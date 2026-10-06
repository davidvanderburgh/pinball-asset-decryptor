"""PAD-412: a line of text sits in its box where the machine puts it (DragonRR: "the text
bounding box ... stretched down into the text below it in PAD ... in game the text moves to
the bottom of that box. ... make sure the text always looks like it will in the game").

The game names a Text's layout fields itself (ScaleToBounds, VerticalAlignment, Bounds,
Multiline, WordWrap, LineSpacing, LetterSpacing); every rule below was measured on the
emulator (Godzilla LE 1.16's language screen, added Texts in 402 px tall boxes):

- VerticalAlignment (the record's last u32): 0 top, 1 middle, 2 bottom of the box;
- ScaleToBounds (the byte before it): the words shrink, never grow, to fit the box;
- Multiline (flag byte 0): off drops the line breaks; WordWrap (flag byte 1) breaks lines at
  the box's width - the first byte alone never wrapped a line;
- the line step is the declared line height plus LineSpacing (the first spacing float)."""

import os

import pytest

PIL = pytest.importorskip("PIL.Image")
np = pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import (                                  # noqa: E402
    scene_edit as X, scene_eval as E, scene_render as R, scene_tree as T)
from tests.test_pad383_fit_text_box import _draw, _ink_box, _text, fonts      # noqa: E402,F401
from tests.test_stern_scene_tree import scene                                  # noqa: E402


def _rows(a):
    """The ink's row runs (one per line of text)."""
    ys = np.nonzero(a[..., :3].sum(-1).sum(-1))[0]
    return [(r[0], r[-1]) for r in np.split(ys, np.where(np.diff(ys) > 1)[0] + 1)]


def test_the_vertical_alignment_puts_the_lines_at_the_top_middle_or_bottom(tmp_path, fonts):
    box = (-2, -2, 200, 120)                 # 122 tall; three 12 px lines take 36
    top = _text("ALPHA\nBRAVO\nCHARLIE", box, 1, flags=(1, 0))
    rows = {v: _rows(_draw(tmp_path, dict(top, valign=v), fonts)) for v in (0, 1, 2)}
    assert [len(r) for r in rows.values()] == [3, 3, 3]
    first = {v: r[0][0] for v, r in rows.items()}
    # bottom: the last line's declared height ends on the box's bottom; top: 2 px under its top
    block = 2 * 12 + 12
    assert first[2] - first[0] == pytest.approx((box[3] - block) - (box[1] + 2), abs=1)
    assert first[1] - first[0] == pytest.approx((first[2] - first[0]) / 2.0, abs=1)


def test_line_spacing_adds_to_the_declared_line_height(tmp_path, fonts):
    d = _text("ALPHA\nBRAVO", (-2, -2, 200, 120), 1, flags=(1, 0))
    plain = _rows(_draw(tmp_path, d, fonts))
    spaced = _rows(_draw(tmp_path, dict(d, spacing=[5.0, 0.0]), fonts))
    assert plain[1][0] - plain[0][0] == 12
    assert spaced[1][0] - spaced[0][0] == 17


def test_multiline_off_runs_the_lines_together(tmp_path, fonts):
    """Emulator: "ALPHA\\nBRAVO\\nCHARLIE" with flags 0 0 drew ALPHABRAVOCHARLIE."""
    d = _text("ALPHA\nBRAVO\nCHARLIE", (-2, -2, 300, 120), 1, flags=(0, 0))
    a = _draw(tmp_path, d, fonts)
    assert len(_rows(a)) == 1
    x0, _y0, x1, _y1 = _ink_box(a)
    assert x1 - x0 == 6 * len("ALPHABRAVOCHARLIE")


def test_only_the_word_wrap_byte_wraps(tmp_path, fonts):
    """Emulator: "WRAP ME INTO SOME LINES PLEASE" in a 302 px box drew one long line with
    flags 1 0 and three lines with flags 1 1."""
    d = _text("WRAP ME INTO SOME LINES PLEASE", (-2, -2, 70, 120), 1)
    assert len(_rows(_draw(tmp_path, dict(d, flags=[1, 0]), fonts))) == 1
    assert len(_rows(_draw(tmp_path, dict(d, flags=[1, 1]), fonts))) > 2
    assert len(_rows(_draw(tmp_path, dict(d, flags=[0, 1]), fonts))) > 2


