/* fb_linux.c - the egl_stern.h interface on a Linux framebuffer: a Barrels
 * of Fun machine (PAD-342).  The BOF build (make PLATFORM=bof) links this in
 * place of egl_stern.c / egl_x11.c; the menu code is unchanged and never
 * knows.
 *
 * WHY THE FRAMEBUFFER.  A BOF machine is an Arch Linux PC that logs the
 * `pinball` user in on tty1, and ~/.bash_profile starts the game from that
 * console.  The menu runs there, BEFORE the game, so there is no X server and
 * no compositor yet - only the kernel's console framebuffer.  That is exactly
 * what BOF's own updater draws on: Labyrinth's update/main (an SDL-linked ELF
 * that never opens a window) runs `sudo fbset -xres 1366 -yres 768 -match`,
 * hides the console cursor with `\033[?17;0;0c` on /dev/tty1, opens /dev/fb0,
 * reads FBIOGET_FSCREENINFO / FBIOGET_VSCREENINFO, mmaps it and writes its
 * BMP frames into it pixel by pixel through the var-info colour offsets.
 * This file does the same, so the menu appears on the glass by the one route
 * the machine's own software is already known to take.
 *
 * THE CANVAS.  The struct egl_stern the menu hands in stays the public
 * surface, and its w/h are the CANVAS (codeselect.c's HEADLESS_W x
 * HEADLESS_H, 1360x768) whatever the screen is, so layout_compute draws the
 * same menu it draws headless and in the preview.  On the glass:
 *
 *   - a screen at least the canvas's size and less than half again as big
 *     (the 1366x768 BOF screen) shows it 1:1, centred, black around it;
 *   - anything else is scaled to fit with the aspect kept (nearest
 *     neighbour: no blur, no float in the copy loop), centred.
 *
 * TWO SCREENS OF DIFFERENT SIZES.  The kernel's DRM console puts ONE buffer
 * on every screen: the buffer is the biggest screen's size (xres_virtual x
 * yres_virtual) and the visible area it reports (xres x yres) is the
 * smallest, so console text fits on all of them.  A Labyrinth has the
 * 1366x768 backbox and the 1280x390 strip over the playfield, so fb0 says
 * "1280x390" of a 1366x768 buffer, and a menu sized to that drew at half
 * size in the backbox's top left (David's photo, 2026-10-04).  Each screen
 * shows the buffer from its own top left at its own size, so when the buffer
 * is WIDER than the visible area the menu takes the whole buffer: the
 * backbox gets it full screen, the strip its top 1280x390.  BOF's updater
 * gets the same by running fbset -xres 1366 -yres 768 first; this changes no
 * console setting.  A buffer that is only TALLER is panning room (double
 * buffering) that no screen shows, and keeps the visible area.
 *
 * THE PIXEL FORMAT is read, never assumed: 16, 24 and 32 bits per pixel,
 * each channel at the var info's offset and length (the updater's own
 * pixel_color() does the same), rows at the fixed info's line_length, and
 * the visible page at xoffset / yoffset.
 *
 * NO VSYNC.  The menu loop presents every pass and lets the swap pace it; a
 * framebuffer write returns at once, so this paces itself to 60 frames a
 * second the way egl_x11.c's XPutImage path does.
 *
 * A FAKE FRAMEBUFFER for tests (no /dev/fb0 on a build host or in WSL):
 * PAD_SELECT_FAKEFB=<W>x<H>x<BPP>[,<VW>x<VH>]:<file> maps that regular file
 * instead, with the common little-endian layout for the depth (32: B G R X;
 * 24: B G R; 16: RGB565) and no ioctls.  <W>x<H> is the visible area and
 * <VW>x<VH> the buffer (default the same): "1280x390x32,1366x768" is a
 * Labyrinth's console.  The test reads the file back as the glass.
 * PAD_SELECT_FB names another device (default /dev/fb0).
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/fb.h>
#include "egl_stern.h"
#include "log.h"

/* the canvas the menu draws: codeselect.c's HEADLESS_W x HEADLESS_H */
#define CANVAS_W 1360
#define CANVAS_H 768

