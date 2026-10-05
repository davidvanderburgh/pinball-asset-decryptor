/* input_fast.c - the cabinet buttons of a Barrels of Fun machine, read off
 * its FAST Pinball Neuron controller (PAD-342).
 *
 * THE PROTOCOL IS THE GAME'S.  Every BOF title talks to a FAST Neuron over
 * USB CDC serial: 921600 baud, ASCII commands ended by '\r'.  What is used
 * here is what the game's own fast_stem.gd sends and parses (decompiled for
 * the emulator, tools/bof_emu/bofhw.py and docs/plans/bof_emulator.md):
 *
 *     ID:\r         -> ID:NET <board>  <fw>     which port is the NET port
 *     CH:2000,01\r  -> CH:P                     the hardware config the game
 *                                               sends first (sent here only
 *                                               when SA: goes unanswered)
 *     SA:\r         -> SA:<n hex>,<hex bytes>   every switch's PHYSICAL level,
 *                                               switch k = bit k%8 of byte k/8
 *
 * Nothing else is ever sent: no switch or driver config, no watchdog, so no
 * coil can fire and the game finds the board exactly as power-up left it.
 * Unsolicited lines (-L:xx / /L:xx switch events of switches some earlier
 * run configured) are read and ignored.
 *
 * WHICH PORT.  The Neuron enumerates as two ttyACM ports (NET and the
 * expansion bus) and Labyrinth also has a FAST Audio Controller on a third.
 * The game's older driver takes "every ttyACM except the Audio Controller";
 * this does the same - a port whose USB product names "Audio" is skipped -
 * and then asks each one ID: and keeps the one that answers ID:NET.
 * --fast DEV names the port outright (the tests' pty), and
 * PAD_SELECT_FAST_ROOT=<dir> looks for <dir>/dev/ttyACM* and their USB names
 * under <dir>/sys instead - the BOF emulator's rig directory, whose bofhw.py
 * lays out exactly that (tools/bof_emu), so the search itself is tested.
 *
 * PRESSED = DIFFERENT FROM HOW IT WAS AT THE START.  SA: is physical, and a
 * title marks some switches `reversed` (the game applies that itself), so
 * whether a cabinet button reads 1 or 0 at rest is the title's wiring, not a
 * constant.  The first SA: reply is taken as everything at rest, and a
 * button is pressed while its level differs from that.  A button that was
 * HELD when the menu started would then read pressed from the moment it is
 * let go, for good - so a switch that has read "pressed" without a break
 * for RELEARN_MS is taken to be at rest after all, its level adopted, and
 * the button works again from there (logged).  Nobody holds a flipper for
 * three seconds in a menu; a stuck button costs that button three seconds,
 * and the countdown boots the highlighted image whatever happens.
 *
 * THE SWITCH NUMBERS come from images.conf (switch_left= / switch_right= /
 * switch_start=, a second number after a comma for a second button that
 * should do the same: Labyrinth's LAUNCH beside START), written by the
 * builder from the title's own switch table; absent = Labyrinth's (LOWER
 * LEFT FLIPPER 15, LOWER RIGHT FLIPPER 22, START 14).
 *
 * A BOARD THAT IS NOT THERE IS NOT AN ERROR.  The menu runs, times out and
 * boots the highlighted image - the rule every backend follows: a dead button
 * must never keep a pinball machine from booting.  The probe is retried every
 * OPEN_MS, and every failure is one log line, not one per attempt.
 *
 * --learn logs every switch that changes (and queues it as a raw event the
 * menu shows on the glass), which is how another title's buttons are read
 * instead of guessed.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <unistd.h>
#include <poll.h>
#include <pthread.h>
#include <termios.h>
#include "input.h"
#include "log.h"

#define POLL_MS       25          /* one SA: every 25 ms: 40 Hz, twice the debouncer's need */
#define OPEN_MS       1000        /* the probe again, when no port answered */
#define ID_WAIT_MS    400         /* how long a port gets to answer ID: */
#define CH_AFTER_MS   500         /* SA: unanswered this long: send CH: once */
#define DEAD_MS       4000        /* ...and this long: drop the port, probe again */
#define NSW_BYTES     32          /* up to 256 switches in one SA: reply */
#define RELEARN_MS    3000        /* "pressed" this long without a break = that is its rest level */

