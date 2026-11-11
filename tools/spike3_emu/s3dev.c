/* s3dev.c - the CPU board's two buses, answered INSIDE the game (PAD-1090).
 *
 * LD_PRELOAD (aarch64), beside s3kms/s3alsa/s3vid. It replaces three host-side
 * pieces that only a specially built PC had - so the Spike 3 rig runs on a
 * stock WSL kernel and stock qemu-user, for anyone who brings their card's
 * own OTP key:
 *
 *   /dev/spidev4.0   the cabinet inputs (SPI chain). Was s3spid.c, a CUSE
 *                    device, plus qemu-spi-ioctls.patch. Same answer here:
 *                    every SPI_IOC_MESSAGE transfer's rx is the slot's live
 *                    spi.in (PAD_S3_SPI_IN, bound at /run/padspi), byte for
 *                    byte, 0xff past its end - ACTIVE LOW, 0xff = at rest.
 *   /dev/i2c-10      the amp/EEPROM bus. Was the kernel's i2c-stub (not in a
 *                    stock WSL kernel) with this ticket's I2C_RDWR addition,
 *                    plus qemu-i2c-ioctls.patch. The SAME generic register
 *                    store, moved here unchanged: per chip address a 256-byte
 *                    register file and a pointer; a write's first byte sets
 *                    the pointer and the rest are stored (auto-increment); a
 *                    read returns stored bytes (auto-increment); every
 *                    address ACKs. Nothing in it knows any chip - it is the
 *                    stub's model, and the game's own driver supplies every
 *                    value it later reads back (MAX9850 init verifies them).
 *
 * The game opens both devices by path; open() here hands out a /dev/null fd
 * and remembers what it stands for, so the paths need not exist in the
 * chroot and no ioctl ever reaches qemu or a kernel. Only the calls the game
 * makes are answered (measured: SPI_IOC_MESSAGE(1) and the SPI settings,
 * I2C_SLAVE, I2C_FUNCS, I2C_RDWR); anything else on these fds is ENOTTY.
 * PAD_S3_DEV=0 leaves both alone (the old CUSE/i2c-stub path).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define MAXFD 4096
enum { NONE, SPI, I2C };
static unsigned char kind[MAXFD];
static unsigned short i2c_addr[MAXFD];

static int on(void)
{
    static int v = -1;
    if (v < 0) {
        const char *e = getenv("PAD_S3_DEV");
        v = !(e && e[0] == '0');
    }
    return v;
}

static int devkind(const char *path)
{
    if (!path || !on())
        return NONE;
    if (!strcmp(path, "/dev/spidev4.0"))
        return SPI;
    if (!strcmp(path, "/dev/i2c-10"))
        return I2C;
    return NONE;
}

static int stand_in(int k)
{
    int (*real_open)(const char *, int, ...) = dlsym(RTLD_NEXT, "open");
    int fd = real_open("/dev/null", O_RDWR | O_CLOEXEC);
    if (fd >= 0 && fd < MAXFD) {
        kind[fd] = (unsigned char)k;
        i2c_addr[fd] = 0;
        fprintf(stderr, "[s3dev] %s answered in the game (fd %d)\n",
                k == SPI ? "/dev/spidev4.0" : "/dev/i2c-10", fd);
    }
    return fd;
}

int open(const char *path, int flags, ...)
{
    int k = devkind(path), mode = 0;
    static int (*real)(const char *, int, ...);
    if (k)
        return stand_in(k);
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    if (!real)
        real = dlsym(RTLD_NEXT, "open");
    return real(path, flags, mode);
}
int open64(const char *path, int flags, ...) __attribute__((alias("open")));

int openat(int dirfd, const char *path, int flags, ...)
{
    int k = devkind(path), mode = 0;
    static int (*real)(int, const char *, int, ...);
    if (k)
        return stand_in(k);
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    if (!real)
        real = dlsym(RTLD_NEXT, "openat");
    return real(dirfd, path, flags, mode);
}
int openat64(int dirfd, const char *path, int flags, ...) __attribute__((alias("openat")));

int close(int fd)
{
    static int (*real)(int);
    if (fd >= 0 && fd < MAXFD)
        kind[fd] = NONE;
    if (!real)
        real = dlsym(RTLD_NEXT, "close");
    return real(fd);
}

/* ---- the SPI chain ---------------------------------------------------- */
struct spi_xfer {                 /* struct spi_ioc_transfer, 32 bytes */
    uint64_t tx_buf, rx_buf;
    uint32_t len, speed_hz;
    uint16_t delay_usecs;
    uint8_t bits_per_word, cs_change, tx_nbits, rx_nbits, word_delay_usecs, pad;
};
static uint8_t spi_mode, spi_lsb, spi_bits = 8;
static uint32_t spi_speed = 1000000, spi_mode32;

