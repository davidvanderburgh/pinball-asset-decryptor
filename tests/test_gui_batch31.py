"""Feedback batch 31 — the Spike 2 tester's second build day.

Two things, both "the app forgets what I told it":

* "The Build/Flash screen does not remember your selections between sessions.
  I did a build only, then updated, then went back in to the same screen and
  both options were selected."  The dialog now opens on the pair you last
  ran, per manufacturer, and only Start records it.

* "Is it possible to put in dismiss button for the warning about the extract
  needing a refresh?  In my case I know I am fine but will have to see that
  message the entire time."  There WAS one — a bare ✕ at the far right of the
  banner, a couple of rows below the window's own ✕ — and dismissing it only
  lasted until the next launch.  It is a labelled Dismiss button now, and the
  acknowledgement is written against the source image's current signature so
  it survives a restart without silencing a later, genuinely new change.

The banner tests drive MainWindow's methods against duck-typed stubs and no
Tk window, the way test_gui_batch26 / test_gui_batch30 do it; the dialog
tests need a real window and follow test_gui_batch18.
"""

import os
import tkinter as tk

import pytest

from pinball_decryptor.core import extract_source
from pinball_decryptor.gui.main_window import MainWindow

from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401  (fixture)

W = MainWindow

FAKE_BUILD = os.path.join(os.sep + "builds", "game-modified.raw")


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _image(path, data=b"\x00" * 4096):
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def _touch_later(path, seconds=120):
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + seconds))


def _stale_project(tmp_path, name="game.raw"):
    """An extract folder whose recorded source has since changed on disk."""
    img = _image(tmp_path / name)
    out = tmp_path / "project"
    out.mkdir()
    extract_source.write_extract_source(str(out), img)
    _touch_later(img)
    assert extract_source.stale_source_message(str(out))
    return img, str(out)


# ---------------------------------------------------------------------------
# "I know I am fine but will have to see that message the entire time"
# ---------------------------------------------------------------------------

def test_dismissing_the_warning_is_remembered(tmp_path):
    _img, out = _stale_project(tmp_path)
    assert extract_source.stale_dismissed(out) is False
    assert extract_source.dismiss_stale_source(out) is True
    # The image really is still stale — the app just isn't nagging about it.
    assert extract_source.stale_source_message(out) is not None
    assert extract_source.stale_dismissed(out) is True


def test_a_further_change_to_the_image_re_arms_the_warning(tmp_path):
    img, out = _stale_project(tmp_path)
    extract_source.dismiss_stale_source(out)
    _touch_later(img, 600)          # something else touched it since
    assert extract_source.stale_dismissed(out) is False


def test_re_extract_clears_the_dismissal(tmp_path):
    img, out = _stale_project(tmp_path)
    extract_source.dismiss_stale_source(out)
    extract_source.write_extract_source(out, img)   # the actual fix, re-run
    assert extract_source.stale_source_message(out) is None
    assert extract_source.stale_dismissed(out) is False


def test_dismissal_keeps_the_rest_of_the_sidecar(tmp_path):
    img, out = _stale_project(tmp_path)
    extract_source.dismiss_stale_source(out)
    rec = extract_source.read_extract_source(out)
    assert rec["input_path"] == os.path.abspath(img)
    assert rec["input_name"] == "game.raw"


def test_dismissing_without_a_sidecar_changes_nothing(tmp_path):
    assert extract_source.dismiss_stale_source(str(tmp_path)) is False
    assert extract_source.stale_dismissed(str(tmp_path)) is False


def test_dismissing_a_vanished_source_changes_nothing(tmp_path):
    img, out = _stale_project(tmp_path)
    os.remove(img)
    assert extract_source.dismiss_stale_source(out) is False
    assert extract_source.stale_dismissed(out) is False


# ---- the banner itself ----------------------------------------------------

class _FakeBanner:
    def __init__(self):
        self.mapped = False

    def winfo_ismapped(self):
        return self.mapped

    def pack(self, **_kw):
        self.mapped = True

    def pack_forget(self):
        self.mapped = False


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def configure(self, text=None, **_kw):
        self.text = text

    def cget(self, _key):
        return self.text


class _ImmediateRoot:
    """`after` runs the callback right away — these tests are about the
    banner's decisions, not Tk's timer wheel."""

    def after(self, _delay, fn=None, *args):
        if fn is not None:
            fn(*args)


