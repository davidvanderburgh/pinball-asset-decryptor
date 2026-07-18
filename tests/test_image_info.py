"""Tests for the Image Info collector (core.image_info) and the Stern Spike 2
card probe behind it (plugins.stern.info) — the read-only "Image Info" tab
(peanuts).  All fixtures are tiny synthetic files; the Spike 2 probe runs over
the same in-memory fake ext4 the Partition Explorer tests use."""

import os
import struct

import pytest

from pinball_decryptor.core import image_info
from pinball_decryptor.core.registry import Game


def _section(sections, title):
    for name, rows in sections:
        if name == title:
            return dict(rows)
    return None


class _FakeMfr:
    display = "FakeCo"

    def __init__(self, claims=True, extra=()):
        self._claims = claims
        self._extra = list(extra)

    def detect(self, path):
        if not self._claims:
            return None
        return Game(key="g", display="Some Game", manufacturer_key="fake",
                    notes="Fake image")

    def image_info(self, path, assets_dir=None):
        return self._extra


# ---------------------------------------------------------------------------
# core.image_info
# ---------------------------------------------------------------------------

def test_human_size_steps():
    assert image_info.human_size(512) == "512 B"
    assert image_info.human_size(1536) == "1.5 KB"
    assert image_info.human_size(8 * 1024 * 1024 * 1024) == "8.0 GB"
    assert image_info.human_size(None) == "?"


def test_collect_file_and_detection(tmp_path):
    img = tmp_path / "game.img"
    img.write_bytes(b"\x00" * 100)
    sections = image_info.collect(
        _FakeMfr(extra=[("Firmware", [("Version", "1.2.3")])]), str(img))
    f = _section(sections, "File")
    assert f["Name"] == "game.img" and "100 bytes" in f["Size"]
    d = _section(sections, "Detection")
    assert d["Manufacturer"] == "FakeCo" and d["Game"] == "Some Game"
    assert d["Format"] == "Fake image"
    # The plugin's own sections are appended after the generic ones.
    assert _section(sections, "Firmware")["Version"] == "1.2.3"


def test_collect_unclaimed_file_skips_platform_details(tmp_path):
    img = tmp_path / "other.bin"
    img.write_bytes(b"\x00")
    sections = image_info.collect(
        _FakeMfr(claims=False, extra=[("Firmware", [("Version", "9")])]),
        str(img))
    d = _section(sections, "Detection")
    assert "Not recognized" in d["Detected"]
    # A foreign image must not get the plugin's Firmware section.
    assert _section(sections, "Firmware") is None


def test_collect_missing_file_reports_not_crashes(tmp_path):
    sections = image_info.collect(_FakeMfr(), str(tmp_path / "nope.img"))
    assert "Error" in _section(sections, "File")


def test_collect_passes_assets_dir_to_plugin_hook_only(tmp_path):
    """assets_dir feeds the plugin hook (BOF's update-version date needs it)
    but produces no section of its own — the old "Extracted Assets" counts
    described whatever folder lingered in the pickers, not the selected
    image, so they were dropped (David)."""
    img = tmp_path / "game.img"
    img.write_bytes(b"\x00")
    assets = tmp_path / "out"
    (assets / "audio").mkdir(parents=True)
    (assets / "audio" / "idx0001.wav").write_bytes(b"RIFF")

    seen = {}

    class _Mfr(_FakeMfr):
        def image_info(self, path, assets_dir=None):
            seen["assets_dir"] = assets_dir
            return []

    sections = image_info.collect(_Mfr(), str(img), assets_dir=str(assets))
    assert seen["assets_dir"] == str(assets)
    assert _section(sections, "Extracted Assets") is None


def test_as_text_report(tmp_path):
    img = tmp_path / "game.img"
    img.write_bytes(b"\x00" * 10)
    text = image_info.as_text(image_info.collect(_FakeMfr(), str(img)))
    assert text.startswith("Image Info\n==========")
    assert "Detection" in text and "Manufacturer" in text and "FakeCo" in text


