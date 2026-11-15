/* padmenu.c - back to the boot menu without switching the machine off (PAD-1309).
 *
 * A multi-boot card's menu (codeselect) runs once, at power-up, from
 * /etc/init.d/game, before the game starts.  To pick another game the operator
 * used to switch the machine off and on.  This object is preloaded into THE
 * GAME (the multi-boot form of the game_monitor hook, modehook.MENU_HOOK_LINES)
 * and gives the coin door a way back instead:
 *
 *     hold BACK on the coin door for HOLD_MS (3 s; the card's back_hold=, PAD-1309)
 *         -> select.sh --reboot: sync, then reboot
 *         -> the machine boots again, and the menu comes up as at power-up
 *
 * HOW IT SEES THE BUTTON, WITHOUT ANY TITLE'S ADDRESSES.  The coin-door buttons
 * are not on the node bus: they are the cabinet word, an 8-byte full-duplex
 * SPI_IOC_MESSAGE the game itself sends on /dev/spidev1.0 in a loop that never
 * stops (hwshim.c "THE CABINET SWITCHES"; codeselect reads the same word in
 * input_hw.c when it owns the machine).  rx[1] bits 0-3 are Service Select /
 * Plus / Minus / Back, ACTIVE LOW.  That is the hardware, so it is the same on
 * every Spike 2 title and version.  This object interposes open()/openat()/
 * close() (to remember which fd is that device) and ioctl(), passes every call
 * through untouched, and only AFTER the game's own transfer has returned does
 * it read bit 3 of rx[1].  It never sends a byte of its own: the
 * word's tx half drives the amplifier enable (input_hw.c), and a second master
 * on that wire is how a machine goes quiet.
 *
 * WHY BACK, HELD.  It is inside the coin door (an operator's control, like the
 * choice of code), and a long hold of it means nothing to the game: in the
 * service menu BACK steps out a level per press, in attract and in play it does
 * nothing.  Five seconds is far past any press.  The hold has to be unbroken: one
 * released sample starts it again.
 *
 * WHAT IT NEVER DOES.  It never takes the game down by itself: the reboot is
 * select.sh's, a plain `sync; reboot` (busybox's, which stops the processes and
 * unmounts as a normal shutdown does).  It never fires twice.  It is inert in
 * any process but the game (the hook preloads it there and nowhere else) and
 * on any fd that is not the cabinet chain - every other ioctl is one extra
 * compare.  Spike 3 builds of it: see "THE TWO MACHINES" below.
 *
 * PADMENU_HOLD_MS=<ms>, PADMENU_CMD=<path> and CODESELECT_REBOOT=<command>
 * exist for the tests and the rig (run_game.sh); a card's game_monitor sets
 * none of them.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

/* THE TWO MACHINES.  Spike 2 (the default): BACK is rx[1] bit 3 of
 * /dev/spidev1.0, and select.sh --reboot does the restart.  Spike 3 (the
 * Makefile's PLATFORM=s3 build, -DPADMENU_S3): BACK is rx[0] bit 3 of
 * /dev/spidev4.0 (stubs_s3.c), and there is no script to call - padselect_s3.sh
 * lives under /games/pad, which the chosen image's bind over /games hides
 * from the running game - so the restart is `sync; reboot` itself. */
/* BARRELS OF FUN (-DPADMENU_FAST, `make PLATFORM=bof`): no SPI word.  The
 * game talks to its FAST Neuron over a USB serial port (/dev/ttyACM*), ASCII
 * lines ended by '\r', and the board PUSHES a line when a switch the game set
 * up changes: "-L:<hex>" active, "/L:<hex>" inactive (tools/bof_emu/bofhw.py,
 * read off the game's own fast_stem.gd).  The coin door's EXIT is switch 5 on
 * every BOF title (Labyrinth, Dune, Winchester profiles), so this reads the
 * lines the game itself reads and times EXIT.  Lines come only on a change,
 * so the hold is timed by a thread of ours, started on the first press.  The
 * game runs as pinball, whose sudo needs no password: `sync; sudo -n reboot`.
 *
 * SPOOKY (the same x86-64 object, `make PLATFORM=spk`): padselect_spk.sh starts
 * the game with PADMENU_PROTO=warden|pinotaur and PADMENU_SWITCH=<its BACK>
 * (Warden titles 94, Halloween/Ultraman 63: tools/spooky_emu/spktitles.py).
 * Those boards speak binary on /dev/WARDEN or /dev/pinheck, every message the
 * board sends of a known size per opcode (spkwarden.py, spkpinotaur.py, read
 * off the games' own Warden.cs / Pinotar.cs), so the stream is followed a
 * MESSAGE at a time and only a switch message is ever read: a byte inside a
 * coil config or an LED row can never pass for BACK.  An opcode it does not
 * know drops it back to looking for the next start byte.  The game runs as
 * root or as a user with password-less sudo. */
