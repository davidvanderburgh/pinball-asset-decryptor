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


# --------------------------------------------------------------------------
# PAD-94: the advice and the check were about two different sets of Pythons
# --------------------------------------------------------------------------

def test_the_sound_notice_says_which_of_the_two_faults_it_is():
    """★ PAD-94.  "No Windows Python with sounddevice" describes two machines
    at once - one with no Python at all, one with a Python that is missing a
    package - and the user who reported this had the second.  He ran the
    command the tab gave him, pip installed it, and the tab went on saying the
    same thing, because the search had never looked in the directory his
    interpreter was in.  Naming what was found is what makes the two visibly
    different."""
    got = setup_notice(facts(winaudio="0",
                             winpy=r"C:\Program Files\Python313\python.exe"),
                       can_fix=True)
    assert r"C:\Program Files\Python313\python.exe" in got, got
    assert "no sounddevice" in got, got
    assert "pip install" in got, got
    # Nothing found is the OTHER machine, and pip cannot help it.
    none = setup_notice(facts(winaudio="0"), can_fix=True)
    assert "no Windows Python" in none, none
    assert "python.org" in none, none
    # ...and a machine with the good path says neither thing.
    assert setup_env_faults(
        facts(winaudio="1", winpy=r"C:\Python313\python.exe")) == []


def test_no_command_in_the_notice_is_wrapped_in_backticks():
    """★ PAD-94, the second half of it.  This notice is a Tk label, not
    markdown: whatever is in the string is what the user sees and copies.  The
    advice was a command wrapped in them, and a user copies a line whole:
    pasted into PowerShell the trailing backtick is a line continuation, so
    the terminal sits at its >> prompt, and cmd answers that the first word
    is not a recognized command.
    "If I type it in the terminal, it don't work."

    Every other command in this notice is already on its own indented line
    (`wsl --install -d …`), which is the shape that survives a paste.
    """
    said = []
    for bad in (facts(winaudio="0"), facts(interop="0"), facts(user="root"),
                facts(display="none"),
                facts(winaudio="0", winpy=r"C:\Python313\python.exe")):
        said.append(setup_notice(bad, can_fix=True))
        said.extend(w + " " + c for w, c in setup_env_faults(bad))
    for text in said:
        assert "`" not in text, text


def test_the_report_names_the_interpreter_it_found():
    """The same rule the Mac's docker line follows (PAD-74): this is the paste
    that settles a disagreement between the tab and the machine, so "found" on
    its own is not enough - which one, and where."""
    lines = " ".join(setup_report(facts(winaudio="1",
                                        winpy=r"C:\Python313\python.exe")))
    assert r"C:\Python313\python.exe" in lines, lines
    lines = " ".join(setup_report(
        facts(winaudio="0", winpy=r"C:\Program Files\Python313\python.exe")))
    assert "no sounddevice" in lines, lines
    assert r"C:\Program Files\Python313\python.exe" in lines, lines
    lines = " ".join(setup_report(facts(winaudio="0")))
    assert "no Windows Python" in lines, lines
    # An older rig reports neither, and must not be accused of either.
    old = facts()
    del old["winaudio"]
    lines = " ".join(setup_report(old))
    assert "Windows sound player: unknown" in lines, lines


@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_setupcheck_reports_the_interpreter_as_well_as_the_verdict():
    with open(os.path.join(RIG, "setupcheck.sh"), encoding="utf8") as fh:
        src = fh.read()
    assert '"winpy=' in src, "setupcheck.sh no longer reports winpy"
    assert "pad_win_python_any" in src, "the second question is not asked"
    # A PC with no Windows Python leaves the last test in the file false, and
    # a non-zero exit makes setup_state() throw away every fact above it.
    assert src.rstrip().endswith("exit 0"), (
        "the fact printer can exit non-zero")


@pytest.mark.skipif(not (os.path.isdir(RIG) and HAS_BASH),
                    reason="rig or working bash not present")
