/* codeselect.c - the boot-time code selector for Spike 2 (item 90).
 *
 * Shows one card per game image on the LCD (a row of up to four, a carousel
 * beyond that), moves the highlight with the flippers (or Service -/+),
 * confirms with START, with the lockdown-bar ACTION button or with Service
 * Select, boots the highlighted image when the countdown runs out, and writes
 * the chosen index to --out (and --last).
 * Exit 0 = a choice was written, 2 = no choice.
 *
 * Each card can carry a still picture (PNG), an animation (GIF, ticking only
 * while its card is highlighted) and a music loop; a move sound plays on
 * every highlight change and a confirm sound plays TO COMPLETION under the
 * LOADING frame before the program exits. Every media failure is non-fatal:
 * the menu runs without the piece that failed.
 *
 *   --headless FILE.ppm   no EGL: run the loop, write the last menu frame as
 *                         a binary P6 PPM (and the LOADING frame beside it as
 *                         FILE.loading.ppm); with --input none the countdown
 *                         expires and the highlighted image is chosen.
 *   --snapshot FILE.ppm   render ONE menu frame - what the machine shows the
 *                         moment the menu appears - as a P6 PPM and exit 0,
 *                         with no display, input, audio, choice or last file:
 *                         the Multi-boot tab's preview. --highlight N picks
 *                         the card, --anim-frame N its animation frame.
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
#include "art.h"
#include "audio.h"
#include "log.h"

#define VERSION "2.1"

#define DEF_CONF     "/usr/local/codeselect/images.conf"
#define DEF_OUT      "/var/volatile/codeselect.choice"
#define DEF_LAST     "/data/codeselect.last"
#define DEF_FONT     "/usr/local/codeselect/font.ttf"
#define DEF_MEDIA    "/usr/local/codeselect/media"
#define CARD_FONT    "/usr/local/spike/VeraMono.ttf"
#define BOOTDISP_CMD "/games/data/boot_display_cmd"
#define DEF_TIMEOUT  10
#define DEF_VOLUME   50
#define HEADLESS_W   1360
#define HEADLESS_H   768
#define MAX_VISIBLE  4              /* cards in a row; more = carousel */
#define ANIM_MAX_FRAMES 30
#define CONFIRM_CAP_MS 8000

struct opts {
    const char *conf, *out, *input, *nodebus, *spi, *padsw, *tables, *last, *log,
               *headless, *font, *preamble, *media, *audio, *audio_fmt, *audio_dump,
               *snapshot;
    int timeout;      /* -1 = from conf */
    int def;          /* -1 = from conf */
    int invert;       /* -1 = auto */
    int volume;       /* -1 = from conf */
    int anim_frame;   /* -1 = animate; else every animation shows this frame */
    int highlight;    /* --snapshot: the highlighted card; -1 = the conf default */
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
        "  --snapshot FILE.ppm  render ONE menu frame as a P6 PPM and exit: no display, input,\n"
        "                     audio, choice or last file (the preview)\n"
        "  --highlight N      --snapshot only: the highlighted card (default conf default=, else 0;\n"
        "                     the last-choice file is never read)\n"
        "  --invert / --no-invert  rotate 180 degrees (default: auto from " BOOTDISP_CMD ")\n"
        "  --preamble min|full  node-bus bring-up to replay before scanning (default min)\n"
        "  --font PATH        TrueType font (default conf font=, " DEF_FONT ", " CARD_FONT ")\n"
        "  --media DIR        where the conf's media names live (default conf media=, " DEF_MEDIA ")\n"
        "  --audio auto|alsa|fifo:PATH|none  sound sink (default auto: alsa, else $PAD_AUDIO_PLAY, else none)\n"
        "  --audio-fmt PATH   the rig's fmt file, gets '44100 2' (default $PAD_AUDIO_FMT)\n"
        "  --volume 0-100     software mix gain (overrides conf volume=, default %d)\n"
        "  --anim-frame N     show frame N of every animation instead of animating (headless tests);\n"
        "                     with --snapshot: the highlighted card's frame (wraps)\n"
        "  --audio-dump FILE  raw s16le 44100 Hz stereo of everything mixed\n"
        "exit status: 0 = a choice was written, 2 = no choice\n", DEF_VOLUME);
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
    o->audio = "auto";
    o->timeout = -1;
    o->def = -1;
    o->invert = -1;
    o->volume = -1;
    o->anim_frame = -1;
    o->highlight = -1;
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
        ARG("--snapshot", snapshot)
        ARG("--font", font)
        ARG("--preamble", preamble)
        ARG("--media", media)
        ARG("--audio", audio)
        ARG("--audio-fmt", audio_fmt)
        ARG("--audio-dump", audio_dump)
