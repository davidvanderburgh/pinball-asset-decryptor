/* glraster.c - a software GLES2/3 subset that actually draws, standing in for
 * the Vivante libGLESv2.so.2 on a PC.
 *
 * WHY THIS IS SMALL. The game's whole render is 2D compositing, measured with
 * PAD_GL_TRACE=1 before any of this was written:
 *   - 2 to 4 draw calls per frame
 *   - every texture arrives as plain RGBA8 (no compressed uploads seen live)
 *   - 20 shaders / 10 programs, and only FOUR distinct fragment bodies:
 *       plain    color = tex * colorTransformMultiply + colorTransformAdd*a
 *       sprite   color = spriteColor * tex
 *       text     r channel = stroke, g channel = fill, cycling gradient
 *       video    three-plane YUV -> RGB
 * So this file is a textured-quad rasteriser with four shading paths, not a
 * general GL implementation. Anything outside that subset is meant to fail
 * LOUDLY (magenta, and a [glraster] line) rather than silently draw nothing -
 * silent success is exactly the trap that cost two passes on the scene bug.
 *
 * Pairs with eglshim.c, which becomes libEGL.so.1 and calls pad_present() here.
 * They must NOT both be built from one source: the state below has to exist
 * once, and building the same .c into both libraries gives each its own copy.
 */

