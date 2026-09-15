/* padmode.c - ITEM 125 PROBE: watch Godzilla Pro 1.15's modes from inside the game,
 * and drive one on demand. The instrument; mode.c is the mode.
 *
 * WHAT IT ANSWERED (run 2, 2026-09-15; MODE_API.md): `cmode_manager_get(mgr, 23)
 * ->v[8]()` starts tesla strike mid-game; shots reach every mode through
 * cmode_manager::v[7]; score_add can be called from our own code.
 * WHAT IT IS FOR NOW: the message ids a mode shows and who shows them (hook on
 * msg_lookup 0x34a764), every shot dispatch, the end of ball, and - when mode.so is
 * preloaded beside it - an independent record of what our mode really called.
 *
 * HOW IT GETS IN. PAD_TRACE_SO=/lib/padmode.so (run_game.sh chains it ahead of
 * hwshim.so; PAD_MODE_SO=/lib/mode.so goes between). hook.h has the rules.
 *
 * WHAT IT CHANGES. Nothing, unless a trigger file appears in /dump (the host's
 * $ROOT/dump), polled twice a second from the tick and acted on there, then deleted:
 *   padmode.start   "<id>"            cmode_manager_get(mgr,id)->v[8]()   (default 23)
 *   padmode.stop    "<id> <reason>"   ->v[11](reason)
 *   padmode.shot    "<id> <hexmask>"  ->v[15](1, mask, 1)
 *   padmode.score   "<value>"         score_add(current player, value)
 *   padmode.sound   "<req>"           sound_request_play(req)
 *   padmode.msgdump (any)             every message id -> English into /dump/padmode_msgs.txt
 *
 * LOG. /dump/padmode.log, appended, capped at 40000 lines. Build: modes/build_modes.sh.
 */
#include "hook.h"

#define NMODES 27

static const char *const mode_name[NMODES] = {
    "null", "godzilla_mb", "mechagodzilla_mb", "bridge_attack_mb", "tank_attack_mb",
    "saucer_attack_mb", "megalon_gigan_mb", "planet_x_mb", "monster_zero_victory_mb",
    "terror_of_mechagodzilla", "kotm_mb", "monster_island_madness", "battle_ebirah",
    "battle_titanosaurus", "battle_gigan", "battle_megalon", "battle_king_ghidorah",
    "battle_ghidorah_gigan", "super_train", "o2_destroyer", "king_of_the_monsters",
    "jet_fighter_attack", "planet_x_hurry_up", "tesla_strike", "monster_rampage",
    "hedorah", "monster_zero",
};

static const char *mname(unsigned id) { return id < NMODES ? mode_name[id] : "?"; }

static void **mode_get(unsigned id)
{
    return ((void **(*)(void *, unsigned))(unsigned long)SITE_GET)((void *)(unsigned long)GZ_MGR, id);
}
#define VT(m) (*(void (***)(void))(m))

static int running_of(void **m)
{
    unsigned p = gz_player();
    return p >= 1 && p <= 4 ? ((unsigned char *)m)[0x1b + p] : -1;   /* strb [this+p+27] */
}

/* ---- dedupe ------------------------------------------------------------------- */
struct last { unsigned a, b, c, n; };
static int changed(struct last *l, unsigned a, unsigned b, unsigned c)
{
    if (l->a == a && l->b == b && l->c == c) { l->n++; return 0; }
    l->a = a; l->b = b; l->c = c; l->n = 0;
    return 1;
}

/* A (value, caller) pair logs once per run: msg_lookup is called every frame. */
#define SEEN_MAX 512
static unsigned seen[SEEN_MAX][2];
static int nseen;
static int first_time(unsigned a, unsigned b)
{
    int i;
    for (i = 0; i < nseen; i++)
        if (seen[i][0] == a && seen[i][1] == b) return 0;
    if (nseen < SEEN_MAX) { seen[nseen][0] = a; seen[nseen][1] = b; nseen++; }
    return 1;
}

