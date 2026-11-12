"""Root for a whole run on a Linux desktop, asked for ONCE (PAD-1173).

A JJP extract or write is root from end to end: it loop-mounts the .iso and the
game image, bind-mounts /dev into a chroot, starts the dongle daemon there and
unmounts it all again - several hundred separate commands.  The JJP, Spooky and
BoF Linux executors sent each one as ``sudo bash -c``, which works in a terminal
(sudo asks there once and remembers) and fails every time from a desktop
launcher: a GUI has no terminal for sudo to ask on.  Asking through pkexec per
command, as the Stern card grow does for its one script (PAD-1172), would mean
hundreds of password dialogs.

So a run that needs root starts ONE root shell through pkexec (the desktop's own
password dialog), the first time it needs it, and sends every command to that
shell; the shell ends when the run is done (:meth:`RootSession.close`), when the
app exits (its stdin closes), or when the session object is dropped.

How the shell runs a command: the request (``run``/``merge``, a random job id,
the command) arrives NUL-separated on its stdin; it starts ``setsid bash -c``
for it in the background, with stdout/stderr in files in its OWN directory
(root's, mode 711, under a random name; the job dir name is a 128-bit random id
too), and prints ``done <id> <rc>`` when it ends.  The app reads the files.
Nothing root writes is in a directory the user can write to, so no symlink can
point a root write somewhere else.  Several commands may run at once (each has
its own id), and a command is stopped by killing its process group.

:func:`route` says how root is had at all: already root, sudo with no password
(both keep the old per-command prefix), pkexec (this session), sudo on a
terminal (the old per-command prefix, which prompts there once), or nothing.
"""

import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import weakref

# How long a person gets to answer the password dialog before the run gives up.
PROMPT_WAIT_S = 600

#: what is said when there is no way to become root here
NO_ROOT = ("this step needs root (it mounts the game image as a disk) and "
           "there is no way to ask for it here: install polkit's pkexec "
           "(package 'polkitd' / 'policykit-1' / 'polkit') so the app can "
           "show your desktop's password prompt, or start the app as root")

_SHELL = r'''
set -u
umask 022
cd / || exit 1
D=$(mktemp -d /tmp/pad-root.XXXXXXXXXX) || exit 1
chmod 711 "$D" || exit 1
stop_all() {
  for p in "$D"/*/pid; do
    [ -f "$p" ] && kill -TERM -- "-$(cat "$p")" 2>/dev/null
  done
  rm -rf "$D"
}
trap stop_all EXIT
trap 'exit 0' TERM HUP INT
printf 'dir %s\n' "$D"
while IFS= read -r -d '' op && IFS= read -r -d '' id; do
  case "$id" in ''|*[!0-9a-f]*) continue ;; esac
  J="$D/$id"
  case "$op" in
    run|merge)
      IFS= read -r -d '' cmd || break
      if ! mkdir -m 711 "$J"; then printf 'done %s 125\n' "$id"; continue; fi
      (
        if [ "$op" = merge ]; then
          setsid bash -c "$cmd" </dev/null >"$J/out" 2>&1 &
        else
          setsid bash -c "$cmd" </dev/null >"$J/out" 2>"$J/err" &
        fi
        echo "$!" >"$J/pid"
        wait "$!"
        printf 'done %s %s\n' "$id" "$?"
      ) </dev/null 2>/dev/null &
      ;;
    kill) [ -f "$J/pid" ] && kill -TERM -- "-$(cat "$J/pid")" 2>/dev/null ;;
    forget) rm -rf "$J" ;;
  esac
done
'''


class RootError(Exception):
    """The root shell could not be had, or it stopped; *rc* as pkexec gave it."""

    def __init__(self, message, rc=1):
        self.rc = rc
        super().__init__(message)


class RootTimeout(Exception):
    """A command in the root shell ran past its timeout (and was stopped)."""


def _is_root():
    return hasattr(os, "getuid") and os.getuid() == 0


def passwordless_sudo():
    """sudo runs a command with no password asked - asked once a process,
    sharing the core executor's answer (PAD-314)."""
    from .executor import NativeExecutor, _passwordless_sudo
    if NativeExecutor._sudo_ok is None:
        NativeExecutor._sudo_ok = _passwordless_sudo()
    return bool(NativeExecutor._sudo_ok)


def _has_desktop():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _on_terminal():
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (ValueError, OSError):
        return False


def route():
    """How a command that needs root gets it here: ``"root"``, ``"sudo"``
    (sudo asks no password), ``"pkexec"`` (one :class:`RootSession`),
    ``"sudo-tty"`` (sudo asks on the terminal this app was started from, as it
    always did), or ``None``."""
    if _is_root():
        return "root"
    if passwordless_sudo():
        return "sudo"
    pk = shutil.which("pkexec")
    if pk and _has_desktop():
        return "pkexec"
    if _on_terminal() and shutil.which("sudo"):
        return "sudo-tty"
    return "pkexec" if pk else None


