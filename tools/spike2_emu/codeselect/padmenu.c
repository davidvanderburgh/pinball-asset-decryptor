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
static void nb_forget(int fd);             /* the node bus watcher's, afresh (Spike 2) */

static void note_open(int fd, const char *path)
{
    if (fd >= 0 && fd < MAX_FD) {
        fd_kind[fd] = is_cab_path(path) ? 1 : 0;
        fd_reset(fd);
        nb_forget(fd);
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
        nb_forget(fd);
    }
    return next(fd);
}

/* Run `<cmd> --reboot` detached: a new session, no LD_PRELOAD, its own
 * process, so the game goes on until the reboot stops it as it stops
 * everything.  vfork+exec: the game is many threads, and a child that only
 * execs is the one thing that is safe to make from any of them. */
static void ask_for_reboot_why(const char *why);
static void ask_for_reboot(void) { ask_for_reboot_why("padmenu: BACK held - restarting the machine into the boot menu\n"); }
static void ask_for_reboot_why(const char *why)
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
    say(why);
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
/* BACK HELD, AND NOTHING ELSE IN ITS BYTE (PAD-1490).  The byte's low four bits
 * are the four service buttons, Select / Plus / Minus / Back (Spike 3: Select /
 * Next / Previous / Back), active low.  A finger on BACK leaves the other three
 * high; a read the chain did not drive - a dead or glitching cabinet word, all
 * zeros - shows all four "pressed" at once, and three seconds of that must not
 * restart a machine nobody touched.  So only 0111 in those bits is BACK held:
 * anything else counts as released and starts the hold again. */
#define SERVICE_MASK   0x0fu
#define BACK_ONLY      (SERVICE_MASK & ~(1u << BACK_BIT))
/* AND UNBROKEN IN TIME.  The game reads the word in a loop with no sleep, an
 * 8-byte transfer at 100 kHz every ~640 us, so a real hold is thousands of
 * samples in a row.  Two stray "BACK" reads with a quiet spell between them
 * (the loop stalled, the device not answering) are not a hold: a gap of more
 * than GAP_MS between samples starts the hold again. */
