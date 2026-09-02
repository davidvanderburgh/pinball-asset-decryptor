/* input_hw.c - the machine's buttons over the node bus and the cabinet SPI.
 *
 * Everything here is what the game itself does on the wire (godzilla_pro
 * 1.15.0 ELF, read_nodebus sections A-F): the tty setup, the RTS pulse, the
 * frame format, the unaddressed bring-up, the enumeration, the identity reads
 * and the 0x11 switch scan of node 8 (flippers) and node 1 (START and the
 * lockdown-bar Action button - two bits of the SAME reply, no extra traffic).
 * The cabinet word (Service Select/Plus/Minus/Back) is the 8-byte SPI transfer.
 *
 * Every ioctl/termios failure is logged and tolerated so the program still
 * runs on a pty (fakebus.py) or /dev/null. The first exchanges are logged in
 * hex so a hardware run leaves a diagnosis trail.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <termios.h>
#include <sys/ioctl.h>
#include <linux/serial.h>
#include <linux/spi/spidev.h>
#include "input.h"
#include "log.h"

#define NODE_FLIPPERS 8
#define NODE_START    1        /* START (bit 11) and the Action button (bit 2) */
#define SCAN_MS       25
#define SPI_MS        10
#define LOG_EXCHANGES 40       /* hex-log this many exchanges, then only changes */

struct hw {
    struct input base;
    int fd, spi;
    int logged;
    long long next_scan, next_spi;         /* sel_now_ms() deadlines: long long, see log.h */
    long long node_retry[2];               /* [0] node 8, [1] node 1: not before this time */
    int node_fail[2];
    unsigned char sw[2][8];
    int sw_valid[2];
    unsigned char cab[8];
    int cab_valid;
    int spi_logged;
};

static const struct input_ops hw_ops;

/* ------------------------------------------------------------- helpers */

static void hex(char *out, int outlen, const unsigned char *b, int n)
{
    int i, k = 0;
    for (i = 0; i < n && k + 3 < outlen; i++)
        k += snprintf(out + k, (size_t)(outlen - k), "%s%02x", i ? " " : "", b[i]);
    out[k] = 0;
}

static int write_all(int fd, const unsigned char *b, int n)
{
    int done = 0;
    while (done < n) {
        int r = (int)write(fd, b + done, (size_t)(n - done));
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        done += r;
    }
    return 0;
}

/* read exactly n bytes; the tty has VMIN 0/VTIME 3 (300 ms) like the game,
 * and poll() caps a device that ignores VTIME. Returns bytes received. */
static int read_exact(int fd, unsigned char *b, int n)
{
    int got = 0;
    long long deadline = sel_now_ms() + 1000;
    while (got < n) {
        struct pollfd p;
        int r;
        p.fd = fd;
        p.events = POLLIN;
        p.revents = 0;
        r = poll(&p, 1, 400);
        if (r < 0 && errno == EINTR) continue;
        if (r <= 0) return got;
        r = (int)read(fd, b + got, (size_t)(n - got));
        if (r < 0) { if (errno == EINTR) continue; return got; }
        if (r == 0) return got;                 /* VTIME expired */
        got += r;
        if (sel_now_ms() > deadline) return got;
    }
    return got;
}

static void log_xchg(struct hw *h, const char *tag, const unsigned char *tx, int txn,
                     const unsigned char *rx, int rxn, const char *verdict)
{
    char a[200], b[200];
    if (h->logged >= LOG_EXCHANGES && !verdict) return;
    hex(a, sizeof a, tx, txn);
    hex(b, sizeof b, rx, rxn);
    sel_log("nb %s: tx %s%s%s%s%s", tag, a, rxn ? " rx " : "", rxn ? b : "",
            verdict ? " " : "", verdict ? verdict : "");
    h->logged++;
}

