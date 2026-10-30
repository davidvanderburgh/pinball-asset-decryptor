"""An MCP server that lets an AI agent drive the running app (PAD-844).

Run by the agent (Claude Desktop, Claude Code, Cursor, VS Code...) as a
stdio MCP server::

    {"mcpServers": {"pinball-asset-decryptor": {
        "command": "C:\\\\Program Files\\\\Pinball Asset Decryptor\\\\python\\\\python.exe",
        "args": ["-m", "pinball_decryptor.mcp"],
        "cwd": "C:\\\\Program Files\\\\Pinball Asset Decryptor"}}}

It does no work itself: it reaches the open app through the link file the
app writes while Settings > "Let AI agents control PAD" is ticked
(:mod:`pinball_decryptor.webui.agent_link`) and makes the calls the app's
own page makes, so everything goes through the same checks as a click.
Standard library only, so the app's own Python runs it as is.

The protocol is JSON-RPC 2.0, one message per line on stdin / stdout
(the MCP stdio transport); only ``initialize``, ``ping``, ``tools/list``
and ``tools/call`` are needed.
"""

import itertools
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

from . import __version__

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

#: the longest a tool result may be, in characters, before it is cut (an
#: agent's context is not the place for a whole scene tree)
MAX_RESULT_CHARS = 60000

INSTRUCTIONS = """\
Pinball Asset Decryptor (PAD) makes mods of pinball machine games: it
extracts a game's pictures, sounds, videos, text, scenes and modes into a
project folder, lets you replace or change them, and writes a new game image.

These tools drive the PAD window that is open on this PC, exactly as clicks
would. Work like this:
1. pad_status: what is open (manufacturer, project folder, tabs, whether a
   job is running, questions waiting for an answer, recent log lines).
2. pad_find_calls: find the call for what you want to do. Calls are named
   "<tab>.<action>", e.g. video.choose, audio.scan, ui.select_tab.
3. pad_state / pad_search: read what a tab shows. Each tab's state lives in
   a namespace named like its calls (video, audio, images, text, modes...);
   its file list is under "rows". pad_search gives each row's "id": the
   file it stands for, what the tab's calls take as their rel argument.
4. pad_call: run a call. If it opens a question (a message box, a file
   picker the app could not answer), the result says so: answer it with
   pad_answer. Long jobs (extract, write) return while running; follow them
   with pad_status / pad_log and pad_result.
5. Files: call pad_use_files with the paths first, then the call that would
   open the Browse... / Choose... picker (video.choose, say); the picker
   takes those paths instead of showing.
A tab's rows exist once it is open in PAD (ui.select_tab) and scanned.
Opening a tab starts its scan by itself: wait while its state's "scanning"
is true (pad_state with keys ["scanning"]). Calls are the window's buttons,
so a Scan called while a scan runs cancels it, as a second click would.
"""


# ----------------------------------------------------------------------
# reaching the app
# ----------------------------------------------------------------------
class AppNotReachable(Exception):
    """The app is not open, or agent access is off."""


def link_path():
    from .core import config
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), "agent.json")


NOT_OPEN = ("Pinball Asset Decryptor is not reachable. Open it and tick "
            "Settings (the gear) > Let AI agents control PAD, then try "
            "again.")


class AppLink:
    """The HTTP calls into the running app, through its link file."""

    def __init__(self, path=None, timeout=None):
        self.path = path or link_path()
        self.timeout = timeout

    def _link(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                link = json.load(f)
            return int(link["port"]), str(link["token"])
        except (OSError, ValueError, KeyError, TypeError):
            raise AppNotReachable(NOT_OPEN)

    def _post(self, route, body, timeout=None):
        port, token = self._link()
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (port, route),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-PAD-Token": token}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise AppNotReachable(
                    "PAD refused the link (it was restarted?): " + NOT_OPEN)
            raise AppNotReachable("PAD answered HTTP %d." % e.code)
        except (urllib.error.URLError, OSError):
            raise AppNotReachable(NOT_OPEN)

    def call(self, method, args=None, kwargs=None, timeout=None):
        """Run one app call; returns its result or raises CallFailed."""
        reply = self._post("/api", {"m": method, "a": list(args or []),
                                    "k": dict(kwargs or {})},
                           timeout if timeout is not None else self.timeout)
        if not isinstance(reply, dict) or not reply.get("ok"):
            raise CallFailed((reply or {}).get("error") or "call failed")
        return reply.get("r")

    def reply(self, mid, value):
        reply = self._post("/api/reply", {"id": mid, "v": value}, 15)
        return bool((reply or {}).get("ok"))


class CallFailed(Exception):
    """The app ran the call and it failed; the message is the app's."""


