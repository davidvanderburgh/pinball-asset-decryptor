"""PAD-857 (DragonRR): Keep size on a picture the game draws as a Shape's fill.

"Radium image scene_textures/radimg_Shape_1360x768_2838c52d.png is 6573x3712, and this
picture can't take a new size (nothing in its scene draws it by size ...)": Godzilla's map
monitor overlay is the fill of three 1360x768 Shape boxes, and the scene zooms in on it to
2x, so a bigger picture is exactly what the user wants.  The rule read the bytes for
:func:`radium_grow.image_refs` triples only, and a picture ONE Bitmap draws has none: that
Bitmap's size is the picture record's own.  71 of Godzilla's pictures drawn by one Bitmap,
and 32 box fills, were refused a new size they could take.

Measured in the emulator (stock Godzilla LE 1.16, the attract title: a 517x660 Bitmap filling
the box (422, 4, 939, 664)): grown to 1034x1320 the regrow way, the WHOLE picture is drawn
squeezed into the same box.  A Shape's rect is left, top, right, bottom.

What holds now, read off the scene's tree:

* a picture one Bitmap draws grows, and the grown scene's Bitmap is drawn at the new size;
* a Shape's fill grows, its box keeps its size, and the log says so;
* the Scenes preview squeezes a fill into its box, read as left, top, right, bottom;
* the Images tab offers Keep size for a fill and says it shows at the same size.
"""
import hashlib
import json
import os

import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.plugins.stern import (                       # noqa: E402
    dds, engine, radium_grow, scene_eval, scene_tree)
from tests.test_stern_image_grow import _Reader, _project, _writes  # noqa: E402
from tests.test_stern_scene_tree import (                           # noqa: E402
    FLAG, cls, fs, mat, node, s, sprite, u8, u32, u64)
from tests.test_stern_text_grow import RAD_PATH                     # noqa: E402

STAGE = (64, 32)
FILL, ICON = (64, 32), (16, 8)
BOX2 = (8.0, 4.0, 72.0, 36.0)          # the second box: 64x32 again, its corner at (8, 4)


def _texture(tid, w, h, rgba):
    arr = np.empty((h, w, 4), dtype=np.uint8)
    arr[:] = rgba
    blob = dds.encode_bc3(arr)
    return u32(FLAG | tid) + u32(w) + u32(h) + u32(5) + s("") + u32(len(blob)) + blob


def _scene():
    """A 64x32 stage: an overlay that fills two 64x32 Shape boxes, one at the origin and
    one at (8, 4), and an icon drawn by one Bitmap.  Returns ``(bytes, fill_off, icon_off)``."""
    kids = [
        node(50, "Overlay", [u32(1) + cls(4, "Shape") + u32(FLAG | 14) + u32(6) + s("")
                             + fs(0, 0, *FILL) + u32(0x40000000) + u32(FLAG | 16)
                             + u32(3) + s("") + u32(FILL[0]) + u32(FILL[1])
                             + _texture(20, *FILL, (30, 200, 60, 255))]),
        node(51, "OverlayAgain", [u32(1) + cls(4) + u32(FLAG | 15) + u32(6) + s("")
                                  + fs(*BOX2) + u32(0x40000000) + u32(16)]),
        node(52, "Icon", [u32(1) + cls(1, "Bitmap") + u32(FLAG | 12) + u32(3) + s("")
                          + u32(ICON[0]) + u32(ICON[1])
                          + _texture(21, *ICON, (200, 40, 40, 255))],
             tracks=((1, mat(1.0, 8, 8)),)),
    ]
    data = (u8(1) + u64(0) + u64(0) + u32(STAGE[0]) + u32(STAGE[1]) + fs(30.0)
            + fs(0, 0, 0, 1) + sprite(2, "", 1, kids))
    sc = scene_tree.parse(data)
    return data, sc.textures[20]["data_off"], sc.textures[21]["data_off"]


def test_the_scene_reads_as_a_tree_and_has_no_triples():
    data, fill, icon = _scene()
    imgs = engine.parse_radium_images(data)
    assert sorted(i["data_off"] for i in imgs) == [fill, icon]
    # neither picture is named by a triple: the byte rule refused both
    assert radium_grow.image_refs(data, fill) == []
    assert radium_grow.image_refs(data, icon) == []
    how = radium_grow.drawn_by(scene_tree.parse(data))
    # a box is left, top, right, bottom: the second one is 64x32 too, not 72x36
    assert how[20] == {"bitmaps": 1, "fills": [FILL, FILL]}
    assert how[21] == {"bitmaps": 1, "fills": []}