/* ---- loggers ---------------------------------------------------------------- */
static void on_started(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[mode] STARTED id=%u %s  lr=0x%x\n", r[1], mname(r[1]), r[5]);
    hk_logs(m);
}

static void on_stopped(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[mode] STOPPED id=%u %s reason=%u  lr=0x%x\n", r[1], mname(r[1]), r[2], r[5]);
    hk_logs(m);
}

static void on_dispatch(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[shot] dispatch mask=%08x_%08x x=%u  lr=0x%x\n", r[3], r[2], r[6], r[5]);
    hk_logs(m);
}

static void on_ballend(unsigned *r)
{
    char m[120];
    snprintf(m, sizeof m, "[ball] end-of-ball broadcast (every mode's v[4])  lr=0x%x\n", r[5]);
    hk_logs(m);
}

static void on_tesla_v41(unsigned *r)
{
    char m[180];
    unsigned p = gz_player();
    const unsigned *o = (const unsigned *)(unsigned long)r[0];
    snprintf(m, sizeof m, "[shot] tesla v41 mask=%08x_%08x lit[p%u]=%08x_%08x  lr=0x%x\n",
             r[3], r[2], p, p >= 1 && p <= 4 ? o[(0x1c + 8 * p) / 4] : 0,
             p >= 1 && p <= 4 ? o[(0x18 + 8 * p) / 4] : 0, r[5]);
    hk_logs(m);
}

static void on_score(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[score] add p=%u v=%llu  lr=0x%x\n", r[0],
             ((unsigned long long)r[3] << 32) | r[2], r[5]);
    hk_logs(m);
}

static void on_caward(unsigned *r)
{
    char m[160];
    unsigned aw = r[0];
    snprintf(m, sizeof m, "[award] caward_add aw=%d v=%llu idx=%u  lr=0x%x\n",
             aw >= 0x79aca0u ? (int)((aw - 0x79aca0u) / 280u) : -1,
             ((unsigned long long)r[3] << 32) | r[2], r[6], r[5]);
    hk_logs(m);
}

static void on_sound(unsigned *r)
{
    static struct last l;
    char m[120];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[sound] request %u  lr=0x%x\n", r[0], r[5]);
    hk_logs(m);
}

static void on_sound_nth(unsigned *r)
{
    char m[120];
    snprintf(m, sizeof m, "[sound] request_nth %u n=%u  lr=0x%x\n", r[0], r[1], r[5]);
    hk_logs(m);
}

static void on_callout(unsigned *r)
{
    char m[120];
    snprintf(m, sizeof m, "[sound] callout %u  lr=0x%x\n", r[0], r[5]);
    hk_logs(m);
}

static void on_show(unsigned *r)
{
    static struct last l;
    char m[120];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[show] start %u  lr=0x%x\n", r[0], r[5]);
    hk_logs(m);
}

static void on_evpost(unsigned *r)
{
    static struct last l;
    char m[140];
    if (!changed(&l, r[0], r[1], r[5])) return;
    snprintf(m, sizeof m, "[event] post_replacing id=%u handler=0x%x flags=0x%x  lr=0x%x\n",
             r[0], r[1], r[2], r[5]);
    hk_logs(m);
}

static void on_text(unsigned *r)
{
    static struct last l;
    char m[140];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[text] 0x3ba540 n=%u a=%u b=%u obj=0x%x  lr=0x%x\n", r[0], r[1], r[2], r[3], r[5]);
    hk_logs(m);
}

static void on_fx(unsigned *r)
{
    static struct last l;
    char m[120];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[fx] 0x185e9c n=%u a=%u b=%u  lr=0x%x\n", r[0], r[1], r[2], r[5]);
    hk_logs(m);
}

static void on_msg(unsigned *r)
{
    char m[200];
    const char *en;
    if (!first_time(r[0], r[5])) return;
    en = gz_msg_en(r[0]);
    snprintf(m, sizeof m, "[msg] id=%u \"%.80s\"  lr=0x%x\n", r[0], en ? en : "?", r[5]);
    hk_logs(m);
}

