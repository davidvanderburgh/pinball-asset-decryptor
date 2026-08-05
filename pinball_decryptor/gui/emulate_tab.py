"""Emulate tab — run the Stern Spike 2 game on this PC and watch its health.

The emulator itself is not part of PAD.  It is a rig of shell scripts, an
``LD_PRELOAD`` hardware shim and a native GL host that live outside the repo
(``c:\\tmp\\spike2_emu`` by default, ``PAD_EMU_DIR`` to move it) and run inside
WSL.  This panel is a *control surface* for that rig: start it, stop it, and say
truthfully what it is doing.  It deliberately does not reimplement any of it.

Three things about it are worth knowing before changing anything here:

* **It runs a card image, and only a card image.**  The image is mounted READ
  ONLY and run in place: nothing is extracted, and nothing can write to it.  The
  two buttons pick which of the project's images to run — the one Extract was
  pointed at, or the one Write builds — so this tab acts on the same files as
  the rest of the app instead of contradicting it.

  Two other sources were offered briefly and both were wrong.  An "extracted
  folder" cannot work: PAD extracts ASSETS, and the rig needs a title directory
  (a ``game`` binary with ``assets/`` and the node ``.hex`` files beside it),
  which is a different shape — pointing it at an extract folder could only fail.
  A "rig's own copy" option exposed whatever happened to be unpacked inside the
  rig on this machine, which is internal state no user can create or reason
  about.

* **It runs as the normal WSL user, not root.**  ``core.executor`` invokes
  ``wsl -u root``; the rig's scripts assume ``/home/david`` and a user-owned
  X11/PulseAudio session, so root would break WSLg and the audio path.  That is
  why this module calls ``wsl.exe`` directly instead of reusing the executor.

* **Stopping must be verified, never assumed.**  An orphaned guest spins at
  ~140% CPU forever and ignores polite signals, so Stop runs the rig's own
  ``killgame.sh`` (SIGKILL for all five processes) and then re-reads the status
  until it reports zero.  The panel shows the process count for exactly this
  reason.
"""

import os
import pathlib
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

#: The rig ships in the repo, next to this package, rather than in the temp
#: directory it was developed in - so it survives a reboot and there is exactly
#: one copy of it.  Resolved from this file so a checkout anywhere works.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "spike2_emu"
)

#: How the rig's ``state=`` word is shown to a human.  ``techalerts`` is not a
#: fault: the game boots to its Tech Alerts screen and waits there for an
#: operator, exactly as the real machine does.  Reading that as "stuck" cost a
#: whole pass of this project, so the wording here is deliberate.
_STATE_TEXT = {
    "off": ("Not running", ""),
    "booting": ("Starting…", "Loading scenes and bringing up the node bus."),
    "techalerts": ("Waiting at Tech Alerts",
                   "Press a switch in the game window to carry on — this is "
                   "what the real machine does, not a fault."),
    "running": ("Running", "Attract mode or the operator menu."),
}

#: Replaces the Tech Alerts hint while the rig's own auto-advance helper is
#: still working.  The default hint tells the user to press something; saying
#: that while something else is already pressing invites two operators fighting
#: over the same screen.
_ADVANCING_HINT = ("Skipping to attract mode on its own — it waits for the "
                   "node bus to finish bringing up, then presses Service Back "
                   "once. Untick “Skip to attract mode” to do it by hand.")


def rig_dir():
    """Where the emulator rig lives.  Overridable so this is not welded to one
    machine's scratch directory."""
    return os.environ.get("PAD_EMU_DIR", DEFAULT_RIG_DIR)


