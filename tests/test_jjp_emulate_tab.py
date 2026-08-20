"""JJP Emulate tab: the parts that can be got wrong without anyone noticing.

Mostly pure pieces — the state wording, the status mapping, the command
builders.  The wording is tested because the FIRST thing a user is told has to
be the first thing that is actually wrong: a run with no security key that says
"Stopped" sends them looking in entirely the wrong place, and the key is the one
thing about JJP that cannot be worked around.

The widget tests build on an invisible root and skip rather than fail when Tk is
unusable, matching tests/test_emulate_tab.py.
"""

import subprocess
from types import SimpleNamespace

import pytest

from pinball_decryptor.gui import _rig, jjp_emulate_tab
from pinball_decryptor.gui.jjp_emulate_tab import (DEFAULT_RIG_DIR,
                                                   JJPEmulatePanel,
                                                   attach_dongle_cmd, rig_cmd,
                                                   rig_cmd_root, rig_dir,
                                                   state_text)


# ---------------------------------------------------------------- plumbing --

def test_wsl_path_maps_drive_letters():
    assert _rig.wsl_path(r"c:\repo\tools\jjp_emu") == "/mnt/c/repo/tools/jjp_emu"
    assert _rig.wsl_path(r"D:\Pinball\x.iso") == "/mnt/d/Pinball/x.iso"


def test_wsl_path_leaves_posix_alone():
    """A Linux desktop has no translation to do, and mangling the path there
    would break the rig on the platform it is actually native to."""
    assert _rig.wsl_path("/var/tmp/jjp_wonka") == "/var/tmp/jjp_wonka"


def test_parse_status_ignores_lines_without_equals():
    """A rig script that prints a warning must not corrupt the reading."""
    info = _rig.parse_status("wsl=1\nsomething went wrong\ngame_procs=3\n")
    assert info == {"wsl": "1", "game_procs": "3"}


def test_emulate_tab_shares_one_definition():
    """The Stern panel must delegate, not keep a second copy — two panels each
    with their own idea of how to spell a WSL path is exactly the class of bug
    the rig's 'never let two scripts define the same fact' rule exists for."""
    from pinball_decryptor.gui import emulate_tab
    assert emulate_tab._wsl_path(r"c:\x") == _rig.wsl_path(r"c:\x")
    assert emulate_tab.parse_status("a=1") == _rig.parse_status("a=1")


def test_rig_dir_is_overridable(monkeypatch):
    monkeypatch.setenv("PAD_JJP_EMU_DIR", "/somewhere/else")
    assert rig_dir() == "/somewhere/else"


def test_rig_dir_defaults_into_the_repo():
    assert DEFAULT_RIG_DIR.replace("\\", "/").endswith("tools/jjp_emu")


def test_rig_cmd_root_refuses_off_windows(monkeypatch):
    """Root is honest only on WSL: on a Linux desktop the equivalent is sudo,
    which wants a password a GUI app has nowhere to ask for."""
    monkeypatch.setattr(jjp_emulate_tab.sys, "platform", "linux")
    with pytest.raises(RuntimeError):
        rig_cmd_root("watch.sh")


def test_rig_cmd_env_is_passed_via_env_not_a_shell(monkeypatch):
    """wsl.exe re-parses its argument line, so a $var written into the command
    reaches the far side already expanded to nothing.  env(1) survives it."""
    monkeypatch.setattr(jjp_emulate_tab.sys, "platform", "win32")
    cmd = rig_cmd("run_game.sh", "--detach", env=["JJP_DISPLAY=:1"])
    assert "env" in cmd and "JJP_DISPLAY=:1" in cmd
    assert cmd.index("env") < cmd.index("bash")


def test_attach_dongle_targets_the_sentinel_key(monkeypatch):
    monkeypatch.setattr(jjp_emulate_tab, "usbipd_path", lambda: "usbipd")
    cmd = attach_dongle_cmd()
    assert cmd == ["usbipd", "attach", "--wsl", "--hardware-id", "0529:0001"]


def test_attach_dongle_is_none_without_usbipd(monkeypatch):
    monkeypatch.setattr(jjp_emulate_tab, "usbipd_path", lambda: None)
    assert attach_dongle_cmd() is None


# ------------------------------------------------------------------ wording --

def test_state_missing_key_beats_stopped():
    """THE important one.  With no key the game cannot run at all, and calling
    that "Stopped" sends the user looking at the emulator instead of at the
    USB port."""
    label, hint = state_text({"wsl": "1", "game_procs": "0",
                              "dongle_present": "0", "image_mounted": "1"})
    assert label == "No security key"
    assert "encrypted" in hint.lower()