#if defined(PADMENU_FAST)
#define CMD_DEFAULT     ""
#define REBOOT_SH       "sync; if [ \"$(id -u)\" = 0 ]; then exec ${CODESELECT_REBOOT:-reboot}; " \
                        "else exec ${CODESELECT_REBOOT:-sudo -n reboot}; fi"
#define BACK_SW_DEFAULT 5
#elif defined(PADMENU_S3)
#define CMD_DEFAULT     ""
#define REBOOT_SH       "sync; exec ${CODESELECT_REBOOT:-reboot}"
#define BACK_BYTE       0
#define CAB_DEV         "/dev/spidev4.0"
#else
#define CMD_DEFAULT     "/usr/local/codeselect/select.sh"
#define REBOOT_SH       "sync; exec ${CODESELECT_REBOOT:-reboot}"
#define BACK_BYTE       1
#define CAB_DEV         "/dev/spidev1.0"
#endif
#if defined(PADMENU_FAST) && defined(__x86_64__)
/* the machine's glibc is whatever its Arch image carried (2.33 at least, the
 * game's own need): ask for the oldest versions of the two symbols that moved */
__asm__(".symver dlsym,dlsym@GLIBC_2.2.5");
__asm__(".symver pthread_create,pthread_create@GLIBC_2.2.5");
#endif
#ifdef PADMENU_FAST
#include <pthread.h>
#endif
#ifndef O_TMPFILE
#define O_TMPFILE 0
#endif
/* HOW LONG.  3 s unless the card says otherwise: images.conf's back_hold=<seconds> (the
 * Multi-boot tab's Menu settings; 0 = off), read from CONF_PATH where the game can see it
 * (Spike 2, Barrels of Fun), or handed in as PADMENU_HOLD_MS=<ms> by the launchers that
 * start the game themselves (Spike 3, Spooky).  PADMENU_CONF names another file (tests). */
#define HOLD_MS_DEFAULT 3000
#if defined(PADMENU_FAST)
#define CONF_PATH       "/home/pinball/extracted/decrypt/padselect/images.conf"
#elif defined(PADMENU_S3)
#define CONF_PATH       ""
#else
#define CONF_PATH       "/usr/local/codeselect/images.conf"
#endif
#define SPI_MAGIC       0x6b            /* 'k', SPI_IOC_MAGIC */
#define MAX_FD          1024
#define BACK_BIT        3

typedef int (*ioctl_fn)(int, unsigned long, ...);
typedef int (*open_fn)(const char *, int, ...);
typedef int (*openat_fn)(int, const char *, int, ...);

#ifndef PADMENU_FAST
static ioctl_fn real_ioctl;
#endif
/* per fd: 0 not looked at yet, 1 the cabinet chain, 2 anything else.  Set when
 * the game OPENS CAB_DEV (whatever fd comes back: the rigs' shims answer with a
 * stand-in, Spike 3's with /dev/null), else on its first SPI transfer by the
 * path the fd reads back as.  Only that one device: another SPI device's bytes
 * read as BACK would restart a machine nobody asked to.  Cleared on close(). */
static unsigned char fd_kind[MAX_FD];
static long long held_since = -1;
static int fired;
static long hold_ms = -1;

static long long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void say(const char *msg)
{
    /* stderr is the game's, which the init script sends to the console */
    ssize_t r = write(2, msg, strlen(msg));
    (void)r;
}

