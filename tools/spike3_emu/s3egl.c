/* s3egl.c - the Spike 3 game's libEGL.so.1 (PAD-1090, stage 2).
 *
 * The game's display server (Godot 4, Stern's glWindow.cpp) runs EGL on the
 * GBM platform with no window surface at all: it renders into GBM buffers it
 * wraps as EGL images (dma-buf import) and page-flips them through KMS. So
 * this EGL is mostly bookkeeping:
 *
 *   eglGetPlatformDisplay(EXT)  any platform -> one display
 *   configs / contexts          one of each kind, every attribute answered
 *                               from an RGBA8888 + D24S8 config
 *   eglMakeCurrent              surfaceless is fine; nothing to emit
 *   eglCreateImageKHR           EGL_LINUX_DMA_BUF_EXT (plane 0 fd) or
 *                               EGL_NATIVE_PIXMAP_KHR (a gbm_bo*) -> the bo's
 *                               handle, which s3gl.c's
 *                               glEGLImageTargetTexture2DOES turns into a
 *                               texture and s3kms.c's page flip presents
 *   fence syncs                 always signalled (the bridge has one stream)
 *   eglGetProcAddress           the bridge first (pad_gl_proc), then this
 *                               file; anything else is logged once and gets
 *                               a no-op, as on Spike 2
 *
 * eglGetError is EGL_SUCCESS throughout: glWindow::setGlContext asserts on it,
 * and that assertion is where every Spike 3 card stopped before this file.
 * Built -nostdlib against the card's own libc, like the Spike 2 shims.
 */
extern long write(int, const void *, unsigned long);
extern unsigned long strlen(const char *);
extern int strcmp(const char *, const char *);
extern char *strstr(const char *, const char *);
extern int snprintf(char *, unsigned long, const char *, ...);

extern void *pad_gl_proc(const char *);
extern unsigned pad_s3_bo_by_fd(int fd, unsigned *w, unsigned *h) __attribute__((weak));

#define EGL_SUCCESS            0x3000
#define EGL_NONE               0x3038
#define EGL_WIDTH              0x3057
#define EGL_HEIGHT             0x3056
#define EGL_NATIVE_PIXMAP_KHR  0x30B0
#define EGL_LINUX_DMA_BUF_EXT  0x3270
#define EGL_DMA_BUF_PLANE0_FD  0x3272
#define S3IMG_BASE             0x5300000ul

static void say(const char *s) { write(2, s, strlen(s)); }

static void sayf1(const char *fmt, unsigned long a, unsigned long b, unsigned long c)
{
    char m[200];
    snprintf(m, sizeof m, fmt, a, b, c);
    say(m);
}

/* ---- displays ----------------------------------------------------------- */
#define DPY ((void *)0x1001)
int   eglGetError(void) { return EGL_SUCCESS; }
void *eglGetDisplay(void *native) { (void)native; return DPY; }
void *eglGetPlatformDisplay(unsigned plat, void *native, const long *attr)
{
    (void)native; (void)attr;
    sayf1("[s3egl] eglGetPlatformDisplay(platform 0x%lx)\n", plat, 0, 0);
    return DPY;
}
void *eglGetPlatformDisplayEXT(unsigned plat, void *native, const int *attr)
{ (void)attr; return eglGetPlatformDisplay(plat, native, 0); }

int eglInitialize(void *dpy, int *major, int *minor)
{
    (void)dpy;
    if (major) *major = 1;
    if (minor) *minor = 5;
    say("[s3egl] eglInitialize: GLES through the PAD GL bridge\n");
    return 1;
}
int eglTerminate(void *dpy) { (void)dpy; return 1; }
int eglReleaseThread(void) { return 1; }
int eglBindAPI(unsigned api) { (void)api; return 1; }
unsigned eglQueryAPI(void) { return 0x30A0; }       /* EGL_OPENGL_ES_API */

static const char EXTS[] =
    "EGL_KHR_platform_gbm EGL_MESA_platform_gbm EGL_EXT_platform_base "
    "EGL_KHR_image_base EGL_KHR_image EGL_EXT_image_dma_buf_import "
    "EGL_EXT_image_dma_buf_import_modifiers EGL_KHR_surfaceless_context "
    "EGL_KHR_no_config_context EGL_KHR_fence_sync EGL_KHR_wait_sync "
    "EGL_KHR_create_context EGL_KHR_gl_texture_2D_image";

const char *eglQueryString(void *dpy, int name)
{
    (void)dpy;
    switch (name) {
    case 0x3053: return "PAD";                       /* EGL_VENDOR */
    case 0x3054: return "1.5 PAD bridge";            /* EGL_VERSION */
    case 0x3055: return EXTS;                        /* EGL_EXTENSIONS */
    case 0x308D: return "OpenGL_ES";                 /* EGL_CLIENT_APIS */
    }
    return "";
}

