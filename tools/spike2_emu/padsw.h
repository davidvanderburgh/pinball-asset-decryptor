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

    /* ---- ONE-SHOT TAP, measured in SPI TRANSFERS rather than milliseconds ----
     *
     * A held cabinet switch AUTO-REPEATS in the game's menus, and the number of
     * repeats depends on how many SPI transfers happen to land inside the hold.
     * That makes a wall-clock press a lottery: measured on the Main Menu, 120 ms
     * and 200 ms moved the cursor 0 rows, 250 ms moved 1 or 2, and 300 ms moved
     * 3. Two "identical" sequences landing on different screens is this, and it
     * is why the handoff's menu recipes never quite reproduce.
     *
     * So do not express a tap in time at all. The guest serves the cabinet word
     * to the game one transfer at a time, and it can simply report the switch
     * made for exactly `tap_reads` of them and then stop - which is the same
     * count on every run, on any host, at any emulation speed.
     *
     * `tap_reads` is a knob rather than a constant because "one transfer" is our
     * unit, not the game's: it debounces over some number of reads of its own,
     * and that number is its business to have and ours to measure.
     *
     * THE SINGLE-WRITER RULE STILL HOLDS. The host writes these and bumps
     * tap_gen; the guest only ever READS them, and remembers separately, in its
     * own memory, which generation it has already served. Nothing here is
     * written from both sides.
     */
    unsigned tap_gen;                    /* host bumps to request a tap        */
    unsigned tap_id;                     /* which switch id                    */
    unsigned tap_reads;                  /* transfers to hold it; 0 means 1    */
};

#endif