static int spi_live(uint8_t *buf, int max)
{
    static int fd = -2;
    if (fd == -2) {
        const char *p = getenv("PAD_S3_SPI_IN");
        int (*real_open)(const char *, int, ...) = dlsym(RTLD_NEXT, "open");
        fd = (p && *p) ? real_open(p, O_RDONLY | O_CLOEXEC) : -1;
        if (fd < 0)
            fprintf(stderr, "[s3dev] no cabinet inputs (PAD_S3_SPI_IN=%s): idle\n",
                    p ? p : "");
    }
    if (fd < 0)
        return 0;
    {
        ssize_t n = pread(fd, buf, (size_t)max, 0);
        return n > 0 ? (int)n : 0;
    }
}

/* PACE THE SPI CHAIN AS THE WIRE DOES (PAD-1090; Spike 2 learned it first:
 * hwshim.c spi_pace_us). The game reads the cabinet inputs in a loop with no
 * sleep of its own; on the machine each transfer takes its bits / clock, and
 * the game COUNTS TRANSFERS to time a held button - a held cabinet switch
 * auto-repeats in its menus by that count (padsw.h: on Spike 2's Main Menu
 * 120 and 200 ms moved the cursor 0 rows, 300 ms 3). Answered instantly, the
 * loop ran far faster than the wire, a 130 ms keypress counted as a long
 * hold, and one press of a flipper ran the Main Menu's highlight for 2.5 s
 * (David's recording) - while burning a core. So each message takes the time
 * the wire would: sum of len * bits / speed_hz (+ delay_usecs).
 * PAD_S3_SPI_US=<n> forces n us a message; PAD_S3_SPI_US=0 free-runs. */
static void spi_pace(uint64_t ns)
{
    static long fixed = -2;
    struct timespec ts;
    if (fixed == -2) {
        const char *p = getenv("PAD_S3_SPI_US");
        fixed = (p && *p) ? atol(p) : -1;
    }
    if (fixed >= 0)
        ns = (uint64_t)fixed * 1000;
    {
        static int said;
        if (!said) {
            said = 1;
            fprintf(stderr, "[s3dev] SPI paced as the wire: %llu us a message%s\n",
                    (unsigned long long)(ns / 1000), fixed >= 0 ? " (PAD_S3_SPI_US)" : "");
        }
    }
    if (!ns)
        return;
    ts.tv_sec = (time_t)(ns / 1000000000ull);
    ts.tv_nsec = (long)(ns % 1000000000ull);
    nanosleep(&ts, NULL);
}

static int spi_ioctl(unsigned long cmd, void *arg)
{
    unsigned nr = (cmd >> 0) & 0xff, type = (cmd >> 8) & 0xff;
    unsigned size = (cmd >> 16) & 0x3fff, dir = (cmd >> 30) & 3;
    void *val = NULL;
    unsigned vsz = 0;
    if (type != 'k') {
        errno = ENOTTY;
        return -1;
    }
    if (nr == 0) {                                     /* SPI_IOC_MESSAGE(n) */
        struct spi_xfer *t = arg;
        unsigned n = size / sizeof(*t), i, j, total = 0;
        uint8_t live[64];
        int live_len = spi_live(live, sizeof(live));
        uint64_t ns = 0;
        for (i = 0; i < n; i++) {
            uint8_t *rx = (uint8_t *)(uintptr_t)t[i].rx_buf;
            uint32_t hz = t[i].speed_hz ? t[i].speed_hz : spi_speed;
            unsigned bits = t[i].bits_per_word ? t[i].bits_per_word : (spi_bits ? spi_bits : 8);
            if (rx)
                for (j = 0; j < t[i].len; j++)
                    rx[j] = j < (unsigned)live_len ? live[j] : 0xff;
            total += t[i].len;
            if (hz)
                ns += (uint64_t)t[i].len * bits * 1000000000ull / hz;
            ns += (uint64_t)t[i].delay_usecs * 1000;
        }
        spi_pace(ns);
        return (int)total;
    }
    switch (nr) {                                      /* the settings */
    case 1: val = &spi_mode; vsz = 1; break;
    case 2: val = &spi_lsb; vsz = 1; break;
    case 3: val = &spi_bits; vsz = 1; break;
    case 4: val = &spi_speed; vsz = 4; break;
    case 5: val = &spi_mode32; vsz = 4; break;
    default:
        errno = ENOTTY;
        return -1;
    }
    if (dir & 1)                                       /* _IOC_WRITE */
        memcpy(val, arg, vsz);
    else
        memcpy(arg, val, vsz);
    return 0;
}