extern void *malloc(unsigned long);
extern void free(void *);
extern void *memcpy(void *, const void *, unsigned long);
extern void *memset(void *, int, unsigned long);
extern char *strstr(const char *, const char *);
extern int strcmp(const char *, const char *);
extern unsigned long strlen(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern long write(int, const void *, unsigned long);
extern int open(const char *, int, ...);
extern int close(int);
extern char *getenv(const char *);

static void say(const char *s) { write(2, s, strlen(s)); }
static void sayf(const char *fmt, int a, int b, int c, int d)
{
    char t[200];
    snprintf(t, sizeof t, fmt, a, b, c, d);
    say(t);
}

/* ---------------- GL enums we care about ---------------- */
#define GL_RGBA               0x1908
#define GL_RGB                0x1907
#define GL_LUMINANCE          0x1909
#define GL_ALPHA              0x1906
#define GL_LUMINANCE_ALPHA    0x190A
#define GL_RED                0x1903
#define GL_UNSIGNED_BYTE      0x1401
#define GL_TRIANGLES          0x0004
#define GL_TRIANGLE_STRIP     0x0005
#define GL_TRIANGLE_FAN       0x0006
#define GL_UNSIGNED_SHORT     0x1403
#define GL_UNSIGNED_INT       0x1405
#define GL_ARRAY_BUFFER       0x8892
#define GL_ELEMENT_ARRAY_BUFFER 0x8893
#define GL_FLOAT              0x1406
#define GL_BLEND              0x0BE2
#define GL_SCISSOR_TEST       0x0C11
#define GL_ZERO               0
#define GL_ONE                1
#define GL_SRC_ALPHA          0x0302
#define GL_ONE_MINUS_SRC_ALPHA 0x0303
#define GL_FRAMEBUFFER        0x8D40
#define GL_COLOR_ATTACHMENT0  0x8CE0
#define GL_FRAMEBUFFER_COMPLETE 0x8CD5
#define GL_COMPRESSED_RGB_S3TC_DXT1  0x83F0
#define GL_COMPRESSED_RGBA_S3TC_DXT1 0x83F1
#define GL_COMPRESSED_RGBA_S3TC_DXT3 0x83F2
#define GL_COMPRESSED_RGBA_S3TC_DXT5 0x83F3

/* ---------------- objects ---------------- */
#define MAXTEX  1024
#define MAXBUF  512
#define MAXPROG 128
#define MAXSH   256
#define MAXFBO  64
#define MAXVAO  64
#define MAXUNI  24
#define MAXATTR 8

typedef struct { int w, h; unsigned char *px; } Tex;      /* always RGBA8 */
typedef struct { unsigned char *data; int size; } Buf;

/* Fragment kinds, classified from the shader text at glShaderSource time. */
enum { F_PLAIN = 0, F_SPRITE, F_TEXT, F_VIDEO, F_SOLID, F_UNKNOWN };

typedef struct {
    int  frag;              /* enum above */
    int  packed_vertex;     /* "in vec4 vertex" = xy position, zw texcoord */
    int  loc_pos, loc_uv;   /* attribute locations */
    char uname[MAXUNI][32];
    float uval[MAXUNI][16];
    int  ucount;
} Prog;

typedef struct { int enabled, buffer, size, type, stride; unsigned long offset; } Attr;

static Tex  tex[MAXTEX];
static Buf  buf[MAXBUF];
static Prog prog[MAXPROG];
static int  sh_frag[MAXSH];      /* per shader id: fragment kind, or -1 vertex */
static int  sh_packed[MAXSH];
static int  fbo_tex[MAXFBO];
static Attr attr[MAXVAO][MAXATTR];

static int cur_prog, cur_vao, cur_fbo;
static int bound_tex[8], active_unit;
static int bound_array_buf, bound_elem_buf;
static int blend_on, blend_src = GL_ONE, blend_dst = GL_ZERO;
static int vp_x, vp_y, vp_w, vp_h;
static float clear_r, clear_g, clear_b, clear_a;

/* default framebuffer */
static int fb_w = 1920, fb_h = 1080;
static unsigned char *fb_px;

/* current render target */
static unsigned char *rt_px;
static int rt_w, rt_h;

/* Object names must never be 0: zero means "no object" in GL, and a program id
 * of 0 made every glGetUniformLocation return -1, so no matrix was ever stored
 * and the MVP fell back to identity - which collapsed every quad onto one
 * pixel at the origin. Per-type counters that wrap to 1, never to 0. */
static int id_tex = 1, id_buf = 1, id_fbo = 1, id_vao = 1, id_prog = 1, id_sh = 1;

static int next_of(int *c, int max)
{
    int v = *c;
    if (++(*c) >= max) *c = 1;
    return v;
}

static int frame_no, dumped, warned_unknown;

/* Readback counters. A gl* call the game READS BACK forces a round trip once
 * rendering moves to a host process, so it matters a great deal whether these
 * happen at init or every frame. */
static long rb_error, rb_integerv, rb_uniloc, rb_attrloc, rb_shaderiv, rb_progiv;

int pad_fb_width(void)  { return fb_w; }
int pad_fb_height(void) { return fb_h; }

/* item 44: libEGL routes multi-display titles through pad_target. This
 * rasteriser has one in-guest framebuffer and no windows, so it has nothing
 * to route - but the symbol must exist or libEGL.so.1 fails to link against
 * this backend (buildgl.sh). */
void pad_target(int disp) { (void)disp; }

/* libEGL's eglGetProcAddress asks the backend for extension entry points by
 * name. This rasteriser implements none - notably not the Vivante direct
 * texture the game uploads video through, which glbridge.c does - so every
 * name falls through to libEGL's no-op, exactly as before. */
void *pad_gl_proc(const char *name) { (void)name; return 0; }

static int envint(const char *n, int dflt)
{
    char *p = getenv(n);
    int v = 0, any = 0;
    if (!p) return dflt;
    while (*p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; any = 1; }
    return any ? v : dflt;
}

static void ensure_fb(void)
{
    if (fb_px) return;
    fb_w = envint("PAD_GL_W", 1920);
    fb_h = envint("PAD_GL_H", 1080);
    fb_px = malloc((unsigned long)fb_w * fb_h * 4);
    if (fb_px) memset(fb_px, 0, (unsigned long)fb_w * fb_h * 4);
    rt_px = fb_px; rt_w = fb_w; rt_h = fb_h;
    vp_w = fb_w; vp_h = fb_h;
    sayf("[glraster] default framebuffer %dx%d\n", fb_w, fb_h, 0, 0);
}

/* ---------------- matrices (column major, as GL wants) ---------------- */
static void mat4_identity(float *m)
{
    int i;
    for (i = 0; i < 16; i++) m[i] = 0.0f;
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

static void mat4_mul(float *r, const float *a, const float *b)   /* r = a*b */
{
    int c, k;
    float t[16];
    for (c = 0; c < 4; c++)
        for (k = 0; k < 4; k++) {
            int i;
            float s = 0.0f;
            for (i = 0; i < 4; i++) s += a[i * 4 + k] * b[c * 4 + i];
            t[c * 4 + k] = s;
        }
    for (c = 0; c < 16; c++) r[c] = t[c];
}

static void mat4_xform(float *out, const float *m, const float *v)
{
    int k;
    for (k = 0; k < 4; k++)
        out[k] = m[0 * 4 + k] * v[0] + m[1 * 4 + k] * v[1]
               + m[2 * 4 + k] * v[2] + m[3 * 4 + k] * v[3];
}

/* ---------------- uniforms by name ---------------- */
static int uni_slot(int p, const char *name)
{
    int i;
    if (p <= 0 || p >= MAXPROG) return -1;
    for (i = 0; i < prog[p].ucount; i++)
        if (!strcmp(prog[p].uname[i], name)) return i;
    if (prog[p].ucount >= MAXUNI) return -1;
    i = prog[p].ucount++;
    snprintf(prog[p].uname[i], 32, "%s", name);
    return i;
}

static const float *uni_get(int p, const char *name)
{
    int i;
    if (p <= 0 || p >= MAXPROG) return 0;
    for (i = 0; i < prog[p].ucount; i++)
        if (!strcmp(prog[p].uname[i], name)) return prog[p].uval[i];
    return 0;
}

/* ---------------- texture upload ---------------- */
static void tex_alloc(int id, int w, int h)
{
    if (id <= 0 || id >= MAXTEX || w <= 0 || h <= 0) return;
    if (tex[id].px) free(tex[id].px);
    tex[id].px = malloc((unsigned long)w * h * 4);
    tex[id].w = w; tex[id].h = h;
    if (tex[id].px) memset(tex[id].px, 0, (unsigned long)w * h * 4);
}

static void put_rgba(unsigned char *d, int r, int g, int b, int a)
{
    d[0] = (unsigned char)r; d[1] = (unsigned char)g;
    d[2] = (unsigned char)b; d[3] = (unsigned char)a;
}

/* Convert whatever the game hands us into RGBA8. The three-plane video path
 * uploads LUMINANCE/RED planes, which is why those matter here. */
static void tex_convert(int id, int x0, int y0, int w, int h,
                        unsigned int fmt, unsigned int type, const unsigned char *src)
{
    int y, x, sp;
    if (id <= 0 || id >= MAXTEX || !tex[id].px || !src) return;
    if (type != GL_UNSIGNED_BYTE) return;
    switch (fmt) {
    case GL_RGBA:            sp = 4; break;
    case GL_RGB:             sp = 3; break;
    case GL_LUMINANCE_ALPHA: sp = 2; break;
    case GL_LUMINANCE: case GL_ALPHA: case GL_RED: sp = 1; break;
    default: return;
    }
    for (y = 0; y < h; y++) {
        int ty = y0 + y;
        if (ty < 0 || ty >= tex[id].h) continue;
        for (x = 0; x < w; x++) {
            int tx = x0 + x;
            const unsigned char *s = src + ((unsigned long)y * w + x) * sp;
            unsigned char *d;
            if (tx < 0 || tx >= tex[id].w) continue;
            d = tex[id].px + ((unsigned long)ty * tex[id].w + tx) * 4;
            switch (fmt) {
            case GL_RGBA:            put_rgba(d, s[0], s[1], s[2], s[3]); break;
            case GL_RGB:             put_rgba(d, s[0], s[1], s[2], 255);  break;
            case GL_LUMINANCE_ALPHA: put_rgba(d, s[0], s[0], s[0], s[1]); break;
            case GL_ALPHA:           put_rgba(d, 255, 255, 255, s[0]);    break;
            default:                 put_rgba(d, s[0], s[0], s[0], 255);  break;
            }
        }
    }
}

/* ---- S3TC, because scene textures on this platform are BC1/BC3 ---- */
static void dxt_colors(const unsigned char *b, unsigned char c[4][4], int dxt1)
{
    int i;
    unsigned int c0 = (unsigned int)b[0] | ((unsigned int)b[1] << 8);
    unsigned int c1 = (unsigned int)b[2] | ((unsigned int)b[3] << 8);
    unsigned int cc[2];
    cc[0] = c0; cc[1] = c1;
    for (i = 0; i < 2; i++) {
        unsigned int v = cc[i];
        c[i][0] = (unsigned char)(((v >> 11) & 31) * 255 / 31);
        c[i][1] = (unsigned char)(((v >> 5) & 63) * 255 / 63);
        c[i][2] = (unsigned char)((v & 31) * 255 / 31);
        c[i][3] = 255;
    }
    if (!dxt1 || c0 > c1) {
        for (i = 0; i < 3; i++) {
            c[2][i] = (unsigned char)((2 * c[0][i] + c[1][i]) / 3);
            c[3][i] = (unsigned char)((c[0][i] + 2 * c[1][i]) / 3);
        }
        c[2][3] = c[3][3] = 255;
    } else {
        for (i = 0; i < 3; i++) c[2][i] = (unsigned char)((c[0][i] + c[1][i]) / 2);
        c[2][3] = 255;
        c[3][0] = c[3][1] = c[3][2] = 0; c[3][3] = 0;
    }
}

static void tex_s3tc(int id, int w, int h, unsigned int ifmt,
                     const unsigned char *src, int size)
{
    int bx, by, dxt1 = (ifmt == GL_COMPRESSED_RGB_S3TC_DXT1 ||
                        ifmt == GL_COMPRESSED_RGBA_S3TC_DXT1);
    int blockbytes = dxt1 ? 8 : 16;
    int bw = (w + 3) / 4, bh = (h + 3) / 4;
    if (!tex[id].px || !src) return;
    if (bw * bh * blockbytes > size) return;
    for (by = 0; by < bh; by++)
        for (bx = 0; bx < bw; bx++) {
            const unsigned char *blk = src + (unsigned long)(by * bw + bx) * blockbytes;
            const unsigned char *cb = dxt1 ? blk : blk + 8;
            unsigned char c[4][4];
            unsigned int bits;
            int i, j;
            unsigned char a[16];
            dxt_colors(cb, c, dxt1);
            bits = (unsigned int)cb[4] | ((unsigned int)cb[5] << 8)
                 | ((unsigned int)cb[6] << 16) | ((unsigned int)cb[7] << 24);
            for (i = 0; i < 16; i++) a[i] = 255;
            if (ifmt == GL_COMPRESSED_RGBA_S3TC_DXT5) {
                unsigned char a0 = blk[0], a1 = blk[1];
                unsigned char tbl[8];
                unsigned long long ab = 0;
                tbl[0] = a0; tbl[1] = a1;
                if (a0 > a1) for (i = 0; i < 6; i++)
                        tbl[2 + i] = (unsigned char)(((6 - i) * a0 + (1 + i) * a1) / 7);
                else {
                    for (i = 0; i < 4; i++)
                        tbl[2 + i] = (unsigned char)(((4 - i) * a0 + (1 + i) * a1) / 5);
                    tbl[6] = 0; tbl[7] = 255;
                }
                for (i = 0; i < 6; i++) ab |= (unsigned long long)blk[2 + i] << (8 * i);
                for (i = 0; i < 16; i++) a[i] = tbl[(ab >> (3 * i)) & 7];
            } else if (ifmt == GL_COMPRESSED_RGBA_S3TC_DXT3) {
                for (i = 0; i < 16; i++) {
                    int nib = (blk[i / 2] >> ((i & 1) ? 4 : 0)) & 15;
                    a[i] = (unsigned char)(nib * 17);
                }
            }
            for (j = 0; j < 4; j++)
                for (i = 0; i < 4; i++) {
                    int px = bx * 4 + i, py = by * 4 + j;
                    int sel = (bits >> (2 * (j * 4 + i))) & 3;
                    unsigned char *d;
                    int al;
                    if (px >= w || py >= h) continue;
                    d = tex[id].px + ((unsigned long)py * tex[id].w + px) * 4;
                    al = c[sel][3];
                    if (ifmt != GL_COMPRESSED_RGB_S3TC_DXT1 &&
                        ifmt != GL_COMPRESSED_RGBA_S3TC_DXT1)
                        al = a[j * 4 + i];
                    put_rgba(d, c[sel][0], c[sel][1], c[sel][2], al);
                }
        }
}

/* ---------------- sampling ---------------- */
static void sample(int id, float u, float v, float *out)
{
    int x, y;
    const unsigned char *p;
    out[0] = out[1] = out[2] = out[3] = 0.0f;
    if (id <= 0 || id >= MAXTEX || !tex[id].px) return;
    /* GL_REPEAT wrap, nearest: the game draws sprites 1:1 so filtering buys
     * little and nearest keeps text atlases crisp. */
    u = u - (float)(int)u; if (u < 0.0f) u += 1.0f;
    v = v - (float)(int)v; if (v < 0.0f) v += 1.0f;
    x = (int)(u * (float)tex[id].w); if (x < 0) x = 0; if (x >= tex[id].w) x = tex[id].w - 1;
    y = (int)(v * (float)tex[id].h); if (y < 0) y = 0; if (y >= tex[id].h) y = tex[id].h - 1;
    p = tex[id].px + ((unsigned long)y * tex[id].w + x) * 4;
    out[0] = p[0] / 255.0f; out[1] = p[1] / 255.0f;
    out[2] = p[2] / 255.0f; out[3] = p[3] / 255.0f;
}

static float clamp01(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }

/* ---------------- fragment shading ---------------- */
static void shade(int p, float u, float v, float oy, float *out)
{
    const float *cm = uni_get(p, "colorTransformMultiply");
    const float *ca = uni_get(p, "colorTransformAdd");
    int i;
    switch (prog[p].frag) {
    case F_SPRITE: {
        const float *sc = uni_get(p, "spriteColor");
        sample(bound_tex[0], u, v, out);
        if (sc) for (i = 0; i < 4; i++) out[i] *= sc[i];
        return;
    }
    case F_VIDEO: {
        float Y[4], U[4], V[4];
        float y, cu, cv;
        sample(bound_tex[0], u, v, Y);
        sample(bound_tex[1], u, v, U);
        sample(bound_tex[2], u, v, V);
        y = 1.1643f * (Y[0] - 0.0625f); cu = U[0] - 0.5f; cv = V[0] - 0.5f;
        out[0] = y + 1.5958f * cv;
        out[1] = y - 0.39173f * cu - 0.81290f * cv;
        out[2] = y + 2.017f * cu;
        out[3] = 1.0f;
        break;
    }
    case F_TEXT: {
        const float *g1 = uni_get(p, "colorFillGradientTransform1");
        const float *g2 = uni_get(p, "colorFillGradientTransform2");
        const float *st = uni_get(p, "colorStroke");
        const float *yo = uni_get(p, "colorFillGradientYOffset");
        const float *gh = uni_get(p, "colorFillGradientHeight");
        const float *ct = uni_get(p, "colorCycleTimeTransform");
        float t[4], Yv, modR, fill, stroke;
        sample(bound_tex[0], u, v, t);
        Yv = (gh && gh[0] != 0.0f) ? (oy - (yo ? yo[0] : 0.0f)) / gh[0] : 0.0f;
        modR = Yv + (ct ? ct[0] : 0.0f);
        modR = modR - (float)(int)modR; if (modR < 0.0f) modR += 1.0f;
        fill = t[1]; stroke = t[0];
        for (i = 0; i < 3; i++) {
            float cf = (g1 ? g1[i] : 1.0f) * modR + (g2 ? g2[i] : 1.0f) * (1.0f - modR);
            out[i] = cf * fill + (st ? st[i] : 0.0f) * stroke;
        }
        out[3] = t[3];
        break;
    }
    case F_SOLID:
        out[0] = 1.0f; out[1] = 0.0f; out[2] = 0.0f; out[3] = 1.0f;
        return;
    case F_UNKNOWN:
        /* Fail loudly: magenta, never an invisible no-op. */
        out[0] = 1.0f; out[1] = 0.0f; out[2] = 1.0f; out[3] = 1.0f;
        return;
    default:
        sample(bound_tex[0], u, v, out);
        break;
    }
    if (cm) for (i = 0; i < 4; i++) out[i] = clamp01(cm[i] * out[i]);
    if (ca) for (i = 0; i < 4; i++) out[i] = clamp01(out[i] + ca[i] * out[3]);
}

/* ---------------- blending ---------------- */
static float blend_factor(int f, float s, float d, float sa, float da)
{
    switch (f) {
    case GL_ZERO: return 0.0f;
    case GL_ONE:  return 1.0f;
    case GL_SRC_ALPHA: return sa;
    case GL_ONE_MINUS_SRC_ALPHA: return 1.0f - sa;
    case 0x0304: return da;             /* GL_DST_ALPHA */
    case 0x0305: return 1.0f - da;      /* GL_ONE_MINUS_DST_ALPHA */
    case 0x0306: return d;              /* GL_DST_COLOR */
    case 0x0300: return s;              /* GL_SRC_COLOR */
    case 0x0301: return 1.0f - s;       /* GL_ONE_MINUS_SRC_COLOR */
    case 0x0307: return 1.0f - d;       /* GL_ONE_MINUS_DST_COLOR */
    default: return 1.0f;
    }
}

static void put_pixel(int x, int y, const float *c)
{
    unsigned char *d;
    int i;
    if (!rt_px || x < 0 || y < 0 || x >= rt_w || y >= rt_h) return;
    d = rt_px + ((unsigned long)y * rt_w + x) * 4;
    if (!blend_on) {
        for (i = 0; i < 4; i++) d[i] = (unsigned char)(clamp01(c[i]) * 255.0f + 0.5f);
        return;
    }
    for (i = 0; i < 4; i++) {
        float s = c[i], dv = d[i] / 255.0f;
        float r = s * blend_factor(blend_src, s, dv, c[3], d[3] / 255.0f)
                + dv * blend_factor(blend_dst, s, dv, c[3], d[3] / 255.0f);
        d[i] = (unsigned char)(clamp01(r) * 255.0f + 0.5f);
    }
}

/* ---------------- vertex fetch ---------------- */
static const unsigned char *attr_base(int loc, int *stride)
{
    Attr *a;
    if (loc < 0 || loc >= MAXATTR) return 0;
    a = &attr[cur_vao][loc];
    if (!a->enabled) return 0;
    *stride = a->stride ? a->stride : (a->size * 4);
    if (a->buffer > 0 && a->buffer < MAXBUF && buf[a->buffer].data)
        return buf[a->buffer].data + a->offset;
    return (const unsigned char *)a->offset;    /* client array */
}

/* ---------------- the rasteriser ---------------- */
typedef struct { float x, y, w, u, v, oy; } Vtx;

/* Per-draw shading telemetry, so "the frame is black" can be attributed to a
 * quad that covered no pixels vs one that covered pixels and shaded them black. */
static long dbg_pixels;
static float dbg_sum[4];
static int dbg_report;

static void fetch_vertex(int p, int idx, Vtx *out, const float *mvp)
{
    const unsigned char *pb, *ub;
    int ps = 0, us = 0;
    float obj[4] = {0, 0, 0, 1}, clip[4];
    float u = 0, v = 0;
    pb = attr_base(prog[p].loc_pos, &ps);
    if (pb) {
        const float *f = (const float *)(pb + (unsigned long)idx * ps);
        obj[0] = f[0]; obj[1] = f[1];
        if (prog[p].packed_vertex) { u = f[2]; v = f[3]; }
        else {
            Attr *a = &attr[cur_vao][prog[p].loc_pos];
            obj[2] = a->size > 2 ? f[2] : 0.0f;
            obj[3] = a->size > 3 ? f[3] : 1.0f;
        }
    }
    if (!prog[p].packed_vertex) {
        ub = attr_base(prog[p].loc_uv, &us);
        if (ub) {
            const float *f = (const float *)(ub + (unsigned long)idx * us);
            u = f[0]; v = f[1];
        }
    }
    mat4_xform(clip, mvp, obj);
    out->w = clip[3] != 0.0f ? clip[3] : 1.0f;
    out->x = (float)vp_x + ((clip[0] / out->w) * 0.5f + 0.5f) * (float)vp_w;
    out->y = (float)vp_y + (1.0f - ((clip[1] / out->w) * 0.5f + 0.5f)) * (float)vp_h;
    out->u = u; out->v = v;
    out->oy = obj[1];      /* the text shader reads object-space y */
}

static void raster_tri(int p, const Vtx *a, const Vtx *b, const Vtx *c)
{
    float minx = a->x, maxx = a->x, miny = a->y, maxy = a->y;
    float area;
    int x, y, x0, x1, y0, y1;
    if (b->x < minx) minx = b->x; if (b->x > maxx) maxx = b->x;
    if (c->x < minx) minx = c->x; if (c->x > maxx) maxx = c->x;
    if (b->y < miny) miny = b->y; if (b->y > maxy) maxy = b->y;
    if (c->y < miny) miny = c->y; if (c->y > maxy) maxy = c->y;
    area = (b->x - a->x) * (c->y - a->y) - (b->y - a->y) * (c->x - a->x);
    if (area > -0.0001f && area < 0.0001f) return;
    x0 = (int)minx; x1 = (int)maxx + 1; y0 = (int)miny; y1 = (int)maxy + 1;
    if (x0 < 0) x0 = 0; if (y0 < 0) y0 = 0;
    if (x1 > rt_w) x1 = rt_w; if (y1 > rt_h) y1 = rt_h;
    for (y = y0; y < y1; y++)
        for (x = x0; x < x1; x++) {
            float px = (float)x + 0.5f, py = (float)y + 0.5f;
            float w0 = ((b->x - a->x) * (py - a->y) - (b->y - a->y) * (px - a->x)) / area;
            float w1 = ((px - a->x) * (c->y - a->y) - (py - a->y) * (c->x - a->x)) / area;
            float w2, u, v, oy, col[4];
            if (w0 < 0.0f || w1 < 0.0f) continue;
            w2 = 1.0f - w0 - w1;
            if (w2 < 0.0f) continue;
            u  = w2 * a->u + w1 * b->u + w0 * c->u;
            v  = w2 * a->v + w1 * b->v + w0 * c->v;
            oy = w2 * a->oy + w1 * b->oy + w0 * c->oy;
            shade(p, u, v, oy, col);
            dbg_pixels++;
            dbg_sum[0] += col[0]; dbg_sum[1] += col[1];
            dbg_sum[2] += col[2]; dbg_sum[3] += col[3];
            put_pixel(x, y, col);
        }
}

/* Three different naming conventions turn up: the sprite shader uses
 * projection/model, the Radium shaders use viewprojMat/modelMat, and there is
 * a Dear ImGui overlay whose single matrix is ProjMtx. Missing ProjMtx left
 * ImGui's screen-space coordinates untransformed and they blew up to millions. */
static void build_mvp(int p, float *mvp)
{
    const float *A = uni_get(p, "projection");
    const float *B = uni_get(p, "model");
    if (!A) A = uni_get(p, "viewprojMat");
    if (!A) A = uni_get(p, "ProjMtx");
    if (!B) B = uni_get(p, "modelMat");
    if (A && B) mat4_mul(mvp, A, B);
    else if (A)  memcpy(mvp, A, 64);
    else if (B)  memcpy(mvp, B, 64);
    else mat4_identity(mvp);
}

static void draw_indexed(unsigned int mode, int count, const int *idx)
{
    float mvp[16];
    int p = cur_prog, i;
    Vtx v[3];
    if (p <= 0 || p >= MAXPROG || !rt_px) return;
    {   /* PAD_GL_NORASTER=1 keeps all the state tracking but skips the pixel
         * loop, so the cost of rasterising in emulated ARM can be isolated. */
        static int nr = -1;
        if (nr < 0) { char *e = getenv("PAD_GL_NORASTER"); nr = (e && e[0] == '1'); }
        if (nr) return;
    }
    if (prog[p].frag == F_UNKNOWN && !warned_unknown) {
        warned_unknown = 1;
        say("[glraster] a program uses a fragment shader this subset does not "
            "implement; it draws MAGENTA so you can see it\n");
    }
    build_mvp(p, mvp);
    /* PAD_GL_DEBUG=1: dump the first few draws so a blank frame can be
     * diagnosed from the numbers instead of guessed at. */
    {
        static int shown;
        char *e = getenv("PAD_GL_DEBUG");
        if (e && e[0] == '1' && shown < 12) {
            Vtx v0;
            char t[240];
            int i;
            shown++;
            fetch_vertex(p, idx[0], &v0, mvp);
            snprintf(t, sizeof t,
                     "[gldbg] prog=%d frag=%d packed=%d locpos=%d locuv=%d "
                     "count=%d tex0=%d rt=%dx%d blend=%d/%d/%d\n",
                     p, prog[p].frag, prog[p].packed_vertex, prog[p].loc_pos,
                     prog[p].loc_uv, count, bound_tex[0], rt_w, rt_h,
                     blend_on, blend_src, blend_dst);
            say(t);
            snprintf(t, sizeof t, "[gldbg]   v0 screen=(%d,%d) uv=(%d,%d)/1000 w=%d/1000\n",
                     (int)v0.x, (int)v0.y, (int)(v0.u * 1000), (int)(v0.v * 1000),
                     (int)(v0.w * 1000));
            say(t);
            snprintf(t, sizeof t, "[gldbg]   uniforms:");
            say(t);
            for (i = 0; i < prog[p].ucount; i++) {
                snprintf(t, sizeof t, " %s", prog[p].uname[i]);
                say(t);
            }
            say("\n");
            dbg_pixels = 0;
            dbg_sum[0] = dbg_sum[1] = dbg_sum[2] = dbg_sum[3] = 0.0f;
            dbg_report = 1;
        }
    }
    if (mode == GL_TRIANGLES) {
        for (i = 0; i + 2 < count; i += 3) {
            fetch_vertex(p, idx[i], &v[0], mvp);
            fetch_vertex(p, idx[i + 1], &v[1], mvp);
            fetch_vertex(p, idx[i + 2], &v[2], mvp);
            raster_tri(p, &v[0], &v[1], &v[2]);
        }
    } else if (mode == GL_TRIANGLE_STRIP) {
        for (i = 0; i + 2 < count; i++) {
            fetch_vertex(p, idx[i], &v[0], mvp);
            fetch_vertex(p, idx[i + 1], &v[1], mvp);
            fetch_vertex(p, idx[i + 2], &v[2], mvp);
            raster_tri(p, &v[0], &v[1], &v[2]);
        }
    } else if (mode == GL_TRIANGLE_FAN) {
        for (i = 1; i + 1 < count; i++) {
            fetch_vertex(p, idx[0], &v[0], mvp);
            fetch_vertex(p, idx[i], &v[1], mvp);
            fetch_vertex(p, idx[i + 1], &v[2], mvp);
            raster_tri(p, &v[0], &v[1], &v[2]);
        }
    }
    if (dbg_report) {
        char t[200];
        dbg_report = 0;
        if (!dbg_pixels)
            say("[gldbg]   -> covered 0 pixels\n");
        else {
            snprintf(t, sizeof t,
                     "[gldbg]   -> %ld px, mean rgba = %d,%d,%d,%d /255\n",
                     dbg_pixels,
                     (int)(dbg_sum[0] / dbg_pixels * 255.0f),
                     (int)(dbg_sum[1] / dbg_pixels * 255.0f),
                     (int)(dbg_sum[2] / dbg_pixels * 255.0f),
                     (int)(dbg_sum[3] / dbg_pixels * 255.0f));
            say(t);
        }
    }
}

int glDrawArrays(unsigned int mode, int first, int count)
{
    int idx[256], i, n = count > 256 ? 256 : count;
    for (i = 0; i < n; i++) idx[i] = first + i;
    draw_indexed(mode, n, idx);
    return 0;
}

int glDrawElements(unsigned int mode, int count, unsigned int type, const void *indices)
{
    int idx[1024], i, n = count > 1024 ? 1024 : count;
    const unsigned char *base = (const unsigned char *)indices;
    if (bound_elem_buf > 0 && bound_elem_buf < MAXBUF && buf[bound_elem_buf].data)
        base = buf[bound_elem_buf].data + (unsigned long)indices;
    if (!base) return 0;
    for (i = 0; i < n; i++) {
        if (type == GL_UNSIGNED_SHORT) idx[i] = ((const unsigned short *)base)[i];
        else if (type == GL_UNSIGNED_INT) idx[i] = (int)((const unsigned int *)base)[i];
        else idx[i] = base[i];
    }
    draw_indexed(mode, n, idx);
    return 0;
}

int glDrawRangeElements(unsigned int mode, unsigned int s, unsigned int e,
                        int count, unsigned int type, const void *indices)
{
    (void)s; (void)e;
    return glDrawElements(mode, count, type, indices);
}

/* ---------------- PNG out (stored deflate, so no zlib needed) ------------ */
static unsigned int crc_tab[256];
static int crc_ready;

static unsigned int crc32_buf(unsigned int c, const unsigned char *p, unsigned long n)
{
    unsigned long i;
    if (!crc_ready) {
        unsigned int k, j;
        for (k = 0; k < 256; k++) {
            unsigned int v = k;
            for (j = 0; j < 8; j++) v = (v & 1) ? (0xEDB88320u ^ (v >> 1)) : (v >> 1);
            crc_tab[k] = v;
        }
        crc_ready = 1;
    }
    for (i = 0; i < n; i++) c = crc_tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c;
}

static void be32(unsigned char *d, unsigned int v)
{
    d[0] = (unsigned char)(v >> 24); d[1] = (unsigned char)(v >> 16);
    d[2] = (unsigned char)(v >> 8);  d[3] = (unsigned char)v;
}

static void png_chunk(int fd, const char *tag, const unsigned char *data, unsigned int n)
{
    unsigned char hdr[8], crcb[4];
    unsigned int c;
    be32(hdr, n);
    hdr[4] = (unsigned char)tag[0]; hdr[5] = (unsigned char)tag[1];
    hdr[6] = (unsigned char)tag[2]; hdr[7] = (unsigned char)tag[3];
    write(fd, hdr, 8);
    if (n) write(fd, data, n);
    c = crc32_buf(0xFFFFFFFFu, hdr + 4, 4);
    if (n) c = crc32_buf(c, data, n);
    be32(crcb, c ^ 0xFFFFFFFFu);
    write(fd, crcb, 4);
}

static void write_png(const char *path, const unsigned char *rgba, int w, int h)
{
    static const unsigned char sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
    unsigned char ihdr[13];
    unsigned char *raw, *z;
    unsigned long rawlen = (unsigned long)h * (w * 3 + 1), zlen, o = 0, i;
    unsigned int a = 1, b = 0;
    int fd = open(path, 0x41 | 0x200, 0644);   /* O_WRONLY|O_CREAT|O_TRUNC */
    if (fd < 0) return;
    write(fd, sig, 8);
    be32(ihdr, (unsigned int)w); be32(ihdr + 4, (unsigned int)h);
    ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;  /* RGB8 */
    png_chunk(fd, "IHDR", ihdr, 13);

    raw = malloc(rawlen);
    if (!raw) { close(fd); return; }
    for (i = 0; i < (unsigned long)h; i++) {
        int x;
        raw[o++] = 0;
        for (x = 0; x < w; x++) {
            const unsigned char *s = rgba + ((unsigned long)i * w + x) * 4;
            raw[o++] = s[0]; raw[o++] = s[1]; raw[o++] = s[2];
        }
    }
    for (i = 0; i < rawlen; i++) {
        a = (a + raw[i]) % 65521; b = (b + a) % 65521;
    }
    /* zlib header + stored deflate blocks + adler32 */
    zlen = 2 + ((rawlen + 65534) / 65535) * 5 + rawlen + 4;
    z = malloc(zlen);
    if (!z) { free(raw); close(fd); return; }
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
    png_chunk(fd, "IDAT", z, (unsigned int)o);
    png_chunk(fd, "IEND", 0, 0);
    close(fd);
    free(z); free(raw);
}

/* Called by eglshim.c's eglSwapBuffers. Kept here so the framebuffer and all
 * the GL state exist exactly once, in one shared object. */
void pad_present(void)
{
    static int every, maxframes, inited;
    char path[160];
    const char *dir;
    ensure_fb();
    if (!inited) {
        inited = 1;
        every = envint("PAD_GL_FRAME_EVERY", 30);
        maxframes = envint("PAD_GL_MAX_FRAMES", 40);
    }
    frame_no++;
    dir = getenv("PAD_GL_DUMP");
    if (!dir || !fb_px) return;
    {   /* Draws reported plenty of lit pixels while the saved frame came out
         * black, so state plainly whether the default framebuffer is the thing
         * being drawn into at present time. */
        char *e = getenv("PAD_GL_DEBUG");
        static int shown;
        if (e && e[0] == '1' && shown < 6) {
            long i, n = (long)fb_w * fb_h, lit = 0;
            char t[180];
            shown++;
            for (i = 0; i < n; i++)
                if (fb_px[i * 4] | fb_px[i * 4 + 1] | fb_px[i * 4 + 2]) lit++;
            snprintf(t, sizeof t,
                     "[gldbg] present frame %d: fb %ld%% non-black, "
                     "render target %s default fb (rt=%dx%d)\n",
                     frame_no, n ? lit * 100 / n : 0,
                     rt_px == fb_px ? "IS" : "is NOT", rt_w, rt_h);
            say(t);
        }
    }
    if (every <= 0) every = 1;
    if (frame_no % every) return;
    if (dumped >= maxframes) return;
    dumped++;
    snprintf(path, sizeof path, "%s/frame_%04d.png", dir, frame_no);
    write_png(path, fb_px, fb_w, fb_h);
    sayf("[glraster] wrote frame %d (%dx%d)\n", frame_no, fb_w, fb_h, 0);
}

/* ---------------- state entry points ---------------- */
int glGenTextures(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) ids[i] = (unsigned int)next_of(&id_tex, MAXTEX); return 0; }
int glGenBuffers(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) ids[i] = (unsigned int)next_of(&id_buf, MAXBUF); return 0; }
int glGenFramebuffers(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) ids[i] = (unsigned int)next_of(&id_fbo, MAXFBO); return 0; }
int glGenVertexArrays(int n, unsigned int *ids)
{ int i; for (i = 0; i < n; i++) ids[i] = (unsigned int)next_of(&id_vao, MAXVAO); return 0; }

