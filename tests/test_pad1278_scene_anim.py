"""PAD-1278 (DragonRR): a picture added in Scenes, animated.

The scene format gives every node a timeline of its own (keyframes, a colour track) and a
nested Sprite with no labels plays round and round, so an added picture can fade in and out,
show and fade as one of the game's lines does (its groups' fades in it), pulse, and show
several pictures in turn - on the card as in the preview.  A scene of words only (most of
Godzilla's) now takes an added picture at all.
"""
import json
import os
import zipfile

import pytest

from pinball_decryptor.plugins.stern import scene_edit as SE
from pinball_decryptor.plugins.stern import scene_eval as V
from pinball_decryptor.plugins.stern import scene_tree as T
from tests.test_stern_scene_tree import cls, fs, mat, node, sprite, text, u8, u32, u64

PIC = SE.FIRST_ADDED_ID + 1


def words_scene():
    """Words only (no Bitmap, no nested Sprite of the library): a group that fades in over
    frames 11-15 holding a line, 60 frames in all."""
    group = node(60, "Instructions", [u32(1) + cls(2, "Sprite") + u32(0x80000000 | 30)
                                      + sprite(4, "", 60, [
                                          node(61, "Line1_Instance",
                                               [u32(1) + cls(3, "Text") + u32(0x80000000 | 31)
                                                + text(5, "BOUNTY VALUE:")])])],
                 kf=((1, 0), (11, 1)),
                 colors=tuple((11 + i, (1, 1, 1, i / 4.0), (0, 0, 0, 0)) for i in range(5)))
    root = sprite(0, "", 60, [group])
    return (u8(1) + u64(0) + u64(0) + u32(1360) + u32(768) + fs(30.0) + fs(0, 0, 0, 1) + root)


@pytest.fixture
def project(tmp_path):
    from PIL import Image
    added = tmp_path / "images" / "scene_textures" / "added"
    added.mkdir(parents=True)
    for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        Image.new("RGBA", (16, 8), c + (255,)).save(str(added / ("f%d.png" % i)))
    return str(tmp_path)


def _ops(**anim):
    add = {"op": "add_picture", "parent": None, "index": 1 << 20, "id": PIC, "name": "PAD_b",
           "image": "scene_textures/added/f0.png", "w": 16, "h": 8, "x": 100, "y": 50}
    return [add, dict({"op": "anim", "node": PIC}, **anim)]


def _man():
    return V.manifest(T.parse(words_scene()))


def test_loop_maths():
    lp = SE.anim_loop({"pulse": 0.25, "period": 4,
                       "images": [{"image": "a.png"}, {"image": "b.png"}], "every": 2})
    assert lp["frames"] == 12 and lp["count"] == 3 and lp["every"] == 2   # lcm(6, 4)
    assert lp["alpha"][0] == 1.0 and lp["alpha"][2] == 0.25 and lp["alpha"][4] == 1.0
    kids = SE._loop_children(lp)
    assert kids[0][0] == [[1, 1], [3, 0], [7, 1], [9, 0]]
    assert kids[1][0] == [[1, 0], [3, 1], [5, 0], [9, 1], [11, 0]]
    assert len(kids[2][1]) == 12                       # the pulse, a key a frame
    assert SE.anim_loop({"start": 5}) is None          # no loop of its own
    assert SE.new_id({}, _ops(images=[{"image": "x"}])) == PIC + 2


def test_fade_in_and_out_on_the_scene_timeline():
    kf, col = SE._anim_timing({"start": 10, "end": 30, "fade_in": 4, "fade_out": 2}, None,
                              [[1, 1]], [])
    assert kf == [[10, 1], [31, 0]]
    assert [(f, m[3]) for f, m, _a in col] == [(10, 0.0), (11, 0.25), (12, 0.5), (13, 0.75),
                                               (14, 1.0), (28, 1.0), (29, 0.5), (30, 0.0)]
    # a picture the user hid stays hidden; a tint is kept under the fade
    kf, col = SE._anim_timing({"fade_in": 2}, None, [[1, 0]],
                              [[1, [0.5, 0.5, 0.5, 1.0], [0, 0, 0, 0]]])
    assert kf == [[1, 0]] and col[0][1] == [0.5, 0.5, 0.5, 0.0]


