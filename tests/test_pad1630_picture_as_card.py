"""PAD-1630 (reopened): a PICTURE in the card's place.

Dustin's session log on v1.630.1 showed what the redacted report hid: the
first image's "card" was images/iron_maiden_le/assets/lcd/GameLogo.png.
The container read it fine - it is a PNG, and a PNG has no MBR - so the
selector, the size check and the preview all failed on it.  It got there
through Edit image…, whose only drop target with the game's own logo
showing is Replace image…, and nothing anywhere asked whether a row's file
was a card rather than only whether it was there.
"""

import os

from PIL import Image

from pinball_decryptor.webui import multiboot_core as mt
from tests.webui_harness import web_app
from tests.test_webui_multiboot import (  # noqa: F401  (autouse fixture)
    _no_tools, _raw, _add, _st, _panel)


def _png(tmp_path, name="GameLogo.png"):
    d = tmp_path / "images" / "iron_maiden_le" / "assets" / "lcd"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    Image.new("RGB", (32, 18), (200, 30, 30)).save(p, format="PNG")
    return str(p)


def test_media_kind_by_name_and_by_bytes(tmp_path):
    png = _png(tmp_path)
    bare = tmp_path / "logo_without_extension"
    bare.write_bytes(open(png, "rb").read())
    raw = _raw(tmp_path, "iron_maiden_le-1_18_0.Release.8G.sdcard.raw")
    wav = tmp_path / "x.dat"
    wav.write_bytes(b"RIFF\0\0\0\0WAVEfmt ")
    assert mt.file_media_kind(png) == "picture"
    assert mt.file_media_kind(str(bare)) == "picture"
    assert mt.file_media_kind(str(wav)) == "sound"
    assert mt.file_media_kind(str(tmp_path / "clip.MP4")) == "video"
    assert mt.file_media_kind(raw) == ""
    assert mt.file_media_kind(str(tmp_path / "missing.raw")) == ""
    why = mt.not_card_reason(png, mt.BACKENDS["stern"])
    assert why.startswith("GameLogo.png is a picture, not a card image.")
    assert "Picture" in why
    assert mt.not_card_reason(raw, mt.BACKENDS["stern"]) == ""
    assert mt.not_card_reason("", mt.BACKENDS["stern"]) == ""


def test_the_form_names_a_picture_where_a_card_goes(tmp_path):
    """Dustin's list: image 0 a logo, image 1 his build.  Every check that
    gates the preview, the Build and the update says so, with or without
    the sources being checked."""
    png = _png(tmp_path)
    build = _raw(tmp_path, "iron_maiden_le-1_18_0.Release.8G.sdcard-modified.raw")
    form = mt.MultibootForm(images=[mt.ImageRow(path=png, title="Iron Maiden"),
                                    mt.ImageRow(path=build, title="Iron Maiden")])
    for sources in (True, False):
        errs = mt.validate_form(form, sources=sources)
        assert any(e.startswith("Image 0: GameLogo.png is a picture, not a "
                                "card image.") for e in errs), errs
    good = mt.MultibootForm(images=[
        mt.ImageRow(path=_raw(tmp_path, "a.raw")), mt.ImageRow(path=build)])
    assert not any("is a picture" in e for e in mt.validate_form(good))


def test_add_image_refuses_a_picture(tmp_path):
    png = _png(tmp_path)
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, png)
        panel = _panel(w)
        assert [r.path for r in panel._rows] == [a]


def test_a_logo_through_replace_image_becomes_the_picture(tmp_path):
    """The way it happened: a logo dropped on Edit image… (the drop arms
    Replace image…'s picker).  The card file stays, the logo is the
    image's Picture, and the form is still good."""
    png = _png(tmp_path)
    stock = _raw(tmp_path, "iron_maiden_le-1_18_0.Release.8G.sdcard.raw")
    build = _raw(tmp_path, "iron_maiden_le-1_18_0.Release.8G.sdcard-modified.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, stock)
        _add(w, build)
        panel = _panel(w)
        w.call("multiboot.edit", 0)
        w.answers.append(png)
        assert w.call("multiboot.edit_replace") is True
        s = _st(w)
        assert s["ed"]["source"] == stock
        assert s["ed_picture"] == png
        assert s["ed"]["kind"] == "picture"
        w.call("multiboot.edit_ok")
        s = _st(w)
        assert [r.path for r in panel._rows] == [stock, build]
        assert s["rows"][0]["media"] == "GameLogo.png"
        assert mt.validate_form(panel.form()) == []


def test_replace_image_itself_refuses_a_picture(tmp_path):
    png = _png(tmp_path)
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        panel = _panel(w)
        assert panel.replace_image(png, index=0) is False
        assert panel._rows[0].path == a


def test_the_size_check_does_not_hand_a_picture_to_the_tool(tmp_path):
    """A list saved before this (Dustin's) still names the logo: the size
    check stays unknown instead of running 'plan --primary GameLogo.png'
    (the autouse fixture fails the test if any tool is started)."""
    png = _png(tmp_path)
    a = _raw(tmp_path, "a_pro-1_59_0.Release.8G.sdcard.raw")
    b = _raw(tmp_path, "b_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _add(w, a)
        _add(w, b)
        panel = _panel(w)
        panel._rows[0].path = png
        panel._auto_plan = True
        assert panel._plan_now() is False


def test_a_random_card_refuses_a_picture_among_its_games(tmp_path):
    png = _png(tmp_path)
    form = mt.MultibootForm(images=[
        mt.ImageRow(path=_raw(tmp_path, "a.raw")),
        mt.ImageRow(path="", members=[mt.MemberRow(path=_raw(tmp_path, "b.raw")),
                                      mt.MemberRow(path=png)])])
    errs = mt.validate_form(form)
    assert any(e.startswith("Image 1, game 2: GameLogo.png is a picture")
               for e in errs), errs
    assert os.path.isfile(png)
