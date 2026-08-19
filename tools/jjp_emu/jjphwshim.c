/* jjphwshim.c - fake JJP's playfield I/O boards for a game running on a PC.
 *
 * WHAT IT REPLACES
 * ----------------
 * On a real machine every playfield board is a custom USB device driven by
 * JJP's own out-of-tree kernel modules, and userspace talks to them through
 * plain char devices: /dev/jjpio100 (I/O board: switch returns + coil drives),
 * /dev/jjpled100, /dev/jjpacc100, /dev/jjpcab100, /dev/jjptop100, plus sixteen
 * /dev/jjplp1NN LilyPads and sixteen /dev/jjpstep1NN steppers.  Those modules
 * are built for kernel 5.13 and will not load on WSL's 6.6, so the devices can
 * never exist here.  We interpose libc instead.
 *
 * WHY THIS IS SMALL, COMPARED WITH STERN'S hwshim.c (~9,200 lines)
 * ---------------------------------------------------------------
 * The protocol is a fixed 64-byte frame in both directions on every board, and
 * the real driver's read() is NON-BLOCKING: it takes a spinlock, copies the
 * last cached IN frame, and returns.  So we never have to model URB completion,
 * transfer timing, or a bus.  There is one path family (/dev/jjp*), no i2c
 * EEPROM to emulate, no termios, no pty, no node-bus framing.
 *
 * THE FRAME LAYOUT
 * ----------------
 * Derived from the live Switch objects (see swdump.py, which re-derives and
 * re-checks it on every dump).  For the I/O board's IN frame:
 *
 *     switch_NNN  ->  byte 4 + (N-1)/8 ,  bit 1 << ((N-1)%8)
 *
 * i.e. the 128-switch matrix is bytes 4..19, LSB first.  Everything outside
 * that window we serve as zero, which is correct-enough: the game treats a
 * missing board as non-fatal (CORE_NFERR_INIT_SWITCH/COIL/LED) and an all-zero
 * frame simply reads as "no switch closed".
 *
 * SHARED STATE
 * ------------
 * A POSIX shared-memory block (/jjp_switches by default) carries the switch
 * bitmap in, and the most recent OUT frame per board back out, so a UI process
 * can both drive switches and watch coils.  Layout is in jjpshm.h.
 *
 * Build:  see build.sh (plain -shared -fPIC, no dependencies beyond libc).
 * Use:    LD_PRELOAD=/path/jjphwshim.so ./game
 */

#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "jjpshm.h"

#define MAX_FAKE_FD 64
#define FRAME_LEN 64

/* One entry per fake device we have handed out. */
struct fake {
    int fd;             /* the real (pipe) fd we returned to the game */
    int board;          /* JJP_BOARD_* */
    int unit;           /* lilypad / stepper index, else 0 */
    int in_use;
};

static struct fake g_fake[MAX_FAKE_FD];
static struct jjp_shm *g_shm;
static int g_debug;
static int g_open_total;
static int g_fopen_total;

/* Real libc entry points. */
static int  (*real_open)(const char *, int, ...);
static int  (*real_open64)(const char *, int, ...);
static int  (*real_openat)(int, const char *, int, ...);
static ssize_t (*real_read)(int, void *, size_t);
static ssize_t (*real_write)(int, const void *, size_t);
static int  (*real_close)(int);
static int  (*real_ioctl)(int, unsigned long, ...);
static int  (*real_stat)(const char *, struct stat *);
static int  (*real_access)(const char *, int);

static void dbg(const char *fmt, ...)
{
    if (!g_debug)
        return;
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[jjphwshim] ");
    vfprintf(stderr, fmt, ap);
    fputc('\n', stderr);
    va_end(ap);
}

static void resolve(void)
{
    if (real_open)
        return;
    real_open    = dlsym(RTLD_NEXT, "open");
    real_open64  = dlsym(RTLD_NEXT, "open64");
    real_openat  = dlsym(RTLD_NEXT, "openat");
    real_read    = dlsym(RTLD_NEXT, "read");
    real_write   = dlsym(RTLD_NEXT, "write");
    real_close   = dlsym(RTLD_NEXT, "close");
    real_ioctl   = dlsym(RTLD_NEXT, "ioctl");
    real_stat    = dlsym(RTLD_NEXT, "stat");
    real_access  = dlsym(RTLD_NEXT, "access");
}