#define GAP_MS         250
static long long last_sample = -1;
static void sample(const unsigned char *rx)
{
    int back = (rx[BACK_BYTE] & SERVICE_MASK) == BACK_ONLY;
    long long t;
    if (fired)
        return;
    t = now_ms();
    if (last_sample >= 0 && t - last_sample > GAP_MS)
        held_since = -1;
    last_sample = t;
    if (!back) {
        held_since = -1;
        return;
    }
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

static int conf_word(const char *path, const char *key, char *out, size_t outlen);
#if !defined(PADMENU_FAST) && !defined(PADMENU_S3)
/* ---- THE RIGHT FLIPPER, HELD, WITH NO GAME ON (Simon, 2026-11-22) ------------------------------
 * Simon: "get back to the multiboot menu from a running game", then: "This should not run during
 * gameplay at all. Just when no game is running" and "Right flipper held on - 5 seconds for
 * activation."  On when the card's images.conf says boot_menu=flipper or hidden (the Multi-boot tab),
 * for flip_hold= seconds after flip_guard= seconds with no game on (flip_init); PADMENU_TRACE=<file>
 * says what it saw.
 *
 * THE BUTTON.  The flipper buttons are on the node bus (/dev/ttymxc1), node 8, not the cabinet
 * SPI word: the game sends { 0x88, n, 0x11, [key], ck, 12 } and reads 10 bytes + ck + status;
 * bytes 0..7 are the switch bits, XORed with rol8(key, c) when n is 3 (hwshim.c "COMMAND 0x11"),
 * RIGHT FLIPPER BUTTON byte 3 bit 0, LEFT bit 1, active low (input_hw.c scan_node).  As with BACK,
 * only the game's own exchange is read, after it returns; not a byte is sent.
 *
 * NO GAME ON, WITHOUT ANY TITLE'S ADDRESSES.  The boards fire the flippers themselves, from their
 * own switch, under a rule the game hands them with command 0x41 (hwshim.c "PAD-775"): power at
 * byte 4, a rule cleared by power 0 or the short form `41 <coil>`.  A machine with any rule live
 * is a game in play; none live is attract, a tilt, the bonus or the end of a game.  The last few
 * are still a game, so the hold also needs the rules to have been off for PADMENU_FLIP_QUIET_MS. */
#define NB_DEV        "/dev/ttymxc1"
#define NB_NODE_FLIP  8
static unsigned char nb_kind[MAX_FD];      /* 0 unknown, 1 the node bus, 2 anything else */
static int nb_want[MAX_FD], nb_got[MAX_FD], nb_is_scan[MAX_FD];
static unsigned char nb_key[MAX_FD], nb_rx[MAX_FD][16];
static unsigned char rule_on[64][32];      /* 1: a live rule fired by a FLIPPER BUTTON (node 8 input 24/25) */
static int rules_live;
static long long rules_off_since;          /* set at start: a game starts with none live */
static long flip_ms, flip_quiet_ms;
static int flip_fire, flip_fired;
static long long flip_since = -1, flip_last = -1;
static int flip_was = -1;
static long flip_hold_cur;                 /* the hold now counting, ms (the ring) */
static const char *ring_who = "";          /* which hold the ring shows (the trace) */
static FILE *trace;
/* THE SERVICE MENU ROW (Simon, 2026-11-25: "there is no way to enable or disable the right flipper action").  A
 * game the app wrote with BOOT MENU FLIPPER ticked has /usr/local/padmode/padmenu.cfg (boot_flip.py):
 *     flip_secs <the value's word> <key> <default>
 * the seconds with no game on before a hold counts, 0 Off (Simon 2026-11-26: "we let the user set the values"; the
 * first build's 1 Off / 2 20 s / 3 60 s only went to Simon's test table).  The word is the game's own address of the row's value (this
 * object runs inside the game), or, at 0xfade0000 and up, one of the mode runtime's MORE SETTINGS words, whose value
 * the runtime keeps in /dump/pad_settings.state as "<key> <value>".  Where the card has the row, it wins over
 * images.conf's boot_menu= / flip_guard=.  An address the game has not mapped is never read (flip_row_ok). */
#define ROW_CFG     "/usr/local/padmode/padmenu.cfg"
#define ROW_CFG_RIG "/dump/padmenu.cfg"           /* the emulator puts a card's runtime files in /dump */
#define ROW_STATE   "/dump/pad_settings.state"
#define ROW_SHARED  0xfade0000ul
#define ROW_HOLD_MS 5000
#define ROW_MAX_S   600
#define ROW_MIN_S   15
static unsigned long row_addr;             /* 0: no row on this card */
static char row_key[40], row_state[128] = ROW_STATE;
static int row_def = 15, row_val = -1, row_ok = -1;
static int guard_env;                      /* PADMENU_FLIP_GUARD_MS given (the tests): it wins over the row's too */
static long long row_due;

static void tr(const char *fmt, ...)
{
    va_list ap;
    if (!trace)
        return;
    fprintf(trace, "%lld ", now_ms());
    va_start(ap, fmt);
    vfprintf(trace, fmt, ap);
    va_end(ap);
    fputc('\n', trace);
    fflush(trace);
}

static void nb_forget(int fd)
{
    if (fd >= 0 && fd < MAX_FD) {
        nb_kind[fd] = 0;
        nb_want[fd] = nb_got[fd] = nb_is_scan[fd] = 0;
    }
}

static int is_nb(int fd)
{
    char link[32], path[128];
    ssize_t n;
    size_t k = strlen(NB_DEV), m;
    if (fd < 0 || fd >= MAX_FD)
        return 0;
    if (!nb_kind[fd]) {
        snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
        n = readlink(link, path, sizeof path - 1);
        path[n > 0 ? n : 0] = 0;
        m = strlen(path);
        nb_kind[fd] = (m >= k && !strcmp(path + m - k, NB_DEV)) ? 1 : 2;
    }
    return nb_kind[fd] == 1;
}

static void rule_set(unsigned node, unsigned coil, int on, int input)
{
    int i, j, live = 0;
    /* only the flippers' own rules: the game keeps others (Godzilla's node 9 coil 2, input 0, for
     * 10 s at a time in attract) that say nothing about a game.  A rule's input byte is 0x40 | the
     * board input; the flipper buttons are node 8 inputs 24 and 25 on every Spike 2 title. */
    if (on && !(node == NB_NODE_FLIP && (input == 0x58 || input == 0x59))) {
        tr("rule node %u coil %u ON input 0x%02x (not a flipper's)", node, coil, input);
        return;
    }
    if (node >= 64 || coil >= 32 || rule_on[node][coil] == (on ? 1 : 0))
        return;
    rule_on[node][coil] = on ? 1 : 0;
    for (i = 0; i < 64 && !live; i++)
        for (j = 0; j < 32; j++)
            if (rule_on[i][j]) { live = 1; break; }
    tr("rule node %u coil %u %s input 0x%02x (rules live: %d)", node, coil, on ? "ON" : "off", input, live);
    if (live != rules_live) {
        rules_live = live;
        if (!live)
            rules_off_since = now_ms();
        tr("FLIPPERS %s", live ? "LIVE (a game is in play)" : "DEAD (no rule live)");
    }
}

/* THE HOLD, ON STATE (the table, 2026-11-25: a 9 s hold never counted).  On the real machine the
 * game reads node 8's switches when the board says one CHANGED: a held flipper gives one reading at
 * the press and one at the release, and a whole minute of attract gave one.  The emulator's boards
 * answer the scan all the time, which is why the first version (a hold = readings no more than
 * 500 ms apart) passed there.  So the last reading IS the button until the next one, and the 5 s
 * are counted on the game's other bus traffic (flip_check from every frame the game writes). */
/* the row's address in a readable mapping of this process (read once) */
static int flip_row_ok(void)
{
    FILE *f;
    char line[256];
    if (row_ok >= 0)
        return row_ok;
    row_ok = 0;
    if (!(f = fopen("/proc/self/maps", "r")))
        return 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long a, b;
        char perm[8];
        if (sscanf(line, "%lx-%lx %7s", &a, &b, perm) == 3 && perm[0] == 'r'
                && row_addr >= a && row_addr + 4 <= b) {
            row_ok = 1;
            break;
        }
    }
    fclose(f);
    if (!row_ok)
        tr("BOOT MENU FLIPPER: 0x%08lx is not in this game's memory - the row is not read", row_addr);
    return row_ok;
}

/* the row's value now (seconds, 0 Off): its word, or the runtime's file; the default until there is one.  The file is read at
 * most once a second, and only while the button is down (flip_check). */
static int flip_row(long long t)
{
    int v = -1;
    if (row_addr < ROW_SHARED) {
        if (flip_row_ok())
            v = (int)*(volatile uint32_t *)(uintptr_t)row_addr;
    } else if (t >= row_due) {
        FILE *f = fopen(row_state, "r");
        char line[96];
        size_t k = strlen(row_key);
        row_due = t + 1000;
        row_val = -1;
        if (f) {
            while (fgets(line, sizeof line, f))
                if (!strncmp(line, row_key, k) && line[k] == ' ')
                    row_val = atoi(line + k + 1);
            fclose(f);
        }
        v = row_val;
    } else {
        v = row_val;
    }
    if (v < 0 || v > ROW_MAX_S)
        v = row_def;                           /* not a value the row can hold */
    else if (v > 0 && v < ROW_MIN_S)
        v = ROW_MIN_S;                         /* the shared row steps by one: 1 to 14 is the least, 15 (Simon) */
    return v;
}