int glActiveTexture(unsigned int u) { active_unit = (int)(u - 0x84C0); if (active_unit < 0 || active_unit > 7) active_unit = 0; return 0; }
int glBindTexture(unsigned int t, unsigned int id) { (void)t; bound_tex[active_unit] = (int)id; return 0; }

int glTexImage2D(unsigned int target, int level, int ifmt, int w, int h,
                 int border, unsigned int fmt, unsigned int type, const void *px)
{
    int id = bound_tex[active_unit];
    (void)target; (void)border; (void)ifmt;
    if (level != 0) return 0;
    tex_alloc(id, w, h);
    if (px) tex_convert(id, 0, 0, w, h, fmt, type, px);
    {   /* A black frame can also mean the textures themselves arrived empty. */
        char *e = getenv("PAD_GL_DEBUG");
        static int shown;
        if (e && e[0] == '1' && shown < 16 && tex[id].px) {
            long i, n = (long)w * h, lit = 0;
            char t[160];
            shown++;
            for (i = 0; i < n; i++)
                if (tex[id].px[i * 4] | tex[id].px[i * 4 + 1] | tex[id].px[i * 4 + 2])
                    lit++;
            snprintf(t, sizeof t,
                     "[gldbg] tex %d %dx%d fmt=0x%x  %ld%% non-black%s\n",
                     id, w, h, (int)fmt, n ? lit * 100 / n : 0,
                     px ? "" : "  (NO DATA)");
            say(t);
        }
    }
    return 0;
}

