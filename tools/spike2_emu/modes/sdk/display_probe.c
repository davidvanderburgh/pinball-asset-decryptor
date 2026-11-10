/* display_probe.c - WHO takes the Spike 2 display, and at what priority? (item 154 display; a porting
 * instrument, MODE_SDK.md "Display priority")
 *
 * The game arbitrates its display on two levels (read off Godzilla Pro 1.15 / Premium 1.16):
 *   1. DISPLAY EFFECTS: a table of 152 effects {process fn, u16 flags, u8 priority}; one runs at a time
 *      (dm+0xc id, dm+0xe priority); deff_start(dm, id, queue, force, one) starts a higher one (killing
 *      the current), refuses a lower one, or queues it (queue != 0).
 *   2. LAYERED DISPLAYS (BDL): under the layered-display host effect, a background + one foreground
 *      (bdl mgr +0x58 request, +0x5c priority), each requested by a WAITER process that waits until its
 *      priority >= bdl_cur_prio(mgr) and the host effect is current.
 * This probe logs every request on both levels, every clip_play, and every change of the state, and
 * can HOLD the display the way a mode of ours would (display.hold "<P> <Q>": effects of priority <= P
 * and layered foregrounds of priority < Q wait), to test that the game's own arbitration does the rest.
 *
 * build_mode.sh -p -o display_probe.so display_probe.c ; preload it with PAD_TRACE_SO; sites in
 * /dump/display.sites (below); log /dump/display.log. Triggers (read twice a second):
 *   /dump/display.mark "<label>"   a mark line
 *   /dump/display.hold "<P> <Q>"   hold (0 0 releases; the release puts the host's priority back and runs
 *                                  the effect queue, as the end of a display effect does)
 *   /dump/display.force "<id>" | "stop <id>"   start / stop stock mode id (cmode_manager get -> v[8] / v[11])
 *   /dump/display.deff "<id>"      start display effect id with queue 0, force 0 (the award-screen call)
 *   /dump/display.fg "<id>"        show layered display id now (bdl_fg, as its waiter does; in a game)
 *
 *   site tick | deff_start | deff_start_w | deff_waiter | bdl_waiter | bdl_fg | bdl_bg | clip_play |
 *        bdl_cur_prio | deff_service | mode_get     <addr> <w0> <w1>
 *   data dm_ptr | bdl_mgr_ptr | cur_proc | deff_table | bdl_table | mode_mgr | cur_player <addr>
 * Godzilla Premium 1.16's display.sites (item 154 display runs r1-r7; Pro 1.15's addresses are in its
 * port's display lines):
 *   site tick           0x003b5420 0xe92d4038 0xe3a00037
 *   site deff_start     0x00439194 0xe92d47f0 0xe2516000
 *   site deff_start_w   0x00405908 0xe92d4070 0xe24dd008
 *   site deff_waiter    0x00052d08 0xe92d4ff0 0xe30494f8
 *   site bdl_waiter     0x00052ea4 0xe92d4ff0 0xe304c4f8
 *   site bdl_fg         0x0003da68 0xe92d40f0 0xe1a04000
 *   site bdl_bg         0x0003dd08 0xe92d41f0 0xe3076858
 *   site clip_play      0x000529f4 0xe92d43f0 0xe24dd014
 *   site bdl_cur_prio   0x0003cfcc 0xe92d4008 0xe5903058
 *   site deff_service   0x00439578 0xe30735a4 0xe340307f
 *   site mode_get       0x000d3fa0 0xe351001a 0xe92d4008
 *   data dm_ptr         0x007f75a4
 *   data bdl_mgr_ptr    0x007b0f70
 *   data cur_proc       0x007d627c
 *   data deff_table     0x0070c378
 *   data bdl_table      0x0070bc3c
 *   data mode_mgr       0x007b0ce4
 *   data cur_player     0x00713b94
 * Log lines: "DEFF start id= prio= queue= force= ... | cur=<effect>/<priority>", "DEFF waiter", "BDL waiter",
 * "BDL fg request", "CLIP play", "ST effect <id> prio <p> ... | layered fg bdl <n> prio <p> bg idx <i>".
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
#define MAX_LINES 80000

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
    char b[600];
    int n, m;
    va_list ap;
    if (log_fd < 0 || log_lines > MAX_LINES) return;
    __sync_fetch_and_add(&log_lines, 1);
    n = __builtin_snprintf(b, sizeof b, "%8lu ", ms());
    va_start(ap, fmt);
    m = vsnprintf(b + n, sizeof b - (unsigned long)n - 1, fmt, ap);
    va_end(ap);
    if (m < 0) return;
    n += m;
    if (n > (int)sizeof b - 2) n = (int)sizeof b - 2;
    b[n++] = '\n';
    write(log_fd, b, (unsigned long)n);
}

/* ---- the sites file ------------------------------------------------------------------ */
struct entry { char name[24]; unsigned addr, w0, w1; int site; };
static struct entry entries[48];
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
    while (*s == ' ' || *s == '\t') s++;
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
    int fd = open("/dump/display.sites", O_RDONLY);
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

