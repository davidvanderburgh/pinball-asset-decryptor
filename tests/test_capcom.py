"""Capcom (PAD-1087): the six titles in the PinMAME classic plugin.

Synthetic zips carrying the ROM names libpinmame asks for when it loads
each romset; the real capture (Big Bang Bar from ``bbb109.zip``) was
run in libpinmame for the ticket.
"""

import wave
import zipfile

import pytest

from pinball_decryptor.plugins.pinmame_classic import capture
from pinball_decryptor.plugins.pinmame_classic.capcom import (CAPCOM_GAME_DB,
                                                               pick_romset)

SHARED = ["u24_v11.bin"]          # the sound CPU, the same on every title


def _zip(path, names):
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, b"\x00" * 64)
    return str(path)


ALL_ROMSETS = [(key, romset) for key, info in CAPCOM_GAME_DB.items()
               for romset in info["romsets"]]


def test_capcom_registered_with_basic_and_capture(manufacturers_by_key):
    cap = manufacturers_by_key["capcom"]
    assert cap.display == "Capcom"
    # Basic = every sound out of the sound ROMs (PAD-1088), and the capture
    assert cap.capabilities.capture and cap.capabilities.extract
    assert {g.display for g in cap.games} == {
        "Pinball Magic", "Airborne", "Breakshot", "Flipper Football",
        "Kingpin", "Big Bang Bar"}
    assert all(g.manufacturer_key == "capcom" for g in cap.games)


def test_every_libpinmame_capcom_romset_is_catalogued():
    # libpinmame 3.6's PinmameGetGames, manufacturer Capcom
    assert sorted(r for _, r in ALL_ROMSETS) == sorted(
        "abv105 abv106 abv106r bbb108 bbb109 bsb105 bsv100r bsv102 "
        "bsv102r bsv103 ffv101 ffv103 ffv104 kpb105 pmv112 pmv112r".split())


@pytest.mark.parametrize("key,romset", ALL_ROMSETS)
def test_detect_and_pick_by_name(manufacturers_by_key, tmp_path, key, romset):
    info = CAPCOM_GAME_DB[key]
    z = _zip(tmp_path / f"{romset}.zip", info["romsets"][romset] + SHARED)
    game = manufacturers_by_key["capcom"].detect(z)
    assert game is not None and game.key == key
    assert pick_romset(z, info) == romset


@pytest.mark.parametrize("key,romset", ALL_ROMSETS)
def test_renamed_zip_reads_its_version(manufacturers_by_key, tmp_path,
                                       key, romset):
    """A zip named anything is matched and run as the version inside."""
    info = CAPCOM_GAME_DB[key]
    z = _zip(tmp_path / "my capcom game.zip",
             info["romsets"][romset] + SHARED)
    game = manufacturers_by_key["capcom"].detect(z)
    assert game is not None and game.key == key
    assert pick_romset(z, info) == romset


def test_flipper_football_103_and_104_share_u1(tmp_path):
    info = CAPCOM_GAME_DB["flipper_football"]
    u1 = ["u1l_v104.bin", "u1h_v104.bin"]
    z103 = _zip(tmp_path / "a.zip", u1 + ["u3l_v103.bin", "u3h_v103.bin"])
    z104 = _zip(tmp_path / "b.zip", u1 + ["u3l_v104.bin", "u3h_v104.bin"])
    assert pick_romset(z103, info) == "ffv103"
    assert pick_romset(z104, info) == "ffv104"


def test_only_shared_roms_runs_as_parent(tmp_path):
    z = _zip(tmp_path / "x.zip", SHARED)
    assert pick_romset(z, CAPCOM_GAME_DB["big_bang_bar"]) == "bbb109"


