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

The banner tests drive the shell service's methods
(webui/tabs/shell_extras.py) against duck-typed stubs; the choices and
flashed-image memory drive the Write tab service's (webui/tabs/write.py);
the dialog tests build the Build / flash dialog's logic
(webui/write_dialogs.FlashDialog) on its own, with drive enumeration off.
"""

import os
import threading
import types

import pytest

from pinball_decryptor.core import extract_source
from pinball_decryptor.webui.tabs.shell_extras import ShellExtras
from pinball_decryptor.webui.tabs.write import WriteTab

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

class _ImmediateLoop:
    """`post` runs the callback right away: these tests are about the
    banner's decisions, not the UI loop."""

    def post(self, fn, *args):
        fn(*args)


class _BannerWindow:
    def __init__(self):
        self.banners = {}

    def set_banner(self, banner_id, spec):
        if spec is None:
            self.banners.pop(banner_id, None)
        else:
            self.banners[banner_id] = spec


class _BannerHost:
    """Just the surface the shell service's stale-source banner touches.

    The refresh is ASYNC: the staleness probe stats the source image, which
    can live on OneDrive/NAS, so it runs on a worker (a frozen post-reboot
    tab switch, 2026-08-09).  The host joins the probe before returning so
    every assertion below reads the settled answer."""

    def __init__(self, assets_dir):
        self.write_assets_var = _Var(assets_dir)
        self.window = _BannerWindow()
        self.ctx = types.SimpleNamespace(loop=_ImmediateLoop())
        self._stale_token = 0
        self._stale_dismissed = None
        self._stale_shown = None

    def _var_or_none(self, name):
        return self.write_assets_var if name == "write_assets_var" else None

    def _apply_stale_source_banner(self, *a):
        try:
            return ShellExtras._apply_stale_source_banner(self, *a)
        finally:
            self._applied.set()

    def refresh(self):
        self._applied = threading.Event()
        ShellExtras._refresh_stale_source_banner(self)
        assert self._applied.wait(5), "the staleness probe never answered"

    def dismiss(self):
        return ShellExtras._stale_banner_action(self, "dismiss_source")

    @property
    def mapped(self):
        return "stale_source" in self.window.banners


def test_dismissal_survives_the_next_launch(tmp_path):
    """The complaint was seeing it "the entire time" — a fresh window on the
    same project must not resurrect a banner already waved through."""
    _img, out = _stale_project(tmp_path)
    _BannerHost(out).dismiss()
    fresh = _BannerHost(out)        # new session, nothing in memory
    fresh.refresh()
    assert not fresh.mapped


def test_a_new_change_gets_through_a_previous_dismissal(tmp_path):
    img, out = _stale_project(tmp_path)
    _BannerHost(out).dismiss()
    _touch_later(img, 900)
    fresh = _BannerHost(out)
    fresh.refresh()
    assert fresh.mapped


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
    assert host.mapped


def test_unwritable_folder_still_hides_it_for_the_session(tmp_path,
                                                          monkeypatch):
    _img, out = _stale_project(tmp_path)

    def _boom(_dir):
        raise OSError("read-only share")

    # the service imports the name from the module at call time
    monkeypatch.setattr(extract_source, "dismiss_stale_source", _boom)
    host = _BannerHost(out)
    host.refresh()
    host.dismiss()                  # must not raise
    assert not host.mapped
    host.refresh()
    assert not host.mapped


def test_the_stale_banner_dismiss_is_a_labelled_button(tmp_path):
    """It had one all along — an unlabelled ✕ at the far right of a wide
    window, two rows under the window's own ✕, which is why the tester asked
    for a dismiss button while looking straight at it."""
    _img, out = _stale_project(tmp_path)
    host = _BannerHost(out)
    host.refresh()
    spec = host.window.banners["stale_source"]
    labels = [a["label"] for a in spec["actions"]]
    assert "Dismiss" in labels, labels
    assert "✕" not in labels
    assert spec["dismiss"] is False, "no bare close cross beside it"


# ---------------------------------------------------------------------------
# "The Build/Flash screen does not remember your selections between sessions"
# ---------------------------------------------------------------------------

