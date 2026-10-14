"""Emulate DP tab: run a Dutch Pinball game (The Big Lebowski, Alice's
Adventures in Wonderland) on this PC.

THIN, like the BoF tab: every step of the launch (prepare the build off the
disk image, lay an update over it, start the game) lives in
``tools/dp_emu/watch.sh``.  This service starts it (and cancels it), stops
it, and polls ``status.sh``.

The machine's switches are a WINDOW of their own, as the other rigs' are:
``tools/dp_emu/dppf.py`` - The Big Lebowski's own machine view (machine.png,
with every switch where machine.yaml puts it) plus a labelled list; Alice's
switches as a list - run on the app's Windows Python.  This tab opens it once the game is up, reopens it on
request, and closes it on Stop.

Exports ``dp_emulate_img_var`` / ``dp_emulate_zip_var`` (the run logic
persists them per project) and answers ``emulate_shutdown`` (the app-quit
fan-out).  ``launch_update(path)`` starts the image with a given update -
the hook for "play what Write just built".
"""

import os
import subprocess
import sys
import threading

from pinball_decryptor.webui import rig as _rig
from .. import compat
from ...core import rigslot
from .. import emulate_dp_core as dp
from ..emulate_jjp_common import (RigTabMixin, rig_off, load_audio_ctl,
                                  windows_python,
                                  share_distro)
from .base import TabService, rpc

INTRO = ("Run a Dutch Pinball game on this PC - The Big Lebowski or Alice's "
         "Adventures in Wonderland. The emulator stands in for the machine's "
         "controller board and gives the game a window, sound and every "
         "switch.\n"
         "Pick the machine's disk image. For The Big Lebowski you can also lay "
         "an update over it - the factory's, or one the Write tab built, to "
         "play a mod before it goes on a USB stick.")

IMG_TIP = ("The machine's disk image (.img) - for Alice's Adventures in "
           "Wonderland, its full_image installer. It is only read: the "
           "emulator copies the game out of it once (a few minutes, several "
           "GB) and keeps the last two, so the next start is quick. The update "
           "zips alone cannot run - most of the game's pictures and sounds "
           "exist only on the machine's disk.")

ZIP_TIP = ("Optional, The Big Lebowski only: an update (.zip), laid over the "
           "version on the disk image the way the machine installs it. Leave "
           "empty to play the image as it is.")

SOUND_TIP = ("Play the game's sound on this PC. Applies when the game starts; "
             "the game's own volume is in its service menu.")

SWITCHES_TIP = ("The machine's switches: the game's own machine view with every "
                "switch on it, and a labeled list. Hold a switch with the "
                "mouse, right-click to latch it.")

