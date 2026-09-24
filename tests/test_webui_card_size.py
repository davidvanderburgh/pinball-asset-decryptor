"""The Write tab's "SD card size" (Stern Spike 2, plugins/stern/card_size.py):
the setting persists and is mirrored into PAD_STERN_CARD_SIZE the way the
grow-for-longer-text option is, and the control is offered only for an
original laid out the way Stern lays a Spike 2 card out, with the sizes bigger
than that card's own and a note saying what the original is, how much room
its games partition has at each size, and what the choice costs.  A build the
engine's pre-flight refuses for space is one clean dialog.  The size the
control knows is used wherever a build's size
matters: the default build name, the Build / flash dialog's fit check, the
Build / flash dialog's Start (a size the original, or this computer, can't
build is refused before any of its questions and before anything is
staged), and Port + build (other cards build at their own size).  The
originals here are SPARSE synthetic cards: the real MBR and EBR entries at
their real places, nothing else written.  Every test runs as on a computer
that offers the option (the CI's macOS leg included) and can grow a card,
unless it says otherwise."""

import json
import os
import queue
import struct
import time
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.webui.tabs import write as write_mod
from tests.conftest import sparse_image
from tests.webui_harness import web_app

ENV = cs.ENV
#: the real platform rule, before the autouse fixture pins it
_REAL_SUPPORTED = write_mod.card_size_supported

# (p3 sector count, p4 start LBA) as Stern ships each class
TABLES = {
    "8G": (13402110, 14114816),
    "16G": (28311550, 29024256),
    "32G": (57343998, 58056704),
}
P4_COUNT = 1239038


