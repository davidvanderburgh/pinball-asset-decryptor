/* codeselect.c - the boot-time code selector for Spike 2 (item 90).
 *
 * Shows one card per game image on the LCD, moves the highlight with the
 * flippers (or Service -/+), confirms with START (or Service Select), boots
 * the highlighted image when the countdown runs out, and writes the chosen
 * index to --out (and --last). Exit 0 = a choice was written, 2 = no choice.
 *
 *   --headless FILE.ppm   no EGL: run the loop, write the last menu frame as
 *                         a binary P6 PPM (and the LOADING frame beside it as
 *                         FILE.loading.ppm); with --input none the countdown
 *                         expires and the highlighted image is chosen.
 *
 * stdout lines are prefixed '[select] ' for the rig's event pane; stderr
 * (and --log) carry the diagnostics.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <errno.h>
#include "conf.h"
#include "gfx.h"
#include "egl_stern.h"
#include "input.h"
#include "log.h"

#define VERSION "1.0"

#define DEF_CONF     "/usr/local/codeselect/images.conf"
#define DEF_OUT      "/var/volatile/codeselect.choice"
#define DEF_LAST     "/data/codeselect.last"
#define DEF_FONT     "/usr/local/codeselect/font.ttf"
#define CARD_FONT    "/usr/local/spike/VeraMono.ttf"
#define BOOTDISP_CMD "/games/data/boot_display_cmd"
#define DEF_TIMEOUT  10
#define HEADLESS_W   1360
#define HEADLESS_H   768

struct opts {
    const char *conf, *out, *input, *nodebus, *spi, *padsw, *tables, *last, *log,
               *headless, *font, *preamble;
    int timeout;      /* -1 = from conf */
    int def;          /* -1 = from conf */
    int invert;       /* -1 = auto */
};

static volatile sig_atomic_t g_stop;

static void on_signal(int s)
{
    (void)s;
    g_stop = 1;
}

static void usage(FILE *f)
{
    fprintf(f,
        "codeselect " VERSION " - Spike 2 boot-time code selector\n"
        "  --conf PATH        images.conf (default " DEF_CONF ")\n"
        "  --out PATH         choice file, one line '<index>' (default " DEF_OUT ")\n"
        "  --input hw|padsw|none   button source (default hw)\n"
        "  --nodebus DEV      node bus tty (default /dev/ttymxc1)\n"
        "  --spi DEV          cabinet spidev, 'none' disables (default /dev/spidev1.0)\n"
        "  --padsw PATH       rig keyboard file (default $PAD_SW_SHM or /dump/padsw)\n"
        "  --tables PATH      switch_list.txt (default /dump/tables/$PAD_GAME/switch_list.txt)\n"
        "  --timeout SEC      countdown, 0 = wait for ever (overrides conf)\n"
        "  --last PATH        last-choice file (default " DEF_LAST ")\n"
        "  --default N        highlight when there is no last choice (overrides conf)\n"
        "  --log PATH         append diagnostics here (stderr always)\n"
        "  --headless FILE.ppm  no EGL; write the final menu frame as a P6 PPM\n"
        "  --invert / --no-invert  rotate 180 degrees (default: auto from " BOOTDISP_CMD ")\n"
        "  --preamble min|full  node-bus bring-up to replay before scanning (default min)\n"
        "  --font PATH        TrueType font (default conf font=, " DEF_FONT ", " CARD_FONT ")\n"
        "exit status: 0 = a choice was written, 2 = no choice\n");
}

static int parse_args(struct opts *o, int argc, char **argv)
{
    int i;
    memset(o, 0, sizeof *o);
    o->conf = DEF_CONF;
    o->out = DEF_OUT;
    o->input = "hw";
    o->nodebus = "/dev/ttymxc1";
    o->spi = "/dev/spidev1.0";
    o->last = DEF_LAST;
    o->preamble = "min";
    o->timeout = -1;
    o->def = -1;
    o->invert = -1;
    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : NULL;
#define ARG(name, field) if (!strcmp(a, name)) { if (!v) goto missing; o->field = v; i++; continue; }
        ARG("--conf", conf)
        ARG("--out", out)
        ARG("--input", input)
        ARG("--nodebus", nodebus)
        ARG("--spi", spi)
        ARG("--padsw", padsw)
        ARG("--tables", tables)
        ARG("--last", last)
        ARG("--log", log)
        ARG("--headless", headless)
        ARG("--font", font)
        ARG("--preamble", preamble)
#undef ARG
        if (!strcmp(a, "--timeout")) { if (!v) goto missing; o->timeout = atoi(v); i++; continue; }
        if (!strcmp(a, "--default")) { if (!v) goto missing; o->def = atoi(v); i++; continue; }
        if (!strcmp(a, "--invert")) { o->invert = 1; continue; }
        if (!strcmp(a, "--no-invert")) { o->invert = 0; continue; }
        if (!strcmp(a, "--help") || !strcmp(a, "-h")) { usage(stdout); exit(0); }
        fprintf(stderr, "codeselect: unknown option %s\n", a);
        usage(stderr);
        return -1;
missing:
        fprintf(stderr, "codeselect: %s needs a value\n", a);
        return -1;
    }
    if (strcmp(o->input, "hw") && strcmp(o->input, "padsw") && strcmp(o->input, "none")) {
        fprintf(stderr, "codeselect: --input must be hw, padsw or none\n");
        return -1;
    }
    if (strcmp(o->preamble, "min") && strcmp(o->preamble, "full")) {
        fprintf(stderr, "codeselect: --preamble must be min or full\n");
        return -1;
    }
    return 0;
}

