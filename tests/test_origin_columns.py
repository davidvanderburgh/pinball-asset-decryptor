"""The Origin column on the Audio, Video and Text tabs (core/asset_origin.py), as the Images tab's.

Simon (2026-11-21): "another column (Probably audio, video, images and even text) to account for whether the
asset is original or custom (custom being an asset that isn't original but has been extracted from the current
card)".  Each row carries "og" (Original / Custom; none when not known) and the column sorts.
"""

import hashlib
import struct
import time
import wave

import pytest

from tests.webui_harness import web_app


def _record(**over):
    rec = {"official": False, "against": "x",
           "custom": {"audio/b.wav", "video/b.mp4"},
           "known": {"audio": True, "video": True, "text": True, "images": True},
           "text_custom": {("/g/aaaaaaaaaaaaaaaaaaaa/scene.radium", "EBIRAH")}}
    rec.update(over)
    return rec


@pytest.fixture
def origins(monkeypatch):
    from pinball_decryptor.core import asset_origin
    box = {"rec": _record()}
    monkeypatch.setattr(asset_origin, "origins", lambda *a, **k: box["rec"])
    return box


def _wait(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _set_project(w, folder):
    def _set():
        try:
            w.window.write_assets_var.set(str(folder))
        except Exception:                               # noqa: BLE001 - another tab's trace
            pass
    w.run(_set)


# ------------------------------------------------------------------ Audio
def _wav(path, seconds=0.2, rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", 2000 if i % 16 < 8 else -2000)
                               for i in range(int(seconds * rate))))


def test_audio_rows_carry_origin(tmp_path, origins):
    folder = tmp_path / "proj"
    for rel in ("audio/a.wav", "audio/b.wav"):
        _wav(folder / rel)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(folder))
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _set_project(w, folder)
        w.call("ui.select_tab", "audio")
        assert _wait(w, lambda: len(w.state("audio")["rows"]) == 2 and not w.state("audio")["scanning"])
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        assert rows["audio/a.wav"]["og"] == "Original"
        assert rows["audio/b.wav"]["og"] == "Custom"
        # sortable: A to Z, so Custom first
        assert w.call("audio.sort", "org") is True
        assert [r["k"] for r in w.state("audio")["rows"]] == ["audio/b.wav", "audio/a.wav"]
        # not known: no "og" at all
        origins["rec"] = _record(known={})
        w.call("audio.sort", "org")
        assert all("og" not in r for r in w.state("audio")["rows"])
        # the column's dragged width is kept
        assert w.call("audio.save_widths", {"org": 90}) is True
        assert w.state("audio")["widths"]["org"] == 90


# ------------------------------------------------------------------ Video
def test_video_rows_carry_origin(tmp_path, origins):
    root = tmp_path / "proj"
    lines = []
    for rel in ("video/a.mp4", "video/b.mp4"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * 64)
        lines.append("%s\t%s\n" % (rel, hashlib.md5(b"\0" * 64).hexdigest()))
    (root / ".checksums.md5").write_text("".join(lines), encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        _set_project(w, root)
        w.call("video.scan")
        assert _wait(w, lambda: not w.state("video").get("scanning") and w.state("video").get("rows"))
        st = w.state("video")
        rows = {r["rel"]: r for r in st["rows"]}
        assert rows["video/a.mp4"]["og"] == "Original"
        assert rows["video/b.mp4"]["og"] == "Custom"
        assert w.call("video.sort", "org") is True
        st = w.state("video")
        assert st["sort"]["key"] == "org"
        assert [st["rows"][i]["rel"] for i in st["view"]] == ["video/b.mp4", "video/a.mp4"]
        origins["rec"] = _record(known={"images": True})
        w.call("video.sort", "org")
        assert all("og" not in r for r in w.state("video")["rows"])
        from pinball_decryptor.webui.tabs.video import VideoTab
        assert "org" in VideoTab._WIDTH_COLS


# ------------------------------------------------------------------ Text
def test_text_rows_carry_origin(tmp_path, origins):
    from pinball_decryptor.core import text_manifest
    folder = tmp_path / "proj"
    folder.mkdir()
    text_manifest.save(str(folder), [
        {"path": "/g/aaaaaaaaaaaaaaaaaaaa/scene.radium", "original": "GODZILLA", "replacement": ""},
        {"path": "/g/aaaaaaaaaaaaaaaaaaaa/scene.radium", "original": "EBIRAH", "replacement": ""},
    ])
    with web_app(tmp_path, mfr="stern") as w:
        _set_project(w, folder)
        w.call("ui.select_tab", "text")
        assert _wait(w, lambda: not w.state("text")["scanning"] and w.state("text").get("total", 0) == 2)
        rows = {r["o"]: r for r in w.state("text")["rows"]}
        assert rows["GODZILLA"]["og"] == "Original"
        assert rows["EBIRAH"]["og"] == "Custom"
        assert w.call("text.sort_by", "org") is True
        st = w.state("text")
        assert [st["rows"][i]["o"] for i in st["view"]] == ["EBIRAH", "GODZILLA"]
        assert w.call("text.save_widths", {"org": 80}) is True
        assert w.state("text")["col_widths"]["org"] == 80


def test_origin_words_never_say_mode():
    import os
    import re
    base = os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "webui", "static", "js", "tabs")
    for name in ("audio.js", "video.js", "text.js"):
        with open(os.path.join(base, name), encoding="utf-8") as f:
            src = f.read()
        tip = re.search(r'const ORG_TIP = "([^"]*)"', src)
        assert tip, name
        assert not re.search(r"\bmodes?\b", tip.group(1), re.I)
