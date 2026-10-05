/* godzilla_angry.c - GODZILLA ANGRY!: a RAGE meter fed by every switch, a chase in staged locks, a multiball
 * (PAD-379, for Godzilla). Modelled on Lyman Sheats' "Gappa Angry!" in Elvira's House of Horrors (2019): its
 * Freak Fryer counts every switch hit toward the mode, and the mode is a fixed sequence of lit shots, each
 * stage ending in a lock somewhere else, the last one starting a 6-ball multiball.
 *
 * Godzilla vs. Mechagodzilla II (1993): G-Force carries Baby Godzilla away as bait. Godzilla comes for him.
 *
 *   THE RAGE   Every playfield switch hit (the game's 0x1 dispatch) fills the RAGE meter, for the player up,
 *              all game. Five levels: 100, 125, 150, 175 and 200 hits (EHoH's 150..250, scaled to Godzilla's
 *              one pop bumper). Each level pays 1,000,000 more 500,000 a level, with a roar. Nothing counts
 *              during a multiball (two balls in play, or the game's own), during the mode itself, or after a
 *              tilt. The meter is on the glass all the time: a gauge on the right edge (RAGE n/5), the award
 *              line every quarter of a level ("40 MORE FOR RAGE 3"). Level 5 lights it: GODZILLA IS ANGRY,
 *              and the BUILDING insert pulses red.
 *   START      The BUILDING while it is lit (no other mode of ours, none of the game's, one ball in play):
 *              a 5 s ball save, and the chase.
 *   THE CHASE  Five places, each a set of lit shots (any order) then a LOCK (a virtual one: the ball stays
 *              in play). The Building that started it is ADONOA ISLAND's shot.
 *                1 ADONOA ISLAND  lock at the captive ball
 *                2 YOKKAICHI      both ramps, then lock at the Maser
 *                3 OSAKA          the Big loop and the Building, then lock at the captive ball
 *                4 KYOTO          both ramps, the Building and the Big loop, then lock at the Maser
 *                5 MAKUHARI       both ramps, the Big loop, the Building and the center powerline, then
 *                                 lock at the captive ball
 *                6 BABY           the BUILDING: BABY FOUND, the SUPER JACKPOT and a 6-ball multiball
 *              A shot pays 500,000, +500,000 a place and +25,000 a shot within it, and adds an eighth of
 *              it to the JACKPOT; a lock pays twice that and adds 250,000 a place. Every switch hit adds 10,000
 *              to the SUPER JACKPOT (from 5,000,000). Each place has 30 s; a lit shot with under 15 s left
 *              puts it back to 15 (EHoH's Haunts).
 *   FAILING STILL PAYS (EHoH: the balls you locked become a smaller multiball): a place's clock running out
 *              ends the chase, and the locks made become a multiball of locks + 1 balls (2 to 6) scoring
 *              the JACKPOT built. With no lock yet, the trail goes cold: the meter stays full and the
 *              Building starts the chase again. A drain ends the chase too, and the place and its locks wait
 *              for the next ball: the Building picks the trail up there.
 *   MULTIBALL  ANGRY MULTIBALL (6 balls when BABY was found, else the locks + 1), 15 s ball save. The
 *              ramps, the Building and the Big loop are lit; one of them is BABY (it moves every 10 s and
 *              when hit): BABY scores the JACKPOT times the multiplier, any other lit shot pays 500,000 and
 *              raises the multiplier, up to x6 (EHoH's Scream Test); BABY puts it back to x1.
 *   ENDS       One ball left (after the ball save and 3 s more), a tilt, one of the game's own modes
 *              beginning, leaving the game. Then the meter starts again, each level 25 hits more.
 *   THE GLASS  Godzilla raging, full screen, at the chase's start; his march behind the score panel; the
 *              place, what to shoot, LOCKS, JACKPOT and SUPER at the edges, the place's clock in the badge,
 *              the locks on the right edge's gauge. A lock plays Godzilla smashing through; BABY FOUND,
 *              the super and the endings are full screen.
 *   INSERTS    Ready: the BUILDING pulsing red. The chase: the place's shots still to make red, the lock
 *              white and blinking, faster as the clock runs out. The multiball: the jackpot shots orange,
 *              BABY green and blinking.
 *   DISPLAY    Priority 180 for the chase, 190 for the multiball.
 *
 * Emulator test triggers: /dump/godzilla_angry.start (the chase now, as if lit), .stop, .light (the meter
 * full), .shot "<shot name>", .rage "<hits>" (add switch hits to the meter), .mb "<balls>" (the multiball now).
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "GODZILLA ANGRY"
#define FOLDER             "godzilla_angry"
#define START_SHOT         "Building"
#define LEVELS             5
#define LEVEL_FIRST        100            /* hits for RAGE 1; each level 25 more */
#define LEVEL_STEP         25
#define REPEAT_STEP        25             /* each level 25 more every time the mode has been played */
#define LEVEL_AWARD        1000000ull
#define LEVEL_AWARD_STEP   500000ull
#define START_SAVE_S       5
#define PLACE_SECONDS      30
#define LIT_SHOT_FLOOR     15             /* a lit shot with under 15 s left puts the clock back to 15 */
#define SHOT_BASE          500000ull
#define SHOT_PLACE_STEP    500000ull
#define SHOT_WITHIN_STEP   25000ull
#define LOCK_JACKPOT_STEP  250000ull
#define JACKPOT_SHARE      8              /* a lit shot adds an eighth of what it paid to the JACKPOT */
#define SUPER_START        5000000ull
#define SUPER_PER_SWITCH   10000ull
#define MB_BALLS_FULL      6
#define MB_SAVE_S          15
#define END_GRACE_MS       3000
#define ONE_BALL_MS        2000
#define BABY_MOVES_MS      10000
#define MULT_MAX           6
#define OTHER_SHOT         500000ull
#define TOTAL_SHOWN_MS     10000
#define AFTER_ANOTHER_MS   300            /* the shot that just ended another of ours is not a start */

