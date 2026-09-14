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


# ---- the menu-only write, where someone about to wait an hour will find it ----------
def _spike_image_for(tmp_path):
    """A miniature card image with a Linux rootfs as p2 - enough for
    menu_write_plan to say yes."""
    import struct
    sec = 512

    def entry(ptype, lba, count):
        return (b"\x00\x00\x00\x00" + bytes([ptype]) + b"\x00\x00\x00"
                + struct.pack("<II", lba, count))
    img = bytearray(256 * sec)
    mbr = bytearray(sec)
    for i, (t, lba, cnt) in enumerate([(0x0C, 8, 8), (0x83, 16, 16),
                                       (0x83, 32, 16), (0x0F, 64, 64)]):
        mbr[446 + i * 16:446 + (i + 1) * 16] = entry(t, lba, cnt)
    mbr[510:512] = b"\x55\xaa"
    img[0:sec] = mbr
    p = tmp_path / "card.multi.raw"
    p.write_bytes(bytes(img))
    return str(p)


@pytest.mark.gui
@gui_only
def test_the_flash_dialog_offers_the_menu_only_write(app, monkeypatch,
                                                     tmp_path):
    """A 14.7 GB image on an ordinary card is forty minutes; its MENU is one
    partition and about a minute.  The option defaults ON for an image that
    has one and that a flash has already put onto an SD card (David, twice:
    "flashing the whole thing takes over an hour with my slow sd card"; the
    never-flashed case is PAD-145's test below)."""
    _pick(app, "stern")
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(app, monkeypatch,
                       initial_choices={"build": False, "write": True},
                       flashed_fn=lambda i: True)
    try:
        dlg._image_var.set(img)
        dlg._sync_sections()
        assert dlg._menu_var.get() is True, "on by default when it can be"
        assert str(dlg._menu_chk.state()).find("disabled") < 0
        assert "menu partition only" in dlg._menu_note.cget("text")
        # ...and never for a build+flash: a fresh image was never on that card
        dlg._build_var.set(True)
        dlg._sync_sections()
        assert dlg._menu_var.get() is False
        assert "has to be written" in dlg._menu_note.cget("text")
        # ...nor for something that is not a card image at all
        dlg._build_var.set(False)
        plain = tmp_path / "notacard.raw"
        plain.write_bytes(b"\x00" * 4096)
        dlg._image_var.set(str(plain))
        dlg._sync_sections()
        assert dlg._menu_var.get() is False
    finally:
        dlg._dlg.destroy()


@pytest.mark.gui
@gui_only
@pytest.mark.parametrize("key", ["jjp", "cgc"])
def test_the_menu_only_write_is_only_offered_where_the_flash_has_one(
        app, monkeypatch, tmp_path, key):
    """PAD-138: the tick asked the IMAGE whether it had a menu partition and
    never the BRAND, so a JJP USB stick's dialog carried a Stern promise ("the
    machine keeps its settings and scores"), and a CGC image with a Linux
    second partition would have ticked it ON for a flash that cannot do it.
    Same image as the Stern test above - only the brand differs."""
    _pick(app, key)
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(app, monkeypatch,
                       initial_choices={"build": False, "write": True})
    try:
        dlg._image_var.set(img)
        dlg._sync_sections()
        assert not dlg._menu_chk.winfo_manager(), "not even on the dialog"
        assert not dlg._menu_note.winfo_manager()
        assert dlg._menu_var.get() is False
    finally:
        dlg._dlg.destroy()


@pytest.mark.gui
@gui_only
def test_a_window_short_of_its_content_still_shows_start_and_cancel(
        app, monkeypatch, tmp_path):
    """A DIALOG CAN BE WRONG ABOUT ITS HEIGHT; IT MUST NOT BE ABLE TO EAT THE
    TWO CONTROLS THAT END IT.  pack() hands out space in the order things
    were packed, so whatever went in LAST is what gets squeezed when the
    window ends up short of its content - and that was the row carrying
    Start and Cancel (David: "the confirm and cancel buttons in this modal
    are squeezed to be too tiny to see" - his were 10 px of a wanted 25,
    two coloured slivers with no text in them).

    The row is packed FIRST now, against the bottom, so the body is what
    gives way instead.  Forcing the window 90 px short is this test: it is
    the state the screenshot was in, and it reproduced at exactly 10 px."""
    _pick(app, "stern")
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(app, monkeypatch,
                       initial_choices={"build": False, "write": True})
    try:
        dlg._image_var.set(img)
        dlg._sync_sections()
        app.root.update()
        w, start = dlg._dlg, dlg._start_btn
        # ...as it opens: the window is as tall as everything inside it
        assert w.winfo_height() >= w.winfo_reqheight()
        assert start.winfo_height() >= start.winfo_reqheight()
        # ...and 90 px short of that, which is what a note growing a line
        # after the geometry was pinned does to it
        w.geometry("%dx%d" % (w.winfo_width(), w.winfo_reqheight() - 90))
        app.root.update()
        assert w.winfo_height() < w.winfo_reqheight(), "the force worked"
        assert start.winfo_height() >= start.winfo_reqheight(), \
            "Start is squeezed: %d of %d" % (start.winfo_height(),
                                             start.winfo_reqheight())
        # every state of the ticks keeps it that way: each one changes the
        # note, and the readout changes with them
        for build, write, menu in ((True, True, False), (False, True, True),
                                   (False, False, False)):
            dlg._build_var.set(build)
            dlg._write_var.set(write)
            dlg._menu_var.set(menu)
            dlg._sync_sections()
            app.root.update()
            assert start.winfo_height() >= start.winfo_reqheight(), \
                "build=%s write=%s menu=%s" % (build, write, menu)
    finally:
        dlg._dlg.destroy()


