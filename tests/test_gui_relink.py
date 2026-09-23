"""Project ▾ → "Relink moved files…" — the window that re-points a moved
project's replacement sources, driven end to end.

The whole value of this window is that a user clicks Search, reads what was
found, and clicks Relink, so the test walks the same three steps through the
calls the page makes (webui/shellx_projects.py, ``shellx.relink_*``) and then
reads the sidecar the app would build from.
"""

import json
import os
import time
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import staged_changes
from tests.webui_harness import web_app


def _until(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def moved(tmp_path, monkeypatch):
    """A project whose replacements all point at a PC that isn't this one,
    plus the same files sitting under a new folder."""
    proj = tmp_path / "GZ Heisei Custom"
    proj.mkdir()
    staged_changes.save(str(proj), {
        # One clip used by two slots, plus a video and an image.
        "audio": {"audio/idx0001.wav": r"G:\GZ media\audio\roar.wav",
                  "audio/idx0417.wav": r"G:\GZ media\audio\roar.wav"},
        "video": {"video/intro.mov": r"G:\GZ media\video\intro.mp4"},
        "image": {"images/logo.png": r"G:\GZ media\art\logo.png"},
        "audio_levels": {"audio/idx0001.wav": 4},
    })
    media = tmp_path / "moved media"
    for rel in ("audio/roar.wav", "video/intro.mp4"):
        p = media.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"media")

    with web_app(tmp_path / "ui", mfr="stern") as w:
        logs, reloads = [], []
        monkeypatch.setattr(w.window, "append_log",
                            lambda text, level="info", *a, **k:
                            logs.append((text, level)))
        monkeypatch.setattr(w.window, "reload_assets_tabs",
                            lambda: reloads.append(1))
        monkeypatch.setattr(w.app, "_project_folder", lambda: str(proj))
        yield SimpleNamespace(w=w, proj=proj, media=media, logs=logs,
                              reloads=reloads)
        w.call("shellx.relink_close")


def _sidecar(proj):
    with open(os.path.join(str(proj), staged_changes.SIDE_CAR),
              encoding="utf-8") as fh:
        return json.load(fh)


def _state(m):
    return m.w.state("shellx")["relink"]


def _text(st):
    return " || ".join([st.get("head") or "", st.get("status") or ""])


def _search(m, root):
    m.w.call("shellx.relink_set_root", root)
    ok = m.w.call("shellx.relink_search")
    if ok:
        assert _until(m.w, lambda: not _state(m)["busy"])
    return ok


# ---------------------------------------------------------------------------
# The window itself
# ---------------------------------------------------------------------------

def test_opening_lists_every_unreachable_file_and_where_it_was(moved):
    st = moved.w.call("shellx.relink_open", str(moved.proj))
    assert st is not None
    text = _text(st)
    # 3 files (the shared clip counts once), out of 3 recorded.
    assert "3 of this project's 3 replacement file(s) are not on this PC" \
        in text
    assert r"Last seen in:  G:\GZ media" in text
    assert len(st["rows"]) == 3
    # The folder they were last seen in is pre-filled, ready to be replaced.
    assert st["root"] == r"G:\GZ media"


def test_search_then_relink_repoints_every_slot(moved):
    moved.w.call("shellx.relink_open", str(moved.proj))
    assert _search(moved, str(moved.media)) is True

    st = _state(moved)
    assert st["apply_label"] == "Relink 2 file(s)"
    assert st["can_apply"] is True
    assert "Found 2 of 3 file(s)" in st["status"]
    assert "covering 3 slot(s)" in st["status"]
    # Nothing written yet — the preview is a preview.
    assert _sidecar(moved.proj)["video"]["video/intro.mov"] \
        == r"G:\GZ media\video\intro.mp4"

    assert moved.w.call("shellx.relink_apply") is True
    data = _sidecar(moved.proj)
    assert data["audio"] == {
        "audio/idx0001.wav": os.path.join(str(moved.media), "audio",
                                          "roar.wav"),
        "audio/idx0417.wav": os.path.join(str(moved.media), "audio",
                                          "roar.wav")}
    assert data["video"]["video/intro.mov"] == os.path.join(
        str(moved.media), "video", "intro.mp4")
    # The image nobody could find is untouched, and per-slot state survives.
    assert data["image"]["images/logo.png"] == r"G:\GZ media\art\logo.png"
    assert data["audio_levels"] == {"audio/idx0001.wav": 4}
    # The Replace tabs were told to re-scan, and the log says what happened.
    assert moved.reloads == [1]
    assert any("Relinked 2 replacement file(s) across 3 slot(s)" in t
               for t, _lvl in moved.logs)
    # …and the project's own history recorded it.
    with open(os.path.join(str(moved.proj), ".history.log"),
              encoding="utf-8") as fh:
        hist = fh.read()
    assert "Relinked 2 replacement file(s)" in hist


def test_after_relinking_the_window_relists_what_is_still_missing(moved):
    moved.w.call("shellx.relink_open", str(moved.proj))
    _search(moved, str(moved.media))
    moved.w.call("shellx.relink_apply")

    st = _state(moved)
    assert "1 of this project's 3 replacement file(s) are not on this PC" \
        in _text(st)
    assert st["can_apply"] is False


def test_a_project_with_no_recorded_replacements_says_so(moved, tmp_path):
    empty = tmp_path / "fresh"
    empty.mkdir()
    assert moved.w.call("shellx.relink_open", str(empty)) is None
    assert _state(moved) is None
    assert "no recorded replacements" in moved.w.asked[-1]["message"]


def test_search_without_a_folder_asks_for_one_and_writes_nothing(moved):
    moved.w.call("shellx.relink_open", str(moved.proj))
    assert _search(moved, r"G:\not a folder on this pc") is False
    assert "Pick the folder" in moved.w.asked[-1]["message"]
    assert _sidecar(moved.proj)["video"]["video/intro.mov"] \
        == r"G:\GZ media\video\intro.mp4"


# ---------------------------------------------------------------------------
# The menu entry that reaches it
# ---------------------------------------------------------------------------

def test_project_menu_carries_relink_and_fires_the_callback(tmp_path,
                                                            monkeypatch):
    """Project ▾ → "Relink moved files…" calls back ``on_relink_project``,
    which opens the page's Relink window."""
    with web_app(tmp_path, mfr="stern") as w:
        opened = []
        real = w.ctx.bus.publish

        def _publish(event, **data):
            if event == "open_dialog":
                opened.append(data.get("name"))
            return real(event, **data)
        monkeypatch.setattr(w.ctx.bus, "publish", _publish)
        assert "on_relink_project" in w.window.cb
        w.call("ui.call_back", "on_relink_project")
        assert opened == ["project_relink"]