int glTexSubImage2D(unsigned int target, int level, int x, int y, int w, int h,
                    unsigned int fmt, unsigned int type, const void *px)
{
    (void)target;
    if (level == 0) tex_convert(bound_tex[active_unit], x, y, w, h, fmt, type, px);
    return 0;
}

int glCompressedTexImage2D(unsigned int target, int level, unsigned int ifmt,
                           int w, int h, int border, int size, const void *data)
{
    int id = bound_tex[active_unit];
    (void)target; (void)border;
    if (level != 0) return 0;
    tex_alloc(id, w, h);
    if (ifmt >= GL_COMPRESSED_RGB_S3TC_DXT1 && ifmt <= GL_COMPRESSED_RGBA_S3TC_DXT5)
        tex_s3tc(id, w, h, ifmt, data, size);
    else {
        static int once;
        if (!once) { once = 1; sayf("[glraster] unsupported compressed format 0x%x\n",
                                    (int)ifmt, 0, 0, 0); }
    }
    return 0;
}

int glCompressedTexSubImage2D(unsigned int t, int l, int x, int y, int w, int h,
                              unsigned int f, int size, const void *d)
{ (void)t; (void)l; (void)x; (void)y; (void)w; (void)h; (void)f; (void)size; (void)d; return 0; }

