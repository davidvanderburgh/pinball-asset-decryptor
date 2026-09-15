/* padmode.c - ITEM 125 PHASE 0 PROBE: watch Godzilla Pro 1.15's modes from inside
 * the game, and drive one on demand.
 *
 * WHAT IT ANSWERS, each a question tools/spike2_emu/modes/MODE_API.md could only
 * infer at the desk:
 *   - does `cmode_manager_get(mgr, 23)->v[8]()` really start tesla strike mid-game?
 *   - who delivers shots to a mode (the caller of cmode::v[15], logged by lr)?
 *   - which shot BIT does each switch make (the mask logged per call)?
 *   - what does a mode call to score, speak, show and flash, with which ids?
 *
 * HOW IT GETS IN. Preloaded ahead of hwshim.so through run_game.sh's existing
 * PAD_TRACE_SO chain (PAD_TRACE_SO=/lib/padmode.so). Hooks are inline trampolines,
 * the layout of hwshim.c's pad_hook, except that the logger is handed a pointer to
 * the saved r0-r3/ip/lr so it can read every argument, and the caller's stack args
 * sit just past them.
 *
 * WHAT IT CHANGES. Nothing, unless a trigger file appears in /dump (the host's
 * $ROOT/dump). The tick hook polls twice a second; each trigger is acted on once,
 * on the game's own scheduler thread, then deleted:
 *   padmode.start   "<id>"            cmode_manager_get(mgr,id)->v[8]()   (default 23)
 *   padmode.stop    "<id> <reason>"   ->v[11](reason)
 *   padmode.shot    "<id> <hexmask>"  ->v[15](1, mask, 1)
 *   padmode.score   "<value>"         score_add(current player, value)
 *   padmode.sound   "<req>"           sound_request_play(req)
 *
 * SAFETY. Every site's first two instruction words are compared against the ones
 * gen_sites.py read out of the ELF this was built for; ANY mismatch and nothing is
 * hooked or called at all - the game runs stock and the log says why.
 *
 * AND BEFORE THAT, IS THIS THE GAME AT ALL. A PAD_PIVOT run EXPORTS LD_PRELOAD, so
 * every child the game spawns - `system("rm -r -f /connectivity/files/gkpd_3")`
 * two seconds in - loads this .so too, and the first build compared the words
 * straight away: the child /bin/sh had nothing mapped at the tick address, took
 * SIGSEGV reading it (`-> 139`), and watch.sh saw the fatal signal in game.out
 * and stopped a game that was fine (item 125, run 1). The card's launcher is the
 * same shape - game_monitor is a shell loop under the same LD_PRELOAD - so the
 * gate is not a rig workaround: /proc/self/maps must show an executable `game`
 * mapping over the tick site, or the constructor returns without a word.
 *
 * LOG. /dump/padmode.log, appended, one line per event, capped. Deduped where a
 * call repeats every frame. Build: modes/build_padmode.sh.
 */
#include "padmode_sites.h"

extern int   open(const char *, int, ...);
extern long  read(int, void *, unsigned long);
extern long  write(int, const void *, unsigned long);
extern int   close(int);
extern int   unlink(const char *);
extern int   snprintf(char *, unsigned long, const char *, ...);
extern int   clock_gettime(int, void *);
extern int   mprotect(void *, unsigned long, int);

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define CLOCK_MONOTONIC 1

#define MGR          0x79d954u       /* cmode_manager */
#define MGR_GUARD    0x79dbd8u       /* bit 0 = constructed */
#define CUR_PLAYER   0x708170u       /* byte, 1..4 */
#define SCORES       0x7e4968u       /* u64 x4 */
#define MODE_TABLE   0x7a1698u       /* 27 mode pointers */
#define NMODES       27

