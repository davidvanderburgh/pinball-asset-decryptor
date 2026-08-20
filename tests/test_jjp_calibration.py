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
