/* padglhost.c - native x86-64 renderer for the emulated game.
 *
 * Creates the shared ring, then decodes the GL command stream the guest stub
 * (glbridge.c) writes into it and replays it on a real GLES context via EGL.
 * Run it BEFORE the game; it creates the ring and waits.
 *
 *   gcc -O2 -o padglhost padglhost.c -l:libEGL.so.1
 *   GALLIUM_DRIVER=d3d12 ./padglhost /dev/shm/padgl     # GPU  (measured 914 fps)
 *   ./padglhost /dev/shm/padgl                          # llvmpipe (214 fps)
 *
 * GLES entry points come from eglGetProcAddress so libgles2 need not be
 * installed, and the game's own `#version 300 es` shaders are replayed
 * VERBATIM. Forwarding calls rather than reimplementing them is the whole
 * point: there is no translation layer here to get subtly wrong.
 *
 * Guest FBO 0 means "the screen". The host's real FBO 0 is a tiny pbuffer, so
 * guest 0 is redirected to a texture-backed FBO of the display size, which is
 * also what makes glReadPixels for frame dumps possible.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <signal.h>

#include "padgl.h"
#include "padvid.h"

typedef void *EGLDisplay, *EGLConfig, *EGLContext, *EGLSurface;
typedef int EGLint;
typedef unsigned int EGLenum, EGLBoolean;
extern EGLDisplay eglGetDisplay(void *);
extern EGLBoolean eglInitialize(EGLDisplay, EGLint *, EGLint *);
extern EGLBoolean eglChooseConfig(EGLDisplay, const EGLint *, EGLConfig *, EGLint, EGLint *);
extern EGLBoolean eglBindAPI(EGLenum);
extern EGLContext eglCreateContext(EGLDisplay, EGLConfig, EGLContext, const EGLint *);
extern EGLSurface eglCreatePbufferSurface(EGLDisplay, EGLConfig, const EGLint *);
extern EGLBoolean eglMakeCurrent(EGLDisplay, EGLSurface, EGLSurface, EGLContext);
extern void (*eglGetProcAddress(const char *))(void);
extern EGLint eglGetError(void);

static const unsigned char *(*p_glGetString)(unsigned);
static void (*p_glViewport)(int,int,int,int);
static void (*p_glScissor)(int,int,int,int);
static void (*p_glClearColor)(float,float,float,float);
static void (*p_glClear)(unsigned);
static void (*p_glEnable)(unsigned);
static void (*p_glDisable)(unsigned);
static void (*p_glBlendFunc)(unsigned,unsigned);
static void (*p_glBlendFuncSeparate)(unsigned,unsigned,unsigned,unsigned);
static void (*p_glBlendEquation)(unsigned);
static void (*p_glBlendEquationSeparate)(unsigned,unsigned);
static void (*p_glGenTextures)(int,unsigned*);
static void (*p_glDeleteTextures)(int,const unsigned*);
static void (*p_glBindTexture)(unsigned,unsigned);
static void (*p_glActiveTexture)(unsigned);
static void (*p_glTexImage2D)(unsigned,int,int,int,int,int,unsigned,unsigned,const void*);
static void (*p_glTexSubImage2D)(unsigned,int,int,int,int,int,unsigned,unsigned,const void*);
static void (*p_glCompressedTexImage2D)(unsigned,int,unsigned,int,int,int,int,const void*);
static void (*p_glTexParameteri)(unsigned,unsigned,int);
static void (*p_glGenBuffers)(int,unsigned*);
static void (*p_glDeleteBuffers)(int,const unsigned*);
static void (*p_glBindBuffer)(unsigned,unsigned);
static void (*p_glBufferData)(unsigned,long,const void*,unsigned);
static void (*p_glBufferSubData)(unsigned,long,long,const void*);
static void (*p_glGenVertexArrays)(int,unsigned*);
static void (*p_glBindVertexArray)(unsigned);
static void (*p_glVertexAttribPointer)(unsigned,int,unsigned,unsigned char,int,const void*);
static void (*p_glEnableVertexAttribArray)(unsigned);
static void (*p_glDisableVertexAttribArray)(unsigned);
static unsigned (*p_glCreateShader)(unsigned);
static void (*p_glShaderSource)(unsigned,int,const char*const*,const int*);
static void (*p_glCompileShader)(unsigned);
static void (*p_glGetShaderiv)(unsigned,unsigned,int*);
static void (*p_glGetShaderInfoLog)(unsigned,int,int*,char*);
static unsigned (*p_glCreateProgram)(void);
static void (*p_glAttachShader)(unsigned,unsigned);
static void (*p_glBindAttribLocation)(unsigned,unsigned,const char*);
static void (*p_glLinkProgram)(unsigned);
static void (*p_glGetProgramiv)(unsigned,unsigned,int*);
static void (*p_glGetProgramInfoLog)(unsigned,int,int*,char*);
static void (*p_glUseProgram)(unsigned);
static int  (*p_glGetUniformLocation)(unsigned,const char*);
static int  (*p_glGetAttribLocation)(unsigned,const char*);
static void (*p_glUniform1f)(int,float);
static void (*p_glUniform1i)(int,int);
static void (*p_glUniform2f)(int,float,float);
static void (*p_glUniform3f)(int,float,float,float);
static void (*p_glUniform4f)(int,float,float,float,float);
static void (*p_glUniform4fv)(int,int,const float*);
static void (*p_glUniformMatrix4fv)(int,int,unsigned char,const float*);
static void (*p_glGenFramebuffers)(int,unsigned*);
static void (*p_glBindFramebuffer)(unsigned,unsigned);
static void (*p_glFramebufferTexture2D)(unsigned,unsigned,unsigned,unsigned,int);
static unsigned (*p_glCheckFramebufferStatus)(unsigned);
static void (*p_glDrawArrays)(unsigned,int,int);
static void (*p_glDrawElements)(unsigned,int,unsigned,const void*);
static void (*p_glReadPixels)(int,int,int,int,unsigned,unsigned,void*);
static void (*p_glFinish)(void);
static unsigned (*p_glGetError)(void);
static void (*p_glGetIntegerv)(unsigned,int*);
static void (*p_glGetVertexAttribiv)(unsigned,unsigned,int*);

static void load_gl(void)
{
#define LOAD(n) do { *(void **)&p_##n = (void *)eglGetProcAddress(#n); \
        if (!p_##n) { fprintf(stderr, "padglhost: missing %s\n", #n); exit(1); } } while (0)
    LOAD(glGetString); LOAD(glViewport); LOAD(glScissor); LOAD(glClearColor);
    LOAD(glClear); LOAD(glEnable); LOAD(glDisable); LOAD(glBlendFunc);
    LOAD(glBlendFuncSeparate); LOAD(glBlendEquation); LOAD(glBlendEquationSeparate);
    LOAD(glGenTextures); LOAD(glDeleteTextures); LOAD(glBindTexture);
    LOAD(glActiveTexture); LOAD(glTexImage2D); LOAD(glTexSubImage2D);
    LOAD(glCompressedTexImage2D); LOAD(glTexParameteri);
    LOAD(glGenBuffers); LOAD(glDeleteBuffers); LOAD(glBindBuffer);
    LOAD(glBufferData); LOAD(glBufferSubData);
    LOAD(glGenVertexArrays); LOAD(glBindVertexArray); LOAD(glVertexAttribPointer);
    LOAD(glEnableVertexAttribArray); LOAD(glDisableVertexAttribArray);
    LOAD(glCreateShader); LOAD(glShaderSource); LOAD(glCompileShader);
    LOAD(glGetShaderiv); LOAD(glGetShaderInfoLog); LOAD(glCreateProgram);
    LOAD(glAttachShader); LOAD(glBindAttribLocation); LOAD(glLinkProgram);
    LOAD(glGetProgramiv); LOAD(glGetProgramInfoLog); LOAD(glUseProgram);
    LOAD(glGetUniformLocation); LOAD(glUniform1f); LOAD(glUniform1i);
    LOAD(glUniform2f); LOAD(glUniform3f); LOAD(glUniform4f); LOAD(glUniform4fv);
    LOAD(glUniformMatrix4fv); LOAD(glGenFramebuffers); LOAD(glBindFramebuffer);
    LOAD(glFramebufferTexture2D); LOAD(glCheckFramebufferStatus);
    LOAD(glDrawArrays); LOAD(glDrawElements); LOAD(glReadPixels);
    LOAD(glFinish); LOAD(glGetError); LOAD(glGetIntegerv);
    LOAD(glGetVertexAttribiv); LOAD(glGetAttribLocation);
#undef LOAD
}

/* ---- guest name -> real GL name ---- */
#define MAXNAME 4096
#define MAXPROG 128
#define MAXUNI  32
static unsigned map_tex[MAXNAME], map_buf[MAXNAME], map_obj[MAXNAME];
static unsigned map_vao[1024], map_fbo[256];
static int  uni_loc[MAXPROG][MAXUNI];
static char uni_name[MAXPROG][MAXUNI][40];
static int  attr_loc[MAXPROG][PADGL_ATTR_PER_PROG];
static char attr_name[MAXPROG][PADGL_ATTR_PER_PROG][40];
static void (*p_glGetAttribLocation_fwd)(void);

/* Below the token base the value is a real index the shader fixed with a
 * layout qualifier; at or above it, it is (program, slot) to resolve by name. */
static int attr_resolve(unsigned tok)
{
    unsigned g, slot;
    if (tok < PADGL_ATTR_TOKEN_BASE) return (int)tok;
    tok -= PADGL_ATTR_TOKEN_BASE;
    g = tok / PADGL_ATTR_PER_PROG;
    slot = tok % PADGL_ATTR_PER_PROG;
    if (g >= MAXPROG || slot >= PADGL_ATTR_PER_PROG) return -1;
    return attr_loc[g][slot];
}

static char *shader_src[MAXNAME];
static unsigned long shader_len[MAXNAME];

static padgl_hdr *hdr;
static unsigned char *ring;
static unsigned int ring_bytes;
static int fb_w = 1920, fb_h = 1080;
static unsigned fbo_screen, tex_screen;
static volatile int stop_now;
static long frames_done;
static const char *dump_dir;
static int dump_every = 30, dump_max = 40, dumped;
static long unknown_ops;
static int  dbg;
/* Which frames PADGL_DEBUG=3 dumps op-by-op. Fixed at 60..62 originally, which
 * only ever showed the steady state; the splash lives in the first few frames,
 * so the window has to be movable to compare the two. */
static long seq_from = 60, seq_to = 62;
static unsigned cur_tex_unit_binding;
static unsigned char min_filter_set[MAXNAME];

