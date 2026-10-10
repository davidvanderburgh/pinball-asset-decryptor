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
 * WHAT IS IN IT. Two decoders, and they are gated very differently.
 *
 * The GODZILLA-generation one reads the three indexed shapes and is restricted
 * to the INSERT boards (nodes 1, 8 and 9) - see leddecode.py for why the same
 * command byte on nodes 7/12/14 must NOT be run through it. Those shapes are
 * loose enough that the node gate is the only thing keeping them honest.
 *
 * The SWELF-generation one (led_wide_publish, added for batman) reads the
 * bit-packed family every board of that generation speaks, and it runs on ANY
 * node - because it does not need a node gate. Its block walk has to land
 * EXACTLY on the end of the body or the frame is refused, which is a test a
 * mis-parse fails by itself. That self-check is what makes nodes 10 and 13
 * safe to read when nothing else was.
 *
 * `decoded` says how many writes have actually landed so a reader can tell
 * "off" from "no data". A dark playfield with decoded == 0 means the decoder
 * never fired - and one with decoded in the hundreds of thousands and every
 * val[] byte still zero means the frames are arriving and carrying black,
 * which is its own fault with its own cause (see NB_HWID_DEFAULT in hwshim.c).
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
#define PADLED_VERSION 6

/* Node ids run to 14 and index to 95, so a flat [16][96] covers every board
 * with room to spare and needs no per-node base to get wrong. */
#define PADLED_NODES 16
#define PADLED_IDX   96
#define PADLED_COILS 16
/* VERSION 4's `seen` plane pushed the struct past one page, and VERSION 6's
 * `hi` plane past two. Four, now - the mapping is created by watch.sh from
 * this constant, and the shim takes its size from the file, so an older
 * watch.sh simply gets the version its file has room for. */
#define PADLED_BYTES 16384

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
    /* VERSION 4: ADDRESSED, WHICH IS NOT THE SAME QUESTION AS LIT - and until
     * now this block could only answer the second one. Offsets for a Python
     * reader: seen 3232, wide_decoded 4768, wide_skipped 4772.
     *
     * A reader builds its roster from val[] going non-zero, so a lamp only
     * earns a cell by being lit at a moment somebody was looking. That was
     * fine while the only decoded frames were the ones that carry a level.
     * The swelf generation (batman) breaks it in two ways at once: half its
     * lamp commands address a set of LEDs and carry NO level byte at all
     * (cmd bits 0-1 == 0 or 1 - see led_wide_publish), and the rest of its
     * boards were simply never decoded, so nodes 10 and 13 did not exist as
     * far as the window was concerned.
     *
     * So: one bit per (node, index) the wire has ADDRESSED by any frame this
     * shim could parse, level or no level. It is the honest membership
     * answer - "this lamp exists and the game talks to it" - and it is
     * deliberately SEPARATE from val[], because merging them would mean
     * inventing a brightness for a frame that never carried one. That
     * invention is the exact failure this file keeps having to undo.
     *
     * STICKY, never cleared: a roster that shrinks while you watch it is
     * unreadable, and the reader's own roster is sticky for the same reason. */
    unsigned char seen[PADLED_NODES][PADLED_IDX];
    unsigned wide_decoded;        /* wide-dialect frames parsed exactly     */
    unsigned wide_skipped;        /* wide-dialect frames that did not close */
    /* VERSION 5 (PAD-381): what each coil is DRIVEN to, and until when.
     * `coil`/`lvl` above say a coil was addressed; these say whether it is
     * still on, which is the question a held magnet asks. Offsets for a Python
     * reader: drive_t0 4776, drive_tps 4780, drive_until 4784,
     * drive_pulse_t 5808, drive_hold_t 6320, drive_pulse_pwr 6832,
     * drive_hold_pwr 7088, drive_fires 7344, drive_offs 7348,
     * drive_rule_fires 7352.
     *
     * The frame and every field are named from the game's own serialiser -
     * coil_drive_decode() in hwshim.c has the addresses. Times are in BOARD
     * TICKS as sent; ms = ticks * 1000 / drive_tps (the tick rate the rig's
     * boards claim). drive_until is the guest pad_ms() at which the last
     * command's pulse + hold run out, 0 once an OFF (cmd 4d) lands. A coil is
     * ON while drive_until > now, where now = the reader's CLOCK_MONOTONIC ms
     * minus drive_t0. That the board stops there is the GAME's reading (it
     * counts the coil busy for exactly pulse + hold), not a measurement of a
     * board. */
    unsigned drive_t0;            /* pad_ms()'s CLOCK_MONOTONIC origin, ms  */
    unsigned drive_tps;           /* board ticks per second, as claimed     */
    unsigned drive_until[PADLED_NODES][PADLED_COILS];
    unsigned short drive_pulse_t[PADLED_NODES][PADLED_COILS];
    unsigned short drive_hold_t[PADLED_NODES][PADLED_COILS];
    unsigned char drive_pulse_pwr[PADLED_NODES][PADLED_COILS];
    unsigned char drive_hold_pwr[PADLED_NODES][PADLED_COILS];
    unsigned drive_fires;         /* 14-byte cmd 40 commands, ever          */
    unsigned drive_offs;          /* cmd 4d, ever                           */
    unsigned drive_rule_fires;    /* the short cmd 40 (fire by rule), ever  */
    /* VERSION 6 (PAD-500): A STRIP BOARD'S CHANNELS PAST ITS FIRST 96. A board
     * with more lamps than val[] has room for takes them in banks of 96 (the
     * bank form, item 165), and until this plane every bank past the first was
     * walked, counted and published nowhere - the back three quarters of a
     * topper, and of the cabinet's expressive-lighting blades (288 channels on
     * node 2), never lit in any reader. hi[node][(bank - 1) * 96 + index] is
     * channel 96 * bank + index of that board, banks 1 to 4, so channels 96 to
     * 479. Levels only, as the frame carried them: no `seen` twin, and the
     * counters above are untouched, so nothing that judges a run (the light
     * show announcer, `decoded`) reads these frames any differently than it
     * did. Offset for a Python reader: hi 7356. */
    unsigned char hi[PADLED_NODES][4 * PADLED_IDX];
};

#endif
