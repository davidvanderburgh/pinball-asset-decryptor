"""PAD-812 (a field report): the Video tab's compare report, a CSV with a row for every
replacement, random clip and mode's row of a shared clip beside the game's own clip it stands
in for - the lengths to the hundredth of a second first.

The rows are checked on stubbed probes (the length rules), on real clips ffmpeg makes (the
tab's report end to end: stock read from the pristine snapshot, Trim / pad, as-is, random
clips) and on a stubbed Godzilla reading (the shared clip's mode rows)."""

import csv
import os
import subprocess
import time

import pytest

from pinball_decryptor.core import video_compare_report as VR
from pinball_decryptor.core.video import VideoInfo, find_ffmpeg
from tests.test_pad444_clip_modes import FOLLOW, SHARED, SOLO, OTHER, MAIN, _ready, _stub_reading
from tests.test_webui_video import _project, _scan
from tests.webui_harness import web_app


def _col(row, name):
    return row[VR.HEADER.index(name)]


def _info(dur, w=1360, h=768, fps=30.0, audio=False):
    return VideoInfo("x", vcodec="h264", width=w, height=h, fps=fps, duration=dur,
                     has_audio=audio, audio_rate=48000 if audio else 0,
                     audio_channels=2 if audio else 0)


def _entry(tmp_path, **kw):
    stock = tmp_path / "stock.mp4"
    rep = tmp_path / "rep.mp4"
    stock.write_bytes(b"\0" * 2_000_000)
    rep.write_bytes(b"\0" * 500_000)
    base = dict(slot="video/a.mp4", what="Replacement", stock_rel="video/a.mp4",
                stock_path=str(stock), file=str(rep))
    base.update(kw)
    return VR.Entry(**base)


def test_lengths_are_seconds_to_two_decimals_with_the_difference_and_the_length_on_the_card(tmp_path):
    infos = {"stock.mp4": _info(12.345), "rep.mp4": _info(14.0, 1920, 1080, 29.97, True)}
    probe = lambda p: infos.get(os.path.basename(p))        # noqa: E731
    row = VR.row(_entry(tmp_path, after=VR.AFTER_STOCK), probe)
    assert _col(row, "Stock length (s)") == "12.35" and _col(row, "Replacement length (s)") == "14.00"
    assert _col(row, "Difference (s)") == "+1.65"
    assert _col(row, "Length after Write (s)") == "12.35"
    assert _col(row, "Stock resolution") == "1360x768" and _col(row, "Replacement resolution") == "1920x1080"
    assert _col(row, "Stock fps") == "30" and _col(row, "Replacement fps") == "29.97"
    assert _col(row, "Stock frames") == "370" and _col(row, "Replacement frames") == "420"
    assert _col(row, "Stock audio") == "none" and _col(row, "Replacement audio") == "48 kHz Stereo"
    assert _col(row, "Stock size (MB)") == "2.00" and _col(row, "Replacement size (MB)") == "0.50"
    notes = _col(row, "Notes")
    assert "cut on Write to the stock length" in notes and "scaled to 1360x768" in notes
    assert "converted to 30 fps" in notes
    # its own length: kept; a typed length: that; as it is: kept, nothing converted
    assert _col(VR.row(_entry(tmp_path), probe), "Length after Write (s)") == "14.00"
    assert _col(VR.row(_entry(tmp_path, after=9.5), probe), "Length after Write (s)") == "9.50"
    asis = VR.row(_entry(tmp_path, asis=True), probe)
    assert _col(asis, "Length after Write (s)") == "14.00"
    assert _col(asis, "Notes") == "used as it is (no conversion)"
    # shorter: padded, and a match reads 0.00
    infos["rep.mp4"] = _info(10.0)
    row = VR.row(_entry(tmp_path, after=VR.AFTER_STOCK), probe)
    assert _col(row, "Difference (s)") == "-2.35" and "padded on Write" in _col(row, "Notes")
    infos["rep.mp4"] = _info(12.349)
    assert _col(VR.row(_entry(tmp_path), probe), "Difference (s)") == "0.00"


def test_a_file_gone_or_unreadable_still_gets_its_row(tmp_path):
    e = _entry(tmp_path, file=str(tmp_path / "gone.mp4"))
    row = VR.row(e, lambda p: _info(5.0) if p.endswith("stock.mp4") else None)
    assert _col(row, "Stock length (s)") == "5.00" and _col(row, "Replacement length (s)") == ""
    assert _col(row, "Difference (s)") == "" and "replacement file not found" in _col(row, "Notes")
    out = tmp_path / "r.csv"
    assert VR.write(str(out), [e], probe=lambda p: None) == 1
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0] == VR.HEADER and "stock clip could not be read" in rows[1][-1]


# ---- the tab, on real clips ------------------------------------------------------------------
def _clip(path, secs, size="320x240", fps=30):
    ff = find_ffmpeg()
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=%s:rate=%d:duration=%s" % (size, fps, secs),
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)], check=True)
    return path


