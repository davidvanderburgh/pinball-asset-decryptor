"""Guards for feedback batch 16, on the web Replace tabs.

Covers the change-state ("Show") filters and the video Export CSV holding
every slot whatever the view is filtered to.
"""

import csv
import os

from tests.test_webui_audio import _open, _project, _wait, _wav
from tests.test_webui_video import _mine, _scan
from tests.test_webui_video import _project as _video_project
from tests.test_webui_video import _wait as _video_wait
from tests.webui_harness import web_app

A = "audio/idx0001 - Jackpot.wav"
B = "audio/idx0002.wav"
C = "audio/idx0003 - music loop.wav"


def _rows(w):
    return {r["k"] for r in w.state("audio")["rows"]}


def _pick(w, tmp_path, rel):
    rep = str(tmp_path / "mine" / "rep.wav")
    if not os.path.isfile(rep):
        _wav(rep, seconds=1.0)
    w.answers.append(rep)
    assert w.call("audio.choose", rel) is True


# ---- change-state filter (a tester: show only modified files) -------------

def test_audio_change_filter_filters_the_list(tmp_path):
    folder = _project(tmp_path)
    # C is changed on disk (no pick): it differs from the extract baseline
    _wav(os.path.join(folder, "audio", "idx0003 - music loop.wav"),
         seconds=0.9, amp=900)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert _wait(w, lambda: {r["k"]: r for r in w.state("audio")["rows"]}
                     [C]["t"] == "ondisk"), w.state("audio")["rows"]
        _pick(w, tmp_path, B)
        assert _rows(w) == {A, B, C}

        w.call("audio.set_show", "Changed")
        assert _rows(w) == {B, C}, \
            "Changed must keep BOTH a pending pick and a changed-on-disk row"

        # Unchanged is its exact complement, so the two views together are
        # always the whole folder (batch 28: "if I could select unchanged, I
        # could then filter out the ones I have already dealt with").
        w.call("audio.set_show", "Unchanged")
        assert _rows(w) == {A}
        w.call("audio.set_show", "All")
        assert _rows(w) == {A, B, C}


def test_change_filter_does_not_hide_the_total_count(tmp_path):
    """The status line still reports the real total, with "(N shown)" so a
    filtered view can't be mistaken for the whole card."""
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        _pick(w, tmp_path, B)
        w.call("audio.set_show", "Changed")
        status = w.state("audio")["status"]
        assert "1 of 3 slots changed" in status and "1 shown" in status
        w.call("audio.set_show", "All")


# ---- video Export CSV (mirrors audio) ------------------------------------

def test_video_export_csv_writes_every_slot(tmp_path):
    proj = _video_project(tmp_path)
    # boss.mp4 differs from the extract baseline: changed on disk
    (proj / "video" / "sub" / "boss.mp4").write_bytes(b"\2" * 64)
    mine = _mine(tmp_path)
    out = tmp_path / "out" / "video_slots.csv"
    out.parent.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _video_wait(w, lambda s: "still checking" not in s["status"])
        w.answers.append(str(mine))
        assert w.call("video.choose", "video/intro.mp4") is True
        # Filter the view down: the CSV must still hold EVERY slot.
        w.call("video.set_change_filter", "Changed")
        w.answers.append(str(out))
        assert w.call("video.export_csv") is True

    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "Original Video"
    assert [r[0] for r in rows[1:]] == ["video/attract.mp4",
                                        "video/intro.mp4",
                                        "video/sub/boss.mp4"]
    # Column order is part of the contract: index by the header rather than
    # by a literal, so adding a column (batch 22 inserted "Convert" before
    # "Changed On Disk") can't silently shift what these assertions read.
    col = {name: i for i, name in enumerate(rows[0])}
    by = {r[0]: r for r in rows[1:]}
    assert by["video/intro.mp4"][col["Replacement"]] == str(mine)
    assert by["video/sub/boss.mp4"][col["Changed On Disk"]] == "yes"
    # A slot with no replacement has nothing to convert.
    assert by["video/sub/boss.mp4"][col["Convert"]] == ""