/* ---- video: the other half of PADGL_TEXDIRECT ---------------------------
 *
 * The guest normally sends only a byte offset, because the frame is already in
 * the block padvidhost.py decodes into and this process can open it too. That
 * keeps 1.5 MB per frame out of the emulated guest AND out of the GL ring; the
 * inline form exists only as a fallback for a pointer that is not in the ring.
 */
static const unsigned char *vid_ring;
static long vid_texdirect, vid_dropped;

static void vid_open(void)
{
    static int tried;
    const char *path;
    int fd;
    void *p;
    if (vid_ring || tried) return;
    tried = 1;
    path = getenv("PAD_VID_SHM");
    if (!path || !*path) return;
    fd = open(path, O_RDONLY);
    if (fd < 0) { fprintf(stderr, "[padglhost] no video block at %s\n", path); return; }
    p = mmap(0, PADVID_BYTES, PROT_READ, MAP_SHARED, fd, 0);
    close(fd);
    if (p == MAP_FAILED) { fprintf(stderr, "[padglhost] video mmap failed\n"); return; }
    if (((const struct padvid_shm *)p)->magic != PADVID_MAGIC) {
        fprintf(stderr, "[padglhost] video block has the wrong magic\n");
        munmap(p, PADVID_BYTES);
        return;
    }
    if (((const struct padvid_shm *)p)->version != PADVID_VERSION) {
        fprintf(stderr, "[padglhost] video block is version %u, this build "
                "wants %u - restart padvidhost.py\n",
                ((const struct padvid_shm *)p)->version, PADVID_VERSION);
        munmap(p, PADVID_BYTES);
        return;
    }
    vid_ring = (const unsigned char *)p + PADVID_HDR;
    fprintf(stderr, "[padglhost] video block attached: %s\n", path);
}

/* I420 -> RGBA, BT.601 limited range, which is what the Vivante texture unit
 * does for GL_VIV_I420 on the real machine. Integer, 8-bit fixed point; the Y
 * term is a table because it is the only one indexed by every pixel. */
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

static void on_signal(int s) { (void)s; stop_now = 1; }
static double now_s(void)
{ struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }

static void ring_get(unsigned long long at, void *dst, unsigned int n)
{
    unsigned int off = (unsigned int)(at % ring_bytes);
    unsigned int first = ring_bytes - off;
    if (n <= first) memcpy(dst, ring + off, n);
    else { memcpy(dst, ring + off, first);
           memcpy((unsigned char *)dst + first, ring, n - first); }
}

/* ---- live window (PAD_GL_WINDOW=1) --------------------------------------
 *
 * The host already renders the game at 60 fps into tex_screen; it just never
 * put it on a screen. This section adds a real X11 window and an EGL window
 * surface so the emulator can be WATCHED. Under WSLg an X11 window from this
 * distro is a normal window on the Windows desktop, so no extra plumbing is
 * needed on the Windows side.
 *
 * No dev packages are installed and there are no X11/EGL headers on this box,
 * so every entry point is hand-declared, exactly as the EGL ones above already
 * are, and the link uses -l:libX11.so.6 (plain -lX11 would fail: there is no
 * libX11.so dev symlink).
 *
 * TRAPS, all of them verified on this machine rather than assumed:
 *  - DefaultScreen()/RootWindow()/BlackPixel() are MACROS in Xlib.h. A build
 *    without headers must call the exported function forms XDefaultScreen(),
 *    XRootWindow(), XBlackPixel(), which really are exported by libX11.so.6.
 *  - eglCreateWindowSurface takes the X Window XID BY VALUE (unsigned long),
 *    not a pointer to it.
 *  - the EGL config must ask for EGL_WINDOW_BIT; the old config asked for
 *    EGL_PBUFFER_BIT only.
 *  - sizeof(XEvent) is 192 here, so events are read into an over-allocated
 *    buffer and only offsets confirmed on this box are read back out.
 */
typedef struct XDisplay XDisplay;
extern XDisplay *XOpenDisplay(const char *);
extern int XCloseDisplay(XDisplay *);
extern int XDefaultScreen(XDisplay *);
extern unsigned long XRootWindow(XDisplay *, int);
extern unsigned long XBlackPixel(XDisplay *, int);
extern unsigned long XCreateSimpleWindow(XDisplay *, unsigned long, int, int,
                                         unsigned int, unsigned int,
                                         unsigned int, unsigned long, unsigned long);
extern int XStoreName(XDisplay *, unsigned long, const char *);
extern int XSelectInput(XDisplay *, unsigned long, long);
extern int XMapWindow(XDisplay *, unsigned long);
extern int XDestroyWindow(XDisplay *, unsigned long);
extern unsigned long XInternAtom(XDisplay *, const char *, int);
extern int XSetWMProtocols(XDisplay *, unsigned long, unsigned long *, int);
extern int XPending(XDisplay *);
extern int XNextEvent(XDisplay *, void *);
extern int XFlush(XDisplay *);

extern EGLSurface eglCreateWindowSurface(EGLDisplay, EGLConfig, unsigned long, const EGLint *);
extern EGLBoolean eglSwapBuffers(EGLDisplay, EGLSurface);
extern EGLBoolean eglSwapInterval(EGLDisplay, EGLint);
extern EGLBoolean eglQuerySurface(EGLDisplay, EGLSurface, EGLint, EGLint *);

/* The EGL display and the surface we present to. These were locals in main();
 * win_present() needs them, so they are file scope now. */
static EGLDisplay egl_dpy;
static EGLSurface egl_surf;

static int win_on;                       /* PAD_GL_WINDOW=1                  */
static XDisplay *xdpy;
static unsigned long xwin, wm_delete;
static int win_w, win_h;                 /* current drawable size            */
static int win_flip;                     /* 0 = correct here; see win_present() */
static int win_every = 1;                /* present every Nth frame          */
static unsigned blit_prog, blit_vao;
static int blit_tex_loc = -1;

static const char *BLIT_VS =
    "#version 300 es\n"
    "out vec2 v_uv;\n"
    "void main(){\n"
    "  float x = float(gl_VertexID & 1);\n"
    "  float y = float((gl_VertexID >> 1) & 1);\n"
    "  v_uv = vec2(x, y);\n"
    "  gl_Position = vec4(x * 2.0 - 1.0, y * 2.0 - 1.0, 0.0, 1.0);\n"
    "}\n";
static const char *BLIT_FS =
    "#version 300 es\n"
    "precision mediump float;\n"
    "uniform sampler2D u_tex;\n"
    "uniform float u_flip;\n"
    "in vec2 v_uv;\n"
    "out vec4 o_col;\n"
    "void main(){\n"
    "  vec2 uv = vec2(v_uv.x, mix(v_uv.y, 1.0 - v_uv.y, u_flip));\n"
    "  o_col = vec4(texture(u_tex, uv).rgb, 1.0);\n"
    "}\n";

/* ---- keyboard -> switches, and the legend window ------------------------
 *
 * This process is the only one that can see a key press: it owns the X11
 * window, while the switches live in an ARM library inside the emulated game.
 * The two talk through a small shared file (padsw.h), the same host-path /
 * guest-path trick the GL ring already uses.
 *
 * Everything is declared by hand as elsewhere in this file - there are no X11
 * headers on this box. The XKeyEvent offsets were derived the same way the
 * ClientMessage one was and cross-check against it: type 0, serial 8,
 * send_event 16, display 24, window 32, root 40, subwindow 48, time 56, x 64,
 * y 68, x_root 72, y_root 76, state 80, KEYCODE 84.
 *
 * AUTO-REPEAT is the one real trap. X delivers a held key as an endless
 * Press/Release/Press/Release stream, so a naive handler releases the flipper
 * ~30 times a second while you are holding it down. The fix is the standard
 * peek: a KeyRelease immediately followed by a KeyPress of the same keycode at
 * the same timestamp is a repeat, not a release, so both are swallowed.
 */
#include "padsw.h"

typedef void *XGC;
extern XGC XCreateGC(XDisplay *, unsigned long, unsigned long, void *);
extern int XSetForeground(XDisplay *, XGC, unsigned long);
extern int XDrawString(XDisplay *, unsigned long, XGC, int, int, const char *, int);
extern int XFillRectangle(XDisplay *, unsigned long, XGC, int, int, unsigned, unsigned);
extern int XClearWindow(XDisplay *, unsigned long);
extern unsigned long XWhitePixel(XDisplay *, int);
extern unsigned long XLoadFont(XDisplay *, const char *);
extern int XSetFont(XDisplay *, XGC, unsigned long);
extern int XMoveWindow(XDisplay *, unsigned long, int, int);
extern int XGetGeometry(XDisplay *, unsigned long, unsigned long *, int *, int *,
                        unsigned *, unsigned *, unsigned *, unsigned *);
extern int XTranslateCoordinates(XDisplay *, unsigned long, unsigned long,
                                 int, int, int *, int *, unsigned long *);

extern int XPeekEvent(XDisplay *, void *);
extern unsigned long XLookupKeysym(void *, int);
extern void *XSetErrorHandler(void *);

/* WM_NORMAL_HINTS, so a remembered window position actually takes. An
 * XMoveWindow issued right after XMapWindow LOSES to the window manager's own
 * initial placement under WSLg - the game window got away with it by timing,
 * the Controls window measurably did not (.pad_windows said 941,930 and the
 * window opened at the default anyway). The X way to place a window is to
 * CREATE it at the position and say so in the size hints BEFORE mapping;
 * USPosition is the flag WMs treat as "the user chose this, respect it". */
typedef struct {
    long flags;
    int x, y;
    int width, height;
    int min_width, min_height;
    int max_width, max_height;
    int width_inc, height_inc;
    struct { int x, y; } min_aspect, max_aspect;
    int base_width, base_height;
    int win_gravity;
} XSizeHints;
#define PAD_USPosition (1L << 0)
#define PAD_PPosition  (1L << 1)
extern void XSetWMNormalHints(XDisplay *, unsigned long, XSizeHints *);

static void win_place(unsigned long w, int x, int y)
{
    XSizeHints h;
    int i;
    for (i = 0; i < (int)sizeof h; i++) ((char *)&h)[i] = 0;
    h.flags = PAD_USPosition | PAD_PPosition;
    h.x = x; h.y = y;
    XSetWMNormalHints(xdpy, w, &h);
}

/* An X protocol error must never be fatal here: the default handler EXITS, so
 * one unavailable font name would otherwise take the emulator down with it. */
static int x_swallow_error(void *dpy, void *err) { (void)dpy; (void)err; return 0; }

struct keybind {
    unsigned long sym;
    const char   *key;      /* as shown in the legend */
    const char   *what;
    short         ids[7];   /* 0-terminated list of switch ids */
    int           toggle;   /* 1 = latching, for things you hold for minutes */
    int           live;     /* 0 = bound, but the game cannot see it yet */
};

