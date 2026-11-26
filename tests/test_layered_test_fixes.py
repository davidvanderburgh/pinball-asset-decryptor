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


# ---- the Scenes tab: the bar, the search, the video ----------------------------------------------------------
def test_the_dialog_starts_with_the_ticked_scenes(monkeypatch, tmp_path):
    from pinball_decryptor.webui import text_scenes as TS
    t = TS.TextScenesService.__new__(TS.TextScenesService)
    t.window = types.SimpleNamespace(current_mfr="stern")
    t.assets_dir = proj = str(tmp_path / "proj")
    os.makedirs(os.path.join(proj, "video"))
    for f in ("match.mp4", "tilt.mov", "notes.txt"):
        open(os.path.join(proj, "video", f), "wb").write(b"x")
    t._sel = "s/c"
    t._scenes = {"s/a": {"label": "A", "texts": ["MATCH"], "videos": []},
                 "s/b": {"label": "B", "texts": ["Player 1\nPlayer 2"], "videos": ["video/match.mp4"]},
                 "s/c": {"label": "C", "texts": [], "videos": []}}
    t._sorted_dirs = lambda: ["s/b", "s/a", "s/c"]
    monkeypatch.setattr(tc, "available", lambda m: True)
    tc.shared().items = [tc.Item("scene", "A", "", proj, "s/a"), tc.Item("scene", "B", "", proj, "s/b")]
    o = t.layered_options()
    assert [c["d"] for c in o["start"]] == ["s/b", "s/a"], "the ticked ones, in the list's order"
    assert o["ticked"] == ["s/b", "s/a"]
    assert {c["d"]: c["words"] for c in o["scenes"]}["s/b"] == "Player 1 Player 2"
    assert [c["file"] for c in o["clips"]] == ["match.mp4", "tilt.mov"] and o["clips"][0]["own"]
    tc.shared().items = []
    assert [c["d"] for c in t.layered_options()["start"]] == ["s/c"], "none ticked: the scene shown"


def test_the_page_has_the_bar_the_search_and_the_video_preview():
    js = open(JS, encoding="utf-8").read()
    bar = js[js.index("function LayeredBar("):]
    bar = bar[:bar.index("\n}\n")]
    assert "ticked TEST" in bar and "Starts with the scene shown" in bar and ">Layered test…<//>" in bar
    assert "${s.test_on && (s.scenes || []).length ? html`<${LayeredBar}" in js
    head = js[js.index("export function ScenesActions() {"):]
    assert "Layered test" not in head[:head.index("Export picture")], "the header button went to the bar"
    dlg = js[js.index("function LayeredDialog("):]
    dlg = dlg[:dlg.index("\nfunction LayeredBar(")]
    assert 'placeholder=${"Search " + o.scenes.length + " scenes: name, hash or the words in them"}' in dlg
    assert "words.every((w) => hay.includes(w))" in dlg
    assert "setLayers([...layers, { d: c.d" in dlg, "several can still be added"
    assert "label: c.file +" in dlg, "the video's name with its extension"
    assert '<video class="lt-preview" src=${mediaUrl(info.path)} muted loop autoplay playsinline>' in dlg
    assert 'call("text_scenes.layered_clip", clip)' in dlg and "Shown as" in dlg
    assert "<${SceneThumb} d=${c.d} />" in dlg and "<${SceneThumb} d=${l.d} />" in dlg
    css = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "css", "tabs", "text_scenes.css"),
               encoding="utf-8").read()
    assert ".lt-row { display: grid;" in css and "justify-content: start" in css


def test_adding_takes_the_ticked_scenes_off_when_asked(monkeypatch):
    from pinball_decryptor.webui import text_scenes as TS
    src = inspect.getsource(TS.TextScenesService.add_layered)
    assert "player=str(player or \"\")" in src
    assert 'lst.set_tag("scene", self.assets_dir, ly["d"], False)' in src and "if untick:" in src
