"""The playfield's positional view needs ENOUGH usable devices, not just one.

uncanny_xmen_le 0.97.0 (item 80 sweep, 2026-09-06) positions exactly three
devices - the SHOOTER BEZEL lamps, on the cabinet-front picture - and nothing
on a playfield. Those three lamps resolve to a node, so the old gate ("any lamp
that can light") promoted the title out of the Schematic and into a Field view
drawn on a blank 448x274 extent: "the virtual playfield is just a large empty
black space". The Schematic it displaced had 109 clickable switch rows.

Module globals are set directly: the gate reads DEV_ROWS / LAYOUT_IMAGE /
GROUP_NODE / TDIR at call time, and an empty table dir is exactly what a
first run looks like.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)

CAB = "System/TestMode/spike_2_cabinet_front_cropped"


def _led(name, x, y, group, index, image):
    return dict(kind="led", name=name, x=x, y=y, w=30, h=30, group=group,
                index=index, conn="-", image=image)


@pytest.fixture
def pf(monkeypatch, tmp_path):
    playfield = pytest.importorskip("playfield")
    monkeypatch.setattr(playfield, "PF_VIEW", "")
    monkeypatch.setattr(playfield, "TDIR", str(tmp_path))   # no tables yet
    monkeypatch.setattr(playfield, "load_coils", lambda: [])
    return playfield


def test_three_cabinet_bezel_lamps_are_not_a_playfield(pf, monkeypatch):
    rows = [_led("SHOOTER BEZEL %d" % i, 398 + 10 * i, 244, 5, 8 + i, CAB)
            for i in (1, 2, 3)]
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    monkeypatch.setattr(pf, "LAYOUT_IMAGE", CAB)
    monkeypatch.setattr(pf, "GROUP_NODE", {5: 1})      # they CAN light
    assert pf.layout_extent()                          # the old gate's yes
    assert not pf.layout_is_usable()


def test_a_real_lamp_layout_still_qualifies(pf, monkeypatch):
    rows = [_led("INSERT %d" % i, 20 + 12 * i, 100 + 9 * i, 7, i, "playfield")
            for i in range(pf.MIN_USABLE_LAYOUT)]
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    monkeypatch.setattr(pf, "LAYOUT_IMAGE", "playfield")
    monkeypatch.setattr(pf, "GROUP_NODE", {7: 8})
    assert pf.layout_is_usable()


def test_lamps_nothing_can_light_still_do_not_count(pf, monkeypatch):
    # elvira3's shape (item 50): many positioned lamps, no wire address.
    rows = [_led("TOPPER %d" % i, 5 * i, 3 * i, 3, i, "topper")
            for i in range(40)]
    monkeypatch.setattr(pf, "DEV_ROWS", rows)
    monkeypatch.setattr(pf, "LAYOUT_IMAGE", "topper")
    monkeypatch.setattr(pf, "GROUP_NODE", {})
    assert not pf.layout_is_usable()
