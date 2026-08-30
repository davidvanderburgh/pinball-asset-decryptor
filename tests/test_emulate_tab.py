"""Emulate tab: the parts that can be got wrong without anyone noticing.

Mostly the pure pieces — status parsing, the wording shown for each state, the
Windows->WSL path map.  The wording is tested because "Waiting at Tech Alerts"
being read as a fault cost this project a whole pass of believing the emulator
was hung when it was doing exactly what the real machine does; a test is the
cheapest way to stop that regressing into "Stuck".

The source-picker tests at the bottom DO build widgets, on an invisible root,
because what they check is the translation from what the user picked into the
environment the rig is handed — and that only exists once the widgets do.  They
skip rather than fail when Tk is unusable.
"""

import json
import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

from pinball_decryptor.gui import emulate_tab

from pinball_decryptor.gui.emulate_tab import (DEFAULT_RIG_DIR, parse_status,
                                               rig_cmd_root, setup_extras,
                                               setup_notice, setup_ok,
                                               setup_settled, setup_state,
                                               setup_summary, state_text,
                                               _NEEDS_WSL_RESTART, _wsl_path)

# ``setup_state`` is imported BY VALUE here on purpose.  The autouse fixture
# below replaces ``emulate_tab.setup_state`` so that building a panel never
# shells out to WSL, and the two tests that are about the probe itself have to
# reach the real one - through this binding, which monkeypatch does not touch.
# Without it they exercised the stub and one of them passed for that reason.


@pytest.fixture(autouse=True)
def _no_real_setup_probe(monkeypatch):
    """Building a panel probes THIS machine for what the emulator needs, and a
    unit test must not shell out to WSL to find out.  None is "could not ask",
    which is deliberately the same as "nothing to say" - so the default panel
    in every test below carries no prerequisite notice.  Tests that are about
    the notice patch this again with facts of their own."""
    monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)


def test_parse_status_reads_key_value_lines():
    info = parse_status("procs=5\nrunning=1\ncpu=14.9\nrss=995\nstate=running\n")
    assert info["procs"] == "5"
    assert info["running"] == "1"
    assert info["cpu"] == "14.9"
    assert info["state"] == "running"


def test_parse_status_survives_noise_and_emptiness():
    # status.sh is invoked through wsl.exe, which is entitled to prepend its own
    # warnings ("your 131072x1 screen size is bogus") to stdout.
    assert parse_status("") == {}
    assert parse_status(None) == {}
    info = parse_status("your screen size is bogus\nstate=off\n")
    assert info == {"state": "off"}


def test_values_containing_equals_are_not_truncated():
    assert parse_status("log=/home/x/a=b.log")["log"] == "/home/x/a=b.log"


def test_tech_alerts_is_described_as_a_place_not_a_fault():
    # ("Waiting at Tech Alerts" until 2026-08-24 — but since item 63 a boot
    # steps past the screen on its own, so "waiting" was itself misleading;
    # David called it. The point stands: at a glance it must not read as a
    # defect.)
    label, hint = state_text({"state": "techalerts"})
    assert label == "At Tech Alerts"
    for wrong in ("stuck", "hung", "fault", "error", "failed", "parked"):
        assert wrong not in label.lower(), wrong
    # The hint has to say what to do about it, and say it is normal.
    assert "press a switch" in hint.lower()
    assert "not a fault" in hint.lower()


def test_tech_alerts_hint_changes_while_auto_advance_is_working():
    # Telling the user to press something while autoattract.sh is pressing it
    # gets two operators fighting over the same screen — and the label names
    # the WORK (the node-bus bring-up, matching the footer's "Node boards"
    # chip), not the readout screen it ends on.
    label, hint = state_text({"state": "techalerts", "auto": "1"})
    assert "node boards" in label.lower()
    assert "press a switch" not in hint.lower()
    assert "attract" in hint.lower()


def test_auto_advance_wording_only_applies_at_tech_alerts():
    # auto= lingers for a poll or two after the game has moved on; the hint for
    # a running game must not turn into "skipping to attract mode".
    _, hint = state_text({"state": "running", "auto": "1"})
    assert hint == "Attract loop, operator menu, or a game in play."
    # auto=0 is the rig saying the helper has finished or was never started.
    _, hint = state_text({"state": "techalerts", "auto": "0"})
    assert "press a switch" in hint.lower()


def test_every_state_the_rig_can_emit_has_wording():
    # `attract` is the word status.sh emits now; `running` is what it emitted
    # before, kept so an older rig still reads as something.
    for state in ("off", "booting", "techalerts", "attract", "running"):
        label, _ = state_text({"state": state})
        assert label and label != state


def test_a_running_game_is_not_called_attract_or_tech_alerts():
    # Two generations of the same lie. 2026-08-05: the app said "Waiting at
    # Tech Alerts" while the game sat in attract (status.sh and
    # autoattract.sh disagreed). 2026-08-24, David: "when i start a game,
    # it's no longer in attract mode" — the rig deliberately cannot tell
    # attract from a game in play (gamestate.sh), so the label must claim
    # neither.  "Game running" is what it can stand behind.
    label, hint = state_text({"state": "attract"})
    assert "running" in label.lower()
    assert "attract" not in label.lower()
    assert "tech alert" not in label.lower()
    # ...the honest breakdown lives in the hint instead.
    assert "attract" in hint.lower() and "in play" in hint.lower()


def test_auto_advance_giving_up_is_not_shown_as_ordinary_waiting():
    # auto=0 means the helper is not running; it does NOT mean it succeeded.
    # "finished the job" and "ran out of presses" both used to read as the
    # same unchanging "Waiting at Tech Alerts", and they need opposite things
    # from the human.
    label, hint = state_text({"state": "techalerts", "auto": "0",
                              "auto_result": "gaveup"})
    assert "stuck" in label.lower()
    assert "service menu" in hint.lower()
    assert "esc" in hint.lower()
    # ...a helper that simply finished reads as being AT the screen — not
    # "Waiting", which was a lie in the common case once item 63 made boots
    # step past it on their own (David, 2026-08-24).
    label, hint = state_text({"state": "techalerts", "auto": "0",
                              "auto_result": "ok"})
    assert label == "At Tech Alerts"
    assert "press a switch" in hint.lower()
    # ...and while the helper is actually on the job, the label names the
    # node-bus work, matching the footer chip.
    label, _ = state_text({"state": "techalerts", "auto": "1"})
    assert "node boards" in label.lower()


def test_unknown_state_falls_back_to_the_raw_word():
    # Better to show what the rig said than to silently claim it is off.
    assert state_text({"state": "wat"})[0] == "wat"
    assert state_text({})[0] == "Not running"


def test_windows_paths_map_into_wsl():
    assert _wsl_path(r"c:\repo\tools\spike2_emu") == "/mnt/c/repo/tools/spike2_emu"
    assert _wsl_path(r"D:\a\b") == "/mnt/d/a/b"
    # Already a POSIX path (someone set PAD_EMU_DIR from inside WSL).
    assert _wsl_path("/mnt/c/repo/tools/spike2_emu") == "/mnt/c/repo/tools/spike2_emu"


def test_default_rig_dir_is_the_copy_in_the_repo():
    # The rig used to live in c:\tmp, where a reboot could take it. It is in the
    # repo now, and this default is what makes the Emulate tab find it - so a
    # relocation that forgets this file breaks Start with no other symptom.
    rig = pathlib.Path(DEFAULT_RIG_DIR)
    assert rig.name == "spike2_emu" and rig.parent.name == "tools"
    assert (rig / "watch.sh").is_file()
    assert (rig / "status.sh").is_file()


def test_stop_and_killgame_agree_on_the_restart_token():
    # Stop's "restart WSL?" offer fires on a token killgame.sh prints when
    # leftovers survive everything it can do from inside the VM.  2026-08-09:
    # dead guests held as zombies kept the process count nonzero, so the
    # button stayed on Stop (which killed nothing) and "Restart WSL…" stayed
    # greyed out (nonzero procs reads as a live run) - a wedge only `wsl
    # --shutdown` from Windows could clear, and only the log pane knew.  The
    # token lives in two languages; this is what keeps it ONE string.
    killgame = (pathlib.Path(DEFAULT_RIG_DIR) / "killgame.sh").read_text(
        encoding="utf-8")
    emitted = [ln for ln in killgame.splitlines()
               if _NEEDS_WSL_RESTART in ln
               and not ln.lstrip().startswith("#")]
    assert emitted, ("killgame.sh no longer prints %r, so Stop can never "
                     "offer the WSL restart again" % _NEEDS_WSL_RESTART)
    assert any("echo" in ln for ln in emitted)


# --------------------------------------------------------------------------
# "Card image to run" survives a restart
#
# The field was empty on every launch and the path had to be re-browsed.  The
# save half was never the problem: _on_close and _materialize_anchor have
# always written `emulate_card` into the project anchor, and
# _apply_project_folder has always read it back — but that only runs on an
# EXPLICIT Project -> Open.  An ordinary startup goes through
# _apply_manufacturer, which restored the manufacturer's paths and re-marked
# the folder as the loaded project without ever fetching the card.
#
# So these drive _apply_manufacturer itself rather than a helper in isolation.
# A helper test would have passed against the broken app, because the bug was
# that nothing called it.  Stub pattern borrowed from test_gui_batch27.
# --------------------------------------------------------------------------

def _anchor(folder, emulate_card=None):
    """Write a project anchor into *folder* through the REAL writers — save()
    for the anchor and update_anchor() for the card, which is the pair
    _materialize_anchor and _on_close actually use.  Hand-rolling the JSON
    here silently produced a file load() rejects (no "kind"), and the tests
    then passed the failure off as the app's."""
    from pinball_decryptor.core import project_file
    project_file.save(
        project_file.anchor_path(str(folder)),
        manufacturer_key="stern",
        paths={"extract_input": "C:/stock/game.raw",
               "extract_output": str(folder)},
        extract_options={},
        app_version="test")
    if emulate_card is not None:
        project_file.update_anchor(str(folder), emulate_card=emulate_card)


def _restore(folder, settings=None):
    """Run _apply_manufacturer over *folder* and return what the card field
    ends up showing."""
    from pinball_decryptor.app import App

    class _Var:
        def __init__(self):
            self.value = "SENTINEL — never set"

        def set(self, v):
            self.value = v

    var = _Var()
    stub = SimpleNamespace(
        _load_manufacturer_paths=lambda key: None,
        _kick_off_prereq_check=lambda mfr: None,
        _project_folder=lambda: str(folder),
        _set_loaded_project=lambda p: None,
        _settings=settings if settings is not None else {},
        window=SimpleNamespace(apply_manufacturer=lambda mfr: None,
                               emulate_card_var=var),
    )
    # Bound by hand rather than stubbed out: BOTH halves have to be the real
    # code or this stops testing the thing that was broken, which was the call
    # site and not the restore.
    stub._restore_emulate_card = (
        lambda folder: App._restore_emulate_card(stub, folder))
    App._apply_manufacturer(stub, SimpleNamespace(key="stern"))
    return var.value


def test_startup_restores_the_card_from_the_project(tmp_path):
    proj = tmp_path / "godzilla"
    proj.mkdir()
    _anchor(proj, emulate_card="D:/cards/godzilla.raw")
    assert _restore(proj) == "D:/cards/godzilla.raw"