def _grown(tmp_path, monkeypatch, off, size, new, name):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    data = _scene()[0]
    png = _project(tmp_path, data, off, *size, name=name)
    Image.new("RGBA", new, (255, 0, 255, 255)).save(png)
    writes, n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert writes == [] and n == 1
    assert not any("can't take a new size" in m for _l, m in msgs)
    (_node, imgs), = grown.values()
    w, h, payload = imgs[off]
    assert (w, h) == new
    out = radium_grow.regrow(data, images={off: (w, h, payload)})
    assert radium_grow.agree(data, out["data"], {}, out["shift"], images={off: new})[0] == []
    return out, msgs


def test_a_picture_one_bitmap_draws_takes_a_new_size(tmp_path, monkeypatch):
    _data, _fill, icon = _scene()
    out, msgs = _grown(tmp_path, monkeypatch, icon, ICON, (30, 10), "icon")
    assert out["images"] == {icon: 0}
    sc = scene_tree.parse(out["data"])
    bm, = [o for o in sc.objects.values() if o.kind == "Bitmap" and o.body["tex"] == 21]
    assert (bm.body["w"], bm.body["h"]) == (30, 10)
    assert (sc.textures[21]["w"], sc.textures[21]["h"]) == (30, 10)
    assert not any("box" in m for _l, m in msgs)
    man = scene_eval.manifest(sc, {sc.textures[21]["data_off"]: "icon.png"})
    d, = [d for d in scene_eval.draw_list(man) if d.get("image") == "icon.png"]
    assert (d["w"], d["h"]) == (30, 10)


def test_a_fill_takes_a_new_size_and_its_box_keeps_its_own(tmp_path, monkeypatch):
    _data, fill, _icon = _scene()
    out, msgs = _grown(tmp_path, monkeypatch, fill, FILL, (128, 64), "fill")
    sc = scene_tree.parse(out["data"])
    assert (sc.textures[20]["w"], sc.textures[20]["h"]) == (128, 64)
    bm, = [o for o in sc.objects.values() if o.kind == "Bitmap" and o.body["tex"] == 20]
    assert (bm.body["w"], bm.body["h"]) == (128, 64)
    boxes = sorted(tuple(o.body["rect"]) for o in sc.objects.values() if o.kind == "Shape")
    assert boxes == [(0.0, 0.0, 64.0, 32.0), BOX2]
    said = [m for lvl, m in msgs if "box" in m]
    assert len(said) == 1 and "fills a 64x32 box in its scene, and the box keeps its size" \
        in said[0] and "128x64 pixels" in said[0]
    # the preview squeezes the bigger picture into the same boxes, where the boxes are
    man = scene_eval.manifest(sc, {sc.textures[20]["data_off"]: "fill.png"})
    got = sorted((d["m"][4], d["m"][5], d["m"][0] * d["w"], d["m"][3] * d["h"])
                 for d in scene_eval.draw_list(man) if d.get("image") == "fill.png")
    assert got == [(0.0, 0.0, 64.0, 32.0), (8.0, 4.0, 64.0, 32.0)]


def test_a_scene_that_does_not_walk_keeps_the_byte_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    data, _fill, icon = _scene()

    def refuse(_d):
        raise scene_tree.SceneTreeError("not a tree")
    monkeypatch.setattr(scene_tree, "parse", refuse)
    png = _project(tmp_path, data, icon, *ICON, name="icon")
    Image.new("RGBA", (30, 10), (255, 0, 255, 255)).save(png)
    _w, _n, _ov, grown, msgs = _writes(tmp_path, _Reader(RAD_PATH, data))
    assert grown == {}
    assert any("nothing in its scene draws it by size" in m for _l, m in msgs)


# ---------------------------------------------------------------------------------------------
# the Images tab
# ---------------------------------------------------------------------------------------------
def _manifest(data, fill, icon, fill_rel, icon_rel):
    sc = scene_tree.parse(data)
    return scene_eval.manifest(sc, {fill: fill_rel, icon: icon_rel})


def test_picture_fills_read_off_the_manifest():
    data, fill, icon = _scene()
    fills, named = scene_eval.picture_fills(_manifest(data, fill, icon, "f.png", "i.png"))
    assert fills == {"f.png": [FILL, FILL]}
    assert named == {"f.png", "i.png"}


