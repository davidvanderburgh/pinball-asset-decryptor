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
#define glAttachShader pad_s2_glAttachShader
#define glUseProgram   pad_s2_glUseProgram
#define glDrawArrays   pad_s2_glDrawArrays
#define glDrawElements pad_s2_glDrawElements
#define glUniform4fv   pad_s2_glUniform4fv
#define glUniformMatrix4fv pad_s2_glUniformMatrix4fv
#include "glbridge.c"
#undef glUniform4fv
#undef glUniformMatrix4fv
#undef glAttachShader
#undef glUseProgram
#undef glDrawArrays
#undef glDrawElements

/* WHERE THE VIDEO GOES (diagnostic, PAD_S3_VIDDRAW=1): the programs built
 * from a samplerExternalOES shader (marked by glShaderSource below) are the
 * game's video/camera-feed passes. Each of their first draws is logged with
 * the framebuffer it draws into and the texture on unit 0, so a run says
 * whether the video is ever sampled, and into what. */
static unsigned char ext_shader[4096], ext_prog[4096];
static unsigned cur_prog_s3;
static int viddraw = -1;
int glAttachShader(unsigned int p, unsigned int s)
{
    if (p < 4096 && s < 4096 && ext_shader[s]) ext_prog[p] = 1;
    return pad_s2_glAttachShader(p, s);
}
int glUseProgram(unsigned int p) { cur_prog_s3 = p; return pad_s2_glUseProgram(p); }
static void viddraw_note(const char *what, int count)
{
    static int said;
    char m[200];
    if (viddraw < 0) viddraw = envint("PAD_S3_VIDDRAW", 0);
    if (!viddraw || cur_prog_s3 >= 4096 || !ext_prog[cur_prog_s3] || said >= 40) return;
    said++;
    snprintf(m, sizeof m, "[s3gl] video draw %s prog %u n %d: fbo %u, unit %u, tex(2D) on unit0 %u, frame %u\n",
             what, cur_prog_s3, count, cur_fbo_shadow, cur_unit, cur_tex2d[0], (unsigned)frame_no);
    say(m);
}
int glDrawArrays(unsigned int mode, int first, int count)
{ viddraw_note("arrays", count); return pad_s2_glDrawArrays(mode, first, count); }
int glDrawElements(unsigned int mode, int count, unsigned int type, const void *idx)
{ viddraw_note("elements", count); return pad_s2_glDrawElements(mode, count, type, idx); }
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
    if (sh < 4096) ext_shader[sh] = 1;
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

/* ---- the extensions this bridge really carries (PAD-1182) ---------------
 * Godot 4's GLES3 renderer reads its extension list with glGetStringi and
 * only then decides what it may use. With an empty list it set
 * external_texture_supported false, never looked up
 * glEGLImageTargetTexture2DOES, and every video it plays through an
 * ExternalTexture (Pokemon's DISCOVER background, the capture/select/evolve
 * backgrounds) stayed on its black placeholder: s3vid decoded the frames,
 * the game made an EGL image of each, and nothing was ever attached. Stern's
 * own SpiVideoPlayer (the map background) looks the function up without
 * asking, which is why that clip played. Only what is bridged is listed:
 * EGL images (s3egl.c/glEGLImageTargetTexture2DOES below) and the external
 * sampler, which the shader rewrite above turns into a 2D one. */
static const char *const s3_ext[] = {
    "GL_OES_EGL_image",
    "GL_OES_EGL_image_external",
    "GL_OES_EGL_image_external_essl3",
};
#define S3_NEXT ((int)(sizeof s3_ext / sizeof s3_ext[0]))

