"""PAD-217: "Skip verify" in the Build / flash dialog.

A flash reads the whole card back and compares it to the image, which about
doubles the time.  The dialog now offers to skip that - a tick that is off
every time the dialog opens and says what the risk is once ticked - on the
brands whose flash is that read-back (Stern, CGC).  These pin the tick, the
note, the confirm wording, and ``verify=False`` riding from the dialog
through the app (direct flash and the build->flash chain) into the core
write.  Nothing here touches a real card.
"""
import importlib
import inspect
import os

import pytest

from pinball_decryptor.core import registry
from tests.test_webui_write import (fake_drives, make_project, point_at,
                                    recorder, wait_for)
from tests.webui_harness import web_app

registry.load_plugins()
FLASHERS = [m for m in registry.all_manufacturers()
            if m.capabilities.flash_image]
FAKE_IMG = os.path.join(os.sep + "imgs", "image.raw")
FAKE_DEVICE = r"\\.\PHYSICALDRIVE9"


# ---- the plugin contract ----------------------------------------------------

def test_skip_verify_is_offered_by_the_read_back_brands():
    offered = {m.key for m in FLASHERS
               if getattr(m, "flash_skip_verify", False)}
    assert offered == {"stern", "cgc"}


@pytest.mark.parametrize("mfr", FLASHERS, ids=lambda m: m.key)
def test_verify_is_taken_exactly_where_skip_verify_is_offered(mfr):
    takes = "verify" in inspect.signature(
        mfr.make_flash_pipeline).parameters
    assert takes == bool(getattr(mfr, "flash_skip_verify", False))


# ---- the pipelines hand verify= to the core write ---------------------------

@pytest.mark.parametrize("module, name", [
    ("pinball_decryptor.plugins.stern.pipeline", "SternFlashImagePipeline"),
    ("pinball_decryptor.plugins.cgc.pipeline", "FlashImagePipeline"),
])
@pytest.mark.parametrize("verify", [True, False])
def test_pipeline_passes_verify_and_says_so(tmp_path, monkeypatch, module,
                                            name, verify):
    mod = importlib.import_module(module)
    from pinball_decryptor.core.rawdevice import SKIP_VERIFY_LOG, FlashError
    image = tmp_path / "card.img"
    image.write_bytes(b"\0" * 4096)
    seen = {}

    def _flash(img, dev, **k):
        seen.update(k)
        raise FlashError("stop here")          # nothing past the write

    monkeypatch.setattr(mod, "flash_image_with_privileges", _flash)
    monkeypatch.setattr(mod, "is_device_path", lambda p: True)
    logs, done = [], []
    pipe = getattr(mod, name)(
        str(image), FAKE_DEVICE, lambda t, lvl="info": logs.append((t, lvl)),
        lambda i: None, lambda *a: None, lambda ok, s: done.append(ok),
        verify=verify)
    pipe.run()
    assert seen["verify"] is verify
    assert done == [False]
    skipped = [lvl for t, lvl in logs if t == SKIP_VERIFY_LOG]
    assert skipped == ([] if verify else ["warning"])


# ---- the app hands it to the plugin -----------------------------------------