static void shm_attach(void)
{
    if (g_shm)
        return;
    const char *name = getenv("JJP_SHM_NAME");
    if (!name)
        name = JJP_SHM_DEFAULT_NAME;

    int fd = shm_open(name, O_RDWR | O_CREAT, 0666);
    if (fd < 0) {
        dbg("shm_open(%s) failed: %s", name, strerror(errno));
        return;
    }
    if (ftruncate(fd, sizeof(struct jjp_shm)) < 0)
        dbg("ftruncate: %s", strerror(errno));

    void *p = mmap(NULL, sizeof(struct jjp_shm), PROT_READ | PROT_WRITE,
                   MAP_SHARED, fd, 0);
    real_close(fd);
    if (p == MAP_FAILED) {
        dbg("mmap failed: %s", strerror(errno));
        return;
    }
    g_shm = p;
    if (g_shm->magic != JJP_SHM_MAGIC) {
        memset(g_shm, 0, sizeof(*g_shm));
        g_shm->magic = JJP_SHM_MAGIC;
        g_shm->version = JJP_SHM_VERSION;
    }
    g_shm->game_pid = getpid();
    dbg("attached shm %s", name);
}

/* Parse one or two hex digits.  Deliberately NOT strtol: the host's headers
 * redirect strtol to __isoc23_strtol (glibc 2.38), which the game's 2.34 image
 * does not export, and the game then dies with a symbol lookup error before
 * main().  Hand-rolling it keeps the .so loadable on the old runtime. */
static int hex2(const char *p)
{
    int v = 0, n = 0;
    for (; n < 2 && *p; p++, n++) {
        int d;
        if (*p >= '0' && *p <= '9') d = *p - '0';
        else if (*p >= 'a' && *p <= 'f') d = *p - 'a' + 10;
        else if (*p >= 'A' && *p <= 'F') d = *p - 'A' + 10;
        else break;
        v = v * 16 + d;
    }
    return v;
}

/* Recognise /dev/jjp* and say which board it is.  Returns 0 if not ours. */
static int classify(const char *path, int *board, int *unit)
{
    if (!path || strncmp(path, "/dev/jjp", 8) != 0)
        return 0;
    const char *p = path + 8;
    *unit = 0;

    if      (!strncmp(p, "io",   2)) { *board = JJP_BOARD_IO;   return 1; }
    else if (!strncmp(p, "led",  3)) { *board = JJP_BOARD_LED;  return 1; }
    else if (!strncmp(p, "acc",  3)) { *board = JJP_BOARD_ACC;  return 1; }
    else if (!strncmp(p, "cab",  3)) { *board = JJP_BOARD_CAB;  return 1; }
    else if (!strncmp(p, "top2", 4)) { *board = JJP_BOARD_TOP2;
                                       *unit = hex2(p + 4) & 0xf;
                                       return 1; }
    else if (!strncmp(p, "top",  3)) { *board = JJP_BOARD_TOP;  return 1; }
    else if (!strncmp(p, "lp",   2)) { *board = JJP_BOARD_LILY;
                                       *unit = hex2(p + 2) & 0xf;
                                       return 1; }
    else if (!strncmp(p, "step", 4)) { *board = JJP_BOARD_STEP;
                                       *unit = hex2(p + 4) & 0xf;
                                       return 1; }
    return 0;
}

/* Hand back a real fd so poll/select/close behave, but one WE own.  A pipe is
 * the cheapest thing that is a genuine fd; we never actually transfer through
 * it, because read() and write() are interposed below. */
