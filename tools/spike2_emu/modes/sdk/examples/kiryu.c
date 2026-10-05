/* kiryu.c - KIRYU: charge the ABSOLUTE ZERO, then fire it or push your luck (PAD-379, for Godzilla).
 * Modelled on Lyman Sheats' risk and reward: Metallica's Sparky (a meter the shots fill, each start costing
 * more hits) and Crank It Up's cash out or carry on, Batman '66's cash the super now or take +1x.
 *
 * Godzilla Against Mechagodzilla (2002): Kiryu, the Mechagodzilla built on the 1954 Godzilla's bones, carries
 * the Absolute Zero cannon. It has to charge, and it can run too hot.
 *
 *   LIGHT IT   Spin the MECHAGODZILLA spinner (the shield ramp's) 30 times; every spin counts. It starts at
 *              once. The next time it takes 40 spins, then 50...
 *   CHARGE     A 40 s clock. The lit shots charge the cannon: the RAMPS, the BUILDING and the BIG LOOP 15%
 *              each, the MASER 10%, each SHIELD target 8%, every spin of the Mechagodzilla spinner 1%. Each
 *              shot pays 750,000. A lit shot with under 15 s left puts the clock back to 15.
 *   FIRE       From 100% ABSOLUTE ZERO is READY: the CAPTIVE BALL (Godzilla) or the ACTION BUTTON fires it:
 *              10,000,000 times the multiplier, plus a quarter of everything the mode has scored. Firing
 *              ends the mode: KIRYU WINS.
 *   PUSH IT    Charge on instead: 200% is x2, 300% x3, 400% x4 (the most). From 200% the reactor OVERHEATS:
 *              12 s to fire, and each 100% more gives 12 s again. Run out and Kiryu VENTS: the charge falls
 *              to 0 and the multiplier with it - charge again from the start, the clock still running.
 *   ENDS       Fired; the clock (at 100% or more Kiryu fires on its own at x1 with no bonus; under it, the
 *              charge is lost); a drain; a tilt; one of the game's own modes beginning.
 *   THE GLASS  Kiryu activated, full screen; Kiryu over the city behind the score panel; CHARGE, ABSOLUTE
 *              ZERO and MULTIPLIER at the edges, the charge on the right edge's gauge, the clock in the badge
 *              (the overheat's seconds while it overheats). Each 100% plays the cannon charging, an overheat
 *              Kiryu sparking; the shot and the endings are full screen.
 *   INSERTS    The charging shots ice blue; ready: the CAPTIVE BALL (MAGNA GRAB) and the ACTION BUTTON
 *              flashing white; overheating: flashing red, faster as the seconds run out.
 *   DISPLAY    Priority 180.
 *
 * Emulator test triggers: /dump/kiryu.start, .stop, .shot "<shot name>", .charge "<percent>" (set the charge).
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "KIRYU"
#define FOLDER             "kiryu"
#define SPIN_SHOT          "Shield ramp spinner"
#define FIRE_SHOT          "Godzilla target"
#define BUTTON_SHOT        "Action button"
#define SPINS_FIRST        30
#define SPINS_STEP         10
#define RUN_SECONDS        40
#define LIT_SHOT_FLOOR     15
#define SHOT_VALUE         750000ull
#define SPIN_VALUE         10000ull
#define CHARGE_MAX         400
#define OVERHEAT_FROM      200
#define OVERHEAT_SECONDS   12
#define FIRE_VALUE         10000000ull
#define FIRE_SHARE         4               /* a quarter of the mode's points rides the shot */
#define FIRED_MS           4000            /* the shot's moment, then the ending */
#define TOTAL_SHOWN_MS     10000

#define N_CHARGE 8
static const struct { const char *shot; unsigned pct; } CHARGE[N_CHARGE] = {
    { "Left ramp", 15 }, { "Right ramp", 15 }, { "Building", 15 }, { "Big loop", 15 }, { "Maser target", 10 },
    { "Shield target left", 8 }, { "Shield target center", 8 }, { "Shield target right", 8 },
};

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t charge_mask[N_CHARGE], all_charge, spin_mask, fire_mask, button_mask;
static unsigned spins[5], plays[5];
static int waiting[5];                       /* lit while one of the game's modes ran: the next spin starts it */
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;
static unsigned poll;

