"""Feedback batch 37 — a tester's evening on a fresh Led Zeppelin extract.

Six separate reports, all from the same session:

* the import told him "8 of the pack's 232 file(s) ... will be skipped" and
  named none of them ("I would be interested in know what those files were");
* the import-complete box said the tabs were re-scanning, but every scan line
  had already gone into the log ABOVE the import's own "completed" line, so
  it read as a promise nothing kept;
* dragging a column wider showed the new width and snapped straight back
  ("I seem to get this with a lot of these columns across all tabs");
* ticking "Use my files as-is" rejected his 30 fps clips for "this slot's
  clip is 60 fps" — the 60 fps being his own earlier import sitting in the
  slot, not anything the card asked for;
* the red WRONG FORMAT callout that appeared with it took the whole options
  row off the screen ("the option buttons disappeared");
* both audio preview boxes carried the same file name.

Plus four asks: sortable Write-tab columns and a CSV export (so two projects
that disagree about their change count can be compared), a per-clip answer to
"use my files as-is" ("you can't mix and match. Any reason why?"), a log per
project instead of one shared file, and the ▶ under Original honouring "Play
replacements" the way the rest of the run already did.

The Write list's sort and CSV export, the two preview boxes' names and the
per-clip as-is row are covered by the web tabs' own tests
(test_webui_write.py, test_webui_audio.py, test_webui_video.py); the
changed-on-disk cell and the play redirect drive the web Audio tab
(webui/tabs/audio.py) through tests/webui_harness.py.
"""

import os
import zipfile

from pinball_decryptor.core import modpack
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.webui.video_helpers import playability_conflict
from tests.webui_harness import web_app


# ---------------------------------------------------------------------------
# 1. The import names every file it is going to skip.
# ---------------------------------------------------------------------------

def _pack(tmp_path, members):
    zpath = tmp_path / "pack.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(modpack.MANIFEST_NAME, '{"source_name": "other.raw"}')
        for name in members:
            zf.writestr(name, b"x")
    return str(zpath)


def _extract(tmp_path, baseline):
    folder = tmp_path / "extract"
    (folder / "audio").mkdir(parents=True)
    for rel in baseline:
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    (folder / ".checksums.md5").write_text(
        "\n".join("%s\t%s" % (rel, "0" * 32) for rel in baseline),
        encoding="utf-8")
    return str(folder)


def test_every_skipped_file_is_named(tmp_path):
    """The count on its own sent him hunting through the folder afterwards."""
    folder = _extract(tmp_path, ["audio/keep.wav"])
    plan = modpack.inspect_mod_pack(
        _pack(tmp_path, ["audio/keep.wav", "video/Prem.mov",
                         "audio/three.wav"]), folder)
    rows = modpack.skipped_rows(plan)
    assert [name for name, _why in rows] == ["audio/three.wav",
                                             "video/Prem.mov"]
    assert all("no slot on this card has that name" == why
               for _n, why in rows)


def test_a_stray_left_by_an_earlier_import_says_it_is_being_removed(tmp_path):
    """Two different outcomes hide behind one count: a file still only in the
    zip, and one an earlier import already dropped into the folder."""
    folder = _extract(tmp_path, ["audio/keep.wav"])
    # A previous import of this same pack left the stray behind.
    os.makedirs(os.path.join(folder, "video"), exist_ok=True)
    with open(os.path.join(folder, "video", "Prem.mov"), "wb") as f:
        f.write(b"x")
    plan = modpack.inspect_mod_pack(
        _pack(tmp_path, ["audio/keep.wav", "video/Prem.mov"]), folder)
    why = dict(modpack.skipped_rows(plan))["video/Prem.mov"]
    assert "will be removed" in why


def test_the_import_log_carries_one_line_per_skip(tmp_path):
    """"Also maybe log each skip as well?" — his words."""
    folder = _extract(tmp_path, ["audio/keep.wav"])
    zpath = _pack(tmp_path, ["audio/keep.wav", "video/Prem.mov",
                             "video/Premv.mov"])
    lines = []
    modpack.import_mod_pack(zpath, folder,
                            log_cb=lambda t, lvl="info": lines.append(t))
    assert any("skipped video/Prem.mov" in t for t in lines)
    assert any("skipped video/Premv.mov" in t for t in lines)


# ---------------------------------------------------------------------------
# 2. The as-is gate measures against the STOCK clip, not the modded one.
# ---------------------------------------------------------------------------

def _info(w=1360, h=768, fps=30.0, codec="h264", pix_fmt="yuv420p"):
    return VideoInfo(path="x.mov", vcodec=codec, width=w, height=h, fps=fps,
                     duration=25.0, pix_fmt=pix_fmt, container="mov")


def _slot60():
    """The slot as it sits after his earlier import: his own 60 fps file."""
    return VideoSlot(rel_path="video/JUKEBOX_LOOP3.mov",
                     abs_path="/assets/video/JUKEBOX_LOOP3.mov", ext=".mov",
                     info=_info(fps=60.0), size=1024)


