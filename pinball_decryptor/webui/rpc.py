"""The page's calls into Python: a registry of named methods.

A tab service marks its callable methods with :func:`rpc`; registering the
service publishes them as ``"<namespace>.<method>"``.  By default a call runs
on the UI loop (so it may touch app and window state, like a Tk button
handler); ``@rpc(loop=False)`` runs it on the HTTP thread instead, for pure
reads that must answer while a modal holds the loop (a folder listing for the
page's file browser, for one).
"""

import inspect
import logging
import traceback

log = logging.getLogger(__name__)


def rpc(fn=None, *, loop=True):
    """Mark a method as callable from the page."""
    def deco(f):
        f.__pad_rpc__ = {"loop": loop}
        return f
    if fn is not None:
        return deco(fn)
    return deco


class RpcError(Exception):
    """An error meant for the page: its message is shown as is."""


class Registry:
    def __init__(self, loop):
        self._loop = loop
        self._methods = {}      # name -> (fn, on_loop)

    def register(self, name, fn, on_loop=True):
        self._methods[name] = (fn, on_loop)

    def service(self, ns, obj):
        """Register every ``@rpc`` method of ``obj`` under ``ns``."""
        for attr, member in inspect.getmembers(obj):
            meta = getattr(member, "__pad_rpc__", None)
            if meta is None:
                continue
            self.register("%s.%s" % (ns, attr), member, meta["loop"])

    def names(self):
        return sorted(self._methods)

    def call(self, name, args=None, kwargs=None):
        entry = self._methods.get(name)
        if entry is None:
            raise RpcError("No such call: %s" % name)
        fn, on_loop = entry
        args = list(args or [])
        kwargs = dict(kwargs or {})
        if on_loop:
            return self._loop.call(lambda: fn(*args, **kwargs))
        return fn(*args, **kwargs)

    def dispatch(self, payload):
        """Run one call from the page; always returns a JSON-able dict."""
        name = payload.get("m") or ""
        try:
            result = self.call(name, payload.get("a"), payload.get("k"))
            return {"ok": True, "r": result}
        except RpcError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                      # noqa: BLE001
            text = traceback.format_exc()
            log.error("call %s failed:\n%s", name, text)
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                    "trace": text}
