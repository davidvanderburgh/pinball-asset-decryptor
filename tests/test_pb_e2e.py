"""End-to-end Extract -> modify -> Write round-trip for Pinball Brothers.

Generates a synthetic .upd, runs the plugin's full Extract pipeline,
modifies a file in the output, runs Write to repack, then re-extracts
the output and verifies our edit landed.
"""

import os

import pytest

from tests import synthetic
from tests._runner import run_pipeline_sync


# ---------------------------------------------------------------------------
# Extract only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("game_key", ["abba", "alien", "queen", "predator"])
def test_pb_extract_synthetic_upd(manufacturers_by_key, tmp_path, game_key):
    pb = manufacturers_by_key["pb"]
    upd = synthetic.make_pb_upd(tmp_path / f"{game_key}.upd",
                                game_key=game_key)
    out_dir = tmp_path / "extracted"
    out_dir.mkdir()

    pipeline = pb.make_extract_pipeline(
        str(upd), str(out_dir),
        log_cb=lambda *a, **k: None,
        phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None,
        done_cb=lambda *a, **k: None)
    result = run_pipeline_sync(pipeline)

    assert result.success is True, \
        f"Extract failed for {game_key}: {result.summary}\n{result.log_text()}"
    # Baseline checksum file should have been written
    assert (out_dir / ".checksums.md5").is_file()
    # And every synthetic file we put in should be on disk
    from pinball_decryptor.plugins.pb.games import GAME_DB
    internal_dir = GAME_DB[game_key]["internal_dir"]
    expected = out_dir / internal_dir / "main.cfg"
    assert expected.is_file()


# ---------------------------------------------------------------------------
# Full round trip
# ---------------------------------------------------------------------------

def test_pb_round_trip(manufacturers_by_key, tmp_path):
    """Extract -> modify a file -> Write a new .upd -> re-extract -> verify."""
    pb = manufacturers_by_key["pb"]
    game_key = "abba"

    # 1. Synthesize input
    upd_in = synthetic.make_pb_upd(tmp_path / "in.upd", game_key=game_key)
    extracted = tmp_path / "extracted"
    extracted.mkdir()

    # 2. Extract
    p1 = pb.make_extract_pipeline(
        str(upd_in), str(extracted),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    r1 = run_pipeline_sync(p1)
    assert r1.success is True, r1.summary

    # 3. Modify main.cfg
    from pinball_decryptor.plugins.pb.games import GAME_DB
    internal = GAME_DB[game_key]["internal_dir"]
    cfg = extracted / internal / "main.cfg"
    cfg.write_bytes(b"# modified by test\nversion=ROUND_TRIP\n")

    # 4. Write a new .upd
    upd_out = tmp_path / "out.upd"
    p2 = pb.make_write_pipeline(
        str(upd_in), str(extracted), str(upd_out),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    r2 = run_pipeline_sync(p2)
    assert r2.success is True, r2.summary
    assert upd_out.is_file() and upd_out.stat().st_size > 0

    # 5. Re-extract the output to a fresh dir
    re_extracted = tmp_path / "re_extracted"
    re_extracted.mkdir()
    p3 = pb.make_extract_pipeline(
        str(upd_out), str(re_extracted),
        log_cb=lambda *a, **k: None, phase_cb=lambda *a, **k: None,
        progress_cb=lambda *a, **k: None, done_cb=lambda *a, **k: None)
    r3 = run_pipeline_sync(p3)
    assert r3.success is True, r3.summary

    # 6. Verify our edit survived the round trip
    cfg_after = re_extracted / internal / "main.cfg"
    assert cfg_after.is_file()
    assert b"ROUND_TRIP" in cfg_after.read_bytes()
