/* s3kms.c - the Spike 3 game's display hardware, faked (PAD-1090, stage 2).
 *
 * LD_PRELOAD (aarch64) into the card's own game. The game's window code
 * (Stern's own Godot display server, glWindow.cpp) drives the Pi's KMS
 * directly: it opens /dev/dri/card1 (or card0), walks drmModeGetResources ->
 * connector -> encoder -> crtc, creates GBM buffers, wraps them as EGL images
 * through their dma-buf fds, renders into them, and shows each one with
 * drmModeAddFB + drmModePageFlip, waiting for the flip through drmHandleEvent.
 * Under qemu-user there is no DRM device, so every one of those calls is
 * answered here instead, for the symbols the game imports (it is BIND_NOW, so
 * interposing by name is exact):
 *
 *   /dev/dri/card0|1   an eventfd: readable exactly when a flip is pending, so
 *                      the game's poll() on it behaves like the real device
 *   two connectors     both connected, 1920x1080@60 ($PAD_S3_W / $PAD_S3_H),
 *                      each with its own encoder and crtc: the Pi 4 has two
 *                      HDMI outputs and the game picks its screen BY INDEX
 *                      in drmModeRes.connectors - display_number 1, the
 *                      SECOND, on pokemon_le 0.82.0 (glWindow, 0x926c9c:
 *                      index < count_connectors, then connection == 1, else
 *                      "failed to get DRM connector for display_number N")
 *   gbm_bo             a struct of our own; get_fd hands out a dup'd memfd so
 *                      every bo has a distinct fd the EGL shim can map back
 *                      (pad_s3_bo_by_fd) when the game makes an EGL image
 *   page flip          pad_s3_flip(bo) -> the GL bridge presents the texture
 *                      that bo's EGL image was bound to (s3gl.c), then the
 *                      flip event is queued and the eventfd made readable
 *   two screens        PAD-1199: Fallout drives BOTH outputs - its backbox
 *                      on HDMI-A-2 (display_number 1, opened first) and the
 *                      Pip-Boy screen on HDMI-A-1 - flipping them in turn.
 *                      Every flip used to go to the one window, so the two
 *                      pictures alternated in it frame by frame. Each flip
 *                      now says which screen it is: the crtc the game shows
 *                      FIRST is the main window (display 0) and any other
 *                      crtc is the second window (display 1), so a one-screen
 *                      title is unchanged whichever output it picks. The
 *                      flip event hands back the crtc it was asked for, and
 *                      each crtc keeps its own current fb.
 *
 * Nothing here talks to the host renderer itself; it calls weak hooks in the
 * game's libGLESv2 (the bridge), so a run without the bridge still boots and
 * just shows nothing. [s3kms] lines go to stderr.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#include <dlfcn.h>
#include <pthread.h>

/* ---- libdrm's public structs, field for field (xf86drmMode.h / xf86drm.h) */
typedef struct {
    uint32_t clock;
    uint16_t hdisplay, hsync_start, hsync_end, htotal, hskew;
    uint16_t vdisplay, vsync_start, vsync_end, vtotal, vscan;
    uint32_t vrefresh, flags, type;
    char name[32];
} drmModeModeInfo;

typedef struct {
    int count_fbs; uint32_t *fbs;
    int count_crtcs; uint32_t *crtcs;
    int count_connectors; uint32_t *connectors;
    int count_encoders; uint32_t *encoders;
    uint32_t min_width, max_width, min_height, max_height;
} drmModeRes;

typedef struct {
    uint32_t connector_id, encoder_id, connector_type, connector_type_id;
    int connection;                       /* 1 = DRM_MODE_CONNECTED */
    uint32_t mmWidth, mmHeight;
    int subpixel;
    int count_modes; drmModeModeInfo *modes;
    int count_props; uint32_t *props; uint64_t *prop_values;
    int count_encoders; uint32_t *encoders;
} drmModeConnector;

typedef struct {
    uint32_t encoder_id, encoder_type, crtc_id, possible_crtcs, possible_clones;
} drmModeEncoder;

typedef struct {
    uint32_t crtc_id, buffer_id, x, y, width, height;
    int mode_valid;
    drmModeModeInfo mode;
    int gamma_size;
} drmModeCrtc;

typedef struct {
    int version;
    void (*vblank_handler)(int, unsigned, unsigned, unsigned, void *);
    void (*page_flip_handler)(int, unsigned, unsigned, unsigned, void *);
    void (*page_flip_handler2)(int, unsigned, unsigned, unsigned, unsigned, void *);
    void (*sequence_handler)(int, uint64_t, uint64_t, uint64_t);
} drmEventContext;

