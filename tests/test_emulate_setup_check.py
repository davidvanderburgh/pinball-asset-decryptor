"""“Check setup…”, and the four faults the setup probe never used to ask about.

WHAT THIS IS FOR.  ``setupcheck.sh`` answered one question - "can a 32-bit ARM
binary execute here" - which is packages plus the kernel handler.  A machine can
pass every part of that and still be unusable, and on 2026-08-12 one was: a
distro that logs in as root runs the renderer as root, the renderer cannot then
attach to the WSLg X server's shared memory, and the game window opens and stays
BLACK while sound, switches and the playfield all work.  The tab said nothing,
correctly, because nothing had ever asked.

Four facts now come back with the packages - who the distro logs in as, whether
it can start Windows programs, whether there is a display, and whether the good
audio path is available - and none of them is fixable by “Set up emulator…”,
which is the other half of this: the notice has to carry them without the button
claiming them.

AND THE BUTTON ITSELF.  Looking was never something a user could ask for: the
notice speaks only when something is wrong, so silence meant both "asked,
nothing wrong" and "never asked", and a user with a black window had nothing to
press and nothing to send.  “Check setup…” is always there, changes nothing
(``setupcheck.sh`` is read-only by its own design) and reports in full either
way.
"""
import os
import shutil
import subprocess

import pytest

from pinball_decryptor.gui import emulate_tab
from pinball_decryptor.gui.emulate_tab import (setup_env_faults, setup_fixable,
                                               setup_fix_steps, setup_notice,
                                               setup_ok, setup_report,
                                               setup_settled)

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

#: A machine with every package, a registered handler and nothing else wrong.
HEALTHY = {"binfmt": "1", "iswsl": "1", "wslconf": "1", "user": "david",
           "interop": "1", "display": "ok", "winaudio": "1",
           "distro": "ubuntu 24.04 noble"}


def facts(**over):
    out = dict(HEALTHY)
    out.update(over)
    return out


@pytest.fixture(autouse=True)
def _no_real_setup_probe(monkeypatch):
    """Same rule as test_emulate_tab: building a panel must not shell out."""
    monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)


# --------------------------------------------------------------------------
# The four facts
# --------------------------------------------------------------------------

def test_a_healthy_machine_has_no_environment_faults():
    assert setup_env_faults(HEALTHY) == []
    assert setup_settled(HEALTHY)
    assert setup_notice(HEALTHY, can_fix=True) == ""


def test_absent_keys_accuse_nobody():
    """An older rig emits none of these lines, and silence is not a fault -
    the same rule every other reader in this module follows."""
    old = {"binfmt": "1", "iswsl": "1", "wslconf": "1"}
    assert setup_env_faults(old) == []
    assert setup_env_faults(None) == []
    assert setup_settled(old)


def test_a_root_login_is_named_as_the_black_window():
    """The fault itself.  It has to be said in the notice, on a machine whose
    packages are all present, or it is exactly as invisible as it was."""
    root_pc = facts(user="root")
    assert setup_ok(root_pc), "this machine CAN run the emulator"
    assert not setup_settled(root_pc), "so the notice would stay hidden"
    text = setup_notice(root_pc, can_fix=True)
    assert "BLACK" in text
    assert "ordinary user" in text


def test_no_display_and_no_interop_are_named_too():
    assert "no game window" in setup_notice(facts(display="nosocket"),
                                            can_fix=True)
    assert "cannot start Windows programs" in setup_notice(
        facts(interop="0"), can_fix=True)
    # ...and a display we have nothing to say about is not a fault.
    assert setup_env_faults(facts(display="remote")) == []


def test_the_sound_advice_is_not_given_to_a_machine_that_cannot_take_it():
    """THE WRONG-FAULT GUARD.  Every candidate interpreter is a Windows .exe,
    so a distro with no interop answers "no Windows Python" however many are
    installed - and `py -m pip install sounddevice` is then advice addressed to
    a fault the user does not have.  That sentence was in a reply draft on
    2026-08-12 before this branch existed."""
    both_bad = facts(interop="0", winaudio="0")
    said = setup_notice(both_bad, can_fix=True)
    assert "sounddevice" not in said
    assert "cannot start Windows programs" in said
    # With interop working, it IS the right advice.
    assert "sounddevice" in setup_notice(facts(winaudio="0"), can_fix=True)


# --------------------------------------------------------------------------
# ...without the button claiming them
# --------------------------------------------------------------------------

