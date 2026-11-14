/* settings.c - see settings.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include "settings.h"
#include "colour.h"
#include "testpics.h"
#include "art.h"
#include "log.h"

#define TH(e, role) ((e)->th->rgb[TH_##role])

/* how a held flipper repeats a step, once it has been held this long */
#define REPEAT_AFTER_MS 450
#define REPEAT_EVERY_MS 80

/* one press of a value row */
#define STEP_GAMMA 0.05f
#define STEP_GAIN  0.02f
#define STEP_SAT   0.05f
#define STEP_LIFT  0.005f
#define STEP_BRIGHT   0.05f
#define STEP_CONTRAST 0.05f

/* THE STARTING POINTS the Color profile tab offers (core/colour_profile.py
 * PRESETS - tests/test_stern_shader_profile.py holds these numbers to that
 * table), after "As built", which is each image's own. */
struct preset {
    const char *name;
    float gamma[3], gain[3], lift[3], sat;
};
static const struct preset PRESETS[] = {
    { "Recommended",     { 1.10f, 1.20f, 1.35f }, { 1, 1, 1 }, { 0, 0, 0 }, 0.90f },
    { "No change",       { 1, 1, 1 },             { 1, 1, 1 }, { 0, 0, 0 }, 1.00f },
    { "Black and white", { 1, 1, 1 },             { 1, 1, 1 }, { 0, 0, 0 }, 0.00f },
};
#define NPRESETS ((int)(sizeof PRESETS / sizeof PRESETS[0]))

static void preset_colour(int k, struct colour *out)
{
    memcpy(out->gamma, PRESETS[k].gamma, sizeof out->gamma);
    memcpy(out->gain, PRESETS[k].gain, sizeof out->gain);
    memcpy(out->lift, PRESETS[k].lift, sizeof out->lift);
    out->sat = PRESETS[k].sat;
    out->bright = out->contrast = 1.0f;
}

enum row_kind { R_GAME, R_PRESET, R_BRIGHT, R_CONTRAST, R_SAT, R_GAMMA, R_GAIN, R_LIFT,
                R_SAVE, R_TEST, R_SAVE_ALL, R_LEAVE };
struct row { int kind, ch; };

enum screen { S_LIST, S_COLOR, S_TEST, S_DONE };

/* the Settings list's entries (PAD-1279: Test pictures joined Color correction) */
enum { L_COLOR, L_TEST, L_BACK };

/* the frames a test= animation may have; the app makes them fit */
#define TEST_ANIM_FRAMES 600

struct state {
    struct settings_env *e;
    int screen;
    int list_sel;
    /* the colour screen */
    int imgs[CONF_MAX_IMAGES], nimg, cur;
    struct colour work[CONF_MAX_IMAGES];     /* per image: what the screen shows */
    struct colour saved[CONF_MAX_IMAGES];    /* per image: what it boots with now */
    int has_saved[CONF_MAX_IMAGES];          /* ...and whether that is the file's, not the build's */
    struct row rows[16];
    int nrows, sel, editing;
    char status[240];
    int preset_k;                            /* START FROM while it is being changed: 0 = as built */
    int hold_ev;                             /* the key being held while editing, or 0 */
    long long next_rep;
    int move_voice;
    /* the TEST PICTURES screen (PAD-1279) */
    int colour_ready;                        /* colour_open has filled imgs / work */
    int t_item;                              /* what is up: TP_* first, then c->test[], then BACK */
    int t_col;                               /* the correction it is drawn through: imgs[t_col], -1 none */
    int t_from;                              /* the screen BACK goes to: S_LIST or S_COLOR */
    int t_caption;                           /* the caption is up... */
    long long t_caption_until;               /* ...until then (0: for good - a snapshot) */
    struct art_image *t_img;                 /* the picture up, or NULL */
    struct art_anim *t_anim;                 /* the animation up, or NULL */
    int t_frame;
    long long t_next_ms;                     /* when its next frame is due */
    struct audio_clip *t_clip[CONF_MAX_TESTS];   /* sounds, loaded when first played */
    int t_voice;
    char t_err[240];                         /* why the item up cannot be shown, or "" */
};

static const char *const CH_NAME[3] = { "RED", "GREEN", "BLUE" };
static const unsigned CH_RGB[3] = { 0xE05555, 0x55C060, 0x5588E8 };

/* ------------------------------------------------------------- the values */

static const struct conf_colour *built_of(const struct state *st, int img)
{
    return &st->e->c->colour[img];
}

static int image_dirty(const struct state *st, int img)
{
    return !colour_equal(&st->work[img], &st->saved[img]);
}

static int any_dirty(const struct state *st)
{
    int k;
    for (k = 0; k < st->nimg; k++)
        if (image_dirty(st, st->imgs[k])) return 1;
    return 0;
}

/* which starting point the numbers are: 0 = as built, 1.. = PRESETS[k-1],
 * -1 = none of them (somebody's own) */
static int preset_of(const struct state *st, const struct colour *c, int img)
{
    int k;
    if (colour_equal(c, &built_of(st, img)->built)) return 0;
    for (k = 0; k < NPRESETS; k++) {
        struct colour p;
        preset_colour(k, &p);
        if (colour_equal(c, &p)) return k + 1;
    }
    return -1;
}

static float lift_of(const struct colour *c)
{
    return (c->lift[0] + c->lift[1] + c->lift[2]) / 3.0f;
}

static float stepped(float v, float step, int dir, float lo, float hi)
{
    v = roundf(v / step) * step + (float)dir * step;
    v = roundf(v / step) * step;
    return v < lo ? lo : v > hi ? hi : v;
}

