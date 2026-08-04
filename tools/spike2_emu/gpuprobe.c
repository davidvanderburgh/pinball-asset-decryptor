/* gpuprobe.c - can a native x86-64 process in this WSL reach a real GPU, and
 * is it fast enough to be worth building a guest->host bridge for?
 *
 * Renders the game's ACTUAL workload: 4 full-screen textured quads at 1080p
 * through the game's own sprite shader, into an FBO, and times it. Built with
 * hand-written declarations so no -dev headers are needed.
 *
 * Uses DESKTOP GL because libGLESv2 is not installed here and there is no
 * passwordless sudo to add it. The GPU throughput measured is the same either
 * way; a real bridge should use GLES to run the game's own shaders verbatim,
 * which means `sudo apt install libgles2`.
 *
 *   gcc -O2 -o gpuprobe gpuprobe.c -l:libEGL.so.1 -l:libGL.so.1
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef void *EGLDisplay, *EGLConfig, *EGLContext, *EGLSurface;
typedef int EGLint;
typedef unsigned int EGLenum, EGLBoolean;

extern EGLDisplay eglGetDisplay(void *);
extern EGLBoolean eglInitialize(EGLDisplay, EGLint *, EGLint *);
extern EGLBoolean eglChooseConfig(EGLDisplay, const EGLint *, EGLConfig *, EGLint, EGLint *);
extern EGLBoolean eglBindAPI(EGLenum);
extern EGLContext eglCreateContext(EGLDisplay, EGLConfig, EGLContext, const EGLint *);
extern EGLSurface eglCreatePbufferSurface(EGLDisplay, EGLConfig, const EGLint *);
extern EGLBoolean eglMakeCurrent(EGLDisplay, EGLSurface, EGLSurface, EGLContext);
extern const char *eglQueryString(EGLDisplay, EGLint);
extern EGLint eglGetError(void);

typedef unsigned int GLenum, GLuint, GLbitfield;
typedef int GLint, GLsizei;
typedef unsigned char GLboolean;
extern const unsigned char *glGetString(GLenum);
extern GLuint glCreateShader(GLenum);
extern void glShaderSource(GLuint, GLsizei, const char *const *, const GLint *);
extern void glCompileShader(GLuint);
extern void glGetShaderiv(GLuint, GLenum, GLint *);
extern void glGetShaderInfoLog(GLuint, GLsizei, GLsizei *, char *);
extern GLuint glCreateProgram(void);
extern void glAttachShader(GLuint, GLuint);
extern void glLinkProgram(GLuint);
extern void glUseProgram(GLuint);
extern GLint glGetUniformLocation(GLuint, const char *);
extern void glUniformMatrix4fv(GLint, GLsizei, GLboolean, const float *);
extern void glUniform4f(GLint, float, float, float, float);
extern void glUniform1i(GLint, GLint);
extern void glGenTextures(GLsizei, GLuint *);
extern void glBindTexture(GLenum, GLuint);
extern void glTexImage2D(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void *);
extern void glTexParameteri(GLenum, GLenum, GLint);
extern void glGenFramebuffers(GLsizei, GLuint *);
extern void glBindFramebuffer(GLenum, GLuint);
extern void glFramebufferTexture2D(GLenum, GLenum, GLenum, GLuint, GLint);
extern GLenum glCheckFramebufferStatus(GLenum);
extern void glGenBuffers(GLsizei, GLuint *);
extern void glBindBuffer(GLenum, GLuint);
extern void glBufferData(GLenum, long, const void *, GLenum);
extern void glVertexAttribPointer(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
extern void glEnableVertexAttribArray(GLuint);
extern void glViewport(GLint, GLint, GLsizei, GLsizei);
extern void glClearColor(float, float, float, float);
extern void glClear(GLbitfield);
extern void glDrawArrays(GLenum, GLint, GLsizei);
extern void glEnable(GLenum);
extern void glBlendFunc(GLenum, GLenum);
extern void glFinish(void);
extern void glGenVertexArrays(GLsizei, GLuint *);
extern void glBindVertexArray(GLuint);
extern GLenum glGetError(void);

#define W 1920
#define H 1080
#define QUADS_PER_FRAME 4
#define FRAMES 300

static double now_s(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

/* The game's own sprite pair, verbatim from the shader dump. */
static const char *VS =
"#version 300 es\n"
"layout (location = 0) in vec4 vertex;\n"
"out vec2 TexCoords;\n"
"uniform mat4 model;\n"
"uniform mat4 projection;\n"
"void main(){ TexCoords = vertex.zw;"
" gl_Position = projection * model * vec4(vertex.xy, 0.0, 1.0); }\n";