/* Ids are the game own switch ids, straight out of its table (PAD_SW_MAP).
 *
 * `live` is not decoration. The CABINET switches (node 0) are read continuously
 * as the RX half of an SPI transfer, so they work. The PLAYFIELD switches come
 * over the node bus as command 0x11, and the game currently sends that exactly
 * ONCE per board per run - the service loop call to 0x1d6d94 is gated on
 * board[+4] bit 0, which nothing has been seen to set. Until that is found the
 * playfield keys are inert, and saying so on screen beats letting someone
 * conclude the whole channel is broken because the flippers do nothing. */
static struct keybind binds[] = {
    { 0xff0d, "Enter",  "Service Select",      { 25, 0 }, 0, 1 },
    { 0xff8d, "KP Ent", "Service Select",      { 25, 0 }, 0, 1 },
    { 0x003d, "=",      "Service Plus",        { 26, 0 }, 0, 1 },
    { 0x002d, "-",      "Service Minus",       { 27, 0 }, 0, 1 },
    { 0xff08, "Bksp",   "Service Back",        { 28, 0 }, 0, 1 },
    { 0xff1b, "Esc",    "Service Back",        { 28, 0 }, 0, 1 },
    { 0x0031, "1",      "Start Button",        { 36, 0 }, 0, 1 },
    { 0x0035, "5",      "Left Coin",           { 39, 0 }, 0, 1 },
    { 0x0020, "Space",  "Action Button",       { 34, 0 }, 0, 1 },
    { 0x0074, "T",      "Tilt Pendulum",       { 38, 0 }, 0, 1 },
    { 0x0063, "C",      "Coin Door Closed",    { 33, 0 }, 1, 1 },
    { 0xff51, "Left",   "Left Flipper",        { 60, 0 }, 0, 0 },
    { 0xff53, "Right",  "Right Flipper",       { 59, 0 }, 0, 0 },
    { 0xff52, "Up",     "Upper Left Flipper",  { 61, 0 }, 0, 0 },
    { 0x0066, "F",      "Shooter Lane",        { 62, 0 }, 0, 0 },
    { 0x0071, "Q",      "Skill Shot",          { 46, 0 }, 0, 0 },
    { 0x0077, "W",      "Left Spinner",        { 47, 0 }, 0, 0 },
    { 0x0065, "E",      "Pop Bumper",          { 49, 0 }, 0, 0 },
    { 0x0072, "R",      "Godzilla Target",     { 76, 0 }, 0, 0 },
    { 0x0061, "A",      "Left Slingshot",      { 64, 0 }, 0, 0 },
    { 0x0073, "S",      "Right Slingshot",     { 63, 0 }, 0, 0 },
    { 0x0064, "D",      "Right Scoop",         { 53, 0 }, 0, 0 },
    { 0x007a, "Z",      "Left Outlane",        { 55, 0 }, 0, 0 },
    { 0x0078, "X",      "Right Outlane",       { 58, 0 }, 0, 0 },
    { 0x0067, "G",      "Right Spinner",       { 84, 0 }, 0, 0 },
    { 0x0062, "B",      "6 balls in trough",   { 66, 67, 68, 69, 70, 71, 0 }, 1, 0 },
};
#define NBINDS ((int)(sizeof binds / sizeof binds[0]))

static struct padsw_shm *swshm;
static unsigned char key_down[NBINDS];      /* momentary keys currently held */
static unsigned char key_latch[NBINDS];     /* toggles currently latched     */
static unsigned long legend_win;
static XGC legend_gc;
static int legend_dirty = 1;

/* ---- WINDOW POSITIONS, REMEMBERED ---------------------------------------
 *
 * Both windows come back where they were left. The file is one line per
 * window in the user's home, not in the rig directory, because it is
 * per-machine state rather than part of the rig.
 *
 * The position has to be read with XTranslateCoordinates against the root
 * rather than XGetGeometry alone: under a reparenting window manager - and
 * WSLg is one - XGetGeometry returns coordinates relative to the frame the WM
 * wrapped around the window, which is 0,0 however far across the screen the
 * window actually is. */
#define WINPOS_PATH_MAX 512
static char winpos_path[WINPOS_PATH_MAX];

static const char *winpos_file(void)
{
    const char *home;
    if (winpos_path[0]) return winpos_path;
    home = getenv("HOME");
    snprintf(winpos_path, sizeof winpos_path, "%s/.pad_windows",
             home && *home ? home : "/tmp");
    return winpos_path;
}

static int winpos_get(const char *key, int *x, int *y)
{
    char line[160], k[64];
    FILE *f = fopen(winpos_file(), "r");
    int gx, gy, hit = 0;
    if (!f) return 0;
    while (fgets(line, sizeof line, f))
        if (sscanf(line, "%63s %d %d", k, &gx, &gy) == 3 && !strcmp(k, key)) {
            *x = gx; *y = gy; hit = 1;
        }
    fclose(f);
    return hit;
}

static void winpos_put(const char *key, int x, int y)
{
    char line[160], k[64];
    char keep[8][160];
    int n = 0, gx, gy, i;
    FILE *f = fopen(winpos_file(), "r");
    if (f) {
        while (n < 8 && fgets(line, sizeof line, f))
            if (sscanf(line, "%63s %d %d", k, &gx, &gy) == 3 && strcmp(k, key))
                snprintf(keep[n++], sizeof keep[0], "%s %d %d\n", k, gx, gy);
        fclose(f);
    }
    f = fopen(winpos_file(), "w");
    if (!f) return;
    for (i = 0; i < n; i++) fputs(keep[i], f);
    fprintf(f, "%s %d %d\n", key, x, y);
    fclose(f);
}

/* Absolute position of a window on the root, reparenting WM and all. */
static int winpos_read(unsigned long w, int *x, int *y)
{
    unsigned long root_ret, child;
    int rx, ry;
    unsigned uw, uh, bw, depth;
    if (!w) return 0;
    if (!XGetGeometry(xdpy, w, &root_ret, &rx, &ry, &uw, &uh, &bw, &depth))
        return 0;
    if (!XTranslateCoordinates(xdpy, w, root_ret, 0, 0, x, y, &child)) return 0;
    return 1;
}

static void winpos_save_all(void)
{
    int x, y;
    if (!xdpy) return;
    if (xwin && winpos_read(xwin, &x, &y)) winpos_put("game", x, y);
    if (legend_win && winpos_read(legend_win, &x, &y)) winpos_put("legend", x, y);
}

/* Recompute held[] from scratch and publish. Rebuilding rather than patching
 * incrementally means two keys bound to the same switch cannot leave it stuck
 * on when only one of them is released. */
static void sw_publish(void)
{
    unsigned char h[PADSW_MAX_ID];
    int i, j;
    legend_dirty = 1;
    if (!swshm) return;
    memset(h, 0, sizeof h);
    for (i = 0; i < NBINDS; i++) {
        if (!(binds[i].toggle ? key_latch[i] : key_down[i])) continue;
        for (j = 0; binds[i].ids[j]; j++)
            if (binds[i].ids[j] < PADSW_MAX_ID) h[binds[i].ids[j]] = 1;
    }
    memcpy(swshm->held, h, sizeof h);
    __sync_synchronize();
    swshm->gen++;
}

