"""PAD-891: the game window lets go of its keys when it loses the focus.

Mike St P, Deadpool in Visual Pinball: "when game launches, the stern volume
starts to tick up without any inputs". X hands a KeyRelease to whichever
window has the focus when the key comes UP. A Visual Pinball run's game
window takes the foreground as it opens and the controller hands it straight
back to the table, so a key that went down in the game window came up in
Visual Pinball, and padglhost held its switch for the rest of the run. Held
Service Plus ('=') is the game's own auto-repeating volume up.

Reproduced on a hidden Deadpool Pro run through the VPX bridge: '=' down in
the game window, the focus moved off it, the release delivered elsewhere -
`[sw] +26k` with no `-26k`, and VOLUME 62, 63 on the screen. With the fix the
same steps log `-26k` at the focus change and the volume moves one step.

The event loop itself is X11 and is checked in the source; keys_let_go() is
the real function, compiled and driven (Linux with gcc, like the cabinet keys'
harness).
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


def _src():
    with open(os.path.join(RIG, "padglhost.c"), encoding="utf8", newline="") as f:
        return f.read()


def test_every_window_that_takes_keys_hears_about_losing_the_focus():
    """The game window, the legend and the second display all select
    KeyPress|KeyRelease, so all three must select FocusChange (1<<21) too:
    whichever had the key is the one the release went missing from."""
    c = _src()
    calls = re.findall(r"XSelectInput\(xdpy,\s*(\w+),([^;]*)\);", c)
    keyed = [(w, m) for w, m in calls
             if {"1L", "2L"} <= {t.strip() for t in m.split("|")}]
    assert {w for w, _ in keyed} == {"xwin", "legend_win", "xwin2"}, calls
    for w, m in keyed:
        assert "(1L << 21)" in m, (w, m)


def test_focus_out_lets_go_of_the_keys():
    c = _src()
    loop = c[c.index("while (XPending(xdpy) > 0) {"):]
    case = loop[loop.index("case 10:"):loop.index("case 2:")]
    assert "keys_let_go(" in case
    assert "!= 2" in case          # NotifyInferior: the focus stayed with us


# --- keys_let_go(), compiled and driven ---------------------------------------

_HARNESS = r'''
#define main padglhost_main
#include "padglhost.c"
#undef main
#include <assert.h>
#include <stdio.h>

static struct padsw_shm blk;

static void press(unsigned long sym, int down)
{
    int b = bind_for(sym);
    cab_key(sym, down);
    assert(b >= 0);
    if (binds[b].toggle) { if (down) key_latch[b] = !key_latch[b]; }
    else key_down[b] = (unsigned char)down;
    sw_publish();
}

int main(void)
{
    unsigned gen;
    int plus, door;
    binds_init();
    swshm = &blk;
    plus = binds[bind_for(0x3d)].ids[0];
    door = binds[bind_for(0x63)].ids[0];
    press(0x3d, 1);                                   /* '=' down: Service Plus */
    assert(swshm->held[plus] == 1);
    assert(swshm->cab[PADSW_CAB_PLUS] == 1);
    press(0x63, 1);                                   /* C: the door latch      */
    assert(swshm->held[door] == 1);
    gen = swshm->gen;
    keys_let_go("test");                              /* the focus went away    */
    assert(swshm->held[plus] == 0);                   /* the held key is up     */
    assert(swshm->cab[PADSW_CAB_PLUS] == 0);          /* and the menu's copy    */
    assert(swshm->gen != gen);                        /* published              */
    assert(swshm->held[door] == 1);                   /* a latch is not a key   */
    gen = swshm->gen;
    keys_let_go("test");                              /* nothing held: no edge  */
    assert(swshm->gen == gen);
    puts("harness ok");
    return 0;
}
'''


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    gcc = shutil.which("gcc")
    if not gcc or not sys.platform.startswith("linux"):
        pytest.skip("needs gcc on Linux")
    d = tmp_path_factory.mktemp("focusharness")
    (d / "h.c").write_text(_HARNESS)
    common = ["-std=gnu17", "-O0", "-Wall", "-Werror=implicit-function-declaration", "-I", RIG]
    obj = subprocess.run([gcc, *common, "-c", str(d / "h.c"), "-o", str(d / "h.o")],
                         capture_output=True, text=True)
    assert obj.returncode == 0, obj.stderr
    exe = d / "h"
    link = subprocess.run([gcc, str(d / "h.o"), "-o", str(exe), "-l:libEGL.so.1", "-l:libX11.so.6"],
                          capture_output=True, text=True)
    if link.returncode != 0:
        pytest.skip("no libEGL/libX11 to link padglhost against: %s" % link.stderr.strip()[-200:])
    return exe


def test_losing_the_focus_lets_go_of_held_keys_and_keeps_latches(harness):
    r = subprocess.run([str(harness)], capture_output=True, text=True)
    assert r.returncode == 0 and "harness ok" in r.stdout, (r.stdout, r.stderr[-400:])
    assert "let go of" in r.stderr
