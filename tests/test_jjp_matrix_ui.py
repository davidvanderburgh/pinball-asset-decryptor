"""Headless tests for the JJP switch/LED matrix UI (tools/jjp_emu/jjpsw.py).

Cover the pure logic - shared-memory layout, driving switches by absolute frame
address (so direct/cabinet switches like Start have a route), the RGB LED byte
mapping, and per-title keyboard resolution - without opening a Tk window.
"""

import importlib.util
import mmap
import os
import tempfile
import types

import pytest

pytest.importorskip("tkinter")  # jjpsw imports tkinter at module load

JJPSW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools", "jjp_emu", "jjpsw.py")


@pytest.fixture(scope="module")
def m():
    if not os.path.exists(JJPSW):
        pytest.skip("tools/jjp_emu/jjpsw.py not present")
    spec = importlib.util.spec_from_file_location("jjpsw_undertest", JJPSW)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def shm(m):
    fd, path = tempfile.mkstemp()
    os.close(fd)

    class ScratchShm(m.SwitchShm):
        def __init__(self, p):
            f = os.open(p, os.O_RDWR | os.O_CREAT, 0o666)
            os.ftruncate(f, m.SHM_SIZE)
            self.map = mmap.mmap(f, m.SHM_SIZE)
            os.close(f)

    s = ScratchShm(path)
    yield s
    s.map.close()
    os.unlink(path)


def test_layout_offsets(m):
    # in_frame replaced the old switches/cabinet arrays: OUT sits right after it.
    assert m.OFF_IN_FRAME == 12
    assert m.OFF_OUT == 12 + m.FRAME_LEN
    assert m.OFF_OUT_CHANGES == m.OFF_OUT + m.BOARD_COUNT * m.FRAME_LEN
    # out_rise is one byte per OUT BIT per board, and read_count follows it.
    assert m.OFF_OUT_RISE == m.OFF_OUT_CHANGES + m.BOARD_COUNT * 4
    assert m.OFF_READ_COUNT == m.OFF_OUT_RISE + m.BOARD_COUNT * m.FRAME_LEN * 8
    assert m.SHM_SIZE == m.OFF_WRITE_COUNT + 4
    # The unsigned ints after out_rise must stay 4-byte aligned.
    assert m.OFF_READ_COUNT % 4 == 0


def test_polarity_regions(m):
    # The direct/cabinet region is active low; everything else active high.
    assert m.direct_byte(0) and m.direct_byte(3)
    assert not m.direct_byte(4) and not m.direct_byte(20)
    idle = m.idle_frame()
    assert len(idle) == m.FRAME_LEN
    assert idle[:m.DIRECT_BYTES] == bytes([m.DIRECT_IDLE]) * m.DIRECT_BYTES
    assert set(idle[m.DIRECT_BYTES:]) == {0}


def test_board_map_and_led_boards(m):
    assert m.BOARD_LED == m.BOARDS["JJP_BOARD_LED"]
    assert m.BOARDS["JJP_BOARD_IO"] not in m.LED_BOARDS
    assert m.BOARDS["JJP_BOARD_CAB"] not in m.LED_BOARDS
    assert m.BOARD_LED in m.LED_BOARDS


def test_direct_switches_are_active_low(m, shm):
    # Start is a DIRECT switch (byte 3 bit 0x01) and the cabinet region is
    # active LOW: a closed contact CLEARS its bit.  Measured against the game's
    # own Switch objects - see jjpshm.h.
    shm.idle()
    assert shm.get_switch(3, 0x01) is False        # idle = open
    assert shm.map[m.OFF_IN_FRAME + 3] == m.DIRECT_IDLE
    shm.set_switch(3, 0x01, True)
    assert shm.get_switch(3, 0x01) is True
    assert shm.map[m.OFF_IN_FRAME + 3] == m.DIRECT_IDLE & ~0x01   # bit CLEARED
    shm.set_switch(3, 0x01, False)
    assert shm.get_switch(3, 0x01) is False