enum { PHASE_CHARGE, PHASE_FIRED };
static struct {
    int on, phase, fired, vents;
    unsigned player, charge, mult;
    uint64_t scored, total, shot_paid;
    unsigned long fired_at;
    struct kit_timer clock, heat;
} run;

/* ---- light shows: ice and steel -------------------------------------------------------------- */
#define KY_ICE         PM_RGB(140, 220, 255)
#define KY_STEEL       PM_RGB(20, 40, 70)
#define KY_HOT         PM_RGB(255, 40, 0)
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_SWEEP_UP,  700, KIT_WHITE, KY_STEEL, KIT_AT_CENTER, 0, KIT_GI_DARK },      /* the systems come on */
    { KIT_FX_CHASE_RING, 900, KY_ICE, KY_STEEL, KIT_AT_CENTER, 70, KIT_GI_DARK },
    { KIT_FX_PULSE,     600, KY_ICE, KY_STEEL, KIT_AT_CENTER, 150, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  300, KY_ICE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_CHARGE[] = {    /* each 100% */
    { KIT_FX_IMPLODE,   600, KIT_WHITE, KY_ICE, KIT_AT_MAGNA, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_FIRE[] = {      /* ABSOLUTE ZERO */
    { KIT_FX_STROBE,    400, KIT_WHITE, KY_ICE, KIT_AT_CENTER, 40, KIT_GI_FLASH },
    { KIT_FX_BURST,     900, KIT_WHITE, KY_ICE, KIT_AT_MAGNA, 0, KIT_GI_FLASH },
    { KIT_FX_SPARKLE,  1500, KIT_WHITE, KY_ICE, KIT_AT_CENTER, 0, KIT_GI_KEEP },      /* frost */
    { KIT_FX_FADE_OUT,  700, KY_ICE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_VENT[] = {
    { KIT_FX_STROBE,    500, KY_HOT, 0, KIT_AT_CENTER, 70, KIT_GI_FLASH },
    { KIT_FX_FADE_OUT,  500, KY_HOT, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_END[] = {
    { KIT_FX_SWEEP_DOWN, 800, KY_ICE, KY_STEEL, KIT_AT_TOP, 0, KIT_GI_DARK },          /* power down */
    { KIT_FX_FADE_OUT,  900, KY_STEEL, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_SHOW(a) (int)(sizeof (a) / sizeof (a)[0])

/* ---- sound: its own music, calls and clips (modes/kiryu/assets.json) --------------------------- */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_START, CUE_CHARGE, CUE_READY, CUE_FIRE, CUE_OVERHEAT, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:    pa_start(&own); break;                     /* the march, Kiryu online, Kiryu over the city */
    case CUE_CHARGE:                                              /* another 100% */
        pa_call(&own, "charge");
        pa_clip_event(&own, "charge");
        break;
    case CUE_READY:                                               /* ABSOLUTE ZERO READY */
        pa_call(&own, "ready");
        pa_clip_event(&own, "ready");
        break;
    case CUE_FIRE:
        pa_call(&own, "fire");
        pa_clip_full(&own, "fire");
        break;
    case CUE_OVERHEAT:
        pa_call(&own, "overheat");
        pa_clip_event(&own, "overheat");
        break;
    case CUE_END:      pa_end(&own); break;
    }
}

static unsigned spins_needed(unsigned p) { return SPINS_FIRST + SPINS_STEP * plays[p]; }

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    run.scored += got;
    return got;
}

static unsigned mult_of(unsigned charge) { return charge < 100 ? 0 : charge / 100; }

static uint64_t fire_value(int bonus)
{
    unsigned m = run.mult ? run.mult : 1;
    return FIRE_VALUE * m + (bonus ? run.scored / FIRE_SHARE : 0);
}

/* ---- the glass and the inserts ------------------------------------------------------------------------ */
static void show_lamps(void)
{
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_CHARGE) {
        if (run.charge < CHARGE_MAX) kit_lamps_shot(&lamps, all_charge, KY_ICE, PM_LAMP_SOLID, 0);
        if (run.mult) {
            uint64_t fire = fire_mask | button_mask;
            if (run.heat.ticks)
                kit_lamps_shot(&lamps, fire, KY_HOT, PM_LAMP_BLINK,
                               kit_hurry_ms((unsigned long)kit_timer_seconds(&run.heat) * 1000u, OVERHEAT_SECONDS * 1000u));
            else
                kit_lamps_shot(&lamps, fire, KIT_WHITE, PM_LAMP_BLINK, 300);
        }
    }
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char c[16], v[24], m[16], sub[24];
    show_lamps();
    if (run.phase == PHASE_FIRED) return;
    kit_hud_title(&hud, "KIRYU", run.heat.ticks ? "OVERHEATING! FIRE NOW" : run.mult ?
                  "FIRE: THE CAPTIVE BALL  -  OR CHARGE ON" : "CHARGE THE ABSOLUTE ZERO: LIT SHOTS");
    pm_snprintf(c, sizeof c, "%u%%", run.charge);
    kit_hud_counter(&hud, 0, "CHARGE", c, run.mult ? "READY" : "CHARGING");
    kit_hud_counter(&hud, 1, "ABSOLUTE ZERO", kit_short(v, sizeof v, fire_value(1)), "THE CAPTIVE BALL");
    pm_snprintf(m, sizeof m, "X%u", run.mult ? run.mult : 1);
    if (run.charge >= CHARGE_MAX) kit_copy(sub, sizeof sub, "THE MOST");
    else pm_snprintf(sub, sizeof sub, "X%u AT %u%%", run.mult + 1, (run.mult + 1) * 100);
    kit_hud_counter(&hud, 2, "MULTIPLIER", m, sub);
    kit_hud_timer(&hud, (int)kit_timer_seconds(run.heat.ticks ? &run.heat : &run.clock));
    kit_hud_gauge(&hud, run.charge >= CHARGE_MAX ? 10 : (int)(run.charge % 100) / 10, run.heat.ticks ? "OVERHEAT" : "CHARGE");
}

/* ---- start, charge, fire, end ----------------------------------------------------------------------- */
static int start(const char *why)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_wait_game(MODE_NAME, why, "still lit: the next spin after it starts it")) {
        waiting[p] = 1;
        return 0;
    }
    if (!kit_begin(MODE_NAME)) {
        waiting[p] = 1;
        return 0;
    }
    kit_display(KIT_DISPLAY_MODE);
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);
    run.on = 1;
    run.player = p;
    run.phase = PHASE_CHARGE;
    run.charge = run.mult = 0;
    run.fired = run.vents = 0;
    run.scored = run.total = run.shot_paid = 0;
    run.heat.ticks = 0;
    kit_timer_set(&run.clock, RUN_SECONDS, 1);
    waiting[p] = 0;
    spins[p] = 0;
    plays[p]++;
    kit_hud_begin(&hud, "KIRYU", "");
    kit_hud_pips(&hud, 10);
    show();
    kit_hud_award(&hud, 3000, "KIRYU ONLINE", "CHARGE THE ABSOLUTE ZERO");
    kit_show_start(&show_fx, "kiryu start", SHOW_START, N_SHOW(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, %d s, fire at %s or the %s from 100%%; next time %u spins, score %llu", why, p,
           RUN_SECONDS, FIRE_SHOT, BUTTON_SHOT, spins_needed(p), (unsigned long long)pm_score(p));
    return 1;
}

static void end(const char *why)
{
    char a[24], b[KIT_HUD_WORDS];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);
    kit_end_after(TOTAL_SHOWN_MS);
    sound(CUE_END);
    pa_clip_full(&own, run.fired ? "won" : "lost");
    kit_show_start(&show_fx, "kiryu end", SHOW_END, N_SHOW(SHOW_END));
    if (run.fired) pm_snprintf(b, sizeof b, "ABSOLUTE ZERO X%u  -  %s", run.mult ? run.mult : 1, kit_num(a, sizeof a, run.shot_paid));
    else pm_snprintf(b, sizeof b, "THE CANNON NEVER FIRED");
    kit_hud_title(&hud, run.fired ? "KIRYU WINS" : "KIRYU IS DOWN", b);
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, kit_num(a, sizeof a, run.total), " ");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, the charge %u%%, %u vent(s), total %llu, score %llu", why,
           run.fired ? "FIRED" : "not fired", run.charge, run.vents, (unsigned long long)run.total,
           (unsigned long long)pm_score(run.player));
}