# ---- a card the Multi-boot tab hands in is only written (PAD-144) -----------
def _reader():
    from pinball_decryptor.core.drives import PhysicalDrive
    return PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE9",
                         model="Generic- USB3.0 CRW -SD",
                         size_bytes=15_931_539_456, bus_type="USB")


@pytest.mark.gui
@gui_only
def test_a_card_from_the_multiboot_tab_is_only_written(app, monkeypatch,
                                                       tmp_path):
    """The tester's screenshot: the dialog the Multi-boot tab opens still
    carried the Write tab's "Build a fresh image" section and its single-game
    build path ("Could you even use this option to create a fresh build of a
    multigame?"), and Start asked "Nothing modified" - a check on Write-tab
    edits the card never came from ("its not really true since I am not
    rebuilding but pointing to a custom image")."""
    from tkinter import messagebox
    _pick(app, "stern")
    img = _spike_image_for(tmp_path)
    asked, flashed, remembered = [], [], []
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda title, *a, **k: asked.append(title) or True)
    dlg = _make_dialog(
        app, monkeypatch, initial_image=img, handed_in="Multi-boot",
        has_pending_changes=False, on_choices=remembered.append,
        initial_choices={"build": True, "write": True},
        on_flash=lambda i, d, menu_only=False: flashed.append(
            (i, d, menu_only)))
    try:
        # no Build section, and no write tick to untick into a dead Start
        assert not dlg._build_box.winfo_manager()
        assert not dlg._write_chk.winfo_manager()
        assert (dlg._build_var.get(), dlg._write_var.get()) == (False, True)
        assert dlg._image_var.get() == img
        assert dlg._start_btn.cget("text") == "Flash image"
        # unticked, the note says what the whole write is for
        dlg._menu_var.set(False)
        dlg._sync_sections()
        assert "first time" in dlg._menu_note.cget("text")
        dlg._selected = _reader()
        dlg._do_start()
        assert asked == ["Erase the SD card and continue?"]
        assert flashed == [(img, r"\\.\PHYSICALDRIVE9", False)]
        # ...and writing that card is not the Write tab's choice to remember
        assert remembered == []
    finally:
        if dlg._dlg.winfo_exists():
            dlg._dlg.destroy()


@pytest.mark.gui
@gui_only
def test_a_card_just_built_is_written_whole(app, monkeypatch, tmp_path):
    """"Only the boot menu" came up ticked on a card the Multi-boot tab had
    only just built.  That write refuses any SD card the image was not
    already flashed onto, so on a fresh card the default could only cost a
    refusal - and after an update, which rewrites game files inside the
    card, it would pass its check and leave the old games on the SD card.
    Any OTHER image picked in the box is offered it as before.  (Every image
    is "flashed" here, so the fresh card is kept off even against that.)"""
    _pick(app, "stern")
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(app, monkeypatch, initial_image=img,
                       handed_in="Multi-boot", fresh_image=True,
                       flashed_fn=lambda i: True)
    try:
        assert dlg._menu_var.get() is False
        assert "disabled" in dlg._menu_chk.state()
        assert "no SD card holds it yet" in dlg._menu_note.cget("text")
        (tmp_path / "older").mkdir()
        dlg._image_var.set(_spike_image_for(tmp_path / "older"))
        dlg._sync_sections()
        assert dlg._menu_var.get() is True
        assert "disabled" not in dlg._menu_chk.state()
    finally:
        dlg._dlg.destroy()


