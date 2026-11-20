/* UNCANNY STORY: the MPF game in ../mpf ported to PAD's mode SDK by following
 * tools/spike2_emu/modes/sdk/MPF_PORTING.md (PAD-1410). One code mode folder (the slug "xstory"), four of MPF's
 * modes as three pm_modes (MPF's roster is a menu the base opens, not a mode of its own):
 *
 *   MPF mode            PAD                                                         MPF priority -> PAD
 *   future   (base)     FUTURE: pm_begin + pm_own_game(1), starts with each game      100 -> the base
 *   roster   (carousel) kit_menu, opened by FUTURE at each player's first ball         -
 *   sentinel            SENTINEL: pm_begin_layer(50, 0), resumes on the next ball    200 -> layer 50
 *   phoenix             PHOENIX: pm_begin_layer(80, 0), claims the right ramp         300 -> layer 80
 *
 * MPF's player_vars are the P[] array (one per player, swapped when the player up changes), its counters plain
 * ints, its timers tick counts at 60 a second, its ball_saves pm_ball_save, its multiballs pm_multiball_start,
 * its persist: true machine_vars and the per-player story saver pm_saved_get / pm_saved_put, its bar widgets the
 * kit's meters, the Optic Blast show the kit's fades. Built for every title that takes a mode's screens and has an
 * Action button; written against Uncanny X-Men LE and Pro 0.98's shot names (the same on both). */
#include "pad_mode.h"
#include "intricate_kit.h"

#define TPS 60
#define METER_FULL 3          /* future.yaml: s_action_active{current_player.mutant_meter>=3} */
#define SENTINEL_HP 6         /* sentinel.yaml: sentinel_health starting_count */
#define PHOENIX_HP 4          /* phoenix.yaml: phoenix_health starting_count */
#define PHOENIX_S 30          /* phoenix.yaml: phoenix_clock start_value */

static const char *const MUTANTS[] = { "CYCLOPS", "STORM", "WOLVERINE" };
static const int DAMAGE[] = { 3, 2, 2 };     /* an ability's hit; a ramp is 1 */

/* MPF's player_vars, plus the saved ones read back for the player */
struct player {
    int loaded;               /* chapter and mutant read from the saved-progress store this game */
    unsigned stamp;           /* pm_saved_stamp when read: a login or a clear changes it */
    int chapter, mutant;      /* saved */
    int meter, lit;           /* mutant_meter; sentinel_lit (reset each ball) */
    int asked;                /* the roster menu opened for them this game */
    int sentinel_hp;          /* a Sentinel a drain interrupted, resumed next ball (0 = none) */
    uint64_t given;           /* every point this game gave them: their score, since the game's rules are off */
};
static struct player P[5];
static unsigned up;           /* the player whose P[] is live */

static struct kit_game game;
static struct kit_meter m_sentinel, m_phoenix, m_mutant;
static struct kit_fade f_black, f_red;
static struct kit_menu roster;
static uint64_t S_LEFT, S_RIGHT, S_XJET, S_DR, S_ACTION;

static int fut_on, fut_done;
static int want_sentinel, want_phoenix;    /* MPF's start_mode_* events: the layer begins in its own tick */
static int sentinel_on, sentinel_hp, xjet_n;
static int phoenix_on, phoenix_hp;
static unsigned long phoenix_ticks, blast_ticks;

/* ---- scoring: every point is ours (pm_own_game), so the score is the sum of these ---- */
static void award(const char *why, uint64_t pts)
{
    unsigned p = pm_player();
    uint64_t got;
    if (p < 1 || p > 4) return;
    got = pm_score_add(p, pts);
    P[p].given += got;
    pm_log("xstory: +%llu %s - player %u score %llu, given %llu", (unsigned long long)got, why, p,
           (unsigned long long)pm_score(p), (unsigned long long)P[p].given);
}

/* ---- saved progress (machine_vars persist: true, and the per-player story) ---- */
static void load(unsigned p)
{
    long long m = pm_saved_get("xstory:mutant", p, 0);
    P[p].chapter = (int)pm_saved_get("xstory:chapter", p, 1);
    P[p].mutant = m >= 0 && m <= 2 ? (int)m : 0;
    P[p].stamp = pm_saved_stamp(p);
    P[p].loaded = 1;
    pm_log("xstory: player %u saved progress: CHAPTER %d, last mutant %s (sentinels defeated on this machine: %lld,"
           " games %lld)", p, P[p].chapter, MUTANTS[P[p].mutant], pm_saved_get("xstory:sentinels", 0, 0),
           pm_saved_get("xstory:games", 0, 0));
}

