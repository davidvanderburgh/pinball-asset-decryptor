"""PAD-1315 (DoomWalrus666): "In co-op mode, Player 1's user icon moves to the scoreboard position of the active player
next to their username ... Please make each player's user icon remain at their scoreboard position at all times".

PAD-1108 puts the teammate up's Insider login in the game's player 1's place; PAD-1267 made the boxes' NAMES ask for the
place holding their own player's login. The icons are drawn apart from the names, by the score frame's Insider overlay
(NetScoreFrameOverlay, every Spike 2 build): draw(this, logins, player 1..4, r3, [sp]; rectangle in s0-s3), which reads
the player's login state and login from the swapped entry. portcoop.score_icon_sites finds the overlay's one call of
that drawer (`site coop_icon_draw`) and the runtime answers it with the place holding the box's own player's login.

And a gap PAD-1267 left: re-pointing the name's PLAYER made a guest's box (no login: "PLAYER %d" of the number given)
read the number of the place its entry was moved to. portcoop.name_user_site finds the name's own user lookup
(`site coop_panel_name_user`); the runtime gives the name its own number and re-points that lookup instead.
"""
import glob
import os
import pathlib

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import portcoop
from tests import test_spike2_mode_roster as R
from tests.test_pad1267_coop_panel_names import BASE, NOP, POP, PUSH, _bl, _elf

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = RUNTIME.parent / "ports"
ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1315/elfs;C:/tmp/PAD-1267/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))

VA = lambda i: BASE + 4 * i                                              # noqa: E731
MOV_R4_R2, MOV_R1_R2, MOV_R1_R4, MOV_R1_R3, MOV_R7_R0 = 0xE1A04002, 0xE1A01002, 0xE1A01004, 0xE1A01003, 0xE1A07000
VSTR_S3, CMP_R0_0, CMP_R6_R4 = 0xED8D1A05, 0xE3500000, 0xE1560004
LOGIN_READ = [0xE92D4038, 0xE2413001, 0xE3530003, 0x8A000008, 0xE0811101, 0xE0800101, 0xE2804004, 0xE8BD8038]


def _icons(tmp_path, calls=1, r1=MOV_R1_R4):
    """the login read; a state call reaching it; the drawer (its player r2 to both as r1, a VFP store between); a
    decoy drawer giving r3; then the overlay's loop calling the drawer `calls` times. Returns (path, the call's va)."""
    w = list(LOGIN_READ)                                                 # 0 login(table, player, out)
    state = len(w)
    w += [PUSH, _bl(VA(state + 1), VA(0)), POP]                           # the login state: reads it
    drawer = len(w)
    w += [0xE92D4FF0, MOV_R4_R2, MOV_R1_R2, VSTR_S3, NOP]
    w += [_bl(VA(len(w)), VA(state)), MOV_R7_R0, r1]
    w += [_bl(VA(len(w)), VA(0)), CMP_R0_0, 0xE8BD8FF0]
    decoy = len(w)                                                       # gives r3, not its player
    w += [0xE92D4FF0, MOV_R1_R3, _bl(VA(decoy + 2), VA(state)), MOV_R1_R3, _bl(VA(decoy + 4), VA(0)), 0xE8BD8FF0]
    w += [0xE92D40F0]                                                    # the overlay's loop over the boxes
    at = []
    for _ in range(calls):
        at.append(len(w))
        w += [_bl(VA(len(w)), VA(drawer)), CMP_R6_R4]
    w += [_bl(VA(len(w)), VA(decoy)), CMP_R6_R4, 0xE8BD80F0] + [NOP] * 8
    p = tmp_path / "icons.elf"
    p.write_bytes(_elf(w))
    return str(p), VA(at[0])


def test_the_finder_takes_the_overlays_drawer_call(tmp_path):
    path, call = _icons(tmp_path)
    e = portcoop.Elf(path)
    assert portcoop.login_reader(e) == BASE
    assert portcoop.score_icon_sites(e) == [("coop_icon_draw", call)]


