/* destoroyah.c - DESTOROYAH: waves of aggregates that ADVANCE down the playfield (PAD-379, for Godzilla).
 * Modelled on Lyman Sheats' Horde in The Walking Dead (2014): walkers advance on you, a kill is worth more the
 * closer it is (up to 4x), each wave needs one more kill, a cleared wave pays a super worth the wave.
 *
 * Godzilla vs. Destoroyah (1995): the micro-oxygen of the Oxygen Destroyer woke something in Tokyo Bay. The
 * crab-like aggregates swarm into the city, then merge into Destoroyah's perfect form.
 *
 *   LIGHT IT   Spin the CENTER spinner 30 times (every spin counts). It starts at once. Then 40, 50...
 *   THE SWARM  Aggregates come over the top of the playfield at the POWERLINES (far, x1) and advance every few
 *              seconds: to the RAMPS, the BUILDING or the BIG LOOP (near, x2), to the MASER, the SHIELDS or the
 *              CAPTIVE BALL (close, x4), and then into the city. Up to two at a time. A kill pays 1,000,000
 *              (+250,000 a wave) times how close it was: let one come closer for more, at your risk.
 *   WAVES      Wave 1 needs 3 kills, wave 2 needs 4, wave 3 needs 5; they advance every 7, 6 and 5 s. A
 *              cleared wave pays the WAVE SUPER: every kill of the wave again.
 *   THE CITY   An aggregate that gets past the close shots hits the city. Three hits and Destoroyah wins.
 *   PERFECT    After wave 3 Destoroyah stands up in his PERFECT FORM on the BUILDING: 25 s, three hits of
 *   FORM       5,000,000; the third is the SUPER JACKPOT, every kill of the mode again.
 *   ENDS       The perfect form defeated (won); three city hits or the perfect form's clock (lost); a drain;
 *              a tilt; one of the game's own modes beginning.
 *   THE GLASS  The aggregates emerging, full screen; the swarm in the city at night behind the score panel;
 *              WAVE, KILLS and CITY at the edges, the wave's kills on the right edge's gauge, the perfect
 *              form's clock in the badge. A kill plays an aggregate blown apart (every few seconds), a city
 *              hit an aggregate's attack, a cleared wave the swarm merging; the perfect form and the endings
 *              are full screen.
 *   INSERTS    Each aggregate's shot: far yellow and solid, near orange and blinking, close red and
 *              flickering. The perfect form: the BUILDING blinking red, faster as its clock runs out.
 *   SHIELDS    On Godzilla Premium/LE the shield platform turns toward the player as it starts and back away
 *              when it ends (the game's own mode beginning keeps it as that mode left it). A Pro's shields are fixed.
 *              No aggregate comes to a shield until they face the player.
 *   DISPLAY    Priority 180.
 *
 * Emulator test triggers: /dump/destoroyah.start, .stop, .shot "<shot name>", .boss (the perfect form now).
 */
#include "intricate_kit.h"
#include "pad_mode_assets.h"

/* ---- the knobs ------------------------------------------------------------------------------ */
#define MODE_NAME          "DESTOROYAH"
#define FOLDER             "destoroyah"
#define SPIN_SHOT          "Top spinner"
#define BOSS_SHOT          "Building"
#define SPINS_FIRST        30
#define SPINS_STEP         10
#define WAVES              3
#define FIRST_NEED         3              /* kills in wave 1; one more a wave */
#define ALIVE_MAX          2
#define ADVANCE_FIRST_MS   7000           /* one second faster a wave */
#define SPAWN_AFTER_MS     1200
#define WAVE_GAP_MS        2500
#define KILL_VALUE         1000000ull
#define KILL_WAVE_STEP     250000ull
#define CITY_HITS          3
#define BOSS_SECONDS       25
#define BOSS_HITS          3
#define BOSS_HIT_VALUE     5000000ull
#define KILL_CLIP_GAP_MS   4000
#define TOTAL_SHOWN_MS     10000

