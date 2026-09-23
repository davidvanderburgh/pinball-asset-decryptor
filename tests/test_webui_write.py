"""The web Write tab (webui/tabs/write.py): per-manufacturer state, the
Modified Files scan, the one primary button and its Cancel, the Build /
flash dialog, Card diagnostics, Image Info, the BOF version date and the
exports the run logic (app.py) reads.  Nothing here touches a real card:
drive enumeration is faked and every run callback is a recorder."""

import hashlib
import os
import time

import pytest

from tests.webui_harness import web_app

EXPORTS = (
    "write_assets_var", "write_output_var", "write_upd_var",
    "write_input_source_var", "write_filename_var", "write_drive_var",
    "write_version_override", "write_version_validation_error",
    "_target_write_path", "text_grow_enabled", "set_flash_running",
    "begin_revert_view", "_remember_flashed_image",
    "write_partition_override_var",
)


@pytest.fixture(autouse=True)
def _no_real_runs(monkeypatch):
    """Belt and braces: no test here may reach a real build, flash, direct
    write, revert or delta.  The window's callbacks are bound when the app is
    built (after this patch), so a test that forgets its recorder fails loud
    instead of starting a pipeline."""
    from pinball_decryptor import app as app_mod

    def _refuse(name):
        def _f(self, *a, **k):
            raise AssertionError("a Write test reached the real %s" % name)
        return _f
    for name in ("_start_write", "_start_direct_ssd_write",
                 "_start_flash_image", "_on_build_flash_request",
                 "_start_revert_all", "_start_apply_delta",
                 "_start_read_card"):
        monkeypatch.setattr(app_mod.App, name, _refuse(name))


def wait_for(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    w.drain()
    return pred()


def _md5(data):
    return hashlib.md5(data).hexdigest()


def make_project(root, changed=True):
    """A project folder with a .checksums.md5 baseline; one file edited."""
    proj = root / "proj"
    (proj / "audio").mkdir(parents=True)
    (proj / "images").mkdir(parents=True)
    files = {"audio/a.wav": b"RIFF-a", "images/b.png": b"PNG-b"}
    lines = []
    for rel, data in files.items():
        (proj / rel).write_bytes(data)
        lines.append("%s  %s" % (_md5(data), rel))
    (proj / ".checksums.md5").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")
    if changed:
        (proj / "images" / "b.png").write_bytes(b"PNG-b-edited")
    return proj


DRIVE = r"\\.\PhysicalDrive9"


def fake_drives(monkeypatch, drives=None):
    from pinball_decryptor.core import drives as drv
    if drives is None:
        drives = [drv.PhysicalDrive(device_path=r"\\.\PhysicalDrive9",
                                    model="SDXC Card Reader",
                                    size_bytes=32 * 10 ** 9, bus_type="USB")]
    monkeypatch.setattr(drv, "list_physical_drives", lambda: list(drives))
    return drives


def recorder(w, name):
    calls = []

    def _rec(*a, **k):
        calls.append((a, k))
    w.window.cb[name] = _rec
    return calls


def point_at(w, original, project):
    w.call("ui.set", "extract", "input", str(original))
    w.call("ui.set", "extract", "output", str(project))
    w.drain()


# ------------------------------------------------------------------ state
CASES = [
    # mfr, era, direct, flash, revert, diagnose, grow, version, delta, help
    ("stern", "", True, True, True, False, True, False, False, False),
    ("stern", "spike1", False, True, True, False, False, False, False, False),
    ("jjp", "", True, True, True, False, False, False, False, True),
    ("cgc", "", False, True, True, True, False, False, False, True),
    ("dp", "", True, False, True, False, False, False, True, False),
    ("bof", "", False, False, True, False, False, True, False, True),
    ("pb", "", False, False, True, False, False, False, True, True),
    ("ap", "", False, False, True, False, False, False, False, True),
    ("spooky", "", False, False, True, False, False, False, False, True),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0] + (c[1] and "-" + c[1]))
