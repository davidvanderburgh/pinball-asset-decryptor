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
"""

import os
import zipfile

import pytest

from pinball_decryptor.core import modpack
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.gui.main_window import MainWindow
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)


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
    assert MainWindow._video_playability_conflict(
        _slot60(), "/picks/new.mov",
        "/stock/JUKEBOX_LOOP3.mov") is None


def test_without_a_stock_copy_the_slot_itself_is_still_the_reference(
        monkeypatch):
    """No .orig snapshot (a project older than snapshots): fall back to the
    clip in the slot rather than judging nothing."""
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda p: _info(fps=30.0))
    why = MainWindow._video_playability_conflict(_slot60(), "/picks/new.mov")
    assert "60 fps" in why and "stock" not in why


def test_a_pick_the_stock_clip_also_rejects_is_still_rejected(monkeypatch):
    """The gate is not being loosened — only re-pointed at real evidence."""
    probes = {"/stock/JUKEBOX_LOOP3.mov": _info(w=1360, h=768),
              "/picks/small.mov": _info(w=640, h=360)}
    monkeypatch.setattr("pinball_decryptor.core.video.detect_video_info",
                        lambda p: probes.get(p))
    why = MainWindow._video_playability_conflict(
        _slot60(), "/picks/small.mov", "/stock/JUKEBOX_LOOP3.mov")
    assert "640x360" in why and "stock clip" in why


# ---------------------------------------------------------------------------
# GUI-backed halves.
# ---------------------------------------------------------------------------

pytestmark_gui = pytest.mark.skipif(not HAS_DISPLAY,
                                    reason="no Tk display available")


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update()
    app.root.update()
    return app.window


@pytest.mark.gui
@pytestmark_gui
def test_a_dragged_column_stops_stretching_so_ttk_cannot_take_it_back(app):
    """ttk redistributes the difference between the total column width and the
    widget across every stretchy column on the next layout pass — which is
    what snapped his drag straight back."""
    w = _stern(app)
    tree = w._audio_tree
    tree.column("#0", width=150)
    assert str(tree.column("#0", "stretch")) in ("1", "True")
    # A press on the separator, a wider column, a release: a real drag.
    w._tree_drag_widths["audio"] = {c: int(tree.column(c, "width"))
                                    for c in ("#0", "len", "fmt", "rep",
                                              "loop", "keep", "type")}
    tree.column("#0", width=420)
    w._save_tree_columns(tree, "audio",
                         ("#0", "len", "fmt", "rep", "loop", "keep", "type"))
    assert w._saved_column_widths["audio"]["#0"] == 420
    assert str(tree.column("#0", "stretch")) in ("0", "False")


@pytest.mark.gui
@pytestmark_gui
def test_a_row_click_is_not_a_resize(app):
    """Every click fires ButtonRelease.  Recording widths on all of them wrote
    a width for every column the first time the user selected a row, which
    then froze fit-to-content sizing for the whole tree."""
    w = _stern(app)
    w._saved_column_widths.pop("audio", None)
    w._tree_drag_widths["audio"] = None          # press was on a cell
    w._audio_tree.column("#0", width=333)
    w._save_tree_columns(w._audio_tree, "audio", ("#0", "len"))
    assert "audio" not in w._saved_column_widths


@pytest.mark.gui
@pytestmark_gui
def test_the_wrong_format_callout_does_not_eat_the_options_row(app,
                                                               monkeypatch):
    """The notebook's pane height is pinned to the tab's height as it was when
    the tab was selected, so the callout packed in afterwards left the options
    row under it with no space at all — it vanished rather than overflowing."""
    w = _stern(app)
    w._notebook.select(w._tab_video)
    for _ in range(4):
        app.root.update()
        app.root.update_idletasks()
    pinned_before = int(w._notebook.cget("height"))
    # Drive the real callout path, not a bare pack().
    monkeypatch.setattr(w, "_slot_unplayable",
                        lambda _s: "is ProRes and the machine plays H.264")
    w._video_slots_by_rel = {"video/a.mov": object()}
    w._video_current_rel = "video/a.mov"
    w._video_update_preview_note("video/a.mov")
    for _ in range(4):
        app.root.update()
        app.root.update_idletasks()
    assert w._video_preview_note.winfo_ismapped()
    assert int(w._notebook.cget("height")) > pinned_before
    assert w._video_opts_row.winfo_ismapped()
    assert w._video_no_conversion_cb.winfo_ismapped()


@pytest.mark.gui
@pytestmark_gui
def test_the_write_list_sorts_and_returns_to_scan_order(app):
    """"I want to compare the two apps and sort by type but there is no
    sorting.  Can sorting be added to this screen?\""""
    w = _stern(app)
    w._write_preview_scan_id = 7
    w._clear_write_preview_rows()
    w._write_preview_tree.delete(*w._write_preview_tree.get_children())
    for rel, ext, status in (("video/b.mov", "mov", "Pending (Replace Video)"),
                             ("audio/a.wav", "wav", "Modified"),
                             ("images/c.png", "png", "Modified")):
        w._add_write_preview_row(rel, ext, status, 7)

    def _names():
        return [w._write_preview_tree.item(i, "text")
                for i in w._write_preview_tree.get_children()]

    assert _names() == ["video/b.mov", "audio/a.wav", "images/c.png"]
    w._sort_click("_write_sort", "type", False,          # by type, ascending
                  w._refresh_write_preview_list, True)
    assert _names() == ["video/b.mov", "images/c.png", "audio/a.wav"]
    w._sort_click("_write_sort", "type", False,          # descending
                  w._refresh_write_preview_list, True)
    assert _names() == ["audio/a.wav", "images/c.png", "video/b.mov"]
    w._sort_click("_write_sort", "type", False,          # back to scan order
                  w._refresh_write_preview_list, True)
    assert _names() == ["video/b.mov", "audio/a.wav", "images/c.png"]


@pytest.mark.gui
@pytestmark_gui
def test_the_write_list_exports_as_csv(app, tmp_path, monkeypatch):
    """"I then thought maybe I could export a file and compare but that does
    not exist.\""""
    import pinball_decryptor.gui.main_window as mw
    w = _stern(app)
    w._write_preview_scan_id = 9
    w._clear_write_preview_rows()
    w._write_preview_tree.delete(*w._write_preview_tree.get_children())
    w._write_sort = (None, False)
    w._add_write_preview_row("audio/a.wav", "wav", "Modified", 9)
    w._add_write_preview_row("video/b.mov", "mov", "Pending (Replace Video)", 9)
    out = tmp_path / "changes.csv"
    monkeypatch.setattr(mw.filedialog, "asksaveasfilename",
                        lambda *a, **k: str(out))
    w._write_export_csv()
    text = out.read_text(encoding="utf-8-sig")
    assert "File,Type,Status" in text
    assert "audio/a.wav,wav,Modified" in text
    assert "video/b.mov,mov,Pending (Replace Video)" in text


@pytest.mark.gui
@pytestmark_gui
def test_the_two_preview_boxes_no_longer_read_identically(app, tmp_path):
    """With a stock snapshot on the left and the folder's own file on the
    right, both panes wore the slot's name and nothing else — "the two preview
    boxes have the same file name which does not seem correct\"."""
    from pinball_decryptor.core import staged_originals
    from pinball_decryptor.core.audio_slots import AudioSlot
    w = _stern(app)
    rel = "audio/00m44s895 - idx0172 - Song Remains The Same Snippet.wav"
    folder = tmp_path / "ex"
    (folder / "audio").mkdir(parents=True)
    (folder / rel).write_bytes(b"RIFFmodified")
    snap = folder / staged_originals.ORIG_DIR / rel
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_bytes(b"RIFFstock")
    w._audio_scan_dir = str(folder)
    w._audio_slots = [AudioSlot(rel_path=rel, abs_path=str(folder / rel),
                                ext=".wav", info=None, size=12)]
    w._audio_slots_by_rel = {rel: w._audio_slots[0]}
    w._audio_assignments = {}
    w._audio_changed_on_disk = {rel}
    w._audio_load_track(rel)
    left = w._audio_pane_orig.title_var.get()
    right = w._audio_pane_rep.title_var.get()
    assert left != right
    assert left.startswith("Original (stock)")
    assert right.startswith("Replacement (your file)")


