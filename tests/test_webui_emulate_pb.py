"""The web Emulate PB tab (webui/tabs/emulate_pb.py, PAD-271), without ever
touching a rig: the harness sets PAD_UI_NO_RIG, conftest points the rig dir
at an empty directory, and the tests that need more stub it."""

import os
import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_pb"


def _svc(w):
    return w.window.service(NS)


@pytest.fixture(autouse=True)
def _no_theme_probe(monkeypatch):
    """macOS asks for the theme through subprocess, which tests here spy on."""
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_pb_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)


# ------------------------------------------------------------------ gating
def test_pb_shows_the_tab_and_says_what_it_runs(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] and tabs[NS]["label"] == "Emulate"
        assert tabs[NS]["group"] == "Play"
        for other in ("emulate", "emulate_jjp", "emulate_spike1", "emulate_ap",
                      "emulate_bof", "emulate_dp", "emulate_spooky"):
            assert not tabs[other]["visible"]
        s = w.state(NS)
        assert s["supported"] == ["Predator", "Alien", "ABBA", "Queen"]
        assert "Supported: Predator, Alien, ABBA, Queen" in s["intro"]
        # Queen runs now (PAD-326): nothing is "not yet"
        assert s["pending"] == [] and not s["pending_note"]
        assert s["go_label"] == "Start" and s["go_enabled"]
        assert [c["label"] for c in s["cells"]] == [
            "Game", "Version", "Balls", "Switches", "Window", "Memory", "Uptime"]


@pytest.mark.parametrize("mfr", ["stern", "spooky", "ap", "bof"])
def test_other_manufacturers_do_not_get_the_pb_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert "tools/pb_emu" in s["note"]


def test_the_shipped_rig_is_complete(monkeypatch):
    """rig_available() checks the scripts the tab runs; the repo has them."""
    from pinball_decryptor.webui import emulate_pb_core as core
    monkeypatch.delenv("PAD_PB_EMU_DIR", raising=False)
    assert core.rig_available()


