"""PAD-163 — "Replace from folder…" and what a dropped-in stray is.

A modder converted every Godzilla clip they extracted to black and white,
deleted the extract's clips and dropped theirs in, hoping for "voila, black
and white".  Their converter wrote .mp4 for the card's .mov clips, so those rows
said "not on this card" and blamed a mod pack, and the only other way in was a
replacement pick per clip.  The Replace tabs now take a whole folder by name,
and a stray that is a slot's own file under another type says so.
"""

import os

import pytest

from pinball_decryptor.core.video_slots import VideoSlot
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk display available"),
]

CLIPS = ["Tank_Jackpot1.mov", "Rampage_P.mov", "tilt.mp4"]


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


def _project(w, tmp_path, clips=CLIPS):
    """A project folder holding *clips*, scanned onto the Video tab."""
    assets = str(tmp_path / "project")
    os.makedirs(os.path.join(assets, "video"))
    slots = []
    for name in clips:
        path = os.path.join(assets, "video", name)
        with open(path, "wb") as f:
            f.write(b"stock " + name.encode())
        slots.append(VideoSlot(rel_path="video/" + name, abs_path=path,
                               ext=os.path.splitext(name)[1], info=None,
                               size=1, probed=True))
    w.write_assets_var.set(assets)
    w._video_scan_dir = assets
    w._video_slots = slots
    w._video_slots_by_rel = {s.rel_path: s for s in slots}
    w._video_assignments = {}
    w._video_asis_flags = {}
    w._video_foreign_rels = set()
    return assets


def _bw_folder(tmp_path, names=("Tank_Jackpot1.mp4", "Rampage_P.mp4",
                                "tilt.mp4", "my_new_intro.mp4")):
    folder = str(tmp_path / "BW clips")
    os.makedirs(folder)
    for name in names:
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"bw " + name.encode())
    return folder


@pytest.fixture
def dialogs(monkeypatch):
    """Answer the folder dialog and record every message box."""
    from pinball_decryptor.gui import main_window as mw
    seen = {"folder": None, "yes": True, "boxes": []}

    def _box(kind):
        def _show(title, msg, **_kw):
            seen["boxes"].append((kind, title, msg))
            return seen["yes"] if kind == "askyesno" else None
        return _show

    monkeypatch.setattr(mw.filedialog, "askdirectory",
                        lambda **_kw: seen["folder"])
    for kind in ("askyesno", "showinfo", "showwarning"):
        monkeypatch.setattr(mw.messagebox, kind, _box(kind))
    return seen


def _logs(w, monkeypatch):
    lines = []
    monkeypatch.setattr(w, "append_log",
                        lambda text, level="info", *a, **k:
                        lines.append((level, text)))
    return lines


def test_every_replace_tab_has_the_button(app):
    w = _stern(app)
    assert set(w._from_folder_btns) == {"audio", "video", "image"}
    for btn in w._from_folder_btns.values():
        assert btn.cget("text") == "Replace from folder…"


def test_a_folder_of_converted_clips_becomes_one_pick_per_slot(
        app, tmp_path, dialogs, monkeypatch):
    w = _stern(app)
    assets = _project(w, tmp_path)
    dialogs["folder"] = folder = _bw_folder(tmp_path)
    lines = _logs(w, monkeypatch)

    w._replace_from_folder("video")

    assert w._video_assignments == {
        "video/Tank_Jackpot1.mov": os.path.join(folder, "Tank_Jackpot1.mp4"),
        "video/Rampage_P.mov": os.path.join(folder, "Rampage_P.mp4"),
        "video/tilt.mp4": os.path.join(folder, "tilt.mp4"),
    }
    [(kind, _title, msg)] = dialogs["boxes"]
    assert kind == "askyesno"
    assert "Use 3 file(s)" in msg
    assert "2 of them are a different file type" in msg
    assert "1 file(s) in the folder are left out" in msg
    # The picks are real picks: saved with the project like any other.
    from pinball_decryptor.core import staged_changes
    assert staged_changes.load(assets)["video"]["video/Rampage_P.mov"] \
        == os.path.join(folder, "Rampage_P.mp4")
    text = "\n".join(t for _l, t in lines)
    assert "picked 3 replacement(s) by name" in text
    assert "my_new_intro.mp4" in text
    # ...and the row says what it will build with.
    w._refresh_video_list()
    assert "Tank_Jackpot1.mp4" in w._video_tree.item(
        "video/Tank_Jackpot1.mov", "values")[4]


