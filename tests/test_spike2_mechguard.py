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
    assert re.search(r'GAMEPG=\$!\n(?:\s*#[^\n]*\n)*\s*PAD_GAME="\$GAME" PAD_LAUNCH_HOLD="\$\{PAD_LAUNCH_HOLD:-0\}" '
                     r'PAD_ADJ_KEEP="\$ROOT/data/padkeep-\$GAME\.json" \\\n\s*python3 "\$RIG/mechguard\.py" "\$GAMEPG" >> "\$LOG"',
                     launch[:1600])
    assert re.search(r"^\s*/\\\[mechguard\\\]/\s*\{ print \"\[event\] \" \$0; fflush\(\); next \}", src, re.M)


def test_off_by_choice(monkeypatch):
    monkeypatch.setenv("PAD_MECHGUARD", "0")
    monkeypatch.delenv("PAD_LAUNCH_HOLD", raising=False)
    monkeypatch.delenv("PAD_ADJ_KEEP", raising=False)
    assert M.main(["mechguard.py", "1"]) == 0


# --------------------------------------------------------------------------
# PAD-1487 (DragonRR): "Hold the ball in the shooter lane" holds TIMED PLUNGER
# --------------------------------------------------------------------------

# Godzilla LE 1.16's launch settings as shipped (id 96 / 97 there)
LAUNCH = SPECS + [("AD_TIMED_PLUNGER", 0, 0, 300), ("AD_FLIPPER_BALL_LAUNCH", 0, 0, 4)]


def test_the_timed_plunger_is_found_and_is_not_a_mech_switch():
    elf = make_elf(LAUNCH)
    t = A.AdjustmentTable(elf)
    assert M.launch_setting(elf) == (t.by_name["AD_TIMED_PLUNGER"], 300)
    ids, _table = M.guarded(elf)
    assert set(ids.values()) == MECHS
    assert M.launch_setting(make_elf(SPECS)) is None      # a game without one


def test_the_hold_sets_it_off_and_keeps_the_machines_own(tmp_path, capsys):
    keep = str(tmp_path / "padkeep-godzilla_le.json")
    live = FakeLive({96: (10, _ck(10))})
    hold = M.LaunchHold(live, (96, 300), True, keep)
    assert hold.look() is False                           # holds for the whole run
    assert live.vals[96] == (0, _ck(0))
    assert M.load_keep(keep) == {"AD_TIMED_PLUNGER": 10}
    assert "TIMED PLUNGER was 10 s" in capsys.readouterr().out
    # the service menu setting it again mid-run is held again
    live.vals[96] = (20, _ck(20))
    hold.look()
    assert live.vals[96][0] == 0 and M.load_keep(keep) == {"AD_TIMED_PLUNGER": 20}


def test_a_hold_on_a_setting_already_off_keeps_nothing(tmp_path, capsys):
    keep = str(tmp_path / "padkeep.json")
    live = FakeLive({96: (0, _ck(0))})
    hold = M.LaunchHold(live, (96, 300), True, keep)
    hold.look()
    hold.look()
    assert live.vals[96] == (0, _ck(0)) and not os.path.exists(keep)
    assert capsys.readouterr().out.count("holding the ball in the shooter lane") == 1


def test_a_value_not_loaded_yet_is_left_alone(tmp_path):
    keep = str(tmp_path / "padkeep.json")
    live = FakeLive({96: (10, 0x00)})                     # check byte wrong: not loaded
    assert M.LaunchHold(live, (96, 300), True, keep).look() is False
    assert live.vals[96] == (10, 0x00) and not os.path.exists(keep)


def test_the_next_run_without_the_hold_puts_it_back(tmp_path, capsys):
    keep = str(tmp_path / "padkeep.json")
    M.save_keep(keep, {"AD_TIMED_PLUNGER": 10})
    live = FakeLive({96: (0, _ck(0))})                    # the held run's 0 came back from NVRAM
    hold = M.LaunchHold(live, (96, 300), False, keep)
    assert hold.look() is True
    assert live.vals[96] == (10, _ck(10)) and not os.path.exists(keep)
    assert "put back to the machine's own 10 s" in capsys.readouterr().out


def test_a_setting_changed_since_is_not_overwritten(tmp_path):
    keep = str(tmp_path / "padkeep.json")
    M.save_keep(keep, {"AD_TIMED_PLUNGER": 10})
    live = FakeLive({96: (25, _ck(25))})                  # set by hand on the machine since
    assert M.LaunchHold(live, (96, 300), False, keep).look() is True
    assert live.vals[96][0] == 25 and not os.path.exists(keep)


def test_a_chrooted_user_run_finds_the_program_under_its_root():
    """PAD-1487: on a rig run as a user, maps names the game with the slot's
    chroot prefix and only root/games/<title>/game opens (proven on slot 1:
    map_files EPERM, root/<whole path> ENOENT, which had kept the guard off)."""
    path = "/home/david/padslots/1/root/games/godzilla_le/game"
    got = M._program_paths(42, 0x18000, 0x70f000, path, root_link="/home/david/padslots/1/root")
    assert got[:3] == ["/proc/42/map_files/18000-70f000", "/proc/42/root" + path,
                       "/proc/42/root/games/godzilla_le/game"]
    assert got[-1] == path and len(got) == len(set(got))
    # an unchrooted (root) run: the old two first, unchanged
    assert M._program_paths(42, 0x8000, 0x9000, "/games/x/game", root_link="/")[:2] == \
        ["/proc/42/map_files/8000-9000", "/proc/42/root/games/x/game"]


def test_watch_starts_the_guard_for_a_hold_even_with_mechguard_off(monkeypatch):
    """PAD_MECHGUARD=0 is about the mechs: a hold or a value to put back still runs."""
    monkeypatch.setenv("PAD_MECHGUARD", "0")
    monkeypatch.setenv("PAD_LAUNCH_HOLD", "1")
    looked = []
    monkeypatch.setattr(M, "find_game", lambda root: looked.append(root) or None)
    monkeypatch.setattr(M.os.path, "exists", lambda p: False)   # the launch gone at once
    M.main(["mechguard.py", "1"])
    assert looked == [1]                          # it went looking for the game
    monkeypatch.setenv("PAD_LAUNCH_HOLD", "0")
    looked.clear()
    M.main(["mechguard.py", "1"])
    assert looked == []                           # nothing to do: returns at once