static const char *FS =
"#version 300 es\n"
"in highp vec2 TexCoords;\n"
"out lowp vec4 color;\n"
"uniform sampler2D image;\n"
"uniform lowp vec4 spriteColor;\n"
"void main(){ color = spriteColor * texture(image, TexCoords); }\n";

static GLuint mkshader(GLenum type, const char *src)
{
    GLint ok = 0;
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, 0);
    glCompileShader(s);
    glGetShaderiv(s, 0x8B81 /*COMPILE_STATUS*/, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(s, sizeof log, 0, log);
        fprintf(stderr, "shader compile failed:\n%s\n", log);
        exit(1);
    }
    return s;
}

int main(void)
{
    EGLint major, minor, n;
    EGLDisplay dpy;
    EGLConfig cfg;
    EGLContext ctx;
    EGLSurface surf;
    static const EGLint cfgattr[] = {
        0x3033, 0x0001,           /* SURFACE_TYPE, PBUFFER */
        0x3040, 0x0008,           /* RENDERABLE_TYPE, EGL_OPENGL_BIT */
        0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8,   /* R,G,B,A */
        0x3038 };
    static const EGLint pbattr[] = { 0x3057, 16, 0x3056, 16, 0x3038 };  /* W,H */
    static const EGLint ctxattr[] = { 0x3098, 3, 0x30FB, 3,
                                 0x30FD, 0x0001, 0x3038 };  /* GL 3.3 core */

    dpy = eglGetDisplay((void *)0);          /* EGL_DEFAULT_DISPLAY */
    if (!dpy) { fprintf(stderr, "eglGetDisplay failed\n"); return 1; }
    if (!eglInitialize(dpy, &major, &minor)) {
        fprintf(stderr, "eglInitialize failed 0x%x\n", eglGetError()); return 1;
    }
    printf("EGL %d.%d\n", major, minor);
    printf("EGL_VENDOR     : %s\n", eglQueryString(dpy, 0x3053));

    eglBindAPI(0x30A2);                      /* EGL_OPENGL_API */
    if (!eglChooseConfig(dpy, cfgattr, &cfg, 1, &n) || n < 1) {
        fprintf(stderr, "eglChooseConfig failed\n"); return 1;
    }
    surf = eglCreatePbufferSurface(dpy, cfg, pbattr);
    ctx = eglCreateContext(dpy, cfg, 0, ctxattr);
    if (!ctx) { fprintf(stderr, "eglCreateContext failed 0x%x\n", eglGetError()); return 1; }
    if (!eglMakeCurrent(dpy, surf, surf, ctx)) {
        fprintf(stderr, "eglMakeCurrent failed 0x%x\n", eglGetError()); return 1;
    }

    printf("GL_VENDOR      : %s\n", glGetString(0x1F00));
    printf("GL_RENDERER    : %s\n", glGetString(0x1F01));
    printf("GL_VERSION     : %s\n", glGetString(0x1F02));

    {
        GLuint prog = glCreateProgram(), tex, fbo, rt, vbo, vao;
        GLint loc_proj, loc_model, loc_col, loc_img;
        unsigned char *pix;
        float ident[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        /* one full-screen quad in clip space, xy + uv */
        static const float quad[] = {
            -1,-1, 0,0,   1,-1, 1,0,   1, 1, 1,1,
            -1,-1, 0,0,   1, 1, 1,1,  -1, 1, 0,1,
        };
        int i, f;
        double t0, t1;

        glAttachShader(prog, mkshader(0x8B31, VS));
        glAttachShader(prog, mkshader(0x8B30, FS));
        glLinkProgram(prog);
        glUseProgram(prog);
        loc_proj  = glGetUniformLocation(prog, "projection");
        loc_model = glGetUniformLocation(prog, "model");
        loc_col   = glGetUniformLocation(prog, "spriteColor");
        loc_img   = glGetUniformLocation(prog, "image");
        glUniformMatrix4fv(loc_proj, 1, 0, ident);
        glUniformMatrix4fv(loc_model, 1, 0, ident);
        glUniform4f(loc_col, 1, 1, 1, 1);
        glUniform1i(loc_img, 0);

        /* a 1360x768 source texture, the size the game actually uploads */
        pix = malloc(1360 * 768 * 4);
        for (i = 0; i < 1360 * 768 * 4; i++) pix[i] = (unsigned char)(i * 7);
        glGenTextures(1, &tex);
        glBindTexture(0x0DE1, tex);
        glTexImage2D(0x0DE1, 0, 0x1908, 1360, 768, 0, 0x1908, 0x1401, pix);
        glTexParameteri(0x0DE1, 0x2801, 0x2601);   /* MIN_FILTER LINEAR */
        glTexParameteri(0x0DE1, 0x2800, 0x2601);   /* MAG_FILTER LINEAR */
        free(pix);

        /* render into a 1920x1080 target, like the real framebuffer */
        glGenTextures(1, &rt);
        glBindTexture(0x0DE1, rt);
        glTexImage2D(0x0DE1, 0, 0x1908, W, H, 0, 0x1908, 0x1401, 0);
        glGenFramebuffers(1, &fbo);
        glBindFramebuffer(0x8D40, fbo);
        glFramebufferTexture2D(0x8D40, 0x8CE0, 0x0DE1, rt, 0);
        if (glCheckFramebufferStatus(0x8D40) != 0x8CD5) {
            fprintf(stderr, "framebuffer incomplete\n"); return 1;
        }
        glBindTexture(0x0DE1, tex);

        glGenVertexArrays(1, &vao);
        glBindVertexArray(vao);   /* core profile requires one */
        glGenBuffers(1, &vbo);
        glBindBuffer(0x8892, vbo);
        glBufferData(0x8892, sizeof quad, quad, 0x88E4);
        glVertexAttribPointer(0, 4, 0x1406, 0, 16, 0);
        glEnableVertexAttribArray(0);

        glViewport(0, 0, W, H);
        glEnable(0x0BE2);                       /* BLEND */
        glBlendFunc(0x0302, 0x0303);            /* SRC_ALPHA, ONE_MINUS_SRC_ALPHA */
        glClearColor(0, 0, 0, 1);

        /* warm up */
        for (f = 0; f < 10; f++) {
            glClear(0x4000);
            for (i = 0; i < QUADS_PER_FRAME; i++) glDrawArrays(0x0004, 0, 6);
        }
        glFinish();

        t0 = now_s();
        for (f = 0; f < FRAMES; f++) {
            glClear(0x4000);
            for (i = 0; i < QUADS_PER_FRAME; i++) glDrawArrays(0x0004, 0, 6);
        }
        glFinish();
        t1 = now_s();

        if (glGetError()) fprintf(stderr, "warning: GL error 0x%x\n", glGetError());
        printf("\n%d frames of %d full-screen quads at %dx%d\n",
               FRAMES, QUADS_PER_FRAME, W, H);
        printf("  %.3f s total, %.3f ms/frame  ->  %.0f fps\n",
               t1 - t0, (t1 - t0) * 1000.0 / FRAMES, FRAMES / (t1 - t0));
        printf("  headroom vs 60 fps target: %.0fx\n", (FRAMES / (t1 - t0)) / 60.0);
    }
    return 0;
}