#define NBTN 3
static const int DEF_SW[NBTN] = { 15, 22, 14 };   /* Labyrinth: LL flipper, LR flipper, START */
static const int EV_OF[NBTN] = { EV_LEFT, EV_RIGHT, EV_START };
static const char *const NAME_OF[NBTN] = { "LEFT", "RIGHT", "START" };

struct fast {
    struct input base;
    char dev[512];               /* the one named, or "" = probe /dev/ttyACM* */
    char opened[512];
    int fd;
    int sw[NBTN], sw2[NBTN];     /* switch numbers; sw2 -1 = none */
    int learn;
    pthread_t th;
    int th_on, th_stop;
    long long next_open, last_sa, last_reply, first_sa;
    int ch_sent, open_logged;
    char rx[1024];
    int rxn;
    unsigned char rest[NSW_BYTES], prev[NSW_BYTES];
    long long away_since[NSW_BYTES * 8];   /* when a mapped switch left its rest level (0 = at rest) */
    int have_rest, nbytes;
    long long replies, sent, reopens, bad;
};

static int set_raw(int fd)
{
    struct termios t;
    if (tcgetattr(fd, &t) < 0) return -1;
    cfmakeraw(&t);
    t.c_cflag |= CLOCAL | CREAD;
    t.c_cc[VMIN] = 0;
    t.c_cc[VTIME] = 0;
#ifdef B921600
    cfsetispeed(&t, B921600);
    cfsetospeed(&t, B921600);
#endif
    if (tcsetattr(fd, TCSANOW, &t) < 0) return -1;
    tcflush(fd, TCIOFLUSH);
    return 0;
}

static int put(int fd, const char *s)
{
    size_t n = strlen(s), done = 0;
    while (done < n) {
        ssize_t w = write(fd, s + done, n - done);
        if (w < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN) { sel_sleep_ms(1); continue; }
            return -1;
        }
        done += (size_t)w;
    }
    return 0;
}

/* one line out of fd within wait_ms ('\r' or '\n' ended, without it); 1 got
 * one, 0 none in time, -1 the port failed */
static int read_line(int fd, char *rx, int *rxn, int rxcap, char *line, int cap, int wait_ms)
{
    long long until = sel_now_ms() + wait_ms;
    for (;;) {
        int i;
        for (i = 0; i < *rxn; i++) {
            if (rx[i] == '\r' || rx[i] == '\n') {
                int len = i < cap - 1 ? i : cap - 1;
                memcpy(line, rx, (size_t)len);
                line[len] = 0;
                memmove(rx, rx + i + 1, (size_t)(*rxn - i - 1));
                *rxn -= i + 1;
                if (len == 0) { i = -1; continue; }   /* an empty line between \r and \n */
                return 1;
            }
        }
        if (*rxn >= rxcap) *rxn = 0;          /* a line longer than the buffer: noise, dropped */
        {
            struct pollfd p = { fd, POLLIN, 0 };
            long long left = until - sel_now_ms();
            ssize_t n;
            if (left <= 0) return 0;
            if (poll(&p, 1, (int)left) <= 0) return 0;
            if (p.revents & (POLLERR | POLLHUP | POLLNVAL)) return -1;
            n = read(fd, rx + *rxn, (size_t)(rxcap - *rxn));
            if (n < 0) { if (errno == EINTR || errno == EAGAIN) continue; return -1; }
            if (n == 0) return -1;
            *rxn += (int)n;
        }
    }
}

