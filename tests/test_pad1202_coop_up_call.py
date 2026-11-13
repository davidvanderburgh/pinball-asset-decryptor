"""PAD-1202 (DoomWalrus666, Godzilla: "a call out that said 'player one, you're up' during player two's turn. Are we
able to turn that call out off during these modes"; daveyvandy: "or correct them for the active player"): a co-op game
plays the game's player 1 (a team game its player 1 or 2), so the ball start's "player N, you're up" process named the
game's player. portcoop.up_call names that process's call of the player-up getter (`site coop_up_call`) and the runtime
wraps it (pad_mode_runtime.c, coop_up_wrap) to answer the player really up; every other caller still hears the game's."""
import glob
import os
import pathlib

import pytest

from pinball_decryptor.plugins.stern import adjustments
from pinball_decryptor.plugins.stern import portcoop
from tests import test_pad1017_coop_lines as L
from tests import test_spike2_mode_roster as R

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = RUNTIME.parent / "ports"


def _up_program(cmphi=False, gate=True, branch_in=False, second_proc=False):
    """Godzilla LE 1.16's framework player code (test_pad1017_coop_lines), the player-up and player-count getters,
    then its "you're up" process (0x555f4's shape, cut down) and the ball start that starts it with more than one
    player (0x5625c's)."""
    w, *_ = L._program()
    at = lambda: L.BASE + 4 * len(w)

    def getter(byte):
        va = at()
        w.extend([L._movw(3, byte & 0xFFFF), L._movt(3, byte), L._ldrb(0, 3), 0xE12FFF1E])
        return va

    up, count = getter(L.PLAYER), getter(L.PLAYERS)

    def proc():
        va = at()
        w.extend([0xE92D4010, 0xE3A000BA])                 # push {r4, lr} ; mov r0, #0xba (the wait)
        w.append(L._bl(at(), 0x8000))
        w.append(0xE3004470)                               # movw r4, #0x470
        call = at()
        w.append(L._bl(at(), up))
        w.extend([0xE2401001, 0xE1A00004])                 # sub r1, r0, #1 ; mov r0, r4
        w.append(L._bl(at(), 0x9000))                      # callout_nth
        if branch_in:
            w.append(0xEA000000 | (((call + 4) - at() - 8) >> 2) & 0xFFFFFF)   # b <the word after the call>
        w.append(0xE8BD8010)                               # pop {r4, pc}
        return va, call

    procs = [proc()] + ([proc()] if second_proc else [])
    for va, _call in procs:
        w.append(0xE92D4010)                               # push {r4, lr}: the ball start
        w.append(L._bl(at(), count))
        w.append(0xE3500001)                               # cmp r0, #1
        if cmphi:
            w.append(0x83540001)                           # cmphi r4, #1
        w.append(0x9A000004 if gate else 0xE1A00000)       # bls / nop
        w += [L._movw(1, va & 0xFFFF), 0xE1A02004, L._movt(1, va), 0xE3000163]
        w.append(L._bl(at(), 0xA000))                      # the process start
        w += [0xE3A00001, 0xE8BD8010]
    return w, [c for _va, c in procs]