#define N_PLACES 5
#define MAX_LIT  5
static const struct {
    const char *place;
    const char *shots[MAX_LIT];          /* lit before the lock (0 = none) */
    const char *lock, *lock_says;
} PLACE[N_PLACES] = {
    { "ADONOA ISLAND", { 0 }, "Godzilla target", "THE CAPTIVE BALL" },
    { "YOKKAICHI", { "Left ramp", "Right ramp", 0 }, "Maser target", "THE MASER" },
    { "OSAKA", { "Big loop", "Building", 0 }, "Godzilla target", "THE CAPTIVE BALL" },
    { "KYOTO", { "Left ramp", "Right ramp", "Building", "Big loop", 0 }, "Maser target", "THE MASER" },
    { "MAKUHARI", { "Left ramp", "Right ramp", "Big loop", "Building", "Powerline center" }, "Godzilla target",
      "THE CAPTIVE BALL" },
};
#define N_JP 4
static const char *const JP[N_JP] = { "Left ramp", "Right ramp", "Building", "Big loop" };
static const char *const JP_SAYS[N_JP] = { "LEFT RAMP", "RIGHT RAMP", "BUILDING", "BIG LOOP" };

/* what the instruction line calls a shot */
static const char *says(const char *shot)
{
    static const char *const W[][2] = {
        { "Left ramp", "LEFT RAMP" }, { "Right ramp", "RIGHT RAMP" }, { "Building", "BUILDING" },
        { "Big loop", "BIG LOOP" }, { "Powerline center", "CENTER POWERLINE" },
    };
    unsigned i;
    for (i = 0; i < sizeof W / sizeof W[0]; i++)
        if (kit_same(W[i][0], shot)) return W[i][1];
    return shot;
}

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t start_mask, jp_mask[N_JP];
static unsigned hits[5], level[5], plays[5];         /* the RAGE meter, per player */
static int ready[5], tilted, meter_wait;             /* meter_wait: hidden from a drain to the next switch */
static int mb_now;                                   /* a multiball is on (asked ten times a second) */
static unsigned place_at[5], locks_at[5];            /* a chase left by a drain: where, and its locks */
static uint64_t jackpot_at[5], super_at[5];
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps, ready_lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;
static unsigned poll, rnd = 1993;

enum { PHASE_CHASE, PHASE_MB };
static struct {
    int on, phase, lock_lit, full, served_two;
    unsigned player, place, locks, made, mult, baby, babies, balls;
    uint64_t made_mask, jackpot, super, total;
    unsigned long started, baby_at, one_ball_since;
    struct kit_timer clock;
} run;