def test_matrix_switches_are_active_high(m, shm):
    shm.idle()
    assert shm.get_switch(4, 0x80) is False
    shm.set_switch(4, 0x80, True)
    assert shm.get_switch(4, 0x80) is True
    assert shm.map[m.OFF_IN_FRAME + 4] == 0x80     # bit SET
    shm.set_switch(99, 0x01, True)      # out of frame - ignored, no crash
    assert shm.get_switch(99, 0x01) is False


def test_inverted_optos_read_the_other_way_up(m, shm):
    # The trough (and other optos) are inverted: a present ball breaks the beam
    # so the switch reads OPEN electrically, and "nothing there" reads CLOSED.
    # Callers still say closed=True to mean "ball present"; SwitchShm flips the
    # electrical bit for a switch in .inverted.  This is the bug that made a full
    # trough read as empty and the game never start.
    try:
        shm.inverted = {(4, 0x01)}          # a matrix opto (Wonka trough #5)
        shm.idle()
        # idle = nothing there = inactive.  A non-inverted matrix switch is then
        # electrically OPEN, but an inverted opto reads inactive when it is
        # CLOSED - so its bit is SET, not clear.
        assert shm.get_switch(4, 0x01) is False            # inactive
        assert shm.map[m.OFF_IN_FRAME + 4] & 0x01          # bit SET (closed)
        # ball present -> active -> electrically OPEN (the flip)
        shm.set_switch(4, 0x01, True)
        assert shm.get_switch(4, 0x01) is True             # present
        assert not (shm.map[m.OFF_IN_FRAME + 4] & 0x01)    # bit CLEARED (open)
        # a normal matrix switch in the same byte is unaffected by the flag
        shm.set_switch(4, 0x80, True)
        assert shm.get_switch(4, 0x80) is True
        assert shm.map[m.OFF_IN_FRAME + 4] & 0x80          # bit SET
    finally:
        shm.inverted = frozenset()


def test_idle_is_not_an_all_zero_frame(m, shm):
    # The specific bug this guards: a zeroed frame reads as every cabinet
    # button jammed on, so Start has no press edge left to give.
    shm.set_switch(0, 0x01, True)
    shm.set_switch(19, 0x80, True)
    shm.idle()
    assert bytes(shm.map[m.OFF_IN_FRAME:m.OFF_IN_FRAME + m.FRAME_LEN]) \
        == m.idle_frame()
    assert all(not shm.get_switch(fb, 1 << b)
               for fb in range(m.FRAME_LEN) for b in range(8))


def test_out_rise_reads_the_per_bit_counter(m, shm):
    # coil_vuk_trough is IO byte 1 bit 4; the shim counts its rising edges.
    off = m.OFF_OUT_RISE + (m.BOARD_IO * m.FRAME_LEN + 1) * 8 + 4
    assert shm.out_rise(m.BOARD_IO, 1, 4) == 0
    shm.map[off] = 7
    assert shm.out_rise(m.BOARD_IO, 1, 4) == 7
    assert shm.out_rise(m.BOARD_IO, 1, 5) == 0      # neighbouring bit untouched
    assert shm.out_rise(99, 1, 4) == 0              # out of range, no crash


def test_categorisation_helpers(m):
    assert m._category(0) == m.CAT_CABINET
    assert m._category(3) == m.CAT_CABINET
    assert m._category(4) == m.CAT_PLAYFIELD
    assert m._category(19) == m.CAT_PLAYFIELD
    assert m._category(20) == m.CAT_MECH
    # switch_071 -> byte 4 bit 0x01 is matrix #1; a direct switch has no number.
    assert m._matrix_num(4, 0x01) == 1
    assert m._matrix_num(3, 0x01) is None
    assert m._addr_str(3, 0x01) == "3.0"
    assert m._addr_str(4, 0x80) == "4.7"