static void flip_check(long long t)
{
    long hold = flip_ms, quiet = flip_quiet_ms;
    if (flip_fired || flip_was != 1)
        return;
    if (row_addr) {                            /* the operator's row wins over images.conf */
        static int said = -1;
        int v = flip_row(t);
        if (v != said)
            tr("BOOT MENU FLIPPER reads %d (%s)", v, v ? "seconds after a game" : "off");
        said = v;
        if (v == 0)
            return;
        hold = flip_ms > 0 ? flip_ms : ROW_HOLD_MS;
        if (!guard_env)
            quiet = v * 1000L;
    }
    if (hold <= 0)
        return;
    if (rules_live || t - rules_off_since < quiet) {
        if (flip_since >= 0)
            tr("hold broken: %s", rules_live ? "a game is in play" : "the flippers went off too lately");
        flip_since = -1;                       /* no game on, for the whole hold */
        return;
    }
    flip_hold_cur = hold;                     /* the ring's (eglSwapBuffers) */
    if (flip_since < 0) {
        flip_since = t;
        return;
    }
    if (t - flip_since >= hold) {
        flip_fired = 1;
        tr("RIGHT FLIPPER HELD %ld ms with no game on - %s", hold,
           flip_fire ? "restarting into the boot menu" : "would restart (PADMENU_FLIP_FIRE not set)");
        if (flip_fire)
            ask_for_reboot_why("padmenu: right flipper held - restarting the machine into the boot menu\n");
    }
}

/* one right flipper reading, from a good node 8 scan reply */
static long scans_asked, scans_read;
static void flip_sample(int pressed)
{
    long long t = now_ms();
    scans_read++;
    if (!pressed && flip_fired && !flip_fire)
        flip_fired = 0;                        /* log only: every hold is a try */
    if (pressed != flip_was) {
        tr("right flipper %s (rules live %d, off for %lld ms)", pressed ? "PRESSED" : "released",
           rules_live, rules_live ? 0 : t - rules_off_since);
        flip_was = pressed;
        flip_since = -1;                       /* a new press starts its own count */
    }
    flip_last = t;
    flip_check(t);
}

/* the game's frames out: rules, and which reply is the node 8 scan's */
static void nb_wrote(int fd, const unsigned char *b, ssize_t n)
{
    ssize_t i = 0;
    nb_want[fd] = nb_got[fd] = nb_is_scan[fd] = 0;
    while (i + 3 <= n && (b[i] & 0x80)) {
        unsigned len = b[i + 1], node = b[i] & 0x3fu, size = len + 3, k, sum = 0;
        if (i + (ssize_t)size > n)
            break;
        for (k = 0; k < size - 1; k++)
            sum += b[i + k];
        if ((sum & 0xff) == 0) {
            unsigned cmd = b[i + 2], rl = b[i + size - 1];
            if (cmd == 0x41 && len >= 3)
                rule_set(node, b[i + 3], size > 6 && b[i + 4] != 0, size > 26 ? b[i + 26] : -1);
            if (rl && rl <= sizeof nb_rx[0]) {
                nb_want[fd] = (int)rl;
                nb_is_scan[fd] = cmd == 0x11 && node == NB_NODE_FLIP && rl == 12;
                if (nb_is_scan[fd]) scans_asked++;
                nb_key[fd] = len == 3 ? b[i + 3] : 0;
            }
        }
        i += size;
    }
    {
        static long long acct;
        long long t = now_ms();
        flip_check(t);
        if (trace && t - acct >= 30000) {     /* how often the game reads node 8, for the trace */
            if (acct) tr("node 8 scans: %ld asked, %ld read in 30 s", scans_asked, scans_read);
            acct = t;
            scans_asked = scans_read = 0;
        }
    }
}

static void nb_read(int fd, const unsigned char *b, ssize_t n)
{
    ssize_t i;
    for (i = 0; i < n && nb_got[fd] < nb_want[fd]; i++)
        nb_rx[fd][nb_got[fd]++] = b[i];
    if (nb_want[fd] && nb_got[fd] == nb_want[fd]) {
        if (nb_is_scan[fd]) {
            unsigned sum = 0, k, key = nb_key[fd];
            for (k = 0; k <= 10; k++)
                sum += nb_rx[fd][k];
            if ((sum & 0xff) == 0 && !(nb_rx[fd][11] & 0x0c)) {
                unsigned r3 = nb_rx[fd][3] ^ (((key << 3) | (key >> 5)) & 0xffu);
                flip_sample(!(r3 & 1));
            }
        }
        nb_want[fd] = nb_got[fd] = nb_is_scan[fd] = 0;
    }
}

typedef ssize_t (*write_fn)(int, const void *, size_t);
typedef ssize_t (*rd_fn)(int, void *, size_t);
typedef ssize_t (*rdchk_fn)(int, void *, size_t, size_t);

ssize_t write(int fd, const void *buf, size_t n)
{
    static write_fn next;
    ssize_t r;
    if (!next && !(next = (write_fn)dlsym(RTLD_NEXT, "write"))) { errno = ENOSYS; return -1; }
    r = next(fd, buf, n);
    if (r > 0 && (flip_ms > 0 || row_addr || trace) && fd > 2 && is_nb(fd))
        nb_wrote(fd, buf, r);
    return r;
}

ssize_t read(int fd, void *buf, size_t n)
{
    static rd_fn next;
    ssize_t r;
    if (!next && !(next = (rd_fn)dlsym(RTLD_NEXT, "read"))) { errno = ENOSYS; return -1; }
    r = next(fd, buf, n);
    if (r > 0 && fd >= 0 && fd < MAX_FD && nb_want[fd])
        nb_read(fd, buf, r);
    return r;
}

ssize_t __read_chk(int fd, void *buf, size_t n, size_t buflen)
{
    static rdchk_fn next;
    ssize_t r;
    if (!next && !(next = (rdchk_fn)dlsym(RTLD_NEXT, "__read_chk"))) { errno = ENOSYS; return -1; }
    r = next(fd, buf, n, buflen);
    if (r > 0 && fd >= 0 && fd < MAX_FD && nb_want[fd])
        nb_read(fd, buf, r);
    return r;
}

/* THE CARD SAYS (images.conf, the Multi-boot tab's Menu settings): boot_menu=flipper|hidden turns it on,
 * flip_hold=<s> (5) and flip_guard=<s> (60).  PADMENU_FLIP_MS / PADMENU_FLIP_GUARD_MS (ms) are the tests'
 * and the rig's, and win; PADMENU_FLIP_LOG=1 only says what it would do (the feasibility runs). */