# ---------------------------------------------------------------------------
# 3. "Use my files as-is", per clip.
# ---------------------------------------------------------------------------

def _fake_stage(store):
    def _stage(slot, rep, trim_to_length=False, no_conversion=False,
               cancel_cb=None, byte_budget=None):
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


@pytest.mark.gui
@pytestmark_gui
def test_the_per_clip_setting_wins_over_the_box_and_is_remembered(app,
                                                                 tmp_path):
    from pinball_decryptor.core import staged_changes
    w = _stern(app)
    rel = "video/JUKEBOX_LOOP3.mov"
    folder = tmp_path / "ex"
    folder.mkdir()
    w.write_assets_var.set(str(folder))
    w._video_scan_dir = str(folder)
    w._video_slots_by_rel = {rel: _slot60()}
    w._video_slots = [w._video_slots_by_rel[rel]]
    w._video_assignments = {rel: str(tmp_path / "mine.mov")}
    w._video_asis_flags = {}
    w.video_no_conversion_var.set(False)
    assert w._video_asis_for(rel) is False

    w._video_set_asis(rel, True)
    assert w._video_asis_for(rel) is True
    assert staged_changes.load(str(folder))["video_asis_slots"] == {rel: True}

    # Clearing it hands the row back to the box.
    w._video_set_asis(rel, None)
    assert w._video_asis_for(rel) is False
    w.video_no_conversion_var.set(True)
    assert w._video_asis_for(rel) is True