def test_state_running_reports_size_and_uptime():
    label, hint = state_text({"wsl": "1", "game_procs": "3",
                              "game_rss_kb": str(1024 * 1024 * 2),
                              "game_uptime_s": "75", "board_nodes": "5",
                              "frames_in": "1000"})
    assert label == "Running"
    assert "2.0 GB" in hint and "1:15" in hint


def test_state_running_without_boards_says_so():
    """A game running with no boards has no switches and no LEDs, which looks
    like a bug in the matrix rather than a missing device."""
    _, hint = state_text({"wsl": "1", "game_procs": "3", "board_nodes": "0"})
    assert "NO BOARDS" in hint


def test_state_no_wsl():
    label, _ = state_text({"wsl": "0"})
    assert "WSL" in label


def test_state_empty_is_checking():
    assert state_text({})[0] == "Checking…"


def test_state_no_image():
    label, _ = state_text({"wsl": "1", "game_procs": "0",
                           "dongle_present": "1", "image_mounted": "0"})
    assert label == "No image mounted"


# ------------------------------------------------------------------ widgets --

@pytest.fixture(scope="module")
def root():
    """ONE Tk root for the whole module.

    A root per test skipped intermittently with "no usable Tk display": Tk does
    not enjoy being created and destroyed repeatedly in one process, and a test
    that sometimes runs and sometimes silently skips is worse than one that
    does not exist - it looks like coverage.
    """
    tk = pytest.importorskip("tkinter")
    try:
        r = tk.Tk()
    except Exception:                                       # noqa: BLE001
        pytest.skip("no usable Tk display")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except Exception:                                       # noqa: BLE001
        pass


@pytest.fixture
def panel(root, monkeypatch):
    """A built panel whose poller never actually shells out to WSL."""
    import tkinter as tk
    monkeypatch.setattr(JJPEmulatePanel, "_schedule_poll",
                        lambda self, ms=None: None)
    frame = tk.Frame(root)
    p = JJPEmulatePanel(frame, iso_var=tk.StringVar())
    p.build(frame)
    yield p
    p._stopped = True
    try:
        frame.destroy()
    except Exception:                                       # noqa: BLE001
        pass


def test_panel_builds_and_starts_disabled_controls(panel):
    """Screenshot acts on a RUNNING game; offering it when nothing is running
    is an invitation to a confusing error."""
    assert str(panel._shot_btn["state"]) == "disabled"


def test_there_is_no_switch_matrix_button(panel):
    """The matrix opens WITH the emulator now.  A button for it silently did
    nothing when it was launched as the wrong user, and a control that lies
    about having worked is worse than no control."""
    assert not hasattr(panel, "_matrix_btn")


def test_matrix_launch_is_root(monkeypatch):
    """swdump.py reads the game's memory and the game runs as root, so the
    ordinary-user form fails before it ever reaches the UI."""
    monkeypatch.setattr(jjp_emulate_tab.sys, "platform", "win32")
    cmd = rig_cmd_root("jjpsw_launch.sh")
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]


def test_apply_running_enables_controls_and_flips_the_button(panel):
    panel._apply({"wsl": "1", "game_procs": "3", "game_rss_kb": "1048576",
                  "game_uptime_s": "30", "board_nodes": "5",
                  "frames_in": "10", "frames_out": "10", "led_writes": "99",
                  "dongle_present": "1", "hasp_port_1947": "1",
                  "image_mounted": "1", "game": "Wonka"})
    assert panel._last_up is True
    assert panel._go_btn["text"] == "Stop"
    assert str(panel._shot_btn["state"]) == "normal"
    assert panel._cells["game"]["text"] == "Wonka"
    assert panel._cells["led_writes"]["text"] == "99"


def test_apply_stopped_flips_back(panel):
    panel._apply({"wsl": "1", "game_procs": "3"})
    panel._apply({"wsl": "1", "game_procs": "0", "dongle_present": "1",
                  "image_mounted": "1"})
    assert panel._last_up is False
    assert panel._go_btn["text"] == "Start"
    assert str(panel._shot_btn["state"]) == "disabled"


def test_note_warns_when_running_without_boards(panel):
    panel._apply({"wsl": "1", "game_procs": "3", "board_nodes": "0"})
    assert "boards" in panel._note["text"].lower()


def test_note_warns_about_the_key_when_stopped(panel):
    panel._apply({"wsl": "1", "game_procs": "0", "dongle_present": "0"})
    assert "key" in panel._note["text"].lower()


