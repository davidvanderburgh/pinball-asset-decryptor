/* art.h - the menu's pictures: PNG stills and animated GIFs, decoded with the
 * vendored stb_image (third_party/stb_image.h, PNG + GIF only) and box-
 * downscaled ONCE into the card's art panel so every later draw is a plain
 * blit and RAM is bounded by the panel size, not the file.
 *
 * An animation is decoded ON DEMAND: one frame lives in memory (plus frame 0,
 * kept as the still), and a tick costs one frame's LZW decode.  So a 5 s /
 * 30 fps loop (150 frames, 10 MB on the card) costs the selector no more RAM
 * than a 4-frame test GIF did when every frame was kept - two panels' worth
 * - and the menu is up after ONE frame, not after the whole file.
 *
 * Every failure is reported through err and is NON-FATAL for the caller: a
 * card without a picture still boots.
 */
#ifndef CODESELECT_ART_H
#define CODESELECT_ART_H

struct art_image {
    int w, h;
    unsigned char *rgba;      /* w*h*4, tightly packed */
};

struct art_anim {
    int n;                    /* frames in the file (counted at open, at most the cap
                                 asked for); lowered when decoding stops early */
    int w, h;                 /* fitted frame size (every frame) */
    int *delay_ms;            /* n delays; 100 when the GIF said 0, clamped 20 ms..10 s */
    float period_ms;          /* the loop's frame period when its delays are (near)
                                 uniform - a constant-rate clip, whose centisecond
                                 delays alternate 30/40 for 33.3 - else 0: tick on
                                 delay_ms[] */
    int cur;                  /* the frame `frame` holds (-1: none) */
    struct art_image frame;   /* the frame decoded last - the one being shown */
    struct art_image first;   /* frame 0, kept: the still of a card that is not highlighted */
    int decodes;              /* frames decoded so far, all told, and... */
    long long decode_us;      /* ...the time they took (for the log) */
    void *dec;                /* the file bytes + stb's state */
    char err[200];            /* why decoding stopped early, or "" */
    int err_said;             /* the caller has logged err */
};

/* Decode a PNG and fit it into max_w x max_h (aspect kept, never upscaled).
 * NULL + err on failure. */
struct art_image *art_load_png(const char *path, int max_w, int max_h, char *err, int errlen);
void art_image_free(struct art_image *im);

/* Open an animated GIF: reads the file, counts its frames and reads their
 * delays (a walk of the block stream - no decoding), then decodes frame 0.
 * NULL + err when the file cannot be read, is not a GIF, has no frames or
 * its first frame does not decode.  Frames are fitted like art_load_png;
 * at most max_frames are counted (the rest of the file is never read). */
struct art_anim *art_anim_open(const char *path, int max_w, int max_h, int max_frames,
                               char *err, int errlen);
/* Frame k (wrapped to n), DECODED ON DEMAND: the frame after the current one
 * costs one decode, an earlier one a rewind and the decodes up to it.  Never
 * NULL for an opened animation: when the file holds fewer frames than were
 * counted, n is lowered, err says so, and the last frame there is comes
 * back. */
const struct art_image *art_anim_frame(struct art_anim *a, int k);
/* Frame 0 without touching the decoder: what a card shows while another is
 * highlighted. */
const struct art_image *art_anim_still(const struct art_anim *a);
void art_anim_free(struct art_anim *a);

#endif
