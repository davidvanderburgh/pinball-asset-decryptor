"""The web Emulate Spooky tab (webui/tabs/emulate_spooky.py, PAD-266),
without ever touching a rig: the harness sets PAD_UI_NO_RIG, conftest points
the rig dir at an empty directory, and the tests that need more stub it."""

import time

import pytest

from tests.webui_harness import web_app

NS = "emulate_spooky"


def _svc(w):
    return w.window.service(NS)


@pytest.fixture(autouse=True)
def _no_theme_probe(monkeypatch):
    """macOS asks for the theme through subprocess, which tests here spy on."""
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")


@pytest.fixture
def rig(monkeypatch):
    from pinball_decryptor.webui import emulate_spooky_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)


def _spooky(w):
    if "spooky" not in {m.key for m in w.window.manufacturers}:
        pytest.skip("no spooky plugin (its crypto dependency is missing)")


# ------------------------------------------------------------------ gating
def test_spooky_shows_the_tab_and_says_what_it_runs(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs[NS]["visible"] and tabs[NS]["label"] == "Emulate"
        for other in ("emulate", "emulate_jjp", "emulate_spike1",
                      "emulate_bof", "emulate_dp"):
            assert not tabs[other]["visible"]
        s = w.state(NS)
        assert s["supported"] == [
            "Beetlejuice", "Scooby-Doo", "Texas Chainsaw Massacre",
            "Evil Dead", "Looney Tunes", "Halloween", "Ultraman",
            "Rick and Morty", "Alice Cooper's Nightmare Castle"]
        assert ("Supported: Beetlejuice, Scooby-Doo, Texas Chainsaw "
                "Massacre, Evil Dead, Looney Tunes, Halloween, Ultraman, "
                "Rick and Morty, Alice Cooper's Nightmare Castle."
                in s["intro"])
        assert s["go_label"] == "Start" and s["go_enabled"]
        assert [c["label"] for c in s["cells"]] == [
            "Game", "Version", "Switches", "Window", "Memory", "Uptime"]


@pytest.mark.parametrize("mfr", ["stern", "jjp", "bof"])
def test_other_manufacturers_do_not_get_the_spooky_tab(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs[NS]["visible"]


def test_a_missing_rig_says_so_and_greys_start(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        s = w.state(NS)
        assert not s["go_enabled"] and not s["rig_ok"]
        assert "tools/spooky_emu" in s["note"]


def test_the_shipped_rig_is_complete():
    """rig_available() checks the scripts the tab runs; the repo has them."""
    import os
    from pinball_decryptor.webui import emulate_spooky_core as core
    for s in ("watch.sh", "stop.sh", "status.sh", "cancel.sh", "ctl.sh",
              "spkshim.so", "spkwarden.py", "spkpf.py", "proc/watch.sh",
              "proc/sppctl.py", "proc/sppswitches.py"):
        assert os.path.isfile(os.path.join(core.DEFAULT_RIG_DIR, s)), s


def test_browse_asks_for_a_spooky_update(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        f = tmp_path / "v2026.09.15.11.beetlejuice"
        f.write_bytes(b"")
        w.answers.append(str(f))
        assert w.call(NS + ".browse")
        assert ["Spooky game update",
                "*.beetlejuice *.ed *.looney *.pkg *.scooby"] in w.asked[-1]["filetypes"]
        assert w.window.spooky_emulate_file_var.get() == str(f)


def test_an_empty_field_uses_a_beetlejuice_update_picked_on_select_card(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\v2026.09.15.11.beetlejuice")
        assert svc.file_path().endswith(".beetlejuice")
        # another title's update is picked up too (PAD-316)
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\code_UM.pkg")
        assert svc.file_path().endswith("code_UM.pkg")
        # a restore image, or a game it does not run, is not
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\bj_production_base_image.zip")
        assert svc.file_path() == ""
        w.window.extract_input_var.set(r"D:\Pinball\images\Spooky\tna-gamecode.pkg")
        assert svc.file_path() == ""
        # its own field wins
        w.window.spooky_emulate_file_var.set(r"C:\mods\bj_mod.beetlejuice")
        assert svc.file_path() == r"C:\mods\bj_mod.beetlejuice"


def test_showing_the_tab_puts_up_its_ladder(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        w.call("ui.select_tab", NS)
        f = w.state("shell")["footer"]
        assert f["phases"] == ["Unpack", "Board", "Game", "Ready"]
        assert f["mode"] == "emulate"


def test_start_without_a_file_asks_and_runs_nothing(rig, monkeypatch, tmp_path):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: ran.append(a))
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        w.call(NS + ".toggle")
        assert ran == [] and not _svc(w)._busy


# ------------------------------------------------------------ the poll
RUNNING = {"wsl": "1", "running": "1", "title": "bj", "title_name": "Beetlejuice",
           "build": "bj_v2026.09.15.11", "version": "v2026.09.15.11", "pid": "42",
           "rss_kb": str(3 * 1048576), "uptime_s": "95", "display": ":0",
           "visible": "1", "window": "1280x720", "switches": "60", "slot": "0",
           "attract": "1",
           "switches_json": "/var/tmp/pad_spooky/rig0/switches.json"}


def test_apply_running_fills_the_grid(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _svc(w)._apply(dict(RUNNING))
        s = w.state(NS)
        assert s["up"] and s["ready"] and s["go_label"] == "Stop"
        assert s["state_label"] == "Running" and s["tone"] == "ok"
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Game"] == "Beetlejuice" and v["Version"] == "v2026.09.15.11"
        assert v["Switches"] == "60" and v["Window"] == "1280 × 720"
        assert v["Memory"] == "3.0 GB" and v["Uptime"] == "1:35"


def test_the_grid_names_the_running_title(rig, tmp_path):
    """Every title the rig runs says its own name (status.sh title_name),
    and the board's key alone is enough (PAD-316)."""
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _svc(w)._apply(dict(RUNNING, title="um", title_name="Ultraman",
                            build="um_v1_18", version=""))
        s = w.state(NS)
        v = {c["label"]: c["value"] for c in s["cells"]}
        assert v["Game"] == "Ultraman" and s["game"] == "Ultraman"
        assert s["state_hint"].startswith("Ultraman")
        info = dict(RUNNING, title="h78", attract="0")
        del info["title_name"]
        _svc(w)._apply(info)
        assert w.state(NS)["state_hint"] == "Halloween is loading…"


def test_loading_is_not_yet_running(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _svc(w)._apply(dict(RUNNING, attract="0"))
        s = w.state(NS)
        assert s["state_label"] == "Starting" and not s["ready"]


def test_launch_lines_move_the_footer(rig, tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        seen = []
        svc._footer = lambda kind, pct=None, text="": seen.append((kind, pct))
        for line in ("== Unpack ==", "progress 40", "== Board ==",
                     "== Game ==", "== Ready =="):
            svc._footer_line(line)
        assert seen == [("copy", 0), ("copy", 40), ("boot", None),
                        ("techalerts", None), ("run", None)]


def test_the_switch_window_command(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import emulate_spooky_core as core
    from pinball_decryptor.webui.tabs import emulate_spooky as tab
    monkeypatch.setattr(tab, "windows_python", lambda: "pythonw.exe")
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        cmd = _svc(w)._switch_window_cmd(dict(RUNNING))
        assert cmd[0] == "pythonw.exe" and cmd[1].endswith("spkpf.py")
        assert cmd[cmd.index("--slot") + 1] == "0"
        assert cmd[cmd.index("--distro") + 1] == "PAD-Runtime"
        assert "--parent-pipe" in cmd                  # Stop closes it
        assert cmd[cmd.index("--table") + 1] == (
            r"\\wsl.localhost\PAD-Runtime\var\tmp\pad_spooky\rig0\switches.json")
        assert cmd[cmd.index("--audio-ctl") + 1].endswith("audio_ctl.json")
        # no table yet (the game is still loading): no window
        assert _svc(w)._switch_window_cmd({"running": "1"}) is None


def test_quit_stops_only_a_run_this_app_started(rig, monkeypatch, tmp_path):
    import subprocess
    ran = []
    from pinball_decryptor.webui import emulate_spooky_core as core
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(
        "pinball_decryptor.webui.tabs.emulate_spooky.rig_off", lambda: False)
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
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
    from pinball_decryptor.webui import emulate_spooky_core as core
    ran = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: ["bash"] + list(a))
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **k: ran.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"cancelled=1", b""))
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
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


@pytest.mark.parametrize("name,title", [
    (r"D:\x\v2026.09.15.11.beetlejuice", "Beetlejuice"),
    ("/mnt/d/X.BEETLEJUICE", "Beetlejuice"),
    ("v2025.12.01.09.scooby", "Scooby-Doo"),
    ("tcm-1_00.pkg", "Texas Chainsaw Massacre"),
    ("2026.07.15.ed", "Evil Dead"),
    ("2025.10.08.looney", "Looney Tunes"),
    ("code_H78.pkg", "Halloween"),
    (r"C:\mods\code_H78-modified.pkg", "Halloween"),
    ("code_UM.pkg", "Ultraman"),
    # the P-ROC games (PAD-319)
    ("rm-gamecode-20220902.pkg", "Rick and Morty"),
    (r"D:\Pinball\images\Spooky\AC-GAMECODE.pkg", "Alice Cooper's Nightmare Castle"),
    # a key nobody has, restore images, DMD games: not yet
    ("tna-gamecode.pkg", ""),
    ("rm-gamecode-20220902.zip", ""),
    ("ED_clonezilla_base_image_2025_02_27.iso", ""),
    ("Jetsons_Code.zip", ""),
    ("v2026.09.15.11.beetlejuice.zip", ""),
    ("", ""),
])
def test_supported_file_is_by_name(name, title):
    from pinball_decryptor.webui import emulate_spooky_core as core
    assert core.title_of(name) == title
    assert core.supported_file(name) == bool(title)


def test_every_supported_title_is_one_the_rig_runs():
    """The tab's list and the rig's profiles (spktitles.py) agree."""
    import os
    import pathlib
    import sys
    from pinball_decryptor.webui import emulate_spooky_core as core
    sys.path.insert(0, core.DEFAULT_RIG_DIR)
    try:
        import spktitles
    finally:
        sys.path.remove(core.DEFAULT_RIG_DIR)
    rig = pathlib.Path(core.DEFAULT_RIG_DIR) / "proc"
    run = (rig / "run_game.sh").read_text()
    for name, key, _pats in core.SUPPORTED:
        if key in core.PROC_KEYS:
            # the P-ROC rig's profile names it (run_game.sh NAME=)
            assert 'NAME="%s"' % name in run, key
        else:
            assert spktitles.TITLES[key]["name"] == name
    assert {k for _n, k, _p in core.SUPPORTED} == \
        set(spktitles.TITLES) | set(core.PROC_KEYS)
    assert set(core.PROC_KEYS) == {"rm", "ac"}
    assert "        rm-gamecode*|ac-gamecode*|tna-gamecode*)" in \
        (rig.parent / "spkpath.sh").read_text()


def test_start_refuses_a_file_it_does_not_run(rig, monkeypatch, tmp_path):
    from pinball_decryptor.webui import compat
    from pinball_decryptor.webui import emulate_spooky_core as core
    said, seen = [], []
    monkeypatch.setattr(compat.messagebox, "showinfo",
                        lambda *a, **k: said.append(a))
    monkeypatch.setattr(core, "rig_cmd_root", lambda *a, **k: seen.append(a))
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        f = tmp_path / "tna-gamecode.pkg"
        f.write_bytes(b"x")
        w.window.spooky_emulate_file_var.set(str(f))
        monkeypatch.setattr(svc, "_refuse_off", lambda: False)
        svc._start_async()
        assert seen == [] and not svc._busy
        assert "tna-gamecode.pkg is not an update" in said[-1][1]


def test_start_passes_sound_and_the_volume_control(rig, monkeypatch, tmp_path):
    """As the AP tab: sound always on, the level from the shared control file."""
    from pinball_decryptor.webui import emulate_spooky_core as core
    seen = []
    monkeypatch.setattr(core, "rig_cmd_root",
                        lambda *a, **k: seen.append((a, k)) or ["true"])
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        f = tmp_path / "code_UM.pkg"
        f.write_bytes(b"x")
        w.window.spooky_emulate_file_var.set(str(f))
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
        assert any(e.startswith("PAD_AUDIO_CTL=") and e.endswith("audio_ctl.json")
                   for e in env)
        # the rig board names the run by the file's title
        assert "PAD_TITLE=Ultraman" in env


def test_the_cache_window_lists_and_names_builds(rig, tmp_path):
    from pinball_decryptor.webui import emulate_spooky_core as core
    entries, disk = core.parse_cache(
        "entry=bj_v2026.09.15.11 kind=build kb=5242880 used=1759200000 "
        "src=/mnt/d/Pinball/images/Spooky/v2026.09.15.11.beetlejuice\n"
        "disk=31457280 102400000\n")
    assert disk == (31457280, 102400000)
    assert core.cache_label(entries[0]) == "Beetlejuice v2026.09.15.11"
    assert core.cache_label({"name": "um_v1_18"}) == "Ultraman v1_18"
    assert core.cache_label({"name": "tcm_TCM_V1.00"}) == \
        "Texas Chainsaw Massacre TCM_V1.00"
    assert core.cache_label({"name": "rm_20220902"}) == \
        "Rick and Morty 20220902"
    assert core.cache_label({"name": "ac_1.1.0.5"}) == \
        "Alice Cooper's Nightmare Castle 1.1.0.5"
    assert core.cache_label({"name": "odd"}) == "odd"
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        svc = _svc(w)
        svc._cache_open = True
        svc.set(cache={"head": "", "rows": [], "sel": [], "busy": True, "hint": ""})
        svc._cache_show((entries, disk))
        c = w.state(NS)["cache"]
        assert c["rows"][0]["label"] == "Beetlejuice v2026.09.15.11"
        assert c["rows"][0]["src"].endswith(".beetlejuice")
        assert c["head"].startswith("1 item")


def test_rig_commands_carry_the_apps_rig_slot(monkeypatch):
    """An app a ticket started drives its own rig (PAD_SLOT), as the Stern
    and PB tabs do - before PAD-319 every Spooky run went to rig 0."""
    from pinball_decryptor.webui import emulate_spooky_core as core
    monkeypatch.setattr(core, "rig_distro", lambda: "PAD-Runtime")
    monkeypatch.setenv("PAD_SLOT", "2")
    monkeypatch.setenv("PAD_LABEL", "PAD-319")
    cmd = core.rig_cmd_root("watch.sh", "x.pkg", env=["PAD_VISIBLE=1"])
    assert cmd.index("PAD_SLOT=2") < cmd.index("PAD_VISIBLE=1")
    assert "PAD_LABEL=PAD-319" in cmd
    assert "PAD_SLOT=2" in core.rig_cmd("status.sh")
    # an ordinary install: rig 0, nothing added
    monkeypatch.delenv("PAD_SLOT")
    monkeypatch.delenv("PAD_LABEL")
    monkeypatch.delenv("PAD_TICKET", raising=False)
    assert not any(c.startswith("PAD_SLOT=") for c in core.rig_cmd("status.sh"))
