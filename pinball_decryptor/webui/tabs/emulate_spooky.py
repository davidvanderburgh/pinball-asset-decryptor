"""Emulate Spooky tab: run a Spooky Pinball game on this PC from its update
file - the games the rig runs (``emulate_spooky_core.SUPPORTED``), which the
page names.

Built on the American Pinball tab (webui/tabs/emulate_ap.py), the template
every maker's Emulate tab follows (David, PAD-266: "We want the volume and the
ball feed and everything to look consistent between the manufacturers"):

* THIN: every step of the launch (unpack, board, game) lives in
  ``tools/spooky_emu/watch.sh``.  This service starts it (and cancels it),
  stops it, and polls ``status.sh`` - the same keys as AP's.
* The machine is a WINDOW of its own - AP's virtual playfield
  (``tools/ap_emu/appf.py``, the Stern window's page) pointed at this rig's
  board by ``tools/spooky_emu/spkpf.py``: the keys, the service buttons,
  BALLS (Plunge, Drain, Reset balls), Pause and the Volume bar.  It opens
  once the game is in attract, reopens on request, and closes on Stop (its
  stdin is the tab's pipe) or when the game ends.
* Sound is always on; Volume / Mute follow live through the control file
  every Emulate tab shares (``tools/spooky_emu/spkvol.py`` holds the game's
  stream at that level).
* A Cache window (AP's) shows and deletes the builds unpacked in the app's
  Linux.

Exports ``spooky_emulate_file_var`` (the run logic persists it per project)
and answers ``emulate_shutdown`` (the app-quit fan-out).
"""

import os
import subprocess
import sys
import threading
import time

from pinball_decryptor.webui import rig as _rig
from .. import compat
from ...core import rigslot
from .. import emulate_spooky_core as spk
from ..emulate_jjp_common import (RigTabMixin, rig_off, audio_ctl_file,
                                  windows_python,
                                  share_distro)
from .base import TabService, rpc

INTRO = ("Run a Spooky Pinball game on this PC. Supported: %s. The "
         "emulator stands in for the machine's controller board and gives the "
         "game a window, sound and every switch.\n"
         "Pick the machine's update file, or one the Write tab built, to play "
         "a mod before it goes on a USB stick."
         % ", ".join(spk.supported_names()))

FILE_TIP = ("The game's update file, named as the machine wants it "
            "(v….beetlejuice, v….scooby, ….ed, ….looney, tcm-….pkg, "
            "code_H78.pkg, code_UM.pkg, rm-gamecode-….pkg, "
            "ac-gamecode.pkg). It is only read: the emulator unpacks it once "
            "(a few minutes) and keeps it, so the next start is quicker.")

VOLUME_TIP = ("The game's sound on this PC - Volume and Mute follow at once, "
              "while the game plays (the same knob every Emulate tab shares). "
              "The game's own volume is in its service menu.")

SWITCHES_TIP = ("The virtual playfield, as on the American Pinball and Stern "
                "Emulate tabs: every switch, the keyboard, the service "
                "buttons and the balls (Plunge, Drain, Reset balls), Pause "
                "and the volume.")

