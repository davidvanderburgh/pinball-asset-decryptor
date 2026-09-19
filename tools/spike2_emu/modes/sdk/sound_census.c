/* sound_census.c - which sound requests does the game play, when, and for how long? (item 150)
 *
 * A measuring instrument, not a mode, and not built with the runtime:
 *     build_mode.sh -p -o sound_census.so sound_census.c
 * Preload it INSTEAD of a mode object (both hook the tick). It reads the port the rig uses,
 * /dump/game.port (then /usr/local/padmode/game.port), and needs these lines in it:
 *     site sound_worker   every request funnels through it (hooked: one log line per call)
 *     site tick           hooked: the channel dump and the trigger files
 *     site sound_play     called by the fire trigger          (optional)
 *     site sound_nth      called by the fire trigger with n   (optional)
 *     site sound_stop     called by the stop trigger          (optional)
 *     site sound_active   called by the active trigger        (optional)
 *     data sound_channels the 8 x 196-byte channel table      (optional)
 *     data sound_queue    the 8 x 20-byte delayed-request queue (optional)
 *     data city_variants  RuleCities' request -> request hash map (optional)
 * A site is hooked or called only if its first two instruction words match the port.
 *
 * What it writes, all in /dump (wall-clock ms, so marks written outside line up):
 *   sound_census.log   "<ms> R <req> <r2> <lr> <caller> <s0> <s1>"  one line per worker call, no cap
 *                      (r2 = 1 for a numbered variant; lr = the entry point's return address;
 *                      caller = the word 9 slots up the entry point's frame, which is its own
 *                      caller for sound_play / sound_nth)
 *                      "<ms> MARK <text>", "<ms> FIRE <req> [n] rc <rc>", "<ms> STOP <req> rc <rc>",
 *                      "<ms> ACTIVE <req> <0|1>", "<ms> CITY <n> <from>:<to> ...", "<ms> CALL ..."
 *   sound_census.chan  every 500 ms: u32 'SCH1', u32 ms low, u32 ms high, then the channel table
 *                      (1568 bytes) and the queue (160 bytes); zeros where a table is absent
 * Trigger files, polled every 250 ms and deleted once read (write them with a single echo):
 *   sc.mark    "<text>"         a MARK line
 *   sc.fire    "<req> [n]"      sound_play(req), or sound_nth(req, n)
 *   sc.stop    "<req>"          sound_stop(req)        (0 stops every channel)
 *   sc.active  "<req>"          sound_active(req)
 *   sc.city    anything         dump the city-variant map (also done once, 60 s after the first tick)
 * Read the results with sound_census_read.py.
 */
extern int  open(const char *, int, ...);
extern long read(int, void *, __SIZE_TYPE__);
extern long write(int, const void *, __SIZE_TYPE__);
extern int  close(int);
extern int  unlink(const char *);
extern int  clock_gettime(int, void *);
extern int  mprotect(void *, __SIZE_TYPE__, int);
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  0100
#define O_APPEND 02000
#define CLOCK_REALTIME 0
struct ts32 { long tv_sec, tv_nsec; };

#define CHANNELS_BYTES 1568
#define QUEUE_BYTES    160

struct site { unsigned addr, w0, w1; int ok; };
static struct site s_worker, s_tick, s_play, s_nth, s_stop, s_active;
static unsigned d_channels, d_queue, d_city;
static int log_fd = -1, chan_fd = -1;

/* ---- tiny formatting (no libc stdio inside the game) --------------------------------------- */
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

