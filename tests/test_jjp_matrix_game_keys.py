"""The switch matrix takes its keys from the GAME's window too (item 118).

jjpkeys.py reports presses made in the game's nested display; the matrix maps
them through its own resolved keymap and applies them with the handlers its Tk
bindings use.  Pure: no Tk window, no X server."""
import importlib.util
import os
import types

import pytest

pytest.importorskip("tkinter")  # jjpsw imports tkinter at module load

JJPSW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools", "jjp_emu", "jjpsw.py")


@pytest.fixture(scope="module")
def m():
    spec = importlib.util.spec_from_file_location("jjpsw_gamekeys", JJPSW)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_game_window_uses_the_matrix_keymap(m):
    bindings = [(("1",), "Start", (3, 1)),
                (("Left", "a"), "L Flipper", (1, 1)),
                (("Return",), "Menu Enter", None)]           # unresolved: no key
    got = m.game_key_actions(bindings, ball_keys=[(("space",), "Plunge", "plunge")])
    assert got == {"1": ("switch", (3, 1)), "Left": ("switch", (1, 1)),
                   "a": ("switch", (1, 1)), "space": ("ball", "plunge")}


def test_a_press_in_the_game_window_is_the_matrix_key(m):
    """A press pulses, Shift latches, a ball key goes to the feeder, and
    anything else is ignored - exactly what the matrix window does."""
    calls = []
    fake = types.SimpleNamespace(
        _gk_actions=m.game_key_actions([(("Left",), "L", (1, 1)), (("1",), "S", (3, 1))],
                                       ball_keys=[(("d",), "Drain", "drain")]),
        _gk_ready=False,
        feeder=types.SimpleNamespace(drain=lambda: calls.append("drain")),
        pulse=lambda k: calls.append(("pulse", k)),
        toggle=lambda k: calls.append(("toggle", k)),
        _keys_log=lambda msg: None)
    for line in ("ready :1 3", "press Left 0", "press 1 1", "press d 0",
                 "press Up 0", "garbage", ""):
        m.MatrixUI._game_key_line(fake, line)
    assert fake._gk_ready is True
    assert calls == [("pulse", (1, 1)), ("toggle", (3, 1)), "drain"]
