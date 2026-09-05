/* codec.c - see codec.h.  One small i2c client, modelled on the game's own
 * (godzilla_pro 0x1fa6d0 / 0x1fa724 / 0x1fa7b8 / 0x1fa8c0): I2C_SLAVE_FORCE
 * because the kernel's sgtl5000 driver is bound to both addresses, then
 * I2C_RDWR messages - a write is 4 bytes {reg hi, reg lo, val hi, val lo},
 * a read is a 2-byte register select followed by a 2-byte I2C_M_RD - and
 * ten 1 ms retries when the bus is busy.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include "codec.h"
#include "log.h"

#define I2C_DEV          "/dev/i2c-1"
#define CHIP_ID          0x0000
#define SGTL5000_PARTID  0xa0            /* CHIP_ID bits 15:8 */
#define NREG             50
#define RETRIES          10

static const unsigned char ADDRS[2] = { 0x0a, 0x2a };   /* sgtl5000-main, sgtl5000-center */

/* THE GAME'S TABLE (godzilla_pro .rodata 0x638ae8, identical in every
 * title checked): 50 registers, then the values for 0x0a and for 0x2a.
 * This is the full-power set its recovery path writes over a running
 * stream; the standby set its first bring-up writes (DAC muted, outputs
 * unpowered, 0x4060) is not what a menu wants. */
static const unsigned short REGS[NREG] = {
    0x0002, 0x0004, 0x0006, 0x000a, 0x000e, 0x0010, 0x0014, 0x0020, 0x0022, 0x0024,
    0x0026, 0x0028, 0x002a, 0x002c, 0x002e, 0x0030, 0x0032, 0x0034, 0x0036, 0x0038,
    0x003a, 0x003c, 0x0100, 0x0102, 0x0104, 0x0106, 0x0108, 0x010a, 0x010c, 0x010e,
    0x0110, 0x0116, 0x0118, 0x011a, 0x011c, 0x011e, 0x0120, 0x0122, 0x0124, 0x0126,
    0x0128, 0x012a, 0x012c, 0x012e, 0x0130, 0x0132, 0x0134, 0x0136, 0x0138, 0x013a,
};
static const unsigned short PLAY_MAIN[NREG] = {
    0x0061, 0x0006, 0x0000, 0x0010, 0x0200, 0x8282, 0x015f, 0x0000, 0x5e5e, 0x0020,
    0x0068, 0x01f0, 0x0000, 0x0322, 0x0404, 0x40f9, 0x5000, 0x0000, 0x0017, 0x01c0,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0040, 0x051f, 0x0000, 0x0040, 0x0000, 0x0000,
    0x0000, 0x002f, 0x002f, 0x002f, 0x002f, 0x002f, 0x8000, 0x0000, 0x0100, 0x1473,
    0x0028, 0x0050, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
};
static const unsigned short PLAY_CENTER[NREG] = {
    0x0061, 0x0006, 0x0000, 0x0010, 0x0200, 0x8282, 0x015f, 0x00cc, 0x4040, 0x0022,
    0x0068, 0x01f0, 0x0002, 0x0322, 0x0404, 0x40f9, 0x5000, 0x0000, 0x0017, 0x01c0,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0040, 0x051f, 0x0000, 0x0040, 0x0000, 0x0000,
    0x0000, 0x002f, 0x002f, 0x002f, 0x002f, 0x002f, 0x8000, 0x0000, 0x0100, 0x1473,
    0x0028, 0x0050, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
};

/* THE STANDBY SET - what the game's first bring-up writes (0x1fa8c0(1))
 * right after the bridge's 08 01 01 has reset the chips: DAC muted (000e
 * 020c), outputs unpowered (0030 4060), the clock at its 48 kHz/256 setting
 * (0004 0008) and the I2S format at default (0006 0000) - the PCM open that
 * follows powers what it needs.  Written EXACTLY (no ORing: there is no
 * live kernel configuration to preserve after a reset). */