def test_a_drawer_not_given_its_player_or_called_twice_is_left(tmp_path):
    path, _call = _icons(tmp_path, r1=MOV_R1_R3)                         # the login read is not given the player
    assert portcoop.score_icon_sites(portcoop.Elf(path)) == []
    path, _call = _icons(tmp_path, calls=2)
    assert portcoop.score_icon_sites(portcoop.Elf(path)) == []


def test_the_names_own_user_lookup(tmp_path):
    w = [PUSH, NOP, NOP, POP]                                            # 0 look
    w += [PUSH, _bl(VA(5), VA(0)), NOP, POP]                             # 4 user_for_player
    helper = len(w)                                                      # 8 the name's helper
    w += [0xE92D4FF0, 0xE1A05001, NOP, 0xE1A00005, _bl(VA(helper + 4), VA(4)), 0xE250A000, 0xE8BD8FF0]
    name = len(w)
    w += [PUSH, _bl(VA(name + 1), VA(helper)), POP]
    call = len(w)
    w += [_bl(VA(call), VA(name)), NOP] + [NOP] * 8
    p = tmp_path / "name.elf"
    p.write_bytes(_elf(w))
    e = portcoop.Elf(str(p))
    assert portcoop.name_user_site(e, VA(call), VA(0)) == VA(helper + 4)
    assert portcoop.name_user_site(e, VA(call), None) is None


def test_the_lines_carry_them():
    src = pathlib.Path(portcoop.__file__).read_text(encoding="utf-8")
    assert "for name, at in score_icon_sites(e):" in src and '"coop_panel_name_user"' in src
    from pinball_decryptor.plugins.stern import portgen
    assert "panel_name(?:_\\d|_user)?|icon_draw|" in pathlib.Path(portgen.__file__).read_text(encoding="utf-8")


ICON_MAIN = r"""
#include <stdio.h>
static unsigned cu_g, cu_p;
static void say(const char *f, ...) {}
static unsigned coop_user_word(unsigned p) { return 0xa0 + p; }
static float fx, fy, fw, fh;
static unsigned got[5];
static unsigned game_draw(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, float x, float y, float w,
                          float h)
{ got[0] = r0; got[1] = r1; got[2] = r2; got[3] = r3; got[4] = s0; fx = x; fy = y; fw = w; fh = h; return r2; }
static unsigned user_got;
static unsigned game_user(unsigned r0, unsigned r1, unsigned r2, unsigned r3) { user_got = r0; return 0x500 + r0; }
static unsigned coop_name_user_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3);
static unsigned game_name(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, unsigned s1)
{ unsigned u = coop_name_user_wrap(r1, 0, 0, 0); return (u << 4) | r1; }   /* the user found, the number given */
@FNS@
int main(void)
{
    unsigned b;
    coop_icon_game = game_draw;
    for (b = 1; b <= 4; b++) printf("as made box %u -> %u\n", b, coop_icon_wrap(7, 8, b, 9, 10, 1.5f, 2.5f, 3.5f, 4.5f));
    cu_g = 1; cu_p = 2;                                   /* teammate 2 up: their login in place 1 */
    for (b = 1; b <= 4; b++) printf("teammate 2 up box %u -> %u\n", b, coop_icon_wrap(7, 8, b, 9, 10, 1.5f, 2.5f, 3.5f, 4.5f));
    printf("args %x %x %x %x %.1f %.1f %.1f %.1f\n", got[0], got[1], got[3], got[4], fx, fy, fw, fh);
    coop_name_game = game_name;
    coop_name_user_game = game_user;
    for (b = 1; b <= 3; b++) printf("name box %u -> %x\n", b, coop_name_wrap(0, b, 0, 0, 0, 0));
    printf("outside a box's name: %x\n", coop_name_user_wrap(1, 0, 0, 0));
    return 0;
}
"""


