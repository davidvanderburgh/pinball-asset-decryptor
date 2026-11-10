/* s3spid - a userspace SPI device (CUSE) standing in for a Spike 3 CPU-board
 * SPI peripheral, so the game's `/dev/spidev4.0` opens and its transfers can
 * be seen and answered (PAD-1090).
 *
 *   s3spid -f --name=pad-spidev4.0 [--log=FILE]      (root; cuse.ko loaded)
 *
 * The kernel's CUSE driver makes /dev/<name> a real character device whose
 * open/read/write/ioctl come here; s3run.sh binds it over the chroot's
 * /dev/spidev4.0. The game's spidev ioctls reach the host through the
 * qemu-spi-ioctls.patch translation, already pointing at host memory, so the
 * nested SPI_IOC_MESSAGE buffers are fetched with CUSE's ioctl retry.
 *
 * Every transfer is logged as one line: time, tx bytes, rx bytes. Every rx
 * byte is --idle (default 0x00): the inputs at rest.
 *
 * Build: gcc -O2 -Wall -o s3spid s3spid.c $(pkg-config --cflags --libs fuse3)
 */
#define FUSE_USE_VERSION 31
#include <cuse_lowlevel.h>
#include <fuse_opt.h>
#include <errno.h>
#include <linux/spi/spidev.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/uio.h>
#include <time.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static FILE *logf;
static int idle = 0x00;            /* --idle=0xNN: every rx byte */
/* --input=FILE: the inputs LIVE - the file's bytes are the rx bytes of
 * every transfer (byte k of a transfer = byte k of the file, up to its
 * length), re-read through a shared mapping, so a button is pressed by
 * writing the file (s3press.py) while the game runs */
static volatile unsigned char *live;
static unsigned live_len;
static uint8_t mode = 0, lsb = 0, bits = 8;
static uint32_t speed = 1000000, mode32 = 0;
static struct timespec t0;
static unsigned long nxfer;

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
}

static void hexlog(const char *tag, const uint8_t *b, size_t n)
{
    size_t i, show = n > 64 ? 64 : n;
    fprintf(logf, " %s[%zu]", tag, n);
    for (i = 0; i < show; i++)
        fprintf(logf, "%s%02x", i ? "" : " ", b[i]);
    if (show < n)
        fprintf(logf, "..");
}

static void s_open(fuse_req_t req, struct fuse_file_info *fi)
{
    fprintf(logf, "%9.3f open\n", now());
    fuse_reply_open(req, fi);
}

static void s_release(fuse_req_t req, struct fuse_file_info *fi)
{
    (void)fi;
    fprintf(logf, "%9.3f close\n", now());
    fuse_reply_err(req, 0);
}

static void s_read(fuse_req_t req, size_t size, off_t off, struct fuse_file_info *fi)
{
    (void)off; (void)fi;
    uint8_t *b = calloc(1, size ? size : 1);
    fprintf(logf, "%9.3f read %zu\n", now(), size);
    fuse_reply_buf(req, (char *)b, size);
    free(b);
}

static void s_write(fuse_req_t req, const char *buf, size_t size, off_t off,
                    struct fuse_file_info *fi)
{
    (void)off; (void)fi;
    fprintf(logf, "%9.3f write", now());
    hexlog("tx", (const uint8_t *)buf, size);
    fputc('\n', logf);
    fuse_reply_write(req, size);
}

/* a 1- or 4-byte setting: RD answers it, WR takes it */
static int setting(fuse_req_t req, unsigned cmd, void *arg, const void *in,
                   size_t insz, size_t outsz, void *val, size_t vsz, const char *name)
{
    struct iovec iov = { arg, vsz };
    if (_IOC_DIR(cmd) & _IOC_WRITE) {
        if (insz < vsz) {
            fuse_reply_ioctl_retry(req, &iov, 1, NULL, 0);
            return 1;
        }
        memcpy(val, in, vsz);
        fprintf(logf, "%9.3f set %s = %u\n", now(), name,
                vsz == 1 ? *(uint8_t *)val : *(uint32_t *)val);
        fuse_reply_ioctl(req, 0, NULL, 0);
    } else {
        if (outsz < vsz) {
            fuse_reply_ioctl_retry(req, NULL, 0, &iov, 1);
            return 1;
        }
        fuse_reply_ioctl(req, 0, val, vsz);
    }
    return 1;
}