static void sw_shm_open(void)
{
    const char *path = getenv("PAD_SW_SHM");
    int fd;
    if (!path || !*path) return;
    fd = open(path, O_RDWR | O_CREAT, 0666);
    if (fd < 0) {
        fprintf(stderr, "[padglhost] switch shm %s: open failed\n", path);
        return;
    }
    if (ftruncate(fd, PADSW_BYTES) != 0) { close(fd); return; }
    swshm = mmap(0, PADSW_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (swshm == MAP_FAILED) { swshm = 0; return; }
    memset(swshm, 0, PADSW_BYTES);
    swshm->magic = PADSW_MAGIC;
    __sync_synchronize();
    swshm->gen = 1;
    fprintf(stderr, "[padglhost] keyboard -> switches via %s\n", path);
}

static void legend_open(int scr)
{
    unsigned long f;
    /* Beside the game by default, but back where it was left if it has been
     * moved before. The position must be set BEFORE the map (create at it,
     * then say so in WM_NORMAL_HINTS): the old move-after-map lost the race
     * with WSLg's window manager every time, which is exactly "the Controls
     * window does not remember its position". See win_place(). */
    int lx = win_w + 16, ly = 0;
    winpos_get("legend", &lx, &ly);
    legend_win = XCreateSimpleWindow(xdpy, XRootWindow(xdpy, scr),
                                     lx, ly, 430,
                                     (unsigned)(NBINDS * 20 + 124), 0,
                                     XBlackPixel(xdpy, scr), XBlackPixel(xdpy, scr));
    win_place(legend_win, lx, ly);
    XStoreName(xdpy, legend_win, "Controls - Spike 2 emulator");
    /* KeyPress | KeyRelease | Exposure | StructureNotify. Keys are selected on
     * this window too, so whichever of the two has focus can drive the game. */
    XSelectInput(xdpy, legend_win, 1L | 2L | (1L << 15) | (1L << 17));
    XSetWMProtocols(xdpy, legend_win, &wm_delete, 1);
    XMapWindow(xdpy, legend_win);
    legend_gc = XCreateGC(xdpy, legend_win, 0, 0);
    /* Any of these may be absent; the error handler makes that harmless and the
     * server default font still draws. */
    if ((f = XLoadFont(xdpy, "9x15bold"))) XSetFont(xdpy, legend_gc, f);
    else if ((f = XLoadFont(xdpy, "9x15"))) XSetFont(xdpy, legend_gc, f);
    else if ((f = XLoadFont(xdpy, "fixed"))) XSetFont(xdpy, legend_gc, f);
}

static void legend_draw(int scr)
{
    unsigned long white = XWhitePixel(xdpy, scr);
    unsigned long black = XBlackPixel(xdpy, scr);
    int i, y;
    if (!legend_win || !legend_gc) return;
    XClearWindow(xdpy, legend_win);
    XSetForeground(xdpy, legend_gc, white);
    XDrawString(xdpy, legend_win, legend_gc, 12, 26, "KEYBOARD -> SWITCHES", 20);
    XDrawString(xdpy, legend_win, legend_gc, 12, 46,
                "click a window first. B and C latch.", 36);
    XDrawString(xdpy, legend_win, legend_gc, 12, 74, "CABINET - these work:", 21);
    for (i = 0; i < NBINDS; i++) {
        int on = binds[i].toggle ? key_latch[i] : key_down[i];
        char line[96];
        int n;
        y = 94 + i * 20 + (binds[i].live ? 0 : 28);
        if (i && !binds[i].live && binds[i - 1].live) {
            XSetForeground(xdpy, legend_gc, white);
            XDrawString(xdpy, legend_win, legend_gc, 12, y - 20,
                        "PLAYFIELD - live, may stick:", 28);
        }
        n = snprintf(line, sizeof line, "%-7s %s%s", binds[i].key, binds[i].what,
                     binds[i].toggle ? (on ? "  [ON]" : "  [off]") : "");
        if (n > (int)sizeof line - 1) n = (int)sizeof line - 1;
        if (on) {
            XSetForeground(xdpy, legend_gc, white);
            XFillRectangle(xdpy, legend_win, legend_gc, 6, y - 14, 418, 18);
            XSetForeground(xdpy, legend_gc, black);
        } else {
            XSetForeground(xdpy, legend_gc, white);
        }
        XDrawString(xdpy, legend_win, legend_gc, 12, y, line, n);
    }
    XFlush(xdpy);
    legend_dirty = 0;
}

/* Returns the bind index for a keysym, or -1. */
static int bind_for(unsigned long sym)
{
    int i;
    for (i = 0; i < NBINDS; i++) if (binds[i].sym == sym) return i;
    return -1;
}

/* Opens the window. Called BEFORE eglGetDisplay so the EGL display can be the
 * X display, and before eglChooseConfig so the config can be window-capable.
 * Returns 0 and leaves win_on clear if anything fails, so a broken or absent
 * X server degrades to the old headless behaviour instead of killing the run. */
static int win_open(void)
{
    const char *t = getenv("PAD_GL_WINDOW");
    char *e;
    int scr;
    if (!t || t[0] != '1') return 0;
    if ((e = getenv("PAD_GL_FLIP")))     win_flip  = e[0] == '1';
    if ((e = getenv("PAD_GL_WIN_EVERY")) && atoi(e) > 0) win_every = atoi(e);

    xdpy = XOpenDisplay(0);
    if (!xdpy) {
        fprintf(stderr, "[padglhost] PAD_GL_WINDOW=1 but XOpenDisplay failed "
                        "(DISPLAY=%s); staying headless\n",
                getenv("DISPLAY") ? getenv("DISPLAY") : "(unset)");
        return 0;
    }
    scr  = XDefaultScreen(xdpy);
    win_w = fb_w; win_h = fb_h;
    {   /* Reopen where the window was last closed. The position has to be on
         * the window BEFORE it is mapped (create + WM_NORMAL_HINTS): a move
         * issued after the map races the window manager's initial placement,
         * and under WSLg the WM wins. */
        int gx = 0, gy = 0;
        winpos_get("game", &gx, &gy);
        xwin = XCreateSimpleWindow(xdpy, XRootWindow(xdpy, scr), gx, gy,
                                   (unsigned)win_w, (unsigned)win_h, 0,
                                   XBlackPixel(xdpy, scr), XBlackPixel(xdpy, scr));
        win_place(xwin, gx, gy);
    }
    /* THE TITLE NAMES THE TITLE. It used to say "Godzilla Pro" whatever was
     * running, which is merely untidy until you are looking at a screenshot of
     * a TMNT boot with Godzilla in the title bar and trying to work out which
     * game you are debugging. PAD_GAME is the rig's name for the directory
     * under games/; watch.sh always sets it. */
    {
        static char title[160];
        const char *g = getenv("PAD_GAME");
        snprintf(title, sizeof title, "%s - Stern Spike 2 emulator",
                 (g && *g) ? g : "Spike 2");
        XStoreName(xdpy, xwin, title);
    }
    /* StructureNotifyMask (1<<17) gives ConfigureNotify for resizes;
     * KeyPressMask (1) and KeyReleaseMask (2) are what make the keyboard work. */
    XSelectInput(xdpy, xwin, (1L << 17) | 1L | 2L);
    wm_delete = XInternAtom(xdpy, "WM_DELETE_WINDOW", 0);
    XSetWMProtocols(xdpy, xwin, &wm_delete, 1);
    XMapWindow(xdpy, xwin);
    XFlush(xdpy);
    win_on = 1;

    /* Keyboard -> switches. Both are optional: without PAD_SW_SHM the window
     * still works exactly as before, it just cannot press anything. */
    XSetErrorHandler((void *)x_swallow_error);
    sw_shm_open();
    /* The LATCHING switches start ON, because that is a machine at rest: the
     * coin door is shut - otherwise the game draws "* 48V DISABLED *" across
     * the top of the screen and will not fire a coil - and six balls are
     * sitting in the trough. Both are things you hold for minutes at a time,
     * which is why they are toggles at all. Press C or B for the other state. */
    {
        int i;
        for (i = 0; i < NBINDS; i++) if (binds[i].toggle) key_latch[i] = 1;
    }
    sw_publish();
    if (getenv("PAD_GL_LEGEND") == 0 || getenv("PAD_GL_LEGEND")[0] != '0')
        legend_open(scr);
    fprintf(stderr, "[padglhost] window opened %dx%d on DISPLAY=%s\n",
            win_w, win_h, getenv("DISPLAY") ? getenv("DISPLAY") : "?");
    return 1;
}

static unsigned blit_shader(unsigned type, const char *src)
{
    unsigned s = p_glCreateShader(type);
    int ok = 0;
    p_glShaderSource(s, 1, &src, 0);
    p_glCompileShader(s);
    p_glGetShaderiv(s, 0x8B81, &ok);          /* COMPILE_STATUS */
    if (!ok) {
        char log[1024];
        p_glGetShaderInfoLog(s, sizeof log, 0, log);
        fprintf(stderr, "[padglhost] blit shader failed:\n%s\n", log);
    }
    return s;
}

/* Builds the one program that copies tex_screen to the window. Must run with
 * the context already current. */
static void win_init_gl(void)
{
    int ok = 0;
    if (!win_on) return;
    blit_prog = p_glCreateProgram();
    p_glAttachShader(blit_prog, blit_shader(0x8B31, BLIT_VS));   /* VERTEX   */
    p_glAttachShader(blit_prog, blit_shader(0x8B30, BLIT_FS));   /* FRAGMENT */
    p_glLinkProgram(blit_prog);
    p_glGetProgramiv(blit_prog, 0x8B82, &ok);                    /* LINK_STATUS */
    if (!ok) { fprintf(stderr, "[padglhost] blit program link FAILED\n"); win_on = 0; return; }
    blit_tex_loc = p_glGetUniformLocation(blit_prog, "u_tex");
    p_glGenVertexArrays(1, &blit_vao);
}

/* X events. Closing the window sets stop_now, which is the same clean stop the
 * SIGINT handler uses, so the shutdown path is shared and already proven. */
static void win_pump(void)
{
    /* sizeof(XEvent) is 192 on this LP64 build; 256 bytes is a safe
     * over-allocation. A union rather than casts because reading the same
     * bytes as int and as unsigned long through pointer casts is a
     * strict-aliasing violation that -O2 is entitled to miscompile. */
    union { long l[32]; unsigned long ul[32]; int i[64]; } ev;
    if (!win_on) return;
    while (XPending(xdpy) > 0) {
        XNextEvent(xdpy, &ev);
        switch (ev.i[0]) {
        case 33:                       /* ClientMessage */
            /* data.l[0] is at byte 56 = index 7, verified on this box. */
            if (ev.ul[7] == wm_delete) {
                fprintf(stderr, "[padglhost] window closed; stopping\n");
                /* The last position save was up to 1 s ago (the throttle), so
                 * the final resting spot of a drag could be lost. This runs
                 * BEFORE watch.sh starts killing anything, so unlike a save
                 * at exit it actually lands on disk. */
                winpos_save_all();
                stop_now = 1;
            }
            break;
        case 17:                       /* DestroyNotify */
            /* Belt and braces: a window manager that tears the window down
             * without going through WM_DELETE_WINDOW would otherwise leave the
             * host rendering into a dead surface forever, which is exactly the
             * orphan-at-full-CPU state this rig has to avoid. Note UnmapNotify
             * is deliberately NOT treated as a close - that also fires on
             * minimise, and minimising should not kill the emulator. */
            fprintf(stderr, "[padglhost] window destroyed; stopping\n");
            stop_now = 1;
            break;
        case 22:                       /* ConfigureNotify: width/height ints at 56/60 */
            /* The GAME window drives the drawable size; the legend window
             * resizing must not be mistaken for it. */
            if (ev.ul[4] == xwin) { win_w = ev.i[14]; win_h = ev.i[15]; }
            /* SAVE THE POSITION HERE, not at exit. Saving on shutdown does not
             * survive contact with watch.sh, which SIGINTs and then SIGKILLs a
             * second later - measured: the file was never written. A window
             * move always produces this event, so recording it here is both
             * more robust and always current. Throttled, because dragging a
             * window produces a ConfigureNotify per pixel. */
            {
                static double last_saved;
                double now = now_s();
                if (now - last_saved > 1.0) { last_saved = now; winpos_save_all(); }
            }
            break;
        case 12:                       /* Expose */
            legend_dirty = 1;
            break;
        case 2:                        /* KeyPress   */
        case 3: {                      /* KeyRelease */
            int press = ev.i[0] == 2;
            unsigned kc = (unsigned)ev.i[21];
            unsigned long t = ev.ul[7];
            int b;
            /* Auto-repeat arrives as Release immediately followed by Press of
             * the same key at the same timestamp. Swallow both: the key is
             * still down, and treating it as a release makes a held flipper
             * flutter 30 times a second. */
            if (!press && XPending(xdpy) > 0) {
                union { long l[32]; unsigned long ul[32]; int i[64]; } nx;
                XPeekEvent(xdpy, &nx);
                if (nx.i[0] == 2 && (unsigned)nx.i[21] == kc && nx.ul[7] == t) {
                    XNextEvent(xdpy, &nx);
                    break;
                }
            }
            b = bind_for(XLookupKeysym(&ev, 0));
            if (b < 0) break;
            if (binds[b].toggle) {
                if (press) { key_latch[b] = !key_latch[b]; sw_publish(); }
            } else if (key_down[b] != (unsigned char)press) {
                key_down[b] = (unsigned char)press;
                sw_publish();
            }
            break;
        }
        default: break;
        }
    }
    if (legend_dirty) legend_draw(XDefaultScreen(xdpy));
}

/* Copies the finished frame to the window, letterboxed to preserve the game's
 * aspect ratio.
 *
 * Everything this touches is saved and restored, because the guest's GL state
 * machine keeps running straight after the swap and would otherwise find its
 * program, texture, VAO, viewport and enables silently changed. The existing
 * dump path gets away with re-binding the framebuffer only because the guest
 * re-binds one every frame anyway; a blit is not that forgiving.
 *
 * Y FLIP: none is needed, and the reason is worth writing down because the
 * plausible-sounding argument for flipping is wrong. tex_screen holds the frame
 * in ordinary GL orientation - texel row 0 is the BOTTOM of the picture - so
 * sampling V straight from the quad's Y is already right. The PNG dumps look
 * the right way up not because the framebuffer is Y-down but because write_png
 * flips them itself, at `row = rgba + (h - 1 - i) * w * 4`. Reasoning from "the
 * PNGs come out correct" to "the texture must be Y-down" skips that line and
 * produces an upside-down window, which is exactly what the first version did.
 * PAD_GL_FLIP=1 forces the flip back on if a future backend changes this. */
static void win_present(void)
{
    int prog = 0, fbo = 0, vp[4] = {0,0,0,0}, tex0 = 0, vao = 0, act = 0;
    int blend = 0, depth = 0, scis = 0, cull = 0;
    int dw, dh, dx, dy;

    if (!win_on) return;
    win_pump();
    if (win_every > 1 && (frames_done % win_every)) return;

    /* Ask EGL how big the drawable actually is, rather than trusting that a
     * ConfigureNotify arrived. Under WSLg the window is a RAIL proxy on the
     * Windows side and resize events do not always reach the X client, which
     * showed up as the picture staying 1360x768 in the corner of a window that
     * had grown. eglQuerySurface is authoritative, costs nothing, and needs no
     * event delivery at all. ConfigureNotify is still handled as a fallback for
     * the case where the surface query is not supported. */
    {
        EGLint qw = 0, qh = 0;
        if (eglQuerySurface(egl_dpy, egl_surf, 0x3057, &qw) &&    /* EGL_WIDTH  */
            eglQuerySurface(egl_dpy, egl_surf, 0x3056, &qh) &&    /* EGL_HEIGHT */
            qw > 0 && qh > 0) {
            win_w = qw; win_h = qh;
        }
    }

    p_glGetIntegerv(0x8B8D, &prog);    /* CURRENT_PROGRAM      */
    p_glGetIntegerv(0x8CA6, &fbo);     /* FRAMEBUFFER_BINDING  */
    p_glGetIntegerv(0x0BA2, vp);       /* VIEWPORT             */
    p_glGetIntegerv(0x85B5, &vao);     /* VERTEX_ARRAY_BINDING */
    p_glGetIntegerv(0x84E0, &act);     /* ACTIVE_TEXTURE       */
    p_glGetIntegerv(0x0BE2, &blend);   /* BLEND                */
    p_glGetIntegerv(0x0B71, &depth);   /* DEPTH_TEST           */
    p_glGetIntegerv(0x0C11, &scis);    /* SCISSOR_TEST         */
    p_glGetIntegerv(0x0B44, &cull);    /* CULL_FACE            */
    p_glActiveTexture(0x84C0);         /* TEXTURE0 - then read ITS binding */
    p_glGetIntegerv(0x8069, &tex0);    /* TEXTURE_BINDING_2D   */

    /* Letterbox: fit fb_w x fb_h inside win_w x win_h without distorting. */
    dw = win_w; dh = (int)((long)win_w * fb_h / (fb_w ? fb_w : 1));
    if (dh > win_h) { dh = win_h; dw = (int)((long)win_h * fb_w / (fb_h ? fb_h : 1)); }
    dx = (win_w - dw) / 2; dy = (win_h - dh) / 2;

    p_glBindFramebuffer(0x8D40, 0);    /* the real window                    */
    p_glDisable(0x0BE2); p_glDisable(0x0B71);
    p_glDisable(0x0C11); p_glDisable(0x0B44);
    p_glViewport(0, 0, win_w, win_h);
    p_glClearColor(0.f, 0.f, 0.f, 1.f);
    p_glClear(0x4000);                 /* COLOR_BUFFER_BIT                   */
    p_glViewport(dx, dy, dw, dh);
    p_glUseProgram(blit_prog);
    p_glBindVertexArray(blit_vao);
    p_glBindTexture(0x0DE1, tex_screen);
    if (blit_tex_loc >= 0) p_glUniform1i(blit_tex_loc, 0);
    {   int fl = p_glGetUniformLocation(blit_prog, "u_flip");
        if (fl >= 0) p_glUniform1f(fl, win_flip ? 1.f : 0.f); }
    p_glDrawArrays(0x0005, 0, 4);      /* TRIANGLE_STRIP                     */
    eglSwapBuffers(egl_dpy, egl_surf);

    p_glBindTexture(0x0DE1, (unsigned)tex0);
    p_glActiveTexture((unsigned)act);
    p_glBindVertexArray((unsigned)vao);
    p_glUseProgram((unsigned)prog);
    p_glBindFramebuffer(0x8D40, (unsigned)fbo);
    p_glViewport(vp[0], vp[1], vp[2], vp[3]);
    if (blend) p_glEnable(0x0BE2);
    if (depth) p_glEnable(0x0B71);
    if (scis)  p_glEnable(0x0C11);
    if (cull)  p_glEnable(0x0B44);
}

/* ---- PNG out: stored deflate, so no zlib dependency ---- */
static unsigned crc_tab[256]; static int crc_ready;
static unsigned crc32_buf(unsigned c, const unsigned char *p, unsigned long n)
{
    unsigned long i;
    if (!crc_ready) { unsigned k, j; for (k = 0; k < 256; k++) { unsigned v = k;
        for (j = 0; j < 8; j++) v = (v & 1) ? (0xEDB88320u ^ (v >> 1)) : (v >> 1);
        crc_tab[k] = v; } crc_ready = 1; }
    for (i = 0; i < n; i++) c = crc_tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c;
}
static void be32(unsigned char *d, unsigned v)
{ d[0]=(unsigned char)(v>>24); d[1]=(unsigned char)(v>>16); d[2]=(unsigned char)(v>>8); d[3]=(unsigned char)v; }
static void png_chunk(FILE *f, const char *tag, const unsigned char *data, unsigned n)
{
    unsigned char h[8], c[4]; unsigned v;
    be32(h, n); memcpy(h + 4, tag, 4);
    fwrite(h, 1, 8, f);
    if (n) fwrite(data, 1, n, f);
    v = crc32_buf(0xFFFFFFFFu, h + 4, 4);
    if (n) v = crc32_buf(v, data, n);
    be32(c, v ^ 0xFFFFFFFFu); fwrite(c, 1, 4, f);
}
static void write_png(const char *path, const unsigned char *rgba, int w, int h)
{
    static const unsigned char sig[8] = {137,80,78,71,13,10,26,10};
    unsigned char ihdr[13], *raw, *z;
    unsigned long rawlen = (unsigned long)h * (w * 3 + 1), o = 0, i;
    unsigned a = 1, b = 0;
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fwrite(sig, 1, 8, f);
    be32(ihdr, (unsigned)w); be32(ihdr + 4, (unsigned)h);
    ihdr[8]=8; ihdr[9]=2; ihdr[10]=0; ihdr[11]=0; ihdr[12]=0;
    png_chunk(f, "IHDR", ihdr, 13);
    raw = malloc(rawlen);
    if (!raw) { fclose(f); return; }
    /* GL reads bottom-up; PNG is top-down. */
    for (i = 0; i < (unsigned long)h; i++) {
        const unsigned char *row = rgba + (unsigned long)(h - 1 - i) * w * 4;
        int x; raw[o++] = 0;
        for (x = 0; x < w; x++) { raw[o++]=row[x*4]; raw[o++]=row[x*4+1]; raw[o++]=row[x*4+2]; }
    }
    for (i = 0; i < rawlen; i++) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }
    z = malloc(2 + ((rawlen + 65534) / 65535) * 5 + rawlen + 4);
    if (!z) { free(raw); fclose(f); return; }
    o = 0; z[o++] = 0x78; z[o++] = 0x01;
    for (i = 0; i < rawlen; ) {
        unsigned long n = rawlen - i; int last;
        if (n > 65535) n = 65535;
        last = (i + n >= rawlen);
        z[o++] = (unsigned char)last;
        z[o++] = (unsigned char)(n & 0xFF); z[o++] = (unsigned char)(n >> 8);
        z[o++] = (unsigned char)(~n & 0xFF); z[o++] = (unsigned char)((~n >> 8) & 0xFF);
        memcpy(z + o, raw + i, n); o += n; i += n;
    }
    be32(z + o, (b << 16) | a); o += 4;
    png_chunk(f, "IDAT", z, (unsigned)o);
    png_chunk(f, "IEND", 0, 0);
    fclose(f); free(z); free(raw);
}