static void new_game(void)
{
    unsigned p;
    long long g = pm_saved_get("xstory:games", 0, 0) + 1;
    for (p = 0; p < 5; p++) {
        P[p].loaded = P[p].asked = P[p].meter = P[p].lit = P[p].sentinel_hp = 0;
        P[p].given = 0;
    }
    want_sentinel = want_phoenix = 0;
    pm_saved_put("xstory:games", 0, g);
    pm_log("xstory: a new game - game %lld on this machine", g);
}

static void player_up(unsigned p)
{
    up = p;
    if (!P[p].loaded) load(p);
    pm_log("xstory: player %u is up: CHAPTER %d, %s, Mutant Meter %d of %d", p, P[p].chapter, MUTANTS[P[p].mutant],
           P[p].meter, METER_FULL);
}

/* ---- FUTURE: the game-long base (future.yaml) ------------------------------------------------------------- */
static void fut_init(void)
{
    kit_meter_init(&m_sentinel, "hud", "PadMode_xstory_Meter1");
    kit_meter_init(&m_phoenix, "hud", "PadMode_xstory_Meter2");
    kit_meter_init(&m_mutant, "hud", "PadMode_xstory_Meter3");
    kit_fade_init(&f_black, "hud", "PadMode_xstory_Fade1");
    kit_fade_init(&f_red, "hud", "PadMode_xstory_Fade2");
    kit_menu_init(&roster, "hud", "PadMode_xstory_Menu1");
    S_LEFT = pm_shot("Left ramp exit opto");
    S_RIGHT = pm_shot("Right ramp exit opto");
    S_XJET = pm_shot("Xjet tgt");
    S_DR = pm_shot("Dr ramp exit");
    S_ACTION = pm_shot("Action button");
    pm_log("xstory: shots left ramp %#llx, right ramp %#llx, xjet %#llx, dr ramp %#llx, action %#llx",
           (unsigned long long)S_LEFT, (unsigned long long)S_RIGHT, (unsigned long long)S_XJET,
           (unsigned long long)S_DR, (unsigned long long)S_ACTION);
}

static void fut_start(void)
{
    if (!pm_begin()) {
        pm_log("xstory: FUTURE could not begin - another mode of ours runs");
        fut_done = 1;
        return;
    }
    pm_running_name("FUTURE");
    if (!pm_own_game(1)) pm_log("xstory: this port cannot switch the game's own rules off - they run beside it");
    fut_on = 1;
    pm_log("xstory: FUTURE began: the whole game");
    player_up(pm_player());
}

static void fut_end(const char *why)
{
    kit_menu_close(&roster);
    kit_meter_hide(&m_mutant);
    kit_fade_off(&f_black);
    kit_fade_off(&f_red);
    pm_log("xstory: FUTURE ended (%s)", why);
    pm_end();
    fut_on = 0;
    fut_done = 1;
}

/* the Action button: spend a full Mutant Meter on the mutant's ability, hitting the topmost enemy */
static void ability(void)
{
    int m = P[up].mutant, d = DAMAGE[m], *hp;
    const char *who;
    if (P[up].meter < METER_FULL) {
        pm_log("xstory: Action: the Mutant Meter is at %d of %d - no ability", P[up].meter, METER_FULL);
        return;
    }
    if (phoenix_on) hp = &phoenix_hp, who = "PHOENIX";
    else if (sentinel_on) hp = &sentinel_hp, who = "SENTINEL";
    else {
        pm_log("xstory: Action: no enemy to hit - the meter stays full");
        return;
    }
    P[up].meter = 0;                                          /* ability_fired: mutant_meter set 0 */
    *hp = *hp > d ? *hp - d : 0;
    pm_log("xstory: ABILITY: %s hits the %s for %d (%d left)", MUTANTS[m], who, d, *hp);
    if (m == 0) {                                             /* show_player: optic_blast_fade */
        kit_fade_to(&f_black, 80, 400);
        kit_fade_to(&f_red, 100, 400);
        blast_ticks = 90;
        pm_log("xstory: OPTIC BLAST: the glass fades to black with a red glow");
    }
}

