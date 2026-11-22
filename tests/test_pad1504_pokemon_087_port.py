"""PAD-1504: Pokemon LE 0.87's Spike 3 port, carried from the emulator-proven 0.82 port.

0.87 is the same title one build on: every line of the 0.82 port is in it at 0.87's own addresses, and only what 0.87
changed is different - the start menu (rebuilt for TOURNAMENT: its list at sp+0xd0 with room for 14, the cursor in
w20, only the LAST index kept, Competition at game-mode index 7), the message ids after it, the challenge flag (18)
and the attract table (63 pages). The rig proofs (docs/plans/spike3_modes.md, "Pokemon LE 0.87") are recorded in
mode_project's tables; these tests keep the port and those tables in step. The checks against the program itself run
when PAD_S3_PROGRAMS names a folder holding pokemon_le-0.87.game (the card's /games/pokemon_le/game).
"""
import os
import pathlib
import struct

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import prolonged_comp as PC

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORTS = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3"
RUNTIME = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
OLD, NEW = "pokemon_le-0.82", "pokemon_le-0.87"

#: the values 0.87 changed, and what they are now
CHANGED = {
    "comp_menu_frame_list_at": 208, "comp_menu_frame_count_at": 140, "comp_menu_frame_cap": 14,
    "comp_menu_frame_cursor_reg": 20, "comp_menu_index": 7, "comp_menu_index_msg": 1921, "comp_menu_end_msg": 1916,
    "challenge_menu_frame_list_at": 208, "challenge_menu_frame_count_at": 140, "challenge_menu_frame_cap": 14,
    "challenge_menu_frame_cursor_reg": 20, "challenge_menu_frame_caption_msg": 1915,
    "challenge_menu_frame_name_msg": 1916, "challenge_menu_caption": 1922, "challenge_on_flag": 18,
    "attract_count": 63,
}
#: 0.82 kept the count and a copy of the last index; 0.87 keeps the last index alone
GONE = {"comp_menu_frame_last_at", "challenge_menu_frame_last_at"}
ADDED = {"comp_menu_frame_count_last": 1, "challenge_menu_frame_count_last": 1}


def _port(name):
    return MP.read_port(str(PORTS / (name + ".port")))


def test_every_line_of_the_proven_port_is_carried():
    old, new = _port(OLD), _port(NEW)
    for kind in ("site", "data", "scene", "switch"):
        assert set(old[kind]) == set(new[kind]), kind
    assert set(old["value"]) - GONE == set(new["value"]) - set(ADDED)
    for k, v in old["value"].items():
        if k not in GONE:
            assert new["value"][k] == CHANGED.get(k, v), k
    for k, v in ADDED.items():
        assert new["value"][k] == v
    assert old["switch"] == new["switch"]          # the device table's ids came out the same
    assert old["scene"] == new["scene"]            # the clip bank is the framework's 60ed7e50 on both


def test_the_head_names_the_program():
    head = (PORTS / (NEW + ".port")).read_text(encoding="utf-8")
    assert "4ea258112e5451fee0bba91125751208d83880cb" in head
    assert "\ngame           pokemon_le\nversion        0.87\n" in head


def test_the_app_offers_on_0_87_what_it_offers_on_0_82():
    a = MP.profile_from_port(str(PORTS / (OLD + ".port")))
    b = MP.profile_from_port(str(PORTS / (NEW + ".port")))
    assert sorted(dict(a.cannot)) == sorted(dict(b.cannot))
    for part in ("ball_save", "multiball", "challenge", "clip"):
        assert b.can(part), dict(b.cannot).get(part)
    assert PC.port_ready(_port(NEW))
    key = NEW + "/spike3"
    for table in (MP.MULTIBALL_PROVEN, MP.BALL_SAVE_PROVEN, MP.SWITCH_SHOTS_PROVEN):
        assert key in table
    assert "PENDING" not in MP.CHALLENGE_MENU_FRAME_PROVEN[key]
    assert MP.TITLE_SCENES[key] == dict(bank="32eb5f813905cf4b00a0304c7195bbb4", clip_proven=True)


def test_the_challenge_menu_reads_a_last_index_count():
    src = RUNTIME.read_text(encoding="utf-8")
    body = src[src.index("static void challenge_menu_frame(pm_reg *r)"):]
    body = body[:body.index("\n}\n")]
    assert '"challenge_menu_frame_count_last"' in body
    assert "cnt = *count + clast;" in body and "*count = cnt - clast;" in body
    assert "*count >" not in body and "*count >=" not in body     # every other read is the entries


def _program():
    path = os.path.join(PROGS, NEW + ".game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % NEW)
    from pinball_decryptor.plugins.stern import spike3_requests as S3R
    return S3R.Program(open(path, "rb").read())


def test_the_sites_are_the_programs_own_words():
    prog = _program()
    port = _port(NEW)
    for name, rec in port["site"].items():
        va, w0, w1 = rec[:3]
        if name == "dynamic_cast":                 # a PLT stub, outside .text's words
            continue
        assert struct.unpack_from("<2I", prog.raw, prog.off(va)) == (w0, w1), name


def test_the_start_menu_is_the_one_measured():
    prog = _program()
    va = _port(NEW)["site"]["comp_menu_frame"][0]

    def w(at, n=1):
        return struct.unpack_from("<%dI" % n, prog.raw, prog.off(at))

    assert w(va) == (0xB874DAFA,)                  # ldr w26, [x23, w20, sxtw #2]: the index under cursor w20
    assert 0xB9008FE1 in w(va - 0x70, 8)           # str w1, [sp, #0x8c]: the count - 1, once, before the loop
    assert w(va - 0x14) == (0xB9408FE1,)           # ldr w1, [sp, #0x8c]: the right press wraps at the last index
    assert PC.card_lines(prog.raw) == (17, 1920, 1915)
