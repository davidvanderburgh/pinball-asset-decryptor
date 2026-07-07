"""Parallel-transcription worker sizing (pure arithmetic, no model, no RAM read).

monkeybug ran medium.en over 549 clips on an 8-core box: the pool spun up 7
workers (cores-1), each loading its own ~2 GB medium.en model, and partway
through the run every worker hit a multi-minute clip at once (files are
duration-sorted) and inference started failing with "mkl_malloc: failed to
allocate memory", silently demoting long clips to non-speech.  _plan_workers
now caps the worker count to a RAM budget so the heavy model can't
over-subscribe memory.
"""
from pinball_decryptor.core import transcribe
from pinball_decryptor.core.transcribe import _plan_workers


def test_heavy_model_capped_by_ram():
    # 8 GB free, medium.en (~2.2 GB/worker): (8-2)/2.2 = 2 workers, not 7.
    assert _plan_workers("medium.en", ncpu=8, nwavs=549, avail_ram_gb=8) == 2


def test_heavy_model_more_ram_more_workers_but_cpu_bounded():
    # Plenty of RAM: falls back to the CPU cap (cores-1, max 8).
    assert _plan_workers("medium.en", ncpu=8, nwavs=549, avail_ram_gb=64) == 7
    assert _plan_workers("medium.en", ncpu=32, nwavs=549, avail_ram_gb=256) == 8


def test_light_model_uses_cpu_cap():
    # tiny.en (~0.6 GB) never hits the RAM cap on a normal box.
    assert _plan_workers("tiny.en", ncpu=8, nwavs=549, avail_ram_gb=16) == 7


def test_work_available_bounds_workers():
    assert _plan_workers("tiny.en", ncpu=8, nwavs=3, avail_ram_gb=64) == 3


def test_never_below_one():
    assert _plan_workers("large-v3", ncpu=2, nwavs=1, avail_ram_gb=1) == 1
    assert _plan_workers("medium.en", ncpu=8, nwavs=549, avail_ram_gb=2.5) == 1


def test_unknown_ram_falls_back_to_model_only_cap(monkeypatch):
    monkeypatch.setattr(transcribe, "_available_ram_gb", lambda: None)
    # Heavy model, RAM unknown: conservative cap of 2 (not cores-1 = 7).
    assert _plan_workers("medium.en", ncpu=8, nwavs=549) == 2
    # Light model, RAM unknown: full CPU cap.
    assert _plan_workers("tiny.en", ncpu=8, nwavs=549) == 7


def test_available_ram_gb_never_raises():
    # Whatever the platform, the live reader must be None-safe.
    v = transcribe._available_ram_gb()
    assert v is None or (isinstance(v, float) and v > 0)
