/* pad_mode_runtime.c - the half of every mode.so you do not write (item 134).
 *
 * It reads the game's PORT, checks it against the running game, hooks the game's tick,
 * shot dispatch and end of ball, and implements pad_mode.h on the game's own functions.
 * Every call here was first proven in the emulator on Godzilla Pro 1.15 with the
 * addresses as constants (items 125-133, tools/spike2_emu/modes/MODE_API.md); the only
 * change is that addresses, globals and struct offsets now come from the port.
 *
 * Built -nostdlib: libc is declared by hand below and resolved from the game's own libc
 * when the object loads. There is no allocator, so everything is static.
 */
#include "pad_mode.h"
#include "pad_stock.h"          /* item 161: the game's own rules in C */

extern int   open(const char *, int, ...);
extern long  read(int, void *, __SIZE_TYPE__);
extern long  write(int, const void *, __SIZE_TYPE__);
extern int   close(int);
extern int   unlink(const char *);
extern int   vsnprintf(char *, __SIZE_TYPE__, const char *, va_list);
extern int   clock_gettime(int, void *);
extern int   mprotect(void *, __SIZE_TYPE__, int);

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define CLOCK_MONOTONIC 1
#define U __attribute__((unused))

/* ---- the log ---------------------------------------------------------------------- */
static int log_fd = -1, log_lines;
static struct { long s, ns; } t0;
static const struct pm_mode *current;           /* whose callback is running */

unsigned long pm_ms(void)
{
    struct { long s, ns; } t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (unsigned long)((t.s - t0.s) * 1000L + (t.ns - t0.ns) / 1000000L);
}

static void log_raw(const char *who, const char *fmt, va_list ap)
{
    char b[400];
    int n, m;
    if (log_fd < 0 || log_lines > 40000) return;
    log_lines++;
    n = pm_snprintf(b, sizeof b, "%8lu [%s] ", pm_ms(), who);
    if (n < 0 || n >= (int)sizeof b) return;
    m = vsnprintf(b + n, sizeof b - (unsigned long)n, fmt, ap);
    if (m < 0) return;
    n += m;
    if (n >= (int)sizeof b - 1) n = (int)sizeof b - 2;
    if (b[n - 1] != '\n') b[n++] = '\n';
    write(log_fd, b, (unsigned long)n);
}

void pm_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    log_raw(current && current->name ? current->name : "mode", fmt, ap);
    va_end(ap);
}

static void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void say(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    log_raw("pad", fmt, ap);
    va_end(ap);
}

int pm_snprintf(char *out, unsigned long cap, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(out, cap, fmt, ap);
    va_end(ap);
    return n;
}

