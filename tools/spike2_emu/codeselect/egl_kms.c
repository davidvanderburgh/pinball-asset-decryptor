/* egl_kms.c - the menu on a Stern Spike 3 machine (PAD-1263): the Raspberry
 * Pi CM4's KMS, the way the game's own display server (Stern's glWindow.cpp)
 * drives it.
 *
 * The Spike 3 game has no window system. It opens /dev/dri/card1 (or card0),
 * walks the connectors, renders into GBM buffers it wraps as EGL images
 * through their dma-buf fds, and shows each buffer with drmModeAddFB +
 * drmModePageFlip. This file takes exactly that path, so the same binary runs
 * on the machine (Mesa on the v3d/vc4 pair) and in PAD's emulator, whose
 * s3kms.so / s3egl / s3gl shims answer the game's calls by name: the menu
 * needs nothing of its own there.
 *
 * The four egl_stern_* entry points are the menu's whole display interface
 * (egl_stern.h); this file implements them for Spike 3 the way fb_linux.c and
 * egl_x11.c do for the other machines.
 *
 * ROW ORDER. A KMS buffer's row 0 is the TOP of the screen. Rendering into a
 * texture-backed framebuffer puts GL's y = 0 in row 0, so the projection here
 * maps the canvas's top row to y = 0 (no flip), the opposite of egl_stern.c's
 * window surface. PAD's host presenter blits a page-flipped buffer with the
 * same row-0-at-the-top rule, so what the emulator shows is what the LCD shows.
 *
 * WHICH SCREEN. The game picks its screen by connector INDEX (display_number
 * in its config): 1, the second HDMI output, on both titles measured
 * (pokemon_le 0.82.0, fallout_le 0.82.0, whose Pip-Boy screen is the other
 * one). The menu takes index 1 when it is connected, else the first connected
 * one; PADSELECT_DRM_CONNECTOR=<index> overrides.
 *
 * No Khronos or libdrm headers are on the box: the few prototypes and the
 * libdrm structs (a stable ABI since 2008) are declared here by hand.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <errno.h>
#include "egl_stern.h"
#include "log.h"

/* ---- libdrm (xf86drmMode.h / xf86drm.h), by hand ------------------------ */
typedef struct {
    uint32_t clock;
    uint16_t hdisplay, hsync_start, hsync_end, htotal, hskew;
    uint16_t vdisplay, vsync_start, vsync_end, vtotal, vscan;
    uint32_t vrefresh, flags, type;
    char name[32];
} drm_mode;
typedef struct {
    int count_fbs; uint32_t *fbs;
    int count_crtcs; uint32_t *crtcs;
    int count_connectors; uint32_t *connectors;
    int count_encoders; uint32_t *encoders;
    uint32_t min_width, max_width, min_height, max_height;
} drm_res;
typedef struct {
    uint32_t connector_id, encoder_id, connector_type, connector_type_id;
    int connection;                     /* 1 = DRM_MODE_CONNECTED */
    uint32_t mmWidth, mmHeight;
    int subpixel;
    int count_modes; drm_mode *modes;
    int count_props; uint32_t *props; uint64_t *prop_values;
    int count_encoders; uint32_t *encoders;
} drm_conn;
typedef struct {
    uint32_t encoder_id, encoder_type, crtc_id, possible_crtcs, possible_clones;
} drm_enc;
typedef struct {
    int version;
    void (*vblank_handler)(int, unsigned, unsigned, unsigned, void *);
    void (*page_flip_handler)(int, unsigned, unsigned, unsigned, void *);
    void (*page_flip_handler2)(int, unsigned, unsigned, unsigned, unsigned, void *);
    void (*sequence_handler)(int, uint64_t, uint64_t, uint64_t);
} drm_evctx;

extern drm_res  *drmModeGetResources(int);
extern void      drmModeFreeResources(drm_res *);
extern drm_conn *drmModeGetConnector(int, uint32_t);
extern void      drmModeFreeConnector(drm_conn *);
extern drm_enc  *drmModeGetEncoder(int, uint32_t);
extern void      drmModeFreeEncoder(drm_enc *);
extern int drmModeAddFB(int, uint32_t, uint32_t, uint8_t, uint8_t, uint32_t, uint32_t, uint32_t *);
extern int drmModeRmFB(int, uint32_t);
extern int drmModeSetCrtc(int, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t *, int, drm_mode *);
extern int drmModePageFlip(int, uint32_t, uint32_t, uint32_t, void *);
extern int drmHandleEvent(int, drm_evctx *);