#: The status grid (label, key into the values _apply computes).
CELLS = (
    ("Game", "title"),
    ("Version", "version"),
    ("Switches", "switches"),
    ("Window", "window"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulateDPTab(RigTabMixin, TabService):
    ns = "emulate_dp"
    key = "Emulate DP"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("dp_emulate_img_var", "dp_emulate_zip_var")

    LOG_PREFIX = "DP: "
    PHASES = dp.PHASES
    POLL_MS = dp.POLL_MS
    POLL_IDLE_MS = dp.POLL_IDLE_MS
    POLL_FIRST_MS = dp.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.dp_emulate_img_var = self.var("img")
        self.dp_emulate_zip_var = self.var("zip")
        self._init_rig_state()
        self._starting = False
        self._cancelling = False
        #: the switch window (dppf.py), when this app opened one
        self._sw_proc = None
        ok = dp.rig_available()
        if not ok:
            note = ("The Dutch Pinball emulator is missing from "
                    "tools/dp_emu - this install looks incomplete.")
        elif not dp.platform_ok():
            ok = False
            note = ("The Dutch Pinball emulator runs through WSL, so it is "
                    "available on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, img_tip=IMG_TIP, zip_tip=ZIP_TIP,
                 sound_tip=SOUND_TIP, switches_tip=SWITCHES_TIP,
                 platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, game="")
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return dp.rig_available()

    def on_manufacturer(self, mfr):
        if getattr(self, "_visible", False):
            self._schedule_poll()
        else:
            self._restore_default_phases()

    def on_show(self):
        self._show_own_phases()
        self._reload_volume()
        if self._polled_once and not self._busy:
            self._footer_from_info()
        elif not self._busy:
            self._footer_now("idle")
        self._poll_on_show()

    def on_close(self):
        self._stopped = True
        self._cancel_poll()

    def _picked(self):
        """The Select card input (the Extract tab's), when it is one of
        ours - that page lists Emulate as working straight from the card."""
        card = getattr(self.window, "extract_input_var", None)
        try:
            return (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            return ""

    def img_path(self):
        own = (self.dp_emulate_img_var.get() or "").strip()
        if own:
            return own
        card = self._picked()
        return card if dp.is_image(card) else ""

    def zip_path(self):
        own = (self.dp_emulate_zip_var.get() or "").strip()
        if own:
            return own
        card = self._picked()
        return card if dp.is_update(card) else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "dp_emulate_img", "Select a Dutch Pinball disk image",
            [("Disk image", "*.img *.bin *.raw"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.img_path()))
        if path:
            self.dp_emulate_img_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def browse_zip(self):
        path = self.window.ask_open(
            "dp_emulate_zip", "Select a Dutch Pinball update",
            [("Dutch Pinball update", "*.zip"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(
                self.zip_path() or self.img_path()))
        if path:
            self.dp_emulate_zip_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight (a first
        start copies several GB off the image)."""
        if self._starting and not self._cancelling:
            return self.cancel()
        if self._busy:
            return False
        if self._last_up:
            self._stop_async()
        else:
            self._start_async()
        return True

    @rpc
    def cancel(self):
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Canceling…", False)
        self._log("DP: canceling the start…")

        def work():
            try:
                out = subprocess.run(
                    dp.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("DP: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("DP: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-dp-cancel").start()
        return True

    @rpc
    def switches(self):
        """Open (or bring back) the switch window for the running game."""
        if rig_off() or not self._last_up:
            return False
        info = dict(self._info)

        def work():
            self._open_switches(info)
        threading.Thread(target=work, daemon=True,
                         name="pad-dp-switches").start()
        return True

    def launch_update(self, path):
        """Start the rig on the picked image with *path* (an update .zip)
        laid over it, exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.dp_emulate_zip_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # the switch window
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """dppf.py's command line for the running game, or None."""
        table = info.get("switches_json")
        py = windows_python()
        if not table or not py:
            return None
        cmd = [py, os.path.join(dp.rig_dir(), "dppf.py"),
               "--slot", info.get("slot") or "0",
               "--title", dp.title_name(info) or "Dutch Pinball"]
        # the default distro's name when the app's runtime is not in use
        distro = share_distro(dp.rig_distro())
        if distro:
            # the table (and the machine view it names) live in the app's
            # Linux; Windows reads them through the distro's share
            cmd += ["--distro", distro, "--table",
                    "\\\\wsl.localhost\\%s%s" % (distro, table.replace("/", "\\"))]
        else:
            cmd += ["--table", table]
        return cmd

    def _open_switches(self, info=None):
        if rigslot.hidden():
            # a session's app runs hidden: no window on the desktop, this
            # one included (PAD-309)
            self._log("DP: a hidden run opens no playfield window "
                      "(PAD_HIDDEN=0 in this app's environment shows it).")
            return False
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True
        if info is None or not info.get("switches_json"):
            info = self._read_status()
        cmd = self._switch_window_cmd(info or {})
        if not cmd:
            self._log("DP: could not open the switch window (no Python to "
                      "run it with, or the game is not running).")
            return False
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_rig.CREATE_FLAGS)
            return True
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("DP: could not open the switch window: %s" % exc)
            return False

    def _close_switches(self):
        proc, self._sw_proc = self._sw_proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:                              # noqa: BLE001
                pass

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
        kw["starting"] = self._starting
        self.set(**kw)

    def _start_async(self):
        img = self.img_path()
        upd = self.zip_path()
        if not img:
            compat.messagebox.showinfo(
                "Emulate",
                "Pick the machine's disk image first (.img). The update zips "
                "alone cannot run: most of the game's pictures and sounds "
                "exist only on the machine's disk.")
            return
        for p in (img, upd):
            if p and not os.path.isfile(p):
                compat.messagebox.showinfo("Emulate",
                                           "There is no file at\n%s" % p)
                return
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = False
        self._starting = True
        self._cancelling = False
        self._started_here = True
        self._set_go("Cancel", True)
        _vol, muted = load_audio_ctl()
        args = [_rig.wsl_path(img)] + ([_rig.wsl_path(upd)] if upd else [])

        def work():
            try:
                self._log("DP: starting %s%s (a first start copies the game "
                          "off the image - a few minutes; the next is quick)."
                          % (os.path.basename(img),
                             " + " + os.path.basename(upd) if upd else ""))
                rc = self._run_streaming(
                    dp.rig_cmd_root(
                        "watch.sh", *args,
                        env=["PAD_VISIBLE=1",
                             "PAD_AUDIO=%d" % (0 if muted else 1),
                             "PAD_LABEL=PAD"] + rigslot.board_env()
                        + rigslot.quiet_env()),
                    timeout=3600, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("DP: start canceled.")
                elif rc not in (0, None):
                    self._log("DP: start failed (exit %d). %s"
                              % (rc, dp.EXIT_TEXT.get(rc, "")))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("DP: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-dp-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in dp.FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        if line.startswith("progress "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self._footer("copy", pct, "Copying the game off the image… %d%%"
                         % pct)

    def _stop_async(self):
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = True
        self._started_here = False
        self._set_go("Stopping…", False)
        self._close_switches()

        def work():
            try:
                out = subprocess.run(
                    dp.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("DP: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("DP: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-dp-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=dp.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        return self._run_status(dp.rig_cmd("status.sh"))

    def _footer_from_info(self):
        if self._last_up:
            self._footer_now("run", None, "Game running")
        else:
            self._footer_now("idle")

    def _apply(self, info):
        self._info = info
        was_up = self._last_up
        self._last_up = info.get("running") == "1"
        if was_up and not self._last_up:
            self._started_here = False
            self._close_switches()
            if not self._busy:           # not our own Stop: say how it ended
                self._log("DP: " + dp.ended_text(info.get("last_exit")))
        label, hint = dp.state_text(info)
        tone = "ok" if self._last_up else (
            "warn" if label == "WSL not answering" else "")
        up = self._last_up
        rss = int(info.get("rss_kb") or 0)
        secs = int(info.get("uptime_s") or 0)
        values = {
            "title": dp.title_name(info) if up else "—",
            "version": (info.get("version") or "—") if up else "—",
            "switches": (info.get("switches") or "—") if up else "—",
            # "1366x768 480x480" -> "1366 × 768 + 480 × 480" (Alice has two)
            "window": " + ".join(w.replace("x", " × ") for w in
                                 (info.get("window") or "").split()) or "—"
            if up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if up and rss else "—",
            "uptime": ("%d:%02d" % (secs // 60, secs % 60)) if up and secs
            else "—",
        }
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if dp.rig_available() else self.get("note"),
                  up=up, game=dp.title_name(info) if up else "")
        if not self._busy:
            kw["go_label"] = "Stop" if up else "Start"
            kw["go_enabled"] = dp.rig_available()
            self._footer_from_info()
        kw["busy"] = self._busy
        kw["go_busy"] = self._go_busy
        kw["starting"] = self._starting
        self.set(**kw)

    # ------------------------------------------------------------------
    # app quit
    # ------------------------------------------------------------------
    def emulate_shutdown(self):
        """App-quit hook: stop the game this app started (bounded), and
        nothing else - a run it merely saw is somebody else's."""
        self._stopped = True
        self._cancel_poll()
        self._close_switches()
        if rig_off() or not dp.rig_available() or not dp.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(dp.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateDPTab
