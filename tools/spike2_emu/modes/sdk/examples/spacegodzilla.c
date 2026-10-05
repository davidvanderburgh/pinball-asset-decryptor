/* spacegodzilla.c - SPACEGODZILLA: a multiball of crystal LOCKS that are harder to light each time (PAD-379, for
 * Godzilla). Modelled on Lyman Sheats' lock ladders: Elvira's House of Horrors' Garage (one hit lights all three
 * locks, then one hit per lock, then two) and its three multiballs in turn, Batman '66's Villain Multiball,
 * Metallica's Casket (a super worth the sum of the jackpots), and his supers that add a ball the first times.
 *
 * Godzilla vs. SpaceGodzilla (1994): SpaceGodzilla plants crystal towers across Fukuoka to draw power;
 * Godzilla and M.O.G.U.E.R.A. tear them down before they strike at him.
 *
 *   LIGHT A LOCK   The SHIELD targets. The first multiball: any shield target lights all three locks. The
 *                  second: each shield target hit lights one lock. From the third: two shield hits a lock.
 *   LOCK           The BIG LOOP while a lock is lit: SpaceGodzilla plants CRYSTAL 1, 2, 3 (250,000 a crystal,
 *                  times its number). The locks are virtual (the ball goes on) and wait across balls. Nothing
 *                  lights or locks during a multiball or while another mode of ours runs.
 *   START          The third crystal starts CRYSTAL MULTIBALL: 3 balls, a 15 s ball save. While one of the
 *                  game's own modes runs it waits, still ready: the next Big loop after it starts it.
 *   THE TOWERS     Three crystal towers stand on the LEFT RAMP, the BUILDING and the RIGHT RAMP. Each JACKPOT
 *                  (the base, +100,000 a jackpot) cracks its tower; a tower falls after 2 jackpots. All three
 *                  down lights the SUPER JACKPOT at the BIG LOOP for 20 s: worth every jackpot since the last
 *                  super. The first three supers add a ball. Then the towers grow back, each one jackpot
 *                  stronger (the super's window running out grows them back too).
 *   IN TURN        Each multiball is the next of three (EHoH's garage multiballs):
 *                    1 CRYSTAL TOWERS  jackpots from 1,000,000
 *                    2 M.O.G.U.E.R.A.  from 1,500,000, towers one jackpot stronger, and every SHIELD target
 *                                      is a spiral grenade: +250,000 on the jackpot for the rest of it
 *                    3 SPACE BEAST     from 2,000,000, towers stronger, and every 5th jackpot lights the
 *                                      super as well (EHoH's Attic Attack)
 *   ENDS           One ball left (after the ball save and 3 s more), a tilt, one of the game's own modes
 *                  beginning, leaving the game.
 *   THE GLASS      SpaceGodzilla arriving, full screen; the crystal towers glowing over Fukuoka behind the score
 *                  panel; TOWERS, JACKPOT and SUPER at the edges, the towers' strength on the right edge's
 *                  gauge, the super's window in the badge. A jackpot plays a tower cracking, a fallen tower
 *                  its collapse; the super and the endings are full screen.
 *   INSERTS        A lit lock: the BIG LOOP blinking purple. The towers purple (solid while strong, blinking on
 *                  their last jackpot); the super: the BIG LOOP flashing white; M.O.G.U.E.R.A.'s shields
 *                  pulsing cyan.
 *   DISPLAY        Priority 190 (a multiball of ours).
 *
 * Emulator test triggers: /dump/spacegodzilla.start (the multiball now), .stop, .light (light the locks),
 * .lock (plant a crystal), .shot "<shot name>".
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "SPACEGODZILLA"
#define FOLDER             "spacegodzilla"
#define LOCK_SHOT          "Big loop"
#define LOCKS              3
#define LOCK_AWARD         250000ull
#define BALLS              3
#define BALL_SAVE_S        15
#define END_GRACE_MS       3000
#define ONE_BALL_MS        2000
#define TOWER_HITS         2              /* the first multiball's towers; later ones one more */
#define JACKPOT_STEP       100000ull
#define SUPER_SECONDS      20
#define SUPERS_ADD_A_BALL  3
#define GRENADE            250000ull
#define BEAST_EVERY        5
#define TOTAL_SHOWN_MS     10000

#define N_TOWERS 3
static const char *const TOWER[N_TOWERS] = { "Left ramp", "Building", "Right ramp" };
static const char *const TOWER_SAYS[N_TOWERS] = { "LEFT RAMP", "BUILDING", "RIGHT RAMP" };
static const char *const SHIELDS[3] = { "Shield target left", "Shield target center", "Shield target right" };
#define N_KINDS 3
static const struct { const char *name; uint64_t base; } KIND[N_KINDS] = {
    { "CRYSTAL TOWERS", 1000000ull }, { "M.O.G.U.E.R.A.", 1500000ull }, { "SPACE BEAST", 2000000ull },
};

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t tower_mask[N_TOWERS], lock_mask, shield_mask;
static unsigned crystals[5], lit[5], shield_hits[5], plays[5];
static int mb_ready[5];                              /* three crystals planted: the next Big loop starts it */
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps, lock_lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;
static unsigned poll;
static int mb_now;

static struct {
    int on, served_two, super_lit;
    unsigned player, kind, hp[N_TOWERS], strength, jackpots, supers, since_super, added;
    uint64_t base, sum, total;
    unsigned long started, one_ball_since;
    struct kit_timer clock;
} run;

/* ---- light shows: crystal purple and blue ------------------------------------------------------- */
#define SG_PURPLE      PM_RGB(190, 40, 255)
#define SG_BLUE        PM_RGB(40, 90, 255)
#define SG_DEEP        PM_RGB(30, 0, 60)
static const struct kit_fx_step SHOW_LOCK[] = {      /* a crystal erupts */
    { KIT_FX_IMPLODE,   600, SG_PURPLE, SG_DEEP, KIT_AT_TOP, 0, KIT_GI_KEEP },
    { KIT_FX_SPARKLE,   500, KIT_WHITE, SG_PURPLE, KIT_AT_CENTER, 0, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  300, SG_PURPLE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_SPARKLE,   900, KIT_WHITE, SG_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },        /* stars */
    { KIT_FX_SWEEP_DOWN, 700, SG_PURPLE, SG_BLUE, KIT_AT_TOP, 0, KIT_GI_DARK },          /* he descends */
    { KIT_FX_SPIN,     1200, KIT_WHITE, SG_PURPLE, KIT_AT_CENTER, 120, KIT_GI_DARK },    /* the crystals turn */
    { KIT_FX_FADE_OUT,  400, SG_PURPLE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_TOWER[] = {
    { KIT_FX_BURST,     700, KIT_WHITE, SG_PURPLE, KIT_AT_CENTER, 0, KIT_GI_FLASH },
    { KIT_FX_FADE_OUT,  300, SG_PURPLE, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_SUPER[] = {
    { KIT_FX_IMPLODE,   700, KIT_WHITE, SG_BLUE, KIT_AT_TOP, 0, KIT_GI_FLASH },
    { KIT_FX_RAINBOW,  1200, 0, 0, KIT_AT_CENTER, 70, KIT_GI_KEEP },
    { KIT_FX_STROBE,    400, KIT_WHITE, SG_PURPLE, KIT_AT_CENTER, 50, KIT_GI_FLASH },
};
static const struct kit_fx_step SHOW_END[] = {
    { KIT_FX_SPARKLE,   900, SG_PURPLE, SG_DEEP, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_FADE_OUT, 1000, SG_DEEP, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_SHOW(a) (int)(sizeof (a) / sizeof (a)[0])

/* ---- sound: its own music, calls and clips (modes/spacegodzilla/assets.json) -------------------- */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_LIT, CUE_LOCK, CUE_START, CUE_JACKPOT, CUE_TOWER, CUE_SUPER, CUE_ADD, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_LIT:      pa_call(&own, "lit"); break;               /* a lock is lit: the crystals hum */
    case CUE_LOCK:     pa_call(&own, "lock"); break;              /* a crystal planted */
    case CUE_START:    pa_start(&own); break;                     /* his theme, his arrival, the towers */
    case CUE_JACKPOT:
        pa_call(&own, "jackpot");
        pa_clip_event(&own, "jackpot");
        break;
    case CUE_TOWER:                                               /* a tower falls */
        pa_call(&own, "tower");
        pa_clip_event(&own, "tower");
        break;
    case CUE_SUPER:
        pa_call(&own, "super");
        pa_clip_full(&own, "super");
        break;
    case CUE_ADD:      pa_call(&own, "add"); break;
    case CUE_END:      pa_end(&own); break;
    }
}

static unsigned hits_a_lock(unsigned p)      /* 0 = one hit lights every lock left */
{
    return plays[p] == 0 ? 0 : plays[p] == 1 ? 1 : 2;
}

static int multiball_on(void)
{
    const char *what = 0;
    if (pm_can(PM_CAN_MULTIBALL) && pm_balls_in_play() >= 2) return 1;
    return kit_stock_busy(PM_STOCK_MULTIBALL, MODE_NAME, &what);
}

/* ---- the multiball ----------------------------------------------------------------------------- */
static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static unsigned towers_left(void)
{
    unsigned i, n = 0;
    for (i = 0; i < N_TOWERS; i++) n += run.hp[i] > 0;
    return n;
}

static void towers_grow(void)
{
    unsigned i;
    run.strength++;
    for (i = 0; i < N_TOWERS; i++) run.hp[i] = run.strength;
    pm_log("the crystal towers grow back: %u jackpots each", run.strength);
}

static void show_lamps(void)
{
    unsigned i;
    kit_lamps_begin(&lamps);
    for (i = 0; i < N_TOWERS; i++)
        if (run.hp[i]) kit_lamps_shot(&lamps, tower_mask[i], SG_PURPLE, run.hp[i] == 1 ? PM_LAMP_BLINK : PM_LAMP_SOLID, 300);
    if (run.super_lit)
        kit_lamps_shot(&lamps, lock_mask, KIT_WHITE, PM_LAMP_BLINK,
                       kit_hurry_ms((unsigned long)kit_timer_seconds(&run.clock) * 1000u, SUPER_SECONDS * 1000u));
    if (run.kind == 1) kit_lamps_shot(&lamps, shield_mask, KIT_CYAN, PM_LAMP_PULSE, 900);
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char v[24], s[24], n[24];
    unsigned i, hp = 0;
    show_lamps();
    for (i = 0; i < N_TOWERS; i++) hp += run.hp[i];
    kit_hud_title(&hud, run.kind ? KIND[run.kind].name : "SPACEGODZILLA",
                  run.super_lit ? "SUPER JACKPOT: SHOOT THE BIG LOOP" : run.kind == 1 ?
                  "SHATTER TOWERS  -  SHIELDS RAISE JACKPOTS" : "SHATTER THE CRYSTAL TOWERS");
    pm_snprintf(n, sizeof n, "%u LEFT", towers_left());
    kit_hud_counter(&hud, 0, "TOWERS", n, KIND[run.kind].name);
    kit_hud_counter(&hud, 1, "JACKPOT", kit_short(v, sizeof v, run.base + JACKPOT_STEP * run.jackpots), " ");
    kit_hud_counter(&hud, 2, "SUPER", kit_short(s, sizeof s, run.sum), run.super_lit ? "BIG LOOP" : "THE SUM");
    kit_hud_timer(&hud, run.super_lit ? (int)kit_timer_seconds(&run.clock) : -1);
    kit_hud_gauge(&hud, (int)(hp > 9 ? 9 : hp), "CRYSTALS");
}

static int start(const char *why)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_wait_game(MODE_NAME, why, "still ready: the next Big loop after it starts it")) {
        mb_ready[p] = 1;
        return 0;
    }
    if (!pm_can(PM_CAN_MULTIBALL)) {
        pm_log("not started (%s): this port cannot serve a multiball", why);
        return 0;
    }
    if (!kit_begin(MODE_NAME)) {
        mb_ready[p] = 1;
        return 0;
    }
    if (!pm_multiball_start(BALLS, BALL_SAVE_S)) {
        pm_log("not started (%s): the game refused the multiball - still ready", why);
        mb_ready[p] = 1;
        kit_end();
        return 0;
    }
    kit_display(KIT_DISPLAY_WIZARD);
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);
    run.on = 1;
    run.player = p;
    run.kind = plays[p] < N_KINDS ? plays[p] : N_KINDS - 1;
    run.base = KIND[run.kind].base;
    run.strength = TOWER_HITS - 1 + (run.kind ? 1 : 0);
    towers_grow();
    run.jackpots = run.supers = run.since_super = run.added = 0;
    run.sum = run.total = 0;
    run.super_lit = run.served_two = 0;
    run.started = pm_ms();
    run.one_ball_since = 0;
    mb_ready[p] = 0;
    crystals[p] = lit[p] = shield_hits[p] = 0;
    plays[p]++;
    kit_lamps_begin(&lock_lamps);
    kit_lamps_commit(&lock_lamps);
    kit_hud_begin(&hud, "SPACEGODZILLA", "");
    show();
    kit_hud_award(&hud, 3000, KIND[run.kind].name, "MULTIBALL");
    kit_show_start(&show_fx, "spacegodzilla start", SHOW_START, N_SHOW(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, %s, %d balls, towers %u jackpots each, jackpots from %llu, score %llu", why, p,
           KIND[run.kind].name, BALLS, run.hp[0], (unsigned long long)run.base, (unsigned long long)pm_score(p));
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
    pa_clip_full(&own, run.supers ? "won" : "lost");
    kit_show_start(&show_fx, "spacegodzilla end", SHOW_END, N_SHOW(SHOW_END));
    pm_snprintf(b, sizeof b, "%u JACKPOT%s  -  %u SUPER%s", run.jackpots, run.jackpots == 1 ? "" : "S", run.supers,
                run.supers == 1 ? "" : "S");
    kit_hud_title(&hud, run.supers ? "SPACEGODZILLA FALLS" : "SPACEGODZILLA ESCAPES", b);
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, kit_num(a, sizeof a, run.total), " ");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, %u jackpot(s), %u super(s), %u ball(s) added, total %llu, score %llu", why,
           KIND[run.kind].name, run.jackpots, run.supers, run.added, (unsigned long long)run.total,
           (unsigned long long)pm_score(run.player));
}

static void light_super(const char *why)
{
    if (run.super_lit) return;
    run.super_lit = 1;
    kit_timer_set(&run.clock, SUPER_SECONDS, 1);
    pm_log("SUPER JACKPOT lit at %s for %d s (%s): %llu", LOCK_SHOT, SUPER_SECONDS, why, (unsigned long long)run.sum);
    kit_hud_award(&hud, 2500, "SUPER JACKPOT IS LIT", "SHOOT THE BIG LOOP");
}

static void mb_shot(uint64_t shot)
{
    char a[24], s[KIT_HUD_WORDS];
    unsigned i;
    if (run.kind == 1) {                                           /* M.O.G.U.E.R.A.'s spiral grenades */
        for (i = 0; i < 3; i++) {
            uint64_t m = pm_shot(SHIELDS[i]);
            if (!m || !(shot & m) || !kit_fresh(&db, m)) continue;
            run.base += GRENADE;
            pm_log("spiral grenade at %s: the jackpot base %llu", SHIELDS[i], (unsigned long long)run.base);
            kit_hud_award(&hud, 1200, "SPIRAL GRENADE", "+250,000 ON EVERY JACKPOT");
            sound(CUE_ADD);
        }
    }
    if (run.super_lit && lock_mask && (shot & lock_mask) && kit_fresh(&db, lock_mask)) {
        uint64_t got = pay(run.sum);
        run.supers++;
        run.super_lit = 0;
        run.clock.ticks = 0;
        pm_log("SUPER JACKPOT %u at %s: +%llu (the sum of %u jackpots)", run.supers, LOCK_SHOT,
               (unsigned long long)got, run.since_super);
        kit_hud_award(&hud, 3000, "SUPER JACKPOT", kit_num(a, sizeof a, got));
        kit_show_start(&show_fx, "super", SHOW_SUPER, N_SHOW(SHOW_SUPER));
        sound(CUE_SUPER);
        if (run.supers <= SUPERS_ADD_A_BALL && pm_multiball_add(1, 10)) {
            run.added++;
            pm_log("the super adds a ball (%u)", run.added);
            sound(CUE_ADD);
        }
        run.sum = 0;
        run.since_super = 0;
        if (!towers_left()) towers_grow();
        return;
    }
    for (i = 0; i < N_TOWERS; i++) {
        uint64_t got;
        if (!tower_mask[i] || !(shot & tower_mask[i]) || !run.hp[i] || !kit_fresh(&db, tower_mask[i])) continue;
        got = pay(run.base + JACKPOT_STEP * run.jackpots);
        run.jackpots++;
        run.since_super++;
        run.sum += got;
        run.hp[i]--;
        pm_log("JACKPOT %u at %s: +%llu, the tower %s", run.jackpots, TOWER[i], (unsigned long long)got,
               run.hp[i] ? "cracks" : "FALLS");
        if (run.hp[i]) {
            kit_hud_award(&hud, 1600, "JACKPOT", kit_num(a, sizeof a, got));
            sound(CUE_JACKPOT);
        } else {
            pm_snprintf(s, sizeof s, "%s TOWER FALLS", TOWER_SAYS[i]);
            kit_hud_award(&hud, 2000, s, kit_num(a, sizeof a, got));
            kit_show_start(&show_fx, "tower falls", SHOW_TOWER, N_SHOW(SHOW_TOWER));
            sound(CUE_TOWER);
        }
        if (!towers_left()) light_super("every tower down");
        else if (run.kind == 2 && run.since_super && run.since_super % BEAST_EVERY == 0) light_super("5 jackpots");
    }
}