def test_the_windows_python_search_asks_the_launcher_it_recommends():
    r"""★ PAD-94, the fault itself.

    The tab said "run `py -m pip install sounddevice`" and then looked for the
    result in two hard-coded directories, neither of which was where `py`
    lives on the reporter's machine: an all-users install writes
    ``C:\Program Files\Python313``, and nothing in this rig had ever looked
    there.  So the advice worked, the check could not see it, and the message
    never changed.  Asking the launcher makes the set we check and the set the
    advice changes the same set.

    THE SCRIPT IS FED ON STDIN, whole, for the reason
    test_setupcheck_still_parses_as_key_value gives: `bash` is git-bash on one
    Windows host and the WSL launcher on the next, and only one of them can
    read `C:\...\padpath.sh` as a path.  The fakes are built by the script
    itself, in its own mktemp, so nothing crosses that boundary either.
    """
    with open(os.path.join(RIG, "padpath.sh"), encoding="utf8") as fh:
        src = fh.read()
    harness = r"""
tmp=$(mktemp -d) || exit 1
cat > "$tmp/pylauncher" <<'LAUNCH'
#!/bin/sh
# `py -0p` as a real launcher prints it: CRLF, a tag column, the default
# starred, and one path with a space in it.
[ "$1" = "-0p" ] || exit 1
printf -- '-V:3.13          C:\\Users\\ralf'
printf -- '\\AppData\\Local\\Programs\\Python\\Python313\\python.exe\r\n'
printf -- '-V:3.12 *        C:\\Program Files\\Python312\\python.exe\r\n'
LAUNCH
cat > "$tmp/wslpath" <<'WSLP'
#!/bin/sh
# -u only: C:\a\b -> /mnt/c/a/b, which is all pad_win_pythons asks of it.
d=$(printf '%s' "${2%%:*}" | tr 'A-Z' 'a-z')
r=$(printf '%s' "${2#*:}" | tr '\\' '/')
printf '/mnt/%s%s\n' "$d" "$r"
WSLP
chmod +x "$tmp/pylauncher" "$tmp/wslpath"
echo "--- asked"
PATH="$tmp:$PATH" PAD_WINPY_LAUNCHER="$tmp/pylauncher" pad_win_pythons
echo "--- fallback"
PAD_WINPY_LAUNCHER=/nonexistent pad_win_pythons
echo "--- usable"
: > "$tmp/store.exe"
pad_win_python_usable "$tmp/store.exe" && echo "EMPTY IS RUNNABLE"
pad_win_python_usable "$tmp/wslpath" && echo "real one is runnable"
"""
    out = subprocess.run(["bash", "-s"], input=(src + harness).encode("utf-8"),
                         capture_output=True, timeout=120)
    said = out.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    # Every marker, before any split: a probe that runs a WINDOWS child
    # can swallow this script's own stdin (it is fed on stdin), and the
    # symptom is simply that the rest of the harness never runs.
    assert "--- usable" in said, said
    asked, rest = said.split("--- fallback", 1)
    fallback, usable = rest.split("--- usable", 1)
    asked = [ln for ln in asked.splitlines() if ln.startswith("/")]
    # THE DEFAULT LEADS.  `py -m pip install` installs into the starred one, so
    # it has to be the first thing checked, or the advice can fix a machine the
    # check goes on failing.
    assert asked[0] == "/mnt/c/Program Files/Python312/python.exe", asked
    assert ("/mnt/c/Users/ralf/AppData/Local/Programs/Python/Python313"
            "/python.exe") in asked, asked
    # ...and the space in "Program Files" arrives whole rather than as two
    # candidates, which is the whole reason these are read a line at a time.
    assert not any(ln == "/mnt/c/Program" for ln in asked), asked
    # With no launcher, the directories are still searched - and now include
    # the one an all-users installer writes to.
    assert any(ln.startswith("/mnt/c/Program Files/Python3")
               for ln in fallback.splitlines()), fallback
    assert any(ln.startswith("/mnt/c/Python3")
               for ln in fallback.splitlines()), fallback
    # A Store install's zero-byte app-execution alias is executable to every
    # test /mnt/c can make and is not a program.
    assert "EMPTY IS RUNNABLE" not in usable, usable
    assert "real one is runnable" in usable, usable


# --------------------------------------------------------------------------
# PAD-95: the advice named a program the machine did not have, and PAD was
# shipping the Python it was telling the user to go and install
# --------------------------------------------------------------------------

