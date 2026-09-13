/* egl_x11.c - the egl_stern.h interface on an X11 desktop: a JJP machine
 * (Ubuntu 21.10 rootfs, Mesa, the X server xinit started for rungame.sh) or
 * the rig's Xephyr / WSLg.  The JJP build (make PLATFORM=jjp) links this in
 * place of egl_stern.c; the menu code is unchanged and never knows.
 *
 * Two ways to put the canvas on the glass, tried in this order:
 *
 *   1. EGL/GLES2 on the X window.  libEGL.so.1 and libGLESv2.so.2 are
 *      dlopen'd at run time and never linked: the WSL host that builds this
 *      has no libGLESv2 at all, and a machine whose Mesa is missing or
 *      broken must still get a menu through path 2.  Same shaders, same
 *      one-quad upload and dirty-rect glTexSubImage2D as egl_stern.c; the
 *      quad scales the 1360x768 canvas to the window, so the picture is the
 *      one the snapshot and the Stern card show, only bigger.
 *   2. XPutImage of the canvas, centred, unscaled.  Plain Xlib, no GL.
 *
 * Xlib is linked (libX11.so.6 is on every X box) but its prototypes are
 * declared by hand, the way egl_stern.c declares EGL: the build host has no
 * X11 headers, and the handful of calls used here have signatures that have
 * not moved in thirty years.  Two structs are laid out by hand - Visual (to
 * read the colour masks) and XSetWindowAttributes (override_redirect) - and
 * both are frozen public ABI.
 *
 * The struct egl_stern the menu hands in stays the public surface.  Its w/h
 * are the CANVAS size (HEADLESS_W x HEADLESS_H) whatever the screen is, so
 * layout_compute draws the same menu it draws headless; everything else
 * lives in file-static state.  There is one display.
 *
 * THE WINDOW.  On the machine there is no window manager - xinit runs
 * rungame.sh and nothing else - so a plain window at 0,0 sized to the main
 * display IS the whole glass, exactly as the game's own window is.  It is
 * override-redirect too, which keeps a desktop's window manager (the rig on
 * WSLg :0) from decorating or moving it.  A cabinet with a second display
 * (Wonka's apron) has an X screen wider than 16:9: the main display sits at
 * 0,0, so the window is cut to a 16:9 box of the screen's height.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include "egl_stern.h"
#include "log.h"

/* ---- Xlib, declared by hand (no X11 headers on the build host) ---- */
typedef unsigned long XID;
struct x_visual {                 /* Visual, Xlib.h */
    void *ext_data;
    XID visualid;
    int class_;
    unsigned long red_mask, green_mask, blue_mask;
    int bits_per_rgb;
    int map_entries;
};
struct x_setwinattr {             /* XSetWindowAttributes, Xlib.h */
    XID background_pixmap;
    unsigned long background_pixel;
    XID border_pixmap;
    unsigned long border_pixel;
    int bit_gravity, win_gravity, backing_store;
    unsigned long backing_planes, backing_pixel;
    int save_under;
    long event_mask, do_not_propagate_mask;
    int override_redirect;
    XID colormap, cursor;
};
#define CW_OVERRIDE_REDIRECT (1L << 9)
#define ZPIXMAP 2

extern void *XOpenDisplay(const char *);
extern int   XCloseDisplay(void *);
extern int   XDefaultScreen(void *);
extern XID   XRootWindow(void *, int);
extern int   XDisplayWidth(void *, int);
extern int   XDisplayHeight(void *, int);
extern void *XDefaultVisual(void *, int);
extern int   XDefaultDepth(void *, int);
extern XID   XVisualIDFromVisual(void *);
extern XID   XCreateSimpleWindow(void *, XID, int, int, unsigned, unsigned, unsigned, unsigned long, unsigned long);
extern int   XChangeWindowAttributes(void *, XID, unsigned long, struct x_setwinattr *);
extern int   XStoreName(void *, XID, const char *);
extern int   XMapRaised(void *, XID);
extern int   XDestroyWindow(void *, XID);
extern int   XFlush(void *);
extern int   XSync(void *, int);
extern void *XCreateGC(void *, XID, unsigned long, void *);
extern int   XFreeGC(void *, void *);
extern void *XCreateImage(void *, void *, unsigned, int, int, char *, unsigned, unsigned, int, int);
extern int   XPutImage(void *, XID, void *, void *, int, int, int, int, unsigned, unsigned);
extern int   XFree(void *);