def test_no_picks_change_when_the_confirm_is_declined(
        app, tmp_path, dialogs):
    w = _stern(app)
    _project(w, tmp_path)
    w._video_assignments["video/tilt.mp4"] = "C:\\mine\\tilt.mp4"
    dialogs["folder"] = _bw_folder(tmp_path)
    dialogs["yes"] = False

    w._replace_from_folder("video")

    assert w._video_assignments == {"video/tilt.mp4": "C:\\mine\\tilt.mp4"}


def test_clips_set_to_go_on_as_is_are_converted_when_the_type_differs(
        app, tmp_path, dialogs):
    """As-is needs the slot's own file type; the one-clip picker offers to
    convert just that clip, so the folder does the same for its retyped
    clips and leaves the rest alone."""
    w = _stern(app)
    _project(w, tmp_path)
    w.video_no_conversion_var.set(True)
    dialogs["folder"] = _bw_folder(tmp_path)

    w._replace_from_folder("video")

    assert w._video_asis_flags == {"video/Tank_Jackpot1.mov": False,
                                   "video/Rampage_P.mov": False}
    assert w._video_asis_for("video/tilt.mp4") is True
    assert "set to be converted" in dialogs["boxes"][0][2]


def test_a_folder_inside_the_project_is_refused(app, tmp_path, dialogs):
    """Those files ARE the slots; pairing them with themselves (or with
    strays dropped beside them) is never what anyone wants."""
    w = _stern(app)
    assets = _project(w, tmp_path)
    dialogs["folder"] = os.path.join(assets, "video")

    w._replace_from_folder("video")

    assert w._video_assignments == {}
    assert dialogs["boxes"][0][0] == "showwarning"
    assert "part of the project folder" in dialogs["boxes"][0][2]


def test_strays_are_not_offered_as_slots(app, tmp_path, dialogs):
    """The dropped-in Tank_Jackpot1.mp4 lists as a row; a folder file of the
    same name must go to the card's clip, not to that stray."""
    w = _stern(app)
    _project(w, tmp_path, clips=CLIPS + ["Tank_Jackpot1.mp4"])
    w._video_foreign_rels = {"video/Tank_Jackpot1.mp4"}
    dialogs["folder"] = _bw_folder(tmp_path)

    w._replace_from_folder("video")

    assert "video/Tank_Jackpot1.mp4" not in w._video_assignments
    assert "video/Tank_Jackpot1.mov" in w._video_assignments


def test_nothing_named_like_a_slot_explains_the_fingerprint(
        app, tmp_path, dialogs):
    w = _stern(app)
    w._image_slots_by_rel = {
        "images/scene_textures/glyphs/radimg_512x512_a4a16c84/U+0069_i.png":
            None}
    w._image_foreign_rels = set()
    w.write_assets_var.set(str(tmp_path / "project"))
    folder = tmp_path / "silent" / "glyphs" / "radimg_512x512_bba78124"
    folder.mkdir(parents=True)
    (folder / "U+0041_A.png").write_bytes(b"png")
    dialogs["folder"] = str(tmp_path / "silent")

    w._replace_from_folder("image")

    [(kind, _title, msg)] = dialogs["boxes"]
    assert kind == "showinfo"
    assert "fingerprint" in msg
    assert "Transfer Mods to New Version" in msg


def test_no_slots_yet_says_to_scan(app, dialogs):
    w = _stern(app)
    w._audio_slots_by_rel = {}
    w._replace_from_folder("audio")
    assert dialogs["boxes"][0][0] == "showinfo"
    assert "Scan" in dialogs["boxes"][0][2]