def test_follow_track_has_the_groups_fade_in_it():
    man = _man()
    tr = SE.follow_track(man, 61)
    assert tr[0] == [1, 0, 0.0]
    assert [k for k in tr if k[0] in (11, 13, 15)] == [[11, 1, 0.0], [13, 1, 0.5], [15, 1, 1.0]]
    assert SE.follow_track(man, 999) is None


def test_preview_follows_pulses_and_flips(project):
    man = _man()
    ops = _ops(follow=61, track=SE.follow_track(man, 61), pulse=0.0, period=4,
               images=[{"image": "scene_textures/added/f1.png", "w": 16, "h": 8}], every=2)
    m2, notes = SE.apply_manifest(man, ops)
    assert notes == []

    def pic(f):
        return [(d["image"][-6:], round(d["mul"][3], 3)) for d in V.draw_list(m2, f)
                if d["node"] == PIC]

    assert pic(5) == []                                # before the line shows
    # the loop counts from frame 11, where it first shows: the group's fade times the pulse
    assert pic(11) == [("f0.png", 0.0)]
    assert pic(13) == [("f1.png", 0.0)]                # the pulse's low point, picture 2
    assert pic(15) == [("f0.png", 1.0)]                # line fully in, pulse bright, picture 1
    assert pic(16) == [("f0.png", 0.5)]


def test_card_gets_a_looping_sprite_on_a_words_only_scene(project):
    man = _man()
    sc = T.parse(words_scene())
    ops = _ops(start=5, end=40, fade_in=2, pulse=0.5, period=10,
               images=[{"image": "scene_textures/added/f1.png", "w": 16, "h": 8},
                       {"image": "scene_textures/added/f2.png", "w": 16, "h": 8}], every=3)
    applied, notes = SE.apply_scene(sc, ops, assets_dir=project,
                                    names={61: "Line1_Instance", 60: "Instructions"})
    assert notes == [] and applied == 2
    back = T.parse(T.serialize(sc))
    assert T.serialize(back) == T.serialize(sc)
    by = {n.name: n for n, _p, _d in back.walk()}
    pic = by["PAD_b"]
    assert pic.keyframes == [(5, 1), (41, 0)]
    assert [round(m[3], 2) for _f, m, _a in pic.colors] == [0.0, 0.5, 1.0]
    (comp,) = pic.components
    spr = comp.obj
    assert spr.kind == "Sprite" and spr.body["labels"] == [] and spr.body["frames"] == 90
    assert [k.name for k in spr.body["kids"]] == ["PAD_b_1", "PAD_b_2", "PAD_b_3"]
    assert all(k.components[0].obj.kind == "Bitmap" for k in spr.body["kids"])
    assert len({k.components[0].obj.body["tex"] for k in spr.body["kids"]}) == 3
    # the preview of the written scene draws what the edit's preview drew
    m_card = V.manifest(back)
    m_prev, _n = SE.apply_manifest(man, ops)
    for f in (4, 5, 6, 9, 12, 20, 40, 41):
        card = [round(d["mul"][3], 3) for d in V.draw_list(m_card, f)
                if d["path"][:1] == ["PAD_b"]]
        prev = [round(d["mul"][3], 3) for d in V.draw_list(m_prev, f) if d["node"] == PIC]
        assert card == prev, f


def test_plain_add_picture_on_a_words_only_scene(project):
    sc = T.parse(words_scene())
    applied, notes = SE.apply_scene(sc, _ops()[:1], assets_dir=project)
    assert (applied, notes) == (1, [])
    by = {n.name: n for n, _p, _d in T.parse(T.serialize(sc)).walk()}
    assert by["PAD_b"].components[0].obj.body["sym"] == 0


def test_anim_with_nothing_puts_the_picture_back(project):
    sc = T.parse(words_scene())
    ops = _ops(pulse=0.5, period=10) + [{"op": "anim", "node": PIC}]
    SE.apply_scene(sc, ops, assets_dir=project)
    pic = {n.name: n for n, _p, _d in sc.walk()}["PAD_b"]
    assert pic.keyframes == [(1, 1)] and pic.colors == []
    assert pic.components[0].obj.kind == "Bitmap"