static void present(void)
{
    frames_done++;
    /* Straight after the frame counter and BEFORE every early return below.
     * The dump path bails out on !dump_dir, on dump_every and on dump_max, so
     * anything placed further down would render only every Nth frame and then
     * stop forever - which for a live window means a picture that freezes. */
    win_present();
    /* "the draws arrived with correct state" and "the target has pixels in it"
     * are separate claims. Check the second directly. */
    if (dbg && frames_done <= 400 && (frames_done % 40) == 0) {
        unsigned char *px = malloc((size_t)fb_w * fb_h * 4);
        if (px) {
            long i, n = (long)fb_w * fb_h, lit = 0;
            p_glBindFramebuffer(0x8D40, fbo_screen);
            p_glFinish();
            p_glReadPixels(0, 0, fb_w, fb_h, 0x1908, 0x1401, px);
            for (i = 0; i < n; i++)
                if (px[i*4] | px[i*4+1] | px[i*4+2]) lit++;
            fprintf(stderr, "[padglhost] frame %ld: screen fbo %ld%% non-black (err 0x%x)\n",
                    frames_done, n ? lit * 100 / n : 0, p_glGetError());
            free(px);
        }
    }
    if (!dump_dir) return;
    if (frames_done % dump_every) return;
    if (dumped >= dump_max) return;
    dumped++;
    {
        unsigned char *px = malloc((size_t)fb_w * fb_h * 4);
        char path[600];
        if (!px) return;
        p_glBindFramebuffer(0x8D40, fbo_screen);
        p_glReadPixels(0, 0, fb_w, fb_h, 0x1908, 0x1401, px);
        snprintf(path, sizeof path, "%s/frame_%04ld.png", dump_dir, frames_done);
        write_png(path, px, fb_w, fb_h);
        free(px);
        fprintf(stderr, "[padglhost] wrote %s\n", path);
    }
}