@pytest.fixture(autouse=True)
def _no_card_size_env(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


@pytest.fixture(autouse=True)
def _a_computer_that_can_grow_a_card(monkeypatch):
    """Every test runs as on a computer the option is offered on, whatever
    runs it: the CI's macOS leg too (card_size_supported is False on darwin,
    which hides the control; test_not_offered_on_macos is that case).  And
    "can this computer grow a card?" answers yes without starting any Linux
    (card_size._E2fs runs WSL or sudo); each test starts with no answer."""
    monkeypatch.setattr(write_mod, "card_size_supported",
                        lambda platform=None: _REAL_SUPPORTED(
                            platform or "linux"))
    monkeypatch.setattr(cs, "supported", lambda: True)
    monkeypatch.setattr(cs, "_E2fs", lambda: None)
    monkeypatch.setattr(write_mod, "_GROW_HERE",
                        {"why": None, "at": None, "busy": False})


def _entry(ptype, start, count):
    """One 16-byte partition entry (Stern's capped CHS bytes)."""
    return (bytes.fromhex("0003e0ff") + bytes([ptype])
            + bytes.fromhex("03e0ff") + struct.pack("<II", start, count))


def make_card(path, cls="8G", size=None):
    """A sparse Stern-shaped Spike 2 card image of class *cls*: only the MBR
    and the two EBRs are written; the file costs a few KB on any disk.
    *size* makes the FILE longer than its table (a dump of a whole bigger SD
    card)."""
    p3c, p4s = TABLES[cls]
    sparse_image(str(path), size or cs.CARD_SIZES[cls])
    mbr = bytearray(512)
    mbr[446:462] = _entry(0x0C, 8192, 16384)
    mbr[462:478] = _entry(0x83, 24576, 688128)
    mbr[478:494] = _entry(0x83, 712704, p3c)
    mbr[494:510] = _entry(0x0F, p4s, P4_COUNT)
    mbr[510:512] = b"\x55\xaa"
    ebr1 = bytearray(512)
    ebr1[446:462] = _entry(0x83, 2048, 147454)
    ebr1[462:478] = _entry(0x05, 149502, 1089536)
    ebr1[510:512] = b"\x55\xaa"
    ebr2 = bytearray(512)
    ebr2[446:462] = _entry(0x83, 2, 1089534)
    ebr2[510:512] = b"\x55\xaa"
    with open(path, "r+b") as f:
        for lba, sec in ((0, mbr), (p4s, ebr1), (p4s + 149502, ebr2)):
            f.seek(lba * 512)
            f.write(bytes(sec))
    return path


def wait_for(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    w.drain()
    return pred()


def point_at(w, original):
    w.call("ui.set", "extract", "input", str(original))
    w.drain()


def values(s):
    return [o["value"] for o in s["card_size_options"]]


# ----------------------------------------------------------------- fixture
def test_the_fixture_is_a_card_card_size_reads(tmp_path):
    for cls in TABLES:
        p = make_card(tmp_path / ("%s.raw" % cls), cls)
        with open(p, "rb") as f:
            layout = cs.read_layout(f)
        assert cs.class_of(layout.laid_out) == cls
        os.remove(p)


# ------------------------------------------------------ setting + env var
def test_setting_persists_and_mirrors_the_env(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        settings_file = tmp_path / "cfg" / "settings.json"
        assert win.card_size_choice() == ""
        assert ENV not in os.environ
        w.call("ui.set", "write", "card_size", "16G")
        assert win.card_size_choice() == "16G"
        assert os.environ.get(ENV) == "16G"
        assert w.app._settings.get("card_size") == "16G"
        saved = json.loads(settings_file.read_text(encoding="utf-8"))
        assert saved.get("card_size") == "16G"
        w.call("ui.set", "write", "card_size", "32G")
        assert os.environ.get(ENV) == "32G"
        # the original's own size: the var is UNSET, not "" or "8G"
        w.call("ui.set", "write", "card_size", "")
        assert ENV not in os.environ
        assert w.app._settings.get("card_size") == ""
        # anything else reads as the original's size
        w.call("ui.set", "write", "card_size", "64G")
        assert win.write_card_size_var.get() == ""
        assert win.card_size_choice() == ""
        assert ENV not in os.environ
        # the run logic's own mirror before a build (app._start_write)
        w.call("ui.set", "write", "card_size", "32G")
        os.environ.pop(ENV, None)
        w.app._apply_card_size_env(win.card_size_choice())
        assert os.environ.get(ENV) == "32G"


@pytest.mark.parametrize("saved,want", [("32G", "32G"), ("16g", "16G"),
                                        ("8G", ""), ("huge", ""), (16, "")])
def test_saved_setting_applies_at_startup(tmp_path, saved, want):
    with web_app(tmp_path, mfr="stern", settings={"card_size": saved}) as w:
        assert w.window.card_size_choice() == want
        assert os.environ.get(ENV) == (want or None)


def test_env_name_is_card_size_env():
    from pinball_decryptor.app import App
    assert App._CARD_SIZE_ENV == cs.ENV


def test_the_engine_hint_names_this_control():
    """The engine's no-space failure sends the user to "SD card size on the
    Write tab": the control must be called that."""
    import inspect

    from pinball_decryptor.plugins.stern import engine
    from pinball_decryptor.webui.tabs import write
    assert write.CARD_SIZE_LABEL == "SD card size"
    assert "SD card size on the Write tab" in " ".join(
        inspect.getsource(engine._bigger_card_hint).split())


# ------------------------------------------------------------- capability
def test_no_control_without_a_spike2_card(tmp_path):
    junk = tmp_path / "not-a-card.raw"
    junk.write_bytes(b"\0" * 4096)
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("write")["card_size_cap"] is False
        point_at(w, junk)
        svc = w.window.service("write")
        assert wait_for(w, lambda: svc._card_probe is not None)
        s = w.state("write")
        assert s["card_size_cap"] is False
        assert s["card_size_options"] == []
        assert s["card_size_note"] == ""
        # a missing original: nothing to show either
        point_at(w, tmp_path / "gone.raw")
        w.drain()
        assert w.state("write")["card_size_cap"] is False


def test_an_8g_original_offers_16_and_32(tmp_path):
    card = make_card(tmp_path / "gz.raw", "8G")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert s["card_size_label"] == "SD card size"
        assert "games partition" in s["card_size_tip"]
        assert s["card_size_options"] == [
            {"value": "", "label": "Same as the original"},
            {"value": "16G", "label": "16 GB card"},
            {"value": "32G", "label": "32 GB card"}]
        assert s["card_size_shown"] == ""
        assert s["card_size_note"] == "The original is an 8 GB card."
        assert s["card_size_note_kind"] == ""
        w.call("ui.set", "write", "card_size", "16G")
        s = w.state("write")
        assert s["card_size_shown"] == "16G"
        assert s["card_size_note"] == (
            "The original is an 8 GB card. The built image is 15.49 GB and "
            "needs an SD card of at least 16 GB; flashing it takes longer.")
        w.call("ui.set", "write", "card_size", "32G")
        assert w.state("write")["card_size_note"].endswith(
            "The built image is 30.36 GB and needs an SD card of at least "
            "32 GB; flashing it takes longer.")


def test_a_16g_original_offers_only_32(tmp_path):
    card = make_card(tmp_path / "jaws.raw", "16G")
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert values(s) == ["", "32G"]
        # 16 GB asked for, and the card is that already: the build is the
        # original's size, and the control says so
        assert s["card_size_shown"] == ""
        assert s["card_size_note"] == "The original is a 16 GB card."
        w.call("ui.set", "write", "card_size", "32G")
        s = w.state("write")
        assert s["card_size_shown"] == "32G"
        assert "at least 32 GB" in s["card_size_note"]


def test_a_32g_original_has_nothing_to_offer(tmp_path):
    card = make_card(tmp_path / "met.raw", "32G")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        svc = w.window.service("write")
        assert wait_for(w, lambda: svc._card_probe is not None)
        assert svc._card_probe["own"] == "32G"
        assert w.state("write")["card_size_cap"] is False


def test_the_original_changing_re_reads_it(tmp_path):
    small = make_card(tmp_path / "gz.raw", "8G")
    big = make_card(tmp_path / "jaws.raw", "16G")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, small)
        assert wait_for(w, lambda: values(w.state("write")) == ["", "16G",
                                                                 "32G"])
        point_at(w, big)
        assert wait_for(w, lambda: values(w.state("write")) == ["", "32G"])


# ------------------------------------------------- can't be built that big
def test_a_size_this_original_cant_take_is_shown_in_red(tmp_path):
    junk = tmp_path / "hand-edited.raw"
    junk.write_bytes(b"\0" * 4096)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, junk)
        # the build would be refused: the control is on screen with the
        # reason, and the way back to the original's size
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert s["card_size_note_kind"] == "err"
        # the class in the control's own words, never card_size's "16G"
        assert s["card_size_note"].startswith(
            "This card can't be built for a 16 GB SD card:")
        assert "16G" not in s["card_size_note"]
        assert values(s) == ["", "16G"]
        assert s["card_size_shown"] == "16G"
        w.call("ui.set", "write", "card_size", "")
        s = w.state("write")
        assert s["card_size_cap"] is False
        assert ENV not in os.environ


def _multi_boot(monkeypatch):
    from pinball_decryptor.plugins.stern import multiimage
    monkeypatch.setattr(multiimage, "images_for_path",
                        lambda p: ["godzilla", "jaws"])


def test_a_multi_boot_card_offers_no_size(tmp_path, monkeypatch):
    """A multi-boot store card is laid out like a stock one, and target_for
    refuses it at every size: nothing is offered, so the control is not
    there (the Multi-boot tab sizes those cards)."""
    card = make_card(tmp_path / "multi.raw", "8G")
    _multi_boot(monkeypatch)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        svc = w.window.service("write")
        assert wait_for(w, lambda: svc._card_probe is not None)
        assert svc._card_probe["own"] == "8G"
        assert all(svc._card_probe["why"][c][1] for c in ("16G", "32G"))
        s = w.state("write")
        assert s["card_size_cap"] is False
        assert s["card_size_options"] == []


def test_a_multi_boot_card_asked_for_a_size_says_why_not(tmp_path,
                                                         monkeypatch):
    card = make_card(tmp_path / "multi.raw", "8G")
    _multi_boot(monkeypatch)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "32G"}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert s["card_size_note_kind"] == "err"
        assert "multi-boot card" in s["card_size_note"]
        assert "32 GB SD card" in s["card_size_note"]
        assert s["card_size_shown"] == "32G"
        # only the way back, and the size asked for: never 16 GB, which
        # would be refused just the same
        assert values(s) == ["", "32G"]
        # the Build button's question gets the same sentence
        problem = w.run(w.window.card_size_problem)
        assert problem == s["card_size_note"]
        w.call("ui.set", "write", "card_size", "")
        assert w.state("write")["card_size_cap"] is False
        assert w.run(w.window.card_size_problem) == ""


def test_help_has_the_tip():
    from pinball_decryptor.webui.help_content import HELP_CONTENT
    titles = {t: b for t, b in HELP_CONTENT["Write"]}
    body = titles["SD card size (Stern Spike 2)"]
    assert "games partition" in body
    assert "macOS" in body
    assert "Pinball Browser" not in body
    # a name with no card size in it is the same at every size
    # (_name_for_class), so Help never promises the builds land side by side
    assert "Any other name stays the same at every size" in body
    assert "doesn't replace a build made at the original's size" not in body


