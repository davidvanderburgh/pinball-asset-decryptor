"""The web UI's answers to what the run logic asks of its window toolkit.

``app.py`` (the run logic) was written against Tk and still talks in its
shapes: a ``root`` (``after`` timers, the title), message boxes, file
pickers and variables (``StringVar.get()/set()``, ``trace_add``).  This
module provides each of them, backed by the page:

* :class:`Root`   - ``after``/``after_cancel``/``title``... on the UI loop;
* :data:`messagebox` - the page's modal questions;
* :data:`filedialog` - native pickers (or the page's own browser);
* :data:`simpledialog` - a one-line answer;
* :class:`StringVar` & co. - values with Tk's trace API, optionally mirrored
  into a store namespace so the page shows them and can set them.

``app.py`` imports :data:`messagebox` and :data:`filedialog` from here;
:func:`install` binds them to a live context.
"""

import itertools
import threading
import types

_ctx = None


def install(ctx):
    """Bind the dialogs to ``ctx`` (loop, store, dialogs, host).
    :func:`uninstall` undoes it."""
    global _ctx
    _ctx = ctx


def uninstall():
    """Unbind (tests, and a second install)."""
    global _ctx
    _ctx = None


def ctx():
    if _ctx is None:
        raise RuntimeError("the web UI context is not installed")
    return _ctx


# ----------------------------------------------------------------------
# messagebox
# ----------------------------------------------------------------------
_OK = [{"id": "ok", "label": "OK", "style": "primary"}]
_YES_NO = [{"id": "yes", "label": "Yes", "style": "primary"},
           {"id": "no", "label": "No"}]
_YES_NO_CANCEL = [{"id": "yes", "label": "Yes", "style": "primary"},
                  {"id": "no", "label": "No"},
                  {"id": "cancel", "label": "Cancel"}]
_OK_CANCEL = [{"id": "ok", "label": "OK", "style": "primary"},
              {"id": "cancel", "label": "Cancel"}]
_RETRY_CANCEL = [{"id": "retry", "label": "Retry", "style": "primary"},
                 {"id": "cancel", "label": "Cancel"}]


def _box(default_icon, buttons, title, message, options):
    icon = options.get("icon") or default_icon
    default = options.get("default")
    answer = ctx().dialogs.message(icon, title, message, buttons,
                                   default=default,
                                   detail=options.get("detail"))
    return answer


def _showinfo(title=None, message=None, **options):
    _box("info", _OK, title, message, options)
    return "ok"


def _showwarning(title=None, message=None, **options):
    _box("warning", _OK, title, message, options)
    return "ok"


def _showerror(title=None, message=None, **options):
    _box("error", _OK, title, message, options)
    return "ok"


def _askyesno(title=None, message=None, **options):
    return _box("question", _YES_NO, title, message, options) == "yes"


def _askyesnocancel(title=None, message=None, **options):
    answer = _box("question", _YES_NO_CANCEL, title, message, options)
    if answer == "yes":
        return True
    if answer == "no":
        return False
    return None


def _askokcancel(title=None, message=None, **options):
    return _box("question", _OK_CANCEL, title, message, options) == "ok"


def _askretrycancel(title=None, message=None, **options):
    return _box("warning", _RETRY_CANCEL, title, message, options) == "retry"


def _askquestion(title=None, message=None, **options):
    answer = _box("question", _YES_NO, title, message, options)
    return "yes" if answer == "yes" else "no"


messagebox = types.SimpleNamespace(
    showinfo=_showinfo, showwarning=_showwarning, showerror=_showerror,
    askyesno=_askyesno, askyesnocancel=_askyesnocancel,
    askokcancel=_askokcancel, askretrycancel=_askretrycancel,
    askquestion=_askquestion,
    YES="yes", NO="no", OK="ok", CANCEL="cancel",
)


# ----------------------------------------------------------------------
# filedialog
# ----------------------------------------------------------------------
def _askopenfilename(**opts):
    return ctx().dialogs.file(
        "open", title=opts.get("title"), initialdir=opts.get("initialdir"),
        initialfile=opts.get("initialfile"), filetypes=opts.get("filetypes"))