#: What the Windows installer puts beside the app, on every packaged install.
APP_PY = r"C:\Program Files\Pinball Asset Decryptor\python\python.exe"
#: ...and the front door the playfield window is opened through (PAD-99):
#: the same install, in its GUI-subsystem spelling.
APP_PYW = APP_PY.replace("python.exe", "pythonw.exe")


def test_when_the_python_is_ours_the_answer_is_a_menu_not_a_command():
    """★ PAD-95.  The reporter ran what the tab told him to and his terminal
    answered

        "py" wurde nicht als Name eines Cmdlet ... erkannt

    - the launcher is an OPTIONAL tick in the Windows installer and he had
    never installed a Python at all.  Meanwhile every packaged install ships
    one: an embeddable CPython with pip, beside the app.  When that is the
    interpreter missing the package there is nothing to type, so the notice
    must not hand him a command line for it - the app's own prerequisite
    installer is the whole answer.
    """
    got = setup_notice(facts(winaudio="0", winpy=APP_PY, padpy=APP_PY),
                       can_fix=True)
    assert "PAD's own Python" in got, got
    assert "Install / repair prerequisites" in got, got
    assert "Stern Pinball" in got, got
    # Not one word of the old advice, either half of it.
    assert "py -m pip" not in got, got
    assert "python.org" not in got, got


def test_a_python_of_the_users_own_is_named_and_paste_safe():
    """The other machine, and its path is not a command.

    PowerShell reads a quoted path in the first word as a STRING - it prints
    it and runs nothing - and the paths that need the quotes are exactly the
    ``C:\\Program Files`` ones PAD-94 went looking for.  ``cd`` there and run
    ``.\\python.exe``: two lines that mean the same thing in PowerShell and in
    cmd.  Same class of trap as PAD-94's backticks - what is on this label is
    what gets pasted.
    """
    theirs = r"C:\Program Files\Python313\python.exe"
    got = setup_notice(facts(winaudio="0", winpy=theirs, padpy=APP_PY),
                       can_fix=True)
    assert theirs in got, got
    assert 'cd "C:\\Program Files\\Python313"' in got, got
    assert ".\\python.exe -m pip install --user sounddevice" in got, got
    assert "py -m pip" not in got, got
    # A quoted path is never the first word of a line here.
    for line in got.splitlines():
        assert not line.strip().startswith('"'), got


def test_no_python_anywhere_still_never_says_py():
    """The launcher cannot be assumed even on a PC that installs Python next:
    it is a checkbox, and so is PATH.  Name the checkbox and give the command
    that ticking it produces."""
    got = setup_notice(facts(winaudio="0"), can_fix=True)
    assert "python.org" in got, got
    assert "python.exe to PATH" in got, got
    assert "python -m pip install --user sounddevice" in got, got
    assert "py -m pip" not in got, got


def test_the_report_says_whose_python_it_is():
    """The paste that settles a disagreement has to distinguish the two, since
    one is repaired by pressing something in this app and the other by typing
    something in a terminal."""
    lines = " ".join(setup_report(facts(winaudio="0", winpy=APP_PY,
                                        padpy=APP_PY)))
    assert "(PAD's own)" in lines, lines
    assert "no sounddevice" in lines, lines
    # A DIFFERENT interpreter: name ours as well, so the paste says both.
    theirs = r"C:\Python313\python.exe"
    lines = " ".join(setup_report(facts(winaudio="1", winpy=theirs,
                                        padpy=APP_PY)))
    assert theirs in lines, lines
    assert "PAD's own Python: " + APP_PY in lines, lines
    assert "(PAD's own)" not in lines, lines
    # An older rig reports no padpy at all and must not be second-guessed.
    lines = " ".join(setup_report(facts(winaudio="0", winpy=theirs)))
    assert "(PAD's own)" not in lines, lines
    assert "PAD's own Python:" not in lines, lines


