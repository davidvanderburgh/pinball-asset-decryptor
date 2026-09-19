/* call_probe.c - a porting instrument: which game functions does something reach, and with
 * what arguments? (item 137, where it found TMNT Pro's shot dispatch and end of ball)
 *
 * Not a mode and not built with the runtime: `build_mode.sh -p -o probe.so call_probe.c`.
 * Preload it instead of a mode. It reads /dump/probe.sites - one "<name> <address> <w0> <w1>"
 * per line, written by probe_sites.py - and hooks every site whose first two instruction
 * words match, with the runtime's trampoline (literal loads relocated the same way). Each
 * call appends "<wall-clock ms> <name> r0 r1 r2 r3 sp0 sp1 sp2 sp3" to /dump/probe.log,
 * at most MAX_LINES lines per site, so a function the game calls every frame goes quiet.
 * Write marks into the same log from outside ("<date +%s%3N> mark <label>") around each
 * switch press or drain, then read it with probe_read.py.
 *
 * It acts only inside the process whose program maps the first site (the game).
 */
/* libc by hand, as pad_mode_runtime.c does: the toolchain's headers map clock_gettime to
 * __clock_gettime64, which the card's glibc does not have (an item 137 probe died on its first log line). */
extern int  open(const char *, int, ...);
extern long read(int, void *, __SIZE_TYPE__);
extern long write(int, const void *, __SIZE_TYPE__);
extern int  close(int);
extern int  clock_gettime(int, void *);
extern int  mprotect(void *, __SIZE_TYPE__, int);
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define CLOCK_REALTIME 0
struct ts32 { long tv_sec, tv_nsec; };

#define MAX_SITES 128
#define MAX_LINES 60

struct site { char name[40]; unsigned addr, w0, w1; unsigned lines; };
static struct site sites[MAX_SITES];
static int n_sites;
static int log_fd = -1;

static unsigned hexval(const char **p)
{
    unsigned v = 0;
    const char *s = *p;
    while (*s == ' ' || *s == '\t') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    for (;; s++) {
        unsigned d;
        if (*s >= '0' && *s <= '9') d = (unsigned)(*s - '0');
        else if (*s >= 'a' && *s <= 'f') d = (unsigned)(*s - 'a' + 10);
        else if (*s >= 'A' && *s <= 'F') d = (unsigned)(*s - 'A' + 10);
        else break;
        v = v * 16 + d;
    }
    *p = s;
    return v;
}

static char *put_hex(char *o, unsigned v)
{
    int i;
    for (i = 7; i >= 0; i--) *o++ = "0123456789abcdef"[(v >> (i * 4)) & 0xf];
    return o;
}

