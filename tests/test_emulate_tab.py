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
    for key, pkg, _why in emulate_tab._SETUP_TOOLS:
        assert 'sudo' not in pkg
        assert pkg in check, "%s (%s) is explained but never installed" % (
            pkg, key)
        assert "%s:" % key in check
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
