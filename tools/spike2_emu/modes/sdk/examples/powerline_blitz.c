/* powerline_blitz.c - POWERLINE BLITZ, a game mode for Godzilla Pro 1.15 (Stern Spike 2).
 *
 * WRITTEN BY AN AI AGENT GIVEN ONLY THE SDK FOLDER (item 134's test of MODE_SDK.md), and
 * kept unchanged. In the emulator, with real switch presses, it started on two Big loops,
 * paid each powerline once, completed with its bonus (11,000,000), ended early on a shield,
 * and ended on time - on the first run.
 *
 *   - Make the Big loop 2 times in one ball and the mode starts.
 *   - For 15 seconds each powerline target (left, center, right) pays a flat 2,000,000,
 *     but only ONCE per run. All three hit: a 5,000,000 bonus and the mode ends at once
 *     ("completed").
 *   - Either shield target ends it early ("shielded"), with no bonus.
 *   - Its own screen, if the build added one: "3 TO GO", "2 TO GO", "1 TO GO", then
 *     "TOTAL <points>" at the end.
 *   - A red light sweep while it runs (the port's example light command, recoloured) and
 *     the port's lights-off command at the end.
 *   - The game's ten-second callout and countdown; its time-up callout only when time runs
 *     out (never when completed, shielded, drained or stopped by a trigger).
 *
 * Emulator test triggers, checked twice a second. Each is consumed when read, and none
 * does anything unless a game is on:
 *   echo 1 > /dump/powerline_blitz.start                  start it now (skips the Big loops)
 *   echo 1 > /dump/powerline_blitz.stop                   end it now (no time-up callout)
 *   echo "Powerline left" > /dump/powerline_blitz.shot    act as if the game dispatched that
 *                                                         shot (any shot name in the port)
 *
 * Rules kept (MODE_SDK.md): never block, no malloc, no libc, static state, pm_begin() before
 * starting, and a 0 / NULL return means "not on this game" - log it and carry on.
 */
#include "pad_mode.h"

/* ---- the knobs ------------------------------------------------------------------------- */
#define MODE_NAME         "POWERLINE BLITZ"
#define FOLDER            "powerline_blitz"   /* the mode's folder: screen and trigger names */
#define START_SHOT        "Big loop"
#define HITS_TO_START     2
#define RUN_SECONDS       15
#define TARGET_PAYS       2000000ull          /* each powerline target, once per run */
#define ALL_THREE_BONUS   5000000ull
#define TICKS_PER_SECOND  60
#define TOTAL_SHOWN_TICKS (5 * TICKS_PER_SECOND)

#define SCREEN_NODE  "PadMode_" FOLDER "_Screen"
#define SCREEN_TEXT  "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"

#define N_TARGETS    3
#define ALL_TARGETS  ((1u << N_TARGETS) - 1u)

static const char *const TARGET_NAMES[N_TARGETS] = {
    "Powerline left", "Powerline center", "Powerline right",
};
static const char *const SHIELD_NAMES[2] = { "Shield target left", "Shield target right" };

/* ---- state: static, because there is no allocator -------------------------------------- */
static uint64_t start_mask;                  /* the Big loop */
static uint64_t target_mask[N_TARGETS];      /* each powerline target */
static uint64_t shield_mask;                 /* both shield targets */
static unsigned id_ten_seconds, id_countdown, id_time_up;
static char red_sweep[128];                  /* "" = no light command for the run */
static unsigned hits[5];                     /* Big loops this ball, per player 1-4 */

static struct {
    int on;
    unsigned player, ticks_left, seconds_shown;
    unsigned paid;                           /* bit i: target i has paid this run */
    uint64_t total;                          /* what the game actually added */
} run;

static void *screen, *screen_words;          /* 0 when this build has no screen for us */
static char words_now[48];                   /* what the screen should say */
static unsigned hide_ticks;                  /* hide the screen this many ticks after the end */
static unsigned poll;

/* ---- small helpers (no libc) ------------------------------------------------------------- */
static unsigned targets_paid(unsigned bits)
{
    unsigned n = 0;
    for (; bits; bits >>= 1) n += bits & 1u;
    return n;
}

static int token_is(const char *t, unsigned len, const char *word)
{
    unsigned i;
    for (i = 0; i < len; i++)
        if (t[i] != word[i]) return 0;
    return word[len] == 0;
}

/* Copy the port's example "lights on" command, replacing the values of --red, --green and
 * --blue with red. Returns 1 only if all three were found and the result fits. */