# ----------------------------------------------------------------------
# calls that may stop on a question
# ----------------------------------------------------------------------
class Pending:
    """App calls still running (they wait on a question, or are long)."""

    def __init__(self):
        self._ids = itertools.count(1)
        self._calls = {}            # id -> {"thread", "done", "result"...}
        self._lock = threading.Lock()

    def start(self, link, method, args, kwargs):
        cid = next(self._ids)
        entry = {"method": method, "done": threading.Event()}

        def _run():
            try:
                entry["result"] = link.call(method, args, kwargs)
            except (CallFailed, AppNotReachable) as e:
                entry["error"] = str(e)
            except Exception as e:                      # noqa: BLE001
                entry["error"] = "%s: %s" % (type(e).__name__, e)
            finally:
                entry["done"].set()

        with self._lock:
            self._calls[cid] = entry
        threading.Thread(target=_run, name="pad-mcp-call-%d" % cid,
                         daemon=True).start()
        return cid

    def ids(self):
        with self._lock:
            return [cid for cid, e in self._calls.items()]

    def wait(self, link, cid, seconds, questions_before=()):
        """Wait for call *cid* up to *seconds*; stop early when the app asks
        a question it did not have open before.  Returns the tool result."""
        with self._lock:
            entry = self._calls.get(cid)
        if entry is None:
            return {"status": "unknown_call", "call_id": cid,
                    "running_calls": self.ids()}
        seen = {q.get("id") for q in questions_before}
        deadline = time.monotonic() + max(0.0, float(seconds))
        while True:
            if entry["done"].wait(0.25):
                with self._lock:
                    self._calls.pop(cid, None)
                if "error" in entry:
                    return {"status": "failed", "call_id": cid,
                            "method": entry["method"],
                            "error": entry["error"]}
                return {"status": "done", "call_id": cid,
                        "method": entry["method"],
                        "result": entry.get("result")}
            try:
                questions = link.call("agent.modals", timeout=10) or []
            except (CallFailed, AppNotReachable):
                questions = []
            new = [q for q in questions if q.get("id") not in seen]
            if new:
                return {"status": "waiting_on_question", "call_id": cid,
                        "method": entry["method"], "questions": questions,
                        "next": "Answer with pad_answer (question id and "
                                "the value: one of its buttons for a "
                                "message, a path or list of paths for a "
                                "file picker, \"\" to cancel)."}
            if time.monotonic() >= deadline:
                return {"status": "still_running", "call_id": cid,
                        "method": entry["method"],
                        "next": "Follow it with pad_result (this call_id), "
                                "pad_status or pad_log."}


# ----------------------------------------------------------------------
# the tools
# ----------------------------------------------------------------------
def _obj(props, required=()):
    return {"type": "object", "properties": props,
            "required": list(required)}


TOOLS = [
    {"name": "pad_status",
     "description": "What the open PAD window shows: version, manufacturer, "
                    "project folder, the tabs, the tab open, whether a job "
                    "runs, questions waiting for an answer and the last log "
                    "lines.",
     "inputSchema": _obj({})},
    {"name": "pad_find_calls",
     "description": "Find app calls by words in their name or help, e.g. "
                    "'video replace' or 'scan'. Each comes with its "
                    "parameters and what it does. Empty query lists all.",
     "inputSchema": _obj({
         "query": {"type": "string", "description": "words to match"},
         "namespace": {"type": "string",
                       "description": "only this tab's calls, e.g. video"}})},
    {"name": "pad_call",
     "description": "Run an app call (a click). Returns its result, or "
                    "that it waits on a question (answer with pad_answer), "
                    "or that it still runs (pad_result).",
     "inputSchema": _obj({
         "method": {"type": "string", "description": "e.g. video.choose"},
         "args": {"type": "array", "description": "positional arguments"},
         "kwargs": {"type": "object", "description": "named arguments"},
         "wait_seconds": {"type": "number",
                          "description": "how long to wait (default 30)"}},
         ["method"])},
    {"name": "pad_answer",
     "description": "Answer a question PAD shows (from pad_status or a "
                    "pad_call that waits on one), then wait for the call "
                    "it held up.",
     "inputSchema": _obj({
         "question_id": {"type": "string"},
         "value": {"description": "a button of a message (e.g. 'yes', "
                                  "'ok'), a path or list of paths for a "
                                  "file picker, '' to cancel"},
         "wait_seconds": {"type": "number"}}, ["question_id", "value"])},
    {"name": "pad_result",
     "description": "Wait for a call pad_call reported still running.",
     "inputSchema": _obj({"call_id": {"type": "integer"},
                          "wait_seconds": {"type": "number"}},
                         ["call_id"])},
    {"name": "pad_state",
     "description": "Read what a tab shows. No namespace: every namespace "
                    "and its keys. With keys: only those (a tab's whole "
                    "state can be large).",
     "inputSchema": _obj({
         "namespace": {"type": "string"},
         "keys": {"type": "array", "items": {"type": "string"}}})},
    {"name": "pad_search",
     "description": "Find rows in a tab's lists holding every word of a "
                    "query, e.g. namespace 'video', query 'advance tank'. "
                    "Each row's 'id' is what that tab's calls take as "
                    "rel.",
     "inputSchema": _obj({
         "namespace": {"type": "string"},
         "query": {"type": "string"},
         "key": {"type": "string", "description": "only this list"},
         "limit": {"type": "integer"}}, ["namespace", "query"])},
    {"name": "pad_use_files",
     "description": "The next file or folder picker PAD opens (within 2 "
                    "minutes) takes these paths instead of showing; a "
                    "Save As takes the first. Then call what opens it.",
     "inputSchema": _obj({"paths": {"type": "array",
                                    "items": {"type": "string"}}},
                         ["paths"])},
    {"name": "pad_log",
     "description": "The last lines of PAD's log.",
     "inputSchema": _obj({"lines": {"type": "integer"}})},
]


