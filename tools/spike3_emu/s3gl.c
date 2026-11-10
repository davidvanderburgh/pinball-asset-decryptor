/* s3gl.c - the Spike 3 game's libGLESv2: the Spike 2 GL bridge plus what a
 * Godot 4 GLES3 renderer needs on top of it (PAD-1090, stage 2).
 *
 * The Spike 3 game is Godot 4 (its "compatibility" GLES3 renderer) under a
 * display server of Stern's own that renders into GBM buffers and page-flips
 * them (s3kms.c fakes the KMS side). This file is ONE translation unit with
 * ../spike2_emu/glbridge.c - it #includes it - so it reaches the bridge's ring
 * and shadow state without a single change to the Spike 2 build. What it adds:
 *
 *  * the 55 GL entry points the game imports and glbridge.c does not export
 *    (the game is BIND_NOW: a missing one stops it before main). Real where
 *    the bridge already has the machinery (glMapBufferRange is a guest-side
 *    shadow flushed as glBufferSubData at unmap; renderbuffer and query names
 *    are handed out here), canned answers for queries, and the rest log their
 *    FIRST call ([s3gl] first call: <name>) and do nothing - so a run says
 *    exactly which of them the renderer really uses, instead of guessing;
 *  * glGetIntegerv answering the Pi 4 V3D's GLES 3.1 limits, where the Spike 2
 *    bridge answered 0 for nearly everything (Godot sizes its uniform blocks,
 *    texture units and viewport from these);
 *  * GL_OES_EGL_image: glEGLImageTargetTexture2DOES gives the bound texture
 *    fb-sized storage and remembers which GBM bo it stands for, and
 *    pad_s3_present_bo (called by s3kms.c's page flip) presents THAT texture
 *    with PADGL_PRESENTTEX - the Spike 3 frame boundary, where Spike 2's is
 *    eglSwapBuffers.
 */
#define glGetIntegerv  pad_s2_glGetIntegerv
#define glGetProgramiv pad_s2_glGetProgramiv
#define pad_gl_proc    pad_s2_gl_proc
#define glBindTexture  pad_s2_glBindTexture
#define glTexParameteri pad_s2_glTexParameteri
#define glShaderSource pad_s2_glShaderSource
#include "glbridge.c"
#undef glGetIntegerv
#undef glGetProgramiv
#undef pad_gl_proc
#undef glBindTexture
#undef glTexParameteri
#undef glShaderSource

/* THE VIDEO SHADERS SAMPLE A 2D TEXTURE HERE. The game's video, camera-feed
 * and some canvas shaders declare `samplerExternalOES` under
 * `#extension GL_OES_EGL_image_external(_essl3)`. The host GPU accepts that
 * and compiles them - and an external sampler then reads the texture bound
 * to GL_TEXTURE_EXTERNAL_OES on its unit, where nothing is (the frames go to
 * GL_TEXTURE_2D, see glBindTexture below): black, every frame of every clip,
 * with no error anywhere. So the source is rewritten on its way to the host
 * into the game's own fallback for GPUs without external images: the
 * extension lines dropped and `#define samplerExternalOES sampler2D` after
 * #version. */