static void fire(const char *how, int bonus)
{
    char a[24], s[KIT_HUD_WORDS];
    uint64_t got;
    if (!run.mult) run.mult = 1;
    got = pay(fire_value(bonus));
    run.shot_paid = got;
    run.fired = 1;
    run.phase = PHASE_FIRED;
    run.fired_at = pm_ms();
    run.heat.ticks = 0;
    pm_log("ABSOLUTE ZERO fired (%s): x%u at %u%%, +%llu", how, run.mult, run.charge, (unsigned long long)got);
    pm_snprintf(s, sizeof s, "ABSOLUTE ZERO X%u", run.mult);
    kit_hud_award(&hud, FIRED_MS, s, kit_num(a, sizeof a, got));
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, 10, "FIRED");
    kit_show_start(&show_fx, "absolute zero", SHOW_FIRE, N_SHOW(SHOW_FIRE));
    sound(CUE_FIRE);
    show_lamps();
}

static void charge_by(unsigned pct, const char *what)
{
    unsigned was = run.charge, m;
    if (run.charge >= CHARGE_MAX) return;
    run.charge += pct;
    if (run.charge > CHARGE_MAX) run.charge = CHARGE_MAX;
    m = mult_of(run.charge);
    if (m == mult_of(was)) return;
    run.mult = m;
    pm_log("the charge passes %u%% (%s): x%u", m * 100, what, m);
    if (m == 1) {
        kit_hud_award(&hud, 2500, "ABSOLUTE ZERO READY", "FIRE: THE CAPTIVE BALL OR THE BUTTON");
        sound(CUE_READY);
    } else {
        char s[KIT_HUD_WORDS];
        pm_snprintf(s, sizeof s, "X%u  -  %u%%", m, m * 100);
        kit_hud_award(&hud, 2000, s, m * 100 >= OVERHEAT_FROM ? "THE REACTOR OVERHEATS" : "CHARGE ON");
        sound(CUE_CHARGE);
    }
    kit_show_start(&show_fx, "charge", SHOW_CHARGE, N_SHOW(SHOW_CHARGE));
    if (run.charge >= OVERHEAT_FROM) {
        kit_timer_set(&run.heat, OVERHEAT_SECONDS, 1);
        pm_log("OVERHEATING: %d s to fire", OVERHEAT_SECONDS);
        if (m * 100 == OVERHEAT_FROM) sound(CUE_OVERHEAT);
    }
}