class _BannerHost:
    """Just the surface _refresh/_dismiss_stale_source_banner touch.

    The refresh is ASYNC now — the staleness probe stats the source image,
    which can live on OneDrive/NAS, so the real method moved it to a worker
    (a frozen post-reboot tab switch, 2026-08-09).  The host joins the probe
    before returning so every assertion below still reads the settled
    answer, exactly as it did when the method was synchronous."""

    def __init__(self, assets_dir):
        self.write_assets_var = _Var(assets_dir)
        self._stale_source_banner = _FakeBanner()
        self._stale_source_banner_text = _FakeLabel()
        self._stale_source_dismissed = None
        self._top_bar = None
        self.root = _ImmediateRoot()

    def _apply_stale_source_banner(self, *a):
        try:
            return W._apply_stale_source_banner(self, *a)
        finally:
            self._applied.set()

    def refresh(self):
        import threading as _th
        self._applied = _th.Event()
        W._refresh_stale_source_banner(self)
        assert self._applied.wait(5), "the staleness probe never answered"

    dismiss = W._dismiss_stale_source_banner


def test_banner_shows_then_stays_down_once_dismissed(tmp_path):
    _img, out = _stale_project(tmp_path)
    host = _BannerHost(out)
    host.refresh()
    assert host._stale_source_banner.mapped
    host.dismiss()
    assert not host._stale_source_banner.mapped
    host.refresh()
    assert not host._stale_source_banner.mapped


def test_dismissal_survives_the_next_launch(tmp_path):
    """The complaint was seeing it "the entire time" — a fresh window on the
    same project must not resurrect a banner already waved through."""
    _img, out = _stale_project(tmp_path)
    _BannerHost(out).dismiss()
    fresh = _BannerHost(out)        # new session, nothing in memory
    fresh.refresh()
    assert not fresh._stale_source_banner.mapped


def test_a_new_change_gets_through_a_previous_dismissal(tmp_path):
    img, out = _stale_project(tmp_path)
    _BannerHost(out).dismiss()
    _touch_later(img, 900)
    fresh = _BannerHost(out)
    fresh.refresh()
    assert fresh._stale_source_banner.mapped


def test_dismissing_one_project_does_not_silence_another(tmp_path):
    _img_a, a = _stale_project(tmp_path, "a.raw")
    b_root = tmp_path / "second"
    b_root.mkdir()
    _img_b, b = _stale_project(b_root, "b.raw")
    host = _BannerHost(a)
    host.refresh()
    host.dismiss()
    # Same window, user switches project folder: the other one still warns.
    host.write_assets_var.set(b)
    host.refresh()
    assert host._stale_source_banner.mapped


def test_unwritable_folder_still_hides_it_for_the_session(tmp_path,
                                                          monkeypatch):
    _img, out = _stale_project(tmp_path)

    def _boom(_dir):
        raise OSError("read-only share")

    # main_window imports the name directly, so that's the binding to replace.
    monkeypatch.setattr("pinball_decryptor.gui.main_window."
                        "dismiss_stale_source", _boom)
    host = _BannerHost(out)
    host.refresh()
    host.dismiss()                  # must not raise
    assert not host._stale_source_banner.mapped
    host.refresh()
    assert not host._stale_source_banner.mapped


# ---------------------------------------------------------------------------
# "The Build/Flash screen does not remember your selections between sessions"
# ---------------------------------------------------------------------------

class _ChoicesHost:
    def __init__(self, saved=None, sink=None):
        self._saved_flash_choices = dict(saved or {})
        self._on_flash_choices_change = sink

    remember = W._remember_flash_choices


def test_window_forwards_the_pair_for_persistence():
    seen = []
    host = _ChoicesHost(sink=seen.append)
    host.remember("stern", {"build": True, "write": False})
    assert host._saved_flash_choices == {
        "stern": {"build": True, "write": False}}
    assert seen == [{"stern": {"build": True, "write": False}}]


def test_an_omitted_build_flag_leaves_the_previous_answer_standing():
    host = _ChoicesHost({"stern": {"build": True, "write": True}})
    host.remember("stern", {"write": False})     # build box was disabled
    assert host._saved_flash_choices["stern"] == {"build": True,
                                                  "write": False}


def test_manufacturers_keep_their_own_pair():
    seen = []
    host = _ChoicesHost({"stern": {"build": True, "write": False}},
                        sink=seen.append)
    host.remember("jjp", {"build": True, "write": True})
    assert host._saved_flash_choices == {
        "stern": {"build": True, "write": False},
        "jjp": {"build": True, "write": True}}


def test_an_unchanged_pair_is_not_re_persisted():
    seen = []
    host = _ChoicesHost({"stern": {"build": True, "write": False}},
                        sink=seen.append)
    host.remember("stern", {"build": True, "write": False})
    assert seen == []


# ---- the dialog (needs a real window) -------------------------------------

gui_only = pytest.mark.skipif(not HAS_DISPLAY,
                              reason="no Tk display available")