static struct {
    int fd;
    unsigned char *map;       /* the whole mapping */
    size_t map_len;
    unsigned char *page;      /* the visible page: map + yoffset rows + xoffset px */
    int fb_w, fb_h, bpp, stride;
    int vw, vh, panned;       /* the buffer's size; panned = a non-zero x/yoffset */
    int r_off, r_len, g_off, g_len, b_off, b_len;
    int ox, oy, dw, dh;       /* where the canvas lands on the glass, and how big */
    int scaled;
    int *xmap, *ymap;         /* scaled: glass column/row -> canvas column/row */
    int fake;
} F = { .fd = -1 };

static unsigned pixel_of(unsigned char r, unsigned char g, unsigned char b)
{
    return ((unsigned)(r >> (8 - F.r_len)) << F.r_off)
         | ((unsigned)(g >> (8 - F.g_len)) << F.g_off)
         | ((unsigned)(b >> (8 - F.b_len)) << F.b_off);
}

static void put_px(unsigned char *d, unsigned v)
{
    switch (F.bpp) {
    case 32: d[0] = v; d[1] = v >> 8; d[2] = v >> 16; d[3] = v >> 24; break;
    case 24: d[0] = v; d[1] = v >> 8; d[2] = v >> 16; break;
    default: d[0] = v; d[1] = v >> 8; break;
    }
}

static int fake_up(const char *spec)
{
    int w, h, bpp, vw, vh, n = 0;
    const char *path;
    if (sscanf(spec, "%dx%dx%d,%dx%d:%n", &w, &h, &bpp, &vw, &vh, &n) == 5 && n) {
        if (vw < w || vh < h) n = 0;
    } else if (sscanf(spec, "%dx%dx%d:%n", &w, &h, &bpp, &n) == 3 && n) {
        vw = w; vh = h;
    } else {
        n = 0;
    }
    if (!n || w <= 0 || h <= 0 || (bpp != 16 && bpp != 24 && bpp != 32)) {
        sel_log("fb: PAD_SELECT_FAKEFB=%s is not <W>x<H>x<16|24|32>[,<VW>x<VH>]:<file> "
                "(the buffer at least the visible area)", spec);
        return -1;
    }
    path = spec + n;
    F.fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0644);
    if (F.fd < 0) { sel_log("fb: cannot open fake framebuffer %s: %s", path, strerror(errno)); return -1; }
    F.fb_w = w; F.fb_h = h; F.bpp = bpp;
    F.vw = vw; F.vh = vh; F.panned = 0;
    F.stride = vw * (bpp / 8);
    F.map_len = (size_t)F.stride * vh;
    if (ftruncate(F.fd, (off_t)F.map_len) < 0) {
        sel_log("fb: cannot size %s: %s", path, strerror(errno));
        close(F.fd); F.fd = -1;
        return -1;
    }
    if (bpp == 16) { F.r_off = 11; F.r_len = 5; F.g_off = 5; F.g_len = 6; F.b_off = 0; F.b_len = 5; }
    else { F.r_off = 16; F.r_len = 8; F.g_off = 8; F.g_len = 8; F.b_off = 0; F.b_len = 8; }
    F.fake = 1;
    sel_log("fb: fake framebuffer %s %dx%d of a %dx%d buffer, %d bpp", path, w, h, vw, vh, bpp);
    return 0;
}