#define RINGS 3
static const char *const RING_NAME[RINGS] = { "FAR", "NEAR", "CLOSE" };
static const unsigned RING_MULT[RINGS] = { 1, 2, 4 };
static const char *const RING_SHOTS[RINGS][5] = {
    { "Powerline left", "Powerline center", "Powerline right", 0, 0 },
    { "Left ramp", "Right ramp", "Big loop", "Building", 0 },
    { "Maser target", "Shield target left", "Shield target center", "Shield target right", "Godzilla target" },
};

/* ---- state ----------------------------------------------------------------------------------- */
static uint64_t ring_mask[RINGS][5], spin_mask, boss_mask, shield_mask;
static unsigned ring_n[RINGS];
static unsigned spins[5], plays[5];
static int waiting[5];
static struct kit_db db;
static struct kit_game game;
static struct kit_lamps lamps;
static struct kit_hud hud = { .slug = FOLDER };
static struct kit_show show_fx;
static struct kit_shields shields;           /* PAD-379: the Premium's shield platform, turned toward the player */
static unsigned poll, rnd = 1995;

struct agg { int on; unsigned ring, at; unsigned long step_at; };
enum { PHASE_SWARM, PHASE_GAP, PHASE_BOSS };
static struct {
    int on, phase, won;
    unsigned player, wave, kills, city, boss_hits, all_kills;
    struct agg a[ALIVE_MAX];
    uint64_t wave_total, kill_total, total;
    unsigned long spawn_at, gap_until, kill_clip_at;
    struct kit_timer clock;
} run;

