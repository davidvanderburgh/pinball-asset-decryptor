"""Emulate tab: the parts that can be got wrong without anyone noticing.

No Tk here on purpose — these are the pure pieces (status parsing, the wording
shown for each state, the Windows->WSL path map).  The wording is tested because
"Waiting at Tech Alerts" being read as a fault cost this project a whole pass of
believing the emulator was hung when it was doing exactly what the real machine
does; a test is the cheapest way to stop that regressing into "Stuck".
"""

import pathlib

from pinball_decryptor.gui.emulate_tab import (DEFAULT_RIG_DIR, parse_status,
                                               state_text, _wsl_path)


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


def test_tech_alerts_is_described_as_waiting_not_as_a_fault():
    label, hint = state_text({"state": "techalerts"})
    # The LABEL is the bit read at a glance, so it must not sound like a defect.
    assert "Waiting" in label
    for wrong in ("stuck", "hung", "fault", "error", "failed", "parked"):
        assert wrong not in label.lower(), wrong
    # The hint has to say what to do about it, and say it is normal.
    assert "press a switch" in hint.lower()
    assert "not a fault" in hint.lower()


def test_tech_alerts_hint_changes_while_auto_advance_is_working():
    # Telling the user to press something while autoattract.sh is pressing it
    # gets two operators fighting over the same screen.
    label, hint = state_text({"state": "techalerts", "auto": "1"})
    assert "Waiting" in label            # the label is still the honest one
    assert "press a switch" not in hint.lower()
    assert "attract" in hint.lower()


def test_auto_advance_wording_only_applies_at_tech_alerts():
    # auto= lingers for a poll or two after the game has moved on; the hint for
    # a running game must not turn into "skipping to attract mode".
    _, hint = state_text({"state": "running", "auto": "1"})
    assert "Attract mode or the operator menu." == hint
    # auto=0 is the rig saying the helper has finished or was never started.
    _, hint = state_text({"state": "techalerts", "auto": "0"})
    assert "press a switch" in hint.lower()


def test_every_state_the_rig_can_emit_has_wording():
    for state in ("off", "booting", "techalerts", "running"):
        label, _ = state_text({"state": state})
        assert label and label != state


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