class _ChoicesHost:
    def __init__(self, saved=None, sink=None):
        self._saved_flash_choices = dict(saved or {})
        cb = {"on_flash_choices_change": sink} if sink else {}
        self.window = types.SimpleNamespace(cb=cb)

    remember = WriteTab._remember_flash_choices


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


# ---- the dialog's logic ----------------------------------------------------

class _NoLoop:
    def post(self, fn, *args):
        pass


def _mfr(key):
    from pinball_decryptor.core.registry import get_manufacturer, load_plugins
    load_plugins()
    mfr = get_manufacturer(key)
    assert mfr is not None, key
    return mfr


def _make_dialog(monkeypatch, key="stern", **kw):
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    monkeypatch.setattr(FlashDialog, "refresh_drives", lambda self: None)
    defaults = dict(
        host=_NoLoop(), manufacturer=_mfr(key),
        on_flash=lambda i, d, **k: None, on_build_flash=lambda b, d: None,
        build_target=FAKE_BUILD, can_build=True, has_pending_changes=True)
    defaults.update(kw)
    return FlashDialog(**defaults)


def _answer_modals(monkeypatch, asked=None, warned=None):
    from pinball_decryptor.webui import compat
    asked = [] if asked is None else asked
    monkeypatch.setattr(compat.messagebox, "askyesno",
                        lambda title, *a, **k: asked.append(title) or True)
    if warned is not None:
        monkeypatch.setattr(compat.messagebox, "showwarning",
                            lambda title, *a, **k: warned.append(title))
    return asked


def test_dialog_opens_on_the_pair_you_last_ran(monkeypatch):
    """The exact report: build only, come back, both boxes ticked again."""
    dlg = _make_dialog(monkeypatch,
                       initial_choices={"build": True, "write": False})
    assert dlg.build is True
    assert dlg.write is False
    assert dlg.start_label() == "Build image"


def test_start_records_the_pair_and_cancel_does_not(monkeypatch):
    seen = []
    dlg = _make_dialog(monkeypatch, on_choices=seen.append)
    dlg.set("write", False)
    dlg.close()
    assert seen == [], "a cancelled dialog must not rewrite the memory"

    dlg = _make_dialog(monkeypatch, on_choices=seen.append)
    dlg.set("write", False)
    assert dlg.start() is True
    assert seen == [{"write": False, "build": True}]


def test_a_disabled_build_box_is_not_a_choice(monkeypatch):
    """Build unavailable (Write tab not set up) forces the box off — recording
    that would open build-less next time, once the tab IS set up."""
    seen = []
    dlg = _make_dialog(monkeypatch, can_build=False, on_choices=seen.append)
    dlg._remember_choices()
    assert seen == [{"write": True}]


def test_a_remembered_pair_beats_the_no_changes_default(monkeypatch):
    """Having run build-only before outranks "nothing is modified"; the
    "Nothing modified — build anyway?" confirm still catches an accident."""
    dlg = _make_dialog(monkeypatch, has_pending_changes=False,
                       initial_choices={"build": True, "write": False})
    assert dlg.build is True
    assert dlg.write is False


def test_an_all_off_memory_falls_back_to_the_defaults(monkeypatch):
    """A dialog that opens with Start greyed out looks broken."""
    dlg = _make_dialog(monkeypatch,
                       initial_choices={"build": False, "write": False})
    assert dlg.build is True
    assert dlg.write is True
    assert dlg.state()["start_enabled"] is True


def test_a_remembered_build_cannot_tick_an_impossible_box(monkeypatch):
    dlg = _make_dialog(monkeypatch, can_build=False,
                       initial_choices={"build": True, "write": True})
    assert dlg.build is False


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


def test_the_flash_dialog_offers_the_menu_only_write(monkeypatch, tmp_path):
    """A 14.7 GB image on an ordinary card is forty minutes; its MENU is one
    partition and about a minute.  The option defaults ON for an image that
    has one and that a flash has already put onto an SD card (David, twice:
    "flashing the whole thing takes over an hour with my slow sd card"; the
    never-flashed case is PAD-145's test below)."""
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(monkeypatch,
                       initial_choices={"build": False, "write": True},
                       flashed_fn=lambda i: True)
    dlg.set("image_path", img)
    assert dlg.menu is True, "on by default when it can be"
    assert dlg.menu_enabled is True
    assert "menu partition only" in dlg.menu_note
    # ...and never for a build+flash: a fresh image was never on that card
    dlg.set("build", True)
    assert dlg.menu is False
    assert "has to be written" in dlg.menu_note
    # ...nor for something that is not a card image at all
    dlg.set("build", False)
    plain = tmp_path / "notacard.raw"
    plain.write_bytes(b"\x00" * 4096)
    dlg.set("image_path", str(plain))
    assert dlg.menu is False


