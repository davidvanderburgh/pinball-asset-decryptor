"""PAD-1108 (DoomWalrus666, 3-player co-op): "achievements earned by player 2 and 3 were shown as earned by Player 1.
Player 1 username displayed on End of Ball Bonus for all 3 players. High score attributed only to Player 1".

The game plays one player for the team, and its user manager answers "the login of player N" from two tables of the
players' entries (player p at table + 20p + 4). In a co-op game the runtime swaps the game's player's entry with the
teammate up's and puts them back before each of the game's own player changes (not in a team game: the game clears the
entries past its count of two, and would lose player 1's); it refuses the game's achievement award while Insider
Connected is held back. Both addresses are read off the card's program (coop_play.insider_users / achievement_award).

Desk: hand-made code for the finders, the runtime's words. With game programs at hand (PAD_GAME_ELVES=<folder of game
ELFs>, or C:/tmp/PAD-1108/elfs) every build is checked: one user manager each, one award each (Star Wars ELG has no
audit add the app finds, so no award line there).
"""
import glob
import os
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
BASE = 0x8000
ELVES = os.environ.get("PAD_GAME_ELVES") or "C:/tmp/PAD-1108/elfs"


def _elf(words):
    """A 32-bit little-endian ELF holding the words in one executable PT_LOAD at BASE."""
    code = struct.pack("<%dI" % len(words), *words)
    hdr = bytearray(0x54)
    hdr[0:4] = b"\x7fELF"
    hdr[4], hdr[5] = 1, 1
    struct.pack_into("<I", hdr, 0x1C, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, 0x54, BASE, BASE, len(code), len(code), 5, 4)
    return bytes(hdr) + code


def _b(at, to, link):
    return (0xEB000000 if link else 0xEA000000) | (((to - at - 8) >> 2) & 0xFFFFFF)


def _movw(rd, v):
    return 0xE3000000 | ((v & 0xF000) << 4) | (rd << 12) | (v & 0xFFF)


def _movt(rd, v):
    return 0xE3400000 | ((v & 0xF000) << 4) | (rd << 12) | (v & 0xFFF)


NOP = 0xE1A00000
MGR = 0x7BF878


def _users_program(lookups=1):
    """[1] a caller: movw/movt r0 manager; bl lookup.  [8] the lookup(s).  [32] the table lookup."""
    w = [NOP] * 64
    table = BASE + 32 * 4
    for n in range(lookups):
        k = 8 + 6 * n
        w[k:k + 4] = [0xE590C160, 0xE3530001, 0xE5900164, 0x11A0000C]
        w[k + 4] = _b(BASE + 4 * (k + 4), table, False)
    w[1], w[2] = _movw(0, MGR & 0xFFFF), _movt(0, MGR >> 16)
    w[3] = _b(BASE + 12, BASE + 8 * 4, True)
    w[32:44] = [0xE92D4038, 0xE2413001, 0xE3530003, 0x8A000014, 0xE3520000, 0xE1A05002, 0x0A00000E,
                0xE0811101, 0xE0800101, 0xE2804004, NOP, NOP]
    return w


def test_the_user_manager_and_its_two_tables():
    assert CP.insider_users(_elf(_users_program())) == (MGR, 0x160, 0x164)


def test_two_lookups_of_that_shape_name_none():
    assert CP.insider_users(_elf(_users_program(2))) is None


def test_a_lookup_into_another_table_shape_names_none():
    w = _users_program()
    w[33] = NOP                                               # no `sub r3, r1, #1`: not the 20-byte player table
    assert CP.insider_users(_elf(w)) is None