static void check_shader(unsigned real, unsigned guest)
{
    int ok = 0;
    p_glGetShaderiv(real, 0x8B81, &ok);
    if (!ok) {
        char log[2048];
        p_glGetShaderInfoLog(real, sizeof log, 0, log);
        fprintf(stderr, "[padglhost] shader %u FAILED to compile:\n%s\n", guest, log);
    }
}

/* Op histogram + first-draw detail. A bridge that runs at full speed while
 * drawing nothing is exactly the failure mode worth being able to localise:
 * either the draws never arrive, or they arrive and the state is wrong. */
static long op_count[PADGL_OP_MAX];

static void dump_op_histogram(void)
{
    static const char *nm[PADGL_OP_MAX] = {0};
    int i;
    nm[PADGL_SWAP]="SWAP"; nm[PADGL_CLEAR]="CLEAR"; nm[PADGL_VIEWPORT]="VIEWPORT";
    nm[PADGL_TEXIMAGE]="TEXIMAGE"; nm[PADGL_BUFDATA]="BUFDATA";
    nm[PADGL_DRAWARRAYS]="DRAWARRAYS"; nm[PADGL_DRAWELEMENTS]="DRAWELEMENTS";
    nm[PADGL_USEPROGRAM]="USEPROGRAM"; nm[PADGL_LINKPROGRAM]="LINKPROGRAM";
    nm[PADGL_UNIFORM]="UNIFORM"; nm[PADGL_REGUNIFORM]="REGUNIFORM";
    nm[PADGL_BINDFBO]="BINDFBO"; nm[PADGL_BINDTEX]="BINDTEX";
    nm[PADGL_VERTEXATTRIB]="VERTEXATTRIB"; nm[PADGL_ENABLEATTRIB]="ENABLEATTRIB";
    nm[PADGL_BINDVAO]="BINDVAO"; nm[PADGL_COMPILESHADER]="COMPILESHADER";
    nm[PADGL_TEXDIRECT]="TEXDIRECT";
    fprintf(stderr, "[padglhost] ops:");
    for (i = 0; i < PADGL_OP_MAX; i++)
        if (op_count[i]) fprintf(stderr, " %s=%ld", nm[i] ? nm[i] : "?", op_count[i]);
    fprintf(stderr, "\n");
    /* TEXDIRECT is the video path. Report the drops separately: a climbing
     * TEXDIRECT with a climbing dropped count is not video, it is video being
     * thrown away, and the two look identical in the histogram above. */
    if (vid_texdirect || vid_dropped)
        fprintf(stderr, "[padglhost] video frames uploaded=%ld dropped=%ld\n",
                vid_texdirect, vid_dropped);
}

