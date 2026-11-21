"""Simon (2026-11-21): pictures are written for the screen, not "as big as possible".

"There has been an assumption made (mainly by me) that high res = better. This is not the case. We should be
optimising for the actual screen ... we need to allow for video and images that the game might zoom into."

What holds:

* a picture kept at its own size is written at the most the game ever shows it on the glass - its box times its
  biggest zoom, with the Scenes tab's layout on - never bigger than the picture itself (radium_grow.shown_scale,
  engine._kept_size);
* the measure is the same on a card PAD already wrote, so writing onto it again does not grow the picture (it did:
  DragonRR's V2.3 Battle Select cards 632x828 -> 1264x904 -> 2528x1808);
* a picture placed pixel for pixel (a new pick, scene_edit.PLACE_KEY) draws at its own size from the original's
  origin, and still does when the Write wrote it smaller;
* the Images tab's Original / Imported / Current / Written (picture_sizes.columns) say the same numbers;
* Origin (core/asset_origin.py) tells the official card's assets from custom ones.
"""
import json
import os

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.core import asset_origin                     # noqa: E402
from pinball_decryptor.plugins.stern import (                       # noqa: E402
    engine, picture_sizes, radium_grow, scene_edit, scene_tree)
from tests.test_pad857_fill_keep_size import FILL, ICON, _scene     # noqa: E402
from tests.test_pad865_keep_size_in_box import _m6                  # noqa: E402
from tests.test_stern_image_grow import _Reader, _project, _writes  # noqa: E402
from tests.test_stern_text_grow import RAD_PATH                     # noqa: E402

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")


# ---------------------------------------------------------------------------------------------------------------
# the measure
# ---------------------------------------------------------------------------------------------------------------
def test_the_scale_is_the_box_times_the_biggest_zoom():
    for zoom in (1.0, 2.0):
        data, fill, icon = _scene(zoom=zoom)
        sc = scene_tree.parse(data)
        # the icon's 16x8 box, a 160x80 picture fitted into it: a tenth, times the zoom
        s, left = radium_grow.shown_scale(sc, {21}, (160, 80))
        assert not left and s == pytest.approx(0.1 * zoom)
        assert radium_grow.shown_size((160, 80), s) == (int(16 * zoom), int(8 * zoom))
        # the fill's 64x32 Shape box the same
        s, _l = radium_grow.shown_scale(sc, {20}, (640, 320))
        assert s == pytest.approx(0.1 * zoom)


def test_a_picture_is_never_enlarged():
    assert radium_grow.shown_size((10, 5), 3.0) == (10, 5)
    assert picture_sizes.written_size((10, 5), 3.0) == (10, 5)
    assert picture_sizes.size_at((10, 5), 3.0) == (30, 15)          # Current says the game enlarges it


def test_a_node_its_timeline_never_shows_is_not_measured():
    from tests.test_stern_scene_tree import FLAG, cls, fs, mat, node, s, sprite, u8, u32, u64
    from tests.test_pad857_fill_keep_size import _texture
    kids = [node(52, "Icon", [u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + u32(3) + s("") + u32(ICON[0])
                              + u32(ICON[1]) + _texture(21, *ICON, (200, 40, 40, 255))],
                 tracks=((1, mat(1.0)),)),
            node(53, "Hidden", [u32(1) + cls(1) + u32(FLAG | 13) + u32(3) + s("") + u32(ICON[0]) + u32(ICON[1])
                                + u32(21)], kf=((1, 0),), tracks=((1, mat(5.0)),))]
    data = (u8(1) + u64(0) + u64(0) + u32(64) + u32(32) + fs(30.0) + fs(0, 0, 0, 1) + sprite(2, "", 1, kids))
    sc = scene_tree.parse(data)
    s_, _left = radium_grow.shown_scale(sc, {21}, ICON)
    assert s_ == pytest.approx(1.0)                                 # the hidden 5x one does not count


def test_own_size_and_own_box_nodes():
    data, _fill, _icon = _scene()
    sc = scene_tree.parse(data)
    # drawn at its own size: its scale is the node's zoom, whatever its box
    assert radium_grow.shown_scale(sc, {21}, (160, 80), own={52})[0] == pytest.approx(1.0)
    # fitted into its own box (PAD-1301)
    assert radium_grow.shown_scale(sc, {21}, (160, 80), own={52}, own_boxes={52: (32, 16)})[0] \
        == pytest.approx(0.2)


