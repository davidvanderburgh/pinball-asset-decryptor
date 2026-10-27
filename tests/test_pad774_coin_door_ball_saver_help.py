"""A Home Edition given its coin door (PAD-755) also gets the game's own COIN
DOOR BALL SAVER (PAD-774): the help says so, in every language.

The proof is the emulator's: JP The Pin 1.05 with the door linked and the
setting on arms the game's ball save the moment the door opens mid-ball
(0x5c5574 goes to 0x138/0xbb, one save); with the setting off, or on the stock
build whose door is never read, nothing is armed.  The Home Editions' switch
table has no tilt pendulum or slam tilt, so COIN DOOR DISABLE TILT has nothing
to act on there.
"""
import pytest

from pinball_decryptor.webui import help_content, i18n
from pinball_decryptor.webui.tips_render import plain, render


def _coin_door_section():
    for sections in help_content.HELP_CONTENT.values():
        for sec in sections:
            if isinstance(sec, tuple) and sec[0] == "Coin door (Home Editions)":
                return sec[1]
    raise AssertionError("no Coin door (Home Editions) help section")


def _bullets():
    body = next(p for p in _coin_door_section() if isinstance(p, str)
                and "service buttons" in p)
    return body


def test_the_help_names_the_ball_saver_and_why_tilt_does_nothing():
    body = _bullets()
    assert "**COIN DOOR BALL SAVER**" in body
    assert "off as shipped" in body
    assert "**COIN DOOR DISABLE TILT**" in body and "no tilt switch" in body


@pytest.mark.parametrize("code", ["de", "es", "fr"])
def test_the_ball_saver_line_is_translated(code):
    tr = i18n.translator(code)
    english = plain(render(_bullets()))
    shown = plain(render(_bullets(), tr=tr))
    line = next(ln for ln in english.splitlines() if "BALL SAVER" in ln)
    assert line not in shown
    # the game's own setting names stay as the machine shows them
    assert "COIN DOOR BALL SAVER" in shown and "COIN DOOR DISABLE TILT" in shown
