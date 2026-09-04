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
 * while its card is highlighted), a music loop and a confirm sound of its
 * own; a move sound plays on every highlight change and a confirm sound - the
 * chosen card's when it has one, else the menu-wide one - plays TO COMPLETION
 * under the LOADING frame before the program exits. Every media failure is
 * non-fatal: the menu runs without the piece that failed.
 *
 *   --headless FILE.ppm   no EGL: run the loop, write the last menu frame as
 *                         a binary P6 PPM (and the LOADING frame beside it as
 *                         FILE.loading.ppm); with --input none the countdown
 *                         expires and the highlighted image is chosen.
 *   --snapshot FILE.ppm   render ONE menu frame - what the machine shows the
 *                         moment the menu appears - as a P6 PPM and exit 0,
 *                         with no display, input, audio, choice or last file:
 *                         the Multi-boot tab's preview. --highlight N picks
 *                         the card, --anim-frame N its animation frame, and
 *                         --frames K writes a WHOLE RUN of K frames from the
 *                         one load (FILE.ppm is then a "%d" pattern) - the
 *                         preview used to pay a process start, and a re-load
 *                         of every PNG, GIF and font, for each frame it showed.
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
#include "nvm.h"
#include "codec.h"
#include "log.h"

#define VERSION "2.6"

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
/* the title + subtitle block under a card's picture, at 768 px: what the
 * picture must leave room for (selectmedia.py's TEXT_BLOCK - the two must
 * agree, it is how the tools know the panel's size) */
#define TEXT_BLOCK   118
/* the most frames an animation is read for: 5 s at 30 fps (selectmedia.py's
 * GIF_MAX_FRAMES - the two must agree); frames are decoded on demand, so
 * this bounds a file walk and a --frames run, not memory */
#define ANIM_MAX_FRAMES 150
#define CONFIRM_CAP_MS 8000

/* The two footer lines, and the two long forms of the countdown line. Which
 * pair is drawn depends on whether this title HAS a lockdown-bar Action
 * button: see draw_menu(). They are named constants on their own lines so
 * anything outside this program that has to quote the footer (the GUI's
 * Multi-boot preview) can lift the text from here instead of retyping it. */
#define FOOT_START   "LEFT / RIGHT FLIPPER: choose      START: boot"
#define FOOT_ACTION  "LEFT / RIGHT FLIPPER: choose      START or ACTION: boot"
#define PRESS_START  "press START to boot "
#define PRESS_ACTION "press START or ACTION to boot "

struct opts {
    const char *conf, *out, *input, *nodebus, *spi, *padsw, *tables, *last, *log,
               *headless, *font, *preamble, *media, *audio, *audio_fmt, *audio_dump,
               *snapshot, *codec;
    int timeout;      /* -1 = from conf */
    int def;          /* -1 = from conf */
    int invert;       /* -1 = auto */
    int volume;       /* -1 = from conf */
    int anim_frame;   /* -1 = animate; else every animation shows this frame */
    int highlight;    /* --snapshot: the highlighted card; -1 = the conf default */
    int frames;       /* --snapshot: how many frames to write from one load (1) */
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
        "  --frames K         --snapshot only: write K frames (1-%d) from one load, starting at\n"
        "                     --anim-frame and stepping by one (wrapping); K > 1 makes the\n"
        "                     --snapshot value a printf pattern holding exactly one %%d, the\n"
        "                     frame number (default 1: one frame, the value used as it stands)\n"
        "  --invert / --no-invert  rotate 180 degrees (default: auto from " BOOTDISP_CMD ")\n"
        "  --preamble min|full  node-bus bring-up to replay before scanning (default min)\n"
        "  --font PATH        TrueType font (default conf font=, " DEF_FONT ", " CARD_FONT ")\n"
        "  --media DIR        where the conf's media names live (default conf media=, " DEF_MEDIA ")\n"
        "  --audio auto|alsa|fifo:PATH|none  sound sink (default auto: alsa, else $PAD_AUDIO_PLAY, else none)\n"
        "  --audio-fmt PATH   the rig's fmt file, gets '44100 2' (default $PAD_AUDIO_FMT)\n"
        "  --codec auto|off   auto = power the machine's codecs' line-out over i2c the way the game\n"
        "                     does, put back at exit (only when both SGTL5000s answer); off = leave them\n"
        "  --volume 0-100     software mix gain (overrides conf volume=, default %d)\n"
        "  --anim-frame N     hold every animation at frame N instead of playing them (headless tests);\n"
        "                     with --snapshot: the highlighted card's frame (wraps), and the\n"
        "                     first of the --frames K run\n"
        "  --audio-dump FILE  raw s16le 44100 Hz stereo of everything mixed\n"
        "exit status: 0 = a choice was written, 2 = no choice\n", ANIM_MAX_FRAMES, DEF_VOLUME);
}

/* With --frames K > 1 the --snapshot value is a printf PATTERN, so the caller
 * keeps its own file naming (the Multi-boot tab names its cache
 * frame_<fingerprint>_<highlight>_<n>.ppm). Exactly one conversion is allowed
 * and it must be a bare %d, the frame number: none would pile every frame into
 * one file, two would hand snprintf an argument it was never given, and a %s or
 * a width is a caller that believes this is a richer format than it is. "%%" is
 * a literal percent and does not count. 0 = usable, -1 = why, in err. */