# ---------------------------------------------------------------------------------------------------------------
# the Write
# ---------------------------------------------------------------------------------------------------------------
def _write(tmp_path, monkeypatch, data, off, size, pic, name):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    png = _project(tmp_path, data, off, *size, name=name)
    pic.save(png)
    writes, n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert writes == [] and n == 1
    (_node, imgs), = grown.values()
    return imgs[off], msgs


def test_the_write_puts_it_on_at_the_most_it_is_shown(tmp_path, monkeypatch):
    data, _fill, icon = _scene(zoom=2.0)
    (w, h, payload, nat), msgs = _write(tmp_path, monkeypatch, data, icon, ICON,
                                        Image.new("RGBA", (400, 200), (9, 9, 9, 255)), "icon")
    assert (w, h) == (32, 16) and nat == (400, 200)
    said = [m for _l, m in msgs if "shows it at most 32x16" in m]
    assert len(said) == 1 and "400x200" in said[0] and "measured from the scene" in said[0]


def test_writing_onto_a_card_pad_wrote_does_not_grow_it_again(tmp_path, monkeypatch):
    """The old rule wrote twice the box of the card written onto; on a card PAD wrote, that box was the last
    Write's picture, so it doubled every time.  Box times zoom is the same on both cards."""
    data, _fill, icon = _scene(zoom=2.0)
    (w, h, payload, _nat), _m = _write(tmp_path / "a", monkeypatch, data, icon, ICON,
                                       Image.new("RGBA", (400, 200), (9, 9, 9, 255)), "icon")
    grown = radium_grow.regrow(data, images={icon: (w, h, payload)})["data"]
    card2 = radium_grow.keep_boxes(data, grown, [icon])[0]           # the card the first Write made
    sc2 = scene_tree.parse(card2)
    tex = [t for t in sc2.textures.values() if (t["w"], t["h"]) == (32, 16)][0]
    # the same picture measured on that card: the same size again, not twice it
    s2, _left = radium_grow.shown_scale(sc2, {[k for k, v in sc2.textures.items() if v is tex][0]}, (400, 200))
    assert radium_grow.shown_size((400, 200), s2) == (32, 16)


def test_a_picture_placed_pixel_for_pixel_keeps_its_size_when_written_smaller():
    """keep_boxes scales an own-size node by the picture's own size over the written one."""
    data, _fill, icon = _scene()
    from tests.test_pad865_keep_size_in_box import _payload
    grown = radium_grow.regrow(data, images={icon: (16, 8, _payload(16, 8))})["data"]
    # written at 16x8 (its box at 1x) from a 160x80 picture drawn at its own size
    out = radium_grow.keep_boxes(data, grown, [icon], own={52}, natural={icon: (160, 80)})[0]
    a, _b, _c, d, tx, ty = _m6(scene_tree.parse(out), 52)
    assert (a, d) == (10.0, 10.0) and (tx, ty) == (8.0, 8.0)         # top-left stays at the node's origin


def test_placed_nodes_come_from_the_picks(tmp_path):
    data, _fill, icon = _scene()
    png = _project(tmp_path, data, icon, *ICON, name="icon")
    rel = "images/" + os.path.relpath(str(png), str(tmp_path / "images")).replace(os.sep, "/")
    (tmp_path / ".staged_changes.json").write_text(json.dumps({scene_edit.PLACE_KEY: [rel]}), encoding="utf-8")
    assert scene_edit.placed_rels(str(tmp_path)) == {rel}
    assert scene_edit.placed_nodes(str(tmp_path), RAD_PATH, scene_tree.parse(data)) == {52}


# ---------------------------------------------------------------------------------------------------------------
# the Images tab's columns
# ---------------------------------------------------------------------------------------------------------------
def _man(zoom, box=(16, 8)):
    return {"root": {"kids": [{"id": 1, "kf": [[1, 1]], "tr": [[1, [zoom, 0, 0, zoom, 0, 0]]],
                               "comps": [[1, 10]]}]},
            "objects": {"10": {"kind": "Bitmap", "w": box[0], "h": box[1], "image": "scene_textures/a.png"}}}


def test_columns_from_a_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_edit, "trees_of", lambda d: {"card": _man(2.0)})
    rows = {"images/scene_textures/a.png": ((16, 8), (400, 200)),
            "images/boot_screen/b.png": ((1360, 768), (1920, 1080))}
    got = picture_sizes.columns(str(tmp_path), rows)
    a = got["images/scene_textures/a.png"]
    assert (a["o"], a["i"], a["c"], a["w"]) == ([16, 8], [400, 200], [32, 16], [32, 16])
    b = got["images/boot_screen/b.png"]
    assert b["fixed"] and b["w"] == [1360, 768]                     # used at exactly the original's size


