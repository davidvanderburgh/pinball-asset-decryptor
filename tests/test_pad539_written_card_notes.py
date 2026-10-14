"""PAD-539 (DragonRR): a project extracted from a card a Write had already changed, and Scenes'
Filled-in marks with no reading of the boxes the game program names.

His project came off a card PAD had written, so that Write's added pictures, hides and new text
were its "original": As shipped and Reset could not take them back, and nothing said why.  And
with no ``engine.program_node_paths`` (his card was not at hand for the Text tab's re-read) the
Filled-in marks were the old word guesses, so a box the game writes said "Not this one".  Now
Scenes, its As shipped questions and the Reset dialog say which card the project came off, and
the Filled-in bar says its marks are guesses, with Re-read from card to read the real ones."""

import json
import os

import pytest

from pinball_decryptor.core import extract_source as es
from pinball_decryptor.core import lineage
from tests.test_gui_scene_editor import CARD, _tv
from tests.test_pad485_game_line_in_scenes import _project, _wait
from tests.webui_harness import web_app

pytest.importorskip("PIL")


def _lineage(folder, **source):
    data = {"format": lineage.LINEAGE_FORMAT, "id": "x",
            "stock": {"sidx": "gz", "label": "Godzilla LE 1.16", "print": "p0"},
            "source": dict({"print": "p1", "name": "card.raw", "label": "Godzilla LE 1.16"},
                           **source),
            "revs": []}
    assert lineage.write_lineage(str(folder), data)


def test_extracted_from_names_a_written_or_modified_card(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    assert lineage.extracted_from(str(folder)) is None              # nothing says
    _lineage(folder, status="official", rev=0)
    assert lineage.extracted_from(str(folder)) is None
    _lineage(folder, status="modified", rev=3)                      # one of its own revisions
    assert lineage.extracted_from(str(folder)) == {
        "kind": "written", "rev": 3, "label": "Godzilla LE 1.16"}
    _lineage(folder, status="modified", rev=None)
    assert lineage.extracted_from(str(folder)) == {
        "kind": "modified", "label": "Godzilla LE 1.16"}
    # no print taken (no lineage), but the extract's stock check said modified
    os.remove(os.path.join(str(folder), lineage.LINEAGE_FILE))
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 64)
    es.write_extract_source(str(folder), str(card))
    es.amend_extract_source(str(folder), stock={"status": "modified", "label": "Godzilla Pro"})
    assert lineage.extracted_from(str(folder)) == {"kind": "modified", "label": "Godzilla Pro"}
    es.amend_extract_source(str(folder), stock={"status": "official"})
    assert lineage.extracted_from(str(folder)) is None


def test_the_note_says_as_shipped_goes_back_to_that_card():
    assert lineage.extracted_from_note(None) is None
    note = lineage.extracted_from_note({"kind": "written", "rev": 2, "label": "x"})
    assert note["chip"] == "From a written card"
    assert "Rev 2" in note["lines"][0]
    assert note["lines"][1].startswith("As shipped and Reset put things back the way that card")
    assert "cannot be taken back" in note["lines"][2] and "red stop sign" in note["lines"][2]
    mod = lineage.extracted_from_note({"kind": "modified", "label": "Godzilla LE 1.16"},
                                      scenes=False)
    assert mod["chip"] == "From a modified card"
    assert "modified Godzilla LE 1.16 card" in mod["lines"][0]
    assert "Scenes tab" in mod["lines"][2]
    assert lineage.extracted_from_note({"kind": "hidden"})["chip"] == "From a written card"


def _open(w, folder):
    w.run(lambda: w.window.write_assets_var.set(str(folder)))
    w.call("ui.select_tab", "scenes")
    w.call("text_scenes.select", "/g/scene1")
    _wait(w, lambda: (w.state("text_scenes").get("frames") or []) != [] and _tv(w))


