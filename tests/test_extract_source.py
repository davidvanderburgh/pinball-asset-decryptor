"""Tests for core.extract_source — the source-image staleness sidecar that
backs the GUI's 'source image changed' banner."""

import json
import os

from pinball_decryptor.core.extract_source import (
    SIDE_CAR, stale_source_message, write_extract_source)


def _make_image(path, data=b"\x00" * 4096):
    with open(path, "wb") as f:
        f.write(data)


def test_no_sidecar_is_quiet(tmp_path):
    # An assets folder with no sidecar (older extract) never warns.
    assert stale_source_message(str(tmp_path)) is None


def test_unchanged_source_is_quiet(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    assert os.path.isfile(out / SIDE_CAR)
    assert stale_source_message(str(out)) is None


def test_mtime_change_is_flagged(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    # Simulate a revert-to-fresh-copy: same bytes, new mtime.
    st = os.stat(img)
    os.utime(img, (st.st_atime, st.st_mtime + 120))
    msg = stale_source_message(str(out))
    assert msg is not None and "game.raw" in msg


def test_size_change_is_flagged(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    _make_image(str(img), b"\x01" * 8192)  # different size
    assert stale_source_message(str(out)) is not None


def test_missing_source_is_quiet(tmp_path):
    img = tmp_path / "game.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    os.remove(img)  # user relocated/deleted the image — don't nag
    assert stale_source_message(str(out)) is None


def test_nonfile_input_writes_no_sidecar(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    # A device-style path (Direct-SSD) isn't a regular file → no sidecar.
    write_extract_source(str(out), r"\\.\PHYSICALDRIVE9")
    assert not os.path.isfile(out / SIDE_CAR)
    assert stale_source_message(str(out)) is None


def test_corrupt_sidecar_is_quiet(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    with open(out / SIDE_CAR, "w", encoding="utf-8") as f:
        f.write("{ not json")
    assert stale_source_message(str(out)) is None


def test_sidecar_records_expected_fields(tmp_path):
    img = tmp_path / "the_image.raw"
    out = tmp_path / "out"
    out.mkdir()
    _make_image(str(img))
    write_extract_source(str(out), str(img))
    with open(out / SIDE_CAR, encoding="utf-8") as f:
        rec = json.load(f)
    assert rec["input_name"] == "the_image.raw"
    assert rec["size"] == 4096
    assert "mtime" in rec and isinstance(rec["mtime"], int)