@pytest.mark.parametrize("key", ["jjp", "cgc"])
def test_the_menu_only_write_is_only_offered_where_the_flash_has_one(
        monkeypatch, tmp_path, key):
    """PAD-138: the tick asked the IMAGE whether it had a menu partition and
    never the BRAND, so a JJP USB stick's dialog carried a Stern promise ("the
    machine keeps its settings and scores"), and a CGC image with a Linux
    second partition would have ticked it ON for a flash that cannot do it.
    Same image as the Stern test above - only the brand differs."""
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(monkeypatch, key=key,
                       initial_choices={"build": False, "write": True},
                       flashed_fn=lambda i: True)
    dlg.set("image_path", img)
    st = dlg.state()
    assert st["menu_offered"] is False, "not even on the dialog"
    assert st["menu_enabled"] is False
    assert st["menu"] is False


# ---- a card the Multi-boot tab hands in is only written (PAD-144) -----------
def _reader():
    from pinball_decryptor.core.drives import PhysicalDrive
    return PhysicalDrive(device_path=r"\\.\PHYSICALDRIVE9",
                         model="Generic- USB3.0 CRW -SD",
                         size_bytes=15_931_539_456, bus_type="USB")


def test_a_card_from_the_multiboot_tab_is_only_written(monkeypatch, tmp_path):
    """The tester's screenshot: the dialog the Multi-boot tab opens still
    carried the Write tab's "Build a fresh image" section and its single-game
    build path ("Could you even use this option to create a fresh build of a
    multigame?"), and Start asked "Nothing modified" - a check on Write-tab
    edits the card never came from ("its not really true since I am not
    rebuilding but pointing to a custom image")."""
    img = _spike_image_for(tmp_path)
    asked = _answer_modals(monkeypatch)
    flashed, remembered = [], []
    dlg = _make_dialog(
        monkeypatch, initial_image=img, handed_in="Multi-boot",
        has_pending_changes=False, on_choices=remembered.append,
        initial_choices={"build": True, "write": True},
        on_flash=lambda i, d, menu_only=False: flashed.append(
            (i, d, menu_only)))
    st = dlg.state()
    # no Build section, and no write tick to untick into a dead Start
    assert st["handed_in"] is True and st["can_build"] is False
    assert (dlg.build, dlg.write) == (False, True)
    assert dlg.image_path == img
    assert dlg.start_label() == "Flash image"
    # unticked, the note says what the whole write is for
    dlg.set("menu", False)
    assert "first time" in dlg.menu_note
    dlg.selected = _reader()
    assert dlg.start() is True
    assert asked == ["Erase the SD card and continue?"]
    assert flashed == [(img, r"\\.\PHYSICALDRIVE9", False)]
    # ...and writing that card is not the Write tab's choice to remember
    assert remembered == []


def test_a_card_just_built_is_written_whole(monkeypatch, tmp_path):
    """"Only the boot menu" came up ticked on a card the Multi-boot tab had
    only just built.  That write refuses any SD card the image was not
    already flashed onto, so on a fresh card the default could only cost a
    refusal - and after an update, which rewrites game files inside the
    card, it would pass its check and leave the old games on the SD card.
    Any OTHER image picked in the box is offered it as before.  (Every image
    is "flashed" here, so the fresh card is kept off even against that.)"""
    img = _spike_image_for(tmp_path)
    dlg = _make_dialog(monkeypatch, initial_image=img,
                       handed_in="Multi-boot", fresh_image=True,
                       flashed_fn=lambda i: True)
    assert dlg.menu is False
    assert dlg.menu_enabled is False
    assert "no SD card holds it yet" in dlg.menu_note
    (tmp_path / "older").mkdir()
    dlg.set("image_path", _spike_image_for(tmp_path / "older"))
    assert dlg.menu is True
    assert dlg.menu_enabled is True