#undef ARG
        if (!strcmp(a, "--timeout")) { if (!v) goto missing; o->timeout = atoi(v); i++; continue; }
        if (!strcmp(a, "--default")) { if (!v) goto missing; o->def = atoi(v); i++; continue; }
        if (!strcmp(a, "--volume")) { if (!v) goto missing; o->volume = atoi(v); i++; continue; }
        if (!strcmp(a, "--anim-frame")) { if (!v) goto missing; o->anim_frame = atoi(v); i++; continue; }
        if (!strcmp(a, "--highlight")) { if (!v) goto missing; o->highlight = atoi(v); i++; continue; }
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
    if (strcmp(o->audio, "auto") && strcmp(o->audio, "alsa") && strcmp(o->audio, "none") &&
        strncmp(o->audio, "fifo:", 5)) {
        fprintf(stderr, "codeselect: --audio must be auto, alsa, fifo:PATH or none\n");
        return -1;
    }
    if (o->snapshot && o->headless) {
        fprintf(stderr, "codeselect: --snapshot and --headless are exclusive\n");
        return -1;
    }
    if (o->highlight >= 0 && !o->snapshot) {
        fprintf(stderr, "codeselect: --highlight is only used with --snapshot\n");
        return -1;
    }
    if (o->volume > 100) o->volume = 100;
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

/* ------------------------------------------------------------- the layout */

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

struct layout {
    float s;
    int n, vis, carousel;     /* images; visible full cards; n > MAX_VISIBLE */
    int margin, gap, top, ch, cw, pad, inner;
    int art_h;                /* the art panel's height; 0 = no art anywhere (v1 picture) */
};

static void layout_compute(struct layout *L, const struct gfx *g, const struct conf *c)
{
    float s = (float)g->h / 768.0f;
    memset(L, 0, sizeof *L);
    L->s = s;
    L->n = c->n;
    L->carousel = c->n > MAX_VISIBLE;
    L->vis = L->carousel ? 3 : c->n;
    L->margin = (int)(60 * s);
    L->gap = (int)(36 * s);
    L->top = (int)(150 * s);
    L->ch = (int)(420 * s);
    L->cw = (g->w - 2 * L->margin - (L->vis - 1) * L->gap) / L->vis;
    L->pad = (int)(28 * s);
    L->inner = L->cw - 2 * L->pad;
    L->art_h = conf_has_art(c) ? (int)(0.40f * L->ch) : 0;
}

/* slot 0..vis-1 = the visible full cards; -1 and vis = the carousel's peeking
 * neighbours */
static int card_x(const struct layout *L, int slot)
{
    return L->margin + slot * (L->cw + L->gap);
}

/* which image sits in a slot */
static int slot_image(const struct layout *L, int hl, int slot)
{
    if (!L->carousel) return slot;
    return ((hl + slot - 1) % L->n + L->n) % L->n;
}

static void panel_rect(const struct layout *L, int slot, int *px, int *py, int *pw, int *ph)
{
    *px = card_x(L, slot) + L->pad;
    *py = L->top + L->pad;
    *pw = L->inner;
    *ph = L->art_h;
}

/* --------------------------------------------------------------- media */

struct clip_cache {
    char name[CONF_STR];
    struct audio_clip *clip;
};

struct media {
    struct art_image *art[CONF_MAX_IMAGES];
    struct art_anim *anim[CONF_MAX_IMAGES];
    struct audio_clip *music[CONF_MAX_IMAGES];
    struct audio_clip *move, *confirm;
    struct clip_cache cache[CONF_MAX_IMAGES + 2];
    int ncache;
    int n_art, n_anim, n_music, pending, logged;
    char dir[CONF_STR];
};

