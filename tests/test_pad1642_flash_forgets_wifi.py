"""PAD-1642: a whole card written with "Keep my network settings" but not the card's own settings.

Dustin flashed a multi-boot Iron Maiden card with remote access kept on it, the machine came up, and Find my machine
found no device at all.  The Wi-Fi network a Spike 2 machine joined is one of the game's own settings
(/data/nv/<game>/NVM), and a whole card written without "Keep the SD card's settings, audits and high scores" puts
the image's empty /data in their place: remote access on, and no network to reach it over.  Nothing said so.  Now
the flash dialog says it under the network tick, the flash log says it after such a write, and the Network tab's
Find my machine names it when it finds nothing.
"""
import importlib

import pytest

from pinball_decryptor.core import network_keep
from tests.test_flash_keep_data import FAKE_DEVICE, _open
from tests.webui_harness import web_app

PIPE = importlib.import_module("pinball_decryptor.plugins.stern.pipeline")


def _flash(tmp_path, monkeypatch, remote, **kwargs):
    image = tmp_path / "card.img"
    image.write_bytes(b"\0" * 4096)
    monkeypatch.setattr(PIPE, "flash_image_with_privileges", lambda img, dev, **k: 4096)
    monkeypatch.setattr(PIPE, "is_device_path", lambda p: True)
    from pinball_decryptor.core import menu_network
    if isinstance(remote, Exception):
        def boom(path):
            raise remote
        monkeypatch.setattr(menu_network, "has_remote_access", boom)
    else:
        monkeypatch.setattr(menu_network, "has_remote_access", lambda path: remote)
    logs, done = [], []
    PIPE.SternFlashImagePipeline(str(image), FAKE_DEVICE, lambda text, level="info": logs.append((level, text)),
                                 lambda i: None, lambda *a: None, lambda ok, s: done.append(ok), **kwargs).run()
    return [t for lvl, t in logs if lvl == "warning" and t == PIPE.FORGETS_WIFI], done


def test_a_whole_card_with_remote_access_and_fresh_settings_says_the_wifi_is_forgotten(tmp_path, monkeypatch):
    said, done = _flash(tmp_path, monkeypatch, True)
    assert said and done == [True]
    assert "forgotten your Wi-Fi network" in PIPE.FORGETS_WIFI and "machine's own menu" in PIPE.FORGETS_WIFI
    assert "off and on" in PIPE.FORGETS_WIFI


@pytest.mark.parametrize("remote, kwargs", [
    (True, {"keep_data": True}),          # the card's settings, and its Wi-Fi with them, were kept
    (True, {"menu_only": True}),          # a menu write leaves /data alone
    (False, {}),                          # nothing reaches this card over the network anyway
    (OSError("unreadable"), {}),          # a check that fails never fails a written card
])
def test_no_note_where_nothing_was_lost_or_nothing_reaches_it(tmp_path, monkeypatch, remote, kwargs):
    if kwargs.get("menu_only"):
        monkeypatch.setattr(PIPE, "flash_image_with_privileges", lambda img, dev, **k: 4096)
    said, done = _flash(tmp_path, monkeypatch, remote, **kwargs)
    assert said == [] and done == [True]


def test_the_flash_dialog_says_the_network_tick_does_not_keep_the_machines_wifi(tmp_path, monkeypatch):
    monkeypatch.setattr(network_keep, "options", lambda project: {"ssh": {"enabled": True}})
    image = tmp_path / "multi.raw"
    image.write_bytes(b"\0" * 2048)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, tmp_path, monkeypatch, changed=False)
        w.call("write.flash_set", "build", False)
        w.call("write.flash_set", "image_path", str(image))
        f = w.state("write")["flash_dlg"]
        assert f["net_keep"] is True and f["keep_data"] is False
        assert "remote access" in f["net_note"] and "own Wi-Fi network is not one of them" in f["net_note"]
        w.call("write.flash_set", "keep_data", True)
        f = w.state("write")["flash_dlg"]
        assert "remote access" in f["net_note"] and "Wi-Fi network" not in f["net_note"]
        w.call("write.flash_close")
