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


def test_led_level_uses_the_measured_full_scale(m):
    """THE fix for "the LEDs jump between colours instead of fading".

    The scale used to be x4, on the belief the values were 6-bit.  They are not:
    measured over 15,393 samples of live traffic the payload runs to 0x80, and
    2.5% of bytes sit above 0x3f.  Scaling by 4 pinned EVERY value from 0x40 up
    to 255 - the whole bright half of the range collapsed onto one colour, so a
    lamp climbing through it appeared to snap straight to full.
    """
    assert m.LED_FULL == 0x80
    assert m.led_level(0) == 0
    assert m.led_level(m.LED_FULL) == 255
    assert m.led_level(0x40) == 127                 # half scale, was 255
    # The values that used to collapse together must now be distinct and ordered.
    collapsed = [0x40, 0x60, 0x70, 0x7f, 0x80]
    got = [m.led_level(v) for v in collapsed]
    assert len(set(got)) == len(collapsed), got
    assert got == sorted(got)
    assert all(0 <= v <= 255 for v in got)
    # Never over-range, whatever the byte.
    assert m.led_level(0xff) == 255


def test_led_rgb_reads_scales_and_wraps(m, shm):
    o = m.OFF_OUT + m.BOARD_LED * m.FRAME_LEN
    shm.map[o + 6], shm.map[o + 7], shm.map[o + 8] = 0x10, 0x20, 0x30
    off = m.OFF_OUT_CHANGES + m.BOARD_LED * 4
    shm.map[off:off + 4] = (1).to_bytes(4, "little")
    buf = shm.led_buffer()
    stub = types.SimpleNamespace(lamps=[{"index": 0}, {"index": 2}])
    # A lamp is three bytes at index*3; index 2 -> byte 6.
    assert m.MatrixUI.led_rgb(stub, 1, buf) == (
        m.led_level(0x10), m.led_level(0x20), m.led_level(0x30))
    assert m.MatrixUI.led_rgb(stub, 0, b"") == (0, 0, 0)      # empty -> black
    # A full-scale byte reaches full, and nothing exceeds it.
    shm.map[o + 0] = m.LED_FULL
    buf = shm.led_buffer()
    big = types.SimpleNamespace(lamps=[{"index": len(buf)}])   # index*3 % n == 0
    assert m.MatrixUI.led_rgb(big, 0, buf)[0] == 255


def test_the_pages_are_read_faster_than_they_are_drawn(m):
    """Sampling and repainting are two different rates.

    The game rewrites the LED frame ~2,139 times a second across 11 pages and
    the shim keeps only the LATEST, so one look yields one page.  Reading once
    per 100 ms repaint saw ~6 pages a second - each lamp refreshed about every
    1.8 s - which aliases every fade into a jump between two distant samples.
    """
    assert m.LED_POLL_MS < 100                       # faster than the repaint
    assert 11 * m.LED_POLL_MS < 500                  # a full cycle inside ~0.5s
    import inspect
    src = inspect.getsource(m.MatrixUI._led_poll)
    assert "_accumulate_leds" in src
    assert "LED_POLL_MS" in src
    # ...and tick() must NOT also gather them, or the rate is a lie.
    assert "_accumulate_leds" not in inspect.getsource(m.MatrixUI.tick)


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


def test_there_is_one_lamp_colour_path(m):
    """``_rgb_hex``/``_led_colour`` painted the raw value and are gone with it.
    Two ways to turn a lamp into a colour is two places to fix the next time
    the rendering changes - and the raw-value one is the bug that was just
    removed, so leaving it callable invites its return."""
    assert not hasattr(m.MatrixUI, "_rgb_hex")
    assert not hasattr(m.MatrixUI, "_led_colour")
    assert hasattr(m.MatrixUI, "_lamp_paint") and callable(m.blend)


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


def test_in_use_drops_the_addresses_the_title_never_wired(m):
    """The table lists switches the game NAMES.  Wonka names 69 of its 296
    addresses and calls the other 227 "not used", so showing them all buries
    the real ones in seven times their number of blanks."""
    assert m.in_use({"name": "6-Ball Trough #5"}) is True
    assert m.in_use({"name": "not used"}) is False
    assert m.in_use({"name": "NOT USED"}) is False      # case is not meaning
    assert m.in_use({"name": "  not used  "}) is False
    assert m.in_use({"name": ""}) is False              # unnamed == unused
    assert m.in_use({}) is False


