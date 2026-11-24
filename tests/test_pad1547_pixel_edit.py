"""PAD-1547: Edit pixels, the Images tab's pixel editor (Sonic's ring display
frames are 14 x 14 PNGs in graphics/Mini LED), and the smallest-PNG encoder
that keeps an edited frame inside the byte size Sonic-era JJP games hold."""

import base64
import io
import os
import random
import time

import pytest

from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")

FRAME0 = "graphics/Mini LED/Bad_Crabby/Loop/Crab00.png"
FRAME1 = "graphics/Mini LED/Bad_Crabby/Loop/Crab01.png"
SHEET = "graphics/Mini LED/Fireworks/fireworks_set.png"
BIG = "graphics/Attract/big.png"
PHOTO = "graphics/Attract/photo.jpg"


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE", str(tmp_path / "tag_library.json"))


def _noise(size, seed=1):
    rnd = random.Random(seed)
    im = Image.new("RGBA", size)
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), 255)
                for _ in range(size[0] * size[1])])
    return im


def _crab(colour):
    im = Image.new("RGBA", (14, 14), (0, 0, 0, 0))
    for y in range(3, 11):
        for x in range(3, 11):
            im.putpixel((x, y), colour)
    return im


def _project(tmp_path):
    assets = tmp_path / "sonic"
    for rel in (FRAME0, SHEET, BIG):
        (assets / rel).parent.mkdir(parents=True, exist_ok=True)
    _crab((220, 30, 60, 255)).save(assets / FRAME0)
    _crab((250, 90, 90, 255)).save(assets / FRAME1)
    Image.new("RGBA", (42, 14), (255, 200, 0, 255)).save(assets / SHEET)
    (assets / SHEET).with_suffix(".txt").write_text(
        "struct { int x, y, w, h; } sprite_rectangles[] =\n{\n"
        "\t{    0,    0,   14,   14 },\t// burst_A000\n"
        "\t{   14,    0,   14,   14 },\t// burst_A001\n"
        "\t{   28,    0,   14,   14 },\t// burst_A002\n};\n", encoding="utf-8")
    Image.new("RGBA", (300, 20), (1, 2, 3, 255)).save(assets / BIG)
    Image.new("RGB", (14, 14), (1, 2, 3)).save(assets / PHOTO)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(assets))
    return str(assets)