def test_card_class_words():
    from pinball_decryptor.plugins.stern.pipeline import card_class_words
    assert card_class_words(
        "a 16G SD card, a 32G card and an 8G one (16G, and the original's)"
    ) == ("a 16 GB SD card, a 32 GB card and an 8 GB one (16 GB, and the "
          "original's)")
    assert card_class_words("128G, 16GB and x16G stay") == \
        "128G, 16GB and x16G stay"
    assert card_class_words("this build is for 32G.") == \
        "this build is for 32 GB."
    assert card_class_words(None) == ""


@pytest.mark.parametrize("path", [
    # a grown build's default name, as losetup and an OSError quote it
    "/mnt/c/b/Godzilla_Pro-1_16_0-Release.16G.sdcard-modified.raw",
    r"'\\?\D:\builds\Godzilla_Pro-1_16_0-Release.16G.sdcard-modified.raw'",
    # the class as a folder, and a name the swap left before "-modified"
    r"D:\builds\16G\gz.raw", "/builds/16G/gz.raw", "/b/gz 16G-modified.raw",
    "/b/gz 16G.raw",
])
def test_card_class_words_leaves_a_file_name_alone(path):
    """A failed grow quotes the build's own path, and a grown build's default
    name carries its class: the message must name the file that is there."""
    from pinball_decryptor.plugins.stern.pipeline import card_class_words
    text = ("This card can't be built for a 16G SD card: losetup: %s: failed "
            "to set up loop device" % path)
    assert card_class_words(text) == (
        "This card can't be built for a 16 GB SD card: losetup: %s: failed "
        "to set up loop device" % path)


# ------------------------------------------------- where it can't be done
def test_only_macos_cant_grow_a_card():
    assert _REAL_SUPPORTED("darwin") is False
    assert _REAL_SUPPORTED("win32") is True
    assert _REAL_SUPPORTED("linux") is True


def test_not_offered_on_macos(tmp_path, monkeypatch):
    """macOS: card_size can't grow a card there (no loop devices), so the
    control is not offered, and a saved size builds the original's (the
    app's own normaliser asks the same function).  The platform is darwin's
    here whatever runs the test."""
    card = make_card(tmp_path / "gz.raw", "8G")
    monkeypatch.setattr(write_mod, "card_size_supported",
                        lambda platform=None: _REAL_SUPPORTED(
                            platform or "darwin"))
    monkeypatch.setattr(cs, "supported", lambda: False)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        assert w.window.card_size_choice() == ""
        assert ENV not in os.environ
        point_at(w, card)
        w.drain()
        assert w.state("write")["card_size_cap"] is False
        assert w.run(w.window.card_size_problem) == ""
        w.call("ui.set", "write", "card_size", "32G")
        assert w.window.card_size_choice() == ""
        assert ENV not in os.environ
        # and nothing asked whether this computer can grow a card
        w.drain()
        assert write_mod._GROW_HERE == {"why": None, "at": None,
                                        "busy": False}


# ------------------------------------------------ what the build really is
def test_a_longer_original_file_gives_the_real_built_size(tmp_path):
    """card_size.plan keeps an original FILE that is longer than its table
    (a dump of a whole 32 GB SD card holding an 8 GB card): the note gives
    that size, not the class size it would not fit."""
    dump = 31914983424
    card = make_card(tmp_path / "dump.raw", "8G", size=dump)
    with open(card, "rb") as f:
        assert cs.plan(cs.read_layout(f), "16G")[1].size == dump
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        assert w.state("write")["card_size_note"] == (
            "The original is an 8 GB card in a 31.91 GB file. The built "
            "image is 31.91 GB, as long as the original file, so it needs an "
            "SD card that holds at least 31.91 GB; flashing it takes longer.")


@pytest.mark.parametrize("name,cls,want", [
    ("g.Release.8G.sdcard-modified.raw", "16G",
     "g.Release.16G.sdcard-modified.raw"),
    ("j.Release.16G.sdcard.raw", "32G", "j.Release.32G.sdcard.raw"),
    ("a_8G_b_8G.raw", "16G", "a_8G_b_16G.raw"),
    ("custom-modified.raw", "16G", "custom-modified.raw"),
    ("card-128G.raw", "16G", "card-128G.raw"),
    ("x.8GB.raw", "16G", "x.8GB.raw"),
])
def test_name_for_class(name, cls, want):
    assert write_mod._name_for_class(name, cls) == want


def test_the_build_is_named_for_its_card_size(tmp_path):
    card = make_card(tmp_path / "gz_pro-1_16_0_spike2.Release.8G.sdcard.raw")
    named = "gz_pro-1_16_0_spike2.Release.%s.sdcard-modified.raw"
    with web_app(tmp_path, mfr="stern") as w:
        name = w.window.write_filename_var.get
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        assert name() == named % "8G"
        w.call("ui.set", "write", "card_size", "16G")
        assert name() == named % "16G"
        assert w.state("write")["build_path"].endswith(named % "16G")
        # a stock card grows: nothing to refuse
        assert w.run(w.window.card_size_problem) == ""
        w.call("ui.set", "write", "card_size", "32G")
        assert name() == named % "32G"
        w.call("ui.set", "write", "card_size", "")
        assert name() == named % "8G"
        # a name the user typed is theirs
        w.call("ui.set", "write", "filename", "mine.raw")
        w.call("ui.set", "write", "card_size", "16G")
        assert name() == "mine.raw"


# ------------------------------------------------- the Build / flash dialog
class _NoLoop:
    def post(self, fn, *args):
        pass


def _flash_dialog(monkeypatch, tmp_path, stale_size=4096, **kw):
    """The dialog with Build and Flash ticked, an 8 GB SD card picked, and
    the file an EARLIER build left at the build path."""
    from pinball_decryptor.core.registry import get_manufacturer, load_plugins
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    load_plugins()
    monkeypatch.setattr(FlashDialog, "refresh_drives", lambda self: None)
    stale = tmp_path / "last-build.raw"
    sparse_image(str(stale), stale_size)
    dlg = FlashDialog(_NoLoop(), get_manufacturer("stern"),
                      lambda *a, **k: None,
                      on_build_flash=lambda *a, **k: None,
                      build_target=str(stale), can_build=True,
                      initial_choices={"build": True, "write": True}, **kw)
    dlg.selected = SimpleNamespace(size_bytes=7948206080,
                                   display="8 GB SD card")
    assert dlg.building and dlg.write
    return dlg