def describe(r=None):
    """One line for a prerequisite list: how root will be had (no prompt)."""
    r = route() if r is None else r
    return {
        "root": "Native Linux (running as root)",
        "sudo": "Native Linux (root via sudo)",
        "pkexec": ("Native Linux (asks for your password once per run, "
                   "with your desktop's password prompt)"),
        "sudo-tty": ("Native Linux (sudo asks for your password in the "
                     "terminal this app was started from)"),
    }.get(r, "Native Linux, but " + NO_ROOT)


def user_env():
    """The process environment with /usr/sbin and /sbin on the end of PATH
    (Debian keeps e2fsprogs there, off a user's PATH; PAD-571)."""
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((env.get("PATH", ""), "/usr/sbin", "/sbin"))
    return env


def _pkexec_error(rc, text):
    from .elevated_flash import _pkexec_declined, _pkexec_explained
    if _pkexec_declined(rc, text):
        return "the password prompt for root was canceled or refused"
    low = (text or "").lower()
    if "authentication agent" in low:
        return _pkexec_explained(text)
    return ("could not get root through pkexec (exit %d)%s"
            % (rc, (": " + text.strip()) if (text or "").strip() else ""))


_NL = re.compile(rb"\r\n|\r|\n")


class RootSession:
    """One root shell, through pkexec, for every root command of a run."""

    def __init__(self, pkexec=None):
        self._pkexec = pkexec or shutil.which("pkexec")
        self._proc = None
        self._dir = None
        self._done = {}
        self._dead = None            # why the shell is gone, once it is
        self._err_tail = b""
        self._cond = threading.Condition()
        self._wlock = threading.Lock()
        self._start_lock = threading.Lock()
        self._streams = set()
        self._refused = None         # a refusal holds until close(): the
        #                              cleanup after it must not ask again
        self.starts = 0              # how many times a password was asked

    # -- the shell -------------------------------------------------------
    def _ensure(self):
        with self._start_lock:
            if self._proc is not None and self._dead is None:
                return
            if self._refused is not None:
                raise self._refused
            if not self._pkexec:
                raise RootError(NO_ROOT)
            try:
                self._start()
            except RootError as e:
                self._refused = e
                raise

    def _start(self):
        self._done, self._dead, self._dir = {}, None, None
        self._err_tail = b""
        proc = subprocess.Popen(
            [self._pkexec, "--disable-internal-agent",
             "bash", "-c", _SHELL, "pad-root"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            # not the app's own cwd: from an AppImage that is its FUSE
            # mount, which root cannot enter (PAD-1188)
            cwd="/")
        self._proc = proc
        self.starts += 1
        threading.Thread(target=self._read_out, args=(proc,),
                         daemon=True).start()
        self._err_thread = threading.Thread(target=self._read_err,
                                            args=(proc,), daemon=True)
        self._err_thread.start()
        weakref.finalize(self, _close_pipe, proc)
        deadline = time.monotonic() + PROMPT_WAIT_S
        with self._cond:
            while self._dir is None and self._dead is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(min(left, 1.0))
        if self._dir is None:
            if self._dead is None:
                proc.kill()     # still our pkexec: nobody answered
                proc.wait()
                self._dead = "nobody answered the password prompt"
                raise RootError("the password prompt for root was not "
                                "answered in %d minutes"
                                % (PROMPT_WAIT_S // 60))
            rc = proc.wait()
            self._err_thread.join(5)
            text = self._err_tail.decode("utf-8", "replace")
            self._proc = None
            raise RootError(_pkexec_error(rc, text), rc)

    def _read_out(self, proc):
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            with self._cond:
                if line.startswith("dir ") and self._dir is None:
                    self._dir = line[4:]
                elif line.startswith("done "):
                    parts = line.split()
                    if len(parts) == 3:
                        try:
                            self._done[parts[1]] = int(parts[2])
                        except ValueError:
                            self._done[parts[1]] = -1
                self._cond.notify_all()
        with self._cond:
            if self._dead is None:
                self._dead = "the root shell stopped"
            self._cond.notify_all()

    def _read_err(self, proc):
        for raw in iter(proc.stderr.readline, b""):
            self._err_tail = (self._err_tail + raw)[-4000:]

    def _send(self, *fields):
        data = b"".join(f.encode("utf-8") + b"\0" for f in fields)
        with self._wlock:
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except (OSError, ValueError, AttributeError) as e:
                raise RootError("the root shell stopped: %s" % e) from e

    def _start_job(self, cmd, merge):
        self._ensure()
        if "\0" in cmd:
            raise ValueError("a command cannot hold a NUL byte")
        jid = secrets.token_hex(16)
        self._send("merge" if merge else "run", jid, cmd)
        return jid

    def _wait(self, jid, timeout):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while jid not in self._done and self._dead is None:
                left = None if deadline is None else deadline - time.monotonic()
                if left is not None and left <= 0:
                    return None
                self._cond.wait(0.5 if left is None else min(left, 0.5))
            return self._done.get(jid)

    def _stop_job(self, jid):
        try:
            self._send("kill", jid)
        except RootError:
            return
        self._wait(jid, 10)

    def _forget(self, jid):
        with self._cond:
            self._done.pop(jid, None)
        try:
            self._send("forget", jid)
        except RootError:
            pass

    def _read(self, jid, name):
        try:
            with open(os.path.join(self._dir, jid, name), "rb") as f:
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _gone(self):
        text = self._err_tail.decode("utf-8", "replace").strip()
        return RootError((self._dead or "the root shell stopped")
                         + ((": " + text) if text else ""))

    # -- what the executors call ----------------------------------------
    def run(self, cmd, timeout=120):
        """Run *cmd* as root: ``(rc, stdout, stderr)``.  Raises
        :class:`RootTimeout` past *timeout* (the command is stopped first) and
        :class:`RootError` when root could not be had."""
        jid = self._start_job(cmd, merge=False)
        try:
            rc = self._wait(jid, timeout)
            if rc is None:
                if self._dead is not None:
                    raise self._gone()
                self._stop_job(jid)
                raise RootTimeout(timeout)
            return rc, self._read(jid, "out"), self._read(jid, "err")
        finally:
            self._forget(jid)

    def stream(self, cmd, timeout=600):
        """Run *cmd* as root with stderr merged into stdout, yielding its lines
        as they come (``\\r`` ends a line too, like a text-mode pipe).  The
        generator's return value is the exit code."""
        jid = self._start_job(cmd, merge=True)
        with self._cond:
            self._streams.add(jid)
        deadline = time.monotonic() + timeout
        path = os.path.join(self._dir, jid, "out")
        f, buf = None, b""
        try:
            while True:
                with self._cond:
                    finished = jid in self._done
                    dead = self._dead
                if f is None:
                    try:
                        f = open(path, "rb")
                    except OSError:
                        f = None
                chunk = f.read(65536) if f else b""
                if chunk:
                    buf += chunk
                    # a \r last is held back: the \n of a \r\n may be next
                    hold = b"\r" if buf.endswith(b"\r") else b""
                    parts = _NL.split(buf[:len(buf) - len(hold)])
                    buf = parts.pop() + hold
                    for p in parts:
                        yield p.decode("utf-8", "replace")
                    continue
                if finished:
                    break
                if dead is not None:
                    raise self._gone()
                if time.monotonic() > deadline:
                    self._stop_job(jid)
                    raise RootTimeout(timeout)
                with self._cond:
                    self._cond.wait(0.05)
            tail = buf.rstrip(b"\r")
            if tail:
                yield tail.decode("utf-8", "replace")
            with self._cond:
                return self._done.get(jid, -1)
        finally:
            if f:
                f.close()
            with self._cond:
                self._streams.discard(jid)
            self._forget(jid)

    def kill_streams(self):
        """Stop every streaming command (what ``executor.kill()`` means)."""
        with self._cond:
            jids = list(self._streams)
        for jid in jids:
            try:
                self._send("kill", jid)
            except RootError:
                pass

    @property
    def alive(self):
        return self._proc is not None and self._dead is None

    def close(self):
        """End the root shell (it stops whatever still runs in it)."""
        self._refused = None
        proc, self._proc = self._proc, None
        if proc is None:
            return
        _close_pipe(proc)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass


def _close_pipe(proc):
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except OSError:
        pass


# --------------------------------------------------------------------------
# A host-side ISO mount (Spooky, Pinball Brothers): root for mount + umount.
def mount_iso(image_path, prefix="pad_iso_"):
    """Loop-mount *image_path* read-only on a fresh temp dir:
    ``(mount_point, cleanup)``.  On a desktop the root shell that mounts it
    stays until *cleanup* unmounts it, so that is ONE password prompt."""
    mount_point = tempfile.mkdtemp(prefix=prefix)
    r = route()
    session = None
    mount = "mount -o loop,ro %s %s" % (_q(image_path), _q(mount_point))
    umount = "umount %s" % _q(mount_point)

    def _do(cmd, timeout):
        if session is not None:
            rc, out, err = session.run(cmd, timeout=timeout)
            return rc, (err or "") + (out or "")
        argv = ["bash", "-c", cmd]
        if r in ("sudo", "sudo-tty"):
            argv = ["sudo"] + argv
        res = subprocess.run(argv, capture_output=True, text=True,
                             timeout=timeout)
        return res.returncode, (res.stderr or "") + (res.stdout or "")

    try:
        if r is None:
            raise RuntimeError("mount failed: " + NO_ROOT)
        if r == "pkexec":
            session = RootSession()
        try:
            rc, text = _do(mount, 120)
        except (RootError, RootTimeout, subprocess.TimeoutExpired) as e:
            raise RuntimeError("mount failed: %s" % (
                str(e) if isinstance(e, RootError) else "timed out")) from e
        if rc != 0:
            raise RuntimeError("mount failed: %s" % text.strip())
    except Exception:
        if session is not None:
            session.close()
        try:
            os.rmdir(mount_point)
        except OSError:
            pass
        raise

    def cleanup():
        try:
            _do(umount, 30)
        except Exception:
            pass
        finally:
            if session is not None:
                session.close()
            try:
                os.rmdir(mount_point)
            except OSError:
                pass

    return mount_point, cleanup


def _q(s):
    return "'" + str(s).replace("'", "'\\''") + "'"
