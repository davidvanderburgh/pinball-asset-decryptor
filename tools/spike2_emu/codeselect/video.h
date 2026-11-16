/* video.h - the TEST CARD's video player (PAD-1279).
 *
 * A test video is played whole, at its own frame rate and in full colour - a
 * GIF (art.h) has 256 colours, which is no use for judging a colour profile,
 * and a menu clip stops at 5 s.  The machine's only H.264 decoder is the
 * i.MX6 VPU behind the game's GStreamer 0.10, so the app writes a test video
 * as a .padv file instead: every frame a baseline JPEG (4:4:4, so the colour
 * is not halved), decoded here by stb_image on every CPU core at once, ahead
 * of the clock.
 *
 *   offset 0   "PADVJPG1"
 *          8   u32 width, u32 height        (every frame; at most the screen)
 *         16   u32 frame rate x 1000, u32 frames
 *         24   u32 0, u32 0                 (reserved)
 *         32   u32 offset[frames + 1]       frame k = bytes offset[k]..offset[k+1]
 *   all little-endian.  The sound, if the video had any, is a WAV of the same
 *   name beside it (<name>.wav), started with frame 0.
 *
 * PLAYBACK KEEPS TO THE CLOCK: frame k is due k * 1000 / fps ms after the
 * start.  The decoders take the frames in turn; one that finds its frame
 * already past due skips it without decoding, and the caller is handed the
 * newest decoded frame that is due - so a machine too slow for the clip
 * drops frames and stays in time, and vid_stats says how many, for the
 * caption.  At the end the clip starts again (vid_loops counts it, so the
 * caller can restart the sound).
 */
#ifndef CODESELECT_VIDEO_H
#define CODESELECT_VIDEO_H

#include "art.h"

#define VID_MAGIC "PADVJPG1"
#define VID_HEADER 32
#define VID_MAX_FRAMES 216000          /* two hours at 30 fps */

struct vid;

/* Open a .padv: read and check the header and index, start the decoders.
 * NULL + err when the file cannot be read, is not a .padv, its frames are
 * bigger than max_w x max_h, or its index is broken. */
struct vid *vid_open(const char *path, int max_w, int max_h, long long now_ms,
                     char *err, int errlen);

/* The frame due now: a frame newer than the one last returned, or NULL when
 * nothing newer is decoded yet (keep showing the last).  `*k` is the frame's
 * number in the file. */
const struct art_image *vid_frame(struct vid *v, long long now_ms, int *k);

/* the frame handed out last (still valid until the next vid_frame or
 * vid_restart), or NULL before the first */
const struct art_image *vid_current(struct vid *v);

/* back to frame 0, now */
void vid_restart(struct vid *v, long long now_ms);

int   vid_frames(const struct vid *v);
float vid_fps(const struct vid *v);
int   vid_loops(const struct vid *v);       /* times it has started again */
/* since the last start: frames shown and frames skipped (late) */
void  vid_stats(const struct vid *v, int *shown, int *dropped);
/* decoder threads, for the log */
int   vid_threads(const struct vid *v);
/* the decode error that stopped a frame, or "" */
const char *vid_error(const struct vid *v);

void vid_close(struct vid *v);

#endif
