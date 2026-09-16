"""A scene the game could not read is named in the exit report (PAD-159).

THE REPORT, 2026-09-16, a field report on Godzilla LE: "won't start emulator.. well
it does, I see the Stern logo and then it stops", and the pane ended on::

    terminate called after throwing an instance of 'cereal::Exception'
      what():  Error while trying to deserialize a polymorphic pointer. Could
               not find type id 993416120

That is a ``scene.radium`` the game could not deserialize, and nothing in the
log said WHICH of the title's 194 scenes it was, or whether it was one PAD had
written into the override set bound over the card - so the ticket could not be
settled from the log it came with.

NOW the shim writes ``[scenefail] <scene> at byte <n>: <what>`` for every
cereal exception (hwshim.c, the thread's own last-read scene), and
``pad_scenefail_report`` (padpath.sh) is what watch.sh's exit report says about
it.  Proven in the emulator on godzilla_pro 1.15 with the reported type id
planted over a polymorphic id in a demand-loaded scene 41930 bytes in: the pane
named that scene "at byte 41934" (the four bytes of the id read) and called it
one of the user's edits.

The function is driven for real here; the two halves that need a guest (the
shim reporting, watch.sh calling) are checked as text.
"""
import os
import re
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

SCENE = ("./assets/lcd/demand_loaded/394c4a037fb26e12f536c42b2677bfed831f5c98/"
         "scene.radium")
WHAT = ("Error while trying to deserialize a polymorphic pointer. Could not "
        "find type id 993416120")
#: A game log as the shim writes it: other throws first, the scene failure,
#: and the game's own lines after.
GAME_LOG = (
    "[throw] type=27do_stack_unwind_exception_t msg=\"\"\n"
    "[scenefail] ./assets/lcd/auto_loaded/a24cebb4/scene.radium at byte 12: "
    "an earlier one\n"
    "[scenefail] %s at byte 41934: %s\n"
    "terminate called after throwing an instance of 'cereal::Exception'\n"
    "  what():  %s\n"
    "qemu: uncaught target signal 6 (Aborted) - core dumped\n"
    % (SCENE, WHAT, WHAT))

#: EVERYTHING RELATIVE, AND THE SCRIPT ON DISK: on Windows `bash` is as likely
#: to be WSL's launcher as Git's, and that one sees a C:\\... path as a name
#: with no directories in it (test_spike2_renderer_fallback.py).
_DRIVER = """#!/bin/bash
RIG=$(pwd); export RIG
PAD_HOME=$RIG; export PAD_HOME
. "$RIG/padpath.sh"
pad_scenefail_report "$@"
echo "RC=$?"
"""


def _drive(tmp_path, log, *args, override_files=()):
    rig = tmp_path / ("rig%d" % len(list(tmp_path.glob("rig*"))))
    rig.mkdir(parents=True)
    shutil.copy(os.path.join(RIG, "padpath.sh"), str(rig / "padpath.sh"))
    for name, text in (("game.log", log), ("driver.sh", _DRIVER)):
        with open(str(rig / name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    for rel in override_files:
        p = rig / "ovr" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    os.chmod(str(rig / "driver.sh"), 0o755)
    out = subprocess.run([BASH, "driver.sh"] + list(args), cwd=str(rig),
                         capture_output=True, text=True)
    return out.stdout.splitlines()


@pytest.mark.skipif(not BASH, reason="no bash")
def test_an_edited_scene_is_named_with_its_byte_and_owned(tmp_path):
    """The reported message, the scene and the byte, and that the file came
    from the user's own override set - with what to try."""
    lines = _drive(tmp_path, GAME_LOG, "game.log", "ovr", "godzilla_le",
                   override_files=["godzilla_le/" + SCENE[2:]])
    assert lines[0] == "[watch] the game could not read one of its scene files:"
    assert lines[1] == "[watch]   %s at byte 41934: %s" % (SCENE, WHAT)
    said = "\n".join(lines)
    assert "one of YOUR EDITS" in said
    assert "\"Apply my replaced assets on top\"" in said and "unticked" in said
    assert "card image's own" not in said
    assert lines[-1] == "RC=0"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_scene_the_set_does_not_hold_is_the_cards_own(tmp_path):
    for args in (("game.log", "ovr", "godzilla_le"),   # a set, not this file
                 ("game.log", "", "godzilla_le")):     # no set at all
        lines = _drive(tmp_path, GAME_LOG, *args,
                       override_files=["godzilla_le/game"])
        said = "\n".join(lines)
        assert "at byte 41934" in said
        assert "card image's own" in said and "YOUR EDITS" not in said


@pytest.mark.skipif(not BASH, reason="no bash")
def test_an_ordinary_exit_says_nothing_new(tmp_path):
    log = "ExchangeData: read failed (received 0, expected length=13)\n"
    assert _drive(tmp_path, log, "game.log", "ovr", "godzilla_le") == ["RC=0"]
    assert _drive(tmp_path, log, "no-such.log", "", "") == ["RC=0"]


def _src(name):
    with open(os.path.join(RIG, name), encoding="utf8", errors="replace") as f:
        return f.read()


def test_the_shim_reports_every_cereal_throw_outside_the_throw_budget():
    """The game throws other things first (do_stack_unwind_exception_t), and
    the [throw] log stops after six: a scene failure must not be the seventh
    that goes unsaid."""
    shim = _src("hwshim.c")
    body = shim[shim.index("void shim_cxa_throw(void *obj, void *tinfo, "
                           "void *dest)\n{"):]
    body = body[:body.index("\n}\n")]
    assert body.index("scenefail_report(") < body.index("if (budget-- > 0)")
    assert 'strstr(name, "cereal")' in body
    report = shim[shim.index("static void scenefail_report("):]
    report = report[:report.index("\n}\n")]
    assert "[scenefail] %s at byte %lu: %s" in report
    # THE THREAD'S OWN scene: cereal throws on the thread reading the stream.
    assert "syscall(224)" in report and "e->tid == me" in report
    xsgetn = shim[shim.index("int shim_fb_xsgetn(void *self, char *s, int n)\n{"):]
    xsgetn = xsgetn[:xsgetn.index("\n}\n")]
    assert "e->tid = syscall(224)" in xsgetn and "e->seq = ++sb_seq" in xsgetn


def test_the_exit_report_asks_for_it_from_the_right_log():
    watch = _src("watch.sh")
    exit_at = watch.index('echo "[watch] the game exited. Last lines of its log:"')
    report = watch[exit_at:watch.index("break", exit_at)]
    assert re.search(r'pad_scenefail_report "\$ROOT/dump/game\.out" '
                     r'"\$\{PAD_OVERRIDE_DIR:-\}" "\$GAME"', report)
    assert re.search(r'pad_scenefail_report "\$LOG" '
                     r'"\$\{PAD_OVERRIDE_DIR:-\}" "\$GAME"', report)
    assert "PAD_PIVOT" in report