def test_fill_boxes_across_scenes(tmp_path):
    from pinball_decryptor.webui.tabs import images
    data, fill, icon = _scene()
    tex = tmp_path / "images" / "scene_textures"
    tex.mkdir(parents=True)
    a = _manifest(data, fill, icon, "scene_textures/f.png", "scene_textures/i.png")
    # a picture that is a fill in one scene and an icon in another still names its box
    b = _manifest(data, fill, icon, "scene_textures/both.png", "scene_textures/i2.png")
    c = _manifest(data, fill, icon, "scene_textures/f3.png", "scene_textures/both.png")
    (tex / "scene_tree.json").write_text(json.dumps({"/a": a, "/b": b, "/c": c}),
                                         encoding="utf-8")
    assert images.fill_boxes(str(tmp_path)) == {"images/scene_textures/f.png": FILL,
                                                "images/scene_textures/both.png": FILL,
                                                "images/scene_textures/f3.png": FILL}


SHAPE = "images/scene_textures/radimg_Shape_64x32_2838c52d.png"
ICON_REL = "images/scene_textures/radimg_Icon_16x8_0badf00d.png"


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE", str(tmp_path / "tag_library.json"))


@pytest.fixture
def window(tmp_path):
    from tests.test_gui_image_keep_size import _scan
    from tests.webui_harness import web_app
    data, fill, icon = _scene()
    assets = tmp_path / "gz"
    tex = assets / "images" / "scene_textures"
    tex.mkdir(parents=True)
    Image.new("RGBA", FILL, (0, 0, 0, 255)).save(assets / SHAPE)
    Image.new("RGBA", ICON, (0, 0, 0, 255)).save(assets / ICON_REL)
    man = _manifest(data, fill, icon, SHAPE[len("images/"):], ICON_REL[len("images/"):])
    (tex / "scene_tree.json").write_text(json.dumps({RAD_PATH: man}), encoding="utf-8")
    (tex / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "%s\t%s\t%d\t%d\t64\t32\t5\n%s\t%s\t%d\t%d\t16\t8\t5\n"
        % (SHAPE[len("images/"):], RAD_PATH, fill, 64 * 32,
           ICON_REL[len("images/"):], RAD_PATH, icon, 16 * 8), encoding="utf-8")
    rep = tmp_path / "Retro Alien Monitor QHD - V2.png"
    Image.new("RGBA", (6573 // 50, 3712 // 50), (255, 255, 255, 255)).save(rep)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _scan(w, str(assets))
        yield w, svc, str(assets), str(rep)


def test_the_tab_says_a_kept_fill_shows_at_the_same_size(window):
    w, svc, assets, rep = window
    w.call("images.select", SHAPE)
    w.answers.append(rep)
    assert w.call("images.choose", SHAPE) == SHAPE
    keep = w.state("images")["preview"]["keep"]
    assert keep["on"] is False and "squeezed to fit" in keep["text"]
    assert w.call("images.set_keep", SHAPE, True) is not False
    assert w.state("images")["preview"]["keep"] == {"on": True, "text": (
        "Kept at 131×74 (the original is 64×32): the game draws it in the same 64×32 box, "
        "so it shows at the same size, with more detail where the scene zooms in on it.")}
    assert w.window.pending_image_assignments(assets)[2] == frozenset({SHAPE})


def test_a_picture_drawn_by_size_keeps_the_old_words(window):
    w, svc, assets, rep = window
    w.call("images.select", ICON_REL)
    w.answers.append(rep)
    assert w.call("images.choose", ICON_REL) == ICON_REL
    assert w.call("images.set_keep", ICON_REL, True) is not False
    assert w.state("images")["preview"]["keep"]["text"].endswith("the scene grows to fit it.")
    assert w.window.pending_image_assignments(assets)[2] == frozenset({ICON_REL})


# ---------------------------------------------------------------------------------------------
# DragonRR's scene (Godzilla's map, cac32730), when a copy is at hand
# ---------------------------------------------------------------------------------------------
REAL = os.path.join(os.environ.get("PAD_SCENE_DIR", r"c:\tmp\pad251"), "cac32730.radium")


def test_the_monitor_overlay_on_the_real_scene():
    if not os.path.isfile(REAL):
        pytest.skip("scene not present: %s" % REAL)
    data = open(REAL, "rb").read()
    imgs = engine.parse_radium_images(data)
    sc = scene_tree.parse(data)
    how = radium_grow.drawn_by(sc)
    tid_of = {t["data_off"]: tid for tid, t in sc.textures.items()}
    overlay, = [i for i in imgs if hashlib.md5(
        data[i["data_off"]:i["data_off"] + i["length"]]).hexdigest().startswith("2838c52d")]
    got = how[tid_of[overlay["data_off"]]]
    assert got["bitmaps"] == 1 and set(got["fills"]) == {(1360, 768)}
    # every picture a Bitmap draws can now take a new size; the triples alone missed some
    single = [i for i in imgs if not radium_grow.image_refs(data, i["data_off"], imgs)
              and how.get(tid_of[i["data_off"]], {}).get("bitmaps")]
    assert overlay in single and len(single) > 1