# ---------------------------------------------------------------------------
# plugins.stern.info — the Spike 2 card probe
# ---------------------------------------------------------------------------

from pinball_decryptor.plugins.stern.info import (card_info,
                                                  version_from_filename)


@pytest.mark.parametrize("name,expected", [
    ("munsters_le-1_27_0.Release.8G.sdcard.raw", ("1.27.0", "LE")),
    ("tmnt_pro-1_53.Release.8G.sdcard.raw", ("1.53", "Pro")),
    ("godzilla_prem-0_87_0.Release.16G.sdcard.raw", ("0.87.0", "Premium")),
    ("jurassic_park-2_02_0.Release.8G.sdcard.raw", ("2.02.0", None)),
    ("my_backup_card.raw", (None, None)),          # renamed: nothing to parse
    ("card-final.raw", (None, None)),              # dash but not a version
])
def test_version_from_filename(name, expected):
    assert version_from_filename("D:\\cards\\" + name) == expected


def _make_sidx(paths, tag=b"FI64", payload_len=80):
    """Minimal valid .sidx: 0x38 header, STRS path block, one record/path."""
    blob = bytearray(0x38)
    struct.pack_into("<I", blob, 0x34, 0x12345678)
    strs = b"".join(p.encode() + b"\x00" for p in paths)
    blob += b"STRS" + struct.pack("<I", len(strs)) + strs
    for _ in paths:
        blob += tag + struct.pack("<I", payload_len) + b"\x00" * payload_len
    return bytes(blob)


# A sniffable fake MP4: size >= 0x1000 with "ftyp" at offset 4, the same
# signature engine.extract_videos keys on (Spike 2 videos are extensionless
# .asset files, so the probe counts by magic, not name).
_FAKE_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 0x1000

SIDX_TREE = {
    "spk": {"index": {"turtles.sidx": _make_sidx(
        ["turtles_pro/image.bin", "turtles_pro/game/scenes.pack"])}},
    "turtles_pro": {
        "image.bin": b"\x01" * 2048,
        "game": {"assets": {
            "0a1b2c": {"scene.radium": b"RAD",
                       "scene.assets": {"0.asset": _FAKE_MP4}},
            "logo.png": b"png!",
            "score.png": b"png!",
        }},
    },
}


def test_card_info_probe(tmp_path, monkeypatch):
    from tests._ext4_fake import install_fake_reader, write_fake_card
    install_fake_reader(monkeypatch, spec=SIDX_TREE)
    img = write_fake_card(tmp_path / "turtles_le-1_23_0.Release.8G.sdcard.raw")

    sections = dict(card_info(img))
    fw = dict(sections["Firmware"])
    assert fw["System"] == "Stern Spike 2"
    assert fw["Version"].startswith("1.23.0")
    assert fw["Edition"] == "LE"
    assert fw["Game folder"] == "turtles_pro"
    assert fw["Validated files"] == "2 (FI64 manifest)"
    assert "image.bin — 2.0 KB (2,048 bytes)" == fw["Asset container"]
    # On-card counts, no Extract needed: the ftyp-sniffed .asset video, the
    # loose PNGs, the scene.radium — and an honest note for the packed sounds.
    assets = dict(sections["Assets on Card"])
    assert assets["Videos"] == "1" and assets["Images"] == "2"
    assert assets["Scenes"] == "1"
    assert "image.bin" in assets["Sounds"]
    parts = dict(sections["Partitions"])
    assert len(parts) == 4 and "FAT (boot)" in parts["Partition 0"]
    assert dict(sections["Sound System"])["Sample rate"] == "44,100 Hz"


def test_card_info_unopenable_image_degrades(tmp_path):
    img = tmp_path / "not_a_card.raw"
    img.write_bytes(b"junk")
    sections = dict(card_info(str(img)))
    rows = dict(sections["Firmware"])
    # No partitions/sidx, but the section still renders with an explanation.
    assert rows["System"] == "Stern Spike 2"