extern void *malloc(unsigned long);
extern void free(void *);
extern char *strchr(const char *, int);
extern int strncmp(const char *, const char *, unsigned long);
extern void *memmove(void *, const void *, unsigned long);
int glShaderSource(unsigned int sh, int count, const char *const *str, const int *len)
{
    unsigned long n = 0, k;
    int i;
    char *src, *out, *o;
    const char *p;
    static int said;
    if (!str) return 0;
    for (i = 0; i < count; i++)
        if (str[i]) n += len && len[i] >= 0 ? (unsigned long)len[i] : strlen(str[i]);
    src = malloc(n + 1);
    if (!src) return pad_s2_glShaderSource(sh, count, str, len);
    for (i = 0, k = 0; i < count; i++) {
        unsigned long m;
        if (!str[i]) continue;
        m = len && len[i] >= 0 ? (unsigned long)len[i] : strlen(str[i]);
        memcpy(src + k, str[i], m);
        k += m;
    }
    src[n] = 0;
    if (!strstr(src, "samplerExternalOES")) {
        const char *one[1] = { src };
        pad_s2_glShaderSource(sh, 1, one, 0);
        free(src);
        return 0;
    }
    out = malloc(n + 64);
    if (!out) { free(src); return pad_s2_glShaderSource(sh, count, str, len); }
    o = out;
    p = src;
    {
        int defined = strstr(src, "#define samplerExternalOES") != 0, put = defined;
        while (*p) {
            const char *e = strchr(p, '\n');
            unsigned long m = e ? (unsigned long)(e - p) + 1 : strlen(p);
            int ext = 0;
            if (m > 10 && !strncmp(p, "#extension", 10)) {
                unsigned long q;
                for (q = 10; q + 22 <= m && !ext; q++)
                    ext = !strncmp(p + q, "OES_EGL_image_external", 22);
            }
            if (!ext) {
                memcpy(o, p, m);
                o += m;
                if (!put && m > 8 && !strncmp(p, "#version", 8)) {
                    if (!e) *o++ = '\n';
                    memcpy(o, "#define samplerExternalOES sampler2D\n", 37);
                    o += 37;
                    put = 1;
                }
            }
            p += m;
        }
        *o = 0;
        if (!put) {                      /* no #version line: the define goes first */
            memmove(out + 37, out, (unsigned long)(o - out) + 1);
            memcpy(out, "#define samplerExternalOES sampler2D\n", 37);
        }
    }
    if (said < 3) {
        char m[120];
        said++;
        snprintf(m, sizeof m, "[s3gl] shader %u: samplerExternalOES -> sampler2D (video on a 2D texture)\n", sh);
        say(m);
    }
    {
        const char *one[1] = { out };
        pad_s2_glShaderSource(sh, 1, one, 0);
    }
    free(out);
    free(src);
    return 0;
}

/* GL_TEXTURE_EXTERNAL_OES is the Pi's dma-buf target (the game's video and
 * camera-feed textures). The host has no such target: the frame is uploaded
 * into a plain 2D texture (stage 5, s3vid.c), and the game's shaders already
 * fall back to `#define samplerExternalOES sampler2D` when the extension is
 * not offered - so a bind or parameter on it is the same thing on 2D. */
#define GL_TEXTURE_EXTERNAL_OES 0x8D65u
int glBindTexture(unsigned int t, unsigned int id)
{ return pad_s2_glBindTexture(t == GL_TEXTURE_EXTERNAL_OES ? 0x0DE1u : t, id); }
int glTexParameteri(unsigned int t, unsigned int p, int v)
{ return pad_s2_glTexParameteri(t == GL_TEXTURE_EXTERNAL_OES ? 0x0DE1u : t, p, v); }

extern void *malloc(unsigned long);
extern void free(void *);

static void s3say(const char *what, const char *name)
{
    char m[160];
    snprintf(m, sizeof m, "[s3gl] %s: %s\n", what, name);
    say(m);
}

/* First call of an entry point this bridge does not carry yet. */
#define FIRST(name) do { static int seen_; if (!seen_) { seen_ = 1; \
                         s3say("first call (not bridged yet)", name); } } while (0)

