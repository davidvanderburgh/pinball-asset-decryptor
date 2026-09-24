"""The Modes tab's run logic, on the web UI (the old Tk Modes tab's tests, retargeted).

Every test here once drove the Tk ``ModesPanel`` through a Tk window. They now drive the
web Modes service (``webui/tabs/modes.py`` with ``webui/modes_tryit.py``) in-process through
``tests/webui_harness.py``, or call the logic it runs directly (``webui/write_scan.py``,
``webui/modes_filmcut.py``, ``webui/help_content.py`` and the stern plugins). Nothing here
starts a process, touches the emulator or opens a window: the rig commands are stood in
for, and any process start fails the test.
"""

import json
import os
import pathlib
import threading
import time
import types

import pytest

from tests.webui_harness import web_app


# ---------------------------------------------------------------------- helpers
def _svc(w):
    return w.window.service("modes")


def _wait(w, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        try:
            if cond():
                return True
        except (OSError, ValueError):
            # a poll that reads a file mid-save: Windows refuses the read while
            # os.replace swaps it in, or the JSON is not all there yet
            pass
        time.sleep(0.02)
    w.drain()
    return cond()


def _project(w, path):
    """Point the project folder (Write's assets folder) at *path* ("" for none), as the
    window's traces did, and let the Modes tab read it."""
    if path:
        os.makedirs(str(path), exist_ok=True)
    svc = _svc(w)

    def go():
        var = svc._project_var()
        try:
            var.set(str(path) if path else "")
        except Exception:                           # noqa: BLE001 - another tab's trace
            pass
        svc._refresh_all()
    w.run(go)
    w.drain()


def _set(w, key, value):
    w.call("ui.set", "modes", key, value)


def _f(w, key, value):
    """One field of the form, as the page edits it."""
    _set(w, "f:" + key, value)


def _save(w):
    w.run(_svc(w).save_now)
    w.drain()


def _st(w):
    return w.state("modes")


def _status(w):
    return w.state("modes")["status"]


def _line(w):
    return w.state("modes")["tryit_line"]


def _tryit(w):
    return w.state("modes")["tryit"]


def _select(w, slug):
    w.call("modes.select", slug, "form")
    w.drain()


def _ok(stdout="ok"):
    return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _no_wsl(monkeypatch):
    """Any process start at all fails the test: these reach no WSL and launch nothing."""
    import subprocess

    def refuse(*a, **kw):
        raise AssertionError("a Modes test started a process: %r" % (a[:1],))
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


def _fake_rig(svc, ran=None):
    """The tab's rig commands as plain lists (``RIG`` as the user, ``ROOT`` as root), and
    (with ``ran``) every command recorded and answered ok instead of run."""
    svc._rig_cmd = lambda script, *args: ["RIG", script] + [str(a) for a in args]
    svc._rig_cmd_root = lambda script, *args: ["ROOT", script] + [str(a) for a in args]
    if ran is not None:
        svc._run_fn = lambda cmd, **kw: ran.append(cmd) or _ok()


def _tryit_ready(svc, tmp_path, handed, base="try"):
    """Try it's surroundings stood in for: its folder under tmp_path, a hand-off that records
    the preparation and accepts, an Emulate tab with nothing to say before the hand-off, a
    user (not root) launch, and no ffmpeg."""
    svc._tryit_base = str(tmp_path / base)
    svc._try_fn = lambda prepare: handed.append(prepare) or (True, "")
    svc._emulate_state = lambda: None
    svc._as_root = lambda: False
    svc._platform = "win32"
    svc._ffmpeg_fn = lambda: None


def _tryit_setup(w, tmp_path, monkeypatch, name="QUIET"):
    """A project with one quiet form mode open in the Modes tab, the rig and its commands
    stood in for (``ran`` records them), and a Try it hand-off that records the preparation
    and accepts (``handed``). Returns ``(svc, ran, handed, card)``."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
    _project(w, project)
    _no_wsl(monkeypatch)
    svc = _svc(w)
    ran, handed = [], []
    _fake_rig(svc, ran)
    _tryit_ready(svc, tmp_path, handed)
    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    return svc, ran, handed, card


def _modes_card_project(tmp_path, card_name, card_version=None, folder="proj"):
    """A project folder whose extract record names ``card_name`` (item 148)."""
    project = tmp_path / folder
    project.mkdir()
    rec = {"input_path": "D:\\cards\\" + card_name, "input_name": card_name, "size": 1, "mtime": 1}
    if card_version:
        rec["card_version"] = card_version
    (project / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
    return project


def _stock_modes_project(tmp_path, name="godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw"):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".extract_source.json").write_text(json.dumps(
        {"input_path": "D:\\cards\\" + name, "input_name": name, "size": 1, "mtime": 1}),
        encoding="utf-8")
    return project


def _modes_js():
    root = pathlib.Path(__file__).resolve().parents[1] / "pinball_decryptor" / "webui" / "static"
    return (root / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")


def _wait_threads(name, timeout=120.0):
    end = time.time() + timeout
    for t in [t for t in threading.enumerate() if t.name == name]:
        t.join(max(0.0, end - time.time()))
        assert not t.is_alive(), name


# ---------------------------------------------------------------------- the tab and the form
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_is_built_and_sits_between_defaults_and_write(tmp_path):
    """The window builds the Modes tab, and it sits beside Defaults, before Write.

    Item 127 shipped this tab EMPTY: its builder existed and nothing called it, and every
    earlier test constructed the panel by hand, so none of them could see it. This one looks
    at the real window's tabs. Placement is David's (2026-09-16): a mode is one more change
    a card build applies, so it is authored before Write like the tabs to its left (on the
    web, in the Make group with Defaults, ahead of the Build group that holds Write).
    """
    with web_app(tmp_path, mfr="stern") as w:
        tabs = [t for t in w.state("shell")["tabs"] if t.get("visible")]
        keys = [t["key"] for t in tabs]
        groups = {t["key"]: t.get("group") for t in tabs}
        assert groups["Modes"] == groups["Default Settings"] == "Make", groups
        assert abs(keys.index("Default Settings") - keys.index("Modes")) == 1, keys
        assert keys.index("Modes") < keys.index("Write"), keys
        assert keys.index("Default Settings") < keys.index("Write"), keys
        assert _svc(w) is not None and w.state("modes")["about"]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_makes_and_edits_a_mode_in_the_project(tmp_path):
    """New makes a mode IN THE PROJECT, and an edit on the form lands in its mode.json.

    David, 2026-09-16: a mode belongs to the card project and reaches a card through
    Write. The starter is buildable as it stands (the runtime refuses a mode without a
    clock or a trigger count), shots are picked BY NAME, and the list follows a rename.
    """
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        slug = w.call("modes.new")
        st = _st(w)
        assert slug == "new_mode" and st["rows"][0]["name"] == "NEW MODE"
        assert "Ready to build" in st["status"]
        assert st["preview"] and st["preview"].get("path")         # the screen preview drew

        _f(w, "name", "KAIJU RUSH")
        _f(w, "start_shot", "Maser target")
        _f(w, "award", "2,000,000")
        w.call("modes.set_shots", ["Left ramp", "Powerline center"])
        _f(w, "clip", "title")
        _save(w)
        data = json.loads((project / "modes" / slug / "mode.json").read_text(encoding="utf-8"))
        assert data["name"] == "KAIJU RUSH" and data["award"] == 2000000
        assert data["scoring_shots"] == ["Left ramp", "Powerline center"] and data["clip"] == "title"
        assert _st(w)["rows"][0]["name"] == "KAIJU RUSH"
        spec = MP.load(str(project / "modes" / slug / "mode.json"))
        assert "0x20100000" in MP.runtime_cfg(spec, slug)          # the named shots, as a mask

        _f(w, "seconds", "0")
        _save(w)
        assert "at least a second" in _status(w)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_examples_add_kaiju_rush_and_an_empty_editor_keeps_its_labels(tmp_path):
    """Two things David saw on 2026-09-16 with a project that had no modes: the form was
    "barely legible" in the dark theme, and KAIJU RUSH was nowhere to be found.

    The first was every control under the editor being greyed with no mode open, labels
    included; the page now greys only what a person types in or clicks (``editor_on``). The
    second is the Examples menu: KAIJU RUSH, as it ran on the machine, one click away.
    """
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        st = _st(w)
        assert "Examples" in st["status"]
        assert st["open"] is False and st["editor_on"] is False     # nothing to edit yet
        assert st["ex_ok"] is True

        w.call("modes.example", "KAIJU RUSH")
        st = _st(w)
        assert st["rows"][0]["name"] == "KAIJU RUSH"
        assert st["editor_on"] is True
        spec = MP.load(str(project / "modes" / "kaiju_rush" / "mode.json"))
        assert spec.start_shot == "Maser target" and spec.start_count == 3 and spec.seconds == 30
        assert "0x08000000 3" in MP.runtime_cfg(spec, "kaiju_rush")   # the machine-proven trigger


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_follows_the_project_and_never_leaks_an_edit(tmp_path):
    """Switching project shows THAT project's modes, and an edit in flight is saved to
    the project it was made in - never into the one switched to."""
    a, b = tmp_path / "a", tmp_path / "b"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, a)
        slug = w.call("modes.new")
        _f(w, "name", "ONLY IN A")                          # debounced, not yet saved
        _project(w, b)
        assert _st(w)["rows"] == [] and not (b / "modes").exists()
        assert '"name": "ONLY IN A"' in (a / "modes" / slug / "mode.json").read_text(encoding="utf-8")
        _project(w, a)
        assert _st(w)["rows"][0]["name"] == "ONLY IN A"
        w.run(_svc(w).delete_mode, slug)
        assert _st(w)["rows"] == [] and not (a / "modes" / slug).exists()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_without_a_project_says_where_modes_go(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, "")
        assert w.run(_svc(w).new_mode) is None
        assert "Extract tab" in _st(w)["project_label"]


# ---------------------------------------------------------------------- item 127: Try it
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_tryit_section_is_built_and_its_env_is_pure(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        _no_wsl(monkeypatch)
        svc = _svc(w)
        svc._tryit_base = str(tmp_path / "try")
        env = svc.tryit_env()
        assert env[0].startswith("PAD_OVERRIDE_DIR=") and env[0].endswith("/try/set")
        assert "\\" not in env[0]
        assert env[1] == "PAD_MODE_SO=/lib/pad_mode.so"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_tryit_commands_name_the_right_slot(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        _no_wsl(monkeypatch)
        svc = _svc(w)
        _fake_rig(svc)
        assert svc.trigger_cmd(0) == ["RIG", "modes/tryit.sh", "start", "0"]
        assert svc.trigger_cmd(3) == ["RIG", "modes/tryit.sh", "start", "3"]
        assert svc.stop_cmd() == ["RIG", "modes/tryit.sh", "stop"]
        stage = str(tmp_path / "rig")
        cmd = svc.install_cmd(stage)
        assert cmd[:3] == ["RIG", "modes/tryit.sh", "install"] and "\\" not in cmd[3]
        push = svc.push_cmd(os.path.join(stage, "push", "mode2.cfg"), 2)
        assert push[:3] == ["RIG", "modes/tryit.sh", "push"] and push[-1] == "2"
        build = svc.compile_cmd(os.path.join(stage, "pad_mode.so"), [str(tmp_path / "blitz.c")])
        assert build[1] == "modes/sdk/build_mode.sh" and build[2] == "-o"
        assert build[-1].endswith("modes/sdk/mode_file.c") and build[-2].endswith("blitz.c")
    # ...and the rig script those commands run is there, with every verb
    rig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tools", "spike2_emu", "modes", "tryit.sh")
    body = open(rig, encoding="utf-8").read()
    for verb in ("install)", "start)", "stop)", "push)"):
        assert verb in body
    assert '"$LIB/pad_mode.so"' in body and '"$DUMP/game.port"' in body


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_hands_the_emulate_tab_a_preparation(tmp_path, monkeypatch):
    """Try it launches NOTHING itself: it hands a preparation to the Emulate tab's own
    launch. The preparation builds the set, installs through the rig script, and returns
    the env; while the run is up an autosave pushes the regenerated mode file."""
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, card = _tryit_setup(w, tmp_path, monkeypatch)
        running = [False]
        svc._running_fn = lambda: running[0]
        _writes_builder(monkeypatch, [])
        assert w.run(svc.on_try) is True
        assert handed == [svc.tryit_prepare] and not ran     # nothing launched, nothing run

        env = handed[0](str(card))                           # what the start worker does
        w.drain()
        # Write's set for QUIET (no screen, no clip) holds the game program with the validator
        # bypass, so the run binds the set and preloads the object (item 149)
        assert env == svc.tryit_env() and env[1] == "PAD_MODE_SO=/lib/pad_mode.so"
        # the rig is CHECKED first (feature/emulate-prepare), then the stage is installed
        assert [c[:3] for c in ran] == [["RIG", "modes/tryit.sh", "check"],
                                        ["RIG", "modes/tryit.sh", "install"]]
        stage = MT.stage_dir(svc._tryit_base)
        assert sorted(os.listdir(stage)) == ["game.port", "mode.cfg", "pad_mode.so"]
        assert handed[0](str(tmp_path / "no_such.raw")) is None  # a missing card refuses
        w.drain()

        # Start mode now / End mode, per slot, only while the emulator is up
        assert w.run(svc.on_start_now) is None
        running[0] = True
        assert w.run(svc.on_start_now) == ["RIG", "modes/tryit.sh", "start", "0"]
        assert w.run(svc.on_end_now) == ["RIG", "modes/tryit.sh", "stop"]
        assert _wait(w, lambda: len(ran) >= 4)

        # an edit while the game runs: the regenerated file is pushed into slot 0
        _f(w, "seconds", "9")
        _save(w)
        assert _wait(w, lambda: any(c[2] == "push" for c in ran))
        push = [c for c in ran if c[2] == "push"][-1]
        assert push[-1] == "0"
        pushed = open(os.path.join(stage, "push", "mode.cfg"), encoding="utf-8").read()
        assert "seconds        9" in pushed
        # a screen change cannot reload live, and says so
        n = len(ran)
        _f(w, "screen", True)
        _save(w)
        assert _wait(w, lambda: len(ran) > n)
        assert _wait(w, lambda: "next Try it" in _line(w))


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_new_code_mode_copies_the_template_and_opens_the_sdk(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        opened = []
        svc._opener = opened.append
        path = w.call("modes.new_code_mode", "Blitz Rush")
        assert path == str(project / "modes" / "blitz_rush" / "blitz_rush.c")
        # the Code modes line names it at once, and no form mode is opened for it
        assert "Blitz Rush" in _st(w)["code_words"] and svc._slug is None
        assert _st(w)["sel"] == {"slug": "blitz_rush", "kind": "code"}
        text = open(path, encoding="utf-8").read()
        assert '#define MODE_NAME        "Blitz Rush"' in text
        assert '"blitz_rush.start"' in text and "PadMode_blitz_rush_Screen" in text
        assert "target_rush" not in text and "PM_REGISTER(blitz_rush_mode);" in text
        assert opened == [path]
        w.call("modes.open_sdk_doc")
        assert opened[-1].endswith("MODE_SDK.md") and os.path.isfile(opened[-1])


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_compiles_a_code_mode_first_and_names_it(tmp_path, monkeypatch):
    """A project with a CODE mode (New code mode): Try it compiles it with build_mode.sh,
    beside the mode-file interpreter, BEFORE the install, and the ready line names it -
    it has no mode.json, so it is not a form mode and Start mode now cannot reach it."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    project = tmp_path / "proj"
    project.mkdir()
    MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    MT.new_code_mode(str(project), "Blitz")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran, handed = [], []
        _fake_rig(svc, ran)
        _tryit_ready(svc, tmp_path, handed)
        monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
        _writes_builder(monkeypatch, [])
        assert w.run(svc.on_try) is True and not ran
        card = tmp_path / "card.raw"
        card.write_bytes(b"\0" * 32)
        assert handed[0](str(card)) == svc.tryit_env()      # Write's set: the game program
        w.drain()
        assert [c[1] for c in ran] == ["modes/tryit.sh", "modes/sdk/build_mode.sh", "modes/tryit.sh"]
        assert ran[0][2] == "check"                          # the rig first, before any build
        assert ran[1][-2].endswith("blitz/blitz.c") and ran[1][-1].endswith("mode_file.c")
        assert ran[1][3].endswith("/pad_mode.so") and ran[2][2] == "install"
        status = _line(w)
        assert "1 mode(s) ready (QUIET)" in status and "Code mode(s) built in: blitz" in status
        # a card Written from the project carries the code modes too (their own assets with them)
        assert "A card Written from this project carries them the same way" in status
        # End mode ends both: the form modes' mode.stop and the code mode's own blitz.stop
        svc._running_fn = lambda: True
        assert w.run(svc.on_end_now) == ["RIG", "modes/tryit.sh", "stop", "blitz"]
        assert _wait(w, lambda: "end the running mode, and the code mode(s) blitz." in _line(w))


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_says_it_does_not_run_on_a_mac_yet(tmp_path, monkeypatch):
    """On macOS the rig runs in padbox.sh's container, which neither mounts the Try it
    folder nor forwards PAD_MODE_SO: Try it there would start a run with no mode in it, or
    fail with a rig error. It says so in a sentence and hands nothing to the Emulate tab."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, _card = _tryit_setup(w, tmp_path, monkeypatch)
        svc._platform = "darwin"
        assert w.run(svc.on_try) is False and handed == [] and ran == []
        assert "runs on Windows and Linux for now" in _line(w)
        svc._platform = "linux"
        assert w.run(svc.on_try) is True and handed == [svc.tryit_prepare]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_refused_stays_on_the_modes_tab_and_says_why(tmp_path, monkeypatch):
    """feature/emulate-prepare: a refused Try it (no card picked, a run up, the edits box
    ticked) used to land the user on the Emulate tab with nothing happening on it. Now the
    tab only comes forward on acceptance, and the Emulate service hands the Modes tab its
    own reason: the hand-off answers ``(accepted, reason)``."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, _ran, _handed, _card = _tryit_setup(w, tmp_path, monkeypatch)
        svc.__dict__.pop("_try_fn", None)            # the real hand-off, to the real service
        emu = w.window.service("emulate")
        w.call("ui.select_tab", "modes")
        assert w.state("shell")["tab"] == "modes"
        handed = []
        why = "Pick a card image first - the one on the Extract tab."

        def refuse(prepare):
            handed.append(prepare)
            emu.last_refusal = why
            return False
        monkeypatch.setattr(emu, "launch_with", refuse)
        assert w.run(svc._try_fn, svc.tryit_prepare) == (False, why)
        assert handed == [svc.tryit_prepare]
        assert w.state("shell")["tab"] == "modes"
        # accepted: the tab comes forward, and the answer is (True, "")
        monkeypatch.setattr(emu, "launch_with", lambda prepare: True)
        assert w.run(svc._try_fn, svc.tryit_prepare) == (True, "")
        w.drain()
        assert w.state("shell")["tab"] == "emulate"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_pressed_again_during_a_build_is_cancel(tmp_path, monkeypatch):
    """feature/emulate-prepare: ONE button. While a preparation is in flight it reads
    "Cancel", and pressing it launches nothing a second time: it raises the tab's cancel
    flag, which the engine's own checkpoint reads (build_set's ``cancel``), and the build
    that stops there lands "Try it was cancelled; nothing was started." with the button
    reading "Try it" again."""
    from pinball_decryptor.plugins.stern import mode_write as MW

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, card = _tryit_setup(w, tmp_path, monkeypatch)
        asked = []

        def build(project, card_, base, log=None, progress=None, cancel=None, label=None,
                  sound_ok=None):
            asked.append(cancel())
            return None                                  # the engine's answer to a cancel
        monkeypatch.setattr(MW, "build_tryit_set", build)
        assert w.run(svc.on_try) is True
        assert _tryit(w)["state"] == "preflight" and _tryit(w)["working"]   # the button: Cancel
        assert w.run(svc.on_try) is False                    # the second press: Cancel
        assert len(handed) == 1 and svc._tryit_cancel is True
        assert _line(w) == "cancelling…"
        assert _tryit(w)["working"]                          # until the worker lands it
        # the worker (a thread, as the Emulate tab's is) finds the flag at the engine's
        # checkpoint
        result = []
        threading.Thread(target=lambda: result.append(handed[0](str(card))),
                         daemon=True).start()
        assert _wait(w, lambda: result, 10)
        assert result == [None] and asked == [True]
        assert _wait(w, lambda: _tryit(w)["state"] == "failed", 5)
        assert _tryit(w)["reason"] == "cancelled"
        assert _line(w) == "Try it was cancelled; nothing was started."
        assert svc.tryit_prepare.last_reason == "Try it was cancelled; nothing was started."
        assert not _tryit(w)["working"]
        assert [c[2] for c in ran] == ["check"]              # nothing installed
        # a run that came up meanwhile is the Emulate tab's: Cancel at "starting" only says
        # so, and LEAVES THE STATE (the launch is real and booting; landing failed here
        # reopened Try it over a rig still coming up)
        w.run(svc._tryit_set, "starting")
        assert _tryit(w)["working"]
        assert w.run(svc.on_try) is False and len(handed) == 1
        assert _tryit(w)["state"] == "starting" and _tryit(w)["working"]
        assert "the run is the Emulate tab's now" in _line(w)
        # ...and when that launch is over without the run ever being seen up (the Emulate
        # tab's run_ended from its start worker), the tab lands failed with where to look
        w.run(svc.run_ended, None)
        assert _tryit(w)["state"] == "failed" and _tryit(w)["reason"] == "not up"
        assert _line(w) == svc.TRYIT_NOT_UP
        assert not _tryit(w)["working"]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_says_when_the_preparation_raises_or_is_cancelled_late(
        tmp_path, monkeypatch):
    """feature/emulate-prepare, review: an error the builder does not wrap lands on the
    tab's line (it used to keep the last "Preparing: ..." text while the button read Try
    it); a Cancel that lands after the install's last checkpoint refuses instead of handing
    the env back; and a launch that is over while the tab still waits in preflight lands
    failed too."""
    from pinball_decryptor.plugins.stern import mode_write as MW
    from tests.test_stern_mode_tryit import _writes_builder

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, card = _tryit_setup(w, tmp_path, monkeypatch)

        def boom(project, card_, base, log=None, progress=None, cancel=None, label=None,
                 sound_ok=None):
            progress(3, 8, "growing the sound bank…")
            raise KeyError("no such record")
        monkeypatch.setattr(MW, "build_tryit_set", boom)
        assert w.run(svc.on_try) is True
        raised = []

        def worker():
            try:
                handed[0](str(card))
            except KeyError as e:
                raised.append(e)
        threading.Thread(target=worker, daemon=True).start()
        assert _wait(w, lambda: raised, 10)                  # it still escapes to the worker
        assert _wait(w, lambda: _tryit(w)["state"] == "failed", 5)
        assert _line(w) == "the run could not be prepared: 'no such record'"
        assert svc.tryit_prepare.last_reason == _line(w)
        assert not _tryit(w)["working"]

        # a Cancel in the install's last poll interval: the rig's install answers ok, but
        # the flag is up by the time it returns
        _writes_builder(monkeypatch, [])

        def late_cancel(cmd, **kw):
            ran.append(cmd)
            if cmd[2] == "install":
                svc._tryit_cancel = True
            return _ok()
        svc._run_fn = late_cancel
        ran.clear()
        assert w.run(svc.on_try) is True
        assert handed[-1](str(card)) is None
        w.drain()
        assert [c[2] for c in ran] == ["check", "install"]
        assert _tryit(w)["state"] == "failed" and _tryit(w)["reason"] == "cancelled"
        assert _line(w) == svc.TRYIT_CANCELLED

        # the launch over while the tab is still in preflight (the Emulate tab's worker
        # returned before the preparation ran): failed, not stuck on Cancel
        svc._run_fn = lambda cmd, **kw: ran.append(cmd) or _ok()
        assert w.run(svc.on_try) is True
        assert _tryit(w)["state"] == "preflight"
        w.run(svc.run_ended, 3)
        assert _tryit(w)["state"] == "failed"
        assert _line(w) == svc.TRYIT_NOT_UP
        assert not _tryit(w)["working"]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_asks_the_rig_first_and_a_refusal_costs_no_build(tmp_path, monkeypatch):
    """feature/emulate-prepare: a dump folder left root-owned by an emulator run as root
    used to refuse the INSTALL, after minutes of building. tryit.sh's ``check`` runs before
    anything slow; its sentence (without the script's tag, the hand-back command verbatim)
    is on the tab's line, pinned on the Emulate tab through its refusal call and recorded on
    the callable for that tab's own worker, and the state is failed."""
    from pinball_decryptor.plugins.stern import mode_write as MW

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, card = _tryit_setup(w, tmp_path, monkeypatch)
        why = ("cannot put the modes in the emulator: /home/pad/dump belongs to root, not pad "
               "(an emulator run as root made it). Hand it back with: sudo chown -R pad:pad "
               "/home/pad/dump")

        def run(cmd, **kw):
            ran.append(cmd)
            blocked = cmd[2] == "check"
            return types.SimpleNamespace(returncode=1 if blocked else 0, stdout="",
                                         stderr="[tryit] %s\n" % why if blocked else "ok")
        svc._run_fn = run
        built, refused = [], []
        monkeypatch.setattr(MW, "build_tryit_set", lambda *a, **kw: built.append(a) or None)
        svc._refuse_fn = refused.append
        assert w.run(svc.on_try) is True
        assert handed[0](str(card)) is None
        w.drain()
        assert [c[:3] for c in ran] == [["RIG", "modes/tryit.sh", "check"]]
        assert built == []                                   # no build was started
        assert _line(w) == why
        assert refused == [why] and svc.tryit_prepare.last_reason == why
        assert _tryit(w)["state"] == "failed" and _tryit(w)["reason"] == why
        assert not _tryit(w)["working"]
        # the person can paste the fix as the script gave it
        assert why.split("Hand it back with: ")[1] == "sudo chown -R pad:pad /home/pad/dump"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_preflight_reads_the_emulate_tabs_state(tmp_path, monkeypatch):
    """feature/emulate-prepare: a run that is up, a Start or Stop in flight, or the edits
    box ticked on the Emulate tab refuse the press ON THE UI LOOP, before the hand-off,
    each in its own sentence; the card and the rig stay launch_with's to report."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, _ran, handed, _card = _tryit_setup(w, tmp_path, monkeypatch)
        state = {"up": False, "busy": False, "overrides": False, "card": "", "rig": True}
        svc._emulate_state = lambda: state
        state["up"] = True
        assert w.run(svc.on_try) is False and handed == []
        assert _line(w) == ("the emulator is already running: stop it on the Emulate tab "
                            "first, then press Try it.")
        state["up"], state["busy"] = False, True
        assert w.run(svc.on_try) is False and handed == []
        assert "starting or stopping; wait for it" in _line(w)
        state["busy"], state["overrides"] = False, True
        assert w.run(svc.on_try) is False and handed == []
        assert _line(w).startswith("\"apply my edits\" is ticked")
        assert "Try it already carries your edits" in _line(w)
        assert not _tryit(w)["working"]
        state["overrides"] = False                           # no card in the box: not this tab's
        assert w.run(svc.on_try) is True and handed == [svc.tryit_prepare]
        # ...and an Emulate tab that cannot answer leaves the checks to launch_with
        w.run(svc._tryit_set, "idle")
        svc._emulate_state = lambda: None
        assert w.run(svc.on_try) is True and len(handed) == 2


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_progress_from_the_worker_lands_with_a_percent(tmp_path, monkeypatch):
    """feature/emulate-prepare: the engine's checkpoints (build_set's ``progress``) reach
    the tab's line as "Preparing: <step> NN%" and the Emulate tab's progress with the
    same words and percent, from the start worker, through the UI loop; the ready line then
    takes over, and a set handed back unbuilt says so."""
    from pinball_decryptor.plugins.stern import mode_write as MW
    from tests.test_stern_mode_tryit import _writes_builder

    with web_app(tmp_path, mfr="stern") as w:
        svc, _ran, _handed, card = _tryit_setup(w, tmp_path, monkeypatch)
        _writes_builder(monkeypatch, [])
        inner = MW.build_tryit_set
        go = threading.Event()
        shown = []
        svc._progress_fn = lambda text, pct=None: shown.append((text, pct))

        def build(project, card_, base, log=None, progress=None, cancel=None, label=None,
                  sound_ok=None):
            progress(3, 8, "growing the sound bank…")
            go.wait(10)
            ts = inner(project, card_, base, log=log, progress=progress, cancel=cancel,
                       sound_ok=sound_ok)
            ts.reused = True
            return ts
        monkeypatch.setattr(MW, "build_tryit_set", build)
        result = []
        svc._try_fn = lambda prepare: threading.Thread(
            target=lambda: result.append(prepare(str(card))), daemon=True).start() or (True, "")
        try:
            assert w.run(svc.on_try) is True
            assert _wait(w, lambda: _line(w) == "Preparing: growing the sound bank… 37%", 10)
            assert _tryit(w)["state"] == "building" and _tryit(w)["working"]
            assert shown == [("growing the sound bank…", 37)]
            go.set()
            assert _wait(w, lambda: result, 20)
            assert result == [svc.tryit_env()]
            assert _wait(w, lambda: "1 mode(s) ready (QUIET)" in _line(w), 10)
            assert "(the set from the last Try it, used as it is)" in _line(w)
            assert _tryit(w)["state"] == "starting" and _tryit(w)["working"]
            # the Emulate tab's poll says the run is up: live, with the launch it belongs to
            svc._run_id_fn = lambda: 5
            svc._running_fn = lambda: True
            assert _wait(w, lambda: _tryit(w)["state"] == "live", 5)
            assert svc._tryit["run"] == 5 and not _tryit(w)["working"]
        finally:
            go.set()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_run_ended_lands_ended_and_drops_the_live_record(tmp_path, monkeypatch):
    """feature/emulate-prepare: the Emulate tab tells the tab which launch went down
    (``run_ended``). Try it's own run lands "ended", says so, and the record of what the run
    had in it goes with the run; another launch's end is not this tab's news."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, _ran, _handed, _card = _tryit_setup(w, tmp_path, monkeypatch)
        svc._running_fn = lambda: True          # the poll never lands the run on its own
        project = svc.project()
        w.run(svc._tryit_note, "1 mode(s) ready (QUIET).")
        w.run(svc._tryit_set, "live")
        svc._tryit["run"] = 7
        svc._tryit_live = {"project": project, "slots": {"quiet": 0}, "signatures": {},
                           "stage": str(tmp_path / "stage"), "run": 7}
        w.run(svc.run_ended, 8)                              # not this run
        assert _tryit(w)["state"] == "live" and svc._tryit_live is not None
        assert _line(w) == "1 mode(s) ready (QUIET)."
        w.run(svc.run_ended, 7)
        assert _tryit(w)["state"] == "ended" and svc._tryit_live is None
        assert _line(w) == "The run ended. Press Try it to run the modes again."
        assert not _tryit(w)["working"]
        # a run the tab never asked for is not its news either
        w.run(svc._tryit_set, "idle")
        w.run(svc.run_ended, 9)
        assert _tryit(w)["state"] == "idle"
        assert _line(w) == "The run ended. Press Try it to run the modes again."   # unchanged


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_installs_as_root_when_the_launch_is_root(tmp_path, monkeypatch):
    """feature/emulate-prepare: the Emulate tab's Start with save states is a root launch,
    and an install made as the user is refused by the root-owned dump it leaves. When the
    Emulate tab says the launch is root, the check and the install go through rig_cmd_root,
    so the files go in as the run will read them (and tryit.sh hands them back)."""
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, card = _tryit_setup(w, tmp_path, monkeypatch)
        _writes_builder(monkeypatch, [])
        svc._as_root = lambda: True
        assert svc.check_cmd() == ["RIG", "modes/tryit.sh", "check"]
        assert svc.check_cmd(as_root=True) == ["ROOT", "modes/tryit.sh", "check"]
        assert w.run(svc.on_try) is True
        assert handed[0](str(card)) == svc.tryit_env()
        w.drain()
        stage = MT.stage_dir(svc._tryit_base)
        assert [c[:3] for c in ran] == [["ROOT", "modes/tryit.sh", "check"],
                                        ["ROOT", "modes/tryit.sh", "install"]]
        assert ran[1][3] == svc._linux_path(stage)
        # ...and as the user when it is not
        svc._as_root = lambda: False
        w.run(svc._tryit_set, "idle")
        del ran[:]
        assert w.run(svc.on_try) is True
        assert handed[1](str(card)) == svc.tryit_env()
        w.drain()
        assert [c[0] for c in ran] == ["RIG", "RIG"]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_shows_the_emulate_tabs_refusal_verbatim(tmp_path, monkeypatch):
    """feature/emulate-prepare: the hand-off answers ``(accepted, reason)``; a refusal's
    reason is the Emulate tab's own sentence, shown on the tab's line as it is, and the
    state is failed with the button reading "Try it". A bare False (an older caller) still
    gets the three-way sentence."""
    with web_app(tmp_path, mfr="stern") as w:
        svc, _ran, handed, _card = _tryit_setup(w, tmp_path, monkeypatch)
        svc._try_fn = lambda prepare: handed.append(prepare) or (False, "no card image is picked")
        assert w.run(svc.on_try) is False and len(handed) == 1
        assert _line(w) == "no card image is picked"
        assert _tryit(w)["state"] == "failed"
        assert _tryit(w)["reason"] == "no card image is picked"
        assert not _tryit(w)["working"]
        svc._try_fn = lambda prepare: handed.append(prepare) or False
        assert w.run(svc.on_try) is False and len(handed) == 2
        assert _line(w).startswith("the Emulate tab did not start the run; it says why there")
        assert _tryit(w)["state"] == "failed"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_a_save_that_changes_nothing_pushes_nothing(tmp_path, monkeypatch):
    """Item 127 run 2 (2026-09-17): picking another mode in the list saves the open one
    first, and every such click pushed an IDENTICAL mode file into the running game and
    said "updated in the running game". Only a file the game does not have is pushed."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    project = tmp_path / "proj"
    project.mkdir()
    for name in ("ALPHA", "BRAVO"):
        MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran = []
        _fake_rig(svc, ran)
        svc._running_fn = lambda: True
        # what a Try it install leaves: the stage's mode files, one per slot
        stage = tmp_path / "stage"
        stage.mkdir()
        found = MP.list_modes(str(project))[0]
        for slot, (slug, spec) in enumerate(found):
            with open(stage / MA.mode_file_name(slot), "w", encoding="utf-8", newline="\n") as f:
                f.write(MP.runtime_cfg(spec, slug))
        svc._tryit_live = {"project": str(project),
                           "slots": {slug: i for i, (slug, _s) in enumerate(found)},
                           "signatures": {slug: MT.asset_signature(s) for slug, s in found},
                           "stage": str(stage)}

        _select(w, found[0][0])
        _select(w, found[1][0])                              # saves the first, unchanged
        _select(w, found[0][0])                              # and the second
        time.sleep(0.2)
        w.drain()
        assert ran == [] and "updated in the running game" not in _line(w)

        _f(w, "seconds", "9")                                # a real edit is pushed, once
        _save(w)
        assert _wait(w, lambda: "updated in the running game" in _line(w))
        assert len(ran) == 1 and ran[0][2] == "push" and ran[0][-1] == "0"
        _save(w)
        _select(w, found[1][0])
        time.sleep(0.2)
        w.drain()
        assert len(ran) == 1


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_start_mode_now_reaches_only_a_mode_the_running_game_has(tmp_path, monkeypatch):
    """Start mode now names a SLOT, and the game's slot K is whatever Try it installed
    there. A mode added after Try it (BRAVO, between ALPHA and CHARLIE) would take
    CHARLIE's slot by the project's order: it is refused in a sentence, never guessed. The
    record belongs to Try it's own launch: after another Start there are no modes to reach,
    and an edit pushes nothing."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    project = tmp_path / "proj"
    project.mkdir()
    for name in ("ALPHA", "CHARLIE"):
        MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran = []
        _fake_rig(svc, ran)
        launch = [7]
        svc._running_fn = lambda: True
        svc._run_id_fn = lambda: launch[0]
        found = MP.list_modes(str(project))[0]
        stage = tmp_path / "stage"                        # what Try it installed: ALPHA 0, CHARLIE 1
        stage.mkdir()
        for slot, (slug, spec) in enumerate(found):
            with open(stage / MA.mode_file_name(slot), "w", encoding="utf-8", newline="\n") as f:
                f.write(MP.runtime_cfg(spec, slug))
        svc._tryit_live = {"project": str(project), "slots": {"alpha": 0, "charlie": 1},
                           "signatures": {slug: MT.asset_signature(s) for slug, s in found},
                           "stage": str(stage), "run": 7}

        MP.new_mode(str(project), "BRAVO", MP.ModeSpec(name="BRAVO", screen=False, clip="none"))
        w.run(svc.refresh)
        assert MT.slot_of(str(project), "bravo") == 1          # CHARLIE's slot in the game
        _select(w, "bravo")
        assert w.run(svc.on_start_now) is None and ran == []
        assert "BRAVO is not in the running game yet" in _line(w)

        _select(w, "charlie")
        assert w.run(svc.on_start_now) == ["RIG", "modes/tryit.sh", "start", "1"]
        # the note names the mode, never its slot (a number the person never chose)
        assert _wait(w, lambda: "asked the game to start CHARLIE. A game must be in play."
                     in _line(w))
        assert "slot" not in _line(w)
        # an edit while Try it's OWN launch is up (a matching run id) is pushed into the slot
        # the game has
        _f(w, "seconds", "9")
        _save(w)
        assert _wait(w, lambda: any(c[2] == "push" for c in ran))
        assert [c[-1] for c in ran if c[2] == "push"] == ["1"]
        assert _wait(w, lambda: "CHARLIE updated in the running game" in _line(w))

        # a mode opened from ANOTHER project is not in the game either
        other = tmp_path / "other"
        other.mkdir()
        MP.new_mode(str(other), "ALPHA", MP.ModeSpec(name="ALPHA", screen=False, clip="none"))
        _project(w, other)
        _select(w, "alpha")
        n = len(ran)
        assert w.run(svc.on_start_now) is None and len(ran) == n
        assert "another project's modes" in _line(w)
        _project(w, project)

        # the Emulate tab launched again (its own Start, no modes): the record is forgotten
        launch[0] = 8
        _select(w, "alpha")
        assert w.run(svc.on_start_now) is None and len(ran) == n
        assert "not started by Try it" in _line(w)
        assert svc._tryit_live is None
        assert w.run(svc.on_end_now) is None and len(ran) == n
        _f(w, "seconds", "9")
        _save(w)
        time.sleep(0.2)
        w.drain()
        assert len(ran) == n                                     # nothing pushed


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_logs_from_the_start_worker_on_the_main_loop(tmp_path, monkeypatch):
    """Try it's preparation runs on the Emulate tab's start WORKER, and the app's log (the
    store) belongs to the UI loop: every line the preparation and the rig commands log
    reaches the log ON THE UI LOOP, in order - never from the worker."""
    from tests.test_stern_mode_tryit import _writes_builder

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, _handed, card = _tryit_setup(w, tmp_path, monkeypatch)
        logged, result = [], []
        # the Emulate tab's launch_with, as it behaves: the preparation on a worker thread
        svc._try_fn = lambda prepare: threading.Thread(
            target=lambda: result.append(prepare(str(card))), daemon=True).start() or (True, "")
        svc._running_fn = lambda: True

        def log(msg, *a, **kw):
            if str(msg).startswith(svc.LOG_TAG):
                logged.append((msg, w.ctx.loop.in_loop()))
        monkeypatch.setattr(w.window, "append_log", log)
        _writes_builder(monkeypatch, [])
        assert w.run(svc.on_try) is True
        assert _wait(w, lambda: result and any("ready" in m for m, _t in logged), 20)
        assert result == [svc.tryit_env()] and ran and ran[-1][2] == "install"
        said = [m for m, _t in logged]
        built = [m for m in said                                # build_set's own log, on the worker
                 if "Try it: building the" in m and "Emulate tab" not in m]
        assert built, said
        assert said.index([m for m in said if "ready" in m][0]) > said.index(built[0])
        # ...and a rig command's answer, from the tab's own thread
        assert w.run(svc.on_end_now) == ["RIG", "modes/tryit.sh", "stop"]
        assert _wait(w, lambda: any("asked the game to end" in m for m, _t in logged))
        assert all(on_loop for _m, on_loop in logged), [m for m, t in logged if not t]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_runs_a_project_of_code_modes_only(tmp_path, monkeypatch):
    """A project whose only mode is a CODE mode (New code mode, nothing in the form) can
    Try it: no set (no screens or clips to build), only the object compiled from it, the
    card's port, and PAD_MODE_SO. A card the SDK has no port for is refused."""
    from pinball_decryptor.plugins.stern import mode_tryit as MT

    project = tmp_path / "proj"
    project.mkdir()
    MT.new_code_mode(str(project), "Blitz")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran, handed = [], []
        _fake_rig(svc, ran)
        _tryit_ready(svc, tmp_path, handed)
        running = [False]
        svc._running_fn = lambda: running[0]
        card = tmp_path / "card.raw"
        card.write_bytes(b"\0" * 32)
        monkeypatch.setattr(MT, "card_title", lambda c: ("nosuch_pro", "9.9.0", 0))
        assert w.run(svc.on_try) is True and not ran
        assert handed[0](str(card)) is None
        w.drain()
        assert [c[2] for c in ran] == ["check"]              # the rig was asked, nothing built
        assert "no port for nosuch_pro 9.9.0" in _line(w)
        del ran[:]

        monkeypatch.setattr(MT, "card_title", lambda c: ("godzilla_pro", "1.15.0", 0))
        assert w.run(svc.on_try) is True
        assert handed[-1](str(card)) == ["PAD_MODE_SO=/lib/pad_mode.so"]
        w.drain()
        assert [c[1] for c in ran] == ["modes/tryit.sh", "modes/sdk/build_mode.sh", "modes/tryit.sh"]
        assert ran[0][2] == "check"
        assert ran[1][-2].endswith("blitz/blitz.c") and ran[2][2] == "install"
        stage = MT.stage_dir(svc._tryit_base)
        assert os.listdir(stage) == ["game.port"]          # the object is the compiler's to make
        assert not os.path.isdir(MT.set_dir(svc._tryit_base))
        assert "Code mode(s) built in: blitz" in _line(w)
        assert "carries them the same way" in _line(w)
        running[0] = True
        # End mode reaches the code mode by ITS trigger (a code mode never reads mode.stop)
        assert w.run(svc.on_end_now) == ["RIG", "modes/tryit.sh", "stop", "blitz"]
        assert _wait(w, lambda: len(ran) >= 4)
        assert _wait(w, lambda: "end the code mode(s) blitz." in _line(w))


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_without_screens_or_clips_takes_no_override_set(tmp_path, monkeypatch):
    """Item 127 (2026-09-17): a set that holds no file of the TITLE - with Write's code
    (item 149), one whose only file is the manifest beside the title, as Jaws' is -
    is refused by run_game.sh ("nothing in this set belongs to the title being booted",
    exit 1), and the game never started. Such a project, alone or beside a code mode,
    hands the launch PAD_MODE_SO and no PAD_OVERRIDE_DIR, and its mode files still reach
    the rig."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
    _writes_builder(monkeypatch, [], files=["spk/index/godzilla_pro-1_15_0.sidx"])
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 32)
    with web_app(tmp_path, mfr="stern") as w:
        for with_code in (False, True):
            kind = "code" if with_code else "form"
            project = tmp_path / ("proj_" + kind)
            project.mkdir()
            for name in ("QUIET", "HUSH"):
                MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none"))
            if with_code:
                MT.new_code_mode(str(project), "Blitz")
            _project(w, project)
            _no_wsl(monkeypatch)
            svc = _svc(w)
            ran, handed = [], []
            _fake_rig(svc, ran)
            _tryit_ready(svc, tmp_path, handed, base="try_" + kind)
            w.run(svc._tryit_set, "idle")
            assert w.run(svc.on_try) is True and not ran
            env = handed[0](str(card))                      # what the start worker does
            w.drain()
            assert env == ["PAD_MODE_SO=/lib/pad_mode.so"], (kind, env)
            # the set on disk really holds no file of the title...
            sdir = MT.set_dir(svc._tryit_base)
            held = sorted(os.path.relpath(os.path.join(d, n), sdir).replace(os.sep, "/")
                          for d, _dirs, names in os.walk(sdir) for n in names)
            assert held == ["spk/index/godzilla_pro-1_15_0.sidx"], (kind, held)
            # ...and the modes still reach the rig: compiled (a code mode), then installed
            assert [c[1] for c in ran] == ["modes/tryit.sh"] \
                + (["modes/sdk/build_mode.sh"] if with_code else []) \
                + ["modes/tryit.sh"], (kind, ran)
            assert ran[0][2] == "check"
            assert ran[-1][2] == "install"
            assert {"mode.cfg", "mode1.cfg", "game.port"} <= set(
                os.listdir(MT.stage_dir(svc._tryit_base)))
            assert svc._tryit_live["slots"] == {"hush": 0, "quiet": 1}
            assert svc._tryit_live["codes"] == (["blitz"] if with_code else [])
            assert "2 mode(s) ready" in _line(w)


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_with_game_files_in_the_set_still_binds_it(tmp_path, monkeypatch):
    """The other side of the fix above: when the build DOES make a file of the title (a
    mode's screen puts the HUD scene in the set), the launch binds the set with
    PAD_OVERRIDE_DIR as before. Write's builder is stood in for with that scene file in its
    set, so this needs neither the stock HUD scene nor ffmpeg."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    with web_app(tmp_path, mfr="stern") as w:
        svc, ran, handed, card = _tryit_setup(w, tmp_path, monkeypatch, name="LOUD")
        hud_rel = "%s/%s/scene.radium" % (MA.LCD, MP.GODZILLA_PRO_1_15.hud_scene)
        _writes_builder(monkeypatch, [], files=["godzilla_pro/" + hud_rel,
                                                "spk/index/godzilla_pro-1_15_0.sidx"])
        assert w.run(svc.on_try) is True
        env = handed[0](str(card))
        w.drain()
        assert env == svc.tryit_env()
        assert env[0].startswith("PAD_OVERRIDE_DIR=") and env[0].endswith("/try/set")
        assert os.path.isfile(os.path.join(MT.set_dir(svc._tryit_base), "godzilla_pro",
                                           *hud_rel.split("/")))
        assert ran and ran[-1][2] == "install"


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_open_sdk_doc_falls_back_to_plain_text(tmp_path, monkeypatch):
    """Open MODE_SDK.md on a Windows PC with no .md association: os.startfile raises "No
    application is associated", and the tab only said "could not open". MODE_SDK.md and a
    code mode's .c are plain text: Notepad opens them on Windows, the web browser elsewhere,
    and only when that fails too does the tab say it could not open the file."""
    import webbrowser
    from pinball_decryptor.webui import modes_tryit

    with web_app(tmp_path, mfr="stern") as w:
        _no_wsl(monkeypatch)
        svc = _svc(w)
        doc = svc.sdk_doc()
        tries = []

        def no_association(path):
            tries.append(path)
            raise OSError(1155, "No application is associated with the specified file")
        svc._opener = no_association
        started = []
        monkeypatch.setattr(modes_tryit.subprocess, "Popen", lambda argv, **kw: started.append(argv))
        svc._platform = "win32"
        w.call("modes.open_sdk_doc")
        assert tries == [doc] and started == [["notepad.exe", doc]]
        assert "opened MODE_SDK.md in Notepad" in _line(w)

        # elsewhere, the web browser, by a file URI
        browsed = []
        monkeypatch.setattr(webbrowser, "open", lambda url, *a, **kw: browsed.append(url) or True)
        svc._platform = "linux"
        w.call("modes.open_sdk_doc")
        assert len(browsed) == 1 and browsed[0].startswith("file:")
        assert browsed[0].endswith("/MODE_SDK.md") and len(started) == 1
        assert "MODE_SDK.md in the web browser" in _line(w)

        # when the fallback fails too, it says it could not open the file
        def no_notepad(argv, **kw):
            raise FileNotFoundError(2, "The system cannot find the file specified")
        monkeypatch.setattr(modes_tryit.subprocess, "Popen", no_notepad)
        svc._platform = "win32"
        w.call("modes.open_sdk_doc")
        assert "could not open %s" % doc in _line(w)

        # an opener that works needs no fallback
        opened = []
        svc._opener = opened.append
        monkeypatch.setattr(modes_tryit.subprocess, "Popen", lambda argv, **kw: started.append(argv))
        w.call("modes.open_sdk_doc")
        assert opened == [doc] and len(started) == 1


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_runs_on_the_projects_own_card(tmp_path, monkeypatch):
    """Item 127 with item 148: a project made from a Premium/LE 1.16 card whose modes were
    saved as Pro 1.15 (David's own project is exactly this). Try it used to refuse that card
    and, on a Pro 1.15 card, staged Pro's port while the build inside went to LE. Now the
    run takes the project's card: LE 1.16's port and masks in the stage, pressing Try it on
    an unedited mode leaves its mode.json as it was (only an edit is saved), and an edit
    while the game runs pushes LE's masks without claiming its screen waits for the next
    Try it."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
                                  "1.16.0")
    shots = ["Shield target right"]
    slug, _spec = MP.new_mode(str(project), "QUIET", MP.ModeSpec(
        name="QUIET", screen=False, clip="none", scoring_shots=shots))
    mode_json = project / "modes" / slug / "mode.json"
    saved = mode_json.read_bytes()
    le = MP.profile_for_card("godzilla_le", "1.16.0")
    assert le.mask(shots) != MP.GODZILLA_PRO_1_15.mask(shots)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        assert svc._spec.title == le.key                       # the form shows the card's title
        ran, handed = [], []
        _fake_rig(svc, ran)
        _tryit_ready(svc, tmp_path, handed)
        running = [False]
        svc._running_fn = lambda: running[0]
        monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_le", "1.16.0", 2))
        _writes_builder(monkeypatch, [])
        card = tmp_path / "card.raw"
        card.write_bytes(b"\0" * 32)
        try:
            assert w.run(svc.on_try) is True
            assert mode_json.read_bytes() == saved             # no edit, nothing saved
            env = handed[0](str(card))
            w.drain()
            assert env == svc.tryit_env(), _line(w)
            stage = MT.stage_dir(svc._tryit_base)
            with open(os.path.join(stage, "game.port"), "rb") as a, open(MP.port_path(le), "rb") as b:
                assert a.read() == b.read()
            cfg = open(os.path.join(stage, "mode.cfg"), encoding="utf-8").read()
            assert "shots          0x%08x" % le.mask(shots) in cfg
            assert "1 mode(s) ready" in _line(w)
            assert mode_json.read_bytes() == saved
            # while the game runs, an edit pushes LE's masks, and nothing waits for the next Try it
            running[0] = True
            _f(w, "seconds", "9")
            _save(w)
            assert _wait(w, lambda: any(c[2] == "push" for c in ran))
            pushed = open(os.path.join(stage, "push", "mode.cfg"), encoding="utf-8").read()
            assert "seconds        9" in pushed and "shots          0x%08x" % le.mask(shots) in pushed
            assert _wait(w, lambda: "updated in the running game" in _line(w))
            assert "next Try it" not in _line(w)
            # a sound of its own is built into the set's sound bank: a change to one waits for
            # the next Try it, and the tab says so
            spec = w.run(svc.collect)
            spec.music = "theme.wav"
            w.run(svc._tryit_saved, str(project), slug, spec)
            assert _wait(w, lambda: "own sounds reaches the game at the next Try it" in _line(w))
        finally:
            running[0] = False


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_pushes_keep_the_carriers_writes_set_named(tmp_path, monkeypatch):
    """Item 149 with item 150: Try it's set is Write's, so a mode's own start sound is in its
    sound bank on a carrier request, and the stage's mode file names it. The ready line does
    not call that sound left out, and an edit pushed while the game runs keeps naming the
    carrier (a push without it would silence the sound the set carries)."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    project = tmp_path / "proj"
    project.mkdir()
    slug, spec = MP.new_mode(str(project), "QUIET", MP.ModeSpec(name="QUIET", screen=False,
                                                                 clip="none"))
    folder = MP.mode_folder(str(project), slug)
    with open(os.path.join(folder, "go.wav"), "wb") as f:
        f.write(b"RIFF")
    spec.sound_start = "go.wav"
    MP.save(str(project), slug, spec)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran, handed = [], []
        _fake_rig(svc, ran)
        _tryit_ready(svc, tmp_path, handed)
        running = [False]
        svc._running_fn = lambda: running[0]
        monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
        carried = {slug: {"requests": {"sound_start": 1251}, "ms": {"sound_start": 480}}}
        _writes_builder(monkeypatch, [], own_sounds=carried)
        card = tmp_path / "card.raw"
        card.write_bytes(b"\0" * 32)
        try:
            assert w.run(svc.on_try) is True
            assert handed[0](str(card)) == svc.tryit_env()
            w.drain()
            status = _line(w)
            assert "1 mode(s) ready (QUIET)" in status and "not in this run" not in status, status
            stage = MT.stage_dir(svc._tryit_base)
            assert "sound_start    1251 480" in open(os.path.join(stage, "mode.cfg"),
                                                     encoding="utf-8").read()
            running[0] = True
            _f(w, "seconds", "9")
            _save(w)
            assert _wait(w, lambda: any(c[2] == "push" for c in ran))
            pushed = open(os.path.join(stage, "push", "mode.cfg"), encoding="utf-8").read()
            assert "seconds        9" in pushed and "sound_start    1251 480" in pushed
        finally:
            running[0] = False


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_runs_a_tmnt_pro_project(tmp_path, monkeypatch):
    """Item 127 with item 148: TMNT Pro 1.59's port names no HUD scene, and Try it read one
    anyway (``/turtles_pro/assets/lcd/auto_loaded//scene.radium``), so every form mode on
    TMNT Pro and Deadpool was refused while a Write build of it succeeded. Try it's own
    check runs here against a stand-in card and reads no scene; Write's builder (stood in
    for; tests/test_stern_mode_tryit runs the real one on the real TMNT card) gives the run
    TMNT's port and TMNT's masks, and the set with its patched game program."""
    from pinball_decryptor.plugins.stern import explorer
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from tests.test_stern_mode_tryit import _writes_builder

    tmnt = MP.profile("turtles_pro_1_59")
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    shots = ["Left ramp", "Right ramp"]
    slug, _spec = MP.new_mode(str(project), "SHELL SHOCK", MP.ModeSpec(
        name="SHELL SHOCK", title=tmnt.key, start_shot="Center loop", scoring_shots=shots,
        screen=False, clip="none"))
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran, handed, reads = [], [], []
        _fake_rig(svc, ran)
        _tryit_ready(svc, tmp_path, handed)

        class Card:
            def __init__(self, path):
                reads.append(path)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def preview(self, part, path, cap=None):
                reads.append(path)
                return None
        monkeypatch.setattr(explorer, "CardImage", Card)
        monkeypatch.setattr(MT, "card_title", lambda card: ("turtles_pro", "1.59.0", 3))
        _writes_builder(monkeypatch, [])
        card = tmp_path / "turtles.raw"
        card.write_bytes(b"\0" * 32)
        assert w.run(svc.on_try) is True and not ran
        env = handed[0](str(card))
        w.drain()
        status = _line(w)
        assert env == svc.tryit_env(), status
        assert reads == [] and "scene.radium" not in status
        assert "1 mode(s) ready (SHELL SHOCK)" in status
        assert [c[:3] for c in ran] == [["RIG", "modes/tryit.sh", "check"],
                                        ["RIG", "modes/tryit.sh", "install"]]
        stage = MT.stage_dir(svc._tryit_base)
        with open(os.path.join(stage, "game.port"), "rb") as a, open(MP.port_path(tmnt), "rb") as b:
            assert a.read() == b.read()
        cfg = open(os.path.join(stage, "mode.cfg"), encoding="utf-8").read()
        assert "shots          0x%08x" % tmnt.mask(shots) in cfg
        assert svc._tryit_live["slots"] == {slug: 0}


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_try_it_without_a_card_names_the_projects_own_card(tmp_path, monkeypatch):
    """With no card picked in the Emulate tab, Try it says which card to pick: the
    PROJECT'S card (item 148), not the title its modes were first saved for."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    cases = (("godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0", MP.GODZILLA_PRO_1_15.key,
              "Godzilla Premium/LE 1.16"),
             ("turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0", "turtles_pro_1_59",
              "TMNT Pro 1.59"))
    with web_app(tmp_path, mfr="stern") as w:
        for n, (card_name, version, saved_as, label) in enumerate(cases):
            project = _modes_card_project(tmp_path, card_name, version, folder="proj%d" % n)
            MP.new_mode(str(project), "QUIET", MP.ModeSpec(
                name="QUIET", title=saved_as, start_shot="Left ramp", scoring_shots=["Left ramp"],
                screen=False, clip="none"))
            _project(w, project)
            _no_wsl(monkeypatch)
            svc = _svc(w)
            ran, handed = [], []
            _fake_rig(svc, ran)
            _tryit_ready(svc, tmp_path, handed, base="try%d" % n)
            assert w.run(svc.on_try) is True
            assert handed[0](str(tmp_path / "no_card_picked.raw")) is None
            w.drain()
            status = _line(w)
            assert "pick a card image in the Emulate tab first (a %s card)" % label in status, status
            assert not ran


# ---------------------------------------------------------------------- item 148: per title
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_on_a_tmnt_pro_project_lists_its_shots_and_greys_what_it_cannot(tmp_path):
    """Item 148: a project on a TMNT Pro 1.59 card offers TMNT's 17 shots from its port,
    greys Lights, Screen and Clip and the countdown WITH the reason in words, and New
    makes a mode whose runtime file carries TMNT's own masks and no line TMNT cannot do."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        st = _st(w)
        names = [n for n, _m in tmnt.shots]
        assert len(names) == 17
        assert st["profile"]["shots"] == names
        title = st["title_text"]
        assert "TMNT Pro 1.59" in title and "turtles_pro-1.59.port" in title and "17 shots" in title
        assert [e["name"] for e in st["examples"]] == ["TARGET RUSH"]
        assert st["new_ok"] is True

        slug = w.call("modes.new")
        st = _st(w)
        assert "Ready to build" in st["status"]
        for part in ("lights", "screen", "clip"):
            assert st["dis"][part], part
            reason = st["reasons"][part]
            assert "Not on this game" in reason and tmnt.why_not(part) in reason
        assert st["dis"]["countdown"] and st["dis"]["own_sound"]
        assert "countdown" in st["reasons"]["sound"]
        assert st["editor_on"] is True                          # the shots stay live

        spec = MP.load(str(project / "modes" / slug / "mode.json"))
        assert spec.title == "turtles_pro_1_59" and spec.start_shot == "Center loop"
        cfg = MP.runtime_cfg(spec, slug)
        assert "trigger        0x00000080 3" in cfg                  # Center loop x3, TMNT's bit
        assert "shots          0x00000210" in cfg                    # Left ramp + Right ramp on TMNT
        for gone in ("screen_scene", "clip_start", "light_on", "callout_count", "callout_end"):
            assert gone not in cfg


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_premium_1_16_project_offers_godzillas_names(tmp_path):
    """The machine's card, Godzilla Premium 1.16 (a godzilla_le card): Godzilla's names
    including its third shield target, KAIJU RUSH under Examples, nothing greyed."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        st = _st(w)
        names = st["profile"]["shots"]
        assert len(names) == 21 and "Shield target center" in names and "Maser target" in names
        assert "Left spinner" in names and "Top spinner" in names and "Shield ramp spinner" in names
        assert "Godzilla Premium/LE 1.16" in st["title_text"]
        assert st["examples"][0]["name"] == "KAIJU RUSH"
        w.call("modes.example", "KAIJU RUSH")
        st = _st(w)
        assert "Ready to build" in st["status"]
        assert st["reasons"] == {}, st["reasons"]
        assert not st["dis"]["lights"]
        spec = MP.load(str(project / "modes" / "kaiju_rush" / "mode.json"))
        assert spec.title == "godzilla_le_1_16"
        assert "0x08000000 3" in MP.runtime_cfg(spec, "kaiju_rush")


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_card_with_no_port_points_at_making_a_port(tmp_path):
    """Godzilla Pro 1.16 has no port: the tab says so, names MODE_SDK.md's "Making a
    port", and New and Examples are off."""
    project = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        st = _st(w)
        note = st["title_note"]
        assert "MODE_SDK.md" in note and "Making a port for another game or version" in note
        assert "Godzilla Pro 1.16.0" in note
        assert st["new_ok"] is False
        assert st["ex_ok"] is False


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_jaws_greys_lights_and_screen_and_a_godzilla_mode_is_retargeted(tmp_path, monkeypatch):
    """Jaws LE 1.02 can count down and add a clip (an added clip played in item 148's run2)
    but has no lights and no measured HUD; its 27 shots go in three columns. A Godzilla mode
    already in the project is matched by name: the shots Jaws lacks are dropped and the log
    says which."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    MP.new_mode(str(project), spec=MP.example("KAIJU RUSH"))
    with web_app(tmp_path, mfr="stern") as w:
        logged = []
        real_log = w.window.append_log

        def log(msg, *a, **kw):
            logged.append(str(msg))
            return real_log(msg, *a, **kw)
        monkeypatch.setattr(w.window, "append_log", log)
        _project(w, project)
        st = _st(w)
        assert len(st["profile"]["shots"]) == 27 and st["profile"]["cols"] == 3
        for part in ("lights", "screen"):
            assert st["dis"][part] and st["reasons"][part], part
        assert not st["dis"]["clip"] and "clip" not in st["reasons"]
        assert not st["dis"]["countdown"]
        assert st["form"]["start_shot"] == "Chum bucket target"
        assert st["shots_on"] == ["Left ramp", "Right ramp"]
        status = st["status"]
        assert ("Maser target is not a shot on Jaws LE 1.02, so it starts on Chum bucket target "
                "until you pick one") in status
        assert "Powerline left, Powerline center, Powerline right are not on Jaws LE 1.02" in status
        assert status.startswith("Ready to build once saved") and "its file is unchanged" in status
        # the countdown stays live on Jaws, and says its callouts have not been heard
        assert "not been heard yet" in st["reasons"]["sound_unheard"]
        _f(w, "award", "1,500,000")                              # an edit: now the card's shots are saved
        _save(w)
        spec = MP.load(str(project / "modes" / "kaiju_rush" / "mode.json"))
        assert spec.title == "jaws_le_1_02" and spec.scoring_shots == ["Left ramp", "Right ramp"]
        assert spec.start_shot == "Chum bucket target" and spec.award == 1500000
        assert _status(w).startswith("Ready to build.")
        assert "Its file now has this card's shots" in _status(w)
        log_text = "\n".join(logged)
        assert "Powerline left" in log_text and "Jaws LE 1.02" in log_text


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_bare_project_keeps_godzilla_pro_1_15(tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MP

    with web_app(tmp_path, mfr="stern") as w:
        _project(w, tmp_path / "bare")
        st = _st(w)
        assert st["profile"]["shots"] == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
        assert "names no card" in st["title_text"]
        assert st["title_note"] == ""
        assert st["new_ok"] is True


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_greys_stacking_and_film_cuts_a_title_cannot_use(tmp_path):
    """Item 148 with items 140 and 142: TMNT Pro 1.59's port names none of the game's own
    mode queries and cannot use a clip, a screen picture or a sound of the mode's own, so
    "The game's own modes" and the three film buttons are greyed, each with the reason;
    Jaws LE 1.02 greys only the picture cut. On the machine's Premium 1.16 card
    everything stays live."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        assert w.call("modes.new")
        st = _st(w)
        assert st["dis"]["stack"]
        assert tmnt.why_not("stack") in st["reasons"]["stack"]
        assert all(st["dis"]["film_" + t] for t in ("clip", "still", "sound"))
        film = st["reasons"]["film"]
        assert "a clip, a picture for the screen or a sound" in film and "TMNT Pro 1.59" in film
        # item 147's events: TMNT's port names none, so "An event" is greyed with the reason
        assert st["dis"]["events"] and tmnt.why_not("events") in st["reasons"]["events"]

        jaws = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0",
                                   folder="jaws")
        _project(w, jaws)
        assert w.call("modes.new")
        st = _st(w)
        assert {t: st["dis"]["film_" + t] for t in ("clip", "still", "sound")} == {
            "clip": False, "still": True, "sound": False}
        assert "cutting a picture for the screen from a film" in st["reasons"]["film"]

        premium = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
                                      "1.16.0", folder="prem")
        _project(w, premium)
        assert w.call("modes.new")
        st = _st(w)
        assert not st["dis"]["stack"] and "stack" not in st["reasons"]
        assert not any(st["dis"]["film_" + t] for t in ("clip", "still", "sound"))
        assert "film" not in st["reasons"]
        assert not st["dis"]["events"] and "events" not in st["reasons"]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_no_port_card_after_another_title_never_rewrites_a_modes_shots(tmp_path):
    """Item 148: after a TMNT project, a project on a card with no port (Godzilla Pro 1.16)
    that already holds Godzilla modes shows each mode with the shots of the title it was
    made for - never TMNT's - read-only, and nothing it does rewrites mode.json. A no-port
    project with no modes shows no shot names at all."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    gz116 = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0",
                                folder="gz116")
    for name, spec in MP.example_specs()[:2]:
        MP.new_mode(str(gz116), name, spec)
    files = {slug: (gz116 / "modes" / slug / "mode.json").read_bytes()
             for slug, _s in MP.list_modes(str(gz116))[0]}
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, tmnt)
        assert w.call("modes.new")
        assert "Center loop" in _st(w)["profile"]["shots"]

        _project(w, gz116)
        st = _st(w)
        pro = [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
        assert st["profile"]["shots"] == pro and "Center loop" not in st["profile"]["shots"]
        assert svc._spec.name == "ATOMIC BREATH"                  # slug order: atomic_breath first
        assert sorted(st["shots_on"]) == sorted(MP.example("ATOMIC BREATH").scoring_shots)
        assert st["editor_on"] is False, "a mode on a card with no port is shown read-only"
        assert st["del_ok"] is True
        assert "read-only" in st["status"]
        _f(w, "award", "2,000,000")                             # even a change made in code
        _save(w)
        _select(w, "kaiju_rush")                                # and moving between modes
        assert svc._spec.name == "KAIJU RUSH"
        assert sorted(_st(w)["shots_on"]) == sorted(MP.example("KAIJU RUSH").scoring_shots)
        _save(w)
        assert {slug: (gz116 / "modes" / slug / "mode.json").read_bytes() for slug in files} == files

        jaws = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0",
                                   folder="jaws")
        _project(w, jaws)
        assert len(_st(w)["profile"]["shots"]) == 27
        empty = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw",
                                    "1.16.0", folder="empty")
        _project(w, empty)
        st = _st(w)
        assert st["profile"]["shots"] == [] and st["shots_on"] == []
        assert st["form"]["start_shot"] == ""
        assert st["new_ok"] is False


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_renamed_card_is_read_only_until_its_game_is_read(tmp_path, monkeypatch):
    """Item 148: while a renamed card's game is read off the UI loop, its project's mode is
    shown on its own title, read-only, and nothing is saved; once the card answers, the mode
    is on the card's port and editable. A card file that goes away mid-read stops the wait."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    def project(folder, image):
        p = tmp_path / folder
        p.mkdir()
        rec = {"input_path": str(image), "input_name": image.name, "size": 1, "mtime": 1,
               "card_version": "1.16.0"}
        (p / ".extract_source.json").write_text(json.dumps(rec), encoding="utf-8")
        return p

    go = threading.Event()

    def probe(path):
        go.wait(15)
        try:
            MP._PROBED[MP._probe_key(path)] = ("godzilla_le", "1.16.0")
        except OSError:
            return None, None
        return "godzilla_le", "1.16.0"

    monkeypatch.setattr(MP, "_PROBED", {})
    monkeypatch.setattr(MP, "probe_card_title", probe)
    image = tmp_path / "my card.raw"
    image.write_bytes(b"\0" * 1024)
    proj = project("proj", image)
    MP.new_mode(str(proj), spec=MP.example("KAIJU RUSH"))
    saved = (proj / "modes" / "kaiju_rush" / "mode.json").read_bytes()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        try:
            _project(w, proj)
            st = _st(w)
            assert "Reading which game" in st["title_text"]
            assert st["profile"]["shots"] == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
            assert st["editor_on"] is False
            _f(w, "award", "5")
            _save(w)
            assert (proj / "modes" / "kaiju_rush" / "mode.json").read_bytes() == saved
            go.set()
            assert _wait(w, lambda: "Premium/LE 1.16" in _st(w)["title_text"], 8)
            assert len(_st(w)["profile"]["shots"]) == 21 and svc._spec.title == "godzilla_le_1_16"
            assert _st(w)["dup_ok"] is True
            assert "read-only" not in _status(w)
        finally:
            go.set()

        go.clear()
        gone = tmp_path / "gone card.raw"
        gone.write_bytes(b"\0" * 1024)
        try:
            _project(w, project("gone", gone))
            assert "Reading which game" in _st(w)["title_text"]
            gone.unlink()
            assert _wait(w, lambda: "could not be read" in _st(w)["title_text"], 8)
            assert _st(w)["new_ok"] is True
        finally:
            go.set()


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_bare_project_keeps_a_modes_own_title(tmp_path):
    """Item 148: a project that names no card retargets nothing. A TMNT mode in it is shown
    with TMNT's shots and saved back as TMNT, while New still makes Godzilla Pro 1.15."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    project = tmp_path / "bare"
    project.mkdir()
    spec = MP.blank_spec(tmnt, "TURTLE RUSH")
    spec.scoring_shots = ["Left orbit", "Left ramp", "Right top lane"]
    slug, _s = MP.new_mode(str(project), spec=spec)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        assert _st(w)["profile"]["shots"] == [n for n, _m in tmnt.shots]
        _f(w, "award", "123456")
        _save(w)
        saved = MP.load(str(project / "modes" / slug / "mode.json"))
        assert saved.title == tmnt.key and saved.scoring_shots == spec.scoring_shots
        assert saved.award == 123456
        assert _st(w)["examples"][0]["name"] == "KAIJU RUSH"
        new = w.call("modes.new")
        assert MP.load(str(project / "modes" / new / "mode.json")).title == MP.GODZILLA_PRO_1_15.key
        assert _st(w)["profile"]["shots"] == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_opening_a_mode_on_another_titles_card_writes_nothing_until_an_edit(tmp_path):
    """Item 148: opening a mode made for Godzilla Pro 1.15 on a Jaws LE 1.02 card matches
    its shots by name IN THE FORM only. Moving between modes, pressing New and switching
    project, with no edit, leave its mode.json byte for byte as it was, so a build still
    refuses it (MODE_SDK.md: a mode naming a shot the card's game lacks is refused, never
    built with shots left out). On the machine's Premium 1.16 card a mode saved as Pro 1.15
    keeps its file too."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP

    def files(project):
        return {p.parent.name: p.read_bytes() for p in project.glob("modes/*/mode.json")}

    def pump(seconds):
        time.sleep(seconds)
        w.drain()

    jaws = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0", folder="jaws")
    MP.new_mode(str(jaws), spec=MP.example("KAIJU RUSH"))
    MP.new_mode(str(jaws), spec=MP.example("ATOMIC BREATH"))
    before = files(jaws)
    bare = tmp_path / "bare"
    bare.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, jaws)
        assert svc._spec.name == "ATOMIC BREATH" and svc._spec.title == "jaws_le_1_02"   # in the form
        for slug in ("kaiju_rush", "atomic_breath", "kaiju_rush"):   # between the two, no edit
            _select(w, slug)
            pump(0.2)
        assert svc._spec.name == "KAIJU RUSH" and _st(w)["form"]["start_shot"] == "Chum bucket target"
        assert "until you pick one" in _status(w)
        _project(w, bare)                                    # and away, no edit
        pump(0.7)
        assert files(jaws) == before
        _project(w, jaws)
        new = w.call("modes.new")                            # New flushes only an edit
        pump(0.7)
        after = files(jaws)
        assert set(after) == set(before) | {new} and {k: after[k] for k in before} == before
        with pytest.raises(MA.ModeAssetError) as e:
            MA.build(str(jaws), None, None, str(tmp_path / "out"))
        assert "KAIJU RUSH" in str(e.value) and "Maser target" in str(e.value)

        prem = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
                                   "1.16.0", folder="prem")
        MP.new_mode(str(prem), spec=MP.example("KAIJU RUSH"))
        saved = files(prem)
        assert MP.load(str(prem / "modes" / "kaiju_rush" / "mode.json")).title == "godzilla_pro_1_15"
        _project(w, prem)
        assert svc._spec.title == "godzilla_le_1_16"
        assert "until you pick one" not in _status(w)        # every shot is on Premium
        _project(w, bare)
        pump(0.7)
        assert files(prem) == saved


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_and_the_games_call_follow_the_title(tmp_path):
    """Item 148 with item 141: on TMNT Pro 1.59 the Advanced section's points per shot and
    its early-ending shot offer TMNT's own 17 shots (they listed Godzilla Pro 1.15's on
    every game), its callout picks name none (TMNT's port names no countdown or time-up
    callout), and "The game's own call" is greyed with the reason, since nothing plays when
    time is up. A TMNT shot's own points are saved as TMNT's mask and shown again when the
    mode is opened again. A project with no modes shows none of the last mode's values."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    tmnt = MP.profile("turtles_pro_1_59")
    names = [n for n, _m in tmnt.shots]
    project = _modes_card_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw", "1.59.0")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.call("modes.new")
        st = _st(w)
        assert list(st["awards"]) == names
        assert st["profile"]["end_shots"] == [svc.PARAM_NEVER] + names
        assert st["profile"]["callouts"] == [] and "TMNT Pro 1.59" in st["profile"]["callouts_none"]
        assert st["dis"]["end_game"]                            # "The game's own call" greyed
        assert "nothing plays when time is up" in st["reasons"]["sound"]
        assert st["editor_on"] is True                          # a shot's own points stay live
        assert st["dis"]["clip_both"] and "a second clip" in st["reasons"]["clip_both"]

        _set(w, "award:Left orbit", "750000")
        _f(w, "end_shot", "Center loop")
        _save(w)
        spec = MP.load(str(project / "modes" / slug / "mode.json"))
        assert spec.shot_award == [["Left orbit", 750000]] and spec.end_shot == "Center loop"
        assert MP.validate(spec) == []
        cfg = MP.runtime_cfg(spec, slug)
        assert "shot_award     0x%08x 750000" % tmnt.mask(["Left orbit"]) in cfg
        assert "end_shot       0x%08x" % tmnt.mask(["Center loop"]) in cfg

        _project(w, tmp_path / "empty")
        st = _st(w)
        assert list(st["awards"]) == [n for n, _m in MP.GODZILLA_PRO_1_15.shots]
        for key in ("name", "seconds", "award", "start_shot", "clip_title"):
            assert st["form"][key] == "", key
        assert st["shots_on"] == []
        _project(w, project)
        st = _st(w)
        assert st["awards"]["Left orbit"] == "750000"        # shown, not kept aside
        assert st["form"]["end_shot"] == "Center loop"
        no_port = _modes_card_project(tmp_path, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw",
                                      "1.16.0", folder="noport")
        _project(w, no_port)                                 # no port, no modes: no shot names anywhere
        st = _st(w)
        assert st["awards"] == {} and st["profile"]["end_shots"] == [svc.PARAM_NEVER]
        assert st["form"]["name"] == ""

        prem = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
                                   "1.16.0", folder="prem")
        _project(w, prem)
        assert w.call("modes.new")
        le = MP.profile("godzilla_le_1_16")
        st = _st(w)
        assert list(st["awards"]) == [n for n, _m in le.shots]
        callouts = st["profile"]["callouts"]
        assert len(callouts) == 2
        assert callouts[0]["label"] == "Ten seconds left (%d)" % le.callout_ten_seconds
        assert not st["dis"]["end_game"]
        assert "sound_unheard" not in st["reasons"]
        assert not st["dis"]["clip_both"] and "clip_both" not in st["reasons"]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_a_godzilla_modes_advanced_fields_follow_a_jaws_card(tmp_path):
    """Family sweep (item 148's open gap with item 141): a Godzilla Pro 1.15 mode with points
    on a Powerline, a Powerline that ends it early and a hand-typed callout, opened on a Jaws
    LE 1.02 card. Before, the Powerline's points were kept aside where no control showed them
    and every build refused the mode for good. Now the form drops what Jaws lacks and says so,
    moves the ten-seconds call to Jaws's own id, and after one edit the file builds."""
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "jaws_le-1_02_0.Release.16G.sdcard.raw", "1.02.0")
    spec = MP.example("KAIJU RUSH")
    spec.clip = "none"                                   # no stock bank is read here
    spec.shot_award = [["Powerline left", 750000], ["Left ramp", 500000]]
    spec.end_shot = "Powerline right"
    spec.callout_at = [[10, 1291], [3, 1111]]
    slug, _spec = MP.new_mode(str(project), spec=spec)
    path = project / "modes" / slug / "mode.json"
    before = path.read_bytes()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        st = _st(w)
        assert st["awards"]["Left ramp"] == "500000"
        assert "Powerline left" not in st["awards"] and svc._params_kept_awards == []
        assert st["form"]["end_shot"] == svc.PARAM_NEVER and "end_shot" not in svc._params_raw
        f = st["form"]
        assert [(f["callout_secs_%d" % i], f["callout_id_%d" % i]) for i in range(2)] == [
            ("10", "1387"), ("", "")]
        assert svc._params_kept_callouts == []
        status = st["status"]
        for words in ("Powerline left is not on Jaws LE 1.02, so its own points are left out",
                      "Powerline right is not on Jaws LE 1.02, so no shot ends the mode early",
                      "callout 1111 is a sound number of another game and no callout measured "
                      "on Jaws LE 1.02",
                      "callout 1291 is 1387 on Jaws LE 1.02", "a build refuses it"):
            assert words in status, words
        assert path.read_bytes() == before                   # opening it wrote nothing
        with pytest.raises(MA.ModeAssetError, match="callout 1111"):
            MA.build(str(project), None, None, str(tmp_path / "out"))

        _f(w, "award", "1,500,000")                          # one edit saves the card's version
        _save(w)
        saved = MP.load(str(path))
        assert saved.shot_award == [["Left ramp", 500000]] and saved.end_shot == ""
        assert saved.callout_at == [[10, 1387]] and MP.validate(saved) == []
        assert _status(w).startswith("Ready to build.")
        out = tmp_path / "out2"
        MA.build(str(project), None, None, str(out))
        cfg = (out / "padmode" / "mode.cfg").read_text(encoding="utf-8")
        assert "shot_award     0x%08x 500000" % MP.profile("jaws_le_1_02").mask(["Left ramp"]) in cfg
        assert "callout_at     10 1291" not in cfg and "1111" not in cfg and "end_shot" not in cfg