@pytest.mark.gui
@pytestmark_gui
def test_an_overridden_row_is_marked_in_the_convert_column(app):
    """One row set apart from the box has to be findable among a hundred."""
    w = _stern(app)
    rel = "video/JUKEBOX_LOOP3.mov"
    w._video_slots_by_rel = {rel: _slot60()}
    w._video_asis_flags = {}
    w._video_conv_cache[w._video_conv_key(rel, "C:/x/mine.mov")] = "As-is"
    assert w._video_conv_cell(rel, "C:/x/mine.mov") == "As-is"
    w._video_asis_flags[rel] = True
    w._video_conv_cache[w._video_conv_key(rel, "C:/x/mine.mov")] = "As-is"
    assert w._video_conv_cell(rel, "C:/x/mine.mov") == "• As-is"


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


@pytest.mark.gui
@pytestmark_gui
def test_changed_on_disk_names_the_file_it_was_changed_with(app, tmp_path):
    from pinball_decryptor.core import staged_changes
    w = _stern(app)
    rel = "audio/00m44s895 - idx0172 - Song Remains The Same Snippet.wav"
    folder = tmp_path / "ex"
    folder.mkdir()
    staged_changes.save(str(folder),
                        {"replacement_names": {rel: "Song Remains.wav"}})
    w._load_staged_changes(str(folder))
    w._audio_scan_dir = str(folder)
    assert w._changed_on_disk_cell("audio", rel) == \
        "✓ changed on disk (Song Remains.wav)"
    # A slot with nothing remembered still reads the way it always did.
    assert w._changed_on_disk_cell("audio", "audio/other.wav") == \
        "✓ changed on disk"


# ---------------------------------------------------------------------------
# 6. "Play replacements" applies to the play button you press, not only to
#    the rows the sequential run steps onto.
# ---------------------------------------------------------------------------

@pytest.mark.gui
@pytestmark_gui
def test_play_replacements_redirects_the_original_play_button(app,
                                                              monkeypatch):
    """"If you select 'play replacements' but click start on the left original
    audio file, it plays the original and not the replacement."."""
    w = _stern(app)
    w._audio_current_rel = "audio/a.wav"
    monkeypatch.setattr(w, "_audio_rep_available", lambda _rel: True)
    started = []
    w._audio_pane_rep.path = "C:/x/mine.wav"
    monkeypatch.setattr(w._audio_pane_rep, "start_playback",
                        lambda pos=0.0: started.append(pos))

    w.audio_play_subst_var.set(False)
    assert w._audio_play_intercept() is False    # off: the button means stock
    w.audio_play_subst_var.set(True)
    assert w._audio_play_intercept() is True
    assert started == [0.0]


@pytest.mark.gui
@pytestmark_gui
def test_a_row_with_no_replacement_still_plays_its_original(app, monkeypatch):
    """Stock is what the card plays there, so nothing is redirected."""
    w = _stern(app)
    w._audio_current_rel = "audio/a.wav"
    w.audio_play_subst_var.set(True)
    monkeypatch.setattr(w, "_audio_rep_available", lambda _rel: False)
    assert w._audio_play_intercept() is False
