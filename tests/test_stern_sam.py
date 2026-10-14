"""Stern S.A.M. era (PAD-577): matching a SAM code update by checksum,
staging it for PinMAME, and the Stern card's "sam" era surface.

Real SAM .bins are 5-120 MB, so the matching tests plant a small fake
romset in the lookup tables; the catalogue test checks the real table.
The capture itself (libpinmame) was proven on Mustang 1.45 by hand.
"""

import os
import zipfile
import zlib

import pytest

from pinball_decryptor.core.pipeline_base import PipelineError
from pinball_decryptor.plugins.pinmame_classic import capture, sam
from pinball_decryptor.plugins.pinmame_classic.sam_games import SAM_GAME_DB

PAYLOAD = bytes(range(256)) * 64          # 16 KB stand-in for a SAM .bin


@pytest.fixture
def fake_mustang(monkeypatch):
    """Mustang gets a romset 'mt_999h' whose .bin is PAYLOAD."""
    crc = zlib.crc32(PAYLOAD) & 0xFFFFFFFF
    db = {k: dict(v) for k, v in SAM_GAME_DB.items()}
    db["mustang"]["romsets"] = dict(
        db["mustang"]["romsets"],
        mt_999h=("mt_999h.bin", crc, len(PAYLOAD),
                 "Mustang Limited Edition (V9.99)"))
    monkeypatch.setattr(sam, "SAM_GAME_DB", db)
    monkeypatch.setitem(sam._BY_CRC, (crc, len(PAYLOAD)),
                        ("mustang", "mt_999h"))
    monkeypatch.setitem(sam._BY_SIZE, len(PAYLOAD), {("mustang", "mt_999h")})
    monkeypatch.setattr(sam, "MIN_BIN_SIZE", 1)
    return crc


@pytest.fixture(autouse=True)
def _reset_stern_era(manufacturers_by_key):
    yield
    manufacturers_by_key["stern"].set_era("")


def _zip(path, name, data):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, data)
        zf.writestr("README.TXT", b"Stern release notes")
    return str(path)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

def test_catalogue_covers_the_sam_titles():
    names = {v["display"] for v in SAM_GAME_DB.values()}
    for title in ("Mustang", "Metallica", "TRON: Legacy", "AC/DC",
                  "The Walking Dead", "Star Trek", "World Poker Tour"):
        assert title in names
    mt = SAM_GAME_DB["mustang"]["romsets"]["mt_145h"]
    assert mt[:3] == ("mt_145h.bin", 0x20EC78B3, 63098052)
    assert mt[3] == "Mustang Limited Edition (V1.45)"
    for info in SAM_GAME_DB.values():
        for fn, _crc, size, title in info["romsets"].values():
            assert fn.lower().endswith(sam.EXTENSIONS)
            assert sam.MIN_BIN_SIZE <= size <= sam.MAX_BIN_SIZE
            assert ", The" not in title and "(Stern)" not in title


# ---------------------------------------------------------------------------
# identify()
# ---------------------------------------------------------------------------

def test_identify_by_checksum_whatever_the_names(tmp_path, fake_mustang):
    # Stern's download zip: its own file name, a readme beside it.
    z = _zip(tmp_path / "Mustang_LE_update.zip", "MT999LE.BIN", PAYLOAD)
    m = sam.identify(z)
    assert (m.key, m.romset, m.member, m.exact) == \
        ("mustang", "mt_999h", "MT999LE.BIN", True)
    # The bare .bin off the USB stick, renamed.
    b = tmp_path / "my mustang.bin"
    b.write_bytes(PAYLOAD)
    m = sam.identify(str(b))
    assert (m.key, m.romset, m.member, m.exact) == \
        ("mustang", "mt_999h", "", True)


def test_identify_unknown_version_same_size_borrows_romset(tmp_path,
                                                           fake_mustang):
    patched = b"\x01" + PAYLOAD[1:]
    m = sam.identify(_zip(tmp_path / "mt_999h.zip", "mt_999h.bin", patched))
    assert m.key == "mustang" and m.romset == "mt_999h"
    assert not m.exact and m.runnable


def test_same_size_prefers_the_newest_version(monkeypatch):
    # mt_140h, mt_145h and the mt_145hb "Boss" romset are one size; an
    # unlisted Mustang that size runs as plain 1.45, unless named for one.
    size = SAM_GAME_DB["mustang"]["romsets"]["mt_145h"][2]
    same = sorted(rs for k, rs in sam._BY_SIZE[size] if k == "mustang")
    assert {"mt_140h", "mt_145h", "mt_145hb"} <= set(same)
    assert sam._match(0, size, "mt_150h.bin", "").romset == "mt_145h"
    assert sam._match(0, size, "mt_140h.bin", "").romset == "mt_140h"


def test_identify_unknown_size_names_title_but_cannot_run(tmp_path,
                                                         fake_mustang):
    m = sam.identify(_zip(tmp_path / "x.zip", "mt_150h.bin", PAYLOAD + b"x"))
    assert m.key == "mustang" and not m.runnable


def test_identify_ignores_other_files(tmp_path, fake_mustang):
    # A family prefix isn't enough on its own: "mtl" is Metallica, not "mt".
    assert sam.identify(_zip(tmp_path / "a.zip", "mtl_1.bin",
                             PAYLOAD + b"x")).key == "metallica"
    assert sam.identify(_zip(tmp_path / "b.zip", "game.bin",
                             PAYLOAD + b"x")) is None
    other = tmp_path / "notes.bin"
    other.write_bytes(b"\x00" * 100)
    assert sam.identify(str(other)) is None


