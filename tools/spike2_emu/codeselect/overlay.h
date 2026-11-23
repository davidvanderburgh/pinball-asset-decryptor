/* overlay.h - a scene over a test clip: the LAYERED TEST (Simon, 2026-11-22/23).
 *
 * Simon: "do the overlay with the match video" - the game plays a clip and draws a
 * scene over it (Godzilla's Match: the clip, then MATCH and a digit zooming in).  A
 * test card shows the same: the clip through the machine's own decoder (gstclip.h)
 * or a .padv (video.h), and over it the scene's own frames, rendered on the PC by
 * PAD's scene renderer (pinball_decryptor/plugins/stern/layered_test.py).
 *
 * The file sits beside its clip with the same name: test3.mp4 -> test3.pado.
 *
 *   offset 0   "PADOVL01"
 *          8   u32 canvas width, u32 canvas height   (the scene's stage; centred on
 *                                                     the screen, as the clip is)
 *         16   u32 frame rate x 1000, u32 frames
 *         24   u32 pictures, u32 0
 *         32   u32 picture[frames]                    which picture frame k shows,
 *                                                     0xFFFFFFFF = nothing
 *              { i32 x, i32 y, u32 offset, u32 size } [pictures]
 *              the pictures: PNGs (RGBA, straight alpha), each cropped to what it
 *              draws and placed at x, y on the canvas
 *   all little-endian.  A scene holds still for most of its length, so the frames
 *   share pictures: Godzilla's Match is 221 frames and 13 pictures.
 *
 * WHICH FRAME is the clip's time since it last started, at the overlay's rate: the
 * machine's decoder hands over frames, not their numbers.  Past the last frame the
 * last one stays (the clip, looping, starts the overlay again).
 */
#ifndef CODESELECT_OVERLAY_H
#define CODESELECT_OVERLAY_H

#include "art.h"

#define OVL_MAGIC "PADOVL01"
#define OVL_HEADER 32
#define OVL_MAX_FRAMES 216000
#define OVL_MAX_PICTURES 65536
#define OVL_NONE 0xFFFFFFFFu

struct ovl;

/* Open a .pado: the whole file is read (it is small) and checked.  NULL + err when it
 * cannot be read, is not one, or its canvas is bigger than max_w x max_h. */
struct ovl *ovl_open(const char *path, int max_w, int max_h, char *err, int errlen);

/* the picture for `ms` after the clip started, decoded (the last one is kept, so a
 * still stretch costs nothing), and where it goes on the canvas; NULL = nothing then */
const struct art_image *ovl_at(struct ovl *o, long long ms, int *x, int *y);

int ovl_frames(const struct ovl *o);
float ovl_fps(const struct ovl *o);
int ovl_pictures(const struct ovl *o);
void ovl_canvas(const struct ovl *o, int *w, int *h);
/* a picture that would not decode, or "" */
const char *ovl_error(const struct ovl *o);

void ovl_close(struct ovl *o);

#endif
