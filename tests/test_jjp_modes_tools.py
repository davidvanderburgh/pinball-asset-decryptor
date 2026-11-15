"""Headless tests for the JJP custom-modes tooling (PAD-1335):
jjppoke.py's switch lookup and swdump.find_pid keeping to the JJP jail."""
import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(HERE, "tools", "jjp_emu")


def _load(name):
    path = os.path.join(RIG, name + ".py")
    if not os.path.exists(path):
        pytest.skip(f"tools/jjp_emu/{name}.py not present")
    sys.path.insert(0, RIG)
    try:
        spec = importlib.util.spec_from_file_location(name + "_undertest", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(RIG)
    return mod


SWITCHES = [
    {"symbol": "switch_target_jam", "name": "Jam Target", "frame_byte": 9, "frame_bit": 16, "inverted": False},
    {"symbol": "dswitch_start", "name": "Start Button", "frame_byte": 3, "frame_bit": 1, "inverted": False},
    {"symbol": "switch_045", "name": "not used", "frame_byte": 9, "frame_bit": 32, "inverted": False},
    {"symbol": "switch_046", "name": "not used", "frame_byte": 9, "frame_bit": 64, "inverted": False},
]


def test_poke_finds_by_symbol_or_display_name_case_insensitive():
    poke = _load("jjppoke")
    assert poke.find(SWITCHES, "SWITCH_TARGET_JAM")["frame_byte"] == 9
    assert poke.find(SWITCHES, "start button")["symbol"] == "dswitch_start"


def test_poke_refuses_an_ambiguous_display_name():
    poke = _load("jjppoke")
    # Two switches are called "not used": a name that is not unique presses nothing.
    assert poke.find(SWITCHES, "not used") is None
    assert poke.find(SWITCHES, "no_such_switch") is None


def test_find_pid_ignores_a_fatter_game_outside_the_jjp_jail(monkeypatch):
    swdump = _load("swdump")
    # pid 10: a Spike 2 rig's `game` (fat, rooted in a rig slot); 11/12: the JJP game.
    roots = {10: "/home/u/padslots/2/root", 11: "/var/tmp/jjp_run", 12: "/var/tmp/jjp_run"}
    rss = {10: 900000, 11: 300000, 12: 5000}
    monkeypatch.setattr(swdump.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout="10\n11\n12\n"))
    monkeypatch.setattr(swdump.os, "readlink", lambda p: roots[int(p.split("/")[2])])
    real_open = open

    def fake_open(path, *a, **k):
        if str(path).startswith("/proc/") and str(path).endswith("/statm"):
            pid = int(str(path).split("/")[2])
            return types.SimpleNamespace(read=lambda: f"1 {rss[pid]} 0",
                                         __enter__=None, __exit__=None)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    assert swdump.find_pid(jail="/var/tmp/jjp_run") == 11
