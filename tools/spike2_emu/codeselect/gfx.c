/* gfx.c - see gfx.h */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "gfx.h"

#define STB_TRUETYPE_IMPLEMENTATION
#include "third_party/stb_truetype.h"

/* ---------------------------------------------------------------- canvas */

int gfx_init(struct gfx *g, int w, int h)
{
    memset(g, 0, sizeof *g);
    if (w <= 0 || h <= 0) return -1;
    g->w = w;
    g->h = h;
    g->px = calloc((size_t)w * h, 4);
    g->scratch = calloc((size_t)w * h, 4);
    if (!g->px || !g->scratch) { gfx_free(g); return -1; }
    gfx_clean(g);
    return 0;
}

/* grow the dirty union by a rectangle (clipped to the canvas) */
static void mark(struct gfx *g, int x0, int y0, int x1, int y1)
{
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > g->w) x1 = g->w;
    if (y1 > g->h) y1 = g->h;
    if (x1 <= x0 || y1 <= y0) return;
    if (g->dx1 <= g->dx0) {                  /* empty so far */
        g->dx0 = x0; g->dy0 = y0; g->dx1 = x1; g->dy1 = y1;
        return;
    }
    if (x0 < g->dx0) g->dx0 = x0;
    if (y0 < g->dy0) g->dy0 = y0;
    if (x1 > g->dx1) g->dx1 = x1;
    if (y1 > g->dy1) g->dy1 = y1;
}

int gfx_dirty(const struct gfx *g, int *x, int *y, int *w, int *h)
{
    if (g->dx1 <= g->dx0 || g->dy1 <= g->dy0) {
        *x = *y = *w = *h = 0;
        return 0;
    }
    *x = g->dx0;
    *y = g->dy0;
    *w = g->dx1 - g->dx0;
    *h = g->dy1 - g->dy0;
    return 1;
}

void gfx_clean(struct gfx *g)
{
    g->dx0 = g->dy0 = 0;
    g->dx1 = g->dy1 = 0;
}

void gfx_free(struct gfx *g)
{
    free(g->px);
    free(g->scratch);
    g->px = g->scratch = NULL;
}

static inline void put(unsigned char *p, unsigned rgb)
{
    p[0] = (unsigned char)(rgb >> 16);
    p[1] = (unsigned char)(rgb >> 8);
    p[2] = (unsigned char)rgb;
    p[3] = 0xff;
}

static inline void blend(unsigned char *p, unsigned rgb, unsigned a)
{
    unsigned ia = 255 - a;
    p[0] = (unsigned char)((p[0] * ia + ((rgb >> 16) & 0xff) * a) / 255);
    p[1] = (unsigned char)((p[1] * ia + ((rgb >> 8) & 0xff) * a) / 255);
    p[2] = (unsigned char)((p[2] * ia + (rgb & 0xff) * a) / 255);
    p[3] = 0xff;
}

void gfx_fill(struct gfx *g, unsigned rgb)
{
    gfx_rect(g, 0, 0, g->w, g->h, rgb);
}

static void span(struct gfx *g, int y, int x0, int x1, unsigned rgb)
{
    unsigned char *p;
    int x;
    if (y < 0 || y >= g->h) return;
    if (x0 < 0) x0 = 0;
    if (x1 > g->w) x1 = g->w;
    if (x1 <= x0) return;
    mark(g, x0, y, x1, y + 1);
    p = g->px + ((size_t)y * g->w + x0) * 4;
    for (x = x0; x < x1; x++, p += 4) put(p, rgb);
}

void gfx_rect(struct gfx *g, int x, int y, int w, int h, unsigned rgb)
{
    int yy;
    for (yy = y; yy < y + h; yy++) span(g, yy, x, x + w, rgb);
}

void gfx_round_rect(struct gfx *g, int x, int y, int w, int h, int r, unsigned rgb)
{
    int yy;
    if (r > w / 2) r = w / 2;
    if (r > h / 2) r = h / 2;
    for (yy = 0; yy < h; yy++) {
        int inset = 0;
        float dy = 0;
        if (yy < r) dy = (float)(r - yy) - 0.5f;
        else if (yy >= h - r) dy = (float)(yy - (h - r)) + 0.5f;
        if (dy > 0) {
            float fx = (float)r - sqrtf((float)r * r - dy * dy);
            inset = (int)(fx + 0.5f);
        }
        span(g, y + yy, x + inset, x + w - inset, rgb);
    }
}

