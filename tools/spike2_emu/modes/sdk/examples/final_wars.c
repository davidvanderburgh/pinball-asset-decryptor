/* final_wars.c - FINAL WARS: a MULTI-PHASE wizard mode with qualification, for Godzilla (item 152).
 *
 * Godzilla: Final Wars (2004): the Xiliens set every monster loose at once. Three phases, each
 * with its own shots, its own clock and bigger stakes, earned by playing the other modes.
 *
 *   QUALIFY    Play KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE in one game (won or not),
 *              or WIN any two of them. Then FINAL WARS IS LIT (the screen says so) and stays lit
 *              through the rest of the game. Kept per player; a new game starts from nothing.
 *   START      With FINAL WARS lit, shoot the BUILDING. It never runs beside the game's own
 *              battle or multiball (it is the wizard mode): it waits, still lit, and the next
 *              Building shot after them starts it. Once per qualification: afterwards the three
 *              modes have to be played again.
 *   PHASE 1    INVASION (25 s): the LEFT RAMP, the RIGHT RAMP and the BIG LOOP are lit. Each
 *              one pays 3,000,000 and goes out. All three out: phase 2.
 *   PHASE 2    MONSTER X (25 s): ONE target is lit and it MOVES every 3 s among the three
 *              powerline targets and the Godzilla target. Hit the lit one 3 times: 5,000,000,
 *              then 10,000,000, then 15,000,000. Then phase 3.
 *   PHASE 3    KEIZER GHIDORAH (20 s): the BUILDING is the wizard shot: 30,000,000 plus
 *              1,000,000 for every second left.
 *   ADD TIME   Any shield target adds 3 s to the phase's clock, 3 times a phase.
 *   ENDS       GODZILLA WINS (the wizard shot), or THE XILIENS WIN (a phase's clock runs out),
 *              or the ball drains, or the ball is tilted. The screen shows the total.
 *   INSERTS    FINAL WARS IS LIT: the BUILDING pulses gold whenever none of our modes runs (not
 *              between balls). Phase 1: the cities still to save (LEFT RAMP, RIGHT RAMP, BIG
 *              LOOP) blink orange, faster as the phase clock runs down; a saved one goes back to
 *              the game. Phase 2: only the lit target's insert flashes (a powerline or MAGNA
 *              GRAB), and it follows MONSTER X as it moves. Phase 3: the BUILDING blinks gold,
 *              faster as the clock runs down. In every phase the three SHIELD inserts pulse
 *              green while add-time is left. Everything is handed back at the end.
 *   DISPLAY    Priority 190, the wizard's: the game's jackpots wait until it ends, and its
 *              full-screen shot awards, multiball and battle start screens and totals are not
 *              shown while it runs; the battle select screen, the raid award and the tilt
 *              warning still come through.
 *   LIGHTS     No light sweep: the port's example sweep recolours the inserts around the
 *              shots (measured, item 157), so it would make shots that pay nothing look lit.
 *   SCREEN     Each phase's own lines, e.g. "SAVE 2 CITIES 18" / "PHASE 1 INVASION",
 *              "HIT POWERLINE C 1/3", "SHOOT THE BUILDING 12" / "WIZARD 42,000,000".
 *
 * The qualification is the pack's ledger (intricate_kit.h): each of the other three modes notes
 * it was played, and whether it was won, when it starts and ends. Built without them, FINAL
 * WARS only starts from its trigger file.
 *
 * Emulator test triggers: /dump/final_wars.start (start now), .stop, .shot "<shot name>",
 * .light (light it for the player up, as if qualified).
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "FINAL WARS"
#define FOLDER             "final_wars"
#define START_SHOT         "Building"
#define P1_SECONDS         25
#define P2_SECONDS         25
#define P3_SECONDS         20
#define P1_PAYS            3000000ull
#define P2_PAYS            5000000ull     /* x hits in phase 2 */
#define P2_HITS            3
#define P2_MOVE_MS         3000
#define WIZARD_BASE        30000000ull
#define WIZARD_PER_SECOND  1000000ull
#define ADD_SECONDS        3
#define ADDS_PER_PHASE     3
#define LIT_NOTE_DELAY_MS  7000           /* after the mode that lit it has shown its total */
#define TOTAL_SHOWN_MS     7000

