"""Emulate tab for Stern Spike 1: run a DMD-era game on this PC (web port of
the old Tk ``Spike1EmulatePanel`` and its two pop-out windows).

THIN, like the Tk panel: every step of the launch (build, extract, seed,
responder, game, windows) lives in ``tools/spike1_emu/start.sh``.  This
service starts it, stops it, manages its save-state slots and its
extracted-game cache, installs what the rig is missing (Fix setup), and
reports truthfully what it is doing.  The rig facts (``rig_cmd``,
``state_text``, the payload keys, the event-log filters, the run-dir
reader) are ``webui/emulate_spike1_core.py``'s, called, not copied.

The DMD and the switch / LED matrix are two native windows while a game
runs, as they were in Tk (two cards on the tab when the app has no native
window: ``--browser`` / ``--serve``; see ``emulate_jjp_spike1view``).

Exports ``spike1_emulate_card_var`` (persisted per project by the run
logic) and answers ``emulate_shutdown`` (the app-quit fan-out).
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time

from ...core import payloads, rigdata, runtime
from pinball_decryptor.webui import rig as _rig
from pinball_decryptor.webui import runtime_prompt as _runtime_ui
from .. import emulate_spike1_core as s1
from .. import compat
from ..emulate_jjp_common import (RigTabMixin, audio_ctl_file, rig_off,
                                  windows_python)
from ..emulate_jjp_spike1view import DisplayFeed, SwitchModel, ViewWindows
from .base import TabService, rpc


INTRO = ("Run a Stern Spike 1 (DMD-era) game on this PC. The game is a static "
         "ARM binary, so it runs under a patched emulator with a software "
         "model of the machine's boards — this needs WSL and runs with root "
         "there.\n"
         "Pick a card image: the game is extracted from it once and kept, "
         "then boots and shows its attract on the dot-matrix display — which "
         "opens in its own window, alongside a switch/LED window you can "
         "click to inject switches.")

TIPS = {
    "card": ("A Spike 1 game card image (.img/.raw/.vhd/.iso). The game is "
             "extracted from it once and kept; after that you can Start "
             "without a card."),
    "reset": ("Force-restart WSL to clear a wedged emulator. Closes ALL WSL "
              "sessions and takes ~15s; your card and settings are "
              "untouched."),
    "winreset": "Reopen the DMD / switch windows if they got lost or closed.",
    "check": ("Look at the rig without changing anything — build state, "
              "extracted game, and whether it is running — and print it to "
              "the log."),
    "fix": ("Install whatever the emulator is missing: the ARM emulator and "
            "device model we build and verify ourselves, downloaded and "
            "checked against the exact version this app expects. Nothing is "
            "compiled on your machine, and no terminal is needed. Offers a "
            "file picker if the download is blocked. Right-click for "
            "\"Remove the app’s Linux\", which gives the disk back."),
    "states": s1.STATES_TIP,
}

#: The Status grid, same five-row shape as the Spike 2 tab.
ROWS = (("state", "State:"), ("procs", "Processes:"),
        ("cpu", "Game CPU / memory:"), ("dmd", "DMD frames:"),
        ("boards", "Boards registered:"))

#: The footer ladder: Spike 1 EXTRACTS the game rather than copying a card.
PHASES = ("Extract", "Boot", "Node boards", "Ready")

_MISSING_NOTE = ("The Spike 1 emulator rig is missing from tools/spike1_emu "
                 "— this checkout looks incomplete.")
_WINDOWS_NOTE = ("The Spike 1 emulator runs through WSL, so this tab is "
                 "Windows-only.")
_RUNNING_NOTE = ("The game is running and the boards registered — it boots "
                 "to its attract on the DMD, with the switch/LED window "
                 "beside it. Click a switch cell to inject it.")

_SLOT_NAME = re.compile(r"[A-Za-z0-9_.-]+")


class EmulateSpike1Tab(RigTabMixin, TabService):
    ns = "emulate_spike1"
    key = "Emulate Spike1"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = ("spike1_emulate_card_var",)

    LOG_PREFIX = "Spike 1: "
    PHASES = PHASES
    POLL_MS = s1.POLL_MS
    POLL_IDLE_MS = s1.POLL_IDLE_MS
    POLL_FIRST_MS = s1.POLL_FIRST_MS
    PAYLOAD_KEYS = s1.PAYLOAD_KEYS
    DEFAULT_AUDIO = s1.DEFAULT_AUDIO

    def __init__(self, window):
        super().__init__(window)
        # A separate card variable from the Spike 2 tab: a Spike 1 card and
        # a Spike 2 .raw in one key is a bug waiting for the first era switch.
        self.spike1_emulate_card_var = self.var("card")
        self._init_rig_state()
        self._dl_pct = 0
        self._extracting = False
        self._log_tailer = None
        self._slots_rows = []
        self._slots_mtime = None
        self._slots_busy = False
        self._player = None
        self._player_at = 0.0
        self._io = None
        self._feed = None
        self._model = None
        self._decoders = None
        self._cache_rows = []
        #: the display and switch windows (Tk's Spike1Viewers)
        self._windows = ViewWindows(self.ctx, log_line=self._log)
        win = sys.platform == "win32"
        ok = s1.rig_available()
        note = _MISSING_NOTE if not ok else ("" if win else _WINDOWS_NOTE)
        slots_ok = win and ok
        self.set(intro=INTRO, tips=TIPS, platform=sys.platform, win=win,
                 rig_ok=ok, go_label="Start emulator", go_enabled=ok and win,
                 busy=False, go_busy=False, reset_label="Restart WSL…",
                 reset_enabled=True, reset_busy=False,
                 # greyed only off Windows, as the Tk button was: with the
                 # rig incomplete it still installs the Linux and the shipped
                 # binaries and runs prereqcheck.sh
                 fix_enabled=win,
                 rows=[{"key": k, "label": lbl, "value": "—"}
                       for k, lbl in ROWS],
                 tone="", hint="", note=note,
                 note_kind="warn" if note else "",
                 up=False, slots=[], slots_enabled=slots_ok,
                 slots_sum=("The slots appear with the next status poll, or "
                            "press Refresh.") if slots_ok else
                 "Slot management is available on Windows (WSL).",
                 view_open=False, view_mode="dmd", view_popout=False,
                 sw=None, reveal=0,
                 cache={"open": False, "rows": [], "header": "",
                        "busy": False})
        # the Tk panel polled from build(), for every manufacturer
        self._start_polling()

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def _rig_ready(self):
        return s1.rig_available() and sys.platform == "win32"

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
        self._windows.shutdown()
        self._close_viewers()
        self._stop_log_tail()
        self._stop_player()

    def card_path(self):
        return (self.spike1_emulate_card_var.get() or "").strip()

    # ------------------------------------------------------------------
    # card row
    # ------------------------------------------------------------------
    @rpc
    def browse(self):
        path = self.window.ask_open(
            "spike1_emulate_card", "Select a Spike 1 card image",
            [("Spike 1 card image", "*.img *.raw *.vhd *.iso"),
             ("All files", "*.*")],
            initialdir=self.window._initialdir_for(self.card_path()))
        if path:
            self.spike1_emulate_card_var.set(os.path.normpath(path))
        return path or ""

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def _set_go(self, label=None, enabled=None):
        kw = {"busy": self._busy, "go_busy": self._go_busy}
        if label is not None:
            kw["go_label"] = label
        if enabled is not None:
            kw["go_enabled"] = bool(enabled)
        self.set(**kw)

    def _go_allowed(self):
        return s1.rig_available() and sys.platform == "win32"

    @rpc
    def toggle(self):
        if self._busy:
            return False
        if self._last_up:
            self._stop_async()
        else:
            self._start_async()
        return True

    def _start_async(self):
        card = self.card_path()
        if not card and self._info.get("game_ready") != "1":
            compat.messagebox.showinfo(
                "Emulate",
                "Pick a Spike 1 card image first.\n\nThe game is extracted "
                "from it once and kept — after that you can Start without a "
                "card.")
            return
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = True
        self._set_go("Starting…", False)
        # If a game still has to be extracted, the first stretch is the
        # extract phase - light the footer's first chip for it.
        self._extracting = self._info.get("game_ready") != "1" and bool(card)
        if self._extracting:
            self._patch_row("state", "Extracting the game…")
            self.set(hint="")
            self._footer_now("copy", 50, "Extracting the game…")

        def on_line(line):
            # the extract phase ends when the game files land
            if "extracted" in line and "game files" in line:
                self._extracting = False
                self._footer("boot", None, "Booting…")

        def work():
            try:
                # SELF-HEALING BEFORE IT IS ASKED FOR: a machine missing the
                # emulator gets the binaries we built and verified, now.
                try:
                    got = self._install_payloads()
                    if got:
                        self._log("Spike 1: installed the emulator (%s) — "
                                  "nothing had to be compiled here."
                                  % ", ".join(got))
                except Exception as exc:                    # noqa: BLE001
                    self._log("Spike 1: could not install the shipped "
                              "emulator (%s). Falling back to building it on "
                              "this machine." % exc)
                self._note_where_the_old_extraction_went()
                self._ensure_data_disk()
                if self._info.get("qemu_built") != "1":
                    self._log("Spike 1: first run — building the emulator, "
                              "this takes a few minutes. Each step is shown "
                              "below.")
                args = [card] if card else []
                env = ["PAD_AUDIO=1", "PAD_AUDIO_CTL=" + audio_ctl_file(),
                       "PAD_AUDIO_SINK=relay", "S1_PIVOT=1"]
                rc = self._run_streaming(
                    s1.rig_cmd_root("start.sh", *args, env=env),
                    timeout=1800, on_line=on_line)
                if rc == 2:
                    self._log("Spike 1: the one-time emulator build did not "
                              "finish. The lines just above name what this "
                              "machine still needs — install those, then "
                              "press Start again.")
                elif rc not in (0, None):
                    self._log("Spike 1: start failed (exit %d)." % rc)
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: start failed: %s" % exc)
            finally:
                self._extracting = False
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-s1-start").start()

    def _stop_async(self):
        if self._refuse_off():
            return
        self._busy = True
        self._go_busy = True
        self._set_go("Stopping…", False)

        def work():
            try:
                out = subprocess.run(
                    s1.rig_cmd_root("stop.sh"),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=180, creationflags=_rig.CREATE_FLAGS)
                self._log("Spike 1: "
                          + out.stdout.decode("utf-8", "replace").strip())
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: stop failed: %s" % exc)
            finally:
                self._stop_player()
                self._release()

        threading.Thread(target=work, daemon=True, name="pad-s1-stop").start()

    def _release(self):
        def done():
            self._busy = False
            self._go_busy = False
            self._set_go(enabled=self._go_allowed())
            self._poll_now()
        self._post(done)

    # ------------------------------------------------------------------
    # the Windows-side speaker (the APP owns it, not the rig)
    # ------------------------------------------------------------------
    def _player_cmd(self):
        py = windows_python(console=True)
        pp = os.path.join(os.path.dirname(s1.rig_dir()), "spike2_emu",
                          "padplay.py")
        if not py or not os.path.isfile(pp):
            return None
        rate, ch = self._audio_format()
        return [py, pp, "127.0.0.1", "45998", rate, ch]

    def _audio_format(self):
        work = self._info.get("work")
        distro = self._info.get("distro")
        if work and distro:
            path = s1.wsl_unc(distro, work.rstrip("/") + "/s1audio")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    parts = f.read().split()
                if len(parts) == 2 and all(p.isdigit() for p in parts):
                    return parts[0], parts[1]
            except (OSError, TypeError):
                pass
        return self.DEFAULT_AUDIO

    def _ensure_player(self):
        """Keep one Windows player alive while a run is up (relaunched with
        a 5 s backoff when it exits)."""
        if sys.platform != "win32" or rig_off():
            return
        p = self._player
        if p is not None and p.poll() is None:
            return
        now = time.monotonic()
        if now - self._player_at < 5.0:
            return
        cmd = self._player_cmd()
        if not cmd:
            return
        self._player_at = now
        env = dict(os.environ)
        env["PAD_AUDIO_CTL"] = audio_ctl_file()
        try:
            self._player = subprocess.Popen(
                cmd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_rig.CREATE_FLAGS)
            if p is None:
                self._log("Spike 1: speaker up (app-side Windows player).")
        except Exception as exc:                           # noqa: BLE001
            self._log("Spike 1: could not start the speaker: %s" % exc)
            self._player = None

    def _stop_player(self):
        p, self._player = self._player, None
        if p is None:
            return
        try:
            p.kill()
        except Exception:                                  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Restart WSL / Reset windows / Check setup
    # ------------------------------------------------------------------
    @rpc
    def fix_state(self):
        if self._busy:
            return False
        if sys.platform != "win32":
            compat.messagebox.showinfo(
                "Restart WSL",
                "This recovery restarts WSL and only applies on Windows.")
            return False
        if not compat.messagebox.askyesno(
                "Restart WSL",
                "Force-restart WSL to clear a wedged emulator?\n\n"
                "Use this when Stop did not work. It closes EVERYTHING running "
                "in WSL (other terminals too) and takes about 15 seconds. Your "
                "card and settings are untouched."):
            return False
        if self._refuse_off():
            return False
        self._busy = True
        # Start is only greyed while WSL restarts (Tk): the spinner belongs to
        # the button doing the work
        self._set_go(enabled=False)
        self.set(reset_label="Restarting…", reset_enabled=False,
                 reset_busy=True)

        def work():
            try:
                self._log("Spike 1: shutting WSL down to clear stuck state…")
                out = subprocess.run(
                    ["wsl.exe", "--shutdown"], stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=120,
                    creationflags=_rig.CREATE_FLAGS)
                if out.returncode == 0:
                    self._log("Spike 1: WSL was shut down — stuck processes "
                              "and frozen windows are cleared. Press Start to "
                              "run again.")
                else:
                    self._log("Spike 1: wsl --shutdown returned %d. %s"
                              % (out.returncode,
                                 out.stdout.decode("utf-8", "replace")
                                 .strip()))
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: could not restart WSL: %s" % exc)
            finally:
                self._post(self._reset_done)

        threading.Thread(target=work, daemon=True, name="pad-s1-fix").start()
        return True

    def _reset_done(self):
        self._busy = False
        self._set_go(enabled=self._go_allowed())
        self.set(reset_label="Restart WSL…", reset_enabled=True,
                 reset_busy=False)
        self._poll_now()

    @rpc
    def window_reset(self):
        """Reopen the DMD / switch windows and pull them back on-screen (the
        escape hatch for a window dragged to a monitor that went away, or
        one that was closed); without native windows, bring the cards into
        view."""
        if not self._last_up:
            self.log("Spike 1: nothing running — start the emulator first.")
            return False
        self._open_viewers(reset=True)
        if not self.get("view_popout"):
            self.set(reveal=int(self.get("reveal", 0) or 0) + 1)
        self.log("Spike 1: DMD and switch windows reopened.")
        return True

    @rpc
    def check_setup(self):
        """Read-only: print the rig's state to the log.  Never mutates."""
        if sys.platform != "win32":
            self.log("Spike 1: Check setup is available on Windows (WSL).")
            return False
        if self._refuse_off():
            return False

        def work():
            try:
                out = subprocess.run(
                    s1.rig_cmd("status.sh"), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=25,
                    creationflags=_rig.CREATE_FLAGS)
                info = _rig.parse_status(
                    out.stdout.decode("utf-8", "replace"))
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: check failed: %s" % exc)
                return

            def yn(k):
                return "yes" if info.get(k) == "1" else "no"

            self._log("Spike 1 setup — emulator built: %s · device model: %s · "
                      "game extracted: %s · running: %s"
                      % (yn("qemu_built"), yn("hwshim_built"), yn("game_ready"),
                         "yes" if int(info.get("game_procs") or 0) else "no"))
            state, detail = runtime.status()
            if state in ("unsupported", "unpublished"):
                self._log("Spike 1 setup — Linux: %s (%s)"
                          % (info.get("distro") or "the machine's default",
                             "the app has no runtime of its own here"))
            else:
                self._log("Spike 1 setup — Linux: %s · %s"
                          % (info.get("distro") or "?", detail))

        threading.Thread(target=work, daemon=True, name="pad-s1-check").start()
        return True

    # ------------------------------------------------------------------
    # Fix setup (and its right-click menu)
    # ------------------------------------------------------------------
    def _install_payloads(self, log=None):
        return payloads.ensure(list(self.PAYLOAD_KEYS), log=log or self._log,
                               distro=s1.rig_distro())

    def _install_runtime(self, log=None):
        say = log or self._log
        if self._last_up:
            say("Spike 1: the emulator is running — stop it first.")
            return None
        # runtime_prompt asks with compat's messagebox / filedialog: the
        # page's own dialogs
        return _runtime_ui.ensure(
            say=lambda m: say("Spike 1: %s" % m),
            progress=self._download_progress,
            ask=self._ask_before_replacing,
            on_blocked=lambda exc: threading.Thread(
                target=self._offer_runtime_from_file, args=(exc,),
                daemon=True).start())

    def _download_progress(self, done, total):
        if not total:
            return
        pct = int(done * 100 / total)
        if pct >= self._dl_pct + 10:
            self._dl_pct = pct
            self._log("Spike 1: downloading… %d%% of %d MB"
                      % (pct, total // (1024 * 1024)))

    def _ask_before_replacing(self):
        return _runtime_ui.ask_before_replacing()

    def _offer_runtime_from_file(self, exc):
        _runtime_ui.offer_from_file(
            say=lambda m: self._log("Spike 1: %s" % m), exc=exc,
            ask=self._ask_before_replacing)

    def _offer_file_install(self, exc):
        """The blocked-download path: a person who can copy the file onto
        this machine another way picks it; the same SHA-256 is checked."""
        want = [payloads.PAYLOADS[k] for k in self.PAYLOAD_KEYS
                if payloads.is_published(payloads.PAYLOADS[k])]
        if not want or not compat.messagebox.askyesno(
                "Fix setup",
                "%s\n\nIf you can copy the file onto this machine another "
                "way, choose it now — it is checked against the same "
                "checksum before it is installed.\n\nChoose a file?" % exc):
            return
        for p in want:
            path = compat.filedialog.askopenfilename(
                title="Choose the downloaded %s" % p.filename,
                initialfile=p.filename)
            if not path:
                return
            try:
                payloads.install_from_file(p, path, log=self._log)
            except Exception as e:                          # noqa: BLE001
                self._log("Spike 1: %s" % e)
                return

    def _ensure_data_disk(self):
        d = s1.rig_distro()
        if not d:
            return
        try:
            if rigdata.ensure(d, log=lambda m: self._log("Spike 1: %s" % m)):
                free = rigdata.free_bytes(d)
                if free and free < rigdata.LOW_SPACE_BYTES:
                    self._log(
                        "Spike 1: the emulator's data disk is nearly full "
                        "(%.1f GB left). Right-click Fix setup to delete what "
                        "is on it." % (free / 1073741824.0))
        except Exception as exc:                            # noqa: BLE001
            self._log("Spike 1: could not set up the data disk (%s) — the "
                      "emulator will keep its work inside the runtime "
                      "instead." % exc)

    def _default_distro_has_a_game(self):
        try:
            out = subprocess.run(
                _rig.rig_cmd(s1.rig_dir(), "status.sh"),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25,
                creationflags=_rig.CREATE_FLAGS)
        except Exception:                                   # noqa: BLE001
            return False
        return _rig.parse_status(
            out.stdout.decode("utf-8", "replace")).get("game_ready") == "1"

    def _note_where_the_old_extraction_went(self):
        if self._info.get("game_ready") == "1" or not s1.rig_distro():
            return
        if not self._default_distro_has_a_game():
            return
        self._log(
            "Spike 1: the emulator now runs in the Linux this app installs "
            "(%s), so this card is extracted into it once. Your earlier "
            "extractions are still in this PC's own WSL distro — untouched, "
            "not deleted — and setting PAD_RUNTIME=0 goes back to using them."
            % runtime.DISTRO)

    @rpc
    def fix_setup(self):
        """Install what is missing, then say what is left - one button, no
        terminal.  The looking half is the rig's own prereqcheck.sh."""
        if self._busy or sys.platform != "win32":
            # greyed off Windows, as the Tk button was: on a Mac it would
            # install x86-64 Linux binaries for a rig that cannot run there.
            # An incomplete tools/spike1_emu does NOT grey it (Tk left it
            # on): the Linux and the shipped binaries still install.
            return False
        if self._refuse_off():
            return False
        self.set(fix_enabled=False)

        def work():
            try:
                self._log("Spike 1: checking the emulator install…")
                try:
                    self._install_runtime()
                except Exception as exc:                    # noqa: BLE001
                    self._log("Spike 1: %s" % exc)
                try:
                    got = self._install_payloads()
                    if got:
                        self._log("Spike 1: installed %s." % ", ".join(got))
                except Exception as exc:                    # noqa: BLE001
                    self._log("Spike 1: %s" % exc)
                    threading.Thread(target=self._offer_file_install,
                                     args=(exc,), daemon=True).start()
                try:
                    out = subprocess.run(
                        s1.rig_cmd("prereqcheck.sh"), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, timeout=120,
                        creationflags=_rig.CREATE_FLAGS)
                    for line in out.stdout.decode("utf-8",
                                                  "replace").splitlines():
                        if line.strip():
                            self._log("Spike 1: %s" % line.rstrip())
                except Exception as exc:                    # noqa: BLE001
                    self._log("Spike 1: could not check the rig: %s" % exc)
            finally:
                self._post(lambda: self.set(
                    fix_enabled=sys.platform == "win32"))

        threading.Thread(target=work, daemon=True, name="pad-s1-setup").start()
        return True

    @rpc
    def delete_rig_data(self):
        """Give the disk back (the data disk is the unit of reclaim)."""
        if self._last_up:
            self.log("Spike 1: the emulator is running — stop it first.")
            return False
        if self._refuse_off():
            return False
        if not rigdata.exists():
            self.log("Spike 1: there is no emulator data to delete.")
            return False
        size = rigdata.size_on_disk() / 1073741824.0
        if not compat.messagebox.askyesno(
                "Delete the emulator's data?",
                "This deletes everything both emulators have written: games "
                "extracted from your cards, cached cards, and any SAVE STATES."
                "\n\nIt frees %.1f GB. Your cards and anything you have "
                "exported are untouched, and the emulator itself stays "
                "installed - the next run just extracts again."
                "\n\nDelete it?" % size):
            return False

        def work():
            if rigdata.delete():
                self._log("Spike 1: deleted the emulator's data (%.1f GB "
                          "freed)." % size)
            else:
                self._log("Spike 1: could not delete the data disk — is a run "
                          "still using it?")

        threading.Thread(target=work, daemon=True).start()
        return True

    @rpc
    def delete_downloads(self):
        """The third thing that takes disk: what we downloaded to install."""
        if self._refuse_off():
            return False
        root = payloads.cache_root()
        total = 0
        for base, _dirs, files in os.walk(root):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(base, f))
                except OSError:
                    pass
        if not total:
            self.log("Spike 1: nothing downloaded to delete.")
            return False
        if not compat.messagebox.askyesno(
                "Delete downloaded files?",
                "This deletes the installer files the app has downloaded (the "
                "emulator binaries and the runtime image), freeing %.1f GB."
                "\n\nNothing that is installed is removed - they are only "
                "downloaded again if something needs reinstalling."
                "\n\nDelete them?" % (total / 1073741824.0)):
            return False

        def work():
            try:
                shutil.rmtree(root)
                self._log("Spike 1: deleted the downloaded files (%.1f GB "
                          "freed)." % (total / 1073741824.0))
            except OSError as exc:
                self._log("Spike 1: could not delete them: %s" % exc)

        threading.Thread(target=work, daemon=True).start()
        return True

    @rpc
    def remove_runtime(self):
        """Give back the disk the app's own Linux takes (asks first, names
        everything it deletes)."""
        if self._refuse_off():
            return False

        def work():
            state, detail = runtime.status(refresh=True)
            if state in ("absent", "unsupported", "unpublished"):
                self._log("Spike 1: there is no runtime installed to remove.")
                return
            if self._last_up:
                self._log("Spike 1: the emulator is running - stop it first.")
                return
            if state == "foreign":
                self._log("Spike 1: %s" % detail)
                return
            if not compat.messagebox.askyesno(
                    "Remove the emulator's Linux?",
                    "This removes %s and everything inside it:\n\n"
                    "  - games extracted from your cards\n"
                    "  - cached cards\n"
                    "  - any SAVE STATES made while running in it\n\n"
                    "Your cards, your extractions on this PC and your own WSL "
                    "distro are untouched, and the emulator goes back to using "
                    "the machine's own distro.\n\nRemove it?"
                    % runtime.DISTRO):
                return
            try:
                if runtime.uninstall():
                    self._log("Spike 1: removed %s. The emulator will use "
                              "this PC's own WSL distro again."
                              % runtime.DISTRO)
                else:
                    self._log("Spike 1: could not remove %s."
                              % runtime.DISTRO)
            except Exception as exc:                        # noqa: BLE001
                self._log("Spike 1: %s" % exc)

        threading.Thread(target=work, daemon=True).start()
        return True

    # ------------------------------------------------------------------
    # extracted-game cache (the Cache… window)
    # ------------------------------------------------------------------
    def _cache_state(self, **kw):
        cur = dict(self.get("cache") or {})
        cur.update(kw)
        self.set(cache=cur)

    @rpc
    def cache_open(self):
        if sys.platform != "win32":
            compat.messagebox.showinfo(
                "Cache",
                "The extracted-game cache lives in WSL, so it is managed on "
                "Windows.")
            return False
        self._cache_rows = []
        self._cache_state(open=True, rows=[], header="Reading…", busy=False)
        self.cache_reload()
        return True

    @rpc
    def cache_close(self):
        self._cache_state(open=False)
        return True

    @rpc
    def cache_reload(self):
        def work():
            text = ""
            if not rig_off():
                try:
                    out = subprocess.run(
                        s1.rig_cmd("cache.sh", "list"),
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        timeout=30, creationflags=_rig.CREATE_FLAGS)
                    text = out.stdout.decode("utf-8", "replace")
                except Exception:                           # noqa: BLE001
                    text = ""
            try:
                rows, free = s1.parse_cache(text)
            except Exception:                               # noqa: BLE001
                rows, free = [], None
            self._post(self._cache_apply, rows, free)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _cache_apply(self, rows, free):
        if not (self.get("cache") or {}).get("open"):
            return
        self._cache_rows = rows
        now = time.time()
        out = []
        for r in rows:
            age = now - int(r["boot"] or 0)
            used = ("just now" if age < 90
                    else "%dh ago" % (age // 3600) if age < 86400
                    else "%dd ago" % (age // 86400))
            out.append({"label": r["label"], "game": r["game"],
                        "size": s1.human_kb(r["kb"]), "used": used,
                        "active": bool(r["active"])})
        total = sum(int(r["kb"] or 0) for r in rows)
        header = "%d cached — %s on disk · %s free (WSL disk)" % (
            len(rows), s1.human_kb(total), s1.human_kb(free))
        self._cache_state(rows=out, header=header, busy=False)

    @rpc
    def cache_delete(self, label):
        row = next((r for r in self._cache_rows if r["label"] == label),
                   None)
        if row is None or row["active"]:
            return False
        if not compat.messagebox.askyesno(
                "Delete cached game",
                "Delete the cached extraction for %s? The next Start from "
                "that card will extract it again (~1 minute)." % label):
            return False
        if self._refuse_off():
            return False
        self._cache_state(busy=True)

        def work():
            try:
                subprocess.run(
                    s1.rig_cmd_root("cache.sh", "drop", label),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=60, creationflags=_rig.CREATE_FLAGS)
                self._log("Spike 1: deleted cached extraction %s." % label)
            except Exception as exc:                        # noqa: BLE001
                self._log("Spike 1: delete failed: %s" % exc)
            self._post(self.cache_reload)

        threading.Thread(target=work, daemon=True).start()
        return True

    # ------------------------------------------------------------------
    # save states
    # ------------------------------------------------------------------
    def _slots_ok(self):
        return sys.platform == "win32" and s1.rig_available()

    @rpc
    def slots_refresh(self):
        """Re-read the slots as root, off the loop, and repaint."""
        if self._slots_busy or not self._slots_ok() or rig_off():
            return False
        self._slots_busy = True

        def run():
            rows, total, free = [], None, None
            try:
                out = subprocess.run(
                    s1.rig_cmd_root("s1slots.sh", "list"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=30, creationflags=_rig.CREATE_FLAGS)
                for line in out.stdout.decode("utf-8", "replace").splitlines():
                    p = line.strip().split("|", 5)
                    if p[0] == "slot" and len(p) >= 6:
                        rows.append({"ref": p[1], "bytes": p[2], "game": p[3],
                                     "label": p[4].strip(), "epoch": p[5]})
                    elif p[0] == "total" and len(p) >= 2:
                        total = p[1]
                    elif p[0] == "free" and len(p) >= 2:
                        free = p[1]
            except Exception:                              # noqa: BLE001
                pass

            def apply():
                self._slots_busy = False
                self._slots_rows = rows
                self._slots_paint(total, free)

            self._post(apply)

        threading.Thread(target=run, daemon=True).start()
        return True

    def _slots_paint(self, total=None, free=None):
        rows = []
        for row in self._slots_rows:
            rows.append({"ref": row["ref"],
                         "slot": row["ref"].split("/", 1)[-1],
                         "name": row["label"], "game": row["game"],
                         "size": s1.fmt_size(row["bytes"]),
                         "saved": s1.fmt_when(row["epoch"])})
        if self._slots_rows:
            n = len(self._slots_rows)
            text = "%d slot%s — %s on disk" % (n, "" if n == 1 else "s",
                                                s1.fmt_size(total))
            if free is not None:
                text += " · %s free (WSL disk)" % s1.fmt_size(free)
        else:
            text = "No save states yet — Save now snapshots the running game."
        self.set(slots=rows, slots_sum=text)

    def _slot_op(self, cmd_args, doing, then_refresh=True):
        if self._refuse_off():
            return

        def run():
            try:
                out = subprocess.run(
                    s1.rig_cmd_root(*cmd_args),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=300, creationflags=_rig.CREATE_FLAGS)
                for line in out.stdout.decode("utf-8",
                                              "replace").splitlines():
                    line = line.strip()
                    if line:
                        self._log("Spike 1: " + line)
            except Exception as exc:                       # noqa: BLE001
                self._log("Spike 1: %s failed: %s" % (doing, exc))
            if then_refresh:
                self._post(self.slots_refresh)

        threading.Thread(target=run, daemon=True).start()

    def _running(self):
        return int(self._info.get("game_procs") or 0) >= 1

    @rpc
    def slot_save(self):
        """Save now: asks for the slot name (Tk's simpledialog.askstring,
        "quicksave" filled in), checks it, then saves."""
        if not self._running():
            compat.messagebox.showinfo(
                "Save state",
                "No game is running — start the emulator first, then Save "
                "now snapshots it mid-play.")
            return None
        name = compat.simpledialog.askstring(
            "Save state", "Slot name (letters, digits, _ . - only):",
            initialvalue="quicksave")
        if not name:
            return None
        name = name.strip()
        if not _SLOT_NAME.fullmatch(name):
            compat.messagebox.showerror(
                "Save state", "Slot names use letters, digits, _ . - only.")
            return None
        self.log("Spike 1: saving the game to slot '%s'…" % name)
        self._slot_op(("s1savestate.sh", name), "save")
        return True

    @rpc
    def slot_load(self, ref=None):
        if not ref:
            compat.messagebox.showinfo("Load state", "Pick a slot to load.")
            return None
        if not self._running():
            compat.messagebox.showinfo(
                "Load state",
                "The emulator is not running. Start it on the slot's title "
                "first — Load then swaps the running game for the slot.")
            return None
        self.log("Spike 1: loading slot '%s'…" % ref)
        self._slot_op(("s1restorestate.sh", ref), "load")
        return True

    @rpc
    def slot_rename(self, ref=None):
        """Rename…: asks for the new name with the current one filled in
        (Tk's simpledialog.askstring; Cancel changes nothing)."""
        if not ref:
            compat.messagebox.showinfo("Rename", "Pick a slot to rename.")
            return None
        row = next((r for r in self._slots_rows if r["ref"] == ref), None)
        label = compat.simpledialog.askstring(
            "Rename slot", "Name for %s:" % ref,
            initialvalue=(row or {}).get("label", ""))
        if label is None:
            return None
        self._slot_op(("s1slots.sh", "label", ref, label), "rename")
        return True

    @rpc
    def slot_delete(self, ref=None):
        if not ref:
            compat.messagebox.showinfo("Delete", "Pick a slot to delete.")
            return None
        if not compat.messagebox.askyesno(
                "Delete slot", "Delete the save state %s?\n\n"
                "This frees its disk space and cannot be undone." % ref):
            return False
        self._slot_op(("s1slots.sh", "delete", ref), "delete")
        return True

    # ------------------------------------------------------------------
    # the display and switch cards (the Tk pop-out windows)
    # ------------------------------------------------------------------
    def _load_decoders(self):
        if self._decoders is None:
            try:
                dmd = s1._load_dmd_decoder()
                self._decoders = (dmd.decode_frame, s1._load_alpha())
            except Exception:                              # noqa: BLE001
                self._decoders = (None, None)
        return self._decoders

    def _open_viewers(self, info=None, reset=False):
        """Open whichever of the display and the switch panel is not up
        (idempotent: a running game calls this on every poll, as Tk's
        ``Spike1Viewers.open`` was).  ``info`` carries what the poll read
        off the run dir (the display kind, the switch names)."""
        info = self._info if info is None else info
        work = info.get("work")
        distro = info.get("distro")
        if not (work and distro):
            return
        io = self._io
        if io is None or (io.run_dir_wsl, io.distro) != (work, distro):
            self._close_viewers()
            io = self._io = s1._RunDirIO(work, distro)
            decode, alpha = self._load_decoders()
            self._feed = DisplayFeed(io, decode, alpha) if decode else None
            self._model = SwitchModel(
                io, after=lambda ms, fn: self.ctx.loop.after(ms, fn),
                on_change=lambda st: self.set(sw=st))
        # the display kind is known only once the game is extracted, which
        # is after the first open: re-read on every poll (Tk's display_mode)
        if self._feed is not None and "_display" in info:
            self._feed.set_mode("alpha" if info.get("_display") ==
                                "alphanumeric" else "dmd")
        if self._model is not None and "_names" in info:
            self._model.refresh_names(info.get("_names") or {})
        mode = self._feed.mode if self._feed is not None else "dmd"
        popout = self._windows.available()
        self.set(view_open=True, view_mode=mode,
                 view_display=self._feed is not None, view_popout=popout)
        if popout:
            self._windows.show(mode if self._feed is not None else None,
                               switches=True, reset=reset)
        else:
            # a window that would not open: the cards take over, and the
            # other window does not stay up alone
            self._windows.close()

    def _close_viewers(self):
        self._windows.close()
        model, self._model = self._model, None
        if model is not None:
            model.close()
        self._feed = None
        self._io = None
        self.set(view_open=False, sw=None)

    @rpc(loop=False)
    def view_frame(self, since=""):
        feed = self._feed
        if feed is None:
            return None
        try:
            return feed.frame(since or "")
        except Exception:                                  # noqa: BLE001
            return None

    @rpc(loop=False)
    def view_state(self):
        model = self._model
        if model is None:
            return None
        try:
            return model.snapshot()
        except Exception:                                  # noqa: BLE001
            return None

    def _with_model(self, fn, *args):
        model = self._model
        if model is None:
            return False
        fn(model, *args)
        return True

    @rpc
    def sw_pulse(self, node, idx):
        return self._with_model(SwitchModel.pulse, int(node), int(idx))

    @rpc
    def sw_toggle(self, node, idx):
        return self._with_model(SwitchModel.toggle, int(node), int(idx))

    @rpc
    def key_down(self, keysym):
        return self._with_model(SwitchModel.press_key, str(keysym))

    @rpc
    def key_up(self, keysym):
        return self._with_model(SwitchModel.release_key, str(keysym))

    @rpc
    def keys_release(self):
        return self._with_model(SwitchModel.release_all_keys)

    @rpc
    def ball_cmd(self, cmd):
        return self._with_model(SwitchModel.ball_cmd, str(cmd))

    @rpc
    def ball_click(self, i):
        return self._with_model(SwitchModel.ball_click, int(i))

    # ------------------------------------------------------------------
    # rig event logs -> the app's log
    # ------------------------------------------------------------------
    def _start_log_tail(self):
        if self._log_tailer is not None or rig_off():
            return
        work = self._info.get("work")
        distro = self._info.get("distro")
        if not (work and distro):
            return
        stop = threading.Event()
        t = threading.Thread(target=self._tail_event_logs,
                             args=(work, distro, stop), daemon=True,
                             name="pad-s1-tail")
        self._log_tailer = (t, stop)
        t.start()

    def _stop_log_tail(self):
        if self._log_tailer is not None:
            self._log_tailer[1].set()
            self._log_tailer = None

    def _tail_event_logs(self, work, distro, stop):
        pos = {}
        while not stop.wait(1.0):
            for name, tag, keep in s1._EVENT_LOGS:
                p = s1.wsl_unc(distro, work.rstrip("/") + "/" + name)
                if not p:
                    continue
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                if name not in pos:
                    pos[name] = 0 if size <= s1._EVENT_REPLAY_MAX else size
                if size < pos[name]:
                    pos[name] = 0
                if size == pos[name]:
                    continue
                try:
                    with open(p, "rb") as f:
                        f.seek(pos[name])
                        raw = f.read(256 * 1024)
                except OSError:
                    continue
                cut = raw.rfind(b"\n")
                if cut < 0:
                    continue
                pos[name] += cut + 1
                chunk = raw[:cut + 1].decode("utf-8", "replace")
                lines = [ln.strip() for ln in chunk.splitlines()]
                lines = [ln for ln in lines
                         if ln and (keep is None or keep.search(ln))]
                extra = len(lines) - s1._EVENT_LINES_PER_POLL
                for ln in lines[:s1._EVENT_LINES_PER_POLL]:
                    self._log("Spike 1 [%s] %s"
                              % (tag, ln[:s1._EVENT_LINE_CLIP]))
                if extra > 0:
                    self._log("Spike 1 [%s] … %d more lines in %s"
                              % (tag, extra, name))

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------
    def _read_status(self):
        info = self._run_status(s1.rig_cmd("status.sh"))
        # the display kind and the switch names are read here, off the
        # loop: the rig writes both minutes into a boot.  The poll that
        # first sees the run reads them too, so the display window opens
        # as the right kind rather than being replaced a poll later.
        if int(info.get("game_procs") or 0) > 0:
            work, distro = info.get("work"), info.get("distro")
            io = self._io
            if work and distro and (io is None or (
                    io.run_dir_wsl, io.distro) != (work, distro)):
                io = s1._RunDirIO(work, distro)
            if io is not None:
                try:
                    info["_display"] = io.read_text("s1display")
                    info["_names"] = io.read_switch_names()
                except Exception:                          # noqa: BLE001
                    pass
        return info

    def _patch_row(self, key, value):
        rows = [dict(r) for r in (self.get("rows") or [])]
        for r in rows:
            if r["key"] == key:
                r["value"] = value
        self.set(rows=rows)

    def _footer_from_info(self):
        info = self._info
        if self._busy and self._extracting:
            self._footer_now("copy", 50, "Extracting the game…")
        elif self._last_up and info.get("nodes_registered") == "1":
            self._footer_now("run", None, "Game running")
        elif self._last_up:
            self._footer_now("boot", None, "Booting…")
        elif not self._busy:
            self._footer_now("idle")

    def _apply(self, info):
        self._info = info
        self._last_up = int(info.get("game_procs") or 0) > 0
        label, hint = s1.state_text(info)
        if self._busy and self._extracting:
            label = "Extracting the game…"
        vals = {"state": label}
        procs = info.get("game_procs", "0")
        vals["procs"] = "%s running%s" % (
            procs, "  (all stopped)" if procs == "0" else "")
        if self._last_up:
            cpu = info.get("cpu", "?")
            rss = info.get("rss_mb", "?")
            up = int(info.get("game_uptime_s") or 0)
            uptxt = "  ·  up %d:%02d" % (up // 60, up % 60) if up else ""
            vals["cpu"] = "%s%% of one core, %s MB%s" % (cpu, rss, uptxt)
        else:
            vals["cpu"] = "—"
        vals["dmd"] = info.get("dmd_frames", "0")
        if not self._last_up:
            vals["boards"] = "—"
        else:
            vals["boards"] = "yes" if info.get("nodes_registered") == "1" \
                else "not yet"
        if self._last_up:
            tone = "ok" if info.get("nodes_registered") == "1" else "acc"
        elif label in ("WSL not answering", "Setup needed"):
            tone = "warn"
        else:
            tone = ""

        kw = dict(rows=[{"key": k, "label": lbl, "value": vals.get(k, "—")}
                        for k, lbl in ROWS],
                  hint=hint if not self._busy else "", tone=tone,
                  up=self._last_up)
        if not self._busy:
            kw["go_label"] = "Stop" if self._last_up else "Start emulator"
            kw["go_enabled"] = self._go_allowed()

        # the note: the rig's own condition first, then the run
        if not s1.rig_available():
            kw.update(note=_MISSING_NOTE, note_kind="warn")
        elif sys.platform != "win32":
            kw.update(note=_WINDOWS_NOTE, note_kind="warn")
        elif self._last_up and info.get("nodes_registered") == "1":
            kw.update(note=_RUNNING_NOTE, note_kind="ok")
        elif not self._last_up:
            kw.update(note="", note_kind="")
        kw["busy"] = self._busy
        kw["go_busy"] = self._go_busy
        self.set(**kw)

        # the app-side speaker follows the run
        if self._last_up:
            self._ensure_player()
        else:
            self._stop_player()

        # re-list the save slots when their directory changed, and once on
        # the first poll so the manager fills without a button press
        sm = info.get("saves_mtime")
        if sm != self._slots_mtime:
            self._slots_mtime = sm
            self.slots_refresh()

        self._footer_from_info()

        # the display + switch windows and the event-log tail follow the run
        if self._last_up:
            self._open_viewers(info)
            self._start_log_tail()
        else:
            self._close_viewers()
            self._stop_log_tail()

    # ------------------------------------------------------------------
    # app quit
    # ------------------------------------------------------------------
    def emulate_shutdown(self):
        """App-quit hook: take the emulator down with the app (blocking,
        bounded)."""
        self._stopped = True
        self._cancel_poll()
        # the windows close without waiting: this runs while the main
        # window's closing handler holds the GUI thread
        self._windows.shutdown()
        self._close_viewers()
        self._stop_log_tail()
        if rig_off() or not s1.rig_available() or sys.platform != "win32":
            return
        if not (self._last_up or self._info.get("responder") == "1"):
            return
        try:
            subprocess.run(s1.rig_cmd_root("stop.sh"), timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_rig.CREATE_FLAGS)
        except Exception:                                  # noqa: BLE001
            pass

    shutdown_sync = emulate_shutdown


TAB = EmulateSpike1Tab