static int is_cab_path(const char *p)
{
#ifdef PADMENU_FAST
    /* every USB serial port: the NET port answers among them, and only it
     * sends -L:/L: lines (a test's own directory may come before /dev);
     * Spooky's boards by their udev names */
    return p && (strstr(p, "/dev/ttyACM") || strstr(p, "/dev/ttyUSB") ||
                 strstr(p, "/dev/WARDEN") || strstr(p, "/dev/pinheck"));
#else
    size_t n, k = strlen(CAB_DEV);
    if (!p)
        return 0;
    n = strlen(p);            /* a chroot's or a test's prefix is allowed: ends with it */
    return n >= k && !strcmp(p + n - k, CAB_DEV);
#endif
}

static void fd_reset(int fd);              /* a reader's per-fd state, afresh */

static void note_open(int fd, const char *path)
{
    if (fd >= 0 && fd < MAX_FD) {
        fd_kind[fd] = is_cab_path(path) ? 1 : 0;
        fd_reset(fd);
    }
}

#ifndef PADMENU_FAST
static int is_spidev(int fd)
{
    char link[32], path[128];
    ssize_t n;
    if (fd < 0 || fd >= MAX_FD)
        return 0;
    if (!fd_kind[fd]) {
        snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
        n = readlink(link, path, sizeof path - 1);
        path[n > 0 ? n : 0] = 0;
        fd_kind[fd] = is_cab_path(path) ? 1 : 2;
    }
    return fd_kind[fd] == 1;
}
#endif

/* the opens, passed straight on; the fd of CAB_DEV is remembered */
#define OPEN_MODE(flags, ap, mode) \
    do { if ((flags) & (O_CREAT | O_TMPFILE)) { va_start(ap, flags); mode = va_arg(ap, int); va_end(ap); } } while (0)

int open(const char *path, int flags, ...)
{
    static open_fn next;
    va_list ap;
    int mode = 0, fd;
    OPEN_MODE(flags, ap, mode);
    if (!next && !(next = (open_fn)dlsym(RTLD_NEXT, "open"))) { errno = ENOSYS; return -1; }
    fd = next(path, flags, mode);
    note_open(fd, path);
    return fd;
}

int open64(const char *path, int flags, ...)
{
    static open_fn next;
    va_list ap;
    int mode = 0, fd;
    OPEN_MODE(flags, ap, mode);
    if (!next && !(next = (open_fn)dlsym(RTLD_NEXT, "open64"))) { errno = ENOSYS; return -1; }
    fd = next(path, flags, mode);
    note_open(fd, path);
    return fd;
}

int openat(int dirfd, const char *path, int flags, ...)
{
    static openat_fn next;
    va_list ap;
    int mode = 0, fd;
    OPEN_MODE(flags, ap, mode);
    if (!next && !(next = (openat_fn)dlsym(RTLD_NEXT, "openat"))) { errno = ENOSYS; return -1; }
    fd = next(dirfd, path, flags, mode);
    note_open(fd, path);
    return fd;
}

int close(int fd)
{
    static int (*next)(int);
    if (!next && !(next = (int (*)(int))dlsym(RTLD_NEXT, "close"))) { errno = ENOSYS; return -1; }
    if (fd >= 0 && fd < MAX_FD) {
        fd_kind[fd] = 0;
        fd_reset(fd);
    }
    return next(fd);
}

/* Run `<cmd> --reboot` detached: a new session, no LD_PRELOAD, its own
 * process, so the game goes on until the reboot stops it as it stops
 * everything.  vfork+exec: the game is many threads, and a child that only
 * execs is the one thing that is safe to make from any of them. */
