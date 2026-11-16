/* testpics.c - see testpics.h */
#include <string.h>
#include <strings.h>
#include <math.h>
#include "testpics.h"
#include "colour.h"

static const char *const NAME[TP_NBUILTIN] = {
    "Test card", "Gray ramp", "Color ramps", "Sharpness", "Full white", "Full black",
};
static const char *const HINT[TP_NBUILTIN] = {
    "Grey steps, full and half colors, dark tones and skin tones",
    "Every step should show, down to the darkest and up to the lightest",
    "Smooth ramps: no bands, and no tint as they darken",
    "One- and two-pixel lines and checks: sharp and even; the white border is the picture's edge",
    "Even brightness edge to edge, and no tint",
    "How much the backlight glows through",
};

const char *testpics_name(int k)
{
    return k >= 0 && k < TP_NBUILTIN ? NAME[k] : "";
}

const char *testpics_hint(int k)
{
    return k >= 0 && k < TP_NBUILTIN ? HINT[k] : "";
}

static void put(unsigned char *px, int stride, int x, int y, unsigned rgb)
{
    unsigned char *p = px + (size_t)y * (size_t)stride + (size_t)x * 4;
    p[0] = (unsigned char)(rgb >> 16);
    p[1] = (unsigned char)(rgb >> 8);
    p[2] = (unsigned char)rgb;
    p[3] = 255;
}

static void fill(unsigned char *px, int stride, int x0, int y0, int w, int h, unsigned rgb)
{
    int x, y;
    for (y = y0; y < y0 + h; y++)
        for (x = x0; x < x0 + w; x++) put(px, stride, x, y, rgb);
}

static unsigned grey(int v)
{
    v = v < 0 ? 0 : v > 255 ? 255 : v;
    return (unsigned)v * 0x010101u;
}

/* a band of `steps` equal patches from a to b (steps <= 0: a smooth ramp) */
static void ramp(unsigned char *px, int stride, int y0, int h, int w, int a, int b, int steps,
                 unsigned mask)
{
    int x, y;
    for (x = 0; x < w; x++) {
        int v;
        if (steps > 1) {
            int k = x * steps / w;
            v = a + (b - a) * k / (steps - 1);
        } else {
            v = a + (int)lround((double)(b - a) * x / (w > 1 ? w - 1 : 1));
        }
        for (y = y0; y < y0 + h; y++) put(px, stride, x, y, grey(v) & mask);
    }
}

static void draw_grey(unsigned char *px, int stride, int w, int h)
{
    int b = h / 4;
    ramp(px, stride, 0, b, w, 0, 255, 0, 0xFFFFFF);            /* smooth */
    ramp(px, stride, b, b, w, 0, 255, 32, 0xFFFFFF);           /* 32 steps */
    ramp(px, stride, 2 * b, b, w, 0, 15, 16, 0xFFFFFF);        /* the darkest 16 */
    ramp(px, stride, 3 * b, h - 3 * b, w, 240, 255, 16, 0xFFFFFF);   /* the lightest 16 */
}

static void hue(double t, unsigned *rgb)
{
    /* full-strength hue round the wheel, t in 0..1 */
    double h6 = t * 6.0, f = h6 - floor(h6);
    int k = (int)floor(h6) % 6, up = (int)lround(255 * f), dn = 255 - up;
    static const int R[6] = { 2, 1, 0, 0, 3, 2 }, G[6] = { 3, 2, 2, 1, 0, 0 },
                     B[6] = { 0, 0, 3, 2, 2, 1 };
    /* 0 = none, 1 = falling, 2 = full, 3 = rising */
    int lv[4] = { 0, dn, 255, up };
    *rgb = ((unsigned)lv[R[k]] << 16) | ((unsigned)lv[G[k]] << 8) | (unsigned)lv[B[k]];
}

static void draw_colours(unsigned char *px, int stride, int w, int h)
{
    static const unsigned MASK[6] = { 0xFF0000, 0x00FF00, 0x0000FF, 0x00FFFF, 0xFF00FF, 0xFFFF00 };
    int b = h / 7, k, x, y;
    for (k = 0; k < 6; k++) ramp(px, stride, k * b, b, w, 0, 255, 0, MASK[k]);
    for (x = 0; x < w; x++) {
        unsigned rgb;
        hue((double)x / (w > 1 ? w : 1), &rgb);
        for (y = 6 * b; y < h; y++) put(px, stride, x, y, rgb);
    }
}

static void draw_sharp(unsigned char *px, int stride, int w, int h)
{
    /* two rows of three: vertical lines, horizontal lines, a check - one
     * pixel wide on top, two below - inside a one-pixel white border */
    int cw = w / 3, ch = h / 2, r, c, x, y;
    fill(px, stride, 0, 0, w, h, 0x000000);
    for (r = 0; r < 2; r++) {
        int p = r + 1;
        for (c = 0; c < 3; c++) {
            int x0 = c * cw + 8, y0 = r * ch + 8, x1 = (c + 1) * cw - 8, y1 = (r + 1) * ch - 8;
            for (y = y0; y < y1; y++)
                for (x = x0; x < x1; x++) {
                    int on = c == 0 ? ((x - x0) / p) & 1
                           : c == 1 ? ((y - y0) / p) & 1
                                    : (((x - x0) / p) + ((y - y0) / p)) & 1;
                    put(px, stride, x, y, on ? 0xFFFFFF : 0x000000);
                }
        }
    }
    fill(px, stride, 0, 0, w, 1, 0xFFFFFF);
    fill(px, stride, 0, h - 1, w, 1, 0xFFFFFF);
    fill(px, stride, 0, 0, 1, h, 0xFFFFFF);
    fill(px, stride, w - 1, 0, 1, h, 0xFFFFFF);
}

void testpics_draw(int k, unsigned char *px, int stride, int w, int h)
{
    switch (k) {
    case TP_CARD: {
        /* the card keeps its own 640 x 400 shape, as big as the screen allows */
        int cw = w, ch = w * 400 / 640;
        if (ch > h) { ch = h; cw = h * 640 / 400; }
        fill(px, stride, 0, 0, w, h, 0x000000);
        colour_test_card(px, stride, (w - cw) / 2, (h - ch) / 2, cw, ch);
        break;
    }
    case TP_GREY: draw_grey(px, stride, w, h); break;
    case TP_COLOURS: draw_colours(px, stride, w, h); break;
    case TP_SHARP: draw_sharp(px, stride, w, h); break;
    case TP_WHITE: fill(px, stride, 0, 0, w, h, 0xFFFFFF); break;
    default: fill(px, stride, 0, 0, w, h, 0x000000); break;
    }
}

int testpics_kind(const char *file)
{
    const char *dot = file ? strrchr(file, '.') : NULL;
    if (!dot) return TF_UNKNOWN;
    if (!strcasecmp(dot, ".png")) return TF_PICTURE;
    if (!strcasecmp(dot, ".gif")) return TF_ANIM;
    if (!strcasecmp(dot, ".wav")) return TF_SOUND;
    if (!strcasecmp(dot, ".padv")) return TF_VIDEO;
    return TF_UNKNOWN;
}