/* ---- EGL / GLES2 through dlopen: function pointers, not symbols ---- */
static struct {
    void *egl, *gles;
    void *(*eglGetDisplay)(void *);
    int   (*eglInitialize)(void *, int *, int *);
    int   (*eglChooseConfig)(void *, const int *, void **, int, int *);
    int   (*eglGetConfigAttrib)(void *, void *, int, int *);
    void *(*eglCreateWindowSurface)(void *, void *, XID, const int *);
    int   (*eglBindAPI)(unsigned);
    void *(*eglCreateContext)(void *, void *, void *, const int *);
    int   (*eglMakeCurrent)(void *, void *, void *, void *);
    int   (*eglSwapBuffers)(void *, void *);
    int   (*eglSwapInterval)(void *, int);
    int   (*eglDestroySurface)(void *, void *);
    int   (*eglDestroyContext)(void *, void *);
    int   (*eglTerminate)(void *);
    int   (*eglReleaseThread)(void);
    int   (*eglGetError)(void);
    const unsigned char *(*glGetString)(unsigned);
    void (*glViewport)(int, int, int, int);
    void (*glClearColor)(float, float, float, float);
    void (*glClear)(unsigned);
    void (*glEnable)(unsigned);
    void (*glDisable)(unsigned);
    void (*glBlendFunc)(unsigned, unsigned);
    void (*glGenVertexArrays)(int, unsigned *);
    void (*glBindVertexArray)(unsigned);
    void (*glGenBuffers)(int, unsigned *);
    void (*glBindBuffer)(unsigned, unsigned);
    void (*glBufferData)(unsigned, long, const void *, unsigned);
    void (*glVertexAttribPointer)(unsigned, int, unsigned, unsigned char, int, const void *);
    void (*glEnableVertexAttribArray)(unsigned);
    unsigned (*glCreateShader)(unsigned);
    void (*glShaderSource)(unsigned, int, const char *const *, const int *);
    void (*glCompileShader)(unsigned);
    void (*glGetShaderiv)(unsigned, unsigned, int *);
    unsigned (*glCreateProgram)(void);
    void (*glAttachShader)(unsigned, unsigned);
    void (*glLinkProgram)(unsigned);
    void (*glGetProgramiv)(unsigned, unsigned, int *);
    void (*glUseProgram)(unsigned);
    int  (*glGetUniformLocation)(unsigned, const char *);
    void (*glUniform1i)(int, int);
    void (*glUniformMatrix4fv)(int, int, unsigned char, const float *);
    void (*glGenTextures)(int, unsigned *);
    void (*glBindTexture)(unsigned, unsigned);
    void (*glTexParameteri)(unsigned, unsigned, int);
    void (*glTexImage2D)(unsigned, int, int, int, int, int, unsigned, unsigned, const void *);
    void (*glTexSubImage2D)(unsigned, int, int, int, int, int, unsigned, unsigned, const void *);
    void (*glActiveTexture)(unsigned);
    void (*glDrawArrays)(unsigned, int, int);
    unsigned (*glGetError)(void);
} G;

