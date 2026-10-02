"""Emulate PB tab: run a Pinball Brothers game on this PC from its update
file - Predator on its rig (tools/pb_emu), Alien, ABBA and Queen on the
I/O-board rig (tools/pbio_emu, PAD-315, PAD-326); the file picked says
which (``emulate_pb_core.kind_of``), and the rest of the tab is the same.

Built on the American Pinball tab (webui/tabs/emulate_ap.py), the template
every maker's Emulate tab follows (David, PAD-271: "modeled off the same look
and feel of the other emulate tabs (like AP and stern)"), by way of the
Spooky tab (webui/tabs/emulate_spooky.py), whose rig is the closest:

* THIN: every step of the launch (setup, unpack, board, game) lives in
  ``tools/pb_emu/watch.sh``.  This service starts it (and cancels it), stops
  it, and polls ``status.sh`` - the same keys as AP's.
* Set up emulator…, as the AP tab has: the app's own Linux when it is
  missing or out of date, and the libraries the game runs on (setup.sh,
  about 700 MB) ahead of the first Start - which does it otherwise.
* The machine is a WINDOW of its own - AP's virtual playfield
  (``tools/ap_emu/appf.py``, the Stern window's page) pointed at this rig's
  board by ``tools/pb_emu/pbpf.py``: the keys, the service buttons, BALLS
  (Plunge, Drain, Reset balls), Pause and the Volume bar.  It opens once the
  game is in attract, reopens on request, and closes on Stop (its stdin is
  the tab's pipe) or when the game ends.
* Sound is always on; Volume / Mute follow live through the control file
  every Emulate tab shares (``tools/pb_emu/pbvol.py`` holds Predator's
  stream at that level; ``tools/pbio_emu/pbioaudio.py`` plays Alien's and
  ABBA's at it, PAD-322).
* A Cache window (AP's) shows and deletes the builds unpacked in the app's
  Linux, and the one-time setup.

Exports ``pb_emulate_file_var`` (the run logic persists it per project) and
answers ``emulate_shutdown`` (the app-quit fan-out).
"""

import os
import subprocess
import sys
import threading
import time

from pinball_decryptor.webui import rig as _rig
from .. import compat
from ...core import rigslot, runtime
from .. import emulate_pb_core as pb
from .. import runtime_prompt as _runtime_ui
from ..emulate_jjp_common import (RigTabMixin, rig_off, audio_ctl_file,
                                  windows_python,
                                  share_distro)
from .base import TabService, rpc

INTRO = ("Run a Pinball Brothers game on this PC. Supported: %s. The "
         "emulator stands in for the machine's controller boards and gives "
         "the game its screen and every switch.\n"
         "Pick the update for the version you want to play; a smaller "
         "follow-up update needs the full one it builds on in the same "
         "folder. Alien and Queen can also start from their restore images "
         "(clonezilla-live-alien40.iso, clonezilla-live-queen20d.iso), "
         "which their updates need beside them the first time (ABBA's: "
         "Alien's)." % ", ".join(pb.supported_names()))

FILE_TIP = ("A game's update file (pbpp_predator_game_….upd, pbap….upd, "
            "pbq….upd) or a restore image (clonezilla-live-alien40.iso, "
            "clonezilla-live-queen20d.iso). It is only "
            "read: the emulator unpacks it once (a few minutes) and keeps "
            "it, so the next start is quicker.")

#: the Supported games card: the games not run yet, and why (none now)
PENDING = []
PENDING_NOTE = ""

VOLUME_TIP = ("The game's sound on this PC - Volume and Mute follow at once, "
              "while the game plays (the same knob every Emulate tab shares). "
              "The game's own volume is in its service menu.")

SWITCHES_TIP = ("The virtual playfield, as on the American Pinball and Stern "
                "Emulate tabs: every switch, the keyboard, the service "
                "buttons and the balls (Plunge, Drain, Reset balls), Pause "
                "and the volume.")

#: The status grid (label, key into the values _apply computes) - AP's,
#: with the board's ball count.
CELLS = (
    ("Game", "title"),
    ("Version", "version"),
    ("Balls", "balls"),
    ("Switches", "switches"),
    ("Window", "window"),
    ("Memory", "rss"),
    ("Uptime", "uptime"),
)


