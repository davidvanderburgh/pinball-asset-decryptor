"""JJP Emulate tab: the parts that can be got wrong without anyone noticing.

Mostly pure pieces — the state wording, the status mapping, the command
builders.  The wording is tested because the FIRST thing a user is told has to
be the first thing that is actually wrong: a run with no security key that says
"Stopped" sends them looking in entirely the wrong place, and the key is the one
thing about JJP that cannot be worked around.

The subject is ``webui/emulate_jjp_core.py`` (the rig facts the web JJP
Emulate tab calls); the tab itself is driven in tests/test_webui_emulate_jjp.py.
"""

import subprocess
from types import SimpleNamespace

import pytest

from pinball_decryptor.webui import rig as _rig
from pinball_decryptor.webui import emulate_jjp_core as jjp_emulate_tab
from pinball_decryptor.webui.emulate_jjp_core import (DEFAULT_RIG_DIR,
                                                      attach_dongle_cmd,
                                                      rig_cmd, rig_cmd_root,
                                                      rig_dir, state_text)
from pinball_decryptor.webui.tabs import emulate_jjp as jjp_web
from pinball_decryptor.webui.tabs.emulate_jjp import EmulateJJPTab


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
    from pinball_decryptor.webui import emulate_core
    assert emulate_core._wsl_path(r"c:\x") == _rig.wsl_path(r"c:\x")
    assert emulate_core.parse_status("a=1") == _rig.parse_status("a=1")


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


# ------------------------------------------------- ONE Linux, whichever one --
#
# This tab is the one place in the app that deliberately did NOT move into the
# Linux the app installs, and the reason is worth keeping written down: the JJP
# rig keeps its restored images in /var/tmp INSIDE the distro (padpath.sh keys
# them on the .iso so a title you have run once comes back instantly).  Moving
# the tab would strand several GB per title in the old distro and put the new
# copies somewhere a runtime version bump deletes - which is the one thing
# core/runtime.py's replace flag exists to prevent.  The Spike rigs could move
# because their work lives on the shared data disk (core/rigdata.py); this one
# needs that treatment first.
#
# So what has to hold is AGREEMENT, not a particular answer.  Three separate
# places name a distro here - the usbipd attach, the probe that asks whether the
# key arrived, and the rig commands themselves - and a half-done move would
# attach the key into one Linux and then look for it from another, which reads
# to the user as a key that is not plugged in.  That is exactly the failure the
# whole branch exists to end, and it is why this asserts they match rather than
# asserting they have no -d.


def _distro_named(argv):
    """Which distro this argument list targets, however it spells it."""
    for flag in ("-d", "--distribution", "--wsl"):
        if flag in argv:
            i = argv.index(flag) + 1
            # `--wsl` takes an OPTIONAL value: the next word is the distro only
            # when it is not another option.
            if i < len(argv) and not argv[i].startswith("-"):
                return argv[i]
            return None
    return None


def test_every_jjp_emulate_path_names_the_same_linux(monkeypatch):
    monkeypatch.setattr(jjp_emulate_tab, "usbipd_path", lambda: "usbipd")
    monkeypatch.setattr(jjp_emulate_tab.sys, "platform", "win32")

    probe = []
    monkeypatch.setattr(
        jjp_web.subprocess, "run",
        lambda cmd, *a, **kw: probe.append(list(cmd)) or SimpleNamespace(
            stdout=b"no", returncode=0))
    EmulateJJPTab._key_visible_in_wsl(object())

    named = {
        "usbipd attach": _distro_named(attach_dongle_cmd()),
        "the key probe": _distro_named(probe[0]),
        "the rig, as the user": _distro_named(rig_cmd("status.sh")),
        "the rig, as root": _distro_named(rig_cmd_root("watch.sh")),
    }
    assert len(set(named.values())) == 1, (
        "the key would be attached into one Linux and looked for in another: %s"
        % named)


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


def test_matrix_launch_is_root(monkeypatch):
    """swdump.py reads the game's memory and the game runs as root, so the
    ordinary-user form fails before it ever reaches the UI."""
    monkeypatch.setattr(jjp_emulate_tab.sys, "platform", "win32")
    cmd = rig_cmd_root("jjpsw_launch.sh")
    assert cmd[:4] == ["wsl.exe", "-u", "root", "-e"]


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


def test_help_has_an_entry_for_the_new_tab():
    """A tab with no HELP_CONTENT entry opens an empty '?' window."""
    from pinball_decryptor.webui.help_content import HELP_CONTENT
    body = " ".join(t + " " + b for t, b in HELP_CONTENT["Emulate JJP"])
    assert "security key" in body.lower()
    assert "read only" in body.lower()


# ------------------------------------------------------- dongle self-healing --


# ------------------------------------------------------------- wrong-title key --