def test_the_new_notices_carry_no_backtick_either():
    """PAD-94's rule, over PAD-95's strings: this is a Tk label, so whatever is
    in it is what the user copies."""
    for bad in (facts(winaudio="0", winpy=APP_PY, padpy=APP_PY),
                facts(winaudio="0", winpy=r"C:\Program Files\Py\python.exe",
                      padpy=APP_PY),
                facts(winaudio="0", padpy=APP_PY)):
        said = [setup_notice(bad, can_fix=True)]
        said.extend(w + " " + c for w, c in setup_env_faults(bad))
        for text in said:
            assert "`" not in text, text


@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_setupcheck_reports_which_python_is_pads_own():
    with open(os.path.join(RIG, "setupcheck.sh"), encoding="utf8") as fh:
        src = fh.read()
    assert '"padpy=' in src, "setupcheck.sh no longer reports padpy"
    assert "PAD_WINPYTHON" in src, "the app's own interpreter is not asked for"
    assert src.rstrip().endswith("exit 0"), (
        "the fact printer can exit non-zero")


@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_the_run_asks_for_its_advice_rather_than_carrying_a_copy():
    """playaudio.sh printed the same `py` line the tab did, so fixing one
    would have left the other saying it during every run."""
    with open(os.path.join(RIG, "playaudio.sh"), encoding="utf8") as fh:
        play = fh.read()
    assert "pad_sounddevice_hint" in play
    for line in play.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "py -m pip" not in line, line


@pytest.mark.skipif(not (os.path.isdir(RIG) and HAS_BASH),
                    reason="rig or working bash not present")
def test_the_search_leads_with_pads_own_python_and_asks_path_too():
    r"""★ PAD-95, the search half.

    Two things the rig could not find before: the interpreter PAD ships (it
    only ever looked for one the USER had installed) and one installed without
    the ``py`` launcher (it asked the launcher and three fixed directories).
    The reporter had no launcher, which is what made the advice unrunnable and
    the check blind at the same time.

    Fed on stdin, whole, for the reason the other bash tests here give: `bash`
    is git-bash on one Windows host and the WSL launcher on the next.
    """
    with open(os.path.join(RIG, "padpath.sh"), encoding="utf8") as fh:
        src = fh.read()
    harness = r"""
tmp=$(mktemp -d) || exit 1
printf '#!/bin/sh\nexit 0\n' > "$tmp/python.exe"
printf '#!/bin/sh\nexit 0\n' > "$tmp/ours.exe"
chmod +x "$tmp/python.exe" "$tmp/ours.exe"
export PATH="$tmp:$PATH"
echo "--- order"
PAD_WINPY_LAUNCHER=/nonexistent PAD_WINPYTHON="$tmp/ours.exe" pad_win_pythons
"""
    out = subprocess.run(["bash", "-s"], input=(src + harness).encode("utf-8"),
                         capture_output=True, timeout=120)
    said = out.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert "--- order" in said, said
    order = [ln for ln in said.split("--- order", 1)[1].splitlines() if ln]
    # OURS FIRST, because it is the one whose missing package the app can fix
    # by itself - and because a machine with no Python of its own has to stop
    # being told there is no Windows Python at all.
    assert order[0].endswith("/ours.exe"), order
    # ...and a python.exe on PATH counts, launcher or no launcher.
    assert any(ln.endswith("/python.exe") and "/tmp" in ln
               for ln in order), order


@pytest.mark.skipif(not (os.path.isdir(RIG) and HAS_BASH),
                    reason="rig or working bash not present")
