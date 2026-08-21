"""Emulate tab for Jersey Jack Pinball — run a JJP game on this PC.

A SIBLING OF ``emulate_tab``, NOT AN EXTENSION OF IT.  That module is 3,446
lines welded to the Stern Spike 2 rig in a dozen places that are not cosmetic:
its rig directory, its ``qemu-user-static`` / ``gcc-arm-linux-gnueabihf``
prerequisite vocabulary, its state words, its Stern SD-card filename regex, its
``PAD_CARD=`` launch environment.  Threading a second rig through all of that
would carry two prerequisite vocabularies and two state vocabularies in one
file, against three existing test files, for no user-visible gain.  What the
two genuinely share — how a Windows path is spelled for WSL, how a rig script
is invoked, how ``key=value`` status is parsed — lives in :mod:`._rig`, so
there is still exactly one definition of each.

WHAT MAKES JJP DIFFERENT FROM SPIKE 2
-------------------------------------
Simpler in the big ways: the game is a native x86-64 Linux binary, so there is
no ``qemu-user``; it draws through GLX so there is no GL bridge; it decodes its
own WebM with libavcodec so there is no video bridge.  Those are the three
largest subsystems of the Spike 2 rig and none of them exist here.

Harder in one way that has no Spike 2 analogue: **the purple Sentinel USB key
is mandatory and cannot be faked.**  The game binary is Sentinel LDK Envelope
protected — 7,086 of its 8,566 functions are ciphertext at rest — and the
dongle supplies the AES key that decrypts them.  There is no branch to patch.
Without it the game prints ``Sentinel key not found (H0007)`` and exits 1,
which is exactly what a real machine shows, so this panel reports it as a
first-class state rather than as a crash.

The key is also per-title: a key for another JJP game will H0007 on this one.

WHY THE PANEL IS THIN
---------------------
Every step of the launch — mount, jail, dongle, audio, boards, display, game —
lives in ``tools/jjp_emu/watch.sh``, in the one order that works.  This panel
starts it, stops it, and says truthfully what it is doing.  Putting the
sequence here instead would be a second definition of it, and the order is
exactly the part that was learned the hard way.
"""

import os
import pathlib
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import _rig
from .widgets import _Tooltip

#: The rig ships in the repo next to this package, so it survives a reboot and
#: there is exactly one copy of it.  Resolved from this file so a checkout
#: anywhere works.  ``PAD_JJP_EMU_DIR`` moves it.
DEFAULT_RIG_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "jjp_emu"
)


def rig_dir():
    return os.environ.get("PAD_JJP_EMU_DIR") or DEFAULT_RIG_DIR


def rig_available():
    """Is the rig actually present?  Checked by script, not by directory:
    a half-copied tools tree is the failure this catches."""
    d = rig_dir()
    return all(os.path.isfile(os.path.join(d, s))
               for s in ("watch.sh", "stop.sh", "status.sh"))


def rig_cmd(*args, **kw):
    return _rig.rig_cmd(rig_dir(), *args, **kw)


def rig_cmd_root(*args, **kw):
    return _rig.rig_cmd_root(rig_dir(), *args, **kw)


#: usbipd lives here on a default install; found on PATH first.
USBIPD_FALLBACK = r"C:\Program Files\usbipd-win\usbipd.exe"

#: The Sentinel HL key.  Aladdin/SafeNet vendor id, and the same for every JJP
#: title — it is the LICENCE on the key that is per-title, not the hardware.
HASP_VID_PID = "0529:0001"


def usbipd_path():
    from shutil import which
    return which("usbipd") or (USBIPD_FALLBACK
                               if os.path.isfile(USBIPD_FALLBACK) else None)


def attach_dongle_cmd():
    """Hand the Sentinel key to WSL.

    ``usbipd`` needs a WSL session ALREADY RUNNING or it fails with "There is
    no WSL 2 distribution running" — which is why the panel pokes WSL awake
    first rather than trusting that something else has.
    """
    exe = usbipd_path()
    if not exe:
        return None
    return [exe, "attach", "--wsl", "--hardware-id", HASP_VID_PID]