/* ---- gbm.h, by hand ------------------------------------------------------ */
struct gbm_device;
struct gbm_bo;
typedef union { void *ptr; int32_t s32; uint32_t u32; int64_t s64; uint64_t u64; } gbm_handle;
extern struct gbm_device *gbm_create_device(int);
extern void gbm_device_destroy(struct gbm_device *);
extern struct gbm_bo *gbm_bo_create(struct gbm_device *, uint32_t, uint32_t, uint32_t, uint32_t);
extern void gbm_bo_destroy(struct gbm_bo *);
extern int gbm_bo_get_fd(struct gbm_bo *);
extern uint32_t gbm_bo_get_stride(struct gbm_bo *);
extern gbm_handle gbm_bo_get_handle(struct gbm_bo *);

#define GBM_FORMAT_XRGB8888   0x34325258u     /* 'XR24' */
#define GBM_BO_USE_SCANOUT    (1u << 0)
#define GBM_BO_USE_RENDERING  (1u << 2)

/* ---- EGL / GLES, by hand ------------------------------------------------- */
extern void *eglGetPlatformDisplay(unsigned, void *, const intptr_t *);
extern void *eglGetDisplay(void *);
extern int   eglInitialize(void *, int *, int *);
extern int   eglChooseConfig(void *, const int *, void **, int, int *);
extern int   eglBindAPI(unsigned);
extern void *eglCreateContext(void *, void *, void *, const int *);
extern int   eglMakeCurrent(void *, void *, void *, void *);
extern int   eglTerminate(void *);
extern int   eglReleaseThread(void);
extern int   eglGetError(void);
extern void *eglGetProcAddress(const char *);

extern const unsigned char *glGetString(unsigned);
extern void glViewport(int, int, int, int);
extern void glClearColor(float, float, float, float);
extern void glClear(unsigned);
extern void glEnable(unsigned);
extern void glDisable(unsigned);
extern void glBlendFunc(unsigned, unsigned);
extern void glGenVertexArrays(int, unsigned *);
extern void glBindVertexArray(unsigned);
extern void glGenBuffers(int, unsigned *);
extern void glBindBuffer(unsigned, unsigned);
extern void glBufferData(unsigned, long, const void *, unsigned);
extern void glVertexAttribPointer(unsigned, int, unsigned, unsigned char, int, const void *);
extern void glEnableVertexAttribArray(unsigned);
extern unsigned glCreateShader(unsigned);
extern void glShaderSource(unsigned, int, const char *const *, const int *);
extern void glCompileShader(unsigned);
extern unsigned glCreateProgram(void);
extern void glAttachShader(unsigned, unsigned);
extern void glLinkProgram(unsigned);
extern void glUseProgram(unsigned);
extern int  glGetUniformLocation(unsigned, const char *);
extern void glUniform1i(int, int);
extern void glUniformMatrix4fv(int, int, unsigned char, const float *);
extern void glGenTextures(int, unsigned *);
extern void glBindTexture(unsigned, unsigned);
extern void glTexParameteri(unsigned, unsigned, int);
extern void glTexImage2D(unsigned, int, int, int, int, int, unsigned, unsigned, const void *);
extern void glTexSubImage2D(unsigned, int, int, int, int, int, unsigned, unsigned, const void *);
extern void glActiveTexture(unsigned);
extern void glDrawArrays(unsigned, int, int);
extern void glGenFramebuffers(int, unsigned *);
extern void glBindFramebuffer(unsigned, unsigned);
extern void glFramebufferTexture2D(unsigned, unsigned, unsigned, unsigned, int);
extern unsigned glCheckFramebufferStatus(unsigned);
extern void glFinish(void);
extern unsigned glGetError(void);