static unsigned fn(const char *name)
{
    struct entry *e = find(name, 1);
    return e && words_ok(e) ? e->addr : 0;
}

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
    t[0] = 0xe92d500fu; t[1] = 0xe1a0000du; t[2] = 0xe1a00000u; t[3] = 0xe59fc014u;
    t[4] = 0xe12fff3cu; t[5] = 0xe8bd500fu; t[6] = p[0]; t[7] = p[1];
    t[8] = 0xe59ff004u; t[9] = 0u; t[10] = (unsigned)(unsigned long)logger; t[11] = addr + 8u;
    t[14] = p[0]; t[15] = p[1];
    for (i = 0; i < 2; i++) relocate_literal(t, i, addr, p[i]);
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* a veto hook (pad_mode_runtime.c's shape): the logger returns non-zero to skip the function */
typedef int (*veto_fn)(unsigned *regs);
static int hook_veto(unsigned addr, veto_fn logger)
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t;
    if (!addr || tramp_used >= 16) return 0;
    if ((p[0] & 0x0F7F0000u) == 0x051F0000u || (p[1] & 0x0F7F0000u) == 0x051F0000u) return 0;
    t = tramp + tramp_used++ * 16;
    t[0] = 0xe92d500fu; t[1] = 0xe1a0000du; t[2] = 0xe1a00000u; t[3] = 0xe59fc020u;
    t[4] = 0xe12fff3cu; t[5] = 0xe3500000u; t[6] = 0xe8bd500fu; t[7] = 0x13a00001u;
    t[8] = 0x112fff1eu; t[9] = p[0]; t[10] = p[1]; t[11] = 0xe59ff004u; t[12] = 0u;
    t[13] = (unsigned)(unsigned long)logger; t[14] = addr + 8u; t[15] = 0u;
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* ---- the game's display state ------------------------------------------------------------ */
static unsigned char *dm(void)
{
    unsigned a = data("dm_ptr");
    return a ? *(unsigned char **)(unsigned long)a : 0;
}

static unsigned char *bdl_mgr(void)
{
    unsigned a = data("bdl_mgr_ptr");
    return a ? *(unsigned char **)(unsigned long)a : 0;
}

static unsigned deff_prio(unsigned id)
{
    unsigned t = data("deff_table"), ent, cnt;
    if (!t) return 0;
    ent = *(unsigned *)(unsigned long)t;
    cnt = *(unsigned *)(unsigned long)(t + 4);
    return id < cnt ? *(unsigned char *)(unsigned long)(ent + 8 * id + 6) : 999;
}

static unsigned bdl_prio(unsigned id, unsigned *flags)
{
    unsigned t = data("bdl_table"), ent, cnt;
    if (!t) return 0;
    ent = *(unsigned *)(unsigned long)t;
    cnt = *(unsigned *)(unsigned long)(t + 4);
    if (id >= cnt) return 999;
    if (flags) *flags = *(unsigned *)(unsigned long)(ent + 16 * id);
    return *(unsigned char *)(unsigned long)(ent + 16 * id + 12);
}

static unsigned proc_id(void)
{
    unsigned a = data("cur_proc");
    unsigned char *p = a ? *(unsigned char **)(unsigned long)a : 0;
    return p ? *(unsigned short *)p : 0;
}

static unsigned player(void)
{
    unsigned a = data("cur_player");
    return a ? *(unsigned char *)(unsigned long)a : 0;
}

static int queue_len(unsigned char *d)
{
    unsigned head = *(unsigned *)(d + 0xf78), tail = *(unsigned *)(d + 0xf7c);
    int n = 0;
    while (head != tail && n < 64) {
        head += 0x148;
        if (head > (unsigned)(unsigned long)(d + 0xe30)) head = (unsigned)(unsigned long)(d + 0x18);
        n++;
    }
    return n;
}

/* the priority bdl_cur_prio(mgr) answers, computed as the game's function does */
static unsigned bdl_real_prio(unsigned char *m)
{
    int idx;
    unsigned char *v0, *v1;
    if (*(unsigned *)(m + 0x58)) return m[0x5c];
    idx = *(int *)(m + 0x44);
    if (idx == -1) return 0;
    v0 = *(unsigned char **)(m + 0x48);
    v1 = *(unsigned char **)(m + 0x4c);
    if (idx < 0 || (unsigned)idx >= (unsigned)((v1 - v0) / 20)) return 0;
    return v0[idx * 20 + 4];
}

/* ---- hold ---------------------------------------------------------------------------------- */
static unsigned hold_p, hold_q, host_id, host_prio;
static unsigned char fake_mgr[0x60];

static void on_bdl_cur_prio(unsigned *r)
{
    unsigned real;
    unsigned char *m = (unsigned char *)(unsigned long)r[0];
    if (!hold_q || !m) return;
    real = bdl_real_prio(m);
    if (real >= hold_q) return;
    *(unsigned *)(fake_mgr + 0x58) = 1;
    fake_mgr[0x5c] = (unsigned char)hold_q;
    r[0] = (unsigned)(unsigned long)fake_mgr;
}

static void hold_tick(void)
{
    unsigned char *d = dm();
    if (!d || !hold_p || !host_id) return;
    if (*(unsigned short *)(d + 0xc) == host_id && d[0xe] < hold_p) {
        say("hold: the host effect %u is current at priority %u - raised to %u", host_id, d[0xe], hold_p);
        d[0xe] = (unsigned char)hold_p;
    }
}

static void hold_set(unsigned p, unsigned q)
{
    unsigned char *d = dm();
    unsigned was = hold_p;
    hold_p = p;
    hold_q = q;
    say("hold: P %u (effects <= P wait) Q %u (layered foregrounds < Q wait)", p, q);
    if (p) { hold_tick(); return; }
    if (was && d && *(unsigned short *)(d + 0xc) == host_id && d[0xe] == was) {
        d[0xe] = (unsigned char)host_prio;
        say("hold: released - the host's priority %u back, queue %d", host_prio, queue_len(d));
        if (fn("deff_service") && queue_len(d)) {
            ((void (*)(void))(unsigned long)fn("deff_service"))();
            say("hold: the effect queue was run");
        }
    }
}

/* ---- the hooks ------------------------------------------------------------------------------ */
static void on_deff_start(unsigned *r)
{
    unsigned char *d = (unsigned char *)(unsigned long)r[0];
    static unsigned skipped;
    if (d && r[1] == *(unsigned short *)(d + 0x12) && *(unsigned short *)(d + 0xc) && deff_prio(*(unsigned short *)(d + 0xc)) > 1) {
        if (++skipped % 500 == 1) say("DEFF (the background %u asked again under effect %u: %u times so far, not logged)",
                                      r[1], *(unsigned short *)(d + 0xc), skipped);
        return;
    }
    say("DEFF start id=%u prio=%u queue=%u force=%u a5=%u lr=0x%08x proc=0x%x | cur=%u/%u bg=%u q=%d p=%u",
        r[1], deff_prio(r[1]), r[2], r[3], r[6] & 0xff, r[5], proc_id(),
        d ? *(unsigned short *)(d + 0xc) : 0, d ? d[0xe] : 0, d ? *(unsigned short *)(d + 0x12) : 0,
        d ? queue_len(d) : -1, player());
}

static void first_thread(const char *what, volatile int *said)
{
    if (*said || !__sync_bool_compare_and_swap(said, 0, 1)) return;
    say("THREAD %s runs on thread %ld", what, syscall(SYS_GETTID));
}

static void on_deff_waiter(unsigned *r)
{
    static volatile int said;
    first_thread("an effect waiter", &said);
    say("DEFF waiter id=%u prio(own)=%u timeout=%u tab-prio=%u cb=0x%08x lr=0x%08x proc=0x%x",
        r[0] & 0xffff, r[2] & 0xff, r[1], deff_prio(r[0] & 0xffff), r[3], r[5], proc_id());
}

static void on_bdl_waiter(unsigned *r)
{
    static volatile int said;
    first_thread("a layered waiter", &said);
    unsigned fl = 0, pr = bdl_prio(r[0], &fl);
    say("BDL waiter bdl=%u prio(own)=%u timeout=%u tab-prio=%u flags=0x%x cb=0x%08x lr=0x%08x proc=0x%x",
        r[0], r[2] & 0xff, r[1], pr, fl, r[3], r[5], proc_id());
}

static void on_bdl_fg(unsigned *r)
{
    unsigned fl = 0, pr = bdl_prio(r[1], &fl);
    unsigned char *m = (unsigned char *)(unsigned long)r[0];
    say("BDL fg request bdl=%u prio=%u flags=0x%x lr=0x%08x | cur fg %s prio %u bg idx %d",
        r[1], pr, fl, r[5], m && *(unsigned *)(m + 0x58) ? "up" : "none", m ? m[0x5c] : 0, m ? *(int *)(m + 0x44) : -9);
}

static void on_bdl_bg(unsigned *r)
{
    unsigned fl = 0, pr = bdl_prio(r[1], &fl);
    say("BDL bg request bdl=%u prio=%u flags=0x%x lr=0x%08x", r[1], pr, fl, r[5]);
}

static void on_clip_play(unsigned *r)
{
    static volatile int said;
    first_thread("clip_play", &said);
    const char *name = (const char *)(unsigned long)r[0], *crop = (const char *)(unsigned long)r[2];
    say("CLIP play \"%.60s\" loop=%u crop=\"%.20s\" lr=0x%08x proc=0x%x", name ? name : "(null)", r[1],
        crop ? crop : "", r[5], proc_id());
}

/* ---- draw-order trace (hud-layers): who puts which scene on which display layer, in what order,
 * each frame. /dump/display.trace "<ticks>" logs every scene_show(scene, layer) and
 * display_draw(display, scene, layer) for that many ticks, a TICK line between. */
static volatile unsigned trace_ticks, draw1_ticks, draw1_layer;
static unsigned long draw1_last;

static unsigned vt_of(unsigned p)
{
    return p && p > 0x10000 ? *(unsigned *)(unsigned long)p : 0;
}

static void bg_swap(unsigned *r);

static void on_scene_show(unsigned *r)
{
    bg_swap(r);
    if (!trace_ticks) return;
    say("SS scene=0x%08x vt=0x%08x layer=%u lr=0x%08x proc=0x%x", r[0], vt_of(r[0]), r[1], r[5], proc_id());
}

static void on_display_draw(unsigned *r)
{
    if (!trace_ticks) return;
    say("DD disp=0x%08x scene=0x%08x vt=0x%08x layer=%u lr=0x%08x", r[0], r[1], vt_of(r[1]), r[2], r[5]);
}

/* ---- our video IN THE CITY'S PLACE (hud-layers) ---------------------------------------------
 * Each frame the layered display draws its background element first: BDLBackground::v[8] (site
 * bg_draw) shows the video player when the background has a clip, then the element's own scene -
 * the city, for the five main-play backgrounds (data bg_city_vtable). The HUD scenes come after.
 * While /dump/display.bg is on, a veto hook on that draw shows the video player INSTEAD of the city
 * (scene_show(player, 3), the current effect's layer), so a clip on the surface sits where the city
 * was: under the score panel, the slide-outs and a mode's own screen. */
static volatile int bg_on;
static char bg_name[96], bg_crop[24];
static unsigned bg_draws, bg_replays;

/* h5: nothing of the game's is skipped. The background element's draw (a plain hook) notes WHICH
 * element is drawing; the scene_show hook then swaps the argument when that element is a city and the
 * scene is its own ([this+24]): the game's own call shows the player in the city's place. */
static volatile unsigned bg_elem;

static void on_bg_draw(unsigned *r)
{
    bg_elem = r[0];
}

/* h6: the city is still shown (its own video keeps playing: hiding it made the game pause it, and the
 * emulator's renderer then stopped presenting - runs h4, h5), and our player right after it: the
 * city's scene is shown here first (a nested call, let through), then the game's own call is given
 * the player. Order: city, our video, the HUD. */
static volatile int bg_nested, bg_over = 2;
/* h9 (bg_over 2): the TICK draws the player (layer 0, after everything the frame showed - the runtime's
 * hardware-proven clip route) and then shows the frame's HUD scenes AGAIN over it: their "in the list"
 * byte (scene+8+layer) cleared, display_draw adds them a second time. The HUD scenes are the ones the
 * score frame overlay showed this frame (lr = data hud_lr1..3). */
static volatile unsigned hud_scene[3];
/* h11 (bg_over 3): the clip is PLAYED from inside the layered display's process (the game's clips are:
 * proc 2; ours from the tick were proc 0), at the first city draw after "on", then drawn over the city */
static volatile int bg_play_pending;
/* h12 (bg_over 5 / 6): THE GAME'S OWN WAY - played in-process, then the city object's own video field
 * (+0x54, what BDLBackground::v[13] sets for a background with a clip) set to the surface: the game's
 * update (v[7]) advances the player and its draw (v[8]) shows it, then the city scene. 6 also skips the
 * city scene: its show is given the player, already in the frame's list, so display_draw refuses it. */
static volatile unsigned bg_city_obj;

static void bg_swap(unsigned *r)
{
    unsigned vp = fn("video_player"), city = data("bg_city_vtable"), ss = fn("scene_show"), e = bg_elem;
    unsigned player;
    if (bg_over == 2) {
        unsigned k;
        static const char *const lrn[3] = { "hud_lr1", "hud_lr2", "hud_lr3" };
        for (k = 0; k < 3; k++)
            if (r[5] == data(lrn[k])) hud_scene[k] = r[0];
        return;
    }
    if (bg_nested || !bg_on || !e || !vp || !ss || vt_of(e) != city || r[0] != *(unsigned *)(unsigned long)(e + 24)) return;
    if ((bg_over == 5 || bg_over == 6) && bg_on) {
        if (bg_play_pending) {
            unsigned cp = fn("clip_play"), vs = fn("video_surface");
            bg_play_pending = 0;
            if (cp) ((void (*)(const char *, unsigned, const char *))(unsigned long)cp)(bg_name, 1u, bg_crop[0] ? bg_crop : 0);
            if (vs) *(unsigned *)(unsigned long)(e + 0x54) = (unsigned)(unsigned long)((void *(*)(void))(unsigned long)vs)();
            bg_city_obj = e;
            say("bg: \"%s\" played in-process; the city 0x%08x's video field = 0x%08x (mode %d)", bg_name, e,
                *(unsigned *)(unsigned long)(e + 0x54), bg_over);
            return;
        }
        if (bg_over == 6) {
            if (bg_draws++ % 600 == 0) say("bg: the city scene skipped (draw %u)", bg_draws);
            r[0] = (unsigned)(unsigned long)((void *(*)(void))(unsigned long)vp)();
        }
        return;
    }
    if (bg_over == 3 && bg_play_pending) {
        unsigned cp = fn("clip_play");
        bg_play_pending = 0;
        say("bg: \"%s\" played from inside the display process (proc 0x%x)", bg_name, proc_id());
        if (cp) ((void (*)(const char *, unsigned, const char *))(unsigned long)cp)(bg_name, 1u, bg_crop[0] ? bg_crop : 0);
        return;
    }
    player = (unsigned)(unsigned long)((void *(*)(void))(unsigned long)vp)();
    if (!player) return;
    {   /* h7: only a surface that PLAYS (2) is drawn - the game's own elements wait for it too (h4-h6
         * drew 35 ms after clip_play, still prerolling, and the renderer never presented again) */
        unsigned vs = fn("video_surface"), st = fn("surface_state");
        void *surf = vs ? ((void *(*)(void))(unsigned long)vs)() : 0;
        if (!surf || !st || ((int (*)(void *))(unsigned long)st)(surf) != 2) return;
    }
    if (bg_over == 1 || bg_over == 3) {
        bg_nested = 1;
        ((void (*)(unsigned, unsigned))(unsigned long)ss)(r[0], r[1]);
        bg_nested = 0;
    }
    if (bg_draws++ % 600 == 0) say("bg: our video 0x%08x shown over the city 0x%08x's scene 0x%08x (draw %u)", player, e, r[0], bg_draws);
    r[0] = player;
}

/* /dump/display.draw "<layer> <ticks>": draw the video bank's player on that layer from the tick, as the
 * runtime draws a mode's clip on layer 0 */
static void draw_tick(void)
{
    unsigned vp = fn("video_player"), adv = fn("player_advance"), dd = fn("display_draw"), holder = data("display_holder");
    void *player, *display;
    struct { long s, ns; } t;
    unsigned long now;
    if (bg_on && vp && bg_over != 5 && bg_over != 6) {
        unsigned vs = fn("video_surface"), st = fn("surface_state"), cp = fn("clip_play");
        unsigned char *m = bdl_mgr();
        static unsigned n;
        clock_gettime(CLOCK_MONOTONIC, &t);
        now = (unsigned long)(t.s * 1000L + t.ns / 1000000L);
        player = ((void *(*)(void))(unsigned long)vp)();
        if (player && adv && draw1_last) ((void (*)(void *, float))(unsigned long)adv)(player, (float)(now - draw1_last));
        draw1_last = now;
        if (bg_over == 2 && player && dd && holder) {
            void *surf0 = vs ? ((void *(*)(void))(unsigned long)vs)() : 0;
            display = *(void **)(unsigned long)(holder + 0x7c);
            if (display && surf0 && st && ((int (*)(void *))(unsigned long)st)(surf0) == 2) {
                unsigned k;
                if (bg_draws % 600 == 0 || trace_ticks)
                    say("bg: hud scenes 0x%08x 0x%08x 0x%08x flags %u %u %u", hud_scene[0], hud_scene[1], hud_scene[2],
                        hud_scene[0] ? *(unsigned char *)(unsigned long)(hud_scene[0] + 8) : 9,
                        hud_scene[1] ? *(unsigned char *)(unsigned long)(hud_scene[1] + 8) : 9,
                        hud_scene[2] ? *(unsigned char *)(unsigned long)(hud_scene[2] + 8) : 9);
                ((void (*)(void *, void *, unsigned))(unsigned long)dd)(display, player, 0u);
                for (k = 0; k < 3; k++) {
                    unsigned h = hud_scene[k];
                    if (!h) continue;
                    *(unsigned char *)(unsigned long)(h + 8) = 0;
                    ((void (*)(void *, void *, unsigned))(unsigned long)dd)(display, (void *)(unsigned long)h, 0u);
                    hud_scene[k] = 0;
                }
                if (bg_draws++ % 600 == 0) say("bg: the tick drew our video and the HUD again over it (%u)", bg_draws);
            }
        }
        /* the surface idle and no layered foreground up: our loop again (a framed clip took it) */
        if (++n % 30 == 0 && vs && st && cp && m && !*(unsigned *)(m + 0x58)) {
            void *surf = ((void *(*)(void))(unsigned long)vs)();
            if (surf && ((int (*)(void *))(unsigned long)st)(surf) != 2) {
                bg_replays++;
                say("bg: the surface is idle - \"%s\" again (%u)", bg_name, bg_replays);
                ((void (*)(const char *, unsigned, const char *))(unsigned long)cp)(bg_name, 1u, bg_crop[0] ? bg_crop : 0);
            }
        }
    }
    if (!draw1_ticks || !vp || !dd || !holder) return;
    draw1_ticks--;
    clock_gettime(CLOCK_MONOTONIC, &t);
    now = (unsigned long)(t.s * 1000L + t.ns / 1000000L);
    player = ((void *(*)(void))(unsigned long)vp)();
    display = *(void **)(unsigned long)(holder + 0x7c);
    if (!player || !display) return;
    if (adv && draw1_last) ((void (*)(void *, float))(unsigned long)adv)(player, (float)(now - draw1_last));
    draw1_last = now;
    ((void (*)(void *, void *, unsigned))(unsigned long)dd)(display, player, draw1_layer);
    if (trace_ticks) say("probe drew the player 0x%08x on layer %u", (unsigned)(unsigned long)player, draw1_layer);
}

/* ---- tick --------------------------------------------------------------------------------- */
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
    unsigned get = fn("mode_get"), mgr = data("mode_mgr"), id, **obj;
    const char *s = what;
    int stop = 0;
    if (s[0] == 's' && s[1] == 't' && s[2] == 'o' && s[3] == 'p') { stop = 1; s += 4; }
    id = number(&s);
    if (!get || !mgr) { say("force %s: no mode_get / mode_mgr", what); return; }
    obj = ((unsigned **(*)(unsigned, unsigned))(unsigned long)get)(mgr, id);
    if (!obj) { say("force %s: get returned 0", what); return; }
    say("force %s mode %u", stop ? "stop" : "start", id);
    if (stop) ((void (*)(void *, unsigned))(unsigned long)(*obj)[11])(obj, 0u);
    else ((void (*)(void *))(unsigned long)(*obj)[8])(obj);
}