#define EGL_SUCCESS           0x3000
#define EGL_NATIVE_VISUAL_ID  0x302E
#define EGL_OPENGL_ES_API     0x30A0
#define GL_TEXTURE_2D         0x0DE1
#define GL_TEXTURE0           0x84C0
#define GL_RGBA               0x1908
#define GL_UNSIGNED_BYTE      0x1401
#define GL_TEXTURE_MIN_FILTER 0x2801
#define GL_TEXTURE_MAG_FILTER 0x2800
#define GL_TEXTURE_WRAP_S     0x2802
#define GL_TEXTURE_WRAP_T     0x2803
#define GL_LINEAR             0x2601
#define GL_CLAMP_TO_EDGE      0x812F
#define GL_ARRAY_BUFFER       0x8892
#define GL_STATIC_DRAW        0x88E4
#define GL_FLOAT              0x1406
#define GL_TRIANGLES          0x0004
#define GL_VERTEX_SHADER      0x8B31
#define GL_FRAGMENT_SHADER    0x8B30
#define GL_COMPILE_STATUS     0x8B81
#define GL_LINK_STATUS        0x8B82
#define GL_BLEND              0x0BE2
#define GL_SRC_ALPHA          0x0302
#define GL_ONE_MINUS_SRC_ALPHA 0x0303
#define GL_COLOR_DEPTH_BITS   0x4100

/* RGB 8/8/8 (minimums: a 24-bit X visual), no alpha needed, no depth needed
 * for one quad - a depth buffer would only cost a swrast box memory */
static const int cfg_attr[] = { 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 0,
                                0x3040, 0x0004 /* EGL_RENDERABLE_TYPE = ES2 */,
                                0x3033, 0x0004 /* EGL_SURFACE_TYPE = WINDOW */, 0x3038 };
static const int ctx_attr[] = { 0x3098, 2, 0x3038 };

static const char *VS =
    "#version 300 es\n"
    "layout (location = 0) in vec4 vertex; // <vec2 position, vec2 texCoords>\n"
    "out vec2 TexCoords;\n"
    "uniform mat4 projection;\n"
    "void main() {\n"
    "    TexCoords = vertex.zw;\n"
    "    gl_Position = projection * vec4(vertex.xy, 0.0, 1.0);\n"
    "}\n";
static const char *FS =
    "#version 300 es\n"
    "in highp vec2 TexCoords;\n"
    "out lowp vec4 color;\n"
    "uniform sampler2D image;\n"
    "void main() { color = texture(image, TexCoords); }\n";

/* the canvas the menu draws: codeselect.c's HEADLESS_W x HEADLESS_H */
#define CANVAS_W 1360
#define CANVAS_H 768

/* ---- the one display ---- */
static struct {
    void *dpy;                /* Display* */
    int screen;
    XID root, win;
    int win_w, win_h;         /* the window on the glass */
    int mode;                 /* 0 none, 1 GL, 2 XImage */
    /* GL */
    void *edpy, *cfg, *surf, *ctx;
    /* XImage */
    void *gc, *img;
    unsigned char *pix;       /* CANVAS_W*CANVAS_H*4, the server's pixel order */
    int rsh, gsh, bsh;        /* where each 8-bit channel goes in the 32-bit word */
    int ox, oy;               /* where the canvas sits in the window */
} X;

static int shift_of(unsigned long mask)
{
    int s = 0;
    if (!mask) return 0;
    while (!(mask & 1)) { mask >>= 1; s++; }
    /* an 8-bit channel; a 5- or 6-bit one lands close enough to be seen */
    return s;
}

static void *sym(void *lib, const char *name, int *missing)
{
    void *p = lib ? dlsym(lib, name) : NULL;
    if (!p) (*missing)++;
    return p;
}

static int load_gl(void)
{
    int missing = 0;
    if (G.egl) return 0;
    G.egl = dlopen("libEGL.so.1", RTLD_NOW | RTLD_GLOBAL);
    G.gles = dlopen("libGLESv2.so.2", RTLD_NOW | RTLD_GLOBAL);
    if (!G.egl || !G.gles) {
        sel_log("egl: %s: %s", G.egl ? "libGLESv2.so.2" : "libEGL.so.1", dlerror());
        return -1;
    }
#define E(n) G.n = sym(G.egl, #n, &missing)
#define L(n) G.n = sym(G.gles, #n, &missing)
    E(eglGetDisplay); E(eglInitialize); E(eglChooseConfig); E(eglGetConfigAttrib);
    E(eglCreateWindowSurface); E(eglBindAPI); E(eglCreateContext); E(eglMakeCurrent);
    E(eglSwapBuffers); E(eglSwapInterval); E(eglDestroySurface); E(eglDestroyContext);
    E(eglTerminate); E(eglReleaseThread); E(eglGetError);
    L(glGetString); L(glViewport); L(glClearColor); L(glClear); L(glEnable); L(glDisable);
    L(glBlendFunc); L(glGenVertexArrays); L(glBindVertexArray); L(glGenBuffers);
    L(glBindBuffer); L(glBufferData); L(glVertexAttribPointer); L(glEnableVertexAttribArray);
    L(glCreateShader); L(glShaderSource); L(glCompileShader); L(glGetShaderiv);
    L(glCreateProgram); L(glAttachShader); L(glLinkProgram); L(glGetProgramiv);
    L(glUseProgram); L(glGetUniformLocation); L(glUniform1i); L(glUniformMatrix4fv);
    L(glGenTextures); L(glBindTexture); L(glTexParameteri); L(glTexImage2D);
    L(glTexSubImage2D); L(glActiveTexture); L(glDrawArrays); L(glGetError);
#undef E
#undef L
    if (missing) {
        sel_log("egl: %d EGL/GLES2 entry point(s) missing from the libraries", missing);
        return -1;
    }
    return 0;
}

static int egl_ok(const char *step)
{
    int e = G.eglGetError();
    if (e != EGL_SUCCESS) {
        sel_log("egl: %s failed, eglGetError=0x%x", step, e);
        return 0;
    }
    return 1;
}

/* the X side: display, screen geometry, the window.  0 ok. */
static int x_up(void)
{
    struct x_setwinattr a;
    struct x_visual *v;
    int sw, sh;
    if (X.dpy) return 0;
    X.dpy = XOpenDisplay(NULL);
    if (!X.dpy) {
        const char *d = getenv("DISPLAY");
        sel_log("x11: cannot open display '%s'", d ? d : "(unset)");
        return -1;
    }
    X.screen = XDefaultScreen(X.dpy);
    X.root = XRootWindow(X.dpy, X.screen);
    sw = XDisplayWidth(X.dpy, X.screen);
    sh = XDisplayHeight(X.dpy, X.screen);
    X.win_w = sw;
    X.win_h = sh;
    /* a second display makes the screen wider than any one panel: the main
     * display is at 0,0 and 16:9 (setupdisplays.sh puts the aux right of it) */
    if (sh > 0 && sw * 9 > sh * 16 * 11 / 10) {
        X.win_w = sh * 16 / 9;
        sel_log("x11: screen %dx%d is wider than 16:9, using the left %dx%d", sw, sh, X.win_w, X.win_h);
    }
    if (X.win_w <= 0 || X.win_h <= 0) { X.win_w = CANVAS_W; X.win_h = CANVAS_H; }
    X.win = XCreateSimpleWindow(X.dpy, X.root, 0, 0, (unsigned)X.win_w, (unsigned)X.win_h, 0, 0, 0);
    memset(&a, 0, sizeof a);
    a.override_redirect = 1;
    XChangeWindowAttributes(X.dpy, X.win, CW_OVERRIDE_REDIRECT, &a);
    XStoreName(X.dpy, X.win, "jjpselect - boot menu");
    XMapRaised(X.dpy, X.win);
    XSync(X.dpy, 0);
    v = XDefaultVisual(X.dpy, X.screen);
    X.rsh = shift_of(v->red_mask);
    X.gsh = shift_of(v->green_mask);
    X.bsh = shift_of(v->blue_mask);
    sel_log("x11: screen %dx%d depth %d, window %dx%d at 0,0 (visual 0x%lx, masks %lx/%lx/%lx)",
            sw, sh, XDefaultDepth(X.dpy, X.screen), X.win_w, X.win_h,
            (unsigned long)XVisualIDFromVisual(v), v->red_mask, v->green_mask, v->blue_mask);
    return 0;
}

