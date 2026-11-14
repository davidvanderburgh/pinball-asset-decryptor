"""PAD-1267 (DoomWalrus666): "Co-op mode: Active player name always appeared on Player 1 scoreboard, while the active
highlighted score was the correct score position. Teams mode, player 3 and 4 names don't appear on scoreboard after
ball 1".

Co-op: PAD-1108 puts the teammate up's Insider login in the game's player 1's place (so the bonus names them), and the
score panel's box 1 read that place too. portcoop.panel_name_sites names the panel's calls that name a BOX's player
(`site coop_panel_name[_n]`) and the runtime answers each through the swap (coop_name_player), so every box names its
own player; the call naming the player up is left as it is.

Teams: the game counts two players and clears the logins past its count as player 3's first turn begins (emulator,
Godzilla LE 1.16); the runtime keeps a copy before each of the game's player changes, puts back what the game cleared,
and gives the game its own bytes back at the team game's end.
"""
import glob
import os
import pathlib
import struct

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import portcoop
from tests import test_spike2_mode_roster as R

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = RUNTIME.parent / "ports"
BASE = 0x8000
ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1267/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


def _elf(words):
    code = struct.pack("<%dI" % len(words), *words)
    hdr = bytearray(0x54)
    hdr[0:4] = b"\x7fELF"
    hdr[4], hdr[5] = 1, 1
    struct.pack_into("<I", hdr, 0x1C, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, 0x54, BASE, BASE, len(code), len(code), 5, 4)
    return bytes(hdr) + code


def _bl(at, to):
    return 0xEB000000 | (((to - at - 8) >> 2) & 0xFFFFFF)


PUSH, POP, NOP = 0xE92D4010, 0xE8BD8010, 0xE1A00000


def _panel(tmp_path, r1=0xE1A01009):
    """look, user_for_player (calls look), name (calls it), a function reaching nothing, the getter; then a panel
    function: a box's name call (r1 = sb), the player-up's (r1 = the getter's answer), the same shape into the
    function that reaches no lookup. Returns (path, look, getter, lit, the box call's va)."""
    w = [PUSH, NOP, NOP, POP]                                         # 0 look
    va = lambda i: BASE + 4 * i
    w += [PUSH, _bl(va(5), va(0)), NOP, POP]                          # 4 user_for_player
    w += [PUSH, _bl(va(9), va(4)), NOP, POP]                          # 8 name
    w += [PUSH, NOP, NOP, POP]                                        # 12 reaches nothing
    w += [PUSH, NOP, NOP, POP]                                        # 16 the getter
    w += [0xE92D4FF0]                                                 # 20 the panel function
    shape = lambda target, at: [0xE3A02000, r1, 0xE58D2000, 0xE28D001C, 0xE58D2004, 0xE1A03002, _bl(va(at), target)]
    box = len(w) + 6
    w += shape(va(8), box) + [0xE28D101C]                             # the box's name: found
    up = len(w)
    w += [_bl(va(up), va(16))]
    w += [0xE3A02000, 0xE1A01000, 0xE58D2000, 0xE28D0028, 0xE58D2004, 0xE1A03002, _bl(va(len(w) + 6), va(8)),
          0xE1A00005]                                                 # the player up's: left alone
    other = len(w) + 6
    w += shape(va(12), other) + [0xE28D101C]                          # no lookup behind it: left alone
    w += [0xE8BD8FF0] + [NOP] * 8
    p = tmp_path / "panel.elf"
    p.write_bytes(_elf(w))
    return str(p), va(0), va(16), va(20), va(box)


def test_the_finder_names_the_box_call_only(tmp_path):
    path, look, getter, lit, box = _panel(tmp_path)
    e = portcoop.Elf(path)
    assert portcoop.panel_name_sites(e, getter, lit, look) == [("coop_panel_name", box)]


def test_no_lookup_no_panel_no_sites(tmp_path):
    path, look, getter, lit, _box = _panel(tmp_path)
    e = portcoop.Elf(path)
    assert portcoop.panel_name_sites(e, getter, lit, None) == []
    assert portcoop.panel_name_sites(e, getter, None, look) == []


def test_a_box_number_from_r0_is_the_player_up_and_left_alone(tmp_path):
    path, look, getter, lit, _box = _panel(tmp_path, r1=0xE1A01000)   # mov r1, r0
    assert portcoop.panel_name_sites(portcoop.Elf(path), getter, lit, look) == []


