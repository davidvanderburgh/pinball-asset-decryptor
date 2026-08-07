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
 * COILS TOO, since version 2. Same board, same frames, same reasoning - see
 * coildecode.py. A coil is an EVENT rather than a level, so it is published as
 * a wrapping fire COUNTER per (node, index): a reader flashes the marker when
 * the counter moves and cannot miss a pulse between two polls the way a
 * sampled on/off bit would. `lvl` carries the drive byte alongside it, because
 * a hold (a flipper held up) and a pulse (a slingshot) look identical in a
 * counter and different here.
 *
 * SINGLE WRITER. The guest writes, the host only reads. `gen` is bumped after
 * each update so a reader can tell it moved without diffing 3 KB.
 */
#ifndef PADLED_H
#define PADLED_H

#define PADLED_MAGIC   0x44454c50u      /* 'PLED' */
#define PADLED_VERSION 2

/* Node ids run to 14 and index to 95, so a flat [16][96] covers every board
 * with room to spare and needs no per-node base to get wrong. */
#define PADLED_NODES 16
#define PADLED_IDX   96
#define PADLED_COILS 16
#define PADLED_BYTES 4096

/* APPEND ONLY. A reader compiled against version 1 maps the same page and finds
 * every field it knows at the same offset, which is what lets the playfield
 * window and the shim be updated independently. Offsets, since a Python reader
 * has to hard-code them: val 20, coil 1556, lvl 1812, coil_gen 2068,
 * coil_decoded 2072. */
struct padled_shm {
    unsigned magic;
    unsigned version;
    unsigned gen;                 /* bumped after every decoded write        */
    unsigned decoded;             /* total LED writes decoded, ever          */
    unsigned skipped;             /* frames that looked indexed but were not */
    unsigned char val[PADLED_NODES][PADLED_IDX];
    unsigned char coil[PADLED_NODES][PADLED_COILS];  /* wrapping fire count  */
    unsigned char lvl[PADLED_NODES][PADLED_COILS];   /* last drive byte      */
    unsigned coil_gen;            /* bumped after every decoded coil frame   */
    unsigned coil_decoded;        /* total coil fires decoded, ever          */
    /* VERSION 3: the FADE layer - `cmd a2` blen=6, the animation half of the
     * light show. One entry per command, a ring so a slow reader loses old
     * pulses rather than blocking the shim. Offsets for a Python reader:
     * fade_head 2076, entries 2080, entry stride 12, FADE_RING 96.
     *
     * WHAT AN ENTRY MEANS (established 2026-08-06/07 from the skip captures,
     * see REMAINING item 1d): a ONE-SHOT PULSE ENVELOPE over a lamp RANGE -
     * go FROM -> TO using the rate slot for that direction, then return to
     * FROM using the other slot; 0 = instantly. The pulses are an OVERLAY on
     * the base picture (the indexed writes), which is why val[] is NOT
     * touched here: the base layer owns it, and a pulse ends where the base
     * says. The RATE UNIT is not established - the reader scales it.
     * NOT established either: whether a wide range pulses together or as a
     * travelling sweep. Rendered together until an LED Tests run says. */
    unsigned fade_head;           /* entries written, ever; ring index = %96 */
    struct padled_fade {
        unsigned ms;              /* guest CLOCK_MONOTONIC ms at decode      */
        unsigned char node, start, end;      /* raw indices, inclusive      */
        unsigned char from, to;              /* levels                      */
        unsigned char rise, fall;            /* rate per direction, 0=snap  */
        unsigned char pad;
    } fade[96];
};

#endif