class EmulatePBTab(RigTabMixin, TabService):
    ns = "emulate_pb"
    key = "Emulate PB"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("pb_emulate_file_var",)

    LOG_PREFIX = "PB: "
    PHASES = pb.PHASES
    POLL_MS = pb.POLL_MS
    POLL_IDLE_MS = pb.POLL_IDLE_MS
    POLL_FIRST_MS = pb.POLL_FIRST_MS

    def __init__(self, window):
        super().__init__(window)
        self.pb_emulate_file_var = self.var("file")
        self._init_rig_state()
        #: the rig the tab polls and drives: "pb" (Predator) or "pbio"
        #: (Alien, ABBA) - the picked file's, except while a game runs
        #: (``_poll_kind``)
        self._kind = "pb"
        self._starting = False
        self._cancelling = False
        self._setting_up = False
        #: the virtual playfield (pbpf.py), when this app opened one
        self._sw_proc = None
        #: the Cache window: open?, its entries by name, the selection
        self._cache_open = False
        self._cache_entries = {}
        self._cache_sel = []
        ok = pb.rig_available()
        if not ok:
            note = ("The Pinball Brothers emulator is missing from "
                    "tools/pb_emu or tools/pbio_emu - this install looks "
                    "incomplete.")
        elif not pb.platform_ok():
            ok = False
            note = ("The Pinball Brothers emulator runs through WSL, so it is "
                    "available on Windows only.")
        else:
            note = ""
        self.set(intro=INTRO, file_tip=FILE_TIP, volume_tip=VOLUME_TIP,
                 switches_tip=SWITCHES_TIP, supported=pb.supported_names(),
                 pending=PENDING, pending_note=PENDING_NOTE, title_note="",
                 platform=sys.platform, rig_ok=ok,
                 go_label="Start", go_enabled=ok, busy=False, go_busy=False,
                 starting=False,
                 state_label="Checking…", state_hint="", tone="",
                 cells=[{"label": lbl, "key": k, "value": "—"}
                        for lbl, k in CELLS],
                 note=note, up=False, ready=False, game="", cache=None,
                 setup_msg="", setup_btn=False, setup_label=pb.SETUP_LABEL,
                 setup_enabled=True)
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return pb.rig_available()

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
        (the Extract input) when it is one the emulator runs - a file already
        picked must not be asked for again."""
        own = (self.pb_emulate_file_var.get() or "").strip()
        if own:
            return own
        card = getattr(self.window, "extract_input_var", None)
        try:
            path = (card.get() or "").strip() if card is not None else ""
        except Exception:                                  # noqa: BLE001
            path = ""
        return path if pb.supported_file(path) else ""

    def _poll_kind(self):
        """The rig to poll: the running game's while one runs (or starts),
        else the picked file's - Predator's when nothing is picked."""
        if not (self._last_up or self._busy):
            self._kind = pb.kind_of(self.file_path()) or "pb"
        return self._kind

    # ------------------------------------------------------------------
    # the page's calls
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "pb_emulate_file", "Select a Pinball Brothers update file",
            [("Pinball Brothers update or restore image", "*.upd *.iso"),
             ("Predator update", "pbpp_predator_game_*.upd"),
             ("Alien or ABBA update", "pbap*.upd"),
             ("Restore image", "clonezilla-live-*.iso"), ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.file_path()))
        if path:
            self.pb_emulate_file_var.set(os.path.normpath(path))
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
        """End the start in flight: the rig's cancel.sh ends watch.sh and
        everything it started, drops a half-unpacked build and stops any
        game that had come up."""
        if not self._starting or self._cancelling:
            return False
        self._cancelling = True
        self._set_go("Cancelling…", False)
        self._log("PB: cancelling the start…")
        kind = self._kind

        def work():
            try:
                out = subprocess.run(
                    pb.rig_cmd_root("cancel.sh", kind=kind),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("PB: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("PB: cancel failed: %s" % exc)

        threading.Thread(target=work, daemon=True,
                         name="pad-pb-cancel").start()
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
                         name="pad-pb-switches").start()
        return True

    def launch_file(self, path):
        """Start the rig on *path*, exactly as the Start button."""
        path = (path or "").strip()
        if not path or self._busy:
            return False
        self.pb_emulate_file_var.set(path)
        self._start_async()
        return True

    # ------------------------------------------------------------------
    # Set up emulator…, as the AP tab has: the app's own Linux (when it is
    # missing or out of date) and the libraries the game runs on, ahead of
    # the first Start
    # ------------------------------------------------------------------
    @rpc
    def setup(self):
        """Set up emulator…: install or update the app's own Linux (the
        shared runtime_prompt ladder, with its consent for a replace), then
        run the rig's setup.sh there (the one-time libraries)."""
        if self._setting_up or rig_off() or not pb.platform_ok():
            return False
        if self._busy or self._last_up:
            self._log("PB: the game is running - stop it first.")
            return False
        rt = (self._info or {}).get("_rt")
        # only Predator's rig has libraries to download: Alien and ABBA run
        # on the machine's own, restored from its image
        libs = self._poll_kind() == "pb"
        steps = []
        if rt in ("absent", "stale") and _runtime_ui.can_install():
            steps.append("%s the Linux this app runs its emulators in "
                         "(PAD-Runtime, a one-time download)"
                         % ("Install" if rt == "absent" else "Update"))
        if libs:
            steps.append("Download the libraries Predator runs on (sound, "
                         "video), inside that Linux (about 700 MB, once)")
        if not steps:
            return False
        if not compat.messagebox.askyesno(
                "Set up the emulator",
                "This will:\n\n" + "\n\n".join("  •  " + x for x in steps)
                + "\n\nIt takes a few minutes; you can watch it in the log. "
                  "Nothing on the Windows side is touched, and nothing is "
                  "removed.\n\nGo ahead?"):
            return False
        self._setting_up = True
        self._busy = True
        self.set(setup_enabled=False, setup_label=pb.SETUP_BUSY)
        self._set_go(enabled=False)
        say = lambda m: self._log("PB: %s" % m)              # noqa: E731
        pct = {"at": -10}

        def progress(done, total):
            if total and int(done * 100 / total) >= pct["at"] + 10:
                pct["at"] = int(done * 100 / total)
                say("downloading… %d%% of %d MB"
                    % (pct["at"], total // (1024 * 1024)))

        def ask():
            return bool(self.ctx.loop.call(_runtime_ui.ask_before_replacing))

        def work():
            try:
                if rt in ("absent", "stale") and _runtime_ui.can_install():
                    state = _runtime_ui.ensure(say=say, progress=progress,
                                               ask=ask)
                    runtime.invalidate()
                    if state != "ready":
                        say("the emulator's Linux is not set up, so the "
                            "libraries were not downloaded either.")
                        return
                if not libs:
                    say("the emulator is set up.")
                    return
                say("downloading the libraries the game runs on (about "
                    "700 MB, a few minutes)…")
                rc = self._run_streaming(pb.rig_cmd_root("setup.sh"),
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
                    self.set(setup_enabled=True, setup_label=pb.SETUP_LABEL)
                self._post(done)
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-pb-setup").start()
        return True

    # ------------------------------------------------------------------
    # the Cache window (AP's): the builds unpacked in the app's Linux and
    # the one-time setup, and deleting them (tools/pb_emu/cache.sh)
    # ------------------------------------------------------------------
    CACHE_HINT = ("Deleting frees the space now: a build is unpacked again on "
                  "its next Start, the setup downloaded again - nothing is "
                  "lost (settings and high scores are kept apart).")

    @rpc
    def open_cache(self):
        if not pb.rig_available() or not pb.platform_ok():
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
            # both rigs' caches in one list: the I/O-board rig's names carry
            # "pbio:" (cache_delete sends each name to its own rig)
            entries, disk = [], None
            for kind in ("pb", "pbio"):
                try:
                    out = subprocess.run(
                        pb.rig_cmd_root("cache.sh", "--list", kind=kind),
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        timeout=120, creationflags=_rig.CREATE_FLAGS)
                    text = out.stdout.decode("utf-8", "replace")
                except Exception:                          # noqa: BLE001
                    text = ""
                got, d = pb.parse_cache(text)
                for e in got:
                    if kind == "pbio":
                        e["name"] = "pbio:" + e["name"]
                    entries.append(e)
                disk = disk or d
            self._post(self._cache_show, (entries, disk))

        threading.Thread(target=work, daemon=True,
                         name="pad-pb-cache").start()
        return True

    def _cache_show(self, result):
        if not self._cache_open:
            return
        from ..emulate_core import human_size
        entries, disk = result
        self._cache_entries = {e["name"]: e for e in entries}
        running = (self._info.get("build") or "") if self._last_up else ""
        rows = [{"name": e["name"], "label": pb.cache_label(e),
                 "size": human_size(e["kb"]),
                 "used": time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(e["used"]))
                 if e["used"] else "—",
                 "src": ("running now" if e["name"] == running
                         else e["src"].replace("+", " + "))}
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
        extra = ("\n\nThe emulator setup downloads again (about 700 MB) on the "
                 "next Start." if "setup" in names else "")
        if not compat.messagebox.askyesno(
                "Delete cached items",
                "Delete %d item%s, freeing about %s?\n\nA running game's "
                "build is kept.%s" % (len(names), "" if len(names) == 1 else "s",
                                      human_size(freed), extra)):
            return False
        self._cache_patch(busy=True, hint="Deleting…")

        by_rig = {"pb": [n for n in names if not n.startswith("pbio:")],
                  "pbio": [n[5:] for n in names if n.startswith("pbio:")]}

        def work():
            for kind, drop in by_rig.items():
                if not drop:
                    continue
                try:
                    out = subprocess.run(
                        pb.rig_cmd_root("cache.sh", "--drop", *drop, kind=kind),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=600, creationflags=_rig.CREATE_FLAGS)
                    for line in out.stdout.decode("utf-8",
                                                  "replace").splitlines():
                        if line.startswith("refused="):
                            self._log("PB: cache: kept %s" % line[8:])
                        elif line.startswith("dropped "):
                            self._log("PB: cache: deleted %s" % line[8:])
                except Exception as exc:                   # noqa: BLE001
                    self._log("PB: cache delete failed: %s" % exc)
            self._post(self.cache_refresh)

        threading.Thread(target=work, daemon=True,
                         name="pad-pb-cache-drop").start()
        return True

    # ------------------------------------------------------------------
    # the virtual playfield
    # ------------------------------------------------------------------
    def _switch_window_cmd(self, info):
        """pbpf.py's command line for the running game, or None."""
        table = (info or {}).get("switches_json")
        py = windows_python()
        if not table or not py:
            return None
        # --parent-pipe: the window closes itself when this app closes its
        # stdin (_close_switches)
        cmd = [py, os.path.join(pb.rig_dir(), "pbpf.py"), "--parent-pipe",
               "--slot", info.get("slot") or "0",
               # the status bar's VOL / Mute: the same control file as this tab's
               "--audio-ctl", audio_ctl_file()]
        if (info.get("_kind") or self._kind) == "pbio":
            cmd += ["--rig", "pbio"]        # Alien's, ABBA's board
        # the default distro's name when the app's runtime is not in use
        distro = share_distro(pb.rig_distro())
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
            self._log("PB: a hidden run opens no playfield window "
                      "(PAD_HIDDEN=0 in this app's environment shows it).")
            return False
        if self._sw_proc is not None and self._sw_proc.poll() is None:
            return True
        if info is None or not info.get("switches_json"):
            info = self._read_status()
        cmd = self._switch_window_cmd(info or {})
        if not cmd:
            self._log("PB: could not open the virtual playfield (no Python "
                      "to run it with, or the game is not running).")
            return False
        try:
            self._sw_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=_rig.CREATE_FLAGS)
            return True
        except Exception as exc:                           # noqa: BLE001
            self._sw_proc = None
            self._log("PB: could not open the virtual playfield: %s" % exc)
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
                             name="pad-pb-switches-close").start()

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
                "Pick a game's update file first (pbpp_predator_game_….upd, "
                "pbap….upd, pbq….upd) or a restore image "
                "(clonezilla-live-alien40.iso, clonezilla-live-queen20d.iso)."
                "\n\n"
                "Supported: %s." % ", ".join(pb.supported_names()))
            return
        if not os.path.isfile(path):
            compat.messagebox.showinfo("Emulate", "There is no file at\n%s"
                                       % path)
            return
        if not pb.supported_file(path):
            compat.messagebox.showinfo("Emulate", pb.EXIT_TEXT[4])
            return
        if self._refuse_off():
            return
        kind = self._kind = pb.kind_of(path)
        title = pb.title_of(path)
        self._busy = True
        # No spinner on the button while starting: it is the Cancel button
        # now, and the footer ladder shows the progress.
        self._go_busy = False
        self._starting = True
        self._cancelling = False
        self._started_here = True
        self._set_go("Cancel", True)

        # sound always on, on both rigs: Volume / Mute follow live through
        # the control file (Predator: pbvol.py; Alien and ABBA:
        # pbioaudio.py, PAD-322), so unmuting a game started muted works
        env = ["PAD_VISIBLE=1", "PAD_AUDIO=1",
               "PAD_AUDIO_CTL=%s" % _rig.wsl_path(audio_ctl_file())]
        if kind == "pbio":
            first = ("a first start restores the machine's Linux from its "
                     "image and unpacks the update - a few minutes")
        else:
            first = ("a first start sets up the emulator and unpacks the "
                     "update - a few minutes")
        # the rig board names the run by its title (PAD-296)
        env += (["PAD_TITLE=%s" % title] + rigslot.board_env()
                + rigslot.quiet_env())

        def work():
            try:
                self._log("PB: starting %s %s (%s; then the game loads in "
                          "under a minute)." % (title, os.path.basename(path),
                                                first))
                if pb.TITLE_NOTES.get(title):
                    self._log("PB: " + pb.TITLE_NOTES[title])
                rc = self._run_streaming(
                    pb.rig_cmd_root("watch.sh", _rig.wsl_path(path),
                                    kind=kind, env=env),
                    timeout=3600, on_line=self._footer_line)
                if self._cancelling:
                    self._started_here = False
                    self._log("PB: start cancelled.")
                elif rc not in (0, None):
                    self._log("PB: start failed (exit %d). %s"
                              % (rc, pb.exit_text(kind, rc)))
                else:
                    self._open_switches()
            except Exception as exc:                       # noqa: BLE001
                self._log("PB: start failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-pb-start").start()

    def _footer_line(self, line):
        for head, kind, pct, text in pb.FOOTER_STEPS:
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
        kind = self._kind

        def work():
            try:
                out = subprocess.run(
                    pb.rig_cmd_root("stop.sh", kind=kind),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=120, creationflags=_rig.CREATE_FLAGS)
                self._log("PB: " + out.stdout.decode("utf-8", "replace")
                          .strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("PB: stop failed: %s" % exc)
            finally:
                self._release()

        threading.Thread(target=work, daemon=True,
                         name="pad-pb-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._starting = False
            self._cancelling = False
            self._set_go(enabled=pb.rig_available())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        kind = self._poll_kind()
        info = self._run_status(pb.rig_cmd("status.sh", kind=kind))
        info["_kind"] = kind
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
            # the game ended (it quit, or was stopped elsewhere): so does its
            # window
            self._started_here = False
            self._close_switches()
        up = self._last_up
        ready = up and info.get("attract") == "1"
        label, hint = pb.state_text(info)
        tone = "ok" if ready else (
            "warn" if label == "WSL not answering" else "")
        rss = int(info.get("rss_kb") or 0)
        secs = int(info.get("uptime_s") or 0)
        name = info.get("title_name") or (
            "Predator" if info.get("_kind", "pb") == "pb" else "—")
        balls = "—"
        if up and info.get("balls"):
            try:
                tr, sh, play = (int(x) for x in info["balls"].split("/"))
                balls = "trough %d · lane %d · in play %d" % (tr, sh, play)
            except ValueError:
                pass
        values = {
            "title": name if up else "—",
            "version": (info.get("version") or "—") if up else "—",
            "balls": balls,
            "switches": (info.get("switches") or "—") if up else "—",
            "window": (info.get("window") or "—").replace("x", " × ")
            if up else "—",
            "rss": (pb.mem_text(rss) or "—") if up else "—",
            "uptime": ("%d:%02d" % (secs // 60, secs % 60)) if up and secs
            else "—",
        }
        msg, btn = pb.setup_notice(info, info.get("_rt"),
                                   _runtime_ui.can_install())
        if msg:
            # the notice says it; the headline need not say it twice
            hint = "" if not up else hint
        kw = dict(state_label=label, state_hint=hint, tone=tone,
                  setup_msg=msg, setup_btn=btn,
                  cells=[{"label": lbl, "key": k, "value": values.get(k, "—")}
                         for lbl, k in CELLS],
                  note="" if pb.rig_available() else self.get("note"),
                  up=up, ready=ready, game=name if up else "",
                  title_note=pb.TITLE_NOTES.get(name, "") if up else "")
        if not self._busy:
            kw["go_label"] = "Stop" if up else "Start"
            kw["go_enabled"] = pb.rig_available()
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
        if rig_off() or not pb.rig_available() or not pb.platform_ok():
            return
        if not self._started_here or not (self._last_up or self._busy):
            return
        try:
            subprocess.run(pb.rig_cmd_root("stop.sh", kind=self._kind),
                           timeout=120,
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


TAB = EmulatePBTab