static void gl_drop(struct egl_stern *e)
{
    if (X.edpy) {
        G.eglMakeCurrent(X.edpy, 0, 0, 0);
        if (X.ctx) G.eglDestroyContext(X.edpy, X.ctx);
        if (X.surf) G.eglDestroySurface(X.edpy, X.surf);
        G.eglTerminate(X.edpy);
        G.eglReleaseThread();
    }
    X.edpy = X.cfg = X.surf = X.ctx = NULL;
    e->dpy = e->cfg = e->surf = e->ctx = NULL;
}

/* EGL on the window: 0 ok, -1 = fall back to XImage */
static int gl_up(struct egl_stern *e)
{
    int maj = 0, min = 0, n = 0, i;
    void *cfgs[64];
    XID want;
    if (load_gl() < 0) return -1;
    setenv("EGL_PLATFORM", "x11", 0);          /* Mesa: this display pointer is Xlib's */
    X.edpy = G.eglGetDisplay(X.dpy);
    if (!X.edpy) { sel_log("egl: eglGetDisplay returned EGL_NO_DISPLAY"); return -1; }
    if (!G.eglInitialize(X.edpy, &maj, &min) || !egl_ok("eglInitialize")) return -1;
    sel_log("egl: initialised %d.%d", maj, min);
    if (!G.eglChooseConfig(X.edpy, cfg_attr, cfgs, 64, &n) || !egl_ok("eglChooseConfig") || n < 1) {
        sel_log("egl: eglChooseConfig gave %d configs", n);
        return -1;
    }
    /* the window was made with the default visual: take the config that
     * names it, or the first one and let Mesa say no */
    want = XVisualIDFromVisual(XDefaultVisual(X.dpy, X.screen));
    X.cfg = cfgs[0];
    for (i = 0; i < n; i++) {
        int vid = 0;
        if (G.eglGetConfigAttrib(X.edpy, cfgs[i], EGL_NATIVE_VISUAL_ID, &vid) && (XID)vid == want) {
            X.cfg = cfgs[i];
            break;
        }
    }
    sel_log("egl: %d configs, using %d (visual %s)", n, i < n ? i : 0, i < n ? "matched" : "first");
    X.surf = G.eglCreateWindowSurface(X.edpy, X.cfg, X.win, NULL);
    if (!X.surf || !egl_ok("eglCreateWindowSurface")) return -1;
    if (!G.eglBindAPI(EGL_OPENGL_ES_API) || !egl_ok("eglBindAPI")) return -1;
    X.ctx = G.eglCreateContext(X.edpy, X.cfg, NULL, ctx_attr);
    if (!X.ctx || !egl_ok("eglCreateContext")) return -1;
    if (!G.eglMakeCurrent(X.edpy, X.surf, X.surf, X.ctx) || !egl_ok("eglMakeCurrent")) return -1;
    G.eglSwapInterval(X.edpy, 1);
    G.glClearColor(0.f, 0.f, 0.f, 1.f);
    G.glClear(GL_COLOR_DEPTH_BITS);
    G.eglSwapBuffers(X.edpy, X.surf);
    G.glViewport(0, 0, X.win_w, X.win_h);
    G.glEnable(GL_BLEND);
    G.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    sel_log("egl: window %dx%d, GL_VERSION '%s' renderer '%s'", X.win_w, X.win_h,
            (const char *)G.glGetString(0x1F02), (const char *)G.glGetString(0x1F01));
    e->dpy = X.edpy; e->cfg = X.cfg; e->surf = X.surf; e->ctx = X.ctx;
    return 0;
}

