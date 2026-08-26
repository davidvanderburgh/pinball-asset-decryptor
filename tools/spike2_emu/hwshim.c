/* hwshim.c - LD_PRELOAD shim that fakes Spike 2 peripheral hardware.
 *
 * The game is a plain dynamically linked armhf ELF, so every hardware touch
 * goes through libc: open() on /dev/spidev1.0, /dev/i2c-1, /dev/ttymxc1 and
 * then ioctl()/read()/write(). Intercepting those is enough to stand in for
 * the SPI display processor, the i2c NVRAM and the node bus.
 *
 * Explicit asm labels are used so the definitions do not collide with glibc's
 * _FILE_OFFSET_BITS=64 redirect of open -> open64.
 */
#define _GNU_SOURCE
#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>   /* the scan fault guard - see scan_guard_check() */

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)
extern long write(int, const void *, unsigned long);
extern char *strstr(const char *, const char *);
extern size_t strlen(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern char *getenv(const char *);
extern long syscall(long, ...);   /* raw gettid, from a signal handler */

#define MAXFD 4096
static char faked[MAXFD];

static int (*real_open)(const char *, int, int);
static int (*real_open64)(const char *, int, int);
static int (*real_ioctl)(int, unsigned long, void *);

static unsigned long pad_ms(void);       /* defined with the periodic dumps */
/* PAD_PEEK - read arbitrary guest globals. Defined after addr_readable(),
 * declared here because the usleep interposer is the periodic site that drives
 * it and that sits far above. */
static void pad_peek_tick(void);

/* PAD_LOG_TIME=1 - prefix every shim log line with "[SSS.mmm] ", milliseconds
 * since the shim started.
 *
 * OPT-IN, deliberately. Every analysis script in this rig greps log lines by
 * their leading tag ("^\[nb\]", "^\[scenebytes\]", ...) and a timestamp in
 * front of them breaks all of it at once, so this must never be the default.
 * With it on, use the un-anchored forms.
 *
 * It exists because timing questions used to be answered by counting bus writes
 * or by reading the "[eglshim] N frames in M ms" lines as a clock, and both are
 * indirect: the first is not a clock at all (the service loop's rate swings by
 * 4x), and the second only resolves to the nearest 20 frames. Attributing the
 * boot's ~30 s to a phase needed better than that.
 *
 * The timestamp is a SEPARATE write() from the line, so two threads logging at
 * once can interleave a stamp with someone else's text. That is already true of
 * the lines themselves in this rig - the existing logs contain spliced lines -
 * so it is not a new failure mode, but do not read a single odd stamp as
 * evidence of anything. */
static void logmsg(const char *s)
{
    static int want = -1;
    unsigned long n = 0;
    if (want < 0) {
        const char *e = getenv("PAD_LOG_TIME");
        want = (e && *e && *e != '0') ? 1 : 0;
    }
    if (want) {
        char t[24];
        unsigned long ms = pad_ms();
        int k = snprintf(t, sizeof t, "[%lu.%03lu] ", ms / 1000ul, ms % 1000ul);
        if (k > 0) write(2, t, (unsigned long)k);
    }
    while (s[n]) n++;
    write(2, s, n);
}

/* alsastub.c's say() routes through here, so ALSA lines carry the PAD_LOG_TIME
 * stamp like everything else. They did not, which is why the mixer-open cadence
 * - the one number that would have settled whether the audio retrigger is
 * volume being re-applied - could not be read off a log at all. The two files
 * are separate translation units linked into one hwshim.so, so a plain
 * non-static function crosses, the same way pad_pcm_frames already does. */
void pad_say(const char *s) { logmsg(s); }

/* Defined with the GAME VALIDATION dump further down. It is called from the
 * stdio hooks because the validation module does all of its work through
 * fopen/fseek/ftell/fread, so those calls ARE its trace - and its failing
 * transitions happen long before the first node bus write, which is what the
 * periodic dump alone can sample. */
static void val_probe(const char *what, unsigned long ra,
                      unsigned long a, unsigned long b, unsigned long c);
static void val_sample(void);

static void init(void)
{
    if (real_ioctl) return;
    real_open   = dlsym(RTLD_NEXT, "open");
    real_open64 = dlsym(RTLD_NEXT, "open64");
    real_ioctl  = dlsym(RTLD_NEXT, "ioctl");
}

static char classify(const char *p)
{
    if (!p) return 0;
    if (strstr(p, "/dev/spidev"))  return 'S';
    if (strstr(p, "/dev/i2c"))     return 'I';
    if (strstr(p, "/dev/ttymxc"))  return 'T';
    if (strstr(p, "/dev/mxc_vpu")) return 'V';
    if (strstr(p, "/dev/rtc"))     return 'R';
    return 0;
}

static void nv_load(void);

/* PAD_OPEN_LOG=1 - log every file the game opens, and every open that FAILS.
 * The Tech Alerts screen reports GAME VALIDATION ERROR #2/#3, so the first
 * question is which files the validator actually touches and whether any of
 * them are missing here. Successful opens under /assets/ are skipped unless
 * PAD_OPEN_LOG=2, because scene loading alone is thousands of them. */
static void openlog(const char *path, int ok, unsigned long from,
                    unsigned long dur_ms)
{
    static int mode = -1;
    char b[300];
    if (mode < 0) {
        char *p = getenv("PAD_OPEN_LOG");
        mode = (p && p[0] >= '0' && p[0] <= '9') ? p[0] - '0' : 0;
    }
    if (!mode) return;
    if (ok && mode < 2 && path && strstr(path, "/assets/")) return;
    /* ITEM 17: t= and dur= joined this line for the maintenance-cycle hunt.
     * The bus thread's 681 ms hole is a usleep(100000) loop at 0x5a5f90
     * polling fstream is_open() on the bus object's +0x5d0 member, so the
     * question became WHICH file another thread opens once per cycle and
     * when. pad_ms is the same clock every [nbts] frame is stamped with. */
    snprintf(b, sizeof b, "[open] t=%lu dur=%lu %-6s %s  (from 0x%lx)\n",
             pad_ms(), dur_ms, ok ? "ok" : "FAIL",
             path ? path : "(null)", from);
    logmsg(b);
}

/* PAD_STR_WATCH=<substring> - report the caller of every string the game turns
 * into text containing <substring>, from several angles at once. The
 * "GAME VALIDATION ERROR" rows are reached by index and nothing in the whole
 * binary holds their address, so no static search can find who raises them.
 * A source inside the loaded image (VA < 0x800000) is the .rodata literal
 * itself; anything else is already a copy, i.e. a consumer not the raiser. */
static const char *strwatch_want(void)
{
    static const char *want = (const char *)-1;
    if (want == (const char *)-1) want = getenv("PAD_STR_WATCH");
    return want;
}

static void strwatch_hit(const char *tag, const char *s, unsigned long ra)
{
    static int wbudget = 4000;
    static int busy;
    const char *want = strwatch_want();
    char b[320];
    unsigned long p = (unsigned long)s;
    if (busy || !want || !want[0] || !s) return;
    if (!strstr(s, want) || wbudget-- <= 0) return;
    busy = 1;
    snprintf(b, sizeof b, "[strwatch] %-6s %s ra=0x%lx src=0x%lx \"%.110s\"\n",
             tag, p < 0x800000 ? "IMAGE" : "heap ", ra, p, s);
    logmsg(b);
    busy = 0;
}

static void note(int fd, const char *path)
{
    char buf[256];
    char c = classify(path);
    if (fd >= 0 && fd < MAXFD) faked[fd] = c;
    if (c == 'I') nv_load();
    /* BUDGETED, and saturating. The game re-opens /dev/i2c-1 about 450 times a
     * second for the whole run - 208814 opens in one 8-minute session - so this
     * one unbudgeted line was ~450 write syscalls a second and most of the log's
     * volume. Per device class, so the first few of each are still visible.
     * `if (n++ < X)` would wrap at INT_MAX and come back to life; this does not. */
    if (c) {
        static int seen[128];
        unsigned ci = (unsigned char)c & 127u;
        if (seen[ci] > 8) return;            /* saturated: never comes back */
        seen[ci]++;
        if (seen[ci] == 9) {
            snprintf(buf, sizeof buf,
                     "[hwshim] open class %c: further opens not logged\n", c);
            logmsg(buf);
            return;
        }
    }
    if (c) {
        snprintf(buf, sizeof buf, "[hwshim] open %s -> fd %d class %c\n", path, fd, c);
        logmsg(buf);
    }
}

/* Logging the caller's return address turns any open() into a pointer straight
 * at the code responsible, which is how the scene loader was located. */
static int radium_trace = 14;

/* ---- scene file lifecycle -------------------------------------------- *
 * "The game loaded a scene" means bytes were read out of a scene.radium, not
 * merely that it was opened: the loader opens every scene during enumeration.
 * Tracking each FILE* from fopen/fopen64 through to fclose gives the same
 * number fdstat.py extracts from a QEMU_STRACE log, without the 1.6 GB log.
 */
#define SCENEMAX 128
struct scenef {
    void *f;
    int fd;
    unsigned long bytes, ra;
    unsigned int reads, seeks;
    char path[176];
};
static struct scenef scenes[SCENEMAX];
static int scene_budget = 600;
static int scene_opens, scene_overflow;

static void copystr(char *d, const char *s, int max)
{
    int n = 0;
    while (s[n] && n < max - 1) { d[n] = s[n]; n++; }
    d[n] = 0;
}

/* One dump of the guest memory map: scene.radium is opened from a return
 * address in a shared library, not in the game, and this says which one. */
static void dump_maps(void)
{
    static int done;
    char buf[1024];
    long n;
    int fd;
    long (*real_read)(int, void *, unsigned long);
    if (done) return;
    done = 1;
    init();
    real_read = dlsym(RTLD_NEXT, "read");
    fd = real_open("/proc/self/maps", 0, 0);
    if (fd < 0 || !real_read) return;
    logmsg("[maps] --- guest memory map ---\n");
    while ((n = real_read(fd, buf, sizeof buf - 1)) > 0) {
        buf[n] = 0;
        logmsg(buf);
    }
    logmsg("[maps] --- end ---\n");
}

/* The fopen64 return address lands in libstdc++ (std::ifstream), so the game
 * function responsible is only visible by scanning the stack for words inside
 * the game's own .text - the same trick the SIGSEGV reporter uses. */
static void scene_backtrace(const char *path)
{
    unsigned long *w = (unsigned long *)__builtin_frame_address(0);
    char b[240];
    int i, shown = 0;
    snprintf(b, sizeof b, "[scenebt] opener of %s\n", path);
    logmsg(b);
    for (i = 0; i < 512 && shown < 20; i++) {
        unsigned long v = w[i];
        if (v > 0x16a00 && v < 0x5d3168 && (v & 3) == 0) {
            snprintf(b, sizeof b, "[scenebt]   stack[%3d] = 0x%lx\n", i, v);
            logmsg(b);
            shown++;
        }
    }
}

static void scene_open(void *f, const char *path, unsigned long ra)
{
    static int (*real_fileno)(void *);
    static int bt_auto, bt_demand;
    int i;
    if (!f || !path || !strstr(path, ".radium")) return;
    scene_opens++;
    dump_maps();
    if (strstr(path, "auto_loaded") ? !bt_auto++ : !bt_demand++)
        scene_backtrace(path);
    if (!real_fileno) real_fileno = dlsym(RTLD_NEXT, "fileno");
    for (i = 0; i < SCENEMAX; i++) {
        if (!scenes[i].f) {
            scenes[i].f = f;
            /* Scenes are opened by libstdc++ (std::ifstream), and its reads go
             * straight to read() on the underlying fd rather than through
             * fread, so bytes have to be counted per fd as well. */
            scenes[i].fd = real_fileno ? real_fileno(f) : -1;
            scenes[i].bytes = 0;
            scenes[i].reads = 0;
            scenes[i].seeks = 0;
            scenes[i].ra = ra;
            copystr(scenes[i].path, path, sizeof scenes[i].path);
            {
                static int n;
                if (n++ < 4) {
                    char b[240];
                    snprintf(b, sizeof b, "[sceneopen] FILE*=%p fd=%d slot=%d %s\n",
                             f, scenes[i].fd, i, path);
                    logmsg(b);
                }
            }
            return;
        }
    }
    scene_overflow++;
}

static struct scenef *scene_find(void *f)
{
    int i;
    if (!f) return 0;
    for (i = 0; i < SCENEMAX; i++)
        if (scenes[i].f == f) return &scenes[i];
    return 0;
}

static struct scenef *scene_find_fd(int fd)
{
    int i;
    if (fd < 0) return 0;
    for (i = 0; i < SCENEMAX; i++)
        if (scenes[i].f && scenes[i].fd == fd) return &scenes[i];
    return 0;
}

/* The game imports fopen, fopen64 and open. Radium's FileStream uses the
 * large-file variant, which is why scene loading was invisible until fopen64
 * was interposed too. */
void *shim_fopen(const char *path, const char *mode) __asm__("fopen");
void *shim_fopen(const char *path, const char *mode)
{
    static void *(*real_fopen)(const char *, const char *);
    void *f;
    unsigned long t0 = pad_ms();
    if (!real_fopen) real_fopen = dlsym(RTLD_NEXT, "fopen");
    f = real_fopen(path, mode);
    openlog(path, f != 0, (unsigned long)__builtin_return_address(0),
            pad_ms() - t0);
    scene_open(f, path, (unsigned long)__builtin_return_address(0));
    val_sample();
    if (path && strstr(path, "radium") && radium_trace-- > 0) {
        char b[200];
        snprintf(b, sizeof b, "[trace] fopen(%s,%s) from 0x%lx -> %s\n",
                 path, mode ? mode : "?",
                 (unsigned long)__builtin_return_address(0), f ? "ok" : "NULL");
        logmsg(b);
    }
    return f;
}

void *shim_fopen64(const char *path, const char *mode) __asm__("fopen64");
void *shim_fopen64(const char *path, const char *mode)
{
    static void *(*real_fopen64)(const char *, const char *);
    void *f;
    unsigned long t0 = pad_ms();
    if (!real_fopen64) real_fopen64 = dlsym(RTLD_NEXT, "fopen64");
    f = real_fopen64(path, mode);
    openlog(path, f != 0, (unsigned long)__builtin_return_address(0),
            pad_ms() - t0);
    scene_open(f, path, (unsigned long)__builtin_return_address(0));
    val_sample();
    if (path && strstr(path, "radium") && radium_trace-- > 0) {
        char b[200];
        snprintf(b, sizeof b, "[trace] fopen64(%s,%s) from 0x%lx -> %s\n",
                 path, mode ? mode : "?",
                 (unsigned long)__builtin_return_address(0), f ? "ok" : "NULL");
        logmsg(b);
    }
    return f;
}

/* ---- scene load queue -------------------------------------------------- *
 * Every scene.radium is opened and closed by the enumerator thread (0x444e14)
 * without a single byte being read, so the open pass is a probe and the real
 * work belongs to the "LoadSceneCache" thread (0x447440). Logging the
 * condvar/semaphore traffic with the caller's return address says whether that
 * thread is idle-waiting on a queue nothing ever fills.
 */
static int sync_budget = 400;

static void synclog(const char *op, void *obj, unsigned long ra)
{
    char b[160];
    if (sync_budget-- <= 0) return;
    snprintf(b, sizeof b, "[sync] %-14s obj=%p from=0x%lx\n", op, obj, ra);
    logmsg(b);
}

#define SYNCWRAP(name, sym)                                                   \
    int shim_##name(void *o) __asm__(sym);                                    \
    int shim_##name(void *o)                                                  \
    {                                                                         \
        static int (*real)(void *);                                           \
        unsigned long ra = (unsigned long)__builtin_return_address(0);        \
        if (!real) real = dlsym(RTLD_NEXT, sym);                              \
        if (ra > 0x16a00 && ra < 0x5d3168) synclog(sym, o, ra);               \
        return real(o);                                                       \
    }

SYNCWRAP(cond_signal,    "pthread_cond_signal")
SYNCWRAP(cond_broadcast, "pthread_cond_broadcast")
SYNCWRAP(sem_post,       "sem_post")
SYNCWRAP(sem_wait,       "sem_wait")

int shim_cond_wait(void *c, void *m) __asm__("pthread_cond_wait");
int shim_cond_wait(void *c, void *m)
{
    static int (*real)(void *, void *);
    unsigned long ra = (unsigned long)__builtin_return_address(0);
    if (!real) real = dlsym(RTLD_NEXT, "pthread_cond_wait");
    if (ra > 0x16a00 && ra < 0x5d3168) synclog("pthread_cond_wait", c, ra);
    return real(c, m);
}

int shim_cond_timedwait(void *c, void *m, void *t) __asm__("pthread_cond_timedwait");
int shim_cond_timedwait(void *c, void *m, void *t)
{
    static int (*real)(void *, void *, void *);
    unsigned long ra = (unsigned long)__builtin_return_address(0);
    if (!real) real = dlsym(RTLD_NEXT, "pthread_cond_timedwait");
    if (ra > 0x16a00 && ra < 0x5d3168) synclog("pthread_cond_timedwait", c, ra);
    return real(c, m, t);
}

/* ---- libstdc++ read path ---------------------------------------------- *
 * cereal's loadBinary asks the streambuf for exactly 1 byte (the endianness
 * marker), so a 1-byte xsgetn is a distinctive signature. Hooking all three
 * layers says where the scene reads disappear:
 *   basic_filebuf::xsgetn  -> basic_filebuf::underflow -> __basic_file::xsgetn
 * and only the last one actually calls read()/fread().
 */
static int fb_xsgetn_calls, fb_underflow_calls, bf_xsgetn_calls;
static int fb_xsgetn_small;

/* Per-scene accounting keyed on the filebuf, which is the only handle common to
 * every layer: the ifstream ctor gives path -> rdbuf, cereal's reads arrive at
 * basic_filebuf::xsgetn(rdbuf, ...) and the disk reads at
 * __basic_file::xsgetn(rdbuf + 0x38, ...). Keying on the FILE* or the fd was
 * what made scene reads look like zero. */
#define SBMAX 64
struct sbent {
    void *rdbuf;
    unsigned long asked, fromdisk;
    unsigned int calls, fills;
    int verbose;
    char path[176];
};
static struct sbent sbs[SBMAX];

static struct sbent *sb_find(void *rdbuf, int off)
{
    int i;
    for (i = 0; i < SBMAX; i++)
        if (sbs[i].rdbuf && (char *)sbs[i].rdbuf + off == (char *)rdbuf)
            return &sbs[i];
    return 0;
}

static void sb_report(struct sbent *e)
{
    char b[300];
    snprintf(b, sizeof b,
             "[scenebytes] %8lu asked in %u calls, %8lu off disk in %u fills  %s\n",
             e->asked, e->calls, e->fromdisk, e->fills, e->path);
    logmsg(b);
}

/* Stack-allocated ifstreams reuse the same address for every scene, so flush
 * the previous tenant's totals when a new one claims the slot. */
static void sb_register(void *rdbuf, const char *path)
{
    int i;
    struct sbent *e = sb_find(rdbuf, 0);
    if (e) { sb_report(e); e->rdbuf = 0; }
    for (i = 0; i < SBMAX; i++) {
        if (!sbs[i].rdbuf) {
            sbs[i].rdbuf = rdbuf;
            sbs[i].asked = sbs[i].fromdisk = 0;
            sbs[i].calls = sbs[i].fills = 0;
            copystr(sbs[i].path, path, sizeof sbs[i].path);
            {   /* PAD_SCENE_VERBOSE=<substring of a scene path> dumps every
                 * field cereal pulls out of that one scene, which is how the
                 * 85-byte header gets decoded. */
                char *want = getenv("PAD_SCENE_VERBOSE");
                sbs[i].verbose = (want && *want && strstr(path, want)) ? 1 : 0;
                if (sbs[i].verbose) {
                    char b[240];
                    snprintf(b, sizeof b, "[hdr] === %s ===\n", path);
                    logmsg(b);
                    /* Ground truth: read the same file straight through the
                     * shim's own open()/read(), bypassing libstdc++ entirely. */
                    {
                        static const char hex[] = "0123456789abcdef";
                        long (*rd)(int, void *, unsigned long) = dlsym(RTLD_NEXT, "read");
                        unsigned char buf[16];
                        int fd2;
                        init();
                        fd2 = real_open(path, 0, 0);
                        if (fd2 >= 0 && rd) {
                            long got = rd(fd2, buf, sizeof buf);
                            char *p;
                            snprintf(b, sizeof b, "[hdr] SHIM-DIRECT read %ld : ", got);
                            p = b; while (*p) p++;
                            {
                                int k;
                                for (k = 0; k < got && k < 16; k++) {
                                    *p++ = hex[buf[k] >> 4];
                                    *p++ = hex[buf[k] & 15];
                                    *p++ = ' ';
                                }
                            }
                            *p++ = '\n'; *p = 0;
                            logmsg(b);
                        }
                        if (fd2 >= 0) {
                            int (*cl)(int) = dlsym(RTLD_NEXT, "close");
                            if (cl) cl(fd2);
                        }
                    }
                }
            }
            return;
        }
    }
}

int shim_fb_xsgetn(void *self, char *s, int n)
    __asm__("_ZNSt13basic_filebufIcSt11char_traitsIcEE6xsgetnEPci");
int shim_fb_xsgetn(void *self, char *s, int n)
{
    static int (*real)(void *, char *, int);
    static int budget = 20;
    int r;
    if (!real) real = dlsym(RTLD_NEXT, "_ZNSt13basic_filebufIcSt11char_traitsIcEE6xsgetnEPci");
    r = real(self, s, n);
    fb_xsgetn_calls++;
    {
        struct sbent *e = sb_find(self, 0);
        if (e && r > 0) {
            if (e->verbose) {
                static const char hex[] = "0123456789abcdef";
                char b[160], *p = b;
                int k;
                const char *pre = "[hdr]  +";
                while (*pre) *p++ = *pre++;
                p += 0; /* offset printed below via snprintf for clarity */
                snprintf(b, sizeof b, "[hdr]  +%-5lu n=%-3d ", e->asked, n);
                p = b;
                while (*p) p++;
                for (k = 0; k < r && k < 16; k++) {
                    *p++ = hex[(unsigned char)s[k] >> 4];
                    *p++ = hex[(unsigned char)s[k] & 15];
                    *p++ = ' ';
                }
                *p++ = ' ';
                for (k = 0; k < r && k < 16; k++)
                    *p++ = (s[k] >= 32 && s[k] < 127) ? s[k] : '.';
                *p++ = '\n';
                *p = 0;
                logmsg(b);
            }
            e->asked += (unsigned long)r;
            e->calls++;
        }
    }
    if (n <= 8) {
        fb_xsgetn_small++;
        if (budget-- > 0) {
            char b[160];
            snprintf(b, sizeof b, "[fb] filebuf::xsgetn(this=%p, n=%d) -> %d\n", self, n, r);
            logmsg(b);
        }
    }
    return r;
}

int shim_fb_underflow(void *self)
    __asm__("_ZNSt13basic_filebufIcSt11char_traitsIcEE9underflowEv");
int shim_fb_underflow(void *self)
{
    static int (*real)(void *);
    static int budget = 20;
    int r;
    if (!real) real = dlsym(RTLD_NEXT, "_ZNSt13basic_filebufIcSt11char_traitsIcEE9underflowEv");
    r = real(self);
    fb_underflow_calls++;
    if (budget-- > 0) {
        char b[160];
        snprintf(b, sizeof b, "[fb] filebuf::underflow(this=%p) -> 0x%x\n", self, r);
        logmsg(b);
    }
    return r;
}

int shim_bf_xsgetn(void *self, char *s, int n)
    __asm__("_ZNSt12__basic_fileIcE6xsgetnEPci");
int shim_bf_xsgetn(void *self, char *s, int n)
{
    static int (*real)(void *, char *, int);
    static int budget = 20;
    int r;
    if (!real) real = dlsym(RTLD_NEXT, "_ZNSt12__basic_fileIcE6xsgetnEPci");
    r = real(self, s, n);
    bf_xsgetn_calls++;
    {
        struct sbent *e = sb_find(self, 0x38);
        if (e && r > 0) {
            if (e->verbose) {
                static const char hex[] = "0123456789abcdef";
                char b[160], *p;
                int k;
                snprintf(b, sizeof b, "[hdr] DISK n=%d -> %d : ", n, r);
                p = b; while (*p) p++;
                for (k = 0; k < r && k < 16; k++) {
                    *p++ = hex[(unsigned char)s[k] >> 4];
                    *p++ = hex[(unsigned char)s[k] & 15];
                    *p++ = ' ';
                }
                *p++ = '\n'; *p = 0;
                logmsg(b);
            }
            e->fromdisk += (unsigned long)r;
            e->fills++;
        }
    }
    if (budget-- > 0) {
        char b[160];
        snprintf(b, sizeof b, "[fb] __basic_file::xsgetn(this=%p, n=%d) -> %d\n", self, n, r);
        logmsg(b);
    }
    return r;
}

/* Each scene is opened and closed again with no read in between and no error
 * message, and the loader has __cxa_end_cleanup blocks, which is what a thrown
 * exception caught per scene looks like. __cxa_throw carries the type_info, so
 * the type name and (for anything deriving from std::runtime_error) the
 * message can both be printed here. */
void shim_cxa_throw(void *obj, void *tinfo, void *dest) __asm__("__cxa_throw");
void shim_cxa_throw(void *obj, void *tinfo, void *dest)
{
    static void (*real_throw)(void *, void *, void *);
    static int budget = 6;
    if (!real_throw) real_throw = dlsym(RTLD_NEXT, "__cxa_throw");
    if (budget-- > 0) {
        char b[400];
        const char *name = "?";
        const char *msg = "";
        if (tinfo) {
            const char **np = (const char **)((char *)tinfo + 4);
            if (*np) name = *np;
        }
        /* std::runtime_error/logic_error keep a std::string right after the
         * vptr, and its data pointer is NUL-terminated. */
        if (obj) {
            const char *m = *(const char **)((char *)obj + 4);
            if (m > (const char *)0x10000) msg = m;
        }
        snprintf(b, sizeof b, "[throw] type=%s msg=\"%s\"\n", name, msg);
        logmsg(b);
        {
            unsigned long *w = (unsigned long *)__builtin_frame_address(0);
            int i, shown = 0;
            for (i = 0; i < 400 && shown < 8; i++) {
                unsigned long v = w[i];
                if (v > 0x16a00 && v < 0x5d3168 && (v & 3) == 0) {
                    snprintf(b, sizeof b, "[throw]   stack[%3d] = 0x%lx\n", i, v);
                    logmsg(b);
                    shown++;
                }
            }
        }
    }
    real_throw(obj, tinfo, dest);
}

/* 0x273bd8 is the return address of the operator new(372) inside 0x273bb8,
 * which only the "radium" branch of the loader reaches, and 0x4440bc that of
 * the operator new(52) in the caller. Seeing them proves how far the loader
 * actually gets. */
void *shim_op_new(unsigned long n) __asm__("_Znwj");
void *shim_op_new(unsigned long n)
{
    static void *(*real_new)(unsigned long);
    static int budget = 10;
    unsigned long ra = (unsigned long)__builtin_return_address(0);
    if (!real_new) real_new = dlsym(RTLD_NEXT, "_Znwj");
    if ((ra == 0x273bd8 || ra == 0x4440bc) && budget-- > 0) {
        char b[120];
        snprintf(b, sizeof b, "[new] %lu bytes from 0x%lx\n", n, ra);
        logmsg(b);
    }
    return real_new(n);
}

/* scene.radium is a cereal PortableBinaryInputArchive. The loader at 0x26aa58
 * picks a branch by comparing the file extension against "radium" and then
 * "json", building each literal with std::string(const char*, allocator).
 * 0x26aab8 is the return address of the "radium" construction and 0x26ac2c of
 * the "json" one, so seeing which fires says which branch the loader took
 * without needing a debugger. */
void *shim_string_ctor(void *self, const char *s, const void *a)
    __asm__("_ZNSsC1EPKcRKSaIcE");
void *shim_string_ctor(void *self, const char *s, const void *a)
{
    static void *(*real_ctor)(void *, const char *, const void *);
    static int budget = 40;
    unsigned long ra = (unsigned long)__builtin_return_address(0);
    if (!real_ctor) real_ctor = dlsym(RTLD_NEXT, "_ZNSsC1EPKcRKSaIcE");
    if (ra >= 0x26aa58 && ra <= 0x26ad00 && budget-- > 0) {
        char b[160];
        snprintf(b, sizeof b, "[branch] loader compares against \"%s\" (ra=0x%lx)\n",
                 s ? s : "?", ra);
        logmsg(b);
    }
    strwatch_hit("strctor", s, ra);
    return real_ctor(self, s, a);
}

/* The scene loader's very first act is `if (stream.rdstate() != 0) return ""`,
 * so a stream that opened at the OS level but is not in goodbit state loads
 * nothing and reports no error. Interposing the ifstream constructor is the
 * only way to see that state: read it back out of the basic_ios subobject the
 * same way the game does (vtable[-3] is the virtual-base offset, and
 * _M_streambuf_state sits 20 bytes into ios_base). */
void *shim_ifstream_ctor(void *self, void *str, int mode)
    __asm__("_ZNSt14basic_ifstreamIcSt11char_traitsIcEEC1ERKSsSt13_Ios_Openmode");
void *shim_ifstream_ctor(void *self, void *str, int mode)
{
    static void *(*real_ctor)(void *, void *, int);
    static int budget = 250;
    void *r;
    if (!real_ctor)
        real_ctor = dlsym(RTLD_NEXT,
            "_ZNSt14basic_ifstreamIcSt11char_traitsIcEEC1ERKSsSt13_Ios_Openmode");
    r = real_ctor(self, str, mode);
    {
        const char *path = str ? *(const char **)str : 0;
        if (path && strstr(path, ".radium") && budget-- > 0) {
            char b[300];
            char *vptr = *(char **)self;
            long vbase = *(long *)(vptr - 12);
            char *ios = (char *)self + vbase;
            /* _M_streambuf sits 120 bytes into basic_ios - the offset the game
             * itself uses at 0x273188 to reach rdbuf(). If it does not point
             * into this ifstream object, the archive is not reading the file. */
            snprintf(b, sizeof b,
                     "[ifs] mode=%d rdstate=%d self=%p rdbuf=%p (self+%d)  %s\n",
                     mode, *(int *)(ios + 20), self, *(void **)(ios + 120),
                     (int)((char *)*(void **)(ios + 120) - (char *)self), path);
            logmsg(b);
        }
        if (path && strstr(path, ".radium")) {
            char *vptr = *(char **)self;
            char *ios = (char *)self + *(long *)(vptr - 12);
            sb_register(*(void **)(ios + 120), path);
        }
    }
    return r;
}

/* stdio, not read(): glibc's fopen64/fread reach the kernel through internal
 * calls that LD_PRELOAD cannot see, so the byte counts have to be taken at the
 * stdio layer. */
unsigned long shim_fread(void *p, unsigned long sz, unsigned long n, void *f) __asm__("fread");
unsigned long shim_fread(void *p, unsigned long sz, unsigned long n, void *f)
{
    static unsigned long (*real_fread)(void *, unsigned long, unsigned long, void *);
    unsigned long r;
    struct scenef *s;
    if (!real_fread) real_fread = dlsym(RTLD_NEXT, "fread");
    r = real_fread(p, sz, n, f);
    if ((s = scene_find(f)) != 0) { s->bytes += r * sz; s->reads++; }
    val_probe("fread", (unsigned long)__builtin_return_address(0), sz, n, r);
    {
        static int budget = 25;
        if (budget-- > 0) {
            char b[160];
            snprintf(b, sizeof b, "[fread] FILE*=%p sz=%lu n=%lu -> %lu from 0x%lx\n",
                     f, sz, n, r, (unsigned long)__builtin_return_address(0));
            logmsg(b);
        }
    }
    return r;
}

int shim_fseek(void *f, long off, int wh) __asm__("fseek");
int shim_fseek(void *f, long off, int wh)
{
    static int (*real_fseek)(void *, long, int);
    struct scenef *s;
    if (!real_fseek) real_fseek = dlsym(RTLD_NEXT, "fseek");
    if ((s = scene_find(f)) != 0) s->seeks++;
    val_probe("fseek", (unsigned long)__builtin_return_address(0),
              (unsigned long)off, (unsigned long)wh, 0);
    return real_fseek(f, off, wh);
}

long shim_ftell(void *f) __asm__("ftell");
long shim_ftell(void *f)
{
    static long (*real_ftell)(void *);
    long r;
    if (!real_ftell) real_ftell = dlsym(RTLD_NEXT, "ftell");
    r = real_ftell(f);
    val_probe("ftell", (unsigned long)__builtin_return_address(0), 0, 0,
              (unsigned long)r);
    return r;
}

int shim_fseeko64(void *f, long long off, int wh) __asm__("fseeko64");
int shim_fseeko64(void *f, long long off, int wh)
{
    static int (*real_fseeko64)(void *, long long, int);
    struct scenef *s;
    if (!real_fseeko64) real_fseeko64 = dlsym(RTLD_NEXT, "fseeko64");
    if ((s = scene_find(f)) != 0) s->seeks++;
    return real_fseeko64(f, off, wh);
}

int shim_fclose(void *f) __asm__("fclose");
int shim_fclose(void *f)
{
    static int (*real_fclose)(void *);
    struct scenef *s = scene_find(f);
    if (!real_fclose) real_fclose = dlsym(RTLD_NEXT, "fclose");
    if (s) {
        if (scene_budget-- > 0) {
            char b[300];
            snprintf(b, sizeof b, "[scene] %8lu bytes  %u reads  %u seeks  from 0x%lx  %s\n",
                     s->bytes, s->reads, s->seeks, s->ra, s->path);
            logmsg(b);
        }
        s->f = 0;
    }
    return real_fclose(f);
}

/* The boot step at 0x4f0720 waits for a readiness flag with usleep(250000) in
 * a 480-iteration loop (2 minutes) before it gives up and shows the UI anyway.
 * Seeing that loop run to exhaustion is the difference between "scenes are
 * still loading" and "scene loading never completes". */
/* ★ ITEM 52: THE TWO NODE-BUS SLEEP SITES ARE RECOGNISED BY SHAPE, NOT BY
 * ADDRESS. Both substitutions below (recovery 5 ms pair -> 250 us, reset
 * 2 s -> 1 s) used to key on Godzilla Pro 1.15.0 return addresses
 * (0x59eb94, 0x1d6ec4). On stranger_things the same code lives at 0x4eb5cc
 * and 0x204f5c, the literals matched nothing, and BOTH sleeps ran at the
 * game's own full length - measured 2026-08-18: ST's node-bus service loop
 * ran ONE pass every 3.3 s against godzilla's ~100 Hz tick, every switch
 * closure waited 0.5-2.9 s for its node's scan, and a 113 ms tap read as
 * seconds of hold. The pass itself took 1 ms; the other 3.3 s were these
 * two sleeps at their real-hardware lengths, paid on every failed exchange
 * (ST re-asks its absent node 4 every pass) and every bus reset.
 *
 * The recognisers read the CALLER'S CODE at the return address, which is the
 * same on every title because it is the same source:
 *
 *   recovery  ...; bl X(port,1); mov r0,#5000; bl usleep      <- ra here:
 *             ldr r0,[r4]; mov r1,#0; bl X(port,0); mov r0,#5000; b usleep
 *             so at ra: `ldr r0,[r4]` (e5940000) then `mov r1,#0` (e3a01000)
 *             and the sleep is 5000. The tail-call twin is caught by `armed`
 *             exactly as before.
 *   reset     bl X(assert); movw/movt r0,#2000000; bl usleep   <- ra here:
 *             <release arg>; bl X(release) - so at ra: `mov r0, r5`
 *             (e1a00005, stranger_things) or `mov r0, #1` (e3a00001,
 *             godzilla) followed by a `bl` (top byte 0xeb), sleep 2000000.
 *
 * Verified against both disassemblies (godzilla 0x59eb94 = e5940000
 * e3a01000, 0x1d6ec4 = e3a00001 eb0f35a5; ST 0x4eb5ec = e5940000 e3a01000,
 * 0x204f60 = e1a00005 eb0baf91), so the labelled example keeps exactly the
 * timings it was tuned to. Reads are
 * addr_readable-guarded because a return address into a library that faults
 * would be a crash in usleep. */
static int addr_readable(const void *p);   /* defined with the fault reporter */
static int nb_sleep_site_recover(unsigned long ra)
{
    const unsigned *p = (const unsigned *)ra;
    if (ra < 0x8000ul || ra >= 0x02000000ul) return 0;   /* game image only */
    if (!addr_readable(p) || !addr_readable(p + 1)) return 0;
    return p[0] == 0xe5940000u && p[1] == 0xe3a01000u;
}
static int nb_sleep_site_reset(unsigned long ra)
{
    const unsigned *p = (const unsigned *)ra;
    if (ra < 0x8000ul || ra >= 0x02000000ul) return 0;
    if (!addr_readable(p) || !addr_readable(p + 1)) return 0;
    /* the release argument is `mov r0, r5` on stranger_things and
     * `mov r0, #1` on godzilla - both then `bl` the release */
    return (p[0] == 0xe1a00005u || p[0] == 0xe3a00001u) && (p[1] >> 24) == 0xebu;
}

int shim_usleep(unsigned int us) __asm__("usleep");
int shim_usleep(unsigned int us)
{
    static int (*real_usleep)(unsigned int);
    static unsigned int n;
    if (!real_usleep) real_usleep = dlsym(RTLD_NEXT, "usleep");
    /* 0x4f09a0 is the return address of the usleep(64000) issued at 0x4f099c
     * (0x4f0998 is the mov that sets up its argument), the
     * last thing the boot step does before dispatch(96) and the UI bring-up.
     * Stretching just that one call hands the scene loader thread as much time
     * as it wants, which separates "the load queue is empty" from "the main
     * thread simply wins the race". PAD_BOOT_DELAY=<seconds>. */
    if ((unsigned long)__builtin_return_address(0) == 0x4f09a0) {
        char *d = getenv("PAD_BOOT_DELAY");
        char m[96];
        snprintf(m, sizeof m, "[boot] reached 0x4f0998 usleep(%u); PAD_BOOT_DELAY=%s\n",
                 us, d ? d : "(unset)");
        logmsg(m);
        if (d) {
            int secs = 0, i;
            char b[96];
            for (i = 0; d[i] >= '0' && d[i] <= '9'; i++) secs = secs * 10 + (d[i] - '0');
            snprintf(b, sizeof b, "[sleep] boot hold: %d s before UI bring-up\n", secs);
            logmsg(b);
            for (i = 0; i < secs * 2; i++) real_usleep(500000);
        }
    }
    pad_peek_tick();   /* PAD_PEEK - the periodic site every thread passes through */
    {
        unsigned long ra = (unsigned long)__builtin_return_address(0);
        n++;
        if (n <= 40 || (n % 500) == 0) {
            char b[128];
            snprintf(b, sizeof b, "[sleep] #%u usleep(%u) from 0x%lx\n", n, us, ra);
            logmsg(b);
        }
        /* PAD_SLEEP_CENSUS=<n> - every n sleeps, print total time asked for per
         * call site. The 1-in-500 sampling above is fine for "who sleeps at all"
         * and useless for "where does the boot go": a site called 15000 times
         * for 1 ms costs more than one called 10 times for 200 ms, and sampling
         * ranks them the wrong way round. Totals, not samples. */
        {
            static struct { unsigned long ra; unsigned us; unsigned long n, total; } cs[24];
            static int ncs, every = -1;
            int i;
            if (every < 0) {
                const char *e = getenv("PAD_SLEEP_CENSUS");
                every = 0;
                if (e && *e) { while (*e >= '0' && *e <= '9') every = every * 10 + (*e++ - '0'); }
            }
            if (every > 0) {
                for (i = 0; i < ncs; i++) if (cs[i].ra == ra && cs[i].us == us) break;
                if (i == ncs && ncs < (int)(sizeof cs / sizeof cs[0])) {
                    cs[ncs].ra = ra; cs[ncs].us = us; ncs++;
                }
                if (i < (int)(sizeof cs / sizeof cs[0])) {
                    cs[i].n++;
                    cs[i].total += us;
                }
                if ((n % (unsigned)every) == 0) {
                    char b[160];
                    /* ASKED FOR, not slept. This census runs BEFORE the two
                     * substitutions below, on purpose: it has to keep showing
                     * the game's own timing so a site stays comparable across
                     * runs with and without them. A line reading
                     * "usleep(2000000) x 6 = 12000 ms" with PAD_NB_RESET_US at
                     * its default means 6 resets that actually slept 0.6 s. */
                    logmsg("[slpcensus] --- total microseconds ASKED FOR (pre-substitution) ---\n");
                    for (i = 0; i < ncs; i++) {
                        snprintf(b, sizeof b,
                                 "[slpcensus] 0x%08lx usleep(%7u) x %-7lu = %lu ms\n",
                                 cs[i].ra, cs[i].us, cs[i].n, cs[i].total / 1000ul);
                        logmsg(b);
                    }
                }
            }
        }
        /* THE NODE BUS RECOVERY SLEEP - the single biggest cost of booting.
         *
         * 0x59eb74 is the exchange wrapper's recovery path, run after a failed
         * exchange, and it is two 5 ms sleeps around a line-state toggle:
         *
         *     59eb88  bl 5a7ba0(port, 1)      ; assert
         *     59eb90  bl usleep(5000)         ; <- return address 0x59eb94
         *     59eb9c  bl 5a7ba0(port, 0)      ; release
         *     59eba8  b  usleep(5000)         ; TAIL CALL, so its return
         *                                     ;   address is the CALLER's
         *
         * On a real machine that is a physical RS485 bus settling. Here there is
         * no bus: the shim answers out of memory, instantly. Every failed
         * exchange therefore buys 10 ms of pure wall clock for nothing, and the
         * boot spends ~1520 of them on node 2 alone - the board a Godzilla Pro
         * does not have and which can never answer.
         *
         * The second sleep is a TAIL CALL, so it cannot be recognised by its
         * return address - that address belongs to whoever called 0x59eb74.
         * `armed` carries the recognition across the pair instead. The node bus
         * lives on one dedicated thread so the pair is not interleaved; if two
         * threads ever did land here at once the only consequence is one extra
         * 5 ms sleep somewhere being shortened, which is the same class of
         * change as the intended one.
         *
         * PAD_NB_RECOVER_US=<us> sets the replacement (default 250).
         * PAD_NB_RECOVER_US=5000 restores the game's own timing exactly. */
        {
            static int rec_us = -1;
            static int armed;
            if (rec_us < 0) {
                const char *e = getenv("PAD_NB_RECOVER_US");
                rec_us = 250;
                if (e && *e) {
                    int v = 0;
                    while (*e >= '0' && *e <= '9') v = v * 10 + (*e++ - '0');
                    rec_us = v;
                }
            }
            if (us == 5000 && (nb_sleep_site_recover(ra) || armed)) {
                armed = nb_sleep_site_recover(ra);
                if (rec_us < (int)us) us = (unsigned int)rec_us;
            } else {
                armed = 0;
            }
        }

        /* THE NODE BUS RESET PULSE - the other half, and the bigger half.
         *
         * 0x1d6e98(ms) is a broadcast bus reset:
         *
         *     1d6ea8  bl 5a4564(0)            ; assert - frame {.., 7, 1, 0, 0}
         *     1d6ec0  bl usleep(2000000)      ; <- return address 0x1d6ec4
         *     1d6ec8  bl 5a4564(1)            ; release
         *     1d6ee4  b  usleep(ms * 1000)    ; caller's own settle time
         *
         * TWO WHOLE SECONDS, and its three callers - 0x1d73b4, 0x1d7474 and
         * 0x1d7510 - are all inside bring-up 0x1d734c and its 5-pass retry loop,
         * i.e. squarely on the critical path. Measured with PAD_SLEEP_CENSUS:
         * five calls, 10.0 s of the boot, the single largest item.
         *
         * On a real machine that is a node board actually rebooting and needing
         * time to come back. Here the "boards" are a few hundred bytes in this
         * process and are back before the call returns.
         *
         * PAD_NB_RESET_US=<us> sets the replacement. PAD_NB_RESET_US=2000000
         * restores the game's own timing exactly.
         *
         * DEFAULT 1000000 (1 s), AND THE VALUE IS LOAD-BEARING FOR THE SOUND,
         * not just for the clock. At 0.1 s the boot buzzes: the mixer voice
         * underruns and restarts ~15 times a second for seven seconds - see
         * "ONE SOUND STUTTERING" in the handoff. Measured, restarts of that
         * voice against time-to-attract:
         *
         *     0.1 s  -> 118 restarts, buzz to 10.8 s,  boot 14.5 s
         *     0.5 s  -> 135 restarts, buzz to 11.5 s   (WORSE - it is a race)
         *     1.0 s  ->   3 restarts, buzz to  3.9 s,  boot 14.5 s   <- default
         *     2.0 s  ->  17 restarts, buzz to  4.8 s,  boot 21.8 s
         *
         * 1 s costs NOTHING in boot time - these sleeps overlap the node 2 retry
         * storm instead of extending the critical path - and it is the whole
         * difference between a boot that sounds broken and one that does not.
         * Three consecutive runs at 1 s gave 3 restarts every time.
         *
         * DO NOT "optimise" this back down without re-running the restart count.
         * 0.5 s being worse than 0.1 s is the warning: this is not monotonic,
         * it is a race between the audio producer catching up and the next burst
         * of bring-up work.
         *
         * It is also deliberately not 0: the reset is a real protocol step, the
         * boards' own state is torn down and rebuilt around it, and there is no
         * reason to find out the hard way what needs a non-zero gap. */
        {
            static int rst_us = -1;
            if (rst_us < 0) {
                const char *e = getenv("PAD_NB_RESET_US");
                rst_us = 1000000;
                if (e && *e) {
                    int v = 0;
                    while (*e >= '0' && *e <= '9') v = v * 10 + (*e++ - '0');
                    rst_us = v;
                }
            }
            if (us == 2000000 && nb_sleep_site_reset(ra) && rst_us < (int)us)
                us = (unsigned int)rst_us;
        }
    }
    if (!us) return 0;
    return real_usleep(us);
}

/* The six validation messages are printf format strings (#4/#5 carry two
 * numbers, #6 three), so whoever raises them almost certainly formats them.
 * The game imports snprintf and vsnprintf; its own sprintf at 0x1c2a4 is local
 * code but reaches vsnprintf through the PLT, so both routes land here. */
int shim_vsnprintf(char *b, unsigned long n, const char *f, va_list ap) __asm__("vsnprintf");
int shim_vsnprintf(char *b, unsigned long n, const char *f, va_list ap)
{
    static int (*real_vsnprintf)(char *, unsigned long, const char *, va_list);
    if (!real_vsnprintf) real_vsnprintf = dlsym(RTLD_NEXT, "vsnprintf");
    strwatch_hit("vsnprf", f, (unsigned long)__builtin_return_address(0));
    return real_vsnprintf(b, n, f, ap);
}

int shim_snprintf(char *b, unsigned long n, const char *f, ...) __asm__("snprintf");
int shim_snprintf(char *b, unsigned long n, const char *f, ...)
{
    static int (*real_vsnprintf)(char *, unsigned long, const char *, va_list);
    va_list ap; int r;
    if (!real_vsnprintf) real_vsnprintf = dlsym(RTLD_NEXT, "vsnprintf");
    strwatch_hit("snprf", f, (unsigned long)__builtin_return_address(0));
    va_start(ap, f);
    r = real_vsnprintf(b, n, f, ap);
    va_end(ap);
    return r;
}

/* ---- /dev/mxc_vpu mmap: the i.MX6 VPU's shared control block ------------
 *
 * The boot video is the first thing that ever exercised the hardware decoder,
 * and it faults immediately: pc = libpthread+0x91c4 with r0 = 0, which is
 * `pthread_mutex_timedlock(NULL)` at its very first instruction
 * (`ldr ip, [r0, #12]`). The only importer of that symbol in the whole rootfs
 * is usr/lib/libvpu.so.4, so the caller is Freescale's VPU userspace library
 * taking the lock on its shared semaphore block - a block it gets by mmap()ing
 * the VPU device. With no interposer, that mmap fails and the semaphore
 * pointer is NULL.
 *
 * Handing it an anonymous zeroed mapping is the right shape rather than a
 * dodge: a zero-filled pthread_mutex_t IS a valid default-initialised mutex on
 * glibc, so the lock succeeds instead of faulting, and every other field the
 * library reads reads as zero rather than as a wild address.
 *
 * This does NOT make the VPU decode anything. It clears one null and lets the
 * failure move to wherever the library actually needs real hardware.
 * PAD_VPU_MMAP=0 turns it off to get the old behaviour back for comparison. */
static void *(*real_mmap)(void *, unsigned long, int, int, int, long);
static void *(*real_mmap64)(void *, unsigned long, int, int, int, long long);

static void *vpu_anon(unsigned long len)
{
    void *r;
    char b[140];
    if (!real_mmap) real_mmap = dlsym(RTLD_NEXT, "mmap");
    if (!real_mmap) return (void *)-1;
    /* PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS */
    r = real_mmap(0, len, 1 | 2, 0x02 | 0x20, -1, 0);
    {
        static int budget = 6;
        if (budget > 0) {
            budget--;
            snprintf(b, sizeof b, "[vpu] anonymous mmap len=%lu -> %p\n", len, r);
            logmsg(b);
        }
    }
    return r;
}

static int vpu_mmap_on(void)
{
    static int on = -1;
    if (on == -1) { char *q = getenv("PAD_VPU_MMAP"); on = !(q && *q == '0'); }
    return on;
}

void *shim_mmap(void *a, unsigned long len, int prot, int flags, int fd, long off) __asm__("mmap");
void *shim_mmap(void *a, unsigned long len, int prot, int flags, int fd, long off)
{
    init();
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'V' && vpu_mmap_on())
        return vpu_anon(len);
    if (!real_mmap) real_mmap = dlsym(RTLD_NEXT, "mmap");
    return real_mmap(a, len, prot, flags, fd, off);
}

void *shim_mmap64(void *a, unsigned long len, int prot, int flags, int fd, long long off) __asm__("mmap64");
void *shim_mmap64(void *a, unsigned long len, int prot, int flags, int fd, long long off)
{
    init();
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'V' && vpu_mmap_on())
        return vpu_anon(len);
    if (!real_mmap64) real_mmap64 = dlsym(RTLD_NEXT, "mmap64");
    if (real_mmap64) return real_mmap64(a, len, prot, flags, fd, off);
    if (!real_mmap) real_mmap = dlsym(RTLD_NEXT, "mmap");
    return real_mmap(a, len, prot, flags, fd, (long)off);
}

int shim_open(const char *path, int flags, ...) __asm__("open");
int shim_open(const char *path, int flags, ...)
{
    va_list ap; int m; int fd;
    unsigned long t0;
    init();
    va_start(ap, flags); m = va_arg(ap, int); va_end(ap);
    t0 = pad_ms();
    fd = real_open(path, flags, m);
    openlog(path, fd >= 0, (unsigned long)__builtin_return_address(0),
            pad_ms() - t0);
    if (path && strstr(path, "radium") && radium_trace-- > 0) {
        char b[200];
        snprintf(b, sizeof b, "[trace] open(%s) called from 0x%lx\n",
                 path, (unsigned long)__builtin_return_address(0));
        logmsg(b);
    }
    note(fd, path);
    return fd;
}

int shim_open64(const char *path, int flags, ...) __asm__("open64");
int shim_open64(const char *path, int flags, ...)
{
    va_list ap; int m; int fd;
    unsigned long t0;
    init();
    va_start(ap, flags); m = va_arg(ap, int); va_end(ap);
    t0 = pad_ms();
    fd = real_open64 ? real_open64(path, flags, m) : real_open(path, flags, m);
    openlog(path, fd >= 0, (unsigned long)__builtin_return_address(0),
            pad_ms() - t0);
    if (path && strstr(path, "radium") && radium_trace-- > 0) {
        char b[200];
        snprintf(b, sizeof b, "[trace] open64(%s) called from 0x%lx\n",
                 path, (unsigned long)__builtin_return_address(0));
        logmsg(b);
    }
    note(fd, path);
    return fd;
}

/* The game runs its game-loop threads at SCHED_RR. An unprivileged host user
 * cannot grant real-time priority, and the failure is fatal (error 229). */
int shim_sched_setscheduler(int pid, int policy, const void *p) __asm__("sched_setscheduler");
int shim_sched_setscheduler(int pid, int policy, const void *p)
{
    (void)pid; (void)policy; (void)p;
    return 0;
}

int shim_pthread_setschedparam(unsigned long t, int policy, const void *p) __asm__("pthread_setschedparam");
int shim_pthread_setschedparam(unsigned long t, int policy, const void *p)
{
    (void)t; (void)policy; (void)p;
    return 0;
}

/* Threads are requested with an explicit SCHED_RR policy, which glibc applies
 * from inside pthread_create through a non-interposable internal call. Forcing
 * the attribute back to PTHREAD_INHERIT_SCHED (0) stops it from trying, while
 * leaving the policy the caller set visible to its own sanity checks. */
static int (*real_pthread_create)(unsigned long *, void *, void *(*)(void *), void *);
static int (*real_attr_setinheritsched)(void *, int);

#define THMAX 128
static struct { void *(*fn)(void *); void *arg; int id; } thslot[THMAX];

/* ---- IS THIS ABSOLUTE ADDRESS MAPPED? -----------------------------------
 *
 * Every hard-coded address in this shim came out of ONE title's binary, and in
 * another title's it is very likely not mapped at all. Dereferencing one does
 * not produce a wrong answer, it kills the process - and it did: the first
 * attempt to boot a second title (TMNT 1.59) died at 0.06 s inside the shim's
 * own [thread] log line, because that line prints the audio gate byte from
 * 0x7acb54 and TMNT's image ends around 0x6e8000. The crash looked like a
 * threading bug and was a printf.
 *
 * write() to /dev/null returns EFAULT for an unreadable buffer rather than
 * faulting, so this asks the kernel instead of assuming. The result is cached
 * for the last address asked about, which is enough: these are asked per thread
 * start and per log line, always about the same one or two addresses.
 *
 * ANY new absolute address in this file must go through here.
 *
 * ★★★ AND THE ONE-ADDRESS CACHE IS FINE UNTIL SOMETHING SCANS, at which point
 * it is a catastrophe, which is what it turned out to be for stranger_things.
 * sw_find_table() walks every writable region of the guest at a 4-BYTE step and
 * asks about `e` and `e+28` per candidate - two different pointers, so the
 * `p == last` memo never hits and every 4 bytes of address space costs two to
 * four real write(2) syscalls under qemu-user. Godzilla never pays it
 * (sw_configured_ok() validates on tick 0 and the search is never called); a
 * title whose configured address does not validate pays it on bus-write ticks
 * 0, 8, 16, 24.
 *
 * THAT SEARCH RUNS INSIDE THE GUEST'S write() TO THE NODE BUS, so the bus
 * thread is blocked for its whole duration. Measured on stranger_things: three
 * dead windows of 38.8 s, 43.7 s and 43.4 s, each beginning at exactly a search
 * tick and at no other frame - about 126 s of a 180 s run. The game asked its
 * first discovery question at t=57 s and the shim answered "bus empty", because
 * the node-directory seed cannot exist until the FOURTH search failure, which
 * is t=145 s. The game gave up at 155 s. None of that is the game's doing and
 * none of it is a protocol problem; it is this cache.
 *
 * ▼▼▼ THE PAGE CACHE IS BACK, AND ONLY BECAUSE THE FAULT GUARD EXISTS. The
 * first attempt cached the probe per page with no guard, and it worked as
 * intended - the four dead windows collapsed, the node-directory seed moved
 * from t=145 s to t=20 s, TX went 149 -> 990 - and then took a SIGSEGV inside
 * sw_entry_ok, twice, at two different pcs, in runs where no pre-change build
 * had ever taken one. The half of "readability" that is not a page property
 * is WHEN: the scan walks a /proc/self/maps snapshot while the guest
 * allocates and frees scene memory, so a page probed readable early in a scan
 * can be gone by the time the walk reaches it, and the cache then hands
 * sw_entry_ok a yes for memory that is no longer there.
 *
 * The answer to WHEN is not a fresher probe - any probe is stale by the time
 * the read lands - it is to make the stale yes SURVIVABLE. sw_find_table
 * wraps the scan in a sigsetjmp guard hooked into the SIGSEGV handlers this
 * file already owns: a fault on the scanning thread aborts the scan (counted
 * as a failed search, retried on a later tick) instead of killing the
 * process. The cache below is armed only while that guard is (pr_gen != 0),
 * so nothing outside a guarded scan can ever act on a scan-lifetime answer,
 * and outside a scan this function is exactly the one-address memo it always
 * was. */
#define PR_SLOTS 2048
static struct pr_slot { unsigned page, gen; unsigned char ok; } pr_tab[PR_SLOTS];
static unsigned pr_gen;            /* nonzero while a guarded scan runs */

static int addr_readable(const void *p)
{
    static long (*w)(int, const void *, unsigned long);
    static int nullfd = -2;
    static const void *last;
    static int lastok;
    if (!p) return 0;
    if (!pr_gen && p == last) return lastok;
    if (nullfd == -2) {
        int (*ro)(const char *, int, ...) = dlsym(RTLD_NEXT, "open");
        w = dlsym(RTLD_NEXT, "write");
        nullfd = ro ? ro("/dev/null", 1 /*O_WRONLY*/, 0) : -1;
    }
    if (pr_gen) {
        unsigned page = (unsigned)(unsigned long)p >> 12;
        struct pr_slot *c = &pr_tab[(page ^ (page >> 11)) & (PR_SLOTS - 1)];
        if (c->gen == pr_gen && c->page == page) return c->ok;
        c->page = page;
        c->gen  = pr_gen;
        c->ok   = (unsigned char)(nullfd >= 0 && w && w(nullfd, p, 1) == 1);
        return c->ok;
    }
    last = p;
    lastok = (nullfd >= 0 && w && w(nullfd, p, 1) == 1);
    return lastok;
}

/* PAD_PEEK=<hexaddr>[:<len>][,<hexaddr>[:<len>]]... - LOG GUEST GLOBALS WHEN
 * THEY CHANGE. The shim shares the guest's address space, so a global the game
 * keeps in .bss is just a pointer here.
 *
 * WHY THIS EXISTS, and it is the lesson of item 52's frequency pass: a whole
 * day went into "what does the code do?", which disassembly answers, and the
 * question that actually mattered was "what did the game MEASURE?", which it
 * cannot. Every earlier attempt at that question took the form of changing an
 * input and re-running to see whether the symptom moved - one bit of evidence
 * per rig run, on a rig that is a mutex between sessions. This reads the answer
 * directly. `len` defaults to 4 and caps at 64; up to 8 addresses.
 *
 * Deduped on value, so a static global prints once and a changing one prints
 * its transitions - the same discipline the screen oracle uses, and for the
 * same reason: an undeduped 5 Hz dump is thousands of identical lines.
 *
 * A leading `*` DEREFERENCES: `*0x724608:176` reads the pointer at 0x724608 and
 * dumps 176 bytes from wherever it points. Half of what this rig wants to look
 * at is reached that way - a game table is a pointer in .data or .bss and the
 * table itself is on the heap, so without this every question costs two runs
 * (one to learn the pointer, one to read through it) and the second run gets a
 * different heap.
 */
#define PEEK_MAX   8
#define PEEK_BYTES 192
static struct peek_slot {
    unsigned addr, len;
    int deref;
    unsigned char last[PEEK_BYTES];
    int primed;
} peek_slot[PEEK_MAX];
static int peek_n = -1;

static void peek_init(void)
{
    const char *p = getenv("PAD_PEEK");
    char m[120];
    peek_n = 0;
    if (!p || !*p) return;
    while (*p && peek_n < PEEK_MAX) {
        unsigned a = 0, l = 4;
        int got = 0, deref = 0;
        while (*p == ',' || *p == ' ') p++;
        if (*p == '*') { deref = 1; p++; }
        if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) p += 2;
        for (;;) {
            int d;
            if (*p >= '0' && *p <= '9')      d = *p - '0';
            else if (*p >= 'a' && *p <= 'f') d = *p - 'a' + 10;
            else if (*p >= 'A' && *p <= 'F') d = *p - 'A' + 10;
            else break;
            a = a * 16u + (unsigned)d; p++; got = 1;
        }
        if (!got) break;
        if (*p == ':') {
            p++; l = 0;
            while (*p >= '0' && *p <= '9') l = l * 10u + (unsigned)(*p++ - '0');
        }
        if (l == 0 || l > PEEK_BYTES) l = 4;
        peek_slot[peek_n].addr  = a;
        peek_slot[peek_n].len   = l;
        peek_slot[peek_n].deref = deref;
        peek_n++;
        while (*p && *p != ',') p++;
    }
    snprintf(m, sizeof m, "[peek] watching %d address(es)\n", peek_n);
    logmsg(m);
}

static void pad_peek_tick(void)
{
    static unsigned long next_ms;
    int i, j;
    if (peek_n < 0) peek_init();
    if (peek_n <= 0) return;
    if (pad_ms() < next_ms) return;
    next_ms = pad_ms() + 200;
    for (i = 0; i < peek_n; i++) {
        struct peek_slot *s = &peek_slot[i];
        const unsigned char *g;
        unsigned char cur[PEEK_BYTES];
        char m[700];
        unsigned at = s->addr;
        int o, same = 1;
        if (!addr_readable((const void *)(unsigned long)at)) continue;
        if (s->deref) {
            at = *(const unsigned *)(unsigned long)at;
            if (!at || !addr_readable((const void *)(unsigned long)at)) continue;
        }
        g = (const unsigned char *)(unsigned long)at;
        if (!addr_readable(g + s->len - 1)) continue;
        for (j = 0; j < (int)s->len; j++) cur[j] = g[j];
        for (j = 0; j < (int)s->len; j++)
            if (cur[j] != s->last[j]) { same = 0; break; }
        if (s->primed && same) continue;
        for (j = 0; j < (int)s->len; j++) s->last[j] = cur[j];
        s->primed = 1;
        o = snprintf(m, sizeof m, "[peek] t=%lu %s0x%08x%s:", pad_ms(),
                     s->deref ? "*" : "", s->addr, s->deref ? "" : "");
        if (s->deref)
            o += snprintf(m + o, sizeof m - (unsigned)o, " ->0x%08x", at);
        for (j = 0; j < (int)s->len && o < (int)sizeof m - 6; j++)
            o += snprintf(m + o, sizeof m - (unsigned)o, " %02x", cur[j]);
        snprintf(m + o, sizeof m - (unsigned)o, "\n");
        logmsg(m);
    }
}

/* Declared here because the SEGV report, far above where these are defined,
 * asks "is this the title those addresses came from?" before printing any of
 * them. Non-zero means the configured Godzilla Pro addresses are mapped. */
static unsigned a_sw_struct(void);

/* The audio streaming worker's start gate: a byte the worker reads ONCE and
 * then spins on in a register. 0x7acb54 is where Godzilla Pro 1.15.0 keeps it.
 * PAD_AUDIO_GATE=<hex> moves it for another title; unset and unmapped are
 * treated the same, which is "there is no gate here" rather than a guess. */
static unsigned char *gate_addr(void)
{
    static unsigned char *v;
    static int done;
    if (!done) {
        const char *e = getenv("PAD_AUDIO_GATE");
        unsigned long a = 0x7acb54UL;
        done = 1;
        if (e && *e) {
            /* Parsed here rather than with the file's ishex/hexval, which are
             * defined a thousand lines further down. */
            a = 0;
            if (e[0] == '0' && (e[1] == 'x' || e[1] == 'X')) e += 2;
            for (; *e; e++) {
                int c = *e;
                if (c >= '0' && c <= '9') c -= '0';
                else if (c >= 'a' && c <= 'f') c -= 'a' - 10;
                else if (c >= 'A' && c <= 'F') c -= 'A' - 10;
                else break;
                a = a * 16 + (unsigned long)c;
            }
        }
        v = (a && addr_readable((void *)a)) ? (unsigned char *)a : 0;
    }
    return v;
}

/* The gate's value, or -1 when this title has no gate we know of. */
static int gate_val(void)
{
    unsigned char *g = gate_addr();
    return g ? (int)*(volatile unsigned char *)g : -1;
}

/* An address of one of the GAME's own tables, from the environment if this
 * title's is known, and 0 if what we have is not mapped - see the TITLE_ADDR
 * block further down for the list and for why it exists. */
static unsigned title_addr(const char *env, unsigned dflt)
{
    const char *e = getenv(env);
    unsigned long a = dflt;
    if (e && *e) {
        a = 0;
        if (e[0] == '0' && (e[1] == 'x' || e[1] == 'X')) e += 2;
        for (; *e; e++) {
            int c = *e;
            if (c >= '0' && c <= '9') c -= '0';
            else if (c >= 'a' && c <= 'f') c -= 'a' - 10;
            else if (c >= 'A' && c <= 'F') c -= 'A' - 10;
            else break;
            a = a * 16 + (unsigned long)c;
        }
    }
    return (a && addr_readable((const void *)a)) ? (unsigned)a : 0u;
}

/* Resolve once, on first use, and remember - including remembering 0. */
#define TITLE_ADDR(fn, env, dflt)                           \
    static unsigned fn(void)                                \
    {                                                       \
        static unsigned v;                                  \
        static int done;                                    \
        if (!done) { done = 1; v = title_addr(env, dflt); } \
        return v;                                           \
    }

/* READ ONE OF THE GAME'S TABLES SAFELY. A TITLE_ADDR is 0 when this title's
 * address is unknown or unmapped, and `*(unsigned *)0` is as fatal as reading
 * some other title's address - it is how the second boot attempt died, in
 * sw_force(), which loads three of them before its first check.
 *
 * Every reader downstream already rejects a zero with sw_ok() or an equivalent
 * bounds test, so returning 0 turns "we do not know where this title keeps its
 * switch table" into "there is no switch state", which is true and survivable.
 * Reading at an offset needs its own form: SW_STRUCT + 4 is 4, not 0, when the
 * base is unknown, and 4 is just as unmapped and far less obvious. */
static unsigned tread_at(unsigned base, unsigned off)
{
    return base ? *(const unsigned *)(unsigned long)(base + off) : 0u;
}

static unsigned tread(unsigned addr) { return tread_at(addr, 0); }

static int thentry_enabled(void)
{
    char *p = getenv("PAD_THREAD_ENTRY");
    return p && p[0] == '1';
}

static int ungate_enabled(void)
{
    char *p = getenv("PAD_AUDIO_UNGATE");
    return p && p[0] == '1';
}

static void *th_tramp(void *p)
{
    struct { void *(*fn)(void *); void *arg; int id; } *s = p;
    char b[120];
    /* Several thread bodies open with `ldrb r3,[0x7acb54]; cmp r3,#0; bne .-4`,
     * which loads the byte once and then spins on the register - so what
     * matters is the value at the instant the thread starts, not at the crash.
     * The audio streaming worker (body 0x459604) is one of them. */
    snprintf(b, sizeof b, "[thread] #%d ENTERED body=0x%lx gate=%d\n",
             s->id, (unsigned long)s->fn, gate_val());
    logmsg(b);
    /* The audio streaming worker reads 0x7acb54 once and spins on the register,
     * so starting while the byte is 1 wedges it permanently even though the
     * byte is 0 seconds later. Do the re-reading wait the code meant to do,
     * on its own thread, before handing control over. */
    if (ungate_enabled() && (unsigned long)s->fn == 0x459604 && gate_addr()) {
        static int (*real_usleep)(unsigned long);
        volatile unsigned char *g = gate_addr();
        int waited = 0;
        if (!real_usleep) real_usleep = dlsym(RTLD_NEXT, "usleep");
        while (*g && waited < 5000) {
            if (real_usleep) real_usleep(1000);
            waited++;
        }
        snprintf(b, sizeof b,
                 "[thread] #%d waited %d ms for gate; gate now %d\n",
                 s->id, waited, (int)*g);
        logmsg(b);
    }
    {
        void *r = s->fn(s->arg);
        snprintf(b, sizeof b, "[thread] #%d RETURNED body=0x%lx\n",
                 s->id, (unsigned long)s->fn);
        logmsg(b);
        return r;
    }
}

int shim_pthread_create(unsigned long *th, void *attr, void *(*fn)(void *), void *arg) __asm__("pthread_create");
int shim_pthread_create(unsigned long *th, void *attr, void *(*fn)(void *), void *arg)
{
    if (!real_pthread_create) {
        real_pthread_create = dlsym(RTLD_NEXT, "pthread_create");
        real_attr_setinheritsched = dlsym(RTLD_NEXT, "pthread_attr_setinheritsched");
    }
    if (attr && real_attr_setinheritsched)
        real_attr_setinheritsched(attr, 0);
    {
        static int n;
        char b[160];
        /* pthread_create is called from several threads at once, so the
         * counter has to be atomic and the slot index has to come from this
         * thread's own increment - reading `n` again races and hands two
         * threads the same slot, which sends one of them into the wrong body. */
        int myn = __sync_fetch_and_add(&n, 1) + 1;
        if (myn <= 80) {
            snprintf(b, sizeof b, "[thread] #%d start=0x%lx from=0x%lx\n",
                     myn, (unsigned long)fn,
                     (unsigned long)__builtin_return_address(0));
            logmsg(b);
        }
        /* QEMU_LOG=in_asm turned out to log only a subset of threads - the
         * whole scene-loading path and even main() are absent from it - so it
         * cannot answer "did this thread run?". Wrapping the start routine
         * can. Off by default: substituting the entry point is a real change
         * to the guest, so the validation baseline must not depend on it. */
        if (thentry_enabled()) {
            int slot = myn - 1;
            if (slot >= 0 && slot < THMAX) {
                int rc;
                thslot[slot].fn = fn;
                thslot[slot].arg = arg;
                thslot[slot].id = myn;
                rc = real_pthread_create(th, attr, th_tramp, &thslot[slot]);
                snprintf(b, sizeof b, "[thread] #%d create rc=%d\n", myn, rc);
                logmsg(b);
                return rc;
            }
        }
    }
    return real_pthread_create(th, attr, fn, arg);
}

/* ---------------- survivable null page (diagnostic) ------------------- *
 * The game calls virtual methods on lookup results without checking them, so
 * one missing object stops everything. Mapping guest address 0 turns those
 * calls into no-ops: word 0 points at a fake vtable full of pointers to a
 * `bx lr` stub, so `ldr r3,[r0]; ldr r3,[r3,#N]; blx r3` returns harmlessly.
 *
 * This masks real bugs and is strictly a probe for what lies beyond the first
 * null. Opt in with PAD_NULL_PAGE=1.
 */
extern void *mmap(void *, unsigned long, int, int, int, long);
extern char *getenv(const char *);

__attribute__((constructor))
static void map_null_page(void)
{
    char b[120];
    unsigned int *p;
    void *r;
    char *e = getenv("PAD_NULL_PAGE");
    if (!(e && e[0] == '1')) return;

    r = mmap((void *)0, 0x3000, 1 | 2 | 4, 0x02 | 0x10 | 0x20, -1, 0);
    if (r != (void *)0) {
        snprintf(b, sizeof b, "[nullpage] mmap at 0 failed (got %p)\n", r);
        logmsg(b);
        return;
    }
    p = (unsigned int *)0;
    p[0] = 0x1000;                        /* object -> fake vtable        */
    for (p = (unsigned int *)0x1000; p < (unsigned int *)0x2000; p++)
        *p = 0x2000;                      /* every slot -> the stub       */
    for (p = (unsigned int *)0x2000; p < (unsigned int *)0x3000; p++)
        *p = 0xe12fff1e;                  /* bx lr                        */
    logmsg("[nullpage] guest address 0 mapped; null virtual calls are no-ops\n");
}

/* ---------------- fault reporter -------------------------------------- *
 * The game installs its own SIGSEGV handler that returns, so a null deref
 * turns into an endless fault loop with nothing to show for it. Taking the
 * handler over reports the faulting PC once and stops.
 *
 * TWO MODES, because those are two different jobs (item 41, 2026-08-11):
 *
 *   HEADER mode (on by default) reports and gets out of the way. It prints
 *   pc/lr/r0/fault and the /proc/self/maps line containing the pc, then hands
 *   the fault onward exactly as it would have gone without us - to the game's
 *   own handler if it registered one, otherwise to SIG_DFL. So it changes
 *   NOTHING about how a run lives or dies; it only means the death has a
 *   signature. Turn it off with PAD_SEGV_HEADER=0.
 *
 *   FULL mode (PAD_SEGV_REPORT=1) is the old behaviour: take the handler over
 *   completely, dump the mixer/loader/event state below, and _exit(99).
 *
 * WHY HEADER MODE HAD TO EXIST. Everything below only ever ran when the GAME
 * called sigaction(11) - we installed ours by interposing that call. Item 41's
 * two turtles_pro crashes died with `qemu: uncaught target signal 11`, which is
 * qemu-user saying the guest had NO handler registered, so the interpose never
 * fired and the most informative crash reporter in the rig sat unused through
 * the exact fault it was built for. A reporter that depends on the faulting
 * program asking for it is not a reporter. This one installs itself from a
 * constructor.
 */
extern void _exit(int);
extern char *getenv(const char *);

static int (*real_sigaction)(int, const void *, void *);

/* FULL mode: take the handler over and dump everything. Off by default,
 * because with the game's own handler left in place the faulting thread spins
 * but the others keep running, which is what you want when watching whether a
 * later stage recovers - and because the dump below reads Godzilla Pro's
 * addresses. */
static int getenv_pad(void)
{
    char *p = getenv("PAD_SEGV_REPORT");
    return p && p[0] == '1';
}

/* HEADER mode: report and delegate. On unless explicitly disabled. */
static int segv_header_on(void)
{
    char *p = getenv("PAD_SEGV_HEADER");
    return !(p && p[0] == '0');
}

/* What the game asked for, recorded rather than installed once we hold the
 * signal. sa_handler/sa_sigaction share slot 0 of struct sigaction on ARM
 * Linux; slot 132 is sa_flags, and SA_SIGINFO (4) says which shape it is. */
static void *game_segv_fn;
static int   game_segv_flags;
static int   segv_reports;      /* header prints, capped - see below */

/* The universal half: true on any title, invents nothing. Kept separate from
 * the dump below so that a title this shim has never seen still gets the one
 * thing every crash report needs - where it faulted. */
static void segv_print_header(unsigned long *uc)
{
    char b[200];

    snprintf(b, sizeof b, "[segv] pc=0x%lx lr=0x%lx r0=0x%lx fault=0x%lx\n",
             uc[23], uc[22], uc[8], uc[25]);
    logmsg(b);

    /* NAME THE PC. A pc inside a loaded library is otherwise just a number, and
     * guessing which .so it belongs to from the load order wastes a run. Walk
     * /proc/self/maps and print the mapping that contains it (and the one that
     * contains lr, when lr looks like a code address). Uses raw open/read
     * because this runs from a signal handler. */
    {
        long (*rd)(int, void *, unsigned long) = dlsym(RTLD_NEXT, "read");
        int fd;
        /* real_open is resolved LAZILY, by init(), on the first interposed
         * call. A guest that faults before it has opened anything therefore
         * reaches here with real_open still NULL - and calling it would fault
         * INSIDE the signal handler, killing the process with the report half
         * written. That is not hypothetical: it is what the offline segv test
         * did, and it cost the delegation step below. The game opens files
         * constantly so it never showed up there, which is exactly why an
         * early crash is the one that would have lost its report. */
        if (!real_open) init();
        if (!real_open) {
            logmsg("[segv] (no maps: open not resolved yet)\n");
            rd = 0;
        }
        fd = real_open ? real_open("/proc/self/maps", 0 /*O_RDONLY*/, 0) : -1;
        if (fd >= 0 && rd) {
            static char m[16384];
            long got, off = 0;
            char *line;
            while ((got = rd(fd, m + off, sizeof m - 1 - (unsigned long)off)) > 0) {
                off += got;
                if ((unsigned long)off >= sizeof m - 1) break;
            }
            m[off] = 0;
            for (line = m; *line; ) {
                char *eol = line, *q = line;
                unsigned long lo = 0, hi = 0;
                int ispc, islr;
                while (*eol && *eol != '\n') eol++;
                while ((*q >= '0' && *q <= '9') || (*q >= 'a' && *q <= 'f'))
                    lo = lo * 16 + (unsigned long)(*q <= '9' ? *q - '0' : *q - 'a' + 10), q++;
                if (*q == '-') q++;
                while ((*q >= '0' && *q <= '9') || (*q >= 'a' && *q <= 'f'))
                    hi = hi * 16 + (unsigned long)(*q <= '9' ? *q - '0' : *q - 'a' + 10), q++;
                ispc = uc[23] >= lo && uc[23] < hi;
                islr = uc[22] >= lo && uc[22] < hi;
                if (ispc || islr) {
                    char save = *eol;
                    *eol = 0;
                    /* %.170s: a maps line can be pathological and clipping
                     * one in a crash log is fine - gcc's format-truncation
                     * warning here printed as a wall of "errors" in the app
                     * log on every shim rebuild (tester report, 2026-08-25),
                     * which is the bug this precision fixes. Same story on
                     * every other %.Ns in a log line below. */
                    snprintf(b, sizeof b, "[segv] map %.170s%s\n", line,
                             ispc ? "   <-- PC" : "   <-- LR");
                    logmsg(b);
                    if (ispc) {
                        snprintf(b, sizeof b,
                                 "[segv] pc = mapping + 0x%lx\n", uc[23] - lo);
                        logmsg(b);
                    }
                    *eol = save;
                }
                line = *eol ? eol + 1 : eol;
            }
        }
    }
}

/* ---- item 52: the scan fault guard --------------------------------- *
 * sw_find_table() runs a whole-heap scan whose readability answers are
 * page-cached for speed and can therefore be stale (see addr_readable's
 * note). Rather than trying to out-probe the guest's allocator, the scan
 * runs under this guard: when the SCANNING THREAD faults, the two handlers
 * below land here first and siglongjmp back into sw_find_table, which
 * closes the scan's fd, counts a failed search and moves on. Any other
 * thread's fault, and any fault while no scan runs, falls through to the
 * reporting and delegation below unchanged.
 *
 * The tid check is load-bearing: the jump buffer belongs to the scanning
 * thread's stack, and a longjmp taken on another thread's fault would be a
 * second, far stranger crash. gettid is a raw syscall (ARM EABI 224)
 * because this runs inside a signal handler and because the shim resolves
 * libc lazily. */
static sigjmp_buf sw_scan_env;
static volatile long sw_scan_tid;          /* nonzero = the guard is armed */
static volatile int  scan_guard_busy;      /* one guarded scan at a time */
static volatile unsigned long sw_scan_pc, sw_scan_addr;    /* for the log */
static int sw_scan_fd = -1;   /* the scan's maps fd, closed on an abort */
static int segv_guard_ready;  /* the constructor really took SIGSEGV */

static void scan_guard_check(unsigned long *uc)
{
    if (!sw_scan_tid || syscall(224) != sw_scan_tid) return;
    sw_scan_tid = 0;
    if (uc) { sw_scan_pc = uc[23]; sw_scan_addr = uc[25]; }
    siglongjmp(sw_scan_env, 1);
}

/* HEADER mode's handler: print, then put the fault back where it was going.
 *
 * "Where it was going" is the whole point - this must not change whether a run
 * survives, only whether its death is legible. Two cases:
 *   - the game registered a handler: call it, with its own calling convention,
 *     and let its semantics (including returning, and therefore looping) stand;
 *   - it did not: restore SIG_DFL and return, so the faulting instruction
 *     re-executes and the process dies exactly as it does today, with qemu
 *     printing `uncaught target signal 11` - now preceded by our line.
 *
 * The print is CAPPED. A game handler that returns re-faults immediately and
 * forever; item 23 measured that shape as a hang. Three reports name the fault
 * without turning a hang into a gigabyte of log.
 */
static void segv_header_handler(int sig, void *info, void *ucv)
{
    unsigned long *uc = ucv;

    scan_guard_check(uc);   /* never returns if the guarded scan faulted */

    if (uc && segv_reports < 3) {
        segv_reports++;
        segv_print_header(uc);
        if (segv_reports == 3)
            logmsg("[segv] (further faults will not be reported)\n");
    }

    if (game_segv_fn) {
        char d[80];
        snprintf(d, sizeof d, "[segv] delegating to guest handler %p flags=0x%x\n",
                 game_segv_fn, game_segv_flags);
        logmsg(d);
        if (game_segv_flags & 4)        /* SA_SIGINFO: three-argument form */
            ((void (*)(int, void *, void *))game_segv_fn)(sig, info, ucv);
        else
            ((void (*)(int))game_segv_fn)(sig);
        return;
    }
    logmsg("[segv] no guest handler recorded; falling through to SIG_DFL\n");

    /* Nobody else wants it: die the way we would have died anyway. */
    if (real_sigaction) {
        unsigned char dfl[160];
        int i;
        for (i = 0; i < 160; i++) dfl[i] = 0;   /* sa_handler = SIG_DFL (0) */
        real_sigaction(11, dfl, 0);
    }
}

__attribute__((constructor))
static void segv_install(void)
{
    unsigned char mine[160];
    int i;

    if (!segv_header_on()) return;
    if (!real_sigaction) real_sigaction = dlsym(RTLD_NEXT, "sigaction");
    if (!real_sigaction) return;

    for (i = 0; i < 160; i++) mine[i] = 0;
    *(void **)mine = (void *)segv_header_handler;
    *(int *)(mine + 132) = 4;              /* SA_SIGINFO */
    if (real_sigaction(11, mine, 0) == 0)
        segv_guard_ready = 1;   /* sw_find_table's guard can land */
}

static void segv_handler(int sig, void *info, void *ucv)
{
    unsigned long *uc = ucv;
    char b[240];            /* the 16-register dump is 217 bytes - 200 was
                             * genuinely truncating pc= off the crash log   */
    (void)sig; (void)info;
    scan_guard_check(uc);   /* never returns if the guarded scan faulted */
    if (!uc) { logmsg("[segv] no context\n"); _exit(99); }

    segv_print_header(uc);

    /* The scene loader thread (0x447440) does no work at all unless the gate
     * byte at 0x7e1a10 is set, and the boot step waits on 0x7e1974. The shim
     * shares the guest address space, so both can just be read here. */
    {
        /* GODZILLA PRO 1.15.0 ADDRESSES, and the danger on another title is not
         * a crash - it is a LIE. EHOH printed "loader_gate=171 boot_ready=93"
         * off unrelated data of its own, in a crash report, as fact. A report
         * that invents findings is worse than one that says less, so these are
         * printed only for the title they came from. */
        unsigned char *gate  = (unsigned char *)0x7e1a10;
        unsigned char *ready = (unsigned char *)0x7e1974;
        unsigned char *run   = (unsigned char *)0x794af5;
        if (a_sw_struct())
            snprintf(b, sizeof b,
                     "[segv] loader_gate[0x7e1a10]=%d boot_ready[0x7e1974]=%d "
                     "thread_run[0x794af5]=%d scene_opens=%d\n",
                     *gate, *ready, *run, scene_opens);
        else
            snprintf(b, sizeof b,
                     "[segv] scene_opens=%d (loader-gate addresses are Godzilla"
                     " Pro's; not reported for this title)\n", scene_opens);
        logmsg(b);
        snprintf(b, sizeof b,
                 "[segv] filebuf::xsgetn=%d (small=%d) filebuf::underflow=%d "
                 "__basic_file::xsgetn=%d\n",
                 fb_xsgetn_calls, fb_xsgetn_small, fb_underflow_calls,
                 bf_xsgetn_calls);
        logmsg(b);
        {
            int i;
            for (i = 0; i < SBMAX; i++)
                if (sbs[i].rdbuf) sb_report(&sbs[i]);
        }
    }

    /* The boot step at 0x4f0720 runs the whole game init only if dispatch(93)
     * is not vetoed. Statically there is one listener for 93 and it always
     * returns 1, so whatever returns 0 is registered at run time. The event
     * table at 0x7e4d48 is indexed by event id and each entry is a linked list
     * of {handler, priority, next}, so it can just be walked here. */
    {
        /* Also Godzilla Pro 1.15.0's. Walking it on another title produced
         * "[segv] event 93 has NO handlers", which is not a finding about that
         * title - it is this shim reading someone else's memory and stating the
         * result. Same rule as the block above. */
        unsigned long *tbl = (unsigned long *)0x7e4d48;
        int ev;
        for (ev = 93; a_sw_struct() && ev <= 94; ev++) {
            unsigned long node = tbl[ev];
            int k = 0;
            while (node && k < 12) {
                snprintf(b, sizeof b, "[segv] event %d handler[%d] = 0x%lx prio=%d\n",
                         ev, k, *(unsigned long *)node,
                         *(unsigned char *)(node + 4));
                logmsg(b);
                node = *(unsigned long *)(node + 8);
                k++;
            }
            if (!k) {
                snprintf(b, sizeof b, "[segv] event %d has NO handlers\n", ev);
                logmsg(b);
            }
        }
    }

    /* The wall is in the audio mixer. The mixer walks a static array of eight
     * 64-byte voice slots at 0x7b90c0 (= audio state 0x7b8990 + 0x730), and
     * pulls PCM from the producer/consumer queue at voice+0x38. Frame layout,
     * checked against the reported stack indices:
     *
     *   0x30ed20  push {9 regs}; sub sp,#76   -> its sp = S0 - 112
     *   0x4db74c  push {9 regs}; sub sp,#20   -> entered with sp = S0
     *   pthread_mutex_lock pushes 3 more      -> handler sp = S0 - 68
     *
     * so the voice pointer 0x30ed20 kept at [sp,#44] is stack word 28, and its
     * saved lr is word 44 - which is exactly where 0x2a24ac was reported. */
    {
        unsigned long sp = uc[21];
        unsigned long *w = (unsigned long *)sp;
        unsigned long obj = w[28];
        unsigned long base = 0x7b90c0;
        int n;

        snprintf(b, sizeof b,
                 "[audio] mixer voice = 0x%lx  index %ld  queue(r4)=0x%lx "
                 "bytes_wanted(fp)=%lu\n",
                 obj, (long)((obj - base) / 64), uc[12], uc[19]);
        logmsg(b);

        /* Don't infer the caller from the stack scan - print the registers and
         * the raw frame. r5 holds the out descriptor, which each mixer clone
         * places at a different offset in its own frame, so r5 identifies the
         * clone exactly. */
        snprintf(b, sizeof b,
                 "[audio] r0=%08lx r1=%08lx r2=%08lx r3=%08lx r4=%08lx r5=%08lx\n"
                 "[audio] r6=%08lx r7=%08lx r8=%08lx r9=%08lx sl=%08lx fp=%08lx\n"
                 "[audio] ip=%08lx sp=%08lx lr=%08lx pc=%08lx\n",
                 uc[8], uc[9], uc[10], uc[11], uc[12], uc[13],
                 uc[14], uc[15], uc[16], uc[17], uc[18], uc[19],
                 uc[20], uc[21], uc[22], uc[23]);
        logmsg(b);
        snprintf(b, sizeof b, "[audio] out-desc r5 is at caller_sp + %ld\n",
                 (long)(uc[13] - (sp + 68)));
        logmsg(b);
        {
            int i;
            for (i = 20; i < 52; i += 4) {
                snprintf(b, sizeof b,
                         "[audio] stack[%2d..%2d] = %08lx %08lx %08lx %08lx\n",
                         i, i + 3, w[i], w[i + 1], w[i + 2], w[i + 3]);
                logmsg(b);
            }
        }

        for (n = 0; n < 8; n++) {
            unsigned char *v = (unsigned char *)(base + n * 64);
            unsigned long *vw = (unsigned long *)v;
            snprintf(b, sizeof b,
                     "[audio] voice[%d] stream=0x%08lx mixA=0x%08lx mixB=0x%08lx "
                     "pos=%lu queue=0x%08lx en=%d mask=0x%02x vol=%d/%d ch=%d\n",
                     n, vw[0], vw[1], vw[2], vw[3], vw[14],
                     v[0x35], v[0x34],
                     *(short *)(v + 0x30), *(short *)(v + 0x32), v[0x1a]);
            logmsg(b);
        }

        /* voice+0 is a stream/format descriptor: +0x10 is the total length the
         * mixer compares the cursor against. Print it for whichever voice the
         * mixer was on. */
        if (obj >= base && obj < base + 512) {
            unsigned long st = *(unsigned long *)obj;
            snprintf(b, sizeof b, "[audio] faulting voice stream desc = 0x%lx\n", st);
            logmsg(b);
            if (st > 0x10000 && st < 0xb0000000) {
                unsigned long *s = (unsigned long *)st;
                snprintf(b, sizeof b,
                         "[audio]   +00=0x%08lx +04=0x%08lx +08=0x%08lx +0c=0x%08lx\n"
                         "[audio]   +10=0x%08lx(len) +14=0x%08lx +18=0x%08lx +1c=0x%08lx\n",
                         s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7]);
                logmsg(b);
            }
        }

        /* 0x7b8990+0x100 is the object the teardown path at 0x2a2044 hands the
         * queue back to, i.e. the queue pool/owner. */
        {
            unsigned long pool = *(unsigned long *)(0x7b8990 + 0x100);
            snprintf(b, sizeof b, "[audio] queue pool [0x7b8a90] = 0x%lx\n", pool);
            logmsg(b);
            /* 0x458e98 returns NULL when the free ring is empty, which it
             * tests as [pool+0x84] == [pool+0x74] before it ever gets as far
             * as open()ing the sound file. Print the ring so the two NULL
             * paths can be told apart. */
            if (pool > 0x10000 && pool < 0xb0000000) {
                unsigned long *p = (unsigned long *)pool;
                snprintf(b, sizeof b,
                         "[audio] pool head[+74]=0x%08lx limit[+7c]=0x%08lx "
                         "end[+84]=0x%08lx  free_ring_empty=%d\n",
                         p[0x74 / 4], p[0x7c / 4], p[0x84 / 4],
                         p[0x84 / 4] == p[0x74 / 4]);
                logmsg(b);
                snprintf(b, sizeof b,
                         "[audio] pool +60=%08lx +64=%08lx +68=%08lx +6c=%08lx "
                         "+70=%08lx +78=%08lx +80=%08lx +bc=%08lx\n",
                         p[0x60 / 4], p[0x64 / 4], p[0x68 / 4], p[0x6c / 4],
                         p[0x70 / 4], p[0x78 / 4], p[0x80 / 4], p[0xbc / 4]);
                logmsg(b);

                /* The streaming worker (thread body 0x459184) does, before
                 * anything else:
                 *     ldrb r3,[0x7acb54]; cmp r3,#0; bne .-4
                 * The byte is loaded ONCE and the branch targets the compare,
                 * so a non-zero read spins that thread forever. If the worker
                 * never runs, queues are never recycled and the pool of 16
                 * empties permanently. */
                {
                    snprintf(b, sizeof b,
                             "[audio] worker spin gate = %d "
                             "(non-zero at thread start = worker wedged; "
                             "-1 = this title has no gate at PAD_AUDIO_GATE)\n",
                             gate_val());
                    logmsg(b);
                }

                /* Three lists hang off the pool: +0x94 the worker's working
                 * list, +0x9c the in-use list 0x458e98 pushes onto, +0xa4 the
                 * released list 0x458674 pushes onto. Count them. */
                {
                    int off[3]; int k;
                    off[0] = 0x94; off[1] = 0x9c; off[2] = 0xa4;
                    for (k = 0; k < 3; k++) {
                        unsigned long head = pool + off[k];
                        unsigned long node = *(unsigned long *)head;
                        int cnt = 0;
                        while (node && node != head && cnt < 64) {
                            unsigned long q = *(unsigned long *)(node + 8);
                            if (cnt < 4 && q > 0x10000 && q < 0xb0000000) {
                                unsigned long *qq = (unsigned long *)q;
                                snprintf(b, sizeof b,
                                         "[audio]   list+%02x[%d] queue=0x%lx fd=%ld "
                                         "total=%lu avail=%ld pops=%lu\n",
                                         off[k], cnt, q, (long)qq[2], qq[4],
                                         (long)qq[0x30 / 4], qq[0x44 / 4]);
                                logmsg(b);
                            }
                            node = *(unsigned long *)node;
                            cnt++;
                        }
                        snprintf(b, sizeof b, "[audio] pool list +%02x : %d entries\n",
                                 off[k], cnt);
                        logmsg(b);
                    }
                }
            }
        }
    }

    /* No frame pointers, so approximate a backtrace by scanning the stack for
     * words that land inside the game's .text. Noisy but enough to see which
     * subsystem is on the call chain. */
    {
        unsigned long sp = uc[21];
        unsigned long *w = (unsigned long *)sp;
        int i, shown = 0;
        for (i = 0; i < 512 && shown < 24; i++) {
            unsigned long v = w[i];
            if (v > 0x16a00 && v < 0x5d3168 && (v & 3) == 0) {
                snprintf(b, sizeof b, "[segv]   stack[%3d] = 0x%lx\n", i, v);
                logmsg(b);
                shown++;
            }
        }
    }
    _exit(99);
}

int shim_sigaction(int sig, const void *act, void *old) __asm__("sigaction");
int shim_sigaction(int sig, const void *act, void *old)
{
    if (!real_sigaction) real_sigaction = dlsym(RTLD_NEXT, "sigaction");
    if (sig == 11 && getenv_pad()) {   /* SIGSEGV */
        unsigned char mine[160];
        int i;
        for (i = 0; i < 160; i++) mine[i] = 0;
        *(void **)mine = (void *)segv_handler;
        *(int *)(mine + 132) = 4;          /* SA_SIGINFO */
        return real_sigaction(sig, mine, old);
    }
    /* HEADER mode holds SIGSEGV, so the game's own registration is RECORDED
     * rather than installed - otherwise it would overwrite our handler and we
     * would be back to reporting nothing. It still runs, from ours; see
     * segv_header_handler. Reporting an old handler the game never installed
     * would be a lie, so `old` gets what we are holding on its behalf. */
    if (sig == 11 && act && segv_header_on()) {
        if (old) {
            unsigned char *o = old;
            int i;
            for (i = 0; i < 160; i++) o[i] = 0;
            *(void **)o = game_segv_fn;
            *(int *)(o + 132) = game_segv_flags;
        }
        game_segv_fn    = *(void **)act;
        game_segv_flags = *(const int *)((const unsigned char *)act + 132);
        return 0;
    }
    return real_sigaction(sig, act, old);
}

void *shim_signal(int sig, void *h) __asm__("signal");
void *shim_signal(int sig, void *h)
{
    static void *(*real_signal)(int, void *);
    if (!real_signal) real_signal = dlsym(RTLD_NEXT, "signal");
    if (sig == 11) {
        /* NOTE, found while building item 41's reporter: this path used to
         * DROP h on the floor - it called sigaction(11, NULL, NULL), which
         * installs nothing, so a game that registers its SIGSEGV handler via
         * signal() rather than sigaction() ended up with no handler at all.
         * That is one way a fault becomes qemu's `uncaught target signal 11`
         * with nothing logged. Record it now so header mode can delegate to
         * it, exactly as the sigaction path does. */
        void *prev = game_segv_fn;
        if (h && segv_header_on()) { game_segv_fn = h; game_segv_flags = 0; }
        else                       { shim_sigaction(11, 0, 0); }
        return prev;
    }
    return real_signal(sig, h);
}

extern int usleep(unsigned);

/* GStreamer element creation returns NULL for anything the platform cannot
 * provide, and a missing hardware decoder is the likeliest source of a null
 * object in this container. */
void *shim_gst_element_factory_make(const char *fac, const char *name) __asm__("gst_element_factory_make");
void *shim_gst_element_factory_make(const char *fac, const char *name)
{
    static void *(*real_make)(const char *, const char *);
    void *r;
    char b[200];
    if (!real_make) real_make = dlsym(RTLD_NEXT, "gst_element_factory_make");
    r = real_make(fac, name);
    /* BUDGETED and saturating: once the game reaches attract mode it rebuilds
     * the video pipeline about 200 times a SECOND (600 element creations/s)
     * because vpudec can never succeed, so this line alone was the log's
     * dominant cost. The running total is still the health signal - see task
     * 1a - so keep counting it, just stop writing it out. */
    {
        static unsigned long n;
        static int keep = -1;
        if (keep == -1) { char *p = getenv("PAD_GST_LOG"); keep = p && p[0] == '1'; }
        if (keep || n < 64) {
            if (n < 64) n++;
            snprintf(b, sizeof b, "[gst] factory_make(\"%s\",\"%s\") -> %s\n",
                     fac ? fac : "?", name ? name : "?", r ? "ok" : "NULL");
            logmsg(b);
        } else if (n == 64) {
            n++;
            logmsg("[gst] further factory_make calls not logged; use "
                   "PAD_GST_LOG=1 to keep them\n");
        }
    }
    /* THROTTLE THE RETRY. The game has no back-off: the pipeline fails, it is
     * torn down and immediately rebuilt, ~200 times a second forever. That
     * burns CPU and leaks about 6.5 MB/s of RSS - the guest went from 1.0 GB to
     * 2.7 GB and kept climbing - which is the real answer to "why does it use so
     * much memory". Sleeping in the decoder's own factory call caps the retry
     * rate without touching anything else. It does NOT fix video (see task 3);
     * it stops a failure that cannot succeed from consuming the machine.
     * PAD_GST_US=0 restores the free-run. */
    if (fac && fac[0] == 'v' && fac[1] == 'p' && fac[2] == 'u') {
        static int us = -1;
        if (us == -1) {
            char *p = getenv("PAD_GST_US");
            us = 100000;                    /* 10 rebuilds a second, not 200 */
            if (p) { us = 0; while (*p >= '0' && *p <= '9') us = us * 10 + (*p++ - '0'); }
        }
        if (us > 0) usleep((unsigned)us);
    }
    return r;
}

/* ---------------- virtual i2c NVRAM ----------------------------------- *
 * The board's persistent storage hangs off /dev/i2c-1. Modelled here as a
 * set of plain EEPROM-style pages: a write message carries an address then
 * data, a read message returns bytes from the current pointer.
 */
#define I2C_SLAVE       0x0703
#define I2C_SLAVE_FORCE 0x0706
#define I2C_FUNCS       0x0705
#define I2C_RDWR        0x0707
#define I2C_M_RD        0x0001

#define NSLOT     8
#define SLOTSIZE  65536
static unsigned char store[NSLOT][SLOTSIZE];
static int slot_addr[NSLOT];
static int slot_used;
static int cur_slot[MAXFD];
static unsigned int cur_ptr[NSLOT];
/* ITEM 17: env-tunable. The fixed 120 was spent inside the first second of
 * boot on every run this rig ever made, so the RUNTIME i2c traffic - the 250
 * transfers per 924 ms maintenance cycle that hold the node bus thread for
 * 681 ms - had never once been seen. PAD_I2C_LOG=<n> sets it. */
static int i2c_log_budget = 120;
static void i2c_log_init(void)
{
    static int done;
    char *p;
    if (done) return;
    done = 1;
    p = getenv("PAD_I2C_LOG");
    if (p && *p) {
        int v = 0;
        while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        i2c_log_budget = v;
    }
}

struct i2c_msg { unsigned short addr, flags, len; unsigned char *buf; };
struct i2c_rdwr { struct i2c_msg *msgs; unsigned int nmsgs; };

/* A termios image for the node bus port. c_cflag starts at B115200|CS8|CREAD|
 * CLOCAL so a read-back before any TCSETS still looks like a working port. */
static unsigned char tio[64] = {
    0,0,0,0,   0,0,0,0,   0xb2,0x18,0,0,   0,0,0,0
};
static int tio_seen;
static int tio_log = 12;

/* struct serial_struct, 60 bytes on 32-bit: type=1 at +0, xmit_fifo_size=32
 * at +20, baud_base=4000000 at +28. Everything else starts zeroed. */
static unsigned char ser[96] = {
    1,0,0,0,   0,0,0,0,   0,0,0,0,   0,0,0,0,
    0,0,0,0,   32,0,0,0,  0,0,0,0,   0x00,0x09,0x3d,0x00
};
static int ser_seen;

/* ITEM 17: the cabinet SPI transfer counter (PAD_CAB_PROBE=1). File scope so
 * the node bus read path can stamp [nbsilent] lines with it - this counter is
 * the one timebase BOTH logs can see (ringwatch reads it out of NodeRec.cur,
 * the shim prints it), so a cabinet-poll gap and a silent-read train can be
 * joined EXACTLY, with no cross-clock alignment step at all. */
static unsigned cab_ctr;

static int slot_for(int addr)
{
    int i;
    for (i = 0; i < slot_used; i++) if (slot_addr[i] == addr) return i;
    if (slot_used < NSLOT) { slot_addr[slot_used] = addr; return slot_used++; }
    return 0;
}

static void hex(char *out, const unsigned char *p, int n)
{
    static const char d[] = "0123456789abcdef";
    int i;
    if (n > 16) n = 16;
    for (i = 0; i < n; i++) { *out++ = d[p[i] >> 4]; *out++ = d[p[i] & 15]; }
    *out = 0;
}

/* hex() caps at 16 bytes, and EVERY node bus frame longer than that has been
 * silently cut off in every log this rig has ever written. The census entries
 * "86 <64 bytes>" and "41 <12 bytes>" were read off truncated lines and are
 * wrong about the payload. Anything that logs a whole frame uses this instead.
 *
 * AND THEN THE SAME TRAP CAME BACK AT THE NEW LIMIT. This capped at 64, so the
 * LED frames on nodes 7/12/14 - whose own length byte says up to 118 - were
 * still being cut off, and every one of them logged as exactly 64 bytes. That
 * produced a confident and wrong conclusion: "everything caps at 64 bytes and a
 * long update is chunked" is a description of THIS FUNCTION, not of the
 * protocol. It also made the strip-board mask/data split impossible to find,
 * because the data was simply missing.
 *
 * The test that catches it costs nothing and is worth keeping in mind for any
 * framed protocol: a frame's own length field must agree with how many bytes
 * were logged. Here `len == plen + 3`, and 3573 frames disagreed - every single
 * one of them observed at exactly the cap.
 *
 * 255 is past the 118 seen and past what a 0x100-byte length byte can express.
 * Callers must give it HEXBUF bytes. */
#define HEXMAX 255
#define HEXBUF (HEXMAX * 2 + 1)
static void hex64(char *out, const unsigned char *p, int n)
{
    static const char d[] = "0123456789abcdef";
    int i;
    if (n > HEXMAX) n = HEXMAX;
    for (i = 0; i < n; i++) { *out++ = d[p[i] >> 4]; *out++ = d[p[i] & 15]; }
    *out = 0;
}

/* The NVRAM is the machine's identity, settings, audits and scores, so it has
 * to survive a restart the way the real board does. */
#define NV_PATH "/data/nvram.bin"

/* ...AND IT IS ONE MACHINE'S, NOT ONE DISK'S. A real Spike 2 EEPROM sits on the
 * CPU board of a cabinet that runs ONE game; this rig has one rootfs that runs
 * every title, so a single /data/nvram.bin meant godzilla, TMNT and
 * stranger_things all read and wrote the SAME 64 KB - each interpreting the
 * other's bytes at its own adjustment offsets. The game's own file-based stores
 * under /data/nv/<title>/ were already per-title; this one was the outlier.
 *
 * The split is still right for the reason above. But the ATTRIBUTION that was
 * written here on 2026-08-17 was WRONG, and it is corrected rather than deleted
 * because it was believed long enough to aim a day's work:
 *
 *   CLAIMED: two godzilla runs, then stranger_things put "THIS MACHINE WILL NOT
 *   OPERATE IN THIS COUNTRY" on the glass, so the COUNTRY CODE adjustment was
 *   read out of bytes another title wrote.
 *
 *   MEASURED, 2026-08-18, by actually comparing the two files: /data/nvram.bin
 *   is ITSELF a stranger_things EEPROM - it contains "SPI-STR-19358604" at
 *   0x100 and the string "stranger_things_le" at 0x150 - and ST's per-title
 *   copy differs from it in SIXTEEN BYTES out of 65536 (a serial and two
 *   timestamps, at 0x10d, 0x13f..0x14d and 0x18c). There is no godzilla content
 *   in it to misread. Cross-title contamination is NOT what causes the refusal,
 *   and going per-title neither caused nor could have fixed it.
 *
 *   What the EEPROM actually shows: an ident block and a date, and an
 *   adjustment area that is ALL ZEROS. The machine is unconfigured, not
 *   mis-configured.
 *
 * A missing per-title file is SEEDED from the shared one rather than started
 * blank, because that file holds real settings and real high scores and this
 * change must not be the thing that loses them. PAD_NV_BLANK=1 skips the seed
 * for a deliberately fresh machine - but note that stranger_things does NOT
 * survive a fresh one: on both an all-zero and an all-0xFF chip it aborts in
 * cereal ("unregistered polymorphic type (Bitmap)") before the node bus starts,
 * which is its own defect and not this function's. */
static const char *nv_path(void)
{
    static char p[160];
    const char *g, *c;
    int safe = 1;
    if (p[0]) return p;
    g = getenv("PAD_GAME");
    /* No string.h here - this object is built -nostdlib. A title name with a
     * slash in it would escape /data, so check by hand. */
    for (c = g; c && *c; c++)
        if (*c == '/') { safe = 0; break; }
    if (g && *g && safe)
        snprintf(p, sizeof p, "/data/nvram-%s.bin", g);
    else
        snprintf(p, sizeof p, "%s", NV_PATH);
    return p;
}
static int nv_loaded;

/* ══ PAD_NV_POKE ═════════════════════════════════════════════════════════
 *
 * PAD_NV_POKE=<lo>[-<hi>]:<val>[,...]   (all hex, e.g. "40-ff:01,200:1e")
 *
 * Overwrite EEPROM bytes after load, before the game sees them. This exists to
 * find ONE number: the offset stranger_things keeps its COUNTRY CODE at. The
 * static route is exhausted - the country table (0x731aac, 30 records, stride
 * 36, +24 name msgid, +32 index 0..29) is reached through the table registry at
 * 0x719b54, whose base 0x719b48 has 674 references and is therefore no
 * shortcut. But the shim OWNS the EEPROM and the screen oracle can now read the
 * glass, so the offset can simply be searched for: fill a range, see whether
 * the refusal screen changes, bisect.
 *
 * SAVES ARE DISABLED WHENEVER THIS IS SET, and that is not a detail. The file
 * being probed holds real settings and real high scores, and nv_save() runs on
 * every EEPROM write the game makes - so without this, one probe run would
 * write its own poked bytes back over the machine's actual NVRAM and the
 * evidence and the data would be destroyed together. A probe must not be able
 * to damage the thing it is measuring. */
static int nv_poke_on(void)
{
    const char *p = getenv("PAD_NV_POKE");
    return p && *p;
}

/* Hex parse in place; *nd is the digit count, so "no digits" is distinguishable
 * from a legitimate zero. No string.h here - this object is built -nostdlib. */
static unsigned nv_hex(const char **s, int *nd)
{
    unsigned v = 0;
    *nd = 0;
    for (;;) {
        char c = **s;
        unsigned d;
        if (c >= '0' && c <= '9') d = (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') d = (unsigned)(c - 'a') + 10u;
        else if (c >= 'A' && c <= 'F') d = (unsigned)(c - 'A') + 10u;
        else break;
        v = v * 16u + d;
        (*s)++;
        (*nd)++;
    }
    return v;
}

static void nv_poke_apply(void)
{
    const char *p = getenv("PAD_NV_POKE");
    char m[240];
    unsigned total = 0;
    int nd;
    if (!p || !*p) return;
    while (*p) {
        unsigned lo, hi, val, i;
        lo = nv_hex(&p, &nd);
        if (!nd) break;
        hi = lo;
        if (*p == '-') { p++; hi = nv_hex(&p, &nd); if (!nd) break; }
        if (*p != ':') break;
        p++;
        val = nv_hex(&p, &nd);
        if (!nd) break;
        if (hi < lo || hi >= SLOTSIZE) {
            snprintf(m, sizeof m, "[i2c] POKE 0x%04x..0x%04x REFUSED: out of "
                     "range (EEPROM is 0x%x bytes)\n", lo, hi, SLOTSIZE);
            logmsg(m);
            break;
        }
        for (i = lo; i <= hi; i++) store[0][i] = (unsigned char)val;
        total += hi - lo + 1u;
        snprintf(m, sizeof m, "[i2c] POKE 0x%04x..0x%04x = 0x%02x\n",
                 lo, hi, val & 0xffu);
        logmsg(m);
        if (*p == ',') p++; else break;
    }
    snprintf(m, sizeof m, "[i2c] %u EEPROM bytes poked; SAVES ARE DISABLED for "
             "this run so the real NVRAM file cannot be damaged by a probe\n",
             total);
    logmsg(m);
}

static long (*real_read)(int, void *, unsigned long);
static long (*real_write)(int, const void *, unsigned long);
static int (*real_close)(int);

static void io_init(void)
{
    if (real_close) return;
    real_read  = dlsym(RTLD_NEXT, "read");
    real_write = dlsym(RTLD_NEXT, "write");
    real_close = dlsym(RTLD_NEXT, "close");
}

static void nv_load(void)
{
    int fd;
    unsigned long got = 0;
    long r;
    char m[220];
    const char *path = nv_path();
    int seeded = 0;
    if (nv_loaded) return;
    nv_loaded = 1;
    init(); io_init();
    fd = real_open(path, 0 /* O_RDONLY */, 0);
    if (fd < 0 && !getenv("PAD_NV_BLANK")) {
        /* First run of this title since the EEPROM went per-title: inherit the
         * shared file so nothing that was already saved is lost. */
        fd = real_open(NV_PATH, 0, 0);
        seeded = fd >= 0;
    }
    if (fd < 0) {
        snprintf(m, sizeof m, "[i2c] no saved NVRAM at %s, starting blank\n", path);
        logmsg(m);
        nv_poke_apply();     /* a poke must land on a blank chip too */
        return;
    }
    while (got < SLOTSIZE && (r = real_read(fd, store[0] + got, SLOTSIZE - got)) > 0)
        got += (unsigned long)r;
    real_close(fd);
    snprintf(m, sizeof m, "[i2c] loaded saved NVRAM from %.130s%s\n",
             seeded ? NV_PATH : path,
             seeded ? " (seeding this title's own EEPROM; it is per-title now)"
                    : "");
    logmsg(m);
    nv_poke_apply();
}

static void nv_save(void)
{
    int fd;
    /* A PROBE MUST NOT DAMAGE WHAT IT MEASURES. nv_save() runs on every EEPROM
     * write the game makes, so without this one line a PAD_NV_POKE run would
     * write its own poked bytes back over the machine's real settings and high
     * scores - losing the data and the experiment in the same stroke. */
    if (nv_poke_on()) return;
    io_init();
    fd = real_open(nv_path(), 0x241 /* O_WRONLY|O_CREAT|O_TRUNC */, 0644);
    if (fd < 0) return;
    real_write(fd, store[0], SLOTSIZE);
    real_close(fd);
}

/* ITEM 17, THE ROOT CAUSE FIX. Two i2c MCUs, slaves 0x0a and 0x2a, present
 * 0x0111 in register 0x24 after a reset, or the game holds the NODE BUS
 * THREAD hostage forever.
 *
 * The chain, measured end to end (runs 11-18):
 *   - The cabinet switch word is forwarded to NodeRec.cur only when the bus
 *     service thread's sweep reaches node 0, and that thread was blind for
 *     681 ms of every 924 ms - the 39% press loss David reported as item 17.
 *   - 163 of 163 blind windows were bracketed by the same broadcast group:
 *     `0a 0a 07 01 01 08 01 01` ... 681 ms ... `0b 01 06` (PAD_NB_TRACE=2).
 *   - 100% of the run's steady-state /dev/i2c-1 traffic sat INSIDE those
 *     windows: exactly 250 poll-pairs per window of register 0x24 from
 *     slaves 0x0a and 0x2a (PAD_OPEN_LOG + PAD_I2C_LOG).
 *   - The game side is 0x1fa9c8: pulse the reset lines via 0x5a9eac (the
 *     07/08 broadcasts ride along), then up to 250 tries of
 *     { usleep(1000); read reg 0x24 from both } until BOTH have read
 *     0x0111 once (r5 = #250 and r7 = #0x111 are literals in the loop).
 *     Success runs once: usleep(750000), then 0x1fa8c0 programs a register
 *     table into both devices - A TABLE THAT INCLUDES reg 0x24 itself
 *     (0x0020 into 0x0a, 0x0022 into 0x2a: the RUN-state value).
 *     Exhaustion returns plain, and a supervisor re-runs the whole init
 *     ~every 924 ms until it succeeds - that retry loop IS the deafness.
 *   - The periodic health check at 0x1fb38c re-reads reg 0x24 and treats
 *     == 0x0111 as "the device reset itself": full re-init. Healthy is the
 *     CONFIG value persisting. So 0x0111 must appear after a reset and
 *     must NOT survive the config write.
 *
 * Runs 15-18 each killed one wrong version of this model, and the wrong
 * versions are worth recording because they LOOK right:
 *   - sticky 0x0111 (a write-transform re-arming it on any write covering
 *     0x24) turned the health check into a 1 Hz re-init loop - the 681 ms
 *     exhaustion hole became an 834 ms success hole (run 16);
 *   - read-clear consumed the seed once and nothing ever re-armed it, so
 *     every health-check-triggered re-init exhausted its 250 tries again
 *     (runs 17/18).
 *
 * The model that matches the device: power-on state 0x0111 (the seed
 * below); ALL writes stick verbatim (the config value is what the health
 * check wants to see); and the `08 01 01` bus-reset broadcast - which this
 * shim can see on the tty - re-arms 0x0111, because that broadcast rides
 * the same reset the waiter polls the aftermath of. PAD_I2C_READY=0
 * restores the blank store. */
static void i2c_ready_arm(void)
{
    static int on = -1;
    int s;
    if (on == -1) {
        char *p = getenv("PAD_I2C_READY");
        on = !(p && *p == '0');
    }
    if (!on) return;
    for (s = 0; s < 2; s++) {
        int slot = slot_for(s ? 0x2a : 0x0a);
        store[slot][0x24] = 0x01;      /* reg 0x24 reads back 0x0111, the  */
        store[slot][0x25] = 0x11;      /* value 0x1fa9c8 polls 250x for    */
    }
}

static void i2c_seed_ready(void)
{
    static int done;
    if (done) return;
    done = 1;
    i2c_ready_arm();
}

static void do_msg(int slot, struct i2c_msg *m)
{
    char line[256], h[40];
    unsigned int p = cur_ptr[slot];
    i2c_log_init();
    i2c_seed_ready();
    if (m->flags & I2C_M_RD) {
        unsigned int i;
        for (i = 0; i < m->len; i++) m->buf[i] = store[slot][(p + i) % SLOTSIZE];
        cur_ptr[slot] = (p + m->len) % SLOTSIZE;
        if (i2c_log_budget-- > 0) {
            hex(h, m->buf, m->len);
            snprintf(line, sizeof line, "[i2c] t=%lu addr=0x%02x READ  @0x%04x len=%u %s\n",
                     pad_ms(), m->addr, p, m->len, h);
            logmsg(line);
        }
    } else {
        unsigned int i, off = 0;
        if (m->len >= 2) { p = ((unsigned)m->buf[0] << 8) | m->buf[1]; off = 2; }
        else if (m->len == 1) { p = m->buf[0]; off = 1; }
        for (i = off; i < m->len; i++) store[slot][(p + i - off) % SLOTSIZE] = m->buf[i];
        cur_ptr[slot] = (p + (m->len - off)) % SLOTSIZE;
        if (slot == 0 && m->len > off) nv_save();
        if (i2c_log_budget-- > 0) {
            hex(h, m->buf, m->len);
            snprintf(line, sizeof line, "[i2c] t=%lu addr=0x%02x WRITE @0x%04x len=%u %s\n",
                     pad_ms(), m->addr, p, m->len, h);
            logmsg(line);
        }
    }
}

/* Defined with the rest of the switch model, forward-declared because the
 * CABINET switches do not come over the node bus at all - they arrive as the
 * RX half of an SPI transfer, and that is handled here in ioctl(). */
static int sw_scan_bytes(unsigned nid, unsigned char out[8]);
static int sw_scan_enabled(void);
/* "This title has no findable switch table, and waiting will not help" - ONE
 * definition, used by the cabinet at-rest word here and by the node-bus
 * discovery fallback in nb_nodes_init(). Both are item 52 fallbacks and both
 * must agree about when to give up, or one fires while the other waits. */
static int sw_table_hopeless(void);
static void sw_prime(unsigned nid, const unsigned char bits[8]);
static unsigned long pad_ms(void);
/* pad_ms()'s CLOCK_MONOTONIC origin, at file scope rather than a static inside
 * it so the switch block can publish it. A host-side script that knows this
 * origin can compute the same millisecond every `[sw]` line is stamped with,
 * off its own CLOCK_MONOTONIC, with no log to tail - see guest_t0_ms in
 * padsw.h, and swreplay.py, which schedules a whole session against it. */
static unsigned long pad_ms_base;
static void sw_tap(void);
static void sw_changes(void);
static void sw_pend_trace(void);
static unsigned sw_shm_gen(void);
static void sw_shm_edges(void);
static void audio_maybe_dump(void);
static void voice_trace(void);
extern int usleep(unsigned);

/* The keyboard/switch shared block, and the one-shot tap that rides on it.
 *
 * MUST MATCH struct padsw_shm IN padsw.h FIELD FOR FIELD. This file is built
 * -nostdlib with its own minimal declarations and does not include that header,
 * so the two are kept in step by hand: a field added there has to be added here
 * as well. Both are declared HERE rather than down with the rest of the switch
 * code because the SPI ioctl, which is where a tap is served, is earlier in this
 * file than that section. */
struct padsw_shm {
    unsigned magic; unsigned gen; unsigned char held[256];
    unsigned tap_gen; unsigned tap_id; unsigned tap_reads;
    unsigned scr_gen; unsigned char scr_held[256];
    unsigned mrg_gen; unsigned char mrg[256];
    unsigned kbd_src; unsigned scr_src; unsigned guest_t0_ms;
    unsigned spin_gen; unsigned char spin[256];
};
#define PADSW_MAGIC 0x53444150u

/* NOT const: mrg[]/mrg_gen are written from here. Everything else in the block
 * is read-only to the guest, and stays that way - see padsw.h for which of the
 * three regions each writer owns. */
static volatile struct padsw_shm *sw_shm;

/* A tap in flight. `pad_tap_id` is consulted by sw_scan_bytes() exactly as if
 * the switch were held; `tap_left` counts down the transfers it still has to
 * appear in. padsw.h says why the unit is transfers and not milliseconds. */
static int pad_tap_id = -1;
static unsigned tap_left;

/* Microseconds to hold each faked SPI transfer; see the long comment at the
 * ioctl site. 640 us is the real machine's 8 bytes at 100 kHz. PAD_SPI_US=0
 * restores the free-run. */
static int spi_pace_us(void)
{
    static int us = -1;
    if (us == -1) {
        char *p = getenv("PAD_SPI_US");
        us = 640;
        if (p) { us = 0; while (*p >= '0' && *p <= '9') us = us * 10 + (*p++ - '0'); }
    }
    return us;
}

/* Microseconds per byte for a faked i2c transfer. 90 us is roughly a byte plus
 * its ack at 100 kHz. PAD_I2C_US=0 restores the free-run. */
static int i2c_pace_us(void)
{
    static int us = -1;
    if (us == -1) {
        char *p = getenv("PAD_I2C_US");
        us = 90;
        if (p) { us = 0; while (*p >= '0' && *p <= '9') us = us * 10 + (*p++ - '0'); }
    }
    return us;
}
/* Bumped whenever the held-switch set changes, so the SPI path can cache. */
static unsigned sw_gen;

int shim_ioctl(int fd, unsigned long req, ...) __asm__("ioctl");
int shim_ioctl(int fd, unsigned long req, ...)
{
    va_list ap; void *arg; char buf[160];
    static int n;
    init();
    va_start(ap, req); arg = va_arg(ap, void *); va_end(ap);
    if (fd < 0 || fd >= MAXFD || !faked[fd])
        return real_ioctl(fd, req, arg);

    if (faked[fd] == 'I') {
        if (req == I2C_SLAVE || req == I2C_SLAVE_FORCE) {
            int addr = (int)(long)arg;
            cur_slot[fd] = slot_for(addr);
            if (i2c_log_budget-- > 0) {
                snprintf(buf, sizeof buf, "[i2c] select slave 0x%02x -> slot %d\n",
                         addr, cur_slot[fd]);
                logmsg(buf);
            }
            return 0;
        }
        if (req == I2C_FUNCS) {
            /* I2C_FUNC_I2C | I2C_FUNC_SMBUS_BYTE_DATA | _WORD_DATA | _BLOCK_DATA */
            if (arg) *(unsigned long *)arg = 0x0001 | 0x00080000 | 0x00200000 | 0x03000000;
            return 0;
        }
        if (req == I2C_RDWR) {
            struct i2c_rdwr *d = arg;
            unsigned int i;
            unsigned bytes = 0;
            if (d && d->msgs)
                for (i = 0; i < d->nmsgs; i++) {
                    do_msg(slot_for(d->msgs[i].addr), &d->msgs[i]);
                    bytes += d->msgs[i].len + 2;      /* + address and ack */
                }
            /* Same fidelity fix as the SPI loop: a real 100 kHz i2c transfer
             * takes ~90 us per byte and the shim answers instantly, so whatever
             * polls the bus runs far faster than the machine ever could. The
             * game re-opens /dev/i2c-1 about 450 times a second all run long.
             * PAD_I2C_US=0 restores the free-run; the default is per byte. */
            if (i2c_pace_us() > 0 && bytes)
                usleep((unsigned)i2c_pace_us() * bytes);
            return d ? (int)d->nmsgs : 0;
        }
    }

    /* The serial port must behave like a tty or the game refuses to use the
     * bus at all: it sets the line parameters and then reads them back to
     * confirm, so TCGETS has to return exactly what TCSETS was given. */
    if (faked[fd] == 'T') {
        unsigned char *u = arg;
        int i;
        if (tio_log-- > 0) {
            snprintf(buf, sizeof buf, "[nb] ioctl req=0x%lx\n", req);
            logmsg(buf);
        }
        if (req == 0x5401 && u) {                        /* TCGETS   */
            for (i = 0; i < 36; i++) u[i] = tio[i];
            return 0;
        }
        if ((req == 0x5402 || req == 0x5403 || req == 0x5404) && u) {   /* TCSETS/W/F */
            for (i = 0; i < 36; i++) tio[i] = u[i];
            if (!tio_seen) { tio_seen = 1; logmsg("[nb] line parameters accepted\n"); }
            return 0;
        }
        if (req == 0x802C542A && u) {                    /* TCGETS2  */
            for (i = 0; i < 44; i++) u[i] = tio[i];
            return 0;
        }
        if ((req == 0x402C542B || req == 0x402C542C || req == 0x402C542D) && u) { /* TCSETS2/W2/F2 */
            for (i = 0; i < 44; i++) tio[i] = u[i];
            if (!tio_seen) { tio_seen = 1; logmsg("[nb] line parameters accepted (termios2)\n"); }
            return 0;
        }
        /* The node bus runs at a non-standard rate, so the game reads the
         * serial_struct, sets ASYNC_SPD_CUST with its own divisor and writes
         * it back. Both directions have to round-trip or it gives up. */
        if (req == 0x541E && u) {                        /* TIOCGSERIAL */
            for (i = 0; i < 60; i++) u[i] = ser[i];
            return 0;
        }
        if (req == 0x541F && u) {                        /* TIOCSSERIAL */
            for (i = 0; i < 60; i++) ser[i] = u[i];
            if (!ser_seen) {
                ser_seen = 1;
                snprintf(buf, sizeof buf,
                         "[nb] serial params accepted: flags=0x%x divisor=%d base=%d\n",
                         *(unsigned *)(ser + 16), *(int *)(ser + 24), *(int *)(ser + 28));
                logmsg(buf);
            }
            return 0;
        }
        if (req == 0x541B && arg) { *(int *)arg = 0; return 0; }        /* FIONREAD */
        if (req == 0x5415 && arg) { *(int *)arg = 0x1a6; return 0; }    /* TIOCMGET */
        return 0;
    }

    /* ---- SPI_IOC_MESSAGE on /dev/spidev1.0: THE CABINET SWITCHES --------
     *
     * "cpuspi" is not a peripheral the game merely pokes - it is the input path
     * for every switch the playfield node boards do NOT carry. The thread at
     * 0x5a9b60 opens /dev/spidev1.0 at 100 kHz mode 3 and loops forever on an
     * 8-byte full-duplex transfer, copying the RX half into 0x842108 and the
     * outputs out of 0x84214c. 0x5a9df8 then hands those 8 bytes to
     * 0x1e78f4(0, buf) - the SAME distributor the node bus feeds - so node 0 is
     * a real node in the switch model that simply lives on a different wire.
     *
     * Bits are ACTIVE LOW: 0x5a9e50 returns !((buf[bit>>3] >> (bit&7)) & 1).
     * Answering with the zeros this stub used to leave meant every cabinet
     * switch read as PERMANENTLY MADE - Service Select included, which is
     * exactly why pressing it could never produce an edge.
     *
     * This is also the whole of the SPI busy-poll: the loop has no sleep, and
     * on real hardware an 8-byte transfer at 100 kHz paces it to ~640 us. The
     * stub returns instantly, so the thread spins. Not fixed here, but it is
     * now explained rather than mysterious.
     *
     * struct spi_ioc_transfer (32 bytes): +0 tx_buf u64, +8 rx_buf u64,
     * +16 len u32, +20 speed_hz, +24 delay_usecs, +26 bits, +27 cs_change. */
    if (faked[fd] == 'S' && arg && ((req >> 8) & 0xffu) == 0x6b &&
        (req & 0xffu) == 0 && ((req >> 16) & 0x3fffu) >= 32 &&
        sw_scan_enabled()) {
        unsigned long msgs = ((req >> 16) & 0x3fffu) / 32;
        static unsigned char bits[8];
        static unsigned long spin;
        static unsigned seen_gen = (unsigned)-1;
        static unsigned seen_kbd = (unsigned)-1;
        static int have;
        /* Sticky, because `have` is: once the at-rest word is synthesized it
         * stays in bits[] until a real scan replaces it, and sw_prime() must
         * keep its hands off for exactly that long. */
        static int cab_synth;
        unsigned long k;
        /* The thread spins with no pacing, so rebuilding the 88-entry walk on
         * every call would dominate the run. Rebuild when the held set changes
         * and, cheaply, every so often so a table built later still lands. */
        /* The tap schedule is evaluated HERE as well as on the node bus write
         * path, because the bus traffic dries up once the game settles into a
         * menu: a tap scheduled for 45 s fired, the same tap at 55 s never did,
         * and the difference was simply that nothing called sw_tap() any more.
         * This loop never stops. sw_tap() is idempotent - it tracks the slot
         * and direction it last applied - so being driven from two threads
         * costs nothing. */
        /* The periodic tick is counted in LOOP ITERATIONS, so pacing the loop
         * also slows every instrument hanging off it. 4096 iterations was ~18 ms
         * at the old 230 kHz free-run and would be 2.6 s at the paced 1.5 kHz -
         * which would quietly turn PAD_SW_CHANGES and PAD_SW_PEND from live
         * traces into useless ones. Scale the mask with the pacing so the
         * wall-clock cadence stays put. */
        if ((spin & (spi_pace_us() > 0 ? 0x1fu : 0xfffu)) == 0) {
            sw_tap(); sw_changes();
            /* Driven from HERE as well as the node bus write path, for the same
             * reason the tap schedule is: node bus traffic dries up once the
             * game settles into a menu, and this loop never stops. */
            audio_maybe_dump();
        }
        /* PAD_SW_PEND IS OFF THE PERIODIC TICK, on purpose and against the
         * comment above. That tick is ~32 paced iterations, i.e. ~20 ms, and
         * this trace's whole job is to say how WIDE a switch closure looked to
         * the game - so sampling it at 20 ms cannot see a 30 ms press at all,
         * which is item 17's measurement. It self-gates twice (a cached getenv
         * that returns before pad_ms() when PAD_SW_PEND is unset, then one line
         * per millisecond per changed id), so calling it on every transfer costs
         * a pointer compare in a normal run and gives the 1 ms resolution the
         * handoff has always claimed for it. */
        sw_pend_trace();
        /* The keyboard generation is checked on EVERY call, not on the periodic
         * tick: a flipper has to answer the moment the key goes down, and the
         * rebuild itself is still gated behind the comparison. */
        voice_trace();
        if (seen_gen != sw_gen || seen_kbd != sw_shm_gen() ||
            (spin++ & 0xfffu) == 0) {
            unsigned char was[8];
            int hadb = have;
            for (k = 0; k < 8; k++) was[k] = bits[k];
            seen_gen = sw_gen;
            seen_kbd = sw_shm_gen();
            sw_shm_edges();
            have = sw_scan_bytes(0, bits);
            if (have) cab_synth = 0;      /* a real word replaced the synthetic */
            /* EVERY change to the cabinet word, with a timestamp. The menu
             * cursor was seen wandering on its own, and inferring the cause
             * from the screen is exactly the mistake this rig keeps making:
             * this is the input the game is actually being handed. */
            if (have) {
                int diff = !hadb;
                for (k = 0; k < 8; k++) if (was[k] != bits[k]) diff = 1;
                if (diff) {
                    static int cbudget = 200;
                    if (cbudget > 0) {
                        char m3[200];
                        cbudget--;
                        snprintf(m3, sizeof m3,
                                 "[cabchg] %lu ms %02x%02x%02x%02x%02x%02x%02x%02x"
                                 " (was %02x%02x%02x%02x%02x%02x%02x%02x)\n",
                                 pad_ms(), bits[0], bits[1], bits[2], bits[3],
                                 bits[4], bits[5], bits[6], bits[7], was[0],
                                 was[1], was[2], was[3], was[4], was[5],
                                 was[6], was[7]);
                        logmsg(m3);
                    }
                }
            }
        }
        /* ---- ONE-SHOT TAP, applied HERE and nowhere else ------------------
         *
         * This is the point at which the cabinet word is actually handed to the
         * game, so it is the only place a press can be counted in transfers.
         * Doing it where the word is REBUILT would not work: the game reads the
         * same `bits` many times between rebuilds, so the switch would stay made
         * for however long that happened to be - which is exactly the lottery
         * this replaces. */
        {
            static unsigned tap_seen;
            if (sw_shm && sw_shm->magic == PADSW_MAGIC &&
                sw_shm->tap_gen != tap_seen) {
                tap_seen  = sw_shm->tap_gen;
                pad_tap_id = (int)sw_shm->tap_id;
                tap_left   = sw_shm->tap_reads ? sw_shm->tap_reads : 1u;
                have = sw_scan_bytes(0, bits);      /* word WITH the tap made */
                seen_gen = sw_gen;                  /* do not fight the rebuild */
                seen_kbd = sw_shm_gen();
            }
        }
        /* ★ ITEM 52: WITH NO SWITCH TABLE, THE GAME WAS READING ITS OWN BUFFER
         * AND SEEING EVERY CABINET SWITCH MADE.
         *
         * sw_scan_bytes() builds the cabinet word from the GAME'S OWN entry
         * table. On a title whose table never resolves - stranger_things, whose
         * device table is empty and whose in-memory table sw_find_table()
         * rejects - it returns 0, and the `if (have)` below then skipped the
         * RX write ENTIRELY: no `[cabspi]` line, nothing written into the
         * transfer's rx buffer, so the game read whatever was already there.
         * That is its own zeroed buffer, and THE CABINET BITS ARE ACTIVE LOW,
         * so all-zero means ALL SWITCHES MADE - a machine booting with its
         * cabinet shorted. Measured: godzilla logs `[cabspi]
         * bits=ff0f0f0000000000` and `[swrest] machine at rest: coin door
         * shut`; stranger_things logs NEITHER, not once in a 289 s run.
         *
         * The at-rest word is a PLATFORM constant, not godzilla's alone: the
         * handoff records the node 0/1/4 cabinet layout measured identical
         * across star_wars_le 1.30.0, godzilla_pro 1.15.0 and john_wick_le
         * 1.01.0 (2017-2024), and ff 0f 0f 00 00 00 00 00 is what every one of
         * them idles at. Handing that to a title we cannot build a word for is
         * strictly better than handing it nothing, because "nothing" is not
         * neutral here - it is the all-made word.
         *
         * ★ ITEM 63, 2026-08-21: THIS USED TO BE GATED ON sw_table_hopeless(),
         * AND THAT GATE IS WHY EVERY BOOT LANDED ON THE TECH ALERTS SCREEN.
         * hopeless() is `sw_find_fails >= 4` - it only becomes true after four
         * failed find attempts, i.e. for a title whose table NEVER resolves.
         * But a normal title (godzilla) has an EARLY-BOOT WINDOW - from the
         * first SPI transfer until its switch table resolves at ~3.5 s
         * (measured: first [cabspi] ff0f0f... at line ~2107 of a clean boot,
         * right after [swrest]) - during which sw_scan_bytes() ALSO returns 0,
         * hopeless() is still false, so this fallback did NOT fire and the RX
         * buffer was left untouched = the all-made word. Active low, all-made =
         * every cabinet switch pressed, INCLUDING the service/MENU button. The
         * game's input decoder (QrOfflineListener) reads that as a MENU press
         * and opens the operator menu (MenuPageLandingPage = the "Tech Alerts"
         * screen) - the game's boot default is attract, so a spurious
         * service-button press at power-up is the whole reason we land on Tech
         * Alerts. A 6-agent RE workflow proved the menu's bit 0x100 has exactly
         * one setter, reachable at boot only via that opcode-19 MENU event.
         * FIRING ON `!have` ALONE presents the at-rest word (service buttons
         * OPEN) through that window too, so the game never sees the phantom
         * press and boots straight to attract. The word is the correct at-rest
         * state (nothing is pressed at power-up), so it is strictly better than
         * the all-made buffer for the early window exactly as it is for a
         * hopeless title. Priming is still skipped (cab_synth), which is what
         * the old crash-at-6.5s was about. PAD_CAB_IDLE=0 disables it for an
         * A/B and restores the old land-on-Tech-Alerts behaviour. */
        if (!have) {
            static int on = -1;
            if (on == -1) {
                char *q = getenv("PAD_CAB_IDLE");
                on = !(q && *q == '0');
            }
            if (on) {
                static const unsigned char idle[8] =
                    { 0xff, 0x0f, 0x0f, 0, 0, 0, 0, 0 };
                static int said;
                for (k = 0; k < 8; k++) bits[k] = idle[k];
                /* ▼ THE PARAGRAPH THAT USED TO BE HERE WAS WRONG, and it cost
                 * four passes. It said the country dips live in byte 0 of this
                 * word and that "THIS MACHINE WILL NOT OPERATE IN THIS COUNTRY"
                 * meant no country was selected. IT IS NOT A COUNTRY PROBLEM AT
                 * ALL. Message ids 765/766 are "50/60 HZ" and "60 HZ" and sit
                 * immediately before 767-770, and the check that raises that
                 * screen (0x23996c) tests the MAINS FREQUENCY: it wanted 57..63
                 * and our own run_game.sh was reporting 1 Hz, because the game
                 * divides in_power_frequency by 100 and we wrote "60". The
                 * country the game read was a valid U.S.A. throughout. See
                 * run_game.sh where the two iio values are written.
                 *
                 * What survives from that paragraph, because it was measured
                 * and is still true: stranger_things' switch table (entry base
                 * *(0x724608), stride 44, count *(0x7bc86c) = 100; node+bit via
                 * the device table *(0x7260b8), stride 24) names switch ids
                 * 17..24 "DIP 1".."DIP 8" at NODE 0, BITS 0..7 - byte 0 here -
                 * ACTIVE LOW, so the 0xff above rests them all open. That is a
                 * correct at-rest level and there is no reason to move it.
                 *
                 * PAD_CAB_DIP=<n> still forces dips 1..8 to n. It is a knob for
                 * whoever needs one; it is NOT the country and it is NOT a
                 * remedy for that screen. Do not sweep it looking for one. */
                {
                    char *dp = getenv("PAD_CAB_DIP");
                    if (dp && *dp) {
                        unsigned v = 0;
                        int any = 0;
                        if (dp[0] == '0' && (dp[1] == 'x' || dp[1] == 'X')) {
                            dp += 2;
                            for (; *dp; dp++) {
                                if (*dp >= '0' && *dp <= '9') v = v*16 + (unsigned)(*dp-'0');
                                else if (*dp >= 'a' && *dp <= 'f') v = v*16 + (unsigned)(*dp-'a'+10);
                                else if (*dp >= 'A' && *dp <= 'F') v = v*16 + (unsigned)(*dp-'A'+10);
                                else break;
                                any = 1;
                            }
                        } else {
                            for (; *dp >= '0' && *dp <= '9'; dp++) { v = v*10 + (unsigned)(*dp-'0'); any = 1; }
                        }
                        if (any) {
                            char m4[160];
                            bits[0] = (unsigned char)(~v & 0xff);
                            snprintf(m4, sizeof m4,
                                     "[cabdip] country dips 1..8 set to %u "
                                     "(byte0=%02x, active low)\n", v & 0xff, bits[0]);
                            logmsg(m4);
                        }
                    }
                }
                have = 1;
                cab_synth = 1;
                if (!said) {
                    said = 1;
                    logmsg("[cabspi] this title has no findable switch table: "
                           "handing the game the platform AT-REST cabinet word "
                           "ff0f0f0000000000 instead of leaving its buffer "
                           "untouched (which reads as every switch MADE)\n");
                }
            }
        }
        if (have) {
            unsigned char out8[8];
            unsigned j0;
            /* NOT primed when the word is synthesized. sw_prime() writes into
             * the GAME'S OWN NodeRec through SW_STRUCT, and a title with no
             * findable switch table has no trustworthy SW_STRUCT either -
             * sw_ok() only range-checks the pointer, so priming there writes
             * into whatever happens to be mapped. Doing it unconditionally is
             * what crashed godzilla at 6.5 s on the first cut of this change:
             * the fallback fired during early boot, before the table existed,
             * and primed a structure that was not built yet. */
            if (!cab_synth) sw_prime(0, bits);
            for (j0 = 0; j0 < 8; j0++) out8[j0] = bits[j0];
            /* ---- ITEM 17: THE CABINET POLL-RATE PROBE (PAD_CAB_PROBE=1) ---
             *
             * The whole item now turns on ONE unmeasured number: how often
             * does the game actually read this word? It takes the reply on
             * every transfer (~1560/s) but only forwards it to the recorder
             * when the runtime sweep reaches node 0, and node 0 is the
             * sweep's terminator - so the forward rate is invisible from
             * both sides. Capture rates only let you INFER it (300 ms
             * presses land 12/20, so T is about 500 ms); this measures it.
             *
             * Stamp a 16-bit transfer counter into reply bytes 6 and 7. The
             * game copies the reply into NodeRec.cur unconditionally
             * (0x1e7988), so cur[6..7] then holds the counter value AS OF
             * THE POLL: every change of those bytes is one poll, its
             * timestamp is the poll time, and the delta is how many
             * transfers went by in between. Watch live 0x7b95b6/b7.
             *
             * SAFE because bits 48-63 carry no node-0 switch: sw_scan_bytes
             * builds `bits` from the GAME'S OWN entry table and never sets
             * a bit above 23 (the idle word is ff 0f 0f 00 00 00 00 00), and
             * the decoder drops changed bits whose switch id is 0 (0x1e79bc)
             * before they can reach an entry. 16 bits so it does not wrap
             * inside a poll interval - one byte would wrap every 164 ms.
             *
             * This is an INSTRUMENT, not a fix: default off, and it must not
             * be left on in a measuring run of anything else. */
            {
                static int on = -1;
                if (on == -1) {
                    char *q = getenv("PAD_CAB_PROBE");
                    on = q && *q == '1';
                }
                if (on) {
                    cab_ctr++;
                    out8[6] = (unsigned char)(cab_ctr & 0xffu);
                    out8[7] = (unsigned char)((cab_ctr >> 8) & 0xffu);
                }
            }
            for (k = 0; k < msgs; k++) {
                const unsigned char *m = (const unsigned char *)arg + k * 32;
                unsigned rx  = *(const unsigned *)(m + 8);
                unsigned len = *(const unsigned *)(m + 16);
                unsigned j;
                if (!rx || !len) continue;
                if (len > 8) len = 8;
                for (j = 0; j < len; j++)
                    ((unsigned char *)(unsigned long)rx)[j] = out8[j];
            }
            {
                static int budget = 8;
                if (budget > 0) {
                    char m2[160];
                    budget--;
                    snprintf(m2, sizeof m2,
                             "[cabspi] msgs=%lu bits=%02x%02x%02x%02x"
                             "%02x%02x%02x%02x\n", msgs, bits[0], bits[1],
                             bits[2], bits[3], bits[4], bits[5], bits[6],
                             bits[7]);
                    logmsg(m2);
                }
            }
            /* The tap has now appeared in one more transfer. When its count is
             * spent, drop it and rebuild so the very next transfer is clean. */
            if (pad_tap_id >= 0 && tap_left && --tap_left == 0) {
                char m4[80];
                snprintf(m4, sizeof m4, "[tap] id=%d served %u transfer(s)\n",
                         pad_tap_id, sw_shm ? (sw_shm->tap_reads ?
                                               sw_shm->tap_reads : 1u) : 1u);
                logmsg(m4);
                pad_tap_id = -1;
                have = sw_scan_bytes(0, bits);
            }
        }
        /* ---- PACE THE SPI LOOP. This is the single biggest CPU cost in the
         * whole rig, and it is a FIDELITY bug, not a performance trade-off.
         *
         * 0x5a9b60 loops forever on an 8-byte full-duplex SPI_IOC_MESSAGE with
         * no sleep of its own. On the real machine an 8-byte transfer at 100 kHz
         * paces it to ~640 us, i.e. about 1560 iterations a second. Here the shim
         * answers instantly AND answers from inside the guest - no host syscall
         * is made at all - so the loop runs as fast as qemu can translate ARM.
         * Measured: 138 million calls in 600 s (~230 kHz, 150x the real rate),
         * one guest thread pinned at 113% CPU, and it never idles because the
         * thread is always "running" and never in a syscall, which is why it
         * does not show up in any syscall-based profile.
         *
         * Sleeping the real transfer time costs nothing the machine would not
         * also cost, and hands back most of a core. PAD_SPI_US=0 restores the
         * old free-run for comparison. */
        if (spi_pace_us() > 0) usleep((unsigned)spi_pace_us());
        return 0;
    }

    /* SATURATE, don't keep counting. `if (n++ < 40)` looks budgeted and is not:
     * the counter wraps at INT_MAX and the budget comes back to life. The game
     * busy-polls SPI_IOC_MESSAGE on /dev/spidev1.0 (class 'S') hard enough to
     * get there inside ten minutes, and a 600 s run wrote a 7.1 GB log of this
     * one line. Every `budget-- > 0` in this file has the same latent bug; this
     * is the only one on a hot enough path to reach it. */
    if (n < 40) {
        n++;
        snprintf(buf, sizeof buf, "[hwshim] ioctl fd=%d class=%c req=0x%lx -> faked OK\n",
                 fd, faked[fd], req);
        logmsg(buf);
    }
    /* How hard is it actually spinning? One line per 16M calls turns "the log
     * exploded" into a rate, which is the difference between a logging bug and
     * a fidelity bug in the SPI stub. */
    {
        static unsigned long spin;
        if ((++spin & 0xffffffu) == 0) {
            snprintf(buf, sizeof buf,
                     "[hwshim] %lu faked ioctls so far (last fd=%d class=%c req=0x%lx)\n",
                     spin, fd, faked[fd], req);
            logmsg(buf);
        }
    }
    return 0;
}

/* ---------------- node bus instrument -------------------------------- *
 * Switches, coils and lamps all live behind /dev/ttymxc1. Handling it here
 * rather than behind a pty means the count passed to read() is visible, and
 * that count IS the reply length the game expects for the request it just
 * sent. That turns the bus into a self-documenting protocol oracle.
 */
/* THE REAL CAP, and the one that hid behind hex64's. Widening the hex dumper
 * changed nothing while this stayed at 64, because the shim only ever KEPT the
 * first 64 bytes of a request - so a node 7/12/14 LED frame whose own length
 * byte says 118 was already gone by the time anything tried to print it.
 * Two caps in series, and fixing the visible one is not enough.
 * The copy that fills this uses `sizeof nb_req`, so the size lives here alone. */
static unsigned char nb_req[256];
static int nb_req_len;
static int nb_log_budget = 400;
static int nb_reply = 1;           /* 0 = stay silent, 1 = answer with zeros */

/* PAD_NB_LOG=<n> raises the [nb] line budget. It matters more than it looks:
 * at the default 400 the log stops about 6 s into a 60 fps run, which reads
 * exactly like the game giving up on the bus and is nothing of the kind. */
static int nb_budget_init(void)
{
    char *p = getenv("PAD_NB_LOG");
    int v = 0;
    if (!p) return nb_log_budget;
    while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
    return v > 0 ? v : nb_log_budget;
}

static int ishex(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return c - 'A' + 10;
}

/* PAD_NB_FILL=<2 hex digits> fills the reply body with a constant instead of
 * zeros. The Tech Alerts screen names each board's state, so changing the body
 * and reading the screen back says which bytes the game actually grades. */
static int nb_fill(void)
{
    static int v = -2;
    char *p;
    int i, x = 0;
    if (v != -2) return v;
    p = getenv("PAD_NB_FILL");
    if (!p || !p[0]) { v = -1; return v; }
    for (i = 0; i < 2 && p[i]; i++) {
        char c = p[i];
        x <<= 4;
        if (c >= '0' && c <= '9') x |= c - '0';
        else if (c >= 'a' && c <= 'f') x |= c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') x |= c - 'A' + 10;
        else { v = -1; return v; }
    }
    v = x & 0xff;
    return v;
}

/* PAD_NB_PART / PAD_NB_HWID / PAD_NB_FW - the identity a node board claims.
 *
 * 0x5a2e10 is "identify node id and register it". It sends the 0xfe request,
 * and on success parses the 11-byte reply payload as
 *
 *     [0]     bit 7 -> a one-bit flag kept in the per-board record
 *     [1..3]  firmware version, one byte each
 *     [4..7]  LE32 MCU part id
 *     [8..9]  LE16 board id
 *     [10]    kept in the record, otherwise unused here
 *
 * [4..7] is then linear-scanned against the 28-entry table of 28-byte
 * descriptors at 0x69cc24 (NXP LPC part ids - "LPC1112FHN33/103",
 * "LPC812M101JD20", "RP235x", ...). A HIT stores that descriptor in the
 * registry at 0x70a474+0x28+id*4; a miss stores 0x69cc24-28 = 0x69cc08, the
 * "Unknown" default whose +20 is 0 - and +20 is exactly what the exchange
 * wrapper tests at 0x59ec1c before it will send a board any subcommand at or
 * below 0xef. So an unrecognised part id is why nothing below 0xef is ever
 * sent: the board is never registered.
 *
 * [8..9] must be NON-ZERO: 0x5a2f44 caches it as the board's id and re-asks
 * for as long as it reads zero.
 */
static unsigned nb_env_hex(const char *name, unsigned def)
{
    char *p = getenv(name);
    unsigned v = 0;
    int any = 0;
    if (!p) return def;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) p += 2;
    for (; *p; p++) {
        char c = *p;
        if (c >= '0' && c <= '9') v = v * 16 + (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') v = v * 16 + (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v = v * 16 + (unsigned)(c - 'A' + 10);
        else return def;
        any = 1;
    }
    return any ? v : def;
}

/* Default part id 0x00020023 = "LPC1112FHN33/103", entry 4 of the table. Any
 * entry opens the registry gate; this one is only a plausible small node-board
 * MCU. PAD_NB_PART sweeps the rest. */
#define NB_PART_DEFAULT 0x00020023u
#define NB_HWID_DEFAULT 0x0001u
#define NB_FW_DEFAULT   0x000100u      /* 0.1.0, as major<<16 | minor<<8 | patch */

/* PER-NODE IDENTITY. A single global identity cannot work, because the game
 * grades each board against the FIRMWARE FILE for that board's node type, and
 * the type differs per node.
 *
 * The chain, all of it measured rather than guessed:
 *   - the game's own node directory says node 1/8/9 are `pinnode`, 2/7/12/14
 *     are `ws2812node` and 4 is `node4`. That shows up as board[+88], the
 *     CRC32 of the type name: dcc6afb2 / d2a9be05 / f585d1cf.
 *   - the firmware file it wants is ./<type>-<CLASS>-1_35_[0-9]*.hex, where
 *     CLASS comes from the MCU part id the board claims: the part table at
 *     0x69cc24 maps part id -> class index at +8, and 0x59e9bc maps that index
 *     to the string in the filename (1 LPC1112_101, 2 LPC1112_201,
 *     3 LPC1113_302, 4 LPC1124_303, 5 LPC1313, 6 LPC812, 7 RP235x).
 *   - so a board may only claim a part id whose CLASS has a firmware file for
 *     ITS type. Only ws2812node-LPC1313 exists, so every ws2812node board must
 *     claim an LPC1313 part or its lookup misses and it stays "Runtime Info".
 *   - then 0x1d5780 compares the board's claimed firmware version and variant
 *     byte against the ones inside that decrypted .hex. Those are printed by
 *     the [nbhex] dump, and the values below are copied straight from it.
 *
 * node4 misbehaved, and the 2026-08-22 revisit found the misread (the old
 * note here reproduced "what 0x5a8644 actually reads" - 124.107.0 - off the
 * image BUFFER at flash 0x1008). 0x5a8644 has TWO paths: when the image
 * node's [+32] selector is set - true on BOTH node4 images, false on every
 * other type - it grades against the parsed HEADER (the encrypted 06/07 hex
 * records: maj/min/patch at node+16/18/20, variant at node+26), and node4's
 * header says 1.35.0 variant 0x03, same as the FILENAME. The buffer bytes on
 * a node4 image are simply not a version block. The 0x98/124.107.0 claim is
 * why every [nbobj] dump ever taken shows slot 4 at status 7 = Checksum,
 * and why godzilla_le (whose build answers a Checksum grade with an endless
 * "UPDATING NODE BOARD RUNTIME" walk over attract) crawled. Measured live
 * with hexreg.py on the Heisei card; nb_hexreg below reads both paths. */
/* `tcrc` is CRC32 of the board's TYPE NAME - the key the game's own hex-image
 * registry is indexed by (see nb_hexreg below). File-derived entries carry it
 * from node_ident.txt's type= field; the built-in rows leave it 0 (positional
 * initializers), which just means the registry cannot correct them. */
struct nb_ident { unsigned char id; unsigned part; unsigned char variant; unsigned fw; unsigned tcrc; };
static const struct nb_ident nb_idents[] = {
    /* id   part id      variant  fw (maj<<16|min<<8|patch)   type / firmware  */
    {  1, 0x00020023u, 0x01, 0x012300u },  /* pinnode    LPC1112_101  1.35.0 */
    {  8, 0x00020023u, 0x01, 0x012300u },
    {  9, 0x00020023u, 0x01, 0x012300u },
    {  2, 0x2c40102bu, 0x05, 0x012300u },  /* ws2812node LPC1313      1.35.0 */
    {  7, 0x2c40102bu, 0x05, 0x012300u },
    { 12, 0x2c40102bu, 0x05, 0x012300u },
    { 14, 0x2c40102bu, 0x05, 0x012300u },
    {  4, 0x00140040u, 0x03, 0x012300u },  /* node4      LPC1124_303  1.35.0
                                              (HEADER values - see above)   */
};

/* THE FIRMWARE VERSION IS THE TITLE'S, AND IT IS WRITTEN ON THE TIN.
 *
 * 1.35.0 above is Godzilla Pro 1.15.0's, and claiming it at a title that ships
 * anything else earns "Check Node Board N : Version Mismatch" on Tech Alerts -
 * which is what TMNT 1.59 did, because TMNT ships 1.33.0. The game grades each
 * board against the .hex images sitting beside its own binary, and those images
 * carry the version IN THEIR FILENAMES:
 *
 *     pinnode-LPC1313-1_35_0.hex      Godzilla Pro 1.15.0
 *     pinnode-LPC1313-1_33_0.hex      TMNT 1.59
 *
 * So read the directory. The guest chdir()s into its own game directory before
 * exec, so "." is the right place and no title name has to be plumbed in.
 *
 * Only the boards whose table entry says 1.35.0 are moved: node 4's two images
 * report versions that are not 1.x at all (124.107.0 and 146.13.128) and those
 * are reproduced deliberately, not corrected. */
static unsigned nb_fw_title(void)
{
    static unsigned v;
    static int done;
    void *(*ropendir)(const char *);
    void *(*rreaddir)(void *);
    int (*rclosedir)(void *);
    void *d;

    if (done) return v;
    done = 1;
    v = 0x012300u;                                   /* 1.35.0, the old value */
    ropendir  = dlsym(RTLD_NEXT, "opendir");
    rreaddir  = dlsym(RTLD_NEXT, "readdir");
    rclosedir = dlsym(RTLD_NEXT, "closedir");
    if (!ropendir || !rreaddir) return v;
    d = ropendir(".");
    if (!d) return v;
    for (;;) {
        /* glibc's struct dirent puts d_name at +19 on this ABI. */
        const char *nm;
        void *e = rreaddir(d);
        int i, n, dot = -1, dash = -1;
        if (!e) break;
        nm = (const char *)e + 19;
        for (n = 0; n < 120 && nm[n]; n++) {
            if (nm[n] == '-') dash = n;
            if (nm[n] == '.') dot = n;
        }
        if (n >= 120 || dash < 0 || dot <= dash + 1) continue;
        if (nm[dot] != '.' || nm[dot + 1] != 'h' || nm[dot + 2] != 'e'
            || nm[dot + 3] != 'x' || nm[dot + 4]) continue;
        {   /* expect <maj>_<min>_<patch> between the last '-' and ".hex" */
            unsigned part[3] = { 0, 0, 0 };
            int k = 0, any = 0;
            for (i = dash + 1; i < dot; i++) {
                if (nm[i] >= '0' && nm[i] <= '9') {
                    part[k] = part[k] * 10 + (unsigned)(nm[i] - '0');
                    any = 1;
                } else if (nm[i] == '_' && k < 2) {
                    k++;
                } else {
                    any = 0;
                    break;
                }
            }
            if (any && k == 2 && part[0] < 256 && part[1] < 256 && part[2] < 256) {
                unsigned f = (part[0] << 16) | (part[1] << 8) | part[2];
                if (f != v) {
                    char m[120];
                    snprintf(m, sizeof m,
                             "[nbfw] node firmware %u.%u.%u, from %s\n",
                             part[0], part[1], part[2], nm);
                    logmsg(m);
                }
                v = f;
                break;
            }
        }
    }
    if (rclosedir) rclosedir(d);
    return v;
}

/* ★ ITEM 51: THE TITLE'S OWN NODE DIRECTORY, WHEN THE RIG HAS DERIVED IT.
 *
 * nb_idents[] above is godzilla's node set measured once and claimed at
 * every title - which star_wars_le answered with "UPDATING NODE BOARD
 * RUNTIME 12 / UPDATE FAILED" looping over attract, and 215+ identity
 * re-asks per node in five minutes: it has nodes 10/11/13/15 the table
 * never heard of (claimed as fw 0.1.0 pinnodes) and its 11/12 are
 * coil4nodes the table claims as ws2812node. The truth is a static
 * structure in each title's game ELF; nbdir.py reads it before the run and
 * writes /dump/tables/<title>/node_ident.txt, and this loads that file -
 * derived per title, nothing committed, the same shape as the census and
 * mktables. The built-in table stays as the fallback for a run whose
 * derivation failed, which is exactly the old behaviour.
 *
 * Read with dlsym(RTLD_NEXT) rather than plain fopen for the same reason
 * nb_fw_title() reads the directory that way: the shim hooks the libc I/O
 * the GAME uses, and going through its own hooks would recurse. */
static struct nb_ident nb_fident[64];      /* file-derived, by node id      */
static unsigned char   nb_fident_have[64];
static int             nb_fident_state;    /* 0 unloaded, 1 loaded, -1 none */

/* No <stdio.h> in this file, so no sscanf: find `key` in `line` and parse
 * the number after it. Decimal and hex variants; both demand at least one
 * digit and return 0 on a missing key or empty number. */
static int nb_field_dec(const char *line, const char *key, unsigned *out)
{
    const char *s = strstr(line, key);
    unsigned v = 0;
    int any = 0;
    if (!s) return 0;
    for (s += strlen(key); *s >= '0' && *s <= '9'; s++) {
        v = v * 10 + (unsigned)(*s - '0');
        any = 1;
    }
    if (any) *out = v;
    return any;
}

static int nb_field_hex(const char *line, const char *key, unsigned *out)
{
    const char *s = strstr(line, key);
    unsigned v = 0;
    int any = 0;
    if (!s) return 0;
    for (s += strlen(key); ; s++) {
        char c = *s;
        if (c >= '0' && c <= '9') v = v * 16 + (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') v = v * 16 + (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v = v * 16 + (unsigned)(c - 'A' + 10);
        else break;
        any = 1;
    }
    if (any) *out = v;
    return any;
}

static void nb_fident_load(void)
{
    typedef void *FILEP;
    FILEP (*ropen)(const char *, const char *);
    char *(*rgets)(char *, int, FILEP);
    int  (*rclose)(FILEP);
    FILEP f;
    char path[192], line[256], msg[160];
    const char *p, *g;
    int n = 0;

    if (nb_fident_state) return;
    nb_fident_state = -1;
    p = getenv("PAD_NB_IDENT");
    g = getenv("PAD_GAME");
    if (p && *p)
        snprintf(path, sizeof path, "%s", p);
    else if (g && *g)
        snprintf(path, sizeof path, "/dump/tables/%s/node_ident.txt", g);
    else
        return;
    ropen  = dlsym(RTLD_NEXT, "fopen");
    rgets  = dlsym(RTLD_NEXT, "fgets");
    rclose = dlsym(RTLD_NEXT, "fclose");
    if (!ropen || !rgets || !rclose) return;
    f = ropen(path, "r");
    if (!f) return;
    while (rgets(line, sizeof line, f)) {
        unsigned id, part, var, fw;
        const char *t;
        if (line[0] == '#') continue;
        if (!nb_field_dec(line, "node=", &id) || id >= 64) continue;
        if (!nb_field_hex(line, "part=0x", &part)) continue;
        if (!nb_field_hex(line, "variant=0x", &var)) continue;
        if (!nb_field_hex(line, "fw=0x", &fw)) continue;
        nb_fident[id].id = (unsigned char)id;
        nb_fident[id].part = part;
        nb_fident[id].variant = (unsigned char)var;
        nb_fident[id].fw = fw;
        /* The TYPE NAME, as its CRC32 - the key into the game's own hex-image
         * registry (nb_hexreg below), so a derived claim can be corrected
         * against what the game actually decrypted. Absent field = 0 = never
         * corrected, which is exactly the old behaviour. */
        nb_fident[id].tcrc = 0;
        t = strstr(line, "type=");
        if (t) {
            unsigned c = 0xffffffffu;
            int k;
            for (t += 5; *t && *t != ' ' && *t != '\n'; t++) {
                c ^= (unsigned char)*t;
                for (k = 0; k < 8; k++)
                    c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
            }
            nb_fident[id].tcrc = c ^ 0xffffffffu;
        }
        nb_fident_have[id] = 1;
        n++;
    }
    rclose(f);
    if (n > 0) {
        nb_fident_state = 1;
        snprintf(msg, sizeof msg,
                 "[nbid] %d node identities from %.110s\n", n, path);
        logmsg(msg);
    }
}

/* PAD_NB_PART / PAD_NB_VARIANT / PAD_NB_FW still override, globally, so the
 * table can be bypassed for a sweep without editing code. */
static unsigned nb_ident_fw(const struct nb_ident *i)
{
    if (!i) return NB_FW_DEFAULT;
    /* file-derived entries carry the title's own per-node version already -
     * only the built-in table's 1.35.0 placeholders go through the
     * filename-glob fallback */
    if (i >= nb_fident && i < nb_fident + 64) return i->fw;
    return i->fw == 0x012300u ? nb_fw_title() : i->fw;
}

static const struct nb_ident *nb_ident_for(unsigned id)
{
    unsigned i;
    nb_fident_load();
    if (id < 64 && nb_fident_have[id]) return &nb_fident[id];
    for (i = 0; i < sizeof nb_idents / sizeof nb_idents[0]; i++)
        if (nb_idents[i].id == id) return &nb_idents[i];
    return 0;
}

/* ---- THE GAME'S OWN HEX-IMAGE EXPECTATIONS, READ BACK OUT OF ITS MEMORY --
 *
 * The game grades every board's claimed identity against the DECRYPTED
 * <type>-<class>-*.hex image: variant at flash 0x1008, version at
 * 0x1009..0x100b (0x1d5780 / 0x5a8644, and nb_dump_hexlist's annotations).
 * A claim it rejects starts the RUNTIME UPDATE walk - "UPDATING NODE BOARD
 * RUNTIME / UPDATE FAILED / PLEASE WAIT" retried every ~15 s, and the game
 * sits on it before attract. MEASURED 2026-08-22 on the Heisei card
 * (godzilla_le): nbdir.py had to GUESS the tmc5041node variant (0x01, the
 * hex body is encrypted so the file cannot say), the game's decrypted image
 * carries 0x0d, and that one byte cost every boot ~80 s of failed updates
 * on node 10 before the game gave up and went to attract at t=104 s.
 *
 * The fix is to stop inventing what the game already knows: the decrypted
 * images are IN ITS MEMORY, in the hex-image registry (a linked list keyed
 * by CRC32 of the type name - zlib polynomial, verified against the keys at
 * the top of this file - and LPC class). The registry HEAD is a per-title
 * global (0x7e1b98 is godzilla_pro 1.15.0's, and walking that literal on
 * another title is the segfault item 52 recorded), but the NODES have a
 * rigid 64-byte shape, so they are found per title BY SHAPE, the same move
 * as nb_objs_addr():
 *
 *     w[0]  CRC32(type name)  - must be one of the 14 known type names
 *     w[1]  LPC class 1..7
 *     w[2]  char* path        - must point at readable memory ending .hex
 *     w[7]  decrypted image buffer (indexed by absolute flash address)
 *     w[10] image-kind flag == 1
 *     w[11] min flash address == 0x1000
 *     w[12] span > 11
 *
 * SAFE BY CONSTRUCTION, unlike the pro-literal walk: every candidate and
 * every pointer it carries is range-checked against /proc/self/maps (the
 * guest view - qemu-user serves the guest's own mappings there) before it
 * is dereferenced, so a false positive costs a skipped candidate, never a
 * fault. host-side twin: hexreg.py, which read the live game's registry
 * through /proc/<pid>/mem and produced the 0x0d measurement above.
 *
 * COST, because item 52's lesson was our own heap scan on the game's bus
 * thread: the scan runs on the fe (identity) path, at most once every 2 s
 * of RUN TIME and NB_HEXREG_TRIES attempts in total, only until it
 * succeeds, over rw regions capped at 16 MB each / 32 MB per attempt - the
 * registry lives in the low heap (found at guest 0x85xxxx), well inside the
 * caps. TIME-paced rather than per-N-requests on purpose: the update walk
 * hammers fe at ~18/s, and the first shape of this throttle (every 64th fe,
 * 20 tries) spent its whole budget inside the first minute of a boot -
 * "[nbexp] no hex-image registry found" on the very run whose walk was
 * using that registry to flash from. Bring-up is also when the bus thread
 * spends its time sleeping on probe timeouts, so a bounded scan there is
 * invisible next to the traffic.
 *
 * PAD_NB_HEXREG=0 disables the whole thing for an A/B; claims then come
 * from node_ident.txt / the built-in table exactly as before. */
#define NB_HEXREG_MAX   24
#define NB_HEXREG_TRIES 40

static struct { unsigned tcrc, klass, fw; unsigned char variant; }
    nb_hexreg[NB_HEXREG_MAX];
static int nb_hexreg_n;                 /* entries found; -1 = given up      */

static const char *const nb_hexreg_types[] = {
    "pinnode", "ws2812pinnode", "ws2812node", "coil4_lednode", "coil4node",
    "lcdnode", "hdminode", "hdmi_ws2812node", "afnode", "magsensornode",
    "node4", "tmc2590node", "tmc5041node", "netbridge",
};

static unsigned nb_hexreg_crc(const char *s)
{
    unsigned c = 0xffffffffu;
    int k;
    for (; *s; s++) {
        c ^= (unsigned char)*s;
        for (k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return c ^ 0xffffffffu;
}

static int nb_hexreg_type_known(unsigned crc)
{
    static unsigned crcs[sizeof nb_hexreg_types / sizeof *nb_hexreg_types];
    static int done;
    unsigned i;
    if (!done) {
        for (i = 0; i < sizeof crcs / sizeof *crcs; i++)
            crcs[i] = nb_hexreg_crc(nb_hexreg_types[i]);
        done = 1;
    }
    for (i = 0; i < sizeof crcs / sizeof *crcs; i++)
        if (crcs[i] == crc) return 1;
    return 0;
}

/* /proc/self/maps, guest view. `rd` collects every readable region (for
 * pointer validation), the return value is how many; `rw` marks which are
 * also writable (scan candidates). Read through RTLD_NEXT like every other
 * shim-side file read, so it cannot recurse into our own hooks. */
#define NB_HEXREG_REGIONS 128
static int nb_hexreg_maps(unsigned lo[], unsigned hi[], unsigned char rw[])
{
    typedef void *FILEP;
    FILEP (*ropen)(const char *, const char *);
    char *(*rgets)(char *, int, FILEP);
    int (*rclose)(FILEP);
    FILEP f;
    /* 512, not a small buffer: a maps line longer than the buffer makes
     * fgets hand back the TAIL of the line as a second read, and a path
     * fragment that happens to parse as hex-dash-hex would put a fabricated
     * region into a list the scanner dereferences. The perms-shape check
     * below is the second lock on the same door. */
    char line[512];
    int n = 0;

    ropen  = dlsym(RTLD_NEXT, "fopen");
    rgets  = dlsym(RTLD_NEXT, "fgets");
    rclose = dlsym(RTLD_NEXT, "fclose");
    if (!ropen || !rgets || !rclose) return 0;
    f = ropen("/proc/self/maps", "r");
    if (!f) return 0;
    while (n < NB_HEXREG_REGIONS && rgets(line, sizeof line, f)) {
        unsigned a = 0, b = 0;
        const char *s = line;
        int any = 0;
        for (; (*s >= '0' && *s <= '9') || (*s >= 'a' && *s <= 'f'); s++) {
            a = a * 16 + (unsigned)(*s <= '9' ? *s - '0' : *s - 'a' + 10);
            any = 1;
        }
        if (!any || *s != '-') continue;
        for (s++; (*s >= '0' && *s <= '9') || (*s >= 'a' && *s <= 'f'); s++)
            b = b * 16 + (unsigned)(*s <= '9' ? *s - '0' : *s - 'a' + 10);
        if (*s != ' ' || b <= a || (a & 0xfff)) continue;
        /* the whole rwxp column has to look like one, not just its first
         * letter - see the buffer comment above */
        if (s[1] != 'r') continue;
        if (s[2] != 'w' && s[2] != '-') continue;
        if (s[3] != 'x' && s[3] != '-') continue;
        if (s[4] != 'p' && s[4] != 's') continue;
        lo[n] = a;
        hi[n] = b;
        rw[n] = s[2] == 'w';
        n++;
    }
    rclose(f);
    return n;
}

static int nb_hexreg_readable(const unsigned lo[], const unsigned hi[],
                              int n, unsigned addr, unsigned len)
{
    int i;
    if (!addr || addr + len < addr) return 0;
    for (i = 0; i < n; i++)
        if (addr >= lo[i] && addr + len <= hi[i]) return 1;
    return 0;
}

/* Last-scan facts for the give-up line: a scan that fails on some future
 * title must say what it looked at, or "not found" cannot be told apart from
 * "never really looked" (an empty maps parse, a giant heap skipped by the
 * caps) without another instrumented run. */
static unsigned nb_hexreg_stat_maps, nb_hexreg_stat_rw;
static unsigned long nb_hexreg_stat_bytes;

static void nb_hexreg_scan(void)
{
    static unsigned lo[NB_HEXREG_REGIONS], hi[NB_HEXREG_REGIONS];
    static unsigned char rw[NB_HEXREG_REGIONS];
    unsigned long scanned = 0;
    char m[200];
    int nmaps, r;

    nmaps = nb_hexreg_maps(lo, hi, rw);
    nb_hexreg_stat_maps = (unsigned)nmaps;
    nb_hexreg_stat_rw = 0;
    for (r = 0; r < nmaps; r++) nb_hexreg_stat_rw += rw[r];
    /* CAPS, and they are about the bus thread, not memory: this runs inside
     * an fe exchange, and the game's serial read timeout is ~10 ms - a scan
     * that stalls the reply for long enough reads as an absent board, on
     * EVERY title including the ones whose claims were already right. The
     * registry sits in the first MBs of the guest heap (measured at
     * 0x85xxxx), and maps come back in address order, so a 16 MB per-region
     * / 32 MB per-attempt budget reaches it with room to spare while keeping
     * one attempt to tens of emulated milliseconds. */
    for (r = 0; r < nmaps && nb_hexreg_n < NB_HEXREG_MAX; r++) {
        const unsigned *p, *end;
        if (!rw[r] || hi[r] - lo[r] > 16u * 1024 * 1024) continue;
        if (lo[r] >= 0xf0000000u) continue;
        if (scanned > 32u * 1024 * 1024) break;
        scanned += hi[r] - lo[r];
        p = (const unsigned *)(unsigned long)((lo[r] + 3u) & ~3u);
        end = (const unsigned *)(unsigned long)(hi[r] - 64u);
        for (; p <= end && nb_hexreg_n < NB_HEXREG_MAX; p++) {
            const unsigned char *buf, *path;
            int i;
            if (p[11] != 0x1000u) continue;     /* min flash addr, rarest    */
            if (p[10] != 1u) continue;          /* image-kind flag           */
            if ((int)p[12] <= 11) continue;     /* span                      */
            if (p[1] < 1u || p[1] > 7u) continue;
            if (!nb_hexreg_type_known(p[0])) continue;
            /* validated for the WHOLE walk below, not the first byte - a
             * string that runs to the very end of its mapping must not take
             * the walk over the edge */
            if (!nb_hexreg_readable(lo, hi, nmaps, p[2], 200)) continue;
            path = (const unsigned char *)(unsigned long)p[2];
            for (i = 0; i < 200 && path[i]; i++) ;
            if (i < 4 || i >= 200) continue;
            if (path[i-4] != '.' || path[i-3] != 'h'
                    || path[i-2] != 'e' || path[i-1] != 'x') continue;
            /* ★ TWO VERSION SOURCES, and the game's reader 0x5a8644 picks:
             * with the node's [+32] selector SET it grades against the
             * parsed HEADER (the encrypted 06/07 records - maj/min/patch at
             * node+16/18/20, variant at node+26); only with it clear does it
             * read the decrypted buffer at flash 0x1008. Both node4 images
             * carry the selector, and reading only the buffer is exactly the
             * misread that had node 4 claiming 124.107.0/0x98 against a
             * header saying 1.35.0/0x03 - status 7 on every boot ever
             * dumped. Mirror the game's choice, not one of its inputs. */
            {
                const unsigned char *nb = (const unsigned char *)p;
                unsigned char var, v0, v1, v2;
                const char *src;
                if (p[8]) {
                    var = nb[26]; v0 = nb[16]; v1 = nb[18]; v2 = nb[20];
                    src = "header";
                } else {
                    if (!nb_hexreg_readable(lo, hi, nmaps, p[7] + p[11], 12))
                        continue;
                    buf = (const unsigned char *)(unsigned long)(p[7] + p[11]);
                    var = buf[8]; v0 = buf[9]; v1 = buf[10]; v2 = buf[11];
                    src = "image";
                }
                nb_hexreg[nb_hexreg_n].tcrc = p[0];
                nb_hexreg[nb_hexreg_n].klass = p[1];
                nb_hexreg[nb_hexreg_n].variant = var;
                nb_hexreg[nb_hexreg_n].fw = ((unsigned)v0 << 16)
                                          | ((unsigned)v1 << 8) | v2;
                nb_hexreg_n++;
                snprintf(m, sizeof m,
                         "[nbexp] %s class=%u variant=0x%02x version=%u.%u.%u  %s\n",
                         src, p[1], var, v0, v1, v2, (const char *)path);
                logmsg(m);
            }
        }
    }
    nb_hexreg_stat_bytes = scanned;
}

/* The board's MCU part id names its LPC class (the game's own table at
 * 0x69cc24); only the classes hwshim has measured part ids for are
 * ever claimed, so these entries are the whole mapping. */
static unsigned nb_hexreg_class(unsigned part)
{
    if (part == 0x00020023u) return 1;          /* LPC1112_101 */
    if (part == 0x00030030u) return 3;          /* LPC1113_302 (lcdnode) -
                                                 * measured off batman's own
                                                 * descriptor table, item 82 */
    if (part == 0x00140040u) return 4;          /* LPC1124_303 */
    if (part == 0x2c40102bu) return 5;          /* LPC1313     */
    return 0;
}

/* Correct a claim's (variant, fw) from the game's own registry, when the
 * registry has been found and carries this (type, class). Says so in the log
 * once per node when it actually changed something - the update overlay and
 * these lines are the oracle pair. */
static void nb_hexreg_answer(unsigned nid, unsigned tcrc, unsigned part,
                             unsigned *var, unsigned *fw)
{
    static int on = -1, tries;
    static unsigned long last_try;
    static unsigned long long said;
    int i;

    if (on == -1) { char *q = getenv("PAD_NB_HEXREG"); on = !(q && *q == '0'); }
    if (!on || !tcrc) return;
    if (nb_hexreg_n <= 0) {
        unsigned long now;
        if (tries < 0) return;                  /* given up                  */
        now = pad_ms();
        if (last_try && now - last_try < 2000) return;
        last_try = now;
        nb_hexreg_scan();
        if (nb_hexreg_n > 0) {
            char m[120];
            snprintf(m, sizeof m, "[nbexp] the game's hex-image registry: "
                     "%d decrypted image(s) found by shape\n", nb_hexreg_n);
            logmsg(m);
        } else if (++tries >= NB_HEXREG_TRIES) {
            char m[200];
            tries = -1;
            snprintf(m, sizeof m, "[nbexp] no hex-image registry found by "
                     "shape after %d scans (last: %u map lines, %u rw, "
                     "%lu bytes walked); claims stay file/table-derived\n",
                     NB_HEXREG_TRIES, nb_hexreg_stat_maps,
                     nb_hexreg_stat_rw, nb_hexreg_stat_bytes);
            logmsg(m);
            return;
        }
    }
    for (i = 0; i < nb_hexreg_n; i++) {
        if (nb_hexreg[i].tcrc != tcrc) continue;
        if (nb_hexreg[i].klass != nb_hexreg_class(part)) continue;
        if ((*var != nb_hexreg[i].variant || *fw != nb_hexreg[i].fw)
                && nid < 64 && !(said & (1ull << nid))) {
            char m[160];
            said |= 1ull << nid;
            snprintf(m, sizeof m, "[nbexp] node %u claim corrected from the "
                     "game's own image: variant 0x%02x->0x%02x fw %u.%u.%u->"
                     "%u.%u.%u\n", nid, *var, nb_hexreg[i].variant,
                     (*fw >> 16) & 0xff, (*fw >> 8) & 0xff, *fw & 0xff,
                     (nb_hexreg[i].fw >> 16) & 0xff,
                     (nb_hexreg[i].fw >> 8) & 0xff, nb_hexreg[i].fw & 0xff);
            logmsg(m);
        }
        *var = nb_hexreg[i].variant;
        *fw = nb_hexreg[i].fw;
        return;
    }
}

/* PAD_NB_DUMP=<n> - every n node bus writes, dump the node board registry.
 *
 * The addressed path of the bus exchange at 0x59ebfc indexes a table to decide
 * whether a board is worth talking to:
 *     r3 = req[0] & 0x3f              ; node id
 *     r3 = [0x70a474 + 0x28 + id*4]   ; board object
 *     if ([r3 + 20] == 0) skip the exchange
 * so 0x70a474+0x28 is a 64-entry array of board objects. The shim shares the
 * guest's address space, so it can just read them - no debugger needed. The
 * status strings ("No Errors", "Not Responding", ... "Not Initialized") are
 * message rows 3059..3069, i.e. a small integer somewhere in this object.
 */
#define NB_TABLE 0x70a474u
#define NB_SLOTS 0x28u

/* The per-board identity record 0x5a2e10 writes on success: 12 bytes at
 * 0x841a0c + id*12, i.e. the parsed reply payload. Printing it next to the
 * registry slot turns "did that board register?" into one line. */
#define NB_RECORDS 0x841a0cu

static void nb_dump_boards(void)
{
    char line[400];
    unsigned id;
    const unsigned *slots = (const unsigned *)(unsigned long)(NB_TABLE + NB_SLOTS);
    logmsg("[nbtbl] --- node board registry ---\n");
    for (id = 0; id < 16; id++) {
        unsigned obj = slots[id];
        const unsigned char *rec = (const unsigned char *)(unsigned long)(NB_RECORDS + id * 12);
        const unsigned *w;
        const char *name = "?";
        int i, k = 0;
        if (!obj) continue;
        if (obj < 0x400000u || obj >= 0xf0000000u || (obj & 3)) {
            snprintf(line, sizeof line, "[nbtbl] node %2u obj=0x%08x (not readable)\n", id, obj);
            logmsg(line);
            continue;
        }
        /* +0 is the part id it matched, +4 the descriptor's name, +20 the field
         * the exchange wrapper gates on (0 only for the "Unknown" default). */
        w = (const unsigned *)(unsigned long)obj;
        if (w[1] >= 0x8000u && w[1] < 0x6d63d4u) name = (const char *)(unsigned long)w[1];
        k = snprintf(line, sizeof line,
                     "[nbtbl] node %2u obj=0x%08x part=%08x gate[+20]=%08x %-24s rec:",
                     id, obj, w[0], w[5], name);
        for (i = 0; i < 12 && k < (int)sizeof line - 4; i++)
            k += snprintf(line + k, sizeof line - k, "%s%02x", (i % 4) ? "" : " ", rec[i]);
        snprintf(line + k, sizeof line - k, "\n");
        logmsg(line);
    }
}

/* The BOARD OBJECTS, which is a different and far better instrument than the
 * registry above. 0x39c9e0(id) is "first present board at or after id":
 *
 *     if (id > 31) return 0
 *     obj = 0x7bad88 + id*0xe0            ; 32 slots, stride 224
 *     while (!obj[12]) obj += 0xe0        ; [+12] != 0 means the slot is used
 *
 * and the state machine at 0x1d550c(obj, x) writes the ON-SCREEN STATUS INDEX
 * to [obj+24] - the same 0..11 enum the Tech Alerts line renders through
 * "Check Node Board %d : %s". Every literal it stores is visible in one place:
 *
 *     1d5708  3  Collision                 identity byte b[0] (bit 7 of payload[0]) != 0
 *     1d56f4  4  Not Initialized           the 0x44880c hex-image lookup came back empty
 *     1d55bc  8  Runtime Info              an identity exchange failed and none disagreed
 *     1d55fc  9  Boot                      two identity reads disagreed
 *     1d57a0  6  Hex Image Version not Found
 *     1d57bc  7  Checksum                  board version != hex image version
 *     1d580c  2  Not Registered            everything matched
 *
 * so reading [obj+24] answers "what does the screen say" without rendering a
 * frame, and reading it per board says WHICH board is stuck. This is the
 * cheapest available signal and it costs one memory read.
 *
 * Layout confirmed from the same function: [+0] byte node id, [+4] flags
 * (bit 1 = skip this board), [+12] present pointer, [+24] status, [+28..30]
 * firmware version bytes copied from the identity, [+32] object from
 * 0x59e904(part id), [+40..87] the 48-byte runtime-info record 0x5a2b88
 * builds, [+88] the hex-image owner, [+147]/[+148] two flags.
 */
/* ★ THIS INSTRUMENT ONLY TELLS THE TRUTH ON GODZILLA PRO 1.15.0, AND IT DOES
 * NOT SAY SO (item 52, 2026-08-16). 0x7bad88 is godzilla's address; nothing in
 * this rig ever sets PAD_NB_OBJS - no watch.sh line, no mktables output, no
 * per-title derivation - so on every other title a_nb_objs() returns the
 * built-in default whenever that address merely happens to be READABLE in that
 * guest, which is exactly the trap title_addr() carries and which already cost
 * a pass on the switch table ("EHOH's binary is big enough to cover Godzilla
 * Pro's 0x7a958c, so a_sw_struct() returned an address and the shim read a
 * switch table out of somebody else's data").
 *
 * So [nbobj]/[nbtbl] readings on stranger_things, star_wars, turtles - anything
 * but godzilla_pro - are somebody else's memory formatted as a status table.
 * They are not weak evidence, they are no evidence. NB_TABLE and NB_RECORDS
 * below are worse: plain #defines, not even overridable.
 *
 * This is what makes item 52 dear rather than cheap: the one instrument that
 * turns "what does the screen say" into a per-board memory read cannot judge
 * the title the item is about. Finding the array per title is the job - by
 * shape at runtime is the durable form (32 slots of 0xe0 where slot[i][+0]==i
 * and [+12] is non-zero for the populated ones), and godzilla is the labelled
 * example any finder must reproduce 0x7bad88 on before it is trusted. */
TITLE_ADDR(a_nb_objs, "PAD_NB_OBJS", 0x7bad88u)
#define NB_OBJ_SZ 0xe0u

/* ★ ITEM 52: FIND THE ARRAY BY SHAPE, so this instrument works on a title
 * other than the one it was measured on.
 *
 * THE SHAPE, taken from a measured godzilla dump rather than from prose - every
 * populated slot LABELS ITSELF with its own index:
 *
 *     [nbobj] slot  0 node  0 ... status=2      [nbobj] slot  8 node  8 ...
 *     [nbobj] slot  1 node  1 ... status=2      [nbobj] slot  9 node  9 ...
 *     [nbobj] slot  2 node  2 ... status=8      [nbobj] slot 12 node 12 ...
 *     [nbobj] slot  4 node  4 ... status=7      [nbobj] slot 14 node 14 ...
 *
 * so for 32 slots of stride 0xe0: [+12] non-zero means the slot is in use, and
 * every in-use slot has [+0] == its own index and [+24] a status below 12. The
 * self-labelling is what makes the base UNIQUE - a candidate off by one slot
 * has every id one out and dies immediately - so no alignment guess is needed.
 *
 * DELIBERATE DUPLICATION, and it is worth a line. This repeats sw_find_table()'s
 * /proc/self/maps walk instead of sharing it, because factoring that out would
 * edit the switch table's discovery path - which is load-bearing on exactly the
 * titles this pass is investigating, and which this pass has no way to
 * regression-test. If a THIRD one of these ever appears, factor all three then.
 *
 * Reads stay inside the region the maps line already proved mapped, so no
 * addr_readable() call is needed per candidate and the scan costs no
 * syscalls. ▼ AND "PROVED MAPPED" PROVES WHERE, NOT WHEN (2026-08-18): the
 * guest freed a region mid-walk and this scan died reading a slot's [+12]
 * in-use word, 16 s into the first run whose earlier scans were fast enough
 * to land here during boot's heaviest scene churn. The walk therefore runs
 * under the same fault guard as the switch scan - see nb_scan_objs() below,
 * the guarded wrapper this body was renamed _walk for. */
/* Returns the number of in-use slots if EVERY in-use slot is self-consistent,
 * and 0 the moment one is not. The count is the caller's to judge: three is
 * enough to act on, and one or two is reported as a near miss rather than
 * thrown away, because "an array with two boards in it" and "no array at all"
 * are completely different answers about a title that will not boot - and a
 * finder that cannot tell them apart is the kind of instrument this rig has
 * been burned by before. */
/* The shape test, parameterised by STRIDE so the stride sweep below can run the
 * exact same discriminator at every candidate size instead of a weaker one.
 * The [+12] in-use gate and the [+24] status gate are what make this reject a
 * plain incrementing byte table (which self-labels perfectly but has neither),
 * and dropping them was why the first sweep failed its own labelled example. */
static unsigned nb_objs_shape_ok_s(unsigned base, unsigned stride)
{
    unsigned i, present = 0;
    for (i = 0; i < 32; i++) {
        const unsigned char *o =
            (const unsigned char *)(unsigned long)(base + i * stride);
        if (!*(const unsigned *)(o + 12)) continue;      /* slot not in use */
        if (o[0] != (unsigned char)i) return 0;          /* must self-label */
        if (*(const unsigned *)(o + 24) >= 12u) return 0;   /* status is 0..11 */
        present++;
    }
    return present;
}

static unsigned nb_objs_shape_ok(unsigned base)
{
    return nb_objs_shape_ok_s(base, NB_OBJ_SZ);
}

/* NB_OBJS_MIN is what separates a hit from a near miss, and the difference
 * MATTERS TO THE SCAN ITSELF, not just to the report. A hit skips its own
 * 0x1c00 span, because an array cannot start inside another one; a near miss
 * must NOT, because weak 1-2 slot coincidences are common and each skip is
 * 0x1c00 bytes of address space unexamined. Letting them skip cost this pass a
 * godzilla regression: the scan matched a 2-slot coincidence, jumped its span,
 * and sailed straight over the real 9-slot array at 0x7bad88 that the previous
 * build had found. The labelled example caught it; that is what it is for. */
#define NB_OBJS_MIN 3u

/* ★ ITEM 52: THE STRIDE SWEEP - the one assumption the finder above cannot
 * test about itself. Defined ABOVE nb_scan_objs() because that is where it is
 * called from; C wants it declared first.
 *
 * nb_scan_objs() hard-codes NB_OBJ_SZ (0xe0), which is godzilla 1.15.0's board
 * struct size. Everything this branch concluded about stranger_things rests on
 * "ST creates no board objects" - but an array whose struct grew or shrank in a
 * newer firmware would be INVISIBLE to a 0xe0-stride scan, and the conclusion
 * would be an artefact of the instrument rather than a fact about the title.
 * That is exactly the class of mistake this rig keeps paying for, so test it.
 *
 * It runs the SAME discriminator as the real finder (nb_objs_shape_ok_s: self
 * -label + [+12] in-use + [+24] status < 12) at every stride 0x80..0x200, and
 * scores by in-use slot count. Self-labelling ALONE is far too weak - the first
 * cut of this sweep counted only `byte[a+i*s]==i`, and a plain incrementing
 * byte table (0,1,2,..) scores a perfect 32, which is exactly what it found:
 * 0x0079aca4 stride 0x118 slots 32, beating godzilla's real 9-slot array. It
 * FAILED its own labelled example, which is the whole reason the acceptance is
 * fixed in advance. The [+12]/[+24] gates are what kill those coincidences.
 *
 * On godzilla the answer must be (0x7bad88, 0xe0) with 9. Bounded to the low
 * 16 MB where a statically allocated board array lives on both titles (godzilla
 * 0x7bad88, ST static ends 0x8439dc) - the huge high mappings are all heap and
 * coincidence, and sweeping them is what made the first cut O(3 GB x strides).
 *
 * Gated behind PAD_NB_STRIDE_SWEEP=1 and run ONCE per process. */
#define NB_SWEEP_HI 0x1000000u
static int nb_sweep_on(void)
{
    static int on = -1;
    if (on == -1) {
        char *q = getenv("PAD_NB_STRIDE_SWEEP");
        on = q && *q == '1';
    }
    return on;
}

/* Accumulated across every rw region of ONE walk; reported by
 * nb_sweep_report(), which also latches sw_swept so the sweep runs exactly
 * once per process. nb_scan_objs() is re-entered on every dump tick while it
 * keeps failing, and an O(range x strides) scan on each of those would be its
 * own denial of service. */
static unsigned sw_best_a, sw_best_s, sw_best_n, sw_hits, sw_lo, sw_hi;
static int sw_swept;

static void nb_stride_sweep(unsigned lo, unsigned hi)
{
    unsigned a, s, best_a = 0, best_s = 0, best_n = 0, hits = 0;

    if (hi > NB_SWEEP_HI) hi = NB_SWEEP_HI;          /* low 16 MB only */
    if (lo >= hi) return;
    if (!sw_lo || lo < sw_lo) sw_lo = lo;
    if (hi > sw_hi) sw_hi = hi;
    for (a = lo; a + 32u * 0x200u <= hi; a += 4) {
        const unsigned char *p = (const unsigned char *)(unsigned long)a;
        if (p[0] != 0) continue;         /* slot 0 self-labels as 0 (cheap) */
        for (s = 0x80; s <= 0x200; s += 4) {
            unsigned n = nb_objs_shape_ok_s(a, s);
            if (n >= NB_OBJS_MIN) {
                hits++;
                if (n > best_n) { best_n = n; best_a = a; best_s = s; }
            }
        }
    }
    sw_hits += hits;
    if (best_n > sw_best_n) {
        sw_best_n = best_n; sw_best_a = best_a; sw_best_s = best_s;
    }
}

/* Called once the whole walk is done, so the verdict covers every rw region
 * rather than whichever one happened to be last. */
static void nb_sweep_report(void)
{
    char m[220];
    if (sw_swept || !nb_sweep_on()) return;
    sw_swept = 1;
    if (sw_best_n) {
        unsigned i, k;
        snprintf(m, sizeof m,
                 "[nbsweep] self-labelling array: base=0x%08x stride=0x%x "
                 "slots=%u (%u candidate(s) scored >=5 over 0x%08x-0x%08x)\n",
                 sw_best_a, sw_best_s, sw_best_n, sw_hits, sw_lo, sw_hi);
        logmsg(m);
        /* WHAT IS IN IT. The count alone cannot tell a real board array from a
         * coincidence that happens to pass the shape test; the node ids and
         * statuses can. A board array's in-use slots carry the title's DECLARED
         * node ids (ST: 0,1,2,4,8,9,12) - anything else is a false positive of
         * a wider struct search, and saying which is the whole point. */
        for (i = 0; i < 32; i++) {
            const unsigned char *o = (const unsigned char *)(unsigned long)
                                     (sw_best_a + i * sw_best_s);
            unsigned st;
            if (!*(const unsigned *)(o + 12)) continue;        /* not in use */
            st = *(const unsigned *)(o + 24);
            k = (unsigned)snprintf(m, sizeof m,
                     "[nbsweep]   slot %2u node %2u status %u flags=%08x "
                     "ver=%u.%u.%u raw:", i, o[0], st,
                     *(const unsigned *)(o + 4), o[28], o[29], o[30]);
            {
                unsigned j;
                for (j = 0; j < 32 && k < sizeof m - 4; j++)
                    k += (unsigned)snprintf(m + k, sizeof m - k, "%s%02x",
                                            (j % 4) ? "" : " ", o[j]);
            }
            snprintf(m + k, sizeof m - k, "\n");
            logmsg(m);
        }
    } else {
        snprintf(m, sizeof m,
                 "[nbsweep] NO self-labelling array at ANY stride 0x80-0x200 "
                 "over 0x%08x-0x%08x - so the board table is not merely a "
                 "DIFFERENT SIZE on this title, it is not populated at all\n",
                 sw_lo, sw_hi);
        logmsg(m);
    }
}

static unsigned nb_scan_objs_walk(unsigned *best_out, unsigned *near, unsigned *near_n)
{
    char buf[8192];
    int fd, n;
    int (*ro)(const char *, int, ...) = dlsym(RTLD_NEXT, "open");
    long (*rr)(int, void *, unsigned long) = dlsym(RTLD_NEXT, "read");
    int (*rc)(int) = dlsym(RTLD_NEXT, "close");
    unsigned best = 0, best_n = 0;

    if (!ro || !rr) return 0;
    fd = ro("/proc/self/maps", 0, 0);
    if (fd < 0) return 0;
    sw_scan_fd = fd;      /* published so an aborted scan can close it */
    while ((n = (int)rr(fd, buf, sizeof buf - 1)) > 0) {
        char *line = buf, *end = buf + n;
        buf[n] = 0;
        while (line < end) {
            char *nl = line, *p = line;
            unsigned long lo = 0, hi = 0;
            while (nl < end && *nl != '\n') nl++;
            if (nl >= end) break;
            *nl = 0;
            while (*p && *p != '-') {
                int c = *p++;
                if (c >= '0' && c <= '9') c -= '0';
                else if (c >= 'a' && c <= 'f') c -= 'a' - 10;
                else break;
                lo = lo * 16 + (unsigned long)c;
            }
            if (*p == '-') {
                p++;
                while (*p && *p != ' ') {
                    int c = *p++;
                    if (c >= '0' && c <= '9') c -= '0';
                    else if (c >= 'a' && c <= 'f') c -= 'a' - 10;
                    else break;
                    hi = hi * 16 + (unsigned long)c;
                }
            }
            if (hi > lo && hi - lo < 0x4000000UL && lo >= 0x8000UL
                && hi < 0xf0000000UL && p[0] == ' ' && p[1] == 'r'
                && p[2] == 'w') {
                unsigned a, span = 32u * NB_OBJ_SZ;
                /* item 52: the stride-independent cross-check, off by default
                 * and ONCE per process (sw_swept) - see its comment. */
                if (nb_sweep_on() && !sw_swept)
                    nb_stride_sweep((unsigned)lo, (unsigned)hi);
                for (a = (unsigned)lo; (unsigned long)a + span <= hi; a += 4) {
                    unsigned cnt = nb_objs_shape_ok(a);
                    if (!cnt) continue;
                    if (cnt < NB_OBJS_MIN) {          /* weak: keep scanning */
                        if (near && cnt > *near_n) { *near = a; *near_n = cnt; }
                        continue;
                    }
                    if (cnt > best_n) { best = a; best_n = cnt; }
                    a += span - 4;      /* a real hit consumes its own array */
                }
            }
            line = nl + 1;
        }
    }
    if (rc) rc(fd);
    sw_scan_fd = -1;
    nb_sweep_report();          /* item 52: verdict over ALL regions, once */
    if (best_out) *best_out = best_n;
    return best;
}

/* The guard, worn by BOTH maps walks - see scan_guard_check(). The run that
 * proved it needed to be: with the switch scan guarded and this one not, the
 * 2026-08-18 run died at 16 s with pc inside nb_objs_shape_ok's [+12] read -
 * the same region-freed-mid-walk race, in the walk whose own comment claimed
 * the snapshot could be trusted. The page cache is NOT armed here (this walk
 * never calls addr_readable); only the jump buffer and the latch are. */
static unsigned nb_scan_objs(unsigned *best_out, unsigned *near, unsigned *near_n)
{
    unsigned ret;

    if (!segv_guard_ready)
        return nb_scan_objs_walk(best_out, near, near_n);
    if (__sync_lock_test_and_set(&scan_guard_busy, 1)) {
        if (best_out) *best_out = 0;
        return 0;      /* another guarded scan is mid-flight; asked again */
    }
    if (sigsetjmp(sw_scan_env, 1) == 0) {
        sw_scan_tid = syscall(224);
        ret = nb_scan_objs_walk(best_out, near, near_n);
    } else {
        char m[160];
        int (*rc)(int) = dlsym(RTLD_NEXT, "close");
        if (sw_scan_fd >= 0 && rc) rc(sw_scan_fd);
        sw_scan_fd = -1;
        snprintf(m, sizeof m,
                 "[nbobj] scan aborted by a fault (pc=0x%lx addr=0x%lx) - a "
                 "region left while we walked it; asked again later\n",
                 (unsigned long)sw_scan_pc, (unsigned long)sw_scan_addr);
        logmsg(m);
        if (best_out) *best_out = 0;
        ret = 0;
    }
    sw_scan_tid = 0;
    __sync_lock_release(&scan_guard_busy);
    return ret;
}

/* ★ ITEM 52: WATCH the sweep's found array OVER TIME. The sweep reports once,
 * early, so it shows the boards' initial flags; this dumps the same (base,
 * stride) on every PAD_NB_DUMP tick, so the boards' LIFETIME is visible - in
 * particular whether the playfield boards ever reach flags bit 1 (the ~10 Hz
 * "serviced" heartbeat) the way godzilla's do, or stay stuck at flags=1. It is
 * the missing instrument: nb_dump_objs() reads a fixed 0xe0 stride and so is
 * blind to ST's 0x98 struct. Compact, one line per tick: node=flags/status. */
static void nb_sweep_watch(void)
{
    char m[300];
    unsigned i, k;
    if (!nb_sweep_on() || !sw_best_a || !sw_best_s) return;
    k = (unsigned)snprintf(m, sizeof m, "[nbwatch] 0x%08x/0x%x:",
                           sw_best_a, sw_best_s);
    for (i = 0; i < 32 && k < sizeof m - 24; i++) {
        const unsigned char *o = (const unsigned char *)(unsigned long)
                                 (sw_best_a + i * sw_best_s);
        if (!*(const unsigned *)(o + 12)) continue;
        k += (unsigned)snprintf(m + k, sizeof m - k, " n%u=f%us%u",
                                o[0], *(const unsigned *)(o + 4),
                                *(const unsigned *)(o + 24));
    }
    snprintf(m + k, sizeof m - k, "\n");
    logmsg(m);
}

/* item 52: FORCE A BOARD'S STATUS HEALTHY, to test the readiness gate.
 *
 * PAD_NB_FORCE_STATUS=<id>[,<id>...]  or  =all
 *
 * WHY, and it is a specific mechanism rather than a shotgun (the shotgun was
 * the first cut of this probe and it tested nothing in particular):
 * stranger_things' boot-readiness check at 0x205328 walks the board array and,
 * for each board with a directory entry whose type is not 38/1:
 *
 *      205388  ldr r0,[r3,#24] ; cmp r0,#2   -> status==2 is the OK path
 *      205394  ldr r0,[r2]     ; ands r0,#4  -> else, is the node OPTIONAL?
 *      2053a0  ldr r0,[r3,#4]  ; tst r0,#2   -> optional AND found...
 *      2053a8  movne r4,#0                   -> ...but not status 2 = NOT READY
 *
 * i.e. an OPTIONAL board that IS present but is NOT graded 2 pins readiness at
 * false forever. ST's node 4 (QR SCANNER, directory attr 0x4 = optional) is
 * graded status 7 and answers the bus, so it lands exactly there - and that
 * status is OUR doing: the shim has node 4 claim godzilla's node4 firmware
 * (124.107.0), which nbdir.py flags in a comment as "reproduced not corrected
 * ... worth revisiting if node 4 misbehaves". This forces the status the game
 * grades, so a run says whether that gate is what holds the boot.
 *
 * Requires PAD_NB_STRIDE_SWEEP=1 (the sweep resolves base/stride). Fields as
 * nb_sweep_watch reads them: o+0 id, o+12 in-use, o+24 status. Deliberately
 * does NOT touch flags: bit 1 is what the LOCATING screen's naming predicate
 * reads, and moving both at once would confound the two questions. */
static int nb_force_status_want(unsigned id)
{
    static int state = -1;          /* -1 unread, 0 off, 1 all, 2 list */
    static unsigned char want[64];
    if (state == -1) {
        const char *p = getenv("PAD_NB_FORCE_STATUS");
        state = 0;
        if (p && *p) {
            if (p[0] == 'a')                   /* "all" */
                state = 1;
            else {
                unsigned v = 0;
                int any = 0;
                state = 2;
                for (;; p++) {
                    if (*p >= '0' && *p <= '9') { v = v*10 + (unsigned)(*p-'0'); any = 1; }
                    else {
                        if (any && v < 64) want[v] = 1;
                        v = 0; any = 0;
                        if (!*p) break;
                    }
                }
            }
        }
    }
    if (state == 0) return 0;
    if (state == 1) return 1;
    return id < 64 && want[id];
}

static void nb_force_status(void)
{
    static int said;
    unsigned i;
    if (!sw_best_a || !sw_best_s) return;
    for (i = 0; i < 32; i++) {
        unsigned char *o = (unsigned char *)(unsigned long)
                           (sw_best_a + i * sw_best_s);
        unsigned id;
        if (!*(const unsigned *)(o + 12)) continue;   /* in-use slots only */
        id = o[0];
        if (!nb_force_status_want(id)) continue;
        if (*(const unsigned *)(o + 24) == 2u) continue;
        if (!said) {
            char m[160];
            said = 1;
            snprintf(m, sizeof m, "[nbforce] forcing status 2 (was %u) on node "
                     "%u and any other PAD_NB_FORCE_STATUS node\n",
                     *(const unsigned *)(o + 24), id);
            logmsg(m);
        }
        *(unsigned *)(o + 24) = 2u;
    }
}

/* The best sub-threshold candidate the last scan saw, for nb_dump_objs() to
 * report. Zero when the scan succeeded or saw nothing at all. */
static unsigned nb_near_base, nb_near_n;

/* Resolve once GENUINELY FOUND, and never cache a miss: the array is populated
 * as the game brings the bus up, so an early call must be allowed to fail and
 * be asked again. (TITLE_ADDR caches 0 forever, which is right for a fixed
 * address and wrong for a scan.) */
/* ★ ITEM 52: A MISS IS RATE-LIMITED, and this one line of policy was the
 * whole of stranger_things' unplayability. "Never cache a miss" (below) was
 * right about WHY - the array fills in as bring-up runs - and catastrophic
 * about HOW: NB_OBJS is read by nb_nodes_add_boards() at the top of EVERY
 * node-bus service cycle, ON THE GAME'S BUS THREAD, inside its `00` poll.
 * On a title whose array never resolves by shape (ST's is dense, not
 * self-labelling) that is a full /proc/self/maps heap walk per cycle - and
 * the walk is the whole cycle: measured 2026-08-18, `game:nodebus` was in
 * state R (running, wchan 0, no syscall) in 30 of 30 samples over 6 s while
 * the game got ONE service pass every ~2.8 s and every switch closure waited
 * up to 2.9 s for a scan. Godzilla resolves on the first try and caches
 * forever, which is why the labelled example never showed it. Every earlier
 * theory - node 4's silence, a bus timeout, a game-side gate, the video
 * churn - was measured and died; the profiler-by-/proc named the thread and
 * this function is what runs on it.
 *
 * Policy: after a miss, do not scan again for NB_OBJS_RETRY_MS of wall
 * clock, and after NB_OBJS_MAX_MISSES give up for the run. The numbers are
 * sized to the cost: ONE scan is ~2.8 s of the bus thread on ST, so a 2 s
 * retry (the first cut) still left the thread mostly scanning for the first
 * minute - measured, the last late closures landed at 60 s. Ten seconds
 * apart, three tries, covers bring-up (the array is populated within ~15 s
 * on godzilla) and then stops. A title whose array appears late is found on
 * a retry, and the near-miss report keeps its data. */
#define NB_OBJS_RETRY_MS   10000ul   /* one scan is ~2.8 s of the bus thread */
#define NB_OBJS_MAX_MISSES 3         /* bring-up populates within ~15 s */
static unsigned nb_objs_addr(void)
{
    static unsigned found;
    static unsigned misses;
    static unsigned long next_try_ms;
    unsigned a, cnt = 0;
    char m[200];

    if (found) return found;
    a = a_nb_objs();                       /* PAD_NB_OBJS, else the built-in */
    if (getenv("PAD_NB_OBJS")) {           /* an explicit override is obeyed */
        found = a;
        return found;
    }
    if (misses >= NB_OBJS_MAX_MISSES) return 0;       /* gave up for the run */
    if (next_try_ms && pad_ms() < next_try_ms) return 0;   /* too soon */
    {
        unsigned near = 0, near_n = 0;
        a = nb_scan_objs(&cnt, &near, &near_n);
        if (!a) {
            misses++;
            next_try_ms = pad_ms() + NB_OBJS_RETRY_MS;
            if (misses == NB_OBJS_MAX_MISSES) {
                snprintf(m, sizeof m, "[nbobj] no self-labelling board array "
                         "after %u scans - not scanning again this run (the "
                         "scan runs on the game's bus thread; see "
                         "nb_objs_addr)\n", misses);
                logmsg(m);
            }
            /* Hand the near miss to nb_dump_objs() to REPORT, rather than
             * printing a bare address here. On stranger_things this branch is
             * the whole result of the run - 11 ticks of "no table", best
             * candidate 2 slots at 0x0087429c - and "2 slots" alone does not
             * say WHICH boards, which is the next question every time. The
             * reporting lives in one place and below nb_status_name(), so it
             * can name the statuses too. */
            nb_near_base = near;
            nb_near_n = near_n;
            return 0;
        }
        nb_near_base = 0;
    }
    found = a;
    /* THE LABELLED-EXAMPLE CHECK, printed by the rig itself: on godzilla_pro
     * the scan must land on the address this file has always hard-coded. Any
     * other title has nothing to compare against, and says so. */
    snprintf(m, sizeof m,
             "[nbobj] board objects found by shape at 0x%08x, %u slots in use "
             "(built-in godzilla address 0x%08x: %s)\n",
             a, cnt, 0x7bad88u,
             a == 0x7bad88u ? "AGREES"
                            : "differs - correct unless this IS godzilla_pro");
    logmsg(m);
    return found;
}

/* ★ ITEM 52: IS THIS THE TITLE THE BUILT-IN NODE-BUS ADDRESSES WERE MEASURED
 * ON? NB_TABLE, NB_RECORDS and NB_HEXLIST are Godzilla Pro 1.15.0 literals -
 * two of them plain #defines with no override at all - and on any other title
 * they point into somebody else's data.
 *
 * That is not merely useless, it is DANGEROUS, and this pass proved it: with
 * PAD_NB_DUMP on, stranger_things read NB_HEXLIST, got a plausible-looking
 * 0x0086ce9c that passes every range check nb_dump_hexlist() makes, walked it,
 * and the GUEST SEGFAULTED. Item 51's ST run never crashed because it never
 * set PAD_NB_DUMP; turning the diagnostic on is what killed the title it was
 * meant to diagnose.
 *
 * The gate is the by-shape scan agreeing with the built-in base, which is a
 * MEASURED test rather than "is this address readable" - the readable test is
 * exactly the trap that once had the shim reading a switch table out of
 * another title's memory. */
static int nb_addrs_are_this_title(void)
{
    return nb_objs_addr() == 0x7bad88u;
}

#define NB_OBJS   nb_objs_addr()

static const char *nb_status_name(unsigned s)
{
    static const char *n[12] = {
        "No Errors", "Not Responding", "Not Registered", "Collision",
        "Not Initialized", "Version Mismatch", "Hex Image Version not Found",
        "Checksum", "Runtime Info", "Boot", "Ok", "Unused"
    };
    return s < 12 ? n[s] : "?";
}

/* What the near miss actually CONTAINS. "2 slots in use" is where the last ST
 * run stopped, and the next question was immediately "which two, and saying
 * what?" - so answer it in the same line rather than costing another run.
 * Printed ONCE: 11 identical ticks of this would be noise, and the array does
 * not change while the game is stuck. */
static void nb_report_near(void)
{
    char line[320];
    unsigned i, k;
    static int said;
    if (said || !nb_near_base) return;
    said = 1;
    k = (unsigned)snprintf(line, sizeof line,
                           "[nbobj] near miss at 0x%08x: %u self-consistent "
                           "slot(s), below the %u needed to act on -",
                           nb_near_base, nb_near_n, NB_OBJS_MIN);
    for (i = 0; i < 32 && k < sizeof line - 48; i++) {
        const unsigned char *o = (const unsigned char *)(unsigned long)
                                 (nb_near_base + i * NB_OBJ_SZ);
        unsigned st;
        if (!*(const unsigned *)(o + 12)) continue;
        st = *(const unsigned *)(o + 24);
        k += (unsigned)snprintf(line + k, sizeof line - k,
                                " slot %u node %u status %u (%s)",
                                i, o[0], st, nb_status_name(st));
    }
    snprintf(line + k, sizeof line - k, "\n");
    logmsg(line);
}

static void nb_dump_objs(void)
{
    char line[400];
    unsigned id;
    if (!NB_OBJS) {
        logmsg("[nbobj] no node-object table known for this title\n");
        nb_report_near();
        return;
    }
    logmsg("[nbobj] --- node board objects ---\n");
    for (id = 0; id < 32; id++) {
        const unsigned char *o =
            (const unsigned char *)(unsigned long)(NB_OBJS + id * NB_OBJ_SZ);
        unsigned status, present;
        int i, k;
        present = *(const unsigned *)(o + 12);
        if (!present) continue;
        status = *(const unsigned *)(o + 24);
        /* +144 is a halfword and it is the LAST thing keeping slot 2 on screen.
         * 0x39d554 special-cases the board whose [+0] is 2 when it sets the
         * flags: every other board gets flags = 1 unconditionally, but slot 2
         * gets flags = (halfword at [+144] != 0). With it zero, bit0 stays
         * clear, (flags & 3) can never reach 3, the board is never suppressed,
         * and it renders "Not Registered" forever. The board init at
         * 0x39d3ac..0x39d3d4 zeroes +124 through +143 and stops deliberately
         * short of +144, so something else is meant to fill it in. */
        k = snprintf(line, sizeof line,
                     "[nbobj] slot %2u node %2u flags=%08x status=%u %-28s "
                     "ver=%u.%u.%u p144=%u p146=%u f147=%u f148=%u "
                     "desc=%08x hex=%08x rec:",
                     id, o[0], *(const unsigned *)(o + 4), status,
                     nb_status_name(status), o[28], o[29], o[30],
                     *(const unsigned short *)(o + 144), o[146],
                     o[147], o[148], *(const unsigned *)(o + 32),
                     *(const unsigned *)(o + 88));
        for (i = 0; i < 48 && k < (int)sizeof line - 4; i++)
            k += snprintf(line + k, sizeof line - k, "%s%02x",
                          (i % 4) ? "" : " ", o[40 + i]);
        snprintf(line + k, sizeof line - k, "\n");
        logmsg(line);
    }
}

/* Per-command reply-length census, unbudgeted. The [nb] log is line-limited and
 * the interesting commands repeat thousands of times, so counting is the only
 * way to see the shape of the traffic over a whole run. It matters for `fe` in
 * particular: 0x5a2d84 asks for an 11-byte identity payload (wire reply_len 13)
 * and only on FAILURE retries with a 10-byte one (reply_len 12), so a non-zero
 * count at 12 is a direct readout of "the identity exchange is failing". */
static unsigned nb_cmd_n[256];
static unsigned nb_cmd_len[256][40];

static void nb_count(unsigned char cmd, unsigned long n)
{
    nb_cmd_n[cmd]++;
    if (n < 40) nb_cmd_len[cmd][n]++;
}

/* The HEX IMAGE REGISTRY, which is what actually blocks the boards.
 *
 * The state machine's last gate before it can grade a board is
 *     r0 = 0x44880c(board[+88], desc[+8])
 *     if (!r0 || !r0[28] || !r0[48]) -> status 4 (renders "Runtime Info")
 * and 0x44880c is a plain linked-list find: head at [0x7e1b98], next at
 * [node+60], matching node[0] == board[+88] and node[4] == desc[+8]. So a null
 * head, or a board whose [+88] key is 0, both dead-end in the same place.
 * Walking the list here answers which of the two it is without a debugger. */
#define NB_HEXLIST 0x7e1b98u

static void nb_dump_hexlist(void)
{
    char line[300];
    unsigned node;
    int n = 0;
    node = *(const unsigned *)(unsigned long)NB_HEXLIST;
    snprintf(line, sizeof line, "[nbhex] head [0x%08x] = 0x%08x\n", NB_HEXLIST, node);
    logmsg(line);
    while (node && n++ < 32) {
        const unsigned *w;
        if (node < 0x400000u || node >= 0xf0000000u || (node & 3)) {
            snprintf(line, sizeof line, "[nbhex]   0x%08x (not readable)\n", node);
            logmsg(line);
            break;
        }
        w = (const unsigned *)(unsigned long)node;
        /* Node layout, from 0x448558 (builder) and 0x5a8110 (Intel HEX parser):
         *   [+0]  CRC32 of the node type name  = the key board[+88] must equal
         *   [+4]  LPC part class 1..7          = the key desc[+8] must equal
         *   [+8]  char* path to the .hex file
         *   [+12..59] the parsed image struct, so in NODE offsets:
         *   [+28] data buffer (indexed by ABSOLUTE flash address)
         *   [+40] image-kind flag, must be 1 (set only when min addr == 0x1000)
         *   [+44] min flash address
         *   [+48] span; 0x5a8644 needs it > 11
         *   [+60] next
         * The .hex files are ENCRYPTED (record types 06/07), so the version is
         * only readable here, after the game has decrypted them into [+28].
         * 0x5a8644 reads buf[min+8]=variant and buf[min+9..11]=major.minor.patch
         * and 0x1d5780 compares those against the board's identity, which this
         * shim invents - so these four bytes are what PAD_NB_FW must match. */
        {
            const char *path = "?";
            unsigned buf = w[7], minad = w[11], span = w[12], kind = w[10];
            char ver[80];
            if (w[2] >= 0x8000u && w[2] < 0xf0000000u)
                path = (const char *)(unsigned long)w[2];
            ver[0] = 0;
            if (buf >= 0x8000u && buf < 0xf0000000u && (int)span > 11) {
                const unsigned char *b = (const unsigned char *)(unsigned long)buf;
                snprintf(ver, sizeof ver, "  variant=%02x VERSION=%u.%u.%u",
                         b[minad + 8], b[minad + 9], b[minad + 10], b[minad + 11]);
            }
            snprintf(line, sizeof line,
                     "[nbhex]   key0=%08x class=%u kind=%d min=%04x span=%d%s  %s\n",
                     w[0], w[1], (int)kind, minad, (int)span, ver, path);
        }
        logmsg(line);
        node = w[15];
    }
}

static void nb_dump_census(void)
{
    char line[400];
    unsigned c;
    logmsg("[nbcen] --- command census (reply lengths) ---\n");
    for (c = 0; c < 256; c++) {
        int k, i;
        if (!nb_cmd_n[c]) continue;
        k = snprintf(line, sizeof line, "[nbcen] %02x n=%-6u", c, nb_cmd_n[c]);
        for (i = 0; i < 40 && k < (int)sizeof line - 16; i++)
            if (nb_cmd_len[c][i])
                k += snprintf(line + k, sizeof line - k, " len%d=%u", i,
                              nb_cmd_len[c][i]);
        snprintf(line + k, sizeof line - k, "\n");
        logmsg(line);
    }
}

/* PAD_NB_POKE=1 - CALIBRATION ONLY, not a fix.
 *
 * The board object's [+24] is written by the state machine at 0x1d550c with the
 * literals 2,3,4,6,7,8,9, which looks exactly like the 12-entry status enum. It
 * is not, or not directly: with [+24] == 4 on all eight polled boards the Tech
 * Alerts screen renders "Runtime Info", which is index 8 in the enum as the
 * handoff recorded it. Rather than guess at the offset, write a DIFFERENT value
 * into each board and read the eight labels off one frame - that calibrates the
 * whole mapping in a single run. The poll loop rewrites [+24] constantly, so
 * the poke has to be re-applied on every bus write to win the race. */
static const unsigned char nb_poke_tbl[16] = {
    /* 0 */ 0xff, /* 1 */ 8, /* 2 */ 9, /* 3 */ 0xff,
    /* 4 */ 10,   /* 5 */ 0xff, /* 6 */ 0xff, /* 7 */ 2,
    /* 8 */ 1,    /* 9 */ 0,    /* 10 */ 0xff, /* 11 */ 0xff,
    /* 12 */ 3,   /* 13 */ 0xff, /* 14 */ 4,   /* 15 */ 0xff
};

static void nb_maybe_poke(void)
{
    static int on = -1;
    unsigned id;
    if (on == -1) { char *p = getenv("PAD_NB_POKE"); on = p && p[0] == '1'; }
    if (!on || !NB_OBJS) return;
    for (id = 0; id < 16; id++) {
        unsigned char *o = (unsigned char *)(unsigned long)(NB_OBJS + id * NB_OBJ_SZ);
        if (nb_poke_tbl[id] == 0xff) continue;
        if (!*(const unsigned *)(o + 12)) continue;
        *(unsigned *)(o + 24) = nb_poke_tbl[id];
    }
}

/* FLAGS WATCHER. The periodic [nbobj] dump samples board[+4] on node bus writes
 * and consistently shows 0x3, yet the Tech Alerts screen renders those same
 * boards with bit1 CLEAR. Sampling cannot settle that - a value that is set
 * most of the time and clear at the one instant that matters looks identical to
 * a value that is always set. So watch for CHANGES instead: called on every bus
 * write, it prints only transitions, which turns "what is the flag" into "what
 * is the flag's history" and shows whether anything clears it at all.
 *
 * Also prints the global at 0x706464, because the suppression condition is
 *     skip if status in {2,7} AND ((flags & 3) == 3 OR [0x706464] == 0)
 * so if that global is 0 the flags stop mattering entirely. */
TITLE_ADDR(a_nb_alert_gate, "PAD_NB_ALERT_GATE", 0x706464u)
#define NB_ALERT_GATE a_nb_alert_gate()

static void nb_watch_flags(void)
{
    static int on = -1;
    static unsigned last[32];
    static int primed;
    static unsigned last_gate = 0xffffffffu;
    unsigned id, gate;
    char line[200];

    if (on == -1) { char *p = getenv("PAD_NB_WATCH"); on = p && p[0] == '1'; }
    if (!on || !NB_OBJS) return;

    gate = tread(NB_ALERT_GATE);
    if (gate != last_gate) {
        snprintf(line, sizeof line, "[nbflag] [0x%06x] alert gate %u -> %u\n",
                 NB_ALERT_GATE, last_gate, gate);
        logmsg(line);
        last_gate = gate;
    }

    for (id = 0; id < 32; id++) {
        const unsigned char *o =
            (const unsigned char *)(unsigned long)(NB_OBJS + id * NB_OBJ_SZ);
        unsigned f, st;
        if (!*(const unsigned *)(o + 12)) continue;
        f  = *(const unsigned *)(o + 4);
        st = *(const unsigned *)(o + 24);
        /* Fold the status in, so a flags line also says whether the board was
         * suppressible at that moment - the two only matter together. */
        f |= st << 16;
        if (primed && f == last[id]) continue;
        snprintf(line, sizeof line,
                 "[nbflag] slot %2u flags=%u%u status=%u  %s\n",
                 id, (f >> 1) & 1, f & 1, (f >> 16) & 0xffff,
                 ((f & 3) == 3) ? "SUPPRESSIBLE (no alert line)"
                                : ((f & 1) ? "renders Not Responding"
                                           : "renders Not Registered"));
        logmsg(line);
        last[id] = f;
    }
    primed = 1;
}

/* ------------------------------------------------------------------------
 * THE ALERT PROVIDER LIST  (PAD_ALERT_DUMP)
 *
 * Every line on the Tech Alerts screen comes from a CALLBACK PROVIDER, not
 * from a string the raiser formatted at the raise site. That is why four
 * static searches for "GAME VALIDATION ERROR" came back empty: nothing in
 * .text ever names the message row.
 *
 * 0x2176e0 is the registrar. It mallocs 20 bytes and links the node into a
 * single list sorted by the priority byte, head at [0x7ac834]:
 *
 *     +0   fn       int fn(std::string *out, int idx)   1-BASED idx
 *                   returns non-zero while entry idx exists; with out != 0
 *                   it also formats that entry's line
 *     +4   fn2      per-alert action, read by 0x217948(n)
 *     +8   msgid    u16, read by 0x2179bc(n)
 *     +10  priority u8, the sort key
 *     +12  arg      read by 0x217a30(n)
 *     +16  next
 *
 * The shim shares the guest's address space, so the whole list is a plain
 * memory walk, and fn(0, idx) is exactly what the game's own counter at
 * 0x217788 does - so asking a provider "how many entries do you have right
 * now" is the game's own contract, not a new one invented here.
 * ------------------------------------------------------------------------ */
/* All five are GODZILLA PRO 1.15.0 addresses and all five are dereferenced, so
 * all five go through TITLE_ADDR: on a title whose addresses are unknown they
 * resolve to 0 and the alert text simply is not available, instead of the game
 * dying inside a log line. See the TITLE_ADDR block for the whole argument. */
TITLE_ADDR(a_alert_head, "PAD_ALERT_HEAD", 0x7ac834u)  /* the list head       */
TITLE_ADDR(a_msg_count,  "PAD_MSG_COUNT",  0x5ec0c8u)  /* u32, 3949           */
TITLE_ADDR(a_msg_remap,  "PAD_MSG_REMAP",  0x7b9654u)  /* msgid -> table index*/
TITLE_ADDR(a_msg_ptrs,   "PAD_MSG_PTRS",   0x744c60u)  /* index -> char *[5]  */
TITLE_ADDR(a_msg_lang,   "PAD_MSG_LANG",   0x708330u)  /* language slot       */

#define ALERT_HEAD  a_alert_head()
#define MSG_COUNT   a_msg_count()
#define MSG_REMAP   a_msg_remap()
#define MSG_PTRS    a_msg_ptrs()
#define MSG_LANG    a_msg_lang()

/* Every one of the tables above present and mapped. The readers below are
 * pure reads through several indirections and each one starts here. */
static int title_tables_ok(void)
{
    return MSG_COUNT && MSG_REMAP && MSG_PTRS && MSG_LANG;
}

/* msgid -> text, done by hand rather than by calling 0x34a764, because that
 * function's out-of-range path calls the game's error reporter. This is a
 * pure read: the same three indirections, with every pointer bounds-checked. */
static const char *msg_text(unsigned msgid)
{
    unsigned count;
    if (!title_tables_ok()) return 0;
    count = tread(MSG_COUNT);
    unsigned rt    = tread(MSG_REMAP);
    unsigned lang  = tread(MSG_LANG);
    unsigned idx, row, s;
    if (!count || count > 0x20000u || !rt) return 0;
    if (rt < 0x8000u || rt >= 0x10000000u) return 0;
    if (msgid >= count) return 0;
    idx = ((const unsigned short *)(unsigned long)rt)[msgid];
    if (idx >= count) return 0;
    row = ((const unsigned *)(unsigned long)MSG_PTRS)[idx];
    if (row < 0x8000u || row >= 0x800000u) return 0;
    s = ((const unsigned *)(unsigned long)row)[0];
    if (lang && lang < 5) {
        unsigned t = ((const unsigned *)(unsigned long)row)[lang];
        if (t >= 0x8000u && t < 0x800000u) s = t;
    }
    if (s < 0x8000u || s >= 0x800000u) return 0;
    return (const char *)(unsigned long)s;
}

/* Message text carries real newlines ("GAME VALIDATION ERROR\n#2 UPDATE SD
 * CARD"), which would split one dump line into two and break every grep. */
static const char *msg_esc(const char *s)
{
    static char b[240];
    int i = 0;
    if (!s) return "(no text)";
    while (*s && i < (int)sizeof b - 3) {
        if (*s == '\n') { b[i++] = '\\'; b[i++] = 'n'; s++; }
        else if (*s == '\r') { b[i++] = '\\'; b[i++] = 'r'; s++; }
        else if ((unsigned char)*s < 32) { b[i++] = '.'; s++; }
        else b[i++] = *s++;
    }
    b[i] = 0;
    return b;
}

/* Ask one provider how many entries it is claiming right now. PAD_ALERT_PROBE
 * gates it because it CALLS INTO THE GAME from the node bus thread, and the
 * renderer walks the same list every frame. Pure-read fields come out either
 * way, so a crash here costs the counts, not the dump. */
static int alert_probe_on(void)
{
    static int on = -1;
    if (on == -1) { char *p = getenv("PAD_ALERT_PROBE"); on = (p && *p != '0'); }
    return on;
}

static void alert_dump(void)
{
    char line[420];
    unsigned n;
    int guard = 0, probe = alert_probe_on(), total = 0;

    if (!ALERT_HEAD) {
        logmsg("[alert] no provider-list address known for this title\n");
        return;
    }
    n = *(const unsigned *)(unsigned long)ALERT_HEAD;

    snprintf(line, sizeof line,
             "[alert] --- providers, head [0x%08x] = 0x%08x ---\n", ALERT_HEAD, n);
    logmsg(line);
    while (n >= 0x8000u && n < 0x10000000u && !(n & 3) && guard++ < 64) {
        const unsigned      *w = (const unsigned *)(unsigned long)n;
        const unsigned char *b = (const unsigned char *)(unsigned long)n;
        unsigned fn = w[0], fn2 = w[1], arg = w[3], next = w[4];
        unsigned msgid = *(const unsigned short *)(b + 8);
        unsigned prio  = b[10];
        int active = -1;
        if (probe && fn >= 0x16a00u && fn < 0x5d3168u) {
            int (*f)(void *, int) = (int (*)(void *, int))(unsigned long)fn;
            int i;
            active = 0;
            for (i = 1; i <= 64; i++) { if (!f((void *)0, i)) break; active++; }
            total += active;
        }
        snprintf(line, sizeof line,
                 "[alert] fn=0x%06x fn2=0x%06x msgid=%-5u prio=%-3u arg=0x%08x "
                 "active=%-3d \"%s\"\n",
                 fn, fn2, msgid, prio, arg, active, msg_esc(msg_text(msgid)));
        logmsg(line);
        n = next;
    }

    /* The other half of the picture: what the RENDERER sees. 0x217788 is the
     * total count and 0x2179bc(i) is entry i's msgid, both 1-based. This says
     * which message rows are on the screen this instant, without a frame. */
    if (probe) {
        int  (*cnt)(void)   = (int (*)(void))(unsigned long)0x217788u;
        int  (*mid)(int)    = (int (*)(int))(unsigned long)0x2179bcu;
        int  (*act)(int)    = (int (*)(int))(unsigned long)0x217948u;
        int  (*ext)(int)    = (int (*)(int))(unsigned long)0x217a30u;
        int c = cnt(), i;
        snprintf(line, sizeof line, "[alert] live entries: %d (walk total %d)\n",
                 c, total);
        logmsg(line);
        for (i = 1; i <= c && i <= 32; i++) {
            unsigned m = (unsigned)mid(i);
            snprintf(line, sizeof line,
                     "[alert]   #%-2d msgid=%-5u fn2=0x%06x arg=0x%08x \"%s\"\n",
                     i, m, (unsigned)act(i), (unsigned)ext(i),
                     msg_esc(msg_text(m)));
            logmsg(line);
        }
    }
}

static void alert_maybe_dump(void)
{
    static int every = -1, n;
    if (every == -1) {
        char *p = getenv("PAD_ALERT_DUMP");
        int v = 0;
        while (p && *p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        every = v;
    }
    if (every <= 0) return;
    if (++n % every) return;
    alert_dump();
}

/* ------------------------------------------------------------------------
 * GAME VALIDATION  (PAD_VAL_DUMP)
 *
 * Alert provider 0x24a018 is the one raising GAME VALIDATION ERROR, and it is
 * a plain read of six fields of one object, V = [0x7b7c30]:
 *
 *     V[+42] in {2,3} -> #1     V[+43] in {2,3} -> #2     V[+44] in {2,3} -> #3
 *     [0x7b9308]  != 0 -> #4    V[+24] or V[+41]==1 -> #5  V[+12]|V[+16] -> #6
 *
 * The message strings are NOT message-table rows: 0x249f60(n) DECRYPTS them
 * out of an obfuscated blob at 0x6438bc into a scratch buffer at 0x7b7bf0 and
 * the provider sprintf's that. Nothing in .text ever names a row, which is why
 * four static searches for the raiser came back empty. n maps 2..7 -> #1..#6.
 *
 * The module's own status line calls the three tracks GE (+42), CE (+43) and
 * ZK (+44) and names the states from 0x66d9d8: 0 "S", 1 "P", 2 "F", 3 "E".
 *
 * ALL THREE TRACKS ARE INITIALISED TO 1 ("P"), NOT 3 ("E") - the module init
 * writes 1 to +42/+43/+44, on BOTH titles, instruction for instruction. A
 * track is set to 3 when its handler STARTS and to 1 or 2 when it finishes,
 * so on this screen "E" means IN PROGRESS at least as often as it means
 * failed. That is why godzilla's #2 "cleared itself" at ~70 s: CE was simply
 * running. Anything that stops the state machine ticking therefore leaves
 * every track reading "P" and SILENCES the banner rather than raising it.
 *
 * ONE OVERRIDE MOVES ALL FOUR, because V, the state byte and the worker
 * context are FIXED OFFSETS from the module base - +0xc0, +0xc5, +0xc8 - and
 * that layout was confirmed identical on a second title (item 62, 2026-08-23).
 * turtles_pro 1.59.0 puts the module at 0x681994 and godzilla_pro 1.15.0 at
 * 0x7b7b70; every landmark in between maps at a constant +0x970f8, and the
 * module's init, provider, decryptor and grade-setters are the same code. So
 * `PAD_VAL_MOD=0x681994` is the whole of what turtles needs, rather than four
 * addresses that could be given inconsistently.
 * ------------------------------------------------------------------------ */
TITLE_ADDR(a_val_mod, "PAD_VAL_MOD", 0x7b7b70u)  /* module globals           */
TITLE_ADDR(a_val_aud, "PAD_VAL_AUD", 0x7b9308u)  /* #4 term, audio block     */

#define VAL_MOD  a_val_mod()    /* module globals                            */
#define VAL_V    (VAL_MOD + 0xc0u)  /* the state object (a pointer to MOD)   */
#define VAL_ST   (VAL_MOD + 0xc5u)  /* the state-machine state               */
#define VAL_CTX  (VAL_MOD + 0xc8u)  /* the worker context                    */
#define VAL_AUD  a_val_aud()    /* the #4 term, inside the audio state block */

static const char *val_state(unsigned s)
{
    static const char *n[4] = { "S ok", "P pending", "F fail", "E error" };
    return s < 4 ? n[s] : "?";
}

/* ------------------------------------------------------------------------
 * SWITCHES AND BALL DEVICES  (PAD_SW_DUMP / PAD_SW_SET)
 *
 * This is the virtual playfield's landing point. The switch subsystem is one
 * struct at 0x7a958c:
 *
 *     [0x7a958c + 0]  entry[]      32 bytes each, indexed by switch id
 *     [0x7a958c + 4]  raw[]        ONE BYTE per switch id, the live state
 *     [0x7e43d8]      count
 *
 * per entry:  +8  cfg     +12 -> a struct whose +16 is the NAME message row
 *             +24 the logical state byte
 * per cfg:    +20 u16 the switch NUMBER printed on the Switch Test screen
 *             +28 u16 flags; bit 2 = polarity, bits 5..6 = hidden from the test
 *
 * 0x1e6d90(sw) reads entry[+24] and inverts it when (cfg[28] & 4) == 0;
 * 0x1e67c4(sw) reads raw[sw] and returns 0 when (cfg[28] & 0x60) != 0.
 * Note `raw` is NOT findable with findref.sh - it is the second field of the
 * struct, so every reference is built as [0x7a958c, #4] and no code ever names
 * 0x7a9590. Two of these globals were nearly missed that way.
 *
 * Ball devices are the other half, because "Device Malfunction" is what the
 * screen shows when a device kicks and no switch answers. Provider 0x3958c8
 * walks a table at 0x7446a4, stride 40, count [0x5ec030], 1-based:
 *     entry+0  -> device object, whose (u16)[+20] bit 0 means MALFUNCTION
 *     entry+32 -> the device's NAME message row
 * ------------------------------------------------------------------------ */
/* ---- THE GAME'S OWN TABLES, WHICH ARE PER TITLE -------------------------
 *
 * Every address here was read out of GODZILLA PRO 1.15.0 and means nothing in
 * another title's binary. That was fine while the rig ran one game and fatal
 * the first time it ran two: TMNT 1.59 died 0.06 s in, inside sw_scan_bytes,
 * loading from 0x7a958c - an address past the end of its image.
 *
 * So each is resolved ONCE, through the environment for a title whose addresses
 * are known, and then CHECKED. An address that is not mapped resolves to 0 and
 * the feature that needs it turns itself off. The game boots either way; what
 * it loses is the shim's view of the game's own switch table, which is a
 * convenience for this rig and not something the game needs to run.
 *
 *   PAD_SW_STRUCT  the switch struct: +0 entry array, +4 raw state bytes
 *   PAD_SW_COUNT   how many switches
 *   PAD_DEV_TABLE  device table, stride 40, 1-based
 *   PAD_DEV_COUNT  how many devices
 *   PAD_MSG_LANG   the current language slot, for msg_row()
 */
TITLE_ADDR(a_sw_struct, "PAD_SW_STRUCT", 0x7a958cu)
TITLE_ADDR(a_sw_count,  "PAD_SW_COUNT",  0x7e43d8u)
TITLE_ADDR(a_dev_table, "PAD_DEV_TABLE", 0x7446a4u)
TITLE_ADDR(a_dev_count, "PAD_DEV_COUNT", 0x5ec030u)

/* The runtime finder's answer, for a title whose address is not configured.
 * Two words of the shim's own, holding what the game's own SW_STRUCT and
 * SW_COUNT hold, so every reader downstream is unchanged - see the FINDING THE
 * SWITCH TABLE block below for how they get filled in. */
static void sw_dump(void);
static unsigned sw_shadow[2];            /* [0] entry[]  [1] raw[] (0 = none) */
static unsigned sw_shadow_count;

/* THE FOUND TABLE WINS OVER THE CONFIGURED ONE, because "configured" only ever
 * means "mapped". EHOH's binary is big enough to cover Godzilla Pro's
 * 0x7a958c, so a_sw_struct() returned an address, the finder was skipped as
 * unnecessary, and the shim read a switch table out of somebody else's data.
 * There was no error to see: no crash, no [swfind] line, just switches that
 * never worked. sw_find_maybe() validates the configured address rather than
 * trusting it, and puts its answer here when the configured one does not hold
 * up. */
static unsigned sw_struct_addr(void)
{
    if (sw_shadow[0]) return (unsigned)(unsigned long)&sw_shadow[0];
    return a_sw_struct();
}

static unsigned sw_count_addr(void)
{
    if (sw_shadow_count) return (unsigned)(unsigned long)&sw_shadow_count;
    return a_sw_count();
}

#define SW_STRUCT sw_struct_addr()
#define SW_COUNT  sw_count_addr()
#define DEV_TABLE a_dev_table()
#define DEV_COUNT a_dev_count()

/* 0x485918 in miniature: a message row is up to five const char*, one per
 * language, falling back to slot 0. */
static const char *msg_row(unsigned row)
{
    unsigned lang, s;
    if (!MSG_LANG) return 0;
    lang = tread(MSG_LANG);
    if (row < 0x8000u || row >= 0x800000u) return 0;
    s = ((const unsigned *)(unsigned long)row)[0];
    if (lang && lang < 5) {
        unsigned t = ((const unsigned *)(unsigned long)row)[lang];
        if (t >= 0x8000u && t < 0x800000u) s = t;
    }
    if (s < 0x8000u || s >= 0x800000u) return 0;
    return (const char *)(unsigned long)s;
}

static int sw_ok(unsigned p) { return p >= 0x8000u && p < 0xf0000000u; }

/* ---- the walking-bit sweep -------------------------------------------- *
 * PAD_NB_SWWALK=<samples per step> builds the whole node/bit -> switch map in
 * ONE run. It sets exactly one bit of one node's `ff` input word, holds it,
 * prints which switch ids went active, and moves on.
 *
 * A step must outlast the poll interval or the map is garbage: the service
 * loop visits one board about every 101 ms and there are eight of them, so a
 * given board is only asked every ~800 ms. Anything under ~1.5 s reads the
 * previous step's state and shifts the entire mapping by one.
 * ---------------------------------------------------------------------- */
static const unsigned char swwalk_nodes[] = { 1, 4, 7, 8, 9, 12, 14 };
#define SWWALK_NODES (sizeof swwalk_nodes / sizeof swwalk_nodes[0])
static unsigned swwalk_step;
static int swwalk_hold = -1;

static int swwalk_on(void)
{
    if (swwalk_hold == -1) {
        char *p = getenv("PAD_NB_SWWALK");
        int v = 0;
        while (p && *p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        swwalk_hold = v;
    }
    return swwalk_hold > 0;
}

/* The reply builder asks: what should THIS node's input word be right now? */
static unsigned swwalk_word(unsigned nid)
{
    unsigned idx = swwalk_step / 32, bit = swwalk_step % 32;
    if (!swwalk_on() || idx >= SWWALK_NODES) return 0;
    return (swwalk_nodes[idx] == nid) ? (1u << bit) : 0u;
}

/* THE TWO STORES ARE IN DIFFERENT UNITS, and that is the whole point.
 *
 *     entry[+24]  the ELECTRICAL level as read from the node board.
 *                 0x1e6d90 converts it to logical and INVERTS when
 *                 (cfg[28] & 4) is clear, which is most of this machine.
 *     raw[id]     the DEBOUNCED LOGICAL state. 0x1e67c4 returns it as-is.
 *
 * So with the shim answering the bus in all-zeros, every active-low switch -
 * 78 of the 88 - reads ACTIVE through 0x1e6d90 while reading INACTIVE through
 * 0x1e67c4. The game is being told the whole playfield is permanently made,
 * and the two views of it disagree. That is a rig artefact of exactly the
 * class this document keeps warning about, not a property of the game.
 *
 *   PAD_SW_IDLE=1        drive every switch to its INACTIVE level (the
 *                        honest resting state of a machine with no ball)
 *   PAD_SW_SET=<ids>     then make these ids ACTIVE - the "change one and
 *                        watch the game react" probe
 *
 * Both write the level the bus receive path would have written, so the game's
 * own debounce and edge detection still run on top.
 */
static int sw_inactive_level(unsigned cfg)
{
    /* polarity bit set -> active high, so inactive is 0; clear -> inverted. */
    if (!sw_ok(cfg)) return 0;
    return (*(const unsigned short *)(unsigned long)(cfg + 28) & 4) ? 0 : 1;
}

static void sw_force(void)
{
    static char *list = (char *)-1;
    static int idle = -1;
    unsigned st = tread(SW_STRUCT);
    unsigned raw = tread_at(SW_STRUCT, 4);
    unsigned n = tread(SW_COUNT);
    unsigned id;
    char *p;

    if (idle == -1) { char *q = getenv("PAD_SW_IDLE"); idle = (q && *q != '0'); }
    if (list == (char *)-1) list = getenv("PAD_SW_SET");
    if (!sw_ok(st) || !sw_ok(raw) || n > 4096) return;
    if (!idle && !(list && *list)) return;

    if (idle) {
        for (id = 1; id < n; id++) {
            unsigned char *e = (unsigned char *)(unsigned long)(st + id * 32);
            e[24] = (unsigned char)sw_inactive_level(*(const unsigned *)(e + 8));
            ((unsigned char *)(unsigned long)raw)[id] = 0;
        }
    }
    for (p = list ? list : ""; *p; ) {
        unsigned v = 0;
        while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        if (v && v < n) {
            unsigned char *e = (unsigned char *)(unsigned long)(st + v * 32);
            e[24] = (unsigned char)!sw_inactive_level(*(const unsigned *)(e + 8));
            ((unsigned char *)(unsigned long)raw)[v] = 1;
        }
        while (*p && (*p < '0' || *p > '9')) p++;
    }
}

/* ---- FINDING THE SWITCH TABLE WITHOUT BEING TOLD WHERE IT IS -------------
 *
 * SW_STRUCT is a Godzilla Pro 1.15.0 address and no other title keeps its
 * switch table anywhere near it. Reversing each new title by hand is the
 * obvious answer and the wrong one: the table has a SHAPE, and the shape is the
 * same in every title because the code that walks it is the same. Look for the
 * shape instead, and a title nobody has opened works on the first run.
 *
 * WHAT IT LOOKS LIKE. entry[] is an array of 32-byte records, one per switch,
 * and these are the fields this shim already relies on:
 *
 *     +8   ptr  -> a config object   (+20 switch number, +28 flags)
 *     +12  ptr  -> a name object     (+16 message row)
 *     +18  u16  bit within the node's input word, always < 64
 *     +20  u8   node id, always a board that is really on the bus
 *     +24  u8   the logical level, 0 or 1
 *
 * Two live pointers, a small bit, a small node and a boolean, repeating every
 * 32 bytes for as long as the machine has switches.
 *
 * THE CONFIRMATION IS NOT THE SEARCH, which is what makes this trustworthy
 * rather than merely plausible. A run of the right shape is necessary and not
 * sufficient, so a candidate must also satisfy two things a coincidence will
 * not: every (node, bit) pair in the run is DISTINCT - two switches cannot
 * share one input line - and the nodes form a small set of distinct boards
 * rather than 24 different ones. A random stretch of heap that happens to
 * validate field by field fails both.
 *
 * WHAT IT DOES WITH THE ANSWER is deliberately boring: it fills in two words of
 * its own and points SW_STRUCT and SW_COUNT at them. Everything downstream then
 * reads the table exactly as it always has, through the same two indirections,
 * and there is no second code path to keep in step.
 *
 * raw[] is NOT found this way - it is the game's debounced state array and only
 * the dump and force instruments use it - so it stays 0 and those two say so.
 * Switch INPUT needs only entry[] and the count.
 */
static int sw_find_done;

/* The by-shape switch search has run and found nothing usable, this many times.
 * ZERO on godzilla and on every title whose table IS found: godzilla's
 * configured address checks out in sw_find_maybe so sw_find_table is never
 * called, and a found table sets sw_find_done and stops the search. Non-zero
 * only on a title whose switch table cannot be found by shape - which is what
 * item 52's node-directory discovery fallback (nb_nodes_init) keys on. */
static unsigned sw_find_fails;

static int sw_ptr_ok(unsigned v)
{
    return v >= 0x8000u && v < 0xf0000000u
           && addr_readable((const void *)(unsigned long)v);
}

static int sw_entry_ok(const unsigned char *e)
{
    unsigned p8, p12, bit, node, lvl;
    if (!addr_readable(e) || !addr_readable(e + 28)) return 0;
    p8   = *(const unsigned *)(e + 8);
    p12  = *(const unsigned *)(e + 12);
    bit  = *(const unsigned short *)(e + 18);
    node = e[20];
    lvl  = e[24];
    if (!sw_ptr_ok(p8) || !sw_ptr_ok(p12)) return 0;
    return bit < 64 && node < 16 && lvl <= 1;
}

static unsigned sw_run_len(unsigned base, unsigned cap)
{
    unsigned k = 0;
    while (k < cap
           && sw_entry_ok((const unsigned char *)(unsigned long)(base + k * 32)))
        k++;
    return k;
}

/* Distinct (node, bit) pairs and a small set of boards - see the header. */
static int sw_run_consistent(unsigned base, unsigned n)
{
    unsigned char seen[16][8];
    unsigned nodes = 0, i, j;
    for (i = 0; i < 16; i++)
        for (j = 0; j < 8; j++) seen[i][j] = 0;
    for (i = 0; i < n; i++) {
        const unsigned char *e =
            (const unsigned char *)(unsigned long)(base + i * 32);
        unsigned bit = *(const unsigned short *)(e + 18), node = e[20];
        unsigned m = 1u << (bit & 7);
        if (seen[node][bit >> 3] & m) return 0;      /* two switches, one line */
        seen[node][bit >> 3] |= (unsigned char)m;
    }
    for (i = 0; i < 16; i++)
        for (j = 0; j < 8; j++)
            if (seen[i][j]) { nodes++; break; }
    return nodes >= 2 && nodes <= 10;
}

/* Walk /proc/self/maps and try every writable region: the table is heap and the
 * heap moves, so nothing here assumes an address. */
static int sw_find_table_scan(void)
{
    char buf[8192];
    int fd, n;
    int (*ro)(const char *, int, ...) = dlsym(RTLD_NEXT, "open");
    long (*rr)(int, void *, unsigned long) = dlsym(RTLD_NEXT, "read");
    int (*rc)(int) = dlsym(RTLD_NEXT, "close");
    unsigned best = 0, best_n = 0;
    /* The longest run seen at all, accepted or not. When nothing qualifies this
     * is the only thing that says WHY - too short, or shaped right but
     * inconsistent - and without it a title that fails here is a blank. */
    unsigned near = 0, near_n = 0;

    if (!ro || !rr) return 0;
    fd = ro("/proc/self/maps", 0, 0);
    if (fd < 0) return 0;
    sw_scan_fd = fd;      /* published so an aborted scan can close it */

    while ((n = (int)rr(fd, buf, sizeof buf - 1)) > 0) {
        char *line = buf, *end = buf + n;
        buf[n] = 0;
        while (line < end) {
            char *nl = line, *p = line;
            unsigned long lo = 0, hi = 0;
            while (nl < end && *nl != '\n') nl++;
            if (nl >= end) break;
            *nl = 0;
            while (*p && *p != '-') {
                int c = *p++;
                if (c >= '0' && c <= '9') c -= '0';
                else if (c >= 'a' && c <= 'f') c -= 'a' - 10;
                else break;
                lo = lo * 16 + (unsigned long)c;
            }
            if (*p == '-') {
                p++;
                while (*p && *p != ' ') {
                    int c = *p++;
                    if (c >= '0' && c <= '9') c -= '0';
                    else if (c >= 'a' && c <= 'f') c -= 'a' - 10;
                    else break;
                    hi = hi * 16 + (unsigned long)c;
                }
            }
            /* rw-, inside the guest's own range, and not enormous. */
            if (hi > lo && hi - lo < 0x4000000UL && lo >= 0x8000UL
                && hi < 0xf0000000UL && p[0] == ' ' && p[1] == 'r' && p[2] == 'w') {
                unsigned a;
                for (a = (unsigned)lo; a + 32 * 32 < (unsigned)hi; a += 4) {
                    unsigned len;
                    if (!sw_entry_ok((const unsigned char *)(unsigned long)a))
                        continue;
                    len = sw_run_len(a, 2048);
                    if (len > near_n) { near = a; near_n = len; }   /* diagnosis */
                    if (len >= 24 && sw_run_consistent(a, len) && len > best_n) {
                        best = a;
                        best_n = len;
                    }
                    a += len * 32;
                }
            }
            line = nl + 1;
        }
    }
    if (rc) rc(fd);
    sw_scan_fd = -1;

    if (best) {
        char m[160];
        /* entry[0] is a dummy the game skips (`for id = 1`), so the run found
         * here starts at what the game calls index 1. Step the base back one
         * record so the ids this shim reports are the game's own. */
        sw_shadow[0] = best - 32;
        sw_shadow[1] = 0;
        sw_shadow_count = best_n + 1;
        snprintf(m, sizeof m,
                 "[swfind] found the switch table: entry[] at 0x%08x, "
                 "%u switches\n", sw_shadow[0], sw_shadow_count);
        logmsg(m);
        sw_dump();          /* print it, so the find can be judged not trusted */
        return 1;
    }
    if (near_n) {
        static int said;
        if (!said) {
            char m[160];
            said = 1;
            snprintf(m, sizeof m,
                     "[swfind] no switch table yet. Longest run of the right "
                     "shape: %u records at 0x%08x (%s)\n", near_n, near,
                     near_n < 24 ? "too short"
                                 : "long enough but (node,bit) not distinct");
            logmsg(m);
        }
    }
    /* Searched and found nothing usable. item 52's discovery fallback counts
     * these: enough of them, with no table ever found, means this title has no
     * switch table to seed the node-bus discovery walk from. */
    sw_find_fails++;
    return 0;
}

/* The seam, now filled - see addr_readable's note for the whole history.
 * The scan runs with the page-granular probe cache armed and the fault guard
 * around it. A stale cached yes - a region the guest freed mid-scan - faults,
 * scan_guard_check() longjmps back here, and the abort is simply a failed
 * search this tick: fd closed, fail counted, retried on a later tick. Armed
 * around the call and dead outside it, so nothing else in the shim can ever
 * act on a scan-lifetime readability answer. With PAD_SEGV_HEADER=0 there is
 * no handler to land in, so the scan runs the old way: unguarded, uncached,
 * slow, safe. */
static int sw_find_table(void)
{
    int ret;

    if (!segv_guard_ready)
        return sw_find_table_scan();

    if (__sync_lock_test_and_set(&scan_guard_busy, 1))
        return 0;      /* another guarded scan is mid-flight; this tick is
                        * simply lost and the cadence asks again soon */
    pr_gen++;
    if (!pr_gen) pr_gen = 1;                    /* 0 means disarmed */
    if (sigsetjmp(sw_scan_env, 1) == 0) {
        sw_scan_tid = syscall(224);             /* arm - see scan_guard_check */
        ret = sw_find_table_scan();
    } else {
        char m[160];
        int (*rc)(int) = dlsym(RTLD_NEXT, "close");
        if (sw_scan_fd >= 0 && rc) rc(sw_scan_fd);
        sw_scan_fd = -1;
        snprintf(m, sizeof m,
                 "[swfind] scan aborted by a fault (pc=0x%lx addr=0x%lx) - a "
                 "region left while we walked it; counted as a failed "
                 "search\n",
                 (unsigned long)sw_scan_pc, (unsigned long)sw_scan_addr);
        logmsg(m);
        sw_find_fails++;
        ret = 0;
    }
    sw_scan_tid = 0;
    pr_gen = 0;
    __sync_lock_release(&scan_guard_busy);
    return ret;
}

/* The predicate both item 52 fallbacks key on - see its forward declaration.
 * `!sw_find_done` means no table has been found by ANY route (configured or by
 * shape), and `sw_find_fails >= 4` means the by-shape search has actually RUN
 * and failed several times, so this is "hopeless" rather than "not yet". A
 * title whose table resolves - godzilla via sw_configured_ok(), star_wars by
 * shape at ~27 s - can never satisfy it. */
static int sw_table_hopeless(void)
{
    return !sw_find_done && sw_find_fails >= 4;
}

/* ★ ITEM 52: THE FILE TABLE - the third route to a switch table, for a title
 * whose in-memory table cannot be found by shape. stranger_things is why: its
 * entries are 44 bytes with node and bit in a separate device table, so the
 * by-shape hunt (32-byte godzilla records) can never succeed - and without a
 * table sw_scan_bytes() answers every 0x11 with "no switch state", which is a
 * playfield with no switches and a keyboard wired to nothing. Measured
 * 2026-08-18: bus fully up (0x11 at 53 s, 0x40 coils at 30 s), plunge.py
 * pressed coin, start and both flippers, and NOT ONE [nbchg] line - every
 * injection died at this table's absence.
 *
 * The table has existed on the host since swelf.py: mktables.py reads it
 * straight out of the title's ELF (validated against David's photographed
 * TECH ALERTS numbers) and writes /dump/tables/<game>/switch_list.txt. This
 * loads that file into godzilla-SHAPED 32-byte entries - +8 cfg pointer,
 * +18 bit, +20 node, the three fields the reply builder and the discovery
 * seed read - and publishes them through the same sw_shadow seam a by-shape
 * find uses, so every consumer downstream is unchanged. Tried only at
 * sw_table_hopeless(), so godzilla (configured, tick 0) and any title whose
 * in-memory table is found can never reach it.
 *
 * Absent ids are POISONED (node 0xff, bit 0xffff), not zeroed: an all-zero
 * entry reads as node 0 bit 0, and a held id with no row would close DIP 1
 * in the cabinet word. cfg is per-entry so the dump's num column stays real;
 * +28 polarity is left clear (active low) uniformly, which is godzilla's
 * shape for 78 of 88 - if ST's optos ever prove to need per-device polarity
 * it belongs in the file, not in a constant here.
 *
 * NOT sw_dump()ed on install, deliberately: mktables.py PREFERS a log dump
 * over the ELF walk, and this table would dump with every name "?" - the
 * next regeneration would trade the ELF's real names for question marks.
 * The file came from the host; publishing it back at the host is circular.
 * One log line says what was loaded and from where. */
#define SW_FTAB_MAX 512
static unsigned char sw_ftab[SW_FTAB_MAX][32];
static unsigned char sw_fcfg[SW_FTAB_MAX][32];
static int sw_ftab_state;          /* 0 untried, -1 tried and refused */
static int sw_ftab_installed;      /* the discovery seed keys on this */

static int sw_file_table(void)
{
    typedef void *FILEP;
    FILEP (*ropen)(const char *, const char *);
    char *(*rgets)(char *, int, FILEP);
    int  (*rclose)(FILEP);
    FILEP f;
    char path[192], line[300], msg[240];
    const char *p, *g;
    unsigned maxid = 0, n = 0, i;

    if (sw_ftab_state) return 0;
    sw_ftab_state = -1;
    p = getenv("PAD_SW_TABLE");
    g = getenv("PAD_GAME");
    if (p && *p)
        snprintf(path, sizeof path, "%s", p);
    else if (g && *g)
        snprintf(path, sizeof path, "/dump/tables/%s/switch_list.txt", g);
    else
        return 0;
    ropen  = dlsym(RTLD_NEXT, "fopen");
    rgets  = dlsym(RTLD_NEXT, "fgets");
    rclose = dlsym(RTLD_NEXT, "fclose");
    if (!ropen || !rgets || !rclose) return 0;
    f = ropen(path, "r");
    if (!f) {
        snprintf(msg, sizeof msg, "[swfind] no by-shape table and no file "
                 "table (%.140s): the playfield stays switchless this run\n",
                 path);
        logmsg(msg);
        return 0;
    }
    for (i = 0; i < SW_FTAB_MAX; i++) {
        sw_ftab[i][18] = 0xff;             /* poisoned - see the header */
        sw_ftab[i][19] = 0xff;
        sw_ftab[i][20] = 0xff;
    }
    while (rgets(line, sizeof line, f)) {
        unsigned v[4], k = 0;
        const char *q = line;
        if (line[0] == '#') continue;
        while (k < 4) {
            unsigned val = 0;
            int any = 0;
            while (*q == ' ' || *q == '\t') q++;
            while (*q >= '0' && *q <= '9') {
                val = val * 10 + (unsigned)(*q++ - '0');
                any = 1;
            }
            if (!any) break;
            v[k++] = val;
        }
        /* id num node bit NAME... - the name stays in the file (see header) */
        if (k < 4 || v[0] == 0 || v[0] >= SW_FTAB_MAX || v[2] >= 64
            || v[3] >= 256)
            continue;
        *(unsigned short *)(sw_ftab[v[0]] + 18) = (unsigned short)v[3];
        sw_ftab[v[0]][20] = (unsigned char)v[2];
        *(unsigned *)(sw_ftab[v[0]] + 8) =
            (unsigned)(unsigned long)sw_fcfg[v[0]];
        *(unsigned short *)(sw_fcfg[v[0]] + 20) = (unsigned short)v[1];
        if (v[0] > maxid) maxid = v[0];
        n++;
    }
    rclose(f);
    if (n < 16) {   /* a handful of rows is a parse accident, not a table */
        snprintf(msg, sizeof msg, "[swfind] file table %.140s parsed to only "
                 "%u row(s) - not trusted, not installed\n", path, n);
        logmsg(msg);
        return 0;
    }
    sw_shadow[0] = (unsigned)(unsigned long)&sw_ftab[0][0];
    sw_shadow[1] = 0;
    sw_shadow_count = maxid + 1;
    sw_ftab_installed = 1;
    snprintf(msg, sizeof msg,
             "[swfind] switch table loaded from %.120s: %u switches, ids to "
             "%u (ELF-derived; the names live in the file)\n", path, n, maxid);
    logmsg(msg);
    return 1;
}

/* Try, at most every 256 bus writes, until it works: the table does not exist
 * yet at the first ask, and a scan of the heap is not free. */
/* Does the CONFIGURED address really point at a switch table in THIS title?
 * Mapped is not correct - see sw_struct_addr(). Re-asked rather than cached,
 * because the table does not exist yet at the first bus write. */
static int sw_configured_ok(void)
{
    unsigned a = a_sw_struct(), st;
    if (!a || !a_sw_count()) return 0;
    st = *(const unsigned *)(unsigned long)a;
    if (!sw_ok(st)) return 0;
    /* Entry 0 is a dummy, so check from entry 1, and ask for rather less than
     * the finder does - this is a confirmation, not a search. */
    return sw_run_len(st + 32, 64) >= 8;
}

/* THE TABLE IS PUBLISHED EITHER WAY, and it was not: this used to accept the
 * configured address and return in silence, so the dump below - the ONLY route
 * the switch list has out of the guest - ran for a title that had to be
 * searched for and never for one that did not.
 *
 * That inverted exactly the wrong way round. Godzilla Pro 1.15.0 is the title
 * every address in this file was read out of, so it is the one title that takes
 * this branch, and it was therefore the one title whose virtual playfield could
 * never gain a clickable switch: mktables.py builds switch_list.txt from
 * `[sw] --- switches:` in the run log, that line never appeared, and the window
 * said "clickable switches will appear on the next run" on every run forever.
 * Six titles on this disk had a switch table cached; Godzilla, the one the rig
 * was built on, did not.
 *
 * Dumping here costs one pass over the table, once per run. */
static void sw_find_maybe(void)
{
    static unsigned tick;
    unsigned t;
    if (sw_find_done) return;
    /* DENSE EARLY, SPARSE LATER - and the spacing is load-bearing, not taste.
     *
     * A flat `tick % 256` costs one table pass per 256 node-bus frames, which
     * is the right price for a search that usually succeeds. But the "there is
     * no table on this title" VERDICT needs four failed searches
     * (sw_table_hopeless), so a flat 256 put that verdict 1024 frames away -
     * MEASURED at 178.4 s on stranger_things, where the discovery schedule
     * then seeded at 178.4 s and the boards went found at 181 s.
     *
     * The game does not wait that long and never re-asks: 0x2059ac raises the
     * LOCATING screen after 300 ms of failed location and gives up re-checking
     * seconds later, and the only clear of that screen bit lives inside the
     * loop that exits. So for the whole window in which stranger_things is
     * asking, the shim was answering "the bus is empty", and by the time the
     * truth arrived nothing was listening. The verdict has to be reachable in
     * the same seconds the game spends asking.
     *
     * Four searches inside the first 32 frames, then the old 256 spacing. Same
     * number of passes, front-loaded onto the frames the game actually cares
     * about - those first frames ARE the bare-00 discovery walk. */
    t = tick++;
    /* Ticks 0, 2, 4, 6 rather than 0, 8, 16, 24. The FOURTH failure is what
     * sw_table_hopeless() waits for, and everything item 52 built on top of it -
     * the node-directory discovery seed, the cabinet at-rest word - cannot exist
     * before then. At every eighth bus write that verdict lands on TX #25, and
     * the game asks its first discovery question at TX #12: the answer was
     * always going to be "bus empty" no matter how good it was. At every second
     * it lands on TX #7, five frames before the question. Only affordable
     * because addr_readable() no longer costs a syscall per candidate; before
     * that fix this line would have made things worse, not better.
     *
     * ▼ (t & 1) WAS TRIED, BACKED OUT, AND IS NOW BACK, in that order. With
     * the page cache making each scan complete in milliseconds, four scans at
     * ticks 0/2/4/6 all land inside the first seconds of boot - exactly when
     * the guest allocates and frees scene memory hardest - and the first
     * attempt took a SIGSEGV in sw_entry_ok at 79 s that no pre-change run
     * had ever taken. That race is closed now, the only way it can be: the
     * scan runs under sw_find_table's fault guard, so a scan that steps on a
     * freed region aborts and counts as a failed search rather than killing
     * the run. The dense cadence is therefore safe again - and it is the
     * difference between the hopeless verdict landing on TX #7, five frames
     * BEFORE the game's first discovery question at TX #12, and landing
     * after the game has stopped listening. */
    if (t < 8 ? (t & 1) != 0 : (t % 256) != 0) return;
    if (sw_configured_ok()) {                               /* the known title */
        char m[160];
        sw_find_done = 1;
        snprintf(m, sizeof m,
                 "[swfind] the configured switch table checks out: entry[] at "
                 "0x%08x, %u switches\n", tread(SW_STRUCT), tread(SW_COUNT));
        logmsg(m);
        sw_dump();      /* publish it, exactly as a found table is published */
        return;
    }
    if (sw_find_table()) { sw_find_done = 1; return; }
    /* Hopeless by shape (four failed searches) - the file is the last route,
     * and it is tried exactly once (sw_ftab_state). */
    if (sw_table_hopeless() && sw_file_table()) sw_find_done = 1;
}

static void sw_dump(void)
{
    char line[300];
    unsigned st  = tread(SW_STRUCT);
    unsigned raw = tread_at(SW_STRUCT, 4);
    unsigned n   = tread(SW_COUNT);
    unsigned dn  = tread(DEV_COUNT);
    unsigned id;

    snprintf(line, sizeof line,
             "[sw] --- switches: count=%u entry[]=0x%08x raw[]=0x%08x ---\n",
             n, st, raw);
    logmsg(line);
    /* raw[] IS NOT REQUIRED. It used to be, and that silently emptied this
     * whole dump for a title found by sw_find_table(), which locates entry[]
     * and deliberately does not claim to know where the debounced state array
     * is. One missing column is not a reason to print nothing. */
    if (sw_ok(st) && n <= 4096) {
        for (id = 1; id < n; id++) {
            const unsigned char *e =
                (const unsigned char *)(unsigned long)(st + id * 32);
            unsigned cfg = *(const unsigned *)(e + 8);
            unsigned nameobj = *(const unsigned *)(e + 12);
            const char *nm = 0;
            unsigned num = 0, fl = 0;
            char rawtxt[8];
            if (sw_ok(cfg)) {
                num = *(const unsigned short *)(unsigned long)(cfg + 20);
                fl  = *(const unsigned short *)(unsigned long)(cfg + 28);
            }
            if (sw_ok(nameobj))
                nm = msg_row(*(const unsigned *)(unsigned long)(nameobj + 16));
            if (sw_ok(raw))
                snprintf(rawtxt, sizeof rawtxt, "%u",
                         ((const unsigned char *)(unsigned long)raw)[id]);
            else
                rawtxt[0] = '?', rawtxt[1] = 0;
            snprintf(line, sizeof line,
                     "[sw] id=%-3u num=%-4u node=%-2u bit=%-2u raw=%s logical=%u "
                     "flags=0x%04x %s\n",
                     id, num, e[20], *(const unsigned short *)(e + 18),
                     rawtxt, e[24], fl, nm ? nm : "?");
            logmsg(line);
        }
    }

    snprintf(line, sizeof line, "[dev] --- ball devices: count=%u ---\n", dn);
    logmsg(line);
    if (dn <= 256) {
        for (id = 1; id < dn; id++) {
            const unsigned char *ent =
                (const unsigned char *)(unsigned long)(DEV_TABLE + id * 40);
            unsigned obj = *(const unsigned *)ent;
            unsigned flags = 0;
            const char *nm = msg_row(*(const unsigned *)(ent + 32));
            if (sw_ok(obj))
                flags = *(const unsigned short *)(unsigned long)(obj + 20);
            snprintf(line, sizeof line,
                     "[dev] %-2u obj=0x%08x flags=0x%04x%s %s\n",
                     id, obj, flags, (flags & 1) ? "  MALFUNCTION" : "",
                     nm ? nm : "?");
            logmsg(line);
        }
    }
}

/* PAD_SW_PRESS=<id>[,<id>...] - actually PRESS switches, through the game's own
 * input entry point.
 *
 * WRITING THE STATE ARRAYS DOES NOTHING, and that cost a run to learn. The
 * input-side producer is:
 *
 *     0x1da600(id, value)
 *         0x1e6e6c(id, value)          raw[id] = value, under mutex 0x7aa99c
 *         if (0x1e6bdc(id))            per-switch gate: [[entry+12]+8] != 0
 *             0x45feb8(id, value)      set/clear bit (id&15) of the packed
 *                                      bitmap at 0x7e29ec + 0x60 + (id>>4)*2
 *
 * Its only two callers are 0x1dad8c and 0x1db0c4, so this is the seam the real
 * node bus input arrives through, and calling it from the bus service thread
 * delivers input the same way the machine would.
 *
 * THIS IS STILL NOT ENOUGH, and the reason is recorded rather than guessed:
 * 0x45feb8 is a BITMAP SETTER, not an event dispatch - an earlier version of
 * this comment called it one, which was wrong. So 0x1da600 updates two of the
 * THREE switch representations and notifies nobody; it does not touch
 * entry[+24], the electrical level 0x1e6d90 reads. Pressing Service Select
 * (id 25) through it produced no visible reaction. What turns a state change
 * into a game reaction is the open question - see the handoff.
 *
 * Each id is pressed for PRESS_HOLD samples and released, one after another,
 * so the game sees a real edge pair rather than a level held forever.
 */
#define SW_INPUT  0x1da600u
#define PRESS_HOLD  16          /* samples held down, ~200 ms at ~80/s        */
#define PRESS_GAP  120          /* samples between presses, ~1.5 s           */

static void sw_press(void)
{
    static char *list = (char *)-1;
    static unsigned n, start;
    void (*input)(unsigned, unsigned) =
        (void (*)(unsigned, unsigned))(unsigned long)SW_INPUT;
    char *p;
    unsigned slot, k, i = 0;

    if (list == (char *)-1) {
        list = getenv("PAD_SW_PRESS");
        start = 0;
        {   char *q = getenv("PAD_SW_PRESS_AT");
            while (q && *q >= '0' && *q <= '9') start = start * 10 + (*q++ - '0');
            if (!start) start = 2400;      /* ~30 s in: let the boot settle   */
        }
    }
    if (!list || !*list) return;
    if (++n < start) return;
    slot = (n - start) / PRESS_GAP;
    k    = (n - start) % PRESS_GAP;
    if (k != 0 && k != PRESS_HOLD) return;

    for (p = list; *p; i++) {
        unsigned id = 0;
        while (*p >= '0' && *p <= '9') id = id * 10 + (*p++ - '0');
        while (*p && (*p < '0' || *p > '9')) p++;
        if (i != slot || !id) continue;
        {
            char line[120];
            snprintf(line, sizeof line, "[sw] %s switch %u via 0x%x\n",
                     k ? "RELEASE" : "PRESS  ", id, SW_INPUT);
            logmsg(line);
        }
        input(id, k ? 0u : 1u);
        return;
    }
}

/* Report the step that just finished, then advance. Reporting BEFORE the
 * advance is the whole correctness argument: the switch table reflects the bit
 * that was held, not the one about to be set. */
static void swwalk_tick(void)
{
    static unsigned n, started;
    char line[400];
    unsigned st, id, cnt, k;
    if (!swwalk_on()) return;
    if (++n < 2400) return;                 /* let the boot settle first */
    if (!started) { started = 1; n = 2400; }
    if ((n - 2400) % (unsigned)swwalk_hold) return;

    st = tread(SW_STRUCT);
    cnt = tread(SW_COUNT);
    if (sw_ok(st) && cnt <= 4096 && swwalk_step / 32 < SWWALK_NODES) {
        static unsigned char prev[512];
        static int primed;
        if (cnt > 512) cnt = 512;
        k = snprintf(line, sizeof line, "[swmap] node=%-2u bit=%-2u ->",
                     swwalk_nodes[swwalk_step / 32], swwalk_step % 32);
        /* DIFFERENTIAL, and it has to be. An absolute "which switches are
         * active" reading is useless here: switches the bus never writes keep
         * entry[+24] at 0, and for the 78 active-low ones that reads as
         * PRESSED, so the first version of this sweep reported ids 17..33 -
         * DIPs and service buttons, which are not on any node board - under
         * every single bit. Report only what THIS step changed. */
        for (id = 1; id < cnt && k < (unsigned)sizeof line - 10; id++) {
            const unsigned char *e =
                (const unsigned char *)(unsigned long)(st + id * 32);
            unsigned cfg = *(const unsigned *)(e + 8);
            unsigned char cur = e[24];
            if (primed && cur != prev[id])
                k += snprintf(line + k, sizeof line - k, " %c%u",
                              cur != (unsigned char)sw_inactive_level(cfg)
                                  ? '+' : '-', id);
            prev[id] = cur;
        }
        if (!primed) { primed = 1; k += snprintf(line + k, sizeof line - k, " (baseline)"); }
        snprintf(line + k, sizeof line - k, "\n");
        logmsg(line);
    }
    swwalk_step++;
}

/* ======================================================================
 * THE REAL SWITCH INPUT PATH: node bus command 0x11
 *
 * The `ff` probe is NOT it, and all eight of its callers now say so. Five
 * (0x1d619c 0x1d62a8 0x1d6370 0x1d6478 0x1d6590) are inside 0x1d6184, the node
 * board FLASH PROGRAMMER, which polls bit 7 of the reply's second word as a
 * "busy" flag while it erases and writes 96 sectors. Two (0x1d7630 0x1d7730)
 * are inside 0x1d734c, the bus enumeration, and both do only
 *     ldr r3,[reply+4]; eor r3,#0x80000; ubfx r3,#19,#1; strb r3,[0x7a908c+node+276]
 * i.e. ONE gate bit per node. The eighth, 0x1d8230, is the service loop's fault
 * read. Filling the `ff` reply moved 53 switches because those bits overlap the
 * fault mask - a fault response, exactly as the handoff warned.
 *
 * The actual chain, read end to end:
 *
 *   0x1d7d88  node service loop, one board per pass
 *     -> 0x1d6d94(node, 0)
 *          0x59f034(node, buf8)  -> 0x59ef60: sends { 0x80|node, 01, 11, 0a },
 *                                   10-byte reply; bytes 0..7 are the SWITCH
 *                                   BITS, bytes 8..9 a u16 extra
 *          gate: 0x7a908c[276 + node] must be non-zero  (set from `ff` bit 19,
 *                inverted - so an all-zero `ff` reply leaves it ENABLED)
 *       -> 0x1e78f4(node, buf8)   distribute
 *       -> 0x1d54b8(node, buf8, 0)
 *
 * 0x1e78f4 XORs the 8 new bytes against NodeRec.cur[8], and for every bit that
 * CHANGED looks up NodeRec.map[bit] to get a switch id, bumps entry[+22] and
 * links the entry onto a pending list at 0x7aa9b8. 0x1e7540 drains that list
 * and is what finally writes the electrical level:
 *
 *     level = (NodeRec.cur[bit>>3] >> (bit&7)) & 1
 *     if ((entry[+22] & 1) == 0) level ^= 1        // replays fast edges
 *     entry[+24] = level
 *
 * NodeRec is 160 bytes, array at 0x7a958c + 16, indexed by node id:
 *     +0 next   +4 board obj   +8 switch list   +12 prev[8]   +20 cur[8]
 *     +28 u16 map[64]   +156 queued
 * (node 0's first 12 bytes are the subsystem header - entries at +0, raw at +4 -
 * because nodes[] starts at +16 and the first 12 bytes of each record are unused.
 * That is why 0x7a958c reads as both a struct and an array base.)
 *
 * We do not need map[] at all: every switch entry carries its own coordinates.
 *     entry[+18]  u16  BIT number within the node   (0..63)
 *     entry[+20]  u8   NODE id
 *
 * Obfuscation: 0x59ef60 XORs the reply with a rotating key. The key is in the
 * REQUEST, so we never have to find it in memory - request[1]==2 means keyed
 * with request[3], request[1]==1 means plain. Read it off the wire.
 *
 * TWO THINGS BLOCK A CHANGE in 0x1e78f4 and both are ours to avoid:
 *     entry[+26] != 0   an inhibit byte
 *     raw[id]    != 0   PAD_SW_SET writes raw[], so PAD_SW_SET actively
 *                       SUPPRESSES real scan input. Do not combine them.
 * ====================================================================== */
#define SW_NODEREC(n)  (SW_STRUCT + 16u + (n) * 160u)
#define NB_GATE   0x7a908cu     /* +276+node = per-node scan enable          */

/* Ids held ACTIVE right now: PAD_SW_HOLD plus whatever the tap sequence has
 * pressed. Byte per id. 128 was "more than the 88 this machine has" - but an
 * id is the TITLE'S table index and munsters/sword_of_rage index their whole
 * cabinet past 190 (door 198/201, trough 234..240), so 128 silently dropped
 * every one of their rows in sw_rest_resolve's guard (item 73's review
 * caught it). 256 = PADSW_MAX_ID, the shm held[] bound; every use is
 * sizeof-checked so this is the only line that names the size. */
static unsigned char sw_active[256];
static int sw_scan_on = -1;

/* The level the shim put on the wire for each id on the last word it built.
 * PAD_SW_PEND prints this next to the bit the game recorded in NodeRec.cur[],
 * and the two disagreeing is the signature of a reply-decode bug - which is
 * exactly how the XOR key was caught. */
static unsigned char sw_sent[256];


static int sw_scan_enabled(void)
{
    if (sw_scan_on == -1) {
        char *q = getenv("PAD_SW_SCAN");
        sw_scan_on = !(q && *q == '0');     /* default ON once built */
    }
    return sw_scan_on;
}

/* A MACHINE AT REST, and it is not cosmetic - it gates node bus bring-up.
 *
 * 0x446824 runs once from the boot chain (0x4f0910), reads the COIN DOOR
 * interlock with 0x5a9e50(23), and latches the answer into [0x706464].
 * Everything in bring-up hangs off that word: 0x1d6fb8 waits up to SIXTY
 * SECONDS for it (0x1d6fdc, r4 = 60000 counted down 100 ms at a time) and
 * bring-up's retry loop can enter that wait five times, so a door the game
 * believes is open costs up to five minutes before the service loop starts.
 * No service loop means no `ff`, so the per-node scan gate is never written,
 * so no 0x11 is ever sent and the playfield is dead for the whole run.
 *
 * That was the intermittent bring-up stall. It looked random because it is a
 * race: 0x446824 latches the door at one instant during boot, and whether the
 * shim had already filled the cabinet word by then decided the answer. The
 * screen said so all along - a stalled run draws `* 48V DISABLED *` - and it
 * got dismissed as normal for a measurement run.
 *
 * padglhost has always defaulted these ON (its `toggle` bindings: switch 33
 * coin door, 66..71 six balls in the trough), which is why watch.sh never hit
 * this and nbrun.sh hit it half the time. The default belongs HERE so every
 * run starts from the same machine, keyboard or not.
 *
 * Skipped when PAD_SW_SHM is set: the host then owns the latching switches and
 * forcing them here would make `C` unable to open the door again. PAD_SW_REST=0
 * disables it outright, which is how to reproduce the stall on purpose. */
static const unsigned char sw_rest_ids[] = { 33, 66, 67, 68, 69, 70, 71 };
static int sw_rest_on;   /* the set is wanted at all (PAD_SW_REST != 0) */

/* ★ ITEM 27: THE REST SET'S TROUGH IDS ARE PER TITLE, and this table was the
 * FOURTH copy of Godzilla's numbers to be found holding a wrong switch (after
 * plunge.py, padglhost's binds[], and nodecensus's case). It is also the one
 * that mattered most: the game decides during BOOT whether its ball devices
 * have their balls - before padglhost's window exists, which is the exact
 * window sw_rest_pending() covers - so on jaws_le the trough device was told
 * Godzilla's 66..71 were closed (its TROUGH JAM plus five phantoms) while its
 * real trough 60..65 read empty. The device model bakes there: a trough
 * filled correctly LATER changes nothing, Start finds a ball-less (and
 * jam-flagged) trough device and is refused without so much as a ball
 * search - measured 2026-08-10, CREDITS 1 on the game's own screen, Start
 * delivered on its own scan, no eject, no LOCATING PINBALLS.
 *
 * Resolution is by NAME from the derived table the guest can already see at
 * /dump/tables/$PAD_GAME/switch_list.txt (mktables writes it before the
 * guest starts; /dump is bound into the pivot). No file, or no PAD_GAME,
 * keeps the compiled Godzilla ids: exactly the old behaviour.
 *
 * ★ ITEM 73: THE DOOR RESOLVES TOO, BY WIRE. "The door stays 33 - a
 * platform switch, identical on every title measured" was true of the
 * WIRE (node 0 bit 23 on all 29 derived lists) and false of the ID, which
 * is a table index: 34 on aerosmith/avengers, 36 on batman, 198/201 on
 * munsters/sword_of_rage. Holding id 33 on those titles holds some other
 * switch while the interlock bit the game latches during bring-up
 * (0x5a9e50(23), the sixty-second stall above) is only covered by the
 * synthetic at-rest word for as long as no table has resolved. So the door
 * takes the id its (node,bit) = (0,23) has in the title's own list; the
 * name is not used because five titles' lists are all-'?'. */
extern long read(int, void *, unsigned long);   /* self-interposed; unknown
                                                 * fds pass through, same as
                                                 * open/close in the LED
                                                 * block (declared there too,
                                                 * which is below this use) */
extern int open(const char *, int, int);
extern int close(int);
static unsigned char sw_rest_set[8];
static unsigned sw_rest_n;

static void sw_rest_resolve(void)
{
    static char buf[16384];
    static int done;
    const char *game;
    char path[256];
    long n;
    int fd, got = 0;
    unsigned i;
    char *p, *e;

    if (done) return;
    done = 1;
    for (i = 0; i < sizeof sw_rest_ids; i++) sw_rest_set[i] = sw_rest_ids[i];
    sw_rest_n = sizeof sw_rest_ids;

    game = getenv("PAD_GAME");
    if (!game || !*game) return;
    snprintf(path, sizeof path, "/dump/tables/%s/switch_list.txt", game);
    fd = open(path, 0 /*O_RDONLY*/, 0);
    if (fd < 0) return;
    n = read(fd, buf, sizeof buf - 1);
    close(fd);
    if (n <= 0) return;
    buf[n] = 0;

    /* Lines are `id num node bit NAME...`; find TROUGH 1..6 by name, case-
     * insensitively, taking the id from the front of that line - and the
     * door by wire, (node,bit) == (0,23) (item 73). */
    sw_rest_n = 1;                     /* slot 0 = the door, 33 until found */
    for (p = buf; *p; p = e) {
        unsigned id = 0, t, f;
        unsigned num[3] = { 0, 0, 0 }; /* num, node, bit */
        int seen[3] = { 0, 0, 0 };
        char *q = p;
        for (e = p; *e && *e != '\n'; e++) ;
        if (*e) e++;
        if (*q == '#') continue;
        while (*q >= '0' && *q <= '9') id = id * 10 + (unsigned)(*q++ - '0');
        if (!id || id >= sizeof sw_active) continue;
        for (f = 0; f < 3; f++) {
            while (*q == ' ' || *q == '\t') q++;
            while (*q >= '0' && *q <= '9') {
                num[f] = num[f] * 10 + (unsigned)(*q++ - '0');
                seen[f] = 1;
            }
            if (!seen[f]) break;
        }
        if (seen[1] && seen[2] && num[1] == 0 && num[2] == 23) {
            sw_rest_set[0] = (unsigned char)id;   /* the door, per title */
            continue;
        }
        for (; q < e - 8; q++) {
            if ((q[0] == 'T' || q[0] == 't') &&
                (q[1] == 'R' || q[1] == 'r') &&
                (q[2] == 'O' || q[2] == 'o') &&
                (q[3] == 'U' || q[3] == 'u') &&
                (q[4] == 'G' || q[4] == 'g') &&
                (q[5] == 'H' || q[5] == 'h') && q[6] == ' ' &&
                q[7] >= '1' && q[7] <= '6' &&
                (q[8] == '\n' || q[8] == '\r' || q[8] == 0 || q[8] == ' ')) {
                t = (unsigned)(q[7] - '0');
                if (sw_rest_n < sizeof sw_rest_set && t) {
                    sw_rest_set[sw_rest_n++] = (unsigned char)id;
                    got++;
                }
                break;
            }
        }
    }
    if (got) {
        char m[128];
        int  o = 0;
        o = snprintf(m, sizeof m, "[swrest] trough resolved for %s:", game);
        for (i = 1; i < sw_rest_n && o < (int)sizeof m - 8; i++)
            o += snprintf(m + o, sizeof m - (unsigned)o, " %u", sw_rest_set[i]);
        snprintf(m + o, sizeof m - (unsigned)o, "\n");
        logmsg(m);
    } else {
        /* a list with no TROUGH rows: keep Godzilla's TROUGH ids, but say
         * so. The door slot is NOT reset - its wire resolution above stands
         * whatever the trough names look like (item 73). */
        for (i = 1; i < sizeof sw_rest_ids; i++)
            sw_rest_set[i] = sw_rest_ids[i];
        sw_rest_n = sizeof sw_rest_ids;
        logmsg("[swrest] no TROUGH rows in the switch list; "
               "trough rest set stays Godzilla's\n");
    }
    if (sw_rest_set[0] != sw_rest_ids[0]) {
        char m[96];
        snprintf(m, sizeof m, "[swrest] door resolved for %s: id %u "
                 "(node 0 bit 23), not 33\n", game, sw_rest_set[0]);
        logmsg(m);
    }
}

static void sw_hold_init(void)
{
    static int done;
    char *p;
    unsigned i;
    if (done) return;
    done = 1;
    sw_rest_resolve();
    p = getenv("PAD_SW_REST");
    sw_rest_on = !(p && *p == '0');
    if (!(p && *p == '0') && !getenv("PAD_SW_SHM")) {
        for (i = 0; i < sw_rest_n; i++)
            sw_active[sw_rest_set[i]] = 1;
        logmsg("[swrest] machine at rest: coin door shut, balls in trough\n");
    }
    p = getenv("PAD_SW_HOLD");
    while (p && *p) {
        unsigned id = 0;
        while (*p >= '0' && *p <= '9') id = id * 10 + (unsigned)(*p++ - '0');
        if (id && id < sizeof sw_active) sw_active[id] = 1;
        while (*p && (*p < '0' || *p > '9')) p++;
    }
    sw_gen++;
}

/* Build node `nid`'s 8 scan bytes from the live switch table. Every switch on
 * that node contributes its own bit at its own coordinates; an id in
 * sw_active[] gets the ACTIVE level, everything else the honest resting level.
 * A switch the table does not place on this node contributes nothing, so a bit
 * with no switch behind it stays 0 and 0x1e78f4 discards it (map[bit] == 0). */
/* Write the same 8 bytes into the node's own board mirror, so the FIRST reply
 * of a run does not read as 64 simultaneous switch changes.
 *
 * Measured: the first 0x11 for nodes 1/8/9 lands ~35 s in (the boards are not
 * enabled before that), and it flipped 27 playfield switches - Start Button,
 * both flipper buttons, Tilt Pendulum, the coin switches - to MADE and left
 * them there. They stayed wrong because of the replay rule in 0x1e7540:
 *     level = cur[bit>>3] >> (bit&7) & 1 ;  if ((entry[+22] & 1) == 0) level ^= 1
 * Switches whose change got deferred once were counted twice, landed on an even
 * count, and were stored inverted. The phantom Start/flipper presses that
 * followed are what was walking the operator menu cursor around on its own.
 *
 * Priming is the honest fix rather than a mask: NodeRec.cur[] IS the mirror of
 * what the board last reported, and at power-on the host and the board agree by
 * definition. Only genuine later changes then produce edges. */
/* ---- THE NODE SERVICE SCHEDULE -----------------------------------------
 *
 * `00` - a single unaddressed zero byte - is the bus master asking WHICH NODE
 * WANTS SERVICING. 0x59ef30 sends it and returns reply[0]; 0x1d7d88 then
 * services that node and asks again, looping while the answer is non-zero:
 *
 *     1d7d98  bl 0x59ef30            ; r4 = next node
 *     1d7dc0  cmp r4, #0 ; bne ...   ; non-zero -> playfield path
 *     1d7e7c  bl 0x1d6d94(r4)        ; <- the 0x11 SWITCH SCAN happens here
 *     1d7e5c  cmp r4, #0 ; bne 1d7d98
 *
 * The shim answered that poll with zeros, so the answer was always node 0. The
 * loop therefore serviced the cabinet and returned, every single time, and the
 * playfield was scanned exactly once per run - during enumeration, by a
 * different caller. Six 0x11 requests in 130 s against 5166 polls.
 *
 * That is a fidelity bug in the shim, not a gate in the game: on a real machine
 * the netbridge names a board that has input pending. Answering with a real
 * schedule is what turns the playfield from a one-shot snapshot into a live
 * scan.
 *
 * ZERO MUST COME UP REGULARLY. The loop only exits when the answer is 0 (or the
 * exchange fails), so a schedule that never returns 0 spins 0x1d7d88 forever
 * inside the guest - the exact runaway this rig must not create. Alternating
 * "one playfield node, then 0" is both the safe shape and the natural one: it
 * matches one outer invocation of the loop, and it keeps the cabinet buttons
 * responsive because 0 comes up every other poll.
 *
 * The node list is read from the game's own switch table rather than hardcoded,
 * so this works for any title: entry[+20] is the node each switch lives on.
 */
static unsigned char nb_nodes[16];
static int nb_nnodes = -1;

/* ★ ITEM 52: THE PRIORITY LANE. `nb_news[node]` is set by the switch merge
 * the instant a switch on that node moves and cleared when that node's 0x11
 * scan is answered; nb_next_node() names news-bearing nodes at the HEAD of
 * every service cycle. See the long comment on nb_next_node's lane. */
static volatile unsigned char nb_news[64];
static int nb_lane_on = -1;                    /* PAD_NB_LANE=0 disables */

/* Is `node` in PAD_NB_SILENT? One definition, because the node-bus RX handler
 * (shim_read) tests the same list to refuse an addressed reply, and item 52's
 * node-directory discovery fallback (nb_nodes_init) must not seed a node the
 * machine does not have - two places, one fact. The list is a comma/space
 * separated set of decimal ids; empty or unset means nothing is silenced. */
static int nb_is_silent(unsigned node)
{
    static const char *silent = (const char *)-1;
    const char *s;
    if (silent == (const char *)-1) silent = getenv("PAD_NB_SILENT");
    if (!silent) return 0;
    for (s = silent; *s; ) {
        unsigned v = 0;
        int any = 0;
        while (*s >= '0' && *s <= '9') { v = v * 10 + (unsigned)(*s++ - '0'); any = 1; }
        if (any && v == node) return 1;
        if (*s) s++;
    }
    return 0;
}

/* Does a SILENCED node still answer the `ff` status poll (item 52's
 * "silent for identity, present for status" carve-out)? PER NODE now, because
 * the global carve-out turned out to hold godzilla_le's whole boot hostage:
 *
 * MEASURED 2026-08-22 on the Heisei card (godzilla_le, node 2 silenced by the
 * census): with every silenced node answering `ff`, bring-up re-probed node
 * 2's identity in 90-probe bursts every ~15 s until t=100.4 s - 1530 refusals
 * in all - and the attract light show (and with it the playfield's LED block,
 * autoattract's `past` signal, everything) waited on the last burst. Item 17's
 * run 12, taken BEFORE the carve-out existed, is the control: "every
 * [nbsilent] train sits in the first 20 s". A board that answers status but
 * refuses identity reads as alive-but-unidentified, and the game keeps trying
 * to identify it; a board that answers nothing is written off at the first
 * storm's end, which is what a real absent board looks like and is the whole
 * point of the silence. So total silence is again the default, and the
 * carve-out applies only where its benefit was actually measured: the
 * OPTIONAL node4-class boards on stranger_things' coil/switch service path,
 * whose refused `ff` cost every service pass ~3.3 s (item 52).
 *
 * PAD_NB_SILENT_FF: a comma/space list of node ids = answer `ff` on exactly
 * those silenced nodes (watch.sh computes it from nodecensus.py, the same
 * place the silence list comes from); "0" = none, the pre-item-52 total
 * silence; "1" or unset = every silenced node, item 52's original shape, kept
 * as the A/B knob. Node ids 0 and 1 are the CPU bridge and the cabinet board,
 * never silenced, so the two flag values collide with no real list. */
static int nb_silent_ff(unsigned node)
{
    static const char *ff = (const char *)-1;
    const char *s;
    if (ff == (const char *)-1) ff = getenv("PAD_NB_SILENT_FF");
    if (!ff || !*ff || (ff[0] == '1' && !ff[1])) return 1;
    if (ff[0] == '0' && !ff[1]) return 0;
    for (s = ff; *s; ) {
        unsigned v = 0;
        int any = 0;
        while (*s >= '0' && *s <= '9') { v = v * 10 + (unsigned)(*s++ - '0'); any = 1; }
        if (any && v == node) return 1;
        if (*s) s++;
    }
    return 0;
}

static void nb_nodes_add(unsigned node)
{
    char b[80];
    int i;
    if (!node || nb_nnodes < 0) return;
    if (nb_nnodes >= (int)sizeof nb_nodes) return;
    for (i = 0; i < nb_nnodes; i++) if (nb_nodes[i] == node) return;
    nb_nodes[nb_nnodes++] = (unsigned char)node;
    snprintf(b, sizeof b, "[nbsched] + node %u (board table)\n", node);
    logmsg(b);
}

/* THE SWITCH TABLE IS NOT THE WHOLE BUS, and believing it was cost ~25 s on
 * every single boot.
 *
 * nb_nodes_init() below derives the service schedule from the game's switch
 * table, one entry per switch, `entry[+20]` naming its node. That is a good
 * title-independent trick and it finds every board that carries a switch - on a
 * Godzilla Pro, nodes 4, 1, 8 and 9. It cannot find a board that carries none.
 *
 * The three LED boards - 7, 12 and 14 - carry no switches, so they were never
 * named by the `00` poll, so the service loop at 0x1d7d88 never serviced them,
 * so `0x1d8314` never set their `board[+4]` bit 1. That bit is a live ~10 Hz
 * "answered its last poll" heartbeat, and the Tech Alerts provider 0x39c6b8
 * only suppresses a board when `(flags & 3) == 3`. Three boards permanently
 * short of bit 1 means three permanent `Check Node Board N : Not Responding`
 * lines, and the game will not leave Tech Alerts while an alert is live.
 *
 * Measured: slots 7/12/14 sat at `flags=00000001` from 12.2 s and only reached
 * `00000003` at 35.3 s, by some slower path - and 35.3 s is exactly when a
 * Service Back hold started being accepted. That is the whole wait.
 *
 * So also take every board the GAME itself has registered. Two filters, and the
 * second one matters:
 *   - `[+12]` non-zero - the slot is in use at all.
 *   - `[+144]` non-zero - the board has devices assigned to it in the game's own
 *     static configuration. THIS IS WHAT KEEPS NODE 2 OUT. Node 2 is not fitted
 *     on a Godzilla Pro, its `[+144]` is 0, and servicing it would put the shim
 *     straight back into answering for an address the machine does not have -
 *     the exact fidelity bug PAD_NB_SILENT=2 exists to fix.
 *
 * Re-scanned rather than latched, because boards register over the first few
 * seconds and a one-shot scan at first use finds an empty table.
 * PAD_NB_SCHED_BOARDS=0 turns it off for an A/B. */
static void nb_nodes_add_boards(void)
{
    static int on = -1;
    unsigned id;
    if (on == -1) { char *q = getenv("PAD_NB_SCHED_BOARDS"); on = !(q && *q == '0'); }
    /* NB_OBJS is a Godzilla address; without it there is no board table to
     * scan and this must do nothing rather than walk from 0. */
    if (!on || nb_nnodes < 0 || !NB_OBJS) return;
    for (id = 1; id < 32; id++) {
        const unsigned char *o =
            (const unsigned char *)(unsigned long)(NB_OBJS + id * NB_OBJ_SZ);
        if (!*(const unsigned *)(o + 12)) continue;            /* slot unused */
        if (!*(const unsigned short *)(o + 144)) continue;     /* not fitted */
        nb_nodes_add(o[0]);
    }
}

static void nb_nodes_seed_log(const char *src)
{
    char b[180];
    int i, k = snprintf(b, sizeof b, "[nbsched] playfield nodes:");
    for (i = 0; i < nb_nnodes; i++)
        k += snprintf(b + k, sizeof b - (unsigned)k, " %u", nb_nodes[i]);
    snprintf(b + k, sizeof b - (unsigned)k, " (from %s)\n", src);
    logmsg(b);
}

static void nb_nodes_init(void)
{
    unsigned st = tread(SW_STRUCT);
    unsigned n  = tread(SW_COUNT);
    unsigned id;
    int i;
    if (nb_nnodes >= 0) return;

    /* PRIMARY: the switch table names every board that carries a switch
     * (entry[+20]). godzilla's path, and every title whose table resolves. */
    if (sw_ok(st) && n <= 4096) {
        nb_nnodes = 0;
        for (id = 1; id < n && nb_nnodes < (int)sizeof nb_nodes; id++) {
            unsigned node = ((const unsigned char *)(unsigned long)(st + id * 32))[20];
            if (!node) continue;                 /* 0 is the cabinet, over SPI */
            if (node == 0xffu) continue;         /* swelf poisons the ids its
                                                  * file table does not carry
                                                  * with node 0xff - a marker,
                                                  * not a board. batman seeded
                                                  * a bogus node 255 into the
                                                  * schedule off it (item 82) */
            if (nb_is_silent(node)) continue;    /* the machine does not have it
                                                  * - same fact, same filter as
                                                  * the fallback below */
            for (i = 0; i < nb_nnodes; i++) if (nb_nodes[i] == node) break;
            if (i == nb_nnodes) nb_nodes[nb_nnodes++] = (unsigned char)node;
        }
        /* item 52: a FILE table names only the boards that CARRY SWITCHES, so
         * seeding from it alone would strand the LED-only boards (ST: node 2
         * CABINET LIGHTS, node 12 TOPPER) - they are discovered on godzilla by
         * nb_nodes_add_boards(), which walks a board array that resolves by
         * shape there and can never resolve on ST (its array is dense, not
         * self-labelling). Merge the title's own declared directory, minus
         * the silenced - exactly the set the fallback below would have used.
         * A title whose table came from GAME MEMORY is untouched: its board
         * array resolves and add_boards() keeps doing this job. */
        if (sw_ftab_installed) {
            nb_fident_load();
            for (id = 1; id < 64 && nb_nnodes < (int)sizeof nb_nodes; id++) {
                if (!nb_fident_have[id] || nb_is_silent(id)) continue;
                for (i = 0; i < nb_nnodes; i++)
                    if (nb_nodes[i] == (unsigned char)id) break;
                if (i == nb_nnodes) nb_nodes[nb_nnodes++] = (unsigned char)id;
            }
            nb_nodes_seed_log("switch table + node directory");
            return;
        }
        nb_nodes_seed_log("switch table");
        return;
    }

    /* FALLBACK (item 52): a title with NO findable switch table - measured on
     * stranger_things, whose device table is empty and whose in-memory switch
     * table sw_find_table rejects as "(node,bit) not distinct". Without a seed
     * the bare-00 discovery walk (0x1d6f28) is told the bus is EMPTY on its
     * first ask, no board object is ever created, and bring-up wedges on
     * "LOCATING NODE BOARDS / <required> / NODES NOT FOUND" forever - even
     * though the game identifies every declared node correctly (its own static
     * directory drives that, and the shim answers all six of ST's with correct
     * replies). The boards are answerable; they were just never discovered.
     *
     * So seed the discovery schedule from the title's own NODE DIRECTORY - the
     * node_ident.txt nbdir.py derives and nb_fident_load() already reads - minus
     * any node the machine does not have (PAD_NB_SILENT). This breaks the
     * chicken-and-egg: board objects exist only after discovery, discovery ran
     * only from the switch/board tables, and both are empty until boards exist.
     *
     * IRONCLAD AGAINST TOUCHING A WORKING TITLE. `!sw_find_done` means no switch
     * table has been found by ANY route (configured or by-shape); godzilla sets
     * sw_find_done via sw_configured_ok before this is ever reached, and any
     * title whose table is found - even slowly - sets it too, so this branch is
     * permanently unreachable for them. sw_find_fails>=4 additionally keeps a
     * title whose table is merely a few searches late on the switch path. */
    if (sw_table_hopeless()) {
        nb_fident_load();
        nb_nnodes = 0;
        for (id = 1; id < 64 && nb_nnodes < (int)sizeof nb_nodes; id++) {
            if (!nb_fident_have[id]) continue;
            if (nb_is_silent(id)) continue;      /* the machine does not have it */
            nb_nodes[nb_nnodes++] = (unsigned char)id;
        }
        if (nb_nnodes == 0) {                    /* no directory either: keep waiting */
            nb_nnodes = -1;
            return;
        }
        nb_nodes_seed_log("node directory - no switch table");
        return;
    }
    /* still waiting: neither a switch table nor a settled directory fallback */
}

/* The answer to one `00` poll. */
/* The answer to the bare `00` poll, and it has TWO consumers that want
 * different things from it. Getting that wrong is what made bring-up
 * intermittent.
 *
 *   0x1d7d98, the service loop - services the node it is given and asks again,
 *     looping while the answer is non-zero. It only ever RETURNS on a zero, so
 *     a schedule that never says 0 spins the guest forever.
 *   0x1d6f28, the discovery walk inside bring-up - records the node it is given
 *     and asks again, and treats the first zero as "that is the whole bus".
 *     Whatever it has seen when the zero arrives IS the discovered set.
 *
 * The old schedule strictly alternated `node, 0, node, 0`. That is fine for the
 * service loop and WRONG for discovery: each walk saw exactly one node before
 * being told the bus was finished, so bring-up needed as many passes of its
 * loop at 0x1d73e4 as there are boards - and that loop is capped at 30 passes
 * with a 100 ms sleep and a full enumeration in each one. Whether it finished
 * inside a run was a race, and it lost about half the time: bring-up then never
 * reached the `ff` poll at 0x1d7630, so the per-node scan gate at
 * 0x7a908c+276+node was never written, no 0x11 was ever sent, and the game sat
 * on an empty Tech Alerts screen for the rest of the run.
 *
 * Emit the WHOLE list and then one zero. Discovery sees every board in a single
 * walk, and the service loop still gets its terminating zero every cycle - it
 * just services all of them per pass instead of one. */
static unsigned nb_next_node(void)
{
    static int on = -1, idx;
    if (on == -1) { char *q = getenv("PAD_NB_SCHED"); on = !(q && *q == '0'); }
    if (!on) return 0;
    nb_nodes_init();
    /* Pick up boards that registered since the last cycle. Done at the START of
     * a cycle, not mid-list, so the set the service loop walks cannot change
     * under it between the first node and the terminating zero. */
    if (idx == 0) nb_nodes_add_boards();
    if (nb_nnodes <= 0) return 0;
    /* ★ ITEM 52: THE PRIORITY LANE - a node with unserved switch NEWS is
     * named before the round-robin resumes, every cycle, until its scan is
     * answered.
     *
     * WHY THIS IS THE FIX AND NOT A TUNING. The game's service loop
     * (0x1d7d88) fetches a node's 0x11 switch scan INSIDE servicing that
     * node, one board per pass, and it asks US which node to service (the
     * bare `00` poll). Its own cadence is what it is - measured on
     * stranger_things IN A GAME, closures waited 0.5-2.8 s for their node's
     * turn (swlatch id=64 waited=2785 ms with a ball in play), and in the
     * guided-setup wizard a 113 ms tap read as a 3-7 s hold because node 8's
     * turn came round every ~3.3 s. Every earlier answer to "the flippers
     * feel late" tuned the SHIM (hold longer, latch a closure, minscans) -
     * all of which trade width for delivery and none of which move WHEN the
     * game looks. This moves WHEN: the round-robin is ours to order, and a
     * board with news goes first. A real bus master does the same thing -
     * it services the board that raised its line.
     *
     * The lane is a queue, not a hijack: news nodes are drained one per
     * call and then the round-robin continues exactly where it was, and the
     * terminating zero (the CABINET's only clock - see below) still comes
     * once per cycle. Godzilla is unaffected in the common case (no news =
     * no lane) and helped in the same way when it has news. */
    if (nb_lane_on == -1) { char *q = getenv("PAD_NB_LANE"); nb_lane_on = !(q && *q == '0'); }
    if (nb_lane_on) {
        int i;
        for (i = 0; i < nb_nnodes; i++) {
            unsigned n = nb_nodes[i];
            if (n < 64 && nb_news[n] == 1) {
                nb_news[n] = 2;             /* named; cleared when 0x11 answers */
                return n;
            }
        }
    }
    if (idx >= nb_nnodes) {
        idx = 0;
        /* ITEM 17: THIS ZERO IS THE CABINET, AND THIS IS ITS ONLY CLOCK.
         *
         * The game's runtime sweep (0x1d7d88) asks us who needs service and
         * keeps looping until we answer 0. Node 0 is BOTH the terminator and
         * the cabinet, so 0x1d6d58 - the only path there is from the SPI word
         * to NodeRec.cur - runs exactly once per cycle of this list. Emitting
         * the whole list before the zero therefore divides the cabinet's poll
         * rate by the number of boards, which is the shape of item 17: a
         * 300 ms button press is seen about 60% of the time and a 2 s hold
         * always is.
         *
         * Measure the period rather than inferring it from capture rates.
         * PAD_NB_SWEEP=1. */
        {
            static int on = -1;
            static unsigned long prev_ms;
            static unsigned cyc, budget = 300;
            if (on == -1) {
                char *q = getenv("PAD_NB_SWEEP");
                on = q && *q == '1';
            }
            if (on && budget > 0) {
                unsigned long now = pad_ms();
                char m[120];
                budget--;
                snprintf(m, sizeof m,
                         "[nbsweep] %lu ms cycle=%u nodes=%d since=%lu ms\n",
                         now, ++cyc, nb_nnodes,
                         prev_ms ? now - prev_ms : 0);
                logmsg(m);
                prev_ms = now;
            }
        }
        return 0;
    }
    return nb_nodes[idx++];
}

static void sw_prime(unsigned nid, const unsigned char bits[8])
{
    static unsigned char primed[64];
    unsigned char *rec;
    unsigned i;
    if (nid >= 64 || primed[nid]) return;
    if (!sw_ok(tread(SW_STRUCT))) return;
    primed[nid] = 1;
    rec = (unsigned char *)(unsigned long)SW_NODEREC(nid);
    for (i = 0; i < 8; i++) { rec[12 + i] = bits[i]; rec[20 + i] = bits[i]; }
    {
        char m[140];
        snprintf(m, sizeof m,
                 "[swprime] node=%u cur[]=prev[]=%02x%02x%02x%02x%02x%02x%02x%02x\n",
                 nid, bits[0], bits[1], bits[2], bits[3], bits[4], bits[5],
                 bits[6], bits[7]);
        logmsg(m);
    }
}

/* ---- the keyboard channel ----------------------------------------------
 *
 * padglhost owns the X11 window and is the only thing that can see a key
 * press; the switches are filled in here, inside the emulated game. The two
 * share a small file under /dump (padsw.h), exactly as they already share the
 * GL ring. PAD_SW_SHM names it; unset means no keyboard, and everything else
 * still works.
 *
 * Read with no lock: take gen, read the bytes, take gen again. A disagreement
 * means the host wrote mid-read, and the cost of using the older byte for one
 * scan is one frame of a switch being wrong - indistinguishable from the
 * contact bounce the game already debounces.
 */
/* Declared up with the other switch forward declarations, because the SPI
 * ioctl - which is where a tap is actually served - comes earlier in this file
 * than this section does. */

/* RETRIED, not tried once. watch.sh deletes the file and padglhost only creates
 * it inside win_open() - which runs when the WINDOW opens, i.e. on the game's
 * first rendered frame, tens of seconds after the guest starts. A single
 * attempt at the first switch scan can therefore land before the file exists
 * and kill the keyboard for the whole run. The retry is rate limited because
 * the caller is the unpaced SPI spin. */
static void sw_shm_init(void)
{
    static unsigned tick;
    char *path;
    int fd;
    void *m;
    if (sw_shm) return;
    if (tick++ & 0x3ffu) return;
    path = getenv("PAD_SW_SHM");
    if (!path || !*path) return;
    init();
    fd = real_open(path, 2 /* O_RDWR */, 0);
    if (fd < 0) return;
    if (!real_mmap) real_mmap = dlsym(RTLD_NEXT, "mmap");
    if (!real_mmap) return;
    /* PROT_READ|PROT_WRITE, MAP_SHARED - RDWR because a read-only private map
     * would not see the host's later writes at all, which is the whole point. */
    m = real_mmap(0, 4096, 1 | 2, 0x01, fd, 0);
    if (m == (void *)-1) return;
    sw_shm = (volatile struct padsw_shm *)m;
    {
        char b[160];
        snprintf(b, sizeof b, "[swshm] %s mapped at %p magic=0x%08x\n",
                 path, m, sw_shm->magic);
        logmsg(b);
    }
}

/* ---- THE MERGE. Two writers, one answer, and it is NOT an OR ------------
 *
 * padglhost owns held[] and rebuilds it from its key state on every key event;
 * the scripts own scr_held[]. Before the split there was one array and the
 * rebuild wiped the scripts' work on every key press - the scoop click that
 * did not register and the plunge that looked dead (REMAINING item 7).
 *
 * OR IS THE OBVIOUS MERGE AND IT IS WRONG. padglhost latches the coin door and
 * all six trough balls ON when its window opens, because that is a machine at
 * rest, so `held[66] == 1` for the whole run. Under an OR plunge.py could never
 * take a ball out of the trough again - it would have swapped a stomp for a
 * deadlock, and the deadlock is worse because it looks deliberate.
 *
 * LAST EDGE WINS, PER ID. Each side is compared against what it said last time;
 * only ids that MOVED are copied into the answer. A rebuild that re-asserts
 * held[66] = 1 has not moved anything, so it cannot touch a 66 the script just
 * opened - while pressing B, which really does move it, still wins immediately.
 * Same-poll ties go to the keyboard: the window is one SPI iteration, so a true
 * tie is a coincidence, and when a human and a script really do fight over one
 * switch the human should win.
 *
 * The merged bytes are published back into mrg[] so a reader outside the guest
 * can see what the game was handed rather than one of the two inputs. Nothing
 * in the input path reads mrg[] back; it is an output. */
static unsigned char sw_kbd_prev[256];
static unsigned char sw_scr_prev[256];
static unsigned char sw_mrg[256];
/* item 43: which ids have EVER seen a real edge through the merge. A fresh
 * block is all zeros and zeros carry no meaning - the door gate misread that
 * window as "door open" and refused every backdrop pipeline of an ordinary
 * boot. An id with no edge yet has NO known state. */
static unsigned char sw_edged[256];

/* ---- THE ONE-SCAN LATCH. REMAINING item 17, and the whole of it. -----------
 *
 * MEASURED 2026-08-06, and it is not what the item guessed. A ladder of script
 * pokes at 10/20/30/50/80/120/200/400/900 ms (swladder.py) was read off the
 * game's OWN entry[+24] with PAD_SW_PEND, and every single failure had ZERO
 * samples inside the closure - the game had not looked. Every closure it did
 * look at registered, down to 10 ms, off ONE scan with the switch made. So:
 *
 *   there is NO minimum closure width and NO debounce problem. There is a
 *   SAMPLING RATE, and it is the game's, not ours.
 *
 * The 0x11 switch scan is REQUEST-driven: the game asks per node when its own
 * service loop gets round to it, and the shim only answers. In attract that can
 * leave hundreds of milliseconds between two looks at one node - a 400 ms poke
 * on node 8 was missed 4 times out of 4 in the same run where a 10 ms poke on
 * node 1 landed 4 times out of 4. That is "hold the key longer and it works",
 * exactly as reported, and holding longer only helps because it buys more
 * chances to be looked at. It is a lottery with better odds, not a fix.
 *
 * So a closure is OWED a scan: when the merged state goes 1 -> 0 without ever
 * having been placed on the wire as made, the release is deferred and the next
 * scan of that switch's node reports it made once. One scan is enough - that is
 * the measurement above, not an assumption - and PAD_SW_MINSCANS raises it if a
 * title ever needs more.
 *
 * THIS IS NOT THE SAME AS `tap_reads`, and both are worth having. A tap is a
 * request for a press of a stated length, counted in SPI transfers, aimed at
 * the cabinet's menu auto-repeat. This is automatic, applies to every writer
 * including the keyboard, and is counted in scans OF THE SWITCH'S OWN NODE,
 * which is the only clock that decides whether the game sees anything.
 *
 * THE LIMIT, stated because it is the next thing that will be blamed: a closure
 * shorter than the merge's own poll (~640 us, the paced SPI loop) is invisible
 * here too, because both edges land between two reads of the shared block and
 * the merge never moves. No human keystroke is that short; a script could be.
 * PAD_SW_LATCH=0 turns the whole thing off for an A/B on one build. */
static int sw_latch_budget = 400;        /* [swlatch] lines; saturates, see below */
static unsigned char sw_owed[256];       /* a closure still waiting for a scan */
static unsigned char sw_src[256];        /* who moved it last; see padsw.h     */
static unsigned char sw_served[256];     /* it has been on the wire as made    */
static unsigned long sw_made_at[256];    /* when it closed, for the log line   */
static unsigned long sw_shut_at[256];    /* when it opened again               */

/* ---- THE RIP. Item 26, and padsw.h owns the why. ---------------------------
 *
 * While the host holds spin[id] set, the level reported for id ALTERNATES on
 * successive scans of its own node - a closure per two scans, the maximum rate
 * a diffed level can carry, at whatever rate the game actually scans. Nothing
 * here touches the merge, sw_owed[] or sw_served[]: those book-keep the merged
 * state, the rip rides above it, and when the flag clears the report falls
 * back to the merge - which is OPEN unless something else really holds the
 * switch, so a rip cannot strand a switch closed.
 *
 * The stop line is also a MEASUREMENT, and it is one this rig has never had:
 * closures delivered over the rip's own duration is the per-node scan rate of
 * a live game, directly, on whatever screen the game was showing. Item 17
 * measured 670 ms between scans of one node in attract; nobody has measured
 * during play, and item 46 wants the same number. */
static unsigned char sw_spin_on[256];    /* a rip was seen in progress         */
static unsigned char sw_spin_phase[256]; /* the level the NEXT scan reports    */
static unsigned sw_spin_scans[256];      /* scans of its node while ripping    */
static unsigned sw_spin_made[256];       /* how many of them reported MADE     */
static unsigned long sw_spin_t0[256];    /* pad_ms() when the rip began        */
static int sw_spin_budget = 200;         /* [swspin] lines; saturates          */

static int sw_latch_on(void)
{
    static int on = -1;
    if (on == -1) { char *q = getenv("PAD_SW_LATCH"); on = !(q && *q == '0'); }
    return on;
}

static unsigned sw_latch_scans(void)
{
    static unsigned n = (unsigned)-1;
    if (n == (unsigned)-1) {
        char *p = getenv("PAD_SW_MINSCANS");
        unsigned v = 0;
        while (p && *p >= '0' && *p <= '9') v = v * 10 + (unsigned)(*p++ - '0');
        n = v ? v : 1;
    }
    return n;
}

static void sw_shm_merge(void)
{
    static unsigned seen_k = (unsigned)-1, seen_s = (unsigned)-1;
    unsigned kg, sg, ktag, stag;
    int n, moved = 0;
    if (!sw_shm || sw_shm->magic != PADSW_MAGIC) return;
    kg = sw_shm->gen;
    sg = sw_shm->scr_gen;
    if (kg == seen_k && sg == seen_s) return;
    seen_k = kg; seen_s = sg;
    /* WHO SAID SO. Read here, once, alongside the generations that brought us
     * in - not per id, which would let a writer's tag change halfway down the
     * array and split one press across two names. padsw.h has the letters and
     * the one case this cannot resolve (two scripts inside one merge). */
    ktag = sw_shm->kbd_src ? sw_shm->kbd_src : '?';
    stag = sw_shm->scr_src ? sw_shm->scr_src : '?';
    for (n = 0; n < 256; n++) {
        unsigned char k = sw_shm->held[n] ? 1 : 0;
        unsigned char s = sw_shm->scr_held[n] ? 1 : 0;
        unsigned char want = sw_mrg[n];
        unsigned char src = 0;
        if (k != sw_kbd_prev[n])      { want = k; src = (unsigned char)ktag; }
        else if (s != sw_scr_prev[n]) { want = s; src = (unsigned char)stag; }
        sw_kbd_prev[n] = k;
        sw_scr_prev[n] = s;
        if (want != sw_mrg[n]) {
            sw_mrg[n] = want;
            sw_src[n] = src ? src : '?';
            sw_edged[n] = 1;                       /* item 43: state now known */
            moved = 1;
            /* item 52: RAISE THE NEWS for this switch's node - the priority
             * lane in nb_next_node() names it at the head of the next service
             * cycle. Read through the resolved table so it holds for a found,
             * configured or file table alike; node 0 is the cabinet (SPI, not
             * the bus) and is skipped. */
            {
                unsigned st = tread(SW_STRUCT), cnt = tread(SW_COUNT);
                if (sw_ok(st) && (unsigned)n < cnt && cnt <= 4096) {
                    unsigned node = ((const unsigned char *)(unsigned long)
                                     (st + (unsigned)n * 32))[20];
                    if (node && node < 64 && nb_news[node] != 1)
                        nb_news[node] = 1;
                }
            }
            /* The latch bookkeeping lives HERE because this is the only place
             * the merged answer moves, and the merged answer is what the game
             * is handed. Doing it at either input would count a keyboard
             * rebuild that re-asserted a byte as an edge. */
            if (want) {
                sw_served[n] = 0;
                sw_made_at[n] = pad_ms();
            } else if (!sw_served[n] && sw_latch_on()) {
                sw_owed[n] = (unsigned char)sw_latch_scans();
                sw_shut_at[n] = pad_ms();
            }
        }
    }
    if (!moved) return;
    for (n = 0; n < 256; n++) sw_shm->mrg[n] = sw_mrg[n];
    __sync_synchronize();
    sw_shm->mrg_gen++;
}

/* PAD_LATENCY=1 - the two ends of "why does it feel slow".
 *
 * This line is the moment the GUEST first observes a key/switch change the host
 * published. Pair it with alsastub's "[lat] pcm resumed" and, with
 * PAD_LOG_TIME=1 putting both on the one clock, the difference is the GAME's own
 * reaction time - the part no amount of buffer tuning can touch. Measure that
 * before shrinking anything, or you will tune the wrong term. */
static int lat_on(void)
{
    static int on = -1;
    if (on < 0) { const char *e = getenv("PAD_LATENCY"); on = (e && *e && *e != '0'); }
    return on;
}

/* The change counter the SPI path caches against. It is the SUM of the two
 * input generations because either writer moving is a reason to rebuild, and
 * both only ever count up, so the sum only ever counts up too. It is NOT the
 * "has the host published" test - that one wants the host's own counter and
 * asks sw_shm->gen directly; see sw_rest_pending(). */
static unsigned sw_shm_gen(void)
{
    static unsigned last;
    unsigned g;
    if (!sw_shm || sw_shm->magic != PADSW_MAGIC) return 0;
    g = sw_shm->gen + sw_shm->scr_gen;
    if (g != last) {
        last = g;
        if (lat_on()) {
            char b[80];
            snprintf(b, sizeof b, "[lat] switch gen=%u observed by the guest\n", g);
            pad_say(b);
        }
    }
    return g;
}

/* The merged answer, never one of the two inputs. Cheap: sw_shm_merge() returns
 * on an unchanged pair of generations, which is the common case by far. */
static int sw_shm_held(unsigned id)
{
    if (!sw_shm || sw_shm->magic != PADSW_MAGIC || id >= 256) return 0;
    sw_shm_merge();
    return sw_mrg[id] != 0;
}

/* item 43: gstvid.c (same .so, separate translation unit) asks about the coin
 * door to decide whether video pipelines may start - see the door gate in
 * pad_vid_prepare. The merged level, same answer the game gets - EXCEPT that
 * an id nobody has ever edged answers -1, "no known state", NOT 0. The block
 * starts as all zeros and those zeros carry no meaning; the gate's first
 * version read the boot window's zeros as "door open" and refused every
 * backdrop pipeline of a perfectly ordinary run - David's first try lost the
 * Tech Alerts / splash backgrounds to exactly this. The playfield window
 * stamps the door CLOSED (an edge) when it comes up, so a normal session
 * reaches a known 1 shortly after boot; PAD_DOOR_OPEN forces a 1->0 edge
 * before the game's video manager initialises. */
int pad_sw_level(unsigned id)
{
    if (id >= 256 || !sw_shm || sw_shm->magic != PADSW_MAGIC) return -1;
    sw_shm_merge();
    if (!sw_edged[id]) return -1;
    return sw_mrg[id] != 0;
}

/* [sw] - every EDGE in the MERGED switch state, logged at the point the shim
 * consumes it. This is the switch-input instrument the rig lacked: a click on
 * the virtual playfield, a plunge.py sequence and a keyboard flipper all funnel
 * through here, and "the script pressed it" and "the game was handed it" are
 * different claims - only the second one is evidence.
 *
 * It reads the MERGED array on purpose, not held[]: the merge is what the game
 * is handed, so an edge here is an edge the game saw. That also keeps the
 * measurement comparable across the split - before it, held[] and the merge
 * were the same thing, so a before/after run compares like with like. Which is
 * how the two-writers clobber was finally measured rather than argued about:
 * with one array, a 3000 ms `swpoke.py 53` logged its `-53` at the next key
 * event instead of 3000 ms later, and plunge.py's `-66` was followed by a `+66`
 * nobody asked for.
 *
 * One line per generation bump that changed anything, and each edge carries the
 * LETTER OF WHOEVER MOVED IT: "[sw] 12345 ms +59k -66l" is a key press and a
 * plunge. padsw.h owns the alphabet. That letter is what makes the line
 * REPLAYABLE rather than merely readable - without it a replay cannot tell
 * David's flipper from autoattract's Service Back, and re-delivering the second
 * one fights the next run's own autoattract. `?` means nobody said, which is
 * either a writer that has not been taught to tag itself or an edge the merge
 * saw between two tags.
 *
 * PAD_SW_LOG=0 turns it off; the budget stops a runaway (a stuck writer
 * bumping gen forever) from flooding the log. watch.sh forwards these to its
 * [event] stream. */
static void sw_shm_edges(void)
{
    static unsigned char prev[256];
    static int primed;
    static int budget = 2000;
    static int on = -1;
    char line[160];
    int n, len, count = 0;
    if (on == -1) { char *q = getenv("PAD_SW_LOG"); on = !(q && *q == '0'); }
    if (!sw_shm || sw_shm->magic != PADSW_MAGIC) return;
    /* The clock goes out even with the log off, because it is not part of the
     * log: swreplay.py needs the guest's millisecond to schedule against, and a
     * replay run has every reason to want PAD_SW_LOG on but no reason to
     * REQUIRE it. pad_ms() first, because the base is armed lazily. */
    (void)pad_ms();
    sw_shm->guest_t0_ms = (unsigned)pad_ms_base;
    if (!on || budget <= 0) return;
    sw_shm_merge();
    if (!primed) {
        for (n = 0; n < 256; n++) prev[n] = sw_mrg[n];
        primed = 1;
        return;
    }
    len = snprintf(line, sizeof line, "[sw] %lu ms", pad_ms());
    for (n = 0; n < 256; n++) {
        unsigned char cur = sw_mrg[n];
        if (cur == prev[n]) continue;
        prev[n] = cur;
        if (len < (int)sizeof line - 10)
            len += snprintf(line + len, sizeof line - len, " %c%d%c",
                            cur ? '+' : '-', n,
                            sw_src[n] ? sw_src[n] : '?');
        count++;
    }
    if (!count) return;
    snprintf(line + len, sizeof line - len, "\n");
    logmsg(line);
    if (--budget == 0) logmsg("[sw] edge budget spent (PAD_SW_LOG)\n");
}

/* THE HOST DOES NOT OWN THE LATCHING SWITCHES UNTIL IT HAS SPOKEN.
 *
 * sw_hold_init() skips sw_rest_ids[] whenever PAD_SW_SHM is set, on the theory
 * that padglhost defaults them ON so forcing them here would only stop `C` from
 * opening the door again. The first half of that is true; the timing is not.
 * padglhost latches its toggles and publishes inside win_open(), and win_open()
 * runs when the WINDOW opens - on the game's first rendered frame, which is
 * tens of seconds into the boot. Until then held[] is all zeroes, and all-zeroes
 * means COIN DOOR OPEN and TROUGH EMPTY, straight through the part of the boot
 * that latches the door into [0x706464] and decides whether the ball devices
 * have their balls.
 *
 * So the machine-at-rest set applies until gen becomes non-zero, and not one
 * scan longer: padglhost writes gen=1 in sw_shm_open() before it publishes
 * anything, so a non-zero gen means "the host is now authoritative" and `C`
 * works exactly as before. PAD_SW_REST=0 still disables the whole thing. */
static int sw_rest_pending(unsigned id)
{
    static int said;
    unsigned i;
    char *p;
    if (!sw_rest_on) return 0;
    /* Only meaningful when a HOST is expected. With PAD_SW_SHM unset the ids are
     * already in sw_active[] and this would just log a confusing line. */
    p = getenv("PAD_SW_SHM");
    if (!p || !*p) return 0;
    /* sw_shm->gen, NOT sw_shm_gen(): this asks specifically whether the HOST
     * has published, and sw_shm_gen() now also counts the script generation. A
     * script that wrote before padglhost's window opened would otherwise end
     * the machine-at-rest set early, which is the very window this exists for. */
    if (sw_shm && sw_shm->magic == PADSW_MAGIC && sw_shm->gen) {
        if (said == 1) {
            said = 2;
            logmsg("[swrest] host published - it now owns the door and the trough\n");
        }
        return 0;
    }
    if (!said) {
        said = 1;
        logmsg("[swrest] host has not published yet - holding the machine at rest\n");
    }
    sw_rest_resolve();                 /* item 27: per-title trough ids */
    for (i = 0; i < sw_rest_n; i++)
        if (sw_rest_set[i] == id) return 1;
    return 0;
}

static int sw_scan_bytes(unsigned nid, unsigned char out[8])
{
    unsigned st, n, id;
    int placed = 0;

    out[0] = out[1] = out[2] = out[3] = 0;
    out[4] = out[5] = out[6] = out[7] = 0;
    /* THIS IS WHERE THE SECOND TITLE DIED. Both addresses are Godzilla Pro
     * 1.15.0's and TMNT's image stops well short of them, so the two loads at
     * the top of this function - before any check ran - killed the game 0.06 s
     * in. Resolve first, and answer "no switch state" for a title whose table
     * we cannot find, which costs the keyboard and costs the game nothing. */
    if (!SW_STRUCT || !SW_COUNT) return 0;
    st = tread(SW_STRUCT);
    n  = tread(SW_COUNT);
    if (!sw_ok(st) || n > 4096) return 0;
    sw_hold_init();
    sw_shm_init();

    for (id = 1; id < n; id++) {
        const unsigned char *e =
            (const unsigned char *)(unsigned long)(st + id * 32);
        unsigned bit  = *(const unsigned short *)(e + 18);
        unsigned node = e[20];
        unsigned cfg  = *(const unsigned *)(e + 8);
        int level;
        if (node != nid || bit >= 64) continue;
        level = sw_inactive_level(cfg);
        {
            int held = (id < sizeof sw_active && sw_active[id]) ||
                       sw_shm_held(id) || (int)id == pad_tap_id ||
                       sw_rest_pending(id);
            /* sw_shm_held() ran the merge, so sw_owed[] is current by the time
             * it is read - order matters and this is why the call is not
             * short-circuited away. An OWED closure is one whose release was
             * deferred because the game had not looked yet; report it made for
             * this scan and count the scan down. See the long comment on
             * sw_owed[] - this is item 17's whole fix. */
            if (!held && id < 256 && sw_owed[id]) {
                held = 1;
                if (--sw_owed[id] == 0 && sw_latch_budget > 0) {
                    char m[140];
                    sw_latch_budget--;
                    /* TWO numbers, because the first version printed one and
                     * mislabelled it. `closure` is how long the switch was
                     * really made; `waited` is how long it then sat owed before
                     * node `nid` was scanned at all - and THAT is the number
                     * this item is about, since it is the game's sampling gap
                     * measured directly. Printing press-to-scan as "the
                     * closure" made a 30 ms poke look like a 593 ms one. */
                    snprintf(m, sizeof m,
                             "[swlatch] %lu ms id=%u node=%u closure=%lu ms "
                             "waited=%lu ms for a scan (held %u)\n",
                             pad_ms(), id, nid,
                             sw_shut_at[id] - sw_made_at[id],
                             pad_ms() - sw_shut_at[id], sw_latch_scans());
                    logmsg(m);
                }
            } else if (held && id < 256) {
                /* On the wire as made, so nothing is owed for this closure. */
                sw_served[id] = 1;
                sw_owed[id] = 0;
            }
            /* THE RIP OVERRIDES A HOLD on purpose: the game diffs levels, so
             * "made forever" is one closure and a rip has to keep making
             * edges. See the long comment on sw_spin_on[]. */
            if (id < 256 && sw_shm && sw_shm->magic == PADSW_MAGIC &&
                sw_shm->spin[id]) {
                if (!sw_spin_on[id]) {
                    sw_spin_on[id] = 1;
                    sw_spin_phase[id] = 1;     /* first scan reports MADE */
                    sw_spin_scans[id] = 0;
                    sw_spin_made[id] = 0;
                    sw_spin_t0[id] = pad_ms();
                    if (sw_spin_budget > 0) {
                        char m[96];
                        sw_spin_budget--;
                        snprintf(m, sizeof m,
                                 "[swspin] %lu ms id=%u node=%u rip START\n",
                                 pad_ms(), id, nid);
                        logmsg(m);
                    }
                }
                held = sw_spin_phase[id];
                sw_spin_phase[id] ^= 1;
                sw_spin_scans[id]++;
                sw_spin_made[id] += held;
            } else if (id < 256 && sw_spin_on[id]) {
                /* The flag cleared: stop overriding - the merge is OPEN unless
                 * something really holds it - and state what was delivered.
                 * closures/s IS the per-node scan rate over two, measured on
                 * the live game; no other instrument has ever had it. */
                sw_spin_on[id] = 0;
                if (sw_spin_budget > 0) {
                    char m[160];
                    unsigned long dt = pad_ms() - sw_spin_t0[id];
                    sw_spin_budget--;
                    if (!dt) dt = 1;
                    snprintf(m, sizeof m,
                             "[swspin] %lu ms id=%u node=%u rip END: "
                             "%u closures in %lu ms (%lu/s; node scanned "
                             "%u times, %lu scans/s)\n",
                             pad_ms(), id, nid, sw_spin_made[id], dt,
                             (unsigned long)sw_spin_made[id] * 1000ul / dt,
                             sw_spin_scans[id],
                             (unsigned long)sw_spin_scans[id] * 1000ul / dt);
                    logmsg(m);
                }
            }
            if (held) level = !level;
        }

        /* ---- THE SELF-CORRECTING RESYNC IS GONE, AND MUST NOT COME BACK ---
         *
         * There used to be a phase machine here that read back entry[+24], and
         * on a persistent disagreement deliberately put the WRONG bit on the
         * wire for one reply so the next honest one would land with a fresh odd
         * pending count. It fired 210 times per run and it was chasing a defect
         * that lived in this file: the 0x11 reply was being XOR-scrambled with
         * rol8(frame checksum, c) while the game decoded with a key of zero.
         * See the key comment on the 0x11 branch of the reply builder.
         *
         * With the key right, the band-aid measured ZERO firings across a full
         * 115 s run - it had nothing left to correct - so it is deleted rather
         * than left switched off. Anything that starts injecting deliberate
         * extra edges again is papering over a new decode bug; find that
         * instead. PAD_SW_PEND is the instrument: it prints the bit the shim
         * sent next to the bit the game recorded in NodeRec.cur[], and those
         * two must be equal on every single sample. */
        if (id < 256) sw_sent[id] = (unsigned char)level;
        if (level) out[bit >> 3] |= (unsigned char)(1u << (bit & 7));
        placed = 1;
    }
    return placed;
}

/* PAD_SW_TAP=<ids> / PAD_SW_TAP_AT=<bus writes> - press and RELEASE each id in
 * turn, through the scan, so the game sees a real edge pair. Separate from the
 * old PAD_SW_PRESS, which calls 0x1da600 directly and is inert. */
/* PAD_SW_WATCH=<ids> - log the THREE representations of these ids on every bus
 * write, bounded. This is the instrument that says where a press stops:
 *   lvl   entry[+24], the electrical level the scan wrote
 *   log   0x1e6d90(id), the same thing converted to logical (inverting)
 *   raw   raw[id], the debounced state 0x1e67c4 returns
 *   bmp   bit (id&15) of the packed bitmap at 0x7e29ec+0x60+(id>>4)*2
 * A press that moves lvl but not raw/bmp has reached the scan and stopped at
 * the debounce; one that moves none of them never reached the game at all. */
static void sw_watch(void)
{
    static char *list = (char *)-1;
    static int budget = 600;
    static unsigned n;
    unsigned st, raw, cnt;
    char line[300];
    char *p;
    int k = 0;

    if (list == (char *)-1) list = getenv("PAD_SW_WATCH");
    if (!list || !*list || budget <= 0) return;
    if (++n % 20) return;
    st  = tread(SW_STRUCT);
    raw = tread_at(SW_STRUCT, 4);
    cnt = tread(SW_COUNT);
    if (!sw_ok(st) || !sw_ok(raw) || cnt > 4096) return;
    budget--;
    k = snprintf(line, sizeof line, "[swwatch] n=%-6u", n);
    for (p = list; *p && k < (int)sizeof line - 60; ) {
        unsigned id = 0;
        const unsigned char *e;
        unsigned cfg, lvl, lg, bmp;
        while (*p >= '0' && *p <= '9') id = id * 10 + (unsigned)(*p++ - '0');
        while (*p && (*p < '0' || *p > '9')) p++;
        if (!id || id >= cnt) continue;
        e   = (const unsigned char *)(unsigned long)(st + id * 32);
        cfg = *(const unsigned *)(e + 8);
        lvl = e[24];
        lg  = sw_ok(cfg) && (*(const unsigned short *)(unsigned long)(cfg + 28) & 4)
              ? lvl : (lvl ^ 1u);
        bmp = (*(const unsigned short *)(unsigned long)
                (0x7e29ecu + 0x60u + (id >> 4) * 2u) >> (id & 15)) & 1u;
        k += snprintf(line + k, sizeof line - (unsigned)k,
                      "  id=%u lvl=%u log=%u raw=%u bmp=%u", id, lvl, lg,
                      ((const unsigned char *)(unsigned long)raw)[id], bmp);
    }
    snprintf(line + k, sizeof line - (unsigned)k, "\n");
    logmsg(line);
}

/* Milliseconds since the first call. Bus-write counts looked like a clock and
 * are not one: the service loop's rate swings between ~50/s and ~212/s
 * depending on what the game is doing, so a tap scheduled at "write 8000"
 * landed at 38 s in one run and never fired at all in the next. Anything that
 * has to happen at a known MOMENT gets a real clock. */
static unsigned long pad_ms(void)
{
    static int (*cg)(int, void *);
    unsigned long t[2] = { 0, 0 };
    unsigned long ms;
    if (!cg) cg = dlsym(RTLD_NEXT, "clock_gettime");
    if (!cg) return 0;
    cg(1 /* CLOCK_MONOTONIC */, t);
    ms = t[0] * 1000ul + t[1] / 1000000ul;
    if (!pad_ms_base) pad_ms_base = ms;
    return ms - pad_ms_base;
}

/* ---- PAD_AUDIO_DUMP=<seconds> : the audio subsystem, without a crash --------
 *
 * Everything below already existed, but ONLY inside the SIGSEGV handler, which
 * means the one run that could report the state of the mixer was the one run
 * that had already fallen over. "the game writes no PCM" has been carried in
 * the handoff for several passes on the strength of that, i.e. on a snapshot
 * taken at the queue-null fault and never re-checked once the fault was gone.
 *
 * Time based, not bus-write based: a game sitting in a menu barely touches the
 * node bus, and a counter that stops looks exactly like a subsystem that
 * stopped. Driven from both the node bus write path and the SPI spin.
 *
 * What each line answers:
 *   [aud] writei    - has snd_pcm_writei EVER been called (frames + calls)
 *   [aud] voice[n]  - the 8 mixer slots: which have a stream and a queue
 *   [aud] pool      - the free ring, and whether it is empty (the old wall)
 *   [aud] list+XX   - the three queue lists, each queue's fd/total/avail/pops
 *   [aud] gate      - 0x7acb54, non-zero at worker start = worker wedged
 */
extern unsigned long pad_pcm_frames;   /* alsastub.c */
extern unsigned long pad_pcm_calls;    /* alsastub.c */
extern unsigned pad_pcm_rate;          /* alsastub.c - what the game ASKED for */
extern unsigned pad_pcm_channels;      /* alsastub.c */
extern unsigned long pad_pcm_played(void);
extern unsigned long pad_pcm_drops(void);
extern unsigned long pad_pcm_center(void);
extern unsigned long pad_pcm_backlog_ms(void);
extern unsigned long pad_pcm_buffer_ms(void);
extern unsigned long pad_pcm_fifo_ms(void);

/* A RANGE CHECK IS NOT A MAPPING CHECK, and this used to be only the former.
 * 0x10000..0xb0000000 says yes to every Godzilla address in this file, which is
 * correct on Godzilla and fatal on a title whose image is smaller: the audio
 * dump walks a voice table at 0x7b90c0 that TMNT does not have. Ask the kernel
 * as well - the range test stays because it is free and rejects the obvious. */
static int aud_readable(unsigned long p)
{
    return p > 0x10000 && p < 0xb0000000 && addr_readable((const void *)p);
}

static void audio_dump(void)
{
    char b[240];
    unsigned long pool;
    int n;

    snprintf(b, sizeof b,
             "[aud] --- %lu ms --- writei calls=%lu frames=%lu (%lu.%01lu s @ %u Hz "
             "x %u ch)  main played=%lu dropped=%lu  center=%lu  gate=%d"
             "  latency=%lu/%lu ms  fifo=%lu ms\n",
             pad_ms(), pad_pcm_calls, pad_pcm_frames,
             pad_pcm_rate ? pad_pcm_frames / pad_pcm_rate : 0,
             pad_pcm_rate ? (pad_pcm_frames * 10 / pad_pcm_rate) % 10 : 0,
             pad_pcm_rate, pad_pcm_channels,
             pad_pcm_played(), pad_pcm_drops(), pad_pcm_center(),
             gate_val(),
             pad_pcm_backlog_ms(), pad_pcm_buffer_ms(), pad_pcm_fifo_ms());
    logmsg(b);

    /* ★ EVERYTHING BELOW IS GODZILLA PRO 1.15.0's, AT FIXED ADDRESSES, AND THE
     * TITLE IS THE ONLY HONEST TEST FOR IT. This block already said "check
     * before walking rather than after crashing" and then checked the wrong
     * thing: aud_readable() asks whether an address can be READ, not whether
     * it holds what we think. On turtles_pro 0x7b90c0 and the queue pool are
     * perfectly readable - they are simply another title's data - so every
     * guard passed and the walk below dereferenced whatever happened to be
     * there.
     *
     * THAT IS ITEM 41'S CRASH, and it was OURS, not the game's. David's
     * captured signature: pc=hwshim.so+0x8e72, which is the `*(node + 8)` in
     * the pool-list walk further down. The app passes PAD_AUDIO_DUMP=30 on
     * every run, so this fires from ioctl() on the first audio ioctl after
     * each 30 s window - which is why it looked like "press a flipper on that
     * screen and it dies": the flipper makes a sound, the sound is an ioctl,
     * and the ioctl walked a stranger's linked list.
     *
     * a_sw_struct() is the rig's existing test for "this is the title those
     * addresses came from" - the segv handler uses it for exactly this reason,
     * and David's crash output proves it answers correctly here ("loader-gate
     * addresses are Godzilla Pro's; not reported for this title"). */
    if (!a_sw_struct()) {
        logmsg("[aud] mixer/pool dump skipped: those addresses are Godzilla"
               " Pro's and this is not that title\n");
        return;
    }

    for (n = 0; n < 8 && aud_readable(0x7b90c0UL); n++) {
        unsigned char *v = (unsigned char *)(0x7b90c0UL + n * 64);
        unsigned long *vw = (unsigned long *)v;
        if (!vw[0] && !vw[14]) continue;          /* empty slot, say nothing */
        snprintf(b, sizeof b,
                 "[aud] voice[%d] stream=0x%08lx pos=%lu queue=0x%08lx en=%d "
                 "vol=%d/%d ch=%d\n",
                 n, vw[0], vw[3], vw[14], v[0x35],
                 *(short *)(v + 0x30), *(short *)(v + 0x32), v[0x1a]);
        logmsg(b);
    }

    if (!aud_readable(0x7b8990UL + 0x100)) {
        logmsg("[aud] no queue pool pointer at 0x7b8a90 in this title\n");
        return;
    }
    pool = *(unsigned long *)(0x7b8990UL + 0x100);
    if (!aud_readable(pool)) {
        snprintf(b, sizeof b, "[aud] queue pool [0x7b8a90] = 0x%lx (not built yet)\n",
                 pool);
        logmsg(b);
        return;
    }
    {
        unsigned long *p = (unsigned long *)pool;
        snprintf(b, sizeof b,
                 "[aud] pool=0x%lx free ring head=0x%08lx end=0x%08lx empty=%d\n",
                 pool, p[0x74 / 4], p[0x84 / 4], p[0x84 / 4] == p[0x74 / 4]);
        logmsg(b);
    }
    {
        int off[3], k;
        off[0] = 0x94; off[1] = 0x9c; off[2] = 0xa4;
        for (k = 0; k < 3; k++) {
            unsigned long head = pool + off[k];
            unsigned long node = *(unsigned long *)head;
            int cnt = 0;
            while (node && node != head && cnt < 64) {
                unsigned long q;
                /* NODE ITSELF MUST BE READABLE BEFORE IT IS DEREFERENCED. This
                 * loop guarded `q` and not `node`, so the very first
                 * *(node + 8) faulted on a garbage list pointer - item 41's
                 * crash, at this instruction. The title gate above is the real
                 * fix; this is the belt to its braces, because a list can be
                 * torn mid-walk on the RIGHT title too, and a diagnostic that
                 * can kill the run it is diagnosing is worse than no
                 * diagnostic. */
                if (!aud_readable(node)) {
                    snprintf(b, sizeof b,
                             "[aud] pool list +%02x: stopping at unreadable node"
                             " 0x%lx after %d\n", off[k], node, cnt);
                    logmsg(b);
                    break;
                }
                q = *(unsigned long *)(node + 8);
                if (cnt < 4 && aud_readable(q)) {
                    unsigned long *qq = (unsigned long *)q;
                    snprintf(b, sizeof b,
                             "[aud]   list+%02x[%d] queue=0x%lx fd=%ld total=%lu "
                             "avail=%ld pops=%lu\n",
                             off[k], cnt, q, (long)qq[2], qq[4],
                             (long)qq[0x30 / 4], qq[0x44 / 4]);
                    logmsg(b);
                }
                node = *(unsigned long *)node;
                cnt++;
            }
            snprintf(b, sizeof b, "[aud] pool list +%02x : %d entries\n",
                     off[k], cnt);
            logmsg(b);
        }
    }
}

/* PAD_AUDIO_VOICES=1 - log every CHANGE to the 8 mixer voice slots.
 *
 * The periodic [aud] dump samples a few times a minute, which is fine for "is
 * anything playing" and useless for "what is retriggering at 20 Hz". This runs
 * off the SPI loop, which never stops and is paced at ~1.5 kHz, so a 20 Hz
 * event cannot hide between samples.
 *
 * It prints the voice's STREAM DESCRIPTOR pointer, which is the identity of the
 * sound. A sound being retriggered shows up as the same descriptor enabled over
 * and over; a stuck one never changes at all. That distinction is what the boot
 * buzz needs and what neither the screen, the switch tables nor the captured
 * PCM could give. */
static void voice_trace(void)
{
    static int on = -1;
    static unsigned long last_stream[8];
    static unsigned char last_en[8];
    static int budget = 400;
    static int primed;
    int n;
    if (on == -1) { char *q = getenv("PAD_AUDIO_VOICES"); on = (q && *q && *q != '0'); }
    if (!on || budget <= 0) return;
    if (!aud_readable(0x7b90c0UL)) return;
    for (n = 0; n < 8; n++) {
        unsigned char *v = (unsigned char *)(0x7b90c0UL + n * 64);
        unsigned long stream = *(unsigned long *)v;
        unsigned char en = v[0x35];
        if (!primed) { last_stream[n] = stream; last_en[n] = en; continue; }
        if (stream != last_stream[n] || en != last_en[n]) {
            char b[180];
            snprintf(b, sizeof b,
                     "[voice] %d: stream 0x%08lx->0x%08lx en %d->%d pos=%lu\n",
                     n, last_stream[n], stream, last_en[n], en,
                     *(unsigned long *)(v + 12));
            logmsg(b);
            last_stream[n] = stream;
            last_en[n] = en;
            budget--;
            if (budget <= 0) { logmsg("[voice] budget spent\n"); return; }
        }
    }
    primed = 1;
}

static void audio_maybe_dump(void)
{
    static int every = -1;
    static unsigned long next;
    if (every == -1) {
        char *p = getenv("PAD_AUDIO_DUMP");
        every = 0;
        while (p && *p >= '0' && *p <= '9') every = every * 10 + (*p++ - '0');
    }
    if (every <= 0) return;
    if (pad_ms() < next) return;
    next = pad_ms() + (unsigned long)every * 1000ul;
    audio_dump();
}

static unsigned tap_hold = 240;   /* bus writes held down, ~1.1 s at 212/s  */
static unsigned tap_gap  = 640;   /* bus writes per slot, ~3 s              */
static unsigned tap_at_s, tap_hold_s = 1500, tap_gap_s = 5000;   /* ms       */

static void sw_tap(void)
{
    static char *list = (char *)-1;
    static unsigned n, start;
    char *p;
    unsigned slot, k, i = 0;

    if (list == (char *)-1) {
        list = getenv("PAD_SW_TAP");
        start = 0;
        {   char *q = getenv("PAD_SW_TAP_AT");
            while (q && *q >= '0' && *q <= '9') start = start * 10 + (unsigned)(*q++ - '0');
            if (!start) start = 8000;   /* well past the 70 s validation settle */
        }
        {   char *q = getenv("PAD_SW_TAP_HOLD"); unsigned v = 0;
            while (q && *q >= '0' && *q <= '9') v = v * 10 + (unsigned)(*q++ - '0');
            if (v) tap_hold = v;
        }
        {   char *q = getenv("PAD_SW_TAP_GAP"); unsigned v = 0;
            while (q && *q >= '0' && *q <= '9') v = v * 10 + (unsigned)(*q++ - '0');
            if (v) tap_gap = v;
        }
        if (tap_gap <= tap_hold) tap_gap = tap_hold + 1;
        {   char *q = getenv("PAD_SW_TAP_AT_S"); unsigned v = 0;
            while (q && *q >= '0' && *q <= '9') v = v * 10 + (unsigned)(*q++ - '0');
            tap_at_s = v * 1000u;
        }
        {   char *q = getenv("PAD_SW_TAP_HOLD_MS"); unsigned v = 0;
            while (q && *q >= '0' && *q <= '9') v = v * 10 + (unsigned)(*q++ - '0');
            if (v) tap_hold_s = v;
        }
        {   char *q = getenv("PAD_SW_TAP_GAP_MS"); unsigned v = 0;
            while (q && *q >= '0' && *q <= '9') v = v * 10 + (unsigned)(*q++ - '0');
            if (v) tap_gap_s = v;
        }
        if (tap_gap_s <= tap_hold_s) tap_gap_s = tap_hold_s + 1;
    }

    /* PAD_SW_TAP_AT_S=<seconds> - the reliable form. Falls back to the
     * bus-write schedule when it is not set. */
    if (tap_at_s) {
        unsigned long now = pad_ms();
        static unsigned last_slot = (unsigned)-1;
        static int last_down = -1;
        unsigned s2, k2, want, j = 0;
        char *q;
        if (now < tap_at_s) return;
        s2 = (unsigned)((now - tap_at_s) / tap_gap_s);
        k2 = (unsigned)((now - tap_at_s) % tap_gap_s);
        want = k2 < tap_hold_s;
        if (s2 == last_slot && (int)want == last_down) return;
        last_slot = s2; last_down = (int)want;
        for (q = list; *q; j++) {
            unsigned id = 0;
            while (*q >= '0' && *q <= '9') id = id * 10 + (unsigned)(*q++ - '0');
            while (*q && (*q < '0' || *q > '9')) q++;
            if (j != s2 || !id || id >= sizeof sw_active) continue;
            sw_hold_init();
            sw_active[id] = (unsigned char)want;
            sw_gen++;
            {
                char line[140];
                snprintf(line, sizeof line, "[swtap] %s id=%u at %lu ms\n",
                         want ? "PRESS  " : "RELEASE", id, now);
                logmsg(line);
            }
            return;
        }
        return;
    }
    if (!list || !*list) return;
    if (++n < start) return;
    slot = (n - start) / tap_gap;
    k    = (n - start) % tap_gap;
    if (k != 0 && k != tap_hold) return;

    for (p = list; *p; i++) {
        unsigned id = 0;
        while (*p >= '0' && *p <= '9') id = id * 10 + (unsigned)(*p++ - '0');
        while (*p && (*p < '0' || *p > '9')) p++;
        if (i != slot || !id || id >= sizeof sw_active) continue;
        sw_hold_init();
        sw_active[id] = (unsigned char)(k ? 0 : 1);
        sw_gen++;
        {
            char line[140];
            snprintf(line, sizeof line,
                     "[swtap] %s id=%u (bus write %u)\n",
                     k ? "RELEASE" : "PRESS  ", id, n);
            logmsg(line);
        }
        return;
    }
}

/* PAD_SW_MAP=<n> - every n bus writes, print each switch's own (node, bit) and
 * cross-check it against NodeRec.map[]. This replaces the walking-bit sweep
 * entirely: the map is a live table, not something to infer from timing. */
static void sw_map_dump(void)
{
    char line[300];
    unsigned st = tread(SW_STRUCT);
    unsigned n  = tread(SW_COUNT);
    unsigned id;

    if (!sw_ok(st) || n > 4096) return;
    snprintf(line, sizeof line,
             "[swmap] --- switch coordinates (entry+20 node, entry+18 bit) ---\n");
    logmsg(line);
    for (id = 1; id < n; id++) {
        const unsigned char *e =
            (const unsigned char *)(unsigned long)(st + id * 32);
        unsigned bit  = *(const unsigned short *)(e + 18);
        unsigned node = e[20];
        unsigned cfg  = *(const unsigned *)(e + 8);
        unsigned nameobj = *(const unsigned *)(e + 12);
        const char *nm = 0;
        unsigned back = 0xffff, cur = 0, gate = 0;
        if (sw_ok(nameobj))
            nm = msg_row(*(const unsigned *)(unsigned long)(nameobj + 16));
        if (node < 32 && bit < 64) {
            const unsigned char *rec =
                (const unsigned char *)(unsigned long)SW_NODEREC(node);
            back = *(const unsigned short *)(rec + 28 + bit * 2);
            cur  = (rec[20 + (bit >> 3)] >> (bit & 7)) & 1;
            gate = *(const unsigned char *)(unsigned long)(NB_GATE + 276 + node);
        }
        snprintf(line, sizeof line,
                 "[swmap] id=%-3u node=%-2u bit=%-2u map=%-4u%s cur=%u gate=%u"
                 " idle=%d lvl=%u %s\n",
                 id, node, bit, back, back == id ? " ok " : " MISMATCH",
                 cur, gate, sw_inactive_level(cfg), e[24], nm ? nm : "?");
        logmsg(line);
    }
}

/* PAD_SW_CHANGES=1 - log EVERY change of entry[+24] across the whole table,
 * with a timestamp and the switch's name.
 *
 * This exists because the menu cursor was seen moving at moments nothing had
 * been injected, and reading the screen cannot say what input caused it. The
 * electrical level is the single point every source has to pass through - the
 * SPI cabinet word, the node bus 0x11 scan, and anything else - so watching it
 * for the whole table is the complete input trace. Sampled off the SPI loop
 * (which never stops) and rate-limited to ~20 ms, which is finer than the
 * game's own debounce.
 */
static void sw_changes(void)
{
    static int on = -1;
    static unsigned char prev[256];
    static int primed;
    static unsigned long last;
    unsigned long now;
    unsigned st, cnt, id;

    if (on == -1) { char *q = getenv("PAD_SW_CHANGES"); on = (q && *q != '0'); }
    if (!on) return;
    now = pad_ms();
    if (primed && now - last < 20) return;
    last = now;
    st  = tread(SW_STRUCT);
    cnt = tread(SW_COUNT);
    if (!sw_ok(st) || cnt > 256) return;
    for (id = 1; id < cnt; id++) {
        const unsigned char *e =
            (const unsigned char *)(unsigned long)(st + id * 32);
        unsigned lvl = e[24];
        if (primed && lvl != prev[id]) {
            static int budget = 400;
            if (budget > 0) {
                unsigned nameobj = *(const unsigned *)(e + 12);
                const char *nm = sw_ok(nameobj)
                    ? msg_row(*(const unsigned *)(unsigned long)(nameobj + 16)) : 0;
                char line[220];
                budget--;
                snprintf(line, sizeof line,
                         "[swchg] %lu ms id=%-3u node=%-2u bit=%-2u %u->%u"
                         " cnt=%u e26=%u idle=%d  %s\n",
                         now, id, e[20], *(const unsigned short *)(e + 18),
                         prev[id], lvl,
                         *(const unsigned short *)(e + 22), e[26],
                         sw_inactive_level(*(const unsigned *)(e + 8)),
                         nm ? nm : "?");
                logmsg(line);
            }
        }
        prev[id] = (unsigned char)lvl;
    }
    primed = 1;
}

/* PAD_SW_PEND=<ids> - the PENDING-COUNTER trace, and the instrument the latch
 * investigation actually needs.
 *
 * [swchg] prints entry[+22] only when the LEVEL moves, which is precisely the
 * moment the counter's history has already been spent. The latch is a parity
 * rule - 0x1e7540 stores the level INVERTED when (entry[+22] & 1) == 0 - so
 * what has to be watched is the counter itself, every value it takes, next to
 * the four other things in the chain:
 *
 *   sent  the bit the shim put on the wire for this id
 *   prev  NodeRec.prev[bit], last scan's copy
 *   cur   NodeRec.cur[bit],  what 0x1e78f4 recorded from this scan
 *   pend  entry[+22], the pending-change counter
 *   lvl   entry[+24], what 0x1e7540 finally wrote
 *
 * Sampled off the SPI loop (which never stops) at 1 ms, finer than both the
 * ~60 Hz drain and the ~38 Hz per-node scan, and printed only when one of the
 * fields moves. A run of `pend=2` immediately before a wrong `lvl` proves the
 * parity story; `pend=0` with a wrong `lvl` disproves it and points at cur[].
 */
static void sw_pend_trace(void)
{
    static char *list = (char *)-1;
    static int budget = 6000;
    static unsigned long last;
    static unsigned char pv[256], lv[256], cv[256], rv[256], sv[256], ev[256];
    static unsigned char primed[256];
    unsigned long now;
    unsigned st, raw, cnt;
    char *p;

    if (list == (char *)-1) list = getenv("PAD_SW_PEND");
    if (!list || !*list || budget <= 0) return;
    now = pad_ms();
    if (now == last) return;
    last = now;
    st  = tread(SW_STRUCT);
    raw = tread_at(SW_STRUCT, 4);
    cnt = tread(SW_COUNT);
    if (!sw_ok(st) || !sw_ok(raw) || cnt > 4096) return;

    for (p = list; *p; ) {
        unsigned id = 0;
        const unsigned char *e;
        unsigned pend, lvl, e26, rw, node, bit, cur = 0, prv = 0;
        while (*p >= '0' && *p <= '9') id = id * 10 + (unsigned)(*p++ - '0');
        while (*p && (*p < '0' || *p > '9')) p++;
        if (!id || id >= cnt || id >= 256) continue;
        e    = (const unsigned char *)(unsigned long)(st + id * 32);
        bit  = *(const unsigned short *)(e + 18);
        node = e[20];
        pend = *(const unsigned short *)(e + 22);
        lvl  = e[24];
        e26  = e[26];
        rw   = ((const unsigned char *)(unsigned long)raw)[id];
        if (node < 32 && bit < 64) {
            const unsigned char *rec =
                (const unsigned char *)(unsigned long)SW_NODEREC(node);
            cur = (rec[20 + (bit >> 3)] >> (bit & 7)) & 1;
            prv = (rec[12 + (bit >> 3)] >> (bit & 7)) & 1;
        }
        if (primed[id] && pv[id] == (unsigned char)pend &&
            lv[id] == (unsigned char)lvl && cv[id] == (unsigned char)cur &&
            rv[id] == (unsigned char)rw && sv[id] == sw_sent[id] &&
            ev[id] == (unsigned char)prv)
            continue;
        primed[id] = 1;
        pv[id] = (unsigned char)pend; lv[id] = (unsigned char)lvl;
        cv[id] = (unsigned char)cur;  rv[id] = (unsigned char)rw;
        sv[id] = sw_sent[id];         ev[id] = (unsigned char)prv;
        if (budget > 0) {
            char line[240];
            budget--;
            snprintf(line, sizeof line,
                     "[swpend] %lu ms id=%-3u node=%-2u bit=%-2u sent=%u"
                     " prev=%u cur=%u pend=%u lvl=%u raw=%u e26=%u\n",
                     now, id, node, bit, sw_sent[id], prv, cur,
                     pend, lvl, rw, e26);
            logmsg(line);
        }
    }
}

static void sw_maybe_dump(void)
{
    static int every = -1, mevery = -1, n, mn;
    if (every == -1) {
        char *p = getenv("PAD_SW_DUMP");
        int v = 0;
        while (p && *p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        every = v;
    }
    if (mevery == -1) {
        char *p = getenv("PAD_SW_MAP");
        int v = 0;
        while (p && *p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        mevery = v;
    }
    sw_force();
    sw_press();
    sw_tap();
    sw_watch();
    swwalk_tick();
    if (mevery > 0 && ++mn % mevery == 0) sw_map_dump();
    if (every <= 0) return;
    if (++n % every) return;
    sw_dump();
}

static void val_dump(void)
{
    char line[420];
    const unsigned char *m;
    unsigned v, ctx;
    int i, k;

    /* 0 means this title's module base is unknown or not mapped. Every other
     * TITLE_ADDR reader bails the same way rather than dereferencing it. */
    if (!VAL_MOD || !VAL_AUD) return;
    m   = (const unsigned char *)(unsigned long)VAL_MOD;
    v   = *(const unsigned *)(unsigned long)VAL_V;
    ctx = *(const unsigned *)(unsigned long)VAL_CTX;

    snprintf(line, sizeof line,
             "[val] state=%u V=0x%08x ctx=0x%08x tick=%u ge_s=%u ce_s=%u zk_s=%u"
             " audio[0x7b9304]=%u [0x7b9308]=%u\n",
             m[0xc5], v, ctx, *(const unsigned *)(m + 0xe0),
             *(const unsigned *)(m + 0xcc), *(const unsigned *)(m + 0xd0),
             *(const unsigned *)(m + 0xd4),
             *(const unsigned *)(unsigned long)(VAL_AUD - 4),
             *(const unsigned *)(unsigned long)VAL_AUD);
    logmsg(line);

    if (v >= 0x8000u && v < 0x10000000u) {
        const unsigned char *o = (const unsigned char *)(unsigned long)v;
        k = snprintf(line, sizeof line,
                     "[val] GE(+42)=%-10s CE(+43)=%-10s ZK(+44)=%-10s f41=%u "
                     "n8=%u n12=%u n16=%u n20=%u n24=%u  raw:",
                     val_state(o[42]), val_state(o[43]), val_state(o[44]), o[41],
                     *(const unsigned *)(o + 8), *(const unsigned *)(o + 12),
                     *(const unsigned *)(o + 16), *(const unsigned *)(o + 20),
                     *(const unsigned *)(o + 24));
        for (i = 0; i < 48 && k < (int)sizeof line - 4; i++)
            k += snprintf(line + k, sizeof line - k, "%s%02x",
                          (i % 4) ? "" : " ", o[i]);
        snprintf(line + k, sizeof line - k, "\n");
        logmsg(line);
    }

    /* The worker context carries the path it is currently reading (a 4 KB
     * buffer strncpy'd just before every fopen) and the error code the failing
     * paths store at +0x51c4 - which is the difference between "the file is
     * wrong" and "the file would not open". */
    if (ctx >= 0x8000u && ctx < 0xf0000000u) {
        /* TWO path buffers, and they are not interchangeable. The asset sweep
         * (states 5/6) builds its path at ctx+0x4010, but the boot-partition
         * stage decrypts "/mnt/boot/zImage" to ctx+0 and fopens THAT, so
         * printing only +0x4010 shows an empty string for the one stage whose
         * open is failing. */
        const char *path = (const char *)(unsigned long)(ctx + 0x4010);
        const char *zp   = (const char *)(unsigned long)ctx;
        const unsigned *w = (const unsigned *)(unsigned long)(ctx + 0x5000);
        char safe[200], zsafe[120];
        for (i = 0; i < (int)sizeof safe - 1 && path[i]; i++)
            safe[i] = (path[i] >= 32 && path[i] < 127) ? path[i] : '.';
        safe[i] = 0;
        for (i = 0; i < (int)sizeof zsafe - 1 && zp[i]; i++)
            zsafe[i] = (zp[i] >= 32 && zp[i] < 127) ? zp[i] : '.';
        zsafe[i] = 0;
        snprintf(line, sizeof line,
                 "[val] file=0x%08x pos=%u size=%u left=%u crc=0x%08x sub=%u\n"
                 "[val] path=\"%s\" ctx0=\"%s\"\n",
                 w[0x1a8 / 4], w[0x1ac / 4], w[0x1b0 / 4], w[0x1b4 / 4],
                 w[0x1c0 / 4], w[0x1c4 / 4], safe, zsafe);
        logmsg(line);
    }
}

static int val_on(void)
{
    static int on = -1;
    if (on == -1) { char *p = getenv("PAD_VAL_DUMP"); on = (p && *p && *p != '0'); }
    return on;
}

/* Print only when something moved. The state machine settles inside the first
 * couple of seconds and then repeats the same failed record for the rest of the
 * run, so an unconditional periodic dump is thousands of identical lines and
 * still misses every transition. */
static void val_dump_changed(void)
{
    static unsigned char last[52];
    static int primed;
    unsigned char cur[52];
    const unsigned char *m;
    unsigned ctx;
    int i;

    if (!VAL_MOD) return;
    m   = (const unsigned char *)(unsigned long)VAL_MOD;
    ctx = *(const unsigned *)(unsigned long)VAL_CTX;
    for (i = 0; i < 48; i++) cur[i] = m[i];
    cur[48] = m[0xc5];
    cur[49] = (unsigned char)(ctx >> 24);
    cur[50] = cur[51] = 0;
    if (ctx >= 0x8000u && ctx < 0xf0000000u) {
        unsigned e = *(const unsigned *)(unsigned long)(ctx + 0x51c4);
        cur[50] = (unsigned char)e;
        cur[51] = (unsigned char)(e >> 8);
    }
    for (i = 0; i < 52; i++) if (cur[i] != last[i]) break;
    if (primed && i == 52) return;
    for (i = 0; i < 52; i++) last[i] = cur[i];
    primed = 1;
    val_dump();
}

/* The caller filter: only stdio coming from inside the validation module is
 * interesting, and everything else during boot is scene loading. Both bounds
 * are TITLE addresses - on turtles the same module sits at +0x970f8, so a
 * godzilla-shaped filter rejects every one of its calls and the probe reads a
 * confident silence over a module that is working perfectly. */
TITLE_ADDR(a_val_lo, "PAD_VAL_TEXT_LO", 0x249e00u)
TITLE_ADDR(a_val_hi, "PAD_VAL_TEXT_HI", 0x24c2c0u)

#define VAL_LO a_val_lo()
#define VAL_HI a_val_hi()

static void val_probe(const char *what, unsigned long ra,
                      unsigned long a, unsigned long b, unsigned long c)
{
    char line[220];
    if (!val_on()) return;
    if (ra < VAL_LO || ra >= VAL_HI) return;
    /* The hash pass is one 16 KB fread per chunk and a whole-file pass is ~480
     * of them, so log every 32nd - enough to see the rate and the end, without
     * burying the transitions that matter. */
    if (a == 16384) {
        static unsigned bulk;
        if (bulk++ % 32) { val_dump_changed(); return; }
        snprintf(line, sizeof line,
                 "[val] %s from 0x%lx  chunk #%u -> %lu\n", what, ra, bulk, c);
    } else {
        snprintf(line, sizeof line,
                 "[val] %s from 0x%lx  a=%lu b=%lu -> %lu\n", what, ra, a, b, c);
    }
    logmsg(line);
    val_dump_changed();
}

/* Sampled from the fopen hooks as well, because everything above only fires
 * once the validation module itself is doing stdio - and the states this is
 * chasing are already set by then. Scene loading opens thousands of files
 * during boot, so this covers the whole start-up window. */
static void val_sample(void)
{
    if (val_on()) val_dump_changed();
}

static void val_maybe_dump(void)
{
    if (!val_on()) return;
    val_dump_changed();
}

/* ══ THE SCREEN ORACLE ═══════════════════════════════════════════════════
 *
 * PAD_SCREEN=1: log every distinct line of text the game draws, as it draws
 * it.
 *
 * WHY THIS EXISTS, and it is the most expensive lesson of item 52: this rig
 * has never been able to see its own screen. The LOCATING NODE BOARDS wedge
 * burned six passes partly because "what is displayed" could only be answered
 * by asking David to look, and the country-code dip sweep stopped dead on it -
 * that message is a TEXT OVERLAY drawn over video, so the LCD scene hash
 * cannot tell one screen from another and a blind A/B proves nothing at all.
 * A run that cannot report its own screen makes every screen question a
 * guess.
 *
 * THE FIRST CUT OF THIS PROBE WAS WRONG, AND WHY IS WORTH KEEPING. It read a
 * "character page" at 0x7c0114 + idx<<12, on the theory that the renderer
 * composes text into a 4 KB buffer that could simply be read out. It found a
 * page of zeros. Reading 0x3afd64 - the draw-one-message call - explained it:
 *
 *     0x3afd64(id, ctx, ...):   r0 = message id
 *         bl 0x233330           id -> const char *          (r0 = the string)
 *         r1 = 0x7c0114 + ctx<<12
 *         b  0x3afbc8
 *
 *     0x3afbc8(const char *s, target, font, flags, x, y, colour):
 *         walks s one BYTE at a time and blits each character as a SPRITE
 *         (bl 0x440d70 / 0x440ccc).
 *
 * There is no character buffer anywhere. 0x7c0114 + idx<<12 is a RENDER
 * TARGET handle that 0x3afbc8 passes straight through to the blitter, and the
 * old probe was reading a render target as if it were text.
 *
 * So the text is text at exactly ONE moment: on entry to 0x3afbc8, in r0.
 * That is the hook point, and it is the right one because the whole wrapper
 * family funnels into it - 0x3afd64 (draw by message id), 0x3afdec /
 * 0x3afe58 / 0x3afed4 / 0x3aff3c (vsprintf first, so counts and node numbers
 * are already substituted into the string) and 0x3afebc (draw a raw string).
 * The country refusal screen at 0x3c9658 uses 0x3afd64; the LOCATING NODE
 * BOARDS renderer at 0x3db054 uses 0x3afebc and 0x3afdec and would have been
 * missed by hooking 0x3afd64 alone. Hooking the bottleneck catches every
 * screen in the game and needs no message-table decode at all.
 *
 * HOW - an inline hook. The first two instructions of 0x3afbc8 are
 *     e92d4ff0  push {r4,r5,r6,r7,r8,r9,sl,fp,lr}
 *     e24dd01c  sub  sp, sp, #28
 * Neither is PC-relative, so both can be relocated. We overwrite them with
 * `ldr pc,[pc,#-4]; .word tramp`; the trampoline logs r0, re-executes those
 * two, and jumps to 0x3afbd0. The stack is left EXACTLY as the original
 * prologue would have left it, which matters here because the function reads
 * its remaining arguments at [sp,#64], [sp,#68] and [sp,#72] - offsets that
 * only work if 36 bytes of push and 28 of sub happened and nothing else.
 *
 * THE TRAMPOLINE IS GENERATED AS DATA rather than written in asm: a
 * `.word symbol` literal inside a -fPIC shared object is a text relocation,
 * and emitting six known instruction words costs less than arguing with the
 * linker about one. `blx` reaches the logger whichever instruction set it was
 * compiled to, so this does not care whether the shim is ARM or Thumb.
 *
 * THE ADDRESS IS STRANGER_THINGS' and is env-overridable, but the real guard
 * is not the title name - it is that the hook REFUSES to patch unless the two
 * instructions it is about to replace are the two it expects. Patching a byte
 * pattern rather than a byte address is what keeps this from corrupting some
 * other title's unrelated function. */
TITLE_ADDR(a_draw_text, "PAD_SCREEN_FN", 0x3afbc8u)

#define SCREEN_INSN0 0xe92d4ff0u    /* push {r4,r5,r6,r7,r8,r9,sl,fp,lr} */
#define SCREEN_INSN1 0xe24dd01cu    /* sub  sp, sp, #28                  */

#define PAD_PROT_READ  1
#define PAD_PROT_WRITE 2
#define PAD_PROT_EXEC  4
int mprotect(void *addr, unsigned long len, int prot);

/* One page of our own BSS, made executable, holding the generated trampolines.
 * A static buffer rather than mmap() because this file interposes mmap. */
static unsigned pad_hook_page[1024] __attribute__((aligned(4096)));
static int pad_hook_used;      /* trampolines handed out, 16 words each */

/* INSTALL AN INLINE HOOK at `fn`, calling `logger` on every entry.
 *
 * Refuses unless the two instructions it is about to replace are `want0` and
 * `want1` - a byte PATTERN match, not a byte address. That is the whole safety
 * story: the addresses here are stranger_things', and patching some other
 * title's unrelated function at the same offset would corrupt it silently.
 * BOTH RELOCATED INSTRUCTIONS MUST BE PC-INDEPENDENT; every caller below has
 * checked that by reading them.
 *
 * pass_lr=1 passes the CALLER's address to the logger instead of r0, which is
 * how "who dispatches this screen?" gets answered without a debugger.
 *
 * The layout is fixed so one builder serves every hook. `ldr rX,[pc,#n]` reads
 * from the instruction's own address + 8 + n, hence #20 at t[2] and #4 at t[7]. */
static int pad_hook(unsigned fn, unsigned want0, unsigned want1,
                    void *logger, int pass_lr, const char *tag)
{
    volatile unsigned *p;
    unsigned *t, page;
    char m[240];

    if (!fn || !addr_readable((const void *)(unsigned long)fn)) {
        snprintf(m, sizeof m, "[%s] not hooking: 0x%08x unreadable "
                 "(0 means addr_readable said no)\n", tag, fn);
        logmsg(m);
        return 0;
    }
    p = (volatile unsigned *)(unsigned long)fn;
    if (p[0] != want0 || p[1] != want1) {
        snprintf(m, sizeof m, "[%s] not hooking 0x%08x: expected %08x %08x, "
                 "found %08x %08x - wrong title, the function moved, or it is "
                 "already hooked\n", tag, fn, want0, want1, p[0], p[1]);
        logmsg(m);
        return 0;
    }
    if ((pad_hook_used + 1) * 16 > 1024) {
        snprintf(m, sizeof m, "[%s] not hooking: trampoline page full\n", tag);
        logmsg(m);
        return 0;
    }
    t = pad_hook_page + pad_hook_used * 16;
    pad_hook_used++;

    t[0] = 0xe92d500fu;   /* push {r0,r1,r2,r3,ip,lr}  - 24 bytes, stays 8-aligned */
    t[1] = pass_lr ? 0xe1a0000eu   /* mov r0, lr - lr is still the CALLER's here */
                   : 0xe1a00000u;  /* nop        - r0 is already the argument    */
    /* ...and the ENTRY sp as the second argument, which is how a logger walks
     * past a generic thunk. The refusal screen's immediate caller turned out to
     * be `push {r3,lr}; blx r1; pop {r3,pc}` - an invoke-through-a-pointer used
     * by every screen - so `lr` alone names the adapter, never the dispatcher.
     * With the entry sp the logger can read the frame the thunk pushed. */
    t[2] = pass_lr ? 0xe28d1018u   /* add r1, sp, #24 - undo our own push */
                   : 0xe1a00000u;  /* nop */
    t[3] = 0xe59fc014u;   /* ldr ip, [pc, #20]   -> t[10], the logger */
    t[4] = 0xe12fff3cu;   /* blx ip - interworks, so ARM or Thumb both fine */
    t[5] = 0xe8bd500fu;   /* pop  {r0,r1,r2,r3,ip,lr} - args and lr restored */
    t[6] = p[0];          /* the relocated prologue, read rather than assumed */
    t[7] = p[1];
    t[8] = 0xe59ff004u;   /* ldr pc, [pc, #4]    -> t[11], fn + 8 */
    t[9] = 0u;            /* never executed */
    t[10] = (unsigned)(unsigned long)logger;
    t[11] = fn + 8u;

    if (mprotect(pad_hook_page, sizeof pad_hook_page,
                 PAD_PROT_READ | PAD_PROT_WRITE | PAD_PROT_EXEC) != 0) {
        snprintf(m, sizeof m, "[%s] not hooking: mprotect of the trampoline "
                 "page failed\n", tag);
        logmsg(m);
        return 0;
    }
    page = fn & ~0xfffu;   /* two pages: the 8 bytes may straddle a boundary */
    if (mprotect((void *)(unsigned long)page, 0x2000,
                 PAD_PROT_READ | PAD_PROT_WRITE | PAD_PROT_EXEC) != 0) {
        snprintf(m, sizeof m, "[%s] not hooking: mprotect of 0x%08x failed\n",
                 tag, page);
        logmsg(m);
        return 0;
    }
    p[1] = (unsigned)(unsigned long)t;   /* the literal BEFORE the branch */
    p[0] = 0xe51ff004u;                  /* ldr pc, [pc, #-4] */
    __builtin___clear_cache((char *)t, (char *)(t + 16));
    __builtin___clear_cache((char *)(unsigned long)fn, (char *)(unsigned long)fn + 8);

    snprintf(m, sizeof m, "[%s] hooked 0x%08x -> trampoline %p, resuming at "
             "0x%08x\n", tag, fn, (void *)t, fn + 8u);
    logmsg(m);
    return 1;
}

/* Called from the trampoline with r0 = the string about to be drawn.
 *
 * DEDUPED, because a screen redraws its text every frame and an undeduped
 * hook here is the ~450-writes-a-second log flood this file warns about at
 * the top. A 64-entry ring is enough that a static screen prints its lines
 * once, while a screen CHANGE still shows up immediately as new lines. */
__attribute__((noinline, used))
static void screen_note(const char *s)
{
    static char seen[64][80];
    static int nseen, head, total, capped, busy;
    char m[200];
    int i, j, n;

    if (busy) return;                  /* never re-enter through logmsg */
    busy = 1;
    if (!s || !addr_readable(s)) { busy = 0; return; }
    for (n = 0; n < 79 && s[n] >= 32 && s[n] < 127; n++) ;
    if (n < 1) { busy = 0; return; }   /* empty or non-printable: not text */

    for (i = 0; i < nseen; i++) {
        for (j = 0; j < n && seen[i][j] == s[j]; j++) ;
        if (j == n && seen[i][n] == 0) { busy = 0; return; }   /* already said */
    }
    for (j = 0; j < n; j++) seen[head][j] = s[j];
    seen[head][n] = 0;
    head = (head + 1) & 63;
    if (nseen < 64) nseen++;

    if (++total > 500) {
        if (!capped) {
            capped = 1;
            logmsg("[screen] 500 distinct lines logged; suppressing the rest\n");
        }
        busy = 0;
        return;
    }
    snprintf(m, sizeof m, "[screen] %lu ms: %s\n", pad_ms(), seen[(head - 1) & 63]);
    logmsg(m);
    busy = 0;
}

static void screen_install(void)
{
    static int done;
    if (done) return;
    done = 1;
    if (!getenv("PAD_SCREEN")) return;
    if (pad_hook(a_draw_text(), SCREEN_INSN0, SCREEN_INSN1,
                 (void *)&screen_note, 0, "screen"))
        logmsg("[screen] every line of text this game draws will be logged once\n");
}

/* ── PAD_NO_COUNTRY_GATE=1 ────────────────────────────────────────────────
 *
 * A DIAGNOSTIC, NOT A FIX, and off unless asked for. 0x3c9658 is
 * stranger_things' country-refusal screen: it draws message ids 767..770
 * ("THIS MACHINE WILL NOT" / "OPERATE IN THIS COUNTRY" / "PLEASE" / "CONTACT
 * YOUR DISTRIBUTOR" - exactly the screen David photographed) and then spins
 * forever at 0x3c9704. It never returns, so reaching it is terminal.
 *
 * Making it `bx lr` answers one question a dip sweep cannot: is the country
 * gate the LAST thing standing between this rig and an attract mode, or only
 * the first of several? It does not make the country right, and a run with
 * this set is not evidence that anything is fixed. */
TITLE_ADDR(a_country_screen, "PAD_COUNTRY_FN", 0x3c9658u)
#define COUNTRY_INSN0 0xe92d4070u   /* push {r4, r5, r6, lr}  */
#define COUNTRY_INSN1 0xe30e4194u   /* movw r4, #0xe194       */

/* PAD_COUNTRY_TRACE=1: log WHO dispatches the refusal screen.
 *
 * This is the one question blocking item 52 and static reading could not
 * answer it. 0x3c9658 is entry 7 of the 375-entry {handler, attr} screen table
 * at 0x730ef4 (entry 14 is 0x3db054, the LOCATING renderer, which is what
 * confirms the table), but the table is referenced by NO movw/movt pair and NO
 * literal pool, so the dispatcher is not findable by grep. It IS findable by
 * asking the running game: hook the screen and report the caller. The country
 * test is one step upstream of whatever that turns out to be. */
__attribute__((noinline, used))
static void country_note(unsigned caller, const unsigned *entry_sp)
{
    static int said;
    char m[300];
    unsigned k = 0, i;
    if (said) return;              /* the dispatcher calls this every frame */
    said = 1;
    k = (unsigned)snprintf(m, sizeof m, "[country] refusal screen entered at "
            "%lu ms, lr=0x%08x", pad_ms(), caller);
    /* The immediate caller is the generic `blx r1` thunk, so print the words
     * it pushed too: [sp+4] is ITS return address, i.e. the dispatcher. The
     * rest is printed raw rather than guessed at - a wrong frame walk that
     * looks confident is worse than eight honest words. */
    if (entry_sp && addr_readable(entry_sp)) {
        k += (unsigned)snprintf(m + k, sizeof m - k, " sp=[");
        for (i = 0; i < 8 && k < sizeof m - 16; i++)
            k += (unsigned)snprintf(m + k, sizeof m - k, "%s%08x",
                                    i ? " " : "", entry_sp[i]);
        snprintf(m + k, sizeof m - k, "]\n");
    } else {
        snprintf(m + k, sizeof m - k, " (entry sp unreadable)\n");
    }
    logmsg(m);
}

static void country_trace(void)
{
    static int done;
    if (done) return;
    done = 1;
    if (!getenv("PAD_COUNTRY_TRACE")) return;
    pad_hook(a_country_screen(), COUNTRY_INSN0, COUNTRY_INSN1,
             (void *)&country_note, 1, "country");
}

/* ★ ITEM 52 INSTRUMENT: PAD_PASS_HOOK=<hexaddr> - log every ENTRY to one
 * function, with its caller and a timestamp. Generic on purpose: the pattern
 * guard is read from the function itself at arm time (both words must be
 * PC-independent - the caller of this knob has checked). First 200 calls
 * verbatim, then every 256th, so a 60 Hz caller stays legible. Written to
 * answer "how often does the stranger_things bus service pass (0x2064b0)
 * run, and from which branch of its loop" - a question three peeks and a
 * page of disassembly could not settle. */
__attribute__((noinline, used))
static void pass_note(unsigned caller, const unsigned *entry_sp)
{
    static unsigned n, busy;
    static unsigned long last_ms;
    char m[160];
    unsigned long now;
    (void)entry_sp;
    if (busy) return;
    busy = 1;
    n++;
    now = pad_ms();
    if (n <= 200 || (n & 255u) == 0) {
        snprintf(m, sizeof m, "[passhook] #%u %lu ms (+%lu) lr=0x%08x\n",
                 n, now, last_ms ? now - last_ms : 0ul, caller);
        logmsg(m);
    }
    last_ms = now;
    busy = 0;
}

static void pass_hook_arm(void)
{
    static int done;
    unsigned fn = 0;
    const char *e;
    volatile unsigned *p;
    if (done) return;
    done = 1;
    e = getenv("PAD_PASS_HOOK");
    if (!e || !*e) return;
    while (ishex(*e)) fn = fn * 16 + hexval(*e++);
    if (!fn || !addr_readable((const void *)(unsigned long)fn)) return;
    p = (volatile unsigned *)(unsigned long)fn;
    pad_hook(fn, p[0], p[1], (void *)&pass_note, 1, "passhook");
}

static void country_gate_bypass(void)
{
    static int done;
    volatile unsigned *p;
    unsigned fn, page;
    char m[220];

    if (done) return;
    done = 1;
    if (!getenv("PAD_NO_COUNTRY_GATE")) return;

    fn = a_country_screen();
    if (!fn || !addr_readable((const void *)(unsigned long)fn)) {
        snprintf(m, sizeof m, "[country] not patching: 0x%08x unreadable\n", fn);
        logmsg(m);
        return;
    }
    p = (volatile unsigned *)(unsigned long)fn;
    if (p[0] != COUNTRY_INSN0) {
        snprintf(m, sizeof m, "[country] not patching 0x%08x: expected %08x, "
                 "found %08x - wrong title or wrong address\n",
                 fn, COUNTRY_INSN0, p[0]);
        logmsg(m);
        return;
    }
    page = fn & ~0xfffu;
    if (mprotect((void *)(unsigned long)page, 0x2000,
                 PAD_PROT_READ | PAD_PROT_WRITE | PAD_PROT_EXEC) != 0) {
        logmsg("[country] not patching: mprotect failed\n");
        return;
    }
    p[0] = 0xe12fff1eu;   /* bx lr */
    __builtin___clear_cache((char *)(unsigned long)fn, (char *)(unsigned long)fn + 4);
    snprintf(m, sizeof m, "[country] 0x%08x patched to return immediately. This "
             "HIDES the refusal screen, it does not set a country.\n", fn);
    logmsg(m);
}

static void nb_maybe_dump(void)
{
    static int every = -1, n;
    if (every == -1) {
        char *p = getenv("PAD_NB_DUMP");
        int v = 0;
        while (p && *p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
        every = v;
    }
    if (every <= 0) return;
    if (++n % every) return;
    /* nb_dump_objs() finds its own array per title and is safe anywhere. The
     * other two are built on Godzilla Pro 1.15.0 literals and crashed
     * stranger_things when they were let loose on it - see
     * nb_addrs_are_this_title(). Say so rather than skipping in silence. */
    nb_dump_objs();
    nb_sweep_watch();       /* item 52: the 0x98-aware board watch, per tick */
    if (nb_addrs_are_this_title()) {
        nb_dump_boards();
        nb_dump_hexlist();
    } else {
        static int said;
        if (!said) {
            said = 1;
            logmsg("[nbtbl] skipped: the registry and hex-list dumps are "
                   "Godzilla Pro 1.15.0 addresses and this is not that title "
                   "(walking them here segfaulted stranger_things)\n");
        }
    }
    nb_dump_census();
}

/* ---- LIVE LED STATE (padled.h) -----------------------------------------
 *
 * The C twin of leddecode.py, and it must stay a twin: same three shapes, same
 * node restriction, same validity test. If one changes, change both.
 *
 *   body = [N idx][0x0f][N val]          len = 2N+1   (cmd 97 is the N=1 case)
 *   body = [N idx][B][N val][C]          len = 2N+2
 *   body = [N idx][B][0x0f][N val][C]    len = 2N+3
 *
 * ONLY NODES 1, 8 AND 9. The same command byte means something completely
 * different on the strip boards - cmd a6 on node 14 is a masked RGB-triple
 * frame, not this - and running it through here would produce confident
 * nonsense at plausible-looking indices. That restriction is the whole reason
 * this is safe to run against every frame.
 *
 * An index is only accepted if the board has enumerated it at boot (the 6-byte
 * 0x84/0x85 walk), which is what makes "is this really an index?" checkable
 * rather than assumed. */
struct padled_shm {
    unsigned magic, version, gen, decoded, skipped;
    unsigned char val[16][96];
    unsigned char coil[16][16];       /* wrapping fire counter, see coil_publish */
    unsigned char lvl[16][16];        /* last drive byte                         */
    unsigned coil_gen, coil_decoded;
    /* Version 3, the fade layer - the twin of padled.h, which carries the
     * meaning; keep the two in step. */
    unsigned fade_head;
    struct { unsigned ms;
             unsigned char node, start, end, from, to, rise, fall, pad;
    } fade[96];
};
#define PADLED_MAGIC 0x44454c50u

static struct padled_shm *led_shm;
static unsigned char led_known[16][96];      /* seen in the boot enumeration */
/* The same enumeration IN ORDER, which is what a bitmap frame indexes into:
 * led_order[node][k] is the LED index the board announced k-th. */
static unsigned char led_order[16][96];
static unsigned char led_count[16];

static int led_insert_node(unsigned node) { return node == 1 || node == 8 || node == 9; }

/* DECLARED, because GCC 14 STOPPED GUESSING. `open` and `close` were called
 * here with no declaration in sight, which every compiler up to GCC 13 assumed
 * meant `int open()` and warned about. GCC 14 made that an ERROR by default,
 * and a user on a newer distro got a shim that would not build - reported as
 * eight lines of harmless -Wformat-truncation notes, because those were the
 * tail and the three errors were not (see _pad_build in ensurebuild.sh).
 *
 * They are the SHIM'S OWN open/close, and that is not a mistake: this library
 * is LD_PRELOADed, so `open` from inside it binds to shim_open() above, which
 * hands straight to real_open. Declaring what was already being called keeps
 * that exactly as it was - the alternative, real_open/real_close, would be a
 * behaviour change on the LED path for no reason, and real_close is a
 * different pointer here than it is inside shim_close. */
extern int open(const char *, int, int);
extern int close(int);

static void led_map(void)
{
    static int tried;
    const char *path;
    int fd;
    void *m;
    if (led_shm || tried) return;
    tried = 1;
    path = getenv("PAD_LED_SHM");
    if (!path || !*path) return;
    fd = open(path, 2 /*O_RDWR*/, 0);
    if (fd < 0) return;
    m = mmap(0, 4096, 3, 1, fd, 0);
    close(fd);
    if (!m || m == (void *)-1) return;
    led_shm = (struct padled_shm *)m;
    led_shm->magic = PADLED_MAGIC;
    led_shm->version = 3;             /* 3 adds the fade ring; see padled.h  */
}

/* ---- COILS (padled.h, and the C twin of coildecode.py) ------------------
 *
 *     88 0b 40 <IDX> <PWR> 00 00 <B7> 00 00 00 00 <cksum> 00
 *
 * `cmd 0x40` on the coil boards addresses ONE COIL BY INDEX, and the index is
 * the device table's own: node 8 carries 0..8 and node 9 carries 6, which is
 * exactly the ten playfield coils the table lists under groups 6 and 7. Byte 4
 * is drive strength - the AUTO PLUNGER goes out at 0x96 where everything else
 * is 0xff, and the service menu's own "Trough Eject Power 225 (88%)" is the
 * same scale.
 *
 * HOW IT WAS PINNED DOWN, because the reasoning matters more than the layout.
 * Coils cannot be watched casually: 48V is interlocked to the coin door, and
 * the door has to be CLOSED for anything to fire (the game says so on screen,
 * "48V DISABLED / CLOSE COIN DOOR"). So: door closed, trough switches opened to
 * say the balls are gone, Start pressed. The game put up LOCATING PINBALLS and
 * ran a ball search on an 8.3 s cycle - and the frames that appeared carried
 * indices 2, 3, 4, 7 and 8, which are RIGHT SLINGSHOT, LEFT SLINGSHOT, AUTO
 * PLUNGER, POP BUMPER and RIGHT SCOOP. Those are precisely the coils a ball
 * search fires, and precisely NOT the three flippers or the trough eject. The
 * game labelled its own experiment.
 *
 * WHAT IS NOT DECODED: byte 7, which is 0xff for the slingshots and the pop
 * bumper and 0x00 for the auto plunger and the scoop. On/off, hold power and
 * "the board may self-fire this one from its own switch" all fit what has been
 * seen and nothing distinguishes them yet. So this counts a coil being
 * ADDRESSED, and the window says "addressed", not "energised for 30 ms".
 *
 * The FIRST 0x40 for a given coil is its boot configuration - nine arrive back
 * to back on node 8 at startup, one on node 9 - so it seeds the record and does
 * not count as an event. Everything after it does. */
static void coil_publish(const unsigned char *p, int n)
{
    static unsigned char configured[16][16];
    unsigned node, idx;

    if (n != 14 || !(p[0] & 0x80) || p[2] != 0x40) return;
    node = (unsigned)p[0] & 0x3f;
    if (node != 8 && node != 9) return;
    idx = p[3];
    if (idx >= 16) return;

    led_map();
    if (!led_shm) return;
    led_shm->lvl[node][idx] = p[4];
    if (!configured[node][idx]) { configured[node][idx] = 1; return; }
    led_shm->coil[node][idx]++;
    led_shm->coil_decoded++;
    led_shm->coil_gen++;
}

extern int atoi(const char *);           /* same GCC 14 reason as open/close */

/* ---- VILLAIN VISION (padlcd.h, item 83) --------------------------------
 *
 *     98 <ilen> f2 <sel> <payload...> <cksum> <replylen>
 *
 * The lcdnode's three playfield LCDs are driven by ASSET NUMBERS, not
 * pixels: the game names a stored clip in the card's villain-TV store and
 * the board plays it locally, so nothing image-shaped ever crosses this
 * bus. ONE logical display (fixture display count 1; 299/299 call sites on
 * the same device) feeds all three TVs.
 *
 * The payload's shape is chosen BY LENGTH - 4 a verb, 8 an asset, 14 and 24
 * an asset plus fields nobody has named yet. padlcd.h owns that table, the
 * addresses behind it, and the reason `aux` is not called a range end; this
 * struct is its C twin - keep them in step.
 *
 * Which node is the lcdnode differs per title, so PAD_LCD_NODE names it
 * (watch.sh derives it from node_ident.txt's type=lcdnode row); unset or 0
 * publishes nothing, which is every title without one. */
struct padlcd_shm {
    unsigned magic, version, gen, decoded;
    unsigned asset, aux, rate, verb, x1, x2, x3, bright, fade, ms;
    unsigned ring_head;
    struct {
        unsigned ms, last;
        unsigned short rep;
        unsigned char sel, len, b[22], pad[2];
    } ring[64];
};
#define PADLCD_MAGIC 0x44434c50u
#define PADLCD_VERSION 4u

static struct padlcd_shm *lcd_shm;

static unsigned lcd_node(void)
{
    static int n = -1;
    if (n < 0) {
        const char *e = getenv("PAD_LCD_NODE");
        n = (e && *e) ? atoi(e) : 0;
        if (n < 0 || n > 63) n = 0;
    }
    return (unsigned)n;
}

static void lcd_map(void)
{
    static int tried;
    const char *path;
    int fd;
    void *m;
    if (lcd_shm || tried) return;
    tried = 1;
    path = getenv("PAD_LCD_SHM");
    if (!path || !*path) return;
    fd = open(path, 2 /*O_RDWR*/, 0);
    if (fd < 0) return;
    m = mmap(0, 4096, 3, 1, fd, 0);
    close(fd);
    if (!m || m == (void *)-1) return;
    lcd_shm = (struct padlcd_shm *)m;
    /* Brightness BEFORE the magic: the panel blanks the screen when
     * bright < 128 (the game really does command 0 around clip swaps),
     * so a zero-initialised field would read as "the game said dark"
     * from the first poll until the first 0x80 frame. 255 here means 0
     * below only ever appears because the wire carried it. */
    lcd_shm->bright = 255;
    lcd_shm->magic = PADLCD_MAGIC;
    lcd_shm->version = PADLCD_VERSION;
}

/* Frame periods at 0x5c9340, in 1/1280 s -> fps. A range command carries the
 * INDEX's value, not an fps, and it is decoded here so no reader has to know
 * the table. An unknown value passes through as 0 rather than a wrong fps. */
static unsigned lcd_fps(unsigned period)
{
    static const unsigned char per[8] = { 43, 53, 64, 80, 84, 106, 128, 160 };
    static const unsigned char fps[8] = { 30, 24, 20, 16, 15, 12, 10, 8 };
    unsigned i;
    for (i = 0; i < 8; i++) if (per[i] == period) return fps[i];
    return 0;
}

static unsigned lcd_le32(const unsigned char *q)
{
    return (unsigned)q[0] | ((unsigned)q[1] << 8)
         | ((unsigned)q[2] << 16) | ((unsigned)q[3] << 24);
}

/* ★ WRITTEN AGAINST THE GAME'S OWN FRAME BUILDERS AND ITS DISPATCHER
 * (padlcd.h documents the table, the addresses, and what is still unnamed).
 *
 * Two mis-decodes are buried under this function and both are worth keeping
 * in view. v1 read the payload as u16 ids at stride 4 behind a display
 * index, inventing two screens and turning one command into three bogus
 * asset ids. v2 fixed the screens but kept inventing meaning: it named the
 * 14-byte form's two u32s "first" and "last" and called it a range, from a
 * single capture that happened to contain 54 and 928. The dispatcher at
 * 0x37e49c settles it - the u32 at payload offset 1 is the SAME struct
 * field the one-asset command sends as the asset, so it is the clip; the
 * other u32 is a field nobody has traced to a filler yet, and it is
 * published under a name that admits that.
 *
 * The 24-byte form is decoded here too. v2 dropped it as unknown while its
 * own header claimed it had no call sites; kind 3 of the dispatcher
 * (0x37e578 -> 0x51a86c) is that call site, and it carries the asset in the
 * same slot as the other two.
 *
 * Every cmd-f2 selector is ringed, decoded or not - v1 ringed only the
 * frames it already believed in, which is precisely how its mis-parse
 * survived a live capture that contained the evidence against it. */
static void lcd_publish(const unsigned char *p, int n)
{
    unsigned node, sel, ilen, slot, k, plen;
    if (n < 6 || !(p[0] & 0x80)) return;
    node = p[0] & 0x3f;
    if (!lcd_node() || node != lcd_node()) return;
    if (p[2] != 0xf2) return;
    sel = p[3];
    if (sel < 0x80u) return;      /* every LCD selector is >= 0x80          */
    ilen = p[1];                  /* cmd..cksum, so payload ends at p[1+ilen]*/
    if (ilen < 3 || (unsigned)n < ilen + 2) return;
    lcd_map();
    if (!lcd_shm) return;

    /* THE RAW RING FIRST, so a mis-parse below is still on record - but
     * COALESCED (v4): a frame identical to the previous slot bumps that
     * slot's count instead of taking a new one. The first live reading
     * showed why this is not optional: the 0x90 poll arrives at 60 Hz
     * with a constant payload, so a raw ring held ~1 s of history and
     * every play command was flushed within a second of arriving. A 60 Hz
     * constant IS a count; recording it 64 times over is what destroyed
     * the evidence, not what kept it. */
    plen = ilen - 3;              /* bytes after the selector, before cksum */
    if (plen > 22) plen = 22;
    if (lcd_shm->ring_head) {
        slot = (lcd_shm->ring_head - 1u) % 64u;
        if (lcd_shm->ring[slot].sel == (unsigned char)sel
                && lcd_shm->ring[slot].len == (unsigned char)plen) {
            for (k = 0; k < plen; k++)
                if (lcd_shm->ring[slot].b[k] != p[4 + k]) break;
            if (k == plen) {
                lcd_shm->ring[slot].last = (unsigned)pad_ms();
                if (lcd_shm->ring[slot].rep < 0xffffu)
                    lcd_shm->ring[slot].rep++;
                goto ringed;
            }
        }
    }
    slot = lcd_shm->ring_head % 64u;
    lcd_shm->ring[slot].ms   = (unsigned)pad_ms();
    lcd_shm->ring[slot].last = lcd_shm->ring[slot].ms;
    lcd_shm->ring[slot].rep  = 1;
    lcd_shm->ring[slot].sel  = (unsigned char)sel;
    lcd_shm->ring[slot].len  = (unsigned char)plen;
    for (k = 0; k < plen; k++) lcd_shm->ring[slot].b[k] = p[4 + k];
    lcd_shm->ring_head++;
ringed:

    if ((sel & 0xf8u) == 0x98u) {           /* the play family              */
        if (ilen == 4) {
            /* [verb]. 1 and 2 precede content (play looping / play once);
             * 3, 4 and 5 arrive alone from dispatch kinds 7, 5 and 6. The
             * NUMBER is published: v2 stored these in a field called `mode`
             * whose reader only had words for 1 and 2, so a bare 3/4/5 -
             * every candidate for "stop" - reached the panel as silence. */
            lcd_shm->verb = p[4];
        } else if (ilen == 8) {             /* [0] [u32 A]                  */
            lcd_shm->asset = lcd_le32(p + 5);
            lcd_shm->aux = lcd_shm->rate = 0;
            lcd_shm->x1 = lcd_shm->x2 = lcd_shm->x3 = 0;
        } else if (ilen == 14 || ilen == 24) {
            /* [flags][u32 A][u32 D][u16 rate], and for 24 three more
             * fields after it. A is the clip either way. */
            lcd_shm->asset = lcd_le32(p + 5);
            lcd_shm->aux   = lcd_le32(p + 9);
            lcd_shm->rate  = lcd_fps((unsigned)p[13]
                                     | ((unsigned)p[14] << 8));
            if (ilen == 24) {
                lcd_shm->x1 = lcd_le32(p + 15);
                lcd_shm->x2 = lcd_le32(p + 19);
                lcd_shm->x3 = (unsigned)p[23] | ((unsigned)p[24] << 8);
            } else {
                lcd_shm->x1 = lcd_shm->x2 = lcd_shm->x3 = 0;
            }
        } else {
            return;                         /* ringed, not understood       */
        }
        lcd_shm->ms = (unsigned)pad_ms();
        lcd_shm->decoded++;
        lcd_shm->gen++;
    } else if ((sel & 0xf8u) == 0x80u && ilen >= 5) {
        lcd_shm->bright = p[4];             /* [brightness][fade]           */
        lcd_shm->fade   = p[5];
        lcd_shm->gen++;
    }
    /* 0x90 (status poll, wants a 12-byte reply) and the never-called 0x88 /
     * 0xb8 builders are ringed and left alone. (An earlier note here blamed
     * the 250 ms re-send on the unanswered poll; measured WITH the echo on,
     * every command is still double-issued 250 ms apart - pending clears on
     * SEND (0x37e484), it is the game's own habit. The echo stays only
     * because a correct-length reply keeps a raw bus dump readable.)
     * NOTE decoded++ fires ONLY for the play family above - never the 60 Hz
     * poll - so a reader can tell "the game re-commanded the display"
     * from "the block merely re-read". */
}

/* Budgeted like the skip log, and off unless PAD_LED_DEC_LOG is set. A run
 * decodes thousands of these; the point is a SAMPLE to compare against the
 * dropped frames, not a transcript. */
static int led_dec_log(void)
{
    static int budget = -1, used;
    if (budget < 0) {
        const char *e = getenv("PAD_LED_DEC_LOG");
        budget = e ? (*e ? atoi(e) : 200) : 0;
    }
    if (budget > 0 && used < budget) { used++; return 1; }
    return 0;
}

static void led_publish(const unsigned char *p, int n)
{
    unsigned node, cmd, blen, i;
    const unsigned char *body;
    static const struct { int extra, gap; } shape[3] = { {1,1}, {2,1}, {3,2} };
    int s;

    if (n < 5 || !(p[0] & 0x80)) return;
    node = p[0] & 0x3f;
    cmd  = p[2];

    /* THE ATTRACT LIGHT SHOW, announced once, because it is the "past Tech
     * Alerts" signal gamestate.sh reads (item 27). The old test - "a clip
     * opened" (filesrc) - was broken by star_wars_le, which serves clips WHILE
     * sitting on the Tech Alerts screen; its attract clip set is a superset of
     * its alerts clip set, so nothing on the video side can see the state.
     * What CAN see it is the game's own output to the boards: on the full
     * godzilla_pro boot trace (led_trace_1d.log), the whole Tech Alerts period
     * carried exactly 2 lamp-class frames (strip-board boot config, one a4
     * each to nodes 12 and 14) against ~3800 in the first 80 s of attract,
     * and the first attract lamp frame landed 300 ms after the Service Back
     * press that took. The threshold of 10 absorbs boot config with a wide
     * margin; attract crosses it in well under a second.
     *
     * Counted on ANY node, BEFORE the insert-node gate, on purpose: the gate
     * is Godzilla's node numbering, and a title whose insert boards sit
     * elsewhere (the group->node mapping shifts per title - see nodecensus.py)
     * must still trip this line. One line per run; gamestate.sh greps it. */
    /* 0x70 joined the set for the OLDER (swelf) generation - item 79.
     * batman sat visibly in attract while this announcer stayed silent,
     * because that generation's show never speaks the a2-family. The
     * command census (PAD_CMD_CENSUS=1, batman 2026-08-24) measured cmd 70
     * - the base-layer lamp write this file already decodes - at ~109/s
     * sustained through attract against ZERO occurrences in the whole
     * boot-plus-Tech-Alerts window, a wider margin than godzilla's own
     * signal has. The show families this file does NOT decode (72/52/8a,
     * ~35-40/s each) are deliberately not counted: nothing is known about
     * their semantics, and guessed lamp commands are how this detector
     * went wrong twice before. The 30-in-3s rate gate below still guards
     * the star_wars service-menu-entry trap. */
    if (cmd == 0x70 ||
        cmd == 0x97 || cmd == 0xa2 || cmd == 0xa3 || cmd == 0xa4 ||
        cmd == 0xa5 || cmd == 0xa6 || cmd == 0xb4 || cmd == 0xb5) {
        /* RATE-QUALIFIED, not a bare count. The first version announced at
         * the 10th lamp command ever, and star_wars_le promptly showed why
         * that is wrong: a press that walks into the SERVICE MENU emits a
         * small lamp burst on entry, the 10-count tripped on it, autoattract
         * declared "past Tech Alerts" over a parked menu, and the run was
         * lost (2026-08-10, the surface-fix verification run). The attract
         * show is not a count, it is a RATE - ~40 commands/s sustained on
         * both titles measured - so the declaration now needs 30 lamp
         * commands inside 3 seconds: attract crosses that inside the first
         * second, Godzilla's whole alerts wait had 2 commands total, and a
         * menu-entry blip would need to sustain 10/s for 3 s to fake it. */
        static unsigned long t30[30];         /* time of the (n-30)th command */
        static unsigned nlamps;
        static int announced;
        if (!announced) {
            unsigned long now = pad_ms();
            unsigned slot = nlamps % 30;
            if (nlamps >= 30 && now - t30[slot] <= 3000) {
                char m[112];
                snprintf(m, sizeof m,
                         "[led] light show running: 30 lamp commands in "
                         "%lu ms (last node=%u cmd=%02x, %lu ms)\n",
                         now - t30[slot], node, cmd, now);
                logmsg(m);
                announced = 1;
            } else {
                t30[slot] = now;
                nlamps++;
            }
        }
    }

    if (!led_insert_node(node)) return;

    /* The boot enumeration: remember which indices this board really has.
     *
     * ORDER IS RECORDED, not just membership. The a6 fade frames carry a
     * BITMAP rather than indices, so bit k has to mean "the k-th LED of this
     * board" - and which LED that is depends on the order the board announced
     * them in. led_known is a bitmap and cannot answer that; led_order can.
     * Measured: node 9 announces 71 LEDs and a 9-byte bitmap is exactly
     * ceil(71/8), which is the observation that made the bitmap reading
     * credible in the first place. */
    if (n == 6 && (cmd == 0x84 || cmd == 0x85)) {
        if (p[3] < 96) {
            if (!led_known[node][p[3]] && led_count[node] < 96)
                led_order[node][led_count[node]++] = p[3];
            led_known[node][p[3]] = 1;
        }
        return;
    }
    /* ---- THE SERVICE MENU'S OWN SHAPES (cmd 94/95 set, cmd 70 clear) ------
     *
     * Measured on turtles_pro's Diagnostics -> LED Tests -> Single LED Test,
     * driven one named fixture at a time (run 2 of item 50, 85.7 s window,
     * 126k frames): the test never speaks 97/a2/b4/b5 at all. Its whole cycle
     * is a per-LED off sweep and one set:
     *
     *   [node][05][70][idx][v16 lo][v16 hi]  x3948   every idx, value 0000
     *   [node][04][94][idx][val]             x220    the lit fixture
     *   [node][04][95][idx][val]             x212    ditto (alternates with 94)
     *
     * and the walk of (node, idx) across 17 stepped fixtures tracked the
     * glass exactly: fixture 2 START BUTTON = node 1 idx 2, TEAM UP-R =
     * node 8, and so on. godzilla's GAME mode also emits the len-7/len-8
     * forms (178 x95, 6579 x70 in the item 27 capture), all dropped until
     * now. The longer 94s (blen 7..14, godzilla) are some run/compressed
     * form this does not claim to read; the length test keeps them out.
     *
     * NO led_known GATE HERE, and that is measured too: node 1 announces 6
     * LEDs yet the test names and lights node 1 idx 7 (fixture 7). The
     * membership gate exists to keep the LOOSE pair-shape heuristics from
     * eating misparses; an exact cmd+length match has no such ambiguity, and
     * gating would go dark on exactly the fixtures the oracle lights. The
     * bound stays: val[] is 96 wide.
     *
     * 94/95 HOLD ONLY WHILE REFRESHED, and the hammering is the evidence: the
     * test re-asserts the ONE lit fixture at ~7.5 Hz (94/95 alternating,
     * ~133 ms apart, 432 frames for 17 fixtures) and never sends an OFF for
     * indices past the 70-sweep's 0x00..0x26 window - stepping 8:55 -> 8:56
     * emits only an a2 flash tail (37 b8 00 ff 00 08, an overlay by the 651-
     * frame rule) and starts hammering 56. A latch would leave a growing
     * trail of lit fixtures behind the SINGLE LED TEST; a watchdog output
     * that decays when the refresh stops goes dark by itself, which is what
     * the real glass shows and what the refresh rate is FOR. So a 94/95
     * lands in the fade ring as a flat hold - from = to = value, fall = 33
     * units (~400 ms at the reader's 12 ms/unit) - re-armed by every
     * refresh, expiring onto the base val[] (0) when the game moves on.
     * cmd 70 is the base layer's own clear (value observed 0000, 6579 of
     * 6579 on godzilla, 7755 of 7755 on turtles) and writes val[] direct. */
    if (n == 7 && (cmd == 0x94 || cmd == 0x95)) {
        if (p[3] < 96) {
            unsigned slot;
            led_map();
            if (!led_shm) return;
            slot = led_shm->fade_head % 96u;
            led_shm->fade[slot].ms    = (unsigned)pad_ms();
            led_shm->fade[slot].node  = (unsigned char)node;
            led_shm->fade[slot].start = p[3];
            led_shm->fade[slot].end   = p[3];
            led_shm->fade[slot].from  = p[4];
            led_shm->fade[slot].to    = p[4];
            led_shm->fade[slot].rise  = 0;
            led_shm->fade[slot].fall  = 33;
            led_shm->fade[slot].pad   = 0;
            led_shm->fade_head++;
            led_shm->decoded++;
            led_shm->gen++;
        }
        return;
    }
    if (n == 8 && cmd == 0x70) {
        if (p[3] < 96) {
            led_map();
            if (!led_shm) return;
            led_shm->val[node][p[3]] = p[4];
            led_shm->decoded++;
            led_shm->gen++;
        }
        return;
    }
    if (cmd != 0x97 && cmd != 0xa2 && cmd != 0xa3 && cmd != 0xa4 &&
        cmd != 0xa5 && cmd != 0xa6 && cmd != 0xb4 && cmd != 0xb5) return;

    led_map();
    if (!led_shm) return;

    body = p + 3;
    blen = (unsigned)n - 5;                  /* drop checksum + reply-length */

    /* ---- RANGE FADES (cmd b4 up / b5 down) - TESTED BEFORE THE INDEXED
     * SHAPES, WHICH IS THE WHOLE FIX. A 3-byte body parses beautifully as the
     * single-write shape, so `0e b6 0f` - lamps 14..54 fading at rate 0x0f -
     * spent weeks decoded as "lamp 14 := 0x0f": one dim dot per bank sweep,
     * and a RATE byte written into a BRIGHTNESS. The census that caught it:
     * 44 of 44 b4 blen=3 and 22 of 22 b5 fit [start][0x80|end][rate] and 0 of
     * 66 carry the 0x0f gap byte a genuine single write has (97: 71 of 80).
     *
     *   [start][0x80|end][rate]           blen 3
     *   [start][mid][0x80|end][rate]      blen 4 (refs strictly ascend; the
     *                                     mid point is not yet rendered)
     *
     * b4 fades the range UP to full, b5 DOWN to off - direction from what
     * follows on the wire (the next write into a b4'd range asserts HIGH) and
     * from the rate alphabet matching a2's. Unlike an a2 pulse this MOVES THE
     * BASE: val[] takes the target, and the ring entry's envelope expires
     * onto it, so the window ramps and lands with no code of its own. */
    if ((cmd == 0xb4 || cmd == 0xb5) && (blen == 3 || blen == 4)) {
        unsigned s0 = body[0], e7 = body[blen - 2], rate = body[blen - 1];
        unsigned mid_ok = blen == 3 ||
            (body[1] < 96 && led_known[node][body[1]] && body[1] >= body[0]);
        if ((e7 & 0x80) && s0 < 96 && led_known[node][s0]
            && (e7 & 0x7f) < 96 && led_known[node][e7 & 0x7f]
            && s0 <= (e7 & 0x7f) && mid_ok) {
            unsigned e0 = e7 & 0x7f, k;
            unsigned char frm = led_shm->val[node][s0];
            unsigned char to = (cmd == 0xb4) ? 0xff : 0x00;
            unsigned slot = led_shm->fade_head % 96u;
            for (k = s0; k <= e0; k++)
                if (led_known[node][k])
                    led_shm->val[node][k] = to;
            led_shm->decoded += (e0 - s0 + 1);
            led_shm->gen++;
            led_shm->fade[slot].ms    = (unsigned)pad_ms();
            led_shm->fade[slot].node  = (unsigned char)node;
            led_shm->fade[slot].start = (unsigned char)s0;
            led_shm->fade[slot].end   = (unsigned char)e0;
            led_shm->fade[slot].from  = frm;
            led_shm->fade[slot].to    = to;
            led_shm->fade[slot].rise  = (unsigned char)(cmd == 0xb4 ? rate : 0);
            led_shm->fade[slot].fall  = (unsigned char)(cmd == 0xb4 ? 0 : rate);
            led_shm->fade[slot].pad   = 0;
            led_shm->fade_head++;
            return;
        }
    }

    for (s = 0; s < 3; s++) {
        unsigned extra = (unsigned)shape[s].extra, gap = (unsigned)shape[s].gap;
        unsigned cnt;
        if (blen < extra + 2 || ((blen - extra) & 1)) continue;
        cnt = (blen - extra) / 2;
        if (!cnt) continue;
        /* A single-lamp 2N+1 frame must actually CARRY its 0x0f gap byte.
         * With one index the structural test is nearly no test at all, and
         * this shape was eating the a4/a5 pair frames ([lamp][lamp][rate] -
         * `36 37 bb` became "lamp 0x36 := 0xbb", a rate as a brightness).
         * 71 of 80 genuine single writes have the 0x0f; the census says the
         * pair/range families never do. The 9 nonconforming frames now land
         * in the skip log, which is where an undecoded shape belongs. */
        if (cnt == 1 && extra == 1 && body[1] != 0x0f) continue;
        for (i = 0; i < cnt; i++)
            if (body[i] >= 96 || !led_known[node][body[i]]) break;
        if (i != cnt) continue;              /* not all valid indices */
        for (i = 0; i < cnt; i++)
            led_shm->val[node][body[i]] = body[cnt + gap + i];
        led_shm->decoded += cnt;
        led_shm->gen++;
        /* The lamps the WORKING path addresses, under the same env var. The
         * bitmap reading of the a6 frames has to be checked against something,
         * and "do the two paths drive the same lamps" is a check that does not
         * need the operator menu: a mapping that is off by an offset would
         * light a set of lamps the indexed path never touches. */
        if (led_dec_log()) {
            char l[256];
            int q = 0;
            /* The WHOLE body, and rlen, for the ones that decode: the 2-byte
             * frames have to be read against the 3-byte form of the same
             * command, and only the 3-byte form decodes. Logging just the
             * index list answered a question nobody had. */
            q += snprintf(l + q, sizeof l - q,
                          "[leddec] node=%u cmd=%02x rlen=%u blen=%u body=",
                          node, cmd, p[n - 1], blen);
            for (i = 0; i < blen && q < (int)sizeof l - 6; i++)
                q += snprintf(l + q, sizeof l - q, "%02x", body[i]);
            snprintf(l + q, sizeof l - q, "\n");
            logmsg(l);
        }
        return;
    }
    /* ---- THE BITMAP SHAPE (cmd a6): the other half of the light show ------
     *
     * The indexed shapes above carry (index, value) pairs. This one carries a
     * BITMAP over the board's own LED list and then one level per set bit:
     *
     *   [3 payload bytes] [mask bytes] [one level per set bit]
     *   bit k (LSB first within each byte) = the k-th LED THIS BOARD
     *   ANNOUNCED at boot, not raw index k
     *   levels are 0x00, 0x7f or 0xff
     *
     * Everything about that sentence was measured on 396 dropped frames from
     * attract mode, and it is worth writing down HOW, because "a decode that
     * looks plausible" is the failure mode this file has already had once:
     *
     *  - THE SPLIT. 44 of 45 frames have exactly one split whose level region
     *    is drawn purely from {00,7f,ff}; a wrong split spills mask bytes into
     *    it. Scanning the mask length upward and taking the first length that
     *    satisfies blen = 3 + mlen + popcount() lands on that same split, so
     *    the parse below needs no heuristic.
     *  - THE MAPPING, versus the obvious alternative. Node 9 announced 71 LEDs
     *    at indices 0,1,8,9..87 - it has NO lamp at index 2..7. Read as raw
     *    indices, these frames address hardware that is not on the board 21%
     *    of the time (160 of 769 bits). Read as positions in the announced
     *    list: 2 of 769, and both are one bit past the end of a truncated
     *    mask. A 9-byte mask is also exactly ceil(71/8), and 9 is the longest
     *    mask ever seen.
     *  - AGAINST A CONTROL, because the first test I ran had no power and a
     *    shuffled control scored the same as the hypothesis. Shuffling the
     *    announced list keeps every lamp valid and destroys the structure:
     *    complete RGB triples addressed in one frame go from 23 (this
     *    mapping) to 1 (shuffled) to 4 (raw).
     *
     * WHAT IS STILL NOT PROVEN: that the k-th announced LED is the lamp the
     * TABLE calls index k - i.e. this is verified against the board, not
     * against the physical playfield. The oracle for that is the game's own
     * Diagnostics -> LED Tests, one fixture at a time by name. Until someone
     * runs it, a systematic permutation within the board would be invisible
     * here. It renders a coherent light show either way, which is exactly why
     * that caveat needs to stay in writing. */
    if (cmd == 0xa6 && blen >= 4) {
        unsigned mlen;
        for (mlen = 1; 3 + mlen <= blen; mlen++) {
            unsigned bits = 0, j, k, ok = 1, wrote = 0;
            for (j = 0; j < mlen; j++)
                for (k = 0; k < 8; k++)
                    bits += (body[3 + j] >> k) & 1;
            if (3 + mlen + bits != blen) continue;
            /* Every bit must land on a lamp the board announced. A frame that
             * fails this is left to the skip counter rather than guessed at -
             * writing val[] for a lamp that does not exist is how a decode
             * starts lighting the wrong inserts convincingly. */
            for (j = 0; j < mlen && ok; j++)
                for (k = 0; k < 8; k++)
                    if ((body[3 + j] >> k) & 1)
                        if (j * 8 + k >= led_count[node]) { ok = 0; break; }
            if (!ok) break;
            for (j = 0; j < mlen; j++)
                for (k = 0; k < 8; k++)
                    if ((body[3 + j] >> k) & 1)
                        led_shm->val[node][led_order[node][j * 8 + k]] =
                            body[3 + mlen + wrote++];
            led_shm->decoded += wrote;
            led_shm->gen++;
            return;
        }
    }

    /* ---- FRAMES THAT ARE NOT LAMP DATA AT ALL -----------------------------
     *
     * A 2-byte body whose first byte is a lamp this board announced and whose
     * second byte is 0x80 | another announced lamp is a RANGE - two lamp
     * REFERENCES and no level anywhere in it. Measured over 318 of them:
     *
     *   body[0] is an announced lamp                318/318 = 100%
     *   body[1] & 0x7f is an announced lamp         318/318 = 100%
     *   body[1] has bit 7 set                       318/318 = 100%
     *   body[1] & 0x7f == body[0] + 1               285/318 =  90%
     *                       (the rest are wider spans: 23->47, 30->38)
     *
     * ★ DO NOT "FIX" THIS BY ADDING A {0,0} SHAPE TO THE TABLE ABOVE. That is
     * the obvious one-line change - a 2-byte body reads beautifully as
     * (index, value) - and it is WRONG: it would write a LAMP NUMBER into a
     * brightness. The thing that gives it away is that the second byte never
     * once dips below 0x85 in 399 samples, because it is not a level, it is
     * 0x80 | a lamp number. My own first test asked whether the RAW byte was
     * an announced index, got 0 of 399, and concluded it was a value - a
     * rigged question, since bit 7 is set in every single sample.
     *
     * They are NOT counted as skipped, because `skipped` is what the
     * playfield window shows as "N frames NOT decoded" and these are not
     * frames we are failing to read - they are frames with no lamp data in
     * them. They were 88% of everything still being dropped, so counting them
     * turned that indicator into a permanent false alarm. They still appear
     * in PAD_LED_SKIP_LOG.
     *
     * `cmd a2` with a 6-byte body opens with the SAME range prefix (45 of 45:
     * body[0] an announced lamp, body[1] = 0x80 | an announced lamp) followed
     * by four payload bytes. */

    /* ---- THE FADE LAYER (cmd a2, blen 6): the animation half of the show --
     *
     *     [start][0x80|end][FROM][TO][RISE][FALL]
     *
     * A ONE-SHOT PULSE ENVELOPE over the lamp range: go FROM -> TO using the
     * rate slot for the direction of travel, then return to FROM using the
     * other slot, 0 = instantly. Established 2026-08-07 over 93 captured
     * frames (every c:/tmp capture at once):
     *
     *  - 93/93 fit the envelope once "0 = instant" is read into the slots;
     *    86 fit the naive one-directional split and the 7 exceptions are all
     *    one frame, `00 ff 00 02` - instant-on then slow decay, a flash tail.
     *  - the SAME command repeats on the SAME range (x8 for `00 ff 0a 00` on
     *    47..50) - a re-triggered blink, not a state machine. Successive
     *    fades on one range do NOT chain end-to-start (0 of 23), which is
     *    what killed the "it moves the base level" reading.
     *  - the mid-level payloads land on the fixtures that FLICKER on the
     *    real machine: node 9's 72..86 -R BUILDING FIRE lamps get 11->0f
     *    fall 6d (ember) and 0f->ee rise 92 (flare); the -G bank 73..87
     *    fades out. The semantics named themselves.
     *
     * The pulses are an OVERLAY: later base writes into a pulsed range agree
     * with TO only 57 of 651 times, so val[] is deliberately NOT touched -
     * the base layer owns it and a pulse ends where the base says. What is
     * NOT established: the rate unit (the reader scales it; the oracle is
     * Diagnostics -> LED Tests) and together-vs-sweep across a wide range.
     * The longer a2/b4/b5 bodies remain undecoded and still count skipped. */
    /* ---- FORM A (long a2): a multi-lamp fade PROGRAM STEP ---------------
     *
     *     [lamp refs..., last | 0x80] [FROM x N] [TO x N]     blen == 3N
     *
     * The lamp list ends at the first bit7-flagged byte. Established from
     * 16 unique long bodies across every capture, and the structure signs
     * itself: wherever the list carries three CONSECUTIVE lamps, the TO
     * region carries an identical value TRIPLE (a2a2a2, 757575, c7c7c7...)
     * - an RGB fixture's three channels fading to one colour. No rate byte
     * anywhere in the frame, so the reader's nominal rate applies (0x0a,
     * the wire's own most common). These MOVE THE BASE like b4/b5: val[]
     * takes TO and the envelope expires onto it. The header-prefixed long
     * forms (8x 1a/2a Fx ...) remain undecoded and still count skipped.
     *
     * Tried HERE - after the indexed shapes - because every one of these
     * frames landed in the skip log until today: the shapes loop is proven
     * by that data never to claim them, and this order cannot steal a
     * genuine indexed frame the loop would have taken first. */
    if (cmd == 0xa2 && blen > 6 && (blen % 3) == 0) {
        unsigned nref = 0, k, okA = 0;
        for (k = 0; k < blen; k++) {
            unsigned v = body[k] & 0x7f;
            if (v >= 96 || !led_known[node][v]) break;
            nref++;
            if (body[k] & 0x80) { okA = 1; break; }
        }
        if (okA && blen == 3 * nref && nref >= 3) {
            const unsigned char *frm = body + nref, *to = body + 2 * nref;
            for (k = 0; k < nref; k++) {
                unsigned lamp = body[k] & 0x7f;
                unsigned slot = led_shm->fade_head % 96u;
                led_shm->val[node][lamp] = to[k];
                led_shm->fade[slot].ms    = (unsigned)pad_ms();
                led_shm->fade[slot].node  = (unsigned char)node;
                led_shm->fade[slot].start = (unsigned char)lamp;
                led_shm->fade[slot].end   = (unsigned char)lamp;
                led_shm->fade[slot].from  = frm[k];
                led_shm->fade[slot].to    = to[k];
                led_shm->fade[slot].rise  = to[k] >= frm[k] ? 0x0a : 0;
                led_shm->fade[slot].fall  = to[k] >= frm[k] ? 0 : 0x0a;
                led_shm->fade[slot].pad   = 0;
                led_shm->fade_head++;
            }
            led_shm->decoded += nref;
            led_shm->gen++;
            return;
        }
    }

    if (blen == 6
        && body[0] < 96 && led_known[node][body[0]]
        && (body[1] & 0x80)
        && (body[1] & 0x7f) < 96 && led_known[node][body[1] & 0x7f]
        && body[0] <= (body[1] & 0x7f)) {
        unsigned slot = led_shm->fade_head % 96u;
        led_shm->fade[slot].ms    = (unsigned)pad_ms();
        led_shm->fade[slot].node  = (unsigned char)node;
        led_shm->fade[slot].start = body[0];
        led_shm->fade[slot].end   = body[1] & 0x7f;
        led_shm->fade[slot].from  = body[2];
        led_shm->fade[slot].to    = body[3];
        led_shm->fade[slot].rise  = body[4];
        led_shm->fade[slot].fall  = body[5];
        led_shm->fade[slot].pad   = 0;
        led_shm->fade_head++;     /* AFTER the entry, single writer */
        return;
    }
    {
        int is_range = blen == 2
            && body[0] < 96 && led_known[node][body[0]]
            && (body[1] & 0x80)
            && (body[1] & 0x7f) < 96 && led_known[node][body[1] & 0x7f];
        if (!is_range)
            led_shm->skipped++;
    }

    /* ---- PAD_LED_SKIP_LOG=N: SHOW THE FRAMES WE THROW AWAY ----------------
     *
     * The counter above has existed since version 1 and says HOW MANY. It has
     * never said WHAT, so the frames that carry the missing half of the light
     * show have never been looked at. Measured in attract mode 2026-08-05:
     * decoded +229 against skipped +225 over 60 s, and 3-8x more skipped than
     * decoded during the stretches a human calls frozen. That is the material
     * item 1b needs, and it was being dropped on the floor unseen.
     *
     * BUDGETED, and that is not a detail. PAD_NB_LOG is the obvious instrument
     * and it is the wrong one: it quadruples the boot and buries the frames
     * that matter under a hundred thousand that do not (see the coil probe
     * below, which learned this the same way). This prints only frames that
     * ALREADY failed to decode, and stops after N of them - default 200, which
     * is a few seconds of attract and costs nothing measurable.
     *
     * The format is deliberately greppable and complete: node, command, body
     * length, then every body byte, because the shape is exactly what is not
     * understood yet. Nothing here interprets - interpreting is what produced
     * the wrong decode the first time. */
    {
        static int budget = -1, used;
        char line[256];
        int k = 0, j;
        if (budget < 0) {
            const char *e = getenv("PAD_LED_SKIP_LOG");
            budget = e ? atoi(e) : 0;
            if (e && !*e) budget = 200;      /* set-but-empty means "on" */
        }
        if (budget > 0 && used < budget) {
            used++;
            /* THE BOARD'S OWN ENUMERATION, once per node, before the frames.
             * The a6 frames appear to carry a BITMAP over this board's LEDs
             * rather than raw indices - the longest mask seen on node 9 is 9
             * bytes = 72 slots, which is ceil(69/8) for the 69 LEDs led_io.txt
             * lists. That is a hypothesis about which the TABLE cannot be the
             * judge: the table is what a human wrote down, and led_known is
             * what the BOARD said on the wire at boot. Print the wire's answer
             * so the mapping is tested against the machine. */
            {
                static unsigned char dumped[64];
                if (node < 16 && !dumped[node]) {
                    char e[512];
                    int q = 0, x;
                    dumped[node] = 1;
                    /* IN ARRIVAL ORDER. Printing the bitmap instead would sort
                     * it by index and quietly answer a different question. */
                    q += snprintf(e + q, sizeof e - q, "[ledenum] node=%u order=", node);
                    for (x = 0; x < led_count[node]; x++)
                        if (q < (int)sizeof e - 8)
                            q += snprintf(e + q, sizeof e - q, "%d,", led_order[node][x]);
                    snprintf(e + q, sizeof e - q, " count=%d\n", led_count[node]);
                    logmsg(e);
                }
            }
            /* plen/sum/rlen come from the FRAME, not the payload:
             *   [0x80|node] [payload_len+1] [payload...] [checksum] [reply_len]
             * rlen is the one that matters. A frame the master expects an
             * answer to is a READ, and decoding a read as a lamp write would
             * light lamps nobody drove - which is precisely the failure this
             * file keeps having to avoid. The 2-byte a4/a5 frames look like
             * (index, value) and 360 of 399 of them carry the same second
             * byte to the same lamp, which is what a poll looks like and not
             * what a light show looks like. rlen settles it. */
            k += snprintf(line + k, sizeof line - k,
                          "[ledskip] node=%u cmd=%02x plen=%u rlen=%u sum=%02x "
                          "blen=%u body=", node, cmd, p[1], p[n - 1], p[n - 2],
                          blen);
            for (j = 0; j < (int)blen && k < (int)sizeof line - 4; j++)
                k += snprintf(line + k, sizeof line - k, "%02x", body[j]);
            /* Which indices the board actually enumerated, so a reader can see
             * at a glance whether the lead bytes are indices at all - the
             * validity test above is the thing that rejected this frame. */
            k += snprintf(line + k, sizeof line - k, " known=");
            for (j = 0; j < (int)blen && j < 8 && k < (int)sizeof line - 4; j++)
                k += snprintf(line + k, sizeof line - k, "%d",
                              body[j] < 96 && led_known[node][body[j]] ? 1 : 0);
            snprintf(line + k, sizeof line - k, " (%d/%d)\n", used, budget);
            logmsg(line);
            if (used == budget)
                logmsg("[ledskip] budget spent (raise PAD_LED_SKIP_LOG)\n");
        }
    }
}

/* ---- THE COIL PROBE (PAD_COIL_PROBE=1) ---------------------------------
 *
 * WHY NOT JUST RAISE PAD_NB_LOG. That is the obvious instrument and it is the
 * wrong one twice over. It quadruples the boot, so a deliberate coil experiment
 * - start a game, hit a slingshot, watch the wire - cannot reach a playable
 * state inside a sane run; and it buries the ten frames that matter under a
 * hundred thousand that do not. Worse, it is self-defeating here: at 1.5M lines
 * the boot was still running after four minutes and the run had to be thrown
 * away.
 *
 * WHAT THIS LOGS INSTEAD. Nodes 8 and 9 are the coil boards - the device table
 * puts all ten playfield coils there, and the boot enumeration agrees to the
 * index: nine `40 <idx>` records on node 8 for indices 0..8, exactly one on
 * node 9 for index 6, against ten coils in the table with those same
 * (group, index) pairs. This prints a frame from those two boards ONLY WHEN ITS
 * PAYLOAD DIFFERS from the last frame carrying the same command byte. A status
 * frame that repeats itself 188 times costs one line; the frame that changes
 * the moment a solenoid fires costs one line too, and lands in a log with
 * almost nothing else in it.
 *
 * The switch poll (0x11) and the LED writes are skipped - they change every
 * frame by design and are already decoded. */
static int coil_probe_on(void)
{
    static int v = -1;
    if (v < 0) {
        const char *e = getenv("PAD_COIL_PROBE");
        v = (e && *e && *e != '0') ? 1 : 0;
    }
    return v;
}

static void coil_probe(const unsigned char *p, int n)
{
    static unsigned char last[2][256][64];
    static unsigned char lastlen[2][256];
    static int budget = 20000;
    unsigned node, cmd, slot, len, i;
    char line[HEXBUF + 128], h[HEXBUF];

    if (!coil_probe_on() || n < 3 || !(p[0] & 0x80)) return;
    node = (unsigned)p[0] & 0x3f;
    if (node != 8 && node != 9) return;
    cmd = p[2];
    if (cmd == 0x11) return;                                  /* switch poll  */
    if (cmd == 0x97 || (cmd >= 0xa2 && cmd <= 0xa6) ||
        cmd == 0xb4 || cmd == 0xb5) return;                   /* LED writes   */

    slot = (node == 8) ? 0u : 1u;
    len = (unsigned)n > 64 ? 64u : (unsigned)n;
    if (lastlen[slot][cmd] == (unsigned char)len) {
        for (i = 0; i < len; i++)
            if (last[slot][cmd][i] != p[i]) break;
        if (i == len) return;                                 /* unchanged    */
    }
    for (i = 0; i < len; i++) last[slot][cmd][i] = p[i];
    lastlen[slot][cmd] = (unsigned char)len;
    if (budget-- <= 0) return;
    hex64(h, p, n);
    snprintf(line, sizeof line, "[coil] node %u cmd %02x %s\n", node, cmd, h);
    logmsg(line);
}

static void nb_log(const char *dir, const unsigned char *p, int n, unsigned long want)
{
    char line[HEXBUF + 128], h[HEXBUF];
    static int inited;
    if (!inited) { inited = 1; nb_log_budget = nb_budget_init(); }
    if (nb_log_budget-- <= 0) return;
    hex64(h, p, n);
    if (want)
        snprintf(line, sizeof line, "[nb] %s want=%lu  last-tx=%s\n", dir, want, h);
    else
        snprintf(line, sizeof line, "[nb] %s len=%d %s\n", dir, n, h);
    logmsg(line);
}

/* PAD_NB_TRACE=1 - a TIMESTAMPED trace of every node bus frame except the three
 * that make up the steady-state poll: 0x11 (the 37.5 Hz switch scan), the bare
 * 0x00 "which node wants servicing", and 0xff (the fault read). Those three are
 * ~17000 + ~5000 per 115 s and bury everything else; what is left is everything
 * the game does on PURPOSE - fire a coil, drive a lamp, configure a board.
 *
 * The timestamp is the whole point: it is what lets a frame be tied to
 * something OUTSIDE the log - a key press, a menu step, a screenshot. Bus write
 * counts look like a clock and are not one (the rate swings 50/s..212/s).
 *
 * PAD_NB_TRACE=2 keeps 0x11 too.
 *
 * The budget SATURATES. `if (n++ < X)` is not a budget - the counter keeps
 * incrementing, wraps at INT_MAX and the tracer comes back to life; that is how
 * an earlier one wrote 7.1 GB in ten minutes. */
static void nb_trace(void)
{
    static int on = -1;
    static int budget = 400000;
    unsigned char cmd;
    char line[HEXBUF + 128], h[HEXBUF];
    if (on == -1) {
        char *p = getenv("PAD_NB_TRACE");
        on = p && p[0] >= '1' && p[0] <= '9' ? p[0] - '0' : 0;
    }
    if (on <= 0 || budget <= 0 || nb_req_len <= 0) return;
    cmd = nb_req_len > 2 && (nb_req[0] & 0x80) ? nb_req[2] : nb_req[0];
    if (on < 2 && (cmd == 0x11 || cmd == 0xff ||
                   (nb_req_len == 1 && nb_req[0] == 0x00)))
        return;
    budget--;
    hex64(h, nb_req, nb_req_len);
    snprintf(line, sizeof line, "[nbts] t=%lu node=%d cmd=%02x len=%d %s\n",
             pad_ms(), (nb_req[0] & 0x80) ? (nb_req[0] & 0x3f) : -1,
             cmd, nb_req_len, h);
    logmsg(line);
}

/* File descriptors are recycled, and the faked[] class table was only ever
 * written on open()/open64(). Scene files are opened with fopen64, which does
 * not go through note(), so a scene that landed on a descriptor number
 * previously used by /dev/ttymxc1 inherited class 'T': shim_read then zero
 * filled the caller's buffer and returned the full count without touching the
 * file. That is invisible - the read "succeeds", cereal gets its bytes, no
 * error is raised - and it is what made every scene deserialize to nothing.
 * Clearing the class on close is the fix. */
int shim_close(int fd) __asm__("close");
int shim_close(int fd)
{
    static int (*real_close)(int);
    if (!real_close) real_close = dlsym(RTLD_NEXT, "close");
    /* ITEM 17: under PAD_OPEN_LOG, say when the node bus tty itself is
     * closed. If the 924 ms maintenance cycle is a port close/reopen, this
     * line plus the [open] line bracket the 681 ms hole exactly. */
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'T') {
        static int mode = -1;
        if (mode < 0) {
            char *p = getenv("PAD_OPEN_LOG");
            mode = (p && p[0] >= '0' && p[0] <= '9') ? p[0] - '0' : 0;
        }
        if (mode) {
            char b[96];
            snprintf(b, sizeof b, "[open] t=%lu CLOSE tty fd=%d\n",
                     pad_ms(), fd);
            logmsg(b);
        }
    }
    if (fd >= 0 && fd < MAXFD) faked[fd] = 0;
    return real_close(fd);
}

/* dup() family: a duplicated descriptor must carry the class of the descriptor
 * it was copied from, and dup2/dup3 must overwrite whatever the destination
 * used to be. Without this, the same stale-class bug returns by another route. */
int shim_dup(int fd) __asm__("dup");
int shim_dup(int fd)
{
    static int (*real_dup)(int);
    int n;
    if (!real_dup) real_dup = dlsym(RTLD_NEXT, "dup");
    n = real_dup(fd);
    if (n >= 0 && n < MAXFD && fd >= 0 && fd < MAXFD) faked[n] = faked[fd];
    return n;
}

int shim_dup2(int fd, int fd2) __asm__("dup2");
int shim_dup2(int fd, int fd2)
{
    static int (*real_dup2)(int, int);
    int n;
    if (!real_dup2) real_dup2 = dlsym(RTLD_NEXT, "dup2");
    n = real_dup2(fd, fd2);
    if (n >= 0 && n < MAXFD && fd >= 0 && fd < MAXFD) faked[n] = faked[fd];
    return n;
}

/* Plain read()/write() on the i2c fd act on the selected slave. */
long shim_read(int fd, void *b, unsigned long n) __asm__("read");
long shim_read(int fd, void *b, unsigned long n)
{
    io_init();
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'I') {
        struct i2c_msg m;
        m.addr = (unsigned short)slot_addr[cur_slot[fd]];
        m.flags = I2C_M_RD; m.len = (unsigned short)n; m.buf = b;
        do_msg(cur_slot[fd], &m);
        return (long)n;
    }
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'T') {
        unsigned char *p = b;
        unsigned long i;
        unsigned sum = 0;
        /* The caller of read() IS the node bus RX handler, which is the entry
         * point to the reply parser - far more direct than fuzzing reply bytes
         * and watching the screen. */
        {
            static int rabudget = 12;
            unsigned long ra = (unsigned long)__builtin_return_address(0);
            if (rabudget-- > 0) {
                char m[120];
                snprintf(m, sizeof m, "[nb] read() called from 0x%lx want=%lu\n", ra, n);
                logmsg(m);
            }
        }
        nb_count(nb_req_len > 2 && (nb_req[0] & 0x80) ? nb_req[2] : nb_req[0], n);
        nb_log("RX", nb_req, nb_req_len, n);
        if (!nb_reply) return 0;

        /* PAD_NB_SILENT=<id,id,...> - do NOT answer for these node addresses.
         *
         * This is a FIDELITY fix, not a workaround. The shim answers for all 64
         * addresses, so every address the game polls looks populated. That is
         * how node 2 ends up registered and graded at all: on the real machine
         * it does not answer, but here it does.
         *
         * The evidence that node 2 is genuinely absent is data-side, not
         * protocol-side. board[+144] is computed at registration by 0x39d3e0 as
         *     max(entry[+30]) + 1
         * over the static config table at *(0x700b2c), counting only kind-3
         * entries (entry[+32]==3) with bit 3 of entry[+34] clear whose node
         * resolves to that slot; the accumulator starts at -1, so "no matching
         * entries" yields 0. Measured: node 7 = 69, node 12 = 460,
         * node 14 = 276, node 2 = 0, and node 2's kind-1 count is 0 too. The
         * game's own configuration assigns node 2 no devices whatsoever.
         *
         * And 0x39d554 makes slot 2 the ONE board whose "registered" bit is
         * board[+144] != 0, so an unpopulated node 2 can never satisfy
         * (flags & 3) == 3 and can never be suppressed. No bus reply can change
         * that. Answering for an address the machine does not have is what
         * manufactures the problem, so the fix is to stop.
         *
         * Returning 0 from read() is a short read, which is exactly what a real
         * absent board looks like to 0x59d824 (and is the one thing that DOES
         * move the ExchangeData counter). */
        if (nb_req_len > 0 && (nb_req[0] & 0x80)) {
            unsigned want = (unsigned)(nb_req[0] & 0x3f);
            /* ★ ITEM 52: SILENT FOR IDENTITY, PRESENT FOR STATUS. The `ff`
             * status poll is carved OUT of the silence and answered below
             * with the ordinary zero-filled word (no faults, no input news).
             *
             * WHY, measured 2026-08-18 on stranger_things: the game's service
             * loop polls `ff` on EVERY node its directory declares, silenced
             * or not, once per pass. On a silenced node the read returns
             * short, the game retries once, times out (10 ms), and then - on
             * ST's node 4, a device-class board on the coil/switch service
             * path - the whole service pass took a ~3.3 s penalty before the
             * next one ran. That was the "one pass every 3.3 s" that made
             * every switch closure wait 0.5-2.9 s for a scan and a 113 ms tap
             * read as seconds of hold; the pass itself was 1 ms. Item 17 saw
             * the same mechanism on godzilla as a ~690 ms cabinet stall from
             * node 2's silence and named this exact suspect in the comment
             * below; node 2 is a light board and its penalty was smaller.
             *
             * WHY THIS IS STILL TRUTHFUL. Silence exists so the board is
             * never IDENTIFIED - never registered, never graded, never
             * wedging the readiness gate (fe/f9/fc/fa/04 stay refused). A
             * status poll on an unregistered address answering "nothing to
             * report" registers nothing: 0x5a43d0 hands the caller two zero
             * words, no fault bits, no input-changed flag. It is what a bus
             * with no board on that address and a master that does not wait
             * on it would look like - which is the machine we are modelling.
             *
             * ★ PER NODE as of 2026-08-22, and nb_silent_ff() has the
             * measurement: answering `ff` for godzilla_le's silenced node 2
             * kept bring-up re-probing its identity until t=100 s, so the
             * carve-out now applies only to the nodes watch.sh names in
             * PAD_NB_SILENT_FF (the optional node4 class it was built for).
             * PAD_NB_SILENT_FF=0 is total silence, =1 the old everywhere. */
            if (nb_is_silent(want) && nb_req_len > 2 && nb_req[2] == 0xff
                    && nb_silent_ff(want))
                goto silent_status_ok;
            if (nb_is_silent(want)) {
                /* ITEM 17: timestamp every refusal. Run 11 showed the cabinet
                 * poll stops for ~690 ms at a time (~138 x the game's 5 ms
                 * retry sleep), and the prime suspect is the game timing out on
                 * THIS deliberate silence. If that is right, these lines arrive
                 * in ~5 ms trains whose cab_ctr values land INSIDE a gap's
                 * counter jump - the counter is the shared timebase, so the
                 * join needs no clock alignment. If the gaps show NO [nbsilent]
                 * train inside them, the theory is dead. */
                static int sbudget = 8000;
                if (sbudget-- > 0) {
                    char sm[96];
                    snprintf(sm, sizeof sm,
                             "[nbsilent] t=%lu node=%u want=%lu ctr=%u\n",
                             pad_ms(), want, n, cab_ctr);
                    logmsg(sm);
                }
                return 0;
            }
        }
    silent_status_ok:
        for (i = 0; i < n; i++) p[i] = 0;

        /* UNADDRESSED reply (request byte 0 has no 0x80). 0x59dbf8 branches on
         * the sign of the request's first byte and hands the caller all n bytes
         * verbatim - no checksum, no status. The only unaddressed reply that is
         * graded is the bus version at 0x59ec8c, which builds
         * major<<16|minor<<8|patch and sets [0x70a478] only when it is >= 0.3.0
         * ("Nodebus: %d.%02d.%d"). The card ships netbridge-0_5_0.hex, so 0.5.0
         * is the version this bus master really has. */
        if (!(nb_req_len > 0 && (nb_req[0] & 0x80))) {
            if (nb_req_len > 0 && nb_req[0] == 0x03 && n >= 3) {
                p[0] = 0; p[1] = 5; p[2] = 0;
            }
            /* ITEM 17, the recurrence gate. `0a 00` is the bus master's aux
             * status query: 0x59ed10 sends it, reads 2 bytes, and fans
             * reply[0] out as single bits. The runtime sweep 0x1d7d88 asks
             * every 30 passes (~270 ms of service) and re-runs the WHOLE
             * aux-device init - 750 ms settle and all, on the bus thread,
             * with the cabinet blind throughout - whenever reply[0] BIT 1
             * is clear (1d7e24: the out written from ubfx ip,#1,#1). A
             * zero-filled reply therefore meant "aux never initialized",
             * once a second, forever: that retry loop was the 74%-blind
             * cabinet and the 39% press loss this item is about. And BIT 0
             * is graded too: when the mode flag at [0x7a919c] is set the
             * sweep takes 1d7e8c first, which re-inits on bit 0 CLEAR
             * before it ever looks at bit 1 - run 20 kept cycling on
             * exactly that with only bit 1 crafted. Bits 0+1 together say
             * what a real bus master says: present and initialized, leave
             * it be. Same kill switch as the MCU model: PAD_I2C_READY=0. */
            if (nb_req_len == 2 && nb_req[0] == 0x0a && n >= 1) {
                static int on = -1;
                if (on == -1) {
                    char *q = getenv("PAD_I2C_READY");
                    on = !(q && *q == '0');
                }
                if (on) p[0] = 0x03;
            }
            /* The one-byte `00` poll: which node wants servicing. See
             * nb_next_node() - answering this is what makes the playfield a
             * live scan instead of a single snapshot. */
            if (nb_req_len == 1 && nb_req[0] == 0x00 && n >= 1 &&
                sw_scan_enabled()) {
                unsigned want = nb_next_node();
                p[0] = (unsigned char)want;
                {
                    static int budget = 40;
                    static unsigned polls, nonzero;
                    polls++;
                    if (want) nonzero++;
                    /* The two addresses below are Godzilla Pro 1.15.0's and
                     * this is only a diagnostic, so it is skipped entirely on
                     * any other title - Jaws faulted here, in a printf, for the
                     * third time in this file. a_sw_struct() is the test for
                     * "the configured addresses are this title's". */
                    if (budget > 0 && want && a_sw_struct()) {
                        /* Print the two things 0x1d7d88 is about to test for
                         * this node, so a poll that leads nowhere says why:
                         *   board[+4] bit 0  (0x7bad88 + node*0xe0 + 4)
                         *   the scan gate    (0x7a908c + 276 + node) */
                        char m[190];
                        unsigned flags = *(const unsigned *)(unsigned long)
                                         (0x7bad88u + want * 0xe0u + 4u);
                        unsigned gate = *(const unsigned char *)(unsigned long)
                                        (0x7a908cu + 276u + want);
                        budget--;
                        snprintf(m, sizeof m,
                                 "[nbsched] poll #%u -> node %u flags=0x%08x"
                                 " bit0=%u gate=%u (nonzero=%u)\n",
                                 polls, want, flags, flags & 1u, gate, nonzero);
                        logmsg(m);
                    }
                    if ((polls & 0x3ffu) == 0) {
                        char m[120];
                        snprintf(m, sizeof m,
                                 "[nbsched] %u polls, %u non-zero answers\n",
                                 polls, nonzero);
                        logmsg(m);
                    }
                }
            }
            nb_log("TX-reply", p, (int)n, 0);
            return (long)n;
        }

        /* ADDRESSED reply. Layout taken from the validator at 0x59dc40, and it
         * is NOT the shape this shim used to send:
         *
         *   [n-1]      STATUS. (status & 0x0c) != 0 makes the exchange FAIL
         *              (error 1 if bit 2 is set, else 2) and 0x59d824 return 0.
         *   [0..n-2]   must sum to 0 mod 256, so [n-2] is the checksum.
         *   [0..n-3]   the payload the caller actually receives.
         *
         * The old code put the checksum in the LAST byte, so every single
         * exchange was graded as status 0x7f -> bits 2 and 3 both set -> error.
         * That is why no board ever left "Not Initialized", and why raising
         * PAD_NB_FILL only moved it to "Invalid": both replies failed, they
         * just failed with different garbage. Note this failure is invisible in
         * the ExchangeData counter - that one only counts short reads, and the
         * shim always returns the full count. */
        if (n < 2) { nb_log("TX-reply", p, (int)n, 0); return (long)n; }
        {
            int plen = (int)n - 2;
            int fill = nb_fill();
            if (fill >= 0)
                for (i = 0; i < (unsigned long)plen; i++) p[i] = (unsigned char)fill;
            /* PAD_NB_CFILL=<cmd>:<hh>[,<cmd>:<hh>...] - fill ONE command's
             * reply payload. PAD_NB_FILL is whole-bus and corrupts the identity
             * exchange, which un-registers every board and buries the thing you
             * were trying to measure. Per-command is how you ask "does anything
             * downstream care about THIS reply?" without disturbing the rest. */
            {
                static char *spec = (char *)-1;
                if (spec == (char *)-1) spec = getenv("PAD_NB_CFILL");
                if (spec && *spec && nb_req_len > 2) {
                    unsigned char cmd = nb_req[2];
                    char *q = spec;
                    while (*q) {
                        unsigned c = 0, v = 0;
                        while (ishex(*q)) c = c * 16 + hexval(*q++);
                        if (*q == ':') q++;
                        while (ishex(*q)) v = v * 16 + hexval(*q++);
                        if (c == cmd)
                            for (i = 0; i < (unsigned long)plen; i++)
                                p[i] = (unsigned char)v;
                        while (*q && *q != ',') q++;
                        while (*q == ',') q++;
                    }
                }
            }
            /* PAD_NB_RT=1 - fill the RUNTIME INFO block (f9 00, f9 01, fc) with
             * a recognisable pattern instead of zeros. This is the direct test
             * of "is the zero-filled runtime info what keeps the boards on
             * Runtime Info?", because 0x5a2b88 parses these 32 bytes into
             * board[+40..87]: a serial LE32 at buf[8..11] that it sprintf()s as
             * "%09d" and splits into "ddd-dddd-dd", an LE32 at buf[0..3], four
             * version bytes at buf[4..7], and more. Non-zero here must show up
             * in the record, so the record is the proof the fill landed. */
            if (nb_req_len > 2 && (nb_req[2] == 0xf9 || nb_req[2] == 0xfc) &&
                getenv("PAD_NB_RT") && plen > 0) {
                for (i = 0; i < (unsigned long)plen; i++)
                    p[i] = (unsigned char)(0x41 + i);
            }
            /* PAD_NB_SW=<node>:<hex32>[,...] - the SWITCH INPUT WORD of the
             * `ff` probe. node 0 means every node.
             *
             * 0x5a43d0 reads an 8-byte reply and hands the caller two LE32s:
             *     word A = bytes 0..3, the board's FAULT/STATUS word. The
             *              service loop at 0x1d82a0 tests 0x8010211f, 0x200,
             *              0x400, 0x68000, 0x00010080 in it - filling it is
             *              what fabricated "Check Node Board N : Overcurrent
             *              Protection" on screen.
             *     word B = bytes 4..7, the INPUT bits. 0x5a43d0 also sets bit
             *              31 of B itself when A differs from the previous
             *              poll, so bit 31 is not ours to use.
             * Filling only word B gives switch input with no fabricated faults,
             * which is the difference between a usable playfield and a screen
             * full of node board alerts. */
            if (nb_req_len > 2 && nb_req[2] == 0xff && plen >= 8) {
                static char *spec = (char *)-1;
                unsigned nid = (unsigned)(nb_req[0] & 0x3f);
                if (spec == (char *)-1) spec = getenv("PAD_NB_SW");
                /* PAD_NB_SWA=<hex32> - word A, bytes 0..3.
                 *
                 * 0x5a43d0 compares A against a per-node previous value at
                 * 0x841a08+900+(node&31)*4 and sets bit 31 of B on a
                 * difference - but it then stores ZERO back, not A. So the
                 * previous value is always 0, and with A also 0 the difference
                 * is never seen and the "input changed" flag never fires. A
                 * non-zero A is therefore a precondition for the game looking
                 * at the input word at all. Bits 5 and 6 are outside the fault
                 * mask 0x8078279f, so 0x40 raises the flag without inventing
                 * an overcurrent. */
                {
                    static char *aspec = (char *)-1;
                    unsigned a = 0;
                    if (aspec == (char *)-1) aspec = getenv("PAD_NB_SWA");
                    if (swwalk_on()) a = 0x40;
                    else if (aspec) { char *q = aspec;
                                      while (ishex(*q)) a = a * 16 + hexval(*q++); }
                    if (a) {
                        p[0] = (unsigned char)a;
                        p[1] = (unsigned char)(a >> 8);
                        p[2] = (unsigned char)(a >> 16);
                        p[3] = (unsigned char)(a >> 24);
                    }
                }
                if (swwalk_on()) {
                    unsigned v = swwalk_word(nid);
                    p[4] = (unsigned char)v;
                    p[5] = (unsigned char)(v >> 8);
                    p[6] = (unsigned char)(v >> 16);
                    p[7] = (unsigned char)(v >> 24);
                } else if (spec && *spec) {
                    char *q = spec;
                    while (*q) {
                        unsigned node = 0, v = 0;
                        while (*q >= '0' && *q <= '9') node = node * 10 + (*q++ - '0');
                        if (*q == ':') q++;
                        while (ishex(*q)) v = v * 16 + hexval(*q++);
                        if (node == 0 || node == nid) {
                            p[4] = (unsigned char)v;
                            p[5] = (unsigned char)(v >> 8);
                            p[6] = (unsigned char)(v >> 16);
                            p[7] = (unsigned char)(v >> 24);
                        }
                        while (*q && *q != ',') q++;
                        while (*q == ',') q++;
                    }
                }
            }
            /* ---- VILLAIN VISION 0x90 STATUS (item 83) -----------------
             * The lcdnode's cmd f2 selector 0x90 wants a 12-byte payload.
             * The game's poll loop (0x37e5ec, 60 Hz) stores it verbatim as
             * three u32s in the display object (+4/+8/+12).
             *
             * ★ THE CONTENT IS INERT, and this comment is the correction
             * of two claims I shipped before the RE (10-agent pass,
             * 2026-08-25, verified). (1) get_status (0x37e6d4) is the ONLY
             * reader of +4/+8/+12 and it is DEAD CODE - its address occurs
             * zero times in the 7.4 MB image (no bl, no fn-ptr table, no
             * literal). Nothing runtime consumes these words. (2) The 250
             * ms "re-send" is NOT caused by a missing reply and this echo
             * does NOT stop it: measured live WITH the echo active, every
             * attract clip is still commanded twice 250 ms apart. It is the
             * game's own double-issue, and the play command's pending bit
             * is cleared by the SEND succeeding (0x37e484/0x37e504), not by
             * any reply. So answering 0x90 changes nothing the game does.
             *
             * WHY ANSWER IT AT ALL, then: a real board replies, and a
             * correct-LENGTH 12-byte reply is never worse than a short read
             * (which an addressed node uses to mean "absent"). node 24
             * stays present with no fault (nbsched flags 0x0 all run). The
             * word0=asset content below is HUMAN-FACING telemetry only - it
             * makes a raw bus dump readable - not something the game reads.
             *   PAD_LCD_R=<24 hex chars>  force an exact 12-byte payload
             *   PAD_LCD_R=0               all-zero reply (same game effect)
             * Nothing here can revive the villain-TV renderer: those pixels
             * are a SECOND EGL display the binary hard-disables (padlcd.h). */
            if (nb_req_len > 3 && nb_req[2] == 0xf2 && nb_req[3] == 0x90 &&
                lcd_node() && (unsigned)(nb_req[0] & 0x3f) == lcd_node() &&
                plen >= 12) {
                static char *spec = (char *)-1;
                if (spec == (char *)-1) spec = getenv("PAD_LCD_R");
                if (spec && *spec) {
                    char *q = spec;
                    for (i = 0; i < 12 && ishex(q[0]) && ishex(q[1]); i++) {
                        p[i] = (unsigned char)(hexval(q[0]) * 16 + hexval(q[1]));
                        q += 2;
                    }                       /* "0" = fewer than 2 digits: zeros */
                } else if (lcd_shm && lcd_shm->asset) {
                    p[0] = (unsigned char)lcd_shm->asset;
                    p[1] = (unsigned char)(lcd_shm->asset >> 8);
                    p[2] = (unsigned char)(lcd_shm->asset >> 16);
                    p[3] = (unsigned char)(lcd_shm->asset >> 24);
                }
            }
            /* ---- COMMAND 0x11: THE SWITCH SCAN ------------------------
             * 0x59ef60 builds { 0x80|node, 01, 11, 0a } and reads 10 payload
             * bytes: [0..7] switch bits, [8..9] a u16 the caller may want.
             * When request[1] is 2 the payload is XORed with a rotating key
             * and THE KEY IS REQUEST[3] - read it off the wire rather than
             * hunting [0x841a08 + node*12 + 15] and [0x841e24] in memory.
             *
             *     out[c] = reply[c] ^ rol8(key, c)
             *
             * so we encode with the same rotation. key 0 is the identity, so
             * the plain case needs no special path. */
            if (nb_req_len > 2 && nb_req[2] == 0x11 && plen >= 8 &&
                sw_scan_enabled()) {
                unsigned nid = (unsigned)(nb_req[0] & 0x3f);
                unsigned char bits[8];
                if (nid < 64) nb_news[nid] = 0;    /* item 52: news delivered */
                if (sw_scan_bytes(nid, bits)) {
                    /* Same trace as [cabchg], for the node bus half. A burst of
                     * 27 playfield switches was seen flipping together at 35 s
                     * with nothing injected, and the only way to tell "the shim
                     * sent a different word" from "the game mangled a good one"
                     * is to log what was sent. */
                    {
                        static unsigned char last[64][8];
                        static unsigned char seen[64];
                        static int nbudget = 120;
                        unsigned q, diff = 0;
                        if (nid < 64) {
                            if (!seen[nid]) diff = 1;
                            for (q = 0; q < 8; q++)
                                if (last[nid][q] != bits[q]) diff = 1;
                            if (diff && nbudget > 0) {
                                char m4[220];
                                nbudget--;
                                snprintf(m4, sizeof m4,
                                         "[nbchg] %lu ms node=%u %02x%02x%02x%02x"
                                         "%02x%02x%02x%02x (was %02x%02x%02x%02x"
                                         "%02x%02x%02x%02x)\n", pad_ms(), nid,
                                         bits[0], bits[1], bits[2], bits[3],
                                         bits[4], bits[5], bits[6], bits[7],
                                         last[nid][0], last[nid][1], last[nid][2],
                                         last[nid][3], last[nid][4], last[nid][5],
                                         last[nid][6], last[nid][7]);
                                logmsg(m4);
                            }
                            for (q = 0; q < 8; q++) last[nid][q] = bits[q];
                            seen[nid] = 1;
                        }
                    }
                    /* THE KEY, AND THE BUG THAT COST THE SWITCH LATCH.
                     *
                     * The earlier rule - "nb_req[1]==2 means keyed with
                     * nb_req[3]" - reads the frame wrong. nb_req[1] is not a
                     * mode flag, it is a LENGTH: one plus the number of payload
                     * bytes, so the trailing checksum is included in the count.
                     * Every frame on this bus obeys it, and bytes 0..1+n always
                     * sum to zero mod 256:
                     *
                     *   81 02 11 6c 0c   n=2  payload {11} + ck 6c, reply 12
                     *   81 03 f9 00 83 12  n=3 payload {f9,00} + ck 83, reply 18
                     *
                     * So the PLAIN 0x11 request is n=2 and its nb_req[3] is the
                     * CHECKSUM. Treating it as a key made the shim scramble
                     * every reply with rol8(checksum, c) while 0x59ef60 decoded
                     * with a key of zero (its r4 is the per-node obfuscation
                     * flag at [0x841a08 + node*12 + 15], which is 0 here, and it
                     * falls straight through to the XOR loop still holding 0).
                     * The game therefore received sent ^ rol8(ck, c): a fixed
                     * set of bits permanently INVERTED, different per node
                     * because the checksum is. That is the whole latch - node 8
                     * byte 3 mask 0x2b inverts bit 1, which is the Left Flipper
                     * Button, while node 9 byte 3 mask 0x23 leaves bit 4, the
                     * Right Spinner, alone. Measured both ways.
                     *
                     * The obfuscated form is n=3, and there the key really is
                     * nb_req[3] - the game writes it into the request itself at
                     * 0x59efcc, so it still never has to be hunted in memory. */
                    unsigned key = (nb_req_len > 4 && nb_req[1] == 3)
                                   ? nb_req[3] : 0u;
                    sw_prime(nid, bits);
                    for (i = 0; i < 8; i++) {
                        unsigned r = ((key << i) | (key >> ((8 - i) & 7))) & 0xff;
                        p[i] = (unsigned char)(bits[i] ^ r);
                    }
                    {
                        static int budget = 24;
                        if (budget > 0) {
                            char m[160];
                            budget--;
                            snprintf(m, sizeof m,
                                     "[swscan] node=%u key=0x%02x bits="
                                     "%02x%02x%02x%02x%02x%02x%02x%02x\n",
                                     nid, key, bits[0], bits[1], bits[2],
                                     bits[3], bits[4], bits[5], bits[6],
                                     bits[7]);
                            logmsg(m);
                        }
                    }
                }
            }
            if (nb_req_len > 2 && nb_req[2] == 0xfe && plen >= 11) {
                unsigned nid = (unsigned)(nb_req[0] & 0x3f);
                const struct nb_ident *ident = nb_ident_for(nid);
                unsigned part = nb_env_hex("PAD_NB_PART",
                                           ident ? ident->part : NB_PART_DEFAULT);
                unsigned hwid = nb_env_hex("PAD_NB_HWID", NB_HWID_DEFAULT);
                unsigned fwd  = nb_ident_fw(ident);
                unsigned vard = ident ? ident->variant : 0;
                unsigned fw, var;
                /* THE GAME'S OWN DECRYPTED IMAGE OUTRANKS the derived table:
                 * a variant nbdir could only guess (the hex bodies are
                 * encrypted) is exactly what put godzilla_le through ~80 s
                 * of failed RUNTIME UPDATEs on node 10 every boot - see
                 * nb_hexreg_answer(). Env overrides still win below, so a
                 * sweep can bypass both layers at once. */
                nb_hexreg_answer(nid, ident ? ident->tcrc : 0, part,
                                 &vard, &fwd);
                fw  = nb_env_hex("PAD_NB_FW", fwd);
                var = nb_env_hex("PAD_NB_VARIANT", vard);
                /* ★ ITEM 51's INSTRUMENT: say what each node claims, once.
                 * A re-ask-count "refusal detector" lived here for one run
                 * and is deliberately GONE: ~200 fe per node in five
                 * minutes is the game's NORMAL periodic identity poll - it
                 * fired for boards the update walk plainly accepted, so the
                 * count cannot distinguish refusal at all. The screen (the
                 * update overlay naming a board) and the [nbid] claim lines
                 * are the honest oracle pair. */
                {
                    static unsigned long long fe_said;
                    if (!(fe_said & (1ull << nid))) {
                        char m[160];
                        fe_said |= 1ull << nid;
                        snprintf(m, sizeof m, "[nbid] node %u claims "
                                 "part=0x%08x variant=0x%02x fw=%u.%u.%u (%s)\n",
                                 nid, part, var, (fw >> 16) & 0xff,
                                 (fw >> 8) & 0xff, fw & 0xff,
                                 (nid < 64 && nb_fident_have[nid]) ? "derived"
                                 : ident ? "built-in" : "default");
                        logmsg(m);
                    }
                }
                p[0]  = 0;
                p[1]  = (unsigned char)(fw >> 16);
                p[2]  = (unsigned char)(fw >> 8);
                p[3]  = (unsigned char)fw;
                p[4]  = (unsigned char)part;
                p[5]  = (unsigned char)(part >> 8);
                p[6]  = (unsigned char)(part >> 16);
                p[7]  = (unsigned char)(part >> 24);
                p[8]  = (unsigned char)hwid;
                p[9]  = (unsigned char)(hwid >> 8);
                /* payload[10] is the board VARIANT byte, and 0x1d57f8 compares
                 * it against the variant the node's .hex image carries at flash
                 * address 0x1008 (decrypted). The test is
                 *     if (hex_variant != identity[10] && hex_variant != 0) fail
                 * so a non-zero variant in the image forces this to match.
                 * pinnode-*-1_35_0.hex carries 01, ws2812node 05. */
                p[10] = (unsigned char)var;
            }
            for (i = 0; i + 2 < n; i++) sum += p[i];
            p[n - 2] = (unsigned char)((0u - sum) & 0xff);
            p[n - 1] = 0;
        }
        nb_log("TX-reply", p, (int)n, 0);
        return (long)n;
    }
    {
        long r = real_read(fd, b, n);
        struct scenef *s = scene_find_fd(fd);
        static int budget = 60;
        if (s && r > 0) { s->bytes += (unsigned long)r; s->reads++; }
        if (budget-- > 0) {
            char m[160];
            snprintf(m, sizeof m, "[read] fd=%d n=%lu -> %ld%s\n",
                     fd, n, r, s ? "   <-- SCENE" : "");
            logmsg(m);
        }
        return r;
    }
}

long shim_write(int fd, const void *b, unsigned long n) __asm__("write");
long shim_write(int fd, const void *b, unsigned long n)
{
    io_init();
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'I') {
        struct i2c_msg m;
        m.addr = (unsigned short)slot_addr[cur_slot[fd]];
        m.flags = 0; m.len = (unsigned short)n; m.buf = (unsigned char *)b;
        do_msg(cur_slot[fd], &m);
        return (long)n;
    }
    if (fd >= 0 && fd < MAXFD && faked[fd] == 'T') {
        const unsigned char *p = b;
        unsigned long i, keep = n < sizeof nb_req ? n : sizeof nb_req;
        for (i = 0; i < keep; i++) nb_req[i] = p[i];
        nb_req_len = (int)keep;
        /* ITEM 17: the `08 01 01` broadcast rides the reset that puts the
         * two i2c MCUs (slaves 0x0a/0x2a) back into their power-on state,
         * where register 0x24 presents 0x0111 - the value the init waiter
         * at 0x1fa9c8 polls for. Re-arm the model here so a mid-run re-init
         * completes the same way the boot one does. See i2c_ready_arm(). */
        if (nb_req_len == 3 && nb_req[0] == 0x08 && !(nb_req[0] & 0x80))
            i2c_ready_arm();
        {
            static int rabudget = 12;
            unsigned long ra = (unsigned long)__builtin_return_address(0);
            if (rabudget-- > 0) {
                char m[120];
                snprintf(m, sizeof m, "[nb] write() called from 0x%lx len=%lu\n", ra, n);
                logmsg(m);
            }
        }
        /* One unbudgeted line the first time each command byte is seen, so the
         * command set survives however low the [nb] budget is set.
         *
         * Do NOT try to name the caller from here. __builtin_return_address(0)
         * is always inside 0x59d824 (every command funnels through the same
         * exchange), and levels 1..3 all return 0 - the game and the shim are
         * both built without frame pointers, so there is no chain to walk.
         * Tried and useless; use a static search for the command byte instead,
         * remembering it is built with mvn (0xf9 is `mvn rX, #6`). */
        {
            static unsigned char cmdseen[256];
            unsigned char cmd = nb_req_len > 2 && (nb_req[0] & 0x80) ? nb_req[2] : nb_req[0];
            if (!cmdseen[cmd]) {
                char m[HEXBUF + 128], h[HEXBUF];
                cmdseen[cmd] = 1;
                hex64(h, nb_req, nb_req_len);
                snprintf(m, sizeof m, "[nbcmd] %02x first frame %s\n", cmd, h);
                logmsg(m);
            }
        }
        /* ---- THE COMMAND CENSUS (PAD_CMD_CENSUS=1) --------------------
         * Item 79: batman's attract never trips the light-show announcer,
         * because its show speaks an older command dialect the lamp-class
         * set does not count - and nothing had measured WHICH commands the
         * show is made of, at what rate. PAD_NB_LOG is the wrong instrument
         * (quadruples the boot and buries the answer - see the coil probe's
         * header below); this prints ONE line per 10 s window carrying that
         * window's per-command TX counts, phase-attributable from the
         * surrounding log, and costs nothing while the env is unset. */
        {
            static int census = -1;
            static unsigned long win_start;
            static unsigned cmix[256];
            if (census < 0)
                census = getenv("PAD_CMD_CENSUS") ? 1 : 0;
            if (census) {
                unsigned char c2 = nb_req_len > 2 && (nb_req[0] & 0x80)
                                   ? nb_req[2] : nb_req[0];
                unsigned long now = pad_ms();
                int c, k;
                cmix[c2]++;
                if (!win_start) win_start = now;
                if (now - win_start >= 10000) {
                    char m[640];
                    k = snprintf(m, sizeof m, "[cmdmix] %lu ms window %lu ms:",
                                 now, now - win_start);
                    for (c = 0; c < 256; c++)
                        if (cmix[c] && k < (int)sizeof m - 16)
                            k += snprintf(m + k, sizeof m - k, " %02x=%u",
                                          c, cmix[c]);
                    snprintf(m + k, sizeof m - k, "\n");
                    logmsg(m);
                    for (c = 0; c < 256; c++)   /* no memset: string.h is */
                        cmix[c] = 0;            /* not included here      */
                    win_start = now;
                }
            }
        }
        nb_log("TX", nb_req, nb_req_len, 0);
        sw_find_maybe();
        led_publish(nb_req, nb_req_len);
        coil_publish(nb_req, nb_req_len);
        lcd_publish(nb_req, nb_req_len);        /* item 83: VILLAIN VISION */
        coil_probe(nb_req, nb_req_len);
        nb_trace();
        nb_maybe_poke();
        nb_watch_flags();
        nb_force_status();      /* item 52: readiness-gate test (per TX) */
        /* item 52: what is actually on the glass. Both install once and then
         * cost a load and a branch; the hook does the reporting from then on.
         * Here rather than in a constructor because the node bus is the first
         * thing this file is certain the game has reached. */
        screen_install();
        country_trace();
        pass_hook_arm();
        country_gate_bypass();
        nb_maybe_dump();
        alert_maybe_dump();
        val_maybe_dump();
        sw_maybe_dump();
        return (long)n;
    }
    return real_write(fd, b, n);
}