static void media_path(const struct media *m, const char *name, char *out, int outlen)
{
    if (name[0] == '/') snprintf(out, (size_t)outlen, "%s", name);
    else snprintf(out, (size_t)outlen, "%s/%s", m->dir, name);
}

static struct audio_clip *media_clip(struct media *m, const char *name)
{
    char path[CONF_STR * 2 + 2], err[300];
    struct audio_clip *c;
    int i;
    if (!name || !*name) return NULL;
    for (i = 0; i < m->ncache; i++)
        if (!strcmp(m->cache[i].name, name)) return m->cache[i].clip;
    media_path(m, name, path, sizeof path);
    c = audio_load_wav(path, err, sizeof err);
    if (!c) sel_log("audio: %s", err);
    else sel_log("audio: %s: %d frames (%.2f s)", name, c->frames, c->frames / (double)AUDIO_RATE);
    if (m->ncache < (int)(sizeof m->cache / sizeof m->cache[0])) {
        snprintf(m->cache[m->ncache].name, CONF_STR, "%s", name);
        m->cache[m->ncache].clip = c;
        m->ncache++;
    }
    return c;
}

/* the stills and the sounds; animations are opened here and decoded later */
static void media_load(struct media *m, const struct conf *c, const struct layout *L, int with_audio)
{
    int i;
    char path[CONF_STR * 2 + 2], err[300];
    for (i = 0; i < c->n; i++) {
        const struct conf_image *im = &c->img[i];
        if (im->art[0]) {
            media_path(m, im->art, path, sizeof path);
            m->art[i] = art_load_png(path, L->inner, L->art_h, err, sizeof err);
            if (m->art[i]) { m->n_art++; sel_log("art: image %d %s -> %dx%d", i, im->art, m->art[i]->w, m->art[i]->h); }
            else sel_log("art: cannot load %s (%s)", im->art, err);
        }
        if (im->anim[0]) {
            media_path(m, im->anim, path, sizeof path);
            m->anim[i] = art_anim_open(path, L->inner, L->art_h, ANIM_MAX_FRAMES, err, sizeof err);
            if (m->anim[i]) { m->n_anim++; m->pending++; }
            else sel_log("anim: cannot open %s (%s)", im->anim, err);
        }
        if (im->music[0] && with_audio) {
            m->music[i] = media_clip(m, im->music);
            if (m->music[i]) m->n_music++;
        }
    }
    if (with_audio) {
        m->move = media_clip(m, c->sound_move);
        m->confirm = media_clip(m, c->sound_confirm);
    }
}

/* decode one frame of the first animation still pending; returns the image
 * index it advanced or -1 */
static int media_step(struct media *m, int n)
{
    int i;
    for (i = 0; i < n; i++) {
        struct art_anim *a = m->anim[i];
        if (!a || a->done) continue;
        art_anim_step(a);
        if (a->done) {
            m->pending--;
            if (a->err[0]) sel_log("anim: image %d stopped after %d frame(s): %s", i, a->n, a->err);
            else sel_log("anim: image %d %d frames %dx%d", i, a->n, a->w, a->h);
        }
        return i;
    }
    return -1;
}

static void media_log(struct media *m)
{
    int i, frames = 0;
    if (m->logged) return;
    for (i = 0; i < CONF_MAX_IMAGES; i++)
        if (m->anim[i]) frames += m->anim[i]->n;
    sel_log("media: %d art, %d anim (%d frames), %d music, move=%s confirm=%s",
            m->n_art, m->n_anim, frames, m->n_music, m->move ? "y" : "n", m->confirm ? "y" : "n");
    m->logged = 1;
}

static void media_free(struct media *m)
{
    int i;
    for (i = 0; i < CONF_MAX_IMAGES; i++) {
        art_image_free(m->art[i]);
        art_anim_free(m->anim[i]);
    }
    for (i = 0; i < m->ncache; i++) audio_clip_free(m->cache[i].clip);
}

/* the picture image i shows right now: its animation's frame when it is
 * highlighted (or pinned), else its still, else the animation's frame 0 */