/* ---- light shows: micro-oxygen red and black ------------------------------------------------------ */
#define DE_RED         PM_RGB(255, 0, 30)
#define DE_DARK        PM_RGB(40, 0, 10)
#define DE_GLOW        PM_RGB(255, 120, 0)
static const struct kit_fx_step SHOW_START[] = {
    { KIT_FX_SPARKLE,  1000, DE_RED, DE_DARK, KIT_AT_TOP, 0, KIT_GI_DARK },          /* eyes in the dark */
    { KIT_FX_SWEEP_DOWN, 800, DE_RED, DE_DARK, KIT_AT_TOP, 0, KIT_GI_DARK },         /* the swarm comes down */
    { KIT_FX_PULSE,     700, DE_RED, DE_DARK, KIT_AT_CENTER, 180, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  300, DE_RED, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_WAVE[] = {     /* the swarm merges */
    { KIT_FX_IMPLODE,   800, DE_GLOW, DE_DARK, KIT_AT_CENTER, 0, KIT_GI_FLASH },
    { KIT_FX_FADE_OUT,  400, DE_GLOW, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_CITY[] = {
    { KIT_FX_STROBE,    400, DE_RED, 0, KIT_AT_CENTER, 60, KIT_GI_FLASH },
};
static const struct kit_fx_step SHOW_BOSS[] = {
    { KIT_FX_BOLTS,     900, DE_RED, DE_DARK, KIT_AT_CENTER, 130, KIT_GI_DARK },
    { KIT_FX_BURST,     800, DE_GLOW, DE_RED, KIT_AT_BUILDING, 0, KIT_GI_DARK },        /* he stands up */
    { KIT_FX_SPIN,      900, DE_RED, DE_DARK, KIT_AT_BUILDING, 90, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_WON[] = {
    { KIT_FX_BURST,     800, KIT_WHITE, DE_GLOW, KIT_AT_BUILDING, 0, KIT_GI_FLASH },
    { KIT_FX_FIRE,     1200, DE_GLOW, DE_RED, KIT_AT_CENTER, 0, KIT_GI_KEEP },
    { KIT_FX_FADE_OUT,  700, DE_GLOW, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
static const struct kit_fx_step SHOW_END[] = {
    { KIT_FX_SPARKLE,   900, DE_RED, DE_DARK, KIT_AT_CENTER, 0, KIT_GI_DARK },
    { KIT_FX_FADE_OUT,  900, DE_DARK, 0, KIT_AT_CENTER, 0, KIT_GI_KEEP },
};
#define N_SHOW(a) (int)(sizeof (a) / sizeof (a)[0])

/* ---- sound: its own music, calls and clips (modes/destoroyah/assets.json) ----------------------- */
static struct pa_assets own = { .folder = FOLDER };
enum cue { CUE_START, CUE_KILL, CUE_ESCAPE, CUE_WAVE, CUE_BOSS, CUE_END };
static void sound(enum cue c)
{
    switch (c) {
    case CUE_START:    pa_start(&own); break;                     /* his theme, the swarm emerging, the city */
    case CUE_KILL:                                                /* an aggregate blown apart; its clip every few s */
        pa_call(&own, "kill");
        if (pm_ms() - run.kill_clip_at >= KILL_CLIP_GAP_MS && pa_clip_event(&own, "kill")) run.kill_clip_at = pm_ms();
        break;
    case CUE_ESCAPE:                                              /* one got through: the city is hit */
        pa_call(&own, "escape");
        pa_clip_event(&own, "escape");
        break;
    case CUE_WAVE:                                                /* a wave cleared: the swarm merges */
        pa_call(&own, "wave");
        pa_clip_event(&own, "wave");
        break;
    case CUE_BOSS:
        pa_call(&own, "boss");
        pa_clip_full(&own, "boss");
        break;
    case CUE_END:      pa_end(&own); break;
    }
}

static unsigned spins_needed(unsigned p) { return SPINS_FIRST + SPINS_STEP * plays[p]; }
static unsigned wave_need(void) { return FIRST_NEED + run.wave - 1; }
static unsigned long advance_ms(void) { return ADVANCE_FIRST_MS - 1000u * (run.wave - 1); }

static unsigned next_random(unsigned n)
{
    rnd = rnd * 1103515245u + 12345u + (unsigned)pm_ms();
    return n ? (rnd >> 16) % n : 0;
}

static uint64_t pay(uint64_t points)
{
    uint64_t got = pm_score_add(run.player, points);
    run.total += got;
    return got;
}

static unsigned alive(void)
{
    unsigned i, n = 0;
    for (i = 0; i < ALIVE_MAX; i++) n += run.a[i].on;
    return n;
}

/* a shot of `ring` no other aggregate stands on */
static int free_shot(unsigned ring, unsigned *at)
{
    unsigned k, tries;
    for (tries = 0; tries < 8; tries++) {
        unsigned i, taken = 0;
        k = next_random(ring_n[ring]);
        for (i = 0; i < ALIVE_MAX; i++)
            if (run.a[i].on && run.a[i].ring == ring && run.a[i].at == k) taken = 1;
        if (!taken && ring_mask[ring][k] && (!(ring_mask[ring][k] & shield_mask) || kit_shields_reachable())) {
            *at = k;
            return 1;
        }
    }
    return 0;
}

static uint64_t agg_mask(const struct agg *g) { return ring_mask[g->ring][g->at]; }

/* ---- the glass and the inserts ------------------------------------------------------------------------ */
static void show_lamps(void)
{
    unsigned i;
    static const unsigned RGB[RINGS] = { KIT_YELLOW, KIT_ORANGE, KIT_RED };
    static const int PAT[RINGS] = { PM_LAMP_SOLID, PM_LAMP_BLINK, PM_LAMP_BLINK };
    static const unsigned MS[RINGS] = { 0, 400, 120 };
    kit_lamps_begin(&lamps);
    if (run.phase == PHASE_BOSS) {
        kit_lamps_shot(&lamps, boss_mask, KIT_RED, PM_LAMP_BLINK,
                       kit_hurry_ms((unsigned long)kit_timer_seconds(&run.clock) * 1000u, BOSS_SECONDS * 1000u));
    } else {
        for (i = 0; i < ALIVE_MAX; i++)
            if (run.a[i].on) kit_lamps_shot(&lamps, agg_mask(&run.a[i]), RGB[run.a[i].ring], PAT[run.a[i].ring], MS[run.a[i].ring]);
    }
    kit_lamps_commit(&lamps);
}

static void show(void)
{
    char line[KIT_HUD_WORDS], w[16], k[16], c[16], v[24];
    show_lamps();
    pm_snprintf(c, sizeof c, "%u", CITY_HITS - run.city);
    if (run.phase == PHASE_BOSS) {
        kit_hud_title(&hud, "PERFECT DESTOROYAH", "SHOOT THE BUILDING: 3 HITS");
        pm_snprintf(k, sizeof k, "%u/%d", run.boss_hits, BOSS_HITS);
        kit_hud_counter(&hud, 0, "HITS", k, "PERFECT FORM");
        kit_hud_counter(&hud, 1, "SUPER JACKPOT", kit_short(v, sizeof v, run.kill_total), "EVERY KILL AGAIN");
        kit_hud_counter(&hud, 2, "CITY", c, "HITS TO TAKE");
        kit_hud_timer(&hud, (int)kit_timer_seconds(&run.clock));
        kit_hud_pips(&hud, BOSS_HITS);
        kit_hud_gauge(&hud, (int)run.boss_hits, "HITS");
        return;
    }
    if (run.phase == PHASE_GAP) pm_snprintf(line, sizeof line, "WAVE %u IS COMING", run.wave);
    else pm_snprintf(line, sizeof line, "WAVE %u: %u MORE  -  CLOSER PAYS MORE", run.wave, wave_need() - run.kills);
    kit_hud_title(&hud, "DESTOROYAH", line);
    pm_snprintf(w, sizeof w, "%u/%d", run.wave, WAVES);
    kit_hud_counter(&hud, 0, "WAVE", w, "THE SWARM");
    pm_snprintf(k, sizeof k, "%u/%u", run.kills, wave_need());
    pm_snprintf(line, sizeof line, "WAVE %s", kit_short(v, sizeof v, run.wave_total));     /* "WAVE 2.25M" */
    kit_hud_counter(&hud, 1, "KILLS", k, run.wave_total ? line : "X1 X2 X4");
    kit_hud_counter(&hud, 2, "CITY", c, "HITS TO TAKE");
    kit_hud_timer(&hud, -1);
    kit_hud_pips(&hud, (int)wave_need());
    kit_hud_gauge(&hud, (int)run.kills, "KILLS");
}

/* ---- the swarm ------------------------------------------------------------------------------------- */
static void spawn(void)
{
    unsigned i, at;
    for (i = 0; i < ALIVE_MAX; i++) {
        if (run.a[i].on) continue;
        if (!free_shot(0, &at)) return;
        run.a[i].on = 1;
        run.a[i].ring = 0;
        run.a[i].at = at;
        run.a[i].step_at = pm_ms() + advance_ms();
        pm_log("an aggregate comes over the top at %s", RING_SHOTS[0][at]);
        return;
    }
}

static void start_wave(unsigned wave)
{
    unsigned i;
    run.wave = wave;
    run.kills = 0;
    run.wave_total = 0;
    run.phase = PHASE_SWARM;
    for (i = 0; i < ALIVE_MAX; i++) run.a[i].on = 0;
    run.spawn_at = pm_ms();
    pm_log("WAVE %u: %u kills, advancing every %lu ms", wave, wave_need(), advance_ms());
}

static int start(const char *why)
{
    unsigned p = pm_player();
    if (run.on) return 0;
    if (!pm_in_game() || p < 1 || p > 4) {
        pm_log("not started (%s): no game in play", why);
        return 0;
    }
    if (kit_wait_game(MODE_NAME, why, "the next spin after it starts it")) {
        waiting[p] = 1;
        return 0;
    }
    if (!kit_begin(MODE_NAME)) {
        waiting[p] = 1;
        return 0;
    }
    kit_display(KIT_DISPLAY_MODE);
    kit_isolate_list(own.give_way, own.block_ids, own.block_n);
    kit_shields_in(&shields);
    run.on = 1;
    run.player = p;
    run.won = 0;
    run.city = run.boss_hits = run.all_kills = 0;
    run.kill_total = run.total = 0;
    run.kill_clip_at = 0;
    waiting[p] = 0;
    spins[p] = 0;
    plays[p]++;
    start_wave(1);
    run.spawn_at = pm_ms() + 2500;              /* the intro first */
    kit_hud_begin(&hud, "DESTOROYAH", "");
    show();
    kit_hud_award(&hud, 3000, "DESTOROYAH", "THE AGGREGATES ARE COMING");
    kit_show_start(&show_fx, "destoroyah start", SHOW_START, N_SHOW(SHOW_START));
    sound(CUE_START);
    pm_log("START (%s): player %u, %d waves, %d city hits allowed; next time %u spins, score %llu", why, p, WAVES,
           CITY_HITS, spins_needed(p), (unsigned long long)pm_score(p));
    return 1;
}

static void end(const char *why)
{
    char a[24], b[KIT_HUD_WORDS];
    if (!run.on) return;
    run.on = 0;
    kit_lamps_off(&lamps);
    kit_shields_out(&shields, why);
    kit_end_after(TOTAL_SHOWN_MS);
    if (kit_natural_end(why) && !pa_call(&own, run.won ? "won" : "lost") && !(run.won))
        pm_callout(pm_callout_id("time_up"));          /* its own ending call, else the game's time-up */
    sound(CUE_END);
    pa_clip_full(&own, run.won ? "won" : "lost");
    if (run.won) kit_show_start(&show_fx, "destoroyah won", SHOW_WON, N_SHOW(SHOW_WON));
    else kit_show_start(&show_fx, "destoroyah end", SHOW_END, N_SHOW(SHOW_END));
    pm_snprintf(b, sizeof b, "%u KILL%s  -  WAVE %u", run.all_kills, run.all_kills == 1 ? "" : "S", run.wave);
    kit_hud_title(&hud, run.won ? "DESTOROYAH DEFEATED" : "DESTOROYAH WINS", b);
    kit_hud_counter(&hud, 0, 0, 0, 0);
    kit_hud_counter(&hud, 1, 0, 0, 0);
    kit_hud_counter(&hud, 2, 0, 0, 0);
    kit_hud_timer(&hud, -1);
    kit_hud_gauge(&hud, -1, 0);
    kit_hud_award(&hud, TOTAL_SHOWN_MS, kit_num(a, sizeof a, run.total), " ");
    kit_hud_hide_in(&hud, TOTAL_SHOWN_MS);
    pm_log("END (%s): %s, wave %u, %u kill(s), %u city hit(s), total %llu, score %llu", why,
           run.won ? "WON" : "not won", run.wave, run.all_kills, run.city, (unsigned long long)run.total,
           (unsigned long long)pm_score(run.player));
}

static void boss(void)
{
    unsigned i;
    run.phase = PHASE_BOSS;
    for (i = 0; i < ALIVE_MAX; i++) run.a[i].on = 0;
    run.boss_hits = 0;
    kit_timer_set(&run.clock, BOSS_SECONDS, 1);
    pm_log("PERFECT FORM: the %s for %d s, %d hits; the super %llu", BOSS_SHOT, BOSS_SECONDS, BOSS_HITS,
           (unsigned long long)run.kill_total);
    kit_hud_award(&hud, 3000, "PERFECT FORM", "THE BUILDING: THREE HITS");
    kit_show_start(&show_fx, "perfect form", SHOW_BOSS, N_SHOW(SHOW_BOSS));
    sound(CUE_BOSS);
}

static void wave_cleared(void)
{
    char a[24], s[KIT_HUD_WORDS];
    unsigned i;
    uint64_t got = pay(run.wave_total);
    pm_log("WAVE %u CLEARED: the WAVE SUPER +%llu", run.wave, (unsigned long long)got);
    pm_snprintf(s, sizeof s, "WAVE %u CLEARED", run.wave);
    kit_hud_award(&hud, 2500, s, kit_num(a, sizeof a, got));
    kit_show_start(&show_fx, "wave", SHOW_WAVE, N_SHOW(SHOW_WAVE));
    sound(CUE_WAVE);
    if (run.wave >= WAVES) {
        boss();
        return;
    }
    run.phase = PHASE_GAP;
    run.gap_until = pm_ms() + WAVE_GAP_MS;
    run.wave++;
    for (i = 0; i < ALIVE_MAX; i++) run.a[i].on = 0;
}

static void city_hit(struct agg *g)
{
    char s[KIT_HUD_WORDS];
    g->on = 0;
    run.city++;
    pm_log("an aggregate got through at %s: the city is hit (%u of %d)", RING_SHOTS[2][g->at], run.city, CITY_HITS);
    pm_snprintf(s, sizeof s, "%u HIT%s LEFT", CITY_HITS - run.city, CITY_HITS - run.city == 1 ? "" : "S");
    kit_hud_award(&hud, 2000, "THE CITY IS HIT", s);
    kit_show_start(&show_fx, "city hit", SHOW_CITY, N_SHOW(SHOW_CITY));
    sound(CUE_ESCAPE);
    if (run.city >= CITY_HITS) end("the city fell");
    else run.spawn_at = pm_ms() + SPAWN_AFTER_MS;
}

/* ---- shots ------------------------------------------------------------------------------------------- */
static void run_shot(uint64_t shot)
{
    char a[24], s[KIT_HUD_WORDS];
    unsigned i;
    if (run.phase == PHASE_BOSS) {
        uint64_t got;
        if (!boss_mask || !(shot & boss_mask) || !kit_fresh(&db, boss_mask)) return;
        run.boss_hits++;
        got = pay(BOSS_HIT_VALUE);
        pm_log("PERFECT FORM hit %u of %d: +%llu", run.boss_hits, BOSS_HITS, (unsigned long long)got);
        if (run.boss_hits < BOSS_HITS) {
            pm_snprintf(s, sizeof s, "%u MORE", BOSS_HITS - run.boss_hits);
            kit_hud_award(&hud, 1800, "DESTOROYAH IS HIT", s);
            sound(CUE_KILL);
            return;
        }
        got = pay(run.kill_total);
        run.won = 1;
        pm_log("DESTOROYAH DEFEATED: SUPER JACKPOT +%llu (every kill again)", (unsigned long long)got);
        kit_hud_award(&hud, 3000, "SUPER JACKPOT", kit_num(a, sizeof a, got));
        end("the perfect form defeated");
        return;
    }
    if (run.phase != PHASE_SWARM) return;
    for (i = 0; i < ALIVE_MAX; i++) {
        struct agg *g = &run.a[i];
        uint64_t m, got;
        if (!g->on) continue;
        m = agg_mask(g);
        if (!m || !(shot & m) || !kit_fresh(&db, m)) continue;
        got = pay((KILL_VALUE + KILL_WAVE_STEP * (run.wave - 1)) * RING_MULT[g->ring]);
        g->on = 0;
        run.kills++;
        run.all_kills++;
        run.wave_total += got;
        run.kill_total += got;
        pm_log("KILL %u of %u at %s (%s, x%u): +%llu", run.kills, wave_need(), RING_SHOTS[g->ring][g->at],
               RING_NAME[g->ring], RING_MULT[g->ring], (unsigned long long)got);
        pm_snprintf(s, sizeof s, "%s KILL X%u", RING_NAME[g->ring], RING_MULT[g->ring]);
        kit_hud_award(&hud, 1500, s, kit_num(a, sizeof a, got));
        sound(CUE_KILL);
        if (run.kills >= wave_need()) {
            wave_cleared();
            return;
        }
        run.spawn_at = pm_ms() + SPAWN_AFTER_MS;
    }
}

static void swarm_tick(void)
{
    unsigned long now = pm_ms();
    unsigned i, at;
    if (run.phase == PHASE_GAP) {
        if (now >= run.gap_until) start_wave(run.wave);
        return;
    }
    for (i = 0; i < ALIVE_MAX; i++) {
        struct agg *g = &run.a[i];
        if (!g->on || now < g->step_at) continue;
        if (g->ring + 1 >= RINGS) {
            city_hit(g);
            if (!run.on) return;
            continue;
        }
        if (!free_shot(g->ring + 1, &at)) {            /* nowhere to go: it waits a beat */
            g->step_at = now + 500;
            continue;
        }
        g->ring++;
        g->at = at;
        g->step_at = now + advance_ms();
        pm_log("an aggregate advances to %s (%s, x%u)", RING_SHOTS[g->ring][at], RING_NAME[g->ring], RING_MULT[g->ring]);
    }
    if (now >= run.spawn_at && alive() < ALIVE_MAX && alive() < wave_need() - run.kills) {
        spawn();
        run.spawn_at = now + SPAWN_AFTER_MS;
    }
}

static void qualify_shot(uint64_t shot, unsigned p)
{
    char line[KIT_HUD_WORDS];
    unsigned need = spins_needed(p);
    if (!spin_mask || !(shot & spin_mask)) return;      /* every spin counts */
    if (waiting[p]) {
        start("the center spinner, DESTOROYAH lit");
        return;
    }
    if (spins[p] < need) spins[p]++;
    if (spins[p] % 5 == 0 || spins[p] >= need) pm_log("%s %u of %u (player %u)", SPIN_SHOT, spins[p], need, p);
    if (spins[p] >= need) {
        start("the center spinner");
    } else if (!kit_running && spins[p] % 2 == 0) {
        pm_snprintf(line, sizeof line, "%u SPINS TO DESTOROYAH", need - spins[p]);
        kit_hud_note(&hud, 1500, line, "THE MICRO-OXYGEN SPREADS");
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
    run_shot(shot);
}

/* ---- the callbacks ----------------------------------------------------------------------------- */
static void on_init(void)
{
    unsigned r, i;
    for (r = 0; r < RINGS; r++) {
        ring_n[r] = 0;
        for (i = 0; i < 5 && RING_SHOTS[r][i]; i++) {
            ring_mask[r][i] = pm_shot(RING_SHOTS[r][i]);
            if (!ring_mask[r][i]) pm_log("this port has no \"%s\"", RING_SHOTS[r][i]);
            ring_n[r] = i + 1;
        }
    }
    spin_mask = pm_shot(SPIN_SHOT);
    boss_mask = pm_shot(BOSS_SHOT);
    shield_mask = pm_shot("Shield target left") | pm_shot("Shield target center") | pm_shot("Shield target right");
    rnd ^= (unsigned)pm_ms();
    pa_load(&own);
    pm_log("ready on %s %s: %d spins of %s (0x%llx) start it; %u far, %u near and %u close shots; the perfect form "
           "at %s", pm_game(), pm_version(), SPINS_FIRST, SPIN_SHOT, (unsigned long long)spin_mask, ring_n[0],
           ring_n[1], ring_n[2], BOSS_SHOT);
}

static void check_triggers(void)
{
    char name[48];
    if (pm_trigger(FOLDER ".start")) start("trigger file");
    if (pm_trigger(FOLDER ".stop")) end("trigger file");
    if (pm_trigger(FOLDER ".boss") && run.on && run.phase != PHASE_BOSS) boss();
    if (pm_trigger_text(FOLDER ".shot", name, sizeof name)) {
        uint64_t m = pm_shot(name);
        pm_log("shot trigger: \"%s\" (0x%llx)", name, (unsigned long long)m);
        if (m) on_shot(m);
    }
}

static void on_tick(void)
{
    unsigned p;
    kit_hud_tick(&hud);
    kit_show_tick(&show_fx, &lamps);
    pa_tick(&own);
    kit_shields_tick(&shields);
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
    if (run.phase == PHASE_BOSS) {
        if (kit_timer_tick(&run.clock)) {
            end("the perfect form's clock ran out");
            return;
        }
    } else {
        swarm_tick();
        if (!run.on) return;
    }
    show();
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

static const struct pm_mode destoroyah = {
    .name = MODE_NAME,
    .init = on_init,
    .tick = on_tick,
    .shot = on_shot,
    .ball_end = on_ball_end,
    .event = on_event,
};
PM_REGISTER(destoroyah);
