"""PAD-844: an AI agent drives the running app through an MCP server
(buyvalve: "I want to talk to an agent and have it deal with the app to make
my mod").  The app publishes a link file while Settings > "Let AI agents
control PAD" is ticked; ``python -m pinball_decryptor.mcp`` reads it and
makes the page's own calls, questions and file pickers included.
"""

import io
import json
import os
import subprocess
import sys
import threading
import time

from pinball_decryptor import mcp
from pinball_decryptor.webui import agent_link, compat
from pinball_decryptor.webui.context import Context
from pinball_decryptor.webui.rpc import rpc
from pinball_decryptor.webui.server import WebServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _VideoTab:
    """A stand-in tab: a file list in the store, a Choose… that opens a
    picker and a Clear that asks first, like the real Video tab's."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.picked = {}
        ctx.store.set("video", rows=[
            {"rel": "movies/advance_tank_1.mp4", "name": "advance tank 1"},
            {"rel": "movies/attract_loop.mp4", "name": "attract loop"},
            {"rel": "movies/advance_tank_2.mp4", "name": "advance tank 2"}])

    @rpc
    def choose(self, rel):
        """Pick the file that replaces video *rel* (opens a file picker)."""
        path = compat.filedialog.askopenfilename(
            title="Replace %s" % rel, filetypes=[("Video", "*.mp4")])
        if path:
            self.picked[rel] = path
        return path

    @rpc
    def clear_all(self):
        """Clear every replacement, after asking."""
        if not compat.messagebox.askyesno("Clear all", "Clear every one?"):
            return False
        self.picked.clear()
        return True


class _Running:
    def __init__(self, tmp_path):
        self.ctx = Context()
        compat.install(self.ctx)
        self.ctx.loop.start()
        self.server = WebServer(self.ctx)
        self.server.start()
        self.ctx.server = self.server
        self.tab = _VideoTab(self.ctx)
        self.ctx.registry.service("video", self.tab)
        agent_link.register(self.ctx)
        self.link = str(tmp_path / "agent.json")

    def close(self):
        self.ctx.dialogs.cancel_all()
        self.server.stop()
        self.ctx.loop.stop()
        self.ctx.bus.close()
        compat.uninstall()


def _tool(srv, name, **args):
    reply = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args}})
    res = reply["result"]
    text = res["content"][0]["text"]
    try:
        return json.loads(text), res["isError"]
    except ValueError:
        return text, res["isError"]


def _patch_link(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_link, "link_path",
                        lambda: str(tmp_path / "agent.json"))


def test_protocol_handshake_and_tool_list():
    srv = mcp.Server(link=mcp.AppLink(path="nowhere.json"))
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert "pad_use_files" in init["result"]["instructions"]
    assert srv.handle({"jsonrpc": "2.0", "method":
                       "notifications/initialized"}) is None
    names = [t["name"] for t in srv.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        ["result"]["tools"]]
    assert names == ["pad_status", "pad_find_calls", "pad_call",
                     "pad_answer", "pad_result", "pad_state", "pad_search",
                     "pad_use_files", "pad_log"]
    assert srv.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})[
        "error"]["code"] == -32601


def test_app_not_open_says_how_to_turn_it_on(tmp_path):
    srv = mcp.Server(link=mcp.AppLink(path=str(tmp_path / "agent.json")))
    text, err = _tool(srv, "pad_status")
    assert err and "Let AI agents control PAD" in text


def test_agent_finds_replaces_and_answers_through_the_real_server(
        tmp_path, monkeypatch):
    _patch_link(monkeypatch, tmp_path)
    run = _Running(tmp_path)
    try:
        path = agent_link.set_enabled(run.ctx, True, "9.9.9")
        assert path == run.link
        srv = mcp.Server(link=mcp.AppLink(path=run.link))

        found, _ = _tool(srv, "pad_find_calls", query="replaces video")
        assert [c["name"] for c in found] == ["video.choose"]
        assert found[0]["params"] == "(rel)"

        rows, _ = _tool(srv, "pad_search", namespace="video",
                        query="ADVANCE tank")
        rels = [r["id"] for r in rows]
        assert rels == ["movies/advance_tank_1.mp4",
                        "movies/advance_tank_2.mp4"]

        # files: armed, then the picker the call opens takes them unseen
        new = [str(tmp_path / "tank_a.mp4"), str(tmp_path / "tank_b.mp4")]
        for rel, src in zip(rels, new):
            ok, _ = _tool(srv, "pad_use_files", paths=[src])
            assert ok is True
            res, err = _tool(srv, "pad_call", method="video.choose",
                             args=[rel])
            assert not err and res["status"] == "done", res
            assert res["result"] == os.path.normpath(src)
        assert run.tab.picked == {r: os.path.normpath(s)
                                  for r, s in zip(rels, new)}

        # a question: the call stops on it, the answer lets it finish
        res, _ = _tool(srv, "pad_call", method="video.clear_all")
        assert res["status"] == "waiting_on_question", res
        q = res["questions"][0]
        assert q["title"] == "Clear all"
        assert [b["id"] for b in q["buttons"]] == ["yes", "no"]
        status, _ = _tool(srv, "pad_status")
        assert [x["id"] for x in status["questions"]] == [q["id"]]
        res, _ = _tool(srv, "pad_answer", question_id=q["id"], value="yes")
        assert res["status"] == "done" and res["result"] is True, res
        assert run.tab.picked == {}

        # an app error comes back as a tool error, not a crash
        res, err = _tool(srv, "pad_call", method="video.nope")
        assert err and "No such call" in res["error"]

        # off again: the link is gone, and the agent is told so
        agent_link.set_enabled(run.ctx, False)
        assert not os.path.exists(run.link)
        text, err = _tool(srv, "pad_status")
        assert err and "not reachable" in text
    finally:
        run.close()


def test_a_stale_link_from_an_old_session_is_refused(tmp_path, monkeypatch):
    _patch_link(monkeypatch, tmp_path)
    run = _Running(tmp_path)
    try:
        agent_link.set_enabled(run.ctx, True)
        body = json.loads(open(run.link, encoding="utf-8").read())
        body["token"] = "an-old-session"
        with open(run.link, "w", encoding="utf-8") as f:
            json.dump(body, f)
        text, err = _tool(mcp.Server(link=mcp.AppLink(path=run.link)),
                          "pad_status")
        assert err and "refused" in text
        # and closing this session leaves another session's link alone
        assert agent_link.remove_link(run.ctx) is False
        assert os.path.exists(run.link)
    finally:
        run.close()


def test_drop_never_answers_a_save_as_unless_an_agent_armed_it(tmp_path):
    run = _Running(tmp_path)
    try:
        d = run.ctx.dialogs
        d.native_file_dialog = lambda spec: "native.txt"
        d.arm_drop([str(tmp_path / "a.txt")])
        assert run.ctx.loop.call(lambda: d.file(
            "save", filetypes=[("Text", "*.txt")])) == "native.txt"
        d.arm_drop([str(tmp_path / "b.txt")], wait=60, save=True)
        assert run.ctx.loop.call(lambda: d.file(
            "save", filetypes=[("Text", "*.txt")])) == \
            os.path.normpath(str(tmp_path / "b.txt"))
        # an empty arming clears it
        d.arm_drop([str(tmp_path / "c.txt")], wait=60)
        d.arm_drop([], wait=0)
        assert run.ctx.loop.call(lambda: d.file(
            "open", filetypes=[("Text", "*.txt")])) == "native.txt"
    finally:
        run.close()


def test_stdio_process_speaks_line_json(tmp_path):
    """The real ``python -m pinball_decryptor.mcp`` process, as an agent
    starts it: one JSON message per line each way."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    env = dict(os.environ, APPDATA=str(tmp_path),
               XDG_CONFIG_HOME=str(tmp_path))
    proc = subprocess.Popen(
        [sys.executable, "-m", "pinball_decryptor.mcp"], cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out = {}
    try:
        for m in msgs:
            proc.stdin.write((json.dumps(m) + "\n").encode("utf-8"))
            proc.stdin.flush()
        deadline = time.monotonic() + 30
        while len(out) < 2 and time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            reply = json.loads(line)
            out[reply["id"]] = reply
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    assert out[1]["result"]["serverInfo"]["name"] == "pinball-asset-decryptor"
    assert out[1]["result"]["protocolVersion"] == "2024-11-05"
    assert len(out[2]["result"]["tools"]) == len(mcp.TOOLS)


def test_settings_toggle_publishes_and_persists(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    _patch_link(monkeypatch, tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        w.ctx.server = WebServer(w.ctx)
        w.ctx.server.start()
        agent_link.register(w.ctx)          # host.build does, for real
        try:
            item = [i for i in w.state("shell")["settings_items"]
                    if i.get("id") == "toggle_agent_access"][0]
            assert item["label"] == "Let AI agents control PAD"
            assert item["checked"] is False
            assert not os.path.exists(agent_link.link_path())

            w.call("ui.settings_action", "toggle_agent_access")
            link = json.loads(open(agent_link.link_path(),
                                   encoding="utf-8").read())
            assert link["port"] == w.ctx.server.port
            assert link["token"] == w.ctx.token
            told = w.asked[-1]
            assert told["title"] == "Let AI agents control PAD"
            snippet = json.loads(told["detail"])
            entry = snippet["mcpServers"]["pinball-asset-decryptor"]
            assert entry["args"] == ["-m", "pinball_decryptor.mcp"]
            settings = json.loads((tmp_path / "cfg" / "settings.json")
                                  .read_text(encoding="utf-8"))
            assert settings["agent_access"] is True
            item = [i for i in w.state("shell")["settings_items"]
                    if i.get("id") == "toggle_agent_access"][0]
            assert item["checked"] is True

            # the real App's calls answer through the link too
            srv = mcp.Server(link=mcp.AppLink(path=agent_link.link_path()))
            status, err = _tool(srv, "pad_status")
            assert not err and status["manufacturer"] == "stern"
            assert {"ns": "video", "label": "Video"} in status["tabs"] or \
                status["tabs"]
            found, _ = _tool(srv, "pad_find_calls", namespace="video",
                             query="choose")
            assert "video.choose" in [c["name"] for c in found]

            w.call("ui.settings_action", "toggle_agent_access")
            assert not os.path.exists(agent_link.link_path())
            settings = json.loads((tmp_path / "cfg" / "settings.json")
                                  .read_text(encoding="utf-8"))
            assert settings["agent_access"] is False
        finally:
            w.ctx.server.stop()


def test_row_ids_name_each_tabs_file_key():
    rows = {"rows": [{"k": "audio/a tank.wav"}, {"k": "audio/b.wav"}],
            "panes": [{"k": "tank pane"}]}
    hits = agent_link.search_rows(rows, "tank", ns="audio")
    assert [(h["key"], h.get("id")) for h in hits] == [
        ("panes", None), ("rows", "audio/a tank.wav")]
    assert agent_link.row_id("images", {"r": "a.png", "k": "keep"}) == "a.png"
    assert agent_link.row_id("video", {"rel": "m.mp4"}) == "m.mp4"
    assert agent_link.row_id("video", {"name": "m"}) is None