static int fb_up(void)
{
    const char *dev = getenv("PAD_SELECT_FB") && *getenv("PAD_SELECT_FB") ? getenv("PAD_SELECT_FB") : "/dev/fb0";
    struct fb_var_screeninfo v;
    struct fb_fix_screeninfo fx;
    F.fd = open(dev, O_RDWR | O_CLOEXEC);
    if (F.fd < 0) { sel_log("fb: cannot open %s: %s", dev, strerror(errno)); return -1; }
    if (ioctl(F.fd, FBIOGET_FSCREENINFO, &fx) < 0 || ioctl(F.fd, FBIOGET_VSCREENINFO, &v) < 0) {
        sel_log("fb: %s: cannot read the screen info: %s", dev, strerror(errno));
        close(F.fd); F.fd = -1;
        return -1;
    }
    if ((v.bits_per_pixel != 16 && v.bits_per_pixel != 24 && v.bits_per_pixel != 32)
        || !v.red.length || !v.green.length || !v.blue.length
        || v.red.length > 8 || v.green.length > 8 || v.blue.length > 8) {
        sel_log("fb: %s: %u bpp (r %u/%u g %u/%u b %u/%u) is not a true-colour mode this draws",
                dev, v.bits_per_pixel, v.red.offset, v.red.length, v.green.offset, v.green.length,
                v.blue.offset, v.blue.length);
        close(F.fd); F.fd = -1;
        return -1;
    }
    F.fb_w = (int)v.xres; F.fb_h = (int)v.yres; F.bpp = (int)v.bits_per_pixel;
    F.vw = (int)v.xres_virtual; F.vh = (int)v.yres_virtual;
    F.panned = v.xoffset || v.yoffset;
    F.stride = (int)fx.line_length;
    F.r_off = (int)v.red.offset; F.r_len = (int)v.red.length;
    F.g_off = (int)v.green.offset; F.g_len = (int)v.green.length;
    F.b_off = (int)v.blue.offset; F.b_len = (int)v.blue.length;
    F.map_len = fx.smem_len ? fx.smem_len : (size_t)F.stride * v.yres_virtual;
    if ((size_t)F.stride * (v.yoffset + v.yres) > F.map_len) {
        sel_log("fb: %s: the visible page (yoffset %u) lies past the %zu-byte buffer", dev, v.yoffset, F.map_len);
        close(F.fd); F.fd = -1;
        return -1;
    }
    F.map = mmap(NULL, F.map_len, PROT_READ | PROT_WRITE, MAP_SHARED, F.fd, 0);
    if (F.map == MAP_FAILED) {
        sel_log("fb: %s: mmap of %zu bytes failed: %s", dev, F.map_len, strerror(errno));
        F.map = NULL;
        close(F.fd); F.fd = -1;
        return -1;
    }
    F.page = F.map + (size_t)v.yoffset * F.stride + (size_t)v.xoffset * (F.bpp / 8);
    sel_log("fb: %s %dx%d of a %dx%d buffer at %u,%u, %d bpp, stride %d, r %d/%d g %d/%d b %d/%d",
            dev, F.fb_w, F.fb_h, F.vw, F.vh, v.xoffset, v.yoffset, F.bpp,
            F.stride, F.r_off, F.r_len, F.g_off, F.g_len, F.b_off, F.b_len);
    return 0;
}

/* Screens of different sizes (the header's TWO SCREENS): when the buffer is
 * wider than the visible area, the glass is the whole buffer - as much of it
 * as is mapped - from its top left. */
static void whole_buffer(void)
{
    int rows = (int)(F.map_len / (size_t)F.stride), cols = F.stride / (F.bpp / 8);
    int vw = F.vw < cols ? F.vw : cols, vh = F.vh < rows ? F.vh : rows;
    if (F.panned || vw <= F.fb_w || vh < F.fb_h) return;
    sel_log("fb: the console shows %dx%d of a %dx%d buffer (screens of different sizes): "
            "the menu draws the whole buffer", F.fb_w, F.fb_h, vw, vh);
    F.fb_w = vw;
    F.fb_h = vh;
    F.page = F.map;
}

static int map_fake(void)
{
    F.map = mmap(NULL, F.map_len, PROT_READ | PROT_WRITE, MAP_SHARED, F.fd, 0);
    if (F.map == MAP_FAILED) {
        sel_log("fb: fake framebuffer mmap failed: %s", strerror(errno));
        F.map = NULL;
        return -1;
    }
    F.page = F.map;
    return 0;
}