def test_a_line_broken_at_a_space_is_centred_with_the_space_on():
    measure = len
    assert R.text_lines("AB CD EF", 5, True, measure) == ["AB CD", "EF"]
    assert R.text_lines("AB CD EF", 5, True, measure, keep_space=True) == ["AB CD ", "EF"]


def test_scale_to_bounds_shrinks_the_words_to_the_box_and_never_grows_them(tmp_path, fonts):
    long = _text("A MUCH LONGER LINE THAT IS SHRUNK", (-2, -2, 100, 120), 1)
    a = _draw(tmp_path, long, fonts)
    b = _draw(tmp_path, dict(long, fit=1), fonts)
    wa, wb = _ink_box(a), _ink_box(b)
    assert wa[2] - wa[0] > 102 and wb[2] - wb[0] <= 102
    short = _text("HI", (-2, -2, 100, 120), 1)
    assert np.array_equal(_draw(tmp_path, dict(short, fit=1), fonts),
                          _draw(tmp_path, short, fonts))
    # three lines in a box too short for them shrink to its height
    tall = _text("ONE\nTWO\nSIX", (-2, -2, 100, 16), 1, flags=(1, 0))
    rows = _rows(_draw(tmp_path, dict(tall, fit=1), fonts))
    assert len(rows) == 3 and rows[-1][1] - rows[0][0] < 3 * 12


@pytest.mark.parametrize("valign", [1, 2])
def test_fit_box_to_text_keeps_a_middle_or_bottom_line_where_it_is(tmp_path, fonts, valign):
    d = dict(_text("GODZILLA\nVS.\nMEGAGUIRUS", (-2, -2, 200, 160), 1, flags=(1, 0)),
             valign=valign)
    before = _draw(tmp_path, d, fonts)
    rect = R.text_fit_rect(d, fonts[0])
    assert rect[3] - rect[1] < 160 - (-2)
    assert np.array_equal(_draw(tmp_path, dict(d, rect=rect), fonts), before)


def test_the_manifest_carries_scale_to_bounds_and_vertical_alignment():
    sc = T.parse(scene())
    texts = [o for o in sc.objects.values() if o.kind == "Text"]
    texts[0].body["tail"] = (1, 2)
    m = E.manifest(T.parse(T.serialize(sc)), {})
    assert m["v"] == E.MANIFEST_VERSION >= 4
    got = [o for o in m["objects"].values() if o.get("kind") == "Text"]
    assert [(o["fit"], o["valign"]) for o in got][:1] == [(1, 2)]
    draws = [d for d in E.draw_list(m, 1) if d["kind"] == "text"]
    assert draws and all("fit" in d and "valign" in d for d in draws)


def test_a_resized_box_wraps_on_the_machine_too():
    """The corner handles re-flow the words (PAD-383 round 3); the card now gets WordWrap as
    well as Multiline, so the machine re-flows them as the preview does."""
    man = E.manifest(T.parse(scene()))
    ops = [{"op": "text_rect", "node": 53, "rect": [-2.0, -2.0, 30.0, 60.0], "wrap": True}]
    sc = T.parse(scene())
    assert X.apply_scene(sc, ops, names=X.names_of(man)) == (1, [])
    texts = [o for o in T.parse(T.serialize(sc)).objects.values() if o.kind == "Text"]
    assert any(tuple(o.body["flags"]) == (1, 1) for o in texts)


# ---------------------------------------------------------------------------------------------
# the emulator's own pixels (skipped without the PAD-412 rig's Godzilla project copy)
# ---------------------------------------------------------------------------------------------
PROJ = r"C:\tmp\pad412\proj"
#: (text, flags, (fit, valign), box width, box height) -> the ink rows the emulator drew for
#: it on the language screen (Godzilla LE 1.16, node at x = 20 + 340 * i, y = -620)
EMULATOR = [
    ("ALPHA\nBRAVO\nCHARLIE", (1, 0), (0, 1), 300.0, 400.0, [218, 267, 316]),
    ("DELTA\nECHO\nFOXTROT", (1, 0), (0, 2), 300.0, 400.0, [346, 394, 443]),
    ("SCALED TO BOUNDS LINE", (0, 0), (1, 0), 300.0, 400.0, [85]),
    ("GOLF", (0, 0), (0, 2), 300.0, 400.0, [443]),
    ("THREE\nLINE\nSCALE", (1, 0), (1, 0), 300.0, 60.0, [84, 108, 132]),
]


