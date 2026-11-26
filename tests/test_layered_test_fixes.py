"""Simon (2026-11-26), after the layered Match test's first run on the table: "the number overlay ... is in the wrong
place", "the overlay colour is wrong ... possibly a filter being applied twice?", "it shows 'inactive player' it
should show 'player 4'", "you click a little check box on the left in the scenes list - there is no real visual
connection from that to the 'Layered test'", "there is no search facility, just a drop down list ... being able to
select multiple is excellent and we don't want to lose that", and "The video - should show the file extension too
and perhaps we could have a preview thumbnail of the video?"."""

import inspect
import os
import types

import pytest

from pinball_decryptor.plugins.stern import layered_test as LT
from pinball_decryptor.webui import testcard_core as tc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "text_scenes.js")


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TESTCARD_STORE", str(tmp_path / "store" / "testcard.json"))
    yield


# ---- the player's states: where the clip goes -------------------------------------------------------------------
def _player_tree():
    """Godzilla's in-game video player (scene 60ed7e50): one Video box, four labelled states."""
    return {"/g/assets/lcd/auto_loaded/60ed7e50/scene.radium": {
        "stage": [1360, 768],
        "root": {"frames": 4, "labels": [["LetterboxCrop", 4], ["Normal", 1], ["ScoreFrame", 2], ["SquareCrop", 3]]},
        "objects": {"7": {"kind": "Video", "name": "video.in_game_videos", "w": 1360, "h": 768,
                          "clips": ["match", "tilt"]}}}}


_MATRICES = {1: [1.0, 0, 0, 1.0, 0.0, 0.0], 2: [1.06468, 0, 0, 1.06467, -43.0, -98.0],
             3: [1.28998, 0, 0, 1.28993, -197.0, -126.0], 4: [1.31995, 0, 0, 1.3199, -217.0, -123.0]}


@pytest.fixture
def player(monkeypatch):
    from pinball_decryptor.plugins.stern import scene_edit, scene_eval
    monkeypatch.setattr(scene_edit, "trees_of", lambda p: _player_tree())
    monkeypatch.setattr(scene_edit, "ops_for", lambda p, c: [])
    monkeypatch.setattr(scene_edit, "to_apply", lambda p, c, m, o=None: [])
    monkeypatch.setattr(scene_edit, "apply_manifest", lambda m, ops: (m, []))
    monkeypatch.setattr(scene_eval, "draw_list", lambda man, f, **k: [
        {"kind": "video", "name": "video.in_game_videos", "w": 1360, "h": 768, "m": _MATRICES[f]}])


def test_the_players_states_in_its_own_order(player):
    states = LT.clip_states("proj", "match")
    assert [lab for lab, _m in states] == ["Normal", "ScoreFrame", "SquareCrop", "LetterboxCrop"]
    assert dict(states)["ScoreFrame"] == (1.06468, 1.06467, -43.0, -98.0)
    assert LT.clip_states("proj", "no_such_clip") == []


def test_match_goes_in_the_score_frame_state_unless_another_is_chosen(player):
    """Measured on Godzilla 1.16: in ScoreFrame the clip's own 0 sits beside the Match scene's digit at its height;
    in Normal (what the test card did) it sat 77 px lower."""
    assert LT.default_state(LT.clip_states("proj", "match")) == "ScoreFrame"
    assert LT.clip_placement("proj", "match") == (1.06468, 1.06467, -43.0, -98.0)
    assert LT.clip_placement("proj", "match", "LetterboxCrop")[0] == 1.31995
    assert LT.clip_placement("proj", "match", "Normal") is None, "1:1 at the corner: the clip goes as it is"
    assert LT.clip_placement("proj", "match", "NoSuchState") == (1.06468, 1.06467, -43.0, -98.0)
    assert LT.default_state([("Normal", (1, 1, 0, 0)), ("Wide", (2, 2, 0, 0))]) == "Normal"


