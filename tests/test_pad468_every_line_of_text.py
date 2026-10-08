"""PAD-468 (DragonRR): "search for all occurrences of text of any sort in scenes, be able to
correct it if needed and then move on to the next item ... with forwards and back buttons",
so spelling and placement are checked on the Scenes tab instead of in the game.

With nothing typed in the Scenes search, Previous / Next go through every line of text of
every scene (the game program's own strings are not a scene's); a line picked in the scene
editor has a Words box that changes its words where it sits, the same edit the Text tab
makes (a line added in the editor keeps its words in its own edit)."""

import pytest

from tests.test_gui_scene_editor import CARD, _seed, _open, _tv, _ops
from tests.webui_harness import web_app

pytest.importorskip("PIL")

OTHER = "/g/scene2/scene.radium"


def _project(tmp_path):
    from pinball_decryptor.core import text_manifest
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    text_manifest.save(str(folder), [
        {"path": CARD, "original": "KAIJU", "replacement": ""},
        {"path": OTHER, "original": "BALL ONE", "replacement": ""},
        {"path": OTHER, "original": "SHOOT AGAIN", "replacement": ""},
        # the game program's strings are listed as a "scene" of their own: not walked
        {"path": "/g/game", "original": "sigaction", "replacement": "", "budget": 9,
         "fixed": True},
    ])
    return folder


def _title(w):
    return next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]


def _rows(folder):
    from pinball_decryptor.core import text_manifest
    return {(r["path"], r["original"]): r["replacement"]
            for r in text_manifest.load(str(folder))}


def test_with_nothing_typed_the_arrows_walk_every_line_of_every_scene(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        sc = w.state("text_scenes")
        assert sc["search"] == ""
        # three lines in two scenes; the game program's string is left to the Text tab
        assert sc["find"] == {"pos": 0, "n": 3}
        seen = []
        for _ in range(4):
            assert w.call("text_scenes.find_step", 1) is True
            sc = w.state("text_scenes")
            seen.append((sc["sel"], sc["item"], sc["find"]["pos"]))
        assert seen == [("/g/scene1", "txt::0", 1), ("/g/scene2", "txt::0", 2),
                        ("/g/scene2", "txt::1", 3), ("/g/scene1", "txt::0", 1)]
        # in the scene editor the line is picked as its layer
        assert _tv(w)["sel"] == _title(w)
        assert w.call("text_scenes.find_step", -1) is True
        assert (w.state("text_scenes")["sel"], w.state("text_scenes")["item"]) == \
            ("/g/scene2", "txt::1")
        # typed words still narrow the walk to the lines with them (PAD-429)
        w.call("text_scenes.set_search", "shoot")
        assert w.state("text_scenes")["find"]["n"] == 1
        w.call("text_scenes.close")


def test_a_line_picked_by_hand_is_where_next_goes_on_from(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_select", _title(w))
        assert w.state("text_scenes")["find"] == {"pos": 1, "n": 3}
        # a picture leaves the place where it was
        art = next(h for h in _tv(w)["hits"] if h["name"] == "Art")["id"]
        assert w.call("text_scenes.tree_select", art)
        assert w.state("text_scenes")["find"] == {"pos": 1, "n": 3}
        assert w.call("text_scenes.find_step", 1)
        assert w.state("text_scenes")["sel"] == "/g/scene2"
        # another scene picked in the list: Next goes to its first line
        w.call("text_scenes.select", "/g/scene1")
        assert w.state("text_scenes")["find"]["pos"] == 0
        assert w.call("text_scenes.find_step", 1)
        assert w.state("text_scenes")["find"]["pos"] == 1
        w.call("text_scenes.close")


def test_the_words_box_changes_a_line_as_the_text_tab_does(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        title = _title(w)
        assert w.call("text_scenes.tree_select", title)
        words = _tv(w)["props"]["words"]
        assert words == {"text": "KAIJU", "game": "KAIJU", "edited": False, "limit": 96}
        assert w.call("text_scenes.tree_words", title, "KAIJU KING") is True
        assert _rows(folder)[(CARD, "KAIJU")] == "KAIJU KING"
        assert _tv(w)["props"]["words"]["text"] == "KAIJU KING"
        assert _tv(w)["props"]["words"]["edited"]
        # the Text tab lists the same edit
        st = w.state("text")
        assert any(r["o"] == "KAIJU" and r["n"] == "KAIJU KING" for r in st["rows"])
        # the search finds the line by the words it shows now, and still by the card's
        w.call("text_scenes.set_search", "king")
        assert [r["d"] for r in w.state("text_scenes")["scenes"]] == ["/g/scene1"]
        assert w.state("text_scenes")["find"]["n"] == 1
        w.call("text_scenes.set_search", "")
        # too long for a line: refused, after saying why
        assert w.call("text_scenes.tree_words", title, "K" * 97) is False
        assert w.asked[-1]["title"] == "Replacement too long"
        assert _rows(folder)[(CARD, "KAIJU")] == "KAIJU KING"
        # back to the game's words
        assert w.call("text_scenes.tree_select", title)
        assert w.call("text_scenes.tree_words", title, None) is True
        assert _rows(folder)[(CARD, "KAIJU")] == ""
        assert _tv(w)["props"]["words"]["edited"] is False
        # the scene's edit list is not touched by a change of words
        assert _ops(folder) == []
        w.call("text_scenes.close")


def test_a_line_added_here_is_walked_and_its_words_change_with_undo(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_select", _title(w))
        assert w.call("text_scenes.tree_add_text", "MOTHAR")
        added = _ops(folder)[-1]["id"]
        assert _tv(w)["sel"] == added
        assert _tv(w)["props"]["words"] == {"text": "MOTHAR", "added": True}
        # one more line in the walk, after the scene's own
        assert w.state("text_scenes")["find"] == {"pos": 2, "n": 4}
        assert w.call("text_scenes.tree_words", added, "MOTHRA") is True
        assert _ops(folder)[-1]["text"] == "MOTHRA"
        assert _tv(w)["props"]["words"]["text"] == "MOTHRA"
        assert w.call("text_scenes.tree_undo")
        assert _ops(folder)[-1]["text"] == "MOTHAR"
        # an added line is never emptied from here (Remove takes it away)
        assert w.call("text_scenes.tree_words", added, "  ") is False
        w.call("text_scenes.set_search", "mothar")
        assert w.state("text_scenes")["find"]["n"] == 1
        assert w.call("text_scenes.find_step", 1)
        assert _tv(w)["sel"] == added
        w.call("text_scenes.close")


def test_a_line_the_text_list_does_not_hold_has_no_words_box(tmp_path):
    """The numbers the game writes in at run time (scores, 5/10) are not in strings.tsv:
    there is nothing for the Words box to change."""
    from pinball_decryptor.core import text_manifest
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    text_manifest.save(str(folder), [{"path": OTHER, "original": "BALL ONE",
                                      "replacement": ""}])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.call("text_scenes.tree_select", _title(w))
        assert _tv(w)["props"]["words"] is None
        assert w.call("text_scenes.tree_words", _title(w), "NEW") is False
        assert w.asked[-1]["title"] == "Words"
        w.call("text_scenes.close")