/* ---- the amp bus: i2c-stub's generic register store, unchanged --------- */
struct chip { uint8_t reg[256]; uint8_t ptr; };
static struct chip *chips[128];
/* the addresses s3run.sh loaded i2c-stub with; any other address ACKs and
 * reads zero, as the stub's I2C_RDWR addition did */
static const uint8_t chip_addr[] = { 0x10, 0x48, 0x4c, 0x4d, 0x4e, 0x50, 0x51, 0x52, 0x53 };

static struct chip *chip_at(unsigned a)
{
    unsigned k;
    if (a >= 128)
        return NULL;
    for (k = 0; k < sizeof(chip_addr); k++)
        if (chip_addr[k] == a) {
            if (!chips[a])
                chips[a] = calloc(1, sizeof(struct chip));
            return chips[a];
        }
    return NULL;
}

struct i2c_msg_a64 { uint16_t addr, flags, len, pad; uint8_t *buf; };
struct i2c_rdwr_a64 { struct i2c_msg_a64 *msgs; uint32_t nmsgs; };

static int i2c_ioctl(int fd, unsigned long cmd, void *arg)
{
    switch (cmd) {
    case 0x0703:                                       /* I2C_SLAVE */
    case 0x0706:                                       /* I2C_SLAVE_FORCE */
        i2c_addr[fd] = (unsigned short)(uintptr_t)arg;
        return 0;
    case 0x0705:                                       /* I2C_FUNCS */
        *(unsigned long *)arg = 0x0eff0001UL;           /* I2C + SMBus */
        return 0;
    case 0x0701: case 0x0702: case 0x0704: case 0x0708:
        return 0;                                      /* retries, timeout... */
    case 0x0707: {                                     /* I2C_RDWR */
        struct i2c_rdwr_a64 *d = arg;
        unsigned i, j;
        if (!d || !d->msgs || d->nmsgs == 0 || d->nmsgs > 42) {
            errno = EINVAL;
            return -1;
        }
        for (i = 0; i < d->nmsgs; i++) {
            struct i2c_msg_a64 *m = &d->msgs[i];
            struct chip *c = chip_at(m->addr);
            if (m->flags & 1) {                        /* I2C_M_RD */
                static uint8_t said_rd[128];
                if (!said_rd[m->addr & 127]) {         /* what the game reads, once each */
                    said_rd[m->addr & 127] = 1;
                    fprintf(stderr, "[s3dev] i2c 0x%02x: first read (%u bytes at 0x%02x)\n",
                            m->addr, m->len, c ? c->ptr : 0);
                }
                for (j = 0; j < m->len; j++)
                    m->buf[j] = c ? c->reg[c->ptr++] : 0;
            } else if (c && m->len > 0) {
                c->ptr = m->buf[0];
                for (j = 1; j < m->len; j++)
                    c->reg[c->ptr++] = m->buf[j];
            }
        }
        return (int)d->nmsgs;
    }
    }
    errno = ENOTTY;
    return -1;
}

int ioctl(int fd, unsigned long cmd, ...)
{
    static int (*real)(int, unsigned long, ...);
    va_list ap;
    void *arg;
    va_start(ap, cmd);
    arg = va_arg(ap, void *);
    va_end(ap);
    if (fd >= 0 && fd < MAXFD && kind[fd] == SPI)
        return spi_ioctl(cmd, arg);
    if (fd >= 0 && fd < MAXFD && kind[fd] == I2C)
        return i2c_ioctl(fd, cmd, arg);
    if (!real)
        real = dlsym(RTLD_NEXT, "ioctl");
    return real(fd, cmd, arg);
}