@pytest.mark.parametrize("cmphi", [False, True])
def test_the_you_are_up_call_is_named(monkeypatch, cmphi):
    monkeypatch.setattr(adjustments, "AdjustmentTable", L._Adj)
    words, (call,) = _up_program(cmphi=cmphi)
    elf = L._elf(words)
    assert portcoop.up_call(portcoop.Elf(elf), L.PLAYER, L.PLAYERS) == call
    word = lambda va: "0x%08x" % words[(va - L.BASE) // 4]
    got = [l.split() for l in portcoop.lines(elf)[0] if "coop_up_call" in l]
    assert got == [["site", "coop_up_call", "0x%08x" % call, word(call), word(call + 4)]]


@pytest.mark.parametrize("kw", [{"gate": False}, {"branch_in": True}, {"second_proc": True}])
def test_no_line_when_it_cannot_be_told(monkeypatch, kw):
    """No "more than one player" gate (not the turn's call); a branch into the word the wrap moves; two such
    processes (which says whose turn it is cannot be told): the call stays the game's."""
    monkeypatch.setattr(adjustments, "AdjustmentTable", L._Adj)
    words, _ = _up_program(**kw)
    assert portcoop.up_call(portcoop.Elf(L._elf(words)), L.PLAYER, L.PLAYERS) is None
    assert not [l for l in portcoop.lines(L._elf(words))[0] if "coop_up_call" in l]


#: the builds whose ball start has the process, and its getter call (read off the shipped programs)
UP_CALLS = {
    "avengers_infinity_le-1.10.0.elf": 0x5651c, "avengers_infinity_pro-1.10.0.elf": 0x564bc,
    "dungeons_and_dragons_le-1.00.0.elf": 0xa7df8, "dungeons_and_dragons_le-1.10.0.elf": 0xa8258,
    "dungeons_and_dragons_pro-1.10.0.elf": 0xa4f40,
    "foo_fighters_le-1.04.0.elf": 0xaf394, "foo_fighters_pro-1.04.0.elf": 0xaed54,
    "godzilla_le-1.16.0.elf": 0x5562c, "godzilla_pro-1.15.0.elf": 0x554e4, "godzilla_pro-1.16.0.elf": 0x554e4,
    "iron_maiden_le-1.18.0.elf": 0x3004c, "iron_maiden_pro-1.18.0.elf": 0x2ffe0,
    "james_bond_le-1.06.0.elf": 0x9d0b4, "james_bond_pro-1.06.0.elf": 0x9cf6c,
    "jaws_le-1.02.0.elf": 0x56374, "jaws_pro-1.02.0.elf": 0x5697c,
    "jurassic_park_le-1.16.0.elf": 0xdf00c, "jurassic_park_pro-1.16.0.elf": 0xde6b4,
    "king_kong_le-0.96.0.elf": 0x7e990, "king_kong_le-0.97.0.elf": 0x7f208, "king_kong_pro-0.97.0.elf": 0x7e934,
    "led_zeppelin_le-1.21.0.elf": 0x62b64, "led_zeppelin_le-1.22.0.elf": 0x62b64,
    "led_zeppelin_pro-1.22.0.elf": 0x6169c,
    "mando_le-1.45.0.elf": 0xe3e64, "mando_pro-1.45.0.elf": 0xe3f1c,
    "star_wars_le-1.31.0.elf": 0x4edac, "star_wars_pro-1.31.0.elf": 0x4d268,
    "venom_le-1.07.0.elf": 0xd4f14, "venom_pro-1.07.0.elf": 0xd43c8,
}
ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1202/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_the_shipped_calls_and_no_others():
    found = {}
    for p in ELFS:
        e = portcoop.Elf(p)
        pc = portcoop.player_change(e)
        at = portcoop.up_call(e, pc[1], pc[2]) if pc else None
        if at:
            found[os.path.basename(p)] = at
    assert found == {k: v for k, v in UP_CALLS.items() if k in {os.path.basename(p) for p in ELFS}}


def test_the_latest_ports_carry_the_line():
    with_coop = [p for p in sorted(PORTS.glob("*.port")) if "site  coop_player_change" in p.read_text(encoding="utf-8")]
    have = {p.stem for p in with_coop if "site  coop_up_call" in p.read_text(encoding="utf-8")}
    assert have == {"avengers_infinity_le-1.10", "avengers_infinity_pro-1.10", "dungeons_and_dragons_le-1.10",
                    "dungeons_and_dragons_pro-1.10", "foo_fighters_le-1.04", "foo_fighters_pro-1.04",
                    "godzilla_le-1.16", "godzilla_pro-1.16", "iron_maiden_le-1.18", "iron_maiden_pro-1.18",
                    "james_bond_le-1.06", "james_bond_pro-1.06", "jaws_le-1.02", "jaws_pro-1.02",
                    "jurassic_park_le-1.16", "jurassic_park_pro-1.16", "king_kong_le-0.97", "king_kong_pro-0.97",
                    "led_zeppelin_le-1.22", "led_zeppelin_pro-1.22", "mando_le-1.45", "mando_pro-1.45",
                    "star_wars_le-1.31", "star_wars_pro-1.31", "venom_le-1.07", "venom_pro-1.07"}
    text = (PORTS / "godzilla_le-1.16.port").read_text(encoding="utf-8")
    assert "site  coop_up_call           0x0005562c 0xeb0b8c6f 0xe2401001" in text


MAIN = r"""
#include <stdio.h>
static unsigned teammates;
static struct { unsigned turn; int standard; } coop;   /* standard: PAD-1224 */
static unsigned coop_teammates(void) { return teammates; }
static void say(const char *f, ...) { (void)f; }
static unsigned game_player = 1;
static unsigned game_getter(unsigned a, unsigned b, unsigned c, unsigned d) { return game_player; }
static unsigned (*coop_up_game)(unsigned, unsigned, unsigned, unsigned) = game_getter;
@FNS@
int main(void)
{
    printf("plain %u\n", coop_up_wrap(0, 0, 0, 0));
    teammates = 3;                                        /* co-op of three: the game plays player 1 */
    for (coop.turn = 1; coop.turn <= 3; coop.turn++) printf("teammate %u named %u\n", coop.turn, coop_up_wrap(0, 0, 0, 0));
    teammates = 4; game_player = 2; coop.turn = 4;        /* Team 2v2: the game's player 2 is team 2, P4 is up */
    printf("team game %u\n", coop_up_wrap(0, 0, 0, 0));
    teammates = 0; game_player = 2; coop.turn = 1;        /* the co-op game is over: the game's own */
    printf("over %u\n", coop_up_wrap(0, 0, 0, 0));
    return 0;
}
"""


def test_the_call_names_the_player_really_up(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static unsigned coop_panel_box(unsigned n, unsigned turn, unsigned game)",
        "static unsigned coop_up_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)"))
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["plain 1", "teammate 1 named 1", "teammate 2 named 2", "teammate 3 named 3", "team game 4",
                   "over 2"]


def test_the_runtime_arms_it_with_co_op():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "coop_up_arm();" in R._lift(src, "static void coop_arm(void)")
    assert 'hook_call(fn("coop_up_call"), (void *)coop_up_wrap)' in src