static void fut_shot(uint64_t s)
{
    if (!fut_on) return;
    if (kit_menu_shot(&roster, s)) return;                    /* the menu's buttons are the menu's */
    if (pm_paused() || pm_shot_taken()) return;               /* a layer over FUTURE kept this shot */
    if (S_ACTION && (s & S_ACTION)) {
        ability();
        return;
    }
    if (!(s & (S_LEFT | S_RIGHT | S_XJET | S_DR))) return;
    if (P[up].sentinel_hp > 0 && !sentinel_on && !want_sentinel) {
        want_sentinel = 1;                                    /* stop_on_ball_end: false - it resumes */
        pm_log("xstory: the Sentinel from the last ball comes back (%d left)", P[up].sentinel_hp);
    }
    award("FUTURE shot", 1000);
    if (P[up].meter < METER_FULL && ++P[up].meter == METER_FULL) pm_log("xstory: the Mutant Meter is full");
    if ((s & S_LEFT) && !sentinel_on && !want_sentinel && ++P[up].lit >= 3) {
        P[up].lit = 0;                                        /* counter sentinel_lit complete */
        want_sentinel = 1;
        pm_log("xstory: three left ramps - start_mode_sentinel");
    }
}

static void fut_tick(void)
{
    int in = pm_in_game(), got;
    unsigned p = pm_player();
    if (kit_new_game(&game)) {
        if (fut_on) fut_end("a new game");
        fut_done = 0;
        new_game();
    }
    if (!in) {
        if (fut_on) fut_end("the game is over");
        fut_done = 0;
    } else if (!fut_on && !fut_done && p >= 1 && p <= 4) {
        fut_start();
    }
    if (fut_on && p >= 1 && p <= 4) {
        if (p != up) player_up(p);
        if (pm_saved_stamp(up) != P[up].stamp) {              /* a login, a logout or a clear */
            pm_log("xstory: player %u's saved progress changed hands - read again", up);
            load(up);
        }
        if (!P[up].asked &&                               /* roster: ball_started{ball==1}; under the game's start */
            kit_menu_open(&roster, "CHOOSE YOUR MUTANT", MUTANTS, 3, P[up].mutant, 10000, KIT_MENU_HOLD_LANE))
            P[up].asked = 1;                                  /* film it waits for the film (PAD-1464) */
    }
    got = kit_menu_tick(&roster);
    if (got >= 0 && fut_on) {
        P[up].mutant = got;
        pm_saved_put("xstory:mutant", up, got);
        pm_log("xstory: player %u plays as %s", up, MUTANTS[got]);
    }
    if (fut_on) kit_meter_set(&m_mutant, P[up].meter, METER_FULL, 0);
    else kit_meter_hide(&m_mutant);
    if (blast_ticks && --blast_ticks == 0) {
        kit_fade_to(&f_black, 0, 600);
        kit_fade_to(&f_red, 0, 600);
    }
    kit_meter_tick(&m_sentinel);
    kit_meter_tick(&m_phoenix);
    kit_meter_tick(&m_mutant);
    kit_fade_tick(&f_black);
    kit_fade_tick(&f_red);
}

static void fut_ball_end(void)
{
    if (!fut_on) return;
    P[up].lit = 0;                                            /* sentinel_lit: reset_events ball_will_end */
    pm_log("xstory: player %u's ball ended - FUTURE runs on (score %llu, given %llu)", up,
           (unsigned long long)pm_score(up), (unsigned long long)P[up].given);
}

static const struct pm_mode future = {
    .name = "FUTURE", .init = fut_init, .tick = fut_tick, .shot = fut_shot, .ball_end = fut_ball_end,
};
PM_REGISTER(future);

/* ---- SENTINEL: a layer with a health bar (sentinel.yaml) ---------------------------------------------- */
static void sentinel_end(const char *why)
{
    kit_meter_hide(&m_sentinel);
    pm_log("xstory: SENTINEL ended (%s)", why);
    pm_end();
    sentinel_on = 0;
}

static void sentinel_tick(void)
{
    if (!sentinel_on) {
        if (!want_sentinel || !fut_on) return;
        want_sentinel = 0;
        if (!pm_begin_layer(50, 0)) {
            pm_log("xstory: SENTINEL could not begin as a layer");
            return;
        }
        pm_running_name("SENTINEL");
        sentinel_on = 1;
        xjet_n = 0;
        if (P[up].sentinel_hp > 0) {
            sentinel_hp = P[up].sentinel_hp;
            P[up].sentinel_hp = 0;
            pm_log("xstory: SENTINEL resumed with %d of %d", sentinel_hp, SENTINEL_HP);
        } else {
            sentinel_hp = SENTINEL_HP;
            pm_log("xstory: SENTINEL began: %d of %d", sentinel_hp, SENTINEL_HP);
            if (pm_ball_save(10)) pm_log("xstory: ball save 10 s (sentinel_save)");
            else pm_log("xstory: no ball save - the game refused");
        }
        return;
    }
    if (!pm_running()) {
        sentinel_on = 0;
        kit_meter_hide(&m_sentinel);
        return;
    }
    if (!fut_on || !pm_in_game()) {
        sentinel_end("the game ended");
        return;
    }
    kit_meter_set(&m_sentinel, sentinel_hp, SENTINEL_HP, 0);
    if (sentinel_hp <= 0 && !phoenix_on) {                    /* sentinel_defeated */
        long long n = pm_saved_get("xstory:sentinels", 0, 0) + 1;
        award("SENTINEL defeated", 50000);
        P[up].chapter++;
        pm_saved_put("xstory:chapter", up, P[up].chapter);
        pm_saved_put("xstory:sentinels", 0, n);
        pm_log("xstory: SENTINEL DEFEATED - player %u on to CHAPTER %d (saved); %lld on this machine", up,
               P[up].chapter, n);
        sentinel_end("defeated");
    }
}