def test_the_award_is_the_one_function_counting_achievements_given(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_framework, stock_scan, stock_scan_c
    add = BASE + 60 * 4
    w = [NOP] * 64
    w[9] = 0xE12FFF1E                                         # bx lr: the function before
    w[10:12] = [0xE590C004, 0xE92D43F0]                       # ldr ip, [r0, #4]; push {r4-r9, lr}
    w[20:22] = [0xE3A00007, 0xE3A01001]                       # mov r0, #7; mov r1, #1
    w[22] = _b(BASE + 22 * 4, add, True)
    monkeypatch.setattr(mode_framework, "audit_add", lambda e: add)
    monkeypatch.setattr(stock_scan, "Program", lambda raw: raw)
    monkeypatch.setattr(stock_scan_c, "audit_ids", lambda prog: ([], {7: "AUD_CONNECTIVITY_ACHIEVEMENTS_GIVEN"}, None))
    assert CP.achievement_award(_elf(w)) == BASE + 10 * 4
    w[20] = 0xE3A00008                                        # another audit: no award
    assert CP.achievement_award(_elf(w)) is None


def test_lines_leave_out_what_is_not_found():
    assert CP.insider_lines(b"not a program") == []
    assert CP.insider_lines(_elf(_users_program())) == ["users 0x%08x 0x160 0x164" % MGR]


def _src():
    with open(RUNTIME, encoding="utf-8") as f:
        return f.read()


def _body(src, head):
    i = src.index(head)
    return src[i:src.index("\n}\n", i)]


def test_the_runtime_reads_both_lines():
    s = _body(_src(), "static void coop_line(const char *s)")
    assert 'str_starts(s, "users ")' in s and 'str_starts(s, "achievements ")' in s


def test_the_entries_go_back_before_every_game_player_change_and_follow_the_turn():
    src = _src()
    co = _body(src, "static unsigned coop_change_wrap(")
    assert co.index("coop_users_put(0, 0)") < co.index("ret = coop_change_game(")
    assert "coop_users_put(1, coop.turn)" in co[co.index("coop.turn = next;"):]
    tm = _body(src, "static unsigned coop_team_change(")
    assert tm.index("coop_users_put(0, 0)") < tm.index("ret = coop_change_game(")
    assert "coop_users_put(p_after" not in tm and "coop_users_put(1" not in tm    # a team game keeps its logins
    tick = _body(src, "static void coop_tick(void)\n{")
    assert re.search(r"if \(cu_g && !\(coop_teammates\(\) && pm_in_game\(\)\)\) coop_users_put\(0, 0\);", tick)
    assert "coop_users_arm();" in _body(src, "static void coop_arm(")


def test_an_entry_is_20_bytes_from_table_plus_4():
    src = _src()
    assert "#define COOP_USER_ENTRY 20u" in src
    assert "return t + COOP_USER_ENTRY * p + 4u;" in _body(src, "static unsigned coop_user_entry(")


def test_the_award_is_refused_only_while_the_gate_holds():
    src = _src()
    v = _body(src, "static int on_coop_award(unsigned *r)\n{")
    assert "insider_holding(insider_while" in v and "return 0;" in v and "return 1;" in v
    assert "hook_veto(cu_award, on_coop_award)" in _body(src, "static void coop_users_arm(void)")


def _elves():
    return sorted(glob.glob(os.path.join(ELVES, "*.elf")))


@pytest.mark.skipif(not _elves(), reason="no game programs here (PAD_GAME_ELVES)")
def test_every_build_has_one_user_manager_and_one_award():
    missing_award = []
    for p in _elves():
        with open(p, "rb") as f:
            raw = f.read()
        u = CP.insider_users(raw)
        assert u and u[1] in (0x150, 0x160) and u[2] == u[1] + 4, p
        if CP.achievement_award(raw) is None:
            missing_award.append(os.path.basename(p))
    assert all(n.startswith("star_wars_elg") for n in missing_award), missing_award


GZ = os.path.join(ELVES, "godzilla_le-1_16_0_spike2.elf")


@pytest.mark.skipif(not os.path.isfile(GZ), reason="no Godzilla LE 1.16 program here")
def test_godzilla_le_116():
    with open(GZ, "rb") as f:
        raw = f.read()
    assert CP.insider_lines(raw) == ["users 0x007bf878 0x160 0x164", "achievements 0x003ea8a0"]
    assert CP.cfg_text(raw).startswith("coop on\nbutton 59\nusers 0x007bf878 0x160 0x164\nachievements 0x003ea8a0\n"
                                       "award ")