static const struct art_image *card_picture(const struct media *m, int i, int on, int frame, int pinned)
{
    const struct art_anim *a = m->anim[i];
    if (a && a->n > 0 && (on || pinned || !m->art[i])) {
        int f = (on || pinned) ? frame : 0;
        if (f < 0) f = 0;
        return &a->fr[f % a->n];
    }
    return m->art[i];
}

/* ----------------------------------------------------------------- draw */

static void draw_panel(struct gfx *g, const struct layout *L, const struct media *m,
                       int i, int slot, int on, int frame, int pinned)
{
    int px, py, pw, ph;
    const struct art_image *pic;
    if (!L->art_h) return;
    panel_rect(L, slot, &px, &py, &pw, &ph);
    gfx_rect(g, px, py, pw, ph, on ? C_CARD_HL : C_CARD);
    pic = card_picture(m, i, on, frame, pinned);
    if (pic) gfx_blit(g, px + (pw - pic->w) / 2, py + (ph - pic->h) / 2, pic->rgba, pic->w, pic->h);
}

static void draw_card(struct gfx *g, struct gfx_font *f, const struct layout *L,
                      const struct conf *c, const struct media *m,
                      int i, int slot, int on, int frame, int pinned)
{
    const struct conf_image *im = &c->img[i];
    float s = L->s;
    int x = card_x(L, slot), top = L->top, cw = L->cw, ch = L->ch, inner = L->inner;
    float tpx, spx;
    int base, tl, sub_y, nl, k, max_lines, line_h;
    char tlines[2][CONF_STR], lines[4][CONF_STR], buf[64];

    gfx_round_frame(g, x, top, cw, ch, (int)(22 * s), (int)((on ? 8 : 3) * s),
                    on ? C_FRAME_HL : C_FRAME, on ? C_CARD_HL : C_CARD);
    snprintf(buf, sizeof buf, "IMAGE %d", i + 1);

    if (!L->art_h) {
        /* the v1 picture, byte for byte */
        gfx_text_center(g, f, 22 * s, x + cw / 2, top + (int)(50 * s), buf, on ? C_LABEL_HL : C_LABEL);
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
        return;
    }

    /* the art layout: the panel on top, the text packed below it */
    draw_panel(g, L, m, i, slot, on, frame, pinned);
    {
        int label_y = top + L->pad + L->art_h + (int)(30 * s);
        gfx_text_center(g, f, 22 * s, x + cw / 2, label_y, buf, on ? C_LABEL_HL : C_LABEL);
        tpx = gfx_fit_px(f, im->title, inner, 48 * s, 26 * s);
        if (gfx_text_width(f, tpx, im->title) <= inner) {
            tl = 1;
            snprintf(tlines[0], CONF_STR, "%s", im->title);
            base = label_y + (int)(58 * s);
        } else {
            tl = gfx_wrap(f, tpx, im->title, inner, &tlines[0][0], CONF_STR, 2);
            for (k = 0; k < tl; k++) tpx = gfx_fit_px(f, tlines[k], inner, tpx, 20 * s);
            base = label_y + (int)(50 * s);
        }
        for (k = 0; k < tl; k++)
            gfx_text_center(g, f, tpx, x + cw / 2, base + (int)(k * tpx * 1.15f), tlines[k],
                            on ? C_TEXT_HL : C_TEXT);
        sub_y = base + (int)((tl - 1) * tpx * 1.15f) + (int)(44 * s);
        spx = gfx_fit_px(f, im->subtitle, inner * 2, 26 * s, 20 * s);
        line_h = (int)(32 * s);
        max_lines = (top + ch - (int)(12 * s) - sub_y) / line_h + 1;
        if (max_lines < 1) max_lines = 1;
        if (max_lines > 4) max_lines = 4;
        nl = gfx_wrap(f, spx, im->subtitle, inner, &lines[0][0], CONF_STR, max_lines);
        for (k = 0; k < nl; k++)
            gfx_text_center(g, f, spx, x + cw / 2, sub_y + k * line_h, lines[k],
                            on ? C_SUB_HL : C_SUB);
    }
}