static void dispatch(unsigned op, const unsigned char *pl, unsigned len)
{
    const unsigned *u = (const unsigned *)pl;
    const float *fv = (const float *)pl;
    if (op < PADGL_OP_MAX) op_count[op]++;
    /* PADGL_DEBUG=3: log every op of one whole frame, in order. State probes
     * answer "is X right"; only the sequence answers "what actually happens". */
    if (dbg == 3 && frames_done >= seq_from && frames_done < seq_to) {
        static const char *n[PADGL_OP_MAX] = {0};
        if (!n[PADGL_SWAP]) {
            n[PADGL_SWAP]="SWAP"; n[PADGL_CLEAR]="CLEAR"; n[PADGL_CLEARCOLOR]="CLEARCOLOR";
            n[PADGL_VIEWPORT]="VIEWPORT"; n[PADGL_SCISSOR]="SCISSOR";
            n[PADGL_ENABLE]="ENABLE"; n[PADGL_DISABLE]="DISABLE";
            n[PADGL_BLENDFUNC]="BLENDFUNC"; n[PADGL_BINDTEX]="BINDTEX";
            n[PADGL_ACTIVETEX]="ACTIVETEX"; n[PADGL_TEXPARAM]="TEXPARAM";
            n[PADGL_BINDBUF]="BINDBUF"; n[PADGL_BUFDATA]="BUFDATA";
            n[PADGL_BINDVAO]="BINDVAO"; n[PADGL_VERTEXATTRIB]="VERTEXATTRIB";
            n[PADGL_ENABLEATTRIB]="ENABLEATTRIB"; n[PADGL_DISABLEATTRIB]="DISABLEATTRIB";
            n[PADGL_USEPROGRAM]="USEPROGRAM"; n[PADGL_UNIFORM]="UNIFORM";
            n[PADGL_BINDFBO]="BINDFBO"; n[PADGL_FBOTEX]="FBOTEX";
            n[PADGL_DRAWARRAYS]="DRAWARRAYS"; n[PADGL_DRAWELEMENTS]="DRAWELEMENTS";
            n[PADGL_TEXIMAGE]="TEXIMAGE"; n[PADGL_TEXDIRECT]="TEXDIRECT";
        }
        fprintf(stderr, "[seq] %-14s %u %u %u %u\n",
                op < PADGL_OP_MAX && n[op] ? n[op] : "?",
                len >= 4 ? u[0] : 0, len >= 8 ? u[1] : 0,
                len >= 12 ? u[2] : 0, len >= 16 ? u[3] : 0);
    }
    if (dbg && (op == PADGL_DRAWARRAYS || op == PADGL_DRAWELEMENTS)) {
        static int shown;
        if (shown < 8) {
            /* Ask the real GL what state the draw is actually going to use.
             * "the draws arrive and GL is happy" and "the draws land where we
             * read back from" are different claims. */
            int cur_prog = 0, cur_fbo = 0, vp[4] = {0,0,0,0}, tex2d = 0, vao = 0;
            shown++;
            p_glGetIntegerv(0x8B8D, &cur_prog);   /* CURRENT_PROGRAM      */
            p_glGetIntegerv(0x8CA6, &cur_fbo);    /* FRAMEBUFFER_BINDING  */
            p_glGetIntegerv(0x0BA2, vp);          /* VIEWPORT             */
            p_glGetIntegerv(0x8069, &tex2d);      /* TEXTURE_BINDING_2D   */
            p_glGetIntegerv(0x85B5, &vao);        /* VERTEX_ARRAY_BINDING */
            fprintf(stderr,
                    "[padglhost] draw mode=%u count=%u | prog=%d fbo=%d (screen=%u) "
                    "vp=%d,%d %dx%d tex=%d vao=%d err=0x%x\n",
                    u[0], op == PADGL_DRAWARRAYS ? u[2] : u[1],
                    cur_prog, cur_fbo, fbo_screen, vp[0], vp[1], vp[2], vp[3],
                    tex2d, vao, p_glGetError());
            {   /* The last unchecked link: does the draw actually have vertex
                 * data wired to attribute 0? */
                int k;
                for (k = 0; k < 3; k++) {
                    int en = 0, sz = 0, ty = 0, st = 0, bb = 0;
                    p_glGetVertexAttribiv(k, 0x8622, &en);
                    p_glGetVertexAttribiv(k, 0x8623, &sz);
                    p_glGetVertexAttribiv(k, 0x8625, &ty);
                    p_glGetVertexAttribiv(k, 0x8624, &st);
                    p_glGetVertexAttribiv(k, 0x889F, &bb);
                    if (en || bb)
                        fprintf(stderr, "[padglhost]   attr%d enabled=%d size=%d "
                                "type=0x%x stride=%d buffer=%d\n", k, en, sz, ty, st, bb);
                }
            }
        }
    }
    switch (op) {
    case PADGL_SWAP:            present(); hdr->frame_ack++; break;
    case PADGL_VIEWPORT:        p_glViewport((int)u[0],(int)u[1],(int)u[2],(int)u[3]); break;
    case PADGL_SCISSOR:         p_glScissor((int)u[0],(int)u[1],(int)u[2],(int)u[3]); break;
    case PADGL_CLEARCOLOR:
        /* PADGL_DEBUG=2 forces a loud clear colour. If the readback then shows
         * blue, the render target and the readback are fine and the problem is
         * the draws; if it stays black, the target we read is not the target
         * being drawn into. This splits the two halves in one run. */
        if (dbg == 2) p_glClearColor(0.0f, 0.25f, 1.0f, 1.0f);
        else p_glClearColor(fv[0],fv[1],fv[2],fv[3]);
        break;
    case PADGL_CLEAR:           p_glClear(u[0]); break;
    case PADGL_ENABLE:          p_glEnable(u[0]); break;
    case PADGL_DISABLE:         p_glDisable(u[0]); break;
    case PADGL_BLENDFUNC:       p_glBlendFunc(u[0],u[1]); break;
    case PADGL_BLENDFUNCSEP:    p_glBlendFuncSeparate(u[0],u[1],u[2],u[3]); break;
    case PADGL_BLENDEQ:         p_glBlendEquation(u[0]); break;
    case PADGL_BLENDEQSEP:      p_glBlendEquationSeparate(u[0],u[1]); break;

    case PADGL_GENTEX:          if (u[0] < MAXNAME) p_glGenTextures(1, &map_tex[u[0]]); break;
    case PADGL_DELTEX:          if (u[0] < MAXNAME && map_tex[u[0]])
                                    { p_glDeleteTextures(1, &map_tex[u[0]]); map_tex[u[0]] = 0; } break;
    case PADGL_BINDTEX:
        cur_tex_unit_binding = u[1];
        p_glBindTexture(u[0], u[1] < MAXNAME ? map_tex[u[1]] : 0);
        break;
    case PADGL_ACTIVETEX:       p_glActiveTexture(u[0]); break;
    case PADGL_TEXPARAM:
        if (u[1] == 0x2801) min_filter_set[cur_tex_unit_binding & (MAXNAME-1)] = 1;
        if (dbg) { static int shown; if (shown < 6) { shown++;
            fprintf(stderr, "[padglhost] texparam target=0x%x pname=0x%x val=0x%x\n",
                    u[0], u[1], u[2]); } }
        p_glTexParameteri(u[0],u[1],(int)u[2]);
        break;
    case PADGL_TEXIMAGE:
        if (dbg) {
            static int shown;
            if (shown < 6) {
                unsigned long i, n = u[6], lit = 0;
                const unsigned char *px = pl + 28;
                shown++;
                for (i = 0; i + 3 < n; i += 4)
                    if (px[i] | px[i+1] | px[i+2]) lit++;
                fprintf(stderr, "[padglhost] teximage %ux%u fmt=0x%x %u bytes, "
                        "%lu%% non-black\n", u[2], u[3], u[4], u[6],
                        n ? lit * 400 / n : 0);
            }
        }
        p_glTexImage2D(0x0DE1,(int)u[0],(int)u[1],(int)u[2],(int)u[3],0,u[4],u[5],
                       u[6] ? pl + 28 : 0);
        /* GLES samples BLACK from a texture that has only level 0 while
         * MIN_FILTER is still its default NEAREST_MIPMAP_LINEAR - the texture
         * is "incomplete". The Vivante driver on the machine is laxer, and the
         * software rasteriser ignored filters entirely, so this only shows up
         * here. Supply a non-mipmap default; any TEXPARAM the game sends later
         * arrives after this in the stream and still wins. */
        if (u[0] == 0 && !min_filter_set[cur_tex_unit_binding & (MAXNAME-1)]) {
            p_glTexParameteri(0x0DE1, 0x2801, 0x2601);   /* MIN_FILTER LINEAR */
            p_glTexParameteri(0x0DE1, 0x2800, 0x2601);   /* MAG_FILTER LINEAR */
            p_glTexParameteri(0x0DE1, 0x2802, 0x812F);   /* WRAP_S CLAMP_TO_EDGE */
            p_glTexParameteri(0x0DE1, 0x2803, 0x812F);   /* WRAP_T CLAMP_TO_EDGE */
        }
        break;
    case PADGL_TEXDIRECT: {
        /* u[0..5] = w, h, fmt, src, arg, len */
        unsigned w = u[0], h = u[1], fmt = u[2], src = u[3];
        const unsigned char *yuv = 0, *rgba;
        if (len < 24 || !w || !h) { vid_dropped++; break; }
        if (src == PADGL_SRC_VIDSHM) {
            vid_open();
            /* The offset spans ALL channels' rings - the guest names a frame
             * by its distance from the ring base, whichever channel it is in. */
            if (vid_ring && (unsigned long)u[4] + u[5] <=
                    (unsigned long)PADVID_RING_BYTES)
                yuv = vid_ring + u[4];
        } else if (len >= 24 + u[5]) {
            yuv = pl + 24;
        }
        if (!yuv) { vid_dropped++; break; }
        /* THE DIRECT TEXTURE PATH IS NOT A VIDEO PATH. It was written for
         * Godzilla Pro, which only ever uses it for I420 video frames, so
         * anything else was refused as "not I420". Jaws LE uses the same
         * extension for plain GL_RGBA surfaces, which need no conversion at
         * all - they are already in the layout the texture wants. */
        if (fmt == 0x1908u) {                        /* GL_RGBA */
            rgba = yuv;
        } else if (fmt == PADGL_VIV_I420) {
            rgba = i420_to_rgba(yuv, w, h);
        } else {
            static int moaned;
            if (!moaned) { moaned = 1;
                fprintf(stderr, "[padglhost] texdirect format 0x%x has no "
                        "converter here\n", fmt); }
            vid_dropped++;
            break;
        }
        if (!rgba) { vid_dropped++; break; }
        vid_texdirect++;
        if (dbg) {
            static int shown;
            if (shown < 6) {
                unsigned long i, n = (unsigned long)w * h * 4, lit = 0;
                shown++;
                for (i = 0; i + 3 < n; i += 4)
                    if (rgba[i] | rgba[i+1] | rgba[i+2]) lit++;
                fprintf(stderr, "[padglhost] texdirect %ux%u src=%u %lu%% non-black\n",
                        w, h, src, n ? lit * 400 / n : 0);
            }
        }
        p_glTexImage2D(0x0DE1, 0, 0x1908 /*RGBA*/, (int)w, (int)h, 0,
                       0x1908, 0x1401 /*UNSIGNED_BYTE*/, rgba);
        /* Same completeness trap as PADGL_TEXIMAGE, and worse here: the game
         * never sets a filter on this texture at all, because on the machine
         * the Vivante driver gives a direct texture usable defaults. Without
         * these the video samples black and everything above looks correct. */
        if (!min_filter_set[cur_tex_unit_binding & (MAXNAME-1)]) {
            p_glTexParameteri(0x0DE1, 0x2801, 0x2601);   /* MIN_FILTER LINEAR    */
            p_glTexParameteri(0x0DE1, 0x2800, 0x2601);   /* MAG_FILTER LINEAR    */
            p_glTexParameteri(0x0DE1, 0x2802, 0x812F);   /* WRAP_S CLAMP_TO_EDGE */
            p_glTexParameteri(0x0DE1, 0x2803, 0x812F);   /* WRAP_T CLAMP_TO_EDGE */
        }
        break;
    }
    case PADGL_TEXSUBIMAGE:
        p_glTexSubImage2D(0x0DE1,(int)u[0],(int)u[1],(int)u[2],(int)u[3],(int)u[4],
                          u[5],u[6], u[7] ? pl + 32 : 0);
        break;
    case PADGL_TEXCOMPRESSED:
        p_glCompressedTexImage2D(0x0DE1,(int)u[0],u[1],(int)u[2],(int)u[3],0,
                                 (int)u[4], u[4] ? pl + 20 : 0);
        break;

    case PADGL_GENBUF:          if (u[0] < MAXNAME) p_glGenBuffers(1, &map_buf[u[0]]); break;
    case PADGL_DELBUF:          if (u[0] < MAXNAME && map_buf[u[0]])
                                    { p_glDeleteBuffers(1, &map_buf[u[0]]); map_buf[u[0]] = 0; } break;
    case PADGL_BINDBUF:         p_glBindBuffer(u[0], u[1] < MAXNAME ? map_buf[u[1]] : 0); break;
    case PADGL_BUFDATA:
        if (dbg) {
            static int shown;
            if (shown < 3 && len > 12) {
                const float *f = (const float *)(pl + 12);
                shown++;
                fprintf(stderr, "[padglhost] BUFDATA target=0x%x %u bytes: "
                        "%.2f %.2f %.2f %.2f | %.2f %.2f %.2f %.2f\n",
                        u[0], u[2], f[0],f[1],f[2],f[3], f[4],f[5],f[6],f[7]);
            }
        }
        p_glBufferData(u[0], (long)u[2], len > 12 ? pl + 12 : 0, u[1]);
        break;
    case PADGL_BUFSUBDATA:      p_glBufferSubData(u[0], (long)u[1], (long)u[2],
                                                  len > 12 ? pl + 12 : 0); break;

    case PADGL_GENVAO:          if (u[0] < 1024) p_glGenVertexArrays(1, &map_vao[u[0]]); break;
    case PADGL_BINDVAO:         p_glBindVertexArray(u[0] < 1024 ? map_vao[u[0]] : 0); break;
    case PADGL_VERTEXATTRIB: {
        int idx = attr_resolve(u[0]);
        if (idx >= 0)
            p_glVertexAttribPointer((unsigned)idx,(int)u[1],u[2],(unsigned char)u[3],
                                    (int)u[4],(const void *)(unsigned long)u[5]);
        break;
    }
    case PADGL_ENABLEATTRIB: {
        int idx = attr_resolve(u[0]);
        if (idx >= 0) p_glEnableVertexAttribArray((unsigned)idx);
        break;
    }
    case PADGL_DISABLEATTRIB: {
        int idx = attr_resolve(u[0]);
        if (idx >= 0) p_glDisableVertexAttribArray((unsigned)idx);
        break;
    }
    case PADGL_REGATTRIB: {
        unsigned g = u[0], slot = u[1], n = len > 8 ? len - 8 : 0;
        if (g >= MAXPROG || slot >= PADGL_ATTR_PER_PROG) break;
        if (n > 39) n = 39;
        memcpy(attr_name[g][slot], pl + 8, n); attr_name[g][slot][n] = 0;
        attr_loc[g][slot] = p_glGetAttribLocation(map_obj[g], attr_name[g][slot]);
        if (dbg)
            fprintf(stderr, "[padglhost] attrib prog=%u slot=%u '%s' -> real loc %d\n",
                    g, slot, attr_name[g][slot], attr_loc[g][slot]);
        break;
    }

    case PADGL_CREATESHADER:    if (u[0] < MAXNAME) map_obj[u[0]] = p_glCreateShader(u[1]); break;
    case PADGL_CREATEPROGRAM:   if (u[0] < MAXNAME) map_obj[u[0]] = p_glCreateProgram(); break;
    case PADGL_SHADERSOURCE: {
        unsigned g = u[0], n = u[1];
        if (g >= MAXNAME) break;
        shader_src[g] = realloc(shader_src[g], shader_len[g] + n + 1);
        memcpy(shader_src[g] + shader_len[g], pl + 8, n);
        shader_len[g] += n;
        shader_src[g][shader_len[g]] = 0;
        break;
    }
    case PADGL_COMPILESHADER: {
        unsigned g = u[0];
        if (g < MAXNAME && shader_src[g]) {
            const char *s = shader_src[g];
            /* Naming the program that draws a frame is only useful if you know
             * what it is. "the ImGui overlay" was a guess from two uniform
             * names; the source settles it. */
            if (dbg >= 3)
                fprintf(stderr, "[shader] guest id %u source:\n%s\n[/shader]\n", g, s);
            p_glShaderSource(map_obj[g], 1, &s, 0);
            p_glCompileShader(map_obj[g]);
            check_shader(map_obj[g], g);
        }
        break;
    }
    case PADGL_ATTACHSHADER:
        if (u[0] < MAXNAME && u[1] < MAXNAME) p_glAttachShader(map_obj[u[0]], map_obj[u[1]]);
        break;
    case PADGL_BINDATTRIBLOC: {
        char nm[64]; unsigned n = len > 8 ? len - 8 : 0;
        if (n > 63) n = 63;
        memcpy(nm, pl + 8, n); nm[n] = 0;
        if (u[0] < MAXNAME) p_glBindAttribLocation(map_obj[u[0]], u[1], nm);
        break;
    }
    case PADGL_LINKPROGRAM: {
        unsigned g = u[0]; int ok = 0;
        if (g >= MAXNAME) break;
        p_glLinkProgram(map_obj[g]);
        p_glGetProgramiv(map_obj[g], 0x8B82, &ok);
        if (!ok) { char log[2048]; p_glGetProgramInfoLog(map_obj[g], sizeof log, 0, log);
                   fprintf(stderr, "[padglhost] program %u FAILED to link:\n%s\n", g, log); }
        /* Uniform names registered before the link resolve only now. */
        if (g < MAXPROG) { int k; for (k = 0; k < MAXUNI; k++)
            if (uni_name[g][k][0]) uni_loc[g][k] = p_glGetUniformLocation(map_obj[g], uni_name[g][k]); }
        break;
    }
    case PADGL_USEPROGRAM:      if (u[0] < MAXNAME) p_glUseProgram(map_obj[u[0]]); break;
    case PADGL_REGUNIFORM: {
        unsigned g = u[0], slot = u[1], n = len > 8 ? len - 8 : 0;
        if (g >= MAXPROG || slot >= MAXUNI) break;
        if (n > 39) n = 39;
        memcpy(uni_name[g][slot], pl + 8, n); uni_name[g][slot][n] = 0;
        uni_loc[g][slot] = p_glGetUniformLocation(map_obj[g], uni_name[g][slot]);
        break;
    }
    case PADGL_UNIFORM: {
        unsigned g = u[0], slot = u[1], kind = u[2];
        const float *f = (const float *)(pl + 12);
        int loc;
        if (g >= MAXPROG || slot >= MAXUNI) break;
        loc = uni_loc[g][slot];
        if (dbg) {
            static int shown;
            if (shown < 8) {
                shown++;
                fprintf(stderr, "[padglhost] uniform prog=%u slot=%u '%s' loc=%d kind=%u",
                        g, slot, uni_name[g][slot], loc, kind);
                if (kind == PADGL_UM4FV) {
                    int r;
                    fprintf(stderr, " matrix(col-major):");
                    for (r = 0; r < 16; r++) fprintf(stderr, " %.4g", f[r]);
                }
                fprintf(stderr, "\n");
            }
        }
        if (loc < 0) break;
        switch (kind) {
        case PADGL_U1F:   p_glUniform1f(loc, f[0]); break;
        case PADGL_U2F:   p_glUniform2f(loc, f[0], f[1]); break;
        case PADGL_U3F:   p_glUniform3f(loc, f[0], f[1], f[2]); break;
        case PADGL_U4F:   p_glUniform4f(loc, f[0], f[1], f[2], f[3]); break;
        case PADGL_U4FV:  p_glUniform4fv(loc, 1, f); break;
        case PADGL_UM4FV: p_glUniformMatrix4fv(loc, 1, 0, f); break;
        case PADGL_U1I:   p_glUniform1i(loc, *(const int *)f); break;
        default: break;
        }
        break;
    }

    case PADGL_GENFBO:          if (u[0] < 256) p_glGenFramebuffers(1, &map_fbo[u[0]]); break;
    case PADGL_BINDFBO:         p_glBindFramebuffer(u[0], u[1] < 256 ? map_fbo[u[1]] : 0); break;
    case PADGL_FBOTEX:
        p_glFramebufferTexture2D(u[0],u[1],u[2], u[3] < MAXNAME ? map_tex[u[3]] : 0,(int)u[4]);
        break;

    case PADGL_DRAWARRAYS:      p_glDrawArrays(u[0],(int)u[1],(int)u[2]); break;
    case PADGL_DRAWELEMENTS:    p_glDrawElements(u[0],(int)u[1],u[2],
                                                 (const void *)(unsigned long)u[3]); break;
    case PADGL_NOP:             break;
    default:
        if (++unknown_ops < 8)
            fprintf(stderr, "[padglhost] UNKNOWN op %u len %u - the picture will be wrong\n", op, len);
        break;
    }
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/shm/padgl";
    unsigned long ring_mb = 64;
    int fd;
    void *mem;
    unsigned long total;
    EGLint major, minor, n;
    EGLDisplay dpy; EGLConfig cfg; EGLContext ctx; EGLSurface surf;
    /* EGL_SURFACE_TYPE asks for WINDOW|PBUFFER (0x0005) rather than the old
     * PBUFFER-only 0x0001, so the one config serves both the headless path and
     * the live window. All 80 configs on this display support both. */
    static const EGLint cfgattr[] = { 0x3033,0x0005, 0x3040,0x0040,
        0x3024,8, 0x3023,8, 0x3022,8, 0x3021,8, 0x3038 };
    static const EGLint pbattr[]  = { 0x3057,16, 0x3056,16, 0x3038 };
    static const EGLint ctxattr[] = { 0x3098,3, 0x30FB,0, 0x3038 };
    double t0; long last_frames = 0; double last_report;

    if (getenv("PAD_GL_W")) fb_w = atoi(getenv("PAD_GL_W"));
    if (getenv("PAD_GL_H")) fb_h = atoi(getenv("PAD_GL_H"));
    dump_dir = getenv("PAD_GL_DUMP");
    if (dump_dir && !dump_dir[0]) dump_dir = 0;   /* empty means unset, not "/" */
    if (getenv("PAD_GL_FRAME_EVERY")) dump_every = atoi(getenv("PAD_GL_FRAME_EVERY"));
    if (getenv("PAD_GL_MAX_FRAMES"))  dump_max   = atoi(getenv("PAD_GL_MAX_FRAMES"));
    if (getenv("PAD_GL_RING_MB"))     ring_mb    = strtoul(getenv("PAD_GL_RING_MB"), 0, 10);
    dbg = getenv("PADGL_DEBUG") ? atoi(getenv("PADGL_DEBUG")) : 0;
    if (getenv("PADGL_SEQ_FROM")) seq_from = atol(getenv("PADGL_SEQ_FROM"));
    if (getenv("PADGL_SEQ_TO"))   seq_to   = atol(getenv("PADGL_SEQ_TO"));
    if (dump_every <= 0) dump_every = 1;

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    ring_bytes = (unsigned)(ring_mb << 20);
    total = PADGL_HDR_BYTES + ring_bytes;
    fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) { perror("open ring"); return 1; }
    if (ftruncate(fd, (off_t)total)) { perror("ftruncate"); return 1; }
    mem = mmap(0, total, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (mem == MAP_FAILED) { perror("mmap"); return 1; }
    hdr = (padgl_hdr *)mem;
    ring = (unsigned char *)mem + PADGL_HDR_BYTES;
    memset(hdr, 0, sizeof *hdr);
    hdr->magic = PADGL_MAGIC; hdr->version = PADGL_VERSION;
    hdr->ring_bytes = ring_bytes;
    hdr->fb_w = (unsigned)fb_w; hdr->fb_h = (unsigned)fb_h;

    /* Open the window FIRST: the EGL display should be the X display it lives
     * on, and the surface below has to be a window surface rather than the
     * pbuffer. If this fails for any reason it clears win_on and we carry on
     * exactly as before, headless. */
    win_open();

    dpy = eglGetDisplay(win_on ? (void *)xdpy : (void *)0);
    if (!eglInitialize(dpy, &major, &minor)) { fprintf(stderr, "eglInitialize failed\n"); return 1; }
    eglBindAPI(0x30A0);
    if (!eglChooseConfig(dpy, cfgattr, &cfg, 1, &n) || n < 1) {
        fprintf(stderr, "no ES3 config\n"); return 1; }
    if (win_on) {
        surf = eglCreateWindowSurface(dpy, cfg, xwin, 0);
        if (!surf) {
            fprintf(stderr, "[padglhost] eglCreateWindowSurface failed 0x%x; "
                            "falling back to headless\n", eglGetError());
            win_on = 0;
            surf = eglCreatePbufferSurface(dpy, cfg, pbattr);
        }
    } else {
        surf = eglCreatePbufferSurface(dpy, cfg, pbattr);
    }
    ctx  = eglCreateContext(dpy, cfg, 0, ctxattr);
    if (!ctx || !eglMakeCurrent(dpy, surf, surf, ctx)) {
        fprintf(stderr, "context/makecurrent failed 0x%x\n", eglGetError()); return 1; }
    egl_dpy = dpy; egl_surf = surf;
    /* Vsync on by default so the window is smooth; PAD_GL_VSYNC=0 removes the
     * 60 Hz block on eglSwapBuffers if it ever starves the ring drain. */
    if (win_on) eglSwapInterval(dpy, getenv("PAD_GL_VSYNC") &&
                                    getenv("PAD_GL_VSYNC")[0] == '0' ? 0 : 1);
    load_gl();
    win_init_gl();

    fprintf(stderr, "[padglhost] %s | %s\n", p_glGetString(0x1F01), p_glGetString(0x1F02));
    fprintf(stderr, "[padglhost] ring %s (%lu MB), display %dx%d\n", path, ring_mb, fb_w, fb_h);

    /* Guest FBO 0 = the screen; give it a real texture-backed target. */
    p_glGenTextures(1, &tex_screen);
    p_glBindTexture(0x0DE1, tex_screen);
    p_glTexImage2D(0x0DE1, 0, 0x1908, fb_w, fb_h, 0, 0x1908, 0x1401, 0);
    p_glTexParameteri(0x0DE1, 0x2801, 0x2601);
    p_glTexParameteri(0x0DE1, 0x2800, 0x2601);
    p_glGenFramebuffers(1, &fbo_screen);
    p_glBindFramebuffer(0x8D40, fbo_screen);
    p_glFramebufferTexture2D(0x8D40, 0x8CE0, 0x0DE1, tex_screen, 0);
    if (p_glCheckFramebufferStatus(0x8D40) != 0x8CD5) {
        fprintf(stderr, "[padglhost] screen framebuffer incomplete\n"); return 1; }
    map_fbo[0] = fbo_screen;
    map_vao[0] = 0;

    hdr->host_ready = 1;
    fprintf(stderr, "[padglhost] ready, waiting for the game\n");

    t0 = last_report = now_s();
    {
        unsigned char *payload = malloc(ring_bytes / 2 + 64);
        int idle_polls = 0;
        while (!stop_now) {
            padgl_cmd c;
            unsigned long long head = hdr->head, tail = hdr->tail;
            /* Pump X while idle too, so the window stays responsive (and can
             * still be closed) even if the guest stops feeding the ring. */
            /* Idle back-off. A flat usleep(200) is 5000 wakeups a second for as
             * long as the guest has nothing to say, which is most of the time
             * while it is booting or parked. Stay at 200 us for the first few
             * empty polls so a frame that is about to arrive is not delayed,
             * then drop to 2 ms. Worst case this adds 2 ms to the start of a
             * burst, against a 16.7 ms frame. The loop does NOT sleep at all
             * while there is work, so throughput is untouched. */
            if (head - tail < sizeof c) {
                win_pump();
                usleep(++idle_polls > 16 ? 2000 : 200);
                continue;
            }
            ring_get(tail, &c, sizeof c);
            if (head - tail < sizeof c + ((c.len + 7u) & ~7u)) { usleep(200); continue; }
            idle_polls = 0;
            if (c.len) ring_get(tail + sizeof c, payload, c.len);
            dispatch(c.op, payload, c.len);
            hdr->tail = tail + sizeof c + ((c.len + 7u) & ~7u);

            if (now_s() - last_report >= 2.0) {
                double dt = now_s() - last_report;
                fprintf(stderr, "[padglhost] %.1f fps (%ld frames total)\n",
                        (frames_done - last_frames) / dt, frames_done);
                if (dbg) dump_op_histogram();
                last_frames = frames_done; last_report = now_s();
            }
        }
        free(payload);
    }
    fprintf(stderr, "[padglhost] stopped after %ld frames in %.1f s (%.1f fps avg)\n",
            frames_done, now_s() - t0, frames_done / (now_s() - t0));
    return 0;
}