/* ---- small string helpers (no libc string functions here) --------------------------- */
static int str_eq(const char *a, const char *b)
{
    if (!a || !b) return 0;
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

static void str_copy(char *dst, unsigned cap, const char *src, unsigned n)
{
    unsigned i;
    for (i = 0; i < n && i + 1 < cap && src[i]; i++) dst[i] = src[i];
    dst[i] = 0;
}

static int hexval(int c)
{
    return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10
         : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
}

static uint64_t number(const char **p, int *ok)
{
    const char *s = *p;
    uint64_t x = 0;
    int base = 10, got = 0, neg = 0;
    while (*s == ' ' || *s == '\t') s++;
    if (s[0] == '-') { neg = 1; s++; }          /* item 163: `value countdown_step -1` */
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { base = 16; s += 2; }
    for (;; s++) {
        int d = hexval(*s);
        if (d < 0 || (base == 10 && d > 9)) break;
        x = x * (unsigned)base + (unsigned)d;
        got = 1;
    }
    while (*s == ' ' || *s == '\t') s++;
    *p = s;
    if (ok) *ok = got;
    return neg ? (uint64_t)0 - x : x;
}

void pm_commas(char *out, unsigned cap, uint64_t v)
{
    char rev[32];
    unsigned n = 0, i;
    if (!cap) return;
    do {
        if (n && n % 4 == 3) rev[n++] = ',';
        rev[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n + 2 < sizeof rev);
    for (i = 0; i < n && i + 1 < cap; i++) out[i] = rev[n - 1 - i];
    out[i] = 0;
}

/* ---- the port ------------------------------------------------------------------------
 * Key-per-line, `#` comments:
 *   game <name>                  version <text>
 *   site <name> <addr> <w0> <w1> a function: its address and first two instruction words
 *   data <name> <addr>           a global's address
 *   value <name> <number>        a struct offset, a flag, an id
 *   shot <mask> <name ...>       a named shot
 *   switch <id> <mask> <name ...> a switch whose hit is a shot: the switches section below
 *   callout <role> <id>          scene <role> <40-hex id>
 *   text <name> <rest of line>   anything else a mode may want
 * Looked for at /usr/local/padmode/game.port (a card) then /dump/game.port (the rig). */
static const char *const PORT_FILES[] = { "/usr/local/padmode/game.port", "/dump/game.port" };

/* The port is read in PORT_CHUNK pieces, a line at a time, up to PORT_MAX bytes. It was ONE read
 * into a buffer of the port's cap (16 KB, then 32 KB when the lamp lines took Godzilla's past 16 KB);
 * with the display lines too Godzilla Premium 1.16's is 23.6 KB. A port longer than PORT_MAX, or a
 * line a full table cannot take, is said in the boot log, never dropped silently. */
#define PORT_MAX   131072
#define PORT_CHUNK 4096
#define N_SITES    256      /* PAD-363: a title's mode starts (Venom names 50) */
#define N_DATA     224
#define N_VALUES   192      /* PAD-381: Godzilla Premium/LE names 129 (held coils, scoop and PAD-379's shield) */
#define N_SHOTS    64
#define N_ROLES    32
#define N_TEXTS    192      /* PAD-363: each mode a mode may hold off is named */
#define N_SWITCHES 64       /* a build's playfield switches as shots (the switch drain): up to 64, one bit each */
#define N_SWITCH_IDS 256      /* switch ids a `switch` line may name, and a switch_hit site may pass */

/* Limits a port must keep (port_words.py checks them): names up to 39 characters, a shot
 * name or a text value up to 159. */
struct site { char name[40]; unsigned addr, w0, w1; int ok; };
struct named { char name[40]; long value; };
struct shot { char name[160]; uint64_t mask; };
struct text { char name[40]; char value[160]; };
struct switch_shot { unsigned id; uint64_t mask; };

static struct {
    char game[32], version[24], path[40];
    struct site site[N_SITES]; int n_site;
    struct named data[N_DATA]; int n_data;
    struct named value[N_VALUES]; int n_value;
    struct shot shot[N_SHOTS]; int n_shot;
    struct switch_shot sw[N_SWITCHES]; int n_switch;
    struct named callout[N_ROLES]; int n_callout;
    struct text scene[N_ROLES]; int n_scene;
    struct text text[N_TEXTS]; int n_text;
    int dropped, too_long;    /* lines a full table could not take; 1 when the port is past PORT_MAX */
} port;

static unsigned can;          /* PM_CAN_* the verified port provides */

static const char *word(const char *s, char *out, unsigned cap)
{
    unsigned n = 0;
    while (*s == ' ' || *s == '\t') s++;
    while (*s && *s != ' ' && *s != '\t' && *s != '\n' && *s != '\r' && n + 1 < cap) out[n++] = *s++;
    out[n] = 0;
    while (*s && *s != ' ' && *s != '\t' && *s != '\n') s++;     /* a too-long word is cut */
    while (*s == ' ' || *s == '\t') s++;
    return s;
}

static void rest(const char *s, char *out, unsigned cap)
{
    unsigned n = 0;
    while (s[n] && s[n] != '\n' && s[n] != '\r' && n + 1 < cap) { out[n] = s[n]; n++; }
    while (n && (out[n - 1] == ' ' || out[n - 1] == '\t')) n--;
    out[n] = 0;
}

static void event_line(const char *s);        /* `event <name> <id>`: the events section below */
static void lamp_line(const char *s);         /* `lamp <lights> <shots> <name>`: the lights section */
static void rule_line(const char *s);         /* `rule <id> <vtable> <label>`: the stock rules section (item 160) */

static void port_line(const char *s)
{
    char key[16], name[40];
    int ok = 1;
    s = word(s, key, sizeof key);
    if (str_eq(key, "game")) { rest(s, port.game, sizeof port.game); return; }
    if (str_eq(key, "version")) { rest(s, port.version, sizeof port.version); return; }
    if ((str_eq(key, "site") && port.n_site >= N_SITES) || (str_eq(key, "shot") && port.n_shot >= N_SHOTS)) {
        port.dropped++;                                     /* said at the boot (pad_mode_start) */
        return;
    }
    if (str_eq(key, "site") && port.n_site < N_SITES) {
        struct site *x = &port.site[port.n_site];
        s = word(s, x->name, sizeof x->name);
        x->addr = (unsigned)number(&s, &ok);
        x->w0 = (unsigned)number(&s, 0);
        x->w1 = (unsigned)number(&s, 0);
        if (ok && x->name[0]) port.n_site++;
        return;
    }
    if ((str_eq(key, "data") || str_eq(key, "value") || str_eq(key, "callout"))) {
        struct named *tab = str_eq(key, "data") ? port.data : str_eq(key, "value") ? port.value : port.callout;
        int *n = str_eq(key, "data") ? &port.n_data : str_eq(key, "value") ? &port.n_value : &port.n_callout;
        int cap = str_eq(key, "value") ? N_VALUES : str_eq(key, "data") ? N_DATA : N_ROLES;
        if (*n >= cap) { port.dropped++; return; }
        s = word(s, tab[*n].name, sizeof tab[*n].name);
        tab[*n].value = (long)number(&s, &ok);
        if (ok && tab[*n].name[0]) (*n)++;
        return;
    }
    if (str_eq(key, "shot") && port.n_shot < N_SHOTS) {
        struct shot *x = &port.shot[port.n_shot];
        x->mask = number(&s, &ok);
        rest(s, x->name, sizeof x->name);
        if (ok && x->mask && x->name[0]) port.n_shot++;
        return;
    }
    if (str_eq(key, "switch")) {         /* `switch <id> <mask> <name>`: the switch map, and a named shot */
        struct shot sh;
        unsigned id = (unsigned)number(&s, &ok);
        int i, known = 0;
        if (!ok) return;
        sh.mask = number(&s, &ok);
        rest(s, sh.name, sizeof sh.name);
        if (!ok || !sh.mask || !sh.name[0] || id >= N_SWITCH_IDS) return;
        if (port.n_switch >= N_SWITCHES) { port.dropped++; return; }
        port.sw[port.n_switch].id = id;
        port.sw[port.n_switch].mask = sh.mask;
        port.n_switch++;
        for (i = 0; i < port.n_shot; i++) known |= str_eq(port.shot[i].name, sh.name);
        if (known) return;                                  /* a second switch for one named shot */
        if (port.n_shot >= N_SHOTS) { port.dropped++; return; }
        port.shot[port.n_shot++] = sh;
        return;
    }
    if ((str_eq(key, "scene") || str_eq(key, "text"))) {
        struct text *tab = str_eq(key, "scene") ? port.scene : port.text;
        int *n = str_eq(key, "scene") ? &port.n_scene : &port.n_text;
        int cap = str_eq(key, "scene") ? N_ROLES : N_TEXTS;
        if (*n >= cap) { port.dropped++; return; }
        s = word(s, name, sizeof name);
        str_copy(tab[*n].name, sizeof tab[*n].name, name, sizeof name);
        rest(s, tab[*n].value, sizeof tab[*n].value);
        if (tab[*n].name[0]) (*n)++;
        return;
    }
    if (str_eq(key, "event")) { event_line(s); return; }
    if (str_eq(key, "lamp")) { lamp_line(s); return; }
    if (str_eq(key, "rule")) { rule_line(s); return; }
    /* an unknown key is skipped: a newer port must not break an older runtime */
}

static void port_text_line(char *line)
{
    const char *s = line;
    while (*s == ' ' || *s == '\t') s++;
    if (*s && *s != '#') port_line(s);
}

/* The port, a chunk at a time: a line longer than 255 characters is cut, a port longer than
 * PORT_MAX is read to its last whole line before PORT_MAX (port.too_long says so). */
static int port_load(void)
{
    static char buf[PORT_CHUNK];
    char line[256];
    long n, i, j = 0, total = 0;
    unsigned k;
    int fd = -1;
    for (k = 0; k < sizeof PORT_FILES / sizeof PORT_FILES[0]; k++) {
        fd = open(PORT_FILES[k], O_RDONLY);
        if (fd >= 0) {
            str_copy(port.path, sizeof port.path, PORT_FILES[k], 40);
            break;
        }
    }
    if (fd < 0) return 0;
    while (total < PORT_MAX && (n = read(fd, buf, sizeof buf)) > 0) {
        if (n > PORT_MAX - total) n = PORT_MAX - total;
        total += n;
        for (i = 0; i < n; i++) {
            if (buf[i] == '\n') {
                line[j] = 0;
                port_text_line(line);
                j = 0;
            } else if (j + 1 < (long)sizeof line) {
                line[j++] = buf[i];
            }
        }
    }
    if (total >= PORT_MAX && read(fd, buf, 1) > 0) {
        port.too_long = 1;
        j = 0;                                   /* a line cut by the limit is not read */
    }
    close(fd);
    if (j) {                                     /* the last line, without a newline */
        line[j] = 0;
        port_text_line(line);
    }
    return total > 0;
}

static struct site *site(const char *name)
{
    int i;
    for (i = 0; i < port.n_site; i++)
        if (str_eq(port.site[i].name, name)) return &port.site[i];
    return 0;
}

/* a verified site's address, or 0 */
static unsigned fn(const char *name)
{
    struct site *x = site(name);
    return x && x->ok ? x->addr : 0;
}

static long named(const struct named *tab, int n, const char *name, long fallback)
{
    int i;
    for (i = 0; i < n; i++)
        if (str_eq(tab[i].name, name)) return tab[i].value;
    return fallback;
}

static unsigned data(const char *name) { return (unsigned)named(port.data, port.n_data, name, 0); }

long pm_port_value(const char *name, long fallback)
{
    return named(port.value, port.n_value, name, fallback);
}

const char *pm_port_text(const char *name)
{
    int i;
    for (i = 0; i < port.n_text; i++)
        if (str_eq(port.text[i].name, name)) return port.text[i].value;
    return 0;
}

const char *pm_game(void) { return port.game; }
const char *pm_version(void) { return port.version; }
int pm_can(unsigned what) { return (can & what) == what; }

/* ---- rule 1: is this process the game? ----------------------------------------------
 * The machine's launcher and the emulator both pass the preload to every child the game
 * spawns (a shell, for instance), and those have nothing at the game's addresses.
 * Only a process with an executable mapping named ...game covering the tick is it.
 *
 * The process's mappings are read from /proc/self/maps ONCE, at the gate, and every address
 * the gate reads is checked against them first: a port for another game names addresses that
 * may not be mapped in this one (godzilla_le-1.16.port's resource_get 0x538484 falls in The
 * Beatles 1.29's hole between its code and its data), and reading one killed the game at boot. */
#define N_MAPS   1024          /* mappings kept (the game has a few hundred; a trampoline's may be any of them) */
#define MAP_R    1u
#define MAP_X    2u
#define MAP_GAME 4u              /* the line names ...game: the game's own program */
static struct { unsigned long lo, hi; unsigned how; } maps[N_MAPS];
static int n_maps;

/* one line of /proc/self/maps: "lo-hi perms offset dev inode path" (tests lift it verbatim) */
static void maps_line(const char *s, const char *e)
{
    unsigned long lo = 0, hi = 0;
    const char *q = s, *p;
    unsigned how = 0;
    int d;
    if (n_maps >= N_MAPS) return;
    for (; q < e && (d = hexval(*q)) >= 0; q++) lo = lo * 16 + (unsigned)d;
    if (q >= e || *q != '-') return;
    for (q++; q < e && (d = hexval(*q)) >= 0; q++) hi = hi * 16 + (unsigned)d;
    if (q + 4 > e || q[0] != ' ' || hi <= lo) return;
    if (q[1] == 'r') how |= MAP_R;
    if (q[3] == 'x') how |= MAP_X;
    for (p = q; p + 4 <= e; p++)
        if (p[0] == 'g' && p[1] == 'a' && p[2] == 'm' && p[3] == 'e') { how |= MAP_GAME; break; }
    maps[n_maps].lo = lo;
    maps[n_maps].hi = hi;
    maps[n_maps].how = how;
    n_maps++;
}

/* the whole file, a chunk at a time (a game with many libraries has a long one) */
static void maps_read(void)
{
    static char buf[4096];
    char line[512];
    long n, i, j = 0;
    int fd = open("/proc/self/maps", O_RDONLY);
    n_maps = 0;
    if (fd < 0) return;
    while ((n = read(fd, buf, sizeof buf)) > 0)
        for (i = 0; i < n; i++) {
            if (buf[i] == '\n') { maps_line(line, line + j); j = 0; }
            else if (j < (long)sizeof line) line[j++] = buf[i];      /* a longer path is cut */
        }
    close(fd);
    if (j) maps_line(line, line + j);
}

/* 1 when [addr, addr + len) lies inside mappings with every bit of `how`: one mapping, or a run of
 * CONTIGUOUS ones (another preloaded object's mprotect of a page for its trampoline splits the game's
 * code mapping in three, and a site's 8 bytes may cross the split), each with every bit (tests lift it
 * verbatim) */
static int maps_has(unsigned long addr, unsigned long len, unsigned how)
{
    unsigned long at = addr, end = addr + len;
    int i, steps;
    if (end < addr) return 0;
    for (steps = 0; steps <= n_maps; steps++) {
        for (i = 0; i < n_maps; i++)
            if (maps[i].lo <= at && at < maps[i].hi) break;
        if (i == n_maps || (maps[i].how & how) != how) return 0;
        if (end <= maps[i].hi) return 1;
        at = maps[i].hi;                         /* the rest must start where this mapping ends */
    }
    return 0;
}

static int is_game_process(unsigned addr)
{
    return maps_has(addr, 8, MAP_R | MAP_X | MAP_GAME);
}

/* ---- rule 2: the words, followed through another preloaded object's trampoline --------
 * Called only for a site inside the game's code (site_check); a hook jump's target is read only
 * when it is mapped readable too. */
static int words_match(struct site *x)
{
    const unsigned *p = (const unsigned *)(unsigned long)x->addr;
    int depth;
    for (depth = 0; depth < 4; depth++) {
        if (p[0] == x->w0 && p[1] == x->w1) return 1;
        if (p[0] != 0xe51ff004u) break;              /* not a hook jump */
        if (!maps_has((unsigned long)p[1], 64, MAP_R)) break;   /* its target: a trampoline's 16 words */
        p = (const unsigned *)(unsigned long)p[1];
        if (p[0] != 0xe92d500fu) break;              /* not a trampoline of this shape */
        if (p[14] == x->w0 && p[15] == x->w1) return 1;   /* the words it moved, as they were */
        p += 6;                                      /* what it relocated */
    }
    return 0;
}

/* ---- the trampoline --------------------------------------------------------------------- */
typedef void (*hook_fn)(unsigned *regs);      /* r0..r3, ip, lr, then stack arguments */
#define TRAMP_WORDS 4096                /* PAD-363: 256 hooks (a title's mode starts take up to ~60) */
static unsigned tramp[TRAMP_WORDS] __attribute__((aligned(4096)));
static int tramp_used;

/* A literal load `ldr rd, [pc, #+-imm]` (rd not pc) among the two moved words: copy the
 * literal into t[12 + i] and load it from there, so a function that starts by loading a
 * table address can be hooked too (TMNT Pro's end-of-ball broadcast does, item 137). */
static void relocate_literal(unsigned *t, int i, unsigned addr, unsigned w)
{
    unsigned imm, at;
    if ((w & 0xFF7F0000u) != 0xE51F0000u || ((w >> 12) & 0xF) == 15) return;
    imm = w & 0xFFF;
    at = addr + (unsigned)i * 4 + 8;
    at = (w & 0x00800000u) ? at + imm : at - imm;
    t[12 + i] = *(const unsigned *)(unsigned long)at;
    t[6 + i] = 0xE59F0010u | (w & 0xF000u);          /* ldr rd, [pc, #16] -> t[12 + i] */
}

static int hook(unsigned addr, hook_fn logger)
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t;
    int i;
    if (!addr || (tramp_used + 1) * 16 > TRAMP_WORDS) return 0;
    t = tramp + tramp_used++ * 16;
    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;   /* mov r0, sp */
    t[2] = 0xe1a00000u;   /* nop */
    t[3] = 0xe59fc014u;   /* ldr ip, [pc, #20] -> t[10] */
    t[4] = 0xe12fff3cu;   /* blx ip */
    t[5] = 0xe8bd500fu;   /* pop {r0,r1,r2,r3,ip,lr} */
    t[6] = p[0];          /* the original two words (or a sibling's jump + literal) */
    t[7] = p[1];
    t[8] = 0xe59ff004u;   /* ldr pc, [pc, #4] -> t[11] */
    t[9] = 0u;
    t[10] = (unsigned)(unsigned long)logger;
    t[11] = addr + 8u;
    t[14] = p[0];         /* kept as they were, for words_match() in another object */
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

/* ---- a veto hook: the logger decides whether the function runs at all ----------------------
 * The trampoline above, with one more step. The logger gets the same saved registers and
 * returns non-zero to REFUSE: the function is not entered and its caller gets r0 = 1 (what the
 * game's message builders return for "failed"). Zero, and the original two words run and the
 * function continues, with the caller's stack as it was - so a function that takes stack
 * arguments is hooked as well. Sixteen words:
 *   0 push {r0-r3,ip,lr}   1 mov r0,sp   2 nop   3 ldr ip,[pc,#32] -> t[13]   4 blx ip
 *   5 cmp r0,#0   6 pop {r0-r3,ip,lr}   7 movne r0,#1   8 bxne lr   9,10 the original words
 *   11 ldr pc,[pc,#4] -> t[14]   12 -   13 the logger   14 addr+8   15 -
 * A literal load among the two words is not moved here (this refuses it): the sites that take a
 * veto (the Insider Connected gate's) start with plain register instructions, and the port
 * tools refuse pc-relative words for a hooked site. words_match() in ANOTHER object does not
 * follow this shape (it reads t[14] and t[15] as the moved words), and no other object hooks
 * these sites. (tests read the constants) */
typedef int (*veto_fn)(unsigned *regs);
static int hook_veto(unsigned addr, veto_fn logger)
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t;
    if (!addr || (tramp_used + 1) * 16 > TRAMP_WORDS) return 0;
    if ((p[0] & 0x0F7F0000u) == 0x051F0000u || (p[1] & 0x0F7F0000u) == 0x051F0000u) return 0;
    t = tramp + tramp_used++ * 16;
    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;   /* mov r0, sp */
    t[2] = 0xe1a00000u;   /* nop */
    t[3] = 0xe59fc020u;   /* ldr ip, [pc, #32] -> t[13] */
    t[4] = 0xe12fff3cu;   /* blx ip */
    t[5] = 0xe3500000u;   /* cmp r0, #0 */
    t[6] = 0xe8bd500fu;   /* pop {r0,r1,r2,r3,ip,lr}: the flags survive a pop */
    t[7] = 0x13a00001u;   /* movne r0, #1 */
    t[8] = 0x112fff1eu;   /* bxne lr */
    t[9] = p[0];          /* the original two words */
    t[10] = p[1];
    t[11] = 0xe59ff004u;  /* ldr pc, [pc, #4] -> t[14] */
    t[12] = 0u;
    t[13] = (unsigned)(unsigned long)logger;
    t[14] = addr + 8u;
    t[15] = 0u;
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;   /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* PAD-363: a veto whose logger is also told WHICH hook fired (r1 = n, 0-255): the spare nop at t[2] becomes
 * `mov r1, #n`, so one logger serves many starts that carry no object to tell them apart (a plain-C title's) */
typedef int (*veto_n_fn)(unsigned *regs, unsigned n);
static int hook_veto_bl(unsigned addr, veto_n_fn logger, unsigned n, unsigned refused);
static int hook_veto_n(unsigned addr, veto_n_fn logger, unsigned n, unsigned refused)
{
    unsigned *t;
    if (n > 255 || refused > 1) return 0;
    if ((((unsigned *)(unsigned long)addr)[1] & 0xFF000000u) == 0xEB000000u)   /* `push {.., lr}; bl check` */
        return hook_veto_bl(addr, logger, n, refused);
    if (!hook_veto(addr, (veto_fn)(void (*)(void))logger)) return 0;
    t = tramp + (tramp_used - 1) * 16;
    t[2] = 0xe3a01000u | n;   /* mov r1, #n */
    t[7] = 0x13a00000u | refused;   /* movne r0, #refused: what a refused call returns (1 unless the port says 0) */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    return 1;
}

/* PAD-363: the commonest start a plain veto cannot take opens `push {.., lr}; bl <check>` (Star Wars ELG's shot
 * modes, Jurassic Park The Pin's dinosaurs): the bl reaches only 32 MB, so it cannot run from the trampoline
 * as it is. This one, two slots long, calls the bl's target itself and comes back:
 *   0 push {r0-r3,ip,lr}  1 mov r0,sp  2 mov r1,#n  3 ldr ip,[pc,#64] -> t[21]  4 blx ip  5 cmp r0,#0
 *   6 pop {r0-r3,ip,lr}  7 movne r0,#refused  8 bxne lr  9 the push (the first word)
 *   10 add lr,pc,#0 (lr = t[12])  11 ldr pc,[pc,#28] -> t[20] (the bl's target)  12 ldr pc,[pc,#32] -> t[22] (addr+8)
 *   20 the target  21 the logger  22 addr + 8
 * The first word must save lr (the function returns through what it pushed); anything else is refused. */
static int hook_veto_bl(unsigned addr, veto_n_fn logger, unsigned n, unsigned refused)
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t, w1, target;
    int i;
    if (!addr || (tramp_used + 2) * 16 > TRAMP_WORDS) return 0;
    if ((p[0] & 0xFFFF4000u) != 0xE92D4000u) return 0;                 /* push {.., lr} */
    w1 = p[1];
    target = addr + 4 + 8 + (unsigned)(((int)(w1 << 8)) >> 6);         /* the bl's own offset, from its pc */
    t = tramp + tramp_used * 16;
    tramp_used += 2;
    for (i = 0; i < 32; i++) t[i] = 0;
    t[0] = 0xe92d500fu;                       /* push {r0,r1,r2,r3,ip,lr} */
    t[1] = 0xe1a0000du;                       /* mov r0, sp */
    t[2] = 0xe3a01000u | n;                   /* mov r1, #n */
    t[3] = 0xe59fc040u;                       /* ldr ip, [pc, #64] -> t[21] */
    t[4] = 0xe12fff3cu;                       /* blx ip */
    t[5] = 0xe3500000u;                       /* cmp r0, #0 */
    t[6] = 0xe8bd500fu;                       /* pop {r0,r1,r2,r3,ip,lr} */
    t[7] = 0x13a00000u | refused;             /* movne r0, #refused */
    t[8] = 0x112fff1eu;                       /* bxne lr */
    t[9] = p[0];                              /* the push, as it was */
    t[10] = 0xe28fe000u;                      /* add lr, pc, #0: lr = t[12] */
    t[11] = 0xe59ff01cu;                      /* ldr pc, [pc, #28] -> t[20]: the bl's target */
    t[12] = 0xe59ff020u;                      /* ldr pc, [pc, #32] -> t[22]: the function's third word */
    t[20] = target;
    t[21] = (unsigned)(unsigned long)logger;
    t[22] = addr + 8u;
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;                       /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 32));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* ---- the game, right now ------------------------------------------------------------- */
unsigned pm_player(void)
{
    unsigned p = *(unsigned char *)(unsigned long)data("cur_player");
    return p >= 1 && p <= 4 ? p : 0;
}

int pm_in_game(void)
{
    unsigned busy = (unsigned)pm_port_value("mode_mask_busy", 0);
    unsigned mask = data("mode_mask") ? *(unsigned short *)(unsigned long)data("mode_mask") : 0;
    return pm_player() != 0 && (mask & busy) == 0;
}

/* A title with 32-bit scores (The Beatles 1.29: score_add(u8 player, u32 points) -> u32, the scores
 * u32[4]) names its entries `site score_add32` and `data scores32`. The names carry the calling
 * convention, so a runtime without this code finds no `score_add` / `scores` - core entries - and
 * refuses the port (NOT THIS GAME'S PORT) instead of passing 64-bit points into a 32-bit function. */
uint64_t pm_score(unsigned player)
{
    unsigned s32 = data("scores32"), s64 = data("scores");
    if (player < 1 || player > 4) return 0;
    if (s32) return ((const unsigned *)(unsigned long)s32)[player - 1];
    if (!s64) return 0;
    return ((uint64_t *)(unsigned long)s64)[player - 1];
}

/* The 32-bit score_add multiplies the points by the playfield multiplier (a byte: the port's
 * optional `data score_mult`) and adds them into the u32 score with no carry check, so an award
 * past what is left below 4,294,967,295 would wrap the player's score to a small number. The
 * points are cut to that room, divided by the multiplier (taken as 1 when the port names none).
 * (tests lift it verbatim) */
static unsigned score32_points(unsigned player, uint64_t points)
{
    unsigned s32 = data("scores32"), at = data("score_mult"), mult = 1;
    uint64_t room;
    if (!s32 || player < 1 || player > 4) return 0;
    room = 0xffffffffull - ((const unsigned *)(unsigned long)s32)[player - 1];
    if (at && maps_has(at, 1, MAP_R)) mult = *(const unsigned char *)(unsigned long)at;
    if (mult > 1) room /= mult;
    return (unsigned)(points < room ? points : room);
}

uint64_t pm_score_add(unsigned player, uint64_t points)
{
    unsigned f32 = fn("score_add32"), f = fn("score_add"), n;
    if (player < 1 || player > 4) return 0;
    if (f32) {
        n = score32_points(player, points);
        return n ? ((unsigned (*)(unsigned, unsigned))(unsigned long)f32)(player, n) : 0;
    }
    if (!f) return 0;
    return ((uint64_t (*)(unsigned, uint64_t))(unsigned long)f)(player, points);
}

/* PAD-314: a loss goes straight into the score table, never below 0, then the game's add is
 * called with 0 points so its own on-change work (the score on the display) runs. The two's
 * complement through score_add would be exact too, but the add multiplies by the playfield
 * multiplier, which a 64-bit port does not name: a loss equal to the score would pass 0. */
uint64_t pm_score_sub(unsigned player, uint64_t points)
{
    unsigned s32 = data("scores32"), s64 = data("scores"), f32 = fn("score_add32"), f = fn("score_add");
    uint64_t have = pm_score(player), take = points < have ? points : have;
    if (player < 1 || player > 4 || !take) return 0;
    if (s32) {                           /* the table pm_score reads: the game's own RW data */
        if (!maps_has(s32, 16, MAP_R)) return 0;
        ((unsigned *)(unsigned long)s32)[player - 1] = (unsigned)(have - take);
        if (f32) ((unsigned (*)(unsigned, unsigned))(unsigned long)f32)(player, 0);
        return take;
    }
    if (!s64 || !maps_has(s64, 32, MAP_R)) return 0;
    ((uint64_t *)(unsigned long)s64)[player - 1] = have - take;
    if (f) ((uint64_t (*)(unsigned, uint64_t))(unsigned long)f)(player, 0);
    return take;
}

/* ---- shots ------------------------------------------------------------------------------- */
uint64_t pm_shot(const char *name)
{
    int i;
    for (i = 0; i < port.n_shot; i++)
        if (str_eq(port.shot[i].name, name)) return port.shot[i].mask;
    return 0;
}

const char *pm_shot_name(uint64_t shot)
{
    int i;
    for (i = 0; i < port.n_shot; i++)
        if (shot & port.shot[i].mask) return port.shot[i].name;
    return 0;
}

int pm_shot_count(void) { return port.n_shot; }

const char *pm_shot_at(int i, uint64_t *mask)
{
    if (i < 0 || i >= port.n_shot) return 0;
    if (mask) *mask = port.shot[i].mask;
    return port.shot[i].name;
}

/* ---- one mode at a time ---------------------------------------------------------------- */
static const struct pm_mode *running;
static char running_as[40];      /* PAD-363: pm_running_name - the running mode's own name ("" = its .name) */
static void disp_linger_other_began(void);

/* the name the runtime's lines give mode m: what pm_running_name said while it runs, else its .name */
static const char *mode_name(const struct pm_mode *m, const char *none)
{
    if (m && m == running && running_as[0]) return running_as;
    return m && m->name ? m->name : none;
}

int pm_begin(void)
{
    if (running && running != current) {
        pm_log("not started: %s is running", mode_name(running, "another mode"));
        return 0;
    }
    if (running != current) running_as[0] = 0;
    running = current;
    disp_linger_other_began();
    return 1;
}

/* PAD-363: one mode object that runs several modes (mode_file.c: every mode file) names the one it began, so
 * the runtime's own lines ("block: ... - BLOCKTEST is running") say which. Only while it runs; pm_end forgets. */
void pm_running_name(const char *name)
{
    if (!running || running != current) return;
    pm_snprintf(running_as, sizeof running_as, "%s", name ? name : "");
}

static void bd_reset(const char *why);
static void magnet_let_go(const char *why);   /* PAD-381: the magnet section */
static void scoop_let_go(void);               /* PAD-381: the scoop section */
void pm_end(void)
{
    if (running == current) running = 0, running_as[0] = 0;
    if (!running) bd_reset("the mode ended");
    if (!running) magnet_let_go("the mode ended");
    if (!running) scoop_let_go();
}
int pm_running(void) { return running && running == current; }

/* ---- sound ---------------------------------------------------------------------------------- */
unsigned pm_callout_id(const char *role)
{
    return (unsigned)named(port.callout, port.n_callout, role, 0);
}

void pm_callout(unsigned id)
{
    unsigned f = fn("callout");
    if (f && id) ((void (*)(unsigned))(unsigned long)f)(id);
}

void pm_callout_nth(unsigned id, unsigned n)
{
    unsigned f = fn("callout_nth");
    /* item 163: a title whose countdown list opens with something else names the clip "one" is
     * in (Iron Maiden 1.16's request 351: a sting, then "One." .. "Five"): `value countdown_first 1`.
     * A title that says each number with a request of its own names the "one" request and the id
     * step to the next number (Star Wars ELG 1.10: 168 "One!" .. 164 "Five!"): `value
     * countdown_step -1`. A title whose request holds every number in several voices, number by
     * number, names the stride between numbers (Deadpool LE 1.14's 962: "ten" x5, "one" x5, "two"
     * x5 ..: `value countdown_first 5`, `value countdown_stride 5`). Every countdown caller asks
     * for clip seconds - 1 of the countdown role and gets the number. */
    if (id && id == pm_callout_id("countdown")) {
        long step = pm_port_value("countdown_step", 0), stride = pm_port_value("countdown_stride", 1);
        n = n * (unsigned)(stride > 0 ? stride : 1) + (unsigned)pm_port_value("countdown_first", 0);
        if (step) {
            pm_callout((unsigned)((long)id + (long)n * step));
            return;
        }
    }
    if (f && id) ((void (*)(unsigned, unsigned))(unsigned long)f)(id, n);
}

/* Sound requests straight to the game's sound code (item 150): sound_request_play,
 * sound_request_active and sound_request_stop. No PM_CAN_ bit: each is 0 when its site is
 * absent or does not match. The play call takes no city variant, unlike pm_callout. */
static void sound_fade_finish(unsigned request);   /* item 150 follow-up, below */

int pm_sound(unsigned request)
{
    unsigned f = fn("sound_play");
    if (!f || !request) return 0;
    sound_fade_finish(request);      /* a fade still running on this request ends first */
    ((int (*)(unsigned))(unsigned long)f)(request);
    return 1;
}

int pm_sound_active(unsigned request)
{
    unsigned f = fn("sound_active");
    return f && request ? ((int (*)(unsigned))(unsigned long)f)(request) != 0 : 0;
}

int pm_sound_stop(unsigned request)
{
    unsigned f = fn("sound_stop");
    return f && request ? ((int (*)(unsigned))(unsigned long)f)(request) != 0 : 0;
}

/* A request record is 20 bytes: three pointers (the sid list at +8), then +16 priority and
 * +17 flags, both copied into the channel when it plays (the worker, item 150). The table is
 * `data sound_requests`, the number of requests the u32 at `data sound_request_count`. */
int pm_sound_priority(unsigned request, int priority, int flags)
{
    unsigned table = data("sound_requests"), count = data("sound_request_count");
    unsigned char *rec;
    int old;
    if (!table || !count || !request || request >= *(unsigned *)(unsigned long)count) return -1;
    rec = (unsigned char *)(unsigned long)(table + request * 20);
    if (!*(unsigned *)(rec + 8) || rec[16] > 9 || rec[19] != 0) return -1;
    old = rec[16] << 8 | rec[17];
    if (priority >= 0) rec[16] = (unsigned char)priority;
    if (flags >= 0) rec[17] = (unsigned char)flags;
    return old;
}

/* ---- item 150 follow-up: a request pointed at one sound id, fades, the channels now -------
 * The play worker reads a request's sid list (the pointer at +8 of its record) at every play,
 * so pointing it at a one-sid list of ours makes the request play that sound: one music carrier
 * plays a different bed for every mode (each bed a sid the build bound to an appended record,
 * a sid no request names). The request's own list is kept and put back with sid 0. */
#define SID_SLOTS 8
static struct { unsigned request, orig; unsigned list[2]; } sid_slot[SID_SLOTS];

int pm_sound_sid(unsigned request, unsigned sid)
{
    unsigned table = data("sound_requests"), count = data("sound_request_count");
    unsigned char *rec;
    int i, free_i = -1;
    if (!table || !count || !request || request >= *(unsigned *)(unsigned long)count) return 0;
    rec = (unsigned char *)(unsigned long)(table + request * 20);
    for (i = 0; i < SID_SLOTS; i++) {
        if (sid_slot[i].request == request) break;
        if (!sid_slot[i].request && free_i < 0) free_i = i;
    }
    if (!sid) {                                      /* put the request's own list back */
        if (i < SID_SLOTS) {
            *(unsigned *)(rec + 8) = sid_slot[i].orig;
            sid_slot[i].request = 0;
        }
        return 1;
    }
    if (i == SID_SLOTS) {
        if (!*(unsigned *)(rec + 8) || rec[16] > 9 || rec[19] != 0 || free_i < 0) return 0;
        i = free_i;
        sid_slot[i].request = request;
        sid_slot[i].orig = *(unsigned *)(rec + 8);
    }
    sid_slot[i].list[0] = sid;
    sid_slot[i].list[1] = 0;
    *(unsigned *)(rec + 8) = (unsigned)(unsigned long)sid_slot[i].list;
    return 1;
}

/* The engine's channel table (`data sound_channels`, `value sound_channel_*` offsets): a channel
 * plays while its voice bits are set; each set bit names a voice whose u16 volume step (1/3 dB
 * each, 0 = full, 255 = -86 dB, the codec's own table) the codec reads for every block. */
static unsigned char *sound_channel(int i)
{
    unsigned base = data("sound_channels");
    long size = pm_port_value("sound_channel_size", 0), n = pm_port_value("sound_channel_count", 8);
    if (!base || size <= 0 || i < 0 || i >= n) return 0;
    return (unsigned char *)(unsigned long)(base + (unsigned)i * (unsigned)size);
}

int pm_sound_playing(unsigned *requests, unsigned *buses, int max)
{
    long o_req = pm_port_value("sound_channel_request", -1), o_voices = pm_port_value("sound_channel_voices", -1),
         o_bus = pm_port_value("sound_channel_bus", -1), n_ch = pm_port_value("sound_channel_count", 8);
    int i, n = 0;
    if (!sound_channel(0) || o_req < 0 || o_voices < 0 || o_bus < 0) return -1;
    for (i = 0; i < n_ch; i++) {
        unsigned char *c = sound_channel(i);
        if (!c || !c[o_voices]) continue;
        if (n < max) {
            if (requests) requests[n] = *(unsigned short *)(c + o_req);
            if (buses) buses[n] = c[o_bus];
        }
        n++;
    }
    return n;
}

#define FADES_MAX 8
static struct { unsigned request; unsigned long t0, ms; int from; } fades[FADES_MAX];

/* Every voice of every channel playing `request`: set its volume step to at least `step`, or,
 * with step < 0, return the first voice's step (-1 when none plays or the port has no offsets). */
static int fade_voices(unsigned request, int step)
{
    long o_req = pm_port_value("sound_channel_request", -1), o_voices = pm_port_value("sound_channel_voices", -1),
         o_vp = pm_port_value("sound_channel_voice_ptrs", -1), o_vol = pm_port_value("sound_voice_volume", -1),
         n_ch = pm_port_value("sound_channel_count", 8);
    int i, b, first = -1;
    if (!sound_channel(0) || o_req < 0 || o_voices < 0 || o_vp < 0 || o_vol < 0) return -1;
    for (i = 0; i < n_ch; i++) {
        unsigned char *c = sound_channel(i);
        unsigned bits;
        if (!c || !(bits = c[o_voices]) || *(unsigned short *)(c + o_req) != request) continue;
        for (b = 0; b < 8; b++) {
            unsigned char *v;
            unsigned short *vol;
            if (!(bits >> b & 1u)) continue;
            v = (unsigned char *)(unsigned long)*(unsigned *)(c + o_vp + 4 * b);
            if (!v) continue;
            vol = (unsigned short *)(v + o_vol);
            if (first < 0) first = *vol;
            if (step >= 0 && *vol < (unsigned)step) *vol = (unsigned short)step;
        }
    }
    return first;
}

int pm_sound_fade(unsigned request, unsigned ms)
{
    int i, free_i = -1, from;
    if (!request || !pm_sound_active(request)) return 0;
    from = fade_voices(request, -1);
    if (from < 0 || !ms) {                       /* no voice offsets in the port: a plain stop */
        pm_sound_stop(request);
        return 1;
    }
    for (i = 0; i < FADES_MAX; i++) {
        if (fades[i].request == request) { free_i = i; break; }
        if (!fades[i].request && free_i < 0) free_i = i;
    }
    if (free_i < 0) {
        pm_sound_stop(request);
        return 1;
    }
    fades[free_i].request = request;
    fades[free_i].t0 = pm_ms();
    fades[free_i].ms = ms;
    fades[free_i].from = from > 255 ? 255 : from;
    return 1;
}

static void sound_fade_finish(unsigned request)
{
    int i;
    for (i = 0; i < FADES_MAX; i++)
        if (fades[i].request && (!request || fades[i].request == request)) {
            pm_sound_stop(fades[i].request);
            fades[i].request = 0;
        }
}

/* every tick, before the modes': a fade is linear in dB (1/3 dB a step) down to -86 dB, and the
 * request is stopped at the end - in silence */
static void sound_fades_tick(void)
{
    unsigned long now = pm_ms(), el;
    int i, step;
    for (i = 0; i < FADES_MAX; i++) {
        if (!fades[i].request) continue;
        el = now - fades[i].t0;
        if (el >= fades[i].ms || !pm_sound_active(fades[i].request)) {
            pm_sound_stop(fades[i].request);
            fades[i].request = 0;
            continue;
        }
        step = fades[i].from + (int)((255 - fades[i].from) * el / fades[i].ms);
        fade_voices(fades[i].request, step);
    }
}

/* The play chain resolves a request to an 8-byte container key and looks it up (item 130);
 * while armed, the lookup hook points it at OUR key. A handoff between two threads that
 * fails closed: at worst one callout plays the stock sound. */
static volatile int sound_armed;
static const unsigned char *volatile sound_key;

int pm_callout_own_sound(unsigned carrier, const unsigned char key[8])
{
    if (!(can & PM_CAN_OWN_SOUND) || !carrier || !key) return 0;
    sound_key = key;
    sound_armed = 1;
    pm_callout(carrier);
    if (sound_armed) { sound_armed = 0; return 0; }    /* nothing looked anything up */
    return 1;
}

/* the sound log (soundlog.on): r0 = the request, r2 = 1 for a numbered variant (sound_census.c) */
static void on_sound_worker(unsigned *r)
{
    say("sound %u %u", r[0], r[2]);
}

/* ---- item 163: a carrier's STOCK key swapped for an appended record's key, for one play --------
 * pm_sound_swap makes every lookup of `stock` (the carrier's own record key) take `ours` instead
 * (a record the build appended and NO descriptor names, so nothing the game plays can reach it), and
 * gives `request` `priority` without the steal flag, until `ms` (+1/8 +1 s; 10 s when 0) have passed
 * - then the key and the priority/flags come back (a call again moves the time). Matching on the
 * key, not on "the next lookup", holds when the worker thread looks it up later, and holds for a
 * looping descriptor that looks its key up again at every loop. */
#define SWAPS_MAX 8
static struct { unsigned request; int old; unsigned long until; unsigned char stock[8], ours[8]; volatile int looked; } swaps[SWAPS_MAX];
static volatile int swaps_live;

int pm_sound_swap(unsigned request, const unsigned char stock[8], const unsigned char ours[8], int priority, unsigned ms)
{
    int i, free_i = -1, old;
    if (!(can & PM_CAN_OWN_SOUND) || !request || !stock || !ours) return 0;
    for (i = 0; i < SWAPS_MAX; i++) {
        if (swaps[i].request == request) { free_i = i; break; }
        if (!swaps[i].request && free_i < 0) free_i = i;
    }
    if (free_i < 0) return 0;
    old = pm_sound_priority(request, priority, 0);
    if (swaps[free_i].request != request) swaps[free_i].old = old;
    for (i = 0; i < 8; i++) {
        if (swaps[free_i].ours[i] != ours[i]) swaps[free_i].looked = 0;     /* another record: say it again */
        swaps[free_i].stock[i] = stock[i];
        swaps[free_i].ours[i] = ours[i];
    }
    swaps[free_i].until = pm_ms() + (ms ? ms + ms / 8 + 1000 : 10000);
    swaps[free_i].request = request;          /* last: the lookup hook reads it */
    swaps_live = 1;
    return 1;
}

static void sound_swaps_tick(void)
{
    unsigned long now = pm_ms();
    int i, live = 0;
    for (i = 0; i < SWAPS_MAX; i++) {
        unsigned r = swaps[i].request;
        if (!r) continue;
        /* the window only has to cover the lookup, at the start of the play (the channel took the
         * priority then too): no "while it still sounds" - on Munsters 1.28 the carrier read as
         * active long after its record, and the swap outlived the call (item 163). The music
         * re-arms its swap on every poll while the mode runs. */
        if (now < swaps[i].until) {
            live = 1;
            continue;
        }
        swaps[i].request = 0;
        if (swaps[i].old >= 0) pm_sound_priority(r, swaps[i].old >> 8, swaps[i].old & 0xff);
    }
    swaps_live = live;
}

static int key_is(const unsigned char *a, const unsigned char *b)
{
    int i;
    for (i = 0; i < 8; i++) if (a[i] != b[i]) return 0;
    return 1;
}

static void on_sound_lookup(unsigned *r)
{
    if (swaps_live && r[1]) {
        const unsigned char *k = (const unsigned char *)(unsigned long)r[1];
        int i;
        for (i = 0; i < SWAPS_MAX; i++)
            if (swaps[i].request && key_is(k, swaps[i].stock)) {
                r[1] = (unsigned)(unsigned long)swaps[i].ours;
                if (!swaps[i].looked) {         /* once per record armed: the proof it was the one played */
                    swaps[i].looked = 1;
                    say("sound swap: request %u looked up %02x%02x%02x%02x%02x%02x%02x%02x, took "
                        "%02x%02x%02x%02x%02x%02x%02x%02x", swaps[i].request,
                        swaps[i].stock[0], swaps[i].stock[1], swaps[i].stock[2], swaps[i].stock[3],
                        swaps[i].stock[4], swaps[i].stock[5], swaps[i].stock[6], swaps[i].stock[7],
                        swaps[i].ours[0], swaps[i].ours[1], swaps[i].ours[2], swaps[i].ours[3],
                        swaps[i].ours[4], swaps[i].ours[5], swaps[i].ours[6], swaps[i].ours[7]);
                }
                return;
            }
    }
    if (!sound_armed || !sound_key) return;
    sound_armed = 0;
    r[1] = (unsigned)(unsigned long)sound_key;
}

/* ---- lights ------------------------------------------------------------------------------------
 * Everything the light system makes is tagged with the CURRENT event, which is null on
 * our tick. So a live show event is made current around the call, and one lamp group is
 * kept and reused (the pool is small). Proven: item 125, run 12. */
static unsigned char *live_show_event(void)
{
    unsigned char *n = *(unsigned char **)(unsigned long)data("event_head");
    long next = pm_port_value("event_next", 0), flags = pm_port_value("event_flags", 0);
    long show = pm_port_value("event_show_flag", 0), id = pm_port_value("event_show_id", 0);
    int guard = 64;
    while (n && guard-- > 0) {
        if ((*(unsigned short *)(n + flags) & (unsigned)show) && *(unsigned short *)(n + id)) return n;
        n = *(unsigned char **)(n + next);
    }
    return 0;
}

int pm_lights(const char *command)
{
    return pm_lights_as((unsigned)pm_port_value("light_owner", 0), command);
}

int pm_lights_as(unsigned owner, const char *command)
{
    static void *group;
    unsigned char *ev, *old = 0;
    unsigned prio = 0, cur = data("event_current");
    if (!(can & PM_CAN_LIGHTS) || !command || !*command || !owner) return 0;
    ev = live_show_event();
    if (ev) {
        old = *(unsigned char **)(unsigned long)cur;
        *(unsigned char **)(unsigned long)cur = ev;
        prio = ((unsigned (*)(void))(unsigned long)fn("show_priority"))();
    }
    if (!group)
        group = ((void *(*)(unsigned, unsigned, unsigned, unsigned))(unsigned long)fn("lamp_group"))
                (0u, prio & 0xffu, 0u, 0u);
    if (group)
        ((int (*)(unsigned, void *, const char *, unsigned))(unsigned long)fn("light_run"))
            (owner, group, command, 0u);
    if (ev) *(unsigned char **)(unsigned long)cur = old;
    /* Without a live show event the game parses the command and writes no lamp (item 125),
     * so only that case counts as done. */
    return ev && group;
}

/* ---- named inserts: a lamp layer of our own (MODE_SDK.md "Lights: named inserts") -- LAMPS BEGIN
 * Read off Godzilla Premium 1.16 and Pro 1.15 (item mode-leds). The game lights through LAYERS:
 * lamp groups of 48 bytes-ish records, each with a malloc'd array of one 40-byte SLOT per light
 * (group+0), a priority byte (+4), the event it belongs to (+16: a show's end frees every group of
 * its event) and the next group (+20). The allocator (behind `site lamp_group`) keeps the active
 * list sorted by priority, a new group going AFTER every group of equal or lower priority. Every
 * frame the compositor gives each light the global bank's value, then walks the list bottom to
 * top and, for every slot whose byte +3 is non-zero, overwrites the light's level with the slot's
 * +2 (and its fade time with +8). A slot with +3 == 0 covers nothing: the layers below show.
 * So a layer of ours at priority 255, created with no current event, sits on top of every show
 * and is never freed by a show's end; holding an insert is writing its lights' slots with +3 set,
 * and releasing it is clearing +3. Nothing of the game's is hooked or rewritten for this. */
#define N_LAMPS      256          /* item 164: Foo Fighters 1.04 names 235 inserts */
#define LAMP_LAYERS  4
#define LAMP_MODES   64
#define LAMP_SAY_MAX 400

struct lamp { char name[40]; unsigned light[3]; int mono; uint64_t shot; int x, y; };   /* x, y: -1 = not placed */
static struct lamp lamps[N_LAMPS];
static int n_lamps;

struct lamp_held {
    const struct pm_mode *owner;    /* 0 = the game has it */
    unsigned rgb, period;
    int pattern, layer;
    unsigned chase_i, chase_n;
    unsigned long t0;
    int last[3];                    /* the level last written to each light, -1 = rewrite */
    unsigned on_ms;                 /* a blink's ON time; 0 = half the period (item 160: a rule's 300/200 blink) */
};
static struct lamp_held lamp_held[N_LAMPS];
static unsigned lamp_hold_on_ms;    /* the on time the next hold takes (set around a call, runtime-internal) */
static struct { unsigned prio; unsigned char *group; unsigned misses; } lamp_layer[LAMP_LAYERS];
static int n_lamp_layers;
static struct { const struct pm_mode *mode; unsigned prio; } lamp_mode_prio[LAMP_MODES];
static int lamp_says;

static void lamp_say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void lamp_say(const char *fmt, ...)
{
    va_list ap;
    if (lamp_says >= LAMP_SAY_MAX) return;
    if (++lamp_says == LAMP_SAY_MAX) { say("lamps: that is %d lines; no more lamp lines this boot", LAMP_SAY_MAX); return; }
    va_start(ap, fmt);
    log_raw("pad", fmt, ap);
    va_end(ap);
}

/* `lamp <R,G,B light ids | one light id> <shot mask> <name>`: a 0 in the R,G,B list is a colour
 * the fixture does not have; ONE id is a single-colour insert (lit at the colour's brightest part) */
static void lamp_line(const char *s)
{
    struct lamp *x;
    int k, ok = 0, n = 0;
    unsigned i;
    if (n_lamps >= N_LAMPS) return;
    x = &lamps[n_lamps];
    x->light[0] = x->light[1] = x->light[2] = 0;
    for (k = 0; k < 3; k++) {
        x->light[k] = (unsigned)number(&s, &ok);
        if (!ok) return;
        n++;
        if (*s != ',') break;
        s++;
    }
    x->mono = n == 1;
    x->shot = number(&s, &ok);
    if (!ok) return;
    rest(s, x->name, sizeof x->name);
    x->x = x->y = -1;
    {   /* hud-layers: the comment's "at X,Y" (the insert's place on the playfield picture), when given */
        const char *c = s;
        for (; *c && *c != 10; c++)
            if (c[0] == 'a' && c[1] == 't' && c[2] == ' ' && c > s && c[-1] == ' ') {
                const char *q = c + 3;
                int ok1 = 0, ok2 = 0;
                long px = (long)number(&q, &ok1), py;
                if (*q == ',') { q++; py = (long)number(&q, &ok2); if (ok1 && ok2 && (px || py)) { x->x = (int)px; x->y = (int)py; } }
            }
    }
    for (i = 0; x->name[i]; i++)                          /* a trailing comment is not the name */
        if (x->name[i] == '#' && i && (x->name[i - 1] == ' ' || x->name[i - 1] == '\t')) {
            while (i && (x->name[i - 1] == ' ' || x->name[i - 1] == '\t')) i--;
            x->name[i] = 0;
            break;
        }
    if (x->name[0] && (x->light[0] || x->light[1] || x->light[2])) n_lamps++;
}

static int lamp_upper(int c) { return c >= 'a' && c <= 'z' ? c - 32 : c; }

/* `name` against the first `len` characters of `s`, case and surrounding spaces ignored */
static int lamp_name_is(const char *name, const char *s, unsigned len)
{
    while (len && (*s == ' ' || *s == '\t')) { s++; len--; }
    while (len && (s[len - 1] == ' ' || s[len - 1] == '\t')) len--;
    while (len && *name && lamp_upper(*name) == lamp_upper(*s)) { name++; s++; len--; }
    return !len && !*name;
}

static int lamp_index(const char *s, unsigned len)
{
    int i;
    for (i = 0; i < n_lamps; i++)
        if (lamp_name_is(lamps[i].name, s, len)) return i;
    return -1;
}

int pm_lamp_count(void) { return (can & PM_CAN_LAMPS) ? n_lamps : 0; }

const char *pm_lamp_at(int i, uint64_t *shots)
{
    if (!(can & PM_CAN_LAMPS) || i < 0 || i >= n_lamps) return 0;
    if (shots) *shots = lamps[i].shot;
    return lamps[i].name;
}

int pm_lamp_xy(int i, int *x, int *y)
{
    if (!(can & PM_CAN_LAMPS) || i < 0 || i >= n_lamps || lamps[i].x < 0) return 0;
    if (x) *x = lamps[i].x;
    if (y) *y = lamps[i].y;
    return 1;
}

int pm_lamp_find(const char *name)
{
    unsigned n = 0;
    if (!(can & PM_CAN_LAMPS) || !name) return -1;
    while (name[n]) n++;
    return lamp_index(name, n);
}

/* the slot of `light` in a group: group[0] + light * lamp_slot_size, bounded by the light count */
static unsigned char *lamp_slot(unsigned char *group, unsigned light)
{
    unsigned count = data("light_count"), n = count ? *(unsigned *)(unsigned long)count : 0, base;
    if (!group || !light || (n && light >= n)) return 0;
    base = *(unsigned *)group;
    return base ? (unsigned char *)(unsigned long)(base + light * (unsigned)pm_port_value("lamp_slot_size", 40)) : 0;
}

static void lamp_slot_put(unsigned char *group, unsigned light, int level, int hold)
{
    unsigned char *s = lamp_slot(group, light);
    if (!s) return;
    *(unsigned short *)s = (unsigned short)light;
    s[pm_port_value("lamp_slot_level", 2)] = (unsigned char)(hold ? level : 0);
    /* the fade time the game's own inserts carry (+8 of its in-play layers' slots: 3 on Premium 1.16, read
     * live): it rides to the node board with the level, so a held insert changes as the game's own do */
    s[pm_port_value("lamp_slot_fade", 8)] = (unsigned char)(hold ? pm_port_value("lamp_fade", 3) : 0);
    s[pm_port_value("lamp_slot_alpha", 3)] = (unsigned char)(hold ? 255 : 0);   /* last: the level is in place first */
    s[pm_port_value("lamp_slot_used", 36)] = 1;
}

/* A new group from the game's allocator at `prio`, with NO current event, so no show's end frees it. */
static unsigned char *lamp_group_new(unsigned prio)
{
    unsigned cur = data("event_current"), f = fn("lamp_group"), old = 0;
    unsigned long g;
    if (!f) return 0;
    if (cur) {
        old = *(unsigned *)(unsigned long)cur;
        *(unsigned *)(unsigned long)cur = 0;
    }
    g = ((unsigned long (*)(unsigned, unsigned, unsigned, unsigned))(unsigned long)f)(0u, prio & 0xffu, 0u, 0u);
    if (cur) *(unsigned *)(unsigned long)cur = old;
    return (unsigned char *)g;
}

/* the game's active layers, bottom to top: the list head is the word after the free list's */
static unsigned char *lamp_first_layer(void)
{
    unsigned heads = data("lamp_layers");
    return heads ? (unsigned char *)(unsigned long)*(unsigned *)(unsigned long)(heads + 4) : 0;
}

static unsigned char *lamp_next_layer(unsigned char *g)
{
    return (unsigned char *)(unsigned long)*(unsigned *)(g + pm_port_value("lamp_group_next", 20));
}

int pm_lamp_layers(unsigned *priorities, int max)
{
    unsigned char *g;
    int n = 0, guard = 64, k;
    if (!(can & PM_CAN_LAMPS)) return -1;
    for (g = lamp_first_layer(); g && guard-- > 0; g = lamp_next_layer(g)) {
        unsigned p = g[pm_port_value("lamp_group_prio", 4)];
        for (k = 0; k < n_lamp_layers; k++)
            if (lamp_layer[k].group == g) p |= 0x100u;
        if (priorities && n < max) priorities[n] = p;
        n++;
    }
    return n < max ? n : max;
}

static int lamp_layer_for(unsigned prio)
{
    int k;
    for (k = 0; k < n_lamp_layers; k++)
        if (lamp_layer[k].prio == prio) return k;
    if (n_lamp_layers >= LAMP_LAYERS) {
        lamp_say("lamps: no layer at priority %u (we hold %d already)", prio, LAMP_LAYERS);
        return -1;
    }
    lamp_layer[n_lamp_layers].group = lamp_group_new(prio);
    if (!lamp_layer[n_lamp_layers].group) {
        lamp_say("lamps: the game gave no lamp layer at priority %u", prio);
        return -1;
    }
    lamp_layer[n_lamp_layers].prio = prio;
    lamp_layer[n_lamp_layers].misses = 0;
    {
        unsigned p[24];
        char b[160];
        int n = pm_lamp_layers(p, 24), i, m = 0;
        for (i = 0; i < n && m < (int)sizeof b - 8; i++)
            m += pm_snprintf(b + m, sizeof b - (unsigned)m, "%s%u%s", i ? " " : "", p[i] & 0xffu, p[i] & 0x100u ? "*" : "");
        b[m] = 0;
        lamp_say("lamps: our layer at priority %u; the game's layers now, bottom to top (* ours): %s", prio, b);
    }
    return n_lamp_layers++;
}

static unsigned lamp_prio_of(const struct pm_mode *m)
{
    int i;
    for (i = 0; i < LAMP_MODES; i++)
        if (lamp_mode_prio[i].mode == m && lamp_mode_prio[i].prio) return lamp_mode_prio[i].prio;
    return 255;
}

static void lamp_write(int k, int level_r, int level_g, int level_b)
{
    struct lamp_held *h = &lamp_held[k];
    struct lamp *x = &lamps[k];
    int want[3], c;
    if (h->layer < 0) return;
    if (x->mono) {
        want[0] = level_r > level_g ? level_r : level_g;
        if (level_b > want[0]) want[0] = level_b;
        want[1] = want[2] = 0;
    } else {
        want[0] = level_r; want[1] = level_g; want[2] = level_b;
    }
    for (c = 0; c < 3; c++) {
        if (!x->light[c] || h->last[c] == want[c]) continue;
        lamp_slot_put(lamp_layer[h->layer].group, x->light[c], want[c], 1);
        h->last[c] = want[c];
    }
}

static void lamp_let_go(int k)
{
    struct lamp_held *h = &lamp_held[k];
    int c;
    if (!h->owner) return;
    if (h->layer >= 0)
        for (c = 0; c < 3; c++)
            if (lamps[k].light[c]) lamp_slot_put(lamp_layer[h->layer].group, lamps[k].light[c], 0, 0);
    h->owner = 0;
}

static const char *const lamp_pattern_name[] = { "solid", "blink", "pulse", "chase" };

/* hold the lamps in list[0..n) for the calling mode */
static int lamp_hold(const int *list, int n, unsigned rgb, int pattern, unsigned period_ms, const char *what)
{
    int j, layer;
    unsigned prio = lamp_prio_of(current);
    unsigned long now = pm_ms();
    if (!(can & PM_CAN_LAMPS) || n <= 0) return 0;
    if (pattern < PM_LAMP_SOLID || pattern > PM_LAMP_CHASE) pattern = PM_LAMP_SOLID;
    if (!period_ms) period_ms = pattern == PM_LAMP_BLINK ? 500u : pattern == PM_LAMP_PULSE ? 1600u : 150u;
    layer = lamp_layer_for(prio);
    if (layer < 0) return 0;
    for (j = 0; j < n; j++) {
        struct lamp_held *h = &lamp_held[list[j]];
        if (h->owner && h->owner != current)
            lamp_say("lamps: %s takes %s from %s", current && current->name ? current->name : "a mode", lamps[list[j]].name,
                     h->owner->name ? h->owner->name : "another mode");
        if (h->owner && h->layer != layer) lamp_let_go(list[j]);
        h->owner = current ? current : (const struct pm_mode *)&lamps;   /* a call from outside a callback */
        h->rgb = rgb;
        h->pattern = pattern;
        h->period = period_ms;
        h->t0 = now;
        h->chase_i = (unsigned)j;
        h->chase_n = (unsigned)n;
        h->layer = layer;
        h->last[0] = h->last[1] = h->last[2] = -1;
        h->on_ms = lamp_hold_on_ms < period_ms ? lamp_hold_on_ms : 0;
    }
    lamp_say("lamps: %d insert(s) held (%s): %06x %s, %u ms, layer %u", n, what, rgb & 0xffffffu,
             lamp_pattern_name[pattern], period_ms, prio);
    return n;
}

/* hud-layers: ONE insert held solid in `rgb`, quietly - a light show paints every insert every tick,
 * and only a level that changed reaches the game (lamp_write). 0 black is still held (dark). */
int pm_lamp_paint(int k, unsigned rgb)
{
    struct lamp_held *h;
    int layer;
    if (!(can & PM_CAN_LAMPS) || k < 0 || k >= n_lamps) return 0;
    h = &lamp_held[k];
    if (h->owner == (current ? current : (const struct pm_mode *)&lamps) && h->pattern == PM_LAMP_SOLID) {
        h->rgb = rgb;
        return 1;
    }
    layer = lamp_layer_for(lamp_prio_of(current));
    if (layer < 0) return 0;
    if (h->owner && h->layer != layer) lamp_let_go(k);
    h->owner = current ? current : (const struct pm_mode *)&lamps;
    h->rgb = rgb;
    h->pattern = PM_LAMP_SOLID;
    h->period = 150u;
    h->t0 = pm_ms();
    h->chase_i = 0;
    h->chase_n = 1;
    h->layer = layer;
    h->last[0] = h->last[1] = h->last[2] = -1;
    h->on_ms = 0;
    return 1;
}

/* the lamps a comma-separated list names, in its order; unknown names are said once */
static int lamp_list(const char *names, int *list, int cap)
{
    const char *s = names, *e;
    int n = 0, k, j;
    while (names && *s && n < cap) {
        for (e = s; *e && *e != ','; e++) ;
        k = lamp_index(s, (unsigned)(e - s));
        if (k < 0) {
            char b[48];
            unsigned i;
            for (i = 0; i + 1 < sizeof b && s + i < e; i++) b[i] = s[i];
            b[i] = 0;
            if ((unsigned)(e - s) > 0) lamp_say("lamps: \"%s\" is not an insert this game's port names", b);
        } else {
            for (j = 0; j < n && list[j] != k; j++) ;
            if (j == n) list[n++] = k;
        }
        s = *e ? e + 1 : e;
    }
    return n;
}

int pm_lamp_set(const char *names, unsigned rgb, int pattern, unsigned period_ms)
{
    int list[N_LAMPS], n;
    if (!(can & PM_CAN_LAMPS)) return 0;
    n = lamp_list(names, list, N_LAMPS);
    return lamp_hold(list, n, rgb, pattern, period_ms, names);
}

/* item 164: every insert the port names - a mode's Lights on a title without the light language
 * (the whole playfield in the mode's colour) */
int pm_lamp_all(unsigned rgb, int pattern, unsigned period_ms)
{
    int list[N_LAMPS], k;
    if (!(can & PM_CAN_LAMPS)) return 0;
    for (k = 0; k < n_lamps; k++) list[k] = k;
    return lamp_hold(list, n_lamps, rgb, pattern, period_ms, "every insert");
}

int pm_lamp_shot(uint64_t shots, unsigned rgb, int pattern, unsigned period_ms)
{
    int list[N_LAMPS], n = 0, k;
    char what[48];
    if (!(can & PM_CAN_LAMPS) || !shots) return 0;
    for (k = 0; k < n_lamps; k++)
        if (lamps[k].shot & shots) list[n++] = k;
    pm_snprintf(what, sizeof what, "shots %08x_%08x", (unsigned)(shots >> 32), (unsigned)shots);
    if (!n) lamp_say("lamps: no insert of %s in this game's port", what);
    return lamp_hold(list, n, rgb, pattern, period_ms, what);
}

static int lamp_release_list(const int *list, int n, const char *what)
{
    int j, r = 0;
    for (j = 0; j < n; j++) {
        struct lamp_held *h = &lamp_held[list[j]];
        if (!h->owner || (current && h->owner != current)) continue;
        lamp_let_go(list[j]);
        r++;
    }
    if (r) lamp_say("lamps: %d insert(s) handed back to the game (%s)", r, what);
    return r;
}

int pm_lamp_release(const char *names)
{
    int list[N_LAMPS], n;
    if (!(can & PM_CAN_LAMPS)) return 0;
    n = lamp_list(names, list, N_LAMPS);
    return lamp_release_list(list, n, names);
}

int pm_lamp_release_shot(uint64_t shots)
{
    int list[N_LAMPS], n = 0, k;
    if (!(can & PM_CAN_LAMPS) || !shots) return 0;
    for (k = 0; k < n_lamps; k++)
        if (lamps[k].shot & shots) list[n++] = k;
    return lamp_release_list(list, n, "a shot's inserts");
}

int pm_lamp_release_all(void)
{
    int list[N_LAMPS], n = 0, k;
    if (!(can & PM_CAN_LAMPS)) return 0;
    for (k = 0; k < n_lamps; k++)
        if (lamp_held[k].owner && (!current || lamp_held[k].owner == current)) list[n++] = k;
    return lamp_release_list(list, n, "all of the mode's");
}

int pm_lamp_priority(unsigned priority)
{
    int i, free_i = -1, k, layer;
    if (!(can & PM_CAN_LAMPS)) return 0;
    if (priority < 1) priority = 1;
    if (priority > 255) priority = 255;
    for (i = 0; i < LAMP_MODES; i++) {
        if (lamp_mode_prio[i].mode == current) break;
        if (!lamp_mode_prio[i].mode && free_i < 0) free_i = i;
    }
    if (i == LAMP_MODES) {
        if (free_i < 0) return (int)lamp_prio_of(current);
        i = free_i;
        lamp_mode_prio[i].mode = current;
    }
    if (lamp_mode_prio[i].prio == priority) return (int)priority;
    lamp_mode_prio[i].prio = priority;
    layer = -1;
    for (k = 0; k < n_lamps; k++) {
        struct lamp_held *h = &lamp_held[k];
        if (!h->owner || h->owner != current) continue;
        if (layer < 0 && (layer = lamp_layer_for(priority)) < 0) break;
        if (h->layer == layer) continue;
        {
            int c;
            for (c = 0; c < 3; c++)
                if (lamps[k].light[c]) lamp_slot_put(lamp_layer[h->layer].group, lamps[k].light[c], 0, 0);
        }
        h->layer = layer;
        h->last[0] = h->last[1] = h->last[2] = -1;
    }
    lamp_say("lamps: %s's layer is at priority %u", current && current->name ? current->name : "the mode", priority);
    return (int)priority;
}

/* 0..255 of the colour for lamp k now */
static int lamp_level(const struct lamp_held *h, unsigned long now)
{
    unsigned long el = now - h->t0, p = h->period ? h->period : 1, ph = el % p;
    unsigned tri;
    switch (h->pattern) {
    case PM_LAMP_BLINK: return ph < (h->on_ms ? h->on_ms : p / 2) ? 255 : 0;
    case PM_LAMP_PULSE:
        tri = (unsigned)(ph < p / 2 ? ph * 510 / p : (p - ph) * 510 / p);    /* 0..255..0 */
        if (tri > 255) tri = 255;
        return 40 + (int)(215u * tri * tri / (255u * 255u));                   /* eased, never quite dark */
    case PM_LAMP_CHASE: return h->chase_n && (el / p) % h->chase_n == h->chase_i ? 255 : 0;
    default: return 255;
    }
}

/* our layers are still in the game's list? A group we lost (a teardown freed it) is replaced. */
static void lamp_layers_check(void)
{
    int k, j, guard;
    unsigned char *g;
    for (k = 0; k < n_lamp_layers; k++) {
        for (g = lamp_first_layer(), guard = 64; g && guard-- > 0; g = lamp_next_layer(g))
            if (g == lamp_layer[k].group && g[pm_port_value("lamp_group_prio", 4)] == lamp_layer[k].prio) break;
        if (g && guard > 0) { lamp_layer[k].misses = 0; continue; }
        if (++lamp_layer[k].misses < 2) continue;         /* the list may have been moving under us */
        lamp_say("lamps: our layer at priority %u is gone from the game's list - a new one", lamp_layer[k].prio);
        lamp_layer[k].group = lamp_group_new(lamp_layer[k].prio);
        lamp_layer[k].misses = 0;
        for (j = 0; j < n_lamps; j++)
            if (lamp_held[j].owner && lamp_held[j].layer == k)
                lamp_held[j].last[0] = lamp_held[j].last[1] = lamp_held[j].last[2] = -1;
    }
}

static int lamps_checked(void);                 /* below: the lamp lines against the game's light count */

/* every tick: patterns, and the game over */
static void lamps_tick(void)
{
    static unsigned ticks;
    static int was_in;
    unsigned long now;
    int k, in, held = 0;
    if (!(can & PM_CAN_LAMPS) || !lamps_checked()) return;
    ticks++;
    in = pm_in_game();
    if (was_in && !in) {
        int n = 0;
        for (k = 0; k < n_lamps; k++)
            if (lamp_held[k].owner) { lamp_let_go(k); n++; }
        if (n) lamp_say("lamps: the game left play - %d insert(s) handed back", n);
    }
    was_in = in;
    for (k = 0; k < n_lamps && !held; k++) held = lamp_held[k].owner != 0;
    if (!held) return;
    if (ticks % 30 == 0) lamp_layers_check();
    now = pm_ms();
    for (k = 0; k < n_lamps; k++) {
        struct lamp_held *h = &lamp_held[k];
        int f;
        if (!h->owner) continue;
        if (ticks % 30 == 0) h->last[0] = h->last[1] = h->last[2] = -1;   /* re-asserted twice a second */
        f = lamp_level(h, now);
        lamp_write(k, (int)((h->rgb >> 16) & 255u) * f / 255, (int)((h->rgb >> 8) & 255u) * f / 255,
                   (int)(h->rgb & 255u) * f / 255);
    }
}

static int have_data(const char *const *names);         /* the capability checks, below */
static int have_values(const char *const *names);

static void lamps_arm(void)
{
    static const char *const lamp_v[] = { "lamp_slot_size", "lamp_slot_level", "lamp_slot_alpha", "lamp_slot_fade",
                                          "lamp_slot_used", "lamp_group_prio", "lamp_group_next", 0 };
    static const char *const lamp_d[] = { "lamp_layers", "light_count", 0 };
    int k, shots = 0;
    struct site *g = site("lamp_group");
    if (!n_lamps) return;
    if (!g || !g->ok || !have_data(lamp_d) || !have_values(lamp_v)) {
        say("lamps: %d named inserts, but the port lacks the lamp layer (lamp_group, lamp_layers, light_count, lamp_slot_*)", n_lamps);
        return;
    }
    for (k = 0; k < n_lamps; k++) {
        lamp_held[k].layer = -1;
        shots += lamps[k].shot != 0;
    }
    can |= PM_CAN_LAMPS;
    say("lamps: %d named inserts (%d tied to a shot); their light ids are checked once the game counts its lights",
        n_lamps, shots);
}

/* The game counts its lights only once its main() has run (0 at load, measured on Premium 1.16), so
 * the lamp lines are checked against it on the first tick it is there: 1 = fine (or not yet known). */
static int lamps_checked(void)
{
    static int done;
    unsigned count = data("light_count"), n;
    int k, c, bad = 0;
    if (done) return done > 0;
    n = count ? *(unsigned *)(unsigned long)count : 0;
    if (!n) return 1;
    for (k = 0; k < n_lamps; k++)
        for (c = 0; c < 3; c++)
            if (lamps[k].light[c] >= n) bad++;
    /* item 165: a FEW ids past the count are the light table's tail this build does not count (Batman 66's
     * static table has 186 records and the game counts 179: the last seven are lights the model lacks), so
     * only those lines are dropped and the rest hold; MANY past it are another build's lines, and none hold. */
    if (bad && bad * 4 > n_lamps * 3) {
        say("lamps: %d light id(s) are past this game's %u lights - the lamp lines are another build's; no lamps", bad, n);
        for (k = 0; k < n_lamps; k++) lamp_let_go(k);
        can &= ~PM_CAN_LAMPS;
        done = -1;
        return 0;
    }
    if (bad) {
        for (k = 0; k < n_lamps; k++)
            for (c = 0; c < 3; c++)
                if (lamps[k].light[c] >= n) lamps[k].light[c] = 0;     /* never written (lamp_write skips a 0) */
        say("lamps: the game counts %u lights; %d light id(s) past them are dropped, the other lamp lines hold", n, bad);
    } else {
        say("lamps: the game counts %u lights; every lamp line is within them", n);
    }
    done = 1;
    return 1;
}
/* ---- LAMPS END */

/* ---- the display ---------------------------------------------------------------------------
 * Scenes by id through the resource manager, then the TYPED node finder (it returns 0 for
 * a text node, so text has its own finder), shown through the node's own virtual, words
 * through the game's set-text. libstdc++ here is the COW ABI: a std::string is one
 * pointer. Strings and shared pointers are leaked on purpose (tens of bytes per call).
 * Proven: item 131. */
const char *pm_scene_id(const char *role)
{
    int i;
    for (i = 0; i < port.n_scene; i++)
        if (str_eq(port.scene[i].name, role)) return port.scene[i].value;
    return 0;
}

static unsigned std_string(const char *s)
{
    unsigned str = 0, alloc = 0;
    ((void (*)(unsigned *, const char *, unsigned *))(unsigned long)fn("string_new"))(&str, s, &alloc);
    return str;
}

static void *scene(const char *which)
{
    const char *id = pm_scene_id(which);
    unsigned str;
    void *res, *player, *manager;
    long at = pm_port_value("scene_player_scene", 0);
    if (!id) id = which;
    if (!id || !*id) return 0;
    manager = *(void **)(unsigned long)data("resource_manager");
    if (!manager) return 0;                     /* the game has not made it yet */
    str = std_string(id);
    res = ((void *(*)(void *, unsigned *, unsigned))(unsigned long)fn("resource_get"))
          (manager, &str, 0u);
    if (!res) return 0;
    player = ((void *(*)(void *, unsigned, unsigned, int))(unsigned long)fn("dynamic_cast"))
             (res, data("typeinfo_resource"), data("typeinfo_scene_player"), 0);
    return player ? *(void **)((char *)player + at) : 0;
}

static void *find_with(unsigned finder, const char *where, const char *path)
{
    unsigned str, out[2] = { 0, 0 };
    void *sc;
    if (!(can & PM_CAN_SCREENS) || !finder || !path || !*path) return 0;
    sc = scene(where);
    if (!sc) return 0;
    str = std_string(path);
    ((void (*)(unsigned *, void *, unsigned *))(unsigned long)finder)(out, sc, &str);
    return (void *)(unsigned long)out[0];
}

void *pm_node(const char *where, const char *path) { return find_with(fn("find_node"), where, path); }
void *pm_text(const char *where, const char *path) { return find_with(fn("find_text"), where, path); }

void pm_show(void *node, int on)
{
    long slot = pm_port_value("node_visible_vfn", -1);
    if (!(can & PM_CAN_SCREENS) || !node || slot < 0) return;
    ((void (*)(void *, unsigned))(unsigned long)(*(void ***)node)[slot / 4])(node, on ? 1u : 0u);
}

/* item 154 display: the words each text node was last given. pm_set_text writes only a CHANGE, so
 * a mode may call it every tick (a countdown, a health bar in words): an unchanged line costs no
 * string, no leak and no re-layout in the game. A line of 96 characters or more is always written. */
#define TEXT_LAST 16
static struct { void *text; int kept; char words[96]; } text_last[TEXT_LAST];
static unsigned text_last_next;

static int text_unchanged(void *text, const char *words)
{
    unsigned i, k, n;
    for (n = 0; words[n] && n < sizeof text_last[0].words; n++) ;
    for (i = 0; i < TEXT_LAST && text_last[i].text != text; i++) ;
    if (i < TEXT_LAST && text_last[i].kept && n < sizeof text_last[0].words && str_eq(text_last[i].words, words))
        return 1;
    if (i == TEXT_LAST) i = text_last_next++ % TEXT_LAST;
    text_last[i].text = text;
    text_last[i].kept = n < sizeof text_last[0].words;        /* too long to compare: never "unchanged" */
    for (k = 0; k < n && k + 1 < sizeof text_last[0].words; k++) text_last[i].words[k] = words[k];
    text_last[i].words[k] = 0;
    return 0;
}

void pm_set_text(void *text, const char *words)
{
    unsigned str;
    if (!(can & PM_CAN_SCREENS) || !text || !words) return;
    if (text_unchanged(text, words)) return;
    str = std_string(words);
    ((void (*)(void *, unsigned *))(unsigned long)fn("set_text"))(text, &str);
}

/* ---- clips --------------------------------------------------------------------------------------
 * Every in-game clip plays by name on the video bank's surface - and PLAYING IS NOT DRAWING:
 * the display is immediate-mode, so the runtime advances and draws the video player every
 * tick while the surface plays, as the game's own clip loop does. Proven: item 132. */
static struct { int on, seen; unsigned long started, last; } clip;
/* item 164: CLIP V2 - the newer builds have no clip_play / video_player / video_surface function
 * (the lookup is inlined at every call site: Venom 1.07 has 22), so the runtime does what their
 * code does: the video bank scene (`scene video_bank`, 60ed7e50... on 28 of 30 latest builds), its
 * root, the node "VideoSurface" by the typed find (`site surface_find`, find_node + 0x2f4 on every
 * build), then surface_set_video(surface, &name) and surface_play(surface, 0, -1). That surface is
 * DRAWN BY THE GAME (an added clip seen in a game on 14 builds, emulator 2026-09-25): no draw loop. A port
 * with `site video_surface` gets the surface from the game's own getter instead: on a build whose
 * bank is demand_loaded (JP LE) the bank is not in the resource manager until that getter loads it. */
static int clip_v2;
static void *clip2_surf;
/* item 164: a surface the app GRAFTED into a scene the game draws all game (The Munsters' HUD:
 * `value clip_surface_hide 1`) keeps a finished clip's last frame on the glass, so the Sprite
 * "PadMode_Clips" holding it is hidden until a clip plays and hidden again when the clip ends
 * (pm_show, as a screen is). The surface itself is no Sprite: its visibility slot crashes the game. */
static int clip2_hidden, clip2_said;
static unsigned long clip2_tried;

static void clip2_show(int on)
{
    void *node;
    if (!pm_port_value("clip_surface_hide", 0)) return;
    node = pm_node("video_bank", "PadMode_Clips");
    if (!node) return;
    if (!clip2_said) say("clip: the grafted clips' Sprite is found - %s", on ? "shown" : "hidden until a clip plays");
    clip2_said = 1;
    pm_show(node, on);
    clip2_hidden = !on;
}
/* item 164: CLIP LAYER - Deadpool shows a full-screen video by adding a video LAYER to its display
 * stack (`data layer_stack`, `data video_layer`: add(stack, layer, priority) = `site layer_add`,
 * remove(stack, layer) = `site layer_remove`) and asking the layer's video object (at
 * `value layer_video_at` in the layer) for a clip by name (`site layer_video`: request(obj, &name,
 * loop); `site layer_playing`: playing(obj)) - the game's own "SinisterModeTotal" sequence. On those
 * builds the video bank's surface is not on the glass by itself. Emulator-proven on Deadpool LE 1.14
 * 2026-09-25 (attract and a game; the HUD is back when the layer is removed). */
static int clip_layer, clip_layer_in;

static void *clip_layer_video(void)
{
    return *(void **)(unsigned long)(data("video_layer") + (unsigned)pm_port_value("layer_video_at", 0x14));
}

static void clip_layer_out(void)
{
    if (!clip_layer_in) return;
    ((void (*)(unsigned, unsigned))(unsigned long)fn("layer_remove"))(data("layer_stack"), data("video_layer"));
    clip_layer_in = 0;
}

static void *clip2_surface(void)
{
    unsigned str, out[2] = { 0, 0 };
    void *root;
    if (site("video_surface"))                /* the game's own getter: it loads a demand_loaded bank */
        return ((void *(*)(void))(unsigned long)fn("video_surface"))();   /* (JP LE); never cached */
    if (clip2_surf) return clip2_surf;
    root = scene("video_bank");
    if (!root) return 0;
    str = std_string(pm_port_value("clip_surface_hide", 0) ? "PadMode_Clips.VideoSurface" : "VideoSurface");
    ((void (*)(unsigned *, void *, unsigned *))(unsigned long)fn("surface_find"))(out, root, &str);
    clip2_surf = (void *)(unsigned long)out[0];
    return clip2_surf;
}
/* item 154 display: our own clip_play calls are marked, so the clip_play hook can tell the game's
 * from ours; the name is kept for the layered background's calls a hold answers with it */
static volatile int disp_clip_ours, disp_clip_lost;
static char disp_clip_name[96], disp_lost_name[64];
static void display_tick(void);           /* the display priority section, below */
static void block_tick(void);             /* PAD-347: a mode that keeps the game's modes from starting */

int pm_clip(const char *name)
{
    unsigned i;
    if (!(can & PM_CAN_CLIPS) || !name || !*name) return 0;
    if (clip_layer) {
        void *video = clip_layer_video();
        unsigned str;
        if (!video) { say("clip: the video layer has no video yet - \"%s\" not played", name); return 0; }
        if (!clip_layer_in)
            ((void (*)(unsigned, unsigned, unsigned))(unsigned long)fn("layer_add"))
                (data("layer_stack"), data("video_layer"), (unsigned)pm_port_value("clip_layer_priority", 5));
        clip_layer_in = 1;
        str = std_string(name);
        ((void (*)(void *, unsigned *, int))(unsigned long)fn("layer_video"))(video, &str, 0);
        clip.on = 1;
        clip.seen = 0;
        clip.started = clip.last = pm_ms();
        return 1;
    }
    if (clip_v2) {
        void *surf = clip2_surface();
        unsigned str;
        if (!surf) { say("clip: the video bank's VideoSurface is not there yet - \"%s\" not played", name); return 0; }
        str = std_string(name);
        if (!((int (*)(void *, unsigned *))(unsigned long)fn("surface_set_video"))(surf, &str)) {
            say("clip: the video bank has no clip \"%s\"", name);
            return 0;
        }
        clip2_show(1);
        ((int (*)(void *, int, int))(unsigned long)fn("surface_play"))(surf, 0, -1);
        clip.on = 1;
        clip.seen = 0;
        clip.started = clip.last = pm_ms();
        return 1;
    }
    for (i = 0; name[i] && i + 1 < sizeof disp_clip_name; i++) disp_clip_name[i] = name[i];
    disp_clip_name[i] = 0;
    disp_clip_ours = 1;
    ((void (*)(const char *, int, const char *))(unsigned long)fn("clip_play"))(name, 0, 0);
    disp_clip_ours = 0;
    disp_clip_lost = 0;
    clip.on = 1;
    clip.seen = 0;
    clip.started = clip.last = pm_ms();
    return 1;
}

int pm_clip_playing(void) { return clip.on; }

void pm_clip_stop(void)
{
    if (!(can & PM_CAN_CLIPS)) return;
    if (clip_layer) {
        clip_layer_out();
    } else if (clip_v2) {
        if (clip2_surface()) ((void (*)(void *))(unsigned long)fn("surface_stop"))(clip2_surface());
        clip2_show(0);
    } else {
        ((void (*)(void))(unsigned long)fn("clip_stop"))();
    }
    clip.on = 0;
}

/* PAD-301: the frame hand-over (below clip_tick, where it is explained) */
static int frame_hooked, frame_draws;
static volatile int frame_pending, frame_built;
static unsigned frame_n, frame_bare;      /* frames the game built while our full-screen clip played; without it */
static unsigned long frame_adv;           /* pm_ms() the hand-over last advanced the player */
static unsigned frame_loops, frame_builds;  /* the game's main-loop turns and the frames it built, this minute */
static unsigned long frame_minute;
static void clip_frames_said(void);

static void clip_tick(void)
{
    void *player, *surface, *display;
    int state;
    unsigned long now;
    long playing = pm_port_value("surface_playing", 2);
    display_tick();                           /* item 154 display: the hold, the covered state */
    block_tick();                             /* PAD-347: a block ends with its mode */
    if (!clip.on && clip_v2 && !clip2_hidden && pm_ms() - clip2_tried > 1000) {
        clip2_tried = pm_ms();                /* a grafted surface out of sight, once its scene is up */
        clip2_show(0);
    }
    if (frame_hooked && pm_ms() - frame_minute >= 60000) {
        /* PAD-301: the machine's own frame rate, for the emulator to match (PAD_SWAP_VBLANKS): its GPU
         * built ~29 a second while a clip played; how fast it builds the rest of the time is what this says */
        if (frame_minute && frame_loops)
            say("frames: the game built %u of %u frame(s) in the last minute (%u.%u a second)", frame_builds,
                frame_loops, frame_builds / 60, frame_builds % 60 * 10 / 60);
        frame_minute = pm_ms();
        frame_loops = frame_builds = 0;
    }
    if (!clip.on) { clip_frames_said(); return; }
    if (disp_clip_lost) {                     /* item 154 display: the game played a clip of its own */
        clip.on = 0;
        disp_clip_lost = 0;
        say("clip: the game played its own clip \"%s\" on the one surface - ours stops drawing", disp_lost_name);
        return;
    }
    now = pm_ms();
    if (clip_layer) {                         /* the game draws the layer: watch its video, then take it out */
        void *video = clip_layer_video();
        if (video && ((int (*)(void *))(unsigned long)fn("layer_playing"))(video)) clip.seen = 1;
        else if (clip.seen || now - clip.started > 3000) { clip_layer_out(); clip.on = 0; }
        clip.last = now;
        return;
    }
    if (clip_v2) {                            /* the game draws it: only watch the surface */
        surface = clip2_surface();
        state = surface ? ((int (*)(void *))(unsigned long)fn("surface_state"))(surface) : -1;
        if (state == playing) clip.seen = 1;
        else if (clip.seen || now - clip.started > 3000) { clip.on = 0; clip2_show(0); }
        clip.last = now;
        return;
    }
    player = ((void *(*)(void))(unsigned long)fn("video_player"))();
    surface = ((void *(*)(void))(unsigned long)fn("video_surface"))();
    display = *(void **)(unsigned long)(data("display_holder") + (unsigned)pm_port_value("display_at", 0));
    state = player && surface && display ? ((int (*)(void *))(unsigned long)fn("surface_state"))(surface) : -1;
    if (state == playing) {
        if (!frame_draws) {                   /* PAD-301: with the hand-over hooked, advanced and drawn there */
            ((void (*)(void *, float))(unsigned long)fn("player_advance"))(player, (float)(now - clip.last));
            ((void (*)(void *, void *, unsigned))(unsigned long)fn("display_draw"))
                (display, player, (unsigned)pm_port_value("clip_layer", 0));
        }
        clip.seen = 1;
    } else if (clip.seen || now - clip.started > 3000) {
        clip.on = 0;
    }
    clip.last = now;
}

/* PAD-301: A FULL-SCREEN CLIP IS DRAWN AT THE GAME'S FRAME HAND-OVER, NOT FROM THE TICK.
 * How the game hands a frame to its renderer (Godzilla Premium 1.16, read off the program): the main
 * loop runs the tick, asks whether the renderer is idle (frame begin, 0x2a56a0: display +0xb5 busy,
 * +0xb0/b1/b2 a frame pending), builds its frame only then (frame end, 0x405f34, entered with r0 = 0
 * when it builds), and wakes the renderer at the end of either path (the kick, 0x2a5530). The renderer
 * thread takes the whole pending list whenever it wakes or finishes a frame and finds +0xb1 set.
 * A player drawn from the TICK lands before the begin: it keeps the game from building at all while
 * the renderer is fast (the emulator: the clip alone on the glass, the HUD processes starved, run h10),
 * and on the machine, whose renderer needs about two refreshes a frame, the tick's draw is refused
 * while the last frame still holds the player, so the next frame the game builds goes to the glass
 * with the HUD and no clip: the HUD bursting through a mode's intro (traced on a Premium 1.16,
 * 2026-10-01: drawn 60 of 60 ticks, the game building ~29 frames a second). Drawn at the kick of a
 * frame the game built, the player is the last thing in every frame, over the HUD, and the game's
 * display keeps running under it. A port without `site frame_end` / `site frame_kick` keeps the tick.
 * The ADVANCE moves too: advancing the player queues its next picture for the renderer (+0xb0, the
 * same flag the begin reads), so a tick that advances keeps the game from building as surely as a tick
 * that draws - the emulator at the machine's cadence built 1 frame in a 6 s intro with the draw moved
 * and the advance left on the tick. The game advances its own background's player inside its update. */
static void clip_frames_said(void)
{
    if (!frame_n) return;
    say("clip: the game built %u frame(s) while our full-screen clip played; %u went to the glass without it%s",
        frame_n, frame_bare, frame_bare ? " (the HUD showed through)" : "");
    frame_n = frame_bare = 0;
}

static void on_frame_end(unsigned *r)
{
    frame_pending = 1;
    frame_built = r[0] == 0;                  /* the begin said the renderer was idle: a frame is built */
    frame_loops++;
    if (frame_built) frame_builds++;
}

static void on_frame_kick(unsigned *r)
{
    void *player, *surface, *display;
    (void)r;
    if (!frame_pending) return;               /* the kick's other caller (a loading loop): not a game frame */
    frame_pending = 0;
    if (!frame_built || !clip.on || clip_v2 || clip_layer || disp_clip_lost) return;
    player = ((void *(*)(void))(unsigned long)fn("video_player"))();
    surface = ((void *(*)(void))(unsigned long)fn("video_surface"))();
    display = *(void **)(unsigned long)(data("display_holder") + (unsigned)pm_port_value("display_at", 0));
    if (!player || !surface || !display ||
        ((int (*)(void *))(unsigned long)fn("surface_state"))(surface) != pm_port_value("surface_playing", 2))
        return;
    if (frame_draws) {
        unsigned long now = pm_ms(), from = frame_adv > clip.started ? frame_adv : clip.started;
        ((void (*)(void *, float))(unsigned long)fn("player_advance"))(player, (float)(now - from));
        frame_adv = now;
        ((void (*)(void *, void *, unsigned))(unsigned long)fn("display_draw"))
            (display, player, (unsigned)pm_port_value("clip_layer", 0));
    }
    /* the player's in-the-list mark for the layer (display_draw sets it, the renderer clears it): a frame
     * handed over without it is a frame of the game's alone - counted either way, so the tick route
     * (value clip_draw_at_kick 0) can be measured against this one */
    frame_n++;
    if (!((unsigned char *)player)[8 + (unsigned)pm_port_value("clip_layer", 0)]) frame_bare++;
}

static void frame_arm(void)
{
    if (!site("frame_end") && !site("frame_kick")) return;     /* a port without them: the tick draws */
    if (!(can & PM_CAN_CLIPS) || clip_v2 || clip_layer || !site("frame_end") || !site("frame_kick")) {
        say("clip: the frame hand-over lines are incomplete or not this build's - a full-screen clip is drawn from the tick");
        return;
    }
    if (hook(fn("frame_end"), on_frame_end) && hook(fn("frame_kick"), on_frame_kick)) {
        frame_hooked = 1;
        frame_draws = pm_port_value("clip_draw_at_kick", 1) != 0;
        say("clip: %s (frame end 0x%08x, kick 0x%08x)", frame_draws
            ? "a full-screen clip is drawn at the game's frame hand-over"
            : "a full-screen clip is drawn from the tick (clip_draw_at_kick 0); the hand-over only counts its frames",
            fn("frame_end"), fn("frame_kick"));
    }
}

/* ---- the backdrop: a clip BEHIND the HUD (hud-layers) --------------------------------------------
 * How the game shows its own backgrounds (Godzilla Premium 1.16, docs/plans/hud-layers.md, runs h1-h12):
 * every frame the layered display draws its BACKGROUND element first (site backdrop_draw,
 * BDLBackground::v[8]): the video bank's player when the background has a clip (the object's video field,
 * +backdrop_video_at), then the element's own scene (+backdrop_scene_at). The HUD scenes are drawn after
 * it, so a battle's clip sits under the score panel, the top bar and the timers. In main play the
 * background is one of the city objects (data backdrop_city_vtable), whose scene is the city.
 *
 * A player WE put in the frame's list, however placed, stopped the game's display processes (h3-h11).
 * What works is the game's own route, taken from inside the background element's draw (the layered
 * display's process): clip_play there, and the city object's video field set to the surface, as
 * BDLBackground::v[13] does for a background with a clip. The game's update then advances the player, its
 * draw shows it, and the city's own scene show is handed the player instead - already in the frame's
 * list, so display_draw refuses it and the city is not drawn (h12, variant 6).
 *
 * The one surface is shared: a framed award of the game's (the Maser) plays in its place and the loop is
 * played again once the surface is idle; while one of our full-screen clips plays (pm_clip, layer 0) the
 * video field is 0, so the tick's draw of it is not refused. Everything here runs on the display
 * processes' thread (the hooks) or the tick's, which is the same thread (the runtime logs both). */
static struct {
    char loop[96], once[96];          /* the loop, and a clip to play once in its place first */
    int on, pending, playing_once, lost;
    unsigned elem, obj;               /* the background element drawing now; the city whose field we set */
    unsigned long since;              /* pm_ms() of the last play */
    unsigned plays, frames;
} bd;
static unsigned char *disp_layered_mgr;   /* the layered display's manager (display priority, below) */

static unsigned bd_surface_state(void)
{
    void *s = ((void *(*)(void))(unsigned long)fn("video_surface"))();
    return s ? (unsigned)((int (*)(void *))(unsigned long)fn("surface_state"))(s) : 0;
}

static void bd_field(unsigned obj, unsigned v)
{
    if (obj) *(unsigned *)(unsigned long)(obj + (unsigned)pm_port_value("backdrop_video_at", 0x54)) = v;
}

static void bd_release(const char *why)
{
    if (bd.obj) {
        bd_field(bd.obj, 0);
        say("backdrop: taken away (%s) after %u play(s), %u frame(s)", why, bd.plays, bd.frames);
    }
    bd.obj = 0;
}

static void on_backdrop_draw(unsigned *r)
{
    bd.elem = r[0];
}

static void bd_play(unsigned e)
{
    const char *name = bd.once[0] ? bd.once : bd.loop;
    const char *crop = pm_port_text("backdrop_crop");
    int once = name == bd.once;
    char was[96];
    unsigned i;
    if (!name[0]) return;
    for (i = 0; name[i] && i + 1 < sizeof was; i++) was[i] = name[i];
    was[i] = 0;
    disp_clip_ours = 1;
    ((void (*)(const char *, int, const char *))(unsigned long)fn("clip_play"))(was, once ? 0 : 1, crop ? crop : "ScoreFrame");
    disp_clip_ours = 0;
    bd.playing_once = once;
    if (once) bd.once[0] = 0;
    bd_field(e, (unsigned)(unsigned long)((void *(*)(void))(unsigned long)fn("video_surface"))());
    bd.obj = e;
    bd.pending = bd.lost = 0;
    bd.since = pm_ms();
    if (bd.plays++ < 60)
        say("backdrop: \"%s\" %s behind the HUD, in the city 0x%08x's place", was, once ? "once" : "looped", e);
}

/* PAD-353: the game's foreground words are never hidden. PAD-301 emptied the scene_show of a layered
 * foreground of the game's that did not beat a mode's hold (its words sat where a mode's title does); a
 * mode keeps its own words off a game display instead (pm_display_covered), and the game's screens play
 * as the game made them. */
static unsigned disp_prio;
static unsigned char *disp_layered_mgr;

/* scene_show(scene, layer): the city's own scene is where the backdrop goes */
static void on_scene_show(unsigned *r)
{
    unsigned e = bd.elem, playing = (unsigned)pm_port_value("surface_playing", 2);
    /* PAD-301: while our full-screen clip plays, the hand-over draws the one video player LAST in every
     * frame. An element of the game's that draws it too (a framed award of the game's already up when the
     * mode started: its clip in the background's place) would put it in the frame first, under the HUD,
     * and the hand-over's draw would be refused as a second copy - the intro under the HUD (run fg). */
    if (frame_draws && clip.on && !clip_v2 && !clip_layer && !disp_clip_lost && r[0] &&
        r[0] == (unsigned)(unsigned long)((void *(*)(void))(unsigned long)fn("video_player"))()) {
        r[0] = 0;
        return;
    }
    if (!e || r[0] != *(unsigned *)(unsigned long)(e + (unsigned)pm_port_value("backdrop_scene_at", 0x18))) return;
    if (!bd.on || *(unsigned *)(unsigned long)e != data("backdrop_city_vtable")) {
        if (bd.obj) bd_release(!bd.on ? "the mode ended it" : "another background");
        return;
    }
    if (bd.obj && bd.obj != e) bd_release("the city changed");
    if (clip.on) {                     /* our full-screen clip (layer 0) plays: the tick draws it over all */
        if (bd.obj) bd_release("a full-screen clip of ours plays");
        bd.pending = 1;
        return;
    }
    if (!bd.pending && bd.obj && !bd.lost) {
        if (bd_surface_state() == playing) {
            void *player = ((void *(*)(void))(unsigned long)fn("video_player"))();
            if (player) {
                r[0] = (unsigned)(unsigned long)player;   /* refused: it is in the list already */
                bd.frames++;
            }
            return;
        }
        if (pm_ms() - bd.since < 1500) return;          /* still starting */
    }
    if (bd.lost && bd_surface_state() == playing) {      /* the game's clip on the surface: the city */
        if (bd.obj) { bd_field(bd.obj, 0); bd.obj = 0; }
        return;
    }
    bd_play(e);                        /* asked, a one-shot or the game's clip over: play (again) */
}

int pm_backdrop(const char *name)
{
    unsigned i;
    if (!(can & PM_CAN_BACKDROP)) return 0;
    if (!name || !*name) {
        if (bd.on && !clip.on && bd.obj && bd_surface_state() == (unsigned)pm_port_value("surface_playing", 2))
            ((void (*)(void))(unsigned long)fn("clip_stop"))();
        bd.on = 0;
        bd.loop[0] = bd.once[0] = 0;
        bd.playing_once = 0;
        bd_release("the mode ended it");
        return 1;
    }
    if (bd.on && str_eq(bd.loop, name)) return 1;
    for (i = 0; name[i] && i + 1 < sizeof bd.loop; i++) bd.loop[i] = name[i];
    bd.loop[i] = 0;
    bd.on = bd.pending = 1;
    return 1;
}

int pm_backdrop_once(const char *name)
{
    unsigned i;
    if (!(can & PM_CAN_BACKDROP) || !name || !*name || !bd.on) return 0;
    for (i = 0; name[i] && i + 1 < sizeof bd.once; i++) bd.once[i] = name[i];
    bd.once[i] = 0;
    bd.pending = 1;
    return 1;
}

int pm_backdrop_showing(void)
{
    return bd.on && bd.obj && !bd.pending && !clip.on;
}

/* the game played a clip of its own on the one surface while the backdrop is up (the clip_play hook
 * tells us): ours is played again once the surface is idle */
static void bd_clip_lost(void)
{
    if (bd.on && bd.obj) bd.lost = 1;
}

/* a ball end or leaving the game: no backdrop outlives the mode that asked for it */
static void bd_reset(const char *why)
{
    if (!bd.on && !bd.obj) return;
    bd.on = 0;
    bd.loop[0] = bd.once[0] = 0;
    bd_release(why);
}

static int have_sites(const char *const *names);
static void backdrop_arm(void)
{
    static const char *const s[] = { "backdrop_draw", "scene_show", "clip_play", "clip_stop", "video_player",
                                     "video_surface", "surface_state", 0 };
    static const char *const d[] = { "backdrop_city_vtable", 0 };
    if (!site("backdrop_draw")) return;                  /* a port without it: silent */
    if (!(can & PM_CAN_CLIPS) || clip_v2 || clip_layer || !have_sites(s) || !have_data(d)) {
        say("backdrop: off - the port's backdrop lines are incomplete or do not match this build");
        return;
    }
    if (hook(fn("backdrop_draw"), on_backdrop_draw) && hook(fn("scene_show"), on_scene_show)) {
        can |= PM_CAN_BACKDROP;
        say("backdrop: on - a mode's clip plays behind the HUD in the main-play background's place "
            "(draw 0x%08x, scene show 0x%08x)", fn("backdrop_draw"), fn("scene_show"));
    }
}

/* ---- display priority (item 154 display) --------------------------------------------------------
 * HOW THE GAME LAYERS ITS DISPLAY (read off Godzilla Pro 1.15 and Premium 1.16, measured in the
 * emulator with display_probe.c; MODE_SDK.md "Display priority"):
 *  1. DISPLAY EFFECTS. One manager (data display_effects points at it) runs ONE effect at a time
 *     from the table the award screen uses (data award_screen_arg: {records, count}, a record
 *     {process, u16 flags, u8 priority}); +display_now_at is the effect now, +display_priority_at
 *     its priority. start(manager, id, queue, force, 1) starts a new effect when its priority is
 *     above the current one's (equal only when the current one allows it), killing the current one,
 *     and otherwise refuses it, or queues it when the caller asks. Most of the game's awards come
 *     through a WAITER that asks again every frame, at priority 176, until it may start or its
 *     time runs out. Background effects (flag 1) run when nothing else does: attract (1), the
 *     LAYERED DISPLAY (value display_host, 29 on Godzilla, priority 1) in a game, the tilt (31).
 *  2. LAYERED DISPLAYS, inside the layered-display effect: a background (the city, a mode's
 *     background) and one foreground at a time, from a table (data layered_displays: {records,
 *     count}, a record of layered_record_size with its flags first and its priority at
 *     +layered_priority_at). Each foreground is asked for by a waiter process (the display it
 *     waits for at +layered_wait_for_at of the process) that waits while the layered priority now
 *     (site layered_priority) is not below its own. Flags: 0x10 full screen (without it the clip
 *     plays inside the score frame, UNDER the HUD and a mode's own screen), 0x40 a mode start,
 *     0x04 a total (allowed at the end of a ball), 0x02 a background.
 *  The HUD (score frame, the mode slide-outs of scene 32e6ae28 and a mode's own screen in it) is
 *  drawn over a clip played in the "ScoreFrame" crop (the framed layered displays, and effects that
 *  use that crop) and is covered by one played full screen ("Normal" or no crop: LOOPS, BATTLE IS
 *  LIT, a jackpot, the tilt warning); a clip the runtime draws on layer 0 is over everything.
 * PAD-353: A MODE NEVER MAKES THE GAME'S DISPLAYS WAIT. Item 154/157's HOLD raised the layered display's
 * effect priority to a mode's, so the game's own comparison refused or queued what did not beat it, kept
 * its waiters waiting, dropped full-screen layered displays at their waiter and hid a foreground's words.
 * On a Godzilla Premium (2026-10-04) that held the MAGNA-GRAB MAGNET ON: the game keeps the ball on the
 * magnet until its screen (effect 71, priority 180) has played, and that screen waited for KING
 * GHIDORAH's hold at 180 until the machine was switched off. Any rule that waits on a display can stall
 * the same way. So pm_display_priority only notes the mode's priority now, and the runtime WATCHES the
 * game's displays: pm_display_covered says when one has the screen, for the mode to keep its words off it. */
static const struct pm_mode *disp_owner;
static unsigned disp_prio;                /* 0: no hold */
static unsigned long disp_linger_until;   /* pm_end_holding: the hold outlives its mode until then */
static int disp_covered_now;
static unsigned char *disp_manager(void)
{
    unsigned a = data("display_effects"), t = data("award_screen_arg");
    unsigned char *m;
    if (!a || !t) return 0;
    m = *(unsigned char **)(unsigned long)a;
    return m && *(unsigned *)(m + 4) == t ? m : 0;           /* the manager of THIS effect table */
}

static unsigned disp_host(void) { return (unsigned)pm_port_value("display_host", 0); }
static unsigned disp_now(unsigned char *m) { return *(unsigned short *)(m + pm_port_value("display_now_at", 0xc)); }
static unsigned disp_level_now(unsigned char *m) { return *(m + pm_port_value("display_priority_at", 0xe)); }

static void disp_release(const char *why)
{
    unsigned p = disp_prio;
    if (!p) return;
    disp_prio = 0;
    disp_owner = 0;
    disp_linger_until = 0;
    disp_covered_now = 0;
    say("display: priority %u given up (%s)", p, why);
}

int pm_display_priority(unsigned priority)
{
    unsigned char *m;
    if (!(can & PM_CAN_DISPLAY_PRIORITY)) return 0;
    if (!priority) {
        if (disp_prio && (!current || disp_owner == current)) disp_release("the mode gave it up");
        return 1;
    }
    if (!running || running != current) return 0;
    if (priority > 255) priority = 255;
    disp_owner = current;
    disp_prio = priority;
    m = disp_manager();
    say("display: %s asks for display priority %u - noted only: the game's displays are never made to wait "
        "(effect now %u, priority %u)", current && current->name ? current->name : "a mode", priority,
        m ? disp_now(m) : 0, m ? disp_level_now(m) : 0);
    return 1;
}

int pm_display_covered(void) { return disp_prio && disp_covered_now; }

/* an ending kept by pm_end_holding is not the new mode's */
static void disp_linger_other_began(void)
{
    if (disp_linger_until && disp_owner != current) disp_release("another mode began");
}

int pm_end_holding(unsigned ms)
{
    if (!running || running != current) return 0;
    if (disp_prio && disp_owner == current && ms) {
        disp_linger_until = pm_ms() + ms;
        if (!disp_linger_until) disp_linger_until = 1;
        say("display: %s ended - its screen is watched %u ms more for its ending", current->name ? current->name : "a mode", ms);
    }
    pm_end();
    return 1;
}

/* every tick, from clip_tick: follows the mode that asked, and says when a display of the game's has the
 * screen - an effect over the layered display, or a layered foreground - and when it is gone */
static void display_tick(void)
{
    unsigned char *m;
    unsigned now;
    int covered;
    if (!disp_prio) return;
    if (!disp_owner || running != disp_owner) {
        if (!disp_linger_until) { disp_release("the mode that asked ended"); return; }
        if (running) { disp_release("another mode began"); return; }
        if (pm_ms() >= disp_linger_until) { disp_release("its ending is over"); return; }
    }
    if (!pm_in_game()) { disp_release("left the game"); return; }
    m = disp_manager();
    if (!m) return;
    now = disp_now(m);
    covered = now && now != disp_host();
    if (!covered && disp_layered_mgr && now == disp_host() &&
        *(unsigned *)(disp_layered_mgr + pm_port_value("layered_fg_at", 0x58)))
        covered = 2;
    if (!covered != !disp_covered_now) {
        if (covered == 1) say("display: the game's effect %u (priority %u) has the screen", now, disp_level_now(m));
        else if (covered) say("display: a layered display of the game's has the screen");
        else say("display: in view again");
    }
    disp_covered_now = covered;
}

/* The layered priority, as the game asks it: only its manager is noted (display_tick reads the foreground
 * there). The answer is the game's own, always. */
static void on_layered_priority(unsigned *r)
{
    if (r[0]) disp_layered_mgr = (unsigned char *)(unsigned long)r[0];
}

/* clip_play from anyone but us while our clip draws: the one surface is the game's now */
static void on_clip_play(unsigned *r)
{
    const char *name = (const char *)(unsigned long)r[0];
    unsigned i;
    if (!disp_clip_ours) bd_clip_lost();      /* hud-layers: the backdrop is played again after it */
    if (disp_clip_ours || !clip.on) return;
    for (i = 0; name && name[i] && i + 1 < sizeof disp_lost_name; i++) disp_lost_name[i] = name[i];
    disp_lost_name[i] = 0;
    disp_clip_lost = 1;
}

static int have_sites(const char *const *names);
static int have_data(const char *const *names);
static int have_values(const char *const *names);

/* from the constructor: the clip_play hook always (a clip of ours stops drawing when the game takes the
 * surface); the display lines when the port names them, to WATCH the game's displays (pm_display_covered),
 * never to change them (PAD-353) */
static void display_arm(void)
{
    static const char *const d[] = { "display_effects", "award_screen_arg", 0 };
    static const char *const v[] = { "display_host", "display_now_at", "display_priority_at", 0 };
    if ((can & PM_CAN_CLIPS) && !clip_v2 && !clip_layer) hook(fn("clip_play"), on_clip_play);
    if (!site("display_effect_start") && !site("layered_priority")) return;      /* a port without them: silent */
    if (!have_data(d) || !have_values(v)) {
        say("display priority: off - the port's display lines are incomplete or do not match this build");
        return;
    }
    can |= PM_CAN_DISPLAY_PRIORITY;
    if (site("layered_priority") && fn("layered_priority") && pm_port_value("layered_fg_at", -1) >= 0)
        hook(fn("layered_priority"), on_layered_priority);
    say("display priority: watched only - a mode is told when a display of the game's has the screen; none of "
        "the game's displays is ever made to wait, refused, dropped or hidden (PAD-353: Godzilla's Magna-Grab "
        "kept its magnet on while its screen waited for a mode)");
}


/* ---- the game's own message screens (optional) ----------------------------------------------- */
#define N_BORROW 8
static struct { unsigned id, idx; const char **old; const char *group[6]; char words[96]; int held; } borrow[N_BORROW];

int pm_message_set(unsigned id, const char *words)
{
    unsigned count, i, k;
    unsigned short *remap;
    const char ***slot;
    if (!(can & PM_CAN_MESSAGES) || !words) return 0;
    count = *(unsigned *)(unsigned long)data("message_count");
    remap = *(unsigned short **)(unsigned long)data("message_remap");
    if (!remap || id >= count || remap[id] >= count) return 0;
    for (i = 0; i < N_BORROW && borrow[i].held && borrow[i].id != id; i++) ;
    if (i == N_BORROW) return 0;
    str_copy(borrow[i].words, sizeof borrow[i].words, words, sizeof borrow[i].words);
    for (k = 0; k < 5; k++) borrow[i].group[k] = borrow[i].words;
    borrow[i].group[5] = 0;
    if (!borrow[i].held) {
        borrow[i].id = id;
        borrow[i].idx = remap[id];
        slot = (const char ***)(unsigned long)(data("message_table") + 4u * borrow[i].idx);
        borrow[i].old = *slot;
        *slot = borrow[i].group;
        borrow[i].held = 1;
    }
    return 1;
}

void pm_message_restore(unsigned id)
{
    unsigned i;
    for (i = 0; i < N_BORROW; i++)
        if (borrow[i].held && borrow[i].id == id) {
            *(const char ***)(unsigned long)(data("message_table") + 4u * borrow[i].idx) = borrow[i].old;
            borrow[i].held = 0;
        }
}

int pm_award_screen(unsigned type, unsigned message_id, uint64_t value)
{
    unsigned char *node;
    if (!(can & PM_CAN_AWARD_SCREEN) || !type) return 0;
    node = ((unsigned char *(*)(unsigned, unsigned, unsigned, unsigned))(unsigned long)fn("award_screen"))
           (type, 0u, 0u, data("award_screen_arg"));
    if (!node) return 0;
    *(unsigned short *)(node + pm_port_value("award_message_at", 0)) = (unsigned short)message_id;
    *(uint64_t *)(node + pm_port_value("award_value_at", 0)) = value;
    *(unsigned *)(node + pm_port_value("award_count_at", 0)) = 0u;
    return 1;
}

/* ---- trigger files ---------------------------------------------------------------------------- */
int pm_trigger_text(const char *name, char *out, unsigned cap)
{
    char path[96];
    long n;
    int fd;
    pm_snprintf(path, sizeof path, "/dump/%s", name);
    fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    n = out && cap ? read(fd, out, cap - 1) : 0;
    close(fd);
    unlink(path);
    if (out && cap) {
        long i;
        out[n > 0 ? n : 0] = 0;
        for (i = 0; out[i] && out[i] != '\n' && out[i] != '\r'; i++) ;
        out[i] = 0;
    }
    return 1;
}

int pm_trigger(const char *name) { return pm_trigger_text(name, 0, 0); }

long pm_read_file(const char *path, char *buf, unsigned long cap)
{
    long n, tot = 0;
    int fd;
    if (!path || !buf || !cap) return -1;
    fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    while ((unsigned long)tot < cap && (n = read(fd, buf + tot, cap - (unsigned long)tot)) > 0)
        tot += n;
    close(fd);
    return tot;
}

/* ---- the game's own modes (item 140) ------------------------------------------------------------
 * The game's mode manager answers "is one of my modes active?" with compiled virtuals that walk
 * its own mode table (Godzilla: 27 modes, each with a kind - 0x1 multiball, 0x8 battle). The port
 * names them (stock_*_running) and the manager singleton (stock_mode_manager). They are CALLED,
 * never hooked, and only once the manager is built and a player is up: before the game builds
 * the manager its table is empty, and a query would read through null. */
static int stock_query(const char *site_name)
{
    unsigned f = fn(site_name), mgr = data("stock_mode_manager");
    if (!f || !mgr) return -1;
    if (!*(const unsigned *)(unsigned long)mgr) return -1;      /* no vtable yet: not built */
    if (!pm_player()) return 0;                                  /* no game, no game mode */
    return ((int (*)(void *, unsigned))(unsigned long)f)((void *)(unsigned long)mgr, 0u) ? 1 : 0;
}

/* item 164: the GENERIC route, for a title whose manager's own queries are not named (every title but
 * Godzilla): the runtime walks the game's mode TABLE itself (`data stock_mode_table`, `value
 * stock_mode_count`: the array its get-mode-by-id accessor reads), keeps the entries whose class
 * chain reaches `cmode` (their vtable's typeinfo, followed through single-inheritance bases:
 * `data typeinfo_cmode`, `data typeinfo_cmode_mball`), and asks each its ACTIVE slot (`value
 * stock_slot_active`, Godzilla's 14). A cmode_mball descendant that is active is a multiball; any
 * other active cmode is one of the game's modes (its "battle": the title's quests, timed modes...). */
static int stock_generic_on;
static char stock_generic_what[80];     /* "one of the game's modes (cmode_trex_chase)": the last one found */

static int stock_class(const unsigned *obj)
{
    /* 2 = a cmode_mball, 1 = another cmode, 0 = neither */
    unsigned ti_mode = data("typeinfo_cmode"), ti_mb = data("typeinfo_cmode_mball"), ti_vmi = data("typeinfo_vmi"), si, vmi, t;
    int guard = 12;
    if (!obj || !*obj || !ti_mb) return 0;
    si = *(const unsigned *)(unsigned long)ti_mb;            /* the vptr of a single-inheritance typeinfo */
    vmi = ti_vmi ? *(const unsigned *)(unsigned long)ti_vmi : 0;   /* and of a multiple-inheritance one */
    t = ((const unsigned *)(unsigned long)obj[0])[-1];
    while (t && guard-- > 0) {
        const unsigned *ti = (const unsigned *)(unsigned long)t;
        if (t == ti_mb) return 2;
        if (t == ti_mode) return 1;
        if (ti[0] == si) t = ti[2];
        else if (vmi && ti[0] == vmi) {
            /* {vptr, name, flags, base count, {base, offset << 8 | flags} x count}: the base at offset 0
             * (John Wick 1.01's cmode_the_staircase is a cmode_mball and a cwick_mode) */
            unsigned k, n = ti[3], next = 0;
            for (k = 0; k < n && k < 8; k++)
                if (!(ti[5 + 2 * k] >> 8)) { next = ti[4 + 2 * k]; break; }
            t = next;
        } else break;
    }
    return 0;
}

static int stock_generic_route(void)
{
    return data("stock_mode_table") && !(data("stock_mode_manager") && fn("stock_battle_running") && fn("stock_multiball_running"));
}

static int stock_entry_active(const unsigned *o, long slot)
{
    return (((int (*)(const void *))(unsigned long)((const unsigned *)(unsigned long)o[0])[slot])(o) & 0xff) != 0;
}

/* The game's BASE PLAY: some titles run modes for the whole ball (Venom 1.07's cmini_mode_01..03 are
 * active from the plunge on), so "a mode is running" would always be true there. Every tick the runtime
 * notes the entries running from a ball's start until 2 s after its first score; those are the base
 * play, not counted, until they are seen stopped (then they count like any other when they run again).
 * A ball is the player up plus the ball_start events (or ball ends) seen so far. */
#define N_STOCK_TABLE 160
static unsigned char stock_base[N_STOCK_TABLE];
static volatile unsigned stock_ball_ends;       /* on_ball_end, below */
static unsigned event_count(int id);             /* the events section, below */
static unsigned stock_ball_key;
static unsigned long stock_base_until;           /* 0: closed; ~0: open until the ball's first score */
static uint64_t stock_base_score;

static void stock_base_clear(void)
{
    unsigned i;
    for (i = 0; i < N_STOCK_TABLE; i++) stock_base[i] = 0;
}

static void stock_generic_tick(void)
{
    static unsigned ticks;
    const unsigned *tab = (const unsigned *)(unsigned long)data("stock_mode_table");
    long n = pm_port_value("stock_mode_count", 0), slot = pm_port_value("stock_slot_active", -1), i;
    unsigned p, key;
    int ev, open;
    if (!tab || n <= 0 || slot < 0 || !stock_generic_route()) return;
    if (n > N_STOCK_TABLE) n = N_STOCK_TABLE;
    p = pm_in_game() ? pm_player() : 0;
    if (!p) {
        if (stock_ball_key) { stock_ball_key = 0; stock_base_clear(); }
        return;
    }
    ev = pm_event("ball_start");
    key = p | (ev >= 0 ? event_count(ev) : stock_ball_ends) << 3;
    if (key != stock_ball_key) {
        stock_ball_key = key;
        stock_base_clear();
        stock_base_until = ~0UL;
        stock_base_score = pm_score(p);
    }
    if (stock_base_until == ~0UL && pm_score(p) != stock_base_score) stock_base_until = pm_ms() + 2000;
    if (stock_base_until && stock_base_until != ~0UL && pm_ms() > stock_base_until) stock_base_until = 0;
    open = stock_base_until != 0;
    if (!open && ++ticks % 15) return;
    for (i = 0; i < n; i++) {
        const unsigned *o = (const unsigned *)(unsigned long)tab[i];
        if ((!open && !stock_base[i]) || !stock_class(o)) continue;
        if (!stock_entry_active(o, slot)) stock_base[i] = 0;
        else if (open && !stock_base[i]) {
            unsigned ti = ((const unsigned *)(unsigned long)o[0])[-1];
            const char *nm = ti ? (const char *)(unsigned long)((const unsigned *)(unsigned long)ti)[1] : 0;
            while (nm && *nm >= '0' && *nm <= '9') nm++;
            stock_base[i] = 1;
            say("stock modes: %s runs from the ball's start - the game's base play, not counted while it runs", nm ? nm : "?");
        }
    }
}

static int stock_generic(unsigned kinds)
{
    const unsigned *tab = (const unsigned *)(unsigned long)data("stock_mode_table");
    long n = pm_port_value("stock_mode_count", 0), slot = pm_port_value("stock_slot_active", -1), i;
    if (!tab || n <= 0 || slot < 0) return -1;
    if (!pm_player()) return 0;
    for (i = 0; i < n; i++) {
        const unsigned *o = (const unsigned *)(unsigned long)tab[i];
        int c = stock_class(o);
        if (!c || (i < N_STOCK_TABLE && stock_base[i])) continue;
        if (!stock_entry_active(o, slot)) continue;
        if ((c == 2 && (kinds & (PM_STOCK_MULTIBALL | PM_STOCK_ANY))) || (c == 1 && (kinds & (PM_STOCK_BATTLE | PM_STOCK_ANY)))) {
            unsigned ti = ((const unsigned *)(unsigned long)o[0])[-1];
            const char *nm = ti ? (const char *)(unsigned long)((const unsigned *)(unsigned long)ti)[1] : 0;
            while (nm && *nm >= '0' && *nm <= '9') nm++;          /* the mangled name's length */
            pm_snprintf(stock_generic_what, sizeof stock_generic_what, "%s (%s)",
                        c == 2 ? "a multiball" : "one of the game's modes", nm ? nm : "?");
            return c == 2 ? (int)PM_STOCK_MULTIBALL : (int)PM_STOCK_BATTLE;
        }
    }
    return 0;
}

/* item 164: the BALLS IN PLAY route, for a title with no cmode rules (the plain-C titles and Elvira's Rule
 * classes): the framework's own count of the balls in play (`site balls_in_play`, Beatles 1.29 0x1fd194, found
 * by its code on every build): while a multiball is being served it answers the balls that multiball asked
 * for, otherwise the balls installed less those in the trough and the other ball devices. Two or more is a
 * multiball. It says nothing of the title's other modes, so only PM_STOCK_MULTIBALL is ever answered here.
 * (The struct that function reads, `data ball_manager`, holds the asked-for count only while the multiball's
 * own process runs, so it alone is not a witness: 0 through a whole multiball on both Bond builds.) */
static int stock_balls_route(void)
{
    return fn("balls_in_play") && !data("stock_mode_table")
           && !(data("stock_mode_manager") && fn("stock_battle_running") && fn("stock_multiball_running"));
}

/* item 164: the plain-C titles' OTHER modes. Their framework keeps a bitset of game flags (JP The Pin 1.05:
 * set 0x152d60, write 0x152da8, get 0x152df8; the bitmap pointer at [0x594a40 + 4], its size in bits at
 * [0x4beff8]) and each mode's START sets a flag of its own (Stegosaurus 0x90860: flag 40) that its end clears.
 * The port names the flags (`value mode_flag_1` .. `mode_flag_32`, each mode's, read off its start function
 * in the build's stock table) and the bitmap (`data game_flags`, `value game_flags_at`, `data
 * game_flag_count`). Any of them set is one of the game's modes. */
static char stock_flags_what[64];

static int stock_flags_route(void)
{
    return data("game_flags") && pm_port_value("mode_flag_1", 0) > 0;
}

static int stock_flags(void)
{
    const unsigned char *bits;
    unsigned count, i, id;
    char name[20];
    bits = *(const unsigned char **)(unsigned long)(data("game_flags") + (unsigned)pm_port_value("game_flags_at", 4));
    if (!bits) return 0;
    count = data("game_flag_count") ? *(const unsigned *)(unsigned long)data("game_flag_count") : 0;
    for (i = 1; i <= 32; i++) {
        pm_snprintf(name, sizeof name, "mode_flag_%u", i);
        id = (unsigned)pm_port_value(name, 0);
        if (!id) break;
        if (count && id >= count) continue;
        if (bits[id >> 3] >> (id & 7) & 1) {
            pm_snprintf(stock_flags_what, sizeof stock_flags_what, "one of the game's modes (flag %u)", id);
            return 1;
        }
    }
    return 0;
}

/* item 165: the plain-C framework's LIVE RECORDS. Every timed mode's start on these builds begins by asking the
 * framework whether one of the mode's own records is alive - Beatles 1.29 0x1ac0e0(lo, hi), Aerosmith 1.15
 * 0x2e98fc, Guardians 1.14 0x186f08, Metallica 1.03 0x2b9290: a walk of the list of live records (its head at a
 * global, a u16 id at +0 of each, the next at +0x84) that answers 1 when an id in [lo, hi] is found - and refuses
 * to start while one is (Drive My Car asks about 192..193, Should Have Known Better 194..195, Ticket to Ride
 * 196..197, Super Scoring on Aerosmith 239..241). So the same question, asked by us, says the mode is running.
 * The port names the function (`site live_records`) and each mode's ids (`value mode_records_1` ..
 * `mode_records_32`: lo | hi << 16) with the mode's name (`text mode_records_name_N`). */
static char stock_records_what[80];

static int stock_records_route(void)
{
    return fn("live_records") && pm_port_value("mode_records_1", 0) > 0;
}

static int stock_records(void)
{
    unsigned i, v, lo, hi;
    char name[28];
    const char *label;
    for (i = 1; i <= 32; i++) {
        pm_snprintf(name, sizeof name, "mode_records_%u", i);
        v = (unsigned)pm_port_value(name, 0);
        if (!v) break;
        lo = v & 0xffffu;
        hi = v >> 16;
        if (((unsigned (*)(unsigned, unsigned))(unsigned long)fn("live_records"))(lo, hi)) {
            pm_snprintf(name, sizeof name, "mode_records_name_%u", i);
            label = pm_port_text(name);
            pm_snprintf(stock_records_what, sizeof stock_records_what, "one of the game's modes (%s)",
                        label ? label : name);
            return 1;
        }
    }
    return 0;
}

/* item 165: a title whose modes are C++ SINGLETONS with a running byte of their own (Uncanny X-Men LE 0.98:
 * eleven Mode_Shared objects, 0x644f68..0x647248, each start - the shared one at Mode_Shared::v[2] or the
 * mode's own - sets the object's byte +0x74 (Mode_Shared's +0x6c; it sits at +8), and the mode's stop
 * (its own v[3], through Mode_Shared::v[1]) and its completion check clear it). The port names each byte
 * (`data mode_running_1` .. `mode_running_32`) and the mode's name (`text mode_running_name_N`); any of them
 * non-zero is one of the game's modes. */
static char stock_bytes_what[80];

static int stock_bytes_route(void)
{
    return data("mode_running_1") != 0;
}

static int stock_bytes(void)
{
    unsigned i, at;
    char name[28];
    const char *label;
    for (i = 1; i <= 32; i++) {
        pm_snprintf(name, sizeof name, "mode_running_%u", i);
        at = data(name);
        if (!at) break;
        if (*(const unsigned char *)(unsigned long)at) {
            pm_snprintf(name, sizeof name, "mode_running_name_%u", i);
            label = pm_port_text(name);
            pm_snprintf(stock_bytes_what, sizeof stock_bytes_what, "one of the game's modes (%s)", label ? label : name);
            return 1;
        }
    }
    return 0;
}

/* item 165: a title whose modes are C++ RULE OBJECTS that answer for themselves (Elvira 1.13: its fifteen House
 * rules - NOTLD_Rule, TWOW_Rule .. - under the House manager, and its TransientRules - Dance Fever,
 * Scream Test ..). Each class overrides the running test at vtable slot `value mode_rule_slot` (15 on Elvira; the
 * House manager's own check 0xdbe60 and the rules walk 0xf489c both call it), so the byte behind it differs
 * from class to class. The port names each object (`data mode_rule_1` .. `mode_rule_32`, static objects) and the
 * mode's name (`text mode_rule_name_N`); the runtime calls the object's own test, as the game does. */
static char stock_objects_what[80];

static int stock_objects_route(void)
{
    return data("mode_rule_1") != 0 && pm_port_value("mode_rule_slot", 0) > 0;
}

static int stock_objects(void)
{
    unsigned i, obj, vt, f, slot = (unsigned)pm_port_value("mode_rule_slot", 0);
    char name[28];
    const char *label;
    for (i = 1; i <= 32; i++) {
        pm_snprintf(name, sizeof name, "mode_rule_%u", i);
        obj = data(name);
        if (!obj) break;
        vt = *(const unsigned *)(unsigned long)obj;
        f = vt ? ((const unsigned *)(unsigned long)vt)[slot] : 0;
        if (f && ((unsigned (*)(unsigned))(unsigned long)f)(obj)) {
            pm_snprintf(name, sizeof name, "mode_rule_name_%u", i);
            label = pm_port_text(name);
            pm_snprintf(stock_objects_what, sizeof stock_objects_what, "one of the game's modes (%s)", label ? label : name);
            return 1;
        }
    }
    return 0;
}

static int stock_balls(unsigned kinds)
{
    unsigned n;
    if (!pm_player()) return 0;
    stock_flags_what[0] = 0;
    stock_records_what[0] = 0;
    stock_bytes_what[0] = 0;
    stock_objects_what[0] = 0;
    if (stock_flags_route() && (kinds & (PM_STOCK_BATTLE | PM_STOCK_ANY)) && stock_flags())
        return (int)PM_STOCK_BATTLE;
    if (stock_records_route() && (kinds & (PM_STOCK_BATTLE | PM_STOCK_ANY)) && stock_records())
        return (int)PM_STOCK_BATTLE;
    if (stock_bytes_route() && (kinds & (PM_STOCK_BATTLE | PM_STOCK_ANY)) && stock_bytes())
        return (int)PM_STOCK_BATTLE;
    if (stock_objects_route() && (kinds & (PM_STOCK_BATTLE | PM_STOCK_ANY)) && stock_objects())
        return (int)PM_STOCK_BATTLE;
    n = ((unsigned (*)(void))(unsigned long)fn("balls_in_play"))() & 0xffu;
    return n >= 2 && (kinds & (PM_STOCK_MULTIBALL | PM_STOCK_ANY)) ? (int)PM_STOCK_MULTIBALL : 0;
}

int pm_stock_mode_running(unsigned kinds)
{
    static const struct { unsigned kind; const char *site; } Q[] = {
        { PM_STOCK_BATTLE, "stock_battle_running" },
        { PM_STOCK_MULTIBALL, "stock_multiball_running" },
        { PM_STOCK_ANY, "stock_any_running" },
    };
    static int said;
    unsigned i;
    int unknown = 0, r;
    if (!said) {
        said = 1;
        if (stock_generic_route())
            say("stock modes: can tell, from the game's mode table (%ld modes)", pm_port_value("stock_mode_count", 0));
        else if (stock_balls_route() && stock_flags_route())
            say("stock modes: can tell a multiball, from the game's balls in play, and its other modes, from their flags");
        else if (stock_balls_route() && stock_records_route())
            say("stock modes: can tell a multiball, from the game's balls in play, and its timed modes, from the "
                "framework's live records");
        else if (stock_balls_route() && stock_bytes_route())
            say("stock modes: can tell a multiball, from the game's balls in play, and its modes, from their own "
                "running bytes");
        else if (stock_balls_route() && stock_objects_route())
            say("stock modes: can tell a multiball, from the game's balls in play, and its modes, from their own "
                "rule objects");
        else if (stock_balls_route())
            say("stock modes: can tell a multiball, from the game's balls in play (not its other modes)");
        else say("stock modes: %s%s%s%s", data("stock_mode_manager") ? "can tell" : "this port cannot tell (no stock_mode_manager)",
            data("stock_mode_manager") && fn("stock_battle_running") ? " battle" : "",
            data("stock_mode_manager") && fn("stock_multiball_running") ? " multiball" : "",
            data("stock_mode_manager") && fn("stock_any_running") ? " any" : "");
    }
    if (stock_generic_route()) {
        stock_generic_on = 1;
        return stock_generic(kinds);
    }
    if (stock_balls_route()) return stock_balls(kinds);
    for (i = 0; i < sizeof Q / sizeof Q[0]; i++) {
        if (!(kinds & Q[i].kind)) continue;
        r = stock_query(Q[i].site);
        if (r > 0) return (int)Q[i].kind;
        if (r < 0) unknown = 1;
    }
    return unknown ? -1 : 0;
}

const char *pm_stock_mode_what(unsigned kind)
{
    if (kind && stock_generic_on && stock_generic_what[0]) return stock_generic_what;
    if ((kind & PM_STOCK_BATTLE) && stock_flags_what[0]) return stock_flags_what;
    if ((kind & PM_STOCK_BATTLE) && stock_records_what[0]) return stock_records_what;
    if ((kind & PM_STOCK_BATTLE) && stock_bytes_what[0]) return stock_bytes_what;
    if ((kind & PM_STOCK_BATTLE) && stock_objects_what[0]) return stock_objects_what;
    if ((kind & PM_STOCK_BATTLE) && stock_generic_on) return "one of the game's modes";
    if (kind & PM_STOCK_BATTLE) return "a battle";
    if (kind & PM_STOCK_MULTIBALL) return "a multiball";
    return kind ? "a stock mode" : "nothing";
}

/* PAD-347: the middle of the screen belongs to the game's mode. On David's Premium (2026-10-03) one of
 * our modes' title and line sat word for word on JET FIGHTER ATTACK's: both are drawn where the game's
 * own modes put theirs. Stern never shows two modes' words at once - one mode has the middle, the others
 * keep to their badges at the edge - so while one of the game's modes runs for the player up, ours step
 * aside. The game is asked at most every ASIDE_MS (up to three of its own queries), and the change is
 * logged once. A port that cannot tell answers 0, said once: there our modes keep their places. */
#define ASIDE_MS 200
static struct { int kind, said_cannot; unsigned long at; } aside;

int pm_aside(void)
{
    unsigned long now = pm_ms();
    int k;
    if (aside.at && now - aside.at < ASIDE_MS) return aside.kind;
    aside.at = now ? now : 1;
    k = pm_in_game() ? pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL | PM_STOCK_ANY) : 0;
    if (k < 0) {
        if (!aside.said_cannot) say("aside: this port cannot tell when the game's own modes run - our modes keep their places");
        aside.said_cannot = 1;
        k = 0;
    }
    if (k && !aside.kind)
        say("aside: %s is running - the middle of the screen is the game's, our modes keep to the edges",
            pm_stock_mode_what((unsigned)k));
    else if (!k && aside.kind)
        say("aside: the game's mode is over - our modes have the middle of the screen again");
    else if (k != aside.kind)
        say("aside: now %s", pm_stock_mode_what((unsigned)k));
    aside.kind = k;
    return k;
}

