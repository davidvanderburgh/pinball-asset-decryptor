/* gfx.h - a software RGBA canvas with rectangles, rounded frames and
 * TrueType text (stb_truetype, vendored in third_party/). The canvas is what
 * the menu is drawn into; egl_stern.c uploads it as one texture and the
 * --headless mode writes it out as a P6 PPM.
 *
 * Coordinates are pixels, origin top-left, y down. Colours are 0xRRGGBB.
 */
#ifndef CODESELECT_GFX_H
#define CODESELECT_GFX_H

struct gfx {
    int w, h;
    unsigned char *px;        /* w*h*4 RGBA, top-down rows */
    unsigned char *scratch;   /* same size; the 180-degree rotated copy */
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

/* The pixels to present: the canvas itself, or (invert) a 180-degree rotated
 * copy kept in g->scratch - what boot_display's -invert does to its picture. */
const unsigned char *gfx_pixels(struct gfx *g, int invert);
/* binary P6 PPM of gfx_pixels(g, invert); 0 ok */
int  gfx_write_ppm(struct gfx *g, const char *path, int invert);

#endif
