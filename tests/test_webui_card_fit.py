"""PAD-467: the Write tab's "Make the image as small as it can be".

Under SD card size, for a Stern Spike 2 original laid out the way Stern lays a
card out: the setting persists and is mirrored into PAD_STERN_CARD_FIT, the
note says about how big the original comes out made as small as it can be,
and with it ticked the SD card size's note says the size is the room while
the build runs, and the Build / flash dialog doesn't take the size of the
image a build makes as known before it is built.  The synthetic cards carry no
filesystem, so the games partition reads as a Godzilla Premium 1.16 retheme's
(the real figures).
"""

import json
import os

import pytest

from pinball_decryptor.plugins.stern import card_size as cs
from pinball_decryptor.webui.tabs import write as write_mod
from tests.test_stern_card_size_fit import GZ_INODES, GZ_RETHEME
from tests.test_webui_card_size import (  # noqa: F401 - autouse fixtures
    _a_computer_that_can_grow_a_card, _multi_boot, _no_card_size_env,
    make_card, point_at, wait_for)
from tests.webui_harness import web_app

FIT = cs.FIT_ENV
GZ = "godzilla_premium-1_16_0.Release.8G.sdcard.raw"
ROOM = "while the build runs; then the image is made as small as it can be."


@pytest.fixture(autouse=True)
def _no_fit_env(monkeypatch):
    # setenv first, so the var is put back to unset after a test whose app
    # set it (delenv on a var that isn't there records nothing to undo)
    monkeypatch.setenv(FIT, "")
    monkeypatch.delenv(FIT)


@pytest.fixture()
def retheme(monkeypatch):
    """Every read of a card's games partition answers the retheme."""
    monkeypatch.setattr(cs, "p3_space", lambda reader: GZ_RETHEME)
    monkeypatch.setattr(cs, "inodes_used", lambda reader: GZ_INODES)
    monkeypatch.setattr("pinball_decryptor.plugins.stern.ext4.Ext4Reader",
                        lambda *a: None)


def test_the_option_persists_and_mirrors_the_env(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        assert win.card_fit_enabled() is False
        assert FIT not in os.environ
        w.call("ui.set", "write", "card_fit", True)
        assert win.card_fit_enabled() is True
        assert os.environ.get(FIT) == "1"
        saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(
            encoding="utf-8"))
        assert saved.get("card_fit") is True
        w.call("ui.set", "write", "card_fit", False)
        assert FIT not in os.environ
        assert w.app._settings.get("card_fit") is False
        # the run logic's own mirror before a build (app._start_write)
        w.call("ui.set", "write", "card_fit", True)
        os.environ.pop(FIT, None)
        w.app._apply_card_fit_env(win.card_fit_enabled())
        assert os.environ.get(FIT) == "1"


def test_a_saved_tick_applies_at_startup(tmp_path):
    with web_app(tmp_path, mfr="stern", settings={"card_fit": True}) as w:
        assert w.window.card_fit_enabled() is True
        assert os.environ.get(FIT) == "1"


def test_env_name_is_fit_env():
    from pinball_decryptor.app import App
    assert App._CARD_FIT_ENV == cs.FIT_ENV


def test_the_tip_says_the_spare_it_keeps():
    spare = cs.size_words(cs.FIT_SPARE)
    assert "with %s of it left free" % spare in write_mod.CARD_FIT_TIP
    from pinball_decryptor.webui import help_content
    with open(help_content.__file__, encoding="utf-8") as f:
        text = f.read()
    assert "with %s left" % spare in text
    assert ("less than %s to take off" % cs.size_words(cs.FIT_MIN_CUT)
            in text)


def test_an_8g_original_says_how_small_it_comes_out(tmp_path, retheme):
    card = make_card(tmp_path / GZ, "8G")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_fit_cap"])
        s = w.state("write")
        assert s["card_fit_label"] == "Make the image as small as it can be"
        assert s["card_fit_note"] == (
            "Made as small as it can be, this card comes out about 5.93 GB, "
            "plus what the build adds to it.")
        assert s["card_fit_note_kind"] == ""
        assert s["card_fit"] is False
        w.call("ui.set", "write", "card_size", "16G")
        s = w.state("write")
        assert s["card_size_note"].endswith(
            "The built image is 15.49 GB and needs an SD card of at least "
            "16 GB; flashing it takes longer.")
        svc = w.window.service("write")
        assert w.run(svc._card_build)[:2] == ("16G", cs.CARD_SIZES["16G"])
        w.call("ui.set", "write", "card_fit", True)
        s = w.state("write")
        assert s["card_size_note"].endswith(
            "The games partition has that room " + ROOM)
        # the size the build makes is known only once it is built
        assert w.run(svc._card_build)[:2] == ("16G", None)
        # and the name still carries the size the build is for
        assert w.window.write_filename_var.get().endswith(
            ".16G.sdcard-modified.raw")


def test_a_32g_original_is_offered_it_without_a_size(tmp_path, retheme):
    card = make_card(tmp_path / "met.raw", "32G")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_fit_cap"])
        assert w.state("write")["card_size_cap"] is False


def test_no_option_without_a_spike2_card(tmp_path):
    junk = tmp_path / "junk.raw"
    junk.write_bytes(b"\1" * 4096)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, junk)
        svc = w.window.service("write")
        assert wait_for(w, lambda: svc._card_probe is not None
                        or svc._card_probe_path == str(junk))
        assert w.state("write")["card_fit_cap"] is False


def test_a_multi_boot_card_ticked_says_why_not(tmp_path, monkeypatch,
                                               retheme):
    card = make_card(tmp_path / "multi.raw", "8G")
    _multi_boot(monkeypatch)
    with web_app(tmp_path, mfr="stern", settings={"card_fit": True}) as w:
        point_at(w, card)
        assert wait_for(w, lambda: w.state("write")["card_fit_note_kind"]
                        == "err")
        assert w.state("write")["card_fit_note"] == (
            "This card's image keeps its size: this is a multi-boot card, and "
            "the Multi-boot tab sets the size of those.")
        # so the build is the original's size, and the dialog knows it
        svc = w.window.service("write")
        assert w.run(svc._card_build)[:2] == (None, cs.CARD_SIZES["8G"])
        w.call("ui.set", "write", "card_fit", False)
        assert w.state("write")["card_fit_note"] == ""


def test_not_offered_on_macos(tmp_path, monkeypatch, retheme):
    monkeypatch.setattr(write_mod, "card_size_supported",
                        lambda platform=None: False)
    monkeypatch.setattr(cs, "supported", lambda: False)
    card = make_card(tmp_path / GZ, "8G")
    with web_app(tmp_path, mfr="stern", settings={"card_fit": True}) as w:
        point_at(w, card)
        assert w.window.card_fit_enabled() is False
        assert FIT not in os.environ
        assert w.state("write")["card_fit_cap"] is False
