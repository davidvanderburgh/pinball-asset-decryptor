"""PAD-521: the backdrop on a clip v2 build (James Bond LE 1.06): a mode's loop on the video bank's own surface.

The Bond owner's own mini-wizards should look like the game's: a video cycling all through the mode, back again
after a shot's video. On Bond a mode's clips play on the video bank's surface (clip v2), where the Godzilla backdrop
(a background element of the game's taken over) does not exist, so a "behind the HUD, over and over" clip played
once and was gone. With `value backdrop_surface 1` the runtime plays the loop on that surface again whenever it is
idle: after its own end, after a one-shot in its place, after a full-screen clip of the mode's. The code is lifted
from the runtime and run over a fake surface.
"""

import re

import pytest

from tests.test_spike2_mode_roster import RUNTIME, _host_run, _lift

PRELUDE = r"""
#include <stdio.h>
#include <string.h>
#define PM_CAN_CLIPS 0x4u
#define PM_CAN_BACKDROP 0x20000u
static unsigned can = PM_CAN_CLIPS | PM_CAN_BACKDROP;
static int clip_v2 = 1;
static struct { int on; } clip;
static unsigned long now_ms = 1000;
static unsigned long pm_ms(void) { return now_ms; }
static int state;                                  /* the surface: 2 = playing */
static char video[96];
static int known = 1;
static int surf_obj;
static void *clip2_surface(void) { return &surf_obj; }
static int set_video(void *s, unsigned *str) { strcpy(video, (const char *)(unsigned long)*str); return known; }
static int play(void *s, int a, int b) { printf("PLAY %s\n", video); state = 2; return 1; }
static void stop(void *s) { printf("STOP %s\n", video); state = 0; }
static int get_state(void *s) { return state; }
static unsigned fn(const char *n)
{
    if (!strcmp(n, "surface_set_video")) return (unsigned)(unsigned long)set_video;
    if (!strcmp(n, "surface_play")) return (unsigned)(unsigned long)play;
    if (!strcmp(n, "surface_stop")) return (unsigned)(unsigned long)stop;
    if (!strcmp(n, "surface_state")) return (unsigned)(unsigned long)get_state;
    return 0;
}
static long pm_port_value(const char *n, long fallback) { return !strcmp(n, "surface_playing") ? 2 : fallback; }
static char strs[8][96];
static int nstr;
static unsigned std_string(const char *s) { char *d = strs[nstr++ % 8]; strcpy(d, s); return (unsigned)(unsigned long)d; }
static void say(const char *f, ...) {}
static int str_eq(const char *a, const char *b) { return !strcmp(a, b); }
static unsigned bd_surface_state(void) { return state; }
static void bd_field(unsigned obj, unsigned v) { printf("FIELD written\n"); }
static struct { int ours, due; } gbg;              /* PAD-658: Godzilla's route (the game's own background clip back) */
static int disp_clip_ours;
static int bd_v2 = 1;
static int ck_ours, ck_last_ours;                                /* PAD-530: our own asks of the surface */
static unsigned ck_game_display(void) { return 0; }              /* PAD-639: no display of the game's over the TV */
#define CK_LOOP_MS 3000                                           /* PAD-725: a loop of the game's: one pass */
static unsigned long ck_gl_ms;
static long long ck_gl_len;
static char ck_game_last[96];
static long long ck_ms(const char *which, void *surf) { return 1000; }   /* the game's loop is 1 s long */
struct pm_mode { const char *name; };
static const struct pm_mode *running, *current;                 /* PAD-658: whose the backdrop is */
"""

MAIN = r"""
static void tick(unsigned long ms) { now_ms += ms; bd2_tick(); }
int main(void)
{
    tick(16);                                       /* nothing asked: nothing played */
    state = 2;                                      /* the game's main-play video on the surface */
    pm_backdrop("LOOP");
    tick(16);                                       /* the next tick plays it, over the game's */
    tick(16); tick(400);                            /* playing: left alone */
    printf("showing %d\n", pm_backdrop_showing());
    state = 0; tick(16);                            /* its end: again */
    tick(600);
    pm_backdrop_once("HIT"); tick(16);              /* a one-shot at once, in its place */
    state = 0; tick(600);                           /* its end: the loop */
    clip.on = 1; state = 2; tick(600);              /* a full-screen clip of ours has the surface */
    printf("showing %d\n", pm_backdrop_showing());
    clip.on = 0; state = 2; tick(16);               /* over, the game's video already there: the loop at once */
    state = 2; printf("game clip\n"); tick(600);    /* the surface busy (the game's or ours): left alone */
    state = 0; tick(600);
    pm_backdrop(0);                                 /* the mode ends it: ours stopped */
    tick(600); tick(600);
    printf("done\n");
    known = 0; pm_backdrop("NOPE"); tick(16); tick(600); tick(600);   /* no such clip: said once, not retried */
    return 0;
}
"""


def _bd_struct(src):
    m = re.search(r"static struct \{\n    char loop\[96\], once\[96\];.*?\} bd;\n(?:static [^\n]*\bbd_(?:owner|lingers);[^\n]*\n)*",
                  src, re.S)
    assert m
    return m.group(0)


def test_the_loop_plays_again_whenever_the_bank_surface_is_idle(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_bd_struct(src)] + [_lift(src, s) for s in (
        "static void bd_release(const char *why)", "static void bd2_play(void *surf)", "static void bd2_tick(void)\n{",
        "int pm_backdrop(const char *name)", "int pm_backdrop_once(const char *name)", "int pm_backdrop_showing(void)")]
    out = _host_run(tmp_path, PRELUDE + "\n".join(parts) + MAIN, flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    assert out == ["PLAY LOOP", "showing 1", "PLAY LOOP", "PLAY HIT", "PLAY LOOP", "showing 0", "PLAY LOOP",
                   "game clip", "PLAY LOOP", "STOP LOOP", "done"]
    assert "FIELD written" not in out          # never the Godzilla city's video field


def test_the_port_opts_in_and_the_runtime_needs_clip_v2_for_it():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _lift(src, "static void backdrop_arm(void)")
    assert 'pm_port_value("backdrop_surface", 0)' in arm and "!clip_v2" in arm and "bd_v2 = 1;" in arm
    assert arm.index("backdrop_surface") < arm.index('site("backdrop_draw")')
    assert "bd2_tick();" in _lift(src, "static void clip_tick(void)")
    # the Godzilla route's clip_stop is never asked for on clip v2 (the build has no such function)
    assert "if (!bd_v2 && bd.on && !clip.on" in _lift(src, "int pm_backdrop(const char *name)")


def test_every_port_whose_clips_play_on_the_games_own_bank_opts_in():
    """Seen on the glass in the emulator on James Bond LE 1.06 (2026-10-11) and Pro 1.06 (PAD-722, 2026-10-25), and on
    the newest build of every title with a clip v2 bank (PAD-725, 2026-10-25). Not on a port whose surface the app
    grafts into the HUD (`value clip_surface_hide 1`: the game never puts a clip there), nor on one the runtime plays
    clips on through `clip_play` (Jaws Pro 1.02, Godzilla Pro 1.16)."""
    ports = RUNTIME.parent / "ports"
    v1 = ("clip_play", "clip_stop", "video_player", "video_surface", "surface_state", "player_advance", "display_draw")
    want, on = [], []
    for p in sorted(ports.glob("*.port")):
        t = p.read_text(encoding="utf-8")
        if re.search(r"^value\s+backdrop_surface\s+1$", t, re.M):
            on.append(p.name)
        if not re.search(r"^site surface_set_video ", t, re.M) or re.search(r"^value clip_surface_hide\s+1", t, re.M):
            continue
        if all(re.search(r"^site %s " % s, t, re.M) for s in v1) and re.search(r"^data display_holder ", t, re.M) \
                and re.search(r"^value display_at ", t, re.M):     # the runtime's clip_play route (its clip_s/d/v)
            continue
        want.append(p.name)
    assert on == want and len(on) == 45
    assert "james_bond_le-1.06.port" in on and "jaws_pro-1.02.port" not in on and "rush_le-1.19.port" not in on


def test_the_games_main_play_video_gives_the_loop_the_surface_back():
    """Emulator run e3: the intro over, the loop played, and the game put its own main-play video (MainPlayLoop_<film>)
    on the surface 30 ms later; the loop waited it out. The port names that video (`text backdrop_idle`), the runtime
    watches the game's asks (one shared hook on surface_set_video, with PAD-446's clip variants) and takes the surface
    back for the loop; any other clip of the game's is waited out."""
    src = RUNTIME.read_text(encoding="utf-8")
    seen = _lift(src, "static void bd2_seen(unsigned *r)\n{")
    assert 'pm_port_text("backdrop_idle")' in seen and "bd.pending = 1;" in seen
    assert "(unsigned)(unsigned long)bank != r[0]" in seen               # the bank's surface only
    one = _lift(src, "static void on_surface_set_video(unsigned *r)")
    assert "bd2_seen(r)" in one and "on_clipv_set_video(r)" in one
    assert src.count('hook(fn("surface_set_video")') == 1                # a site takes one hook
    port = (RUNTIME.parent / "ports" / "james_bond_le-1.06.port").read_text(encoding="utf-8")
    assert re.search(r"^text backdrop_idle MainPlayLoop$", port, re.M)


GLOOP_MAIN = r"""
static void tick(unsigned long ms) { now_ms += ms; bd2_tick(); }
int main(void)
{
    pm_backdrop("LOOP");
    tick(16);                                       /* the loop plays */
    tick(600);
    strcpy(video, "TownBackground_Arabel");         /* the game LOOPS a background of its own over it (its play hook) */
    strcpy(ck_game_last, video);
    ck_gl_ms = now_ms | 1;
    state = 2;
    tick(16); tick(500);                            /* its one pass (1 s here) still runs: the loop waits */
    printf("waited\n");
    tick(600);                                      /* one pass over: the loop takes the surface back */
    printf("back %lu\n", ck_gl_ms);
    tick(600); tick(600);                           /* ours again: nothing more */
    printf("done\n");
    return 0;
}
"""


def test_a_loop_of_the_games_gets_one_pass_then_the_backdrop_comes_back(tmp_path):
    """PAD-725: a clip the game loops on the surface (D&D's TownBackground_<town>) is a background on every title -
    before, the backdrop waited behind it for good unless the port named it in `text backdrop_idle`"""
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_bd_struct(src)] + [_lift(src, s) for s in (
        "static void bd_release(const char *why)", "static void bd2_play(void *surf)", "static void bd2_tick(void)\n{",
        "int pm_backdrop(const char *name)", "int pm_backdrop_once(const char *name)", "int pm_backdrop_showing(void)")]
    out = _host_run(tmp_path, PRELUDE + "\n".join(parts) + GLOOP_MAIN, flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    assert out == ["PLAY LOOP", "waited", "PLAY LOOP", "back 0", "done"]
