/* meltdown.c - MELTDOWN: a MULTIBALL of our own, for Godzilla (hud-layers).
 *
 * Burning Godzilla (Godzilla vs. Destoroyah, 1995): his heart is a nuclear reactor running away.
 * Every multiball the game has is "shoot lit shots for jackpots"; this one is a PUSH-YOUR-LUCK
 * gauge. The hotter the core, the more each jackpot is worth - and at 100% he melts down.
 *
 *   LIGHT IT   Hit the MAGNA-GRAB captive ball (the Godzilla target) 10 times in a game. Every hit
 *              says how many are left; the tenth says MELTDOWN IS READY and the MAGNA GRAB insert
 *              pulses red. The next hit on it starts the multiball (while none of our other modes
 *              and none of the game's own battles or multiballs runs: it waits, still ready).
 *   START      3 balls in play (the game's own ball server, pm_multiball_start), a 15 s ball save.
 *   THE CORE   The core temperature starts at 25% and rises by itself, 1% a second (2% from 70%).
 *              Each jackpot heats it 4% more (8% for the HEART). The heat names the multiplier:
 *                STABLE under 40%  x1     HOT 40-69%  x2
 *                CRITICAL 70-89%   x3     MELTDOWN IMMINENT 90-99%  x5
 *   JACKPOTS   The LEFT RAMP, the RIGHT RAMP, the BUILDING and the BIG LOOP: 2,000,000 x the heat
 *              multiplier (+500,000 on the base per meltdown survived). One of the four is the HEART
 *              (it moves every 8 s and after it is hit): double, and it heats the core twice as fast.
 *   CADMIUM    Each SHIELD target is a Super X III cadmium missile: the core cools 12%. So the player
 *              chooses: cool him down to be safe, or ride the heat for x5.
 *   MELTDOWN   At 100%: MELTDOWN. For 20 s the BUILDING is the MELTDOWN SUPER JACKPOT: twice every
 *              jackpot this multiball has paid. Hit it: GODZILLA JUNIOR absorbs the radiation, the
 *              core drops to 25% and the jackpot base goes up. Miss it: the core blows - back to 50%
 *              and the base back to 2,000,000.
 *   ADD-A-BALL After 4 jackpots the MAGNA GRAB insert lights green: the captive ball adds a ball
 *              (once a multiball).
 *   ENDS       When one ball is left (after the ball save and 3 s more), a tilt, or leaving the game.
 *   THE GLASS  Burning Godzilla steaming in the dark, full screen, then his night walk glowing red
 *              BEHIND the score panel. At the edges: the core's temperature, the jackpot's value
 *              and the jackpots paid across the top, the CORE gauge on the right filling yellow to
 *              white-hot, BURNING GODZILLA and what to do above the score panel; during MELTDOWN the
 *              MELTDOWN badge counts its 20 s. Jackpots play the spiral ray behind the HUD, cadmium
 *              the freezing mist, crossing into CRITICAL the veins glowing; MELTDOWN is full screen.
 *   INSERTS    The four jackpot shots in the heat's colour (yellow, orange, red, white flashing), the
 *              HEART blinking; the shields pulsing ice blue while the core is above 40%; MELTDOWN:
 *              only the BUILDING, strobing white. Everything back to the game at the end.
 *   LIGHTS     Its own shows: at the start, the playfield dark and a red fire rising from the
 *              flippers into a white-hot strobe; MELTDOWN, a white implosion into the Building;
 *              the super jackpot, a burst of blue and white (Junior's rebirth); the end, embers.
 *   SHIELDS    On Godzilla Premium/LE the shield platform turns toward the player as it starts and back away
 *              when it ends (the game's own mode beginning keeps it as that mode left it). A Pro's shields are fixed.
 *   DISPLAY    Priority 190 (a multiball of ours: the game's own jackpots and start screens wait).
 *
 * Emulator test triggers: /dump/meltdown.start (start now, as if lit), .stop, .shot "<shot name>",
 * .light (light it for the player up), .heat "<percent>" (set the core).
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "MELTDOWN"
#define FOLDER             "meltdown"
#define LIGHT_SHOT         "Godzilla target"      /* the Magna-Grab captive ball */
#define HITS_TO_LIGHT      10
#define BALLS              3
#define BALL_SAVE_S        15
#define END_GRACE_MS       3000                   /* after the ball save, before one ball left ends it */
#define ONE_BALL_MS        2000
#define CORE_START         25
#define CORE_RISE_MS       1000                   /* 1% a second */
#define CORE_RISE_HOT_MS   500                    /* 2% a second from CRITICAL */
#define CORE_JACKPOT       4
#define CORE_HEART         8
#define CORE_CADMIUM       12
#define JACKPOT_BASE       2000000ull
#define BASE_STEP          500000ull
#define HEART_MOVES_MS     8000
#define MELTDOWN_SECONDS   20
#define ADD_BALL_AFTER     4
#define TOTAL_SHOWN_MS     10000

