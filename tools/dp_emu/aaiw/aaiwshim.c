/* aaiwshim.c - a fake P-ROC and switch input for Dutch Pinball's Alice's
 * Adventures in Wonderland (AAIW), preloaded into its game program.
 *
 * AAIW is not The Big Lebowski's Python framework: /opt/pinterface is a
 * stripped native C++ program (Buildroot, SDL2) with libpinproc compiled in,
 * and it has NO simulator - with no P-ROC it plays attract under a red
 * "PROC MISSING" and never starts a game.  libpinproc talks to the board
 * through libftdi1, which the program links dynamically; so this shim
 * replaces the libftdi1 calls and answers them the way a P-ROC's FPGA does
 * (chip id, version, switch state registers), keeps every switch where the
 * machine at rest has it (AAIW_CLOSED: the switches closed at boot - the
 * closed-at-rest ones plus the balls in the trough), and turns a press into
 * the switch event word the game reads.  Coil, lamp and LED writes are
 * accepted and dropped.  (Worked out and first proven by a PAD-263
 * investigation, 2026-09-29: Start begins a game, pop bumpers score.)
 *
 * Commands, one per line, on the FIFO named by $DPEMU_FIFO:
 *     sw <n> c|o            P-ROC switch n closed / open (and stays so)
 *     pulse <n> [ms]        switch n to the other state for ms (default
 *                           200), then back - a hit on any switch, whatever
 *                           its rest state
 *     down <sym> | up <sym> an SDL2 key (the program's own key handler: 1
 *     tap <sym> [ms]        Start, Shift the flippers ...)
 * An empty line is ignored (dpctl.py's "is anyone reading?").
 *
 * It also logs every window the game opens ($DPEMU_LOG: "video: WxH@X,Y"),
 * and on a desktop ($DPEMU_FRAME) gives each a frame and a place on screen,
 * and puts $DPEMU_LABEL in front of its title.
 *
 * Loaded through the chroot's /etc/ld.so.preload (the root's busybox env/sh
 * drop LD_PRELOAD).  It must not need a glibc newer than the root's 2.37:
 * built on a newer host, sscanf/strtoul would bind to 2.38's __isoc23_*
 * versions - so every number here is parsed by hand, and run_aaiw.sh
 * refuses a build that asks for GLIBC_2.38 or later.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ------------------------------------------------------------------ util */
static void logf_(const char *fmt, ...)
{
    const char *path = getenv("DPEMU_LOG");
    FILE *f;
    va_list ap;
    if (!path || !(f = fopen(path, "a")))
        return;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fclose(f);
}

static double now_s(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

/* "123" -> 123 (hex after 0x); *p is left after the number.  -1 if none. */
static long num(const char **p)
{
    const char *s = *p;
    long v = 0;
    int base = 10, any = 0;
    while (*s == ' ')
        s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        base = 16;
        s += 2;
    }
    for (;; s++) {
        int c = *s, d;
        if (c >= '0' && c <= '9')
            d = c - '0';
        else if (base == 16 && (c | 32) >= 'a' && (c | 32) <= 'f')
            d = (c | 32) - 'a' + 10;
        else
            break;
        v = v * base + d;
        any = 1;
    }
    *p = s;
    return any ? v : -1;
}

/* ------------------------------------------------------ the fake P-ROC */
struct ftdi_device_list { struct ftdi_device_list *next; void *dev; };

static pthread_mutex_t pmx = PTHREAD_MUTEX_INITIALIZER;
static uint32_t sw_state[64];      /* bit = 1: open (P-ROC convention) */
static int sw_init;
static uint8_t outq[1 << 20];
static size_t out_h, out_t;        /* bytes for ftdi_read_data */
static uint8_t inb[4];
static int inb_n;
static uint32_t burst_left;        /* data words after a write header */
static int is_p3;

static void out_word(uint32_t w)
{
    for (int k = 3; k >= 0; k--) {
        outq[out_t] = (uint8_t)(w >> (k * 8));
        out_t = (out_t + 1) & (sizeof outq - 1);
    }
}