def test_loop_pictures_travel_in_a_saved_edits_file(project, tmp_path):
    card = "/gz/a/scene.radium"
    ops = _ops(images=[{"image": "scene_textures/added/f1.png", "w": 16, "h": 8}], every=2)
    SE.save(project, {card: ops})
    assert [r for r, _c in SE.picture_rels(ops)] == ["scene_textures/added/f0.png",
                                                     "scene_textures/added/f1.png"]
    z = str(tmp_path / "edits.zip")
    SE.export_edits(project, z)
    assert "images/scene_textures/added/f1.png" in zipfile.ZipFile(z).namelist()
    # into a project whose f1.png is another picture: the loop names the copy
    other = tmp_path / "other"
    (other / "images" / "scene_textures" / "added").mkdir(parents=True)
    from PIL import Image
    Image.new("RGBA", (4, 4), (9, 9, 9, 255)).save(
        str(other / "images" / "scene_textures" / "added" / "f1.png"))
    SE.import_edits(str(other), z)
    got = SE.load(str(other))[card]
    assert got[1]["images"][0]["image"] == "scene_textures/added/f1_2.png"
    assert os.path.isfile(str(other / "images" / "scene_textures" / "added" / "f1_2.png"))


def test_describe():
    assert SE.describe({"op": "anim", "follow": 3, "pulse": 0.4, "period": 20}) == \
        "animated: shows and fades like a game layer, pulses every 20 frames"
    assert "fades in over 5 frames" in SE.describe({"op": "anim", "fade_in": 5})


def test_scenes_window_sets_and_shows_the_animation(tmp_path):
    from PIL import Image
    from tests.webui_harness import web_app
    from tests.test_gui_scene_editor import _seed, _open, _tv, _wait, CARD
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        src = tmp_path / "logo.png"
        Image.new("RGBA", (6, 6), (200, 200, 20, 255)).save(str(src))
        w.answers = [str(src)]
        assert w.call("text_scenes.tree_add_picture")
        assert _wait(w, lambda: any(l["added"] for l in _tv(w)["layers"]))
        pid = next(l for l in _tv(w)["layers"] if l["added"])["id"]
        w.call("text_scenes.tree_select", pid)
        assert _wait(w, lambda: (_tv(w).get("props") or {}).get("anim") is not None)
        props = _tv(w)["props"]
        assert props["anim"]["images"] == [] and props["anim"]["fps"] > 0
        texts = [l for l in _tv(w)["layers"] if l["kind"] == "Text"]
        assert texts and {texts[0]["id"]} <= {c["id"] for c in props["follow_choices"]}

        def anim():
            return [o for o in SE.ops_for(str(folder), CARD) if o["op"] == "anim"]
        assert w.call("text_scenes.tree_anim", pid, {"start": "2", "fade_in": "3",
                                                     "pulse": 1.7, "period": "10"})
        assert anim() == [{"op": "anim", "node": pid, "start": 2, "fade_in": 3,
                           "pulse": 1.0, "period": 10}]
        # the box changed again: still one edit
        assert w.call("text_scenes.tree_anim", pid, {"follow": texts[0]["id"]})
        (op,) = anim()
        assert op["follow"] == texts[0]["id"] and op["track"] and "start" not in op
        assert _wait(w, lambda: _tv(w)["props"]["anim"].get("follow") == texts[0]["id"])
        # a picture shown in turn, then taken out again; the timing is kept
        frame = tmp_path / "frame2.png"
        Image.new("RGBA", (6, 6), (20, 20, 200, 255)).save(str(frame))
        w.answers = [str(frame)]
        assert w.call("text_scenes.tree_anim_picture", pid)
        (op,) = anim()
        assert op["images"][0]["image"].startswith("scene_textures/added/frame2")
        assert op["every"] == 6 and op["follow"] == texts[0]["id"]
        assert _wait(w, lambda: len(_tv(w)["props"]["anim"]["images"]) == 1)
        assert w.call("text_scenes.tree_anim_picture", pid, 0)
        (op,) = anim()
        assert "images" not in op
        assert w.call("text_scenes.tree_anim", pid, {})
        assert anim() == [{"op": "anim", "node": pid}]
        # a game layer is not animated here
        assert w.call("text_scenes.tree_anim", texts[0]["id"], {"fade_in": 3}) is False
        w.call("text_scenes.close")
