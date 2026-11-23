"""A card image double-clicked in Explorer opens PAD on its write dialog
(PAD-1514, webui/open_image.py): the command line, the hand-off to a PAD
already open, the per-user file association and its uninstall, and the app
switching to the image's manufacturer and era with the Flash image dialog
open on it.  No real card, drive or registry is touched."""

import os
import re

import pytest

from tests.webui_harness import web_app
from tests.test_webui_write import DRIVE, fake_drives, recorder, wait_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _no_real_flash(monkeypatch):
    from pinball_decryptor import app as app_mod

    def _refuse(self, *a, **k):
        raise AssertionError("an open-image test reached the real flash")
    monkeypatch.setattr(app_mod.App, "_start_flash_image", _refuse)


@pytest.fixture(autouse=True)
def _no_real_app_picker(monkeypatch):
    """No test may bring Windows' "Select an app" dialog onto the desktop."""
    from pinball_decryptor.webui import open_image as oi

    def _refuse(ext=".raw"):
        raise AssertionError("an open-image test opened Windows' app picker")
    monkeypatch.setattr(oi, "ask_windows", _refuse)


def test_image_arg_takes_the_first_existing_file(tmp_path):
    from pinball_decryptor.webui.open_image import image_arg
    img = tmp_path / "Game 1.0.raw"
    img.write_bytes(b"\0")
    assert image_arg([]) is None
    assert image_arg(["--browser"]) is None
    assert image_arg([str(tmp_path / "gone.raw")]) is None
    assert image_arg(["-x", '"%s"' % img]) == str(img)


def test_association_command_runs_the_launcher_with_the_file():
    from pinball_decryptor.webui import open_image as oi
    app_dir = r"C:\Program Files\Pinball Asset Decryptor"
    rows = oi.association_values(app_dir)
    cmd = dict(((k, n), d) for k, n, d in rows)[
        (oi.PROGID + r"\shell\open\command", "")]
    assert cmd == ('wscript.exe "%s\\launcher.vbs" "%%1"' % app_dir)
    for ext in oi.IMAGE_EXTENSIONS:
        assert (ext + r"\OpenWithProgids", oi.PROGID, "") in rows
        assert any(k == r"SystemFileAssociations\%s\shell\%s\command"
                   % (ext, oi.VERB) for k, _n, _d in rows)
    # PAD takes the double-click only where Windows' own Mount is not it
    assert oi.DEFAULT_FOR == (".raw",)


def test_checkout_is_not_an_install():
    """A checkout has launch.vbs at its root, never launcher.vbs: it never
    registers itself (the installed app does)."""
    from pinball_decryptor.webui import open_image as oi
    if os.path.isfile(os.path.join(ROOT, "launcher.vbs")):
        pytest.skip("running from an install")
    assert oi.install_dir() is None
    assert oi.register_association() is False


def test_launcher_passes_the_file_on():
    with open(os.path.join(ROOT, "installer", "launcher.vbs"),
              encoding="utf-8") as f:
        vbs = f.read()
    assert "For Each a In WScript.Arguments" in vbs
    assert re.search(r'ShellExecute _\s*\n\s*appDir & "\\python\\pythonw.exe", '
                     r'params,', vbs)


def test_uninstall_removes_what_the_app_registers():
    from pinball_decryptor.webui import open_image as oi
    with open(os.path.join(ROOT, "installer", "pinball_decryptor.iss"),
              encoding="utf-8") as f:
        iss = f.read()
    body = iss.split("procedure RemoveTheFileAssociation;", 1)[1]
    body = body.split("\nend;", 1)[0]
    assert oi.PROGID in body and oi.VERB in body
    for ext in oi.IMAGE_EXTENSIONS:
        assert "'%s'" % ext in body
    assert "'Software\\Classes\\' + Exts[I]" in body
    # silent uninstalls (the update's swap) clean up too: before the Exit
    step = iss.split("procedure CurUninstallStepChanged", 1)[1]
    assert step.index("RemoveTheFileAssociation()") < step.index(
        "if UninstallSilent() then")


def _stern_spike2(monkeypatch, image):
    from pinball_decryptor.core.registry import Game
    from pinball_decryptor.plugins.stern.manufacturer import \
        SternManufacturer
    real = SternManufacturer.detect

    def _detect(self, path):
        if os.path.normcase(path) == os.path.normcase(str(image)):
            return Game(key="godzilla", display="Godzilla",
                        manufacturer_key="stern", era="spike2",
                        notes="Spike 2 card image")
        return real(self, path)
    monkeypatch.setattr(SternManufacturer, "detect", _detect)