def _pick(app, key):
    mfr = next(m for m in app._manufacturers if m.key == key)
    app._on_manufacturer_change(mfr)
    app.root.update(); app.root.update()
    return app.window


def _make_dialog(app, monkeypatch, **kw):
    from pinball_decryptor.gui.flash_dialog import FlashImageDialog
    monkeypatch.setattr(FlashImageDialog, "_refresh_drives",
                        lambda self: None)
    defaults = dict(
        parent=app.root, manufacturer=app._current_mfr, theme_name="light",
        on_flash=lambda i, d: None, on_build_flash=lambda b, d: None,
        build_target=FAKE_BUILD, can_build=True, has_pending_changes=True)
    defaults.update(kw)
    return FlashImageDialog(**defaults)


@pytest.mark.gui
@gui_only
def test_dialog_opens_on_the_pair_you_last_ran(app, monkeypatch):
    """The exact report: build only, come back, both boxes ticked again."""
    _pick(app, "stern")
    dlg = _make_dialog(app, monkeypatch,
                       initial_choices={"build": True, "write": False})
    try:
        assert dlg._build_var.get() is True
        assert dlg._write_var.get() is False
        assert dlg._start_btn.cget("text") == "Build image"
    finally:
        dlg._cancel()


@pytest.mark.gui
@gui_only
def test_start_records_the_pair_and_cancel_does_not(app, monkeypatch):
    _pick(app, "stern")
    seen = []
    dlg = _make_dialog(app, monkeypatch, on_choices=seen.append)
    dlg._write_var.set(False); dlg._sync_sections()
    dlg._cancel()
    assert seen == [], "a cancelled dialog must not rewrite the memory"

    dlg = _make_dialog(app, monkeypatch, on_choices=seen.append)
    dlg._write_var.set(False); dlg._sync_sections()
    dlg._do_start()
    assert seen == [{"write": False, "build": True}]


@pytest.mark.gui
@gui_only
def test_a_disabled_build_box_is_not_a_choice(app, monkeypatch):
    """Build unavailable (Write tab not set up) forces the box off — recording
    that would open build-less next time, once the tab IS set up."""
    _pick(app, "stern")
    seen = []
    dlg = _make_dialog(app, monkeypatch, can_build=False,
                       on_choices=seen.append)
    dlg._remember_choices()
    assert seen == [{"write": True}]
    dlg._cancel()


@pytest.mark.gui
@gui_only
def test_nothing_remembered_keeps_the_original_defaults(app, monkeypatch):
    _pick(app, "stern")
    dlg = _make_dialog(app, monkeypatch, has_pending_changes=False)
    try:
        # Unchanged behaviour: no edits ⇒ flash-only, the old Flash dialog.
        assert dlg._build_var.get() is False
        assert dlg._write_var.get() is True
    finally:
        dlg._cancel()


@pytest.mark.gui
@gui_only
def test_a_remembered_pair_beats_the_no_changes_default(app, monkeypatch):
    """Having run build-only before outranks "nothing is modified"; the
    "Nothing modified — build anyway?" confirm still catches an accident."""
    _pick(app, "stern")
    dlg = _make_dialog(app, monkeypatch, has_pending_changes=False,
                       initial_choices={"build": True, "write": False})
    try:
        assert dlg._build_var.get() is True
        assert dlg._write_var.get() is False
    finally:
        dlg._cancel()


@pytest.mark.gui
@gui_only
def test_an_all_off_memory_falls_back_to_the_defaults(app, monkeypatch):
    """A dialog that opens with Start greyed out looks broken."""
    _pick(app, "stern")
    dlg = _make_dialog(app, monkeypatch,
                       initial_choices={"build": False, "write": False})
    try:
        assert dlg._build_var.get() is True
        assert dlg._write_var.get() is True
        assert "disabled" not in dlg._start_btn.state()
    finally:
        dlg._cancel()


@pytest.mark.gui
@gui_only
def test_a_remembered_build_cannot_tick_an_impossible_box(app, monkeypatch):
    _pick(app, "stern")
    dlg = _make_dialog(app, monkeypatch, can_build=False,
                       initial_choices={"build": True, "write": True})
    try:
        assert dlg._build_var.get() is False
    finally:
        dlg._cancel()


@pytest.mark.gui
@gui_only
def test_the_stale_banner_dismiss_is_a_labelled_button(app):
    """It had one all along — an unlabelled ✕ at the far right of a wide
    window, two rows under the window's own ✕, which is why the tester asked
    for a dismiss button while looking straight at it."""
    banner = app.window._stale_source_banner
    labels = [str(c.cget("text")) for c in banner.winfo_children()]
    assert "Dismiss" in labels, labels
    assert "✕" not in labels