static const unsigned short STANDBY_MAIN[NREG] = {
    0x0060, 0x0008, 0x0000, 0x0010, 0x020c, 0x7676, 0x015f, 0x0000, 0x1010, 0x0020,
    0x0068, 0x01f0, 0x0000, 0x0322, 0x0404, 0x4060, 0x5000, 0x0000, 0x0017, 0x01c0,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0040, 0x051f, 0x0000, 0x0040, 0x0000, 0x0000,
    0x0000, 0x002f, 0x002f, 0x002f, 0x002f, 0x002f, 0x8000, 0x0000, 0x0100, 0x1473,
    0x0028, 0x0050, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
};
static const unsigned short STANDBY_CENTER[NREG] = {
    0x0060, 0x0008, 0x0000, 0x0010, 0x020c, 0x6c6c, 0x015f, 0x00cc, 0x4040, 0x0022,
    0x0068, 0x01f0, 0x0002, 0x0322, 0x0404, 0x4060, 0x5000, 0x0000, 0x0017, 0x01c0,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0040, 0x051f, 0x0000, 0x0040, 0x0000, 0x0000,
    0x0000, 0x002f, 0x002f, 0x002f, 0x002f, 0x002f, 0x8000, 0x0000, 0x0100, 0x1473,
    0x0028, 0x0050, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
};

/* left to the kernel: CHIP_CLK_CTRL and CHIP_I2S_CTRL (hw_params set them
 * for the stream that is actually running), CHIP_DAC_VOL and
 * CHIP_ANA_HP_CTRL (the PCM / Headphone mixer controls), CHIP_ANA_STATUS
 * (read-only) */
static int kernel_owned(unsigned reg)
{
    return reg == 0x0004 || reg == 0x0006 || reg == 0x0010 || reg == 0x0022 || reg == 0x0036;
}

/* CHIP_DIG_POWER and CHIP_ANA_POWER: bits are added, never taken away -
 * LINREG_D / VDDC_CHRGPMP / STARTUP / LINREG_SIMPLE are the kernel's call
 * for this board's supplies */
static int power_reg(unsigned reg)
{
    return reg == 0x0002 || reg == 0x0030;
}

struct saved { unsigned char addr; unsigned short reg, was; };
static struct saved changed[2 * NREG];
static int nchanged;
static int enabled = 1;
static int gone;                 /* the bus or the chips are not there: say so once, stop trying */

void codec_configure(const char *mode)
{
    if (mode && !strcmp(mode, "off")) {
        enabled = 0;
        sel_log("codec: left alone (--codec off)");
    }
}

static int rdwr(int fd, struct i2c_msg *msgs, int n)
{
    struct i2c_rdwr_ioctl_data d;
    int tries;
    d.msgs = msgs;
    d.nmsgs = (unsigned)n;
    for (tries = 0; ; tries++) {
        if (ioctl(fd, I2C_RDWR, &d) >= 0) return 0;
        if (tries >= RETRIES) return -1;
        usleep(1000);
    }
}

static int rd(int fd, int addr, unsigned reg, unsigned *val)
{
    unsigned char a[2], v[2] = { 0, 0 };
    struct i2c_msg m[2];
    a[0] = (unsigned char)(reg >> 8);
    a[1] = (unsigned char)reg;
    m[0].addr = (unsigned short)addr; m[0].flags = 0;        m[0].len = 2; m[0].buf = a;
    m[1].addr = (unsigned short)addr; m[1].flags = I2C_M_RD; m[1].len = 2; m[1].buf = v;
    if (rdwr(fd, m, 2) < 0) return -1;
    *val = ((unsigned)v[0] << 8) | v[1];
    return 0;
}

static int wr(int fd, int addr, unsigned reg, unsigned val)
{
    unsigned char b[4];
    struct i2c_msg m;
    b[0] = (unsigned char)(reg >> 8);
    b[1] = (unsigned char)reg;
    b[2] = (unsigned char)(val >> 8);
    b[3] = (unsigned char)val;
    m.addr = (unsigned short)addr; m.flags = 0; m.len = 4; m.buf = b;
    return rdwr(fd, &m, 1);
}