#define SCREEN_NODE "PadMode_" FOLDER "_Screen"
#define SCREEN_TEXT "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"

#define N_P1 3
static const struct { const char *shot, *says; } P1[N_P1] = {
    { "Left ramp", "LEFT RAMP" }, { "Right ramp", "RIGHT RAMP" }, { "Big loop", "BIG LOOP" },
};
#define N_P2 4
static const struct { const char *shot, *says; } P2[N_P2] = {
    { "Powerline left", "POWERLINE L" }, { "Powerline center", "POWERLINE C" },
    { "Powerline right", "POWERLINE R" }, { "Godzilla target", "GODZILLA" },
};
static const char *const SHIELDS[3] = { "Shield target left", "Shield target center", "Shield target right" };

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t start_mask, p1_mask[N_P1], p2_mask[N_P2], shield_mask;
static int lit[5];                        /* per player: FINAL WARS is lit */
static unsigned long lit_note_at;         /* show "FINAL WARS IS LIT" then; 0 = nothing to show */
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static int between_balls;                 /* a ball ended; the next shot or ball start clears it */
static int ball_start_event = -1;
static struct kit_screen screen = { .node_name = SCREEN_NODE, .text_name = SCREEN_TEXT, .alt_ms = 1500 };
static unsigned poll;
static unsigned rnd = 12345;

static struct {
    int on, phase;                        /* 1, 2, 3 */
    unsigned player, p1_left, p1_done, p2_lit, p2_hits, adds;
    unsigned long p2_moved;
    struct kit_timer clock;
    uint64_t total;
} run;

/* ---- sound: the one place the mode's own clip, music and calls are played --------------------------
 * From modes/final_wars/assets.json through final_wars.assets (pad_mode_assets.h). A phase starting
 * is the phase before it WON: phase 2 starting plays "phase1", phase 3 starting "phase2". */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_LIT, CUE_START, CUE_PHASE, CUE_HIT, CUE_MOVE, CUE_ADD_TIME, CUE_WIZARD, CUE_TIME_UP, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:   pa_start(&own); break;                     /* its music, its start clip */
    case CUE_PHASE:                                              /* the phase before this one was won */
        if (run.phase == 2) pa_call(&own, "phase1");
        else if (run.phase == 3) pa_call(&own, "phase2");
        break;
    case CUE_WIZARD:  pa_call(&own, "won"); break;               /* GODZILLA WINS */
    case CUE_TIME_UP:                                            /* a phase lost: THE XILIENS WIN */
        if (!pa_call(&own, "lost")) pm_callout(pm_callout_id("time_up"));
        break;
    case CUE_END:     pa_end(&own); break;
    default: break;                                              /* lit, a hit, Monster X moves, add time */
    }
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static uint64_t wizard_value(void)
{
    return WIZARD_BASE + WIZARD_PER_SECOND * kit_timer_seconds(&run.clock);
}

static unsigned next_random(unsigned n)
{
    rnd = rnd * 1103515245u + 12345u + (unsigned)pm_ms();
    return (rnd >> 16) % n;
}

/* ---- qualification (the pack's ledger) ------------------------------------------------------------- */
static int qualified(unsigned p, unsigned *played, unsigned *won)
{
    unsigned k;
    *played = *won = 0;
    for (k = 0; k < KIT_LEDGER_MODES; k++) {
        *played += kit_ledger.played[p][k] ? 1u : 0u;
        *won += kit_ledger.won[p][k] ? 1u : 0u;
    }
    return *played == KIT_LEDGER_MODES || *won >= 2;
}

static void light(unsigned p, const char *why)
{
    lit[p] = 1;
    lit_note_at = pm_ms() + LIT_NOTE_DELAY_MS;
    pm_log("FINAL WARS IS LIT for player %u (%s): shoot the %s", p, why, START_SHOT);
    sound(CUE_LIT);
}

static void qualify_watch(void)
{
    unsigned p = pm_player(), played, won;
    if (p < 1 || p > 4 || lit[p] || run.on) return;
    if (qualified(p, &played, &won)) {
        char why[64];
        pm_snprintf(why, sizeof why, "%u of %d played, %u won", played, KIT_LEDGER_MODES, won);
        light(p, why);
    }
}

