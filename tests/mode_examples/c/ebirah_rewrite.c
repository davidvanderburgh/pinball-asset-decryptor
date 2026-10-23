/* ebirah_rewrite.c - battle vs EBIRAH with different shots: three shots in order, then the building.
 * (item 161; emulator-proven on Godzilla Premium 1.16 on 2026-09-23: MODE_SDK.md, "Rewriting a stock
 * rule's shot logic", "What is measured". A card with it has not been flashed.)
 *
 * The game's own Ebirah battle: rip three spinners (15, 40, 15 spins), then hit the Pop bumper for
 * the 25,000,000 final blow. This file keeps everything of the battle but its shots: it still starts
 * from the BATTLE SELECTION screen, pays the game's own 250,000 start award, runs on the game's own
 * 60-second clock, shows the game's own screens and ends the game's own way. What changes is only
 * what a shot does:
 *
 *   1. the Left ramp,   then
 *   2. the Right ramp,  then
 *   3. the Big loop,    each paying what a spin pays and, when made, the game's own stage award
 *      (5,000,000 / 10,000,000 / 15,000,000, in that order) with its award screen;
 *   4. then the BUILDING for the game's own final blow: 25,000,000, the finishing bonus, the
 *      "EBIRAH FINAL BLOW" screen and the battle WON, exactly as a Pop bumper does in stock.
 *
 * The lit insert follows the shot that is next (yellow blink, the battle's colour), through the
 * port's named inserts. A shot that is not the one that is next does nothing (as an unlit shot does
 * in stock). With this file left out of the build, the battle is the game's own.
 *
 * What the game still does that this file does not touch: the timer and its callouts, the fail
 * screen when time runs out, the battle's start and total screens, King of the Monsters (a battle
 * started by KOTM pays through KOTM's award in stock; this file pays through Ebirah's own award and
 * says so in the log). Not measured: whether the stock stage screens, which name the SPINNER that
 * was completed, read well over a ramp; whether the battle's on-screen words (the BG layer masks
 * the field with the spinner bits) show anything for these shots.
 *
 * Build (with the runtime, once item 160's wrapper is in it):
 *     build_mode.sh -o mode.so ebirah_rewrite.c
 * On a card: modes/<folder>/<folder>.c of a project (MODE_SDK.md, "Rewriting a stock rule's shot logic").
 */
#include "pad_mode.h"
#include "pad_stock.h"

#define MODE_NAME "EBIRAH, THREE SHOTS THEN THE BUILDING"

#define STAGES 3
static const char *const STAGE_SHOT[STAGES] = { "Left ramp", "Right ramp", "Big loop" };
/* which stock stage award each of our stages takes (the game's own 5M / 10M / 15M, by completion order) */
static const int STAGE_SPINNER[STAGES] = { PM_EBIRAH_LEFT, PM_EBIRAH_TOP, PM_EBIRAH_SHIELD };

static uint64_t stage_bit[STAGES], building_bit;
static int stage_of[5];                 /* per player 1-4: how many of the three are made (3 = the building is lit) */
static unsigned lit_player;             /* whose insert we hold, 0 = none */
static uint64_t lit_bit;

static unsigned rule_id(void) { return (unsigned)pm_port_value("ebirah_rule", 12); }

static void light(unsigned player)
{
    int s = stage_of[player];
    uint64_t bit = s < STAGES ? stage_bit[s] : building_bit;
    if (lit_bit == bit && lit_player == player) return;
    pm_lamp_release_all();
    lit_bit = bit;
    lit_player = player;
    if (bit) pm_lamp_shot(bit, PM_RGB(255, 255, 0), PM_LAMP_BLINK, 500);
}

static void dark(void)
{
    if (lit_bit) pm_lamp_release_all();
    lit_bit = 0;
    lit_player = 0;
}

/* after the game's own START ran: the field is rebuilt from the spin counts by the game; we make it
 * our first shot instead, so the battle's lit-shot query (v[25]) reports what we light */