/* ---- configs ------------------------------------------------------------
 * TWO configs, one per GBM scan-out format. glWindow walks eglGetConfigs and
 * takes the one whose EGL_NATIVE_VISUAL_ID equals the format of its GBM
 * buffers - XR24 (XRGB8888) on pokemon_le 0.82.0 - and with only an AR24
 * config here it logged "failed to find egl config for gbm format" and
 * retried create_window for ever (PAD-1090). */
#define NCFG 2
static const unsigned cfg_visual[NCFG] = { 0x34325258u /* XR24 */, 0x34325241u /* AR24 */ };
#define CFG(i) ((void *)(0x2001ul + (i)))
static int cfg_index(void *cfg)
{
    unsigned long v = (unsigned long)cfg;
    return (v >= 0x2001ul && v < 0x2001ul + NCFG) ? (int)(v - 0x2001ul) : 0;
}

int eglGetConfigs(void *dpy, void **cfgs, int n, int *num)
{
    int i;
    (void)dpy;
    if (!cfgs) { if (num) *num = NCFG; return 1; }
    for (i = 0; i < n && i < NCFG; i++) cfgs[i] = CFG(i);
    if (num) *num = i;
    return 1;
}
int eglChooseConfig(void *dpy, const int *attr, void **cfgs, int n, int *num)
{ (void)attr; return eglGetConfigs(dpy, cfgs, n, num); }

int eglGetConfigAttrib(void *dpy, void *cfg, int a, int *v)
{
    int i = cfg_index(cfg);
    (void)dpy;
    if (!v) return 0;
    switch (a) {
    case 0x3024: case 0x3023: case 0x3022: *v = 8; break;  /* R G B */
    case 0x3021: *v = i == 0 ? 0 : 8; break;         /* ALPHA: XR24 has none */
    case 0x3020: *v = i == 0 ? 24 : 32; break;       /* BUFFER_SIZE */
    case 0x3025: *v = 24; break;                     /* DEPTH_SIZE */
    case 0x3026: *v = 8;  break;                     /* STENCIL_SIZE */
    case 0x302E: *v = (int)cfg_visual[i]; break;     /* NATIVE_VISUAL_ID = GBM format */
    case 0x3040: *v = 0x0044; break;                 /* RENDERABLE_TYPE: ES2|ES3 */
    case 0x3042: *v = 0x0044; break;                 /* CONFORMANT */
    case 0x3033: *v = 0x0005; break;                 /* SURFACE_TYPE: window|pbuffer */
    case 0x3028: *v = i + 1; break;                  /* CONFIG_ID */
    case 0x3031: case 0x3032: *v = 0; break;         /* SAMPLES, SAMPLE_BUFFERS */
    default: *v = 0;
    }
    return 1;
}

/* ---- contexts and surfaces ---------------------------------------------- */
static unsigned nctx;
void *eglCreateContext(void *dpy, void *cfg, void *share, const int *attr)
{
    (void)dpy; (void)cfg; (void)attr;
    nctx++;
    sayf1("[s3egl] eglCreateContext #%lu (share %lx)\n", nctx, (unsigned long)share, 0);
    return (void *)(0x3000ul + nctx);
}
int eglDestroyContext(void *dpy, void *ctx) { (void)dpy; (void)ctx; return 1; }
int eglMakeCurrent(void *dpy, void *d, void *r, void *ctx)
{ (void)dpy; (void)d; (void)r; (void)ctx; return 1; }
void *eglGetCurrentContext(void) { return (void *)0x3001; }
void *eglGetCurrentDisplay(void) { return DPY; }
void *eglGetCurrentSurface(int which) { (void)which; return 0; }

void *eglCreateWindowSurface(void *dpy, void *cfg, void *win, const int *attr)
{ (void)dpy; (void)cfg; (void)win; (void)attr;
  say("[s3egl] eglCreateWindowSurface (unexpected on Spike 3)\n"); return (void *)0x4001; }
void *eglCreatePlatformWindowSurface(void *dpy, void *cfg, void *win, const long *attr)
{ (void)attr; return eglCreateWindowSurface(dpy, cfg, win, 0); }
void *eglCreatePbufferSurface(void *dpy, void *cfg, const int *attr)
{ (void)dpy; (void)cfg; (void)attr; return (void *)0x4002; }
int eglDestroySurface(void *dpy, void *s) { (void)dpy; (void)s; return 1; }
int eglSwapBuffers(void *dpy, void *s) { (void)dpy; (void)s; return 1; }
int eglSwapInterval(void *dpy, int n) { (void)dpy; (void)n; return 1; }
int eglQuerySurface(void *dpy, void *s, int a, int *v) { (void)dpy; (void)s; (void)a; if (v) *v = 0; return 1; }
int eglWaitClient(void) { return 1; }
int eglWaitGL(void) { return 1; }
int eglWaitNative(int e) { (void)e; return 1; }