#define EGL_SUCCESS            0x3000
#define EGL_NONE               0x3038
#define EGL_OPENGL_ES_API      0x30A0
#define EGL_PLATFORM_GBM_KHR   0x31D7
#define EGL_LINUX_DMA_BUF_EXT  0x3270
#define EGL_LINUX_DRM_FOURCC_EXT 0x3271
#define EGL_DMA_BUF_PLANE0_FD_EXT 0x3272
#define EGL_DMA_BUF_PLANE0_OFFSET_EXT 0x3273
#define EGL_DMA_BUF_PLANE0_PITCH_EXT 0x3274
#define EGL_WIDTH              0x3057
#define EGL_HEIGHT             0x3056
#define GL_TEXTURE_2D      0x0DE1
#define GL_TEXTURE0        0x84C0
#define GL_RGBA            0x1908
#define GL_UNSIGNED_BYTE   0x1401
#define GL_TEXTURE_MIN_FILTER 0x2801
#define GL_TEXTURE_MAG_FILTER 0x2800
#define GL_TEXTURE_WRAP_S  0x2802
#define GL_TEXTURE_WRAP_T  0x2803
#define GL_LINEAR          0x2601
#define GL_CLAMP_TO_EDGE   0x812F
#define GL_ARRAY_BUFFER    0x8892
#define GL_STATIC_DRAW     0x88E4
#define GL_FLOAT           0x1406
#define GL_TRIANGLES       0x0004
#define GL_VERTEX_SHADER   0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_BLEND           0x0BE2
#define GL_SRC_ALPHA       0x0302
#define GL_ONE_MINUS_SRC_ALPHA 0x0303
#define GL_COLOR_BUFFER_BIT 0x4000
#define GL_FRAMEBUFFER     0x8D40
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_FRAMEBUFFER_COMPLETE 0x8CD5
#define DRM_MODE_PAGE_FLIP_EVENT 0x01
#define DRM_MODE_TYPE_PREFERRED  (1 << 3)

typedef void *(*create_image_fn)(void *, void *, unsigned, void *, const int *);
typedef void (*image_target_fn)(unsigned, void *);

#define NBUF 2
static struct {
    int fd;
    struct gbm_device *gbm;
    uint32_t conn_id, crtc_id;
    drm_mode mode;
    struct gbm_bo *bo[NBUF];
    uint32_t fb[NBUF];
    unsigned tex[NBUF], fbo[NBUF];
    int back, shown, flip_pending, flips_failed;
} K = { .fd = -1 };

/* RGBA8, no depth: the menu is one textured quad */
static const int cfg_attr[] = { 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8,
                                0x3040, 0x0040 /* EGL_RENDERABLE_TYPE = ES3 */,
                                EGL_NONE };
static const int ctx_attr[] = { 0x3098, 3, EGL_NONE };   /* EGL_CONTEXT_CLIENT_VERSION 3 */

static const char *VS =
    "#version 300 es\n"
    "layout (location = 0) in vec4 vertex;\n"
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

static int egl_ok(const char *step)
{
    int e = eglGetError();
    if (e != EGL_SUCCESS) {
        sel_log("kms: %s failed, eglGetError=0x%x", step, e);
        return 0;
    }
    return 1;
}

/* the connector to draw on, its mode and a crtc that can drive it */
static int pick_output(int fd)
{
    drm_res *r = drmModeGetResources(fd);
    int i, want = -1, pick = -1;
    const char *env = getenv("PADSELECT_DRM_CONNECTOR");
    drm_conn *c = NULL;
    if (!r) return -1;
    if (r->count_connectors < 1 || r->count_crtcs < 1) { drmModeFreeResources(r); return -1; }
    if (env && *env) want = atoi(env);
    else if (r->count_connectors > 1) want = 1;            /* the game's display_number */
    for (i = -1; i < r->count_connectors && pick < 0; i++) {
        int idx = i < 0 ? want : i;
        drm_conn *t;
        if (idx < 0 || idx >= r->count_connectors) continue;
        t = drmModeGetConnector(fd, r->connectors[idx]);
        if (t && t->connection == 1 && t->count_modes > 0) { c = t; pick = idx; break; }
        if (t) drmModeFreeConnector(t);
    }
    if (!c) { sel_log("kms: no connected output with a mode"); drmModeFreeResources(r); return -1; }
    K.conn_id = c->connector_id;
    K.mode = c->modes[0];
    for (i = 0; i < c->count_modes; i++)
        if (c->modes[i].type & DRM_MODE_TYPE_PREFERRED) { K.mode = c->modes[i]; break; }
    K.crtc_id = 0;
    if (c->encoder_id) {
        drm_enc *e = drmModeGetEncoder(fd, c->encoder_id);
        if (e) { K.crtc_id = e->crtc_id; drmModeFreeEncoder(e); }
    }
    for (i = 0; !K.crtc_id && i < c->count_encoders; i++) {
        drm_enc *e = drmModeGetEncoder(fd, c->encoders[i]);
        int j;
        if (!e) continue;
        for (j = 0; j < r->count_crtcs; j++)
            if (e->possible_crtcs & (1u << j)) { K.crtc_id = r->crtcs[j]; break; }
        drmModeFreeEncoder(e);
    }
    if (!K.crtc_id) K.crtc_id = r->crtcs[0];
    sel_log("kms: connector %d of %d (id %u) %s %ux%u@%u, crtc %u", pick, r->count_connectors,
            K.conn_id, K.mode.name, K.mode.hdisplay, K.mode.vdisplay, K.mode.vrefresh, K.crtc_id);
    drmModeFreeConnector(c);
    drmModeFreeResources(r);
    return 0;
}