static void draw_menu(struct gfx *g, struct gfx_font *f, const struct layout *L,
                      const struct conf *c, const struct media *m,
                      int hl, int remain, int frame, int pinned)
{
    float s = L->s;
    int W = g->w, slot;
    char buf[300], widest[300];

    gfx_fill(g, C_BG);
    gfx_text_center(g, f, 60 * s, W / 2, (int)(96 * s), "SELECT GAME CODE", C_TITLE);

    if (L->carousel) {
        /* the neighbours-but-one peek in from the edges: frames only */
        gfx_round_frame(g, card_x(L, -1), L->top, L->cw, L->ch, (int)(22 * s), (int)(3 * s), C_FRAME, C_CARD);
        gfx_round_frame(g, card_x(L, L->vis), L->top, L->cw, L->ch, (int)(22 * s), (int)(3 * s), C_FRAME, C_CARD);
    }
    for (slot = 0; slot < L->vis; slot++) {
        int i = slot_image(L, hl, slot);
        draw_card(g, f, L, c, m, i, slot, i == hl, frame, pinned);
    }
    if (L->carousel) {
        snprintf(buf, sizeof buf, "<   %d / %d   >", hl + 1, L->n);
        gfx_text_center(g, f, 26 * s, W / 2, (int)(602 * s), buf, C_FOOT);
    }

    /* Both bottom lines are fitted to the glass: a 199-character title (the
     * conf's limit) must shrink, never run off the edge. The countdown line is
     * sized from its LONGEST form, the 'press ...' one, so the size does not
     * wobble as the digits drop from 10 to 9. */
    {
        static const char foot[] = "LEFT / RIGHT FLIPPER: choose      START or ACTION: boot";
        const int wmax = W - (int)(80 * s);
        gfx_text_center(g, f, gfx_fit_px(f, foot, wmax, 30 * s, 20 * s), W / 2,
                        (int)(648 * s), foot, C_FOOT);
        snprintf(widest, sizeof widest, "press START or ACTION to boot %s", c->img[hl].title);
        if (remain >= 0)
            snprintf(buf, sizeof buf, "booting %s in %d s", c->img[hl].title, remain);
        else
            snprintf(buf, sizeof buf, "%s", widest);
        gfx_text_center(g, f, gfx_fit_px(f, widest, wmax, 38 * s, 24 * s), W / 2,
                        (int)(718 * s), buf, C_COUNT);
    }
}

/* the LOADING frame: the chosen card's picture (when it has one) above the
 * line; this frame stays on the LCD until the game's first frame */
static void draw_loading(struct gfx *g, struct gfx_font *f, const char *title,
                         const struct art_image *pic)
{
    float s = (float)g->h / 768.0f;
    char buf[300];
    int y = (int)(400 * s);
    gfx_fill(g, C_BG);
    if (pic) {
        gfx_blit(g, (g->w - pic->w) / 2, (int)(200 * s), pic->rgba, pic->w, pic->h);
        y = (int)(200 * s) + pic->h + (int)(90 * s);
    }
    snprintf(buf, sizeof buf, "LOADING %s...", title);
    gfx_text_center(g, f, gfx_fit_px(f, buf, g->w - (int)(80 * s), 64 * s, 30 * s),
                    g->w / 2, y, buf, C_TEXT_HL);
}

/* the slot image i is drawn in, or -1 when it is not on screen */
static int image_slot(const struct layout *L, int hl, int i)
{
    int slot;
    for (slot = 0; slot < L->vis; slot++)
        if (slot_image(L, hl, slot) == i) return slot;
    return -1;
}

/* -------------------------------------------------------------- snapshot */

static const char *media_dir(const struct opts *o, const struct conf *c)
{
    return o->media ? o->media : *c->media ? c->media : DEF_MEDIA;
}

/* --snapshot: ONE menu frame, the picture the machine shows the moment the
 * menu appears - the countdown at its full value - with the highlighted
 * card's animation at frame --anim-frame (0 when unset; past the end it
 * wraps); every other card shows its still, or frame 0 when it has none,
 * exactly as it does live. No input backend, no audio (the WAVs are not
 * even opened), nothing written but the PPM. Every animation is decoded in
 * full first so the frame asked for exists. Returns the exit status:
 * 0 = written, 2 = could not. */
