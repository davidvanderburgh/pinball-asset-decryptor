"""PAD-1043 (DoomWalrus666, Godzilla: "Player one's score is highlighted in yellow regardless of which players turn
it is"): a co-op game plays player 1, so the score panel lit player 1's box all game. portcoop.py names the panel's
own calls of the player-up getter (`site coop_panel_lit`, `site coop_panel_up[_n]`) and the runtime answers them with
the teammate up (pad_mode_runtime.c, coop_panel_wrap); every other caller still hears player 1."""
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


def _panel_program(lit_functions=1):
    """Godzilla LE 1.16's framework player code (test_pad1017_coop_lines), then the getter, the panel's "player
    changed" check and its frame update (0x1ae3a4 / 0x1ae4e0's shapes, cut down)."""
    w, *_ = L._program()
    at = lambda: L.BASE + 4 * len(w)
    getter = at()
    w += [L._movw(3, L.PLAYER & 0xFFFF), L._movt(3, L.PLAYER), L._ldrb(0, 3), 0xE12FFF1E]
    check = at() + 8
    w += [0xE92D4030, 0xE1A04000]                         # push {r4, r5, lr} ; mov r4, r0
    w.append(L._bl(at(), getter))
    w += [L._ldrb(3, 4, 0x1B5), 0xE1530000, 0xE8BD8030]  # ldrb r3, [r4, #0x1b5] ; cmp r3, r0 ; pop
    lits = []
    for _ in range(lit_functions):
        lits.append(at() + 4)
        w.append(0xE92D4FF0)                              # push {r4-fp, lr}
        w.append(L._bl(at(), getter))
        w += [0xE1A07000, L._ldrb(3, 6, 0x1B4),           # mov r7, r0 ; ldrb r3, [r6, #0x1b4]: the count
              0xE0658007, 0xE16F8F18, 0xE1A082A8,         # rsb r8, r5, r7 ; clz r8, r8 ; lsr r8, r8, #5
              0xE5903000, 0xE5933040, 0xE12FFF33,         # ldr r3, [r0] ; ldr r3, [r3, #0x40] ; blx r3: the colour
              0xE35B0005, 0xE8BD8FF0]                     # cmp fp, #5 ; pop
    return w, getter, check, lits


def test_the_panel_calls_are_named(monkeypatch):
    monkeypatch.setattr(adjustments, "AdjustmentTable", L._Adj)
    words, getter, check, (lit,) = _panel_program()
    elf = L._elf(words)
    assert portcoop.player_getter(portcoop.Elf(elf), L.PLAYER) == getter
    panel = [l.split() for l in portcoop.lines(elf)[0] if "coop_panel" in l]
    word = lambda va: "0x%08x" % words[(va - L.BASE) // 4]
    assert panel == [["site", "coop_panel_lit", "0x%08x" % lit, word(lit), word(lit + 4)],
                     ["site", "coop_panel_up", "0x%08x" % check, word(check), word(check + 4)]]


def test_two_panels_of_the_shape_name_none(monkeypatch):
    """Which one is the score panel cannot be told: the panel stays the game's rather than a wrong call wrapped."""
    monkeypatch.setattr(adjustments, "AdjustmentTable", L._Adj)
    words, *_ = _panel_program(lit_functions=2)
    assert not [l for l in portcoop.lines(L._elf(words))[0] if "coop_panel" in l]


#: the builds whose score panel lights the player up's box, and their calls (read off the shipped programs)
PANELS = {
    "godzilla_le-1_16_0_spike2.elf": ["0x001ae4e0", "0x001ae3a4"],
    "godzilla_pro-1_16_0_spike2.elf": ["0x001aa084", "0x001a9f48"],
    "godzilla_pro-1_15_0.elf": ["0x001aa084", "0x001a9f48"],          # an older build (no co-op in its port)
    "avengers_infinity_le-1_10_0.elf": ["0x00160e9c", "0x00160d38"],
    "avengers_infinity_pro-1_10_0.elf": ["0x0015f86c", "0x0015f708"],
    "jurassic_park_the_pin-1_05_0.elf": ["0x0009fd90", "0x0009fb2c"],
    "uncanny_xmen_le-0_98_0.elf": ["0x0010caa8", "0x0010c570", "0x0010ff04"],
    "uncanny_xmen_pro-0_98_0.elf": ["0x00107b28", "0x001075f0", "0x0010af84"],
}
ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1041/elfs;C:/tmp/PAD-1010/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_the_shipped_panels_and_no_others():
    found = {os.path.basename(p): [l.split()[2] for l in portcoop.lines(p)[0] if "coop_panel" in l] for p in ELFS}
    assert {k: v for k, v in found.items() if v} == {k: v for k, v in PANELS.items() if k in found}


def test_the_latest_ports_carry_the_panel_lines():
    for port, n in (("godzilla_le-1.16", 2), ("godzilla_pro-1.16", 2), ("avengers_infinity_le-1.10", 2),
                    ("avengers_infinity_pro-1.10", 2), ("jurassic_park_the_pin-1.05", 2),
                    ("uncanny_xmen_le-0.98", 3), ("uncanny_xmen_pro-0.98", 3)):
        text = (PORTS / (port + ".port")).read_text(encoding="utf-8")
        assert len([l for l in text.splitlines() if l.startswith("site  coop_panel_")]) == n, port


MAIN = r"""
#include <stdio.h>
static int in_game;
static unsigned teammates;
static struct { unsigned turn; } coop;
static int pm_in_game(void) { return in_game; }
static unsigned coop_teammates(void) { return teammates; }
static unsigned game_getter(unsigned a, unsigned b, unsigned c, unsigned d) { return 1; }   /* the game plays player 1 */
static unsigned (*coop_panel_game)(unsigned, unsigned, unsigned, unsigned) = game_getter;
@FNS@
int main(void)
{
    printf("plain %u\n", coop_panel_wrap(0, 0, 0, 0));
    in_game = 1;
    printf("one-player %u\n", coop_panel_wrap(0, 0, 0, 0));
    teammates = 3;
    for (coop.turn = 1; coop.turn <= 3; coop.turn++) printf("teammate %u lit %u\n", coop.turn, coop_panel_wrap(0, 0, 0, 0));
    coop.turn = 2; in_game = 0;
    printf("over %u\n", coop_panel_wrap(0, 0, 0, 0));
    return 0;
}
"""


def test_the_panel_lights_the_teammate_up(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static unsigned coop_panel_box(unsigned n, unsigned turn, unsigned game)",
        "static unsigned coop_panel_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)"))
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["plain 1", "one-player 1", "teammate 1 lit 1", "teammate 2 lit 2", "teammate 3 lit 3", "over 1"]


def test_the_runtime_arms_the_panel_with_co_op():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = R._lift(src, "static void coop_arm(void)")
    assert "coop_panel_arm();" in arm
    assert '"coop_panel_lit", "coop_panel_up", "coop_panel_up_2"' in src