void gfx_round_frame(struct gfx *g, int x, int y, int w, int h, int r, int t,
                     unsigned frame_rgb, unsigned fill_rgb)
{
    gfx_round_rect(g, x, y, w, h, r, frame_rgb);
    if (w > 2 * t && h > 2 * t)
        gfx_round_rect(g, x + t, y + t, w - 2 * t, h - 2 * t, r > t ? r - t : 0, fill_rgb);
}

void gfx_blit(struct gfx *g, int x, int y, const unsigned char *rgba, int w, int h)
{
    int sx0 = 0, sy0 = 0, sx1 = w, sy1 = h, yy, xx;
    if (!rgba || w <= 0 || h <= 0) return;
    if (x < 0) sx0 = -x;
    if (y < 0) sy0 = -y;
    if (x + sx1 > g->w) sx1 = g->w - x;
    if (y + sy1 > g->h) sy1 = g->h - y;
    if (sx1 <= sx0 || sy1 <= sy0) return;
    mark(g, x + sx0, y + sy0, x + sx1, y + sy1);
    for (yy = sy0; yy < sy1; yy++) {
        const unsigned char *s = rgba + ((size_t)yy * w + sx0) * 4;
        unsigned char *d = g->px + ((size_t)(y + yy) * g->w + x + sx0) * 4;
        for (xx = sx0; xx < sx1; xx++, s += 4, d += 4) {
            unsigned a = s[3];
            if (a == 255) { d[0] = s[0]; d[1] = s[1]; d[2] = s[2]; d[3] = 0xff; }
            else if (a) blend(d, ((unsigned)s[0] << 16) | ((unsigned)s[1] << 8) | s[2], a);
        }
    }
}

/* ------------------------------------------------------------------ font */

struct glyph {
    int cp, px;               /* key; px is the pixel height (integer) */
    int used;
    unsigned char *bmp;       /* w*h coverage */
    int w, h, xoff, yoff;
    float adv;
};

#define GLYPH_CACHE 1024

struct gfx_font {
    unsigned char *data;
    stbtt_fontinfo info;
    int ascent, descent, linegap;   /* unscaled */
    struct glyph cache[GLYPH_CACHE];
    int cached;
};

struct gfx_font *gfx_font_load(const char *path)
{
    FILE *f = fopen(path, "rb");
    struct gfx_font *fo;
    long n;
    if (!f) return NULL;
    fo = calloc(1, sizeof *fo);
    if (!fo) { fclose(f); return NULL; }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0 || n > 32 * 1024 * 1024) { fclose(f); free(fo); return NULL; }
    fo->data = malloc((size_t)n);
    if (!fo->data || fread(fo->data, 1, (size_t)n, f) != (size_t)n) {
        fclose(f); free(fo->data); free(fo); return NULL;
    }
    fclose(f);
    if (!stbtt_InitFont(&fo->info, fo->data, stbtt_GetFontOffsetForIndex(fo->data, 0))) {
        free(fo->data); free(fo); return NULL;
    }
    stbtt_GetFontVMetrics(&fo->info, &fo->ascent, &fo->descent, &fo->linegap);
    return fo;
}

void gfx_font_free(struct gfx_font *f)
{
    int i;
    if (!f) return;
    for (i = 0; i < GLYPH_CACHE; i++) free(f->cache[i].bmp);
    free(f->data);
    free(f);
}

int gfx_font_ascent(struct gfx_font *f, float px)
{
    float s = stbtt_ScaleForPixelHeight(&f->info, px);
    return (int)(f->ascent * s + 0.5f);
}

int gfx_font_descent(struct gfx_font *f, float px)
{
    float s = stbtt_ScaleForPixelHeight(&f->info, px);
    return (int)(-f->descent * s + 0.5f);
}

static struct glyph *glyph_get(struct gfx_font *f, int cp, int px)
{
    unsigned h = ((unsigned)cp * 2654435761u + (unsigned)px * 97u) % GLYPH_CACHE;
    unsigned i;
    struct glyph *g;
    float scale;
    int x0, y0, x1, y1, adv, lsb;