def test_opened_image_switches_manufacturer_and_opens_write(tmp_path,
                                                            monkeypatch):
    """PAD on JJP, a Stern Spike 2 image double-clicked: Stern, Spike 2, the
    Flash image dialog on that image, write only, Start writes it."""
    fake_drives(monkeypatch)
    image = tmp_path / "Godzilla Premium 1.16.raw"
    image.write_bytes(b"\0" * 1024)
    _stern_spike2(monkeypatch, image)
    with web_app(tmp_path, mfr="jjp") as w:
        assert w.app._current_mfr.key == "jjp"
        flashes = recorder(w, "on_flash_image")
        assert w.run(w.app.open_image, str(image)) is True
        assert w.app._current_mfr.key == "stern"
        assert w.app._current_mfr.current_era == "spike2"
        assert w.state("shell")["tab"] == "write"
        assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                        .get("drives"))
        f = w.state("write")["flash_dlg"]
        assert f["handed_in"] is True
        assert f["build"] is False and f["write"] is True
        assert f["image_path"] == str(image)
        assert f["title"] == "Flash SD card image"
        assert f["header"] == ("Write Godzilla Premium 1.16.raw onto the "
                               "SD card")
        assert "The image you opened" in f["intro"]
        assert "press Flash image;" in f["intro"]
        w.answers.append("yes")                     # Erase … and continue?
        assert w.call("write.flash_start") is True
        assert flashes[0][0] == (str(image), DRIVE)
        # not the Write tab's own remembered choice
        assert "stern" not in w.window.service("write")._saved_flash_choices


def test_opened_image_waits_for_the_disclaimer(tmp_path, monkeypatch):
    image = tmp_path / "card.raw"
    image.write_bytes(b"\0")
    with web_app(tmp_path, mfr="stern") as w:
        w.app._session_started = False
        assert w.run(w.app.open_image, str(image)) is True
        assert w.ctx.open_image == str(image)
        assert w.state("write").get("flash_dlg") is None


def test_unrecognised_image_on_the_picker_says_so(tmp_path):
    image = tmp_path / "holiday.raw"
    image.write_bytes(b"\0" * 1024)
    with web_app(tmp_path) as w:
        assert w.app._current_mfr is None
        assert w.run(w.app.open_image, str(image)) is False
        assert w.asked and w.asked[-1]["title"] == "Open image"


def test_second_launch_hands_the_image_to_the_open_app(tmp_path,
                                                       monkeypatch):
    """The link file + the server's /api: a second launch's
    hand_to_running gives the path to this app, which opens it."""
    from pinball_decryptor.webui import open_image as oi
    from pinball_decryptor.webui.server import WebServer
    fake_drives(monkeypatch)
    image = tmp_path / "Godzilla Premium 1.16.raw"
    image.write_bytes(b"\0" * 1024)
    _stern_spike2(monkeypatch, image)
    with web_app(tmp_path, mfr="jjp") as w:
        w.ctx.registry.register("shell.open_image", w.app.open_image)
        server = WebServer(w.ctx)
        server.start()
        try:
            assert oi.hand_to_running(str(image)) is False   # no link yet
            path = oi.write_link(w.ctx, server.port)
            assert os.path.dirname(path) == str(tmp_path / "cfg")
            assert oi.hand_to_running(str(image)) is True
            w.drain()
            assert w.app._current_mfr.key == "stern"
            assert (w.state("write")["flash_dlg"] or {}).get(
                "image_path") == str(image)
            assert oi.remove_link(w.ctx) is True
            assert oi.hand_to_running(str(image)) is False
        finally:
            server.stop()


