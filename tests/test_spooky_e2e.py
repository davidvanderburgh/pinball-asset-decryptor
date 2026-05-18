"""End-to-end Extract -> Write round-trips for Spooky's synthesizable formats.

Covers every format we can synthesize without external tools or large
binary fixtures:
  - .ed         (Evil Dead, plain tar.gz)
  - .scooby     (Scooby-Doo, plain tar.gz)
  - .looney     (Looney Tunes, plain tar)
  - P3 .zip     (Jetsons, plain ZIP)
  - .pkg rm_pkg (Rick & Morty, AES-256-CBC with known key)
  - .pkg ac_pkg (Alice Cooper, AES-256-CBC with known key)

Skipped here (no good synthetic fixture / needs external tools):
  - GPG-symmetric .pkg (UM, H78)
  - GPG-signed .pkg (Beetlejuice)
  - Clonezilla .iso / .zip
"""

import pytest

from tests import synthetic
from tests._runner import run_pipeline_sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_extract(mfr, input_path, out_dir):
    p = mfr.make_extract_pipeline(
        str(input_path), str(out_dir),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    return run_pipeline_sync(p)


def _run_write(mfr, original, assets, output):
    p = mfr.make_write_pipeline(
        str(original), str(assets), str(output),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    return run_pipeline_sync(p)


# ---------------------------------------------------------------------------
# Extract-only tests (one per format)
# ---------------------------------------------------------------------------

def test_spooky_extract_ed(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    ed = synthetic.make_spooky_targz(tmp_path / "2025.12.19.ed")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(sp, ed, out)
    assert r.success, r.summary
    assert (out / "game" / "data.bin").is_file()


def test_spooky_extract_scooby(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    sc = synthetic.make_spooky_targz(tmp_path / "v2025.12.01.scooby")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(sp, sc, out)
    assert r.success, r.summary
    assert (out / "game" / "data.bin").is_file()


def test_spooky_extract_looney(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    lt = synthetic.make_spooky_plain_tar(tmp_path / "v2025.10.looney")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(sp, lt, out)
    assert r.success, r.summary
    assert (out / "game" / "data.bin").is_file()


def test_spooky_extract_p3_zip(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    z = synthetic.make_spooky_p3_zip(tmp_path / "Jetsons_Code.zip")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(sp, z, out)
    assert r.success, r.summary
    assert (out / "Jetsons" / "ATTRACT.VID").is_file()


def test_spooky_extract_rm_pkg(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    pkg = synthetic.make_spooky_aes_pkg(
        tmp_path / "rm-gamecode-test.pkg", key_name="rm_pkg")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(sp, pkg, out)
    assert r.success, r.summary
    # The synthetic ZIP we encrypted contained game.txt
    assert (out / "game.txt").is_file()
    assert (out / "game.txt").read_bytes() == b"R&M synthetic content"


def test_spooky_extract_ac_pkg(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    pkg = synthetic.make_spooky_aes_pkg(
        tmp_path / "ac-gamecode-test.pkg", key_name="ac_pkg")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(sp, pkg, out)
    assert r.success, r.summary
    assert (out / "game.txt").is_file()


# ---------------------------------------------------------------------------
# Round trips - Extract -> modify -> Write -> re-extract -> verify
# ---------------------------------------------------------------------------

def test_spooky_round_trip_ed(manufacturers_by_key, tmp_path):
    sp = manufacturers_by_key["spooky"]
    ed_in = synthetic.make_spooky_targz(tmp_path / "in.ed")
    extracted = tmp_path / "ex"; extracted.mkdir()

    r1 = _run_extract(sp, ed_in, extracted)
    assert r1.success, r1.summary

    # Modify a file
    f = extracted / "game" / "data.bin"
    f.write_bytes(b"MODIFIED_BY_TEST")

    ed_out = tmp_path / "out.ed"
    r2 = _run_write(sp, ed_in, extracted, ed_out)
    assert r2.success, r2.summary
    assert ed_out.is_file() and ed_out.stat().st_size > 0

    re_extracted = tmp_path / "re"; re_extracted.mkdir()
    r3 = _run_extract(sp, ed_out, re_extracted)
    assert r3.success, r3.summary
    assert (re_extracted / "game" / "data.bin").read_bytes() == b"MODIFIED_BY_TEST"


def test_spooky_round_trip_rm_pkg(manufacturers_by_key, tmp_path):
    """AES-256-CBC round trip — extract -> modify -> encrypt -> re-extract."""
    sp = manufacturers_by_key["spooky"]
    pkg_in = synthetic.make_spooky_aes_pkg(
        tmp_path / "rm-gamecode-in.pkg", key_name="rm_pkg")
    extracted = tmp_path / "ex"; extracted.mkdir()

    r1 = _run_extract(sp, pkg_in, extracted)
    assert r1.success, r1.summary

    (extracted / "game.txt").write_bytes(b"AES_ROUND_TRIP_OK")

    pkg_out = tmp_path / "rm-gamecode-out.pkg"
    r2 = _run_write(sp, pkg_in, extracted, pkg_out)
    assert r2.success, r2.summary

    re_extracted = tmp_path / "re"; re_extracted.mkdir()
    r3 = _run_extract(sp, pkg_out, re_extracted)
    assert r3.success, r3.summary
    assert (re_extracted / "game.txt").read_bytes() == b"AES_ROUND_TRIP_OK"