static int snapshot_frame(const struct opts *o, const struct conf *c, struct gfx *g,
                          struct gfx_font *font, const struct layout *L, int hl,
                          const char *how, int timeout, int invert, const char *fontpath)
{
    struct media media;
    int n = c->n, frame = o->anim_frame > 0 ? o->anim_frame : 0, frames = 0;

    memset(&media, 0, sizeof media);
    snprintf(media.dir, sizeof media.dir, "%s", media_dir(o, c));
    media_load(&media, c, L, 0);
    while (media_step(&media, n) >= 0)
        ;
    media_log(&media);
    if (media.anim[hl]) frames = media.anim[hl]->n;
    if (!frames) {
        frame = 0;
    } else if (frame >= frames) {
        sel_log("snapshot: frame %d wraps to %d (image %d has %d frames)", frame, frame % frames, hl, frames);
        frame %= frames;
    }
    draw_menu(g, font, L, c, &media, hl, timeout > 0 ? timeout : -1, frame, 0);
    if (gfx_write_ppm(g, o->snapshot, invert) < 0) {
        sel_say("error: cannot write %s: %s", o->snapshot, strerror(errno));
        media_free(&media);
        return 2;
    }
    sel_say("snapshot: %s %dx%d, highlight %d (%s) from %s, frame %d of %d, timeout %d s, invert %d, font %s, media %s",
            o->snapshot, g->w, g->h, hl, c->img[hl].title, how, frame, frames, timeout, invert,
            fontpath, media.dir);
    media_free(&media);
    return 0;
}

/* ------------------------------------------------------------------ main */

/* present whatever is dirty: one packed sub-rect upload, then a swap */
static void present(struct gfx *g, struct egl_stern *egl, int headless, int invert)
{
    int x, y, w, h;
    const unsigned char *packed = gfx_pack(g, invert, &x, &y, &w, &h);
    gfx_clean(g);
    if (headless) sel_sleep_ms(16);
    else egl_stern_frame(egl, packed, x, y, w, h);      /* swap EVERY frame */
}