/* ---- PAD-347 / PAD-363: a mode that keeps the game's own modes from starting ------------------------------
 * David (2026-10-04): "make isolated modes like our own custom ones that prevent the stock modes from
 * starting", then "extend this kind of thinking to other games ... the levers built in for the user". A rule of
 * the game's starts one of its modes by calling the mode's START: on a C++ rule title a virtual at the title's
 * start slot (Godzilla 8, Deadpool 13), on a plain-C title the function that counts the mode's started audit.
 * The app reads every mode's start (and on C++ titles its static object) and name out of the game program
 * (game_mode_blocks.py) into the port: `site block_start_<id>`, `data block_obj_<id>` (C++ only), `text
 * block_name_<id>`. The runtime puts a veto on each named start (several C++ modes may share one: the object
 * tells them apart; a start with no object is one mode's own) and, while a mode of ours that asked runs, refuses
 * the start for the ids in that mode's list (`pm_block_list`, a mode file's `block_modes`) or, when it gave none,
 * the port's checked defaults (`text block_default <ids>`). A refused start never runs: the mode never begins,
 * and the rule that asked carries on. A multiball is never named (balls in a lock, a magnet: PAD-353). Ids are
 * 0-127 (D&D's map modes run to 70, Venom's to 91). */
#define BLOCK_IDS 128
#define BLOCK_WORDS (BLOCK_IDS / 32)
#define BLOCK_HOOKS 128
static const struct pm_mode *block_owner;
static unsigned block_mask[BLOCK_WORDS];      /* the ids the running block refuses */
static unsigned block_list[BLOCK_WORDS];      /* the asking mode's own list, set before it blocks (none = the defaults) */
static const struct pm_mode *block_list_by;
static unsigned block_said[BLOCK_WORDS];      /* the ids refused this hold */
static unsigned block_named[BLOCK_WORDS];     /* the ids whose start is hooked */
static unsigned block_obj[BLOCK_IDS];         /* each id's object (0: its start is its own, a plain-C title's) */
static unsigned char block_hook_of[BLOCK_IDS];/* each id's hook, + 1 */
static unsigned block_hooked[BLOCK_HOOKS];
static int block_n_hooked;
static int block_battles;                     /* the battle rule's shot handler is hooked (Godzilla) */
static unsigned block_battle_said;
static char block_who[40];                    /* the blocking mode's name, kept for the line when it has ended */