static const char *const mode_name[NMODES] = {
    "null", "godzilla_mb", "mechagodzilla_mb", "bridge_attack_mb", "tank_attack_mb",
    "saucer_attack_mb", "megalon_gigan_mb", "planet_x_mb", "monster_zero_victory_mb",
    "terror_of_mechagodzilla", "kotm_mb", "monster_island_madness", "battle_ebirah",
    "battle_titanosaurus", "battle_gigan", "battle_megalon", "battle_king_ghidorah",
    "battle_ghidorah_gigan", "super_train", "o2_destroyer", "king_of_the_monsters",
    "jet_fighter_attack", "planet_x_hurry_up", "tesla_strike", "monster_rampage",
    "hedorah", "monster_zero",
};

/* ---- log ---------------------------------------------------------------- */
static int log_fd = -1, log_lines, armed;
static struct { long s, ns; } t0;

static unsigned long ms_now(void)
{
    struct { long s, ns; } t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long)((t.s - t0.s) * 1000L + (t.ns - t0.ns) / 1000000L);
}

static void logs(const char *m)
{
    char b[300];
    int n;
    if (log_fd < 0 || log_lines > 40000) return;
    log_lines++;
    n = snprintf(b, sizeof b, "%8lu %s", ms_now(), m);
    if (n > 0) write(log_fd, b, n < (int)sizeof b ? (unsigned long)n : sizeof b - 1);
}

static const char *mname(unsigned id) { return id < NMODES ? mode_name[id] : "?"; }

/* ---- hooks -------------------------------------------------------------- */
static unsigned hook_page[1024] __attribute__((aligned(4096)));
static int hook_used;

/* regs[0..3] = r0..r3 at entry, regs[4] = ip, regs[5] = lr (the caller),
 * regs[6..] = the caller's stack arguments. */
typedef void (*logger_fn)(unsigned *regs);

static int words_ok(unsigned fn, unsigned w0, unsigned w1, const char *tag)
{
    const unsigned *p = (const unsigned *)(unsigned long)fn;
    char m[160];
    if (p[0] == w0 && p[1] == w1) return 1;
    snprintf(m, sizeof m, "[padmode] %s 0x%08x: expected %08x %08x, found %08x %08x\n",
             tag, fn, w0, w1, p[0], p[1]);
    logs(m);
    return 0;
}

