"""PAD-413: a mode's ENDING gives way when another of our modes begins.

David's Premium, 2026-10-06 (the PAD-392 card): "on kiryu it was overlapping text at one point". BIOLLANTE began
4.8 s into KIRYU's 10 s ending; the runtime gave KIRYU's display hold up at once (``pm_end_holding``), but nothing
told the ending's words. Now ``pm_begun()`` counts our modes' starts, and an ending still on the glass when it
moves is dropped at once:

- the runtime stops a full-screen clip another mode played (its ending clip) in ``pm_begin``;
- a mode file's own screen (its TOTAL) is hidden, an end clip still waiting never plays, and one still playing
  stops when the mode that began is another mode file's (mode_file.c, compiled for the HOST as the roster and
  aside tests compile it).

The examples' kit (a HUD's total, a note) and a blocks mode's screen are in test_spike2_intricate_modes.py and
test_stern_block_modes.py. Skips without an ELF C compiler.
"""
import os
import re
import subprocess

import pytest

from tests.test_spike2_mode_aside import SCREEN_STUBS, _build
from tests.test_spike2_mode_roster import _host_run, _lift
from tests.test_spike2_mode_display import RUNTIME

# the aside harness (a screen the mode finds, its shows printed), with pm_begun counting every start - a mode
# file's (pm_begin) and one in C (`c_mode`: it holds pm_begin from then on, `c_end`: it ended) - and the
# full-screen clip printed and kept playing until it is stopped
BEGUN_STUBS = SCREEN_STUBS + [
    ("int pm_clip(const char *n) { return 0; }",
     "static int clip_on;\n"
     "int pm_clip(const char *n) { printf(\"CLIP %s at %lu\\n\", n, now_ms); clip_on = 1; return 1; }\n"
     "int pm_clip_playing(void) { return clip_on; }\n"
     "void pm_clip_stop(void) { if (clip_on) printf(\"CLIP STOPPED at %lu\\n\", now_ms); clip_on = 0; }"),
    ("int pm_begin(void) { if (running_mode || c_mode) return 0; running_mode = 1; return 1; }",
     "static unsigned begun;\n"
     "int pm_begin(void) { if (running_mode || c_mode) return 0; running_mode = 1; begun++; return 1; }\n"
     "unsigned pm_begun(void) { return begun; }"),
    ("            c_mode = 1;\n",
     "            c_mode = 1;\n"
     "            begun++;\n"
     "            printf(\"C MODE BEGAN at %lu\\n\", now_ms);\n"
     "        } else if (!strcmp(argv[k], \"c_end\")) {\n"
     "            c_mode = 0;\n"),
]


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    return _build(tmp_path_factory, BEGUN_STUBS, "ending")


def _run(harness, tmp_path, cfg, *args, mode1=None):
    (tmp_path / "mode.cfg").write_text(cfg)
    if mode1 is not None:
        (tmp_path / "mode1.cfg").write_text(mode1)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


SCREEN = "screen_node PadMode_{s}_Screen\nscreen_text PadMode_{s}_Screen.PadMode_{s}_Screen_Words\n"
RUSH = ("name RUSH\ntrigger 0x08000000 1\nseconds 2\nshots 0x00300000\naward 1000000\nrestore_after 10\n"
        + SCREEN.format(s="rush"))
BLITZ = ("name BLITZ\ntrigger 0x04000000 1\nseconds 20\nshots 0x00300000\naward 1000000\n"
         + SCREEN.format(s="blitz"))


def _at(out, text):
    m = re.search(r"%s at (\d+)" % re.escape(text), out)
    return int(m.group(1)) if m else None


def _hidden_after(out, t):
    """ms of the first SHOW 0 at or after `t`"""
    for v, ms in re.findall(r"^SHOW (\d) at (\d+)$", out, re.M):
        if v == "0" and int(ms) >= t:
            return int(ms)
    return None


def test_a_mode_files_total_stays_its_time_with_nothing_else_beginning(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH, "shot", "0x08000000", "tick", "150", "tick", "700")
    assert "RUSH END" in out and "its total gives way" not in out
    assert "own screen hidden" in out                         # its 10 s ran out by itself


