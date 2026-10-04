"""PAD-352: the Scenes preview's Machine screen is for the game's pictures and
videos; a line of text passes it by and keeps its own colour.  The whole
screen overlay still reaches text, as the game draws it over everything."""

import pytest

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

ID = (1.0, 0.0, 0.0, 1.0)
INK = (250, 150, 50)


def _grey(rgb):
    """A black-and-white screen."""
    g = (rgb.astype(np.float32) @ np.asarray([0.299, 0.587, 0.114], np.float32))
    return np.repeat(np.clip(g + 0.5, 0, 255).astype(np.uint8)[..., None], 3, axis=-1)


def _blue(rgb):
    """An overlay that zeroes red."""
    out = np.array(rgb, copy=True)
    out[..., 0] = 0
    return out


@pytest.fixture
def fonts(monkeypatch):
    """One fake font whose every line is a solid INK block."""
    from pinball_decryptor.plugins.stern import fontrender as fr
    font = {"key": "f", "ascent": 4, "descent": 0}
    monkeypatch.setattr(fr, "font_at_size", lambda f, px: f)
    monkeypatch.setattr(fr, "font_fmt", lambda f: 0)
    monkeypatch.setattr(fr, "render_text",
                        lambda f, s, **k: (PIL.new("RGBA", (6, 4), INK + (255,)), []))
    return [font]


def _project(tmp_path):
    proj = tmp_path / "proj"
    tex = proj / "images" / "scene_textures"
    tex.mkdir(parents=True, exist_ok=True)
    PIL.new("RGBA", (16, 16), (40, 200, 40, 255)).save(str(tex / "stock.png"))
    return str(proj)


def _draws():
    return [{"kind": "bitmap", "image": "scene_textures/stock.png",
             "mul": (1.0, 1.0, 1.0, 1.0), "add": (0, 0, 0, 0), "m": ID + (0.0, 0.0)},
            {"kind": "text", "text": "HI", "font": "f", "font_px": 4, "rgba": (1, 1, 1, 1),
             "rect": (0, 0, 16, 8), "align": 0, "mul": (1.0, 1.0, 1.0, 1.0),
             "add": (0, 0, 0, 0), "m": ID + (0.0, 0.0)}]


def _view(overlay=None):
    def view(rgb):
        if overlay is not None:
            rgb = overlay(rgb)
        return _grey(rgb)
    view.overlay = overlay
    return view


def _ink_px(img):
    """The middle of the text block, wherever the gutter put it."""
    a = np.asarray(img).astype(int)
    hit = np.argwhere(np.abs(a[..., :3] - np.asarray(INK)).sum(-1) < 6)
    return a, hit


def test_text_keeps_its_colour_and_the_art_is_viewed(tmp_path, fonts):
    from pinball_decryptor.plugins.stern import scene_render as R
    img = R.render_tree(_project(tmp_path), {"stage": [16, 16, 30]}, draws=_draws(),
                        fonts=fonts, pictures={}, sizes={}, view=_view())
    a, hit = _ink_px(img)
    assert len(hit) >= 12                                     # the text, orange
    g = int(_grey(np.asarray([[[40, 200, 40]]], np.uint8))[0, 0, 0])
    assert tuple(a[14, 14][:3]) == (g, g, g)                  # the picture, viewed


def test_the_overlay_still_reaches_text(tmp_path, fonts):
    from pinball_decryptor.plugins.stern import scene_render as R
    img = R.render_tree(_project(tmp_path), {"stage": [16, 16, 30]}, draws=_draws(),
                        fonts=fonts, pictures={}, sizes={}, view=_view(_blue))
    a = np.asarray(img).astype(int)
    assert len(np.argwhere((a[..., 0] == 0) & (np.abs(a[..., 1] - 150) < 3)
                           & (np.abs(a[..., 2] - 50) < 3))) >= 12


def test_the_editors_layers_keep_it_too(tmp_path, fonts):
    from pinball_decryptor.plugins.stern import scene_render as R
    got = R.render_tree(_project(tmp_path), {"stage": [16, 16, 30]}, draws=_draws(),
                        fonts=fonts, pictures={}, sizes={}, view=_view(), split={1})
    for key in ("full", "sel"):
        assert len(_ink_px(got[key])[1]) >= 12, key


def test_layout_scenes_too(tmp_path, fonts):
    from pinball_decryptor.plugins.stern import scene_render as R
    layout = {"stage": [16, 16, 30],
              "sprites": [{"image": "scene_textures/stock.png", "x": 0, "y": 0}],
              "texts": [{"text": "HI", "font": "f", "rgba": (1, 1, 1, 1),
                         "rect": (0, 0, 16, 8), "align": 0, "x": 0, "y": 6}]}
    img = R.render_layout(_project(tmp_path), layout, fonts=fonts, view=_view())
    a, hit = _ink_px(img)
    assert len(hit) >= 12
    g = int(_grey(np.asarray([[[40, 200, 40]]], np.uint8))[0, 0, 0])
    assert tuple(a[14, 14][:3]) == (g, g, g)
    img = R.render_layout(_project(tmp_path), layout, fonts=fonts, view=_view(_blue))
    a = np.asarray(img).astype(int)
    assert len(np.argwhere((a[..., 0] == 0) & (np.abs(a[..., 1] - 150) < 3))) >= 12