def test_start_without_an_iso_or_a_mount_does_not_shell_out(panel, monkeypatch):
    """Pressing Start with nothing selected must ask, not launch."""
    called = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: called.append(a) or SimpleNamespace(
                            returncode=0, stdout=b""))
    shown = []
    monkeypatch.setattr(jjp_emulate_tab.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    panel._info = {}
    panel._start_async()
    assert shown and not called


def test_shutdown_sync_is_a_noop_when_nothing_ran(panel, monkeypatch):
    """Quitting an app that never started the emulator must not spawn a WSL
    teardown — that is a visible pause on every exit for no reason."""
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    panel._last_up = False
    panel._info = {"cuse_daemons": "0"}
    panel.shutdown_sync()
    assert not called


def test_poll_does_not_stack(panel, monkeypatch):
    """A slow poll must not be lapped by the timer that scheduled it: a second
    tab polling WSL doubles the exposure the guard exists for."""
    monkeypatch.setattr(jjp_emulate_tab, "rig_available", lambda: True)
    started = []
    monkeypatch.setattr(jjp_emulate_tab.threading, "Thread",
                        lambda *a, **k: started.append(k) or SimpleNamespace(
                            start=lambda: None, daemon=True))
    panel._poll_busy = True
    panel._poll()
    assert not started


# -------------------------------------------------------------- integration --

def test_jjp_plugin_declares_the_capability():
    """The tab is gated on this flag; without it the panel is built and never
    shown, which looks exactly like a broken tab."""
    from pinball_decryptor.core.registry import get_manufacturer
    caps = get_manufacturer("jjp").capabilities
    assert caps.emulate_jjp is True


def test_stern_does_not_get_the_jjp_tab():
    """The two emulators share a visible LABEL but must never share a flag:
    ``emulate`` is read at one place to gate one frame, so a manufacturer
    setting both would get the Stern panel for its JJP games."""
    from pinball_decryptor.core.registry import get_manufacturer
    caps = get_manufacturer("stern").capabilities
    assert getattr(caps, "emulate_jjp", False) is False
    assert caps.emulate is True


def test_main_window_wires_both_emulate_tabs():
    """Both tabs must be constructed, keyed distinctly, and gated separately."""
    import inspect
    from pinball_decryptor.gui import main_window
    src = inspect.getsource(main_window)
    assert '(self._tab_jjp_emulate, "Emulate", "Emulate JJP")' in src
    assert 'self._build_jjp_emulate_tab()' in src
    assert '_configure_tab("Emulate JJP"' in src
    assert '_configure_tab("Emulate", ' in src


def test_help_has_an_entry_for_the_new_tab():
    """A tab with no HELP_CONTENT entry opens an empty '?' window."""
    from pinball_decryptor.gui.help_dialog import HELP_CONTENT
    body = " ".join(t + " " + b for t, b in HELP_CONTENT["Emulate JJP"])
    assert "security key" in body.lower()
    assert "read only" in body.lower()


# ------------------------------------------------------- dongle self-healing --

def test_attach_returns_true_when_key_already_visible(panel, monkeypatch):
    """If the key is already enumerated in WSL, attach is a no-op that
    succeeds without calling usbipd at all."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=b""))
    monkeypatch.setattr(panel, "_key_visible_in_wsl", lambda: True)
    assert panel._attach_dongle() is True


def test_attach_waits_out_the_async_race(panel, monkeypatch):
    """usbipd attach is async, so a key that is not visible at first but
    appears shortly after must be waited for, not failed on."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0,
                                                        stdout=b"attached"))
    # visible only from the 3rd check onward
    seq = iter([False, False, False, True, True])
    monkeypatch.setattr(panel, "_key_visible_in_wsl",
                        lambda: next(seq, True))
    monkeypatch.setattr("time.sleep", lambda *_a: None)
    assert panel._attach_dongle() is True


def test_attach_gives_up_cleanly_when_key_not_plugged_in(panel, monkeypatch):
    """A key that is genuinely not on the PC is a clean False, not a hang or a
    crash - usbipd says 'no device', and there is nothing to wait for."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(
                            returncode=1, stdout=b"usbipd: error: no device"))
    monkeypatch.setattr(panel, "_key_visible_in_wsl", lambda: False)
    monkeypatch.setattr("time.sleep", lambda *_a: None)
    assert panel._attach_dongle() is False


def test_start_skips_launch_when_key_never_appears(panel, monkeypatch):
    """If the key cannot be made visible, do NOT shell out to watch.sh - that
    would restore the image and wait another minute only to fail the same way."""
    monkeypatch.setattr(panel, "_attach_dongle", lambda: False)
    ran = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: ran.append(a) or SimpleNamespace(
                            returncode=0, stdout=b""))
    panel._iso_var.set("D:/x/Godfather.iso")
    panel._info = {}
    panel._start_async()
    import time as _t
    _t.sleep(0.3)          # let the worker thread run
    assert not ran         # watch.sh was never invoked