static void value_text(const struct row *r, const struct colour *c, char *out, int n)
{
    switch (r->kind) {
    case R_GAMMA: {
        int d = (int)lroundf((c->gamma[r->ch] - 1.0f) * 100.0f);
        if (d == 0) snprintf(out, (size_t)n, "unchanged");
        else if (d > 0) snprintf(out, (size_t)n, "%d%% darker", d);
        else snprintf(out, (size_t)n, "%d%% brighter", -d);
        break;
    }
    case R_GAIN:
        snprintf(out, (size_t)n, "%d%%", (int)lroundf(c->gain[r->ch] * 100.0f));
        break;
    case R_SAT:
        snprintf(out, (size_t)n, "%d%%", (int)lroundf(c->sat * 100.0f));
        break;
    case R_BRIGHT:
        snprintf(out, (size_t)n, "%d%%", (int)lroundf(c->bright * 100.0f));
        break;
    case R_CONTRAST:
        snprintf(out, (size_t)n, "%d%%", (int)lroundf(c->contrast * 100.0f));
        break;
    case R_LIFT: {
        float l = lift_of(c);
        if (l < 0.002f) snprintf(out, (size_t)n, "off");
        else snprintf(out, (size_t)n, "black becomes %d of 255", (int)lroundf(l * 255.0f));
        break;
    }
    default:
        out[0] = 0;
    }
}

/* one LEFT (-1) / RIGHT (+1) on the row being changed; 1 when anything moved */
static int step_row(struct state *st, int dir)
{
    const struct row *r = &st->rows[st->sel];
    int img = st->imgs[st->cur];
    struct colour *c = &st->work[img], before = *c;
    switch (r->kind) {
    case R_GAME:
        if (st->nimg < 2) return 0;
        st->cur = (st->cur + dir + st->nimg) % st->nimg;
        sel_log("color: now %s (image %d)", st->e->c->img[st->imgs[st->cur]].title, st->imgs[st->cur]);
        return 1;
    case R_PRESET: {
        /* through As built and the starting points, from the one the row
         * showed when it was opened - KEPT, not worked out from the numbers
         * again, or a game built with Recommended could never step past it:
         * its numbers are As built and Recommended both */
        int total = NPRESETS + 1;
        st->preset_k = (st->preset_k + dir + total) % total;
        if (st->preset_k == 0) *c = built_of(st, img)->built;
        else preset_colour(st->preset_k - 1, c);
        return 1;
    }
    case R_GAMMA:
        c->gamma[r->ch] = stepped(c->gamma[r->ch], STEP_GAMMA, dir, COLOUR_GAMMA_MIN, COLOUR_GAMMA_MAX);
        break;
    case R_GAIN:
        c->gain[r->ch] = stepped(c->gain[r->ch], STEP_GAIN, dir, COLOUR_GAIN_MIN, COLOUR_GAIN_MAX);
        break;
    case R_SAT:
        c->sat = stepped(c->sat, STEP_SAT, dir, COLOUR_SAT_MIN, COLOUR_SAT_MAX);
        break;
    case R_BRIGHT:
        c->bright = stepped(c->bright, STEP_BRIGHT, dir, COLOUR_BRIGHT_MIN, COLOUR_BRIGHT_MAX);
        break;
    case R_CONTRAST:
        c->contrast = stepped(c->contrast, STEP_CONTRAST, dir, COLOUR_CONTRAST_MIN, COLOUR_CONTRAST_MAX);
        break;
    case R_LIFT: {
        float l = stepped(lift_of(c), STEP_LIFT, dir, COLOUR_LIFT_MIN, COLOUR_LIFT_MAX);
        c->lift[0] = c->lift[1] = c->lift[2] = l;
        break;
    }
    default:
        return 0;
    }
    return !colour_equal(&before, c);
}

static void build_rows(struct state *st)
{
    int k, n = 0;
    if (st->nimg > 1) st->rows[n++] = (struct row){ R_GAME, 0 };
    st->rows[n++] = (struct row){ R_PRESET, 0 };
    /* PAD-537: the plain controls first - what an owner reaches for - then
     * the per-channel ones the Color profile tab has */
    st->rows[n++] = (struct row){ R_BRIGHT, 0 };
    st->rows[n++] = (struct row){ R_CONTRAST, 0 };
    st->rows[n++] = (struct row){ R_SAT, 0 };
    for (k = 0; k < 3; k++) st->rows[n++] = (struct row){ R_GAMMA, k };
    for (k = 0; k < 3; k++) st->rows[n++] = (struct row){ R_GAIN, k };
    st->rows[n++] = (struct row){ R_LIFT, 0 };
    /* PAD-1279: these numbers on the test pictures, full screen, unsaved */
    st->rows[n++] = (struct row){ R_TEST, 0 };
    st->rows[n++] = (struct row){ R_SAVE, 0 };
    if (st->nimg > 1) st->rows[n++] = (struct row){ R_SAVE_ALL, 0 };
    st->rows[n++] = (struct row){ R_LEAVE, 0 };
    st->nrows = n;
}