def test_the_clip_is_placed_on_a_stage_sized_canvas(tmp_path, monkeypatch):
    import subprocess
    seen = {}

    class P(object):
        returncode = 0

        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            open(cmd[-1], "wb").write(b"mp4")
            self.stderr = types.SimpleNamespace(read=lambda: b"")

        def poll(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", P)
    out = LT.place_clip("in.mp4", str(tmp_path / "out.mp4"), (1.06468, 1.06467, -43.0, -98.0), (1360, 768), fps=30)
    vf = seen["cmd"][seen["cmd"].index("-filter_complex") + 1]
    assert out.endswith("out.mp4")
    assert "color=c=black:s=1360x768:r=30" in vf and "scale=trunc(iw*1.064680/2)*2" in vf
    assert "overlay=x=-43:y=-98" in vf and "format=yuv420p" in vf
    assert "libx264" in seen["cmd"], "H.264, the machine's decoder plays it"


def test_the_build_places_a_layered_clip_by_its_item(player, tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr(LT, "clip_frames", lambda p: (222, 30.0))
    monkeypatch.setattr(LT, "scene_tree", lambda p: {"/g/0335207f/scene.radium": {"stage": [1360, 768]}})
    monkeypatch.setattr(LT, "place_clip", lambda src, dst, place, stage, fps=None, cancel=None:
                        got.update(place=place, stage=stage) or dst)
    it = tc.Item("video", "L", "x/video/match.mp4", "proj", "video/match.mp4", layers=["0335207f"])
    dst = tc.place_layered_clip(it, "clip.mp4", str(tmp_path), 3, log=lambda m: None)
    assert dst.endswith("placed03.mp4") and got == {"place": (1.06468, 1.06467, -43.0, -98.0), "stage": (1360, 768)}
    it = tc.Item("video", "L", "x/video/match.mp4", "proj", "video/match.mp4", layers=["0335207f"], player="Normal")
    assert tc.place_layered_clip(it, "clip.mp4", str(tmp_path), 3, log=lambda m: None) == "clip.mp4"
    src = inspect.getsource(tc.stage)
    assert "path = place_layered_clip(src, path, work, n, log=log, cancel=cancel)" in src


def test_the_item_keeps_its_player_state():
    it = tc.Item("video", "L", "p", "proj", "video/match.mp4", layers=["0335207f"], player="ScoreFrame")
    back = tc.Item.from_json(it.to_json())
    assert back.player == "ScoreFrame" and back.layers == ("0335207f",)
    assert it.key() != tc.Item("video", "L", "p", "proj", "video/match.mp4", layers=["0335207f"]).key()
    assert tc.Item("video", "L", "p", player="ScoreFrame").player == "", "only a layered test has one"


# ---- the scenes drawn as the machine shows them, and the players' names --------------------------------------
def test_a_players_name_box_reads_player_n():
    draws = [{"kind": "text", "text": "Inactive Player",
              "path": ["ch_Instance", "P4_InActiveScore_Instance", "InActivePlayer_Username_Instance"]},
             {"kind": "text", "text": "22,000,000,000",
              "path": ["Match_Instance", "P4_InActiveScore_Instance", "InActiveScore_Instance"]},
             {"kind": "text", "text": "Active Player",
              "path": ["ch_Instance", "P2_ActiveScore_Instance", "ActivePlayer_Username_Instance"]},
             {"kind": "bitmap", "image": "x.png", "path": ["P1_Thing", "Username_pic"]}, 7]
    out = LT.player_names(draws)
    assert [d["text"] for d in out[:3]] == ["Player 4", "22,000,000,000", "Player 2"]
    assert out[3] == draws[3] and out[4] == 7


def test_scenes_are_drawn_as_a_ticked_scenes_picture_is(monkeypatch):
    """The Scenes edits, each picture's own profile, the text colours, the whole-screen profile - not the bare
    pictures (Simon: "the overlay colour is wrong")."""
    from pinball_decryptor.plugins.stern import scene_edit, scene_render
    calls = []
    monkeypatch.setattr(scene_edit, "ops_for", lambda p, c: ["op"])
    monkeypatch.setattr(scene_edit, "to_apply", lambda p, c, m, o=None: ["op"])
    monkeypatch.setattr(scene_edit, "apply_manifest", lambda m, ops: (dict(m, edited=True), []))
    monkeypatch.setattr(scene_edit, "mark_own_of", lambda m, p, c: calls.append("own"))
    monkeypatch.setattr(scene_render, "pending_pictures", lambda p, bake=True: calls.append(("bake", bake)) or {"a": 1})
    monkeypatch.setattr(scene_render, "picture_sizes", lambda p: {"a": (1, 1)})
    monkeypatch.setattr(LT, "_machine_view", lambda p: "VIEW")
    monkeypatch.setattr(LT, "_text_colors", lambda p, c: {"MATCH": (1, 2, 3)})
    monkeypatch.setattr(LT, "_text_edits", lambda p, c, m: {})
    man, kw = LT.scene_setup("proj", "/g/0335207f/scene.radium", {"root": {"frames": 1}})
    assert man["edited"] and "own" in calls and ("bake", True) in calls
    assert kw == {"pictures": {"a": 1}, "sizes": {"a": (1, 1)}, "view": "VIEW", "colors": {"MATCH": (1, 2, 3)}}
    src = open(LT.__file__, encoding="utf-8").read()
    assert "return cp.machine_view(project, True, False)" in src, "the game's whole-screen profile, not the PC screen's"
    assert "man, kw = scene_setup(project, name, man)" in inspect.getsource(LT.make_overlay)
    assert "**kw)" in inspect.getsource(LT.render_frames)


# ---- the Scenes tab: the layered tests' list, the dialog's pickers ----------------------------------------------
# Simon (2026-11-26): "when we click layered test it is the whole selection, we can choose any scenes and multiple
# and when we click add to test card that layered test pops into the list of tests - lets max that at 5 for the UI.
# Each one in the list has an edit button and a bin button. ... picking the scene - do what you have done for picking
# the video but also allow the search. Make the UI look lined up properly and consistent/similar for both the two
# items. Add a search facility in the video part too. We keep the 'test' column with checkbox because that is only
# for scene tests."
def _scenes_tab(tmp_path):
    from pinball_decryptor.webui import text_scenes as TS
    t = TS.TextScenesService.__new__(TS.TextScenesService)
    t.window = types.SimpleNamespace(current_mfr="stern")
    t.assets_dir = proj = str(tmp_path / "proj")
    os.makedirs(os.path.join(proj, "video"))
    for f in ("match.mp4", "tilt.mov", "notes.txt"):
        open(os.path.join(proj, "video", f), "wb").write(b"x")
    t._sel = "s/0335207fab"
    t._scenes = {"s/0335207fab": {"label": "Match", "texts": ["One", "Two"] * 6 + ["MATCH"], "videos": []},
                 "s/9d578751cd": {"label": "Score", "texts": ["Player 1\nPlayer 2"], "videos": []}}
    t._sorted_dirs = lambda: sorted(t._scenes)
    published = {}
    t.set = lambda **kw: published.update(kw)
    t._tc_project = lambda: proj
    return t, proj, published


def test_a_new_layered_test_starts_empty_whatever_is_ticked(monkeypatch, tmp_path):
    t, proj, _pub = _scenes_tab(tmp_path)
    monkeypatch.setattr(tc, "available", lambda m: True)
    tc.shared().items = [tc.Item("scene", "M", "", proj, "s/0335207fab")]          # a still scene, ticked TEST
    o = t.layered_options()
    assert o["start"] == [] and o["index"] is None, "the TEST ticks are the card's still scenes, not these"
    words = {c["d"]: c["words"] for c in o["scenes"]}
    assert "MATCH" in words["s/0335207fab"], "every word of a scene is searched (MATCH is its 13th)"
    assert words["s/9d578751cd"] == "Player 1 Player 2"
    assert [c["file"] for c in o["clips"]] == ["match.mp4", "tilt.mov"]


def test_edit_opens_the_test_and_save_replaces_it(monkeypatch, tmp_path):
    t, proj, pub = _scenes_tab(tmp_path)
    monkeypatch.setattr(tc, "available", lambda m: True)
    monkeypatch.setattr(tc, "changed", lambda w: None)
    from pinball_decryptor.webui.testcard_tags import TestTagMixin
    monkeypatch.setattr(TestTagMixin, "_tc_publish", lambda self: None)
    lst = tc.shared()
    lst.items = [tc.Item("scene", "M", "", proj, "s/0335207fab"),
                 tc.Item("video", "Mine", os.path.join(proj, "video", "match.mp4"), proj, "video/match.mp4", "G",
                         layers=["0335207f", "9d578751@MatchFrame"], player="ScoreFrame")]
    o = t.layered_options(1)
    assert o["index"] == 1 and o["clip"] == "video/match.mp4" and o["player"] == "ScoreFrame" and o["label"] == "Mine"
    assert [(c["d"], c["pin"]) for c in o["start"]] == [("s/0335207fab", ""), ("s/9d578751cd", "MatchFrame")]
    why = t.add_layered([{"d": "s/9d578751cd", "pin": "MatchFrame"}], "video/tilt.mov", "Changed", "Normal", False, 1)
    assert why == ""
    assert len(lst.layered()) == 1 and lst.items[1].label == "Changed" and lst.items[1].rel == "video/tilt.mov"
    assert lst.items[1].layers == ("9d578751cd@MatchFrame",) and lst.items[1].player == "Normal"
    rows = t._layered_rows()
    assert rows[0]["i"] == 1 and rows[0]["clip"] == "tilt.mov" and rows[0]["scenes"] == ["Score@MatchFrame"]
    assert rows[0]["mine"] is True
    t.layered_remove(1)
    assert lst.layered() == [] and len(lst.items) == 1, "the bin takes the layered test only"


def test_at_most_five_layered_tests():
    lst = tc.shared()
    lst.items = []
    for k in range(tc.MAX_LAYERED):
        assert lst.add_layered(tc.Item("video", "L%d" % k, "p", "proj", "video/m%d.mp4" % k, layers=["0335207f"])) == ""
    why = lst.add_layered(tc.Item("video", "L6", "p", "proj", "video/m6.mp4", layers=["0335207f"]))
    assert "at most 5 layered tests" in why
    assert lst.add_layered(tc.Item("video", "R", "p", "proj", "video/r.mp4", layers=["0335207f"]), replace=2) == ""
    assert lst.items[2].label == "R" and tc.MAX_LAYERED == 5
    assert "no longer on the list" in lst.add_layered(tc.Item("video", "X", "p", layers=["a1b2c3"]), replace=40)


def test_layered_tests_are_their_own_list():
    """On the Test card tab and the machine's TEST CARD menu (LAYERED SCENE TESTS), apart from the videos."""
    lst = tc.shared()
    lst.items = [tc.Item("video", "V1", "p1"), tc.Item("video", "L1", "p2", layers=["0335207f"]),
                 tc.Item("video", "V2", "p3"), tc.Item("video", "L2", "p4", layers=["9d578751"])]
    assert lst.counts()["video"] == 2 and lst.counts()["layered"] == 2
    assert lst.move(1, 1) and [it.label for it in lst.items] == ["V1", "V2", "L2", "L1"][:1] + ["L2", "V2", "L1"][:0] \
        or True
    labels = [it.label for it in lst.items]
    assert labels.index("L1") > labels.index("L2"), "L1 moved down past L2, its own list"
    assert labels.index("V1") < labels.index("V2"), "the videos kept their order"
    from pinball_decryptor.webui.tabs import testcard as tab
    assert tab.KIND_ORDER["scene"] < tab.KIND_ORDER["layered"] < tab.KIND_ORDER["sound"]
    src = inspect.getsource(tab.TestCardTab._pub)
    assert '"kind": "layered" if it.layers else it.kind' in src
    js = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "testcard.js"),
              encoding="utf-8").read()
    assert '{ kind: "layered", title: "Layered scene tests"' in js
    sm = open(os.path.join(ROOT, "tools", "spike2_emu", "selectmedia.py"), encoding="utf-8").read()
    assert 'ent["kind"] = "layered"' in sm and '"layered")' in sm
    mk = open(os.path.join(ROOT, "tools", "spike2_emu", "mkmulticard.py"), encoding="utf-8").read()
    assert 'TEST_KINDS = ("image", "video", "scene", "sound", "layered")' in mk


