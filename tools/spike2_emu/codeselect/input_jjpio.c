/* input_jjpio.c - the cabinet buttons of a JJP machine, read the way JJP's
 * own installer helper reads them.
 *
 * THE SOURCE IS JJP'S.  Every install stick carries /jjp/bin/jjpcrt, the
 * "push both flippers / push start" prompt jjp_install.sh shows before it
 * wipes a disk.  It ships unstripped with DWARF (jjpcrt.c:108-194, read
 * 2026-09-12 out of GunsNRoses-v03.03.iso), and its io_thread is this:
 *
 *     memset(read_buf, 0xff, 64); memset(write_buf, 0, 64);
 *     open("/dev/jjpio%i")
 *     loop:  read(fd, read_buf, 64)  - anything but 64 = unplugged, reopen
 *            LEFT  flipper = read_buf[1] & 0x01   (high = released)
 *            RIGHT flipper = read_buf[1] & 0x04
 *            START         = read_buf[3] & 0x01
 *            write(fd, write_buf, 64)             - ALL ZERO, every pass
 *
 * So: one 64-byte IN frame per read, one 64-byte all-zero OUT frame per
 * write, paired; the buttons are active LOW in the frame's cabinet bytes;
 * and the ZERO OUT FRAME IS JJP'S OWN IDLE FRAME, written by their installer
 * on a powered machine - it drives no coil.  This backend writes that frame
 * and nothing else, and stops the moment the menu exits.  The positions are
 * platform-wide (the same jjpcrt runs on every title), and the rig's CUSE
 * board serves the same bytes (jjpshm.h: bytes 0..3 cabinet, active low).
 *
 * THE VOLUME BUTTONS (item 120) are not jjpcrt's - its prompt needs only the
 * flippers and START - but they sit in the same cabinet byte: GNR's device
 * table names dswitch_plus "Up / Volume+ Button" byte 1 bit 5 and
 * dswitch_minus "Down / Volume- Button" byte 1 bit 6 (masks 0x20 / 0x40,
 * beside the flippers' 0x01 / 0x04).  That is ONE title's table, so
 * key_plus= / key_minus= and --learn are how a machine that wires them
 * elsewhere is set right.  They arrive as EV_PLUS / EV_MINUS, and the menu
 * gives them their JJP meaning (codeselect.c: the volume, not the highlight).
 *
 * PACING.  jjpcrt has no sleep: the real driver (jjp_bulk_io.ko) completes
 * a read when the interrupt URB does, ~1 ms.  The rig's CUSE device answers
 * at once, which would spin a core, so this thread paces itself to
 * POLL_MS between frames - 200 Hz, twice the debouncer's two-sample need
 * and far below the game's own 1 kHz.  poll() first: a device that stops
 * answering (unplugged, or the test's pty with no writer) must not pin the
 * thread in read() past close.
 *
 * A DEVICE THAT IS NOT THERE IS NOT AN ERROR.  The menu runs, times out and
 * boots the primary - the rule every backend follows: a dead button must
 * never keep a pinball machine from booting.  The open is retried every
 * OPEN_MS, and every failure is one log line, not one per attempt.
 *
 * --learn logs the four cabinet bytes whenever they change, which is how a
 * machine whose buttons sit elsewhere in the frame is calibrated: read the
 * log, write key_left= / key_right= / key_start= / key_plus= / key_minus=
 * (<byte>.<bit>) into images.conf.  The name to the game is /dev/jjpio100 (udev's symlink,
 * 90-jjp_usb_device.rules); the driver's own node is /dev/jjpio0.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <pthread.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include "input.h"
#include "log.h"

#define FRAME_LEN 64
#define POLL_MS   5
#define OPEN_MS   500
#define READ_WAIT_MS 50           /* poll() bound: how long a dead device holds the thread */

static const char *const DEVS[] = { "/dev/jjpio100", "/dev/jjpio0", NULL };