static void colour_open(struct state *st)
{
    const struct conf *c = st->e->c;
    int i, first = 0;
    st->nimg = 0;
    for (i = 0; i < c->n; i++) {
        if (!c->colour[i].set) continue;
        if (i == st->e->first_image) first = st->nimg;
        st->imgs[st->nimg++] = i;
        st->has_saved[i] = colour_file_get(st->e->colour_file, c->img[i].device, &st->saved[i]);
        if (!st->has_saved[i]) st->saved[i] = c->colour[i].built;
        st->work[i] = st->saved[i];
    }
    st->cur = first;
    st->colour_ready = 1;
    build_rows(st);
    st->sel = 0;
    st->editing = 0;
    st->hold_ev = 0;
    st->status[0] = 0;
    {
        int img = st->imgs[st->cur];
        char vals[200];
        colour_format(&st->work[img], vals, sizeof vals);
        sel_say("settings: color correction, %d adjustable image%s, on image %d (%s): %s (%s)",
                st->nimg, st->nimg == 1 ? "" : "s", img, c->img[img].title, vals,
                st->has_saved[img] ? "set on this machine" : "as built");
    }
}

/* one image's numbers to the values file: none when they are the build's own */
static int save_image(struct state *st, int img, const struct colour *v)
{
    const struct conf *c = st->e->c;
    int as_built = colour_equal(v, &c->colour[img].built);
    char vals[200];
    if (colour_file_put(st->e->colour_file, c->img[img].device, as_built ? NULL : v) < 0) {
        sel_say("color: image %d (%s): cannot write %s: %s", img, c->img[img].title,
                st->e->colour_file, strerror(errno));
        return -1;
    }
    st->saved[img] = *v;
    st->work[img] = *v;
    st->has_saved[img] = !as_built;
    colour_format(v, vals, sizeof vals);
    sel_say("color: image %d (%s) saved: %s%s", img, c->img[img].title, vals,
            as_built ? " (as built: no line in the values file)" : "");
    return 0;
}

/* the Settings list as this card has it: Color correction only when an image
 * can be corrected; Test pictures always (the built-in patterns need nothing) */
static int list_items(const struct state *st, int out[3])
{
    int n = 0;
    if (st->e->c->ncolour > 0) out[n++] = L_COLOR;
    out[n++] = L_TEST;
    if (!st->e->testcard) out[n++] = L_BACK;    /* a test card has no games to go back to */
    return n;
}

/* ------------------------------------------------------------ test pictures */

static int test_count(const struct state *st)
{
    return TP_NBUILTIN + st->e->c->ntest + 1;      /* + BACK */
}

static const struct conf_test *test_own(const struct state *st, int k)
{
    int j = k - TP_NBUILTIN;
    return j >= 0 && j < st->e->c->ntest ? &st->e->c->test[j] : NULL;
}

static int test_is_back(const struct state *st, int k)
{
    return k == test_count(st) - 1;
}

static int test_kind(const struct state *st, int k)
{
    const struct conf_test *t = test_own(st, k);
    return t ? testpics_kind(t->file) : TF_UNKNOWN;
}

static const char *test_name(const struct state *st, int k)
{
    const struct conf_test *t = test_own(st, k);
    if (k < TP_NBUILTIN) return testpics_name(k);
    if (t) return t->label;
    return st->t_from == S_COLOR ? "Back to color correction" : "Back to settings";
}

static void test_unload(struct state *st)
{
    if (st->t_img) { art_image_free(st->t_img); st->t_img = NULL; }
    if (st->t_anim) { art_anim_free(st->t_anim); st->t_anim = NULL; }
    if (st->t_voice >= 0) { audio_stop(st->e->au, st->t_voice); st->t_voice = -1; }
    st->t_err[0] = 0;
}

static int anim_delay(const struct art_anim *a, int k)
{
    if (a->period_ms > 0) return (int)lroundf(a->period_ms);
    return a->delay_ms[k % a->n];
}

static void test_play(struct state *st)
{
    int j = st->t_item - TP_NBUILTIN;
    if (st->t_voice >= 0) { audio_stop(st->e->au, st->t_voice); st->t_voice = -1; }
    if (j >= 0 && j < CONF_MAX_TESTS && st->t_clip[j] && st->e->au)
        st->t_voice = audio_play(st->e->au, st->t_clip[j], 0);
}

/* the item up, read from the card (pictures and animations again each time:
 * one at a time in RAM; sounds once, kept until Settings closes) */
static void test_load(struct state *st, long long now)
{
    struct settings_env *e = st->e;
    const struct conf_test *t = test_own(st, st->t_item);
    char path[2 * CONF_STR + 2];
    test_unload(st);
    if (t) {
        snprintf(path, sizeof path, "%s/%s", e->media_dir && *e->media_dir ? e->media_dir : ".",
                 t->file);
        switch (testpics_kind(t->file)) {
        case TF_PICTURE:
            st->t_img = art_load_png(path, e->g->w, e->g->h, st->t_err, sizeof st->t_err);
            break;
        case TF_ANIM:
            st->t_anim = art_anim_open(path, e->g->w, e->g->h, TEST_ANIM_FRAMES, st->t_err,
                                       sizeof st->t_err);
            st->t_frame = 0;
            if (st->t_anim) st->t_next_ms = now + anim_delay(st->t_anim, 0);
            break;
        case TF_SOUND: {
            int j = st->t_item - TP_NBUILTIN;
            if (!st->t_clip[j]) st->t_clip[j] = audio_load_wav(path, st->t_err, sizeof st->t_err);
            test_play(st);
            break;
        }
        default:
            snprintf(st->t_err, sizeof st->t_err, "%s is not a PNG, GIF or WAV", t->file);
        }
    }
    sel_say("test: %d/%d %s%s%s%s", st->t_item + 1, test_count(st), test_name(st, st->t_item),
            t ? " (" : "", t ? t->file : "", t ? ")" : "");
    if (st->t_err[0]) sel_say("test: %s", st->t_err);
}

