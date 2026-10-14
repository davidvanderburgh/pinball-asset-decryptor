"""Emulate BoF tab: run a Barrels of Fun game on this PC.

THIN, like the JJP tab: every step of the launch (decrypt, boards, game)
lives in ``tools/bof_emu/watch.sh``.  This service starts it (and cancels
it), stops it, and polls ``status.sh``.

The machine's switches are a WINDOW of their own, as the Stern and JJP rigs'
are: ``tools/bof_emu/bofpf.py``, the game's own playfield drawing with every
switch on it plus a labelled list, run on the app's Windows Python.  This tab
opens it once the game has found its boards, reopens it on request, and
closes it on Stop.

Exports ``bof_emulate_fun_var`` (the run logic persists it per project) and
answers ``emulate_shutdown`` (the app-quit fan-out).  ``launch_fun(path)``
starts a given build - the hook for "play what Write just built".
"""

import os
import subprocess
import sys
import threading

from pinball_decryptor.webui import rig as _rig
from .. import compat
from ...core import rigslot
from .. import emulate_bof_core as bof
from ..emulate_jjp_common import (RigTabMixin, rig_off, load_audio_ctl,
                                  windows_python)
from .base import TabService, rpc

INTRO = ("Run a Barrels of Fun game on this PC - Dune, Winchester Mystery "
         "House or Labyrinth. The game is a native Linux program, so it runs "
         "directly; the emulator stands in for the machine's boards.\n"
         "Pick the machine's .fun update file, or one the Write tab built, to "
         "play a mod before it goes on a USB stick.")

FUN_TIP = ("A Barrels of Fun update file (.fun). It is only read: the "
           "emulator unpacks a copy inside the app's Linux, and keeps the last "
           "two so the next start is instant.")

SOUND_TIP = ("Play the game's sound on this PC. Applies when the game starts; "
             "the game's own volume is in its service menu.")

SWITCHES_TIP = ("The machine's switches: the game's own playfield drawing with "
                "every switch on it, and a labeled list. Hold a switch with "
                "the mouse, right-click to latch it.")