def test_the_preview_draws_where_the_emulator_did():
    import json
    from pinball_decryptor.plugins.stern import fontrender
    path = os.path.join(PROJ, "images", "scene_textures", "scene_tree.json")
    if not os.path.isfile(path):
        pytest.skip("needs the PAD-412 Godzilla project copy")
    trees = json.load(open(path, encoding="utf-8"))
    card = next(c for c in trees if "762a9b99" in c)
    man = trees[card]
    idx = X._man_index(man)
    by = {}
    for nid, (n, _k) in idx.items():
        by.setdefault(n["name"], []).append(nid)
    fonts = fontrender.load_fonts(PROJ)
    for i, (text, flags, tail, w, h, want) in enumerate(EMULATOR):
        nid = X.FIRST_ADDED_ID + 2 * i
        ops = [{"op": "add_text", "parent": by["LanguageText"][0], "index": 99, "id": nid,
                "name": "T", "text": text, "x": 20 + 340 * (i % 4), "y": -620,
                "like": by["LanguageInstructions_Instance"][0], "flags": list(flags)},
               {"op": "text_rect", "node": nid, "rect": [-2.0, -2.0, w, h]}]
        edited, notes = X.apply_manifest(man, ops)
        assert notes == []
        for o in edited["objects"].values():
            if o and o.get("kind") == "Text" and o.get("text") == text:
                o["fit"], o["valign"] = tail
        d = next(x for x in E.draw_list(edited, 80) if x["kind"] == "text"
                 and x["text"] == text)
        img = np.asarray(R.render_tree(PROJ, edited, draws=[d], fonts=fonts))
        white = img[..., :3].min(axis=2) > 200
        ys = np.nonzero(white.sum(axis=1))[0]
        tops = [r[0] for r in np.split(ys, np.where(np.diff(ys) > 1)[0] + 1)]
        assert len(tops) == len(want), (text, tops)
        assert all(abs(a - b) <= 2 for a, b in zip(tops, want)), (text, tops, want)


# ---------------------------------------------------------------------------------------------
# round 2: Write's space padding moved the words (DragonRR: "This text placement is worse than
# before" - a project re-read from his built card showed "GODZILLA VS BATTRA" well left of its
# box). The game lays out trailing spaces too (emulator: 26 of them drew the centred title
# ~170 px left), so the spaces a shorter replacement is padded with go where they don't show.
# ---------------------------------------------------------------------------------------------
from pinball_decryptor.plugins.stern import engine  # noqa: E402

W = b"GODZILLA VS BATTRA"


@pytest.mark.parametrize("looks, want", [
    ((), W + b" " * 6),                                         # no layout known: as before
    ([(0, False, True, False)], W + b" " * 6),                  # left: after the words
    ([(2, False, True, False)], b" " * 6 + W),                  # right: before them
    ([(1, False, True, False)], b" " * 3 + W + b" " * 3),       # centred: split
    ([(1, True, True, False)], b" " * 3 + W + b" " * 3),        # one line: still split
])
def test_a_shorter_replacement_is_padded_where_its_alignment_hides_it(looks, want):
    assert engine._padded_text(W, len(W) + 6, looks) == want


def test_a_multiline_centred_text_takes_its_padding_as_a_line_under_it():
    words = b"GODZILLA\nVS. BATTRA"
    top = [(1, True, True, False)]
    assert engine._padded_text(words, len(words) + 6, top) == words + b"\n" + b" " * 5
    # middle/bottom of its box, or scaled to fit: one more line would move it, so split
    for looks in ([(1, True, False, False)], [(1, True, True, True)]):
        assert engine._padded_text(words, len(words) + 6, looks) == \
            b" " * 3 + words + b" " * 3
    assert engine._padded_text(words, len(words), top) == words


def test_the_scene_says_how_each_string_is_aligned():
    sc = T.parse(scene())
    texts = [o for o in sc.objects.values() if o.kind == "Text"]
    texts[0].body.update(align=2, flags=(1, 1), tail=(1, 2))
    looks = engine._radium_text_looks(T.serialize(sc))
    key = texts[0].body["text"].decode("latin1")
    assert (2, True, False, True) in looks[key]
    assert engine._radium_text_looks(b"not a scene") == {}