def test_browse_asks_for_a_predator_update(tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        f = tmp_path / "pbpp_predator_game_1_0_1.upd"
        f.write_bytes(b"")
        w.answers.append(str(f))
        assert w.call(NS + ".browse")
        assert ["Predator update", "pbpp_predator_game_*.upd"] in w.asked[-1]["filetypes"]
        assert w.window.pb_emulate_file_var.get() == str(f)


def test_an_empty_field_uses_a_game_file_picked_on_select_card(tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        w.window.extract_input_var.set(
            r"D:\Pinball\images\Pinball Brothers\pbpp_predator_game_1_0_1.upd")
        assert svc.file_path().endswith("pbpp_predator_game_1_0_1.upd")
        # Alien's update and its restore image run too (PAD-315)
        w.window.extract_input_var.set(r"D:\Pinball\images\Pinball Brothers\pbap412.upd")
        assert svc.file_path().endswith("pbap412.upd")
        w.window.extract_input_var.set(
            r"D:\Pinball\images\Pinball Brothers\clonezilla-live-alien40.iso")
        assert svc.file_path().endswith("clonezilla-live-alien40.iso")
        # Queen's runs too (PAD-326); another maker's image does not
        w.window.extract_input_var.set(r"D:\Pinball\images\Pinball Brothers\pbq0210G.upd")
        assert svc.file_path().endswith("pbq0210G.upd")
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\clonezilla-live-tcm.iso")
        assert svc.file_path() == ""
        # its own field wins
        w.window.pb_emulate_file_var.set(r"C:\mods\pbpp_predator_game_1_0.upd")
        assert svc.file_path() == r"C:\mods\pbpp_predator_game_1_0.upd"


def test_showing_the_tab_puts_up_its_ladder(tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Unpack", "Board", "Game", "Ready"]
        assert f["mode"] == "emulate"


def test_start_without_a_file_asks_and_runs_nothing(rig, monkeypatch, tmp_path):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    with web_app(tmp_path, mfr="pb") as w:
        w.call(NS + ".toggle")
        assert ran == [] and not _svc(w)._busy


def test_start_runs_queen_on_the_io_board_rig(rig, monkeypatch, tmp_path):
    """PAD-326: Queen was refused ("can't be emulated yet") until its restore
    image was in hand; now its file starts the I/O-board rig, with the note
    that its flippers launch."""
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui import emulate_pb_core as core
    seen, said = [], []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: seen.append((a, k)) or ["true"])
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        monkeypatch.setattr(compat.messagebox, "showinfo",
                            lambda title, text, **k: said.append(text))
        f = tmp_path / "pbq0210G.upd"
        f.write_bytes(b"x")
        w.window.pb_emulate_file_var.set(str(f))
        monkeypatch.setattr(svc, "_refuse_off", lambda: False)
        monkeypatch.setattr(svc, "_run_streaming", lambda *a, **k: 1)
        svc._start_async()
        end = time.time() + 5
        while not seen and time.time() < end:
            time.sleep(0.02)
        assert not said
        args, kw = seen[0]
        assert args[0] == "watch.sh" and kw.get("kind") == "pbio"
        assert "PAD_TITLE=Queen" in kw["env"]
        assert "flippers launch" in core.TITLE_NOTES["Queen"]


# ------------------------------------------------------------ the poll
RUNNING = {"wsl": "1", "ready": "1", "running": "1", "title": "predator",
           "title_name": "Predator", "build": "predator_1_0_1-028700ac",
           "version": "1.0.1", "pid": "42", "rss_kb": str(1048576),
           "uptime_s": "95", "display": ":0", "visible": "1",
           "window": "1920x1080", "switches": "95", "slot": "0",
           "attract": "1", "balls": "5/1/0", "leds_lit": "155",
           "switches_json": "/var/tmp/pad_pb/rig0/switches.json"}


def test_apply_running_fills_the_grid(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        _svc(w)._apply(dict(RUNNING))
        s = w.state(NS)
        assert s["up"] and s["ready"] and s["go_label"] == "Stop"
        assert s["state_label"] == "Running" and s["tone"] == "ok"
        assert s["game"] == "Predator"
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Game"] == "Predator" and v["Version"] == "1.0.1"
        assert v["Balls"] == "trough 5 · lane 1 · in play 0"
        assert v["Switches"] == "95" and v["Window"] == "1920 × 1080"
        assert v["Memory"] == "1.0 GB" and v["Uptime"] == "1:35"
        # pinprog itself is tens of MB
        _svc(w)._apply(dict(RUNNING, rss_kb="28244"))
        v = {c["label"]: c["value"] for c in w.state(NS)["cells"]}
        assert v["Memory"] == "28 MB"
        assert "28 MB" in w.state(NS)["state_hint"]


def test_loading_is_not_yet_running(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        _svc(w)._apply(dict(RUNNING, attract="0"))
        s = w.state(NS)
        assert s["state_label"] == "Starting" and not s["ready"]


def test_no_libraries_yet_puts_up_the_setup_notice(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        _svc(w)._apply({"wsl": "1", "ready": "0", "running": "0", "_rt": "ready"})
        s = w.state(NS)
        assert s["setup_btn"] and "700 MB" in s["setup_msg"]
        assert s["setup_label"] == "Set up emulator…"
        _svc(w)._apply({"wsl": "1", "ready": "1", "running": "0", "_rt": "ready"})
        assert w.state(NS)["setup_msg"] == ""


def test_launch_lines_move_the_footer(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        seen = []
        svc._footer = lambda kind, pct=None, text="": seen.append((kind, pct))
        for line in ("== Setup ==", "== Unpack ==", "progress 40", "== Board ==",
                     "== Game ==", "== Ready =="):
            svc._footer_line(line)
        assert seen == [("copy", 0), ("copy", 0), ("copy", 40), ("boot", None),
                        ("techalerts", None), ("run", None)]


def test_the_switch_window_command(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_pb_core as core
    from pinball_decryptor.webui.tabs import emulate_pb as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="pb") as w:
        cmd = _svc(w)._switch_window_cmd(dict(RUNNING))
        assert cmd[0] == "pythonw.exe" and cmd[1].endswith("pbpf.py")
        assert cmd[cmd.index("--slot") + 1] == "0"
        assert cmd[cmd.index("--distro") + 1] == "PAD-Runtime"
        assert "--parent-pipe" in cmd                  # Stop closes it
        assert cmd[cmd.index("--table") + 1] == (
            r"\\wsl.localhost\PAD-Runtime\var\tmp\pad_pb\rig0\switches.json")
        assert cmd[cmd.index("--audio-ctl") + 1].endswith("audio_ctl.json")
        # no table yet (the game is still loading): no window
        assert _svc(w)._switch_window_cmd({"running": "1"}) is None


def test_quit_stops_only_a_run_this_app_started(rig, monkeypatch, tmp_path):
    import subprocess
    ran = []
    from pinball_decryptor.webui import emulate_pb_core as core
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(
        "pinball_decryptor.webui.tabs.emulate_pb.rig_off", lambda: False)
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        svc._last_up = True
        svc._started_here = False
        svc.emulate_shutdown()
        assert ran == []
        svc._started_here = True
        svc.emulate_shutdown()
        assert len(ran) == 1 and "stop.sh" in " ".join(ran[0][0])


def test_while_starting_the_button_is_cancel(rig, monkeypatch, tmp_path):
    import subprocess
    from pinball_decryptor.webui import emulate_pb_core as core
    ran = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"cancelled=1", b""))
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        svc._busy = True
        svc._starting = True
        svc._set_go("Cancel", True)
        assert w.state(NS)["go_label"] == "Cancel"
        assert w.call(NS + ".toggle")
        end = time.time() + 5
        while not ran and time.time() < end:
            time.sleep(0.02)
        assert ran and ran[0][-1] == "cancel.sh"


def test_supported_file_is_by_name():
    from pinball_decryptor.webui import emulate_pb_core as core
    assert core.supported_file(r"D:\x\pbpp_predator_game_1_0_1.upd")
    assert core.supported_file("/mnt/d/PBPP_PREDATOR_GAME_1_0.UPD")
    assert not core.supported_file("pbpp_predator_game_1_0.iso")
    assert not core.supported_file("")
    assert core.title_of("pbpp_predator_game_1_0.upd") == "Predator"
    assert core.kind_of("pbpp_predator_game_1_0.upd") == "pb"
    # PAD-315: Alien and ABBA share "pbap"; the major version tells them apart
    for name, title in (("pbap412.upd", "Alien"), ("pbap41.upd", "Alien"),
                        (r"D:\x\clonezilla-live-alien40.iso", "Alien"),
                        ("PBAP145.UPD", "ABBA"), ("pbap141.upd", "ABBA")):
        assert core.supported_file(name), name
        assert core.title_of(name) == title, name
        assert core.kind_of(name) == "pbio", name
    for name in ("pbq0210G.upd", "clonezilla-live-queen20d.iso"):
        assert core.supported_file(name) and core.title_of(name) == "Queen"
        assert core.kind_of(name) == "pbio"
    # another maker's restore image is not a PB game
    assert not core.supported_file("clonezilla-live-tcm_prod.iso")
    assert core.version_of("pbpp_predator_game_1_0_1.upd") == "1.0.1"


def test_start_passes_sound_the_volume_control_and_the_title(rig, monkeypatch, tmp_path):
    """As the AP tab: sound always on, the level from the shared control file."""
    from pinball_decryptor.webui import emulate_pb_core as core
    seen = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: seen.append((a, k)) or ["true"])
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        f = tmp_path / "pbpp_predator_game_1_0_1.upd"
        f.write_bytes(b"x")
        w.window.pb_emulate_file_var.set(str(f))
        monkeypatch.setattr(svc, "_refuse_off", lambda: False)
        monkeypatch.setattr(svc, "_run_streaming", lambda *a, **k: 1)
        svc._start_async()
        end = time.time() + 5
        while not seen and time.time() < end:
            time.sleep(0.02)
        args, kw = seen[0]
        assert args[0] == "watch.sh"
        env = kw["env"]
        assert "PAD_AUDIO=1" in env and "PAD_VISIBLE=1" in env
        assert "PAD_TITLE=Predator" in env
        assert any(e.startswith("PAD_AUDIO_CTL=") and e.endswith("audio_ctl.json")
                   for e in env)


def test_the_cache_window_lists_builds_and_the_setup(rig, tmp_path):
    from pinball_decryptor.webui import emulate_pb_core as core
    entries, disk = core.parse_cache(
        "entry=predator_1_0_1-028700ac kind=build kb=5242880 used=1759200000 "
        "src=pbpp_predator_game_1_0.upd+pbpp_predator_game_1_0_1.upd\n"
        "entry=setup kind=setup kb=716800 used=1759100000 src=\n"
        "disk=31457280 102400000\n")
    assert disk == (31457280, 102400000)
    assert core.cache_label(entries[0]) == "Predator 1.0.1"
    assert core.cache_label(entries[1]).startswith("Emulator setup")
    assert core.cache_label({"name": "os-clonezilla-live-alien40", "kind": "os",
                             "src": "clonezilla-live-alien40.iso"}) == (
        "Alien machine image (clonezilla-live-alien40.iso)")
    assert core.cache_label({"name": "upd-pbap145", "kind": "update",
                             "src": "pbap145.upd"}) == "ABBA update (pbap145.upd)"
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        svc._cache_open = True
        svc.set(cache={"head": "", "rows": [], "sel": [], "busy": True, "hint": ""})
        svc._cache_show((entries, disk))
        c = w.state(NS)["cache"]
        assert [r["label"] for r in c["rows"]] == [
            "Predator 1.0.1", "Emulator setup (Predator's libraries)"]
        assert c["rows"][0]["src"] == (
            "pbpp_predator_game_1_0.upd + pbpp_predator_game_1_0_1.upd")
        assert c["head"].startswith("2 items")


def test_the_page_and_its_style_ship():
    here = os.path.dirname(os.path.abspath(__file__))
    static = os.path.join(here, "..", "pinball_decryptor", "webui", "static")
    assert os.path.isfile(os.path.join(static, "js", "tabs", "emulate_pb.js"))
    assert os.path.isfile(os.path.join(static, "css", "tabs", "emulate_pb.css"))


# ------------------------------------------------- Alien and ABBA (PAD-315)
PBIO_RUNNING = {"wsl": "1", "running": "1", "title": "abba", "title_name": "ABBA",
                "build": "build-pbap141+pbap145", "version": "1.45", "pid": "77",
                "rss_kb": "30000", "uptime_s": "20", "display": ":0",
                "visible": "1", "window": "1920x1080", "switches": "75",
                "slot": "0", "attract": "1", "balls": "6/0/0", "leds_lit": "12",
                "switches_json": "/var/tmp/pad_pbio/rig0/switches.json",
                "_kind": "pbio"}


def test_an_alien_file_starts_the_io_board_rig_with_sound(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_pb_core as core
    seen = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: seen.append((a, k)) or ["true"])
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        f = tmp_path / "pbap412.upd"
        f.write_bytes(b"x")
        w.window.pb_emulate_file_var.set(str(f))
        monkeypatch.setattr(svc, "_refuse_off", lambda: False)
        monkeypatch.setattr(svc, "_run_streaming", lambda *a, **k: 5)
        svc._start_async()
        end = time.time() + 5
        while not seen and time.time() < end:
            time.sleep(0.02)
        args, kw = seen[0]
        assert args[0] == "watch.sh" and kw["kind"] == "pbio"
        assert "PAD_TITLE=Alien" in kw["env"] and "PAD_VISIBLE=1" in kw["env"]
        # sound on, at the shared Volume / Mute (pbioaudio.py, PAD-322)
        assert "PAD_AUDIO=1" in kw["env"]
        assert any(e.startswith("PAD_AUDIO_CTL=") and e.endswith("audio_ctl.json")
                   for e in kw["env"])
        # Stop and Cancel go to the same rig
        assert svc._kind == "pbio"
    # the failure names what an Alien delta needs, not Predator's files
    assert "pbap411.upd" in core.exit_text("pbio", 5)
    assert "pbpp_predator" in core.exit_text("pb", 5)


def test_the_poll_follows_the_picked_file_until_a_game_runs(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        assert svc._poll_kind() == "pb"
        w.window.pb_emulate_file_var.set(r"D:\x\pbap145.upd")
        assert svc._poll_kind() == "pbio"
        svc._apply(dict(PBIO_RUNNING))
        # a running ABBA keeps the tab on its rig whatever is picked now
        w.window.pb_emulate_file_var.set(r"D:\x\pbpp_predator_game_1_0.upd")
        assert svc._poll_kind() == "pbio"
        svc._apply({"wsl": "1", "running": "0", "_kind": "pbio"})
        assert svc._poll_kind() == "pb"


def test_a_running_abba_says_its_screens_are_dark(rig, tmp_path):
    with web_app(tmp_path, mfr="pb") as w:
        _svc(w)._apply(dict(PBIO_RUNNING))
        s = w.state(NS)
        assert s["game"] == "ABBA" and s["state_label"] == "Running"
        assert "screens stay dark" in s["title_note"]
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Balls"] == "trough 6 · lane 0 · in play 0"
        # no libraries to set up for this rig
        assert s["setup_msg"] == ""
        _svc(w)._apply(dict(RUNNING))
        assert w.state(NS)["title_note"] == ""


def test_the_switch_window_drives_the_io_board(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_pb_core as core
    from pinball_decryptor.webui.tabs import emulate_pb as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="pb") as w:
        cmd = _svc(w)._switch_window_cmd(dict(PBIO_RUNNING))
        assert cmd[1].endswith("pbpf.py")
        assert cmd[cmd.index("--rig") + 1] == "pbio"
        assert cmd[cmd.index("--table") + 1] == (
            r"\\wsl.localhost\PAD-Runtime\var\tmp\pad_pbio\rig0\switches.json")
        assert "--rig" not in _svc(w)._switch_window_cmd(dict(RUNNING, _kind="pb"))


def test_the_cache_window_shows_both_rigs_and_deletes_on_each(rig, monkeypatch, tmp_path):
    import subprocess
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui import emulate_pb_core as core
    monkeypatch.setattr("pinball_decryptor.webui.tabs.emulate_pb.rig_off", lambda: False)
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: [k.get("kind", "pb")] + list(a))
    lists = {"pb": b"entry=setup kind=setup kb=716800 used=1759100000 src=\n"
                   b"disk=31457280 102400000\n",
             "pbio": b"entry=os-clonezilla-live-alien40 kind=os kb=3500000 "
                     b"used=1759200000 src=clonezilla-live-alien40.iso\n"
                     b"disk=31457280 102400000\n"}
    ran = []

    def run(cmd, **k):
        ran.append(cmd)
        out = lists[cmd[0]] if "--list" in cmd else b"dropped=1"
        return subprocess.CompletedProcess(cmd, 0, out, b"")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: True)
    with web_app(tmp_path, mfr="pb") as w:
        svc = _svc(w)
        assert svc.open_cache()
        end = time.time() + 5
        while (w.state(NS).get("cache") or {}).get("busy", True) and time.time() < end:
            time.sleep(0.02)
        rows = w.state(NS)["cache"]["rows"]
        assert [r["label"] for r in rows] == [
            "Emulator setup (Predator's libraries)",
            "Alien machine image (clonezilla-live-alien40.iso)"]
        assert rows[1]["name"] == "pbio:os-clonezilla-live-alien40"
        svc.cache_select([r["name"] for r in rows])
        ran.clear()
        assert svc.cache_delete()
        end = time.time() + 5
        while len([c for c in ran if "--drop" in c]) < 2 and time.time() < end:
            time.sleep(0.02)
        drops = sorted(c for c in ran if "--drop" in c)
        assert drops == [["pb", "cache.sh", "--drop", "setup"],
                         ["pbio", "cache.sh", "--drop", "os-clonezilla-live-alien40"]]


def test_rig_commands_carry_the_apps_rig_slot(monkeypatch):
    """An app a ticket started drives its own rig (PAD_SLOT), as the Stern
    tab does - before PAD-315 every PB run went to rig 0, David's."""
    from pinball_decryptor.webui import emulate_pb_core as core
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    monkeypatch.setenv("PAD_SLOT", "2")
    monkeypatch.setenv("PAD_LABEL", "PAD-315")
    cmd = core.rig_cmd_root("watch.sh", "x.iso", kind="pbio", env=["PAD_VISIBLE=1"])
    assert cmd.index("PAD_SLOT=2") < cmd.index("PAD_VISIBLE=1")
    assert "PAD_LABEL=PAD-315" in cmd
    assert any(c.replace("\\", "/").endswith("pbio_emu/watch.sh") for c in cmd)
    assert "PAD_SLOT=2" in core.rig_cmd("status.sh")
    # an ordinary install: rig 0, nothing added
    monkeypatch.delenv("PAD_SLOT")
    monkeypatch.delenv("PAD_LABEL")
    monkeypatch.delenv("PAD_TICKET", raising=False)
    assert not any(c.startswith("PAD_SLOT=") for c in core.rig_cmd("status.sh"))