def test_the_right_column_has_one_fixed_width_derived_from_its_columns(m):
    """The switch column is a FIXED width, and that is load-bearing.

    It used to be as wide as its widest child wanted to be - and three of those
    children rewrite their text on every 100 ms tick (ball state, ball log, LED
    note).  So the column grew and shrank as the WORDING changed, the playfield
    beside it was handed a different width each time, and the photograph
    rescaled under the pointer while nothing on the machine had moved.  Measured
    with the pin removed, the column swung 540 -> 852 -> 442 px and the
    playfield lurched 878 -> 566 -> 976.
    """
    assert m.RIGHT_W == sum(w for _id, _h, w, _a in m.TREE_COLS) + m.SCROLLBAR_W
    ids = [c[0] for c in m.TREE_COLS]
    assert ids[0] == "#0"                    # the tree's built-in first column
    assert len(set(ids)) == len(ids)
    assert all(w > 0 for _id, _h, w, _a in m.TREE_COLS)

    import inspect
    src = inspect.getsource(m.MatrixUI._build_right)
    # The frame is given the width AND told not to let its children change it;
    # either half alone leaves the column free to move.
    assert "width=RIGHT_W" in src
    assert "pack_propagate(False)" in src


def test_the_ball_buttons_do_not_share_a_row_with_the_status_line(m):
    """Plunge was showing as "ge (Sp".

    It sat beside the ball status line, which packs first with expand=True and
    so claims the whole row - the buttons got whatever was left, which was not
    enough.  It was never going to fit either: the status text alone is ~300 px
    of a 442 px column and the two buttons want ~200 more.  So the buttons get
    their own row and split it evenly.
    """
    import inspect
    src = inspect.getsource(m.MatrixUI._build_ball_panel)
    # The status line is packed straight onto the column, not into the button
    # row - if it goes back into a shared frame it will squeeze them again.
    assert "self.ball_state.pack(anchor='w', fill='x')" in src
    # Both buttons share their row equally and are allowed to grow into it.
    assert src.count("fill='x', expand=True") >= 1
    body = src[src.index("row = tk.Frame"):]
    assert "expand=True" in body
    # Buttons are explicitly coloured - a default Tk button is light grey and
    # reads as disabled on this dark panel.
    assert "BTN_BG" in src and "BTN_FG" in src


def test_button_colour_does_not_collide_with_switch_state(m):
    """Green already means CLOSED here (a closed row, a closed marker), so a
    green button under the green trough rows reads as state, not a control."""
    assert m.BTN_BG not in (m.ROW_CLOSED, m.MARK_ON, m.MARK_OFF)
    # And it must actually stand out from the panel it sits on.
    assert m.BTN_BG != m.BG and m.BTN_BG != m.PANEL
    for colour in (m.BTN_BG, m.BTN_FG, m.BTN_ACTIVE):
        assert len(colour) == 7 and colour.startswith("#")
    # Blue-dominant, i.e. not another shade of the green that means "closed".
    r, g, b = m._hex_rgb(m.BTN_BG)
    assert b > g and b > r


def test_the_variable_length_notes_wrap_instead_of_widening(m):
    """A note that cannot wrap asks for the width of its longest line, which is
    the other half of how the column used to move."""
    import inspect
    for label, method in (("ball_note", m.MatrixUI._build_ball_panel),
                          ("led_note", m.MatrixUI._build_led_panel)):
        src = inspect.getsource(method)
        i = src.index("self.%s = tk.Label" % label)
        assert "wraplength" in src[i:i + 400], "%s must wrap" % label


