/* art.c - see art.h.
 *
 * stb_image v2.30 (third_party/) compiled here, PNG + GIF only, memory input
 * only (the files are read whole first; a GIF is decoded ONE FRAME PER CALL
 * through stb's own per-frame entry stbi__gif_load_next, the loop that
 * stbi__load_gif_main runs in one go).  Frames are decoded ON DEMAND as the
 * menu ticks through them - the frame shown and frame 0 are the only ones
 * in memory, box-downscaled into the art panel, with the two previous
 * full-size composites kept for GIF disposal mode 3 - so a 150-frame loop
 * (5 s at 30 fps) costs what a 4-frame one does, and the menu is up after
 * one frame's decode.  The frame count and the delays come from a walk of
 * the block stream at open, which reads no pixels.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
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
    int max_w, max_h;
};

static void gifdec_drop_state(struct gifdec *d)
{
    STBI_FREE(d->g.out);
    STBI_FREE(d->g.history);
    STBI_FREE(d->g.background);
    memset(&d->g, 0, sizeof d->g);
    free(d->prev);
    free(d->prevprev);
    d->prev = d->prevprev = NULL;
}

/* back to the first frame: stb's per-file state and the two composites it
 * disposes against are as they were before the first decode */
static void gifdec_rewind(struct gifdec *d)
{
    gifdec_drop_state(d);
    stbi__start_mem(&d->s, d->buf, d->len);
}

static void gifdec_free(struct gifdec *d)
{
    if (!d) return;
    gifdec_drop_state(d);
    free(d->buf);
    free(d);
}

static int clamp_delay(int ms)
{
    if (ms <= 0) ms = DELAY_DEFAULT;
    if (ms < DELAY_MIN) ms = DELAY_MIN;
    if (ms > DELAY_MAX) ms = DELAY_MAX;
    return ms;
}

/* past the data sub-blocks that start at pos: the position after their 0
 * terminator (or the end of the file) */
static int gif_skip_subblocks(const unsigned char *d, int len, int pos)
{
    while (pos < len) {
        int n = d[pos++];
        if (n == 0) return pos;
        pos += n;
    }
    return len;
}

/* Count the frames and read their delays by walking the block stream - no
 * LZW, so it is one pass over the bytes, not a decode (the same walk
 * selectmedia.py's gif_info and mkmulticard.py's gif_info make).  Stops at
 * the trailer, at max_frames, or at a block it does not know (what was
 * counted is what plays).  Returns the count; *delays gets a malloc'd array
 * of that many (NULL for none). */
static int gif_walk(const unsigned char *d, int len, int max_frames, int **delays)
{
    int pos = 13, n = 0, cap = 0, pending = 0, *dl = NULL;
    *delays = NULL;
    if (len < 13) return 0;
    if (d[10] & 0x80) pos += 3 * (2 << (d[10] & 7));          /* global colour table */
    while (pos < len) {
        unsigned char b = d[pos];
        if (b == 0x3B) break;                                    /* trailer */
        if (b == 0x21) {                                         /* extension */
            if (pos + 1 >= len) break;
            if (d[pos + 1] == 0xF9 && pos + 7 < len)              /* graphic control: delay in cs */
                pending = (d[pos + 4] | (d[pos + 5] << 8)) * 10;
            pos = gif_skip_subblocks(d, len, pos + 2);
        } else if (b == 0x2C) {                                  /* image descriptor */
            int lp;
            if (pos + 10 > len) break;
            lp = d[pos + 9];
            pos += 10;
            if (lp & 0x80) pos += 3 * (2 << (lp & 7));            /* local colour table */
            pos += 1;                                            /* LZW minimum code size */
            pos = gif_skip_subblocks(d, len, pos);
            if (n == max_frames) break;
            if (n == cap) {
                int want = cap ? cap * 2 : 16;
                int *t = realloc(dl, (size_t)want * sizeof *dl);
                if (!t) break;
                dl = t;
                cap = want;
            }
            dl[n++] = clamp_delay(pending);
            pending = 0;
        } else {
            break;
        }
    }
    *delays = dl;
    return n;
}

static long long now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000LL + ts.tv_nsec / 1000;
}

/* Decode the file's next frame into a->frame: 1 = done (a->cur advanced),
 * 0 = no more (a clean end of the file, or an error - a->err says which). */