/* ---- light shows: rage red and white ----------------------------------------------------------- */
#define GA_RED         PM_RGB(255, 10, 0)
#define GA_EMBER       PM_RGB(80, 6, 0)
#define GA_BLUE        PM_RGB(40, 120, 255)            /* his atomic breath */
static const struct kit_fx_step SHOW_LEVEL[] = {      /* a rage level: a red throb from the flippers */
    { KIT_FX_SWEEP_UP,  450, GA_RED, GA_EMBER, KIT_AT_CENTER, 0, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  300, GA_RED, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_ANGRY[] = {      /* the meter full: the whole playfield throbs */
    { KIT_FX_PULSE,     900, GA_RED, GA_EMBER, KIT_AT_CENTER, 150, KIT_GI_DARK },
    { KIT_FX_STROBE,    500, KIT_WHITE, GA_RED, KIT_AT_CENTER, 60, KIT_GI_FLASH },
    { KIT_FX_IMPLODE,   700, GA_RED, GA_EMBER, KIT_AT_BUILDING, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_BOLTS,     900, KIT_WHITE, GA_EMBER, KIT_AT_CENTER, 140, KIT_GI_DARK },
    { KIT_FX_BURST,     800, GA_BLUE, GA_RED, KIT_AT_BUILDING, 0, KIT_GI_DARK },
    { KIT_FX_SWEEP_UP,  600, GA_RED, GA_EMBER, KIT_AT_CENTER, 0, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  300, GA_RED, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_LOCK[] = {
    { KIT_FX_BURST,     700, KIT_WHITE, GA_RED, KIT_AT_MAGNA, 0, KIT_GI_FLASH },
    { KIT_FX_FADE_OUT,  300, GA_RED, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_BABY[] = {       /* BABY FOUND: green, then every colour */
    { KIT_FX_BURST,     800, KIT_GREEN, KIT_WHITE, KIT_AT_BUILDING, 0, KIT_GI_FLASH },
    { KIT_FX_RAINBOW,  1500, 0, 0, KIT_AT_BUILDING, 80, KIT_GI_KEEP },
    { KIT_FX_STROBE,    500, KIT_WHITE, KIT_GREEN, KIT_AT_CENTER, 50, KIT_GI_FLASH },
};
static const struct kit_fx_step SHOW_END[] = {
    { KIT_FX_SPARKLE,   900, GA_RED, GA_EMBER, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_FADE_OUT, 1000, GA_EMBER, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_SHOW(a) (int)(sizeof (a) / sizeof (a)[0])

/* ---- sound: its own music, calls and clips (modes/godzilla_angry/assets.json) -------------------- */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_RAGE, CUE_ANGRY, CUE_START, CUE_LOCK, CUE_BABY, CUE_JACKPOT, CUE_SUPER, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_RAGE:     pa_call(&own, "rage"); break;              /* a rage level: a short roar */
    case CUE_ANGRY:    pa_call(&own, "angry"); break;             /* GODZILLA IS ANGRY: his full roar */
    case CUE_START:    pa_start(&own); break;                     /* the march, his rage full screen, then on */
    case CUE_LOCK:                                                /* he smashes through */
        pa_call(&own, "lock");
        pa_clip_event(&own, "lock");
        break;
    case CUE_BABY:                                                /* BABY FOUND */
        pa_call(&own, "baby");
        pa_clip_full(&own, "baby");
        break;
    case CUE_JACKPOT:                                             /* the atomic ray */
        pa_call(&own, "jackpot");
        pa_clip_event(&own, "jackpot");
        break;
    case CUE_SUPER:
        pa_call(&own, "super");
        pa_clip_full(&own, "super");
        break;
    case CUE_END:      pa_end(&own); break;
    }
}

/* ---- the RAGE meter ------------------------------------------------------------------------------ */
static unsigned level_need(unsigned p, unsigned lv)          /* hits for level lv (0-based) */
{
    return LEVEL_FIRST + LEVEL_STEP * lv + REPEAT_STEP * plays[p];
}

/* a multiball is on: two balls in play, or the game's own (EHoH: no Freak Fryer progress in its 6-ball wizard
 * multiball; David: "not counting switch hits during multiball") */
static int multiball_on(void)
{
    const char *what = 0;
    if (pm_can(PM_CAN_MULTIBALL) && pm_balls_in_play() >= 2) return 1;
    return kit_stock_busy(PM_STOCK_MULTIBALL, MODE_NAME, &what);
}

/* the meter counts now: a game, one ball, no tilt, the mode not running */
static int meter_counts(void)
{
    return pm_in_game() && !tilted && !run.on && !mb_now;
}

static void show_fx_if_free(const char *name, const struct kit_fx_step *steps, int n)
{
    if (!kit_running && !show_fx.on) kit_show_start(&show_fx, name, steps, n);   /* never over another mode's inserts */
}

static void rage_switch(unsigned p)
{
    char line[KIT_HUD_WORDS], sub[KIT_HUD_WORDS], v[24];
    unsigned need, q0, q1;
    if (ready[p] || !meter_counts()) return;
    need = level_need(p, level[p]);
    q0 = hits[p] * 4 / need;
    hits[p]++;
    q1 = hits[p] * 4 / need;
    if (hits[p] < need) {
        if (q1 != q0) {
            pm_log("rage %u: %u of %u switch hits (player %u)", level[p] + 1, hits[p], need, p);
            pm_snprintf(line, sizeof line, "%u MORE FOR RAGE %u", need - hits[p], level[p] + 1);
            kit_hud_note(&hud, 1500, line, "GODZILLA IS GETTING ANGRY");
        }
        return;
    }
    {
        uint64_t asked = LEVEL_AWARD + LEVEL_AWARD_STEP * level[p], got = pm_score_add(p, asked);
        level[p]++;
        hits[p] = 0;
        pm_log("RAGE LEVEL %u of %d (player %u): +%llu", level[p], LEVELS, p, (unsigned long long)got);
        if (level[p] >= LEVELS) {
            ready[p] = 1;
            pm_log("GODZILLA IS ANGRY for player %u: the %s starts the chase", p, START_SHOT);
            kit_hud_note(&hud, 3500, "GODZILLA IS ANGRY!", "SHOOT THE BUILDING");
            sound(CUE_ANGRY);
            show_fx_if_free("angry", SHOW_ANGRY, N_SHOW(SHOW_ANGRY));
        } else {
            pm_snprintf(line, sizeof line, "RAGE LEVEL %u", level[p]);
            pm_snprintf(sub, sizeof sub, "%s", kit_num(v, sizeof v, got));
            kit_hud_note(&hud, 2200, line, sub);
            sound(CUE_RAGE);
            show_fx_if_free("rage level", SHOW_LEVEL, N_SHOW(SHOW_LEVEL));
        }
    }
}

/* The meter on the glass: the right edge's gauge while it counts, its own label; nothing while the mode
 * runs (its HUD is the mode's), during a multiball, from a drain to the next switch hit, outside a game. */
static void meter_tick(void)
{
    unsigned p = pm_player();
    char label[24];
    int pips, n_pips;
    if (run.on || !pm_in_game() || p < 1 || p > 4 || meter_wait || tilted || mb_now) {
        kit_hud_meter(&hud, -1, 0);
        return;
    }
    kit_hud_pips(&hud, 0);
    n_pips = hud.n_pips ? hud.n_pips : KIT_HUD_PIPS;    /* as many as the card was built with */
    if (ready[p]) {
        pips = n_pips;
        kit_copy(label, sizeof label, "ANGRY!");
    } else {
        unsigned need = level_need(p, level[p]);
        pips = (int)(hits[p] * (unsigned)n_pips / need);
        pm_snprintf(label, sizeof label, "RAGE %u/%d", level[p] + 1, LEVELS);
    }
    kit_hud_meter(&hud, pips, label);
}

/* The BUILDING pulses red while the chase is lit and nothing else owns the playfield. */
static void ready_light(void)
{
    unsigned p = pm_player();
    int want = !run.on && !show_fx.on && !kit_running && start_mask && pm_in_game() && p >= 1 && p <= 4 &&
               ready[p] && !kit_game_busy(MODE_NAME, 0);
    kit_lamps_begin(&ready_lamps);
    if (want) kit_lamps_shot(&ready_lamps, start_mask, GA_RED, PM_LAMP_PULSE, 700);
    kit_lamps_commit(&ready_lamps);
}

/* ---- scoring ---------------------------------------------------------------------------------------- */
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

static uint64_t shot_value(void)
{
    return SHOT_BASE + SHOT_PLACE_STEP * run.place + SHOT_WITHIN_STEP * run.made;
}

/* ---- the glass and the inserts ------------------------------------------------------------------------ */
static uint64_t place_shots(unsigned place)
{
    uint64_t m = 0;
    unsigned i;
    for (i = 0; i < MAX_LIT && PLACE[place].shots[i]; i++) m |= pm_shot(PLACE[place].shots[i]);
    return m;
}

static void show_lamps(void)
{
    unsigned i;
    unsigned long left = (unsigned long)kit_timer_seconds(&run.clock) * 1000u;
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_CHASE) {
        if (run.place < N_PLACES) {
            uint64_t todo = place_shots(run.place) & ~run.made_mask;
            if (!run.lock_lit && todo) kit_lamps_shot(&lamps, todo, GA_RED, PM_LAMP_SOLID, 0);
            if (run.lock_lit)
                kit_lamps_shot(&lamps, pm_shot(PLACE[run.place].lock), KIT_WHITE, PM_LAMP_BLINK,
                               kit_hurry_ms(left, PLACE_SECONDS * 1000u));
        } else {
            kit_lamps_shot(&lamps, start_mask, KIT_GREEN, PM_LAMP_BLINK, kit_hurry_ms(left, PLACE_SECONDS * 1000u));
        }
    } else {
        uint64_t rest = 0;
        for (i = 0; i < N_JP; i++)
            if (i != run.baby) rest |= jp_mask[i];
        kit_lamps_shot(&lamps, rest, KIT_ORANGE, PM_LAMP_SOLID, 0);
        kit_lamps_shot(&lamps, jp_mask[run.baby], KIT_GREEN, PM_LAMP_BLINK, 200);
    }
    kit_lamps_commit(&lamps);
}

/* "OSAKA: BIG LOOP, BUILDING" - the shots still to make, named while they fit, else counted */
static void what_to_shoot(char *out, unsigned cap)
{
    unsigned i, n = 0, k;
    uint64_t todo;
    if (run.place >= N_PLACES) {
        kit_copy(out, cap, "SHOOT THE BUILDING: BABY IS THERE");
        return;
    }
    if (run.lock_lit) {
        pm_snprintf(out, cap, "LOCK IS LIT AT %s", PLACE[run.place].lock_says);
        return;
    }
    todo = place_shots(run.place) & ~run.made_mask;
    k = (unsigned)pm_snprintf(out, cap, "%s:", PLACE[run.place].place);
    for (i = 0; i < MAX_LIT && PLACE[run.place].shots[i]; i++) {
        const char *w;
        if (!(todo & pm_shot(PLACE[run.place].shots[i]))) continue;
        w = says(PLACE[run.place].shots[i]);
        n++;
        if (k < cap) k += (unsigned)pm_snprintf(out + k, cap - k, "%s %s", n > 1 ? "," : "", w);
    }
    if (k >= 40 || k >= cap)
        pm_snprintf(out, cap, "%s: %u LIT SHOTS TO GO", PLACE[run.place].place, n);
}

static void show(void)
{
    char line[KIT_HUD_WORDS], v[24], s[24], n[24];
    show_lamps();
    if (run.phase == PHASE_CHASE) {
        what_to_shoot(line, sizeof line);
        kit_hud_title(&hud, "GODZILLA ANGRY!", line);
        pm_snprintf(n, sizeof n, "%u/%d", run.locks, N_PLACES);
        kit_hud_counter(&hud, 0, "LOCKS", n, run.place < N_PLACES ? PLACE[run.place].place : "BABY");
        kit_hud_counter(&hud, 1, "JACKPOT", kit_short(v, sizeof v, run.jackpot), "BUILT BY SHOTS");
        kit_hud_counter(&hud, 2, "SUPER", kit_short(s, sizeof s, run.super), "FED BY SWITCHES");
        kit_hud_timer(&hud, (int)kit_timer_seconds(&run.clock));
        kit_hud_pips(&hud, N_PLACES + 1);
        kit_hud_gauge(&hud, (int)run.locks, "LOCKS");
        return;
    }
    pm_snprintf(line, sizeof line, "BABY IS AT THE %s", JP_SAYS[run.baby]);
    kit_hud_title(&hud, "ANGRY MULTIBALL", line);
    pm_snprintf(n, sizeof n, "X%u", run.mult);
    kit_hud_counter(&hud, 0, "MULTIPLIER", n, "OTHERS RAISE IT");
    kit_hud_counter(&hud, 1, "JACKPOT", kit_short(v, sizeof v, run.jackpot), "AT BABY");
    pm_snprintf(s, sizeof s, "%u", run.babies);
    kit_hud_counter(&hud, 2, "JACKPOTS", s, "AT BABY");
    kit_hud_timer(&hud, -1);
    kit_hud_pips(&hud, MULT_MAX);
    kit_hud_gauge(&hud, (int)run.mult, "MULTIPLIER");
}

/* ---- start, the places, the multiball, the end ------------------------------------------------------------ */
static void enter_place(unsigned place)
{
    run.place = place;
    run.made = 0;
    run.made_mask = 0;
    run.lock_lit = place < N_PLACES && !place_shots(place);    /* ADONOA ISLAND: the lock at once */
    kit_timer_set(&run.clock, PLACE_SECONDS, 1);
    if (place < N_PLACES)
        pm_log("place %u: %s (%s lock at %s)", place + 1, PLACE[place].place, run.lock_lit ? "the" : "then the",
               PLACE[place].lock);
    else
        pm_log("BABY: the %s is BABY FOUND for %d s", START_SHOT, PLACE_SECONDS);
}

static int start(const char *why)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_wait_game(MODE_NAME, why, "still lit: the Building after it starts it")) return 0;   /* PAD-347 */
    if (!kit_begin(MODE_NAME)) return 0;
    kit_display(KIT_DISPLAY_MODE);
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);
    run.on = 1;
    run.player = p;
    run.phase = PHASE_CHASE;
    run.full = run.served_two = 0;
    run.locks = locks_at[p];
    run.jackpot = jackpot_at[p];
    run.super = super_at[p] ? super_at[p] : SUPER_START;
    run.total = 0;
    run.mult = 1;
    run.babies = 0;
    run.started = pm_ms();
    kit_hud_meter(&hud, -1, 0);
    enter_place(place_at[p]);
    if (pm_ball_save(START_SAVE_S)) pm_log("a %d s ball save", START_SAVE_S);
    ready_light();
    kit_hud_begin(&hud, "GODZILLA ANGRY!", "");
    show();
    kit_hud_award(&hud, 3000, place_at[p] ? "THE TRAIL AGAIN" : "GODZILLA ANGRY!",
                  place_at[p] ? PLACE[place_at[p]].place : "THEY TOOK BABY GODZILLA");
    kit_show_start(&show_fx, "angry start", SHOW_START, N_SHOW(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, place %u (%s), %u lock(s), jackpot %llu, super %llu, score %llu", why, p,
           run.place + 1, run.place < N_PLACES ? PLACE[run.place].place : "BABY", run.locks,
           (unsigned long long)run.jackpot, (unsigned long long)run.super, (unsigned long long)pm_score(p));
    return 1;
}

static void start_multiball(unsigned balls, const char *why)
{
    if (balls < 2) balls = 2;
    if (balls > MB_BALLS_FULL) balls = MB_BALLS_FULL;
    if (!pm_multiball_start(balls, MB_SAVE_S)) {
        pm_log("the game refused the multiball (%s)", why);
        run.balls = 0;
    } else {
        run.balls = balls;
    }
    run.phase = PHASE_MB;
    run.mult = 1;
    run.baby = next_random(N_JP);
    run.baby_at = run.started = pm_ms();
    run.one_ball_since = 0;
    run.served_two = 0;
    if (run.jackpot < SHOT_BASE * 4) run.jackpot = SHOT_BASE * 4;
    kit_display(KIT_DISPLAY_WIZARD);
    pm_log("ANGRY MULTIBALL (%s): %u balls, jackpot %llu at BABY (%s)", why, balls, (unsigned long long)run.jackpot,
           JP[run.baby]);
}

static void lock_made(void)
{
    char a[24];
    uint64_t got = pay(2 * shot_value());
    run.locks++;
    run.jackpot += LOCK_JACKPOT_STEP * (run.place + 1);
    pm_log("LOCK %u at %s (%s): +%llu, the jackpot %llu", run.locks, PLACE[run.place].lock, PLACE[run.place].place,
           (unsigned long long)got, (unsigned long long)run.jackpot);
    kit_hud_award(&hud, 2200, run.locks == 1 ? "1 LOCK" : run.locks == 2 ? "2 LOCKS" : run.locks == 3 ? "3 LOCKS"
                  : run.locks == 4 ? "4 LOCKS" : "5 LOCKS", kit_num(a, sizeof a, got));
    kit_show_start(&show_fx, "lock", SHOW_LOCK, N_SHOW(SHOW_LOCK));
    sound(CUE_LOCK);
    enter_place(run.place + 1);
}

static void baby_found(void)
{
    char a[24], b[KIT_HUD_WORDS];
    uint64_t got = pay(run.super);
    pm_log("BABY FOUND: SUPER JACKPOT +%llu (switches built it)", (unsigned long long)got);
    pm_snprintf(b, sizeof b, "BABY FOUND: %s", kit_num(a, sizeof a, got));
    kit_hud_award(&hud, 3500, "SUPER JACKPOT", b);
    kit_show_start(&show_fx, "baby found", SHOW_BABY, N_SHOW(SHOW_BABY));
    sound(CUE_BABY);
    run.full = 1;
    run.locks = N_PLACES;
    start_multiball(MB_BALLS_FULL, "BABY FOUND");
}

static void forget_trail(unsigned p)
{
    place_at[p] = locks_at[p] = 0;
    jackpot_at[p] = super_at[p] = 0;
}

static void meter_again(unsigned p)
{
    ready[p] = 0;
    level[p] = hits[p] = 0;
    plays[p]++;
    forget_trail(p);
    pm_log("the RAGE meter starts again for player %u: RAGE 1 at %u hits", p, level_need(p, 0));
}

static void end(const char *why)
{
    char a[24], b[KIT_HUD_WORDS];
    unsigned p = run.player;
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);
    kit_end_after(TOTAL_SHOWN_MS);
    if (kit_natural_end(why) && !pa_call(&own, run.full ? "won" : "lost") && !(run.full))
        pm_callout(pm_callout_id("time_up"));          /* its own ending call, else the game's time-up */
    sound(CUE_END);
    if (run.phase == PHASE_MB) {
        pa_clip_full(&own, run.full ? "won" : "lost");
        meter_again(p);
    } else if (run.locks || run.place) {               /* a drain mid-chase: the trail waits for the next ball */
        place_at[p] = run.place;
        locks_at[p] = run.locks;
        jackpot_at[p] = run.jackpot;
        super_at[p] = run.super;
        pa_clip_full(&own, "lost");
    } else {
        pa_clip_full(&own, "lost");
    }
    kit_show_start(&show_fx, "angry end", SHOW_END, N_SHOW(SHOW_END));
    if (run.phase == PHASE_MB)
        pm_snprintf(b, sizeof b, "%u BABY JACKPOT%s  -  %u LOCK%s", run.babies, run.babies == 1 ? "" : "S", run.locks,
                    run.locks == 1 ? "" : "S");
    else
        pm_snprintf(b, sizeof b, "THE TRAIL WAITS AT %s", run.place < N_PLACES ? PLACE[run.place].place : "BABY");
    kit_hud_title(&hud, run.full ? "GODZILLA AND BABY" : "GODZILLA ANGRY TOTAL", b);
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, kit_num(a, sizeof a, run.total), " ");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, %u lock(s), %u baby jackpot(s), total %llu, score %llu", why,
           run.phase == PHASE_MB ? (run.full ? "the multiball after BABY FOUND" : "a smaller multiball")
                                 : "the chase", run.locks, run.babies, (unsigned long long)run.total,
           (unsigned long long)pm_score(p));
}