static void sw_setup(void)
{
    const char *c, *p;
    if (sw_init)
        return;
    sw_init = 1;
    for (int i = 0; i < 64; i++)
        sw_state[i] = 0xffffffffu;
    c = getenv("AAIW_CLOSED");
    while (c && *c) {
        long n = num(&c);
        if (n >= 0 && n < 2048)
            sw_state[n / 32] &= ~(1u << (n % 32));
        if (*c)
            c++;
    }
    p = getenv("AAIW_PROC_CHIP");
    is_p3 = p && !strcmp(p, "p3");
}

static int sw_closed(int n)
{
    return !(sw_state[n / 32] & (1u << (n % 32)));
}

static uint32_t reg_read(uint32_t sel, uint32_t addr)
{
    if (sel == 0) {
        switch (addr) {
        case 0: return is_p3 ? 0xf33db33fu : 0xfeedbeefu;   /* chip id */
        case 1: return (2u << 16) | 0x10;                    /* version 2.16 */
        default: return 0;               /* watchdog, dip switches: 0 */
        }
    }
    if (sel == 2) {
        uint32_t sb = is_p3 ? 16 : 4, db = is_p3 ? 32 : 12;
        if (addr >= sb && addr < sb + 16)
            return sw_state[addr - sb];
        if (addr >= db && addr < db + 16)
            return 0xffffffffu;
        if (!is_p3 && addr == 11)
            return 0xffffffffu;
    }
    return 0;
}

static void handle_word(uint32_t w)
{
    uint32_t len = (w >> 20) & 0x7ff, sel = (w >> 16) & 0xf, addr = w & 0xffff;
    if (burst_left) {
        burst_left--;
        return;
    }
    if (w >> 31) {                         /* a write burst's header */
        if (w != 0x801F1122u)              /* init pattern A */
            burst_left = len;
        return;
    }
    if (w == 0x345678ABu)                  /* init pattern B */
        return;
    out_word(w & 0x7fffffffu);             /* a read: header + len words */
    for (uint32_t i = 0; i < len; i++)
        out_word(reg_read(sel, addr + i));
}

static void proc_switch(int n, int closed)
{
    if (n < 0 || n >= 2048)
        return;
    pthread_mutex_lock(&pmx);
    sw_setup();
    if (closed)
        sw_state[n / 32] &= ~(1u << (n % 32));
    else
        sw_state[n / 32] |= 1u << (n % 32);
    out_word(0x80000000u);                 /* unrequested data: an event */
    out_word((n & 0x7ff) | (closed ? 0 : 0x1000) | 0x2000);
    pthread_mutex_unlock(&pmx);
}

int ftdi_init(void *ctx) { (void)ctx; return 0; }
void ftdi_deinit(void *ctx) { (void)ctx; }
int ftdi_usb_find_all(void *ctx, struct ftdi_device_list **devlist, int vendor, int product)
{
    (void)ctx; (void)vendor; (void)product;
    *devlist = calloc(1, sizeof **devlist);
    return 1;
}
void ftdi_list_free(struct ftdi_device_list **devlist)
{
    if (devlist && *devlist) {
        free(*devlist);
        *devlist = 0;
    }
}
int ftdi_usb_get_strings(void *ctx, void *dev, char *m, int ml, char *d, int dl, char *s, int sl)
{
    (void)ctx; (void)dev; (void)s; (void)sl;
    if (m && ml)
        snprintf(m, ml, "Multimorphic");
    if (d && dl)
        snprintf(d, dl, "PAD emulated P-ROC");
    return 0;
}
int ftdi_usb_open(void *ctx, int vendor, int product)
{
    (void)ctx; (void)vendor; (void)product;
    pthread_mutex_lock(&pmx);
    sw_setup();
    pthread_mutex_unlock(&pmx);
    logf_("proc: open (%s)\n", is_p3 ? "P3-ROC" : "P-ROC");
    return 0;
}
int ftdi_usb_close(void *ctx) { (void)ctx; return 0; }
int ftdi_read_chipid(void *ctx, unsigned int *id) { (void)ctx; if (id) *id = 0x12345678; return 0; }
int ftdi_read_data_set_chunksize(void *ctx, unsigned int c) { (void)ctx; (void)c; return 0; }
int ftdi_set_latency_timer(void *ctx, unsigned char l) { (void)ctx; (void)l; return 0; }
char *ftdi_get_error_string(void *ctx) { (void)ctx; return (char *)"emulated P-ROC"; }