def key_on_pc():
    """Is the Sentinel key plugged into the PC, whatever WSL can see?

    ``status.sh``'s ``dongle_present`` is a WSL question - it reads sysfs
    INSIDE the distro - so a key sitting in the machine but not passed through
    by usbipd reads as absent, and the panel said "No security key" at a user
    looking straight at the key.  Those are different faults: one needs a key,
    the other needs an attach, and the panel already knows how to do the second.

    Returns True / False, or None when usbipd cannot be asked at all.
    """
    exe = usbipd_path()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "list"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=20,
                             creationflags=_rig.CREATE_FLAGS)
    except Exception:                                      # noqa: BLE001
        return None
    return HASP_VID_PID in out.stdout.decode("utf-8", "replace").lower()


def key_failure(line):
    """(headline, hint) if this rig line is a key verdict, else None.

    H0007 — "Sentinel key not found" — covers TWO faults with opposite fixes,
    and the panel used to report only the first.  On 2026-08-20 that cost an
    hour: it said "wrong key, plug in the GunsNRoses key" while the truth was
    that the licence daemon could see NO key at all, so every title failed the
    same way, including the one whose key WAS plugged in.  ``run_game.sh`` now
    distinguishes them and this reads its verdict rather than guessing one.
    """
    if line.startswith("NO KEY:"):
        return ("No security key",
                "No Sentinel key is visible inside WSL — the passthrough is "
                "not up, or it dropped. Plug the key in and press Start; the "
                "panel re-attaches it for you.")
    if line.startswith("KEY NOT ACCEPTED:"):
        return ("Key not accepted",
                "The key is visible in WSL but the game could not open it. "
                "Either it is another JJP title's key — they are per-title — "
                "or the licence daemon never picked it up, which no key swap "
                "fixes. The log line below says how to tell the two apart.")
    # The pre-2026-08-20 wording, still understood so an older rig script in a
    # half-updated checkout does not silently stop being reported.
    if "WRONG KEY" in line:
        return ("Wrong key for this game",
                "The plugged-in key runs a different JJP title. JJP keys are "
                "per-title — plug in this game's own key.")
    return None


