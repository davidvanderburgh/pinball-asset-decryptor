/* glstub.c - headless stand-in for the Vivante libEGL.so.1 / libGLESv2.so.2.
 *
 * The i.MX6 GPU userspace driver talks to /dev/galcore, which does not exist
 * off the machine. The game only imports 12 EGL and 72 GLES entry points, so
 * a stub that answers "success" to every query lets the game past window
 * creation and on into its own logic with no picture drawn.
 */

extern long write(int, const void *, unsigned long);

static void say(const char *s)
{
    unsigned long n = 0;
    while (s[n]) n++;
    write(2, s, n);
}

/* ---------------- EGL ---------------- */
#define EGL_SUCCESS 0x3000

int eglGetError(void) { return EGL_SUCCESS; }
void *eglGetDisplay(void *native) { (void)native; return (void *)0x1001; }
int eglInitialize(void *dpy, int *major, int *minor)
{
    (void)dpy;
    if (major) *major = 1;
    if (minor) *minor = 4;
    say("[glstub] eglInitialize -> headless\n");
    return 1;
}
int eglBindAPI(unsigned int api) { (void)api; return 1; }
int eglChooseConfig(void *dpy, const int *attr, void **configs, int size, int *num)
{
    (void)dpy; (void)attr;
    if (configs && size > 0) configs[0] = (void *)0x2001;
    if (num) *num = (size > 0) ? 1 : 0;
    return 1;
}
void *eglCreateWindowSurface(void *dpy, void *cfg, void *win, const int *attr)
{
    (void)dpy; (void)cfg; (void)win; (void)attr;
    say("[glstub] eglCreateWindowSurface -> headless surface\n");
    return (void *)0x3001;
}
void *eglCreateContext(void *dpy, void *cfg, void *share, const int *attr)
{
    (void)dpy; (void)cfg; (void)share; (void)attr;
    return (void *)0x4001;
}
int eglMakeCurrent(void *dpy, void *draw, void *read, void *ctx)
{
    (void)dpy; (void)draw; (void)read; (void)ctx; return 1;
}
/* Real hardware blocks here until vsync. Returning immediately lets the game
 * run its boot sequence at unbounded frame rate and move on before the
 * asynchronous asset loader has read anything. */
extern int gettimeofday(void *, void *);
extern int nanosleep(const void *, void *);
struct tv_ { long sec, usec; };
struct ts_ { long sec, nsec; };

static unsigned long long swap_now_us(void)
{
    struct tv_ t;
    gettimeofday(&t, 0);
    return (unsigned long long)t.sec * 1000000ULL + (unsigned long long)t.usec;
}

int eglSwapBuffers(void *dpy, void *surf)
{
    static unsigned long long next_us;
    unsigned long long now = swap_now_us();
    const unsigned long long frame_us = 16667;   /* 60 Hz */
    (void)dpy; (void)surf;
    if (!next_us) next_us = now;
    if (now < next_us) {
        struct ts_ req;
        unsigned long long d = next_us - now;
        req.sec = (long)(d / 1000000ULL);
        req.nsec = (long)((d % 1000000ULL) * 1000ULL);
        nanosleep(&req, 0);
    }
    next_us += frame_us;
    if (next_us < now) next_us = now + frame_us;   /* resync after a long stall */
    return 1;
}
int eglTerminate(void *dpy) { (void)dpy; return 1; }
int eglReleaseThread(void) { return 1; }
/* Returning NULL here is fatal: the game calls whatever comes back without
 * checking, which lands on address 0 and spins in its own SIGSEGV handler. */
static int noop_entry(void) { return 0; }
void *eglGetProcAddress(const char *name) { (void)name; return (void *)noop_entry; }

/* ------- Vivante fbdev platform helpers the game calls directly -------- */
void *fbGetDisplayByIndex(int index) { (void)index; return (void *)0x6001; }
void fbGetDisplayGeometry(void *dpy, int *width, int *height)
{
    (void)dpy;
    if (width)  *width  = 1920;
    if (height) *height = 1080;
}
void *fbCreateWindow(void *dpy, int x, int y, int w, int h)
{
    (void)dpy; (void)x; (void)y; (void)w; (void)h;
    return (void *)0x7001;
}

/* ---------------- GLES: queries that must answer plausibly ------------- */
#define GL_FRAMEBUFFER_COMPLETE 0x8CD5

static const char *VENDOR   = "pinball-asset-decryptor";
static const char *RENDERER = "glstub headless";
static const char *VERSION  = "OpenGL ES 2.0 stub";
static const char *SLVER    = "OpenGL ES GLSL ES 1.00";

