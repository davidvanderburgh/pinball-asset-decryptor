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
    int base = 10, got = 0;
    while (*s == ' ' || *s == '\t') s++;
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
    return x;
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
#define N_SITES    80
#define N_DATA     48
#define N_VALUES   128
#define N_SHOTS    64
#define N_ROLES    32
#define N_TEXTS    32
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
static unsigned tramp[1024] __attribute__((aligned(4096)));
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
    if (!addr || (tramp_used + 1) * 16 > 1024) return 0;
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

int pm_begin(void)
{
    if (running && running != current) {
        pm_log("not started: %s is running", running->name ? running->name : "another mode");
        return 0;
    }
    running = current;
    return 1;
}

void pm_end(void) { if (running == current) running = 0; }
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

static void on_sound_lookup(unsigned *r)
{
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
#define N_LAMPS      192
#define LAMP_LAYERS  4
#define LAMP_MODES   64
#define LAMP_SAY_MAX 400

struct lamp { char name[40]; unsigned light[3]; int mono; uint64_t shot; };
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
    if (bad) {
        say("lamps: %d light id(s) are past this game's %u lights - the lamp lines are another build's; no lamps", bad, n);
        for (k = 0; k < n_lamps; k++) lamp_let_go(k);
        can &= ~PM_CAN_LAMPS;
        done = -1;
        return 0;
    }
    say("lamps: the game counts %u lights; every lamp line is within them", n);
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
/* item 154 display: our own clip_play calls are marked, so the clip_play hook can tell the game's
 * from ours; the name is kept for the layered background's calls a hold answers with it */
static volatile int disp_clip_ours, disp_clip_lost;
static char disp_clip_name[96], disp_lost_name[64];
static void display_tick(void);           /* the display priority section, below */

int pm_clip(const char *name)
{
    unsigned i;
    if (!(can & PM_CAN_CLIPS) || !name || !*name) return 0;
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
    ((void (*)(void))(unsigned long)fn("clip_stop"))();
    clip.on = 0;
}

static void clip_tick(void)
{
    void *player, *surface, *display;
    int state;
    unsigned long now;
    long playing = pm_port_value("surface_playing", 2);
    display_tick();                           /* item 154 display: the hold, the covered state */
    if (!clip.on) return;
    if (disp_clip_lost) {                     /* item 154 display: the game played a clip of its own */
        clip.on = 0;
        disp_clip_lost = 0;
        say("clip: the game played its own clip \"%s\" on the one surface - ours stops drawing", disp_lost_name);
        return;
    }
    now = pm_ms();
    player = ((void *(*)(void))(unsigned long)fn("video_player"))();
    surface = ((void *(*)(void))(unsigned long)fn("video_surface"))();
    display = *(void **)(unsigned long)(data("display_holder") + (unsigned)pm_port_value("display_at", 0));
    state = player && surface && display ? ((int (*)(void *))(unsigned long)fn("surface_state"))(surface) : -1;
    if (state == playing) {
        ((void (*)(void *, float))(unsigned long)fn("player_advance"))(player, (float)(now - clip.last));
        ((void (*)(void *, void *, unsigned))(unsigned long)fn("display_draw"))
            (display, player, (unsigned)pm_port_value("clip_layer", 0));
        clip.seen = 1;
    } else if (clip.seen || now - clip.started > 3000) {
        clip.on = 0;
    }
    clip.last = now;
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
 * A HOLD (pm_display_priority) rides on both: while the layered-display effect is current its
 * priority is raised to the mode's (the game's own comparison then refuses, queues or keeps
 * waiting whatever does not beat it), and a layered waiter whose display must wait is told the
 * layered priority is 255. A display that beats the hold covers the screen for its length and
 * the screen is in view again after it; the hold is raised again when the layered display
 * returns. Released at the mode's end: the layered display's own priority back, its queue run. */
static const struct pm_mode *disp_owner;
static unsigned disp_prio;                /* 0: no hold */
static int disp_covered_now, disp_said_wait;
static unsigned disp_said_layered[8];     /* the layered displays a hold has said wait, one bit each */
static unsigned disp_said_dropped[8];     /* item 157: the layered displays a hold has dropped, one bit each */
static unsigned disp_said_effect[8];      /* the effects waiting to start a hold has said about, one bit each */
static unsigned char *disp_layered_mgr;   /* as the layered_priority calls pass it */
static unsigned char disp_fake_layered[0x100];

static unsigned char *disp_manager(void)
{
    unsigned a = data("display_effects"), t = data("award_screen_arg");
    unsigned char *m;
    if (!a || !t) return 0;
    m = *(unsigned char **)(unsigned long)a;
    return m && *(unsigned *)(m + 4) == t ? m : 0;           /* the manager of THIS effect table */
}

static unsigned disp_effect(unsigned id, int flags)          /* an effect's table priority (or flags) */
{
    unsigned t = data("award_screen_arg"), recs, n;
    if (!t) return 0;
    recs = *(unsigned *)(unsigned long)t;
    n = *(unsigned *)(unsigned long)(t + 4);
    if (!id || id >= n) return 0;
    return flags ? *(unsigned short *)(unsigned long)(recs + 8 * id + 4) : *(unsigned char *)(unsigned long)(recs + 8 * id + 6);
}

static unsigned disp_host(void) { return (unsigned)pm_port_value("display_host", 0); }
static unsigned disp_now(unsigned char *m) { return *(unsigned short *)(m + pm_port_value("display_now_at", 0xc)); }
static unsigned char *disp_level(unsigned char *m) { return m + pm_port_value("display_priority_at", 0xe); }

/* raise the layered display's effect priority to the hold's; 1 if it was raised */
static int disp_raise(unsigned char *m)
{
    unsigned char *p;
    if (!disp_prio || !m || disp_now(m) != disp_host()) return 0;
    p = disp_level(m);
    if (*p >= disp_prio) return 0;
    *p = (unsigned char)disp_prio;
    return 1;
}

static void disp_release(const char *why)
{
    unsigned char *m = disp_manager();
    unsigned p = disp_prio, next = fn("display_effect_next");
    if (!p) return;
    disp_prio = 0;
    disp_owner = 0;
    disp_covered_now = 0;
    if (m && disp_now(m) == disp_host() && *disp_level(m) == p) {
        *disp_level(m) = (unsigned char)disp_effect(disp_host(), 0);
        if (next) ((void (*)(void))(unsigned long)next)();        /* what the end of an effect does */
    }
    say("display: priority %u released (%s) - the game's own display order again", p, why);
}

int pm_display_priority(unsigned priority)
{
    unsigned char *m;
    unsigned now;
    if (!(can & PM_CAN_DISPLAY_PRIORITY)) return 0;
    if (!priority) {
        if (disp_prio && (!current || disp_owner == current)) disp_release("the mode gave it up");
        return 1;
    }
    if (!running || running != current) return 0;
    if (priority > 255) priority = 255;
    disp_owner = current;
    disp_prio = priority;
    disp_said_wait = 0;
    for (now = 0; now < 8; now++) disp_said_layered[now] = disp_said_effect[now] = disp_said_dropped[now] = 0;
    m = disp_manager();
    /* A display effect of the game's already on the screen plays to its end (whatever its priority):
     * the hold applies from the layered display's next turn. Ending it from here was tried (run 4, a
     * forced start of the layered display from the tick) and changed nothing, so it is not done. */
    disp_raise(m);
    say("display: %s holds display priority %u - the game's displays that do not beat it wait (effect now %u, priority %u)",
        current && current->name ? current->name : "a mode", priority, m ? disp_now(m) : 0, m ? *disp_level(m) : 0);
    return 1;
}

int pm_display_covered(void) { return disp_prio && disp_covered_now; }

/* every tick, from clip_tick: the hold follows its mode, is raised again when the layered display
 * comes back, and says when a display that beat it covers the screen and when it is gone */
static void display_tick(void)
{
    unsigned char *m;
    unsigned now;
    int covered;
    if (!disp_prio) return;
    if (!disp_owner || running != disp_owner) { disp_release("the mode that held it ended"); return; }
    if (!pm_in_game()) { disp_release("left the game"); return; }
    m = disp_manager();
    if (!m) return;
    now = disp_now(m);
    if (disp_raise(m) && disp_covered_now)
        say("display: the layered display is back - held at %u again", disp_prio);
    covered = now && now != disp_host() && *disp_level(m) > disp_prio;
    if (!covered && disp_layered_mgr && now == disp_host() &&
        *(unsigned *)(disp_layered_mgr + pm_port_value("layered_fg_at", 0x58)) &&
        (*(unsigned *)(disp_layered_mgr + pm_port_value("layered_fg_flags_at", 0x60)) & 0x10))
        covered = 2;
    if (!covered != !disp_covered_now) {
        if (covered == 1) say("display: covered by the game's effect %u (priority %u beats %u)", now, *disp_level(m), disp_prio);
        else if (covered) say("display: covered by a full-screen layered display of the game's that beats %u", disp_prio);
        else say("display: in view again");
    }
    disp_covered_now = covered;
}

/* The effect priority now, as the game's effect WAITERS read it every frame (site
 * display_priority_now, a two-instruction leaf): a hold is raised first, so a waiter polling in the
 * moment after the layered display started again (the end of an effect that beat the hold) sees it,
 * and keeps waiting. Run 2 (Premium 1.16) caught effect 126 slipping through in that moment.
 * A waiter asks at ITS OWN priority (176 for the game's awards), but the effect it waits for has a
 * priority of its own (the battle select screen 132: 196, BATTLE IS LIT 128: 177). When the call is a
 * waiter's (it returns to effect_waiter_call) and the effect it waits for (at +layered_wait_for_at of
 * the waiting process, as for a layered waiter) beats the hold, the waiter is shown the priority the
 * layered display has without the hold, so it goes on to start the effect, which then beats the hold
 * in the start's own comparison. Run 4 (Premium 1.16): without this the battle select screen waited
 * out a mode at 180, so no battle could start while it ran. */
static unsigned char disp_fake_effects[0x40];

static void on_display_priority_now(unsigned *r)
{
    unsigned char *m = (unsigned char *)(unsigned long)r[0], *proc;
    unsigned id, prio;
    long at = pm_port_value("display_priority_at", 0xe);
    if (!disp_prio || m != disp_manager()) return;
    disp_raise(m);
    if (!r[5] || r[5] != (unsigned)pm_port_value("effect_waiter_call", 0) || at < 0 || at >= (long)sizeof disp_fake_effects)
        return;
    proc = *(unsigned char **)(unsigned long)data("event_current");
    if (!proc) return;
    id = *(unsigned short *)(proc + pm_port_value("layered_wait_for_at", 0xa0));
    prio = disp_effect(id, 0);
    if (id < 256 && !(disp_said_effect[id / 32] & (1u << (id % 32)))) {
        disp_said_effect[id / 32] |= 1u << (id % 32);
        say("display: the game's effect %u (priority %u) is waiting to start - %s %u", id, prio,
            prio > disp_prio ? "it beats the hold at" : "it waits for the hold at", disp_prio);
    }
    if (prio <= disp_prio) return;
    /* only OUR raise is lifted: while an effect of the game's runs the waiter sees its priority, and
     * waits for it as the game would (run 6: lifted over effect 126, the select screen's start was
     * refused behind it and its waiter gave up) */
    if (disp_now(m) != disp_host()) return;
    disp_fake_effects[at] = (unsigned char)disp_effect(disp_host(), 0);
    r[0] = (unsigned)(unsigned long)disp_fake_effects;
}

/* The effect start, before it runs: a hold is raised first (the layered display may have started
 * again since the last tick), so the game's comparison sees it. Never changes the request. */
static void on_display_effect_start(unsigned *r)
{
    unsigned char *m = (unsigned char *)(unsigned long)r[0];
    if (!disp_prio || m != disp_manager()) return;
    disp_raise(m);
    if (!r[3] && r[1] != disp_host() && disp_effect(r[1], 0) <= disp_prio && disp_said_wait < 40) {
        disp_said_wait++;
        say("display: the game's effect %u (priority %u) does not beat %u - refused or queued, as behind an effect of the game's",
            r[1], disp_effect(r[1], 0), disp_prio);
    }
}

/* Must a layered display of these flags wait for a hold? (tests lift it verbatim) A background never
 * does; a mode start (0x40) or total (0x04) counts as one of the game's mode displays (mode_level) and
 * comes through when that beats the hold; any other display counts as its layered-display effect
 * (priority 1). Of those, a full-screen one (0x10) waits; a framed one plays under the mode's screen,
 * as the game layers it, except while the mode's own clip plays (it would take the one surface). */
static int disp_layered_must_wait(unsigned flags, unsigned hold, unsigned mode_level, int our_clip)
{
    unsigned level;
    if (!hold || (flags & 0x02)) return 0;
    level = (flags & 0x44) ? mode_level : 1;
    if (level > hold) return 0;
    return (flags & 0x10) || our_clip;
}

/* The layered priority, as a WAITER asks it (its call returns to layered_waiter_call): the display
 * it waits for is read off the waiting process, and when it must wait for the hold the waiter is
 * handed a layered manager whose foreground priority is 255. Any other caller, and any display that
 * beats the hold, gets the game's own answer. */
static void on_layered_priority(unsigned *r)
{
    unsigned char *proc, *rec;
    unsigned t, id, n, flags;
    if (r[0]) disp_layered_mgr = (unsigned char *)(unsigned long)r[0];
    if (!disp_prio || r[5] != (unsigned)pm_port_value("layered_waiter_call", 0)) return;
    proc = *(unsigned char **)(unsigned long)data("event_current");
    t = data("layered_displays");
    if (!proc || !t) return;
    id = *(unsigned *)(proc + pm_port_value("layered_wait_for_at", 0xa0));
    n = *(unsigned *)(unsigned long)(t + 4);
    if (!id || id >= n) return;
    rec = (unsigned char *)(unsigned long)(*(unsigned *)(unsigned long)t + id * (unsigned)pm_port_value("layered_record_size", 16));
    flags = *(unsigned *)rec;
    if (!disp_layered_must_wait(flags, disp_prio, (unsigned)pm_port_value("display_mode_level", 184),
                                clip.on && !disp_clip_lost)) return;
    *(unsigned *)(disp_fake_layered + pm_port_value("layered_fg_at", 0x58)) = 1;
    disp_fake_layered[pm_port_value("layered_fg_at", 0x58) + 4] = 255;   /* the foreground's priority, read by the waiter */
    r[0] = (unsigned)(unsigned long)disp_fake_layered;
    if (id < 256 && !(disp_said_layered[id / 32] & (1u << (id % 32)))) {
        disp_said_layered[id / 32] |= 1u << (id % 32);
        say("display: the game's layered display %u (priority %u, flags 0x%x) waits for the hold at %u", id,
            rec[pm_port_value("layered_priority_at", 12)], flags, disp_prio);
    }
}

/* item 157: A LAYERED DISPLAY THAT MUST WAIT IS DROPPED, NOT KEPT WAITING. While a layered waiter
 * waits, the game presents NO frames: measured on Premium 1.16 (the eglshim frame count stops) in the
 * showcase run, 3.8 to 8.1 s each time a full-screen layered display (LOOPS 40, POWERLINE ATTACK 59,
 * 110) waited under a hold with the layered display on the glass, ending the moment the hold was
 * released; the integration branch's run 1 froze 8.3 s the same way at 180. So the waiter's own entry
 * (site layered_waiter: the process body the layered display's start tail-calls with r0 = the display,
 * r1 = the frames it may wait, r2 = its priority) is hooked, and a display the hold would keep waiting
 * gets r1 = 0: it returns at once, as when its time runs out, and is not shown. The game's rules that
 * asked for it (a loop counted, an award paid) are untouched. A port without the site keeps the wait
 * (on_layered_priority above), freeze and all. */
static void on_layered_waiter(unsigned *r)
{
    unsigned t, n, id = r[0], flags;
    unsigned char *rec;
    if (!disp_prio || !r[1]) return;
    t = data("layered_displays");
    if (!t) return;
    n = *(unsigned *)(unsigned long)(t + 4);
    if (!id || id >= n) return;
    rec = (unsigned char *)(unsigned long)(*(unsigned *)(unsigned long)t + id * (unsigned)pm_port_value("layered_record_size", 16));
    flags = *(unsigned *)rec;
    if (!disp_layered_must_wait(flags, disp_prio, (unsigned)pm_port_value("display_mode_level", 184),
                                clip.on && !disp_clip_lost)) return;
    r[1] = 0;
    if (id < 256 && !(disp_said_dropped[id / 32] & (1u << (id % 32)))) {
        disp_said_dropped[id / 32] |= 1u << (id % 32);
        say("display: the game's layered display %u (priority %u, flags 0x%x) is dropped for the hold at %u "
            "(a waiting one would stop the game's drawing)", id, rec[pm_port_value("layered_priority_at", 12)], flags,
            disp_prio);
    }
}

/* clip_play from anyone but us while our clip draws: the one surface is the game's now. While a hold
 * is up and the layered display runs its BACKGROUND (no effect over it, no layered foreground), the
 * background's clip is asked for as ours instead, as a foreground would keep the surface from it. */
static void on_clip_play(unsigned *r)
{
    unsigned char *m;
    const char *name = (const char *)(unsigned long)r[0];
    unsigned i;
    if (disp_clip_ours || !clip.on) return;
    m = disp_manager();
    if (disp_prio && m && disp_now(m) == disp_host() && disp_layered_mgr &&
        !*(unsigned *)(disp_layered_mgr + pm_port_value("layered_fg_at", 0x58)) && disp_clip_name[0] &&
        ((int (*)(void *))(unsigned long)fn("surface_state"))(((void *(*)(void))(unsigned long)fn("video_surface"))())
            == pm_port_value("surface_playing", 2)) {       /* ours still plays: asked again, it is not restarted */
        say("clip: the layered background asked for \"%.40s\" while ours plays under a hold - ours is asked for again",
            name ? name : "");
        r[0] = (unsigned)(unsigned long)disp_clip_name;
        r[1] = 0;
        r[2] = 0;
        return;
    }
    for (i = 0; name && name[i] && i + 1 < sizeof disp_lost_name; i++) disp_lost_name[i] = name[i];
    disp_lost_name[i] = 0;
    disp_clip_lost = 1;
}

static int have_sites(const char *const *names);
static int have_data(const char *const *names);
static int have_values(const char *const *names);

/* from the constructor: the clip_play hook always (a clip of ours stops drawing when the game takes
 * the surface), the rest when the port names the display arbitration */
static void display_arm(void)
{
    static const char *const s[] = { "display_effect_start", "layered_priority", 0 };
    static const char *const d[] = { "display_effects", "layered_displays", "award_screen_arg", "event_current", 0 };
    static const char *const v[] = { "display_host", "display_mode_level", "display_now_at", "display_priority_at",
                                     "layered_record_size", "layered_priority_at", "layered_wait_for_at",
                                     "layered_waiter_call", "layered_fg_at", "layered_fg_flags_at", 0 };
    /* The effect half alone: a title whose game has no layered displays (The Beatles 1.29 has the
     * framework's effect start, next and priority-now, and nothing of Godzilla's layered-display
     * library). The hold then rides on the display effects only: an effect of the game's comes
     * through when its priority beats the hold's. */
    static const char *const es[] = { "display_effect_start", 0 };
    static const char *const ed[] = { "display_effects", "award_screen_arg", "event_current", 0 };
    static const char *const ev[] = { "display_host", "display_mode_level", "display_now_at", "display_priority_at", 0 };
    if (can & PM_CAN_CLIPS) hook(fn("clip_play"), on_clip_play);
    if (!site("display_effect_start") && !site("layered_priority")) return;      /* a port without them: silent */
    if (!site("layered_priority")) {
        if (!have_sites(es) || !have_data(ed) || !have_values(ev)) {
            say("display priority: off - the port's display lines are incomplete or do not match this build");
            return;
        }
        if (!hook(fn("display_effect_start"), on_display_effect_start)) return;
        can |= PM_CAN_DISPLAY_PRIORITY;
        if (fn("display_priority_now")) hook(fn("display_priority_now"), on_display_priority_now);
        else say("display priority: the port has no display_priority_now - a waiter can slip through in the frame after an effect ends");
        say("display priority: on, display effects only (the port has no layered display) - the effect start 0x%08x is hooked "
            "(host effect %u)", fn("display_effect_start"), disp_host());
        return;
    }
    if (!have_sites(s) || !have_data(d) || !have_values(v)) {
        say("display priority: off - the port's display lines are incomplete or do not match this build");
        return;
    }
    if (hook(fn("display_effect_start"), on_display_effect_start) && hook(fn("layered_priority"), on_layered_priority)) {
        can |= PM_CAN_DISPLAY_PRIORITY;
        if (fn("display_priority_now")) hook(fn("display_priority_now"), on_display_priority_now);
        else say("display priority: the port has no display_priority_now - a waiter can slip through in the frame after an effect ends");
        if (fn("layered_waiter") && hook(fn("layered_waiter"), on_layered_waiter))
            say("display priority: a layered display the hold would keep waiting is dropped at its waiter 0x%08x "
                "(a waiting one stops the game's drawing)", fn("layered_waiter"));
        else
            say("display priority: the port has no layered_waiter - a layered display waits for a hold, and the game "
                "draws no frames while it does");
        say("display priority: on - the effect start 0x%08x and the layered priority 0x%08x are hooked (layered display effect %u, the game's mode level %ld)",
            fn("display_effect_start"), fn("layered_priority"), disp_host(), pm_port_value("display_mode_level", 184));
    }
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
        say("stock modes: %s%s%s%s", data("stock_mode_manager") ? "can tell" : "this port cannot tell (no stock_mode_manager)",
            data("stock_mode_manager") && fn("stock_battle_running") ? " battle" : "",
            data("stock_mode_manager") && fn("stock_multiball_running") ? " multiball" : "",
            data("stock_mode_manager") && fn("stock_any_running") ? " any" : "");
    }
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
    if (kind & PM_STOCK_BATTLE) return "a battle";
    if (kind & PM_STOCK_MULTIBALL) return "a multiball";
    return kind ? "a stock mode" : "nothing";
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
    events_deliver();
    switches_deliver();
    EACH_MODE(m) if (m->tick) { current = m; m->tick(); }
    current = 0;
    roster_deferred_tick();
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
    EACH_MODE(m) if (m->ball_end) { current = m; m->ball_end(); }
    current = 0;
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
        if (have_sites(clip_s) && have_data(clip_d) && have_values(clip_v)) can |= PM_CAN_CLIPS;
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
    if (can & PM_CAN_OWN_SOUND) hook(fn("sound_lookup"), on_sound_lookup);
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
    EACH_MODE(m) modes += m != 0;
    if (fn("score_add32") && data("score_mult"))
        say("scores: 32-bit (score_add32 0x%08x, scores32 0x%08x, multiplier byte 0x%08x)", fn("score_add32"),
            data("scores32"), data("score_mult"));
    else if (fn("score_add32"))
        say("scores: 32-bit (score_add32 0x%08x, scores32 0x%08x, no score_mult: the multiplier is taken as 1)",
            fn("score_add32"), data("scores32"));
    if (!fn("shot_dispatch")) say("shots: from switches only (the port has no shot_dispatch)");
    say("armed: %d mode(s); can%s%s%s%s%s%s%s", modes,
        can & PM_CAN_CALLOUT ? " callout" : "", can & PM_CAN_LIGHTS ? " lights" : "",
        can & PM_CAN_SCREENS ? " screens" : "", can & PM_CAN_CLIPS ? " clips" : "",
        can & PM_CAN_OWN_SOUND ? " own-sound" : "", can & PM_CAN_MESSAGES ? " messages" : "",
        can & PM_CAN_AWARD_SCREEN ? " award-screen" : "");
    /* The modes' init waits for the first tick (on_tick): nothing of the game may be
     * called from here, before its main() has run. */
}