#define N_JP 4
static const struct { const char *shot, *says; } JP[N_JP] = {
    { "Left ramp", "LEFT RAMP" }, { "Right ramp", "RIGHT RAMP" }, { "Building", "BUILDING" }, { "Big loop", "BIG LOOP" },
};
static const char *const SHIELDS[3] = { "Shield target left", "Shield target center", "Shield target right" };
#define BUILDING 2

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t jp_mask[N_JP], shield_mask, light_mask;
static unsigned hits[5];
static int ready[5];
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;
static struct kit_shields shields;           /* PAD-379: the Premium's shield platform, turned toward the player */
static struct kit_lamps ready_lamps;   /* the MAGNA GRAB insert pulsing red while MELTDOWN is ready */
static unsigned poll, rnd = 777;

enum { PHASE_BURN, PHASE_MELTDOWN };
static struct {
    int on, phase, heat_level, add_used, served_two;
    unsigned player, core, heart, jackpots, meltdowns, cadmium;
    uint64_t base, paid, total;           /* paid: the jackpots of this multiball (the super is twice it) */
    unsigned long rise_at, heart_at, started, one_ball_since;
    struct kit_timer clock;
} run;

/* ---- light shows: unique to MELTDOWN, fire and radiation ---------------------------------------- */
#define MD_RED         PM_RGB(255, 20, 0)
#define MD_ORANGE      PM_RGB(255, 90, 0)
#define MD_EMBER       PM_RGB(70, 8, 0)
#define MD_ICE         PM_RGB(120, 210, 255)
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_PULSE,    1000, MD_RED, 0, KIT_AT_CENTER, 250, KIT_GI_DARK },           /* his heart, in the dark */
    { KIT_FX_FIRE,     1400, PM_RGB(255, 200, 40), MD_RED, KIT_AT_CENTER, 0, KIT_GI_DARK },   /* the fire rises */
    { KIT_FX_SWEEP_UP,  700, KIT_WHITE, MD_ORANGE, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_STROBE,    600, KIT_WHITE, MD_RED, KIT_AT_CENTER, 55, KIT_GI_FLASH },       /* white-hot */
    { KIT_FX_FADE_OUT,  400, MD_RED, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_MELTDOWN[] = {
    { KIT_FX_STROBE,    700, KIT_WHITE, MD_RED, KIT_AT_CENTER, 45, KIT_GI_FLASH },
    { KIT_FX_IMPLODE,   900, KIT_WHITE, MD_RED, KIT_AT_BUILDING, 0, KIT_GI_DARK },    /* everything into the Building */
    { KIT_FX_FIRE,     1000, KIT_WHITE, MD_RED, KIT_AT_CENTER, 0, KIT_GI_DARK },
};
static const struct kit_fx_step SHOW_SUPER[] = {
    { KIT_FX_BURST,     800, KIT_WHITE, MD_ICE, KIT_AT_BUILDING, 0, KIT_GI_FLASH },     /* Junior absorbs it */
    { KIT_FX_SPARKLE,  1000, MD_ICE, PM_RGB(0, 30, 80), KIT_AT_CENTER, 0, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  500, MD_ICE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_COOL[] = {
    { KIT_FX_SWEEP_RL,  500, MD_ICE, PM_RGB(0, 20, 60), KIT_AT_SHIELDS, 0, KIT_GI_KEEP },   /* cadmium */
};
static const struct kit_fx_step SHOW_END[] = {
    { KIT_FX_SPARKLE,   900, MD_ORANGE, MD_EMBER, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_FADE_OUT, 1200, MD_EMBER, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_SHOW(a) (int)(sizeof (a) / sizeof (a)[0])

/* ---- sound: its own music, calls and clips (modes/meltdown/assets.json) ------------------------- */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_LIT, CUE_START, CUE_JACKPOT, CUE_COOL, CUE_HEAT, CUE_CRITICAL, CUE_MELTDOWN, CUE_SUPER, CUE_BLOWN,
           CUE_ADD, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_LIT:      pa_call(&own, "lit"); break;              /* MELTDOWN IS READY: his roar */
    case CUE_START:    pa_start(&own); break;                    /* the march, the intro, then the night walk */
    case CUE_JACKPOT:                                            /* the spiral ray */
        pa_call(&own, "jackpot");
        pa_clip_event(&own, "jackpot");
        break;
    case CUE_COOL:                                               /* cadmium: the freezing mist */
        pa_call(&own, "cool");
        pa_clip_event(&own, "cool");
        break;
    case CUE_HEAT:     pa_call(&own, "heat"); break;             /* a hotter level: the core alarm */
    case CUE_CRITICAL:                                           /* into CRITICAL: the veins glowing */
        pa_call(&own, "critical");
        pa_clip_event(&own, "critical");
        break;
    case CUE_MELTDOWN:                                           /* MELTDOWN: full screen */
        pa_call(&own, "meltdown");
        pa_clip_full(&own, "meltdown");
        break;
    case CUE_SUPER:                                              /* Junior absorbs the radiation */
        pa_call(&own, "won");
        pa_clip_full(&own, "won");
        break;
    case CUE_BLOWN:    if (!pa_call(&own, "lost")) pm_callout(pm_callout_id("time_up")); break;
    case CUE_ADD:      pa_call(&own, "add"); break;
    case CUE_END:      pa_end(&own); break;
    }
}

/* ---- the core -------------------------------------------------------------------------------------- */
static int heat_level(unsigned core)
{
    return core >= 90 ? 3 : core >= 70 ? 2 : core >= 40 ? 1 : 0;
}
static const char *const HEAT_NAME[4] = { "STABLE", "HOT", "CRITICAL", "IMMINENT" };
static const unsigned HEAT_MULT[4] = { 1, 2, 3, 5 };
static const unsigned HEAT_RGB[4] = { PM_RGB(255, 210, 0), PM_RGB(255, 110, 0), PM_RGB(255, 20, 0), PM_RGB(255, 255, 255) };

static uint64_t jackpot_value(int heart)
{
    return run.base * HEAT_MULT[heat_level(run.core)] * (heart ? 2u : 1u);
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static unsigned next_random(unsigned n)
{
    rnd = rnd * 1103515245u + 12345u + (unsigned)pm_ms();
    return (rnd >> 16) % n;
}

static void start_meltdown(void);

/* the core moved: its level may have changed (a call for a hotter level; 100% is MELTDOWN) */
static void core_set(int core)
{
    int was = run.heat_level;
    if (core < 0) core = 0;
    if (core > 100) core = 100;
    run.core = (unsigned)core;
    run.heat_level = heat_level(run.core);
    if (run.phase == PHASE_BURN && run.core >= 100) {
        start_meltdown();
        return;
    }
    if (run.heat_level > was) {
        pm_log("the core is %s (%u%%): jackpots x%u", HEAT_NAME[run.heat_level], run.core, HEAT_MULT[run.heat_level]);
        kit_hud_award(&hud, 1800, run.heat_level == 3 ? "MELTDOWN IMMINENT" : HEAT_NAME[run.heat_level],
                      run.heat_level == 3 ? "SHOOT THE SHIELDS TO COOL HIM" : "JACKPOTS ARE WORTH MORE");
        sound(run.heat_level == 2 ? CUE_CRITICAL : CUE_HEAT);
    }
}

/* ---- the glass and the inserts ------------------------------------------------------------------------ */
static void show_lamps(void)
{
    unsigned i;
    unsigned rgb = HEAT_RGB[run.heat_level];
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_MELTDOWN) {
        kit_lamps_shot(&lamps, jp_mask[BUILDING], KIT_WHITE, PM_LAMP_BLINK,
                       kit_timer_seconds(&run.clock) > 5 ? 120 : 60);
    } else {
        uint64_t rest = 0;
        for (i = 0; i < N_JP; i++)
            if (i != run.heart) rest |= jp_mask[i];
        kit_lamps_shot(&lamps, rest, rgb, run.heat_level == 3 ? PM_LAMP_BLINK : PM_LAMP_SOLID, 150);
        kit_lamps_shot(&lamps, jp_mask[run.heart], rgb, PM_LAMP_BLINK, run.heat_level >= 2 ? 100 : 250);  /* the heart */
        if (run.core >= 40) kit_lamps_shot(&lamps, shield_mask, MD_ICE, PM_LAMP_PULSE, 900);
        if (!run.add_used && run.jackpots >= ADD_BALL_AFTER)
            kit_lamps_shot(&lamps, light_mask, KIT_GREEN, PM_LAMP_BLINK, 300);
    }
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char core[8], v[24], n[8], sub[24];
    show_lamps();
    pm_snprintf(core, sizeof core, "%u%%", run.core);
    pm_snprintf(n, sizeof n, "%u", run.jackpots);
    if (run.phase == PHASE_MELTDOWN) {
        kit_hud_title(&hud, "MELTDOWN!", "SHOOT THE BUILDING: MELTDOWN SUPER JACKPOT");
        kit_hud_counter(&hud, 0, "CORE", "100%", "MELTDOWN");
        kit_hud_counter(&hud, 1, "SUPER JACKPOT", kit_short(v, sizeof v, 2 * run.paid), "BUILDING");
        kit_hud_counter(&hud, 2, "JACKPOTS", n, " ");
        kit_hud_timer(&hud, (int)kit_timer_seconds(&run.clock));
        kit_hud_gauge(&hud, 10, "CORE");
        return;
    }
    kit_hud_title(&hud, "BURNING GODZILLA", run.heat_level >= 2 ? "SHIELDS COOL THE CORE  -  OR RIDE THE HEAT"
                                                                : "SHOOT RED SHOTS  -  THE HEART PAYS DOUBLE");
    kit_hud_counter(&hud, 0, "CORE", core, HEAT_NAME[run.heat_level]);
    pm_snprintf(sub, sizeof sub, "X%u HEAT", HEAT_MULT[run.heat_level]);
    kit_hud_counter(&hud, 1, "JACKPOT", kit_short(v, sizeof v, jackpot_value(0)), sub);
    pm_snprintf(sub, sizeof sub, "SUPER %s", kit_short(v, sizeof v, 2 * run.paid));
    kit_hud_counter(&hud, 2, "JACKPOTS", n, run.paid ? sub : " ");
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, (int)((run.core + 9) / 10), "CORE");
}

/* The MAGNA GRAB insert pulses red while the player's MELTDOWN is ready and nothing else owns the
 * playfield: not while we run, another of our modes runs, the game's own battle or multiball runs, or a
 * light show plays (a show hands every insert back when it ends). */
static void ready_light(void)
{
    unsigned p = pm_player();
    int want = !run.on && !show_fx.on && !kit_running && light_mask && pm_in_game() && p >= 1 && p <= 4 &&
               ready[p] && !kit_game_busy(MODE_NAME, 0);
    kit_lamps_begin(&ready_lamps);
    if (want) kit_lamps_shot(&ready_lamps, light_mask, MD_RED, PM_LAMP_PULSE, 700);
    kit_lamps_commit(&ready_lamps);
}

/* ---- start, MELTDOWN, end --------------------------------------------------------------------------- */
static int start(const char *why)
{
    const char *what = "";
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_game_busy(MODE_NAME, &what)) {
        pm_log("not started (%s): %s is running - still ready, the next captive ball hit after it starts it", why, what);
        return 0;
    }
    if (!pm_can(PM_CAN_MULTIBALL)) {
        pm_log("not started (%s): this port cannot serve a multiball", why);
        return 0;
    }
    if (!kit_begin(MODE_NAME)) return 0;
    if (!pm_multiball_start(BALLS, BALL_SAVE_S)) {
        pm_log("not started (%s): the game refused the multiball - still ready", why);
        kit_end();
        return 0;
    }
    kit_display(KIT_DISPLAY_WIZARD);
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);   /* PAD-347/363: the game's modes wait for it */
    kit_shields_in(&shields);
    run.on = 1;
    run.player = p;
    run.phase = PHASE_BURN;
    run.core = CORE_START;
    run.heat_level = heat_level(run.core);
    run.base = JACKPOT_BASE;
    run.jackpots = run.meltdowns = run.cadmium = 0;
    run.paid = run.total = 0;
    run.add_used = run.served_two = 0;
    run.heart = next_random(N_JP);
    run.started = run.rise_at = run.heart_at = pm_ms();
    run.one_ball_since = 0;
    ready[p] = 0;
    hits[p] = 0;
    ready_light();                               /* the ready insert handed back */
    kit_hud_begin(&hud, "BURNING GODZILLA", "");
    show();
    kit_hud_award(&hud, 3000, "MELTDOWN MULTIBALL", "HIS HEART IS A NUCLEAR REACTOR");
    kit_show_start(&show_fx, "meltdown start", SHOW_START, N_SHOW(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, %d balls, ball save %d s, core %u%%, the heart: %s, score %llu", why, p, BALLS,
           BALL_SAVE_S, run.core, JP[run.heart].shot, (unsigned long long)pm_score(p));
    return 1;
}

static void start_meltdown(void)
{
    run.phase = PHASE_MELTDOWN;
    run.core = 100;
    run.heat_level = 3;
    kit_timer_set(&run.clock, MELTDOWN_SECONDS, 1);
    kit_hud_award(&hud, 3000, "MELTDOWN!", "20 SECONDS: SHOOT THE BUILDING");
    kit_show_start(&show_fx, "meltdown", SHOW_MELTDOWN, N_SHOW(SHOW_MELTDOWN));
    sound(CUE_MELTDOWN);
    pm_log("MELTDOWN: the core is at 100%%; the Building is the super jackpot for %d s: %llu", MELTDOWN_SECONDS,
           (unsigned long long)(2 * run.paid));
}

static void meltdown_over(int collected)
{
    char n[24];
    if (collected) {
        uint64_t asked = run.paid ? 2 * run.paid : jackpot_value(0) * 5, got = pay(asked);
        run.meltdowns++;
        run.base += BASE_STEP;
        pm_log("MELTDOWN SUPER JACKPOT: +%llu (asked %llu); Junior absorbs it: the core back to %d%%, the base %llu",
               (unsigned long long)got, (unsigned long long)asked, CORE_START, (unsigned long long)run.base);
        kit_hud_award(&hud, 3500, "MELTDOWN SUPER JACKPOT", kit_num(n, sizeof n, got));
        kit_show_start(&show_fx, "meltdown super", SHOW_SUPER, N_SHOW(SHOW_SUPER));
        sound(CUE_SUPER);
        run.core = CORE_START;
    } else {
        pm_log("the MELTDOWN super jackpot ran out: the core blows - back to 50%%, the base back to %llu",
               (unsigned long long)JACKPOT_BASE);
        kit_hud_award(&hud, 3000, "THE CORE BLOWS", "THE JACKPOTS START AGAIN");
        sound(CUE_BLOWN);
        run.core = 50;
        run.base = JACKPOT_BASE;
    }
    run.phase = PHASE_BURN;
    run.heat_level = heat_level(run.core);
    run.paid = 0;
    run.rise_at = pm_ms();
    show();
}

static void end(const char *why)
{
    char a[24], b[KIT_HUD_WORDS];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);
    kit_shields_out(&shields, why);
    kit_end_after(TOTAL_SHOWN_MS);      /* the ending clip and the total keep the screen */
    sound(CUE_END);
    pa_clip_full(&own, run.meltdowns ? "won" : "lost");
    kit_show_start(&show_fx, "meltdown end", SHOW_END, N_SHOW(SHOW_END));
    pm_snprintf(b, sizeof b, "%u JACKPOT%s  -  %u MELTDOWN%s SURVIVED", run.jackpots, run.jackpots == 1 ? "" : "S",
                run.meltdowns, run.meltdowns == 1 ? "" : "S");
    kit_hud_title(&hud, "MELTDOWN TOTAL", b);
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, kit_num(a, sizeof a, run.total), " ");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %u jackpot(s), %u meltdown(s) survived, %u cadmium, total %llu, score %llu", why, run.jackpots,
           run.meltdowns, run.cadmium, (unsigned long long)run.total, (unsigned long long)pm_score(run.player));
}