def test_flash_dialog_checks_the_size_the_build_will_be(tmp_path,
                                                         monkeypatch):
    from pinball_decryptor.webui import compat
    hint = "or pick a smaller SD card size on the Write tab"
    dlg = _flash_dialog(monkeypatch, tmp_path,
                        build_size=cs.CARD_SIZES["16G"],
                        build_size_hint=hint)
    text, kind = dlg.readout()
    assert kind == "err"
    assert "15.49 GB" in text and "7.95 GB" in text and hint in text
    errors = []
    monkeypatch.setattr(compat.messagebox, "showerror",
                        lambda title, msg=None, **k: errors.append(
                            (title, msg)))
    assert dlg.start() is False
    assert [t for t, _m in errors] == ["Image too big"]
    assert "15.49 GB" in errors[0][1] and hint in errors[0][1]


def test_flash_dialog_ignores_a_stale_bigger_build(tmp_path, monkeypatch):
    """A 16 GB build sits at the build path and the next one is for the
    original's size: it fits the 8 GB SD card."""
    dlg = _flash_dialog(monkeypatch, tmp_path,
                        stale_size=cs.CARD_SIZES["16G"],
                        build_size=cs.CARD_SIZES["8G"])
    text, kind = dlg.readout()
    assert kind == "ok", text
    assert "7.86 GB" in text


def test_flash_dialog_without_a_known_size_reads_the_file(tmp_path,
                                                          monkeypatch):
    dlg = _flash_dialog(monkeypatch, tmp_path)
    assert dlg.readout()[1] == "ok"


def test_the_tab_hands_the_dialog_the_build_size(tmp_path, monkeypatch):
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    monkeypatch.setattr(FlashDialog, "refresh_drives", lambda self: None)
    card = make_card(tmp_path / "gz.Release.8G.sdcard.raw")
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        w.call("ui.set", "write", "assets", str(proj))
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        svc = w.window.service("write")
        for choice, size in (("", cs.CARD_SIZES["8G"]),
                             ("16G", cs.CARD_SIZES["16G"])):
            w.call("ui.set", "write", "card_size", choice)
            assert w.run(svc._open_flash_dialog) is True
            assert svc._flash._build_size == size
            assert bool(svc._flash._build_size_hint) is bool(choice)
            w.run(svc._flash.close)


def test_a_longer_original_is_not_told_to_pick_a_smaller_size(tmp_path,
                                                              monkeypatch):
    """An 8 GB card in a 31.91 GB file builds at the file's length whatever
    size is picked, so the dialog's "won't fit" never suggests a smaller SD
    card size: it would build the same image."""
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    monkeypatch.setattr(FlashDialog, "refresh_drives", lambda self: None)
    dump = 31914983424
    card = make_card(tmp_path / "dump.raw", "8G", size=dump)
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        w.call("ui.set", "write", "assets", str(proj))
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        svc = w.window.service("write")
        for choice in ("", "16G", "32G"):
            w.call("ui.set", "write", "card_size", choice)
            assert w.run(svc._open_flash_dialog) is True
            dlg = svc._flash
            assert dlg._build_size == dump
            assert dlg._build_size_hint == ""
            w.run(dlg.set, "build", True)
            w.run(dlg.set, "write", True)
            dlg.selected = SimpleNamespace(size_bytes=15931539456,
                                           display="16 GB SD card")
            text, kind = dlg.readout()
            assert kind == "err" and "smaller" not in text, text
            w.run(dlg.close)


# --------------------------------------------- refused before the encode
def _to_the_build_button(w, tmp_path, monkeypatch):
    """The Write tab set up to build (original, project, build location),
    with the pipeline caught: the list a build that started lands in."""
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    monkeypatch.setattr(FlashDialog, "refresh_drives", lambda self: None)
    proj = tmp_path / "proj"
    proj.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    w.call("ui.set", "write", "assets", str(proj))
    w.call("ui.set", "write", "output", str(out))
    w.drain()
    started = []
    monkeypatch.setattr(w.app, "_run_pipeline_with_audio",
                        lambda *a, **k: started.append(a))
    return started


def _press_build(w, build, flash):
    """What the user does: the Write tab's Build / flash button, the ticks,
    an SD card picked, Start, and Yes to every question asked."""
    svc = w.window.service("write")
    w.asked.clear()
    assert w.call("write.primary") is True
    dlg = svc._flash
    assert dlg is not None and not dlg.closed
    w.run(dlg.set, "build", build)
    w.run(dlg.set, "write", flash)
    assert dlg.building and bool(dlg.write) is flash
    dlg.selected = SimpleNamespace(size_bytes=64 * 10 ** 9,
                                   display="64 GB SD card",
                                   device_path=r"\\.\PhysicalDrive9")
    w.answers[:] = ["yes"] * 4
    closed = w.run(dlg.start)
    w.drain()
    msgs = [a for a in w.asked if a.get("kind") == "message"]
    return dlg, closed, msgs


@pytest.mark.parametrize("flash", [False, True], ids=["build", "build+flash"])
def test_build_refuses_a_size_the_original_cant_take_first(tmp_path,
                                                          monkeypatch, flash):
    """The Build / flash button, then Start: a size this original can't take
    is refused before any of the dialog's questions ("Nothing modified", the
    Erase confirmation), in the control's own sentence with the way back,
    and the dialog stays open."""
    card = make_card(tmp_path / "multi.raw")
    _multi_boot(monkeypatch)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, card)
        started = _to_the_build_button(w, tmp_path, monkeypatch)
        dlg, closed, msgs = _press_build(w, build=True, flash=flash)
        assert [m["title"] for m in msgs] == ["SD card size"]
        assert "multi-boot card" in msgs[0]["message"]
        assert "16 GB SD card" in msgs[0]["message"]
        assert "Same as the original" in msgs[0]["message"]
        assert closed is False and not dlg.closed
        assert not started
        assert getattr(w.app, "_chain_flash_after_build", None) is None
        # Flash on its own is not a build: the size is not what stops it
        # (here, that no image is picked yet)
        w.run(dlg.set, "build", False)
        w.run(dlg.set, "write", True)
        w.asked.clear()
        assert w.run(dlg.start) is False
        assert [a["title"] for a in w.asked
                if a.get("kind") == "message"] == ["No image"]
        w.run(dlg.close)