static void on_tick(unsigned *r)
{
    static unsigned ticks, s_cur = 9999, s_pr = 9999, s_bg = 9999, s_fg = 9999, s_fgp = 9999;
    static int s_q = -9, s_bgi = -9;
    unsigned char *d = dm(), *m = bdl_mgr();
    char buf[64];
    (void)r;
    if (ticks++ == 0) say("first tick; dm %p bdl mgr %p", d, m);
    if (d) {
        unsigned cur = *(unsigned short *)(d + 0xc), pr = d[0xe], bg = *(unsigned short *)(d + 0x12);
        int q = queue_len(d);
        unsigned fg = m ? *(unsigned *)(m + 0x58) : 0, fgp = m ? m[0x5c] : 0;
        int bgi = m ? *(int *)(m + 0x44) : -9;
        if (!host_id && cur && (deff_prio(cur) == 1) && bg == cur && m) {
            /* the layered-display host: the background effect current while a layered display is up */
        }
        if (cur != s_cur || pr != s_pr || bg != s_bg || q != s_q || fg != s_fg || fgp != s_fgp || bgi != s_bgi) {
            say("ST effect %u prio %u (table %u) bg %u queue %d | layered fg bdl %u prio %u bg idx %d prio-now %u | p=%u",
                cur, pr, deff_prio(cur), bg, q, fg, fgp, bgi, m ? bdl_real_prio(m) : 0, player());
            s_cur = cur; s_pr = pr; s_bg = bg; s_q = q; s_fg = fg; s_fgp = fgp; s_bgi = bgi;
        }
    }
    hold_tick();
    draw_tick();
    if (trace_ticks) { say("TICK %u", ticks); trace_ticks--; }
    if (ticks % 30) return;
    if (read_trigger("/dump/display.trace", buf, sizeof buf)) {
        const char *s = buf;
        trace_ticks = number(&s);
        say("trace for %u ticks; video player 0x%08x", trace_ticks,
            fn("video_player") ? (unsigned)(unsigned long)((void *(*)(void))(unsigned long)fn("video_player"))() : 0);
    }
    if (read_trigger("/dump/display.bgover", buf, sizeof buf)) {
        bg_over = buf[0] - '0';
        say("bg: mode %d", bg_over);
    }
    if (read_trigger("/dump/display.bg", buf, sizeof buf)) {
        /* "<crop|-> <name>" plays the clip looped and shows it in the city's place; "off" stops */
        unsigned i = 0, j = 0, cp = fn("clip_play");
        if (buf[0] == 'o' && buf[1] == 'f' && buf[2] == 'f') {
            bg_on = 0;
            if (bg_city_obj) { *(unsigned *)(unsigned long)(bg_city_obj + 0x54) = 0; bg_city_obj = 0; }
            say("bg: off (%u draws, %u replays)", bg_draws, bg_replays);
            if (fn("clip_stop")) ((void (*)(void))(unsigned long)fn("clip_stop"))();
        } else {
            while (buf[i] && buf[i] != ' ' && j + 1 < sizeof bg_crop) bg_crop[j++] = buf[i++];
            bg_crop[j] = 0;
            if (bg_crop[0] == '-' && !bg_crop[1]) bg_crop[0] = 0;
            while (buf[i] == ' ') i++;
            for (j = 0; buf[i] && j + 1 < sizeof bg_name; ) bg_name[j++] = buf[i++];
            bg_name[j] = 0;
            draw1_last = 0;
            bg_on = 1;
            say("bg: on - \"%s\" crop \"%s\" in the city's place", bg_name, bg_crop);
            if (bg_over == 3 || bg_over == 5 || bg_over == 6) bg_play_pending = 1;
            else if (cp) ((void (*)(const char *, unsigned, const char *))(unsigned long)cp)(bg_name, 1u, bg_crop[0] ? bg_crop : 0);
        }
    }
    if (read_trigger("/dump/display.draw", buf, sizeof buf)) {
        const char *s = buf;
        draw1_layer = number(&s);
        draw1_ticks = number(&s);
        draw1_last = 0;
        say("the probe draws the player on layer %u for %u ticks", draw1_layer, draw1_ticks);
    }
    if (read_trigger("/dump/display.mark", buf, sizeof buf)) say("MARK %s", buf);
    if (read_trigger("/dump/display.hold", buf, sizeof buf)) {
        const char *s = buf;
        unsigned p = number(&s), q = number(&s);
        hold_set(p, q);
    }
    if (read_trigger("/dump/display.host", buf, sizeof buf)) {
        const char *s = buf;
        host_id = number(&s);
        host_prio = deff_prio(host_id);
        say("host effect %u (table priority %u)", host_id, host_prio);
    }
    if (read_trigger("/dump/display.force", buf, sizeof buf)) force(buf);
    if (read_trigger("/dump/display.clip", buf, sizeof buf)) {
        /* "<loop> <crop|-> <name>": play a clip on the video bank's surface and draw nothing - does
         * the game's own layering show it (a "ScoreFrame" clip under the HUD, as its framed displays)? */
        const char *s = buf, *crop;
        char *sp;
        unsigned loop = number(&s), f = fn("clip_play");
        while (*s == ' ') s++;
        crop = s;
        for (sp = (char *)s; *sp && *sp != ' '; sp++) ;
        if (*sp) *sp++ = 0;
        if (crop[0] == '-' && !crop[1]) crop = 0;
        say("clip \"%s\" loop %u crop \"%s\" requested by the probe", sp, loop, crop ? crop : "(null)");
        if (f) ((void (*)(const char *, unsigned, const char *))(unsigned long)f)(sp, loop, crop);
    }
    if (read_trigger("/dump/display.fg", buf, sizeof buf)) {
        /* PAD-1115: "<id>" asks the layered display host for foreground <id> straight away, the call a
         * layered waiter makes once the display is free (only acts while the host effect runs: a game) */
        const char *s = buf;
        unsigned id = number(&s), f = fn("bdl_fg");
        unsigned char *m = bdl_mgr();
        say("bdl fg %u requested by the probe: %s", id, f && m ? "calling" : "no bdl_fg / bdl mgr");
        if (f && m) ((void (*)(void *, unsigned))(unsigned long)f)(m, id);
    }
    if (read_trigger("/dump/display.deff", buf, sizeof buf)) {
        const char *s = buf;
        unsigned id = number(&s), f = fn("deff_start_w");
        say("deff %u requested by the probe: %s", id, f ? "calling" : "no deff_start_w");
        if (f) ((void *(*)(unsigned, unsigned, unsigned, unsigned))(unsigned long)f)(id, 0u, 0u, data("deff_table"));
    }
}