int glBindBuffer(unsigned int target, unsigned int id)
{
    if (target == GL_ELEMENT_ARRAY_BUFFER) bound_elem_buf = (int)id;
    else bound_array_buf = (int)id;
    return 0;
}

int glBufferData(unsigned int target, long size, const void *data, unsigned int usage)
{
    int id = (target == GL_ELEMENT_ARRAY_BUFFER) ? bound_elem_buf : bound_array_buf;
    (void)usage;
    if (id <= 0 || id >= MAXBUF || size <= 0) return 0;
    if (buf[id].data) free(buf[id].data);
    buf[id].data = malloc((unsigned long)size);
    buf[id].size = (int)size;
    if (buf[id].data) {
        if (data) memcpy(buf[id].data, data, (unsigned long)size);
        else memset(buf[id].data, 0, (unsigned long)size);
    }
    return 0;
}

int glBufferSubData(unsigned int target, long off, long size, const void *data)
{
    int id = (target == GL_ELEMENT_ARRAY_BUFFER) ? bound_elem_buf : bound_array_buf;
    if (id <= 0 || id >= MAXBUF || !buf[id].data || !data) return 0;
    if (off + size <= buf[id].size) memcpy(buf[id].data + off, data, (unsigned long)size);
    return 0;
}

int glBindVertexArray(unsigned int id) { cur_vao = (int)id % MAXVAO; return 0; }

