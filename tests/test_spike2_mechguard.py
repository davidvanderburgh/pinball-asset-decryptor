"""mechguard.py: a game setting that switches a mech off is set back Off (PAD-1225).

A player's Batman 66 never sent its turntable anywhere - no boot test, no ball
search, no turn for the Bat Phone hurry-up - while its crane moved. On the rig
AD_TURNTABLE_MOTOR_DISABLED = 1 gives that same log, and the emulator's mechs
cannot break, so the guard turns such settings Off in the running game.
"""
import os
import re
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "spike2_emu"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mechguard as M  # noqa: E402
from test_stern_adjustments import make_elf  # noqa: E402

from pinball_decryptor.plugins.stern import adjustments as A  # noqa: E402

# batman 1.14's mech switches and their neighbours (defaults, min, max as shipped)
SPECS = [("AD_FREE_PLAY", 0, 0, 1),
         ("AD_PENGUIN_MOTOR_DISABLED", 0, 0, 1),
         ("AD_PENGUIN_MOTOR_SHUTDOWN_COUNT", 0, 0, 5),
         ("AD_TURNTABLE_MOTOR_DISABLED", 0, 0, 1),
         ("AD_TURNTABLE_MOTOR_CONSECUTIVE_SHUTDOWN_COUNT", 2, 0, 5),
         ("AD_TURNTABLE_MOTOR_LAG", 1250, 0, 2000),
         ("AD_TURNTABLE_DIVERTER_DISABLED", 0, 0, 1),
         ("AD_TURNTABLE_MAGNET_DISABLED", 0, 0, 1),
         ("AD_LEFT_CONTROL_GATE_DISABLED", 0, 0, 1),
         ("AD_DISABLE_Q24_KNOCKER_WHEN_HEADPHONES_DETECTED", 0, 0, 1),
         ("AD_COIN_DOOR_DISABLE_TILT", 0, 0, 1),
         ("AD_SHAKER_MOTOR", 3, 0, 3)]
MECHS = {"AD_PENGUIN_MOTOR_DISABLED", "AD_TURNTABLE_MOTOR_DISABLED",
         "AD_TURNTABLE_DIVERTER_DISABLED", "AD_TURNTABLE_MAGNET_DISABLED",
         "AD_LEFT_CONTROL_GATE_DISABLED"}


def test_only_the_switches_that_take_a_mech_out_are_guarded():
    ids, (table, elem) = M.guarded(make_elf(SPECS))
    assert set(ids.values()) == MECHS
    t = A.AdjustmentTable(make_elf(SPECS))
    assert (table, elem) == (t.table_va, t.elem)
    assert all(t.names[i] == n for i, n in ids.items())


def test_the_table_is_found_without_numpy(monkeypatch):
    elf = make_elf(SPECS)
    want = A.AdjustmentTable(elf)
    monkeypatch.setattr(A.AdjustmentTable, "_longest_name_run", M._pure_name_run)
    got = A.AdjustmentTable(elf)
    assert (got.table_va, got.elem, got.names) == (want.table_va, want.elem, want.names)


class FakeLive:
    """The game's live values: {id: (u32, check byte)}."""

    def __init__(self, vals):
        self.vals = dict(vals)

    def get(self, i):
        return self.vals[i]

    def set(self, i, v):
        b = struct.pack("<i", v)
        self.vals[i] = (v, ~sum(b) & 0xff)


def _ck(v):
    return ~sum(struct.pack("<i", v)) & 0xff


def test_a_switched_off_mech_is_switched_back_on_once(capsys):
    ids = {331: "AD_TURNTABLE_MOTOR_DISABLED", 327: "AD_PENGUIN_MOTOR_DISABLED"}
    live = FakeLive({331: (1, _ck(1)), 327: (0, _ck(0))})
    done = set()
    assert M.guard(live, ids, done) == ["AD_TURNTABLE_MOTOR_DISABLED"]
    assert live.vals[331] == (0, 0xff) and live.vals[327] == (0, 0xff)
    out = capsys.readouterr().out
    assert out.count("[mechguard] TURNTABLE MOTOR DISABLED was On") == 1
    # the game turning it On again is turned back, without a second line
    live.vals[331] = (1, _ck(1))
    assert M.guard(live, ids, done) == ["AD_TURNTABLE_MOTOR_DISABLED"]
    assert live.vals[331][0] == 0 and capsys.readouterr().out == ""


def test_a_value_that_is_not_a_valid_on_is_left_alone():
    ids = {331: "AD_TURNTABLE_MOTOR_DISABLED"}
    live = FakeLive({331: (1, 0x00)})          # not yet loaded / not an adjustment value
    assert M.guard(live, ids, set()) == [] and live.vals[331] == (1, 0x00)


def test_watch_starts_the_guard_with_the_game_and_forwards_its_lines():
    src = open(os.path.join(ROOT, "tools", "spike2_emu", "watch.sh"), encoding="utf-8").read()
    launch = src[src.index('bash "$RIG/run_game.sh" > "$LOG"'):]
    assert re.search(r'GAMEPG=\$!\n(?:\s*#[^\n]*\n)*\s*PAD_GAME="\$GAME" python3 "\$RIG/mechguard\.py" "\$GAMEPG" >> "\$LOG"',
                     launch[:1200])
    assert re.search(r"^\s*/\\\[mechguard\\\]/\s*\{ print \"\[event\] \" \$0; fflush\(\); next \}", src, re.M)


def test_off_by_choice(monkeypatch):
    monkeypatch.setenv("PAD_MECHGUARD", "0")
    assert M.main(["mechguard.py", "1"]) == 0