# ---- ...and only a card an SD card already has is ticked for it (PAD-145) ---
def test_a_card_no_sd_card_has_had_is_not_ticked_for_the_menu(monkeypatch,
                                                              tmp_path):
    """"I found that 'only boot menu' was still checked off" - on a card
    built in an EARLIER run and flashed on its own, which PAD-144's fresh
    flag never sees (it is only set when the build runs in the same Start).
    The tick now waits for a flash of that image to have finished; until
    then it is offered, unticked, with a note saying why."""
    img = _spike_image_for(tmp_path)
    flashed = set()
    kw = dict(initial_image=img, handed_in="Multi-boot",
              flashed_fn=lambda i: i in flashed)
    dlg = _make_dialog(monkeypatch, **kw)
    assert dlg.menu is False
    assert dlg.menu_enabled is True, "still one tick away"
    assert "not been flashed onto an SD card" in dlg.menu_note
    dlg.set("menu", True)
    assert "menu partition only" in dlg.menu_note
    dlg.close()
    # once a flash of it has finished, the next dialog ticks it again
    flashed.add(img)
    dlg = _make_dialog(monkeypatch, **kw)
    assert dlg.menu is True
    dlg.set("menu", False)
    assert "first time this image goes onto it" in dlg.menu_note


class _FlashedHost:
    def __init__(self, sink):
        self._flashed_images = []
        self.window = types.SimpleNamespace(
            cb={"on_flashed_images_change": sink})

    _remember_flashed_image = WriteTab._remember_flashed_image
    _image_was_flashed = WriteTab._image_was_flashed


def test_the_window_remembers_a_flashed_image_by_what_is_in_it(tmp_path):
    """The record the dialog asks: an image's identity, not its path, so a
    menu edit keeps it and a games tree written into loses it by itself."""
    img = _spike_image_for(tmp_path)
    saved = []
    win = _FlashedHost(saved.append)
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


def test_only_a_flash_that_finishes_is_recorded(monkeypatch, tmp_path):
    """The app's side: a failed flash leaves no SD card holding the image,
    so it must not tick the menu write next time; a finished one is saved
    in settings, since the flash is often the last thing before closing."""
    import time
    from tests.webui_harness import web_app
    img = _spike_image_for(tmp_path)
    dones = []

    class _Idle:
        def run(self):
            pass

    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        monkeypatch.setattr(
            app._current_mfr, "make_flash_pipeline",
            lambda i, d, log, phase, prog, done, **kw: dones.append(done)
            or _Idle())

        def finish(success):
            w.run(app._start_flash_image, img, r"\\.\PHYSICALDRIVE9")
            dones[-1](success, "summary")
            end = time.time() + 10
            while w.window._running and time.time() < end:
                time.sleep(0.05)
            w.drain()
            assert not w.window._running, "the flash never ended"

        finish(False)
        assert w.window._image_was_flashed(img) is False
        finish(True)
        assert w.window._image_was_flashed(img) is True
        svc = w.window.service("write")
        assert app._settings["flashed_images"] == svc._flashed_images


def test_a_jjp_iso_can_go_straight_onto_the_games_disk(monkeypatch, tmp_path):
    """Item 123: the dialog's second place for a JJP install ISO - the game's SSD in a
    dock.  Choosing it swaps the drive picker to disks, words the confirmation as an
    install that wipes the disk, and hands ``target="disk"`` to the app; the stick, the
    default, hands nothing new."""
    img = tmp_path / "GunsNRoses-v03.03.multi.iso"
    img.write_bytes(b"iso")
    asked = _answer_modals(monkeypatch)
    flashed = []

    def dialog():
        return _make_dialog(
            monkeypatch, key="jjp", initial_image=str(img),
            handed_in="Multi-boot", has_pending_changes=False,
            on_flash=lambda i, d, menu_only=False, **kw: flashed.append(
                (i, d, kw)))

    dlg = dialog()
    assert [t[0] for t in dlg._targets] == ["stick", "disk"], \
        "JJP offers the disk as a second place"
    assert dlg.target == "stick" and not dlg.to_disk()
    assert dlg.words["target_kind"] == "usb_stick"
    # the disk: the picker's kind and label follow, the readout says what happens
    dlg.set("target", "disk")
    assert dlg.to_disk()
    assert dlg.words["target_kind"] == "ssd"
    assert dlg.words["target_label"] == "Target disk:"
    dlg.selected = _reader()
    assert "erased" in dlg.readout()[0]
    assert dlg.start() is True
    assert asked == ["Erase the disk and install onto it?"]
    assert flashed == [(str(img), r"\\.\PHYSICALDRIVE9", {"target": "disk"})]
    # ...and back on the stick nothing new travels
    asked.clear()
    flashed.clear()
    dlg = dialog()
    dlg.selected = _reader()
    assert dlg.start() is True
    assert flashed == [(str(img), r"\\.\PHYSICALDRIVE9", {})]
    assert asked and asked[0].startswith("Erase the USB stick")


