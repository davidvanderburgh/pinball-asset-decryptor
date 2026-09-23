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
from types import SimpleNamespace

import pytest

from pinball_decryptor.core.video_slots import VideoSlot
from pinball_decryptor.webui import video_helpers as vh
from pinball_decryptor.webui.tabs import video as video_mod
from tests.webui_harness import web_app

_BUILD_PROMISE = "what the next build puts on the card"


@pytest.fixture
def w(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        yield w


def _slot(rel):
    return VideoSlot(rel_path=rel, abs_path=os.path.join("C:\\x", rel),
                     ext=os.path.splitext(rel)[1], info=None, size=1,
                     probed=True)


def _load_video_rows(v, rels, changed=(), foreign=()):
    v._slots = [_slot(r) for r in rels]
    v._by_rel = {s.rel_path: s for s in v._slots}
    v._assign = {}
    v._changed = set(changed)
    v._foreign = set(foreign)


def _rows(w):
    return {r["rel"]: r for r in w.state("video")["rows"]}


def test_a_stray_row_is_not_marked_as_a_change_that_will_build(w):
    """The Replacement column separates "changed, and it builds" from
    "this file isn't on the card at all"."""
    v = w.window.service("video")
    real, stray = "video/JUKEBOX_LOOP6.mov", "video/JUKEBOX_LOOP6f.mov"

    # Both differ from the baseline (a rel that ISN'T in it counts as changed —
    # see checksums.changed_rels), but only one of them is a slot.
    def _go():
        _load_video_rows(v, [real, stray], changed={real, stray},
                         foreign={stray})
        v._refresh_list()
    w.run(_go)

    rows = _rows(w)
    assert rows[real]["rep"] == "✓ changed on disk"
    assert rows[stray]["rep"] == vh.NOT_ON_CARD_MARK
    assert rows[real]["rep_cls"] == "ondisk"
    assert rows[stray]["rep_cls"] == "stray"


def test_the_metadata_pass_keeps_the_stray_mark(w):
    """ffprobe fills Length/Resolution/Format in behind the list; that rewrite
    used to be where a row's mark got dropped (batch 34), so it has to know
    about this state too."""
    v = w.window.service("video")
    stray = "video/JUKEBOX_LOOP6f.mov"

    def _go():
        _load_video_rows(v, [stray], changed={stray}, foreign={stray})
        v._refresh_list()
        v._apply_meta(v._scan_id, stray, None)
    w.run(_go)

    assert _rows(w)[stray]["rep"] == vh.NOT_ON_CARD_MARK


def test_the_replacement_pane_does_not_promise_a_build_for_a_stray(w):
    v = w.window.service("video")
    stray = "video/JUKEBOX_LOOP6f.mov"
    w.run(lambda: _load_video_rows(v, [stray], changed={stray},
                                   foreign={stray}))

    text = w.run(v._rep_pane_empty_text, stray, "no replacement assigned")
    assert _BUILD_PROMISE not in text
    assert "not part of this extract" in text
    assert "Transfer Mods" in text


def test_a_real_changed_slot_still_reads_as_before(w):
    """The snapshot-less-but-real case (batch 31) keeps its wording — that one
    IS what the next build writes."""
    v = w.window.service("video")
    real = "video/JUKEBOX_LOOP6.mov"
    w.run(lambda: _load_video_rows(v, [real], changed={real}))

    text = w.run(v._rep_pane_empty_text, real, "no replacement assigned")
    assert _BUILD_PROMISE in text


def test_an_untouched_slot_keeps_the_default_text(w):
    v = w.window.service("video")
    rel = "video/JUKEBOX_LOOP6.mov"
    w.run(lambda: _load_video_rows(v, [rel]))

    assert w.run(v._rep_pane_empty_text, rel, "no replacement assigned") \
        == "no replacement assigned"


def test_the_change_diff_records_which_rows_are_strays(w, tmp_path,
                                                        monkeypatch):
    """End to end: the background diff that flags changed-on-disk rows is what
    answers the question, so it has to keep the set rather than only log it."""
    from pinball_decryptor.core import checksums

    v = w.window.service("video")
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

    def _set_folder():
        try:
            w.window.write_assets_var.set(assets)
        except Exception:                                # noqa: BLE001
            pass
    w.run(_set_folder)
    w.drain()
    w.run(lambda: _load_video_rows(
        v, ["video/JUKEBOX_LOOP6.mov", "video/ATTRACT_LOOP1.mov",
            "video/JUKEBOX_LOOP6f.mov"]))

    # Run the worker inline instead of on a thread, then let the callback it
    # posts to the UI loop land.
    def _inline(target=None, **_kw):
        return SimpleNamespace(start=target)

    with monkeypatch.context() as m:
        m.setattr(video_mod, "threading", SimpleNamespace(Thread=_inline))
        w.run(v._start_change_scan)
    w.drain()

    assert v._foreign == {"video/JUKEBOX_LOOP6f.mov"}
    assert "video/JUKEBOX_LOOP6f.mov" in v._changed
    assert "video/JUKEBOX_LOOP6.mov" not in v._changed


def test_audio_and_image_rows_get_the_same_treatment(w):
    """The same import scatters sounds and art; all three tabs share the diff."""
    a = w.window.service("audio")
    stray = "audio/idx0001 - old name.wav"

    def _audio():
        a._changed = {stray}
        a._foreign = {stray}
        return a._rep_pane_empty_text(stray, "x")
    assert _BUILD_PROMISE not in w.run(_audio)

    img = w.window.service("images")
    stray_img = "images/scene_textures/old_name.png"

    def _images():
        img._changed_on_disk = {stray_img}
        img._foreign_rels = {stray_img}
        return img._rep_pane_empty_text(stray_img, "x")
    assert _BUILD_PROMISE not in w.run(_images)
