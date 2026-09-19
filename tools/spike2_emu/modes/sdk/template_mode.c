/* template_mode.c - a complete game mode to copy and change. (item 134)
 *
 * TARGET RUSH:
 *   - hit the starting shot 3 times in one ball and the mode starts;
 *   - for 20 seconds every named shot scores, each one worth more than the last;
 *   - it shows its own screen (if the build added one), plays a clip, sweeps the lights
 *     and counts down in the game's own voice;
 *   - when time runs out (or the ball drains) it shows the total and cleans up.
 *
 * It uses no address and no game-specific number: everything specific to a game comes
 * from that game's PORT (pm_shot, pm_callout_id, pm_port_text...), so this file runs
 * unchanged on any game that has one. Build and try it: MODE_SDK.md, "The loop".
 *
 * Everything below runs inside the game. The rules (pad_mode.h, MODE_SDK.md): never
 * block, no malloc, static state, pm_begin() before starting, and treat a 0 / NULL
 * return as "this game cannot do that" - then carry on without it.
 */
#include "pad_mode.h"

/* ---- the knobs: change these first ------------------------------------------------ */
#define MODE_NAME        "TARGET RUSH"
#define HITS_TO_START    3
#define RUN_SECONDS      20
#define FIRST_SHOT_PAYS  1000000ull      /* the Nth shot pays N times this */
#define TICKS_PER_SECOND 60              /* the tick callback runs 60 times a second */

/* The screen a build added for this mode (the Modes tab names them after the mode's
 * folder; this template's folder is "template"). Not there = no screen, which is fine. */
#define SCREEN_NODE  "PadMode_template_Screen"
#define SCREEN_TEXT  "PadMode_template_Screen.PadMode_template_Screen_Words"

/* ---- state: static, because there is no allocator ------------------------------------ */
static uint64_t start_mask;        /* the starting shot's bit(s) */
static uint64_t scoring_mask;      /* every named shot */
static unsigned hits[5];           /* starting-shot hits this ball, per player 1-4 */

static struct {
    int on;
    unsigned player, ticks_left, seconds_shown, shots;
    uint64_t total;
} run;

static void *screen, *screen_words; /* 0 when this game or build has no screen for us */
static unsigned hide_ticks;         /* hide the screen this many ticks after the end */
static unsigned poll;               /* ticks, for checking trigger files twice a second */

/* ---- showing words ------------------------------------------------------------------ */
static void words(const char *before, uint64_t value, const char *after)
{
    char number[32], line[96];
    if (!screen_words) return;
    pm_commas(number, sizeof number, value);
    pm_snprintf(line, sizeof line, "%s%s%s", before, number, after);
    pm_set_text(screen_words, line);
}

/* ---- start and end ----------------------------------------------------------------------- */
static void start(const char *why)
{
    const char *clip, *lights;
    if (run.on || !pm_in_game()) return;
    /* One of our modes at a time: a card can carry several. */
    if (!pm_begin()) return;
    run.on = 1;
    run.player = pm_player();
    run.ticks_left = RUN_SECONDS * TICKS_PER_SECOND;
    run.seconds_shown = RUN_SECONDS;
    run.shots = 0;
    run.total = 0;
    hide_ticks = 0;

    if (screen) {
        words("", FIRST_SHOT_PAYS, " A SHOT");
        pm_show(screen, 1);
    }
    /* A clip plays full screen; the runtime keeps drawing it until it ends. */
    clip = pm_port_text("example_clip");
    if (clip) pm_clip(clip);
    lights = pm_port_text("example_lights_on");
    if (lights) pm_lights(lights);

    pm_log("START (%s): player %u, score %llu", why, run.player,
           (unsigned long long)pm_score(run.player));
}

static void end(const char *why)
{
    const char *lights;
    if (!run.on) return;
    run.on = 0;
    lights = pm_port_text("example_lights_off");
    if (lights) pm_lights(lights);
    if (screen) {
        words("TOTAL ", run.total, "");
        hide_ticks = 5 * TICKS_PER_SECOND;          /* leave the total up for 5 s */
    }
    pm_end();
    pm_log("END (%s): %u shots, %llu points", why, run.shots, (unsigned long long)run.total);
}

