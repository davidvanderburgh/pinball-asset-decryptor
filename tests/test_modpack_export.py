"""Export Mod Pack must include the user's Replace-tab edits.

monkeybug assigned ~50 audio replacements on the Replace Audio tab and hit
"Export mod pack" straight away — it failed with "No modified files found"
even though the Write preview listed every one as Pending.  The Replace tabs
record assignments in memory (+ a sidecar) and only *stage them onto disk* at
build time; the export diffed the still-pristine on-disk bytes against the
baseline and saw nothing.  ``App._export_worker`` now stages pending
replacements first, exactly like the build flow, so an export needs no
build-first dance.

Also guards a baseline-flavour regression: ``export_mod_pack`` must read the
md5sum-style ``.checksums.md5`` (JJP), not only the tab form.
"""
import os
import queue
import zipfile

import pytest

from pinball_decryptor import app as appmod
from pinball_decryptor.core import modpack
from pinball_decryptor.core.messages import LogMsg


# --- baseline parsing: export_mod_pack accepts BOTH .checksums.md5 flavours ---

def _write(path, data=b"data"):
    with open(path, "wb") as f:
        f.write(data)


def _md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def test_export_reads_tab_flavour_baseline(tmp_path):
    # BOF / Stern style: "<path>\t<md5>".
    _write(tmp_path / "a.wav", b"orig")
    _write(tmp_path / "b.wav", b"orig")
    (tmp_path / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\nb.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    _write(tmp_path / "a.wav", b"CHANGED")   # modify one file

    n, _ = modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))
    assert n == 1
    with zipfile.ZipFile(tmp_path / "pack.zip") as zf:
        assert zf.namelist() == ["a.wav"]


def test_export_reads_md5sum_flavour_baseline(tmp_path):
    # JJP / md5sum style: "<md5>  <path>".  read_checksums() returned {} for
    # this, so export wrongly raised "no baseline" on a valid JJP extract.
    _write(tmp_path / "a.wav", b"orig")
    (tmp_path / ".checksums.md5").write_text(
        f"{_md5(b'orig')}  a.wav\n", encoding="utf-8")
    _write(tmp_path / "a.wav", b"CHANGED")

    n, _ = modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))
    assert n == 1


def test_export_no_changes_raises(tmp_path):
    _write(tmp_path / "a.wav", b"orig")
    (tmp_path / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No modified files"):
        modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))


def test_export_missing_baseline_raises(tmp_path):
    _write(tmp_path / "a.wav", b"orig")
    with pytest.raises(FileNotFoundError):
        modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))


# --- the fix: App._export_worker stages pending replacements before diffing ---

class _FakeRoot:
    def after(self, _delay, fn=None, *a):
        # Run the scheduled dialog callback inline so exceptions surface; the
        # messagebox is patched to a no-op in the app module for these tests.
        if fn is not None:
            fn(*a)


def _make_app(monkeypatch):
    a = appmod.App.__new__(appmod.App)      # skip Tk/window construction
    a.msg_queue = queue.Queue()
    a.root = _FakeRoot()
    monkeypatch.setattr(appmod, "messagebox",
                        type("M", (), {"showinfo": staticmethod(lambda *a, **k: None),
                                       "showerror": staticmethod(lambda *a, **k: None)}))
    return a


def _baseline(tmp_path, files):
    for name, data in files.items():
        _write(tmp_path / name, data)
    lines = "".join(f"{name}\t{_md5(data)}\n" for name, data in files.items())
    (tmp_path / ".checksums.md5").write_text(lines, encoding="utf-8")


def test_export_worker_stages_pending_then_packs(tmp_path, monkeypatch):
    a = _make_app(monkeypatch)
    _baseline(tmp_path, {"a.wav": b"orig", "b.wav": b"orig"})

    # Simulate the Replace-Audio stager: it writes the converted replacement
    # over a.wav (as the real one does), and reports (pending, staged, fails).
    def _stage_audio(assets_dir):
        _write(os.path.join(assets_dir, "a.wav"), b"REPLACED")
        return (1, 1, [])

    monkeypatch.setattr(a, "_stage_pending_audio", _stage_audio)
    monkeypatch.setattr(a, "_stage_pending_video", lambda d: (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_image", lambda d: (0, 0, []))

    zip_path = str(tmp_path / "pack.zip")
    a._export_worker(str(tmp_path), zip_path)

    assert os.path.isfile(zip_path), "export should have produced a zip"
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["a.wav"]
    logs = [m.text for m in _drain(a.msg_queue) if isinstance(m, LogMsg)]
    assert any("Mod pack: 1 file" in t for t in logs)


def test_export_worker_all_staging_failed_raises(tmp_path, monkeypatch):
    a = _make_app(monkeypatch)
    _baseline(tmp_path, {"a.wav": b"orig"})

    # Every convert failed (e.g. no ffmpeg): nothing lands on disk, so the pack
    # would be empty — surface that loudly instead of writing a useless zip.
    monkeypatch.setattr(a, "_stage_pending_audio",
                        lambda d: (2, 0, [("audio: a.wav", "need ffmpeg")]))
    monkeypatch.setattr(a, "_stage_pending_video", lambda d: (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_image", lambda d: (0, 0, []))

    a._export_worker(str(tmp_path), str(tmp_path / "pack.zip"))

    assert not os.path.isfile(tmp_path / "pack.zip")
    logs = [m.text for m in _drain(a.msg_queue) if isinstance(m, LogMsg)]
    assert any("Export failed" in t and "ffmpeg" in t for t in logs)


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
