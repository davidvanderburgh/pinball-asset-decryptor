/* oxygen_destroyer.c - OXYGEN DESTROYER: a HURRY-UP with a super jackpot, for Godzilla (item 152).
 *
 * Dr. Serizawa's weapon (Godzilla, 1954). Its value drains away in real time: collect it
 * before it is gone, then deliver it for double.
 *
 *   START      Hit the Godzilla target 3 times in one ball. Up to 3 times a game per player,
 *              and not again for 15 s after it ends (it needs 3 fresh hits every time). It
 *              runs beside anything the game is doing (a hurry-up only adds points).
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
 *   DISPLAY    Priority 180 (the game's full-screen shot awards are not shown over the panel;
 *              its jackpots, starts and the tilt warning come through, and the panel is back).
 *   LIGHTS     No light sweep: the port's example sweep recolours the inserts around the
 *              shots (measured, item 157), so it would make shots that pay nothing look lit.
 *   SCREEN     "LEFT RAMP 13,440,000" (the live value), then "SUPER RIGHT RAMP 9" alternating
 *              with the super jackpot's value.
 *
 * Emulator test triggers: /dump/oxygen_destroyer.start, .stop, .shot "<shot name>".
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "OXYGEN DESTROYER"
#define FOLDER             "oxygen_destroyer"
#define START_SHOT         "Godzilla target"
#define HITS_TO_START      3
#define STARTS_PER_GAME    3
#define COOLDOWN_MS        15000
#define VALUE_START        20000000ull
#define VALUE_PER_SECOND   800000ull       /* 0 after 25 s */
#define HOLD_OFF_MS        2000            /* a Godzilla target hit puts this much time back */
#define HOLD_OFFS          3
#define COLLECT_SHOT       "Left ramp"
#define SUPER_SHOT         "Right ramp"
#define SUPER_SECONDS      12
#define TOTAL_SHOWN_MS     6000

#define SCREEN_NODE "PadMode_" FOLDER "_Screen"
#define SCREEN_TEXT "PadMode_" FOLDER "_Screen.PadMode_" FOLDER "_Screen_Words"

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t start_mask, collect_mask, super_mask;
static unsigned hits[5], ran_game[5];
static unsigned long ended_at[5];         /* pm_ms() + 1 of the last end, per player; 0 = none */
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_screen screen = { .node_name = SCREEN_NODE, .text_name = SCREEN_TEXT, .alt_ms = 1500 };
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
    case CUE_START:   pa_start(&own); break;                     /* its music, its start clip */
    case CUE_COLLECT: pa_call(&own, "collect"); break;           /* the hurry-up collected */
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
    char a[KIT_WORDS], b[KIT_WORDS], n[24];
    uint64_t v;
    show_lamps();
    if (run.phase == PHASE_SUPER) {
        pm_snprintf(a, sizeof a, "SUPER RIGHT RAMP %u", kit_timer_seconds(&run.super_clock));
        pm_snprintf(b, sizeof b, "SUPER %s", kit_num(n, sizeof n, 2 * run.collected));
        kit_screen_status(&screen, a, b);
        return;
    }
    v = value_now();
    pm_snprintf(a, sizeof a, "LEFT RAMP %s", kit_num(n, sizeof n, v));
    kit_screen_status(&screen, a, 0);
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
    if (!kit_begin(MODE_NAME)) return 0;
    kit_display(KIT_DISPLAY_MODE);                /* first: before the screen and the clip */
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
    kit_screen_show(&screen, 1);
    show();
    kit_screen_flash(&screen, 1500, "OXYGEN DESTROYER");
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
    kit_end();
    ended_at[run.player] = pm_ms() + 1;
    kit_ledger_note(KIT_OXYGEN, run.player, won);
    sound(CUE_END);
    pm_snprintf(a, sizeof a, "TOTAL %s", kit_num(n, sizeof n, run.total));
    kit_screen_status(&screen, a, won ? "GODZILLA IS GONE" : run.collected ? "OXYGEN DESTROYER" : "LOST");
    screen.flash[0] = 0;
    kit_screen_hide_in(&screen, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, collected %llu, total %llu, score %llu", why, won ? "WON" : "not won",
           (unsigned long long)run.collected, (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    start_mask = pm_shot(START_SHOT);
    collect_mask = pm_shot(COLLECT_SHOT);
    super_mask = pm_shot(SUPER_SHOT);
    if (!start_mask) pm_log("this port has no \"%s\": only the start trigger starts it", START_SHOT);
    if (!collect_mask || !super_mask) pm_log("this port lacks \"%s\" or \"%s\"", COLLECT_SHOT, SUPER_SHOT);
    pa_load(&own);
    pm_log("ready on %s %s: starts on %s x%d (0x%llx); collect 0x%llx, super 0x%llx", pm_game(), pm_version(),
           START_SHOT, HITS_TO_START, (unsigned long long)start_mask, (unsigned long long)collect_mask,
           (unsigned long long)super_mask);
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_WORDS];
    unsigned long since;
    if (!start_mask || !(shot & start_mask) || !kit_fresh(&db, start_mask)) return;
    if (ran_game[p] >= STARTS_PER_GAME) {
        pm_log("%s: not counted - it already ran %d times this game", START_SHOT, STARTS_PER_GAME);
        return;
    }
    if (ended_at[p]) {
        since = pm_ms() - (ended_at[p] - 1);
        if (since < COOLDOWN_MS) {
            pm_log("%s: not counted - cooling down, %lu s left", START_SHOT, (COOLDOWN_MS - since + 999) / 1000);
            return;
        }
    }
    if (hits[p] < HITS_TO_START) hits[p]++;
    pm_log("%s %u of %d (player %u)", START_SHOT, hits[p], HITS_TO_START, p);
    if (hits[p] >= HITS_TO_START) {
        start("Godzilla target", 1);
    } else if (!kit_running) {
        pm_snprintf(line, sizeof line, "DESTROYER %u OF %d", hits[p], HITS_TO_START);
        kit_screen_note(&screen, 2000, line);
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
            kit_screen_flash(&screen, 1000, "HELD OFF +2 SEC");
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
        pm_snprintf(line, sizeof line, "COLLECTED %s", kit_num(n, sizeof n, run.collected));
        kit_screen_flash(&screen, 2000, line);
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
    pm_snprintf(line, sizeof line, "SUPER %s", kit_num(n, sizeof n, got));
    kit_screen_flash(&screen, 2500, line);
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
    kit_screen_tick(&screen);
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
    for (p = 0; p < 5; p++) hits[p] = 0;
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) end("tilted", 0);        /* its lights go dark with the game's */
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