const char *glGetString(unsigned int name)
{
    switch (name) {
    case 0x1F00: return VENDOR;    /* GL_VENDOR   */
    case 0x1F01: return RENDERER;  /* GL_RENDERER */
    case 0x1F02: return VERSION;   /* GL_VERSION  */
    case 0x8B8C: return SLVER;     /* GL_SHADING_LANGUAGE_VERSION */
    default:     return "";
    }
}

int glGetError(void) { return 0; }

/* Answering 4096 to everything is wrong for the queries that are not sizes:
 * anything asking how much memory is available would get 4 KB and conclude
 * there is no room to load content. Known GLES2 limits are answered exactly,
 * and anything unrecognised gets a large value rather than a small one. */
void glGetIntegerv(unsigned int pname, int *params)
{
    if (!params) return;
    switch (pname) {
    case 0x0D33: *params = 4096; return;   /* GL_MAX_TEXTURE_SIZE            */
    case 0x851C: *params = 4096; return;   /* GL_MAX_CUBE_MAP_TEXTURE_SIZE   */
    case 0x84E8: *params = 4096; return;   /* GL_MAX_RENDERBUFFER_SIZE       */
    case 0x0D3A: params[0] = 4096; params[1] = 4096; return; /* VIEWPORT_DIMS */
    case 0x8869: *params = 16;   return;   /* GL_MAX_VERTEX_ATTRIBS          */
    case 0x8DFB: *params = 256;  return;   /* MAX_VERTEX_UNIFORM_VECTORS     */
    case 0x8DFC: *params = 8;    return;   /* GL_MAX_VARYING_VECTORS         */
    case 0x8DFD: *params = 224;  return;   /* MAX_FRAGMENT_UNIFORM_VECTORS   */
    case 0x8872: *params = 8;    return;   /* MAX_TEXTURE_IMAGE_UNITS        */
    case 0x8B4C: *params = 4;    return;   /* MAX_VERTEX_TEXTURE_IMAGE_UNITS */
    case 0x8B4D: *params = 8;    return;   /* MAX_COMBINED_TEXTURE_IMAGE_UNITS */
    case 0x86A2: *params = 0;    return;   /* NUM_COMPRESSED_TEXTURE_FORMATS */
    case 0x8DF8: params[0] = 0; params[1] = 0; params[2] = 0; return; /* SHADER_PRECISION */
    default:     *params = 0x08000000; return;  /* 128M for anything else */
    }
}
void glGetBooleanv(unsigned int pname, unsigned char *params)
{
    (void)pname;
    if (params) *params = 1;
}
int glIsEnabled(unsigned int cap) { (void)cap; return 1; }

static unsigned int next_id = 1;
static unsigned int alloc_id(void) { return next_id++; }

unsigned int glCreateShader(unsigned int type) { (void)type; return alloc_id(); }
unsigned int glCreateProgram(void) { return alloc_id(); }

void glGetShaderiv(unsigned int s, unsigned int pname, int *params)
{
    (void)s; (void)pname;
    if (params) *params = 1;       /* COMPILE_STATUS = GL_TRUE, log length 1 */
}
void glGetProgramiv(unsigned int p, unsigned int pname, int *params)
{
    (void)p; (void)pname;
    if (params) *params = 1;
}
void glGetShaderInfoLog(unsigned int s, int buf, int *len, char *log)
{
    (void)s; (void)buf;
    if (len) *len = 0;
    if (log && buf > 0) log[0] = 0;
}
void glGetProgramInfoLog(unsigned int p, int buf, int *len, char *log)
{
    (void)p; (void)buf;
    if (len) *len = 0;
    if (log && buf > 0) log[0] = 0;
}

int glGetUniformLocation(unsigned int p, const char *n) { (void)p; (void)n; return (int)alloc_id(); }
int glGetAttribLocation(unsigned int p, const char *n) { (void)p; (void)n; return (int)alloc_id(); }

static void fill_ids(int n, unsigned int *ids)
{
    int i;
    if (!ids) return;
    for (i = 0; i < n; i++) ids[i] = alloc_id();
}
void glGenTextures(int n, unsigned int *ids)      { fill_ids(n, ids); }
void glGenBuffers(int n, unsigned int *ids)       { fill_ids(n, ids); }
void glGenFramebuffers(int n, unsigned int *ids)  { fill_ids(n, ids); }
void glGenVertexArrays(int n, unsigned int *ids)  { fill_ids(n, ids); }

unsigned int glCheckFramebufferStatus(unsigned int t) { (void)t; return GL_FRAMEBUFFER_COMPLETE; }

void *glFenceSync(unsigned int cond, unsigned int flags) { (void)cond; (void)flags; return (void *)0x5001; }
unsigned int glClientWaitSync(void *s, unsigned int f, unsigned long long t)
{
    (void)s; (void)f; (void)t;
    return 0x911A;                 /* GL_ALREADY_SIGNALED */
}

/* ---------------- GLES: everything else is a no-op --------------------- */
#define NOOP(name) int name(void) { return 0; }