class Server:
    def __init__(self, link=None, out=None):
        self.link = link or AppLink()
        self.pending = Pending()
        self.out = out or sys.stdout
        self._write_lock = threading.Lock()

    # -- the tools ------------------------------------------------------
    def tool(self, name, a):
        link = self.link
        if name == "pad_status":
            return link.call("agent.status", timeout=15)
        if name == "pad_find_calls":
            return link.call("agent.calls", [a.get("query") or "",
                                             a.get("namespace") or ""],
                             timeout=15)
        if name == "pad_call":
            method = str(a.get("method") or "")
            if not method:
                raise CallFailed("method is required")
            before = link.call("agent.modals", timeout=10) or []
            cid = self.pending.start(link, method, a.get("args") or [],
                                     a.get("kwargs") or {})
            return self.pending.wait(link, cid, a.get("wait_seconds", 30),
                                     before)
        if name == "pad_answer":
            mid = str(a.get("question_id") or "")
            ok = link.reply(mid, a.get("value"))
            if not ok:
                return {"status": "no_such_question", "question_id": mid,
                        "questions": link.call("agent.modals", timeout=10)}
            ids = self.pending.ids()
            if not ids:
                return {"status": "answered"}
            # the call the answer let go on (the newest still running)
            time.sleep(0.2)
            return self.pending.wait(
                link, ids[-1], a.get("wait_seconds", 30),
                link.call("agent.modals", timeout=10) or [])
        if name == "pad_result":
            return self.pending.wait(
                link, int(a.get("call_id") or 0), a.get("wait_seconds", 30),
                link.call("agent.modals", timeout=10) or [])
        if name == "pad_state":
            return link.call("agent.state", [a.get("namespace") or "",
                                             a.get("keys") or None],
                             timeout=30)
        if name == "pad_search":
            return link.call("agent.search", [
                a.get("namespace") or "", a.get("query") or "",
                a.get("key") or "", int(a.get("limit") or 50)], timeout=30)
        if name == "pad_use_files":
            return link.call("agent.use_files", [a.get("paths") or []],
                             timeout=10)
        if name == "pad_log":
            return link.call("agent.log", [int(a.get("lines") or 40)],
                             timeout=10)
        raise KeyError(name)

    # -- the protocol ---------------------------------------------------
    def handle(self, msg):
        """One JSON-RPC message in; the response dict, or None for a
        notification."""
        mid = msg.get("id")
        method = msg.get("method")
        if mid is None:
            return None                     # notifications: nothing to say
        params = msg.get("params") or {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _ok(mid, {
                "protocolVersion": asked if asked in PROTOCOLS
                else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "pinball-asset-decryptor",
                               "version": __version__},
                "instructions": INSTRUCTIONS})
        if method == "ping":
            return _ok(mid, {})
        if method == "tools/list":
            return _ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            if name not in {t["name"] for t in TOOLS}:
                return _err(mid, -32602, "Unknown tool: %s" % name)
            try:
                result = self.tool(name, params.get("arguments") or {})
                failed = isinstance(result, dict) and \
                    result.get("status") == "failed"
                return _ok(mid, _content(result, failed))
            except (AppNotReachable, CallFailed) as e:
                return _ok(mid, _content(str(e), True))
            except Exception as e:                      # noqa: BLE001
                return _ok(mid, _content("%s: %s" % (type(e).__name__, e),
                                         True))
        return _err(mid, -32601, "Method not found: %s" % method)

    def send(self, obj):
        line = json.dumps(obj, ensure_ascii=False, default=str)
        with self._write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def serve(self, stdin=None):
        stdin = stdin or sys.stdin
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send(_err(None, -32700, "Parse error"))
                continue
            if not isinstance(msg, dict):
                self.send(_err(None, -32600, "Invalid request"))
                continue
            # each request on its own thread: a call waiting on a question
            # must not hold up the pad_answer that lets it go on
            threading.Thread(target=self._answer, args=(msg,),
                             daemon=True).start()

    def _answer(self, msg):
        reply = self.handle(msg)
        if reply is not None:
            self.send(reply)


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": code, "message": message}}


def _content(result, is_error=False):
    text = result if isinstance(result, str) else json.dumps(
        result, ensure_ascii=False, indent=1, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = (text[:MAX_RESULT_CHARS] + "\n... cut at %d of %d characters: "
                "ask for fewer keys (pad_state keys) or search (pad_search)."
                % (MAX_RESULT_CHARS, len(text)))
    return {"content": [{"type": "text", "text": text}],
            "isError": bool(is_error)}


def main():
    # MCP's stdio transport is UTF-8 both ways, whatever the console's code page
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
    Server().serve()


if __name__ == "__main__":
    main()