def test_drawable_coils_skips_the_unmapped_sentinel_byte(m):
    """Frame byte 255 is the game's UNMAPPED sentinel - the same one the switch
    table uses for dswitch_null - and coils land on it too: Wonka parks its
    three elevator coils there, all on one address.

    They carry POSITIONS, so nothing else excludes them, and out_rise reads 0
    for an out-of-frame byte - so they would draw as markers that can never
    flash.  That is worse than leaving them out: on a view whose whole point is
    showing the game driving the machine, a coil that never lights reads as a
    coil the game is not driving.
    """
    coils = [
        {"symbol": "coil_vuk_trough", "frame_byte": 1, "frame_bit": 0x10,
         "x": 10, "y": 20},
        {"symbol": "coil_vuk_elevator", "frame_byte": 255, "frame_bit": 0x80,
         "x": 139, "y": 48},                        # the sentinel - dropped
        {"symbol": "coil_knocker", "frame_byte": 2, "frame_bit": 0x01,
         "x": None, "y": None},                     # real, but nowhere to draw
        {"symbol": "coil_no_addr", "frame_byte": None, "frame_bit": None,
         "x": 5, "y": 5},
        {"symbol": "coil_zero_bit", "frame_byte": 3, "frame_bit": 0,
         "x": 5, "y": 5},
    ]
    got = [c["symbol"] for c in m.drawable_coils(coils)]
    assert got == ["coil_vuk_trough"]
    assert m.drawable_coils(None) == []
    assert m.drawable_coils([]) == []
    # The boundary itself: the last byte IN frame is kept, the first out is not.
    edge = [{"symbol": "in", "frame_byte": m.FRAME_LEN - 1, "frame_bit": 1,
             "x": 1, "y": 1},
            {"symbol": "out", "frame_byte": m.FRAME_LEN, "frame_bit": 1,
             "x": 1, "y": 1}]
    assert [c["symbol"] for c in m.drawable_coils(edge)] == ["in"]


def test_blend_resolves_alpha_to_a_solid_colour(m):
    """Tk canvas items have no alpha channel, so translucency has to be
    resolved before it is drawn."""
    assert m.blend((255, 0, 0), (0, 0, 0), 1.0) == "#ff0000"      # opaque
    assert m.blend((255, 0, 0), (0x11, 0x22, 0x33), 0.0) == "#112233"   # clear
    assert m.blend((255, 255, 255), (0, 0, 0), 0.5) == "#808080"  # halfway
    # Out-of-range alphas clamp rather than producing an impossible colour.
    assert m.blend((255, 0, 0), (0, 0, 0), 5.0) == "#ff0000"
    assert m.blend((255, 0, 0), (0, 0, 0), -3.0) == "#000000"


def test_lamp_paint_draws_brightness_as_opacity(m):
    """THE fix for "the LEDs have no alpha levels".

    Painting the raw value made every level below about half look like the same
    flat near-black blob on a dark photograph.  Compositing over the photo means
    a dim lamp is a FAINT version of its own colour, which is what dim looks
    like, and the hue survives all the way down.
    """
    stub = types.SimpleNamespace(
        lamps=[{"index": 0}], _lamp_bg=[(200, 200, 200)],   # a pale background
        led_rgb=lambda i, buf: buf)                          # buf IS the rgb
    paint = m.MatrixUI._lamp_paint
    full = paint(stub, 0, (255, 0, 0))
    half = paint(stub, 0, (128, 0, 0))
    dim = paint(stub, 0, (25, 0, 0))
    # Every level is a DIFFERENT colour - that is what "alpha levels showing up"
    # means, and what painting the raw value failed to do.
    assert len({full, half, dim}) == 3
    # Brighter is nearer the lamp's colour; dimmer is nearer the playfield.
    reds = [int(c[1:3], 16) for c in (dim, half, full)]
    greens = [int(c[3:5], 16) for c in (dim, half, full)]
    assert reds == sorted(reds)                 # red rises with brightness
    assert greens == sorted(greens, reverse=True)   # background bleeds away
    # A dim lamp keeps its HUE instead of collapsing toward grey.
    assert int(dim[1:3], 16) > int(dim[3:5], 16)
    # THE two assertions that pin the actual mechanism.  Against a PALE
    # background a dim lamp must come out LIGHTER in red than the background
    # itself - which is only true if the colour was composited (rather than
    # painted raw, giving 0x19) AND its hue was normalised to full first
    # (without which it lands at 0x9e, below the background).
    assert int(dim[1:3], 16) > 200
    assert dim == "#d59898"