# ---------------------------------------------------------------------- the form's sections
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_offers_sounds_of_its_own(tmp_path):
    """Item 150: a start sound, a shot sound (every Nth shot) and music, each a WAV in the
    mode folder, saved with the mode and turned into the mode-file keys once carried."""
    import wave
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_sounds as MS

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.call("modes.new")
        folder = project / "modes" / slug
        assert {a for a, _m, _w, _s in svc._OWN_SOUNDS} == {"sound_start", "sound_shot", "music"}
        for name in ("start.wav", "shot.wav", "music.wav", "end.wav"):
            with wave.open(str(folder / name), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(44100)
                f.writeframes(b"\x00\x00" * 4410)

        # what "My sound…" does after the file dialog: the file named, the radio on file
        def named():
            svc._spec.sound_start, svc._spec.sound_shot = "start.wav", "shot.wav"
            svc._spec.music, svc._spec.end_sound = "music.wav", "end.wav"
        w.run(named)
        for var in ("start_sound_mode", "shot_sound_mode", "music_mode", "end_mode"):
            _f(w, var, "file")
        _f(w, "sound_shot_every", "3")
        _save(w)
        data = json.loads((folder / "mode.json").read_text(encoding="utf-8"))
        assert (data["sound_start"], data["sound_shot"], data["music"], data["sound_shot_every"]) == \
            ("start.wav", "shot.wav", "music.wav", 3)
        assert "Ready to build" in _status(w)
        assert _st(w)["labels"]["music"] == "Sound: music.wav"

        spec = MP.load(str(folder / "mode.json"))
        carried = MS.assign_specs(spec.title, [spec])[0]
        assert set(carried) == set(MS.SOUND_KEYS) | {"music_sid"}      # item 150 follow-up: its own bed
        text = MP.runtime_cfg(spec, slug, own_sounds=carried)
        assert "sound_shot     %d 3" % carried["sound_shot"] in text
        assert "music          %d %d" % (carried["music"], carried["music_sid"]) in text
        assert "callout_end" in text                     # an older mode.so still has its call
        assert "sound_start" not in MP.runtime_cfg(spec, slug)

        _f(w, "music_mode", "none")
        _save(w)
        assert json.loads((folder / "mode.json").read_text(encoding="utf-8"))["music"] == ""
        _f(w, "sound_shot_every", "0")
        _save(w)
        assert "every 2nd" in _status(w)


def test_modes_tab_own_sounds_note_never_says_write_leaves_them_out():
    """Item 149 (`b15b0ebd`) made Write carry item 150's start sound, shot sound and music,
    so the "Sounds of its own" note may not go back to saying Write leaves them off the
    card. A stale note here is the tab telling a person their sounds will not be written."""
    js = _modes_js()
    start = js.index('title="Sounds of its own"')
    note = js[start:js.index("<//>", js.index('class="small muted wrap"', start))]
    note = note[note.index('class="small muted wrap"'):]
    assert "does not add" not in note and "not yet" not in note and "yet." not in note, note
    assert "Write puts them on the card" in note, note


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_how_often_a_mode_can_start(tmp_path):
    """Item 139: the tab's "How often it can start" choices land in mode.json and in the
    generated mode file, the tab says it in words - the same words the generator gives
    for the saved spec, so the tab and the file agree - and reopening restores the form.
    A mode left at the default writes neither key, as before."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.call("modes.new")
        path = project / "modes" / slug / "mode.json"
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert (data["starts"], data["cooldown"]) == ("unlimited", 0)
        text = MP.runtime_cfg(MP.load(str(path)), slug)
        assert "\nstarts " not in text and "\ncooldown " not in text
        assert _st(w)["starts_words"] == "Can start: any number of times"

        cases = [
            ("once_per_game", None, "0", "once_per_game", 0, "starts         once_per_game"),
            ("once_per_ball", None, "15", "once_per_ball", 15, "starts         once_per_ball"),
            ("count", "3", "0", 3, 0, "starts         3"),
            ("unlimited", None, "20", "unlimited", 20, "cooldown       20"),
        ]
        for policy, count, cooldown, want_starts, want_cooldown, want_line in cases:
            _f(w, "starts_policy", policy)
            if count is not None:
                _f(w, "starts_count", count)
            _f(w, "cooldown", cooldown)
            _save(w)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert (data["starts"], data["cooldown"]) == (want_starts, want_cooldown), policy
            spec = MP.load(str(path))
            assert want_line in MP.runtime_cfg(spec, slug).splitlines(), policy
            assert _st(w)["starts_words"] == MP.starts_words(spec), policy
            assert "Ready to build" in _status(w), policy

        # reopening the mode puts the form back as it was saved
        _f(w, "starts_policy", "count")
        _f(w, "starts_count", "7")
        _f(w, "cooldown", "45")
        _save(w)

        def reopen():
            svc._slug = None
            svc.refresh(select=slug)
        w.run(reopen)
        f = _st(w)["form"]
        assert f["starts_policy"] == "count" and f["starts_count"] == "7"
        assert f["cooldown"] == "45"
        assert _st(w)["starts_words"] == \
            "Can start: up to 7 times a game, for each player; not again until 45 s after it ends"

        # a count that is not one is named, not silently changed
        _f(w, "starts_count", "0")
        _save(w)
        assert "How often it can start" in _status(w)


# ---------------------------------------------------------------------- item 142: from a film
def _film(tmp_path):
    from pinball_decryptor.core import audio
    from tests.test_stern_film_cut import make_film

    ff = audio.find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    film = make_film(str(tmp_path / "films"), ff)
    if not film:
        pytest.skip("this ffmpeg cannot make the synthetic film")
    return ff, film


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_from_a_film_makes_the_cut_the_modes_clip_sound_and_picture(tmp_path):
    """Item 142: "From a film" on the Modes tab. The dialog's logic (FilmCutForm, never a
    window) cuts a span of a synthetic lavfi film into the open mode's folder, and the tab
    makes the cut the mode's clip, end sound and screen picture, saves where each came
    from, and still says Ready to build. The mode keeps only the cut: nothing of the film
    is copied in."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.webui.modes_filmcut import FilmCutForm

    ff, film = _film(tmp_path)
    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.run(svc.new_mode, "FILM RUSH")
        st = _st(w)
        assert "Nothing cut from a film yet" in st["labels"]["film"]
        assert not any(st["dis"]["film_" + t] for t in ("clip", "still", "sound"))
        folder = MP.mode_folder(str(project), slug)

        form = FilmCutForm.from_spec(svc._spec, "clip")
        form.film, form.start, form.length, form.crop = film, "0:02", "6", "fill"
        form.take_sound = form.take_still = True
        w.run(svc.apply_film_cut, form.apply(folder, ff))

        data = json.loads(open(os.path.join(folder, "mode.json"), encoding="utf-8").read())
        assert (data["clip"], data["clip_file"], data["end_sound"], data["screen_art"]) == (
            "file", "clip.mp4", "end.wav", "art.png")
        assert (data["clip_from"], data["clip_length"], data["sound_from"], data["art_from"]) == (
            2.0, 6.0, 2.0, 2.0)
        assert data["clip_source"] == data["sound_source"] == data["art_source"] == os.path.abspath(film)
        assert sorted(os.listdir(folder)) == ["art.png", "clip.mp4", "end.wav", "mode.json"]
        film_bytes = open(film, "rb").read()
        assert all(open(os.path.join(folder, n), "rb").read() != film_bytes for n in os.listdir(folder))
        st = _st(w)
        assert "Ready to build" in st["status"]
        assert (st["form"]["clip"], st["form"]["end_mode"], st["form"]["art_mode"]) == (
            "file", "file", "file")
        assert st["labels"]["film"] == ("Clip: 6 s from 0:02. Sound: 6 s from 0:02. Picture: the "
                                        "frame at 0:02. Cut from synthetic_film.mp4.")
        assert "Video: clip.mp4" in st["labels"]["clip"]
        spec = MP.load(os.path.join(folder, "mode.json"))
        assert "synthetic_film" not in MP.runtime_cfg(spec, slug)