    for (i = 0; i < GLYPH_CACHE; i++) {
        g = &f->cache[(h + i) % GLYPH_CACHE];
        if (!g->used) break;
        if (g->cp == cp && g->px == px) return g;
    }
    if (i == GLYPH_CACHE) {          /* full: evict the home slot */
        g = &f->cache[h];
        free(g->bmp);
        memset(g, 0, sizeof *g);
    }
    scale = stbtt_ScaleForPixelHeight(&f->info, (float)px);
    stbtt_GetCodepointBitmapBox(&f->info, cp, scale, scale, &x0, &y0, &x1, &y1);
    stbtt_GetCodepointHMetrics(&f->info, cp, &adv, &lsb);
    g->used = 1;
    g->cp = cp;
    g->px = px;
    g->w = x1 - x0;
    g->h = y1 - y0;
    g->xoff = x0;
    g->yoff = y0;
    g->adv = adv * scale;
    g->bmp = NULL;
    if (g->w > 0 && g->h > 0) {
        g->bmp = malloc((size_t)g->w * g->h);
        if (g->bmp)
            stbtt_MakeCodepointBitmap(&f->info, g->bmp, g->w, g->h, g->w, scale, scale, cp);
    }
    return g;
}

/* one UTF-8 code point; malformed bytes come back as themselves */
static int utf8_next(const char **ps)
{
    const unsigned char *s = (const unsigned char *)*ps;
    int cp, n;
    if (s[0] < 0x80) { cp = s[0]; n = 1; }
    else if ((s[0] & 0xe0) == 0xc0 && (s[1] & 0xc0) == 0x80) { cp = ((s[0] & 0x1f) << 6) | (s[1] & 0x3f); n = 2; }
    else if ((s[0] & 0xf0) == 0xe0 && (s[1] & 0xc0) == 0x80 && (s[2] & 0xc0) == 0x80) {
        cp = ((s[0] & 0x0f) << 12) | ((s[1] & 0x3f) << 6) | (s[2] & 0x3f); n = 3;
    } else if ((s[0] & 0xf8) == 0xf0 && (s[1] & 0xc0) == 0x80 && (s[2] & 0xc0) == 0x80 && (s[3] & 0xc0) == 0x80) {
        cp = ((s[0] & 0x07) << 18) | ((s[1] & 0x3f) << 12) | ((s[2] & 0x3f) << 6) | (s[3] & 0x3f); n = 4;
    } else { cp = s[0]; n = 1; }
    *ps += n;
    return cp;
}

static float text_advance(struct gfx_font *f, int px, const char *s, int *out_w)
{
    float x = 0, scale = stbtt_ScaleForPixelHeight(&f->info, (float)px);
    int prev = 0, maxx = 0;
    while (*s) {
        int cp = utf8_next(&s);
        struct glyph *g = glyph_get(f, cp, px);
        if (prev) x += stbtt_GetCodepointKernAdvance(&f->info, prev, cp) * scale;
        if (g->w > 0 && (int)(x + g->xoff + g->w) > maxx) maxx = (int)(x + g->xoff + g->w);
        x += g->adv;
        prev = cp;
    }
    if (out_w) *out_w = (int)(x + 0.5f) > maxx ? (int)(x + 0.5f) : maxx;
    return x;
}

int gfx_text_width(struct gfx_font *f, float px, const char *s)
{
    int w = 0;
    if (!f || !s) return 0;
    text_advance(f, (int)(px + 0.5f), s, &w);
    return w;
}

void gfx_text(struct gfx *g, struct gfx_font *f, float pxf, int x, int baseline,
              const char *s, unsigned rgb)
{
    int px = (int)(pxf + 0.5f);
    float pen = (float)x, scale;
    int prev = 0;
    if (!f || !s) return;
    scale = stbtt_ScaleForPixelHeight(&f->info, (float)px);
    while (*s) {
        int cp = utf8_next(&s);
        struct glyph *gl = glyph_get(f, cp, px);
        int gx, gy, yy, xx;
        if (prev) pen += stbtt_GetCodepointKernAdvance(&f->info, prev, cp) * scale;
        gx = (int)(pen + 0.5f) + gl->xoff;
        gy = baseline + gl->yoff;
        if (gl->bmp) {
            mark(g, gx, gy, gx + gl->w, gy + gl->h);
            for (yy = 0; yy < gl->h; yy++) {
                int y = gy + yy;
                const unsigned char *row = gl->bmp + (size_t)yy * gl->w;
                if (y < 0 || y >= g->h) continue;
                for (xx = 0; xx < gl->w; xx++) {
                    int xp = gx + xx;
                    unsigned a = row[xx];
                    if (!a || xp < 0 || xp >= g->w) continue;
                    blend(g->px + ((size_t)y * g->w + xp) * 4, rgb, a);
                }
            }
        }
        pen += gl->adv;
        prev = cp;
    }
}

