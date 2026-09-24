"""PAD-204: the Pause key freezes the emulated game, and a long pause survives.

DragonRR: "It would be useful to be able to hit the pause key (or another key)
to completely freeze the game state ... I want to look at an animation."

padglhost owns the game window, so it owns the key: Pause (or F9) SIGSTOPs
every `game` process and the next press SIGCONTs them. The part that needs
guarding is the game's own watchdog - its dispatch loop waits with a 10 s
absolute pthread_cond_timedwait and exits 5 on ETIMEDOUT (PAD-200). Measured
on the rig, 2026-09-24, godzilla_pro attract: a bare 15 s SIGSTOP ended the
game on resume with GAME EXIT DISPATCH TIMEOUT; with the frozen time written to
padsw's paused_ms before the SIGCONT and hwshim moving the deadline out by it,
a pause of over a minute resumed and kept running.

These are source-level checks on the three copies of that contract (padsw.h,
padsw.py, hwshim's mirror) and on the order of padglhost's writes - the order
is the whole fix, and it is invisible to anything but a 10 s freeze on a rig.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf8", newline="") as f:
        return f.read()


def _func(src, name):
    """The body of a C function defined at file scope, by name."""
    m = re.search(r"\n[^\n]*\b%s\([^)]*\)\n\{(.*?)\n\}" % re.escape(name), src, re.S)
    assert m, name
    return m.group(1)


def test_the_pause_fields_close_the_block():
    import padsw
    assert padsw.OFF_PAUSED == 1084
    assert padsw.OFF_PAUSED_MS == 1088
    assert padsw.SIZE == 1092


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_padsw_h_puts_the_pause_fields_where_python_reads_them(tmp_path):
    import padsw
    src = tmp_path / "layout.c"
    src.write_text('#include <stdio.h>\n#include <stddef.h>\n#include "padsw.h"\n'
                   'int main(void){printf("%zu %zu\\n", '
                   'offsetof(struct padsw_shm, paused), '
                   'offsetof(struct padsw_shm, paused_ms));return 0;}\n')
    exe = tmp_path / "layout"
    subprocess.run(["gcc", "-std=gnu17", "-I", RIG, "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    assert [int(x) for x in out.split()] == [padsw.OFF_PAUSED, padsw.OFF_PAUSED_MS]


def test_the_shim_moves_a_deadline_that_expired_across_a_pause():
    body = _func(_text("hwshim.c"), "shim_cond_timedwait")
    # the pause count is read BEFORE the wait, compared after an ETIMEDOUT
    assert body.index("pause_total_ms()") < body.index("r = real(c, m, t);")
    assert "r != 110" in body                      # only a timeout is retried
    assert "while (r == 110 && (p1 = pause_total_ms()) != p0)" in body
    assert "r = real(c, m, &dl);" in body          # ...against the moved deadline
    # a real timeout with no pause in it is still returned as one
    assert body.rstrip().endswith("return r;")


def test_the_pause_key_toggles_and_presses_nothing():
    c = _text("padglhost.c")
    i = c.index("PAD-204: Pause / F9 freeze and resume")
    hook = c[i:i + 300]
    assert "0xff13" in hook and "0xffc6" in hook   # XK_Pause, XK_F9
    assert "if (press) pause_toggle();" in hook
    assert "break;" in hook                        # never reaches cab_key/binds
    assert i < c.index("cab_key(sym, press);")


def test_resume_counts_the_frozen_time_before_the_game_runs():
    body = _func(_text("padglhost.c"), "pause_release")
    assert body.index("swshm->paused_ms +=") < body.index("pause_signal(SIGCONT)")
    assert body.index("__sync_synchronize()") < body.index("pause_signal(SIGCONT)")


def test_pause_needs_the_switch_block_and_a_game():
    body = _func(_text("padglhost.c"), "pause_toggle")
    # no block = nothing to tell the shim, so no freeze the watchdog would kill
    assert body.index("if (!swshm)") < body.index("pause_signal(SIGSTOP)")
    assert "no running game to pause" in body


def test_a_stopping_renderer_never_leaves_the_game_frozen():
    c = _text("padglhost.c")
    assert c.index("pause_release();") < c.index('"[padglhost] stopped after %ld frames')