static void colour_open(struct state *st);

static void test_open(struct state *st, int from, long long now)
{
    const struct conf *c = st->e->c;
    /* from the list the games draw as they will next start (their saved
     * numbers); from Color correction, with the numbers being changed */
    if (from == S_LIST && c->ncolour > 0) colour_open(st);
    st->t_from = from;
    st->t_col = c->ncolour > 0 ? st->cur : -1;
    st->t_item = 0;
    st->t_voice = -1;
    st->t_caption = 1;
    st->t_caption_until = now + TEST_CAPTION_MS;
    st->screen = S_TEST;
    sel_say("test: open (%d built-in, %d of the card's own)", TP_NBUILTIN, c->ntest);
    test_load(st, now);
}

static void test_close(struct state *st)
{
    test_unload(st);
    st->screen = st->t_from;
    sel_say("test: closed");
}

/* one animation tick: 0 nothing, 1 the frame changed (only the frame's own
 * rectangle needs drawing), 2 the caption went (the whole screen does) */
static int test_tick(struct state *st, long long now)
{
    int changed = 0;
    if (st->t_anim && st->t_anim->n > 1 && now >= st->t_next_ms) {
        st->t_frame = (st->t_frame + 1) % st->t_anim->n;
        st->t_next_ms += anim_delay(st->t_anim, st->t_frame);
        if (st->t_next_ms < now) st->t_next_ms = now;      /* fell behind: no catch-up burst */
        changed = 1;
    }
    if (st->t_caption && st->t_caption_until && now >= st->t_caption_until) {
        st->t_caption = 0;
        changed = 2;
    }
    return changed;
}

/* ------------------------------------------------------------------ draw */

static float S(const struct settings_env *e)
{
    return (float)e->g->h / 768.0f;
}

static void text_fit(struct settings_env *e, const char *s, float px, float min_px, int max_w,
                     int x, int base, int align, unsigned rgb)
{
    char cut[300];
    float p = gfx_fit_px(e->font, s, max_w, px, min_px);
    int w;
    gfx_ellipsize(e->font, p, s, max_w, cut, sizeof cut);
    w = gfx_text_width(e->font, p, cut);
    if (align == 0) gfx_text_center(e->g, e->font, p, x, base, cut, rgb);
    else gfx_text(e->g, e->font, p, align < 0 ? x : x - w, base, cut, rgb);
}

static void draw_footer(struct settings_env *e, const char *line)
{
    float s = S(e);
    text_fit(e, line, 28 * s, 18 * s, e->g->w - (int)(80 * s), e->g->w / 2, (int)(728 * s), 0,
             TH(e, FOOTER));
}