def rig_available():
    """Whether the rig is present.  The tab stays visible when it is not and
    explains what is missing, rather than disappearing without a word."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, f))
               for f in ("watch.sh", "killgame.sh", "status.sh"))


def parse_status(text):
    """Parse ``status.sh``'s ``key=value`` output into a dict.

    Split out of the panel so it can be tested without a Tk root — the state
    wording is the part most likely to be got wrong, and it is the part a user
    reads first.
    """
    info = {}
    for line in (text or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            info[key.strip()] = value.strip()
    return info


def state_text(info):
    """(label, hint) for the rig's ``state=`` word.

    ``auto=`` is the number of auto-advance helpers still running, so a
    non-zero value at Tech Alerts means the rig is already dealing with it and
    the user should be told to wait rather than to press something.
    """
    label, hint = _STATE_TEXT.get(info.get("state", "off"),
                                  (info.get("state", ""), ""))
    if info.get("state") == "techalerts" and info.get("auto", "0") != "0":
        return label, _ADVANCING_HINT
    return label, hint


def _wsl_path(win_path):
    """``c:\\repo\\tools\\spike2_emu`` -> ``/mnt/c/repo/tools/spike2_emu``."""
    p = win_path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


class EmulatePanel:
    """The Emulate tab's widgets and its background poller."""

    #: Wall-clock cap handed to ``watch.sh``.  A forgotten window must not be
    #: able to burn a core all night; the rig enforces it, this only chooses it.
    BACKSTOP_MIN = 120

    #: Status poll period.  Each poll is one ``wsl.exe`` round trip, so this is
    #: slow enough to cost nothing and fast enough to feel live.
    POLL_MS = 2000

    def __init__(self, parent, log=None, project_paths=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        # A zero-argument callable returning (original, build) from the rest of
        # the app.  A CALLABLE and not two strings, because both are entry
        # boxes the user edits after this panel is built; reading them at
        # construction time would pin the buttons to whatever was there when
        # the tab was first opened.
        self._project_paths = project_paths
        self._proc = None            # the watch.sh child, while we own one
        # TWO flags, not one.  A single "_busy" covering both was a real bug:
        # the thread that drains watch.sh's output lives for as long as the
        # emulator does, so a shared flag stayed set the whole session and Stop
        # returned immediately without doing anything.  _starting is only true
        # across the launch itself.
        self._starting = False
        self._stopping = False
        self._poll_job = None
        self._stopped = False
        self._logfile = "/home/david/gzpad.log"

    def _timer(self):
        """The widget every ``after`` job on this panel is hung off.

        NOT the tab frame, which is the obvious choice and is wrong.  An
        ``after`` job registers a Tcl command owned by the widget it was
        scheduled on, and the tab frame is destroyed in the middle of the
        ``root.destroy()`` cascade - cancelling a job on a widget that is
        itself being torn down raises ``can't delete Tcl command``, which
        showed up as four errors in the GUI smoke test and is not visible in
        normal use because the app is normally alive when a poll fires.  The
        toplevel outlives every tab, so a cancel from the frame's ``<Destroy>``
        handler always lands on a live widget.
        """
        return self._parent.winfo_toplevel()

    def _log(self, msg):
        """Log from ANY thread.  ``append_log`` writes into a Tk Text widget and
        Tk is not thread safe, so the two places this is called from - the
        watch.sh output drain and the stop worker - must hand it back to the
        main loop.  Calling it directly is the bug that froze the Partition
        Explorer's extract."""
        try:
            self._timer().after(0, lambda: self._log_sink(msg))
        except (tk.TclError, RuntimeError):
            pass    # main loop gone; nothing to log into

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        pad = {"padx": 10, "pady": 4}

        intro = ttk.Label(
            frame, justify=tk.LEFT, wraplength=820,
            text=("Runs a real Stern Spike 2 game binary on this PC under "
                  "emulation, in its own window, with sound.\n"
                  "Pick a card image and it runs straight off it — nothing is "
                  "extracted and the image is opened read only."))
        intro.pack(anchor=tk.W, **pad)

        self._build_source(frame, pad)

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, **pad)
        self._start_btn = ttk.Button(btns, text="Start emulator",
                                     command=self.start)
        self._start_btn.pack(side=tk.LEFT)
        self._stop_btn = ttk.Button(btns, text="Stop", command=self.stop,
                                    state=tk.DISABLED)
        self._stop_btn.pack(side=tk.LEFT, padx=(6, 0))

        # BOTH tickboxes are read ONCE, when Start builds the environment for
        # watch.sh, so they are start-time options and not live controls.  They
        # are therefore disabled while the emulator is up: leaving them
        # clickable invites unticking one mid-run and concluding the option is
        # broken when nothing happens, which is exactly what a tester reported.
        self._audio_var = tk.BooleanVar(value=True)
        self._audio_chk = ttk.Checkbutton(btns, text="Sound",
                                          variable=self._audio_var)
        self._audio_chk.pack(side=tk.LEFT, padx=(16, 0))

        # On by default: the game boots to Tech Alerts and waits for an
        # operator, which means sitting through ~15 s of bring-up and then
        # pressing Escape twice, every single start.  There is no state to save
        # instead — see autoattract.sh for why NVRAM is not the lever.
        self._auto_var = tk.BooleanVar(value=True)
        self._auto_chk = ttk.Checkbutton(btns, text="Skip to attract mode",
                                         variable=self._auto_var)
        self._auto_chk.pack(side=tk.LEFT, padx=(12, 0))

        grid = ttk.LabelFrame(frame, text="Status")
        grid.pack(fill=tk.X, **pad)
        self._vals = {}
        rows = [
            ("state", "State:"),
            ("procs", "Processes:"),
            ("cpu", "Game CPU / memory:"),
            ("host", "Renderer:"),
            ("audio", "Audio:"),
        ]
        for r, (key, label) in enumerate(rows):
            ttk.Label(grid, text=label, width=22, anchor=tk.W).grid(
                row=r, column=0, sticky=tk.W, padx=8, pady=2)
            v = ttk.Label(grid, text="—", anchor=tk.W)
            v.grid(row=r, column=1, sticky=tk.W, padx=4, pady=2)
            self._vals[key] = v
        grid.columnconfigure(1, weight=1)

        self._hint = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                               foreground="#888", text="")
        self._hint.pack(anchor=tk.W, **pad)

        # The key list that used to be here is gone. The rig opens its own
        # Controls window listing every binding, and it is generated from the
        # bindings themselves rather than typed out - so a copy on this tab was
        # a second source of truth that could only ever drift out of date.

        if not rig_available():
            self._start_btn.configure(state=tk.DISABLED)
            self._hint.configure(
                text=("The emulator rig was not found in %s.\n"
                      "It is not part of this repository; set PAD_EMU_DIR to "
                      "point at it." % rig_dir()))
        # The poll re-arms itself forever, so it MUST be cancelled when the tab
        # goes away.  A pending `after` job outliving its widgets is what makes
        # Tk raise "can't delete Tcl command" during teardown - it showed up
        # immediately as an error in the GUI smoke test.
        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._schedule_poll()

    def _build_source(self, frame, pad):
        """The card image to run.  One box, because there is only one thing the
        rig can be pointed at that a user of this app actually has.

        AN EXTRACTED FOLDER IS NOT AN OPTION, and offering it was a mistake: PAD
        extracts ASSETS, and the rig needs a title directory - a ``game`` binary
        with ``assets/`` and the node ``.hex`` files beside it.  They are not the
        same shape, so picking an extract folder here could only ever fail, and
        it did.  A card image is mounted read only and run in place, so there is
        nothing to prepare either way.

        The two buttons pick which of the project's images to run: the one
        Extract was pointed at (stock) or the one Write builds (the mod).  Which
        of those you want is a decision, not something to guess, so both are
        offered and neither is forced.
        """
        box = ttk.LabelFrame(frame, text="Card image to run")
        box.pack(fill=tk.X, **pad)

        self._src_path = tk.StringVar()

        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=8, pady=(6, 2))
        self._src_entry = ttk.Entry(row, textvariable=self._src_path)
        self._src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse…", width=10,
                   command=self._browse).pack(side=tk.LEFT, padx=(6, 0))

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, padx=8, pady=(2, 6))
        self._orig_btn = ttk.Button(row2, text="Use stock image",
                                    command=lambda: self._use_project(0))
        self._orig_btn.pack(side=tk.LEFT)
        self._build_btn = ttk.Button(row2, text="Use modded image",
                                     command=lambda: self._use_project(1))
        self._build_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._src_note = ttk.Label(row2, foreground="#888", text="")
        self._src_note.pack(side=tk.LEFT, padx=(12, 0))

        self._sync_source()

    def _project_pair(self):
        """(stock, modded) from the rest of the app, each possibly blank."""
        if not self._project_paths:
            return "", ""
        try:
            a, b = self._project_paths()
        except Exception:                               # noqa: BLE001
            return "", ""
        return (a or ""), (b or "")

    def _sync_source(self):
        """Offer only the project images that exist, and start from the stock
        one so Start works without a decision on the common path."""
        stock, mod = self._project_pair()
        self._orig_btn.configure(state=tk.NORMAL if stock else tk.DISABLED)
        self._build_btn.configure(state=tk.NORMAL if mod else tk.DISABLED)
        if not self._src_path.get().strip() and stock:
            self._src_path.set(stock)
        if not (stock or mod) and not self._src_path.get().strip():
            self._src_note.configure(
                text="no image loaded on the Extract or Write tab yet")
        else:
            self._src_note.configure(text="")

    def _use_project(self, which):
        path = self._project_pair()[which]
        if path:
            self._src_path.set(path)
            self._sync_source()

    def _browse(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Pick a Spike 2 card image",
            filetypes=[("Card images", "*.raw *.img"), ("All files", "*.*")])
        if path:
            self._src_path.set(path)

    def _source_env(self):
        """The environment for watch.sh, or None with a reason already shown.

        Validated HERE rather than in the rig: a bad path should be a sentence
        on the tab, not a shell script exiting into the log pane.
        """
        path = self._src_path.get().strip().strip('"')
        if not path:
            self._hint.configure(
                text="Pick a card image first — the one on the Extract tab, the "
                     "one Write builds, or any other Spike 2 card.")
            return None
        if not os.path.isfile(path):
            self._hint.configure(text="No such image: %s" % path)
            return None
        return ["PAD_CARD=%s" % _wsl_path(path)]

    def _on_destroy(self, event=None):
        # <Destroy> fires for every descendant too; only the frame itself means
        # the tab is really going.  Compared by widget path rather than by
        # identity so this still holds if tkinter ever hands the callback a bare
        # Tcl name instead of a resolved widget.
        if event is not None and str(event.widget) != str(self._parent):
            return
        self._stopped = True
        if self._poll_job is not None:
            try:
                self._timer().after_cancel(self._poll_job)
            except (tk.TclError, ValueError):
                pass
            self._poll_job = None

    # ------------------------------------------------------------------
    # start / stop
    # ------------------------------------------------------------------

    def start(self):
        if self._starting or self._stopping or not rig_available():
            return
        self._starting = True
        self._start_btn.configure(state=tk.DISABLED)
        self._set("state", "Starting…")
        d = _wsl_path(rig_dir())
        # Validate the source BEFORE anything is launched, and put the reason
        # on the tab.  A bad path reaching the rig becomes a shell error in the
        # log pane, which is the wrong place to read it.
        src = self._source_env()
        if src is None:
            self._starting = False
            self._start_btn.configure(state=tk.NORMAL)
            self._set("state", "Not running")
            return
        env = ["LOG=%s" % self._logfile, "PAD_AUDIO_DUMP=30"] + src
        if not self._audio_var.get():
            env.append("PAD_AUDIO=0")
        if not self._auto_var.get():
            env.append("PAD_AUTO_ATTRACT=0")
        cmd = (["wsl.exe", "-e", "env"] + env
               + ["bash", "%s/watch.sh" % d, str(self.BACKSTOP_MIN)])
        self._log("[emulate] %s" % " ".join(cmd))

        def run():
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=_CREATE_FLAGS)
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] failed to start: %s" % exc)
                self._proc = None
                self._starting = False
                return
            # Launched.  Clear _starting HERE, not when the process ends: this
            # thread now lives for the whole session draining output, and
            # holding a flag across it is what stopped Stop from working.
            self._starting = False
            try:
                # Drain so the pipe cannot fill and block the rig; the rig keeps
                # its own log, this is only for PAD's log pane.
                for line in self._proc.stdout:
                    self._log("[emulate] " + line.decode("utf-8", "replace")
                              .rstrip())
            except Exception:                           # noqa: BLE001
                pass                                    # pipe closed under us
            finally:
                self._proc = None

        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        """Kill everything and VERIFY.  Never assume: the rig's own killgame.sh
        SIGKILLs all five processes and reports what survived."""
        if self._stopping:
            return
        self._stopping = True
        self._stop_btn.configure(state=tk.DISABLED)
        self._set("state", "Stopping…")
        d = _wsl_path(rig_dir())

        def run():
            try:
                out = subprocess.run(
                    ["wsl.exe", "-e", "bash", "%s/killgame.sh" % d],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=60, creationflags=_CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    self._log("[emulate] " + line)
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] stop failed: %s" % exc)
            # watch.sh is still sitting in its own poll loop; it notices the
            # renderer has gone and runs its teardown (which also removes the
            # audio fifo). Wait briefly for that rather than racing it.
            proc = self._proc
            if proc is not None:
                try:
                    proc.wait(timeout=20)
                except Exception:                       # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:                   # noqa: BLE001
                        pass
            self._stopping = False

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # status polling
    # ------------------------------------------------------------------

    def _schedule_poll(self):
        if self._stopped:
            return
        try:
            self._poll_job = self._timer().after(self.POLL_MS, self._poll)
        except tk.TclError:
            self._stopped = True

    def _poll(self):
        self._poll_job = None
        if self._stopped:
            return
        if not rig_available():
            self._schedule_poll()
            return
        d = _wsl_path(rig_dir())

        def run():
            try:
                out = subprocess.run(
                    ["wsl.exe", "-e", "bash", "%s/status.sh" % d,
                     self._logfile],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=20, creationflags=_CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                            # noqa: BLE001
                text = ""
            info = parse_status(text)
            # Tk is not thread safe — every widget touch goes back to the main
            # loop.  Doing it from the worker is the exact bug that froze the
            # Partition Explorer's extract.
            if self._stopped:
                return
            try:
                self._timer().after(0, lambda: self._apply(info))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=run, daemon=True).start()
        self._schedule_poll()

    def _apply(self, info):
        try:
            label, hint = state_text(info)
            self._set("state", label)
            self._hint.configure(text=hint)

            procs = info.get("procs", "0")
            self._set("procs", "%s running%s" % (
                procs, "  (all stopped)" if procs == "0" else ""))

            if info.get("running") == "1":
                self._set("cpu", "%s%% of one core, %s MB"
                          % (info.get("cpu", "?"), info.get("rss", "?")))
                self._set("host", "%s%% CPU, %s fps"
                          % (info.get("host_cpu", "?"), info.get("fps", "—")))
                pcm = info.get("pcm")
                if pcm is None:
                    self._set("audio", "not sampled")
                else:
                    drop = info.get("drop", "0")
                    self._set("audio", "%s frames played, %s dropped%s" % (
                        pcm, drop,
                        "" if drop == "0" else "   <-- dropping"))
            else:
                for k in ("cpu", "host", "audio"):
                    self._set(k, "—")

            busy = self._starting or self._stopping
            up = info.get("running") == "1" or procs != "0"
            self._start_btn.configure(
                state=tk.DISABLED if (up or busy) else tk.NORMAL)
            self._stop_btn.configure(
                state=tk.NORMAL if (up and not self._stopping) else tk.DISABLED)
            # Start-time options: they follow the Start button, because that is
            # the only moment they are read.
            opts = tk.DISABLED if (up or busy) else tk.NORMAL
            self._audio_chk.configure(state=opts)
            self._auto_chk.configure(state=opts)
        except tk.TclError:
            pass        # the tab went away between the poll and its result

    def _set(self, key, text):
        try:
            self._vals[key].configure(text=text)
        except (KeyError, tk.TclError):
            pass