def test_state_after_manufacturer(tmp_path, case):
    mfr, era, direct, flash, revert, diag, grow, version, delta, helps = case
    with web_app(tmp_path, mfr=mfr, era=era or None) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["write"]["visible"]
        s = w.state("write")
        assert s["write_cap"] is True
        assert s["direct"] is direct
        assert s["flash"] is flash
        assert s["revert_cap"] is revert
        assert s["diagnose"] is diag
        assert s["text_grow_cap"] is grow
        assert s["version_cap"] is version
        assert s["delta_cap"] is delta
        assert bool(s["install_help"]) is helps
        # the subtitle names what Build makes: a flash plugin's image, the
        # others' update package (their button reads "Build update")
        assert s["build_noun"] == ("an image" if flash else "an update")
        assert s["source"] == "iso"
        assert s["direct_mode"] is False
        assert (s["editable_hint"] != "") is (mfr == "bof")
        if flash:
            assert s["primary_label"] == s["flash_label"]
        else:
            assert s["primary_label"] == w.window.current_mfr.write_build_button
        assert s["original_label"].startswith("Original")
        if mfr == "stern":
            assert s["original_label"] == "Original Card image"
            assert s["iso_label"] == "Build SD-card image"
            assert s["ssd_label"] == "Write to SD card"
            assert s["flash_label"] == "Build / flash SD card…"
        if mfr == "jjp":
            assert s["flash_label"] == "Build / make USB install stick…"
        # every export the run logic reads is this tab's own
        svc = w.window.service("write")
        for name in EXPORTS:
            got = getattr(w.window, name)
            if name.endswith("_var"):
                assert w.window._exports.get(name) is svc, name
            else:
                assert callable(got), name
        assert w.window.text_grow_enabled() is svc.text_grow_enabled()
        assert not {n for n in (getattr(w.window, "missing_exports", {})
                                or {}) if n.startswith("write_")}


@pytest.mark.parametrize("mfr,era", [("williams", ""), ("stern", "whitestar")])
def test_hidden_without_write(tmp_path, mfr, era):
    with web_app(tmp_path, mfr=mfr, era=era or None) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["write"]["visible"]
        assert w.state("write")["write_cap"] is False


# ------------------------------------------------- mirrors + Build Image
def test_mirrors_and_build_path(tmp_path):
    proj = make_project(tmp_path)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0" * 1024)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, orig, proj)
        win = w.window
        assert win.write_upd_var.get() == str(orig)
        assert win.write_assets_var.get() == str(proj)
        assert win.write_output_var.get() == os.path.normpath(
            str(proj / "build"))
        assert win.write_filename_var.get() == "godzilla-modified.raw"
        target = win._target_write_path()
        assert target == os.path.abspath(str(proj / "build" /
                                             "godzilla-modified.raw"))
        s = w.state("write")
        assert s["build_path"] == target
        assert s["project"] == str(proj) and s["project_set"]
        assert s["filename_hint"] == ""
        # an existing build: the grey "already exists" line
        (proj / "build").mkdir()
        (proj / "build" / "godzilla-modified.raw").write_bytes(b"x")
        w.call("ui.set", "write", "filename", "godzilla-modified.raw")
        s = w.state("write")
        assert "already exists here" in s["filename_hint"]
        assert s["filename_hint_kind"] == "muted"
        # a typed name gets the forced extension, and says so
        w.call("ui.set", "write", "filename", "mine")
        assert w.state("write")["filename_hint"] == "Will build: mine.raw"
        # the name of the original in its own folder: red
        w.call("ui.set", "write", "output", str(tmp_path))
        w.call("ui.set", "write", "filename", "godzilla.img")
        # .img is forced to .raw, so point at a .raw original instead
        raw = tmp_path / "card.raw"
        raw.write_bytes(b"\0")
        w.call("ui.set", "extract", "input", str(raw))
        w.call("ui.set", "write", "filename", "card.raw")
        s = w.state("write")
        assert s["filename_hint_kind"] == "err"
        assert "matches the original" in s["filename_hint"]


