"""The inches -> playfield-pixel calibration behind the matrix UI's LEDs.

THE BUG THESE EXIST FOR.  ``swdump.calibrate`` fits the lamps' inch positions
onto the switches' pixel positions, one linear fit per axis.  Fitting the axes
independently allows a mapping no photograph can have — different
inches-per-pixel horizontally and vertically — and that is exactly what
happened on Wonka: 17.06 across, 18.88 down.

The cause is that a lamp and a switch sharing a name are not always the same
spot: ``lp_inlane_left_1`` is the arrow insert and ``switch_inlane_left_1`` is
the rollover ~2.3 in DOWN-LANE of it.  That offset runs along the lane, so it
falls almost entirely in Y and cancels in X; and because the usable pairs bunch
into two clusters (jets high, lanes low) it does not average out — it tilts the
Y fit.

The symptom was not "the LEDs are wrong" but "the LEDs are right at the top and
drift downward toward the bottom", because a scale error grows with distance:
~27 px by the mid-playfield inserts and 55 px by the SHOOT AGAIN insert between
the flipper tips.  A scale that is 10% wrong looks like a placement bug, which
is what makes it worth pinning down in tests.
"""

import struct

import pytest

from tools.jjp_emu import swdump


# A synthetic playfield whose TRUE mapping is deliberately anisotropic, the way
# a stretched switch space makes it look: 17 px/in across, 19 px/in down.
TRUE_SX, TRUE_CX = 17.0, 10.0
TRUE_SY, TRUE_CY = 19.0, -40.0

#: (suffix, x_in, y_in) spread over the playfield so both axis fits are
#: well conditioned — clustered anchors are what made the real fit fragile.
_LAMPS = [("jet_left", 1.5, 10.5), ("jet_right", 6.0, 14.0),
          ("ramp", 12.0, 18.0), ("spinner", 16.0, 22.0),
          ("inlane_left", 2.5, 31.0), ("outlane_right", 17.5, 33.0)]


def _devices(sx=TRUE_SX, cx=TRUE_CX, sy=TRUE_SY, cy=TRUE_CY):
    """Switch/lamp tables that encode the given mapping exactly."""
    switches, lamps = [], []
    for name, xi, yi in _LAMPS:
        switches.append({"symbol": "switch_" + name, "name": name,
                         "x": int(round(sx * xi + cx)),
                         "y": int(round(sy * yi + cy))})
        lamps.append({"symbol": "lp_" + name, "name": name, "placed": True,
                      "x_in": xi, "y_in": yi})
    return switches, lamps


#: Wonka's own numbers, from ``hook_playfield_width`` / ``_height``.
PLAYFIELD = {"width": 20.25, "height": 46.0}
IMAGE = (385, 768)


def test_the_fit_recovers_a_mapping_it_was_given():
    """Sanity: the underlying solver is exact.  The corrected fit keeps what it
    replaced under ``raw_*``, which is the only place the pre-correction Y
    scale survives — and is what makes a bad correction auditable."""
    switches, lamps = _devices()
    cal = swdump.calibrate(switches, lamps)
    assert cal["ok"]
    assert cal["x"]["scale"] == pytest.approx(TRUE_SX, abs=0.05)
    assert cal["y"]["raw_scale"] == pytest.approx(TRUE_SY, abs=0.05)
    assert cal["y"]["raw_offset"] == pytest.approx(TRUE_CY, abs=1.0)


def test_square_pixels_forces_one_scale_onto_both_axes():
    """THE fix.  A photograph has square pixels, so two different scales are
    not a close call between two fits — one of them is impossible."""
    switches, lamps = _devices()
    cal = swdump.calibrate(switches, lamps, playfield=PLAYFIELD,
                           image_size=IMAGE)
    assert cal["x"]["scale"] == pytest.approx(cal["y"]["scale"])
    assert cal["square_pixels"]["corrected"] == "y"
    assert cal["square_pixels"]["raw_scale"] == pytest.approx(TRUE_SY, abs=0.05)


def test_the_impossible_scale_is_the_one_that_is_dropped():
    """WHICH scale to keep is decided by the game's own playfield size, not by
    preference: at 19 px/in a 46in playfield is 874 px tall, which cannot fit
    inside a 768 px photograph of it."""
    switches, lamps = _devices()
    cal = swdump.calibrate(switches, lamps, playfield=PLAYFIELD,
                           image_size=IMAGE)
    fits = cal["square_pixels"]["playfield_fits"]
    assert fits["x"] is True and fits["y"] is False
    assert cal["square_pixels"]["took_scale_from"] == "x"