def test_the_disk_target_offers_the_menu_alone_and_one_image_alone(monkeypatch, tmp_path):
    """Item 124: with the disk chosen, a Write choice appears - everything, only the menu,
    only image 0/1 (named by the tab's titles) from its own ISO - and each reaches the app as
    ``disk_mode`` (+ ``image`` and ``from_iso``); the image write refuses to start without
    its ISO."""
    img = tmp_path / "GunsNRoses-v03.03.multi.iso"
    img.write_bytes(b"iso")
    new = tmp_path / "CHAKAs_v2.iso"
    new.write_bytes(b"iso")
    flashed, warned = [], []
    asked = _answer_modals(monkeypatch, warned=warned)

    def dialog():
        return _make_dialog(
            monkeypatch, key="jjp", initial_image=str(img),
            handed_in="Multi-boot", has_pending_changes=False,
            image_titles=["GUNS N' ROSES 3.03", "CHAKA'S LOTLJ"],
            on_flash=lambda i, d, menu_only=False, **kw: flashed.append(
                (i, d, kw)))

    dlg = dialog()
    assert dlg.state()["show_disk_mode"] is False, "no Write row for the stick"
    dlg.set("target", "disk")
    st = dlg.state()
    assert st["show_disk_mode"] is True and st["show_from"] is False
    labels = [lbl for _k, lbl in dlg.disk_modes()]
    assert labels[0].startswith("everything") and labels[1].startswith("only the boot menu")
    assert labels[2] == "only image 0: GUNS N' ROSES 3.03, from its own ISO"
    assert labels[3] == "only image 1: CHAKA'S LOTLJ, from its own ISO"
    # the menu alone
    dlg.set("disk_mode", "menu")
    assert dlg.current_disk_mode() == "menu" and not dlg.state()["show_from"]
    dlg.selected = _reader()
    assert "only the boot menu" in dlg.readout()[0]
    assert dlg.start() is True
    assert asked == ["Replace the boot menu?"]
    assert flashed == [(str(img), r"\\.\PHYSICALDRIVE9", {"target": "disk", "disk_mode": "menu"})]
    asked.clear()
    flashed.clear()
    dlg = dialog()
    dlg.set("target", "disk")
    dlg.set("disk_mode", "image1")
    assert dlg.current_disk_mode() == "image1" and dlg.state()["show_from"]
    dlg.selected = _reader()
    assert "still to pick" in dlg.readout()[0]
    assert dlg.start() is False
    assert warned == ["No ISO for the image"] and flashed == []
    dlg.set("from_path", str(new))
    assert "CHAKAs_v2.iso" in dlg.readout()[0]
    assert dlg.start() is True
    assert asked == ["Replace image 1?"]
    assert flashed == [(str(img), r"\\.\PHYSICALDRIVE9",
                        {"target": "disk", "disk_mode": "image", "image": 1, "from_iso": str(new)})]
    # back on the stick the Write row goes away and nothing new travels
    flashed.clear()
    asked.clear()
    dlg = dialog()
    dlg.set("target", "disk")
    dlg.set("target", "stick")
    st = dlg.state()
    assert not st["show_disk_mode"] and not st["show_from"]
    dlg.selected = _reader()
    assert dlg.start() is True
    assert flashed == [(str(img), r"\\.\PHYSICALDRIVE9", {})]