def test_a_second_project_shows_its_own_card_not_the_first(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    _anchor(a, emulate_card="D:/cards/a.raw")
    _anchor(b, emulate_card="D:/cards/b.raw")
    assert _restore(a) == "D:/cards/a.raw"
    assert _restore(b) == "D:/cards/b.raw"


def test_a_project_with_no_card_shows_empty_not_the_global(tmp_path):
    """A project's own value wins even when it is EMPTY.  Falling back here
    would leak the previously-used card into a project that never had one,
    which is the exact leak _apply_project_folder already guards against."""
    proj = tmp_path / "fresh"
    proj.mkdir()
    _anchor(proj)
    assert _restore(proj, {"emulate_card": "D:/cards/other.raw"}) == ""


def test_no_project_falls_back_to_the_global_last_used(tmp_path):
    plain = tmp_path / "just-a-folder"
    plain.mkdir()
    assert _restore(plain, {"emulate_card": "D:/cards/last.raw"}) \
        == "D:/cards/last.raw"
    assert _restore(plain, {}) == ""
    assert _restore("", {"emulate_card": "D:/cards/last.raw"}) \
        == "D:/cards/last.raw"


def test_an_unreadable_anchor_leaves_the_field_empty_not_broken(tmp_path):
    """Anchors live in the project folder, which is often a NAS.  A truncated
    or half-written one must not take the startup down with it."""
    proj = tmp_path / "corrupt"
    proj.mkdir()
    from pinball_decryptor.core import project_file
    pathlib.Path(project_file.anchor_path(str(proj))).write_text(
        "{not json", encoding="utf-8")
    assert _restore(proj) == ""


def test_the_global_is_written_on_every_settings_save(tmp_path, monkeypatch):
    """Without this the no-project fallback above has nothing to read: the
    anchor save in _on_close is skipped outright when the folder is not a
    project, so a card picked against a plain folder had nowhere to live."""
    from pinball_decryptor import app as app_mod
    from pinball_decryptor.app import App
    # _save_settings really writes, so point it somewhere disposable — the
    # default is the user's live settings.json.
    monkeypatch.setattr(app_mod, "SETTINGS_FILE",
                        str(tmp_path / "settings.json"))
    settings = {}
    stub = SimpleNamespace(
        _current_mfr=None,
        _settings=settings,
        root=SimpleNamespace(winfo_geometry=lambda: "1x1"),
        # The save also records the window state; a 1x1 footprint is below
        # the "don't persist a window you can't see" floor, so nothing but
        # the maximized flag comes out of it here.
        _window_is_maximized=lambda: False,
        _last_normal_geometry=None,
        window=SimpleNamespace(
            _current_theme="dark",
            _last_browse_dirs=None,
            emulate_card_var=SimpleNamespace(
                get=lambda: "  D:/cards/last.raw  ")),
    )
    App._save_settings(stub)
    assert settings["emulate_card"] == "D:/cards/last.raw"


# --------------------------------------------------------------------------
# Source picker
# --------------------------------------------------------------------------

def _panel(tmp_path):
    """A built panel on an invisible root, or a skip when Tk is unusable."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # no display / no Tcl
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    frame = tk.Frame(root)
    frame.pack()
    panel = emulate_tab.EmulatePanel(frame)
    panel.build(frame)
    root.update()
    return root, panel


def test_card_source_becomes_pad_card(tmp_path):
    """A card image is handed to the rig as PAD_CARD, in WSL form."""
    img = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    img.write_bytes(bytes(16))
    root, panel = _panel(tmp_path)
    try:
        panel._src_path.set(str(img))
        env = panel._source_env()
        assert len(env) == 1 and env[0].startswith("PAD_CARD=")
        assert env[0].endswith(img.name)
        assert "\\" not in env[0]      # a Windows path would not mount
    finally:
        root.destroy()


def test_missing_image_is_refused_on_the_tab(tmp_path):
    """A bad path is a sentence on the tab, not a shell error in the log."""
    root, panel = _panel(tmp_path)
    try:
        panel._src_path.set(str(tmp_path / "nope.raw"))
        assert panel._source_env() is None
        assert "No such image" in panel._hint.cget("text")
        panel._src_path.set("")
        assert panel._source_env() is None
        assert "Pick a card image" in panel._hint.cget("text")
    finally:
        root.destroy()


def test_no_folder_or_rig_options(tmp_path):
    """An extracted folder is the wrong shape for the rig and the rig's own
    copy is internal state; neither is offered any more."""
    root, panel = _panel(tmp_path)
    try:
        assert not hasattr(panel, "_src_kind")
        texts = []
        def walk(w):
            for child in w.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except Exception:                        # noqa: BLE001
                    pass
                walk(child)
        walk(root)
        blob = " ".join(texts)
        assert "Extracted folder" not in blob
        assert "Rig's own copy" not in blob
        # And no buttons guessing which of the project's images you meant.
        assert "Use stock image" not in blob
        assert "Use modded image" not in blob
    finally:
        root.destroy()


def test_keys_help_is_gone(tmp_path):
    """The rig's own Controls window is the single source of truth for the key
    bindings; a copy on this tab could only drift."""
    root, panel = _panel(tmp_path)
    try:
        texts = []
        def walk(w):
            for child in w.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except Exception:                        # noqa: BLE001
                    pass
                walk(child)
        walk(root)
        blob = " ".join(texts)
        assert "Service Plus" not in blob
        assert "shooter lane" not in blob
    finally:
        root.destroy()


# --- item 56: master PC-side volume + Mute -----------------------------------
#
# "master pc volume knob for emulator (not for in game, but for the emulator
# to my pc speakers). should have mute and volume setting controls." — the
# file is BOTH the remembered preference and padplay.py's live control
# channel (see AUDIO_CTL_FILE's docstring), so these tests cover the GUI half
# of that contract: what gets written, what gets loaded back, and that a
# corrupt/missing file degrades to today's unity/unmuted behaviour rather
# than failing the panel outright.
#
# EVERY test below points AUDIO_CTL_FILE at its own tmp_path first. The
# session-wide _isolate_audio_ctl fixture in conftest.py is only the backstop
# against a stray write reaching the developer's real settings dir; it shares
# ONE path for the whole run, so a test that cares whether the file is
# absent, corrupt, or holds a specific value needs its own, or it would be
# reading whatever the previous test in the session left behind.

def _isolated_ctl(monkeypatch, tmp_path):
    path = str(tmp_path / "audio_ctl.json")
    monkeypatch.setattr(emulate_tab, "AUDIO_CTL_FILE", path)
    return path


def test_audio_ctl_round_trips(monkeypatch, tmp_path):
    _isolated_ctl(monkeypatch, tmp_path)
    emulate_tab._write_audio_ctl(0.35, False)
    assert emulate_tab._load_audio_ctl() == (0.35, False)
    emulate_tab._write_audio_ctl(0.0, True)
    assert emulate_tab._load_audio_ctl() == (0.0, True)


def test_audio_ctl_defaults_to_unity_unmuted_when_absent(monkeypatch, tmp_path):
    path = _isolated_ctl(monkeypatch, tmp_path)
    assert not os.path.exists(path)
    assert emulate_tab._load_audio_ctl() == (1.0, False)


def test_audio_ctl_survives_a_corrupt_file(monkeypatch, tmp_path):
    """Half-written or foreign JSON must not take the panel down with it —
    same tolerance as every other small state file in this rig."""
    path = _isolated_ctl(monkeypatch, tmp_path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert emulate_tab._load_audio_ctl() == (1.0, False)


def test_audio_ctl_clamps_an_out_of_range_gain(monkeypatch, tmp_path):
    path = _isolated_ctl(monkeypatch, tmp_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"gain": 4.0, "muted": False}, f)
    assert emulate_tab._load_audio_ctl() == (1.0, False)


def test_panel_shows_the_remembered_volume(monkeypatch, tmp_path):
    """The slider reflects the file at construction — the acceptance test's
    "the level survives an app restart", read from the GUI side."""
    _isolated_ctl(monkeypatch, tmp_path)
    emulate_tab._write_audio_ctl(0.6, False)
    root, panel = _panel(tmp_path)
    try:
        assert round(panel._volume_var.get()) == 60
        assert panel._mute_var.get() is False
    finally:
        root.destroy()


def test_panel_shows_remembered_mute(monkeypatch, tmp_path):
    _isolated_ctl(monkeypatch, tmp_path)
    emulate_tab._write_audio_ctl(0.6, True)
    root, panel = _panel(tmp_path)
    try:
        assert panel._mute_var.get() is True
    finally:
        root.destroy()


def test_moving_the_slider_writes_the_control_file_live(monkeypatch, tmp_path):
    """No restart, no Start press — the write happens the moment the var
    changes, which is what lets a running padplay.py pick it up inside one
    poll interval."""
    _isolated_ctl(monkeypatch, tmp_path)
    root, panel = _panel(tmp_path)
    try:
        panel._volume_var.set(25)
        panel._on_volume_change()
        assert emulate_tab._load_audio_ctl() == (0.25, False)
        panel._mute_var.set(True)
        panel._on_volume_change()
        assert emulate_tab._load_audio_ctl() == (0.25, True)
    finally:
        root.destroy()


def test_building_the_panel_seeds_the_file_on_a_fresh_machine(monkeypatch,
                                                              tmp_path):
    """A machine that has never touched the knob must still have the file
    present before the first Start — padplay.py's own default (unity) would
    otherwise happen to agree, but the file existing is what makes it a real
    control channel rather than two defaults coinciding."""
    path = _isolated_ctl(monkeypatch, tmp_path)
    assert not os.path.exists(path)
    root, panel = _panel(tmp_path)
    try:
        assert emulate_tab._load_audio_ctl() == (1.0, False)
    finally:
        root.destroy()


def test_volume_and_mute_are_never_disabled_by_a_run(monkeypatch, tmp_path):
    """The whole point of item 56's slider is that it works WITHOUT a
    restart, so it must stay live through exactly the state that disables
    its neighbours (Reset windows is the sanity probe for "a run disables
    things" — the Sound/Auto-attract tickboxes that used to be it were
    removed on 2026-08-24: both behaviours are simply always on)."""
    _isolated_ctl(monkeypatch, tmp_path)
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    root, panel = _panel(tmp_path)
    try:
        panel._apply({"state": "running", "running": "1", "procs": "5"})
        assert str(panel._winreset_btn.cget("state")) == "disabled"   # sanity
        assert str(panel._vol_scale.cget("state")) != "disabled"
        assert str(panel._mute_chk.cget("state")) != "disabled"
    finally:
        root.destroy()


def test_start_tells_the_rig_where_the_control_file_is(monkeypatch, tmp_path):
    import time
    _isolated_ctl(monkeypatch, tmp_path)
    img = tmp_path / "godzilla_pro-1_15_0.Release.8G.sdcard.raw"
    img.write_bytes(bytes(16))
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    monkeypatch.setattr(emulate_tab, "docker_state", lambda: "ok")
    captured = {}

    def fake_watch_cmd(minutes, env, savestates=True):
        captured["env"] = env
        return ["true"]

    monkeypatch.setattr(emulate_tab, "watch_cmd", fake_watch_cmd)
    monkeypatch.setattr(
        emulate_tab.subprocess, "Popen",
        lambda *a, **kw: SimpleNamespace(stdout=iter(()),
                                         wait=lambda timeout=None: 0))
    root, panel = _panel(tmp_path)
    try:
        panel._src_path.set(str(img))
        panel.start()
        deadline = time.time() + 5
        while "env" not in captured and time.time() < deadline:
            time.sleep(0.01)
        assert "PAD_AUDIO_CTL=" + emulate_tab.AUDIO_CTL_FILE in captured["env"]
    finally:
        root.destroy()


# --- how each platform reaches the rig ---------------------------------------
#
# The rig is a Linux program and the three platforms differ only in how Linux is
# reached.  Getting this wrong is invisible on the machine you develop on and
# total on the other two, which is exactly what a test is for.

def _cmd_on(monkeypatch, platform, tmp_path, *args, **kw):
    monkeypatch.setattr(emulate_tab.sys, "platform", platform)
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    return emulate_tab.rig_cmd(*args, **kw)


def test_linux_runs_the_rig_directly(monkeypatch, tmp_path):
    cmd = _cmd_on(monkeypatch, "linux", tmp_path, "watch.sh", 30)
    assert cmd[0] == "bash"
    assert cmd[1].endswith("watch.sh")
    assert cmd[2] == "30"
    assert "wsl.exe" not in cmd


def test_windows_reaches_the_rig_through_wsl(monkeypatch, tmp_path):
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "watch.sh", 30)
    assert cmd[:2] == ["wsl.exe", "-e"]
    assert "bash" in cmd
    # The path handed to WSL must be a POSIX one, never the Windows spelling.
    assert not any("\\" in c for c in cmd), cmd


def test_macos_goes_through_the_container(monkeypatch, tmp_path):
    """qemu-user translates LINUX syscalls and the chroot needs Linux
    namespaces, so macOS runs the rig in a container rather than natively.
    padbox.sh owns every detail of that."""
    cmd = _cmd_on(monkeypatch, "darwin", tmp_path, "watch.sh", 30)
    assert any(c.endswith("padbox.sh") for c in cmd), cmd
    assert "wsl.exe" not in cmd
    assert cmd[-2:] == ["watch.sh", "30"]


def test_env_survives_the_hop_on_every_platform(monkeypatch, tmp_path):
    """`env NAME=value` rather than a shell assignment: wsl.exe re-parses its
    arguments, and `$var` expands to nothing on that second pass."""
    for platform in ("linux", "win32", "darwin"):
        cmd = _cmd_on(monkeypatch, platform, tmp_path, "watch.sh", 30,
                      env=["LOG=/tmp/x.log"])
        assert "LOG=/tmp/x.log" in cmd, (platform, cmd)
        assert any(c.endswith("env") or c == "env" for c in cmd), (platform, cmd)


# --- the checkpointable launch (item 13) -------------------------------------
#
# On Windows, Start boots the guest as root under PAD_PIVOT=1 - the only shape
# criu can checkpoint, so the only shape the playfield's Save/Load state
# buttons work in.  watch.sh drops the helpers back to the desktop user, whose
# home rides along explicitly because root's own HOME is the wrong rootfs.

def _home(monkeypatch, value):
    """Pin wsl_home()'s answer - the probe itself needs a live WSL."""
    monkeypatch.setattr(emulate_tab, "_WSL_HOME", [value, True])


def test_windows_start_is_the_checkpointable_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_tab.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"])
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert "PAD_PIVOT=1" in cmd
    assert "HOME=/home/somebody" in cmd
    # The caller's env still survives the hop, same rule as rig_cmd's.
    assert "PAD_CARD=/mnt/c/x.raw" in cmd
    assert cmd[-1] == "120"
    assert not any("\\" in c for c in cmd), cmd


def test_a_failed_home_probe_degrades_to_the_ordinary_launch(monkeypatch,
                                                             tmp_path):
    """No save states rather than a root run pointed at /root/spike2root."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, None)
    cmd = emulate_tab.watch_cmd(120, [])
    assert cmd[:2] == ["wsl.exe", "-e"]
    assert "-u" not in cmd and "PAD_PIVOT=1" not in cmd


def test_savestates_off_is_the_ordinary_launch(monkeypatch, tmp_path):
    """The tab's opt-out - and the DEFAULT: with the toggle off, even a
    machine whose home probe would succeed boots the plain user launch, not
    root and not PAD_PIVOT, so a run costs nothing it did not cost before
    item 13.  watch.sh then starts the playfield without its Save/Load
    state controls (no --savestates), so nothing on screen can only refuse."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_tab.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"],
                                savestates=False)
    assert cmd[:2] == ["wsl.exe", "-e"]
    assert "-u" not in cmd and "PAD_PIVOT=1" not in cmd
    # The caller's env still survives the hop, same rule as rig_cmd's.
    assert "PAD_CARD=/mnt/c/x.raw" in cmd


def test_other_platforms_keep_their_launch(monkeypatch, tmp_path):
    """The pivot boot is a WSL arrangement; macOS's container and a Linux
    desktop keep the launch they had."""
    for platform in ("linux", "darwin"):
        monkeypatch.setattr(emulate_tab.sys, "platform", platform)
        monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
        _home(monkeypatch, "/home/somebody")
        cmd = emulate_tab.watch_cmd(30, [])
        assert "wsl.exe" not in cmd, (platform, cmd)
        assert "PAD_PIVOT=1" not in cmd, (platform, cmd)


def test_launch_from_slot_loads_as_root_with_the_desktop_home(monkeypatch,
                                                              tmp_path):
    """The tab's Launch button restores a slot: root (criu), the desktop
    HOME (padpath's rootfs), and PAD_RESTORE_KILL so the booted guest is
    replaced by the restored one."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_tab.load_cmd("slot3")
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert "HOME=/home/somebody" in cmd
    assert "PAD_RESTORE_KILL=1" in cmd
    assert any(c.endswith("loadgame.sh") for c in cmd)
    assert cmd[-1] == "slot3"


def test_stop_kills_as_root_on_windows(monkeypatch, tmp_path):
    """A PAD_PIVOT guest is a root process: the ordinary user's pkill reports
    success and kills nothing.  Root's kill reaches both kinds of run."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_tab.kill_cmd()
    assert cmd[:3] == ["wsl.exe", "-u", "root"]
    assert any(c.endswith("killgame.sh") for c in cmd)
    _home(monkeypatch, None)
    cmd = emulate_tab.kill_cmd()
    assert cmd[:2] == ["wsl.exe", "-e"], cmd


def test_the_container_entry_point_ships_with_the_rig():
    """rig_cmd names it on macOS, so its absence would be a macOS-only failure
    that nobody developing on Windows or Linux would ever see."""
    import os
    box = pathlib.Path(DEFAULT_RIG_DIR) / "docker" / "padbox.sh"
    dockerfile = pathlib.Path(DEFAULT_RIG_DIR) / "docker" / "Dockerfile"
    entry = pathlib.Path(DEFAULT_RIG_DIR) / "docker" / "entrypoint.sh"
    if not pathlib.Path(DEFAULT_RIG_DIR).is_dir():
        pytest.skip("rig not present")
    for p in (box, dockerfile, entry):
        assert p.is_file(), "missing %s" % p


# --------------------------------------------------------------------------
# Docker, which is macOS's WSL
# --------------------------------------------------------------------------

def _fake_run(rc=0, raises=None):
    def run(*a, **kw):
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=rc)
    return run


def test_docker_state_tells_absent_from_stopped(monkeypatch):
    """Two different faults with two different remedies: nothing installed is a
    download, installed-but-down is one click.  Collapsing them into "no
    Docker" sends someone to the website who already has it."""
    # The client is FOUND here, so this test is about the three answers the
    # probe itself gives.  Finding it is its own question and its own test
    # below - a machine with no docker at all answers "absent" before running
    # anything, which is the point of that one.
    monkeypatch.setattr(emulate_tab, "docker_cli",
                        lambda: "/usr/local/bin/docker")
    # AND THE ENGINE IS FOUND, because on darwin a failing `docker info` is
    # only "stopped" when there is something behind the client to have
    # stopped - the engineless split below is what this same call answers
    # otherwise, and it has its own test.  Unpinned, this read "engineless"
    # on the macOS CI runner, which ships neither an engine nor colima.
    monkeypatch.setattr(emulate_tab, "docker_engine",
                        lambda: ("Docker Desktop", "app",
                                 "/Applications/Docker.app"))
    monkeypatch.setattr(emulate_tab.subprocess, "run", _fake_run(rc=0))
    assert emulate_tab.docker_state() == "ok"
    monkeypatch.setattr(emulate_tab.subprocess, "run", _fake_run(rc=1))
    assert emulate_tab.docker_state() == "stopped"
    monkeypatch.setattr(emulate_tab.subprocess, "run",
                        _fake_run(raises=FileNotFoundError()))
    assert emulate_tab.docker_state() == "absent"


def test_docker_is_looked_for_where_a_mac_actually_keeps_it(tmp_path,
                                                           monkeypatch):
    """★ PAD-74.  A Mac app launched from Finder inherits launchd's PATH -
    /usr/bin:/bin:/usr/sbin:/sbin - so a bare ["docker", "info"] is a PATH
    lookup that fails on a Mac where docker is installed and working.  A
    reporter had installed it with MacPorts, and the tab told him Docker
    Desktop was required while /opt/local/bin/docker sat on his disk."""
    tool = tmp_path / "docker"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(emulate_tab.shutil, "which", lambda *a, **kw: None)
    assert emulate_tab.which_tool("docker", (str(tmp_path),)) == str(tool)
    assert emulate_tab.which_tool("nosuchtool", (str(tmp_path),)) is None
    # PATH still wins when it has an answer: someone who launched the app from
    # a terminal has already said which docker they mean.
    monkeypatch.setattr(emulate_tab.shutil, "which", lambda *a, **kw: "/p/d")
    assert emulate_tab.which_tool("docker", (str(tmp_path),)) == "/p/d"
    # The list itself is the fix, so the places it must name are the test.
    for d in ("/usr/local/bin",                     # Docker Desktop's symlink
              "/opt/homebrew/bin",                  # Homebrew, Apple Silicon
              "/opt/local/bin",                     # MacPorts - the reporter
              "~/.docker/bin"):                     # Desktop, no symlink
        assert d in emulate_tab.DOCKER_DIRS, d