static void ask_for_reboot(void)
{
    const char *cmd = getenv("PADMENU_CMD");
    char *argv[4] = { NULL, NULL, NULL, NULL };
    /* CODESELECT_REBOOT (select.sh's stand-in for `reboot`) is the one variable
     * passed on: the rig turns the restart into its own reboot request with it */
    const char *rb = getenv("CODESELECT_REBOOT");
    static char rbvar[512];
    char *envp[] = { "PATH=/sbin:/usr/sbin:/bin:/usr/bin", NULL, NULL };
    pid_t pid;
    if (rb && *rb && strlen(rb) < sizeof(rbvar) - 20) {
        strcpy(rbvar, "CODESELECT_REBOOT=");
        strcat(rbvar, rb);
        envp[1] = rbvar;
    }
    if (!cmd || !*cmd)
        cmd = CMD_DEFAULT;
    /* IN ONE OF PAD'S EMULATORS a real `reboot` is never right: the rig runs
     * the guest as root on the PC's own Linux, so it would restart that, not
     * the game.  Each rig passes CODESELECT_REBOOT (its own restart request);
     * a run that did not (its shims' variables set, no stand-in) does nothing. */
    if (!(rb && *rb) && (getenv("PAD_AUDIO_OUT") || getenv("PAD_S3_SPI_IN") ||
                         getenv("PAD_GL_BRIDGE") || getenv("PAD_SW_SHM") ||
                         getenv("BOFHW_DEV") || getenv("SPK_WARDEN"))) {
        say("padmenu: in the emulator with no CODESELECT_REBOOT - not restarting\n");
        return;
    }
    if (*cmd) {
        argv[0] = (char *)cmd;
        argv[1] = "--reboot";
    } else {
        /* no script (Spike 3): the restart itself, CODESELECT_REBOOT honoured */
        cmd = "/bin/sh";
        argv[0] = "sh";
        argv[1] = "-c";
        argv[2] = REBOOT_SH;
        argv[3] = NULL;
    }
    say("padmenu: BACK held - restarting the machine into the boot menu\n");
    pid = vfork();
    if (pid == 0) {
        setsid();
        execve(cmd, argv, envp);
        _exit(127);
    }
    if (pid < 0)
        say("padmenu: could not start the restart\n");
}

#ifdef PADMENU_FAST
#if defined(__x86_64__)
__asm__(".symver pthread_detach,pthread_detach@GLIBC_2.2.5");
#endif
typedef ssize_t (*read_fn)(int, void *, size_t);
typedef ssize_t (*read_chk_fn)(int, void *, size_t, size_t);
static int back_sw = BACK_SW_DEFAULT;
static volatile int thread_on;
static char lbuf[MAX_FD][24];           /* the line so far, per serial fd */
static unsigned char llen[MAX_FD];

/* the timer: lines come only on a change, so the hold is timed here */
static void *watch(void *unused)
{
    struct timespec ts = { 0, 100 * 1000 * 1000 };
    (void)unused;
    while (!fired) {
        long long since = held_since;
        if (since >= 0 && now_ms() - since >= hold_ms) {
            fired = 1;
            ask_for_reboot();
            break;
        }
        nanosleep(&ts, NULL);
    }
    return NULL;
}

static void set_back(int on)
{
    pthread_t t;
    if (fired)
        return;
    if (!on) {
        held_since = -1;
        return;
    }
    if (held_since < 0)
        held_since = now_ms();
    if (!thread_on) {
        thread_on = 1;
        if (pthread_create(&t, NULL, watch, NULL) == 0)
            pthread_detach(t);
        else
            thread_on = 0;
    }
}

/* "-L:05" / "/L:05" (any case, any number of hex digits) */
static void line_done(const char *s)
{
    const char *p = strstr(s, "L:");
    int n = 0, digits = 0, active;
    if (!p || p == s || (p[-1] != '-' && p[-1] != '/'))
        return;
    active = p[-1] == '-';
    for (p += 2; *p; p++, digits++) {
        int c = *p, v = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                        c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (v < 0)
            break;
        n = n * 16 + v;
    }
    if (digits && n == back_sw)
        set_back(active);
}

static void feed_lines(int fd, const char *b, ssize_t n)
{
    ssize_t k;
    for (k = 0; k < n; k++) {
        char c = b[k];
        if (c == '\r' || c == '\n') {
            lbuf[fd][llen[fd]] = 0;
            if (llen[fd])
                line_done(lbuf[fd]);
            llen[fd] = 0;
        } else if (llen[fd] < sizeof lbuf[fd] - 1) {
            lbuf[fd][llen[fd]++] = c;
        } else {
            llen[fd] = 0;                     /* not a switch line: drop it */
        }
    }
}

