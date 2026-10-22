"""PAD-674: a game program whose sound key comes from the machine's CPU board.

The PAD-657 user sent in his Jurassic Park 1.13 game program.  Its boot
doesn't seed the sound keystream from constants as every released build in
the library does: a key builder asks the CPU board's bus master four
questions over the node bus (frame ``0d 05 <op> <4 bytes>``, the same
request PAD-603 met in Venom LE 0.95) and seeds from the answers.  Every
build's sound bank is keyed to its own program (JP LE 1.15 and 1.16 banks
differ from their first MiB), so nothing on the card can stand in for the
board.  The locator now says ``BOARD_KEY`` for such a program and the app
says why in plain words instead of asking for the program to be sent in.
"""
import io
import os
import struct

import pytest

pytest.importorskip("capstone")

from pinball_decryptor.plugins.stern import engine as E  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import locate as L  # noqa: E402
from pinball_decryptor.webui import i18n  # noqa: E402

JP = r"D:\Pinball\images\Stern\spike2\jurassic_park_le-1_16_0.Release.8G.sdcard.raw"


class _Fw:
    """Just enough of locate._FwView for the instruction scans."""

    def __init__(self, words, base=0x1000):
        self.raw = b"".join(struct.pack("<I", w) for w in words)
        self.secs = {".text": dict(off=0, addr=base, size=len(self.raw))}


def _asker(second=5):
    # push {r4,lr} ; mov r2,#0xd ; strb r2,[sp,#8] ; mov r2,#<second> ;
    # strb r2,[sp,#9] ; pop {r4,pc}   (JP 1.13's 0x46474c, cut down)
    return [0xE92D4010, 0xE3A0200D, 0xE5CD2008, 0xE3A02000 | second,
            0xE5CD2009, 0xE8BD8010]


def test_the_bus_master_question_is_recognised():
    assert L._asks_bus_master(_Fw(_asker()), 0x1000)


def test_another_frame_is_not():
    assert not L._asks_bus_master(_Fw(_asker(second=6)), 0x1000)


def test_a_register_overwritten_between_is_not():
    # mov r2,#0xd ; ldrb r2,[r0] ; strb r2,[sp,#8] ... : the stored byte isn't 0xd
    w = _asker()
    w[2:2] = [0xE5D02000]
    assert not L._asks_bus_master(_Fw(w), 0x1000)


@pytest.mark.parametrize("job", ["extract", "rebuild", "reset"])
def test_the_message_says_why_and_asks_for_nothing(job):
    msg = E._sounds_unread_why(["BOARD_KEY"], job)
    assert "CPU board" in msg and "BOARD_KEY" not in msg
    for stale in ("developer", "changed outside", "send"):
        assert stale not in msg
    for code in ("de", "es", "fr"):
        got = i18n.catalog(code).tr(msg)
        # every sentence translated, none left in English
        for sentence in ("The key isn't anywhere", "Later versions", "CPU board instead"):
            assert sentence not in got, (code, got)


def test_extract_does_not_keep_the_program_for_a_board_key(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    gr = work / "game_real"
    gr.write_bytes(b"\x7fELF" + bytes(60))

    def inputs(disk_f, parts, work_dir, log, read_progress=None):
        return str(gr), str(work / "image.bin"), object(), None, None

    monkeypatch.setattr(E, "_extract_inputs", inputs)
    monkeypatch.setattr(E, "_work_dir", lambda label=None: str(work))
    monkeypatch.setattr(EM, "audio_decode_supported", lambda p: False)
    monkeypatch.setattr(EM, "audio_decode_missing", lambda p: ["BOARD_KEY"])
    for fn in ("extract_videos", "extract_images", "extract_radium_text"):
        monkeypatch.setattr(E, fn, lambda *a, **k: None)
    lines = []
    out = tmp_path / "project"
    n = E.extract_all("card.raw", [], str(out), log=lambda m, lvl="info": lines.append((m, lvl)),
                      open_disk=lambda: io.BytesIO(), do_video=True,
                      do_images=False, do_text=False)
    assert n == 0
    warn = [m for m, lvl in lines if lvl == "warning" and "sounds can't be extracted" in m]
    assert len(warn) == 1, lines
    assert "CPU board" in warn[0] and "The video extracted normally." in warn[0]
    assert not (out / "firmware_game_real.bin").exists()


def test_a_released_build_is_not_board_keyed():
    if not os.path.isfile(JP):
        pytest.skip("Jurassic Park LE 1.16 card not present")
    with open(JP, "rb") as f:
        r, fw, _img = E._locate(f, E._linux_partitions(JP))
        raw = bytes(r.read_file_bytes(fw))
    assert not L._board_keyed(L._FwView(raw))
    assert L.missing(raw=raw) == []
