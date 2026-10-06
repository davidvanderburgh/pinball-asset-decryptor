/* oxygen_destroyer.c - OXYGEN DESTROYER: a HURRY-UP with a super jackpot, for Godzilla (item 152).
 *
 * Dr. Serizawa's weapon (Godzilla, 1954). Its value drains away in real time: collect it
 * before it is gone, then deliver it for double.
 *
 *   START      Spin the LEFT SPINNER 25 times in one ball (hud-layers: it used to be the Godzilla
 *              target 3 times, which MELTDOWN's ten captive-ball hits would always set off first).
 *              Up to 3 times a game per player, and not again for 15 s after it ends (25 fresh spins
 *              every time). It waits out a multiball (the game's, or two balls in play) and stays
 *              ready: the next spin after it starts it (PAD-347). Beside the game's battles and timed
 *              modes it runs, its words aside (a hurry-up only adds points).
 *   HURRY-UP   The value starts at 20,000,000 and falls 800,000 every second, down to 0 at
 *              25 s. The LEFT RAMP collects it. The Godzilla target holds it off: each hit
 *              puts 2 seconds (1,600,000) back, up to 20,000,000, three times at most.
 *   SUPER      Collecting lights the RIGHT RAMP for 12 s: the super jackpot, worth DOUBLE
 *              what was collected. Miss it and the mode ends with what was collected.
 *   ENDS       Delivered (the super jackpot), or the super jackpot runs out, or the value
 *              reaches 0 before it was collected (LOST: nothing), or the ball drains, or the
 *              ball is tilted. The screen shows the total.
 *   INSERTS    The LEFT RAMP (collect) blinks green, then yellow, then red as the value falls,
 *              faster and faster (a flicker in its last 3 s). The Godzilla target's insert
 *              (MAGNA GRAB) PULSES while a hold-off is left. Collected: those two go back to the
 *              game and the RIGHT RAMP flashes white for the super jackpot (faster in its last
 *              3 s). Everything is handed back the moment the mode ends, however it ends.
 *   DISPLAY    Priority 180 (the game's full-screen shot awards are not shown over it; its
 *              jackpots, starts and the tilt warning come through).
 *   THE GLASS  (hud-layers) The canister on the sea bed full screen as it starts, then the murky
 *              depths looping BEHIND the score panel. At the edges: the falling value as the big
 *              counter, the OXYGEN badge counting its seconds, and the oxygen gauge on the right
 *              draining segment by segment. The collect plays the bubbles erupting behind the HUD;
 *              the ending is full screen (Godzilla dissolving, or surging out of the sea).
 *   LIGHTS     Its own shows: bubbles rising up the playfield in blue at the start; delivered, a
 *              white flash dissolving into a slow blue fade; lost, a blue wash draining away.
 *
 * Emulator test triggers: /dump/oxygen_destroyer.start, .stop, .shot "<shot name>".
 */
#include "intricate_kit.h"

/* PAD-411: the game's own light shows at its start (flashy) and its end (subdued): the Oxygen Destroyer sinks: an ocean-blue fade */
#define GAME_SHOW_START "Colour sweep"
#define GAME_SHOW_END   "Blue fade"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "OXYGEN DESTROYER"
#define FOLDER             "oxygen_destroyer"
#define START_SHOT         "Godzilla target"   /* the hold-off (the captive ball); it no longer starts it */
#define SPIN_SHOT          "Left spinner"
#define HITS_TO_START      25                  /* spins, each one counted (a spinner shot is many spins) */
#define STARTS_PER_GAME    3
#define COOLDOWN_MS        15000
#define VALUE_START        20000000ull
#define VALUE_PER_SECOND   800000ull       /* 0 after 25 s */
#define HOLD_OFF_MS        2000            /* a Godzilla target hit puts this much time back */
#define HOLD_OFFS          3
#define COLLECT_SHOT       "Left ramp"
#define SUPER_SHOT         "Right ramp"
#define SUPER_SECONDS      12
#define TOTAL_SHOWN_MS     10000          /* the ending clip (5 s) full screen, then the total */
#define GAUGE_PIPS         10

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t start_mask, collect_mask, super_mask, spin_mask;
static unsigned hits[5], ran_game[5];
static unsigned long ended_at[5];         /* pm_ms() + 1 of the last end, per player; 0 = none */
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;