def test_each_box_draws_its_own_players_icon_and_number(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = ("static unsigned (*coop_icon_game)(unsigned, unsigned, unsigned, unsigned, unsigned, float, float, float, "
           "float);\n"
           "static unsigned (*coop_name_game)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);\n"
           "static unsigned (*coop_name_user_game)(unsigned, unsigned, unsigned, unsigned);\n"
           "static volatile unsigned cn_box, cn_place;\n"
           + "\n".join(R._lift(src, sig) for sig in (
               "static unsigned coop_name_player(unsigned p, unsigned g, unsigned q)",
               "static unsigned coop_icon_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, "
               "float x, float y,\n                               float w, float h)",
               "static unsigned coop_name_user_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)",
               "static unsigned coop_name_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, "
               "unsigned s1)")))
    out = R._host_run(tmp_path, ICON_MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["as made box 1 -> 1", "as made box 2 -> 2", "as made box 3 -> 3", "as made box 4 -> 4",
                   # box 1 draws place 2 (player 1's login while teammate 2 is up), box 2 place 1 (teammate 2's)
                   "teammate 2 up box 1 -> 2", "teammate 2 up box 2 -> 1", "teammate 2 up box 3 -> 3",
                   "teammate 2 up box 4 -> 4",
                   "args 7 8 9 a 1.5 2.5 3.5 4.5",           # everything else, the rectangle too, goes on as given
                   # a box's name: its own number given, the login looked up in its place
                   "name box 1 -> 5021", "name box 2 -> 5012", "name box 3 -> 5033",
                   "outside a box's name: 501"]


def test_the_runtime_arms_them_with_the_names():
    src = RUNTIME.read_text(encoding="utf-8")
    i = src.index("static void coop_name_arm(void)")
    body = src[i:src.index("\n}\n", i)]
    assert "coop_icon_arm();" in body and 'site("coop_panel_name_user")' in body
    assert 'hook_call(fn("coop_icon_draw"), (void *)coop_icon_wrap)' in src


#: the overlay's drawer calls, read off the shipped programs
DRAW_SITES = {"godzilla_pro-1.16.0.elf": 0x484440, "godzilla_pro-1_16_0_spike2.elf": 0x484440,
              "godzilla_le-1.16.0.elf": 0x3e1a10, "godzilla_pro-1.15.0.elf": 0x3c2efc}


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_the_shipped_programs():
    seen = 0
    for p in ELFS:
        name = os.path.basename(p)
        e = portcoop.Elf(p)
        got = portcoop.score_icon_sites(e)
        assert len(got) == 1, name
        if name in DRAW_SITES:
            assert got[0][1] == DRAW_SITES[name], name
            seen += 1
        if name == "godzilla_pro-1.16.0.elf":
            assert portcoop.name_user_site(e, 0x1aa2e4, CP.users_lookup(e)) == 0x3bc944
    assert seen


def test_every_coop_port_carries_them():
    for p in sorted(PORTS.glob("*.port")):
        text = p.read_text(encoding="utf-8")
        coop = "coop_player_change" in text
        lines = text.splitlines()
        assert len([l for l in lines if l.startswith("site  coop_icon_draw")]) == (1 if coop else 0), p.stem
        assert len([l for l in lines if l.startswith("site  coop_panel_name_user")]) == \
            (1 if any(l.startswith("site  coop_panel_name ") for l in lines) else 0), p.stem
        assert not any(l.startswith("site  coop_panel_icon") for l in lines), p.stem
    gz = [l for l in (PORTS / "godzilla_pro-1.16.port").read_text(encoding="utf-8").splitlines()
          if l.startswith(("site  coop_icon", "site  coop_panel_name_user"))]
    assert gz == ["site  coop_panel_name_user   0x003bc944 0xebfffbb6 0xe250a000",
                  "site  coop_icon_draw         0x00484440 0xebfffdf3 0xe1560004"]