/* where the canvas goes: 1:1 centred when the screen is the canvas's size or a
 * little more, else scaled to fit, aspect kept */
static int place(void)
{
    int i;
    if (F.fb_w >= CANVAS_W && F.fb_h >= CANVAS_H
        && F.fb_w * 2 < CANVAS_W * 3 && F.fb_h * 2 < CANVAS_H * 3) {
        F.dw = CANVAS_W;
        F.dh = CANVAS_H;
        F.scaled = 0;
    } else {
        /* fit: the smaller of the two ratios, in integer arithmetic */
        if ((long long)F.fb_w * CANVAS_H <= (long long)F.fb_h * CANVAS_W) {
            F.dw = F.fb_w;
            F.dh = (int)((long long)F.fb_w * CANVAS_H / CANVAS_W);
        } else {
            F.dh = F.fb_h;
            F.dw = (int)((long long)F.fb_h * CANVAS_W / CANVAS_H);
        }
        if (F.dw < 1 || F.dh < 1) return -1;
        F.scaled = 1;
        F.xmap = malloc(sizeof *F.xmap * (size_t)F.dw);
        F.ymap = malloc(sizeof *F.ymap * (size_t)F.dh);
        if (!F.xmap || !F.ymap) return -1;
        for (i = 0; i < F.dw; i++) F.xmap[i] = (int)((long long)i * CANVAS_W / F.dw);
        for (i = 0; i < F.dh; i++) F.ymap[i] = (int)((long long)i * CANVAS_H / F.dh);
    }
    F.ox = (F.fb_w - F.dw) / 2;
    F.oy = (F.fb_h - F.dh) / 2;
    return 0;
}

static void clear_glass(void)
{
    int r;
    unsigned black = pixel_of(0, 0, 0);
    int bp = F.bpp / 8, c;
    for (r = 0; r < F.fb_h; r++) {
        unsigned char *d = F.page + (size_t)r * F.stride;
        if (!black) { memset(d, 0, (size_t)F.fb_w * bp); continue; }
        for (c = 0; c < F.fb_w; c++) put_px(d + (size_t)c * bp, black);
    }
}

/* the canvas rectangle x,y,w,h, whose RGBA rows are `src` with `pitch` pixels
 * to a row, onto the glass */
static void blit(const unsigned char *src, int pitch, int x, int y, int w, int h)
{
    int bp = F.bpp / 8;
    if (!F.scaled) {
        int r, c;
        for (r = 0; r < h; r++) {
            const unsigned char *s = src + (size_t)r * pitch * 4;
            unsigned char *d = F.page + (size_t)(F.oy + y + r) * F.stride + (size_t)(F.ox + x) * bp;
            for (c = 0; c < w; c++, s += 4, d += bp)
                put_px(d, pixel_of(s[0], s[1], s[2]));
        }
        return;
    }
    {
        /* the glass rows/columns whose source falls inside the rectangle */
        int dy, dx;
        for (dy = 0; dy < F.dh; dy++) {
            int sy = F.ymap[dy];
            unsigned char *d;
            if (sy < y || sy >= y + h) continue;
            d = F.page + (size_t)(F.oy + dy) * F.stride + (size_t)F.ox * bp;
            for (dx = 0; dx < F.dw; dx++) {
                int sx = F.xmap[dx];
                const unsigned char *s;
                if (sx < x || sx >= x + w) continue;
                s = src + ((size_t)(sy - y) * pitch + (size_t)(sx - x)) * 4;
                put_px(d + (size_t)dx * bp, pixel_of(s[0], s[1], s[2]));
            }
        }
    }
}

/* The console's text cursor would blink over the menu: off, the way BOF's
 * updater turns it off (\033[?17;0;0c, the Linux console's soft-cursor
 * sequence) plus the standard hide.  Only on a terminal, and never on the
 * fake framebuffer (a test's stdout is a pipe or the developer's terminal). */
