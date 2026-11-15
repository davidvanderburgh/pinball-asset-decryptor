"""PAD-1309: padmenu_proc.py, the P-ROC titles' way back to the boot menu (EXIT held 5 s).

The hook wraps pinproc.PinPROC and, on each get_events(), asks the game's own `exit` switch
(procgame's Switch: name, number, is_active()) whether it is active.  Proven on the real
Rick and Morty and Alice Cooper in the Spooky P-ROC rig; this pins the logic without one.
"""
import importlib.util
import os
import sys
import types

import pytest

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "spike2_emu", "codeselect", "padmenu_proc.py")


def load(monkeypatch, **env):
    for k in ("CODESELECT_REBOOT", "PROC_EMU_CTL", "PROC_EMU_FPGA", "SPP_LOG",
              "PADMENU_HOLD_MS", "PADMENU_SWITCH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("padmenu_proc_under_test", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Switch(object):            # procgame's class name is what the hook looks for
    def __init__(self, name, number):
        self.name, self.number, self.active = name, number, False

    def is_active(self):
        return self.active


def fake_pinproc():
    mod = types.ModuleType("pinproc")

    class PinPROC(object):
        def __init__(self, machine_type):
            self.machine_type = machine_type
            self.calls = 0

        def get_events(self):
            self.calls += 1
            return [{"type": 1, "value": 7, "time": 0}]

        def switch_update_rule(self, *a):
            return "rule %s" % (a,)

    mod.PinPROC = PinPROC
    return mod


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]

    def run(m, board, secs, step=0.05):
        end = t[0] + secs
        while t[0] < end:
            board.get_events()
            t[0] += step
    return t, run


def setup(monkeypatch, clock, **env):
    m = load(monkeypatch, **env)
    t, run = clock
    monkeypatch.setattr(m.time, "time", lambda: t[0])
    mod = fake_pinproc()
    m._wrap(mod)
    board = mod.PinPROC("pdb")
    restarts = []
    return m, board, run, restarts


def test_the_board_object_is_passed_through(monkeypatch, clock):
    m, board, run, _ = setup(monkeypatch, clock)
    assert board.machine_type == "pdb"
    assert board.get_events() == [{"type": 1, "value": 7, "time": 0}]
    assert board.switch_update_rule(7, "closed") == "rule (7, 'closed')"
    board.extra = 5
    assert object.__getattribute__(board, "_real").extra == 5
    m._wrap(sys.modules.get("x", types.ModuleType("x")))       # nothing to wrap: no error


def test_a_hold_restarts_once_and_a_tap_does_not(monkeypatch, clock):
    m, board, run, _ = setup(monkeypatch, clock, PADMENU_HOLD_MS="1000",
                             CODESELECT_REBOOT="touch /x")
    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda argv, **k: spawned.append((argv, k["env"])))
    sw = Switch("exit", 7)
    keep = [Switch("down", 6), sw]                 # live objects the hook can find
    run(m, board, 0.5)                             # found, nothing held
    sw.active = True
    run(m, board, 0.6)                             # a tap
    sw.active = False
    run(m, board, 0.3)
    assert spawned == []
    sw.active = True
    run(m, board, 2.5)                             # a hold
    assert len(spawned) == 1
    argv, env = spawned[0]
    assert argv[:2] == ["/bin/sh", "-c"] and "reboot" in argv[2]
    assert env["CODESELECT_REBOOT"] == "touch /x" and "LD_PRELOAD" not in env
    run(m, board, 3)
    assert len(spawned) == 1                       # never twice
    del keep


def test_the_rig_without_a_stand_in_never_restarts(monkeypatch, clock):
    m, board, run, _ = setup(monkeypatch, clock, PADMENU_HOLD_MS="500", PROC_EMU_CTL="/tmp/ctl")
    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda argv, **k: spawned.append(argv))
    sw = Switch("exit", 7)
    sw.active = True
    run(m, board, 2)
    assert spawned == []
    del sw


def test_another_switch_name_is_not_taken(monkeypatch, clock):
    m, board, run, _ = setup(monkeypatch, clock, PADMENU_HOLD_MS="500", CODESELECT_REBOOT="x")
    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda argv, **k: spawned.append(argv))
    other = Switch("exitLane", 9)
    other.active = True
    run(m, board, 2)
    assert spawned == []
    del other