static char *put_dec(char *o, unsigned long long v)
{
    char tmp[24];
    int n = 0;
    do { tmp[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) *o++ = tmp[--n];
    return o;
}

/* ---- the SDK runtime's trampoline, one logger per site ------------------------------------ */
static unsigned tramp[MAX_SITES * 16] __attribute__((aligned(4096)));
static int tramp_used;

static void log_call(int k, unsigned *r)
{
    struct site *x = &sites[k];
    char line[160], *o = line;
    struct ts32 ts;
    int i;
    if (x->lines >= MAX_LINES || log_fd < 0) return;
    x->lines++;
    clock_gettime(CLOCK_REALTIME, &ts);
    o = put_dec(o, (unsigned long long)ts.tv_sec * 1000ull + (unsigned long long)(ts.tv_nsec / 1000000));
    *o++ = ' ';
    for (i = 0; x->name[i]; i++) *o++ = x->name[i];
    for (i = 0; i < 4; i++) { *o++ = ' '; o = put_hex(o, r[i]); }
    for (i = 6; i < 10; i++) { *o++ = ' '; o = put_hex(o, r[i]); }   /* stack arguments */
    *o++ = '\n';
    write(log_fd, line, (unsigned long)(o - line));
}

/* One tiny entry per site so the logger knows which site fired. */
#define ENTRY(k) static void entry##k(unsigned *r) { log_call(k, r); }
#define ENTRIES(X) X(0) X(1) X(2) X(3) X(4) X(5) X(6) X(7) X(8) X(9) X(10) X(11) X(12) X(13) \
    X(14) X(15) X(16) X(17) X(18) X(19) X(20) X(21) X(22) X(23) X(24) X(25) X(26) X(27) X(28) \
    X(29) X(30) X(31) X(32) X(33) X(34) X(35) X(36) X(37) X(38) X(39) X(40) X(41) X(42) X(43) \
    X(44) X(45) X(46) X(47) X(48) X(49) X(50) X(51) X(52) X(53) X(54) X(55) X(56) X(57) X(58) \
    X(59) X(60) X(61) X(62) X(63) X(64) X(65) X(66) X(67) X(68) X(69) X(70) X(71) X(72) X(73) \
    X(74) X(75) X(76) X(77) X(78) X(79)
ENTRIES(ENTRY)
#define PTR(k) entry##k,
static void (*const entries[])(unsigned *) = { ENTRIES(PTR) };

/* A literal load `ldr rd, [pc, #+-imm]` (rd not pc) moved into the trampoline: copy the
 * literal into t[12 + i] and load it from there. 0 if the word is not one. */
static int relocate_literal(unsigned *t, int i, unsigned addr, unsigned w)
{
    unsigned imm, at;
    if ((w & 0xFF7F0000u) != 0xE51F0000u || ((w >> 12) & 0xF) == 15) return 0;
    imm = w & 0xFFF;
    at = addr + (unsigned)i * 4 + 8;
    at = (w & 0x00800000u) ? at + imm : at - imm;
    t[12 + i] = *(const unsigned *)(unsigned long)at;
    t[6 + i] = 0xE59F0010u | (w & 0xF000u);      /* ldr rd, [pc, #16] -> t[12 + i] */
    return 1;
}

static int hook(unsigned addr, void (*logger)(unsigned *))
{
    unsigned *p = (unsigned *)(unsigned long)addr, *t;
    int i;
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
    for (i = 0; i < 2; i++) relocate_literal(t, i, addr, p[i]);
    mprotect(tramp, sizeof tramp, 7);
    mprotect((void *)(unsigned long)(addr & ~0xfffu), 0x2000, 7);
    p[1] = (unsigned)(unsigned long)t;
    p[0] = 0xe51ff004u;   /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 1;
}

/* Is addr inside an executable mapping of a file named "game"? */
static int in_game(unsigned addr)
{
    static char buf[65536];
    long n, tot = 0;
    char *s = buf;
    int fd = open("/proc/self/maps", O_RDONLY);
    if (fd < 0) return 0;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - (unsigned long)tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    while (*s) {
        const char *q = s;
        unsigned lo = hexval(&q), hi;
        char *end = s, *name;
        q++;                                   /* '-' */
        hi = hexval(&q);
        while (*end && *end != '\n') end++;
        name = end;
        while (name > s && name[-1] != '/') name--;
        if (lo <= addr && addr < hi && end - name == 4 && name[0] == 'g' && name[1] == 'a' && name[2] == 'm' && name[3] == 'e')
            return 1;
        s = *end ? end + 1 : end;
    }
    return 0;
}

__attribute__((constructor))
static void probe_start(void)
{
    static char buf[16384];
    long n, tot = 0;
    const char *s;
    int fd = open("/dump/probe.sites", O_RDONLY), k, hooked = 0, bad = 0;
    if (fd < 0) return;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - (unsigned long)tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    for (s = buf; *s && n_sites < (int)(sizeof entries / sizeof entries[0]);) {
        struct site *x = &sites[n_sites];
        int i = 0;
        while (*s == ' ' || *s == '\n') s++;
        if (!*s) break;
        if (*s == '#') { while (*s && *s != '\n') s++; continue; }
        while (*s && *s != ' ' && i < 39) x->name[i++] = *s++;
        x->name[i] = 0;
        while (*s && *s != ' ') s++;
        x->addr = hexval(&s);
        x->w0 = hexval(&s);
        x->w1 = hexval(&s);
        while (*s && *s != '\n') s++;
        n_sites++;
    }
    if (!n_sites || !in_game(sites[0].addr)) return;
    log_fd = open("/dump/probe.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    for (k = 0; k < n_sites; k++) {
        const unsigned *p = (const unsigned *)(unsigned long)sites[k].addr;
        if (p[0] == sites[k].w0 && p[1] == sites[k].w1) hooked += hook(sites[k].addr, entries[k]);
        else bad++;
    }
    if (log_fd >= 0) {
        char line[96], *o = line;
        const char *msg = "0 probe hooked ";
        while (*msg) *o++ = *msg++;
        o = put_dec(o, (unsigned)hooked);
        msg = " sites, refused ";
        while (*msg) *o++ = *msg++;
        o = put_dec(o, (unsigned)bad);
        *o++ = '\n';
        write(log_fd, line, (unsigned long)(o - line));
    }
}
