"""The codec-params derive reports progress (fast; no boot, no card).

The derive is a strictly sequential walk of the card's sound catalog, so it
scales with catalog size: measured ~19 s of chain for TMNT 1.58's 2067 records
against ~19 min for Deadpool Pro 1.16's 8175.  It used to show one indeterminate
"Deriving codec parameters..." for that whole time, which is exactly what the
field report behind PAD-2 read as an indefinite hang.  The record count is known
from the master-directory malloc in the first instructions, so the chain can
report real per-record progress.
"""
import pickle

import pytest

from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern.spike2.emulator import (PROGRESS_UPDATES,
                                                             _progress_step)


@pytest.mark.parametrize("nrec", [0, 1, 2, 199, 200, 201, 2067, 8175, 10500])
def test_step_is_never_zero(nrec):
    """A 0 step would make ``idx % step`` raise and take the whole derive down
    on exactly the small catalogs that never needed throttling."""
    assert _progress_step(nrec) >= 1


@pytest.mark.parametrize("nrec", [1, 2, 199, 2067, 8175, 10500])
def test_update_count_is_bounded_and_useful(nrec):
    """About PROGRESS_UPDATES updates for any catalog: enough that the bar keeps
    moving, few enough that a slow GUI callback can't dominate the loop."""
    step = _progress_step(nrec)
    n = len(range(0, nrec, step))
    assert n <= PROGRESS_UPDATES + 1
    assert n >= min(nrec, PROGRESS_UPDATES) // 2


def test_small_catalog_reports_every_record():
    """Below the update budget nothing is throttled away."""
    assert _progress_step(150) == 1


def test_deadpool_sized_catalog_is_throttled():
    """8175 records must not mean 8175 GUI callbacks."""
    assert _progress_step(8175) > 1
    assert len(range(0, 8175, _progress_step(8175))) <= PROGRESS_UPDATES + 1


class _FakeEmu:
    """Records how derive_params was called."""

    def __init__(self):
        self.got_progress = "not called"

    def derive_params(self, progress=None):
        self.got_progress = progress
        return [{"idx": 0, "key0": 1}]


def _card(tmp_path):
    gr = tmp_path / "game_real"
    img = tmp_path / "image.bin"
    gr.write_bytes(b"\x7fELF" + b"\x00" * 64)
    img.write_bytes(b"\x11" * 0x20000)
    return str(gr), str(img)


def test_progress_is_forwarded_to_the_chain(tmp_path, monkeypatch):
    """The wiring is the thing that silently breaks: derive_params defaults
    progress to None, so a dropped argument costs no test and no error -- it
    just goes back to a frozen bar for the whole derive."""
    monkeypatch.setattr(engine, "_params_cache_dir", lambda: str(tmp_path / "c"))
    (tmp_path / "c").mkdir()
    gr, img = _card(tmp_path)
    emu = _FakeEmu()
    seen = []

    engine._load_or_derive_params(
        emu, gr, img, lambda *a, **k: None,
        lambda done, total, msg: seen.append((done, total, msg)))

    assert emu.got_progress is not None, "derive_params got no progress callback"
    assert callable(emu.got_progress)
    emu.got_progress(7, 99, "x")
    assert (7, 99, "x") in seen


def test_derive_still_works_without_a_progress_callback(tmp_path, monkeypatch):
    """Extract passes one; the Write path and the tests don't."""
    monkeypatch.setattr(engine, "_params_cache_dir", lambda: str(tmp_path / "c"))
    (tmp_path / "c").mkdir()
    gr, img = _card(tmp_path)
    emu = _FakeEmu()
    params = engine._load_or_derive_params(emu, gr, img, lambda *a, **k: None, None)
    assert params and emu.got_progress is None


def test_derive_result_is_cached_under_the_revision_tag(tmp_path, monkeypatch):
    """A derive this expensive must not be repeated: confirm it lands in the
    cache under the current revision so the next run loads it."""
    monkeypatch.setattr(engine, "_params_cache_dir", lambda: str(tmp_path / "c"))
    (tmp_path / "c").mkdir()
    gr, img = _card(tmp_path)
    engine._load_or_derive_params(_FakeEmu(), gr, img, lambda *a, **k: None, None)
    cache = engine._cache_path(engine._fingerprint(gr, img))
    assert pickle.load(open(cache, "rb"))[0]["idx"] == 0
    assert engine._is_stale_cache_file(cache.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]) is False