def state_text(info):
    """(label, hint) for the panel's headline, from status.sh's key=value.

    The order of these tests is the order a user hits them, so the FIRST thing
    that is wrong is what they are told about — a run with no key is not
    "stopped", it is "no security key", and saying "stopped" would send them
    looking in the wrong place.
    """
    if not info:
        return "Checking…", ""
    if info.get("wsl") != "1":
        return "WSL not answering", "The rig is a Linux program and runs inside WSL."
    procs = int(info.get("game_procs") or 0)
    if procs:
        bits = []
        rss = int(info.get("game_rss_kb") or 0)
        if rss:
            bits.append("%.1f GB" % (rss / 1024.0 / 1024.0))
        up = int(info.get("game_uptime_s") or 0)
        if up:
            bits.append("%d:%02d" % (up // 60, up % 60))
        if info.get("frames_in", "0") != "0":
            bits.append("%s frames in" % info["frames_in"])
        if info.get("board_nodes", "0") == "0":
            bits.append("NO BOARDS — no switches or LEDs")
        return "Running", "  ·  ".join(bits)
    if info.get("dongle_present") != "1":
        # The key can be IN the PC and still invisible to the rig: usbipd has
        # to hand it to WSL first.  Saying "no security key" to someone looking
        # at the key in the port is how this presented.
        if info.get("key_on_pc") == "1":
            return ("Key not passed through yet",
                    "The key is in this PC but WSL cannot see it yet — it has "
                    "to be handed over by usbipd. Doing that now; it takes a "
                    "few seconds.")
        return ("No security key",
                "Plug in the purple JJP USB key. The game's code is encrypted "
                "with it — this is not a check that can be skipped.")
    if info.get("image_mounted") != "1":
        return "No image mounted", "Pick a JJP ISO and press Start."
    return "Stopped", ""


class JJPEmulatePanel:
    """The JJP Emulate tab's widgets and its background poller."""

    #: Status poll period while something is running.  Each poll is one
    #: ``wsl.exe`` round trip.
    POLL_MS = 2000

    #: Poll period when the rig is idle.  A machine with no emulator on it is
    #: not worth a WSL spawn every two seconds for as long as the app is open —
    #: that is 1,800 round trips an hour to be told "off", and after a Windows
    #: reboot the first of them boots the whole WSL VM.  This is the same guard
    #: the Spike 2 panel carries, and a second polling tab in the same app
    #: doubles the exposure it exists for.
    POLL_IDLE_MS = 10000

    #: Fast retry until the FIRST answer, so a freshly opened tab settles
    #: quickly instead of showing "Checking…" for ten seconds.
    POLL_FIRST_MS = 700

    def __init__(self, parent, log=None, iso_var=None, theme_fn=None,
                 badge_fn=None, resize_fn=None):
        self._parent = parent
        self._log_sink = log or (lambda msg: None)
        self._iso_var = iso_var
        self._theme_fn = theme_fn or (lambda: "dark")
        self._badge_fn = badge_fn
        self._resize_fn = resize_fn or (lambda: None)

        self._poll_job = None
        self._poll_busy = False
        self._polled_once = False
        self._stopped = False
        self._busy = False            # a start/stop worker is in flight
        self._last_up = False
        self._info = {}
        #: The last start failed because the plugged-in key unlocks a DIFFERENT
        #: JJP title.  Sticky so the poll's own state text does not immediately
        #: paint over the explanation; cleared when a new start begins.
        self._wrong_key = False
        #: One-shot guard for the automatic usbipd hand-over.
        self._auto_attached = False
        #: What the rig actually said about the key, so the sticky headline
        #: repeats the real verdict instead of assuming a wrong-title key.
        self._key_verdict = ("Wrong key for this game",
                             "The plugged-in key runs a different JJP title.")

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    def _timer(self):
        """The widget every ``after`` job hangs off.

        The TOPLEVEL, not the tab frame: an ``after`` job registers a Tcl
        command owned by the widget it was scheduled on, and the tab frame is
        destroyed mid-cascade during ``root.destroy()`` — cancelling a job on a
        widget that is itself being torn down raises "can't delete Tcl
        command".  The toplevel outlives every tab.
        """
        return self._parent.winfo_toplevel()

    def _log(self, msg):
        """Log from ANY thread.  ``append_log`` writes into a Tk Text widget
        and Tk is not thread safe, so the workers hand it back to the main
        loop."""
        try:
            self._timer().after(0, lambda: self._log_sink(msg))
        except (tk.TclError, RuntimeError):
            pass

    def iso_path(self):
        return (self._iso_var.get() if self._iso_var is not None else "").strip()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def build(self, frame):
        outer = ttk.Frame(frame)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        intro = ttk.Label(
            outer, justify=tk.LEFT, wraplength=760,
            text=("Run a Jersey Jack game on this PC. The game is a native "
                  "x86-64 Linux program, so it runs directly — no CPU "
                  "emulation.\n"
                  "The purple JJP USB security key must be plugged in: the "
                  "game's code is encrypted with it, so this is not a check "
                  "that can be skipped."))
        intro.pack(anchor="w", pady=(0, 8))

        # --- image row ---------------------------------------------------
        row = ttk.Frame(outer)
        row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row, text="Game ISO:").pack(side=tk.LEFT)
        if self._iso_var is None:
            self._iso_var = tk.StringVar()
        self._iso_entry = ttk.Entry(row, textvariable=self._iso_var)
        self._iso_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self._browse_btn = ttk.Button(row, text="Browse…", command=self._browse)
        self._browse_btn.pack(side=tk.LEFT)
        _Tooltip(self._iso_entry,
                 "A JJP release ISO (Clonezilla image). It is mounted READ "
                 "ONLY and run in place — nothing is written to it.",
                 self._theme_fn)

        # --- controls ----------------------------------------------------
        ctl = ttk.Frame(outer)
        ctl.pack(fill=tk.X, pady=(2, 8))
        self._go_btn = ttk.Button(ctl, text="Start", command=self._toggle)
        self._go_btn.pack(side=tk.LEFT)

        # Recovery sits NEXT TO Start, not banished to the right edge.  It is
        # reached at the same moment and for the same reason - the run will not
        # come up - so putting it where the eye already is beats making it a
        # thing to go and find.
        self._reset_btn = ttk.Button(ctl, text="Fix stuck state",
                                     command=self._fix_state)
        self._reset_btn.pack(side=tk.LEFT, padx=(6, 0))
        _Tooltip(self._reset_btn,
                 "Force-restart WSL to clear a wedged emulator — a frozen "
                 "window with no border, a game that will not stop, or orphaned "
                 "board devices. Closes ALL WSL sessions and takes ~15s; your "
                 "ISO and settings are untouched.",
                 self._theme_fn)

        # --- state headline ----------------------------------------------
        self._state_lbl = ttk.Label(outer, text="Checking…",
                                    font=("Segoe UI", 11, "bold"))
        self._state_lbl.pack(anchor="w", pady=(4, 0))
        self._hint_lbl = ttk.Label(outer, text="", wraplength=760,
                                   justify=tk.LEFT)
        self._hint_lbl.pack(anchor="w")

        # --- status grid --------------------------------------------------
        grid = ttk.LabelFrame(outer, text="Status")
        grid.pack(fill=tk.X, pady=(10, 0))
        self._cells = {}
        rows = [
            ("Security key", "dongle_present"),
            ("Licence daemon", "hasp_port_1947"),
            ("Image mounted", "image_mounted"),
            ("Game", "game"),
            ("Processes", "game_procs"),
            ("Memory", "game_rss_kb"),
            ("Uptime", "game_uptime_s"),
            ("Display", "nested_display"),
            ("Boards", "board_nodes"),
            ("Frames in / out", "frames_in"),
            ("LED writes", "led_writes"),
        ]
        for i, (label, key) in enumerate(rows):
            r, c = i % 6, i // 6
            ttk.Label(grid, text=label + ":").grid(
                row=r, column=c * 2, sticky="w", padx=(8, 4), pady=1)
            v = ttk.Label(grid, text="—")
            v.grid(row=r, column=c * 2 + 1, sticky="w", padx=(0, 18), pady=1)
            self._cells[key] = v

        self._note = ttk.Label(outer, text="", wraplength=760,
                               justify=tk.LEFT, foreground="#c07a3a")
        self._note.pack(anchor="w", pady=(8, 0))

        if not rig_available():
            self._note.configure(
                text="The JJP emulator rig is missing from tools/jjp_emu — "
                     "this checkout looks incomplete.")
            self._go_btn.configure(state=tk.DISABLED)

        frame.bind("<Destroy>", self._on_destroy)
        self._schedule_poll(self.POLL_FIRST_MS)

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self._parent:
            return
        self._stopped = True
        if self._poll_job:
            try:
                self._timer().after_cancel(self._poll_job)
            except (tk.TclError, RuntimeError, ValueError):
                pass
            self._poll_job = None

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select a JJP game ISO",
            filetypes=[("JJP game image", "*.iso"), ("All files", "*.*")])
        if path:
            self._iso_var.set(path)

    def _toggle(self):
        if self._busy:
            return
        if self._last_up:
            self._stop_async()
        else:
            self._start_async()

    def _start_async(self):
        iso = self.iso_path()
        if not iso and self._info.get("image_mounted") != "1":
            messagebox.showinfo(
                "Emulate",
                "Pick a JJP game ISO first.\n\nIt is mounted read only and run "
                "in place — nothing is written to it.")
            return
        if self._info.get("dongle_present") != "1":
            # Not fatal here: the attach below may be exactly what is missing.
            self._log("JJP: security key not visible in WSL yet — attaching.")

        self._busy = True
        self._wrong_key = False       # a new attempt clears the last verdict
        self._go_btn.configure(state=tk.DISABLED, text="Starting…")

        def work():
            try:
                if not self._attach_dongle():
                    # The key never became visible.  watch.sh would just wait
                    # again and fail with the same message; stop here with the
                    # guidance instead of a redundant minute of restore + wait.
                    return
                self._log("JJP: starting the rig (this takes a minute on a "
                          "first run — the image has to be restored). Each step "
                          "is shown below as it runs.")
                args = [iso] if iso else []
                # Stream the launch line by line rather than capturing it all
                # and logging it once at the end.  A wrong-title key only shows
                # itself at the game step, ~15 s in, and the old capture-then-log
                # meant the panel sat silent on "Starting…" the whole time — a
                # launch that was working looked frozen.  A wrong-title key is
                # the one failure worth pulling into the headline (the key IS
                # plugged in, so "No security key" would mislead) and it is
                # caught the instant "WRONG KEY" is printed.
                rc, saw_wrong_key = self._run_streaming(
                    rig_cmd_root("watch.sh", *args), timeout=1800)
                if saw_wrong_key or rc == 7:
                    self._mark_wrong_key()
                elif rc not in (0, None):
                    self._log("JJP: start failed (exit %d)." % rc)
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True).start()

    def _run_streaming(self, cmd, timeout=1800):
        """Run a rig command, logging each line AS IT IS PRINTED.

        Returns ``(returncode, saw_wrong_key)``.  The launch used to be a
        single ``subprocess.run`` whose whole output was captured and only
        logged once the process returned — so a twenty-second launch (or a
        wrong-dongle launch that has to reach the game step to find out) showed
        nothing at all until it was over, which reads as a frozen app.
        Streaming turns that dead wait into a running account of what the rig is
        doing, and surfaces a WRONG KEY the moment the game step prints it
        rather than fifteen seconds later.

        The whole launch is bounded by ``timeout``: a genuinely wedged step
        must not leave the reader blocked forever.  The timer kills the process;
        the readline loop then drains and ends.
        """
        timed_out = {"v": False}
        saw_wrong = {"v": False}
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, universal_newlines=True,
                creationflags=_rig.CREATE_FLAGS)
        except Exception as exc:                           # noqa: BLE001
            self._log("JJP: could not start the rig: %s" % exc)
            return None, False

        def _kill():
            timed_out["v"] = True
            try:
                proc.kill()
            except Exception:                              # noqa: BLE001
                pass

        killer = threading.Timer(timeout, _kill)
        killer.daemon = True
        killer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._log("JJP: " + line)
                verdict = key_failure(line)
                if verdict and not saw_wrong["v"]:
                    saw_wrong["v"] = True
                    self._mark_key_failure(*verdict)
        finally:
            killer.cancel()
            try:
                proc.stdout.close()
            except Exception:                              # noqa: BLE001
                pass
            proc.wait()
        if timed_out["v"]:
            self._log("JJP: start timed out — the rig was stopped.")
        return proc.returncode, saw_wrong["v"]

    def _mark_key_failure(self, label, hint):
        """Flip the headline to the key verdict, from any thread.

        Sticky (``_wrong_key``) so the next status poll — which may see a key
        present and no game — does not immediately paint "Stopped" over the real
        reason.  Cleared when the next start begins.
        """
        self._wrong_key = True
        self._key_verdict = (label, hint)

        def paint():
            try:
                self._state_lbl.configure(text=label)
                self._hint_lbl.configure(text=hint)
            except tk.TclError:
                pass

        try:
            self._timer().after(0, paint)
        except (tk.TclError, RuntimeError):
            pass

    def _auto_attach(self):
        """Hand the key to WSL without being asked.

        The panel already knew how to do this - it just only did it when Start
        was pressed, so a key plugged in before the app opened sat there reading
        "No security key" until the user pressed a button they had no reason to
        think would help.  Detecting it and saying "plug it in" was the panel
        describing a problem it was holding the fix for.

        ONE SHOT per drop.  It re-arms in _apply the moment the key is visible
        again, so a key pulled and replaced is picked up - but a key that will
        not attach does not get a usbipd call every poll for as long as the app
        is open.
        """
        if self._auto_attached or self._busy:
            return
        self._auto_attached = True
        self._log("JJP: the security key is in this PC but not passed through "
                  "to WSL — attaching it.")

        def work():
            try:
                if self._attach_dongle():
                    self._log("JJP: security key attached.")
                else:
                    self._log("JJP: could not attach the security key "
                              "automatically. Press Start to try again.")
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: auto-attach failed: %s" % exc)
            finally:
                # Poll straight away so the panel stops saying the old thing.
                try:
                    self._timer().after(0, self._poll)
                except (tk.TclError, RuntimeError):
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _attach_dongle(self):
        """Hand the key to WSL and WAIT until it is actually there.

        Two things make this need to be more than a single ``usbipd attach``:

        * ``usbipd attach`` fails outright if no WSL 2 distribution is running,
          and on a freshly booted machine — or right after a ``wsl --shutdown``
          — nothing has started one yet.  The harmless ``true`` wakes it.
        * ``usbipd attach`` is ASYNCHRONOUS.  It returns before WSL finishes
          enumerating the USB device, so proceeding straight to the launch
          hands the rig a key that is not visible yet, and the launch fails
          "NO KEY" a second before the key appears.  This is exactly the error
          the user hit.  So after attaching we POLL WSL until the key is really
          visible, and re-attach once if it is not.

        Returns True if the key ends up visible in WSL, False otherwise — the
        caller can then decide whether the launch is worth attempting.
        """
        cmd = attach_dongle_cmd()
        if not cmd:
            self._log("JJP: usbipd-win not found — cannot pass the security "
                      "key through to WSL. Install it from "
                      "https://github.com/dorssel/usbipd-win")
            return False

        # Wake WSL so usbipd has a distribution to attach to.
        try:
            subprocess.run(["wsl.exe", "-e", "true"], timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

        if self._key_visible_in_wsl():
            self._log("JJP: security key already present in WSL.")
            return True

        for attempt in (1, 2):
            try:
                out = subprocess.run(cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, timeout=60,
                                     creationflags=_rig.CREATE_FLAGS)
                msg = out.stdout.decode("utf-8", "replace").strip()
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: usbipd failed: %s" % exc)
                return False

            low = msg.lower()
            if "no device" in low or "not found" in low:
                # The key is not plugged into the PC at all — nothing to wait
                # for, and the status grid already says "No security key".
                self._log("JJP: the purple JJP key is not plugged into this PC.")
                return False
            if "not shared" in low or "bind" in low:
                self._bind_dongle()                        # then the retry attaches

            # Attached (or already attached) — now WAIT for it to enumerate.
            if self._wait_for_key():
                self._log("JJP: security key attached and visible in WSL.")
                return True
            self._log("JJP: key attached but not visible yet — retrying.")

        self._log("JJP: the security key did not appear in WSL. If it is "
                  "plugged in, unplug and replug it, then press Start again.")
        return False

    def _bind_dongle(self):
        """Share the key with usbipd (needed the first time, or after a
        reboot).  Best-effort; the attach retry is what actually uses it."""
        exe = usbipd_path()
        if not exe:
            return
        try:
            subprocess.run([exe, "bind", "--hardware-id", HASP_VID_PID],
                           timeout=30, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    def _key_visible_in_wsl(self):
        """True if the Sentinel key is enumerated in WSL right now."""
        try:
            out = subprocess.run(
                ["wsl.exe", "-e", "bash", "-lc",
                 "for d in /sys/bus/usb/devices/*; do "
                 "[ -f $d/idVendor ] || continue; "
                 "[ \"$(cat $d/idVendor)\" = 0529 ] && "
                 "[ \"$(cat $d/idProduct)\" = 0001 ] && { echo yes; exit 0; }; "
                 "done; echo no"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
                creationflags=_rig.CREATE_FLAGS)
            return b"yes" in out.stdout
        except Exception:                                  # noqa: BLE001
            return False

    def _wait_for_key(self, tries=12):
        """Poll for the key to enumerate after an attach (it is async)."""
        import time
        for _ in range(tries):
            if self._key_visible_in_wsl():
                return True
            time.sleep(1)
        return False

    def _stop_async(self):
        self._busy = True
        self._go_btn.configure(state=tk.DISABLED, text="Stopping…")

        def work():
            try:
                out = subprocess.run(
                    rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=180, creationflags=_rig.CREATE_FLAGS)
                self._log("JJP: " + out.stdout.decode("utf-8", "replace").strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True).start()

    def _release(self):
        def done():
            self._busy = False
            self._go_btn.configure(state=tk.NORMAL)
            self._poll()
        try:
            self._timer().after(0, done)
        except (tk.TclError, RuntimeError):
            self._busy = False

    def _fix_state(self):
        """Force-restart WSL to recover from a wedged emulator.

        This is the escalation past Stop.  ``stop.sh`` kills the processes it
        can find, but a truly wedged run can leave things Stop cannot fix from
        inside WSL: a frozen WSLg window with no border (the compositor never
        got the surface back), zombies pinning a parent, a mount the kernel will
        not release.  ``wsl --shutdown`` tears the whole VM down, which clears
        ALL of that at once — and is the one thing the user was told to run by
        hand for exactly this, so the panel should offer it as a button.

        It is deliberately heavier than Stop and says so: it closes every WSL
        session on the machine (other terminals included) and takes ~15s to come
        back.  Nothing on disk is touched, so the ISO, the restored image and
        settings all survive.
        """
        if self._busy:
            return
        if sys.platform != "win32":
            messagebox.showinfo(
                "Fix stuck state",
                "This recovery restarts WSL and only applies on Windows.")
            return
        if not messagebox.askyesno(
                "Fix stuck state",
                "Force-restart WSL to clear a wedged emulator?\n\n"
                "Use this when Stop did not work — a frozen window with no "
                "border, a game that will not stop, or the boards left "
                "orphaned.\n\n"
                "It closes EVERYTHING running in WSL (any other WSL terminals "
                "or sessions too) and takes about 15 seconds to come back. Your "
                "ISO, the restored image and your settings are untouched."):
            return

        self._busy = True
        self._go_btn.configure(state=tk.DISABLED)
        self._reset_btn.configure(state=tk.DISABLED, text="Resetting…")

        def work():
            try:
                self._log("JJP: shutting WSL down to clear stuck state…")
                out = subprocess.run(
                    ["wsl.exe", "--shutdown"], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=120,
                    creationflags=_rig.CREATE_FLAGS)
                msg = out.stdout.decode("utf-8", "replace").strip()
                if out.returncode == 0:
                    self._log("JJP: WSL was shut down — frozen windows, stuck "
                              "processes and orphaned devices are cleared. Press "
                              "Start to run again.")
                else:
                    self._log("JJP: wsl --shutdown returned %d. %s"
                              % (out.returncode, msg))
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: could not restart WSL: %s" % exc)
            finally:
                self._timer().after(0, self._reset_done)

        threading.Thread(target=work, daemon=True).start()

    def _reset_done(self):
        self._busy = False
        try:
            self._go_btn.configure(state=tk.NORMAL)
            self._reset_btn.configure(state=tk.NORMAL, text="Fix stuck state")
        except tk.TclError:
            return
        # Re-poll: the first status call boots WSL back up and confirms the
        # clean state, which is the feedback that the reset worked.
        self._poll()

    def _open_matrix(self):
        """Re-open the switch/LED matrix beside a running game.

        Normally unnecessary: ``watch.sh`` opens it as its last step, because
        it is the control surface for the machine rather than an optional
        extra.  This exists for the case where the user closed it.

        AS ROOT.  ``swdump.py`` reads the game's memory to get the switch and
        lamp tables, and the game runs as root — so the ordinary-user form
        fails before it ever reaches the UI, which is exactly how this first
        presented: the log said "opened" and no window appeared.  The script
        drops to the desktop user for the UI itself, which needs their WSLg
        session.

        And it REPORTS what happened.  The old version logged success
        unconditionally, so a launch that died on the first line still read as
        a working one.
        """
        def work():
            try:
                out = subprocess.run(
                    rig_cmd_root("jjpsw_launch.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=180, creationflags=_rig.CREATE_FLAGS)
                msg = out.stdout.decode("utf-8", "replace").strip()
                if out.returncode == 0:
                    self._log("JJP: " + (msg or "switch matrix opened."))
                else:
                    self._log("JJP: the switch matrix did not open. " + msg)
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: could not open the switch matrix: %s" % exc)
        threading.Thread(target=work, daemon=True).start()

    # The Screenshot button and its handler are gone.  Capturing the game is
    # still a rig job - `grab.sh` does it, and does it better, because it knows
    # about WSLg's RAIL (an x11grab of :0 returns a blank frame while the game
    # draws perfectly).  A panel button that shells out to the same script only
    # added a file dialog to a thing better done where the rig already lives.

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------

    def _schedule_poll(self, ms=None):
        if self._stopped:
            return
        if ms is None:
            if not self._polled_once:
                ms = self.POLL_FIRST_MS
            else:
                ms = self.POLL_MS if self._last_up else self.POLL_IDLE_MS
        try:
            self._poll_job = self._timer().after(ms, self._poll)
        except (tk.TclError, RuntimeError):
            self._poll_job = None

    def _poll(self):
        self._poll_job = None
        if self._stopped or not rig_available():
            return
        # Skipping rather than queueing is right: a status poll is a snapshot,
        # and the answer a stacked poll would give is the one already in
        # flight.  ``_poll_busy`` is only ever written on the main thread.
        if self._poll_busy or self._busy:
            self._schedule_poll()
            return
        self._poll_busy = True

        def run():
            try:
                out = subprocess.run(
                    rig_cmd("status.sh"), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=25,
                    creationflags=_rig.CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                              # noqa: BLE001
                text = ""
            info = _rig.parse_status(text)
            # A key the rig cannot see may still be sitting in the PC, waiting
            # to be handed over.  Asked ONLY when it matters, so the ordinary
            # poll stays the one WSL round trip it has always been.
            if info and info.get("dongle_present") != "1":
                on_pc = key_on_pc()
                if on_pc is not None:
                    info["key_on_pc"] = "1" if on_pc else "0"
            if self._stopped:
                self._poll_busy = False
                return

            def apply_and_release():
                self._poll_busy = False
                self._polled_once = True
                self._apply(info)

            try:
                self._timer().after(0, apply_and_release)
            except (tk.TclError, RuntimeError):
                self._poll_busy = False

        threading.Thread(target=run, daemon=True).start()
        self._schedule_poll()

    def _apply(self, info):
        try:
            self._info = info
            self._last_up = int(info.get("game_procs") or 0) > 0
            label, hint = state_text(info)
            # A key verdict sticks until the next start: the game is down and
            # dongle_present may well be 1, so the plain state text would say
            # "Stopped" and hide the real reason it will not run.  The verdict
            # is whatever the rig actually reported - not an assumed one.
            if self._wrong_key and not self._last_up:
                label, hint = self._key_verdict
            self._state_lbl.configure(text=label)
            self._hint_lbl.configure(text=hint)
            if not self._busy:
                self._go_btn.configure(text="Stop" if self._last_up else "Start")


            def yn(k):
                return "yes" if info.get(k) == "1" else "no"

            if info.get("dongle_present") == "1":
                self._auto_attached = False      # re-arm for the next drop
            self._cells["dongle_present"].configure(text=yn("dongle_present"))
            self._cells["hasp_port_1947"].configure(text=yn("hasp_port_1947"))
            self._cells["image_mounted"].configure(text=yn("image_mounted"))
            self._cells["game"].configure(text=info.get("game") or "—")
            self._cells["game_procs"].configure(text=info.get("game_procs") or "0")
            rss = int(info.get("game_rss_kb") or 0)
            self._cells["game_rss_kb"].configure(
                text=("%.1f GB" % (rss / 1024.0 / 1024.0)) if rss else "—")
            up = int(info.get("game_uptime_s") or 0)
            self._cells["game_uptime_s"].configure(
                text=("%d:%02d" % (up // 60, up % 60)) if up else "—")
            self._cells["nested_display"].configure(
                text="windowed" if info.get("nested_display", "0") != "0"
                else ("desktop" if self._last_up else "—"))
            nodes = info.get("board_nodes", "0")
            self._cells["board_nodes"].configure(
                text=("%s device%s" % (nodes, "" if nodes == "1" else "s"))
                if nodes != "0" else "none")
            self._cells["frames_in"].configure(
                text="%s / %s" % (info.get("frames_in", "0"),
                                  info.get("frames_out", "0")))
            self._cells["led_writes"].configure(text=info.get("led_writes", "0"))

            # The one note worth interrupting for: a running game with no
            # boards has no switches and no LEDs, and looks like a bug.
            if self._last_up and info.get("board_nodes", "0") == "0":
                self._note.configure(
                    text="The game is running but the playfield boards are not "
                         "present, so it can see no switches and drive no "
                         "LEDs. Stop and start again to bring them up.")
            elif (not self._last_up and info.get("key_on_pc") == "1"
                  and info.get("dongle_present") != "1"):
                self._note.configure(
                    text="The security key is in this PC but WSL cannot see it "
                         "yet. Handing it over — no need to do anything.")
                self._auto_attach()
            elif not self._last_up and info.get("dongle_present") == "0":
                self._note.configure(
                    text="No security key detected. The game's code is "
                         "encrypted with the purple JJP USB key — plug it in "
                         "before starting.")
            else:
                self._note.configure(text="")
        except tk.TclError:
            pass    # widgets went away under us during shutdown

    # ------------------------------------------------------------------
    # app quit
    # ------------------------------------------------------------------

    def shutdown_sync(self):
        """App-quit hook: take the emulator down with the app.

        Blocking and bounded.  A quit must not leave a game, five CUSE daemons
        and a nested X server orphaned behind a control surface that no longer
        exists — and the CUSE daemons in particular hold real device nodes that
        would then be served by nothing.
        """
        self._stopped = True
        if not rig_available() or sys.platform != "win32":
            return
        if not (self._last_up or self._info.get("cuse_daemons", "0") != "0"):
            return
        try:
            subprocess.run(rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass
