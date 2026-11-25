/* egl_stern.c - see egl_stern.h.
 *
 * The call order and the attribute lists are boot_display's, byte for byte
 * (glWindow::create_window @0x12010; lists at .rodata 0x212dc / 0x2129c; the
 * turtles game ELF carries the identical lists). Only symbols exported by BOTH
 * Vivante's libEGL/libGLESv2 and the rig's bridge shims are used: no
 * eglDestroy*, no glPixelStorei, no glGetShaderiv gating, no client-side
 * vertex arrays.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "egl_stern.h"
#include "log.h"

/* ---- hand-written prototypes: no EGL/GLES headers exist on the box ---- */
extern void *fbGetDisplayByIndex(int);
extern void  fbGetDisplayGeometry(void *, int *, int *);
extern void *fbCreateWindow(void *, int, int, int, int);
extern void *eglGetDisplay(void *);
extern int   eglInitialize(void *, int *, int *);
extern int   eglChooseConfig(void *, const int *, void **, int, int *);
extern void *eglCreateWindowSurface(void *, void *, void *, const int *);
extern int   eglBindAPI(unsigned);
extern void *eglCreateContext(void *, void *, void *, const int *);
extern int   eglMakeCurrent(void *, void *, void *, void *);
extern int   eglSwapBuffers(void *, void *);
extern int   eglTerminate(void *);
extern int   eglReleaseThread(void);
extern int   eglGetError(void);

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
extern unsigned glGetError(void);

#define EGL_SUCCESS        0x3000
#define EGL_OPENGL_ES_API  0x30A0
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
#define GL_COLOR_DEPTH_BITS 0x4100
#define GL_LUMINANCE       0x1909
#define GL_LUMINANCE_ALPHA 0x190A
#define GL_NEAREST         0x2600
#define GL_DYNAMIC_DRAW    0x88E8
#define FOURCC_NV12        0x3231564Eu      /* 'N' 'V' '1' '2' */
#define FOURCC_YV12        0x32315659u      /* 'Y' 'V' '1' '2' */

/* boot_display .rodata 0x212dc: RGB 5/6/5, ALPHA don't-care, SAMPLES 0, DEPTH 24 */
static const int cfg_attr[] = { 0x3024, 5, 0x3023, 6, 0x3022, 5, 0x3021, -1,
                                0x3031, 0, 0x3025, 24, 0x3038 };
/* boot_display .rodata 0x2129c: EGL_CONTEXT_CLIENT_VERSION 2 */
static const int ctx_attr[] = { 0x3098, 2, 0x3038 };

/* boot_display's sprite shader pair (its own assert strings), minus the
 * model matrix and the colour tint the menu does not need. */
static const char *VS =
    "#version 300 es\n"
    "layout (location = 0) in vec4 vertex; // <vec2 position, vec2 texCoords>\n"
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

/* THE VIDEO LAYER's shader: BT.601 limited range, the numbers gstclip.c's CPU
 * conversion uses (298/409/100/208/516 over 256).  NV12's chroma is one two-channel
 * texture (U in L, V in A); I420/YV12's two one-channel ones. */
static const char *YFS =
    "#version 300 es\n"
    "in highp vec2 TexCoords;\n"
    "out lowp vec4 color;\n"
    "uniform sampler2D ty;\n"
    "uniform sampler2D tu;\n"
    "uniform sampler2D tv;\n"
    "uniform int nv12;\n"
    "void main() {\n"
    "    highp float y = 1.1640625 * (texture(ty, TexCoords).r - 0.0627451);\n"
    "    highp float u, v;\n"
    "    if (nv12 == 1) { highp vec4 c = texture(tu, TexCoords); u = c.r - 0.5019608; v = c.a - 0.5019608; }\n"
    "    else { u = texture(tu, TexCoords).r - 0.5019608; v = texture(tv, TexCoords).r - 0.5019608; }\n"
    "    color = vec4(y + 1.5976563 * v, y - 0.390625 * u - 0.8125 * v, y + 2.015625 * u, 1.0);\n"
    "}\n";

static int egl_ok(const char *step)
{
    int e = eglGetError();
    if (e != EGL_SUCCESS) {
        sel_log("egl: %s failed, eglGetError=0x%x", step, e);
        return 0;
    }
    return 1;
}

static void egl_drop(struct egl_stern *e)
{
    if (e->dpy) {
        eglMakeCurrent(e->dpy, 0, 0, 0);
        eglTerminate(e->dpy);
    }
    eglReleaseThread();
    e->dpy = e->cfg = e->win = e->surf = e->ctx = NULL;
    e->up = 0;
}

static int try_init(struct egl_stern *e)
{
    int maj = 0, min = 0, n = 0;

    setenv("FB_MULTI_BUFFER", "2", 0);                 /* @0x12054 */
    e->fbd = fbGetDisplayByIndex(0);                   /* @0x1205c */
    if (!e->fbd) { sel_log("egl: fbGetDisplayByIndex(0) returned NULL"); return -1; }
    e->dpy = eglGetDisplay(e->fbd);                    /* @0x12064 */
    if (!e->dpy) { sel_log("egl: eglGetDisplay returned EGL_NO_DISPLAY"); return -1; }
    if (!eglInitialize(e->dpy, &maj, &min) || !egl_ok("eglInitialize")) return -1;   /* @0x12074 */
    sel_log("egl: initialised %d.%d", maj, min);
    if (!eglChooseConfig(e->dpy, cfg_attr, &e->cfg, 1, &n) || !egl_ok("eglChooseConfig") || n != 1) {
        sel_log("egl: eglChooseConfig gave %d configs", n);                        /* @0x1209c */
        return -1;
    }
    e->w = e->h = 0;
    fbGetDisplayGeometry(e->fbd, &e->w, &e->h);        /* @0x12448 */
    if (e->w <= 0 || e->h <= 0) {
        sel_log("egl: fbGetDisplayGeometry gave %dx%d, assuming 1360x768", e->w, e->h);
        e->w = 1360;
        e->h = 768;
    }
    e->win = fbCreateWindow(e->fbd, 0, 0, e->w, e->h); /* @0x120e0 */
    if (!e->win) { sel_log("egl: fbCreateWindow returned NULL"); return -1; }
    e->surf = eglCreateWindowSurface(e->dpy, e->cfg, e->win, NULL);   /* @0x120f0 */
    if (!e->surf || !egl_ok("eglCreateWindowSurface")) return -1;
    if (!eglBindAPI(EGL_OPENGL_ES_API) || !egl_ok("eglBindAPI")) return -1;     /* @0x12108 */
    e->ctx = eglCreateContext(e->dpy, e->cfg, NULL, ctx_attr);        /* @0x12118 */
    if (!e->ctx || !egl_ok("eglCreateContext")) return -1;
    if (!eglMakeCurrent(e->dpy, e->surf, e->surf, e->ctx) || !egl_ok("eglMakeCurrent")) return -1; /* @0x1213c */
    /* Stern's first frame: clear + swap, then the viewport and blending */
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_DEPTH_BITS);
    eglSwapBuffers(e->dpy, e->surf);                   /* @0x1215c..0x1217c */
    glViewport(0, 0, e->w, e->h);                      /* @0x1219c */
    glEnable(GL_BLEND);                                /* @0x121c4 */
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); /* @0x121dc */
    sel_log("egl: display %dx%d, GL_VERSION '%s' renderer '%s'", e->w, e->h,
            (const char *)glGetString(0x1F02), (const char *)glGetString(0x1F01));
    return 0;
}

static float e_proj[16];        /* the canvas's ortho matrix, for the video layer too */

static void build_program(struct egl_stern *e)
{
    unsigned vs, fs;
    float m[16];
    float q[24];
    float w = (float)e->w, h = (float)e->h;

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
    /* ortho: x 0..w left->right, y 0..h TOP->bottom (column-major). The
     * -invert rotation is applied to the pixels (gfx_pixels), not here, so
     * the headless PPM and the live picture come from one code path. */
    memset(m, 0, sizeof m);
    m[0] = 2.0f / w;
    m[5] = -2.0f / h;
    m[10] = -1.0f;
    m[12] = -1.0f;
    m[13] = 1.0f;
    m[15] = 1.0f;
    glUniformMatrix4fv(glGetUniformLocation(e->prog, "projection"), 1, 0, m);
    memcpy(e_proj, m, sizeof m);
    glUniform1i(glGetUniformLocation(e->prog, "image"), 0);

    /* VAO + VBO ONLY: the bridge refuses client-side arrays */
    glGenVertexArrays(1, &e->vao);
    glBindVertexArray(e->vao);
    glGenBuffers(1, &e->vbo);
    glBindBuffer(GL_ARRAY_BUFFER, e->vbo);
    {   /* x, y, u, v: two triangles covering the display */
        float t[24] = { 0, 0, 0, 0,   w, 0, 1, 0,   w, h, 1, 1,
                        0, 0, 0, 0,   w, h, 1, 1,   0, h, 0, 1 };
        memcpy(q, t, sizeof q);
    }
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
            sel_log("egl: up after %d attempt(s), glGetError=0x%x", attempt, glGetError());
            return 0;
        }
        egl_drop(e);
        if (attempt < retries) {
            sel_log("egl: attempt %d/%d failed, retrying in %d ms", attempt, retries, retry_ms);
            sel_sleep_ms(retry_ms);
        }
    }
    sel_log("egl: giving up after %d attempts", retries);
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
    /* set EXPLICITLY: the bridge keeps per-name shadows across guests */
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    /* RGBA8: 4-byte rows, so the default UNPACK_ALIGNMENT is right and
     * glPixelStorei (which the bridge does not export) is never needed */
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    sel_log("egl: texture %u %dx%d created, glGetError=0x%x", e->tex, w, h, glGetError());
    return 0;
}

/* the video layer's program, textures and quad, once (y_ok 1), or refused (-1) */
static int video_make(struct egl_stern *e)
{
    unsigned vs, fs;
    if (e->y_ok) return e->y_ok;
    vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs, 1, &VS, NULL);
    glCompileShader(vs);
    fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs, 1, &YFS, NULL);
    glCompileShader(fs);
    e->yprog = glCreateProgram();
    glAttachShader(e->yprog, vs);
    glAttachShader(e->yprog, fs);
    glLinkProgram(e->yprog);
    glUseProgram(e->yprog);
    glUniformMatrix4fv(glGetUniformLocation(e->yprog, "projection"), 1, 0, e_proj);
    glUniform1i(glGetUniformLocation(e->yprog, "ty"), 0);
    glUniform1i(glGetUniformLocation(e->yprog, "tu"), 1);
    glUniform1i(glGetUniformLocation(e->yprog, "tv"), 2);
    glGenVertexArrays(1, &e->yvao);
    glBindVertexArray(e->yvao);
    glGenBuffers(1, &e->yvbo);
    glBindBuffer(GL_ARRAY_BUFFER, e->yvbo);
    {
        float q[24];
        memset(q, 0, sizeof q);
        glBufferData(GL_ARRAY_BUFFER, (long)sizeof q, q, GL_DYNAMIC_DRAW);
    }
    glVertexAttribPointer(0, 4, GL_FLOAT, 0, 4 * (int)sizeof(float), (const void *)0);
    glEnableVertexAttribArray(0);
    glGenTextures(3, e->ytex);
    /* back to the canvas's own state: egl_stern_frame sets nothing up per frame */
    glUseProgram(e->prog);
    glBindVertexArray(e->vao);
    glBindBuffer(GL_ARRAY_BUFFER, e->vbo);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, e->tex);
    {
        unsigned err = glGetError();
        sel_log("egl: video layer made (program %u), glGetError=0x%x", e->yprog, err);
        e->y_ok = err ? -1 : 1;
    }
    return e->y_ok;
}

/* one plane into texture unit `unit`: made at this size, else replaced in place */
static void video_plane(struct egl_stern *e, int unit, unsigned fmt, int w, int h, const unsigned char *px,
                        int remake)
{
    glActiveTexture(GL_TEXTURE0 + (unsigned)unit);
    glBindTexture(GL_TEXTURE_2D, e->ytex[unit]);
    if (remake) {
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexImage2D(GL_TEXTURE_2D, 0, (int)fmt, w, h, 0, fmt, GL_UNSIGNED_BYTE, px);
    } else {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, fmt, GL_UNSIGNED_BYTE, px);
    }
    e->uploaded += (long long)w * h * (fmt == GL_LUMINANCE_ALPHA ? 2 : 1);
}

int egl_stern_video(struct egl_stern *e, const unsigned char *data, unsigned fourcc, int w, int h,
                    int stride, int rows, int x, int y, int dw, int dh, int invert)
{
    int nv12 = fourcc == FOURCC_NV12, remake;
    const unsigned char *u, *v;
    if (!e->up) return -1;
    if (!data) { e->y_on = 0; return 0; }
    /* rows of a plane must be 4-byte multiples: no glPixelStorei on the bridge */
    if (stride <= 0 || rows <= 0 || stride % 8 || rows % 2 || w > stride || h > rows) return -1;
    if (video_make(e) < 0) return -1;
    remake = e->y_stride != stride || e->y_rows != rows || e->y_nv12 != nv12;
    e->y_stride = stride;
    e->y_rows = rows;
    e->y_nv12 = nv12;
    u = data + (size_t)stride * rows;
    v = u + (size_t)(stride / 2) * (rows / 2);
    if (fourcc == FOURCC_YV12) { const unsigned char *t = u; u = v; v = t; }
    video_plane(e, 0, GL_LUMINANCE, stride, rows, data, remake);
    if (nv12) {
        video_plane(e, 1, GL_LUMINANCE_ALPHA, stride / 2, rows / 2, u, remake);
    } else {
        video_plane(e, 1, GL_LUMINANCE, stride / 2, rows / 2, u, remake);
        video_plane(e, 2, GL_LUMINANCE, stride / 2, rows / 2, v, remake);
    }
    {   /* the quad: the picture's part of the padded planes, at its place on the screen */
        float um = (float)w / (float)stride, vm = (float)h / (float)rows;
        float x0 = (float)x, y0 = (float)y, x1 = (float)(x + dw), y1 = (float)(y + dh);
        float u0 = 0, v0 = 0, u1 = um, v1 = vm, q[24];
        if (invert) {                    /* the canvas's turn: mirrored place, reversed texture */
            x0 = (float)(e->w - x - dw); y0 = (float)(e->h - y - dh);
            x1 = x0 + (float)dw; y1 = y0 + (float)dh;
            u0 = um; u1 = 0; v0 = vm; v1 = 0;
        }
        {
            float t[24] = { x0, y0, u0, v0,   x1, y0, u1, v0,   x1, y1, u1, v1,
                            x0, y0, u0, v0,   x1, y1, u1, v1,   x0, y1, u0, v1 };
            memcpy(q, t, sizeof q);
        }
        glBindVertexArray(e->yvao);
        glBindBuffer(GL_ARRAY_BUFFER, e->yvbo);
        glBufferData(GL_ARRAY_BUFFER, (long)sizeof q, q, GL_DYNAMIC_DRAW);
        glBindVertexArray(e->vao);
        glBindBuffer(GL_ARRAY_BUFFER, e->vbo);
    }
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, e->tex);
    if (!e->y_on) sel_log("egl: video layer on: %dx%d %s in %dx%d planes, at %d,%d %dx%d, glGetError=0x%x",
                          w, h, nv12 ? "NV12" : fourcc == FOURCC_YV12 ? "YV12" : "I420", stride, rows,
                          x, y, dw, dh, glGetError());
    e->y_on = 1;
    return 0;
}

void egl_stern_frame(struct egl_stern *e, const unsigned char *packed, int x, int y, int w, int h)
{
    if (!e->up) return;
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_DEPTH_BITS);
    if (e->y_on) {                       /* the clip first; the canvas over it, see-through there */
        glUseProgram(e->yprog);
        glBindVertexArray(e->yvao);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, e->ytex[0]);
        glActiveTexture(GL_TEXTURE0 + 1);
        glBindTexture(GL_TEXTURE_2D, e->ytex[1]);
        glActiveTexture(GL_TEXTURE0 + 2);
        glBindTexture(GL_TEXTURE_2D, e->ytex[2]);
        glUniform1i(glGetUniformLocation(e->yprog, "nv12"), e->y_nv12);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glUseProgram(e->prog);
        glBindVertexArray(e->vao);
        glActiveTexture(GL_TEXTURE0);
    }
    glBindTexture(GL_TEXTURE_2D, e->tex);
    if (packed && w > 0 && h > 0) {
        /* the packed rows are w*4 bytes, so the default UNPACK_ALIGNMENT (4)
         * and UNPACK_ROW_LENGTH (0 = the rect's width) hold - glPixelStorei,
         * which the bridge does not export, is never needed */
        glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, packed);
        e->uploaded += (long long)w * h * 4;
    }
    glDrawArrays(GL_TRIANGLES, 0, 6);
    eglSwapBuffers(e->dpy, e->surf);
    e->frames++;
}

void egl_stern_close(struct egl_stern *e)
{
    if (!e->up) return;
    /* default-looking state for whoever draws next (the bridge host keeps
     * GL state across guests; Vivante does not care). NO clear and NO swap
     * here: the LOADING frame was swapped in one vsync ago and has to stay
     * on the LCD until the game's first frame, many seconds later - a
     * teardown swap of a cleared buffer blanked the panel for all of them.
     * The resets are state, not pixels; the bridge needs no swap for them. */
    glBindTexture(GL_TEXTURE_2D, 0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindVertexArray(0);
    glUseProgram(0);
    glDisable(GL_BLEND);
    glViewport(0, 0, e->w, e->h);
    sel_log("egl: %d frames, %lld KB uploaded, closing (the LOADING frame stays up)",
            e->frames, e->uploaded / 1024);
    egl_drop(e);                                       /* boot_display @0x12628 */
}
