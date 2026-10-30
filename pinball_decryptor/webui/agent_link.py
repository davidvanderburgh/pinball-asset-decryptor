"""Let an AI agent drive the running app (PAD-844).

Off by default: Settings (the gear) > "Let AI agents control PAD" turns it
on.  While it is on, the app writes :func:`link_path` (``agent.json`` beside
settings.json): the local server's port and its session token, which only
programs running as this Windows user can read.  The MCP server
(``python -m pinball_decryptor.mcp``, :mod:`pinball_decryptor.mcp`) reads it
and makes the same calls the app's own page makes, so an agent can do
anything a click can, through the same checks.  Turned off, or the app
closed, the file is removed and the token in it dies with the session.

The calls this adds for the agent (``agent.*``):

* ``agent.calls(query, ns)``: every call the page can make, with its
  parameters and the first paragraph of its help, so the agent can find
  the one it needs without reading the code;
* ``agent.use_files(paths)``: the next file or folder picker the app
  opens answers with *paths* instead of showing (a Save As too), so the
  agent can pick files the way a drop on a Browse… button does (PAD-838).
"""

import inspect
import json
import logging
import os
import sys
import time

from ..core import config
from .rpc import RpcError

log = logging.getLogger(__name__)

#: how long :func:`use_files` paths wait for the picker the next call opens
USE_FILES_WAIT_S = 120.0


def link_path():
    """Where the running app tells an agent how to reach it."""
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "agent.json")


def mcp_command():
    """The command an agent's MCP config starts the server with: this very
    Python (the packaged app's own ``python\\python.exe`` on Windows) and
    the module, as a list."""
    exe = sys.executable or "python"
    if getattr(sys, "frozen", False):
        # the Mac / Linux app bundle: its own binary runs the server
        # (installer/pyinstaller_entry.py)
        return [exe, "--mcp"]
    if os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(console):
            exe = console
    return [exe, "-m", "pinball_decryptor.mcp"]


def mcp_config_snippet():
    """The ``mcpServers`` entry to paste into an agent's MCP config."""
    cmd = mcp_command()
    entry = {"command": cmd[0], "args": cmd[1:]}
    if not getattr(sys, "frozen", False):
        # ``-m`` finds the package from here: the app's own folder
        entry["cwd"] = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
    return json.dumps({"mcpServers": {"pinball-asset-decryptor": entry}},
                      indent=2)