/* SPOOKY'S BOARDS, a message at a time.  Per fd: what is expected next. */
enum { PROTO_FAST, PROTO_WARDEN, PROTO_PINOTAUR };
static int proto = PROTO_FAST;
enum { B_START, B_OP, B_SKIP, B_TEXT, B_SW };
static struct bstate {
    unsigned char st, op, need, got;
    unsigned char a[2];
} bs[MAX_FD];

static void switch_level(int sw, int on)
{
    if (sw == back_sw)
        set_back(on);
}

/* the payload size of a board message by its opcode: -1 unknown, -2 a NUL-ended
 * text, 100 + k a switch message of k bytes */
static int payload(int op)
{
    if (proto == PROTO_WARDEN) {
        switch (op) {
        case 0x00: case 0x01: return 101;     /* <0|1> <sw> */
        case 0x98: return 102;                /* <sw> <level> */
        case 0xA8: return 5;                  /* coil config */
        case 0x96: case 0x97: return -2;      /* firmware / hardware text */
        case 0xD4: return 1;                  /* stepper state */
        }
    } else {
        switch (op) {
        case 0x58: return 102;                /* <sw> <level> */
        case 0x59: return 101;                /* <0x80|sw>, 0x7F nothing */
        case 0x00: return 9;
        case 0x01: case 0x02: return 5;
        case 0x6F: return 3;
        case 0x28: return 32;
        case 0x25: case 0x2B: return 0;
        case 0x20: return 5;
        case 0x0F: return 2;
        }
    }
    return -1;
}

static void feed_board(int fd, const unsigned char *b, ssize_t n)
{
    struct bstate *s = &bs[fd];
    unsigned char start = proto == PROTO_WARDEN ? 0x3C : 0x3E;
    ssize_t k;
    for (k = 0; k < n; k++) {
        unsigned char c = b[k];
        int p;
        switch (s->st) {
        case B_START:
            if (c == start)
                s->st = B_OP;
            break;
        case B_OP:
            s->op = c;
            p = payload(c);
            if (p == -1) {
                s->st = c == start ? B_OP : B_START;
            } else if (p == -2) {
                s->st = B_TEXT;
            } else if (p >= 100) {
                s->st = B_SW;
                s->need = (unsigned char)(p - 100);
                s->got = 0;
            } else {
                s->need = (unsigned char)p;
                s->st = p ? B_SKIP : B_START;
            }
            break;
        case B_SKIP:
            if (--s->need == 0)
                s->st = B_START;
            break;
        case B_TEXT:
            if (!c)
                s->st = B_START;
            break;
        case B_SW:
            s->a[s->got++] = c;
            if (s->got < s->need)
                break;
            s->st = B_START;
            if (proto == PROTO_WARDEN)
                switch_level(s->a[0], s->op == 0x98 ? s->a[1] : s->op);  /* 0x00/0x01: the op is the level */
            else if (s->op == 0x58)
                switch_level(s->a[0], s->a[1]);
            else if (s->a[0] != 0x7F)
                switch_level(s->a[0] & 0x7F, (s->a[0] & 0x80) != 0);
            break;
        }
    }
}

static void fd_reset(int fd)
{
    llen[fd] = 0;
    memset(&bs[fd], 0, sizeof bs[fd]);
}

static void feed(int fd, const char *b, ssize_t n)
{
    if (proto == PROTO_FAST)
        feed_lines(fd, b, n);
    else
        feed_board(fd, (const unsigned char *)b, n);
}

ssize_t read(int fd, void *buf, size_t n)
{
    static read_fn next;
    ssize_t r;
    if (!next && !(next = (read_fn)dlsym(RTLD_NEXT, "read"))) { errno = ENOSYS; return -1; }
    r = next(fd, buf, n);
    if (r > 0 && fd >= 0 && fd < MAX_FD && fd_kind[fd] == 1 && hold_ms > 0)
        feed(fd, buf, r);
    return r;
}

