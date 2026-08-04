/* padsw.h - the keyboard -> switch channel, shared by the host and the guest.
 *
 * The two halves of this rig are different architectures in different address
 * spaces: padglhost is a native x86-64 process that owns the X11 window (and so
 * is the only thing that can see a key press), while the switches themselves
 * are filled in by hwshim.so, an ARM library inside the emulated game. The GL
 * ring already proves the pattern - a file under spike2root/dump/ that the host
 * opens by its WSL path and the chrooted guest opens by its /dump path - so the
 * switch channel is the same trick with a much smaller payload.
 *
 * There is deliberately no locking. The host writes bytes and then bumps `gen`;
 * the guest reads `gen`, reads the bytes, and re-reads `gen`. A torn read costs
 * one frame of a switch being wrong, which is far cheaper than any of the
 * alternatives and is indistinguishable from ordinary switch bounce.
 */
#ifndef PADSW_H
#define PADSW_H

#define PADSW_MAGIC   0x53444150u        /* 'PADS' little-endian */
#define PADSW_MAX_ID  256
#define PADSW_BYTES   4096

struct padsw_shm {
    unsigned magic;
    unsigned gen;                        /* bumped after every change */
    unsigned char held[PADSW_MAX_ID];    /* 1 = this switch id is held ACTIVE */
};

#endif