static void flip_init(const char *conf)
{
    const char *v = getenv("PADMENU_FLIP_MS"), *q = getenv("PADMENU_FLIP_GUARD_MS"),
               *f = getenv("PADMENU_FLIP_LOG"), *t = getenv("PADMENU_TRACE");
    char w[32];
    long hold_s = 0, guard_s = 60;
    if (conf_word(conf, "boot_menu", w, sizeof w) && (!strcmp(w, "flipper") || !strcmp(w, "hidden")))
        hold_s = 5;
    if (hold_s && conf_word(conf, "flip_hold", w, sizeof w) && atol(w) >= 1 && atol(w) <= 30)
        hold_s = atol(w);
    if (conf_word(conf, "flip_guard", w, sizeof w) && w[0] >= '0' && w[0] <= '9' && atol(w) <= 600)
        guard_s = atol(w);
    flip_ms = v && *v ? strtol(v, NULL, 10) : hold_s * 1000;
    flip_quiet_ms = q && *q ? strtol(q, NULL, 10) : guard_s * 1000;
    guard_env = q && *q;
    flip_fire = !(f && *f == '1');
    rules_off_since = now_ms();
    if (t && *t)
        trace = fopen(t, "a");
    {
        const char *rc = getenv("PADMENU_ROW_CFG"), *rs = getenv("PADMENU_ROW_STATE");   /* the tests' */
        FILE *cf = fopen(rc && *rc ? rc : ROW_CFG, "r");
        if (!cf && !(rc && *rc))
            cf = fopen(ROW_CFG_RIG, "r");
        char line[160], key[40];
        unsigned long a;
        int d;
        if (cf) {
            while (fgets(line, sizeof line, cf))
                if (sscanf(line, "flip_secs %lx %39s %d", &a, key, &d) == 3 && a) {
                    row_addr = a;
                    snprintf(row_key, sizeof row_key, "%s", key);
                    row_def = d >= 0 && d <= ROW_MAX_S ? d : 15;
                }
            fclose(cf);
        }
        if (rs && *rs)
            snprintf(row_state, sizeof row_state, "%s", rs);
        unsetenv("PADMENU_ROW_CFG");
        unsetenv("PADMENU_ROW_STATE");
    }
    tr("padmenu flipper watcher: hold %ld ms (0 = off), after the flippers are off %ld ms, %s", flip_ms,
       flip_quiet_ms, flip_fire ? "restarts" : "log only");
    if (row_addr)
        tr("BOOT MENU FLIPPER row at 0x%08lx (%s, %d s to start with): it decides", row_addr, row_key, row_def);
    if (row_addr) {
        say("padmenu: the service menu's BOOT MENU FLIPPER decides the right flipper hold back to the boot menu\n");
    } else if (flip_ms > 0) {
        char m[160];
        snprintf(m, sizeof m, "padmenu: the right flipper held %ld s with no game on restarts into the boot menu"
                 " (the flippers off %ld s first)\n", flip_ms / 1000, flip_quiet_ms / 1000);
        say(m);
    }
    unsetenv("PADMENU_FLIP_MS");
    unsetenv("PADMENU_FLIP_GUARD_MS");
    unsetenv("PADMENU_FLIP_LOG");
    unsetenv("PADMENU_TRACE");
}

/* ---- THE HOLD, SHOWN (David, PR #48 review) ----------------------------------------------------
 * David: "as the user is holding the flipper to show some animation overlay (like a circle filling
 * up) to let the user know it's coming. Otherwise the restart is confusing."  So while a hold that
 * will restart the machine is counting - the right flipper with no game on, or BACK in a game - a
 * ring fills in the middle of the screen over the game's own picture, "HOLD FOR BOOT MENU" under
 * it, and once the hold has fired "RESTARTING TO BOOT MENU" until the game is gone.
 *
 * HOW.  This object is preloaded into the game, so the game's eglSwapBuffers is this one: just
 * before the game's frame goes out a quad is drawn over it with a program of our own, every piece
 * of GL state touched saved first and put back after, and the frame goes on to the real
 * eglSwapBuffers (RTLD_NEXT: libEGL, or the mode runtime's when a mode card re-points the slot -
 * it calls on to this one).  GL is looked up by name at the first frame, from the libraries the
 * game already has loaded: nothing new is linked.  Nothing is drawn unless a hold has been counting
 * RING_SHOW_MS, a second (half the hold if that is shorter), and then starts empty and fills over the rest - a
 * flipper tap in attract or a BACK press in the service menu never flashes it - and a program that does not compile
 * turns the ring off for good, the frames untouched.  PADMENU_RING=0 turns it off. */
typedef unsigned int GLuint_;
typedef int GLint_;
#define R_GL_BLEND 0x0BE2
#define R_GL_CULL_FACE 0x0B44
#define R_GL_DEPTH_TEST 0x0B71
#define R_GL_SCISSOR_TEST 0x0C11
#define R_GL_STENCIL_TEST 0x0B90
#define R_GL_VIEWPORT 0x0BA2
#define R_GL_COLOR_WRITEMASK 0x0C23
#define R_GL_BLEND_SRC_RGB 0x80C9
#define R_GL_BLEND_DST_RGB 0x80C8
#define R_GL_BLEND_SRC_ALPHA 0x80CB
#define R_GL_BLEND_DST_ALPHA 0x80CA
#define R_GL_BLEND_EQUATION_RGB 0x8009
#define R_GL_BLEND_EQUATION_ALPHA 0x883D
#define R_GL_FUNC_ADD 0x8006
#define R_GL_CURRENT_PROGRAM 0x8B8D
#define R_GL_ARRAY_BUFFER 0x8892
#define R_GL_ARRAY_BUFFER_BINDING 0x8894
#define R_GL_FRAMEBUFFER 0x8D40
#define R_GL_FRAMEBUFFER_BINDING 0x8CA6
#define R_GL_VERTEX_ATTRIB_ARRAY_ENABLED 0x8622
#define R_GL_VERTEX_ATTRIB_ARRAY_SIZE 0x8623
#define R_GL_VERTEX_ATTRIB_ARRAY_STRIDE 0x8624
#define R_GL_VERTEX_ATTRIB_ARRAY_TYPE 0x8625
#define R_GL_VERTEX_ATTRIB_ARRAY_NORMALIZED 0x886A
#define R_GL_VERTEX_ATTRIB_ARRAY_POINTER 0x8645
#define R_GL_VERTEX_ATTRIB_ARRAY_BUFFER_BINDING 0x889F
#define R_GL_FLOAT 0x1406
#define R_GL_STREAM_DRAW 0x88E0
#define R_GL_TRIANGLES 0x0004
#define R_GL_SRC_ALPHA 0x0302
#define R_GL_ONE_MINUS_SRC_ALPHA 0x0303
#define R_GL_VERTEX_SHADER 0x8B31
#define R_GL_FRAGMENT_SHADER 0x8B30
#define R_GL_COMPILE_STATUS 0x8B81
#define R_GL_LINK_STATUS 0x8B82
#define R_EGL_WIDTH 0x3057
#define R_EGL_HEIGHT 0x3056
#define RING_SHOW_MS 1000                 /* David: "shouldn't start to animate until being held for like a second" */