/* the bus with both chips proven, or -1 (logged once; later calls are silent) */
static int open_bus(void)
{
    int fd, i;
    if (!enabled || gone) return -1;
    fd = open(I2C_DEV, O_RDWR);
    if (fd < 0) {
        sel_log("codec: %s: %s (codecs left alone)", I2C_DEV, strerror(errno));
        gone = 1;
        return -1;
    }
    for (i = 0; i < 2; i++) {
        unsigned id = 0;
        if (ioctl(fd, I2C_SLAVE_FORCE, (long)ADDRS[i]) < 0) {
            sel_log("codec: 0x%02x: I2C_SLAVE_FORCE: %s (codecs left alone)", ADDRS[i], strerror(errno));
            close(fd);
            gone = 1;
            return -1;
        }
        if (rd(fd, ADDRS[i], CHIP_ID, &id) < 0 || (id >> 8) != SGTL5000_PARTID) {
            sel_log("codec: 0x%02x: CHIP_ID %s0x%04x, not an SGTL5000 (codecs left alone)",
                    ADDRS[i], id ? "" : "unreadable ", id);
            close(fd);
            gone = 1;
            return -1;
        }
    }
    return fd;
}

void codec_snapshot(const char *when)
{
    int fd = open_bus(), i, k;
    if (fd < 0) return;
    for (i = 0; i < 2; i++) {
        char line[600];
        int n = 0;
        for (k = 0; k < NREG; k++) {
            unsigned v = 0;
            int ok = rd(fd, ADDRS[i], REGS[k], &v) == 0;
            if (k == NREG / 2) {
                sel_log("codec 0x%02x %s (1/2):%s", ADDRS[i], when, line);
                n = 0;
                line[0] = 0;
            }
            n += snprintf(line + n, sizeof line - (size_t)n, ok ? " %04x=%04x" : " %04x=????", REGS[k], v);
            if (n >= (int)sizeof line - 12) break;
        }
        sel_log("codec 0x%02x %s (2/2):%s", ADDRS[i], when, line);
    }
    close(fd);
}

/* write a table (wm for 0x0a, wc for 0x2a) to both chips, verify-and-correct
 * like the game's 0x1fa8c0.  whole = 1 is the after-reset pass: every
 * register but the two volumes the game skips and the read-only status,
 * values exact; whole = 0 is the live pass: the kernel-owned registers are
 * left alone and the power registers ORed.  record = 1 saves the values
 * found into changed[] (for restore); log_each = 1 logs every write, with
 * `note` on the end.  Returns registers changed (negative = had failures). */
static int apply(int fd, const unsigned short *wm, const unsigned short *wc, int whole,
                 int record, int log_each, const char *note)
{
    int i, k, total = 0, bad = 0;
    for (i = 0; i < 2; i++) {
        const unsigned short *want = i == 0 ? wm : wc;
        for (k = 0; k < NREG; k++) {
            unsigned reg = REGS[k], cur = 0, to, back = 0;
            if (whole ? (reg == 0x0010 || reg == 0x002e || reg == 0x0036) : kernel_owned(reg)) continue;
            if (rd(fd, ADDRS[i], reg, &cur) < 0) {
                if (log_each) sel_log("codec 0x%02x reg %04x: unreadable, skipped", ADDRS[i], reg);
                bad++;
                continue;
            }
            to = (!whole && power_reg(reg)) ? (cur | want[k]) : want[k];
            if (to == cur) continue;
            if (wr(fd, ADDRS[i], reg, to) < 0 || rd(fd, ADDRS[i], reg, &back) < 0) {
                sel_log("codec 0x%02x reg %04x %04x -> %04x: write failed", ADDRS[i], reg, cur, to);
                bad++;
                continue;
            }
            if (record && nchanged < (int)(sizeof changed / sizeof *changed)) {
                changed[nchanged].addr = ADDRS[i];
                changed[nchanged].reg = (unsigned short)reg;
                changed[nchanged].was = (unsigned short)cur;
                nchanged++;
            }
            total++;
            if (log_each) sel_log("codec 0x%02x reg %04x %04x -> %04x%s", ADDRS[i], reg, cur, to, note);
            if (back != to) sel_log("codec 0x%02x reg %04x reads back %04x, not %04x", ADDRS[i], reg, back, to);
        }
    }
    return bad ? -total - 1 : total;
}