static int anim_decode_next(struct art_anim *a)
{
    struct gifdec *d = (struct gifdec *)a->dec;
    stbi_uc *u;
    int comp = 0, stride;
    struct art_image *im;
    long long t0 = now_us();

    u = stbi__gif_load_next(&d->s, &d->g, &comp, 4, d->prevprev);
    if (u == (stbi_uc *)&d->s) {                          /* end-of-animation marker */
        snprintf(a->err, sizeof a->err, "the file ends after %d frame(s)", a->cur + 1);
        return 0;
    }
    if (!u) {
        snprintf(a->err, sizeof a->err, "%s", stbi_failure_reason());
        return 0;
    }
    stride = d->g.w * d->g.h * 4;
    if (d->g.w <= 0 || d->g.h <= 0 || d->g.w > 4096 || d->g.h > 4096) {
        snprintf(a->err, sizeof a->err, "frame size out of range");
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
    if (!im) { snprintf(a->err, sizeof a->err, "out of memory"); return 0; }
    if (!a->first.rgba) { a->w = im->w; a->h = im->h; }  /* the very first decode sets the size */
    else if (im->w != a->w || im->h != a->h) {   /* cannot happen: one GIF, one size */
        art_image_free(im);
        snprintf(a->err, sizeof a->err, "frame size changed");
        return 0;
    }
    free(a->frame.rgba);
    a->frame = *im;
    free(im);                                           /* the struct only; rgba moved */
    a->cur++;
    a->decodes++;
    a->decode_us += now_us() - t0;
    return 1;
}

struct art_anim *art_anim_open(const char *path, int max_w, int max_h, int max_frames,
                               char *err, int errlen)
{
    struct art_anim *a;
    size_t bytes;
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
    a = calloc(1, sizeof *a);
    if (!a) { gifdec_free(d); snprintf(err, errlen, "%s: out of memory", path); return NULL; }
    a->dec = d;
    a->cur = -1;
    a->n = gif_walk(d->buf, d->len, max_frames > 0 ? max_frames : 150, &a->delay_ms);
    if (a->n <= 0) {
        snprintf(err, errlen, "%s: no frames", path);
        art_anim_free(a);
        return NULL;
    }
    /* a constant-rate clip (ffmpeg's GIFs: every delay within 2x of every
     * other, the centisecond rounding alternating 30/40 for a 30 fps
     * source) is ticked at its mean period, so the rate is the source's
     * exactly; anything else keeps its per-frame delays */
    if (a->n >= 2) {
        int k, lo = a->delay_ms[0], hi = a->delay_ms[0];
        long sum = 0;
        for (k = 0; k < a->n; k++) {
            if (a->delay_ms[k] < lo) lo = a->delay_ms[k];
            if (a->delay_ms[k] > hi) hi = a->delay_ms[k];
            sum += a->delay_ms[k];
        }
        if (hi <= 2 * lo) a->period_ms = (float)sum / (float)a->n;
    }
    if (!anim_decode_next(a)) {
        snprintf(err, errlen, "%s: frame 0: %s", path, a->err[0] ? a->err : "cannot decode");
        art_anim_free(a);
        return NULL;
    }
    /* frame 0 is kept whole: the still of a card that is not highlighted */
    bytes = (size_t)a->frame.w * (size_t)a->frame.h * 4;
    a->first.w = a->frame.w;
    a->first.h = a->frame.h;
    a->first.rgba = malloc(bytes);
    if (!a->first.rgba) {
        snprintf(err, errlen, "%s: out of memory", path);
        art_anim_free(a);
        return NULL;
    }
    memcpy(a->first.rgba, a->frame.rgba, bytes);
    return a;
}

const struct art_image *art_anim_still(const struct art_anim *a)
{
    return a && a->first.rgba ? &a->first : NULL;
}

const struct art_image *art_anim_frame(struct art_anim *a, int k)
{
    if (!a || a->n <= 0) return NULL;
    k %= a->n;
    if (k < 0) k += a->n;
    if (k == a->cur) return &a->frame;
    /* an earlier frame (the loop wrapping, usually) means starting the file
     * over: one decode per tick either way, since frame 0 is the first thing
     * the fresh decoder produces */
    if (k < a->cur) {
        gifdec_rewind((struct gifdec *)a->dec);
        a->cur = -1;
    }
    while (a->cur < k) {
        if (!anim_decode_next(a)) {
            /* fewer frames than the walk counted (or a bad one): the loop
             * is what did decode, and the caller's next `% n` wraps there */
            if (a->cur < 0) {
                a->n = 1;
                return &a->first;
            }
            a->n = a->cur + 1;
            return &a->frame;
        }
    }
    return &a->frame;
}

void art_anim_free(struct art_anim *a)
{
    if (!a) return;
    free(a->frame.rgba);
    free(a->first.rgba);
    free(a->delay_ms);
    gifdec_free((struct gifdec *)a->dec);
    free(a);
}
