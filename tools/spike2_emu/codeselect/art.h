/* art.h - the menu's pictures: PNG stills and animated GIFs, decoded with the
 * vendored stb_image (third_party/stb_image.h, PNG + GIF only) and box-
 * downscaled ONCE into the card's art panel so every later draw is a plain
 * blit and RAM is bounded by the panel size, not the file.
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
    int n;                    /* frames decoded so far */
    int w, h;                 /* fitted frame size (every frame) */
    int done;                 /* 1 once the whole file is decoded (or decoding failed) */
    struct art_image *fr;     /* n frames */
    int *delay_ms;            /* n delays; 100 when the GIF said 0 */
    void *dec;                /* incremental decoder state while !done */
    char err[200];            /* why decoding stopped early, or "" */
};

/* Decode a PNG and fit it into max_w x max_h (aspect kept, never upscaled).
 * NULL + err on failure. */
struct art_image *art_load_png(const char *path, int max_w, int max_h, char *err, int errlen);
void art_image_free(struct art_image *im);

/* Open an animated GIF: reads the file and prepares the decoder; frames are
 * decoded ONE PER art_anim_step() call so the caller can spread the work
 * across loop iterations. NULL + err when the file cannot be read or is not a
 * GIF. Frames are fitted like art_load_png; delays come from the GIF. */
struct art_anim *art_anim_open(const char *path, int max_w, int max_h, int max_frames,
                               char *err, int errlen);
/* Decode the next frame. 1 = a frame was added, 0 = nothing more (done). */
int  art_anim_step(struct art_anim *a);
void art_anim_free(struct art_anim *a);

#endif
