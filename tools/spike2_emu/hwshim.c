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

extern void *dlsym(void *, const char *);
#define RTLD_NEXT ((void *)-1L)
extern long write(int, const void *, unsigned long);
extern char *strstr(const char *, const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern char *getenv(const char *);

#define MAXFD 4096
static char faked[MAXFD];

static int (*real_open)(const char *, int, int);
static int (*real_open64)(const char *, int, int);
static int (*real_ioctl)(int, unsigned long, void *);

static unsigned long pad_ms(void);       /* defined with the periodic dumps */

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
static void openlog(const char *path, int ok, unsigned long from)
{
    static int mode = -1;
    char b[300];
    if (mode < 0) {
        char *p = getenv("PAD_OPEN_LOG");
        mode = (p && p[0] >= '0' && p[0] <= '9') ? p[0] - '0' : 0;
    }
    if (!mode) return;
    if (ok && mode < 2 && path && strstr(path, "/assets/")) return;
    snprintf(b, sizeof b, "[open] %-6s %s  (from 0x%lx)\n",
             ok ? "ok" : "FAIL", path ? path : "(null)", from);
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
    if (!real_fopen) real_fopen = dlsym(RTLD_NEXT, "fopen");
    f = real_fopen(path, mode);
    openlog(path, f != 0, (unsigned long)__builtin_return_address(0));
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
    if (!real_fopen64) real_fopen64 = dlsym(RTLD_NEXT, "fopen64");
    f = real_fopen64(path, mode);
    openlog(path, f != 0, (unsigned long)__builtin_return_address(0));
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
            if (us == 5000 && (ra == 0x59eb94ul || armed)) {
                armed = (ra == 0x59eb94ul);
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
            if (us == 2000000 && ra == 0x1d6ec4ul && rst_us < (int)us)
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
    init();
    va_start(ap, flags); m = va_arg(ap, int); va_end(ap);
    fd = real_open(path, flags, m);
    openlog(path, fd >= 0, (unsigned long)__builtin_return_address(0));
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
    init();
    va_start(ap, flags); m = va_arg(ap, int); va_end(ap);
    fd = real_open64 ? real_open64(path, flags, m) : real_open(path, flags, m);
    openlog(path, fd >= 0, (unsigned long)__builtin_return_address(0));
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
    snprintf(b, sizeof b, "[thread] #%d ENTERED body=0x%lx gate[0x7acb54]=%d\n",
             s->id, (unsigned long)s->fn, *(unsigned char *)0x7acb54);
    logmsg(b);
    /* The audio streaming worker reads 0x7acb54 once and spins on the register,
     * so starting while the byte is 1 wedges it permanently even though the
     * byte is 0 seconds later. Do the re-reading wait the code meant to do,
     * on its own thread, before handing control over. */
    if (ungate_enabled() && (unsigned long)s->fn == 0x459604) {
        static int (*real_usleep)(unsigned long);
        int waited = 0;
        if (!real_usleep) real_usleep = dlsym(RTLD_NEXT, "usleep");
        while (*(volatile unsigned char *)0x7acb54 && waited < 5000) {
            if (real_usleep) real_usleep(1000);
            waited++;
        }
        snprintf(b, sizeof b,
                 "[thread] #%d waited %d ms for gate; gate now %d\n",
                 s->id, waited, *(volatile unsigned char *)0x7acb54);
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
 */
extern void _exit(int);
extern char *getenv(const char *);

/* Off by default: with the game's own handler left in place the faulting
 * thread spins but the others keep running, which is what you want when
 * watching whether a later stage recovers. */
static int getenv_pad(void)
{
    char *p = getenv("PAD_SEGV_REPORT");
    return p && p[0] == '1';
}

static void segv_handler(int sig, void *info, void *ucv)
{
    unsigned long *uc = ucv;
    char b[200];
    (void)sig; (void)info;
    if (!uc) { logmsg("[segv] no context\n"); _exit(99); }

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
        int fd = real_open("/proc/self/maps", 0 /*O_RDONLY*/, 0);
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
                    snprintf(b, sizeof b, "[segv] map %s%s\n", line,
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

    /* The scene loader thread (0x447440) does no work at all unless the gate
     * byte at 0x7e1a10 is set, and the boot step waits on 0x7e1974. The shim
     * shares the guest address space, so both can just be read here. */
    {
        unsigned char *gate  = (unsigned char *)0x7e1a10;
        unsigned char *ready = (unsigned char *)0x7e1974;
        unsigned char *run   = (unsigned char *)0x794af5;
        snprintf(b, sizeof b,
                 "[segv] loader_gate[0x7e1a10]=%d boot_ready[0x7e1974]=%d "
                 "thread_run[0x794af5]=%d scene_opens=%d\n",
                 *gate, *ready, *run, scene_opens);
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
        unsigned long *tbl = (unsigned long *)0x7e4d48;
        int ev;
        for (ev = 93; ev <= 94; ev++) {
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
                    unsigned char gate = *(unsigned char *)0x7acb54;
                    snprintf(b, sizeof b,
                             "[audio] worker spin gate [0x7acb54] = %d "
                             "(non-zero at thread start = worker wedged)\n", gate);
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

static int (*real_sigaction)(int, const void *, void *);

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
    return real_sigaction(sig, act, old);
}

void *shim_signal(int sig, void *h) __asm__("signal");
void *shim_signal(int sig, void *h)
{
    static void *(*real_signal)(int, void *);
    if (!real_signal) real_signal = dlsym(RTLD_NEXT, "signal");
    if (sig == 11) { shim_sigaction(11, 0, 0); return 0; }
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
static int i2c_log_budget = 120;

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
static int nv_loaded;

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
    if (nv_loaded) return;
    nv_loaded = 1;
    init(); io_init();
    fd = real_open(NV_PATH, 0 /* O_RDONLY */, 0);
    if (fd < 0) { logmsg("[i2c] no saved NVRAM, starting blank\n"); return; }
    while (got < SLOTSIZE && (r = real_read(fd, store[0] + got, SLOTSIZE - got)) > 0)
        got += (unsigned long)r;
    real_close(fd);
    logmsg("[i2c] loaded saved NVRAM\n");
}

static void nv_save(void)
{
    int fd;
    io_init();
    fd = real_open(NV_PATH, 0x241 /* O_WRONLY|O_CREAT|O_TRUNC */, 0644);
    if (fd < 0) return;
    real_write(fd, store[0], SLOTSIZE);
    real_close(fd);
}

static void do_msg(int slot, struct i2c_msg *m)
{
    char line[256], h[40];
    unsigned int p = cur_ptr[slot];
    if (m->flags & I2C_M_RD) {
        unsigned int i;
        for (i = 0; i < m->len; i++) m->buf[i] = store[slot][(p + i) % SLOTSIZE];
        cur_ptr[slot] = (p + m->len) % SLOTSIZE;
        if (i2c_log_budget-- > 0) {
            hex(h, m->buf, m->len);
            snprintf(line, sizeof line, "[i2c] addr=0x%02x READ  @0x%04x len=%u %s\n",
                     m->addr, p, m->len, h);
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
            snprintf(line, sizeof line, "[i2c] addr=0x%02x WRITE @0x%04x len=%u %s\n",
                     m->addr, p, m->len, h);
            logmsg(line);
        }
    }
}

/* Defined with the rest of the switch model, forward-declared because the
 * CABINET switches do not come over the node bus at all - they arrive as the
 * RX half of an SPI transfer, and that is handled here in ioctl(). */
static int sw_scan_bytes(unsigned nid, unsigned char out[8]);
static int sw_scan_enabled(void);
static void sw_prime(unsigned nid, const unsigned char bits[8]);
static unsigned long pad_ms(void);
static void sw_tap(void);
static void sw_changes(void);
static void sw_pend_trace(void);
static unsigned sw_shm_gen(void);
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
};
#define PADSW_MAGIC 0x53444150u

static const volatile struct padsw_shm *sw_shm;

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
            sw_tap(); sw_changes(); sw_pend_trace();
            /* Driven from HERE as well as the node bus write path, for the same
             * reason the tap schedule is: node bus traffic dries up once the
             * game settles into a menu, and this loop never stops. */
            audio_maybe_dump();
        }
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
            have = sw_scan_bytes(0, bits);
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
        if (have) {
            sw_prime(0, bits);
            for (k = 0; k < msgs; k++) {
                const unsigned char *m = (const unsigned char *)arg + k * 32;
                unsigned rx  = *(const unsigned *)(m + 8);
                unsigned len = *(const unsigned *)(m + 16);
                unsigned j;
                if (!rx || !len) continue;
                if (len > 8) len = 8;
                for (j = 0; j < len; j++)
                    ((unsigned char *)(unsigned long)rx)[j] = bits[j];
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
 * node4's two images report a version that does not look like 1.35.0 even
 * after decryption (LPC1124_303 -> 124.107.0, LPC812 -> 146.13.128). That is
 * reproduced here rather than "corrected", because what matters is matching
 * what 0x5a8644 actually reads. Worth revisiting if node 4 misbehaves. */
struct nb_ident { unsigned char id; unsigned part; unsigned char variant; unsigned fw; };
static const struct nb_ident nb_idents[] = {
    /* id   part id      variant  fw (maj<<16|min<<8|patch)   type / firmware  */
    {  1, 0x00020023u, 0x01, 0x012300u },  /* pinnode    LPC1112_101  1.35.0 */
    {  8, 0x00020023u, 0x01, 0x012300u },
    {  9, 0x00020023u, 0x01, 0x012300u },
    {  2, 0x2c40102bu, 0x05, 0x012300u },  /* ws2812node LPC1313      1.35.0 */
    {  7, 0x2c40102bu, 0x05, 0x012300u },
    { 12, 0x2c40102bu, 0x05, 0x012300u },
    { 14, 0x2c40102bu, 0x05, 0x012300u },
    {  4, 0x00140040u, 0x98, 0x7c6b00u },  /* node4      LPC1124_303  as read */
};

/* PAD_NB_PART / PAD_NB_VARIANT / PAD_NB_FW still override, globally, so the
 * table can be bypassed for a sweep without editing code. */
static const struct nb_ident *nb_ident_for(unsigned id)
{
    unsigned i;
    for (i = 0; i < sizeof nb_idents / sizeof nb_idents[0]; i++)
        if (nb_idents[i].id == id) return &nb_idents[i];
    return 0;
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
#define NB_OBJS   0x7bad88u
#define NB_OBJ_SZ 0xe0u

static const char *nb_status_name(unsigned s)
{
    static const char *n[12] = {
        "No Errors", "Not Responding", "Not Registered", "Collision",
        "Not Initialized", "Version Mismatch", "Hex Image Version not Found",
        "Checksum", "Runtime Info", "Boot", "Ok", "Unused"
    };
    return s < 12 ? n[s] : "?";
}

static void nb_dump_objs(void)
{
    char line[400];
    unsigned id;
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
    if (!on) return;
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
#define NB_ALERT_GATE 0x706464u

static void nb_watch_flags(void)
{
    static int on = -1;
    static unsigned last[32];
    static int primed;
    static unsigned last_gate = 0xffffffffu;
    unsigned id, gate;
    char line[200];

    if (on == -1) { char *p = getenv("PAD_NB_WATCH"); on = p && p[0] == '1'; }
    if (!on) return;

    gate = *(const unsigned *)(unsigned long)NB_ALERT_GATE;
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
#define ALERT_HEAD  0x7ac834u   /* the list head                            */
#define MSG_COUNT   0x5ec0c8u   /* u32, 3949                                */
#define MSG_REMAP   0x7b9654u   /* u32 -> u16[count]: msgid -> table index   */
#define MSG_PTRS    0x744c60u   /* u32[count]: index -> const char *[5] row  */
#define MSG_LANG    0x708330u   /* u32, current language slot within the row */

/* msgid -> text, done by hand rather than by calling 0x34a764, because that
 * function's out-of-range path calls the game's error reporter. This is a
 * pure read: the same three indirections, with every pointer bounds-checked. */
static const char *msg_text(unsigned msgid)
{
    unsigned count = *(const unsigned *)(unsigned long)MSG_COUNT;
    unsigned rt    = *(const unsigned *)(unsigned long)MSG_REMAP;
    unsigned lang  = *(const unsigned *)(unsigned long)MSG_LANG;
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
    unsigned n = *(const unsigned *)(unsigned long)ALERT_HEAD;
    int guard = 0, probe = alert_probe_on(), total = 0;

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
 * ------------------------------------------------------------------------ */
#define VAL_MOD  0x7b7b70u      /* module globals                            */
#define VAL_V    0x7b7c30u      /* MOD+0xc0, the state object                */
#define VAL_ST   0x7b7c35u      /* MOD+0xc5, the state-machine state         */
#define VAL_CTX  0x7b7c38u      /* MOD+0xc8, the worker context              */
#define VAL_AUD  0x7b9308u      /* the #4 term, inside the audio state block */

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
#define SW_STRUCT 0x7a958cu     /* +0 entry array, +4 raw state bytes        */
#define SW_COUNT  0x7e43d8u
#define DEV_TABLE 0x7446a4u     /* stride 40, 1-based                        */
#define DEV_COUNT 0x5ec030u

/* 0x485918 in miniature: a message row is up to five const char*, one per
 * language, falling back to slot 0. */
static const char *msg_row(unsigned row)
{
    unsigned lang = *(const unsigned *)(unsigned long)MSG_LANG;
    unsigned s;
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
    unsigned st = *(const unsigned *)(unsigned long)SW_STRUCT;
    unsigned raw = *(const unsigned *)(unsigned long)(SW_STRUCT + 4);
    unsigned n = *(const unsigned *)(unsigned long)SW_COUNT;
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

static void sw_dump(void)
{
    char line[300];
    unsigned st  = *(const unsigned *)(unsigned long)SW_STRUCT;
    unsigned raw = *(const unsigned *)(unsigned long)(SW_STRUCT + 4);
    unsigned n   = *(const unsigned *)(unsigned long)SW_COUNT;
    unsigned dn  = *(const unsigned *)(unsigned long)DEV_COUNT;
    unsigned id;

    snprintf(line, sizeof line,
             "[sw] --- switches: count=%u entry[]=0x%08x raw[]=0x%08x ---\n",
             n, st, raw);
    logmsg(line);
    if (sw_ok(st) && sw_ok(raw) && n <= 4096) {
        for (id = 1; id < n; id++) {
            const unsigned char *e =
                (const unsigned char *)(unsigned long)(st + id * 32);
            unsigned cfg = *(const unsigned *)(e + 8);
            unsigned nameobj = *(const unsigned *)(e + 12);
            const char *nm = 0;
            unsigned num = 0, fl = 0;
            if (sw_ok(cfg)) {
                num = *(const unsigned short *)(unsigned long)(cfg + 20);
                fl  = *(const unsigned short *)(unsigned long)(cfg + 28);
            }
            if (sw_ok(nameobj))
                nm = msg_row(*(const unsigned *)(unsigned long)(nameobj + 16));
            snprintf(line, sizeof line,
                     "[sw] id=%-3u num=%-4u raw=%u logical=%u flags=0x%04x %s\n",
                     id, num, ((const unsigned char *)(unsigned long)raw)[id],
                     e[24], fl, nm ? nm : "?");
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

    st = *(const unsigned *)(unsigned long)SW_STRUCT;
    cnt = *(const unsigned *)(unsigned long)SW_COUNT;
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
 * pressed. Bit per id, 128 ids is more than the 88 this machine has. */
static unsigned char sw_active[128];
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

static void sw_hold_init(void)
{
    static int done;
    char *p;
    unsigned i;
    if (done) return;
    done = 1;
    p = getenv("PAD_SW_REST");
    sw_rest_on = !(p && *p == '0');
    if (!(p && *p == '0') && !getenv("PAD_SW_SHM")) {
        for (i = 0; i < sizeof sw_rest_ids; i++)
            sw_active[sw_rest_ids[i]] = 1;
        logmsg("[swrest] machine at rest: coin door shut, 6 balls in trough\n");
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
    if (!on || nb_nnodes < 0) return;
    for (id = 1; id < 32; id++) {
        const unsigned char *o =
            (const unsigned char *)(unsigned long)(NB_OBJS + id * NB_OBJ_SZ);
        if (!*(const unsigned *)(o + 12)) continue;            /* slot unused */
        if (!*(const unsigned short *)(o + 144)) continue;     /* not fitted */
        nb_nodes_add(o[0]);
    }
}

static void nb_nodes_init(void)
{
    unsigned st = *(const unsigned *)(unsigned long)SW_STRUCT;
    unsigned n  = *(const unsigned *)(unsigned long)SW_COUNT;
    unsigned id;
    int i;
    if (nb_nnodes >= 0) return;
    if (!sw_ok(st) || n > 4096) return;          /* table not built yet */
    nb_nnodes = 0;
    for (id = 1; id < n && nb_nnodes < (int)sizeof nb_nodes; id++) {
        unsigned node = ((const unsigned char *)(unsigned long)(st + id * 32))[20];
        if (!node) continue;                     /* 0 is the cabinet, over SPI */
        for (i = 0; i < nb_nnodes; i++) if (nb_nodes[i] == node) break;
        if (i == nb_nnodes) nb_nodes[nb_nnodes++] = (unsigned char)node;
    }
    {
        char b[160];
        int k = snprintf(b, sizeof b, "[nbsched] playfield nodes:");
        for (i = 0; i < nb_nnodes; i++)
            k += snprintf(b + k, sizeof b - (unsigned)k, " %u", nb_nodes[i]);
        snprintf(b + k, sizeof b - (unsigned)k, "\n");
        logmsg(b);
    }
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
    if (idx >= nb_nnodes) { idx = 0; return 0; }
    return nb_nodes[idx++];
}

static void sw_prime(unsigned nid, const unsigned char bits[8])
{
    static unsigned char primed[64];
    unsigned char *rec;
    unsigned i;
    if (nid >= 64 || primed[nid]) return;
    if (!sw_ok(*(const unsigned *)(unsigned long)SW_STRUCT)) return;
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
    sw_shm = (const volatile struct padsw_shm *)m;
    {
        char b[160];
        snprintf(b, sizeof b, "[swshm] %s mapped at %p magic=0x%08x\n",
                 path, m, sw_shm->magic);
        logmsg(b);
    }
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

static unsigned sw_shm_gen(void)
{
    static unsigned last;
    unsigned g;
    if (!sw_shm || sw_shm->magic != PADSW_MAGIC) return 0;
    g = sw_shm->gen;
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

static int sw_shm_held(unsigned id)
{
    if (!sw_shm || sw_shm->magic != PADSW_MAGIC || id >= 256) return 0;
    return sw_shm->held[id] != 0;
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
    if (sw_shm_gen()) {
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
    for (i = 0; i < sizeof sw_rest_ids; i++)
        if (sw_rest_ids[i] == id) return 1;
    return 0;
}

static int sw_scan_bytes(unsigned nid, unsigned char out[8])
{
    unsigned st = *(const unsigned *)(unsigned long)SW_STRUCT;
    unsigned n  = *(const unsigned *)(unsigned long)SW_COUNT;
    unsigned id;
    int placed = 0;

    out[0] = out[1] = out[2] = out[3] = 0;
    out[4] = out[5] = out[6] = out[7] = 0;
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
        if ((id < sizeof sw_active && sw_active[id]) || sw_shm_held(id) ||
            (int)id == pad_tap_id || sw_rest_pending(id))
            level = !level;

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
    st  = *(const unsigned *)(unsigned long)SW_STRUCT;
    raw = *(const unsigned *)(unsigned long)(SW_STRUCT + 4);
    cnt = *(const unsigned *)(unsigned long)SW_COUNT;
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
    static unsigned long base;
    unsigned long t[2] = { 0, 0 };
    unsigned long ms;
    if (!cg) cg = dlsym(RTLD_NEXT, "clock_gettime");
    if (!cg) return 0;
    cg(1 /* CLOCK_MONOTONIC */, t);
    ms = t[0] * 1000ul + t[1] / 1000000ul;
    if (!base) base = ms;
    return ms - base;
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

static int aud_readable(unsigned long p)
{
    return p > 0x10000 && p < 0xb0000000;
}

static void audio_dump(void)
{
    char b[240];
    unsigned long pool;
    int n;

    snprintf(b, sizeof b,
             "[aud] --- %lu ms --- writei calls=%lu frames=%lu (%lu.%01lu s @ %u Hz "
             "x %u ch)  main played=%lu dropped=%lu  center=%lu  gate[0x7acb54]=%d"
             "  latency=%lu/%lu ms  fifo=%lu ms\n",
             pad_ms(), pad_pcm_calls, pad_pcm_frames,
             pad_pcm_rate ? pad_pcm_frames / pad_pcm_rate : 0,
             pad_pcm_rate ? (pad_pcm_frames * 10 / pad_pcm_rate) % 10 : 0,
             pad_pcm_rate, pad_pcm_channels,
             pad_pcm_played(), pad_pcm_drops(), pad_pcm_center(),
             *(unsigned char *)0x7acb54,
             pad_pcm_backlog_ms(), pad_pcm_buffer_ms(), pad_pcm_fifo_ms());
    logmsg(b);

    for (n = 0; n < 8; n++) {
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
                unsigned long q = *(unsigned long *)(node + 8);
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
    unsigned st = *(const unsigned *)(unsigned long)SW_STRUCT;
    unsigned n  = *(const unsigned *)(unsigned long)SW_COUNT;
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
    st  = *(const unsigned *)(unsigned long)SW_STRUCT;
    cnt = *(const unsigned *)(unsigned long)SW_COUNT;
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
    st  = *(const unsigned *)(unsigned long)SW_STRUCT;
    raw = *(const unsigned *)(unsigned long)(SW_STRUCT + 4);
    cnt = *(const unsigned *)(unsigned long)SW_COUNT;
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
    const unsigned char *m = (const unsigned char *)(unsigned long)VAL_MOD;
    unsigned v   = *(const unsigned *)(unsigned long)VAL_V;
    unsigned ctx = *(const unsigned *)(unsigned long)VAL_CTX;
    int i, k;

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
    const unsigned char *m = (const unsigned char *)(unsigned long)VAL_MOD;
    unsigned ctx = *(const unsigned *)(unsigned long)VAL_CTX;
    int i;
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

#define VAL_LO 0x249e00u
#define VAL_HI 0x24c2c0u

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
    nb_dump_boards();
    nb_dump_objs();
    nb_dump_hexlist();
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
};
#define PADLED_MAGIC 0x44454c50u

static struct padled_shm *led_shm;
static unsigned char led_known[16][96];      /* seen in the boot enumeration */

static int led_insert_node(unsigned node) { return node == 1 || node == 8 || node == 9; }

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
    led_shm->version = 1;
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
    if (!led_insert_node(node)) return;

    /* The boot enumeration: remember which indices this board really has. */
    if (n == 6 && (cmd == 0x84 || cmd == 0x85)) {
        if (p[3] < 96) led_known[node][p[3]] = 1;
        return;
    }
    if (cmd != 0x97 && cmd != 0xa2 && cmd != 0xa3 && cmd != 0xa4 &&
        cmd != 0xa5 && cmd != 0xa6 && cmd != 0xb4 && cmd != 0xb5) return;

    led_map();
    if (!led_shm) return;

    body = p + 3;
    blen = (unsigned)n - 5;                  /* drop checksum + reply-length */
    for (s = 0; s < 3; s++) {
        unsigned extra = (unsigned)shape[s].extra, gap = (unsigned)shape[s].gap;
        unsigned cnt;
        if (blen < extra + 2 || ((blen - extra) & 1)) continue;
        cnt = (blen - extra) / 2;
        if (!cnt) continue;
        for (i = 0; i < cnt; i++)
            if (body[i] >= 96 || !led_known[node][body[i]]) break;
        if (i != cnt) continue;              /* not all valid indices */
        for (i = 0; i < cnt; i++)
            led_shm->val[node][body[i]] = body[cnt + gap + i];
        led_shm->decoded += cnt;
        led_shm->gen++;
        return;
    }
    led_shm->skipped++;
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
        {
            static const char *silent = (const char *)-1;
            if (silent == (const char *)-1) silent = getenv("PAD_NB_SILENT");
            if (silent && nb_req_len > 0 && (nb_req[0] & 0x80)) {
                unsigned want = (unsigned)(nb_req[0] & 0x3f);
                const char *s = silent;
                while (*s) {
                    unsigned v = 0;
                    int any = 0;
                    while (*s >= '0' && *s <= '9') { v = v * 10 + (unsigned)(*s++ - '0'); any = 1; }
                    if (any && v == want) return 0;
                    if (*s) s++;
                }
            }
        }
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
                    if (budget > 0 && want) {
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
                unsigned fw   = nb_env_hex("PAD_NB_FW",
                                           ident ? ident->fw : NB_FW_DEFAULT);
                unsigned var  = nb_env_hex("PAD_NB_VARIANT",
                                           ident ? ident->variant : 0);
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
        nb_log("TX", nb_req, nb_req_len, 0);
        led_publish(nb_req, nb_req_len);
        nb_trace();
        nb_maybe_poke();
        nb_watch_flags();
        nb_maybe_dump();
        alert_maybe_dump();
        val_maybe_dump();
        sw_maybe_dump();
        return (long)n;
    }
    return real_write(fd, b, n);
}
