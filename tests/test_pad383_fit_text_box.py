"""PAD-383: "Fit box to text" (DragonRR: a shorter line left in its wide box ran the box off
the screen; "a single button that snaps the bounding box to the actual text").

The fit sets the Text's own rect round the ink it draws, with a small border, and the words
stay exactly where they were: the aligned edge and the top are kept (a centred line keeps its
middle), and a wrapping line keeps room for its widest line so it breaks in the same places.
The edit is a ``text_rect`` op the preview and the card apply alike."""

import pytest

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import (                                  # noqa: E402
    scene_edit as X, scene_eval as E, scene_render as R, scene_tree as T)
from tests.test_stern_scene_tree import scene                                  # noqa: E402

ID = (1.0, 0.0, 0.0, 1.0)
PAD = 3          # transparent columns each side of a fake line's ink, as a glyph cell's margin


def _ink(s):
    w = 6 * len(s) + 2 * PAD
    img = PIL.new("RGBA", (w, 10), (0, 0, 0, 0))
    img.paste((250, 150, 50, 255), (PAD, 2, w - PAD, 9))
    return img


@pytest.fixture
def fonts(monkeypatch):
    from pinball_decryptor.plugins.stern import fontrender as fr
    font = {"key": "f", "ascent": 8, "descent": 2}
    monkeypatch.setattr(fr, "font_at_size", lambda f, px: f)
    monkeypatch.setattr(fr, "font_fmt", lambda f: 0)
    monkeypatch.setattr(fr, "render_text", lambda f, s, **k: (_ink(s), []))
    return [font]


def _text(text, rect, align, flags=(0, 0)):
    return {"kind": "text", "text": text, "font": "f", "font_px": 8, "rgba": (1, 1, 1, 1),
            "rect": list(rect), "align": align, "line": 12, "ascent": 8,
            "flags": list(flags), "mul": (1.0, 1.0, 1.0, 1.0), "add": (0, 0, 0, 0),
            "m": ID + (20.0, 30.0)}


def _draw(tmp_path, d, fonts, text_edits=None):
    img = R.render_tree(str(tmp_path), {"stage": [400, 200]}, draws=[d], fonts=fonts,
                        text_edits=text_edits)
    return np.asarray(img)


def _ink_box(a):
    ys, xs = np.nonzero(a[..., :3].sum(-1))
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


@pytest.mark.parametrize("align", [0, 1, 2])
def test_the_box_goes_round_the_words_and_they_do_not_move(tmp_path, fonts, align):
    d = _text("GODZILLA VS BATTRA", (-2, -2, 340, 40), align)
    before = _draw(tmp_path, d, fonts)
    rect = R.text_fit_rect(d, fonts[0])
    fitted = dict(d, rect=rect)
    assert np.array_equal(_draw(tmp_path, fitted, fonts), before)
    # the box hugs the ink: within the margin (plus the 2 px gutter on the aligned edge)
    x0, y0, x1, y1 = _ink_box(before)
    L, T_, Rr, B = rect[0] + 20, rect[1] + 30, rect[2] + 20, rect[3] + 30
    assert L <= x0 and Rr >= x1 and B >= y1 and T_ == 28
    slack = R.FIT_MARGIN + 2 + PAD + 1
    assert x0 - L <= slack and Rr - x1 <= slack and B - y1 <= R.FIT_MARGIN + 1
    assert Rr - L < 340 - (-2)
    if align == 1:
        assert (rect[0] + rect[2]) / 2.0 == pytest.approx((-2 + 340) / 2.0)


def test_a_pending_replacement_is_what_the_box_is_fitted_to(tmp_path, fonts):
    d = _text("GODZILLA AND ANGUIRIS VS KING GHIDORAH", (-2, -2, 340, 40), 1)
    edits = {d["text"]: "VS BATTRA"}
    rect = R.text_fit_rect(d, fonts[0], edits)
    assert rect[2] - rect[0] < 6 * 9 + 2 * (R.FIT_MARGIN + PAD) + 1
    assert np.array_equal(_draw(tmp_path, dict(d, rect=rect), fonts, edits),
                          _draw(tmp_path, d, fonts, edits))


def test_a_replaced_title_with_line_breaks_is_fitted_to_the_replacement(tmp_path, fonts):
    """DragonRR, round 2: Godzilla's three-line title ("GODZILLA AND JET JAGUAR / VS. /
    MEGALON AND GIGAN") replaced with "GODZILLA VS. GIGAN" kept a three-line-tall box: the
    Text tab keys a line with breaks flat (spaces), and the fit looked it up as drawn."""
    d = _text("GODZILLA AND JET JAGUAR\nVS.\nMEGALON AND GIGAN", (-2, -2, 340, 60), 1,
              flags=(1, 0))
    edits = {"GODZILLA AND JET JAGUAR VS. MEGALON AND GIGAN": "GODZILLA VS. GIGAN"}
    rect = R.text_fit_rect(d, fonts[0], edits)
    assert rect[3] - rect[1] < 12 + R.FIT_MARGIN + 2       # one line tall, not three
    assert np.array_equal(_draw(tmp_path, dict(d, rect=rect), fonts, edits),
                          _draw(tmp_path, d, fonts, edits))


