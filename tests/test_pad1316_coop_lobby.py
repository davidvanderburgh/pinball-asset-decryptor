"""PAD-1316 (DoomWalrus666, Godzilla Pro 1.16, CO-OP PLAY from the start menu with two players logged in to Insider
Connected): a game begun from the Insider lobby adds the lobby's players 2..n only after ball 1's start returns - after
the co-op intro and pick hold its serve - so the score panel showed PRESS START for one of them until Action. The
runtime adds them while ball 1 waits (pad_mode_runtime.c coop_lobby_now) and the game's own loop finds them done;
portcoop.lobby_sites finds the game start and its loop's add on every build."""
import glob
import os
import re
from pathlib import Path

import pytest
from types import SimpleNamespace

from pinball_decryptor.plugins.stern import portcoop
from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T

RUNTIME = T.RUNTIME
PORTS = Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "ports"

DUE_MAIN = r"""
#include <stdio.h>
@FN@
int main(void)
{
    printf("%u %u %u %u %u %u %u\n",
           coop_lobby_due(1, 2, 0, 1),        /* a lobby of 2, the co-op game formed: one to add */
           coop_lobby_due(1, 4, 0, 1),        /* a full lobby: three */
           coop_lobby_due(1, 1, 0, 1),        /* no lobby */
           coop_lobby_due(0, 2, 0, 1),        /* not inside the game start */
           coop_lobby_due(1, 2, 1, 1),        /* added already */
           coop_lobby_due(1, 2, 0, 0),        /* the co-op game not formed yet: wait */
           coop_lobby_due(1, 9, 0, 1));       /* nonsense size: none */
    return 0;
}
"""


def test_the_lobby_is_added_once_while_ball_1_waits(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static unsigned coop_lobby_due(unsigned armed, unsigned size, unsigned done, int formed)")
    assert R._host_run(tmp_path, DUE_MAIN.replace("@FN@", fn)).split() == ["1", "3", "0", "0", "0", "0", "0"]


def test_both_holds_add_the_lobby_before_any_start_of_the_intro():
    src = RUNTIME.read_text(encoding="utf-8")
    for head in ("static void ci_ball_hold(unsigned ball)", "static void coop_pick_hold(void)"):
        body = R._lift(src, head)
        assert body.index("coop_lobby_now(") < body.index("ci_start_poll(")
    wrap = R._lift(src, "static unsigned coop_lobby_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "lb.added--;" in wrap and "return 1;" in wrap          # the game's own add, found done
    start = R._lift(src, "static unsigned coop_start_game_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3, "
                         "unsigned s0)")
    assert "lb.size = s0 & 0xff;" in start and "lb.armed = 0;" in start
    assert "coop_lobby_arm();" in src


def test_every_coop_port_names_the_game_start_and_its_lobby_add():
    with_coop = [p for p in PORTS.glob("*.port") if "coop_add_player" in p.read_text(encoding="utf-8")]
    assert len(with_coop) >= 53
    for p in with_coop:
        text = p.read_text(encoding="utf-8")
        start = re.search(r"^site\s+coop_start_game\s+0x([0-9a-f]+) 0x([0-9a-f]+)", text, re.M)
        add = re.search(r"^site\s+coop_lobby_add\s+0x([0-9a-f]+) 0x([0-9a-f]+)", text, re.M)
        assert start and add, p.name
        assert int(start.group(2), 16) & 0xFFFF4000 == 0xE92D4000, p.name     # the game start's push {.., lr}
        assert int(add.group(2), 16) >> 24 == 0xEB, p.name                    # the loop's bl
        assert 0 < int(add.group(1), 16) - int(start.group(1), 16) < 0x400, p.name


def _bl(frm, to):
    return 0xEB000000 | ((to - frm - 2) & 0xFFFFFF)


def _program(fifth_word=True):
    """A made-up program in the framework's shape: add (0), the Start button's add (10, calls add), the game start
    (30: reads its fifth word off the stack, then a loop calling the Start button's add with its own words)."""
    w = [0xE320F000] * 60                                       # nop
    w[0] = 0xE92D4038                                           # add: push {r3, r4, r5, lr}
    w[10], w[14] = 0xE92D41F0, _bl(14, 0)                       # full: push ; .. ; bl add
    w[30] = 0xE92D47F0                                          # start: push {r4-sl, lr} (8 words)
    w[32] = 0xE59D5020 if fifth_word else 0xE1A05000            # ldr r5, [sp, #0x20]  (or mov r5, r0)
    w[40] = _bl(40, 50)                                         # bl <can add>
    w[41:45] = [0xE1A00007, 0xE1A01009, 0xE1A0200A, 0xE1A03008]  # mov r0, r7 ; mov r1, sb ; mov r2, sl ; mov r3, r8
    w[45], w[46] = _bl(45, 10), 0xE2506000                      # bl full ; subs r6, r0, #0
    w[47] = 0xEAFFFFF6                                          # b back to the loop's test (40)
    w[50] = 0xE92D4010                                          # can add: push {r4, lr}
    return SimpleNamespace(words=w, text_va=0x1000)


#: shipped programs, when PAD_GAME_ELFS points at a folder of them (<build>-<version>[_spike2].elf)
ELFS = sorted(glob.glob(os.path.join(os.environ.get("PAD_GAME_ELFS", "-"), "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_the_shipped_programs_give_the_ports_lines():
    """Godzilla Pro 1.16: the game start 0x45a08c, its loop's add 0x45a1b4 (emulator-proven); each port's lines are
    what lobby_sites reads off that build's own program."""
    seen = 0
    for p in ELFS:
        key = re.sub(r"-(\d+)[_.](\d+)[_.]\d+(_spike2)?$", r"-\1.\2", os.path.basename(p)[:-4])
        port = PORTS / (key + ".port")
        if not port.exists() or "coop_add_player" not in port.read_text(encoding="utf-8"):
            continue
        want = [l for l in port.read_text(encoding="utf-8").splitlines()
                if l.startswith(("site  coop_start_game", "site  coop_lobby_add"))]
        got = [l for l in portcoop.lines(p)[0] if l.startswith(("site  coop_start_game", "site  coop_lobby_add"))]
        assert got == want, key
        seen += 1
    assert seen


def test_lobby_sites_finds_the_game_start_and_its_loop_add():
    assert portcoop.lobby_sites(_program(), 0x1000) == (0x1000 + 4 * 30, 0x1000 + 4 * 45)
    assert portcoop.lobby_sites(_program(fifth_word=False), 0x1000) is None   # no lobby size: not the game start
