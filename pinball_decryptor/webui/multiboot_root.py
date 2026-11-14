"""Root for the Multi-boot tab's root steps on a Linux desktop (PAD-1188).

A Stern build loop-mounts the card's partitions, a JJP one mounts the ISO, so
those steps run as root.  Windows has ``wsl -u root`` and a Mac the container's
own root user; a Linux desktop had ``sudo -n``, which never asks for a password
- so from a desktop launcher (no terminal) every build failed at once with
"sudo: interactive authentication is required" (sudo-rs's words; classic sudo
says "a password is required").  Brombomb, building a Godzilla two-image card
from the AppImage.

Now a root step gets root the way the JJP extract does (PAD-1173,
:mod:`..core.root_session`): already root, or a sudo that needs no password,
keep the old one-command prefix; a terminal keeps sudo asking there; otherwise
ONE root shell through pkexec - the desktop's own password dialog - asked the
first time a writing run needs root and ended when that run finishes, so a run
with several root steps (a JJP build has five) asks once.  A background preview
never asks: it uses a shell a run already has open, or fails with a sentence.

THE APPIMAGE'S OWN FILES ARE NOT ROOT'S TO READ.  The tools live on the
AppImage's FUSE mount (``/tmp/.mount_XXXX``), made without ``allow_other``, and
that is closed to every other user, root included (PAD-288's flash helper hit
the same wall) - so even a root shell could not ``cd`` there.  A root step
from an AppImage runs from a copy of the bundled ``tools`` and
``pinball_decryptor`` trees in the user's cache instead
(:func:`root_repo_dir`), made once per AppImage build.
"""

import hashlib
import os
import queue
import shlex
import shutil
import sys
import threading

from ..core import root_session

#: A shell line a root step runs, as long as a build may take (an hour-plus
#: card is not unusual); Cancel is the way to stop one early.
STEP_TIMEOUT_S = 24 * 3600

#: What a background preview says when its step needs root and no run has a
#: root shell open - it must never put a password dialog up by itself.
PREVIEW_NO_PROMPT = ("this step needs root, and a preview does not ask for "
                     "your password: Build or Apply asks once, with your "
                     "desktop's password prompt")


class RootLine(list):
    """A root step's argv for the pkexec route: ``["pkexec", <line>]`` so the
    Log's ``$ argv[-1]`` still echoes the shell line, but never run as it is -
    the tab's runner sees the type and sends *line* to the run's root shell
    (:func:`start`)."""

    def __init__(self, line):
        super().__init__(["pkexec", line])
        self.line = line


def _user_home():
    return os.path.expanduser("~")


def linux_argv(line, home=None):
    """The argv that runs shell *line* as root on a Linux desktop, carrying
    the desktop user's HOME (``~/spike2root`` in a build line is the one the
    selector step, run as the user, just filled - root's own is /root, and
    both sudo and pkexec reset it).  Resolved on the worker: the route asks
    ``sudo -n true`` once a process."""
    home = home or _user_home()
    env = ["env", "HOME=" + home] if home else []
    r = root_session.route()
    if r == "root":
        return env + ["bash", "-lc", line]
    if r == "sudo":
        return ["sudo", "-n"] + env + ["bash", "-lc", line]
    if r == "sudo-tty":
        # started from a terminal: sudo asks there, as it always did
        return ["sudo"] + env + ["bash", "-lc", line]
    # pkexec, or no way to root at all (start() says which, at the step)
    rl = RootLine(line)
    rl.cmd = " ".join([shlex.quote(e) for e in env]
                      + ["bash", "-lc", shlex.quote(line)])
    return rl


# --------------------------------------------------------------- the session
_LOCK = threading.Lock()
_SESSION = [None]


def _session(create):
    with _LOCK:
        s = _SESSION[0]
        if s is not None and (s.alive or create):
            return s
        if not create:
            return None
        s = root_session.RootSession()
        _SESSION[0] = s
        return s


def end_run():
    """A writing run is over: end its root shell (and whatever still runs in
    it).  The next run asks again."""
    with _LOCK:
        s, _SESSION[0] = _SESSION[0], None
    if s is not None:
        try:
            s.close()
        except Exception:                               # noqa: BLE001
            pass


