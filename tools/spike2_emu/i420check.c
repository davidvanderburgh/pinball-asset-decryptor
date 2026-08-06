/* i420check.c - run padglhost's REAL I420->RGBA converter on a file.
 *
 *     i420check <in.i420> <w> <h> <out.rgba>
 *
 * Built by vidcheck.py, which pulls the input frame out of the live
 * padvidhost.py ring and then diffs this program's output against ffmpeg's own
 * RGBA decode of the same frame. That reference is the whole point: a metric
 * that scores the converter's output on its own would be scoring the CLIP.
 *
 * The converter comes from i420.h, which padglhost.c includes as well, so this
 * is the shipping code and not a copy of it.
 *
 * w and h are given SEPARATELY from the file so that a deliberate mismatch can
 * be rendered - "what does a 520x294 frame look like when it is uploaded as
 * 1360x768" is the question item 6 is really asking, and the answer has to be
 * looked at, not reasoned about. Reads short and pads with zero rather than
 * refusing, because that is exactly what the shipping path does when the ring
 * holds less than w*h*3/2 bytes.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "i420.h"

int main(int argc, char **argv)
{
    unsigned w, h;
    unsigned long need, got;
    unsigned char *in;
    const unsigned char *out;
    FILE *f;

    if (argc != 5) {
        fprintf(stderr, "usage: i420check <in.i420> <w> <h> <out.rgba>\n");
        return 2;
    }
    w = (unsigned)strtoul(argv[2], 0, 10);
    h = (unsigned)strtoul(argv[3], 0, 10);
    if (!w || !h) { fprintf(stderr, "bad size\n"); return 2; }
    need = (unsigned long)w * h * 3 / 2;

    in = calloc(1, need);
    if (!in) { fprintf(stderr, "out of memory\n"); return 2; }
    f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    got = fread(in, 1, need, f);
    fclose(f);
    if (got < need)
        fprintf(stderr, "i420check: input is %lu bytes, %ux%u wants %lu - "
                "zero-padded (this is what a size mismatch does)\n",
                got, w, h, need);

    out = i420_to_rgba(in, w, h);
    if (!out) { fprintf(stderr, "conversion failed\n"); return 2; }

    f = fopen(argv[4], "wb");
    if (!f) { perror(argv[4]); return 2; }
    if (fwrite(out, 1, (unsigned long)w * h * 4, f) != (unsigned long)w * h * 4) {
        perror("write"); fclose(f); return 2;
    }
    fclose(f);
    return 0;
}
