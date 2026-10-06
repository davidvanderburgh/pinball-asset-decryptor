"""PAD-406: a card an earlier Write gave a color profile keeps it.

Its drawing shaders already carry ``pad_cp``, so a later build from that card
(a Write, or an Emulate run with "Show it through the machine's screen")
leaves them alone.  The log used to blame space ("the corrected shaders
don't fit") for that; it now says the card already carries a profile and
draws with it, so a user emulating a written card knows the Machine screen
was not added."""

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.core import colour_profile as cp      # noqa: E402
from pinball_decryptor.plugins.stern import engine            # noqa: E402
from pinball_decryptor.plugins.stern import shader_profile as sp  # noqa: E402
from tests.test_stern_shader_profile import SPRITE            # noqa: E402
from tests.test_stern_text_grow import (                      # noqa: E402
    DATA_OFF, FW_PATH, _capture, _grow_elf)

PROF = dict(cp.PRESETS)["recommended"]


def _with_shader(text):
    raw, _offs = _grow_elf()
    buf = bytearray(raw)
    at = DATA_OFF + 0x400
    blob = text.encode() + b"\x00"
    assert not any(buf[at:at + len(blob)])
    buf[at:at + len(blob)] = blob
    return bytes(buf)


def _build(tmp_path, raw, shader):
    staged = tmp_path / "game_real"
    staged.write_bytes(raw)
    msgs, log = _capture()
    engine._program_text_writes(
        None, {"i_block": b"\x01" * 60, "size": len(raw)}, FW_PATH, [],
        str(staged), log, grow={"ok": True, "why": "", "dir": str(tmp_path)},
        shader=shader)
    return [m for _lvl, m in msgs if m.startswith("Color profile")]


def test_a_built_cards_profile_is_named_not_blamed_on_space(tmp_path):
    raw = _with_shader(sp.patch_source(SPRITE, PROF))
    screen = cp.Profile(name="screen", gamma=(1.3, 1.3, 1.3))
    lines = _build(tmp_path, raw, sp.Shown(None, screen))
    assert len(lines) == 1
    assert "already carries the color profile an earlier Write gave it " \
           "(Recommended)" in lines[0]
    assert "through the Machine screen screen" in lines[0]
    assert "don't fit" not in lines[0]


def test_a_stock_card_is_not_called_built(tmp_path):
    lines = _build(tmp_path, _with_shader(SPRITE), PROF)
    assert len(lines) == 1 and "already carries" not in lines[0]
