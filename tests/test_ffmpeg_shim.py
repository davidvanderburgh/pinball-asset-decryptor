"""Tests for the bundled-ffmpeg PATH shim.

The frozen macOS/Linux apps bundle ffmpeg via imageio-ffmpeg under a
version-stamped name (e.g. ``ffmpeg-osx-arm64-v7.0``), so
``shutil.which("ffmpeg")`` and the ``ffmpeg -version`` prerequisite probes
can't see it.  ``core.audio.ensure_bundled_ffmpeg_on_path`` exposes it as a
plain ``ffmpeg`` on PATH so every finder/probe resolves it.  This guards the
CGC/Spooky/Williams "ffmpeg missing" reports on macOS even though it was
bundled.
"""

import os
import shutil

import pinball_decryptor.core.audio as audio


def test_shim_noop_when_ffmpeg_already_on_path(monkeypatch):
    audio._ffmpeg_shimmed = False
    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/ffmpeg")
    before = os.environ.get("PATH", "")
    audio.ensure_bundled_ffmpeg_on_path()
    assert os.environ.get("PATH", "") == before  # PATH untouched


def test_shim_exposes_bundled_ffmpeg(monkeypatch, tmp_path):
    audio._ffmpeg_shimmed = False
    # No system ffmpeg on PATH...
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    # ...but imageio ships a version-stamped binary.
    fake = tmp_path / "ffmpeg-osx-arm64-v7.0"
    fake.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(audio, "_imageio_ffmpeg_exe", lambda: str(fake))
    saved = os.environ.get("PATH", "")
    try:
        audio.ensure_bundled_ffmpeg_on_path()
        first = os.environ["PATH"].split(os.pathsep)[0]
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        assert os.path.isfile(os.path.join(first, name)), (
            "shim should expose a plain 'ffmpeg' on the front of PATH")
    finally:
        os.environ["PATH"] = saved
        audio._ffmpeg_shimmed = False


def test_shim_is_idempotent(monkeypatch):
    audio._ffmpeg_shimmed = False
    calls = []

    def _which(_n):
        calls.append(1)
        return "/usr/bin/ffmpeg"

    monkeypatch.setattr(shutil, "which", _which)
    audio.ensure_bundled_ffmpeg_on_path()
    audio.ensure_bundled_ffmpeg_on_path()
    assert len(calls) == 1  # second call short-circuits on the guard
