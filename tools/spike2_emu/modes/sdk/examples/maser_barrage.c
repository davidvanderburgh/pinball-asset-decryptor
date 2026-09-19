/* maser_barrage.c - MASER BARRAGE: a COMBO CHAIN with a timer between shots, started by the game's
 * own SKILL SHOT, for Godzilla (item 152).
 *
 * The Maser cannons fire in sequence (the Maser tanks of the Showa and Heisei films): make the
 * shots in order, each one quickly after the last, and the multiplier climbs. Wait too long and
 * the chain breaks.
 *
 *   START      Make the game's SKILL SHOT (its own skill shot award, an EVENT the port names;
 *              MODE_SDK.md "Events"), or hit the Maser target 3 times in one ball. Once a
 *              ball per player. It runs beside anything the game is doing. A skill shot made
 *              while another of our modes runs is held for 15 s and starts when that one ends.
 *   SEQUENCE   LEFT RAMP, then RIGHT RAMP, then the BUILDING. Only the next shot in the
 *              sequence counts. Each step pays 1,000,000 x the multiplier.
 *   WINDOW     After a step, the next must come within 7 s. Miss the window and the CHAIN
 *              BREAKS: the multiplier goes back to x1 and the sequence starts again at the
 *              Left ramp.
 *   BARRAGE    The third step completes a barrage: a JACKPOT of 5,000,000 x the multiplier,
 *              then the multiplier goes up by 1 (up to x5), the clock gets 5 s more, the
 *              window gets 1 s shorter (down to 4 s), and the sequence starts again.
 *   CLOCK      40 s (plus 5 s a barrage).
 *   ENDS       When the clock runs out, or the ball drains, or the ball is tilted. It counts
 *              as WON with at least one barrage (for FINAL WARS). The screen shows the total.
 *   INSERTS    The NEXT shot's insert is bright Maser blue; the other two shots of the sequence
 *              are a dim blue, so the whole chain is on the playfield. The next shot is solid
 *              while no window runs (the first step), and BLINKS while the window runs, faster
 *              as it closes. Everything is handed back the moment the mode ends.
 *   DISPLAY    Priority 180 (the game's full-screen shot awards are not shown over the panel;
 *              its jackpots, starts and the tilt warning come through, and the panel is back).
 *   LIGHTS     No light sweep: the port's example sweep recolours the inserts around the
 *              shots (measured, item 157), so it would make shots that pay nothing look lit.
 *   SCREEN     "NEXT RIGHT RAMP 5" (the window's seconds) alternating with "x2  TIME 31".
 *
 * Emulator test triggers: /dump/maser_barrage.start, .stop, .shot "<shot name>".
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "MASER BARRAGE"
#define FOLDER             "maser_barrage"
#define ALT_START_SHOT     "Maser target"
#define HITS_TO_START      3
#define HELD_MS            15000          /* a skill shot made while another mode runs */
#define RUN_SECONDS        40
#define BARRAGE_ADDS_SECONDS 5
#define WINDOW_MS          7000
#define WINDOW_MIN_MS      4000
#define WINDOW_SHRINK_MS   1000
#define STEP_PAYS          1000000ull     /* x the multiplier */
#define JACKPOT_PAYS       5000000ull     /* x the multiplier */
#define MULT_MAX           5
#define TOTAL_SHOWN_MS     6000

#define SCREEN_NODE "PadMode_" FOLDER "_Screen"
#define SCREEN_TEXT "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"

#define N_STEPS 3
static const struct { const char *shot, *says; } STEP[N_STEPS] = {
    { "Left ramp",  "LEFT RAMP" },
    { "Right ramp", "RIGHT RAMP" },
    { "Building",   "BUILDING" },
};

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t step_mask[N_STEPS], alt_mask;
static unsigned hits[5], ran_ball[5];
static unsigned long held_until;          /* a held skill shot start; 0 = none */
static unsigned held_player;
static int skill_event = -1;
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_screen screen = { .node_name = SCREEN_NODE, .text_name = SCREEN_TEXT, .alt_ms = 1500 };
static unsigned poll;

static struct {
    int on;
    unsigned player, step, mult, barrages, breaks, best_mult;
    unsigned long step_at, window_ms;     /* the last step's time; the window now */
    struct kit_timer clock;
    uint64_t total;
} run;

/* ---- sound: the one place the mode's own clip, music and calls are played --------------------------
 * From modes/maser_barrage/assets.json through maser_barrage.assets (pad_mode_assets.h). */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_START, CUE_STEP, CUE_JACKPOT, CUE_BROKEN, CUE_TIME_UP, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:   pa_start(&own); break;                     /* its music, its start clip */
    case CUE_JACKPOT: pa_call(&own, "barrage"); break;           /* a barrage completed */
    case CUE_BROKEN:  pa_call(&own, "broken"); break;            /* the chain broke */
    case CUE_TIME_UP:                                            /* the clock: won with a barrage */
        if (!pa_call(&own, run.barrages ? "won" : "lost")) pm_callout(pm_callout_id("time_up"));
        break;
    case CUE_END:     pa_end(&own); break;
    default: break;                                              /* a step */
    }
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static unsigned window_left_s(void)
{
    unsigned long used = pm_ms() - run.step_at;
    return used >= run.window_ms ? 0 : (unsigned)((run.window_ms - used + 999) / 1000);
}

