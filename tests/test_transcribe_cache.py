"""Unit tests for core.transcribe's cache helpers (no model, no network).

clear_whisper_cache backs the ⚙ menu's "Clear downloaded voice models"
(monkeybug: a damaged download kept failing with "Unable to open file
'model.bin'" and manual cache surgery was the only way out).  The critical
property: it must remove ONLY the faster-whisper model dirs — the same
huggingface hub cache holds users' unrelated models (stable-diffusion etc.).
"""
import os

import pytest

from pinball_decryptor.core import transcribe


def _mk(base, name, nbytes=100):
    d = os.path.join(base, name)
    os.makedirs(os.path.join(d, "snapshots", "abc"), exist_ok=True)
    with open(os.path.join(d, "snapshots", "abc", "blob"), "wb") as f:
        f.write(b"x" * nbytes)
    return d


def test_clear_whisper_cache_removes_only_whisper_dirs(tmp_path, monkeypatch):
    hfc = pytest.importorskip("huggingface_hub.constants")
    base = str(tmp_path)
    monkeypatch.setattr(hfc, "HF_HUB_CACHE", base)

    tiny = _mk(base, "models--Systran--faster-whisper-tiny.en", 100)
    corrupt = _mk(base, "models--Systran--faster-whisper-medium.en.corrupt",
                  50)
    other = _mk(base, "models--stabilityai--stable-diffusion-xl-base-1.0",
                999)
    loose = os.path.join(base, "version.txt")
    with open(loose, "w") as f:
        f.write("1")

    n, freed = transcribe.clear_whisper_cache()
    assert n == 2
    assert freed == 150
    assert not os.path.exists(tiny)
    assert not os.path.exists(corrupt)
    assert os.path.isdir(other)          # unrelated models untouched
    assert os.path.exists(loose)


def test_clear_whisper_cache_empty_or_missing(tmp_path, monkeypatch):
    hfc = pytest.importorskip("huggingface_hub.constants")
    monkeypatch.setattr(hfc, "HF_HUB_CACHE",
                        str(tmp_path / "does_not_exist"))
    assert transcribe.clear_whisper_cache() == (0, 0)


def test_disable_hf_progress_bars_sets_env(monkeypatch):
    """The windowed app has sys.stderr None — hf's tqdm bars must be off or
    a model download dies with 'NoneType' object has no attribute 'write'
    (David's Guardians run)."""
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    transcribe._disable_hf_progress_bars()      # must not raise
    assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"


def test_whisper_model_cached_false_on_empty_cache(tmp_path, monkeypatch):
    hfc = pytest.importorskip("huggingface_hub.constants")
    monkeypatch.setattr(hfc, "HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")   # belt: never hit the network
    assert transcribe.whisper_model_cached("tiny.en") is False


def test_wav_seconds(tmp_path):
    import wave
    p = str(tmp_path / "a.wav")
    w = wave.open(p, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(b"\x00\x00" * 44100)   # exactly 1.0 s
    w.close()
    assert transcribe._wav_seconds(p) == pytest.approx(1.0)
    assert transcribe._wav_seconds(str(tmp_path / "missing.wav")) is None
