"""PAD-782: the Attract page - the game's attract screens in order with the owner's items between them.

The game's screens are stubbed (attract_items.project_pages, the title's refusal): the page's own work is under test -
adding photos, a clip and a text card after or before a screen, moving an item past items and past a run of screens
of one name, its seconds, its words, taking it off, the record in the project's sidecar, and a game it cannot add to.
"""
import json
import os
import time

from pinball_decryptor.plugins.stern import attract_items as AI
from pinball_decryptor.plugins.stern import clip_variants as CV
from tests.webui_harness import web_app

PAGES = [AI.Page(0, 0x100, 0x200, 3.0, "Player Id"),
         AI.Page(1, 0x110, 0, 5.0, "Credits Press Start"),
         AI.Page(2, 0x120, 0x210, 3.0, "High score / champion page"),
         AI.Page(3, 0x130, 0x210, 3.0, "High score / champion page"),
         AI.Page(4, 0x140, 0, 5.0, "Game Title")]


def _wait(w, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        w.drain(0.05)
        if cond():
            return True
    return False


def _stub(monkeypatch, why=""):
    monkeypatch.setattr(CV, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(AI, "title_refusal", lambda prof: why)
    monkeypatch.setattr(AI, "project_pages", lambda project, prof=None: list(PAGES))


def _open(w, folder):
    w.run(lambda: w.window.write_assets_var.set(folder))
    w.call("ui.select_tab", "attract")
    assert _wait(w, lambda: not w.state("attract")["reading"] and w.state("attract")["project"] == folder)


def _sidecar(proj):
    with open(os.path.join(proj, ".staged_changes.json"), encoding="utf-8") as f:
        return json.load(f)


def _seq(w):
    """The painted sequence in words: game runs as their name (xN), items as their label."""
    out = []
    for r in w.state("attract")["seq"]:
        out.append(("%s x%d" % (r["name"], r["n"])) if r["t"] == "game" else r["label"])
    return out


def test_the_page_puts_items_between_the_games_screens(tmp_path, monkeypatch):
    _stub(monkeypatch)
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    photos = [str(tmp_path / ("p%d.jpg" % k)) for k in (1, 2)]
    clip = str(tmp_path / "c.mp4")
    for f in photos + [clip]:
        open(f, "wb").close()
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        st = w.state("attract")
        assert st["available"] and st["count"] == 0
        assert _seq(w) == ["Player Id x1", "Credits Press Start x1", "High score / champion page x2", "Game Title x1"]
        # two photos after the champion pages (one menu, several files), a clip before the first screen
        w.answers.append(photos)
        assert w.call("attract.add", "photo", 2, 3, "after") is True
        w.answers.append(clip)
        assert w.call("attract.add", "clip", 0, 0, "before") is True
        assert w.call("attract.add", "text", 1, 1, "after") is True
        assert _seq(w) == ["Clip: c.mp4", "Player Id x1", "Credits Press Start x1", "Text: Your words here",
                           "High score / champion page x2", "Photo: p1.jpg", "Photo: p2.jpg", "Game Title x1"]
        rec = _sidecar(proj)[AI.STAGED_KEY]
        assert [(i["kind"], i["entry"], i["where"]) for i in rec["items"]] == [
            ("photo", 3, "after"), ("photo", 3, "after"), ("clip", 0, "before"), ("text", 1, "after")]
        # its words and its seconds
        text = next(r for r in w.state("attract")["seq"] if r["t"] == "item" and r["kind"] == "text")
        assert w.call("attract.set_text", text["i"], "Welcome to Dave's basement\nFree play") is True
        assert w.call("attract.set_seconds", text["i"], "500") is True
        it = AI.load(proj).items[text["i"]]
        assert it.text == "Welcome to Dave's basement\nFree play" and it.seconds == AI.MAX_SECONDS
        # moved down: past the run of champion pages in one step, then past a photo
        assert w.call("attract.move", text["i"], 1) is True
        assert _seq(w)[3:5] == ["High score / champion page x2", "Text: Welcome to Dave's basement / Free play"]
        t = AI.load(proj).items
        k = next(n for n, i in enumerate(t) if i.kind == "text")
        assert (t[k].entry, t[k].where) == (3, "after")
        assert w.call("attract.move", k, 1) is True
        assert _seq(w)[4:7] == ["Photo: p1.jpg", "Text: Welcome to Dave's basement / Free play", "Photo: p2.jpg"]
        # a drag of two rows up: back past the photo and above the champion pages
        k = next(n for n, i in enumerate(AI.load(proj).items) if i.kind == "text")
        assert w.call("attract.move_by", k, -2) is True
        assert _seq(w)[3:5] == ["Text: Welcome to Dave's basement / Free play", "High score / champion page x2"]
        # the clip cannot go higher than the top
        k = next(n for n, i in enumerate(AI.load(proj).items) if i.kind == "clip")
        assert w.call("attract.move", k, -1) is False
        # taken off
        assert w.call("attract.remove", k) is True
        assert "Clip: c.mp4" not in _seq(w) and w.state("attract")["count"] == 3


def test_a_game_it_cannot_add_to_says_why(tmp_path, monkeypatch):
    _stub(monkeypatch, why="Venom starts its attract screens in a way the app cannot add to yet.")
    proj = str(tmp_path / "proj")
    os.makedirs(proj)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        st = w.state("attract")
        assert not st["available"] and st["why"].startswith("Venom starts")
        assert w.call("attract.add", "text", 0, 0, "after") is False
    assert not os.path.isfile(os.path.join(proj, ".staged_changes.json"))


def test_the_rail_shows_it_on_spike2_only(tmp_path):
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["attract"]["visible"] and tabs["attract"]["group"] == "Make"
    with web_app(tmp_path / "jjp", mfr="jjp") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["attract"]["visible"]