def test_not_claimed_across_brands(manufacturers_by_key, tmp_path):
    cap = manufacturers_by_key["capcom"]
    bbb = _zip(tmp_path / "bbb109.zip",
               CAPCOM_GAME_DB["big_bang_bar"]["romsets"]["bbb109"] + SHARED)
    assert manufacturers_by_key["data_east"].detect(bbb) is None
    assert manufacturers_by_key["sega"].detect(bbb) is None
    # "bbb" also starts an unrelated romset: whole names only
    assert cap.detect(_zip(tmp_path / "bbbowlin.zip", ["x.bin"])) is None
    assert cap.detect(_zip(tmp_path / "random.zip", ["x.bin"])) is None
    # a Data East romset is not Capcom's
    from pinball_decryptor.plugins.pinmame_classic.games import GAME_DB
    lw3 = GAME_DB["lethal_weapon_3"]
    z = _zip(tmp_path / "lw3_208.zip", lw3["game_roms"] + lw3["sound_roms"])
    assert cap.detect(z) is None


def test_capture_pipeline_runs_the_romset_inside(manufacturers_by_key,
                                                 tmp_path):
    info = CAPCOM_GAME_DB["big_bang_bar"]
    z = _zip(tmp_path / "Big Bang Bar.zip", info["romsets"]["bbb108"] + SHARED)
    pipe = manufacturers_by_key["capcom"].make_capture_pipeline(
        z, str(tmp_path), lambda *a, **k: None, lambda *a: None,
        lambda *a, **k: None, lambda *a: None, duration_seconds=30)
    assert isinstance(pipe, capture.CapcomCapturePipeline)
    assert pipe.simulate_gameplay is False
    key, got, rom_zip, rom_name = pipe._resolve()
    assert (key, rom_zip, rom_name) == ("big_bang_bar", z, "bbb108")


# --------------------------------------------- clip audio (all PinMAME)

class _F:
    def __init__(self, ms):
        self.timestamp_ms = ms


class _R:
    audio_sample_rate = 48000
    audio_channels = 1
    audio_pcm = b"\x01\x00" * 48000          # one second of audio


@pytest.mark.parametrize("start_ms", [500, 5000])
def test_clip_audio_covers_every_frame(tmp_path, start_ms):
    """A clip's WAV lasts as long as its frames, also past the end of the
    captured audio: the MP4 is cut to the shorter stream, so a short WAV
    left a clip with no picture (the last clip of a Big Bang Bar run)."""
    from pinball_decryptor.plugins.williams.capture_pipeline import (
        CapturePipeline)
    clip = [_F(start_ms + i * 1000 / 60) for i in range(41)]
    wav = tmp_path / "c.wav"
    CapturePipeline._slice_audio_to_wav(None, _R(), clip, str(wav))
    with wave.open(str(wav)) as w:
        secs = w.getnframes() / w.getframerate()
    assert secs >= 41 / 60 - 1e-3


# ------------------------------------- staging the zip for PinMAME (all)

def test_staging_replaces_a_different_newer_copy(tmp_path, monkeypatch):
    """The staged <romset>.zip is re-copied whenever it is not this file's
    copy: a different zip staged under the same name and NEWER than the one
    picked used to be run in its place (PinMAME: every ROM NOT FOUND)."""
    import os
    from pinball_decryptor.plugins.williams import pinmame_capture as pc
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "home"))
    real = _zip(tmp_path / "bbb109.zip", ["u1l_b19.bin"])
    os.utime(real, (1_500_000_000, 1_500_000_000))        # an old file
    base = pc._ensure_vpm_dir(real, "bbb109")
    staged = os.path.join(base, "roms", "bbb109.zip")
    with open(staged, "wb") as f:                          # a newer stand-in
        f.write(b"stub")
    pc._ensure_vpm_dir(real, "bbb109")
    assert open(staged, "rb").read() == open(real, "rb").read()
    # this file's own copy is left as it is
    before = os.stat(staged).st_mtime_ns
    pc._ensure_vpm_dir(real, "bbb109")
    assert os.stat(staged).st_mtime_ns == before
