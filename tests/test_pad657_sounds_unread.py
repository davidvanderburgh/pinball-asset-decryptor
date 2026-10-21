"""PAD-657: a card whose game program has no sound decoder the app can find.

A Pinside user's modded Jurassic Park 1.13 card extracted no sounds, with a
message about "a dual-path codec" and "the per-sound keystream" -- a theory
the codec work later showed was a misdiagnosis (docs/architecture/stern.md):
every Stern Spike 2 build in the library locates, older builds too.  So a
card that doesn't is a program nobody here has seen, and the message now says
that in plain words, names what the locator missed, keeps the game program
beside the extract for the developer, and only claims the kinds of file that
were actually extracted.

Pinned here: :func:`locate.missing` names what it couldn't find (a real game
program with its sound body provider changed, when the library is here); the
messages for extract / rebuild / reset and their translations; and the
Extract's early-out, end to end with the card read stood in for.
"""
import io
import os

import pytest

pytest.importorskip("capstone")

from pinball_decryptor.plugins.stern import engine as E  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import locate as L  # noqa: E402
from pinball_decryptor.webui import i18n  # noqa: E402

JP = r"D:\Pinball\images\Stern\spike2\jurassic_park_le-1_16_0.Release.8G.sdcard.raw"


def test_not_a_game_program_says_so(tmp_path):
    gone = L.missing(raw=b"not an elf at all")
    assert len(gone) == 1 and gone[0].startswith("ELF: ")
    assert L.locate_all(raw=b"not an elf at all") is None
    p = tmp_path / "game_real"
    p.write_bytes(b"\x7fELF" + bytes(60))
    assert EM.audio_decode_missing(str(p))
    assert not EM.audio_decode_supported(str(p))
    assert EM.audio_decode_missing(str(tmp_path / "nope"))[0].startswith("unreadable: ")


def _jp_program():
    if not os.path.isfile(JP):
        pytest.skip("Jurassic Park LE 1.16 card not present")
    with open(JP, "rb") as f:
        r, fw, _img = E._locate(f, E._linux_partitions(JP))
        return bytes(r.read_file_bytes(fw))


def _changed(raw):
    """*raw* with its sound body provider's first two words made NOPs."""
    raw = bytearray(raw)
    fw = L._FwView(bytes(raw))
    prov = L.locate_all(raw=bytes(raw))["PROV"]
    seg = next(s for s in fw.segs if s["vaddr"] <= prov < s["vaddr"] + s["filesz"])
    off = seg["off"] + prov - seg["vaddr"]
    raw[off:off + 8] = b"\x00\x00\xa0\xe1" * 2
    return bytes(raw)


def test_a_real_program_changed_outside_the_app_names_what_is_missing():
    raw = _jp_program()
    assert L.missing(raw=raw) == []
    assert L.locate_all(raw=raw) is not None
    assert L.missing(raw=_changed(raw)) == ["PROV", "QMUL_TABLE"]
    assert L.locate_all(raw=_changed(raw)) is None


@pytest.mark.parametrize("job", ["extract", "rebuild", "reset"])
def test_the_message_is_plain_and_translates(job):
    msg = E._sounds_unread_why(["PROV", "QMUL_TABLE"], job)
    assert "PROV, QMUL_TABLE not found" in msg
    for stale in ("dual-path", "keystream", "codec"):
        assert stale not in msg
    for code in ("de", "es", "fr"):
        got = i18n.catalog(code).tr(msg)
        assert got != msg and "PROV, QMUL_TABLE" in got, (code, got)


def test_the_old_wording_is_gone_from_the_catalogs():
    for code in ("de", "es", "fr"):
        with open(os.path.join(i18n.CATALOG_DIR, code + ".json"), encoding="utf-8") as f:
            assert "dual-path" not in f.read()


@pytest.mark.parametrize("kinds, says", [
    ((False, False, False), None),
    ((True, False, False), "The video extracted normally."),
    ((True, True, True), "The video, images and text extracted normally."),
])
def test_extract_keeps_the_program_and_names_only_what_it_extracted(
        monkeypatch, tmp_path, kinds, says):
    work = tmp_path / "work"
    work.mkdir()
    gr = work / "game_real"
    program = b"\x7fELF" + bytes(60) + b"changed"
    gr.write_bytes(program)

    def inputs(disk_f, parts, work_dir, log, read_progress=None):
        return str(gr), str(work / "image.bin"), object(), None, None

    monkeypatch.setattr(E, "_extract_inputs", inputs)
    monkeypatch.setattr(E, "_work_dir", lambda label=None: str(work))
    for fn in ("extract_videos", "extract_images", "extract_radium_text"):
        monkeypatch.setattr(E, fn, lambda *a, **k: None)
    monkeypatch.setattr(E, "extract_radium_images", lambda *a, **k: None, raising=False)
    lines = []
    out = tmp_path / "project"
    do_video, do_images, do_text = kinds
    n = E.extract_all("card.raw", [], str(out), log=lambda m, lvl="info": lines.append((m, lvl)),
                      open_disk=lambda: io.BytesIO(), do_video=do_video,
                      do_images=do_images, do_text=do_text)
    assert n == 0
    warn = [m for m, lvl in lines if lvl == "warning" and "sounds can't be extracted" in m]
    assert len(warn) == 1, lines
    msg = warn[0]
    assert "not found" in msg and "dual-path" not in msg
    saved = out / "firmware_game_real.bin"
    assert saved.read_bytes() == program        # the work dir itself is gone
    assert str(saved) in msg
    if says is None:
        assert "extracted normally" not in msg
    else:
        assert says in msg