/* a place's clock ran out: the locks become a multiball (EHoH: failing still pays), or the trail goes cold */
static void time_out(void)
{
    if (run.locks) {
        pm_log("%s's clock ran out with %u lock(s): they become a %u-ball multiball", run.place < N_PLACES ?
               PLACE[run.place].place : "BABY", run.locks, run.locks + 1);
        kit_hud_award(&hud, 3000, "THE LOCKS BREAK LOOSE", "ANGRY MULTIBALL");
        sound(CUE_LOCK);
        start_multiball(run.locks + 1, "the clock ran out");
        show();
        return;
    }
    pm_log("the trail goes cold at %s: still angry, the %s starts the chase again", PLACE[run.place].place, START_SHOT);
    forget_trail(run.player);
    end("the trail went cold");
}

/* ---- shots ------------------------------------------------------------------------------------------- */
static void chase_shot(uint64_t shot)
{
    char a[24];
    unsigned i;
    if (run.place >= N_PLACES) {                    /* BABY: the Building */
        if (start_mask && (shot & start_mask) && kit_fresh(&db, start_mask)) baby_found();
        return;
    }
    if (run.lock_lit) {
        uint64_t m = pm_shot(PLACE[run.place].lock);
        if (m && (shot & m) && kit_fresh(&db, m)) lock_made();
        return;
    }
    for (i = 0; i < MAX_LIT && PLACE[run.place].shots[i]; i++) {
        uint64_t m = pm_shot(PLACE[run.place].shots[i]), got;
        if (!m || !(shot & m) || (run.made_mask & m) || !kit_fresh(&db, m)) continue;
        got = pay(shot_value());
        run.made++;
        run.made_mask |= m;
        run.jackpot += got / JACKPOT_SHARE;
        if (kit_timer_at_least(&run.clock, LIT_SHOT_FLOOR)) pm_log("the clock back up to %d s", LIT_SHOT_FLOOR);
        pm_log("%s: %s +%llu, the jackpot %llu", PLACE[run.place].place, PLACE[run.place].shots[i],
               (unsigned long long)got, (unsigned long long)run.jackpot);
        kit_hud_award(&hud, 1500, PLACE[run.place].place, kit_num(a, sizeof a, got));
        if (!(place_shots(run.place) & ~run.made_mask)) {
            run.lock_lit = 1;
            pm_log("LOCK IS LIT at %s", PLACE[run.place].lock);
        }
    }
}

