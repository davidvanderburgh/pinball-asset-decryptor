"""Emulate AP tab: run an American Pinball game (Houdini, Oktoberfest, Hot
Wheels, Legends of Valhalla, Galactic Tank Force) on this PC from its
game-code .pkg.

THIN, like the BoF tab: every step of the launch (set the rig's Python up
the first time, unpack the .pkg, start the game) lives in
``tools/ap_emu/watch.sh``.  This service starts it (and cancels it), stops
it, and polls ``status.sh``.

The machine's switches are a WINDOW of their own, as the other rigs' are:
``tools/ap_emu/appf.py`` - the game's own playfield picture with its
switches on it, plus a labelled list and the ball controls (Plunge, Drain) -
run on the app's Windows Python.  This tab opens it once the game is up,
reopens it on request, and closes it on Stop.

Exports ``ap_emulate_pkg_var`` (the run logic persists it per project) and
answers ``emulate_shutdown`` (the app-quit fan-out).  ``launch_pkg(path)``
starts a given .pkg - the hook for "play what Write just built".
"""

import os
import subprocess
import sys
import threading
import time

from pinball_decryptor.webui import rig as _rig
from .. import compat
from ...core import rigslot, runtime
from .. import emulate_ap_core as ap
from .. import runtime_prompt as _runtime_ui
from ..emulate_jjp_common import (RigTabMixin, rig_off, audio_ctl_file,
                                  windows_python,
                                  share_distro)
from .base import TabService, rpc

INTRO = ("Run an American Pinball game on this PC - Houdini, Oktoberfest, "
         "Hot Wheels, Legends of Valhalla or Galactic Tank Force. The "
         "emulator stands in for the machine's controller board and gives the "
         "game a window, sound and every switch.\n"
         "Pick the game's code file (.pkg) - the one the machine installs, or "
         "one the Write tab built, to play a mod before it goes on a USB "
         "stick.")

PKG_TIP = ("The game's code file (.pkg), as American Pinball publishes it. It "
           "is only read: the emulator unpacks it once (under a minute) and "
           "keeps it, so the next start is quick.")

VOLUME_TIP = ("The game's sound on this PC - Volume and Mute follow at once, "
              "while the game plays (the same knob every Emulate tab shares). "
              "The game's own volume is in its service menu.")

SWITCHES_TIP = ("The virtual playfield, as on the Stern Emulate tab: the game's "
                "playfield with its switches and lights, the keyboard, the "
                "service buttons, the coin door and the balls (Plunge, "
                "Drain, Reset balls), Pause and the volume.")