/* ---- locks ------------------------------------------------------------------------------------- */
static void lock_light(void)
{
    unsigned p = pm_player();
    int want = !run.on && !show_fx.on && !kit_running && lock_mask && pm_in_game() && p >= 1 && p <= 4 &&
               (lit[p] || mb_ready[p]) && !mb_now;
    kit_lamps_begin(&lock_lamps);
    if (want) kit_lamps_shot(&lock_lamps, lock_mask, SG_PURPLE, PM_LAMP_BLINK, mb_ready[p] ? 150 : 400);
    kit_lamps_commit(&lock_lamps);
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_HUD_WORDS];
    unsigned i;
    if (mb_now || kit_running) return;                 /* no lighting or locking during a multiball or a mode */
    if (lock_mask && (shot & lock_mask) && kit_fresh(&db, lock_mask)) {
        if (mb_ready[p]) {
            start("the Big loop, three crystals planted");
            return;
        }
        if (lit[p]) {
            uint64_t got;
            lit[p]--;
            crystals[p]++;
            got = pm_score_add(p, LOCK_AWARD * crystals[p]);
            pm_log("CRYSTAL %u PLANTED at %s (player %u): +%llu", crystals[p], LOCK_SHOT, p, (unsigned long long)got);
            sound(CUE_LOCK);
            if (!kit_running && !show_fx.on) kit_show_start(&show_fx, "crystal", SHOW_LOCK, N_SHOW(SHOW_LOCK));
            if (crystals[p] >= LOCKS) {
                kit_hud_note(&hud, 2500, "CRYSTAL 3 PLANTED", "SPACEGODZILLA ARRIVES");
                start("the third crystal");
            } else {
                pm_snprintf(line, sizeof line, "CRYSTAL %u PLANTED", crystals[p]);
                kit_hud_note(&hud, 2000, line, lit[p] ? "ANOTHER LOCK IS LIT" : "SHIELDS LIGHT THE NEXT LOCK");
            }
        }
        return;
    }
    if (crystals[p] + lit[p] >= LOCKS) return;
    for (i = 0; i < 3; i++) {
        uint64_t m = pm_shot(SHIELDS[i]);
        unsigned need = hits_a_lock(p);
        if (!m || !(shot & m) || !kit_fresh(&db, m)) continue;
        if (!need) {
            lit[p] = LOCKS - crystals[p];
            pm_log("%s: every lock is lit (%u) for player %u", SHIELDS[i], lit[p], p);
        } else if (++shield_hits[p] >= need) {
            shield_hits[p] = 0;
            lit[p]++;
            pm_log("%s: a lock is lit (%u lit, %u planted) for player %u", SHIELDS[i], lit[p], crystals[p], p);
        } else {
            pm_log("%s: %u of %u for the next lock (player %u)", SHIELDS[i], shield_hits[p], need, p);
            kit_hud_note(&hud, 1500, "CRYSTALS GROWING", "ONE MORE SHIELD LIGHTS A LOCK");
            continue;
        }
        kit_hud_note(&hud, 2000, lit[p] > 1 ? "LOCKS ARE LIT" : "LOCK IS LIT", "SHOOT THE BIG LOOP");
        sound(CUE_LIT);
        if (crystals[p] + lit[p] >= LOCKS) return;
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
    if (p != run.player) return;
    mb_shot(shot);
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned i;
    for (i = 0; i < N_TOWERS; i++) {
        tower_mask[i] = pm_shot(TOWER[i]);
        if (!tower_mask[i]) pm_log("this port has no \"%s\"", TOWER[i]);
    }
    for (i = 0; i < 3; i++) shield_mask |= pm_shot(SHIELDS[i]);
    lock_mask = pm_shot(LOCK_SHOT);
    pa_load(&own);
    pm_log("ready on %s %s: the shields (0x%llx) light the locks, %s (0x%llx) locks; towers 0x%llx 0x%llx 0x%llx; "
           "multiball %s", pm_game(), pm_version(), (unsigned long long)shield_mask, LOCK_SHOT,
           (unsigned long long)lock_mask, (unsigned long long)tower_mask[0], (unsigned long long)tower_mask[1],
           (unsigned long long)tower_mask[2], pm_can(PM_CAN_MULTIBALL) ? "yes" : "NOT in this port");
}

