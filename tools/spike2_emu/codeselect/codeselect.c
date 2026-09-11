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
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include "conf.h"
#include "gfx.h"
#include "egl_stern.h"
#include "input.h"
#include "art.h"
#include "audio.h"
#include "nvm.h"
#include "codec.h"
#include "log.h"

#define VERSION "3.0"

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
    int highlight;    /* --snapshot: the highlighted image; -1 = the conf default */
    int frames;       /* --snapshot: how many frames to write from one load (1) */
    /* THE TWO GROUP KNOBS, FOR TESTS AND PROOF RUNS ONLY (item 106).  Neither
     * is ever written to a card: a jukebox that always picked the same member
     * would look exactly like one that was working. */
    int highlight_card; /* --highlight-card: a CARD index, for a keeping group's card */
    const char *loading; /* --loading-out: with --snapshot, ALSO write the
                          * LOADING frame - the one the machine draws once the
                          * card is confirmed, which for a random card is the
                          * one moment the player is told what they got. */
    int last_image;   /* --last-image: what the roll must treat as the last
                       * one booted.  A snapshot reads no last-choice file (it
                       * writes nothing and must not depend on the machine's
                       * memory), so a preview that wants the machine's OWN
                       * behaviour - never the build you just had - says so
                       * here. -1 = nothing was booted before. */
    int pick;         /* boot this image instead of rolling; -1 = roll */
    int seed;         /* make the roll reproducible; -1 = stir it for real */
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
        "  --log PATH         diagnostics: a fresh file each run (the previous run kept as PATH.1),\n"
        "                     at most 1 MiB per run; stderr always carries the same lines\n"
        "  --headless FILE.ppm  no EGL; write the final menu frame as a P6 PPM\n"
        "  --snapshot FILE.ppm  render ONE menu frame as a P6 PPM and exit: no display, input,\n"
        "                     audio, choice or last file (the preview)\n"
        "  --highlight N      --snapshot only: the highlighted card (default conf default=, else 0;\n"
        "                     the last-choice file is never read)\n"
        "  --highlight-card N highlight CARD N (menu order) rather than an image; the only way\n"
        "                     to name a keeping group's card\n"
        "  --pick N           boot image N instead of rolling a group card's member (tests)\n"
        "  --seed N           make a group card's roll reproducible (tests)\n"
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
    o->highlight_card = -1;
    o->pick = -1;
    o->last_image = -1;
    o->seed = -1;
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
        if (!strcmp(a, "--highlight-card")) { if (!v) goto missing; o->highlight_card = atoi(v); i++; continue; }
        if (!strcmp(a, "--loading-out")) { if (!v) goto missing; o->loading = v; i++; continue; }
        if (!strcmp(a, "--last-image")) { if (!v) goto missing; o->last_image = atoi(v); i++; continue; }
        if (!strcmp(a, "--pick")) { if (!v) goto missing; o->pick = atoi(v); i++; continue; }
        if (!strcmp(a, "--seed")) { if (!v) goto missing; o->seed = atoi(v); i++; continue; }
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
    L->n = c->ncards;
    L->carousel = c->ncards > MAX_VISIBLE;
    L->vis = L->carousel ? 3 : c->ncards;
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

/* EVERYTHING BELOW COUNTS CARDS, NOT IMAGES (item 106).  A group card draws
 * one picture, plays one clip and has one confirm sound however many images
 * it can boot, so every per-card array here, and media_tick's moved[] flags,
 * are sized off CONF_MAX_CARDS and live on the stack or in one struct;
 * raising that cap is free up to the point where that stops being true.  The
 * image cap is a different and much larger number that does not reach here:
 * only the boot decision and the two index files still speak in images. */
_Static_assert(CONF_MAX_CARDS >= 1 && CONF_MAX_CARDS <= 256,
               "CONF_MAX_CARDS sizes every per-card array in this file");

/* EVERY `image N` IN THIS FILE'S LOG IS A CARD INDEX from item 106 on.  The
 * wording is kept because the Multi-boot tab parses `anim: image N F frames`
 * and headless.sh greps `anim: cache on image N`; both of those already think
 * in rows, which are cards, so the number they read is the right one.  The
 * conf's own group lines are logged as `card K` and the boot decision as
 * `group: card K boots image N`, where `image` does mean an image. */