#: The status grid (label, key into the values _apply computes).
CELLS = (
    ("Game", "title"),
    ("Version", "version"),
    ("Switches", "switches"),
    ("Window", "window"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulateAPTab(RigTabMixin, TabService):
    ns = "emulate_ap"
    key = "Emulate AP"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("ap_emulate_pkg_var",)

    LOG_PREFIX = "AP: "
    PHASES = ap.PHASES
    POLL_MS = ap.POLL_MS
    POLL_IDLE_MS = ap.POLL_IDLE_MS
    POLL_FIRST_MS = ap.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.ap_emulate_pkg_var = self.var("pkg")
        self._init_rig_state()
        self._starting = False
        self._cancelling = False
        #: the switch window (appf.py), when this app opened one
        self._sw_proc = None
        #: the Cache window: open?, its entries by name, the selection
        self._cache_open = False
        self._cache_entries = {}
        self._cache_sel = []
        #: Set up emulator… is working
        self._setting_up = False
        ok = ap.rig_available()
        if not ok:
            note = ("The American Pinball emulator is missing from "
                    "tools/ap_emu - this install looks incomplete.")
        elif not ap.platform_ok():
            ok = False
            note = ("The American Pinball emulator runs through WSL, so it "
                    "is available on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, pkg_tip=PKG_TIP, volume_tip=VOLUME_TIP,
                 switches_tip=SWITCHES_TIP, platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, game="", cache=None,
                 setup_msg="", setup_btn=False, setup_label=ap.SETUP_LABEL,
                 setup_enabled=True)
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return ap.rig_available()

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

    def pkg_path(self):
        """The tab's own field, else the Select card input (the Extract
        tab's) when it is a .pkg - that page lists Emulate as working
        straight from the file."""
        own = (self.ap_emulate_pkg_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            card = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            card = ""
        return card if ap.is_pkg(card) else ""

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "ap_emulate_pkg", "Select an American Pinball game-code file",
            [("American Pinball game code", "*.pkg"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.pkg_path()))
        if path:
            self.ap_emulate_pkg_var.set(os.path.normpath(path))
        return path or ""

    @rpc
    def toggle(self):
        """Start / Stop - and Cancel while a start is in flight (the first
        one sets the emulator up, a few minutes)."""
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
        self._log("AP: canceling the start…")

        def work():
            try:
                out = subprocess.run(
                    ap.rig_cmd_root("cancel.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("AP: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-ap-cancel").start()
        return True

    @rpc
    def switches(self):
        """Open (or bring back) the switch window for the running game.  One
        already open is brought to the front: it opens while the game's own
        windows hold the focus, so it could sit behind them, and this button
        then did nothing at all (PAD-295)."""
        if rig_off() or not self._last_up:
            return False
        info = dict(self._info)

        def work():
            proc = self._sw_proc
            if proc is not None and proc.poll() is None:
                if not raise_window(_window_title(info)):
                    self._log("AP: the playfield window is open but could "
                              "not be brought to the front - look for it on "
                              "the taskbar.")
                return
            self._open_switches(info)
        threading.Thread(target=work, daemon=True,
                         name="pad-ap-switches").start()
        return True

    # ------------------------------------------------------------------
    # Set up emulator…, as the Stern tab has: the app's own Linux (when it
    # is missing or out of date) and the Python the games run on, ahead of
    # the first Start
    # ------------------------------------------------------------------
    @rpc
    def setup(self):
        """Set up emulator…: install or update the app's own Linux (the
        shared runtime_prompt ladder, with its consent for a replace), then
        run the rig's setup.sh there (the one-time envs)."""
        if self._setting_up or rig_off() or not ap.platform_ok():
            return False
        if self._busy or self._last_up:
            self._log("AP: the game is running - stop it first.")
            return False
        rt = (self._info or {}).get("_rt")
        steps = []
        if rt in ("absent", "stale") and _runtime_ui.can_install():
            steps.append("%s the Linux this app runs its emulators in "
                         "(PAD-Runtime, a one-time download)"
                         % ("Install" if rt == "absent" else "Update"))
        steps.append("Download the Python the American Pinball games run on, "
                     "inside that Linux (about 1 GB, once)")
        if not compat.messagebox.askyesno(
                "Set up the emulator",
                "This will:\n\n" + "\n\n".join("  •  " + x for x in steps)
                + "\n\nIt takes a few minutes; you can watch it in the log. "
                  "Nothing on the Windows side is touched, and nothing is "
                  "removed.\n\nGo ahead?"):
            return False
        self._setting_up = True
        self._busy = True
        self.set(setup_enabled=False, setup_label=ap.SETUP_BUSY)
        self._set_go(enabled=False)
        say = lambda m: self._log("AP: %s" % m)              # noqa: E731
        pct = {"at": -10}

        def progress(done, total):
            if total and int(done * 100 / total) >= pct["at"] + 10:
                pct["at"] = int(done * 100 / total)
                say("downloading… %d%% of %d MB"
                    % (pct["at"], total // (1024 * 1024)))

        def ask():
            return bool(self.ctx.loop.call(_runtime_ui.ask_before_replacing))

        def work():
            ok = False
            try:
                if rt in ("absent", "stale") and _runtime_ui.can_install():
                    state = _runtime_ui.ensure(say=say, progress=progress,
                                               ask=ask)
                    runtime.invalidate()
                    if state != "ready":
                        say("the emulator's Linux is not set up, so the "
                            "Python was not downloaded either.")
                        return
                say("downloading the Python the games run on (about 1 GB, "
                    "a few minutes)…")
                rc = self._run_streaming(ap.rig_cmd_root("setup.sh"),
                                         timeout=3600)
                ok = rc in (0, None)
                say("the emulator is set up - Start is quick now."
                    if ok else "setup did not finish (exit %s) - see above."
                    % rc)
            except Exception as exc:                       # noqa: BLE001
                say("setup failed: %s" % exc)
            finally:
                self._setting_up = False

                def done():
                    self.set(setup_enabled=True, setup_label=ap.SETUP_LABEL)
                self._post(done)
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-ap-setup").start()
        return True

    # ------------------------------------------------------------------
    # the Cache window (as Stern's Emulate tab has): the unpacked builds and
    # the one-time setup, and deleting them (tools/ap_emu/cache.sh)
    # ------------------------------------------------------------------
    CACHE_HINT = ("Deleting frees the space now: a build is unpacked again on "
                  "its next Start, the setup downloaded again - nothing is "
                  "lost.")

    @rpc
    def open_cache(self):
        if not ap.rig_available() or not ap.platform_ok():
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
                    ap.rig_cmd_root("cache.sh", "--list"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                              # noqa: BLE001
                text = ""
            self._post(self._cache_show, ap.parse_cache(text))

        threading.Thread(target=work, daemon=True,
                         name="pad-ap-cache").start()
        return True

    def _cache_show(self, result):
        if not self._cache_open:
            return
        from ..emulate_core import human_size
        entries, disk = result
        self._cache_entries = {e["name"]: e for e in entries}
        running = (self._info.get("build") or "") if self._last_up else ""
        rows = [{"name": e["name"], "label": ap.cache_label(e),
                 "size": human_size(e["kb"]),
                 "used": time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(e["used"]))
                 if e["used"] else "—",
                 "src": ("running now" if e["name"] == running else e["src"])}
                for e in entries]
        total = sum(e["kb"] for e in entries)
        if not entries:
            head = ("Nothing is cached - the first Start sets the emulator up "
                    "and unpacks the game.")
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
        extra = ("\n\nThe emulator setup downloads again (about 1 GB) on the "
                 "next Start." if "envs" in names else "")
        if not compat.messagebox.askyesno(
                "Delete cached items",
                "Delete %d item%s, freeing about %s?\n\nA running game's "
                "build is kept.%s" % (len(names), "" if len(names) == 1 else "s",
                                      human_size(freed), extra)):
            return False
        self._cache_patch(busy=True, hint="Deleting…")

        def work():
            try:
                out = subprocess.run(
                    ap.rig_cmd_root("cache.sh", "--drop", *names),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=600, creationflags=_rig.CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    if line.startswith("refused="):
                        self._log("AP: cache: kept %s" % line[8:])
                    elif line.startswith("dropped "):
                        self._log("AP: cache: deleted %s" % line[8:])
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: cache delete failed: %s" % exc)
            self._post(self.cache_refresh)

        threading.Thread(target=work, daemon=True,
                         name="pad-ap-cache-drop").start()
        return True

    def launch_pkg(self, path):
        """Start the rig on *path* (a .pkg), exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.ap_emulate_pkg_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # the switch window
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """appf.py's command line for the running game, or None."""
        table = info.get("switches_json")
        py = windows_python()
        if not table or not py:
            return None
        # --parent-pipe: the window closes itself when this app closes its
        # stdin (_close_switches)
        cmd = [py, os.path.join(ap.rig_dir(), "appf.py"), "--parent-pipe",
               "--slot", info.get("slot") or "0"]
        if ap.title_name(info):
            cmd += ["--title", ap.title_name(info)]
        # the status bar's VOL / Mute: the same control file as this tab's
        cmd += ["--audio-ctl", audio_ctl_file()]
        # the default distro's name when the app's runtime is not in use
        distro = share_distro(ap.rig_distro())
        if distro:
            # the table (and the playfield picture it names) live in the
            # app's Linux; Windows reads them through the distro's share
            cmd += ["--distro", distro, "--table",
                    "\\\\wsl.localhost\\%s%s" % (distro, table.replace("/", "\\"))]
        else:
            cmd += ["--table", table]
        return cmd

    def _open_switches(self, info=None):
        if rigslot.hidden():
            # a session's app runs hidden: no window on the desktop, this
            # one included (PAD-309)
            self._log("AP: a hidden run opens no playfield window "
                      "(PAD_HIDDEN=0 in this app's environment shows it).")
            return False
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True
        if info is None or not info.get("switches_json"):
            info = self._read_status()
        cmd = self._switch_window_cmd(info or {})
        if not cmd:
            self._log("AP: could not open the switch window (no Python to "
                      "run it with, or the game is not running).")
            return False
        # its errors go to a file: with stderr thrown away, a window that
        # never came up left nothing to go on (PAD-295)
        err_path = _sw_log_path()
        try:
            err = open(err_path, "wb")
        except OSError:
            err, err_path = subprocess.DEVNULL, ""
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=err, creationflags=_rig.CREATE_FLAGS)
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("AP: could not open the switch window: %s" % exc)
            return False
        finally:
            if err is not subprocess.DEVNULL:
                err.close()
        threading.Thread(target=self._front_when_up,
                         args=(self._sw_proc, _window_title(info or {}),
                               err_path),
                         daemon=True, name="pad-ap-switches-front").start()
        return True

    #: how long a new switch window gets to appear before the tab gives up
    #: bringing it to the front
    SW_SHOW_S = 30.0

    def _front_when_up(self, proc, title, err_path):
        """Bring the new switch window in front of the game's once it is
        on screen - the game's windows hold the focus when it opens, so it
        came up behind them (PAD-295) - or log why it closed at once."""
        deadline = time.time() + self.SW_SHOW_S
        while time.time() < deadline:
            if proc.poll() is not None:
                # not when Stop closed it (that clears _sw_proc first), nor
                # when the player closed it
                if proc is self._sw_proc and proc.returncode != 0:
                    self._log("AP: the playfield window closed at once "
                              "(exit %s). %s" % (proc.returncode,
                                                 _tail(err_path)))
                return
            if raise_window(title):
                return
            time.sleep(0.5)

    #: how long the switch window gets to close itself before it is killed
    SW_CLOSE_S = 4.0

    def _close_switches(self, wait=False):
        """Close the switch window.  It is an Edge --app window that appf.py
        started, so killing appf.py alone left the window up (David: Stop
        should also close it).  Closing appf.py's stdin asks it to close its
        window and quit; if it has not within SW_CLOSE_S, its whole process
        tree goes.  In the background unless *wait* (app quit)."""
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
                             name="pad-ap-switches-close").start()

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
        pkg = self.pkg_path()
        if not pkg:
            compat.messagebox.showinfo(
                "Emulate", "Pick the game's code file first (.pkg).")
            return
        if not os.path.isfile(pkg):
            compat.messagebox.showinfo("Emulate",
                                       "There is no file at\n%s" % pkg)
            return
        key, title = ap.game_info(pkg)
        if key in ap.NOT_HERE:
            compat.messagebox.showinfo("Emulate", ap.EXIT_TEXT[10])
            return
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = False
        self._starting = True
        self._cancelling = False
        self._started_here = True
        self._set_go("Cancel", True)

        def work():
            try:
                self._log("AP: starting %s%s." % (
                    os.path.basename(pkg), " (%s)" % title if title else ""))
                rc = self._run_streaming(
                    ap.rig_cmd_root(
                        "watch.sh", _rig.wsl_path(pkg),
                        # sound always on: Volume / Mute follow live
                        # through the control file (apvol.py), so unmuting
                        # a game started muted works
                        env=["PAD_VISIBLE=1", "PAD_AUDIO=1",
                             "PAD_AUDIO_CTL=%s" % _rig.wsl_path(audio_ctl_file()),
                             "PAD_LABEL=PAD",
                             "PAD_TITLE=%s" % title] + rigslot.board_env()
                             + rigslot.quiet_env()),
                    timeout=3600, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("AP: start canceled.")
                elif rc not in (0, None):
                    self._log("AP: start failed (exit %d). %s"
                              % (rc, ap.EXIT_TEXT.get(rc, "")))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-ap-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in ap.FOOTER_STEPS:
            if line.startswith(head):
                self._footer(kind, pct, text)
                return
        if line.startswith("progress "):
            try:
                pct = int(line.split()[1])
            except (IndexError, ValueError):
                return
            # prepare.py: decrypting is the first half, unpacking the rest
            self._footer("copy", pct, "%s the game… %d%%" % (
                "Decrypting" if pct < 50 else "Unpacking", pct))

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
                    ap.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("AP: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("AP: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-ap-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=ap.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        info = self._run_status(ap.rig_cmd("status.sh"))
        # the app's own Linux, for the setup notice: on this worker, since a
        # cold answer costs wsl.exe calls (cached after that)
        try:
            info["_rt"] = runtime.status()[0]
        except Exception:                                  # noqa: BLE001
            pass
        return info

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
        label, hint = ap.state_text(info)
        tone = "ok" if self._last_up else (
            "warn" if label == "WSL not answering" else "")
        up = self._last_up
        rss = int(info.get("rss_kb") or 0)
        secs = int(info.get("uptime_s") or 0)
        window = " + ".join(w.replace("x", " × ") for w in
                            (info.get("window") or "").split())
        if up and info.get("av") == "1":
            window = "AP's A/V player"
        values = {
            "title": ap.title_name(info) if up else "—",
            "version": (info.get("version") or "—") if up else "—",
            "switches": (info.get("switches") or "—") if up else "—",
            "window": (window or "—") if up else "—",
            "rss": ("%.1f GB" % (rss / 1048576.0)) if up and rss else "—",
            "uptime": ("%d:%02d" % (secs // 60, secs % 60)) if up and secs
            else "—",
        }
        msg, btn = ap.setup_notice(info, info.get("_rt"),
                                   _runtime_ui.can_install())
        if msg:
            # the notice says it; the headline need not say it twice
            hint = "" if not up else hint
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  setup_msg=msg, setup_btn=btn,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if ap.rig_available() else self.get("note"),
                  up=up, game=ap.title_name(info) if up else "")
        if not self._busy:
            kw["go_label"] = "Stop" if up else "Start"
            kw["go_enabled"] = ap.rig_available()
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
        if rig_off() or not ap.rig_available() or not ap.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(ap.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


#: appf.py's window title is "<game> - virtual playfield"
PF_SUFFIX = " - virtual playfield"


def _window_title(info):
    """The switch window's title for *info*'s game ("" = any AP one)."""
    name = ap.title_name(info)
    return (name + PF_SUFFIX) if name else ""


def _sw_log_path():
    import tempfile
    return os.path.join(tempfile.gettempdir(), "pad_ap_playfield.log")


def _tail(path, n=3):
    """The last *n* lines of the switch window's error log, one line."""
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return ""
    return " / ".join(lines[-n:])


def raise_window(title):
    """Bring the switch window titled *title* (or, with "", any window whose
    title ends in PF_SUFFIX) to the front of every window, the game's
    included.  True when one was found.  Windows only.

    SetForegroundWindow alone is refused when this app is not the
    foreground process - the case right after a start, when the game's
    windows have the focus - so the window is first put topmost and back,
    which lifts it over them either way.  Explorer's leaked
    Windows.Internal.Shell.* title proxies are skipped (PAD-260)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        found = []
        buf = ctypes.create_unicode_buffer(512)
        cls = ctypes.create_unicode_buffer(256)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(h, _lp):
            if not u.IsWindowVisible(h):
                return True
            u.GetWindowTextW(h, buf, 512)
            text = buf.value
            if not (text == title if title else text.endswith(PF_SUFFIX)):
                return True
            u.GetClassNameW(h, cls, 256)
            if cls.value.startswith("Windows.Internal.Shell."):
                return True
            found.append(h)
            return False
        u.EnumWindows(each, 0)
        if not found:
            return False
        h = found[0]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_uint]
        if u.IsIconic(h):
            u.ShowWindow(h, 9)                             # SW_RESTORE
        flags = 0x0001 | 0x0002 | 0x0040       # NOSIZE | NOMOVE | SHOWWINDOW
        u.SetWindowPos(h, wintypes.HWND(-1), 0, 0, 0, 0, flags)  # TOPMOST
        u.SetWindowPos(h, wintypes.HWND(-2), 0, 0, 0, 0, flags)  # NOTOPMOST
        u.SetForegroundWindow(h)
        return True
    except Exception:                                      # noqa: BLE001
        return False


def _kill_tree(proc):
    """Kill *proc* and everything it started (the switch window's Edge)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, creationflags=_rig.CREATE_FLAGS)
        else:
            proc.kill()
    except Exception:                                      # noqa: BLE001
        pass


TAB = EmulateAPTab
