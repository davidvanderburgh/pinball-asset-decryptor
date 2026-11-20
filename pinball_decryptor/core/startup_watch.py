"""A start-up that does not finish: say where it waits, and rescue a stuck WSL.

PAD-1474: on a PC whose WSL had stopped answering, a double-click started the
app and then nothing showed until the user ended WSL in Task Manager; the
moment WSL went, the app came up.  Something the app does while it builds
itself waited on WSL, and a start-up has no window yet to say so.

So while the app builds itself (webui/host.build) this watches the clock:

* After STALL_S without the app built, every thread's stack goes to a file in
  the log folder (``faulthandler``, whose own thread writes it even if a call
  into C holds the interpreter), and the app's part of it goes into the
  session log: the next problem report then names the call that waited.
  A dump the app never got to log (it was ended first) is logged by the next
  start, from the file it left behind.
* If WSL is not answering then either, a Yes/No box asks to restart WSL, and
  Yes shuts it down - with ``--force``, and last by ending WSL's service, the
  way Task Manager does, when a plain shutdown gets no answer either.  The
  waiting call then gets its answer (an error) and the start carries on.

Windows only for the WSL half; the stack dump is anywhere.
"""

import faulthandler
import os
import re
import subprocess
import sys
import threading

#: how long the app may take to build itself before it counts as stalled.  A
#: cold start on a slow PC builds in a few seconds; Mike's waited 26 s to
#: forever (PAD-1474)
STALL_S = 20

#: after a No (or a restart that did not free the start), ask again this long
#: later while the start is still stalled and WSL still not answering
ASK_AGAIN_S = 60

#: how long WSL gets to answer ``wsl -l --running`` before it counts as stuck.
#: A healthy WSL answers that from the registry in well under a second, even
#: with its VM still booting
WSL_ANSWER_S = 10

#: the file the stacks are written to, in the session log folder
DUMP_NAME = "startup-stall.txt"
#: ...and what a previous start's unlogged dump is renamed to
LEFT_NAME = "startup-stall-previous.txt"

#: the most stack lines one dump puts in the session log
MAX_LOG_LINES = 60

_NO_WINDOW = 0x08000000                 # CREATE_NO_WINDOW

ASK_TITLE = "Pinball Asset Decryptor"
ASK_TEXT = (
    "Pinball Asset Decryptor is taking a long time to start because WSL "
    "(the Linux it runs its tools in) has stopped answering.\n\n"
    "Restart WSL now? Anything running in WSL is stopped, as ending it in "
    "Task Manager would. The app then carries on starting by itself.")


def _run(argv, timeout):
    kw = {"creationflags": _NO_WINDOW} if sys.platform == "win32" else {}
    return subprocess.run(argv, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, **kw)


def wsl_stuck(run=_run, timeout=WSL_ANSWER_S):
    """True when WSL is there but does not answer within *timeout*.  No WSL
    at all, or one that answers with an error, is not stuck."""
    if sys.platform != "win32":
        return False
    try:
        run(["wsl.exe", "-l", "--running", "-q"], timeout)
    except subprocess.TimeoutExpired:
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def restart_wsl(run=_run, say=lambda text: None):
    """Shut WSL down however it will go: a plain shutdown, then a forced one,
    then ending its service (the app runs as Administrator, which that
    needs).  True once one of them worked."""
    steps = (
        ("shutting WSL down", ["wsl.exe", "--shutdown"], 30),
        ("WSL did not shut down; forcing it",
         ["wsl.exe", "--shutdown", "--force"], 30),
        ("WSL still did not shut down; ending its service",
         ["taskkill", "/f", "/im", "wslservice.exe"], 15),
    )
    for what, argv, timeout in steps:
        say("Start-up: %s." % what)
        try:
            out = run(argv, timeout)
        except subprocess.TimeoutExpired:
            continue
        except (OSError, subprocess.SubprocessError) as e:
            say("Start-up: that did not run (%s)." % e)
            continue
        if out.returncode == 0:
            say("Start-up: WSL is down; it starts again by itself when the "
                "app needs it.")
            return True
    say("Start-up: WSL could not be restarted. Restarting Windows clears it.")
    return False


def ask_restart(text=ASK_TEXT, title=ASK_TITLE):
    """A native Yes/No box on top of everything (there is no app window yet).
    True for Yes."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        # MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST
        flags = 0x4 | 0x30 | 0x10000 | 0x40000
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags) == 6
    except Exception:                                   # noqa: BLE001
        return False


def close_ask(title=ASK_TITLE):
    """Answer No for the user on this process's open box (the start finished
    by itself while it was up)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        me = os.getpid()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(h, _):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == me:
                cls = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(h, cls, 64)
                text = ctypes.create_unicode_buffer(128)
                u.GetWindowTextW(h, text, 128)
                if cls.value == "#32770" and text.value == title:
                    u.PostMessageW(h, 0x0111, 7, 0)    # WM_COMMAND, IDNO
            return True
        u.EnumWindows(each, 0)
    except Exception:                                   # noqa: BLE001
        pass


_THREAD = re.compile(r"^(?:Current thread|Thread) 0x[0-9a-fA-F]+"
                     r"(?: \[(?P<name>[^\]]*)\])?")
