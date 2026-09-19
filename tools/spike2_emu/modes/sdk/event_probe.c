/* event_probe.c - which of the game's EVENTS fire when? (item 147)
 *
 * The game's rules talk through one event bus: subscribe(_, id, handler, prio) puts a
 * handler on id's list (ids 0..207), and dispatch(id, arg) calls every handler on that
 * list in priority order. This instrument hooks both, and the game's tick:
 *
 *   subscribe  every registration: id, handler, priority, caller, thread
 *   dispatch   per-id counts per WINDOW (a window runs from one mark to the next), and
 *              the first FIRST_CALLS calls of each id in each window with their argument,
 *              caller, thread, the player up and the game's mode mask
 *   tick       `first tick` (with the whole table, handler by handler), then twice a
 *              second: /dump/event.mark "<label>" closes the window (its counts are
 *              logged) and opens a new one; /dump/event.force "<id>" starts stock mode
 *              <id> the way a rule does (cmode_manager get(mgr, id)->v[8]), and
 *              "stop <id>" stops it (v[11](0))
 *
 * Not a mode and not built with the runtime:  build_mode.sh -p -o event_probe.so event_probe.c
 * Preload it with PAD_MODE_SO, with /dump/event.sites (below; port_words.py fills and checks
 * its words) and read /dump/event.log with event_read.py.
 *
 *   site subscribe  <addr> <w0> <w1>     the bus (both start `cmp rN, #207; push`)
 *   site dispatch   <addr> <w0> <w1>
 *   site tick       <addr> <w0> <w1>     the port's tick
 *   site mode_get   <addr> <w0> <w1>     optional: cmode_manager get, for event.force
 *   data table      <addr>               the bus's list heads (log only)
 *   data mode_mgr   <addr>               optional: the cmode_manager singleton
 *   data cur_player <addr>               optional: logged with each call
 *   data mode_mask  <addr>               optional: logged with each call
 *   site watch_<x>  <addr> <w0> <w1>     optional, up to 8: calls of this function are counted
 *                                        per window like an id (0xd0 + k) and the first ones
 *                                        logged with r0..r3 - for a title's events that are
 *                                        not broadcast (a skill shot award, a mode's start)
 *
 * It acts only in the process whose program maps the tick (the game). The trampoline is
 * the runtime's, and keeps the moved words at t[14..15], so a mode.so loaded beside it
 * still verifies its own sites.
 */
#include <stdarg.h>

extern int  open(const char *, int, ...);
extern long read(int, void *, __SIZE_TYPE__);
extern long write(int, const void *, __SIZE_TYPE__);
extern int  close(int);
extern int  unlink(const char *);
extern int  clock_gettime(int, void *);
extern int  mprotect(void *, __SIZE_TYPE__, int);
extern int  vsnprintf(char *, __SIZE_TYPE__, const char *, va_list);
extern long syscall(long, ...);
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define CLOCK_MONOTONIC 1
#define SYS_GETTID 224

#define N_BUS_IDS   208
#define N_WATCH     8
#define N_IDS       (N_BUS_IDS + N_WATCH)
#define FIRST_CALLS 3
#define MAX_REG     3000
#define MAX_LINES   60000

/* ---- the log ------------------------------------------------------------------------- */
static int log_fd = -1;
static volatile int log_lines;
static struct { long s, ns; } t0;

static unsigned long ms(void)
{
    struct { long s, ns; } t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long)((t.s - t0.s) * 1000L + (t.ns - t0.ns) / 1000000L);
}

static void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void say(const char *fmt, ...)
{
    char b[1024];
    int n, m;
    va_list ap;
    if (log_fd < 0 || log_lines > MAX_LINES) return;
    __sync_fetch_and_add(&log_lines, 1);
    n = 0;
    {
        unsigned long v = ms();
        char tmp[24];
        int k = 0;
        do { tmp[k++] = (char)('0' + v % 10); v /= 10; } while (v);
        while (k) b[n++] = tmp[--k];
        b[n++] = ' ';
    }
    va_start(ap, fmt);
    m = vsnprintf(b + n, sizeof b - (unsigned long)n - 1, fmt, ap);
    va_end(ap);
    if (m < 0) return;
    n += m;
    if (n > (int)sizeof b - 2) n = (int)sizeof b - 2;
    b[n++] = '\n';
    write(log_fd, b, (unsigned long)n);
}

static long tid(void) { return syscall(SYS_GETTID); }

/* ---- the sites file ------------------------------------------------------------------ */
struct entry { char name[24]; unsigned addr, w0, w1; int site; };
static struct entry entries[24];
static int n_entries;

static int hexval(int c)
{
    return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10
         : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
}