def test_an_unlit_lamp_is_faint_but_not_invisible(m):
    """The layout has to be readable with the game stopped - and an invisible
    lamp cannot be hovered for its name."""
    stub = types.SimpleNamespace(lamps=[{"index": 0}], _lamp_bg=[(0, 0, 0)],
                                 led_rgb=lambda i, buf: (0, 0, 0))
    unlit = m.MatrixUI._lamp_paint(stub, 0, b"")
    assert unlit != "#000000"
    # ...but clearly dimmer than a lit one.
    lit = m.MatrixUI._lamp_paint(
        types.SimpleNamespace(lamps=[{"index": 0}], _lamp_bg=[(0, 0, 0)],
                              led_rgb=lambda i, buf: (255, 255, 255)), 0, b"x")
    assert int(unlit[1:3], 16) < int(lit[1:3], 16)


def test_tip_axis_places_after_before_or_pinned(m):
    """The tooltip follows the pointer, flips when it would run off the edge,
    and pins inside when it is too big to flip - flipping unconditionally is
    what pinned a wide tooltip to 0 no matter where the pointer was."""
    axis = m.MatrixUI._tip_axis
    assert axis(50, 100, 800, 14) == 64            # normal: past the pointer
    assert axis(790, 100, 800, 14) == 676          # near the edge: flip before
    assert axis(50, 900, 800, 14) == 0             # too wide to fit either way
    assert axis(5, 100, 80, 14) == 0               # tiny canvas: pinned inside
    assert 0 <= axis(1, 300, 1, 14)                # unmapped canvas: no crash


def test_coil_flash_reads_rising_edges_and_survives_the_wrap(m, shm):
    """A 32 ms coil pulse cannot be caught as a level by a 100 ms tick, so the
    marker is driven by the shim's rising-edge COUNT.  That count is a byte and
    WRAPS, so the test must be "different", never "greater"."""
    painted = []
    coil = {"frame_byte": 1, "frame_bit": 0x10, "name": "Trough VUK"}
    stub = types.SimpleNamespace(
        shm=shm, coils=[coil], coil_marks={0: (99, 0, 0)},
        _coil_rise={}, _coil_fires={}, _coil_flash={}, _coil_drawn={},
        pf=types.SimpleNamespace(
            itemconfig=lambda oid, **kw: painted.append(kw.get("fill"))))
    off = m.OFF_OUT_RISE + (m.BOARD_IO * m.FRAME_LEN + 1) * 8 + 4
    tick = lambda: m.MatrixUI._tick_coils(stub)                  # noqa: E731

    def settle():
        """Let any flash decay, so the NEXT flash is unambiguously new."""
        for _ in range(m.COIL_FLASH_TICKS + 1):
            tick()
        assert painted[-1] == m.COIL_OFF

    # First sight seeds the count WITHOUT flashing - otherwise every coil the
    # game ever fired appears to fire at once when this window opens - and it
    # must not be counted either, because we did not witness it.
    shm.map[off] = 200
    tick()
    assert painted == [m.COIL_OFF]
    assert stub._coil_fires.get(0, 0) == 0

    # A change lights it, and it stays lit for a few ticks so the eye catches it.
    shm.map[off] = 201
    tick()
    assert painted[-1] == m.COIL_FIRED
    assert stub._coil_fires[0] == 1

    # The counter WRAPS 255 -> 0; that is a fire, not a rewind.  The flash is
    # allowed to decay first, so a ">" instead of "!=" cannot pass this on the
    # strength of the previous flash still being lit.
    settle()
    shm.map[off] = 255
    tick()
    settle()
    shm.map[off] = 0
    tick()
    assert painted[-1] == m.COIL_FIRED

    # A tick can span several 32 ms pulses, so the count is the modular DELTA,
    # never a flat +1 - otherwise the busiest coils under-report the worst.
    settle()
    before = stub._coil_fires[0]
    shm.map[off] = 7
    tick()
    assert stub._coil_fires[0] == before + 7


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