/* ---- our ids: output i (0, 1) is connector 31+i, encoder 41+i, crtc 51+i */
#define NOUT     2
#define CONN_ID  31
#define ENC_ID   41
#define CRTC_ID  51
#define CONN_HDMIA 11

/* ---- the gbm objects ---------------------------------------------------- */
struct gbm_device { int fd; };
struct gbm_bo {
    struct gbm_device *dev;
    uint32_t w, h, stride, format, flags, handle;
    int dmafd;                    /* our memfd, what gbm_bo_get_fd dups      */
    void *map;                    /* gbm_bo_map's pixels, made on demand     */
    void *user_data;
    void (*destroy_user_data)(struct gbm_bo *, void *);
};
union gbm_bo_handle { void *ptr; int32_t s32; uint32_t u32; int64_t s64; uint64_t u64; };

#define MAXBO 64
static struct gbm_bo *bos[MAXBO];
static int bo_fds[MAXBO][8];      /* every fd handed out for each bo         */
static uint32_t fb_bo[256];       /* fb id -> bo handle                      */
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;

static int card_fd = -1;          /* the eventfd standing in for card1       */
static int pend_n;                /* flips queued for drmHandleEvent         */
static void *pend_data[8];
static uint32_t pend_crtc[8];     /* the crtc each queued flip was for   */
static unsigned flip_seq, flips;
static uint32_t cur_fb[NOUT];     /* each crtc's current fb (GetCrtc)        */
static uint32_t main_crtc;        /* the first crtc shown: the main window   */
static int scr_w = 1920, scr_h = 1080;

static void say(const char *fmt, ...)
{
    char b[400]; va_list ap; int n;
    va_start(ap, fmt); n = vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
    if (n > 0) { if (n > (int)sizeof b - 1) n = sizeof b - 1; (void)!write(2, b, n); }
}

static void init_once(void)
{
    static int done;
    const char *e;
    if (done) return;
    done = 1;
    if ((e = getenv("PAD_S3_W")) && atoi(e) > 0) scr_w = atoi(e);
    if ((e = getenv("PAD_S3_H")) && atoi(e) > 0) scr_h = atoi(e);
    say("[s3kms] fake KMS: %d HDMI-A connectors, %dx%d@60\n", NOUT, scr_w, scr_h);
}

/* hooks into the bridge (s3gl.c, in the game's libGLESv2); weak so the shim
 * works without one */
extern void pad_s3_present_bo(uint32_t handle, uint32_t w, uint32_t h,
                              uint32_t disp) __attribute__((weak));

/* ---- the device node ---------------------------------------------------- */
static int is_card(const char *p)
{
    return p && (!strcmp(p, "/dev/dri/card0") || !strcmp(p, "/dev/dri/card1"));
}

static int open_card(const char *p)
{
    init_once();
    if (card_fd < 0) {
        card_fd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
        say("[s3kms] %s -> fd %d\n", p, card_fd);
    }
    return dup(card_fd);
}

typedef int (*open_fn)(const char *, int, ...);
int open(const char *p, int fl, ...)
{
    static open_fn real;
    mode_t m = 0;
    if (fl & O_CREAT) { va_list ap; va_start(ap, fl); m = va_arg(ap, mode_t); va_end(ap); }
    if (is_card(p)) return open_card(p);
    if (!real) real = (open_fn)dlsym(RTLD_NEXT, "open");
    return real(p, fl, m);
}
int open64(const char *p, int fl, ...) __attribute__((alias("open")));

typedef int (*openat_fn)(int, const char *, int, ...);
int openat(int d, const char *p, int fl, ...)
{
    static openat_fn real;
    mode_t m = 0;
    if (fl & O_CREAT) { va_list ap; va_start(ap, fl); m = va_arg(ap, mode_t); va_end(ap); }
    if (is_card(p)) return open_card(p);
    if (!real) real = (openat_fn)dlsym(RTLD_NEXT, "openat");
    return real(d, p, fl, m);
}