static int make_fake(int board, int unit)
{
    int pf[2];
    if (pipe(pf) < 0)
        return -1;
    real_close(pf[1]);                      /* keep only the read end */

    for (int i = 0; i < MAX_FAKE_FD; i++) {
        if (!g_fake[i].in_use) {
            g_fake[i].in_use = 1;
            g_fake[i].fd = pf[0];
            g_fake[i].board = board;
            g_fake[i].unit = unit;
            dbg("open board=%d unit=%d -> fd %d", board, unit, pf[0]);
            return pf[0];
        }
    }
    real_close(pf[0]);
    errno = EMFILE;
    return -1;
}

static struct fake *lookup(int fd)
{
    for (int i = 0; i < MAX_FAKE_FD; i++)
        if (g_fake[i].in_use && g_fake[i].fd == fd)
            return &g_fake[i];
    return NULL;
}

/* ---------------------------------------------------------------- open ---- */

static int open_common(const char *path, int flags)
{
    (void)flags;                            /* a char device we fake ignores them */
    int board, unit;
    if (!classify(path, &board, &unit)) {
        /* JJP_SHIM_DEBUG=2 traces every /dev path the game touches.  This is
         * how you find out what it is REALLY probing when it decides a board
         * is absent - it does not necessarily open() the node it wants. */
        if (g_debug > 1 && path && !strncmp(path, "/dev/", 5))
            dbg("probe open %s", path);
        /* JJP_SHIM_DEBUG=3 counts EVERY open.  This is the control experiment:
         * if the game opens thousands of assets and we see none of them, the
         * envelope is not reaching libc through the PLT and no LD_PRELOAD can
         * ever interpose it - which is a completely different problem from
         * "the game chose not to open the boards". */
        if (g_debug > 2) {
            g_open_total++;
            if (g_open_total <= 12)
                dbg("open#%d %s", g_open_total, path ? path : "(null)");
            else if ((g_open_total % 500) == 0)
                dbg("open#%d ...", g_open_total);
        }
        return -2;                          /* not ours */
    }
    shm_attach();
    return make_fake(board, unit);
}

int open(const char *path, int flags, ...)
{
    resolve();
    int r = open_common(path, flags);
    if (r != -2)
        return r;
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    return real_open(path, flags, mode);
}

int open64(const char *path, int flags, ...)
{
    resolve();
    int r = open_common(path, flags);
    if (r != -2)
        return r;
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    return real_open64 ? real_open64(path, flags, mode)
                       : real_open(path, flags, mode);
}

int openat(int dirfd, const char *path, int flags, ...)
{
    resolve();
    int r = open_common(path, flags);
    if (r != -2)
        return r;
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags); mode = va_arg(ap, int); va_end(ap);
    }
    return real_openat(dirfd, path, flags, mode);
}

/* The game may probe with access()/stat() before opening.  Say yes. */
int access(const char *path, int mode)
{
    resolve();
    int board, unit;
    if (classify(path, &board, &unit))
        return 0;
    if (g_debug > 1 && !strncmp(path, "/dev/", 5))
        dbg("probe access %s", path);
    return real_access(path, mode);
}

/* The game may enumerate /dev rather than opening a node by name, in which case
 * a device that does not appear in readdir() is a device it never tries.  Trace
 * the enumeration too. */
DIR *opendir(const char *path)
{
    static DIR *(*real_opendir)(const char *);
    if (!real_opendir)
        real_opendir = dlsym(RTLD_NEXT, "opendir");
    if (g_debug > 1 && !strncmp(path, "/dev", 4))
        dbg("opendir %s", path);
    return real_opendir(path);
}

int stat(const char *path, struct stat *st)
{
    resolve();
    int board, unit;
    if (g_debug > 1 && !strncmp(path, "/dev/", 5) && !classify(path, &board, &unit))
        dbg("probe stat %s", path);
    if (classify(path, &board, &unit)) {
        memset(st, 0, sizeof(*st));
        st->st_mode = S_IFCHR | 0664;
        st->st_rdev = 0;
        return 0;
    }
    return real_stat(path, st);
}

/* ---------------------------------------------------------------- read ---- */

