"""End-to-end Extract + Write tests for Barrels of Fun.

Requires a host `gpg` binary for the synthetic fixture generator
(which runs `gpg --symmetric` to wrap a tar.gz).  BOF on Windows
needs WSL because its NativeExecutor isn't available there — those
tests skip cleanly when WSL isn't around.

Coverage scope:
  - Extract works for every BOF game (gpg-decrypt + tar.gz extract)
  - Extract + unmodified Write + Extract is an identity round-trip
    (i.e. gpg + tar pack/unpack primitives don't corrupt content)

We deliberately don't test "modify a file + Write picks it up" — BOF's
Write pipeline only repacks files from a `pck/` subdirectory produced
by GDRE Tools, so testing that requires GDRE Tools and a real Godot
binary; out of scope for fixture-based CI.
"""

import sys

import pytest

from pinball_decryptor.plugins.bof.games import GAME_DB
from tests import synthetic
from tests._runner import run_pipeline_sync
from tests.conftest import HAS_GPG, HAS_WSL


# BOF needs gpg everywhere AND, on Windows, also needs WSL because its
# executor shells everything out to bash.
_SKIP_REASON = None
if not HAS_GPG:
    _SKIP_REASON = "gpg not installed; BOF .fun tests require it"
elif sys.platform == "win32" and not HAS_WSL:
    _SKIP_REASON = "BOF on Windows requires WSL2 (not present on CI runner)"

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None,
                                 reason=_SKIP_REASON or "")


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


@pytest.mark.requires_gpg
@pytest.mark.parametrize("game_key", ["labyrinth", "dune", "winchester"])
def test_bof_extract(manufacturers_by_key, tmp_path, game_key):
    bof = manufacturers_by_key["bof"]
    # BOF detect() matches on exact .fun filename, not game key —
    # 'lab.fun' for Labyrinth, etc.  Use the canonical name from GAME_DB.
    fun_name = GAME_DB[game_key]["fun_file"]
    fun = synthetic.make_bof_fun(tmp_path / fun_name, game_key=game_key)
    out = tmp_path / "out"; out.mkdir()
    r = _run_extract(bof, fun, out)
    assert r.success, f"{game_key} extract failed: {r.summary}\n{r.log_text()}"
    assert (out / "main.x86_64").is_file()


@pytest.mark.requires_gpg
def test_bof_identity_round_trip(manufacturers_by_key, tmp_path):
    """Extract -> Write (no modify) -> re-extract: verify content
    survives a full gpg-encrypt + tar-pack + gpg-decrypt + tar-unpack
    cycle.  This is the data-flow guarantee BOF's primitives provide;
    the actual "modify the assets" case requires GDRE Tools and is out
    of scope here."""
    bof = manufacturers_by_key["bof"]
    fun_name = GAME_DB["labyrinth"]["fun_file"]   # lab.fun

    fun_in = synthetic.make_bof_fun(tmp_path / fun_name, game_key="labyrinth")
    extracted = tmp_path / "ex"; extracted.mkdir()
    r1 = _run_extract(bof, fun_in, extracted)
    assert r1.success, r1.summary
    original_binary = (extracted / "main.x86_64").read_bytes()

    # Output filename must match BOF's detection pattern (lab.fun for
    # Labyrinth); put it in a sibling dir so it doesn't collide with
    # the input fixture.
    out_dir = tmp_path / "out"; out_dir.mkdir()
    fun_out = out_dir / fun_name
    r2 = _run_write(bof, fun_in, extracted, fun_out)
    assert r2.success, f"BOF write failed: {r2.summary}\n{r2.log_text()}"

    re_extracted = tmp_path / "re"; re_extracted.mkdir()
    r3 = _run_extract(bof, fun_out, re_extracted)
    assert r3.success, r3.summary
    assert (re_extracted / "main.x86_64").read_bytes() == original_binary, (
        "Identity round trip changed the binary - gpg or tar primitives "
        "are not preserving content")