/* ---- light shows (hud-layers): unique to OXYGEN DESTROYER, the deep sea's blues ------------------- */
#define OXY_DEEP       PM_RGB(0, 20, 70)
#define OXY_AQUA       PM_RGB(60, 220, 255)
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_SPARKLE,   900, OXY_AQUA, OXY_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },      /* the sea bed */
    { KIT_FX_SWEEP_UP,  900, KIT_WHITE, OXY_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },     /* bubbles rise */
    { KIT_FX_SWEEP_UP,  800, OXY_AQUA, OXY_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_PULSE,     900, OXY_AQUA, OXY_DEEP, KIT_AT_CENTER, 220, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_WON[] = {
    { KIT_FX_STROBE,    400, KIT_WHITE, 0, KIT_AT_CENTER, 60, KIT_GI_FLASH },           /* the device fires */
    { KIT_FX_BURST,     900, KIT_WHITE, OXY_AQUA, KIT_AT_MAGNA, 0, KIT_GI_DARK },
    { KIT_FX_SPARKLE,  1200, KIT_WHITE, OXY_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },      /* he dissolves */
    { KIT_FX_FADE_OUT,  900, OXY_AQUA, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_LOST[] = {
    { KIT_FX_SWEEP_DOWN, 900, OXY_AQUA, OXY_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },     /* the oxygen drains */
    { KIT_FX_PULSE,      900, KIT_RED, 0, KIT_AT_CENTER, 300, KIT_GI_DARK },
    { KIT_FX_FADE_OUT,   600, OXY_DEEP, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_STEPS(a) (int)(sizeof (a) / sizeof (a)[0])
static unsigned poll;

enum { PHASE_HURRY, PHASE_SUPER };
static struct {
    int on, phase;
    unsigned player, hold_offs;
    unsigned long drained_ms, last_ms;    /* how long the value has been draining; the last tick */
    unsigned said;                        /* the seconds last spoken for */
    uint64_t collected, total;
    struct kit_timer super_clock;
} run;

/* ---- sound: the one place the mode's own clip, music and calls are played --------------------------
 * From modes/oxygen_destroyer/assets.json through oxygen_destroyer.assets (pad_mode_assets.h). */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_START, CUE_HOLD_OFF, CUE_COLLECT, CUE_SUPER, CUE_LOST, CUE_TIME_UP, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:   pa_start(&own); break;                     /* its music, its intro, then the loop */
    case CUE_COLLECT:                                            /* the hurry-up collected */
        pa_call(&own, "collect");
        pa_clip_event(&own, "collect");
        break;
    case CUE_SUPER:   pa_call(&own, "won"); break;               /* the super jackpot delivered */
    case CUE_LOST:                                               /* the value ran out: LOST */
    case CUE_TIME_UP:                                            /* the super jackpot ran out */
        if (!pa_call(&own, "lost")) pm_callout(pm_callout_id("time_up"));
        break;
    case CUE_END:     pa_end(&own); break;
    default: break;                                              /* a hold-off */
    }
}

/* ---- the value ------------------------------------------------------------------------------------- */
static uint64_t value_now(void)
{
    uint64_t gone = VALUE_PER_SECOND * run.drained_ms / 1000u;
    uint64_t v = gone >= VALUE_START ? 0 : VALUE_START - gone;
    return v / 10000u * 10000u;           /* shown and paid in tens of thousands */
}

static unsigned seconds_left(void)
{
    uint64_t v = value_now();
    return (unsigned)((v + VALUE_PER_SECOND - 1) / VALUE_PER_SECOND);
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

/* the inserts for the hurry-up as it stands; every tick, only a change is sent */
static void show_lamps(void)
{
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_SUPER) {
        kit_lamps_shot(&lamps, super_mask, KIT_WHITE, PM_LAMP_BLINK, kit_timer_seconds(&run.super_clock) > 3 ? 150 : 80);
    } else {
        uint64_t v = value_now();
        unsigned rgb = v * 3 > VALUE_START * 2 ? KIT_GREEN : v * 3 > VALUE_START ? KIT_YELLOW : KIT_RED;
        kit_lamps_shot(&lamps, collect_mask, rgb, PM_LAMP_BLINK,
                       kit_hurry_ms((unsigned long)(v * 1000u / VALUE_PER_SECOND), VALUE_START * 1000u / VALUE_PER_SECOND));
        if (run.hold_offs < HOLD_OFFS && start_mask != collect_mask)
            kit_lamps_shot(&lamps, start_mask, KIT_WHITE, PM_LAMP_PULSE, 1000);    /* a hold-off is left */
    }
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char n[24], sub[24];
    uint64_t v;
    int pips;
    show_lamps();
    if (run.phase == PHASE_SUPER) {
        kit_hud_title(&hud, "OXYGEN DESTROYER", "SUPER JACKPOT: SHOOT THE RIGHT RAMP");
        kit_hud_counter(&hud, 0, "COLLECTED", kit_short(n, sizeof n, run.collected), " ");
        kit_hud_counter(&hud, 1, "SUPER JACKPOT", kit_short(sub, sizeof sub, 2 * run.collected), "RIGHT RAMP");
        kit_hud_counter(&hud, 2, 0, 0, 0);
        kit_hud_timer(&hud, (int)kit_timer_seconds(&run.super_clock));
        kit_hud_gauge(&hud, GAUGE_PIPS, "DOUBLE");
        return;
    }
    v = value_now();
    kit_hud_title(&hud, "OXYGEN DESTROYER", run.hold_offs < HOLD_OFFS ? "LEFT RAMP COLLECTS  -  CAPTIVE BALL HOLDS"
                                                                      : "SHOOT THE LEFT RAMP");
    pm_snprintf(sub, sizeof sub, "%u HOLD-OFF%s LEFT", HOLD_OFFS - run.hold_offs, HOLD_OFFS - run.hold_offs == 1 ? "" : "S");
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, "HURRY-UP", kit_short(n, sizeof n, v), sub);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, (int)seconds_left());
    pips = (int)((v * GAUGE_PIPS + VALUE_START - 1) / VALUE_START);          /* the oxygen left */
    kit_hud_gauge(&hud, pips, "OXYGEN");
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
    if (counted && kit_wait_game(MODE_NAME, why, "the next spin after it starts it")) return 0;   /* PAD-347 */
    if (!kit_begin(MODE_NAME)) return 0;
    kit_display(KIT_DISPLAY_MODE);                /* first: before the screen and the clip */
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);   /* PAD-347/363: the game's modes wait for it */
    run.on = 1;
    run.player = p;
    run.phase = PHASE_HURRY;
    run.hold_offs = 0;
    run.drained_ms = 0;
    run.last_ms = pm_ms();
    run.said = 0;
    run.collected = run.total = 0;
    hits[p] = 0;
    if (counted) ran_game[p]++;
    kit_ledger_note(KIT_OXYGEN, p, 0);
    kit_hud_begin(&hud, "OXYGEN DESTROYER", "");
    show();
    kit_hud_award(&hud, 2500, "OXYGEN DESTROYER", "COLLECT IT BEFORE IT IS GONE");
    if (!kit_game_show(GAME_SHOW_START, "its start")) kit_show_start(&show_fx, "oxygen start", SHOW_START, N_STEPS(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, the value %llu falls %llu a second; collect at %s; start %u this game, "
           "score %llu", why, p, (unsigned long long)VALUE_START, (unsigned long long)VALUE_PER_SECOND,
           COLLECT_SHOT, ran_game[p], (unsigned long long)pm_score(p));
    return 1;
}

static void end(const char *why, int won)
{
    char a[KIT_WORDS], n[24];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);                         /* every insert back to the game, at once */
    kit_end_after(TOTAL_SHOWN_MS);      /* the ending clip and the total keep the screen */
    ended_at[run.player] = pm_ms() + 1;
    kit_ledger_note(KIT_OXYGEN, run.player, won);
    sound(CUE_END);
    pa_clip_full(&own, won ? "won" : "lost");      /* the ending, full screen */
    if (!kit_game_show(GAME_SHOW_END, "its end")) {
        kit_show_start(&show_fx, won ? "oxygen won" : "oxygen lost", won ? SHOW_WON : SHOW_LOST,
                       won ? N_STEPS(SHOW_WON) : N_STEPS(SHOW_LOST));
    }
    pm_snprintf(a, sizeof a, "%s", kit_num(n, sizeof n, run.total));
    kit_hud_title(&hud, won ? "GODZILLA IS GONE" : run.collected ? "OXYGEN DESTROYER" : "THE OXYGEN IS GONE", " ");
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, a, "OXYGEN DESTROYER TOTAL");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, collected %llu, total %llu, score %llu", why, won ? "WON" : "not won",
           (unsigned long long)run.collected, (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    start_mask = pm_shot(START_SHOT);
    spin_mask = pm_shot(SPIN_SHOT);
    if (!spin_mask) pm_log("this port has no \"%s\": only the start trigger starts it", SPIN_SHOT);
    collect_mask = pm_shot(COLLECT_SHOT);
    super_mask = pm_shot(SUPER_SHOT);
    if (!start_mask) pm_log("this port has no \"%s\": only the start trigger starts it", START_SHOT);
    if (!collect_mask || !super_mask) pm_log("this port lacks \"%s\" or \"%s\"", COLLECT_SHOT, SUPER_SHOT);
    pa_load(&own);
    pm_log("ready on %s %s: starts on %s x%d (0x%llx); hold-off %s (0x%llx); collect 0x%llx, super 0x%llx", pm_game(),
           pm_version(), SPIN_SHOT, HITS_TO_START, (unsigned long long)spin_mask, START_SHOT,
           (unsigned long long)start_mask, (unsigned long long)collect_mask, (unsigned long long)super_mask);
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_WORDS];
    unsigned long since;
    if (!spin_mask || !(shot & spin_mask)) return;        /* every spin counts: no debounce */
    if (ran_game[p] >= STARTS_PER_GAME) {
        if (hits[p] == 0) pm_log("%s: not counted - it already ran %d times this game", SPIN_SHOT, STARTS_PER_GAME);
        return;
    }
    if (ended_at[p]) {
        since = pm_ms() - (ended_at[p] - 1);
        if (since < COOLDOWN_MS) {
            pm_log("%s: not counted - cooling down, %lu s left", SPIN_SHOT, (COOLDOWN_MS - since + 999) / 1000);
            return;
        }
    }
    if (hits[p] < HITS_TO_START) hits[p]++;
    if (hits[p] % 5 == 0 || hits[p] >= HITS_TO_START) pm_log("%s %u of %d (player %u)", SPIN_SHOT, hits[p], HITS_TO_START, p);
    if (hits[p] >= HITS_TO_START) {
        start("the left spinner", 1);
    } else if (!kit_running) {
        pm_snprintf(line, sizeof line, "%u SPIN%s TO GO", HITS_TO_START - hits[p],
                    HITS_TO_START - hits[p] == 1 ? "" : "S");
        kit_hud_note(&hud, 1500, line, "OXYGEN DESTROYER");
    }
}