_FRAME = re.compile(r'^\s+File "(?P<path>[^"]+)", line (?P<line>\d+) in '
                    r'(?P<func>\S+)')


def _short(path):
    """A frame's file without the folders above the app (they hold the
    account name): ``pinball_decryptor/core/x.py``, else the bare name."""
    p = path.replace("\\", "/")
    i = p.rfind("/pinball_decryptor/")
    if i >= 0:
        return p[i + 1:]
    return p.rsplit("/", 1)[-1]


def summarize(text, max_lines=MAX_LOG_LINES):
    """The lines of a ``faulthandler`` dump worth a log: one per thread that
    is inside the app's code, naming the thread, then its innermost frames
    down to the app's own.  Threads idling in the standard library only
    (pools, the server) are left out."""
    threads = []
    cur = None
    for line in text.splitlines():
        m = _THREAD.match(line)
        if m:
            cur = {"name": m.group("name") or "main", "frames": []}
            threads.append(cur)
            continue
        m = _FRAME.match(line)
        if m and cur is not None:
            cur["frames"].append((_short(m.group("path")), m.group("line"),
                                  m.group("func"),
                                  "pinball_decryptor" in m.group("path")))
    out = []
    for t in threads:
        frames = t["frames"]
        mine = [i for i, f in enumerate(frames) if f[3]]
        if not mine:
            continue
        # innermost first: what it waits in, down to the first app frames
        keep = frames[:mine[0] + 3]
        out.append("  thread %s:" % t["name"])
        for path, line, func, _ in keep:
            out.append("    %s:%s %s" % (path, line, func))
    if len(out) > max_lines:
        out = out[:max_lines] + ["    ... (more in %s)" % DUMP_NAME]
    return out


class StartupWatch:
    """Started before the app builds itself, :meth:`done` once it has.

    *say* writes a line to the session log; the rest are seams for tests."""

    def __init__(self, log_dir, say, stall_s=STALL_S, ask_again_s=ASK_AGAIN_S,
                 stuck=wsl_stuck, ask=ask_restart, restart=restart_wsl,
                 close=close_ask):
        self.log_dir = log_dir
        self.say = say
        self.stall_s = stall_s
        self.ask_again_s = ask_again_s
        self.stuck = stuck
        self.ask = ask
        self.restart = restart
        self.close = close
        self._asking = False
        self._done = threading.Event()
        self._fh = None
        self.stalled = False
        self._logged = False
        self._log_lock = threading.Lock()
        self.dump_path = os.path.join(log_dir, DUMP_NAME)
        self.left_path = os.path.join(log_dir, LEFT_NAME)

    # -- the clock ------------------------------------------------------
    def start(self):
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            if os.path.isfile(self.dump_path):
                # a start that stalled and was ended before it logged this
                os.replace(self.dump_path, self.left_path)
            self._fh = open(self.dump_path, "w", encoding="utf-8")
            faulthandler.dump_traceback_later(self.stall_s, repeat=False,
                                              file=self._fh, exit=False)
        except Exception:                               # noqa: BLE001
            self._fh = None
        threading.Thread(target=self._watch, name="pad-startup-watch",
                         daemon=True).start()
        return self

    def done(self):
        """The app is built: stop the clock, and log a dump an earlier start
        left behind."""
        if self._done.is_set():
            return
        self._done.set()
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:                               # noqa: BLE001
            pass
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
        if self._asking:
            self.close()
        if self.stalled:
            self._log_stall()           # if the watch had not got to it
        _remove(self.dump_path)
        self._log_left_behind()

    # -- what a stall does -------------------------------------------------
    def _watch(self):
        if self._done.wait(self.stall_s):
            return
        self.stalled = True
        self._done.wait(0.5)                # faulthandler's write lands first
        self._log_stall()
        while not self._done.is_set():
            if not self.stuck():
                return
            if self._done.is_set():
                return
            self.say("Start-up: WSL is not answering, which is what the app "
                     "is waiting on.")
            self._asking = True
            try:
                # done() sets its flag, then looks at _asking: one of the
                # two always sees the other, so no box outlives the start
                yes = False if self._done.is_set() else self.ask()
            finally:
                self._asking = False
            if self._done.is_set():
                self.say("Start-up: it went on by itself; WSL left as it is.")
                return
            if yes:
                self.restart(say=self.say)
            else:
                self.say("Start-up: WSL left as it is; still waiting for it.")
            if self._done.wait(self.ask_again_s):
                return

    def _log_stall(self):
        with self._log_lock:
            if self._logged:
                return
            self._logged = True
            self._log_dump(self.dump_path,
                           "Start-up has taken over %d s and is still "
                           "waiting. Where it waits:" % self.stall_s)

    def _log_dump(self, path, head):
        try:
            if self._fh is not None and path == self.dump_path:
                self._fh.flush()
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return False
        lines = summarize(text)
        if not lines:
            return False
        self.say(head)
        for line in lines:
            self.say(line)
        return True

    def _log_left_behind(self):
        if not os.path.isfile(self.left_path):
            return
        self._log_dump(self.left_path,
                       "The last start of the app stalled and was ended "
                       "before it got going. Where it waited:")
        _remove(self.left_path)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