def test_change_build_location(tmp_path):
    proj = make_project(tmp_path)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0")
    other = tmp_path / "out"
    other.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, orig, proj)
        w.answers.append(str(other / "renamed"))
        w.call("write.change_build_location")
        assert w.asked[-1]["kind"] == "file"
        assert w.asked[-1]["title"] == "Build image as"
        assert w.window.write_output_var.get() == str(other)
        assert w.window.write_filename_var.get() == "renamed.raw"


def test_missing_checksums_warning(tmp_path):
    folder = tmp_path / "proj" / "sub"
    folder.mkdir(parents=True)
    (tmp_path / "proj" / ".checksums.md5").write_text("", encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(folder))
        s = w.state("write")
        assert "Did you mean the parent folder" in s["assets_warning"]


# ---------------------------------------------------------- the list
def test_scan_lists_modified_sort_export_revert(tmp_path):
    proj = make_project(tmp_path)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0")
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, orig, proj)
        w.call("ui.select_tab", "write")
        assert wait_for(w, lambda: not w.state("write")["scanning"]
                        and w.state("write")["count"] == 1)
        s = w.state("write")
        assert s["rows"][0] == {"file": "images/b.png", "type": "png",
                                "status": "Modified", "tag": "modified"}
        assert s["revert_enabled"] is True
        assert w.window._has_pending_write_changes()
        # sort cycles asc -> desc -> scan order
        assert w.call("write.sort", "type")
        assert w.state("write")["sort"] == {"key": "type", "desc": False}
        w.call("write.sort", "type")
        assert w.state("write")["sort"] == {"key": "type", "desc": True}
        w.call("write.sort", "type")
        assert w.state("write")["sort"] is None
        # Export CSV writes the list as shown
        out = tmp_path / "list.csv"
        w.answers.append(str(out))
        assert w.call("write.export_csv") is True
        text = out.read_text(encoding="utf-8-sig")
        assert text.splitlines()[0] == "File,Type,Status"
        assert "images/b.png,png,Modified" in text
        # Revert hands the folder to the run logic
        rec = recorder(w, "on_revert_all")
        assert w.call("write.revert_all") is True
        assert rec == [((str(proj),), {})]
        # the revert blanks the list at once
        w.run(w.window.begin_revert_view)
        s = w.state("write")
        assert s["rows"] == [] and s["empty"] == "Reverting…"


def test_scan_empty_states(tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        w.call("ui.select_tab", "write")
        w.run(w.window.service("write")._scan_write_preview)
        assert wait_for(w, lambda: not w.state("write")["scanning"])
        assert w.state("write")["empty"].startswith("Select your modified")
        proj = make_project(tmp_path, changed=False)
        w.call("ui.set", "extract", "output", str(proj))
        assert wait_for(w, lambda: not w.state("write")["scanning"])
        # Refresh while idle scans; while scanning it is "Cancel scan"
        assert w.call("write.refresh") is True
        assert wait_for(w, lambda: not w.state("write")["scanning"])
        s = w.state("write")
        assert s["count"] == 0
        assert s["empty"] == "No modified files detected."
        assert s["revert_enabled"] is False
        export = w.call("write.export_csv")
        assert export is False
        assert "Nothing to export yet" in w.asked[-1]["message"]


def test_scan_pauses_during_a_run(tmp_path):
    proj = make_project(tmp_path)
    with web_app(tmp_path, mfr="pb") as w:
        w.call("ui.set", "extract", "output", str(proj))
        svc = w.window.service("write")
        w.run(lambda: w.window.set_running(True, "write"))
        w.run(svc._scan_write_preview)
        assert svc._rescan_after_run is True
        assert w.state("write")["refresh_disabled"] is True
        w.call("ui.select_tab", "write")
        w.run(lambda: w.window.set_running(False, "write"))
        assert wait_for(w, lambda: w.state("write")["count"] == 1)


# ------------------------------------------------ the one primary button
def test_plain_build_button_and_nothing_modified_guard(tmp_path):
    proj = make_project(tmp_path, changed=False)
    with web_app(tmp_path, mfr="pb") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "write")
        assert wait_for(w, lambda: not w.state("write")["scanning"])
        rec = recorder(w, "on_write")
        w.answers.append("no")
        assert w.call("write.primary") is False
        assert w.asked[-1]["title"] == "Nothing modified"
        assert rec == []
        w.answers.append("yes")
        assert w.call("write.primary") is True
        assert len(rec) == 1


