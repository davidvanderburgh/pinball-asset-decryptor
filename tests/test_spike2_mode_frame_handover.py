"""PAD-301: a mode's full-screen clip drawn at the game's frame hand-over.

- frame_sites.py follows the main loop from the tick to frame end and the kick: proven on a built program
  (runs everywhere), and against the Godzilla programs the ports were made from when they are present.
- The runtime: with the hand-over hooked, the tick neither draws nor advances the player (both are what
  kept the game from building its frames); a port needs both lines.
- PAD-353: the game's foreground words are never hidden (PAD-301's fg_words_off is gone).
"""
import os
import pathlib
import re
import struct
import sys

import pytest

from tests.test_spike2_mode_roster import _host_run, _lift

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"
sys.path.insert(0, str(SDK))
import frame_sites  # noqa: E402

GAMES = {
    "godzilla_le-1.16.port": [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""),
                              r"C:\tmp\kaiju_premium\stock\game", "/mnt/c/tmp/kaiju_premium/stock/game"],
    "godzilla_pro-1.15.port": [os.environ.get("PAD_GODZILLA_PRO_115_GAME", ""),
                               r"C:\tmp\radium_scene_re\godzilla_pro_1_15\game",
                               "/mnt/c/tmp/radium_scene_re/godzilla_pro_1_15/game"],
    "godzilla_pro-1.16.port": [os.environ.get("PAD_GODZILLA_PRO_116_GAME", "")],
}

BASE = 0x10000
CMP_R0_0, PUSH, NOP, MOV_SL_R0, MOV_R0_SL = 0xE3500000, 0xE92D40F8, 0xE1A00000, 0xE1A0A000, 0xE1A0000A


def _branch(at, to, link):
    return (0xEB000000 if link else 0xEA000000) | (((to - at - 8) >> 2) & 0xFFFFFF)


def _program(tail_branch=True):
    """A one-segment ELF: kick at +0x100, tick at +0x200, frame end at +0x300, the loop at +0x400."""
    words = {}
    kick, tick, begin, end, loop = BASE + 0x100, BASE + 0x200, BASE + 0x280, BASE + 0x300, BASE + 0x400
    words[kick] = [PUSH, NOP]
    words[tick] = [PUSH, NOP]
    words[begin] = [PUSH, NOP]
    words[end] = [CMP_R0_0, PUSH, NOP, NOP] + ([_branch(end + 16, kick, False)] if tail_branch else [NOP])
    words[loop] = [_branch(loop, tick, True), _branch(loop + 4, begin, True), MOV_SL_R0, NOP, NOP,
                   MOV_R0_SL, _branch(loop + 24, end, True), NOP]
    code = bytearray(0x600)
    for at, ws in words.items():
        for i, w in enumerate(ws):
            struct.pack_into("<I", code, at - BASE + 4 * i, w)
    hdr = bytearray(0x54)
    hdr[:5] = b"\x7fELF\x01"                                 # 32-bit
    struct.pack_into("<I", hdr, 0x1c, 0x34)                  # phoff
    struct.pack_into("<HH", hdr, 0x2a, 32, 1)                # phentsize, phnum
    struct.pack_into("<8I", hdr, 0x34, 1, 0, BASE, BASE, len(code), len(code), 5, 0x1000)
    code[:len(hdr)] = hdr
    return bytes(code), tick, end, kick


def test_frame_sites_follows_the_loop_from_the_tick(tmp_path):
    data, tick, end, kick = _program()
    elf = tmp_path / "game"
    elf.write_bytes(data)
    got, why = frame_sites.find(str(elf), tick)
    assert why is None
    assert [(n, a) for n, a, _w0, _w1 in got] == [("frame_end", end), ("frame_kick", kick)]
    assert got[0][2:] == (CMP_R0_0, PUSH)


def test_frame_sites_says_which_step_did_not_match(tmp_path):
    data, tick, _end, _kick = _program(tail_branch=False)
    elf = tmp_path / "game"
    elf.write_bytes(data)
    got, why = frame_sites.find(str(elf), tick)
    assert got is None and "kick" in why