ssize_t read(int fd, void *buf, size_t count)
{
    resolve();
    struct fake *f = lookup(fd);
    if (!f)
        return real_read(fd, buf, count);

    /* The real driver rejects a short read outright. */
    if (count < FRAME_LEN) {
        errno = EINVAL;
        return -1;
    }

    unsigned char frame[FRAME_LEN];
    memset(frame, 0, sizeof(frame));

    if (g_shm && f->board == JJP_BOARD_IO) {
        /* bytes 4..19 = the 128-switch matrix, LSB first */
        memcpy(frame + JJP_MATRIX_FIRST_BYTE, (const void *)g_shm->switches,
               JJP_MATRIX_BYTES);
        g_shm->read_count++;
    } else if (g_shm && f->board == JJP_BOARD_CAB) {
        memcpy(frame + JJP_MATRIX_FIRST_BYTE, (const void *)g_shm->cabinet,
               sizeof(g_shm->cabinet));
    }

    memcpy(buf, frame, FRAME_LEN);
    return FRAME_LEN;
}

/* --------------------------------------------------------------- write ---- */

ssize_t write(int fd, const void *buf, size_t count)
{
    resolve();
    struct fake *f = lookup(fd);
    if (!f)
        return real_write(fd, buf, count);

    size_t n = count > FRAME_LEN ? FRAME_LEN : count;
    if (g_shm && f->board >= 0 && f->board < JJP_BOARD_COUNT) {
        volatile unsigned char *dst = g_shm->out[f->board];
        /* Coils are PULSES.  A UI that samples a level will miss a 30 ms
         * slingshot about half the time, so publish a per-byte change counter
         * alongside the level and let the UI read edges, never levels. */
        for (size_t i = 0; i < n; i++) {
            if (dst[i] != ((const unsigned char *)buf)[i])
                g_shm->out_changes[f->board]++;
            dst[i] = ((const unsigned char *)buf)[i];
        }
        g_shm->write_count++;
    }
    return (ssize_t)count;                  /* the driver clamps, never fails */
}

int close(int fd)
{
    resolve();
    struct fake *f = lookup(fd);
    if (f) {
        f->in_use = 0;
        dbg("close fd %d (board %d)", fd, f->board);
    }
    return real_close(fd);
}

int ioctl(int fd, unsigned long req, ...)
{
    resolve();
    va_list ap;
    va_start(ap, req);
    void *arg = va_arg(ap, void *);
    va_end(ap);

    /* LilyPad / stepper / topper2 drivers take ioctls we do not model.  Succeed
     * silently: the game treats board init failure as non-fatal anyway, and an
     * error here would only add noise. */
    if (lookup(fd))
        return 0;
    return real_ioctl(fd, req, arg);
}

/* CONTROL ONLY (JJP_SHIM_DEBUG=3).  fopen is imported by the game, so if we
 * see fopen traffic but no open traffic, the shim IS in the game's path and
 * the game genuinely never open()s a /dev/jjp* node - the asset loading simply
 * goes through fopen, whose internal open() happens inside libc and is not
 * interposable by LD_PRELOAD.  If we see NEITHER, the shim is unreachable and
 * no LD_PRELOAD approach can work; that is what /dev/cuse is for. */
FILE *fopen(const char *path, const char *mode)
{
    static FILE *(*real_fopen)(const char *, const char *);
    if (!real_fopen)
        real_fopen = dlsym(RTLD_NEXT, "fopen");
    if (g_debug > 2) {
        g_fopen_total++;
        if (g_fopen_total <= 8)
            dbg("fopen#%d %s", g_fopen_total, path ? path : "(null)");
        else if ((g_fopen_total % 500) == 0)
            dbg("fopen#%d ...", g_fopen_total);
    }
    return real_fopen(path, mode);
}

__attribute__((constructor))
static void jjphwshim_init(void)
{
    const char *dbgv = getenv("JJP_SHIM_DEBUG");
    g_debug = dbgv ? (dbgv[0] >= '0' && dbgv[0] <= '9' ? dbgv[0] - '0' : 1) : 0;
    resolve();
    shm_attach();
    dbg("loaded (pid %d)", getpid());
}