#: The status grid (label, key into the values _apply computes) - AP's.
CELLS = (
    ("Game", "title"),
    ("Version", "version"),
    ("Switches", "switches"),
    ("Window", "window"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulateSpookyTab(RigTabMixin, TabService):
    ns = "emulate_spooky"
    key = "Emulate Spooky"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("spooky_emulate_file_var",)

    LOG_PREFIX = "Spooky: "
    PHASES = spk.PHASES
    POLL_MS = spk.POLL_MS
    POLL_IDLE_MS = spk.POLL_IDLE_MS
    POLL_FIRST_MS = spk.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.spooky_emulate_file_var = self.var("file")
        self._init_rig_state()
        self._starting = False
        self._cancelling = False
        #: the virtual playfield (spkpf.py), when this app opened one
        self._sw_proc = None
        #: the Cache window: open?, its entries by name, the selection
        self._cache_open = False
        self._cache_entries = {}
        self._cache_sel = []
        ok = spk.rig_available()
        if not ok:
            note = ("The Spooky emulator is missing from tools/spooky_emu - "
                    "this install looks incomplete.")
        elif not spk.platform_ok():
            ok = False
            note = ("The Spooky emulator runs through WSL, so it is available "
                    "on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, file_tip=FILE_TIP, volume_tip=VOLUME_TIP,
                 switches_tip=SWITCHES_TIP, supported=spk.supported_names(),
                 platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, ready=False, game="", cache=None)
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return spk.rig_available()

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

    def file_path(self):
        """This tab's own update file, else the one picked on Select card
        (the Extract input) when it is one the emulator runs - a card already
        picked must not be asked for again."""
        own = (self.spooky_emulate_file_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            path = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            path = ""
        return path if spk.supported_file(path) else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "spooky_emulate_file", "Select a Spooky game update file",
            [("Spooky game update", spk.FILE_PATTERNS), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.file_path()))
        if path:
            self.spooky_emulate_file_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight."""
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
        """End the start in flight: tools/spooky_emu/cancel.sh ends watch.sh
        and everything it started, drops a half-unpacked build and stops any
        game that had come up."""
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Cancelling…", False)
        self._log("Spooky: cancelling the start…")

        def work():
            try:
                out = subprocess.run(
                    spk.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("Spooky: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-cancel").start()
        return True

    @rpc
    def switches(self):
        """Open (or bring back) the virtual playfield for the running game."""
        if rig_off() or not self._last_up:
            return False
        info = dict(self._info)

        def work():
            self._open_switches(info)
        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-switches").start()
        return True

    def launch_file(self, path):
        """Start the rig on *path*, exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.spooky_emulate_file_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # the Cache window (AP's): the builds unpacked in the app's Linux, and
    # deleting them (tools/spooky_emu/cache.sh)
    # ------------------------------------------------------------------
    CACHE_HINT = ("Deleting frees the space now: a build is unpacked again on "
                  "its next Start - nothing is lost (settings and high scores "
                  "are kept apart).")

    @rpc
    def open_cache(self):
        if not spk.rig_available() or not spk.platform_ok():
            return False
        if self._cache_open:
            return True
        self._cache_open = True
        self._cache_sel = []
        self.set(cache={"head": "Reading the cache…", "rows": [], "sel": [],
                        "busy": True, "hint": self.CACHE_HINT})
        self.cache_refresh()
        return True

    def _cache_patch(self, **kw):
        cur = self.get("cache")
        if not cur or not self._cache_open:
            return
        cur = dict(cur)
        cur.update(kw)
        self.set(cache=cur)

    @rpc
    def cache_close(self):
        self._cache_open = False
        self.set(cache=None)
        return True

    @rpc
    def cache_refresh(self):
        if not self._cache_open:
            return False
        self._cache_sel = []
        self._cache_patch(head="Reading the cache…", busy=True, sel=[])
        if rig_off():
            self._post(self._cache_show, ([], None))
            return True

        def work():
            try:
                out = subprocess.run(
                    spk.rig_cmd_root("cache.sh", "--list"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                              # noqa: BLE001
                text = ""
            self._post(self._cache_show, spk.parse_cache(text))

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-cache").start()
        return True

    def _cache_show(self, result):
        if not self._cache_open:
            return
        from ..emulate_core import human_size
        entries, disk = result
        self._cache_entries = {e["name"]: e for e in entries}
        running = (self._info.get("build") or "") if self._last_up else ""
        rows = [{"name": e["name"], "label": spk.cache_label(e),
                 "size": human_size(e["kb"]),
                 "used": time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(e["used"]))
                 if e["used"] else "—",
                 "src": ("running now" if e["name"] == running else e["src"])}
                for e in entries]
        total = sum(e["kb"] for e in entries)
        if not entries:
            head = "Nothing is cached - the next Start unpacks the game."
        else:
            head = "%d item%s — %s" % (len(entries),
                                       "" if len(entries) == 1 else "s",
                                       human_size(total))
            if disk:
                head += " · %s free of %s (the app's Linux)" % (
                    human_size(disk[0]), human_size(disk[1]))
        self._cache_patch(head=head, rows=rows, busy=False, sel=[],
                          hint=self.CACHE_HINT)

    @rpc
    def cache_select(self, names):
        self._cache_sel = [n for n in (names or []) if n in self._cache_entries]
        self._cache_patch(sel=list(self._cache_sel))
        return len(self._cache_sel)

    @rpc
    def cache_delete(self):
        names = list(self._cache_sel)
        if not self._cache_open or not names or rig_off():
            return False
        from ..emulate_core import human_size
        freed = sum(self._cache_entries.get(n, {}).get("kb", 0) for n in names)
        if not compat.messagebox.askyesno(
                "Delete cached items",
                "Delete %d item%s, freeing about %s?\n\nA running game's "
                "build is kept." % (len(names), "" if len(names) == 1 else "s",
                                    human_size(freed))):
            return False
        self._cache_patch(busy=True, hint="Deleting…")

        def work():
            try:
                out = subprocess.run(
                    spk.rig_cmd_root("cache.sh", "--drop", *names),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=600, creationflags=_rig.CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    if line.startswith("refused="):
                        self._log("Spooky: cache: kept %s" % line[8:])
                    elif line.startswith("dropped "):
                        self._log("Spooky: cache: deleted %s" % line[8:])
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: cache delete failed: %s" % exc)
            self._post(self.cache_refresh)

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-cache-drop").start()
        return True

    # ------------------------------------------------------------------
    # the virtual playfield
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """spkpf.py's command line for the running game, or None."""
        table = (info or {}).get("switches_json")
        py = windows_python()
        if not table or not py:
            return None
        # --parent-pipe: the window closes itself when this app closes its
        # stdin (_close_switches)
        cmd = [py, os.path.join(spk.rig_dir(), "spkpf.py"), "--parent-pipe",
               "--slot", info.get("slot") or "0",
               # the status bar's VOL / Mute: the same control file as this tab's
               "--audio-ctl", audio_ctl_file()]
        # the default distro's name when the app's runtime is not in use
        distro = share_distro(spk.rig_distro())
        if distro:
            # the table lives in the app's Linux; Windows reads it through
            # the distro's share
            cmd += ["--distro", distro, "--table",
                    "\\\\wsl.localhost\\%s%s" % (distro, table.replace("/", "\\"))]
        else:
            cmd += ["--table", table]
        return cmd

    def _open_switches(self, info=None):
        if rigslot.hidden():
            # a session's app runs hidden: no window on the desktop, this
            # one included (PAD-309)
            self._log("Spooky: a hidden run opens no playfield window "
                      "(PAD_HIDDEN=0 in this app's environment shows it).")
            return False
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True
        if info is None or not info.get("switches_json"):
            info = self._read_status()
        cmd = self._switch_window_cmd(info or {})
        if not cmd:
            self._log("Spooky: could not open the virtual playfield (no Python "
                      "to run it with, or the game is not running).")
            return False
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=_rig.CREATE_FLAGS)
            return True
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("Spooky: could not open the virtual playfield: %s" % exc)
            return False

    #: how long the window gets to close itself before it is killed
    SW_CLOSE_S = 4.0

    def _close_switches(self, wait=False):
        """Close the virtual playfield, as the AP tab does: closing its stdin
        asks it to close its window and quit; if it has not within
        SW_CLOSE_S, its whole process tree goes."""
        proc, self._sw_proc = self._sw_proc, None
        if proc is None or proc.poll() is not None:
            return

        def work():
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.wait(timeout=self.SW_CLOSE_S)
                return
            except Exception:                              # noqa: BLE001
                pass
            _kill_tree(proc)
        if wait:
            work()
        else:
            threading.Thread(target=work, daemon=True,
                             name="pad-spooky-switches-close").start()

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
        path = self.file_path()
        if not path:
            compat.messagebox.showinfo(
                "Emulate",
                "Pick a game's update file first - the machine's own, or one "
                "the Write tab built.\n\n"
                "Supported: %s." % ", ".join(spk.supported_names()))
            return
        if not spk.supported_file(path):
            compat.messagebox.showinfo(
                "Emulate",
                "%s is not an update of a Spooky game the emulator runs - "
                "it tells them apart by the file's name, as the machine "
                "does.\n\nSupported: %s."
                % (os.path.basename(path), ", ".join(spk.supported_names())))
            return
        if not os.path.isfile(path):
            compat.messagebox.showinfo("Emulate", "There is no file at\n%s"
                                       % path)
            return
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

        def work():
            try:
                self._log("Spooky: starting %s (a first start unpacks the "
                          "update - a few minutes; then the game loads for "
                          "a minute or two)." % os.path.basename(path))
                rc = self._run_streaming(
                    spk.rig_cmd_root(
                        "watch.sh", _rig.wsl_path(path),
                        # sound always on: Volume / Mute follow live through
                        # the control file (spkvol.py), so unmuting a game
                        # started muted works
                        # the rig board names the run by its title
                        # (PAD-296); the file's name says which
                        env=["PAD_VISIBLE=1", "PAD_AUDIO=1",
                             "PAD_AUDIO_CTL=%s" % _rig.wsl_path(audio_ctl_file()),
                             "PAD_TITLE=%s" % spk.title_of(path)]
                        + rigslot.board_env() + rigslot.quiet_env()),
                    timeout=1800, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("Spooky: start cancelled.")
                elif rc not in (0, None):
                    self._log("Spooky: start failed (exit %d). %s"
                              % (rc, spk.EXIT_TEXT.get(rc, "")))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in spk.FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        if line.startswith("progress "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            self._footer("copy", pct, "Unpacking the game… %d%%" % pct)

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
                    spk.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("Spooky: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("Spooky: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-spooky-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=spk.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        return self._run_status(spk.rig_cmd("status.sh"))

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
            # the game ended (its window's X, or it quit): so does its window
            self._started_here = False
            self._close_switches()
        up = self._last_up
        ready = up and info.get("attract") == "1"
        label, hint = spk.state_text(info)
        tone = "ok" if ready else (
            "warn" if label == "WSL not answering" else "")
        rss = int(info.get("rss_kb") or 0)
        secs = int(info.get("uptime_s") or 0)
        game = spk.game_name(info) if up else ""
        values = {
            "title": game or "—",
            "version": (info.get("version") or "—") if up else "—",
            "switches": (info.get("switches") or "—") if up else "—",
            "window": (info.get("window") or "—").replace("x", " × ")
            if up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if up and rss else "—",
            "uptime": ("%d:%02d" % (secs // 60, secs % 60)) if up and secs
            else "—",
        }
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if spk.rig_available() else self.get("note"),
                  up=up, ready=ready, game=game)
        if not self._busy:
            kw["go_label"] = "Stop" if up else "Start"
            kw["go_enabled"] = spk.rig_available()
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
        self._close_switches(wait=True)
        if rig_off() or not spk.rig_available() or not spk.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(spk.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


def _kill_tree(proc):
    """Kill *proc* and everything it started (the window's Edge)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, creationflags=_rig.CREATE_FLAGS)
        else:
            proc.kill()
    except Exception:                                      # noqa: BLE001
        pass


TAB = EmulateSpookyTab