def test_a_30fps_pick_is_judged_against_the_stock_30fps_clip(monkeypatch):
    """His actual case: the slot holds his own 60 fps import, so the check was
    measuring his file against his file and demanding 60 fps back."""
    probes = {"/stock/JUKEBOX_LOOP3.mov": _info(fps=30.0),
              "/picks/new.mov": _info(fps=30.0)}
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda p: probes.get(p))
    assert playability_conflict(
        _slot60(), "/picks/new.mov",
        "/stock/JUKEBOX_LOOP3.mov") is None


def test_without_a_stock_copy_the_slot_itself_is_still_the_reference(
        monkeypatch):
    """No .orig snapshot (a project older than snapshots): fall back to the
    clip in the slot rather than judging nothing."""
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda p: _info(fps=30.0))
    why = playability_conflict(_slot60(), "/picks/new.mov")
    assert "60 fps" in why and "stock" not in why


def test_a_pick_the_stock_clip_also_rejects_is_still_rejected(monkeypatch):
    """The gate is not being loosened — only re-pointed at real evidence."""
    probes = {"/stock/JUKEBOX_LOOP3.mov": _info(w=1360, h=768),
              "/picks/small.mov": _info(w=640, h=360)}
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda p: probes.get(p))
    why = playability_conflict(
        _slot60(), "/picks/small.mov", "/stock/JUKEBOX_LOOP3.mov")
    assert "640x360" in why and "stock clip" in why


# ---------------------------------------------------------------------------
# 3. "Use my files as-is", per clip.
# ---------------------------------------------------------------------------

def _fake_stage(store):
    def _stage(slot, rep, trim_to_length=False, no_conversion=False,
               cancel_cb=None, byte_budget=None, match_bitrate=None,
               best_quality=False):
        store.append((slot.rel_path, no_conversion))
        return True, ""
    return _stage


def test_a_clip_can_go_on_as_is_in_a_project_that_converts(tmp_path,
                                                           monkeypatch):
    """The box is project-wide; one hand-encoded clip should not need the
    whole project switched over to it."""
    from pinball_decryptor.core import video_slots
    staged = []
    monkeypatch.setattr(video_slots, "stage_replacement", _fake_stage(staged))
    rels = ["video/a.mov", "video/b.mov"]
    slots = {}
    for rel in rels:
        p = tmp_path / os.path.basename(rel)
        p.write_bytes(b"x")
        slots[rel] = VideoSlot(rel_path=rel, abs_path=str(p), ext=".mov",
                               info=None, size=1)
    rep = tmp_path / "mine.mov"
    rep.write_bytes(b"y")
    video_slots.stage_replacements(
        slots, {rel: str(rep) for rel in rels}, no_conversion=False,
        asis_overrides={"video/b.mov": True})
    assert dict(staged) == {"video/a.mov": False, "video/b.mov": True}


def test_an_override_also_forces_a_conversion_the_box_would_skip(tmp_path,
                                                                 monkeypatch):
    """It goes both ways — one bad clip converted in a project that otherwise
    copies files through byte-for-byte."""
    from pinball_decryptor.core import video_slots
    staged = []
    monkeypatch.setattr(video_slots, "stage_replacement", _fake_stage(staged))
    p = tmp_path / "a.mov"
    p.write_bytes(b"x")
    rep = tmp_path / "mine.mov"
    rep.write_bytes(b"y")
    slots = {"video/a.mov": VideoSlot(rel_path="video/a.mov", abs_path=str(p),
                                      ext=".mov", info=None, size=1)}
    video_slots.stage_replacements(
        slots, {"video/a.mov": str(rep)}, no_conversion=True,
        asis_overrides={"video/a.mov": False})
    assert staged == [("video/a.mov", False)]


# ---------------------------------------------------------------------------
# 4. One log per project.
# ---------------------------------------------------------------------------

def test_each_project_gets_its_own_log(tmp_path, monkeypatch):
    """"the logs are not independent of each project but rather they are one
    large one. So if you are bouncing around projects, this could get muddy"."""
    from pinball_decryptor.core import session_log
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE",
                        str(tmp_path / "shared"))
    monkeypatch.setattr(session_log, "_project_dir", None)
    one, two = tmp_path / "redux3", tmp_path / "redux4"
    one.mkdir()
    two.mkdir()

    assert session_log.set_project(str(one), version="9.9.9") is True
    session_log.append("Audio scan finished in 1.0 s.")
    assert session_log.set_project(str(two), version="9.9.9") is True
    session_log.append("Video scan finished in 2.0 s.")

    first = (one / "logs" / "project.log").read_text(encoding="utf-8")
    second = (two / "logs" / "project.log").read_text(encoding="utf-8")
    assert "Audio scan finished" in first
    assert "Video scan finished" not in first
    assert "Video scan finished" in second
    assert "Audio scan finished" not in second
    # The shared history still has both, with a banner naming each project.
    shared = open(session_log.log_path(), encoding="utf-8").read()
    assert "Audio scan finished" in shared and "Video scan finished" in shared
    assert "----- Project: redux3" in shared
    assert "----- Project: redux4" in shared