/* ---- EGL images: a bo, by its dma-buf fd or its gbm_bo* ------------------ */
struct gbm_bo_head { void *dev; unsigned w, h, stride, format, flags, handle; };

void *eglCreateImageKHR(void *dpy, void *ctx, unsigned target, void *buf, const int *attr)
{
    unsigned h = 0, w = 0, hh = 0;
    int i;
    (void)dpy; (void)ctx;
    if (target == EGL_LINUX_DMA_BUF_EXT && attr && pad_s3_bo_by_fd) {
        for (i = 0; attr[i] != EGL_NONE && i < 64; i += 2)
            if (attr[i] == EGL_DMA_BUF_PLANE0_FD) h = pad_s3_bo_by_fd(attr[i + 1], &w, &hh);
    } else if (target == EGL_NATIVE_PIXMAP_KHR && buf) {
        const struct gbm_bo_head *bo = (const struct gbm_bo_head *)buf;
        h = bo->handle; w = bo->w; hh = bo->h;
    }
    if (!h) {
        sayf1("[s3egl] eglCreateImageKHR target 0x%lx: not a bo of ours\n", target, 0, 0);
        return 0;
    }
    sayf1("[s3egl] EGL image of bo %lu (%lux", h, w, 0);
    sayf1("%lu)\n", hh, 0, 0);
    return (void *)(S3IMG_BASE + h);
}
void *eglCreateImage(void *dpy, void *ctx, unsigned target, void *buf, const long *attr)
{
    int a[64]; int i;
    for (i = 0; attr && i < 63 && attr[i] != EGL_NONE; i++) a[i] = (int)attr[i];
    a[i] = EGL_NONE;
    return eglCreateImageKHR(dpy, ctx, target, buf, a);
}
int eglDestroyImageKHR(void *dpy, void *img) { (void)dpy; (void)img; return 1; }
int eglDestroyImage(void *dpy, void *img) { (void)dpy; (void)img; return 1; }

/* ---- fences: one ordered stream, so every fence is already signalled ---- */
void *eglCreateSyncKHR(void *dpy, unsigned type, const int *attr)
{ (void)dpy; (void)type; (void)attr; return (void *)0x6001; }
void *eglCreateSync(void *dpy, unsigned type, const long *attr)
{ (void)dpy; (void)type; (void)attr; return (void *)0x6001; }
int eglDestroySyncKHR(void *dpy, void *s) { (void)dpy; (void)s; return 1; }
int eglDestroySync(void *dpy, void *s) { (void)dpy; (void)s; return 1; }
int eglClientWaitSyncKHR(void *dpy, void *s, int fl, unsigned long long t)
{ (void)dpy; (void)s; (void)fl; (void)t; return 0x30F6; }   /* CONDITION_SATISFIED */
int eglClientWaitSync(void *dpy, void *s, int fl, unsigned long long t)
{ return eglClientWaitSyncKHR(dpy, s, fl, t); }
int eglWaitSyncKHR(void *dpy, void *s, int fl) { (void)dpy; (void)s; (void)fl; return 1; }
int eglWaitSync(void *dpy, void *s, int fl) { (void)dpy; (void)s; (void)fl; return 1; }

/* ---- proc lookup -------------------------------------------------------- */
static int noop_entry(void) { return 0; }

#define OWN(n) if (!strcmp(name, #n)) return (void *)n
void *eglGetProcAddress(const char *name)
{
    static char seen[48][56];
    static int nseen;
    void *p;
    int i, j;
    if (!name) return (void *)noop_entry;
    OWN(eglGetPlatformDisplayEXT); OWN(eglGetPlatformDisplay);
    OWN(eglCreateImageKHR); OWN(eglDestroyImageKHR);
    OWN(eglCreateImage); OWN(eglDestroyImage);
    OWN(eglCreateSyncKHR); OWN(eglDestroySyncKHR); OWN(eglClientWaitSyncKHR);
    OWN(eglWaitSyncKHR); OWN(eglCreateSync); OWN(eglDestroySync);
    OWN(eglClientWaitSync); OWN(eglWaitSync);
    OWN(eglCreatePlatformWindowSurface); OWN(eglSwapInterval);
    p = pad_gl_proc(name);
    for (i = 0; i < nseen; i++)
        if (!strcmp(seen[i], name)) return p ? p : (void *)noop_entry;
    if (nseen < 48) {
        char buf[140];
        for (j = 0; name[j] && j < 55; j++) seen[nseen][j] = name[j];
        seen[nseen][j] = 0;
        nseen++;
        snprintf(buf, sizeof buf, "[s3egl] proc %s -> %s\n", name,
                 p ? "bridge" : "NO-OP (not implemented)");
        say(buf);
    }
    return p ? p : (void *)noop_entry;
}