def test_one_live_cancel(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        w.run(lambda: win.set_running(True, "write"))
        s = w.state("write")
        assert s["cancel"] is True and s["primary_disabled"] is False
        cancels = recorder(w, "on_write_cancel")
        assert w.call("write.primary") == "cancel"
        assert len(cancels) == 1
        w.run(lambda: win.set_running(False, "write"))
        s = w.state("write")
        assert s["cancel"] is False
        assert s["primary_label"] == "Build / flash SD card…"
        # someone else's run: greyed, idle label, no Cancel
        w.run(lambda: win.set_running(True, "extract"))
        s = w.state("write")
        assert s["cancel"] is False and s["primary_disabled"] is True
        w.run(lambda: win.set_running(False, "extract"))
        # a flash owns the button until the run ends
        w.run(lambda: win.set_running(True, "write"))
        w.run(lambda: win.set_flash_running(True))
        assert w.state("write")["cancel"] is True
        w.run(lambda: win.set_running(False, "write"))
        assert w.state("write")["cancel"] is False
        assert w.state("write")["primary_disabled"] is False


def test_busy_refuses_the_dialog(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.set_running(True, "extract"))
        assert w.run(w.window.service("write")._open_flash_dialog) is False
        assert w.asked[-1]["title"] == "Busy"
        assert w.state("write")["flash_dlg"] is None
        w.run(lambda: w.window.set_running(False, "extract"))


# ---------------------------------------------------- Build / flash dialog
def test_flash_dialog_flash_only(tmp_path, monkeypatch):
    fake_drives(monkeypatch)
    proj = make_project(tmp_path, changed=False)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0" * 4096)
    image = tmp_path / "backup.raw"
    image.write_bytes(b"\0" * 2048)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, orig, proj)
        w.call("ui.select_tab", "write")
        assert wait_for(w, lambda: not w.state("write")["scanning"])
        flashes = recorder(w, "on_flash_image")
        assert w.call("write.primary") is True
        assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                        .get("drives"))
        f = w.state("write")["flash_dlg"]
        assert f["title"] == "Build / flash SD card image"
        assert f["can_build"] is True
        # nothing modified: opens flash-only
        assert f["build"] is False and f["write"] is True
        assert f["start_label"] == "Flash image"
        assert f["drive"] == 0
        w.call("write.flash_set", "image_path", str(image))
        f = w.state("write")["flash_dlg"]
        assert "✓ fits" in f["readout"] and f["readout_kind"] == "ok"
        assert f["menu_enabled"] is False     # not a Stern card image
        w.answers += ["yes", "yes"]           # Nothing modified, Erase
        assert w.call("write.flash_start") is True
        titles = [a["title"] for a in w.asked[-2:]]
        assert titles == ["Nothing modified",
                          "Erase the SD card and continue?"]
        assert "Target: SDXC Card Reader" in w.asked[-1]["message"]
        assert flashes == [((str(image), r"\\.\PhysicalDrive9"),
                            {"menu_only": False})]
        assert w.state("write")["flash_dlg"] is None
        # the pair that was RUN is remembered for next time
        assert w.window.service("write")._saved_flash_choices["stern"] == \
            {"write": True, "build": False}


def test_flash_dialog_build_and_flash(tmp_path, monkeypatch):
    fake_drives(monkeypatch)
    proj = make_project(tmp_path)
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0" * 4096)
    with web_app(tmp_path, mfr="stern") as w:
        point_at(w, orig, proj)
        w.call("ui.select_tab", "write")
        assert wait_for(w, lambda: not w.state("write")["scanning"]
                        and w.state("write")["count"] == 1)
        builds = recorder(w, "on_build_flash")
        w.call("write.primary")
        assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                        .get("drives"))
        f = w.state("write")["flash_dlg"]
        assert f["build"] is True and f["write"] is True
        assert f["start_label"] == "Build + flash"
        assert f["image_path"] == f["build_path"]
        assert f["image_enabled"] is False
        assert "built first" in f["readout"]
        assert "freshly built" in f["menu_note"]
        # cancelling the confirm keeps the dialog open
        w.answers.append("no")
        assert w.call("write.flash_start") is False
        assert w.state("write")["flash_dlg"] is not None
        w.answers.append("yes")
        assert w.call("write.flash_start") is True
        assert "After the build finishes" in w.asked[-1]["message"]
        assert builds == [((f["build_path"], r"\\.\PhysicalDrive9"), {})]


