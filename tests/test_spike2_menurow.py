"""menurow.py: a frame of the game's Guided Setup / operator menu, and whether its last row is selected."""

import pathlib
import struct
import sys
import zlib

import pytest

RIG = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu"
sys.path.insert(0, str(RIG))
import menurow  # noqa: E402

W, H = 400, 300
DARK, WHITE, RED, SKY = (20, 20, 22), (240, 240, 240), (235, 30, 30), (40, 90, 200)


def _png(path, pixel):
    raw = b"".join(b"\x00" + bytes(c for x in range(W) for c in pixel(x, y)) for y in range(H))
    chunk = lambda tag, body: struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return str(path)


def _menu(tmp_path, red_row):
    """Six rows of 'text' down the left third, 30 px tall, 2 px apart; row `red_row` red."""
    def pixel(x, y):
        k, dy = divmod(y - 70, 32)
        if 0 <= k < 6 and dy < 30 and 10 <= x < 110:
            return RED if k == red_row else WHITE
        return DARK
    return _png(tmp_path / ("menu%d.png" % red_row), pixel)


@pytest.mark.parametrize("red_row, want", [(5, "menu last=yes"), (0, "menu last=no"), (3, "menu last=no")])
def test_a_menu_frame_says_whether_its_last_row_is_selected(tmp_path, capsys, red_row, want):
    assert menurow.main.__module__ == "menurow"
    sys.argv = ["menurow.py", _menu(tmp_path, red_row)]
    assert menurow.main() == 0 and capsys.readouterr().out.strip() == want


def test_a_bright_frame_is_not_a_menu(tmp_path, capsys):
    sys.argv = ["menurow.py", _png(tmp_path / "sky.png", lambda x, y: SKY if y < 200 else RED)]
    assert menurow.main() == 1 and capsys.readouterr().out.strip() == "none"


def test_a_dark_frame_with_no_red_row_is_not_a_menu(tmp_path):
    assert menurow.classify(_menu(tmp_path, 9)) is None