/* where /dev and /sys are: "" on a machine, the rig directory in a test */
static const char *fast_root(void)
{
    const char *r = getenv("PAD_SELECT_FAST_ROOT");
    return r ? r : "";
}

/* the USB product name behind /dev/ttyACMn, or "" */
static void product_of(const char *dev, char *out, int cap)
{
    const char *base = strrchr(dev, '/');
    char path[768];
    FILE *f;
    out[0] = 0;
    base = base ? base + 1 : dev;
    /* .../ttyACMn/device is the USB interface; its parent is the device */
    snprintf(path, sizeof path, "%s/sys/class/tty/%s/device/../product", fast_root(), base);
    f = fopen(path, "r");
    if (!f) return;
    if (fgets(out, cap, f)) out[strcspn(out, "\r\n")] = 0;
    fclose(f);
}

/* ID: on one port: 1 it is the NET port (left open in f->fd), 0 it is not */
static int try_port(struct fast *f, const char *dev)
{
    char line[256];
    int fd, got;
    long long until;
    fd = open(dev, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        if (!f->open_logged) sel_log("fast: cannot open %s: %s", dev, strerror(errno));
        return 0;
    }
    if (set_raw(fd) < 0 && !f->open_logged)
        sel_log("fast: %s: cannot set raw 921600 (%s), trying anyway", dev, strerror(errno));
    f->rxn = 0;
    if (put(fd, "ID:\r") < 0) { close(fd); return 0; }
    until = sel_now_ms() + ID_WAIT_MS;
    while ((got = read_line(fd, f->rx, &f->rxn, (int)sizeof f->rx, line, (int)sizeof line,
                            (int)(until - sel_now_ms()))) == 1) {
        if (!strncmp(line, "ID:NET", 6)) {
            f->fd = fd;
            snprintf(f->opened, sizeof f->opened, "%s", dev);
            sel_log("fast: %s is the NET port (%s); LEFT %d, RIGHT %d, START %d%s", dev, line,
                    f->sw[0], f->sw[1], f->sw[2], f->learn ? ", learning" : "");
            {
                int k;
                for (k = 0; k < NBTN; k++)
                    if (f->sw2[k] >= 0) sel_log("fast: %s also on switch %d", NAME_OF[k], f->sw2[k]);
            }
            return 1;
        }
        if (sel_now_ms() >= until) break;
    }
    if (!f->open_logged) sel_log("fast: %s did not answer ID:NET", dev);
    close(fd);
    return 0;
}

static int probe(struct fast *f)
{
    glob_t g;
    size_t i;
    int found = 0;
    if (f->dev[0]) {
        found = try_port(f, f->dev);
    } else {
        char pat[600];
        snprintf(pat, sizeof pat, "%s/dev/ttyACM*", fast_root());
        if (glob(pat, 0, NULL, &g) != 0) {
            if (!f->open_logged) sel_log("fast: no %s port", pat);
            goto none;
        }
        /* the game's rule first - every port but the Audio Controller - then
         * ID: on what is left, in order */
        char *skip = calloc(g.gl_pathc ? g.gl_pathc : 1, 1);
        for (i = 0; i < g.gl_pathc; i++) {
            char prod[128];
            product_of(g.gl_pathv[i], prod, (int)sizeof prod);
            if (strstr(prod, "Audio")) {
                if (skip) skip[i] = 1;
                if (!f->open_logged) sel_log("fast: %s is the %s, skipped", g.gl_pathv[i], prod);
            }
        }
        for (i = 0; i < g.gl_pathc && !found; i++)
            if (!skip || !skip[i]) found = try_port(f, g.gl_pathv[i]);
        free(skip);
        globfree(&g);
    }
none:
    if (found) {
        long long now = sel_now_ms();
        f->open_logged = 0;
        f->have_rest = 0;
        memset(f->away_since, 0, sizeof f->away_since);
        f->ch_sent = 0;
        f->first_sa = 0;
        f->last_reply = now;
        f->last_sa = 0;
        return 0;
    }
    if (!f->open_logged) {
        sel_log("fast: no FAST NET port answered - the menu has no buttons until one does");
        f->open_logged = 1;
    }
    return -1;
}