/* ---- limits: Mesa v3d on the Pi 4 (V3D 4.2, GLES 3.1) ------------------ */
static int s3_limit(unsigned p, int *v)
{
    switch (p) {
    case 0x821B: v[0] = 3; return 1;                 /* MAJOR_VERSION */
    case 0x821C: v[0] = 1; return 1;                 /* MINOR_VERSION */
    case 0x821D: v[0] = 0; return 1;                 /* NUM_EXTENSIONS */
    case 0x0D33: v[0] = 4096; return 1;              /* MAX_TEXTURE_SIZE */
    case 0x851C: v[0] = 4096; return 1;              /* MAX_CUBE_MAP_TEXTURE_SIZE */
    case 0x8073: v[0] = 2048; return 1;              /* MAX_3D_TEXTURE_SIZE */
    case 0x88FF: v[0] = 2048; return 1;              /* MAX_ARRAY_TEXTURE_LAYERS */
    case 0x84E8: v[0] = 4096; return 1;              /* MAX_RENDERBUFFER_SIZE */
    case 0x0D3A: v[0] = v[1] = 4096; return 1;       /* MAX_VIEWPORT_DIMS */
    case 0x8872: v[0] = 16; return 1;                /* MAX_TEXTURE_IMAGE_UNITS */
    case 0x8B4C: v[0] = 16; return 1;                /* MAX_VERTEX_TEXTURE_IMAGE_UNITS */
    case 0x8B4D: v[0] = 48; return 1;                /* MAX_COMBINED_TEXTURE_IMAGE_UNITS */
    case 0x8869: v[0] = 16; return 1;                /* MAX_VERTEX_ATTRIBS */
    case 0x8DFB: v[0] = 1024; return 1;              /* MAX_VERTEX_UNIFORM_VECTORS */
    case 0x8DFD: v[0] = 1024; return 1;              /* MAX_FRAGMENT_UNIFORM_VECTORS */
    case 0x8DFC: v[0] = 16; return 1;                /* MAX_VARYING_VECTORS */
    /* Godot 4's GLES3 budget is MIN(vertex outputs, fragment inputs) / 4;
     * left at 0 it refused every canvas material with a varying ("Too many
     * varyings used in shader (1 used, maximum supported is 0)") and those
     * items never drew. V3D: 64 components each, the 16 vectors above. */
    case 0x8B4B: v[0] = 64; return 1;                /* MAX_VARYING_COMPONENTS */
    case 0x9122: v[0] = 64; return 1;                /* MAX_VERTEX_OUTPUT_COMPONENTS */
    case 0x9125: v[0] = 64; return 1;                /* MAX_FRAGMENT_INPUT_COMPONENTS */
    case 0x8B4A: v[0] = 4096; return 1;              /* MAX_VERTEX_UNIFORM_COMPONENTS */
    case 0x8B49: v[0] = 4096; return 1;              /* MAX_FRAGMENT_UNIFORM_COMPONENTS */
    case 0x8A30: v[0] = 16384; return 1;             /* MAX_UNIFORM_BLOCK_SIZE */
    case 0x8A2B: case 0x8A2D: v[0] = 12; return 1;   /* MAX_VERTEX/FRAGMENT_UNIFORM_BLOCKS */
    case 0x8A2E: v[0] = 24; return 1;                /* MAX_COMBINED_UNIFORM_BLOCKS */
    case 0x8A2F: v[0] = 24; return 1;                /* MAX_UNIFORM_BUFFER_BINDINGS */
    case 0x8A34: v[0] = 256; return 1;               /* UNIFORM_BUFFER_OFFSET_ALIGNMENT */
    case 0x8D57: v[0] = 4; return 1;                 /* MAX_SAMPLES */
    case 0x8824: v[0] = 8; return 1;                 /* MAX_DRAW_BUFFERS */
    case 0x8CDF: v[0] = 8; return 1;                 /* MAX_COLOR_ATTACHMENTS */
    case 0x8C8B: v[0] = 4; return 1;                 /* MAX_TF_SEPARATE_ATTRIBS */
    case 0x8C8A: v[0] = 64; return 1;                /* MAX_TF_INTERLEAVED_COMPONENTS */
    case 0x8C80: v[0] = 4; return 1;                 /* MAX_TF_SEPARATE_COMPONENTS */
    case 0x87FE: v[0] = 0; return 1;                 /* NUM_PROGRAM_BINARY_FORMATS */
    case 0x86A2: v[0] = 0; return 1;                 /* NUM_COMPRESSED_TEXTURE_FORMATS */
    case 0x80E8: case 0x80E9: v[0] = 65536; return 1;/* MAX_ELEMENTS_VERTICES/INDICES */
    case 0x8D6B: v[0] = 0x7fffffff; return 1;        /* MAX_ELEMENT_INDEX */
    case 0x0D32: v[0] = 6; return 1;                 /* MAX_CLIP_PLANES (harmless) */
    case 0x8CA6: v[0] = (int)cur_fbo_shadow; return 1; /* FRAMEBUFFER_BINDING */
    case 0x8069: v[0] = (int)cur_tex2d[cur_unit & 15u]; return 1; /* TEXTURE_BINDING_2D */
    case 0x84E0: v[0] = (int)(0x84C0u + cur_unit); return 1;      /* ACTIVE_TEXTURE */
    }
    return 0;
}

int glGetIntegerv(unsigned int p, int *v)
{
    if (!v) return 0;
    if (s3_limit(p, v)) return 0;
    return pad_s2_glGetIntegerv(p, v);
}

int glGetInteger64v(unsigned int p, long long *v)
{
    int t[4] = {0, 0, 0, 0};
    if (!v) return 0;
    if (p == 0x8A30) { v[0] = 16384; return 0; }     /* MAX_UNIFORM_BLOCK_SIZE */
    if (p == 0x8D6B) { v[0] = 0xffffffffll; return 0; }
    if (p == 0x9111) { v[0] = 0x7fffffffffffffffll; return 0; } /* MAX_SERVER_WAIT_TIMEOUT */
    glGetIntegerv(p, t);
    v[0] = t[0];
    return 0;
}