#define RESET_WAIT_MS  250      /* the game's 250 x usleep(1000) poll (0x1faa5c) */
#define RESET_SETTLE_US 750000  /* its usleep after the value came (0x1faa84) */
void codec_after_reset(void)
{
    int fd, i, ms, r, total;
    unsigned v[2] = { 0, 0 };
    if (!enabled || gone) return;
    fd = open_bus();
    if (fd < 0) return;
    for (ms = 0; ms < RESET_WAIT_MS; ms++) {
        int ok = 1;
        for (i = 0; i < 2; i++)
            if (rd(fd, ADDRS[i], 0x0024, &v[i]) < 0 || v[i] != 0x0111) ok = 0;
        if (ok) break;
        usleep(1000);
    }
    if (ms < RESET_WAIT_MS)
        sel_log("codec: both chips at their reset value after %d ms (CHIP_ANA_CTRL 0x0111): the bridge reset them", ms);
    else
        sel_log("codec: reset value NOT seen in %d ms (0x0a reads %04x, 0x2a %04x): the bridge did not reset the codecs; continuing as the game would",
                RESET_WAIT_MS, v[0], v[1]);
    close(fd);
    usleep(RESET_SETTLE_US);
    fd = open_bus();
    if (fd < 0) return;
    r = apply(fd, STANDBY_MAIN, STANDBY_CENTER, 1, 0, 0, "");
    total = r < 0 ? -r - 1 : r;
    for (i = 0; i < 2; i++) {
        unsigned a = 0, b = 0, c = 0, d = 0, e = 0, f = 0;
        rd(fd, ADDRS[i], 0x0002, &a); rd(fd, ADDRS[i], 0x0004, &b); rd(fd, ADDRS[i], 0x0006, &c);
        rd(fd, ADDRS[i], 0x000e, &d); rd(fd, ADDRS[i], 0x0024, &e); rd(fd, ADDRS[i], 0x0030, &f);
        sel_log("codec 0x%02x after the standby table: DIG_POWER %04x CLK %04x I2S %04x ADCDAC %04x ANA_CTRL %04x ANA_POWER %04x",
                ADDRS[i], a, b, c, d, e, f);
    }
    close(fd);
    sel_log("codec: the game's standby table written after the reset, %d register(s) changed%s; the stream opens next",
            total, r < 0 ? " (some failed)" : "");
}

int codec_power_up(void)
{
    int fd = open_bus(), r, total;
    if (fd < 0) return 0;
    nchanged = 0;
    r = apply(fd, PLAY_MAIN, PLAY_CENTER, 0, 1, 1, "");
    close(fd);
    total = r < 0 ? -r - 1 : r;
    sel_log("codec: %d register(s) set on the two chips: line-out, VAG, DAC powered, analog mutes cleared", total);
    return total;
}


void codec_restore(void)
{
    int fd, i, back = 0;
    if (!nchanged) return;
    fd = open_bus();
    if (fd < 0) return;
    for (i = nchanged - 1; i >= 0; i--) {
        unsigned cur = 0, to = changed[i].was;
        if (rd(fd, changed[i].addr, changed[i].reg, &cur) < 0) continue;
        if (power_reg(changed[i].reg)) to = cur & changed[i].was;   /* only ever take power away */
        if (to == cur) continue;
        if (wr(fd, changed[i].addr, changed[i].reg, to) == 0) back++;
        else sel_log("codec 0x%02x reg %04x: restore to %04x failed", changed[i].addr, changed[i].reg, to);
    }
    close(fd);
    sel_log("codec: %d register(s) put back as found", back);
    nchanged = 0;
}