/* ---- the callbacks ------------------------------------------------------------------------ */
static void on_init(void)
{
    const char *name;
    uint64_t mask;
    int i;

    /* The starting shot, by name. The port suggests one for its game; a mode written for
     * one game would just say pm_shot("Maser target"). */
    name = pm_port_text("example_start_shot");
    start_mask = name ? pm_shot(name) : 0;
    if (!start_mask && pm_shot_at(0, &mask)) {       /* no suggestion: the first named shot */
        name = pm_shot_at(0, 0);
        start_mask = mask;
    }
    for (i = 0; pm_shot_at(i, &mask); i++)
        scoring_mask |= mask;
    pm_log("ready on %s %s: starts on %s x%d, %d scoring shots",
           pm_game(), pm_version(), name ? name : "(no shots in this port)", HITS_TO_START,
           pm_shot_count());
}

/* Find our screen and HIDE it: a built screen is visible until a mode hides it. The HUD
 * scene may load after init, so this is tried from the tick until it works. */
static void find_screen(void)
{
    static unsigned tries;
    if (screen || !pm_can(PM_CAN_SCREENS) || (tries++ % 30) != 0) return;
    screen = pm_node("hud", SCREEN_NODE);
    if (!screen) return;
    screen_words = pm_text("hud", SCREEN_TEXT);
    if (!run.on) pm_show(screen, 0);
    pm_log("screen found%s", screen_words ? ", with its words" : ", but not its words");
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    if (!pm_in_game() || p < 1 || p > 4) return;

    if (!run.on) {
        /* Test BITS: a switch dispatches 0x1 first, then its own shot. */
        if (start_mask && (shot & start_mask)) {
            hits[p]++;
            pm_log("start shot %u of %d (player %u)", hits[p], HITS_TO_START, p);
            if (hits[p] >= (unsigned)HITS_TO_START) {
                hits[p] = 0;
                start("start shot");
            }
        }
        return;
    }

    if (p == run.player && (shot & scoring_mask)) {
        uint64_t asked = FIRST_SHOT_PAYS * ++run.shots;
        uint64_t got = pm_score_add(p, asked);   /* the game may add less, or nothing */
        run.total += got;
        words("+", got, "");
        pm_log("%s: +%llu", pm_shot_name(shot & scoring_mask), (unsigned long long)got);
    }
}

static void on_tick(void)
{
    unsigned seconds;

    find_screen();

    /* Test triggers, for the emulator: `echo 1 > /dump/template.start` (MODE_SDK.md).
     * Checked twice a second - a file check every tick is needless work for the game. */
    if (++poll % 30 == 0) {
        if (pm_trigger("template.start")) start("trigger file");
        if (pm_trigger("template.stop")) end("trigger file");
    }

    if (hide_ticks && --hide_ticks == 0 && !run.on && screen) pm_show(screen, 0);
    if (!run.on) return;

    /* The game can end, or change player, under us. */
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on");
        return;
    }
    if (run.ticks_left) run.ticks_left--;
    seconds = (run.ticks_left + TICKS_PER_SECOND - 1) / TICKS_PER_SECOND;
    if (seconds != run.seconds_shown) {
        run.seconds_shown = seconds;
        if (seconds == 10) pm_callout(pm_callout_id("ten_seconds"));
        if (seconds >= 1 && seconds <= 5) pm_callout_nth(pm_callout_id("countdown"), seconds - 1);
    }
    if (run.ticks_left == 0) {
        pm_callout(pm_callout_id("time_up"));
        end("time ran out");
    }
}

static void on_ball_end(void)
{
    end("ball ended");
    hits[1] = hits[2] = hits[3] = hits[4] = 0;
}

static const struct pm_mode target_rush = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
};
PM_REGISTER(target_rush);