/* the chain on the playfield: the next shot bright (blinking to its window), the rest dim */
static void show_lamps(void)
{
    unsigned i;
    kit_lamps_begin(&lamps);
    for (i = 0; i < N_STEPS; i++) {
        if (i != run.step) {
            kit_lamps_shot(&lamps, step_mask[i], KIT_BLUE_DIM, PM_LAMP_SOLID, 0);
        } else if (run.step == 0) {
            kit_lamps_shot(&lamps, step_mask[i], KIT_BLUE, PM_LAMP_SOLID, 0);     /* no window runs yet */
        } else {
            unsigned long used = pm_ms() - run.step_at;
            unsigned long left = used >= run.window_ms ? 0 : run.window_ms - used;
            unsigned ms = left * 10 > run.window_ms * 6 ? 500 : left * 10 > run.window_ms * 3 ? 250 : 100;
            kit_lamps_shot(&lamps, step_mask[i], KIT_BLUE, PM_LAMP_BLINK, ms);
        }
    }
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char a[KIT_WORDS], b[KIT_WORDS];
    if (run.step == 0) pm_snprintf(a, sizeof a, "START: %s", STEP[0].says);
    else pm_snprintf(a, sizeof a, "NEXT %s %u", STEP[run.step].says, window_left_s());
    pm_snprintf(b, sizeof b, "x%u  TIME %u", run.mult, kit_timer_seconds(&run.clock));
    kit_screen_status(&screen, a, b);
    show_lamps();
}

/* ---- start and end ---------------------------------------------------------------------------- */
static int start(const char *why, int counted)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (counted && ran_ball[p]) {
        pm_log("not started (%s): it already ran this ball", why);
        return 0;
    }
    if (!kit_begin(MODE_NAME)) return 0;
    kit_display(KIT_DISPLAY_MODE);                /* first: before the screen and the clip */
    run.on = 1;
    run.player = p;
    run.step = 0;
    run.mult = run.best_mult = 1;
    run.barrages = run.breaks = 0;
    run.step_at = pm_ms();
    run.window_ms = WINDOW_MS;
    run.total = 0;
    kit_timer_set(&run.clock, RUN_SECONDS, 1);
    hits[p] = 0;
    held_until = 0;
    if (counted) ran_ball[p]++;
    kit_ledger_note(KIT_MASER, p, 0);
    kit_screen_show(&screen, 1);
    show();
    kit_screen_flash(&screen, 2000, "MASER BARRAGE");
    sound(CUE_START);
    pm_log("START (%s): player %u, %u s, sequence %s > %s > %s, window %lu ms, score %llu", why, p, RUN_SECONDS,
           STEP[0].shot, STEP[1].shot, STEP[2].shot, run.window_ms, (unsigned long long)pm_score(p));
    return 1;
}

