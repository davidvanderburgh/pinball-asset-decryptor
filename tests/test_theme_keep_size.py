"""Per-theme Keep size, and a theme's scene built as theme 1's (Simon, 2026-11-20).

Simon: a theme's picture can keep its own size ("a per-theme Keep size"), as theme 1's can. And a theme's scene is
theme 1's in everything but its pictures ("layout stays theme 1"): before, a theme's copy of a scene was the card's
scene with theme 1's in-place edits only, so a scene theme 1 GREW (a picture at its own size, longer text, the
Scenes tab's edits) lost theme 1's edits in every other theme. :func:`engine._theme_scenes` builds it the way theme
1's own is built."""
import pytest

np = pytest.importorskip("numpy")
from PIL import Image                                               # noqa: E402

from pinball_decryptor.plugins.stern import engine, mode_write, scene_variants as SV   # noqa: E402
from tests.test_pad857_fill_keep_size import FILL, ICON, _scene    # noqa: E402
from tests.test_stern_image_grow import _Reader                     # noqa: E402

RAD_PATH = "/gz/assets/" + "c" * 40 + "/scene.radium"   # a scene's card path
REL = "scene_textures/radimg_Icon_16x8_0badf00d.png"
TREL = "images/" + REL
NODE = {"size": 0, "mode": 0, "flags": 0, "i_block": b"\x42" * 8}


@pytest.fixture(autouse=True)
def _gate(monkeypatch):
    monkeypatch.setattr(engine, "_image_grow_gate", lambda d: (True, ""))
    monkeypatch.setattr(mode_write, "lookup", lambda reader, card: dict(NODE) if card == RAD_PATH else None)


def _setup(tmp_path, size=(32, 16), colour=(0, 0, 255, 255), zoom=1.0):
    data, fill_off, icon_off = _scene(zoom=zoom)
    p = tmp_path / "project"
    (p / "images" / "scene_textures").mkdir(parents=True)
    (p / "images" / "scene_textures" / "radium_images.txt").write_text(
        "# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
        "%s\t%s\t%d\t%d\t%d\t%d\t5\n" % (REL, RAD_PATH, icon_off, ICON[0] * ICON[1], ICON[0], ICON[1]),
        encoding="utf-8")
    p = str(p)
    SV.set_themes_on(p, True)
    assert SV.add_set(p, "LIGHT") == 2
    png = str(tmp_path / "blue.png")
    Image.new("RGBA", size, colour).save(png)
    SV.set_picture(p, 2, TREL, png)
    return p, data, fill_off, icon_off


def _build(tmp_path, p, data, grown_radium=None, grown_overlays=None, tree_whole=None):
    said = []
    got = engine._theme_scenes(_Reader(RAD_PATH, data), p, SV.load(p), grown_radium or {}, grown_overlays or {},
                               tree_whole or {}, str(tmp_path / "work"), lambda m, *a: said.append(m),
                               lambda: False)
    src = (got["scenes"].get(RAD_PATH) or {}).get(2)
    if src is None:
        return None, said
    with open(src["file"], "rb") as f:
        return f.read(), said


def _pictures(data):
    return {(im["tex_w"], im["tex_h"]): im for im in engine.parse_radium_images(data)}


def _rgba(data, im):
    from pinball_decryptor.plugins.stern import dds
    raw = data[im["data_off"]:im["data_off"] + im["length"]]
    return dds.decode_bc3(raw, im["pad_w"], im["pad_h"])


def test_keep_size_off_the_theme_picture_is_fitted_in_place(tmp_path):
    p, data, _fill, icon_off = _setup(tmp_path)
    assert SV.keeps_size(p, 2, TREL) is False                       # a new pick starts unticked
    out, _said = _build(tmp_path, p, data)
    assert len(out) == len(data)                                    # same size: written in place
    assert out[:icon_off] == data[:icon_off]
    assert out[icon_off:icon_off + 128] != data[icon_off:icon_off + 128]
    px = _rgba(out, _pictures(out)[ICON])
    assert tuple(px[4, 8][:3]) == (0, 0, 255)                       # the theme's blue


def test_keep_size_on_the_theme_picture_keeps_its_own_size(tmp_path):
    # the scene shows the icon at twice its box, so a picture twice its size is all used (Simon, 2026-11-21)
    p, data, _fill, _icon = _setup(tmp_path, zoom=2.0)
    SV.set_keep_size(p, 2, TREL, True)
    assert SV.keeps_size(p, 2, TREL) is True
    assert SV.keeps_size(p, 1, TREL) is False                       # theme 1's own tick is untouched
    out, said = _build(tmp_path, p, data)
    assert len(out) > len(data)                                     # the scene grew around it
    pics = _pictures(out)
    assert (32, 16) in pics and ICON not in pics
    assert any("1 at its own size" in m for m in said)