struct media {
    struct art_image *art[CONF_MAX_CARDS];
    struct art_anim *anim[CONF_MAX_CARDS];
    struct audio_clip *music[CONF_MAX_CARDS];
    /* an image's OWN confirm sound (conf field 7); NULL = use ->confirm */
    struct audio_clip *own_confirm[CONF_MAX_CARDS];
    struct audio_clip *move, *confirm;
    /* every WAV is decoded once and shared by name: at most one music and one
     * confirm per image, plus the two menu-wide sounds */
    struct clip_cache cache[CONF_MAX_CARDS * 2 + 2];
    int ncache;
    int n_art, n_anim, n_music, n_own_confirm, logged;
    /* EVERY animation plays, all the time (David, 2026-09-03: "all boot
     * selections should play video at the same time all the time (not
     * just when hovered)"): each keeps its own frame and the moment its
     * next one is due (sel_now_ms() values; 0 = not ticking: pinned, or
     * a still) */
    int frame[CONF_MAX_CARDS];
    double due[CONF_MAX_CARDS];
    /* ticks[i]: how many times clip i has advanced since media_start.
     * paints[i]: how many of those advances reached the repaint step.  TWO
     * counters, not one, because the past-32 bug moved the frame and then
     * dropped the repaint - a single "played" count would have read healthy
     * right through it.  With a correct tick the two are EQUAL; a clip whose
     * ticks climb while its paints stay at 0 is animating into a panel
     * nobody is drawing, which is the bug seen from the log. */
    int ticks[CONF_MAX_CARDS];
    int paints[CONF_MAX_CARDS];
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
    for (i = 0; i < c->ncards; i++) {
        const struct conf_image *im = conf_card_face(c, i);
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

/* what the decoding cost, per animation that was played: on demand (the
 * menu's own thread) or the cache thread's fill */
static void media_stats(const struct media *m)
{
    int i;
    for (i = 0; i < CONF_MAX_CARDS; i++) {
        const struct art_anim *a = m->anim[i];
        if (!a || !a->decodes) continue;
        if (a->caching)
            sel_log("anim: image %d: played %d drawn %d, %d of %d frames cached, %.2f ms each on the cache thread",
                    i, m->ticks[i], m->paints[i], art_anim_ready(a), a->n,
                    a->decodes ? a->decode_us / 1000.0 / a->decodes : 0.0);
        else
            sel_log("anim: image %d: played %d drawn %d, %d frame decodes, %.2f ms each",
                    i, m->ticks[i], m->paints[i], a->decodes, a->decode_us / 1000.0 / a->decodes);
    }
}

/* HOW LONG THE HIGHLIGHT MUST SIT STILL before the cache is re-aimed.  A
 * re-aim frees and allocates tens of megabytes, so doing one per keypress
 * would have a fast scroll thrashing the allocator and re-decoding clips it
 * is about to pass anyway.  Long enough to ride out a scroll, short enough
 * that a card you stop on is playing from RAM before you have read its
 * subtitle. */
#define CACHE_SETTLE_MS 200

/* PAD_ANIM_SETTLE_MS forces the settle, FOR THE TESTS.  The property worth
 * proving is that several moves inside ONE window produce ONE re-aim, and the
 * fastest a test can drive the switch block is about 320 ms a move - wider
 * than the shipped 200 ms, so at the real value every press legitimately gets
 * its own re-aim and the collapsing can never be seen.  The test widens the
 * window instead of the constant being chosen to suit it. */
static long long cache_settle_ms(void)
{
    const char *forced = getenv("PAD_ANIM_SETTLE_MS");
    if (forced && *forced) {
        long ms = strtol(forced, NULL, 10);
        if (ms >= 0) return (long long)ms;
    }
    return CACHE_SETTLE_MS;
}

/* The clips the cache budget should go to, NEAREST THE HIGHLIGHT FIRST:
 * hl, hl+1, hl-1, hl+2, hl-2 ... wrapping at both ends, which is the order
 * the carousel itself wraps in.  art_cache_set takes them in this order until
 * the budget is gone, so the cached set is a WINDOW around the card being
 * looked at and its size is whatever fits - never a number someone guessed,
 * and never images 0..k, which is what it used to be.  Writes n entries
 * (NULLs and stills included: the cache skips them). */
static int rank_by_distance(struct art_anim **out, struct art_anim *const *anim, int n, int hl)
{
    int d, k = 0;
    if (n <= 0) return 0;
    out[k++] = anim[hl];
    for (d = 1; d <= n / 2 && k < n; d++) {
        int r = (hl + d) % n, l = ((hl - d) % n + n) % n;
        out[k++] = anim[r];
        if (l != r && k < n) out[k++] = anim[l];
    }
    return k;
}

/* RAM for the frame cache: half of what the kernel calls available, capped
 * - the game's own working set is not running yet, and the cache is freed
 * before the game starts; 64 MB when /proc/meminfo cannot be read */
static size_t anim_cache_budget(void)
{
    FILE *f;
    char line[128];
    size_t avail_kb = 0, free_kb = 0, budget;
    /* PAD_ANIM_CACHE_MB forces the budget, FOR THE TESTS.  The interesting
     * behaviour of the cache is what it does when the budget runs out, and on
     * any machine a test can run on there is far too much memory for a
     * synthetic clip set to reach it - so without this the eviction path is
     * unreachable and the window around the highlight cannot be shown to
     * exist.  Never set on a card; the machine's own memory answers there. */
    const char *forced = getenv("PAD_ANIM_CACHE_MB");
    if (forced && *forced) {
        long mb = strtol(forced, NULL, 10);
        if (mb >= 0) return (size_t)mb * 1024 * 1024;
    }
    f = fopen("/proc/meminfo", "r");
    if (f) {
        while (fgets(line, sizeof line, f)) {
            unsigned long v;
            if (sscanf(line, "MemAvailable: %lu", &v) == 1) avail_kb = v;
            else if (sscanf(line, "MemFree: %lu", &v) == 1) free_kb = v;
        }
        fclose(f);
    }
    if (!avail_kb) avail_kb = free_kb;
    if (!avail_kb) return (size_t)64 * 1024 * 1024;
    budget = avail_kb * 1024 / 2;
    if (budget > (size_t)192 * 1024 * 1024) budget = (size_t)192 * 1024 * 1024;
    return budget;
}

static void media_log(struct media *m)
{
    int i, frames = 0;
    if (m->logged) return;
    for (i = 0; i < CONF_MAX_CARDS; i++)
        if (m->anim[i]) frames += m->anim[i]->n;
    sel_log("media: %d art, %d anim (%d frames), %d music, %d card confirm, move=%s confirm=%s",
            m->n_art, m->n_anim, frames, m->n_music, m->n_own_confirm,
            m->move ? "y" : "n", m->confirm ? "y" : "n");
    m->logged = 1;
}

static void media_free(struct media *m)
{
    int i;
    for (i = 0; i < CONF_MAX_CARDS; i++) {
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
        m->ticks[i] = 0;
        m->paints[i] = 0;
        m->due[i] = (a && a->n > 1) ? now + anim_step_ms(a, 0) : 0;
    }
}

/* Advance every animation that is due.  Sets moved[i] for each image whose
 * frame changed and returns how many did, so the caller can repaint just
 * those panels.  ON THE CLIP'S OWN TIMELINE, not the loop's: the swap paces
 * this loop to the LCD's vsync (16.7 ms), so 'now + delay' rounded EVERY
 * frame up to the next vsync and a 30 fps clip played at 24.  Due times
 * accumulate instead - late ticks catch up - and only a stall of more than
 * a frame is forgiven (the timeline restarts from now rather than
 * bursting).
 *
 * A FLAG ARRAY, not the `unsigned moved` bitmask this used to be: `1u << i`
 * is undefined from image 32 up, and it fails SILENTLY - image 32's clip
 * simply never repaints while every log line says the menu is healthy.  The
 * cap is 16 today so nothing could reach it, but item 106 raises
 * CONF_MAX_IMAGES well past 32 and must not inherit the trap. */
static int media_tick(struct media *m, int n, double now, unsigned char *moved)
{
    int i, nmoved = 0;
    for (i = 0; i < n; i++) {
        struct art_anim *a = m->anim[i];
        double step;
        moved[i] = 0;
        if (!a || a->n < 2 || m->due[i] <= 0 || now < m->due[i]) continue;
        m->frame[i] = (m->frame[i] + 1) % a->n;
        step = anim_step_ms(a, m->frame[i]);
        m->due[i] += step;
        if (now - m->due[i] > step) m->due[i] = now + step;
        m->ticks[i]++;
        moved[i] = 1;
        nmoved++;
    }
    return nmoved;
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
    const struct conf_image *im = conf_card_face(c, i);
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

/* ", card K/M" for a plain card, and what the group is for a group card.  One
 * clause, used by both the snapshot line and the live menu's opening line.
 *
 * NOTHING IS ADDED TO A CONF WITH NO GROUPS, and that is deliberate: there the
 * card index and the image index are the same number, so the clause would say
 * nothing while changing a line the Multi-boot tab and eleven tests already
 * match on.  A card that reached this menu before item 106 gets byte-identical
 * output from it after. */
static void card_note(const struct conf *c, int hl, int ncards, char *out, int outlen)
{
    int nm = conf_card_nmembers(c, hl);
    if (!c->ngroups)
        out[0] = 0;
    else if (conf_card_boots(c, hl) >= 0)
        snprintf(out, (size_t)outlen, ", card %d/%d", hl + 1, ncards);
    else
        snprintf(out, (size_t)outlen, ", card %d/%d (group %s, %d member%s)",
                 hl + 1, ncards, conf_card_face(c, hl)->title, nm, nm == 1 ? "" : "s");
}

/* WHICH MEMBER a group card boots (item 106).
 *
 * The member the last-choice file names is excluded, so a group of two or
 * more never repeats itself across two power-ups - the whole point of the
 * card is that it changes, and a fair coin would show the same set twice in a
 * row a quarter of the time.
 *
 * FOUR SOURCES ARE STIRRED because not one of them is good enough alone on
 * this machine: /dev/urandom is the real entropy but the card's 3.14 kernel
 * is asked best-effort and the read may not answer, CLOCK_MONOTONIC counts
 * only from power-up and a machine that boots cold reaches this menu at very
 * nearly the same nanosecond every time, time() is one value for a whole run,
 * and the pid barely moves in an init that starts the same processes in the
 * same order.  Taken at the CONFIRM moment rather than at start-up, so a
 * player who reads the menu for a while stirs it further.
 *
 * `seed` >= 0 (--seed, tests only) replaces the lot and makes the roll
 * reproducible.  `why` gets the clause the log prints. */
/* whether card `card` has image `img` among its members */
static int card_has_member(const struct conf *c, int card, int img)
{
    int k, n = conf_card_nmembers(c, card);
    for (k = 0; k < n; k++)
        if (conf_card_member(c, card, k) == img) return 1;
    return 0;
}

static int roll_member(const struct conf *c, int card, int last, int seed,
                       char *why, int whylen)
{
    int cand[CONF_MAX_IMAGES], nc = 0, k, n = conf_card_nmembers(c, card);
    const char *src = "urandom+clock";
    unsigned s = 0;

    /* EXCLUDED BY DEVICE, not merely by index.  A KEEPING group's members also
     * have cards of their own, so the same build can be reached two ways - and
     * a player who has just booted it from its own card would otherwise have
     * the group hand it straight back, which is the one thing this card
     * promises not to do. */
    {
        const char *lastdev = (last >= 0 && last < c->n) ? c->img[last].device : NULL;
        for (k = 0; k < n; k++) {
            int m = conf_card_member(c, card, k);
            if (m == last) continue;
            if (lastdev && *lastdev && !strcmp(c->img[m].device, lastdev)) continue;
            cand[nc++] = m;
        }
    }
    /* a one-member group, or a last choice that is the only member: the
     * exclusion has to give way, it never leaves the menu with nothing */
    if (nc == 0)
        for (k = 0; k < n; k++) cand[nc++] = conf_card_member(c, card, k);
    if (nc == 1) {
        snprintf(why, (size_t)whylen, "rolled from %s: 1 candidate",
                 conf_card_face(c, card)->title);
        return cand[0];
    }
    if (seed >= 0) {
        s = (unsigned)seed;
        src = "--seed";
    } else {
        /* open/read, not stdio: this is a character device, and a FILE* here
         * would put a 4 KB buffered read between the menu and four bytes it
         * actually needs. */
        struct timespec ts;
        unsigned char b[4];
        int fd = open("/dev/urandom", O_RDONLY);
        ssize_t got = fd >= 0 ? read(fd, b, sizeof b) : -1;
        if (fd >= 0) close(fd);
        if (got == (ssize_t)sizeof b)
            s = (unsigned)b[0] | ((unsigned)b[1] << 8) | ((unsigned)b[2] << 16) | ((unsigned)b[3] << 24);
        else {
            src = "clock";
            sel_log("group: /dev/urandom gave %ld byte(s) (%s): the clock seeds the roll",
                    (long)got, fd < 0 ? strerror(errno) : "short read");
        }
        if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0)
            s ^= (unsigned)ts.tv_nsec ^ ((unsigned)ts.tv_sec << 16);
        s ^= (unsigned)time(NULL);
        s ^= (unsigned)getpid() << 7;
    }
    snprintf(why, (size_t)whylen, "rolled from %s: %d candidate%s, %s",
             conf_card_face(c, card)->title, nc, nc == 1 ? "" : "s", src);
    return cand[s % (unsigned)nc];
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
                 conf_card_face(c, hl)->title);
        if (remain >= 0)
            snprintf(buf, sizeof buf, "booting %s in %d s", conf_card_face(c, hl)->title, remain);
        else
            snprintf(buf, sizeof buf, "%s", widest);
        cpx = gfx_fit_px(f, widest, wmax, 38 * s, 24 * s);
        gfx_ellipsize(f, cpx, buf, wmax, cut, sizeof cut);
        gfx_text_center(g, f, cpx, W / 2, (int)(718 * s), cut, TH(L, COUNTDOWN));
    }
}