def test_start_write_refuses_a_size_the_original_cant_take(tmp_path,
                                                           monkeypatch):
    """Every other way a build starts (app._start_write) asks the same, in
    the same words, before its own prompts."""
    card = make_card(tmp_path / "multi.raw")
    _multi_boot(monkeypatch)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, card)
        started = _to_the_build_button(w, tmp_path, monkeypatch)
        w.asked.clear()
        w.run(w.app._start_write)
        msgs = [a for a in w.asked if a.get("kind") == "message"]
        assert [m["title"] for m in msgs] == ["SD card size"]
        assert msgs[0]["message"] == "%s\n\n%s" % (
            w.run(w.window.card_size_problem), write_mod.CARD_SIZE_WAY_BACK)
        assert not started


def _cant_grow(monkeypatch, calls=None):
    why = "the Linux this app uses can't attach the card image as a disk"

    def _no_e2fs():
        if calls is not None:
            calls.append(1)
        raise cs.CardSizeError(why)
    monkeypatch.setattr(cs, "_E2fs", _no_e2fs)
    return why


@pytest.mark.parametrize("flash", [False, True], ids=["build", "build+flash"])
def test_a_computer_that_cant_grow_a_card_is_refused_first(tmp_path,
                                                           monkeypatch,
                                                           flash):
    """A stock card the tables say can grow, on a computer that can't grow
    one: the control's note turns red as soon as the answer is in (asked
    off the UI loop), and Start is refused on it before the Erase
    confirmation, in write_preflight's own words."""
    from pinball_decryptor.core.registry import get_manufacturer
    card = make_card(tmp_path / "gz.raw")
    _cant_grow(monkeypatch)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_note_kind"]
                        == "err")
        s = w.state("write")
        want = ("This card can't be built for a 16 GB SD card on this "
                "computer: the Linux this app uses can't attach the card "
                "image as a disk.")
        assert s["card_size_note"] == want
        # the other bigger size stays on offer, the one asked for once
        assert values(s) == ["", "16G", "32G"]
        assert s["card_size_shown"] == "16G"
        assert w.run(w.window.card_size_problem) == want
        # the build's own check (the worker's backstop) says the same
        mfr = get_manufacturer("stern")
        assert mfr.write_preflight(str(card)) == want
        started = _to_the_build_button(w, tmp_path, monkeypatch)
        dlg, closed, msgs = _press_build(w, build=True, flash=flash)
        assert [m["title"] for m in msgs] == ["SD card size"]
        assert msgs[0]["message"] == "%s\n\n%s" % (
            want, write_mod.CARD_SIZE_WAY_BACK)
        assert closed is False and not dlg.closed
        assert not started
        # the original's own size needs nothing grown: no refusal
        w.run(dlg.close)
        w.call("ui.set", "write", "card_size", "")
        assert w.run(w.window.card_size_problem) == ""
        assert w.state("write")["card_size_note_kind"] == ""


def test_this_computer_is_asked_once_and_a_no_again_later(monkeypatch):
    calls = []
    _cant_grow(monkeypatch, calls)
    done = []
    assert write_mod._ask_grow_here(lambda: done.append(1)) is True
    assert wait_until(lambda: done)
    assert write_mod._grow_here().startswith("the Linux this app uses")
    # a no holds for a minute: not asked again straight away
    assert write_mod._ask_grow_here() is False
    assert calls == [1]
    # ... and is asked again after it
    monkeypatch.setattr(write_mod, "_GROW_HERE_RECHECK", 0.0)
    monkeypatch.setattr(cs, "_E2fs", lambda: calls.append(2))
    done.clear()
    assert write_mod._ask_grow_here(lambda: done.append(1)) is True
    assert wait_until(lambda: done)
    assert write_mod._grow_here() == ""
    # a yes holds for the session
    assert write_mod._ask_grow_here() is False
    assert calls == [1, 2]


def test_no_answer_is_not_a_no(monkeypatch):
    """An unexpected failure asking (not card_size's refusal) is no answer:
    nothing is refused on it, and it is not asked again straight away."""
    def _boom():
        raise OSError("wsl.exe went away")
    monkeypatch.setattr(cs, "_E2fs", _boom)
    done = []
    assert write_mod._ask_grow_here(lambda: done.append(1)) is True
    assert wait_until(lambda: done)
    assert write_mod._grow_here() is None
    assert write_mod._ask_grow_here() is False