def test_theme_1_grew_the_scene_the_theme_keeps_that(tmp_path):
    """Theme 1 kept ITS fill picture at its own size (the scene grew): the theme's copy has it too, beside the
    theme's own icon. Before, the theme's copy was the card's scene: theme 1's fill was lost."""
    from tests.test_pad865_keep_size_in_box import _payload
    p, data, fill_off, _icon = _setup(tmp_path)
    w, h = FILL[0] * 2, FILL[1] * 2
    grown = {RAD_PATH: (dict(NODE), {}, {fill_off: (w, h, _payload(w, h))})}
    out, _said = _build(tmp_path, p, data, grown_radium=grown)
    pics = _pictures(out)
    assert (w, h) in pics and FILL not in pics                      # theme 1's fill, at its own size
    assert tuple(_rgba(out, pics[ICON])[4, 8][:3]) == (0, 0, 255)   # and the theme's icon


def test_the_theme_picture_replaces_theme_1s_grown_one(tmp_path):
    """Theme 1 kept the ICON at its own size; the theme picks its own icon, Keep size off: the theme's icon goes in
    at the icon's size, not theme 1's big one."""
    from tests.test_pad865_keep_size_in_box import _payload
    p, data, _fill, icon_off = _setup(tmp_path)
    grown = {RAD_PATH: (dict(NODE), {}, {icon_off: (48, 24, _payload(48, 24))})}
    out, _said = _build(tmp_path, p, data, grown_radium=grown)
    pics = _pictures(out)
    assert ICON in pics and (48, 24) not in pics
    assert tuple(_rgba(out, pics[ICON])[4, 8][:3]) == (0, 0, 255)


def test_theme_1s_in_place_edits_carry_over(tmp_path):
    """Theme 1's same-size edits of the scene (here a byte of its fill picture) are in the theme's copy."""
    p, data, fill_off, _icon = _setup(tmp_path)
    mark = bytes([0x5A] * 16)
    out, _said = _build(tmp_path, p, data, grown_overlays={NODE["i_block"]: (dict(NODE), {fill_off: mark})})
    assert out[fill_off:fill_off + 16] == mark


def test_keep_size_is_per_theme_and_goes_with_the_pick(tmp_path):
    p, _data, _fill, _icon = _setup(tmp_path)
    with pytest.raises(SV.SceneVariantError):
        SV.set_keep_size(p, 1, TREL, True)                          # theme 1's is the Images tab's own
    assert SV.add_set(p, "DARK") == 3
    with pytest.raises(SV.SceneVariantError):
        SV.set_keep_size(p, 3, TREL, True)                          # theme 3 picked nothing for it
    SV.set_keep_size(p, 2, TREL, True)
    SV.move_set(p, 2, 3)                                            # the tick moves with its theme
    assert SV.keeps_size(p, 3, TREL) is True
    SV.set_picture(p, 3, TREL, None)                                # back to theme 1's: the tick goes too
    assert SV.keeps_size(p, 3, TREL) is False
    SV.set_picture(p, 3, TREL, str(tmp_path / "blue.png"))
    assert SV.keeps_size(p, 3, TREL) is False                       # a new pick starts unticked again


def test_a_colour_only_change_follows_theme_1s_tick(tmp_path):
    from pinball_decryptor.core import staged_changes
    p, _data, _fill, _icon = _setup(tmp_path)
    SV.set_picture(p, 2, TREL, None)
    side = staged_changes.load(p)
    side["image_keep_size"] = [TREL]
    staged_changes.save(p, side)
    assert SV.keeps_size(p, 2, TREL) is True


def test_a_theme_picture_is_written_at_the_most_the_scene_shows_it(tmp_path):
    """Simon (2026-11-21): "We should be optimising for the actual screen" - a theme's own picture kept at its own
    size is written at the size the game shows it at most, like theme 1's: here its 16x8 box at 1x."""
    p, data, _fill, _icon = _setup(tmp_path, size=(160, 80))
    SV.set_keep_size(p, 2, TREL, True)
    out, said = _build(tmp_path, p, data)
    pics = _pictures(out)
    assert (160, 80) not in pics and ICON in pics
    assert any("shows it at most 16x8" in m for m in said)