static int bm_has(const unsigned *m, unsigned id) { return id < BLOCK_IDS && (m[id >> 5] >> (id & 31) & 1u); }
static void bm_set(unsigned *m, unsigned id) { if (id < BLOCK_IDS) m[id >> 5] |= 1u << (id & 31); }
static int bm_count(const unsigned *m)
{
    int n = 0, i;
    unsigned id;
    for (i = 0; i < BLOCK_WORDS; i++)
        for (id = m[i]; id; id &= id - 1) n++;
    return n;
}

/* "21 23 70" (at most cap - 1 characters): the ids of m, for the log */
static void bm_text(const unsigned *m, char *out, unsigned cap)
{
    unsigned id, n = 0;
    out[0] = 0;
    for (id = 0; id < BLOCK_IDS && n + 5 < cap; id++)
        if (bm_has(m, id)) n += (unsigned)pm_snprintf(out + n, cap - n, n ? " %u" : "%u", id);
    if (!n) pm_snprintf(out, cap, "none");
}

/* `text block_default 21 23`: the ids a mode that lists none holds off, kept to the named ones */
static void block_defaults(unsigned *m)
{
    const char *s = pm_port_text("block_default");
    int i;
    for (i = 0; i < BLOCK_WORDS; i++) m[i] = 0;
    while (s && *s) {
        unsigned v = 0;
        int digits = 0;
        while (*s == ' ' || *s == ',' || *s == '\t') s++;
        while (*s >= '0' && *s <= '9') v = v * 10 + (unsigned)(*s++ - '0'), digits++;
        if (!digits) break;
        if (bm_has(block_named, v)) bm_set(m, v);
    }
}

static int on_block_start(unsigned *r, unsigned hook_n)
{
    unsigned id;
    if (!block_owner || running != block_owner || !pm_in_game()) return 0;
    for (id = 0; id < BLOCK_IDS; id++)          /* this start's mode: its object, or the start is its own */
        if (block_hook_of[id] == hook_n + 1 && bm_has(block_named, id) && (!block_obj[id] || block_obj[id] == r[0])) break;
    if (id >= BLOCK_IDS || !bm_has(block_mask, id)) return 0;   /* not one this mode holds off */
    if (!bm_has(block_said, id)) {
        char key[24];
        const char *nm;
        bm_set(block_said, id);
        pm_snprintf(key, sizeof key, "block_name_%u", id);
        nm = pm_port_text(key);
        say("block: the game's mode %u (%s) did not start - %s is running", id, nm ? nm : "?", block_who);
    }
    return 1;                                  /* refused: the mode's start never runs */
}

int pm_block_list(const unsigned char *ids, int n)
{
    int i;
    if (!(can & PM_CAN_BLOCK_GAME)) return 0;
    for (i = 0; i < BLOCK_WORDS; i++) block_list[i] = 0;
    for (i = 0; ids && i < n; i++)
        if (bm_has(block_named, ids[i])) bm_set(block_list, ids[i]);
    block_list_by = current;
    return 1;
}

int pm_block_game_modes(int on)
{
    char ids[200];
    int i, own;
    if (!(can & PM_CAN_BLOCK_GAME)) return 0;
    if (!on) {
        if (block_owner && (!current || block_owner == current)) {
            say("block: %s lets the game's modes start again", block_who);
            block_owner = 0;
        }
        return 1;
    }
    if (!running || running != current) return 0;
    block_owner = current;
    own = block_list_by == current && bm_count(block_list);
    if (own) for (i = 0; i < BLOCK_WORDS; i++) block_mask[i] = block_list[i];
    else block_defaults(block_mask);
    for (i = 0; i < BLOCK_WORDS; i++) block_said[i] = 0;
    block_battle_said = 0;
    pm_snprintf(block_who, sizeof block_who, "%s", mode_name(current, "a mode"));
    bm_text(block_mask, ids, sizeof ids);
    say("block: %s keeps the game's modes %s (%s) from starting while it runs%s", block_who, ids,
        own ? "its own list" : "the port's checked defaults",
        block_battles ? ", and the battle rule from lighting a battle or opening its select screen" : "");
    return 1;
}

/* PAD-347 (David: "what about when a ball goes in the scoop to select a mode? we should prevent that from
 * happening while in our own multiball modes"): the battle rule's SHOT HANDLER (`site block_battle_shots`,
 * RuleBattle::v[25], called with the shot mask in r2:r3) is where a lit ramp counts toward a battle and a
 * lit scoop opens the BATTLE SELECTION screen (it creates the process that waits for display effect 132).
 * While a mode of ours blocks, the handler is shown the shot without those bits (`value
 * block_battle_lo` / `block_battle_hi`: the Left and Right ramp, the scoop): the same path as a ramp
 * that is not lit and a scoop with no battle lit, so the scoop kicks the ball out as it always does
 * then. Nothing of the handler is skipped and nothing else it sees changes; a battle lit before the mode
 * stays lit for after it. */
static void on_battle_shots(unsigned *r)
{
    unsigned lo = (unsigned)pm_port_value("block_battle_lo", 0), hi = (unsigned)pm_port_value("block_battle_hi", 0);
    if (!block_owner || running != block_owner || !pm_in_game()) return;
    if (!(r[2] & lo) && !(r[3] & hi)) return;
    if (block_battle_said++ < 20)
        say("block: the battle rule did not see shot 0x%08x_%08x - %s is running (no battle lit, no select screen)",
            r[3], r[2], block_who);
    r[2] &= ~lo;
    r[3] &= ~hi;
}