#: The status grid (label, key into the values _apply computes).
CELLS = (
    ("Game", "title"),
    ("Boards", "boards"),
    ("Balls", "balls"),
    ("LEDs lit", "leds"),
    ("Drivers set up", "drivers"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulateBoFTab(RigTabMixin, TabService):
    ns = "emulate_bof"
    key = "Emulate BoF"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("bof_emulate_fun_var",)

    LOG_PREFIX = "BoF: "
    PHASES = bof.PHASES
    POLL_MS = bof.POLL_MS
    POLL_IDLE_MS = bof.POLL_IDLE_MS
    POLL_FIRST_MS = bof.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.bof_emulate_fun_var = self.var("fun")
        self._init_rig_state()
        #: a Start is in flight (the button is Cancel) / its cancel is
        self._starting = False
        self._cancelling = False
        #: the switch window (bofpf.py), when this app opened one
        self._sw_proc = None
        ok = bof.rig_available()
        if not ok:
            note = ("The Barrels of Fun emulator is missing from "
                    "tools/bof_emu - this install looks incomplete.")
        elif not bof.platform_ok():
            ok = False
            note = ("The Barrels of Fun emulator runs through WSL, so it is "
                    "available on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, fun_tip=FUN_TIP, sound_tip=SOUND_TIP,
                 switches_tip=SWITCHES_TIP,
                 platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, ready=False, game="")
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return bof.rig_available()

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

    def fun_path(self):
        """This tab's own .fun, else the one picked on Select card (the
        Extract input) - that page lists Emulate as working "straight from
        the card", so a card already picked must not be asked for again."""
        own = (self.bof_emulate_fun_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            path = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            path = ""
        return path if path.lower().endswith(".fun") else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "bof_emulate_fun", "Select a Barrels of Fun .fun file",
            [("Barrels of Fun update", "*.fun"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.fun_path()))
        if path:
            self.bof_emulate_fun_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight (the button
        says so: unpacking a 4 GB build off a busy disk can take a long
        time, and nothing else could end it)."""
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
        """End the start in flight: tools/bof_emu/cancel.sh ends watch.sh and
        everything it started (the decrypt included), drops the half-unpacked
        build and stops any game that had come up."""
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Canceling…", False)
        self._log("BoF: canceling the start…")

        def work():
            try:
                out = subprocess.run(
                    bof.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("BoF: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("BoF: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-bof-cancel").start()
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
                         name="pad-bof-switches").start()
        return True

    def launch_fun(self, path):
        """Start the rig on *path* (a .fun), exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.bof_emulate_fun_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # the switch window
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """bofpf.py's command line for the running game, or None."""
        title = info.get("title")
        py = windows_python()
        if not title or not py:
            return None
        cmd = [py, os.path.join(bof.rig_dir(), "bofpf.py"), "--title", title,
               "--slot", info.get("slot") or "0"]
        distro = bof.rig_distro()
        if distro:
            cmd += ["--distro", distro]
            art = info.get("art") or ""
            if art.startswith("/"):
                # the picture lives in the app's Linux; Windows reads it
                # through the distro's share
                cmd += ["--art", "\\\\wsl.localhost\\%s%s"
                        % (distro, art.replace("/", "\\"))]
        return cmd

    def _open_switches(self, info=None):
        if rigslot.hidden():
            # a session's app runs hidden: no window on the desktop, this
            # one included (PAD-309)
            self._log("BoF: a hidden run opens no playfield window "
                      "(PAD_HIDDEN=0 in this app's environment shows it).")
            return False
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True              # already open (it keeps itself on top)
        if info is None or not info.get("title"):
            info = self._read_status()
        cmd = self._switch_window_cmd(info or {})
        if not cmd:
            self._log("BoF: could not open the switch window (no Python to "
                      "run it with, or the game is not running).")
            return False
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_rig.CREATE_FLAGS)
            return True
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("BoF: could not open the switch window: %s" % exc)
            return False

    def _close_switches(self):
        """The window also closes itself once the game stops answering;
        this is the prompt version, for Stop and app quit."""
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
        fun = self.fun_path()
        if not fun:
            compat.messagebox.showinfo(
                "Emulate",
                "Pick a Barrels of Fun .fun file first - the machine's own "
                "update file, or one the Write tab built.")
            return
        if not os.path.isfile(fun):
            compat.messagebox.showinfo("Emulate", "There is no file at\n%s"
                                       % fun)
            return
        # Bon Jovi can't be emulated yet: its .fun is a signed disk image the
        # rig's decrypt step can't open, and it has no hardware profile.  Say
        # so up front instead of failing deep in watch.sh.
        try:
            from pinball_decryptor.plugins.bof.pipeline import detect_game
            from pinball_decryptor.plugins.bof.manufacturer import BONJOVI_EMU
            if detect_game(fun) == "bonjovi":
                compat.messagebox.showinfo("Emulate", BONJOVI_EMU)
                return
        except Exception:
            pass
        if self._refuse_off():
            return
        self._busy = True
        # No spinner on the button while starting: it is the Cancel button
        # now, and the footer ladder shows the progress.
        self._go_busy = False
        self._starting = True
        self._cancelling = False
        self._started_here = True
        self._set_go("Cancel", True)
        _vol, muted = load_audio_ctl()

        def work():
            try:
                self._log("BoF: starting %s (a first start unpacks the build "
                          "- a minute or two; the next is instant)."
                          % os.path.basename(fun))
                rc = self._run_streaming(
                    bof.rig_cmd_root(
                        "watch.sh", _rig.wsl_path(fun),
                        env=["BOF_KEYS=" + bof.title_keys(),
                             "PAD_VISIBLE=1",
                             "PAD_AUDIO=%d" % (0 if muted else 1)]
                        + rigslot.board_env() + rigslot.quiet_env()),
                    timeout=1800, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("BoF: start canceled.")
                elif rc not in (0, None):
                    self._log("BoF: start failed (exit %d). %s"
                              % (rc, bof.EXIT_TEXT.get(rc, "")))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("BoF: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-bof-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in bof.FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        if line.startswith("progress "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self._footer("copy", pct, "Decrypting the game… %d%%" % pct)

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
                    bof.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("BoF: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("BoF: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-bof-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=bof.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        return self._run_status(bof.rig_cmd("status.sh"))

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
        hw = bof.hw_state(info)
        ready = bool((hw.get("status") or {}).get("hardware_connected"))
        label, hint = bof.state_text(info)
        tone = "ok" if self._last_up and ready else (
            "warn" if label == "WSL not answering" else "")
        title = info.get("title") if self._last_up else ""
        rss = int(info.get("rss_kb") or 0)
        up = int(info.get("uptime_s") or 0)
        values = {
            "title": bof.title_name(title) if title else "—",
            "boards": bof.boards_text(hw) if self._last_up else "—",
            "balls": bof.balls_text(hw) if self._last_up else "—",
            "leds": str(hw.get("leds_lit", "—")) if self._last_up else "—",
            "drivers": str(hw.get("drivers_configured", "—"))
            if self._last_up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if rss else "—",
            "uptime": ("%d:%02d" % (up // 60, up % 60)) if up else "—",
        }
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if bof.rig_available() else self.get("note"),
                  up=self._last_up, ready=ready,
                  game=bof.title_name(title) if title else "")
        if not self._busy:
            kw["go_label"] = "Stop" if self._last_up else "Start"
            kw["go_enabled"] = bof.rig_available()
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
        if rig_off() or not bof.rig_available() or not bof.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(bof.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateBoFTab
