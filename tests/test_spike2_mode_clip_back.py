"""PAD-530: a mode's clip comes back after one of the game's (clip v2, James Bond 1.06).

Jim-Beam's own Bond mode plays a video as long as the mode. When the game put a short clip of its own on the one
video surface in the middle of it (Ball Lock, Extra Ball), the mode's video was gone for good and the game's main-play
video played for the rest of the mode. Now the runtime notes how far into the clip it was when the game's clip took the
surface, and once the game's clip is over (the game asks for its main-play video, or the surface is idle) puts it back
where it would be by then, with the surface's own seek - what the game does for its own film reels (PAD-456). The code
is lifted from the runtime and run over a fake surface whose clips have lengths and a position.
"""

import re

import pytest

from tests.test_spike2_mode_roster import RUNTIME, _host_run, _lift

PORTS = RUNTIME.parent / "ports"

PRELUDE = r"""
#include <stdio.h>
#include <string.h>
#define PM_CAN_CLIPS 0x4u
struct pm_mode { const char *name; };
static const struct pm_mode mode_a = { "A" }, mode_b = { "B" };
static const struct pm_mode *current, *running, *clip_owner;
static unsigned begun;
static unsigned can = PM_CAN_CLIPS;
static int clip_v2 = 1, clip_layer, clip_layer_in;
static struct { int on, seen; unsigned long started, last; } clip;
static volatile int disp_clip_ours, disp_clip_lost;
static char disp_clip_name[96];
static unsigned long now_ms = 1000;
static unsigned long pm_ms(void) { return now_ms; }
static void say(const char *f, ...) {}
static int str_eq(const char *a, const char *b) { return a && b && !strcmp(a, b); }
static const char *idle_text = "MainPlayLoop";
static const char *pm_port_text(const char *n) { return !strcmp(n, "backdrop_idle") ? idle_text : 0; }
static long pm_port_value(const char *n, long fallback) { return !strcmp(n, "surface_playing") ? 2 : fallback; }
static unsigned data(const char *n) { return 0; }
static unsigned fx_now;                            /* PAD-639: the game's foreground display effect now */
static unsigned disp_foreground_effect(void) { return fx_now; }
static void *clip_layer_video(void) { return 0; }
static void clip2_show(int on) {}
static char strs[8][96];
static int nstr;
static unsigned std_string(const char *s) { char *d = strs[nstr++ % 8]; strcpy(d, s); return (unsigned)(unsigned long)d; }

/* the bank's surface: one clip at a time, each with its length; the position runs from its play (or seek) */
static int surf_obj, other_obj;
static int state;                                  /* 2 = playing */
static char video[96];
static unsigned long played_at;
static long long offset;
static int seek_ok = 1;
static void *clip2_surface(void) { return &surf_obj; }
static long long length_of(const char *v)
{
    if (!strcmp(v, "PadMode_long_Clip")) return 40000;
    if (!strncmp(v, "MainPlayLoop", 12)) return 60000;
    if (!strcmp(v, "LeftRamp")) return 2000;
    if (!strcmp(v, "BondWomen_007_Loop")) return 8000;
    return 3000;
}
static long long position(void *s) { return state == 2 ? offset + (long long)(now_ms - played_at) : 0; }
static long long duration(void *s) { return state == 2 ? length_of(video) : 0; }
static void ck_seen(unsigned *r);
static void ck_play_seen(unsigned *r);
static int looping;
static int set_video(void *s, unsigned *str)
{
    static unsigned held;                          /* (a 32-bit game passes its own: low, as the hook's words are) */
    unsigned r[2];
    held = *str;
    r[0] = (unsigned)(unsigned long)s;
    r[1] = (unsigned)(unsigned long)&held;
    ck_seen(r);                                    /* the hook: it sees every ask, ours too */
    if (s != &surf_obj) return 1;
    strcpy(video, (const char *)(unsigned long)*str);
    state = 0;
    return strcmp(video, "Nope") != 0;
}
static int play(void *s, int a, int b)
{
    unsigned r[2] = { (unsigned)(unsigned long)s, (unsigned)a };
    ck_play_seen(r);                               /* the surface_play hook: its second argument is the loop flag */
    printf("PLAY %s%s\n", video, a ? " (looped)" : "");
    state = 2; played_at = now_ms; offset = 0; looping = a;
    return 1;
}
static int seek(void *s, long long ms) { if (!seek_ok) return 0; printf("SEEK %lld\n", ms); offset = ms; played_at = now_ms; return 1; }
static int get_state(void *s) { return state; }
static unsigned fn(const char *n)
{
    if (!strcmp(n, "surface_set_video")) return (unsigned)(unsigned long)set_video;
    if (!strcmp(n, "surface_play")) return (unsigned)(unsigned long)play;
    if (!strcmp(n, "surface_state")) return (unsigned)(unsigned long)get_state;
    if (!strcmp(n, "surface_seek")) return (unsigned)(unsigned long)seek;
    if (!strcmp(n, "surface_duration")) return (unsigned)(unsigned long)duration;
    if (!strcmp(n, "surface_position")) return (unsigned)(unsigned long)position;
    return 0;
}
"""

MAIN = r"""
static void tick(unsigned long ms)
{
    now_ms += ms;
    if (clip.on && state != 2) clip.on = 0;        /* clip_tick: the surface is idle */
    ck_tick();
    if (state == 2 && !looping && position(&surf_obj) >= length_of(video)) state = 0;   /* its end */
}
static void game(const char *name)                 /* the game puts a clip of its own on the surface */
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 0, -1);
}
static void game_loop(const char *name)            /* ... and one it loops (a background) */
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 1, -1);
}
static void begin(const struct pm_mode *m) { current = running = m; begun++; }
int main(void)
{
    ck_can = 1;
    begin(&mode_a);
    pm_clip("PadMode_long_Clip");                  /* the mode's video, 20 s */
    tick(16); tick(5000);
    game("BallLock");                              /* 5 s in: the game's 3 s clip */
    tick(1000); tick(1000);                        /* it plays: left alone */
    tick(1000);
    game("MainPlayLoop_DrNo");                     /* its end: the game's main-play video */
    tick(16);                                      /* ours back where it would be: ~8 s */
    tick(2000);
    game("LeftRamp");                              /* another, and this time the surface goes idle after it */
    tick(1000); tick(1000); tick(16);
    printf("on %d\n", clip.on);
    game("Something"); game("MainPlayLoop_DrNo");  /* two of the game's in a row: back once */
    tick(16); tick(16);
    printf("-- Bond Women: a start clip once, then a loop for as long as the game's multiplier runs\n");
    tick(2000);
    game("BondWomenStart_Honey"); tick(1000); tick(1000); tick(500);
    game_loop("BondWomen_007_Loop");
    tick(1000); tick(1000); printf("waits %d\n", !clip.on || ck.lost); tick(1000); tick(16);
    printf("on %d\n", clip.on);
    game("BondWomen_007Scoring_2X"); tick(16);      /* a scoring clip over ours: waited out */
    tick(3000); tick(16);
    printf("-- the mode ends under the game's clip\n");
    game("BallLock"); tick(1000);
    running = 0;
    tick(16); game("MainPlayLoop_DrNo"); tick(16); tick(16);
    printf("-- its time runs out under the game's clip\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16); tick(38000);
    game("BallLock"); tick(3000); game("MainPlayLoop_DrNo"); tick(16); tick(16);
    printf("-- it plays to its end\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16);
    for (int k = 0; k < 41; k++) tick(1000);
    game("MainPlayLoop_DrNo"); tick(16); tick(16);
    printf("-- another of ours began\n");
    pm_clip("PadMode_long_Clip"); tick(16); tick(2000);
    game("BallLock"); tick(1000);
    begin(&mode_b); tick(16);
    game("MainPlayLoop_DrNo"); tick(16);
    printf("-- the seek is refused\n");
    pm_clip("PadMode_long_Clip"); tick(16); tick(2000);
    game("BallLock"); seek_ok = 0; game("MainPlayLoop_DrNo"); tick(16);
    printf("on %d\n", clip.on);
    printf("-- another scene's surface is none of ours\n");
    seek_ok = 1; begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16); tick(2000);
    { unsigned str = std_string("Elsewhere"); set_video(&other_obj, &str); }
    tick(16); tick(1000);
    printf("done\n");
    return 0;
}
"""


