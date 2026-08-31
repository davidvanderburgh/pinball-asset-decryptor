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
    try:
        r = tk.Tk()
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
    assert io.writes and addr(1, 11) in io.writes[-1][0]      # closed now…
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