/* unaddressed frame: raw bytes out, raw bytes in (no checksum, no status) */
static int xchg_raw(struct hw *h, const char *tag, const unsigned char *tx, int txn,
                    unsigned char *rx, int rxn)
{
    int got = 0;
    if (h->fd < 0) return -1;
    tcflush(h->fd, TCIFLUSH);
    if (write_all(h->fd, tx, txn) < 0) {
        log_xchg(h, tag, tx, txn, NULL, 0, "write failed");
        return -1;
    }
    if (rxn > 0) {
        got = read_exact(h->fd, rx, rxn);
        if (got != rxn) {
            log_xchg(h, tag, tx, txn, rx, got, "short reply (timed out)");
            return -1;
        }
    }
    log_xchg(h, tag, tx, txn, rx, got, NULL);
    return got;
}

/* addressed frame [0x80|node][n+1][payload][ck][reply_len]; the reply
 * [payload rl][ck][STATUS] is checked like the game checks it. */
static int xchg(struct hw *h, const char *tag, int node, const unsigned char *p, int n,
                int rl, unsigned char *reply)
{
    unsigned char f[80], r[64];
    unsigned char ck = 0;
    int k = 0, i, got, want;

    if (h->fd < 0 || n + 4 > (int)sizeof f || rl + 2 > (int)sizeof r) return -1;
    f[k++] = (unsigned char)(0x80 | node);
    f[k++] = (unsigned char)(n + 1);
    memcpy(f + k, p, (size_t)n);
    k += n;
    for (i = 0; i < k; i++) ck = (unsigned char)(ck - f[i]);
    f[k++] = ck;
    f[k++] = (unsigned char)(rl ? rl + 2 : 0);
    tcflush(h->fd, TCIFLUSH);
    if (write_all(h->fd, f, k) < 0) {
        log_xchg(h, tag, f, k, NULL, 0, "write failed");
        return -1;
    }
    if (!rl) { log_xchg(h, tag, f, k, NULL, 0, NULL); return 0; }
    want = rl + 2;
    got = read_exact(h->fd, r, want);
    if (got != want) {
        log_xchg(h, tag, f, k, r, got, "short reply (timed out)");
        return -1;
    }
    ck = 0;
    for (i = 0; i <= rl; i++) ck = (unsigned char)(ck + r[i]);
    if (ck) { log_xchg(h, tag, f, k, r, got, "BAD CHECKSUM"); return -1; }
    if (r[rl + 1] & 0x0c) {
        char v[40];
        snprintf(v, sizeof v, "STATUS 0x%02x = error", r[rl + 1]);
        log_xchg(h, tag, f, k, r, got, v);
        return -1;
    }
    log_xchg(h, tag, f, k, r, got, NULL);
    if (reply) memcpy(reply, r, (size_t)rl);
    return rl;
}

/* ------------------------------------------------------------ tty setup */

static void tty_setup(struct hw *h, const char *dev)
{
    struct serial_struct ss;
    struct termios t;
    int m;

    h->fd = open(dev, O_RDWR | O_NOCTTY);                /* flags 0x102 */
    if (h->fd < 0) {
        sel_log("nb: open %s failed: %s (no node-bus input)", dev, strerror(errno));
        return;
    }
    memset(&ss, 0, sizeof ss);
    if (ioctl(h->fd, TIOCGSERIAL, &ss) < 0) {
        sel_log("nb: TIOCGSERIAL: %s (tolerated)", strerror(errno));
    } else {
        ss.flags |= ASYNC_LOW_LATENCY;
        if (ioctl(h->fd, TIOCSSERIAL, &ss) < 0)
            sel_log("nb: TIOCSSERIAL: %s (tolerated)", strerror(errno));
    }
    memset(&t, 0, sizeof t);
    if (tcgetattr(h->fd, &t) < 0) sel_log("nb: tcgetattr: %s (tolerated)", strerror(errno));
    cfmakeraw(&t);
    t.c_cflag = CS8 | CREAD | CLOCAL | CSTOPB;           /* 8N2 */
    if (cfsetspeed(&t, B460800) < 0) sel_log("nb: cfsetspeed: %s (tolerated)", strerror(errno));
    t.c_cflag &= ~CRTSCTS;
    t.c_cc[VMIN] = 0;
    t.c_cc[VTIME] = 3;
    if (tcsetattr(h->fd, TCSANOW, &t) < 0) sel_log("nb: tcsetattr: %s (tolerated)", strerror(errno));
    if (tcflow(h->fd, TCOON) < 0) sel_log("nb: tcflow: %s (tolerated)", strerror(errno));
    if (tcflush(h->fd, TCIOFLUSH) < 0) sel_log("nb: tcflush: %s (tolerated)", strerror(errno));
    /* RTS pulse: 5 ms on, 5 ms off, left low (game 0x59eb74 via 0x5a7ba0) */
    m = 0;
    if (ioctl(h->fd, TIOCMGET, &m) < 0) {
        sel_log("nb: TIOCMGET: %s (no RTS pulse)", strerror(errno));
    } else {
        m |= TIOCM_RTS;
        if (ioctl(h->fd, TIOCMSET, &m) < 0) sel_log("nb: TIOCMSET: %s (tolerated)", strerror(errno));
        sel_sleep_ms(5);
        m &= ~TIOCM_RTS;
        if (ioctl(h->fd, TIOCMSET, &m) < 0) sel_log("nb: TIOCMSET: %s (tolerated)", strerror(errno));
        sel_sleep_ms(5);
    }
    sel_log("nb: %s open (460800 8N2, VMIN 0 VTIME 3)", dev);
}