def test_flash_dialog_cannot_build_without_a_project(tmp_path, monkeypatch):
    fake_drives(monkeypatch, drives=[])
    with web_app(tmp_path, mfr="cgc") as w:
        w.call("write.primary")
        assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                        .get("drive_text", "").startswith("(no drives"))
        f = w.state("write")["flash_dlg"]
        assert f["can_build"] is False
        assert f["cannot_build_reason"].startswith(
            "Set the original image and the assets folder and the build "
            "location")
        w.call("write.flash_set", "build", True)     # disabled box: ignored
        assert w.state("write")["flash_dlg"]["build"] is False
        w.answers.append("ok")
        assert w.call("write.flash_start") is False
        assert w.asked[-1]["title"] == "No image"
        assert w.call("write.flash_close") is True
        assert w.state("write")["flash_dlg"] is None


def test_jjp_stick_picker_never_guesses(tmp_path, monkeypatch):
    from pinball_decryptor.core import drives as drv
    fake_drives(monkeypatch, [drv.PhysicalDrive(
        device_path=r"\\.\PhysicalDrive3", model="Samsung SSD 870",
        size_bytes=500 * 10 ** 9, bus_type="SATA")])
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("write.primary")
        assert wait_for(w, lambda: "no USB stick" in (
            w.state("write")["flash_dlg"] or {}).get("drive_text", ""))
        f = w.state("write")["flash_dlg"]
        assert f["drive"] is None
        assert f["title"] == "Build / make USB install stick"
        w.call("write.flash_close")