def _report(w, out, timeout=60):
    assert w.call("video.export_compare", str(out)) is True
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if not w.state("video").get("report_busy") and out.exists():
            return list(csv.reader(out.open(encoding="utf-8-sig")))
        time.sleep(0.1)
    raise AssertionError("no report")


@pytest.mark.skipif(not find_ffmpeg(), reason="needs ffmpeg")
def test_the_tab_reports_every_replacement_and_random_clip_against_the_stock_clip(tmp_path):
    proj = _project(tmp_path)
    # attract was written once already: the slot holds a replacement, the snapshot the stock clip
    _clip(proj / "video/attract.mp4", 4)
    _clip(proj / ".orig/video/attract.mp4", 2)
    _clip(proj / "video/intro.mp4", 1.5, "640x360")
    mine = _clip(tmp_path / "mine/mine.mp4", 3.6, "640x360", 25)
    r1 = _clip(tmp_path / "mine/r1.mp4", 1.2)
    r2 = _clip(tmp_path / "mine/r2.mp4", 2.0)
    out = tmp_path / "compare.csv"
    with web_app(tmp_path, mfr="ap") as w:
        w.call("video.export_compare", str(out))
        assert "the video table is empty" in w.asked[-1]["message"]
        _scan(w, proj)
        assert w.call("video.export_compare", str(out)) is False
        assert "nothing to compare" in w.asked[-1]["message"]
        w.answers.append(str(mine))
        w.call("video.choose", "video/attract.mp4")
        w.answers.append(str(mine))
        w.call("video.choose", "video/intro.mp4")
        tab = w.window.service("video")
        w.run(lambda: tab._variants.update({"video/intro.mp4": [str(r1), str(r2)]}))
        w.call("video.set_trim", True)
        w.call("video.set_asis", "video/intro.mp4", True)
        rows = _report(w, out)
    assert rows[0] == VR.HEADER
    body = {(r[0], r[2]): r for r in rows[1:]}
    assert list(body) == [("video/attract.mp4", "Replacement"),
                          ("video/intro.mp4", "Replacement, random clip 1 of 3"),
                          ("video/intro.mp4", "Random clip 2 of 3"),
                          ("video/intro.mp4", "Random clip 3 of 3")]
    a = body[("video/attract.mp4", "Replacement")]
    # the stock clip is the snapshot (2 s), not the 4 s clip the last build put in the slot
    assert _col(a, "Stock length (s)") == "2.00" and _col(a, "Replacement length (s)") == "3.60"
    assert _col(a, "Difference (s)") == "+1.60" and _col(a, "Length after Write (s)") == "2.00"
    assert _col(a, "Stock fps") == "30" and _col(a, "Replacement fps") == "25"
    assert _col(a, "Stock frames") == "60" and _col(a, "Replacement resolution") == "640x360"
    assert "cut on Write" in _col(a, "Notes")
    v = body[("video/intro.mp4", "Random clip 2 of 3")]
    assert _col(v, "Replacement file") == str(r1)
    assert _col(v, "Stock length (s)") == "1.50" and _col(v, "Replacement length (s)") == "1.20"
    assert _col(v, "Difference (s)") == "-0.30"
    # as it is: nothing trims it
    assert _col(v, "Length after Write (s)") == "1.20" and "no conversion" in _col(v, "Notes")


def test_a_clip_two_modes_share_reports_each_modes_row(tmp_path, monkeypatch):
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER, MAIN))
    _stub_reading(monkeypatch, tmp_path, proj)
    mine = tmp_path / "battra.mp4"
    mine.write_bytes(b"\1" * 40)
    out = tmp_path / "compare.csv"
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _ready(w)
        w.answers.append(str(mine))
        assert w.call("video.choose", SHARED) is True
        rows = _report(w, out)
        got = [(r[0], r[1], r[2], r[3], r[4]) for r in rows[1:]]
        assert got == [
            (SHARED, "Battle vs Ghidorah and Gigan", "Replacement", SHARED, str(mine)),
            (FOLLOW, "Battle vs Gigan", "Same clip as Battle vs Ghidorah and Gigan: replacement",
             SHARED, str(mine))]
        # its own replacement makes it a clip of its own: still measured against the shared clip
        mine2 = tmp_path / "mothra.mp4"
        mine2.write_bytes(b"\2" * 40)
        w.answers.append(str(mine2))
        assert w.call("video.choose", FOLLOW) is True
        _ready(w, lambda st: True)
        out.unlink()
        rows = _report(w, out)
        got = [(r[0], r[1], r[2], r[3], r[4]) for r in rows[1:]]
        assert got == [
            (SHARED, "Battle vs Ghidorah and Gigan", "Replacement", SHARED, str(mine)),
            (FOLLOW, "Battle vs Gigan", "Replacement (Battle vs Gigan's own clip)", SHARED,
             str(mine2))]