static void hurry_shot(uint64_t shot)
{
    char line[KIT_WORDS], n[24];
    if (start_mask && (shot & start_mask) && kit_fresh(&db, start_mask)) {
        if (run.hold_offs >= HOLD_OFFS) {
            pm_log("%s: no more hold-offs (%d used)", START_SHOT, HOLD_OFFS);
        } else {
            run.hold_offs++;
            run.drained_ms = run.drained_ms > HOLD_OFF_MS ? run.drained_ms - HOLD_OFF_MS : 0;
            pm_log("%s: hold-off %u of %d, the value is back to %llu", START_SHOT, run.hold_offs, HOLD_OFFS,
                   (unsigned long long)value_now());
            kit_hud_award(&hud, 1200, "HELD OFF", "+2 SECONDS");
            sound(CUE_HOLD_OFF);
        }
    }
    if (collect_mask && (shot & collect_mask) && kit_fresh(&db, collect_mask)) {
        uint64_t v = value_now();
        run.collected = pay(v);
        pm_log("COLLECTED at %s: %llu (asked %llu) after %lu ms; super jackpot %llu lit at %s for %u s",
               COLLECT_SHOT, (unsigned long long)run.collected, (unsigned long long)v, run.drained_ms,
               (unsigned long long)(2 * run.collected), SUPER_SHOT, SUPER_SECONDS);
        run.phase = PHASE_SUPER;
        kit_timer_set(&run.super_clock, SUPER_SECONDS, 1);
        pm_snprintf(line, sizeof line, "SUPER %s AT THE RIGHT RAMP", kit_num(n, sizeof n, 2 * run.collected));
        kit_hud_award(&hud, 2500, "COLLECTED", line);
        sound(CUE_COLLECT);
        show();
    }
}