@pytest.mark.parametrize("key, module, name, passed", [
    ("stern", "pinball_decryptor.plugins.stern.manufacturer",
     "SternFlashImagePipeline", False),
    ("cgc", "pinball_decryptor.plugins.cgc.manufacturer",
     "FlashImagePipeline", False),
    # no "Skip verify" on a JJP stick: never handed a keyword it can't take
    ("jjp", "pinball_decryptor.plugins.jjp.usbstick",
     "UsbStickPreparePipeline", "absent"),
])
def test_start_flash_image_skips_verify_only_where_offered(
        tmp_path, monkeypatch, key, module, name, passed):
    made = []

    class _Pipe:
        def __init__(self, *args, **kwargs):
            made.append(kwargs)

        def run(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(importlib.import_module(module), name, _Pipe)
    with web_app(tmp_path, mfr=key) as w:
        try:
            w.run(lambda: w.app._start_flash_image(FAKE_IMG, FAKE_DEVICE,
                                                   verify=False))
            assert len(made) == 1
            assert made[0].get("verify", "absent") == passed
        finally:
            def _reset():
                w.app._active_mode = None
                w.window.set_running(False, mode="write")
            w.run(_reset)


def test_build_then_flash_chain_carries_skip_verify(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        seen = {}
        monkeypatch.setattr(
            app, "_start_write",
            lambda chain_flash_device=None, chain_flash_verify=True:
            seen.update(device=chain_flash_device, verify=chain_flash_verify))
        build_path = os.path.join(os.sep + "builds", "gz.raw")
        w.run(lambda: app._on_build_flash_request(build_path, FAKE_DEVICE,
                                                  verify=False))
        assert seen == {"device": FAKE_DEVICE, "verify": False}

        import pinball_decryptor.app as app_mod
        flashed = []
        monkeypatch.setattr(app, "_start_flash_image",
                            lambda img, dev, verify=True:
                            flashed.append((img, dev, verify)))
        monkeypatch.setattr(app_mod.messagebox, "showinfo",
                            lambda *a, **k: None)

        def _go():
            app._active_mode = "write"
            app._chain_flash_after_build = (FAKE_DEVICE, FAKE_IMG, False)
            app._on_done(True, "built.")
        w.run(_go)
        assert wait_for(w, lambda: flashed, timeout=3)
        assert flashed == [(FAKE_IMG, FAKE_DEVICE, False)]


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


def test_dialog_skip_verify_is_off_and_warns_once_ticked(tmp_path,
                                                         monkeypatch):
    image = tmp_path / "backup.raw"
    image.write_bytes(b"\0" * 2048)
    with web_app(tmp_path, mfr="stern") as w:
        flashes = recorder(w, "on_flash_image")
        f = _open(w, tmp_path, monkeypatch, changed=False)
        assert f["verify_offered"] is True
        assert f["skip_verify"] is False and f["skip_verify_note"] == ""
        w.call("write.flash_set", "image_path", str(image))
        w.call("write.flash_set", "skip_verify", True)
        f = w.state("write")["flash_dlg"]
        assert f["skip_verify"] is True
        assert "SHELL ERROR" in f["skip_verify_note"]
        assert "not read back" in f["skip_verify_note"]
        w.answers += ["yes", "yes"]           # Nothing modified, Erase
        assert w.call("write.flash_start") is True
        assert "Skip verify is ticked" in w.asked[-1]["message"]
        assert flashes == [((str(image), r"\\.\PhysicalDrive9"),
                            {"menu_only": False, "verify": False})]
        # never remembered: the next dialog opens with verify back on
        w.call("write.primary")
        assert wait_for(w, lambda: w.state("write")["flash_dlg"])
        f = w.state("write")["flash_dlg"]
        assert f["skip_verify"] is False and f["skip_verify_note"] == ""
        w.call("write.flash_close")


def test_dialog_unticked_flash_is_verified(tmp_path, monkeypatch):
    image = tmp_path / "backup.raw"
    image.write_bytes(b"\0" * 2048)
    with web_app(tmp_path, mfr="stern") as w:
        flashes = recorder(w, "on_flash_image")
        _open(w, tmp_path, monkeypatch, changed=False)
        w.call("write.flash_set", "image_path", str(image))
        w.answers += ["yes", "yes"]
        assert w.call("write.flash_start") is True
        assert "Skip verify" not in w.asked[-1]["message"]
        assert flashes == [((str(image), r"\\.\PhysicalDrive9"),
                            {"menu_only": False})]


def test_dialog_build_and_flash_hands_skip_to_the_build(tmp_path,
                                                        monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        builds = recorder(w, "on_build_flash")
        f = _open(w, tmp_path, monkeypatch, changed=True)
        assert f["build"] is True and f["write"] is True
        w.call("write.flash_set", "skip_verify", True)
        w.answers.append("yes")
        assert w.call("write.flash_start") is True
        assert builds == [((f["build_path"], r"\\.\PhysicalDrive9"),
                           {"verify": False})]


def test_dialog_build_only_never_skips(tmp_path, monkeypatch):
    """With only Build ticked nothing is written, so there is nothing to
    verify: no note and nothing handed on."""
    with web_app(tmp_path, mfr="stern") as w:
        builds = recorder(w, "on_build_flash")
        _open(w, tmp_path, monkeypatch, changed=True)
        w.call("write.flash_set", "skip_verify", True)
        w.call("write.flash_set", "write", False)
        f = w.state("write")["flash_dlg"]
        assert f["skip_verify_enabled"] is False
        assert f["skip_verify_note"] == ""
        assert w.call("write.flash_start") is True
        assert builds and builds[0][1] == {}


def test_jjp_stick_has_no_skip_verify(tmp_path, monkeypatch):
    from pinball_decryptor.core import drives as drv
    fake_drives(monkeypatch, [drv.PhysicalDrive(
        device_path=r"\\.\PhysicalDrive3", model="USB Stick",
        size_bytes=32 * 10 ** 9, bus_type="USB")])
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("write.primary")
        assert wait_for(w, lambda: w.state("write")["flash_dlg"])
        w.call("write.flash_set", "skip_verify", True)     # ignored
        f = w.state("write")["flash_dlg"]
        assert f["verify_offered"] is False and f["skip_verify"] is False
        w.call("write.flash_close")