def test_the_rigs_own_advice_fits_the_machine_it_is_printed_on():
    """One definition of what to do about a missing sounddevice, shared by the
    run's log and (through setupcheck.sh's facts) the tab - and none of its
    three answers is `py`."""
    with open(os.path.join(RIG, "padpath.sh"), encoding="utf8") as fh:
        src = fh.read()
    harness = r"""
tmp=$(mktemp -d) || exit 1
cat > "$tmp/wslpath" <<'WSLP'
#!/bin/sh
# -w only: every candidate here is fake, so answer with the layout that
# carries the space - the one a full-path command cannot survive.
printf 'C:\\Program Files\\Python313\\python.exe\n'
WSLP
printf '#!/bin/sh\nexit 0\n' > "$tmp/ours.exe"
printf '#!/bin/sh\nexit 0\n' > "$tmp/theirs.exe"
chmod +x "$tmp/wslpath" "$tmp/ours.exe" "$tmp/theirs.exe"
export PATH="$tmp:$PATH"
echo "--- none"
pad_win_pythons() { :; }
PAD_WINPYTHON="$tmp/ours.exe" pad_sounddevice_hint
echo "--- theirs"
pad_win_pythons() { printf '%s\n' "$tmp/theirs.exe"; }
PAD_WINPYTHON="$tmp/ours.exe" pad_sounddevice_hint
echo "--- ours"
pad_win_pythons() { printf '%s\n' "$tmp/ours.exe"; }
PAD_WINPYTHON="$tmp/ours.exe" pad_sounddevice_hint
rm -rf "$tmp"
"""
    out = subprocess.run(["bash", "-s"], input=(src + harness).encode("utf-8"),
                         capture_output=True, timeout=120)
    said = out.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert "--- ours" in said, said
    none, rest = said.split("--- theirs", 1)
    theirs, ours = rest.split("--- ours", 1)
    # No Python at all: name the checkbox, not the launcher.
    assert "python.org" in none, none
    assert "python -m pip install --user sounddevice" in none, none
    # One of the user's: cd to it and run it from there, so a path with a
    # space in it is still a command in PowerShell.
    assert 'cd "C:\\Program Files\\Python313"' in theirs, theirs
    assert ".\\python.exe -m pip install --user sounddevice" in theirs, theirs
    # Ours: nothing to type at all.
    assert "Install / repair prerequisites" in ours, ours
    assert "Stern Pinball" in ours, ours
    for block in (none, theirs, ours):
        assert "py -m pip" not in block, block


# --------------------------------------------------------------------------
# ★ PAD-99: the OTHER Windows Python - the one that draws the playfield window
#
# The window is a Windows process (this WSL has no Tk), drawn with tkinter AND
# Pillow, and the run used to open it with whatever `pythonw.exe` PATH held.
# With interop on, PATH here is WINDOWS' PATH, so that is whichever Python the
# user installed - and a python.org install has tkinter and no Pillow.  The
# reporter's runs therefore came up with a game window, sound and switches and
# NO PLAYFIELD, while the interpreter that could draw it (PAD's own, which the
# app hands the rig as PAD_WINPYTHON) sat unasked on the same disk.
# --------------------------------------------------------------------------

def _pf_facts(**over):
    """A healthy WSL plus the two facts this ticket added."""
    return facts(padpy=APP_PY, winpy=APP_PY, **over)


def test_the_report_names_the_interpreter_that_opens_the_playfield():
    """The paste that settles “I have no playfield window”, which had no line
    about the playfield in it at all."""
    line = next(ln for ln in setup_report(
        _pf_facts(winpf="1", pfpy=APP_PYW)) if "playfield" in ln)
    assert APP_PYW in line, line
    # ...AND WHOSE IT IS, through the twin spelling: `padpy` is python.exe and
    # the window is opened with pythonw.exe, which is the same install by its
    # other front door.  A plain compare calls PAD's own interpreter
    # somebody else's, which is the difference between "press this" and "type
    # this" in every message built on the answer.
    assert "(PAD's own)" in line, line


def test_a_python_without_pillow_is_reported_as_the_reason():
    """Two faults, not one: no Windows Python at all, and one that is missing
    the package.  Same split the sound line already makes."""
    theirs = r"C:\Users\d\AppData\Local\Programs\Python\Python313\pythonw.exe"
    line = next(ln for ln in setup_report(
        _pf_facts(winpf="0", pfpy=theirs)) if "playfield" in ln)
    assert theirs in line and "Pillow" in line, line
    assert "(PAD's own)" not in line, line
    line = next(ln for ln in setup_report(
        _pf_facts(winpf="0")) if "playfield" in ln)
    assert "no Windows Python" in line, line
    # An older rig reports neither key, and silence is not a fault.
    line = next(ln for ln in setup_report(_pf_facts()) if "playfield" in ln)
    assert "unknown" in line, line


