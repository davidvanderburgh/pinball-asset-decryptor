"""PAD-1077: a Spike 3 extract decodes every image.bin to per-sound WAVs.

Synthetic containers (no Stern data, no keys) laid out like Pokemon LE's: the
main game's ``pokemon_le/image.bin`` and the menu's
``pokemon_le/spike3/spike_menu/image.bin``. Both pipelines (.spk package and
secure SD image) are driven through their extract step with a fake archive.
"""
import os
import shutil
import subprocess
import sys
import wave

import pytest

from pinball_decryptor.plugins.stern import spike3_extract as SX
from pinball_decryptor.plugins.stern import spike3_sound as S3
from pinball_decryptor.plugins.stern import spike3_spk as SPK

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = "pokemon_le/image.bin"
MENU = "pokemon_le/spike3/spike_menu/image.bin"


def _container(tmp_path, name="image.bin"):
    p = os.path.join(str(tmp_path), name)
    S3._synth_container(p)                    # idx0000 mono 100 fr, idx0001 stereo 50 fr
    return p


def _wavs(d):
    return sorted(n for n in os.listdir(d) if n.endswith(".wav"))


def _check_pair(audio_dir):
    assert _wavs(audio_dir) == ["idx0000.wav", "idx0001.wav"]
    with wave.open(os.path.join(audio_dir, "idx0000.wav"), "rb") as w:
        assert (w.getnchannels(), w.getnframes(), w.getframerate(),
                w.getsampwidth()) == (1, 100, 44100, 2)
    with wave.open(os.path.join(audio_dir, "idx0001.wav"), "rb") as w:
        assert (w.getnchannels(), w.getnframes()) == (2, 50)


# -- decoder -------------------------------------------------------------------

def test_decode_container_writes_wavs_and_clears_strays(tmp_path):
    src = _container(tmp_path)
    out = tmp_path / "audio"
    out.mkdir()
    (out / "idx0099.wav").write_bytes(b"old")           # a bigger earlier build
    (out / "notes.txt").write_text("mine")              # not ours: left alone
    seen = []
    got = S3.decode_container(src, str(out), progress=lambda d, t: seen.append((d, t)))
    assert got["sounds"] == 2 and got["mono"] == 1 and got["stereo"] == 1
    assert got["seconds"] == pytest.approx(150 / 44100.0)
    assert seen == [(1, 2), (2, 2)]
    _check_pair(str(out))
    assert (out / "notes.txt").exists()


def test_decode_container_rejects_non_container(tmp_path):
    p = tmp_path / "image.bin"
    p.write_bytes(b"\0" * 4096)
    with pytest.raises(ValueError):
        S3.decode_container(str(p), str(tmp_path / "audio"))


def test_decode_container_cancel(tmp_path):
    src = _container(tmp_path)

    def cancel():
        raise RuntimeError("stop")
    with pytest.raises(RuntimeError):
        S3.decode_container(src, str(tmp_path / "audio"), cancel=cancel)


def test_tool_cli_loads_the_package_decoder(tmp_path):
    tool = os.path.join(REPO, "stern-spike-3", "tools", "image_sound.py")
    r = subprocess.run([sys.executable, tool, "selftest"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    src = _container(tmp_path)
    r = subprocess.run([sys.executable, tool, "extract", src, "--out",
                        str(tmp_path / "out")], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    _check_pair(str(tmp_path / "out"))


# -- pipelines -----------------------------------------------------------------

class _Fobj:
    def __init__(self, path, src):
        self.path, self.src, self.offset = path, src, 0


class _FakeArc:
    """Stands in for spks.SpksArchive: just .files / .extract / ._read."""

    def __init__(self, files):
        self.files = [_Fobj(p, s) for p, s in files]

    def extract(self, fobj, out):
        shutil.copyfile(fobj.src, out)

    def _read(self, off, n):
        return b"\0" * n


class _FakeReader:
    """Stands in for the Spike 3 ext4 reader of the games partition."""

    def __init__(self, files):
        self.files = files

    def iter_regular_files(self, root_ino=2, max_depth=12):
        for i, (p, s) in enumerate(self.files):
            yield "/" + p, i + 10, s

    def extract_file(self, inode, out):
        shutil.copyfile(inode, out)

    def peek(self, inode, n):
        return b"\0" * n


def _pipe(cls, out, cats=None):
    logs = []
    p = cls("in", str(out), lambda m, lvl="info": logs.append((lvl, m)),
            lambda i: None, lambda *a: None, lambda *a: None,
            extract_categories=cats)
    return p, logs


def _files(tmp_path, bad=False):
    main = _container(tmp_path / "a") if (tmp_path / "a").mkdir() is None else None
    menu = _container(tmp_path / "b") if (tmp_path / "b").mkdir() is None else None
    files = [(MAIN, main), (MENU, menu)]
    if bad:
        (tmp_path / "c").mkdir()
        junk = tmp_path / "c" / "image.bin"
        junk.write_bytes(b"\1" * 4096)
        files.append(("other/image.bin", str(junk)))
    return files


def _assert_layout(out):
    snd = out / "sound"
    _check_pair(str(snd / "pokemon_le" / "audio"))
    _check_pair(str(snd / "pokemon_le" / "spike3" / "spike_menu" / "audio"))
    # the raw containers are not kept once decoded
    assert not (snd / "pokemon_le" / "image.bin").exists()
    assert not (snd / "pokemon_le" / "spike3" / "spike_menu" / "image.bin").exists()


def test_spk_pipeline_writes_wavs(tmp_path):
    out = tmp_path / "proj"
    p, logs = _pipe(SPK.Spike3SpkExtractPipeline, out)
    counts = p._extract(_FakeArc(_files(tmp_path, bad=True)))
    assert counts["audio"] == 4
    _assert_layout(out)
    # a container that isn't one is kept as it came, with a warning
    assert (out / "sound" / "other" / "image.bin").exists()
    assert not (out / "sound" / "other" / "audio").exists() or \
        not _wavs(str(out / "sound" / "other" / "audio"))
    assert any(lvl == "warn" and "other/image.bin" in m for lvl, m in logs)
    assert "4 sound (0 min)" in p._summary(counts)


def test_sd_pipeline_writes_wavs(tmp_path):
    out = tmp_path / "proj"
    p, _logs = _pipe(SX.Spike3ExtractPipeline, out)
    counts = p._extract_tree(_FakeReader(_files(tmp_path)))
    assert counts["audio"] == 4
    _assert_layout(out)
    assert "4 sound" in p._summary(counts)


@pytest.mark.parametrize("cats", [{"audio": False}, {"sounds": False}])
def test_audio_unticked_writes_nothing(tmp_path, cats):
    for cls, drive in ((SPK.Spike3SpkExtractPipeline,
                        lambda p, f: p._extract(_FakeArc(f))),
                       (SX.Spike3ExtractPipeline,
                        lambda p, f: p._extract_tree(_FakeReader(f)))):
        out = tmp_path / cls.__name__
        work = tmp_path / ("w_" + cls.__name__)
        work.mkdir()
        p, _ = _pipe(cls, out, cats)
        counts = drive(p, _files(work))
        assert counts["audio"] == 0
        assert not (out / "sound").exists()


def test_extract_tab_offers_audio_for_spike3():
    from pinball_decryptor.plugins.stern import manufacturer as M
    keys = [k for k, _ in M._SPIKE3_CAPS.extract_categories]
    assert keys == ["audio", "video", "images", "scenes"]
    assert SPK.Spike3SpkExtractPipeline.CATEGORIES == SX.CATEGORIES