static struct {
    void (*GetIntegerv)(unsigned, GLint_ *);
    unsigned char (*IsEnabled)(unsigned);
    void (*Enable)(unsigned), (*Disable)(unsigned);
    void (*GetBooleanv)(unsigned, unsigned char *);
    void (*ColorMask)(unsigned char, unsigned char, unsigned char, unsigned char);
    void (*BlendFuncSeparate)(unsigned, unsigned, unsigned, unsigned);
    void (*BlendEquationSeparate)(unsigned, unsigned);
    void (*Viewport)(GLint_, GLint_, GLint_, GLint_);
    void (*UseProgram)(GLuint_);
    void (*BindBuffer)(unsigned, GLuint_);
    void (*GenBuffers)(GLint_, GLuint_ *);
    void (*BufferData)(unsigned, long, const void *, unsigned);
    void (*BindFramebuffer)(unsigned, GLuint_);
    void (*GetVertexAttribiv)(GLuint_, unsigned, GLint_ *);
    void (*GetVertexAttribPointerv)(GLuint_, unsigned, void **);
    void (*VertexAttribPointer)(GLuint_, GLint_, unsigned, unsigned char, GLint_, const void *);
    void (*EnableVertexAttribArray)(GLuint_), (*DisableVertexAttribArray)(GLuint_);
    void (*DrawArrays)(unsigned, GLint_, GLint_);
    GLuint_ (*CreateShader)(unsigned);
    void (*ShaderSource)(GLuint_, GLint_, const char *const *, const GLint_ *);
    void (*CompileShader)(GLuint_);
    void (*GetShaderiv)(GLuint_, unsigned, GLint_ *);
    GLuint_ (*CreateProgram)(void);
    void (*AttachShader)(GLuint_, GLuint_);
    void (*BindAttribLocation)(GLuint_, GLuint_, const char *);
    void (*LinkProgram)(GLuint_);
    void (*GetProgramiv)(GLuint_, unsigned, GLint_ *);
    GLint_ (*GetUniformLocation)(GLuint_, const char *);
    void (*Uniform4f)(GLint_, float, float, float, float);
    void (*Uniform1f)(GLint_, float);
    unsigned (*QuerySurface)(void *, void *, GLint_, GLint_ *);
} gl;
static int ring_state = -1;                /* -1 not tried, 0 off for good, 1 ready */
static GLuint_ ring_prog, ring_buf;     /* our program, and our own vertex buffer (PAD's emulator bridge takes
                                          * vertices from a buffer only; the GPU either way) */
static GLint_ u_c, u_p, u_col;

static int ring_load(void)
{
#define RL(f, n) if (!(*(void **)&gl.f = dlsym(RTLD_DEFAULT, n))) { tr("hold ring: no %s - off", n); return 0; }
    RL(GetIntegerv, "glGetIntegerv") RL(IsEnabled, "glIsEnabled") RL(Enable, "glEnable") RL(Disable, "glDisable")
    RL(BlendFuncSeparate, "glBlendFuncSeparate") RL(Viewport, "glViewport") RL(UseProgram, "glUseProgram")
    RL(BindBuffer, "glBindBuffer") RL(GenBuffers, "glGenBuffers") RL(BufferData, "glBufferData")
    RL(BindFramebuffer, "glBindFramebuffer")
    RL(VertexAttribPointer, "glVertexAttribPointer") RL(EnableVertexAttribArray, "glEnableVertexAttribArray")
    RL(DisableVertexAttribArray, "glDisableVertexAttribArray") RL(DrawArrays, "glDrawArrays")
    RL(CreateShader, "glCreateShader") RL(ShaderSource, "glShaderSource") RL(CompileShader, "glCompileShader")
    RL(GetShaderiv, "glGetShaderiv") RL(CreateProgram, "glCreateProgram") RL(AttachShader, "glAttachShader")
    RL(BindAttribLocation, "glBindAttribLocation") RL(LinkProgram, "glLinkProgram") RL(GetProgramiv, "glGetProgramiv")
    RL(GetUniformLocation, "glGetUniformLocation") RL(Uniform4f, "glUniform4f") RL(Uniform1f, "glUniform1f")
#undef RL
    /* the machine's libGLESv2 has every one; PAD's emulator bridge only what the game itself calls, so these few are
     * put back when there and left alone when not (the game never sets what it cannot call) */
#define RO(f, n) *(void **)&gl.f = dlsym(RTLD_DEFAULT, n);
    RO(GetBooleanv, "glGetBooleanv") RO(ColorMask, "glColorMask") RO(BlendEquationSeparate, "glBlendEquationSeparate")
    RO(GetVertexAttribiv, "glGetVertexAttribiv") RO(GetVertexAttribPointerv, "glGetVertexAttribPointerv")
    RO(QuerySurface, "eglQuerySurface")                                   /* else the viewport's size */
#undef RO
    if (!gl.GetBooleanv)
        gl.ColorMask = NULL;
    if (!gl.GetVertexAttribPointerv)
        gl.GetVertexAttribiv = NULL;
    return 1;
}

static const char RING_VS[] =
    "attribute vec2 a_pos;\nvoid main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";
