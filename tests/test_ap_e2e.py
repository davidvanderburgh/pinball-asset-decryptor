"""End-to-end Extract -> Write round-trips for American Pinball `.pkg` files.

AP game-code packages are AES-256-CBC encrypted ZIPs ([8B size][16B IV][ct]),
decrypted with the universal key recovered from /usr/bin/pkgprocess on the
Clonezilla restore images.
"""

import struct

import pytest

from tests import synthetic
from tests._runner import run_pipeline_sync


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
# Detection
# ---------------------------------------------------------------------------

def test_ap_detects_by_filename(manufacturers_by_key, tmp_path):
    ap = manufacturers_by_key["ap"]
    pkg = synthetic.make_ap_aes_pkg(tmp_path / "houdini-gamecode_99.01.01.pkg")
    game = ap.detect(str(pkg))
    assert game is not None
    assert game.key == "houdini"
    assert game.manufacturer_key == "ap"


def test_ap_detects_unknown_name_by_key(manufacturers_by_key, tmp_path):
    """A package with no recognisable name is still claimed via the key probe."""
    ap = manufacturers_by_key["ap"]
    pkg = synthetic.make_ap_aes_pkg(tmp_path / "mystery-update.pkg")
    game = ap.detect(str(pkg))
    assert game is not None
    assert game.manufacturer_key == "ap"
    assert game.notes  # "detected via universal key"


def test_ap_does_not_claim_foreign_pkg(manufacturers_by_key, tmp_path):
    """A Spooky AES .pkg must not be mis-claimed by AP (wrong key)."""
    ap = manufacturers_by_key["ap"]
    foreign = synthetic.make_spooky_aes_pkg(
        tmp_path / "rm-gamecode-test.pkg", key_name="rm_pkg")
    assert ap.detect(str(foreign)) is None


def test_ap_ignores_non_ap_garbage(manufacturers_by_key, tmp_path):
    ap = manufacturers_by_key["ap"]
    junk = tmp_path / "random.pkg"
    junk.write_bytes(struct.pack("<Q", 100) + b"\x00" * 64)  # zeros, not a ZIP
    assert ap.detect(str(junk)) is None


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def test_ap_extract_pkg(manufacturers_by_key, tmp_path):
    ap = manufacturers_by_key["ap"]
    pkg = synthetic.make_ap_aes_pkg(tmp_path / "bbq-gamecode_24.07.04.pkg")
    out = tmp_path / "out"
    out.mkdir()
    r = _run_extract(ap, pkg, out)
    assert r.success, r.summary
    assert (out / "game.txt").is_file()
    assert (out / "game.txt").read_bytes() == b"AP synthetic content"
    assert (out / "config.yaml").is_file()


# ---------------------------------------------------------------------------
# Round trip — Extract -> modify -> Write -> re-extract -> verify
# ---------------------------------------------------------------------------

def test_ap_round_trip_pkg(manufacturers_by_key, tmp_path):
    ap = manufacturers_by_key["ap"]
    pkg_in = synthetic.make_ap_aes_pkg(tmp_path / "houdini-gamecode-in.pkg")
    extracted = tmp_path / "ex"
    extracted.mkdir()

    r1 = _run_extract(ap, pkg_in, extracted)
    assert r1.success, r1.summary

    (extracted / "game.txt").write_bytes(b"AP_ROUND_TRIP_OK")

    pkg_out = tmp_path / "houdini-gamecode-out.pkg"
    r2 = _run_write(ap, pkg_in, extracted, pkg_out)
    assert r2.success, r2.summary
    assert pkg_out.is_file() and pkg_out.stat().st_size > 0

    re_extracted = tmp_path / "re"
    re_extracted.mkdir()
    r3 = _run_extract(ap, pkg_out, re_extracted)
    assert r3.success, r3.summary
    assert (re_extracted / "game.txt").read_bytes() == b"AP_ROUND_TRIP_OK"