static int open_card(void)
{
    static const char *cards[] = { "/dev/dri/card1", "/dev/dri/card0", "/dev/dri/card2" };
    unsigned i;
    for (i = 0; i < sizeof cards / sizeof *cards; i++) {
        int fd = open(cards[i], O_RDWR | O_CLOEXEC);
        if (fd < 0) continue;
        if (pick_output(fd) == 0) { sel_log("kms: %s", cards[i]); return fd; }
        close(fd);
    }
    sel_log("kms: no /dev/dri/card* with a connected output");
    return -1;
}

static void drop(struct egl_stern *e)
{
    int i;
    if (e->dpy) {
        eglMakeCurrent(e->dpy, 0, 0, 0);
        eglTerminate(e->dpy);
    }
    eglReleaseThread();
    for (i = 0; i < NBUF; i++) {
        if (K.fb[i] && K.fd >= 0) drmModeRmFB(K.fd, K.fb[i]);
        if (K.bo[i]) gbm_bo_destroy(K.bo[i]);
        K.fb[i] = 0; K.bo[i] = NULL; K.tex[i] = K.fbo[i] = 0;
    }
    if (K.gbm) gbm_device_destroy(K.gbm);
    K.gbm = NULL;
    if (K.fd >= 0) close(K.fd);
    K.fd = -1;
    e->dpy = e->cfg = e->ctx = NULL;
    e->up = 0;
}

/* one scanout buffer: a GBM bo, its EGL image as a texture, an FBO on it, a KMS fb */
static int make_buffer(struct egl_stern *e, int i, create_image_fn mkimg, image_target_fn target)
{
    int w = e->w, h = e->h, dfd, attr[16], n = 0;
    uint32_t stride;
    void *img;
    K.bo[i] = gbm_bo_create(K.gbm, (uint32_t)w, (uint32_t)h, GBM_FORMAT_XRGB8888,
                            GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
    if (!K.bo[i]) { sel_log("kms: gbm_bo_create %dx%d failed", w, h); return -1; }
    stride = gbm_bo_get_stride(K.bo[i]);
    dfd = gbm_bo_get_fd(K.bo[i]);
    if (dfd < 0) { sel_log("kms: gbm_bo_get_fd failed"); return -1; }
    attr[n++] = EGL_WIDTH; attr[n++] = w;
    attr[n++] = EGL_HEIGHT; attr[n++] = h;
    attr[n++] = EGL_LINUX_DRM_FOURCC_EXT; attr[n++] = (int)GBM_FORMAT_XRGB8888;
    attr[n++] = EGL_DMA_BUF_PLANE0_FD_EXT; attr[n++] = dfd;
    attr[n++] = EGL_DMA_BUF_PLANE0_OFFSET_EXT; attr[n++] = 0;
    attr[n++] = EGL_DMA_BUF_PLANE0_PITCH_EXT; attr[n++] = (int)stride;
    attr[n++] = EGL_NONE;
    img = mkimg(e->dpy, NULL, EGL_LINUX_DMA_BUF_EXT, NULL, attr);
    close(dfd);                          /* the image holds its own reference */
    if (!img) { sel_log("kms: eglCreateImageKHR failed, eglGetError=0x%x", eglGetError()); return -1; }
    glGenTextures(1, &K.tex[i]);
    glBindTexture(GL_TEXTURE_2D, K.tex[i]);
    target(GL_TEXTURE_2D, img);
    glGenFramebuffers(1, &K.fbo[i]);
    glBindFramebuffer(GL_FRAMEBUFFER, K.fbo[i]);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, K.tex[i], 0);
    {
        unsigned st = glCheckFramebufferStatus(GL_FRAMEBUFFER);
        if (st != GL_FRAMEBUFFER_COMPLETE && st != 0) {
            /* 0 = a bridge that does not answer (the emulator): the flips tell */
            sel_log("kms: buffer %d framebuffer incomplete (0x%x)", i, st);
            return -1;
        }
    }
    if (drmModeAddFB(K.fd, (uint32_t)w, (uint32_t)h, 24, 32, stride,
                     gbm_bo_get_handle(K.bo[i]).u32, &K.fb[i]) != 0) {
        sel_log("kms: drmModeAddFB failed (%s)", strerror(errno));
        return -1;
    }
    glBindTexture(GL_TEXTURE_2D, 0);
    return 0;
}