int glVertexAttribPointer(unsigned int index, int size, unsigned int type,
                          unsigned char norm, int stride, const void *ptr)
{
    Attr *a;
    (void)norm;
    if (index >= MAXATTR) return 0;
    a = &attr[cur_vao][index];
    a->buffer = bound_array_buf; a->size = size; a->type = (int)type;
    a->stride = stride; a->offset = (unsigned long)ptr;
    return 0;
}

int glEnableVertexAttribArray(unsigned int i)
{ if (i < MAXATTR) attr[cur_vao][i].enabled = 1; return 0; }
int glDisableVertexAttribArray(unsigned int i)
{ if (i < MAXATTR) attr[cur_vao][i].enabled = 0; return 0; }

/* ---- shaders / programs ---- */
int glCreateShader(unsigned int type)
{
    int id = next_of(&id_sh, MAXSH);
    sh_frag[id] = (type == 0x8B31) ? -1 : F_UNKNOWN;   /* 0x8B31 = VERTEX_SHADER */
    sh_packed[id] = 0;
    return id;
}

int glCreateProgram(void)
{
    int id = next_of(&id_prog, MAXPROG);
    prog[id].frag = F_UNKNOWN;
    prog[id].loc_pos = 0;
    prog[id].loc_uv = 1;
    prog[id].ucount = 0;
    return id;
}