/* ---- the inserts ---------------------------------------------------------------------------------- */
static unsigned phase_seconds(int k) { return k == 1 ? P1_SECONDS : k == 2 ? P2_SECONDS : P3_SECONDS; }

static void show_lamps(void)
{
    unsigned i;
    unsigned long left = run.clock.ticks * 1000ul / KIT_TICKS, total = phase_seconds(run.phase) * 1000ul;
    uint64_t unsaved = 0;
    kit_lamps_begin(&lamps);
    if (run.phase == 1) {
        for (i = 0; i < N_P1; i++)
            if (!(run.p1_done & (1u << i))) unsaved |= p1_mask[i];
        kit_lamps_shot(&lamps, unsaved, KIT_ORANGE, PM_LAMP_BLINK, kit_hurry_ms(left, total));
    } else if (run.phase == 2) {
        kit_lamps_shot(&lamps, p2_mask[run.p2_lit], KIT_PURPLE, PM_LAMP_BLINK, 150);   /* MONSTER X is here */
    } else {
        kit_lamps_shot(&lamps, start_mask, KIT_GOLD, PM_LAMP_BLINK, kit_hurry_ms(left, total));
    }
    if (run.adds < ADDS_PER_PHASE) kit_lamps_shot(&lamps, shield_mask, KIT_GREEN, PM_LAMP_PULSE, 1200);
    kit_lamps_commit(&lamps);
}

/* FINAL WARS IS LIT and waiting: the Building says so while none of our modes runs, in play */
static void idle_lamps(void)
{
    unsigned p = pm_player();
    kit_lamps_begin(&lamps);
    if (pm_in_game() && p >= 1 && p <= 4 && lit[p] && !kit_running && !between_balls)
        kit_lamps_shot(&lamps, start_mask, KIT_GOLD, PM_LAMP_PULSE, 1000);
    kit_lamps_commit(&lamps);
}

/* ---- phases ------------------------------------------------------------------------------------- */
static void show(void)
{
    char a[KIT_WORDS], b[KIT_WORDS], n[24];
    unsigned s = kit_timer_seconds(&run.clock);
    show_lamps();
    if (run.phase == 1) {
        pm_snprintf(a, sizeof a, "SAVE %u %s %u", run.p1_left, run.p1_left == 1 ? "CITY" : "CITIES", s);
        pm_snprintf(b, sizeof b, "PHASE 1 INVASION");
    } else if (run.phase == 2) {
        pm_snprintf(a, sizeof a, "HIT %s %u/%d", P2[run.p2_lit].says, run.p2_hits, P2_HITS);
        pm_snprintf(b, sizeof b, "PHASE 2 MONSTER X %u", s);
    } else {
        pm_snprintf(a, sizeof a, "SHOOT THE BUILDING %u", s);
        pm_snprintf(b, sizeof b, "WIZARD %s", kit_num(n, sizeof n, wizard_value()));
    }
    kit_screen_status(&screen, a, b);
}

static void phase(int k)
{
    static const char *const says[4] = { "", "PHASE 1: INVASION", "PHASE 2: MONSTER X", "PHASE 3: GHIDORAH" };
    static const unsigned secs[4] = { 0, P1_SECONDS, P2_SECONDS, P3_SECONDS };
    run.phase = k;
    run.adds = 0;
    kit_timer_set(&run.clock, secs[k], 1);
    if (k == 1) {
        run.p1_left = N_P1;
        run.p1_done = 0;
    }
    if (k == 2) {
        run.p2_hits = 0;
        run.p2_lit = next_random(N_P2);
        run.p2_moved = pm_ms();
    }
    kit_screen_flash(&screen, 2000, says[k]);
    sound(CUE_PHASE);
    pm_log("PHASE %d (%s): %u s%s%s", k, says[k] + 9, secs[k], k == 2 ? ", lit " : "", k == 2 ? P2[run.p2_lit].shot : "");
    show();
}