def test_a_mode_in_c_beginning_hides_a_mode_files_total_at_once(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH, "shot", "0x08000000", "tick", "150", "c_mode", "tick", "2")
    assert "RUSH END" in out
    began = _at(out, "C MODE BEGAN")
    assert "RUSH: its total gives way - another mode began" in out
    hid = _hidden_after(out, began)
    assert hid is not None and hid - began <= 17               # the next tick, not 10 s later
    assert "own screen hidden" not in out


def test_another_mode_file_beginning_hides_the_last_ones_total_and_stops_its_end_clip(harness, tmp_path):
    rush = RUSH + "clip_end PadMode_rush_Won\n"
    out = _run(harness, tmp_path, rush, "shot", "0x08000000", "tick", "150", "shot", "0x04000000", "tick", "2",
               mode1=BLITZ)
    assert "CLIP PadMode_rush_Won" in out and "BLITZ START" in out
    assert "RUSH: its total gives way - another mode began" in out
    assert "the last mode's ending clip stopped - another mode began" in out
    lines = out.splitlines()
    stop = next(i for i, ln in enumerate(lines) if ln.startswith("CLIP STOPPED"))
    start = next(i for i, ln in enumerate(lines) if "BLITZ START" in ln)
    assert stop < start                                       # before the new mode's screen and clip


def test_a_mode_in_c_beginning_drops_an_end_clip_still_waiting_and_leaves_the_playing_one_to_the_runtime(
        harness, tmp_path):
    # an end shot's clip waits a moment after the shot (item 141); a mode in C beginning meanwhile drops it
    rush = RUSH.replace("seconds 2\n", "seconds 20\n") + "clip_end PadMode_rush_Won\nend_shot 0x00400000\n"
    out = _run(harness, tmp_path, rush, "shot", "0x08000000", "tick", "5", "shot", "0x00400000", "tick", "1",
               "c_mode", "tick", "60")
    assert "RUSH END (end shot)" in out
    assert 'clip "PadMode_rush_Won" (mode end) dropped before it played: another mode began' in out
    assert "CLIP PadMode_rush_Won" not in out
    assert "CLIP STOPPED" not in out                          # a clip of the C mode's own is never ours to stop


# ---- the runtime: pm_begin stops the full-screen clip another mode played ----------------------------------------
def test_the_runtime_stops_another_modes_full_screen_clip_when_a_mode_begins(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    code = r"""
#include <stdio.h>
struct pm_mode { const char *name; };
static const struct pm_mode *current, *running;
static char running_as[40];
static unsigned begun;
static struct { int on, seen; unsigned long started, last; } clip;
static const struct pm_mode *clip_owner;
static const char *mode_name(const struct pm_mode *m, const char *none) { return m && m->name ? m->name : none; }
static void say(const char *fmt, const char *a) { printf(fmt, a); putchar('\n'); }
static void pm_log(const char *fmt, const char *a) { say(fmt, a); }
static void disp_linger_other_began(void) {}
void pm_clip_stop(void) { printf("STOP\n"); clip.on = 0; }
""" + _lift(src, "static void clip_other_began(void)\n{") + "\n" + _lift(src, "int pm_begin(void)\n{") + "\n" + \
        _lift(src, "unsigned pm_begun(void)") + r"""
int main(void)
{
    static const struct pm_mode kiryu = { "KIRYU" }, bio = { "BIOLLANTE" };
    current = &kiryu; pm_begin(); clip.on = 1; clip_owner = &kiryu;
    running = 0;                                       /* KIRYU ended, its ending clip still plays */
    printf("begun %u\n", pm_begun());
    current = &bio; pm_begin();
    printf("begun %u on %d\n", pm_begun(), clip.on);
    clip.on = 1; clip_owner = &bio;                    /* BIOLLANTE's own clip, then it begins again */
    pm_begin();
    printf("begun %u on %d\n", pm_begun(), clip.on);
    return 0;
}
"""
    out = _host_run(tmp_path, code, flags=("-Wno-format-security", "-Wno-unused-function"))
    lines = out.strip().splitlines()
    assert lines[0] == "begun 1"
    assert lines[1] == "clip: the full-screen clip KIRYU played stopped - another mode began"
    assert lines[2] == "STOP"
    assert lines[3] == "begun 2 on 0"
    assert lines[4] == "begun 2 on 1"                  # its own clip, and already running: no new start