__attribute__((constructor))
static void display_probe_start(void)
{
    static const struct { const char *name; hook_fn f; } H[] = {
        { "deff_start", on_deff_start }, { "deff_waiter", on_deff_waiter }, { "bdl_waiter", on_bdl_waiter },
        { "bdl_fg", on_bdl_fg }, { "bdl_bg", on_bdl_bg }, { "clip_play", on_clip_play },
        { "bdl_cur_prio", on_bdl_cur_prio }, { "scene_show", on_scene_show }, { "display_draw", on_display_draw },
    };
    struct entry *tick;
    unsigned i;
    load_sites();
    tick = find("tick", 1);
    if (!tick || !is_game_process(tick->addr)) return;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    log_fd = open("/dump/display.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    say("display probe: %d entries, thread %ld", n_entries, syscall(SYS_GETTID));
    if (!words_ok(tick)) { say("tick words wrong: nothing hooked"); return; }
    host_id = 29;
    for (i = 0; i < sizeof H / sizeof H[0]; i++) {
        struct entry *e = find(H[i].name, 1);
        if (!e) { say("site %s absent", H[i].name); continue; }
        if (!words_ok(e)) { say("site %s 0x%08x words WRONG - not hooked", e->name, e->addr); continue; }
        say("site %s 0x%08x hooked %d", e->name, e->addr, hook(e->addr, H[i].f));
    }
    {
        struct entry *b = find("bg_draw", 1);
        if (b && words_ok(b)) say("site bg_draw 0x%08x hooked %d", b->addr, hook(b->addr, on_bg_draw));
    }
    hook(tick->addr, on_tick);
    host_prio = 1;
    say("armed; host effect %u", host_id);
}
