"""A module that imports itself on first use.

``np = lazy_module("numpy")`` reads like the real import at every call
site (``np.zeros(...)``), but numpy loads the first time an attribute is
asked for, not when the module naming it does.  numpy and PIL cost the UI
loop 65 to 130 ms at startup through the Modes tab's module chain
(PAD-797), for a user who may never open that tab.
"""

import importlib


class LazyModule:
    """Proxy for a module imported on first attribute access."""

    __slots__ = ("_name", "_mod")

    def __init__(self, name):
        self._name = name
        self._mod = None

    def __getattr__(self, attr):
        mod = self._mod
        if mod is None:
            mod = self._mod = importlib.import_module(self._name)
        return getattr(mod, attr)

    def __repr__(self):
        state = "loaded" if self._mod is not None else "not loaded"
        return "<LazyModule %s (%s)>" % (self._name, state)


def lazy_module(name):
    return LazyModule(name)
