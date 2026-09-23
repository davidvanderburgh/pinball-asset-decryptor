"""Feedback batch 28 — the Spike 2 tester, part-way through a card.

Two fixes under test, both logic-level (no window; duck-typed stubs of the
tab services the way test_gui_batch26 does it):

* The Replace tabs' "Changed only" checkbox is now a Show dropdown with All /
  Changed / Unchanged.  With 90% of his call-outs replaced, the view he
  wanted was the one the checkbox couldn't give: "If I could select
  unchanged, I could then filter out the ones I have already dealt with
  instead of scrolling up and down."  Folders whose sidecar still carries the
  old boolean must come back with the equivalent mode.

* Opening a replacement picker stops every preview first.  A modal file
  dialog does NOT stop the UI loop's timers, so sequential play kept stepping
  down the list behind the open picker ("the sounds just keeps going down the
  list") and handed the row back with a different track loaded in the
  preview.
"""

from types import SimpleNamespace

from pinball_decryptor.webui.tabs.audio import AudioTab
from pinball_decryptor.webui.tabs.images import ImagesTab
from pinball_decryptor.webui.tabs.video import VideoTab


class _Var:
    """The bits of a tab variable the filter helpers use."""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


# Each Replace tab keeps its picks and its on-disk diff under its own names.
_PRED = {
    "audio": (AudioTab._change_filter_pred, "_assign", "_changed"),
    "video": (VideoTab._change_pred, "_assign", "_changed"),
    "image": (ImagesTab._change_filter_pred, "_assignments",
              "_changed_on_disk"),
}


def _pred(kind, mode, assignments, changed_on_disk):
    fn, picks, changed = _PRED[kind]
    stub = SimpleNamespace()
    setattr(stub, "%s_change_filter_var" % kind, _Var(mode))
    setattr(stub, picks, dict(assignments))
    setattr(stub, changed, set(changed_on_disk))
    return fn(stub)


# ---------------------------------------------------------------------------
# Show: All / Changed / Unchanged
# ---------------------------------------------------------------------------

def test_all_does_not_filter_at_all():
    assert _pred("audio", "All", {"a": "rep"}, {"b"}) is None


def test_changed_covers_both_a_pick_and_a_previous_build():
    pred = _pred("audio", "Changed", {"a": "rep"}, {"b"})
    assert pred("a") and pred("b")
    assert not pred("c")


def test_unchanged_is_the_exact_complement():
    """The point of the dropdown: the slots still to deal with.  Changed and
    Unchanged must partition the folder — no slot in both, none in neither."""
    pred = _pred("audio", "Unchanged", {"a": "rep"}, {"b"})
    assert pred("c")
    assert not pred("a") and not pred("b")


def test_the_filter_is_per_tab():
    """Each Replace tab reads its own variable and its own two sets — the
    audio dropdown must never filter by the video tab's picks."""
    for kind in ("audio", "video", "image"):
        pred = _pred(kind, "Changed", {"x": "rep"}, ())
        assert pred("x") and not pred("y")


def test_unknown_mode_filters_nothing():
    """A hand-edited sidecar can name anything; an unrecognised mode must
    show the whole folder rather than hide it."""
    assert _pred("audio", "Whatever", {"a": "rep"}, ()) is None


# ---- restoring a folder's saved choice ------------------------------------

_RESTORE = {"audio": AudioTab._restore_change_filter,
            "image": ImagesTab._restore_change_filter}


def _restore(kind, staged, current="All"):
    stub = SimpleNamespace()
    var = _Var(current)
    setattr(stub, "%s_change_filter_var" % kind, var)
    _RESTORE[kind](stub, staged)
    return var.get()


def test_restore_takes_the_saved_mode():
    assert _restore("audio", {"audio_change_filter": "Unchanged"}) == "Unchanged"


def test_restore_maps_the_old_changed_only_boolean():
    """Sidecars written before the dropdown existed carry the checkbox."""
    assert _restore("image", {"image_changed_only": True}) == "Changed"
    assert _restore("image", {"image_changed_only": False},
                    current="Unchanged") == "All"


def test_restore_prefers_the_new_key_over_the_old_boolean():
    assert _restore("audio", {"audio_changed_only": True,
                              "audio_change_filter": "All"}) == "All"


def test_restore_ignores_a_bad_value_and_an_empty_sidecar():
    assert _restore("audio", {"audio_change_filter": "changed"},
                    current="Changed") == "Changed"
    assert _restore("audio", {}, current="Unchanged") == "Unchanged"


# ---------------------------------------------------------------------------
# The replacement picker silences the previews first
# ---------------------------------------------------------------------------

def _picker_tab(order):
    """A stub Replace tab whose picker records whether playback was stopped
    BEFORE the dialog opened.  The dialog answers "" (cancelled), so nothing
    past the picker runs."""
    def fake_pick(*_a, **_kw):
        order.append("picker")
        return ""

    return SimpleNamespace(
        _by_rel={"slot": object()},
        _current="slot",
        _cancel_select_job=lambda: None,
        stop_all_preview_playback=lambda: order.append("stop"),
        _ask_path=fake_pick,
        window=SimpleNamespace(ask_open=fake_pick),
    )


def test_audio_picker_stops_playback_before_it_opens():
    order = []
    AudioTab.choose(_picker_tab(order), "slot")
    assert order == ["stop", "picker"]


def test_video_picker_stops_playback_before_it_opens():
    order = []
    VideoTab.choose(_picker_tab(order), "slot")
    assert order == ["stop", "picker"]


def test_an_unknown_slot_neither_stops_nor_opens_anything():
    order = []
    AudioTab.choose(_picker_tab(order), "not-a-slot")
    assert order == []


# ---- the queued "play the next row" step ----------------------------------

class _Loop:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []

    def after(self, _ms, fn, *args):
        self.scheduled.append(fn)
        return "job%d" % len(self.scheduled)

    def after_cancel(self, job):
        self.cancelled.append(job)


class _SeqTab:
    """The Audio tab's sequential-play bookkeeping, nothing else."""
    clip_finished = AudioTab.clip_finished
    _after = AudioTab._after
    _cancel = AudioTab._cancel
    _cancel_advance = AudioTab._cancel_advance
    _stop_playback = AudioTab._stop_playback

    def __init__(self, loop, playing_rel="a"):
        self.ctx = SimpleNamespace(loop=loop)
        self.audio_play_through_var = _Var(True)
        self.audio_play_subst_var = _Var(False)
        self._current_rel = playing_rel
        self._advance_job = None
        self._panes = {"orig": {"path": "a.wav"}, "rep": {"path": ""}}

    def _next_visible_rel(self, _rel):
        return "b"

    def _publish(self, *_a, **_kw):
        pass

    def log(self, *_a, **_kw):
        pass


def test_a_finished_clip_records_the_step_it_queued():
    """It has to be recorded to be cancellable — the whole fix hangs on it."""
    loop = _Loop()
    tab = _SeqTab(loop)
    tab.clip_finished("orig")
    assert tab._advance_job == "job1"


def test_stopping_playback_drops_the_queued_step():
    loop = _Loop()
    tab = _SeqTab(loop)
    tab.clip_finished("orig")
    tab._stop_playback()
    assert loop.cancelled == ["job1"]
    assert tab._advance_job is None


def test_cancelling_twice_is_harmless():
    loop = _Loop()
    tab = _SeqTab(loop)
    tab._cancel_advance()
    tab._cancel_advance()
    assert loop.cancelled == []