int glGetFloatv(unsigned int p, float *v)
{
    if (!v) return 0;
    switch (p) {
    case 0x84FF: v[0] = 16.0f; break;                /* MAX_TEXTURE_MAX_ANISOTROPY */
    case 0x84FD: v[0] = 16.0f; break;                /* MAX_TEXTURE_LOD_BIAS */
    case 0x846D: case 0x846E: v[0] = 1.0f; v[1] = 1.0f; break; /* point / line ranges */
    default: { int t[4] = {0,0,0,0}; glGetIntegerv(p, t); v[0] = (float)t[0]; }
    }
    return 0;
}

const unsigned char *glGetStringi(unsigned int name, unsigned int i)
{ (void)name; (void)i; FIRST("glGetStringi"); return (const unsigned char *)""; }

/* ---- programs: never claim a program binary ---------------------------- */
#define MAXBINPROG 4096
static unsigned char prog_from_binary[MAXBINPROG];

int glGetProgramiv(unsigned int prog, unsigned int p, int *v)
{
    if (!v) return 0;
    if (p == 0x8741) { v[0] = 0; return 0; }         /* PROGRAM_BINARY_LENGTH */
    /* a program "loaded" from a cached binary is not linked: the renderer then
     * compiles it from source, which is the only thing this bridge can carry */
    if (p == 0x8B82 && prog < MAXBINPROG && prog_from_binary[prog]) { v[0] = 0; return 0; }
    return pad_s2_glGetProgramiv(prog, p, v);
}

int glGetProgramBinary(unsigned int prog, int bufsize, int *len, unsigned int *fmt, void *bin)
{ (void)prog; (void)bufsize; (void)bin; if (len) *len = 0; if (fmt) *fmt = 0; return 0; }

int glProgramBinary(unsigned int prog, unsigned int fmt, const void *bin, int len)
{
    (void)fmt; (void)bin; (void)len;
    if (prog < MAXBINPROG) prog_from_binary[prog] = 1;
    FIRST("glProgramBinary (refused: recompile from source)");
    return 0;
}

/* ---- names this file hands out ----------------------------------------- */
static unsigned next_rb = 1, next_query = 1;
int glGenRenderbuffers(int n, unsigned *ids)
{ int i; FIRST("glGenRenderbuffers"); for (i = 0; i < n; i++) ids[i] = next_rb++; return 0; }
int glGenQueries(int n, unsigned *ids)
{ int i; for (i = 0; i < n; i++) ids[i] = next_query++; return 0; }

/* ---- buffer mapping: a guest-side shadow, flushed at unmap -------------- */
static struct { unsigned target; long off, len; unsigned access; void *p; } maps[4];

void *glMapBufferRange(unsigned target, long off, long len, unsigned access)
{
    int i;
    for (i = 0; i < 4; i++) if (!maps[i].p) break;
    if (i == 4 || len <= 0) return 0;
    maps[i].p = malloc((unsigned long)len);
    if (!maps[i].p) return 0;
    memset(maps[i].p, 0, (unsigned long)len);
    maps[i].target = target; maps[i].off = off; maps[i].len = len; maps[i].access = access;
    return maps[i].p;
}

unsigned char glUnmapBuffer(unsigned target)
{
    int i;
    for (i = 0; i < 4; i++)
        if (maps[i].p && maps[i].target == target) {
            if (maps[i].access & 0x0002)             /* MAP_WRITE_BIT */
                glBufferSubData(target, maps[i].off, maps[i].len, maps[i].p);
            free(maps[i].p);
            maps[i].p = 0;
            return 1;
        }
    return 0;
}

/* ---- sync / uniform blocks: answers the renderer can live with ---------- */
int glGetSynciv(void *s, unsigned p, int bufsize, int *len, int *v)
{
    (void)s; (void)bufsize;
    if (v) v[0] = p == 0x9114 ? 0x9119 : 0;          /* SYNC_STATUS -> SIGNALED */
    if (len) *len = 1;
    return 0;
}

unsigned glGetUniformBlockIndex(unsigned prog, const char *name)
{ (void)prog; (void)name; FIRST("glGetUniformBlockIndex"); return 0; }

