r"""Pop-out DMD + switch windows for the Spike 1 emulator.

Pure pieces (the UNC path, the run-dir reads/writes) plus a headless smoke test
of the two Tk windows.  The windows read the emulator's run-dir over the
``\\wsl.localhost\<distro>\...`` UNC path; the I/O is tested against local temp
files by pointing ``_unc`` at them.
"""

import pytest

from pinball_decryptor.gui import spike1_windows as W
from pinball_decryptor.plugins.stern.spike1_emulate import SwitchInput, addr


def test_wsl_unc_flips_slashes_and_prefixes_the_distro():
    p = W.wsl_unc("Ubuntu", "/home/david/s1emu/spi0.cap")
    assert p == r"\\wsl.localhost\Ubuntu\home\david\s1emu\spi0.cap"


def test_wsl_unc_without_a_distro_is_none():
    assert W.wsl_unc("", "/home/x") is None
    assert W.wsl_unc(None, "/home/x") is None


def _io_on(tmp_path, monkeypatch):
    io = W._RunDirIO("/home/david/s1emu", "Ubuntu")
    monkeypatch.setattr(io, "_unc", lambda name: str(tmp_path / name))
    return io


def test_tail_frame_returns_the_last_whole_frame(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    (tmp_path / "spi0.cap").write_bytes(
        bytes([1]) * 2048 + bytes([2]) * 2048 + bytes([3]) * 2048)
    assert io.tail_frame("spi0.cap", 2048) == bytes([3]) * 2048


def test_tail_frame_none_when_short_or_absent(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    assert io.tail_frame("spi0.cap", 2048) is None        # absent
    (tmp_path / "spi0.cap").write_bytes(b"\x00" * 100)    # < one frame
    assert io.tail_frame("spi0.cap", 2048) is None


def test_write_injected_is_a_switchinput_block(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    io.write_injected({addr(8, 3), addr(9, 0)}, seq=5)
    closed, seq = SwitchInput.unpack((tmp_path / "s1sw.input").read_bytes())
    assert closed == {addr(8, 3), addr(9, 0)}
    assert seq == 5


def test_read_state_missing_is_empty_not_an_error(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    st = io.read_state()                                   # no s1hw.state
    assert not any(st.switches) and not any(st.lamps)


# --------------------------------------------------------------- widgets --

@pytest.fixture(scope="module")
def root():
    """ONE Tk root for the whole module (matches tests/test_jjp_emulate_tab.py)."""
    tk = pytest.importorskip("tkinter")
    from tests.conftest import make_tk_root
    try:
        # retried: one transient Tcl-script read miss must not skip the
        # whole module (pytest caches a module fixture's skip) - see
        # make_tk_root
        r = make_tk_root(tk)
    except Exception:                                       # noqa: BLE001
        pytest.skip("no usable Tk display")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except Exception:                                       # noqa: BLE001
        pass


class _FakeIO:
    """A run-dir I/O that serves a canned frame / state and records writes."""

    def __init__(self, frame=None, state=None, names=None):
        self._frame = frame
        self._state = state
        self._names = names or {}
        self.writes = []

    def tail_frame(self, name, frame_bytes):
        return self._frame

    def read_state(self):
        from pinball_decryptor.plugins.stern.spike1_emulate import HardwareState
        return self._state or HardwareState()

    def write_injected(self, closed_slots, seq):
        self.writes.append((set(closed_slots), seq))

    def read_switch_names(self):
        return dict(self._names)

    def append_ball_cmd(self, line):
        self.ball_cmds = getattr(self, "ball_cmds", [])
        self.ball_cmds.append(line)
        return True


def _decode():
    # load the rig's decoder by path, the way the tab does
    import importlib.util
    import os
    from pinball_decryptor.gui.spike1_emulate_tab import rig_dir
    p = os.path.join(rig_dir(), "s1dmd.py")
    spec = importlib.util.spec_from_file_location("s1dmd_probe", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.decode_frame


def test_display_window_shows_a_frame(root):
    pytest.importorskip("PIL")
    frame = bytearray(2048)
    frame[0] = 0x80                       # plane0 byte0 bit7 -> pixel (0,0) lit
    io = _FakeIO(frame=bytes(frame))
    win = W.Spike1DisplayWindow(root, io, _decode(), hz=50)
    win.update()
    assert win._photo is not None
    win.close()
    assert win._closed is True


def test_switch_window_click_injects_a_switch(root):
    io = _FakeIO()
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.update()
    # Window MAPPING goes through the real window manager and is
    # asynchronous: on a busy desktop (parallel test workers churning
    # windows) the Toplevel can still be unviewable here, and Tk silently
    # drops a synthetic <Button-1> aimed at an unviewable canvas - the
    # 2026-09-01 -n auto runs failed exactly that way, twice.  Wait for
    # viewability before clicking.
    import time
    for _ in range(200):
        if win._canvas.winfo_viewable():
            break
        win.update()
        time.sleep(0.01)
    # click the first switch cell (kind 'sw', node 8, index 0)
    rid = win._cells[("sw", 8, 0)]
    x0, y0, x1, y1 = win._canvas.coords(rid)
    win._canvas.event_generate("<Button-1>",
                               x=int((x0 + x1) / 2), y=int((y0 + y1) / 2))
    win.update()
    assert io.writes, "a click should write an injected-switch block"
    closed, _seq = io.writes[-1]
    assert addr(8, 0) in closed
    win.close()


def test_switch_window_shows_default_nodes(root):
    io = _FakeIO()
    win = W.Spike1SwitchWindow(root, io, nodes=(0, 8, 9))
    win.update()
    assert ("sw", 0, 0) in win._cells
    assert ("sw", 9, 0) in win._cells
    win.close()


def test_read_switch_names_parses_the_json(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    (tmp_path / "s1switches.json").write_text(
        '{"9,5": "START BUTTON", "1,20": "SHOOTER LANE"}', encoding="utf-8")
    names = io.read_switch_names()
    assert names[(9, 5)] == "START BUTTON"
    assert names[(1, 20)] == "SHOOTER LANE"


def test_read_switch_names_missing_is_empty(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    assert io.read_switch_names() == {}


def test_named_title_lists_switches_by_position_and_name(root):
    # A curated title shows the LIST (David: the giant matrix was unusable —
    # "list them out by name and position like we do on spike 2").
    io = _FakeIO(names={(1, 20): "SHOOTER LANE", (1, 11): "START BUTTON"})
    win = W.Spike1SwitchWindow(root, io, nodes=(1,))
    win.update()
    slots = {r["slot"] for r in win._list_rows}
    assert slots == {addr(1, 20), addr(1, 11)}
    texts = {win._canvas.itemcget(r["name"], "text") for r in win._list_rows}
    assert texts == {"SHOOTER LANE", "START BUTTON"}
    poss = {win._canvas.itemcget(r["pos"], "text") for r in win._list_rows}
    assert poss == {"1,20", "1,11"}
    win.close()


def test_list_click_toggles_the_switch(root):
    io = _FakeIO(names={(1, 11): "START BUTTON"})
    win = W.Spike1SwitchWindow(root, io, nodes=(1,))
    win.update()
    row = win._list_rows[0]
    x0, y0, x1, y1 = win._canvas.coords(row["box"])
    win._canvas.event_generate("<Button-1>", x=int((x0 + x1) / 2),
                               y=int((y0 + y1) / 2))
    win.update()
    assert io.writes and addr(1, 11) in io.writes[-1][0]
    win.close()


def test_list_click_is_momentary_not_a_hold(root):
    """A click pulses the switch for PULSE_S then releases it on its own
    (David: "should only activate it momentarily, not hold it indefinitely
    until clicked again")."""
    import time
    io = _FakeIO(names={(1, 11): "START BUTTON"})
    win = W.Spike1SwitchWindow(root, io, nodes=(1,))
    win.PULSE_S = 0.01
    win.update()
    row = win._list_rows[0]
    x0, y0, x1, y1 = win._canvas.coords(row["box"])
    win._canvas.event_generate("<Button-1>", x=int((x0 + x1) / 2),
                               y=int((y0 + y1) / 2))
    win.update()
    # The press and the timed release are separate writes, and on a slow
    # machine the first update() can already have run the 10ms release
    # timer - peeking at "the last write" between the two races the pulse
    # (it lost on two CI OSes the day the suite went parallel).  The
    # contract is the SEQUENCE: closed at some point, open on its own at
    # the end.
    assert io.writes and any(addr(1, 11) in w[0] for w in io.writes)  # closed…
    for _ in range(50):
        time.sleep(0.01)
        win.update()
        if addr(1, 11) not in io.writes[-1][0]:
            break
    assert addr(1, 11) not in io.writes[-1][0]                # …open again
    win.close()


def test_list_right_click_holds_until_right_clicked_again(root):
    io = _FakeIO(names={(1, 11): "START BUTTON"})
    win = W.Spike1SwitchWindow(root, io, nodes=(1,))
    win.update()
    row = win._list_rows[0]
    x0, y0, x1, y1 = win._canvas.coords(row["box"])
    mid = {"x": int((x0 + x1) / 2), "y": int((y0 + y1) / 2)}
    win._canvas.event_generate("<Button-3>", **mid)
    win.update()
    assert addr(1, 11) in io.writes[-1][0]                    # held
    win._canvas.event_generate("<Button-3>", **mid)
    win.update()
    assert addr(1, 11) not in io.writes[-1][0]                # released
    win.close()


def test_nameless_title_falls_back_to_the_grid(root):
    io = _FakeIO()
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.update()
    assert ("sw", 8, 0) in win._cells
    win.close()


def test_switch_window_readout_names_the_hovered_switch(root):
    io = _FakeIO(names={(9, 5): "START BUTTON"})
    win = W.Spike1SwitchWindow(root, io, nodes=(9,))
    win.update()
    win._describe(9, 5)
    assert "START BUTTON" in win._readout.cget("text")
    win._describe(9, 0)                       # an unassigned position
    assert "unassigned" in win._readout.cget("text")
    win.close()


# --------------------------------------------------------- play controls --

_PLAY_NAMES = {(8, 2): "L. FLIPPER BUTTON", (8, 3): "R. FLIPPER BUTTON",
               (1, 11): "START BUTTON", (1, 16): "LEFT COIN SLOT",
               (9, 1): "SHOOTER LANE"}


def _row(win, keysym):
    return next(r for r in win._key_rows if r["keysym"] == keysym)


def test_key_rows_resolve_from_the_switch_names(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    assert _row(win, "Left")["slot"] == addr(8, 2)
    assert _row(win, "Right")["slot"] == addr(8, 3)
    assert _row(win, "1")["slot"] == addr(1, 11)
    assert _row(win, "5")["slot"] == addr(1, 16)
    assert _row(win, "f")["slot"] == addr(9, 1)
    assert _row(win, "Up")["slot"] is None       # not named on this title
    win.close()


def test_key_press_and_release_write_the_held_state(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.press_key("Left")
    win.press_key("Left")                     # key auto-repeat: no extra write
    assert [w[0] for w in io.writes] == [{addr(8, 2)}]
    win.press_key("Right")
    assert io.writes[-1][0] == {addr(8, 2), addr(8, 3)}
    win.release_key("Left")
    assert io.writes[-1][0] == {addr(8, 3)}
    win.close()


def test_keys_merge_with_clicked_cells(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win._injected.add(addr(8, 9))             # a clicked (held) cell
    win.press_key("Right")
    assert io.writes[-1][0] == {addr(8, 9), addr(8, 3)}
    win.release_key("Right")
    assert io.writes[-1][0] == {addr(8, 9)}   # the click survives the key
    win.close()


def test_unnamed_rows_are_inert(root):
    io = _FakeIO(names={(9, 5): "10 POINTS"})
    win = W.Spike1SwitchWindow(root, io, nodes=(9,))
    win.press_key("Left")                     # no error, no write
    assert io.writes == []
    win.close()


def test_service_and_door_keys_go_to_the_keeper(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.press_key("Return")
    win.release_key("Return")
    win.press_key("minus")
    win.release_key("minus")
    win.press_key("c")
    win.press_key("b")
    assert io.ball_cmds == ["svc select", "svc minus", "door toggle",
                            "trough toggle"]
    assert io.writes == []                    # none of these are slot holds
    win.close()


def test_ball_buttons_queue_daemon_commands(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win._ball_cmd("coin 1")
    assert "coin 1" in win._readout.cget("text")
    win._ball_cmd("plunge")
    assert io.ball_cmds == ["coin 1", "plunge"]
    win.close()


def test_trough_click_fills_or_empties_to_the_ball(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win._ball_state = {"balls": 2}
    win._ball_click(4)                        # click empty ball 5 -> fill to 5
    win._ball_state = {"balls": 6}
    win._ball_click(2)                        # click full ball 3 -> empty to 2
    assert io.ball_cmds == ["trough 5", "trough 2"]
    win.close()


def test_append_ball_cmd_appends_lines(tmp_path, monkeypatch):
    io = _io_on(tmp_path, monkeypatch)
    assert io.append_ball_cmd("coin 3") is True
    assert io.append_ball_cmd("start") is True
    assert (tmp_path / "s1ball.cmd").read_text() == "coin 3\nstart\n"


# ------------------------------------------------- a map that arrives late --
# On a title with no curated map the rig walks the switch names out of the
# RUNNING game, so s1switches.json shows up minutes after this window opened.
# Reading it once at __init__ left such a title nameless and its play keys dead
# for the whole session even though the names were sitting in the run dir
# (PAD-101).

def test_switch_window_adopts_a_map_that_arrives_later(root):
    io = _FakeIO()                            # no names yet: the raw grid
    win = W.Spike1SwitchWindow(root, io, nodes=(1, 8, 9))
    win.update()
    assert ("sw", 8, 0) in win._cells
    assert _row(win, "1")["slot"] is None     # Start is inert without names

    io._names = dict(_PLAY_NAMES)             # the walk lands
    assert win._refresh_names() is True
    win.update()
    assert {r["slot"] for r in win._list_rows} == {
        addr(n, i) for (n, i) in _PLAY_NAMES}
    assert _row(win, "1")["slot"] == addr(1, 11)     # ... and the keys work
    win.press_key("1")
    assert io.writes[-1][0] == {addr(1, 11)}
    win.close()


def test_switch_window_polls_for_the_map_while_it_runs(root):
    io = _FakeIO()
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.update()
    io._names = dict(_PLAY_NAMES)
    if win._job is not None:                  # drive the tick ourselves; the
        win.after_cancel(win._job)            # scheduled one would outlive us
    win._names_tick = win.NAMES_EVERY - 1     # the next tick is a look
    win._tick()
    assert win._names == _PLAY_NAMES
    assert _row(win, "Left")["slot"] == addr(8, 2)
    win.close()


def test_switch_window_ignores_an_unchanged_map(root):
    io = _FakeIO(names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.update()
    rows = win._list_rows
    assert win._refresh_names() is False      # same map: no rebuild
    assert win._list_rows is rows
    win.close()


# ------------------------------------------ the 2012 home models' names --
# Their switch map names the flippers "LEFT FLIPPER" (with "LEFT FLIPPER
# EOS" beside them) and the start button "START"; the play keys must resolve
# on those as well as on the DMD generation's "L. FLIPPER BUTTON" / "START
# BUTTON" (PAD-101).

_EARLY_NAMES = {(8, 1): "LEFT FLIPPER EOS", (8, 2): "RIGHT FLIPPER EOS",
                (8, 4): "TILT", (8, 12): "SHOOTER LANE", (8, 21): "START",
                (8, 26): "LEFT FLIPPER", (8, 39): "RIGHT FLIPPER",
                (8, 42): "SHOOTER LANE EXIT"}


def test_key_rows_resolve_on_the_early_era_names(root):
    io = _FakeIO(names=_EARLY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    assert _row(win, "Left")["slot"] == addr(8, 26)      # not the EOS switch
    assert _row(win, "Right")["slot"] == addr(8, 39)
    assert _row(win, "1")["slot"] == addr(8, 21)
    assert _row(win, "t")["slot"] == addr(8, 4)
    assert _row(win, "f")["slot"] == addr(8, 12)         # not the lane EXIT
    win.close()


def test_key_rows_still_resolve_on_the_dmd_generation_names(root):
    io = _FakeIO(names={**_PLAY_NAMES, (8, 0): "LEFT FLIPPER E.O.S."})
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    assert _row(win, "Left")["slot"] == addr(8, 2)       # L. FLIPPER BUTTON
    assert _row(win, "1")["slot"] == addr(1, 11)
    win.close()


# ---------------------------------------------- the alphanumeric display --

class _AlphaIO(_FakeIO):
    def __init__(self, display, frame):
        super().__init__(frame=frame)
        self._display = display

    def read_text(self, name):
        return self._display if name == "s1display" else ""


def _alpha_mod():
    import importlib.util
    import os
    from pinball_decryptor.gui.spike1_emulate_tab import rig_dir
    p = os.path.join(rig_dir(), "s1alpha.py")
    spec = importlib.util.spec_from_file_location("s1alpha_probe", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_display_window_draws_16_segment_frames_in_alpha_mode(root):
    pytest.importorskip("PIL")
    m = _alpha_mod()
    fr = bytearray(256)
    fr[0] = 0x80                          # digit 0, segment 0 (g1), bit 0
    win = W.Spike1DisplayWindow(root, _AlphaIO("alphanumeric", bytes(fr)),
                                _decode(), hz=50,
                                alpha=(m.decode_frame, m.render_image))
    win.update()
    assert win._frame_bytes == 256
    assert win._photo is not None
    assert "display" in win.title()
    win.close()


def test_viewers_pick_alpha_only_when_the_run_dir_says_so(root, monkeypatch):
    pytest.importorskip("PIL")
    m = _alpha_mod()
    made = []
    monkeypatch.setattr(W, "Spike1DisplayWindow",
                        lambda master, io, decode, alpha=None, on_close=None:
                        made.append(alpha) or _Dummy())
    monkeypatch.setattr(W, "Spike1SwitchWindow",
                        lambda master, io, on_close=None: _Dummy())
    for display, expect in (("alphanumeric", True), ("dotmatrix", False), ("", False)):
        v = W.Spike1Viewers(lambda: root, _decode(),
                            alpha=(m.decode_frame, m.render_image))
        v._io = _AlphaIO(display, None)
        v.open()
        assert (made[-1] is not None) is expect, display


class _Dummy:
    _closed = False

    def winfo_exists(self):
        return True

    def bind_play_keys(self, w):
        pass


# ------------------------------------------- the display window's KIND -----
# The rig only says which display the machine has (s1display) once the game is
# extracted, which is AFTER the windows first open.  A DMD window fed this
# era's 256-byte frames reads eight of them as one 2048-byte frame and draws
# stripes, so the viewers must SWAP it, not leave it up (PAD-101).

class _ModeIO(_FakeIO):
    def __init__(self, display=""):
        super().__init__()
        self.display = display

    def read_text(self, name):
        return self.display if name == "s1display" else ""

    def read_json(self, name):
        return None


def _viewers(root, io, alpha=("d", "r")):
    v = W.Spike1Viewers(lambda: root, _decode(), alpha=alpha)
    v._io = io
    return v


def test_display_mode_follows_the_run_dir(root):
    io = _ModeIO("")
    v = _viewers(root, io)
    assert v.display_mode() == "dmd"
    io.display = "alphanumeric"
    assert v.display_mode() == "alpha"
    io.display = "dotmatrix"
    assert v.display_mode() == "dmd"


def test_a_dmd_window_is_swapped_when_the_marker_arrives(root, monkeypatch):
    made = []

    class _W:
        _closed = False

        def __init__(self, master, io, decode, alpha=None, on_close=None):
            self.alpha = alpha
            self.closed = False
            made.append(self)

        def winfo_exists(self):
            return True

        def close(self):
            self.closed = self._closed = True

        def bind_play_keys(self, w):
            pass

    monkeypatch.setattr(W, "Spike1DisplayWindow", _W)
    monkeypatch.setattr(W, "Spike1SwitchWindow", _W)
    monkeypatch.setattr(W.sys, "platform", "win32")
    io = _ModeIO("")                       # the rig has not said yet
    v = _viewers(root, io)
    v.open()
    first = v._dmd
    assert first.alpha is None and v._dmd_mode == "dmd"

    v.open()                               # same mode: keep the window
    assert v._dmd is first and not first.closed

    io.display = "alphanumeric"            # the rig writes the marker
    v.open()
    assert first.closed, "the stale DMD window must be closed"
    assert v._dmd is not first and v._dmd.alpha is not None
    assert v._dmd_mode == "alpha"


def test_orphaned_windows_from_a_rebuilt_panel_are_closed(root, monkeypatch):
    """Switching era badges rebuilds the panel with a fresh Spike1Viewers; the
    previous one's windows had nothing left to close them."""
    monkeypatch.setattr(W.sys, "platform", "win32")
    io = _ModeIO("")
    old = _viewers(root, io)
    old.open()                              # real windows, parented to root
    orphan_dmd, orphan_sw = old._dmd, old._sw
    assert orphan_dmd is not None and orphan_sw is not None

    fresh = _viewers(root, _ModeIO(""))     # the rebuilt panel's viewers
    fresh.open()
    root.update()
    assert orphan_dmd._closed and orphan_sw._closed
    assert not fresh._dmd._closed
    fresh.close()


# --------------------------------- service controls the machine really has --
# The 2012 home models have no coin-door switch and no service buttons (their
# 46 node-8 switches are all playfield/cabinet), and no operator menu: TestMode
# is entered by holding BOTH FLIPPERS for 3 s.  Offering the DMD generation's
# BACK/-/+/SELECT cluster and coin-door bar there sent David hunting for a
# door-and-SELECT menu that cannot exist (PAD-101).

class _EraIO(_FakeIO):
    def __init__(self, era, names=None):
        super().__init__(names=names)
        self.era = era

    def read_text(self, name):
        return self.era if name == "s1era" else ""


def test_service_keys_are_inert_on_the_early_era(root):
    io = _EraIO("early", names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.press_key("Return")          # SELECT
    win.press_key("BackSpace")       # BACK
    win.press_key("c")               # coin door
    assert not hasattr(io, "ball_cmds") or io.ball_cmds == []
    win.close()


def test_service_keys_still_work_on_the_dmd_generation(root):
    io = _EraIO("dmd", names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    win.press_key("Return")
    win.press_key("c")
    assert io.ball_cmds == ["svc select", "door toggle"]
    win.close()


def test_the_early_panel_says_how_to_open_test_mode(root):
    io = _EraIO("early", names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    shown = {win._panel.itemcget(i, "text")
             for i in win._panel.find_all()
             if win._panel.type(i) == "text"}
    assert any("hold both flippers" in t.lower() for t in shown)
    assert not any("COIN DOOR" in t for t in shown)
    win.close()


def test_the_dmd_panel_still_shows_the_coin_door(root):
    io = _EraIO("dmd", names=_PLAY_NAMES)
    win = W.Spike1SwitchWindow(root, io, nodes=(8,))
    shown = {win._panel.itemcget(i, "text")
             for i in win._panel.find_all()
             if win._panel.type(i) == "text"}
    assert any("COIN DOOR" in t for t in shown)
    win.close()
