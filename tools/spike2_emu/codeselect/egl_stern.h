/* egl_stern.h - Stern's own EGL/GLES2 bring-up (boot_display's
 * glWindow::create_window, which the game shares), driven through whatever
 * libEGL.so.1/libGLESv2.so.2 the rootfs carries: Vivante's on the machine,
 * the rig's GL bridge shims in the emulator. The menu canvas is presented as
 * one full-screen textured quad; after the first upload only the changed
 * sub-rectangle is sent (glTexSubImage2D of a packed rect).
 *
 * No Khronos headers exist on the box; every EGL/GL/fb prototype is declared
 * by hand in egl_stern.c.
 */
#ifndef CODESELECT_EGL_STERN_H
#define CODESELECT_EGL_STERN_H

struct egl_stern {
    void *fbd, *dpy, *cfg, *win, *surf, *ctx;
    int w, h;                 /* fbGetDisplayGeometry's answer */
    unsigned vao, vbo, tex, prog;
    int tex_w, tex_h;
    int frames;
    long long uploaded;       /* bytes sent through glTexSubImage2D (for the log) */
    int up;
    /* THE VIDEO LAYER (egl_stern_video): a test card clip's YUV planes, converted by
     * a shader and drawn under the menu canvas, which is see-through there */
    unsigned yprog, yvao, yvbo, ytex[3];
    int y_on, y_nv12, y_stride, y_rows;
    int y_ok;                 /* 1 made, -1 refused (the CPU draws the clip instead) */
};

/* Bring the display up. Retries the whole sequence `retries` times, `retry_ms`
 * apart (on hardware boot_display may still be releasing the display).
 * 0 ok, -1 failed. */
int  egl_stern_init(struct egl_stern *e, int retries, int retry_ms);

/* Create the one RGBA8 texture of w x h from px (glTexImage2D, once). */
int  egl_stern_texture(struct egl_stern *e, int w, int h, const unsigned char *px);

/* One frame: clear, (packed ? glTexSubImage2D of the w x h rect at x, y from
 * the tightly packed RGBA rows : nothing), draw the quad, swap. Call every
 * frame; pass packed only when the canvas changed (gfx_pack). */
void egl_stern_frame(struct egl_stern *e, const unsigned char *packed, int x, int y, int w, int h);

/* THE VIDEO LAYER (the table, 2026-11-25: "only at 1.4FPS" with the CPU converting
 * every frame): one frame of a clip as the decoder gave it - NV12 (Y, then UV pairs)
 * or I420/YV12 (Y, U, V) - with planes `stride` bytes x `rows` rows, a `w` x `h`
 * picture, drawn at x, y, dw x dh of the screen (canvas coordinates; `invert` is the
 * canvas's 180-degree turn) under the canvas from the next egl_stern_frame on.
 * data NULL takes the layer away.  0 shown; -1 this back end or frame cannot (the
 * caller converts on the CPU as before).  The game does the same with Vivante's
 * glTexDirectVIV; plain textures and a shader also run on the emulator's bridge. */
int  egl_stern_video(struct egl_stern *e, const unsigned char *data, unsigned fourcc, int w, int h,
                     int stride, int rows, int x, int y, int dw, int dh, int invert);

/* Leave default-looking GL state for the next client - unbind, program 0,
 * blend off, viewport reset; NO clear and NO swap, so the LOADING frame just
 * shown stays on the LCD until the game draws - then eglMakeCurrent(dpy,0,0,0)
 * / eglTerminate / eglReleaseThread. */
void egl_stern_close(struct egl_stern *e);

#endif