/* PAD-363 (David's Premium, 2026-10-04: "overlapping text for saucer mode feedback under Ghidorah"): a rule of
 * the game's that is not one of its modes - no start to refuse - puts its own words on the screen from its
 * shot handler: Godzilla's Saucer Attack (RuleSaucerAttack::v[25]) counts the pop bumper toward lighting it
 * ("%d MORE TO LIGHT SAUCER ATTACK"), then runs on its own timer. So a port may name up to BLOCK_RULES more
 * shot handlers, `site block_rule_<n>` with `value block_rule_lo_<n>` / `block_rule_hi_<n>` (and `text
 * block_rule_name_<n>`), each shown the shot without those bits while a mode of ours blocks - as the battle
 * rule's is (above). The bits still reach every other rule (Godzilla's pops score through the saucer rule, so
 * they score nothing while a mode blocks; emulator, 2026-10-04). */
#define BLOCK_RULES 8
static int block_rules_on;                   /* how many are hooked */
static unsigned block_rule_said[BLOCK_RULES];

static void on_rule_shots(unsigned *r, unsigned n)
{
    char key[28];
    unsigned lo, hi;
    const char *nm;
    if (n >= BLOCK_RULES || !block_owner || running != block_owner || !pm_in_game()) return;
    pm_snprintf(key, sizeof key, "block_rule_lo_%u", n);
    lo = (unsigned)pm_port_value(key, 0);
    pm_snprintf(key, sizeof key, "block_rule_hi_%u", n);
    hi = (unsigned)pm_port_value(key, 0);
    if (!(r[2] & lo) && !(r[3] & hi)) return;
    if (block_rule_said[n]++ < 10) {
        pm_snprintf(key, sizeof key, "block_rule_name_%u", n);
        nm = pm_port_text(key);
        say("block: the game's %s did not see shot 0x%08x_%08x - %s is running", nm ? nm : "rule", r[3], r[2], block_who);
    }
    r[2] &= ~lo;
    r[3] &= ~hi;
}

/* a plain hook whose logger is told which (r1 = n), as hook_veto_n's */
typedef void (*hook_n_fn)(unsigned *regs, unsigned n);
static int hook_n(unsigned addr, hook_n_fn logger, unsigned n)
{
    unsigned *t;
    if (n > 255 || !hook(addr, (hook_fn)(void (*)(void))logger)) return 0;
    t = tramp + (tramp_used - 1) * 16;
    t[2] = 0xe3a01000u | n;   /* mov r1, #n */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    return 1;
}

/* every tick, from clip_tick: a block ends with the mode that asked for it */
static void block_tick(void)
{
    if (!block_owner || running == block_owner) return;
    say("block: %s ended - the game's modes may start again", block_who);
    block_owner = 0;
}

/* from the constructor: a veto on each start the port names (once per distinct start), each id's object */
static void block_arm(void)
{
    char name[24], ids[200], dflt[200];
    unsigned id, a, d[BLOCK_WORDS];
    int i, any = 0;
    for (id = 0; id < BLOCK_IDS && !any; id++) {
        pm_snprintf(name, sizeof name, "block_start_%u", id);
        if (site(name)) any = 1;
    }
    if (site("block_battle_shots") || site("block_rule_0")) any = 1;
    if (!any) return;                            /* a port without them: silent */
    for (id = 0; id < BLOCK_IDS; id++) {
        pm_snprintf(name, sizeof name, "block_start_%u", id);
        a = fn(name);                            /* 0: not named, or its words do not match this build */
        if (!a) continue;
        pm_snprintf(name, sizeof name, "block_obj_%u", id);
        for (i = 0; i < block_n_hooked && block_hooked[i] != a; i++) ;
        if (i == block_n_hooked) {
            /* PAD-363: a plain-C title's start reached through a table whose caller goes on as if the mode began
             * when it returns non-zero, and stops cleanly on 0 (The Beatles' songs), is refused with 0 */
            char ret[24];
            pm_snprintf(ret, sizeof ret, "block_ret_%u", id);
            if (block_n_hooked >= BLOCK_HOOKS ||
                !hook_veto_n(a, on_block_start, (unsigned)block_n_hooked, pm_port_value(ret, 1) == 0 ? 0u : 1u)) {
                say("block: the start of the game's mode %u (0x%08x) could not be hooked", id, a);
                continue;
            }
            block_hooked[block_n_hooked++] = a;
        } else if (!data(name)) {                /* a shared start tells its modes apart by their objects */
            say("block: mode %u shares a start but names no object - left alone", id);
            continue;
        }
        block_obj[id] = data(name);
        block_hook_of[id] = (unsigned char)(i + 1);
        bm_set(block_named, id);
    }
    if (fn("block_battle_shots") && (pm_port_value("block_battle_lo", 0) | pm_port_value("block_battle_hi", 0)))
        block_battles = hook(fn("block_battle_shots"), on_battle_shots);
    for (i = 0; i < BLOCK_RULES; i++) {          /* PAD-363: other rules' shot handlers */
        char lo[24], hi[24];
        pm_snprintf(name, sizeof name, "block_rule_%d", i);
        pm_snprintf(lo, sizeof lo, "block_rule_lo_%d", i);
        pm_snprintf(hi, sizeof hi, "block_rule_hi_%d", i);
        if (!fn(name) || !(pm_port_value(lo, 0) | pm_port_value(hi, 0))) continue;
        if (hook_n(fn(name), on_rule_shots, (unsigned)i)) block_rules_on++;
        else say("block: %s (0x%08x) could not be hooked", name, fn(name));
    }
    if (!bm_count(block_named) && !block_battles && !block_rules_on) {
        say("block: off - none of the named starts could be hooked");
        return;
    }
    can |= PM_CAN_BLOCK_GAME;
    bm_text(block_named, ids, sizeof ids);
    block_defaults(d);
    bm_text(d, dflt, sizeof dflt);
    say("block: on - a mode may keep %d of the game's modes from starting: %s (%d start(s) hooked; checked "
        "defaults %s)%s; %d other rule(s) shown fewer shots while it blocks", bm_count(block_named), ids,
        block_n_hooked, dflt,
        block_battles ? "; the battle rule's shot handler is hooked (no battle lit, no select screen while it blocks)" : "",
        block_rules_on);
}

/* ---- a multiball of the mode's own (item 167) ---------------------------------------------------
 * Every build shares the framework's ball code, and its multiballs go through ONE call of it (The
 * Beatles 1.29 0x1fd310, Godzilla Pro 1.15 0x398660; found on every build by its code, `site
 * multiball_serve`): serve balls until r0 are in play. Read off every caller in the 34 latest builds
 * and the game's own multiballs (armmbcall, 2026-09-26): r1 is 0 (a few titles pass a small id of
 * their own), r2 the ball save in ticks (the title's adjustment x 62; 0x138 = 5 s in the framework's
 * own add-a-ball), r3 a second span the framework keeps beside it (0xbb on every build but The
 * Beatles' own, which pass 0x136 / 0xf8 / 0x7c; `value multiball_arg3` overrides), then two zero
 * words on the stack. It answers 0 with no game in play (the mode mask's attract and tilt bits),
 * or when the ball manager has no trough to serve from, and 1 once its serving process is up.
 * The count of the balls in play is the framework's (`site balls_in_play`, the stack section). */
static int have_sites(const char *const *names);     /* the gate section, below */
static int multiball_ok(void)
{
    return (can & PM_CAN_MULTIBALL) != 0;
}

int pm_balls_in_play(void)
{
    if (!fn("balls_in_play")) return -1;
    return (int)(((unsigned (*)(void))(unsigned long)fn("balls_in_play"))() & 0xffu);
}

int pm_multiball_start(unsigned balls, unsigned ballsave_s)
{
    unsigned r, arg3;
    if (!multiball_ok() || !pm_in_game()) return 0;
    if (balls < 2) balls = 2;
    if (balls > 6) balls = 6;
    if (ballsave_s > 120) ballsave_s = 120;
    arg3 = (unsigned)pm_port_value("multiball_arg3", 0xbb);
    r = ((unsigned (*)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned))(unsigned long)fn("multiball_serve"))
            (balls, 0, ballsave_s * 62u, arg3, 0, 0);
    say("multiball: %u balls asked for (%d in play now), ball save %u s: the game %s", balls, pm_balls_in_play(),
        ballsave_s, r ? "is serving" : "refused");
    return r ? 1 : 0;
}

int pm_ball_save(unsigned seconds)
{
    unsigned r, arg3;
    int now = pm_balls_in_play();
    if (!multiball_ok() || !pm_in_game() || !seconds) return 0;
    if (seconds > 120) seconds = 120;
    if (now < 1) now = 1;                   /* a ball on its way to the plunger counts as the one in play */
    arg3 = (unsigned)pm_port_value("multiball_arg3", 0xbb);
    r = ((unsigned (*)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned))(unsigned long)fn("multiball_serve"))
            ((unsigned)now, 0, seconds * 62u, arg3, 0, 0);
    say("ball save: %u s with %d ball(s) in play: the game %s", seconds, now, r ? "is saving" : "refused");
    return r ? 1 : 0;
}

int pm_multiball_add(unsigned n, unsigned ballsave_s)
{
    int now = pm_balls_in_play();
    if (!multiball_ok() || now < 0 || !n) return 0;
    return pm_multiball_start((unsigned)now + n, ballsave_s);
}

static void multiball_arm(void)
{
    static const char *const mb_s[] = { "multiball_serve", "balls_in_play", 0 };
    if (!have_sites(mb_s)) return;
    can |= PM_CAN_MULTIBALL;
    say("multiball: a mode's own, through the game's serve at 0x%08x (arg3 0x%lx)", fn("multiball_serve"),
        pm_port_value("multiball_arg3", 0xbb));
}

/* ---- the magnet: a grab of the mode's own, with limits it cannot raise (PAD-381) --------------
 * David (2026-10-04): modes need "access to these controls" - the scoop, the magnet - "However, we
 * need guardrails on this since these are physical high voltage things and we can't be breaking
 * anything or causing any fires". So a mode asks for a grab of so many ms and nothing else: the
 * runtime picks the powers, clamps the time, decides whether it may, and lets go by itself.
 *
 * What the game does (Godzilla Pro 1.16; docs/plans/mode_coils.md has every address):
 *   - ControlCoil fires through ONE call, `site coil_fire` (0x402ff4): (device, pulse power, pulse ms,
 *     hold power, then on the stack hold ms and an x ms that is always 0). The board drives the pulse,
 *     then the hold, and the game counts the coil busy for exactly that long: a command ENDS BY
 *     ITSELF. An all-zero call is OFF (the coil service sends cmd 4d). Emulator-proven: hwshim's
 *     [coildrive] lines on the ball search's magnet, 255 for 350 ms then 50 for 5500 ms.
 *   - The magnet's powers and times are the operator's adjustments, read live by GodzillaMagnet::
 *     v[29..32]: the LO set, `value magnet_adj_draw_power` 363, `_draw_time` 364, `_hold_power` 365,
 *     `_hold_time` 366 (the adjustment table's own names); `value magnet_adj_disabled` 343 is GODZILLA
 *     MAGNET DISABLED (also the id the magnet's constructor keeps). `site adjustment` reads one.
 *   - The game's own grabs are PROCESSES (`text magnet_procs`: 363 started by the rules, 362 the
 *     Magna-Grab, 360 a timed pulse). Each loops a tick at a time until the game's conditions clear -
 *     a display still playing among them, which is how PAD-353's magnet stayed on - and while one
 *     exists GodzillaMagnet refuses its own fire and off. `site proc_exists` asks.
 *
 * THE GUARDRAILS, none of them the mode's to change:
 *   1. ONE BOUNDED COMMAND PER GRAB, never re-sent. The operator's draw power for the operator's draw
 *      time, then the operator's hold power for the rest of the grab, the whole clamped to
 *      MAGNET_MAX_MS. If everything here stops - the mode wedges, the tick stops, the game dies - the
 *      board lets go when that command runs out. The OFF at the deadline only makes it sooner.
 *   2. Only the running mode, only in a game (not attract, not tilted: pm_in_game), never with the
 *      magnet disabled, never while one of the game's magnet processes runs, never twice at once, not
 *      within MAGNET_COOL_MS of the last grab ending, at most MAGNET_PER_MIN grabs a minute.
 *   3. Let go on: the deadline (every tick), pm_magnet_release, the mode ending, the ball ending, the
 *      game ending or tilting.
 *   4. The game wins. A magnet process of the game's starting while ours holds makes ours give the
 *      magnet back at once; the game's own coil update then drives it (its grab, or off).
 * The device is the port's (`value magnet_dev`: 11 on Pro 1.16, 13 on LE 1.16) and must equal the
 * game's own magnet object's (`site magnet_get`, its device at +4), or nothing is armed.
 *
 * A GRAB IS A GAME PROCESS THAT CONTROLS THE MAGNET (2026-10-05). The first version fired from the
 * tick, and the emulator showed the game switching the magnet off 1 ms later, every time: ControlCoil
 * ::v[38] (0x4ffc8), the coil's update, which the game runs on events (a Godzilla target hit among
 * them), turns a coil OFF (v[54] -> v[58] -> cmd 4d) unless a game process CONTROLS it (the object's
 * +44 is that process's id) or an on-time was asked for through v[36]. The game's own grabs take
 * control from a process: `site coil_take` (0x5079c: coil, wait ticks; only inside a process) records
 * the running process at +44 and registers an exit hook that gives control back; `site coil_give`
 * (0x50860: coil, 1) clears it and runs v[38], which switches the coil off. So a grab here is a
 * process of ours, `value magnet_proc` (an id the game never uses), started with `site proc_create`
 * (create-if-absent: id, entry, flags 0): it takes control, sends the ONE bounded command, sleeps a
 * tick at a time (`site proc_sleep`) until its time is up or the runtime asks it to let go, and gives
 * control back - the game's own update then switches the magnet off. If the game KILLS it (a tilt or
 * the end of a ball kills every process without a protecting flag, and ours has none), the exit hook
 * gives control back and the magnet goes off the same way; the tick notices the process is gone. The
 * on-time path (v[36]) is NOT used: v[55] re-fires the operator's pulse and hold for as long as an
 * on-time is set, which is "held until told", not one bounded command. */
#define MAGNET_MAX_MS  5000u   /* the longest grab a mode may ask for, pulse included */
#define MAGNET_MIN_MS   100u
#define MAGNET_COOL_MS 3000u   /* from one grab's end to the next one's start */
#define MAGNET_PER_MIN    6u   /* grab starts in any 60 s */

struct magnet_cmd { unsigned draw_pwr, draw_ms, hold_pwr, hold_ms; };

/* The one command a grab of `ms` sends, from the operator's adjustments; 0 with *why when the
 * adjustments read as nothing a magnet would be driven with. (tests lift it verbatim) */
static int magnet_plan(unsigned ms, unsigned dp, unsigned dt, unsigned hp, struct magnet_cmd *c,
                       const char **why)
{
    if (ms < MAGNET_MIN_MS) ms = MAGNET_MIN_MS;
    if (ms > MAGNET_MAX_MS) ms = MAGNET_MAX_MS;
    if (!dp || dp > 255 || hp > 255) {
        *why = "the magnet's power adjustments read out of range";
        return 0;
    }
    if (dt > ms) dt = ms;                   /* the pulse is part of the grab, never extra */
    c->draw_pwr = dp;
    c->draw_ms = dt;
    c->hold_ms = ms - dt;
    c->hold_pwr = c->hold_ms ? hp : 0;
    if (!c->hold_pwr) c->hold_ms = 0;
    return 1;
}

/* Why a grab may not start now, or 0. `starts` holds the last MAGNET_PER_MIN start times (0 =
 * none). (tests lift it verbatim) */
static const char *magnet_refusal(int running_mode, int in_game, int disabled, int game_busy,
                                  unsigned long holding_until, unsigned long last_end, unsigned long now,
                                  const unsigned long starts[MAGNET_PER_MIN])
{
    unsigned i, recent = 0;
    if (!running_mode) return "only the running mode may grab";
    if (!in_game) return "no game is being played (attract or a tilt)";
    if (disabled) return "the operator has the magnet disabled";
    if (game_busy) return "the game's own magnet is working";
    if (holding_until) return "a grab is already holding";
    if (last_end && now - last_end < MAGNET_COOL_MS) return "the last grab ended less than 3 s ago";
    for (i = 0; i < MAGNET_PER_MIN; i++)
        if (starts[i] && now - starts[i] < 60000ul) recent++;
    if (recent >= MAGNET_PER_MIN) return "six grabs in the last minute already";
    return 0;
}

/* ---- held coils: the magnet and the port's other coils of the same kind (PAD-381) --------------
 * A Godzilla Premium has three coils a mode may HOLD the same way: the Godzilla magnet, the Mechagodzilla
 * magnet and the bridge diverter - each a ControlCoil object of the game's, each fired by the game as a
 * pulse then a hold (the bridge: 255 for 300 ms, then 25 for up to 5500 ms). The port names them, `text
 * held_coils` (default "magnet"), and for each <name>: `site <name>_get` (the game's getter for its
 * object), `value <name>_dev` (its device, checked against the object's on the first hold), and for the
 * magnet `text magnet_procs` (the game's own magnet processes).
 *
 * Every coil gets the guardrails above, the same code: ONE bounded command (the object's own pulse power
 * for its own pulse time, then its own hold power, the whole clamped to MAGNET_MAX_MS), sent from a game
 * process of ours that takes control of it (`value magnet_proc` + the coil's index) and gives control back
 * at the end; the limits per coil (one at a time, MAGNET_COOL_MS between holds, MAGNET_PER_MIN a minute);
 * refused while the operator has it disabled (the object's v[40]) and while the GAME uses it - a process
 * of the game's controls it (+44), the game asked for an on-time (+36, v[36]: its rules' grabs), or one of
 * the game's processes the port names runs - and given back at once when the game wants it mid-hold.
 * The powers are read from the object (v[29] pulse power, v[30] pulse ms, v[31] hold power): what the game
 * itself would fire it with now (the Godzilla magnet's LO/HI settings, the Mechagodzilla magnet's
 * adjustments 380-383, the bridge's own constants). */
#define COILS_MAX 4

struct held_coil {
    char name[16];
    unsigned dev, obj, id;                  /* the port's device, the game's object, our process's id */
    unsigned long until;                    /* pm_ms() the hold ends; 0 = not holding */
    unsigned long started, ended;
    unsigned long starts[MAGNET_PER_MIN];
    unsigned next;
    struct magnet_cmd cmd;                  /* what the process sends */
    int proc;                               /* our process holds control of the coil */
    int release;                            /* the runtime asked it to let go */
    int checked;                            /* the device check: 0 not yet, 1 matches, -1 does not */
    const char *why;                        /* ... and why */
};
static struct held_coil coils[COILS_MAX];
static int n_coils;

static int proc_alive(unsigned id)
{
    return (((unsigned (*)(unsigned))(unsigned long)fn("proc_exists"))(id) & 0xffu) != 0;
}

static struct held_coil *coil_named(const char *name)
{
    int i;
    for (i = 0; i < n_coils; i++)
        if (name && str_eq(coils[i].name, name)) return &coils[i];
    return 0;
}

/* The object's virtual `slot`, called with the object (ControlCoil's: v[29] pulse power, v[30] pulse ms,
 * v[31] hold power, v[40] disabled) */
static unsigned coil_virtual(unsigned obj, unsigned slot)
{
    unsigned vt = *(const unsigned *)(unsigned long)obj;
    return ((unsigned (*)(unsigned))(unsigned long)(*(const unsigned *)(unsigned long)(vt + 4u * slot)))(obj);
}

/* Is the GAME using this coil: a process of its own controls it, it asked for an on-time, or one of the
 * game's processes the port names for it runs? */
static int coil_game_busy(const struct held_coil *c)
{
    char key[40];
    const char *t;
    unsigned id, ctl;
    if (c->obj) {
        ctl = *(const unsigned short *)(unsigned long)(c->obj + 44);
        if (ctl && ctl != c->id) return 1;
        if (*(const unsigned *)(unsigned long)(c->obj + 36)) return 1;
    }
    pm_snprintf(key, sizeof key, "%s_procs", c->name);
    t = pm_port_text(key);
    while (t && *t) {
        while (*t == ' ') t++;
        for (id = 0; *t >= '0' && *t <= '9'; t++) id = id * 10 + (unsigned)(*t - '0');
        if (id && proc_alive(id)) return 1;
        while (*t && *t != ' ') t++;
    }
    return 0;
}

static void magnet_send(const struct held_coil *c, unsigned p1, unsigned t1, unsigned p2, unsigned t2)
{
    ((unsigned (*)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned))(unsigned long)fn("coil_fire"))
        (c->dev, p1, t1, p2, t2, 0);
}

static void magnet_done(struct held_coil *c)
{
    c->proc = 0;
    c->release = 0;
    c->until = 0;
    c->ended = pm_ms();
}

/* THE HOLD, as a game process (the game's scheduler runs it on its own stack, like the game's own magnet
 * processes; it ends by returning). It takes control, sends the ONE bounded command, waits a tick at a
 * time, and gives control back: the game's coil update then switches the coil off. */
static void magnet_proc(struct held_coil *c)
{
    unsigned long sent;
    unsigned total = c->cmd.draw_ms + c->cmd.hold_ms;
    if (!c->until || c->release) {
        say("%s: let go before the hold began (%s)", c->name, c->why ? c->why : "asked to");
        magnet_done(c);
        return;
    }
    if (!(((unsigned (*)(unsigned, unsigned))(unsigned long)fn("coil_take"))(c->obj, 0) & 0xffu)) {
        say("%s: no hold - a process of the game's controls it", c->name);
        magnet_done(c);
        return;
    }
    c->proc = 1;
    magnet_send(c, c->cmd.draw_pwr, c->cmd.draw_ms, c->cmd.hold_pwr, c->cmd.hold_ms);
    sent = pm_ms();
    c->until = sent + total;                /* the deadline counts from the command itself */
    say("%s: holding - process %u controls it; ONE command: draw %u/255 for %u ms, then hold %u/255 for %u "
        "ms, which the board ends by itself", c->name, c->id, c->cmd.draw_pwr, c->cmd.draw_ms, c->cmd.hold_pwr,
        c->cmd.hold_ms);
    while (!c->release && pm_ms() < c->until)
        ((void (*)(unsigned))(unsigned long)fn("proc_sleep"))(1);
    ((unsigned (*)(unsigned, unsigned))(unsigned long)fn("coil_give"))(c->obj, 1);
    say("%s: let go - %s, after %lu ms (%ld ms before the command's own end); control given back, the "
        "game's coil update switches it off", c->name, c->release && c->why ? c->why : "its time ran out",
        pm_ms() - sent, (long)(c->until - pm_ms()));
    magnet_done(c);
}

/* one process entry per coil: the game's create passes its entry no argument */
static void coil_proc0(void) { magnet_proc(&coils[0]); }
static void coil_proc1(void) { magnet_proc(&coils[1]); }
static void coil_proc2(void) { magnet_proc(&coils[2]); }
static void coil_proc3(void) { magnet_proc(&coils[3]); }
static void (*const coil_procs[COILS_MAX])(void) = { coil_proc0, coil_proc1, coil_proc2, coil_proc3 };

/* Ask a hold to let go: the process gives control back on its next wake, within a tick. */
static void coil_let_go(struct held_coil *c, const char *why)
{
    if (!c->until || c->release) return;
    c->release = 1;
    c->why = why;
}

static void magnet_let_go(const char *why)  /* every held coil (the mode ended, the ball ended) */
{
    int i;
    for (i = 0; i < n_coils; i++) coil_let_go(&coils[i], why);
}

/* The port's device against the game's object, once, on the first hold: not at arm time, which is before
 * the game's main() has run (the objects are built on first use). A mismatch takes that coil away. */
static int coil_device_ok(struct held_coil *c)
{
    char key[40];
    unsigned obj, dev;
    if (c->checked) return c->checked > 0;
    pm_snprintf(key, sizeof key, "%s_get", c->name);
    obj = ((unsigned (*)(void))(unsigned long)fn(key))();
    dev = obj && maps_has(obj + 4, 2, MAP_R) ? *(const unsigned short *)(unsigned long)(obj + 4) : 0xffffu;
    if (dev != c->dev) {
        c->checked = -1;
        say("%s: switched OFF for this run - the game's object is device %u, the port says %u", c->name, dev,
            c->dev);
        return 0;
    }
    c->obj = obj;
    c->checked = 1;
    say("%s: the game's object is device %u, as the port says", c->name, dev);
    return 1;
}

int pm_coil_hold(const char *name, unsigned ms)
{
    struct held_coil *c = coil_named(name);
    unsigned long now = pm_ms();
    struct magnet_cmd cmd;
    const char *why;
    if (!(can & PM_CAN_COILS) || !c || !coil_device_ok(c)) return 0;
    why = magnet_refusal(pm_running(), pm_in_game(), (coil_virtual(c->obj, 40) & 0xffu) != 0,
                         coil_game_busy(c), c->until, c->ended, now, c->starts);
    if (!why && proc_alive(c->id)) why = "the last hold's process is still ending";
    if (!why)
        magnet_plan(ms, coil_virtual(c->obj, 29) & 0xffu, coil_virtual(c->obj, 30) & 0xffffu,
                    coil_virtual(c->obj, 31) & 0xffu, &cmd, &why);
    if (why) {
        say("%s: no hold - %s", c->name, why);
        return 0;
    }
    c->cmd = cmd;
    c->release = 0;
    c->why = 0;
    c->started = now;
    c->until = now + cmd.draw_ms + cmd.hold_ms;
    if (!((unsigned (*)(unsigned, void (*)(void), unsigned))(unsigned long)fn("proc_create"))(
            c->id, coil_procs[c - coils], 0)) {
        c->until = 0;
        say("%s: no hold - the game would not start its process %u", c->name, c->id);
        return 0;
    }
    c->starts[c->next++ % MAGNET_PER_MIN] = now;
    say("%s: HOLD for %u ms (asked %u) - process %u takes control of it and sends ONE command", c->name,
        cmd.draw_ms + cmd.hold_ms, ms, c->id);
    return 1;
}

void pm_coil_release(const char *name)
{
    struct held_coil *c = coil_named(name);
    if (c && pm_running()) coil_let_go(c, "the mode let go");
}

int pm_coil_holding(const char *name)
{
    struct held_coil *c = coil_named(name);
    return c && c->until != 0;
}

int pm_coil_known(const char *name)
{
    struct held_coil *c = coil_named(name);
    return (can & PM_CAN_COILS) && c && c->checked >= 0;
}

int pm_magnet_grab(unsigned ms) { return pm_coil_hold("magnet", ms); }
void pm_magnet_release(void) { pm_coil_release("magnet"); }
int pm_magnet_holding(void) { return pm_coil_holding("magnet"); }

/* Every tick, each coil: the game taking over, ending or killing the hold, and the deadline (the process
 * checks that too). A hold whose process is gone was ended by the game (a tilt or the end of a ball kills
 * it): its exit hook gave control back, which switched the coil off. */
static void magnet_tick(void)
{
    int i;
    for (i = 0; i < n_coils; i++) {
        struct held_coil *c = &coils[i];
        if (!c->until) continue;
        if (!proc_alive(c->id)) {
            if (c->proc || pm_ms() - c->started > 1000ul) {
                say("%s: the hold's process is gone (the game ended it) - its exit gave control back", c->name);
                magnet_done(c);
            }
            continue;
        }
        if (c->release) continue;           /* the process is letting go */
        if (coil_game_busy(c)) coil_let_go(c, "the game wants it");
        else if (pm_ms() >= c->until) coil_let_go(c, "its time ran out");
        else if (!pm_in_game()) coil_let_go(c, "the game ended or tilted");
        else if (!running) coil_let_go(c, "no mode is running");
    }
}

static int have_values(const char *const *names);   /* the gate section, below */
static void coils_arm(void)
{
    static const char *const s[] = { "coil_fire", "proc_exists", "proc_create", "proc_sleep", "coil_take",
                                     "coil_give", 0 };
    static const char *const v[] = { "magnet_proc", 0 };
    const char *t = pm_port_text("held_coils");
    char key[40];
    unsigned base;
    if (!have_sites(s) || !have_values(v)) return;
    base = (unsigned)pm_port_value("magnet_proc", 0) & 0xffffu;
    if (!t) t = "magnet";
    while (*t && n_coils < COILS_MAX) {
        struct held_coil *c = &coils[n_coils];
        unsigned k = 0;
        while (*t == ' ') t++;
        while (*t && *t != ' ' && k + 1 < sizeof c->name) c->name[k++] = *t++;
        c->name[k] = 0;
        while (*t && *t != ' ') t++;
        if (!k) break;
        pm_snprintf(key, sizeof key, "%s_get", c->name);
        if (!fn(key)) { say("%s: the port names no %s - not armed", c->name, key); continue; }
        pm_snprintf(key, sizeof key, "%s_dev", c->name);
        c->dev = (unsigned)pm_port_value(key, 0);
        if (!c->dev) { say("%s: the port names no %s - not armed", c->name, key); continue; }
        c->id = base + (unsigned)n_coils;
        n_coils++;
    }
    if (!n_coils) return;
    can |= PM_CAN_COILS;
    say("held coils: %d (%s%s%s%s%s%s%s) through 0x%08x by processes %u..; each at most %u ms as one command, %u s "
        "between holds, %u a minute", n_coils, coils[0].name, n_coils > 1 ? " " : "", n_coils > 1 ? coils[1].name : "",
        n_coils > 2 ? " " : "", n_coils > 2 ? coils[2].name : "", n_coils > 3 ? " " : "",
        n_coils > 3 ? coils[3].name : "", fn("coil_fire"), base, MAGNET_MAX_MS, MAGNET_COOL_MS / 1000, MAGNET_PER_MIN);
}

/* ---- the scoop: a ball held there for the mode, then the game kicks it out (PAD-381) ----------
 * David (2026-10-04): "putting the ball in the scoop during a mode". A mode may HOLD a ball that lands
 * in the scoop for a while - its screen, a callout - and nothing else: the kick-out stays the game's
 * own, at the operator's SCOOP KICK POWER, with the game's own retries. No coil is ever fired here.
 *
 * What the game does (Godzilla Pro 1.16; docs/plans/mode_coils.md): the scoop is a ball device of the
 * framework's, which runs it in a game process and calls the GAME's handler for it (`site
 * scoop_handler`, 0x7cd94, the program names it right_scoop_event_handler) through a pointer in the
 * device's record (`data scoop_slot`, 0x74b480, RW data) with an event number in r0. Measured on a
 * landing ball (a call probe, 2026-10-05): 21 the switch closed; 2 at +0.8 s, the ball has settled -
 * the game's own hold (its rules, a battle's select screen) loops in there and returns when it is
 * done; 13 a short wait for a display; 16 and 17 at +1.7 s, the kick (coil_fire(10, adj 351, 64 ms),
 * every adj-352th retry a burst of five); 18 the ball left.
 *
 * So the hold WRAPS event 2 (`value scoop_event`): the record's pointer is swapped for scoop_wrap on
 * the first tick (checked to be the handler first), which runs the game's handler as it was and THEN,
 * if the running mode asked for a hold, sleeps a tick at a time in the device's own process until the
 * time is up, the mode lets go or ends, or the game ends or tilts - and returns, so the game's eject
 * goes on exactly as before. The game's own hold always comes first. A process the game ends (a tilt)
 * unwinds through this frame, which build_mode.sh's -funwind-tables makes safe.
 *
 * The limits, not the mode's to change: 100 ms to SCOOP_MAX_MS a hold; only the running mode, only in
 * a game; the hold ends with the mode. Holding a ball powers nothing; the cap keeps a ball from waiting
 * in the scoop long enough for the game to start looking for it. */
#define SCOOP_MAX_MS 10000u
#define SCOOP_MIN_MS   100u

static struct {
    unsigned slot;                          /* the device record's handler pointer */
    unsigned (*orig)(unsigned, unsigned, unsigned, unsigned);
    unsigned event;                         /* the event a settled ball is held in */
    unsigned hold_ms;                       /* the running mode's hold; 0 = none */
    unsigned long until;                    /* pm_ms() a hold ends; 0 = not holding */
    int release;                            /* the mode let go */
    int armed;                              /* 0 not swapped yet, 1 wrapped, -1 refused */
} scoop;

static unsigned scoop_wrap(unsigned ev, unsigned a1, unsigned a2, unsigned a3)
{
    unsigned r = scoop.orig(ev, a1, a2, a3);
    unsigned long t0;
    const char *why;
    if (ev != scoop.event || !scoop.hold_ms || !running || !pm_in_game()) return r;
    t0 = pm_ms();
    scoop.until = t0 + scoop.hold_ms;
    scoop.release = 0;
    say("scoop: a ball settled - holding it %u ms for the mode; then the game kicks it out", scoop.hold_ms);
    while (!scoop.release && scoop.hold_ms && running && pm_in_game() && pm_ms() < scoop.until)
        ((void (*)(unsigned))(unsigned long)fn("proc_sleep"))(1);
    why = scoop.release ? "the mode let go" : !scoop.hold_ms || !running ? "the mode ended"
        : !pm_in_game() ? "the game ended or tilted" : "its time ran out";
    say("scoop: let go after %lu ms (%s) - the game kicks it out", pm_ms() - t0, why);
    scoop.until = 0;
    scoop.release = 0;
    return r;
}

int pm_scoop_hold(unsigned ms)
{
    if (!(can & PM_CAN_SCOOP) || !pm_running()) return 0;
    if (ms && ms < SCOOP_MIN_MS) ms = SCOOP_MIN_MS;
    if (ms > SCOOP_MAX_MS) ms = SCOOP_MAX_MS;
    scoop.hold_ms = ms;
    if (!ms) scoop.release = 1;
    say("scoop: %s", ms ? "a ball that lands in the scoop is held for the mode" : "no hold");
    return 1;
}

void pm_scoop_release(void)
{
    if (pm_running() && scoop.until) scoop.release = 1;
}

int pm_scoop_holding(void) { return scoop.until != 0; }

static void scoop_let_go(void)
{
    scoop.hold_ms = 0;                      /* the hold loop sees it on its next tick */
}

/* The first tick (the game's main() has run): swap the record's pointer, once, if it still points at the
 * game's handler. Then, every tick: a hold whose process the game ended is not waited for. */
static void scoop_tick(void)
{
    unsigned *slot;
    if (!(can & PM_CAN_SCOOP)) return;
    if (!scoop.armed) {
        slot = (unsigned *)(unsigned long)scoop.slot;
        if (!maps_has(scoop.slot, 4, MAP_R | MAP_GAME) || *slot != fn("scoop_handler")) {
            scoop.armed = -1;
            can &= ~PM_CAN_SCOOP;
            say("scoop: switched OFF for this run - the device record at 0x%08x does not point at the "
                "handler 0x%08x", scoop.slot, fn("scoop_handler"));
            return;
        }
        scoop.orig = (unsigned (*)(unsigned, unsigned, unsigned, unsigned))(unsigned long)*slot;
        *slot = (unsigned)(unsigned long)scoop_wrap;
        scoop.armed = 1;
        say("scoop: its handler 0x%08x is wrapped (event %u holds a ball for the mode)", fn("scoop_handler"),
            scoop.event);
    }
    if (scoop.until && pm_ms() > scoop.until + 2000ul) scoop.until = 0;   /* the game ended that process */
}

static void scoop_arm(void)
{
    static const char *const s[] = { "scoop_handler", "proc_sleep", 0 };
    static const char *const d[] = { "scoop_slot", 0 };
    static const char *const v[] = { "scoop_event", 0 };
    if (!have_sites(s) || !have_data(d) || !have_values(v)) return;
    scoop.slot = data("scoop_slot");
    scoop.event = (unsigned)pm_port_value("scoop_event", 2);
    can |= PM_CAN_SCOOP;
    say("scoop: a mode may hold a ball there, up to %u ms; the kick-out stays the game's", SCOOP_MAX_MS);
}

/* ---- the shield platform (PAD-379) --------------------------------------------------------------
 * Godzilla Premium's ShieldMotor (the port's shield lines): one object, a SingleDirectionCoilMotor that
 * runs its coil one way until the position switch it was sent to closes. shield_move(motor, position
 * switch) is the motor's own go-to: 0 when the operator switched the motor off, 1 when it is there or a
 * move process has started (the target at +shield_target_at, +shield_pos_at the switch on arrival, 0
 * before the motor has found itself). The motor is asked only while the object carries the port's
 * vtable word: a build whose object is elsewhere, or not built yet, is refused rather than called. */