static unsigned decval(const char **p, int *got)
{
    unsigned v = 0;
    const char *s = *p;
    *got = 0;
    while (*s == ' ' || *s == '\t') s++;
    while (*s >= '0' && *s <= '9') { v = v * 10 + (unsigned)(*s - '0'); s++; *got = 1; }
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

static char *put_str(char *o, const char *s)
{
    while (*s) *o++ = *s++;
    return o;
}

static unsigned long long now_ms(void)
{
    struct ts32 ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (unsigned long long)ts.tv_sec * 1000ull + (unsigned long long)(ts.tv_nsec / 1000000);
}

static void emit(char *line, char *o)
{
    *o++ = '\n';
    if (log_fd >= 0) write(log_fd, line, (unsigned long)(o - line));
}

/* ---- the SDK runtime's trampoline (call_probe.c's copy) ------------------------------------ */
static unsigned tramp[4 * 16] __attribute__((aligned(4096)));
static int tramp_used;

static int relocate_literal(unsigned *t, int i, unsigned addr, unsigned w)
{
    unsigned imm, at;
    if ((w & 0xFF7F0000u) != 0xE51F0000u || ((w >> 12) & 0xF) == 15) return 0;
    imm = w & 0xFFF;
    at = addr + (unsigned)i * 4 + 8;
    at = (w & 0x00800000u) ? at + imm : at - imm;
    t[12 + i] = *(const unsigned *)(unsigned long)at;
    t[6 + i] = 0xE59F0010u | (w & 0xF000u);
    return 1;
}

static void hook(unsigned addr, void (*logger)(unsigned *))
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
}

/* ---- the worker: one line per request ------------------------------------------------------ */
static void on_worker(unsigned *r)
{
    /* r[0..3] = r0..r3, r[4] = ip, r[5] = lr, r[6..] = the stack at entry */
    char line[128], *o = line;
    o = put_dec(o, now_ms());
    o = put_str(o, " R ");
    o = put_dec(o, r[0]);
    *o++ = ' ';
    o = put_dec(o, r[2]);
    *o++ = ' ';
    o = put_hex(o, r[5]);
    *o++ = ' ';
    o = put_hex(o, r[6 + 9]);
    *o++ = ' ';
    o = put_hex(o, r[6]);
    *o++ = ' ';
    o = put_hex(o, r[7]);
    emit(line, o);
}

/* ---- the tick: channels, triggers -------------------------------------------------------- */
static long read_trigger(const char *path, char *buf, unsigned long cap)
{
    long n, tot = 0;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    while (tot < (long)cap - 1 && (n = read(fd, buf + tot, cap - 1 - (unsigned long)tot)) > 0) tot += n;
    close(fd);
    unlink(path);
    buf[tot] = 0;
    while (tot > 0 && (buf[tot - 1] == '\n' || buf[tot - 1] == '\r' || buf[tot - 1] == ' ')) buf[--tot] = 0;
    return tot;
}

static void dump_city(void)
{
    static char line[16384];
    char *o = line, *count_at;
    const unsigned *node;
    unsigned n = 0;
    o = put_dec(o, now_ms());
    o = put_str(o, " CITY ");
    if (!d_city) { o = put_str(o, "absent"); emit(line, o); return; }
    count_at = o;
    o = put_str(o, "          ");     /* the count goes here */
    node = (const unsigned *)(unsigned long)((const unsigned *)(unsigned long)d_city)[2];
    while (node && n < 1500 && (unsigned long)(o - line) < sizeof line - 32) {
        const unsigned short *kv = (const unsigned short *)(node + 1);
        *o++ = ' ';
        o = put_dec(o, kv[0]);
        *o++ = ':';
        o = put_dec(o, kv[1]);
        n++;
        node = (const unsigned *)(unsigned long)node[0];
    }
    {
        char tmp[16], *t = put_dec(tmp, n);
        int i;
        for (i = 0; i < t - tmp && i < 10; i++) count_at[i] = tmp[i];
    }
    emit(line, o);
}