def test_pad_docker_overrides_and_a_wrong_one_is_not_ignored(tmp_path,
                                                             monkeypatch):
    """The escape hatch for the Mac that keeps it somewhere else - and a
    support instruction that is silently ignored when mistyped is worse than
    one that fails, so a bad override is "absent", not a fallback."""
    tool = tmp_path / "docker"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("PAD_DOCKER", str(tool))
    assert emulate_tab.docker_cli() == str(tool)
    monkeypatch.setenv("PAD_DOCKER", str(tmp_path / "nope"))
    assert emulate_tab.docker_cli() is None


def test_a_client_with_no_engine_is_not_a_missing_docker(monkeypatch):
    """★ PAD-74's second half.  On macOS `docker` is only a client: the
    containers need a Linux machine behind it, and a package manager's docker
    ships none (MacPorts says so of its own port).  That Mac is neither
    "Docker is stopped" - there is nothing to start - nor "not installed",
    which is what it used to be told."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "darwin")
    monkeypatch.setattr(emulate_tab, "docker_cli",
                        lambda: "/opt/local/bin/docker")
    monkeypatch.setattr(emulate_tab.subprocess, "run", _fake_run(rc=1))
    monkeypatch.setattr(emulate_tab, "docker_engine", lambda: None)
    assert emulate_tab.docker_state() == "engineless"
    # An engine that IS installed makes the same failure "start it".
    monkeypatch.setattr(emulate_tab, "docker_engine",
                        lambda: ("Colima", "cli", "/opt/local/bin/colima"))
    assert emulate_tab.docker_state() == "stopped"


def test_engineless_is_macos_only(monkeypatch):
    """Everywhere else the daemon is local, so "installed but not running" is
    the whole of the question and a fourth answer would be a wrong one."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "linux")
    monkeypatch.setattr(emulate_tab, "docker_cli", lambda: "/usr/bin/docker")
    monkeypatch.setattr(emulate_tab.subprocess, "run", _fake_run(rc=1))
    monkeypatch.setattr(emulate_tab, "docker_engine", lambda: None)
    assert emulate_tab.docker_state() == "stopped"


def test_the_setup_plan_follows_the_package_manager_already_working(
        monkeypatch):
    """Colima, from whichever package manager put the client there.  Telling a
    MacPorts user to install Homebrew first is a second package manager for a
    problem the first one solves - and MacPorts' own docker port points at
    colima for exactly this."""
    monkeypatch.setattr(emulate_tab, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_tab, "which_tool",
                        lambda name, dirs=None: ("/opt/local/bin/port"
                                                 if name == "port" else None))
    plan = emulate_tab.engine_setup_plan("/opt/local/bin/docker")
    assert plan["manager"] == "MacPorts"
    # THE PLAN IS THE WORK, not a sentence about the work: this argv is what
    # the button runs, and -N so nothing it cannot see asks a question.
    assert plan["install"] == ["/opt/local/bin/port", "-N", "install", "colima"]
    assert plan["admin"] is True            # port installs system-wide
    assert plan["steps"] and all(isinstance(s, str) for s in plan["steps"])
    # No client at all: colima is the Linux machine, not the docker command,
    # so that Mac needs both.
    assert emulate_tab.engine_setup_plan(None)["packages"] == ["docker",
                                                               "colima"]
    # Homebrew's docker gets Homebrew's colima - and NEVER as root, which
    # Homebrew refuses outright.
    monkeypatch.setattr(emulate_tab, "homebrew",
                        lambda: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(emulate_tab, "which_tool",
                        lambda name, dirs=None: None)
    plan = emulate_tab.engine_setup_plan("/opt/homebrew/bin/docker")
    assert plan["manager"] == "Homebrew"
    assert plan["install"] == ["/opt/homebrew/bin/brew", "install", "colima"]
    assert plan["admin"] is False
    # Neither package manager: there is nothing this app can drive, so there
    # is no plan and the tab must not grow a button that cannot work.
    monkeypatch.setattr(emulate_tab, "homebrew", lambda: None)
    assert emulate_tab.engine_setup_plan("/opt/local/bin/docker") is None


def test_no_step_of_the_mac_setup_asks_anyone_to_type_a_command(monkeypatch):
    """★ David, 2026-08-19: "we should never be asking the user to type things
    in the terminal".  The plan's sentences are what the consent dialog and the
    tab's notice are both built from, so this is the one place to hold the
    line - and the notice is built from the plan for exactly that reason."""
    monkeypatch.setattr(emulate_tab, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_tab, "which_tool",
                        lambda name, dirs=None: ("/opt/local/bin/port"
                                                 if name == "port" else None))
    banned = ("terminal", "sudo ", "type this", "brew install", "port install")
    for cli in ("/opt/local/bin/docker", None):
        plan = emulate_tab.engine_setup_plan(cli)
        assert plan, cli
        words = " ".join(plan["steps"]).lower()
        words += " " + emulate_tab.EmulatePanel._plan_sentence(plan).lower()
        for phrase in banned:
            assert phrase not in words, (phrase, words)
        # It says what WILL HAPPEN, in the app's own voice.
        assert "install" in words and "colima" in words


def test_a_slow_docker_is_starting_not_missing(monkeypatch):
    """`docker info` against a daemon that is waking up can time out, and
    reporting that as "not installed" would send the user to reinstall
    something they already have."""
    import subprocess as sp
    # The client has to be found for the probe to run at all - without this
    # the answer is "absent" before subprocess is reached, which is what the
    # macOS CI runner (no docker installed) actually returned.
    monkeypatch.setattr(emulate_tab, "docker_cli",
                        lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(emulate_tab.subprocess, "run",
                        _fake_run(raises=sp.TimeoutExpired("docker", 12)))
    assert emulate_tab.docker_state() == "stopped"


def test_the_docker_button_is_macos_only(tmp_path):
    """Windows reaches Linux through WSL and Linux is already Linux, so a
    Docker button there is a control that cannot do anything."""
    root, panel = _panel(tmp_path)
    try:
        import sys
        if sys.platform != "darwin":
            assert not panel._docker_btn.winfo_ismapped()
    finally:
        root.destroy()


def _quiesce(panel):
    """Stop the panel's own background probing before driving it by hand.

    ON MACOS THE TAB PROBES DOCKER FOR REAL at build time, and its drain
    callback runs inside any root.update() — so a test that sets a state and
    then pumps the event loop has its state overwritten by the live answer.
    That is not hypothetical: it passed on Windows and Linux, where the darwin
    branch never runs, and failed only on the macOS CI runner.
    """
    panel._on_destroy(None)          # sets _stopped; drain and poll return early
    panel._docker_busy = False
    panel._docker_result = None


def _bare_mac(monkeypatch):
    """A Mac with no package manager at all, so “Set up emulator…” has nothing
    to install and the Docker button is the one that packs.

    Pinned rather than assumed: every macOS CI runner ships Homebrew, so
    engine_setup_plan() answers there and the two buttons swap places.  Which
    button appears for which machine is its own test below; these are about
    the notice packing and unpacking at all."""
    monkeypatch.setattr(emulate_tab, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_tab, "which_tool",
                        lambda name, dirs=None: None)


def test_a_ready_docker_leaves_no_notice_behind(tmp_path, monkeypatch):
    """The button and the message pack themselves only when there is something
    to say.  A Mac with Docker running should look like every other machine."""
    root, panel = _panel(tmp_path)
    _quiesce(panel)
    _bare_mac(monkeypatch)
    try:
        panel._docker_apply("absent")
        root.update()
        assert panel._docker_btn.winfo_ismapped()
        assert "required" in panel._docker_msg.cget("text")
        panel._docker_apply("stopped")
        root.update()
        assert "not running" in panel._docker_msg.cget("text")
        assert panel._docker_btn.cget("text") == "Start Docker"
        panel._docker_apply("ok")
        root.update()
        assert not panel._docker_btn.winfo_ismapped()
        assert not panel._docker_msg.winfo_ismapped()
    finally:
        root.destroy()


def _macports_mac(monkeypatch):
    """A Mac with MacPorts and nothing else docker-ish: the reporter's."""
    monkeypatch.setattr(emulate_tab, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_tab, "which_tool",
                        lambda name, dirs=None: ("/opt/local/bin/port"
                                                 if name == "port" else None))


def test_the_engineless_notice_says_what_is_there_and_what_is_missing(
        tmp_path, monkeypatch):
    """★ PAD-74.  The reporter's Mac was told "Docker Desktop is required"
    with /opt/local/bin/docker installed, so the notice names the command it
    found - and names the thing that is actually missing, which is the Linux
    machine behind it and not Docker Desktop.  The button under it is “Set up
    emulator…”, the same one Windows presses, because on both platforms that
    is the button that CHANGES the machine."""
    root, panel = _panel(tmp_path)
    _quiesce(panel)
    _macports_mac(monkeypatch)
    try:
        panel._docker_cli = "/opt/local/bin/docker"
        panel._docker_engine = None
        panel._docker_apply("engineless")
        root.update()
        text = panel._docker_msg.cget("text")
        assert "/opt/local/bin/docker" in text, text
        assert "Set up emulator" in text, text
        assert "Colima" in text and "MacPorts" in text, text
        # The three things it must NOT say to this machine.
        assert "not running" not in text, text
        assert "Docker Desktop is required" not in text, text
        assert "Terminal" not in text, text
        assert panel._setup_btn.winfo_ismapped()
        assert not panel._docker_btn.winfo_ismapped()
    finally:
        root.destroy()


def test_a_mac_with_no_package_manager_is_offered_a_download_not_a_command(
        tmp_path, monkeypatch):
    """There the app cannot do it FOR them, and the honest offer is a page and
    an installer to double-click - never a line to copy into a shell."""
    root, panel = _panel(tmp_path)
    _quiesce(panel)
    monkeypatch.setattr(emulate_tab, "homebrew", lambda: None)
    monkeypatch.setattr(emulate_tab, "which_tool", lambda name, dirs=None: None)
    try:
        panel._docker_cli = "/opt/local/bin/docker"
        panel._docker_engine = None
        panel._docker_apply("engineless")
        root.update()
        text = panel._docker_msg.cget("text")
        assert "download page" in text, text
        assert "Terminal" not in text and "sudo" not in text, text
        assert panel._docker_btn.cget("text") == "Get Docker…"
        assert panel._docker_btn.winfo_ismapped()
        assert not panel._setup_btn.winfo_ismapped()
    finally:
        root.destroy()


def test_the_mac_setup_button_installs_and_starts_it_here(tmp_path,
                                                          monkeypatch):
    """★ David, 2026-08-19.  The button does the work: a package-manager
    install (with macOS's own password dialog when it needs root) and then
    Colima started, both drained into the log pane - no Terminal window and
    nothing for the user to type."""
    import time as _t
    root, panel = _panel(tmp_path)
    _quiesce(panel)
    _macports_mac(monkeypatch)
    ran = []
    monkeypatch.setattr(panel, "_log", lambda *a: None)
    monkeypatch.setattr(panel, "_run_step",
                        lambda label, argv, admin: ran.append((argv, admin))
                        or True)
    monkeypatch.setattr(emulate_tab.messagebox, "askyesno",
                        lambda *a, **kw: True)
    monkeypatch.setattr(panel, "_colima_argv",
                        lambda: ["/opt/local/bin/colima", "start"])
    try:
        panel._docker = "engineless"
        panel._docker_cli = "/opt/local/bin/docker"
        panel._setup_fix_darwin()
        for _ in range(300):                    # the work is on a thread
            if len(ran) == 2:
                break
            _t.sleep(0.01)
        assert ran == [(["/opt/local/bin/port", "-N", "install", "colima"],
                        True),
                       (["/opt/local/bin/colima", "start"], False)], ran
    finally:
        root.destroy()


def test_the_mac_setup_button_changes_nothing_on_a_no(tmp_path, monkeypatch):
    """Same rule as its Windows twin: every step is named first, and a No
    leaves the machine exactly as it was."""
    import time as _t
    root, panel = _panel(tmp_path)
    _quiesce(panel)
    _macports_mac(monkeypatch)
    ran = []
    monkeypatch.setattr(panel, "_run_step", lambda *a: ran.append(a) or True)
    monkeypatch.setattr(emulate_tab.messagebox, "askyesno",
                        lambda *a, **kw: False)
    try:
        panel._docker_cli = "/opt/local/bin/docker"
        panel._setup_fix_darwin()
        _t.sleep(0.05)
        assert not ran, ran
        assert not panel._setup_fixing
    finally:
        root.destroy()


def test_start_docker_starts_the_engine_this_mac_actually_has(tmp_path,
                                                              monkeypatch):
    """`open -a Docker` was the only thing the button could do, on a platform
    where the engine is as likely to be Colima - and on a Mac without Docker
    Desktop it opened nothing while the log said it had started something."""
    root, panel = _panel(tmp_path)
    _quiesce(panel)
    opened, steps = [], []
    monkeypatch.setattr(emulate_tab.subprocess, "Popen",
                        lambda a, *r, **kw: opened.append(a) or SimpleNamespace())
    monkeypatch.setattr(panel, "_run_engine_setup",
                        lambda phases: steps.extend(phases))
    monkeypatch.setattr(panel, "_log", lambda *a: None)
    try:
        panel._docker = "stopped"
        panel._docker_engine = ("Colima", "cli", "/opt/local/bin/colima")
        panel._docker_fix()
        # Run HERE, into the log pane - not handed to Terminal to watch.
        assert [p[1] for p in steps] == [["/opt/local/bin/colima", "start"]]
        assert not opened, opened
        # An .app is opened, by its own path - OrbStack is not "Docker".
        steps[:] = []
        panel._docker_engine = ("OrbStack", "app", "/Applications/OrbStack.app")
        panel._docker_fix()
        assert opened == [["open", "-a", "/Applications/OrbStack.app"]], opened
        assert not steps, steps
    finally:
        root.destroy()


def test_start_on_a_mac_without_docker_launches_nothing(tmp_path, monkeypatch):
    """It used to launch, say "Starting…", and report the real reason as one
    line of the container script's stderr part way down the log pane."""
    import time
    img = tmp_path / "godzilla_pro-1_15_0.Release.8G.sdcard.raw"
    img.write_bytes(bytes(16))
    root, panel = _panel(tmp_path)
    # The status poll goes through the container too, so silence it: this test
    # is about what Start does, and a poll firing into a faked Popen is noise
    # from a thread nobody is waiting on.
    panel._on_destroy(None)
    launched = []
    monkeypatch.setattr(emulate_tab.sys, "platform", "darwin")
    monkeypatch.setattr(emulate_tab, "docker_state", lambda: "absent")
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    monkeypatch.setattr(emulate_tab.subprocess, "Popen",
                        lambda *a, **kw: launched.append(a) or SimpleNamespace())
    try:
        panel._src_path.set(str(img))
        panel.start()
        deadline = time.time() + 5
        while panel._starting and time.time() < deadline:
            time.sleep(0.01)
        root.update()
        # Only watch.sh: subprocess.run() goes through Popen too, so the status
        # poll lands in the same list.
        watch = [c for c in launched if any("watch.sh" in str(a) for a in c)]
        assert not watch, "watch.sh was started with no Docker to run it in"
        # What lands ON THE TAB is checked by _docker_apply's own test instead:
        # the worker hands its answer back through `after`, and `after` from a
        # non-main thread needs a running mainloop, which this fixture has not
        # got.  Asserting it here would test the fixture, not the panel.
        assert not panel._starting
    finally:
        root.destroy()


def test_start_builds_the_launch_off_the_ui_thread(tmp_path, monkeypatch):
    """watch_cmd() asks WSL for the desktop user's home (wsl_home: two
    wsl.exe probes), and the first wsl.exe after a Windows reboot boots the
    whole WSL VM — tens of seconds.  start() used to build the command on
    the main thread, which was the window frozen solid for that boot
    (David, 2026-08-09, read it as a crashed app).  The boot is simulated
    with an Event rather than a reboot."""
    import threading as _th
    import time
    img = tmp_path / "godzilla_pro-1_15_0.Release.8G.sdcard.raw"
    img.write_bytes(bytes(16))
    root, panel = _panel(tmp_path)
    panel._on_destroy(None)              # silence the status poll
    boot = _th.Event()                   # a cold WSL boot, in miniature
    built = {}

    def cold_watch_cmd(minutes, env, savestates=True):
        built["thread"] = _th.current_thread()
        boot.wait(10)
        return ["watch.sh-stand-in"]

    launched = []
    monkeypatch.setattr(emulate_tab, "watch_cmd", cold_watch_cmd)
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    # Pinned so a macOS runner's Start worker does not go asking a real
    # Docker before it ever reaches watch_cmd.
    monkeypatch.setattr(emulate_tab, "docker_state", lambda: "ok")
    monkeypatch.setattr(
        emulate_tab.subprocess, "Popen",
        lambda *a, **kw: launched.append(a[0]) or
        SimpleNamespace(stdout=iter(()), wait=lambda timeout=None: 0))
    try:
        panel._src_path.set(str(img))
        # Item 74: picking a card fires ONE `cardmount.sh --precache` spawn —
        # from a worker thread, because the card-path stat must stay off the
        # UI thread (a UNC path to a sleeping NAS blocks for seconds).  It is
        # not a launch, so it comes off the ledger before Start is policed.
        # macOS is the one platform _precache_kick deliberately skips (the
        # rig lives in a container there and the card's host path is not
        # the container's — see its own docstring), so nothing to wait for
        # on that platform: this branch is what a real macOS CI run needs,
        # not a hypothetical (found 2026-08-24 when v0.160.0's release CI
        # failed here — the assertion below had never been exercised on
        # Darwin at all).
        if sys.platform == "darwin":
            time.sleep(0.2)
            assert not launched, "macOS must not pre-cache (see _precache_kick)"
        else:
            deadline = time.time() + 5
            while not launched and time.time() < deadline:
                time.sleep(0.01)
            assert launched and launched[0][-1] == "--precache", \
                "picking a card should start the background pre-cache"
        launched.clear()
        panel.start()        # must come back with the "boot" still running
        assert not launched, "start() sat through the WSL boot on the UI thread"
        boot.set()
        deadline = time.time() + 5
        while not launched and time.time() < deadline:
            time.sleep(0.01)
        assert launched and launched[0] == ["watch.sh-stand-in"]
        assert built["thread"] is not _th.main_thread(), \
            "the launch command was built on the UI thread"
    finally:
        boot.set()
        root.destroy()


def test_a_cold_wsl_says_so_instead_of_freezing(tmp_path, monkeypatch):
    """The build-time setup probe is one wsl.exe call, and after a Windows
    reboot that call boots the whole WSL VM.  The tab used to show a dash
    and say nothing for the duration; now it names the wait and its bound.
    A warm probe answers inside one drain pass, so the line never flashes
    on an ordinary start."""
    import threading as _th
    import time
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    boot = _th.Event()
    monkeypatch.setattr(emulate_tab, "setup_state",
                        lambda: (boot.wait(10), None)[1])
    root, panel = _panel(tmp_path)
    # AFTER the build (so the tab came up normally): keep the 2 s status poll
    # from reaching a real wsl.exe once the gate opens, and from writing over
    # the state row this test is reading.
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: False)
    try:
        deadline = time.time() + 5
        while ("take a minute" not in panel._hint.cget("text")
               and time.time() < deadline):
            root.update()
            time.sleep(0.02)
        assert "Starting WSL" in panel._vals["state"].cget("text")
        assert "take a minute" in panel._hint.cget("text")
        # And nothing has claimed "Not running" over it: the poll is gated
        # behind this very probe.
        boot.set()
        deadline = time.time() + 5
        while ("take a minute" in panel._hint.cget("text")
               and time.time() < deadline):
            root.update()
            time.sleep(0.02)
        assert "take a minute" not in panel._hint.cget("text")
        assert panel._vals["state"].cget("text") == "—"
    finally:
        boot.set()
        root.destroy()


def test_polls_do_not_stack_behind_a_booting_wsl(tmp_path, monkeypatch):
    """Each status poll is a wsl.exe worker with a 20 s timeout.  While the
    setup probe is still out (= WSL may be booting), a poll every 2 s just
    queues more of them behind the boot, and the first one back would time
    out empty and write "Not running" over the honest "Starting WSL" line -
    a claim about a machine nobody has seen yet."""
    import time
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    root, panel = _panel(tmp_path)
    ran = []
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    monkeypatch.setattr(
        emulate_tab.subprocess, "run",
        lambda *a, **kw: ran.append(a[0]) or
        SimpleNamespace(stdout=b"", returncode=0))
    try:
        panel._setup_busy = True
        panel._poll()
        time.sleep(0.2)
        root.update()
        assert not ran, "a status poll went out while WSL was still booting"
        panel._setup_busy = False
        panel._poll()
        deadline = time.time() + 5
        while not ran and time.time() < deadline:
            time.sleep(0.01)
        assert any("status.sh" in " ".join(map(str, c)) for c in ran)
    finally:
        root.destroy()


def test_the_docker_probe_survives_having_no_mainloop_yet(tmp_path,
                                                          monkeypatch):
    """The first probe runs at tab BUILD time, before root.mainloop().  A
    worker calling `after` then raises "main thread is not in main loop" and
    the answer vanishes, so the worker leaves it in a field and the main loop
    collects it."""
    import time
    # Patched BEFORE the panel is built, so the build-time probe IS the fake
    # one.  Patching afterwards left the real probe in flight: its answer and
    # the test's raced, and on a runner with no Docker the real one won.  This
    # way every platform exercises the darwin path instead of only macOS CI.
    monkeypatch.setattr(emulate_tab.sys, "platform", "darwin")
    monkeypatch.setattr(emulate_tab, "docker_state", lambda: "stopped")
    root, panel = _panel(tmp_path)
    try:
        deadline = time.time() + 5
        while panel._docker != "stopped" and time.time() < deadline:
            root.update()               # stands in for the mainloop
            time.sleep(0.01)
        assert panel._docker == "stopped"
        assert panel._docker_btn.cget("text") == "Start Docker"
    finally:
        root.destroy()


# ----------------------------------------------------------------------
# The setup check: what this machine still needs before it can emulate.
#
# The fault these are about reached a user on 2026-08-07 as
#
#     chroot: failed to run command '/bin/sh': Exec format error
#
# arriving in the log pane after Start had said "Starting…", on a machine
# that had never had qemu-user-static.  It is the one of the rig's four
# guest-exec faults that the rig cannot repair by itself, so the app has to
# - and the wording is what a user acts on, which is why it is tested.
# ----------------------------------------------------------------------

_READY = {"qemu": "1", "armgcc": "1", "nativecc": "1", "debugfs": "1",
          "fuse": "1", "ffmpeg": "1", "binfmt": "1", "iswsl": "1",
          "wslconf": "1"}


def _facts(**over):
    f = dict(_READY)
    f.update(over)
    return f


def test_a_ready_machine_is_told_nothing():
    assert setup_ok(_facts())
    assert setup_notice(_facts(), can_fix=True) == ""


def test_a_machine_we_could_not_ask_is_not_accused():
    """setup_state returns None for a PC with no WSL and for a probe that
    timed out.  Neither is evidence of a fault, and a prerequisite notice in
    front of someone whose machine is fine is worse than none at all."""
    assert setup_ok(None)
    assert setup_notice(None, can_fix=True) == ""
    assert setup_summary(None) == ([], "1")


def test_summary_lists_only_what_is_actually_missing():
    missing, binfmt = setup_summary(_facts(qemu="0", fuse="0", binfmt="0"))
    assert [pkg for pkg, _ in missing] == ["qemu-user-static", "fuse3"]
    assert binfmt == "0"


def test_the_arm_handler_leads_because_it_is_what_stops_the_run():
    """Ralf's machine: no qemu-user-static and no registration.  The headline
    has to be the thing that would kill the run, not a package list."""
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="0"),
                        can_fix=True)
    assert "cannot run the emulator yet" in text
    handler = text.index("32-bit ARM")
    packages = text.index("qemu-user-static")
    assert handler < packages, "the package list must not bury the cause"
    # And it must say what it will do about it, since it can.
    assert "Set up emulator" in text


