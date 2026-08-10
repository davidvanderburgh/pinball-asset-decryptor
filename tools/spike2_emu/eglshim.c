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
extern char *getenv(const char *);

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

/* ★ ITEM 27, THE STAR WARS FLICKER: THE GAME HAS MORE THAN ONE SURFACE, AND
 * THIS FILE USED TO COLLAPSE THEM INTO ONE SWAP CHAIN.
 *
 * Every eglCreateWindowSurface returned the same 0x4001 and every
 * eglSwapBuffers presented, so a title that renders TWO scene compositions -
 * star_wars_le draws one scene with ch1's clip and another with ch2's, on
 * alternating swaps, measured by padglhost's swap-content mask as a perfect
 * `2x60 4x60 no-draw 0/120` - had both presented to the one window at 60 Hz.
 * On the screen that is two different pictures interleaving: the "flickering
 * a lot" David reported on Star Wars, and during Tech Alerts (second scene
 * dark) it read as the alerts screen alternating with black, 32.8% black
 * frames in a 75 s capture. Godzilla and Jaws create one surface and never
 * flickered - `0x60 1x60`, the benign 30-on-60 alternation.
 *
 * So surfaces carry IDENTITY now, chained from the display the game asked
 * for: fbGetDisplayByIndex(index) -> display handle 0x6000|index ->
 * fbCreateWindow -> window handle 0x7000|index -> eglCreateWindowSurface ->
 * surface handle 0x4000|slot, with the slot's display recorded. Only the
 * PRIMARY surface presents: the first one created on display 0 (the backbox
 * LCD on every Spike 2 cabinet), or the first created if none says display
 * 0. PAD_EGL_PRIMARY=<slot> overrides for A/B - if the wrong scene survives
 * on some title, flip it without a rebuild.
 *
 * The suppressed surface's DRAWS still stream to the renderer - only its
 * present is swallowed. That is safe because every scene render begins with
 * its own full-screen background (today's per-swap captures are complete
 * single-scene pictures, never blends), so the primary's draw pass fully
 * overwrites the secondary's leftovers in the framebuffer before the
 * primary swap presents. */
#define PAD_MAX_SURF 8
static int surf_disp[PAD_MAX_SURF + 1];   /* slot -> display index        */
static int surf_n;                        /* surfaces created so far      */
static int primary_slot;                  /* the one that presents; 0 = TBD */

void *eglCreateWindowSurface(void *dpy, void *cfg, void *win, const int *attr)
{
    unsigned long w = (unsigned long)win;
    int disp = 0, slot;
    char b[96];
    (void)dpy; (void)cfg; (void)attr;
    if ((w & ~0xfful) == 0x7000ul) disp = (int)(w & 0xff);
    if (surf_n < PAD_MAX_SURF) surf_n++;
    slot = surf_n;
    surf_disp[slot] = disp;
    if (!primary_slot && disp == 0) primary_slot = slot;
    snprintf(b, sizeof b, "[eglshim] surface %d on display %d%s\n",
             slot, disp, primary_slot == slot ? " (primary)" : "");
    say(b);
    return (void *)(0x4000ul | (unsigned)slot);
}

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
    static int policy_said, suppressed;
    unsigned long long now = now_us();
    const unsigned long long frame_us = 16667;   /* 60 Hz */
    unsigned long s = (unsigned long)surf;
    int slot = ((s & ~0xfful) == 0x4000ul) ? (int)(s & 0xff) : 0;
    int present = 1;
    (void)dpy;

    /* item 27: with two or more surfaces, only the primary presents - see
     * the long comment at eglCreateWindowSurface. A slot of 0 is a handle
     * this file did not make (or made before the identity scheme); present
     * it, which is the old behaviour and the safe direction. The pacing
     * below runs for EVERY swap either way: the game's own render loop is
     * what is being throttled, whichever scene it just drew. */
    if (surf_n >= 2 && slot) {
        int prim = primary_slot ? primary_slot : 1;
        {
            const char *e = getenv("PAD_EGL_PRIMARY");
            if (e && *e >= '1' && *e <= '8') prim = *e - '0';
        }
        present = (slot == prim);
        if (!policy_said) {
            char b[112];
            policy_said = 1;
            snprintf(b, sizeof b, "[eglshim] %d surfaces: presenting only "
                     "surface %d, suppressing the other(s)\n", surf_n, prim);
            say(b);
        }
        if (!present && ++suppressed == 1)
            say("[eglshim] first suppressed swap (counted, not presented)\n");
    }
    if (present)
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
/* item 27: the display INDEX is the start of the surface-identity chain -
 * see eglCreateWindowSurface. Index 0 is the backbox LCD on every Spike 2
 * cabinet; a title that asks for more is building a second render target,
 * and which one it is survives into the window and surface handles. */
void *fbGetDisplayByIndex(int index)
{
    char b[64];
    snprintf(b, sizeof b, "[eglshim] fbGetDisplayByIndex(%d)\n", index);
    say(b);
    if (index < 0 || index > 0xff) index = 0xff;
    return (void *)(0x6000ul | (unsigned)index);
}

void fbGetDisplayGeometry(void *dpy, int *width, int *height)
{
    (void)dpy;
    if (width)  *width  = pad_fb_width();
    if (height) *height = pad_fb_height();
}

void *fbCreateWindow(void *dpy, int x, int y, int w, int h)
{
    unsigned long d = (unsigned long)dpy;
    int disp = ((d & ~0xfful) == 0x6000ul) ? (int)(d & 0xff) : 0;
    (void)x; (void)y; (void)w; (void)h;
    return (void *)(0x7000ul | (unsigned)disp);
}
