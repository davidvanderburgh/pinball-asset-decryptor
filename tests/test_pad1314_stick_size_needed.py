"""PAD-1314: Build / make USB install stick names the stick size it needs.

With "Prepare the USB stick" ticked the readout says which printed stick
size holds the ISO, how a built ISO sets against the original, and (with
Build ticked) what the build starts from.  A stick smaller than the ISO is
refused before the format erases it.
"""

import os
from types import SimpleNamespace

import pytest

from pinball_decryptor.core.drives import stick_class
from pinball_decryptor.plugins.jjp import usbstick
from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer
from pinball_decryptor.webui import write_dialogs as wd

GB = 10 ** 9


def test_stick_class_rounds_up_to_a_printed_size_with_room():
    assert stick_class(0) is None
    assert stick_class(500 * 10 ** 6) == 1
    assert stick_class(3.8 * GB) == 4
    # a "4 GB" stick holds a little under 4 x 10^9 bytes once formatted
    assert stick_class(3.9 * GB) == 8
    assert stick_class(15.5 * GB) == 32


@pytest.fixture()
def sizes(monkeypatch, tmp_path):
    """Files whose os.path.getsize answers the size given (no 4 GB writes)."""
    table = {}
    real = os.path.getsize

    def getsize(p):
        return table.get(os.path.normpath(str(p)), None) or real(p)
    monkeypatch.setattr(wd.os.path, "getsize", getsize)
    monkeypatch.setattr(wd.FlashDialog, "refresh_drives", lambda self: None)

    def make(name, n):
        p = tmp_path / name
        p.write_bytes(b"\0")
        table[os.path.normpath(str(p))] = int(n)
        return str(p)
    return make


def _dialog(sizes, image=None, original=None, build=False):
    orig = sizes("original.iso", original) if original else ""
    img = sizes("built.iso", image) if image else None
    dlg = wd.FlashDialog(
        None, JJPManufacturer(), lambda *a: None, initial_image=img,
        on_build_flash=lambda *a: None, build_target=img or "x.iso",
        can_build=True, original_size=original, original_path=orig)
    dlg.build, dlg.write = build, True
    if img:
        dlg.image_path = img
    return dlg


def test_a_picked_iso_names_the_stick_it_needs_and_its_change(sizes):
    dlg = _dialog(sizes, image=4.2 * GB, original=3.8 * GB)
    text, kind = dlg.readout()
    assert kind == "gray"
    assert "Image: 4.20 GB (400.0 MB more than the original's 3.80 GB)" in text
    assert "needs an 8 GB USB stick or larger" in text
    assert "pick a target USB stick" in text


def test_a_smaller_build_says_less(sizes):
    text, _ = _dialog(sizes, image=3.5 * GB, original=3.8 * GB).readout()
    assert "(300.0 MB less than the original's 3.80 GB)" in text
    assert "a 4 GB USB stick or larger" in text


def test_the_original_itself_is_not_compared_with_itself(sizes):
    dlg = _dialog(sizes, original=3.8 * GB)
    dlg.image_path = dlg._original_path
    text, _ = dlg.readout()
    assert "original" not in text
    assert "needs a 4 GB USB stick or larger" in text


def test_a_stick_too_small_names_the_size_to_use(sizes):
    dlg = _dialog(sizes, image=4.2 * GB, original=3.8 * GB)
    dlg.selected = SimpleNamespace(size_bytes=4 * GB, display="4 GB stick")
    text, kind = dlg.readout()
    assert kind == "err"
    assert text.endswith("won't fit. Use an 8 GB USB stick or larger."), text


def test_a_stick_that_fits_says_so(sizes):
    dlg = _dialog(sizes, image=4.2 * GB, original=3.8 * GB)
    dlg.selected = SimpleNamespace(size_bytes=16 * GB, display="16 GB")
    text, kind = dlg.readout()
    assert kind == "ok"
    assert text.endswith("USB stick 16.00 GB   ✓ fits")


def test_building_says_what_the_build_starts_from(sizes):
    text, kind = _dialog(sizes, original=3.8 * GB, build=True).readout()
    assert kind == "gray"
    assert "about the size of the original (3.80 GB)" in text
    assert "a 4 GB USB stick or larger" in text


def test_building_onto_a_stick_smaller_than_the_original_warns(sizes):
    dlg = _dialog(sizes, original=3.8 * GB, build=True)
    dlg.selected = SimpleNamespace(size_bytes=2 * GB, display="2 GB")
    text, kind = dlg.readout()
    assert kind == "err"
    assert "The original alone is 3.80 GB" in text


def test_an_sd_card_maker_gets_no_stick_size(sizes):
    mfr = SimpleNamespace(key="stern", capabilities=None)
    img = sizes("card.raw", 15.5 * GB)
    dlg = wd.FlashDialog(None, mfr, lambda *a: None, initial_image=img)
    dlg.write = True
    text, _ = dlg.readout()
    assert "or larger" not in text
    assert text.startswith("Image: 15.50 GB  •  pick a target SD card")


def test_a_stick_smaller_than_the_iso_is_refused_before_the_format(
        tmp_path, monkeypatch):
    monkeypatch.setattr(usbstick.sys, "platform", "linux")
    monkeypatch.setattr(usbstick, "is_device_path", lambda p: True)
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"\0" * 4096)
    monkeypatch.setattr(usbstick.os.path, "getsize",
                        lambda p: int(3.8 * GB))
    monkeypatch.setattr(usbstick.UsbStickPreparePipeline, "_stick_size",
                        lambda self: 2 * GB)
    formatted = []
    monkeypatch.setattr(usbstick.UsbStickPreparePipeline, "_format_stick",
                        lambda self: formatted.append(1))
    done = {}
    p = usbstick.UsbStickPreparePipeline(
        str(iso), "/dev/sdz", lambda m, lvl="info": None, lambda i: None,
        lambda *a: None, lambda ok, msg="": done.update(ok=ok, msg=msg))
    p.run()
    assert done["ok"] is False
    assert "Use a 4 GB stick or larger" in done["msg"]
    assert "Nothing was written" in done["msg"]
    assert formatted == []


def test_building_over_an_earlier_build_names_it_the_last_build(sizes):
    dlg = _dialog(sizes, image=4.2 * GB, original=3.8 * GB, build=True)
    dlg.selected = SimpleNamespace(size_bytes=4 * GB, display="4 GB")
    text, kind = dlg.readout()
    assert kind == "err"
    assert text.startswith("⚠ Last build 4.20 GB (400.0 MB more than the "
                           "original's 3.80 GB) is larger"), text
    assert text.endswith("Use an 8 GB USB stick or larger.")