void gfx_text_center(struct gfx *g, struct gfx_font *f, float px, int cx, int baseline,
                     const char *s, unsigned rgb)
{
    int w = gfx_text_width(f, px, s);
    gfx_text(g, f, px, cx - w / 2, baseline, s, rgb);
}

float gfx_fit_px(struct gfx_font *f, const char *s, int max_w, float px, float min_px)
{
    while (px > min_px && gfx_text_width(f, px, s) > max_w) px -= 2;
    return px < min_px ? min_px : px;
}

int gfx_wrap(struct gfx_font *f, float px, const char *s, int max_w,
             char *lines, int line_len, int max_lines)
{
    int n = 0;
    char cur[512] = "";
    const char *p = s;

    if (!s || !*s || max_lines <= 0) return 0;
    while (*p && n < max_lines) {
        const char *ws;
        char word[256], trial[512];
        int wl;
        while (*p == ' ') p++;
        if (!*p) break;
        ws = p;
        while (*p && *p != ' ') p++;
        wl = (int)(p - ws);
        if (wl > (int)sizeof word - 1) wl = (int)sizeof word - 1;
        memcpy(word, ws, (size_t)wl);
        word[wl] = 0;
        if (*cur) snprintf(trial, sizeof trial, "%s %s", cur, word);
        else snprintf(trial, sizeof trial, "%s", word);
        if (*cur && gfx_text_width(f, px, trial) > max_w) {
            snprintf(lines + (size_t)n * line_len, (size_t)line_len, "%s", cur);
            n++;
            snprintf(cur, sizeof cur, "%s", word);
        } else {
            snprintf(cur, sizeof cur, "%s", trial);
        }
    }
    if (*cur && n < max_lines) {
        snprintf(lines + (size_t)n * line_len, (size_t)line_len, "%s", cur);
        n++;
    }
    return n;
}

/* --------------------------------------------------------------- present */

const unsigned char *gfx_pixels(struct gfx *g, int invert)
{
    size_t n = (size_t)g->w * g->h, i;
    const unsigned *src;
    unsigned *dst;
    if (!invert) return g->px;
    src = (const unsigned *)g->px;
    dst = (unsigned *)g->scratch;
    for (i = 0; i < n; i++) dst[n - 1 - i] = src[i];
    return g->scratch;
}

const unsigned char *gfx_pack(struct gfx *g, int invert, int *x, int *y, int *w, int *h)
{
    int rx, ry, rw, rh, yy, xx;
    if (!gfx_dirty(g, &rx, &ry, &rw, &rh)) {
        *x = *y = *w = *h = 0;
        return NULL;
    }
    if (!invert) {
        unsigned char *d = g->scratch;
        for (yy = 0; yy < rh; yy++, d += (size_t)rw * 4)
            memcpy(d, g->px + ((size_t)(ry + yy) * g->w + rx) * 4, (size_t)rw * 4);
        *x = rx;
        *y = ry;
    } else {
        /* the rect's pixels in reverse order = the same rect of the rotated
         * picture, which sits at the mirrored position */
        unsigned *d = (unsigned *)g->scratch;
        for (yy = 0; yy < rh; yy++) {
            const unsigned *s = (const unsigned *)(g->px + ((size_t)(ry + rh - 1 - yy) * g->w + rx) * 4);
            for (xx = 0; xx < rw; xx++) d[(size_t)yy * rw + xx] = s[rw - 1 - xx];
        }
        *x = g->w - rx - rw;
        *y = g->h - ry - rh;
    }
    *w = rw;
    *h = rh;
    return g->scratch;
}

int gfx_write_ppm(struct gfx *g, const char *path, int invert)
{
    const unsigned char *px = gfx_pixels(g, invert);
    FILE *f = fopen(path, "wb");
    unsigned char *row;
    int y, x;
    if (!f) return -1;
    fprintf(f, "P6\n%d %d\n255\n", g->w, g->h);
    row = malloc((size_t)g->w * 3);
    if (!row) { fclose(f); return -1; }
    for (y = 0; y < g->h; y++) {
        const unsigned char *s = px + (size_t)y * g->w * 4;
        for (x = 0; x < g->w; x++) {
            row[x * 3 + 0] = s[x * 4 + 0];
            row[x * 3 + 1] = s[x * 4 + 1];
            row[x * 3 + 2] = s[x * 4 + 2];
        }
        if (fwrite(row, 3, (size_t)g->w, f) != (size_t)g->w) { free(row); fclose(f); return -1; }
    }
    free(row);
    return fclose(f) == 0 ? 0 : -1;
}