static void mb_shot(uint64_t shot)
{
    char a[24], s[KIT_HUD_WORDS];
    unsigned i;
    for (i = 0; i < N_JP; i++) {
        uint64_t got;
        if (!jp_mask[i] || !(shot & jp_mask[i]) || !kit_fresh(&db, jp_mask[i])) continue;
        if (i == run.baby) {
            got = pay(run.jackpot * run.mult);
            run.babies++;
            pm_log("BABY JACKPOT %u at %s: +%llu (x%u)", run.babies, JP[i], (unsigned long long)got, run.mult);
            pm_snprintf(s, sizeof s, "BABY JACKPOT X%u", run.mult);
            kit_hud_award(&hud, 2000, s, kit_num(a, sizeof a, got));
            sound(run.mult >= 4 ? CUE_SUPER : CUE_JACKPOT);
            run.mult = 1;
            run.baby = (run.baby + 1 + next_random(N_JP - 1)) % N_JP;
            run.baby_at = pm_ms();
        } else {
            got = pay(OTHER_SHOT);
            if (run.mult < MULT_MAX) run.mult++;
            pm_log("%s: +%llu, BABY x%u", JP[i], (unsigned long long)got, run.mult);
            pm_snprintf(s, sizeof s, "BABY X%u", run.mult);
            kit_hud_award(&hud, 1200, s, JP_SAYS[run.baby]);
        }
    }
}

static void on_shot(uint64_t shot)
{
    unsigned p = pm_player();
    if (!pm_in_game() || p < 1 || p > 4) return;
    if (shot & 1ull) {                                /* a playfield switch was hit */
        meter_wait = 0;
        if (run.on && p == run.player && run.phase == PHASE_CHASE) run.super += SUPER_PER_SWITCH;
        else if (!run.on) rage_switch(p);
    }
    if (!run.on) {
        if (!ready[p] || !start_mask || !(shot & start_mask) || !kit_fresh(&db, start_mask)) return;
        if (kit_just_ended(AFTER_ANOTHER_MS)) {
            pm_log("not started (the Building): it just ended another mode of ours - still lit, the next Building "
                   "starts it");
            return;
        }
        start("the Building, GODZILLA ANGRY lit");   /* another of ours running: kit_begin says no, still lit */
        return;
    }
    if (p != run.player) return;
    if (run.phase == PHASE_CHASE) chase_shot(shot);
    else mb_shot(shot);
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    start_mask = pm_shot(START_SHOT);
    for (i = 0; i < N_JP; i++) {
        jp_mask[i] = pm_shot(JP[i]);
        if (!jp_mask[i]) pm_log("this port has no \"%s\"", JP[i]);
    }
    rnd ^= (unsigned)pm_ms();
    pa_load(&own);
    pm_log("ready on %s %s: every switch hit fills the RAGE meter (%d levels from %d hits); %s (0x%llx) starts "
           "the chase; multiball %s", pm_game(), pm_version(), LEVELS, LEVEL_FIRST, START_SHOT,
           (unsigned long long)start_mask, pm_can(PM_CAN_MULTIBALL) ? "yes" : "NOT in this port");
}