def test_every_missing_package_says_what_it_is_for():
    text = setup_notice(_facts(qemu="0", armgcc="0", debugfs="0", fuse="0"),
                        can_fix=True)
    for pkg in ("qemu-user-static", "gcc-arm-linux-gnueabihf", "e2fsprogs",
                "fuse3"):
        assert pkg in text
    assert "32-bit ARM game binary" in text
    assert "without extracting" in text


# ----------------------------------------------------------------------
# THE RIG COMPILES TWO THINGS AND THE TAB ONLY ASKED ABOUT ONE OF THEM.
# The hardware shim is ARM and cross compiled; padglhost, the renderer that
# draws the picture, is native.  A user on 2026-08-08 had the cross compiler,
# watched the shim build in his log, and thirty seconds into the run met
#
#     [build] the GL renderer is not built, and there is no gcc here
#     [build] to build it. It is a NATIVE binary - install gcc ...
#
# The tab had said nothing before Start, because nothing here knew the native
# compiler was a prerequisite at all.
# ----------------------------------------------------------------------

def test_the_native_compiler_is_a_prerequisite_in_its_own_right():
    """Having the ARM cross compiler says nothing about having gcc, which is
    exactly the machine that reported this."""
    facts = _facts(nativecc="0")
    assert not setup_ok(facts)
    missing, _binfmt = setup_summary(facts)
    assert [pkg for pkg, _ in missing] == ["gcc libc6-dev"]
    text = setup_notice(facts, can_fix=True)
    assert "gcc libc6-dev" in text
    # ...and said in terms of what it costs the user, not of a compiler.
    assert "picture" in text


def test_the_headers_are_named_beside_the_compiler():
    """gcc only RECOMMENDS libc6-dev, so `apt install gcc` on a slim WSL is a
    compiler with no headers - and padglhost.c opens with #include <stdio.h>.
    The JJP hooks learned this already; naming only gcc here would have sent
    the same user round again."""
    text = setup_notice(_facts(nativecc="0", binfmt="1"), can_fix=False)
    assert "sudo apt install gcc libc6-dev" in text


def test_a_rig_that_never_heard_of_the_native_compiler_accuses_nobody():
    """An older rig emits no `nativecc` line at all, and an absent fact is not
    a missing package - the same direction everything else here takes."""
    older = dict(_READY)
    del older["nativecc"]
    assert setup_ok(older)
    assert setup_notice(older, can_fix=True) == ""


# ----------------------------------------------------------------------
# AND THE DECODER, WHICH IS THE SAME OMISSION WITH A WORSE SYMPTOM.
# Every other prerequisite here builds or mounts something, so missing one
# ENDS the run and names itself in the log.  Missing ffmpeg ends nothing: the
# guest boots, the shim loads, the renderer opens a 1360x768 window and holds
# 59 fps - and the window is black and silent, because the game decodes
# neither its video nor its audio itself.  A user on 2026-08-08 (PAD-49) ran
# exactly that, with a log repeating
#
#     ch0 decode failed: [Errno 2] No such file or directory: 'ffmpeg'
#
# a hundred times a second, while the tab said nothing before Start and the
# prerequisite strip said "All prerequisites OK" - that strip's ffmpeg is the
# WINDOWS one, which the app bundles, and this one is Linux's.
# ----------------------------------------------------------------------

def test_the_decoder_is_a_prerequisite_in_its_own_right():
    """A machine that passes every other line here is precisely the machine
    that reported this."""
    facts = _facts(ffmpeg="0")
    assert not setup_ok(facts)
    missing, binfmt = setup_summary(facts)
    assert [pkg for pkg, _ in missing] == ["ffmpeg"]
    # Nothing else about that machine was wrong, so nothing else may be said.
    assert binfmt == "1"


def test_the_decoder_is_explained_by_what_its_absence_costs():
    """"ffmpeg" means nothing to the person this is written for; a black
    screen is the thing he actually has, and the notice has to join the two -
    the same standard the native compiler's line is held to ("picture")."""
    text = setup_notice(_facts(ffmpeg="0"), can_fix=True)
    assert "ffmpeg" in text
    assert "video" in text and "sound" in text
    assert "Set up emulator" in text


def test_the_decoder_can_be_the_only_thing_wrong():
    """It has to survive being the WHOLE fault.  Every earlier prerequisite
    fails alongside a dead run, so a notice listing one package and no
    stopped-run headline is a shape this had never had to produce."""
    text = setup_notice(_facts(ffmpeg="0"), can_fix=False)
    assert "sudo apt install ffmpeg" in text
    # ...and it must not invent a second fault to explain itself with.
    assert "32-bit ARM" not in text


def test_the_button_promises_only_what_it_is_going_to_do():
    """The summary sentence used to say "installs those in WSL and registers
    the handler" whatever was wrong, which was safe only because every
    prerequisite before this one turned up on machines that also had no
    handler registered.  The decoder is the first that arrives ALONE, and the
    machine that reported it had its handler already - so that sentence
    promised it an act that was not going to happen."""
    only_pkg = setup_notice(_facts(ffmpeg="0"), can_fix=True)
    assert "installs those in WSL" in only_pkg
    assert "registers the handler" not in only_pkg
    # ...and the converse still says it, since then it IS going to.
    both = setup_notice(_facts(ffmpeg="0", binfmt="0"), can_fix=True)
    assert "installs those in WSL and registers the handler" in both
    # A handler that is merely switched off is a different act, which the
    # consent list has distinguished since it was written.
    off = setup_notice(_facts(binfmt="disabled"), can_fix=True)
    assert "switches the 32-bit ARM handler back on" in off
    assert "installs those in WSL" not in off


def test_a_rig_that_never_heard_of_the_decoder_accuses_nobody():
    """An older rig emits no `ffmpeg` line, and silence is not a missing
    package - the direction every fact here takes."""
    older = dict(_READY)
    del older["ffmpeg"]
    assert setup_ok(older)
    assert setup_notice(older, can_fix=True) == ""


# ----------------------------------------------------------------------
# AND THE ONE THAT IS NOT ABOUT STARTING AT ALL (PAD-53).
#
# v0.126.0 made every Start a checkpointable (PAD_PIVOT) boot so the save-state
# controls could simply be on.  That boot needs a native static busybox, which
# no machine has by default and which was on no prerequisite list anywhere -
# and run_game.sh's answer to a pivot it cannot do was to stop.  A user on
# 2026-08-11 ran star_wars_le and iron_maiden_pro, both of which had worked
# before, and got no window at all:
#
#     [run] PAD_PIVOT needs a STATIC busybox at /bin/busybox
#     [watch] the game never started.
#
# watch.sh now withdraws the request and boots the ordinary way, so the cost is
# the FEATURE.  Which is why this package is not in _SETUP_TOOLS: a machine
# missing it runs the emulator perfectly, and "this PC cannot run the emulator"
# in front of it would be the same false accusation every other rule here
# guards against.
# ----------------------------------------------------------------------

def test_the_save_state_package_does_not_stop_the_emulator():
    facts = _facts(busybox="0")
    assert setup_ok(facts), "a missing extra must not read as a dead emulator"
    assert not setup_settled(facts), "...but there IS something to say"
    assert [pkg for pkg, _ in setup_extras(facts)] == ["busybox-static"]
    # It is not in the list that decides whether a run can start.
    assert setup_summary(facts)[0] == []