def test_current_follows_the_scenes_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(scene_edit, "trees_of", lambda d: {"card": _man(1.0)})
    monkeypatch.setattr(scene_edit, "load", lambda d: {"card": [{"op": "scale", "node": 1, "s": 3.0, "px": 0,
                                                                  "py": 0}]})
    got = picture_sizes.columns(str(tmp_path / "x"), {"images/scene_textures/a.png": ((16, 8), (400, 200))})
    assert got["images/scene_textures/a.png"]["c"] == [48, 24]


# ---------------------------------------------------------------------------------------------------------------
# Origin
# ---------------------------------------------------------------------------------------------------------------
def _extract(folder, sidx, official, files, strings=()):
    os.makedirs(os.path.join(folder, "text"), exist_ok=True)
    with open(os.path.join(folder, ".checksums.md5"), "w", encoding="utf-8") as f:
        for rel, md5 in files.items():
            f.write("%s\t%s\n" % (rel, (md5 * 32)[:32]))              # an MD5's 32 hex digits
    with open(os.path.join(folder, ".pad-lineage.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "stock": {"sidx": sidx}, "source": {
            "print": "p", "status": "official" if official else "modified"}}, f)
    with open(os.path.join(folder, "text", "strings.tsv"), "w", encoding="utf-8") as f:
        for src, words in strings:
            f.write("%s\t%s\t\n" % (src, words))


def test_origin_against_an_official_extract_beside_it(tmp_path):
    _extract(str(tmp_path / "official"), "g.sidx", True,
             {"images/a.png": "1", "audio/s.wav": "2", "video/v.mp4": "3"}, [("scene", "HELLO")])
    _extract(str(tmp_path / "mine"), "g.sidx", False,
             {"images/a.png": "1", "audio/s.wav": "9", "video/v.mp4": "3", "images/new.png": "4"},
             [("scene", "HELLO"), ("scene", "MY WORDS")])
    info = asset_origin.origins(str(tmp_path / "mine"))
    assert info["custom"] == {"audio/s.wav", "images/new.png"}
    assert asset_origin.origin_of(info, "images/a.png") == "Original"
    assert asset_origin.origin_of(info, "audio/s.wav") == "Custom"
    assert asset_origin.text_origin_of(info, "scene", "MY WORDS") == "Custom"
    assert asset_origin.text_origin_of(info, "scene", "HELLO") == "Original"
    assert "official" in asset_origin.tip(info, "Original")


def test_origin_of_a_project_from_the_official_card_is_all_original(tmp_path):
    _extract(str(tmp_path / "official"), "g.sidx", True, {"audio/s.wav": "2"})
    info = asset_origin.origins(str(tmp_path / "official"))
    assert info["official"] and asset_origin.origin_of(info, "audio/s.wav") == "Original"


# ---------------------------------------------------------------------------------------------------------------
# Simon's real card
# ---------------------------------------------------------------------------------------------------------------
BATTLE_SELECT = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium"


def _real_scene():
    import struct
    from pinball_decryptor.plugins.stern import ext4, mode_write
    raw = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    if not os.path.isfile(raw):
        pytest.skip("Godzilla LE 1.16 card not present")
    with open(raw, "rb") as f:
        mbr = f.read(512)
        for i in range(4):
            e = mbr[446 + 16 * i:462 + 16 * i]
            start, n = struct.unpack("<II", e[8:16])
            if e[4] != 0x83 or n * 512 < 1 << 30:
                continue
            r = ext4.Ext4Reader(f, start * 512, n * 512)
            node = mode_write.lookup(r, BATTLE_SELECT)
            if node:
                return r.read_file_bytes(node)
    pytest.skip("Battle Select not on the card")


def test_godzillas_battle_select_on_the_real_card():
    """The numbers Simon checked: a battle card shows at most two thirds of its 527x725 box, the earth map zooms
    in to 2.01x its 1360x768 box."""
    data = _real_scene()
    sc = scene_tree.parse(data)
    by_size = {}
    for im in engine.parse_radium_images(data):
        tids = {tid for tid, t in sc.textures.items() if t["data_off"] == im["data_off"]}
        by_size.setdefault((im["tex_w"], im["tex_h"]), tids)
    card = by_size[(530, 726)]
    s, left = radium_grow.shown_scale(sc, card, (4000, 2860))
    assert not left and radium_grow.shown_size((4000, 2860), s) == (347, 248)
    earth = by_size[(1360, 768)]
    s, _left = radium_grow.shown_scale(sc, earth, (6573, 3712))
    assert radium_grow.shown_size((6573, 3712), s) == (2734, 1544)
