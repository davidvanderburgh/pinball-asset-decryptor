/* esprobe.c - can the host helper get a GLES context and the game's own
 * `#version 300 es` shaders, WITHOUT installing libgles2?
 *
 * If yes, the bridge can replay the game's shader source verbatim and there is
 * no translation layer to get wrong. If no, the helper must rewrite the four
 * fragment shaders into desktop GLSL, or libgles2 has to be installed.
 *
 *   gcc -O2 -o esprobe esprobe.c -l:libEGL.so.1
 */
#include <stdio.h>

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
extern void (*eglGetProcAddress(const char *))(void);
extern EGLint eglGetError(void);

int main(void)
{
    EGLint major, minor, n;
    EGLDisplay dpy;
    EGLConfig cfg;
    EGLContext ctx;
    EGLSurface surf;
    static const EGLint cfgattr[] = {
        0x3033, 0x0001,            /* SURFACE_TYPE, PBUFFER   */
        0x3040, 0x0040,            /* RENDERABLE_TYPE, ES3_BIT */
        0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8,
        0x3038 };
    static const EGLint pbattr[]  = { 0x3057, 16, 0x3056, 16, 0x3038 };
    static const EGLint ctxattr[] = { 0x3098, 3, 0x30FB, 0, 0x3038 };  /* ES 3.0 */

    const unsigned char *(*p_glGetString)(unsigned int);
    unsigned int (*p_glCreateShader)(unsigned int);
    void (*p_glShaderSource)(unsigned int, int, const char *const *, const int *);
    void (*p_glCompileShader)(unsigned int);
    void (*p_glGetShaderiv)(unsigned int, unsigned int, int *);
    void (*p_glGetShaderInfoLog)(unsigned int, int, int *, char *);

    /* the game's real fragment shader, unmodified */
    static const char *FS =
        "#version 300 es\n"
        "in highp vec2 TexCoords;\n"
        "out lowp vec4 color;\n"
        "uniform sampler2D image;\n"
        "uniform lowp vec4 spriteColor;\n"
        "void main(){ color = spriteColor * texture(image, TexCoords); }\n";

    dpy = eglGetDisplay((void *)0);
    if (!eglInitialize(dpy, &major, &minor)) { printf("eglInitialize failed\n"); return 1; }
    if (!eglBindAPI(0x30A0)) { printf("eglBindAPI(ES) failed 0x%x\n", eglGetError()); return 1; }
    if (!eglChooseConfig(dpy, cfgattr, &cfg, 1, &n) || n < 1) {
        printf("no ES3 config: 0x%x\n", eglGetError()); return 1;
    }
    surf = eglCreatePbufferSurface(dpy, cfg, pbattr);
    ctx  = eglCreateContext(dpy, cfg, 0, ctxattr);
    if (!ctx) { printf("eglCreateContext(ES3) failed 0x%x\n", eglGetError()); return 1; }
    if (!eglMakeCurrent(dpy, surf, surf, ctx)) {
        printf("eglMakeCurrent failed 0x%x\n", eglGetError()); return 1;
    }

    p_glGetString       = (const unsigned char *(*)(unsigned int))eglGetProcAddress("glGetString");
    p_glCreateShader    = (unsigned int (*)(unsigned int))eglGetProcAddress("glCreateShader");
    p_glShaderSource    = (void (*)(unsigned int, int, const char *const *, const int *))eglGetProcAddress("glShaderSource");
    p_glCompileShader   = (void (*)(unsigned int))eglGetProcAddress("glCompileShader");
    p_glGetShaderiv     = (void (*)(unsigned int, unsigned int, int *))eglGetProcAddress("glGetShaderiv");
    p_glGetShaderInfoLog= (void (*)(unsigned int, int, int *, char *))eglGetProcAddress("glGetShaderInfoLog");

    if (!p_glGetString || !p_glCreateShader) {
        printf("eglGetProcAddress did NOT return GLES entry points\n"
               "  -> libgles2 is required, or shaders must be translated\n");
        return 1;
    }
    printf("GLES context OK, entry points via eglGetProcAddress\n");
    printf("  GL_RENDERER : %s\n", p_glGetString(0x1F01));
    printf("  GL_VERSION  : %s\n", p_glGetString(0x1F02));
    printf("  GLSL        : %s\n", p_glGetString(0x8B8C));

    {
        int ok = 0;
        unsigned int s = p_glCreateShader(0x8B30);   /* FRAGMENT_SHADER */
        p_glShaderSource(s, 1, &FS, 0);
        p_glCompileShader(s);
        p_glGetShaderiv(s, 0x8B81, &ok);
        if (ok) printf("  the game's own `#version 300 es` shader COMPILES verbatim\n");
        else {
            char log[1024];
            p_glGetShaderInfoLog(s, sizeof log, 0, log);
            printf("  shader FAILED to compile:\n%s\n", log);
            return 1;
        }
    }
    return 0;
}