static void cursor_off(void)
{
    static const char seq[] = "\033[?25l\033[?17;0;0c";
    if (!F.fake && isatty(1)) {
        ssize_t n = write(1, seq, sizeof seq - 1);
        (void)n;
    }
}

int egl_stern_init(struct egl_stern *e, int retries, int retry_ms)
{
    int attempt, ok = -1;
    const char *fake = getenv("PAD_SELECT_FAKEFB");
    memset(e, 0, sizeof *e);
    e->w = CANVAS_W;
    e->h = CANVAS_H;
    if (retries < 1) retries = 1;
    for (attempt = 1; attempt <= retries; attempt++) {
        ok = fake && *fake ? (fake_up(fake) == 0 ? map_fake() : -1) : fb_up();
        if (ok == 0) break;
        if (attempt < retries) {
            sel_log("fb: attempt %d/%d failed, retrying in %d ms", attempt, retries, retry_ms);
            sel_sleep_ms(retry_ms);
        }
    }
    if (ok < 0) {
        sel_log("fb: giving up after %d attempts", retries);
        return -1;
    }
    whole_buffer();
    if (place() < 0) {
        sel_log("fb: cannot place a %dx%d canvas on a %dx%d screen", CANVAS_W, CANVAS_H, F.fb_w, F.fb_h);
        egl_stern_close(e);
        return -1;
    }
    cursor_off();
    clear_glass();
    e->up = 1;
    sel_log("fb: canvas %dx%d %s at %d,%d on the %dx%d screen", CANVAS_W, CANVAS_H,
            F.scaled ? "scaled" : "1:1", F.ox, F.oy, F.fb_w, F.fb_h);
    if (F.scaled) sel_log("fb: scaled to %dx%d", F.dw, F.dh);
    return 0;
}

int egl_stern_texture(struct egl_stern *e, int w, int h, const unsigned char *px)
{
    if (!e->up) return -1;
    e->tex_w = w;
    e->tex_h = h;
    if (w > CANVAS_W) w = CANVAS_W;
    if (h > CANVAS_H) h = CANVAS_H;
    blit(px, e->tex_w, 0, 0, w, h);
    return 0;
}

void egl_stern_frame(struct egl_stern *e, const unsigned char *packed, int x, int y, int w, int h)
{
    static long long next_tick;
    long long now;
    if (!e->up) return;
    if (packed && w > 0 && h > 0) {
        int pitch = w;
        if (x + w > CANVAS_W) w = CANVAS_W - x;
        if (y + h > CANVAS_H) h = CANVAS_H - y;
        if (w > 0 && h > 0) {
            blit(packed, pitch, x, y, w, h);
            e->uploaded += (long long)w * h * 4;
        }
        if (F.fake) msync(F.map, F.map_len, MS_ASYNC);
    }
    /* 60 frames a second, the pace a swap would set */
    now = sel_now_ms();
    if (next_tick > now && next_tick - now <= 17) sel_sleep_ms(next_tick - now);
    now = sel_now_ms();
    next_tick = (next_tick > now - 17 ? next_tick : now) + 16;
    e->frames++;
}

void egl_stern_close(struct egl_stern *e)
{
    if (e->up)
        sel_log("fb: %d frames, %lld KB drawn, closing (the LOADING frame stays up until the game draws)",
                e->frames, e->uploaded / 1024);
    /* THE PICTURE STAYS: nothing is cleared.  The LOADING frame is what the
     * player sees until the game's own first frame replaces it. */
    if (F.map) {
        if (F.fake) msync(F.map, F.map_len, MS_SYNC);
        munmap(F.map, F.map_len);
    }
    if (F.fd >= 0) close(F.fd);
    free(F.xmap);
    free(F.ymap);
    F.map = NULL;
    F.page = NULL;
    F.xmap = F.ymap = NULL;
    F.fd = -1;
    e->up = 0;
}
