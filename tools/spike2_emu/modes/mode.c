/* mode.c - ITEM 125 PHASE 1: KAIJU RUSH, a new mode of our own inside Godzilla Pro 1.15.
 *
 * THE RULES OF THE MODE
 *   - Hit the MASER TARGET three times in one ball: KAIJU RUSH starts.
 *   - For 30 seconds every POWERLINE target (left/center/right) and both RAMPS
 *     score an escalating award: 1,000,000 for the first shot, 2,000,000 for the
 *     second, and so on.
 *   - The countdown speaks with the callouts the game's own timed modes use
 *     (cmode_timed's defaults): 1291 at 10 s, 1287's variants from 5 to 1, and
 *     1295 when time runs out.
 *   - It ends when the timer runs out, when the ball ends, or if the player changes.
 *
 * HOW, ALL OF IT EMULATOR-MAPPED IN MODE_API.md
 *   - shots:  a hook on cmode_manager::v[7] (0xd1a9c) sees every shot mask the game
 *             hands its modes, before any of them - the Maser Target is 0x08000000,
 *             the powerlines 0x10/0x20/0x40000000, the ramps 0x00100000/0x00200000.
 *   - clock:  a hook on the 60 Hz tick (0x4ec828). No game timer is free (all 30 are
 *             taken), and a tick clock stops when the game does, like the game's own.
 *   - score:  score_add(player, value) (0x4b8cf4), which applies the playfield
 *             multiplier and the event-161 veto exactly as the game's shots do.
 *   - sound:  callout_play / callout_play_nth (0x187f44 / 0x18800c).
 *   - end:    a hook on the end-of-ball broadcast (0xd3dcc), which is how tesla
 *             strike learns its ball is over.
 * It is NOT registered with cmode_manager: our mode is not one of the 27, and the
 * manager ignores ids above 26 anyway. Text and lights are the next step.
 *
 * TRIGGERS for testing (a rig run only): /dump/mode.start starts it now, /dump/mode.stop
 * ends it. LOG: /dump/mode.log. Loaded by PAD_MODE_SO=/lib/mode.so; built by
 * modes/build_modes.sh; hook.h has the three rules every hook here obeys.
 */
#include "hook.h"

#define MASER_BIT       0x0000000008000000ull
#define RUSH_SHOT_BITS  0x0000000070300000ull   /* powerlines 28-30, ramps 20-21 */
#define MASER_TO_START  3
#define RUSH_SECONDS    30
#define TICKS_PER_S     60
#define AWARD_STEP      1000000ull
#define CALLOUT_10S     1291u
#define CALLOUT_COUNT   1287u    /* variant n = seconds - 1 */
#define CALLOUT_OVER    1295u

static struct {
    int active;
    unsigned player, ticks_left, secs_shown, hits;
    unsigned long long total, score_at_start;
    unsigned long started_ms;
    unsigned maser[5];
    unsigned restore_ticks;      /* after the end, when to put the borrowed words back */
} rush;

/* ---- the screen: text of our own on a screen the game already has ---------------
 * Emulator-proven with the probe (run 4): the award screen family 0x3ba540(type, 0,
 * 0, 0x6fa618) shows the message id at +0xa0 over the u64 value at +0xa8 - type 122,
 * tesla strike's award, is "TESLA STRIKE AWARD / 2,000,000" over its powerline clip.
 * Our words go in by pointing a message's group at a block of our own: the table
 * 0x744c60 is plain .data. We borrow tesla's 3159 (AWARD) and 3160 (COMPLETED) for
 * the length of the mode and a few seconds after, so a tesla award screen shown in
 * that window would read our words - the one visible cost, and only while ours runs. */
#define SCREEN_TYPE       122u
#define MSG_TITLE         3159u
#define MSG_TOTAL         3160u
#define RESTORE_AFTER_S   6

static const char *const title_group[6] = {
    "KAIJU RUSH", "KAIJU RUSH", "KAIJU RUSH", "KAIJU RUSH", "KAIJU RUSH", 0
};
static const char *const total_group[6] = {
    "KAIJU RUSH TOTAL", "KAIJU RUSH TOTAL", "KAIJU RUSH TOTAL", "KAIJU RUSH TOTAL", "KAIJU RUSH TOTAL", 0
};