def test_a_retyped_stray_names_the_cards_file(app, tmp_path):
    w = _stern(app)
    _project(w, tmp_path, clips=["Tank_Jackpot1.mp4"])
    stray = "video/Tank_Jackpot1.mp4"
    w._video_changed_on_disk = {stray}
    w._video_foreign_rels = {stray}
    w._video_foreign_twins = {stray: "video/Tank_Jackpot1.mov"}

    text = w._rep_pane_empty_text("video", stray, "no replacement assigned")

    assert "Tank_Jackpot1.mov" in text and "Tank_Jackpot1.mp4" in text
    assert "Replace from folder" in text
    # The card's own clip is gone from this folder, so it has to come back.
    assert "extract the card again" in text
    assert "mod pack" not in text


def test_a_retyped_stray_beside_its_slot_needs_no_new_extract(app, tmp_path):
    w = _stern(app)
    _project(w, tmp_path, clips=["Tank_Jackpot1.mov", "Tank_Jackpot1.mp4"])
    stray = "video/Tank_Jackpot1.mp4"
    w._video_changed_on_disk = {stray}
    w._video_foreign_rels = {stray}
    w._video_foreign_twins = {stray: "video/Tank_Jackpot1.mov"}

    text = w._rep_pane_empty_text("video", stray, "x")

    assert "Replace from folder" in text
    assert "extract the card again" not in text


def test_any_other_stray_mentions_copies_from_another_extract(app):
    w = _stern(app)
    stray = "images/scene_textures/glyphs/radimg_512x512_bba78124/U+02C6.png"
    w._image_changed_on_disk = {stray}
    w._image_foreign_rels = {stray}
    w._image_foreign_twins = {}

    text = w._rep_pane_empty_text("image", stray, "x")

    assert "not part of this extract" in text
    assert "different extract" in text and "fingerprint" in text
    assert "Transfer Mods" in text


def test_the_change_diff_records_the_twins_and_logs_them(
        app, tmp_path, monkeypatch):
    """End to end over the real background diff, the way the reporter left the folder:
    the card's .mov gone and a converted .mp4 of the same name in its place."""
    import threading

    from pinball_decryptor.core import checksums

    w = _stern(app)
    assets = _project(w, tmp_path, clips=["Tank_Jackpot1.mov", "tilt.mp4"])
    checksums.generate_checksums(assets)
    vid = os.path.join(assets, "video")
    os.remove(os.path.join(vid, "Tank_Jackpot1.mov"))
    with open(os.path.join(vid, "Tank_Jackpot1.mp4"), "wb") as f:
        f.write(b"bw clip")
    rels = ["video/Tank_Jackpot1.mp4", "video/tilt.mp4"]
    w._video_slots = [s for s in w._video_slots if s.rel_path in rels]
    w._video_slots.append(VideoSlot(
        rel_path=rels[0], abs_path=os.path.join(vid, "Tank_Jackpot1.mp4"),
        ext=".mp4", info=None, size=1, probed=True))
    w._video_slots_by_rel = {s.rel_path: s for s in w._video_slots}
    lines = _logs(w, monkeypatch)

    real_thread = threading.Thread

    def _inline(target=None, **kw):
        return type("T", (), {"start": staticmethod(target)})()

    threading.Thread = _inline
    try:
        w._start_change_scan("video")
        for _ in range(6):
            app.root.update(); app.root.update_idletasks()
    finally:
        threading.Thread = real_thread

    assert w._video_foreign_rels == {"video/Tank_Jackpot1.mp4"}
    assert w._video_foreign_twins == {
        "video/Tank_Jackpot1.mp4": "video/Tank_Jackpot1.mov"}
    text = "\n".join(t for _l, t in lines)
    assert "aren't part of this extract" in text
    assert "Tank_Jackpot1.mp4 where the card has Tank_Jackpot1.mov" in text
