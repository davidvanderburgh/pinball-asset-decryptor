"""Spike 1 emulation: the hardware-state model + the switch/LED viewer render.

These cover the format-agnostic pieces that are usable regardless of how far
the game boots — the viewer's data contract and its rendering. The rig launch
itself needs WSL + a privileged device model and is exercised by hand (see
docs/architecture/spike1_emulation.md).

No Tk windows here (render_png is pure PIL); the live Tk viewer isn't built.
"""

import os

import pytest

from pinball_decryptor.plugins.stern import spike1_emulate as se
from pinball_decryptor.plugins.stern.spike1_emulate import (
    HardwareState, StateBlock, SwitchInput, addr)


def test_addr_bounds():
    assert addr(0, 0) == 0
    assert addr(15, 63) == se.N_SLOTS - 1
    with pytest.raises(ValueError):
        addr(16, 0)
    with pytest.raises(ValueError):
        addr(0, 64)


def test_hardware_state_setters():
    st = HardwareState()
    st.set_switch(2, 5, True)
    assert st.get_switch(2, 5) == 1
    st.set_switch(2, 5, False)
    assert st.get_switch(2, 5) == 0
    st.set_lamp(8, 3, 200, 100, 50)
    assert st.get_lamp(8, 3) == (200, 100, 50)
    st.set_lamp(8, 4, 128)            # mono lamp -> equal channels
    assert st.get_lamp(8, 4) == (128, 128, 128)
    st.set_coil(9, 6, True)
    assert st.get_coil(9, 6) == 1


def test_state_block_round_trip():
    st = HardwareState()
    st.set_switch(2, 5, True)
    st.set_switch(3, 0, True)
    st.set_lamp(8, 3, 200, 100, 50)
    st.set_coil(9, 6, True)
    buf = StateBlock.pack(st, seq=42, flags=1)
    assert len(buf) == StateBlock.SIZE
    st2, seq, flags = StateBlock.unpack(buf)
    assert (seq, flags) == (42, 1)
    assert st2.get_switch(2, 5) == 1 and st2.get_switch(3, 0) == 1
    assert st2.get_lamp(8, 3) == (200, 100, 50)
    assert st2.get_coil(9, 6) == 1
    # untouched slots stay zero
    assert st2.get_switch(0, 0) == 0 and st2.get_lamp(0, 0) == (0, 0, 0)


def test_state_block_rejects_bad_magic_and_short():
    with pytest.raises(ValueError):
        StateBlock.unpack(b"\x00" * StateBlock.SIZE)
    with pytest.raises(ValueError):
        StateBlock.unpack(b"\x00" * 4)


def test_switch_input_round_trip():
    slots = {addr(2, 5), addr(3, 0), addr(9, 63)}
    buf = SwitchInput.pack(slots, seq=7)
    assert len(buf) == SwitchInput.SIZE
    closed, seq = SwitchInput.unpack(buf)
    assert closed == slots and seq == 7


def test_switch_input_empty():
    closed, seq = SwitchInput.unpack(SwitchInput.pack(set()))
    assert closed == set() and seq == 0


def test_init_state_files(tmp_path):
    run = tmp_path / "run"
    state_path, input_path = se.init_state_files(str(run))
    assert os.path.getsize(state_path) == StateBlock.SIZE
    assert os.path.getsize(input_path) == SwitchInput.SIZE
    # idempotent + readable back as a valid (empty) state
    se.init_state_files(str(run))
    with open(state_path, "rb") as f:
        st, seq, _flags = StateBlock.unpack(f.read())
    assert seq == 0 and not any(st.switches)


# ---- viewer render (headless PIL, no Tk) ----

def test_active_nodes_only_populated():
    from tools.spike1_emu import s1view
    st = HardwareState()
    st.set_switch(2, 1, True)
    st.set_lamp(8, 0, 255)
    st.set_coil(9, 0, True)
    assert s1view.active_nodes(st) == [2, 8, 9]
    assert s1view.active_nodes(HardwareState()) == [0]   # never empty


def test_render_png_reflects_state(tmp_path):
    from tools.spike1_emu import s1view
    st = HardwareState()
    st.set_switch(2, 4, True)
    st.set_lamp(8, 2, 0, 200, 0)
    st.set_coil(9, 1, True)
    out = tmp_path / "frame.png"
    img = s1view.render_png(st, str(out))
    assert out.exists()
    # the closed switch cell (node 2 is row 0 of the switch section) is green
    px = img.load()
    # sample the interior of node2/index4's switch cell
    cx = s1view.LABEL_W + 4 * (s1view.CELL + s1view.PAD) + s1view.PAD + s1view.CELL // 2
    cy = s1view.PAD + 20 + s1view.PAD + s1view.CELL // 2
    assert px[cx, cy] == s1view.SW_CLOSED


def test_demo_state_is_lively():
    from tools.spike1_emu import s1view
    # across a second of the synthetic feed, switches and lamps both light up
    any_sw = any(any(s1view.demo_state(t / 10.0).switches) for t in range(10))
    any_lamp = any(any(s1view.demo_state(t / 10.0).lamps) for t in range(10))
    any_coil = any(any(s1view.demo_state(t / 10.0).coils) for t in range(10))
    assert any_sw and any_lamp and any_coil
