"""End-to-end Extract -> Write round-trip for Barrels of Fun.

Requires a host `gpg` binary (BOF .fun files are GPG-symmetric tar.gz).
Skips cleanly when gpg isn't installed — relevant for some CI matrix
entries (Windows runners don't ship gpg by default).
"""

import os
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.bof.games import GAME_DB
from tests import synthetic
from tests._runner import run_pipeline_sync
from tests.conftest import HAS_GPG


pytestmark = pytest.mark.skipif(
    not HAS_GPG, reason="gpg not installed; BOF .fun tests require it")


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


def _take_ownership(path):
    """On Linux, BOF's NativeExecutor wraps every command in
    ``sudo bash -c`` (lifted verbatim from upstream), so the extracted
    files end up owned by root.  Chown back to the current user so
    tests can read/modify them — CI runner has passwordless sudo, and
    a local dev would too if they're set up to run BOF at all."""
    if sys.platform != "linux":
        return
    subprocess.run(
        ["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(path)],
        check=False, capture_output=True)


@pytest.mark.requires_gpg
@pytest.mark.parametrize("game_key", ["labyrinth", "dune", "winchester"])
def test_bof_extract(manufacturers_by_key, tmp_path, game_key):
    bof = manufacturers_by_key["bof"]
    # BOF detect() matches on exact .fun filename, not game key -
    # 'lab.fun' for Labyrinth, etc.  Use the canonical name from GAME_DB.
    fun_name = GAME_DB[game_key]["fun_file"]
    fun = synthetic.make_bof_fun(tmp_path / fun_name, game_key=game_key)
    out = tmp_path / "out"; out.mkdir()
    r = _run_extract(bof, fun, out)
    assert r.success, f"{game_key} extract failed: {r.summary}\n{r.log_text()}"
    _take_ownership(out)
    assert (out / "main.x86_64").is_file()


@pytest.mark.requires_gpg
def test_bof_round_trip(manufacturers_by_key, tmp_path):
    """Extract -> modify -> re-encrypt -> re-extract -> verify edit."""
    bof = manufacturers_by_key["bof"]
    fun_name = GAME_DB["labyrinth"]["fun_file"]   # lab.fun

    fun_in = synthetic.make_bof_fun(tmp_path / fun_name, game_key="labyrinth")
    extracted = tmp_path / "ex"; extracted.mkdir()
    r1 = _run_extract(bof, fun_in, extracted)
    assert r1.success, r1.summary
    # Linux: claim ownership back before we try to modify.
    _take_ownership(extracted)

    # Modify the synthesized "binary"
    (extracted / "main.x86_64").write_bytes(b"BOF_ROUND_TRIP_OK")

    # Output filename must match BOF's detection pattern (lab.fun for
    # Labyrinth), so put it in a sibling dir rather than renaming it.
    out_dir = tmp_path / "out"; out_dir.mkdir()
    fun_out = out_dir / fun_name
    r2 = _run_write(bof, fun_in, extracted, fun_out)
    assert r2.success, f"BOF write failed: {r2.summary}\n{r2.log_text()}"
    _take_ownership(out_dir)

    re_extracted = tmp_path / "re"; re_extracted.mkdir()
    r3 = _run_extract(bof, fun_out, re_extracted)
    assert r3.success, r3.summary
    _take_ownership(re_extracted)
    assert (re_extracted / "main.x86_64").read_bytes() == b"BOF_ROUND_TRIP_OK"
