"""The web Extract tab (webui/tabs/extract.py): per-manufacturer layout,
the page's calls, and every window attribute the run logic reads off it.

Nothing here runs an extract, reads a card or enumerates real drives: the
plugin hooks that would touch a device (detect, identify_card, drive
enumeration, the read-card run) are replaced per test.
"""

import os
import re
import time
import types
from pathlib import Path

import pytest

from tests.webui_harness import web_app

APP_PY = Path(__file__).resolve().parents[1] / "pinball_decryptor" / "app.py"


def _svc(w):
    return w.window.service("extract")


def _settle(w, rounds=6):
    """Wait for the tab's worker threads and the loop jobs they post."""
    svc = _svc(w)

    def _flush_stats():                 # a debounced stats timer: run it now
        if svc._stats_after is not None:
            svc.ctx.loop.after_cancel(svc._stats_after)
            svc._start_stats()

    for _ in range(rounds):
        w.drain()
        w.run(_flush_stats)
        alive = [t for t in svc._workers() if t.is_alive()]
        for t in alive:
            t.join(15)
        w.drain()
        if not alive:
            return


def _mfr(w, key):
    return next(m for m in w.window.manufacturers if m.key == key)


def _titles(w):
    return [a.get("title") for a in w.asked]


# ---------------------------------------------------------------- exports
def test_every_export_resolves_to_the_service(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        for name in svc.exports:
            assert w.window._exports.get(name) is svc, name
            getattr(w.window, name)          # never raises
        assert not getattr(w.window, "missing_exports", {}), \
            "stand-ins handed out: %s" % sorted(w.window.missing_exports)


def test_app_reads_of_extract_attributes_are_provided(tmp_path):
    text = APP_PY.read_text(encoding="utf-8")
    names = set(re.findall(r"self\.window\.([A-Za-z_][A-Za-z0-9_]*)", text))
    names |= set(re.findall(r'getattr\(self\.window,\s*"([A-Za-z_]+)"', text))
    mine = {n for n in names if n.startswith("extract_") or n in {
        "static_extract_var", "capture_mode_var", "capture_duration_var",
        "capture_gameplay_var", "decode_dmd_var", "transcribe_var",
        "music_id_var", "duration_names_var", "_extract_category_vars",
        "get_extract_options", "set_extract_options",
        "_refresh_extract_phases", "acknowledge_macos_fda",
        "reset_dmd_preview", "on_dmd_frame", "on_capture_ready",
        "_on_input_source_change"}}
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        for name in sorted(mine):
            assert name in svc.exports, name
            assert w.window._exports.get(name) is svc, name


# ------------------------------------------------------ per manufacturer
LAYOUT = {
    # key: (input_label, direct, categories, filters, dongle, capture,
    #       capture_primary)
    "ap": (".pkg", False, [], False, False, False, False),
    "bof": (".fun", False, [], False, False, False, False),
    "cgc": (".img", False, [], False, False, False, False),
    "data_east": (".zip", False, [], False, False, True, True),
    "dp": (".zip", True, [], False, False, False, False),
    "jjp": (".iso", True, [], True, True, False, False),
    "pb": (".upd", False, [], False, False, False, False),
    "sega": (".zip", False, [], False, False, True, True),
    "spooky": (".pkg", False, [], False, False, False, False),
    "stern": ("Card image", True, ["audio", "video", "images", "text"],
              False, False, False, False),
    "williams": (".zip", False, [], False, False, True, False),
}


@pytest.mark.parametrize("key", sorted(LAYOUT))
def test_layout_per_manufacturer(tmp_path, key):
    label, direct, cats, filters, dongle, capture, primary = LAYOUT[key]
    with web_app(tmp_path, mfr=key) as w:
        _settle(w)
        st = w.state("extract")
        mfr = w.window.current_mfr
        assert st["mfr_key"] == key
        assert st["input_label"] == label
        assert st["direct"] is direct
        assert [c["key"] for c in st["categories"]] == cats
        assert st["asset_filters"] is filters
        assert st["dongle_cap"] is dongle
        assert st["capture_cap"] is capture
        assert st["capture_primary"] is primary
        assert st["ssd"] is False
        assert st["source"] == "iso"
        caps = mfr.capabilities
        # capture-primary plugins: capture forced on, Basic off
        if primary:
            assert st["capture"] is True and st["static"] is False
        elif not capture:
            assert st["capture"] is False and st["static"] is True
        # the auto-name options follow the capabilities
        assert st["opt_transcribe"] == bool(caps.transcribe and not primary)
        assert st["opt_music"] == bool(getattr(caps, "music_id", False))
        assert st["opt_duration"] == bool(
            getattr(caps, "audio_duration_names", False))
        # no paths: the gate names the input first
        assert st["block_reason"].startswith("Pick ")
        # the footer shows this manufacturer's extract ladder
        footer = w.state("shell")["footer"]
        if footer.get("mode") == "extract":
            assert tuple(footer["phases"]) == tuple(mfr.extract_phases)


@pytest.mark.parametrize("era,label,cats,capture", [
    ("spike2", "Card image", 4, False),
    ("spike1", "Card image", 0, False),
    ("whitestar", "ROM zip", 0, True),
])
def test_stern_eras(tmp_path, era, label, cats, capture):
    with web_app(tmp_path, mfr="stern", era=era) as w:
        _settle(w)
        st = w.state("extract")
        assert st["input_label"] == label
        assert len(st["categories"]) == cats
        assert st["capture_cap"] is capture
        assert st["direct"] is (era == "spike2")
        assert st["identify"] is (era == "spike2")
        assert st["read_card"] is (era == "spike2")
        assert st["block_reason"] == "Pick a %s to extract first." % label


def test_block_reason_order(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        assert w.state("extract")["block_reason"] == \
            "Pick a file to extract first."
        f = tmp_path / "game.iso"
        f.write_bytes(b"x")
        w.call("ui.set", "extract", "input", str(f))
        assert w.state("extract")["block_reason"] == \
            "Choose an output folder first."
        w.call("ui.set", "extract", "output", str(tmp_path / "proj"))
        assert w.state("extract")["block_reason"] == ""
        _settle(w)


def test_a_finished_extract_greys_the_button_until_something_changes(
        tmp_path):
    """PAD-206: after a successful extract the same card, folder and options
    would only redo it.  Picking the card (or folder) again, changing an
    option or replacing the card on disk brings the button back."""
    card = tmp_path / "game.raw"
    card.write_bytes(b"x")
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", str(card))
        w.call("ui.set", "extract", "output", str(proj))
        _settle(w)
        assert w.state("extract")["block_reason"] == ""

        def done():
            w.run(w.window.note_extract_done, str(card), str(proj))
            return w.state("extract")["block_reason"]

        assert done().startswith("Already extracted into this project")
        # an option change: the new run would differ
        w.call("ui.set", "extract", "cat_audio", False)
        assert w.state("extract")["block_reason"] == ""
        w.call("ui.set", "extract", "cat_audio", True)
        assert w.state("extract")["block_reason"].startswith("Already")

        # picking the SAME card again is the way to ask for a fresh run
        w.answers.append(str(card))
        assert w.call("extract.browse_input") is True
        assert w.state("extract")["block_reason"] == ""
        assert done().startswith("Already")
        assert w.call("extract.use_recent", "output", str(proj)) is True
        assert w.state("extract")["block_reason"] == ""
        assert done().startswith("Already")
        assert w.call("extract.drop_paths", [str(card)]) is True
        assert w.state("extract")["block_reason"] == ""

        # the card replaced on disk: seen when the tab is shown again
        assert done().startswith("Already")
        card.write_bytes(b"xy")
        w.run(_svc(w).on_show)
        assert w.state("extract")["block_reason"] == ""

        # another folder: not the same run
        assert done().startswith("Already")
        other = tmp_path / "other"
        other.mkdir()
        w.call("ui.set", "extract", "output", str(other))
        assert w.state("extract")["block_reason"] == ""
        _settle(w)


def test_the_run_logic_reports_a_finished_extract():
    src = APP_PY.read_text(encoding="utf-8")
    i = src.index("if is_extract and success and self._last_extract_io:")
    assert "note_extract_done" in src[i:src.index(
        "self._last_extract_io = None", i)]


# -------------------------------------------------------- options + phases
def test_options_round_trip_and_autoname_greys(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.run(svc.set_extract_options, {
            "auto_name_callouts": True, "auto_name_music": False,
            "duration_names": True, "categories": {"audio": False}})
        st = w.state("extract")
        assert st["transcribe"] is True and st["duration_names"] is True
        assert st["cat_audio"] is False and st["cat_video"] is True
        assert st["autoname_enabled"] is False
        w.call("ui.set", "extract", "cat_audio", True)
        assert w.state("extract")["autoname_enabled"] is True
        opts = w.run(svc.get_extract_options)
        assert opts["auto_name_callouts"] is True
        assert opts["categories"] == {"audio": True, "video": True,
                                      "images": True, "text": True}
        assert "asset_filters" not in opts
        _settle(w)


def test_jjp_filters_and_dongle_phases(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        svc = _svc(w)
        w.call("ui.set", "extract", "filesystem", True)
        opts = w.run(svc.get_extract_options)
        assert opts["asset_filters"] == {"graphics": True, "sounds": True,
                                         "filesystem": True}
        w.call("ui.set", "extract", "dongle", True)
        mfr = w.window.current_mfr
        assert tuple(w.window._phases["extract"]) == \
            tuple(mfr.dongle_extract_phases)
        w.call("ui.set", "extract", "dongle", False)
        assert tuple(w.window._phases["extract"]) == \
            tuple(mfr.extract_phases)
        _settle(w)


def test_williams_capture_toggles(tmp_path):
    with web_app(tmp_path, mfr="williams") as w:
        mfr = w.window.current_mfr
        st = w.state("extract")
        assert st["capture_help"].startswith("Basic only:")
        w.call("ui.set", "extract", "capture", True)
        assert w.state("extract")["capture_help"].startswith("Combined:")
        assert tuple(w.window._phases["extract"]) == \
            tuple(mfr.combined_phases)
        w.call("ui.set", "extract", "transcribe", True)
        w.call("ui.set", "extract", "static", False)
        st = w.state("extract")
        assert st["capture_help"].startswith("Capture only:")
        # hidden means off: no WAVs for transcribe without Basic extract
        assert st["opt_transcribe"] is False and st["transcribe"] is False
        w.call("ui.set", "extract", "capture", False)
        st = w.state("extract")
        assert st["capture_help"] == \
            "Tick at least one box above to run an extract."
        assert st["capture_help_kind"] == "err"
        _settle(w)


def test_start_without_input_warns(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        assert w.call("extract.start") is True
        assert "Missing Input" in _titles(w)
        assert w.call("extract.cancel") is False      # nothing running


# -------------------------------------------------------------- detection
def test_detected_game_names_the_title(tmp_path, monkeypatch):
    f = tmp_path / "card.raw"
    f.write_bytes(b"\0" * 64)
    with web_app(tmp_path, mfr="stern") as w:
        stern = w.window.current_mfr
        game = types.SimpleNamespace(display="Godzilla (Spike 2)",
                                     era="spike2")
        monkeypatch.setattr(stern, "detect",
                            lambda p: game if p == str(f) else None)
        monkeypatch.setattr(stern, "title_caption",
                            lambda p, g: "Godzilla v1.16 Premium")
        w.call("ui.set", "extract", "input", str(f))
        _settle(w)
        st = w.state("extract")
        assert st["badge"] is None
        assert st["detected"]["caption"] == "Godzilla v1.16 Premium"
        assert st["detected"]["size"] == 64
        assert w.app._detected_caption == "Godzilla v1.16 Premium"
        assert "Godzilla v1.16 Premium" in w.state("shell")["title"]
        # the Write tab's Original follows the input
        assert w.window.write_upd_var.get() == str(f)


def test_not_recognised_and_looks_like_switch(tmp_path, monkeypatch):
    f = tmp_path / "some.iso"
    f.write_bytes(b"\0" * 16)
    with web_app(tmp_path, mfr="jjp") as w:
        jjp = w.window.current_mfr
        stern = _mfr(w, "stern")
        for m in w.window.manufacturers:
            monkeypatch.setattr(m, "detect", lambda p: None)
        w.call("ui.set", "extract", "input", str(f))
        _settle(w)
        assert w.state("extract")["badge"]["text"] == \
            "Not recognised as %s" % jjp.display
        monkeypatch.setattr(stern, "detect", lambda p: types.SimpleNamespace(
            display="Godzilla (Spike 2)", era=""))
        w.call("ui.set", "extract", "input", str(f))
        _settle(w)
        badge = w.state("extract")["badge"]
        assert badge["switch"] is True
        assert badge["text"] == ("Looks like Godzilla (Spike 2) "
                                 "(Stern Pinball) — click to switch")
        assert w.call("extract.switch_suggested") is True
        _settle(w)
        assert w.window.current_mfr is stern
        assert w.window.extract_input_var.get() == str(f)


def test_era_auto_switch(tmp_path, monkeypatch):
    f = tmp_path / "rom.zip"
    f.write_bytes(b"PK")
    with web_app(tmp_path, mfr="stern") as w:
        stern = w.window.current_mfr
        assert stern.current_era == "spike2"
        game = types.SimpleNamespace(display="Lord of the Rings",
                                     era="whitestar")
        monkeypatch.setattr(stern, "detect",
                            lambda p: game if p == str(f) else None)
        monkeypatch.setattr(stern, "title_caption", lambda p, g: g.display)
        w.call("ui.set", "extract", "input", str(f))
        _settle(w)
        assert stern.current_era == "whitestar"
        # the era switch re-probes the input: its badge lands on a later
        # loop turn, which a loaded machine can push past _settle's rounds
        end = time.time() + 15
        while w.state("extract")["badge"] is None and time.time() < end:
            _settle(w, rounds=1)
            time.sleep(0.05)
        st = w.state("extract")
        assert st["input_label"] == "ROM zip"
        assert st["capture_cap"] is True
        assert st["badge"]["text"] == ("Extract only — this format has no "
                                       "Write/Replace support.")
        assert w.state("shell")["mfr"]["era"] == "whitestar"


def test_dp_deltas_follow_the_input(tmp_path):
    zip_ = tmp_path / "tbl-1.10.zip"
    zip_.write_bytes(b"PK")
    d1 = tmp_path / "tbl-1.15.zip"
    d1.write_bytes(b"PK")
    with web_app(tmp_path, mfr="dp") as w:
        svc = _svc(w)
        w.call("ui.set", "extract", "input", str(zip_))
        _settle(w)
        st = w.state("extract")
        assert st["deltas_show"] is True and st["decode_show"] is True
        w.answers.append([str(d1)])
        assert w.call("extract.add_deltas") == 1
        assert svc.extract_delta_paths == [os.path.normpath(str(d1))]
        assert w.window.extract_delta_paths == svc.extract_delta_paths
        assert w.state("extract")["deltas_summary"] == \
            "1 update(s): tbl-1.15.zip"
        # an AAIW disk image: no deltas, and the list is dropped
        img = tmp_path / "aaiw.img"
        img.write_bytes(b"\0")
        w.call("ui.set", "extract", "input", str(img))
        _settle(w)
        assert w.state("extract")["deltas_show"] is False
        assert svc.extract_delta_paths == []
        assert w.state("extract")["deltas_summary"] == "No updates added"


# ------------------------------------------------------------------ paths
def test_browse_input_normalises(tmp_path):
    f = tmp_path / "a" / "game.pkg"
    f.parent.mkdir()
    f.write_bytes(b"x")
    with web_app(tmp_path, mfr="spooky") as w:
        w.answers.append(str(f).replace("\\", "/"))
        assert w.call("extract.browse_input") is True
        assert w.window.extract_input_var.get() == os.path.normpath(str(f))
        spec = w.asked[-1]
        assert spec["title"] == "Select input file"
        assert spec["filetypes"][-1] == ["All files", "*.*"]
        _settle(w)


def test_browse_output_offers_the_parent(tmp_path):
    proj = tmp_path / "proj"
    sub = proj / "sound"
    sub.mkdir(parents=True)
    (proj / ".checksums.md5").write_text("x", encoding="utf-8")
    with web_app(tmp_path, mfr="spooky") as w:
        w.answers.extend([str(sub), "yes"])
        assert w.call("extract.browse_output") is True
        assert "Use parent folder?" in _titles(w)
        assert w.window.extract_output_var.get() == str(proj)
        assert w.window.write_assets_var.get() == str(proj)
        _settle(w)
        p = w.state("extract")["project"]
        assert p["exists"] is True and p["details"]["baseline"] is True


def test_drop_paths(tmp_path):
    f = tmp_path / "game.pkg"
    f.write_bytes(b"x")
    folder = tmp_path / "out"
    folder.mkdir()
    with web_app(tmp_path, mfr="spooky") as w:
        assert w.call("extract.drop_paths", [str(f)]) is True
        assert w.window.extract_input_var.get() == str(f)
        assert w.call("extract.drop_paths", [str(folder)]) is True
        assert w.window.extract_output_var.get() == str(folder)
        assert w.call("extract.drop_paths", [str(tmp_path / "nope")]) \
            is False
        assert w.call("extract.use_recent", "input", str(f)) is True
        assert w.call("extract.unmap", "output", str(folder)) is True
        _settle(w)


# ------------------------------------------------------------- card mode
class _Drive:
    def __init__(self, display, device, size=8 * 10 ** 9, letters=""):
        self.display = display
        self.device_path = device
        self.model = "Card Reader"
        self.size_bytes = size
        self.mount_label = letters
        self.bus_type = "USB"


def _fake_drives(monkeypatch, drives):
    from pinball_decryptor.core import drives as drives_mod
    monkeypatch.setattr(drives_mod, "list_physical_drives", lambda: drives)
    monkeypatch.setattr(drives_mod, "pick_best_game_ssd",
                        lambda ds, prefer="ssd": (ds[0], "high", "why")
                        if ds else (None, None, None))
    monkeypatch.setattr(drives_mod, "visible_drives",
                        lambda ds, prefer="ssd", keep=(): list(ds))


def test_card_mode_drives_and_identity(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import extract as mod
    drive = _Drive("Reader (8.0 GB, External) — \\\\.\\PHYSICALDRIVE9",
                   "\\\\.\\PHYSICALDRIVE9")
    _fake_drives(monkeypatch, [drive])
    monkeypatch.setattr(mod, "_is_admin", lambda: True)
    with web_app(tmp_path, mfr="stern") as w:
        stern = w.window.current_mfr
        monkeypatch.setattr(stern, "identify_card",
                            lambda p: "Godzilla Pro" if p.endswith("9")
                            else "")
        w.call("extract.set_source", "ssd")
        _settle(w)
        st = w.state("extract")
        assert st["ssd"] is True and st["drives_state"] == "ok"
        assert w.window.extract_drive_var.get() == drive.device_path
        assert st["card_line"] == "Card: Godzilla Pro"
        assert st["admin_panel"] is False
        assert tuple(w.window._phases["extract"]) == \
            tuple(stern.direct_ssd_extract_phases)
        w.call("ui.set", "extract", "output", str(tmp_path / "p"))
        assert w.state("extract")["block_reason"] == ""
        # back to the file row
        w.call("extract.set_source", "iso")
        assert w.state("extract")["ssd"] is False
        assert tuple(w.window._phases["extract"]) == \
            tuple(stern.extract_phases)


def test_card_mode_without_admin_on_windows(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import extract as mod
    _fake_drives(monkeypatch, [])
    monkeypatch.setattr(mod, "_is_admin", lambda: False)
    monkeypatch.setattr(mod, "sys", types.SimpleNamespace(platform="win32"))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("extract.set_source", "ssd")
        _settle(w)
        st = w.state("extract")
        assert st["admin_panel"] is True
        assert st["drives_state"] == "none"
        assert st["block_reason"] == (
            "Administrator privileges are required to read the SD card "
            "directly — see the warning above.")
        collapsed = st["admin_collapsed"]
        assert w.call("extract.toggle_admin_warning") is (not collapsed)
        assert w.app._settings["admin_warning_collapsed"] is (not collapsed)


def test_fda_panel_on_macos(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import extract as mod
    _fake_drives(monkeypatch, [])
    monkeypatch.setattr(mod, "sys", types.SimpleNamespace(platform="darwin"))
    with web_app(tmp_path, mfr="stern") as w:
        w.call("extract.set_source", "ssd")
        _settle(w)
        assert w.state("extract")["fda_panel"] is True
        assert w.state("extract")["admin_panel"] is False
        w.call("extract.dismiss_fda")
        assert w.state("extract")["fda_panel"] is False
        assert w.app._settings["macos_fda_acknowledged"] is True
        assert w.window._fda_acknowledged is True
        w.run(w.window.acknowledge_macos_fda)          # idempotent


def test_read_card_dialog(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import extract as mod
    drive = _Drive("Reader (8.0 GB) — \\\\.\\PHYSICALDRIVE9",
                   "\\\\.\\PHYSICALDRIVE9")
    _fake_drives(monkeypatch, [drive])
    monkeypatch.setattr(mod, "_is_admin", lambda: True)
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        reads = []
        w.window.cb["on_read_card"] = lambda dev, img: reads.append(
            (dev, img))
        w.call("ui.set", "extract", "output", str(proj))
        assert w.call("extract.open_read_card") is True
        _settle(w)
        rc = w.state("extract")["rc"]
        assert rc["open"] and rc["drive"] == drive.display
        image = w.window.service("extract")._rc_image_var.get()
        assert image == os.path.join(str(proj), "Card-Reader-8GB.raw")
        assert rc["readout"]                      # size vs free space
        w.call("ui.set", "extract", "rc_image", "")
        assert w.call("extract.rc_start") is False
        assert "No image file" in _titles(w)
        w.call("ui.set", "extract", "rc_image",
               str(tmp_path / "missing" / "x.raw"))
        assert w.call("extract.rc_start") is False
        assert "Folder not found" in _titles(w)
        target = proj / "card.raw"
        target.write_bytes(b"old")
        w.call("ui.set", "extract", "rc_image", str(target))
        w.answers.append("no")
        assert w.call("extract.rc_start") is False
        assert "Replace file?" in _titles(w)
        w.answers.append("yes")
        assert w.call("extract.rc_start") is True
        assert reads == [(drive.device_path, str(target))]
        assert w.state("extract")["rc"] is None


def test_read_card_refused_while_running(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.window.set_running, True, "write")
        try:
            assert w.call("extract.open_read_card") is False
            assert "Busy" in _titles(w)
        finally:
            w.run(w.window.set_running, False, "write")


def test_read_card_same_drive_is_refused():
    from pinball_decryptor.webui import extract_helpers as H
    d = _Drive("x", "\\\\.\\PHYSICALDRIVE9", letters="E: F:")
    assert H.destination_is_on(d, "E:\\backups", platform="win32") is True
    assert H.destination_is_on(d, "D:\\backups", platform="win32") is False
    assert H.destination_is_on(d, "E:\\backups", platform="linux") is False
    assert H.fmt_size(7_950_000_000) == "7.95 GB"
    assert H.default_image_name(d, "SD card") == "Card-Reader-8GB.raw"


def test_input_source_change_for_write_is_forwarded(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        seen = []
        wsvc = w.window.service("write")
        if wsvc is not None and hasattr(type(wsvc), "_on_input_source_change"):
            orig = wsvc._on_input_source_change

            import inspect
            if inspect.signature(orig).parameters:
                def spy(mode):
                    seen.append(mode)
                    return orig(mode)
            else:
                def spy():
                    seen.append("write")
                    return orig()
            wsvc._on_input_source_change = spy
            w.run(w.window._on_input_source_change, "write")
            assert len(seen) == 1
        else:
            w.run(w.window._on_input_source_change, "write")   # no error
        w.run(w.window._on_input_source_change, "extract")
        _settle(w)


# ------------------------------------------------------- info windows
def test_image_info(tmp_path):
    f = tmp_path / "game.pkg"
    f.write_bytes(b"\0" * 1024)
    with web_app(tmp_path, mfr="spooky") as w:
        assert w.call("extract.open_image_info") is False
        assert "No image selected" in _titles(w)
        w.call("ui.set", "extract", "input", str(tmp_path / "gone.pkg"))
        assert w.call("extract.open_image_info") is False
        assert "File not found" in _titles(w)
        w.call("ui.set", "extract", "input", str(f))
        assert w.call("extract.open_image_info") is True
        _settle(w)
        info = w.state("extract")["info"]
        assert info["open"] and not info["loading"]
        assert info["sections"][0]["title"] == "File"
        text = w.call("extract.info_copy")
        assert text.startswith("Image Info")
        assert w.state("extract")["info"]["status"] == \
            "Report copied to clipboard."
        w.call("extract.info_close")
        assert w.state("extract")["info"] is None


def test_project_info_and_recents(tmp_path):
    proj = tmp_path / "proj"
    (proj / "sound").mkdir(parents=True)
    (proj / "sound" / "a.wav").write_bytes(b"\0" * 10)
    (proj / "video.mp4").write_bytes(b"\0" * 20)
    settings = {"projects": [{"folder": str(proj),
                                    "manufacturer": "spooky",
                                    "last_opened": "2026-09-20T10:00:00"}]}
    with web_app(tmp_path, mfr="spooky", settings=settings) as w:
        assert w.call("extract.open_project_info") is False
        assert "No project folder" in _titles(w)
        w.call("ui.set", "extract", "output", str(proj))
        assert w.call("extract.open_project_info") is True
        _settle(w)
        p = w.state("extract")["project"]
        rows = dict(p["rows"])
        assert rows["Audio"].startswith("1 file(s)")
        assert rows["Video"].startswith("1 file(s)")
        assert rows["Changed"] == "nothing changed yet"
        assert w.state("extract")["pinfo"] is True
        w.call("extract.close_project_info")
        assert w.state("extract")["pinfo"] is False
        w.run(w.window.service("extract")._refresh_recents)
        recents = w.state("extract")["recents"]
        assert recents[0]["folder"] == str(proj)
        assert recents[0]["current"] is True
        assert recents[0]["date"] == "2026-09-20"
        assert recents[0]["mfr"] == w.window.current_mfr.display


def _anchored_project(tmp_path, name, image, mfr_key="stern"):
    from pinball_decryptor.core import extract_source, project_file
    proj = tmp_path / name
    proj.mkdir()
    extract_source.write_extract_source(str(proj), str(image))
    if mfr_key:
        project_file.save(project_file.anchor_path(str(proj)),
                          manufacturer_key=mfr_key, paths={},
                          extract_options={}, stock_image=str(image))
    return proj


def test_project_game_is_the_projects_not_the_inputs(tmp_path, monkeypatch):
    """"This project"'s Game row names the image the project was extracted
    from, detected by the project's own manufacturer - never whatever the
    input box holds (it read Ghostbusters under a Godzilla project)."""
    img = tmp_path / "godzilla_le-1_16_0.raw"
    img.write_bytes(b"\0" * 32)
    other = tmp_path / "ghostbusters_le-1_17.iso"
    other.write_bytes(b"\0" * 16)
    proj = _anchored_project(tmp_path, "gz_copy", img)
    with web_app(tmp_path, mfr="jjp") as w:
        stern = _mfr(w, "stern")
        games = {str(img): types.SimpleNamespace(display="Godzilla (Spike 2)",
                                                 era="spike2"),
                 str(other): types.SimpleNamespace(
                     display="Ghostbusters (Spike 1)", era="spike1")}
        for m in w.window.manufacturers:
            monkeypatch.setattr(m, "detect", lambda p: None)
        monkeypatch.setattr(stern, "detect", lambda p: games.get(p))
        monkeypatch.setattr(stern, "title_caption", lambda p, g: "%s from %s"
                            % (g.display, os.path.basename(p)))
        w.call("ui.set", "extract", "input", str(other))
        w.call("ui.set", "extract", "output", str(proj))
        _settle(w)
        d = w.state("extract")["project"]["details"]
        # the anchor's manufacturer (Stern) named it, though JJP is current
        assert d["game"] == "Godzilla (Spike 2) from godzilla_le-1_16_0.raw"
        assert d["source_name"] == img.name
        # the input's own detection is still the input's (the badge)
        assert "Ghostbusters" in w.state("extract")["badge"]["text"]
        # the project's image gone: no Game row, and no fall-back to the
        # input's game
        img.unlink()
        w.call("extract.refresh_project")
        _settle(w)
        assert w.state("extract")["project"]["details"]["game"] == ""


def test_project_game_without_an_anchor_uses_the_current_plugin(
        tmp_path, monkeypatch):
    img = tmp_path / "game.pkg"
    img.write_bytes(b"\0" * 8)
    proj = _anchored_project(tmp_path, "plain", img, mfr_key="")
    with web_app(tmp_path, mfr="spooky") as w:
        spooky = w.window.current_mfr
        monkeypatch.setattr(spooky, "detect", lambda p: (
            types.SimpleNamespace(display="Rob Zombie", era="")
            if p == str(img) else None))
        monkeypatch.setattr(spooky, "title_caption", lambda p, g: g.display)
        w.call("ui.set", "extract", "output", str(proj))
        _settle(w)
        assert w.state("extract")["project"]["details"]["game"] == \
            "Rob Zombie"


def test_project_game_skips_a_card_read_in_place(tmp_path):
    from pinball_decryptor.webui import extract_helpers as H

    class Boom:
        key = "stern"

        def detect(self, path):
            raise AssertionError("a device must never be probed: " + path)

    dev = ("\\\\.\\PHYSICALDRIVE7" if os.name == "nt" else "/dev/sdz")
    assert H.project_game(Boom(), [dev]) == ""
    assert H.project_game(None, [str(tmp_path)]) == ""


def test_recent_current_follows_the_project_folder(tmp_path):
    """The highlighted recent project (and the menu's check mark) follows
    the Project folder box as it is typed, browsed or cleared."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    settings = {"projects": [
        {"folder": str(a), "manufacturer": "spooky",
         "last_opened": "2026-09-20T10:00:00"},
        {"folder": str(b), "manufacturer": "spooky",
         "last_opened": "2026-09-19T10:00:00"}]}
    with web_app(tmp_path, mfr="spooky", settings=settings) as w:
        def current():
            return {r["folder"]: r["current"]
                    for r in w.state("extract")["recents"]}
        w.call("ui.set", "extract", "output", str(a))
        assert current() == {str(a): True, str(b): False}
        w.call("ui.set", "extract", "output", str(b))
        assert current() == {str(a): False, str(b): True}
        w.call("ui.set", "extract", "output", "")
        assert current() == {str(a): False, str(b): False}
        _settle(w)


def test_a_failing_trace_on_a_mirrored_var_is_not_the_tabs(tmp_path):
    """The Project folder mirrors into the shared assets folder; a broken
    trace on that var is compat's to log (as Tk did), the box still works."""
    with web_app(tmp_path, mfr="spooky") as w:
        wvar = w.window.write_assets_var

        def boom(*_a):
            raise RuntimeError("a broken trace")

        w.run(wvar.trace_add, "write", boom)
        w.call("ui.set", "extract", "output", str(tmp_path))
        assert wvar.get() == str(tmp_path)
        assert w.state("extract")["block_reason"].startswith("Pick ")
        _settle(w)


# --------------------------------------------------------- the page (JS)
_EXTRACT_JS = (Path(__file__).resolve().parents[1] / "pinball_decryptor"
               / "webui" / "static" / "js" / "tabs" / "extract.js")

_JS_CASES = r"""
import { projectGame } from "./tabs/extract.js";
const flat = (v) => v == null || v === false ? ""
  : (typeof v === "string" || typeof v === "number") ? String(v)
  : Array.isArray(v) ? v.map(flat).join("")
  : v.strings ? v.strings.map((s, i) => s + (i < v.values.length ? flat(v.values[i]) : "")).join("")
  : "";
const out = {};
out.gameNone = projectGame({ project: { details: {} }, detected: { caption: "Ghostbusters v1.17 LE" } });
out.gameNoProject = projectGame({ detected: { caption: "Ghostbusters v1.17 LE" } });
out.game = projectGame({ project: { details: { game: "Godzilla v1.16.0 LE" } }, detected: { caption: "Ghostbusters v1.17 LE" } });
console.log(JSON.stringify(out));
"""


def _node():
    import shutil
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="needs Node.js")
def test_page_project_game(tmp_path):
    """The project card's game is the project's, not the detected card's.
    (The page's Recent projects menu is gone: the top bar's project menu
    lists them.)"""
    import json
    import subprocess
    src = _EXTRACT_JS.read_text(encoding="utf-8")
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "tabs" / "extract.js").write_text(src, encoding="utf-8")
    for mod, frm in (("ui", "../core/ui.js"), ("store", "../core/store.js")):
        m = re.search(r"import \{([^}]*)\} from \"%s\"" % re.escape(frm), src)
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        body = "".join("export const %s = () => null;\n" % n
                       for n in names if n != "html")
        if "html" in names:
            body += ("export const html = (strings, ...values) => "
                     "({ strings: [...strings], values });\n")
        (tmp_path / "core" / (mod + ".js")).write_text(body, encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}',
                                           encoding="utf-8")
    (tmp_path / "cases.js").write_text(_JS_CASES, encoding="utf-8")
    run = subprocess.run([_node(), str(tmp_path / "cases.js")],
                         capture_output=True, text=True, timeout=60,
                         cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["gameNone"] == "" and got["gameNoProject"] == ""
    assert got["game"] == "Godzilla v1.16.0 LE"


def test_page_info_windows_are_not_modal():
    """Image Info and Project Info were Tk Toplevels without a grab: the
    page keeps working under them (no scrim), and the i badges use the
    shared InfoBadge."""
    src = _EXTRACT_JS.read_text(encoding="utf-8")

    def body(name):
        start = src.index("function %s(" % name)
        nxt = src.find("\nfunction ", start + 1)
        return src[start:nxt if nxt > 0 else len(src)]

    for name in ("ImageInfo", "ProjectInfo"):
        assert "Modal" not in body(name), name
        assert "FloatWin" in body(name), name
    win = body("FloatWin")
    assert 'aria-modal="false"' in win and "scrim" not in win
    assert "badge-i" not in src and "IBadge" not in src
    assert src.count("InfoBadge") >= 4          # import + three badges


# ----------------------------------------------------- capture extras
def test_dmd_frames_and_switch_matrix(tmp_path):
    with web_app(tmp_path, mfr="williams") as w:
        svc = _svc(w)
        w.run(svc.reset_dmd_preview)
        assert w.state("extract")["dmd"] is None
        frame = bytes([0, 1, 2, 3] * 32 * 32)
        svc.on_dmd_frame(frame, 128, 32, 2)          # from a capture thread
        w.run(svc._dmd_tick, False)
        dmd = w.state("extract")["dmd"]
        assert dmd["src"].startswith("data:image/png;base64,")
        assert (dmd["w"], dmd["h"]) == (128, 32)
        pressed = []
        script = types.SimpleNamespace(
            title="Attack from Mars",
            profile={"raw": {"swLeft Ramp": 41, "swStart": 13}})
        svc.on_capture_ready(lambda sw, ms: pressed.append((sw, ms)), script)
        w.drain()
        m = w.state("extract")["matrix"]
        assert m["title"].startswith("Switch matrix — Attack from Mars (2 "
                                     "named + ")
        assert [b["sw"] for b in m["named"]] == [13, 41]
        assert m["named"][1]["tip"] == "sw#41 — Left Ramp"
        assert 11 in [b["sw"] for b in m["unknown"]]
        assert w.call("extract.press_switch", 41, "Left Ramp") is True
        assert pressed == [(41, 120)]
        # switching to a plugin without capture drops them
        w.call("ui.pick_manufacturer", "spooky")
        st = w.state("extract")
        assert st["dmd"] is None and st["matrix"] is None
        _settle(w)


def test_running_state_blocks_start(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        w.run(w.window.set_running, True, "write")
        try:
            assert w.call("extract.start") is False
        finally:
            w.run(w.window.set_running, False, "write")