/* ---- triggers, on the game's scheduler thread ----------------------------- */
static void msgdump(void)
{
    unsigned count = *(unsigned *)(unsigned long)GZ_MSG_COUNT, id, rows = 0;
    int fd = open("/dump/padmode_msgs.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    char m[400];
    if (fd < 0) return;
    for (id = 0; id < count; id++) {
        const char *en = gz_msg_en(id), *s;
        char esc[240];
        int k = 0, n;
        if (!en) continue;
        for (s = en; *s && k < (int)sizeof esc - 3; s++) {
            if (*s == '\n') { esc[k++] = '\\'; esc[k++] = 'n'; }
            else if (*s == '\t') { esc[k++] = ' '; }
            else esc[k++] = *s;
        }
        esc[k] = 0;
        n = snprintf(m, sizeof m, "%u\t%s\n", id, esc);
        if (n > 0) write(fd, m, n < (int)sizeof m ? (unsigned long)n : sizeof m - 1);
        rows++;
    }
    close(fd);
    snprintf(m, sizeof m, "[trigger] msgdump: %u of %u ids -> /dump/padmode_msgs.txt\n", rows, count);
    hk_logs(m);
}

/* "KAIJU RUSH" in all five language slots, in the {en,de,fr,es,it,0} shape a message
 * group has, so a hijacked id renders our text whatever the language setting. */
static const char *const kaiju_group[6] = {
    "KAIJU RUSH", "KAIJU RUSH", "KAIJU RUSH", "KAIJU RUSH", "KAIJU RUSH", 0
};
static unsigned hijack_idx = 0xffffffffu;
static const char **hijack_old;

/* Point message id's group at kaiju_group (restore=0), or put the one saved back. The
 * group table 0x744c60 is ordinary .data (the ELF has no RELRO), and every id the
 * remap sends to the same index changes with it, so only pick an id nothing else
 * on screen is using. */
static void msg_hijack(unsigned id, int restore)
{
    unsigned count = *(unsigned *)(unsigned long)GZ_MSG_COUNT;
    unsigned short *remap = *(unsigned short **)(unsigned long)GZ_MSG_REMAP;
    const char ***slot;
    char m[160];
    if (restore) {
        if (hijack_idx == 0xffffffffu) return;
        *(const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * hijack_idx) = hijack_old;
        snprintf(m, sizeof m, "[trigger] msg index %u restored\n", hijack_idx);
        hk_logs(m);
        hijack_idx = 0xffffffffu;
        return;
    }
    if (id >= count || !remap || remap[id] >= count) return;
    slot = (const char ***)(unsigned long)(GZ_MSG_PTRS + 4u * remap[id]);
    if (hijack_idx == 0xffffffffu) { hijack_idx = remap[id]; hijack_old = *slot; }
    snprintf(m, sizeof m, "[trigger] msg id %u (index %u, was \"%.40s\") now reads \"%s\"\n",
             id, remap[id], *slot && (*slot)[0] ? (*slot)[0] : "?", kaiju_group[0]);
    *slot = (const char **)kaiju_group;
    hk_logs(m);
}

static void poll_triggers(void)
{
    unsigned long long v[4];
    char m[200];
    int k;
    if (!(*(unsigned *)(unsigned long)GZ_MGR_GUARD & 1)) return;

    /* padmode.text "<type> <msgid> <value> [count]" - the award-screen family tesla's
     * award uses: 0x3ba540(type, 0, 0, 0x6fa618), then msg id at +0xa0, u64 value at
     * +0xa8, count at +0xb0 (tesla: type 122, 3159/3160) */
    if ((k = hk_read_trigger("/dump/padmode.text", v)) >= 2) {
        unsigned char *node = ((unsigned char *(*)(unsigned, unsigned, unsigned, unsigned))
                               (unsigned long)SITE_TEXT)((unsigned)v[0], 0u, 0u, 0x6fa618u);
        if (node) {
            *(unsigned short *)(node + 0xa0) = (unsigned short)v[1];
            *(unsigned long long *)(node + 0xa8) = v[2];
            *(unsigned *)(node + 0xb0) = (unsigned)v[3];
        }
        snprintf(m, sizeof m, "[trigger] text type %u msg %u value %llu -> node %p\n",
                 (unsigned)v[0], (unsigned)v[1], v[2], (void *)node);
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.show", v)) >= 1) {
        void *node = ((void *(*)(unsigned))(unsigned long)SITE_SHOW)((unsigned)v[0]);
        snprintf(m, sizeof m, "[trigger] show_start(%u) -> node %p\n", (unsigned)v[0], node);
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.showkill", v)) >= 1) {
        int rc = ((int (*)(unsigned))(unsigned long)SITE_SHOW_KILL)((unsigned)v[0]);
        snprintf(m, sizeof m, "[trigger] show_kill(%u) -> %d\n", (unsigned)v[0], rc);
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.msgset", v)) >= 1)
        msg_hijack((unsigned)v[0], 0);
    if (hk_read_trigger("/dump/padmode.msgrestore", v) >= 0)
        msg_hijack(0, 1);

    if ((k = hk_read_trigger("/dump/padmode.start", v)) >= 0) {
        unsigned id = k > 0 ? (unsigned)v[0] : 23u;
        void **mo = mode_get(id);
        int before = running_of(mo), after;
        ((void (*)(void **))VT(mo)[8])(mo);
        after = running_of(mo);
        snprintf(m, sizeof m, "[trigger] start id=%u %s: running %d -> %d, player %u\n",
                 id, mname(id), before, after, gz_player());
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.stop", v)) >= 0) {
        unsigned id = k > 0 ? (unsigned)v[0] : 23u;
        void **mo = mode_get(id);
        ((void (*)(void **, unsigned))VT(mo)[11])(mo, k > 1 ? (unsigned)v[1] : 0u);
        snprintf(m, sizeof m, "[trigger] stop id=%u %s reason=%u: running now %d\n",
                 id, mname(id), k > 1 ? (unsigned)v[1] : 0u, running_of(mo));
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.shot", v)) >= 1) {
        unsigned id = (unsigned)v[0];
        void **mo = mode_get(id);
        ((void (*)(void **, unsigned, unsigned long long, unsigned))VT(mo)[15])(mo, 1u, v[1], 1u);
        snprintf(m, sizeof m, "[trigger] shot id=%u %s mask=%llx: running now %d\n",
                 id, mname(id), v[1], running_of(mo));
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.score", v)) >= 1) {
        unsigned p = gz_player();
        unsigned long long got = ((unsigned long long (*)(unsigned, unsigned long long))
                                  (unsigned long)SITE_SCORE_ADD)(p, v[0]);
        snprintf(m, sizeof m, "[trigger] score_add(p=%u, %llu) returned %llu; p1 score now %llu\n",
                 p, v[0], got, *(unsigned long long *)(unsigned long)GZ_SCORES);
        hk_logs(m);
    }
    if ((k = hk_read_trigger("/dump/padmode.sound", v)) >= 1) {
        int rc = ((int (*)(unsigned))(unsigned long)SITE_SOUND)((unsigned)v[0]);
        snprintf(m, sizeof m, "[trigger] sound_request_play(%u) returned %d\n", (unsigned)v[0], rc);
        hk_logs(m);
    }
    if (hk_read_trigger("/dump/padmode.msgdump", v) >= 0)
        msgdump();
}

static void on_tick(unsigned *r)
{
    static unsigned ticks, last_player;
    static unsigned char last_running[NMODES];
    (void)r;
    if (++ticks % 30) return;
    poll_triggers();
    if (ticks % 60 == 0 && (*(unsigned *)(unsigned long)GZ_MGR_GUARD & 1)) {
        unsigned i, p = gz_player();
        char m[200];
        for (i = 1; i < NMODES; i++) {
            void **mo = (void **)(unsigned long)((unsigned *)(unsigned long)GZ_MODE_TABLE)[i];
            unsigned char run = (mo && p >= 1 && p <= 4) ? ((unsigned char *)mo)[0x1b + p] : 0;
            if (run != last_running[i]) {
                snprintf(m, sizeof m, "[state] mode %u %s running=%u (player %u, score %llu)\n",
                         i, mname(i), run, p,
                         p >= 1 && p <= 4 ? ((unsigned long long *)(unsigned long)GZ_SCORES)[p - 1] : 0ull);
                hk_logs(m);
                last_running[i] = run;
            }
        }
        if (p != last_player) {
            snprintf(m, sizeof m, "[state] current player %u\n", p);
            hk_logs(m);
            last_player = p;
        }
    }
}

__attribute__((constructor))
static void padmode_init(void)
{
    struct { unsigned fn, w0, w1; hk_logger lg; const char *tag; } s[] = {
        { SITE_TICK, SITE_TICK_W0, SITE_TICK_W1, on_tick, "tick" },
        { SITE_STARTED, SITE_STARTED_W0, SITE_STARTED_W1, on_started, "started" },
        { SITE_STOPPED, SITE_STOPPED_W0, SITE_STOPPED_W1, on_stopped, "stopped" },
        { SITE_DISPATCH, SITE_DISPATCH_W0, SITE_DISPATCH_W1, on_dispatch, "dispatch" },
        { SITE_BALLEND, SITE_BALLEND_W0, SITE_BALLEND_W1, on_ballend, "ballend" },
        { SITE_TESLA_V41, SITE_TESLA_V41_W0, SITE_TESLA_V41_W1, on_tesla_v41, "tesla_v41" },
        { SITE_SCORE_ADD, SITE_SCORE_ADD_W0, SITE_SCORE_ADD_W1, on_score, "score_add" },
        { SITE_CAWARD_ADD, SITE_CAWARD_ADD_W0, SITE_CAWARD_ADD_W1, on_caward, "caward_add" },
        { SITE_SOUND, SITE_SOUND_W0, SITE_SOUND_W1, on_sound, "sound" },
        { SITE_CALLOUT, SITE_CALLOUT_W0, SITE_CALLOUT_W1, on_callout, "callout" },
        { SITE_SHOW, SITE_SHOW_W0, SITE_SHOW_W1, on_show, "show" },
        { SITE_EVPOST, SITE_EVPOST_W0, SITE_EVPOST_W1, on_evpost, "evpost" },
        { SITE_TEXT, SITE_TEXT_W0, SITE_TEXT_W1, on_text, "text" },
        { SITE_FX, SITE_FX_W0, SITE_FX_W1, on_fx, "fx" },
        { SITE_MSG, SITE_MSG_W0, SITE_MSG_W1, on_msg, "msg" },
        { SITE_SOUND_NTH, SITE_SOUND_NTH_W0, SITE_SOUND_NTH_W1, on_sound_nth, "sound_nth" },
    };
    unsigned i, ok = 1;
    char m[120];
    if (!hk_is_game_process(SITE_TICK)) return;   /* a child of the game, or not Godzilla */
    hk_log_open("/dump/padmode.log");
    hk_logs("[padmode] loaded - item 125 probe for godzilla Pro 1.15\n");
    for (i = 0; i < sizeof s / sizeof s[0]; i++)
        ok &= hk_site_ok(s[i].fn, s[i].w0, s[i].w1, s[i].tag);
    ok &= hk_site_ok(SITE_GET, SITE_GET_W0, SITE_GET_W1, "get");
    ok &= hk_site_ok(SITE_SHOW_KILL, SITE_SHOW_KILL_W0, SITE_SHOW_KILL_W1, "show_kill");
    if (!ok) {
        hk_logs("[padmode] NOT THIS BUILD - nothing hooked, the game runs stock\n");
        return;
    }
    for (i = 0; i < sizeof s / sizeof s[0]; i++)
        hk_install(s[i].fn, s[i].lg);
    snprintf(m, sizeof m, "[padmode] %d hooks installed; triggers polled from /dump/padmode.*\n", hk_used);
    hk_logs(m);
}