def test_the_notice_leads_with_the_emulator_working():
    """The headline is the difference between a true notice and a false one:
    this machine runs every title, and telling its owner it cannot is how a
    correct warning turns into a wrong one."""
    text = setup_notice(_facts(busybox="0"), can_fix=True)
    assert "cannot run the emulator" not in text
    assert "The emulator runs on this PC" in text
    assert "Save states need" in text
    assert "busybox-static" in text
    # ...and it must not invent a second fault to explain itself with.
    assert "32-bit ARM" not in text


def test_the_button_offers_to_install_the_save_state_package():
    """The button lives UNDER this notice.  Hiding the notice on a machine
    that only misses an extra would have left nothing to press, and the
    package invisible."""
    text = setup_notice(_facts(busybox="0"), can_fix=True)
    assert "installs those in WSL" in text
    steps = emulate_tab.setup_fix_steps(_facts(busybox="0"))
    assert any("busybox-static" in s for s in steps), (
        "the consent list must name what the button is about to install")


def test_linux_asks_for_it_at_the_command_line_like_everything_else():
    text = setup_notice(_facts(busybox="0", iswsl="1"), can_fix=False)
    assert "sudo apt install busybox-static" in text


def test_a_linux_desktop_is_not_told_about_a_windows_only_shape():
    """watch_cmd asks for the checkpointable boot on Windows and nowhere else,
    so a Linux Start never wants a static busybox - and a package a machine's
    runs would never use is not a prerequisite of that machine."""
    facts = _facts(busybox="0", iswsl="0", wslconf="1")
    assert setup_extras(facts) == []
    assert setup_settled(facts)
    assert setup_notice(facts, can_fix=False) == ""


def test_a_rig_that_never_heard_of_the_save_state_package_accuses_nobody():
    """An older setupcheck.sh emits no `busybox` line at all - the same
    direction every other fact here takes."""
    assert setup_extras(_facts()) == []
    assert setup_settled(_facts())
    assert setup_notice(_facts(), can_fix=True) == ""


def test_an_uninstallable_extra_does_not_ask_for_a_new_linux():
    """"Replace your distro" is the answer to an emulator that cannot run.
    Answering a switched-off feature with it would be wildly out of
    proportion - and the machine saying so runs every title today."""
    facts = _facts(busybox="0", nocand="busybox-static", universe="1",
                   indexed="1")
    text = setup_notice(facts, can_fix=True)
    assert "wsl --install" not in text
    assert "save states stay off" in text
    assert "titles start and run exactly as they do now" in text


def test_the_run_says_it_once_when_the_decoder_is_missing_anyway():
    """THE BACKSTOP, for a run started outside this tab.

    Nothing in watch.sh FAILS to start without ffmpeg - padvidhost.py creates
    its mmap either way, so "video: host decoder up" gets printed by a decoder
    that cannot decode a thing.  The check has to come before the helpers, and
    it has to hand the guest the existing no-bridge path: left pointed at a
    bridge that can never fill, the game re-arms the same clip forever and
    blocks on every one of them, which is the hundred-lines-a-second log."""
    watch = _rig_text("watch.sh")
    body = "\n".join(ln for ln in watch.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "command -v ffmpeg" in body, (
        "watch.sh starts the decode helpers without ever asking for ffmpeg")
    # Against where they are STARTED, not merely named: both are named far
    # above this, in the teardown's pkill list.
    at = body.index("command -v ffmpeg")
    for launch in ('setsid_as_user bash "$S/playaudio.sh"',
                   'setsid_as_user python3 "$S/padvidhost.py"'):
        assert launch in body, "watch.sh no longer starts it this way"
        assert at < body.index(launch), (
            "the check must come before the helper it is about")
    assert "export PAD_VID=0" in body


def test_a_registered_but_disabled_handler_is_not_called_missing():
    """Different fault, different repair: it is registered, so nothing needs
    installing and telling the user to install something would be wrong."""
    text = setup_notice(_facts(binfmt="disabled"), can_fix=True)
    assert "switched" in text.lower()
    assert "Missing" not in text
    assert not setup_ok(_facts(binfmt="disabled"))


def test_without_a_fixer_the_user_gets_the_rig_s_own_command():
    """On a Linux desktop the app cannot get root without a password prompt it
    has nowhere to show, so it prints - and it prints the command THIS machine
    wants, which the rig derived (Ubuntu 24.04 and Debian differ)."""
    advice = "sudo sh -c 'cat /usr/lib/binfmt.d/qemu-arm.conf > /proc/sys/fs/binfmt_misc/register'"
    text = setup_notice(_facts(binfmt="0", advice=advice), can_fix=False)
    assert advice in text
    assert "Set up emulator" not in text


def test_missing_packages_are_named_as_one_apt_line_not_four():
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="1"),
                        can_fix=False)
    assert "sudo apt install qemu-user-static gcc-arm-linux-gnueabihf" in text


def test_probe_failure_is_none_rather_than_a_wrong_answer(monkeypatch):
    """A probe that cannot run must not read as "everything is missing"."""
    def boom(*a, **kw):
        raise FileNotFoundError("wsl.exe")
    monkeypatch.setattr(emulate_tab.subprocess, "run", boom)
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    assert setup_state() is None


def test_probe_reads_the_rig_s_key_value_output(monkeypatch):
    out = (b"qemu=0\nbinfmt=0\n"
           b"advice=sudo apt install qemu-user-static\n")
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setattr(emulate_tab.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=0,
                                                         stdout=out))
    facts = setup_state()
    assert facts["qemu"] == "0"
    # The advice is a whole command with '=' nowhere but the first split.
    assert facts["advice"] == "sudo apt install qemu-user-static"


def test_root_commands_are_wsl_only_and_actually_ask_for_root(monkeypatch):
    """The no-root rule the rig follows is a LINUX fact.  `wsl -u root` is uid
    0 with no password, which is why the Windows path may repair and the Linux
    one may only advise - so this must never quietly produce a non-root
    command on a platform where root is not free."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    cmd = rig_cmd_root("setupfix.sh")
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]
    assert cmd[-1].endswith("/setupfix.sh")
    for plat in ("linux", "darwin"):
        monkeypatch.setattr(emulate_tab.sys, "platform", plat)
        with pytest.raises(RuntimeError):
            rig_cmd_root("setupfix.sh")


# ---- the rig side, checked as text: these are the two ways the pair can
# ---- silently stop agreeing with each other.

def _rig_text(name):
    return (pathlib.Path(DEFAULT_RIG_DIR) / name).read_text(encoding="utf-8")


def test_the_repair_installs_exactly_the_packages_the_tab_names():
    """The tab explains five packages and the rig installs them.  Two lists in
    two languages is precisely how they drift.

    The rig's copy lives in setupcheck.sh, which probes the tool and knows the
    package that carries it; setupfix.sh installs whatever that reports as
    missing rather than keeping a third list.

    Commas are how the rig's whitespace-split list spells a fact that needs
    more than one package (gcc,libc6-dev); the tab spells the same thing with
    a space, and this is the seam where those two have to mean the same."""
    check = _rig_text("setupcheck.sh").replace(",", " ")
    fix = _rig_text("setupfix.sh")
    # The optional ones are installed by the same button off the same `need`
    # list, so they are held to the same seam - EXCEPT the ones apt cannot
    # supply at all, which is what the fourth field says.  criu is on no
    # Ubuntu, so its seam is with getcriu.sh instead, and its package field in
    # setupcheck.sh is `-` precisely so it never reaches `need`.
    rows = ([t + ("apt",) for t in emulate_tab._SETUP_TOOLS]
            + list(emulate_tab._SETUP_OPTIONAL))
    for key, pkg, _why, how in rows:
        assert 'sudo' not in pkg
        assert "%s:" % key in check
        if how == "apt":
            assert pkg in check, "%s (%s) is explained but never installed" % (
                pkg, key)
        else:
            assert "%s:@" % key in check and ":-:" in check, (
                "%s must not be handed to apt-get, which has no such package"
                % pkg)
            assert "getcriu.sh" in fix, (
                "%s is explained but nothing gets it" % pkg)
    assert '_get "$facts" need' in fix


def test_the_repair_keeps_no_list_of_its_own_to_prove_itself_with():
    """setupfix.sh's LAST act is to re-probe and declare the machine fixed, and
    it used to do that by naming the four fact keys one per line - a third copy
    of the list, on the success path, where nobody would think to look.  Adding
    a fifth prerequisite would have left it announcing "result=ok" on a machine
    that still could not build the renderer.

    `need` is emitted by the same loop that emits the keys, so the proof is
    about whatever setupcheck probes today."""
    fix = _rig_text("setupfix.sh")
    proof = fix.split("# ---- 4.")[-1]
    assert '-z "$(_get "$facts" need)"' in proof
    for key, _pkg, _why in emulate_tab._SETUP_TOOLS:
        assert '_get "$facts" %s' % key not in proof, (
            "setupfix.sh is naming %s itself again" % key)


def test_the_repair_does_not_hide_apt_failure_behind_a_pipe():
    """`apt-get ... | sed` reports SED's exit status, so a failed install
    reads as a clean one and the tab would announce success."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if "apt-get install" in line or "apt-get update" in line:
            assert "| sed" not in line, line


# ----------------------------------------------------------------------
# "Missing" and "installable" are two different facts, and the tab used to
# know only the first.  A tester on 2026-08-07 was told qemu-user-static was
# missing, pressed the button that installs it, and got
#
#     E: Package 'qemu-user-static' has no installation candidate
#
# twice - because Ubuntu publishes it in `universe` and his WSL had that
# component switched off.  gcc-arm-linux-gnueabihf, named in the same apt
# command and sitting in `main`, was installable and was NOT installed either:
# `apt-get install a b` is all or nothing.
# ----------------------------------------------------------------------

def test_a_package_apt_cannot_install_is_not_just_called_missing():
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="0",
                               nocand="qemu-user-static", universe="0"),
                        can_fix=True)
    assert "universe" in text
    assert "switched off" in text
    # and the button must promise the extra step it is now going to take
    assert "turns universe back on" in text


def test_an_unavailable_package_with_no_known_cause_still_says_so():
    """Not every "no installation candidate" is universe - an out-of-support
    distro does it too.  Naming a cause we have not established would be a
    guess, but saying nothing sends the user back to the same button."""
    text = setup_notice(_facts(qemu="0", binfmt="1",
                               nocand="qemu-user-static", universe="1"),
                        can_fix=True)
    assert "do not offer it" in text
    assert "universe" not in text


def test_the_printed_commands_lead_with_the_one_that_makes_the_rest_work():
    """On Linux the app can only advise, and `sudo apt install
    qemu-user-static` is advice that FAILS on this machine until universe is
    on.  Order is the whole content here."""
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="0",
                               nocand="qemu-user-static", universe="0"),
                        can_fix=False)
    assert text.index("add-apt-repository universe") < text.index("apt install")


def test_a_rig_that_never_heard_of_nocand_accuses_nobody():
    """The fact is new.  An older setupcheck.sh, or a probe that timed out,
    must read as "nothing known against them" and not as "none of them can be
    installed"."""
    assert emulate_tab.setup_unavailable(_facts(qemu="0")) == []
    assert emulate_tab.setup_unavailable(None) == []
    assert "cannot install" not in setup_notice(_facts(qemu="0", binfmt="0"),
                                                can_fix=True)


def test_the_repair_installs_one_package_at_a_time():
    """`apt-get install a b` is all or nothing: one package this machine's
    sources do not carry means NONE of the others get installed, which is how
    a user missing four things ends up with four things still missing."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if line.lstrip().startswith("#"):
            continue                    # the comment explaining exactly this
        if "apt-get install" in line:
            assert '"$pkg"' in line, line
            assert "$pkgs" not in line, line


def test_the_repair_only_edits_the_distro_s_own_sources():
    """Appending `universe` to a PPA line turns a working repository into a
    404 on every apt-get update.  The in-place edit is allowed exactly two
    files, and within them only ubuntu.com archive lines."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if line.strip().startswith("for f in"):
            assert line.count("/etc/apt/") == 2, line
            assert "sources.list.d/*" not in line, line
    assert r"ubuntu\.com" in fix


# ----------------------------------------------------------------------
# PAD-42.  The SAME tester, one release on, and both halves of "apt has no
# installation candidate" were still wrong.
#
#   * His machine: a current Ubuntu, universe ON, whose archive had installed
#     twenty-one packages seconds earlier - and the app told him his distro
#     was out of support or its sources trimmed, and that installing a current
#     Ubuntu was the way back.  Two causes nothing had checked, and the advice
#     was the thing he had already done.  The button stayed on offer, under a
#     sentence saying the package could not be installed, and he pressed it
#     twice.
#
#   * Every OTHER machine: `nocand` and `universe` are both read out of apt's
#     DOWNLOADED metadata, and a WSL Ubuntu that has never run `apt-get
#     update` has none.  `apt-cache policy` prints nothing for a package that
#     is not installed, `apt-get indextargets` prints nothing at all - so a
#     brand-new distro, where all four packages install perfectly, was told
#     its sources offered none of them and that universe was switched off.
#     Reproduced in WSL with APT_CONFIG pointing at an empty lists dir.
# ----------------------------------------------------------------------

#: Jim-Beam's machine as the fixed probe describes it: a release that does not
#: publish qemu-user-static, which the rig is willing to go and fetch.
_NOCAND = dict(qemu="0", armgcc="1", debugfs="1", fuse="1", binfmt="0",
               nocand="qemu-user-static", xrel="qemu-user-static",
               universe="1", indexed="1",
               components="main restricted universe multiverse",
               distro="ubuntu 26.10 resolute")

#: The same shape, for a package the rig will NOT cross-install: an ordinary
#: dynamically linked one whose dependencies belong to its own release.
_NOCAND_HARD = dict(_NOCAND, qemu="1", armgcc="0", binfmt="1",
                    nocand="gcc-arm-linux-gnueabihf", xrel="")


def test_the_release_that_lacks_the_package_is_named_not_guessed_at():
    """"Out of support" and "sources have been trimmed" were both guesses,
    and both wrong about the machine that met them.  What setupcheck.sh can
    actually report is the release and the components apt has on."""
    text = setup_notice(_facts(**_NOCAND), can_fix=True)
    assert "ubuntu 26.10 resolute" in text
    assert "universe” switched on" in text
    assert "does not publish it" in text
    for guess in ("out of support", "trimmed", "latest version"):
        assert guess not in text


def test_the_app_fetches_the_package_rather_than_telling_him_to_move_distro():
    """THE POINT OF PAD-42.  qemu-user-static depends on nothing, so a .deb
    from an Ubuntu that publishes it installs cleanly on one that does not -
    and the app doing that beats the app printing two wsl commands."""
    facts = _facts(**_NOCAND)
    assert emulate_tab.setup_fetchable(facts) == ["qemu-user-static"]
    assert emulate_tab.setup_fixable(facts), "the button can still do this"
    text = setup_notice(facts, can_fix=True)
    assert "Ubuntu %s's archive" % emulate_tab.FALLBACK_RELEASE in text
    assert "depends on nothing" in text
    # ...and it must NOT fall back to telling him to move distro.
    assert "wsl --set-default" not in text


def test_the_fetch_is_named_in_the_dialog_that_consents_to_it():
    """Fetching from another release is not `apt install`, and the dialog is
    the only place the user agrees to any of it."""
    steps = emulate_tab.setup_fix_steps(_facts(**_NOCAND))
    fetch = [s for s in steps if "Ubuntu %s's archive"
             % emulate_tab.FALLBACK_RELEASE in s]
    assert len(fetch) == 1, steps
    assert "depends on nothing" in fetch[0]
    assert "sources are not changed" in fetch[0]
    # and it is not ALSO promised as an ordinary install
    assert not [s for s in steps
                if s.startswith("Install in WSL") and "qemu-user-static" in s]