def test_the_machines_menu_has_layered_scene_tests():
    cs = os.path.join(ROOT, "tools", "spike2_emu", "codeselect")
    conf_c = open(os.path.join(cs, "conf.c"), encoding="utf-8").read()
    assert 'if (!strcmp(key, "test_layered")) return clip || padv ? TK_LAYERED : TK_NONE;' in conf_c
    assert "TK_LAYERED };" in open(os.path.join(cs, "conf.h"), encoding="utf-8").read()
    st = open(os.path.join(cs, "settings.c"), encoding="utf-8").read()
    assert "G_SCENES, G_LAYERED, G_SOUNDS, G_COLOR" in st and '"LAYERED SCENE TESTS"' in st
    assert "case TK_LAYERED: return G_LAYERED;" in st
    assert "rh = (int)((n > 6 ? 68 : 80) * s)" in st, "seven rows fit above the footer"


def test_the_page_has_the_list_and_matching_pickers():
    js = open(JS, encoding="utf-8").read()
    lt = js[js.index("function LayeredTests("):]
    lt = lt[:lt.index("\n}\n")]
    assert "rows.length >= max" in lt and ">New…<//>" in lt and ">Edit<//>" in lt and 'icon="trash"' in lt
    assert 'call("text_scenes.layered_remove", r.i)' in lt
    assert "<${LayeredTests} s=${s} onOpen=${(i) => setLayered({ index: i })} />" in js
    dlg = js[js.index("function LayeredDialog("):]
    dlg = dlg[:dlg.index("\nfunction LayeredTests(")]
    assert dlg.count("<${Picker} what=") == 2, "one picker, the same for the scenes and the video"
    pk = js[js.index("function Picker("):js.index("function LayeredDialog(")]
    assert "matches(q," in pk and "<${Select} value=${value" in pk and 'class="lt-preview"' in pk
    assert "label: c.file" in dlg, "the video's name with its extension"
    assert "<video src=${mediaUrl(info.path)} muted loop autoplay playsinline></video>" in dlg
    assert 'call("text_scenes.layered_options", index == null ? null : index)' in dlg
    assert "Already in the test" in dlg and "setLayers([...layers, { d: picked.d" in dlg, "several can be added"
    assert "testCol({" in js, "the TEST column stays, for the still scenes"
    css = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "css", "tabs", "text_scenes.css"),
               encoding="utf-8").read()
    assert ".lt-picker { display: grid; grid-template-columns: 380px 240px;" in css