/* u_c: centre x, y and radius in pixels, w 1 = a plain colour (the words); u_p: how far, 0..1 */
static const char RING_FS[] =
    "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n#else\nprecision mediump float;\n#endif\n"
    "uniform vec4 u_c; uniform float u_p; uniform vec4 u_col;\n"
    "void main() {\n"
    "  if (u_c.w > 0.5) { gl_FragColor = u_col; return; }\n"
    "  vec2 d = gl_FragCoord.xy - u_c.xy; float r = length(d) / u_c.z;\n"
    "  if (r > 1.0) discard;\n"
    "  float f = atan(d.x, d.y) / 6.2831853; if (f < 0.0) f += 1.0;\n"      /* 0 at the top, clockwise */
    "  float px = 1.0 / u_c.z;\n"
    "  float band = smoothstep(0.66 - px, 0.66 + px, r) * (1.0 - smoothstep(0.90 - px, 0.90 + px, r));\n"
    "  vec4 track = f <= u_p ? u_col : vec4(1.0, 1.0, 1.0, 0.28);\n"
    "  vec4 c = mix(vec4(0.0, 0.0, 0.0, 0.62), vec4(track.rgb, max(track.a, 0.62)), band);\n"
    "  c.a *= 1.0 - smoothstep(1.0 - 2.0 * px, 1.0, r);\n"
    "  gl_FragColor = c;\n"
    "}\n";

static GLuint_ ring_shader(unsigned kind, const char *src)
{
    GLint_ ok = 0;
    GLuint_ s = gl.CreateShader(kind);
    gl.ShaderSource(s, 1, &src, NULL);
    gl.CompileShader(s);
    gl.GetShaderiv(s, R_GL_COMPILE_STATUS, &ok);
    return ok ? s : 0;
}

static int ring_build(void)
{
    GLint_ ok = 0;
    GLuint_ vs, fs;
    if (!ring_load())
        return 0;
    vs = ring_shader(R_GL_VERTEX_SHADER, RING_VS);
    fs = ring_shader(R_GL_FRAGMENT_SHADER, RING_FS);
    if (!vs || !fs) {
        tr("hold ring: a shader did not compile - off");
        return 0;
    }
    ring_prog = gl.CreateProgram();
    gl.AttachShader(ring_prog, vs);
    gl.AttachShader(ring_prog, fs);
    gl.BindAttribLocation(ring_prog, 0, "a_pos");
    gl.LinkProgram(ring_prog);
    gl.GetProgramiv(ring_prog, R_GL_LINK_STATUS, &ok);
    if (!ok) {
        tr("hold ring: the program did not link - off");
        return 0;
    }
    u_c = gl.GetUniformLocation(ring_prog, "u_c");
    u_p = gl.GetUniformLocation(ring_prog, "u_p");
    u_col = gl.GetUniformLocation(ring_prog, "u_col");
    gl.GenBuffers(1, &ring_buf);
    tr("hold ring: ready");
    return 1;
}

/* the words: 5x7 capitals, a row a byte (bit 4 the left column), only the letters said */
static const struct { char c; unsigned char row[7]; } RING_FONT[] = {
    { 'A', { 14, 17, 17, 31, 17, 17, 17 } }, { 'B', { 30, 17, 17, 30, 17, 17, 30 } },
    { 'D', { 30, 17, 17, 17, 17, 17, 30 } }, { 'E', { 31, 16, 16, 30, 16, 16, 31 } },
    { 'F', { 31, 16, 16, 30, 16, 16, 16 } }, { 'G', { 14, 17, 16, 23, 17, 17, 15 } },
    { 'H', { 17, 17, 17, 31, 17, 17, 17 } }, { 'I', { 14, 4, 4, 4, 4, 4, 14 } },
    { 'L', { 16, 16, 16, 16, 16, 16, 31 } }, { 'M', { 17, 27, 21, 21, 17, 17, 17 } },
    { 'N', { 17, 17, 25, 21, 19, 17, 17 } }, { 'O', { 14, 17, 17, 17, 17, 17, 14 } },
    { 'R', { 30, 17, 17, 30, 20, 18, 17 } }, { 'S', { 15, 16, 16, 14, 1, 1, 30 } },
    { 'T', { 31, 4, 4, 4, 4, 4, 4 } }, { 'U', { 17, 17, 17, 17, 17, 17, 14 } },
};
static float ring_v[24 * 35 * 12];

/* the words centred at (cx, top) in pixels, cell px a dot: the triangles, in clip space */
static int ring_words(const char *s, float cx, float top, float cell, float w, float h)
{
    int n = 0, len = (int)strlen(s), i, r, b;
    float x0 = cx - (len * 6 - 1) * cell / 2;
    for (i = 0; i < len && i < 24; i++) {
        const unsigned char *rows = NULL;
        size_t k;
        for (k = 0; k < sizeof RING_FONT / sizeof RING_FONT[0]; k++)
            if (RING_FONT[k].c == s[i])
                rows = RING_FONT[k].row;
        if (!rows)
            continue;
        for (r = 0; r < 7; r++)
            for (b = 0; b < 5; b++)
                if (rows[r] & (16 >> b)) {
                    float xa = (x0 + (i * 6 + b) * cell) / w * 2 - 1, xb = xa + cell / w * 2;
                    float ya = 1 - (top + r * cell) / h * 2, yb = ya - cell / h * 2;
                    float q[12] = { xa, ya, xb, ya, xa, yb, xb, ya, xb, yb, xa, yb };
                    memcpy(ring_v + n * 2, q, sizeof q);
                    n += 6;
                }
    }
    return n;
}

/* how far the hold that is counting has got: 0..1, 2 once it has fired, -1 nothing to show */
static double ring_part(long long held, long hold)       /* after the wait, empty to full over the rest */
{
    long wait = hold / 2 < RING_SHOW_MS ? hold / 2 : RING_SHOW_MS;
    return held < wait ? -1 : (double)(held - wait) / (hold - wait);
}

static double ring_how_far(long long t)
{
    double p = -1, q;
    long long s = held_since;              /* BACK, in a game */
    if (fired)
        return 2;
    if (s >= 0 && hold_ms > 0 && t - last_sample < GAP_MS && (p = ring_part(t - s, hold_ms)) >= 0)
        ring_who = "BACK";
    if (flip_was == 1 && t - flip_last < GAP_MS) {
        ring_who = "the right flipper";
        if (flip_fired)
            return 2;
        s = flip_since;
        if (s >= 0 && flip_hold_cur > 0 && (q = ring_part(t - s, flip_hold_cur)) > p)
            p = q;
        else if (p >= 0)
            ring_who = "BACK";
    }
    return p < 0 ? -1 : p > 1 ? 1 : p;
}