def test_write_pads_a_centred_scene_line_on_both_sides(tmp_path):
    from pinball_decryptor.plugins.stern import radium
    from tests.test_stern_radium import _FakeReader, _apply, _write_tsv
    sc = T.parse(scene())
    text = next(o for o in sc.objects.values() if o.kind == "Text")
    text.body.update(text=b"GODZILLA AND ANGUIRUS", align=1, flags=(0, 0))
    buf = T.serialize(sc)
    if not any(e["text"] == "GODZILLA AND ANGUIRUS" for e in radium.display_texts(buf)):
        pytest.skip("the test scene's line isn't classed as display text")
    _write_tsv(tmp_path, [("/g/a.radium", "GODZILLA AND ANGUIRUS", "GODZILLA VS BATTRA")])
    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
        _FakeReader({"/g/a.radium": buf}), str(tmp_path), log=lambda *a, **k: None,
        cancel=lambda: False)
    assert n == 1 and writes
    out = T.parse(_apply(buf, writes))
    got = next(o for o in out.objects.values() if o.kind == "Text").body["text"]
    assert got == b" GODZILLA VS BATTRA  "


# ---------------------------------------------------------------------------------------------
# round 3: a card an older Write padded (DragonRR on v1.121.1: "Not fixed. the box is large
# enough the text is off"). A project re-read from such a card holds the padded line as its
# original with no edit, so nothing rewrote it; Write now repairs it and Scenes draws it so.
# ---------------------------------------------------------------------------------------------
PADDED = "GODZILLA VS BATTRA" + " " * 26


def test_an_older_writes_padding_is_recognised():
    assert engine._old_padding(PADDED)
    assert not engine._old_padding("KING OF THE MONSTERS UNLOCKED AT PWR UP LVL 8  ")  # stock
    assert not engine._old_padding("POWERLINES ") and not engine._old_padding("     ")


def test_write_sets_an_old_padded_line_back_to_its_words(tmp_path):
    from tests.test_stern_radium import _write_tsv
    _write_tsv(tmp_path, [
        ("/g/a.radium", PADDED, ""),                                  # not edited: repaired
        ("/g/a.radium", "POWERLINES ", ""),                           # stock: left alone
        ("/g/b.radium", "SHOOT  " + " " * 4, "SHOOT RAMP"),           # edited: the edit wins
        ("/godzilla_le/game", "TILT" + " " * 4, ""),                  # program text: not a scene
    ])
    edits = engine._changed_radium_text(str(tmp_path))
    assert edits == {"/g/a.radium": [(PADDED, "GODZILLA VS BATTRA")],
                     "/g/b.radium": [("SHOOT  " + " " * 4, "SHOOT RAMP")]}


def test_scenes_draws_an_old_padded_line_by_its_words(tmp_path, fonts):
    d = _text("GODZILLA VS BATTRA", (-2, -2, 340, 40), 1)
    want = _draw(tmp_path, d, fonts)
    assert np.array_equal(_draw(tmp_path, dict(d, text=PADDED), fonts), want)
    assert not np.array_equal(_draw(tmp_path, dict(d, text="GODZILLA VS BATTRA  "), fonts),
                              want)                                # two: a stock line's own


def test_write_recentres_a_card_an_older_write_padded(tmp_path):
    from pinball_decryptor.plugins.stern import radium
    from tests.test_stern_radium import _FakeReader, _apply, _write_tsv
    sc = T.parse(scene())
    text = next(o for o in sc.objects.values() if o.kind == "Text")
    text.body.update(text=PADDED.encode("latin1"), align=1, flags=(0, 0))
    buf = T.serialize(sc)
    if not any(e["text"] == PADDED for e in radium.display_texts(buf)):
        pytest.skip("the test scene's line isn't classed as display text")
    _write_tsv(tmp_path, [("/g/a.radium", PADDED, "")])
    writes, n, _ov, _fw, _grown = engine._radium_text_writes(
        _FakeReader({"/g/a.radium": buf}), str(tmp_path), log=lambda *a, **k: None,
        cancel=lambda: False)
    assert n == 1 and writes
    out = T.parse(_apply(buf, writes))
    got = next(o for o in out.objects.values() if o.kind == "Text").body["text"]
    assert got == b" " * 13 + b"GODZILLA VS BATTRA" + b" " * 13