def test_remember_flashed_image(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        seen = []
        w.window.cb["on_flashed_images_change"] = seen.append
        w.run(lambda: w.window._remember_flashed_image("x", digest="abc"))
        w.run(lambda: w.window._remember_flashed_image("y", digest="def"))
        assert seen[-1] == ["def", "abc"]


# -------------------------------------------------------- direct mode
def test_direct_mode_picks_the_card(tmp_path, monkeypatch):
    fake_drives(monkeypatch)
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("write.set_source", "ssd") is True
        assert wait_for(w, lambda: w.window.write_drive_var.get() != "")
        s = w.state("write")
        assert s["direct_mode"] is True
        assert w.window.write_drive_var.get() == r"\\.\PhysicalDrive9"
        assert w.window._target_write_path() == ""
        assert s["filename_hint"] == ""
        w.call("write.set_source", "iso")
        assert w.state("write")["direct_mode"] is False


# --------------------------------------------------------------- options
def test_text_grow_toggle_persists_and_mirrors(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.window.text_grow_enabled() is True
        w.call("ui.set", "write", "text_grow", False)
        assert w.window.text_grow_enabled() is False
        assert os.environ.get("PAD_STERN_TEXT_GROW") == "0"
        assert w.app._settings.get("text_grow") is False
        w.call("ui.set", "write", "text_grow", True)
        assert os.environ.get("PAD_STERN_TEXT_GROW") == "1"


def test_bof_version_date(tmp_path):
    with web_app(tmp_path, mfr="bof") as w:
        win = w.window
        assert win.write_version_override() is None
        assert win.write_version_validation_error() is None
        w.call("ui.set", "write", "version_auto", False)
        w.call("ui.set", "write", "version_date", "")
        assert "Enter an update version date" in \
            win.write_version_validation_error()
        w.call("ui.set", "write", "version_date", "2026.13.40")
        assert "isn't a valid date" in win.write_version_validation_error()
        w.call("ui.set", "write", "version_date", "2026.01.15")
        assert win.write_version_validation_error() is None
        assert win.write_version_override() == "2026.01.15"
        assert "select your extracted assets folder" in \
            w.state("write")["version_hint"]


# ------------------------------------------------------------- windows
def test_card_diagnostics_dialog(tmp_path, monkeypatch):
    fake_drives(monkeypatch)
    img = tmp_path / "card.img"
    img.write_bytes(b"\0")
    with web_app(tmp_path, mfr="cgc") as w:
        mfr = w.window.current_mfr

        def _diag(target, log=None):
            log("reading %s" % os.path.basename(target))
            return "REPORT OK"
        monkeypatch.setattr(mfr, "diagnose_card", _diag)
        assert w.call("write.diag_open") is True
        assert wait_for(w, lambda: (w.state("write")["diag"] or {})
                        .get("drives"))
        w.answers.append(str(img))
        assert w.call("write.diag_read_file") is True
        assert wait_for(w, lambda: (w.state("write")["diag"] or {})
                        .get("can_save"))
        d = w.state("write")["diag"]
        assert "reading card.img" in d["text"] and "REPORT OK" in d["text"]
        out = tmp_path / "rep.txt"
        w.answers += [str(out), "ok"]
        assert w.call("write.diag_save") is True
        assert out.read_text(encoding="utf-8").startswith("REPORT OK")
        w.call("write.diag_close")
        assert w.state("write")["diag"] is None


def test_image_info_window(tmp_path):
    orig = tmp_path / "godzilla.img"
    orig.write_bytes(b"\0" * 512)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", str(orig))
        assert w.call("write.image_info") is True
        assert wait_for(w, lambda: (w.state("write")["info"] or {})
                        .get("sections"))
        info = w.state("write")["info"]
        assert info["path"] == os.path.normpath(str(orig))
        text = w.call("write.image_info_copy")
        assert "godzilla.img" in text
        w.call("write.image_info_close")
        assert w.state("write")["info"] is None


def test_manufacturer_switch_resets_to_image_mode(tmp_path, monkeypatch):
    fake_drives(monkeypatch)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("write.set_source", "ssd")
        w.call("ui.pick_manufacturer", "pb")
        w.drain()
        assert w.window.write_input_source_var.get() == "iso"
        assert w.state("write")["direct_mode"] is False


def test_handed_in_card_from_another_tab(tmp_path, monkeypatch):
    """The Multi-boot tab's "flash this card": write only, no Build section,
    no "nothing modified", the Write tab shown under it and the calling tab
    back when it closes."""
    fake_drives(monkeypatch)
    card = tmp_path / "multi.raw"
    card.write_bytes(b"\0" * 1024)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "extract")
        svc = w.window.service("write")
        flashes = recorder(w, "on_flash_image")
        assert w.run(lambda: w.window._open_flash_dialog(
            initial_image=str(card), fresh=True)) is True
        assert w.state("shell")["tab"] == "write"
        assert wait_for(w, lambda: (w.state("write")["flash_dlg"] or {})
                        .get("drives"))
        f = w.state("write")["flash_dlg"]
        assert f["handed_in"] is True
        assert f["title"] == "Flash SD card image"
        assert f["header"] == "Write the Multi-boot card onto the SD card"
        assert f["build"] is False and f["write"] is True
        assert f["image_path"] == str(card)
        w.answers.append("yes")                     # Erase … and continue?
        assert w.call("write.flash_start") is True
        assert [a["title"] for a in w.asked] == [
            "Erase the SD card and continue?"]
        assert flashes[0][0] == (str(card), DRIVE)
        assert w.state("shell")["tab"] == "extract"
        # a handed-in card is not the Write tab's own choice
        assert "stern" not in svc._saved_flash_choices


def test_borrowed_write_tab_does_not_rescan(tmp_path, monkeypatch):
    """While another tab borrows the Write page as the dialog's backdrop,
    Write's on_show does not start the project's MD5 walk."""
    fake_drives(monkeypatch)
    proj = make_project(tmp_path)
    card = tmp_path / "multi.raw"
    card.write_bytes(b"\0" * 1024)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "write")
        assert wait_for(w, lambda: not w.state("write")["scanning"]
                        and w.state("write")["count"] == 1)
        w.call("ui.select_tab", "extract")
        svc = w.window.service("write")
        svc._disk_epoch += 1          # a real entry would rescan now
        before = svc._scan_id
        assert w.run(lambda: w.window._open_flash_dialog(
            initial_image=str(card), fresh=True)) is True
        assert w.state("shell")["tab"] == "write"
        assert svc._scan_id == before
        assert w.state("write")["scanning"] is False
        w.call("write.flash_close")
        assert w.state("shell")["tab"] == "extract"
        # the user's own visit still rescans
        w.call("ui.select_tab", "write")
        assert svc._scan_id > before