static void ring_draw(void *dpy, void *surf, double p)
{
    GLint_ prog, abuf, fb, vp[4], en = 0, size = 4, stride = 0, type = R_GL_FLOAT, norm = 0, vbuf = 0;
    GLint_ bsr, bdr, bsa, bda, ber = R_GL_FUNC_ADD, bea = R_GL_FUNC_ADD, w = 0, h = 0, n;
    unsigned char cm[4] = { 1, 1, 1, 1 }, blend, cull, depth, sc, st;
    void *ptr = NULL;
    float cx, cy, rad, cell, tw, x0, x1, y0, y1;
    const char *words;
    static const float quad[12] = { -1, -1, 1, -1, -1, 1, 1, -1, 1, 1, -1, 1 };
    gl.GetIntegerv(R_GL_CURRENT_PROGRAM, &prog);
    gl.GetIntegerv(R_GL_ARRAY_BUFFER_BINDING, &abuf);
    gl.GetIntegerv(R_GL_FRAMEBUFFER_BINDING, &fb);
    gl.GetIntegerv(R_GL_VIEWPORT, vp);
    if (gl.ColorMask)
        gl.GetBooleanv(R_GL_COLOR_WRITEMASK, cm);
    gl.GetIntegerv(R_GL_BLEND_SRC_RGB, &bsr); gl.GetIntegerv(R_GL_BLEND_DST_RGB, &bdr);
    gl.GetIntegerv(R_GL_BLEND_SRC_ALPHA, &bsa); gl.GetIntegerv(R_GL_BLEND_DST_ALPHA, &bda);
    if (gl.BlendEquationSeparate) {
        gl.GetIntegerv(R_GL_BLEND_EQUATION_RGB, &ber);
        gl.GetIntegerv(R_GL_BLEND_EQUATION_ALPHA, &bea);
    }
    blend = gl.IsEnabled(R_GL_BLEND); cull = gl.IsEnabled(R_GL_CULL_FACE); depth = gl.IsEnabled(R_GL_DEPTH_TEST);
    sc = gl.IsEnabled(R_GL_SCISSOR_TEST); st = gl.IsEnabled(R_GL_STENCIL_TEST);
    if (gl.GetVertexAttribiv) {
        gl.GetVertexAttribiv(0, R_GL_VERTEX_ATTRIB_ARRAY_ENABLED, &en);
        gl.GetVertexAttribiv(0, R_GL_VERTEX_ATTRIB_ARRAY_SIZE, &size);
        gl.GetVertexAttribiv(0, R_GL_VERTEX_ATTRIB_ARRAY_STRIDE, &stride);
        gl.GetVertexAttribiv(0, R_GL_VERTEX_ATTRIB_ARRAY_TYPE, &type);
        gl.GetVertexAttribiv(0, R_GL_VERTEX_ATTRIB_ARRAY_NORMALIZED, &norm);
        gl.GetVertexAttribiv(0, R_GL_VERTEX_ATTRIB_ARRAY_BUFFER_BINDING, &vbuf);
        gl.GetVertexAttribPointerv(0, R_GL_VERTEX_ATTRIB_ARRAY_POINTER, &ptr);
    }

    gl.BindFramebuffer(R_GL_FRAMEBUFFER, 0);
    if (!gl.QuerySurface || !gl.QuerySurface(dpy, surf, R_EGL_WIDTH, &w) || !gl.QuerySurface(dpy, surf, R_EGL_HEIGHT, &h)
            || w <= 0 || h <= 0) {
        w = vp[2];
        h = vp[3];
    }
    if (w > 0 && h > 0) {
        gl.Viewport(0, 0, w, h);
        if (gl.ColorMask)
            gl.ColorMask(1, 1, 1, 1);
        gl.Disable(R_GL_CULL_FACE); gl.Disable(R_GL_DEPTH_TEST); gl.Disable(R_GL_SCISSOR_TEST); gl.Disable(R_GL_STENCIL_TEST);
        gl.Enable(R_GL_BLEND);
        gl.BlendFuncSeparate(R_GL_SRC_ALPHA, R_GL_ONE_MINUS_SRC_ALPHA, R_GL_SRC_ALPHA, R_GL_ONE_MINUS_SRC_ALPHA);
        if (gl.BlendEquationSeparate)
            gl.BlendEquationSeparate(R_GL_FUNC_ADD, R_GL_FUNC_ADD);
        gl.UseProgram(ring_prog);
        gl.BindBuffer(R_GL_ARRAY_BUFFER, ring_buf);
        gl.EnableVertexAttribArray(0);
        rad = h * 0.13f;
        cx = w / 2.0f;
        cy = h / 2.0f;
        cell = h / 150.0f;
        if (cell < 2)
            cell = 2;
        words = p > 1 ? "RESTARTING TO BOOT MENU" : "HOLD FOR BOOT MENU";
        /* a dark panel behind the ring and the words, so they read over any picture */
        tw = (strlen(words) * 6 - 1) * cell;
        if (tw < 2 * rad)
            tw = 2 * rad;
        x0 = (cx - tw / 2 - 4 * cell) / w * 2 - 1;
        x1 = (cx + tw / 2 + 4 * cell) / w * 2 - 1;
        y0 = 1 - (h / 2.0f - rad - 4 * cell) / h * 2;
        y1 = 1 - (h / 2.0f + rad + 14 * cell) / h * 2;
        {
            const float panel[12] = { x0, y0, x1, y0, x0, y1, x1, y0, x1, y1, x0, y1 };
            gl.Uniform4f(u_c, 0, 0, 0, 1);
            gl.Uniform4f(u_col, 0.04f, 0.05f, 0.07f, 0.80f);
            gl.BufferData(R_GL_ARRAY_BUFFER, sizeof panel, panel, R_GL_STREAM_DRAW);
            gl.VertexAttribPointer(0, 2, R_GL_FLOAT, 0, 0, (const void *)0);
            gl.DrawArrays(R_GL_TRIANGLES, 0, 6);
        }
        /* the ring: one quad over the screen, the shader keeps the disc */
        gl.Uniform4f(u_c, cx, cy, rad, 0);
        gl.Uniform1f(u_p, p > 1 ? 1.0f : (float)p);
        gl.Uniform4f(u_col, 1.0f, 0.77f, 0.18f, 1.0f);           /* the menu's own amber, ffc42d */
        gl.BufferData(R_GL_ARRAY_BUFFER, sizeof quad, quad, R_GL_STREAM_DRAW);
        gl.VertexAttribPointer(0, 2, R_GL_FLOAT, 0, 0, (const void *)0);
        gl.DrawArrays(R_GL_TRIANGLES, 0, 6);
        /* the words under it, on a shadow */
        n = ring_words(words, cx + cell * 0.6f,
                       h - cy + rad + cell * 3.6f, cell, (float)w, (float)h);
        gl.Uniform4f(u_c, 0, 0, 0, 1);
        gl.Uniform4f(u_col, 0, 0, 0, 0.85f);
        gl.BufferData(R_GL_ARRAY_BUFFER, (long)n * 2 * sizeof(float), ring_v, R_GL_STREAM_DRAW);
        gl.DrawArrays(R_GL_TRIANGLES, 0, n);
        n = ring_words(words, cx, h - cy + rad + cell * 3,
                       cell, (float)w, (float)h);
        gl.Uniform4f(u_col, 1, 1, 1, 1);
        gl.BufferData(R_GL_ARRAY_BUFFER, (long)n * 2 * sizeof(float), ring_v, R_GL_STREAM_DRAW);
        gl.DrawArrays(R_GL_TRIANGLES, 0, n);
    }

    if (gl.GetVertexAttribiv) {
        gl.BindBuffer(R_GL_ARRAY_BUFFER, (GLuint_)vbuf);   /* its pointer, on its own buffer */
        gl.VertexAttribPointer(0, size, (unsigned)type, (unsigned char)norm, stride, ptr);
        if (!en)
            gl.DisableVertexAttribArray(0);
    }
    gl.BindBuffer(R_GL_ARRAY_BUFFER, (GLuint_)abuf);
    gl.UseProgram((GLuint_)prog);
    gl.BlendFuncSeparate((unsigned)bsr, (unsigned)bdr, (unsigned)bsa, (unsigned)bda);
    if (gl.BlendEquationSeparate)
        gl.BlendEquationSeparate((unsigned)ber, (unsigned)bea);
    (blend ? gl.Enable : gl.Disable)(R_GL_BLEND);
    (cull ? gl.Enable : gl.Disable)(R_GL_CULL_FACE);
    (depth ? gl.Enable : gl.Disable)(R_GL_DEPTH_TEST);
    (sc ? gl.Enable : gl.Disable)(R_GL_SCISSOR_TEST);
    (st ? gl.Enable : gl.Disable)(R_GL_STENCIL_TEST);
    if (gl.ColorMask)
        gl.ColorMask(cm[0], cm[1], cm[2], cm[3]);
    gl.Viewport(vp[0], vp[1], vp[2], vp[3]);
    gl.BindFramebuffer(R_GL_FRAMEBUFFER, (GLuint_)fb);
}

