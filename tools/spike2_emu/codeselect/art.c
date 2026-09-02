/* art.c - see art.h.
 *
 * stb_image v2.30 (third_party/) compiled here, PNG + GIF only, memory input
 * only (the files are read whole first; a GIF is decoded ONE FRAME PER CALL
 * through stb's own per-frame entry stbi__gif_load_next, the loop that
 * stbi__load_gif_main runs in one go - so a 30-frame animation costs one
 * frame's decode per menu loop iteration instead of stalling the picture).
 * Every frame is box-downscaled into the art panel as soon as it is decoded
 * and the full-size copy dropped (only the two previous full-size frames are
 * kept, for GIF disposal mode 3).
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "art.h"

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_GIF
#define STBI_NO_STDIO
#define STBI_NO_LINEAR
#define STBI_NO_HDR
/* with JPEG compiled out two of stb's overflow helpers go unused */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "third_party/stb_image.h"
#pragma GCC diagnostic pop

#define FILE_CAP (32 * 1024 * 1024)
#define DELAY_DEFAULT 100
#define DELAY_MIN 20
#define DELAY_MAX 10000

static unsigned char *read_file(const char *path, int *len, char *err, int errlen)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf;
    long n;
    if (!f) { snprintf(err, errlen, "%s: %s", path, strerror(errno)); return NULL; }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0 || n > FILE_CAP) {
        snprintf(err, errlen, "%s: %ld bytes (cap %d)", path, n, FILE_CAP);
        fclose(f);
        return NULL;
    }
    buf = malloc((size_t)n);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        snprintf(err, errlen, "%s: short read", path);
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    *len = (int)n;
    return buf;
}

/* the size a sw x sh picture takes inside max_w x max_h: aspect kept, never
 * upscaled (the tools pre-scale to the panel) */
static void fit_size(int sw, int sh, int max_w, int max_h, int *dw, int *dh)
{
    float sx, sy, s;
    if (max_w < 1) max_w = 1;
    if (max_h < 1) max_h = 1;
    if (sw <= max_w && sh <= max_h) { *dw = sw; *dh = sh; return; }
    sx = (float)max_w / (float)sw;
    sy = (float)max_h / (float)sh;
    s = sx < sy ? sx : sy;
    *dw = (int)((float)sw * s + 0.5f);
    *dh = (int)((float)sh * s + 0.5f);
    if (*dw < 1) *dw = 1;
    if (*dh < 1) *dh = 1;
    if (*dw > max_w) *dw = max_w;
    if (*dh > max_h) *dh = max_h;
}

/* box filter (area average, alpha-weighted colour) from sw x sh into dw x dh;
 * a 1:1 size is a memcpy */
static unsigned char *resample(const unsigned char *src, int sw, int sh, int dw, int dh)
{
    unsigned char *dst = malloc((size_t)dw * dh * 4);
    int x, y;
    if (!dst) return NULL;
    if (dw == sw && dh == sh) {
        memcpy(dst, src, (size_t)dw * dh * 4);
        return dst;
    }
    for (y = 0; y < dh; y++) {
        int y0 = (int)((long long)y * sh / dh), y1 = (int)((long long)(y + 1) * sh / dh);
        if (y1 <= y0) y1 = y0 + 1;
        if (y1 > sh) y1 = sh;
        for (x = 0; x < dw; x++) {
            int x0 = (int)((long long)x * sw / dw), x1 = (int)((long long)(x + 1) * sw / dw);
            unsigned long r = 0, g = 0, b = 0, a = 0, n = 0;
            int xx, yy;
            unsigned char *d = dst + ((size_t)y * dw + x) * 4;
            if (x1 <= x0) x1 = x0 + 1;
            if (x1 > sw) x1 = sw;
            for (yy = y0; yy < y1; yy++) {
                const unsigned char *s = src + ((size_t)yy * sw + x0) * 4;
                for (xx = x0; xx < x1; xx++, s += 4) {
                    r += (unsigned long)s[0] * s[3];
                    g += (unsigned long)s[1] * s[3];
                    b += (unsigned long)s[2] * s[3];
                    a += s[3];
                    n++;
                }
            }
            if (a) {
                d[0] = (unsigned char)(r / a);
                d[1] = (unsigned char)(g / a);
                d[2] = (unsigned char)(b / a);
            } else {
                d[0] = d[1] = d[2] = 0;
            }
            d[3] = (unsigned char)(n ? a / n : 0);
        }
    }
    return dst;
}

static struct art_image *make_image(const unsigned char *rgba, int sw, int sh, int max_w, int max_h)
{
    struct art_image *im = calloc(1, sizeof *im);
    if (!im) return NULL;
    fit_size(sw, sh, max_w, max_h, &im->w, &im->h);
    im->rgba = resample(rgba, sw, sh, im->w, im->h);
    if (!im->rgba) { free(im); return NULL; }
    return im;
}

/* ------------------------------------------------------------------- PNG */