@pytest.mark.skipif(os.name != "nt", reason="the Windows registry")
def test_register_and_unregister_round_trip():
    """Under a throwaway key of this user's registry: everything PAD writes,
    .raw taken only when free (or when the user asks), and all of it gone
    again - an .raw default that is someone else's is left alone."""
    import uuid
    import winreg
    from pinball_decryptor.webui import open_image as oi
    classes = r"Software\PADTest-%s\Classes" % uuid.uuid4().hex
    app_dir = r"C:\Program Files\Pinball Asset Decryptor"
    hk = winreg.HKEY_CURRENT_USER

    def _get(sub, name=""):
        try:
            with winreg.OpenKey(hk, classes + "\\" + sub) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    try:
        with winreg.CreateKeyEx(hk, classes + r"\.raw") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "SomeViewer.raw")
        assert oi.register_association(app_dir, classes=classes) is True
        assert oi.is_registered(classes) is True
        assert _get(oi.PROGID + r"\shell\open\command").endswith('"%1"')
        assert _get(r".iso\OpenWithProgids", oi.PROGID) == ""
        assert _get(r"SystemFileAssociations\.img\shell\%s\command"
                    % oi.VERB) is not None
        assert _get(".raw") == "SomeViewer.raw"          # not taken
        assert oi.register_association(app_dir, classes=classes) is False
        oi.register_association(app_dir, take_raw=True, classes=classes)
        assert _get(".raw") == oi.PROGID                  # the user asked
        assert oi.unregister_association(classes) is True
        assert oi.is_registered(classes) is False
        assert _get(".raw") is None
        assert _get(r".iso\OpenWithProgids", oi.PROGID) is None
        assert _get(r"SystemFileAssociations\.img\shell\%s" % oi.VERB) is None
    finally:
        root = classes.rsplit("\\", 1)[0]

        def _drop(path):
            try:
                with winreg.OpenKey(hk, path) as k:
                    kids = []
                    i = 0
                    while True:
                        try:
                            kids.append(winreg.EnumKey(k, i))
                            i += 1
                        except OSError:
                            break
                for c in kids:
                    _drop(path + "\\" + c)
                winreg.DeleteKey(hk, path)
            except OSError:
                pass
        _drop(root)


def test_open_with_names_pad_not_the_script_host():
    """The command is wscript.exe, so the ProgID says the app's own name and
    icon or Open with lists "Microsoft Windows Based Script Host"
    (PAD-1518)."""
    from pinball_decryptor.webui import open_image as oi
    rows = {(k, n): d for k, n, d in oi.association_values(r"C:\PAD")}
    assert rows[(oi.PROGID + r"\shell\open", "FriendlyAppName")] == \
        "Pinball Asset Decryptor"
    assert rows[(oi.PROGID + r"\Application", "ApplicationName")] == \
        "Pinball Asset Decryptor"
    assert rows[(oi.PROGID + r"\Application", "ApplicationIcon")].endswith(
        "icon.ico")


@pytest.mark.skipif(os.name != "nt", reason="the Windows registry")
def test_the_switch_takes_raw_from_windows_own_choice(monkeypatch):
    """Ticking the switch forgets the "Always use this app" another app has
    for .raw, both keys Windows keeps it in, so PAD's default opens it with
    nothing to do in Explorer (PAD-1518); a start-up registration, or a
    choice that is already PAD, touches nothing."""
    import uuid
    import winreg
    from pinball_decryptor.webui import open_image as oi
    monkeypatch.setattr(oi, "_assoc_friendly_app_name", lambda p: "")
    base = r"Software\PADTest-%s" % uuid.uuid4().hex
    classes, fileexts = base + r"\Classes", base + r"\FileExts"
    hk = winreg.HKEY_CURRENT_USER

    def _choose(prog):
        for sub in ("UserChoice", r"UserChoiceLatest\ProgId"):
            with winreg.CreateKeyEx(hk, fileexts + "\\.raw\\" + sub) as k:
                winreg.SetValueEx(k, "ProgId", 0, winreg.REG_SZ, prog)

    def _has(sub):
        try:
            with winreg.OpenKey(hk, fileexts + "\\.raw\\" + sub):
                return True
        except OSError:
            return False
    try:
        _choose("AppXphotos")
        assert oi.raw_chosen_elsewhere(".raw", fileexts) == "AppXphotos"
        oi.register_association(r"C:\PAD", classes=classes, fileexts=fileexts)
        assert _has("UserChoice")                 # start-up: left alone
        oi.register_association(r"C:\PAD", take_raw=True, classes=classes,
                                fileexts=fileexts)
        assert not _has("UserChoice") and not _has("UserChoiceLatest")
        assert oi.raw_chosen_elsewhere(".raw", fileexts) == ""
        _choose(oi.PROGID)
        assert oi.release_windows_choice(".raw", fileexts) is True
        assert _has("UserChoice")                 # PAD's own: kept
    finally:
        def _drop(path):
            try:
                with winreg.OpenKey(hk, path) as k:
                    kids = []
                    while True:
                        try:
                            kids.append(winreg.EnumKey(k, len(kids)))
                        except OSError:
                            break
                for c in kids:
                    _drop(path + "\\" + c)
                winreg.DeleteKey(hk, path)
            except OSError:
                pass
        _drop(base)


