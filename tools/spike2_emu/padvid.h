/* padvid.h - the video bridge's shared block, shared by the guest shim
 * (gststub.c, ARM, inside the chroot) and the host decoder (padvidhost.py,
 * x86-64, in WSL). Same host-path/guest-path split as the GL ring and the
 * keyboard.
 *
 * WHY A BRIDGE AT ALL: the guest has no software H.264 decoder. Of the 175
 * plugins in its gstreamer-0.10, the only one that decodes h264 is
 * libmfw_vpu.so, the i.MX6 hardware element, and there is no i.MX6 here. The
 * host has ffmpeg. So the host decodes and the guest is handed finished planes.
 *
 * LAYOUT RULES, because two languages have to agree on this:
 *   - every field is u32 and little-endian on both sides
 *   - the header is a fixed PADVID_HDR bytes, frames start there
 *   - nothing is added in the middle; append only, and bump PADVID_VERSION
 *
 * THE RING IS SINGLE PRODUCER / SINGLE CONSUMER. The host only ever advances
 * write_idx, the guest only ever advances read_idx, and neither writes the
 * other's index. That is what makes it safe without a lock across two
 * processes that cannot share one.
 */
#ifndef PADVID_H
#define PADVID_H

#define PADVID_MAGIC   0x56444150u      /* 'PADV' */
#define PADVID_VERSION 1

/* 1360x768 I420 is 1566720 bytes. Four slots is 6 MB and about 130 ms of
 * buffering at 30 fps - enough to ride out a scheduling hiccup in an emulated
 * guest, small enough that a seek does not have to throw much away. */
#define PADVID_SLOTS      4
#define PADVID_MAX_W      1920
#define PADVID_MAX_H      1088
#define PADVID_SLOT_BYTES ((PADVID_MAX_W) * (PADVID_MAX_H) * 3 / 2)

#define PADVID_HDR        4096
#define PADVID_BYTES      (PADVID_HDR + (unsigned)PADVID_SLOTS * PADVID_SLOT_BYTES)

#define PADVID_PATH_MAX   512

/* status */
#define PADVID_IDLE  0
#define PADVID_OK    1
#define PADVID_ERR   2

struct padvid_shm {
    unsigned magic;
    unsigned version;

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

    unsigned host_alive;        /* host bumps this so the guest can tell */

    char path[PADVID_PATH_MAX]; /* guest-relative, e.g. ./assets/lcd/... */
};

#endif