NAME_MAIN = r"""
#include <stdio.h>
static unsigned cu_g, cu_p;
static void say(const char *f, ...) {}
static unsigned coop_user_word(unsigned p) { return 0xa0 + p; }
static unsigned got[6];
static unsigned game_name(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, unsigned s1)
{ got[0] = r0; got[1] = r1; got[2] = r2; got[3] = r3; got[4] = s0; got[5] = s1; return r0; }
@FNS@
int main(void)
{
    unsigned b;
    coop_name_game = game_name;
    for (b = 1; b <= 4; b++) printf("as made %u -> %u\n", b, coop_name_player(b, 0, 0));
    for (b = 1; b <= 4; b++) printf("teammate 3 up %u -> %u\n", b, coop_name_player(b, 1, 3));
    cu_g = 1; cu_p = 2;
    printf("wrap %u:", coop_name_wrap(0x111, 1, 6, 7, 0x55, 0x66));
    for (b = 0; b < 6; b++) printf(" %x", got[b]);
    printf("\n");
    return 0;
}
"""


def test_each_box_names_its_own_player(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = ("static unsigned (*coop_name_game)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);\n"
           + "\n".join(R._lift(src, sig) for sig in (
               "static unsigned coop_name_player(unsigned p, unsigned g, unsigned q)",
               "static unsigned coop_name_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, "
               "unsigned s1)")))
    out = R._host_run(tmp_path, NAME_MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["as made 1 -> 1", "as made 2 -> 2", "as made 3 -> 3", "as made 4 -> 4",
                   "teammate 3 up 1 -> 3", "teammate 3 up 2 -> 2", "teammate 3 up 3 -> 1", "teammate 3 up 4 -> 4",
                   # box 1 asks for place 2 (player 1's login while teammate 2 is up); the stack arguments go on
                   "wrap 273: 111 2 6 7 55 66"]


TEAM_MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#define COOP_USER_ENTRY 20u
static struct { unsigned teams, n; } coop;
static unsigned teammates;
static unsigned coop_teammates(void) { return teammates; }
static volatile unsigned char *coop_players_byte;
static unsigned cu_mgr, cu_off[2], cu_g, cu_p;
static void say(const char *f, ...) { printf("say %s\n", f); }
static unsigned char tu_made[2][4][COOP_USER_ENTRY];
static unsigned char tu_game[2][4][COOP_USER_ENTRY];
static unsigned tu_have, tu_put;
@FNS@
static unsigned *word(unsigned a) { return (unsigned *)(unsigned long)a; }
static void show(const char *what)
{
    unsigned k, p;
    printf("%s:", what);
    for (k = 0; k < 2; k++)
        for (p = 1; p <= 4; p++) printf(" %x", *word(coop_user_entry(*word(cu_mgr + cu_off[k]), p)));
    printf("\n");
}
int main(void)
{
    unsigned k, p;
    static unsigned char count = 2;
    if (mmap((void *)0x30000000ul, 0x10000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0)
        != (void *)0x30000000ul) { puts("NO MMAP"); return 1; }
    cu_mgr = 0x30000000u; cu_off[0] = 0x160; cu_off[1] = 0x164;
    *word(cu_mgr + 0x160) = 0x30001000u; *word(cu_mgr + 0x164) = 0x30002000u;
    for (k = 0; k < 2; k++)
        for (p = 1; p <= 4; p++) *word(coop_user_entry(0x30001000u + 0x1000u * k, p)) = 0xa10 + 16 * k + p;
    coop_players_byte = &count;
    coop_team_users_keep();                                  /* not a team game: nothing kept */
    printf("co-op kept %x\n", tu_have);
    coop.teams = 1; coop.n = 4; teammates = 4;
    coop_team_users_keep();
    printf("kept %x\n", tu_have);
    memset(word(coop_user_entry(0x30001000u, 3)), 0, 2 * COOP_USER_ENTRY);   /* the game clears 3 and 4, table A */
    show("cleared");
    coop_team_users_back("in its player change");
    show("back");
    coop_team_users_back("after its player change");      /* nothing to put back: no line */
    memset(word(coop_user_entry(0x30001000u, 4)), 0, COOP_USER_ENTRY);
    coop_team_users_back("after its player change");
    show("back again");
    coop_team_users_end();
    show("over");
    printf("kept %x put %x\n", tu_have, tu_put);
    /* player 3 up on the game's player 1: places 1 and 3 swapped, then the game clears places 3 and 4 */
    for (p = 1; p <= 4; p++) *word(coop_user_entry(0x30001000u, p)) = 0xa10 + p;
    coop_team_users_keep();
    for (k = 0; k < 2; k++) {
        unsigned t = 0x30001000u + 0x1000u * k, a = *word(coop_user_entry(t, 1));
        *word(coop_user_entry(t, 1)) = *word(coop_user_entry(t, 3));
        *word(coop_user_entry(t, 3)) = a;
    }
    cu_g = 1; cu_p = 3;
    memset(word(coop_user_entry(0x30001000u, 3)), 0, 2 * COOP_USER_ENTRY);
    coop_team_users_back("after its player change");
    show("swapped back");
    return 0;
}
"""


def test_a_team_game_keeps_players_3_and_4s_logins(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static unsigned coop_name_player(unsigned p, unsigned g, unsigned q)",
        "static unsigned coop_user_entry(unsigned t, unsigned p)",
        "static int coop_user_table_ok(unsigned t)",
        "static unsigned coop_user_word(unsigned p)",
        "static int coop_entry_empty(const volatile unsigned char *x)",
        "static unsigned coop_team_users_from(void)",
        "static void coop_team_users_keep(void)",
        "static void coop_team_users_back(const char *when)",
        "static void coop_team_users_end(void)"))
    out = R._host_run(tmp_path, TEAM_MAIN.replace("@FNS@", fns)).splitlines()
    put = [l for l in out if l.startswith("say co-op insider: team game: the game cleared")]
    out = [l for l in out if not l.startswith("say ")]
    assert out == ["co-op kept 0", "kept ff",                      # every player's login, both tables
                   "cleared: a11 a12 0 0 a21 a22 a23 a24",
                   "back: a11 a12 a13 a14 a21 a22 a23 a24",
                   "back again: a11 a12 a13 a14 a21 a22 a23 a24",
                   "over: a11 a12 0 0 a21 a22 a23 a24",            # the game's own bytes again: nothing left over
                   "kept 0 put 0",
                   # place 3 held player 1's login (the swap): player 1's goes back there, player 4's in place 4
                   "swapped back: a13 a12 a11 a14 a23 a22 a21 a24"]
    assert len(put) == 3


def _body(src, head):
    i = src.index(head)
    return src[i:src.index("\n}\n", i)]


def test_the_runtime_wires_both():
    src = RUNTIME.read_text(encoding="utf-8")
    tm = _body(src, "static unsigned coop_team_change(")
    assert tm.index("coop_team_users_keep();") < tm.index("ret = coop_change_game(") \
        < tm.index('coop_team_users_back("in its player change")')
    assert "else coop_team_users_end();" in tm
    tick = _body(src, "static void coop_tick(void)\n{")
    assert "if (tu_have && !(coop.teams && coop_teammates())) coop_team_users_end();" in tick
    assert 'else if (tu_have) coop_team_users_back("after its player change");' in tick
    assert "tu_have = tu_put = 0;" in _body(src, "static unsigned coop_team_add(")
    assert tm.index("coop.turn = coop_team_player_in(") < tm.index("coop_users_put(p_after, coop.turn);")
    assert "coop_name_arm();" in _body(src, "static void coop_users_arm(void)")
    assert '"coop_panel_name", "coop_panel_name_2", "coop_panel_name_3"' in src


#: the panel's box-name calls, read off the shipped programs
NAME_SITES = {
    "godzilla_le-1.16.0.elf": [0x1ade70, 0x1ae740], "godzilla_pro-1.15.0.elf": [0x1a9a14, 0x1aa2e4],
    "godzilla_pro-1.16.0.elf": [0x1a9a14, 0x1aa2e4], "uncanny_xmen_le-0.98.0.elf": [0x10c940],
    "uncanny_xmen_pro-0.98.0.elf": [0x1079c0], "avengers_infinity_le-1.10.0.elf": [],
    "avengers_infinity_pro-1.10.0.elf": [], "jurassic_park_the_pin-1.05.0.elf": [],
}


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_the_shipped_panels():
    for p in ELFS:
        name = os.path.basename(p)
        if name not in NAME_SITES:
            continue
        got = [int(l.split()[2], 16) for l in portcoop.lines(p)[0] if "coop_panel_name" in l]
        assert got == NAME_SITES[name], name


def test_the_latest_ports_carry_the_lines():
    have = {p.stem: [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("site  coop_panel_name")]
            for p in sorted(PORTS.glob("*.port"))}
    have = {k: v for k, v in have.items() if v}
    assert sorted(have) == ["godzilla_le-1.16", "godzilla_pro-1.16", "uncanny_xmen_le-0.98", "uncanny_xmen_pro-0.98"]
    assert have["godzilla_le-1.16"] == ["site  coop_panel_name        0x001ade70 0xeb0474be 0xe28d101c",
                                        "site  coop_panel_name_2      0x001ae740 0xeb04728a 0xe28d0030"]


def test_users_lookup_is_the_one_insider_users_reads():
    from tests import test_pad1108_coop_insider as U
    e = portcoop.Elf(U._elf(U._users_program()))
    assert CP.users_lookup(e) == BASE + 8 * 4
    assert CP.users_lookup(portcoop.Elf(U._elf(U._users_program(2)))) is None