def _ck_struct(src):
    m = re.search(r"#define CK_END_MS.*?\n\} ck;\nstatic int ck_can, ck_ours, ck_in, sv_ck, ck_play_hooked;\n"
                  r".*?static unsigned long ck_idle_due;\n", src, re.S)
    assert m
    # PAD-639 round 3: the game's display that owns the surface's clip (ck_game_display), and a clip of ours that waits
    fx = re.search(r"#define CK_FX_WINDOW_MS.*?\nstatic unsigned ck_game_display\(void\)\n\{.*?\n\}\n", src, re.S)
    wait = re.search(r"static struct \{\n    char name\[96\];\n    const struct pm_mode \*owner, \*running;.*?\} ck_wait;\n"
                     r"static int ck_wait_in;\n", src, re.S)
    assert fx and wait
    return (m.group(0) + fx.group(0) + wait.group(0) + "int pm_clip(const char *name);\n"
            + _lift(src, "static void ck_wait_tick(void)\n{") + "\n")


def test_a_modes_clip_comes_back_where_it_would_be_after_the_games(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_ck_struct(src)] + [_lift(src, s) for s in (
        "static long long ck_ms(const char *which, void *surf)", "static int ck_mode_runs(void)",
        "static void ck_drop(const char *why)", "static int clip2_start(void *surf, const char *name)",
        "static void ck_seen(unsigned *r)", "static void ck_play_seen(unsigned *r)", "static void ck_tick(void)\n{", "int pm_clip(const char *name)")]
    out = _host_run(tmp_path, PRELUDE + "\n".join(parts) + MAIN, flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    seeks = [int(x.split()[1]) for x in out if x.startswith("SEEK ")]
    out = [x if not x.startswith("SEEK ") else "SEEK" for x in out]
    assert out == [
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo",
        "PLAY PadMode_long_Clip", "SEEK",                     # back after the game's clip, at ~8 s
        "PLAY LeftRamp", "PLAY PadMode_long_Clip", "SEEK",    # the surface idle after the game's: back again
        "on 1",
        "PLAY Something", "PLAY MainPlayLoop_DrNo", "PLAY PadMode_long_Clip", "SEEK",
        "-- Bond Women: a start clip once, then a loop for as long as the game's multiplier runs",
        "PLAY BondWomenStart_Honey",                          # once: waited out
        "PLAY BondWomen_007_Loop (looped)", "waits 1",        # its loop: one pass, at most 3 s
        "PLAY PadMode_long_Clip", "SEEK", "on 1",
        "PLAY BondWomen_007Scoring_2X",                       # a scoring clip: waited out
        "PLAY PadMode_long_Clip", "SEEK",                     # 3 s, its end: the surface idle
        "-- the mode ends under the game's clip",
        "PLAY BallLock", "PLAY MainPlayLoop_DrNo",            # never back: its mode ended
        "-- its time runs out under the game's clip",
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo",
        "-- it plays to its end",
        "PLAY PadMode_long_Clip", "PLAY MainPlayLoop_DrNo",
        "-- another of ours began",
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo",
        "-- the seek is refused",
        "PLAY PadMode_long_Clip", "PLAY BallLock", "PLAY MainPlayLoop_DrNo", "PLAY PadMode_long_Clip",
        "on 1",                                               # from its start, rather than not at all
        "-- another scene's surface is none of ours",
        "PLAY PadMode_long_Clip", "done"]
    # where it would be by then: 5 s in, 3 s of the game's clip -> ~8 s; then ~10 s + 2 s idle wait; then on
    assert 8000 <= seeks[0] <= 8100
    assert 12000 <= seeks[1] <= 12200
    assert seeks[2] > seeks[1]
    # Bond Women: back 3 s into the 8 s loop, 2 + 2.5 + 3 s after the last return: where it would be by then
    assert seeks[3] - seeks[2] >= 2000 + 2500 + 3000


def test_the_runtime_hooks_it_on_clip_v2_with_the_ports_seek_only():
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _lift(src, "static void ck_arm(void)")
    assert '"surface_seek", "surface_duration", "surface_position"' in arm and "!clip_v2" in arm
    assert 'hook(fn("surface_play"), on_surface_play)' in arm and src.count('hook(fn("surface_play")') == 1
    assert "ck_arm();" in src and "ck_tick();" in _lift(src, "static void clip_tick(void)")
    one = _lift(src, "static void on_surface_set_video(unsigned *r)")
    assert one.index("ck_seen(r)") < one.index("on_clipv_set_video(r)")   # before a variant swaps the name
    assert src.count('hook(fn("surface_set_video")') == 1                  # a site takes one hook
    # the backdrop's own asks of the surface are ours, not a clip of the game's
    assert "ck_ours = 1;" in _lift(src, "static void bd2_play(void *surf)")


@pytest.mark.parametrize("port, seek, length, where", [
    ("james_bond_le-1.06.port", "0x00578404", "0x005780bc", "0x00578260"),
    ("james_bond_pro-1.06.port", "0x00574d5c", "0x00574a14", "0x00574bb8"),
])
def test_both_bond_builds_name_the_surfaces_seek_and_the_main_play_video(port, seek, length, where):
    text = (PORTS / port).read_text(encoding="utf-8")
    assert re.search(r"^site surface_seek\s+%s 0xe92d43f0 0xe1a07003$" % seek, text, re.M)
    assert re.search(r"^site surface_duration\s+%s 0xe5d030d4 0xe92d40f0$" % length, text, re.M)
    assert re.search(r"^site surface_position\s+%s 0xe5d030d4 0xe92d40f0$" % where, text, re.M)
    assert re.search(r"^text backdrop_idle MainPlayLoop$", text, re.M)


IDLE_MAIN = r"""
static int in_game = 1, bd_v2;
static struct { int on; } bd;
static int pm_in_game(void) { return in_game; }
static void tick(unsigned long ms)
{
    now_ms += ms;
    if (clip.on && state != 2) clip.on = 0;        /* clip_tick: the surface is idle */
    ck_tick();
    ck_idle_tick();
    if (state == 2 && !looping && position(&surf_obj) >= length_of(video)) state = 0;   /* its end */
}
static void game(const char *name)
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 0, -1);
}
static void game_loop(const char *name)
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 1, -1);
}
static void begin(const struct pm_mode *m) { current = running = m; begun++; }
static void ticks(int n, unsigned long ms) { while (n--) tick(ms); }
int main(void)
{
    ck_can = 1;
    game_loop("MainPlayLoop_DrNo");                /* the ball starts: the game's main-play video */
    tick(16);
    printf("-- ours plays to its end; the game asks for nothing\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); ticks(41, 1000);
    running = 0;
    ticks(10, 100);
    printf("-- the game's own clip ends and leaves the surface idle: the game's business\n");
    game("LeftRamp"); ticks(30, 100);
    printf("-- ours stopped (its mode ended) leaves it idle\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16); tick(5000);
    running = 0; state = 0;                        /* pm_clip_stop: the surface stopped */
    ticks(10, 100);
    printf("-- not in a game (the game is over)\n");
    begin(&mode_a);
    pm_clip("PadMode_long_Clip"); tick(16); tick(5000);
    in_game = 0; state = 0;
    ticks(10, 100);
    printf("done\n");
    return 0;
}
"""


def test_the_games_main_play_video_comes_back_when_ours_ends(tmp_path):
    """Round 4 (Jim-Beam on v1.184.3): his 45 s clip ran to its end with his mode, and the game's own background video
    did not come back until another game clip played (emulator, Bond Pro: our clip's end of stream and no ask from the
    game; the last frame stayed). The runtime asks for the main-play video the game last asked for, looped, once a clip
    of OURS has left the surface idle for 500 ms in a game - never after a clip of the game's, nor outside a game."""
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_ck_struct(src)] + [_lift(src, s) for s in (
        "static long long ck_ms(const char *which, void *surf)", "static int ck_mode_runs(void)",
        "static void ck_drop(const char *why)", "static int clip2_start(void *surf, const char *name)",
        "static void ck_seen(unsigned *r)", "static void ck_play_seen(unsigned *r)", "static void ck_tick(void)\n{",
        "int pm_clip(const char *name)")]
    idle = _lift(src, "static void ck_idle_tick(void)\n{")
    pre = PRELUDE.replace("static void ck_seen(unsigned *r);", "static void ck_seen(unsigned *r);\nstatic void ck_idle_tick(void);")
    out = _host_run(tmp_path, pre + "\n".join(parts) + "\n" + IDLE_MAIN.split("int main(void)")[0]
                    + idle + "\nint main(void)" + IDLE_MAIN.split("int main(void)")[1],
                    flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    assert out == [
        "PLAY MainPlayLoop_DrNo (looped)",
        "-- ours plays to its end; the game asks for nothing",
        "PLAY PadMode_long_Clip", "PLAY MainPlayLoop_DrNo (looped)",     # back 500 ms after ours ended
        "-- the game's own clip ends and leaves the surface idle: the game's business",
        "PLAY LeftRamp",
        "-- ours stopped (its mode ended) leaves it idle",
        "PLAY PadMode_long_Clip", "PLAY MainPlayLoop_DrNo (looped)",
        "-- not in a game (the game is over)",
        "PLAY PadMode_long_Clip",
        "done"]


def test_the_idle_watch_runs_from_the_tick_and_a_backdrop_counts_as_ours():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "ck_idle_tick();" in _lift(src, "static void clip_tick(void)")
    assert "ck_last_ours = 1;" in _lift(src, "static void bd2_play(void *surf)")
    seen = _lift(src, "static void ck_seen(unsigned *r)")
    assert seen.index("ck_last_ours = 0;") < seen.index("if (!ck.name[0]) return;")   # recorded with no clip of ours too


SPIN_MAIN = r"""
static void tick(unsigned long ms)
{
    now_ms += ms;
    if (clip.on && state != 2) clip.on = 0;
    ck_fx_track();
    ck_tick();
    ck_wait_tick();
    if (state == 2 && !looping && position(&surf_obj) >= length_of(video)) state = 0;
}
static void game_loop(const char *name)
{
    unsigned str = std_string(name);
    set_video(&surf_obj, &str);
    play(&surf_obj, 1, -1);
}
static void ticks(int n, unsigned long ms) { while (n--) tick(ms); }
int main(void)
{
    ck_can = 1;
    current = running = &mode_a; begun++;
    pm_clip("PadMode_long_Clip"); tick(16); tick(4000);
    printf("-- the spinner: effect 75 over the game's loop for 15 s\n");
    game_loop("Diamond_EarthSpin"); fx_now = 75;
    ticks(150, 100);
    printf("waits %d\n", ck.lost);
    fx_now = 0; tick(16);                          /* its end: ours at once, where it would be */
    printf("on %d\n", clip.on);
    printf("-- a loop with no effect over it: one pass, as before\n");
    tick(2000);
    game_loop("BondWomen_007_Loop"); ticks(20, 100);
    printf("waits %d\n", ck.lost);
    ticks(11, 100);
    printf("on %d\n", clip.on);
    printf("-- a skill shot: effect 392 plays its hat toss once and holds its picture over the last frame\n");
    tick(2000);
    { unsigned str = std_string("SkillShot_Bond_BrownTrilby"); set_video(&surf_obj, &str); play(&surf_obj, 0, -1); }
    fx_now = 392;
    ticks(34, 100);                                /* 3 s: the toss is over, the surface idle; the picture still up */
    printf("idle %d waits %d\n", state != 2, ck.lost);
    fx_now = 0; tick(16);                          /* the effect ends: ours */
    printf("on %d\n", clip.on);
    printf("-- round 3: a new clip of ours asked for under the skill shot's picture waits for its end\n");
    tick(2000);
    { unsigned str = std_string("SkillShot_Bond_BrownTrilby"); set_video(&surf_obj, &str); play(&surf_obj, 0, -1); }
    fx_now = 392;
    ticks(25, 100);
    printf("asked %d\n", pm_clip("PadMode_short"));
    ticks(10, 100);
    printf("video %s\n", video);                  /* still the game's */
    fx_now = 0; tick(16);
    printf("video %s\n", video);
    printf("-- an effect that began long after the game's clip owns none of it (Bond's serve and its film intro)\n");
    { unsigned str = std_string("GLDFNGR_Intro1"); set_video(&surf_obj, &str); play(&surf_obj, 1, -1); }
    ticks(20, 100);
    fx_now = 55; tick(16);
    printf("asked %d\n", pm_clip("PadMode_short"));
    tick(16);
    printf("video %s\n", video);                  /* ours at once */
    fx_now = 0;
    printf("done\n");
    return 0;
}
"""


def test_a_clip_under_a_display_effect_of_the_games_stays_until_it_ends(tmp_path):
    # PAD-639 (luvthatapex, Bond LE): the spinner's satellite is a see-through picture over the game's Diamond_EarthSpin
    # loop for as long as the spinner spins; the one pass put the mode's clip back under the satellite after 3 s.
    # Round 2 (on v1.220.1): a skill shot award plays its hat toss ONCE and keeps its picture over the toss's last frame
    # until the surface is idle; ours back at the toss's end kept the effect (and its picture) up for good
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_ck_struct(src)] + [_lift(src, s) for s in (
        "static long long ck_ms(const char *which, void *surf)", "static int ck_mode_runs(void)",
        "static void ck_drop(const char *why)", "static int clip2_start(void *surf, const char *name)",
        "static void ck_seen(unsigned *r)", "static void ck_play_seen(unsigned *r)", "static void ck_tick(void)\n{",
        "int pm_clip(const char *name)")]
    out = _host_run(tmp_path, PRELUDE + "\n".join(parts) + SPIN_MAIN, flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    seeks = [int(x.split()[1]) for x in out if x.startswith("SEEK ")]
    out = [x if not x.startswith("SEEK ") else "SEEK" for x in out]
    assert out == [
        "PLAY PadMode_long_Clip",
        "-- the spinner: effect 75 over the game's loop for 15 s",
        "PLAY Diamond_EarthSpin (looped)", "waits 1",           # 15 s, not 3: the satellite keeps its backdrop
        "PLAY PadMode_long_Clip", "SEEK", "on 1",
        "-- a loop with no effect over it: one pass, as before",
        "PLAY BondWomen_007_Loop (looped)", "waits 1",
        "PLAY PadMode_long_Clip", "SEEK", "on 1",
        "-- a skill shot: effect 392 plays its hat toss once and holds its picture over the last frame",
        "PLAY SkillShot_Bond_BrownTrilby", "idle 1 waits 1",    # not back at the toss's end: the picture is up
        "PLAY PadMode_long_Clip", "SEEK", "on 1",
        "-- round 3: a new clip of ours asked for under the skill shot's picture waits for its end",
        "PLAY SkillShot_Bond_BrownTrilby", "asked 1",
        "video SkillShot_Bond_BrownTrilby",
        "PLAY PadMode_short", "video PadMode_short",            # the effect over: ours, from its start
        "-- an effect that began long after the game's clip owns none of it (Bond's serve and its film intro)",
        "PLAY GLDFNGR_Intro1 (looped)", "PLAY PadMode_short", "asked 1", "video PadMode_short",
        "done"]
    assert 19000 <= seeks[0] <= 19200                           # 4 s in + 15 s under the game's: where it would be
    assert seeks[2] - seeks[1] >= 2000 + 3400                   # where it would be after the skill shot's 3.4 s


def test_the_backdrop_loop_waits_for_a_display_of_the_games_too():
    # the backdrop loop goes back on an idle surface: not while the game's effect holds its clip's last frame there -
    # nor at once after a clip of ours (round 3: the start clip the skill shot's hat toss took the surface from)
    body = _lift(RUNTIME.read_text(encoding="utf-8"), "static void bd2_tick(void)\n{")
    assert "if (ck_game_display()) return;" in body
    assert body.index("ck_game_display()") < body.index("if (bd.pending) { bd2_play(surf); return; }")
    tick = _lift(RUNTIME.read_text(encoding="utf-8"), "static void clip_tick(void)")
    assert tick.index("ck_fx_track();") < tick.index("bd2_tick();") and "ck_wait_tick();" in tick


FX_HEAD = r"""
#include <stdio.h>
#include <string.h>
static unsigned recs[2 * 5] = { 0, 0,  0, 0x10001,  0, 0x840002,  0, 0x10001,  0, 0x600002 };   /* {process, flags | prio << 16} */
static unsigned arg[2];
static unsigned char mgr[0x20];
static unsigned char *mgr_p;
static int no_manager;
static unsigned data(const char *n)
{
    if (!strcmp(n, "award_screen_arg")) return (unsigned)(unsigned long)arg;
    if (!strcmp(n, "display_effects")) return no_manager ? 0 : (unsigned)(unsigned long)&mgr_p;
    return 0;
}
static long pm_port_value(const char *n, long fallback) { return fallback; }
"""

FX_MAIN = r"""
int main(void)
{
    unsigned now;
    arg[0] = (unsigned)(unsigned long)recs; arg[1] = 5;
    mgr_p = mgr; *(unsigned *)(mgr + 4) = (unsigned)(unsigned long)arg;
    for (now = 0; now < 6; now++) {
        *(unsigned short *)(mgr + 0xc) = (unsigned short)now;
        printf("%u:%u ", now, disp_foreground_effect());
    }
    *(unsigned *)(mgr + 4) = 0;                    /* another table's manager: none of ours */
    printf("other:%u ", disp_foreground_effect());
    no_manager = 1;
    printf("none:%u\n", disp_foreground_effect());
    return 0;
}
"""


def test_only_a_foreground_effect_of_the_games_counts(tmp_path):
    # the effect now, from the manager of the effect table; a background effect (flag 1: Bond's in-game display 29,
    # Bond Women's 007 SCORING 226) is no display over the TV, nor an effect id past the table
    src = RUNTIME.read_text(encoding="utf-8")
    parts = [_lift(src, s) for s in (
        "static unsigned char *disp_manager(void)", "static unsigned disp_now(unsigned char *m)",
        "static unsigned disp_foreground_effect(void)\n{")]
    out = _host_run(tmp_path, FX_HEAD + "\n".join(parts) + FX_MAIN, flags=("-no-pie", "-fno-pie")).strip()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    assert out == "0:0 1:0 2:2 3:0 4:0 5:0 other:0 none:0"     # 4: the serve's, priority 96: nothing over the TV


@pytest.mark.parametrize("port, manager", [
    ("james_bond_le-1.06.port", "0x0089b708"),
    ("james_bond_pro-1.06.port", "0x008a0348"),
])
def test_both_bond_builds_name_the_display_effect_manager(port, manager):
    # read off each build's award_screen: its manager getter loads this pointer (emulator: the spinner = effect 75)
    text = (PORTS / port).read_text(encoding="utf-8")
    assert re.search(r"^data display_effects\s+%s$" % manager, text, re.M)
    assert "ck_game_display()" in _lift(RUNTIME.read_text(encoding="utf-8"), "static void ck_tick(void)\n{")