static int try_init(struct egl_stern *e)
{
    int maj = 0, min = 0, n = 0, i;
    create_image_fn mkimg;
    image_target_fn target;

    K.fd = open_card();
    if (K.fd < 0) return -1;
    e->w = K.mode.hdisplay;
    e->h = K.mode.vdisplay;
    K.gbm = gbm_create_device(K.fd);
    if (!K.gbm) { sel_log("kms: gbm_create_device failed"); return -1; }
    e->dpy = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, K.gbm, NULL);
    if (!e->dpy) e->dpy = eglGetDisplay(K.gbm);
    if (!e->dpy) { sel_log("kms: no EGL display on the GBM device"); return -1; }
    if (!eglInitialize(e->dpy, &maj, &min) || !egl_ok("eglInitialize")) return -1;
    if (!eglBindAPI(EGL_OPENGL_ES_API) || !egl_ok("eglBindAPI")) return -1;
    if (!eglChooseConfig(e->dpy, cfg_attr, &e->cfg, 1, &n) || n < 1) {
        sel_log("kms: eglChooseConfig gave %d configs", n);
        return -1;
    }
    e->ctx = eglCreateContext(e->dpy, e->cfg, NULL, ctx_attr);
    if (!e->ctx || !egl_ok("eglCreateContext")) return -1;
    /* surfaceless, as the game: every frame goes into a buffer of our own */
    if (!eglMakeCurrent(e->dpy, NULL, NULL, e->ctx) || !egl_ok("eglMakeCurrent")) return -1;
    mkimg = (create_image_fn)eglGetProcAddress("eglCreateImageKHR");
    target = (image_target_fn)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    if (!mkimg || !target) { sel_log("kms: no EGL image import (eglCreateImageKHR / OES_EGL_image)"); return -1; }
    for (i = 0; i < NBUF; i++)
        if (make_buffer(e, i, mkimg, target) < 0) return -1;
    K.back = 0; K.shown = 0; K.flip_pending = 0; K.flips_failed = 0;
    glViewport(0, 0, e->w, e->h);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    sel_log("kms: EGL %d.%d, display %dx%d, GL_VERSION '%s' renderer '%s'", maj, min, e->w, e->h,
            (const char *)glGetString(0x1F02), (const char *)glGetString(0x1F01));
    return 0;
}

static void build_program(struct egl_stern *e)
{
    unsigned vs, fs;
    float m[16];
    float w = (float)e->w, h = (float)e->h;
    float q[24] = { 0, 0, 0, 0,   w, 0, 1, 0,   w, h, 1, 1,
                    0, 0, 0, 0,   w, h, 1, 1,   0, h, 0, 1 };

    vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &VS, NULL);
    glCompileShader(vs);
    fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &FS, NULL);
    glCompileShader(fs);
    e->prog = glCreateProgram();
    glAttachShader(e->prog, vs);
    glAttachShader(e->prog, fs);
    glLinkProgram(e->prog);
    glUseProgram(e->prog);
    /* x 0..w left->right, canvas y 0..h -> GL y 0..h: the canvas's top row
     * lands in the buffer's row 0, the top of the scanout (see ROW ORDER) */
    memset(m, 0, sizeof m);
    m[0] = 2.0f / w;
    m[5] = 2.0f / h;
    m[10] = -1.0f;
    m[12] = -1.0f;
    m[13] = -1.0f;
    m[15] = 1.0f;
    glUniformMatrix4fv(glGetUniformLocation(e->prog, "projection"), 1, 0, m);
    glUniform1i(glGetUniformLocation(e->prog, "image"), 0);
    glGenVertexArrays(1, &e->vao);                     /* VAO + VBO: the bridge refuses client arrays */
    glBindVertexArray(e->vao);
    glGenBuffers(1, &e->vbo);
    glBindBuffer(GL_ARRAY_BUFFER, e->vbo);
    glBufferData(GL_ARRAY_BUFFER, (long)sizeof q, q, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 4, GL_FLOAT, 0, 4 * (int)sizeof(float), (const void *)0);
    glEnableVertexAttribArray(0);
}

