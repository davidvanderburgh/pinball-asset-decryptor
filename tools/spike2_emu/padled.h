/* padled.h - live LED state, published by the shim, read by the playfield window.
 *
 * Same host-path/guest-path split as padsw.h, padvid.h and the GL ring: a file
 * under spike2root/dump/ that the chrooted guest opens by its /dump path and a
 * native process opens by its WSL path.
 *
 * WHY THE SHIM AND NOT A LOG READER. The shim already serves every node bus
 * frame, so it sees the LED writes for free. The alternative - tailing a
 * PAD_NB_LOG capture - needs logging turned up to 400000 lines, which
 * quadruples the boot and is documented as invalidating any timing measurement.
 * Publishing 3 KB of state is cheaper than writing megabytes of hex.
 *
 * WHAT IS IN IT. Only the INSERT boards (nodes 1, 8 and 9), whose per-LED writes
 * are decoded - see leddecode.py for the three frame shapes and, more
 * importantly, for why the same command byte on nodes 7/12/14 must NOT be run
 * through the same decoder. The strip boards are left at zero, and `decoded`
 * says how many writes have actually landed so a reader can tell "off" from
 * "no data". A dark playfield with decoded == 0 means the decoder never fired.
 *
 * SINGLE WRITER. The guest writes, the host only reads. `gen` is bumped after
 * each update so a reader can tell it moved without diffing 3 KB.
 */
#ifndef PADLED_H
#define PADLED_H

#define PADLED_MAGIC   0x44454c50u      /* 'PLED' */
#define PADLED_VERSION 1

/* Node ids run to 14 and index to 95, so a flat [16][96] covers every board
 * with room to spare and needs no per-node base to get wrong. */
#define PADLED_NODES 16
#define PADLED_IDX   96
#define PADLED_BYTES 4096

struct padled_shm {
    unsigned magic;
    unsigned version;
    unsigned gen;                 /* bumped after every decoded write        */
    unsigned decoded;             /* total LED writes decoded, ever          */
    unsigned skipped;             /* frames that looked indexed but were not */
    unsigned char val[PADLED_NODES][PADLED_IDX];
};

#endif