static unsigned shield_obj(void)
{
    unsigned obj = data("shield_motor");
    if (!(can & PM_CAN_SHIELD) || !obj) return 0;
    if (*(const unsigned *)(unsigned long)obj != (unsigned)pm_port_value("shield_motor_vptr", 0)) return 0;
    return obj;
}

static unsigned shield_switch(int where)
{
    return (unsigned)pm_port_value(where == PM_SHIELD_TOWARD ? "shield_toward" : "shield_away", 0);
}

static unsigned shield_field(unsigned obj, const char *at, long fallback)
{
    return *(const unsigned short *)(unsigned long)(obj + (unsigned)pm_port_value(at, fallback));
}

int pm_shield(int where)
{
    unsigned obj = shield_obj(), sw, was, r;
    if (!obj || (where != PM_SHIELD_AWAY && where != PM_SHIELD_TOWARD)) return 0;
    sw = shield_switch(where);
    was = shield_field(obj, "shield_pos_at", 44);
    r = ((unsigned (*)(unsigned, unsigned))(unsigned long)fn("shield_move"))(obj, sw) & 0xffu;
    say("shield: %s (switch %u) from switch %u: %s", where == PM_SHIELD_TOWARD ? "TOWARD the player" : "AWAY", sw,
        was, !r ? "the motor REFUSED (switched off in the adjustments?)" : was == sw ? "already there" : "turning");
    return r ? 1 : 0;
}

int pm_shield_position(void)
{
    unsigned obj = shield_obj(), at, to;
    if (!obj) return -1;
    at = shield_field(obj, "shield_pos_at", 44);
    to = shield_field(obj, "shield_target_at", 48);
    if (to && at != to) return 0;                       /* on its way somewhere else (or its move failed) */
    return at == shield_switch(PM_SHIELD_TOWARD) ? PM_SHIELD_TOWARD :
           at == shield_switch(PM_SHIELD_AWAY) ? PM_SHIELD_AWAY : 0;
}

static void shield_arm(void)
{
    static const char *const s[] = { "shield_move", 0 };
    static const char *const d[] = { "shield_motor", 0 };
    static const char *const v[] = { "shield_motor_vptr", "shield_pos_at", "shield_target_at", "shield_away",
                                     "shield_toward", 0 };
    if (!site("shield_move")) return;                    /* a port without a platform (a Pro): silent */
    if (!have_sites(s) || !have_data(d) || !have_values(v)) {
        say("shield: off - the port's shield lines are incomplete or do not match this build");
        return;
    }
    can |= PM_CAN_SHIELD;
    say("shield: a mode may turn the shield platform (motor 0x%08x, move 0x%08x; away = switch %ld, toward = %ld)",
        data("shield_motor"), fn("shield_move"), pm_port_value("shield_away", 0), pm_port_value("shield_toward", 0));
}

/* ---- the game's own rules: a shot that COUNTS AS one of theirs (item 160) ------------ STOCK BEGIN
 * A rule the game shipped with (a battle, a multiball) is a compiled object with a vtable, and
 * its SHOT HANDLER (one vtable slot) tests the RAW shot mask against fixed bits: Godzilla's
 * battle vs Ebirah counts a spin only when the dispatch carries 0x200 (its left spinner's
 * middle bit), and does nothing with any other bit, lit or not (item 158, emulator-proven).
 * So a shot the rule does not know can never count for it by data alone: it has to ARRIVE
 * as the bit the rule tests. This section does that, and nothing more:
 *
 *   - The PORT names each rule (`rule <id> <vtable> <label>`), the manager's get function
 *     (`site stock_rule_get`, its first two words checked like every site), the manager
 *     (`data stock_mode_manager`) and the slot numbers of this build (`value stock_slot_shot`,
 *     the handler; `stock_slot_active`; `stock_field`, the per-player lit mask's offset).
 *   - A TABLE of rows {rule, from shot, to shot} comes from stock.cfg beside the mode files
 *     (/usr/local/padmode/stock.cfg on a card, /dump/stock.cfg in the rig), re-read twice a
 *     second and re-parsed when its bytes change, so an edit lands in a running game; or from
 *     C through pm_stock_counts_as() (item 161 builds on the same wrap).
 *   - A rule a row names gets its shot slot WRAPPED, once, the way stock_probe.c wraps it:
 *     the vtable word is replaced by our function, which calls the original with r0..r3 and
 *     four stack words passed through. It is wrapped only when the object's vtable pointer is
 *     the port's word for that rule, so a port for another build wraps nothing.
 *   - In the wrap: a dispatch whose bits are all inside a row's `from` is REPLACED by the row's
 *     `to` bit - never ORed in - and only while that bit is lit in the rule's per-player mask.
 *     Once the rule clears it (Ebirah at a spinner's last spin), the shot passes through
 *     unchanged, so a finished target never receives its bit again (a second decrement past 0
 *     would leave the battle unwinnable: item 158's check). `to` must be ONE bit (Ebirah tests
 *     0x200 exactly; the tank matches a position by 64-bit equality). An empty table, or a file
 *     that is gone, passes every shot through: the rule plays stock.
 *   - While the target bit is lit, the `from` shot's inserts are HELD with the lamp layer of
 *     this section's own (pm_lamp_*, priority 255) in the row's colour and blink (Ebirah's
 *     yellow, 300 ms on / 200 ms off by default), and handed back when the bit clears or the
 *     rule stops. The rule's own lamp table (full, 6 entries on Ebirah) is not touched.
 *
 * Threads: the wrap runs on the game's thread that dispatches shots; the table is a pointer
 * swapped on the tick after a full rebuild (two buffers), so the wrap never sees a half-written
 * row. The lit check reads the u64 field the rule itself writes.
 * One ramp = one spin: a ramp standing in for a spinner needs the spinner's count of hits
 * (Ebirah: 15 on the left spinner) unless the count word is lowered (item 159). */
#define N_STOCK_RULES   8
#define STOCK_ROWS      16
#define STOCK_C_ROWS    8
#define STOCK_FILE_MAX  4096
#define STOCK_SAY_MAX   600
#define STOCK_LINE_MAX  160

typedef uint64_t (*stock_vfn8)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);
typedef uint64_t (*stock_vfn1)(unsigned);
static const char *const STOCK_FILES[] = { "/usr/local/padmode/stock.cfg", "/dump/stock.cfg" };

struct stock_rule {
    unsigned id, vt, obj;
    char label[40];
    int wrapped, refused;
    stock_vfn8 orig;                /* the slot's function before our wrap (a probe's wrap, maybe) */
    pm_stock_shot_fn fn;            /* item 161: a C hook that sees every shot first, or 0 */
    const struct pm_mode *fn_by;
    int lit;                        /* the from-shot's inserts are held now */
    uint64_t lit_from;
    unsigned remaps, passes;        /* counted, for the log */
    const struct pm_stock_handler *h161;   /* item 161: the record from the pm_stock section, or 0 */
    stock_vfn8 orig_start, orig_stop;      /* item 161: the START / STOP slots before our wraps */
    int wrapped_start, wrapped_stop, in_original;   /* in_original: a replay of the game's handler is running */
};

struct stock_row { unsigned rule; uint64_t from, to; unsigned rgb, ms, on_ms; int pattern; int from_c; };
struct stock_table { unsigned n; struct stock_row row[STOCK_ROWS]; };

static struct stock_rule stock_rules[N_STOCK_RULES];
static int n_stock_rules;
static struct stock_table stock_tab[2];
static struct stock_table *volatile stock_live = &stock_tab[0];
static int stock_tab_i;
static struct stock_row stock_file_rows[STOCK_ROWS], stock_c_rows[STOCK_C_ROWS];
static unsigned n_stock_file_rows, n_stock_c_rows;
static struct { unsigned rule, rgb, ms, on_ms; int pattern, set; } stock_lights[N_STOCK_RULES];
static char stock_raw[STOCK_FILE_MAX];
static long stock_raw_len = -1;
static int stock_file_which = -1, stock_says, stock_armed;
static const struct pm_mode stock_mode = { .name = "stock" };   /* the holder of this section's inserts */
static int stock161_first(struct stock_rule *x, uint64_t *shot, unsigned s0);   /* item 161, below */
static void stock161_attach(void);

static void stock_say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void stock_say(const char *fmt, ...)
{
    va_list ap;
    if (stock_says >= STOCK_SAY_MAX) return;
    if (++stock_says == STOCK_SAY_MAX) { say("stock: that is %d lines; no more stock lines this boot", STOCK_SAY_MAX); return; }
    va_start(ap, fmt);
    log_raw("pad", fmt, ap);
    va_end(ap);
}

/* `rule <id> <vtable> <label to the end of the line>` */
static void rule_line(const char *s)
{
    struct stock_rule *x;
    int ok = 0;
    unsigned id, vt;
    if (n_stock_rules >= N_STOCK_RULES) { port.dropped++; return; }
    id = (unsigned)number(&s, &ok);
    if (!ok) return;
    vt = (unsigned)number(&s, &ok);
    if (!ok || !vt) return;
    x = &stock_rules[n_stock_rules];
    x->id = id;
    x->vt = vt;
    rest(s, x->label, sizeof x->label);
    {
        unsigned i;
        for (i = 0; x->label[i]; i++)                          /* a trailing comment is not the label */
            if (x->label[i] == '#' && i && (x->label[i - 1] == ' ' || x->label[i - 1] == '\t')) {
                while (i && (x->label[i - 1] == ' ' || x->label[i - 1] == '\t')) i--;
                x->label[i] = 0;
                break;
            }
    }
    if (!x->label[0]) pm_snprintf(x->label, sizeof x->label, "rule %u", id);
    n_stock_rules++;
}

static struct stock_rule *stock_rule(unsigned id)
{
    int i;
    for (i = 0; i < n_stock_rules; i++)
        if (stock_rules[i].id == id) return &stock_rules[i];
    return 0;
}

static struct stock_rule *stock_find(unsigned self)
{
    int i;
    for (i = 0; i < n_stock_rules; i++) if (stock_rules[i].wrapped && stock_rules[i].obj == self) return &stock_rules[i];
    for (i = 0; i < n_stock_rules; i++) if (stock_rules[i].wrapped && stock_rules[i].vt == *(const unsigned *)(unsigned long)self) return &stock_rules[i];
    return 0;
}

static unsigned *stock_vtab(const struct stock_rule *x) { return (unsigned *)(unsigned long)x->vt; }
static int stock_slot(const char *name, long fallback) { return (int)pm_port_value(name, fallback); }

/* the rule's per-player lit mask: u64 at obj + stock_field + 8 * player */
static uint64_t stock_field(const struct stock_rule *x, unsigned p)
{
    unsigned a;
    if (!x->obj || p < 1 || p > 4) return 0;
    a = x->obj + (unsigned)pm_port_value("stock_field", 0x18) + 8u * p;
    return (uint64_t)*(volatile const unsigned *)(unsigned long)a | (uint64_t)*(volatile const unsigned *)(unsigned long)(a + 4) << 32;
}

static int stock_active(const struct stock_rule *x)
{
    int slot = stock_slot("stock_slot_active", -1);
    if (!x->obj || slot < 0 || !pm_player()) return -1;
    return (int)(((stock_vfn1)(unsigned long)stock_vtab(x)[slot])(x->obj) & 0xffu);
}

/* the rule's object through the manager's get, checked: 0 until the manager is built, or when the
 * object's vtable is not the port's word for it */
static unsigned stock_object(struct stock_rule *x, int say_why)
{
    unsigned get = fn("stock_rule_get"), mgr = data("stock_mode_manager"), obj;
    if (x->obj) return x->obj;
    if (!get || !mgr || !*(const unsigned *)(unsigned long)mgr) return 0;       /* not built yet */
    obj = (unsigned)(unsigned long)((void *(*)(void *, unsigned))(unsigned long)get)((void *)(unsigned long)mgr, x->id);
    if (!obj) return 0;
    if (*(const unsigned *)(unsigned long)obj != x->vt) {
        if (say_why && !x->refused)
            stock_say("stock: rule %u %s NOT wrapped - its object 0x%x has vtable 0x%x, the port says 0x%x (another build?)",
                      x->id, x->label, obj, *(const unsigned *)(unsigned long)obj, x->vt);
        x->refused = 1;
        return 0;
    }
    x->obj = obj;
    return obj;
}

/* ---- the wrap: what the game's handler receives ------------------------------------------------- */
/* The decision, and only that (tests lift it verbatim): the first row of `rule` whose `from`
 * holds every bit of `shot` decides. Its `to` bit lit in `field` = the shot becomes that one bit
 * (*hit = the row, 1 returned); not lit = the shot is left as it is (*hit = the row, 0 returned:
 * the rule has finished with that bit, or never lit it). No row = untouched, *hit = 0. A dispatch
 * carrying a bit outside `from` (the 0x1 "a switch was hit" dispatch, a mask of two shots) is never
 * remapped, so nothing is ever ORed into a shot and a multi-bit mask never reaches the handler as
 * the target. */
static int stock_decide(const struct stock_table *t, unsigned rule, uint64_t *shot, uint64_t field,
                        const struct stock_row **hit)
{
    unsigned i;
    *hit = 0;
    for (i = 0; i < t->n; i++) {
        const struct stock_row *r = &t->row[i];
        if (r->rule != rule || !*shot || (*shot & ~r->from)) continue;
        *hit = r;
        if (!(field & r->to)) return 0;
        *shot = r->to;
        return 1;
    }
    return 0;
}

static void stock_remap_shot(struct stock_rule *x, uint64_t *shot)
{
    const struct stock_row *r;
    unsigned p = pm_player();
    uint64_t was = *shot, field = stock_field(x, p);
    if (stock_decide(stock_live, x->id, shot, field, &r)) {
        x->remaps++;
        if (x->remaps <= 200 || x->remaps % 100 == 0)
            stock_say("stock: rule %u shot 0x%llx counts as 0x%llx (p%u, field 0x%llx, #%u)", x->id,
                      (unsigned long long)was, (unsigned long long)*shot, p, (unsigned long long)field, x->remaps);
    } else if (r) {
        x->passes++;
        if (x->passes <= 50 || x->passes % 100 == 0)
            stock_say("stock: rule %u shot 0x%llx passed through - 0x%llx is not lit (p%u, field 0x%llx)", x->id,
                      (unsigned long long)was, (unsigned long long)r->to, p, (unsigned long long)field);
    }
}

static uint64_t stock_w_shot(unsigned r0, unsigned r1, unsigned r2, unsigned r3,
                             unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    struct stock_rule *x = stock_find(r0);
    uint64_t shot = (uint64_t)r2 | (uint64_t)r3 << 32;
    if (!x) return 0;                            /* cannot happen: only wrapped rules' vtables point here */
    if (x->obj != r0) return x->orig(r0, r1, r2, r3, s0, s1, s2, s3);   /* another object of the class: not ours, untouched */
    if (x->in_original) return x->orig(r0, r1, r2, r3, s0, s1, s2, s3);   /* item 161: a replay of the game's handler passes straight through */
    if (x->h161 && stock161_first(x, &shot, s0)) return 0;                  /* item 161: the C handler took the shot */
    if (x->fn) {
        const struct pm_mode *was = current;
        int keep;
        current = x->fn_by;
        keep = x->fn(x->id, &shot, (void *)(unsigned long)r0);
        current = was;
        if (!keep) return 0;                     /* item 161: the hook handled it; the game's handler does not run */
    } else {
        stock_remap_shot(x, &shot);
    }
    return x->orig(r0, r1, (unsigned)shot, (unsigned)(shot >> 32), s0, s1, s2, s3);
}

static int stock_wrap(struct stock_rule *x)
{
    int slot = stock_slot("stock_slot_shot", -1);
    unsigned *vt;
    if (x->wrapped) return 1;
    if (slot < 0 || slot > 96 || !stock_object(x, 1)) return 0;
    vt = stock_vtab(x);
    x->orig = (stock_vfn8)(unsigned long)vt[slot];
    mprotect((void *)(unsigned long)(x->vt & ~0xfffu), ((x->vt & 0xfffu) + 4u * (unsigned)slot + 4u + 0xfffu) & ~0xfffu, 7);
    x->wrapped = 1;
    vt[slot] = (unsigned)(unsigned long)stock_w_shot;
    stock_say("stock: rule %u %s obj 0x%x vtable 0x%x: shot v[%d] 0x%x wrapped (active v[%d], field +0x%lx)", x->id, x->label,
              x->obj, x->vt, slot, (unsigned)(unsigned long)x->orig, stock_slot("stock_slot_active", -1),
              pm_port_value("stock_field", 0x18));
    return 1;
}

/* ---- the table --------------------------------------------------------------------------------- */
static int stock_one_bit(uint64_t v) { return v && !(v & (v - 1)); }

/* rebuild the shadow table from the file's rows and the C rows, then publish it */
static void stock_publish(void)
{
    struct stock_table *t = &stock_tab[stock_tab_i ^ 1];
    unsigned i;
    t->n = 0;
    for (i = 0; i < n_stock_c_rows && t->n < STOCK_ROWS; i++) t->row[t->n++] = stock_c_rows[i];
    for (i = 0; i < n_stock_file_rows && t->n < STOCK_ROWS; i++) t->row[t->n++] = stock_file_rows[i];
    for (i = 0; i < t->n; i++) {                 /* a `light` line for the rule sets the row's colour */
        int k;
        for (k = 0; k < N_STOCK_RULES; k++)
            if (stock_lights[k].set && stock_lights[k].rule == t->row[i].rule) {
                t->row[i].rgb = stock_lights[k].rgb;
                t->row[i].ms = stock_lights[k].ms;
                t->row[i].on_ms = stock_lights[k].on_ms;
                t->row[i].pattern = stock_lights[k].pattern;
            }
    }
    __sync_synchronize();
    stock_live = t;
    stock_tab_i ^= 1;
    for (i = 0; i < t->n; i++) {
        struct stock_rule *x = stock_rule(t->row[i].rule);
        if (x) stock_wrap(x);                    /* now, or on a later tick once the manager is built */
    }
}

static int stock_word_is(const char *s, const char *w, unsigned n)
{
    unsigned i;
    for (i = 0; i < n; i++) if (lamp_upper(s[i]) != lamp_upper(w[i])) return 0;
    return w[n] == 0;
}

/* a shot at *p: `0x..` or a number, else the port's shot NAME up to `stop` (case does not matter) */
static uint64_t stock_shot(const char *s, unsigned len)
{
    int i, ok = 0;
    uint64_t v;
    while (len && (*s == ' ' || *s == '\t')) { s++; len--; }
    while (len && (s[len - 1] == ' ' || s[len - 1] == '\t' || s[len - 1] == '\r')) len--;
    if (!len) return 0;
    if (s[0] >= '0' && s[0] <= '9') {
        const char *q = s;
        v = number(&q, &ok);
        return ok && (unsigned)(q - s) <= len ? v : 0;
    }
    for (i = 0; i < port.n_shot; i++)
        if (stock_word_is(s, port.shot[i].name, len)) return port.shot[i].mask;
    return 0;
}

static int stock_colour(const char **p, unsigned *rgb)
{
    static const struct { const char *name; unsigned rgb; } names[] = {
        { "red", 0xff0000 }, { "green", 0x00ff00 }, { "blue", 0x0000ff }, { "yellow", 0xffff00 },
        { "orange", 0xff6000 }, { "purple", 0xa000ff }, { "cyan", 0x00ffff }, { "white", 0xffffff },
        { "pink", 0xff40a0 },
    };
    const char *s = *p;
    unsigned n = 0, i, v = 0;
    while (*s == ' ' || *s == '\t') s++;
    if (*s == '#') s++;
    while (s[n] && s[n] != ' ' && s[n] != '\t' && s[n] != '\r') n++;
    for (i = 0; i < sizeof names / sizeof names[0]; i++)
        if (stock_word_is(s, names[i].name, n)) { *rgb = names[i].rgb; *p = s + n; return 1; }
    if (n != 6) return 0;
    for (i = 0; i < 6; i++) {
        int d = hexval(s[i]);
        if (d < 0) return 0;
        v = v * 16 + (unsigned)d;
    }
    *rgb = v;
    *p = s + n;
    return 1;
}

/* one line of stock.cfg:
 *   counts_as <rule id> <shot> -> <shot>            shots: the port's names, or 0x masks
 *   light <rule id> <colour> [pattern] [ms] [on ms]  the stand-in's inserts (yellow blink 500 300 when absent) */
static void stock_line(const char *s)
{
    char key[16];
    int ok = 0;
    unsigned id;
    const char *a, *arrow;
    s = word(s, key, sizeof key);
    if (str_eq(key, "counts_as")) {
        struct stock_row r;
        uint64_t from, to;
        unsigned i;
        id = (unsigned)number(&s, &ok);
        if (!ok) { stock_say("stock: counts_as needs a rule id - ignored"); return; }
        for (arrow = s; *arrow && !(arrow[0] == '-' && arrow[1] == '>'); arrow++) ;
        if (!*arrow) { stock_say("stock: counts_as %u needs `<shot> -> <shot>` - ignored", id); return; }
        from = stock_shot(s, (unsigned)(arrow - s));
        a = arrow + 2;
        while (*a == ' ' || *a == '\t') a++;
        for (i = 0; a[i] && a[i] != '\n' && a[i] != '\r'; i++) ;
        to = stock_shot(a, i);
        if (!stock_rule(id)) { stock_say("stock: counts_as %u: this port names no rule %u - ignored", id, id); return; }
        if (!from) { stock_say("stock: counts_as %u: the shot before -> is not a shot this port names - ignored", id); return; }
        if (!to) { stock_say("stock: counts_as %u: the shot after -> is not a shot this port names - ignored", id); return; }
        if (!stock_one_bit(to)) { stock_say("stock: counts_as %u: the target 0x%llx must be ONE bit (a rule tests one bit) - ignored", id, (unsigned long long)to); return; }
        if (from & to) { stock_say("stock: counts_as %u: 0x%llx already carries 0x%llx - ignored", id, (unsigned long long)from, (unsigned long long)to); return; }
        if (n_stock_file_rows >= STOCK_ROWS) { stock_say("stock: more than %d counts_as rows - ignored", STOCK_ROWS); return; }
        r.rule = id; r.from = from; r.to = to; r.from_c = 0;
        r.rgb = 0xffff00; r.ms = 500; r.on_ms = 300; r.pattern = PM_LAMP_BLINK;
        stock_file_rows[n_stock_file_rows++] = r;
        stock_say("stock: counts_as %u %s: 0x%llx (%s) -> 0x%llx (%s)", id, stock_rule(id)->label, (unsigned long long)from,
                  pm_shot_name(from) ? pm_shot_name(from) : "?", (unsigned long long)to, pm_shot_name(to) ? pm_shot_name(to) : "?");
        return;
    }
    if (str_eq(key, "light")) {
        unsigned rgb = 0, k, ms, on;
        int pat = PM_LAMP_BLINK;
        char pw[12];
        id = (unsigned)number(&s, &ok);
        if (!ok || !stock_rule(id)) { stock_say("stock: light needs a rule id this port names - ignored"); return; }
        if (!stock_colour(&s, &rgb)) { stock_say("stock: light %u: no colour (rrggbb or a colour's name) - ignored", id); return; }
        a = word(s, pw, sizeof pw);
        if (pw[0] && !(pw[0] >= '0' && pw[0] <= '9')) {
            if (str_eq(pw, "solid")) pat = PM_LAMP_SOLID;
            else if (str_eq(pw, "blink")) pat = PM_LAMP_BLINK;
            else if (str_eq(pw, "pulse")) pat = PM_LAMP_PULSE;
            else { stock_say("stock: light %u: pattern is solid, blink or pulse - ignored", id); return; }
            s = a;
        }
        ms = (unsigned)number(&s, &ok);
        on = ok ? (unsigned)number(&s, 0) : 0;
        for (k = 0; k < N_STOCK_RULES && stock_lights[k].set && stock_lights[k].rule != id; k++) ;
        if (k == N_STOCK_RULES) return;
        stock_lights[k].set = 1;
        stock_lights[k].rule = id;
        stock_lights[k].rgb = rgb;
        stock_lights[k].pattern = pat;
        stock_lights[k].ms = ms ? ms : 500;
        stock_lights[k].on_ms = on;
        stock_say("stock: light %u: %06x %s, %u ms%s", id, rgb, pat == PM_LAMP_SOLID ? "solid" : pat == PM_LAMP_PULSE ? "pulse" : "blink",
                  stock_lights[k].ms, on ? " (on part given)" : "");
        return;
    }
    stock_say("stock: unknown key, skipped: %.60s", key);
}

static void stock_parse(const char *buf, long len)
{
    char line[STOCK_LINE_MAX];
    long i = 0;
    int k;
    n_stock_file_rows = 0;
    for (k = 0; k < N_STOCK_RULES; k++) stock_lights[k].set = 0;
    while (i < len) {
        long j = 0;
        while (i < len && buf[i] != '\n') {
            if (j + 1 < (long)sizeof line) line[j++] = buf[i];
            i++;
        }
        i++;
        line[j] = 0;
        {
            const char *s = line;
            long c;
            /* a `#` at the start, or after a blank, ends the line: a comment line, or a trailing comment
             * on a row (the app's Write writes one per row; 2026-09-23 a card's rows were refused as
             * "not a shot this port names" because the comment rode into the shot after `->`) */
            for (c = 0; line[c]; c++)
                if (line[c] == '#' && (c == 0 || line[c - 1] == ' ' || line[c - 1] == '\t')) { line[c] = 0; break; }
            while (*s == ' ' || *s == '\t') s++;
            if (*s) stock_line(s);
        }
    }
}

/* twice a second: the file, byte-compared; a change is parsed and published */
static void stock_file_poll(void)
{
    static char buf[STOCK_FILE_MAX];
    long n = -1, i;
    int k;
    for (k = 0; k < (int)(sizeof STOCK_FILES / sizeof STOCK_FILES[0]); k++) {
        n = pm_read_file(STOCK_FILES[k], buf, sizeof buf);
        if (n >= 0) break;
    }
    if (n < 0) {
        if (stock_raw_len < 0) return;
        stock_raw_len = -1;
        stock_file_which = -1;
        n_stock_file_rows = 0;
        stock_publish();
        stock_say("stock: stock.cfg gone - %u C row(s) left; a wrapped rule with no row passes every shot through", n_stock_c_rows);
        return;
    }
    if (stock_file_which != k) {
        stock_file_which = k;
        stock_say("stock: file %s", STOCK_FILES[k]);
    }
    if (n == stock_raw_len) {
        for (i = 0; i < n && buf[i] == stock_raw[i]; i++) ;
        if (i == n) return;
    }
    for (i = 0; i < n; i++) stock_raw[i] = buf[i];
    stock_raw_len = n;
    stock_parse(stock_raw, n);
    stock_publish();
    stock_say("stock: %u counts_as row(s) live (%u from C); an empty table plays every rule stock", stock_live->n, n_stock_c_rows);
}

/* every 100 ms: the stand-in's inserts follow the target bit, while the rule is active */
static void stock_lamps_poll(void)
{
    struct stock_table *t = stock_live;
    const struct pm_mode *was = current;
    int i;
    unsigned k;
    for (i = 0; i < n_stock_rules; i++) {
        struct stock_rule *x = &stock_rules[i];
        const struct stock_row *want = 0;
        int act;
        if (!x->wrapped || !x->obj) continue;
        act = pm_in_game() ? stock_active(x) : 0;
        if (act > 0) {
            uint64_t field = stock_field(x, pm_player());
            for (k = 0; k < t->n && !want; k++)
                if (t->row[k].rule == x->id && (field & t->row[k].to)) want = &t->row[k];
        }
        if (want && (!x->lit || x->lit_from != want->from)) {
            int n;
            current = &stock_mode;
            if (x->lit) pm_lamp_release_shot(x->lit_from);
            lamp_hold_on_ms = want->on_ms;
            n = pm_lamp_shot(want->from, want->rgb, want->pattern, want->ms);
            lamp_hold_on_ms = 0;
            current = was;
            x->lit = 1;
            x->lit_from = want->from;
            stock_say("stock: rule %u %s: %d insert(s) of 0x%llx lit %06x while 0x%llx is lit (%s)", x->id, x->label, n,
                      (unsigned long long)want->from, want->rgb, (unsigned long long)want->to,
                      pm_can(PM_CAN_LAMPS) ? "our lamp layer" : "no lamp layer on this port: nothing lit");
        } else if (!want && x->lit) {
            int n, rows = 0;
            for (k = 0; k < t->n; k++) rows += t->row[k].rule == x->id;
            current = &stock_mode;
            n = pm_lamp_release_shot(x->lit_from);
            current = was;
            x->lit = 0;
            stock_say("stock: rule %u %s: %d insert(s) of 0x%llx handed back (%s)", x->id, x->label, n,
                      (unsigned long long)x->lit_from,
                      act <= 0 ? "the rule is not active" : rows ? "the target bit cleared" : "no row names the rule now");
        }
    }
}

/* from on_tick, AFTER the modes' ticks: a probe that wraps the same slot from its tick (stock_probe.c)
 * wraps first, so it logs what the game's handler receives */
static void stock_tick(void)
{
    static unsigned ticks;
    int i;
    if (!stock_armed) return;
    ticks++;
    if (ticks % 30 == 0) {
        stock_file_poll();
        stock161_attach();                        /* item 161: records from the pm_stock section */
        for (i = 0; i < n_stock_rules; i++) {    /* a rule named before the manager was built */
            unsigned k;
            struct stock_table *t = stock_live;
            if (stock_rules[i].wrapped) continue;
            for (k = 0; k < t->n; k++)
                if (t->row[k].rule == stock_rules[i].id) { stock_wrap(&stock_rules[i]); break; }
        }
    }
    if (ticks % 6 == 0) stock_lamps_poll();
}

static void stock_arm(void)
{
    struct site *g = site("stock_rule_get");
    if (!n_stock_rules) return;
    if (!g || !g->ok || !data("stock_mode_manager") || stock_slot("stock_slot_shot", -1) < 0
        || stock_slot("stock_slot_active", -1) < 0 || pm_port_value("stock_field", -1) < 0) {
        say("stock rules: %d named, but the port lacks stock_rule_get (matching), stock_mode_manager, stock_slot_shot, stock_slot_active or stock_field - no counts-as",
            n_stock_rules);
        return;
    }
    stock_armed = 1;
    can |= PM_CAN_STOCK_RULES;
    say("stock rules: %d named (%s%s); counts_as rows are read from stock.cfg twice a second, shot slot v[%d]",
        n_stock_rules, stock_rules[0].label, n_stock_rules > 1 ? ", ..." : "", stock_slot("stock_slot_shot", -1));
}

/* ---- the calls (pad_mode.h) ---- */
int pm_stock_rule_count(void) { return (can & PM_CAN_STOCK_RULES) ? n_stock_rules : 0; }

int pm_stock_rule_at(int i, unsigned *id, const char **label)
{
    if (!(can & PM_CAN_STOCK_RULES) || i < 0 || i >= n_stock_rules) return 0;
    if (id) *id = stock_rules[i].id;
    if (label) *label = stock_rules[i].label;
    return 1;
}

void *pm_stock_rule_object(unsigned id)
{
    struct stock_rule *x = stock_rule(id);
    if (!(can & PM_CAN_STOCK_RULES) || !x) return 0;
    return (void *)(unsigned long)stock_object(x, 0);
}

int pm_stock_rule_active(unsigned id)
{
    struct stock_rule *x = stock_rule(id);
    if (!(can & PM_CAN_STOCK_RULES) || !x || !stock_object(x, 0)) return -1;
    return stock_active(x);
}

uint64_t pm_stock_rule_field(unsigned id)
{
    struct stock_rule *x = stock_rule(id);
    if (!(can & PM_CAN_STOCK_RULES) || !x || !stock_object(x, 0)) return 0;
    return stock_field(x, pm_player());
}

int pm_stock_rule_hook(unsigned id, pm_stock_shot_fn fn)
{
    struct stock_rule *x = stock_rule(id);
    if (!(can & PM_CAN_STOCK_RULES) || !x || !fn) return 0;
    if (x->fn && x->fn_by != current) return 0;
    if (!stock_wrap(x)) return 0;
    x->fn = fn;
    x->fn_by = current;
    stock_say("stock: rule %u %s: %s hooks its shot handler", id, x->label, current && current->name ? current->name : "a mode");
    return 1;
}

void pm_stock_rule_unhook(unsigned id)
{
    struct stock_rule *x = stock_rule(id);
    if (!x || !x->fn || x->fn_by != current) return;
    x->fn = 0;
    x->fn_by = 0;
    stock_say("stock: rule %u %s: its shot handler is the game's again (the wrap passes through)", id, x->label);
}

int pm_stock_counts_as(unsigned id, uint64_t from, uint64_t to)
{
    unsigned i;
    if (!(can & PM_CAN_STOCK_RULES) || !stock_rule(id) || !from) return 0;
    for (i = 0; i < n_stock_c_rows; i++)
        if (stock_c_rows[i].rule == id && stock_c_rows[i].from == from) break;
    if (!to) {
        if (i == n_stock_c_rows) return 0;
        for (; i + 1 < n_stock_c_rows; i++) stock_c_rows[i] = stock_c_rows[i + 1];
        n_stock_c_rows--;
        stock_publish();
        return 1;
    }
    if (!stock_one_bit(to) || (from & to)) return 0;
    if (i == n_stock_c_rows) {
        if (n_stock_c_rows >= STOCK_C_ROWS) return 0;
        n_stock_c_rows++;
    }
    stock_c_rows[i].rule = id; stock_c_rows[i].from = from; stock_c_rows[i].to = to; stock_c_rows[i].from_c = 1;
    stock_c_rows[i].rgb = 0xffff00; stock_c_rows[i].ms = 500; stock_c_rows[i].on_ms = 300; stock_c_rows[i].pattern = PM_LAMP_BLINK;
    stock_publish();
    return 1;
}
/* ---- STOCK RULES IN C (item 161): a C handler that runs INSTEAD of a rule's shot handler --------------
 * pad_stock.h, on item 160's wrap above. A record in the `pm_stock` section (PM_STOCK_HANDLER /
 * PM_STOCK_RULE) names a rule id and a C function. From the tick, once the manager has built the rule,
 * its shot slot is wrapped (stock_wrap: a probe that wrapped first from its own tick stays inside, so
 * its log shows what the game's handler gets) and, when the record has the callbacks, its START and
 * STOP slots too (`value stock_slot_start` / `stock_slot_stop`). In the wrap the C handler runs first,
 * with the shot as dispatched and the dispatch's stack word (the factor): PM_STOCK_DONE = the game's
 * handler is not run for this shot; PM_STOCK_PASS = item 160's rows and the game's handler run as if
 * the record were not there. pm_stock_call_original runs the slot's function as it was before the wrap
 * (a probe's, or the game's) with the rule marked "in the original", so a handler that replays the
 * game's own code (pm_ebirah_stage_award, pm_stock_final_blow) is never re-entered and no row is
 * applied to the replay. Every accessor reads its slot, offset or address from the port (MODE_SDK.md,
 * "Rewriting a stock rule's shot logic"); a missing line answers 0 / -1 and is said once. */
extern const struct pm_stock_handler *const __start_pm_stock[] __attribute__((weak, visibility("hidden")));
extern const struct pm_stock_handler *const __stop_pm_stock[] __attribute__((weak, visibility("hidden")));
#define EACH_STOCK_HANDLER(h) \
    for (const struct pm_stock_handler *const *ph_ = __start_pm_stock; ph_ && ph_ < __stop_pm_stock && ((h) = *ph_, 1); ph_++)

static struct stock_rule *stock161_of(struct pm_stock_rule *r) { return (struct stock_rule *)(void *)r; }
static struct pm_stock_rule *stock161_handle(struct stock_rule *x) { return (struct pm_stock_rule *)(void *)x; }
static uint64_t stock161_u64(unsigned a)
{
    return (uint64_t)*(volatile const unsigned *)(unsigned long)a | (uint64_t)*(volatile const unsigned *)(unsigned long)(a + 4) << 32;
}