def _askopenfilenames(**opts):
    return ctx().dialogs.file(
        "open", title=opts.get("title"), initialdir=opts.get("initialdir"),
        initialfile=opts.get("initialfile"), filetypes=opts.get("filetypes"),
        multiple=True)


def _asksaveasfilename(**opts):
    return ctx().dialogs.file(
        "save", title=opts.get("title"), initialdir=opts.get("initialdir"),
        initialfile=opts.get("initialfile"), filetypes=opts.get("filetypes"),
        defaultextension=opts.get("defaultextension"),
        confirmoverwrite=opts.get("confirmoverwrite", True))


def _askdirectory(**opts):
    return ctx().dialogs.file(
        "folder", title=opts.get("title"), initialdir=opts.get("initialdir"))


filedialog = types.SimpleNamespace(
    askopenfilename=_askopenfilename, askopenfilenames=_askopenfilenames,
    asksaveasfilename=_asksaveasfilename, askdirectory=_askdirectory,
)


# ----------------------------------------------------------------------
# simpledialog (a one-line answer; None when cancelled)
# ----------------------------------------------------------------------
def _prompt(kind, title, prompt, opts):
    initial = opts.get("initialvalue")
    spec = {"kind": "prompt", "input": kind, "title": title or "",
            "message": "" if prompt is None else str(prompt),
            "initial": "" if initial is None else str(initial),
            "min": opts.get("minvalue"), "max": opts.get("maxvalue"),
            "buttons": [{"id": "ok", "label": "OK", "style": "primary"},
                        {"id": "cancel", "label": "Cancel"}]}
    while True:
        answer = ctx().dialogs.ask(spec)
        if answer is None or answer == "cancel" or answer is False:
            return None
        text = str(answer)
        if kind == "str":
            return text
        try:
            value = int(text) if kind == "int" else float(text)
        except ValueError:
            spec["error"] = "Enter a whole number." if kind == "int" \
                else "Enter a number."
            spec["initial"] = text
            continue
        lo, hi = opts.get("minvalue"), opts.get("maxvalue")
        if lo is not None and value < lo or hi is not None and value > hi:
            spec["error"] = "Enter a value from %s to %s." % (
                "" if lo is None else lo, "" if hi is None else hi)
            spec["initial"] = text
            continue
        return value


simpledialog = types.SimpleNamespace(
    askstring=lambda title, prompt, **o: _prompt("str", title, prompt, o),
    askinteger=lambda title, prompt, **o: _prompt("int", title, prompt, o),
    askfloat=lambda title, prompt, **o: _prompt("float", title, prompt, o),
)


# ----------------------------------------------------------------------
# Tk variables
# ----------------------------------------------------------------------
_var_ids = itertools.count(1)


def _report_trace_error(var_name):
    """A failing trace: the traceback to the session log, one line to the
    app log."""
    import logging
    import traceback
    text = traceback.format_exc()
    logging.getLogger(__name__).error("trace on %s failed:\n%s",
                                      var_name, text)
    try:
        from ..core import session_log
        session_log.append(text)
    except Exception:                                   # noqa: BLE001
        pass
    window = getattr(_ctx, "window", None) if _ctx is not None else None
    if window is not None:
        try:
            last = text.strip().splitlines()[-1]
            window.append_log(
                "Internal error: %s - the action may be half done. The "
                "details are in the session log." % last, "error")
        except Exception:                               # noqa: BLE001
            pass