static void drop(struct fast *f, const char *why)
{
    sel_log("fast: %s: %s - closing, will look again", f->opened[0] ? f->opened : "?", why);
    close(f->fd);
    f->fd = -1;
    f->reopens++;
    f->next_open = sel_now_ms() + OPEN_MS;
}

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int level(const unsigned char *b, int nbytes, int sw)
{
    if (sw < 0 || sw / 8 >= nbytes) return 0;
    return (b[sw / 8] >> (sw % 8)) & 1;
}

/* SA:<n>,<hex>: the levels, then the buttons */
static void on_sa(struct fast *f, const char *arg)
{
    unsigned char now[NSW_BYTES];
    const char *hex = strchr(arg, ',');
    int n = 0, k;
    memset(now, 0, sizeof now);
    if (!hex) { f->bad++; return; }
    for (hex++; hex[0] && hex[1] && n < NSW_BYTES; hex += 2) {
        int hi = hexval((unsigned char)hex[0]), lo = hexval((unsigned char)hex[1]);
        if (hi < 0 || lo < 0) break;
        now[n++] = (unsigned char)(hi << 4 | lo);
    }
    if (!n) { f->bad++; return; }
    f->replies++;
    if (!f->have_rest) {
        memcpy(f->rest, now, sizeof now);
        memcpy(f->prev, now, sizeof now);
        f->nbytes = n;
        f->have_rest = 1;
        sel_log("fast: %d switches read; at rest LEFT %d, RIGHT %d, START %d", n * 8,
                level(now, n, f->sw[0]), level(now, n, f->sw[1]), level(now, n, f->sw[2]));
        return;
    }
    if (n < f->nbytes) n = f->nbytes;
    /* a mapped switch away from its rest level for RELEARN_MS: that level
     * IS its rest (it was held when the menu started) */
    {
        long long t = sel_now_ms();
        for (k = 0; k < NBTN * 2; k++) {
            int sw = k < NBTN ? f->sw[k] : f->sw2[k - NBTN];
            if (sw < 0) continue;
            if (level(now, n, sw) == level(f->rest, n, sw)) {
                f->away_since[sw] = 0;
            } else if (!f->away_since[sw]) {
                f->away_since[sw] = t;
            } else if (t - f->away_since[sw] >= RELEARN_MS) {
                f->rest[sw / 8] ^= (unsigned char)(1u << (sw % 8));
                f->away_since[sw] = 0;
                sel_log("fast: switch %d read %d for %d s without a break - taken as its rest level",
                        sw, level(now, n, sw), RELEARN_MS / 1000);
            }
        }
    }
    for (k = 0; k < NBTN; k++) {
        int pressed = level(now, n, f->sw[k]) != level(f->rest, n, f->sw[k]);
        if (f->sw2[k] >= 0 && level(now, n, f->sw2[k]) != level(f->rest, n, f->sw2[k])) pressed = 1;
        input_sample(&f->base, KEY_OF(EV_OF[k]), pressed);
    }
    if (f->learn) {
        int b, bit;
        for (b = 0; b < n; b++) {
            unsigned d = (unsigned)(now[b] ^ f->prev[b]);
            for (bit = 0; bit < 8 && d; bit++) {
                int sw = b * 8 + bit, mapped = 0, m;
                if (!(d & (1u << bit))) continue;
                for (m = 0; m < NBTN; m++)
                    if (f->sw[m] == sw || f->sw2[m] == sw) mapped = 1;
                sel_log("fast: learn: switch %d -> %d (%s)", sw, (now[b] >> bit) & 1,
                        ((now[b] ^ f->rest[b]) >> bit) & 1 ? "pressed" : "released");
                if (!mapped) input_raw(&f->base, EV_RAW(b, bit, ((now[b] ^ f->rest[b]) >> bit) & 1));
            }
        }
    }
    memcpy(f->prev, now, sizeof now);
}