static int recolour(char *out, unsigned cap, const char *example, const char *r, const char *g,
                    const char *b)
{
    unsigned n = 0, found = 0;
    const char *s = example, *replace = 0;
    if (!example || cap < 2) return 0;
    while (*s) {
        const char *t;
        unsigned len, i;
        if (*s == ' ' || *s == '\t') {
            if (n + 1 >= cap) return 0;
            out[n++] = *s++;
            continue;
        }
        for (t = s, len = 0; t[len] && t[len] != ' ' && t[len] != '\t'; len++) ;
        s = t + len;
        if (replace) {                            /* this token is a colour's value: swap it */
            /* copied with a bounds check per byte, so the compiler cannot make it strlen */
            for (i = 0; replace[i]; i++) {
                if (n + 1 >= cap) return 0;
                out[n++] = replace[i];
            }
            replace = 0;
            continue;
        }
        if (token_is(t, len, "--red")) {
            replace = r; found |= 1u;
        } else if (token_is(t, len, "--green")) {
            replace = g; found |= 2u;
        } else if (token_is(t, len, "--blue")) {
            replace = b; found |= 4u;
        }
        for (i = 0; i < len; i++) {
            if (n + 1 >= cap) return 0;
            out[n++] = t[i];
        }
    }
    out[n] = 0;
    return found == 7u && !replace;
}

static void say_words(const char *line)
{
    unsigned i;
    for (i = 0; line[i] && i + 1 < sizeof words_now; i++) words_now[i] = line[i];
    words_now[i] = 0;
    if (screen_words) pm_set_text(screen_words, words_now);
}

static void say_to_go(void)
{
    char line[24];
    pm_snprintf(line, sizeof line, "%u TO GO", N_TARGETS - targets_paid(run.paid));
    say_words(line);
}

static void say_total(void)
{
    char number[32], line[48];
    pm_commas(number, sizeof number, run.total);
    pm_snprintf(line, sizeof line, "TOTAL %s", number);
    say_words(line);
}

/* ---- start and end ----------------------------------------------------------------------- */
static int start(const char *why)
{
    if (run.on) {
        pm_log("not started (%s): already running", why);
        return 0;
    }
    if (!pm_in_game()) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (!pm_begin()) return 0;                   /* another mode is up; pm_begin logged it */

    run.on = 1;
    run.player = pm_player();
    run.ticks_left = RUN_SECONDS * TICKS_PER_SECOND;
    run.seconds_shown = RUN_SECONDS;
    run.paid = 0;
    run.total = 0;
    hide_ticks = 0;

    say_to_go();                                 /* "3 TO GO" */
    if (screen) pm_show(screen, 1);
    if (red_sweep[0] && !pm_lights(red_sweep)) pm_log("lights: the game did not take the red sweep");

    pm_log("START (%s): player %u, score %llu", why, run.player,
           (unsigned long long)pm_score(run.player));
    return 1;
}

static void end(const char *why)
{
    const char *off;
    if (!run.on) return;
    run.on = 0;
    off = pm_port_text("example_lights_off");
    if (off) pm_lights(off);
    say_total();                                 /* "TOTAL 11,000,000" */
    hide_ticks = TOTAL_SHOWN_TICKS;              /* leave the total up, then hide */
    pm_end();
    pm_log("END (%s): %u of %d targets, %llu points", why, targets_paid(run.paid), N_TARGETS,
           (unsigned long long)run.total);
}

/* ---- the callbacks ----------------------------------------------------------------------- */
static void on_init(void)
{
    int i;

    start_mask = pm_shot(START_SHOT);
    if (!start_mask) pm_log("no \"%s\" shot in this port: only the start trigger can start it", START_SHOT);
    for (i = 0; i < N_TARGETS; i++) {
        target_mask[i] = pm_shot(TARGET_NAMES[i]);
        if (!target_mask[i]) pm_log("no \"%s\" shot in this port: the mode cannot be completed",
                                    TARGET_NAMES[i]);
    }
    shield_mask = pm_shot(SHIELD_NAMES[0]) | pm_shot(SHIELD_NAMES[1]);
    if (!shield_mask) pm_log("no shield target shots in this port: it cannot be shielded");

    id_ten_seconds = pm_callout_id("ten_seconds");
    id_countdown = pm_callout_id("countdown");
    id_time_up = pm_callout_id("time_up");

    if (!recolour(red_sweep, sizeof red_sweep, pm_port_text("example_lights_on"), "255", "0", "0")) {
        red_sweep[0] = 0;
        pm_log("lights: no example_lights_on with --red/--green/--blue in this port; no red sweep");
    }

    pm_log("ready on %s %s: starts on %s x%d (0x%llx); targets 0x%llx 0x%llx 0x%llx; "
           "shields 0x%llx; callouts %u %u %u; can%s%s%s",
           pm_game(), pm_version(), START_SHOT, HITS_TO_START, (unsigned long long)start_mask,
           (unsigned long long)target_mask[0], (unsigned long long)target_mask[1],
           (unsigned long long)target_mask[2], (unsigned long long)shield_mask,
           id_ten_seconds, id_countdown, id_time_up,
           pm_can(PM_CAN_CALLOUT) ? " callout" : "", pm_can(PM_CAN_LIGHTS) ? " lights" : "",
           pm_can(PM_CAN_SCREENS) ? " screens" : "");
    if (red_sweep[0]) pm_log("red sweep: %s", red_sweep);
}