def test_led_buffer_only_written_boards(m, shm):
    assert shm.led_buffer() == b""          # nothing written -> empty
    o = m.OFF_OUT + m.BOARD_LED * m.FRAME_LEN
    shm.map[o + 6], shm.map[o + 7], shm.map[o + 8] = 10, 20, 30
    off = m.OFF_OUT_CHANGES + m.BOARD_LED * 4
    shm.map[off:off + 4] = (5).to_bytes(4, "little")
    buf = shm.led_buffer()
    assert len(buf) == m.FRAME_LEN          # exactly the one written board
    assert (buf[6], buf[7], buf[8]) == (10, 20, 30)
    assert shm.led_write_total() == 5


def test_led_rgb_reads_scales_and_wraps(m, shm):
    o = m.OFF_OUT + m.BOARD_LED * m.FRAME_LEN
    shm.map[o + 6], shm.map[o + 7], shm.map[o + 8] = 10, 20, 30
    off = m.OFF_OUT_CHANGES + m.BOARD_LED * 4
    shm.map[off:off + 4] = (1).to_bytes(4, "little")
    buf = shm.led_buffer()
    stub = types.SimpleNamespace(lamps=[{"index": 0}, {"index": 2}])
    # 6-bit values are scaled x4 to 8-bit; index 2 -> byte 6.
    assert m.MatrixUI.led_rgb(stub, 1, buf) == (40, 80, 120)
    assert m.MatrixUI.led_rgb(stub, 0, b"") == (0, 0, 0)      # empty -> black
    # 0x3f (full 6-bit) scales to 252, and the top is clamped at 255.
    shm.map[o + 0] = 0x3f
    buf = shm.led_buffer()
    big = types.SimpleNamespace(lamps=[{"index": len(buf)}])   # index*3 % n == 0
    assert m.MatrixUI.led_rgb(big, 0, buf)[0] == 0x3f * 4


def test_accumulate_leds_retains_pages(m, shm):
    o = m.OFF_OUT + m.BOARD_LED * m.FRAME_LEN
    off = m.OFF_OUT_CHANGES + m.BOARD_LED * 4
    shm.map[off:off + 4] = (1).to_bytes(4, "little")     # LED board has writes
    stub = types.SimpleNamespace(shm=shm, _led_pages={}, _led_buf=b"")

    # Page 0x81 with a payload byte.
    shm.map[o + 5] = 0x10
    shm.map[o + m.FRAME_LEN - 1] = 0x81
    m.MatrixUI._accumulate_leds(stub)
    assert (m.BOARD_LED, 0x81) in stub._led_pages
    assert len(stub._led_buf) == m.FRAME_LEN - 1
    assert stub._led_buf[5] == 0x10

    # A different page id is retained alongside the first (shim keeps only the
    # last frame, so the UI must accumulate).
    shm.map[o + 5] = 0
    shm.map[o + 7] = 0x3f
    shm.map[o + m.FRAME_LEN - 1] = 0x82
    m.MatrixUI._accumulate_leds(stub)
    assert len(stub._led_pages) == 2
    assert len(stub._led_buf) == 2 * (m.FRAME_LEN - 1)


def test_rgb_hex_and_colour(m):
    assert m.MatrixUI._rgb_hex(10, 20, 30) == "#0a141e"
    assert m.MatrixUI._rgb_hex(255, 255, 255) == "#ffffff"
    stub = types.SimpleNamespace(lamps=[{"index": 0}])
    stub.led_rgb = lambda i, b: (0, 0, 0)
    stub._rgb_hex = m.MatrixUI._rgb_hex
    assert m.MatrixUI._led_colour(stub, 0, b"\x00" * 8) == m.LED_DARK