static void hook(unsigned fn, logger_fn logger)
{
    unsigned *p = (unsigned *)(unsigned long)fn, *t;
    if ((hook_used + 1) * 16 > 1024) return;
    t = hook_page + hook_used++ * 16;
    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;   /* mov r0, sp  - the saved registers */
    t[2] = 0xe1a00000u;   /* nop */
    t[3] = 0xe59fc014u;   /* ldr ip, [pc, #20] -> t[10] */
    t[4] = 0xe12fff3cu;   /* blx ip */
    t[5] = 0xe8bd500fu;   /* pop {r0,r1,r2,r3,ip,lr} */
    t[6] = p[0];
    t[7] = p[1];
    t[8] = 0xe59ff004u;   /* ldr pc, [pc, #4] -> t[11] */
    t[9] = 0u;
    t[10] = (unsigned)(unsigned long)logger;
    t[11] = fn + 8u;
    mprotect(hook_page, sizeof hook_page, 7);
    mprotect((void *)(unsigned long)(fn & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;   /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
}

/* game calls */
static void **mode_get(unsigned id)
{
    return ((void **(*)(void *, unsigned))(unsigned long)SITE_GET)((void *)(unsigned long)MGR, id);
}
#define VT(m) (*(void (***)(void))(m))

static int running_of(void **m)
{
    unsigned p = *(unsigned char *)(unsigned long)CUR_PLAYER;
    return p >= 1 && p <= 4 ? ((unsigned char *)m)[0x1b + p] : -1;   /* strb [this+p+27] */
}

/* ---- dedupe for per-frame callers ------------------------------------- */
struct last { unsigned a, b, c, n; };
static int changed(struct last *l, unsigned a, unsigned b, unsigned c)
{
    if (l->a == a && l->b == b && l->c == c) { l->n++; return 0; }
    l->a = a; l->b = b; l->c = c; l->n = 0;
    return 1;
}

/* ---- loggers -------------------------------------------------------------- */
static void on_started(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[mode] STARTED id=%u %s  lr=0x%x\n", r[1], mname(r[1]), r[5]);
    logs(m);
}

static void on_stopped(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[mode] STOPPED id=%u %s reason=%u  lr=0x%x\n", r[1], mname(r[1]), r[2], r[5]);
    logs(m);
}

static void on_v15(unsigned *r)
{
    static struct last l;
    unsigned id = ((unsigned *)(unsigned long)r[0])[1];
    char m[200];
    if (!changed(&l, r[5], r[2], id)) return;
    snprintf(m, sizeof m, "[shot] v15 mode=%u %s r1=%u mask=%08x_%08x x=%u  lr=0x%x\n",
             id, mname(id), r[1], r[3], r[2], r[6], r[5]);
    logs(m);
}

static void on_tesla_v41(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[shot] tesla v41 r1=%u mask=%08x_%08x  lr=0x%x\n", r[1], r[3], r[2], r[5]);
    logs(m);
}

static void on_score(unsigned *r)
{
    char m[160];
    snprintf(m, sizeof m, "[score] add p=%u v=%llu  lr=0x%x\n", r[0],
             ((unsigned long long)r[3] << 32) | r[2], r[5]);
    logs(m);
}

static void on_caward(unsigned *r)
{
    char m[160];
    unsigned aw = r[0];
    snprintf(m, sizeof m, "[award] caward_add aw=%d v=%llu idx=%u  lr=0x%x\n",
             aw >= 0x79aca0u ? (int)((aw - 0x79aca0u) / 280u) : -1,
             ((unsigned long long)r[3] << 32) | r[2], r[6], r[5]);
    logs(m);
}

static void on_sound(unsigned *r)
{
    static struct last l;
    char m[120];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[sound] request %u  lr=0x%x\n", r[0], r[5]);
    logs(m);
}

static void on_callout(unsigned *r)
{
    char m[120];
    snprintf(m, sizeof m, "[sound] callout %u  lr=0x%x\n", r[0], r[5]);
    logs(m);
}

static void on_show(unsigned *r)
{
    static struct last l;
    char m[120];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[show] start %u  lr=0x%x\n", r[0], r[5]);
    logs(m);
}

static void on_evpost(unsigned *r)
{
    static struct last l;
    char m[140];
    if (!changed(&l, r[0], r[1], r[5])) return;
    snprintf(m, sizeof m, "[event] post_replacing id=%u handler=0x%x flags=0x%x  lr=0x%x\n",
             r[0], r[1], r[2], r[5]);
    logs(m);
}

static void on_text(unsigned *r)
{
    static struct last l;
    char m[140];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[text] 0x3ba540 n=%u a=%u b=%u obj=0x%x  lr=0x%x\n", r[0], r[1], r[2], r[3], r[5]);
    logs(m);
}

static void on_fx(unsigned *r)
{
    static struct last l;
    char m[120];
    if (!changed(&l, r[0], r[5], 0)) return;
    snprintf(m, sizeof m, "[fx] 0x185e9c n=%u a=%u b=%u  lr=0x%x\n", r[0], r[1], r[2], r[5]);
    logs(m);
}

/* ---- triggers, on the game's scheduler thread ----------------------------- */
static int read_trigger(const char *path, unsigned long long v[2])
{
    char buf[64], *s;
    long n;
    int fd = open(path, O_RDONLY), k = 0;
    if (fd < 0) return -1;
    n = read(fd, buf, sizeof buf - 1);
    close(fd);
    unlink(path);
    buf[n > 0 ? n : 0] = 0;
    v[0] = v[1] = 0;
    for (s = buf; *s && k < 2; ) {
        int base = 10;
        unsigned long long x = 0;
        int got = 0;
        while (*s == ' ' || *s == '\n') s++;
        if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
        for (;; s++) {
            int d;
            if (*s >= '0' && *s <= '9') d = *s - '0';
            else if (base == 16 && *s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
            else if (base == 16 && *s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
            else break;
            x = x * base + d;
            got = 1;
        }
        if (!got) break;
        v[k++] = x;
    }
    return k;
}

static void poll_triggers(void)
{
    unsigned long long v[2];
    char m[200];
    int k;
    if (!(*(unsigned *)(unsigned long)MGR_GUARD & 1)) return;

    if ((k = read_trigger("/dump/padmode.start", v)) >= 0) {
        unsigned id = k > 0 ? (unsigned)v[0] : 23u;
        void **mo = mode_get(id);
        int before = running_of(mo), after;
        ((void (*)(void **))VT(mo)[8])(mo);
        after = running_of(mo);
        snprintf(m, sizeof m, "[trigger] start id=%u %s: running %d -> %d, player %u\n",
                 id, mname(id), before, after, *(unsigned char *)(unsigned long)CUR_PLAYER);
        logs(m);
    }
    if ((k = read_trigger("/dump/padmode.stop", v)) >= 0) {
        unsigned id = k > 0 ? (unsigned)v[0] : 23u;
        void **mo = mode_get(id);
        ((void (*)(void **, unsigned))VT(mo)[11])(mo, k > 1 ? (unsigned)v[1] : 0u);
        snprintf(m, sizeof m, "[trigger] stop id=%u %s reason=%u: running now %d\n",
                 id, mname(id), k > 1 ? (unsigned)v[1] : 0u, running_of(mo));
        logs(m);
    }
    if ((k = read_trigger("/dump/padmode.shot", v)) >= 1) {
        unsigned id = (unsigned)v[0];
        void **mo = mode_get(id);
        ((void (*)(void **, unsigned, unsigned long long, unsigned))VT(mo)[15])(mo, 1u, v[1], 1u);
        snprintf(m, sizeof m, "[trigger] shot id=%u %s mask=%llx: running now %d\n",
                 id, mname(id), v[1], running_of(mo));
        logs(m);
    }
    if ((k = read_trigger("/dump/padmode.score", v)) >= 1) {
        unsigned p = *(unsigned char *)(unsigned long)CUR_PLAYER;
        unsigned long long got = ((unsigned long long (*)(unsigned, unsigned long long))
                                  (unsigned long)SITE_SCORE_ADD)(p, v[0]);
        snprintf(m, sizeof m, "[trigger] score_add(p=%u, %llu) returned %llu; p1 score now %llu\n",
                 p, v[0], got, *(unsigned long long *)(unsigned long)SCORES);
        logs(m);
    }
    if ((k = read_trigger("/dump/padmode.sound", v)) >= 1) {
        int rc = ((int (*)(unsigned))(unsigned long)SITE_SOUND)((unsigned)v[0]);
        snprintf(m, sizeof m, "[trigger] sound_request_play(%u) returned %d\n", (unsigned)v[0], rc);
        logs(m);
    }
}

static void on_tick(unsigned *r)
{
    static unsigned ticks, last_player;
    static unsigned char last_running[NMODES];
    (void)r;
    if (++ticks % 30) return;
    poll_triggers();
    if (ticks % 60 == 0 && (*(unsigned *)(unsigned long)MGR_GUARD & 1)) {
        unsigned i, p = *(unsigned char *)(unsigned long)CUR_PLAYER;
        char m[200];
        for (i = 1; i < NMODES; i++) {
            void **mo = (void **)(unsigned long)((unsigned *)(unsigned long)MODE_TABLE)[i];
            unsigned char run = (mo && p >= 1 && p <= 4) ? ((unsigned char *)mo)[0x1b + p] : 0;
            if (run != last_running[i]) {
                snprintf(m, sizeof m, "[state] mode %u %s running=%u (player %u, score %llu)\n",
                         i, mname(i), run, p,
                         p >= 1 && p <= 4 ? ((unsigned long long *)(unsigned long)SCORES)[p - 1] : 0ull);
                logs(m);
                last_running[i] = run;
            }
        }
        if (p != last_player) {
            snprintf(m, sizeof m, "[state] current player %u\n", p);
            logs(m);
            last_player = p;
        }
    }
}

/* Is SITE_TICK inside an executable mapping of a file named like the game?
 * Read before ANY game address is touched - see SAFETY at the top. */
static int is_game_process(void)
{
    static char buf[65536];
    long n, tot = 0;
    char *s = buf, *e;
    int fd = open("/proc/self/maps", O_RDONLY);
    if (fd < 0) return 0;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    while (*s) {
        unsigned long lo = 0, hi = 0;
        char *q = s;
        int d;
        for (e = s; *e && *e != '\n'; e++) ;
        for (; (d = (*q >= '0' && *q <= '9') ? *q - '0' : (*q >= 'a' && *q <= 'f') ? *q - 'a' + 10 : -1) >= 0; q++)
            lo = lo * 16 + d;
        if (*q == '-') {
            q++;
            for (; (d = (*q >= '0' && *q <= '9') ? *q - '0' : (*q >= 'a' && *q <= 'f') ? *q - 'a' + 10 : -1) >= 0; q++)
                hi = hi * 16 + d;
            if (lo <= SITE_TICK && SITE_TICK + 8 <= hi && q[0] == ' ' && q[1] == 'r' && q[3] == 'x') {
                char *p;
                for (p = q; p + 4 <= e; p++)
                    if (p[0] == 'g' && p[1] == 'a' && p[2] == 'm' && p[3] == 'e') return 1;
                return 0;
            }
        }
        s = *e ? e + 1 : e;
    }
    return 0;
}

__attribute__((constructor))
static void padmode_init(void)
{
    struct { unsigned fn, w0, w1; logger_fn lg; const char *tag; } s[] = {
        { SITE_TICK, SITE_TICK_W0, SITE_TICK_W1, on_tick, "tick" },
        { SITE_STARTED, SITE_STARTED_W0, SITE_STARTED_W1, on_started, "started" },
        { SITE_STOPPED, SITE_STOPPED_W0, SITE_STOPPED_W1, on_stopped, "stopped" },
        { SITE_V15, SITE_V15_W0, SITE_V15_W1, on_v15, "v15" },
        { SITE_TESLA_V41, SITE_TESLA_V41_W0, SITE_TESLA_V41_W1, on_tesla_v41, "tesla_v41" },
        { SITE_SCORE_ADD, SITE_SCORE_ADD_W0, SITE_SCORE_ADD_W1, on_score, "score_add" },
        { SITE_CAWARD_ADD, SITE_CAWARD_ADD_W0, SITE_CAWARD_ADD_W1, on_caward, "caward_add" },
        { SITE_SOUND, SITE_SOUND_W0, SITE_SOUND_W1, on_sound, "sound" },
        { SITE_CALLOUT, SITE_CALLOUT_W0, SITE_CALLOUT_W1, on_callout, "callout" },
        { SITE_SHOW, SITE_SHOW_W0, SITE_SHOW_W1, on_show, "show" },
        { SITE_EVPOST, SITE_EVPOST_W0, SITE_EVPOST_W1, on_evpost, "evpost" },
        { SITE_TEXT, SITE_TEXT_W0, SITE_TEXT_W1, on_text, "text" },
        { SITE_FX, SITE_FX_W0, SITE_FX_W1, on_fx, "fx" },
    };
    unsigned i, ok = 1;
    char m[120];
    if (!is_game_process()) return;   /* a child of the game, or not Godzilla at all */
    clock_gettime(CLOCK_MONOTONIC, &t0);
    log_fd = open("/dump/padmode.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    logs("[padmode] loaded - item 125 probe for godzilla Pro 1.15\n");
    for (i = 0; i < sizeof s / sizeof s[0]; i++)
        ok &= words_ok(s[i].fn, s[i].w0, s[i].w1, s[i].tag);
    ok &= words_ok(SITE_GET, SITE_GET_W0, SITE_GET_W1, "get");
    if (!ok) {
        logs("[padmode] NOT THIS BUILD - nothing hooked, the game runs stock\n");
        return;
    }
    for (i = 0; i < sizeof s / sizeof s[0]; i++)
        hook(s[i].fn, s[i].lg);
    armed = 1;
    snprintf(m, sizeof m, "[padmode] %d hooks installed; triggers polled from /dump/padmode.*\n", hook_used);
    logs(m);
}