/* Find our screen and HIDE it (a built screen is visible until a mode hides it). The HUD
 * scene may load after init, so this is tried from the tick, twice a second, until found. */
static void find_screen(void)
{
    static unsigned tries;
    if (screen || !pm_can(PM_CAN_SCREENS) || (tries++ % 30) != 0) return;
    screen = pm_node("hud", SCREEN_NODE);
    if (!screen) return;
    screen_words = pm_text("hud", SCREEN_TEXT);
    if (run.on || hide_ticks) {                  /* found mid-run, or while the total is up */
        if (screen_words && words_now[0]) pm_set_text(screen_words, words_now);
        pm_show(screen, 1);
    } else {
        pm_show(screen, 0);
    }
    pm_log("screen found%s", screen_words ? ", with its words" : ", but not its words");
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    int i;
    if (!pm_in_game() || p < 1 || p > 4) return;

    if (!run.on) {
        /* Test BITS: a switch dispatches 0x1 first, then its own shot. */
        if (start_mask && (shot & start_mask)) {
            if (hits[p] < (unsigned)HITS_TO_START) hits[p]++;
            pm_log("%s %u of %d (player %u)", START_SHOT, hits[p], HITS_TO_START, p);
            /* Refused (another mode is up)? Keep the count: the next Big loop tries again. */
            if (hits[p] >= (unsigned)HITS_TO_START && start("Big loop"))
                hits[p] = 0;
        }
        return;
    }
    if (p != run.player) return;                 /* the tick ends the run on a player change */

    if (shield_mask && (shot & shield_mask)) {
        pm_log("%s hit", pm_shot_name(shot & shield_mask));
        end("shielded");
        return;
    }

    for (i = 0; i < N_TARGETS; i++) {
        uint64_t got;
        if (!target_mask[i] || !(shot & target_mask[i])) continue;
        if (run.paid & (1u << i)) {
            pm_log("%s again: it already paid this run", TARGET_NAMES[i]);
            continue;
        }
        run.paid |= 1u << i;
        got = pm_score_add(p, TARGET_PAYS);      /* the game may add less, or nothing */
        run.total += got;
        pm_log("%s: +%llu (%u of %d)", TARGET_NAMES[i], (unsigned long long)got,
               targets_paid(run.paid), N_TARGETS);
        if (run.paid != ALL_TARGETS) say_to_go();
    }

    if (run.paid == ALL_TARGETS) {
        uint64_t got = pm_score_add(p, ALL_THREE_BONUS);
        run.total += got;
        pm_log("all three powerlines: bonus +%llu", (unsigned long long)got);
        end("completed");
    }
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) {
        if (run.on) end("trigger file");
        else pm_log("stop trigger: not running");
    }
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t mask = pm_shot(name);
        if (!mask) {
            pm_log("shot trigger: no shot named \"%s\" in this port", name);
        } else if (!pm_in_game()) {
            pm_log("shot trigger (%s): no game in play", name);
        } else {
            pm_log("shot trigger: %s", name);
            on_shot(mask);
        }
    }
}

static void on_tick(void)
{
    unsigned seconds;

    find_screen();

    /* Trigger files are for the emulator; a file check every tick is needless work. */
    if (++poll % 30 == 0) check_triggers();

    /* No game: no Big loop count carries into the next one. */
    if (!pm_player()) hits[1] = hits[2] = hits[3] = hits[4] = 0;

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
        if (seconds == 10) pm_callout(id_ten_seconds);
        if (seconds >= 1 && seconds <= 5) pm_callout_nth(id_countdown, seconds - 1);
    }
    if (run.ticks_left == 0) {
        pm_callout(id_time_up);                  /* only here: time ran out */
        end("time ran out");
    }
}

static void on_ball_end(void)
{
    end("ball ended");
    hits[1] = hits[2] = hits[3] = hits[4] = 0;
}

static const struct pm_mode powerline_blitz = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
};
PM_REGISTER(powerline_blitz);