NOOP(glActiveTexture)
NOOP(glAttachShader)
NOOP(glBindAttribLocation)
NOOP(glBindBuffer)
NOOP(glBindFramebuffer)
NOOP(glBindTexture)
NOOP(glBindVertexArray)
NOOP(glBlendEquation)
NOOP(glBlendEquationSeparate)
NOOP(glBlendFunc)
NOOP(glBlendFuncSeparate)
NOOP(glBufferData)
NOOP(glBufferSubData)
/* Instrumented: whether the render loop runs at all is load-bearing, because
 * demand-loading of scene content is driven from it. */
/* ---------------- PAD_GL_TRACE=1: what would we have to rasterise? ------
 * Answers, without implementing any rendering: how many draw calls per frame,
 * how many distinct shader programs, and what texture formats/sizes arrive.
 * That is what decides whether a small 2D compositor can stand in for a real
 * GLES2 implementation here.
 */
extern char *getenv(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);

static int gltrace(void)
{
    static int v = -1;
    if (v < 0) { char *p = getenv("PAD_GL_TRACE"); v = (p && p[0] == '1'); }
    return v;
}

static unsigned long draws_this_frame, draws_total, frames, shaders_seen;

int glClear(unsigned int mask)
{
    static unsigned long n;
    (void)mask;
    if (n == 0) say("[glstub] first glClear - render loop is running\n");
    if (gltrace() && draws_this_frame) {
        char b[160];
        frames++;
        if (frames <= 8 || frames % 300 == 0) {
            snprintf(b, sizeof b, "[gltrace] frame %lu: %lu draw calls\n",
                     frames, draws_this_frame);
            say(b);
        }
    }
    draws_this_frame = 0;
    if (++n % 300 == 0) say("[glstub] 300 more frames cleared\n");
    return 0;
}

int glDrawArrays(unsigned int mode, int first, int count)
{
    (void)mode; (void)first; (void)count;
    draws_this_frame++; draws_total++;
    return 0;
}

int glDrawElements(unsigned int mode, int count, unsigned int type, const void *idx)
{
    (void)mode; (void)count; (void)type; (void)idx;
    draws_this_frame++; draws_total++;
    return 0;
}

int glShaderSource(unsigned int sh, int count, const char *const *str, const int *len)
{
    (void)sh; (void)len;
    if (gltrace() && str) {
        int i;
        char b[80];
        shaders_seen++;
        snprintf(b, sizeof b, "\n[gltrace] ===== shader source #%lu =====\n", shaders_seen);
        say(b);
        for (i = 0; i < count; i++)
            if (str[i]) say(str[i]);
    }
    return 0;
}

int glTexImage2D(unsigned int target, int level, int ifmt, int w, int h,
                 int border, unsigned int fmt, unsigned int type, const void *px)
{
    (void)target; (void)border; (void)px;
    if (gltrace() && level == 0) {
        char b[140];
        snprintf(b, sizeof b,
                 "[gltrace] glTexImage2D %dx%d ifmt=0x%x fmt=0x%x type=0x%x\n",
                 w, h, ifmt, fmt, type);
        say(b);
    }
    return 0;
}

int glCompressedTexImage2D(unsigned int target, int level, unsigned int ifmt,
                           int w, int h, int border, int size, const void *data)
{
    (void)target; (void)border; (void)data;
    if (gltrace() && level == 0) {
        char b[140];
        snprintf(b, sizeof b,
                 "[gltrace] glCompressedTexImage2D %dx%d ifmt=0x%x bytes=%d\n",
                 w, h, ifmt, size);
        say(b);
    }
    return 0;
}
NOOP(glClearColor)
NOOP(glCompileShader)
NOOP(glCompressedTexSubImage2D)
NOOP(glDeleteBuffers)
NOOP(glDeleteProgram)
NOOP(glDeleteShader)
NOOP(glDeleteSync)
NOOP(glDeleteTextures)
NOOP(glDeleteVertexArrays)
NOOP(glDetachShader)
NOOP(glDisable)
NOOP(glDisableVertexAttribArray)
NOOP(glDrawBuffers)
NOOP(glDrawRangeElements)
NOOP(glEnable)
NOOP(glEnableVertexAttribArray)
NOOP(glFramebufferTexture2D)
NOOP(glLineWidth)
NOOP(glLinkProgram)
NOOP(glReadPixels)
NOOP(glScissor)
NOOP(glTexParameteri)
NOOP(glTexSubImage2D)
NOOP(glUniform1f)
NOOP(glUniform1i)
NOOP(glUniform2f)
NOOP(glUniform3f)
NOOP(glUniform4f)
NOOP(glUniform4fv)
NOOP(glUniformMatrix4fv)
NOOP(glUseProgram)
NOOP(glVertexAttribPointer)
NOOP(glViewport)