def test_the_tab_says_it_before_the_run_rather_than_after():
    """The reporter's machine passed every package check, so the tab said
    nothing - and the fault it could not name costs a whole window."""
    theirs = r"C:\Users\d\AppData\Local\Programs\Python\Python313\pythonw.exe"
    bad = _pf_facts(winpf="0", pfpy=theirs)
    said = setup_env_faults(bad)
    assert len(said) == 1, said
    what, todo = said[0]
    assert "Pillow" in what and "playfield" in what, what
    # THE COMMAND HAS TO BE RUNNABLE, and two traps sit on that line.  A quoted
    # path is a STRING in PowerShell, so cd to the folder and run it from
    # there; and pythonw.exe has no console to print pip's output to, so the
    # console twin is what gets typed.
    assert 'cd "C:\\Users\\d\\AppData\\Local\\Programs\\Python\\Python313"' \
        in todo, todo
    assert ".\\python.exe -m pip install --user Pillow" in todo, todo
    assert "pythonw.exe -m pip" not in todo, todo
    # ...and it is not a machine that "cannot run the emulator".
    assert not setup_settled(bad)
    assert setup_ok(bad)
    # Nothing at all from a rig that does not report the fact, and nothing
    # extra when interop is off - that branch already names this window.
    assert setup_env_faults(_pf_facts()) == []
    assert not any("Pillow" in w for w, _ in
                   setup_env_faults(_pf_facts(winpf="0", pfpy=theirs,
                                              interop="0")))


def test_our_own_python_missing_pillow_is_not_a_pip_command():
    """It is a reinstall: Pillow goes into the bundled interpreter at build
    time, so there is no prerequisite tick that puts it back."""
    what, todo = setup_env_faults(_pf_facts(winpf="0", pfpy=APP_PYW))[0]
    assert "PAD's own Python" in what, what
    assert "pip install" not in todo, todo
    assert "Reinstall PAD" in todo, todo


def test_the_playfield_notices_carry_no_backtick_either():
    """PAD-94's rule, over PAD-99's strings: this is a Tk label, so whatever is
    in it is what the user copies."""
    for bad in (_pf_facts(winpf="0", pfpy=APP_PYW),
                _pf_facts(winpf="0", pfpy=r"C:\Py 3\pythonw.exe"),
                _pf_facts(winpf="0")):
        said = [setup_notice(bad, can_fix=False)]
        said.extend(w + " " + c for w, c in setup_env_faults(bad))
        for text in said:
            assert "`" not in text, text


@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_the_run_no_longer_opens_the_playfield_with_whatever_path_holds():
    """The regression itself, in one line of watch.sh.

    `PF_PY=${PAD_PF_PYTHON:-pythonw.exe}` followed by `command -v` is what made
    the choice PATH's, and PATH's answer was a Python with no Pillow.
    """
    with open(os.path.join(RIG, "watch.sh"), encoding="utf8") as fh:
        src = fh.read()
    # Comments skipped, same as the playaudio check above: the launch block's
    # own header quotes the line it replaced, which is where that explanation
    # belongs.
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "PAD_PF_PYTHON:-pythonw.exe" not in line, (
            "watch.sh is back to taking the first pythonw.exe on PATH")
    assert "pad_win_pf_python" in src, "watch.sh chooses no interpreter"
    # The fallback stays: a launch that fails writes a traceback the run
    # prints, and that names the missing package to the one person who can
    # install it.  Refusing to launch would hide it again.
    assert "pad_win_pf_python_any" in src, "no fallback launch"


@pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
def test_setupcheck_reports_the_playfield_interpreter_too():
    with open(os.path.join(RIG, "setupcheck.sh"), encoding="utf8") as fh:
        src = fh.read()
    assert "winpf=" in src, "setupcheck.sh reports no winpf"
    assert "pfpy=" in src, "setupcheck.sh names no pfpy"
    assert src.rstrip().endswith("exit 0"), (
        "the fact printer can exit non-zero")


@pytest.mark.skipif(not (os.path.isdir(RIG) and HAS_BASH),
                    reason="rig or working bash not present")