static void check_triggers(void)
{
    char name[48];
    unsigned p = pm_player(), v = 0, i;
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger(FOLDER ".light") && p >= 1 && p <= 4) {
        ready[p] = 1;
        level[p] = LEVELS;
        pm_log("GODZILLA IS ANGRY for player %u (trigger file)", p);
    }
    if (pm_trigger_text(FOLDER ".rage", name, sizeof name) && p >= 1 && p <= 4) {
        for (i = 0; name[i] >= '0' && name[i] <= '9'; i++) v = v * 10 + (unsigned)(name[i] - '0');
        pm_log("rage trigger: %u switch hits", v);
        while (v--) rage_switch(p);
    }
    if (pm_trigger_text(FOLDER ".mb", name, sizeof name) && run.on && run.phase == PHASE_CHASE) {
        for (i = 0; name[i] >= '0' && name[i] <= '9'; i++) v = v * 10 + (unsigned)(name[i] - '0');
        start_multiball(v ? v : 2, "trigger file");
    }
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void run_tick(void)
{
    int balls;
    if (run.phase == PHASE_CHASE) {
        if (kit_timer_tick(&run.clock)) {
            time_out();
            if (!run.on) return;
        }
        show();
        return;
    }
    balls = pm_can(PM_CAN_MULTIBALL) ? pm_balls_in_play() : 1;
    if (balls >= 2) {
        run.served_two = 1;
        run.one_ball_since = 0;
    } else if (pm_ms() - run.started > (unsigned long)MB_SAVE_S * 1000u + END_GRACE_MS) {
        if (!run.one_ball_since) run.one_ball_since = pm_ms();
        else if (pm_ms() - run.one_ball_since >= ONE_BALL_MS) {
            end(run.served_two ? "one ball left" : "no second ball was served");
            return;
        }
    }
    if (pm_ms() - run.baby_at >= BABY_MOVES_MS) {
        run.baby = (run.baby + 1 + next_random(N_JP - 1)) % N_JP;
        run.baby_at = pm_ms();
    }
    show();
}

static void on_tick(void)
{
    unsigned p;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    if (++poll % KIT_POLL == 0) {
        check_triggers();
        ready_light();
    }
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) {
            hits[p] = level[p] = plays[p] = 0;
            ready[p] = 0;
            forget_trail(p);
        }
        tilted = meter_wait = 0;
        pm_log("new game: every RAGE meter empty");
    }
    if (poll % 6 == 0) mb_now = pm_in_game() && multiball_on();
    meter_tick();
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
    tilted = 0;
    meter_wait = 1;                                /* the bonus has the glass: the meter waits for a switch */
}

static void on_event(unsigned id)
{
    if (kit_is_tilt(id)) {
        end("tilted");
        kit_end_now();
        tilted = 1;
    }
}

static const struct pm_mode godzilla_angry = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(godzilla_angry);