static int build_program(struct egl_stern *e)
{
    unsigned vs, fs;
    int ok = 0;
    float m[16], q[24];
    float w = (float)X.win_w, h = (float)X.win_h;

    vs = G.glCreateShader(GL_VERTEX_SHADER);
    G.glShaderSource(vs, 1, &VS, NULL);
    G.glCompileShader(vs);
    G.glGetShaderiv(vs, GL_COMPILE_STATUS, &ok);
    if (!ok) { sel_log("egl: the vertex shader did not compile"); return -1; }
    fs = G.glCreateShader(GL_FRAGMENT_SHADER);
    G.glShaderSource(fs, 1, &FS, NULL);
    G.glCompileShader(fs);
    G.glGetShaderiv(fs, GL_COMPILE_STATUS, &ok);
    if (!ok) { sel_log("egl: the fragment shader did not compile"); return -1; }
    e->prog = G.glCreateProgram();
    G.glAttachShader(e->prog, vs);
    G.glAttachShader(e->prog, fs);
    G.glLinkProgram(e->prog);
    G.glGetProgramiv(e->prog, GL_LINK_STATUS, &ok);
    if (!ok) { sel_log("egl: the program did not link"); return -1; }
    G.glUseProgram(e->prog);
    /* ortho over the WINDOW: x 0..w, y 0..h top->bottom (column-major) */
    memset(m, 0, sizeof m);
    m[0] = 2.0f / w;
    m[5] = -2.0f / h;
    m[10] = -1.0f;
    m[12] = -1.0f;
    m[13] = 1.0f;
    m[15] = 1.0f;
    G.glUniformMatrix4fv(G.glGetUniformLocation(e->prog, "projection"), 1, 0, m);
    G.glUniform1i(G.glGetUniformLocation(e->prog, "image"), 0);
    G.glGenVertexArrays(1, &e->vao);
    G.glBindVertexArray(e->vao);
    G.glGenBuffers(1, &e->vbo);
    G.glBindBuffer(GL_ARRAY_BUFFER, e->vbo);
    {   /* the whole window, texcoords 0..1: the canvas scales to it */
        float t[24] = { 0, 0, 0, 0,   w, 0, 1, 0,   w, h, 1, 1,
                        0, 0, 0, 0,   w, h, 1, 1,   0, h, 0, 1 };
        memcpy(q, t, sizeof q);
    }
    G.glBufferData(GL_ARRAY_BUFFER, (long)sizeof q, q, GL_STATIC_DRAW);
    G.glVertexAttribPointer(0, 4, GL_FLOAT, 0, 4 * (int)sizeof(float), (const void *)0);
    G.glEnableVertexAttribArray(0);
    return 0;
}

/* the XImage path: a canvas-sized image in the server's pixel order, put
 * centred; 0 ok */
static int ximage_up(void)
{
    X.pix = calloc((size_t)CANVAS_W * CANVAS_H, 4);
    if (!X.pix) return -1;
    X.gc = XCreateGC(X.dpy, X.win, 0, NULL);
    X.img = XCreateImage(X.dpy, XDefaultVisual(X.dpy, X.screen), (unsigned)XDefaultDepth(X.dpy, X.screen),
                         ZPIXMAP, 0, (char *)X.pix, CANVAS_W, CANVAS_H, 32, CANVAS_W * 4);
    if (!X.img) { sel_log("x11: XCreateImage failed"); return -1; }
    X.ox = (X.win_w - CANVAS_W) / 2;
    X.oy = (X.win_h - CANVAS_H) / 2;
    if (X.ox < 0) X.ox = 0;
    if (X.oy < 0) X.oy = 0;
    sel_log("x11: XPutImage path, canvas %dx%d at %d,%d in the window", CANVAS_W, CANVAS_H, X.ox, X.oy);
    return 0;
}

/* RGBA rows (w*4 bytes each) -> the server's 32-bit words at x, y */
static void ximage_put(const unsigned char *rgba, int x, int y, int w, int h)
{
    int r, c;
    for (r = 0; r < h; r++) {
        const unsigned char *s = rgba + (size_t)r * w * 4;
        unsigned *d = (unsigned *)(X.pix + ((size_t)(y + r) * CANVAS_W + x) * 4);
        for (c = 0; c < w; c++, s += 4)
            d[c] = ((unsigned)s[0] << X.rsh) | ((unsigned)s[1] << X.gsh) | ((unsigned)s[2] << X.bsh);
    }
    XPutImage(X.dpy, X.win, X.gc, X.img, x, y, X.ox + x, X.oy + y, (unsigned)w, (unsigned)h);
}