int ftdi_write_data(void *ctx, const unsigned char *buf, int size)
{
    (void)ctx;
    pthread_mutex_lock(&pmx);
    sw_setup();
    for (int i = 0; i < size; i++) {
        inb[inb_n++] = buf[i];
        if (inb_n == 4) {
            handle_word(((uint32_t)inb[0] << 24) | ((uint32_t)inb[1] << 16) |
                        ((uint32_t)inb[2] << 8) | inb[3]);
            inb_n = 0;
        }
    }
    pthread_mutex_unlock(&pmx);
    return size;
}

static void pump(void);

int ftdi_read_data(void *ctx, unsigned char *buf, int size)
{
    int n = 0;
    (void)ctx;
    /* a program with no SDL event loop (the TBL boot menu's dpprocsw,
     * PAD-853) reads its presses here */
    pump();
    pthread_mutex_lock(&pmx);
    while (n < size && out_h != out_t) {
        buf[n++] = outq[out_h];
        out_h = (out_h + 1) & (sizeof outq - 1);
    }
    pthread_mutex_unlock(&pmx);
    return n;
}

/* ------------------------------------------------------ the FIFO, keys */
/* SDL2 events are handed out from SDL_PollEvent, on the game's own thread:
 * a queue of keys, and timed switch returns for pulse/tap. */
#define Q 64
static uint32_t q_type[Q], q_sym[Q];
static double q_at[Q];
static int qh, qt;
static struct { int n, closed; double at; } later[32];
static int fifo = -2;
static char lb[512];
static int lbn;

static void push_key(uint32_t type, uint32_t sym, double at)
{
    int n = (qt + 1) % Q;
    if (n == qh)
        return;
    q_type[qt] = type;
    q_sym[qt] = sym;
    q_at[qt] = at;
    qt = n;
}

static void at_later(int n, int closed, double at)
{
    for (int i = 0; i < 32; i++)
        if (!later[i].at) {
            later[i].n = n;
            later[i].closed = closed;
            later[i].at = at;
            return;
        }
}

static void run_line(const char *t)
{
    const char *p;
    long a, b;
    if (!strncmp(t, "sw ", 3)) {
        p = t + 3;
        a = num(&p);
        while (*p == ' ')
            p++;
        if (a >= 0 && (*p == 'c' || *p == 'o'))
            proc_switch((int)a, *p == 'c');
    } else if (!strncmp(t, "pulse ", 6)) {
        p = t + 6;
        a = num(&p);
        b = num(&p);
        if (a >= 0 && a < 2048) {
            int was;
            pthread_mutex_lock(&pmx);
            sw_setup();
            was = sw_closed((int)a);
            pthread_mutex_unlock(&pmx);
            proc_switch((int)a, !was);
            at_later((int)a, was, now_s() + (b > 0 ? b : 200) / 1000.0);
        }
    } else if (!strncmp(t, "down ", 5) || !strncmp(t, "up ", 3)) {
        int down = t[0] == 'd';
        p = t + (down ? 5 : 3);
        a = num(&p);
        if (a > 0)
            push_key(down ? 0x300 : 0x301, (uint32_t)a, 0);
    } else if (!strncmp(t, "tap ", 4)) {
        p = t + 4;
        a = num(&p);
        b = num(&p);
        if (a > 0) {
            push_key(0x300, (uint32_t)a, 0);
            push_key(0x301, (uint32_t)a, now_s() + (b > 0 ? b : 150) / 1000.0);
        }
    } else
        return;
    logf_("input: %s\n", t);
}

