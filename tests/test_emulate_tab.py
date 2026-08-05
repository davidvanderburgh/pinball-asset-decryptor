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

import pathlib

import pytest

from pinball_decryptor.gui import emulate_tab

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
    # `attract` is the word status.sh emits now; `running` is what it emitted
    # before, kept so an older rig still reads as something.
    for state in ("off", "booting", "techalerts", "attract", "running"):
        label, _ = state_text({"state": state})
        assert label and label != state


def test_attract_is_named_as_attract():
    # The app said "Waiting at Tech Alerts" for a whole run while the game sat
    # in attract mode on its high-score screen, because status.sh and
    # autoattract.sh disagreed about what "past Tech Alerts" meant. The word
    # the user reads has to be the one that matches the screen.
    label, _ = state_text({"state": "attract"})
    assert "attract" in label.lower()
    assert "tech alert" not in label.lower()


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
    # ...and a helper that simply finished still reads as the ordinary wait.
    label, hint = state_text({"state": "techalerts", "auto": "0",
                              "auto_result": "ok"})
    assert "Waiting" in label
    assert "press a switch" in hint.lower()


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