int egl_stern_init(struct egl_stern *e, int retries, int retry_ms)
{
    int attempt;
    memset(e, 0, sizeof *e);
    e->w = CANVAS_W;
    e->h = CANVAS_H;
    if (retries < 1) retries = 1;
    for (attempt = 1; attempt <= retries; attempt++) {
        if (x_up() == 0) break;
        if (attempt < retries) {
            sel_log("x11: attempt %d/%d failed, retrying in %d ms", attempt, retries, retry_ms);
            sel_sleep_ms(retry_ms);
        }
    }
    if (!X.dpy) {
        sel_log("x11: giving up after %d attempts", retries);
        return -1;
    }
    if (gl_up(e) == 0 && build_program(e) == 0) {
        X.mode = 1;
        e->up = 1;
        sel_log("egl: up after %d attempt(s), glGetError=0x%x, canvas %dx%d scaled to %dx%d",
                attempt, G.glGetError(), CANVAS_W, CANVAS_H, X.win_w, X.win_h);
        return 0;
    }
    gl_drop(e);
    sel_log("egl: not available, drawing with XPutImage instead");
    if (ximage_up() < 0) return -1;
    X.mode = 2;
    e->up = 1;
    return 0;
}

int egl_stern_texture(struct egl_stern *e, int w, int h, const unsigned char *px)
{
    if (!e->up) return -1;
    e->tex_w = w;
    e->tex_h = h;
    if (X.mode == 2) {
        if (w > CANVAS_W) w = CANVAS_W;
        if (h > CANVAS_H) h = CANVAS_H;
        ximage_put(px, 0, 0, w, h);
        XFlush(X.dpy);
        return 0;
    }
    G.glActiveTexture(GL_TEXTURE0);
    G.glGenTextures(1, &e->tex);
    G.glBindTexture(GL_TEXTURE_2D, e->tex);
    G.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    G.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    G.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    G.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    G.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    sel_log("egl: texture %u %dx%d created, glGetError=0x%x", e->tex, w, h, G.glGetError());
    return 0;
}

void egl_stern_frame(struct egl_stern *e, const unsigned char *packed, int x, int y, int w, int h)
{
    if (!e->up) return;
    if (X.mode == 2) {
        /* only what changed goes to the server; nothing to do on a clean frame */
        if (packed && w > 0 && h > 0) {
            if (x + w > CANVAS_W) w = CANVAS_W - x;
            if (y + h > CANVAS_H) h = CANVAS_H - y;
            if (w > 0 && h > 0) {
                ximage_put(packed, x, y, w, h);
                e->uploaded += (long long)w * h * 4;
            }
            XFlush(X.dpy);
        }
        e->frames++;
        return;
    }
    G.glClearColor(0.f, 0.f, 0.f, 1.f);
    G.glClear(GL_COLOR_DEPTH_BITS);
    G.glBindTexture(GL_TEXTURE_2D, e->tex);
    if (packed && w > 0 && h > 0) {
        G.glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, packed);
        e->uploaded += (long long)w * h * 4;
    }
    G.glDrawArrays(GL_TRIANGLES, 0, 6);
    G.eglSwapBuffers(X.edpy, X.surf);
    e->frames++;
}

void egl_stern_close(struct egl_stern *e)
{
    if (!e->up) return;
    sel_log("%s: %d frames, %lld KB uploaded, closing (the LOADING frame stays up until the game draws)",
            X.mode == 1 ? "egl" : "x11", e->frames, e->uploaded / 1024);
    if (X.mode == 1) {
        /* the last frame is on the glass; the window is what the game replaces */
        gl_drop(e);
    } else {
        if (X.gc) XFreeGC(X.dpy, X.gc);
        if (X.img) XFree(X.img);        /* the pixel buffer is ours */
        free(X.pix);
        X.gc = X.img = NULL;
        X.pix = NULL;
    }
    /* THE WINDOW STAYS MAPPED: destroying it would show the root's black
     * until the game's first frame, seconds later.  The game maps its own
     * full-screen window over it, and this process exiting is what finally
     * takes it down (the server destroys a client's windows on close). */
    XFlush(X.dpy);
    e->up = 0;
    X.mode = 0;
}