def test_the_playfield_python_is_probed_for_what_it_has_to_import():
    r"""★ PAD-99, the search itself.

    ``pad_win_pythons`` is stubbed so the candidate list is exactly the one
    each case is about - the machine underneath this test has a real Windows
    Python of its own, and the answer must not depend on which.

    Fed on stdin, whole, for the reason the other bash tests here give: `bash`
    is git-bash on one Windows host and the WSL launcher on the next.
    """
    with open(os.path.join(RIG, "padpath.sh"), encoding="utf8") as fh:
        src = fh.read()
    harness = r"""
tmp=$(mktemp -d) || exit 1
# The import probe is what each case is about, so that is the only question
# the fakes answer differently: `-c ""` (can this shell run the .exe at all?)
# always succeeds here, the way it does on any machine with interop on.
mk() {   # mk <dir> <exit-code-for-the-import-probe>
    mkdir -p "$tmp/$1"
    printf '#!/bin/sh\ncase "$2" in *import*) exit %s;; esac\nexit 0\n' "$2" \
        > "$tmp/$1/python.exe"
    cp "$tmp/$1/python.exe" "$tmp/$1/pythonw.exe"
    chmod +x "$tmp/$1/python.exe" "$tmp/$1/pythonw.exe"
}
mk ours 0
mk theirs 0
echo "--- ours"
pad_win_pythons() { printf '%s\n' "$tmp/ours/python.exe" \
                                  "$tmp/theirs/python.exe"; }
pad_win_pf_python
echo "--- theirs"
mk ours 1
pad_win_pf_python
echo "--- none"
mk theirs 1
echo "pf=[$(pad_win_pf_python)]"
pad_win_pf_python_any
echo "--- noexec"
mkdir -p "$tmp/noexec"
printf 'MZ a windows binary, not a linux one\n' > "$tmp/noexec/python.exe"
chmod +x "$tmp/noexec/python.exe"
pad_win_pythons() { printf '%s\n' "$tmp/noexec/python.exe"; }
echo "pf=[$(pad_win_pf_python)] any=[$(pad_win_pf_python_any)]"
echo "--- notwin"
mkdir -p "$tmp/bare"
printf '#!/bin/sh\nexit 0\n' > "$tmp/bare/python.exe"
chmod +x "$tmp/bare/python.exe"
pad_win_pythons() { printf '%s\n' "$tmp/bare/python.exe"; }
pad_win_pf_python
rm -rf "$tmp"
"""
    out = subprocess.run(["bash", "-s"], input=(src + harness).encode("utf-8"),
                         capture_output=True, timeout=180)
    said = out.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    blocks = {}
    for chunk in said.split("--- ")[1:]:
        name, _, body = chunk.partition("\n")
        blocks[name.strip()] = [ln for ln in body.splitlines() if ln]
    # OURS LEADS, and the windowed twin is what gets returned: pythonw.exe is
    # what keeps a console window from sitting beside the playfield for the
    # whole run, but it cannot be probed (it has nowhere to print), so the
    # question is asked of python.exe and only the answer is translated.
    assert blocks["ours"] == [blocks["ours"][0]], blocks["ours"]
    assert blocks["ours"][0].endswith("/ours/pythonw.exe"), blocks
    # A candidate that cannot import both is SKIPPED, not launched.  This is
    # the whole ticket: PATH's answer was an interpreter with tkinter and no
    # Pillow, and it was taken without a question being asked.
    assert blocks["theirs"][0].endswith("/theirs/pythonw.exe"), blocks
    # Nothing can draw it: no choice, and a fallback so the failure is one the
    # run can print rather than a window that never appears.
    assert blocks["none"][0] == "pf=[]", blocks
    assert blocks["none"][1].endswith("/ours/pythonw.exe"), blocks
    # A .exe THIS SHELL CANNOT RUN is not a fallback either, and that is the
    # interop-off machine: every Windows Python under /mnt/c is a file it can
    # see and none of them can be executed.  watch.sh has an answer for that
    # one - it asks PAD to open the window, from the Windows side - and it only
    # gets to give it if nothing here claims to have found an interpreter.
    assert blocks["noexec"] == ["pf=[] any=[]"], blocks
    # No twin beside it: run the console one rather than nothing at all.
    assert blocks["notwin"][0].endswith("/bare/python.exe"), blocks
