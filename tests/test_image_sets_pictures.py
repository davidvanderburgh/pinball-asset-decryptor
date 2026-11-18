"""A set's own pictures (Simon, 2026-11-18: "When the user selects set 2 - there will be an empty list of chosen
images. The user can then choose the variants"): kept per set, moved with the set, and made into a variant of every
scene that holds one."""
import os
import struct

import pytest

from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import scene_variants as SV

CARD = "/godzilla_le/assets/lcd/auto_loaded/" + "c" * 40 + "/scene.radium"
REL = "scene_textures/radimg_8x8_test.png"


def _scene():
    """A scene file holding one 8x8 BC3 picture (the record parse_radium_images reads), all black."""
    head = struct.pack("<9I", 8, 8, 1, 8, 8, E._DXT5_FORMAT, 0, 0, 64)
    return b"RADI" + b"\0" * 12 + head + b"\0" * 64 + b"\0" * 16, 16 + 36


def _project(tmp_path, off):
    p = tmp_path / "project"
    (p / "images" / "scene_textures").mkdir(parents=True)
    (p / "images" / "scene_textures" / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "%s\t%s\t%d\t64\t8\t8\t5\n" % (REL, CARD, off), encoding="utf-8")
    return str(p)


def _png(path, colour):
    from PIL import Image
    Image.new("RGBA", (16, 16), colour).save(path)       # another size: fitted to the place
    return str(path)


def test_set_pictures_are_kept_per_set_and_cleared(tmp_path):
    p = str(tmp_path)
    SV.add_set(p, "Dark")
    SV.set_picture(p, 2, REL, "C:/x/dark.png")
    assert SV.set_pictures(p, 2) == {REL: "C:/x/dark.png"}
    assert SV.set_pictures(p, 1) == {}
    assert SV.load(p)["images"] == {2: {REL: "C:/x/dark.png"}}
    SV.set_picture(p, 2, REL, None)
    assert SV.set_pictures(p, 2) == {}
    with pytest.raises(SV.SceneVariantError):
        SV.set_picture(p, 1, REL, "C:/x/a.png")          # set 1's pictures are the Images tab's own
    with pytest.raises(SV.SceneVariantError):
        SV.set_picture(p, 5, REL, "C:/x/a.png")          # no such set


def test_a_set_removed_or_moved_takes_its_pictures(tmp_path):
    p = str(tmp_path)
    SV.add_set(p, "Dark")
    SV.add_set(p, "Red")
    SV.set_picture(p, 3, REL, "red.png")
    SV.move_set(p, 3, 2)
    assert SV.set_names(p) == ["Standard", "Red", "Dark"]
    assert SV.set_pictures(p, 2) == {REL: "red.png"}
    SV.remove_set(p, 2)
    assert SV.set_pictures(p, 2) == {}
    assert "images" not in staged_changes.load(p)[SV.STAGED_KEY]


def test_encode_pictures_writes_the_set_picture_in_place(tmp_path):
    data, off = _scene()
    src = _png(tmp_path / "red.png", (255, 0, 0, 255))
    out, n = SV.encode_pictures(data, [(src, REL, off, 64, 8, 8, E._DXT5_FORMAT)])
    assert n == 1 and len(out) == len(data)
    assert out[:off] == data[:off] and out[off + 64:] == data[off + 64:]
    assert out[off:off + 64] != data[off:off + 64]


def test_a_place_the_scene_does_not_hold_is_left(tmp_path):
    data, off = _scene()
    src = _png(tmp_path / "red.png", (255, 0, 0, 255))
    said = []
    out, n = SV.encode_pictures(data, [(src, REL, off + 4, 64, 8, 8, E._DXT5_FORMAT)],
                                lambda m, *a: said.append(m))
    assert n == 0 and out == data and "not where the Extract found it" in said[0]


def test_picture_variants_make_a_scene_file_for_the_set(tmp_path):
    data, off = _scene()
    p = _project(tmp_path, off)
    SV.add_set(p, "Dark")
    SV.set_picture(p, 2, REL, _png(tmp_path / "dark.png", (10, 10, 40, 255)))
    sets = SV.load(p)
    said = []
    got = SV.picture_variants(p, sets, lambda card: data if card == CARD else None, str(tmp_path / "work"),
                              lambda m, *a: said.append(m))
    src = got["scenes"][CARD][2]
    assert SV.variant_source(p, src)[0] == "file"
    with open(src["file"], "rb") as f:
        assert f.read() != data
    assert any("1 picture(s) of its own (chosen or colour profiled), in 1 scene(s)" in m for m in said)


def test_the_images_tabs_own_name_finds_the_picture(tmp_path):
    """Simon: every scene picture said "not inside a scene" - the Images tab names it from the project folder."""
    data, off = _scene()
    p = _project(tmp_path, off)
    assert SV.picture_rows(p)["images/" + REL] == SV.picture_rows(p)[REL]
    SV.add_set(p, "Light")
    SV.set_picture(p, 2, "images/" + REL, _png(tmp_path / "light.png", (240, 240, 240, 255)))
    got = SV.picture_variants(p, SV.load(p), lambda card: data, str(tmp_path / "work"))
    assert got["scenes"][CARD][2]["file"].endswith(".radium")


def test_a_picture_outside_any_scene_is_left_out_and_said(tmp_path):
    data, off = _scene()
    p = _project(tmp_path, off)
    SV.add_set(p, "Dark")
    SV.set_picture(p, 2, "boot_screen/boot.png", _png(tmp_path / "boot.png", (0, 0, 0, 255)))
    said = []
    got = SV.picture_variants(p, SV.load(p), lambda card: data, str(tmp_path / "work"), lambda m, *a: said.append(m))
    assert got["scenes"] == {}
    assert any("not inside a scene" in m for m in said)


def test_an_own_scene_file_wins_over_pictures(tmp_path):
    data, off = _scene()
    p = _project(tmp_path, off)
    SV.add_set(p, "Dark")
    SV.set_picture(p, 2, REL, _png(tmp_path / "dark.png", (10, 10, 40, 255)))
    side = staged_changes.load(p)
    side[SV.STAGED_KEY]["scenes"] = {CARD: {"2": {"file": "mine.radium"}}}
    staged_changes.save(p, side)
    got = SV.picture_variants(p, SV.load(p), lambda card: data, str(tmp_path / "work"))
    assert got["scenes"][CARD][2] == {"file": "mine.radium"}
    assert not os.path.isdir(str(tmp_path / "work")) or not os.listdir(str(tmp_path / "work"))
