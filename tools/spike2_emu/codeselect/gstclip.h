/* gstclip.h - a TEST CARD clip decoded by the machine's own video chain (Simon, 2026-11-22).
 *
 * A .padv (video.h) is JPEG frames decoded on the CPU: its colour is the app's
 * conversion, not the machine's.  A clip played the way the GAME plays it goes
 * through the same GStreamer 0.10 chain the game builds -
 *     filesrc ! qtdemux ! queue ! vpudec ! fakesink (handoff)
 * - so the i.MX6 VPU decodes it, exactly as in a game.  The card's libraries
 * are loaded at run time (dlopen), never linked: a card without them, or a
 * machine without a VPU, gets an error line on the test screen instead of a
 * menu that will not start.  In the emulator the rig's video bridge
 * (padgst.so: gststub.c + gstvid.c) answers the same calls from the PC's
 * decoder.
 *
 * Each decoded frame (I420, NV12 or YV12, whatever vpudec negotiated) is turned
 * into RGBA here, fitted down to the screen when it is bigger, and the newest
 * one is handed to the caller.  At the end the clip seeks back to the start. */
#ifndef CODESELECT_GSTCLIP_H
#define CODESELECT_GSTCLIP_H

#include "art.h"

struct gclip;

/* is *path* a clip for this player (by its name: .mp4 .mov .m4v)? */
int gclip_is_clip(const char *path);

/* Start playing *path*; NULL + err when GStreamer is not on this machine or
 * the clip does not start. */
struct gclip *gclip_open(const char *path, int max_w, int max_h, char *err, int errlen);

/* a frame newer than the last one returned, or NULL; *k counts frames shown */
const struct art_image *gclip_frame(struct gclip *g, long long now_ms, int *k);
const struct art_image *gclip_current(struct gclip *g);
int   gclip_loops(const struct gclip *g);
float gclip_fps(const struct gclip *g);
int   gclip_frames(const struct gclip *g);       /* frames in the clip, or 0 when unknown */
void  gclip_stats(const struct gclip *g, int *shown, int *dropped);
const char *gclip_error(const struct gclip *g);
void  gclip_close(struct gclip *g);

/* THE GRAPHICS CHIP'S WAY (the table, 2026-11-25): the frame as the decoder gave it
 * (copied out of its uncached memory), for a shader to convert.  gclip_want_rgba(g, 0)
 * stops the CPU conversion; gclip_yuv_take hands the newest frame over (1) and holds
 * it until gclip_yuv_done. */
struct gclip_yuv {
    const unsigned char *data;
    unsigned size, fourcc;          /* NV12, I420 or YV12 */
    int w, h;                       /* the picture */
    int stride, rows;               /* the Y plane's row length and rows (padded) */
    int ow, oh;                     /* the size it is shown at */
};
void  gclip_want_rgba(struct gclip *g, int on);
int   gclip_yuv_take(struct gclip *g, struct gclip_yuv *f);
void  gclip_yuv_done(struct gclip *g);

#endif
