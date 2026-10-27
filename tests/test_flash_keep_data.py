"""PAD-736: "Keep the SD card's settings, audits and high scores".

A Spike 2 machine keeps its settings, audits and high scores in the SD card's
data partition (p5, /data), and a whole-card flash used to write the image's
copy over it.  The flash dialog now offers to keep it: the card's p5 is read
first and goes back onto the card in place of the image's, in the same pass,
at wherever the IMAGE puts p5 (an 8 GB image onto a card that held a 16 GB
one moves it).  These pin the core write on miniature cards, the refusals
(nothing written), the elevated helper and the pipeline carrying it, the
app's direct and build->flash routes, and the dialog's tick.  Nothing here
touches a real card.
"""
import importlib
import inspect
import json
import os
import struct

import pytest

from pinball_decryptor.core import elevated_flash as ef
from pinball_decryptor.core import rawdevice as rd
from pinball_decryptor.core import registry
from tests.test_webui_write import (fake_drives, make_project, point_at,
                                    recorder, wait_for)
from tests.webui_harness import web_app

registry.load_plugins()
FLASHERS = [m for m in registry.all_manufacturers()
            if m.capabilities.flash_image]
FAKE_IMG = os.path.join(os.sep + "imgs", "image.raw")
FAKE_DEVICE = r"\\.\PHYSICALDRIVE9"
_SEC = 512


# ---- a miniature Spike 2 card, with p5 wherever it is asked for --------------

def _entry(ptype, lba, count):
    return (b"\x00" * 4 + bytes([ptype]) + b"\x00" * 3
            + struct.pack("<II", lba, count))


def _sb(count, fs_blocks=None):
    """An ext superblock (1 KiB blocks) spanning *fs_blocks* blocks, or the
    whole *count*-sector partition - the way Stern's /data is made."""
    sb = bytearray(1024)
    blocks = fs_blocks if fs_blocks is not None else count * _SEC // 1024
    struct.pack_into("<I", sb, 0x04, blocks)
    struct.pack_into("<I", sb, 0x18, 0)
    sb[0x38:0x3A] = b"\x53\xef"
    return bytes(sb)


