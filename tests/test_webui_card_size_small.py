"""PAD-465: the Write tab's "Smaller 16 GB card" (card_size.SMALL).

James Bond 1.06 ships on Stern's 16 GB card, a 15,494,807,552-byte image,
and some SD cards sold as 16 GB hold less.  A 16 GB original is offered the
smaller 16 GB card; the note, the build's name and the Build / flash dialog
say what it makes.  The synthetic cards carry no filesystem, so the games
partition reads as James Bond Pro 1.06's (the real figures).
"""

import pytest

from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.webui.tabs import write as write_mod
from tests.test_stern_card_size_small import BOND_PRO_106
from tests.test_webui_card_size import (  # noqa: F401 - autouse fixtures
    _a_computer_that_can_grow_a_card, _no_card_size_env, make_card, point_at,
    values, wait_for)
from tests.webui_harness import web_app

BOND = "james_bond_pro-1_06_0.Release.16G.sdcard.raw"
NAMED = "james_bond_pro-1_06_0.Release.%s.sdcard-modified.raw"
HINT = ('or pick "Smaller 16 GB card" under SD card size on the Write tab '
        '(a 14.82 GB image)')


@pytest.fixture()
def bond_partition(monkeypatch):
    """Every read of a card's games partition answers James Bond Pro 1.06."""
    monkeypatch.setattr(cs, "p3_space", lambda reader: BOND_PRO_106)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.ext4.Ext4Reader",
                        lambda *a: None)


def test_a_16g_original_is_offered_the_smaller_16g_card(tmp_path,
                                                        bond_partition):
    card = make_card(tmp_path / BOND, "16G")
    with web_app(tmp_path, mfr="stern") as w:
        name = w.window.write_filename_var.get
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        s = w.state("write")
        assert s["card_size_options"] == [
            {"value": "", "label": "Same as the original"},
            {"value": "16S", "label": "Smaller 16 GB card"},
            {"value": "32G", "label": "32 GB card"}]
        room = ("The original is a 16 GB card. Its games partition, where "
                "replaced videos and longer sounds go, has 5.03 GB free; built "
                "for a smaller 16 GB card it has 4.37 GB, for a 32 GB card "
                "19.66 GB.")
        assert s["card_size_note"] == room
        assert "Smaller 16 GB card is for a 16 GB SD card" in s["card_size_tip"]
        assert name() == NAMED % "16G"
        w.call("ui.set", "write", "card_size", "16S")
        s = w.state("write")
        assert s["card_size_shown"] == "16S"
        assert s["card_size_note"] == room + (
            " The built image is 14.82 GB, so it fits a 16 GB SD card too "
            "small for Stern's own 16 GB image (15.49 GB).")
        assert name() == NAMED % "16G-small"
        assert w.run(w.window.card_size_problem) == ""
        w.call("ui.set", "write", "card_size", "32G")
        assert name() == NAMED % "32G"
        w.call("ui.set", "write", "card_size", "")
        assert name() == NAMED % "16G"


def test_a_full_16g_original_is_not_offered_it(tmp_path, monkeypatch):
    """A games partition that holds more than the smaller card has room for:
    the size isn't offered, and asked for it is refused in red, in words."""
    full = BOND_PRO_106._replace(free=100000)
    monkeypatch.setattr(cs, "p3_space", lambda reader: full)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.ext4.Ext4Reader",
                        lambda *a: None)
    card = make_card(tmp_path / BOND, "16G")
    with web_app(tmp_path, mfr="stern", settings={"card_size": "16S"}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_size_note_kind"]
                        == "err")
        s = w.state("write")
        assert values(s) == ["", "32G", "16S"]       # the one asked for, kept
        assert s["card_size_note"] == (
            "This card can't be built for a smaller 16 GB SD card: its games "
            "partition already holds 14.09 GB, more than fits on one.")