def test_identify_skips_big_and_small_bins(tmp_path, monkeypatch):
    # Real limits: a Spike card image named .bin is never read; a classic
    # romset's small .bin chip never counts.
    big = tmp_path / "mt_145h.bin"
    with open(big, "wb") as f:
        f.truncate(sam.MAX_BIN_SIZE + 1)
    assert sam.identify(str(big)) is None
    assert sam.identify(_zip(tmp_path / "mt_145h.zip", "mt_145h.bin",
                             b"\x00" * 1024)) is None


# ---------------------------------------------------------------------------
# stage() + the capture pipeline's resolve step
# ---------------------------------------------------------------------------

def test_stage_names_the_file_for_pinmame(tmp_path, fake_mustang):
    for src in (_zip(tmp_path / "dl.zip", "MT999LE.BIN", PAYLOAD),
                str(tmp_path / "loose.bin")):
        if src.endswith(".bin"):
            open(src, "wb").write(PAYLOAD)
        out = sam.stage(src, sam.identify(src), str(tmp_path / "stage"))
        assert os.path.basename(out) == "mt_999h.zip"
        with zipfile.ZipFile(out) as zf:
            assert zf.namelist() == ["mt_999h.bin"]
            assert zf.read("mt_999h.bin") == PAYLOAD


def _pipe(path, tmp_path):
    return capture.SamCapturePipeline(
        path, str(tmp_path / "out"), lambda *a, **k: None, lambda *a: None,
        lambda *a, **k: None, lambda *a: None)


def test_resolve_stages_and_cleans_up(tmp_path, fake_mustang):
    p = _pipe(_zip(tmp_path / "dl.zip", "MT999LE.BIN", PAYLOAD), tmp_path)
    p._stage_dir = None
    key, info, rom_zip, rom_name = p._resolve()
    assert (key, rom_name) == ("mustang", "mt_999h")
    assert info["display"] == "Mustang"
    assert os.path.isfile(rom_zip)
    # outside the game's output folder, which gets checksummed
    assert not rom_zip.startswith(str(tmp_path / "out"))
    import shutil
    shutil.rmtree(p._stage_dir)


def test_resolve_refuses_a_version_pinmame_lacks(tmp_path, fake_mustang):
    p = _pipe(_zip(tmp_path / "x.zip", "mt_150h.bin", PAYLOAD + b"x"),
              tmp_path)
    p._stage_dir = None
    with pytest.raises(PipelineError) as e:
        p._resolve()
    assert "Mustang Limited Edition (V1.45)" in str(e.value)


# ---------------------------------------------------------------------------
# The Stern card's SAM era
# ---------------------------------------------------------------------------

def test_stern_lists_sam_era_and_games(manufacturers_by_key):
    s = manufacturers_by_key["stern"]
    assert ("sam", "SAM") in [e[:2] for e in s.eras]
    sam_games = [g for g in s.games if g.era == "sam"]
    assert len(sam_games) == len(SAM_GAME_DB)


def test_stern_detects_sam_and_switches_surface(manufacturers_by_key,
                                                tmp_path, fake_mustang):
    s = manufacturers_by_key["stern"]
    z = _zip(tmp_path / "Mustang_LE_update.zip", "MT999LE.BIN", PAYLOAD)
    g = s.detect(z)
    assert (g.key, g.era) == ("mustang", "sam")
    s.set_era(g.era)
    assert s.current_era == "sam"
    # capture of the DMD animations, plus (PAD-582) the sounds and
    # (PAD-584) the animation frames read and written straight from the
    # code update
    assert s.capabilities.capture and s.capabilities.write
    assert s.capabilities.replace_image
    assert s.extract_input_label == "Game file"
    assert s.extract_phases == ("Detect", "Decode audio",
                                "Decode animations", "Checksums")
    assert s.title_caption(z, g) == "Mustang Limited Edition (V9.99)"
    odd = _zip(tmp_path / "mt_998h.zip", "mt_998h.bin", b"\x01" + PAYLOAD[1:])
    assert s.title_caption(odd, s.detect(odd)) == \
        "Mustang, a version PinMAME doesn't have"
    pipe = s.make_capture_pipeline(
        z, str(tmp_path), lambda *a, **k: None, lambda *a: None,
        lambda *a, **k: None, lambda *a: None, duration_seconds=30)
    assert isinstance(pipe, capture.SamCapturePipeline)
    assert pipe.simulate_gameplay is False


def test_stern_whitestar_zip_still_whitestar(manufacturers_by_key, tmp_path):
    from pinball_decryptor.plugins.pinmame_classic.games import GAME_DB
    info = GAME_DB["monopoly"]
    z = tmp_path / "monopoly.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in info["game_roms"] + info["dmd_roms"] + info["sound_roms"]:
            zf.writestr(n, b"\x00" * 256)
    assert manufacturers_by_key["stern"].detect(str(z)).era == "whitestar"


def test_card_probes_leave_sam_files_alone(manufacturers_by_key, tmp_path,
                                           fake_mustang):
    s = manufacturers_by_key["stern"]
    b = tmp_path / "MT999LE.bin"
    b.write_bytes(PAYLOAD)
    rows = dict(s.image_info(str(b))[0][1])
    assert rows["System"] == "Stern S.A.M."
    assert rows["Version"] == "Mustang Limited Edition (V9.99)"
    assert rows["PinMAME romset"] == "mt_999h"
    assert s.card_version(str(b)) == (None, False)
    assert s.stock_check(str(b)) is None
    assert s.source_note(str(b)) == ""
    assert s.video_quality(str(b)) == []
    assert "SAM game files" in s.compare_images(str(b), str(b))[0][1][0][1]
