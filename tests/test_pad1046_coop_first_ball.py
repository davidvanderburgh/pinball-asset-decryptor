"""PAD-1046: a co-op teammate's ball 1 is not a first ball (pad_mode_runtime.c coop_first_ball_wrap; portcoop.first_ball).

DoomWalrus666 (Godzilla, two-player co-op): player 1 started Gigan on ball 1 and made 7 shots; player 2's ball 1 had
to light battle again with both ramps, and on ball 2 the selection screen showed no battle started - while Biollante,
started on ball 2, carried over to player 2 as it should. The framework's ball start tells a first ball by its ball
getter reading 1 and on one runs every rule's first-ball setup; each teammate plays ball 1, so teammates 2..n set the
team's ball-1 progress back. The runtime answers that one read 2 for them."""
import glob
import os
import pathlib
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import adjustments
from pinball_decryptor.plugins.stern import portcoop
from tests import test_pad1017_coop_lines as L
from tests import test_pad1017_coop_turns as T
from tests import test_spike2_mode_roster as R

RUNTIME = T.RUNTIME

# the framework's ball start as the program has it, modelled: its first-ball setup (the rules' per-player starts)
# runs when the ball getter's call in it reads 1
MAIN = T.MAIN.split("static void play(")[0].replace("@FNS@", r"""
static unsigned game_ball(unsigned r0, unsigned r1, unsigned r2, unsigned r3) { return bytes[1]; }
static unsigned (*coop_ball_game)(unsigned, unsigned, unsigned, unsigned) = game_ball;
@FNS@
static unsigned setups;                                   /* the first-ball setups the game ran */
static void ball_start(void)
{
    unsigned ball = coop_first_ball_wrap(0, 0, 0, 0);
    if (ball == 1) setups++;
    printf("start ball %u teammate %u: the game reads %u%s\n", bytes[1], coop.turn ? coop.turn : 1, ball,
           ball == 1 ? " - FIRST BALL SETUP" : "");
}
static void play(unsigned team)
{
    unsigned k;
    memset(&coop, 0, sizeof coop);
    bytes[0] = 1; bytes[1] = 1; players = 1; extra = 0; game_no++; setups = 0;
    button = 1;
    for (k = 1; k < team; k++) coop_add_wrap(0, 0, 0, 0);
    button = 0;
    printf("team %u\n", team);
    do ball_start(); while (coop_change_wrap(0, 0, 0, 0));
    printf("setups %u\n", setups);
}
int main(void)
{
    play(1);          /* no team: the game's own one-player game */
    play(2);
    play(4);
    return 0;
}
""")


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static unsigned coop_next_turn(unsigned n, unsigned turn, unsigned before, unsigned after, unsigned down)",
        "static unsigned coop_teammates(void)",
        "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)",
        "static unsigned coop_change_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)",
        "static unsigned coop_first_ball_answer(unsigned n, unsigned turn, unsigned ball)",
        "static unsigned coop_first_ball_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)"))
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def _game(out, team):
    start = out.index("team %d" % team)
    end = next(i for i in range(start, len(out)) if out[i].startswith("setups "))
    return [l for l in out[start:end] if l.startswith("start ")], out[end]


def test_the_first_ball_setup_runs_once_a_game_however_many_teammates(tmp_path):
    out = _run(tmp_path)
    for team in (1, 2, 4):
        starts, setups = _game(out, team)
        assert setups == "setups 1", (team, starts)
        assert starts[0] == "start ball 1 teammate 1: the game reads 1 - FIRST BALL SETUP"
    starts, _ = _game(out, 2)
    assert starts[1] == "start ball 1 teammate 2: the game reads 2"
    assert starts[2:] == ["start ball %d teammate %d: the game reads %d" % (b, t, b) for b in (2, 3) for t in (1, 2)]
    starts, _ = _game(out, 4)
    assert starts[1:4] == ["start ball 1 teammate %d: the game reads 2" % t for t in (2, 3, 4)]
    assert "co-op: teammate 2's ball 1 - the game's first-ball setup ran at teammate 1's, so the team's progress holds" \
        in out