static void one_pass(struct fast *f)
{
    char line[512];
    long long now = sel_now_ms();
    int r;
    if (now - f->last_sa >= POLL_MS) {
        if (put(f->fd, "SA:\r") < 0) { drop(f, strerror(errno)); return; }
        f->sent++;
        f->last_sa = now;
        if (!f->first_sa) f->first_sa = now;
    }
    while ((r = read_line(f->fd, f->rx, &f->rxn, (int)sizeof f->rx, line, (int)sizeof line, 5)) == 1) {
        if (!strncmp(line, "SA:", 3)) {
            f->last_reply = sel_now_ms();
            on_sa(f, line + 3);
        }
        /* anything else (CH:P, -L:xx, /L:xx, WD:...) is not the menu's */
    }
    if (r < 0) { drop(f, "the port went away"); return; }
    now = sel_now_ms();
    if (!f->have_rest && !f->ch_sent && f->first_sa && now - f->first_sa >= CH_AFTER_MS) {
        sel_log("fast: SA: unanswered for %d ms - sending CH:2000,01 as the game does first", CH_AFTER_MS);
        if (put(f->fd, "CH:2000,01\r") < 0) { drop(f, strerror(errno)); return; }
        f->ch_sent = 1;
    }
    if (now - f->last_reply >= DEAD_MS) drop(f, "no SA: reply");
}

static void *fast_thread(void *p)
{
    struct fast *f = p;
    while (!f->th_stop) {
        long long now = sel_now_ms();
        if (f->fd < 0) {
            if (now >= f->next_open && probe(f) < 0) f->next_open = now + OPEN_MS;
            sel_sleep_ms(50);
            continue;
        }
        one_pass(f);
        sel_sleep_ms(5);
    }
    return NULL;
}

static void fast_poll(struct input *in, long long now_ms)
{
    (void)in; (void)now_ms;          /* threaded: the base only dequeues */
}

static void fast_close(struct input *in)
{
    struct fast *f = (struct fast *)in;
    if (f->th_on) {
        f->th_stop = 1;
        pthread_join(f->th, NULL);
        f->th_on = 0;
    }
    sel_log("fast: %lld SA: sent, %lld replies, %lld unreadable, %lld reopen(s)",
            f->sent, f->replies, f->bad, f->reopens);
    if (f->fd >= 0) close(f->fd);
    f->fd = -1;
    pthread_mutex_destroy(&f->base.lock);
    free(f);
}

static const struct input_ops fast_ops = { fast_poll, fast_close };

struct input *input_fast_open(const struct input_cfg *cfg)
{
    struct fast *f = calloc(1, sizeof *f);
    int k;
    if (!f) return NULL;
    input_base_init(&f->base, &fast_ops);
    f->base.threaded = 1;
    f->fd = -1;
    if (cfg->fast && *cfg->fast) snprintf(f->dev, sizeof f->dev, "%s", cfg->fast);
    for (k = 0; k < NBTN; k++) {
        int s = cfg->fast_sw[k], s2 = cfg->fast_sw2[k];
        f->sw[k] = s >= 0 && s < NSW_BYTES * 8 ? s : DEF_SW[k];
        f->sw2[k] = s2 >= 0 && s2 < NSW_BYTES * 8 ? s2 : -1;
    }
    f->learn = cfg->jjp_learn;
    /* what this cabinet has for the menu: the two flippers and START */
    for (k = 0; k < KEY_COUNT; k++) f->base.present[k] = 0;
    for (k = 0; k < NBTN; k++) f->base.present[KEY_OF(EV_OF[k])] = 1;
    if (pthread_create(&f->th, NULL, fast_thread, f) == 0) {
        f->th_on = 1;
    } else {
        sel_log("fast: cannot start the input thread: %s - no buttons", strerror(errno));
    }
    return &f->base;
}