/* a port line an accessor needs is missing: said once per name, the call answers "nothing" */
static int stock161_missing(const char *name)
{
    static const char *said[24];
    static int n;
    int i;
    for (i = 0; i < n; i++) if (said[i] == name) return 0;
    if (n < 24) said[n++] = name;
    stock_say("stock: the port has no `%s` line - that call does nothing", name);
    return 0;
}
static long stock161_value(const char *name)
{
    long v = pm_port_value(name, -1);
    if (v < 0) stock161_missing(name);
    return v;
}
static unsigned stock161_site(const char *name)
{
    unsigned f = fn(name);
    if (!f) stock161_missing(name);
    return f;
}
static unsigned stock161_data(const char *name)
{
    unsigned d = data(name);
    if (!d) stock161_missing(name);
    return d;
}
static const struct pm_mode *stock161_mode(const struct stock_rule *x)
{
    return x->h161 && x->h161->mode ? x->h161->mode : &stock_mode;
}

/* the C handler, first in the wrap: 1 = it took the shot, the game's handler does not run */
static int stock161_first(struct stock_rule *x, uint64_t *shot, unsigned s0)
{
    const struct pm_mode *was = current;
    int done;
    if (!x->h161->shot) return 0;
    current = stock161_mode(x);
    done = x->h161->shot(stock161_handle(x), *shot, s0);
    current = was;
    return done != 0;
}

static struct stock_rule *stock161_find(unsigned self)
{
    int i;
    for (i = 0; i < n_stock_rules; i++) if (stock_rules[i].obj && stock_rules[i].obj == self) return &stock_rules[i];
    /* the wrap sits in the CLASS's vtable: another object of it reaches here too, and gets the game's slot untouched */
    for (i = 0; i < n_stock_rules; i++) if (stock_rules[i].obj && stock_rules[i].vt == *(const unsigned *)(unsigned long)self) return &stock_rules[i];
    return 0;
}

/* the START wrap: the game's START first, then the record's started() */
static uint64_t stock_w_start(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    struct stock_rule *x = stock161_find(r0);
    uint64_t ret;
    if (!x || !x->orig_start) return 0;
    ret = x->orig_start(r0, r1, r2, r3, s0, s1, s2, s3);
    if (x->obj == r0 && x->h161 && x->h161->started) {
        const struct pm_mode *was = current;
        current = stock161_mode(x);
        x->h161->started(stock161_handle(x));
        current = was;
    }
    return ret;
}

/* the STOP wrap: the record's stopped(reason) first, then the game's STOP */
static uint64_t stock_w_stop(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    struct stock_rule *x = stock161_find(r0);
    if (!x || !x->orig_stop) return 0;
    if (x->obj == r0 && x->h161 && x->h161->stopped) {
        const struct pm_mode *was = current;
        current = stock161_mode(x);
        x->h161->stopped(stock161_handle(x), r1);
        current = was;
    }
    return x->orig_stop(r0, r1, r2, r3, s0, s1, s2, s3);
}

/* one more slot of a rule whose object is known and checked (the shot wrap holds it already) */
static int stock161_wrap_slot(struct stock_rule *x, const char *slot_name, stock_vfn8 *orig, int *flag, stock_vfn8 wrapper)
{
    int slot = stock_slot(slot_name, -1);
    unsigned *vt;
    if (*flag) return 1;
    if (slot < 0) return stock161_missing(slot_name);
    if (slot > 96 || !x->obj) return 0;
    vt = stock_vtab(x);
    *orig = (stock_vfn8)(unsigned long)vt[slot];
    mprotect((void *)(unsigned long)(x->vt & ~0xfffu), ((x->vt & 0xfffu) + 4u * (unsigned)slot + 4u + 0xfffu) & ~0xfffu, 7);
    *flag = 1;
    vt[slot] = (unsigned)(unsigned long)wrapper;
    stock_say("stock: rule %u %s: %s v[%d] 0x%x wrapped", x->id, x->label, slot_name, slot, (unsigned)(unsigned long)*orig);
    return 1;
}

/* from stock_tick, twice a second: every record attached to its rule once the manager has built it */
static void stock161_attach(void)
{
    const struct pm_stock_handler *h;
    static int said_no_rule, said_taken;
    EACH_STOCK_HANDLER(h) {
        struct stock_rule *x;
        if (!h) continue;
        x = stock_rule(h->rule_id);
        if (!x) {
            if (!said_no_rule) {
                said_no_rule = 1;
                stock_say("stock: %s names rule %u, which this port does not name - not installed",
                          h->name ? h->name : "a C handler", h->rule_id);
            }
            continue;
        }
        if (x->h161 == h) continue;
        if (x->h161) {
            if (!said_taken) {
                said_taken = 1;
                stock_say("stock: rule %u %s already has %s; %s is not installed", x->id, x->label,
                          x->h161->name ? x->h161->name : "a C handler", h->name ? h->name : "another");
            }
            continue;
        }
        if (!stock_wrap(x)) continue;                          /* the manager is not built yet: next time */
        if (h->started) stock161_wrap_slot(x, "stock_slot_start", &x->orig_start, &x->wrapped_start, stock_w_start);
        if (h->stopped) stock161_wrap_slot(x, "stock_slot_stop", &x->orig_stop, &x->wrapped_stop, stock_w_stop);
        x->h161 = h;
        stock_say("stock: rule %u %s: its shots go to %s first (PM_STOCK_DONE keeps the game's handler from running)",
                  x->id, x->label, h->name ? h->name : "a C handler");
    }
}

/* ---- the calls (pad_stock.h) ---- */
struct pm_stock_rule *pm_stock_rule(unsigned id)
{
    struct stock_rule *x = stock_rule(id);
    if (!(can & PM_CAN_STOCK_RULES) || !x || !stock_object(x, 0)) return 0;
    return stock161_handle(x);
}

unsigned pm_stock_rule_id(const struct pm_stock_rule *r) { return r ? ((const struct stock_rule *)(const void *)r)->id : 0; }
unsigned pm_stock_player(void) { return pm_player(); }

uint64_t pm_stock_call_original(struct pm_stock_rule *r, uint64_t shot, unsigned factor)
{
    struct stock_rule *x = stock161_of(r);
    uint64_t ret;
    if (!x || !x->wrapped || !x->orig || !x->obj) return 0;
    x->in_original++;
    ret = x->orig(x->obj, 0, (unsigned)shot, (unsigned)(shot >> 32), factor, 0, 0, 0);
    x->in_original--;
    return ret;
}

uint64_t pm_stock_field(struct pm_stock_rule *r, unsigned player)
{
    struct stock_rule *x = stock161_of(r);
    return x ? stock_field(x, player) : 0;
}

int pm_stock_field_set(struct pm_stock_rule *r, unsigned player, uint64_t mask)
{
    struct stock_rule *x = stock161_of(r);
    unsigned a;
    if (!x || !x->obj || player < 1 || player > 4) return 0;
    a = x->obj + (unsigned)pm_port_value("stock_field", 0x18) + 8u * player;
    *(volatile unsigned *)(unsigned long)a = (unsigned)mask;
    *(volatile unsigned *)(unsigned long)(a + 4) = (unsigned)(mask >> 32);
    return 1;
}

uint64_t pm_stock_lit(struct pm_stock_rule *r)
{
    struct stock_rule *x = stock161_of(r);
    long slot = x ? stock161_value("stock_slot_lit") : -1;
    if (!x || !x->obj || slot < 0 || slot > 96) return 0;
    return ((stock_vfn1)(unsigned long)stock_vtab(x)[slot])(x->obj);
}

int pm_stock_active(struct pm_stock_rule *r)
{
    struct stock_rule *x = stock161_of(r);
    return x ? stock_active(x) : -1;
}

int pm_stock_running(struct pm_stock_rule *r, unsigned player)
{
    struct stock_rule *x = stock161_of(r);
    long at = x ? stock161_value("stock_running_at") : -1;
    if (!x || !x->obj || at < 0 || player < 1 || player > 4) return -1;
    return *(volatile const unsigned char *)(unsigned long)(x->obj + (unsigned)at + player);
}

long pm_stock_at(const char *value_name) { return stock161_value(value_name); }

static volatile unsigned *stock161_word(struct pm_stock_rule *r, long at, unsigned player, int per_player)
{
    struct stock_rule *x = stock161_of(r);
    if (!x || !x->obj || at < 0 || at > 0x10000) return 0;
    if (per_player && (player < 1 || player > 4)) return 0;
    return (volatile unsigned *)(unsigned long)(x->obj + (unsigned)at + (per_player ? 4u * player : 0u));
}

int pm_stock_pw_get(struct pm_stock_rule *r, long at, unsigned player, int *out)
{
    volatile unsigned *w = stock161_word(r, at, player, 1);
    if (!w) return 0;
    *out = (int)*w;
    return 1;
}
int pm_stock_pw_set(struct pm_stock_rule *r, long at, unsigned player, int value)
{
    volatile unsigned *w = stock161_word(r, at, player, 1);
    if (!w) return 0;
    *w = (unsigned)value;
    return 1;
}
int pm_stock_w_get(struct pm_stock_rule *r, long at, int *out)
{
    volatile unsigned *w = stock161_word(r, at, 0, 0);
    if (!w) return 0;
    *out = (int)*w;
    return 1;
}
int pm_stock_w_set(struct pm_stock_rule *r, long at, int value)
{
    volatile unsigned *w = stock161_word(r, at, 0, 0);
    if (!w) return 0;
    *w = (unsigned)value;
    return 1;
}
int pm_stock_b_get(struct pm_stock_rule *r, long at, int *out)
{
    volatile unsigned *w = stock161_word(r, at, 0, 0);
    if (!w) return 0;
    *out = *(volatile const unsigned char *)w;
    return 1;
}

/* an award the way the handlers pay one: caward_add / caward_build(the rule's award, 0, value, [sp] 0) */
typedef uint64_t (*stock161_award_fn)(unsigned, unsigned, unsigned, unsigned, unsigned);
static uint64_t stock161_pay(const char *site_name, unsigned obj, uint64_t value)
{
    unsigned f = stock161_site(site_name), award;
    long at = stock161_value("stock_award_at");
    if (!f || at < 0 || !obj) return 0;
    award = *(volatile const unsigned *)(unsigned long)(obj + (unsigned)at);
    if (!award) return 0;
    return ((stock161_award_fn)(unsigned long)f)(award, 0, (unsigned)value, (unsigned)(value >> 32), 0);
}
uint64_t pm_stock_award(struct pm_stock_rule *r, uint64_t value)
{
    struct stock_rule *x = stock161_of(r);
    return x && x->obj ? stock161_pay("caward_add", x->obj, value) : 0;
}
uint64_t pm_stock_award_to(unsigned rule_id, uint64_t value)
{
    struct stock_rule *x = stock_rule(rule_id);
    return x && stock_object(x, 0) ? stock161_pay("caward_add", x->obj, value) : 0;
}
uint64_t pm_stock_build(struct pm_stock_rule *r, uint64_t value)
{
    struct stock_rule *x = stock161_of(r);
    return x && x->obj ? stock161_pay("caward_build", x->obj, value) : 0;
}

void *pm_stock_show(unsigned id)
{
    unsigned f = stock161_site("show_start");
    return f ? ((void *(*)(unsigned))(unsigned long)f)(id) : 0;
}

int pm_stock_event(unsigned id, uint64_t value)
{
    unsigned f = stock161_site("game_event");
    if (!f) return 0;
    /* (id, _, value lo, hi, [sp] a, pad, [sp+8] b lo, hi): b is a u64, so the eighth word is its high half */
    ((void (*)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned))(unsigned long)f)(
        id, 0, (unsigned)value, (unsigned)(value >> 32), 0, 0, 0, 0);
    return 1;
}

void *pm_stock_display_event(unsigned id, unsigned handler, unsigned flags)
{
    unsigned f = stock161_site("event_post_replacing");
    return f ? ((void *(*)(unsigned, unsigned, unsigned))(unsigned long)f)(id, handler, flags) : 0;
}

int pm_stock_event_cancel(unsigned id)
{
    unsigned f = stock161_site("event_cancel");
    if (!f) return 0;
    ((void (*)(unsigned, unsigned))(unsigned long)f)(id, 0xffffu);
    return 1;
}

static int stock161_call_slot(struct pm_stock_rule *r, const char *slot_name, unsigned r1)
{
    struct stock_rule *x = stock161_of(r);
    long slot = x ? stock161_value(slot_name) : -1;
    if (!x || !x->obj || slot < 0 || slot > 96) return 0;
    ((stock_vfn8)(unsigned long)stock_vtab(x)[slot])(x->obj, r1, 0, 0, 0, 0, 0, 0);
    return 1;
}
int pm_stock_stop(struct pm_stock_rule *r, int won) { return stock161_call_slot(r, "stock_slot_stop", won ? 1u : 0u); }
int pm_stock_start(struct pm_stock_rule *r) { return stock161_call_slot(r, "stock_slot_start", 0); }

/* ---- Godzilla: battle vs Ebirah ---- */
static const char *const EB_SPIN_AT[3] = { "ebirah_spin_left_at", "ebirah_spin_top_at", "ebirah_spin_shield_at" };
static const char *const EB_SPIN_BIT[3] = { "ebirah_spin_left_bit", "ebirah_spin_top_bit", "ebirah_spin_shield_bit" };

int pm_ebirah_spins(struct pm_stock_rule *r, int which, unsigned player)
{
    int v;
    if (which < 0 || which > 2) return -1;
    return pm_stock_pw_get(r, stock161_value(EB_SPIN_AT[which]), player, &v) ? v : -1;
}
int pm_ebirah_spins_set(struct pm_stock_rule *r, int which, unsigned player, int n)
{
    if (which < 0 || which > 2) return 0;
    return pm_stock_pw_set(r, stock161_value(EB_SPIN_AT[which]), player, n);
}
uint64_t pm_ebirah_spin_bit(int which)
{
    long v;
    if (which < 0 || which > 2) return 0;
    v = stock161_value(EB_SPIN_BIT[which]);
    return v < 0 ? 0 : (uint64_t)v;
}

int pm_ebirah_stage_award(struct pm_stock_rule *r, int which)
{
    struct stock_rule *x = stock161_of(r);
    unsigned p = pm_player();
    uint64_t bit = pm_ebirah_spin_bit(which);
    if (!x || !p || !bit) return 0;
    if (!pm_ebirah_spins_set(r, which, p, 1)) return 0;
    pm_stock_field_set(r, p, pm_stock_field(r, p) | bit);
    stock_say("stock: rule %u %s: the game's own stage award, replayed as 0x%llx (that spinner's count := 1, its bit lit)",
              x->id, x->label, (unsigned long long)bit);
    pm_stock_call_original(r, bit, 1);
    return 1;
}

int pm_stock_final_blow(struct pm_stock_rule *r)
{
    struct stock_rule *x = stock161_of(r);
    unsigned p = pm_player();
    long lo = stock161_value("ebirah_final_mask_lo"), hi = pm_port_value("ebirah_final_mask_hi", 0);
    long shot = stock161_value("ebirah_final_shot");
    if (!x || !p || lo < 0 || shot < 0) return 0;
    pm_stock_field_set(r, p, (uint64_t)(unsigned long)hi << 32 | (uint64_t)(unsigned long)lo);
    stock_say("stock: rule %u %s: the game's own final blow, replayed as 0x%lx with the field 0x%lx_%08lx",
              x->id, x->label, shot, hi, lo);
    pm_stock_call_original(r, (uint64_t)(unsigned long)shot, 1);
    return 1;
}

uint64_t pm_ebirah_stage_value(unsigned index)
{
    unsigned base = stock161_data("ebirah_stage_awards");
    long n = pm_port_value("ebirah_stage_award_count", 0);
    if (!base || (long)index >= n) return 0;
    return stock161_u64(base + 8u * index);
}

/* ---- Godzilla: tank attack multiball ---- */
static int stock161_tank_vec(struct stock_rule *x, unsigned *begin, unsigned *n, unsigned *size)
{
    long at = stock161_value("tank_records_at"), sz = pm_port_value("tank_record_size", 40);
    unsigned end;
    if (!x || !x->obj || at < 0 || sz < 8) return 0;
    *size = (unsigned)sz;
    *begin = *(volatile const unsigned *)(unsigned long)(x->obj + (unsigned)at);
    end = *(volatile const unsigned *)(unsigned long)(x->obj + (unsigned)at + 4);
    if (!*begin || end < *begin) return 0;
    *n = (end - *begin) / *size;
    if (*n > 64) *n = 64;
    return 1;
}

int pm_tank_records(struct pm_stock_rule *r, struct pm_tank_record *out, int max)
{
    unsigned begin, n, size, i;
    long a_act = pm_port_value("tank_record_active_at", 0), a_pos = pm_port_value("tank_record_pos_at", 8);
    long a_prev = pm_port_value("tank_record_prev_at", 0x10), a_dest = pm_port_value("tank_record_dest_at", 0x18);
    long a_val = pm_port_value("tank_record_value_at", 0x20);
    if (!stock161_tank_vec(stock161_of(r), &begin, &n, &size)) return 0;
    for (i = 0; i < n && (int)i < max; i++) {
        unsigned rec = begin + i * size;
        out[i].active = *(volatile const unsigned char *)(unsigned long)(rec + (unsigned)a_act);
        out[i].pos = stock161_u64(rec + (unsigned)a_pos);
        out[i].prev = stock161_u64(rec + (unsigned)a_prev);
        out[i].dest = stock161_u64(rec + (unsigned)a_dest);
        out[i].value = stock161_u64(rec + (unsigned)a_val);
    }
    return (int)i;                               /* how many were filled: at most max */
}

int pm_tank_destroyed(struct pm_stock_rule *r)
{
    int v;
    return pm_stock_w_get(r, stock161_value("tank_destroyed_at"), &v) ? v : -1;
}
int pm_tank_level(struct pm_stock_rule *r, unsigned player)
{
    int v;
    return pm_stock_pw_get(r, stock161_value("tank_level_at"), player, &v) ? v : -1;
}
int pm_tank_maser_phase(struct pm_stock_rule *r)
{
    struct stock_rule *x = stock161_of(r);
    unsigned f = stock161_site("tank_maser_phase");
    if (!x || !x->obj || !f) return 0;
    return (int)(((stock_vfn1)(unsigned long)f)(x->obj) & 0xffu);
}
int pm_tank_destroy(struct pm_stock_rule *r, int index, int credit)
{
    struct stock_rule *x = stock161_of(r);
    unsigned f = stock161_site("tank_destroy"), begin, n, size;
    if (!f || !stock161_tank_vec(x, &begin, &n, &size) || index < 0 || (unsigned)index >= n) return 0;
    ((void (*)(unsigned, unsigned, unsigned))(unsigned long)f)(x->obj, begin + (unsigned)index * size, credit ? 1u : 0u);
    return 1;
}
static int stock161_tank_call(struct pm_stock_rule *r, const char *site_name)
{
    struct stock_rule *x = stock161_of(r);
    unsigned f = stock161_site(site_name);
    if (!x || !x->obj || !f) return 0;
    ((void (*)(unsigned))(unsigned long)f)(x->obj);
    return 1;
}
int pm_tank_seed_wave(struct pm_stock_rule *r) { return stock161_tank_call(r, "tank_seed_wave"); }
int pm_tank_advance(struct pm_stock_rule *r) { return stock161_tank_call(r, "tank_advance"); }

int pm_tank_path_entry(unsigned index, uint64_t *mask, unsigned *lamp)
{
    unsigned base = stock161_data("tank_path"), a;
    long n = pm_port_value("tank_path_entries", 0), sz = pm_port_value("tank_path_entry_size", 16);
    if (!base || sz < 10 || (long)index >= n) return 0;
    a = base + index * (unsigned)sz;
    *mask = stock161_u64(a);
    *lamp = *(volatile const unsigned short *)(unsigned long)(a + 8);
    return 1;
}
int pm_tank_path_index(struct pm_stock_rule *r, uint64_t shot)
{
    unsigned i, lamp;
    uint64_t mask;
    (void)r;
    for (i = 0; pm_tank_path_entry(i, &mask, &lamp); i++)
        if (mask & shot) return (int)i;
    return -1;
}
/* ---- STOCK END */

/* ---- the modes, and the hooks that call them -------------------------------------------------- */
/* Hidden, like everything in the object (build_mode.sh: -fvisibility=hidden): two mode
 * objects preloaded together must never bind to each other's modes or calls. */
extern const struct pm_mode *const __start_pm_modes[] __attribute__((weak, visibility("hidden")));
extern const struct pm_mode *const __stop_pm_modes[] __attribute__((weak, visibility("hidden")));

#define EACH_MODE(m) \
    for (const struct pm_mode *const *pp_ = __start_pm_modes; pp_ && pp_ < __stop_pm_modes && ((m) = *pp_, 1); pp_++)

/* Which thread each callback runs on, logged once each: pad_mode.h's promises about
 * callbacks not overlapping rest on this, so it is measured on every boot, not assumed. */
extern long syscall(long, ...);
#define SYS_GETTID 224                                   /* ARM EABI */

static void note_thread(const char *what, int *said)
{
    if (*said) return;
    *said = 1;
    say("%s callbacks run on thread %ld", what, syscall(SYS_GETTID));
}

static void events_deliver(void);             /* the events section below */
static void switches_deliver(void);           /* the switches section below */
static void roster_deferred_tick(void);   /* item 146 */
static void stock_tick(void);             /* item 160 */
static void magnet_tick(void);            /* PAD-381 */
static void scoop_tick(void);             /* PAD-381 */

static void on_tick(unsigned *r)
{
    static int started, said;
    const struct pm_mode *m;
    (void)r;
    note_thread("tick", &said);
    /* init runs HERE, on the first tick, and never from the loader's constructor: at
     * load the game's main() has not run, its managers do not exist yet, and the first
     * version of this runtime crashed the game at boot calling a scene lookup from init
     * (item 134, run A: pc in libpthread, lr in the resource manager). */
    if (!started) {
        started = 1;
        EACH_MODE(m) if (m->init) { current = m; m->init(); }
    }
    clip_tick();
    sound_fades_tick();                       /* item 150 follow-up: fades end in silence */
    sound_swaps_tick();                       /* item 163: swapped carrier keys come back */
    events_deliver();
    switches_deliver();
    EACH_MODE(m) if (m->tick) { current = m; m->tick(); }
    current = 0;
    magnet_tick();                            /* PAD-381: after the modes, so a grab's deadline is checked the tick it passes */
    scoop_tick();                             /* PAD-381: the scoop's wrap goes in on the first tick */
    roster_deferred_tick();
    stock_generic_tick();                     /* item 164: the game's base play, for the mode table route */
    stock_tick();                             /* item 160: the game's own rules' counts-as (after the modes: a probe wraps first) */
    lamps_tick();                             /* named inserts: their patterns (lights section) */
}

static void on_shot(unsigned *r)
{
    static int said;
    const struct pm_mode *m;
    /* Where the dispatch carries the mask: a 64-bit value in r2:r3 on Godzilla and Jaws;
     * a 32-bit value in r1 on TMNT Pro (item 137). The port says, with shot_mask_at (the
     * register of the low word) and shot_mask_bits. */
    unsigned at = (unsigned)pm_port_value("shot_mask_at", 2);
    uint64_t shot = at <= 3 ? r[at] : 0;
    if (at <= 2 && pm_port_value("shot_mask_bits", 64) == 64) shot |= (uint64_t)r[at + 1] << 32;
    note_thread("shot", &said);
    EACH_MODE(m) if (m->shot) { current = m; m->shot(shot); }
    current = 0;
}

static void roster_owed_ball_end(void);   /* item 146 */
static void on_ball_end(unsigned *r)
{
    static int said;
    const struct pm_mode *m;
    (void)r;
    note_thread("ball_end", &said);
    stock_ball_ends++;
    EACH_MODE(m) if (m->ball_end) { current = m; m->ball_end(); }
    current = 0;
    if (disp_linger_until) disp_release("the ball ended");
    bd_reset("the ball ended");
    magnet_let_go("the ball ended");          /* PAD-381 */
    roster_owed_ball_end();
}

/* ---- the battle roster (item 146, optional, title specific) ------------------------------------
 * The port's `site roster_start` is the game's "start the picked battle" call: Godzilla Pro 1.15's
 * RuleBattle::start_slot loads the battle's START from its vtable at 0x1220b8 (`ldr r3,[r0]` then
 * `ldr r3,[r3,#32]`) and calls it with r0 = the battle's mode object and r1 = its mode id. The
 * hook finds which roster slot holds that id (RuleBattle's slot vector: `data rule_battle`, the
 * vector's begin at +roster_vec_at, records of roster_record_size with the id at +roster_id_at),
 * and when a mode claimed the slot and takes the pick, swaps r0 for an object whose every virtual
 * is a no-op: the battle's START never runs, and the selection screen's own flow (its cursor,
 * timer, sounds, intro) is untouched. */
#define N_ROSTER 16
static int (*roster_fn[N_ROSTER])(unsigned slot);
static const struct pm_mode *roster_by[N_ROSTER];
static void roster_noop(void) {}
static unsigned roster_vtbl[80];
static unsigned roster_obj[4];
/* Per player 1-4: 0 = holds no pick; 1 = a mode took this player's pick and has not given it back;
 * 2 = given back while another player was up - done when this player is up again. */
static unsigned char roster_owed[5];

/* What pm_roster_done does, decided from the state and the game alone (tests lift it verbatim). The
 * rule's "battle over" acts on WHICHEVER player is up - and outside a game on fields that belong to
 * player 4 - so it may run only for a pick still held, only while the player who picked is up, only in
 * a game. Returns that player (1-4) when the site is to be called now, else 0 with *why set. */
static unsigned roster_give_back(unsigned char owed[5], int in_game, unsigned up, const char **why)
{
    unsigned q, held = 0;
    for (q = 1; q <= 4; q++) held |= owed[q];
    if (!held) {
        *why = "no pick is held - nothing to give back, the ramps are left alone";
        return 0;
    }
    if (!in_game) {
        for (q = 1; q <= 4; q++) owed[q] = 0;
        *why = "no game is being played - nothing is given back (a new game lights the ramps)";
        return 0;
    }
    if (up >= 1 && up <= 4 && owed[up]) {
        owed[up] = 0;
        *why = 0;
        return up;
    }
    for (q = 1; q <= 4; q++)
        if (owed[q] == 1) owed[q] = 2;
    *why = "another player is up - the pick is given back when the player who picked is up again";
    return 0;
}

/* The game stops its own battle at the end of a ball and gives the roster back then. A mode that
 * took a pick and did not call pm_roster_done by the end of that ball gets the same: otherwise the
 * player's ramps would stay dark, and no battle could be lit again, for the rest of the game. */
static void roster_owed_ball_end(void)
{
    unsigned q, held = 0;
    for (q = 1; q <= 4; q++) held |= roster_owed[q] == 1;
    if (!held) return;
    say("roster: the ball ended and the mode that took a pick never called pm_roster_done - calling it now");
    pm_roster_done();
}

/* every tick: a give-back that waited for its player happens once that player is up in a game; a game
 * that ends first drops it */
static void roster_deferred_tick(void)
{
    unsigned q, up, waiting = 0;
    for (q = 1; q <= 4; q++) waiting |= roster_owed[q] == 2;
    if (!waiting) return;
    up = pm_player();
    if (!pm_in_game() || (up >= 1 && up <= 4 && roster_owed[up] == 2)) pm_roster_done();
}

int pm_roster_slots(void)
{
    long n = pm_port_value("roster_slots", 0);
    return (can & PM_CAN_ROSTER) && n > 0 ? (int)(n < N_ROSTER ? n : N_ROSTER) : 0;
}

/* ---- the slot's spoken name (item 146 fix-1) ----
 * When the cursor lands on a slot the selection screen plays that slot's callout: a u16 sound request
 * id in its own slot table (Godzilla Pro 1.15 .data 0x6fc8a4, 32-byte records, the id at +28: 1888
 * "Ebirah!", 1918, 1894, 1910, then 0 for slots 4-6), and its code plays NOTHING for 0 (0x18d268:
 * `ldrh r3,[..,#28]; cmp r3,#0; popeq`). A claimed slot is made silent - the game never says the old
 * monster's name over the new art - until the mode sets an id of its own; releasing the slot puts the
 * game's id back. Port: `data roster_screen_table`, `value roster_screen_record_size`, `value
 * roster_callout_at`. Before the first write the table is checked: every slot's id below 0x4000 and at
 * least one nonzero, or it is never written (a wrong address in a port must not become a memory write). */
static unsigned roster_callout_was[N_ROSTER];   /* the game's id + 1, saved at the first write; 0 = the game's is there */

static unsigned short *roster_callout_word(unsigned slot)
{
    static int checked;                         /* 1 = the table looks right; -1 = it does not, never written */
    unsigned base = data("roster_screen_table"), n = (unsigned)pm_roster_slots(), k, any = 0;
    long size = pm_port_value("roster_screen_record_size", 0), at = pm_port_value("roster_callout_at", -1);
    if (!base || size < 4 || size > 4096 || at < 0 || at + 2 > size || slot >= n) return 0;
    if (!checked) {
        checked = 1;
        for (k = 0; k < n; k++) {
            unsigned w = *(const unsigned short *)(unsigned long)(base + k * (unsigned)size + (unsigned)at);
            if (w >= 0x4000) checked = -1;
            any |= w;
        }
        if (!any) checked = -1;
        say("roster: the selection screen's slot table at 0x%08x %s", base,
            checked > 0 ? "holds a callout id per slot - a claimed slot is silent until its mode names one"
                        : "does not look like one (an id over 0x3fff, or none set) - callouts are left alone");
    }
    if (checked < 0) return 0;
    return (unsigned short *)(unsigned long)(base + slot * (unsigned)size + (unsigned)at);
}

static int roster_callout_set(unsigned slot, unsigned id, const char *why)
{
    unsigned short *w = roster_callout_word(slot);
    if (!w || id > 0xffff) return 0;
    if (!roster_callout_was[slot]) roster_callout_was[slot] = (unsigned)*w + 1;
    if (*w != id) say("roster: slot %u's callout %u -> %u (%s)", slot, (unsigned)*w, id, why);
    *w = (unsigned short)id;
    return 1;
}

static void roster_callout_restore(unsigned slot)
{
    unsigned short *w;
    if (slot >= N_ROSTER || !roster_callout_was[slot] || !(w = roster_callout_word(slot))) return;
    if (*w != roster_callout_was[slot] - 1)
        say("roster: slot %u's callout %u -> %u (released: the game's again)", slot, (unsigned)*w, roster_callout_was[slot] - 1);
    *w = (unsigned short)(roster_callout_was[slot] - 1);
    roster_callout_was[slot] = 0;
}

int pm_roster_callout(unsigned slot, unsigned id)
{
    if (slot >= (unsigned)pm_roster_slots() || !roster_fn[slot] || roster_by[slot] != current) return 0;   /* the holder only */
    return roster_callout_set(slot, id, id ? "the mode's" : "silent");
}

int pm_roster_claim(unsigned slot, int (*on_pick)(unsigned slot))
{
    int was_held;
    if (!on_pick || slot >= (unsigned)pm_roster_slots()) return 0;     /* unsigned: a huge slot is out of range too */
    if (roster_fn[slot] && roster_by[slot] != current) return 0;
    was_held = roster_fn[slot] != 0;
    roster_fn[slot] = on_pick;
    roster_by[slot] = current;
    if (!was_held) roster_callout_set(slot, 0, "claimed: silent until the mode names one");   /* item 146 fix-1 */
    return 1;
}

void pm_roster_release(unsigned slot)
{
    if (slot < N_ROSTER && roster_by[slot] == current) {
        if (roster_fn[slot]) roster_callout_restore(slot);   /* item 146 fix-1 */
        roster_fn[slot] = 0; roster_by[slot] = 0;
    }
}

/* ---- the city's battle (item 146 fix-2) ----
 * When one of the game's battles stops, whatever the outcome, RuleBattle's stop (Pro 1.15 0x122c54) also
 * counts it in the city the player is in: RuleCities' 0x135394(cities, 1) ORs bit 1 into the player's mask
 * for that city, and a city whose four bits are set (0 tank attack, 1 the battle, 2 bridge attack, 3 tesla
 * strike) is complete. roster_done is only the ramps part, so without this a pick a mode took never counted
 * for the city. Port: `site roster_city_done`, `data rule_cities`, `value roster_city_bit`, and for the check
 * before the call (the game's function throws on a city index outside its table, which would take the game
 * down through our frame) `value roster_city_index_at`, `roster_city_vec_at`, `roster_city_record_size`.
 * A port without these lines does what it did before. Returns 1 when the call was made. */
static int roster_city_step(unsigned p)
{
    unsigned rc = data("rule_cities"), f = fn("roster_city_done"), idx, begin, end, *mask, was;
    long bit = pm_port_value("roster_city_bit", -1), at = pm_port_value("roster_city_index_at", -1);
    long vec = pm_port_value("roster_city_vec_at", -1), rec = pm_port_value("roster_city_record_size", 0);
    if (!f || !rc) return 0;
    if (bit < 0 || bit > 31 || at < 0 || vec < 0 || rec < 16 || p < 1 || p > 4) {
        say("roster: the city step is skipped - the port's city lines are incomplete (bit %ld, index at %ld, vector at %ld, record %ld) or no player is up (%u)",
            bit, at, vec, rec, p);
        return 0;
    }
    idx = *(const unsigned *)(unsigned long)(rc + (unsigned)at + 4 * p);
    begin = *(const unsigned *)(unsigned long)(rc + (unsigned)vec);
    end = *(const unsigned *)(unsigned long)(rc + (unsigned)vec + 4);
    if (!begin || end <= begin || idx >= 64 || rec > 64 || idx * (unsigned)rec + (unsigned)rec > end - begin) {
        say("roster: the city step is skipped - player %u's city %u is not in the city table (%u bytes)", p, idx,
            begin && end > begin ? end - begin : 0);
        return 0;
    }
    mask = (unsigned *)(unsigned long)(begin + idx * (unsigned)rec + (p - 1) * 4);
    was = *mask;
    ((void (*)(unsigned, unsigned))(unsigned long)f)(rc, (unsigned)bit);
    say("roster: the pick counts as the battle of player %u's city %u (its mask %x -> %x)", p, idx, was, *mask);
    return 1;
}

void pm_roster_done(void)
{
    struct site *x = site("roster_done");
    const char *why = 0;
    unsigned up = pm_player();
    if (!roster_give_back(roster_owed, pm_in_game(), up, &why)) {
        say("roster: pm_roster_done (player %u up): %s", up, why ? why : "-");
        return;
    }
    if (!(can & PM_CAN_ROSTER) || !x || !x->ok) return;
    ((void (*)(unsigned))(unsigned long)x->addr)(data("rule_battle"));
    say("roster: battle over for player %u (roster_done: qualified cleared, ramps lit)", pm_player());
    roster_city_step(pm_player());                              /* item 146 fix-2: and the city counts it */
}

static void on_roster_start(unsigned *r)
{
    const unsigned *vec;
    unsigned slot, n = (unsigned)pm_roster_slots(), id = r[1];
    unsigned rec = (unsigned)pm_port_value("roster_record_size", 12), at = (unsigned)pm_port_value("roster_id_at", 4);
    const struct pm_mode *was = current;
    int took;
    static int said;
    for (slot = 0; slot < n && !roster_fn[slot]; slot++) ;
    if (slot >= n) return;          /* no mode holds a slot: read nothing, the game's battle runs untouched */
    note_thread("roster pick", &said);
    vec = *(const unsigned **)(unsigned long)(data("rule_battle") + (unsigned)pm_port_value("roster_vec_at", 8));
    for (slot = 0; vec && slot < n && vec[(slot * rec + at) / 4] != id; slot++) ;
    if (!vec || slot >= n) { say("roster: a battle started (mode id %u) that is in no slot", id); return; }
    if (!roster_fn[slot]) { say("roster: slot %u picked (mode id %u): the game's battle", slot, id); return; }
    current = roster_by[slot];
    {
        unsigned up = pm_player();
        if (up >= 1 && up <= 4) roster_owed[up] = 1;   /* before the call: a mode that gives the pick back at once clears it */
        took = roster_fn[slot](slot);
        if (!took && up >= 1 && up <= 4) roster_owed[up] = 0;
    }
    current = was;
    if (took) {
        unsigned k, p = pm_player();
        for (k = 0; k < sizeof roster_vtbl / sizeof roster_vtbl[0]; k++)
            roster_vtbl[k] = (unsigned)(unsigned long)roster_noop;
        roster_obj[0] = (unsigned)(unsigned long)roster_vtbl;
        r[0] = (unsigned)(unsigned long)roster_obj;
        /* The battle would have held the roster: while one of the game's battles runs the ramps
         * stay dark and the scoop opens nothing, and when it stops RuleBattle clears the player's
         * "battle qualified" byte and lights the ramps again. Ours is not one of the game's modes,
         * so clear the byte now - the ramps were put out when the battle qualified - and leave the
         * re-lighting to pm_roster_done() when the mode ends. (Run2 on Pro 1.15 re-lit at the pick:
         * the mode's own ramp shots qualified a battle and the scoop re-opened the screen mid-mode.) */
        if (p >= 1 && p <= 4 && roster_owed[p] && pm_port_value("roster_qualified_at", 0)) {   /* not when it gave the pick back at once */
            unsigned char *q = (unsigned char *)(unsigned long)(data("rule_battle") + (unsigned)pm_port_value("roster_qualified_at", 0) + p);
            say("roster: player %u qualified byte %u cleared; the ramps stay dark until the mode calls pm_roster_done", p, *q);
            *q = 0;
        }
    }
    say("roster: slot %u picked (mode id %u): %s", slot, id,
        took ? "claimed - the game's battle does not start" : "claimed but not taken - the game's battle runs");
}