int egl_stern_init(struct egl_stern *e, int retries, int retry_ms)
{
    int attempt;
    memset(e, 0, sizeof *e);
    if (retries < 1) retries = 1;
    for (attempt = 1; attempt <= retries; attempt++) {
        if (try_init(e) == 0) {
            build_program(e);
            e->up = 1;
            sel_log("kms: up after %d attempt(s), glGetError=0x%x", attempt, glGetError());
            return 0;
        }
        drop(e);
        if (attempt < retries) {
            sel_log("kms: attempt %d/%d failed, retrying in %d ms", attempt, retries, retry_ms);
            sel_sleep_ms(retry_ms);
        }
    }
    sel_log("kms: giving up after %d attempts", retries);
    return -1;
}

int egl_stern_texture(struct egl_stern *e, int w, int h, const unsigned char *px)
{
    if (!e->up) return -1;
    e->tex_w = w;
    e->tex_h = h;
    glActiveTexture(GL_TEXTURE0);
    glGenTextures(1, &e->tex);
    glBindTexture(GL_TEXTURE_2D, e->tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    sel_log("kms: canvas texture %u %dx%d, glGetError=0x%x", e->tex, w, h, glGetError());
    return 0;
}

static void on_flip(int fd, unsigned seq, unsigned s, unsigned us, void *data)
{
    (void)fd; (void)seq; (void)s; (void)us; (void)data;
    K.flip_pending = 0;
}

/* the last flip's event, or up to `ms` of waiting for it */
static void wait_flip(int ms)
{
    drm_evctx ctx;
    struct pollfd p;
    if (!K.flip_pending) return;
    memset(&ctx, 0, sizeof ctx);
    ctx.version = 2;
    ctx.page_flip_handler = on_flip;
    p.fd = K.fd; p.events = POLLIN; p.revents = 0;
    if (poll(&p, 1, ms) > 0) drmHandleEvent(K.fd, &ctx);
    if (K.flip_pending) K.flip_pending = 0;      /* never stall the menu on a lost event */
}

void egl_stern_frame(struct egl_stern *e, const unsigned char *packed, int x, int y, int w, int h)
{
    int b;
    if (!e->up) return;
    wait_flip(100);                               /* the buffer we draw into must be off screen */
    b = K.back;
    glBindTexture(GL_TEXTURE_2D, e->tex);
    if (packed && w > 0 && h > 0) {
        glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, packed);
        e->uploaded += (long long)w * h * 4;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, K.fbo[b]);
    glViewport(0, 0, e->w, e->h);
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    glFinish();
    if (!K.shown) {
        if (drmModeSetCrtc(K.fd, K.crtc_id, K.fb[b], 0, 0, &K.conn_id, 1, &K.mode) != 0)
            sel_log("kms: drmModeSetCrtc failed (%s)", strerror(errno));
        else
            sel_log("kms: first frame on crtc %u", K.crtc_id);
        K.shown = 1;
    } else if (drmModePageFlip(K.fd, K.crtc_id, K.fb[b], DRM_MODE_PAGE_FLIP_EVENT, NULL) == 0) {
        K.flip_pending = 1;
    } else {
        /* a flip refused (EBUSY after a lost event): show it the slow way */
        if (K.flips_failed++ < 3) sel_log("kms: page flip failed (%s), setting the crtc", strerror(errno));
        drmModeSetCrtc(K.fd, K.crtc_id, K.fb[b], 0, 0, &K.conn_id, 1, &K.mode);
    }
    K.back = (b + 1) % NBUF;
    e->frames++;
}

void egl_stern_close(struct egl_stern *e)
{
    if (!e->up) return;
    wait_flip(100);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindVertexArray(0);
    glUseProgram(0);
    glDisable(GL_BLEND);
    sel_log("kms: %d frames, %lld KB uploaded, closing (the game sets its own mode)",
            e->frames, e->uploaded / 1024);
    drop(e);
}