def test_nothing_to_install_means_no_button():
    """A button that cannot do its one job is worse than no button - the rule
    _setup_apply already records a tester meeting twice.  It became reachable
    here the moment the notice could appear on a fully installed PC."""
    root_pc = facts(user="root")
    assert setup_fix_steps(root_pc) == [], "the fixer has nothing to do"
    assert not setup_fixable(root_pc), "so the button must not appear"


def test_a_machine_with_work_to_do_still_gets_its_button():
    """The guard above must not take the button away from the machines it was
    built for."""
    needs = facts(binfmt="0")
    assert setup_fix_steps(needs)
    assert setup_fixable(needs)
    assert setup_fixable(None), "unknown is still yes"


def test_the_notice_does_not_blame_packages_for_a_root_login():
    """setup_fixable answering False used to mean one thing only: apt cannot
    supply something.  The sentence for that case would be a description of a
    fault this machine does not have."""
    said = setup_notice(facts(user="root"), can_fix=True)
    assert "cannot get" not in said
    assert "Set up emulator" not in said


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

def test_the_report_always_says_something():
    """The whole point: a healthy machine gets an answer out loud, because
    silence is what could not be told apart from never having asked."""
    lines = "\n".join(setup_report(HEALTHY))
    assert "this PC can run the emulator." in lines
    assert "logs in as: david" in lines
    assert "packages: all present" in lines


def test_the_report_flags_the_root_login_where_it_is_read():
    lines = "\n".join(setup_report(facts(user="root")))
    assert "logs in as: root" in lines
    assert "the picture will be black" in lines


def test_the_report_survives_no_answer_at_all():
    """A probe that cannot reach WSL is an answer too, and the one case where
    the button would otherwise sit on "Checking…" for the rest of the session."""
    assert "no answer from WSL" in "\n".join(setup_report(None))


# --------------------------------------------------------------------------
# The button
# --------------------------------------------------------------------------

def _panel():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    frame = tk.Frame(root)
    frame.pack()
    panel = emulate_tab.EmulatePanel(frame)
    panel.build(frame)
    root.update()
    return root, panel


def test_check_setup_is_always_there():
    """Unlike “Set up emulator…”, which packs itself only when it has something
    to change.  This one is the surface a user can be pointed at."""
    root, panel = _panel()
    try:
        assert panel._check_btn.winfo_manager(), "not packed"
        assert not panel._setup_btn.winfo_manager(), \
            "the fixer packed itself with nothing to fix"
    finally:
        root.destroy()


def test_check_setup_reports_and_re_enables(monkeypatch):
    """The press-to-answer loop, including the case where the probe fails."""
    root, panel = _panel()
    try:
        said = []
        monkeypatch.setattr(panel, "_log", said.append)
        monkeypatch.setattr(emulate_tab, "setup_state", lambda: HEALTHY)
        panel._setup_recheck_now()
        for _ in range(80):
            root.update()
            if not panel._setup_busy and not panel._setup_report_next:
                break
        assert any("this PC can run the emulator." in s for s in said), said
        assert str(panel._check_btn["text"]) == "Check setup…"
        assert str(panel._check_btn["state"]) == "normal"
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# ...and the rig really emits them
# --------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_setupcheck_emits_the_four_new_facts():
    with open(os.path.join(RIG, "setupcheck.sh"), encoding="utf8") as fh:
        src = fh.read()
    for key in ("user=", "interop=", "display=", "winaudio="):
        assert '"%s' % key in src, "setupcheck.sh no longer reports %s" % key


@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_the_windows_python_search_has_one_definition():
    """playaudio.sh had its own copy; setupcheck.sh now asks the same question,
    and two scripts defining one fact is how alive.sh and killgame.sh once
    disagreed about what a running rig even is."""
    with open(os.path.join(RIG, "padpath.sh"), encoding="utf8") as fh:
        assert "pad_win_python()" in fh.read()
    with open(os.path.join(RIG, "playaudio.sh"), encoding="utf8") as fh:
        play = fh.read()
    assert "pad_win_python" in play
    assert "AppData/Local/Programs" not in play, "the copy is back"


@pytest.mark.skipif(not (os.path.isdir(RIG) and shutil.which("bash")),
                    reason="rig or bash not present")
def test_setupcheck_still_parses_as_key_value():
    """It is read by parse_status, so a line that is not key=value would be
    dropped in silence."""
    out = subprocess.run([shutil.which("bash"), "-n",
                          os.path.join(RIG, "setupcheck.sh")],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