static struct borrowed { unsigned id, idx; const char **old; int held; } borrow[2] = {
    { MSG_TITLE, 0, 0, 0 }, { MSG_TOTAL, 0, 0, 0 },
};

static void words_borrow(void)
{
    unsigned count = *(unsigned *)(unsigned long)GZ_MSG_COUNT, i;
    unsigned short *remap = *(unsigned short **)(unsigned long)GZ_MSG_REMAP;
    for (i = 0; i < 2; i++) {
        struct borrowed *b = &borrow[i];
        const char ***slot;
        if (b->held || !remap || b->id >= count || remap[b->id] >= count) continue;
        b->idx = remap[b->id];
        slot = (const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * b->idx);
        b->old = *slot;
        *slot = (const char **)(i == 0 ? title_group : total_group);
        b->held = 1;
    }
}

static void words_restore(void)
{
    unsigned i;
    for (i = 0; i < 2; i++) {
        struct borrowed *b = &borrow[i];
        if (!b->held) continue;
        *(const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * b->idx) = b->old;
        b->held = 0;
    }
}

static void screen(unsigned msg, unsigned long long value)
{
    unsigned char *node = ((unsigned char *(*)(unsigned, unsigned, unsigned, unsigned))
                           (unsigned long)SITE_TEXT)(SCREEN_TYPE, 0u, 0u, 0x6fa618u);
    if (!node) return;
    *(unsigned short *)(node + 0xa0) = (unsigned short)msg;
    *(unsigned long long *)(node + 0xa8) = value;
    *(unsigned *)(node + 0xb0) = 0u;
}

static unsigned long long score_now(unsigned p)
{
    return p >= 1 && p <= 4 ? ((unsigned long long *)(unsigned long)GZ_SCORES)[p - 1] : 0ull;
}

static unsigned long long score_add(unsigned p, unsigned long long v)
{
    return ((unsigned long long (*)(unsigned, unsigned long long))(unsigned long)SITE_SCORE_ADD)(p, v);
}

static void callout(unsigned req)
{
    ((void (*)(unsigned))(unsigned long)SITE_CALLOUT)(req);
}

static void callout_nth(unsigned req, unsigned n)
{
    ((void (*)(unsigned, unsigned))(unsigned long)SITE_CALLOUT_NTH)(req, n);
}

static void rush_start(const char *why)
{
    char m[200];
    if (rush.active || !gz_in_game()) return;
    rush.active = 1;
    rush.player = gz_player();
    rush.ticks_left = RUSH_SECONDS * TICKS_PER_S;
    rush.secs_shown = RUSH_SECONDS;
    rush.hits = 0;
    rush.total = 0;
    rush.score_at_start = score_now(rush.player);
    rush.started_ms = hk_ms();
    rush.maser[rush.player] = 0;
    rush.restore_ticks = 0;
    words_borrow();
    screen(MSG_TITLE, AWARD_STEP);          /* "KAIJU RUSH / 1,000,000" - the first shot's worth */
    snprintf(m, sizeof m, "[rush] KAIJU RUSH START (%s): player %u, %u s, score %llu\n",
             why, rush.player, RUSH_SECONDS, rush.score_at_start);
    hk_logs(m);
}

static void rush_end(const char *why)
{
    char m[240];
    if (!rush.active) return;
    rush.active = 0;
    screen(MSG_TOTAL, rush.total);          /* "KAIJU RUSH TOTAL / 15,000,000" */
    rush.restore_ticks = RESTORE_AFTER_S * TICKS_PER_S;
    snprintf(m, sizeof m, "[rush] KAIJU RUSH END (%s): %u shots, awarded %llu, score %llu -> %llu, %lu ms wall\n",
             why, rush.hits, rush.total, rush.score_at_start, score_now(rush.player),
             hk_ms() - rush.started_ms);
    hk_logs(m);
}