static void check_triggers(void)
{
    char name[48];
    unsigned p = pm_player();
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger(FOLDER ".light") && p >= 1 && p <= 4) {
        lit[p] = LOCKS - crystals[p];
        pm_log("every lock lit for player %u (trigger file)", p);
    }
    if (pm_trigger(FOLDER ".lock") && p >= 1 && p <= 4 && !lit[p]) lit[p] = 1;
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void run_tick(void)
{
    int balls = pm_balls_in_play();
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
    if (run.super_lit && kit_timer_tick(&run.clock)) {
        run.super_lit = 0;
        pm_log("the super jackpot's window ran out: the sum %llu waits for the next", (unsigned long long)run.sum);
        kit_hud_award(&hud, 2000, "THE CRYSTALS GROW BACK", " ");
        if (!towers_left()) towers_grow();
    }
    show();
}

static void on_tick(void)
{
    unsigned p;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    if (++poll % 6 == 0) mb_now = pm_in_game() && multiball_on();
    if (poll % KIT_POLL == 0) {
        check_triggers();
        lock_light();
    }
    if (kit_new_game(&game)) {
        for (p = 0; p < 5; p++) crystals[p] = lit[p] = shield_hits[p] = plays[p] = 0, mb_ready[p] = 0;
        pm_log("new game: the crystals cleared");
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

static const struct pm_mode spacegodzilla = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(spacegodzilla);