def test_a_project_folder_that_went_away_is_not_recreated(tmp_path,
                                                          monkeypatch):
    """An unplugged NAS must not have its tree rebuilt at a stale mount."""
    from pinball_decryptor.core import session_log
    monkeypatch.setattr(session_log, "LOG_DIR_OVERRIDE",
                        str(tmp_path / "shared"))
    monkeypatch.setattr(session_log, "_project_dir", None)
    import shutil
    gone = tmp_path / "gone"
    gone.mkdir()
    session_log.set_project(str(gone))
    shutil.rmtree(gone)                          # the NAS went away
    session_log.append("still logging")          # no raise
    assert not gone.exists()
    assert "still logging" in open(session_log.log_path(),
                                   encoding="utf-8").read()


def test_the_project_log_folder_is_never_treated_as_an_asset():
    """It is the app's own file inside the user's project, like build/."""
    from pinball_decryptor.core import session_log
    from pinball_decryptor.core.checksums import NON_ASSET_DIRS
    assert session_log.PROJECT_LOG_DIR in NON_ASSET_DIRS


# ---------------------------------------------------------------------------
# 5. A pack carries the name of the file each slot was replaced with.
# ---------------------------------------------------------------------------

def test_a_pack_carries_the_replacement_names(tmp_path):
    """"when you originally put in the file it shows the actual replacement
    file name. Is there a reason that this cannot be shown here?"."""
    from pinball_decryptor.core import staged_changes
    src = tmp_path / "from"
    src.mkdir()
    staged_changes.save(str(src), {
        "audio": {"audio/idx0172.wav": "W:/mine/Song Remains.wav"},
        "replacement_names": {"audio/idx0172.wav": "Song Remains.wav"}})
    extras = modpack.project_extras(str(src))
    assert extras["replacement_names"] == {
        "audio/idx0172.wav": "Song Remains.wav"}
    dest = _extract(tmp_path, ["audio/idx0172.wav"])
    modpack.apply_extras(dest, extras)
    assert staged_changes.load(dest)["replacement_names"] == {
        "audio/idx0172.wav": "Song Remains.wav"}


def test_changed_on_disk_names_the_file_it_was_changed_with(tmp_path):
    from pinball_decryptor.core import staged_changes
    rel = "audio/00m44s895 - idx0172 - Song Remains The Same Snippet.wav"
    folder = tmp_path / "ex"
    folder.mkdir()
    staged_changes.save(str(folder),
                        {"replacement_names": {rel: "Song Remains.wav"}})
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("audio")

        def _cells():
            svc._load_staged_changes(str(folder))
            svc._scan_dir = str(folder)
            return (svc._changed_on_disk_cell(rel),
                    svc._changed_on_disk_cell("audio/other.wav"))
        named, plain = w.run(_cells)
        assert named == "✓ changed on disk (Song Remains.wav)"
        # A slot with nothing remembered still reads the way it always did.
        assert plain == "✓ changed on disk"


# ---------------------------------------------------------------------------
# 6. "Play replacements" applies to the play button you press, not only to
#    the rows the sequential run steps onto.
# ---------------------------------------------------------------------------

def _audio_with_panes(w, monkeypatch, rep_available):
    svc = w.window.service("audio")
    played = []
    monkeypatch.setattr(svc, "_rep_available", lambda _rel: rep_available)
    monkeypatch.setattr(svc, "_publish",
                        lambda name, **kw: played.append((name, kw)))

    def _set():
        svc._current_rel = "audio/a.wav"
        svc._panes["orig"]["path"] = "C:/x/stock.wav"
        svc._panes["rep"]["path"] = "C:/x/mine.wav"
    w.run(_set)
    return svc, played


def test_play_replacements_redirects_the_original_play_button(tmp_path,
                                                              monkeypatch):
    """"If you select 'play replacements' but click start on the left original
    audio file, it plays the original and not the replacement."."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, played = _audio_with_panes(w, monkeypatch, True)

        w.run(svc.audio_play_subst_var.set, False)
        assert w.run(svc._play_intercept) is False  # off: the button means stock
        assert w.call("audio.play", "orig") is True
        assert played[-1][1]["pane"] == "orig"
        w.run(svc.audio_play_subst_var.set, True)
        assert w.call("audio.play", "orig") is True
        assert played[-1][0] == "audio_play"
        assert played[-1][1]["pane"] == "rep"
        assert played[-1][1]["pos"] == 0.0


def test_a_row_with_no_replacement_still_plays_its_original(tmp_path,
                                                            monkeypatch):
    """Stock is what the card plays there, so nothing is redirected."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, played = _audio_with_panes(w, monkeypatch, False)
        w.run(svc.audio_play_subst_var.set, True)
        assert w.run(svc._play_intercept) is False
        assert w.call("audio.play", "orig") is True
        assert played[-1][1]["pane"] == "orig"
