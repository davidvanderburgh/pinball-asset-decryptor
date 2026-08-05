/* padvid.h - the video bridge's shared block, shared by the guest shim
 * (gstvid.c, ARM, inside the chroot), the host decoder (padvidhost.py, WSL)
 * and the renderer (padglhost.c, which reads finished frames straight out of
 * the ring). Same host-path/guest-path split as the GL ring and the keyboard.
 *
 * WHY A BRIDGE AT ALL: the guest has no software H.264 decoder. Of the 175
 * plugins in its gstreamer-0.10, the only one that decodes h264 is
 * libmfw_vpu.so, the i.MX6 hardware element, and there is no i.MX6 here. The
 * host has ffmpeg. So the host decodes and the guest is handed finished planes.
 *
 * VERSION 2: CHANNELS. Version 1 held exactly one stream, because Godzilla's
 * attract loop only ever showed one clip - until it crossfaded to the next
 * page, at which point the game had TWO pipelines alive at once and the two
 * requests fought over the single request slot. The loser's rewind saw the
 * ack generation jump past the one it was waiting for ("[vid] host did not
 * answer"), its pipeline identity was stolen by the newer pipeline_new, and
 * the game retried seek+play on it ~25 times a second for the rest of the run
 * (14,837 "Unable to set the pipeline to the playing state" errors in one
 * log). A channel per stream removes the fight: each guest-side stream owns
 * one channel, requests and rings included, and channels never share state.
 *
 * LAYOUT RULES, because three languages have to agree on this:
 *   - every field is u32 and little-endian on both sides
 *   - the header is a fixed PADVID_HDR bytes, frames start there
 *   - channel c's slots start at PADVID_HDR + c * SLOTS * SLOT_BYTES
 *   - nothing is added in the middle; append only, and bump PADVID_VERSION
 *
 * EACH CHANNEL'S RING IS SINGLE PRODUCER / SINGLE CONSUMER. The host only
 * ever advances write_idx, the guest only ever advances read_idx, and neither
 * writes the other's index. That is what makes it safe without a lock across
 * two processes that cannot share one.
 */
#ifndef PADVID_H
#define PADVID_H

#define PADVID_MAGIC   0x56444150u      /* 'PADV' */
#define PADVID_VERSION 2

/* Four concurrent streams. The most ever observed alive at once is two (the
 * attract crossfade); four leaves room for a game mode that layers more. */
#define PADVID_CHANNELS   4

/* 1360x768 I420 is 1566720 bytes. Four slots is 6 MB and about 130 ms of
 * buffering at 30 fps - enough to ride out a scheduling hiccup in an emulated
 * guest, small enough that a seek does not have to throw much away. */
#define PADVID_SLOTS      4
#define PADVID_MAX_W      1920
#define PADVID_MAX_H      1088
#define PADVID_SLOT_BYTES ((PADVID_MAX_W) * (PADVID_MAX_H) * 3 / 2)

#define PADVID_HDR        4096
#define PADVID_RING_BYTES ((unsigned)PADVID_CHANNELS * PADVID_SLOTS * PADVID_SLOT_BYTES)
#define PADVID_BYTES      (PADVID_HDR + PADVID_RING_BYTES)

#define PADVID_PATH_MAX   512

/* status */
#define PADVID_IDLE  0
#define PADVID_OK    1
#define PADVID_ERR   2

/* One stream. 13 u32 fields + the path = 564 bytes; four of these plus the
 * block header fit in the 4096-byte header page with room to spare. */
struct padvid_chan {
    /* request: the guest writes path[] then bumps req_gen. The host serves it
     * and copies req_gen into ack_gen. Generation counters rather than a flag
     * so a second request for the same file is still seen as new. */
    unsigned req_gen;
    unsigned ack_gen;
    unsigned status;            /* PADVID_* , valid once ack_gen == req_gen */

    unsigned width, height;
    unsigned nframes;
    unsigned fps_num, fps_den;
    unsigned frame_bytes;       /* width*height*3/2, what one slot holds */

    unsigned write_idx;         /* HOST only. frames produced, monotonic */
    unsigned read_idx;          /* GUEST only. frames consumed, monotonic */
    unsigned playing;           /* guest: 1 = keep decoding, 0 = stop */
    unsigned eos;               /* host: 1 = no more frames for this request */

    char path[PADVID_PATH_MAX]; /* guest-relative, e.g. ./assets/lcd/... */
};

struct padvid_shm {
    unsigned magic;
    unsigned version;
    unsigned host_alive;        /* host bumps this so the guest can tell */
    struct padvid_chan ch[PADVID_CHANNELS];
};

/* The header page must actually hold the header. A negative array size is the
 * portable static assert for a -nostdlib build. */
typedef char padvid_hdr_fits[(int)(PADVID_HDR - (int)sizeof(struct padvid_shm))];

#endif