def test_hosted_flash_dialog_stays_on_the_calling_tab(tmp_path, monkeypatch):
    """Once the shell draws the dialog over every tab (WriteOverlays calls
    write.flash_host_ready), the Multi-boot hand-in opens it over that tab,
    as Tk did: no tab switch either way."""
    fake_drives(monkeypatch)
    card = tmp_path / "multi.raw"
    card.write_bytes(b"\0" * 1024)
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("write.flash_host_ready") is True
        assert w.state("write")["flash_hosted"] is True
        w.call("ui.select_tab", "extract")
        assert w.run(lambda: w.window._open_flash_dialog(
            initial_image=str(card), fresh=True)) is True
        assert w.state("shell")["tab"] == "extract"
        assert w.state("write")["flash_dlg"]["handed_in"] is True
        w.call("write.flash_close")
        assert w.state("write")["flash_dlg"] is None
        assert w.state("shell")["tab"] == "extract"


# ------------------------------------------------------- column widths
def test_column_widths_carry_over_and_save(tmp_path):
    """Tk kept the dragged Modified Files widths under
    column_widths.write_preview by its column ids; the page reads them by
    its own keys and a drag writes them back the Tk way."""
    tuned = {"write_preview": {"#0": 488, "type": 149, "status": 289},
             "audio_web": {"#0": 300}}
    with web_app(tmp_path, mfr="stern",
                 settings={"column_widths": tuned}) as w:
        assert w.state("write")["widths"] == {"file": 488, "type": 149,
                                              "status": 289}
        assert w.call("write.save_widths", {"file": 320, "type": 64})
        saved = w.app._settings["column_widths"]
        assert saved["write_preview"] == {"#0": 320, "type": 64,
                                          "status": 289}
        assert saved["audio_web"] == {"#0": 300}     # other lists kept
        assert w.state("write")["widths"] == {"file": 320, "type": 64,
                                              "status": 289}
        # nonsense is refused, and leaves what was saved
        assert w.call("write.save_widths", {"file": 5, "bogus": 90,
                                            "type": True}) is False
        assert w.app._settings["column_widths"]["write_preview"]["#0"] == 320