def test_app_name_says_what_windows_calls_the_choice(monkeypatch):
    """The warning names the app the user chose, never a Store app's
    "AppX..." ProgId (PAD-1518: it printed AppX9rkaq77s0jzh1tyccadx9ghba15r6t3h
    for Photos)."""
    from pinball_decryptor.webui import open_image as oi
    names = {"AppX9rkaq77s0jzh1tyccadx9ghba15r6t3h": "Photos"}
    monkeypatch.setattr(oi, "_assoc_friendly_app_name",
                        lambda p: names.get(p, ""))
    assert oi.app_name("AppX9rkaq77s0jzh1tyccadx9ghba15r6t3h") == "Photos"
    assert oi.app_name(r"Applications\IrfanView.exe") == "IrfanView.exe"
    assert oi.app_name("SomeApp.raw") == "SomeApp.raw"


@pytest.mark.skipif(os.name != "nt", reason="Windows' own lookup")
def test_friendly_app_name_never_raises_on_an_unknown_progid():
    from pinball_decryptor.webui import open_image as oi
    assert oi._assoc_friendly_app_name("NoSuch.ProgId.PAD1518") == ""


def _card_images_item(w):
    menu = [i for i in w.state("shell")["settings_items"]
            if i.get("label") == "Card images"][0]["submenu"]
    return [i for i in menu if i.get("id") == "toggle_card_images"][0]


@pytest.mark.skipif(os.name != "nt", reason="a Windows menu")
def test_gear_toggle_sets_up_and_takes_away(tmp_path, monkeypatch):
    """⚙ > Card images > Open card images with PAD: off until the user ticks
    it (David, 2026-11-23); on takes .raw even from another program and
    says when Windows' own choice still wins; off again takes the
    association away; each is remembered."""
    import json
    from pinball_decryptor.webui import open_image as oi
    calls = []
    monkeypatch.setattr(oi, "install_dir", lambda: r"C:\PAD")
    monkeypatch.setattr(oi, "unregister_association",
                        lambda classes=None: calls.append("off") or True)
    monkeypatch.setattr(oi, "register_association",
                        lambda app_dir=None, take_raw=False, classes=None,
                        fileexts=None:
                        calls.append(("on", take_raw)) or True)
    monkeypatch.setattr(oi, "raw_chosen_elsewhere", lambda: "Photos")
    # another app also opens .raw: Windows' own question comes up from the
    # switch (PAD-1518), never a real dialog in a test
    monkeypatch.setattr(oi, "raw_is_pads", lambda: False)
    monkeypatch.setattr(oi, "ask_windows",
                        lambda ext=".raw": calls.append(("ask", ext)) or True)
    with web_app(tmp_path, mfr="stern") as w:
        item = _card_images_item(w)
        assert item["label"] == "Open card images with PAD"
        assert item["checked"] is False and not item.get("disabled")

        def _saved():
            return json.loads((tmp_path / "cfg" / "settings.json")
                              .read_text(encoding="utf-8"))["card_images"]
        w.call("ui.settings_action", "toggle_card_images")
        wait_for(w, lambda: ("ask", ".raw") in calls)
        calls.remove(("ask", ".raw"))
        assert calls == [("on", True)]
        assert _card_images_item(w)["checked"] is True
        assert _saved() is True
        w.call("ui.settings_action", "toggle_card_images")
        assert calls == [("on", True), "off"]
        assert _card_images_item(w)["checked"] is False
        assert _saved() is False


def test_start_up_registers_only_when_ticked():
    """host.build sets the association up at start-up only for a user who
    ticked the gear switch: a new install leaves Explorer alone."""
    with open(os.path.join(ROOT, "pinball_decryptor", "webui", "host.py"),
              encoding="utf-8") as f:
        src = f.read()
    at = src.index("open_image.register_association")
    assert '.get("card_images", False)' in src[at - 400:at]


@pytest.mark.skipif(os.name != "nt", reason="a Windows menu")
def test_gear_toggle_is_greyed_in_a_checkout(tmp_path, monkeypatch):
    from pinball_decryptor.webui import open_image as oi
    monkeypatch.setattr(oi, "install_dir", lambda: None)
    with web_app(tmp_path, mfr="stern") as w:
        item = _card_images_item(w)
        assert item["disabled"] is True
        assert "installed app" in item["title"]