static unsigned number(const char **p)
{
    const char *s = *p;
    unsigned x = 0;
    int base = 10;
    while (*s == ' ' || *s == '\t') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
    for (;; s++) {
        int d = hexval(*s);
        if (d < 0 || (base == 10 && d > 9)) break;
        x = x * (unsigned)base + (unsigned)d;
    }
    *p = s;
    return x;
}

static int same(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static const char *word(const char *s, char *out, unsigned cap)
{
    unsigned n = 0;
    while (*s == ' ' || *s == '\t') s++;
    while (*s && *s != ' ' && *s != '\t' && *s != '\n' && *s != '\r') {
        if (n + 1 < cap) out[n++] = *s;
        s++;
    }
    out[n] = 0;
    return s;
}

static void load_sites(void)
{
    static char buf[4096];
    long n, tot = 0;
    const char *s;
    int fd = open("/dump/event.sites", O_RDONLY);
    if (fd < 0) return;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - (unsigned long)tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    for (s = buf; *s;) {
        char key[8];
        struct entry *e = &entries[n_entries];
        const char *line = s;
        while (*s && *s != '\n') s++;
        if (*s) s++;
        line = word(line, key, sizeof key);
        if (n_entries >= (int)(sizeof entries / sizeof entries[0])) break;
        if (!same(key, "site") && !same(key, "data")) continue;
        e->site = same(key, "site");
        line = word(line, e->name, sizeof e->name);
        e->addr = number(&line);
        if (e->site) { e->w0 = number(&line); e->w1 = number(&line); }
        if (e->name[0] && e->addr) n_entries++;
    }
}

static struct entry *find(const char *name, int site)
{
    int i;
    for (i = 0; i < n_entries; i++)
        if (entries[i].site == site && same(entries[i].name, name)) return &entries[i];
    return 0;
}

static unsigned data(const char *name) { struct entry *e = find(name, 0); return e ? e->addr : 0; }

/* the words, followed through another preloaded object's trampoline (pad_mode_runtime.c's shape) */
static int words_ok(struct entry *e)
{
    const unsigned *p;
    int depth;
    if (!e) return 0;
    p = (const unsigned *)(unsigned long)e->addr;
    for (depth = 0; depth < 4; depth++) {
        if (p[0] == e->w0 && p[1] == e->w1) return 1;
        if (p[0] != 0xe51ff004u) break;
        p = (const unsigned *)(unsigned long)p[1];
        if (p[0] != 0xe92d500fu) break;
        if (p[14] == e->w0 && p[15] == e->w1) return 1;
        p += 6;
    }
    return 0;
}

/* ---- is this the game? ----------------------------------------------------------------- */
static int is_game_process(unsigned addr)
{
    static char buf[65536];
    long n, tot = 0;
    char *s = buf, *e;
    int fd = open("/proc/self/maps", O_RDONLY);
    if (fd < 0) return 0;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - (unsigned long)tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    while (*s) {
        unsigned long lo = 0, hi = 0;
        char *q = s;
        int d;
        for (e = s; *e && *e != '\n'; e++) ;
        for (; (d = hexval(*q)) >= 0; q++) lo = lo * 16 + (unsigned)d;
        if (*q == '-') {
            q++;
            for (; (d = hexval(*q)) >= 0; q++) hi = hi * 16 + (unsigned)d;
            if (lo <= addr && addr + 8 <= hi && q[0] == ' ' && q[1] == 'r' && q[3] == 'x') {
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

/* ---- the runtime's trampoline ------------------------------------------------------------ */
typedef void (*hook_fn)(unsigned *regs);      /* r0..r3, ip, lr, then stack arguments */
static unsigned tramp[16 * 16] __attribute__((aligned(4096)));
static int tramp_used;

static void relocate_literal(unsigned *t, int i, unsigned addr, unsigned w)
{
    unsigned imm, at;
    if ((w & 0xFF7F0000u) != 0xE51F0000u || ((w >> 12) & 0xF) == 15) return;
    imm = w & 0xFFF;
    at = addr + (unsigned)i * 4 + 8;
    at = (w & 0x00800000u) ? at + imm : at - imm;
    t[12 + i] = *(const unsigned *)(unsigned long)at;
    t[6 + i] = 0xE59F0010u | (w & 0xF000u);
}

static int hook(unsigned addr, hook_fn logger)
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t;
    int i;
    if (!addr || tramp_used >= 16) return 0;
    t = tramp + tramp_used++ * 16;
    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;   /* mov r0, sp */
    t[2] = 0xe1a00000u;   /* nop */
    t[3] = 0xe59fc014u;   /* ldr ip, [pc, #20] -> t[10] */
    t[4] = 0xe12fff3cu;   /* blx ip */
    t[5] = 0xe8bd500fu;   /* pop {r0,r1,r2,r3,ip,lr} */
    t[6] = p[0];
    t[7] = p[1];
    t[8] = 0xe59ff004u;   /* ldr pc, [pc, #4] -> t[11] */
    t[9] = 0u;
    t[10] = (unsigned)(unsigned long)logger;
    t[11] = addr + 8u;
    t[14] = p[0];
    t[15] = p[1];
    for (i = 0; i < 2; i++) relocate_literal(t, i, addr, p[i]);
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;   /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* ---- the game, right now --------------------------------------------------------------- */
static unsigned player(void)
{
    unsigned a = data("cur_player");
    return a ? *(unsigned char *)(unsigned long)a : 0;
}

static unsigned mode_mask(void)
{
    unsigned a = data("mode_mask");
    return a ? *(unsigned short *)(unsigned long)a : 0;
}

/* ---- subscribe ----------------------------------------------------------------------------- */
static volatile int n_reg;

static void on_subscribe(unsigned *r)
{
    if (__sync_fetch_and_add(&n_reg, 1) >= MAX_REG) return;
    say("sub id=0x%02x handler=0x%08x prio=%u r0=0x%08x lr=0x%08x tid=%ld",
        r[1], r[2], r[3] & 0xff, r[0], r[5], tid());
}

/* ---- dispatch ---------------------------------------------------------------------------- */
static volatile unsigned total[N_IDS], window[N_IDS], shown[N_IDS];
static volatile long disp_tid;

static void on_dispatch(unsigned *r)
{
    unsigned id = r[0];
    long t;
    if (id >= N_BUS_IDS) { say("disp id=%u OUT OF RANGE lr=0x%08x", id, r[5]); return; }
    __sync_fetch_and_add(&total[id], 1);
    __sync_fetch_and_add(&window[id], 1);
    if (__sync_fetch_and_add(&shown[id], 1) >= FIRST_CALLS) return;
    t = tid();
    say("disp id=0x%02x arg=0x%08x lr=0x%08x tid=%ld p=%u mask=0x%04x", id, r[1], r[5], t, player(), mode_mask());
    if (disp_tid != t) {
        say("dispatch thread %ld (was %ld)", t, disp_tid);
        disp_tid = t;
    }
}

/* ---- watched functions ------------------------------------------------------------------- */
static struct entry *watched[N_WATCH];
static int n_watched;

static void on_watch(int k, unsigned *r)
{
    unsigned id = N_BUS_IDS + (unsigned)k;
    __sync_fetch_and_add(&total[id], 1);
    __sync_fetch_and_add(&window[id], 1);
    if (__sync_fetch_and_add(&shown[id], 1) >= FIRST_CALLS) return;
    say("watch %s id=0x%02x r0=0x%08x r1=0x%08x r2=0x%08x r3=0x%08x lr=0x%08x tid=%ld p=%u mask=0x%04x",
        watched[k]->name, id, r[0], r[1], r[2], r[3], r[5], tid(), player(), mode_mask());
}

#define WATCH(k) static void on_watch##k(unsigned *r) { on_watch(k, r); }
WATCH(0) WATCH(1) WATCH(2) WATCH(3) WATCH(4) WATCH(5) WATCH(6) WATCH(7)
static const hook_fn watch_hooks[N_WATCH] = { on_watch0, on_watch1, on_watch2, on_watch3,
                                              on_watch4, on_watch5, on_watch6, on_watch7 };

/* ---- tick ---------------------------------------------------------------------------------- */
static void dump_table(const char *why)
{
    unsigned tab = data("table"), id;
    if (!tab) return;
    for (id = 0; id < N_BUS_IDS; id++) {            /* the table holds bus ids only: past it is another global */
        unsigned *node = *(unsigned **)(unsigned long)(tab + 4 * id);
        char line[900];
        int n = 0, guard = 40;
        if (!node) continue;
        while (node && guard-- > 0 && n < (int)sizeof line - 32) {
            n += __builtin_snprintf(line + n, sizeof line - (unsigned long)n, " 0x%08x/%u",
                                    node[0], (unsigned)(*(unsigned char *)(node + 1)));
            node = (unsigned *)(unsigned long)node[2];
        }
        say("table(%s) id=0x%02x:%s", why, id, line);
    }
}

static void close_window(const char *label)
{
    static char open_label[64] = "boot";
    static unsigned long opened;
    char line[3000];
    int n = 0;
    unsigned id, now = (unsigned)ms();
    for (id = 0; id < N_IDS; id++) {
        unsigned c = window[id];
        if (!c) continue;
        __sync_fetch_and_add(&window[id], -c);
        if (n < (int)sizeof line - 24)
            n += __builtin_snprintf(line + n, sizeof line - (unsigned long)n, " %02x=%u", id, c);
        shown[id] = 0;
    }
    line[n] = 0;
    say("window %s %lu ms:%s", open_label, (unsigned long)(now - opened), line);
    say("mark %s p=%u mask=0x%04x", label, player(), mode_mask());
    opened = now;
    for (n = 0; label[n] && n < (int)sizeof open_label - 1; n++) open_label[n] = label[n];
    open_label[n] = 0;
}

static int read_trigger(const char *path, char *out, unsigned cap)
{
    long n;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    n = read(fd, out, cap - 1);
    close(fd);
    unlink(path);
    out[n > 0 ? n : 0] = 0;
    for (n = 0; out[n] && out[n] != '\n' && out[n] != '\r'; n++) ;
    out[n] = 0;
    return 1;
}

static void force(const char *what)
{
    struct entry *get = find("mode_get", 1);
    unsigned mgr = data("mode_mgr"), id, **obj;
    const char *s = what;
    int stop = 0;
    if (s[0] == 's' && s[1] == 't' && s[2] == 'o' && s[3] == 'p') { stop = 1; s += 4; }
    id = number(&s);
    if (!get || !mgr) { say("force %s: no mode_get / mode_mgr in event.sites", what); return; }
    obj = ((unsigned **(*)(unsigned, unsigned))(unsigned long)get->addr)(mgr, id);
    if (!obj) { say("force %s: get returned 0", what); return; }
    say("force %s mode %u obj=0x%08x vptr=0x%08x p=%u mask=0x%04x", stop ? "stop" : "start", id,
        (unsigned)(unsigned long)obj, (unsigned)(unsigned long)*obj, player(), mode_mask());
    if (stop) ((void (*)(void *, unsigned))(unsigned long)(*obj)[11])(obj, 0u);
    else ((void (*)(void *))(unsigned long)(*obj)[8])(obj);
    say("force %s mode %u returned, mask=0x%04x", stop ? "stop" : "start", id, mode_mask());
}

static void on_tick(unsigned *r)
{
    static unsigned ticks;
    char buf[64];
    (void)r;
    if (ticks++ == 0) {
        say("first tick on thread %ld; %d registrations so far", tid(), n_reg);
        dump_table("first tick");
    }
    if (ticks % 30) return;
    if (read_trigger("/dump/event.mark", buf, sizeof buf)) {
        close_window(buf[0] ? buf : "(empty)");
        if (same(buf, "table")) dump_table("mark");
    }
    if (read_trigger("/dump/event.force", buf, sizeof buf)) force(buf);
}

__attribute__((constructor))
static void event_probe_start(void)
{
    struct entry *sub, *disp, *tick, *get;
    load_sites();
    tick = find("tick", 1);
    if (!tick || !is_game_process(tick->addr)) return;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    log_fd = open("/dump/event.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    sub = find("subscribe", 1);
    disp = find("dispatch", 1);
    get = find("mode_get", 1);
    say("event probe: %d entries; tick %s, subscribe %s, dispatch %s, mode_get %s", n_entries,
        words_ok(tick) ? "ok" : "WRONG", sub && words_ok(sub) ? "ok" : "WRONG/absent",
        disp && words_ok(disp) ? "ok" : "WRONG/absent", get ? (words_ok(get) ? "ok" : "WRONG") : "absent");
    if (get && !words_ok(get)) get->site = 2;          /* never call a function that moved */
    if (!words_ok(tick)) { say("tick words wrong: nothing hooked"); return; }
    if (sub && words_ok(sub)) hook(sub->addr, on_subscribe);
    if (disp && words_ok(disp)) hook(disp->addr, on_dispatch);
    hook(tick->addr, on_tick);
    {
        int i;
        for (i = 0; i < n_entries && n_watched < N_WATCH; i++) {
            struct entry *e = &entries[i];
            if (e->site != 1 || e->name[0] != 'w' || e->name[1] != 'a' || e->name[5] != '_') continue;
            if (!words_ok(e)) { say("watch %s 0x%08x: words WRONG, not hooked", e->name, e->addr); continue; }
            watched[n_watched] = e;
            if (hook(e->addr, watch_hooks[n_watched]))
                say("watch %s 0x%08x = id 0x%02x", e->name, e->addr, N_BUS_IDS + (unsigned)n_watched);
            n_watched++;
        }
    }
    say("hooked; pid thread %ld", tid());
}
