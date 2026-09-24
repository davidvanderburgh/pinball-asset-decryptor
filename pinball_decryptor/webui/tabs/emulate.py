"""Emulate tab (Stern Spike 2): run a card image under the rig in
``tools/spike2_emu`` and watch that run's health.

The web port of the old Tk ``EmulatePanel``.  Same behaviour, same words;
the helpers it calls are ``webui/emulate_core.py``'s (``webui/emulate_rig.py``
re-exports them with the panel's word lists).  What the panel did to widgets
this service does to its
store namespace ``emulate``; what it did with ``after`` it does on the UI
loop; every ``wsl.exe`` / ``docker`` / rig script call stays on a worker.

Rules carried over (see ``webui/emulate_core.py``'s doc): the card is the ONLY source,
mounted read only; the user's edits ride as an override set; Stop is
verified by re-reading the status; one Start/Stop toggle owned by
``_run_label``; nothing heavy on the UI loop.

``PAD_UI_NO_RIG`` (captures, tests): no probe, no poll, no pre-cache and no
rig command runs; a user action that would run one is refused through
``_run``/``_popen`` (tests replace those two).

The launch API other tabs call (``window.service("emulate")``):
``start``, ``launch_with``, ``launch_card``, ``last_refusal``,
``set_preparing``, ``prepare_refuse``, ``prepare_cancelled``,
``launch_as_root``, ``launch_state``, ``run_ended_cb``, ``_last_up``,
``_launch_serial``; plus ``play``, ``try_it`` and ``run_card``, the
window seams (``MainWindow._modes_play`` / ``_modes_try`` / the Multi-boot
tab's Run in emulator).
"""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from ...core import config, rigdata, runtime
from .. import compat
from .. import emulate_rig as rig
from .base import TabService, rpc

log = logging.getLogger(__name__)

#: The rig is off in this session: captures and tests set it.
NO_RIG_ENV = "PAD_UI_NO_RIG"
NO_RIG_TEXT = ("the emulator rig is switched off in this session "
               "(PAD_UI_NO_RIG)")


def no_rig():
    return bool(os.environ.get(NO_RIG_ENV))


# ----------------------------------------------------------------- volume
# Item 56: the master volume / Mute control file.  emulate_core computes
# its path once, at import, from settings.json's folder; here it is computed
# at call time so a session run against a copy of settings.json (captures,
# tests) never writes beside the real one.  Same file, same shape, same
# atomic write as emulate_core.py's _load_audio_ctl/_write_audio_ctl.
def audio_ctl_file():
    return os.path.join(os.path.dirname(config.SETTINGS_FILE),
                        "audio_ctl.json")


def load_audio_ctl():
    try:
        with open(audio_ctl_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        gain = float(data.get("gain", 1.0))
        muted = bool(data.get("muted", False))
    except (OSError, ValueError, TypeError, AttributeError):
        return 1.0, False
    return max(0.0, min(1.0, gain)), muted


def write_audio_ctl(gain, muted):
    path = audio_ctl_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"gain": gain, "muted": muted}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def _state_kind(text):
    """The chip colour for a State word (the Tk cell had one colour)."""
    if text in ("Game running",):
        return "ok"
    if text in ("Not running", "—", ""):
        return ""
    if text in ("Stuck at Tech Alerts", "Locked: US machine on 50 Hz"):
        return "warn"
    if text == "At Tech Alerts":
        return "info"
    return "acc"


class EmulateTab(TabService):
    ns = "emulate"
    key = "Emulate"
    label = "Emulate"
    group = "Play"
    icon = "emulate"
    exports = (
        "emulate_card_var", "emulate_savestates_var", "emulate_overrides_var",
        "emulate_country_var", "emulate_power_var",
    )

    BACKSTOP_MIN = rig.BACKSTOP_MIN
    POLL_MS = rig.POLL_MS
    POLL_IDLE_MS = rig.POLL_IDLE_MS
    COUNTRIES = rig.COUNTRIES
    COUNTRY_GAME = rig.COUNTRY_GAME
    POWER_CHOICES = rig.POWER_CHOICES
    OVERRIDE_MODE_OBJECT = rig.OVERRIDE_MODE_OBJECT

    def __init__(self, window):
        super().__init__(window)
        # -- the window-owned variables the run logic persists ------------
        self.emulate_card_var = self.var("card", "str", "")
        self.emulate_savestates_var = self.var("savestates", "bool", True)
        self.emulate_overrides_var = self.var("overrides", "bool", False)
        self.emulate_country_var = self.var("country", "str",
                                            rig.COUNTRY_GAME)
        self.emulate_power_var = self.var("power", "str",
                                          rig.POWER_CHOICES[0][0])
        # -- the panel's own ---------------------------------------------
        vol0, mute0 = load_audio_ctl()
        self._volume_var = self.var("volume", "float", round(vol0 * 100))
        self._mute_var = self.var("mute", "bool", mute0)
        self._select_var = self.var("select", "bool", False)
        self._topper_var = self.var("topper", "bool", True)
        self._assets_var = None
        self._assets_bound = False

        self._saves_token = None
        self._launch_slot = None
        self._launch_prepare = None
        self._launch_accepted = False
        self._launch_serial = 0
        self._loading = False
        self._proc = None
        self._copying = None
        self._copying_pct = None
        self._preparing = None
        self._preparing_pct = None
        self._preparing_kind = None
        self._cancel_prepare = False
        self.last_refusal = ""
        #: "a run this tab started has gone down" (item 127): the Modes
        #: tab's ``run_ended(serial)``; None asks the modes service at call
        #: time, as the Tk window's lambda did.
        self.run_ended_cb = None
        self._precached = None
        self._cache_open = False
        self._cache_entries = {}
        self._cache_sel = []
        self._pf_proc = None
        self._last_up = False
        self._last_info = None
        self._starting = False
        self._runtime_noted = False
        self._rt_noted = False
        self._rt_pct = -10
        self._stopping = False
        self._resetting = False
        self._winresetting = False
        self._poll_job = None
        self._stopped = False
        self._vnc_opened = False
        self._started_here = False
        self._docker = None
        self._docker_busy = False
        self._docker_ticks = 0
        self._docker_cli = None
        self._docker_engine = None
        self._docker_report_next = False
        self._setup = None
        self._setup_busy = False
        self._setup_fixing = False
        self._setup_restart_check = False
        self._setup_report_next = False
        self._setup_ticks = 0
        self._setup_said_boot = False
        self._setup_tick_job = None
        self._poll_busy = False
        self._polled_once = False
        self._select_menu = None
        self._select_why = ""
        self._select_probed = ""
        self._select_stamp = None
        self._select_touched = False
        self._which_token = 0
        self._which = None
        self._browsed = None
        self._slots_rows = None
        self._slots_total = None
        self._slots_free = None
        self._slot_by_iid = {}
        self._slot_sel = None
        self._vals = {"state": "—", "procs": "—", "cpu": "—", "host": "—",
                      "audio": "—"}

        self.emulate_card_var.trace_add("write", self._on_card_changed)
        self.emulate_overrides_var.trace_add(
            "write", lambda *_a: self._overrides_paint())
        self._volume_var.trace_add("write", self._on_volume_change)
        self._mute_var.trace_add("write", self._on_volume_change)

        rig_ok = rig.rig_available()
        self.set(
            platform=sys.platform, no_rig=no_rig(), rig=rig_ok,
            rig_missing="" if rig_ok else self._rig_missing_text(),
            countries=[rig.COUNTRY_GAME] + list(rig.COUNTRIES),
            powers=[label for label, _env in rig.POWER_CHOICES],
            country_tip=rig.COUNTRY_TIP, power_tip=rig.POWER_TIP,
            topper_tip=rig.TOPPER_TIP, states_tip=rig.STATES_TIP,
            launch_tip=rig.LAUNCH_TIP, select_tip=rig.SELECT_TIP_IDLE,
            vals=dict(self._vals), state_kind="", state_tip="", hint="",
            docker_msg="", docker_btn=None, docker_enabled=True,
            setup_msg="", setup_btn=False,
            setup_label="Set up emulator…", setup_enabled=True,
            rt_msg="", rt_btn=False, rt_label="Update emulator Linux…",
            rt_enabled=True, check_label="Check setup…", check_enabled=True,
            fixaud_enabled=rig_ok, winreset_enabled=rig_ok,
            slots=[], slots_read=False, slot_sel=None,
            slots_enabled=sys.platform == "win32",
            slots_sum=("The slots appear with the next status poll."
                       if sys.platform == "win32" else
                       "Slot management is available on Windows (WSL)."),
            game=None, which=None,
            assets="", ovr_hint=rig.OVR_OFF, ovr_refused=False,
            cache=None, rename=None)
        self._run_label(False, False)
        # The panel wrote the control file at build so it exists before a
        # first Start (padplay.py reads it): the same here, bar captures.
        if not no_rig():
            self._on_volume_change()
        # build(): the probes and the poll start once the window is up.
        self.ctx.loop.post(self._build)

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    def _log(self, msg):
        """Log from ANY thread (the drain and the workers call it)."""
        self.ctx.loop.post(self.window.append_log, msg)

    def _post(self, fn, *args):
        self.ctx.loop.post(fn, *args)

    def _after(self, ms, fn, *args):
        return self.ctx.loop.after(ms, fn, *args)

    def _run(self, cmd, **kw):
        """``subprocess.run`` for a rig / WSL / Docker command."""
        if no_rig():
            raise OSError(NO_RIG_TEXT)
        kw.setdefault("creationflags", rig.CREATE_FLAGS)
        return subprocess.run(cmd, **kw)

    def _popen(self, cmd, **kw):
        if no_rig():
            raise OSError(NO_RIG_TEXT)
        kw.setdefault("creationflags", rig.CREATE_FLAGS)
        return subprocess.Popen(cmd, **kw)

    def _cmd(self, script, *args, env=()):
        """``rig_cmd``; under PAD_UI_NO_RIG a plain argv that consults
        nothing (``rig_cmd`` asks core.runtime which distro to use, and off
        the main thread that question can run ``wsl.exe -l``)."""
        if no_rig():
            head = (["env"] + [str(e) for e in env]) if env else []
            return head + ["bash", "%s/%s" % (rig.rig_dir(), script)] + \
                [str(a) for a in args]
        return rig.rig_cmd(script, *args, env=env)

    def _cmd_root(self, script, *args):
        if no_rig():
            return self._cmd(script, *args)
        return rig.rig_cmd_root(script, *args)

    def _thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _card(self):
        return self.emulate_card_var.get().strip().strip('"')

    def _set(self, key, text):
        self._vals[key] = text
        extra = {}
        if key == "state":
            extra["state_kind"] = _state_kind(text)
        self.set(vals=dict(self._vals), **extra)

    def _hint(self, text):
        self.set(hint=text or "")

    def _footer(self, kind, pct=None, text=""):
        """Item 78: ``MainWindow.set_emulate_progress``, tagged with this
        tab so a hidden panel's poll never paints the footer."""
        try:
            self.window.set_emulate_progress(kind, pct, text, tab=self.key)
        except Exception:                                # noqa: BLE001
            log.exception("set_emulate_progress")

    def _rig_missing_text(self):
        d = rig.rig_dir()
        if sys.platform == "darwin":
            return ("The emulator rig was not found in %s.\n\n"
                    "It ships with the app. On macOS it runs in a "
                    "container — the emulator needs Linux — and shows "
                    "its picture over VNC, which Screen Sharing opens "
                    "with nothing to install.\n\n"
                    "Docker Desktop is required. Set PAD_EMU_DIR if the "
                    "rig is somewhere else." % d)
        if sys.platform != "win32":
            return ("The emulator rig was not found in %s.\n\n"
                    "It ships with the app, in tools/spike2_emu. Re-run "
                    "the installer, or set PAD_EMU_DIR to point at that "
                    "folder.\n\n"
                    "There is no setup step once it is found: the "
                    "first run builds the guest filesystem out of the "
                    "card you pick, and compiles the shim and the "
                    "renderer." % d)
        return ("The emulator rig was not found in %s.\n\n"
                "It ships with the app, so this usually means an "
                "upgrade over a copy that predates it, or a checkout "
                "without tools/spike2_emu. Re-run the installer, or "
                "set PAD_EMU_DIR to point at that folder.\n\n"
                "There is no setup step once it is found: the "
                "first run builds the guest filesystem out of the "
                "card you pick, and compiles the shim and the "
                "renderer." % d)

    # ------------------------------------------------------------------
    # build / hooks
    # ------------------------------------------------------------------
    def _build(self):
        # Save states are simply on (item 13): the panel held this true at
        # build so an anchor saved under the old default cannot turn it off.
        self.emulate_savestates_var.set(True)
        self._bind_assets()
        self._select_probe_kick()
        if no_rig() or self._stopped:
            return
        if sys.platform == "darwin":
            self._docker_check()
        else:
            self._setup_check()
        self._schedule_poll()

    def _bind_assets(self):
        """The Write tab's Assets Folder, SHARED not copied (PAD-103)."""
        if self._assets_bound:
            return
        var = getattr(self.window, "write_assets_var", None)
        if var is None:
            return
        self._assets_var = var
        self._assets_bound = True
        try:
            var.trace_add("write", lambda *_a: (self._overrides_paint(),
                                                self._which_kick()))
        except Exception:                                # noqa: BLE001
            pass
        self._overrides_paint()
        self._which_kick()

    def on_manufacturer(self, mfr):
        self._bind_assets()
        self._overrides_paint()

    def on_show(self):
        self._bind_assets()
        # the Stern ladder, then what the last poll said (Tk showed idle
        # here and let the next poll repaint; this is that repaint, early)
        try:
            self.window.set_emulate_phases(rig.EMULATE_PHASES)
        except Exception:                                # noqa: BLE001
            pass
        self._paint_footer()

    def on_close(self):
        self._stopped = True
        if self._poll_job is not None:
            self.ctx.loop.after_cancel(self._poll_job)
            self._poll_job = None

    def emulate_shutdown(self):
        """App quit: the window's fan-out (``emulate_shutdown``)."""
        self.shutdown_sync()

    def machine_choices(self, key):
        """The allowed values of the global machine settings, for the app's
        ``_restore_emulate_machine``."""
        if key == "emulate_country":
            return [rig.COUNTRY_GAME] + list(rig.COUNTRIES)
        if key == "emulate_power":
            return [label for label, _env in rig.POWER_CHOICES]
        return []

    # ------------------------------------------------------------------
    # the card path and what follows it
    # ------------------------------------------------------------------
    def _on_card_changed(self, *_a):
        self.set(game=self._card_game())
        self._slots_paint()
        self._precache_kick()
        self._select_probe_kick()
        self._which_kick()

    # -- which card this is, next to the project (PAD-199) ----------------
    def _which_kick(self):
        """Work out, off the loop, whether the card picked to run is the
        project's own (the one it was extracted from, or one PAD built from
        it).  The header and the Apply box follow the project, the run
        follows this field, and the page never said when those differ."""
        self._which_token += 1
        token = self._which_token
        card, assets = self._card(), self._assets()
        if not card or not assets:
            self._which = None
            self.set(which=None)
            return

        def run():
            from ...core.extract_source import card_relation
            try:
                rel = card_relation(card, assets)
            except Exception:                            # noqa: BLE001
                rel = None
            self._post(self._which_apply, token, rel)

        self._thread(run)

    def _which_apply(self, token, rel):
        if token != self._which_token:
            return
        self._which = rel
        card = self._card()
        if (rel is not None and card and card == self._browsed
                and rel.get("kind") in ("other", "other_build")
                and self.emulate_overrides_var.get()):
            # A card picked with Browse that is not the project's runs as
            # it is: left ticked, the box laid the project's edits over it
            # and the run looked like the project's card, not the one
            # picked (PAD-205).  Ticking it again is one click.
            self.emulate_overrides_var.set(False)
            self._log("[emulate] %s is not your project's card, so it runs "
                      "as it is: \"Apply my replaced assets on top\" was "
                      "unticked. Tick it to run your edits on top of it."
                      % os.path.basename(card))
        self._browsed = None
        if rel is not None:
            same = os.path.normcase(os.path.abspath(self._card()))
            for key in ("source", "build"):
                if rel.get(key) and os.path.normcase(
                        os.path.abspath(rel[key])) == same:
                    rel = dict(rel, **{key: ""})
        self.set(which=rel)

    @rpc
    def use_card(self, key):
        """Switch the card to run to the project's extracted card
        (``"source"``) or its newest build (``"build"``)."""
        path = (self._which or {}).get(key) or ""
        if key not in ("source", "build") or not path:
            return False
        self.emulate_card_var.set(os.path.normpath(path))
        return True

    def _card_game(self):
        path = self._card()
        if not path:
            return None
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        m = re.match(r"([a-z0-9_]+?)-\d", base.lower())
        return m.group(1) if m else None

    @rpc
    def browse(self):
        # The folder of the current card by STRING only: a stat of a card on
        # a sleeping NAS share would freeze the loop before the picker even
        # opened (Tk's Browse did no filesystem call at all).  The picker
        # itself runs off the loop and copes with a folder that is gone.
        card = self._card()
        path = self.window.ask_open(
            "emulate_card", "Pick a Spike 2 card image",
            [("Card images", "*.raw *.img"), ("All files", "*.*")],
            initialdir=os.path.dirname(card) if card else None)
        if path:
            path = os.path.normpath(path)
            if path != card:
                self._browsed = path
            self.emulate_card_var.set(path)
        return path or ""

    def _precache_kick(self):
        if sys.platform == "darwin" or no_rig() or not rig.rig_available():
            return
        path = self._card()
        if not path or path == self._precached:
            return
        if self._proc is not None or self._last_up or self._starting:
            return

        def run():
            if not os.path.isfile(path) or path == self._precached:
                return
            self._precached = path
            try:
                cmd = self._cmd("cardmount.sh", rig.wsl_path(path),
                                "--precache")
                self._popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
                self._log("[emulate] pre-caching %s in the background"
                          % os.path.basename(path))
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] pre-cache failed to start: %s" % exc)

        self._thread(run)

    # -- boot selector (item 90): the CARD decides, a hand overrides -----
    @rpc
    def set_select(self, value):
        self._select_var.set(bool(value))
        self._select_touched = True
        self._select_hint()
        return True

    def _select_hint(self, busy=False):
        tip = rig.SELECT_TIP_IDLE
        if busy:
            tip = rig.SELECT_TIP_BUSY
        elif self._select_menu is True:
            tip = ("This card carries a boot menu"
                   + (" (%s)" % self._select_why if self._select_why else "")
                   + ".\n\nThe emulator shows it before the game, exactly as "
                     "the machine does. Untick to skip it and boot the first "
                     "image straight away.")
        elif self._select_menu is False:
            tip = ("This card has no boot menu"
                   + (" - %s" % self._select_why if self._select_why else "")
                   + ".\n\nThere is nothing to choose between, so the game "
                     "boots straight away. Tick it anyway to force a menu.")
        elif self._select_why:
            tip = ("Nobody could tell whether this card carries a boot menu "
                   "- %s.\n\nThe emulator asks the card again when it starts, "
                   "so leave this alone unless you want to force the answer: "
                   "tick it for a menu, untick it for none."
                   % self._select_why)
        self.set(select_tip=tip, select_menu=self._select_menu)

    def _select_probe_kick(self):
        path = self._card()
        if path != self._select_probed:
            self._select_probed = path
            self._select_stamp = None
            self._select_menu = None
            self._select_why = ""
            self._select_touched = False
            self._select_var.set(False)
            self._select_hint()
        if no_rig():
            return
        if not (path and sys.platform != "darwin" and rig.rig_available()
                and os.path.isfile(os.path.join(rig.rig_dir(), "parts.py"))):
            return
        self._select_hint(busy=True)
        stamp_now = self._select_stamp

        def run():
            try:
                cmd = rig.multiboot_cmd(path)   # built off the UI loop
            except Exception:                            # noqa: BLE001
                cmd = None
            if cmd is None:
                self._post(self._select_apply, path, None, None, None)
                return
            try:
                st = os.stat(path)
            except OSError as exc:
                self._post(self._select_apply, path, "unknown",
                           "cannot read %s: %s"
                           % (os.path.basename(path) or path,
                              getattr(exc, "strerror", exc)), None)
                return
            stamp = (st.st_mtime, st.st_size)
            if stamp == stamp_now:
                self._post(self._select_apply, path, None, None, stamp)
                return
            try:
                r = self._run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,
                              timeout=rig._MULTIBOOT_PROBE_S)
                out = (r.stdout or b"").decode("utf-8", "replace")
            except Exception:                            # noqa: BLE001
                self._post(self._select_apply, path, "unknown",
                           "the card could not be asked here", None)
                return
            state, why = rig.parse_multiboot(out)
            self._post(self._select_apply, path, state, why, stamp)

        self._thread(run)

    def _select_apply(self, path, state, why, stamp=None):
        if path != self._select_probed:
            return
        if stamp is not None:
            self._select_stamp = stamp
        if state is not None:
            self._select_menu = {"yes": True, "no": False}.get(state)
            self._select_why = why or ""
            if not self._select_touched and self._select_menu is not None:
                self._select_var.set(self._select_menu)
        self._select_hint()

    # -- the machine row (PAD-149) -----------------------------------------
    def _machine_env(self):
        env = []
        try:
            index = rig.COUNTRIES.index(self.emulate_country_var.get())
        except ValueError:
            index = None
        if index is not None:
            env += ["PAD_CAB_DIP=%d" % index, "PAD_COUNTRY=%d" % index]
        power = self.emulate_power_var.get()
        for label, extra in rig.POWER_CHOICES:
            if label == power:
                env.extend(extra)
                break
        return env

    # -- the overrides opt-in (PAD-103) ------------------------------------
    def _assets(self):
        var = self._assets_var
        try:
            return var.get().strip() if var is not None else ""
        except Exception:                                # noqa: BLE001
            return ""

    def _overrides_paint(self):
        assets = self._assets()
        if not self.emulate_overrides_var.get():
            text = rig.OVR_OFF
        elif not assets:
            text = rig.OVR_NO_ASSETS
        else:
            text = rig.OVR_ON
        # The whole paragraph, as Tk showed it: the ON text names the cost
        # (Start re-encodes first) and that a Replace-tab pick is written
        # into the project folder at Start, and neither may hide behind a
        # hover (must survive #4).
        self.set(assets=assets, ovr_hint=text, ovr_refused=False)

    def _overrides_wanted(self):
        if not self.emulate_overrides_var.get() or self._assets_var is None:
            return None
        assets = self._assets()
        if not assets:
            return None
        return (self._card(), assets)

    # ------------------------------------------------------------------
    # volume (item 56): LIVE, never greyed
    # ------------------------------------------------------------------
    def _on_volume_change(self, *_a):
        if getattr(self, "_following_audio", False):
            return
        try:
            gain = max(0.0, min(1.0, float(self._volume_var.get()) / 100.0))
        except (TypeError, ValueError):
            gain = 1.0
        write_audio_ctl(gain, bool(self._mute_var.get()))

    def _follow_audio_ctl(self):
        """PAD-204: the virtual playfield window writes the same file from its
        status bar, so the slider follows it on the status poll. It never
        writes the file back: setting the two vars one at a time would
        otherwise save the new volume beside the OLD mute in between."""
        gain, muted = load_audio_ctl()
        vol = round(gain * 100)
        self._following_audio = True
        try:
            try:
                if round(float(self._volume_var.get())) != vol:
                    self._volume_var.set(vol)
            except (TypeError, ValueError):
                pass
            if bool(self._mute_var.get()) != muted:
                self._mute_var.set(muted)
        finally:
            self._following_audio = False

    # ------------------------------------------------------------------
    # Docker (macOS)
    # ------------------------------------------------------------------
    def _docker_check(self):
        if self._docker_busy or sys.platform != "darwin" or no_rig():
            return
        self._docker_busy = True

        def run():
            state = None
            try:
                state = self._docker_probe()
            finally:
                self._docker_busy = False
                self._post(self._docker_back, state)

        self._thread(run)

    def _docker_probe(self):
        self._docker_cli = rig.docker_cli()
        self._docker_engine = rig.docker_engine()
        return rig.docker_state()

    def _docker_back(self, state):
        if self._stopped:
            return
        if state is not None:
            self._docker_apply(state)
        else:
            self._docker_report_if_asked(None)

    def _docker_report_if_asked(self, state):
        if not self._docker_report_next:
            return
        self._docker_report_next = False
        for line in rig.setup_report_darwin(state, self._docker_cli,
                                            self._docker_engine):
            self.log("[emulate] " + line)
        self.set(check_label="Check setup…", check_enabled=True)

    def _docker_apply(self, state):
        self._docker = state
        self._docker_report_if_asked(state)
        if state == "ok":
            self.set(docker_btn=None, setup_btn=False, docker_msg="")
            return
        plan = (rig.engine_setup_plan(self._docker_cli)
                if state in ("engineless", "absent") else None)
        if state == "stopped":
            eng = self._docker_engine
            label = eng[0] if eng else "Docker Desktop"
            msg = ("Docker is installed but not running, and the "
                   "emulator runs inside it. Click “Start Docker”, or "
                   "start %s yourself and give it a moment to come up."
                   % label)
        elif state == "engineless":
            msg = ("The docker command is installed here (%s), but "
                   "nothing on this Mac can run a container: on macOS "
                   "docker is only the client, and the containers "
                   "themselves need a Linux machine behind it."
                   % (self._docker_cli or "found on PATH")
                   + (rig.plan_sentence(plan) if plan else
                      " Docker Desktop, OrbStack and Colima each "
                      "provide one; the button below opens the Docker "
                      "Desktop download page."))
        else:
            msg = ("Docker is required to emulate on macOS: the game is "
                   "a Linux program and a container is how this Mac "
                   "runs one. It is a one-time install."
                   + (rig.plan_sentence(plan) if plan else
                      "\nThe button below opens the download page."))
        if plan:
            self.set(docker_msg=msg, docker_btn=None, setup_btn=True)
        else:
            self.set(docker_msg=msg, setup_btn=False,
                     docker_btn=("Start Docker" if state == "stopped"
                                 else "Get Docker…"))

    @rpc
    def docker_fix(self):
        if self._setup_fixing:
            return False
        if self._docker == "stopped":
            self._docker_start_engine()
            return True
        self._docker_download()
        return True

    def _docker_download(self):
        self.window.open_link(rig.DOCKER_URL)
        self.log("[emulate] opened %s - install it, then click Start "
                 "emulator again" % rig.DOCKER_URL)

    def _docker_start_engine(self):
        eng = self._docker_engine
        if eng and eng[1] == "cli":
            self.log("[emulate] starting %s; the first start takes a couple "
                     "of minutes" % eng[0])
            self._run_engine_setup([("starting %s" % eng[0],
                                     [eng[2], "start"], False)])
            return
        target = eng[2] if eng else "Docker"
        label = eng[0] if eng else "Docker Desktop"
        try:
            self._popen(["open", "-a", target])
            self.log("[emulate] starting %s; it takes a moment to come up"
                     % label)
        except Exception as exc:                         # noqa: BLE001
            self.log("[emulate] could not start %s: %s" % (label, exc))
        self._after(4000, self._docker_check)

    def _run_engine_setup(self, phases):
        self._setup_fixing = True
        self.set(setup_enabled=False, setup_label="Setting up…",
                 docker_enabled=False)

        def run():
            ok = True
            try:
                for label, argv, admin in phases:
                    argv = argv() if callable(argv) else argv
                    if not argv:
                        ok = False
                        self._log("[emulate] %s: the command it needs is not "
                                  "on this Mac, even after the install above."
                                  % label)
                        break
                    ok = self._run_step(label, argv, admin)
                    if not ok:
                        break
            except Exception as exc:                     # noqa: BLE001
                ok = False
                self._log("[emulate] setup failed: %s" % exc)
            if ok:
                self._log("[emulate] the container engine is installed and "
                          "running; this Mac can emulate now.")
            self._setup_fixing = False
            self._post(self._setup_recheck)

        self._thread(run)

    def _run_step(self, label, argv, admin):
        self._log("[emulate] %s: %s" % (label, " ".join(argv)))
        if not admin:
            try:
                proc = self._popen(argv, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] could not start %s: %s" % (argv[0], exc))
                return False
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self._log("[emulate] " + line)
            rc = proc.wait()
            if rc:
                self._log("[emulate] %s did not finish (exit %s)."
                          % (label, rc))
            return rc == 0
        work = tempfile.mkdtemp(prefix="pad_engine_")
        script = os.path.join(work, "setup.sh")
        out = os.path.join(work, "setup.log")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + " ".join(shlex.quote(a) for a in argv)
                    + "\n")
        shell = "/bin/sh %s > %s 2>&1" % (shlex.quote(script),
                                          shlex.quote(out))
        osa = ('do shell script "%s" with administrator privileges'
               % shell.replace("\\", "\\\\").replace('"', '\\"'))
        try:
            proc = self._popen(["osascript", "-e", osa],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as exc:                         # noqa: BLE001
            self._log("[emulate] could not ask macOS for permission: %s" % exc)
            return False
        seen = 0
        while proc.poll() is None:
            seen = self._tail(out, seen)
            time.sleep(0.5)
        self._tail(out, seen)
        err = (proc.stderr.read() or b"").decode("utf-8", "replace")
        shutil.rmtree(work, ignore_errors=True)
        if proc.returncode == 0:
            return True
        if "-128" in err or "cancel" in err.lower():
            self._log("[emulate] setup cancelled; nothing was changed.")
        else:
            self._log("[emulate] %s did not finish. %s"
                      % (label, err.strip() or "See the lines above."))
        return False

    def _tail(self, path, seen):
        try:
            with open(path, "rb") as f:
                f.seek(seen)
                data = f.read()
        except OSError:
            return seen
        if not data:
            return seen
        text = data.decode("utf-8", "replace")
        keep = text.rsplit("\n", 1)
        done = keep[0] if len(keep) > 1 else ""
        for line in done.splitlines():
            if line.strip():
                self._log("[emulate] " + line.rstrip())
        return seen + len(done.encode("utf-8")) + (1 if len(keep) > 1 else 0)

    # ------------------------------------------------------------------
    # setup probe (Windows / Linux)
    # ------------------------------------------------------------------
    def _setup_check(self):
        if self._setup_busy or sys.platform == "darwin" or no_rig():
            return
        self._setup_busy = True
        self._setup_ticks = 0

        def run():
            facts = None
            try:
                facts = rig.setup_state()
                if sys.platform == "win32":
                    # warm the launch's account answer here, off the UI
                    # loop: launch_as_root() is asked from the loop (the
                    # Modes tab's Try it) and wsl_home() caches it
                    rig.wsl_home()
            except Exception:                            # noqa: BLE001
                log.exception("emulate setup probe")
            finally:
                self._post(self._setup_back, facts)

        self._thread(run)
        self._setup_tick_job = self._after(250, self._setup_tick)

    def _setup_tick(self):
        """The Tk drain's ticking half: a probe out this long is the first
        wsl.exe after a reboot booting the VM, and the tab says so."""
        self._setup_tick_job = None
        if self._stopped or not self._setup_busy:
            return
        self._setup_ticks += 1
        if self._setup_ticks == rig._WSL_BOOT_TICKS and \
                sys.platform == "win32":
            self._setup_said_boot = True
            self._set("state", "Starting WSL…")
            self._hint(rig._WSL_BOOT_TEXT)
            self.log("[emulate] starting WSL — the first start after a "
                     "Windows reboot can take a minute")
        self._setup_tick_job = self._after(250, self._setup_tick)

    def _setup_back(self, facts):
        self._setup_busy = False
        if self._setup_tick_job is not None:
            self.ctx.loop.after_cancel(self._setup_tick_job)
            self._setup_tick_job = None
        if self._stopped:
            return
        if self._setup_said_boot:
            self._setup_said_boot = False
            self._set("state", "—")
            self._hint("")
        if facts is not None:
            self._setup_apply(facts)
        else:
            self._setup_report_if_asked(None)

    @rpc
    def check_setup(self):
        """“Check setup…”: re-probe and ALWAYS report in full to the log."""
        if self._setup_busy:
            return False
        self.set(check_label="Checking…", check_enabled=False)
        self.log("[emulate] checking what this PC needs…")
        if no_rig():
            self.log("[emulate] " + NO_RIG_TEXT)
            self.set(check_label="Check setup…", check_enabled=True)
            return False
        if sys.platform == "darwin":
            self._docker_report_next = True
            self._docker_check()
            if not self._docker_busy:
                self._docker_report_if_asked(self._docker)
            return True
        self._setup_report_next = True
        self._setup_check()
        return True

    def _setup_report_if_asked(self, facts):
        if not self._setup_report_next:
            return
        self._setup_report_next = False
        for line in rig.setup_report(facts):
            self.log("[emulate] " + line)
        self.set(check_label="Check setup…", check_enabled=True)

    def _setup_apply(self, facts):
        self._setup = facts
        self._setup_report_if_asked(facts)
        if self._setup_restart_check:
            self._setup_restart_check = False
            if facts and not rig.setup_ok(facts):
                self.log("[emulate] the restart took the 32-bit ARM handler "
                         "with it, so the emulator cannot start until it is "
                         "registered again — press “Set up emulator…” above, "
                         "which does that and makes it survive the next "
                         "restart.")
        if rig.setup_settled(facts):
            self.set(setup_btn=False, setup_msg="")
            return
        self.set(setup_msg=rig.setup_notice(facts,
                                            can_fix=sys.platform == "win32"),
                 setup_btn=bool(sys.platform == "win32"
                                and rig.setup_fixable(facts)))

    @rpc
    def setup_fix(self):
        """“Set up emulator…”: the consent lists every change exactly."""
        if self._setup_fixing:
            return False
        if sys.platform == "darwin":
            return self._setup_fix_darwin()
        if sys.platform != "win32":
            return False
        steps = rig.setup_fix_steps(self._setup or {})
        if not steps:
            return False
        if not compat.messagebox.askyesno(
                "Set up the emulator",
                "This will change your WSL installation:\n\n"
                + "\n\n".join("  •  " + s for s in steps)
                + "\n\nIt runs as root inside WSL, which needs no password. "
                  "Nothing on the Windows side is touched, and nothing is "
                  "removed.\n\nGo ahead?"):
            return False
        self._setup_fixing = True
        self.set(setup_enabled=False, setup_label="Setting up…")

        def run():
            result = ""
            restart = False
            criu = ""
            try:
                cmd = self._cmd_root("setupfix.sh")
                self._log("[emulate] %s" % " ".join(cmd))
                proc = self._popen(cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
                for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    if line.startswith("result="):
                        result = line.split("=", 1)[1]
                    elif line.startswith("extras_criu="):
                        criu = line.split("=", 1)[1]
                    elif line == "needs_restart=1":
                        restart = True
                    if line:
                        self._log("[emulate] " + line)
                proc.wait(timeout=60)
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] setup failed: %s" % exc)
            if result == "ok":
                self._log("[emulate] this PC can run the emulator now.")
                if restart and runtime.distro_for("spike2"):
                    self._log("[emulate] the ARM handler is registered for as "
                              "long as WSL stays up. The app's own Linux does "
                              "not run systemd, so after a full WSL restart "
                              "(or a reboot) press this button again — it "
                              "takes a moment and nothing else is affected.")
                elif restart:
                    self._log("[emulate] systemd was turned on for WSL so the "
                              "ARM handler survives a restart; it takes effect "
                              "the next time WSL starts, and nothing needs "
                              "restarting now.")
            elif result == "nocandidate":
                self._log("[emulate] setup cannot finish on this WSL "
                          "installation: the package it needs is not offered "
                          "by any of that Linux's package sources, so trying "
                          "again will say the same thing.")
            else:
                self._log("[emulate] setup did not finish — the emulator will "
                          "probably still fail to start.")
            if criu == "ok":
                self._log("[emulate] criu was built and installed, so save "
                          "states work from the next title you start.")
            elif criu == "failed":
                self._log("[emulate] criu could not be built — see above. "
                          "Everything else is set up: titles start and run, "
                          "and only the Save/Load state buttons stay off.")
            self._setup_fixing = False
            self._post(self._setup_recheck)

        self._thread(run)
        return True

    def _setup_fix_darwin(self):
        plan = rig.engine_setup_plan(self._docker_cli)
        if not plan:
            self._docker_download()
            return True
        if not compat.messagebox.askyesno(
                "Set up the emulator",
                "This Mac needs a container engine before it can emulate. "
                "This will:\n\n"
                + "\n\n".join("  •  " + s for s in plan["steps"])
                + "\n\nIt runs here, in this window, and you can watch it in "
                  "the log below. Nothing is removed.\n\nGo ahead?"):
            return False
        self.log("[emulate] setting up a container engine with %s"
                 % plan["manager"])
        self._run_engine_setup([
            ("installing " + plan["label"], plan["install"], plan["admin"]),
            ("starting Colima", self._colima_argv, False),
        ])
        return True

    @staticmethod
    def _colima_argv():
        colima = rig.which_tool("colima")
        return [colima, "start"] if colima else None

    def _setup_recheck(self):
        self.set(setup_enabled=True, setup_label="Set up emulator…",
                 docker_enabled=True)
        if sys.platform == "darwin":
            self._docker_check()
        else:
            self._setup_check()

    # ------------------------------------------------------------------
    # the app's own Linux (core.runtime)
    # ------------------------------------------------------------------
    def _runtime_apply(self, rt):
        if rt is None:
            return
        state, detail = rt
        if state not in rig._runtime_ui.UNPROMPTED and state != "foreign":
            self.set(rt_btn=False, rt_msg="")
            return
        text = rig._runtime_ui.notice(state, detail)
        self.set(rt_msg=text,
                 rt_btn=bool(state in rig._runtime_ui.UNPROMPTED
                             and rig._runtime_ui.can_install()))
        if not self._rt_noted:
            self._rt_noted = True
            self.log("[emulate] " + " ".join(text.split()))

    @rpc
    def runtime_fix(self):
        """“Update emulator Linux…”."""
        if self._proc is not None or self._last_up or self._starting:
            self.log("[emulate] the emulator is running — stop it first.")
            return False
        if no_rig():
            self.log("[emulate] " + NO_RIG_TEXT)
            return False
        self.set(rt_enabled=False, rt_label="Updating…")
        self._rt_pct = -10
        say = lambda m: self._log("[emulate] %s" % m)       # noqa: E731

        def ask():
            # runtime_prompt's ONE wording (it names the save states),
            # asked on the page through compat.messagebox
            return self._ask_before_replacing()

        def work():
            try:
                state = rig._runtime_ui.ensure(
                    say=say, progress=self._runtime_progress, ask=ask,
                    on_blocked=lambda exc: self._post(
                        self._offer_from_file, exc))
                if state == "ready":
                    self._ensure_data_disk()
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] %s" % exc)
            finally:
                self._rt_noted = False
                runtime.invalidate()
                self._post(lambda: self.set(rt_enabled=True,
                                            rt_label="Update emulator Linux…"))

        self._thread(work)
        return True

    def _ask_before_replacing(self):
        """``_runtime_ui.ask_before_replacing`` on the UI loop, from any
        thread: the one consent that names the save states."""
        return bool(self.ctx.loop.call(rig._runtime_ui.ask_before_replacing))

    def _offer_from_file(self, exc):
        """``_runtime_ui.offer_from_file`` with its install on a worker.

        Not called directly: that one runs ``runtime.install`` (a 370 MB
        import) and ``runtime.status`` on the calling thread, which is the UI
        loop here.  The replace question is ``_runtime_ui``'s own; the
        from-a-file question is ``rig.from_file_question`` (the same
        sentence)."""
        title, message, pick_title, filename = rig.from_file_question(exc)
        if not compat.messagebox.askyesno(title, message):
            return
        path = compat.filedialog.askopenfilename(title=pick_title,
                                                 initialfile=filename)
        if not path:
            return
        say = lambda m: self._log("[emulate] %s" % m)       # noqa: E731

        def work():
            try:
                # status() can run wsl.exe: asked here, off the loop
                replace = (self._ask_before_replacing()
                           if runtime.status()[0] != "absent" else False)
                runtime.install(log=say, source=path, replace=replace)
            except Exception as e:                       # noqa: BLE001
                say(str(e))

        self._thread(work)

    def _runtime_progress(self, done, total):
        if not total:
            return
        pct = int(done * 100 / total)
        if pct >= self._rt_pct + 10:
            self._rt_pct = pct
            self._log("[emulate] downloading… %d%% of %d MB"
                      % (pct, total // (1024 * 1024)))

    def _reattach_data_disk(self):
        if not runtime.wsl_distro() or not rigdata.exists():
            return
        d = runtime.wsl_distro()
        try:
            if rigdata.attached(d):
                return
            self._log("[emulate] the emulator's work disk came unattached "
                      "(a WSL restart does that); attaching it again.")
            rigdata.attach(d)
        except Exception as exc:                         # noqa: BLE001
            self._log("[emulate] could not re-attach the work disk (%s). The "
                      "run will stop rather than write into memory." % exc)

    def _ensure_data_disk(self):
        d = runtime.wsl_distro()
        if not d:
            return
        try:
            if rigdata.ensure(d, log=lambda m: self._log("[emulate] %s" % m)):
                free = rigdata.free_bytes(d)
                if free and free < rigdata.LOW_SPACE_BYTES:
                    self._log("[emulate] the emulator's data disk is nearly "
                              "full (%.1f GB free)." % (free / 1073741824.0))
        except Exception as exc:                         # noqa: BLE001
            self._log("[emulate] could not set aside the work disk (%s); the "
                      "emulator will keep its work inside the Linux instead."
                      % exc)

    # ------------------------------------------------------------------
    # save states (item 13): always on
    # ------------------------------------------------------------------
    @rpc
    def slots_refresh(self):
        if sys.platform != "win32":
            return False

        def run():
            rows, total, free = [], None, None
            try:
                r = self._run(self._cmd_root("slots.sh", "list"), capture_output=True, timeout=30)
                for ln in (r.stdout or b"").decode("utf8",
                                                   "replace").splitlines():
                    p = ln.split("|")
                    if p[0] == "slot" and len(p) >= 6:
                        rows.append(p[1:6])
                    elif p[0] == "total" and len(p) > 1:
                        total = int(p[1] or 0)
                    elif p[0] == "free" and len(p) > 1:
                        free = int(p[1] or 0)
            except Exception:                            # noqa: BLE001
                pass

            def apply():
                self._slots_rows = rows
                self._slots_total = total
                self._slots_free = free
                self._slots_paint()
            self._post(apply)

        self._thread(run)
        return True

    def _slots_paint(self):
        rows = self._slots_rows
        if rows is None:
            return
        game_now = self._card_game()
        out = []
        by_iid = {}
        shown = hidden = 0
        for name, size, game, label, mtime in rows:
            if game_now and game and game != game_now:
                hidden += 1
                continue
            shown += 1
            try:
                when = time.strftime("%b %d %H:%M",
                                     time.localtime(int(mtime)))
            except (ValueError, OverflowError, OSError):
                when = "?"
            row = {"iid": name, "slot": name.rsplit("/", 1)[-1],
                   "name": label or "", "game": game,
                   "size": rig.human(size), "saved": when}
            by_iid[name] = row
            out.append(row)
        self._slot_by_iid = by_iid
        if self._slot_sel not in by_iid:
            self._slot_sel = None
        if self._slots_total is None:
            summary = "Could not read the slots - is WSL up?"
        else:
            bits = []
            if game_now:
                bits.append("%d slot%s for %s" % (
                    shown, "" if shown == 1 else "s", game_now))
                if hidden:
                    bits.append("%d for other game%s hidden" % (
                        hidden, "" if hidden == 1 else "s"))
            else:
                bits.append("%d slot%s" % (shown, "" if shown == 1 else "s"))
            bits.append("all slots %s" % rig.human(self._slots_total))
            bits.append("free on the WSL disk: %s"
                        % rig.human(self._slots_free))
            summary = " · ".join(bits)
        # "No save states" only after a read that answered (a failed read
        # says so in the summary and claims nothing about the slots)
        self.set(slots=out, slot_sel=self._slot_sel, slots_sum=summary,
                 slots_read=self._slots_total is not None)

    @rpc
    def select_slot(self, iid):
        self._slot_sel = iid if iid in self._slot_by_iid else None
        self.set(slot_sel=self._slot_sel)
        return self._slot_sel is not None

    def _slot_selected(self):
        return self._slot_sel if self._slot_sel in self._slot_by_iid else None

    @rpc
    def slot_launch(self):
        slot = self._slot_selected()
        if not slot:
            self.set(slots_sum="Pick a slot to launch first.")
            return False
        slot_game = str(self._slot_by_iid[slot].get("game") or "")
        game_now = self._card_game()
        if slot_game and game_now and slot_game != game_now:
            self.set(slots_sum="That save is for %s - pick that title's card "
                               "first." % slot_game)
            return False
        if self._loading or self._starting or self._stopping:
            return False
        if self._last_up:
            self._slot_load(slot)
            return True
        self._launch_slot = slot
        self.log("[emulate] will load slot '%s' once the game is up" % slot)
        serial = self._launch_serial
        self.start()
        if self._launch_serial == serial:   # start refused (bad path, busy)
            self._launch_slot = None
        return True

    def _slot_load(self, slot):
        if self._stopping:
            return
        self._loading = True
        self._set("state", "Loading save…")
        self.log("[emulate] loading slot '%s'" % slot)

        def run():
            try:
                r = self._run(self._load_cmd(slot), capture_output=True,
                              timeout=240)
                lines = [ln.strip() for ln in
                         (r.stdout or b"").decode("utf8",
                                                  "replace").splitlines()
                         + (r.stderr or b"").decode("utf8",
                                                    "replace").splitlines()
                         if ln.strip()]
            except Exception:                            # noqa: BLE001
                lines = ["loadgame.sh did not run"]
            for ln in lines[-12:]:
                self._log("[emulate] " + ln)

            def done():
                self._loading = False
            self._post(done)

        self._thread(run)

    @rpc
    def slot_rename_begin(self):
        slot = self._slot_selected()
        if not slot:
            self.set(slots_sum="Pick a slot to rename first.")
            return False
        self.set(rename={"slot": slot,
                         "value": self._slot_by_iid[slot].get("name") or ""})
        return True

    @rpc
    def slot_rename(self, text):
        ren = self.get("rename")
        self.set(rename=None)
        if not ren:
            return False
        ok = ("abcdefghijklmnopqrstuvwxyz"
              "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _.()!-")
        label = "".join(ch for ch in str(text or "") if ch in ok).strip()[:40]
        self._slot_cmd(["label", ren["slot"]] + ([label] if label else []))
        return True

    @rpc
    def slot_rename_cancel(self):
        self.set(rename=None)
        return True

    @rpc
    def slot_delete(self):
        slot = self._slot_selected()
        if not slot:
            self.set(slots_sum="Pick a slot to delete first.")
            return False
        size = " (%s)" % self._slot_by_iid[slot].get("size", "")
        if not compat.messagebox.askyesno(
                "Delete save state",
                "Delete slot '%s'%s?\n\nThe saved game in it is gone for "
                "good." % (slot, size)):
            return False
        self._slot_cmd(["delete", slot])
        return True

    def _slot_cmd(self, args):
        self.set(slots_enabled=False)

        def run():
            out = ""
            try:
                r = self._run(self._cmd_root("slots.sh", *args),
                              capture_output=True, timeout=60)
                out = (r.stdout or b"").decode("utf8", "replace").strip()
            except Exception:                            # noqa: BLE001
                out = "slots.sh did not run"
            if out:
                self._log("[emulate] %s" % out.splitlines()[-1])

            def apply():
                self.set(slots_enabled=True)
                self.slots_refresh()
            self._post(apply)

        self._thread(run)

    # ------------------------------------------------------------------
    # the card cache manager (item 77)
    # ------------------------------------------------------------------
    @rpc
    def open_cache(self):
        if not rig.rig_available():
            self._hint("No emulator rig on this machine — there is no card "
                       "cache to manage.")
            return False
        if self._cache_open:
            return True
        self._cache_open = True
        self._cache_sel = []
        self.set(cache={"head": "Reading the cache…", "rows": [],
                        "sel": [], "busy": True,
                        "hint": "Deleting frees the space now; the card "
                                "re-copies on its next boot."})
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
        self._cache_patch(head="Reading the cache…", busy=True, sel=[])
        self._cache_sel = []

        def run():
            try:
                out = self._run(self._cmd("cardmount.sh", "--cache-list"),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=30)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                            # noqa: BLE001
                text = ""
            result = rig.parse_cache_list(text)
            self._post(self._cache_show, result)

        self._thread(run)
        return True

    def _cache_show(self, result):
        if not self._cache_open:
            return
        entries, disk = result
        self._cache_entries = {e["label"]: e for e in entries}
        rows = [{"label": e["label"], "size": rig.human_size(e["real_kb"]),
                 "booted": rig.cache_boot_text(e["boot"]), "src": e["src"]}
                for e in entries]
        total = sum(e["real_kb"] for e in entries)
        if disk:
            head = ("%d cached cards — %s on disk · %s free of %s (WSL disk)"
                    % (len(entries), rig.human_size(total),
                       rig.human_size(disk[0]), rig.human_size(disk[1])))
        elif entries:
            head = "%d cached cards — %s on disk" % (
                len(entries), rig.human_size(total))
        else:
            head = ("The card cache is empty — cards land here on their "
                    "first boot.")
        self._cache_patch(head=head, rows=rows, busy=False, sel=[])

    @rpc
    def cache_select(self, labels):
        self._cache_sel = [l for l in (labels or [])
                           if l in self._cache_entries]
        self._cache_patch(sel=list(self._cache_sel))
        return len(self._cache_sel)

    @rpc
    def cache_delete(self):
        labels = list(self._cache_sel)
        if not self._cache_open or not labels:
            return False
        freed = sum(self._cache_entries.get(l, {}).get("real_kb", 0)
                    for l in labels)
        if not compat.messagebox.askyesno(
                "Delete cached cards",
                "Delete %d cached card%s, freeing about %s?\n\n"
                "Each re-copies on its next boot — nothing is lost."
                % (len(labels), "" if len(labels) == 1 else "s",
                   rig.human_size(freed))):
            return False
        self._cache_patch(busy=True, hint="Deleting…")

        def run():
            for label in labels:
                try:
                    out = self._run(
                        self._cmd("cardmount.sh", "--cache-drop", label),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=30)
                    for line in out.stdout.decode(
                            "utf-8", "replace").splitlines():
                        self._log("[emulate] " + line)
                except Exception as exc:                 # noqa: BLE001
                    self._log("[emulate] cache drop %s failed: %s"
                              % (label, exc))

            def done():
                self._cache_patch(hint="Deleting frees the space now; the "
                                       "card re-copies on its next boot.")
                self.cache_refresh()
            self._post(done)

        self._thread(run)
        return True

    # ------------------------------------------------------------------
    # preparing the run: source, overrides, a caller's preparation
    # ------------------------------------------------------------------
    def _source_env(self):
        path = self._card()
        if not path:
            self._hint("Pick a card image first — the one on the Extract tab, "
                       "the one Write builds, or any other Spike 2 card.")
            return None
        if not os.path.isfile(path):
            self._hint("No such image: %s" % path)
            return None
        env = ["PAD_CARD=%s" % rig.wsl_path(path)]
        if not self._topper_var.get():
            env.append("PAD_TOPPER=0")
        return env

    def _prepare_overrides(self, card, assets, selector=False):
        from ...core.checksums import read_checksums
        from ...plugins.stern import engine as stern_engine
        if not os.path.isdir(assets):
            self._overrides_refuse(
                "There is no assets folder to apply: %s" % (assets or "(none)"))
            return None
        if not read_checksums(assets):
            self._overrides_refuse(
                "%s has no .checksums.md5 baseline, so nothing there can be "
                "told apart from the card's own assets. Re-extract the card "
                "and the edits you make in the new folder can be run here."
                % assets)
            return None
        if self._stage_fn() is not None and not self._stage_pending(assets):
            return None
        if selector:
            self._log(rig.MULTI_IMAGE_NOTE)
        picked = card
        card, note = rig.override_base_card(card, assets,
                                            stern_engine.card_title_index)
        if note:
            self._log("[emulate] " + note)
        out = rig.overrides_dir()
        fp = rig.assets_fingerprint(assets)
        manifest = stern_engine.read_override_manifest(out)
        why = rig.overrides_reason(manifest, card, assets, fp, run_card=picked)
        if not why:
            why = rig.preview_modes_reason(manifest, assets)
        if not why:
            self._log("[emulate] your edits are unchanged since the override "
                      "set in %s was built — reusing it" % out)
            return self._with_override_modes(
                out, ["PAD_OVERRIDE_DIR=%s" % rig.wsl_path(out)])
        self._log("[emulate] preparing your edits (%s)" % why)
        self._preparing = "Preparing your edits…"
        self._preparing_kind = "edits"
        self._post(self._repaint_preparing)
        try:
            counts, _mode, _val, files = stern_engine.write_overrides(
                card, assets, out,
                log=lambda msg, level="info": self._log("[emulate] " + msg),
                cancel=lambda: (self._stopping or self._stopped
                                or self._cancel_prepare),
                run_card=picked)
        except FileNotFoundError as exc:
            self._log("[emulate] nothing to apply: %s" % exc)
            self._preparing = None
            return []
        except Exception as exc:                         # noqa: BLE001
            self._preparing = None
            self._overrides_refuse(
                "Your edits could not be prepared: %s" % exc)
            return None
        finally:
            self._preparing = None
            self._preparing_kind = None
            # the one button said "Cancel" for this; now it is "Starting…"
            self._post(self._paint_run_btn)
        if counts is None:
            self._overrides_refuse("the preparation was cancelled")
            return None
        stern_engine.stamp_override_manifest(
            out, assets_fingerprint=rig.assets_fingerprint(assets))
        self._log("[emulate] %d card file(s) will be applied on top of the "
                  "card: %s" % (len(files),
                                ", ".join(p for p, _n in files[:6])))
        return self._with_override_modes(
            out, ["PAD_OVERRIDE_DIR=%s" % rig.wsl_path(out)])

    def _with_override_modes(self, out, env):
        from ...plugins.stern import engine as stern_engine
        try:
            modes = (stern_engine.read_override_manifest(out) or {}).get(
                "modes") or {}
        except Exception:                                # noqa: BLE001
            modes = {}
        stage = modes.get("dir") if isinstance(modes, dict) else None
        if not stage:
            return env
        names = ", ".join(modes.get("names") or ()) or "the project's modes"
        if not os.path.isdir(stage):
            self._overrides_refuse(
                "Your edits carry modes (%s), but their runtime folder %s is "
                "missing. Start again to rebuild the set." % (names, stage))
            return None
        stage_arg = rig.wsl_path(stage) if sys.platform == "win32" else stage
        cmd = (self._cmd_root("modes/tryit.sh", "install", stage_arg)
               if self.launch_as_root() else
               self._cmd("modes/tryit.sh", "install", stage_arg))
        try:
            r = self._run(cmd, capture_output=True, timeout=120)
            ok = r.returncode == 0
            said = ((r.stdout or b"") + (r.stderr or b"")).decode(
                "utf8", "replace").strip()
        except (OSError, subprocess.SubprocessError) as exc:
            ok, said = False, str(exc)
        if not ok:
            self._overrides_refuse(
                "Your edits carry modes (%s), and they could not be put in "
                "the emulator: %s" % (names, said[-400:]))
            return None
        self._log("[emulate] your edits carry modes (%s): their runtime runs "
                  "in this game, as on a card Written from the project"
                  % names)
        return list(env) + ["PAD_MODE_SO=%s" % rig.OVERRIDE_MODE_OBJECT]

    def _stage_fn(self):
        """PAD-121: ``App.stage_pending_replacements`` (the window's
        ``on_stage_pending`` callback), or None."""
        return self.window.cb.get("on_stage_pending")

    def _stage_pending(self, assets):
        stage = self._stage_fn()
        self._preparing = "Applying your replacements…"
        self._post(self._repaint_preparing)
        try:
            # "Runs on the caller's worker thread" (App's docstring), as
            # the Tk panel called it
            pending, staged, failures = stage(
                assets, cancel_cb=lambda: (
                    self._stopping or self._stopped or self._cancel_prepare))
        except Exception as exc:                         # noqa: BLE001
            self._overrides_refuse(
                "The replacements you assigned could not be applied to %s: %s"
                % (assets, exc))
            return False
        finally:
            self._preparing = None
            self._post(self._paint_run_btn)
        if pending and not staged:
            self._overrides_refuse(
                "None of the %d replacement(s) you assigned could be applied, "
                "so this run would be the stock card. %s"
                % (pending,
                   "; ".join("%s: %s" % (what, err)
                             for what, err in failures[:3])
                   or "See the log above."))
            return False
        if staged:
            self._log("[emulate] applied %d replacement(s) you assigned on "
                      "the Replace tabs to %s (the same thing a build does "
                      "before it repacks)" % (staged, assets))
            # the Replace tabs' previews still name the files just written
            # over; they now hold the picks, not the originals (PAD-209)
            notify = getattr(self.window, "folder_staged", None)
            if callable(notify):
                self._post(notify, assets)
        return True

    def _overrides_refuse(self, message, say=True):
        """A refused Start: the reason stays beside the opt-in (orange)
        until the box or the folder changes, and goes to the log."""
        if say:
            self._log("[emulate] " + message)
        self._post(lambda: self.set(ovr_hint=message, ovr_refused=True))

    # -- the launch API the Modes tab uses (item 127) ----------------------
    def prepare_refuse(self, reason, say=True):
        self._overrides_refuse(reason, say=say)

    def set_preparing(self, text, pct=None):
        """The Modes tab's Try it progress, from its worker: the State word,
        its ⓘ and the footer, as the tab's own edits preparation shows."""
        if (text, pct) == (self._preparing, self._preparing_pct) and \
                self._preparing_kind == ("modes" if text is not None
                                         else None):
            return
        self._preparing = text
        self._preparing_pct = pct
        if text is not None:
            self._preparing_kind = "modes"
        elif self._preparing_kind == "modes":
            self._preparing_kind = None
        self._post(self._repaint_preparing)

    def _repaint_preparing(self):
        if self._stopping or self._stopped:
            return
        text = self._preparing
        self._paint_run_btn()
        if text is None:
            return
        self._set("state", text)
        self.set(state_tip=self._preparing_explain())
        self._footer("copy", self._preparing_pct, text)

    def _preparing_explain(self):
        return rig._MODES_EXPLAIN if self._preparing_kind == "modes" \
            else rig._OVERRIDE_EXPLAIN

    def prepare_cancelled(self):
        return bool(self._cancel_prepare)

    def _launch_over(self, serial):
        self._post(self._tell_run_ended, serial)

    def _tell_run_ended(self, serial):
        cb = self.run_ended_cb
        if cb is None:
            modes = self.window.service("modes")
            cb = getattr(modes, "run_ended", None)
        if cb is None:
            return
        try:
            cb(serial)
        except Exception:                                # noqa: BLE001
            log.exception("run_ended")

    def launch_as_root(self):
        if no_rig():
            return False
        return sys.platform == "win32" and bool(rig.wsl_home())

    def launch_state(self):
        return {
            "up": bool(self._last_up),
            "busy": bool(self._starting or self._stopping),
            "overrides": self._overrides_wanted() is not None,
            "card": self._card(),
            "rig": rig.rig_available(),
        }

    def is_up(self):
        return bool(self._last_up)

    def launch_serial(self):
        return self._launch_serial

    def _refuse_start(self, reason):
        self.last_refusal = reason
        self.log("[emulate] " + reason)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    @rpc
    def toggle(self):
        """The ONE Start/Stop button."""
        if self._preparing is not None and not self._stopping:
            if not self._cancel_prepare:
                self._cancel_prepare = True
                self.log("[emulate] cancelling the preparation…")
            return True
        if self._starting or self._stopping:
            return False
        if self._last_up or self._launched():
            self.stop()
        else:
            self.start()
        return True

    def _launched(self):
        """The watch.sh this tab launched is still running.  Until the status
        poll counts it (a wsl.exe start, a poll already in flight) the rig
        says nothing is up, and the one button must not offer a second
        launcher on that word (must survive #0)."""
        proc = self._proc
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except Exception:                                # noqa: BLE001
            return True

    def _paint_run_btn(self):
        """``_run_label`` from what is known right now."""
        self._run_label(self._last_up or self._launched(),
                        self._starting or self._stopping)

    def _run_label(self, up, busy):
        if self._preparing is not None and not self._stopping:
            btn = {"label": "Cancel", "enabled": True, "mode": "cancel"}
        elif busy:
            btn = {"label": "Stopping…" if self._stopping else "Starting…",
                   "enabled": False, "mode": "busy"}
        elif up:
            btn = {"label": "Stop emulator", "enabled": True, "mode": "stop"}
        else:
            btn = {"label": "Start emulator",
                   "enabled": bool(rig.rig_available()), "mode": "start"}
        self.set(run_btn=btn)

    def _note_the_runtime_is_a_different_machine(self):
        if runtime.known_state() != "ready" or \
                not runtime.distro_for("spike2"):
            return
        if self._runtime_noted:
            return
        self._runtime_noted = True
        self._log("[emulate] The emulator now runs in the Linux this app "
                  "installs (%s), which carries its whole toolchain. The "
                  "first run there builds the rig's binaries and copies the "
                  "card again; anything cached in this PC's own distro is "
                  "untouched, and PAD_RUNTIME=0 goes back to using it."
                  % runtime.DISTRO)

    def _launch_env(self, src):
        env = ["PAD_AUDIO_DUMP=30", "PAD_AUDIO_CTL=" + audio_ctl_file()] + \
            list(src) + self._machine_env()
        if self._launch_slot:
            env.append("PAD_SELECT=0")
        elif self._select_touched:
            env.append("PAD_SELECT=1" if self._select_var.get()
                       else "PAD_SELECT=0")
        return env

    def _watch_cmd(self, env):
        if no_rig():
            return self._cmd("watch.sh", self.BACKSTOP_MIN, env=env)
        return rig.watch_cmd(self.BACKSTOP_MIN, env, savestates=True)

    def _kill_cmd(self):
        return self._cmd("killgame.sh") if no_rig() else rig.kill_cmd()

    def _load_cmd(self, slot):
        if no_rig():
            return self._cmd("loadgame.sh", slot, env=("PAD_RESTORE_KILL=1",))
        return rig.load_cmd(slot)

    def launch_card(self, path, select=False):
        """The Multi-boot tab's Run in emulator: this card, with the boot
        selector held on, launched exactly as Start would."""
        self.emulate_card_var.set(path or "")
        self._select_var.set(bool(select))
        self._select_touched = True
        self._select_hint()
        self.start()

    def launch_with(self, prepare):
        """Item 127, Try it: Start with a caller's one-shot preparation.
        Returns whether the launch was accepted; ``last_refusal`` says why
        not."""
        self.last_refusal = ""
        if (self._last_up or self._starting or self._stopping
                or self._launched()):
            self._refuse_start("the emulator is already running: stop it "
                               "first, then try again.")
            return False
        if self._overrides_wanted() is not None:
            reason = ("Try it runs your modes as an override set, and "
                      "\"apply my edits\" is ticked, which is another one. A "
                      "run takes one set for now: untick it to try the modes.")
            self.last_refusal = reason
            self._overrides_refuse(reason)
            return False
        self._launch_prepare = prepare
        self._launch_accepted = False
        self.start()
        return bool(self._launch_accepted)

    # -- window seams (MainWindow._modes_play / _modes_try / Multi-boot) --
    def play(self):
        self.window.select_tab(self.ns)
        self.start()

    def try_it(self, prepare):
        if not self.launch_with(prepare):
            return False, str(self.last_refusal or
                              "the Emulate tab did not start the run")
        self.window.select_tab(self.ns)
        return True, ""

    def run_card(self, path):
        self.window.select_tab(self.ns)
        self.launch_card(path, select=True)

    def start(self):
        prepare, self._launch_prepare = self._launch_prepare, None
        if self._starting or self._stopping:
            self._refuse_start("the emulator is already starting or stopping")
            return
        if self._launched():
            # the watch.sh this tab started is still up: a second one would
            # be a second launcher (must survive #0)
            self._refuse_start("the emulator is already running: stop it "
                               "first, then try again.")
            return
        if not rig.rig_available():
            self._refuse_start("the emulator is not set up on this PC; use "
                               "Check setup on the Emulate tab")
            return
        self._cancel_prepare = False
        self._starting = True
        self._run_label(False, True)
        self._set("state", "Starting…")
        src = self._source_env()
        if src is None:
            self._starting = False
            self._run_label(False, False)
            self._set("state", "Not running")
            self._refuse_start(self.get("hint") or "")
            return
        env = self._launch_env(src)
        ovr_request = self._overrides_wanted()
        ovr_selector = bool(self._select_var.get())
        prepare_card = self._card()
        self._select_probe_kick()
        self._launch_serial += 1
        serial = self._launch_serial

        def over():
            if not self._last_up:
                self._launch_over(serial)

        def down():
            self._set("state", "Not running")
            self._run_label(False, False)

        def run():
            if not no_rig():
                self._note_the_runtime_is_a_different_machine()
                self._reattach_data_disk()
            if sys.platform == "darwin" and not no_rig():
                state = self._docker_probe()
                if state != "ok":
                    self._log("[emulate] Docker is %s. The emulator runs in a "
                              "container on macOS, so it cannot start without "
                              "it." % {
                                  "absent": "not installed",
                                  "engineless": "installed, but nothing on "
                                                "this Mac can run a container",
                              }.get(state, "not running"))
                    self._starting = False
                    self._post(lambda: (self._docker_apply(state), down()))
                    if prepare is not None:
                        over()
                    return
            if ovr_request is not None:
                extra = self._prepare_overrides(*ovr_request,
                                                selector=ovr_selector)
                if extra is None:
                    self._starting = False
                    self._post(down)
                    if prepare is not None:
                        over()
                    return
                env.extend(extra)
            if prepare is not None:
                self._preparing = "Preparing your modes…"
                self._preparing_kind = "modes"
                self._post(self._repaint_preparing)
                try:
                    more = prepare(prepare_card)
                except Exception as exc:                 # noqa: BLE001
                    self._log("[emulate] the run could not be prepared: %s"
                              % exc)
                    more = None
                finally:
                    self._preparing = None
                    self._preparing_pct = None
                    self._preparing_kind = None
                    self._post(self._paint_run_btn)
                if more is None:
                    reason = getattr(prepare, "last_reason", "")
                    self.prepare_refuse(
                        reason or "the run was not prepared (the Modes tab "
                                  "says why)",
                        say=not reason)
                    self._starting = False
                    self._post(down)
                    return
                if self._cancel_prepare:
                    self.prepare_refuse("the preparation was cancelled; "
                                        "nothing was started")
                    self._starting = False
                    self._post(down)
                    over()
                    return
                env.extend(more)
            self.last_refusal = ""
            cmd = self._watch_cmd(env)
            self._log("[emulate] %s" % " ".join(str(c) for c in cmd))
            try:
                self._proc = self._popen(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT)
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] failed to start: %s" % exc)
                self._proc = None
                self._starting = False
                self._post(down)
                over()
                return
            self._starting = False
            self._started_here = True
            # Launched: the button keeps the disabled "Starting…" (as Tk's
            # did) until the rig's own answer turns it into "Stop emulator",
            # and that answer is asked for now rather than at the idle
            # cadence (10 s) - an enabled Start there was a second launcher.
            self._post(lambda: (self._run_label(False, True),
                                self._poll_soon()))
            try:
                for raw in self._proc.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    self._log("[emulate] " + line)
                    prog = rig.card_copy_progress(line)
                    if prog is not None and not self._stopping:
                        self._copying = prog
                        m = rig._CARD_COPY_RE.match(line)
                        self._copying_pct = int(m.group(4)) if m else None
                        self._post(self._push_copy, prog, self._copying_pct)
                    elif self._copying is not None and \
                            line.startswith("[card]"):
                        self._copying = None
                    fields = rig.playfield_launch(line)
                    if fields:
                        self._open_playfield(fields)
            except Exception:                            # noqa: BLE001
                pass
            finally:
                self._proc = None
                self._copying = None
                self._post(self._paint_run_btn)
                over()

        def guarded():
            try:
                run()
            except Exception as exc:                     # noqa: BLE001
                log.exception("emulate start")
                self._log("[emulate] failed to start: %s" % exc)
                self._proc = None
                self._preparing = None
                self._starting = False
                self._post(down)
                over()

        self._launch_accepted = prepare is not None
        self._thread(guarded)

    def _open_playfield(self, fields):
        if sys.platform != "win32":
            return
        if self._pf_proc is not None and self._pf_proc.poll() is None:
            return
        py = rig.windows_python()
        if not py:
            self._log("[emulate] the run asked PAD to open the playfield "
                      "window, and there is no Python here to open it with. "
                      "The game itself is unaffected.")
            return
        script = os.path.join(rig.rig_dir(), "playfield.py")
        cmd = [py, script, fields["game"]]
        if fields.get("savestates") == "1":
            cmd.append("--savestates")
        env = dict(os.environ)
        for key, name in (("root", "PAD_ROOT"), ("tables", "PAD_TABLES")):
            if fields.get(key):
                env[name] = fields[key]
        # PAD-204: the window's status bar moves this tab's volume / Mute
        env["PAD_AUDIO_CTL"] = audio_ctl_file()
        try:
            self._pf_proc = self._popen(cmd, env=env)
            self._log("[emulate] opened the virtual playfield window here — "
                      "this WSL cannot start Windows programs itself.")
        except Exception as exc:                         # noqa: BLE001
            self._pf_proc = None
            self._log("[emulate] could not open the playfield window: %s"
                      % exc)

    def _close_playfield(self, grace=8):
        proc, self._pf_proc = self._pf_proc, None
        if proc is None:
            return
        try:
            proc.wait(timeout=grace)
        except Exception:                                # noqa: BLE001
            try:
                proc.kill()
                self._log("[emulate] the playfield window did not close "
                          "itself; closed it here.")
            except Exception:                            # noqa: BLE001
                pass

    def stop(self):
        if self._stopping:
            return
        self._stopping = True
        self._launch_slot = None
        self._copying = None
        self._copying_pct = None
        self._run_label(True, True)
        self._set("state", "Stopping…")

        def run():
            needs_restart = False
            try:
                out = self._run(self._kill_cmd(), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=60)
                for line in out.stdout.decode("utf-8",
                                              "replace").splitlines():
                    self._log("[emulate] " + line)
                    if rig._NEEDS_WSL_RESTART in line:
                        needs_restart = True
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] stop failed: %s" % exc)
            proc = self._proc
            if proc is not None:
                try:
                    proc.wait(timeout=20)
                except Exception:                        # noqa: BLE001
                    try:
                        proc.kill()
                    except Exception:                    # noqa: BLE001
                        pass
            self._close_playfield()
            self._stopping = False
            if needs_restart and sys.platform == "win32":
                self._post(self._offer_wsl_restart)
            # the next poll re-reads the status (Stop is VERIFIED)
            self._post(self._poll_soon)

        self._thread(run)

    def _poll_soon(self):
        if self._poll_job is not None:
            self.ctx.loop.after_cancel(self._poll_job)
            self._poll_job = None
        self._schedule_poll(250)

    def _offer_wsl_restart(self):
        if self._resetting or self._stopped:
            return
        if not compat.messagebox.askyesno(
                "Stop emulator",
                "The emulator did not stop cleanly.\n\n"
                "Some of its processes are stuck in a way that cannot be "
                "fixed from inside WSL - Windows is holding on to processes "
                "that are already dead.  They will keep the emulator looking "
                "half-running and may block the next start.\n\n"
                "Restarting WSL clears them.  This closes EVERYTHING running "
                "in WSL, not just the emulator.  Nothing on disk is lost, "
                "and WSL starts again by itself the next time it is used.\n\n"
                "Restart WSL now?"):
            self.log("[emulate] leftovers kept; press Stop again for this "
                     "offer, or run `wsl --shutdown` yourself when ready")
            return
        self._restart_wsl("clearing stuck emulator processes")

    @rpc
    def restart_wsl(self):
        """“Restart WSL…” (Windows only)."""
        if sys.platform != "win32":
            return False
        if self._resetting or self._starting or self._stopping:
            return False
        if not rig.rig_available():
            return False
        if self._last_up:
            compat.messagebox.showinfo(
                "Restart WSL",
                "Stop the emulator first.\n\n"
                "This restarts WSL, which would kill the running game without "
                "letting it shut down cleanly.")
            return False
        if not compat.messagebox.askyesno(
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
            return False
        self._restart_wsl("rebuilding the audio path and window link",
                          pre_kill=True)
        return True

    @rpc
    def reset_windows(self):
        """“Reset windows”: forget where the game window and the virtual
        playfield were."""
        if self._winresetting or self._starting or self._stopping:
            return False
        if not rig.rig_available():
            return False
        if self._last_up:
            compat.messagebox.showinfo(
                "Reset windows",
                "Stop the emulator first.\n\n"
                "The emulator saves where its windows are as you move them, "
                "and again when it closes — so resetting now would be undone "
                "at the end of this run.")
            return False
        if not compat.messagebox.askyesno(
                "Reset windows",
                "Forget where the emulator windows were?\n\n"
                "The next time you start the emulator, the game window and "
                "the virtual playfield open at their default position and "
                "size.\n\n"
                "Use this when a window has ended up off the screen — after "
                "unplugging a second monitor, for example — and cannot be "
                "dragged back.\n\n"
                "Nothing else is affected: no save state, no setting, and no "
                "running game.\n\n"
                "Reset the window positions now?"):
            return False
        self._winresetting = True
        self.set(winreset_enabled=False)

        def run():
            try:
                out = self._run(self._cmd("winreset.sh"),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120)
                for line in out.stdout.decode("utf-8",
                                              "replace").splitlines():
                    if line.strip():
                        self._log("[emulate] " + line.strip())
                if out.returncode == 0:
                    msg = rig.forget_playfield_pos()
                    if msg:
                        self._log("[emulate] " + msg)
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] reset windows failed: %s" % exc)
            finally:
                self._winresetting = False
                self._post(self._paint_buttons)

        self._thread(run)
        return True

    def _restart_wsl(self, why, pre_kill=False):
        self._resetting = True
        self.set(fixaud_enabled=False)
        self._set("state", "Restarting WSL…")

        def run():
            try:
                if pre_kill:
                    self._run(self._kill_cmd(), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=60)
                self._log("[emulate] restarting WSL: %s" % why)
                out = self._run(["wsl.exe", "--shutdown"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120)
                for line in out.stdout.decode("utf-8",
                                              "replace").splitlines():
                    if line.strip():
                        self._log("[emulate] " + line)
                self._log("[emulate] WSL is down; it restarts by itself on "
                          "next use. Start the emulator again when ready.")
            except Exception as exc:                     # noqa: BLE001
                self._log("[emulate] WSL restart failed: %s" % exc)
            finally:
                self._resetting = False
                self._post(self._setup_after_restart)

        self._thread(run)

    def _setup_after_restart(self):
        self._paint_buttons()
        if self._stopped:
            return
        self.log("[emulate] checking what the restart left behind: the "
                 "kernel's 32-bit ARM handler only survives one on a distro "
                 "that boots systemd.")
        self._setup_restart_check = True
        self._setup_check()

    def shutdown_sync(self):
        """App quit: take the emulator down with the app (blocking,
        bounded), a terminal-started run too."""
        if not (self._proc is not None or self._last_up):
            self._close_playfield(grace=3)
            return
        if not rig.rig_available():
            self._close_playfield(grace=3)
            return
        self._stopped = True
        try:
            self._run(self._kill_cmd(), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, timeout=25)
        except Exception:                                # noqa: BLE001
            pass
        self._close_playfield(grace=3)

    # ------------------------------------------------------------------
    # the status poll
    # ------------------------------------------------------------------
    def _schedule_poll(self, ms=None):
        if self._stopped or no_rig():
            return
        if ms is None:
            if not self._polled_once:
                ms = 700
            else:
                ms = self.POLL_MS if self._last_up else self.POLL_IDLE_MS
        self._poll_job = self._after(ms, self._poll)

    def _poll(self):
        self._poll_job = None
        if self._stopped or no_rig():
            return
        if sys.platform == "darwin" and self._docker != "ok":
            self._docker_ticks += 1
            if self._docker_ticks % 5 == 1:
                self._docker_check()
            if self._docker is not None:
                self._polled_once = True
                self._schedule_poll()
                return
        if self._setup_busy:
            self._schedule_poll()
            return
        if not rig.rig_available():
            self._polled_once = True
            self._schedule_poll()
            return
        if self._poll_busy:
            self._schedule_poll()
            return
        self._poll_busy = True

        def run():
            try:
                out = self._run(self._cmd("status.sh"),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=20)
                text = out.stdout.decode("utf-8", "replace")
            except Exception:                            # noqa: BLE001
                text = ""
            info = rig.parse_status(text)
            try:
                rt = runtime.status()
            except Exception:                            # noqa: BLE001
                rt = None
            if self._stopped:
                self._poll_busy = False
                return

            def apply_and_release():
                self._poll_busy = False
                self._polled_once = True
                self._runtime_apply(rt)
                self._apply(info)
                self._follow_audio_ctl()
            self._post(apply_and_release)

        self._thread(run)
        self._schedule_poll()

    def _push_copy(self, text, pct):
        self._set("state", text)
        self.set(state_tip=rig._COPY_EXPLAIN)
        self._footer("copy", pct, text)

    def _paint_footer(self, info=None):
        info = info if info is not None else self._last_info
        preparing = self._preparing is not None and not self._stopping
        copying = self._copying is not None and not self._stopping
        if preparing:
            self._footer("copy", self._preparing_pct, self._preparing)
        elif copying:
            self._footer("copy", self._copying_pct, self._copying)
        elif info and info.get("running") == "1":
            st_label, _hint = rig.state_text(info)
            st = info.get("state")
            if st in ("attract", "running"):
                self._footer("run", None, st_label)
            elif st == "techalerts":
                self._footer("techalerts", None, st_label)
            else:
                self._footer("boot", None, st_label)
        else:
            self._footer("idle")

    def _paint_buttons(self):
        up = self._last_up
        busy = self._starting or self._stopping
        ok = rig.rig_available()
        self.set(fixaud_enabled=not (up or busy or self._resetting or not ok),
                 winreset_enabled=not (up or busy or self._winresetting
                                       or not ok))

    def _apply(self, info):
        try:
            self._apply_inner(info)
        except Exception:                                # noqa: BLE001
            log.exception("emulate status apply")

    def _apply_inner(self, info):
        self._last_info = info
        label, hint = rig.state_text(info)
        copying = self._copying is not None and not self._stopping
        preparing = self._preparing is not None and not self._stopping
        if preparing:
            label = self._preparing
        elif copying:
            label = self._copying
        self.set(state_tip=(self._preparing_explain() if preparing else
                            (rig._COPY_EXPLAIN if copying else hint)) or "")
        self._set("state", label)
        self._hint("")
        self._paint_footer(info)

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
                    pcm, drop, "" if drop == "0" else "   <-- dropping"))
        else:
            for k in ("cpu", "host", "audio"):
                self._set(k, "—")

        tok = info.get("saves_mtime")
        if tok is not None and tok != self._saves_token:
            self._saves_token = tok
            self.slots_refresh()
        if (self._launch_slot and not self._loading
                and info.get("running") == "1"):
            slot, self._launch_slot = self._launch_slot, None
            self._after(4000, self._slot_load, slot)

        busy = self._starting or self._stopping
        up = info.get("running") == "1" or procs != "0"
        if self._last_up and not up:
            self._vnc_opened = False
            self._started_here = False
            self._tell_run_ended(self._launch_serial)
        if (sys.platform == "darwin" and up and self._started_here
                and not self._vnc_opened):
            self._vnc_opened = True
            try:
                self._popen(["open", "vnc://:pinball@localhost:5900"])
                self.log("[emulate] opening the picture in Screen "
                         "Sharing (VNC password: pinball)")
            except Exception:                            # noqa: BLE001
                pass
        self._last_up = up
        self.set(up=up)
        # a watch.sh this tab launched counts as up for the ONE button, so a
        # poll sampled before the rig saw it cannot offer Start again
        self._run_label(up or self._launched(), busy)
        self._paint_buttons()


TAB = EmulateTab