static void sentinel_shot(uint64_t s)
{
    if (!sentinel_on || !pm_running() || pm_paused() || pm_shot_taken()) return;
    if (s & (S_RIGHT | S_DR)) {
        if (sentinel_hp > 0) sentinel_hp--;
        award("SENTINEL hit", 5000);
        pm_log("xstory: SENTINEL hit: %d of %d left", sentinel_hp, SENTINEL_HP);
    }
    if ((s & S_XJET) && !phoenix_on && !want_phoenix && ++xjet_n >= 2) {
        xjet_n = 0;
        want_phoenix = 1;                                     /* counter phoenix_lit complete */
        pm_log("xstory: two Xjet hits - start_mode_phoenix");
    }
}

static void sentinel_ball_end(void)
{
    if (!sentinel_on) return;
    P[up].sentinel_hp = sentinel_hp > 0 ? sentinel_hp : 0;
    sentinel_end("the ball ended - it waits for the next ball");
}

static const struct pm_mode sentinel = {
    .name = "SENTINEL", .tick = sentinel_tick, .shot = sentinel_shot, .ball_end = sentinel_ball_end,
};
PM_REGISTER(sentinel);

/* ---- PHOENIX: a layer over the Sentinel, a multiball on a clock (phoenix.yaml) ------------------------- */
static void phoenix_end(const char *why)
{
    kit_meter_hide(&m_phoenix);
    pm_log("xstory: PHOENIX ended (%s)", why);
    pm_end();
    phoenix_on = 0;
}

static void phoenix_tick(void)
{
    if (!phoenix_on) {
        if (!want_phoenix || !fut_on) return;
        want_phoenix = 0;
        if (!pm_begin_layer(80, 0)) {
            pm_log("xstory: PHOENIX could not begin as a layer");
            return;
        }
        pm_running_name("PHOENIX");
        phoenix_on = 1;
        phoenix_hp = PHOENIX_HP;
        phoenix_ticks = PHOENIX_S * TPS;
        pm_log("xstory: PHOENIX began: %d of %d, %d s", phoenix_hp, PHOENIX_HP, PHOENIX_S);
        if (pm_multiball_start(2, 10)) pm_log("xstory: multiball: 2 balls, 10 s ball save (phoenix_mb)");
        else pm_log("xstory: no multiball - the game refused");
        return;
    }
    if (!pm_running()) {
        phoenix_on = 0;
        kit_meter_hide(&m_phoenix);
        return;
    }
    if (!fut_on || !pm_in_game()) {
        phoenix_end("the game ended");
        return;
    }
    if (phoenix_ticks) phoenix_ticks--;
    kit_meter_set(&m_phoenix, phoenix_hp, PHOENIX_HP, 0);
    if (phoenix_hp <= 0) {
        award("PHOENIX defeated", 100000);
        pm_log("xstory: PHOENIX DEFEATED");
        phoenix_end("defeated");
    } else if (!phoenix_ticks) {
        pm_log("xstory: PHOENIX escaped - its clock ran out");
        phoenix_end("phoenix_escaped");
    }
}

static void phoenix_shot(uint64_t s)
{
    if (!phoenix_on || !pm_running() || pm_paused() || pm_shot_taken()) return;
    if (s & S_RIGHT) {
        pm_shot_claim();                                      /* block: true - the ones under it never see it */
        if (phoenix_hp > 0) phoenix_hp--;
        award("PHOENIX hit", 20000);
        pm_log("xstory: PHOENIX hit: %d of %d left (the right ramp is the Phoenix's)", phoenix_hp, PHOENIX_HP);
    }
}

static void phoenix_ball_end(void)
{
    if (phoenix_on) phoenix_end("the ball ended");          /* stop_on_ball_end: true */
}

static const struct pm_mode phoenix = {
    .name = "PHOENIX", .tick = phoenix_tick, .shot = phoenix_shot, .ball_end = phoenix_ball_end,
};
PM_REGISTER(phoenix);