class SessionProc:
    """The bit of :class:`subprocess.Popen` the tab's runner uses - ``stdout``
    to iterate (bytes lines), ``wait``, ``poll``, ``kill`` - for one command
    in the root shell.  stderr is merged, as the runner's Popen merges it."""

    def __init__(self, session, cmd, timeout=STEP_TIMEOUT_S, refuse=None):
        self._q = queue.Queue()
        self._session = session
        self._killed = False
        self.returncode = None
        self._done = threading.Event()
        self.stdout = self._lines()
        threading.Thread(target=self._pump, args=(cmd, timeout, refuse),
                         daemon=True).start()

    def _pump(self, cmd, timeout, refuse):
        rc = 1
        try:
            if refuse:
                self._q.put(refuse)
                return
            self._session._ensure()         # the password dialog, if any
            if self._killed:
                self._q.put("canceled before the step started")
                rc = -9
                return
            gen = self._session.stream(cmd, timeout=timeout)
            while True:
                try:
                    line = next(gen)
                except StopIteration as stop:
                    rc = stop.value if stop.value is not None else -1
                    break
                self._q.put(line)
        except root_session.RootTimeout:
            self._q.put("stopped: still running after %d s" % timeout)
            rc = 124
        except root_session.RootError as e:
            self._q.put("root: %s" % e)
            rc = e.rc or 1
        except Exception as e:                          # noqa: BLE001
            self._q.put("root: %s" % e)
            rc = 1
        finally:
            self.returncode = rc
            self._q.put(None)
            self._done.set()

    def _lines(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            yield (item + "\n").encode("utf-8", "replace")

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return self.returncode

    def kill(self):
        """Cancel: stop the command - or, while the password dialog is still
        up, the pkexec asking it, so a password typed after Cancel cannot
        start the build anyway."""
        s = self._session
        if s is None:
            return
        self._killed = True
        if not s.alive:
            p = getattr(s, "_proc", None)
            if p is not None:
                try:
                    p.kill()
                except OSError:
                    pass
            return
        s.kill_streams()

    terminate = kill


def start(argv, preview=False):
    """Start a :class:`RootLine` step: a :class:`SessionProc`.  A writing
    run opens the root shell (the password dialog, once a run); a preview
    only uses one that is open already."""
    cmd = getattr(argv, "cmd", None) or argv.line
    s = _session(create=not preview)
    if s is None:
        return SessionProc(None, cmd, refuse=PREVIEW_NO_PROMPT)
    return SessionProc(s, cmd)      # no pkexec: RootSession says NO_ROOT


def needs_root(fn):
    """Mark a step callable that resolves to a root step, so the run can ask
    for the password before its first step rather than at this one."""
    fn.needs_root = True
    return fn


def wants_root(cmds):
    """The label of a run's first root step, or None."""
    for label, argv in cmds:
        if isinstance(argv, RootLine) or getattr(argv, "needs_root", False):
            return label
    return None


def ask_first():
    """Open the run's root shell NOW, before its first step: the password
    dialog comes up as the user presses Build, not minutes later when the
    long user steps are done and they have walked away (Brombomb, PAD-1188:
    the dialog went unanswered and the build failed).  A :class:`SessionProc`
    running a no-op in the shell (Cancel kills the dialog through it), or
    None when this machine's route asks no password up front (root,
    password-free sudo, sudo on a terminal)."""
    if root_session.route() != "pkexec":
        return None
    return SessionProc(_session(create=True), ":")


# --------------------------------------------------------- the AppImage copy
#: Copied without these: build scratch and host byte-code (the macOS stage's
#: list, multiboot_docker._SKIP).
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "build", "rootfs",
                               "games", ".git")

_STAGED = {}


def _appimage_dir(repo):
    """The AppImage mount *repo* is on, or None when it is not on one (a
    checkout, the Docker image, a root app)."""
    if not sys.platform.startswith("linux"):
        return None
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return None                 # root mounted it, so root can read it
    appdir = os.environ.get("APPDIR")
    if not appdir or not os.environ.get("APPIMAGE"):
        return None
    root = os.path.join(os.path.realpath(appdir), "")
    if not os.path.join(os.path.realpath(repo), "").startswith(root):
        return None
    return appdir


def _cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(_user_home(),
                                                            ".cache")
    return os.path.join(base, "pinball_decryptor", "root-rig")


def _key():
    """One copy per AppImage build: its file's path, size and mtime."""
    img = os.environ.get("APPIMAGE", "")
    try:
        st = os.stat(img)
        sig = "%s|%d|%d" % (img, st.st_size, int(st.st_mtime))
    except OSError:
        sig = img
    return hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:16]


def root_repo_dir(repo):
    """Where a root step must ``cd`` to run the tools in *repo*: *repo*
    itself, or - when it is on the AppImage's FUSE mount, which root cannot
    enter - a copy of its ``tools`` and ``pinball_decryptor`` trees in the
    user's cache.  Made once per AppImage build (the bundle cannot change
    under a running app) and reused; older builds' copies are dropped."""
    if _appimage_dir(repo) is None:
        return repo
    if repo in _STAGED:
        return _STAGED[repo]
    parent = _cache_dir()
    dst = os.path.join(parent, _key())
    done = os.path.join(dst, ".complete")
    if not os.path.isfile(done):
        shutil.rmtree(dst, ignore_errors=True)
        for sub in ("tools", "pinball_decryptor"):
            src = os.path.join(repo, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dst, sub), ignore=_SKIP,
                                symlinks=True, dirs_exist_ok=True)
        with open(done, "w") as f:
            f.write(os.environ.get("APPIMAGE", "") + "\n")
    try:
        for name in os.listdir(parent):
            if name != os.path.basename(dst):
                shutil.rmtree(os.path.join(parent, name), ignore_errors=True)
    except OSError:
        pass
    _STAGED[repo] = dst
    return dst
