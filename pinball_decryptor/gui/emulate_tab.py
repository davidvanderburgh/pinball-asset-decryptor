"""Emulate tab — run the Stern Spike 2 game on this PC and watch its health.

The emulator is a rig of shell scripts, an ``LD_PRELOAD`` hardware shim and a
native GL host, in ``tools/spike2_emu``.  It SHIPS WITH THE APP (this used to
say it lived outside the repo, in ``c:\\tmp\\spike2_emu``, which stopped being
true twice over).  ``PAD_EMU_DIR`` moves it.  This panel is a *control surface*
for that rig: start it, stop it, and say truthfully what it is doing.  It
deliberately does not reimplement any of it.

WHERE IT RUNS.  The rig is a Linux program: the chroot, qemu-user, the node bus
and the GL host have nothing Windows-specific in them.  On a Linux desktop it is
simply run; from Windows it is reached through WSL, and everything that looks
Windows-flavoured in it - the playfield window as a Windows process, the audio
bridge - is a WORKAROUND for what WSL lacks, not a design choice.  ``rig_cmd()``
is the one place that knows which of the two applies.

Three things about it are worth knowing before changing anything here:

* **It runs a card image, and only a card image.**  The image is mounted READ
  ONLY and run in place: nothing is extracted, and nothing can write to it.  The
  user picks the file; whether that is a stock card or their own build is their
  business, and this tab does not guess.

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
from tkinter import messagebox, ttk

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
    "attract": ("In attract mode", "Playing its attract loop, or in the "
                                   "operator menu."),
    # Kept: what status.sh emitted before it learned to say `attract`, so an
    # older rig against a newer app still reads as something rather than as a
    # bare word.  The rename happened because the old word was reached by a
    # test that had quietly stopped working - see gamestate.sh.
    "running": ("Running", "Attract mode or the operator menu."),
}

#: Replaces the Tech Alerts hint while the rig's own auto-advance helper is
#: still working.  The default hint tells the user to press something; saying
#: that while something else is already pressing invites two operators fighting
#: over the same screen.
_ADVANCING_HINT = ("Skipping to attract mode on its own — it waits for the "
                   "node bus to finish bringing up, then presses Service Back "
                   "once. Untick “Skip to attract mode” to do it by hand.")

#: Shown when the auto-advance helper ran out of presses and stopped.  It names
#: the service menu because that is the failure this cannot see: the menu opens
#: no video clip, so from the outside it reads exactly like Tech Alerts.
_GAVEUP_HINT = ("Auto-advance pressed Service Back several times and the "
                "screen did not change. If an earlier press DID take, the game "
                "is probably on the SERVICE MENU, which looks the same from "
                "out here. Click the game window and press Esc: from the menu "
                "it leaves toward attract, from Tech Alerts it clears them.")


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


#: Where Docker Desktop comes from when there is no Homebrew to ask.
DOCKER_URL = "https://www.docker.com/products/docker-desktop/"

#: How long to give the Docker CLI.  ``docker info`` with no daemon behind it
#: answers in about a second; the timeout is only so a wedged socket cannot
#: hang a background probe forever.
_DOCKER_PROBE_S = 12


def docker_state():
    """``ok`` / ``stopped`` / ``absent`` - macOS's answer to "can we emulate?".

    THE EMULATOR NEEDS LINUX, and macOS reaches it through a container (see
    ``rig_cmd``), so Docker is as much a prerequisite there as WSL is on
    Windows.  It was not treated like one: nothing on this tab checked for it,
    the manufacturer's prerequisite list does not carry it, and the only place
    it was ever named was the "rig not found" hint - which a Mac user never
    sees, because the rig SHIPS WITH THE APP and is therefore always found.  So
    the whole of "you need Docker" arrived as one line of padbox.sh's stderr,
    part way down the log pane, after Start appeared to work.

    Three answers rather than two, because the remedies are different: nothing
    installed is a download, and installed-but-not-running is one click.
    """
    try:
        out = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             timeout=_DOCKER_PROBE_S,
                             creationflags=_CREATE_FLAGS)
        return "ok" if out.returncode == 0 else "stopped"
    except FileNotFoundError:
        return "absent"
    except Exception:                                   # noqa: BLE001
        # A timeout is Docker Desktop still waking up, not an absent one.
        return "stopped"


def homebrew():
    """The `brew` binary, or None.  Homebrew installs itself in two places and
    is famously not on a GUI app's inherited PATH, so both are named."""
    for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.isfile(p):
            return p
    return None


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

    ``auto_result=gaveup`` is the case this used to hide.  The helper presses a
    fixed number of times and then exits either way; with only ``auto=`` to go
    on, "finished the job" and "gave up" both showed as the same unchanging
    "Waiting at Tech Alerts", and the two want opposite things from the human.
    """
    label, hint = _STATE_TEXT.get(info.get("state", "off"),
                                  (info.get("state", ""), ""))
    if info.get("state") == "techalerts":
        if info.get("auto", "0") != "0":
            return label, _ADVANCING_HINT
        if info.get("auto_result") == "gaveup":
            return "Stuck at Tech Alerts", _GAVEUP_HINT
    return label, hint


def _wsl_path(win_path):
    """``c:\\repo\\tools\\spike2_emu`` -> ``/mnt/c/repo/tools/spike2_emu``.

    A POSIX path has no drive letter and passes through untouched, so this is
    also correct on a Linux desktop where there is no translation to do.
    """
    p = win_path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def rig_cmd(script, *args, env=()):
    """The command that runs one of the rig's scripts, on THIS platform.

    ONE PLACE THAT KNOWS, because there are six call sites and they were six
    copies of ``["wsl.exe", "-e", "bash", ...]``.  The rig is a Linux program,
    and the three platforms differ only in how Linux is reached:

    ============  ======================================================
    Linux         run it.  Nothing in between.
    Windows       through WSL, which is Linux.
    macOS         in a container, because ``qemu-user`` translates LINUX
                  syscalls and the chroot needs Linux namespaces - so
                  this is not a port that could be written, it is Linux
                  that has to be running somewhere.  ``docker/padbox.sh``
                  owns every detail of that and this only calls it.
    ============  ======================================================

    `env` is a list of ``NAME=value`` strings, applied with ``env`` so the
    values survive the hop without a shell re-parsing them - `wsl.exe` re-parses
    its arguments, and `$var` expands to nothing on that second pass.
    """
    if sys.platform == "darwin":
        # padbox.sh forwards the interesting variables into the container
        # itself, so they are set for IT rather than wrapped around it: `docker
        # run` takes its environment through -e, and an `env` prefix out here
        # would set them on the docker client and nowhere useful.
        box = os.path.join(rig_dir(), "docker", "padbox.sh")
        return ["/usr/bin/env"] + list(env) + ["bash", box, script] + \
               [str(a) for a in args]
    if sys.platform == "win32":
        head = ["wsl.exe", "-e"]
        path = "%s/%s" % (_wsl_path(rig_dir()), script)
    else:
        head = []
        path = os.path.join(rig_dir(), script)
    if env:
        head = head + ["env"] + list(env)
    return head + ["bash", path] + [str(a) for a in args]


class EmulatePanel:
    """The Emulate tab's widgets and its background poller."""

    #: Wall-clock cap handed to ``watch.sh``.  A forgotten window must not be
    #: able to burn a core all night; the rig enforces it, this only chooses it.
    BACKSTOP_MIN = 120

    #: Status poll period.  Each poll is one ``wsl.exe`` round trip, so this is
    #: slow enough to cost nothing and fast enough to feel live.
    POLL_MS = 2000

    def __init__(self, parent, log=None, card_var=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        # The card path lives in a variable the WINDOW owns (when given one):
        # the app persists it into the project anchor and restores it when a
        # project loads, exactly like the Extract/Write path fields. The
        # fallback keeps the panel testable on its own.
        self._card_var = card_var
        self._proc = None            # the watch.sh child, while we own one
        #: Whether the last status poll saw anything running. Read by
        #: shutdown_sync() on app quit: a terminal-started run shows up here
        #: too, and quitting PAD must take the emulator down either way.
        self._last_up = False
        # TWO flags, not one.  A single "_busy" covering both was a real bug:
        # the thread that drains watch.sh's output lives for as long as the
        # emulator does, so a shared flag stayed set the whole session and Stop
        # returned immediately without doing anything.  _starting is only true
        # across the launch itself.
        self._starting = False
        self._stopping = False
        self._resetting = False
        self._poll_job = None
        self._stopped = False
        self._logfile = "/home/david/gzpad.log"
        #: Last answer from docker_state(), macOS only.  None until the first
        #: probe comes back, which is why nothing is claimed before then.
        self._docker = None
        self._docker_busy = False
        self._docker_ticks = 0
        self._docker_result = None

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
        # ONE button, not two.  Start and Stop are never both available - the
        # emulator is either up or it is not - so a pair of buttons meant one of
        # them was always greyed out, and the greyed one still had to be aimed
        # at.  A single button that says what it will do next is the whole
        # control.  _run_label() owns the text and the state; nothing else sets
        # them, so the button cannot drift out of step with the rig.
        self._run_btn = ttk.Button(btns, text="Start emulator",
                                   command=self._toggle, width=16)
        self._run_btn.pack(side=tk.LEFT)

        # The remedy for the faults that are NOT ours and cannot be fixed from
        # inside WSL.  It used to be called "Fix crackly sound", after the only
        # one known at the time; it now covers two, and the one it is reached
        # for most is the second:
        #   * a STRANDED EMULATOR WINDOW.  When WSLg's RAIL side keeps painting
        #     a window whose X client has gone, clicking its X does nothing -
        #     there is no client left to receive the close - and msrdc is a
        #     protected process, so it cannot be killed either.  `wsl
        #     --shutdown` is the only cure found.
        #   * crackly sound on the WSLg fallback path.  Measured 2026-08-05: a
        #     pure sine came back mathematically perfect off the sink's own
        #     monitor while it was audibly breaking up in the room, so nothing
        #     inside WSL can see it.  (The default sink no longer goes through
        #     WSLg at all, so this half is now the fallback's problem only.)
        # It is here because the alternative is remembering a command that has
        # nothing to do with pinball, at the moment you are least inclined to
        # go looking for one.
        #
        # WINDOWS ONLY, because there is no WSL to restart anywhere else and a
        # button that cannot do its one job is worse than no button.  The two
        # faults it cures are both WSL's: a WSLg window still being painted
        # after its X client has gone, and the WSLg-to-Windows audio hop
        # degrading over a long session.  Neither exists on a Linux desktop.
        self._fixaud_btn = ttk.Button(btns, text="Restart WSL…",
                                      command=self._audio_reset, width=17)
        if sys.platform == "win32":
            self._fixaud_btn.pack(side=tk.LEFT, padx=(6, 0))

        # MACOS ONLY, for exactly the reason "Restart WSL…" is Windows only:
        # Docker is that platform's WSL.  The emulator is a Linux program, macOS
        # has no Linux, and a container is how it gets one - so a Mac without
        # Docker cannot emulate at all, and the app had nowhere on this tab that
        # said so or offered to help.  It packs and unpacks itself from
        # _docker_apply(): a ready machine should not carry a button about a
        # dependency it already satisfies.
        self._docker_btn = ttk.Button(btns, text="Install Docker…",
                                      command=self._docker_fix, width=17)

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

        # ITS OWN LABEL, not _hint.  _hint belongs to the status poll and is
        # rewritten every two seconds from the rig's own state word, so a
        # prerequisite message put there would blink out again immediately.
        self._docker_msg = ttk.Label(frame, justify=tk.LEFT, wraplength=820,
                                     foreground="#c07000", text="")
        self._docker_pad = pad

        # The key list that used to be here is gone. The rig opens its own
        # Controls window listing every binding, and it is generated from the
        # bindings themselves rather than typed out - so a copy on this tab was
        # a second source of truth that could only ever drift out of date.

        if not rig_available():
            self._run_btn.configure(state=tk.DISABLED)
            self._fixaud_btn.configure(state=tk.DISABLED)
            # SAY WHERE IT ACTUALLY IS. This used to read "it is not part of
            # this repository", which was wrong and sent people looking for a
            # separate download: the rig IS in the repository, at
            # tools/spike2_emu, and it is the INSTALLERS that deliberately do
            # not carry it. A user who installed to Program Files and read that
            # sentence had no way to work out what to do next.
            if sys.platform == "darwin":
                self._hint.configure(
                    text=("The emulator rig was not found in %s.\n\n"
                          "It ships with the app. On macOS it runs in a "
                          "container — the emulator needs Linux — and shows "
                          "its picture over VNC, which Screen Sharing opens "
                          "with nothing to install.\n\n"
                          "Docker Desktop is required. Set PAD_EMU_DIR if the "
                          "rig is somewhere else." % rig_dir()))
            elif sys.platform != "win32":
                self._hint.configure(
                    text=("The emulator rig was not found in %s.\n\n"
                          "It ships with the app, in tools/spike2_emu. Re-run "
                          "the installer, or set PAD_EMU_DIR to point at that "
                          "folder.\n\n"
                          "First time only: rootfs.sh <card.raw> builds the "
                          "guest from a card image, then build.sh and "
                          "buildbridge.sh." % rig_dir()))
            else:
                self._hint.configure(
                    text=("The emulator rig was not found in %s.\n\n"
                          "It ships with the app, so this usually means an "
                          "upgrade over a copy that predates it, or a checkout "
                          "without tools/spike2_emu. Re-run the installer, or "
                          "set PAD_EMU_DIR to point at that folder.\n\n"
                          "First time only, inside WSL: rootfs.sh <card.raw> "
                          "builds the guest from a card image, then build.sh "
                          "and buildbridge.sh." % rig_dir()))
        # The poll re-arms itself forever, so it MUST be cancelled when the tab
        # goes away.  A pending `after` job outliving its widgets is what makes
        # Tk raise "can't delete Tcl command" during teardown - it showed up
        # immediately as an error in the GUI smoke test.
        frame.bind("<Destroy>", self._on_destroy, add="+")
        if sys.platform == "darwin":
            self._docker_check()
        self._schedule_poll()

    # ------------------------------------------------------------------
    # Docker, which on macOS is what WSL is on Windows
    # ------------------------------------------------------------------

    def _docker_check(self):
        """Probe Docker off the main loop and show the answer.

        Never blocking: ``docker info`` against a daemon that is starting can
        take seconds, and one of the callers is tab BUILD time.

        THE WORKER TOUCHES NO WIDGET AND SCHEDULES NOTHING, which is a stronger
        rule than the one the status poll follows and it is build time that
        forces it: ``after`` from another thread needs a running mainloop, and
        at build time there is not one yet, so the answer would have been
        dropped in silence and the notice would not appear until the first
        re-check ten seconds later.  The worker leaves its answer in a field
        and _docker_drain(), which is main-loop code from the first call,
        collects it.
        """
        if self._docker_busy or sys.platform != "darwin":
            return
        self._docker_busy = True

        def run():
            try:
                self._docker_result = docker_state()
            finally:
                self._docker_busy = False

        threading.Thread(target=run, daemon=True).start()
        self._docker_drain()

    def _docker_drain(self):
        """Main-loop side of _docker_check: show the answer once it lands."""
        if self._stopped:
            return
        if self._docker_busy:
            try:
                self._timer().after(250, self._docker_drain)
            except tk.TclError:
                self._stopped = True
            return
        if self._docker_result is not None:
            self._docker_apply(self._docker_result)
            self._docker_result = None

    def _docker_apply(self, state):
        """Put the Docker answer on the tab, or take it away when it is fine."""
        self._docker = state
        try:
            if state == "ok":
                self._docker_btn.pack_forget()
                self._docker_msg.pack_forget()
                return
            if state == "stopped":
                self._docker_btn.configure(text="Start Docker")
                self._docker_msg.configure(
                    text=("Docker is installed but not running, and the "
                          "emulator runs inside it. Click “Start Docker”, or "
                          "open Docker Desktop yourself and wait for its whale "
                          "to stop animating."))
            else:
                self._docker_btn.configure(
                    text="Install Docker…" if homebrew() else "Get Docker…")
                self._docker_msg.configure(
                    text=("Docker Desktop is required to emulate on macOS: the "
                          "game is a Linux program and the container is how "
                          "this Mac runs one. It is a one-time install."
                          + ("\nHomebrew is here, so the button below runs "
                             "`brew install --cask docker` in Terminal."
                             if homebrew() else
                             "\nThe button below opens the download page.")))
            self._docker_btn.pack(side=tk.LEFT, padx=(6, 0))
            self._docker_msg.pack(anchor=tk.W,
                                  **getattr(self, "_docker_pad", {}))
        except (tk.TclError, AttributeError):
            pass            # the tab was never built, or is being torn down

    def _docker_fix(self):
        """Install it, or start it - whichever this machine needs.

        NEITHER IS DONE SILENTLY. Installing Docker Desktop wants an admin
        password, and a GUI app that appears to hang while an invisible
        installer waits for one is worse than no button at all - so the brew
        path runs in Terminal, where the user can see it and answer it.
        """
        if self._docker == "stopped":
            try:
                subprocess.Popen(["open", "-a", "Docker"])
                self._log("[emulate] starting Docker Desktop; it takes a "
                          "moment to come up")
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] could not start Docker Desktop: %s" % exc)
            self._timer().after(4000, self._docker_check)
            return

        brew = homebrew()
        if not brew:
            import webbrowser
            webbrowser.open(DOCKER_URL)
            self._log("[emulate] opened %s - install it, then click Start "
                      "emulator again" % DOCKER_URL)
            return
        if not messagebox.askyesno(
                "Install Docker Desktop",
                "Run this in Terminal?\n\n"
                "    brew install --cask docker\n\n"
                "It downloads Docker Desktop (a few hundred MB) and will ask "
                "for your password. When it finishes, open Docker Desktop "
                "once, then come back here."):
            return
        # osascript rather than Popen(["brew", ...]): the point is that the
        # user SEES it. A cask install asks for a password, and a progress bar
        # nobody can see is a hang.
        script = ('tell application "Terminal" to do script '
                  '"%s install --cask docker"' % brew)
        try:
            subprocess.Popen(["osascript", "-e", script,
                              "-e", 'tell application "Terminal" to activate'])
            self._log("[emulate] running `brew install --cask docker` in "
                      "Terminal")
        except Exception as exc:                        # noqa: BLE001
            self._log("[emulate] could not open Terminal: %s" % exc)
            import webbrowser
            webbrowser.open(DOCKER_URL)

    def _build_source(self, frame, pad):
        """The card image to run.  One box and a Browse button.

        A CARD IMAGE IS THE ONLY SOURCE, and why the other two went is worth
        keeping: an "extracted folder" cannot work, because PAD extracts ASSETS
        and the rig needs a title directory - a ``game`` binary with ``assets/``
        and the node ``.hex`` files beside it - which is a different shape, so
        it could only ever fail.  A "rig's own copy" option exposed whatever
        happened to be unpacked inside the rig on this machine, which is
        internal state no user can create or reason about.

        There are no "use the project's image" buttons either.  The user picks
        the image; stock or modded is their business, and a pair of buttons
        guessing at it was a second way to set one field for no gain.  The
        picked path IS remembered with the project (the app stores it in the
        anchor and restores it on project load) — remembering a choice is not
        the same as guessing one.
        """
        box = ttk.LabelFrame(frame, text="Card image to run")
        box.pack(fill=tk.X, **pad)
        self._src_path = self._card_var if self._card_var is not None \
            else tk.StringVar()
        row = ttk.Frame(box)
        row.pack(fill=tk.X, padx=8, pady=6)
        self._src_entry = ttk.Entry(row, textvariable=self._src_path)
        self._src_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse…", width=10,
                   command=self._browse).pack(side=tk.LEFT, padx=(6, 0))

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

    def _toggle(self):
        """The one button.  Dispatches on what is actually running rather than
        on what the label says: the label is refreshed by a 1 s poll, so a run
        that died a moment ago could still read "Stop".  Both branches are
        already no-ops when they do not apply, so the worst case is nothing."""
        if self._starting or self._stopping:
            return
        if self._last_up:
            self.stop()
        else:
            self.start()

    def _run_label(self, up, busy):
        """Sole owner of the run button's text and state."""
        try:
            if busy:
                self._run_btn.configure(
                    state=tk.DISABLED,
                    text="Stopping…" if self._stopping else "Starting…")
            elif up:
                self._run_btn.configure(state=tk.NORMAL, text="Stop emulator")
            else:
                self._run_btn.configure(
                    state=tk.NORMAL if rig_available() else tk.DISABLED,
                    text="Start emulator")
        except tk.TclError:
            pass

    def start(self):
        if self._starting or self._stopping or not rig_available():
            return
        self._starting = True
        self._run_label(False, True)
        self._set("state", "Starting…")
        # Validate the source BEFORE anything is launched, and put the reason
        # on the tab.  A bad path reaching the rig becomes a shell error in the
        # log pane, which is the wrong place to read it.
        src = self._source_env()
        if src is None:
            self._starting = False
            self._run_label(False, False)
            self._set("state", "Not running")
            return
        env = ["LOG=%s" % self._logfile, "PAD_AUDIO_DUMP=30"] + src
        if not self._audio_var.get():
            env.append("PAD_AUDIO=0")
        if not self._auto_var.get():
            env.append("PAD_AUTO_ATTRACT=0")
        cmd = rig_cmd("watch.sh", self.BACKSTOP_MIN, env=env)
        self._log("[emulate] %s" % " ".join(cmd))

        def run():
            # DOCKER IS CHECKED HERE, in the worker, so a slow probe cannot
            # freeze the tab - and it is checked on every Start rather than
            # trusted from build time, because the user may have installed or
            # started it in the meantime.  Without this the whole of "you need
            # Docker" was one line of padbox.sh's stderr in the log pane, after
            # the button had already said "Starting…".
            if sys.platform == "darwin":
                state = docker_state()
                if state != "ok":
                    self._log("[emulate] Docker is %s. The emulator runs in a "
                              "container on macOS, so it cannot start without "
                              "it." % ("not installed" if state == "absent"
                                       else "not running"))
                    # QUEUED BEFORE the flag is cleared, so anything waiting on
                    # "no longer starting" can be sure the tab has already been
                    # told why.
                    try:
                        self._timer().after(
                            0, lambda: (self._docker_apply(state),
                                        self._set("state", "Not running"),
                                        self._run_label(False, False)))
                    except (tk.TclError, RuntimeError):
                        pass
                    finally:
                        self._starting = False
                    return
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
        self._run_label(True, True)
        self._set("state", "Stopping…")

        def run():
            try:
                out = subprocess.run(
                    rig_cmd("killgame.sh"),
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

    def _audio_reset(self):
        """Restart WSL: the cure for a stranded window, and for the old crackle.

        NOT A FIX FOR ANYTHING IN THE RIG, and the dialog says so, because
        reaching for this when the emulator really is at fault would only hide
        the problem for a while.  The two faults it does address both live
        outside WSL's reach:

        * a window WSLg keeps painting after its X client has gone.  Clicking
          its X does nothing (nothing is left to receive the close) and msrdc
          refuses Stop-Process, so a restart of WSL is the only way out.
        * crackle on the WSLg audio fallback.  Measured 2026-08-05: a pure sine
          came back mathematically perfect off the sink's own monitor (0 of
          280490 samples off a sine) while it was audibly breaking up in the
          room, so nothing inside WSL can see it and no self-test could catch
          it.  A restart rebuilds the PulseAudio server and that channel.

        Terminates EVERY WSL distro, so it asks first and refuses while a run
        is up (the poll greys the button, and this re-checks).
        """
        if self._resetting or self._starting or self._stopping:
            return
        if not rig_available():
            return
        if self._last_up:
            messagebox.showinfo(
                "Restart WSL",
                "Stop the emulator first.\n\n"
                "This restarts WSL, which would kill the running game without "
                "letting it shut down cleanly.")
            return
        if not messagebox.askyesno(
                "Restart WSL",
                "Restart WSL?\n\n"
                "This is the cure for two things the emulator cannot fix "
                "itself:\n\n"
                "  • an emulator window left on screen that will not close. "
                "Its X button does nothing because nothing is behind it any "
                "more.\n"
                "  • crackly or stuttery sound, which is usually WSL's audio "
                "link to Windows going bad after a long session.\n\n"
                "This closes EVERYTHING running in WSL, not just the "
                "emulator. Nothing on disk is lost, and WSL starts again by "
                "itself the next time it is used.\n\n"
                "Restart WSL now?"):
            return

        self._resetting = True
        self._fixaud_btn.configure(state=tk.DISABLED)
        self._set("state", "Restarting WSL…")

        def run():
            try:
                # Tear the rig down first even though the button is only
                # enabled when nothing is up: a terminal-started run the poll
                # has not seen yet would otherwise be killed by the shutdown
                # with no teardown at all.
                subprocess.run(rig_cmd("killgame.sh"),
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               timeout=60, creationflags=_CREATE_FLAGS)
                self._log("[emulate] restarting WSL to rebuild its audio path")
                out = subprocess.run(["wsl.exe", "--shutdown"],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     timeout=120, creationflags=_CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    if line.strip():
                        self._log("[emulate] " + line)
                self._log("[emulate] WSL is down; it restarts on next use. "
                          "Start the emulator again and sound should be clean.")
            except Exception as exc:                    # noqa: BLE001
                self._log("[emulate] audio reset failed: %s" % exc)
            finally:
                self._resetting = False

        threading.Thread(target=run, daemon=True).start()

    def shutdown_sync(self):
        """Take the whole emulator down because PAD is quitting.  BLOCKING, on
        the main thread, bounded by the subprocess timeout — quitting the app
        must close the game window, the Controls window and the virtual
        playfield, not leave them orphaned behind a vanished control surface.

        Runs whenever this panel started a run OR the last status poll saw one
        (so a terminal-started run is taken down too — the user asked for
        "quitting PAD shuts down all the emulator windows", not "the ones PAD
        started").  killgame.sh SIGKILLs all five processes and removes the
        LED block, which is the playfield window's signal to close itself;
        the game and Controls windows die with padglhost.
        """
        if not (self._proc is not None or self._last_up):
            return
        if not rig_available():
            return
        self._stopped = True             # no more polls into a dying Tk
        try:
            subprocess.run(
                rig_cmd("killgame.sh"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=25, creationflags=_CREATE_FLAGS)
        except Exception:                               # noqa: BLE001
            pass                     # quitting anyway; best effort by design

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
        # RE-ASKED ONLY WHILE THE ANSWER IS BAD, every ~10 s.  A user who
        # installs Docker Desktop with this tab open should see the notice go
        # away, and a machine that already has it should not pay for a `docker
        # info` every two seconds to be told what it was told at build time.
        if sys.platform == "darwin" and self._docker != "ok":
            self._docker_ticks += 1
            if self._docker_ticks % 5 == 1:
                self._docker_check()
            # AND DO NOT POLL THROUGH IT.  status.sh reaches the rig via
            # padbox.sh, so on macOS every poll is a `docker` invocation - and
            # with no Docker to invoke that is a process spawned every two
            # seconds to fail in exactly the same way.  `None` is "the first
            # probe has not answered yet", which is not the same as "no", so it
            # still polls.
            if self._docker is not None:
                self._schedule_poll()
                return
        if not rig_available():
            self._schedule_poll()
            return

        def run():
            try:
                out = subprocess.run(
                    rig_cmd("status.sh", self._logfile),
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
            self._last_up = up
            self._run_label(up, busy)
            # Resetting WSL audio kills every distro, so never offer it while a
            # run is up or mid-transition: the honest order is stop, then reset.
            self._fixaud_btn.configure(
                state=tk.DISABLED if (up or busy or self._resetting
                                      or not rig_available()) else tk.NORMAL)
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
