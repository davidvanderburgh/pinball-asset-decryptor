"""
Tests for the Stern Spike 3 image.bin sound decoder (tools/image_sound.py).

Self-contained: they build a synthetic image.bin container in a temp dir and
need no hardware and no Stern data. The parser, the master-directory invariant,
mono/stereo detection and the WAV round-trip are all exercised.

If the environment variable SPIKE3_IMAGE_BIN points at a real extracted
image.bin, an extra test decodes its first sounds and checks the WAV headers.

Run from this folder:  pytest
(The repo's main suite uses testpaths=tests, so it does not pick these up.)
"""
import os
import struct
import sys
import wave

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import image_sound  # noqa: E402


def test_selftest_cli():
    # The tool's own round-trip self-test must pass.
    assert image_sound.main(["selftest"]) == 0


def _build(tmp_path):
    cpath = os.path.join(str(tmp_path), "image.bin")
    image_sound._synth_container(cpath)
    return cpath


def test_parse_and_geometry(tmp_path):
    img = image_sound.ImageSound(_build(tmp_path))
    assert img.count == 2
    # record 0 is mono/100 frames, record 1 stereo/50 frames
    assert img.records[0].channels == 1
    assert img.records[0].frames == 100
    assert img.records[0].body_bytes == 100 * 1 * 2
    assert img.records[1].channels == 2
    assert img.records[1].frames == 50
    assert img.records[1].body_bytes == 50 * 2 * 2
    img.validate()  # must not raise


def test_invariant_is_enforced(tmp_path):
    cpath = _build(tmp_path)
    # Corrupt the record count so the invariant no longer holds.
    data = bytearray(open(cpath, "rb").read())
    struct.pack_into("<I", data, image_sound.COUNT_FIELD, 9999)
    bad = os.path.join(str(tmp_path), "bad.bin")
    open(bad, "wb").write(data)
    with pytest.raises(ValueError):
        image_sound.ImageSound(bad)


def test_wav_roundtrip(tmp_path):
    img = image_sound.ImageSound(_build(tmp_path))
    for r in img.records:
        out = os.path.join(str(tmp_path), "idx%04d.wav" % r.index)
        img.write_wav(r, out)
        with wave.open(out, "rb") as w:
            assert w.getframerate() == image_sound.SAMPLE_RATE
            assert w.getsampwidth() == 2
            assert w.getnchannels() == r.channels
            assert w.getnframes() == r.frames


def test_bodies_tile_contiguously(tmp_path):
    img = image_sound.ImageSound(_build(tmp_path))
    # first body starts at the header end; bodies are back-to-back up to md_off
    assert img.records[0].offset == image_sound.HEADER_SIZE
    cur = img.records[0].offset
    for r in img.records:
        assert r.offset == cur
        cur += r.body_bytes
    assert cur == img.md_off


@pytest.mark.skipif(not os.environ.get("SPIKE3_IMAGE_BIN"),
                    reason="set SPIKE3_IMAGE_BIN to a real extracted image.bin")
def test_real_container():
    img = image_sound.ImageSound(os.environ["SPIKE3_IMAGE_BIN"])
    assert img.count > 0
    img.validate()
    r = img.records[0]
    body = img.read_body(r)
    assert len(body) == r.body_bytes
