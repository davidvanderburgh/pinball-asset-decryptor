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

    def log(self, text, level="info"):
        self.window.append_log(text, level)

    def toast(self, text, level="info"):
        self.window.toast(text, level)

    # -- hooks -----------------------------------------------------------
    def on_manufacturer(self, mfr):
        pass

    def on_show(self):
        pass

    def on_running(self, running, mode):
        pass

    def on_project(self, folder):
        pass

    def on_close(self):
        pass

    def on_field(self, key, value):
        """The page set ``key`` with no Var bound to it (plain state)."""
        self.set(**{key: value})