def test_a_package_that_cannot_be_fetched_still_takes_the_button_away():
    """The fetch is allowed for one package because it depends on nothing.
    Everything else is still a dead end, and must still read like one."""
    facts = _facts(**_NOCAND_HARD)
    assert emulate_tab.setup_fetchable(facts) == []
    assert not emulate_tab.setup_fixable(facts)
    text = setup_notice(facts, can_fix=True)
    assert "installs those in WSL" not in text
    assert "wsl --install -d %s" % emulate_tab.KNOWN_GOOD_DISTRO in text
    assert "wsl --set-default %s" % emulate_tab.KNOWN_GOOD_DISTRO in text


def test_a_rig_that_never_heard_of_xrel_promises_nothing():
    """`xrel` is new.  An older setupcheck.sh must not have its silence read
    as "yes, fetch it" - that would promise a repair that never happens."""
    assert emulate_tab.setup_fetchable(_facts(qemu="0")) == []
    assert emulate_tab.setup_fetchable(None) == []
    old = _facts(**dict(_NOCAND, xrel=None))
    del old["xrel"]
    assert not emulate_tab.setup_fixable(old)


def test_the_button_stays_when_any_of_it_can_still_be_installed():
    """One unavailable package out of two is not a dead end - installing the
    other is still progress, and one at a time is what the rig now does."""
    facts = _facts(qemu="0", armgcc="0", binfmt="0",
                   nocand="qemu-user-static", universe="1", indexed="1")
    assert emulate_tab.setup_fixable(facts)
    assert "installs those in WSL" in setup_notice(facts, can_fix=True)


def test_universe_is_still_the_repair_it_was_made_in_pad_41():
    """The new dead-end path must not swallow the case that HAS a fix."""
    facts = _facts(qemu="0", binfmt="0", nocand="qemu-user-static",
                   universe="0", indexed="1")
    assert emulate_tab.setup_fixable(facts)
    assert "turns universe back on" in setup_notice(facts, can_fix=True)


def test_printed_advice_leaves_out_a_package_apt_has_no_version_of():
    """`apt install a b` is all or nothing, so naming an uninstallable
    package in the printed command installs neither.  That is the PAD-41 bug,
    still living in the advice the app prints on Linux."""
    text = setup_notice(_facts(qemu="0", armgcc="0", binfmt="1",
                               nocand="qemu-user-static", universe="1",
                               indexed="1"), can_fix=False)
    assert "sudo apt install gcc-arm-linux-gnueabihf" in text
    assert "apt install qemu-user-static" not in text


def test_an_empty_apt_index_is_not_evidence_against_the_sources():
    """The probe must not answer either question out of metadata it does not
    have; setupfix.sh's `apt-get update` is what makes them answerable."""
    check = _rig_text("setupcheck.sh")
    assert 'echo "indexed=$indexed"' in check
    # The loop that fills `nocand` must be behind the index gate.
    lines = [ln for ln in check.splitlines() if not ln.lstrip().startswith("#")]
    start = next(i for i, ln in enumerate(lines) if 'if [ -n "$need" ]' in ln)
    cond = " ".join(lines[start:start + 3])
    assert '[ "$indexed" = 1 ]' in cond, \
        "nocand is still computed off an index that may not be there: " + cond
    # ...and universe is judged from what apt reports it has, not re-probed.
    assert "printf '%s\\n' $components | grep -qx universe" in check


def test_the_probe_reports_the_release_it_is_talking_about():
    check = _rig_text("setupcheck.sh")
    for key in ("indexed=", "components=", "distro="):
        assert "echo \"%s" % key in check or "echo %s" % key in check, key


def test_the_repair_stops_naming_causes_it_never_checked():
    fix = _rig_text("setupfix.sh")
    body = "\n".join(ln for ln in fix.splitlines()
                     if not ln.lstrip().startswith("#"))
    for guess in ("out of support", "have been trimmed",
                  "installing a current Ubuntu"):
        assert guess not in body, guess
    # and it says the release instead
    assert '_get "$f" distro' in fix
    assert '_get "$f" components' in fix


def test_an_update_that_failed_is_not_evidence_the_release_lacks_it():
    """"This release does not publish the package" can only be said about an
    index that was actually refreshed.  An unreachable archive looks exactly
    the same from `apt-cache policy`."""
    fix = _rig_text("setupfix.sh")
    assert "updated=1" in fix and "updated=0" in fix
    assert 'if _run apt-get update -qq; then' in fix


def test_the_two_halves_agree_on_the_fallback_release():
    """One release, three spellings: the distro name a user types at wsl.exe,
    the suite apt knows it by, and the version the tab says out loud."""
    fix = _rig_text("setupfix.sh")
    assert "PAD_KNOWN_GOOD_DISTRO=%s" % emulate_tab.KNOWN_GOOD_DISTRO in fix
    assert emulate_tab.FALLBACK_RELEASE == "24.04"
    assert "PAD_FALLBACK_SUITE=noble" in fix


def test_only_a_package_that_depends_on_nothing_is_cross_installed():
    """THE SAFETY PROPERTY.  A .deb from another release drags its dependency
    chain in with it, which is how "the emulator will not start" becomes "apt
    is broken".  qemu-user-static is exempt because its Depends is empty - and
    that is re-read off the DOWNLOADED FILE, so the flag in setupcheck.sh can
    only narrow what is attempted, never widen what is allowed."""
    check = _rig_text("setupcheck.sh")
    flagged = [ln.split(":")[2] for ln in check.splitlines()
               if ln.count(":") == 3 and ln.rstrip().endswith(":1")]
    assert flagged == ["qemu-user-static"], flagged
    fix = _rig_text("setupfix.sh")
    assert "dpkg-deb -f \"$deb\" Depends" in fix
    assert "dpkg-deb -f \"$deb\" Pre-Depends" in fix
    gate = fix.split("dpkg-deb -f \"$deb\" Depends", 1)[1]
    assert gate.index('[ -n "$deps$predeps" ]') < gate.index("dpkg -i"), \
        "the dependency gate must come before the install, not after"


def test_the_fetch_leaves_the_machine_s_package_sources_alone():
    """The sources-editing version of this idea fails open: a cleanup that is
    skipped leaves a foreign repository on the machine, and every apt-get
    upgrade from then on is pulling from the wrong release.  apt is run
    against a throwaway root instead, so there is no cleanup to skip."""
    fix = _rig_text("setupfix.sh")
    body = fix.split("_fetch_foreign() {", 1)[1].split("\n}", 1)[0]
    for override in ("Dir::Etc::sourcelist=", "Dir::Etc::sourceparts=/dev/null",
                     "Dir::State::lists=", "Dir::Cache="):
        assert override in body, override
    assert "/etc/apt" not in body, "the fetch must not touch the real sources"
    assert 'rm -rf "$t"' in body


def test_the_fetch_uses_the_mirror_apt_is_already_configured_with():
    """Someone on a country mirror or on ports.ubuntu.com has that for a
    reason, and the pool is the same on all of them."""
    body = _rig_text("setupfix.sh").split("_fetch_foreign() {", 1)[1]
    assert "REPO_URI" in body.split("\n}", 1)[0]
    assert "ports.ubuntu.com" in body, "no fallback for non-x86 hosts"


def test_the_probe_reuses_the_rig_s_own_binfmt_detection():
    """setupcheck.sh must not grow its own copy of "is there an ARM handler" -
    ensurebuild.sh owns that, and the run itself uses ensurebuild's."""
    check = _rig_text("setupcheck.sh")
    assert "ensurebuild.sh" in check


def test_the_tab_and_the_run_agree_on_what_a_usable_compiler_is():
    """Same rule, and for the same reason: the prediction the tab makes before
    Start and the decision the run makes half a minute later have to be one
    function, or the tab clears a machine the build then refuses.

    `command -v gcc` in either place is the specific way that goes wrong - it
    passes a WSL that has the compiler and none of its headers."""
    check = _rig_text("setupcheck.sh")
    ensure = _rig_text("ensurebuild.sh")
    assert "_pad_cc_works" in ensure, "the run's own test has to be a function"
    assert "@_pad_cc_works" in check, "setupcheck must call it, not re-ask"
    bridge = ensure.split("pad_ensure_bridge() {", 1)[1].split("\n}", 1)[0]
    assert "command -v gcc" not in bridge, (
        "the renderer's guard is back to a PATH lookup")
    assert bridge.count("_pad_cc_works") == 2, (
        "both the missing and the stale branch decide it the same way")
    assert "_pad_binfmt_arm" in check
    assert "_pad_binfmt_advice" in check
    assert "binfmt_misc/qemu-arm" not in check, "that is a second detector"


# ---------------------------------------------------------------------------
# Per-game save-state scoping (item 33 territory, David 2026-08-10: "you
# can't load a venom save state for john wick"). The title is derived from
# the picked card's filename the same way the rig names its card cache:
# everything up to the first dash-digit of the basename.
# ---------------------------------------------------------------------------

def _tab_with_card(path):
    tab = object.__new__(emulate_tab.EmulatePanel)
    tab._src_path = SimpleNamespace(get=lambda: path)
    return tab


def test_card_game_derives_the_title_from_the_filename():
    t = _tab_with_card(r"D:\imgs\star_wars_le-1_30_0.Release.8G.sdcard.raw")
    assert t._card_game() == "star_wars_le"


def test_card_game_survives_suffixed_and_upscaled_names():
    t = _tab_with_card(
        r"C:\x\turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw")
    assert t._card_game() == "turtles_pro"


def test_card_game_is_case_insensitive_and_strips_quotes():
    t = _tab_with_card('  "d:\y\GODZILLA_PRO-1_15_0_spike2.raw"  ')
    assert t._card_game() == "godzilla_pro"


def test_card_game_answers_none_rather_than_guessing():
    assert _tab_with_card("")._card_game() is None
    assert _tab_with_card(r"C:\x\NoVersionShape.raw")._card_game() is None


# ---------------------------------------------------------------------------
# "Reset windows" (item 37, David 2026-08-10: "button on emulate tab to reset
# window positions of emulator to default (in case they are off-screen somehow
# or messed up from multi-monitor setups)").
#
# The rig-side half lives in winreset.sh and is tested by running it; what is
# testable here is the half the app owns - the Windows-side playfield state,
# where the playfield really is a Windows process and no script inside WSL can
# reach its home - plus the gate, because a reset under a live run is written
# straight back by padglhost and would report a success that never happened.
# ---------------------------------------------------------------------------

def _pf_state(monkeypatch, tmp_path, text):
    p = tmp_path / ".pad_playfield.json"
    if text is None:
        if p.exists():
            p.unlink()
    else:
        p.write_text(text)
    monkeypatch.setattr(emulate_tab.EmulatePanel, "PF_STATE", str(p))
    return p


def test_forget_playfield_pos_takes_only_that_key(monkeypatch, tmp_path):
    """Other playfield state survives: taking the whole file would be a
    second, silent reset nobody asked for."""
    import json as _json
    p = _pf_state(monkeypatch, tmp_path,
                  '{"playfield_pos": [-1800, 300], "keep_me": 7}')
    msg = emulate_tab.EmulatePanel._forget_playfield_pos()
    assert msg and "-1800" in msg
    assert _json.loads(p.read_text()) == {"keep_me": 7}


def test_forget_playfield_pos_is_quiet_when_there_is_nothing_to_forget(
        monkeypatch, tmp_path):
    """Absent key, absent file and junk all answer None rather than raising -
    the button runs on machines that have never opened a playfield."""
    _pf_state(monkeypatch, tmp_path, '{"keep_me": 7}')
    assert emulate_tab.EmulatePanel._forget_playfield_pos() is None
    _pf_state(monkeypatch, tmp_path, None)
    assert emulate_tab.EmulatePanel._forget_playfield_pos() is None
    _pf_state(monkeypatch, tmp_path, "not json at all")
    assert emulate_tab.EmulatePanel._forget_playfield_pos() is None


def test_forget_playfield_pos_leaves_a_non_dict_alone(monkeypatch, tmp_path):
    """Valid JSON that is not an object is still not ours to rewrite."""
    p = _pf_state(monkeypatch, tmp_path, '[1, 2, 3]')
    assert emulate_tab.EmulatePanel._forget_playfield_pos() is None
    assert p.read_text() == '[1, 2, 3]'


def test_reset_windows_button_is_on_the_tab(tmp_path):
    """Every platform, unlike the two buttons beside it: a second monitor
    going away is not a Windows-only event."""
    root, panel = _panel(tmp_path)
    try:
        assert panel._winreset_btn.cget("text") == "Reset windows"
        assert panel._winreset_btn.winfo_manager() == "pack"
    finally:
        root.destroy()


def test_reset_windows_greys_out_while_a_run_is_up(monkeypatch, tmp_path):
    """The gate, and it is the whole reason the button is not always live:
    padglhost re-saves the geometry as the windows move and again at close, so
    a reset during a run is undone by the run itself."""
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    root, panel = _panel(tmp_path)
    try:
        panel._apply({"state": "running", "running": "1", "procs": "5"})
        assert str(panel._winreset_btn.cget("state")) == "disabled"
        panel._apply({"state": "off", "running": "0", "procs": "0"})
        assert str(panel._winreset_btn.cget("state")) == "normal"
    finally:
        root.destroy()


# ----------------------------------------------------------------------
# THE MACHINE WHOSE WSL CANNOT START A WINDOWS PROGRAM.
#
# The virtual playfield is a Windows process, because this WSL has no Tk of
# any kind, and watch.sh launches it through interop.  A user's distro has
# `[interop] enabled=false` in /etc/wsl.conf, so his window could never open
# itself and the rig's only answer was a command to type before every run.
#
# Interop is LINUX -> WINDOWS.  Windows -> Linux (`wsl.exe`) is unaffected by
# that switch, so everything the window DOES once it is up still works - only
# the launch cannot cross.  PAD is already on the far side, so the run asks
# and PAD opens it.
# ----------------------------------------------------------------------

_LAUNCH = (r"PAD_PLAYFIELD_WINDOWS_LAUNCH game=godzilla_pro savestates=1 "
           r"root=\\wsl.localhost\Ubuntu\home\david\spike2root "
           r"tables=\\wsl.localhost\Ubuntu\home\david\spike2root\dump\tables")


def test_the_launch_token_carries_the_title_and_both_paths():
    got = emulate_tab.playfield_launch(_LAUNCH)
    assert got["game"] == "godzilla_pro"
    assert got["savestates"] == "1"
    # The paths are the pair WSLENV's /p would have translated during the
    # interop exec that is not happening - already in Windows form, and
    # entitled to contain a space, which is why the split is on the KEYS.
    assert got["root"] == r"\\wsl.localhost\Ubuntu\home\david\spike2root"
    assert got["tables"].endswith(r"\dump\tables")


def test_the_token_is_found_inside_the_log_line_it_arrives_on():
    """It is read off watch.sh's stdout, which the tab has already prefixed
    for its log pane."""
    assert emulate_tab.playfield_launch("[emulate] " + _LAUNCH)["game"] \
        == "godzilla_pro"


def test_a_path_with_a_space_survives_the_parse():
    got = emulate_tab.playfield_launch(
        r"PAD_PLAYFIELD_WINDOWS_LAUNCH game=jaws_pro savestates=0 "
        r"root=\\wsl.localhost\Ubuntu\home\d v\spike2root tables=")
    assert got["root"].endswith(r"\home\d v\spike2root")
    assert got["savestates"] == "0"


def test_an_ordinary_log_line_is_not_a_launch_request():
    """Every line of the run's output goes through this."""
    for line in ("[watch] virtual playfield window opening",
                 "[watch] the game never started.", "", "state=attract"):
        assert emulate_tab.playfield_launch(line) is None
    # ...and neither is the token with nothing to launch.
    assert emulate_tab.playfield_launch(
        "PAD_PLAYFIELD_WINDOWS_LAUNCH savestates=1") is None


# ----------------------------------------------------------------------
# Item 74: a first boot copies the card BEFORE the guest starts, and
# cardmount.sh narrates it one line every 2 s.  The drain thread turns those
# lines into the state label, because status.sh's honest "Not running" during
# the copy is exactly the looks-like-a-hang this item exists to remove.
# ----------------------------------------------------------------------