static void end(const char *why)
{
    char a[KIT_WORDS], b[KIT_WORDS], n[24];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);                         /* every insert back to the game, at once */
    kit_end();
    kit_ledger_note(KIT_MASER, run.player, run.barrages > 0);
    sound(CUE_END);
    pm_snprintf(a, sizeof a, "TOTAL %s", kit_num(n, sizeof n, run.total));
    pm_snprintf(b, sizeof b, "BARRAGES %u  BEST x%u", run.barrages, run.best_mult);
    kit_screen_status(&screen, a, b);
    screen.flash[0] = 0;
    kit_screen_hide_in(&screen, TOTAL_SHOWN_MS);
    pm_log("END (%s): %u barrage(s), best x%u, %u chain(s) broken, total %llu, score %llu", why, run.barrages,
           run.best_mult, run.breaks, (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

/* ---- the chain ------------------------------------------------------------------------------------ */
static void chain_shot(uint64_t shot)
{
    char line[KIT_WORDS], n[24];
    unsigned i;
    uint64_t got;
    for (i = 0; i < N_STEPS; i++) {
        if (!step_mask[i] || !(shot & step_mask[i]) || !kit_fresh(&db, step_mask[i])) continue;
        if (i != run.step) {
            pm_log("%s: out of order (next is %s) - no effect", STEP[i].shot, STEP[run.step].shot);
            continue;
        }
        got = pay(STEP_PAYS * run.mult);
        pm_log("step %u %s: +%llu (x%u), %lu ms after the last", i + 1, STEP[i].shot, (unsigned long long)got,
               run.mult, pm_ms() - run.step_at);
        run.step_at = pm_ms();
        if (++run.step < N_STEPS) {
            pm_snprintf(line, sizeof line, "%s x%u", STEP[i].says, run.mult);
            kit_screen_flash(&screen, 900, line);
            sound(CUE_STEP);
            show();
            return;
        }
        got = pay(JACKPOT_PAYS * run.mult);
        run.barrages++;
        pm_log("BARRAGE %u: jackpot +%llu (x%u); multiplier -> x%u, +%u s, window %lu -> %lu ms", run.barrages,
               (unsigned long long)got, run.mult, run.mult < MULT_MAX ? run.mult + 1 : MULT_MAX, BARRAGE_ADDS_SECONDS,
               run.window_ms, run.window_ms > WINDOW_MIN_MS ? run.window_ms - WINDOW_SHRINK_MS : run.window_ms);
        pm_snprintf(line, sizeof line, "JACKPOT %s", kit_num(n, sizeof n, got));
        kit_screen_flash(&screen, 2000, line);
        sound(CUE_JACKPOT);
        if (run.mult < MULT_MAX) run.mult++;
        if (run.mult > run.best_mult) run.best_mult = run.mult;
        if (run.window_ms > WINDOW_MIN_MS) run.window_ms -= WINDOW_SHRINK_MS;
        kit_timer_add(&run.clock, BARRAGE_ADDS_SECONDS);
        run.step = 0;
        show();
        return;
    }
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    for (i = 0; i < N_STEPS; i++) {
        step_mask[i] = pm_shot(STEP[i].shot);
        if (!step_mask[i]) pm_log("this port has no \"%s\": the sequence cannot be completed", STEP[i].shot);
    }
    alt_mask = pm_shot(ALT_START_SHOT);
    skill_event = pm_event("skill_shot");
    pa_load(&own);
    pm_log("ready on %s %s: starts on the skill shot (event %d%s) or %s x%d (0x%llx); sequence 0x%llx 0x%llx 0x%llx",
           pm_game(), pm_version(), skill_event, skill_event < 0 ? ", NOT in this port" : "", ALT_START_SHOT,
           HITS_TO_START, (unsigned long long)alt_mask, (unsigned long long)step_mask[0],
           (unsigned long long)step_mask[1], (unsigned long long)step_mask[2]);
}

static void skill_shot(void)
{
    unsigned p = pm_player();
    pm_log("the game's skill shot (player %u)", p);
    if (run.on || p < 1 || p > 4) return;
    if (ran_ball[p]) {
        pm_log("skill shot: it already ran this ball");
        return;
    }
    if (start("skill shot", 1)) return;
    if (kit_running) {                      /* another of our modes: wait for it */
        held_until = pm_ms() + HELD_MS;
        held_player = p;
        pm_log("skill shot held for %d s: %s is running", HELD_MS / 1000, kit_running);
    }
}

static void on_event(unsigned id)
{
    if (skill_event >= 0 && (int)id == skill_event) skill_shot();
    if (kit_is_tilt(id)) {
        held_until = 0;
        end("tilted");                             /* its lights go dark with the game's */
    }
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_WORDS];
    if (!alt_mask || !(shot & alt_mask) || !kit_fresh(&db, alt_mask)) return;
    if (ran_ball[p]) {
        pm_log("%s: not counted - it already ran this ball", ALT_START_SHOT);
        return;
    }
    if (hits[p] < HITS_TO_START) hits[p]++;
    pm_log("%s %u of %d (player %u)", ALT_START_SHOT, hits[p], HITS_TO_START, p);
    if (hits[p] >= HITS_TO_START) {
        start("Maser target", 1);
    } else if (!kit_running) {
        pm_snprintf(line, sizeof line, "MASER %u OF %d", hits[p], HITS_TO_START);
        kit_screen_note(&screen, 2000, line);
    }
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    if (!pm_in_game() || p < 1 || p > 4) return;
    if (!run.on) {
        qualify_shot(shot, p);
        return;
    }
    if (p == run.player) chain_shot(shot);
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file", 0);
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void on_tick(void)
{
    unsigned p;
    kit_screen_tick(&screen);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) check_triggers();
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) hits[p] = ran_ball[p] = 0;
        held_until = 0;
        pm_log("new game: counts cleared");
    }
    if (held_until && !run.on) {            /* a held skill shot */
        if (pm_ms() >= held_until || pm_player() != held_player || !pm_in_game()) {
            held_until = 0;
            pm_log("the held skill shot lapsed");
        } else if (!kit_running) {
            held_until = 0;
            start("skill shot, held", 1);
        }
    }
    if (!run.on) return;
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on");
        return;
    }
    if (kit_timer_tick(&run.clock)) {
        sound(CUE_TIME_UP);
        end("time ran out");
        return;
    }
    if (run.step > 0 && pm_ms() - run.step_at >= run.window_ms) {
        pm_log("CHAIN BROKEN: no %s within %lu ms (was x%u)", STEP[run.step].shot, run.window_ms, run.mult);
        run.breaks++;
        run.step = 0;
        run.mult = 1;
        run.window_ms = WINDOW_MS;
        kit_screen_flash(&screen, 1500, "CHAIN BROKEN");
        sound(CUE_BROKEN);
    }
    show();
}

static void on_ball_end(void)
{
    unsigned p;
    end("ball ended");
    held_until = 0;
    for (p = 0; p < 5; p++) hits[p] = ran_ball[p] = 0;
}

static const struct pm_mode maser_barrage = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(maser_barrage);