/* the five cabinet buttons, in the conf's order LEFT, RIGHT, START, Volume+,
 * Volume- (input_cfg.jjp_byte / conf.jjp_byte index the same way) */
#define NBTN 5
static const int DEF_BYTE[NBTN] = { 1, 1, 3, 1, 1 };
static const int DEF_BIT[NBTN]  = { 0, 2, 0, 5, 6 };
static const int EV_OF[NBTN]    = { EV_LEFT, EV_RIGHT, EV_START, EV_PLUS, EV_MINUS };

struct jj {
    struct input base;
    char dev[512];               /* the one named, or "" = the built-in list */
    const char *opened;          /* which path is open */
    int fd;
    int byte[NBTN], bit[NBTN];
    int learn;
    pthread_t th;
    int th_on, th_stop;
    long long next_open;
    int open_logged;             /* the "cannot open" line, once per outage */
    long long frames, writes, short_reads, reopens;
    unsigned char last_direct[4];
    int have_direct;
};

static int try_open(struct jj *j)
{
    const char *const *cand;
    const char *one[2] = { j->dev, NULL };
    cand = j->dev[0] ? one : DEVS;
    for (; *cand; cand++) {
        int fd = open(*cand, O_RDWR | O_NOCTTY | O_CLOEXEC);
        if (fd >= 0) {
            j->fd = fd;
            j->opened = *cand;
            j->open_logged = 0;
            j->have_direct = 0;
            sel_log("jjpio: %s open (LEFT %d.%d, RIGHT %d.%d, START %d.%d, VOL+ %d.%d, VOL- %d.%d, active low)",
                    *cand, j->byte[0], j->bit[0], j->byte[1], j->bit[1], j->byte[2], j->bit[2],
                    j->byte[3], j->bit[3], j->byte[4], j->bit[4]);
            return 0;
        }
        if (!j->open_logged) sel_log("jjpio: cannot open %s: %s", *cand, strerror(errno));
    }
    if (!j->open_logged) {
        sel_log("jjpio: no I/O board node%s - the menu has no buttons until one appears",
                j->dev[0] ? "" : " (/dev/jjpio100, /dev/jjpio0)");
        j->open_logged = 1;
    }
    return -1;
}

static void drop(struct jj *j, const char *why)
{
    sel_log("jjpio: %s: %s - closing, will reopen", j->opened ? j->opened : "?", why);
    close(j->fd);
    j->fd = -1;
    j->reopens++;
    j->next_open = sel_now_ms() + OPEN_MS;
}

/* one jjpcrt pass: a whole IN frame, the five bits, the zero OUT frame.
 * 0 ok, -1 the device went away (already dropped) */
static int one_pass(struct jj *j)
{
    unsigned char in[FRAME_LEN];
    static const unsigned char out[FRAME_LEN];     /* zero: JJP's idle frame */
    struct pollfd pfd;
    int got = 0, k;

    pfd.fd = j->fd;
    pfd.events = POLLIN;
    if (poll(&pfd, 1, READ_WAIT_MS) <= 0) return 0;  /* nothing yet: not an error */
    if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) { drop(j, "poll says the node is gone"); return -1; }
    while (got < FRAME_LEN) {
        ssize_t n = read(j->fd, in + got, (size_t)(FRAME_LEN - got));
        if (n < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN) { if (got == 0) return 0; break; }
            drop(j, strerror(errno));
            return -1;
        }
        if (n == 0) { drop(j, "read returned 0"); return -1; }
        got += (int)n;
        /* a driver hands the whole frame over at once; a pty may not, so a
         * partial read is completed here rather than treated as jjpcrt does */
        if (got < FRAME_LEN) {
            pfd.events = POLLIN;
            if (poll(&pfd, 1, READ_WAIT_MS) <= 0) break;
        }
    }
    if (got != FRAME_LEN) {
        j->short_reads++;
        if (j->short_reads == 1) sel_log("jjpio: short frame (%d of %d bytes), ignored", got, FRAME_LEN);
        return 0;
    }
    j->frames++;
    for (k = 0; k < NBTN; k++) {
        int b = j->byte[k], bt = j->bit[k];
        int pressed = !(in[b] & (1u << bt));
        input_sample(&j->base, KEY_OF(EV_OF[k]), pressed);
    }
    if (j->learn && (!j->have_direct || memcmp(in, j->last_direct, 4))) {
        sel_log("jjpio: learn: cabinet bytes %02x %02x %02x %02x (bit clear = pressed)",
                in[0], in[1], in[2], in[3]);
        memcpy(j->last_direct, in, 4);
        j->have_direct = 1;
    }
    {
        int put = 0;
        while (put < FRAME_LEN) {
            ssize_t n = write(j->fd, out + put, (size_t)(FRAME_LEN - put));
            if (n < 0) {
                if (errno == EINTR) continue;
                if (errno == EAGAIN) break;          /* a full pty: skip this pass's write */
                drop(j, strerror(errno));
                return -1;
            }
            put += (int)n;
        }
        if (put == FRAME_LEN) j->writes++;
    }
    return 0;
}