def test_a_copy_progress_line_becomes_a_state_label():
    got = emulate_tab.card_copy_progress(
        "[card] copying godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw: "
        "3121 / 7497 MB (41%)")
    assert got == "Copying card: 3121 / 7497 MB (41%)"


def test_a_card_name_with_spaces_survives_the_parse():
    """'Heisei Custom Image Premium V1.raw' is a real card on the desk."""
    got = emulate_tab.card_copy_progress(
        "[card] copying Heisei Custom Image Premium V1.raw: 0 / 7497 MB (0%)")
    assert got == "Copying card: 0 / 7497 MB (0%)"


def test_ordinary_card_lines_are_not_copy_progress():
    """The verdict lines that FOLLOW the progress must parse as None — the
    drain uses that edge to stop showing a copy that has finished."""
    for line in ("[card] using local cache /home/david/cardcache/x.raw",
                 "[card] local cache ready - booting from it",
                 "[card] cache not usable - booting from the original",
                 "[card] caching x.raw to the WSL disk in the background",
                 "[card] copy stalled - booting from the original instead "
                 "(copy continues)",
                 "", "state=attract"):
        assert emulate_tab.card_copy_progress(line) is None


# ----------------------------------------------------------------------
# Item 77: the Card cache manager.  The list format is cardmount.sh's
# --cache-list — tab separated, source LAST, because labels and source
# paths are entitled to spaces ("Heisei Custom Image Premium V1" is real).
# ----------------------------------------------------------------------

_CACHE_LIST = (
    "entry\talpha\t3072\t7168\t1787000000\t/mnt/d/cards/alpha.raw\n"
    "entry\tbeta card\t5242880\t7761920\t0\t/mnt/c/spaced dir/beta card.raw\n"
    "entry\tgamma\t2048\t2048\t1786000000\t\n"
    "disk\t29355388\t263114392\n")


def test_cache_list_parses_and_sorts_biggest_first():
    entries, disk = emulate_tab.parse_cache_list(_CACHE_LIST)
    assert [e["label"] for e in entries] == ["beta card", "alpha", "gamma"]
    assert entries[0]["real_kb"] == 5242880
    assert entries[0]["src"] == "/mnt/c/spaced dir/beta card.raw"
    # boot 0 means no sidecar yet — rendered as "never", never as 1970.
    assert entries[0]["boot"] == 0
    assert disk == (29355388, 263114392)


def test_cache_list_survives_garbage_and_emptiness():
    assert emulate_tab.parse_cache_list("") == ([], None)
    entries, disk = emulate_tab.parse_cache_list(
        "noise\nentry\tbad\tNaN\t1\t2\tx\ndisk\ta\tb\n" + _CACHE_LIST)
    assert len(entries) == 3 and disk is not None


def test_cache_sizes_and_boot_render_for_humans():
    assert emulate_tab.human_size(5242880) == "5.0 GB"
    assert emulate_tab.human_size(2048) == "2 MB"
    assert emulate_tab.cache_boot_text(0) == "never"
    assert emulate_tab.cache_boot_text(1787000000).startswith("20")


# ----------------------------------------------------------------------
# Item 78: the footer bar under the notebook carries the EMULATION's
# loading state while the Emulate tab is showing — the panel dispatches
# semantic kinds and the window renders them.  These test the dispatch.
# ----------------------------------------------------------------------

def test_the_footer_follows_the_emulation_state(monkeypatch, tmp_path):
    _isolated_ctl(monkeypatch, tmp_path)
    root, panel = _panel(tmp_path)
    pushes = []
    panel._footer_cb = lambda kind, pct=None, text="": \
        pushes.append((kind, pct, text))
    try:
        panel._apply({"state": "off", "running": "0", "procs": "0"})
        assert pushes[-1][0] == "idle"
        panel._apply({"state": "booting", "running": "1", "procs": "5"})
        assert pushes[-1][0] == "boot"
        assert "Starting" in pushes[-1][2]
        # Tech Alerts is its OWN chip on the ladder — still loading, never
        # done, and never the same chip as the boot.
        panel._apply({"state": "techalerts", "running": "1", "procs": "5"})
        assert pushes[-1][0] == "techalerts"
        panel._apply({"state": "attract", "running": "1", "procs": "5"})
        assert pushes[-1][0] == "run"
        # A copy in flight outranks everything the poll says (the guest is
        # deliberately not running yet) — and carries its real percent.
        panel._copying = "Copying card: 3121 / 7497 MB (41%)"
        panel._copying_pct = 41
        panel._apply({"state": "off", "running": "0", "procs": "0"})
        assert pushes[-1] == ("copy", 41, "Copying card: 3121 / 7497 MB (41%)")
        # ...except during a Stop, when the copy stops narrating.
        panel._stopping = True
        panel._apply({"state": "off", "running": "0", "procs": "0"})
        assert pushes[-1][0] == "idle"
    finally:
        root.destroy()


def test_the_sound_and_skip_toggles_are_gone_and_env_is_clean(
        monkeypatch, tmp_path):
    """David, 2026-08-24: the volume slider owns loudness and boots land in
    attract on their own — the two start-time tickboxes are removed, and
    Start's environment no longer carries either override."""
    root, panel = _panel(tmp_path)
    try:
        assert not hasattr(panel, "_audio_chk")
        assert not hasattr(panel, "_auto_chk")
    finally:
        root.destroy()


def test_cache_manager_lists_and_drops(tmp_path, monkeypatch):
    """The dialog end to end against a canned rig: rows land biggest-first,
    Delete confirms and shells one --cache-drop per selected label, then
    reloads.  All rig calls are captured — nothing reaches a real WSL."""
    import time as _time
    root, panel = _panel(tmp_path)
    panel._on_destroy(None)
    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        text = _CACHE_LIST if "--cache-list" in cmd else "[card] dropped\n"
        return SimpleNamespace(stdout=text.encode())

    monkeypatch.setattr(emulate_tab.subprocess, "run", fake_run)
    monkeypatch.setattr(emulate_tab.messagebox, "askyesno",
                        lambda *a, **k: True)
    try:
        panel._open_cache_manager()
        tree = panel._cache_ui["tree"]
        deadline = _time.time() + 5
        while not tree.get_children() and _time.time() < deadline:
            root.update()
        assert list(tree.get_children()) == ["beta card", "alpha", "gamma"]
        assert "5.0 GB" in panel._cache_ui["head"].cget("text")
        # A second open LIFTS the same window instead of stacking another.
        win = panel._cache_win
        panel._open_cache_manager()
        assert panel._cache_win is win
        # Drop the spaced-label entry.
        tree.selection_set("beta card")
        root.update()
        panel._cache_delete()
        deadline = _time.time() + 5
        while not any("--cache-drop" in c for c in calls) \
                and _time.time() < deadline:
            root.update()
        drops = [c for c in calls if "--cache-drop" in c]
        assert len(drops) == 1 and drops[0][-1] == "beta card"
        # ...and the reload after the drop asked for a fresh list.
        deadline = _time.time() + 5
        while sum("--cache-list" in c for c in calls) < 2 \
                and _time.time() < deadline:
            root.update()
        assert sum("--cache-list" in c for c in calls) >= 2
    finally:
        root.destroy()