def test_the_flash_dialog_points_at_the_smaller_card(tmp_path, monkeypatch,
                                                     bond_partition):
    """A build at Stern's 16 GB size that won't fit the SD card picked: the
    "won't fit" says the smaller 16 GB card would make a 14.82 GB image.
    Once it is picked the build is that size, and the pointer goes."""
    from types import SimpleNamespace
    from pinball_decryptor.webui.write_dialogs import FlashDialog
    monkeypatch.setattr(FlashDialog, "refresh_drives", lambda self: None)
    card = make_card(tmp_path / BOND, "16G")
    proj = tmp_path / "proj"
    proj.mkdir()
    short16 = SimpleNamespace(size_bytes=15376000000, display="16 GB SD card")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        w.call("ui.set", "write", "assets", str(proj))
        assert wait_for(w, lambda: w.state("write")["card_size_cap"])
        svc = w.window.service("write")
        assert w.run(svc._open_flash_dialog) is True
        dlg = svc._flash
        assert dlg._build_size == cs.CARD_SIZES["16G"]
        assert dlg._build_size_hint == HINT
        w.run(dlg.set, "build", True)
        w.run(dlg.set, "write", True)
        dlg.selected = short16
        text, kind = dlg.readout()
        assert kind == "err" and text.endswith(", " + HINT + "."), text
        w.run(dlg.close)
        w.call("ui.set", "write", "card_size", "16S")
        assert w.run(svc._open_flash_dialog) is True
        dlg = svc._flash
        assert dlg._build_size == cs.LAYOUT_SIZES["16S"]
        assert dlg._build_size_hint == ""
        w.run(dlg.set, "build", True)
        w.run(dlg.set, "write", True)
        dlg.selected = short16
        assert dlg.readout()[1] == "ok"
        w.run(dlg.close)


def test_an_image_already_built_at_16g_is_told_to_build_it_smaller(
        tmp_path, monkeypatch):
    """Flashing a finished 16 GB build onto a card it doesn't fit: the
    pointer is to build it again for the smaller card; any other image (an
    8 GB card, a file with no table) gets none."""
    big = make_card(tmp_path / BOND, "16G")
    small = make_card(tmp_path / "gz.Release.8G.sdcard.raw", "8G")
    junk = tmp_path / "junk.raw"
    junk.write_bytes(b"\0" * 4096)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, big)
        svc = w.window.service("write")
        hint = w.run(svc._image_small_card_hint, str(big),
                     cs.CARD_SIZES["16G"])
        assert hint == ('or build it again with SD card size set to "Smaller '
                        '16 GB card" on the Write tab (a 14.82 GB image)')
        assert w.run(svc._image_small_card_hint, str(small),
                     cs.CARD_SIZES["8G"]) == ""
        assert w.run(svc._image_small_card_hint, str(junk), 4096) == ""


def test_the_dialog_says_the_image_hint_when_the_image_wont_fit(tmp_path,
                                                                monkeypatch):
    from types import SimpleNamespace
    from pinball_decryptor.webui import write_dialogs as wd
    monkeypatch.setattr(wd.FlashDialog, "refresh_drives", lambda self: None)
    img = tmp_path / "built.raw"
    img.write_bytes(b"\0" * 4096)
    asked = []

    def hint(path, size):
        asked.append((path, size))
        return "or do the other thing"
    mfr = SimpleNamespace(key="stern", flash_noun="SD card", capabilities=None)
    try:
        dlg = wd.FlashDialog(None, mfr, lambda *a: None,
                             initial_image=str(img), image_size_hint=hint)
    except Exception:                                   # noqa: BLE001
        pytest.skip("the dialog needs a real manufacturer here")
    dlg.write = True
    dlg.selected = SimpleNamespace(size_bytes=1024, display="tiny card")
    text, kind = dlg.readout()
    assert kind == "err"
    assert text.endswith(", or do the other thing."), text
    assert asked == [(str(img), 4096)]


def test_the_smaller_card_keeps_its_name_token():
    name = write_mod._name_for_class
    assert name("x.Release.16G.sdcard-modified.raw", "16S") == (
        "x.Release.16G-small.sdcard-modified.raw")
    assert name("x.Release.16G-small.sdcard-modified.raw", "32G") == (
        "x.Release.32G.sdcard-modified.raw")
    assert name("x.Release.8G.sdcard-modified.raw", "16S") == (
        "x.Release.16G-small.sdcard-modified.raw")
    assert write_mod._norm_card_size("16s") == "16S"