static int check_frames_pattern(const char *p, char *err, int errlen)
{
    const char *s;
    int n = 0;
    for (s = p; *s; s++) {
        if (*s != '%') continue;
        if (s[1] == '%') { s++; continue; }
        if (!s[1]) {
            snprintf(err, (size_t)errlen, "--snapshot \"%s\" ends in a lone '%%'", p);
            return -1;
        }
        if (s[1] != 'd') {
            snprintf(err, (size_t)errlen,
                     "--snapshot \"%s\" holds '%%%c'; with --frames > 1 it is a printf pattern "
                     "taking exactly one bare '%%d' (the frame number) and '%%%%' for a percent",
                     p, s[1]);
            return -1;
        }
        n++;
        s++;
    }
    if (n != 1) {
        snprintf(err, (size_t)errlen,
                 "--snapshot \"%s\" holds %d '%%d'; with --frames > 1 it is a printf pattern "
                 "taking exactly one, the frame number", p, n);
        return -1;
    }
    return 0;
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
    o->codec = "auto";
    o->timeout = -1;
    o->def = -1;
    o->invert = -1;
    o->volume = -1;
    o->anim_frame = -1;
    o->highlight = -1;
    o->frames = 1;
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
        ARG("--codec", codec)
#undef ARG
        if (!strcmp(a, "--timeout")) { if (!v) goto missing; o->timeout = atoi(v); i++; continue; }
        if (!strcmp(a, "--default")) { if (!v) goto missing; o->def = atoi(v); i++; continue; }
        if (!strcmp(a, "--volume")) { if (!v) goto missing; o->volume = atoi(v); i++; continue; }
        if (!strcmp(a, "--anim-frame")) { if (!v) goto missing; o->anim_frame = atoi(v); i++; continue; }
        if (!strcmp(a, "--highlight")) { if (!v) goto missing; o->highlight = atoi(v); i++; continue; }
        if (!strcmp(a, "--frames")) { if (!v) goto missing; o->frames = atoi(v); i++; continue; }
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
    if (strcmp(o->codec, "auto") && strcmp(o->codec, "off")) {
        fprintf(stderr, "codeselect: --codec must be auto or off\n");
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
    if (o->frames < 1) {
        fprintf(stderr, "codeselect: --frames must be at least 1\n");
        return -1;
    }
    /* An animation is cut at ANIM_MAX_FRAMES when it is decoded, so a larger K
     * could only ask for frames that cannot exist - and every one of them is a
     * full redraw of the canvas. Refuse it here rather than spin. */
    if (o->frames > ANIM_MAX_FRAMES) {
        fprintf(stderr, "codeselect: --frames %d is more than the %d frames an animation can have\n",
                o->frames, ANIM_MAX_FRAMES);
        return -1;
    }
    if (o->frames > 1) {
        char perr[600];
        if (!o->snapshot) {
            fprintf(stderr, "codeselect: --frames > 1 is only used with --snapshot\n");
            return -1;
        }
        /* refused BEFORE a byte is written: a caller that got the pattern
         * wrong must not find half a run of files on disk */
        if (check_frames_pattern(o->snapshot, perr, sizeof perr) < 0) {
            fprintf(stderr, "codeselect: %s\n", perr);
            return -1;
        }
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

/* The menu's colours are the THEME the conf picked (theme.h; the built-in
 * themes are themes.json, and 'midnight' there is the look this program had
 * before it could be chosen).  Every draw function reads them off the layout
 * it is handed, by role. */
#define TH(L, role) ((L)->th.rgb[TH_##role])

struct layout {
    float s;
    int n, vis, carousel;     /* images; visible full cards; n > MAX_VISIBLE */
    int margin, gap, top, ch, cw, pad, inner;
    int art_h;                /* the art panel's height; 0 = no art anywhere (v1 picture) */
    struct theme th;          /* the colours, resolved from the conf (theme_resolve) */
    int th_known;             /* the conf's theme name was a theme (else the default is up) */
    int th_set;               /* how many roles the conf's color_ keys replaced */
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
    L->top = (int)(140 * s);
    L->ch = (int)(460 * s);
    L->cw = (g->w - 2 * L->margin - (L->vis - 1) * L->gap) / L->vis;
    L->pad = (int)(24 * s);
    L->inner = L->cw - 2 * L->pad;
    /* THE PICTURE IS THE CARD (David, 2026-09-03: "the most important
     * information is the image / video display, so let's maximize the
     * space used for that"): a 16:9 panel as wide as the card allows,
     * capped so the title + subtitle block below it still fits; the text
     * is then centred in what is left (draw_card).  selectmedia.py
     * mirrors this arithmetic (panel_geometry) to render clips at exactly
     * the size shown. */
    L->art_h = 0;
    if (conf_has_art(c)) {
        int by_width = L->inner * 9 / 16;
        int by_height = L->ch - 2 * L->pad - (int)(TEXT_BLOCK * s);
        L->art_h = by_width < by_height ? by_width : by_height;
    }
    L->th_set = theme_resolve(&L->th, c->theme, c->color, c->color_set, &L->th_known);
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
    /* an image's OWN confirm sound (conf field 7); NULL = use ->confirm */
    struct audio_clip *own_confirm[CONF_MAX_IMAGES];
    struct audio_clip *move, *confirm;
    /* every WAV is decoded once and shared by name: at most one music and one
     * confirm per image, plus the two menu-wide sounds */
    struct clip_cache cache[CONF_MAX_IMAGES * 2 + 2];
    int ncache;
    int n_art, n_anim, n_music, n_own_confirm, logged;
    /* EVERY animation plays, all the time (David, 2026-09-03: "all boot
     * selections should play video at the same time all the time (not
     * just when hovered)"): each keeps its own frame and the moment its
     * next one is due (sel_now_ms() values; 0 = not ticking: pinned, or
     * a still) */
    int frame[CONF_MAX_IMAGES];
    double due[CONF_MAX_IMAGES];
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

/* the stills, the sounds, and the animations (frame 0 each; the rest decode
 * on demand as the menu ticks) */
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
            if (m->anim[i]) {
                const struct art_anim *a = m->anim[i];
                int k, ms = 0;
                for (k = 0; k < a->n; k++) ms += a->delay_ms[k];
                m->n_anim++;
                sel_log("anim: image %d %d frames %dx%d, a %.1f s loop, decoded a frame at a time",
                        i, a->n, a->w, a->h, ms / 1000.0);
            }
            else sel_log("anim: cannot open %s (%s)", im->anim, err);
        }
        if (im->music[0] && with_audio) {
            m->music[i] = media_clip(m, im->music);
            if (m->music[i]) m->n_music++;
        }
        if (im->confirm[0] && with_audio) {
            m->own_confirm[i] = media_clip(m, im->confirm);
            if (m->own_confirm[i]) m->n_own_confirm++;
            else sel_log("confirm: image %d cannot use %s: the menu-wide sound is used instead", i, im->confirm);
        }
    }
    if (with_audio) {
        m->move = media_clip(m, c->sound_move);
        m->confirm = media_clip(m, c->sound_confirm);
    }
}

/* how long frame `frame` of an animation stays up: the loop's period for a
 * constant-rate clip, else that frame's own delay */
static double anim_step_ms(const struct art_anim *a, int frame)
{
    return a->period_ms > 0 ? (double)a->period_ms : (double)a->delay_ms[frame];
}

/* an animation that turned out shorter than its file said it was: said once */
static void media_check(const struct media *m, int i)
{
    struct art_anim *a = m->anim[i];
    if (a && a->err[0] && !a->err_said) {
        sel_log("anim: image %d stopped after %d frame(s): %s", i, a->n, a->err);
        a->err_said = 1;
    }
}

/* what the on-demand decoding cost, per animation that was played */
static void media_stats(const struct media *m)
{
    int i;
    for (i = 0; i < CONF_MAX_IMAGES; i++) {
        const struct art_anim *a = m->anim[i];
        if (a && a->decodes)
            sel_log("anim: image %d: %d frame decodes, %.2f ms each",
                    i, a->decodes, a->decode_us / 1000.0 / a->decodes);
    }
}

static void media_log(struct media *m)
{
    int i, frames = 0;
    if (m->logged) return;
    for (i = 0; i < CONF_MAX_IMAGES; i++)
        if (m->anim[i]) frames += m->anim[i]->n;
    sel_log("media: %d art, %d anim (%d frames), %d music, %d card confirm, move=%s confirm=%s",
            m->n_art, m->n_anim, frames, m->n_music, m->n_own_confirm,
            m->move ? "y" : "n", m->confirm ? "y" : "n");
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

/* the picture image i shows right now: its animation's current frame
 * (every card's plays, highlighted or not), else its still.  The frame is
 * DECODED HERE if it is not the one in hand (art.h) - the media set is
 * const to every draw, the decoder inside an animation is not. */
static const struct art_image *card_picture(const struct media *m, int i)
{
    struct art_anim *a = m->anim[i];
    if (a && a->n > 0) {
        int f = m->frame[i];
        return art_anim_frame(a, f < 0 ? 0 : f % a->n);
    }
    return m->art[i];
}

/* set every animation to frame f (wrapped): the pinned modes, and the
 * snapshot */
static void media_pin(struct media *m, int n, int f)
{
    int i;
    for (i = 0; i < n; i++) {
        struct art_anim *a = m->anim[i];
        m->frame[i] = (a && a->n > 0) ? ((f < 0 ? 0 : f) % a->n) : 0;
        m->due[i] = 0;
    }
}

/* start every animation at frame 0, its first tick a period from now */
static void media_start(struct media *m, int n, double now)
{
    int i;
    for (i = 0; i < n; i++) {
        struct art_anim *a = m->anim[i];
        m->frame[i] = 0;
        m->due[i] = (a && a->n > 1) ? now + anim_step_ms(a, 0) : 0;
    }
}

/* Advance every animation that is due.  Returns a bitmask of the images
 * that moved (bit i), so the caller can repaint just those panels.  ON THE
 * CLIP'S OWN TIMELINE, not the loop's: the swap paces this loop to the
 * LCD's vsync (16.7 ms), so 'now + delay' rounded EVERY frame up to the
 * next vsync and a 30 fps clip played at 24.  Due times accumulate instead
 * - late ticks catch up - and only a stall of more than a frame is
 * forgiven (the timeline restarts from now rather than bursting). */
static unsigned media_tick(struct media *m, int n, double now)
{
    unsigned moved = 0;
    int i;
    for (i = 0; i < n; i++) {
        struct art_anim *a = m->anim[i];
        double step;
        if (!a || a->n < 2 || m->due[i] <= 0 || now < m->due[i]) continue;
        m->frame[i] = (m->frame[i] + 1) % a->n;
        step = anim_step_ms(a, m->frame[i]);
        m->due[i] += step;
        if (now - m->due[i] > step) m->due[i] = now + step;
        moved |= 1u << i;
    }
    return moved;
}

/* ----------------------------------------------------------------- draw */

static void draw_panel(struct gfx *g, const struct layout *L, const struct media *m,
                       int i, int slot, int on)
{
    int px, py, pw, ph;
    const struct art_image *pic;
    if (!L->art_h) return;
    panel_rect(L, slot, &px, &py, &pw, &ph);
    gfx_rect(g, px, py, pw, ph, on ? TH(L, CARD_HL) : TH(L, CARD));
    pic = card_picture(m, i);
    if (pic) gfx_blit(g, px + (pw - pic->w) / 2, py + (ph - pic->h) / 2, pic->rgba, pic->w, pic->h);
}

static void draw_card(struct gfx *g, struct gfx_font *f, const struct layout *L,
                      const struct conf *c, const struct media *m,
                      int i, int slot, int on)
{
    const struct conf_image *im = &c->img[i];
    float s = L->s;
    int x = card_x(L, slot), top = L->top, cw = L->cw, ch = L->ch, inner = L->inner;
    float tpx, spx;
    int base, tl, sub_y, nl, k, line_h;
    /* every line below is drawn through gfx_ellipsize() into cut[]: wrapping
     * splits on spaces, so ONE long word (or a title with none) is still wider
     * than the card, and gfx_fit_px() bottoms out before it shrinks that far */
    char tlines[2][CONF_STR], lines[4][CONF_STR], cut[CONF_STR + 8];

    /* NO 'IMAGE N' CAPTION on the card (David, 2026-09-03: "we don't need the
     * text 'Image 1', 'Image 2', etc. on each of the images. that is just
     * taking up extra space").  It named the SLOT, which the '< n / N >'
     * counter under the row and the titles already say; the row that carried
     * it is given back to the title and subtitle below. */
    gfx_round_frame(g, x, top, cw, ch, (int)(22 * s), (int)((on ? 8 : 3) * s),
                    on ? TH(L, FRAME_HL) : TH(L, FRAME), on ? TH(L, CARD_HL) : TH(L, CARD));

    if (!L->art_h) {
        /* the v1 picture, byte for byte (bar the dropped caption) */
        tpx = gfx_fit_px(f, im->title, inner, 62 * s, 34 * s);
        if (gfx_text_width(f, tpx, im->title) <= inner) {
            tl = 1;
            snprintf(tlines[0], CONF_STR, "%s", im->title);
        } else {
            tl = gfx_wrap(f, tpx, im->title, inner, &tlines[0][0], CONF_STR, 2);
            for (k = 0; k < tl; k++) tpx = gfx_fit_px(f, tlines[k], inner, tpx, 22 * s);
        }
        base = top + (int)((tl == 2 ? 0.36f : 0.42f) * ch);
        for (k = 0; k < tl; k++) {
            gfx_ellipsize(f, tpx, tlines[k], inner, cut, sizeof cut);
            gfx_text_center(g, f, tpx, x + cw / 2, base + (int)(k * tpx * 1.15f), cut,
                            on ? TH(L, TITLE_HL) : TH(L, TITLE));
        }
        sub_y = base + (int)((tl - 1) * tpx * 1.15f) + (int)(62 * s);
        spx = gfx_fit_px(f, im->subtitle, inner * 2, 30 * s, 22 * s);
        nl = gfx_wrap(f, spx, im->subtitle, inner, &lines[0][0], CONF_STR, 4);
        for (k = 0; k < nl; k++) {
            gfx_ellipsize(f, spx, lines[k], inner, cut, sizeof cut);
            gfx_text_center(g, f, spx, x + cw / 2, sub_y + (int)(40 * k * s), cut,
                            on ? TH(L, SUBTITLE_HL) : TH(L, SUBTITLE));
        }
        return;
    }

    /* the art layout: the panel on top, the text packed below it */
    draw_panel(g, L, m, i, slot, on);
    {
        /* THE TEXT IS CENTRED IN WHAT THE PICTURE LEAVES (David: "the rest
         * needs to be better vertically centered to look more
         * professional"): the title (one or two lines) and the subtitle (up
         * to two) are measured first, then the block is placed in the middle
         * of the zone between the panel and the card's bottom edge. */
        int zone_top = top + L->pad + L->art_h;
        int zone_h = (top + ch - L->pad) - zone_top;
        int title_h, sub_h, block_h, y0, gap = (int)(14 * s);
        tpx = gfx_fit_px(f, im->title, inner, 48 * s, 26 * s);
        if (gfx_text_width(f, tpx, im->title) <= inner) {
            tl = 1;
            snprintf(tlines[0], CONF_STR, "%s", im->title);
        } else {
            tl = gfx_wrap(f, tpx, im->title, inner, &tlines[0][0], CONF_STR, 2);
            for (k = 0; k < tl; k++) tpx = gfx_fit_px(f, tlines[k], inner, tpx, 20 * s);
        }
        spx = gfx_fit_px(f, im->subtitle, inner * 2, 26 * s, 20 * s);
        line_h = (int)(32 * s);
        nl = *im->subtitle ? gfx_wrap(f, spx, im->subtitle, inner, &lines[0][0], CONF_STR, 2) : 0;
        title_h = (int)(tl * tpx * 1.15f);
        sub_h = nl ? gap + nl * line_h : 0;
        block_h = title_h + sub_h;
        y0 = zone_top + (zone_h - block_h) / 2;
        if (y0 < zone_top) y0 = zone_top;
        /* baselines: a line's ascent is ~0.93 of its size in this face */
        base = y0 + (int)(tpx * 0.93f);
        for (k = 0; k < tl; k++) {
            gfx_ellipsize(f, tpx, tlines[k], inner, cut, sizeof cut);
            gfx_text_center(g, f, tpx, x + cw / 2, base + (int)(k * tpx * 1.15f), cut,
                            on ? TH(L, TITLE_HL) : TH(L, TITLE));
        }
        sub_y = y0 + title_h + gap + (int)(spx * 0.93f);
        for (k = 0; k < nl; k++) {
            gfx_ellipsize(f, spx, lines[k], inner, cut, sizeof cut);
            gfx_text_center(g, f, spx, x + cw / 2, sub_y + k * line_h, cut,
                            on ? TH(L, SUBTITLE_HL) : TH(L, SUBTITLE));
        }
    }
}

/* action = this title has a lockdown-bar ACTION button the menu can read; 0
 * means the footer must not promise one */
static void draw_menu(struct gfx *g, struct gfx_font *f, const struct layout *L,
                      const struct conf *c, const struct media *m,
                      int hl, int remain, int action)
{
    float s = L->s;
    int W = g->w, slot;
    char buf[300], widest[300], cut[300];

    gfx_fill(g, TH(L, BACKGROUND));
    gfx_text_center(g, f, 60 * s, W / 2, (int)(96 * s), "SELECT GAME CODE", TH(L, HEADING));

    if (L->carousel) {
        /* the neighbours-but-one peek in from the edges: frames only */
        gfx_round_frame(g, card_x(L, -1), L->top, L->cw, L->ch, (int)(22 * s), (int)(3 * s), TH(L, FRAME), TH(L, CARD));
        gfx_round_frame(g, card_x(L, L->vis), L->top, L->cw, L->ch, (int)(22 * s), (int)(3 * s), TH(L, FRAME), TH(L, CARD));
    }
    for (slot = 0; slot < L->vis; slot++) {
        int i = slot_image(L, hl, slot);
        draw_card(g, f, L, c, m, i, slot, i == hl);
    }
    if (L->carousel) {
        snprintf(buf, sizeof buf, "<   %d / %d   >", hl + 1, L->n);
        gfx_text_center(g, f, 26 * s, W / 2, (int)(626 * s), buf, TH(L, FOOTER));
    }

    /* Both bottom lines are SHRUNK and then CUT to the glass. Shrinking alone
     * was not enough: gfx_fit_px() floors at min_px and hands back that floor
     * whether or not the text fits, and a 199-character title (conf.h's limit)
     * is still about twice the panel wide at 24 px - so the line used to run
     * off both edges, which is exactly what gfx_text_center() does with
     * anything too wide. gfx_ellipsize() ends it "..." instead. The countdown
     * line is SIZED from its longest form, the 'press ...' one, so the size
     * does not wobble as the digits drop from 10 to 9 - but each form is cut
     * on its own, since the shorter one may still fit whole.
     *
     * The footer names the buttons that EXIST. With no Action button resolved
     * - beatles has no lockdown row at all, and a menu still waiting for its
     * switch table has not resolved one either - promising "START or ACTION"
     * named a button nothing on this machine is wired to. */
    {
        const char *foot = action ? FOOT_ACTION : FOOT_START;
        const int wmax = W - (int)(80 * s);
        float fpx = gfx_fit_px(f, foot, wmax, 30 * s, 20 * s), cpx;
        gfx_ellipsize(f, fpx, foot, wmax, cut, sizeof cut);
        gfx_text_center(g, f, fpx, W / 2, (int)(662 * s), cut, TH(L, FOOTER));
        snprintf(widest, sizeof widest, "%s%s", action ? PRESS_ACTION : PRESS_START,
                 c->img[hl].title);
        if (remain >= 0)
            snprintf(buf, sizeof buf, "booting %s in %d s", c->img[hl].title, remain);
        else
            snprintf(buf, sizeof buf, "%s", widest);
        cpx = gfx_fit_px(f, widest, wmax, 38 * s, 24 * s);
        gfx_ellipsize(f, cpx, buf, wmax, cut, sizeof cut);
        gfx_text_center(g, f, cpx, W / 2, (int)(718 * s), cut, TH(L, COUNTDOWN));
    }
}

/* the LOADING frame: the chosen card's picture (when it has one) above the
 * line; this frame stays on the LCD until the game's first frame */
static void draw_loading(struct gfx *g, struct gfx_font *f, const struct theme *th,
                         const char *title, const struct art_image *pic)
{
    float s = (float)g->h / 768.0f;
    char buf[300], cut[300];
    int y = (int)(400 * s), wmax = g->w - (int)(80 * s);
    float px;
    gfx_fill(g, th->rgb[TH_BACKGROUND]);
    if (pic) {
        gfx_blit(g, (g->w - pic->w) / 2, (int)(200 * s), pic->rgba, pic->w, pic->h);
        y = (int)(200 * s) + pic->h + (int)(90 * s);
    }
    snprintf(buf, sizeof buf, "LOADING %s...", title);
    px = gfx_fit_px(f, buf, wmax, 64 * s, 30 * s);
    gfx_ellipsize(f, px, buf, wmax, cut, sizeof cut);
    gfx_text_center(g, f, px, g->w / 2, y, cut, th->rgb[TH_TITLE_HL]);
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

/* --snapshot: the menu frame the machine shows the moment the menu appears -
 * the countdown at its full value - with EVERY card's animation at frame
 * --anim-frame (0 when unset; past the end each wraps to its own length),
 * cards without one showing their still, exactly as it does live. No
 * input backend, no audio (the WAVs are not even opened), nothing written but
 * the PPM(s). An animation is decoded up to the frame asked for and no
 * further (art.h: on demand).
 *
 * --frames K writes a WHOLE RUN of K frames - --anim-frame, then the next, and
 * the next, wrapping - out of that ONE load. The preview used to play an
 * animation by running this program once per frame, so a 16-frame run cost 16
 * qemu-user starts and 16 re-decodes of every PNG, GIF and font just to move
 * one panel; the draw is the only part that differs between them, and it is
 * the cheap part. K past the animation's length would only rewrite files this
 * same run has already written, and a card with no animation has nothing to
 * step at all, so both are trimmed here and said in the log - the caller reads
 * the real count off the 'frame F of N' it already parses.
 *
 * Returns the exit status: 0 = written, 2 = could not. */
static int snapshot_frame(const struct opts *o, const struct conf *c, struct gfx *g,
                          struct gfx_font *font, const struct layout *L, int hl,
                          const char *how, int timeout, int invert, const char *fontpath,
                          int action)
{
    struct media media;
    char path[600];
    int n = c->n, first = o->anim_frame > 0 ? o->anim_frame : 0, frames = 0;
    /* K == 1 is the old path to the byte: the --snapshot value is a file NAME,
     * never a pattern, so a name that happens to hold a '%' still works */
    int pattern = o->frames > 1, want = o->frames, k;

    memset(&media, 0, sizeof media);
    snprintf(media.dir, sizeof media.dir, "%s", media_dir(o, c));
    media_load(&media, c, L, 0);
    media_log(&media);
    /* the run's length and the 'frame F of N' on the line are the
     * HIGHLIGHTED card's; every animation is pinned at the frame asked for
     * (first + k), each wrapping to its own length - a card that is not
     * highlighted plays too, so it is drawn at that frame too */
    if (media.anim[hl]) frames = media.anim[hl]->n;
    if (!frames) {
        if (want > 1) {
            sel_log("snapshot: image %d has no animation: 1 frame, not %d", hl, want);
            want = 1;
        }
    } else {
        if (first >= frames)
            sel_log("snapshot: frame %d wraps to %d (image %d has %d frames)", first, first % frames, hl, frames);
        if (want > frames) {
            sel_log("snapshot: %d frames asked for, image %d has %d: %d written", want, hl, frames, frames);
            want = frames;
        }
    }
    for (k = 0; k < want; k++) {
        int pin = first + k;
        int frame = frames ? pin % frames : 0;
        int len = pattern ? snprintf(path, sizeof path, o->snapshot, frame)
                          : snprintf(path, sizeof path, "%s", o->snapshot);
        if (len < 0 || len >= (int)sizeof path) {
            sel_say("error: snapshot frame %d does not fit %d bytes of path", frame, (int)sizeof path - 1);
            media_free(&media);
            return 2;
        }
        char where[CONF_MAX_IMAGES * 24 + 8];
        int wn = 0, i;
        media_pin(&media, n, pin);
        draw_menu(g, font, L, c, &media, hl, timeout > 0 ? timeout : -1, action);
        for (i = 0; i < n; i++) media_check(&media, i);
        if (gfx_write_ppm(g, path, invert) < 0) {
            sel_say("error: cannot write %s: %s", path, strerror(errno));
            media_free(&media);
            return 2;
        }
        /* WHERE EVERY ANIMATED CARD'S PICTURE IS in the PPM - `i:x,y,w,h`
         * per visible card with an animation, `;`-separated, `none` when
         * there is none - the frame blitted into its panel.  The Multi-boot
         * tab's Play lays each GIF's own frames over this one picture
         * instead of asking for a PPM per frame (150 of them at 3 MB each
         * was the alternative). */
        where[0] = 0;
        for (i = 0; i < n; i++) {
            const struct art_image *pic;
            int slot = image_slot(L, hl, i), px, py, pw, ph, rx, ry;
            if (!media.anim[i] || !L->art_h || slot < 0) continue;
            pic = card_picture(&media, i);
            if (!pic) continue;
            panel_rect(L, slot, &px, &py, &pw, &ph);
            rx = px + (pw - pic->w) / 2;
            ry = py + (ph - pic->h) / 2;
            if (invert) { rx = g->w - rx - pic->w; ry = g->h - ry - pic->h; }
            wn += snprintf(where + wn, sizeof where - wn, "%s%d:%d,%d,%d,%d",
                           wn ? ";" : "", i, rx, ry, pic->w, pic->h);
            if (wn >= (int)sizeof where - 1) break;
        }
        sel_say("snapshot: %s %dx%d, highlight %d (%s) from %s, frame %d of %d, timeout %d s, invert %d, font %s, media %s, footer \"%s\", pictures %s",
                path, g->w, g->h, hl, c->img[hl].title, how, frame, frames, timeout, invert,
                fontpath, media.dir, action ? FOOT_ACTION : FOOT_START, wn ? where : "none");
    }
    media_stats(&media);
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
    int headless, snapshot, invert, timeout, n, hl, chosen = -1, w, h, volume, pinned;
    int machine_v = -1;       /* volume=machine: the machine's own 0-63, else -1 */
    int action;                       /* this title has a lockdown-bar ACTION button */
    int music_voice = -1;
    const struct audio_clip *music_clip = NULL;
    const char *how, *fmt_path;
    long long start, deadline, last_key;   /* sel_now_ms() values: long long, see log.h */
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
    /* the switch list, resolved here because --snapshot needs it too: it runs
     * no input backend, but its footer has to name the same buttons the live
     * menu will */
    if (o.tables) snprintf(tables, sizeof tables, "%s", o.tables);
    else snprintf(tables, sizeof tables, "/dump/tables/%s/switch_list.txt",
                  getenv("PAD_GAME") ? getenv("PAD_GAME") : "");
    /* hw reads node 1 bit 2 off the wire, so there the button is always
     * possible; padsw needs the list to name it */
    action = !strcmp(o.input, "hw") ? 1 : input_padsw_has_action(tables);
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
    {
        char bad[64] = "";
        if (c.bad_colors)
            snprintf(bad, sizeof bad, ", %d colour value%s ignored", c.bad_colors, c.bad_colors == 1 ? "" : "s");
        if (!L.th_known) sel_log("theme: '%s' is not a theme, using %s", c.theme, THEME_DEFAULT);
        sel_log("theme: %s (%d of %d colours set by the conf%s)", L.th.name, L.th_set, TH_N, bad);
    }
    if (snapshot) {
        rc = snapshot_frame(&o, &c, &g, font, &L, hl, how, timeout, invert, fontpath, action);
        gfx_free(&g);
        gfx_font_free(font);
        sel_log("exit %d", rc);
        sel_log_close();
        return rc;
    }

    /* sound first (the FIFO handshake takes a moment), then the pictures */
    fmt_path = o.audio_fmt ? o.audio_fmt : getenv("PAD_AUDIO_FMT");
    /* THE MACHINE'S OWN VOLUME (volume=machine): the MASTER VOLUME SETTING
     * the owner set on the coin door, read off the card's /data/nv mirror
     * (nvm.h); the title's factory level when the machine has no store yet;
     * the plain default when the conf names neither.  --volume still wins.
     * On the hardware the number goes to the codec's mixer exactly as the
     * game hands it over and the mix runs at 100; a sink with no mixer (the
     * emulator's fifo, a dump) gets the same curve as a software gain.
     * David, 2026-09-03: "it should follow the set volume of the actual
     * machine". */
    if (c.volume_machine && o.volume >= 0) {
        sel_log("audio: --volume %d overrides volume=machine", o.volume);
    } else if (c.volume_machine) {
        char why[400] = "", from[600] = "";
        int live = -1;
        if (c.mv_store[0] && c.mv_key_set
            && nvm_read_value(c.mv_store, c.mv_key, &live, from, sizeof from, why, sizeof why) == 0) {
            machine_v = live > 63 ? 63 : live < 0 ? 0 : live;
            sel_log("audio: volume follows the machine: %d/63 (%s)", machine_v, from);
        } else if (c.mv_default >= 0) {
            machine_v = c.mv_default;
            sel_log("audio: volume follows the machine: no setting read (%s); the title's factory %d/63",
                    why[0] ? why : "no store named", machine_v);
        } else {
            sel_log("audio: volume follows the machine: no setting read (%s) and no factory level; %d%%",
                    why[0] ? why : "no store named", volume);
        }
        if (machine_v >= 0) volume = audio_machine_gain(machine_v);
    }
    /* THE CODECS (codec.h): what the two SGTL5000s hold before the menu
     * touches anything goes in the log - it is the whole diagnosis when a
     * machine stays silent - and the ALSA sink powers their line-out after
     * its own open (audio_alsa.c), the way the game does over i2c.  Not on
     * the emulator: there is no /dev/i2c-1 there, and the first call says so. */
    codec_configure(o.codec);
    if (strcmp(o.audio, "none")) codec_snapshot("before the menu");
    au = audio_open(o.audio, fmt_path, volume, o.audio_dump);
    if (machine_v >= 0 && !strcmp(audio_sink_name(au), "alsa")) {
        audio_alsa_mixer(machine_v);     /* the machine's own curve, on its own mixer */
        audio_set_volume(au, 100);
    } else if (machine_v < 0 && c.mixer_volume >= 0) {
        if (!strcmp(audio_sink_name(au), "alsa")) audio_alsa_mixer(c.mixer_volume);
        else sel_log("audio: mixer_volume=%d ignored (sink %s)", c.mixer_volume, audio_sink_name(au));
    }
    memset(&media, 0, sizeof media);
    snprintf(media.dir, sizeof media.dir, "%s", media_dir(&o, &c));
    media_load(&media, &c, &L, audio_active(au));
    media_log(&media);

    memset(&icfg, 0, sizeof icfg);
    icfg.nodebus = o.nodebus;
    icfg.spi = o.spi;
    icfg.preamble_full = !strcmp(o.preamble, "full");
    if (o.padsw) snprintf(padsw, sizeof padsw, "%s", o.padsw);
    else snprintf(padsw, sizeof padsw, "%s", getenv("PAD_SW_SHM") ? getenv("PAD_SW_SHM") : "/dump/padsw");
    icfg.padsw = padsw;
    icfg.tables = tables;
    if (!strcmp(o.input, "hw")) in = input_hw_open(&icfg);
    else if (!strcmp(o.input, "padsw")) in = input_padsw_open(&icfg);
    /* the backend is the authority once it exists: padsw may resolve its table
     * later than the probe above could, and --input none has no buttons */
    action = input_has(in, EV_ACTION);

    sel_say("menu: %d image%s, highlight %d (%s) from %s, timeout %d s, input %s, invert %d, %dx%d, font %s, audio %s, media %s, footer \"%s\"",
            n, n == 1 ? "" : "s", hl, c.img[hl].title, how, timeout, o.input, invert, w, h, fontpath,
            audio_sink_name(au), media.dir, action ? FOOT_ACTION : FOOT_START);
    if (L.carousel) sel_log("layout: carousel of %d (3 visible, %d px cards)", n, L.cw);

    start = sel_now_ms();
    last_key = start;
    deadline = timeout > 0 ? start + (long long)timeout * 1000LL : 0;
    /* every card's animation plays from the first frame on - the pinned
     * modes (--anim-frame) hold them all at that frame instead */
    if (pinned) media_pin(&media, n, o.anim_frame);
    else media_start(&media, n, (double)start);
    draw_menu(&g, font, &L, &c, &media, hl, deadline ? timeout : -1, action);
    remain_shown = deadline ? timeout : -1;
    dirty = 0;
    if (!headless) egl_stern_texture(&egl, w, h, gfx_pixels(&g, invert));
    gfx_clean(&g);
    music_clip = media.music[hl];
    if (music_clip) music_voice = audio_play(au, music_clip, 1);

    while (!g_stop) {
        long long now = sel_now_ms();
        int ev, remain, old_hl = hl;

        /* hold the codecs' line-out on: the kernel routes only the headphone
         * jack, so its DAPM pulls LINE_OUT (the amps' feed) back down once the
         * stream is running - the game reprograms the codec continuously for
         * the same reason (codec.h). A no-op where there is no codec bus. */
        codec_keep(now);

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
            /* a new card: its music takes over (hard switch); the
             * animations all keep running - they were never paused */
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
        /* padsw resolves its switch list a moment into the run, so the Action
         * button can appear (or, on a list rewritten under us, go away) after
         * the first frame: repaint the footer when it does */
        if (input_has(in, EV_ACTION) != action) {
            action = !action;
            sel_log("footer: ACTION button %s", action ? "resolved" : "no longer resolved");
            dirty = 1;
        }

        /* EVERY animation ticks on its clip's own timeline (media_tick);
         * each frame is decoded by the draw (art.h: on demand), and only
         * the panels that moved are repainted - or none, when the whole
         * menu is about to be */
        {
            unsigned moved = pinned ? 0 : media_tick(&media, n, (double)now);
            int i;
            for (i = 0; moved && i < n; i++) {
                if (!(moved & (1u << i))) continue;
                if (!dirty) {
                    int slot = image_slot(&L, hl, i);
                    if (slot >= 0) draw_panel(&g, &L, &media, i, slot, i == hl);
                }
                media_check(&media, i);
            }
        }
        audio_pump(au, now);

        if (dirty) {
            draw_menu(&g, font, &L, &c, &media, hl, remain, action);
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
        draw_loading(&g, font, &L.th, c.img[chosen].title,
                     card_picture(&media, chosen));
        if (headless) {
            char lp[400];
            snprintf(lp, sizeof lp, "%s.loading.ppm", o.headless);
            gfx_write_ppm(&g, lp, invert);
        }
        present(&g, &egl, headless, invert);
        /* the confirm sound plays to completion under the LOADING frame, then
         * the sink is drained and closed - before the choice file, so the
         * game never finds the device busy. The chosen image's OWN sound when
         * it loaded one, else the menu-wide sound_confirm. */
        if (audio_active(au)) {
            long long t0 = sel_now_ms(), cap = t0 + CONFIRM_CAP_MS, done_at = 0;
            const struct audio_clip *cc = media.own_confirm[chosen];
            char cwhich[CONF_STR + 40];
            int cv = -1;
            if (cc) snprintf(cwhich, sizeof cwhich, "image %d sound %s", chosen, c.img[chosen].confirm);
            else if ((cc = media.confirm) != NULL) snprintf(cwhich, sizeof cwhich, "menu sound %s", c.sound_confirm);
            else snprintf(cwhich, sizeof cwhich, "no sound");
            if (music_voice >= 0) audio_stop(au, music_voice);
            if (cc) cv = audio_play(au, cc, 0);
            while (!g_stop) {
                long long now = sel_now_ms();
                codec_keep(now);        /* keep line-out up while the confirm sound plays */
                audio_pump(au, now);
                if (!done_at && (cv < 0 || !audio_playing(au, cv))) done_at = now + audio_lead_ms(au);
                if (done_at && now >= done_at) break;
                if (now >= cap) { sel_log("confirm sound capped at %d ms", CONFIRM_CAP_MS); break; }
                present(&g, &egl, headless, invert);
            }
            sel_log("confirm: %s, %lld ms under the LOADING frame", cwhich, sel_now_ms() - t0);
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
    media_stats(&media);
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