struct art_image *art_load_png(const char *path, int max_w, int max_h, char *err, int errlen)
{
    int len = 0, w = 0, h = 0, comp = 0;
    unsigned char *buf = read_file(path, &len, err, errlen);
    unsigned char *px;
    struct art_image *im;
    if (!buf) return NULL;
    px = stbi_load_from_memory(buf, len, &w, &h, &comp, 4);
    free(buf);
    if (!px) {
        snprintf(err, errlen, "%s: %s", path, stbi_failure_reason());
        return NULL;
    }
    im = make_image(px, w, h, max_w, max_h);
    stbi_image_free(px);
    if (!im) snprintf(err, errlen, "%s: out of memory", path);
    return im;
}

void art_image_free(struct art_image *im)
{
    if (!im) return;
    free(im->rgba);
    free(im);
}

/* ------------------------------------------------------------------- GIF */

struct gifdec {
    stbi__context s;
    stbi__gif g;
    unsigned char *buf;
    int len;
    unsigned char *prev, *prevprev;   /* the last two composited frames, full size */
    int max_w, max_h, max_frames;
};

static void gifdec_free(struct gifdec *d)
{
    if (!d) return;
    STBI_FREE(d->g.out);
    STBI_FREE(d->g.history);
    STBI_FREE(d->g.background);
    free(d->prev);
    free(d->prevprev);
    free(d->buf);
    free(d);
}

struct art_anim *art_anim_open(const char *path, int max_w, int max_h, int max_frames,
                               char *err, int errlen)
{
    struct art_anim *a;
    struct gifdec *d = calloc(1, sizeof *d);
    if (!d) { snprintf(err, errlen, "%s: out of memory", path); return NULL; }
    d->buf = read_file(path, &d->len, err, errlen);
    if (!d->buf) { free(d); return NULL; }
    stbi__start_mem(&d->s, d->buf, d->len);
    if (!stbi__gif_test(&d->s)) {
        snprintf(err, errlen, "%s: not a GIF", path);
        gifdec_free(d);
        return NULL;
    }
    d->max_w = max_w;
    d->max_h = max_h;
    d->max_frames = max_frames > 0 ? max_frames : 30;
    a = calloc(1, sizeof *a);
    if (!a) { gifdec_free(d); snprintf(err, errlen, "%s: out of memory", path); return NULL; }
    a->dec = d;
    return a;
}

static void anim_finish(struct art_anim *a, const char *why)
{
    if (why && !a->err[0]) snprintf(a->err, sizeof a->err, "%s", why);
    gifdec_free((struct gifdec *)a->dec);
    a->dec = NULL;
    a->done = 1;
}

int art_anim_step(struct art_anim *a)
{
    struct gifdec *d;
    stbi_uc *u;
    int comp = 0, stride, delay;
    struct art_image *im, *fr;
    int *dl;

    if (!a || a->done) return 0;
    d = (struct gifdec *)a->dec;
    u = stbi__gif_load_next(&d->s, &d->g, &comp, 4, d->prevprev);
    if (u == (stbi_uc *)&d->s) u = NULL;                 /* end-of-animation marker */
    if (!u) {
        anim_finish(a, a->n == 0 ? stbi_failure_reason() : NULL);
        return 0;
    }
    stride = d->g.w * d->g.h * 4;
    if (d->g.w <= 0 || d->g.h <= 0 || d->g.w > 4096 || d->g.h > 4096) {
        anim_finish(a, "frame size out of range");
        return 0;
    }
    /* keep this frame and the one before it full-size for disposal mode 3 */
    {
        unsigned char *t = d->prevprev;
        d->prevprev = d->prev;
        d->prev = t ? t : malloc((size_t)stride);
        if (d->prev) memcpy(d->prev, u, (size_t)stride);
    }
    im = make_image(u, d->g.w, d->g.h, d->max_w, d->max_h);
    if (!im) { anim_finish(a, "out of memory"); return 0; }
    if (a->n == 0) { a->w = im->w; a->h = im->h; }
    else if (im->w != a->w || im->h != a->h) {   /* cannot happen: one GIF, one size */
        art_image_free(im);
        anim_finish(a, "frame size changed");
        return 0;
    }
    fr = realloc(a->fr, (size_t)(a->n + 1) * sizeof *fr);
    dl = realloc(a->delay_ms, (size_t)(a->n + 1) * sizeof *dl);
    if (!fr || !dl) {
        if (fr) a->fr = fr;
        if (dl) a->delay_ms = dl;
        art_image_free(im);
        anim_finish(a, "out of memory");
        return 0;
    }
    a->fr = fr;
    a->delay_ms = dl;
    a->fr[a->n] = *im;
    free(im);                                           /* the struct only; rgba moved */
    delay = d->g.delay > 0 ? d->g.delay : DELAY_DEFAULT;
    if (delay < DELAY_MIN) delay = DELAY_MIN;
    if (delay > DELAY_MAX) delay = DELAY_MAX;
    a->delay_ms[a->n] = delay;
    a->n++;
    if (a->n >= d->max_frames) anim_finish(a, NULL);
    return 1;
}

void art_anim_free(struct art_anim *a)
{
    int i;
    if (!a) return;
    for (i = 0; i < a->n; i++) free(a->fr[i].rgba);
    free(a->fr);
    free(a->delay_ms);
    gifdec_free((struct gifdec *)a->dec);
    free(a);
}
