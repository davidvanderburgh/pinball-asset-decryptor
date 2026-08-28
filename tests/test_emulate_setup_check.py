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
import subprocess
import sys
import time

import pytest

from tests.conftest import HAS_BASH

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
    """Same rule as test_emulate_tab: building a panel must not shell out.

    BOTH probes, and the second one is why v0.151.0's CI went red on macOS
    while Windows and Linux passed.  Only ``setup_state`` was stubbed here, so
    ``docker_state`` still asked the real machine - and on a macOS runner with
    no Docker but a usable install route the panel CORRECTLY packs “Set up
    emulator…”, which is exactly what ``test_check_setup_is_always_there``
    asserts does not happen.  The code was right and the test's premise was
    false: on that machine there IS something to fix.  It passed on Windows and
    Linux because the Docker notice is a macOS path, and it had passed on macOS
    before only because whether the probe answers inside the single
    ``root.update()`` is a race.

    "ok" rather than None: None is "could not ask", which leaves the panel
    saying nothing, while "ok" is the healthy machine these tests mean when
    they say there is nothing to fix.  The two tests that are ABOUT the Docker
    notice patch this again with states of their own.
    """
    monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)
    monkeypatch.setattr(emulate_tab, "docker_state", lambda: "ok")


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


def _settle(root, panel, tries=200):
    """Run the main loop until the press has been answered.

    The drain reschedules itself with ``after(250, ...)`` and ``update()`` does
    NOT wait for a timer, so a tight loop of updates can run out long before
    the probe is ever collected - a race that only ever fell the right way
    because the probes here are monkeypatched to return instantly.  This gives
    the timers real time to fire and stops the moment nothing is armed.
    """
    for _ in range(tries):
        root.update()
        if not (panel._setup_busy or panel._docker_busy
                or panel._setup_report_next or panel._docker_report_next):
            return
        time.sleep(0.02)


def test_check_setup_reports_and_re_enables(monkeypatch):
    """The press-to-answer loop, including the case where the probe fails."""
    root, panel = _panel()
    try:
        said = []
        monkeypatch.setattr(panel, "_log", said.append)
        monkeypatch.setattr(emulate_tab, "setup_state", lambda: HEALTHY)
        monkeypatch.setattr(emulate_tab, "docker_state", lambda: "ok")
        panel._setup_recheck_now()
        _settle(root, panel)
        # EACH PLATFORM IS ASKED ITS OWN QUESTION and answers in its own words:
        # a Mac has no WSL and no packages to install, so "this PC can run the
        # emulator" is not a sentence its probe can honestly print.  What is
        # the same everywhere is that the press is ANSWERED and the button
        # comes back, which is the whole reason the button exists.
        want = ("this Mac can run the emulator." if sys.platform == "darwin"
                else "this PC can run the emulator.")
        assert any(want in s for s in said), said
        assert str(panel._check_btn["text"]) == "Check setup…"
        assert str(panel._check_btn["state"]) == "normal"
    finally:
        root.destroy()


def test_check_setup_answers_even_when_there_is_no_probe_to_run(monkeypatch):
    """★ THE FAULT THIS BUTTON EXISTS TO FIX, TURNED ON THE BUTTON ITSELF.

    A press that goes unanswered leaves it DISABLED and reading "Checking…"
    for the rest of the session, which is worse than the silence it replaced.
    Every Mac got exactly that: ``setup_state`` answers None on macOS by
    design, so ``_setup_check`` returned without starting a probe at all and
    nothing ever called back.  Whatever this machine is, and whether or not
    anything can be asked of it, the button must come back with words.
    """
    root, panel = _panel()
    try:
        said = []
        monkeypatch.setattr(panel, "_log", said.append)
        monkeypatch.setattr(emulate_tab, "setup_state", lambda: None)
        monkeypatch.setattr(emulate_tab, "docker_state", lambda: "absent")
        panel._setup_recheck_now()
        _settle(root, panel)
        assert str(panel._check_btn["state"]) == "normal", said
        assert str(panel._check_btn["text"]) == "Check setup…"
        assert len(said) > 1, said       # more than the "checking…" line
        assert any("cannot run the emulator" in s or "no answer" in s
                   for s in said), said
    finally:
        root.destroy()


def test_setup_report_darwin_never_asks_a_mac_about_wsl():
    """setup_report's no-answer line names WSL, which on a Mac would accuse a
    perfect machine of missing something it is not supposed to have."""
    for state in ("ok", "stopped", "absent", None):
        lines = " ".join(emulate_tab.setup_report_darwin(state))
        assert "WSL" not in lines, lines
        assert "packages" in lines, lines
    assert "can run the emulator." in " ".join(
        emulate_tab.setup_report_darwin("ok"))
    for state in ("stopped", "absent", "engineless", None):
        assert "cannot run the emulator yet." in " ".join(
            emulate_tab.setup_report_darwin(state))


def test_the_mac_report_says_which_docker_and_where_it_looked():
    """★ PAD-74.  The bug was a docker in /opt/local/bin that the app could
    not see, and no line of any report said where it had looked - so the one
    paste a user is asked for could not settle it either way."""
    lines = " ".join(emulate_tab.setup_report_darwin(
        "engineless", "/opt/local/bin/docker", None))
    assert "/opt/local/bin/docker" in lines, lines
    assert "none installed" in lines, lines
    # Nothing found: say where it looked, not just that it failed.
    lines = " ".join(emulate_tab.setup_report_darwin("absent"))
    assert "/opt/local/bin" in lines, lines
    assert "not found on PATH" in lines, lines
    # And an engine that IS there is named with its path.
    lines = " ".join(emulate_tab.setup_report_darwin(
        "stopped", "/opt/local/bin/docker",
        ("Colima", "cli", "/opt/local/bin/colima")))
    assert "Colima (/opt/local/bin/colima)" in lines, lines


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


@pytest.mark.skipif(not (os.path.isdir(RIG) and HAS_BASH),
                    reason="rig or working bash not present")
def test_setupcheck_still_parses_as_key_value():
    r"""It is read by parse_status, so a line that is not key=value would be
    dropped in silence.

    THE SCRIPT IS FED ON STDIN, NOT NAMED AS A PATH, and that is not a style
    choice: which("bash") answers with git-bash on one Windows host and with
    the WSL launcher (C:\Windows\System32\bash.exe) on the next, and the
    two disagree about what a native Windows path means.  Handing the WSL one
    `C:\...\setupcheck.sh` loses every backslash - it reported
    `C:UsersdavidDocuments...: No such file or directory` and exited 127 - so
    the test failed for a reason that had nothing to do with the script it was
    checking.  Stdin crosses that boundary unchanged.  test_installer.py's
    test_shell_script_parses has done it this way since v0.6.1.
    """
    with open(os.path.join(RIG, "setupcheck.sh"), "rb") as fh:
        src = fh.read()
    out = subprocess.run(["bash", "-n"], input=src,
                         capture_output=True, timeout=60)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