/* ---- limits: Mesa v3d on the Pi 4 (V3D 4.2, GLES 3.1) ------------------ */
static int s3_limit(unsigned p, int *v)
{
    switch (p) {
    case 0x821B: v[0] = 3; return 1;                 /* MAJOR_VERSION */
    case 0x821C: v[0] = 1; return 1;                 /* MINOR_VERSION */
    case 0x821D: v[0] = S3_NEXT; return 1;           /* NUM_EXTENSIONS */
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
{
    if (name == 0x1F03 && i < (unsigned)S3_NEXT)      /* GL_EXTENSIONS */
        return (const unsigned char *)s3_ext[i];
    return 0;                                         /* GL_INVALID_VALUE */
}

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

/* ---- the rest of GLES 3 that Godot 4 uses: real ops now (padgl.h's ops
 * after PADGL_PRESENTTEX, executed by padglhost.c) ------------------------ */

/* Uniform blocks: the index handed back is a per-program slot, the name is
 * kept here, and glUniformBlockBinding sends the NAME - the host looks the
 * real index up in the real program (the token trick attributes and
 * uniforms already use, so no round trip). */
#define S3_UBO_PER_PROG 16
static char ubo_name[MAXPROG][S3_UBO_PER_PROG][48];
static unsigned char ubo_n[MAXPROG];

unsigned glGetUniformBlockIndex(unsigned prog, const char *name)
{
    unsigned i;
    if (prog >= MAXPROG || !name) return 0xFFFFFFFFu;
    for (i = 0; i < ubo_n[prog]; i++)
        if (!strcmp(ubo_name[prog][i], name)) return i;
    if (ubo_n[prog] >= S3_UBO_PER_PROG) return 0xFFFFFFFFu;
    i = ubo_n[prog]++;
    snprintf(ubo_name[prog][i], sizeof ubo_name[prog][i], "%s", name);
    return i;
}

void glUniformBlockBinding(unsigned prog, unsigned idx, unsigned binding)
{
    unsigned a[2];
    if (prog >= MAXPROG || idx >= ubo_n[prog]) return;
    a[0] = prog; a[1] = binding;
    emit(PADGL_UBOBINDING, a, sizeof a, ubo_name[prog][idx], (unsigned)strlen(ubo_name[prog][idx]));
}

void glBindBufferBase(unsigned target, unsigned index, unsigned buf)
{ unsigned a[3]; a[0] = target; a[1] = index; a[2] = buf; emit(PADGL_BINDBUFBASE, a, sizeof a, 0, 0); }

void glBindBufferRange(unsigned target, unsigned index, unsigned buf, long off, long size)
{
    unsigned a[5];
    a[0] = target; a[1] = index; a[2] = buf; a[3] = (unsigned)off; a[4] = (unsigned)size;
    emit(PADGL_BINDBUFRANGE, a, sizeof a, 0, 0);
}

void glDrawArraysInstanced(unsigned mode, int first, int count, int inst)
{
    unsigned a[4];
    a[0] = mode; a[1] = (unsigned)first; a[2] = (unsigned)count; a[3] = (unsigned)inst;
    emit(PADGL_DRAWARRAYSINST, a, sizeof a, 0, 0);
}

void glDrawElementsInstanced(unsigned mode, int count, unsigned type, const void *idx, int inst)
{
    unsigned a[5];
    a[0] = mode; a[1] = (unsigned)count; a[2] = type;
    a[3] = (unsigned)(unsigned long)idx;          /* an offset: Godot draws from buffers */
    a[4] = (unsigned)inst;
    emit(PADGL_DRAWELEMSINST, a, sizeof a, 0, 0);
}

void glVertexAttribDivisor(unsigned idx, unsigned div)
{ unsigned a[2]; a[0] = idx; a[1] = div; emit(PADGL_ATTRIBDIVISOR, a, sizeof a, 0, 0); }

void glVertexAttribIPointer(unsigned idx, int size, unsigned type, int stride, const void *ptr)
{
    unsigned a[5];
    a[0] = idx; a[1] = (unsigned)size; a[2] = type; a[3] = (unsigned)stride;
    a[4] = (unsigned)(unsigned long)ptr;
    emit(PADGL_VERTEXATTRIBI, a, sizeof a, 0, 0);
}

void glVertexAttrib4f(unsigned idx, float x, float y, float z, float w)
{
    unsigned a[6];
    float f[4];
    f[0] = x; f[1] = y; f[2] = z; f[3] = w;
    a[0] = idx; a[1] = 0;
    memcpy(&a[2], f, 16);
    emit(PADGL_VERTEXATTRIBC, a, sizeof a, 0, 0);
}

void glVertexAttribI4ui(unsigned idx, unsigned x, unsigned y, unsigned z, unsigned w)
{
    unsigned a[6];
    a[0] = idx; a[1] = 1; a[2] = x; a[3] = y; a[4] = z; a[5] = w;
    emit(PADGL_VERTEXATTRIBC, a, sizeof a, 0, 0);
}

void glColorMask(unsigned char r, unsigned char g, unsigned char b, unsigned char al)
{ unsigned a[4]; a[0] = r; a[1] = g; a[2] = b; a[3] = al; emit(PADGL_COLORMASK, a, sizeof a, 0, 0); }
void glDepthMask(unsigned char f)
{ unsigned a[1]; a[0] = f; emit(PADGL_DEPTHMASK, a, sizeof a, 0, 0); }
void glPixelStorei(unsigned pname, int v)
{ unsigned a[2]; a[0] = pname; a[1] = (unsigned)v; emit(PADGL_PIXELSTORE, a, sizeof a, 0, 0); }
static void state1(unsigned which, unsigned v)
{ unsigned a[2]; a[0] = which; a[1] = v; emit(PADGL_STATE1, a, sizeof a, 0, 0); }
void glCullFace(unsigned m)  { state1(PADGL_S1_CULLFACE, m); }
void glFrontFace(unsigned m) { state1(PADGL_S1_FRONTFACE, m); }
void glDepthFunc(unsigned f) { state1(PADGL_S1_DEPTHFUNC, f); }
void glClearDepthf(float d)  { unsigned v; memcpy(&v, &d, 4); state1(PADGL_S1_CLEARDEPTH, v); }
void glBlendColor(float r, float g, float b, float al)
{ float f[4]; f[0] = r; f[1] = g; f[2] = b; f[3] = al; emit(PADGL_BLENDCOLOR, f, sizeof f, 0, 0); }

void glTexImage3D(unsigned target, int lvl, int ifmt, int w, int h, int d, int border,
                  unsigned fmt, unsigned type, const void *px)
{
    unsigned a[8];
    (void)border;
    a[0] = target; a[1] = (unsigned)lvl; a[2] = (unsigned)ifmt; a[3] = (unsigned)w;
    a[4] = (unsigned)h; a[5] = (unsigned)d; a[6] = fmt; a[7] = type;
    emit(PADGL_TEXIMAGE3D, a, sizeof a, px, px ? pixel_bytes(fmt, type, w, h) * (unsigned)d : 0);
}

void glTexSubImage3D(unsigned target, int lvl, int x, int y, int z, int w, int h, int d,
                     unsigned fmt, unsigned type, const void *px)
{
    unsigned a[10];
    if (!px) return;
    a[0] = target; a[1] = (unsigned)lvl; a[2] = (unsigned)x; a[3] = (unsigned)y;
    a[4] = (unsigned)z; a[5] = (unsigned)w; a[6] = (unsigned)h; a[7] = (unsigned)d;
    a[8] = fmt; a[9] = type;
    emit(PADGL_TEXSUBIMAGE3D, a, sizeof a, px, pixel_bytes(fmt, type, w, h) * (unsigned)d);
}

void glGenerateMipmap(unsigned target)
{ unsigned a[1]; a[0] = target; emit(PADGL_GENMIPMAP, a, sizeof a, 0, 0); }

void glTexStorage2D(unsigned target, int levels, unsigned ifmt, int w, int h)
{
    unsigned a[5];
    a[0] = target; a[1] = (unsigned)levels; a[2] = ifmt; a[3] = (unsigned)w; a[4] = (unsigned)h;
    emit(PADGL_TEXSTORAGE2D, a, sizeof a, 0, 0);
}

/* Uniform arrays and the vector/matrix forms glbridge.c does not carry, with
 * their COUNT (the bridge's glUniform4fv/glUniformMatrix4fv sent element 0
 * only - an array of them arrived as its first entry). */
static void uniformn(int loc, unsigned kind, int count, const void *data, unsigned elem_bytes)
{
    unsigned a[4];
    if (loc < 0 || count <= 0) return;
    a[0] = (unsigned)(loc / MAXUNI); a[1] = (unsigned)(loc % MAXUNI); a[2] = kind; a[3] = (unsigned)count;
    emit(PADGL_UNIFORMN, a, sizeof a, data, elem_bytes * (unsigned)count);
}
void glUniform1iv(int l, int n, const int *v)        { uniformn(l, PADGL_UN_1IV, n, v, 4); }
void glUniform2iv(int l, int n, const int *v)        { uniformn(l, PADGL_UN_2IV, n, v, 8); }
void glUniform1ui(int l, unsigned v)                 { uniformn(l, PADGL_UN_1UIV, 1, &v, 4); }
void glUniform1uiv(int l, int n, const unsigned *v)  { uniformn(l, PADGL_UN_1UIV, n, v, 4); }
void glUniform2fv(int l, int n, const float *v)      { uniformn(l, PADGL_UN_2FV, n, v, 8); }
void glUniform3fv(int l, int n, const float *v)      { uniformn(l, PADGL_UN_3FV, n, v, 12); }
void glUniformMatrix3fv(int l, int n, unsigned char t, const float *v)
{ (void)t; uniformn(l, PADGL_UN_M3FV, n, v, 36); }
int glUniform4fv(int l, int n, const float *v)
{
    if (n == 1) return pad_s2_glUniform4fv(l, n, v);
    uniformn(l, PADGL_UN_4FV, n, v, 16);
    return 0;
}
int glUniformMatrix4fv(int l, int n, unsigned char t, const float *v)
{
    if (n == 1) return pad_s2_glUniformMatrix4fv(l, n, t, v);
    uniformn(l, PADGL_UN_M4FV, n, v, 64);
    return 0;
}

/* ---- the rest: logged on first use until a run shows they are needed ---- */
#define STUB(ret, name, ...) ret name(__VA_ARGS__) { FIRST(#name); return (ret)0; }
#define VSTUB(name, ...) void name(__VA_ARGS__) { FIRST(#name); }
VSTUB(glBeginTransformFeedback, unsigned a)
VSTUB(glEndTransformFeedback, void)
VSTUB(glTransformFeedbackVaryings, unsigned a, int b, const char *const *c, unsigned d)
VSTUB(glBindRenderbuffer, unsigned a, unsigned b)
VSTUB(glRenderbufferStorage, unsigned a, unsigned b, int c, int d)
VSTUB(glFramebufferRenderbuffer, unsigned a, unsigned b, unsigned c, unsigned d)
VSTUB(glDeleteRenderbuffers, int a, const unsigned *b)
VSTUB(glDeleteFramebuffers, int a, const unsigned *b)
VSTUB(glFramebufferTextureLayer, unsigned a, unsigned b, unsigned c, int d, int e)
VSTUB(glBlitFramebuffer, int a, int b, int c, int d, int e, int f, int g, int h, unsigned i, unsigned j)
VSTUB(glReadBuffer, unsigned a)
VSTUB(glClearBufferfv, unsigned a, int b, const float *c)
VSTUB(glCopyBufferSubData, unsigned a, unsigned b, long c, long d, long e)
VSTUB(glCompressedTexImage3D, unsigned a, int b, unsigned c, int d, int e, int f, int g, int h, const void *i)
VSTUB(glCompressedTexSubImage3D, unsigned a, int b, int c, int d, int e, int f, int g, int h, unsigned i, int j, const void *k)
VSTUB(glTexParameterf, unsigned a, unsigned b, float c)
VSTUB(glDeleteQueries, int a, const unsigned *b)
VSTUB(glFinish, void)
VSTUB(glFlush, void)

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
    if (!strcmp(name, "glUniform4fv"))    return (void *)glUniform4fv;
    if (!strcmp(name, "glUniformMatrix4fv")) return (void *)glUniformMatrix4fv;
    if (!strcmp(name, "glDrawArrays"))    return (void *)glDrawArrays;
    if (!strcmp(name, "glDrawElements"))  return (void *)glDrawElements;
    if (!strcmp(name, "glUseProgram"))    return (void *)glUseProgram;
    if (!strcmp(name, "glAttachShader"))  return (void *)glAttachShader;
    return pad_s2_gl_proc(name);
}
