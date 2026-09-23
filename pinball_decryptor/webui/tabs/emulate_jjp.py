"""Emulate JJP tab: run a Jersey Jack game on this PC (web port of the old
Tk ``JJPEmulatePanel``).

Like the Tk panel it is THIN: every step of the launch (mount, jail, dongle,
audio, boards, display, game) lives in ``tools/jjp_emu/watch.sh``.  This
service starts it, stops it, hands the purple Sentinel key to WSL, polls
``status.sh`` and says truthfully what the rig is doing.  The rig facts
(``rig_cmd``, ``state_text``, ``key_failure``, usbipd, the ghost-window
sweep) are ``webui/emulate_jjp_core.py``'s functions, called, not copied.

Exports ``jjp_emulate_iso_var`` (the run logic persists it per project) and
answers ``emulate_shutdown`` (the app-quit fan-out).  ``launch_iso(path)`` is
the Multi-boot tab's "Run in emulator" for a JJP multi-boot ISO.
"""

import os
import subprocess
import sys
import threading
import time

from pinball_decryptor.webui import rig as _rig
from .. import emulate_jjp_core as jjp
from .. import compat
from ..emulate_jjp_common import RigTabMixin, rig_off
from .base import TabService, rpc

INTRO = ("Run a Jersey Jack game on this PC. The game is a native x86-64 "
         "Linux program, so it runs directly — no CPU emulation.\n"
         "The purple JJP USB security key must be plugged in: the game's "
         "code is encrypted with it, so this is not a check that can be "
         "skipped.")

ISO_TIP = ("A JJP release ISO (Clonezilla image). It is mounted READ ONLY and "
           "run in place — nothing is written to it.")

FIX_TIP = ("Force-restart WSL to clear a wedged emulator — a frozen window "
           "with no border, a game that will not stop, or orphaned board "
           "devices. Closes ALL WSL sessions and takes ~15s; your ISO and "
           "settings are untouched.")

VOLUME_TIP = ("This PC's volume for the emulated game and its boot menu - not "
              "the machine's own volume setting. It changes a running game at "
              "once, and it is the same level as the other Emulate tabs.")

#: The status grid, in the Tk panel's order (label, status.sh key).
CELLS = (
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
)

#: Headlines that mean "something is in the way" (drawn as a warning).
_WARN_STATES = {"WSL not answering", "Key not passed through yet",
                "No security key", "Key not accepted",
                "Wrong key for this game"}

#: The footer ladder (Tk's MainWindow.EMULATE_PHASES_JJP, item 118).
PHASES = ("Restore image", "Boot", "Game", "Ready")