static void pump_one(void)
{
    double now = now_s();
    for (int i = 0; i < 32; i++)
        if (later[i].at && now >= later[i].at) {
            later[i].at = 0;
            proc_switch(later[i].n, later[i].closed);
        }
    if (fifo == -2) {
        const char *path = getenv("DPEMU_FIFO");
        fifo = path ? open(path, O_RDWR | O_NONBLOCK) : -1;
        if (fifo >= 0)
            logf_("input: listening on %s\n", path);
    }
    if (fifo < 0)
        return;
    for (;;) {
        int r = (int)read(fifo, lb + lbn, sizeof lb - 1 - lbn);
        char *nl;
        if (r <= 0)
            break;
        lbn += r;
        lb[lbn] = 0;
        while ((nl = memchr(lb, '\n', lbn))) {
            int used = (int)(nl - lb) + 1;
            *nl = 0;
            if (nl > lb && nl[-1] == '\r')
                nl[-1] = 0;
            if (lb[0])
                run_line(lb);
            memmove(lb, nl + 1, lbn - used);
            lbn -= used;
        }
        if (lbn >= (int)sizeof lb - 1)
            lbn = 0;
    }
}

/* the game's SDL thread and its P-ROC reads both pump; one at a time */
static void pump(void)
{
    static pthread_mutex_t pumpmx = PTHREAD_MUTEX_INITIALIZER;
    if (pthread_mutex_trylock(&pumpmx))
        return;
    pump_one();
    pthread_mutex_unlock(&pumpmx);
}

int SDL_PollEvent(void *ev)
{
    static int (*real)(void *);
    if (!real)
        real = (int (*)(void *))dlsym(RTLD_NEXT, "SDL_PollEvent");
    pump();
    if (qh != qt && ev && now_s() >= q_at[qh]) {
        unsigned char *e = ev;
        uint32_t type = q_type[qh], sym = q_sym[qh];
        qh = (qh + 1) % Q;
        memset(e, 0, 56);                  /* sizeof(SDL_Event) */
        memcpy(e, &type, 4);               /* SDL_KeyboardEvent.type */
        e[12] = type == 0x300;             /* .state */
        memcpy(e + 20, &sym, 4);           /* .keysym.sym */
        return 1;
    }
    return real ? real(ev) : 0;
}

/* ------------------------------------------------------------- sound */
/* The root's SDL2 was built with ALSA only - no PulseAudio driver, and no
 * ALSA pulse plugin - so on a PC its sound goes out through SDL's "disk"
 * driver into a FIFO that run_aaiw.sh's relay plays to WSLg's PulseAudio.
 * The relay has to know the stream's format: log what the game opens. */
int Mix_OpenAudio(int frequency, uint16_t format, int channels, int chunksize)
{
    static int (*real)(int, uint16_t, int, int);
    if (!real)
        real = (int (*)(int, uint16_t, int, int))dlsym(RTLD_NEXT, "Mix_OpenAudio");
    logf_("audio: %d 0x%x %d\n", frequency, format, channels);
    return real ? real(frequency, format, channels, chunksize) : -1;
}

/* ----------------------------------------------------------- windows */
#define SDL_WINDOW_FULLSCREEN 0x00000001u
#define SDL_WINDOW_BORDERLESS 0x00000010u
#define SDL_WINDOW_FULLSCREEN_DESKTOP 0x00001001u
void *SDL_CreateWindow(const char *title, int x, int y, int w, int h, uint32_t flags)
{
    static void *(*real)(const char *, int, int, int, int, uint32_t);
    const char *label = getenv("DPEMU_LABEL");
    char buf[256];
    if (!real)
        real = (void *(*)(const char *, int, int, int, int, uint32_t))
            dlsym(RTLD_NEXT, "SDL_CreateWindow");
    if (getenv("DPEMU_FRAME")) {
        /* the cabinet's two screens become two ordinary windows, side by
         * side near the top left of the desktop */
        flags &= ~(SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_BORDERLESS);
        if (x >= 0 && x < 0x1FFF0000)
            x += 40;
        if (y >= 0 && y < 0x1FFF0000)
            y += 40;
    }
    if (label && *label && title) {
        snprintf(buf, sizeof buf, "%s - %s", label, title);
        title = buf;
    }
    logf_("video: %dx%d@%d,%d\n", w, h, x & 0xFFFF, y & 0xFFFF);
    return real ? real(title, x, y, w, h, flags) : NULL;
}