/* boot_display's option file: fgets(500), CR/LF/TAB -> space, strtok ' ',
 * the same parser as its argv; '-invert' = rotate the picture 180 degrees. */
static int detect_invert(void)
{
    FILE *f = fopen(BOOTDISP_CMD, "r");
    char line[500];
    char *tok, *s;
    int inv = 0;
    if (!f) return 0;
    if (fgets(line, sizeof line, f)) {
        for (s = line; *s; s++)
            if (*s == '\r' || *s == '\n' || *s == '\t') *s = ' ';
        for (tok = strtok(line, " "); tok; tok = strtok(NULL, " "))
            if (!strcmp(tok, "-invert")) inv = 1;
    }
    fclose(f);
    sel_log("%s: %s", BOOTDISP_CMD, inv ? "-invert found" : "no -invert");
    return inv;
}

static struct gfx_font *load_font(const struct opts *o, const struct conf *c, char *used, int usedlen)
{
    const char *cand[4];
    int n = 0, i;
    if (o->font) cand[n++] = o->font;
    if (*c->font) cand[n++] = c->font;
    cand[n++] = DEF_FONT;
    cand[n++] = CARD_FONT;
    for (i = 0; i < n; i++) {
        struct gfx_font *f = gfx_font_load(cand[i]);
        if (f) { snprintf(used, (size_t)usedlen, "%s", cand[i]); return f; }
        sel_log("font: %s not usable", cand[i]);
    }
    return NULL;
}

/* ------------------------------------------------------------- the menu */

#define C_BG        0x0b0e13
#define C_TITLE     0xe8ecf1
#define C_CARD      0x171c24
#define C_CARD_HL   0x263041
#define C_FRAME     0x2c3542
#define C_FRAME_HL  0xffc42d
#define C_TEXT      0xb8c0cc
#define C_TEXT_HL   0xffffff
#define C_SUB       0x8a94a2
#define C_SUB_HL    0xd6dce4
#define C_LABEL     0x5d6673
#define C_LABEL_HL  0xffc42d
#define C_FOOT      0x7d8794
#define C_COUNT     0xffc42d