def wait_until(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _bare_app():
    from pinball_decryptor import app as appmod
    a = appmod.App.__new__(appmod.App)   # no window
    a.msg_queue = queue.Queue()
    a._staging_failures = []
    a._cancel_requested = False
    a.pipeline = SimpleNamespace(
        run=lambda: pytest.fail("the build must not run"))
    return a


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_a_build_that_cant_finish_is_refused_before_staging(monkeypatch):
    from pinball_decryptor.core.messages import DoneMsg
    a = _bare_app()
    why = ("This card can't be built for a 16 GB SD card on this computer: "
           "growing the games partition isn't available on macOS yet.")
    a._current_mfr = SimpleNamespace(write_preflight=lambda p: why)
    staged = []
    monkeypatch.setattr(a, "_stage_pending_audio",
                        lambda d: staged.append("a") or (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_video",
                        lambda d, cancel_cb=None: staged.append("v")
                        or (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_image",
                        lambda d: staged.append("i") or (0, 0, []))
    a._run_pipeline_with_audio("ASSETS", original="orig.raw")
    assert staged == []
    dones = [m for m in _drain(a.msg_queue) if isinstance(m, DoneMsg)]
    assert len(dones) == 1
    assert dones[0].success is False and dones[0].summary == why


def test_stern_write_preflight(tmp_path, monkeypatch):
    from pinball_decryptor.core.registry import get_manufacturer, load_plugins
    from pinball_decryptor.plugins.stern import multiimage
    load_plugins()
    mfr = get_manufacturer("stern")
    era = mfr.current_era
    mfr.set_era("spike2")
    try:
        card = str(make_card(tmp_path / "gz.raw"))
        # the original's own size checks nothing
        assert mfr.write_preflight(card) is None
        monkeypatch.setenv(ENV, "16G")
        _multi_boot(monkeypatch)
        why = mfr.write_preflight(card)
        assert "multi-boot card" in why
        assert "16 GB SD card" in why and "16G" not in why
        # a stock card on a computer that can't grow one
        monkeypatch.setattr(multiimage, "images_for_path",
                            lambda p: ["godzilla"])

        def _no_e2fs():
            raise cs.CardSizeError("growing the games partition isn't "
                                   "available on macOS yet")
        monkeypatch.setattr(cs, "_E2fs", _no_e2fs)
        assert mfr.write_preflight(card) == (
            "This card can't be built for a 16 GB SD card on this computer: "
            "growing the games partition isn't available on macOS yet.")
        mfr.set_era("spike1")
        assert mfr.write_preflight(card) is None
    finally:
        mfr.set_era(era)


def test_the_overwrite_prompt_reason_uses_gb(monkeypatch):
    from pinball_decryptor.core.registry import get_manufacturer, load_plugins
    from pinball_decryptor.plugins.stern import pipeline
    load_plugins()
    mfr = get_manufacturer("stern")
    era = mfr.current_era
    mfr.set_era("spike2")
    reason = ["it was built for a different SD card size (16G, and this "
              "build is for 32G)"]
    monkeypatch.setattr(pipeline, "engine", SimpleNamespace(
        read_build_manifest=lambda p: {},
        build_update_reason=lambda *a: reason[0]))
    try:
        assert mfr.build_update_reason("o", "a", "b") == (
            "it was built for a different SD card size (16 GB, and this "
            "build is for 32 GB)")
        reason[0] = "the file has changed since it was built"
        assert mfr.build_update_reason("o", "a", "b") == reason[0]
    finally:
        mfr.set_era(era)


# ------------------------------------ the room on the games partition
# The games partitions of two stock cards as the superblock and descriptors
# give them (read off the real images, 2026-09-23; the figures the engine's
# pre-flight measures a build against: tests/test_stern_space_preflight.py).
GZ_PRO_116 = dict(blocks=1675263, free=89975, ipg=8064, resv_gdt=408)
JAWS_LE_102 = dict(blocks=3538943, free=1543649, ipg=8192, resv_gdt=863)


def _p3(g):
    return cs.P3Space(block_size=4096, blocks=g["blocks"], free=g["free"],
                      r_blocks=0, blocks_per_group=32768,
                      inodes_per_group=g["ipg"], inode_size=256,
                      reserved_gdt=g["resv_gdt"], first_data_block=0,
                      desc_size=32, sparse_super=True, meta_bg=False)


def _stock_partition(monkeypatch, geometry, harness=None):
    """card_size.read_space answers with a stock card's games partition.
    Returns the list of its calls, each True when it was asked on the UI
    loop of *harness* (a one-item list, filled once the app is up)."""
    asked = []

    def _read_space(path, offset=cs.P3_START * cs.SECTOR):
        loop = harness[0].ctx.loop if harness else None
        asked.append(bool(loop is not None and loop.in_loop()))
        return _p3(geometry)
    monkeypatch.setattr(cs, "read_space", _read_space)
    return asked


GZ_ROOM = ("The original is an 8 GB card. Its games partition, where replaced "
           "videos and longer sounds go, has 352 MB free; built for a 16 GB "
           "card it has 7.87 GB, for a 32 GB card 22.50 GB.")


def test_the_note_gives_the_real_room_at_each_size(tmp_path, monkeypatch):
    """The note says how much room the games partition has at the
    original's own size and at each bigger size (usable: the kernel's
    reserve off), read on the probe's worker thread, never on the UI loop."""
    card = make_card(tmp_path / "gz.raw", "8G")
    holder = []
    asked = _stock_partition(monkeypatch, GZ_PRO_116, holder)
    with web_app(tmp_path, mfr="stern") as w:
        holder.append(w)
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert s["card_size_note"] == GZ_ROOM
        assert s["card_size_note_kind"] == ""
        assert asked and not any(asked), "read on the UI loop"
        probe = w.window.service("write")._card_probe
        assert probe["room"] == {"8G": (89975 - 4096) * 4096,
                                 "16G": (1924909 - 4096) * 4096,
                                 "32G": (5497389 - 4096) * 4096}
        n = len(asked)
        w.call("ui.set", "write", "card_size", "16G")
        assert w.state("write")["card_size_note"] == (
            GZ_ROOM + " The built image is 15.49 GB and needs an SD card of "
            "at least 16 GB; flashing it takes longer.")
        # choosing a size re-reads nothing: the probe has every size's room
        assert len(asked) == n


def test_a_refused_size_says_only_why(tmp_path, monkeypatch):
    """A size this original can't take: the red note is the reason alone,
    and no room is worked out at a size it can't be built for."""
    card = make_card(tmp_path / "multi.raw", "8G")
    _multi_boot(monkeypatch)
    _stock_partition(monkeypatch, GZ_PRO_116)
    with web_app(tmp_path, mfr="stern", settings={"card_size": "32G"}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert s["card_size_note_kind"] == "err"
        assert "multi-boot card" in s["card_size_note"]
        assert "free" not in s["card_size_note"]
        assert list(w.window.service("write")._card_probe["room"]) == ["8G"]


def test_a_16g_original_gives_its_own_room_and_32(tmp_path, monkeypatch):
    card = make_card(tmp_path / "jaws.raw", "16G")
    _stock_partition(monkeypatch, JAWS_LE_102)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        assert w.state("write")["card_size_note"] == (
            "The original is a 16 GB card. Its games partition, where "
            "replaced videos and longer sounds go, has 6.31 GB free; built "
            "for a 32 GB card it has 20.93 GB.")


def test_the_room_is_read_off_the_real_partition(tmp_path):
    """No stand-in: a real (tiny) filesystem where a Spike 2 card keeps its
    games partition, its descriptors counting 200 free 1 KB blocks, of which
    the kernel keeps 2% back."""
    from tests import synthetic
    card = make_card(tmp_path / "gz.raw", "8G")
    fs = bytearray(synthetic.make_ext2_fs({"game/readme": b"x" * 100}))
    struct.pack_into("<I", fs, 1024 + 0x0C, 200)        # superblock total
    struct.pack_into("<H", fs, 2 * 1024 + 0x0C, 200)    # group 0's count
    with open(card, "r+b") as f:
        f.seek(cs.P3_START * cs.SECTOR)
        f.write(bytes(fs))
    probe = write_mod._probe_card_size(str(card))
    assert probe["room"]["8G"] == (200 - 512 // 50) * 1024
    with open(card, "rb") as f:
        layout = cs.read_layout(f)
    want = cs.room_by_class(layout, cs.read_space(str(card)),
                            ["16G", "32G"], cs.ROUTE_MOUNT)
    assert {c: probe["room"][c] for c in want} == dict(want)
    assert want["16G"] > 7 * 10 ** 9 and want["32G"] > want["16G"]
    assert write_mod._room_words(probe["room"], "8G", ["16G", "32G"]) \
        .startswith(" Its games partition, where replaced videos and longer "
                    "sounds go, has 195 KB free; built for a 16 GB card it "
                    "has ")


def test_no_room_figure_when_the_partition_cant_be_read(tmp_path):
    """The synthetic cards above have nothing at the games partition: the
    note keeps to what the tables say."""
    card = make_card(tmp_path / "gz.raw", "8G")
    probe = write_mod._probe_card_size(str(card))
    assert probe["own"] == "8G" and probe["room"] == {}
    assert write_mod._room_words({}, "8G", ["16G"]) == ""
    # a size whose figure is missing is left out, the rest still said
    assert write_mod._room_words({"8G": 351760384}, "8G", ["16G"]) == (
        " Its games partition, where replaced videos and longer sounds go, "
        "has 352 MB free.")


def test_the_tip_says_what_a_bigger_card_does_not_lift():
    tip = write_mod.CARD_SIZE_TIP
    assert "games partition" in tip
    assert "about 2 GB on its sound bank" in tip
    assert "original's space" in tip
    # the note carries the real figure now
    assert "few hundred MB" not in tip
    assert "16G" not in tip and "32G" not in tip


# ------------------------------------------ refused by the pre-flight
def test_a_build_that_wont_fit_is_one_clean_dialog(tmp_path, monkeypatch):
    """The engine's pre-flight refuses a build that can't fit the games
    partition (card_size.WontFit, a CardSizeError) before anything is
    encoded.  The Stern pipeline turns it into a PipelineError, so the user
    gets ONE "Write Failed" dialog in its own words: no "Unexpected error",
    no traceback in the log, and a flash chained after the build never
    starts."""
    from pinball_decryptor.plugins.stern import pipeline as sp
    refusal = cs.WontFit(1_990_000_000, 351_760_384,
                         [(81_000_000, "godzilla_pro/assets/a.asset"),
                          (20_000_000, "godzilla_pro/assets/b.asset")],
                         fits="16G", fits_room=7_867_650_048)
    calls = []

    def _write_image(*a, **k):
        calls.append(k.get("update"))
        raise refusal
    monkeypatch.setattr(sp, "detect_game", lambda p: "godzilla_pro")
    monkeypatch.setattr(sp, "display_for_key", lambda *a, **k: "Godzilla")
    monkeypatch.setattr(sp, "engine", SimpleNamespace(
        AVAILABLE=True, write_image=_write_image,
        read_build_manifest=lambda p: {}))
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        flashed = []
        monkeypatch.setattr(app, "_start_flash_image",
                            lambda *a, **k: flashed.append(a))
        log_cb, phase_cb, progress_cb, done_cb = app._make_callbacks()
        pipe = sp.SternWritePipeline(
            str(tmp_path / "orig.raw"), str(tmp_path), str(tmp_path / "o.raw"),
            log_cb, phase_cb, progress_cb, done_cb)

        def _building():
            # the run state app._start_write sets, a flash chained after
            app._active_mode = "write"
            app._cancel_requested = False
            app._chain_flash_after_build = (r"\\.\PhysicalDrive9",
                                            str(tmp_path / "o.raw"))
            w.window.set_running(True, mode="write")
        w.run(_building)
        w.asked.clear()
        pipe.run()                      # what the build's worker thread does
        assert calls == [None]

        def _msgs():
            return [a for a in w.asked if a.get("kind") == "message"]
        assert wait_for(w, _msgs)
        w.drain()
        msgs = _msgs()
        assert [m["title"] for m in msgs] == ["Write Failed"]
        text = msgs[0]["message"]
        assert text == str(refusal)
        assert text.startswith("This build needs 1.99 GB on the card's "
                               "games partition, which has 352 MB free")
        assert "Build it for a 16 GB SD card" in text
        assert "16G" not in text and "Unexpected error" not in text
        lines = [e["text"] for e in w.window._log.get("stern", [])]
        assert not any("Unexpected error" in t or "Traceback" in t
                       for t in lines), lines
        assert app._chain_flash_after_build is None and not flashed
        assert w.state("shell").get("running") is False


# ------------------------------------------- one click to a bigger card
QUESTION_8_TO_16 = (
    "Your assets no longer fit on an 8 GB SD card. Would you like to change "
    "the size requirement to 16 GB so that you don't have to compress any "
    "assets?\n\nThe SD card in the machine has to be 16 GB or bigger.")


def _refused_run(w, tmp_path, monkeypatch, refusal, answer):
    """A Stern build whose engine pre-flight raises *refusal*, run the way the
    build's worker runs it, with a flash chained after it; the modal
    question answered *answer*.  Returns (messages asked, the builds started
    again)."""
    from pinball_decryptor.plugins.stern import pipeline as sp

    def _write_image(*a, **k):
        raise refusal
    monkeypatch.setattr(sp, "detect_game", lambda p: "godzilla_pro")
    monkeypatch.setattr(sp, "display_for_key", lambda *a, **k: "Godzilla")
    monkeypatch.setattr(sp, "engine", SimpleNamespace(
        AVAILABLE=True, write_image=_write_image,
        read_build_manifest=lambda p: {}))
    app = w.app
    again = []
    monkeypatch.setattr(app, "_start_write", lambda **k: again.append(k))
    log_cb, phase_cb, progress_cb, done_cb = app._make_callbacks()
    pipe = sp.SternWritePipeline(
        str(tmp_path / "orig.raw"), str(tmp_path), str(tmp_path / "o.raw"),
        log_cb, phase_cb, progress_cb, done_cb)

    def _building():
        app._active_mode = "write"
        app._cancel_requested = False
        app._space_refusal = None
        app.pipeline = pipe
        app._chain_flash_after_build = (r"\\.\PhysicalDrive9",
                                        str(tmp_path / "o.raw"))
        w.window.set_running(True, mode="write")
    w.run(_building)
    w.asked.clear()
    w.answers[:] = [answer]
    pipe.run()

    def _msgs():
        return [a for a in w.asked if a.get("kind") == "message"]
    assert wait_for(w, _msgs)
    w.drain()
    return _msgs(), again


def _refusal(**k):
    base = dict(fits="16G", fits_room=7_867_650_048, current="8G")
    base.update(k)
    return cs.WontFit(1_990_000_000, 351_760_384,
                      [(81_000_000, "big_loop2.mp4")], **base)


def test_a_refused_build_asks_to_build_for_the_size_that_fits(tmp_path,
                                                              monkeypatch):
    """PAD-176 in one click: a build the games partition can't hold, where a
    bigger SD card size would, asks that question instead of the Write
    Failed dialog.  Yes sets SD card size (saved and applied, as if the user
    chose it) and starts the same build again, chained to the same flash."""
    monkeypatch.setenv(ENV, "")
    monkeypatch.delenv(ENV)             # restored to unset afterwards
    with web_app(tmp_path, mfr="stern") as w:
        msgs, again = _refused_run(w, tmp_path, monkeypatch, _refusal(),
                                   "yes")
        assert [m["title"] for m in msgs] == ["SD card size"]
        assert msgs[0]["message"] == QUESTION_8_TO_16
        assert wait_for(w, lambda: again)
        assert again == [{"chain_flash_device": r"\\.\PhysicalDrive9",
                          "again": True}]
        assert w.run(w.window.card_size_choice) == "16G"
        assert w.app._settings["card_size"] == "16G"
        assert os.environ.get(ENV) == "16G"
        lines = [e["text"] for e in w.window._log.get("stern", [])]
        assert "SD card size is now 16 GB; building again." in lines


def test_no_keeps_the_size_and_builds_nothing(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        msgs, again = _refused_run(w, tmp_path, monkeypatch, _refusal(),
                                   "no")
        assert [m["title"] for m in msgs] == ["SD card size"]
        w.drain()
        assert not again
        assert w.run(w.window.card_size_choice) == ""
        assert not w.app._settings.get("card_size")
        lines = [e["text"] for e in w.window._log.get("stern", [])]
        assert ("Not built: the SD card size stays 8 GB. To fit it, use "
                "fewer or smaller replacements.") in lines
        # the refusal itself, with its numbers, is in the log above it
        assert any(t.startswith("This build needs 1.99 GB") for t in lines)


@pytest.mark.parametrize("kw", [
    {"fits": None, "largest": "32G", "largest_room": 22_500_000_000},
    {"fixed": True},                   # a port: it can't take a size
    {"current": None},                 # not measured at a Stern size
    {"current": "16G", "fits": "16G"},  # nothing bigger to offer
], ids=["nothing-fits", "port", "no-size", "not-bigger"])
def test_no_question_when_a_bigger_card_isnt_the_answer(tmp_path,
                                                        monkeypatch, kw):
    with web_app(tmp_path, mfr="stern") as w:
        refusal = _refusal(**kw)
        msgs, again = _refused_run(w, tmp_path, monkeypatch, refusal, "yes")
        assert [m["title"] for m in msgs] == ["Write Failed"]
        assert msgs[0]["message"] == str(refusal)
        assert not again


def test_not_offered_where_a_card_cant_be_grown(monkeypatch):
    """macOS has no loop devices: no size to change to there."""
    monkeypatch.setattr(cs, "supported", lambda: False)
    assert cs.bigger_card_offer(_refusal()) is None
    monkeypatch.setattr(cs, "supported", lambda: True)
    assert cs.bigger_card_offer(_refusal()) == ("8G", "16G")
    assert cs.bigger_card_offer(ValueError("no")) is None


def test_the_question_names_both_sizes():
    assert cs.offer_question("8G", "16G") == QUESTION_8_TO_16
    assert cs.offer_question("16G", "32G").startswith(
        "Your assets no longer fit on a 16 GB SD card. Would you like to "
        "change the size requirement to 32 GB")


def test_the_early_refusal_asks_the_same(tmp_path, monkeypatch):
    """The Build's first step (write_preflight, before any clip is
    converted) refuses with the same WontFit: the same question."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        refusal = _refusal(early=True)
        monkeypatch.setattr(app._current_mfr, "write_preflight",
                            lambda *a, **k: cs.RefusalText(
                                "Not enough room.", refusal))
        again = []
        monkeypatch.setattr(app, "_start_write", lambda **k: again.append(k))

        def _building():
            app._active_mode = "write"
            app._cancel_requested = False
            app._chain_flash_after_build = None
            app.pipeline = SimpleNamespace(output_path=None, update=None)
            w.window.set_running(True, mode="write")
        w.run(_building)
        w.asked.clear()
        w.answers[:] = ["yes"]
        app._run_pipeline_with_audio(str(tmp_path),
                                     original=str(tmp_path / "orig.raw"))

        def _msgs():
            return [a for a in w.asked if a.get("kind") == "message"]
        assert wait_for(w, _msgs)
        w.drain()
        assert [m["message"] for m in _msgs()] == [QUESTION_8_TO_16]
        assert wait_for(w, lambda: again)
        assert again == [{"chain_flash_device": None, "again": True}]
        monkeypatch.delenv(ENV, raising=False)


def test_building_again_asks_nothing_already_answered(tmp_path, monkeypatch):
    """The build started again after Yes replaces the file the user already
    agreed to replace without asking again, and builds it whole; a
    different file at the output (the new size's default name) is still
    asked about."""
    card = make_card(tmp_path / "orig.raw")
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16G"}) as w:
        point_at(w, card)
        started = _to_the_build_button(w, tmp_path, monkeypatch)
        out = os.path.join(w.window.write_output_var.get(),
                           w.window.write_filename_var.get())
        with open(out, "wb") as f:
            f.write(b"the build the user already agreed to replace")
        w.app._last_build_output = out
        w.asked.clear()
        w.run(lambda: w.app._start_write(again=True))
        w.drain()
        assert not [a for a in w.asked if a.get("kind") == "message"]
        assert len(started) == 1
        assert w.app.pipeline.update is False
        # the same Build started fresh (not again) asks about that file
        w.asked.clear()
        w.answers[:] = ["cancel"]
        w.run(lambda: w.app._start_write())
        w.drain()
        assert [a for a in w.asked if a.get("kind") == "message"]
        assert len(started) == 1
        # and so does again, for a file it wasn't told about
        w.app._last_build_output = os.path.join(str(tmp_path), "other.raw")
        w.asked.clear()
        w.answers[:] = ["cancel"]
        w.run(lambda: w.app._start_write(again=True))
        w.drain()
        assert [a for a in w.asked if a.get("kind") == "message"]
        assert len(started) == 1
        monkeypatch.delenv(ENV, raising=False)


# ------------------------------------------------------- Port + build
@pytest.mark.parametrize("saved", ["16G", ""])
def test_port_builds_are_made_at_each_cards_own_size(monkeypatch, saved):
    from pinball_decryptor.core import mod_port
    from pinball_decryptor.core.messages import LogMsg
    a = _bare_app()
    a._settings = {"card_size": saved}
    if saved:
        monkeypatch.setenv(ENV, saved)
    seen = []
    monkeypatch.setattr(mod_port, "run_ports",
                        lambda *args: seen.append(os.environ.get(ENV)) or [])
    a._run_port_chain("PROJECT", [])
    assert seen == [None]
    # the Write tab's choice is back once the chain is over
    assert os.environ.get(ENV) == (saved or None)
    logs = [m.text for m in _drain(a.msg_queue) if isinstance(m, LogMsg)]
    assert any("16 GB" in t for t in logs) is bool(saved)