static void vent(void)
{
    run.vents++;
    pm_log("KIRYU VENTS: the reactor ran too hot at %u%% - the charge back to 0", run.charge);
    run.charge = run.mult = 0;
    run.heat.ticks = 0;
    kit_hud_award(&hud, 2500, "KIRYU VENTS", "THE CHARGE IS LOST");
    kit_show_start(&show_fx, "vent", SHOW_VENT, N_SHOW(SHOW_VENT));
    sound(CUE_OVERHEAT);
}

/* ---- shots ------------------------------------------------------------------------------------------- */
static void charge_shot(uint64_t shot)
{
    unsigned i;
    if (run.mult && (((fire_mask & shot) && kit_fresh(&db, fire_mask)) || (button_mask & shot))) {
        fire((button_mask & shot) ? "the action button" : "the captive ball", 1);
        return;
    }
    if (spin_mask && (shot & spin_mask)) {          /* every spin: no debounce */
        pay(SPIN_VALUE);
        charge_by(1, "a spin");
    }
    for (i = 0; i < N_CHARGE; i++) {
        uint64_t got;
        if (!charge_mask[i] || !(shot & charge_mask[i]) || !kit_fresh(&db, charge_mask[i])) continue;
        got = pay(SHOT_VALUE);
        if (kit_timer_at_least(&run.clock, LIT_SHOT_FLOOR)) pm_log("the clock back up to %d s", LIT_SHOT_FLOOR);
        pm_log("%s: +%llu, charge +%u%%", CHARGE[i].shot, (unsigned long long)got, CHARGE[i].pct);
        charge_by(CHARGE[i].pct, CHARGE[i].shot);
    }
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_HUD_WORDS];
    unsigned need = spins_needed(p);
    if (!spin_mask || !(shot & spin_mask)) return;  /* every spin counts */
    if (waiting[p]) {
        start("the Mechagodzilla spinner, KIRYU lit");
        return;
    }
    if (spins[p] < need) spins[p]++;
    if (spins[p] % 5 == 0 || spins[p] >= need) pm_log("%s %u of %u (player %u)", SPIN_SHOT, spins[p], need, p);
    if (spins[p] >= need) {
        start("the Mechagodzilla spinner");
    } else if (!kit_running) {
        pm_snprintf(line, sizeof line, "%u SPIN%s TO KIRYU", need - spins[p], need - spins[p] == 1 ? "" : "S");
        kit_hud_note(&hud, 1500, line, "MECHAGODZILLA IS BEING BUILT");
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
    if (p != run.player || run.phase != PHASE_CHARGE) return;
    charge_shot(shot);
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    for (i = 0; i < N_CHARGE; i++) {
        charge_mask[i] = pm_shot(CHARGE[i].shot);
        all_charge |= charge_mask[i];
        if (!charge_mask[i]) pm_log("this port has no \"%s\"", CHARGE[i].shot);
    }
    spin_mask = pm_shot(SPIN_SHOT);
    fire_mask = pm_shot(FIRE_SHOT);
    button_mask = pm_shot(BUTTON_SHOT);
    pa_load(&own);
    pm_log("ready on %s %s: %d spins of %s (0x%llx) start it; fire at %s (0x%llx)%s", pm_game(), pm_version(),
           SPINS_FIRST, SPIN_SHOT, (unsigned long long)spin_mask, FIRE_SHOT, (unsigned long long)fire_mask,
           button_mask ? " or the action button" : " (this port has no action button shot)");
}

