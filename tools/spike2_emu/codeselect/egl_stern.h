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

/* Leave default-looking GL state for the next client - unbind, program 0,
 * blend off, viewport reset; NO clear and NO swap, so the LOADING frame just
 * shown stays on the LCD until the game draws - then eglMakeCurrent(dpy,0,0,0)
 * / eglTerminate / eglReleaseThread. */
void egl_stern_close(struct egl_stern *e);

#endif
