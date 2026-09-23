r"""Pop-out DMD + switch windows for the Spike 1 emulator.

The pure pieces (the UNC path, the run-dir reads/writes), from
``webui/emulate_spike1_core.py``; the web windows themselves are driven in
tests/test_webui_emulate_spike1.py.  The windows read the emulator's run-dir
over the ``\\wsl.localhost\<distro>\...`` UNC path; the I/O is tested against local temp
files by pointing ``_unc`` at them.
"""

from pinball_decryptor.webui import emulate_spike1_core as W
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


# --------------------------------------------------------- play controls --


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


# ------------------------------------------ the 2012 home models' names --
# Their switch map names the flippers "LEFT FLIPPER" (with "LEFT FLIPPER
# EOS" beside them) and the start button "START"; the play keys must resolve
# on those as well as on the DMD generation's "L. FLIPPER BUTTON" / "START
# BUTTON" (PAD-101).


# ---------------------------------------------- the alphanumeric display --


# ------------------------------------------- the display window's KIND -----
# The rig only says which display the machine has (s1display) once the game is
# extracted, which is AFTER the windows first open.  A DMD window fed this
# era's 256-byte frames reads eight of them as one 2048-byte frame and draws
# stripes, so the viewers must SWAP it, not leave it up (PAD-101).


# --------------------------------- service controls the machine really has --
# The 2012 home models have no coin-door switch and no service buttons (their
# 46 node-8 switches are all playfield/cabinet), and no operator menu: TestMode
# is entered by holding BOTH FLIPPERS for 3 s.  Offering the DMD generation's
# BACK/-/+/SELECT cluster and coin-door bar there sent David hunting for a
# door-and-SELECT menu that cannot exist (PAD-101).


