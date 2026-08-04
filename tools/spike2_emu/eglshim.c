/* eglshim.c - becomes libEGL.so.1, and ONLY that.
 *
 * The GL state and the framebuffer live in glraster.c / libGLESv2.so.2. This
 * file must not be built from the same source: compiling one .c into both
 * shared objects gives each library its own copy of every static, so the
 * framebuffer eglSwapBuffers presents would not be the one the draw calls
 * wrote to. libEGL therefore links against libGLESv2 and calls into it.
 */

extern long write(int, const void *, unsigned long);
extern unsigned long strlen(const char *);
extern int gettimeofday(void *, void *);
extern int nanosleep(const void *, void *);
extern int snprintf(char *, unsigned long, const char *, ...);

/* provided by libGLESv2.so.2 (glraster.c) */
extern void pad_present(void);
extern int  pad_fb_width(void);
extern int  pad_fb_height(void);
extern long pad_readback_counts(long *, long *, long *, long *, long *, long *);
extern long pad_getintegerv_hist(unsigned int *, long *);
/* Extension entry points the backend implements, resolved by name. Both
 * backends define it; the rasteriser's returns 0 for everything. */
extern void *pad_gl_proc(const char *);

static void say(const char *s) { write(2, s, strlen(s)); }

#define EGL_SUCCESS 0x3000

int eglGetError(void) { return EGL_SUCCESS; }
void *eglGetDisplay(void *native) { (void)native; return (void *)0x1001; }

int eglInitialize(void *dpy, int *major, int *minor)
{
    (void)dpy;
    if (major) *major = 1;
    if (minor) *minor = 4;
    say("[eglshim] eglInitialize -> software raster\n");
    return 1;
}

int eglBindAPI(unsigned int api) { (void)api; return 1; }

int eglChooseConfig(void *dpy, const int *attr, void *cfgs, int n, int *num)
{
    (void)dpy; (void)attr;
    if (cfgs && n > 0) ((void **)cfgs)[0] = (void *)0x2001;
    if (num) *num = 1;
    return 1;
}

void *eglCreateContext(void *dpy, void *cfg, void *share, const int *attr)
{ (void)dpy; (void)cfg; (void)share; (void)attr; return (void *)0x3001; }

void *eglCreateWindowSurface(void *dpy, void *cfg, void *win, const int *attr)
{ (void)dpy; (void)cfg; (void)win; (void)attr; return (void *)0x4001; }

int eglMakeCurrent(void *dpy, void *draw, void *read, void *ctx)
{ (void)dpy; (void)draw; (void)read; (void)ctx; return 1; }

/* The game runs its boot at unbounded frame rate otherwise, and moves on
 * before the asynchronous asset loader has read anything. */
struct tv_ { long sec, usec; };
struct ts_ { long sec, nsec; };

static unsigned long long now_us(void)
{
    struct tv_ t;
    gettimeofday(&t, 0);
    return (unsigned long long)t.sec * 1000000ULL + (unsigned long long)t.usec;
}

int eglSwapBuffers(void *dpy, void *surf)
{
    static unsigned long long next_us;
    unsigned long long now = now_us();
    const unsigned long long frame_us = 16667;   /* 60 Hz */
    (void)dpy; (void)surf;

    pad_present();

    /* Achieved frame rate, so the cost of rasterising in emulated ARM is a
     * measured number rather than an impression. Compare a run against one
     * with PAD_GL_NORASTER=1 to separate raster cost from everything else. */
    {
        static unsigned long long t0;
        static int n;
        if (!t0) t0 = now;
        if (++n % 20 == 0) {
            char t[240];
            long e, iv, u, a, sh, pr, fr;
            fr = pad_readback_counts(&e, &iv, &u, &a, &sh, &pr);
            snprintf(t, sizeof t,
                     "[readback] after %ld frames: glGetError=%ld glGetIntegerv=%ld "
                     "GetUniformLocation=%ld GetAttribLocation=%ld GetShaderiv=%ld "
                     "GetProgramiv=%ld\n", fr, e, iv, u, a, sh, pr);
            say(t);
            {
                unsigned int names[8]; long counts[8]; int k;
                pad_getintegerv_hist(names, counts);
                for (k = 0; k < 8; k++) if (counts[k]) {
                    snprintf(t, sizeof t, "[readback]   glGetIntegerv(0x%x) x%ld\n",
                             names[k], counts[k]);
                    say(t);
                }
            }
            unsigned long long el = now - t0;
            int mfps = el ? (int)((unsigned long long)n * 1000000ULL * 10ULL / el) : 0;
            snprintf(t, sizeof t, "[eglshim] %d frames in %d ms = %d.%d fps\n",
                     n, (int)(el / 1000), mfps / 10, mfps % 10);
            say(t);
        }
    }

    if (!next_us) next_us = now;
    if (now < next_us) {
        struct ts_ req;
        unsigned long long d = next_us - now;
        req.sec = (long)(d / 1000000ULL);
        req.nsec = (long)((d % 1000000ULL) * 1000ULL);
        nanosleep(&req, 0);
    }
    next_us += frame_us;
    if (next_us < now) next_us = now + frame_us;
    return 1;
}

int eglTerminate(void *dpy) { (void)dpy; return 1; }
int eglReleaseThread(void) { return 1; }

/* Returning NULL here is fatal: the game calls whatever comes back without
 * checking, which lands on address 0 and spins in its own SIGSEGV handler.
 *
 * The blanket no-op that used to be the whole of this function is ALSO how
 * video stayed invisible for a whole pass. The game uploads its video frames
 * through glTexDirectVIVMap / glTexDirectInvalidateVIV, both of them Vivante
 * extensions and both of them reached only from here - so the frames arrived,
 * were handed to GL, and went into a function that returns 0. Ask the GL
 * backend by name first; the no-op is only the fallback it always was.
 *
 * Every distinct name is logged once. An extension the game wants and does not
 * get is now visible instead of silent. */
static int noop_entry(void) { return 0; }

void *eglGetProcAddress(const char *name)
{
    static char seen[16][48];
    static int nseen;
    void *p = name ? pad_gl_proc(name) : 0;
    int i;
    for (i = 0; i < nseen; i++) {
        const char *a = seen[i], *b = name;
        while (*a && *a == *b) { a++; b++; }
        if (!*a && !*b) return p ? p : (void *)noop_entry;
    }
    if (name && nseen < 16) {
        char buf[120];
        int j = 0;
        while (name[j] && j < 47) { seen[nseen][j] = name[j]; j++; }
        seen[nseen][j] = 0;
        nseen++;
        snprintf(buf, sizeof buf, "[eglshim] proc %s -> %s\n",
                 name, p ? "bridge" : "NO-OP (not implemented)");
        say(buf);
    }
    return p ? p : (void *)noop_entry;
}

/* ---- Vivante fbdev platform helpers the game calls directly ---- */
void *fbGetDisplayByIndex(int index) { (void)index; return (void *)0x6001; }

void fbGetDisplayGeometry(void *dpy, int *width, int *height)
{
    (void)dpy;
    if (width)  *width  = pad_fb_width();
    if (height) *height = pad_fb_height();
}

void *fbCreateWindow(void *dpy, int x, int y, int w, int h)
{ (void)dpy; (void)x; (void)y; (void)w; (void)h; return (void *)0x7001; }
