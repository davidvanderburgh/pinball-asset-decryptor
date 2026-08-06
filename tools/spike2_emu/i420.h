/* i420.h - I420 -> RGBA, BT.601 limited range.
 *
 * This is what the Vivante texture unit does for GL_VIV_I420 on the real
 * machine, done in software here because there is no Vivante. It lived inside
 * padglhost.c until item 6 (the pink/green TV inset) needed to run it OUTSIDE
 * a live emulator, against a clip whose correct output ffmpeg can produce.
 *
 * IT IS A HEADER SO THERE IS EXACTLY ONE COPY. A test that runs a duplicate of
 * the converter proves nothing about the converter that ships; padglhost.c and
 * i420check.c both #include this file and both get the same object code.
 *
 * Integer, 8-bit fixed point; the Y term is a table because it is the only one
 * indexed by every pixel.
 */
#ifndef PAD_I420_H
#define PAD_I420_H

static unsigned char *rgba_buf;
static unsigned long rgba_cap;
static short yclamp[256];
static unsigned char sat[1024];          /* sat[x] clamps x-384 into 0..255 */

static void conv_init(void)
{
    int i;
    if (sat[0] || sat[1023]) return;
    for (i = 0; i < 256; i++) yclamp[i] = (short)((298 * (i - 16) + 128) >> 8);
    for (i = 0; i < 1024; i++) {
        int v = i - 384;
        sat[i] = (unsigned char)(v < 0 ? 0 : (v > 255 ? 255 : v));
    }
}

#define SAT(v) sat[(unsigned)((v) + 384) < 1024u ? (unsigned)((v) + 384) : ((v) < 0 ? 0u : 1023u)]

static const unsigned char *i420_to_rgba(const unsigned char *src, unsigned w, unsigned h)
{
    const unsigned char *Y = src, *U = src + (unsigned long)w * h;
    const unsigned char *V = U + (unsigned long)(w / 2) * (h / 2);
    unsigned long need = (unsigned long)w * h * 4;
    unsigned x, y;
    conv_init();
    if (need > rgba_cap) {
        unsigned char *n = realloc(rgba_buf, need);
        if (!n) return 0;
        rgba_buf = n; rgba_cap = need;
    }
    for (y = 0; y < h; y++) {
        const unsigned char *yp = Y + (unsigned long)y * w;
        const unsigned char *up = U + (unsigned long)(y / 2) * (w / 2);
        const unsigned char *vp = V + (unsigned long)(y / 2) * (w / 2);
        unsigned char *o = rgba_buf + (unsigned long)y * w * 4;
        for (x = 0; x < w; x += 2) {
            int u = up[x / 2] - 128, v = vp[x / 2] - 128;
            int rd = (409 * v + 128) >> 8;
            int gd = -((100 * u + 208 * v + 128) >> 8);
            int bd = (516 * u + 128) >> 8;
            int k;
            for (k = 0; k < 2 && x + (unsigned)k < w; k++) {
                int c = yclamp[yp[x + k]];
                o[0] = SAT(c + rd); o[1] = SAT(c + gd); o[2] = SAT(c + bd); o[3] = 255;
                o += 4;
            }
        }
    }
    return rgba_buf;
}

#endif