def test_coop_arms_the_call_where_the_ball_start_makes_it():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = R._lift(src, "static void coop_arm(void)")
    assert 'fn("coop_first_ball")' in arm and "hook_call(at, (void *)coop_first_ball_wrap)" in arm


# ---- the finder ---------------------------------------------------------------------------------------------------

def _ball_start_program(kill_first=True, cmp_reg=4):
    """The player code of test_pad1017_coop_lines plus Godzilla LE 1.16's ball getter and ball start, cut down."""
    w, *_ = L._program()
    at = lambda: L.BASE + 4 * len(w)
    getter = at()
    w += [L._movw(3, L.PLAYER & 0xFFFF), L._movt(3, L.PLAYER), L._ldrb(0, 3, 1), 0xE12FFF1E]
    kill = at()
    w += [0xE12FFF1E]
    start = at()
    w += [0xE92D4070, 0xE3A00025, 0xE3A01000, 0xE1A00000, 0xE3500000, 0x0A000040]
    w += [0xE3A01080, 0xE3A00000] if kill_first else [0xE3A01081, 0xE3A00000]
    w.append(L._bl(at(), kill))
    call = at()
    w.append(L._bl(at(), getter))
    w += [0xE1A04000, 0xE3A00009, 0xE1A00000, 0xE2203001, 0xE1A05000, 0xE3500001 | cmp_reg << 16, 0xE8BD8070]
    return w, getter, start, call


def test_first_ball_finds_the_ball_start_s_read_of_the_ball(monkeypatch):
    monkeypatch.setattr(adjustments, "AdjustmentTable", L._Adj)
    words, getter, _start, call = _ball_start_program()
    e = portcoop.Elf(L._elf(words))
    assert portcoop.ball_getters(e, L.PLAYER) == [getter]
    assert portcoop.first_ball(e, L.PLAYER) == call
    lines = portcoop.lines(L._elf(words))[0]
    assert "site  coop_first_ball    0x%08x 0x%08x 0xe1a04000" % (call, words[(call - L.BASE) // 4]) in lines


def test_first_ball_needs_the_proc_kill_and_the_test_against_1(monkeypatch):
    monkeypatch.setattr(adjustments, "AdjustmentTable", L._Adj)
    words, *_ = _ball_start_program(kill_first=False)
    assert portcoop.first_ball(portcoop.Elf(L._elf(words)), L.PLAYER) is None
    words, *_ = _ball_start_program(cmp_reg=6)        # the ball is never tested: not the ball start
    assert portcoop.first_ball(portcoop.Elf(L._elf(words)), L.PLAYER) is None
    # no line, and co-op's own four lines still come
    lines = portcoop.lines(L._elf(words))[0]
    assert not any("coop_first_ball" in l for l in lines) and lines[0].startswith("site  coop_player_change")


ELFS = sorted(p for d in os.environ.get("PAD_GAME_ELFS", "C:/tmp/PAD-1041/elfs").split(";")
              for p in glob.glob(os.path.join(d, "*.elf")))


@pytest.mark.skipif(not ELFS, reason="no shipped game programs here (PAD_GAME_ELFS)")
def test_every_shipped_build_has_the_first_ball_read():
    found = {}
    for p in ELFS:
        e = portcoop.Elf(p)
        pc = portcoop.player_change(e)
        found[os.path.basename(p)] = portcoop.first_ball(e, pc[1]) if pc else None
    assert [k for k, v in found.items() if v is None] == []
    if "godzilla_le-1_16_0_spike2.elf" in found:
        assert found["godzilla_le-1_16_0_spike2.elf"] == 0x2A7714


def test_every_latest_port_carries_the_first_ball_read():
    ports = L._latest_ports()
    assert len(ports) == 53
    for p in ports:
        text = open(p, encoding="utf-8").read()
        m = re.search(r"^site  coop_first_ball    0x[0-9a-f]{8} 0xeb[0-9a-f]{6} 0xe1a04000$", text, re.M)
        assert m, os.path.basename(p)
    gz = open(next(p for p in ports if p.endswith("godzilla_le-1.16.port")), encoding="utf-8").read()
    assert "site  coop_first_ball    0x002a7714 0xeb02445a 0xe1a04000" in gz
