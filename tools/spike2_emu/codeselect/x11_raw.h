/* x11_raw.h - a full-screen window on an X server without libX11 (the
 * Dutch Pinball build, PAD-853; see x11_raw.c). */
#ifndef CODESELECT_X11_RAW_H
#define CODESELECT_X11_RAW_H

/* connect to $DISPLAY, map a black override-redirect window the root's size;
 * *w x *h is that size.  0 ok, -1 failed (logged). */
int  x11raw_open(int *w, int *h);
/* rows y0 .. y0+rows-1 of a w x h 0x00RRGGBB picture (stride bytes a row)
 * onto the window.  0 ok, -1 the connection is gone. */
int  x11raw_put(const unsigned char *px, int stride, int y0, int rows);
/* close the connection: the window goes with it */
void x11raw_close(void);

#endif