/* ---- modesetting -------------------------------------------------------- */
static void fill_mode(drmModeModeInfo *m)
{
    memset(m, 0, sizeof *m);
    m->clock = 148500;
    m->hdisplay = scr_w; m->hsync_start = scr_w + 88; m->hsync_end = scr_w + 132;
    m->htotal = scr_w + 280;
    m->vdisplay = scr_h; m->vsync_start = scr_h + 4; m->vsync_end = scr_h + 9;
    m->vtotal = scr_h + 45;
    m->vrefresh = 60;
    m->flags = 0x5;                       /* PHSYNC | PVSYNC */
    m->type = 0x48;                       /* DRIVER | PREFERRED */
    snprintf(m->name, sizeof m->name, "%dx%d", scr_w, scr_h);
}

drmModeRes *drmModeGetResources(int fd)
{
    drmModeRes *r = calloc(1, sizeof *r);
    (void)fd; init_once();
    int i;
    r->count_crtcs = r->count_connectors = r->count_encoders = NOUT;
    r->crtcs = malloc(4 * NOUT); r->connectors = malloc(4 * NOUT); r->encoders = malloc(4 * NOUT);
    for (i = 0; i < NOUT; i++) {
        r->crtcs[i] = CRTC_ID + i; r->connectors[i] = CONN_ID + i; r->encoders[i] = ENC_ID + i;
    }
    r->min_width = r->min_height = 1; r->max_width = r->max_height = 8192;
    say("[s3kms] drmModeGetResources\n");
    return r;
}
void drmModeFreeResources(drmModeRes *r)
{
    if (!r) return;
    free(r->crtcs); free(r->connectors); free(r->encoders); free(r->fbs); free(r);
}

drmModeConnector *drmModeGetConnector(int fd, uint32_t id)
{
    drmModeConnector *c;
    (void)fd;
    if (id < CONN_ID || id >= CONN_ID + NOUT) return NULL;
    c = calloc(1, sizeof *c);
    c->connector_id = id; c->encoder_id = ENC_ID + (id - CONN_ID);
    c->connector_type = CONN_HDMIA; c->connector_type_id = 1 + (id - CONN_ID);
    c->connection = 1; c->mmWidth = 527; c->mmHeight = 296; c->subpixel = 1;
    c->count_modes = 1; c->modes = malloc(sizeof *c->modes); fill_mode(c->modes);
    c->count_encoders = 1; c->encoders = malloc(4); c->encoders[0] = c->encoder_id;
    say("[s3kms] drmModeGetConnector %u (HDMI-A-%u)\n", id, c->connector_type_id);
    return c;
}
void drmModeFreeConnector(drmModeConnector *c)
{
    if (!c) return;
    free(c->modes); free(c->encoders); free(c->props); free(c->prop_values); free(c);
}

drmModeEncoder *drmModeGetEncoder(int fd, uint32_t id)
{
    drmModeEncoder *e;
    (void)fd;
    if (id < ENC_ID || id >= ENC_ID + NOUT) return NULL;
    e = calloc(1, sizeof *e);
    e->encoder_id = id; e->encoder_type = 2;      /* TMDS */
    e->crtc_id = CRTC_ID + (id - ENC_ID); e->possible_crtcs = 1u << (id - ENC_ID);
    return e;
}
void drmModeFreeEncoder(drmModeEncoder *e) { free(e); }

drmModeCrtc *drmModeGetCrtc(int fd, uint32_t id)
{
    drmModeCrtc *c;
    (void)fd;
    if (id < CRTC_ID || id >= CRTC_ID + NOUT) return NULL;
    c = calloc(1, sizeof *c);
    c->crtc_id = id; c->buffer_id = cur_fb[id - CRTC_ID];
    c->width = scr_w; c->height = scr_h; c->mode_valid = 1; fill_mode(&c->mode);
    c->gamma_size = 256;
    return c;
}
void drmModeFreeCrtc(drmModeCrtc *c) { free(c); }

static struct gbm_bo *bo_by_handle(uint32_t h)
{
    return (h && h <= MAXBO) ? bos[h - 1] : NULL;
}

int drmModeAddFB(int fd, uint32_t w, uint32_t h, uint8_t depth, uint8_t bpp,
                 uint32_t pitch, uint32_t handle, uint32_t *fb_id)
{
    uint32_t i;
    (void)fd; (void)depth; (void)bpp; (void)pitch;
    pthread_mutex_lock(&mu);
    for (i = 1; i < 256 && fb_bo[i]; i++) {}
    if (i < 256) fb_bo[i] = handle;
    pthread_mutex_unlock(&mu);
    if (i >= 256) return -ENOSPC;
    *fb_id = 100 + i;
    say("[s3kms] AddFB %ux%u bo %u -> fb %u\n", w, h, handle, *fb_id);
    return 0;
}

