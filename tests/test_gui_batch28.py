"""Feedback batch 28 — the Spike 2 tester, part-way through a card.

Two fixes under test, both logic-level (no Tk window; duck-typed stubs the
way test_gui_batch26 does it):

* The Replace tabs' "Changed only" checkbox is now a Show dropdown with All /
  Changed / Unchanged.  With 90% of his call-outs replaced, the view he
  wanted was the one the checkbox couldn't give: "If I could select
  unchanged, I could then filter out the ones I have already dealt with
  instead of scrolling up and down."  Folders whose sidecar still carries the
  old boolean must come back with the equivalent mode.

* Opening a replacement picker stops every preview first.  A modal file
  dialog does NOT stop Tk's timers, so sequential play kept stepping down the
  list behind the open picker ("the sounds just keeps going down the list")
  and handed the row back with a different track loaded in the preview.
"""

from types import SimpleNamespace

from pinball_decryptor.gui import main_window as mw
from pinball_decryptor.gui.main_window import MainWindow


class _Var:
    """The bits of tk.StringVar the filter helpers use."""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _win(kind, mode, assignments, changed_on_disk):
    stub = SimpleNamespace()
    setattr(stub, "%s_change_filter_var" % kind, _Var(mode))
    setattr(stub, "_%s_assignments" % kind, dict(assignments))
    setattr(stub, "_%s_changed_on_disk" % kind, set(changed_on_disk))
    stub._CHANGE_FILTER_VALUES = MainWindow._CHANGE_FILTER_VALUES
    return stub


# ---------------------------------------------------------------------------
# Show: All / Changed / Unchanged
# ---------------------------------------------------------------------------

def test_all_does_not_filter_at_all():
    stub = _win("audio", "All", {"a": "rep"}, {"b"})
    assert MainWindow._change_filter_pred(stub, "audio") is None


def test_changed_covers_both_a_pick_and_a_previous_build():
    stub = _win("audio", "Changed", {"a": "rep"}, {"b"})
    pred = MainWindow._change_filter_pred(stub, "audio")
    assert pred("a") and pred("b")
    assert not pred("c")


def test_unchanged_is_the_exact_complement():
    """The point of the dropdown: the slots still to deal with.  Changed and
    Unchanged must partition the folder — no slot in both, none in neither."""
    stub = _win("audio", "Unchanged", {"a": "rep"}, {"b"})
    pred = MainWindow._change_filter_pred(stub, "audio")
    assert pred("c")
    assert not pred("a") and not pred("b")


def test_the_filter_is_per_tab():
    """Each Replace tab reads its own variable and its own two sets — the
    audio dropdown must never filter by the video tab's picks."""
    for kind in ("audio", "video", "image"):
        stub = _win(kind, "Changed", {"x": "rep"}, ())
        pred = MainWindow._change_filter_pred(stub, kind)
        assert pred("x") and not pred("y")


def test_unknown_mode_filters_nothing():
    """A hand-edited sidecar can name anything; an unrecognised mode must
    show the whole folder rather than hide it."""
    stub = _win("audio", "Whatever", {"a": "rep"}, ())
    assert MainWindow._change_filter_pred(stub, "audio") is None


# ---- restoring a folder's saved choice ------------------------------------

def _restore(kind, staged, current="All"):
    stub = SimpleNamespace(_CHANGE_FILTER_VALUES=MainWindow._CHANGE_FILTER_VALUES)
    var = _Var(current)
    setattr(stub, "%s_change_filter_var" % kind, var)
    MainWindow._restore_change_filter(stub, kind, staged)
    return var.get()


def test_restore_takes_the_saved_mode():
    assert _restore("audio", {"audio_change_filter": "Unchanged"}) == "Unchanged"


def test_restore_maps_the_old_changed_only_boolean():
    """Sidecars written before the dropdown existed carry the checkbox."""
    assert _restore("image", {"image_changed_only": True}) == "Changed"
    assert _restore("image", {"image_changed_only": False},
                    current="Unchanged") == "All"


def test_restore_prefers_the_new_key_over_the_old_boolean():
    assert _restore("video", {"video_changed_only": True,
                              "video_change_filter": "All"}) == "All"


def test_restore_ignores_a_bad_value_and_an_empty_sidecar():
    assert _restore("audio", {"audio_change_filter": "changed"},
                    current="Changed") == "Changed"
    assert _restore("audio", {}, current="Unchanged") == "Unchanged"


# ---------------------------------------------------------------------------
# The replacement picker silences the previews first
# ---------------------------------------------------------------------------

def _picker_win(kind, monkeypatch, order):
    """A stub Replace tab whose picker records whether playback was stopped
    BEFORE the dialog opened.  The dialog answers "" (cancelled), so nothing
    past the picker runs."""
    def fake_pick(**_kw):
        order.append("picker")
        return ""

    monkeypatch.setattr(mw.filedialog, "askopenfilename", fake_pick)
    stub = SimpleNamespace(
        stop_playback_for_picker=lambda: order.append("stop"),
        last_browse_dir=lambda _k: "",
        video_no_conversion_var=_Var(False),
    )
    setattr(stub, "_%s_slots_by_rel" % kind, {"slot": object()})
    return stub


def test_audio_picker_stops_playback_before_it_opens(monkeypatch):
    order = []
    MainWindow._audio_assign_rel(_picker_win("audio", monkeypatch, order),
                                 "slot")
    assert order == ["stop", "picker"]


def test_video_picker_stops_playback_before_it_opens(monkeypatch):
    order = []
    MainWindow._video_assign_rel(_picker_win("video", monkeypatch, order),
                                 "slot")
    assert order == ["stop", "picker"]


def test_an_unknown_slot_neither_stops_nor_opens_anything(monkeypatch):
    order = []
    MainWindow._audio_assign_rel(_picker_win("audio", monkeypatch, order),
                                 "not-a-slot")
    assert order == []


# ---- the queued "play the next row" step ----------------------------------

class _Root:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []

    def after(self, _ms, fn):
        self.scheduled.append(fn)
        return "job%d" % len(self.scheduled)

    def after_cancel(self, job):
        self.cancelled.append(job)


def _seq_win(root, playing_rel="a"):
    stub = SimpleNamespace(
        _tk_root=lambda: root,
        audio_play_through_var=_Var(True),
        audio_play_subst_var=_Var(False),
        _audio_current_rel=playing_rel,
        _audio_advance_job=None,
        _audio_pane_orig=None,
        _audio_pane_rep=None,
        _audio_next_visible_rel=lambda _rel: "b",
        append_log=lambda *a, **k: None,
    )
    stub._cancel_audio_advance = lambda: MainWindow._cancel_audio_advance(stub)
    return stub


def test_a_finished_clip_records_the_step_it_queued():
    """It has to be recorded to be cancellable — the whole fix hangs on it."""
    root = _Root()
    stub = _seq_win(root)
    MainWindow._audio_on_clip_finished(stub, None)
    assert stub._audio_advance_job == "job1"


def test_stopping_playback_drops_the_queued_step():
    root = _Root()
    stub = _seq_win(root)
    MainWindow._audio_on_clip_finished(stub, None)
    MainWindow._audio_stop_playback(stub)
    assert root.cancelled == ["job1"]
    assert stub._audio_advance_job is None


def test_cancelling_twice_is_harmless():
    root = _Root()
    stub = _seq_win(root)
    MainWindow._cancel_audio_advance(stub)
    MainWindow._cancel_audio_advance(stub)
    assert root.cancelled == []