def test_a_wrapping_line_breaks_where_it_did(tmp_path, fonts):
    d = _text("SHOOT THE SWITCHES TO LIGHT THE JACKPOT", (-2, -2, 150, 80), 1, flags=(1, 0))
    before = _draw(tmp_path, d, fonts)
    rect = R.text_fit_rect(d, fonts[0])
    assert rect[2] - rect[0] < 152
    assert np.array_equal(_draw(tmp_path, dict(d, rect=rect), fonts), before)


def test_nothing_drawn_has_no_box(fonts):
    assert R.text_fit_rect(_text("", (0, 0, 50, 20), 1), fonts[0]) is None
    assert R.text_fit_rect(_text("A", (0, 0, 50, 20), 1), None) is None


def test_the_preview_and_the_card_fit_the_same_box():
    man = E.manifest(T.parse(scene()))
    ops = [{"op": "text_rect", "node": 53, "rect": [-2.0, -2.0, 60.0, 21.5]}]
    preview, notes = X.apply_manifest(man, ops)
    assert notes == []
    title = [d for d in E.draw_list(preview, 1) if d["kind"] == "text"][0]
    assert title["rect"] == pytest.approx([-2.0, -2.0, 60.0, 21.5])
    sc = T.parse(scene())
    n, notes = X.apply_scene(sc, ops, names=X.names_of(man))
    assert (n, notes) == (1, [])
    card = E.manifest(T.parse(T.serialize(sc)))
    got = [d for d in E.draw_list(card, 1) if d["kind"] == "text"][0]
    assert got["rect"] == pytest.approx([-2.0, -2.0, 60.0, 21.5])
    assert X.describe(ops[0]) == "box fitted"
    # a picture has no box to fit
    assert X.apply_scene(T.parse(scene()), [dict(ops[0], node=50)],
                         names=X.names_of(man))[0] == 0


def test_a_second_fit_replaces_the_first(tmp_path):
    a = str(tmp_path)
    X.add(a, "/c", {"op": "text_rect", "node": 5, "rect": [0, 0, 10, 10]})
    X.add(a, "/c", {"op": "text_rect", "node": 5, "rect": [0, 0, 8, 9]})
    assert X.ops_for(a, "/c") == [{"op": "text_rect", "node": 5, "rect": [0, 0, 8, 9]}]


def test_a_resized_box_turns_word_wrap_on_on_both_sides():
    """DragonRR, round 3: "Bounding box doesn't change the text size, the words shuffle to try
    to fit within the area"; a box resized by hand turns the Text's wrap flag on."""
    man = E.manifest(T.parse(scene()))
    ops = [{"op": "text_rect", "node": 53, "rect": [-2.0, -2.0, 30.0, 60.0], "wrap": True}]
    preview = X.apply_manifest(man, ops)[0]
    title = [d for d in E.draw_list(preview, 1) if d["kind"] == "text"][0]
    assert title["flags"][0] == 1 and title["rect"] == pytest.approx([-2, -2, 30, 60])
    sc = T.parse(scene())
    assert X.apply_scene(sc, ops, names=X.names_of(man)) == (1, [])
    card = E.manifest(T.parse(T.serialize(sc)))
    got = [d for d in E.draw_list(card, 1) if d["kind"] == "text"][0]
    assert got["flags"][0] == 1 and got["rect"] == pytest.approx([-2, -2, 30, 60])
    assert X.describe(ops[0]) == "box resized"


def test_a_narrower_box_wraps_the_words_at_their_size(tmp_path, fonts):
    d = _text("GODZILLA VS GIGAN", (-2, -2, 340, 40), 1)
    one = _draw(tmp_path, d, fonts)
    narrow = dict(d, rect=[-2, -2, 70, 40], flags=[1, 0])
    two = _draw(tmp_path, narrow, fonts)
    a, b = _ink_box(one), _ink_box(two)
    assert b[3] - b[1] > 2 * (a[3] - a[1])          # three lines now, not one
    assert b[2] - b[0] < a[2] - a[0]


def test_the_box_handles_and_w_h_px_size_a_texts_box_not_its_words(tmp_path):
    from tests.test_gui_scene_editor import _seed, _open, _tv, _ops
    from tests.webui_harness import web_app
    folder = tmp_path / "proj"
    folder.mkdir()
    _seed(folder)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        title = next(h for h in _tv(w)["hits"] if h["name"] == "Title")["id"]
        assert w.call("text_scenes.tree_select", title)
        p = _tv(w)["props"]
        assert w.call("text_scenes.tree_set_box", title, p["x"], p["y"], p["w"] + 40, p["h"] + 20)
        q = _tv(w)["props"]
        assert (q["x"], q["y"], q["w"], q["h"]) == (p["x"], p["y"], p["w"] + 40, p["h"] + 20)
        assert q["scale"] == 100 and q["scale_y"] == 100
        assert [o["op"] for o in _ops(folder)] == ["text_rect"] and _ops(folder)[0]["wrap"]
        # W px on a text sizes the box too (one edit: the second folds into the first)
        assert w.call("text_scenes.tree_set_pixels", title, 30, None, True)
        r = _tv(w)["props"]
        assert r["w"] == 30 and r["h"] == q["h"] and r["scale"] == 100
        assert [o["op"] for o in _ops(folder)] == ["text_rect"]
        # Size % still sizes the words
        assert w.call("text_scenes.tree_set_scale", title, 200)
        assert _tv(w)["props"]["scale"] == 200
        w.call("text_scenes.close")