def _fill(marker, size):
    return (marker * (size // len(marker) + 1))[:size]


def _card(path, data_lba=386, games=b"GAMES", data=b"DATA", dump=b"DUMP",
          total=768, data_fs_blocks=None):
    """p1 boot, p2 rootfs, p3 games, and an extended container holding p5
    /data at *data_lba* (100 sectors) and p6 /dump - each partition filled
    with its own marker.  Moving *data_lba* is a card of another size."""
    img = bytearray(total * _SEC)
    mbr = bytearray(_SEC)
    for i, (ptype, lba, count, fill) in enumerate(
            [(0x0C, 64, 64, b"BOOT"), (0x83, 128, 128, b"MENU"),
             (0x83, 256, 128, games)]):
        mbr[446 + i * 16:446 + (i + 1) * 16] = _entry(ptype, lba, count)
        img[lba * _SEC:(lba + count) * _SEC] = _fill(fill, count * _SEC)
    ext = 384
    mbr[446 + 48:446 + 64] = _entry(0x0F, ext, total - ext)
    mbr[510:512] = b"\x55\xaa"
    img[:_SEC] = mbr
    dump_lba = max(data_lba + 100, 514) + 2
    # the first EBR is the container's first sector, wherever p5 starts
    logical = [(ext, data_lba, data), (dump_lba - 1, dump_lba, dump)]
    for n, (ebr_lba, lba, fill) in enumerate(logical):
        ebr = bytearray(_SEC)
        ebr[446:462] = _entry(0x83, lba - ebr_lba, 100)
        if n + 1 < len(logical):
            nxt = logical[n + 1][0]
            ebr[462:478] = _entry(0x05, nxt - ext, 102)
        ebr[510:512] = b"\x55\xaa"
        img[ebr_lba * _SEC:(ebr_lba + 1) * _SEC] = ebr
        img[lba * _SEC:(lba + 100) * _SEC] = _fill(fill, 100 * _SEC)
        img[lba * _SEC + 1024:lba * _SEC + 2048] = _sb(
            100, data_fs_blocks if n == 0 else None)
    with open(str(path), "wb") as f:
        f.write(img)
    return str(path)


def _at(path, lba, n):
    with open(path, "rb") as f:
        f.seek(lba * _SEC)
        return f.read(n)


def _played(card, data_lba=386):
    """The machine has been playing: its own settings and scores in p5."""
    raw = bytearray(open(card, "rb").read())
    raw[data_lba * _SEC + 4096:data_lba * _SEC + 4096 + 32] = \
        b"MY SETTINGS + HIGH SCORES".ljust(32)
    open(card, "wb").write(bytes(raw))
    return bytes(raw[data_lba * _SEC:(data_lba + 100) * _SEC])


# ---- the core write ----------------------------------------------------------

def test_data_partition_is_the_first_logical(tmp_path):
    img = _card(tmp_path / "a.raw", data_lba=400)
    with open(img, "rb") as f:
        def at(lba):
            f.seek(lba * _SEC)
            return f.read(_SEC)
        assert rd.data_partition(at) == (400 * _SEC, 100 * _SEC)
    blank = tmp_path / "blank.raw"
    blank.write_bytes(b"\0" * 768 * _SEC)
    with open(str(blank), "rb") as f:
        assert rd.data_partition(lambda lba: (f.seek(lba * _SEC),
                                              f.read(_SEC))[1]) is None


def test_a_kept_flash_writes_the_image_and_keeps_the_cards_data(tmp_path):
    card = _card(tmp_path / "card.raw", games=b"OLDGAMES")
    mine = _played(card)
    img = _card(tmp_path / "img.raw", games=b"NEWGAMES", dump=b"FRESHDMP")
    said = []
    rd.flash_image_to_device(img, card, eject=False, keep_data=True,
                             log=lambda m, k="info": said.append(m))
    # the image's games and everything else...
    assert _at(card, 256, 8) == b"NEWGAMES"
    assert _at(card, 516, 8) == b"FRESHDMP"
    # ...but the machine's own /data, byte for byte
    assert _at(card, 386, 100 * _SEC) == mine
    text = " ".join(said)
    assert "Keeping the card's settings, audits and high scores" in text
    assert "(verified)" in text and "keeping the card's settings" in text


def test_without_the_tick_the_image_data_goes_on_as_before(tmp_path):
    card = _card(tmp_path / "card.raw")
    _played(card)
    img = _card(tmp_path / "img.raw")
    rd.flash_image_to_device(img, card, eject=False)
    assert open(card, "rb").read() == open(img, "rb").read()


def test_the_data_goes_where_the_image_puts_p5(tmp_path):
    """An image of another card size has p5 somewhere else: the card's data
    goes into the IMAGE's p5, which is the one the flashed table names."""
    card = _card(tmp_path / "card.raw", data_lba=386)
    mine = _played(card, 386)
    img = _card(tmp_path / "img.raw", data_lba=520, games=b"NEWGAMES")
    said = []
    rd.flash_image_to_device(img, card, eject=False, keep_data=True,
                             log=lambda m, k="info": said.append(m))
    assert _at(card, 520, 100 * _SEC) == mine
    assert _at(card, 256, 8) == b"NEWGAMES"
    with open(card, "rb") as f:
        def at(lba):
            f.seek(lba * _SEC)
            return f.read(_SEC)
        assert rd.data_partition(at) == (520 * _SEC, 100 * _SEC)
    assert "where the card had it" in " ".join(said)


def test_the_read_back_checks_the_kept_data_too(tmp_path, monkeypatch):
    """The verify compares the card with what was MEANT to land: the image,
    with the card's data where p5 is - so a bad write there is caught."""
    card = _card(tmp_path / "card.raw")
    _played(card)
    img = _card(tmp_path / "img.raw", games=b"NEWGAMES")
    real = rd.RawDeviceFile.copy_image_onto

    def _bad(self, src, total, **k):
        n = real(self, src, total, **k)
        self.seek(386 * _SEC + 4096)
        self.write(b"X" * 16)                       # a flaky card in /data
        return n

    monkeypatch.setattr(rd.RawDeviceFile, "copy_image_onto", _bad)
    with pytest.raises(rd.FlashError) as e:
        rd.flash_image_to_device(img, card, eject=False, keep_data=True)
    assert "does not match the image" in str(e.value)


@pytest.mark.parametrize("what", ["blank card", "not a card image",
                                  "data too big"])
def test_refusals_write_nothing(tmp_path, what):
    if what == "blank card":
        card = tmp_path / "card.raw"
        card.write_bytes(b"\xA5" * 768 * _SEC)
        card = str(card)
        img = _card(tmp_path / "img.raw")
        words = "no settings, audits or high scores to keep"
    elif what == "not a card image":
        card = _card(tmp_path / "card.raw")
        img = tmp_path / "img.raw"
        img.write_bytes(b"\0" * 768 * _SEC)
        img = str(img)
        words = "no data partition to put the card's settings in"
    else:
        card = _card(tmp_path / "card.raw", data_fs_blocks=60)  # 60 KiB fs
        img = _card(tmp_path / "img.raw")                        # 50 KiB p5
        words = "do not fit"
    before = open(card, "rb").read()
    with pytest.raises(rd.FlashError) as e:
        rd.flash_image_to_device(img, card, eject=False, keep_data=True)
    assert words in str(e.value)
    assert "Nothing was written" in str(e.value)
    assert open(card, "rb").read() == before


def test_cancel_before_the_write_writes_nothing(tmp_path):
    card = _card(tmp_path / "card.raw")
    before = open(card, "rb").read()
    img = _card(tmp_path / "img.raw", games=b"NEWGAMES")
    with pytest.raises(rd.FlashCancelled):
        rd.flash_image_to_device(img, card, eject=False, keep_data=True,
                                 cancel=lambda: True)
    assert open(card, "rb").read() == before


def test_overlay_swaps_only_its_own_span():
    assert rd._apply_overlay(b"abcdefgh", 0, (2, b"XY")) == b"abXYefgh"
    assert rd._apply_overlay(b"abcd", 4, (2, b"XYZW")) == b"ZWcd"
    assert rd._apply_overlay(b"abcd", 8, (2, b"XY")) == b"abcd"
    assert rd._apply_overlay(b"abcd", 0, (3, b"XYZ")) == b"abcX"


# ---- the elevated route ------------------------------------------------------

def test_the_in_process_write_carries_keep_data(tmp_path):
    card = _card(tmp_path / "card.raw")
    mine = _played(card)
    img = _card(tmp_path / "img.raw", games=b"NEWGAMES")
    ef.flash_image_with_privileges(img, card, keep_data=True)
    assert _at(card, 386, 100 * _SEC) == mine


def test_the_helper_job_carries_keep_data(tmp_path, monkeypatch):
    card = _card(tmp_path / "card.raw")
    mine = _played(card)
    img = _card(tmp_path / "img.raw", games=b"NEWGAMES")
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    (ipc / "job.json").write_text(json.dumps(
        {"image": img, "device": card, "verify": True, "menu_only": False,
         "keep_data": True}), encoding="utf-8")
    monkeypatch.setattr(rd, "_eject_device", lambda *a, **k: None)
    assert ef.run_helper_main(["x", "--flash-helper", str(ipc)]) == 0
    assert json.loads((ipc / "result.json").read_text())["ok"] is True
    assert _at(card, 386, 100 * _SEC) == mine
    assert _at(card, 256, 8) == b"NEWGAMES"


def test_the_parent_writes_keep_data_into_the_job(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(ef, "is_admin", lambda: False)
    monkeypatch.setattr(ef, "is_device_path", lambda p: True)

    def _spawn(ipc):
        seen.update(json.load(open(os.path.join(ipc, "job.json"))))
        return None                         # "could not elevate": stop here

    monkeypatch.setattr(ef, "_spawn_elevated_helper", _spawn)
    with pytest.raises(rd.FlashError):
        ef.flash_image_with_privileges(FAKE_IMG, FAKE_DEVICE, keep_data=True)
    assert seen["keep_data"] is True and seen["menu_only"] is False


def test_a_menu_write_is_never_handed_keep_data(monkeypatch):
    seen = {}
    monkeypatch.setattr(ef, "flash_menu_to_device",
                        lambda *a, **k: seen.update(k) or 1)
    monkeypatch.setattr(ef, "is_admin", lambda: True)
    ef.flash_image_with_privileges(FAKE_IMG, FAKE_DEVICE, menu_only=True,
                                   keep_data=True)
    assert "keep_data" not in seen


# ---- the plugin contract and the pipeline ------------------------------------

def test_keep_data_is_offered_by_stern_only():
    assert {m.key for m in FLASHERS
            if getattr(m, "flash_keep_data", False)} == {"stern"}


@pytest.mark.parametrize("mfr", FLASHERS, ids=lambda m: m.key)
def test_keep_data_is_taken_exactly_where_offered(mfr):
    takes = "keep_data" in inspect.signature(
        mfr.make_flash_pipeline).parameters
    assert takes == bool(getattr(mfr, "flash_keep_data", False))


@pytest.mark.parametrize("keep", [True, False])
def test_the_stern_pipeline_hands_it_on_and_says_so(tmp_path, monkeypatch,
                                                    keep):
    mod = importlib.import_module("pinball_decryptor.plugins.stern.pipeline")
    image = tmp_path / "card.img"
    image.write_bytes(b"\0" * 4096)
    seen = {}

    def _flash(img, dev, **k):
        seen.update(k)
        return 4096

    monkeypatch.setattr(mod, "flash_image_with_privileges", _flash)
    monkeypatch.setattr(mod, "is_device_path", lambda p: True)
    done = []
    pipe = mod.SternFlashImagePipeline(
        str(image), FAKE_DEVICE, lambda *a: None, lambda i: None,
        lambda *a: None, lambda ok, s: done.append((ok, s)), keep_data=keep)
    pipe.run()
    assert seen.get("keep_data", False) is keep
    assert done[0][0] is True
    assert ("keeping the machine's settings, audits and high scores"
            in done[0][1]) is keep


# ---- the app hands it to the plugin ------------------------------------------

@pytest.mark.parametrize("key, module, name, kwargs, passed", [
    ("stern", "pinball_decryptor.plugins.stern.manufacturer",
     "SternFlashImagePipeline", {}, True),
    # the menu-only write keeps them anyway: never both
    ("stern", "pinball_decryptor.plugins.stern.manufacturer",
     "SternFlashImagePipeline", {"menu_only": True}, False),
    ("cgc", "pinball_decryptor.plugins.cgc.manufacturer",
     "FlashImagePipeline", {}, "absent"),
])
def test_start_flash_image_keeps_data_only_where_offered(
        tmp_path, monkeypatch, key, module, name, kwargs, passed):
    made = []

    class _Pipe:
        def __init__(self, *args, **kw):
            made.append(kw)

        def run(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(importlib.import_module(module), name, _Pipe)
    with web_app(tmp_path, mfr=key) as w:
        try:
            w.run(lambda: w.app._start_flash_image(
                FAKE_IMG, FAKE_DEVICE, keep_data=True, **kwargs))
            assert len(made) == 1
            assert made[0].get("keep_data", "absent") == passed
        finally:
            def _reset():
                w.app._active_mode = None
                w.window.set_running(False, mode="write")
            w.run(_reset)


def test_build_then_flash_chain_carries_keep_data(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        seen = {}
        monkeypatch.setattr(
            app, "_start_write",
            lambda chain_flash_device=None, chain_flash_verify=True,
            chain_flash_keep_data=False:
            seen.update(device=chain_flash_device, keep=chain_flash_keep_data))
        build_path = os.path.join(os.sep + "builds", "gz.raw")
        w.run(lambda: app._on_build_flash_request(build_path, FAKE_DEVICE,
                                                  keep_data=True))
        assert seen == {"device": FAKE_DEVICE, "keep": True}

        import pinball_decryptor.app as app_mod
        flashed = []
        monkeypatch.setattr(app, "_start_flash_image",
                            lambda img, dev, verify=True, keep_data=False:
                            flashed.append((img, dev, verify, keep_data)))
        monkeypatch.setattr(app_mod.messagebox, "showinfo",
                            lambda *a, **k: None)

        def _go():
            app._active_mode = "write"
            app._chain_flash_after_build = (FAKE_DEVICE, FAKE_IMG, True, True)
            app._on_done(True, "built.")
        w.run(_go)
        assert wait_for(w, lambda: flashed, timeout=3)
        assert flashed == [(FAKE_IMG, FAKE_DEVICE, True, True)]


# ---- the dialog --------------------------------------------------------------

def _open(w, tmp_path, monkeypatch, changed):
    fake_drives(monkeypatch)
    proj = make_project(tmp_path, changed=changed)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0" * 4096)
    point_at(w, orig, proj)
    w.call("ui.select_tab", "write")
    assert wait_for(w, lambda: not w.state("write")["scanning"])
    w.call("write.primary")
    assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                    .get("drives"))
    return w.state("write")["flash_dlg"]


def test_dialog_keep_tick_flashes_keeping_and_is_remembered(tmp_path,
                                                            monkeypatch):
    image = tmp_path / "backup.raw"
    image.write_bytes(b"\0" * 2048)
    with web_app(tmp_path, mfr="stern") as w:
        flashes = recorder(w, "on_flash_image")
        f = _open(w, tmp_path, monkeypatch, changed=False)
        assert f["keep_offered"] is True
        assert f["keep_data"] is False and f["keep_note"] == ""
        w.call("write.flash_set", "image_path", str(image))
        w.call("write.flash_set", "keep_data", True)
        f = w.state("write")["flash_dlg"]
        assert f["keep_data"] is True
        assert "data partition" in f["keep_note"]
        w.answers += ["yes", "yes"]           # Nothing modified, Erase
        assert w.call("write.flash_start") is True
        assert ("settings, audits and high scores on it are kept"
                in w.asked[-1]["message"])
        assert flashes == [((str(image), r"\\.\PhysicalDrive9"),
                            {"menu_only": False, "keep_data": True})]
        # remembered: the next dialog opens with it ticked
        w.call("write.primary")
        assert wait_for(w, lambda: w.state("write")["flash_dlg"])
        assert w.state("write")["flash_dlg"]["keep_data"] is True
        w.call("write.flash_close")


def test_dialog_build_and_flash_hands_keep_to_the_build(tmp_path,
                                                        monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        builds = recorder(w, "on_build_flash")
        f = _open(w, tmp_path, monkeypatch, changed=True)
        assert f["build"] is True and f["write"] is True
        w.call("write.flash_set", "keep_data", True)
        w.answers.append("yes")
        assert w.call("write.flash_start") is True
        assert builds == [((f["build_path"], r"\\.\PhysicalDrive9"),
                           {"keep_data": True})]


def test_dialog_build_only_keeps_nothing(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        builds = recorder(w, "on_build_flash")
        _open(w, tmp_path, monkeypatch, changed=True)
        w.call("write.flash_set", "keep_data", True)
        w.call("write.flash_set", "write", False)
        f = w.state("write")["flash_dlg"]
        assert f["keep_enabled"] is False and f["keep_note"] == ""
        assert w.call("write.flash_start") is True
        assert builds and builds[0][1] == {}


def test_jjp_stick_has_no_keep_tick(tmp_path, monkeypatch):
    from pinball_decryptor.core import drives as drv
    fake_drives(monkeypatch, [drv.PhysicalDrive(
        device_path=r"\\.\PhysicalDrive3", model="USB Stick",
        size_bytes=32 * 10 ** 9, bus_type="USB")])
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("write.primary")
        assert wait_for(w, lambda: w.state("write")["flash_dlg"])
        w.call("write.flash_set", "keep_data", True)       # ignored
        f = w.state("write")["flash_dlg"]
        assert f["keep_offered"] is False and f["keep_data"] is False
        w.call("write.flash_close")
