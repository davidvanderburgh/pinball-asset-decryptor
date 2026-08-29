"""Tests for finding ffplay (Replace-Audio preview) -- PAD-92.

ffplay only ships with the FULL ffmpeg build, so users are told to drop it
next to the ffmpeg the app uses.  On a Windows install that ffmpeg is the
version-stamped imageio-ffmpeg binary, which
``ensure_bundled_ffmpeg_on_path`` re-exposes as a plain ``ffmpeg.exe`` COPY in
a throwaway temp dir -- and that copy is what ``find_ffmpeg`` then resolves.
The old lookup only searched next to it, so a hand-dropped ffplay next to the
real binary was never found (a user's report: "placing ffplay in the same
directory didn't seem to work").
"""

import os
import shutil

import pytest

import pinball_decryptor.core.audio as audio

EXT = ".exe" if os.name == "nt" else ""


@pytest.fixture(autouse=True)
def _clean_caches(monkeypatch):
    """Every finder memoises its answer in a module global; start from cold
    and never leak this test's fake paths into another one."""
    monkeypatch.setattr(audio, "_ffmpeg_path", None)
    monkeypatch.setattr(audio, "_ffprobe_path", None)
    monkeypatch.setattr(audio, "_ffplay_path", None)
    monkeypatch.setattr(audio, "_ffmpeg_shim_dir", "")
    monkeypatch.setattr(audio, "_ffmpeg_shim_src", "")
    monkeypatch.setattr(audio, "_imageio_ffmpeg_exe", lambda: None)
    monkeypatch.setattr(audio, "_ffmpeg_candidates", lambda _n: [])
    monkeypatch.setattr(shutil, "which", lambda _n: None)


def _bundled_install(tmp_path, monkeypatch, with_ffplay=True):
    """The reporter's machine: imageio's version-stamped ffmpeg under the
    install dir, the temp shim copy on PATH, and (optionally) an ffplay he
    dropped next to the real binary."""
    binaries = tmp_path / "site-packages" / "imageio_ffmpeg" / "binaries"
    binaries.mkdir(parents=True)
    real = binaries / ("ffmpeg-win-x86_64-v7.1" + EXT)
    real.write_bytes(b"real")
    if with_ffplay:
        (binaries / ("ffplay" + EXT)).write_bytes(b"dropped by hand")

    shim_dir = tmp_path / "pad-ffmpeg-abc123"
    shim_dir.mkdir()
    shim = shim_dir / ("ffmpeg" + EXT)
    shim.write_bytes(b"copy of the real one")

    monkeypatch.setattr(audio, "_imageio_ffmpeg_exe", lambda: str(real))
    monkeypatch.setattr(audio, "_ffmpeg_shim_src", str(real))
    monkeypatch.setattr(audio, "_ffmpeg_shim_dir", str(shim_dir))
    monkeypatch.setattr(audio, "_ffmpeg_path", str(shim))  # find_ffmpeg says
    return binaries, shim_dir


def test_ffplay_found_next_to_the_bundled_ffmpeg(tmp_path, monkeypatch):
    """The regression: ffplay dropped beside the REAL bundled binary, while
    ffmpeg resolves to the temp shim copy that sits alone in its own dir."""
    binaries, _shim_dir = _bundled_install(tmp_path, monkeypatch)
    assert audio.find_ffplay() == str(binaries / ("ffplay" + EXT))


def test_no_ffplay_still_reports_missing(tmp_path, monkeypatch):
    """Nothing dropped anywhere -> None (the preview's "Can't Preview" path),
    and the answer is cached as "looked, found nothing"."""
    _bundled_install(tmp_path, monkeypatch, with_ffplay=False)
    assert audio.find_ffplay() is None
    assert audio._ffplay_path == ""


def test_sibling_dirs_never_offer_the_temp_shim(tmp_path, monkeypatch):
    """The GUI tells the user which folder to drop ffplay into, so the temp
    shim dir -- one throwaway copy of ffmpeg, gone next run -- must never be
    the advice; the real binary's folder is."""
    binaries, shim_dir = _bundled_install(tmp_path, monkeypatch)
    dirs = audio.ffmpeg_sibling_dirs()
    assert dirs[0] == str(binaries)
    assert str(shim_dir) not in dirs


def test_sibling_dirs_prefer_a_real_ffmpeg_install(tmp_path, monkeypatch):
    """With a real (essentials) ffmpeg on PATH there is no shim, so the
    advice is that install's own folder -- not the bundled one."""
    real_bin = tmp_path / "winget" / "bin"
    real_bin.mkdir(parents=True)
    ffmpeg = real_bin / ("ffmpeg" + EXT)
    ffmpeg.write_bytes(b"essentials build")
    bundled = tmp_path / "binaries" / ("ffmpeg-win-x86_64-v7.1" + EXT)
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"bundled")
    monkeypatch.setattr(audio, "_ffmpeg_path", str(ffmpeg))
    monkeypatch.setattr(audio, "_imageio_ffmpeg_exe", lambda: str(bundled))

    dirs = audio.ffmpeg_sibling_dirs()
    assert dirs[0] == str(real_bin)
    assert str(bundled.parent) in dirs   # still searched, just second


def test_ffplay_found_in_an_os_install_location(tmp_path, monkeypatch):
    """A full build installed by winget/scoop/brew is found even when its
    folder never made it onto this process's PATH."""
    d = tmp_path / "choco" / "bin"
    d.mkdir(parents=True)
    play = d / ("ffplay" + EXT)
    play.write_bytes(b"full build")
    monkeypatch.setattr(audio, "_ffmpeg_candidates",
                        lambda name: [str(d / (name + EXT))])
    assert audio.find_ffplay() == str(play)


def test_path_still_wins(tmp_path, monkeypatch):
    """PATH is still the first answer -- the extra lookups are fallbacks."""
    _bundled_install(tmp_path, monkeypatch)
    monkeypatch.setattr(shutil, "which",
                        lambda n: "/usr/bin/ffplay" if n == "ffplay" else None)
    assert audio.find_ffplay() == "/usr/bin/ffplay"


def test_ffprobe_also_looks_beside_the_real_binary(tmp_path, monkeypatch):
    """Same shim blind spot, same fix: a hand-dropped ffprobe is found."""
    binaries, _ = _bundled_install(tmp_path, monkeypatch, with_ffplay=False)
    probe = binaries / ("ffprobe" + EXT)
    probe.write_bytes(b"dropped by hand")
    assert audio.find_ffprobe() == str(probe)


def test_shim_records_the_binary_it_copied(monkeypatch, tmp_path):
    """ensure_bundled_ffmpeg_on_path must leave the trail the lookups need:
    the temp dir it made and the real binary behind it."""
    monkeypatch.setattr(audio, "_ffmpeg_shimmed", False)
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    fake = tmp_path / "ffmpeg-win-x86_64-v7.1"
    fake.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(audio, "_imageio_ffmpeg_exe", lambda: str(fake))
    saved = os.environ.get("PATH", "")
    try:
        audio.ensure_bundled_ffmpeg_on_path()
        assert audio._ffmpeg_shim_src == str(fake)
        first = os.environ["PATH"].split(os.pathsep)[0]
        assert audio._ffmpeg_shim_dir == first
    finally:
        os.environ["PATH"] = saved
        audio._ffmpeg_shimmed = False
        audio._ffmpeg_shim_dir = audio._ffmpeg_shim_src = ""