def test_the_interpreter_is_never_the_frozen_app_itself(monkeypatch):
    """sys.executable is the answer on the Windows build (the app runs on the
    Python bundled beside it) and a TRAP in a frozen one, where it is PAD.exe
    - handing that a script path starts a second copy of PAD."""
    monkeypatch.setattr(emulate_tab.sys, "frozen", True, raising=False)
    monkeypatch.setattr(emulate_tab.sys, "executable",
                        r"C:\Program Files\PAD\PAD.exe")
    monkeypatch.setattr(emulate_tab.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(emulate_tab.shutil, "which", lambda n: None)
    got = emulate_tab.windows_python()
    assert got and got.lower().endswith("pythonw.exe"), got
    assert "PAD.exe" not in got


def test_the_interpreter_prefers_the_windowed_twin_of_the_running_one(
        monkeypatch):
    """python.exe would put a black console beside the playfield."""
    monkeypatch.setattr(emulate_tab.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_tab.sys, "executable", r"C:\Py\python.exe")
    monkeypatch.setattr(emulate_tab.os.path, "isfile", lambda p: True)
    assert emulate_tab.windows_python() == r"C:\Py\pythonw.exe"


def test_no_interpreter_at_all_is_said_rather_than_guessed(monkeypatch):
    """A wrong guess here launches something that is not Python."""
    monkeypatch.setattr(emulate_tab.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_tab.sys, "executable", "")
    monkeypatch.setattr(emulate_tab.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(emulate_tab.shutil, "which", lambda n: None)
    assert emulate_tab.windows_python() is None


def test_the_path_search_does_not_go_through_a_platform_aware_helper(
        monkeypatch, tmp_path):
    """shutil.which BRANCHES ON sys.platform, and its win32 branch reaches for
    a `_winapi` that is None everywhere else - so the moment that call landed
    in the Windows launch path, every test that walks that path by faking the
    platform died inside the standard library on the Linux and macOS runners,
    and the shape went unchecked on two machines out of three.  The lookup
    walks PATH itself; the names are spelled with their extension, so there is
    nothing else which() was doing for us."""
    def boom(_name):
        raise AttributeError("'NoneType' object has no attribute "
                             "'NeedCurrentDirectoryForExePath'")

    monkeypatch.setattr(emulate_tab.shutil, "which", boom)
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setattr(emulate_tab.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_tab.sys, "executable", "")
    monkeypatch.setenv("PATH", str(tmp_path))
    # Nothing on PATH is an ANSWER, not a crash.
    assert emulate_tab.windows_python() is None
    # ...and with the interpreter there, PATH is what finds it.
    exe = tmp_path / "python.exe"
    exe.write_text("")
    assert emulate_tab.windows_python(console=True) == str(exe)
    # Which is what makes the whole Windows launch shape reachable from any
    # host again - the thing the fake platform is there to test.
    monkeypatch.setenv("PAD_EMU_DIR", str(tmp_path))
    assert emulate_tab.rig_cmd("watch.sh", 30)[:2] == ["wsl.exe", "-e"]


class _FakeProc:
    """Just enough Popen for the playfield handling: alive until killed."""

    def __init__(self):
        self.waited = None
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.waited = timeout
        raise RuntimeError("still open")

    def kill(self):
        self.killed = True


def test_the_run_that_asks_gets_a_playfield_window(monkeypatch, tmp_path):
    """End to end through the panel: the token in the log stream becomes one
    Popen of playfield.py, with the title, the save-state flag and both paths
    the run worked out."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setattr(emulate_tab, "windows_python",
                        lambda console=False: r"C:\py\pw.exe")
    seen = {}

    def _popen(cmd, env=None, **kw):
        seen["cmd"], seen["env"] = cmd, env
        return _FakeProc()

    monkeypatch.setattr(emulate_tab.subprocess, "Popen", _popen)
    root, panel = _panel(tmp_path)
    try:
        panel._open_playfield(emulate_tab.playfield_launch(_LAUNCH))
        assert seen["cmd"][0] == r"C:\py\pw.exe"
        assert seen["cmd"][1].endswith("playfield.py")
        assert seen["cmd"][2] == "godzilla_pro"
        assert seen["cmd"][3] == "--savestates"
        assert seen["env"]["PAD_ROOT"].startswith("\\\\wsl.localhost")
        assert seen["env"]["PAD_TABLES"].endswith("\\dump\\tables")
        # ONE window, not one per line of output.
        seen.clear()
        panel._open_playfield(emulate_tab.playfield_launch(_LAUNCH))
        assert not seen
    finally:
        root.destroy()


def test_a_run_without_save_states_gets_no_save_buttons(monkeypatch, tmp_path):
    """PF_STATES is watch.sh's answer, not this side's guess - a run whose
    pivot was withdrawn must not show buttons that can only fail."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    monkeypatch.setattr(emulate_tab, "windows_python",
                        lambda console=False: r"C:\py\pw.exe")
    seen = {}

    def _popen(cmd, env=None, **kw):
        seen["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(emulate_tab.subprocess, "Popen", _popen)
    root, panel = _panel(tmp_path)
    try:
        panel._open_playfield(emulate_tab.playfield_launch(
            "PAD_PLAYFIELD_WINDOWS_LAUNCH game=jaws_pro savestates=0"))
        assert "--savestates" not in seen["cmd"]
    finally:
        root.destroy()


def test_pad_closes_the_window_it_opened(tmp_path):
    """Whoever owns the launch owns the teardown: the rig's forced close is a
    powershell.exe call, which is the interop this machine does not have."""
    root, panel = _panel(tmp_path)
    try:
        proc = _FakeProc()
        panel._pf_proc = proc
        panel._close_playfield()
        # The polite exit gets its chance first - that is what saves the
        # window position - and only then is it closed here.
        assert proc.waited and proc.killed
        assert panel._pf_proc is None
        # And nothing to close is not an error: the ordinary machine's window
        # is watch.sh's child and never passes through here.
        panel._close_playfield()
    finally:
        root.destroy()


def test_a_playfield_that_stops_leaves_something_to_read():
    """The ORDINARY launch, which is watch.sh's own and not this tab's.

    Reported 2026-08-11: "starting Bond Pro was missing the keys window and
    playfield", with a full run log in which not one line was about the
    playfield.  It could not be: the launch was `... >/dev/null 2>&1 &`, so a
    window that died on its first line and a window the user closed produced
    exactly the same evidence, which is none.  Since item 39 retired the
    Controls window into that window's key panel, it takes the key list with
    it - which is why the report names two windows and not one.
    """
    body = "\n".join(ln for ln in _rig_text("watch.sh").splitlines()
                     if not ln.lstrip().startswith("#"))
    # Both launches - the Linux desktop's local Tk process and WSL's Windows
    # one through interop - write where a human can read it afterwards, the
    # same rule autoattract.sh and ballfeed.py have always followed.
    for launch in ('"$RIG/playfield.py" "$GAME" $PF_STATES',
                   '"$PF_WIN" "$GAME" $PF_STATES'):
        lines = [ln for ln in body.splitlines() if launch in ln]
        assert len(lines) == 1, "watch.sh no longer launches it this way"
        assert '>>"$PFLOG" 2>&1' in lines[0], (
            "the playfield's own output goes nowhere again")
        assert ">/dev/null 2>&1 &" not in lines[0]
    # ...and the run ASKS, once, whether it stayed up. Only for a window the
    # RUN launched: the one PAD opens has no process on that side to find,
    # and the app reports its own failures.
    assert body.count("PF_LAUNCHED=1") == 2, "one per launch, and only there"
    assert '[ "${PF_LAUNCHED:-0}" = 1 ] && ! pf_up' in body
    assert body.index('[ "${PF_LAUNCHED:-0}" = 1 ]') > body.index("PF_LAUNCHED=1"), (
        "the check has to come after the launch it is about")
    # An empty log is a different fault from a traceback - the interpreter
    # never ran the script at all - and is worth its own sentence.
    check = body[body.index('[ "${PF_LAUNCHED:-0}" = 1 ]'):]
    assert '-s "$PFLOG"' in check and "never ran it" in check


# ----------------------------------------------------------------------
# ...AND THE OTHER HALF OF A SAVE STATE, WHICH APT CANNOT SUPPLY.
#
# PAD-53 made a missing busybox-static cost the feature instead of the run.
# A machine that then installed busybox-static STILL had no save states:
# criu was a hard-coded /var/tmp/criubuild/... in eight rig scripts, and no
# Ubuntu publishes criu at all (`apt-cache policy criu` -> empty version
# table).  It is built from source instead, and the tab has to say so without
# ever handing that name to apt.
# ----------------------------------------------------------------------

_CRIU_FACTS = {"iswsl": "1", "qemu": "1", "armgcc": "1", "nativecc": "1",
               "debugfs": "1", "fuse": "1", "ffmpeg": "1", "busybox": "1",
               "criu": "0", "binfmt": "1", "universe": "1", "nocand": ""}


def test_a_machine_missing_only_criu_still_runs_the_emulator():
    """The notice must not tell a working PC that it cannot emulate."""
    assert setup_ok(_CRIU_FACTS)
    assert not setup_settled(_CRIU_FACTS)
    notice = setup_notice(_CRIU_FACTS, can_fix=True)
    assert notice.startswith("The emulator runs on this PC.")
    assert "criu" in notice


def test_criu_is_never_offered_as_a_package_to_install():
    """No Ubuntu publishes it: `apt install criu` cannot work anywhere, and
    naming it beside a real package fails that one too."""
    steps = emulate_tab.setup_fix_steps(_CRIU_FACTS)
    assert steps and all("Install in WSL:  criu" not in s for s in steps)
    assert any("Build criu from source" in s for s in steps), steps
    # The consent has to say what a build costs - it is minutes and a
    # download, not an apt install.
    build = [s for s in steps if "Build criu" in s][0]
    assert "GitHub" in build and "minutes" in build


def test_the_button_stays_for_a_machine_whose_only_gap_is_criu():
    """It can build it, so there is something to press."""
    assert emulate_tab.setup_fixable(_CRIU_FACTS)
    assert "Set up emulator" in setup_notice(_CRIU_FACTS, can_fix=True)


def test_both_save_state_pieces_are_named_when_both_are_missing():
    facts = dict(_CRIU_FACTS, busybox="0")
    extras = [p for p, _ in setup_extras(facts)]
    assert extras == ["busybox-static", "criu"]
    steps = emulate_tab.setup_fix_steps(facts)
    assert any(s.startswith("Install in WSL:") and "busybox-static" in s
               for s in steps)
    assert any("Build criu" in s for s in steps)


def test_printed_advice_never_names_a_package_that_does_not_exist():
    """`sudo apt install criu` is advice that cannot work on any Ubuntu."""
    facts = dict(_CRIU_FACTS, ffmpeg="0", busybox="0")
    notice = setup_notice(facts, can_fix=False)
    assert "apt install criu" not in notice
    assert "apt install ffmpeg busybox-static" in notice
    assert "getcriu.sh" in notice


def test_a_rig_that_never_heard_of_criu_accuses_nobody():
    """An older rig emits no `criu` line, and silence is not a missing
    program - the same rule every other fact here follows."""
    facts = dict(_CRIU_FACTS)
    del facts["criu"]
    assert setup_extras(facts) == []
    assert emulate_tab.setup_built(facts) == []
    assert setup_settled(facts)


# ----------------------------------------------------------------------
# What the app's own WSL restart leaves behind
#
# Reported 2026-08-12 (Pinside, #151-#153).  A tester's run stopped on an
# unset DISPLAY; the cure offered was "Restart WSL…" on this tab; and his
# NEXT run stopped on
#
#     chroot: failed to run command '/bin/sh': Exec format error
#
# because the kernel's 32-bit ARM registration lives in the RUNNING kernel
# and his distro does not boot systemd, so the restart took it with it.  The
# tab said nothing about that at all: the setup probe ran once, at build
# time, against the machine as it was BEFORE the restart - so the notice and
# the "Set up emulator…" button that puts the handler back both stayed
# hidden, and what the user got instead was a wall of guest log text telling
# him to edit /etc/wsl.conf by hand.
# ----------------------------------------------------------------------

def _restart_rig(tmp_path, monkeypatch, survives):
    """Build a panel over a WSL whose `--shutdown` costs the ARM handler (or
    not, when `survives`), and hand back the panel, the log and the root."""
    monkeypatch.setattr(emulate_tab.sys, "platform", "win32")
    machine = {"binfmt": "1", "probes": 0}

    monkeypatch.setattr(emulate_tab, "rig_available", lambda: True)

    def probe():
        machine["probes"] += 1
        return _facts(binfmt=machine["binfmt"], wslconf="0")

    monkeypatch.setattr(emulate_tab, "setup_state", probe)

    def fake_run(cmd, *a, **kw):
        # THE FACT BEING SIMULATED, and it is one line: a distro without
        # systemd comes back from `wsl --shutdown` with an empty
        # binfmt_misc.  Everything else about the machine is unchanged -
        # qemu-user-static is still installed, which is why the tab cannot
        # infer this and has to ask.
        if not survives and any("--shutdown" in str(c) for c in cmd):
            machine["binfmt"] = "0"
        return SimpleNamespace(stdout=b"", returncode=0)

    monkeypatch.setattr(emulate_tab.subprocess, "run", fake_run)
    root, panel = _panel(tmp_path)
    logged = []
    panel._log_sink = logged.append
    return root, panel, logged, machine


def _pump(root, want, seconds=10):
    """Wait for *want* under a REAL mainloop, and say whether it came true.

    NOT ``root.update()`` in a loop, which is what every other panel test
    here uses and what this one cannot: the restart worker hands its answer
    back with ``after`` FROM ANOTHER THREAD, and tkinter refuses that unless
    the mainloop is genuinely running in the thread that made the
    interpreter.  ``update()`` does not count - the worker's ``after`` raises
    RuntimeError, the panel swallows it exactly as it must in a torn-down
    tab, and the test then watches a tab that nothing ever reached.  (Both
    of the log lines the worker writes travel the same way, so this is the
    production path, not a test-only one.)
    """
    import time
    deadline = time.time() + seconds
    got = {"v": False}

    def tick():
        got["v"] = bool(want())
        if got["v"] or time.time() > deadline:
            root.quit()
        else:
            root.after(20, tick)

    root.after(0, tick)
    root.mainloop()
    return got["v"]


def test_a_wsl_restart_re_probes_what_it_left_behind(tmp_path, monkeypatch):
    """The button that restarts WSL is one of the two ways a machine that
    could emulate a minute ago stops being one, so the answer it invalidates
    is asked again - and the notice and its button come back with it."""
    root, panel, logged, machine = _restart_rig(tmp_path, monkeypatch,
                                                survives=False)
    try:
        assert _pump(root, lambda: panel._setup is not None), \
            "the build-time probe never answered"
        assert not panel._setup_msg.winfo_ismapped(), \
            "a healthy machine was given a notice before anything happened"

        panel._restart_wsl("the test's own reason")
        assert _pump(root, lambda: panel._setup_msg.winfo_ismapped()), \
            ("the tab still shows the machine it probed BEFORE the restart - "
             "the next Start is the only thing that would say otherwise")
        assert panel._setup_btn.winfo_ismapped(), \
            "nothing on the tab offers to put the handler back"
        assert "32-bit ARM" in panel._setup_msg.cget("text")
        # ...and in the log too, which is where the user is looking while a
        # restart runs.
        assert any("ARM handler" in m for m in logged), logged
    finally:
        root.destroy()


def test_a_machine_that_came_back_intact_is_told_nothing(tmp_path,
                                                         monkeypatch):
    """David's own WSL boots systemd, so its handler survives - and a restart
    there must not leave a notice or an accusation behind.  The re-probe is
    allowed to cost one wsl.exe and nothing else."""
    root, panel, logged, machine = _restart_rig(tmp_path, monkeypatch,
                                                survives=True)
    try:
        assert _pump(root, lambda: machine["probes"] >= 1)
        # SNAPSHOT, not a fixed count: a panel from an earlier test in this
        # file can still have a probe worker in flight, and monkeypatch has
        # by now pointed `setup_state` at THIS test's counter - so an
        # absolute `>= 2` can be satisfied by someone else's straggler.
        before = machine["probes"]
        panel._restart_wsl("the test's own reason")
        assert _pump(root, lambda: any("what the restart left behind" in m
                                       for m in logged)), \
            "the restart did not re-probe at all"
        assert _pump(root, lambda: machine["probes"] > before)
        # ...and then let the answer be applied before insisting on silence.
        _pump(root, lambda: False, seconds=1)
        assert not panel._setup_msg.winfo_ismapped()
        assert not panel._setup_btn.winfo_ismapped()
        assert not any("took the 32-bit ARM handler" in m for m in logged), \
            logged
    finally:
        root.destroy()


def test_the_restart_says_why_it_is_looking_before_it_looks(tmp_path,
                                                            monkeypatch):
    """The re-probe is what boots WSL back up, and on a cold VM that is tens
    of seconds - which would read as the restart itself hanging.  So the
    reason goes up first, whatever the answer turns out to be."""
    root, panel, logged, machine = _restart_rig(tmp_path, monkeypatch,
                                                survives=True)
    try:
        assert _pump(root, lambda: machine["probes"] >= 1)
        panel._restart_wsl("the test's own reason")
        assert _pump(root, lambda: any("what the restart left behind" in m
                                       for m in logged)), logged
        said = [m for m in logged if "what the restart left behind" in m][0]
        assert "systemd" in said
    finally:
        root.destroy()


# ----------------------------------------------------------------------
# ...and the same fault said from the other side.
#
# When the handler really is gone, the run's own message is what the user
# reads, and it used to be two root commands and an /etc/wsl.conf edit with
# no mention that the app in front of him does both.  The tester on
# 2026-08-12 set about doing it by hand.
# ----------------------------------------------------------------------

def _guest_binfmt_message():
    """The lines pad_ensure_guest_exec prints when no ARM handler exists,
    comments dropped - what the user reads, not what the file explains."""
    text = (pathlib.Path(DEFAULT_RIG_DIR) / "ensurebuild.sh").read_text(
        encoding="utf-8")
    body = text[text.index("no handler registered for 32-bit ARM"):]
    body = body[:body.index("return 1")]
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_guest_message_names_the_button_that_does_all_of_it(tmp_path,
                                                                monkeypatch):
    """One string, two languages: the rig prints the name of a button this
    module packs, so the two must not drift.  It is checked without its
    ellipsis - the shell writes three dots and Tk one character."""
    said = _guest_binfmt_message()
    assert "Set up emulator" in said
    # No probe: this test is about a label, and the build-time one is a real
    # wsl.exe on a Windows runner.
    monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)
    root, panel = _panel(tmp_path)
    try:
        assert panel._setup_btn.cget("text").startswith("Set up emulator")
    finally:
        root.destroy()


def test_the_button_is_offered_before_the_commands_and_only_on_wsl():
    """A Linux desktop has no such button and no free root, so it keeps the
    commands on their own - and where the button does exist it comes first,
    because it is what the reader should do."""
    said = _guest_binfmt_message()
    assert said.index("Set up emulator") < said.index("$(_pad_binfmt_advice)")
    assert 'IS_WSL' in said[:said.index("Set up emulator")], \
        "a Linux desktop is being pointed at a button it does not have"
    # The by-hand route is still printed, for a terminal run and for anyone
    # who wants to see what is being done.
    assert "wsl.conf" in said and "systemd=true" in said


def test_the_notice_asks_the_window_to_make_room_for_it(tmp_path, monkeypatch):
    """FOUND IN THE PROOF SHOTS, not here: the first cut of the re-probe put
    the button up beside a sentence nobody could read.

    ttk.Notebook pins its pane to the selected tab's requested height, and
    that is measured when the tab is selected.  Every other notice on this
    panel is already there by then; this one appears LATER, while the user is
    sitting on the tab - and pack gives a slave that no longer fits no space
    at all and leaves it unmapped.  So the panel says it is taller now.
    """
    root, panel, logged, machine = _restart_rig(tmp_path, monkeypatch,
                                                survives=False)
    asked = []
    panel._resize_fn = lambda: asked.append(1)
    try:
        assert _pump(root, lambda: panel._setup is not None)
        panel._restart_wsl("the test's own reason")
        assert _pump(root, lambda: panel._setup_msg.winfo_ismapped())
        assert asked, ("the notice was packed into a pane measured without "
                       "it, so it is there and invisible")
    finally:
        root.destroy()


def test_the_window_hands_the_panel_something_to_ask_with():
    """The panel's half is useless without the wiring, and the wiring is one
    keyword nobody would miss until a notice went missing again."""
    import inspect
    from pinball_decryptor.gui.main_window import MainWindow
    src_ = inspect.getsource(MainWindow._build_emulate_tab)
    assert "resize_fn=" in src_
    assert "_resize_notebook_to_current_tab" in src_
    # ...and it must be the real method, not a name that has moved on.
    assert callable(MainWindow._resize_notebook_to_current_tab)


# --- PAD's own Python, handed to the rig (PAD-95) ----------------------------
#
# The rig can only find a Python the USER installed, so a PC with none was told
# there was no Windows Python for the sound to go through and sent to
# python.org - with a `py` command its terminal did not recognise.  The app is
# standing on the Windows side already and every packaged install ships an
# embeddable CPython with pip beside it, so the app says where that is.


def test_the_sound_bridge_asks_for_the_console_twin(monkeypatch):
    """The playfield wants pythonw.exe (no console beside the window); the
    sound bridge wants python.exe - it is a stdio program with the guest's PCM
    piped into it, and python.exe is also the spelling the rig's own search
    produces, so the path handed over and the path reported back match."""
    monkeypatch.setattr(emulate_tab.sys, "frozen", False, raising=False)
    monkeypatch.setattr(emulate_tab.sys, "executable", r"C:\Py\pythonw.exe")
    monkeypatch.setattr(emulate_tab.os.path, "isfile", lambda p: True)
    assert emulate_tab.windows_python() == r"C:\Py\pythonw.exe"
    assert emulate_tab.windows_python(console=True) == r"C:\Py\python.exe"


def test_the_rig_is_handed_pads_own_python_on_windows(monkeypatch, tmp_path):
    r"""★ PAD-95.  Two scripts need this interpreter and neither can find it:
    setupcheck.sh reports whether this PC has a Windows sound player at all,
    and playaudio.sh plays through one.  It rides every rig call as
    PAD_WINPYTHON, which padpath.sh has always read first - translated to
    /mnt/c on the way, spaces and all, because `C:\Program Files` is where it
    lives on a default install."""
    ours = r"C:\Program Files\PAD\python\python.exe"
    said = "PAD_WINPYTHON=/mnt/c/Program Files/PAD/python/python.exe"
    monkeypatch.setattr(emulate_tab, "windows_python",
                        lambda console=False: ours)
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "setupcheck.sh")
    assert said in cmd, cmd
    assert "env" in cmd, cmd
    # A Windows path never crosses: WSL is handed the POSIX spelling.
    assert not any("\\" in c for c in cmd), cmd
    # The caller's own entries follow it and win any argument.
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "watch.sh", 30,
                  env=["PAD_CARD=/mnt/c/x.raw"])
    assert cmd.index(said) < cmd.index("PAD_CARD=/mnt/c/x.raw"), cmd
    # ...AND THE CHECKPOINTABLE LAUNCH SAYS IT TOO, because that one is built
    # here rather than by rig_cmd - a run started without it is a run whose
    # sound quietly takes the WSLg path.
    _home(monkeypatch, "/home/somebody")
    cmd = emulate_tab.watch_cmd(120, ["PAD_CARD=/mnt/c/x.raw"])
    assert cmd[:3] == ["wsl.exe", "-u", "root"], cmd
    assert said in cmd, cmd
    assert cmd[-1] == "120", cmd


def test_nothing_of_the_sort_off_windows(monkeypatch, tmp_path):
    """There is no interop boundary to hand a Windows .exe across, and the
    container forwards its own variables - so this must not appear at all."""
    monkeypatch.setattr(emulate_tab, "windows_python",
                        lambda console=False: r"C:\Py\python.exe")
    for platform in ("linux", "darwin"):
        cmd = _cmd_on(monkeypatch, platform, tmp_path, "watch.sh", 30)
        assert not any(c.startswith("PAD_WINPYTHON") for c in cmd), (
            platform, cmd)


def test_no_interpreter_to_name_leaves_the_rig_as_it_was(monkeypatch,
                                                         tmp_path):
    """Running from a checkout with nothing to point at is not a fault: an
    absent variable is the rig's own search, unchanged."""
    monkeypatch.setattr(emulate_tab, "windows_python",
                        lambda console=False: None)
    cmd = _cmd_on(monkeypatch, "win32", tmp_path, "setupcheck.sh")
    assert not any(c.startswith("PAD_WINPYTHON") for c in cmd), cmd
    assert "env" not in cmd, cmd
