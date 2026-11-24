"""The base every tab service builds on.

A tab service is the Python half of one tab: it owns that tab's state (a
store namespace the page renders), its callable methods (``@rpc``), the Tk
variables and methods the run logic in ``app.py`` reads off the window
(listed in ``exports``), and its reactions to the shell's events.

Contract (see docs/plans/web_ui.md, "Writing a tab"):

* ``ns``     - store + call namespace, lower case ("extract", "audio")
* ``key``    - the Tk tab's stable key ("Extract", "Replace Audio"); the
               shell gates the tab by capability with it, exactly as the Tk
               window's ``_configure_tab`` did
* ``label``  - the rail label; ``group`` - the rail group; ``icon`` - its icon
* ``exports`` - window attribute names this service answers for; the window
               looks them up on the service (``self.<name>``)

Hooks (all on the UI loop):
  on_manufacturer(mfr)   a manufacturer (or era) was applied
  on_show()              the tab became the selected one
  on_hide()              another tab became the selected one (PAD-1546)
  on_running(running, mode)  a run started or ended (set_running)
  on_project(folder)     the project folder changed
"""

from .. import compat
from ..rpc import rpc  # noqa: F401  (re-exported for tab modules)


class TabService:
    ns = ""
    key = ""
    label = ""
    group = ""
    icon = ""
    exports = ()

    def __init__(self, window):
        self.window = window
        self.ctx = window.ctx
        self.store = window.ctx.store
        self._vars = {}

    # -- the app ---------------------------------------------------------
    @property
    def app(self):
        return self.window.app

    @property
    def mfr(self):
        return self.window.current_mfr

    @property
    def caps(self):
        mfr = self.window.current_mfr
        return getattr(mfr, "capabilities", None)

    def cap(self, name, default=False):
        caps = self.caps
        return bool(getattr(caps, name, default)) if caps is not None \
            else default

    # -- state -----------------------------------------------------------
    def set(self, **values):
        return self.store.set(self.ns, **values)

    def get(self, key, default=None):
        return self.store.get(self.ns, key, default)

    def set_item(self, key, index, value):
        return self.store.set_item(self.ns, key, index, value)

    def patch_item(self, key, index, **fields):
        return self.store.patch_item(self.ns, key, index, **fields)

    def var(self, key, kind="str", value=None):
        """A Tk-variable look-alike mirrored at ``<ns>.<key>``; the page's
        edits of that key come back through its ``set`` (traces fire)."""
        cls = {"str": compat.StringVar, "bool": compat.BooleanVar,
               "int": compat.IntVar, "float": compat.DoubleVar}[kind]
        v = cls(value=value, store=self.store, ns=self.ns, key=key)
        self._vars[key] = v
        self.window.bind_var(self.ns, key, v)
        return v

    # PAD-1176 / PAD-1209 (PAD-1527: shared with the Video tab): choices kept
    # app-wide in settings.json
    def _pref(self, key, kind):
        """The value *key* was last set to (of type *kind*), this session
        or an earlier one; None when it never was."""
        app = self.app
        s = getattr(app, "_settings", None) if app is not None else None
        got = s.get(key) if isinstance(s, dict) else None
        if not isinstance(got, kind):
            got = getattr(self, "_prefs_local", {}).get(key)
        return got if isinstance(got, kind) else None

    def _remember_pref(self, key, value):
        """Keep *value* for *key* in settings.json (saved straight away, so
        it is there next session whatever way the app is closed)."""
        if not hasattr(self, "_prefs_local"):
            self._prefs_local = {}
        if self._prefs_local.get(key) == value and self._pref(
                key, type(value)) == value:
            return
        self._prefs_local[key] = value
        app = self.app
        if app is not None and isinstance(getattr(app, "_settings", None), dict):
            app._settings[key] = value
            try:
                app._save_settings()
            except Exception:                              # noqa: BLE001
                pass

    def log(self, text, level="info"):
        self.window.append_log(text, level)

    def toast(self, text, level="info"):
        self.window.toast(text, level)

    def shown(self):
        """True while this is the selected tab, the one on screen.  (``_visible``
        is the window's: the tab is on the rail for this manufacturer.)"""
        return self.store.get("shell", "tab") == self.ns

    # -- hooks -----------------------------------------------------------
    def on_manufacturer(self, mfr):
        pass

    def on_show(self):
        pass

    def on_hide(self):
        pass

    def on_running(self, running, mode):
        pass

    def on_project(self, folder):
        pass

    def on_close(self):
        pass

    def rail_needs(self):
        """What this tab needs before it can be used on this manufacturer:
        ``None`` for the page's own table (static/js/core/locks.js NEEDS),
        ``"none"``, ``"project"``, ``"extract"`` or ``"spike3key"`` to say
        otherwise."""
        return None

    def _spike3_era(self):
        """True on a Stern Spike 3 card, where everything needs the user's
        own OTP key (PAD-1090: rail_needs "spike3key")."""
        return getattr(self.mfr, "_era", None) == "spike3"

    def on_field(self, key, value):
        """The page set ``key`` with no Var bound to it (plain state)."""
        self.set(**{key: value})