def test_resolve_keymap_targets_direct_switches(m):
    switches = {
        (3, 0x01): {"symbol": "dswitch_start", "name": "Start Button"},
        (2, 0x01): {"symbol": "dswitch_coin_1", "name": "1st Coin"},
        (1, 0x01): {"symbol": "dswitch_l_flipper_lo", "name": "Left Flipper Lo"},
        (1, 0x04): {"symbol": "dswitch_r_flipper_lo", "name": "Right Flipper Lo"},
        (10, 0x02): {"symbol": "switch_shooter", "name": "Shooter Lane", "x": 1, "y": 2},
    }
    res = m.MatrixUI._resolve_keymap(types.SimpleNamespace(switches=switches))
    got = {label: key for (_ks, label, key) in res}
    assert got["Start"] == (3, 0x01)
    assert got["Coin"] == (2, 0x01)
    assert got["L Flipper"] == (1, 0x01)
    assert got["R Flipper"] == (1, 0x04)
    # No menu switches present -> those shortcuts are left unmapped.
    assert got["Menu Enter"] is None
    assert got["Menu +"] is None
    # The shooter is NOT here: it is a ball action, not a switch pulse - a
    # shooter lane you pulse is a ball that appears and vanishes.
    assert "Shooter" not in got
    assert [label for _ks, label, _a in m.BALL_KEYS] == ["Plunge", "Drain"]


def test_find_switch_prefers_the_exact_symbol(m):
    switches = {
        (3, 0x02): {"symbol": "dswitch_coin_door_open", "name": "Coin Door Open"},
        (2, 0x01): {"symbol": "dswitch_coin_1", "name": "1st Coin"},
    }
    stub = types.SimpleNamespace(switches=switches)
    find = m.MatrixUI._find_switch
    assert find(stub, ("dswitch_coin_door_open", "coin_door")) == (3, 0x02)
    assert find(stub, ("nothing_like_this",)) is None


def test_key_label_dedups(m):
    assert m.MatrixUI._key_label(("Return", "KP_Enter")) == "Enter"
    assert m.MatrixUI._key_label(("Left", "a")) == "\u2190/a"
    assert m.MatrixUI._key_label(("1",)) == "1"


def test_default_geometry_is_generous_and_clamped(m):
    class FakeRoot:
        def __init__(self, w, h):
            self._w, self._h = w, h

        def update_idletasks(self):
            pass

        def winfo_screenwidth(self):
            return self._w

        def winfo_screenheight(self):
            return self._h

    import re
    # On a big screen it opens at the full DEFAULT_W x DEFAULT_H.
    g = m.MatrixUI._default_geometry(types.SimpleNamespace(root=FakeRoot(3840, 2160)))
    mo = re.match(r"^(\d+)x(\d+)$", g)
    assert mo and (int(mo.group(1)), int(mo.group(2))) == (m.DEFAULT_W, m.DEFAULT_H)
    # On a small screen it is clamped to fit, never larger than the screen.
    g2 = m.MatrixUI._default_geometry(types.SimpleNamespace(root=FakeRoot(1280, 800)))
    w2, h2 = (int(x) for x in g2.split("x"))
    assert w2 <= 1280 - 80 and h2 <= 800 - 80


def test_all_open_returns_the_machine_to_rest(m, shm):
    # "All open" must not leave the game in BALL TROUGH ERROR with its coin
    # door hanging open - neither is a state a machine is ever in.
    seated = [(4, 0x01), (4, 0x40)]
    feeder = types.SimpleNamespace(seat_trough=lambda: seated)
    stub = types.SimpleNamespace(shm=shm, latched={(9, 0x01)},
                                 door=(3, 0x02), feeder=feeder)
    shm.set_switch(9, 0x01, True)
    m.MatrixUI.all_open(stub)
    assert shm.get_switch(9, 0x01) is False     # the stray latch is gone
    assert shm.get_switch(3, 0x02) is True      # door shut
    assert stub.latched == {(3, 0x02), (4, 0x01), (4, 0x40)}