int main(int argc, char **argv)
{
    struct opts o;
    struct conf c;
    struct gfx g;
    struct gfx_font *font;
    struct egl_stern egl;
    struct input *in = NULL;
    struct input_cfg icfg;
    struct layout L;
    struct media media;
    struct audio *au = NULL;
    char err[300], fontpath[300], tables[400], padsw[400];
    int headless, snapshot, invert, timeout, n, hl, chosen = -1, w, h, volume, pinned, frame = 0;
    int music_voice = -1;
    const struct audio_clip *music_clip = NULL;
    const char *how, *fmt_path;
    long long start, deadline, last_key, next_tick = 0;   /* sel_now_ms() values: long long, see log.h */
    int remain_shown = -2, dirty;
    int rc = 2;

    if (parse_args(&o, argc, argv) < 0) return 2;
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGHUP, on_signal);
    signal(SIGPIPE, SIG_IGN);                    /* a FIFO reader may go away mid-write */
    sel_log_open(o.log);
    sel_log("codeselect " VERSION " starting (conf %s, input %s%s)", o.conf, o.input,
            o.snapshot ? ", snapshot" : o.headless ? ", headless" : "");

    if (conf_load(&c, o.conf, err, sizeof err) < 0) {
        sel_say("error: %s", err);
        return 2;
    }
    n = c.n;
    timeout = o.timeout >= 0 ? o.timeout : c.timeout >= 0 ? c.timeout : DEF_TIMEOUT;
    volume = o.volume >= 0 ? o.volume : c.volume >= 0 ? c.volume : DEF_VOLUME;
    snapshot = o.snapshot != NULL;
    if (snapshot) {
        /* the preview never reads the last-choice file: the card asked for,
         * else the conf's default, is what it shows */
        if (o.highlight >= 0) {
            if (o.highlight >= n) {
                sel_say("error: --highlight %d out of range (%d image%s)", o.highlight, n, n == 1 ? "" : "s");
                return 2;
            }
            hl = o.highlight;
            how = "--highlight";
        }
        else if (o.def >= 0 && o.def < n) { hl = o.def; how = "--default"; }
        else if (c.def >= 0 && c.def < n) { hl = c.def; how = "conf default"; }
        else { hl = 0; how = "first"; }
    } else {
        hl = conf_read_last(o.last);
        if (hl >= 0 && hl < n) how = "last choice";
        else if (o.def >= 0 && o.def < n) { hl = o.def; how = "--default"; }
        else if (c.def >= 0 && c.def < n) { hl = c.def; how = "conf default"; }
        else { hl = 0; how = "first"; }
    }
    headless = o.headless != NULL;
    pinned = o.anim_frame >= 0;
    if (pinned) frame = o.anim_frame;
    /* the snapshot is what the PLAYER sees: boot_display's -invert compensates
     * for an LCD mounted upside down, so it is applied only when asked for */
    invert = o.invert >= 0 ? o.invert : snapshot ? 0 : detect_invert();

    font = load_font(&o, &c, fontpath, sizeof fontpath);
    if (!font) {
        sel_say("error: no usable font (tried --font, conf font=, %s, %s)", DEF_FONT, CARD_FONT);
        return 2;
    }

    if (headless || snapshot) {
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
    layout_compute(&L, &g, &c);
    if (snapshot) {
        rc = snapshot_frame(&o, &c, &g, font, &L, hl, how, timeout, invert, fontpath);
        gfx_free(&g);
        gfx_font_free(font);
        sel_log("exit %d", rc);
        sel_log_close();
        return rc;
    }

    /* sound first (the FIFO handshake takes a moment), then the pictures */
    fmt_path = o.audio_fmt ? o.audio_fmt : getenv("PAD_AUDIO_FMT");
    au = audio_open(o.audio, fmt_path, volume, o.audio_dump);
    if (c.mixer_volume >= 0) {
        if (!strcmp(audio_sink_name(au), "alsa")) audio_alsa_mixer(c.mixer_volume);
        else sel_log("audio: mixer_volume=%d ignored (sink %s)", c.mixer_volume, audio_sink_name(au));
    }
    memset(&media, 0, sizeof media);
    snprintf(media.dir, sizeof media.dir, "%s", media_dir(&o, &c));
    media_load(&media, &c, &L, audio_active(au));
    /* the highlighted card's animation is complete before the first frame;
     * the others decode one frame per loop iteration */
    if (media.anim[hl]) {
        long long t0 = sel_now_ms();
        while (!media.anim[hl]->done) media_step(&media, n);
        sel_log("anim: image %d decoded before the first frame (%lld ms)", hl, sel_now_ms() - t0);
    }
    if (!media.pending) media_log(&media);

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

    sel_say("menu: %d image%s, highlight %d (%s) from %s, timeout %d s, input %s, invert %d, %dx%d, font %s, audio %s, media %s",
            n, n == 1 ? "" : "s", hl, c.img[hl].title, how, timeout, o.input, invert, w, h, fontpath,
            audio_sink_name(au), media.dir);
    if (L.carousel) sel_log("layout: carousel of %d (3 visible, %d px cards)", n, L.cw);

    start = sel_now_ms();
    last_key = start;
    deadline = timeout > 0 ? start + (long long)timeout * 1000LL : 0;
    draw_menu(&g, font, &L, &c, &media, hl, deadline ? timeout : -1, frame, pinned);
    remain_shown = deadline ? timeout : -1;
    dirty = 0;
    if (!headless) egl_stern_texture(&egl, w, h, gfx_pixels(&g, invert));
    gfx_clean(&g);
    music_clip = media.music[hl];
    if (music_clip) music_voice = audio_play(au, music_clip, 1);
    if (media.anim[hl] && media.anim[hl]->n > 0 && !pinned) next_tick = start + media.anim[hl]->delay_ms[0];

    while (!g_stop) {
        long long now = sel_now_ms();
        int ev, remain, old_hl = hl, stepped;

        while ((ev = input_poll(in, now)) != EV_NONE) {
            sel_say("key: %s", input_event_name(ev));
            switch (ev) {
            case EV_LEFT: case EV_MINUS:
                hl = (hl + n - 1) % n;
                dirty = 1;
                audio_play(au, media.move, 0);
                break;
            case EV_RIGHT: case EV_PLUS:
                hl = (hl + 1) % n;
                dirty = 1;
                audio_play(au, media.move, 0);
                break;
            case EV_START: case EV_ACTION: case EV_SELECT:
                chosen = hl;                        /* ACTION = the lockdown-bar button */
                break;
            default:
                break;                          /* BACK: ignored */
            }
            last_key = now;
            if (chosen >= 0) break;
        }
        if (chosen >= 0) break;
        if (hl != old_hl) {
            /* a new card: its animation restarts and its music takes over (hard switch) */
            frame = pinned ? o.anim_frame : 0;
            next_tick = (media.anim[hl] && media.anim[hl]->n > 0 && !pinned) ? now + media.anim[hl]->delay_ms[0] : 0;
            if (media.music[hl] != music_clip) {
                if (music_voice >= 0) audio_stop(au, music_voice);
                music_clip = media.music[hl];
                music_voice = music_clip ? audio_play(au, music_clip, 1) : -1;
            }
        }
        if (deadline) {
            /* a key restarts the countdown so a reader is not cut off */
            if (last_key > start) { deadline = last_key + (long long)timeout * 1000LL; start = last_key; }
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

        /* the highlighted card's animation ticks on the GIF's own delays */
        if (next_tick && now >= next_tick) {
            struct art_anim *a = media.anim[hl];
            frame = (frame + 1) % a->n;
            next_tick = now + a->delay_ms[frame];
            if (!dirty) draw_panel(&g, &L, &media, hl, image_slot(&L, hl, hl), 1, frame, pinned);
        }
        /* one frame of a pending animation per iteration, never a stall */
        stepped = media_step(&media, n);
        if (stepped >= 0) {
            struct art_anim *a = media.anim[stepped];
            /* its first frame just appeared, or (pinned) the pinned frame may
             * have: repaint that panel */
            if ((a->n == 1 || (a->done && pinned)) && !dirty) {
                int slot = image_slot(&L, hl, stepped);
                if (slot >= 0) draw_panel(&g, &L, &media, stepped, slot, stepped == hl, frame, pinned);
                if (stepped == hl && !pinned && !next_tick && a->n > 0) next_tick = now + a->delay_ms[0];
            }
            if (!media.pending) media_log(&media);
        }
        audio_pump(au, now);

        if (dirty) {
            draw_menu(&g, font, &L, &c, &media, hl, remain, frame, pinned);
            dirty = 0;
        }
        present(&g, &egl, headless, invert);
    }

    if (chosen >= 0) {
        if (headless) {
            if (gfx_write_ppm(&g, o.headless, invert) < 0)
                sel_log("cannot write %s: %s", o.headless, strerror(errno));
            else
                sel_log("wrote %s (%dx%d)", o.headless, w, h);
        }
        draw_loading(&g, font, c.img[chosen].title, card_picture(&media, chosen, 1, frame, pinned));
        if (headless) {
            char lp[400];
            snprintf(lp, sizeof lp, "%s.loading.ppm", o.headless);
            gfx_write_ppm(&g, lp, invert);
        }
        present(&g, &egl, headless, invert);
        /* the confirm sound plays to completion under the LOADING frame, then
         * the sink is drained and closed - before the choice file, so the
         * game never finds the device busy */
        if (audio_active(au)) {
            long long t0 = sel_now_ms(), cap = t0 + CONFIRM_CAP_MS, done_at = 0;
            int cv = -1;
            if (music_voice >= 0) audio_stop(au, music_voice);
            if (media.confirm) cv = audio_play(au, media.confirm, 0);
            while (!g_stop) {
                long long now = sel_now_ms();
                audio_pump(au, now);
                if (!done_at && (cv < 0 || !audio_playing(au, cv))) done_at = now + audio_lead_ms(au);
                if (done_at && now >= done_at) break;
                if (now >= cap) { sel_log("confirm sound capped at %d ms", CONFIRM_CAP_MS); break; }
                present(&g, &egl, headless, invert);
            }
            sel_log("confirm: %lld ms under the LOADING frame", sel_now_ms() - t0);
        }
        audio_close(au);
        au = NULL;
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

    media_log(&media);
    audio_close(au);
    input_close(in);
    if (!headless) egl_stern_close(&egl);
    media_free(&media);
    gfx_free(&g);
    gfx_font_free(font);
    sel_log("exit %d", rc);
    sel_log_close();
    return rc;
}