/* ---- start and end ---------------------------------------------------------------------------- */
static int start(const char *why)
{
    const char *what = "";
    unsigned p = pm_player(), k;
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_stock_busy(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL, MODE_NAME, &what)) {
        pm_log("not started (%s): %s is running - still lit, the next %s after it starts it", why, what, START_SHOT);
        return 0;
    }
    if (!kit_begin(MODE_NAME)) return 0;
    kit_display(KIT_DISPLAY_WIZARD);              /* first: before the screen and the clip */
    run.on = 1;
    run.player = p;
    run.total = 0;
    lit[p] = 0;
    lit_note_at = 0;
    for (k = 0; k < KIT_LEDGER_MODES; k++) kit_ledger.played[p][k] = kit_ledger.won[p][k] = 0;
    kit_screen_show(&screen, 1);
    sound(CUE_START);
    pm_log("START (%s): player %u, score %llu - the qualification is used up", why, p, (unsigned long long)pm_score(p));
    phase(1);
    return 1;
}

static void end(const char *why, int won)
{
    char a[KIT_WORDS], n[24];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);                         /* every insert back to the game, at once */
    kit_end();
    sound(CUE_END);
    pm_snprintf(a, sizeof a, "TOTAL %s", kit_num(n, sizeof n, run.total));
    kit_screen_status(&screen, a, won ? "GODZILLA WINS" : "THE XILIENS WIN");
    screen.flash[0] = 0;
    kit_screen_hide_in(&screen, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s in phase %d, total %llu, score %llu", why, won ? "WON" : "not won", run.phase,
           (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

/* ---- shots -------------------------------------------------------------------------------------- */
static void add_time(uint64_t shot)
{
    unsigned i;
    for (i = 0; i < 3; i++) {
        uint64_t m = pm_shot(SHIELDS[i]);
        if (!m || !(shot & m) || !kit_fresh(&db, m)) continue;
        if (run.adds >= ADDS_PER_PHASE) {
            pm_log("%s: no more add-time this phase", SHIELDS[i]);
            return;
        }
        run.adds++;
        kit_timer_add(&run.clock, ADD_SECONDS);
        pm_log("ADD TIME: %s +%d s (%u of %d this phase), %u s left", SHIELDS[i], ADD_SECONDS, run.adds,
               ADDS_PER_PHASE, kit_timer_seconds(&run.clock));
        kit_screen_flash(&screen, 1000, "SHIELDS +3 SEC");
        sound(CUE_ADD_TIME);
        return;
    }
}

static void war_shot(uint64_t shot)
{
    char line[KIT_WORDS], n[24];
    unsigned i;
    uint64_t got;
    add_time(shot);
    if (run.phase == 1) {
        for (i = 0; i < N_P1; i++) {
            if (!p1_mask[i] || !(shot & p1_mask[i]) || !kit_fresh(&db, p1_mask[i])) continue;
            if (run.p1_done & (1u << i)) {
                pm_log("phase 1: %s is already saved", P1[i].shot);
                continue;
            }
            run.p1_done |= 1u << i;
            run.p1_left--;
            got = pay(P1_PAYS);
            pm_log("phase 1: %s +%llu, %u left", P1[i].shot, (unsigned long long)got, run.p1_left);
            pm_snprintf(line, sizeof line, "%s SAVED", P1[i].says);
            kit_screen_flash(&screen, 1200, line);
            sound(CUE_HIT);
            if (!run.p1_left) {
                phase(2);
                return;
            }
        }
        show();
        return;
    }
    if (run.phase == 2) {
        for (i = 0; i < N_P2; i++) {
            if (!p2_mask[i] || !(shot & p2_mask[i]) || !kit_fresh(&db, p2_mask[i])) continue;
            if (i != run.p2_lit) {
                pm_log("phase 2: %s is not the lit one (%s)", P2[i].shot, P2[run.p2_lit].shot);
                continue;
            }
            run.p2_hits++;
            got = pay(P2_PAYS * run.p2_hits);
            pm_log("phase 2: MONSTER X hit at %s, %u of %d, +%llu", P2[i].shot, run.p2_hits, P2_HITS,
                   (unsigned long long)got);
            if (run.p2_hits >= P2_HITS) {
                phase(3);
                return;
            }
            pm_snprintf(line, sizeof line, "MONSTER X HIT %u", run.p2_hits);
            kit_screen_flash(&screen, 1200, line);
            sound(CUE_HIT);
            run.p2_lit = (run.p2_lit + 1 + next_random(N_P2 - 1)) % N_P2;   /* it moves at once */
            run.p2_moved = pm_ms();
            pm_log("phase 2: MONSTER X moves -> %s", P2[run.p2_lit].shot);
            show();
            return;
        }
        return;
    }
    if (start_mask && (shot & start_mask) && kit_fresh(&db, start_mask)) {
        uint64_t asked = wizard_value();
        got = pay(asked);
        pm_log("WIZARD JACKPOT: %s with %u s left, +%llu (asked %llu)", START_SHOT, kit_timer_seconds(&run.clock),
               (unsigned long long)got, (unsigned long long)asked);
        pm_snprintf(line, sizeof line, "WIZARD %s", kit_num(n, sizeof n, got));
        kit_screen_flash(&screen, 2500, line);
        sound(CUE_WIZARD);
        end("wizard jackpot", 1);
    }
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    start_mask = pm_shot(START_SHOT);
    for (i = 0; i < N_P1; i++) p1_mask[i] = pm_shot(P1[i].shot);
    for (i = 0; i < N_P2; i++) p2_mask[i] = pm_shot(P2[i].shot);
    for (i = 0; i < 3; i++) shield_mask |= pm_shot(SHIELDS[i]);
    ball_start_event = pm_event("ball_start");
    rnd ^= (unsigned)pm_ms();
    pa_load(&own);
    pm_log("ready on %s %s: lit by the pack's ledger, starts at %s (0x%llx); phase 1 0x%llx 0x%llx 0x%llx, "
           "phase 2 0x%llx 0x%llx 0x%llx 0x%llx, add time 0x%llx", pm_game(), pm_version(), START_SHOT,
           (unsigned long long)start_mask, (unsigned long long)p1_mask[0], (unsigned long long)p1_mask[1],
           (unsigned long long)p1_mask[2], (unsigned long long)p2_mask[0], (unsigned long long)p2_mask[1],
           (unsigned long long)p2_mask[2], (unsigned long long)p2_mask[3], (unsigned long long)shield_mask);
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    if (!pm_in_game() || p < 1 || p > 4) return;
    between_balls = 0;                    /* a ball is in play */
    if (!run.on) {
        if (lit[p] && start_mask && (shot & start_mask) && kit_fresh(&db, start_mask)) start(START_SHOT);
        return;
    }
    if (p == run.player) war_shot(shot);
}

static void check_triggers(void)
{
    char name[48];
    unsigned p = pm_player();
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file", 0);
    if (pm_trigger(FOLDER ".light") && p >= 1 && p <= 4) light(p, "trigger file");
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
    if (++poll % KIT_POLL == 0) {
        check_triggers();
        qualify_watch();
    }
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) {
            unsigned k;
            lit[p] = 0;
            for (k = 0; k < KIT_LEDGER_MODES; k++) kit_ledger.played[p][k] = kit_ledger.won[p][k] = 0;
        }
        lit_note_at = 0;
        pm_log("new game: the ledger and FINAL WARS's light cleared");
    }
    if (lit_note_at && !run.on && pm_ms() >= lit_note_at) {
        p = pm_player();
        if (!kit_running && p >= 1 && p <= 4 && lit[p] && kit_screen_note(&screen, 3000, "FINAL WARS IS LIT"))
            lit_note_at = 0;              /* otherwise another screen is up: try again next tick */
    }
    if (!run.on) {
        idle_lamps();
        return;
    }
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on", 0);
        return;
    }
    if (kit_timer_tick(&run.clock)) {
        sound(CUE_TIME_UP);
        end("a phase's clock ran out", 0);
        return;
    }
    if (run.phase == 2 && pm_ms() - run.p2_moved >= P2_MOVE_MS) {
        unsigned was = run.p2_lit;
        run.p2_lit = (run.p2_lit + 1 + next_random(N_P2 - 1)) % N_P2;
        run.p2_moved = pm_ms();
        pm_log("phase 2: MONSTER X moves %s -> %s", P2[was].shot, P2[run.p2_lit].shot);
        sound(CUE_MOVE);
    }
    show();
}

static void on_ball_end(void)
{
    end("ball ended", 0);
    between_balls = 1;
    idle_lamps();                          /* the lit Building goes dark with the ball */
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) {
        end("tilted", 0);                  /* its lights go dark with the game's */
        between_balls = 1;
        idle_lamps();
    }
    if (ball_start_event >= 0 && (int)id == ball_start_event) between_balls = 0;
}

static const struct pm_mode final_wars = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(final_wars);
