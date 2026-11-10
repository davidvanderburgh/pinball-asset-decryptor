"""PAD-1107: the game's start-of-game logo is kept off the co-op character pick.

DoomWalrus666 (Godzilla): "The GODZILLA logo appears over the character selection screen during beginning of Co-Op or
Teams play. While it does disappear, it feels a little disruptive." Godzilla's logo reveal is a scene of its own
(43b52a63..., one node: Logo_Instance), auto-loaded and drawn over the HUD the pick's cards are in; a CO-OP PLAY start
with a teammate's Start opens the pick while it plays (emulator, Godzilla LE 1.16). The runtime hides the node while a
pick card is up and gives it back when the card goes.

- coop_logo_hold, lifted verbatim: no port lines, nothing; found once (retried every 250 ms until the scene has it),
  hidden every tick a card is up, shown again once when it goes.
- coop_screens_tick passes it whether a card is on the glass.
- The Godzilla 1.16 ports (LE and Pro, the same scene id on both cards) name the scene and the node.
"""
import pathlib

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
LOGO_SCENE = "43b52a63772ce0a35b7f0e3d4f249566066b55f8"

MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
static void say(const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); printf("\n"); }
static unsigned long now_ms = 1000;
static unsigned long pm_ms(void) { return now_ms; }
static int ported = 1, loaded = 0, finds = 0, shows = 0, visible = 1;
static int node;
static const char *pm_port_text(const char *k)
{
    if (!ported) return 0;
    return !strcmp(k, "start_logo_scene") ? "43b52a63" : !strcmp(k, "start_logo_path") ? "Logo_Instance" : 0;
}
static void *pm_node(const char *where, const char *path)
{
    finds++;
    return loaded && !strcmp(where, "43b52a63") && !strcmp(path, "Logo_Instance") ? (void *)&node : 0;
}
static void pm_show(void *n, int on) { if (n == &node) shows++, visible = on; }
static void *coop_logo;
static unsigned long coop_logo_try;
static int coop_logo_hid, coop_logo_said;
@FN@
static void tick(int up, const char *what) { now_ms += 100; coop_logo_hold(up); printf("%s: visible %d finds %d shows %d\n", what, visible, finds, shows); }
int main(void)
{
    ported = @PORTED@;
    tick(0, "no card");
    tick(1, "card, scene not up");
    tick(1, "card, 100 ms later");
    loaded = 1;
    tick(1, "card, 200 ms later");
    tick(1, "card, 300 ms later");
    tick(1, "card, a tick on");
    tick(0, "card gone");
    tick(0, "no card");
    tick(1, "next card");
    return 0;
}
"""


def _run(tmp_path, ported):
    """The lifted function over MAIN's model game; *ported*: the port names the logo."""
    code = MAIN.replace("@FN@", R._lift(RUNTIME.read_text(encoding="utf-8"), "static void coop_logo_hold(int card_up)\n{"))
    code = code.replace("@PORTED@", "1" if ported else "0")
    return R._host_run(tmp_path, code).splitlines()


def test_the_logo_is_hidden_while_a_card_is_up_and_given_back_after(tmp_path):
    out = _run(tmp_path, True)
    lines = [l for l in out if ": visible" in l]
    said = [l for l in out if ": visible" not in l]
    assert lines[0] == "no card: visible 1 finds 0 shows 0"                     # nothing looked for with no card
    assert lines[1] == "card, scene not up: visible 1 finds 1 shows 0"
    assert lines[2] == "card, 100 ms later: visible 1 finds 1 shows 0"          # retried at 250 ms, not each tick
    assert lines[3] == "card, 200 ms later: visible 1 finds 1 shows 0"
    assert lines[4] == "card, 300 ms later: visible 0 finds 2 shows 1"          # found: hidden
    assert lines[5] == "card, a tick on: visible 0 finds 2 shows 2"             # hidden again each tick
    assert lines[6] == "card gone: visible 1 finds 2 shows 3"                   # given back once
    assert lines[7] == "no card: visible 1 finds 2 shows 3"
    assert lines[8] == "next card: visible 0 finds 2 shows 4"                   # the node found once stays
    assert sum("is not up yet" in l for l in said) == 1
    assert sum("given back" in l for l in said) == 1


def test_a_port_without_the_lines_leaves_the_game_alone(tmp_path):
    out = _run(tmp_path, False)
    assert all(l.endswith("visible 1 finds 0 shows 0") for l in out)


def test_the_pick_screens_pass_whether_a_card_is_up():
    tick = R._lift(RUNTIME.read_text(encoding="utf-8"), "static void coop_screens_tick(void)")
    assert "coop_logo_hold(want >= 0 && want <= coop_ch_n && coop_scr[want] != 0);" in tick


def test_the_godzilla_1_16_ports_name_the_start_logo():
    for name in ("godzilla_le-1.16.port", "godzilla_pro-1.16.port"):
        lines = (SDK / "ports" / name).read_text(encoding="utf-8").splitlines()
        assert "text start_logo_scene     " + LOGO_SCENE in lines, name
        assert "text start_logo_path      Logo_Instance" in lines, name