int glShaderSource(unsigned int sh, int count, const char *const *str, const int *len)
{
    int i;
    (void)len;
    if (sh >= MAXSH || !str) return 0;
    for (i = 0; i < count; i++) {
        const char *s = str[i];
        if (!s) continue;
        if (strstr(s, "textureYSampler"))            sh_frag[sh] = F_VIDEO;
        else if (strstr(s, "colorFillGradient"))     sh_frag[sh] = F_TEXT;
        else if (strstr(s, "spriteColor"))           sh_frag[sh] = F_SPRITE;
        else if (strstr(s, "vec4(255.0, 0.0"))       sh_frag[sh] = F_SOLID;
        else if (strstr(s, "gl_FragColor") || strstr(s, "out lowp vec4 color"))
                                                     sh_frag[sh] = F_PLAIN;
        if (strstr(s, "gl_Position")) {
            sh_frag[sh] = -1;
            sh_packed[sh] = strstr(s, "in vec4 vertex") ? 1 : 0;
        }
    }
    return 0;
}

int glAttachShader(unsigned int p, unsigned int sh)
{
    if (p >= MAXPROG || sh >= MAXSH) return 0;
    if (sh_frag[sh] >= 0) prog[p].frag = sh_frag[sh];
    else prog[p].packed_vertex = sh_packed[sh];
    return 0;
}

int glUseProgram(unsigned int p) { cur_prog = (int)p % MAXPROG; return 0; }

int glGetUniformLocation(unsigned int p, const char *name)
{
    int s = uni_slot((int)p, name);
    rb_uniloc++;
    return s < 0 ? -1 : (int)p * MAXUNI + s;
}

static float *uni_ptr(int loc)
{
    int p = loc / MAXUNI, s = loc % MAXUNI;
    if (loc < 0 || p <= 0 || p >= MAXPROG || s >= MAXUNI) return 0;
    return prog[p].uval[s];
}

int glUniform1f(int loc, float a) { float *u = uni_ptr(loc); if (u) u[0] = a; return 0; }
int glUniform1i(int loc, int a)   { float *u = uni_ptr(loc); if (u) u[0] = (float)a; return 0; }
int glUniform2f(int loc, float a, float b)
{ float *u = uni_ptr(loc); if (u) { u[0] = a; u[1] = b; } return 0; }
int glUniform3f(int loc, float a, float b, float c)
{ float *u = uni_ptr(loc); if (u) { u[0] = a; u[1] = b; u[2] = c; } return 0; }
int glUniform4f(int loc, float a, float b, float c, float d)
{ float *u = uni_ptr(loc); if (u) { u[0] = a; u[1] = b; u[2] = c; u[3] = d; } return 0; }
int glUniform4fv(int loc, int n, const float *v)
{ float *u = uni_ptr(loc); (void)n; if (u && v) memcpy(u, v, 16); return 0; }
int glUniformMatrix4fv(int loc, int n, unsigned char transpose, const float *v)
{ float *u = uni_ptr(loc); (void)n; (void)transpose; if (u && v) memcpy(u, v, 64); return 0; }

int glBindAttribLocation(unsigned int p, unsigned int idx, const char *name)
{
    if (p >= MAXPROG || !name) return 0;
    if (strstr(name, "TextureCoordinate") || strstr(name, "texCoord"))
        prog[p].loc_uv = (int)idx;
    else prog[p].loc_pos = (int)idx;
    return 0;
}

int glGetAttribLocation(unsigned int p, const char *name)
{
    rb_attrloc++;
    if (p >= MAXPROG || !name) return 0;
    if (strstr(name, "TextureCoordinate") || strstr(name, "texCoord")) return prog[p].loc_uv;
    return prog[p].loc_pos;
}

/* ---- framebuffer objects ---- */
int glBindFramebuffer(unsigned int target, unsigned int id)
{
    (void)target;
    ensure_fb();
    cur_fbo = (int)id % MAXFBO;
    if (cur_fbo == 0) { rt_px = fb_px; rt_w = fb_w; rt_h = fb_h; }
    else {
        int t = fbo_tex[cur_fbo];
        if (t > 0 && t < MAXTEX && tex[t].px) { rt_px = tex[t].px; rt_w = tex[t].w; rt_h = tex[t].h; }
        else { rt_px = fb_px; rt_w = fb_w; rt_h = fb_h; }
    }
    return 0;
}