static void dump_channels(unsigned long long ms)
{
    static unsigned char rec[12 + CHANNELS_BYTES + QUEUE_BYTES];
    unsigned hdr[3];
    int i;
    if (chan_fd < 0) return;
    hdr[0] = 0x31484353u;             /* "SCH1" */
    hdr[1] = (unsigned)ms;
    hdr[2] = (unsigned)(ms >> 32);
    for (i = 0; i < 12; i++) rec[i] = ((unsigned char *)hdr)[i];
    for (i = 0; i < CHANNELS_BYTES; i++)
        rec[12 + i] = d_channels ? ((const unsigned char *)(unsigned long)d_channels)[i] : 0;
    for (i = 0; i < QUEUE_BYTES; i++)
        rec[12 + CHANNELS_BYTES + i] = d_queue ? ((const unsigned char *)(unsigned long)d_queue)[i] : 0;
    write(chan_fd, rec, sizeof rec);
}

static int call1(struct site *s, unsigned a)
{
    return ((int (*)(unsigned))(unsigned long)s->addr)(a);
}

static int call2(struct site *s, unsigned a, unsigned b)
{
    return ((int (*)(unsigned, unsigned))(unsigned long)s->addr)(a, b);
}

static void on_tick(unsigned *r)
{
    static unsigned long long first, last_chan, last_poll;
    static int city_done;
    char buf[160], line[256], *o;
    const char *p;
    unsigned long long ms = now_ms();
    int got, got2;
    (void)r;
    if (!first) {
        first = ms;
        o = put_dec(line, ms);
        o = put_str(o, " MARK first tick");
        emit(line, o);
    }
    if (ms - last_chan >= 500) { last_chan = ms; dump_channels(ms); }
    if (!city_done && ms - first >= 60000) { city_done = 1; dump_city(); }
    if (ms - last_poll < 250) return;
    last_poll = ms;

    if (read_trigger("/dump/sc.mark", buf, sizeof buf) >= 0) {
        o = put_dec(line, ms);
        o = put_str(o, " MARK ");
        o = put_str(o, buf);
        emit(line, o);
    }
    if (read_trigger("/dump/sc.fire", buf, sizeof buf) >= 0) {
        unsigned req, n;
        int rc = -1;
        p = buf;
        req = decval(&p, &got);
        n = decval(&p, &got2);
        if (got && got2 && s_nth.ok) rc = call2(&s_nth, req, n);
        else if (got && s_play.ok) rc = call1(&s_play, req);
        o = put_dec(line, now_ms());
        o = put_str(o, " FIRE ");
        o = put_dec(o, req);
        if (got2) { *o++ = ' '; o = put_dec(o, n); }
        o = put_str(o, " rc ");
        if (rc < 0) { *o++ = '-'; o = put_dec(o, (unsigned)-rc); } else o = put_dec(o, (unsigned)rc);
        emit(line, o);
    }
    if (read_trigger("/dump/sc.stop", buf, sizeof buf) >= 0) {
        unsigned req;
        int rc = -1;
        p = buf;
        req = decval(&p, &got);
        if (got && s_stop.ok) rc = call1(&s_stop, req);
        o = put_dec(line, now_ms());
        o = put_str(o, " STOP ");
        o = put_dec(o, req);
        o = put_str(o, " rc ");
        if (rc < 0) { *o++ = '-'; o = put_dec(o, (unsigned)-rc); } else o = put_dec(o, (unsigned)rc);
        emit(line, o);
    }
    if (read_trigger("/dump/sc.active", buf, sizeof buf) >= 0) {
        unsigned req;
        int rc = -1;
        p = buf;
        req = decval(&p, &got);
        if (got && s_active.ok) rc = call1(&s_active, req);
        o = put_dec(line, now_ms());
        o = put_str(o, " ACTIVE ");
        o = put_dec(o, req);
        *o++ = ' ';
        if (rc < 0) { *o++ = '-'; o = put_dec(o, (unsigned)-rc); } else o = put_dec(o, (unsigned)rc);
        emit(line, o);
    }
    if (read_trigger("/dump/sc.city", buf, sizeof buf) >= 0) dump_city();
}

/* ---- the port ---------------------------------------------------------------------------- */
static int word_is(const char *s, const char *w)
{
    while (*w) if (*s++ != *w++) return 0;
    return *s == ' ' || *s == '\t';
}