static void *jj_thread(void *p)
{
    struct jj *j = p;
    setpriority(PRIO_PROCESS, (int)syscall(SYS_gettid), -5);   /* root: allowed; else ignored */
    while (!j->th_stop) {
        long long now = sel_now_ms();
        if (j->fd < 0) {
            if (now >= j->next_open) {
                if (try_open(j) < 0) j->next_open = now + OPEN_MS;
            }
            sel_sleep_ms(POLL_MS * 4);
            continue;
        }
        if (one_pass(j) < 0) continue;
        sel_sleep_ms(POLL_MS);
    }
    return NULL;
}

static void jj_poll(struct input *in, long long now_ms)
{
    (void)in; (void)now_ms;          /* threaded: the base only dequeues */
}

static void jj_close(struct input *in)
{
    struct jj *j = (struct jj *)in;
    if (j->th_on) {
        j->th_stop = 1;
        pthread_join(j->th, NULL);
        j->th_on = 0;
    }
    sel_log("jjpio: %lld frames read, %lld idle frames written, %lld short, %lld reopen(s)",
            j->frames, j->writes, j->short_reads, j->reopens);
    if (j->fd >= 0) close(j->fd);
    j->fd = -1;
    pthread_mutex_destroy(&j->base.lock);
    free(j);
}

static const struct input_ops jj_ops = { jj_poll, jj_close };

struct input *input_jjpio_open(const struct input_cfg *cfg)
{
    struct jj *j = calloc(1, sizeof *j);
    int k;
    if (!j) return NULL;
    input_base_init(&j->base, &jj_ops);
    j->base.threaded = 1;
    j->fd = -1;
    if (cfg->jjpio && *cfg->jjpio) snprintf(j->dev, sizeof j->dev, "%s", cfg->jjpio);
    for (k = 0; k < NBTN; k++) {
        int b = cfg->jjp_byte[k], bt = cfg->jjp_bit[k];
        int ok = b >= 0 && b < FRAME_LEN && bt >= 0 && bt < 8;
        j->byte[k] = ok ? b : DEF_BYTE[k];
        j->bit[k] = ok ? bt : DEF_BIT[k];
    }
    j->learn = cfg->jjp_learn;
    /* what this cabinet has: the two flippers, START and the volume pair.  No
     * lockdown-bar Action button, no Select/Back - the footer must not promise
     * them */
    for (k = 0; k < KEY_COUNT; k++) j->base.present[k] = 0;
    for (k = 0; k < NBTN; k++) j->base.present[KEY_OF(EV_OF[k])] = 1;
    try_open(j);                                     /* a miss is retried by the thread */
    if (pthread_create(&j->th, NULL, jj_thread, j) == 0) {
        j->th_on = 1;
    } else {
        sel_log("jjpio: cannot start the I/O thread: %s - no buttons", strerror(errno));
    }
    return &j->base;
}