def test_scenes_says_the_marks_are_guesses_until_the_card_is_read(tmp_path, monkeypatch):
    """No reading of the program's node paths: fills_proven is False.  Re-read from card reads
    the program off the card (here a stand-in that notes the paths) and the marks become the
    proven ones at once, with no reopening of the scene."""
    from pinball_decryptor.plugins.stern import engine
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    seen = {"armed": False}

    def fake_refresh(assets_dir, log=None, cancel=None, card=None):
        # the Text tab's own re-read (at open, card not at hand) reads nothing
        if seen["armed"]:
            engine._program_modes_read(assets_dir, {}, {}, ["Award_Textbox.Title"])
        return 0

    monkeypatch.setattr(engine, "refresh_program_text_flags", fake_refresh)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        tv = _tv(w)
        assert tv["fills_proven"] is False
        assert tv["base_note"] is None                 # nothing says it came off a written card
        seen["armed"] = True
        assert w.call("text_scenes.read_program") is True
        _wait(w, lambda: _tv(w).get("fills_proven") is True
              and not w.state("text_scenes").get("fills_reading"))
        assert "marked for sure" in w.state("text_scenes")["rebuild_msg"]
        layers = {l["name"] + str(l["depth"]): l["filled"] for l in _tv(w)["layers"]}
        assert layers["Title0"] is None and layers["Title1"] is not None
        w.call("text_scenes.close")


def test_a_failed_reread_keeps_the_guesses_and_says_why(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine

    def fake_refresh(assets_dir, log=None, cancel=None, card=None):
        log("The card image this project was extracted from isn't where it was (X:/gone.raw).")
        return 0

    monkeypatch.setattr(engine, "refresh_program_text_flags", fake_refresh)
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        w.answers.append("ok")
        assert w.call("text_scenes.read_program") is True
        _wait(w, lambda: not w.state("text_scenes").get("fills_reading"))
        assert _tv(w)["fills_proven"] is False
        w.call("text_scenes.close")


def test_scenes_and_as_shipped_say_the_project_came_off_a_written_card(tmp_path):
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    _lineage(folder, status="modified", rev=2)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        note = _tv(w)["base_note"]
        assert note["chip"] == "From a written card" and "Rev 2" in note["lines"][0]
        svc = w.window.service("text").scenes
        line = w.run(svc._tree_base_line, CARD)              # As shipped's question
        assert "Rev 2" in line and "cannot be taken back" in line
        w.call("text_scenes.close")


def test_a_scene_with_layers_a_write_hid_says_so_without_a_record(tmp_path):
    """No lineage, but the card's scene has a layer never drawn (PAD-535): only a Write does
    that, so the scene says it came off a written card."""
    folder = _project(tmp_path, {"original": "KAIJU!"}, two=True)
    path = folder / "images" / "scene_textures" / "scene_tree.json"
    trees = json.loads(path.read_text(encoding="utf-8"))
    from pinball_decryptor.webui.text_scenes_tree import _walk_man
    for man in trees.values():
        for n, _p, _d in _walk_man(man):
            if n.get("name") == "Title":
                n["kf"] = [[1, 0]]
                break
    path.write_text(json.dumps(trees), encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        note = _tv(w)["base_note"]
        assert note and note["head"] == "Extracted from a card a Write changed"
        w.call("text_scenes.close")


def test_the_reset_dialog_says_reset_goes_back_to_that_card(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(str(folder)))
        assert w.call("shellx.reset_open") is True
        assert w.state("shellx")["reset"]["base_note"] is None
        w.call("shellx.reset_close")
        _lineage(folder, status="modified", rev=None)
        assert w.call("shellx.reset_open") is True
        note = w.state("shellx")["reset"]["base_note"]
        assert note["head"] == "Extracted from a modified card"
        assert "Scenes tab" in note["lines"][2]
        w.call("shellx.reset_close")


def test_refresh_reads_the_card_it_is_given(tmp_path, monkeypatch):
    """Re-read from card hands the card its caller resolved (the Extract tab's, or this
    project's source for one of its builds) over the one the extract recorded."""
    from pinball_decryptor.core import text_manifest as tm
    from pinball_decryptor.plugins.stern import engine
    assets = tmp_path / "proj"
    (assets / "text").mkdir(parents=True)
    tm.save(str(assets), [{"path": "/g/game", "original": "X", "replacement": "", "budget": 1}])
    (assets / ".extract_source.json").write_text(
        json.dumps({"input_path": str(tmp_path / "gone.raw"), "size": 99}), encoding="utf-8")
    other = tmp_path / "here.raw"
    other.write_bytes(b"\0" * 4096)
    opened = []
    monkeypatch.setattr(engine, "_linux_partitions",
                        lambda p: opened.append(p) or [(0, 4096)])
    monkeypatch.setattr(engine, "_locate", lambda f, parts: (None, None, None))
    assert engine.refresh_program_text_flags(str(assets)) == 0
    assert opened == []                                   # the recorded card is gone
    assert engine.refresh_program_text_flags(str(assets), card=str(other)) == 0
    assert opened == [str(other)]