static void draw_list(struct state *st)
{
    struct settings_env *e = st->e;
    float s = S(e);
    int W = e->g->w, k, it[3], n = list_items(st, it);
    static const char *const TITLES[3] = { "COLOR CORRECTION", "TEST PICTURES", "BACK TO THE GAMES" };
    static const char *const SUBS[3] = { "How the screen shows each game's colors",
                                         "Patterns and the card's own pictures, full screen", "" };
    int rw = (int)(760 * s), rh = (int)(110 * s), x = (W - rw) / 2;
    int y0 = (int)((n > 2 ? 170 : 220) * s);

    gfx_fill(e->g, TH(e, BACKGROUND));
    text_fit(e, e->testcard ? "TEST CARD" : "SETTINGS", 60 * s, 30 * s, W - (int)(80 * s), W / 2,
             (int)(96 * s), 0, TH(e, HEADING));
    for (k = 0; k < n; k++) {
        int on = k == st->list_sel, y = y0 + k * (rh + (int)(30 * s)), i = it[k];
        gfx_round_frame(e->g, x, y, rw, rh, (int)(22 * s), (int)((on ? 8 : 3) * s),
                        on ? TH(e, FRAME_HL) : TH(e, FRAME), on ? TH(e, CARD_HL) : TH(e, CARD));
        if (*SUBS[i]) {
            text_fit(e, TITLES[i], 40 * s, 24 * s, rw - (int)(60 * s), W / 2, y + (int)(52 * s), 0,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
            text_fit(e, SUBS[i], 24 * s, 18 * s, rw - (int)(60 * s), W / 2, y + (int)(88 * s), 0,
                     on ? TH(e, SUBTITLE_HL) : TH(e, SUBTITLE));
        } else {
            text_fit(e, TITLES[i], 40 * s, 24 * s, rw - (int)(60 * s), W / 2, y + (int)(70 * s), 0,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
        }
    }
    draw_footer(e, "LEFT / RIGHT FLIPPER: choose      START: open");
}

static const char *row_label(const struct state *st, const struct row *r)
{
    switch (r->kind) {
    case R_GAME: return "GAME";
    case R_PRESET: return "START FROM";
    case R_GAMMA: return r->ch == 0 ? "MIDDLE SHADES" : "";
    case R_GAIN: return r->ch == 0 ? "COLOR LEVEL" : "";
    case R_BRIGHT: return "BRIGHTNESS";
    case R_CONTRAST: return "CONTRAST";
    case R_SAT: return "SATURATION";
    case R_LIFT: return "DARKEST SHADES";
    case R_SAVE: return st->nimg > 1 ? "SAVE FOR THIS GAME" : "SAVE";
    case R_SAVE_ALL: return "SAVE FOR EVERY GAME";
    case R_TEST: return "SEE IT ON THE TEST PICTURES";
    case R_LEAVE: return any_dirty(st) ? "LEAVE WITHOUT SAVING" : "BACK";
    }
    return "";
}

static void draw_colour(struct state *st)
{
    struct settings_env *e = st->e;
    const struct conf *c = e->c;
    float s = S(e);
    int W = e->g->w, img = st->imgs[st->cur], k;
    const struct colour *v = &st->work[img];
    int px = (int)(36 * s), pw = (int)(600 * s), y0 = (int)(124 * s);
    int rh = st->nrows > 15 ? (int)(34 * s) : st->nrows > 14 ? (int)(36 * s)
           : st->nrows > 12 ? (int)(39 * s) : (int)(42 * s);
    float tpx = 22 * s;
    char buf[300], val[120];

    gfx_fill(e->g, TH(e, BACKGROUND));
    text_fit(e, "COLOR CORRECTION", 46 * s, 28 * s, W - (int)(80 * s), W / 2, (int)(62 * s), 0,
             TH(e, HEADING));
    {
        int p = preset_of(st, &built_of(st, img)->built, img);
        const char *bn = built_of(st, img)->name;
        (void)p;
        snprintf(buf, sizeof buf, "%s  -  built with %s", c->img[img].title,
                 *bn ? bn : "a color profile of its own");
        text_fit(e, buf, 24 * s, 16 * s, W - (int)(80 * s), W / 2, (int)(100 * s), 0, TH(e, SUBTITLE));
    }

    for (k = 0; k < st->nrows; k++) {
        const struct row *r = &st->rows[k];
        int on = k == st->sel, y = y0 + k * rh, base = y + (int)(rh * 0.68f);
        int action = r->kind >= R_SAVE;
        if (action) y += (int)(10 * s), base += (int)(10 * s);
        if (on)
            gfx_round_frame(e->g, px, y + (int)(2 * s), pw, rh - (int)(4 * s), (int)(10 * s),
                            (int)((st->editing ? 5 : 3) * s), TH(e, FRAME_HL), TH(e, CARD_HL));
        else if (action)
            gfx_round_frame(e->g, px, y + (int)(2 * s), pw, rh - (int)(4 * s), (int)(10 * s),
                            (int)(2 * s), TH(e, FRAME), TH(e, CARD));
        if (action) {
            text_fit(e, row_label(st, r), tpx, 16 * s, pw - (int)(30 * s), px + pw / 2, base, 0,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
            continue;
        }
        text_fit(e, row_label(st, r), tpx, 16 * s, (int)(230 * s), px + (int)(16 * s), base, -1,
                 on ? TH(e, LABEL_HL) : TH(e, LABEL));
        if (r->kind == R_GAMMA || r->kind == R_GAIN) {
            int sq = (int)(14 * s);
            gfx_rect(e->g, px + (int)(252 * s), base - sq, sq, sq, CH_RGB[r->ch]);
            text_fit(e, CH_NAME[r->ch], tpx, 16 * s, (int)(100 * s), px + (int)(274 * s), base, -1,
                     on ? TH(e, TITLE_HL) : TH(e, TITLE));
        }
        if (r->kind == R_GAME) {
            snprintf(val, sizeof val, "%s", c->img[img].title);
        } else if (r->kind == R_PRESET) {
            int p = on && st->editing ? st->preset_k : preset_of(st, v, img);
            snprintf(val, sizeof val, "%s", p == 0 ? "As built" : p > 0 ? PRESETS[p - 1].name
                                                                   : "Your own");
        } else {
            value_text(r, v, val, sizeof val);
        }
        if (on && st->editing) snprintf(buf, sizeof buf, "<  %s  >", val);
        else snprintf(buf, sizeof buf, "%s", val);
        {
            /* the value's room starts after the label, and after the channel
             * name on the rows that have one */
            int vx0 = r->kind == R_GAMMA || r->kind == R_GAIN ? (int)(380 * s) : (int)(250 * s);
            text_fit(e, buf, tpx, 14 * s, pw - vx0 - (int)(16 * s), px + pw - (int)(16 * s), base, 1,
                     on ? TH(e, TITLE_HL) : TH(e, SUBTITLE));
        }
    }

    /* THE TEST CARD, corrected with what the rows say now: the same maths the
     * game's shaders will run (colour.h), on the CPU */
    {
        int cx = (int)(672 * s), cy = (int)(124 * s), cw = W - cx - (int)(36 * s);
        int ch = cw * 400 / 640;
        struct colour_lut lut;
        if (cy + ch > (int)(600 * s)) {
            ch = (int)(600 * s) - cy;
            cw = ch * 640 / 400;
        }
        gfx_rect(e->g, cx, cy, cw, ch, 0x181818);       /* marks it dirty */
        colour_test_card(e->g->px, e->g->w * 4, cx, cy, cw, ch);
        colour_lut_build(&lut, v);
        colour_lut_apply(&lut, e->g->px + ((size_t)cy * (size_t)e->g->w + (size_t)cx) * 4, cw, ch,
                         e->g->w * 4);
        text_fit(e, "Test card, as this game will draw it", 22 * s, 16 * s, cw, cx + cw / 2,
                 cy + ch + (int)(34 * s), 0, TH(e, FOOTER));
        if (st->status[0])
            snprintf(buf, sizeof buf, "%s", st->status);
        else if (image_dirty(st, img))
            snprintf(buf, sizeof buf, "Changed, not saved yet");
        else if (st->has_saved[img])
            snprintf(buf, sizeof buf, "Set on this machine");
        else
            snprintf(buf, sizeof buf, "As built");
        text_fit(e, buf, 24 * s, 16 * s, cw, cx + cw / 2, cy + ch + (int)(72 * s), 0,
                 TH(e, TITLE_HL));
    }

    if (st->editing)
        draw_footer(e, "LEFT / RIGHT FLIPPER: less / more      START: done");
    else if (st->rows[st->sel].kind >= R_SAVE)
        draw_footer(e, "LEFT / RIGHT FLIPPER: move      START: do it");
    else
        draw_footer(e, "LEFT / RIGHT FLIPPER: move      START: change");
}

/* THE TEST PICTURE UP, full screen, through the correction picked; then the
 * caption, which is never corrected */
static void draw_test(struct state *st)
{
    struct settings_env *e = st->e;
    const struct conf *c = e->c;
    float s = S(e);
    int W = e->g->w, H = e->g->h, k = st->t_item, kind = test_kind(st, k), visual = 1;
    char buf[400], col[260];

    gfx_fill(e->g, 0x000000);
    if (k < TP_NBUILTIN) {
        testpics_draw(k, e->g->px, W * 4, W, H);
    } else if (test_is_back(st, k)) {
        visual = 0;
        gfx_fill(e->g, TH(e, BACKGROUND));
        text_fit(e, st->t_from == S_COLOR ? "BACK TO COLOR CORRECTION" : "BACK TO SETTINGS",
                 56 * s, 28 * s, W - (int)(80 * s), W / 2, H / 2, 0, TH(e, HEADING));
        text_fit(e, "press START", 30 * s, 18 * s, W - (int)(80 * s), W / 2, H / 2 + (int)(60 * s), 0,
                 TH(e, SUBTITLE));
    } else if (st->t_err[0]) {
        visual = 0;
        gfx_fill(e->g, TH(e, BACKGROUND));
        text_fit(e, test_name(st, k), 44 * s, 24 * s, W - (int)(80 * s), W / 2, H / 2 - (int)(30 * s), 0,
                 TH(e, HEADING));
        text_fit(e, st->t_err, 24 * s, 14 * s, W - (int)(80 * s), W / 2, H / 2 + (int)(30 * s), 0,
                 TH(e, SUBTITLE));
    } else if (kind == TF_SOUND) {
        visual = 0;
        gfx_fill(e->g, TH(e, BACKGROUND));
        text_fit(e, "SOUND", 40 * s, 24 * s, W - (int)(80 * s), W / 2, H / 2 - (int)(80 * s), 0,
                 TH(e, SUBTITLE));
        text_fit(e, test_name(st, k), 56 * s, 28 * s, W - (int)(80 * s), W / 2, H / 2, 0, TH(e, HEADING));
        text_fit(e, !e->au ? "the menu has no sound on this machine"
                 : audio_playing(e->au, st->t_voice) ? "playing" : "press START to play it again",
                 28 * s, 18 * s, W - (int)(80 * s), W / 2, H / 2 + (int)(60 * s), 0, TH(e, TITLE));
    } else {
        const struct art_image *im = st->t_img ? st->t_img
                                   : st->t_anim ? art_anim_frame(st->t_anim, st->t_frame) : NULL;
        if (im) gfx_blit(e->g, (W - im->w) / 2, (H - im->h) / 2, im->rgba, im->w, im->h);
    }
    if (visual && st->t_col >= 0) {
        struct colour_lut lut;
        colour_lut_build(&lut, &st->work[st->imgs[st->t_col]]);
        colour_lut_apply(&lut, e->g->px, W, H, W * 4);
    }
    if (!st->t_caption) return;

    if (!visual) {
        col[0] = 0;                            /* nothing on this one is colored */
    } else if (st->t_col < 0) {
        snprintf(col, sizeof col, "%s", c->ncolour > 0 ? "Color: not corrected" : "Color: as the file has it");
    } else {
        int img = st->imgs[st->t_col];
        snprintf(col, sizeof col, "Color: %s, %s", c->img[img].title,
                 image_dirty(st, img) ? "as changed, not saved"
                 : st->has_saved[img] ? "as set on this machine" : "as built");
    }
    {
        int bh = (int)(96 * s), y = H - bh, line = (int)(2 * s) > 0 ? (int)(2 * s) : 1;
        const char *hint = k < TP_NBUILTIN ? testpics_hint(k) : "";
        const char *keys;
        gfx_rect(e->g, 0, y, W, bh, 0x101114);
        gfx_rect(e->g, 0, y, W, line, TH(e, FRAME_HL));
        snprintf(buf, sizeof buf, "%d / %d   %s", k + 1, test_count(st), test_name(st, k));
        text_fit(e, buf, 26 * s, 16 * s, W / 2 - (int)(40 * s), (int)(30 * s), y + (int)(38 * s), -1,
                 0xF0F0F0);
        text_fit(e, col, 22 * s, 14 * s, W / 2 - (int)(40 * s), W - (int)(30 * s), y + (int)(38 * s), 1,
                 0xF0C040);
        if (test_is_back(st, k)) keys = "LEFT / RIGHT FLIPPER: previous / next      START: back";
        else if (kind == TF_SOUND) keys = "LEFT / RIGHT FLIPPER: previous / next      START: play again";
        else if (c->ncolour > 0) keys = "LEFT / RIGHT FLIPPER: previous / next      START: another game's colors";
        else keys = "LEFT / RIGHT FLIPPER: previous / next";
        snprintf(buf, sizeof buf, "%s%s%s", hint, *hint ? "      " : "", keys);
        text_fit(e, buf, 20 * s, 12 * s, W - (int)(60 * s), W / 2, y + (int)(78 * s), 0, 0xB8BCC4);
    }
}

/* THE NEXT ANIMATION FRAME alone: the frame's rectangle, corrected, and the
 * caption's band put back over it - a whole-screen pass per frame is a
 * million pixels through the LUT and a whole-screen upload */
static void draw_test_frame(struct state *st)
{
    struct settings_env *e = st->e;
    int W = e->g->w, H = e->g->h, x, y, bottom;
    const struct art_image *im;
    if (!st->t_anim || st->t_err[0]) return;
    im = art_anim_frame(st->t_anim, st->t_frame);
    if (!im) return;
    x = (W - im->w) / 2;
    y = (H - im->h) / 2;
    gfx_blit(e->g, x, y, im->rgba, im->w, im->h);
    if (st->t_col >= 0) {
        struct colour_lut lut;
        colour_lut_build(&lut, &st->work[st->imgs[st->t_col]]);
        colour_lut_apply(&lut, e->g->px + ((size_t)y * (size_t)W + (size_t)x) * 4, im->w, im->h, W * 4);
    }
    bottom = y + im->h;
    if (st->t_caption && bottom > H - (int)(96 * S(e))) draw_test(st);   /* under the caption: all of it */
}

static void draw(struct state *st)
{
    if (st->screen == S_LIST) draw_list(st);
    else if (st->screen == S_COLOR) draw_colour(st);
    else if (st->screen == S_TEST) draw_test(st);
}

/* ----------------------------------------------------------------- input */

static void click(struct state *st)
{
    struct settings_env *e = st->e;
    if (!e->au || !e->move) return;
    if (!audio_playing_clip(e->au, st->move_voice, e->move))
        st->move_voice = audio_play(e->au, e->move, 0);
}

/* START / ACTION / Select on the highlighted row */
static void activate(struct state *st)
{
    const struct conf *c = st->e->c;
    if (st->screen == S_LIST) {
        int it[3], n = list_items(st, it), i = it[st->list_sel < n ? st->list_sel : n - 1];
        if (i == L_COLOR) {
            st->screen = S_COLOR;
            colour_open(st);
        } else if (i == L_TEST) {
            test_open(st, S_LIST, sel_now_ms());
        } else {
            sel_say("settings: back to the games");
            st->screen = S_DONE;
        }
        return;
    }
    if (st->screen == S_TEST) {
        if (test_is_back(st, st->t_item)) {
            test_close(st);
        } else if (test_kind(st, st->t_item) == TF_SOUND) {
            test_play(st);
        } else if (c->ncolour > 0) {
            /* none -> each adjustable game in turn -> none */
            st->t_col = st->t_col + 1 >= st->nimg ? -1 : st->t_col + 1;
            sel_say("test: color %s", st->t_col < 0 ? "not corrected"
                                                    : c->img[st->imgs[st->t_col]].title);
        }
        return;
    }
    switch (st->rows[st->sel].kind) {
    case R_SAVE: {
        int img = st->imgs[st->cur];
        if (save_image(st, img, &st->work[img]) == 0)
            snprintf(st->status, sizeof st->status, "Saved. %s starts with these colors next time.",
                     c->img[img].title);
        else
            snprintf(st->status, sizeof st->status, "Could not save: %s", strerror(errno));
        break;
    }
    case R_SAVE_ALL: {
        struct colour v = st->work[st->imgs[st->cur]];
        int k, bad = 0;
        for (k = 0; k < st->nimg; k++)
            if (save_image(st, st->imgs[k], &v) < 0) bad++;
        if (bad)
            snprintf(st->status, sizeof st->status, "Could not save %d of %d games", bad, st->nimg);
        else
            snprintf(st->status, sizeof st->status, "Saved for all %d games. They start with these colors next time.",
                     st->nimg);
        break;
    }
    case R_TEST:
        test_open(st, S_COLOR, sel_now_ms());
        break;
    case R_LEAVE:
        if (any_dirty(st)) sel_say("settings: left color correction, unsaved changes dropped");
        else sel_say("settings: left color correction");
        st->screen = S_LIST;
        break;
    default:
        st->editing = 1;
        st->status[0] = 0;
        if (st->rows[st->sel].kind == R_PRESET) {
            int img = st->imgs[st->cur], k = preset_of(st, &st->work[img], img);
            st->preset_k = k < 0 ? 0 : k;
        }
        break;
    }
}

static void key(struct state *st, int ev, long long now)
{
    int dir = (ev == EV_LEFT || ev == EV_MINUS) ? -1 : (ev == EV_RIGHT || ev == EV_PLUS) ? 1 : 0;
    int go = ev == EV_START || ev == EV_ACTION || ev == EV_SELECT;
    if (st->screen == S_LIST) {
        int it[3], n = list_items(st, it);
        if (dir) { st->list_sel = (st->list_sel + n + dir) % n; click(st); }
        else if (go) activate(st);
        return;
    }
    if (st->screen == S_TEST) {
        /* any key brings the caption back; the one that does still counts */
        st->t_caption = 1;
        st->t_caption_until = now + TEST_CAPTION_MS;
        if (dir) {
            int n = test_count(st);
            st->t_item = (st->t_item + n + dir) % n;
            click(st);
            test_load(st, now);
        } else if (go) {
            activate(st);
        }
        return;
    }
    if (st->editing) {
        if (dir) {
            if (step_row(st, dir)) click(st);
            st->hold_ev = ev;
            st->next_rep = now + REPEAT_AFTER_MS;
        } else if (go) {
            int img = st->imgs[st->cur];
            char vals[200];
            st->editing = 0;
            st->hold_ev = 0;
            colour_format(&st->work[img], vals, sizeof vals);
            sel_log("color: image %d now %s", img, vals);
        }
        return;
    }
    if (dir) {
        st->sel = (st->sel + st->nrows + dir) % st->nrows;
        st->status[0] = 0;
        click(st);
    } else if (go) {
        activate(st);
    }
}

/* PAD_SETTINGS_IDLE_MS shortens the idle exit, FOR THE TESTS: two minutes is
 * the right wait on a machine and far too long for a test to sit through */
static long long idle_ms(void)
{
    const char *forced = getenv("PAD_SETTINGS_IDLE_MS");
    if (forced && *forced) {
        long ms = strtol(forced, NULL, 10);
        if (ms > 0) return (long long)ms;
    }
    return SETTINGS_IDLE_MS;
}

void settings_run(struct settings_env *e)
{
    struct state st;
    long long last, idle = idle_ms();
    int ev;
    memset(&st, 0, sizeof st);
    st.e = e;
    st.screen = S_LIST;
    st.move_voice = -1;
    st.t_voice = -1;
    sel_say("settings: open");
    draw(&st);
    last = sel_now_ms();
    while (!*e->stop && st.screen != S_DONE) {
        long long now = sel_now_ms();
        int dirty = 0;
        while ((ev = input_poll(e->in, now)) != EV_NONE) {
            if (ev >= EV_RAW_BASE) continue;
            sel_say("key: %s", input_event_name(ev));
            if (ev == EV_BACK) continue;        /* ignored, as in the menu */
            key(&st, ev, now);
            last = now;
            dirty = 1;
            if (st.screen == S_DONE) break;
        }
        if (st.screen == S_DONE) break;
        /* A HELD FLIPPER REPEATS while a value is being changed: the gamma of
         * one channel is 40 presses from end to end */
        if (st.editing && st.hold_ev) {
            if (!input_held(e->in, st.hold_ev)) {
                st.hold_ev = 0;
            } else if (now >= st.next_rep) {
                int dir = (st.hold_ev == EV_LEFT || st.hold_ev == EV_MINUS) ? -1 : 1;
                if (step_row(&st, dir)) { click(&st); dirty = 1; }
                st.next_rep = now - st.next_rep > REPEAT_EVERY_MS ? now + REPEAT_EVERY_MS
                                                                   : st.next_rep + REPEAT_EVERY_MS;
                last = now;
            }
        }
        if (st.screen == S_TEST && !dirty) {
            int tick = test_tick(&st, now);
            if (tick == 1) draw_test_frame(&st);
            else if (tick) dirty = 1;
        }
        /* the test pictures are looked at, not pressed: a longer wait there
         * (unless the tests shortened every wait) */
        long long wait = st.screen == S_TEST && idle == SETTINGS_IDLE_MS ? TEST_IDLE_MS : idle;
        if (!e->testcard && now - last > wait) {
            sel_say("settings: nothing pressed for %lld s: back to the games%s", wait / 1000,
                    st.colour_ready && any_dirty(&st) ? ", unsaved changes dropped" : "");
            break;
        }
        audio_pump(e->au, now);
        if (dirty) draw(&st);
        e->present(e->ctx);
    }
    /* the test sounds outlive their voices by a fade: let it end first */
    test_unload(&st);
    {
        int k;
        long long until = sel_now_ms() + 200;
        while (e->au && sel_now_ms() < until) {
            int busy = 0;
            for (k = 0; k < CONF_MAX_TESTS && !busy; k++)
                if (st.t_clip[k]) busy = 1;
            if (!busy) break;
            audio_pump(e->au, sel_now_ms());
        }
        for (k = 0; k < CONF_MAX_TESTS; k++)
            if (st.t_clip[k]) audio_clip_free(st.t_clip[k]);
    }
    sel_say("settings: closed");
}

int settings_snapshot(struct settings_env *e, const char *screen, int row, int editing,
                      char *why, int whylen)
{
    struct state st;
    memset(&st, 0, sizeof st);
    st.e = e;
    st.move_voice = -1;
    if (!strcmp(screen, "settings")) {
        st.screen = S_LIST;
        int it[3], n = list_items(&st, it);
        st.list_sel = row >= 0 && row < n ? row : 0;
    } else if (!strcmp(screen, "test")) {
        int k;
        st.t_voice = -1;
        test_open(&st, S_LIST, 0);
        st.t_caption_until = 0;                /* a snapshot: the caption stays */
        if (row >= 0 && row < test_count(&st) && row != st.t_item) {
            st.t_item = row;
            test_load(&st, 0);
        }
        st.t_caption = !editing;
        draw(&st);
        test_unload(&st);
        for (k = 0; k < CONF_MAX_TESTS; k++)
            if (st.t_clip[k]) audio_clip_free(st.t_clip[k]);
        return 0;
    } else if (!strcmp(screen, "color")) {
        if (e->c->ncolour < 1) {
            snprintf(why, (size_t)whylen, "--screen color: this conf has no color_profile= line");
            return -1;
        }
        st.screen = S_COLOR;
        colour_open(&st);
        st.sel = row >= 0 && row < st.nrows ? row : 0;
        st.editing = editing && st.rows[st.sel].kind < R_SAVE;
    } else {
        snprintf(why, (size_t)whylen, "--screen %s: not settings, color or test", screen);
        return -1;
    }
    draw(&st);
    return 0;
}