static void on_started(struct pm_stock_rule *r)
{
    unsigned p = pm_stock_player();
    if (!p) return;
    stage_of[p] = 0;
    pm_stock_field_set(r, p, stage_bit[0]);
    light(p);
    pm_log("%s: started for player %u, the %s is lit (spins left %d/%d/%d)", MODE_NAME, p, STAGE_SHOT[0],
           pm_ebirah_spins(r, PM_EBIRAH_LEFT, p), pm_ebirah_spins(r, PM_EBIRAH_TOP, p),
           pm_ebirah_spins(r, PM_EBIRAH_SHIELD, p));
}

/* before the game's own STOP runs (won, timed out, drained): give the inserts back */
static void on_stopped(struct pm_stock_rule *r, unsigned reason)
{
    (void)r;
    pm_log("%s: stopped (%s)", MODE_NAME, reason == 1 ? "won" : "not won");
    dark();
}

/* runs INSTEAD of the game's handler for every shot while the battle is active */
static int on_shot(struct pm_stock_rule *r, uint64_t shot, unsigned factor)
{
    unsigned p = pm_stock_player();
    int s;
    if (!p) return PM_STOCK_PASS;
    s = stage_of[p];
    if (s < STAGES) {
        if (!(shot & stage_bit[s])) return PM_STOCK_DONE;          /* not the shot that is next: nothing */
        /* what a spin pays (200,000 x the dispatch's factor), through the battle's own award */
        pm_stock_award(r, 200000ull * (factor ? factor : 1));
        pm_stock_show(347);
        /* the game's own stage award, screen and reminder event, in completion order */
        pm_ebirah_stage_award(r, STAGE_SPINNER[s]);
        stage_of[p] = ++s;
        /* the game's handler wrote the final mask when every counter reached 0 (after our third
         * stage); before that we light our next shot in the field ourselves */
        if (s < STAGES) pm_stock_field_set(r, p, stage_bit[s]);
        else pm_stock_field_set(r, p, pm_stock_field(r, p) | building_bit);
        light(p);
        pm_log("%s: player %u made %s (%d of %d); next: %s", MODE_NAME, p, STAGE_SHOT[s - 1], s, STAGES,
               s < STAGES ? STAGE_SHOT[s] : "the Building");
        return PM_STOCK_DONE;
    }
    if (shot & building_bit) {
        pm_log("%s: player %u hit the Building: the game's own final blow", MODE_NAME, p);
        dark();
        pm_stock_final_blow(r);                                     /* 25,000,000, the screens, STOP as won */
        return PM_STOCK_DONE;
    }
    return PM_STOCK_DONE;                                           /* anything else: nothing, as unlit in stock */
}

static void on_init(void)
{
    int i;
    for (i = 0; i < STAGES; i++) {
        stage_bit[i] = pm_shot(STAGE_SHOT[i]);
        if (!stage_bit[i]) pm_log("%s: this port has no shot named %s", MODE_NAME, STAGE_SHOT[i]);
    }
    building_bit = pm_shot("Building");
    pm_log("%s: rule %u; shots 0x%llx 0x%llx 0x%llx then 0x%llx", MODE_NAME, rule_id(),
           (unsigned long long)stage_bit[0], (unsigned long long)stage_bit[1],
           (unsigned long long)stage_bit[2], (unsigned long long)building_bit);
}

static void on_ball_end(void)
{
    dark();                       /* the game stops the battle on a drain; the next start relights */
}

/* the ordinary mode record carries init and ball_end; the stock-rule record carries the handler */
static const struct pm_mode ebirah_rewrite = {
    .name = "ebirah_rewrite", .init = on_init, .ball_end = on_ball_end,
};
PM_REGISTER(ebirah_rewrite);

static const struct pm_stock_handler ebirah_shots = {
    .rule_id = 12, .shot = on_shot, .started = on_started, .stopped = on_stopped, .name = MODE_NAME,
    .mode = &ebirah_rewrite,
};
PM_STOCK_RULE(ebirah_shots);