# ---- ...and only a card an SD card already has is ticked for it (PAD-145) ---
@pytest.mark.gui
@gui_only
def test_a_card_no_sd_card_has_had_is_not_ticked_for_the_menu(app, monkeypatch,
                                                              tmp_path):
    """"I found that 'only boot menu' was still checked off" - on a card
    built in an EARLIER run and flashed on its own, which PAD-144's fresh
    flag never sees (it is only set when the build runs in the same Start).
    The tick now waits for a flash of that image to have finished; until
    then it is offered, unticked, with a note saying why."""
    _pick(app, "stern")
    img = _spike_image_for(tmp_path)
    flashed = set()
    kw = dict(initial_image=img, handed_in="Multi-boot",
              flashed_fn=lambda i: i in flashed)
    dlg = _make_dialog(app, monkeypatch, **kw)
    try:
        assert dlg._menu_var.get() is False
        assert "disabled" not in dlg._menu_chk.state(), "still one tick away"
        assert "not been flashed onto an SD card" in dlg._menu_note.cget("text")
        dlg._menu_var.set(True)
        dlg._sync_sections()
        assert "menu partition only" in dlg._menu_note.cget("text")
    finally:
        dlg._dlg.destroy()
    # once a flash of it has finished, the next dialog ticks it again
    flashed.add(img)
    dlg = _make_dialog(app, monkeypatch, **kw)
    try:
        assert dlg._menu_var.get() is True
        dlg._menu_var.set(False)
        dlg._sync_sections()
        assert "first time this image goes onto it" in \
            dlg._menu_note.cget("text")
    finally:
        dlg._dlg.destroy()


@pytest.mark.gui
@gui_only
def test_the_window_remembers_a_flashed_image_by_what_is_in_it(app,
                                                              monkeypatch,
                                                              tmp_path):
    """The record the dialog asks: an image's identity, not its path, so a
    menu edit keeps it and a games tree written into loses it by itself."""
    win = app.window
    img = _spike_image_for(tmp_path)
    saved = []
    monkeypatch.setattr(win, "_flashed_images", [])
    monkeypatch.setattr(win, "_on_flashed_images_change", saved.append)
    assert win._image_was_flashed(img) is False
    win._remember_flashed_image(img)
    assert win._image_was_flashed(img) is True
    assert len(saved) == 1 and len(saved[0]) == 1
    win._remember_flashed_image(img)
    assert len(saved) == 1, "the same image again changes nothing"
    raw = bytearray(open(img, "rb").read())
    raw[16 * 512 + 100:16 * 512 + 116] = b"A DIFFERENT MENU"      # p2
    with open(img, "wb") as f:
        f.write(bytes(raw))
    assert win._image_was_flashed(img) is True
    raw[32 * 512 + 1024 + 0x30] ^= 0xFF                 # p3's s_wtime
    with open(img, "wb") as f:
        f.write(bytes(raw))
    assert win._image_was_flashed(img) is False
    # not a card with a menu: nothing to record, and no error
    plain = tmp_path / "plain.raw"
    plain.write_bytes(b"\x00" * 4096)
    win._remember_flashed_image(str(plain))
    assert len(saved) == 1
    assert win._image_was_flashed(str(plain)) is False


@pytest.mark.gui
@gui_only
def test_only_a_flash_that_finishes_is_recorded(app, monkeypatch, tmp_path):
    """The app's side: a failed flash leaves no SD card holding the image,
    so it must not tick the menu write next time; a finished one is saved
    in settings, since the flash is often the last thing before closing."""
    import queue
    from pinball_decryptor.core.messages import UiCallMsg
    _pick(app, "stern")
    img = _spike_image_for(tmp_path)
    win = app.window
    dones = []

    class _Idle:
        def run(self):
            pass
    monkeypatch.setattr(
        app._current_mfr, "make_flash_pipeline",
        lambda i, d, log, phase, prog, done, **kw: dones.append(done)
        or _Idle())
    monkeypatch.setattr(win, "_flashed_images", [])

    def finish(success):
        app._start_flash_image(img, r"\\.\PHYSICALDRIVE9")
        dones[-1](success, "summary")
        while True:
            try:
                msg = app.msg_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(msg, UiCallMsg):
                msg.fn()
        win.set_running(False, mode="write")
        app.pipeline, app._active_mode = None, None

    finish(False)
    assert win._image_was_flashed(img) is False
    finish(True)
    assert win._image_was_flashed(img) is True
    assert app._settings["flashed_images"] == win._flashed_images


@pytest.mark.gui
@gui_only
def test_the_multiboot_hand_off_reaches_the_dialog(app, monkeypatch,
                                                   tmp_path):
    """The wiring: the Multi-boot tab's flash_fn names the tab and passes
    fresh on; the Write tab's own button hands nothing in."""
    from pinball_decryptor.gui import flash_dialog
    _pick(app, "stern")
    win = app.window
    panel = getattr(win, "_multiboot_panel", None)
    if panel is None:
        pytest.skip("no Multi-boot tab in this build")
    img = _spike_image_for(tmp_path)
    opened = []
    monkeypatch.setattr(flash_dialog, "FlashImageDialog",
                        lambda *a, **kw: opened.append(kw))
    panel._flash_fn(img, fresh=True)
    win._open_flash_dialog()
    assert [(kw["handed_in"], kw["fresh_image"]) for kw in opened] == [
        ("Multi-boot", True), ("", False)]
    assert opened[0]["initial_image"] == img
