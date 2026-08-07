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
from types import SimpleNamespace

import pytest

from pinball_decryptor.gui import emulate_tab

from pinball_decryptor.gui.emulate_tab import (DEFAULT_RIG_DIR, parse_status,
                                               rig_cmd_root, setup_notice,
                                               setup_ok, setup_state,
                                               setup_summary,
                                               state_text, _wsl_path)

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
    monkeypatch.setattr(emulate_tab.subprocess, "run", _fake_run(rc=0))
    assert emulate_tab.docker_state() == "ok"
    monkeypatch.setattr(emulate_tab.subprocess, "run", _fake_run(rc=1))
    assert emulate_tab.docker_state() == "stopped"
    monkeypatch.setattr(emulate_tab.subprocess, "run",
                        _fake_run(raises=FileNotFoundError()))
    assert emulate_tab.docker_state() == "absent"


def test_a_slow_docker_is_starting_not_missing(monkeypatch):
    """`docker info` against a daemon that is waking up can time out, and
    reporting that as "not installed" would send the user to reinstall
    something they already have."""
    import subprocess as sp
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


def test_a_ready_docker_leaves_no_notice_behind(tmp_path):
    """The button and the message pack themselves only when there is something
    to say.  A Mac with Docker running should look like every other machine."""
    root, panel = _panel(tmp_path)
    _quiesce(panel)
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

_READY = {"qemu": "1", "armgcc": "1", "debugfs": "1", "fuse": "1",
          "binfmt": "1", "iswsl": "1", "wslconf": "1"}


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
    """The tab explains four packages and setupfix.sh installs them.  Two
    lists in two languages is precisely how they drift."""
    fix = _rig_text("setupfix.sh")
    for key, pkg, _why in emulate_tab._SETUP_TOOLS:
        assert 'sudo' not in pkg
        assert pkg in fix, "%s (%s) is explained but never installed" % (pkg,
                                                                         key)
        assert '_get "$facts" %s' % key in fix


def test_the_repair_does_not_hide_apt_failure_behind_a_pipe():
    """`apt-get ... | sed` reports SED's exit status, so a failed install
    reads as a clean one and the tab would announce success."""
    fix = _rig_text("setupfix.sh")
    for line in fix.splitlines():
        if "apt-get install" in line or "apt-get update" in line:
            assert "| sed" not in line, line


def test_the_probe_reuses_the_rig_s_own_binfmt_detection():
    """setupcheck.sh must not grow its own copy of "is there an ARM handler" -
    ensurebuild.sh owns that, and the run itself uses ensurebuild's."""
    check = _rig_text("setupcheck.sh")
    assert "ensurebuild.sh" in check
    assert "_pad_binfmt_arm" in check
    assert "_pad_binfmt_advice" in check
    assert "binfmt_misc/qemu-arm" not in check, "that is a second detector"
