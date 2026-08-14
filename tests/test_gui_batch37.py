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

Plus two Write-tab asks: sortable columns and a CSV export, so two projects
that disagree about their change count can actually be compared.
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
