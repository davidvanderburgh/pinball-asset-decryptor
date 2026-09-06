"""The node-board VARIANT table nbdir.py derives a title's identity claims from.

WHAT THIS GUARDS. Every row in `nbdir.VARIANT_PRIOR` is a MEASUREMENT taken
with `hexreg.py` off a live game's decrypted hex-image registry, and every
type NOT in it is a guess the shim marks `variant_guess=1`. A wrong or missing
row is not cosmetic: the game grades each board's claimed variant against its
own image, a mismatch is status 7 = Checksum, and this generation of game code
answers status 7 with the "UPDATING NODE BOARD RUNTIME / UPDATE FAILED / <node>"
walk over attract - godzilla_le's node 10 (tmc5041node, 2026-08-22), turtles'
node 12 (coil4node, 2026-08-23), batman's VILLAIN VISION board (lcdnode,
2026-08-24) and mando_le's topper board at node 12 (hdmi_ws2812node,
2026-09-05, item 67) each cost a session before their row existed.

These pins keep a measured row from drifting back to the 0x01 default, and
keep the class each one was measured on beside it: the variant byte lives
INSIDE the per-class image, so a prior graded against another class's image is
a prior nobody has read.

FAST AND SYNTHETIC like the rest of the rig's tests: no WSL, no emulator, no
card, no Tk.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


@pytest.fixture()
def nbdir():
    import nbdir as mod
    return mod


#: (type, measured variant, the class it was measured on) - the provenance of
#: each row is in nbdir.py's own comment block above VARIANT_PRIOR.
MEASURED = [
    ("pinnode",         0x01, 1),
    ("ws2812node",      0x05, 5),
    ("node4",           0x03, 4),
    ("tmc5041node",     0x0d, 5),
    ("coil4node",       0x04, 5),
    ("lcdnode",         0x02, 3),
    ("hdmi_ws2812node", 0x0c, 5),   # mando_le 1.44.0's topper, 2026-09-05
    ("coil4_lednode",   0x10, 5),   # uncanny_xmen_le 0.97.0's topper, 2026-09-06
]


@pytest.mark.parametrize("typ,variant,klass", MEASURED)
def test_measured_variant_row(nbdir, typ, variant, klass):
    assert nbdir.VARIANT_PRIOR[typ] == variant
    # the class the measurement was taken on is the class the prior is
    # graded against - a type whose preference forgets it would be graded
    # against an image nobody read
    pref = nbdir.CLASS_PREF.get(typ, nbdir.CLASS_PREF_DEFAULT)
    assert klass in pref


def test_every_prior_names_a_type_the_game_knows(nbdir):
    known = {t.decode() for t in nbdir.TYPE_NAMES}
    assert set(nbdir.VARIANT_PRIOR) <= known
    assert set(nbdir.CLASS_PREF) <= known


def test_the_default_is_the_guess_not_a_measurement(nbdir):
    # 0x01 is what an UNLISTED type gets, and the output marks it as a guess;
    # a listed type must never be listed AT the default by accident of a
    # copy - that would silence the guess marker on a value nobody measured.
    assert nbdir.VARIANT_DEFAULT == 0x01
    for typ, var in nbdir.VARIANT_PRIOR.items():
        if var == nbdir.VARIANT_DEFAULT:
            assert typ == "pinnode", typ   # the one measured 0x01
