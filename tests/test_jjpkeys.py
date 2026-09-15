"""tools/jjp_emu/jjpkeys.py - the matrix's keys, pressed in the game's window.

Pure: the keycode naming and the raw XEvent decode.  The grab itself needs an X
server and is proven on the rig."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "jjpkeys", os.path.join(HERE, "..", "tools", "jjp_emu", "jjpkeys.py"))
jjpkeys = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(jjpkeys)


def _event(etype, keycode, state=0):
    b = bytearray(jjpkeys.XEVENT_SIZE)
    b[0:4] = etype.to_bytes(4, "little")
    b[jjpkeys.STATE_OFF:jjpkeys.STATE_OFF + 4] = state.to_bytes(4, "little")
    b[jjpkeys.KEYCODE_OFF:jjpkeys.KEYCODE_OFF + 4] = keycode.to_bytes(4, "little")
    return bytes(b)


def test_one_physical_key_is_named_once():
    """'d' and 'D' are the same keycode; a keysym the server has no key for
    (keycode 0) is not grabbed at all."""
    got = jjpkeys.keycode_names([("d", 40), ("D", 40), ("Left", 113), ("nope", 0)])
    assert got == {40: "d", 113: "Left"}


def test_a_press_of_a_grabbed_key_is_a_line_with_its_modifiers():
    names = {113: "Left", 10: "1"}
    assert jjpkeys.press_line(_event(jjpkeys.KEY_PRESS, 113), names) == "press Left 0"
    assert jjpkeys.press_line(_event(jjpkeys.KEY_PRESS, 10, state=1), names) == "press 1 1"


def test_releases_and_other_keys_say_nothing():
    names = {113: "Left"}
    assert jjpkeys.press_line(_event(3, 113), names) is None          # KeyRelease
    assert jjpkeys.press_line(_event(jjpkeys.KEY_PRESS, 38), names) is None