/* ---- shots ------------------------------------------------------------------------------------------- */
static void burn_shot(uint64_t shot)
{
    char line[KIT_HUD_WORDS], n[24];
    unsigned i;
    for (i = 0; i < 3; i++) {                     /* cadmium */
        uint64_t m = pm_shot(SHIELDS[i]);
        if (!m || !(shot & m) || !kit_fresh(&db, m)) continue;
        run.cadmium++;
        pm_log("CADMIUM at %s: the core %u%% -> %d%%", SHIELDS[i], run.core, (int)run.core - CORE_CADMIUM);
        core_set((int)run.core - CORE_CADMIUM);
        run.heat_level = heat_level(run.core);
        kit_hud_award(&hud, 1500, "CADMIUM MISSILE", "THE CORE COOLS");
        kit_show_start(&show_fx, "cadmium", SHOW_COOL, N_SHOW(SHOW_COOL));
        sound(CUE_COOL);
    }
    if (!run.add_used && run.jackpots >= ADD_BALL_AFTER && light_mask && (shot & light_mask) && kit_fresh(&db, light_mask)) {
        run.add_used = 1;
        pm_log("ADD-A-BALL at the captive ball: %d", pm_multiball_add(1, 10));
        kit_hud_award(&hud, 2000, "ADD-A-BALL", "ANOTHER BALL IN PLAY");
        sound(CUE_ADD);
    }
    for (i = 0; i < N_JP; i++) {
        int heart = i == run.heart;
        uint64_t asked, got;
        if (!jp_mask[i] || !(shot & jp_mask[i]) || !kit_fresh(&db, jp_mask[i])) continue;
        asked = jackpot_value(heart);
        got = pay(asked);
        run.paid += got;
        run.jackpots++;
        pm_log("JACKPOT %u at %s%s: +%llu (x%u, the core %u%%)", run.jackpots, JP[i].shot, heart ? " (THE HEART)" : "",
               (unsigned long long)got, HEAT_MULT[run.heat_level], run.core);
        pm_snprintf(line, sizeof line, heart ? "HEART JACKPOT" : "JACKPOT");
        kit_hud_award(&hud, 1800, line, kit_num(n, sizeof n, got));
        sound(CUE_JACKPOT);
        if (heart) {
            run.heart = (run.heart + 1 + next_random(N_JP - 1)) % N_JP;
            run.heart_at = pm_ms();
        }
        core_set((int)run.core + (heart ? CORE_HEART : CORE_JACKPOT));
        if (!run.on || run.phase != PHASE_BURN) return;
    }
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    char line[KIT_HUD_WORDS];
    if (!pm_in_game() || p < 1 || p > 4) return;
    if (!run.on) {
        if (!light_mask || !(shot & light_mask) || !kit_fresh(&db, light_mask)) return;
        if (kit_running) return;                 /* another of our modes owns the shot and the glass */
        if (ready[p]) {
            start("the captive ball, MELTDOWN ready");
            return;
        }
        if (hits[p] < HITS_TO_LIGHT) hits[p]++;
        pm_log("captive ball %u of %d (player %u)", hits[p], HITS_TO_LIGHT, p);
        if (hits[p] >= HITS_TO_LIGHT) {
            ready[p] = 1;
            pm_log("MELTDOWN IS READY for player %u: the captive ball starts it", p);
            kit_hud_note(&hud, 3000, "MELTDOWN IS READY", "HIT THE CAPTIVE BALL");
            sound(CUE_LIT);
        } else {
            pm_snprintf(line, sizeof line, "%u MORE FOR MELTDOWN", HITS_TO_LIGHT - hits[p]);
            kit_hud_note(&hud, 1800, line, "THE CORE IS HEATING UP");
        }
        return;
    }
    if (p != run.player) return;
    if (run.phase == PHASE_MELTDOWN) {
        if (jp_mask[BUILDING] && (shot & jp_mask[BUILDING]) && kit_fresh(&db, jp_mask[BUILDING])) meltdown_over(1);
        return;
    }
    burn_shot(shot);
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    for (i = 0; i < N_JP; i++) {
        jp_mask[i] = pm_shot(JP[i].shot);
        if (!jp_mask[i]) pm_log("this port has no \"%s\"", JP[i].shot);
    }
    for (i = 0; i < 3; i++) shield_mask |= pm_shot(SHIELDS[i]);
    light_mask = pm_shot(LIGHT_SHOT);
    rnd ^= (unsigned)pm_ms();
    pa_load(&own);
    pm_log("ready on %s %s: %d hits on %s (0x%llx) light it; jackpots 0x%llx 0x%llx 0x%llx 0x%llx, cadmium 0x%llx; "
           "multiball %s", pm_game(), pm_version(), HITS_TO_LIGHT, LIGHT_SHOT, (unsigned long long)light_mask,
           (unsigned long long)jp_mask[0], (unsigned long long)jp_mask[1], (unsigned long long)jp_mask[2],
           (unsigned long long)jp_mask[3], (unsigned long long)shield_mask,
           pm_can(PM_CAN_MULTIBALL) ? "yes" : "NOT in this port");
}