static void draw_menu(struct gfx *g, struct gfx_font *f, const struct conf *c,
                      int hl, int remain)
{
    float s = (float)g->h / 768.0f;
    int W = g->w;
    int n = c->n, i;
    int margin = (int)(60 * s), gap = (int)(36 * s);
    int top = (int)(150 * s), ch = (int)(420 * s);
    int cw = (W - 2 * margin - (n - 1) * gap) / n;
    char buf[300];

    gfx_fill(g, C_BG);
    gfx_text_center(g, f, 60 * s, W / 2, (int)(96 * s), "SELECT GAME CODE", C_TITLE);

    for (i = 0; i < n; i++) {
        const struct conf_image *im = &c->img[i];
        int x = margin + i * (cw + gap);
        int on = i == hl;
        int pad = (int)(28 * s);
        int inner = cw - 2 * pad;
        float tpx, spx;
        int base, tl, sub_y;
        char tlines[2][CONF_STR], lines[4][CONF_STR];
        int nl, k;

        gfx_round_frame(g, x, top, cw, ch, (int)(22 * s), (int)((on ? 8 : 3) * s),
                        on ? C_FRAME_HL : C_FRAME, on ? C_CARD_HL : C_CARD);
        snprintf(buf, sizeof buf, "IMAGE %d", i + 1);
        gfx_text_center(g, f, 22 * s, x + cw / 2, top + (int)(50 * s), buf, on ? C_LABEL_HL : C_LABEL);

        /* the title: shrink to fit down to 34 px; if it still does not fit,
         * wrap it onto two lines and shrink each of those */
        tpx = gfx_fit_px(f, im->title, inner, 62 * s, 34 * s);
        if (gfx_text_width(f, tpx, im->title) <= inner) {
            tl = 1;
            snprintf(tlines[0], CONF_STR, "%s", im->title);
        } else {
            tl = gfx_wrap(f, tpx, im->title, inner, &tlines[0][0], CONF_STR, 2);
            for (k = 0; k < tl; k++) tpx = gfx_fit_px(f, tlines[k], inner, tpx, 22 * s);
        }
        base = top + (int)((tl == 2 ? 0.36f : 0.42f) * ch);
        for (k = 0; k < tl; k++)
            gfx_text_center(g, f, tpx, x + cw / 2, base + (int)(k * tpx * 1.15f), tlines[k],
                            on ? C_TEXT_HL : C_TEXT);
        sub_y = base + (int)((tl - 1) * tpx * 1.15f) + (int)(62 * s);

        spx = gfx_fit_px(f, im->subtitle, inner * 2, 30 * s, 22 * s);
        nl = gfx_wrap(f, spx, im->subtitle, inner, &lines[0][0], CONF_STR, 4);
        for (k = 0; k < nl; k++)
            gfx_text_center(g, f, spx, x + cw / 2, sub_y + (int)(40 * k * s), lines[k],
                            on ? C_SUB_HL : C_SUB);
    }

    gfx_text_center(g, f, 30 * s, W / 2, (int)(648 * s),
                    "LEFT / RIGHT FLIPPER: choose      START: boot", C_FOOT);
    if (remain >= 0)
        snprintf(buf, sizeof buf, "booting %s in %d s", c->img[hl].title, remain);
    else
        snprintf(buf, sizeof buf, "press START to boot %s", c->img[hl].title);
    gfx_text_center(g, f, 38 * s, W / 2, (int)(718 * s), buf, C_COUNT);
}

static void draw_loading(struct gfx *g, struct gfx_font *f, const char *title)
{
    float s = (float)g->h / 768.0f;
    char buf[300];
    gfx_fill(g, C_BG);
    snprintf(buf, sizeof buf, "LOADING %s...", title);
    gfx_text_center(g, f, gfx_fit_px(f, buf, g->w - (int)(80 * s), 64 * s, 30 * s),
                    g->w / 2, (int)(400 * s), buf, C_TEXT_HL);
}

/* ------------------------------------------------------------------ main */