class EmulateJJPTab(RigTabMixin, TabService):
    ns = "emulate_jjp"
    key = "Emulate JJP"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("jjp_emulate_iso_var",)

    LOG_PREFIX = "JJP: "
    PHASES = PHASES
    POLL_MS = jjp.POLL_MS
    POLL_IDLE_MS = jjp.POLL_IDLE_MS
    POLL_FIRST_MS = jjp.POLL_FIRST_MS
    _FOOTER_STEPS = jjp.FOOTER_STEPS
    _RESTORE_PCT = jjp.RESTORE_PCT

    def __init__(self, window):
        super().__init__(window)
        # The ISO path is a WINDOW variable so the run logic can persist it
        # into the project anchor and restore it on load.  Deliberately NOT
        # the Stern tab's card variable (a .raw and an .iso in one key is a
        # bug waiting for the first manufacturer switch).
        self.jjp_emulate_iso_var = self.var("iso")
        self._init_rig_state()
        #: sticky key verdict (see _mark_key_failure)
        self._wrong_key = False
        self._auto_attached = False
        self._key_verdict = ("Wrong key for this game",
                             "The plugged-in key runs a different JJP title.")
        ok = jjp.rig_available()
        self.set(intro=INTRO, iso_tip=ISO_TIP, fix_tip=FIX_TIP,
                 volume_tip=VOLUME_TIP, platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 fix_label="Fix stuck state", fix_enabled=True,
                 fix_busy=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=("The JJP emulator rig is missing from tools/jjp_emu — "
                       "this checkout looks incomplete.") if not ok else "",
                 up=False, game="")
        # the Tk panel polled from build(), for every manufacturer
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return jjp.rig_available()

    def on_manufacturer(self, mfr):
        if getattr(self, "_visible", False):
            self._schedule_poll()
        else:
            self._restore_default_phases()

    def on_show(self):
        self._show_own_phases()
        self._reload_volume()
        # entry shows the rig's last known state at once; the next poll
        # repaints within a couple of seconds
        if self._polled_once and not self._busy:
            self._footer_from_info()
        elif not self._busy:
            self._footer_now("idle")
        self._poll_on_show()

    def on_close(self):
        self._stopped = True
        self._cancel_poll()

    def iso_path(self):
        return (self.jjp_emulate_iso_var.get() or "").strip()

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "jjp_emulate_iso", "Select a JJP game ISO",
            [("JJP game image", "*.iso"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.iso_path()))
        if path:
            self.jjp_emulate_iso_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        if self._busy:
            return False
        if self._last_up:
            self._stop_async()
        else:
            self._start_async()
        return True

    @rpc
    def fix_state(self):
        return self._fix_state()

    def launch_iso(self, path):
        """Start the rig on *path* - the Multi-boot tab's 'Run in emulator'
        (item 118), handed a multi-boot install ISO it just built.  Exactly
        the Start button's launch: the rig itself shows the boot menu when the
        image carries one.  Refused, in a log line, while a start or stop is
        already in flight."""
        path = (path or "").strip()
        if not path:
            return False
        if self._busy:
            self._log("JJP: a start or stop is already running - wait for it, "
                      "then start %s." % os.path.basename(path))
            return False
        self.jjp_emulate_iso_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # start / stop
    # ------------------------------------------------------------------
    def _set_go(self, label=None, enabled=None):
        kw = {}
        if label is not None:
            kw["go_label"] = label
        if enabled is not None:
            kw["go_enabled"] = bool(enabled)
        kw["busy"] = self._busy
        kw["go_busy"] = self._go_busy
        self.set(**kw)

    def _start_async(self):
        iso = self.iso_path()
        if not iso and self._info.get("image_mounted") != "1":
            compat.messagebox.showinfo(
                "Emulate",
                "Pick a JJP game ISO first.\n\nIt is mounted read only and run "
                "in place — nothing is written to it.")
            return
        if self._refuse_off():
            return
        if self._info.get("dongle_present") != "1":
            # Not fatal here: the attach below may be exactly what is missing.
            self._log("JJP: security key not visible in WSL yet — attaching.")

        self._busy = True
        self._go_busy = True
        self._wrong_key = False       # a new attempt clears the last verdict
        self._set_go("Starting…", False)

        def work():
            try:
                if not self._attach_dongle():
                    # The key never became visible: stop here with the
                    # guidance instead of a redundant minute of restore + wait.
                    return
                self._log("JJP: starting the rig (this takes a minute on a "
                          "first run — the image has to be restored). Each step "
                          "is shown below as it runs.")
                args = [iso] if iso else []
                rc, saw_wrong_key = self._run_launch(
                    jjp.rig_cmd_root(
                        "watch.sh", *args,
                        env=["PAD_AUDIO_CTL=" + self._audio_ctl_file()]),
                    timeout=1800)
                if saw_wrong_key or rc == 7:
                    self._mark_wrong_key()
                elif rc not in (0, None):
                    self._log("JJP: start failed (exit %d)." % rc)
                elif jjp.rdp_client_running() is False:
                    self._log("JJP: WSLg's window layer is not running (no "
                              "msrdc.exe on this desktop), so the game's "
                              "windows cannot appear and sound has nowhere to "
                              "go. Press 'Fix stuck state' (it restarts WSL) "
                              "and Start again.")
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-jjp-start").start()

    @staticmethod
    def _audio_ctl_file():
        from ..emulate_jjp_common import audio_ctl_file
        return audio_ctl_file()

    def _run_launch(self, cmd, timeout=1800):
        """The launch, streamed: each line logged as printed, the footer
        ladder moved by watch.sh's step headers, and a key verdict pulled
        into the headline the moment the game step prints it.
        Returns ``(returncode, saw_key_failure)``."""
        saw = {"v": False}

        def on_line(line):
            self._footer_line(line)
            verdict = jjp.key_failure(line)
            if verdict and not saw["v"]:
                saw["v"] = True
                self._mark_key_failure(*verdict)

        rc = self._run_streaming(cmd, timeout=timeout, on_line=on_line)
        return rc, saw["v"]

    def _footer_line(self, line):
        """One streamed launch line -> the ladder."""
        for head, kind, pct, text in self._FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        m = self._RESTORE_PCT.match(line)
        if m:
            self._footer("copy", int(m.group(2)),
                         "Restoring the image… %s %s%%" % (m.group(1),
                                                           m.group(2)))

    def _mark_wrong_key(self):
        self._mark_key_failure(*self._key_verdict)

    def _mark_key_failure(self, label, hint):
        """Flip the headline to the key verdict, from any thread.  Sticky so
        the next status poll does not paint "Stopped" over the real reason;
        cleared when the next start begins."""
        self._wrong_key = True
        self._key_verdict = (label, hint)
        self._post(lambda: self.set(state_label=label, state_hint=hint,
                                    tone="warn"))

    def _stop_async(self):
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = True
        self._set_go("Stopping…", False)

        def work():
            try:
                out = subprocess.run(
                    jjp.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=180, creationflags=_rig.CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace").strip()
                self._log("JJP: " + text)
                # A clean stop can still leave frames on the desktop; only
                # when the rig said the display and the matrix are gone.
                if jjp.stop_left_nothing(text):
                    time.sleep(1.0)
                    n = jjp.hide_rig_ghosts()
                    if n:
                        self._log("JJP: hid %d window(s) the stopped rig left "
                                  "on the desktop - WSLg kept their frames "
                                  "after the programs had exited." % n)
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-jjp-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._set_go(enabled=jjp.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # the security key
    # ------------------------------------------------------------------
    def _auto_attach(self):
        """Hand the key to WSL without being asked - ONE SHOT per drop (it
        re-arms in _apply the moment the key is visible again)."""
        if self._auto_attached or self._busy or rig_off():
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
                self._post(self._poll_now)

        threading.Thread(target=work, daemon=True,
                         name="pad-jjp-attach").start()

    def _attach_dongle(self):
        """Hand the key to WSL and WAIT until it is actually there (usbipd
        needs a running distro, and its attach is asynchronous).  True if
        the key ends up visible in WSL."""
        cmd = jjp.attach_dongle_cmd()
        if not cmd:
            self._log("JJP: usbipd-win not found — cannot pass the security "
                      "key through to WSL. Install it from "
                      "https://github.com/dorssel/usbipd-win")
            return False
        try:
            subprocess.run(["wsl.exe", "-e", "true"], timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass
        if self._key_visible_in_wsl():
            self._log("JJP: security key already present in WSL.")
            return True
        for _attempt in (1, 2):
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
                self._log("JJP: the purple JJP key is not plugged into this "
                          "PC.")
                return False
            if "not shared" in low or "bind" in low:
                self._bind_dongle()
            if self._wait_for_key():
                self._log("JJP: security key attached and visible in WSL.")
                return True
            self._log("JJP: key attached but not visible yet — retrying.")
        self._log("JJP: the security key did not appear in WSL. If it is "
                  "plugged in, unplug and replug it, then press Start again.")
        return False

    def _bind_dongle(self):
        exe = jjp.usbipd_path()
        if not exe:
            return
        try:
            subprocess.run([exe, "bind", "--hardware-id", jjp.HASP_VID_PID],
                           timeout=30, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    def _key_visible_in_wsl(self):
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
        for _ in range(tries):
            if self._key_visible_in_wsl():
                return True
            time.sleep(1)
        return False

    # ------------------------------------------------------------------
    # Fix stuck state (wsl --shutdown)
    # ------------------------------------------------------------------
    def _fix_state(self):
        if self._busy:
            return False
        if sys.platform != "win32":
            compat.messagebox.showinfo(
                "Fix stuck state",
                "This recovery restarts WSL and only applies on Windows.")
            return False
        if not compat.messagebox.askyesno(
                "Fix stuck state",
                "Force-restart WSL to clear a wedged emulator?\n\n"
                "Use this when Stop did not work — a frozen window with no "
                "border, a game that will not stop, or the boards left "
                "orphaned.\n\n"
                "It closes EVERYTHING running in WSL (any other WSL terminals "
                "or sessions too) and takes about 15 seconds to come back. Your "
                "ISO, the restored image and your settings are untouched."):
            return False
        if self._refuse_off():
            return False
        self._busy = True
        # Start is only greyed while WSL restarts (Tk): the spinner belongs to
        # the button doing the work
        self._set_go(enabled=False)
        self.set(fix_label="Resetting…", fix_enabled=False, fix_busy=True)

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
                              "processes and orphaned devices are cleared. "
                              "Press Start to run again.")
                else:
                    self._log("JJP: wsl --shutdown returned %d. %s"
                              % (out.returncode, msg))
            except Exception as exc:                       # noqa: BLE001
                self._log("JJP: could not restart WSL: %s" % exc)
            finally:
                self._post(self._reset_done)

        threading.Thread(target=work, daemon=True, name="pad-jjp-fix").start()
        return True

    def _reset_done(self):
        self._busy = False
        self._set_go(enabled=jjp.rig_available())
        self.set(fix_label="Fix stuck state", fix_enabled=True, fix_busy=False)
        # the first status call boots WSL back up and confirms the clean
        # state, which is the feedback that the reset worked
        self._poll_now()

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        info = self._run_status(jjp.rig_cmd("status.sh"))
        # A key the rig cannot see may still be sitting in the PC.  Asked
        # ONLY when it matters, so the ordinary poll stays one WSL call.
        if info and info.get("dongle_present") != "1":
            on_pc = jjp.key_on_pc()
            if on_pc is not None:
                info["key_on_pc"] = "1" if on_pc else "0"
        return info

    def _footer_from_info(self):
        info = self._info
        if self._last_up:
            self._footer_now("run", None, "Game running")
        elif int(info.get("selector_procs") or 0) > 0:
            self._footer_now("techalerts", None, "Boot menu showing…")
        else:
            self._footer_now("idle")

    def _apply(self, info):
        self._info = info
        self._last_up = int(info.get("game_procs") or 0) > 0
        label, hint = jjp.state_text(info)
        if self._wrong_key and not self._last_up:
            label, hint = self._key_verdict
        tone = "ok" if self._last_up else (
            "warn" if label in _WARN_STATES else "")
        values = {}

        def yn(k):
            return "yes" if info.get(k) == "1" else "no"

        if info.get("dongle_present") == "1":
            self._auto_attached = False      # re-arm for the next drop
        values["dongle_present"] = yn("dongle_present")
        values["hasp_port_1947"] = yn("hasp_port_1947")
        values["image_mounted"] = yn("image_mounted")
        values["game"] = info.get("game") or "—"
        values["game_procs"] = info.get("game_procs") or "0"
        rss = int(info.get("game_rss_kb") or 0)
        values["game_rss_kb"] = ("%.1f GB" % (rss / 1024.0 / 1024.0)) \
            if rss else "—"
        up = int(info.get("game_uptime_s") or 0)
        values["game_uptime_s"] = ("%d:%02d" % (up // 60, up % 60)) \
            if up else "—"
        values["nested_display"] = (
            "windowed" if info.get("nested_display", "0") != "0"
            else ("desktop" if self._last_up else "—"))
        nodes = info.get("board_nodes", "0")
        values["board_nodes"] = ("%s device%s" % (
            nodes, "" if nodes == "1" else "s")) if nodes != "0" else "none"
        values["frames_in"] = "%s / %s" % (info.get("frames_in", "0"),
                                           info.get("frames_out", "0"))
        values["led_writes"] = info.get("led_writes", "0")

        # The one note worth interrupting for: a running game with no
        # boards has no switches and no LEDs, and looks like a bug.
        note = ""
        attach = False
        if not jjp.rig_available():
            note = ("The JJP emulator rig is missing from tools/jjp_emu — "
                    "this checkout looks incomplete.")
        elif self._last_up and info.get("board_nodes", "0") == "0":
            note = ("The game is running but the playfield boards are not "
                    "present, so it can see no switches and drive no "
                    "LEDs. Stop and start again to bring them up.")
        elif (not self._last_up and info.get("key_on_pc") == "1"
              and info.get("dongle_present") != "1"):
            note = ("The security key is in this PC but WSL cannot see it "
                    "yet. Handing it over — no need to do anything.")
            attach = True
        elif not self._last_up and info.get("dongle_present") == "0":
            note = ("No security key detected. The game's code is "
                    "encrypted with the purple JJP USB key — plug it in "
                    "before starting.")

        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note=note, up=self._last_up,
                  game=(info.get("game") or "") if self._last_up else "")
        if not self._busy:
            kw["go_label"] = "Stop" if self._last_up else "Start"
            kw["go_enabled"] = jjp.rig_available()
            self._footer_from_info()
        kw["busy"] = self._busy
        kw["go_busy"] = self._go_busy
        self.set(**kw)
        if attach:
            self._auto_attach()

    # ------------------------------------------------------------------
    # app quit
    # ------------------------------------------------------------------
    def emulate_shutdown(self):
        """App-quit hook: take the emulator down with the app (blocking,
        bounded) - a quit must not leave a game, five CUSE daemons and a
        nested X server orphaned behind a control surface that is gone."""
        self._stopped = True
        self._cancel_poll()
        if rig_off() or not jjp.rig_available() or sys.platform != "win32":
            return
        if not (self._last_up or self._info.get("cuse_daemons", "0") != "0"):
            return
        try:
            subprocess.run(jjp.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateJJPTab
