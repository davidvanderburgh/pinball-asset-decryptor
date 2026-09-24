"""The web window: what the run logic (``app.App``) drives instead of Tk's
``MainWindow``.

It keeps the same method names ``app.py`` calls (``append_log``,
``set_running``, ``set_progress``, ``apply_manufacturer``...) and answers the
Tk variables ``app.py`` reads (``extract_input_var``...) through the tab
services, each of which lists the attributes it provides in ``exports``.

The shell's own state lives in the store namespace ``"shell"``:

  view        "picker" | "mfr"
  mfrs        the picker's manufacturers
  mfr         the current manufacturer (key, display, eras, era, labels)
  tabs        the rail: [{ns, key, label, group, icon, visible}]
  tab         the selected tab's ns
  running     a run is in flight; run_mode is its mode
  footer      {mode, phases, index, pct, busy, status, started}
  prereqs     [{name, state, message, hint}]
  banners, toasts, title, theme, zoom, version, project ...
"""

import collections
import itertools
import logging
import os
import time

from .. import __version__
from ..core import session_log
from . import compat
from .rpc import RpcError, rpc
from .tabs import load_tab_classes

log = logging.getLogger(__name__)

LOG_KEEP = 5000

#: Emulate / multi-boot ladders, as the Tk window had them.
EMULATE_PHASES = ("Copy card", "Boot", "Node boards", "Ready")
MULTIBOOT_PHASES = ("Media", "Copy", "Inject", "Verify")

#: Which chip row a tab owns (Tk's PHASE_ROW_BY_TAB): None = no run row.
PHASE_ROW_BY_KEY = {
    "Extract": "extract", "Compare": "extract", "Mod Pack": "extract",
    "Write": "write", "Modes": "write",
    "Emulate": "emulate", "Emulate JJP": "emulate",
    "Emulate Spike1": "emulate",
    "Multi-boot": "multiboot",
    "Replace Audio": None, "Replace Video": None,
    "Replace Images": None, "Replace Text": None,
    "Partition Explorer": None, "Default Settings": None,
}

def _system_theme():
    """No saved theme: follow the OS, as the Tk window did."""
    try:
        from pinball_decryptor.webui.theme import detect_system_theme
        return detect_system_theme()
    except Exception:                                   # noqa: BLE001
        return "dark"


_EMULATE_KINDS = {"copy": (0, None), "boot": (1, 55),
                  "techalerts": (2, 80), "run": (4, 100)}


class WebWindow:
    def __init__(self, ctx, app, manufacturers, callbacks):
        self.ctx = ctx
        self.app = app
        self.cb = dict(callbacks)
        self.manufacturers = list(manufacturers)
        self.current_mfr = None
        self._vars = {}                     # (ns, key) -> Var
        self._running = False
        self._run_mode = None
        self._borrowed_row = None
        self._start_time = None
        self._timer = None
        self._log = collections.defaultdict(
            lambda: collections.deque(maxlen=LOG_KEEP))
        self._log_ids = itertools.count(1)
        self._log_line_run = 0
        self._keyed = {}                    # (run, key) -> line id
        self._pending_log = collections.deque(maxlen=LOG_KEEP)
        self._toast_ids = itertools.count(1)
        self._last_browse_dirs = {}
        self._path_history = {}
        self._phases = {"extract": (), "write": (),
                        "emulate": EMULATE_PHASES,
                        "multiboot": MULTIBOOT_PHASES}
        self._phase_index = {"extract": -1, "write": -1, "emulate": -1,
                             "multiboot": -1}
        self.ctx.window = self

        # the tab services, in rail order
        self.tabs = []
        self._by_ns = {}
        self._exports = {}
        for cls in load_tab_classes():
            try:
                svc = cls(self)
            except Exception:                        # noqa: BLE001
                log.exception("tab %s failed to start", cls.__name__)
                continue
            self.tabs.append(svc)
            self._by_ns[svc.ns] = svc
            for name in svc.exports:
                self._exports.setdefault(name, svc)
            ctx.registry.service(svc.ns, svc)
        ctx.registry.service("ui", self)

        self.ctx.store.set(
            "shell", view="picker", version=__version__,
            mfrs=[self._mfr_card(m) for m in self.manufacturers],
            mfr=None, tabs=self._rail(), tab=None, running=False,
            run_mode=None, footer=self._footer_idle("extract"),
            prereqs=[], banners=[], toasts=[], title="",
            theme=self.cb.get("initial_theme") or _system_theme(),
            zoom=1.0, back_enabled=True)

    # ------------------------------------------------------------------
    # attribute delegation to the tab services
    # ------------------------------------------------------------------
    def __getattr__(self, name):
        exports = self.__dict__.get("_exports")
        if exports is not None:
            svc = exports.get(name)
            if svc is not None:
                return getattr(svc, name)
            # A Tk variable no tab provides yet: a stand-in, RECORDED, so a
            # missing port shows up in tests/test_webui_contract.py instead
            # of crashing the run logic.  Never relied on by a finished tab.
            if name.endswith("_var"):
                missing = self.__dict__.setdefault("missing_exports", {})
                var = missing.get(name)
                if var is None:
                    var = compat.StringVar()
                    missing[name] = var
                    log.warning("window.%s is not provided by any tab", name)
                return var
        raise AttributeError(name)

    def service(self, ns):
        return self._by_ns.get(ns)

    def bind_var(self, ns, key, var):
        self._vars[(ns, key)] = var

    # ------------------------------------------------------------------
    # the page's generic calls
    # ------------------------------------------------------------------
    @rpc
    def set(self, ns, key, value):
        """The page changed a field.  A bound Tk-style var is set (its traces
        fire, as a Tk entry's would); otherwise the tab's ``on_field``."""
        var = self._vars.get((ns, key))
        if var is not None:
            var.set(value)
            return True
        svc = self._by_ns.get(ns)
        if svc is not None:
            svc.on_field(key, value)
            return True
        self.ctx.store.set(ns, **{key: value})
        return True

    #: The window itself tells every service about a tab change (Tk's
    #: _on_tab_changed); services need not wrap select_tab.
    fans_tab_changes = True

    @rpc
    def select_tab(self, ns):
        svc = self._by_ns.get(ns)
        if svc is None:
            raise RpcError("No tab %s" % ns)
        prev_key = self.current_tab_key()
        self.ctx.store.set("shell", tab=ns)
        # Tk's _on_tab_changed: no preview keeps playing behind another tab,
        # and a footer an emulator or the multi-boot panel owned goes back
        # to "Ready" when their tab is left.
        self.stop_all_preview_playback()
        if not self._running:
            emu = ("Emulate", "Emulate JJP", "Emulate Spike1")
            if ((prev_key in emu and svc.key not in emu)
                    or (prev_key == "Multi-boot" and svc.key != "Multi-boot")):
                self._set_footer(pct=0, busy=False, index=-1,
                                 status="Ready")
        if not self._running and self._borrowed_row is None:
            self._show_row_for_tab()
        for other in self.tabs:
            fn = getattr(type(other), "on_tab_changed", None)
            if fn is not None:
                try:
                    other.on_tab_changed(ns)
                except Exception:                    # noqa: BLE001
                    log.exception("on_tab_changed %s", other.ns)
        try:
            svc.on_show()
        except Exception:                            # noqa: BLE001
            log.exception("on_show %s", ns)
            self.append_log("The %s tab failed to refresh; the details are "
                            "in the session log." % svc.label, "error")
        return True

    @rpc
    def pick_manufacturer(self, key):
        for m in self.manufacturers:
            if m.key == key:
                cb = self.cb.get("on_manufacturer_change")
                if cb is not None:
                    cb(m)
                return True
        raise RpcError("Unknown manufacturer %s" % key)

    @rpc
    def back_to_picker(self):
        if self._running:
            return False
        cb = self.cb.get("on_back")
        if cb is not None:
            cb()
        else:
            self.show_picker()
        return True

    @rpc
    def set_era(self, era_key):
        mfr = self.current_mfr
        if (mfr is None or self._running or not hasattr(mfr, "set_era")
                or getattr(mfr, "current_era", "") == era_key):
            return False
        mfr.set_era(era_key)
        var = self._vars.get(("extract", "input"))
        if var is not None:
            var.set("")
        self.apply_manufacturer(mfr, reset_era=False)
        cb = self.cb.get("on_recheck_prereqs")
        if cb is not None:
            cb()
        return True

    @rpc
    def dismiss_toast(self, tid):
        toasts = [t for t in (self.ctx.store.get("shell", "toasts") or [])
                  if t.get("id") != tid]
        self.ctx.store.set("shell", toasts=toasts)
        return True

    @rpc
    def log_history(self):
        key = self.current_mfr.key if self.current_mfr else ""
        return list(self._log.get(key, ()))

    @rpc
    def cancel(self):
        """The status bar's Cancel: the run logic's one cancel (it cancels
        the running job and every queued follow-up)."""
        fn = self.cb.get("on_extract_cancel") or self.cb.get("on_write_cancel")
        if fn is not None and self._running:
            fn()
            return True
        return False

    @rpc
    def set_theme(self, theme):
        theme = theme if theme in ("dark", "light", "system") else "dark"
        self._current_theme = theme
        self.ctx.store.set("shell", theme=theme)
        fn = self.cb.get("on_theme_change")
        if fn is not None:
            fn(theme)
        return True

    @rpc
    def open_link(self, url):
        from ..core import desktop
        try:
            desktop.open_url(url)
        except Exception:                            # noqa: BLE001
            self.ctx.bus.publish("open_url", url=url)
        return True

    #: id -> fn(window); the shell's settings and help menus call these.
    #: A settings service adds its own (see tabs/shellmenus.py).
    settings_actions = {}

    @rpc
    def settings_action(self, action_id, *args):
        fn = self.settings_actions.get(action_id)
        if fn is None:
            if action_id == "check_updates" and self.cb.get(
                    "on_check_updates"):
                return self.cb["on_check_updates"]()
            raise RpcError("That menu item is not available yet.")
        return fn(self, *args)

    #: banner id -> fn(window, action_id)
    banner_handlers = {}

    @rpc
    def banner_action(self, banner_id, action_id):
        fn = self.banner_handlers.get(banner_id)
        if fn is not None:
            return fn(self, action_id)
        if action_id == "dismiss":
            self.set_banner(banner_id, None)
        return True

    @rpc
    def call_back(self, name, *args):
        """Run one of the constructor callbacks (the ``on_*`` the run logic
        handed the window) by name: the project and settings menus."""
        fn = self.cb.get(name)
        if fn is None:
            raise RpcError("No action %s" % name)
        return fn(*args)

    # ------------------------------------------------------------------
    # picker / manufacturer
    # ------------------------------------------------------------------
    @staticmethod
    def _mfr_card(m):
        games = []
        for g in getattr(m, "games", ()) or ():
            games.append({"key": g.key, "display": g.display,
                          "supported": bool(getattr(g, "supported", True)),
                          "reason": getattr(g, "unsupported_reason", "")})
        return {"key": m.key, "display": m.display,
                "tagline": getattr(m, "picker_tagline", "") or "",
                "badge": getattr(m, "picker_badge", "") or "",
                "games": games}

    def _rail(self):
        rail = []
        for svc in self.tabs:
            rail.append({"ns": svc.ns, "key": svc.key, "label": svc.label,
                         "group": svc.group, "icon": svc.icon,
                         "visible": bool(getattr(svc, "_visible", False)),
                         "badge": getattr(svc, "_badge", None)})
        return rail

    def refresh_rail(self):
        self.ctx.store.set("shell", tabs=self._rail())

    def set_tab_badge(self, ns, badge):
        svc = self._by_ns.get(ns)
        if svc is None:
            return
        if getattr(svc, "_badge", None) != badge:
            svc._badge = badge
            self.refresh_rail()

    def show_picker(self):
        self.ctx.store.set("shell", view="picker")

    def show_mfr_view(self):
        self.ctx.store.set("shell", view="mfr")

    def tab_visible(self, key):
        for svc in self.tabs:
            if svc.key == key:
                return bool(getattr(svc, "_visible", False))
        return False

    _tab_visible = tab_visible

    def _gate(self, mfr):
        caps = mfr.capabilities
        g = lambda name: bool(getattr(caps, name, False))   # noqa: E731
        gates = {
            "Extract": g("extract") or g("capture"),
            "Replace Audio": g("replace_audio"),
            "Replace Video": g("replace_video"),
            "Replace Images": g("replace_image"),
            "Replace Text": g("replace_text"),
            "Write": g("write"),
            "Mod Pack": g("modpack"),
            "Partition Explorer": g("partition_explorer"),
            "Default Settings": g("settings_editor"),
            "Compare": g("compare"),
            "Emulate": g("emulate"),
            "Emulate JJP": g("emulate_jjp"),
            "Emulate Spike1": g("emulate_spike1"),
            "Multi-boot": g("multiboot"),
            "Modes": self.modes_preview_on(mfr),
        }
        return gates

    def modes_preview_on(self, mfr=None):
        mfr = mfr if mfr is not None else self.current_mfr
        if mfr is None or not getattr(mfr.capabilities, "modes", False):
            return False
        from ..core import preview
        return preview.enabled("modes")

    _modes_preview_on = modes_preview_on

    def _mfr_state(self, mfr):
        eras = []
        for entry in tuple(getattr(mfr, "eras", ()) or ()):
            eras.append({"key": entry[0], "label": entry[1],
                         "flag": entry[2] if len(entry) > 2 else None})
        noun = getattr(mfr, "extract_input_label", None)
        return {"key": mfr.key, "display": mfr.display, "eras": eras,
                "era": getattr(mfr, "current_era", "") or "",
                "input_noun": noun or "",
                "iso_label": getattr(mfr, "extract_iso_label", "") or "",
                "ssd_label": getattr(mfr, "extract_ssd_label", "") or ""}

    def apply_manufacturer(self, mfr, reset_era=True):
        self.current_mfr = mfr
        if reset_era and hasattr(mfr, "set_era"):
            mfr.set_era("")
        self._phases["extract"] = tuple(mfr.extract_phases)
        self._phases["write"] = tuple(mfr.write_phases)
        gates = self._gate(mfr)
        for svc in self.tabs:
            svc._visible = bool(gates.get(svc.key, False))
        self.ctx.store.set("shell", mfr=self._mfr_state(mfr))
        self.reset_prereqs(mfr.prerequisites)
        self.show_mfr_view()
        # flush lines logged while the picker showed
        while self._pending_log:
            entry = self._pending_log.popleft()
            self._store_line(mfr.key, entry)
        for svc in self.tabs:
            try:
                svc.on_manufacturer(mfr)
            except Exception:                        # noqa: BLE001
                log.exception("on_manufacturer %s", svc.ns)
                session_log.append("tab %s on_manufacturer failed" % svc.ns)
        self.refresh_rail()
        self._ensure_visible_selection()
        self.ctx.bus.publish("log_reset", mfr=mfr.key)
        self._show_row_for_tab()

    def _ensure_visible_selection(self):
        cur = self.ctx.store.get("shell", "tab")
        svc = self._by_ns.get(cur) if cur else None
        if svc is not None and getattr(svc, "_visible", False):
            return
        for svc in self.tabs:
            if getattr(svc, "_visible", False):
                self.select_tab(svc.ns)
                return
        self.ctx.store.set("shell", tab=None)

    def current_tab_key(self):
        ns = self.ctx.store.get("shell", "tab")
        svc = self._by_ns.get(ns) if ns else None
        return svc.key if svc is not None else ""

    _current_tab_key = current_tab_key

    # ------------------------------------------------------------------
    # prerequisites
    # ------------------------------------------------------------------
    def reset_prereqs(self, prereqs):
        rows = []
        for p in prereqs or ():
            rows.append({"name": p.name, "state": "checking",
                         "message": "", "hint": "",
                         "reason": getattr(p, "reason", "") or ""})
        self.ctx.store.set("shell", prereqs=rows)

    def set_prereq_result(self, name, ok, message, install_hint=None):
        rows = self.ctx.store.get("shell", "prereqs") or []
        for row in rows:
            if row["name"] == name:
                row["state"] = "ok" if ok else "missing"
                row["message"] = message or ""
                row["hint"] = install_hint or ""
        self.ctx.store.set("shell", prereqs=rows)

    # ------------------------------------------------------------------
    # log
    # ------------------------------------------------------------------
    def _store_line(self, mfr_key, entry):
        self._log[mfr_key].append(entry)
        self.ctx.bus.publish("log", mfr=mfr_key, line=entry)

    def append_log(self, text, level="info"):
        text = session_log.clean_line(str(text))
        session_log.append(text, level)
        entry = {"id": next(self._log_ids), "ts": time.strftime("%H:%M:%S"),
                 "text": text, "level": level or "info"}
        if self.current_mfr is None:
            self._pending_log.append(entry)
            return
        self._store_line(self.current_mfr.key, entry)

    def append_log_link(self, text, url):
        session_log.append("%s (%s)" % (text, url))
        entry = {"id": next(self._log_ids), "ts": time.strftime("%H:%M:%S"),
                 "text": str(text), "level": "link", "url": url}
        if self.current_mfr is None:
            self._pending_log.append(entry)
            return
        self._store_line(self.current_mfr.key, entry)

    def update_log_line(self, key, text, level="info"):
        if self.current_mfr is None:
            return
        mkey = self.current_mfr.key
        lid = self._keyed.get((self._log_line_run, key))
        text = session_log.clean_line(str(text))
        if lid is None:
            lid = next(self._log_ids)
            self._keyed[(self._log_line_run, key)] = lid
            entry = {"id": lid, "ts": time.strftime("%H:%M:%S"),
                     "text": text, "level": level or "info"}
            self._store_line(mkey, entry)
            return
        for entry in self._log[mkey]:
            if entry["id"] == lid:
                entry["text"] = text
                entry["level"] = level or "info"
                break
        self.ctx.bus.publish("log_update", mfr=mkey, id=lid, text=text,
                             level=level or "info")

    # ------------------------------------------------------------------
    # toasts / banners
    # ------------------------------------------------------------------
    def toast(self, text, level="info", ms=6000):
        toasts = list(self.ctx.store.get("shell", "toasts") or [])
        tid = "t%d" % next(self._toast_ids)
        toasts.append({"id": tid, "text": str(text), "level": level,
                       "ms": ms})
        self.ctx.store.set("shell", toasts=toasts[-4:])
        return tid

    def set_banner(self, bid, banner):
        banners = [b for b in (self.ctx.store.get("shell", "banners") or [])
                   if b.get("id") != bid]
        if banner is not None:
            banner = dict(banner)
            banner["id"] = bid
            banners.append(banner)
        self.ctx.store.set("shell", banners=banners)

    # ------------------------------------------------------------------
    # footer: phases, progress, status, running
    # ------------------------------------------------------------------
    def _footer_idle(self, mode):
        return {"mode": mode, "phases": list(self._phases.get(mode) or ()),
                "index": -1, "pct": None, "busy": False,
                "status": "Ready", "started": None}

    def _footer(self):
        return dict(self.ctx.store.get("shell", "footer") or {})

    def _set_footer(self, **kw):
        f = self._footer()
        f.update(kw)
        self.ctx.store.set("shell", footer=f)

    def _row_for_tab(self):
        return PHASE_ROW_BY_KEY.get(self.current_tab_key(), "extract")

    _phase_row_for_tab = _row_for_tab

    def _show_row_for_tab(self):
        mode = self._row_for_tab()
        self.show_phase_row(mode or "extract")
        if mode is None:
            self._set_footer(phases=[])

    def show_phase_row(self, mode, borrow=False):
        if borrow:
            self._borrowed_row = mode
        self._set_footer(mode=mode,
                         phases=list(self._phases.get(mode) or ()),
                         index=self._phase_index.get(mode, -1))

    def set_phase(self, index, mode="extract"):
        self._phase_index[mode] = index
        f = self._footer()
        if f.get("mode") == mode:
            self._set_footer(index=index)

    def reset_steps(self, mode="extract"):
        self._phase_index[mode] = -1
        f = self._footer()
        if f.get("mode") == mode:
            self._set_footer(index=-1, pct=0 if not self._running else None)

    def _rebuild_phase_steps(self, extract_phases, write_phases):
        self._phases["extract"] = tuple(extract_phases)
        self._phases["write"] = tuple(write_phases)
        f = self._footer()
        if f.get("mode") in ("extract", "write"):
            self._set_footer(phases=list(self._phases[f["mode"]]))

    def set_write_phases(self, phases):
        if not phases:
            return
        self._rebuild_phase_steps(self._phases["extract"], phases)
        self.reset_steps(mode="write")

    def show_chained_phases(self, phases):
        if not phases:
            return
        self._rebuild_phase_steps(phases, self._phases["write"])
        self.reset_steps(mode="extract")

    def set_progress(self, current, total, desc="", mode="extract"):
        if total and total > 0:
            pct = max(0, min(100, int(100 * current / total)))
            self._set_footer(pct=pct, busy=False)
        else:
            self._set_footer(pct=None, busy=True)
        if desc:
            self.set_status(desc)

    def set_status(self, text):
        self._set_footer(status=str(text))

    def set_cancelling(self):
        self.ctx.store.set("shell", cancelling=True)
        self.set_status("Cancelling...")

    def set_running(self, running, mode="extract"):
        self._running = bool(running)
        self._run_mode = mode if running else None
        if running:
            self._log_line_run += 1
            self._start_time = time.time()
            self.ctx.store.set("shell", running=True, run_mode=mode,
                               cancelling=False, back_enabled=False)
            self._set_footer(status="Starting…", busy=True, pct=None,
                             started=self._start_time)
        else:
            self._start_time = None
            self._borrowed_row = None
            self.ctx.store.set("shell", running=False, run_mode=None,
                               cancelling=False, back_enabled=True)
            self._set_footer(busy=False, started=None)
            self._show_row_for_tab()
        for svc in self.tabs:
            try:
                svc.on_running(self._running, mode)
            except Exception:                        # noqa: BLE001
                log.exception("on_running %s", svc.ns)

    def folder_staged(self, folder):
        """Tell the Replace tabs that their picks were just written over
        the files in *folder* by something that is not a build (Emulate's
        Start): a preview drawn before still names the slot's own file, which
        now holds the replacement, under "Original" (PAD-209).  The Replace
        tabs' re-diff after a revert is the same job: it re-reads which slots
        have an ``.orig`` snapshot and redraws the open preview from it.
        Not the Write tab: its own refresh logs itself as "after Revert all
        changes".  Call on the loop thread."""
        for ns in ("images", "video", "audio"):
            svc = self._by_ns.get(ns)
            if svc is None or not hasattr(svc, "refresh_after_revert"):
                continue
            try:
                svc.refresh_after_revert()
            except Exception:                        # noqa: BLE001
                log.exception("%s.refresh_after_revert", ns)

    def _is_running(self):
        return self._running

    is_running = _is_running

    def set_back_enabled(self, enabled):
        self.ctx.store.set("shell", back_enabled=bool(enabled))

    def set_emulate_progress(self, kind, pct=None, text="", tab=None):
        if self._running:
            return
        key = self.current_tab_key()
        if key not in ("Emulate", "Emulate JJP", "Emulate Spike1"):
            return
        if tab is not None and key != tab:
            return
        if kind in _EMULATE_KINDS:
            index, value = _EMULATE_KINDS[kind]
            if kind == "copy":
                value = int((pct or 0) * 0.4)
            self._phase_index["emulate"] = index
            self._set_footer(mode="emulate",
                             phases=list(self._phases["emulate"]),
                             index=index, pct=value, busy=False)
        else:
            self._phase_index["emulate"] = -1
            self._set_footer(mode="emulate",
                             phases=list(self._phases["emulate"]),
                             index=-1, pct=0, busy=False)
        if text:
            self.set_status(text)
        elif kind == "idle":
            self.set_status("Ready")

    def set_emulate_phases(self, phases):
        self._phases["emulate"] = tuple(phases)
        f = self._footer()
        if f.get("mode") == "emulate":
            self._set_footer(phases=list(phases))

    def set_multiboot_phase(self, index, total=None, status=None):
        n = len(self._phases["multiboot"])
        if index is None:
            self._phase_index["multiboot"] = -1
            self._set_footer(mode="multiboot",
                             phases=list(self._phases["multiboot"]),
                             index=-1, pct=0)
        elif index < 0:
            self._phase_index["multiboot"] = n
            self._set_footer(mode="multiboot",
                             phases=list(self._phases["multiboot"]),
                             index=n, pct=100)
        else:
            span = max(1, total or n)
            i = min(int(index), n - 1)
            self._phase_index["multiboot"] = i
            self._set_footer(mode="multiboot",
                             phases=list(self._phases["multiboot"]),
                             index=i, pct=min(100, int(100.0 * index / span)))
        if status:
            self.set_status(status)

    @property
    def _start_time_(self):                      # pragma: no cover - alias
        return self._start_time

    # ------------------------------------------------------------------
    # browse folders / path history (shared by every tab)
    # ------------------------------------------------------------------
    def last_browse_dir(self, key):
        path = self._last_browse_dirs.get(key) or ""
        return path if path and os.path.isdir(path) else ""

    def remember_browse_dir(self, key, path):
        if not path:
            return
        d = path if os.path.isdir(path) else os.path.dirname(path)
        if d and os.path.isdir(d):
            self._last_browse_dirs[key] = d

    def set_path_history(self, history):
        self._path_history = dict(history or {})
        self.ctx.store.set("shell", path_history=self._path_history)

    def path_history(self, field):
        return list(self._path_history.get(field) or [])

    # ------------------------------------------------------------------
    # asking the page (used by tab services)
    # ------------------------------------------------------------------
    def ask_open(self, key, title, filetypes=None, multiple=False,
                 initialdir=None):
        start = initialdir or self.last_browse_dir(key)
        fn = (compat.filedialog.askopenfilenames if multiple
              else compat.filedialog.askopenfilename)
        path = fn(title=title, initialdir=start, filetypes=filetypes or [])
        if path:
            self.remember_browse_dir(
                key, path[0] if isinstance(path, tuple) else path)
        return path

    def ask_folder(self, key, title, initialdir=None):
        path = compat.filedialog.askdirectory(
            title=title, initialdir=initialdir or self.last_browse_dir(key))
        if path:
            self.remember_browse_dir(key, path)
        return path

    def ask_save(self, key, title, initialfile="", filetypes=None,
                 defaultextension=""):
        path = compat.filedialog.asksaveasfilename(
            title=title, initialdir=self.last_browse_dir(key),
            initialfile=initialfile, filetypes=filetypes or [],
            defaultextension=defaultextension)
        if path:
            self.remember_browse_dir(key, path)
        return path

    # ------------------------------------------------------------------
    # cross-tab calls the run logic makes: fanned out to every tab that
    # answers them (a tab defines the same-named method on its service)
    # ------------------------------------------------------------------
    def _fan(self, name, *args, **kw):
        results = []
        for svc in self.tabs:
            fn = getattr(type(svc), name, None)
            if fn is None:
                continue
            try:
                results.append(getattr(svc, name)(*args, **kw))
            except Exception:                        # noqa: BLE001
                log.exception("%s.%s", svc.ns, name)
        return results

    def invalidate_asset_scans(self, rescan_visible=True):
        self._fan("invalidate_asset_scans", rescan_visible)

    def reload_assets_tabs(self):
        self._fan("reload_assets_tabs")

    def stop_all_preview_playback(self):
        self._fan("stop_all_preview_playback")

    def emulate_shutdown(self):
        self._fan("emulate_shutdown")

    def refresh_after_revert(self):
        self._fan("refresh_after_revert")

    def clear_replace_assignments(self, assets_dir):
        self._fan("clear_replace_assignments", assets_dir)

    def begin_revert_view(self):
        self._fan("begin_revert_view")

    def acknowledge_macos_fda(self):
        # Extract and Write both show the Full Disk Access panel
        self._fan("acknowledge_macos_fda")

    def replacement_folder_mismatches(self, assets_dir):
        out = []
        for part in self._fan("replacement_folder_mismatches", assets_dir):
            out.extend(part or [])
        return out

    # Tk notebook stand-in: app.py selects the Extract tab with
    # ``window._notebook.select(window._tab_extract)``.
    _tab_extract = "extract"

    class _Notebook:
        def __init__(self, win):
            self._win = win

        def select(self, ns=None):
            if ns is None:
                return self._win.ctx.store.get("shell", "tab")
            self._win.select_tab(ns)
            return None

    @property
    def _notebook(self):
        return WebWindow._Notebook(self)

    def ask_with_details(self, title, message, rows, details_label,
                         details_columns=("File", "Why")):
        """A Yes/No question with a table of details the user can open."""
        answer = self.ctx.dialogs.ask({
            "kind": "details", "icon": "question", "title": title or "",
            "message": str(message or ""),
            "rows": [list(map(str, r)) for r in (rows or [])],
            "details_label": details_label or "Details",
            "columns": list(details_columns or ()),
            "buttons": [{"id": "yes", "label": "Yes", "style": "primary"},
                        {"id": "no", "label": "No"}],
        })
        return answer == "yes"

    def _initialdir_for(self, *values):
        for v in values:
            v = (v or "").strip() if isinstance(v, str) else ""
            if not v:
                continue
            if os.path.isdir(v):
                return v
            d = os.path.dirname(v)
            if d and os.path.isdir(d):
                return d
        return ""

    # ------------------------------------------------------------------
    # closing
    # ------------------------------------------------------------------
    def close(self):
        for svc in self.tabs:
            try:
                svc.on_close()
            except Exception:                        # noqa: BLE001
                log.exception("on_close %s", svc.ns)