static void super_shot(uint64_t shot)
{
    char line[KIT_WORDS], n[24];
    uint64_t asked, got;
    if (!super_mask || !(shot & super_mask) || !kit_fresh(&db, super_mask)) return;
    asked = 2 * run.collected;
    got = pay(asked);
    pm_log("SUPER JACKPOT at %s: +%llu (asked %llu) with %u s left", SUPER_SHOT, (unsigned long long)got,
           (unsigned long long)asked, kit_timer_seconds(&run.super_clock));
    (void)line;
    (void)n;
    sound(CUE_SUPER);
    end("super jackpot", 1);
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    if (!pm_in_game() || p < 1 || p > 4) return;
    if (!run.on) {
        qualify_shot(shot, p);
        return;
    }
    if (p != run.player) return;
    if (run.phase == PHASE_HURRY) hurry_shot(shot);
    else super_shot(shot);
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file", 0);
    if (pm_trigger(FOLDER ".stop")) end("trigger file", 0);
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void on_tick(void)
{
    unsigned p, s;
    unsigned long now, d;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) check_triggers();
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) hits[p] = ran_game[p] = 0, ended_at[p] = 0;
        pm_log("new game: counts and cooldowns cleared");
    }
    if (!run.on) return;
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on", 0);
        return;
    }
    if (kit_game_began()) {                        /* PAD-347: isolated - the game began one of its own */
        end("the game's own mode began", 0);
        kit_end_now();
        return;
    }
    if (run.phase == PHASE_SUPER) {
        if (kit_timer_tick(&run.super_clock)) {
            sound(CUE_TIME_UP);
            end("the super jackpot ran out", 0);
            return;
        }
        show();
        return;
    }
    now = pm_ms();                        /* real time; a stalled frame drains at most 100 ms */
    d = now - run.last_ms;
    run.last_ms = now;
    run.drained_ms += d > 100 ? 100 : d;
    s = seconds_left();
    if (s != run.said) {
        run.said = s;
        if (s == 10) pm_callout(pm_callout_id("ten_seconds"));
        if (s >= 1 && s <= 5) pm_callout_nth(pm_callout_id("countdown"), s - 1);
    }
    if (value_now() == 0) {
        sound(CUE_LOST);
        end("the value ran out before it was collected", 0);
        return;
    }
    show();
}

static void on_ball_end(void)
{
    unsigned p;
    end("ball ended", 0);
    kit_end_now();
    for (p = 0; p < 5; p++) hits[p] = 0;
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) {
        end("tilted", 0);                          /* its lights go dark with the game's */
        kit_end_now();
    }
}

static const struct pm_mode oxygen_destroyer = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(oxygen_destroyer);