static void check_triggers(void)
{
    char name[48];
    unsigned v = 0, i;
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger_text(FOLDER ".charge", name, sizeof name) && run.on && run.phase == PHASE_CHARGE) {
        for (i = 0; name[i] >= '0' && name[i] <= '9'; i++) v = v * 10 + (unsigned)(name[i] - '0');
        pm_log("charge trigger: %u%% -> %u%%", run.charge, v);
        if (v > run.charge) charge_by(v - run.charge, "trigger file");
    }
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void run_tick(void)
{
    if (run.phase == PHASE_FIRED) {
        if (pm_ms() - run.fired_at >= FIRED_MS) end("fired");
        return;
    }
    if (run.heat.ticks && kit_timer_tick(&run.heat)) vent();
    run.clock.voice = !run.heat.ticks;            /* one countdown speaks at a time: the overheat's first */
    if (kit_timer_tick(&run.clock)) {
        if (run.mult) {
            pm_log("the clock ran out at %u%%: Kiryu fires on its own, x1, no bonus", run.charge);
            run.mult = 1;
            fire("the clock ran out", 0);
        } else {
            end("time ran out");
        }
        return;
    }
    show();
}

static void on_tick(void)
{
    unsigned p;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) check_triggers();
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) spins[p] = plays[p] = 0, waiting[p] = 0;
        pm_log("new game: the spins cleared");
    }
    if (!run.on) return;
    if (!pm_in_game() || pm_player() != run.player) {
        end("the game moved on");
        return;
    }
    if (kit_game_began()) {                        /* PAD-347: isolated - the game began one of its own */
        end("the game's own mode began");
        kit_end_now();
        return;
    }
    run_tick();
}

static void on_ball_end(void)
{
    end("ball ended");
    kit_end_now();
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) {
        end("tilted");
        kit_end_now();
    }
}

static const struct pm_mode kiryu = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(kiryu);