int glFramebufferTexture2D(unsigned int target, unsigned int att, unsigned int tt,
                           unsigned int t, int level)
{
    (void)target; (void)tt; (void)level;
    if (att == GL_COLOR_ATTACHMENT0 && cur_fbo > 0 && cur_fbo < MAXFBO) {
        fbo_tex[cur_fbo] = (int)t;
        if ((int)t > 0 && (int)t < MAXTEX && tex[t].px) {
            rt_px = tex[t].px; rt_w = tex[t].w; rt_h = tex[t].h;
        }
    }
    return 0;
}

int glCheckFramebufferStatus(unsigned int t) { (void)t; return GL_FRAMEBUFFER_COMPLETE; }

/* ---- raster state ---- */
int glViewport(int x, int y, int w, int h)
{
    static int said;
    ensure_fb();
    vp_x = x; vp_y = y; vp_w = w; vp_h = h;
    if (!said) { said = 1; sayf("[glraster] first glViewport %d,%d %dx%d\n", x, y, w, h); }
    return 0;
}

int glClearColor(float r, float g, float b, float a)
{ clear_r = r; clear_g = g; clear_b = b; clear_a = a; return 0; }

int glClear(unsigned int mask)
{
    unsigned long i, n;
    unsigned char c[4];
    ensure_fb();
    if (!(mask & 0x4000) || !rt_px) return 0;    /* GL_COLOR_BUFFER_BIT */
    c[0] = (unsigned char)(clamp01(clear_r) * 255.0f);
    c[1] = (unsigned char)(clamp01(clear_g) * 255.0f);
    c[2] = (unsigned char)(clamp01(clear_b) * 255.0f);
    c[3] = (unsigned char)(clamp01(clear_a) * 255.0f);
    n = (unsigned long)rt_w * rt_h;
    for (i = 0; i < n; i++) memcpy(rt_px + i * 4, c, 4);
    return 0;
}

int glEnable(unsigned int cap)  { if (cap == GL_BLEND) blend_on = 1; return 0; }
int glDisable(unsigned int cap) { if (cap == GL_BLEND) blend_on = 0; return 0; }
int glIsEnabled(unsigned int cap) { return cap == GL_BLEND ? blend_on : 1; }
int glBlendFunc(unsigned int s, unsigned int d) { blend_src = (int)s; blend_dst = (int)d; return 0; }
int glBlendFuncSeparate(unsigned int s, unsigned int d, unsigned int as, unsigned int ad)
{ (void)as; (void)ad; blend_src = (int)s; blend_dst = (int)d; return 0; }

int glReadPixels(int x, int y, int w, int h, unsigned int fmt, unsigned int type, void *px)
{
    int j;
    (void)fmt; (void)type;
    if (!rt_px || !px) return 0;
    for (j = 0; j < h; j++) {
        int sy = y + j;
        if (sy < 0 || sy >= rt_h) continue;
        memcpy((unsigned char *)px + (unsigned long)j * w * 4,
               rt_px + ((unsigned long)sy * rt_w + x) * 4, (unsigned long)w * 4);
    }
    return 0;
}

/* ---- queries that must answer plausibly ---- */
static const char *VENDOR   = "pinball-asset-decryptor";
static const char *RENDERER = "glraster software";
static const char *VERSION  = "OpenGL ES 3.0 glraster";
static const char *SLVER    = "OpenGL ES GLSL ES 3.00";

const char *glGetString(unsigned int name)
{
    switch (name) {
    case 0x1F00: return VENDOR;
    case 0x1F01: return RENDERER;
    case 0x1F02: return VERSION;
    case 0x8B8C: return SLVER;
    case 0x1F03: return "";
    default: return "";
    }
}

long pad_readback_counts(long *e, long *i, long *u, long *a, long *s, long *p)
{ *e=rb_error; *i=rb_integerv; *u=rb_uniloc; *a=rb_attrloc; *s=rb_shaderiv; *p=rb_progiv; return frame_no; }
int glGetError(void) { rb_error++; return 0; }
/* Which pnames does the game ask for, and how often? Anything queried per
 * frame has to be answerable locally or the bridge pays a round trip. */
static unsigned int gi_pname[8];
static long gi_count[8];
long pad_getintegerv_hist(unsigned int *names, long *counts)
{ int i; for (i = 0; i < 8; i++) { names[i] = gi_pname[i]; counts[i] = gi_count[i]; } return 8; }

int glGetIntegerv(unsigned int p, int *v)
{
    int k;
    rb_integerv++;
    for (k = 0; k < 8; k++) {
        if (gi_count[k] && gi_pname[k] != p) continue;
        gi_pname[k] = p; gi_count[k]++; break;
    }
    if (!v) return 0;
    switch (p) {
    case 0x0D33: *v = 4096; break;               /* MAX_TEXTURE_SIZE      */
    case 0x8872: *v = 8;    break;               /* MAX_TEXTURE_IMAGE_UNITS */
    case 0x8DFB: case 0x8DFC: *v = 256; break;   /* MAX_*_UNIFORM_VECTORS */
    case 0x8869: *v = 16;   break;               /* MAX_VERTEX_ATTRIBS    */
    default: *v = 0; break;
    }
    return 0;
}
int glGetBooleanv(unsigned int p, unsigned char *v) { (void)p; if (v) *v = 0; return 0; }
int glGetShaderiv(unsigned int s, unsigned int p, int *v) { rb_shaderiv++; (void)s; (void)p; if (v) *v = 1; return 0; }
int glGetProgramiv(unsigned int s, unsigned int p, int *v) { rb_progiv++; (void)s; (void)p; if (v) *v = 1; return 0; }
int glGetShaderInfoLog(unsigned int s, int m, int *l, char *b)
{ (void)s; (void)m; if (l) *l = 0; if (b) b[0] = 0; return 0; }
int glGetProgramInfoLog(unsigned int s, int m, int *l, char *b)
{ (void)s; (void)m; if (l) *l = 0; if (b) b[0] = 0; return 0; }

/* ---- the genuinely uninteresting rest ---- */
#define NOOP(name) int name(void) { return 0; }
NOOP(glAttachShader_unused)
NOOP(glCompileShader)
NOOP(glDeleteBuffers)
NOOP(glDeleteProgram)
NOOP(glDeleteShader)
NOOP(glDeleteSync)
NOOP(glDeleteTextures)
NOOP(glDeleteVertexArrays)
NOOP(glDetachShader)
NOOP(glDrawBuffers)
NOOP(glLineWidth)
NOOP(glLinkProgram)
NOOP(glScissor)
NOOP(glTexParameteri)
NOOP(glBlendEquation)
NOOP(glBlendEquationSeparate)
NOOP(glFenceSync)
NOOP(glClientWaitSync)
