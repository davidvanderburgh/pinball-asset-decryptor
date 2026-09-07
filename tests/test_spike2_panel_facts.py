"""The window a display is SHOWN in, when the binary will not say.

Three separate things land here, all of them host-side only and none of them
able to reach the guest:

  * a playfield picture is accepted on PROPORTION, not on containing every
    last marker - one stray device used to cost a title its whole artwork;
  * the facts a game binary does not carry (a one-screen cabinet's panel, a
    topper mounted on its side) are reported from real machines and kept in
    one place, with the evidence, rather than guessed per title;
  * the topper can be switched off, because a machine without one is a real
    machine.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


# ------------------------------------------------ the artwork fit ----------

@pytest.fixture
def pf(monkeypatch, tmp_path):
    playfield = pytest.importorskip("playfield")
    monkeypatch.setattr(playfield, "PF_VIEW", "")
    monkeypatch.setattr(playfield, "TDIR", str(tmp_path))
    return playfield


def _png(tmp_path, w, h):
    """A real PNG header - gameinfo.png_size reads only the IHDR."""
    import struct
    import zlib
    ihdr = struct.pack(">II5B", w, h, 8, 2, 0, 0, 0)
    chunk = (struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
             + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF))
    p = tmp_path / "playfield.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk)
    return str(p)


def _points(pf, monkeypatch, pts):
    monkeypatch.setattr(pf, "layout_points", lambda: pts)


def test_one_stray_device_no_longer_costs_the_whole_playfield(pf, monkeypatch,
                                                              tmp_path):
    """★ uncanny_xmen_le 0.98.0. It positions 185 devices on `playfield` and
    ships a 321x710 picture to draw them on - the right picture, found the
    right way. ONE of the 185 sits at x=383, so the max-extent test made the
    layout 383 wide, the artwork failed by 62 pixels, and the window fell back
    to a blank field. David, looking straight at it: "running xmen on main
    right now has no artwork"."""
    art = _png(tmp_path, 321, 710)
    monkeypatch.setattr(pf, "PF_PNG", art)
    _points(pf, monkeypatch, [(20, 40 + i) for i in range(184)] + [(383, 200)])
    assert pf.layout_art() == art


def test_a_picture_the_layout_is_not_drawn_on_is_still_refused(pf, monkeypatch,
                                                               tmp_path):
    """The case the test exists for, and it is nothing like one stray:
    uncanny_xmen_le 0.97.0's cabinet front (448x274) under playfield
    coordinates that reach y=626. Not one point over the edge - most of them."""
    art = _png(tmp_path, 448, 274)
    monkeypatch.setattr(pf, "PF_PNG", art)
    _points(pf, monkeypatch, [(20, 300 + i) for i in range(100)])
    assert pf.layout_art() is None


def test_the_floor_is_a_proportion_of_this_title_s_own_layout(pf, monkeypatch,
                                                              tmp_path):
    """Just under the floor is refused and just over it is accepted, so the
    rule is the stated one and not an accident of these two examples."""
    art = _png(tmp_path, 100, 100)
    monkeypatch.setattr(pf, "PF_PNG", art)
    n = 100
    for outside, want_art in ((int(n * (1 - pf.ART_FIT_MIN)) - 1, True),
                              (int(n * (1 - pf.ART_FIT_MIN)) + 2, False)):
        pts = ([(10, 10)] * (n - outside)) + ([(999, 999)] * outside)
        _points(pf, monkeypatch, pts)
        assert (pf.layout_art() == art) is want_art, outside


def test_no_picture_and_no_layout_are_both_just_no_artwork(pf, monkeypatch,
                                                           tmp_path):
    monkeypatch.setattr(pf, "PF_PNG", None)
    _points(pf, monkeypatch, [(1, 1)])
    assert pf.layout_art() is None
    monkeypatch.setattr(pf, "PF_PNG", _png(tmp_path, 100, 100))
    _points(pf, monkeypatch, [])
    assert pf.layout_art() is None


# --------------------------------------------- the reported facts ----------

def test_the_reported_panels_are_only_what_the_binary_cannot_say():
    """★ THE TABLE THIS RIG OTHERWISE REFUSES TO KEEP, kept deliberately and
    kept SMALL. Each entry is a measurement from a machine somebody owns, for
    a fact established to be absent from the binary: the one-screen cabinets
    reference no /dev/fb* at all and carry no 800x480, and no binary says
    which way round a panel is bolted on.

    The shape is pinned so an entry cannot quietly grow into something that
    reaches the guest: a screen is a (w, h) window size, a rotation is a
    quarter turn, and nothing else is allowed in.
    """
    display2 = pytest.importorskip("display2")
    for title, facts in display2.REPORTED_PANELS.items():
        assert title and isinstance(title, str)
        assert set(facts) <= {"screen", "rot2"}, title
        if "screen" in facts:
            w, h = facts["screen"]
            assert 160 <= w <= 7680 and 120 <= h <= 4320, title
        if "rot2" in facts:
            assert facts["rot2"] in (90, 180, 270), title
    # the three one-screen cabinets, all reported at the same size
    assert {t for t, f in display2.REPORTED_PANELS.items()
            if f.get("screen") == (800, 480)} == {
        "james_bond_60th_le", "star_wars_elg", "jurassic_park_the_pin"}
    # venom's topper, the only panel known to be mounted on its side
    assert display2.REPORTED_PANELS["venom_le"]["rot2"] == 90


def test_a_title_nobody_reported_gets_nothing():
    """Silence is the default: a title with no entry keeps the derived
    reading, which is every title but four."""
    display2 = pytest.importorskip("display2")
    assert display2.reported("godzilla_le") == {}
    assert display2.reported("") == {}
    assert display2.reported(None) == {}


def test_reported_hands_back_a_copy():
    """A caller that edits what it gets must not edit the table."""
    display2 = pytest.importorskip("display2")
    got = display2.reported("venom_le")
    got["rot2"] = 270
    assert display2.REPORTED_PANELS["venom_le"]["rot2"] == 90