/* --------------------------------------------------------------- preamble */

static void preamble(struct hw *h, int full)
{
    static const unsigned char c0a[] = { 0x0a, 0x00 };
    static const unsigned char c07[] = { 0x07, 0x01, 0x01 };
    static const unsigned char poll0[] = { 0x00 };
    static const unsigned char f1[] = { 0xf1 };
    static const unsigned char f0_22[] = { 0xf0, 0x22 };
    static const unsigned char f0_11[] = { 0xf0, 0x11 };
    static const unsigned char f0_10[] = { 0xf0, 0x10 };
    static const unsigned char f0_20[] = { 0xf0, 0x20 };
    static const unsigned char fe[] = { 0xfe };
    static const int nodes[2] = { NODE_FLIPPERS, NODE_START };
    unsigned char r[32];
    int i, loops;

    if (h->fd < 0) return;
    /* 1. bus open: 0a 00 (2-byte reply) + 07 01 01 (no reply) */
    xchg_raw(h, "0a", c0a, sizeof c0a, r, 2);
    xchg_raw(h, "07", c07, sizeof c07, NULL, 0);
    /* 3. f1 to node 0 */
    xchg(h, "f1", 0, f1, sizeof f1, 0, NULL);
    /* 4. enumeration */
    xchg(h, "f0 22", 0, f0_22, sizeof f0_22, 0, NULL);
    xchg(h, "f0 11", 0, f0_11, sizeof f0_11, 0, NULL);
    for (loops = 0; loops < 64; loops++) {
        int n;
        if (xchg_raw(h, "poll", poll0, sizeof poll0, r, 1) != 1) break;
        n = r[0];
        if (n == 0) break;
        if (n >= 1 && n <= 31) {
            xchg(h, "f0 10", n, f0_10, sizeof f0_10, 0, NULL);
            xchg(h, "f0 20", n, f0_20, sizeof f0_20, 0, NULL);
        }
    }
    xchg(h, "f0 22", 0, f0_22, sizeof f0_22, 0, NULL);
    /* 5. identity of the two boards we scan (pure reads) */
    for (i = 0; i < 2; i++) {
        if (xchg(h, "fe", nodes[i], fe, sizeof fe, 11, r) == 11) {
            sel_log("nb: node %d identity fw %d.%d.%d part 0x%02x%02x%02x%02x board 0x%02x%02x variant %d",
                    nodes[i], r[1], r[2], r[3], r[7], r[6], r[5], r[4], r[9], r[8], r[10]);
        } else {
            sel_log("nb: node %d identity read failed (board absent or silent)", nodes[i]);
        }
    }
    if (!full) return;
    /* 6. the write-only frames the game sends before its first 0x11, only
     * those captured byte-exactly (gz610.log 31793-32052); the coil-config
     * series (46 <mask>/40 <i>/72/85/84) was not captured verbatim and is
     * not replayed. */
    {
        static const unsigned char ff[] = { 0xff };
        static const unsigned char n8_14a[] = { 0x14, 0x40, 0x00, 0x27, 0x00 };
        static const unsigned char n8_14b[] = { 0x14, 0x60, 0x00, 0x40, 0x00 };
        static const unsigned char n8_46[] = { 0x46, 0xff, 0x01 };
        static const unsigned char n8_72[] = { 0x72, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                                               0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
        static const unsigned char n8_48[] = { 0x48, 0x00, 0x00 };
        static const unsigned char n1_14a[] = { 0x14, 0x08, 0x00, 0x17, 0x00 };
        static const unsigned char n1_14b[] = { 0x14, 0x60, 0x00, 0x40, 0x00 };
        static const unsigned char n1_44[] = { 0x44, 0x01 };
        xchg(h, "ff", NODE_FLIPPERS, ff, sizeof ff, 8, r);
        xchg(h, "14", NODE_FLIPPERS, n8_14a, sizeof n8_14a, 0, NULL);
        xchg(h, "14", NODE_FLIPPERS, n8_14b, sizeof n8_14b, 0, NULL);
        xchg(h, "46", NODE_FLIPPERS, n8_46, sizeof n8_46, 0, NULL);
        xchg(h, "72", NODE_FLIPPERS, n8_72, sizeof n8_72, 0, NULL);
        xchg(h, "48", NODE_FLIPPERS, n8_48, sizeof n8_48, 0, NULL);
        xchg(h, "ff", NODE_START, ff, sizeof ff, 8, r);
        xchg(h, "14", NODE_START, n1_14a, sizeof n1_14a, 0, NULL);
        xchg(h, "14", NODE_START, n1_14b, sizeof n1_14b, 0, NULL);
        xchg(h, "44", NODE_START, n1_44, sizeof n1_44, 0, NULL);
    }
}

/* ------------------------------------------------------------------- SPI */

static void spi_setup(struct hw *h, const char *dev)
{
    unsigned hz = 100000;
    unsigned char mode = SPI_MODE_3;
    h->spi = -1;
    if (!dev || !*dev || !strcmp(dev, "none")) return;
    h->spi = open(dev, O_RDWR);
    if (h->spi < 0) {
        sel_log("spi: open %s failed: %s (no service buttons)", dev, strerror(errno));
        return;
    }
    if (ioctl(h->spi, SPI_IOC_WR_MAX_SPEED_HZ, &hz) < 0)
        sel_log("spi: SPI_IOC_WR_MAX_SPEED_HZ: %s (tolerated)", strerror(errno));
    if (ioctl(h->spi, SPI_IOC_WR_MODE, &mode) < 0)
        sel_log("spi: SPI_IOC_WR_MODE: %s (tolerated)", strerror(errno));
    sel_log("spi: %s open (100 kHz, mode 3, 8-byte transfers)", dev);
}

static void spi_poll(struct hw *h)
{
    unsigned char tx[8], rx[8];
    struct spi_ioc_transfer x;
    memset(tx, 0, sizeof tx);
    memset(rx, 0, sizeof rx);
    memset(&x, 0, sizeof x);
    x.tx_buf = (unsigned long)tx;
    x.rx_buf = (unsigned long)rx;
    x.len = 8;
    if (ioctl(h->spi, SPI_IOC_MESSAGE(1), &x) < 0) {
        if (h->spi_logged < 3) sel_log("spi: transfer failed: %s", strerror(errno));
        h->spi_logged++;
        return;
    }
    if (h->spi_logged < 5 || (h->cab_valid && memcmp(rx, h->cab, 8))) {
        char b[40];
        hex(b, sizeof b, rx, 8);
        sel_log("spi: rx %s%s", b, h->spi_logged < 5 ? "" : " (changed)");
        h->spi_logged++;
    }
    memcpy(h->cab, rx, 8);
    h->cab_valid = 1;
    /* rx[1] bits 0-3: Service Select/Plus/Minus/Back, ACTIVE LOW */
    input_sample(&h->base, KEY_OF(EV_SELECT), !((rx[1] >> 0) & 1));
    input_sample(&h->base, KEY_OF(EV_PLUS),   !((rx[1] >> 1) & 1));
    input_sample(&h->base, KEY_OF(EV_MINUS),  !((rx[1] >> 2) & 1));
    input_sample(&h->base, KEY_OF(EV_BACK),   !((rx[1] >> 3) & 1));
}

/* ------------------------------------------------------------- scanning */

static void scan_node(struct hw *h, int slot, long long now)
{
    static const unsigned char c11[] = { 0x11 };
    int node = slot == 0 ? NODE_FLIPPERS : NODE_START;
    unsigned char r[16];

    if (now < h->node_retry[slot]) return;
    if (xchg(h, "11", node, c11, sizeof c11, 10, r) != 10) {
        long back;
        h->node_fail[slot]++;
        back = h->node_fail[slot] >= 3 ? 2000 : h->node_fail[slot] == 2 ? 1000 : 500;
        h->node_retry[slot] = now + back;
        if (h->node_fail[slot] <= 3 || h->node_fail[slot] % 50 == 0)
            sel_log("nb: node %d scan failed (%d), next try in %ld ms", node, h->node_fail[slot], back);
        return;
    }
    if (h->node_fail[slot]) sel_log("nb: node %d answers again", node);
    h->node_fail[slot] = 0;
    if (!h->sw_valid[slot] || memcmp(r, h->sw[slot], 8)) {
        char b[40];
        hex(b, sizeof b, r, 8);
        sel_log("nb: node %d switches %s", node, b);
    }
    memcpy(h->sw[slot], r, 8);
    h->sw_valid[slot] = 1;
    /* released = 1, pressed = 0 */
    if (node == NODE_FLIPPERS) {
        input_sample(&h->base, KEY_OF(EV_RIGHT), !((r[3] >> 0) & 1));   /* bit 24 */
        input_sample(&h->base, KEY_OF(EV_LEFT),  !((r[3] >> 1) & 1));   /* bit 25 */
    } else {
        input_sample(&h->base, KEY_OF(EV_START),  !((r[1] >> 3) & 1));  /* bit 11 */
        /* the lockdown-bar button, node 1 bit 2 on every Spike 2 list on this
         * disk (30 of 31; the beatles list has no such row) - padglhost's
         * cab_wire table resolves it the same way */
        input_sample(&h->base, KEY_OF(EV_ACTION), !((r[0] >> 2) & 1));  /* bit 2 */
    }
}

static void hw_poll(struct input *in, long long now)
{
    struct hw *h = (struct hw *)in;
    if (h->fd >= 0 && now >= h->next_scan) {
        scan_node(h, 0, now);
        scan_node(h, 1, now);
        h->next_scan = now + SCAN_MS;
    }
    if (h->spi >= 0 && now >= h->next_spi) {
        spi_poll(h);
        h->next_spi = now + SPI_MS;
    }
}

static void hw_close(struct input *in)
{
    struct hw *h = (struct hw *)in;
    if (h->fd >= 0) close(h->fd);
    if (h->spi >= 0) close(h->spi);
    free(h);
}

static const struct input_ops hw_ops = { hw_poll, hw_close };

struct input *input_hw_open(const struct input_cfg *cfg)
{
    struct hw *h = calloc(1, sizeof *h);
    if (!h) return NULL;
    input_base_init(&h->base, &hw_ops);
    h->fd = -1;
    h->spi = -1;
    tty_setup(h, cfg->nodebus ? cfg->nodebus : "/dev/ttymxc1");
    preamble(h, cfg->preamble_full);
    spi_setup(h, cfg->spi ? cfg->spi : "/dev/spidev1.0");
    if (h->fd < 0 && h->spi < 0)
        sel_log("hw: neither the node bus nor the SPI opened: no buttons, countdown only");
    return &h->base;
}