static void s_ioctl(fuse_req_t req, int icmd, void *arg, struct fuse_file_info *fi,
                    unsigned flags, const void *in, size_t insz, size_t outsz)
{
    unsigned cmd = (unsigned)icmd;
    (void)fi; (void)flags;

    switch (cmd) {
    case SPI_IOC_RD_MODE: case SPI_IOC_WR_MODE:
        setting(req, cmd, arg, in, insz, outsz, &mode, 1, "mode"); return;
    case SPI_IOC_RD_LSB_FIRST: case SPI_IOC_WR_LSB_FIRST:
        setting(req, cmd, arg, in, insz, outsz, &lsb, 1, "lsb_first"); return;
    case SPI_IOC_RD_BITS_PER_WORD: case SPI_IOC_WR_BITS_PER_WORD:
        setting(req, cmd, arg, in, insz, outsz, &bits, 1, "bits_per_word"); return;
    case SPI_IOC_RD_MAX_SPEED_HZ: case SPI_IOC_WR_MAX_SPEED_HZ:
        setting(req, cmd, arg, in, insz, outsz, &speed, 4, "max_speed_hz"); return;
    case SPI_IOC_RD_MODE32: case SPI_IOC_WR_MODE32:
        setting(req, cmd, arg, in, insz, outsz, &mode32, 4, "mode32"); return;
    }

    if (_IOC_TYPE(cmd) == SPI_IOC_MAGIC && _IOC_NR(cmd) == 0 &&
        _IOC_DIR(cmd) == _IOC_WRITE) {
        size_t n = _IOC_SIZE(cmd) / sizeof(struct spi_ioc_transfer), i;
        size_t arr = n * sizeof(struct spi_ioc_transfer), txsum = 0, rxsum = 0;
        const struct spi_ioc_transfer *t = in;
        struct iovec inv[17], outv[16];
        int ni = 0, no = 0;

        if (n == 0 || n > 16) {
            fuse_reply_err(req, EINVAL);
            return;
        }
        if (insz < arr) {                       /* 1: the transfer array */
            struct iovec iov = { arg, arr };
            fuse_reply_ioctl_retry(req, &iov, 1, NULL, 0);
            return;
        }
        for (i = 0; i < n; i++) {
            if (t[i].tx_buf) txsum += t[i].len;
            if (t[i].rx_buf) rxsum += t[i].len;
        }
        /* 2: the buffers. After it, `in` is longer than the array (tx data)
         * or `out` is non-empty (rx room), so this can't match twice. */
        if ((txsum || rxsum) && insz == arr && outsz == 0) {
            inv[ni].iov_base = arg; inv[ni++].iov_len = arr;
            for (i = 0; i < n; i++) {
                if (t[i].tx_buf && t[i].len) {
                    inv[ni].iov_base = (void *)(uintptr_t)t[i].tx_buf;
                    inv[ni++].iov_len = t[i].len;
                }
                if (t[i].rx_buf && t[i].len) {
                    outv[no].iov_base = (void *)(uintptr_t)t[i].rx_buf;
                    outv[no++].iov_len = t[i].len;
                }
            }
            fuse_reply_ioctl_retry(req, inv, ni, no ? outv : NULL, no);
            return;
        }
        /* 3: answer. tx data follows the array in `in`, in transfer order. */
        {
            const uint8_t *tx = (const uint8_t *)in + arr;
            uint8_t *rx = malloc(rxsum ? rxsum : 1), *rp = rx;
            memset(rx, idle, rxsum ? rxsum : 1);
            if (live) {                 /* each transfer's rx from the file */
                size_t q = 0, j;
                for (i = 0; i < n; i++)
                    if (t[i].rx_buf)
                        for (j = 0; j < t[i].len; j++, q++)
                            rx[q] = j < live_len ? live[j] : (uint8_t)idle;
            }
            size_t total = 0;
            /* LOGGED ON CHANGE: the chain is polled ~3000 times a second with
             * the same bytes, so a transfer whose tx and rx match the last
             * one only counts (a boot logged a million identical lines) */
            static uint8_t last[64];
            static size_t last_n;
            static unsigned long same;
            uint8_t cur[64];
            size_t cn = 0;
            const uint8_t *tp = tx, *rq = rx;
            int changed;
            for (i = 0; i < n && cn + 2 * (size_t)t[i].len <= sizeof cur; i++) {
                if (t[i].tx_buf) { memcpy(cur + cn, tp, t[i].len); cn += t[i].len; tp += t[i].len; }
                if (t[i].rx_buf) { memcpy(cur + cn, rq, t[i].len); cn += t[i].len; rq += t[i].len; }
            }
            changed = cn != last_n || memcmp(cur, last, cn);
            if (changed && same)
                fprintf(logf, "%9.3f   (%lu identical transfers)\n", now(), same);
            if (changed) { memcpy(last, cur, cn); last_n = cn; same = 0; } else same++;
            for (i = 0; i < n; i++) {
                if (changed) {
                    fprintf(logf, "%9.3f xfer#%lu.%zu len %u speed %u%s", now(), nxfer, i,
                            t[i].len, t[i].speed_hz, t[i].cs_change ? " cs_change" : "");
                    if (t[i].tx_buf && t[i].len) hexlog("tx", tx, t[i].len);
                    if (t[i].rx_buf && t[i].len) hexlog("rx", rp, t[i].len);
                    fputc('\n', logf);
                }
                if (t[i].tx_buf && t[i].len) tx += t[i].len;
                if (t[i].rx_buf && t[i].len) rp += t[i].len;
                total += t[i].len;
            }
            nxfer++;
            fuse_reply_ioctl(req, (int)total, rx, rxsum);
            free(rx);
        }
        return;
    }

    fprintf(logf, "%9.3f ioctl 0x%08x unknown\n", now(), cmd);
    fuse_reply_err(req, ENOTTY);
}