/* ---- the shot dispatch: cmode_manager::v[7](mgr, _, mask64, x) --------------- */
static void on_dispatch(unsigned *r)
{
    unsigned long long mask = ((unsigned long long)r[3] << 32) | r[2];
    unsigned p = gz_player();
    char m[200];
    if (!gz_in_game()) return;
    if (!rush.active) {
        if (mask & MASER_BIT) {
            rush.maser[p]++;
            snprintf(m, sizeof m, "[rush] maser target %u of %u (player %u)\n", rush.maser[p], MASER_TO_START, p);
            hk_logs(m);
            if (rush.maser[p] >= MASER_TO_START) rush_start("maser target x3");
        }
        return;
    }
    if (p == rush.player && (mask & RUSH_SHOT_BITS)) {
        unsigned long long asked = AWARD_STEP * ++rush.hits, got = score_add(p, asked);
        rush.total += got;
        screen(MSG_TITLE, got);             /* "KAIJU RUSH / 3,000,000" */
        snprintf(m, sizeof m, "[rush] shot %08x_%08x: +%llu (asked %llu), %u shots, %llu awarded\n",
                 (unsigned)(mask >> 32), (unsigned)mask, got, asked, rush.hits, rush.total);
        hk_logs(m);
    }
}

/* ---- the end-of-ball broadcast --------------------------------------------- */
static void on_ballend(unsigned *r)
{
    (void)r;
    rush_end("ball ended");
    rush.maser[1] = rush.maser[2] = rush.maser[3] = rush.maser[4] = 0;
}

/* ---- the clock --------------------------------------------------------------- */
static void on_tick(unsigned *r)
{
    static unsigned ticks;
    unsigned long long v[4];
    unsigned secs;
    char m[80];
    (void)r;
    if (++ticks % 30 == 0) {
        if (hk_read_trigger("/dump/mode.start", v) >= 0) rush_start("trigger");
        if (hk_read_trigger("/dump/mode.stop", v) >= 0) rush_end("trigger");
    }
    if (rush.restore_ticks && --rush.restore_ticks == 0 && !rush.active) {
        words_restore();
        hk_logs("[rush] borrowed messages 3159/3160 restored\n");
    }
    if (!rush.active) return;
    if (!gz_in_game() || gz_player() != rush.player) {
        rush_end("left the game, or the player changed");
        return;
    }
    if (rush.ticks_left) rush.ticks_left--;
    secs = (rush.ticks_left + TICKS_PER_S - 1) / TICKS_PER_S;
    if (secs != rush.secs_shown) {
        rush.secs_shown = secs;
        if (secs == 10) callout(CALLOUT_10S);
        else if (secs >= 1 && secs <= 5) callout_nth(CALLOUT_COUNT, secs - 1);
        if (secs % 10 == 0 || secs <= 5) {
            snprintf(m, sizeof m, "[rush] %u s left\n", secs);
            hk_logs(m);
        }
    }
    if (rush.ticks_left == 0) {
        callout(CALLOUT_OVER);
        rush_end("time ran out");
    }
}

__attribute__((constructor))
static void mode_init(void)
{
    int ok;
    if (!hk_is_game_process(SITE_TICK)) return;
    hk_log_open("/dump/mode.log");
    ok = hk_site_ok(SITE_TICK, SITE_TICK_W0, SITE_TICK_W1, "tick")
       & hk_site_ok(SITE_DISPATCH, SITE_DISPATCH_W0, SITE_DISPATCH_W1, "dispatch")
       & hk_site_ok(SITE_BALLEND, SITE_BALLEND_W0, SITE_BALLEND_W1, "ballend")
       & hk_site_ok(SITE_SCORE_ADD, SITE_SCORE_ADD_W0, SITE_SCORE_ADD_W1, "score_add")
       & hk_site_ok(SITE_CALLOUT, SITE_CALLOUT_W0, SITE_CALLOUT_W1, "callout")
       & hk_site_ok(SITE_CALLOUT_NTH, SITE_CALLOUT_NTH_W0, SITE_CALLOUT_NTH_W1, "callout_nth")
       & hk_site_ok(SITE_TEXT, SITE_TEXT_W0, SITE_TEXT_W1, "award_screen");
    if (!ok) {
        hk_logs("[rush] NOT THIS BUILD - KAIJU RUSH is not installed, the game runs stock\n");
        return;
    }
    hk_install(SITE_TICK, on_tick);
    hk_install(SITE_DISPATCH, on_dispatch);
    hk_install(SITE_BALLEND, on_ballend);
    hk_logs("[rush] KAIJU RUSH armed: three maser target hits start it\n");
}