int drmModeRmFB(int fd, uint32_t fb)
{
    (void)fd;
    if (fb >= 100 && fb < 356) fb_bo[fb - 100] = 0;
    return 0;
}

/* Which window a crtc's pictures go to: 0 = the main one (the first crtc the
 * game shows), 1 = the second. An id that is no crtc of ours is the main. */
static uint32_t disp_of(uint32_t crtc)
{
    if (crtc < CRTC_ID || crtc >= CRTC_ID + NOUT) return 0;
    if (!main_crtc) {
        main_crtc = crtc;
        say("[s3kms] crtc %u (HDMI-A-%u) is the main window\n", crtc, 1 + crtc - CRTC_ID);
    }
    if (crtc == main_crtc) return 0;
    {
        static int said;
        if (!said++)
            say("[s3kms] crtc %u (HDMI-A-%u) shows too: a second screen, its own window\n",
                crtc, 1 + crtc - CRTC_ID);
    }
    return 1;
}

static void show_fb(uint32_t crtc, uint32_t fb)
{
    uint32_t h = (fb >= 100 && fb < 356) ? fb_bo[fb - 100] : 0;
    struct gbm_bo *bo = bo_by_handle(h);
    uint32_t d = disp_of(crtc);
    if (crtc >= CRTC_ID && crtc < CRTC_ID + NOUT) cur_fb[crtc - CRTC_ID] = fb;
    flips++;
    if (flips == 1 || flips == 60 || flips % 1800 == 0)
        say("[s3kms] flip %u: crtc %u fb %u (bo %u %ux%u) display %u%s\n", flips, crtc, fb, h,
            bo ? bo->w : 0, bo ? bo->h : 0, d,
            pad_s3_present_bo ? "" : " - no bridge, nothing shown");
    if (bo && pad_s3_present_bo) pad_s3_present_bo(h, bo->w, bo->h, d);
}

int drmModeSetCrtc(int fd, uint32_t crtc, uint32_t fb, uint32_t x, uint32_t y,
                   uint32_t *conns, int count, drmModeModeInfo *mode)
{
    (void)fd; (void)x; (void)y; (void)conns; (void)count; (void)mode;
    say("[s3kms] SetCrtc %u fb %u\n", crtc, fb);
    if (fb) show_fb(crtc, fb);
    return 0;
}

int drmModePageFlip(int fd, uint32_t crtc, uint32_t fb, uint32_t flags, void *data)
{
    uint64_t one = 1;
    (void)fd; (void)flags;
    show_fb(crtc, fb);
    pthread_mutex_lock(&mu);
    if (pend_n < 8) { pend_crtc[pend_n] = crtc; pend_data[pend_n++] = data; }
    pthread_mutex_unlock(&mu);
    (void)!write(card_fd, &one, sizeof one);
    return 0;
}

int drmHandleEvent(int fd, drmEventContext *ctx)
{
    uint64_t v;
    void *d[8];
    uint32_t c[8];
    int n, i;
    struct timespec ts;
    (void)fd;
    (void)!read(card_fd, &v, sizeof v);
    pthread_mutex_lock(&mu);
    n = pend_n; memcpy(d, pend_data, sizeof d); memcpy(c, pend_crtc, sizeof c); pend_n = 0;
    pthread_mutex_unlock(&mu);
    clock_gettime(CLOCK_MONOTONIC, &ts);
    for (i = 0; i < n; i++) {
        flip_seq++;
        if (ctx->version >= 3 && ctx->page_flip_handler2)
            ctx->page_flip_handler2(card_fd, flip_seq, ts.tv_sec, ts.tv_nsec / 1000, c[i], d[i]);
        else if (ctx->page_flip_handler)
            ctx->page_flip_handler(card_fd, flip_seq, ts.tv_sec, ts.tv_nsec / 1000, d[i]);
    }
    return 0;
}

/* ---- gbm ---------------------------------------------------------------- */
struct gbm_device *gbm_create_device(int fd)
{
    struct gbm_device *d = calloc(1, sizeof *d);
    d->fd = fd;
    say("[s3kms] gbm_create_device(fd %d)\n", fd);
    return d;
}
void gbm_device_destroy(struct gbm_device *d) { free(d); }
int gbm_device_get_fd(struct gbm_device *d) { return d->fd; }