static void check_triggers(void)
{
    char name[48];
    unsigned p = pm_player();
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger(FOLDER ".light") && p >= 1 && p <= 4) {
        ready[p] = 1;
        hits[p] = HITS_TO_LIGHT;
        pm_log("MELTDOWN IS READY for player %u (trigger file)", p);
    }
    if (pm_trigger_text(FOLDER ".heat", name, sizeof name) && run.on) {
        unsigned v = 0, i;
        for (i = 0; name[i] >= '0' && name[i] <= '9'; i++) v = v * 10 + (unsigned)(name[i] - '0');
        pm_log("heat trigger: the core %u%% -> %u%%", run.core, v);
        core_set((int)v);
    }
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void burn_tick(void)
{
    unsigned long now = pm_ms(), step = run.core >= 70 ? CORE_RISE_HOT_MS : CORE_RISE_MS;
    if (run.phase == PHASE_MELTDOWN) {
        if (kit_timer_tick(&run.clock)) meltdown_over(0);
        show();
        return;
    }
    if (now - run.rise_at >= step) {              /* the core rises by itself */
        run.rise_at = now;
        core_set((int)run.core + 1);
        if (run.phase != PHASE_BURN) return;
    }
    if (now - run.heart_at >= HEART_MOVES_MS) {   /* the heart moves */
        run.heart = (run.heart + 1 + next_random(N_JP - 1)) % N_JP;
        run.heart_at = now;
    }
    show();
}

static void on_tick(void)
{
    unsigned p;
    int balls;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    kit_shields_tick(&shields);
    if (++poll % KIT_POLL == 0) {
        check_triggers();
        ready_light();
    }
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) hits[p] = 0, ready[p] = 0;
        pm_log("new game: the captive ball counts cleared");
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
    balls = pm_balls_in_play();
    if (balls >= 2) {
        run.served_two = 1;
        run.one_ball_since = 0;
    } else if (pm_ms() - run.started > (unsigned long)BALL_SAVE_S * 1000u + END_GRACE_MS) {
        if (!run.one_ball_since) run.one_ball_since = pm_ms();
        else if (pm_ms() - run.one_ball_since >= ONE_BALL_MS) {
            end(run.served_two ? "one ball left" : "no second ball was served");
            return;
        }
    }
    burn_tick();
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

static const struct pm_mode meltdown = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(meltdown);