def test_h0007_is_not_always_a_wrong_title_key():
    """THE misdiagnosis, and it cost an hour on 2026-08-20.

    H0007 is "Sentinel key not found" and covers two faults with OPPOSITE
    fixes: another title's key (swap it), or a key the licence daemon never
    picked up (swapping does nothing).  The panel used to report the first
    unconditionally - so it said "plug in the GunsNRoses key" while the truth
    was that the daemon could see NO key, and every title failed identically
    including the one whose key was plugged in.
    """
    no_key = jjp_emulate_tab.key_failure("NO KEY: nothing visible inside WSL.")
    assert no_key and no_key[0] == "No security key"

    unusable = jjp_emulate_tab.key_failure(
        "KEY NOT ACCEPTED: Wonka could not open the plugged-in Sentinel key.")
    assert unusable and unusable[0] == "Key not accepted"
    # It must NOT assert the title is wrong - that is the whole bug.
    assert "either" in unusable[1].lower()
    assert unusable[0] != no_key[0]

    # An older rig script in a half-updated checkout still gets reported.
    assert jjp_emulate_tab.key_failure("WRONG KEY: ...")[0] == \
        "Wrong key for this game"
    # Ordinary progress lines are not verdicts.
    assert jjp_emulate_tab.key_failure("== game (Wonka) ==") is None
    assert jjp_emulate_tab.key_failure("") is None


# --------------------------------------------------------------- log streaming --


# ----------------------------------------------------------- volume (item 118) --


# ------------------------------------------------------ ghost windows (item 118) --

def test_rig_ghosts_are_only_the_rigs_visible_wslg_windows():
    wins = [(1, "JJP GunsNRoses - emulated (Ubuntu)", "msrdc.exe", True),
            (2, "JJP switch matrix (Ubuntu)", "MSRDC.EXE", True),
            (3, "JJP switch matrix (Ubuntu)", "msrdc.exe", False),     # already hidden
            (4, "JJP GunsNRoses - emulated", "Xephyr.exe", True),      # not WSLg's
            (5, "Pinball Asset Decryptor", "msrdc.exe", True),
            (6, "JJP Wonka - emulated", "msrdc.exe", True)]
    assert jjp_emulate_tab.rig_ghosts(wins) == [1, 2, 6]


def test_only_a_stop_that_left_nothing_running_hides_windows():
    assert jjp_emulate_tab.stop_left_nothing("killed 3\ngame=0 matrix=0 xephyr=0 cuse=0")
    assert not jjp_emulate_tab.stop_left_nothing("game=0 matrix=1 xephyr=0 cuse=0")
    assert not jjp_emulate_tab.stop_left_nothing("game=0 matrix=0 xephyr=1 cuse=0")
    assert not jjp_emulate_tab.stop_left_nothing("")


def test_hide_rig_ghosts_hides_what_it_found(monkeypatch):
    monkeypatch.setattr(jjp_emulate_tab.sys, "platform", "win32")
    hidden = []
    wins = [(7, "JJP switch matrix (Ubuntu)", "msrdc.exe", True),
            (8, "Notepad", "notepad.exe", True)]
    assert jjp_emulate_tab.hide_rig_ghosts(windows=wins, hide=hidden.append) == 1
    assert hidden == [7]


# ------------------------------------------------- key present but not shared --

def test_a_key_in_the_pc_is_not_the_same_as_no_key():
    """The panel said "No security key" at a user looking straight at the key.

    ``dongle_present`` is a WSL question — status.sh reads sysfs INSIDE the
    distro — so a key sitting in the machine that usbipd has not handed over
    reads as absent.  Those are different faults with different fixes, and only
    one of them is the user's to solve.
    """
    on_pc = {"wsl": "1", "game_procs": "0", "dongle_present": "0",
             "key_on_pc": "1", "image_mounted": "1"}
    label, hint = state_text(on_pc)
    assert label != "No security key"
    assert "cannot see it yet" in hint or "passed through" in hint.lower()

    absent = dict(on_pc, key_on_pc="0")
    assert state_text(absent)[0] == "No security key"

    # Unknown (no usbipd) must fall back to the old wording, not invent a state.
    unknown = {k: v for k, v in on_pc.items() if k != "key_on_pc"}
    assert state_text(unknown)[0] == "No security key"


def test_key_on_pc_is_only_asked_when_the_rig_cannot_see_the_key():
    """usbipd list is a Windows round trip; the happy path must not pay for it
    on every poll."""
    import inspect
    src = inspect.getsource(EmulateJJPTab._read_status)
    assert 'dongle_present") != "1"' in src
    assert src.index('dongle_present') < src.index('key_on_pc(')


# ------------------------------------------------------- the ISO is remembered --

def test_the_game_iso_is_written_into_the_project_anchor():
    """The Game ISO box came back EMPTY on every load with a project open.

    It was saved to settings.json but never written into the project anchor -
    and the restore reads the anchor first whenever a project is loaded.  So the
    global copy was shadowed by an anchor that had no such key, and the box was
    cleared however many launches had used the ISO.
    """
    import inspect
    from pinball_decryptor import app as app_mod
    src = inspect.getsource(app_mod)
    # Written on BOTH anchor paths - the update of an existing one and the
    # creation of the first - or half the projects still forget it.
    assert "jjp_emulate_iso=jjp_emulate_iso" in src
    assert '"jjp_emulate_iso": jjp_emulate_iso' in src


def test_an_older_anchor_falls_back_to_the_global_setting():
    """An anchor written before the fix has no such key.  Without a fallback
    this would only ever help projects created afterwards, and every existing
    one would still come back blank."""
    import inspect
    from pinball_decryptor import app as app_mod
    src = inspect.getsource(app_mod)
    i = src.index('data.get("jjp_emulate_iso")')
    window = src[i:i + 700]
    assert '_settings.get("jjp_emulate_iso")' in window