/* ---- the rest: logged on first use until a run shows they are needed ---- */
#define STUB(ret, name, ...) ret name(__VA_ARGS__) { FIRST(#name); return (ret)0; }
#define VSTUB(name, ...) void name(__VA_ARGS__) { FIRST(#name); }
VSTUB(glBeginTransformFeedback, unsigned a)
VSTUB(glEndTransformFeedback, void)
VSTUB(glTransformFeedbackVaryings, unsigned a, int b, const char *const *c, unsigned d)
VSTUB(glBindBufferBase, unsigned a, unsigned b, unsigned c)
VSTUB(glBindBufferRange, unsigned a, unsigned b, unsigned c, long d, long e)
VSTUB(glUniformBlockBinding, unsigned a, unsigned b, unsigned c)
VSTUB(glBindRenderbuffer, unsigned a, unsigned b)
VSTUB(glRenderbufferStorage, unsigned a, unsigned b, int c, int d)
VSTUB(glFramebufferRenderbuffer, unsigned a, unsigned b, unsigned c, unsigned d)
VSTUB(glDeleteRenderbuffers, int a, const unsigned *b)
VSTUB(glDeleteFramebuffers, int a, const unsigned *b)
VSTUB(glFramebufferTextureLayer, unsigned a, unsigned b, unsigned c, int d, int e)
VSTUB(glBlitFramebuffer, int a, int b, int c, int d, int e, int f, int g, int h, unsigned i, unsigned j)
VSTUB(glReadBuffer, unsigned a)
VSTUB(glBlendColor, float a, float b, float c, float d)
VSTUB(glClearBufferfv, unsigned a, int b, const float *c)
VSTUB(glClearDepthf, float a)
VSTUB(glColorMask, unsigned char a, unsigned char b, unsigned char c, unsigned char d)
VSTUB(glCullFace, unsigned a)
VSTUB(glFrontFace, unsigned a)
VSTUB(glDepthFunc, unsigned a)
VSTUB(glDepthMask, unsigned char a)
VSTUB(glDrawArraysInstanced, unsigned a, int b, int c, int d)
VSTUB(glDrawElementsInstanced, unsigned a, int b, unsigned c, const void *d, int e)
VSTUB(glVertexAttribDivisor, unsigned a, unsigned b)
VSTUB(glVertexAttribIPointer, unsigned a, int b, unsigned c, int d, const void *e)
VSTUB(glVertexAttribI4ui, unsigned a, unsigned b, unsigned c, unsigned d, unsigned e)
VSTUB(glVertexAttrib4f, unsigned a, float b, float c, float d, float e)
VSTUB(glCopyBufferSubData, unsigned a, unsigned b, long c, long d, long e)
VSTUB(glTexImage3D, unsigned a, int b, int c, int d, int e, int f, int g, unsigned h, unsigned i, const void *j)
VSTUB(glTexSubImage3D, unsigned a, int b, int c, int d, int e, int f, int g, int h, unsigned i, unsigned j, const void *k)
VSTUB(glCompressedTexImage3D, unsigned a, int b, unsigned c, int d, int e, int f, int g, int h, const void *i)
VSTUB(glCompressedTexSubImage3D, unsigned a, int b, int c, int d, int e, int f, int g, int h, unsigned i, int j, const void *k)
VSTUB(glTexStorage2D, unsigned a, int b, unsigned c, int d, int e)
VSTUB(glTexParameterf, unsigned a, unsigned b, float c)
VSTUB(glGenerateMipmap, unsigned a)
VSTUB(glPixelStorei, unsigned a, int b)
VSTUB(glDeleteQueries, int a, const unsigned *b)
VSTUB(glFinish, void)
VSTUB(glFlush, void)
VSTUB(glUniform1iv, int a, int b, const int *c)
VSTUB(glUniform1ui, int a, unsigned b)
VSTUB(glUniform1uiv, int a, int b, const unsigned *c)
VSTUB(glUniform2fv, int a, int b, const float *c)
VSTUB(glUniform2iv, int a, int b, const int *c)
VSTUB(glUniform3fv, int a, int b, const float *c)
VSTUB(glUniformMatrix3fv, int a, int b, unsigned char c, const float *d)

/* ---- GL_OES_EGL_image + the Spike 3 frame boundary --------------------- */
#define MAXS3BO 65
static unsigned tex_of_bo[MAXS3BO];
extern unsigned pad_s3_bo_size(unsigned handle, unsigned *w, unsigned *h) __attribute__((weak));

/* An EGL image made by s3egl.c is (void *)(0x5300000 + bo handle). */
#define S3IMG_BASE 0x5300000ul

/* A video image (s3egl.c, stage 5) is (void *)(0x5400000 + id): a slot of the
 * padvid ring the host decoder fills. Binding it uploads that slot's frame
 * into the bound texture on the host GPU - PADGL_TEXDIRECT, the same op the
 * Spike 2 video path uses - and the pixels never cross the emulated CPU. */