int main(int argc, char **argv)
{
    struct opts o;
    struct conf c;
    struct gfx g;
    struct gfx_font *font;
    struct egl_stern egl;
    struct input *in = NULL;
    struct input_cfg icfg;
    char err[300], fontpath[300], tables[400], padsw[400];
    int headless, invert, timeout, n, hl, chosen = -1, w, h;
    const char *how;
    long start, deadline, last_key;
    int remain_shown = -2, dirty;
    int rc = 2;
    const unsigned char *px;

    if (parse_args(&o, argc, argv) < 0) return 2;
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGHUP, on_signal);
    signal(SIGPIPE, SIG_IGN);
    sel_log_open(o.log);
    sel_log("codeselect " VERSION " starting (conf %s, input %s%s)", o.conf, o.input,
            o.headless ? ", headless" : "");

    if (conf_load(&c, o.conf, err, sizeof err) < 0) {
        sel_say("error: %s", err);
        return 2;
    }
    n = c.n;
    timeout = o.timeout >= 0 ? o.timeout : c.timeout >= 0 ? c.timeout : DEF_TIMEOUT;
    hl = conf_read_last(o.last);
    if (hl >= 0 && hl < n) how = "last choice";
    else if (o.def >= 0 && o.def < n) { hl = o.def; how = "--default"; }
    else if (c.def >= 0) { hl = c.def; how = "conf default"; }
    else { hl = 0; how = "first"; }
    headless = o.headless != NULL;
    invert = o.invert >= 0 ? o.invert : detect_invert();

    font = load_font(&o, &c, fontpath, sizeof fontpath);
    if (!font) {
        sel_say("error: no usable font (tried --font, conf font=, %s, %s)", DEF_FONT, CARD_FONT);
        return 2;
    }

    if (headless) {
        w = HEADLESS_W;
        h = HEADLESS_H;
    } else {
        if (egl_stern_init(&egl, 6, 500) < 0) {
            sel_say("error: display bring-up failed");
            gfx_font_free(font);
            return 2;
        }
        w = egl.w;
        h = egl.h;
    }
    if (gfx_init(&g, w, h) < 0) {
        sel_say("error: cannot allocate a %dx%d canvas", w, h);
        return 2;
    }

    memset(&icfg, 0, sizeof icfg);
    icfg.nodebus = o.nodebus;
    icfg.spi = o.spi;
    icfg.preamble_full = !strcmp(o.preamble, "full");
    if (o.padsw) snprintf(padsw, sizeof padsw, "%s", o.padsw);
    else snprintf(padsw, sizeof padsw, "%s", getenv("PAD_SW_SHM") ? getenv("PAD_SW_SHM") : "/dump/padsw");
    icfg.padsw = padsw;
    if (o.tables) snprintf(tables, sizeof tables, "%s", o.tables);
    else snprintf(tables, sizeof tables, "/dump/tables/%s/switch_list.txt",
                  getenv("PAD_GAME") ? getenv("PAD_GAME") : "");
    icfg.tables = tables;
    if (!strcmp(o.input, "hw")) in = input_hw_open(&icfg);
    else if (!strcmp(o.input, "padsw")) in = input_padsw_open(&icfg);

    sel_say("menu: %d image%s, highlight %d (%s) from %s, timeout %d s, input %s, invert %d, %dx%d, font %s",
            n, n == 1 ? "" : "s", hl, c.img[hl].title, how, timeout, o.input, invert, w, h, fontpath);

    start = sel_now_ms();
    last_key = start;
    deadline = timeout > 0 ? start + (long)timeout * 1000L : 0;
    draw_menu(&g, font, &c, hl, deadline ? timeout : -1);
    remain_shown = deadline ? timeout : -1;
    dirty = 0;
    px = gfx_pixels(&g, invert);
    if (!headless) egl_stern_texture(&egl, w, h, px);

    while (!g_stop) {
        long now = sel_now_ms();
        int ev, remain;

        while ((ev = input_poll(in, now)) != EV_NONE) {
            sel_say("key: %s", input_event_name(ev));
            switch (ev) {
            case EV_LEFT: case EV_MINUS:
                hl = (hl + n - 1) % n;
                dirty = 1;
                break;
            case EV_RIGHT: case EV_PLUS:
                hl = (hl + 1) % n;
                dirty = 1;
                break;
            case EV_START: case EV_SELECT:
                chosen = hl;
                break;
            default:
                break;                          /* BACK: ignored */
            }
            last_key = now;
            if (chosen >= 0) break;
        }
        if (chosen >= 0) break;
        if (deadline) {
            /* a key restarts the countdown so a reader is not cut off */
            if (last_key > start) { deadline = last_key + (long)timeout * 1000L; start = last_key; }
            if (now >= deadline) {
                sel_log("countdown expired: booting image %d", hl);
                chosen = hl;
                break;
            }
            remain = (int)((deadline - now + 999) / 1000);
        } else {
            remain = -1;
        }
        if (remain != remain_shown) { remain_shown = remain; dirty = 1; }
        if (dirty) {
            draw_menu(&g, font, &c, hl, remain);
            px = gfx_pixels(&g, invert);
            dirty = 0;
        } else {
            px = NULL;
        }
        if (headless) sel_sleep_ms(16);
        else egl_stern_frame(&egl, px);         /* swap EVERY frame */
    }

    if (chosen >= 0) {
        if (headless) {
            if (gfx_write_ppm(&g, o.headless, invert) < 0)
                sel_log("cannot write %s: %s", o.headless, strerror(errno));
            else
                sel_log("wrote %s (%dx%d)", o.headless, w, h);
        }
        draw_loading(&g, font, c.img[chosen].title);
        px = gfx_pixels(&g, invert);
        if (headless) {
            char lp[400];
            snprintf(lp, sizeof lp, "%s.loading.ppm", o.headless);
            gfx_write_ppm(&g, lp, invert);
        } else {
            egl_stern_frame(&egl, px);
        }
        if (conf_write_last(o.last, chosen) < 0)
            sel_log("cannot write %s: %s (continuing)", o.last, strerror(errno));
        if (conf_write_choice(o.out, chosen) < 0) {
            sel_say("error: cannot write %s: %s", o.out, strerror(errno));
        } else {
            sel_say("chose %d %s", chosen, c.img[chosen].title);
            rc = 0;
        }
    } else {
        sel_say("error: interrupted before a choice");
    }

    input_close(in);
    if (!headless) egl_stern_close(&egl);
    gfx_free(&g);
    gfx_font_free(font);
    sel_log("exit %d", rc);
    sel_log_close();
    return rc;
}