def test_correcting_the_scale_keeps_the_top_of_the_playfield_still():
    """A rescale pivots about some point and the top is the right one to keep:
    it is where the switch space and the image agree, and it is the part that
    was already landing correctly.  Only what was wrong should move."""
    switches, lamps = _devices()
    cal = swdump.calibrate(switches, lamps, playfield=PLAYFIELD,
                           image_size=IMAGE)
    top_in = min(l["y_in"] for l in lamps)
    before = TRUE_SY * top_in + TRUE_CY
    after = cal["y"]["scale"] * top_in + cal["y"]["offset"]
    assert after == pytest.approx(before, abs=1.0)


def test_the_bottom_of_the_playfield_moves_up():
    """The whole point: the far end of the playfield is where a scale error
    accumulates, and it must come UP toward the inserts."""
    switches, lamps = _devices()
    cal = swdump.calibrate(switches, lamps, playfield=PLAYFIELD,
                           image_size=IMAGE)
    bottom_in = 39.8                       # Wonka's SHOOT AGAIN insert
    before = TRUE_SY * bottom_in + TRUE_CY
    after = cal["y"]["scale"] * bottom_in + cal["y"]["offset"]
    assert after < before - 30


def test_an_already_square_fit_is_left_alone():
    """A title whose two fits already agree must not be perturbed — rewriting
    a good fit would only add noise."""
    switches, lamps = _devices(sy=TRUE_SX, cy=TRUE_CY)
    cal = swdump.calibrate(switches, lamps, playfield=PLAYFIELD,
                           image_size=IMAGE)
    assert cal.get("square_pixels") is None
    assert cal["y"]["scale"] == pytest.approx(TRUE_SX, abs=0.05)


def test_without_a_photo_it_still_squares_the_scales():
    """The photo only decides WHICH scale is credible.  With no photo we fall
    back to X — the better-conditioned fit — rather than leaving a mapping that
    is known to be impossible."""
    switches, lamps = _devices()
    cal = swdump.calibrate(switches, lamps)
    assert cal["x"]["scale"] == pytest.approx(cal["y"]["scale"])
    assert cal["square_pixels"]["took_scale_from"] == "x"


def test_a_down_lane_rollover_offset_does_not_tilt_the_fit():
    """The REAL Wonka failure, reproduced from its cause.

    Build a perfectly square-pixel playfield, then move only the LOWER cluster's
    switches down-lane, the way a rollover sits below its arrow insert.  The
    naive per-axis fit reads that as "more pixels per inch" and tilts Y; the
    correction has to put it back, because the lower cluster is the one that
    lied and the jets at the top are the ones that did not.
    """
    switches, lamps = _devices(sy=TRUE_SX, cy=TRUE_CY)     # truly square
    for s in switches:
        if "lane" in s["symbol"]:                          # in/outlane rollovers
            s["y"] += 40                                   # ~2.3 in down-lane
    cal = swdump.calibrate(switches, lamps, playfield=PLAYFIELD,
                           image_size=IMAGE)
    # The uncorrected fit was dragged well off the true scale...
    assert cal["y"]["raw_scale"] > TRUE_SX + 1.0
    # ...and the correction brings it back to the honest, square-pixel one.
    assert cal["y"]["scale"] == pytest.approx(TRUE_SX, abs=0.05)
    # A lamp at the far end lands near where it belongs instead of tens of
    # pixels below it.  Asserted as an IMPROVEMENT rather than an absolute
    # tolerance: pinning at the top carries a little of the tilt with it, so
    # the honest claim is that almost all of the error is gone, not that the
    # result is pixel-exact.
    truth = TRUE_SX * 39.8 + TRUE_CY
    before = abs(cal["y"]["raw_scale"] * 39.8 + cal["y"]["raw_offset"] - truth)
    after = abs(cal["y"]["scale"] * 39.8 + cal["y"]["offset"] - truth)
    assert before > 40
    assert after < before / 5


