/* gfx.h - a software RGBA canvas with rectangles, rounded frames, TrueType
 * text (stb_truetype, vendored in third_party/) and RGBA blits. The canvas is
 * what the menu is drawn into; egl_stern.c uploads it as one texture and then
 * only the DIRTY rectangle (the union of everything drawn since the last
 * gfx_clean) as a packed sub-rect, and the --headless mode writes it out as a
 * P6 PPM.
 *
 * Coordinates are pixels, origin top-left, y down. Colours are 0xRRGGBB.
 */
#ifndef CODESELECT_GFX_H
#define CODESELECT_GFX_H

struct gfx {
    int w, h;
    unsigned char *px;        /* w*h*4 RGBA, top-down rows */
    unsigned char *scratch;   /* same size; the packed / rotated copy for presenting */
    int dx0, dy0, dx1, dy1;   /* dirty union, clipped to the canvas; empty when dx1 <= dx0 */
};

struct gfx_font;

int  gfx_init(struct gfx *g, int w, int h);           /* 0 ok */
void gfx_free(struct gfx *g);

void gfx_fill(struct gfx *g, unsigned rgb);
void gfx_rect(struct gfx *g, int x, int y, int w, int h, unsigned rgb);
void gfx_round_rect(struct gfx *g, int x, int y, int w, int h, int r, unsigned rgb);
/* a rounded rectangle with a border t pixels wide in frame_rgb and the inside
 * in fill_rgb */
void gfx_round_frame(struct gfx *g, int x, int y, int w, int h, int r, int t,
                     unsigned frame_rgb, unsigned fill_rgb);
/* alpha-blend a w x h RGBA image (tightly packed rows) at x, y; clipped */
void gfx_blit(struct gfx *g, int x, int y, const unsigned char *rgba, int w, int h);

struct gfx_font *gfx_font_load(const char *path);     /* NULL on failure */
void gfx_font_free(struct gfx_font *f);
/* ascent (above the baseline) and descent (below, positive) in pixels at px */
int  gfx_font_ascent(struct gfx_font *f, float px);
int  gfx_font_descent(struct gfx_font *f, float px);

int  gfx_text_width(struct gfx_font *f, float px, const char *s);
void gfx_text(struct gfx *g, struct gfx_font *f, float px, int x, int baseline,
              const char *s, unsigned rgb);
void gfx_text_center(struct gfx *g, struct gfx_font *f, float px, int cx, int baseline,
                     const char *s, unsigned rgb);
/* the largest size in [min_px, px] at which s fits into max_w pixels */
float gfx_fit_px(struct gfx_font *f, const char *s, int max_w, float px, float min_px);
/* word-wrap s into lines of at most max_w pixels; returns the line count
 * (at most max_lines; a longer text is cut). Each line is at most line_len-1
 * bytes. */
int  gfx_wrap(struct gfx_font *f, float px, const char *s, int max_w,
              char *lines, int line_len, int max_lines);

/* Dirty tracking: every drawing call grows the union; gfx_dirty() reports it
 * (0 = nothing drawn since the last gfx_clean), gfx_clean() empties it. */
int  gfx_dirty(const struct gfx *g, int *x, int *y, int *w, int *h);
void gfx_clean(struct gfx *g);

/* The pixels to present: the canvas itself, or (invert) a 180-degree rotated
 * copy kept in g->scratch - what boot_display's -invert does to its picture. */
const unsigned char *gfx_pixels(struct gfx *g, int invert);
/* The dirty rectangle, tightly packed (w*4-byte rows) into g->scratch, ready
 * for one glTexSubImage2D; with invert the pixels are reversed and the
 * returned rectangle is the mirrored one (W-x-w, H-y-h, w, h). NULL and w=h=0
 * when nothing is dirty. Does not clean. */
const unsigned char *gfx_pack(struct gfx *g, int invert, int *x, int *y, int *w, int *h);
/* binary P6 PPM of gfx_pixels(g, invert); 0 ok */
int  gfx_write_ppm(struct gfx *g, const char *path, int invert);

#endif