def _wait(w, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        st = w.state("images")
        if cond(st):
            return st
        time.sleep(0.05)
    raise AssertionError("timed out")


def _rows(st):
    out = []
    for k in range(st.get("nchunks") or 0):
        out.extend(st.get("rows_%d" % k) or [])
    return out


def _settled(st):
    rows = _rows(st)
    return (not st.get("scanning") and st.get("total") and rows
            and "still checking" not in (st.get("status") or ""))


@pytest.fixture
def jjp(tmp_path):
    assets = _project(tmp_path)
    with web_app(tmp_path, mfr="jjp") as w:
        def _do():
            try:
                w.window.write_assets_var.set(assets)
            except Exception:                            # noqa: BLE001
                pass
        w.run(_do)
        w.call("images.scan")
        st = _wait(w, _settled)
        yield w, assets, st


def _b64(im):
    return base64.b64encode(im.convert("RGBA").tobytes()).decode("ascii")


def _labels(w, rel):
    return [it.get("label") for it in w.call("images.menu", rel, [rel]) or []]


# ------------------------------------------------------------ the encoder
def test_smallest_png_is_lossless_and_never_bigger_than_pillows():
    from pinball_decryptor.core.png_small import smallest_png
    for im in (_noise((14, 14)), _crab((10, 200, 30, 255)), _noise((40, 30), 7).convert("RGB")):
        out = smallest_png(im)
        back = Image.open(io.BytesIO(out)).convert("RGBA")
        assert back.tobytes() == im.convert("RGBA").tobytes()
        buf = io.BytesIO()
        im.convert("RGBA").save(buf, "PNG", optimize=True)
        assert len(out) <= len(buf.getvalue())


def test_smallest_png_drops_alpha_when_opaque_and_blacks_out_hidden_colour():
    from pinball_decryptor.core.png_small import smallest_png
    opaque = Image.open(io.BytesIO(smallest_png(_noise((14, 14))))).mode
    assert opaque == "RGB"
    im = _crab((200, 10, 10, 255))
    im.putpixel((0, 0), (90, 80, 70, 0))              # a colour nobody can see
    back = Image.open(io.BytesIO(smallest_png(im))).convert("RGBA")
    assert back.getpixel((0, 0)) == (0, 0, 0, 0)
    assert back.getpixel((5, 5)) == (200, 10, 10, 255)


def test_the_filter_search_beats_pillow_on_a_picture_pillow_packs_badly():
    """Pillow's optimize tries one filter heuristic; the search tries them
    all (Sonic had 128 LED sheets Pillow could not get back into their slot)."""
    from pinball_decryptor.core.png_small import smallest_png
    im = Image.new("RGBA", (98, 98))
    im.putdata([((x * 3 + y * 5) & 255, (x * x + y) & 255, (x ^ y) & 255, 255)
                for y in range(98) for x in range(98)])
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG", optimize=True)
    assert len(smallest_png(im)) < len(buf.getvalue())


# ------------------------------------------------------------ helpers
def test_sprite_cell_reads_the_rectangles_table_and_falls_back_to_the_ring(tmp_path):
    from pinball_decryptor.webui.tabs.pixel_edit import sprite_cell, is_ring_picture
    (tmp_path / "set.txt").write_text("sprite_rectangles[] = { { 0, 0, 7, 7 }, { 7, 0, 7, 7 } };",
                                      encoding="utf-8")
    assert sprite_cell(str(tmp_path), (14, 7)) == [7, 7]
    assert sprite_cell(str(tmp_path / "none"), (28, 28), ring=True) == [14, 14]
    assert sprite_cell(str(tmp_path / "none"), (14, 14), ring=True) is None
    assert sprite_cell(str(tmp_path / "none"), (28, 28)) is None
    assert is_ring_picture("graphics/Mini LED/Chao/a.png")
    assert not is_ring_picture("graphics/Attract/Mini LED.png")


def test_pixel_edits_is_the_apps_own_folder():
    from pinball_decryptor.core import checksums
    assert checksums.PIXEL_EDITS_DIR in checksums.NON_ASSET_DIRS


# ------------------------------------------------------------ the tab
def test_menu_offers_edit_pixels_on_small_pngs_only(jjp):
    w, _assets, _st = jjp
    assert "Edit pixels…" in _labels(w, FRAME0)
    assert "Edit pixels…" in _labels(w, SHEET)
    assert "Edit pixels…" not in _labels(w, BIG)       # over 256 px a side
    assert "Edit pixels…" not in _labels(w, PHOTO)     # a JPEG would not save losslessly
    assert w.call("images.act", "pixel_edit", FRAME0, [FRAME0]) == {"pixel": FRAME0}
    assert w.call("images.pixel_open", BIG) is None


def test_open_gives_the_picture_its_frames_ring_and_budget(jjp):
    w, assets, _st = jjp
    sp = w.call("images.pixel_open", FRAME1)
    assert (sp["w"], sp["h"], sp["ring"], sp["edited"]) == (14, 14, True, False)
    assert sp["budget"] == os.path.getsize(os.path.join(assets, FRAME1))
    assert [f["rel"] for f in sp["frames"]] == [FRAME0, FRAME1] and sp["index"] == 1
    assert sp["cell"] is None
    px = Image.frombytes("RGBA", (14, 14), base64.b64decode(sp["data"]))
    assert px.getpixel((5, 5)) == (250, 90, 90, 255) and px.getpixel((0, 0))[3] == 0
    assert w.call("images.pixel_open", SHEET)["cell"] == [14, 14]


def test_save_makes_it_the_replacement_and_reopens_from_it(jjp):
    w, assets, _st = jjp
    w.call("images.select", FRAME0)
    edit = _crab((220, 30, 60, 255))
    edit.putpixel((5, 5), (255, 255, 255, 255))
    r = w.call("images.pixel_save", FRAME0, 14, 14, _b64(edit))
    assert r["ok"] and r["bytes"] <= r["budget"]
    path = os.path.join(assets, "Pixel edits", *FRAME0.split("/"))
    assert r["path"] == path and os.path.isfile(path)
    assert Image.open(path).convert("RGBA").tobytes() == edit.tobytes()
    assert w.call("images.pixel_bytes", 14, 14, _b64(edit), r["budget"]) == os.path.getsize(path)
    st = _wait(w, lambda s: (s.get("preview") or {}).get("has_pick"))
    assert st["preview"]["pixel"] is True
    sp = w.call("images.pixel_open", FRAME0)
    assert sp["edited"] and base64.b64decode(sp["data"]) == edit.tobytes()
    assert base64.b64decode(sp["orig"]) == _crab((220, 30, 60, 255)).tobytes()
    # the project's own folder is never listed as slots of its own
    w.call("images.scan")
    st = _wait(w, _settled)
    assert not [r for r in _rows(st) if r["r"].startswith("Pixel edits/")]


def test_saving_the_games_own_picture_drops_the_replacement(jjp):
    w, assets, _st = jjp
    edit = _crab((10, 10, 250, 255))
    assert w.call("images.pixel_save", FRAME0, 14, 14, _b64(edit))["ok"]
    r = w.call("images.pixel_save", FRAME0, 14, 14, _b64(_crab((220, 30, 60, 255))))
    assert r["ok"] and r["same"]
    assert not os.path.exists(os.path.join(assets, "Pixel edits", *FRAME0.split("/")))
    assert not w.call("images.pixel_open", FRAME0)["edited"]


def test_a_picture_too_big_for_the_jjp_slot_is_not_saved(jjp):
    w, assets, _st = jjp
    r = w.call("images.pixel_save", FRAME0, 14, 14, _b64(_noise((14, 14))))
    assert not r["ok"] and r["bytes"] > r["budget"]
    assert "Too big for this slot" in r["msg"]
    assert not os.path.exists(os.path.join(assets, "Pixel edits", *FRAME0.split("/")))
    assert not w.call("images.pixel_open", FRAME0)["edited"]
    bad = w.call("images.pixel_save", FRAME0, 13, 14, _b64(_noise((13, 14))))
    assert not bad["ok"]


def test_other_makers_have_no_byte_budget(tmp_path):
    assets = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        def _do():
            try:
                w.window.write_assets_var.set(assets)
            except Exception:                            # noqa: BLE001
                pass
        w.run(_do)
        w.call("images.scan")
        _wait(w, _settled)
        sp = w.call("images.pixel_open", FRAME0)
        assert sp["budget"] is None and sp["ring"] is False
        r = w.call("images.pixel_save", FRAME0, 14, 14, _b64(_noise((14, 14))))
        assert r["ok"] and r["budget"] is None
