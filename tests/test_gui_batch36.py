"""Feedback batch 36 — a stray clip an old-name mod pack left in the folder.

The tester exported a mod pack from a project extracted before PAD-61 fixed the
Spike 2 clip-name scan (it used to take the low byte of the record's u32 id into
the name, so runs of clips came out ending a, b, c, …), then imported it into a
fresh extract of the same card.  The clips whose corrected name matched still
landed on their slot; the rest were written as brand-new files the card has no
slot for.  Two things then lied to him on the Video tab:

* they wore the same "✓ changed on disk" mark as a real staged change, and
* their Replacement pane said "the change is on the left, and it is what the
  next build puts on the card" — which the build cannot do, since it only
  repacks files that came off the card.

All he could see was the missing original ("some of the videos look like they
didn't save the original... it's inconsistent").  The change diff already knew
which rows those were — it logs them — so keep the set and say it per row.
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

_BUILD_PROMISE = "what the next build puts on the card"


def _stern(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


def _slot(rel):
    return VideoSlot(rel_path=rel, abs_path=os.path.join("C:\\x", rel),
                     ext=os.path.splitext(rel)[1], info=None, size=1,
                     probed=True)


def _load_video_rows(w, rels):
    w._video_slots = [_slot(r) for r in rels]
    w._video_slots_by_rel = {s.rel_path: s for s in w._video_slots}
    w._video_assignments = {}


def test_a_stray_row_is_not_marked_as_a_change_that_will_build(app):
    """The Replacement column separates "changed, and it builds" from
    "this file isn't on the card at all"."""
    w = _stern(app)
    real, stray = "video/JUKEBOX_LOOP6.mov", "video/JUKEBOX_LOOP6f.mov"
    _load_video_rows(w, [real, stray])
    # Both differ from the baseline (a rel that ISN'T in it counts as changed —
    # see checksums.changed_rels), but only one of them is a slot.
    w._video_changed_on_disk = {real, stray}
    w._video_foreign_rels = {stray}
    w._refresh_video_list()

    vals = {r: w._video_tree.item(r, "values") for r in (real, stray)}
    assert vals[real][4] == "✓ changed on disk"
    assert vals[stray][4] == w._NOT_ON_CARD_MARK
    assert "changed" in w._video_tree.item(real, "tags")
    assert "foreign" in w._video_tree.item(stray, "tags")


def test_the_metadata_pass_keeps_the_stray_mark(app):
    """ffprobe fills Length/Resolution/Format in behind the list; that rewrite
    used to be where a row's mark got dropped (batch 34), so it has to know
    about this state too."""
    w = _stern(app)
    stray = "video/JUKEBOX_LOOP6f.mov"
    _load_video_rows(w, [stray])
    w._video_changed_on_disk = {stray}
    w._video_foreign_rels = {stray}
    w._refresh_video_list()

    w._apply_video_meta(w._video_scan_id, stray, None)
    assert w._video_tree.item(stray, "values")[4] == w._NOT_ON_CARD_MARK


def test_the_replacement_pane_does_not_promise_a_build_for_a_stray(app):
    w = _stern(app)
    stray = "video/JUKEBOX_LOOP6f.mov"
    _load_video_rows(w, [stray])
    w._video_changed_on_disk = {stray}
    w._video_foreign_rels = {stray}

    text = w._rep_pane_empty_text("video", stray, "no replacement assigned")
    assert _BUILD_PROMISE not in text
    assert "not part of this extract" in text
    assert "Transfer Mods" in text


def test_a_real_changed_slot_still_reads_as_before(app):
    """The snapshot-less-but-real case (batch 31) keeps its wording — that one
    IS what the next build writes."""
    w = _stern(app)
    real = "video/JUKEBOX_LOOP6.mov"
    _load_video_rows(w, [real])
    w._video_changed_on_disk = {real}
    w._video_foreign_rels = set()

    text = w._rep_pane_empty_text("video", real, "no replacement assigned")
    assert _BUILD_PROMISE in text


def test_an_untouched_slot_keeps_the_default_text(app):
    w = _stern(app)
    rel = "video/JUKEBOX_LOOP6.mov"
    _load_video_rows(w, [rel])
    w._video_changed_on_disk = set()
    w._video_foreign_rels = set()

    assert w._rep_pane_empty_text("video", rel, "no replacement assigned") \
        == "no replacement assigned"


def test_the_change_diff_records_which_rows_are_strays(app, tmp_path):
    """End to end: the background diff that flags changed-on-disk rows is what
    answers the question, so it has to keep the set rather than only log it."""
    import threading

    from pinball_decryptor.core import checksums

    w = _stern(app)
    assets = str(tmp_path / "extract")
    vid = os.path.join(assets, "video")
    os.makedirs(vid)
    for name in ("JUKEBOX_LOOP6.mov", "ATTRACT_LOOP1.mov"):
        with open(os.path.join(vid, name), "wb") as f:
            f.write(b"stock-" + name.encode())
    checksums.generate_checksums(assets)
    # What the old import wrote: the same clip under the name the previous
    # extract gave it.  Nothing in the baseline matches.
    with open(os.path.join(vid, "JUKEBOX_LOOP6f.mov"), "wb") as f:
        f.write(b"my modded clip")

    w.write_assets_var.set(assets)
    _load_video_rows(w, ["video/JUKEBOX_LOOP6.mov", "video/ATTRACT_LOOP1.mov",
                         "video/JUKEBOX_LOOP6f.mov"])
    w._video_changed_on_disk = set()
    w._video_foreign_rels = set()

    # Run the worker inline instead of on a thread, then let the after()
    # callbacks it queues land.
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

    assert w._video_foreign_rels == {"video/JUKEBOX_LOOP6f.mov"}
    assert "video/JUKEBOX_LOOP6f.mov" in w._video_changed_on_disk
    assert "video/JUKEBOX_LOOP6.mov" not in w._video_changed_on_disk


def test_audio_and_image_rows_get_the_same_treatment(app):
    """The same import scatters sounds and art; all three tabs share the diff."""
    w = _stern(app)
    stray = "audio/idx0001 - old name.wav"
    w._audio_changed_on_disk = {stray}
    w._audio_foreign_rels = {stray}
    assert _BUILD_PROMISE not in w._rep_pane_empty_text("audio", stray, "x")

    stray_img = "images/scene_textures/old_name.png"
    w._image_changed_on_disk = {stray_img}
    w._image_foreign_rels = {stray_img}
    assert _BUILD_PROMISE not in w._rep_pane_empty_text("image", stray_img, "x")