/* ---- events (item 147) ------------------------------------------------------------------------
 * The game's rules talk through one event bus: dispatch(id, arg) calls every handler
 * subscribed to id (0..207). The port names the events measured for its build, in two kinds:
 *   site  hook_dispatch <addr> <w0> <w1>     the bus's dispatch
 *   event <name> <id>                         a bus id, e.g. `event ball_start 0x25`
 *   event <name> site <site name>             a CALL of a port site is the event: for what a
 *                                             title does without a broadcast (its skill shot
 *                                             award, a multiball mode's start)
 * The hooks only COUNT, lock-free, on whichever thread runs them; the tick hands each new
 * firing to every mode's .event. So a mode never runs inside the game's broadcast, and its
 * callbacks keep to the tick thread. A dispatch is counted whether or not one of the game's
 * handlers vetoes the rest. A site event's id is 208 + its place among the site events.
 * Optional: a port without hook_dispatch or site events just has no events. */
#define N_EVENTS      48
#define N_BUS_IDS     208
#define N_SITE_EVENTS 8
#define N_EVENT_IDS   (N_BUS_IDS + N_SITE_EVENTS)

static struct { char name[40]; unsigned id; char site[40]; int armed; } event_names[N_EVENTS];
static int n_event_names, n_site_events;
static volatile unsigned event_fired[N_EVENT_IDS];
static unsigned event_delivered[N_EVENT_IDS];

static unsigned event_count(int id) { return id >= 0 && id < N_EVENT_IDS ? event_fired[id] : 0; }

static void event_line(const char *s)
{
    int ok = 0;
    char how[8];
    const char *t;
    if (n_event_names >= N_EVENTS) return;
    s = word(s, event_names[n_event_names].name, sizeof event_names[n_event_names].name);
    t = word(s, how, sizeof how);
    if (str_eq(how, "site")) {
        if (n_site_events >= N_SITE_EVENTS) return;
        word(t, event_names[n_event_names].site, sizeof event_names[n_event_names].site);
        if (!event_names[n_event_names].name[0] || !event_names[n_event_names].site[0]) return;
        event_names[n_event_names].id = N_BUS_IDS + (unsigned)n_site_events++;
        n_event_names++;
        return;
    }
    event_names[n_event_names].id = (unsigned)number(&s, &ok);
    event_names[n_event_names].site[0] = 0;
    if (ok && event_names[n_event_names].name[0] && event_names[n_event_names].id < N_BUS_IDS)
        n_event_names++;
}

int pm_event(const char *name)
{
    int i;
    if (!(can & PM_CAN_EVENTS)) return -1;
    for (i = 0; i < n_event_names; i++)
        if (event_names[i].armed && str_eq(event_names[i].name, name)) return (int)event_names[i].id;
    return -1;
}

const char *pm_event_name(unsigned id)
{
    int i;
    for (i = 0; i < n_event_names; i++)
        if (event_names[i].id == id) return event_names[i].name;
    return 0;
}

/* A port with no ball_end site ends a ball on a bus id instead (`value ball_end_event 0x34`; the
 * core takes hook_dispatch then, core_of_port). It is handed to the modes from the dispatch itself,
 * as the game's own handler of that id would run: on The Beatles 1.29 the ball_end site IS a bus
 * 0x34 handler, called from inside this dispatch. -1: the ball_end site is the end of a ball. */
static int ball_end_event = -1;

static void on_event_dispatch(unsigned *r)
{
    static volatile int said;
    if (r[0] < N_BUS_IDS) __sync_fetch_and_add(&event_fired[r[0]], 1u);
    if (!said && __sync_bool_compare_and_swap(&said, 0, 1))
        say("event dispatch runs on thread %ld (first seen)", syscall(SYS_GETTID));
    if (ball_end_event >= 0 && r[0] == (unsigned)ball_end_event) on_ball_end(r);
}

/* one counter per site event: the trampoline hands a logger only the registers */
#define SITE_EVENT(k) static void on_site_event##k(unsigned *r) { (void)r; __sync_fetch_and_add(&event_fired[N_BUS_IDS + k], 1u); }
SITE_EVENT(0) SITE_EVENT(1) SITE_EVENT(2) SITE_EVENT(3) SITE_EVENT(4) SITE_EVENT(5) SITE_EVENT(6) SITE_EVENT(7)
static const hook_fn site_event_hooks[N_SITE_EVENTS] = {
    on_site_event0, on_site_event1, on_site_event2, on_site_event3,
    on_site_event4, on_site_event5, on_site_event6, on_site_event7,
};

static void events_deliver(void)
{
    const struct pm_mode *m;
    int i, j;
    if (!(can & PM_CAN_EVENTS)) return;
    for (i = 0; i < n_event_names; i++) {
        unsigned id = event_names[i].id, now, n;
        if (!event_names[i].armed) continue;
        now = event_fired[id];
        n = now - event_delivered[id];
        if (!n) continue;
        /* two names for one id deliver once */
        for (j = 0; j < i && !(event_names[j].armed && event_names[j].id == id); j++) ;
        if (j < i) continue;
        event_delivered[id] = now;
        if (n > 8) n = 8;                            /* a flood is not N separate events */
        while (n--) EACH_MODE(m) if (m->event) { current = m; m->event(id); }
        current = 0;
    }
}

static void events_arm(void)
{
    struct site *bus = site("hook_dispatch");
    int i, bus_names = 0, armed = 0, bus_hooked = 0;
    unsigned id;
    if (!n_event_names && !bus) return;
    for (id = 0; id < N_EVENT_IDS; id++) event_delivered[id] = event_fired[id];
    for (i = 0; i < n_event_names; i++) bus_names += !event_names[i].site[0];
    if (bus_names || ball_end_event >= 0) {
        if (!bus || !bus->ok) say("bus events off: %s", !bus ? "the port has no hook_dispatch" : "hook_dispatch does not match this build");
        else if ((bus_hooked = hook(bus->addr, on_event_dispatch)) != 0) {
            for (i = 0; i < n_event_names; i++)
                if (!event_names[i].site[0]) { event_names[i].armed = 1; armed++; }
        }
        if (ball_end_event >= 0 && !bus_hooked)
            say("ball end: the dispatch could not be hooked - no mode sees a ball end");
    }
    for (i = 0; i < n_event_names; i++) {
        struct site *x;
        if (!event_names[i].site[0]) continue;
        x = site(event_names[i].site);
        if (!x || !x->ok) {
            say("event %s off: site %s is %s", event_names[i].name, event_names[i].site, !x ? "not in the port" : "wrong for this build");
            continue;
        }
        if (hook(x->addr, site_event_hooks[event_names[i].id - N_BUS_IDS])) { event_names[i].armed = 1; armed++; }
    }
    if (armed) can |= PM_CAN_EVENTS;
    say("events: %d of %d named events armed%s", armed, n_event_names,
        bus && bus->ok && bus_names ? ", dispatch hooked" : "");
}

/* ---- shots from switches (optional) ---------------------------------------------------------------
 * A title whose rules are plain C sends a shot only for what its rules score as one: The Beatles
 * 1.29's shot dispatch never carries its four standups (73-76) or its lanes (48-51). The framework
 * itself broadcasts every switch whose descriptor flags ask for it, from its switch drain, through
 * one small function per flag with r0 = the switch id (The Beatles: 0x96e68 for flag 0x2000, 0x96f08
 * for flag 0x1000; Godzilla Pro 1.16's is 0x1e1508). The port names each as a site whose name starts
 * `switch_hit` (switch_hit, switch_hit2 ...; the id's register in value switch_hit_at, r0 if absent)
 * and maps switch ids to shot bits of its own, bits the rules' dispatch never sends:
 *   switch <id> <mask> <name>      e.g. `switch 73 0x100000000 Target 1`
 * The name is also a named shot (pm_shot), unless a shot of that name is in the port already. Like
 * the events, a hit is only COUNTED where it happens, lock-free; the tick hands it to every mode's
 * .shot, so a mode's callbacks keep to the tick thread. Only a switch the game's flags broadcast can
 * be mapped (on The Beatles not the slingshots, whose descriptors ask for nothing). */
static volatile unsigned switch_fired[N_SWITCH_IDS];
static unsigned switch_delivered[N_SWITCH_IDS];
static unsigned switch_at;                    /* the register holding the switch id */

static void on_switch_hit(unsigned *r)
{
    static volatile int said;
    unsigned id = r[switch_at];
    if (id < N_SWITCH_IDS) __sync_fetch_and_add(&switch_fired[id], 1u);
    if (!said && __sync_bool_compare_and_swap(&said, 0, 1))
        say("switch hits run on thread %ld (first seen: switch %u)", syscall(SYS_GETTID), id);
}

/* every tick: each switch hit since the last, as its shots (all the lines naming that switch) */
static void switches_deliver(void)
{
    const struct pm_mode *m;
    int i, j;
    if (!(can & PM_CAN_SWITCH_SHOTS)) return;
    for (i = 0; i < port.n_switch; i++) {
        unsigned id = port.sw[i].id, now = switch_fired[id], n = now - switch_delivered[id];
        uint64_t mask = 0;
        if (!n) continue;
        switch_delivered[id] = now;
        for (j = i; j < port.n_switch; j++)
            if (port.sw[j].id == id) mask |= port.sw[j].mask;
        if (n > 8) n = 8;                            /* a flood is not N separate hits */
        while (n--) EACH_MODE(m) if (m->shot) { current = m; m->shot(mask); }
        current = 0;
    }
}

static int is_switch_hit(const char *name)
{
    static const char want[] = "switch_hit";
    unsigned k;
    for (k = 0; k + 1 < sizeof want; k++)
        if (name[k] != want[k]) return 0;
    return 1;
}

/* ---- shots from the switch drain (optional; any build) ----------------------------------------------
 * Every Spike 2 build's framework runs one switch drain per tick, which hands the game each switch edge
 * the node boards reported. For every edge it calls one small per-switch function with r0 = the switch
 * id: the port's `site switch_edge`. Hooking it gives EVERY playfield switch, where switch_hit gives only
 * the ones whose descriptors ask for a broadcast, and it is the same code in every build of a framework
 * generation (portswitch.py finds it by one signature per generation). What the edge was is read from
 * the game's own tables, through the port:
 *   site  switch_drain <addr> <w0> <w1>   the drain itself, never hooked: an edge counts only when
 *   value switch_drain_size <bytes>       switch_edge returns into it (the game also calls switch_edge
 *                                         from its switch resets, which are not edges)
 *   data  switch_records <addr>           the pointer to the per-switch records, indexed by switch id
 *   data  switch_count <addr>             the number of switches (u32)
 *   value switch_record_size <bytes>
 *   value switch_level_at <offset>        the switch's level byte (0/1): in the record, or - with
 *   value switch_level_via <offset>       - in the state the record points at from this offset
 *   value switch_level_before 1           the byte still holds the level from BEFORE this edge (A)
 *   value switch_desc_via <offset>        the record points at the switch's descriptor from here (B);
 *                                         without it the record IS the descriptor (A)
 *   value switch_flags_at <offset>        the descriptor's u16 edge flags: 0x400 = the game's handler runs
 *                                         on the level-0 edge, 0x800 = on the level-1 edge
 *   value switch_polarity_at <offset>     the descriptor's u16 whose bit 2 says the switch is active high
 *   data  mode_mask <addr>                (optional) the u16 the drain tests before a switch's handler
 * A HIT is the edge the game's own handler runs on; for a switch whose handler runs on both edges, or
 * that has none (slingshots, pop bumpers), the edge to its active level (closed). With a mode_mask the
 * drain's own test applies too: the mask is 0, or shares a bit with the switch's flags - so attract,
 * the bonus count and a tilt give no hits. A hit is counted, lock-free, like a switch_hit, and the tick
 * hands it to the modes through the port's `switch` lines. */
static struct {
    unsigned records, count, mode_mask, drain, drain_end;
    long size, level_at, level_via, level_before, desc_via, flags_at, polarity_at;
} edge;

static int have_values(const char *const *names);   /* the gate section below */

/* 1 when (id, the edge's level, the switch's descriptor fields, the mode mask) is a hit, the rule above
 * (tests lift it verbatim) */
static int edge_is_hit(unsigned level, unsigned flags, unsigned polarity, int have_mask, unsigned mask)
{
    unsigned closed = (flags & 0xc00u) == 0x400u ? 0u : (flags & 0xc00u) == 0x800u ? 1u : (polarity & 4u) ? 1u : 0u;
    if ((level & 1u) != closed) return 0;
    return !have_mask || !mask || (mask & flags) != 0;
}

static long edge_log_left;                   /* value switch_edge_log N: log the first N edges (proving a port) */

static void on_switch_edge(unsigned *r)
{
    static volatile int said;
    unsigned id = r[0], lr = r[5], base, rec, st, level, desc, flags, pol, mask;
    int hit, playing;
    if (lr <= edge.drain || lr > edge.drain_end) return;           /* not from the drain: not an edge */
    if (!id || id >= N_SWITCH_IDS || (edge.count && id >= *(const unsigned *)(unsigned long)edge.count)) return;
    base = *(const unsigned *)(unsigned long)edge.records;
    if (!base) return;
    rec = base + id * (unsigned)edge.size;
    st = edge.level_via >= 0 ? *(const unsigned *)(unsigned long)(rec + (unsigned)edge.level_via) : rec;
    desc = edge.desc_via >= 0 ? *(const unsigned *)(unsigned long)(rec + (unsigned)edge.desc_via) : rec;
    if (!st || !desc) return;
    level = *(const unsigned char *)(unsigned long)(st + (unsigned)edge.level_at);
    if (edge.level_before) level ^= 1u;
    flags = *(const unsigned short *)(unsigned long)(desc + (unsigned)edge.flags_at);
    pol = *(const unsigned short *)(unsigned long)(desc + (unsigned)edge.polarity_at);
    mask = edge.mode_mask ? *(const unsigned short *)(unsigned long)edge.mode_mask : 0u;
    hit = edge_is_hit(level, flags, pol, edge.mode_mask != 0, mask);
    playing = pm_in_game();                  /* attract, a tilt: no player up for a mode to score */
    if (edge_log_left > 0 && __sync_sub_and_fetch(&edge_log_left, 1) >= 0)
        say("edge: switch %u level %u (flags 0x%04x, polarity 0x%04x, mode mask 0x%04x, in game %d)%s", id, level & 1u,
            flags, pol, mask, playing, hit && playing ? " - a hit" : "");
    if (!hit || !playing) return;
    __sync_fetch_and_add(&switch_fired[id], 1u);
    if (!said && __sync_bool_compare_and_swap(&said, 0, 1))
        say("switch edges run on thread %ld (first hit: switch %u)", syscall(SYS_GETTID), id);
}

/* The switch_edge site's tables, checked against the process's mappings (read at the gate: the game's
 * own globals are mapped by then). 0 with *why when the port lacks one or one is not mapped. */
static int edge_arm(const char **why)
{
    struct site *d = site("switch_drain");
    static const char *const need[] = { "switch_drain_size", "switch_record_size", "switch_level_at",
                                        "switch_flags_at", "switch_polarity_at", 0 };
    edge.records = data("switch_records");
    edge.count = data("switch_count");
    edge.mode_mask = data("mode_mask");
    if (!d || !d->ok) { *why = !d ? "the port has no switch_drain" : "switch_drain does not match this build"; return 0; }
    if (!have_values(need)) { *why = "the port lacks a switch_* value"; return 0; }
    if (!edge.records || !maps_has(edge.records, 4, MAP_R)) { *why = "switch_records is not mapped"; return 0; }
    if (edge.count && !maps_has(edge.count, 4, MAP_R)) edge.count = 0;
    if (edge.mode_mask && !maps_has(edge.mode_mask, 2, MAP_R)) edge.mode_mask = 0;
    edge.drain = d->addr;
    edge.drain_end = d->addr + (unsigned)pm_port_value("switch_drain_size", 0);
    edge.size = pm_port_value("switch_record_size", 0);
    edge.level_at = pm_port_value("switch_level_at", 0);
    edge.level_via = pm_port_value("switch_level_via", -1);
    edge.level_before = pm_port_value("switch_level_before", 0);
    edge.desc_via = pm_port_value("switch_desc_via", -1);
    edge.flags_at = pm_port_value("switch_flags_at", 0);
    edge.polarity_at = pm_port_value("switch_polarity_at", 0);
    edge_log_left = pm_port_value("switch_edge_log", 0);
    if (edge.size <= 0 || edge.size > 4096 || edge.drain_end <= edge.drain) { *why = "a switch_* value is out of range"; return 0; }
    return 1;
}

static void switches_arm(void)
{
    long at = pm_port_value("switch_hit_at", 0);
    int i, sites = 0, hooked = 0;
    unsigned id;
    struct site *e = site("switch_edge");
    const char *why = 0;
    if (!port.n_switch) return;                  /* a switch_hit site with no switch lines: nothing to hand on */
    switch_at = at >= 0 && at <= 3 ? (unsigned)at : 0;
    for (id = 0; id < N_SWITCH_IDS; id++) switch_delivered[id] = switch_fired[id];
    if (e) {                                     /* the drain's edges: every switch; the switch_hit sites stay unhooked */
        if (e->ok && edge_arm(&why) && hook(e->addr, on_switch_edge)) {
            can |= PM_CAN_SWITCH_SHOTS;
            say("switch shots: %d switch line(s) hand their shots to the modes; the switch drain's edges (switch_edge "
                "0x%08x, from the drain 0x%08x..0x%08x%s)", port.n_switch, e->addr, edge.drain, edge.drain_end,
                edge.mode_mask ? ", the game's mode mask applied" : ", no mode mask");
        } else {
            say("switch shots off: %s", !e->ok ? "switch_edge does not match this build" : why ? why : "switch_edge could not be hooked");
        }
        return;
    }
    for (i = 0; i < port.n_site; i++) {
        if (!is_switch_hit(port.site[i].name)) continue;
        sites++;
        if (port.site[i].ok && hook(port.site[i].addr, on_switch_hit)) hooked++;
    }
    if (hooked) {
        can |= PM_CAN_SWITCH_SHOTS;
        say("switch shots: %d switch line(s) hand their shots to the modes; %d of %d switch_hit site(s) hooked (the id in r%u)",
            port.n_switch, hooked, sites, switch_at);
    } else {
        say("switch shots off: %s", sites ? "no switch_hit site matches this build" : "the port has no switch_hit site");
    }
}

/* Which sites and data each capability needs; all must be present and verified. */
static int have_sites(const char *const *names)
{
    for (; *names; names++) {
        struct site *x = site(*names);
        if (!x || !x->ok) return 0;
    }
    return 1;
}

static int have_data(const char *const *names)
{
    for (; *names; names++)
        if (!data(*names)) return 0;
    return 1;
}

static int have_values(const char *const *names)
{
    int i, found;
    for (; *names; names++) {
        for (i = 0, found = 0; i < port.n_value; i++)
            if (str_eq(port.value[i].name, *names)) found = 1;
        if (!found) return 0;
    }
    return 1;
}

/* ---- the gate ------------------------------------------------------------------------------------
 * The CORE is what every mode needs; without it nothing is hooked. A port names one of each:
 *   the tick             site tick
 *   a shot source        site shot_dispatch, or (a title whose rules send no shot for its switches)
 *                        site switch_edge (the framework's switch drain: any build) or site switch_hit,
 *                        with `switch` lines
 *   the end of a ball    site ball_end, or value ball_end_event (a bus id) with site hook_dispatch
 *   the score            site score_add + data scores (64-bit points in r2:r3, u64 scores), or
 *                        site score_add32 + data scores32 (32-bit points in r1, u32 scores: The Beatles).
 *                        The names carry the calling convention, so a runtime without the 32-bit
 *                        form finds no core score_add in such a port and hooks nothing
 *   the player up        data cur_player
 * (tests lift it verbatim) Fills s[] and d[] with the core sites and data this port uses, 0-ended. */
static void core_of_port(const char *s[8], const char *d[4])
{
    int n = 0, s32 = site("score_add32") != 0;
    long ev = pm_port_value("ball_end_event", -1);
    s[n++] = "tick";
    s[n++] = !site("shot_dispatch") && site("switch_edge") && port.n_switch ? "switch_edge"
           : !site("shot_dispatch") && site("switch_hit") && port.n_switch ? "switch_hit" : "shot_dispatch";
    s[n++] = !site("ball_end") && ev >= 0 && ev < N_BUS_IDS ? "hook_dispatch" : "ball_end";
    s[n++] = s32 ? "score_add32" : "score_add";
    s[n] = 0;
    d[0] = "cur_player";
    d[1] = s32 ? "scores32" : "scores";
    d[2] = 0;
}

/* One site against the running game: first that it lies inside the game's own code (nothing
 * outside is ever read), then its words. (tests lift it verbatim) */
static int site_check(struct site *x)
{
    if (!maps_has(x->addr, 8, MAP_R | MAP_X | MAP_GAME)) {
        say("site %s 0x%08x: not in the game's code - not read", x->name, x->addr);
        return x->ok = 0;
    }
    x->ok = words_match(x);
    if (!x->ok)
        say("site %s 0x%08x: expected %08x %08x, found %08x %08x",
            x->name, x->addr, x->w0, x->w1,
            ((const unsigned *)(unsigned long)x->addr)[0], ((const unsigned *)(unsigned long)x->addr)[1]);
    return x->ok;
}

/* The core sites first: when one is missing, outside the game's code or not this build's, no other
 * site is read and the port is refused. Then every other site, each switching off only its own
 * capability. 1 = this game's port. (tests lift it verbatim) */
static int port_gate(void)
{
    const char *cs[8], *cd[4];
    int i, j, bad = 0, core = 1;
    core_of_port(cs, cd);
    for (i = 0; cs[i]; i++) {
        struct site *x = site(cs[i]);
        if (!x) {
            say("core site %s: not in the port", cs[i]);
            core = 0;
        } else if (!site_check(x)) {
            bad++;
            core = 0;
        }
    }
    for (i = 0; cd[i]; i++)
        if (!data(cd[i])) {
            say("core data %s: not in the port", cd[i]);
            core = 0;
        }
    if (!core) {
        say("NOT THIS GAME'S PORT - the core functions do not match (%d site(s) wrong). "
            "Nothing is hooked; the game runs stock.", bad);
        return 0;
    }
    for (i = 0; i < port.n_site; i++) {
        for (j = 0; cs[j] && !str_eq(cs[j], port.site[i].name); j++) ;
        if (!cs[j]) site_check(&port.site[i]);          /* a core site was checked above */
    }
    return 1;
}

/* ---- Insider Connected: no score leaves a machine that carries modes ---------------------------
 * A mode scores through the game's own score_add, so its points are not stock scoring, and the
 * card's validation bypass makes the game grade itself P/P/P: Insider Connected would take those
 * games as real. The game builds every report itself and hands it to Stern's agent (conagent)
 * over a local socket; the login, the heartbeat and the message of the day are the agent's own
 * and are not touched. Two sites, the same on every build measured (36 of 36, 2026-09-26):
 *   agent_header  the request header constructor: r1 is the endpoint path ("/api/v3/game/...")
 *   agent_begin   the message-begin thunk every sender calls next: refused (r0 = 1) for a score
 *                 report, and the sender takes its own failure path - it logs "Failed to begin
 *                 construction of GAME_SESSION_END message", the outgoing queue drops the entry
 *                 (a failed send is dequeued, never retried) and the game plays on.
 * What is refused: the game session (start, update, end: the players and their scores), the
 * high-score table report, and the game-event stream achievements are earned from. Everything
 * else the game sends (audits, alerts, home team, player properties, the free-game code, the
 * configuration and descriptor queries) goes out as before.
 * The gate is REQUIRED: a port without both sites arms nothing (insider_arm), and the app refuses
 * to put modes on a card whose port lacks them (mode_write.card_refusal). */
#define INSIDER_ENDPOINT_MAX 96
static char insider_endpoint[INSIDER_ENDPOINT_MAX];
static unsigned insider_dropped[4];
static const char *const INSIDER_BLOCKED[] = {
    "/api/v3/game/session_",              /* session_start, session_update, session_end */
    "/api/v1/game/high_score_events",     /* the high-score table (HSTD_REPORT) */
    "/ingest/v1/game/game_events",        /* the event stream (GAME_EVENTS): achievements */
    0
};

static int str_starts(const char *s, const char *prefix)
{
    if (!s || !prefix) return 0;
    while (*prefix && *s == *prefix) { s++; prefix++; }
    return *prefix == 0;
}

/* 1 + the index of the blocked prefix an endpoint starts with, 0 for one that may go out.
 * (tests lift it verbatim) */
static int insider_blocked(const char *endpoint)
{
    int i;
    for (i = 0; INSIDER_BLOCKED[i]; i++)
        if (str_starts(endpoint, INSIDER_BLOCKED[i])) return i + 1;
    return 0;
}

static void on_agent_header(unsigned *r)
{
    const char *s = (const char *)(unsigned long)r[1];
    if (s && s[0] == '/') str_copy(insider_endpoint, sizeof insider_endpoint, s, INSIDER_ENDPOINT_MAX - 1);
    else insider_endpoint[0] = 0;
}

static int on_agent_begin(unsigned *r)
{
    int i = insider_blocked(insider_endpoint);
    unsigned n;
    (void)r;
    if (!i) return 0;
    n = ++insider_dropped[i - 1];
    if (n == 1)
        say("insider: %s is not sent to Insider Connected (the game logs a failed message and plays on)",
            insider_endpoint);
    else if ((n & 15) == 0)
        say("insider: %s not sent, %u times", insider_endpoint, n);
    insider_endpoint[0] = 0;
    return 1;
}

/* 1 = the gate is up. 0 = this port cannot keep scores off Insider Connected: NOTHING is hooked
 * and the game runs stock, whatever else the port names. */
static int insider_arm(void)
{
    static const char *const s[] = { "agent_header", "agent_begin", 0 };
    if (!have_sites(s)) {
        say("insider: the port has no agent_header/agent_begin, so a mode's points could reach "
            "Insider Connected as real scores - NOTHING IS HOOKED, the game runs stock");
        return 0;
    }
    if (!hook(fn("agent_header"), on_agent_header) || !hook_veto(fn("agent_begin"), on_agent_begin)) {
        say("insider: the gate could not be hooked - NOTHING IS HOOKED, the game runs stock");
        return 0;
    }
    say("insider: score reports stay on this machine (the game session, high scores and game "
        "events; agent_header 0x%08x, agent_begin 0x%08x); the login and the rest of Insider "
        "Connected are untouched", fn("agent_header"), fn("agent_begin"));
    return 1;
}

__attribute__((constructor))
static void pad_mode_start(void)
{
    const struct pm_mode *m;
    struct site *tick;
    int modes = 0;
    if (!port_load()) return;                       /* no port: stay out of the way */
    tick = site("tick");
    if (!tick) return;
    maps_read();                                    /* the process's mappings, read once */
    if (!is_game_process(tick->addr)) return;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    log_fd = open("/dump/mode.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    say("port %s: %s %s, %d sites, %d shots", port.path, port.game, port.version, port.n_site, port.n_shot);
    if (port.too_long) say("port: longer than %d bytes - the lines after that are not read", PORT_MAX);
    if (port.dropped)
        say("port: %d line(s) not read - a table is full (sites %d of %d, data %d of %d, values %d of %d, shots %d of %d, switches %d of %d)",
            port.dropped, port.n_site, N_SITES, port.n_data, N_DATA, port.n_value, N_VALUES, port.n_shot, N_SHOTS,
            port.n_switch, N_SWITCHES);
    if (!port_gate()) return;
    if (!insider_arm()) return;               /* no score gate, no modes: see insider_arm */
    {
        static const char *const callout_s[] = { "callout", "callout_nth", 0 };
        static const char *const light_s[] = { "light_run", "lamp_group", "show_priority", 0 };
        static const char *const light_d[] = { "event_head", "event_current", 0 };
        static const char *const screen_s[] = { "string_new", "resource_get", "dynamic_cast",
                                                "find_node", "find_text", "set_text", 0 };
        static const char *const screen_d[] = { "resource_manager", "typeinfo_resource",
                                                "typeinfo_scene_player", 0 };
        static const char *const clip_s[] = { "clip_play", "clip_stop", "video_player", "video_surface",
                                              "surface_state", "player_advance", "display_draw", 0 };
        static const char *const clip_d[] = { "display_holder", 0 };
        static const char *const sound_s[] = { "sound_lookup", "callout", 0 };
        static const char *const msg_d[] = { "message_count", "message_remap", "message_table", 0 };
        static const char *const award_s[] = { "award_screen", 0 };
        static const char *const award_d[] = { "award_screen_arg", 0 };
        static const char *const light_v[] = { "event_next", "event_flags", "event_show_flag",
                                               "event_show_id", "light_owner", 0 };
        static const char *const screen_v[] = { "scene_player_scene", "node_visible_vfn", 0 };
        static const char *const clip_v[] = { "display_at", "surface_playing", 0 };
        static const char *const award_v[] = { "award_message_at", "award_value_at", "award_count_at", 0 };
        if (have_sites(callout_s)) can |= PM_CAN_CALLOUT;
        if (have_sites(light_s) && have_data(light_d) && have_values(light_v)) can |= PM_CAN_LIGHTS;
        if (have_sites(screen_s) && have_data(screen_d) && have_values(screen_v)) can |= PM_CAN_SCREENS;
        static const char *const clip2_s[] = { "surface_find", "surface_set_video", "surface_play", "surface_stop",
                                               "surface_state", "string_new", "resource_get", "dynamic_cast", 0 };
        static const char *const clip2_d[] = { "resource_manager", "typeinfo_resource", "typeinfo_scene_player", 0 };
        static const char *const clip2_v[] = { "surface_playing", "scene_player_scene", 0 };
        static const char *const clip3_s[] = { "layer_add", "layer_remove", "layer_video", "layer_playing",
                                               "string_new", 0 };
        static const char *const clip3_d[] = { "layer_stack", "video_layer", 0 };
        static const char *const clip3_v[] = { "clip_layer_priority", "layer_video_at", 0 };
        if (have_sites(clip_s) && have_data(clip_d) && have_values(clip_v)) can |= PM_CAN_CLIPS;
        else if (have_sites(clip3_s) && have_data(clip3_d) && have_values(clip3_v)) {
            can |= PM_CAN_CLIPS;          /* item 164: clip layer, the game's full-screen video layer */
            clip_layer = 1;
        } else if (have_sites(clip2_s) && have_data(clip2_d) && have_values(clip2_v)
                 && (pm_scene_id("video_bank") || site("video_surface"))) {
            can |= PM_CAN_CLIPS;          /* item 164: clip v2, the surface itself */
            clip_v2 = 1;
        }
        if (have_sites(sound_s)) can |= PM_CAN_OWN_SOUND;
        if (have_data(msg_d)) can |= PM_CAN_MESSAGES;
        if (have_sites(award_s) && have_data(award_d) && have_values(award_v)) can |= PM_CAN_AWARD_SCREEN;
    }
    hook(fn("tick"), on_tick);
    if (fn("shot_dispatch")) hook(fn("shot_dispatch"), on_shot);
    if (site("ball_end")) {
        hook(fn("ball_end"), on_ball_end);
    } else {                                  /* the core took the event's way (core_of_port) */
        ball_end_event = (int)pm_port_value("ball_end_event", -1);
        say("ball end: the game's event 0x%x, from its dispatch (the port has no ball_end site)",
            (unsigned)ball_end_event);
    }
    display_arm();                            /* item 154 display: the clip_play hook, display priority */
    block_arm();                              /* PAD-347: a mode may keep the game's modes from starting */
    backdrop_arm();                           /* hud-layers: a clip behind the HUD */
    frame_arm();                              /* PAD-301: a full-screen clip drawn at the frame hand-over */
    if (can & PM_CAN_OWN_SOUND) hook(fn("sound_lookup"), on_sound_lookup);
    /* item 163: with /dump/soundlog.on there at the start, every request the game's sound worker
     * takes is logged ("[pad] sound <request> <n>"), so a check game is also the sound census that
     * says which stock requests a build never plays (the carriers a mode's own sounds ride on) */
    if (fn("sound_worker") && pm_trigger("soundlog.on") && hook(fn("sound_worker"), on_sound_worker))
        say("sound log: every request the sound worker takes (soundlog.on)");
    events_arm();
    switches_arm();                           /* shots from switches, when the port maps some */
    {   /* item 146: the battle roster, when the port has one */
        static const char *const roster_s[] = { "roster_start", "roster_done", 0 };   /* both: a pick taken must be given back */
        static const char *const roster_d[] = { "rule_battle", 0 };
        static const char *const roster_v[] = { "roster_slots", 0 };
        if (have_sites(roster_s) && have_data(roster_d) && have_values(roster_v) && hook(fn("roster_start"), on_roster_start)) {
            can |= PM_CAN_ROSTER;
            say("roster: %d slots, the battle start at 0x%08x is hooked", pm_roster_slots(), fn("roster_start"));
        }
    }
    lamps_arm();                                    /* the port's named inserts (lights section) */
    stock_arm();                                    /* item 160: the port's `rule` lines (stock rules section) */
    multiball_arm();                                /* item 167: a multiball of the mode's own */
    coils_arm();                                    /* PAD-381: a magnet grab of the mode's own */
    scoop_arm();                                    /* PAD-381: a ball held in the scoop */
    shield_arm();                                   /* PAD-379: the Premium's shield platform */
    EACH_MODE(m) modes += m != 0;
    if (fn("score_add32") && data("score_mult"))
        say("scores: 32-bit (score_add32 0x%08x, scores32 0x%08x, multiplier byte 0x%08x)", fn("score_add32"),
            data("scores32"), data("score_mult"));
    else if (fn("score_add32"))
        say("scores: 32-bit (score_add32 0x%08x, scores32 0x%08x, no score_mult: the multiplier is taken as 1)",
            fn("score_add32"), data("scores32"));
    if (!fn("shot_dispatch")) say("shots: from switches only (the port has no shot_dispatch)");
    say("armed: %d mode(s); can%s%s%s%s%s%s%s%s%s%s%s%s", modes,
        can & PM_CAN_CALLOUT ? " callout" : "", can & PM_CAN_LIGHTS ? " lights" : "",
        can & PM_CAN_SCREENS ? " screens" : "", can & PM_CAN_CLIPS ? " clips" : "",
        can & PM_CAN_OWN_SOUND ? " own-sound" : "", can & PM_CAN_MESSAGES ? " messages" : "",
        can & PM_CAN_AWARD_SCREEN ? " award-screen" : "", can & PM_CAN_MULTIBALL ? " multiball" : "",
        can & PM_CAN_BACKDROP ? " backdrop" : "", can & PM_CAN_COILS ? " magnet" : "",
        can & PM_CAN_SCOOP ? " scoop" : "", can & PM_CAN_SHIELD ? " shield" : "");
    /* The modes' init waits for the first tick (on_tick): nothing of the game may be
     * called from here, before its main() has run. */
}