unsigned eglSwapBuffers(void *dpy, void *surf)
{
    static unsigned (*next)(void *, void *);
    static int said;
    static long long shown_at;
    double p;
    if (!next && !(next = (unsigned (*)(void *, void *))dlsym(RTLD_NEXT, "eglSwapBuffers")))
        return 0;
    if (ring_state != 0 && (p = ring_how_far(now_ms())) >= 0) {
        if (ring_state < 0) {
            tr("hold ring: first shown, for %s", ring_who);
            const char *e = getenv("PADMENU_RING");
            ring_state = (e && !strcmp(e, "0")) ? 0 : ring_build();
        }
        if (ring_state == 1) {
            if (said != (p > 1 ? 2 : 1))
                tr("hold ring: %s (%s)", p > 1 ? "restarting" : "filling", ring_who);
            if (!said)
                shown_at = now_ms();
            said = p > 1 ? 2 : 1;
            ring_draw(dpy, surf, p);
        }
    } else {
        if (said)
            tr("hold ring: gone after %lld ms", now_ms() - shown_at);
        said = 0;
    }
    return next(dpy, surf);
}
#else
static void nb_forget(int fd) { (void)fd; }
static void flip_init(const char *conf) { (void)conf; }
#endif

/* <key>=<value> in an images.conf (the last one wins): 1 and the value, trimmed; 0 when the file or the line
 * is not there */
static int conf_word(const char *path, const char *key, char *out, size_t outlen)
{
    FILE *f;
    char line[256];
    size_t k = strlen(key);
    int got = 0;
    if (!path || !*path || !(f = fopen(path, "r")))
        return 0;
    while (fgets(line, sizeof line, f)) {
        const char *p = line;
        size_t n = 0;
        while (*p == ' ' || *p == '\t')
            p++;
        if (strncmp(p, key, k))
            continue;
        p += k;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p != '=')
            continue;
        p++;
        while (*p == ' ' || *p == '\t')
            p++;
        while (p[n] && p[n] != '\r' && p[n] != '\n' && p[n] != ' ' && p[n] != '\t' && n + 1 < outlen) {
            out[n] = p[n];
            n++;
        }
        out[n] = 0;
        got = 1;
    }
    fclose(f);
    return got;
}

/* back_hold=<seconds> in an images.conf -> ms, or -1 when the file or the line is not there */
static long conf_hold_ms(const char *path)
{
    char w[32];
    long v = 0;
    const char *p = w;
    if (!conf_word(path, "back_hold", w, sizeof w) || *p < '0' || *p > '9')
        return -1;
    while (*p >= '0' && *p <= '9' && v < 1000)
        v = v * 10 + (*p++ - '0');
    return v * 1000;
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
    flip_init(c && *c ? c : CONF_PATH);
    /* the game's own children (system()) inherit LD_PRELOAD: nothing here for them */
    unsetenv("PADMENU_HOLD_MS");
    unsetenv("PADMENU_CONF");
}