static void load_port(void)
{
    static char buf[16384];
    static const char *const files[] = { "/dump/game.port", "/usr/local/padmode/game.port" };
    long n, tot = 0;
    const char *s;
    unsigned f;
    int fd = -1;
    for (f = 0; f < 2 && fd < 0; f++) fd = open(files[f], O_RDONLY);
    if (fd < 0) return;
    while (tot < (long)sizeof buf - 1 && (n = read(fd, buf + tot, sizeof buf - 1 - (unsigned long)tot)) > 0)
        tot += n;
    close(fd);
    buf[tot] = 0;
    for (s = buf; *s;) {
        const char *line = s, *q;
        while (*s && *s != '\n') s++;
        if (*s) s++;
        if (line[0] == 's' && word_is(line, "site")) {
            struct site *x = 0;
            q = line + 4;
            while (*q == ' ' || *q == '\t') q++;
            if (word_is(q, "sound_worker")) x = &s_worker;
            else if (word_is(q, "tick")) x = &s_tick;
            else if (word_is(q, "sound_play")) x = &s_play;
            else if (word_is(q, "sound_nth")) x = &s_nth;
            else if (word_is(q, "sound_stop")) x = &s_stop;
            else if (word_is(q, "sound_active")) x = &s_active;
            if (!x) continue;
            while (*q && *q != ' ' && *q != '\t') q++;
            x->addr = hexval(&q);
            x->w0 = hexval(&q);
            x->w1 = hexval(&q);
        } else if (line[0] == 'd' && word_is(line, "data")) {
            unsigned *d = 0;
            q = line + 4;
            while (*q == ' ' || *q == '\t') q++;
            if (word_is(q, "sound_channels")) d = &d_channels;
            else if (word_is(q, "sound_queue")) d = &d_queue;
            else if (word_is(q, "city_variants")) d = &d_city;
            if (!d) continue;
            while (*q && *q != ' ' && *q != '\t') q++;
            *d = hexval(&q);
        }
    }
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
        q++;
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

static int check(struct site *x)
{
    const unsigned *p;
    if (!x->addr) return 0;
    p = (const unsigned *)(unsigned long)x->addr;
    x->ok = p[0] == x->w0 && p[1] == x->w1;
    return x->ok;
}

__attribute__((constructor))
static void census_start(void)
{
    char line[256], *o;
    load_port();
    if (!s_worker.addr || !s_tick.addr || !in_game(s_tick.addr)) return;
    log_fd = open("/dump/sound_census.log", O_WRONLY | O_CREAT | O_APPEND, 0644);
    check(&s_worker); check(&s_tick); check(&s_play); check(&s_nth); check(&s_stop); check(&s_active);
    o = put_dec(line, now_ms());
    o = put_str(o, " MARK census worker ");
    o = put_str(o, s_worker.ok ? "ok" : "MISMATCH");
    o = put_str(o, " tick ");
    o = put_str(o, s_tick.ok ? "ok" : "MISMATCH");
    o = put_str(o, " play ");  o = put_dec(o, (unsigned)s_play.ok);
    o = put_str(o, " nth ");   o = put_dec(o, (unsigned)s_nth.ok);
    o = put_str(o, " stop ");  o = put_dec(o, (unsigned)s_stop.ok);
    o = put_str(o, " active "); o = put_dec(o, (unsigned)s_active.ok);
    o = put_str(o, " channels "); o = put_hex(o, d_channels);
    o = put_str(o, " queue "); o = put_hex(o, d_queue);
    o = put_str(o, " city "); o = put_hex(o, d_city);
    emit(line, o);
    if (!s_worker.ok || !s_tick.ok) return;
    chan_fd = open("/dump/sound_census.chan", O_WRONLY | O_CREAT | O_APPEND, 0644);
    hook(s_worker.addr, on_worker);
    hook(s_tick.addr, on_tick);
}