struct gbm_bo *gbm_bo_create(struct gbm_device *dev, uint32_t w, uint32_t h,
                             uint32_t format, uint32_t flags)
{
    struct gbm_bo *bo;
    int i;
    pthread_mutex_lock(&mu);
    for (i = 0; i < MAXBO && bos[i]; i++) {}
    if (i == MAXBO) { pthread_mutex_unlock(&mu); return NULL; }
    bo = calloc(1, sizeof *bo);
    bo->dev = dev; bo->w = w; bo->h = h; bo->format = format; bo->flags = flags;
    bo->stride = w * 4; bo->handle = (uint32_t)i + 1;
    bo->dmafd = (int)syscall(SYS_memfd_create, "pad-s3-bo", 0);
    bos[i] = bo;
    memset(bo_fds[i], -1, sizeof bo_fds[i]);
    pthread_mutex_unlock(&mu);
    say("[s3kms] gbm_bo_create %ux%u fmt %.4s flags 0x%x -> bo %u\n",
        w, h, (const char *)&format, flags, bo->handle);
    return bo;
}

void gbm_bo_destroy(struct gbm_bo *bo)
{
    int k;
    if (!bo) return;
    if (bo->destroy_user_data) bo->destroy_user_data(bo, bo->user_data);
    pthread_mutex_lock(&mu);
    bos[bo->handle - 1] = NULL;
    for (k = 0; k < 8; k++) bo_fds[bo->handle - 1][k] = -1;
    pthread_mutex_unlock(&mu);
    if (bo->map) free(bo->map);
    close(bo->dmafd);
    free(bo);
}

uint32_t gbm_bo_get_width(struct gbm_bo *bo)  { return bo->w; }
uint32_t gbm_bo_get_height(struct gbm_bo *bo) { return bo->h; }
uint32_t gbm_bo_get_stride(struct gbm_bo *bo) { return bo->stride; }
uint32_t gbm_bo_get_format(struct gbm_bo *bo) { return bo->format; }
struct gbm_device *gbm_bo_get_device(struct gbm_bo *bo) { return bo->dev; }
union gbm_bo_handle gbm_bo_get_handle(struct gbm_bo *bo)
{ union gbm_bo_handle u; u.u64 = 0; u.u32 = bo->handle; return u; }
void gbm_bo_set_user_data(struct gbm_bo *bo, void *d, void (*fn)(struct gbm_bo *, void *))
{ bo->user_data = d; bo->destroy_user_data = fn; }
void *gbm_bo_get_user_data(struct gbm_bo *bo) { return bo->user_data; }

int gbm_bo_get_fd(struct gbm_bo *bo)
{
    int fd = dup(bo->dmafd), k;
    pthread_mutex_lock(&mu);
    for (k = 0; k < 8; k++)
        if (bo_fds[bo->handle - 1][k] < 0) { bo_fds[bo->handle - 1][k] = fd; break; }
    pthread_mutex_unlock(&mu);
    return fd;
}

/* The EGL shim's way back from a dma-buf fd to the bo it is (0 = not ours). */
uint32_t pad_s3_bo_by_fd(int fd, uint32_t *w, uint32_t *h)
{
    int i, k;
    uint32_t r = 0;
    pthread_mutex_lock(&mu);
    for (i = 0; i < MAXBO && !r; i++)
        if (bos[i])
            for (k = 0; k < 8; k++)
                if (bo_fds[i][k] == fd) { r = bos[i]->handle; *w = bos[i]->w; *h = bos[i]->h; break; }
    pthread_mutex_unlock(&mu);
    return r;
}

/* s3gl.c's way to a bo's size from its handle (0 = no such bo). */
unsigned pad_s3_bo_size(unsigned handle, unsigned *w, unsigned *h)
{
    struct gbm_bo *bo = bo_by_handle(handle);
    if (!bo) return 0;
    *w = bo->w; *h = bo->h;
    return 1;
}

void *gbm_bo_map(struct gbm_bo *bo, uint32_t x, uint32_t y, uint32_t w, uint32_t h,
                 uint32_t flags, uint32_t *stride, void **map_data)
{
    (void)w; (void)h; (void)flags;
    if (!bo->map) bo->map = calloc(1, (size_t)bo->stride * bo->h);
    *stride = bo->stride;
    *map_data = bo->map;
    return (char *)bo->map + (size_t)y * bo->stride + x * 4;
}
void gbm_bo_unmap(struct gbm_bo *bo, void *map_data) { (void)bo; (void)map_data; }
