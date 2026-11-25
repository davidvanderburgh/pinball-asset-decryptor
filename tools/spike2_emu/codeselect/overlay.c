/* overlay.c - a scene over a test clip (overlay.h). */
#include <stddef.h>
#include "overlay.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "log.h"

struct ovl {
    unsigned char *buf;
    long len;
    int cw, ch;
    float fps;
    int n, np;
    const unsigned char *frame;     /* u32 picture[n] */
    const unsigned char *pict;      /* { x, y, off, size }[np] */
    int cur;                        /* the picture last handed out, or -1 */
    /* every picture decoded once, at open: the table (2026-11-25) took ~100 ms a
     * whole-screen PNG on the Cortex-A9, each time the scene changed picture */
    struct art_image *img;          /* [np] */
    char err[200];
};

static uint32_t u32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

struct ovl *ovl_open(const char *path, int max_w, int max_h, char *err, int errlen)
{
    struct ovl *o;
    FILE *f = fopen(path, "rb");
    long len;
    int i;
    if (!f) { snprintf(err, (size_t)errlen, "the overlay cannot be read"); return NULL; }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len < OVL_HEADER || len > (256L << 20)) {
        fclose(f);
        snprintf(err, (size_t)errlen, "the overlay is %ld bytes: not one", len);
        return NULL;
    }
    o = calloc(1, sizeof *o);
    if (!o || !(o->buf = malloc((size_t)len)) || fread(o->buf, 1, (size_t)len, f) != (size_t)len) {
        fclose(f);
        if (o) free(o->buf);
        free(o);
        snprintf(err, (size_t)errlen, "the overlay cannot be read");
        return NULL;
    }
    fclose(f);
    o->len = len;
    o->cur = -1;
    if (memcmp(o->buf, OVL_MAGIC, 8)) {
        snprintf(err, (size_t)errlen, "not an overlay (no %s)", OVL_MAGIC);
        goto bad;
    }
    o->cw = (int)u32(o->buf + 8);
    o->ch = (int)u32(o->buf + 12);
    o->fps = u32(o->buf + 16) / 1000.0f;
    o->n = (int)u32(o->buf + 20);
    o->np = (int)u32(o->buf + 24);
    if (o->cw <= 0 || o->ch <= 0 || o->cw > max_w || o->ch > max_h) {
        snprintf(err, (size_t)errlen, "the overlay is %dx%d, the screen %dx%d", o->cw, o->ch, max_w, max_h);
        goto bad;
    }
    if (o->fps <= 0.0f || o->n <= 0 || o->n > OVL_MAX_FRAMES || o->np < 0 || o->np > OVL_MAX_PICTURES
        || OVL_HEADER + 4L * o->n + 16L * o->np > len) {
        snprintf(err, (size_t)errlen, "the overlay's header is broken");
        goto bad;
    }
    o->frame = o->buf + OVL_HEADER;
    o->pict = o->frame + 4L * o->n;
    for (i = 0; i < o->n; i++) {
        uint32_t p = u32(o->frame + 4L * i);
        if (p != OVL_NONE && p >= (uint32_t)o->np) {
            snprintf(err, (size_t)errlen, "the overlay's frame %d names picture %u of %d", i, (unsigned)p, o->np);
            goto bad;
        }
    }
    for (i = 0; i < o->np; i++) {
        const unsigned char *e = o->pict + 16L * i;
        uint32_t off = u32(e + 8), size = u32(e + 12);
        if (off > (uint32_t)len || size > (uint32_t)len - off) {
            snprintf(err, (size_t)errlen, "the overlay's picture %d is past the end", i);
            goto bad;
        }
    }
    if (o->np && !(o->img = calloc((size_t)o->np, sizeof *o->img))) {
        snprintf(err, (size_t)errlen, "out of memory");
        goto bad;
    }
    {
        long long t0 = sel_now_ms();
        for (i = 0; i < o->np; i++) {
            const unsigned char *e = o->pict + 16L * i;
            char why[200] = "";
            int w = 0, h = 0;
            unsigned char *px = art_jpeg_decode(o->buf + u32(e + 8), (int)u32(e + 12), &w, &h, why, sizeof why);
            if (!px) {
                snprintf(err, (size_t)errlen, "the overlay's picture %d: %s", i, why);
                goto bad;
            }
            o->img[i].rgba = px;
            o->img[i].w = w;
            o->img[i].h = h;
        }
        sel_log("overlay: %d pictures decoded in %lld ms", o->np, sel_now_ms() - t0);
    }
    return o;
bad:
    if (o->img) for (i = 0; i < o->np; i++) free(o->img[i].rgba);
    free(o->img);
    free(o->buf);
    free(o);
    return NULL;
}

const struct art_image *ovl_at(struct ovl *o, long long ms, int *x, int *y)
{
    long long k = ms < 0 ? 0 : (long long)(ms * o->fps / 1000.0);
    uint32_t p;
    const unsigned char *e;
    if (k >= o->n) k = o->n - 1;
    p = u32(o->frame + 4 * k);
    if (p == OVL_NONE) return NULL;
    e = o->pict + 16L * p;
    o->cur = (int)p;
    *x = (int)(int32_t)u32(e);
    *y = (int)(int32_t)u32(e + 4);
    return &o->img[p];
}

int ovl_frames(const struct ovl *o) { return o->n; }
float ovl_fps(const struct ovl *o) { return o->fps; }
int ovl_pictures(const struct ovl *o) { return o->np; }
void ovl_canvas(const struct ovl *o, int *w, int *h) { *w = o->cw; *h = o->ch; }
const char *ovl_error(const struct ovl *o) { return o->err; }

void ovl_close(struct ovl *o)
{
    int i;
    if (!o) return;
    if (o->img) for (i = 0; i < o->np; i++) free(o->img[i].rgba);
    free(o->img);
    free(o->buf);
    free(o);
}