def test_column_widths_default_empty(tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        assert w.state("write")["widths"] == {}
        assert w.call("write.save_widths", {"file": 400, "type": 80})
        assert w.app._settings["column_widths"]["write_preview"] == {
            "#0": 400, "type": 80}


# ------------------------------------- one Administrator panel flag
def test_admin_panel_collapse_is_one_flag(tmp_path):
    """Tk drove every Administrator panel from one flag: collapsing it on
    Write collapses Extract's too, and the reverse, and it is saved once."""
    with web_app(tmp_path, mfr="dp") as w:
        assert w.state("write")["admin_collapsed"] is False
        assert w.call("write.toggle_admin_warning") is True
        assert w.state("write")["admin_collapsed"] is True
        assert w.state("extract")["admin_collapsed"] is True
        assert w.app._settings["admin_warning_collapsed"] is True
        # flipped from the Extract tab: Write shows it on its next entry
        w.call("ui.select_tab", "extract")
        w.call("extract.toggle_admin_warning")
        assert w.state("extract")["admin_collapsed"] is False
        assert w.app._settings["admin_warning_collapsed"] is False
        w.call("ui.select_tab", "write")
        assert w.state("write")["admin_collapsed"] is False
        # and Write flips the shared value, not a stale copy of its own
        assert w.call("write.toggle_admin_warning") is True
        assert w.state("extract")["admin_collapsed"] is True
        assert w.app._settings["admin_warning_collapsed"] is True


def test_fda_hide_reaches_every_panel(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("write.dismiss_fda") is True
        assert w.state("write")["fda_ack"] is True
        assert w.state("extract")["fda_ack"] is True


# --------------------------------------------------- Before you build
def test_before_you_build_notes(tmp_path, monkeypatch):
    """The design's card: a video slot the machine can't play (err), Replace
    assignments made for another folder (warn), files this extract never
    produced (info), in the words the Video tab / app.py / the Replace tabs
    already use."""
    proj = make_project(tmp_path, changed=False)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        win = w.window
        svc = win.service("write")
        audio = win.service("audio")
        video = win.service("video")
        assert w.state("write")["prebuild"] == []

        audio._scan_dir = str(proj)
        audio._foreign = {"audio/x%d.wav" % i for i in range(6)}
        monkeypatch.setattr(
            type(audio), "replacement_folder_mismatches",
            lambda self, assets: [("audio", 2, r"X:\other")])
        from pinball_decryptor.webui import video_helpers as vh
        monkeypatch.setattr(
            vh, "slot_unplayable",
            lambda key, slot: "is HEVC and the machine plays H.264")
        video._by_rel = {"modes/m/clip.mp4": object()}
        video._unplayable_warned = {(str(proj), "modes/m/clip.mp4")}
        w.run(svc._refresh_prebuild_notes)
        notes = w.state("write")["prebuild"]
        assert [n["kind"] for n in notes] == ["err", "warn", ""]
        assert notes[0]["text"].startswith(
            'Video slot "modes/m/clip.mp4" currently holds a clip that is '
            'HEVC and the machine plays H.264')
        assert notes[1]["text"].startswith(
            "Your Replace-tab assignments were made against a different "
            "project folder")
        assert "2 audio replacement(s)" in notes[1]["text"]
        assert notes[2]["text"] == (
            "Replace Audio: 6 file(s) in this folder aren't part of this "
            "extract (audio/x0.wav, audio/x1.wav, audio/x2.wav, and 3 "
            "more); a build can't use them.")
        # another folder's scan says nothing about this one
        audio._scan_dir = str(tmp_path / "elsewhere")
        video._unplayable_warned = {(str(tmp_path), "modes/m/clip.mp4")}
        w.run(svc._refresh_prebuild_notes)
        assert [n["kind"] for n in w.state("write")["prebuild"]] == ["warn"]


def test_editable_hint_and_warning_are_page_state(tmp_path):
    """BOF's tip and the .checksums warning are drawn under Project Folder
    (the page reads them from these keys)."""
    folder = tmp_path / "proj" / "sub"
    folder.mkdir(parents=True)
    (tmp_path / "proj" / ".checksums.md5").write_text("", encoding="utf-8")
    with web_app(tmp_path, mfr="bof") as w:
        w.call("ui.set", "extract", "output", str(folder))
        s = w.state("write")
        assert s["editable_hint"].startswith("Tip: edit your audio")
        assert s["assets_warning"].startswith("⚠ No `.checksums.md5` here.")


def test_change_walk_leaves_the_folder_alone_in_a_capture_run(
        tmp_path, monkeypatch):
    """A capture run walks the user's REAL project folder: the hash-cache
    sidecar must not be written there (a normal run does write it)."""
    from pinball_decryptor.core import hashcache
    from pinball_decryptor.webui.write_scan import walk_changes
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "a.wav").write_bytes(b"RIFF" + b"\0" * 64)
    sidecar = tmp_path / hashcache.CACHE_FILE
    saved = {"audio/a.wav": "0" * 32}       # a baseline, so the file is hashed

    monkeypatch.setenv("PAD_UI_CAPTURE", "1")
    walk_changes(str(tmp_path), saved, hide_imported_cache=False,
                 current=lambda: True)
    assert not sidecar.exists()

    monkeypatch.delenv("PAD_UI_CAPTURE")
    walk_changes(str(tmp_path), saved, hide_imported_cache=False,
                 current=lambda: True)
    assert sidecar.exists()