ssize_t __read_chk(int fd, void *buf, size_t n, size_t buflen)
{
    static read_chk_fn next;
    ssize_t r;
    if (!next && !(next = (read_chk_fn)dlsym(RTLD_NEXT, "__read_chk"))) { errno = ENOSYS; return -1; }
    r = next(fd, buf, n, buflen);
    if (r > 0 && fd >= 0 && fd < MAX_FD && fd_kind[fd] == 1 && hold_ms > 0)
        feed(fd, buf, r);
    return r;
}
#else /* the SPI word: Spike 2 and Spike 3 */
static void fd_reset(int fd) { (void)fd; }
static void sample(const unsigned char *rx)
{
    int back = !((rx[BACK_BYTE] >> BACK_BIT) & 1);    /* active low */
    long long t;
    if (fired)
        return;
    if (!back) {
        held_since = -1;
        return;
    }
    t = now_ms();
    if (held_since < 0) {
        held_since = t;
        return;
    }
    if (t - held_since >= hold_ms) {
        fired = 1;
        ask_for_reboot();
    }
}

/* struct spi_ioc_transfer (32 bytes): +0 tx_buf u64, +8 rx_buf u64, +16 len u32 */
static void look(int fd, unsigned long req, void *arg)
{
    unsigned long n, k;
    const unsigned char *x;
    if (((req >> 8) & 0xffu) != SPI_MAGIC || (req & 0xffu) != 0 || !arg)
        return;
    n = ((req >> 16) & 0x3fffu) / 32;
    if (!n || !is_spidev(fd))
        return;
    x = arg;
    for (k = 0; k < n; k++, x += 32) {
        uint64_t rxp;
        uint32_t len;
        memcpy(&rxp, x + 8, 8);
        memcpy(&len, x + 16, 4);
        if (len == 8 && rxp) {
            sample((const unsigned char *)(uintptr_t)rxp);
            return;
        }
    }
}

int ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    void *arg;
    int r;
    va_start(ap, req);
    arg = va_arg(ap, void *);
    va_end(ap);
    if (!real_ioctl) {
        real_ioctl = (ioctl_fn)dlsym(RTLD_NEXT, "ioctl");
        if (!real_ioctl) {
            errno = ENOSYS;
            return -1;
        }
    }
    r = real_ioctl(fd, req, arg);
    if (r >= 0 && hold_ms > 0)
        look(fd, req, arg);
    return r;
}
#endif

/* back_hold=<seconds> in an images.conf -> ms, or -1 when the file or the line is not there */
static long conf_hold_ms(const char *path)
{
    FILE *f;
    char line[256];
    long ms = -1;
    if (!path || !*path || !(f = fopen(path, "r")))
        return -1;
    while (fgets(line, sizeof line, f)) {
        const char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        if (strncmp(p, "back_hold", 9))
            continue;
        p += 9;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p != '=')
            continue;
        p++;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p >= '0' && *p <= '9') {
            long v = 0;
            while (*p >= '0' && *p <= '9' && v < 1000)
                v = v * 10 + (*p++ - '0');
            ms = v * 1000;
        }
    }
    fclose(f);
    return ms;
}

__attribute__((constructor))
static void padmenu_init(void)
{
    const char *h = getenv("PADMENU_HOLD_MS");
    const char *c = getenv("PADMENU_CONF");
    long ms;
    if (h && *h)
        hold_ms = strtol(h, NULL, 10);
    else if ((ms = conf_hold_ms(c && *c ? c : CONF_PATH)) >= 0)
        hold_ms = ms;
    else
        hold_ms = HOLD_MS_DEFAULT;
#ifdef PADMENU_FAST
    h = getenv("PADMENU_PROTO");           /* Spooky's launcher; BOF sets nothing: FAST */
    if (h && !strcmp(h, "warden"))
        proto = PROTO_WARDEN;
    else if (h && !strcmp(h, "pinotaur"))
        proto = PROTO_PINOTAUR;
    h = getenv("PADMENU_SWITCH");          /* Spooky's BACK; every BOF title's EXIT is 5 */
    if (h && *h)
        back_sw = (int)strtol(h, NULL, 10);
#endif
    /* the game's own children (system()) inherit LD_PRELOAD: nothing here for them */
    unsetenv("PADMENU_HOLD_MS");
    unsetenv("PADMENU_CONF");
}