def write_link(ctx, port, version=""):
    """Publish the link file (atomically: an agent never reads half)."""
    path = link_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = {"port": int(port), "token": ctx.token, "pid": os.getpid(),
            "version": version, "written": time.time()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.replace(tmp, path)
    return path


def remove_link(ctx=None):
    """Take the link file away; only this app's own (another PAD running
    beside it may have written its own since)."""
    path = link_path()
    try:
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
    except (OSError, ValueError):
        return False
    if ctx is not None and body.get("token") != ctx.token:
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def set_enabled(ctx, on, version=""):
    """Agent access on or off for this session; returns the link path (on)
    or None.  Never raises: a link that cannot be written is logged."""
    server = getattr(ctx, "server", None)
    try:
        if on and server is not None:
            return write_link(ctx, server.port, version)
        remove_link(ctx)
    except OSError:
        log.exception("agent link")
    return None


# ----------------------------------------------------------------------
# the agent's own calls
# ----------------------------------------------------------------------
def _signature(fn):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return "(...)"
    params = [p for p in sig.parameters.values() if p.name != "self"]
    return "(%s)" % ", ".join(str(p) for p in params)


def _first_paragraph(fn):
    doc = inspect.getdoc(fn) or ""
    return doc.split("\n\n", 1)[0].replace("\n", " ").strip()


def describe_calls(registry, query="", ns=""):
    """The registry's calls as ``[{name, params, doc}]``, filtered to those
    whose name or help holds every word of *query* (any case) and, with
    *ns*, to that namespace."""
    words = [w for w in str(query or "").lower().split() if w]
    out = []
    for name in registry.names():
        if ns and not name.startswith(ns + "."):
            continue
        fn = registry._methods[name][0]
        doc = _first_paragraph(fn)
        hay = (name + " " + doc).lower()
        if words and not all(w in hay for w in words):
            continue
        out.append({"name": name, "params": _signature(fn), "doc": doc})
    return out


#: where a tab's file-list row keeps the file the tab's calls take (its
#: ``rel``); a tab not named here keeps it under ``rel``
ROW_ID_KEYS = {"audio": "k", "images": "r"}


def row_id(ns, row):
    """The file *row* of tab *ns* stands for, or None."""
    if not isinstance(row, dict):
        return None
    value = row.get(ROW_ID_KEYS.get(ns, "rel"))
    return value if isinstance(value, str) else None


def search_rows(values, query, key="", limit=50, ns=""):
    """``[{key, index, id, row}]`` for the list items under *values* (one
    state namespace) whose JSON holds every word of *query*, any case;
    ``id`` is the file a ``rows`` item stands for (:func:`row_id`)."""
    words = [w for w in str(query or "").lower().split() if w]
    out = []
    for k in sorted(values):
        if key and k != key:
            continue
        rows = values[k]
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            try:
                hay = json.dumps(row, default=str).lower()
            except (TypeError, ValueError):
                continue
            if all(w in hay for w in words):
                hit = {"key": k, "index": i, "row": row}
                if k == "rows":
                    hit["id"] = row_id(ns, row)
                out.append(hit)
                if len(out) >= int(limit):
                    return out
    return out


def register(ctx):
    """Publish the ``agent.*`` calls (run off the UI loop: they only read,
    and must answer while a modal holds the loop)."""
    reg = ctx.registry

    def calls(query="", ns=""):
        return describe_calls(reg, query, ns)

    def use_files(paths):
        if isinstance(paths, str):
            paths = [paths]
        paths = [str(p) for p in (paths or []) if str(p).strip()]
        if not paths:
            ctx.dialogs.arm_drop([], wait=0)
            return False
        ctx.dialogs.arm_drop(paths, wait=USE_FILES_WAIT_S, save=True)
        return True

    def modals():
        return ctx.store.get("modals", "open") or []

    def known(ns):
        with ctx.store._lock:
            if not ns:
                return {name: sorted(values)
                        for name, values in ctx.store._ns.items()}
            if ns not in ctx.store._ns:
                raise RpcError("No state namespace %r; agent.state() with "
                               "no namespace lists them." % ns)
        return None

    def state(ns="", keys=None):
        listing = known(ns)
        if listing is not None:
            return listing
        values = ctx.store.namespace(ns)
        if keys:
            if isinstance(keys, str):
                keys = [keys]
            values = {k: values.get(k) for k in keys}
        return values

    def log_lines(lines=40):
        window = ctx.window
        rows = window.log_history() if window is not None else []
        return ["%s %s%s" % (r.get("ts", ""),
                             "" if r.get("level") in ("info", None)
                             else "[%s] " % r.get("level"), r.get("text", ""))
                for r in rows[-max(1, int(lines)):]]

    def status():
        shell = ctx.store.namespace("shell") or {}
        window = ctx.window
        project = ""
        var = getattr(window, "write_assets_var", None) if window else None
        try:
            project = var.get() if var is not None else ""
        except Exception:                               # noqa: BLE001
            project = ""
        mfr = shell.get("mfr") or {}
        return {"version": shell.get("version", ""),
                "view": shell.get("view"),
                "manufacturer": mfr.get("key") if isinstance(mfr, dict)
                else mfr,
                "tab": shell.get("tab"),
                "tabs": [{"ns": t.get("ns"), "label": t.get("label")}
                         for t in (shell.get("tabs") or [])
                         if isinstance(t, dict) and t.get("visible")],
                "project_folder": project,
                "running": bool(shell.get("running")),
                "run_mode": shell.get("run_mode"),
                "questions": modals(),
                "log": log_lines(10)}

    def search(ns, query, key="", limit=50):
        """Rows of the lists in state namespace *ns* (or just its *key*)
        holding every word of *query*: a tab's file list, say."""
        known(ns or "-")
        return search_rows(ctx.store.namespace(ns), query, key, limit, ns)

    reg.register("agent.search", search, on_loop=False)
    reg.register("agent.calls", calls, on_loop=False)
    reg.register("agent.use_files", use_files, on_loop=False)
    reg.register("agent.modals", modals, on_loop=False)
    reg.register("agent.state", state, on_loop=False)
    reg.register("agent.log", log_lines, on_loop=False)
    reg.register("agent.status", status, on_loop=False)