#define S3VIMG_BASE 0x5400000ul
extern int pad_s3_vid_image(unsigned id, unsigned *off, unsigned *w, unsigned *h,
                            unsigned *bytes) __attribute__((weak));

static void glEGLImageTargetTexture2DOES(unsigned target, void *image)
{
    unsigned long v = (unsigned long)image;
    unsigned handle, w = 0, h = 0;
    unsigned tex = cur_tex2d[cur_unit & 15u];
    char m[160];
    if (v >= S3VIMG_BASE && v < S3VIMG_BASE + 0x10000ul) {
        unsigned a[6], off = 0, bytes = 0;
        static unsigned long binds;
        if (!pad_s3_vid_image || !pad_s3_vid_image((unsigned)(v - S3VIMG_BASE), &off, &w, &h, &bytes))
            return;
        a[0] = w; a[1] = h; a[2] = PADGL_VIV_I420;
        a[3] = PADGL_SRC_VIDSHM; a[4] = off; a[5] = bytes;
        emit(PADGL_TEXDIRECT, a, sizeof a, 0, 0);
        if (++binds == 1 || binds % 1800 == 0) {
            snprintf(m, sizeof m, "[s3gl] video frame %lu: slot %lu (%ux%u) into texture %u\n",
                     binds, v - S3VIMG_BASE, w, h, tex);
            say(m);
        }
        (void)target;
        return;
    }
    handle = v > S3IMG_BASE ? (unsigned)(v - S3IMG_BASE) : 0;
    if (!handle || handle >= MAXS3BO || !pad_s3_bo_size || !pad_s3_bo_size(handle, &w, &h)) {
        say("[s3gl] glEGLImageTargetTexture2DOES on an image that is no bo of ours\n");
        return;
    }
    /* the bo's pixels live on the host: give the texture storage there */
    glTexImage2D(target, 0, 0x1908, (int)w, (int)h, 0, 0x1908, 0x1401, 0);
    tex_of_bo[handle] = tex;
    snprintf(m, sizeof m, "[s3gl] bo %u (%ux%u) is texture %u\n", handle, w, h, tex);
    say(m);
}

static void glEGLImageTargetRenderbufferStorageOES(unsigned target, void *image)
{ (void)target; (void)image; FIRST("glEGLImageTargetRenderbufferStorageOES"); }

/* s3kms.c's page flip: show the texture this bo stands for. */
void pad_s3_present_bo(unsigned handle, unsigned w, unsigned h)
{
    unsigned v[3];
    if (!bridge_init() || handle >= MAXS3BO || !tex_of_bo[handle]) return;
    v[0] = tex_of_bo[handle]; v[1] = w; v[2] = h;
    frame_no++;
    emit_u(PADGL_PRESENTTEX, v, 3);
    hdr->frame_seq++;
    {
        static int inflight = -1;
        int spins = 0;
        if (inflight < 0) inflight = envint("PAD_GL_INFLIGHT", 1);
        while (hdr->frame_seq - hdr->frame_ack > (unsigned long long)inflight) {
            if (++spins > 200000) { bridge_dead = 1; break; }
            host_wait();
        }
    }
}

static void glDebugMessageCallbackKHR(void *cb, const void *user) { (void)cb; (void)user; }
static void glFramebufferTexture2DMultisampleEXT(unsigned a, unsigned b, unsigned c,
                                                 unsigned tex, int lvl, int samples)
{ (void)samples; glFramebufferTexture2D(a, b, c, tex, lvl); }

void *pad_gl_proc(const char *name)
{
    if (!name) return 0;
    if (!strcmp(name, "glEGLImageTargetTexture2DOES"))  return (void *)glEGLImageTargetTexture2DOES;
    if (!strcmp(name, "glEGLImageTargetRenderbufferStorageOES"))
        return (void *)glEGLImageTargetRenderbufferStorageOES;
    if (!strcmp(name, "glDebugMessageCallbackKHR"))     return (void *)glDebugMessageCallbackKHR;
    if (!strcmp(name, "glFramebufferTexture2DMultisampleEXT"))
        return (void *)glFramebufferTexture2DMultisampleEXT;
    if (!strcmp(name, "glBindTexture"))   return (void *)glBindTexture;
    if (!strcmp(name, "glTexParameteri")) return (void *)glTexParameteri;
    if (!strcmp(name, "glShaderSource"))  return (void *)glShaderSource;
    return pad_s2_gl_proc(name);
}