class _Var:
    """A Tk-variable look-alike.  Traces run synchronously in the thread
    that sets the value, as Tk's do on its own thread.  When bound to a
    store key the value is mirrored there, and the page's edits come back
    through :meth:`set`."""

    _default = ""

    def __init__(self, master=None, value=None, name=None, *,
                 store=None, ns=None, key=None):
        self._name = name or "PY_VAR%d" % next(_var_ids)
        self._lock = threading.RLock()
        self._value = self._coerce(self._default if value is None else value)
        self._traces = []           # (cbname, modes, fn)
        self._store = store
        self._ns = ns
        self._key = key
        if store is not None:
            store.set(ns, **{key: self._value})

    def __str__(self):
        return self._name

    # -- value ---------------------------------------------------------
    def _coerce(self, value):
        return value

    def get(self):
        with self._lock:
            return self._value

    def set(self, value):
        value = self._coerce(value)
        with self._lock:
            self._value = value
            traces = list(self._traces)
        if self._store is not None:
            self._store.set(self._ns, **{self._key: value})
        for _cbname, modes, fn in traces:
            if "write" in modes or "w" in modes:
                # Tk reports a failing trace and carries on with the rest;
                # one tab's broken reaction must not take the others with it.
                try:
                    fn(self._name, "", "write")
                except Exception:                       # noqa: BLE001
                    _report_trace_error(self._name)

    def bind(self, store, ns, key):
        """Mirror this var at ``ns.key`` from now on."""
        self._store, self._ns, self._key = store, ns, key
        store.set(ns, **{key: self.get()})

    def initialize(self, value):
        self.set(value)

    # -- traces --------------------------------------------------------
    def trace_add(self, mode, callback):
        modes = (mode,) if isinstance(mode, str) else tuple(mode)
        cbname = "%s_trace%d" % (self._name, next(_var_ids))
        with self._lock:
            self._traces.append((cbname, modes, callback))
        return cbname

    def trace_remove(self, mode, cbname):
        with self._lock:
            self._traces = [t for t in self._traces if t[0] != cbname]

    def trace_info(self):
        with self._lock:
            return [(t[1], t[0]) for t in self._traces]

    def trace(self, mode, callback):              # legacy Tk API
        return self.trace_add("write", callback)

    trace_variable = trace

    def trace_vdelete(self, mode, cbname):
        self.trace_remove(mode, cbname)


class StringVar(_Var):
    _default = ""

    def _coerce(self, value):
        return "" if value is None else str(value)


class BooleanVar(_Var):
    _default = False

    def _coerce(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)


class IntVar(_Var):
    _default = 0

    def _coerce(self, value):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return 0
            return int(float(value))
        return int(value or 0)


class DoubleVar(_Var):
    _default = 0.0

    def _coerce(self, value):
        if isinstance(value, str):
            value = value.strip()
            return float(value) if value else 0.0
        return float(value or 0.0)


# ----------------------------------------------------------------------
# root
# ----------------------------------------------------------------------
class Root:
    """What ``App`` asks of Tk's root window, on the UI loop."""

    def __init__(self, ctx_):
        self._ctx = ctx_
        self._title = ""

    # timers
    def after(self, ms, func=None, *args):
        return self._ctx.loop.after(ms, func, *args)

    def after_idle(self, func, *args):
        return self._ctx.loop.after_idle(func, *args)

    def after_cancel(self, tid):
        self._ctx.loop.after_cancel(tid)

    # window chrome
    def title(self, text=None):
        if text is None:
            return self._title
        self._title = str(text)
        self._ctx.store.set("shell", title=self._title)
        host = getattr(self._ctx, "host", None)
        if host is not None:
            host.set_title(self._title)
        return None

    def protocol(self, *_args, **_kw):
        return None

    def destroy(self):
        host = getattr(self._ctx, "host", None)
        if host is not None:
            host.quit()

    def quit(self):
        self.destroy()

    # no-ops: the desktop host owns the window
    def update(self):
        return None

    def update_idletasks(self):
        return None

    def withdraw(self):
        return None

    def deiconify(self):
        return None

    def lift(self):
        return None

    def focus_force(self):
        return None

    def bind(self, *_a, **_k):
        return None

    def unbind(self, *_a, **_k):
        return None

    def geometry(self, *_a):
        return ""

    def state(self, *_a):
        return "normal"

    def winfo_exists(self):
        return True

    def winfo_geometry(self):
        """The window's "WxH+X+Y", as settings.json keeps it."""
        app = getattr(self._ctx, "app", None)
        geo = getattr(app, "_last_normal_geometry", None) if app else None
        if not geo and app is not None:
            geo = (getattr(app, "_settings", {}) or {}).get(
                "window_geometry")
        return geo or "1280x860+80+60"

    def winfo_screenwidth(self):
        return 2560

    def winfo_screenheight(self):
        return 1440

    def clipboard_clear(self):
        self._clip = ""

    def clipboard_append(self, text):
        self._clip = getattr(self, "_clip", "") + str(text)
        self._ctx.bus.publish("clipboard", text=self._clip)
