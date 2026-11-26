"""PAD-1612: JJP gets the Replace Images tab, as Stern has it.

A JJP extract's pictures are loose files (graphics/, ecoredata/) that the
changed-file repack already re-encrypts, so the tab stages a pick over the
extracted file like every other Replace tab.  The Scenes tab (and the Images
tab's Fonts… / Group by scene) used to follow replace_image alone; it now
has its own switch, since JJP's pictures sit in no scene trees.

On a Sonic-era image every asset keeps its byte size, and a picture re-saved
by the tab (or by hand) often comes out bigger, so the encrypt step squeezes
a PNG or JPEG down before padding it onto the slot.
"""
import io
import os
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import registry
from pinball_decryptor.plugins.jjp import crypto_v3 as v3
from pinball_decryptor.plugins.jjp import pipeline as P
from tests.test_jjp_write_integrity import SONIC_PATH, _pinned_slot

PIL = pytest.importorskip("PIL.Image")

SONIC_JPG = "/jjpe/gen1/Sonic/edata/graphics/UI/backdrop.jpg"


def _gates(mfr):
    from pinball_decryptor.webui.window import WebWindow
    me = SimpleNamespace(modes_preview_on=lambda mfr=None: False,
                         vpx_preview_on=lambda: False)
    return WebWindow._gate(me, mfr)


def _mfr(key):
    import pinball_decryptor.plugins  # noqa: F401  (registers them)
    m = registry.get_manufacturer(key)
    if m is None:
        pytest.skip("no %s plugin" % key)
    return m


def _noise(w, h, mode="RGB", seed=7):
    import random
    rnd = random.Random(seed)
    im = PIL.new(mode, (w, h))
    n = len(mode)
    im.putdata([tuple(rnd.randrange(256) for _ in range(n))
                for _ in range(w * h)])
    return im


def _encode(im, fmt, **kw):
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def _pixels(data):
    with PIL.open(io.BytesIO(data)) as im:
        im.load()
        return im.convert("RGBA").tobytes(), im.size


# ------------------------------------------------------------- the tabs
def test_jjp_shows_replace_images_but_no_scenes():
    gates = _gates(_mfr("jjp"))
    assert gates["Replace Images"]
    assert gates["Replace Audio"] and gates["Replace Video"]
    assert not gates["Scenes"]
    assert gates["Color Profile"]          # it had that already (videos)


@pytest.mark.parametrize("era", ["spike2", "spike3"])
def test_stern_keeps_its_scenes_tab(era):
    stern = _mfr("stern")
    old = getattr(stern, "era", None) or "spike2"
    stern.set_era(era)
    try:
        gates = _gates(stern)
        assert gates["Replace Images"] and gates["Scenes"]
    finally:
        stern.set_era(old)


def test_the_images_page_hides_the_scene_tools_on_jjp(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path, mfr="jjp") as w:
        assert w.state("images")["scenes"] is False
    with web_app(tmp_path / "s", mfr="stern") as w:
        assert w.state("images")["scenes"] is True


def test_the_page_gates_fonts_and_group_by_on_scenes():
    js = open(os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor",
                           "webui", "static", "js", "tabs", "images.js"),
              encoding="utf-8").read()
    assert js.count("s.shades_only || !s.scenes ? null") == 2


def test_jjp_lists_the_game_pictures_not_the_os_dump(tmp_path):
    for d in ("graphics/UI", "ecoredata/graphics", "system/usr/share/icons",
              ".write_cache"):
        (tmp_path / d).mkdir(parents=True)
    for f in ("graphics/UI/a.png", "ecoredata/graphics/b.png",
              "system/usr/share/icons/c.png", ".write_cache/d.png"):
        (tmp_path / f).write_bytes(_encode(_noise(4, 4), "PNG"))
    jjp = _mfr("jjp")
    from pinball_decryptor.core.image_slots import scan_image_slots
    slots = scan_image_slots(str(tmp_path),
                             roots=jjp.image_slot_dirs(str(tmp_path)),
                             probe=False)
    assert [s.rel_path for s in slots] == ["ecoredata/graphics/b.png",
                                          "graphics/UI/a.png"]
    assert "byte size" in jjp.image_note()


# ------------------------------------------------------ the pinned fit
@pytest.mark.parametrize("extra", [4, 5, 7, 100, 65537, 65538, 65540,
                                   65541, 200003])
def test_a_jpeg_is_padded_to_any_size_four_or_more_bytes_up(extra):
    jpg = _encode(_noise(16, 16), "JPEG", quality=90)
    out = P.fit_jpeg_to_size(jpg, len(jpg) + extra)
    assert out is not None and len(out) == len(jpg) + extra
    assert _pixels(out) == _pixels(jpg)


@pytest.mark.parametrize("extra", [-1, 1, 2, 3])
def test_a_jpeg_too_big_or_one_to_three_short_is_not_padded(extra):
    jpg = _encode(_noise(16, 16), "JPEG", quality=90)
    assert P.fit_jpeg_to_size(jpg, len(jpg) + extra) is None
    assert P.fit_jpeg_to_size(jpg, len(jpg)) == jpg


@pytest.mark.parametrize("ext,fmt", [(".png", "PNG"), (".jpg", "JPEG")])
def test_a_picture_bigger_than_its_slot_is_squeezed_then_padded(ext, fmt):
    """An edited picture re-saved bigger than the original: squeezed (fewer
    colours / lower quality) and then padded onto the exact byte count."""
    im = _noise(48, 48)
    big = _encode(im, fmt, **({"quality": 98} if fmt == "JPEG" else {}))
    target = len(big) // 2
    logs = []
    out = P.fit_picture_to_size(big, target, ext,
                                log=lambda t, l="info": logs.append(t))
    assert out is not None and len(out) == target
    with PIL.open(io.BytesIO(out)) as got:
        got.load()
        assert got.size == (48, 48) and got.format == fmt
    assert any("Squeezed from %d" % len(big) in t for t in logs)


def test_a_picture_that_cannot_shrink_far_enough_is_left_alone():
    big = _encode(_noise(48, 48), "PNG")
    assert P.fit_picture_to_size(big, 40, ".png") is None


@pytest.mark.parametrize("path,fmt", [(SONIC_PATH, "PNG"),
                                      (SONIC_JPG, "JPEG")])
def test_a_sonic_era_slot_takes_a_bigger_picture(path, fmt):
    """Through the real encrypt step: the slot keeps its byte size, and what
    went in decodes as a picture of the slot's shape."""
    entry, read_original = _pinned_slot(path, orig_len=3000, lead=216)
    slot = len(v3.decrypt_file(read_original(entry), 216, path, "Sonic"))
    big = _encode(_noise(40, 40), fmt,
                  **({"quality": 98} if fmt == "JPEG" else {}))
    assert len(big) > slot
    out, note, written = P._encrypt_one(v3.SCHEME_V3, entry, big, "Sonic",
                                        read_original)
    assert len(written) == slot and "refitted" in note
    assert v3.decrypt_file(out, 216, path, "Sonic") == written
    with PIL.open(io.BytesIO(written)) as got:
        got.load()
        assert got.size == (40, 40) and got.format == fmt