def _film_dialog_setup(w, tmp_path, monkeypatch):
    """Item 142 dialog tests: the synthetic film, a project with one mode open, and the
    dialog's staging folders kept under tmp_path so a leaked one is seen."""
    import tempfile

    ff, film = _film(tmp_path)
    project = tmp_path / "proj"
    svc = _svc(w)
    _project(w, project)
    slug = w.run(svc.new_mode, "FILM RUSH")
    stages = tmp_path / "stages"
    stages.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(stages))
    return ff, film, stages, svc, slug


def _staged_left(stages):
    from pinball_decryptor.webui import modes_filmcut as FCD
    return [n for n in os.listdir(str(stages)) if n.startswith(FCD.STAGE_PREFIX)]


@pytest.mark.usefixtures("preview_modes_on")
def test_film_cut_dialog_probes_previews_and_cuts_on_workers(tmp_path, monkeypatch):
    """Item 142: the "From a film" dialog, driven as the page drives it: a Preview pressed
    before the film's probe has answered does not strand the film line, the preview draws,
    Cut runs on a worker and makes the cut the mode's, the dialog closes and no staging
    folder is left behind."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    with web_app(tmp_path, mfr="stern") as w:
        ff, film, stages, svc, slug = _film_dialog_setup(w, tmp_path, monkeypatch)
        svc._ffmpeg_fn = lambda: ff
        assert w.call("modes.film_open", "clip") is True
        dlg = _st(w)["film"]
        assert dlg["film"] == "" and dlg["take_clip"]
        fields = dict(dlg, film=film, start="0:02", length="6", crop="fill", take_sound=True,
                      take_still=True)
        assert w.call("modes.film_probe", fields)
        assert w.call("modes.film_preview", fields)          # before the probe answers

        def drawn():
            d = _st(w)["film"] or {}
            return d.get("preview") and d.get("info") not in (None, "", "Reading the film…")
        assert _wait(w, drawn, 60)
        dlg = _st(w)["film"]
        assert dlg["info"].startswith("720x300, 23.976 fps, 0:10, sound 6 ch")
        assert dlg["status"] == "The frame at 0:02, as the clip will show it."

        assert w.call("modes.film_cut", fields)
        _set(w, "film:start", "0:09")                         # an edit during the cut changes nothing
        assert _wait(w, lambda: _st(w)["film"] is None, 120)
        folder = MP.mode_folder(svc._open_project, slug)
        data = json.loads(open(os.path.join(folder, "mode.json"), encoding="utf-8").read())
        assert (data["clip_file"], data["end_sound"], data["screen_art"]) == ("clip.mp4", "end.wav", "art.png")
        assert (data["clip_from"], data["clip_length"], data["clip_crop"], data["art_crop"]) == (
            2.0, 6.0, "fill", "fill")
        assert sorted(os.listdir(folder)) == ["art.png", "clip.mp4", "end.wav", "mode.json"]
        assert "Ready to build" in _status(w)
        _wait_threads("modes-film-cut")
        assert _staged_left(stages) == []

        assert w.call("modes.film_open", "clip")             # reopens on the cut, its crop included
        again = _st(w)["film"]
        assert (again["film"], again["start"], again["crop"]) == (os.path.abspath(film), "0:02", "fill")
        w.call("modes.film_close")
        assert _st(w)["film"] is None


@pytest.mark.usefixtures("preview_modes_on")
def test_film_cut_dialog_closed_during_a_cut_leaves_the_mode_as_it_was(tmp_path, monkeypatch):
    """Item 142: Cancel (or Escape, or the window's X) while a cut runs abandons it: the
    mode's files and mode.json are untouched and the staging folder goes. A cut already
    being moved into the mode when the dialog closes still lands, and the mode's file
    follows it."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.webui import modes_filmcut as FCD

    with web_app(tmp_path, mfr="stern") as w:
        ff, film, stages, svc, slug = _film_dialog_setup(w, tmp_path, monkeypatch)
        svc._ffmpeg_fn = lambda: ff
        folder = MP.mode_folder(svc._open_project, slug)
        first = FCD.FilmCutForm(film=film, start="0:02", length="6", take_sound=True)
        w.run(svc.apply_film_cut, first.apply(folder, ff))
        mode_json = os.path.join(folder, "mode.json")
        before = {n: open(os.path.join(folder, n), "rb").read()
                  for n in ("clip.mp4", "end.wav", "mode.json")}

        gate = threading.Event()
        real_apply = FCD.FilmCutForm.apply

        def held_apply(self, mode_folder, ffmpeg=None):
            gate.wait(60)
            return real_apply(self, mode_folder, ffmpeg)
        monkeypatch.setattr(FCD.FilmCutForm, "apply", held_apply)
        assert w.call("modes.film_open", "clip")
        fields = dict(_st(w)["film"], film=film, start="0:06", length="3")
        assert w.call("modes.film_cut", fields)
        time.sleep(0.2)
        w.call("modes.film_close")                           # Cancel, mid-cut
        gate.set()
        _wait_threads("modes-film-cut")
        time.sleep(0.4)
        w.drain()
        after = {n: open(os.path.join(folder, n), "rb").read()
                 for n in ("clip.mp4", "end.wav", "mode.json")}
        assert after == before
        assert sorted(os.listdir(folder)) == ["clip.mp4", "end.wav", "mode.json"]
        assert _staged_left(stages) == []

        # closed while the cut is already being moved in: it lands, and mode.json follows it
        monkeypatch.setattr(FCD.FilmCutForm, "apply", real_apply)
        moving, go = threading.Event(), threading.Event()
        real_commit = FCD.commit_cut

        def held_commit(result, mode_folder):
            moving.set()
            go.wait(60)
            return real_commit(result, mode_folder)
        monkeypatch.setattr(FCD, "commit_cut", held_commit)
        assert w.call("modes.film_open", "clip")
        fields = dict(_st(w)["film"], start="0:06", length="3")
        assert w.call("modes.film_cut", fields)
        assert moving.wait(120)
        w.call("modes.film_close")
        go.set()
        _wait_threads("modes-film-cut")
        assert _wait(w, lambda: json.loads(open(mode_json, encoding="utf-8").read())["clip_from"]
                     == 6.0, 60)
        data = json.loads(open(mode_json, encoding="utf-8").read())
        assert (data["clip_from"], data["clip_length"]) == (6.0, 3.0)
        assert open(os.path.join(folder, "clip.mp4"), "rb").read() != before["clip.mp4"]
        assert _staged_left(stages) == []


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_can_run_during_the_game_s_own_modes(tmp_path):
    """Item 140: "Can run during the game's own modes" is on for a new mode; unticking it
    saves stack false, the generated file says `stack no`, and reopening the mode shows
    it unticked while another mode keeps its own tick."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    assert _modes_js().count("Can run during the game's own modes") == 1
    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.run(svc.new_mode, "WAITS")
        assert _st(w)["form"]["stack"] is True
        _f(w, "stack", False)
        _save(w)
        path = project / "modes" / slug / "mode.json"
        assert json.loads(path.read_text(encoding="utf-8"))["stack"] is False
        assert "stack          no" in MP.runtime_cfg(MP.load(str(path)), slug)

        other = w.run(svc.new_mode, "STACKS")
        assert other != slug and _st(w)["form"]["stack"] is True
        _select(w, slug)
        assert svc._slug == slug and _st(w)["form"]["stack"] is False
        assert json.loads((project / "modes" / other / "mode.json").read_text(
            encoding="utf-8"))["stack"] is True


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_lights_the_shots_and_sets_a_display_priority(tmp_path):
    """Item 157: the form's "Light the shots that score" (a colour and a pattern) and its "Display
    priority" land in mode.json and in the generated file as `light_shots` and `priority`; a new mode
    writes neither (the bytes of every mode before them), a reopened mode shows them, a bad priority is
    named, and the section's words are plain labels."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    js = _modes_js()
    assert "Light the shots that score" in js and "Display priority" in js
    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.run(svc.new_mode, "LIT")
        path = project / "modes" / slug / "mode.json"
        cfg = MP.runtime_cfg(MP.load(str(path)), slug)
        assert "light_shots" not in cfg and "priority" not in cfg
        f = _st(w)["form"]
        assert f["light_shots_on"] is False and f["priority"] == "0"
        assert _st(w)["editor_on"] is True                       # the open mode's form is live

        _f(w, "light_shots_on", True)
        _f(w, "light_shots_color", "#FF6000")
        _f(w, "light_shots_pattern", "Pulse")
        _f(w, "priority", "180")
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["light_shots"] == "#FF6000" and data["light_shots_pattern"] == "pulse"
        assert data["priority"] == 180
        cfg = MP.runtime_cfg(MP.load(str(path)), slug)
        assert "light_shots    ff6000 pulse\n" in cfg and "priority       180\n" in cfg

        other = w.run(svc.new_mode, "PLAIN")
        f = _st(w)["form"]
        assert other != slug and f["light_shots_on"] is False and f["priority"] == "0"
        _select(w, slug)
        f = _st(w)["form"]
        assert svc._slug == slug and f["light_shots_on"] is True
        assert f["light_shots_pattern"] == "Pulse" and f["priority"] == "180"

        _f(w, "priority", "300")
        _save(w)
        assert "display priority is 0 (none) to 255" in _status(w)
        _f(w, "priority", "0")
        _f(w, "light_shots_on", False)
        _save(w)
        cfg = MP.runtime_cfg(MP.load(str(path)), slug)
        assert "light_shots" not in cfg and "priority" not in cfg


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_section_writes_every_parameter(tmp_path):
    """Item 141: the Advanced controls edit every parameter the tab hid - the award ladder,
    points per shot, an ending shot, a second clip, callouts at chosen seconds and how long
    the screen stays up - and each lands in mode.json and in the runtime file, and a mode
    that sets any of them opens with them all shown again."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.run(svc.new_mode, "PARAM TEST")
        path = project / "modes" / slug / "mode.json"
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert (data["award_ladder"], data["shot_award"], data["end_shot"], data["clip_both"],
                data["callout_at"], data["restore_after"]) == ("rising", [], "", {}, [], 6)

        _f(w, "seconds", "45")
        _f(w, "award_ladder", "fixed")
        _set(w, "award:Building", "5,000,000")
        _set(w, "award:Godzilla target", "3000000")
        _f(w, "end_shot", "Shield target left")
        _f(w, "clip", "title")
        _f(w, "clip_both", "title")
        _f(w, "clip_both_title", "PARAM END")
        _f(w, "clip_both_seconds", "3")
        _f(w, "callout_secs_0", "30")
        _f(w, "callout_id_0", "1291")
        _f(w, "callout_secs_1", "20")
        # Pick: one of the callouts measured on this game
        _f(w, "callout_id_1", str(MP.callout_choices(MP.GODZILLA_PRO_1_15)[1][1]))
        _f(w, "restore_after", "8")
        _save(w)
        assert "Ready to build" in _status(w)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["award_ladder"] == "fixed"
        assert data["shot_award"] == [["Building", 5000000], ["Godzilla target", 3000000]]
        assert data["end_shot"] == "Shield target left"
        assert data["clip_both"] == {"clip": "title", "title": "PARAM END", "seconds": 3.0}
        assert data["callout_at"] == [[30, 1291], [20, 1295]] and data["restore_after"] == 8
        cfg = MP.runtime_cfg(MP.load(str(path)), slug)
        for line in ("award_ladder   fixed", "shot_award     0x00400000 5000000",
                     "shot_award     0x00080000 3000000", "end_shot       0x80000000",
                     "clip_start     PadMode_param_test_Clip", "clip_end       PadMode_param_test_Clip2",
                     "callout_at     30 1291", "callout_at     20 1295", "restore_after  8"):
            assert line + "\n" in cfg, line

        # reopen: every control comes back
        w.run(svc._open, slug, MP.load(str(path)))
        st = _st(w)
        f = st["form"]
        assert f["award_ladder"] == "fixed" and f["end_shot"] == "Shield target left"
        assert st["awards"]["Building"] == "5000000" and st["awards"]["Big loop"] == ""
        assert (f["clip_both"], f["clip_both_title"], f["clip_both_seconds"]) == (
            "title", "PARAM END", "3")
        assert [(f["callout_secs_%d" % i], f["callout_id_%d" % i]) for i in range(4)] == [
            ("30", "1291"), ("20", "1295"), ("", ""), ("", "")]
        assert f["restore_after"] == "8"

        # the same clip at both ends, and back to none
        _f(w, "clip_both", "same")
        _f(w, "end_shot", svc.PARAM_NEVER)
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["clip_both"] == {"clip": "same"} and data["end_shot"] == ""
        _f(w, "clip_both", "none")
        _save(w)
        assert json.loads(path.read_text(encoding="utf-8"))["clip_both"] == {}


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_section_names_bad_values_and_keeps_what_it_cannot_show(tmp_path):
    """A bad value in the Advanced section is named in the status, not dropped; rows the form
    has no place for (callouts past its four rows, a shot this title does not name) are
    written back as they were; and with no mode open every Advanced field is greyed."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        assert _st(w)["editor_on"] is False

        slug = w.run(svc.new_mode, "BAD")
        assert _st(w)["editor_on"] is True
        _set(w, "award:Building", "lots")
        _f(w, "seconds", "30")
        _f(w, "callout_secs_0", "45")
        _f(w, "callout_id_0", "1291")
        _f(w, "restore_after", "0")
        _f(w, "clip", "none")
        _f(w, "clip_both", "same")
        _save(w)
        status = _status(w)
        for words in ("Building's own points", "45 seconds left", "1 to 60 seconds",
                      "choose the first clip"):
            assert words in status, words
        path = project / "modes" / slug / "mode.json"
        assert json.loads(path.read_text(encoding="utf-8"))["shot_award"] == [["Building", "lots"]]

        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(callout_at=[[25, 1], [24, 2], [23, 3], [22, 4], [21, 5]],
                    shot_award=[["Spinner", 7]], restore_after=6, clip_both={})
        path.write_text(json.dumps(data), encoding="utf-8")
        w.run(svc._open, slug, MP.load(str(path)))
        _set(w, "award:Building", "")
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["callout_at"] == [[25, 1], [24, 2], [23, 3], [22, 4], [21, 5]]
        assert data["shot_award"] == [["Spinner", 7]]


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_advanced_section_keeps_hand_edited_values_until_changed(tmp_path):
    """Item 141: a hand-edited mode.json the Advanced section cannot show (an unknown ladder,
    end shot or second clip, a shot name that is not text, a second award for one shot, a
    callout row that is not [seconds, id]) opens without an error, is written back as it was,
    and is named in the status; setting that control replaces it. The form shows a shot's
    FIRST award, the one the runtime pays. restore_after is checked only with the mode's own
    screen, the only time it is written."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.run(svc.new_mode, "RAW")
        _save(w)
        path = project / "modes" / slug / "mode.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(award_ladder="steep", end_shot=["Shield target left"], clip_both={"clip": "loop"},
                    shot_award=[["Building", 5], ["Building", 7], [["x"], 3]],
                    callout_at=[[25, 1], "bad", [24, 2]])
        path.write_text(json.dumps(data), encoding="utf-8")
        w.run(svc._open, slug, MP.load(str(path)))
        st = _st(w)
        f = st["form"]
        assert (f["award_ladder"], f["end_shot"], f["clip_both"]) == (
            "rising", svc.PARAM_NEVER, "none")
        assert st["awards"]["Building"] == "5"
        assert [(f["callout_secs_%d" % i], f["callout_id_%d" % i]) for i in range(4)] == [
            ("25", "1"), ("24", "2"), ("", ""), ("", "")]
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert (data["award_ladder"], data["end_shot"], data["clip_both"]) == (
            "steep", ["Shield target left"], {"clip": "loop"})
        assert data["shot_award"] == [["Building", 5], ["Building", 7], [["x"], 3]]
        assert data["callout_at"] == [[25, 1], [24, 2], "bad"]
        status = _status(w)
        for words in ("rising or fixed", "to end the mode", "same clip, a title card", "[shot, points]",
                      "Building has its own points twice", "[seconds left, id]"):
            assert words in status, words

        # a page control only reports a CHANGE (picking the value it already shows sends
        # nothing), so each is moved off the value it shows and back
        _f(w, "award_ladder", "fixed")
        _f(w, "end_shot", "Shield target left")
        _f(w, "end_shot", svc.PARAM_NEVER)
        _f(w, "clip_both", "same")
        _f(w, "clip_both", "none")
        _save(w)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert (data["award_ladder"], data["end_shot"], data["clip_both"]) == ("fixed", "", {})

        # restore_after does nothing without the mode's own screen, so it does not block a build
        data.update(shot_award=[], callout_at=[])
        path.write_text(json.dumps(data), encoding="utf-8")
        w.run(svc._open, slug, MP.load(str(path)))
        _f(w, "restore_after", "0")
        _save(w)
        assert "1 to 60 seconds" in _status(w)
        _f(w, "screen", False)
        _save(w)
        assert "1 to 60 seconds" not in _status(w)


# ---------------------------------------------------------------------- item 145: the game's own modes
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_lists_the_games_own_modes_and_stages_like_defaults(tmp_path):
    """Item 145: the Modes tab lists the timers and awards of the modes the game shipped
    with (from item 144's table for the project's build), and Set / Stock / All to stock
    stage them in the project's .staged_changes.json: a word under "stock_modes", an
    operator setting under Defaults' own "settings". A number the game computes in code
    stays read-only and says why."""
    from pinball_decryptor.core import staged_changes

    project = _stock_modes_project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        stock = _st(w)["stock"]
        assert "godzilla_pro 1.15" in stock["msg"]
        rows = {r["key"]: r for r in stock["rows"]}
        assert "12.start.caward_add" in rows and "12.timer.seconds" in rows
        assert "12.timer.v57" not in rows                      # one row per operator setting
        assert rows["12.start.caward_add"]["mode"] == "Battle vs Ebirah"
        assert rows["12.start.caward_add"]["value"] == "250,000"

        # an award: select, type, Set
        w.call("modes.stock_select", "12.start.caward_add")
        w.call("modes.stock_set", "777,777")
        data = staged_changes.load(str(project))
        assert data["stock_modes"] == {"build": "godzilla_pro 1.15",
                                       "values": {"12.start.caward_add": 777777},
                                       "touched": ["12.start.caward_add"]}
        rows = {r["key"]: r for r in _st(w)["stock"]["rows"]}
        assert rows["12.start.caward_add"]["value"].startswith("777,777")
        # a timer that is an operator setting: Defaults' settings key
        w.call("modes.stock_select", "12.timer.seconds")
        note = _st(w)["stock"]["note"]
        assert "Defaults tab" in note
        # what the emulator measured (item 145 runs 2-3): a machine at the default follows it
        assert "still on the game's default takes the new one" in note
        assert "still on the game's default takes the new one" in svc.STOCK_TIP
        w.call("modes.stock_set", "30")
        assert staged_changes.load(str(project))["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 30}
        w.call("modes.stock_set", "99")                         # outside the game's own range
        assert "between 30 and 70" in _st(w)["stock"]["note"]
        assert staged_changes.load(str(project))["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 30}

        # code stays read-only, with the reason
        w.call("modes.stock_select", "12.shot.caward_add")
        stock = _st(w)["stock"]
        assert stock["row_on"] is False
        assert "Read-only" in stock["note"] and "code" in stock["note"]

        # Stock on one row, then All to stock
        w.call("modes.stock_select", "12.start.caward_add")
        w.call("modes.stock_reset")
        assert staged_changes.load(str(project))["stock_modes"]["values"] == {}
        w.call("modes.stock_all")
        data = staged_changes.load(str(project))
        assert "settings" not in data and data["stock_modes"]["values"] == {}


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_says_when_the_build_has_no_table(tmp_path):
    project = _stock_modes_project(tmp_path, "turtles_pro-1_59_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        stock = _st(w)["stock"]
        assert "doesn't know" in stock["msg"]
        assert "turtles_pro 1.59.0" in stock["msg"]
        assert stock["rows"] == []
        assert stock["on"] is False and stock["row_on"] is False


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_picks_a_tank_position_by_shot_and_sets_a_spin_count(tmp_path, manufacturers_by_key):
    """Item 159: a stock mode's SHOTS as data. Tank attack's positions are picked by shot name
    (a select of the shots the switches send alone, and none), ebirah's spins per spinner are
    typed, the rows item 158 proved inert (the lit-mask getter words) are read-only with the
    reason, and the Write list names the shots, not raw words."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.webui import write_scan as WS

    stern = manufacturers_by_key["stern"]
    project = _stock_modes_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        stock = _st(w)["stock"]
        assert "godzilla_le 1.16" in stock["msg"]
        rows = {r["key"]: r for r in stock["rows"]}
        # the positions: 2 and 4 pickable, the seeds and the goal read-only with the reason
        assert rows["4.path.3"]["number"] == "Position 4" and rows["4.path.3"]["stock"] == "Top spinner, first bit"
        assert not rows["4.path.3"]["readonly"] and rows["4.path.3"]["raw"] == "2048"
        labels = {c["value"]: c["label"] for c in rows["4.path.3"]["choices"]}
        assert labels["0"].startswith("none") and labels["2048"] == "Top spinner, first bit"
        assert labels[str(0x400000)] == "Building" and str(1 << 36) not in labels
        assert str(0x200000) not in labels                       # Right ramp is position 5
        assert rows["4.path.0"]["readonly"] and "choices" not in rows["4.path.0"]
        assert "4.path.counted.lo" not in rows and "4.path.spot.2" not in rows
        # the lit-mask getter rows were never listed here (not awards or timers); the model
        # keeps the ones item 158 measured inert read-only (tests/test_stern_stock_modes.py)
        assert "4.initial_mask.lo" not in rows and "12.initial_mask.lo" not in rows
        # pick none for position 4
        w.call("modes.stock_select", "4.path.3")
        st = _st(w)["stock"]
        assert st["row_on"] and st["value"] == "2048" and st["choices"] == rows["4.path.3"]["choices"]
        assert "tanks then skip this position" in st["note"]
        note = w.call("modes.stock_set", "0")
        assert "position 4: Top spinner, first bit -> none staged" in note
        assert staged_changes.load(str(project))["stock_modes"]["values"] == {"4.path.3": 0}
        rows = {r["key"]: r for r in _st(w)["stock"]["rows"]}
        assert rows["4.path.3"]["value"].startswith("none") and rows["4.path.3"]["changed"]
        assert "1 change(s) staged" in _st(w)["stock"]["msg"]
        # a duplicate is refused with the reason
        assert "already position" in w.call("modes.stock_set", str(0x200000))
        # a spin count is typed
        w.call("modes.stock_select", "12.spins.left")
        st = _st(w)["stock"]
        assert st["row_on"] and st["choices"] is None and st["value"] == "15"
        assert "How many spins" in st["note"]
        assert "left spinner spins: 15 -> 5 staged" in w.call("modes.stock_set", "5")
        assert "at least 1" in w.call("modes.stock_set", "0")
        assert staged_changes.load(str(project))["stock_modes"]["values"] == {
            "4.path.3": 0, "12.spins.left": 5}
        # the Write list names the shot
        got = [r[0] for r in WS.stock_mode_rows(stern, str(project))]
        assert "Tank Attack Multiball position 4: Top spinner, first bit -> none" in got
        assert "Battle vs Ebirah left spinner spins: 15 -> 5" in got
        # Stock puts the position back; All to stock clears the rest
        w.call("modes.stock_select", "4.path.3")
        assert "back to the game's own Top spinner" in w.call("modes.stock_reset")
        assert w.call("modes.stock_all") == 1
        assert staged_changes.load(str(project))["stock_modes"]["values"] == {}


@pytest.mark.usefixtures("preview_modes_on")
def test_write_scan_lists_the_games_own_mode_changes(tmp_path, manufacturers_by_key):
    """Item 145: a staged stock-mode number is a pending Write row (the Write computes it
    from the sidecar, the MD5 scan can't see it), the operator setting too, and staging
    moves the Write fingerprint."""
    from pinball_decryptor.plugins.stern import stock_modes as SM
    from pinball_decryptor.webui import write_scan as WS

    stern = manufacturers_by_key["stern"]
    window = types.SimpleNamespace()
    project = _stock_modes_project(tmp_path)
    fp0 = WS.fingerprint(window, str(project), 0, True)
    build = SM.table_for_project(str(project))
    SM.stage(str(project), build, build.number("23.start.caward_add"), 555555)
    SM.stage(str(project), build, build.number("12.timer.seconds"), 30)
    assert WS.fingerprint(window, str(project), 0, True) != fp0
    rows = WS.pending_rows(window, stern, str(project), grow_on=True, direct=False)
    assert len(rows) >= 2
    got = [r[0] for r in rows if r[2] == WS.PENDING_STOCK_MODES]
    assert "Tesla Strike start award: 250,000 -> 555,555" in got
    assert "Battle vs Ebirah timer: 60 -> 30" in got


@pytest.mark.usefixtures("preview_modes_on")
def test_defaults_form_adopts_a_timer_the_modes_tab_staged(tmp_path):
    """The Defaults form's autostage REPLACES the staged settings from its own fields, so
    a timer staged on the Modes tab is put into the form's field (item 145) - else the next
    Defaults edit would drop it."""
    from pinball_decryptor.core import staged_changes
    from tests.test_webui_defaults import PLAN, _Hstd, _row

    project = _stock_modes_project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        dflt = w.window.service("defaults")
        _project(w, project)
        rows = [_row("AD_BATTLE_VS_EBIRAH_TIMER", "Ebirah timer", "Game", 60, 30, 70)]
        res = ("ok", object(), 3, "/game", rows, "C:/card.raw", _Hstd(), [], PLAN)
        w.run(lambda: dflt._apply_result(res))
        assert w.state("defaults")["values"]["AD_BATTLE_VS_EBIRAH_TIMER"] == 60
        w.run(svc.refresh_stock_modes)
        w.run(svc.stage_stock_value, "12.timer.seconds", 45)
        assert w.state("defaults")["values"]["AD_BATTLE_VS_EBIRAH_TIMER"] == 45
        assert staged_changes.load(str(project))["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 45}
        w.run(svc.stage_stock_value, "12.timer.seconds", 60)
        assert w.state("defaults")["values"]["AD_BATTLE_VS_EBIRAH_TIMER"] == 60
        assert not staged_changes.load(str(project)).get("settings")


@pytest.mark.usefixtures("preview_modes_on")
def test_revert_all_and_defaults_only_settings_with_the_games_own_modes(tmp_path, manufacturers_by_key):
    """Item 145 fix round 2. A setting staged only on the Defaults tab is not a Write row of
    the game's own modes (Defaults applies it after the next build, as before). Revert all
    changes drops every staged number but keeps the project managing the game's own modes,
    so the next Write can put its card back to stock."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import stock_modes as SM
    from pinball_decryptor.webui import write_scan as WS

    stern = manufacturers_by_key["stern"]
    project = _stock_modes_project(tmp_path)
    staged_changes.save(str(project), {"settings": {"AD_BATTLE_VS_EBIRAH_TIMER": 30}})
    assert WS.stock_mode_rows(stern, str(project)) == []

    build = SM.table_for_project(str(project))
    SM.stage(str(project), build, build.number("12.start.caward_add"), 777777)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        w.run(w.window.clear_replace_assignments, str(project))
    data = staged_changes.load(str(project))
    assert data == {"stock_modes": {"build": "godzilla_pro 1.15", "values": {},
                                    "touched": ["12.start.caward_add"]}}
    assert SM.manages(str(project)) and SM.pending_count(str(project)) == 0


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_starts_and_ends_on_an_event(tmp_path):
    """Item 147: "Starts on: its shot / an event" and "Ends on: the drain / the clock only /
    an event". The form shows events in words, the file keeps their names, and the runtime
    file an event start generates has no trigger line."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        slug = w.run(svc.new_mode, "EVENT RUSH")
        f = _st(w)["form"]
        assert f["starts_kind"] == "shot" and f["ends_kind"] == "drain"
        _f(w, "starts_kind", "event")
        _f(w, "start_event", MP.EVENT_LABELS["ball_start"])
        _f(w, "ends_kind", "event")
        _f(w, "end_event", MP.EVENT_LABELS["multiball_end"])
        _save(w)
        path = project / "modes" / slug / "mode.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["starts_on"] == "event ball_start" and data["ends_on"] == "event multiball_end"
        assert "Ready to build" in _status(w)
        cfg = MP.runtime_cfg(MP.load(str(path)), slug)
        assert "starts_on      event ball_start" in cfg
        assert not [line for line in cfg.splitlines() if line.startswith("trigger ")]

        _f(w, "ends_kind", "clock")
        _save(w)
        assert json.loads(path.read_text(encoding="utf-8"))["ends_on"] == "clock"
        # reopening the mode shows what was saved

        def reopen():
            svc._slug = None
            svc.refresh(select=slug)
        w.run(reopen)
        f = _st(w)["form"]
        assert f["starts_kind"] == "event"
        assert f["start_event"] == MP.EVENT_LABELS["ball_start"]
        assert f["ends_kind"] == "clock"
        _f(w, "start_event", "")
        _save(w)
        assert "Pick the event that starts" in _status(w)


# ---------------------------------------------------------------------- item 149: the Write scan
@pytest.mark.usefixtures("preview_modes_on")
def test_the_write_scan_lists_each_mode_and_what_it_adds(manufacturers_by_key, tmp_path, monkeypatch):
    """Item 149: a project's modes are a change Build applies, so the Write change scan
    lists one "Pending (Modes)" row per mode saying what it adds - its screen, its clip,
    its own end sound, its mode file - and none for a project without modes or a
    manufacturer without the modes capability."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.webui import write_scan as WS

    # a host that carries modes (a Mac's rows say they are left out: the test below pins that)
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    stern, spooky = manufacturers_by_key["stern"], manufacturers_by_key["spooky"]
    project = str(tmp_path / "project")
    for name, spec in MP.example_specs()[:2]:
        slug, spec = MP.new_mode(project, spec=spec)
        if name == "KAIJU RUSH":
            spec.end_sound = "end.wav"
            MP.save(project, slug, spec)
    rows = WS.mode_rows(stern, project, direct=False)
    assert len(rows) == 2
    assert [(r[1], r[2]) for r in rows] == [("mode", "Pending (Modes)")] * 2
    kaiju = next(r[0] for r in rows if r[0].startswith("KAIJU RUSH"))
    for needle in ("its own screen", "title-card clip", "its own end sound end.wav",
                   "mode file mode1.cfg"):
        assert needle in kaiju, needle
    # the other mode ends on the same (re-pointed) time-up call, and the row says whose sound
    atomic = next(r[0] for r in rows if r[0].startswith("ATOMIC BREATH"))
    assert "KAIJU RUSH's end sound when it ends" in atomic
    # nothing for a folder with no modes, or a manufacturer without the capability
    assert WS.mode_rows(stern, str(tmp_path / "empty"), direct=False) == []
    assert WS.mode_rows(spooky, project, direct=False) == []
    # a CODE mode (modes/<slug>/<slug>.c, no mode file) reaches the card too, and the scan says what
    os.makedirs(os.path.join(project, "modes", "blitz"))
    with open(os.path.join(project, "modes", "blitz", "blitz.c"), "w") as f:
        f.write("/* a mode */\n")
    rows = WS.mode_rows(stern, project, direct=False)
    assert len(rows) == 3
    assert rows[-1][0].startswith("BLITZ (code mode): its code (blitz.c)")


@pytest.mark.usefixtures("preview_modes_on")
def test_the_write_scan_says_a_direct_sd_write_leaves_the_modes_out(manufacturers_by_key, tmp_path):
    """Item 149: a direct-SD write cannot add files, so the engine leaves a project's modes out.
    With the Write tab set to write to the SD card, the scan's Modes rows say so instead of
    promising the screens, clips and mode files an image build would add."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.webui import write_scan as WS

    stern = manufacturers_by_key["stern"]
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    rows = [r[0] for r in WS.mode_rows(stern, project, direct=True)]
    assert len(rows) == 2
    assert all("left out of a Direct-SD write" in r for r in rows), rows
    assert not any("its own screen" in r or "mode file" in r for r in rows), rows
    # an image build lists what it adds, as before
    rows = WS.mode_rows(stern, project, direct=False)
    assert len(rows) == 2
    assert not any("Direct-SD" in r[0] for r in rows)


@pytest.mark.usefixtures("preview_modes_on")
def test_the_write_scan_says_a_mac_leaves_the_modes_out(manufacturers_by_key, tmp_path, monkeypatch):
    """Item 149: on a Mac the tools that put a mode's files on the card do not run, so the engine
    leaves every mode out; the scan's Modes rows say so instead of promising them."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.webui import write_scan as WS

    stern = manufacturers_by_key["stern"]
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: MW.MAC_REFUSAL)
    rows = [r[0] for r in WS.mode_rows(stern, project, direct=False)]
    assert len(rows) == 2
    assert all("left out of this Write: a Mac cannot put" in r for r in rows), rows
    assert not any("its own screen" in r or "mode file" in r for r in rows), rows
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    rows = WS.mode_rows(stern, project, direct=False)
    assert len(rows) == 2
    assert not any("left out" in r[0] for r in rows)


@pytest.mark.usefixtures("preview_modes_on")
def test_a_mode_edit_makes_the_write_tab_rescan(tmp_path, monkeypatch):
    """Item 149: the Write scan's fingerprint covers the project's modes, so adding a mode,
    editing its mode.json, giving it a sound, removing it or closing a modes gate rescans when
    the Write tab is shown again, instead of keeping stale Modes rows (or none, and a Build
    that warns "no modified files" while it writes the modes)."""
    import shutil
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.delenv("PAD_STERN_MODES", raising=False)
    monkeypatch.delenv("PAD_STERN_MODE_SOUND", raising=False)
    with web_app(tmp_path, mfr="stern") as w:
        ws = w.window.service("write")
        scans = []
        monkeypatch.setattr(ws, "_scan_write_preview", lambda: scans.append(1))
        monkeypatch.setattr(w.window, "current_tab_key", lambda: "Write")
        w.run(lambda: ws.write_assets_var.set(str(project)))
        w.drain()

        def shown_again():
            """what the tab does when shown: rescan only if the fingerprint moved;
            then record the fingerprint the way a finished scan does."""
            n = len(scans)
            w.run(ws._maybe_rescan_write_preview)
            ws._scan_fp = w.run(ws._fingerprint)
            return len(scans) > n

        ws._scan_fp = w.run(ws._fingerprint)
        assert not shown_again()                      # nothing changed: no rescan
        _name, spec = MP.example_specs()[0]
        slug, spec = MP.new_mode(str(project), spec=spec)
        assert shown_again(), "a mode added"
        assert not shown_again()
        spec.name = spec.name + " TWO"
        MP.save(str(project), slug, spec)
        assert shown_again(), "a mode.json edited"
        (project / "modes" / slug / "end.wav").write_bytes(b"RIFF")
        assert shown_again(), "a sound added to a mode"
        monkeypatch.setenv("PAD_STERN_MODE_SOUND", "0")
        assert shown_again(), "the own-sound gate closed"
        monkeypatch.setenv("PAD_STERN_MODES", "0")
        assert shown_again(), "the modes gate closed"
        shutil.rmtree(str(project / "modes" / slug))
        assert shown_again(), "a mode removed"
        assert not shown_again()


# ---------------------------------------------------------------------- code modes with assets
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_offers_the_five_intricate_modes_as_code_examples(tmp_path):
    """Examples lists the form modes, then the SDK's five intricate modes as CODE modes (a Godzilla
    title only: their shots are Godzilla's)."""
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        labels = [e.get("label") or e["name"] for e in _st(w)["examples"]]
        assert labels[0] == "KAIJU RUSH"
        assert labels[-5:] == ["KING GHIDORAH (code mode)", "OXYGEN DESTROYER (code mode)",
                               "MASER BARRAGE (code mode)", "FINAL WARS (code mode)",
                               "ANGUIRUS (code mode)"]
        assert "No code modes in this project" in _st(w)["code_words"]


@pytest.mark.usefixtures("preview_modes_on")
def test_a_code_example_without_its_films_is_added_and_the_tab_says_which(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP

    monkeypatch.delenv("PAD_FILMS_DIR", raising=False)
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        t = w.run(svc.add_code_example, "ANGUIRUS", [str(tmp_path)])
        assert t is not None
        t.join(60)
        assert not t.is_alive()
        w.drain()
        folder = MP.mode_folder(str(project), "anguirus_assist")
        assert sorted(os.listdir(folder)) == ["anguirus_assist.c", "assets.json", "intricate_kit.h"]
        status = _line(w)
        assert "added the example ANGUIRUS as modes/anguirus_assist with its code" in status
        assert "Godzilla Raids Again (1955)" in status and "Cut film assets" in status
        assert _wait(w, lambda: "ANGUIRUS (its film assets are not cut yet)" in _st(w)["code_words"])
        # not a form mode: a code mode has no mode.json
        assert [r for r in _st(w)["rows"] if r["kind"] == "form"] == []
        assert w.run(svc.add_code_example, "ANGUIRUS") is None
        assert "already in this project" in _line(w)


@pytest.mark.usefixtures("preview_modes_on")
def test_a_code_example_is_cut_from_the_films_folder_the_person_picks(tmp_path, monkeypatch):
    """The recipe's clip, picture, music loop and calls are cut with the film cutter from the folder
    asked for (a synthetic film under a collection file name: nothing of a film is in the repo)."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    from tests.test_stern_code_modes import _ffmpeg, _synthetic_film

    ff = _ffmpeg()
    monkeypatch.delenv("PAD_FILMS_DIR", raising=False)
    films = str(tmp_path / "films")
    _synthetic_film(films, CM.FILMS["fw04"], ff)
    ex = {"name": "TEST WARS", "slug": "test_wars", "source": "final_wars.c", "headers": ["intricate_kit.h"],
          "seconds": 40,
          "recipe": {"clip": {"film": "fw04", "from": 1.0, "length": 3.0, "crop": "fill"},
                     "art": {"film": "fw04", "at": 2.0, "crop": "fill"},
                     "music": {"film": "fw04", "from": 2.0, "length": 10.0},
                     "calls": {"won": {"film": "fw04", "from": 3.0, "length": 1.5}}}}
    monkeypatch.setattr(CM, "EXAMPLES", [ex])
    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        svc._ffmpeg_fn = lambda: ff
        w.answers.append(films)                              # "Where are the films?"
        assert w.call("modes.code_example", "TEST WARS") is True
        assert "Godzilla: Final Wars (2004)" in json.dumps(w.asked[-1])
        _wait_threads("modes-code-example", 60)
        assert _wait(w, lambda: "TEST WARS (clip, picture, music, 1 call(s))" in _st(w)["code_words"],
                     10)
        assert "its own clip, picture, music and calls cut from the films" in _line(w)
        spec = CM.load(str(project), "test_wars")
        assert spec.film["dir"] == films and spec.calls == {"won": "won.wav"}


@pytest.mark.usefixtures("preview_modes_on")
def test_try_it_carries_code_modes_with_assets_through_writes_set(tmp_path, monkeypatch):
    """A project of code modes WITH assets is not the code-only fast path: Try it builds Write's own
    set (their screens, clips and sounds), whose stage already holds the object Write compiled, so
    the tab installs it without compiling again."""
    from pinball_decryptor.plugins.stern import code_modes as CM
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_runtime as MR
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from pinball_decryptor.plugins.stern import mode_write as MW
    from tests.test_stern_code_modes import _code_project

    project = _code_project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _no_wsl(monkeypatch)
        svc = _svc(w)
        ran, handed, calls = [], [], []
        _fake_rig(svc, ran)
        _tryit_ready(svc, tmp_path, handed)
        monkeypatch.setattr(MT, "card_title", lambda card: ("godzilla_pro", "1.15.0", 2))
        monkeypatch.setattr(CM, "profile_for", lambda project, code=(): MP.GODZILLA_PRO_1_15)

        def build(project_, card, base, log=None, **kw):
            calls.append(project_)
            s = os.path.join(base, MW.TRYIT_SET)
            stage = s + "-modes"
            os.makedirs(os.path.join(s, "godzilla_pro"), exist_ok=True)
            with open(os.path.join(s, "godzilla_pro", "game"), "wb") as f:
                f.write(b"set file")
            os.makedirs(stage, exist_ok=True)
            for name, data in (("pad_mode.so", b"\x7fELF compiled by Write"),
                               ("game.port", b"game godzilla_pro\n"),
                               ("ghidorah_heads.assets", b"name KING GHIDORAH\n")):
                with open(os.path.join(stage, name), "wb") as f:
                    f.write(data)
            return MW.TryItSet(set_dir=s, stage_dir=stage, game_dir="godzilla_pro", version="1.15",
                               files=["godzilla_pro/game"], port=os.path.join(stage, "game.port"),
                               codes=["ghidorah_heads"], code_object=True)
        monkeypatch.setattr(MW, "build_tryit_set", build)
        assert w.run(svc.on_try) is True
        card = tmp_path / "card.raw"
        card.write_bytes(b"\0" * 32)
        env = handed[0](str(card))
        w.drain()
        assert calls == [project]                               # Write's set, not the fast path
        assert env == svc.tryit_env()
        assert [c[1:3] for c in ran] == [["modes/tryit.sh", "check"],
                                         ["modes/tryit.sh", "install"]]     # no second compile
        status = _line(w)
        assert "Code mode(s) built in: ghidorah_heads" in status and "carries them the same way" in status
        assert status.startswith("Ready. Start a game") and "0 mode(s)" not in status   # no form mode
        assert MR.sdk_dir()                                      # the SDK is where the tab looks


# ---------------------------------------------------------------------- words, small truths, the help
@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_counts_the_modes_and_at_the_cap_greys_only_the_form_examples(tmp_path):
    """The line under New says how many of the card's modes the project has. At the cap New
    is off and the line says what to do; Examples stays live with only its FORM entries
    greyed, since a mode written in C takes none of the card's slots."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = _modes_card_project(tmp_path, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw", "1.16.0")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        _project(w, project)
        assert _st(w)["cap_text"] == "0 of 8 modes"
        slugs = [MP.new_mode(str(project), "MODE %d" % i,
                             MP.ModeSpec(name="MODE %d" % i, screen=False, clip="none"))[0]
                 for i in range(MP.MAX_MODES)]
        w.run(svc.refresh)
        st = _st(w)
        assert st["cap_text"] == (
            "8 of 8 modes: delete one to add another. Modes written in C are not counted.")
        assert st["new_ok"] is False
        assert st["ex_ok"] is True
        states = {e.get("label") or e["name"]: e["disabled"] for e in st["examples"]}
        assert states["KAIJU RUSH"] is True
        code = {k: v for k, v in states.items() if k.endswith(" (code mode)")}
        assert len(code) == 5 and set(code.values()) == {False}
        w.run(svc.delete_mode, slugs[0])
        st = _st(w)
        assert st["cap_text"] == "7 of 8 modes"
        assert st["new_ok"] is True
        assert not any(e["disabled"] for e in st["examples"])
        _project(w, "")
        assert _st(w)["cap_text"] == ""


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_tab_sound_label_says_whose_end_sound_the_card_carries(tmp_path):
    """A card carries ONE end sound of a mode's own (Write takes the first mode in slot order
    that has one, mode_write.choose_end_sound). The Sound label says so on each mode instead
    of promising every mode's is added to the card."""
    from pinball_decryptor.plugins.stern import mode_project as MP

    project = tmp_path / "proj"
    project.mkdir()
    for name in ("ALPHA", "BRAVO"):
        slug, _s = MP.new_mode(str(project), name, MP.ModeSpec(name=name, screen=False, clip="none",
                                                               end_sound="end.wav"))
        (project / "modes" / slug / "end.wav").write_bytes(b"RIFF")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, project)
        _select(w, "alpha")
        assert _st(w)["labels"]["sound"] == "Sound: end.wav (put on the card by Write)"
        _select(w, "bravo")
        assert _st(w)["labels"]["sound"] == (
            "Sound: end.wav (not on the card: a card carries one end sound, and ALPHA's is it)")
        _f(w, "end_mode", "game")
        _save(w)
        assert _st(w)["labels"]["sound"] == ""
        assert MP.load(str(project / "modes" / "bravo" / "mode.json")).end_sound == ""


def test_modes_end_note_names_the_code_modes_it_could_not_reach():
    """End mode's note keeps its wording for the modes it asked to end, and names a code mode
    whose folder is not a trigger name (letters, digits and _), which it could not ask."""
    from pinball_decryptor.webui.tabs.modes import ModesTab as P

    assert P._end_note(True, []) == "asked the game to end the running mode."
    assert P._end_note(True, ["blitz"]) == (
        "asked the game to end the running mode, and the code mode(s) blitz.")
    assert P._end_note(False, ["blitz"]) == "asked the game to end the code mode(s) blitz."
    assert P._end_note(False, ["blitz"], ["Bad-Name"]) == (
        "asked the game to end the code mode(s) blitz; not ended: Bad-Name (its folder name is "
        "not a trigger name; use letters, digits and _).")
    assert P._end_note(True, [], ["a-b", "c d"]) == (
        "asked the game to end the running mode; not ended: a-b, c d (their folder names are "
        "not trigger names; use letters, digits and _).")
    codes = [("blitz", "/p/blitz.c"), ("Bad-Name", "/p/b.c")]
    assert P._tryit_code_triggers(codes) == ["blitz"]
    assert P._tryit_code_unreached(codes) == ["Bad-Name"]


def test_modes_tab_words_name_the_title_card_and_no_light_grammar():
    """The words a person reads on the form: the Clip section's entry is the title card's
    text, and the Lights tip names the game's own light language without the grammar's own
    name (a word that meant nothing to a tester)."""
    from pinball_decryptor.webui.tabs.modes import ModesTab

    js = _modes_js()
    assert "Title card text" in js and "Card title" not in js
    tips = [getattr(ModesTab, n) for n in dir(ModesTab) if n.endswith("_TIP")
            and isinstance(getattr(ModesTab, n), str)]
    lights = [t for t in tips if "light language" in t]
    assert lights and all("blele" not in t for t in lights)
    assert "blele" not in js


@pytest.mark.usefixtures("preview_modes_on")
def test_modes_help_names_every_port_and_the_tab_as_it_is(tmp_path):
    """The "?" text for the Modes tab (in PREVIEW_HELP, so behind the switch): "Which games"
    is read off the ports when the window renders and names every one, the drafted ones as
    such; the other sections describe the tab as it is on this branch."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.webui import help_content as HD

    sections = HD.sections_for("Modes")
    assert [t for t, _b in sections] == [
        "What it's for", "Which games", "Making a mode", "Several modes", "Try it",
        "Modes written in C", "The game's own modes", "From a film", "A preview feature"]
    bodies = dict(sections)
    assert all(isinstance(b, str) and b for b in bodies.values())
    which = bodies["Which games"]
    ports = list(MP.profiles().values())
    assert ports and all(p.label in which for p in ports)
    drafted = [p.label for p in ports if not p.proven]
    assert ("drafted and never run" in which) == bool(drafted)
    assert "for now" not in which and "Making a port for another game or version" in which
    assert callable(dict(HD.PREVIEW_HELP["modes"]["Modes"])["Which games"])   # read at render
    assert "three minutes" in bodies["Try it"] and "Cancel" in bodies["Try it"]
    assert "used as it is" in bodies["Try it"] and "Start mode now" in bodies["Try it"]
    code = bodies["Modes written in C"]
    assert "New code mode" in code and "assets.json" in code and "MODE_SDK.md" in code
    stock = bodies["The game's own modes"]
    assert "All to stock" in stock and "Defaults tab" in stock and "Text tab" in stock
    assert "never the film" in bodies["From a film"]
    assert "8 modes" in bodies["Several modes"] and "not counted" in bodies["Several modes"]
    for title, body in sections:
        assert "\u2014" not in body, title
    # and it is what the window shows
    with web_app(tmp_path, mfr="stern") as w:
        shown = json.dumps(w.call("shellx.tips", "Modes"))
    assert "Modes written in C" in shown and "Ports so far" in shown


def test_modes_help_stays_behind_the_switch_and_its_which_games_never_raises(monkeypatch):
    from pinball_decryptor.core import preview
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.webui import help_content as HD

    assert not preview.enabled("modes")
    assert HD.sections_for("Modes") == []
    assert HD._and_list(["a"]) == "a" and HD._and_list(["a", "b", "c"]) == "a, b and c"
    monkeypatch.setattr(MP, "profiles", lambda ports_dir=None: (_ for _ in ()).throw(OSError("x")))
    assert "No port could be read" in HD._modes_which_games()
    # a section whose body fails to render is left out, never a traceback in the window
    monkeypatch.setitem(HD.HELP_CONTENT, "Modes", [("Broken", lambda: 1 / 0), ("Kept", "words")])
    assert HD.sections_for("Modes") == [("Kept", "words")]
