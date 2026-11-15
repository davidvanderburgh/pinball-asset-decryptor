/* padmenu.c - back to the boot menu without switching the machine off (PAD-1309).
 *
 * A multi-boot card's menu (codeselect) runs once, at power-up, from
 * /etc/init.d/game, before the game starts.  To pick another game the operator
 * used to switch the machine off and on.  This object is preloaded into THE
 * GAME (the multi-boot form of the game_monitor hook, modehook.MENU_HOOK_LINES)
 * and gives the coin door a way back instead:
 *
 *     hold BACK on the coin door for HOLD_MS (5 s)
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
#ifdef PADMENU_S3
#define CMD_DEFAULT     ""
#define BACK_BYTE       0
#define CAB_DEV         "/dev/spidev4.0"
#else
#define CMD_DEFAULT     "/usr/local/codeselect/select.sh"
#define BACK_BYTE       1
#define CAB_DEV         "/dev/spidev1.0"
#endif
#ifndef O_TMPFILE
#define O_TMPFILE 0
#endif
#define HOLD_MS_DEFAULT 5000
#define SPI_MAGIC       0x6b            /* 'k', SPI_IOC_MAGIC */
#define MAX_FD          1024
#define BACK_BIT        3

typedef int (*ioctl_fn)(int, unsigned long, ...);
typedef int (*open_fn)(const char *, int, ...);
typedef int (*openat_fn)(int, const char *, int, ...);

static ioctl_fn real_ioctl;
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
    size_t n, k = strlen(CAB_DEV);
    if (!p)
        return 0;
    n = strlen(p);            /* a chroot's or a test's prefix is allowed: ends with it */
    return n >= k && !strcmp(p + n - k, CAB_DEV);
}

static void note_open(int fd, const char *path)
{
    if (fd >= 0 && fd < MAX_FD)
        fd_kind[fd] = is_cab_path(path) ? 1 : 0;
}

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
    if (fd >= 0 && fd < MAX_FD)
        fd_kind[fd] = 0;
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
                         getenv("PAD_GL_BRIDGE") || getenv("PAD_SW_SHM"))) {
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
        argv[2] = "sync; exec ${CODESELECT_REBOOT:-reboot}";
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

__attribute__((constructor))
static void padmenu_init(void)
{
    const char *h = getenv("PADMENU_HOLD_MS");
    hold_ms = h && *h ? strtol(h, NULL, 10) : HOLD_MS_DEFAULT;
    /* the game's own children (system()) inherit LD_PRELOAD: nothing here for them */
    unsetenv("PADMENU_HOLD_MS");
}