def _port(name):
    lines = {}
    for line in (PORTS / name).read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 3 and parts[0] in ("site", "data", "value"):
            lines[(parts[0], parts[1])] = [int(p, 0) for p in parts[2:]]
    return lines


@pytest.mark.parametrize("name", sorted(GAMES))
def test_the_godzilla_ports_name_the_hand_over(name):
    port = _port(name)
    assert ("site", "frame_end") in port and ("site", "frame_kick") in port
    assert port[("site", "frame_end")][1:] == [CMP_R0_0, PUSH]


@pytest.mark.parametrize("name", sorted(GAMES))
def test_the_hand_over_lines_are_what_frame_sites_finds_in_the_game(name):
    game = next((p for p in GAMES[name] if p and os.path.isfile(p)), None)
    if not game:
        pytest.skip("the %s program is not on this machine" % name)
    port = _port(name)
    got, why = frame_sites.find(game, port[("site", "tick")][0])
    assert why is None, why
    for site, at, w0, w1 in got:
        assert port[("site", site)] == [at, w0, w1]


def test_the_tick_neither_draws_nor_advances_once_the_hand_over_draws():
    body = _lift(RUNTIME.read_text(encoding="utf-8"), "static void clip_tick(void)")
    guarded = re.search(r"if \(!frame_draws\) \{(.*?)\n        \}", body, re.S)
    assert guarded, "the tick's draw is not guarded by frame_draws"
    assert "player_advance" in guarded.group(1) and "display_draw" in guarded.group(1)
    assert body.count("player_advance") == 1 and body.count("display_draw") == 1


def test_the_hand_over_needs_both_lines_and_advances_before_it_draws():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _lift(src, "static void frame_arm(void)")
    assert '!site("frame_end") || !site("frame_kick")' in arm
    kick = _lift(src, "static void on_frame_kick(unsigned *r)")
    assert "if (!frame_pending) return;" in kick                 # the kick's other caller is not a game frame
    assert "!frame_built" in kick
    assert kick.index("player_advance") < kick.index("display_draw")


def test_the_games_foreground_words_are_never_hidden():
    """PAD-353: PAD-301 emptied a weaker layered foreground's scene_show under a mode's hold; the game's
    screens now play as the game made them, and a mode keeps its own words off them instead."""
    src = RUNTIME.read_text(encoding="utf-8")
    assert "fg_words_off" not in src and "hold_hides_fg_words" not in src


def test_scene_show_settles_our_player_before_the_backdrop():
    """While our full-screen clip plays, nothing of the game's puts the player in the frame first (the
    hand-over draws it last); only then the backdrop's own business."""
    body = _lift(RUNTIME.read_text(encoding="utf-8"), "static void on_scene_show(unsigned *r)")
    ours = body.index('fn("video_player"))()) {')
    assert body.index("frame_draws && clip.on") < ours < body.index("if (!e ||")
    assert "r[0] = 0;" in body[ours:body.index("if (!e ||")]


def test_a_godzilla_run_swaps_at_the_machines_cadence_unless_told_otherwise():
    """The machine built ~29 frames a second; at the rig's old 60 Hz swap the clip bug could not show."""
    watch = (SDK.parents[1] / "watch.sh").read_text(encoding="utf-8")
    block = re.search(r'if \[ -z "\$\{PAD_SWAP_VBLANKS:-\}" \]; then\n(.*?)\nfi\n', watch, re.S)
    assert block and 'godzilla_*) export PAD_SWAP_VBLANKS=2' in block.group(1)
    assert watch.index("export PAD_GAME=") < block.start() < watch.index('bash "$RIG/run_game.sh"')
    egl = (SDK.parents[1] / "eglshim.c").read_text(encoding="utf-8")
    assert 'getenv("PAD_SWAP_VBLANKS")' in egl and 'getenv("PAD_REFRESH_HZ")' in egl
    assert "const unsigned long long frame_us = swap_frame_us();" in egl