static const struct cuse_lowlevel_ops ops = {
    .open = s_open, .release = s_release, .read = s_read,
    .write = s_write, .ioctl = s_ioctl,
};

struct opts { char *name; char *log; char *idle; char *input; };
#define OPT(t, p) { t, offsetof(struct opts, p), 1 }
static const struct fuse_opt optspec[] = {
    OPT("--name=%s", name), OPT("--log=%s", log), OPT("--idle=%s", idle), OPT("--input=%s", input), FUSE_OPT_END
};

int main(int argc, char **argv)
{
    struct fuse_args args = FUSE_ARGS_INIT(argc, argv);
    struct opts o = { 0 };
    char devname[160];
    const char *dev_info_argv[] = { devname };
    struct cuse_info ci;

    if (fuse_opt_parse(&args, &o, optspec, NULL))
        return 1;
    snprintf(devname, sizeof(devname), "DEVNAME=%s", o.name ? o.name : "pad-spidev4.0");
    if (o.input) {
        int fd = open(o.input, O_RDONLY);
        struct stat sb;
        if (fd >= 0 && fstat(fd, &sb) == 0 && sb.st_size > 0) {
            void *m = mmap(0, (size_t)sb.st_size, PROT_READ, MAP_SHARED, fd, 0);
            if (m != MAP_FAILED) { live = m; live_len = (unsigned)sb.st_size; }
        }
        if (fd >= 0) close(fd);
    }
    if (o.idle)
        idle = (int)strtol(o.idle, NULL, 0) & 0xff;
    logf = o.log ? fopen(o.log, "w") : stderr;
    if (!logf) {
        perror(o.log);
        return 1;
    }
    setvbuf(logf, NULL, _IOLBF, 0);
    clock_gettime(CLOCK_MONOTONIC, &t0);
    fprintf(logf, "# s3spid %s\n", devname + 7);

    memset(&ci, 0, sizeof(ci));
    ci.dev_info_argc = 1;
    ci.dev_info_argv = dev_info_argv;
    ci.flags = CUSE_UNRESTRICTED_IOCTL;
    return cuse_lowlevel_main(args.argc, args.argv, &ci, &ops, NULL);
}
