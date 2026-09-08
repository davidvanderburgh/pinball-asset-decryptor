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


# ------------------------------- the panel is the RENDER size --------------
#
# ★ THE CORRECTION OF 2026-09-08 (peanuts: "the screen resolution for Star
# Wars Home Edition, Jurassic Park The Pin and James Bond 60th are still
# wrong", against a release that had already given all three an 800x480
# WINDOW). Sizing the window alone could never have worked: these games draw
# their scene at its authored size in the corner of whatever framebuffer they
# are handed - his star_wars_elg screenshot has the service screen at 800x480
# in the top-left of a 1360x768 window with the rest black - so a smaller
# window scales that same wrong picture down. The panel has to be what the
# GAME is told.


def _rig_text(name):
    with open(os.path.join(RIG, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def test_a_one_screen_cabinet_gets_the_panel_as_its_render_size():
    """The half the first attempt was missing. PAD_GL_W/H is what the game is
    told; without it the picture stays in the corner however small the window
    is made."""
    display2 = pytest.importorskip("display2")
    for title in ("james_bond_60th_le", "star_wars_elg",
                  "jurassic_park_the_pin"):
        got = display2.reported_exports(title)
        assert "PAD_GL_W=800" in got and "PAD_GL_H=480" in got, title
        # and the window too, which is also padglhost's signal that this run's
        # size is a reported panel rather than the rig's 1360x768 default
        assert "PAD_GL_WIN_W=800" in got and "PAD_GL_WIN_H=480" in got, title


def test_a_reported_rotation_never_resizes_the_guest():
    """venom_le's topper is mounted on its side, which is a fact about a
    cabinet and not about a framebuffer. A rotation that reached the guest
    would be a rotation applied twice."""
    display2 = pytest.importorskip("display2")
    got = display2.reported_exports("venom_le")
    assert got == ["PAD_GL2_ROT=90"]
    assert not [g for g in got if g.startswith("PAD_GL_W")]


def test_a_title_nobody_reported_exports_nothing():
    display2 = pytest.importorskip("display2")
    assert display2.reported_exports("godzilla_le") == []
    assert display2.reported_exports("") == []
    assert display2.reported_exports(None) == []


def test_watch_sh_knows_every_knob_the_table_can_ask_for():
    """The shell reads what reported_exports prints. A fact that grows a new
    knob and is then silently dropped by the loop is the failure this pins -
    the whole point of moving the decision into Python was that the two halves
    can disagree.
    """
    display2 = pytest.importorskip("display2")
    names = set()
    for title in display2.REPORTED_PANELS:
        names |= {kv.split("=")[0] for kv in display2.reported_exports(title)}
    assert names  # the table is not empty
    watch = _rig_text("watch.sh")
    for name in names:
        assert "%s=*)" % name in watch, \
            "watch.sh has no case branch for %s" % name


def test_a_caller_that_names_the_render_size_by_hand_still_wins():
    """A sweep that sets PAD_GL_W/H must get exactly what it asked for - the
    reported panel is a default for a title, not an override of a person.
    PAD_GL_W is already set by the time the reported block runs, so the
    'was it the caller' answer has to be recorded before the default lands.
    """
    watch = _rig_text("watch.sh")
    assert "GL_WH_FROM_CALLER=0" in watch
    assert ('if [ -n "${PAD_GL_W:-}${PAD_GL_H:-}" ]; then '
            'GL_WH_FROM_CALLER=1; fi') in watch
    # and the two branches that set it are guarded by that answer
    for name in ("PAD_GL_W", "PAD_GL_H"):
        i = watch.index("%s=*)" % name)
        branch = watch[i:watch.index(";;", i)]
        assert 'GL_WH_FROM_CALLER" = 0' in branch, name


def test_a_window_size_remembered_around_another_picture_is_dropped():
    """~/.pad_windows outlives a change to what the window frames. Every line
    the three one-screen cabinets have was saved around a 1360x768 render, and
    replaying it would hand the fix a window nearly twice the panel - the same
    "window too large" the reporter already has.
    """
    src = _rig_text("padglhost.c")
    # the render size is written WITH the window size, so the size can be read
    assert r'fprintf(f, "%s %d %d %d %d %d %d\n", key, x, y, w, h,' in src
    # ... and a line without one is only distrusted where the size is a
    # reported panel; every other title keeps what it was left at
    assert "win_reported_panel" in src
    assert "int matched = gfw ? (gfw == fb_w && gfh == fb_h)" in src


def test_the_save_slot_records_the_render_size_and_a_restore_checks_it():
    """PAD_GL_W/H sizes the guest's own drawing surface, so it is inside the
    checkpoint. Making it per-title means a slot saved before this release
    cannot load after it, and criu finds that out only after the live guest
    has been killed - so it is refused in the pre-flight, where a refusal
    still costs nothing.
    """
    save = _rig_text("savestate.sh")
    restore = _rig_text("restorestate.sh")
    assert 'echo "render $RENDER" >> "$DDIR/restore.env"' in save
    assert "SLOT_RENDER" in restore and "NOW_RENDER" in restore
    # Refused BEFORE the live guest is killed. The kill itself, not the
    # comment about it: a refusal that lands afterwards takes the whole
    # session with it, which is the lesson this pre-flight was built on.
    head = restore[:restore.index("pkill -9 -x game")]
    assert "SLOT_RENDER" in head, "the render check runs after the kill"