def test_the_game_binary_is_found_not_assumed(tmp_path, monkeypatch):
    """THE hard-coded "Wonka" that made the matrix lie.

    ``--elf`` defaulted to the literal ``.../gen1/Wonka/game`` - the one thing
    padpath.sh says must never happen ("nothing downstream should contain the
    word Wonka").  Running Guns N' Roses, swdump died with FileNotFoundError on
    Wonka's path, wrote no dump, and jjpsw_launch.sh then found the PREVIOUS
    Wonka dump sitting there looking valid and opened the matrix onto it - so
    the panel showed gobstopper targets over a GnR playfield.
    """
    base = tmp_path / "gen1"
    (base / "GunsNRoses").mkdir(parents=True)
    exe = base / "GunsNRoses" / "game"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert swdump.default_elf(str(base)) == str(exe)

    # The title is discovered, so a different one is found without code changes.
    (base / "Godfather").mkdir()
    other = base / "Godfather" / "game"
    other.write_text("#!/bin/sh\n")
    other.chmod(0o755)
    assert swdump.default_elf(str(base)) in (str(exe), str(other))

    # Nothing mounted: it must not raise, and must not name a title it invented.
    empty = swdump.default_elf(str(tmp_path / "nothing"))
    assert "Wonka" not in empty
    assert isinstance(empty, str)


def test_no_title_is_hard_coded_in_swdump():
    """The rig is title-agnostic; a literal title in a default path is how that
    breaks silently, because it only shows up on the SECOND game."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(swdump))

    # Docstrings legitimately discuss Wonka - it is the title everything was
    # measured on, and the comment explaining this very bug names its path.  So
    # check the string LITERALS the code actually uses, with docstrings excluded.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]
    offenders = [s for s in literals if "wonka" in s.lower()]
    assert not offenders, "swdump hard-codes a title: %r" % (offenders,)


def test_png_size_reads_the_ihdr(tmp_path):
    png = tmp_path / "pf.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
                    + struct.pack(">II", 385, 768) + b"\x08\x06\x00\x00\x00")
    assert swdump.png_size(str(png)) == (385, 768)


def test_png_size_is_none_for_rubbish(tmp_path):
    """A title that ships no photo (or a failed decrypt) must not take the
    calibration down with it."""
    bad = tmp_path / "not.png"
    bad.write_bytes(b"this is not a png")
    assert swdump.png_size(str(bad)) is None
    assert swdump.png_size(str(tmp_path / "missing.png")) is None


# ------------------------------------------------ which playfield photo to use --

def _pfimage():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "jjp_emu", "pfimage.py")
    if not os.path.exists(path):
        pytest.skip("pfimage.py not present")
    spec = importlib.util.spec_from_file_location("pfimage_undertest", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _game(tmp_path, names):
    d = tmp_path / "edata" / "graphics" / "Game Tests"
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_bytes(b"x")
    return str(tmp_path)


def test_the_artwork_playfield_beats_the_whitewood(tmp_path, monkeypatch):
    """``pf_image.png`` is the obvious pick and it is WRONG on Guns N' Roses.

    GnR ships a bare whitewood as pf_image.png plus GNR_playfield_LE/SE.png,
    and the device coordinates are in the ARTWORK's pixel space: the three pop
    bumpers land dead-centre on the bumper caps in LE/SE and between them on the
    whitewood.  Drawing on the whitewood put every marker in the wrong place
    while looking plausible enough to be believed.
    """
    m = _pfimage()
    monkeypatch.setattr(m, "PF_EDITION", "LE")
    g = _game(tmp_path, ["pf_image.png", "GNR_playfield_LE.png",
                         "GNR_playfield_SE.png", "topper_image.png"])
    assert m.pick_pf(g).endswith("GNR_playfield_LE.png")

    monkeypatch.setattr(m, "PF_EDITION", "SE")
    assert m.pick_pf(g).endswith("GNR_playfield_SE.png")


def test_a_title_with_only_pf_image_still_works(tmp_path):
    """Wonka ships ONLY pf_image.png and there it IS the finished playfield -
    so the rule is "prefer a named playfield, else fall back", never "always
    take the artwork"."""
    m = _pfimage()
    g = _game(tmp_path, ["pf_image.png", "topper_image.png"])
    assert m.pick_pf(g).endswith("pf_image.png")


def test_an_explicit_name_wins(tmp_path, monkeypatch):
    """An escape hatch, because which edition a machine is cannot always be
    guessed from the files."""
    m = _pfimage()
    g = _game(tmp_path, ["pf_image.png", "GNR_playfield_LE.png"])
    monkeypatch.setenv("JJP_PF_NAME", "pf_image.png")
    assert m.pick_pf(g).endswith("pf_image.png")
    monkeypatch.setenv("JJP_PF_NAME", "nope.png")     # absent -> ignored
    assert m.pick_pf(g).endswith("GNR_playfield_LE.png")


def test_a_missing_directory_is_not_a_crash(tmp_path):
    m = _pfimage()
    out = m.pick_pf(str(tmp_path / "no-such-game"))
    assert out.endswith("pf_image.png")