/* WHAT THE LOADING FRAME SHOWS: the BUILD's own picture when the card knows
 * what that build looks like, else the card's.
 *
 * They are the same thing on an ordinary card.  On a RANDOM card they are not,
 * and the build's is the one worth showing: this frame is the one moment the
 * player is told which of them they got, so it should look like that one
 * (David, 2026-09-11: "on this loading screen, I want to see the random image
 * that was selected").  A member that keeps a card of its own has a picture
 * here; a member a consuming group swallowed has none, and the card's own
 * picture is then the only true answer. */
static const struct art_image *loading_picture(const struct conf *c,
                                               const struct media *m,
                                               int card, int boot)
{
    int own = conf_card_of_image(c, boot);
    if (own >= 0 && own != card && card_picture(m, own))
        return card_picture(m, own);
    return card_picture(m, card);
}

/* the LOADING frame: the chosen card's picture (when it has one) above the
 * line; this frame stays on the LCD until the game's first frame */
static void draw_loading(struct gfx *g, struct gfx_font *f, const struct theme *th,
                         const char *title, const char *subtitle,
                         const struct art_image *pic)
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
    /* AND THE SUBTITLE, which is where a jukebox keeps the difference.  Its
     * members are one title with different song sets, so the title alone says
     * "LOADING Godzilla Premium 1..." whichever one the roll landed on - and
     * this frame exists to tell the player which one they got. */
    if (subtitle && *subtitle) {
        float spx = gfx_fit_px(f, subtitle, wmax, 34 * s, 22 * s);
        gfx_ellipsize(f, spx, subtitle, wmax, cut, sizeof cut);
        gfx_text_center(g, f, spx, g->w / 2, y + (int)(px * 1.25f), cut,
                        th->rgb[TH_SUBTITLE_HL]);
    }
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
                          struct gfx_font *font, const struct layout *L, int hl, int hlimg,
                          const char *how, int timeout, int invert, const char *fontpath,
                          int action)
{
    struct media media;
    char path[600], cardinfo[CONF_STR + 64];
    int n = c->ncards, first = o->anim_frame > 0 ? o->anim_frame : 0, frames = 0;
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
        char where[CONF_MAX_CARDS * 24 + 8];
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
        /* WHICH CARD the highlighted image landed on.  `highlight` echoes the
         * IMAGE the caller asked for, because that is what --highlight,
         * default= and the choice file all speak; `card K/M` is where it
         * landed, which is a different number the moment a group card
         * swallows several images.  The tab's _SNAP_RE absorbs between the
         * two with .*?, and _SNAP_PICTURES_RE anchors on the tail: this sits
         * between them and touches neither. */
        card_note(c, hl, n, cardinfo, sizeof cardinfo);
        sel_say("snapshot: %s %dx%d, highlight %d (%s) from %s%s, frame %d of %d, timeout %d s, invert %d, font %s, media %s, footer \"%s\", pictures %s",
                path, g->w, g->h, hlimg, conf_card_face(c, hl)->title, how, cardinfo,
                frame, frames, timeout, invert,
                fontpath, media.dir, action ? FOOT_ACTION : FOOT_START, wn ? where : "none");
    }
    /* THE LOADING FRAME, when it is asked for: what the machine draws the
     * moment the card is confirmed.  A RANDOM card ROLLS for it, because that
     * frame is the one place the player is told which build they got, and a
     * preview that showed a fixed member would be showing a lie.  Nothing else
     * of the confirm happens - no choice file, no last file, no sound, no
     * boot - so this stays what --snapshot is: a picture, and no side effect. */
    if (o->loading && *o->loading) {
        int boot = conf_card_boots(c, hl);
        char why[CONF_STR + 64], rolled[CONF_STR + 80];
        rolled[0] = 0;
        if (conf_card_group(c, hl) >= 0) {
            boot = o->pick >= 0 ? o->pick
                                : roll_member(c, hl, o->last_image, o->seed,
                                              why, sizeof why);
            if (o->pick < 0) snprintf(rolled, sizeof rolled, " (%s)", why);
        }
        if (boot < 0) boot = 0;
        draw_loading(g, font, &L->th, c->img[boot].title, c->img[boot].subtitle,
                     loading_picture(c, &media, hl, boot));
        if (gfx_write_ppm(g, o->loading, invert) < 0)
            sel_log("cannot write %s: %s", o->loading, strerror(errno));
        else
            sel_say("loading: %s %dx%d, card %d boots image %d (%s)%s",
                    o->loading, g->w, g->h, hl + 1, boot, c->img[boot].title, rolled);
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
    /* `n` COUNTS CARDS from item 106 on, because that is what the menu draws
     * and what the highlight walks; `nimg` is the image lines behind them.
     * `hl` and `chosen` are CARD indexes, `hlimg`, `lastimg` and `boot` are
     * IMAGE indexes - the choice file, the last-choice file, default= and
     * select.sh have always spoken images and still do. */
    int headless, snapshot, invert, timeout, n, nimg, hl, hlimg, lastimg, lastcard;
    int chosen = -1, boot = -1, w, h, volume, pinned;
    int machine_v = -1;       /* volume=machine: the machine's own 0-63, else -1 */
    int audio_up = 0;         /* the bridge brought the audio section up (hw only) */
    int action;                       /* this title has a lockdown-bar ACTION button */
    int music_voice = -1;
    const struct audio_clip *music_clip = NULL;
    const char *how, *fmt_path;
    long long start, deadline, last_key;   /* sel_now_ms() values: long long, see log.h */
    /* when the cache is due to be re-aimed on the highlight; 0 = not due.
     * Armed by a move, disarmed by the re-aim (item 109). */
    long long reaim_due = 0;
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
    nimg = c.n;
    n = c.ncards;
    /* everything a group got wrong: dropped, never fatal, and said here so a
     * run log explains a card the builder expected and cannot see */
    {
        int wi;
        for (wi = 0; wi < c.nwarn && wi < CONF_MAX_WARN; wi++) sel_log("conf: %s", c.warn[wi]);
        if (c.nwarn > CONF_MAX_WARN)
            sel_log("conf: %d more problem(s) not listed", c.nwarn - CONF_MAX_WARN);
    }
    if (c.ngroups)
        sel_log("conf: %d image line(s) in %d card(s), %d group(s)", nimg, n, c.ngroups);
    timeout = o.timeout >= 0 ? o.timeout : c.timeout >= 0 ? c.timeout : DEF_TIMEOUT;
    volume = o.volume >= 0 ? o.volume : c.volume >= 0 ? c.volume : DEF_VOLUME;
    snapshot = o.snapshot != NULL;
    /* --highlight, --default, default= and the last-choice file all name an
     * IMAGE; the menu highlights the CARD that image belongs to.  That one
     * mapping is what lets a remembered member light its jukebox card up
     * again, and it is why a group needs no state file of its own: the next
     * countdown rolls from that card afresh (item 106). */
    /* ONE LADDER, most specific first.  Two of the rungs name a CARD and the
     * rest name an IMAGE, which is the whole subtlety: `default=` and the
     * last-choice file have always spoken images, and a card named outright is
     * the only way to reach a KEEPING group's card, because once its members
     * keep cards of their own no image index resolves to the group. */
    /* THE LAST CHOICE IS READ BEFORE THE LADDER, not inside one of its rungs.
     * It is TWO things: the highlight's strongest rung, and the roll's
     * exclusion - and a rung that named a card outright used to skip the read
     * entirely, so a group could hand back the very build the player had just
     * booted from its own card.  The file is the machine's memory either way. */
    lastcard = -1;
    lastimg = snapshot ? -1 : conf_read_last(o.last, &lastcard);
    hl = -1;
    hlimg = -1;
    if (o.highlight_card >= 0) {
        if (o.highlight_card >= c.ncards) {
            sel_say("error: --highlight-card %d out of range (%d card%s)",
                    o.highlight_card, c.ncards, c.ncards == 1 ? "" : "s");
            return 2;
        }
        hl = o.highlight_card;
        how = "--highlight-card";
    } else if (snapshot) {
        /* the preview never reads the last-choice file: the image asked for,
         * else the conf's default, is what it shows */
        if (o.highlight >= 0) {
            if (o.highlight >= nimg) {
                sel_say("error: --highlight %d out of range (%d image%s)", o.highlight, nimg, nimg == 1 ? "" : "s");
                return 2;
            }
            hlimg = o.highlight;
            how = "--highlight";
        }
        else if (o.def >= 0 && o.def < nimg) { hlimg = o.def; how = "--default"; }
        else if (c.def_card >= 0) { hl = c.def_card; how = "conf default_card"; }
        else if (c.def >= 0 && c.def < nimg) { hlimg = c.def; how = "conf default"; }
        else { hlimg = 0; how = "first"; }
    } else {
        /* THE CARD IS REMEMBERED, NOT ONLY THE BUILD.  A random card's whole
         * point is that the player did not pick what it booted, so coming back
         * to that build's own card (a keeping group leaves it one) would turn
         * "surprise me" into "that one, from now on" after a single power-up.
         * Only a GROUP card is taken from the file: for any other the image
         * below resolves to the same card, and the image is the older, better
         * tested road. */
        hlimg = lastimg;
        if (lastcard >= 0 && lastcard < c.ncards && conf_card_group(&c, lastcard) >= 0
            && card_has_member(&c, lastcard, lastimg)) {
            hl = lastcard;
            hlimg = -1;
            how = "last choice";
        }
        else if (hlimg >= 0 && hlimg < nimg) how = "last choice";
        else if (o.def >= 0 && o.def < nimg) { hlimg = o.def; how = "--default"; }
        /* DEFAULT_CARD OUTRANKS DEFAULT, because a conf carries both and only
         * one of them can be a deliberate answer: every conf this builder has
         * ever written has a `default=`, and `default_card=` is written only
         * when somebody named a card that no image can name.  The other way
         * round, a menu meant to power up on "surprise me" powered up on
         * whichever build `default=` happened to hold (seen on the rig). */
        else if (c.def_card >= 0) { hl = c.def_card; how = "conf default_card"; }
        else if (c.def >= 0 && c.def < nimg) { hlimg = c.def; how = "conf default"; }
        else { hlimg = 0; how = "first"; }
    }
    if (hl < 0) {
        hl = conf_card_of_image(&c, hlimg);
        if (hl < 0) hl = 0;
    }
    /* A CARD-NAMED RUNG LEAVES NO IMAGE BEHIND IT, so one is derived for the
     * log alone.  The other way round it must NOT be: `highlight` echoes the
     * image the caller asked for, and overwriting it with the card's first
     * member would quietly rename what somebody typed. */
    if (hlimg < 0) {
        hlimg = conf_card_boots(&c, hl);
        if (hlimg < 0) hlimg = conf_card_member(&c, hl, 0);
        if (hlimg < 0) hlimg = 0;
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
        rc = snapshot_frame(&o, &c, &g, font, &L, hl, hlimg, how, timeout, invert, fontpath, action);
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
    /* THE INPUT FIRST - the node bus is also the way to the CPU board's bridge
     * MCU, which the audio section below is brought up through */
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

    /* THE AUDIO SECTION, in the game's order (0x1fa9c8 then 0x1fb2a8): the
     * codecs as found go in the log; the amplifiers are muted in the cabinet
     * word; the bridge MCU is told to bring the audio section up (08 01 01 -
     * until then it answers `0a 00` with bit 1 clear, "audio not initialized",
     * and no codec register, ALSA switch, SPI bit or GPIO the menu could set
     * made a sound: David's Godzilla, five silent builds); both codecs are
     * waited for at their reset value, the game's 750 ms, its standby table;
     * THEN the stream, and once it runs 0b 01 06 and the unmute.  Every step
     * is a no-op where there is no bridge (the emulator, --input none). */
    codec_configure(o.codec);
    if (strcmp(o.audio, "none")) {
        codec_snapshot("before the menu");
        input_hw_amp_mute(in, 1);
        if (input_hw_bridge(in, 0x08, 0x01) >= 0) {
            codec_after_reset();
            audio_up = 1;
        }
    }
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
    /* THE FRAME CACHE (art.h): clips decoded once, on a thread below this one,
     * and played from RAM - on the machine a frame costs 13 ms to decode,
     * which is not a cost the menu loop can pay three times in a 33 ms frame,
     * and two clips at their rate were already more than half the CPU here.
     * The budget only stretches to a handful of clips, so it goes to the ones
     * NEAREST THE HIGHLIGHT and follows it from here (item 109).  Not when the
     * frames are pinned: those modes need frame k exactly. */
    if (!pinned) {
        struct art_anim *rank[CONF_MAX_CARDS];
        char why[240];
        int k, ai;
        for (ai = 0; ai < n; ai++) if (media.anim[ai]) media.anim[ai]->idx = ai;
        k = rank_by_distance(rank, media.anim, n, hl);
        art_cache_set(rank, k, anim_cache_budget(), why, sizeof why);
        sel_log("anim: cache on image %d: %s", hl, why);
    }

    /* (the input backend was opened before the sound: see THE AUDIO SECTION) */
    /* the backend is the authority once it exists: padsw may resolve its table
     * later than the probe above could, and --input none has no buttons */
    action = input_has(in, EV_ACTION);
    /* the bring-up's last step (the game's 0x1d7e3c after its audio init), then
     * the amplifiers back on now that the stream is running - no-ops off hw */
    if (audio_up) input_hw_bridge(in, 0x0b, 0x06);
    input_hw_amp_mute(in, 0);

    {
        char cardinfo[CONF_STR + 64];
        card_note(&c, hl, n, cardinfo, sizeof cardinfo);
        sel_say("menu: %d image%s, highlight %d (%s) from %s%s, timeout %d s, input %s, invert %d, %dx%d, font %s, audio %s, media %s, footer \"%s\"",
                nimg, nimg == 1 ? "" : "s", hlimg, conf_card_face(&c, hl)->title, how, cardinfo,
                timeout, o.input, invert, w, h, fontpath,
                audio_sink_name(au), media.dir, action ? FOOT_ACTION : FOOT_START);
    }
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

    /* the loop's own account: how many passes, the longest one (a stall this
     * long is a press that can be missed on a polled backend and a hitch in
     * every picture), and how far the cache has got.  Every 5 s for the first
     * minute (the bring-up and the cache fill), then once a minute: a menu
     * left idle must not talk a log full */
    long long perf_every = 5000, perf_due = start + perf_every, perf_worst = 0;
    int perf_loops = 0;

    while (!g_stop) {
        long long now = sel_now_ms();
        int ev, remain, old_hl = hl;

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
            /* WHERE THE HIGHLIGHT WENT, one line per move.  From five images
             * up the menu is a carousel of three and the highlight is the
             * only thing that says where in the set you are, so a run log
             * without this cannot tell a menu that moved twice from one that
             * moved four times and wrapped - which is exactly what a carousel
             * proof has to show.  `card k/n` is the counter the player sees
             * under the panels, 1-based like the display, and `wrap` marks
             * the step that crossed the end. */
            sel_log("menu: highlight %d -> %d (%s), card %d/%d%s", old_hl, hl,
                    conf_card_face(&c, hl)->title, hl + 1, n,
                    (old_hl == 0 && hl == n - 1) || (old_hl == n - 1 && hl == 0) ? " - wrap" : "");
            /* the cache follows, once the scrolling stops (item 109) */
            if (!pinned) reaim_due = now + cache_settle_ms();
            /* a new card: its music takes over (hard switch); the
             * animations all keep running - they were never paused */
            if (media.music[hl] != music_clip) {
                if (music_voice >= 0) audio_stop(au, music_voice);
                music_clip = media.music[hl];
                music_voice = music_clip ? audio_play(au, music_clip, 1) : -1;
            }
        }
        /* THE CACHE FOLLOWS THE HIGHLIGHT, on a settle rather than on every
         * press.  Everything else about the animations is untouched: every
         * clip's timeline keeps ticking whether or not its frames are cached
         * (media_tick), because all the cards animate together rather than
         * only the highlighted one, and a card you scroll to has to be
         * mid-loop rather than starting over. Only the FRAMES move. */
        if (reaim_due && now >= reaim_due) {
            struct art_anim *rank[CONF_MAX_CARDS];
            char why[240];
            int k = rank_by_distance(rank, media.anim, n, hl);
            art_cache_set(rank, k, anim_cache_budget(), why, sizeof why);
            sel_log("anim: cache re-aimed on image %d: %s", hl, why);
            reaim_due = 0;
        }
        if (deadline) {
            /* a key restarts the countdown so a reader is not cut off */
            if (last_key > start) { deadline = last_key + (long long)timeout * 1000LL; start = last_key; }
            if (now >= deadline) {
                sel_log("countdown expired: booting card %d", hl + 1);
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
            unsigned char moved[CONF_MAX_CARDS];
            int nmoved = pinned ? 0 : media_tick(&media, n, (double)now, moved);
            int i;
            for (i = 0; nmoved && i < n; i++) {
                if (!moved[i]) continue;
                if (!dirty) {
                    int slot = image_slot(&L, hl, i);
                    if (slot >= 0) draw_panel(&g, &L, &media, i, slot, i == hl);
                }
                media.paints[i]++;      /* what the tick was FOR (media_stats) */
                media_check(&media, i);
            }
        }
        audio_pump(au, now);

        if (dirty) {
            draw_menu(&g, font, &L, &c, &media, hl, remain, action);
            dirty = 0;
        }
        present(&g, &egl, headless, invert);
        {
            long long dt = sel_now_ms() - now;
            if (dt > perf_worst) perf_worst = dt;
            perf_loops++;
            if (now >= perf_due) {
                char cs[200];
                int ci, cn = 0;
                for (ci = 0; ci < n && cn < (int)sizeof cs - 24; ci++)
                    if (media.anim[ci])
                        cn += snprintf(cs + cn, sizeof cs - (size_t)cn, "%s%d:%d/%d", cn ? " " : "",
                                       ci, art_anim_ready(media.anim[ci]), media.anim[ci]->n);
                sel_log("perf: %d loops in %lld s (%lld/s), longest %lld ms; cache %s",
                        perf_loops, perf_every / 1000, perf_loops * 1000 / perf_every,
                        perf_worst, cn ? cs : "-");
                perf_loops = 0;
                perf_worst = 0;
                if (now - start >= 60000) perf_every = 60000;
                perf_due = now + perf_every;
            }
        }
    }

    if (chosen >= 0) {
        /* WHAT THE CARD ACTUALLY BOOTS.  A plain card boots its own image; a
         * group rolls one of its members HERE, at the confirm, so the seed
         * has the whole time the player spent in the menu in it.  --pick
         * names a member outright (tests and proof runs) and is honoured only
         * when it really is one of this card's members: a --pick that misses
         * would otherwise boot something the menu never offered. */
        char rolled[CONF_STR + 80] = "";
        boot = conf_card_boots(&c, chosen);
        if (boot < 0) {
            if (o.pick >= 0) {
                int k, nm = conf_card_nmembers(&c, chosen), ok = 0;
                for (k = 0; k < nm; k++) if (conf_card_member(&c, chosen, k) == o.pick) ok = 1;
                if (ok) {
                    boot = o.pick;
                    snprintf(rolled, sizeof rolled, " (--pick from %s)", conf_card_face(&c, chosen)->title);
                } else {
                    sel_log("--pick %d is not a member of %s: rolling instead",
                            o.pick, conf_card_face(&c, chosen)->title);
                }
            }
            if (boot < 0) {
                char why[CONF_STR + 64];
                boot = roll_member(&c, chosen, lastimg, o.seed, why, sizeof why);
                snprintf(rolled, sizeof rolled, " (%s)", why);
            }
            sel_log("group: card %d boots image %d%s", chosen + 1, boot, rolled);
        }
        if (headless) {
            if (gfx_write_ppm(&g, o.headless, invert) < 0)
                sel_log("cannot write %s: %s", o.headless, strerror(errno));
            else
                sel_log("wrote %s (%dx%d)", o.headless, w, h);
        }
        /* the LOADING frame names the MEMBER under the GROUP's picture: the
         * card said "a different song set every power-up", so this is the one
         * moment the player is told which set they got */
        draw_loading(&g, font, &L.th, c.img[boot].title, c.img[boot].subtitle,
                     loading_picture(&c, &media, chosen, boot));
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
            /* `image %d` here is a CARD index, like every other one in this
             * file's log: padsw_test.py pins the wording (see the note on
             * struct media), and the number was always the card's anyway */
            if (cc) snprintf(cwhich, sizeof cwhich, "image %d sound %s", chosen, conf_card_face(&c, chosen)->confirm);
            else if ((cc = media.confirm) != NULL) snprintf(cwhich, sizeof cwhich, "menu sound %s", c.sound_confirm);
            else snprintf(cwhich, sizeof cwhich, "no sound");
            if (music_voice >= 0) audio_stop(au, music_voice);
            if (cc) cv = audio_play(au, cc, 0);
            while (!g_stop) {
                long long now = sel_now_ms();
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
        /* BOTH FILES GET THE IMAGE, never the card: select.sh's awk counts
         * image= lines and run_game.sh translates an image index, and neither
         * has any idea groups exist.  That is the whole reason the grammar
         * put members in the image array. */
        /* THE CARD IS RECORDED ONLY WHEN THE IMAGE DOES NOT FIND IT AGAIN,
         * which is exactly a random card whose members keep cards of their own.
         * Everywhere else the image resolves straight back to the card it was
         * chosen from, so a second number would say nothing and would change
         * this file for every menu - a group-free card's behaviour is
         * byte-identical to 2.9's on purpose. */
        if (conf_write_last(o.last, boot,
                            conf_card_of_image(&c, boot) != chosen ? chosen : -1) < 0)
            sel_log("cannot write %s: %s (continuing)", o.last, strerror(errno));
        if (conf_write_choice(o.out, boot) < 0) {
            sel_say("error: cannot write %s: %s", o.out, strerror(errno));
        } else {
            sel_say("chose %d %s%s", boot, c.img[boot].title, rolled);
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
    art_cache_stop();
    media_free(&media);
    gfx_free(&g);
    gfx_font_free(font);
    sel_log("exit %d", rc);
    sel_log_close();
    return rc;
}
