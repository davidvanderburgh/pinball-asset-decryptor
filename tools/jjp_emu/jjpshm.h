/* jjpshm.h - the one definition of the shared block between the hardware shim
 * and whatever is driving it (a UI, a test script, the GUI panel).
 *
 * Both sides include THIS file.  The Spike 2 rig's hardest-won rule is that two
 * places must never define the same fact; the Python side reads the layout from
 * here rather than restating it (see jjpsw.py, which parses these constants).
 */

#ifndef JJPSHM_H
#define JJPSHM_H

#define JJP_SHM_DEFAULT_NAME "/jjp_switches"
/* "JJP3".  Bumped whenever the layout changes, so a stale block from an older
 * build REINITIALISES instead of being read at the wrong offsets:
 *   JJP1 -> JJP2  the IN region grew from the 16-byte matrix to the whole frame
 *   JJP2 -> JJP3  per-OUT-bit rising-edge counters (out_rise), and the direct
 *                 region now idles at 0xff rather than 0 (polarity, below)
 */
#define JJP_SHM_MAGIC   0x4a4a5033u          /* "JJP3" */
#define JJP_SHM_VERSION 3

/* Board ids.  Order is ours, not JJP's - it only indexes our own out[] rows. */
enum {
    JJP_BOARD_IO = 0,
    JJP_BOARD_LED,
    JJP_BOARD_ACC,
    JJP_BOARD_CAB,
    JJP_BOARD_TOP,
    JJP_BOARD_TOP2,
    JJP_BOARD_LILY,
    JJP_BOARD_STEP,
    JJP_BOARD_COUNT
};

/* The IN frame is 64 bytes and the game reads switches from ALL of it, not just
 * the playfield matrix.  Measured from the live Switch objects (swdump.py):
 *
 *     bytes  0..3   direct / cabinet switches - start, flippers, coins, the
 *                   coin-door menu buttons, slam/plumb tilt (dswitch_*)
 *     bytes  4..19  the 128-switch playfield matrix (switch_*), LSB first,
 *                   switch_NNN -> byte 4 + (N-1)/8, bit 1 << ((N-1)%8).
 *                   DERIVED AND VERIFIED - re-checked on every swdump.py run.
 *     bytes 20..36  stepper / topper switches (stepswit*, tswitch_*)
 *
 * So the driver hands the game one whole frame (in_frame below) rather than
 * only the matrix.  Filling only 4..19 is why start/flippers/coins were dead:
 * the game read bytes 0..3 as permanently open.
 */
#define JJP_MATRIX_FIRST_BYTE 4
#define JJP_MATRIX_BYTES      16
#define JJP_MATRIX_SWITCHES   128
#define JJP_DIRECT_FIRST_BYTE 0
#define JJP_DIRECT_BYTES      4
#define JJP_FRAME_LEN         64

/* THE FRAME IS MIXED POLARITY, AND THE SPLIT IS EXACTLY THE REGIONS ABOVE.
 *
 * Measured 2026-08-20 against the game's OWN Switch objects (offset 62 is the
 * game's live view; polarity.py drove the frame and read all 296 of them back):
 *
 *     bytes  0..3   direct / cabinet   ACTIVE LOW   32 of 32   bit CLEAR = closed
 *     bytes  4..19  playfield matrix   ACTIVE HIGH  128 of 128 bit SET   = closed
 *     bytes 20..36  stepper / topper   ACTIVE HIGH  136 of 136 bit SET   = closed
 *
 * That is ordinary hardware: the cabinet buttons are pull-ups shorted to ground
 * when pressed, while the matrix is scanned active-high.
 *
 * SO AN ALL-ZERO FRAME IS NOT AN IDLE FRAME.  With bytes 0..3 zeroed the game
 * reads every cabinet switch as CLOSED - both flippers held, all four menu
 * buttons held, five coin switches shorted, and the plumb-bob tilt made.  A
 * machine tilted with Start already down has no press edge left to give, which
 * is why the Start key did nothing until this was measured.  The block must
 * therefore come up at JJP_DIRECT_IDLE, not at zero.
 *
 * (An earlier note in this file claimed the whole frame was active high, on the
 * strength of an experiment that drove 0xff into bytes 0..3 and opened the coin
 * door.  That experiment was right and its READING was backwards: 0xff is every
 * cabinet switch OPEN, door included.)
 */
#define JJP_DIRECT_IDLE       0xff

struct jjp_shm {
    unsigned int magic;
    unsigned int version;
    unsigned int game_pid;

    /* Driver -> game.  The WHOLE 64-byte IN frame, in the game's own polarity
     * per region (see JJP_DIRECT_IDLE above - it is NOT "set = closed"
     * everywhere).  Written by the UI, copied verbatim into every read() of the
     * IO board (and the CAB board, since which one carries a given cabinet
     * switch is not known and serving both costs nothing).  Addressed by
     * absolute frame byte/bit, so a switch anywhere in the frame - direct,
     * matrix or mech - has a route. */
    volatile unsigned char in_frame[JJP_FRAME_LEN];

    /* Game -> driver.  Last OUT frame per board: coil drives, lamp pages. */
    volatile unsigned char out[JJP_BOARD_COUNT][JJP_FRAME_LEN];

    /* Coils are PULSES, not levels.  A 30 ms slingshot falls between UI polls
     * about half the time, so the shim publishes a monotonic change counter
     * per board and the UI must read EDGES from it, never sample out[] and
     * call it state.  This is the same mistake the Spike 2 rig made once with
     * its coil view. */
    volatile unsigned int out_changes[JJP_BOARD_COUNT];

    /* Per-BIT rising-edge counter for the OUT frames, wrapping at 256.
     *
     * out_changes above says only "this board changed", which is enough to
     * light an activity meter and useless for answering "did the trough eject
     * just fire".  A coil IS one bit: coil_vuk_trough is IO byte 1 bit 4, and
     * the game drives it for the 32 ms its own Coil object asks for (swdump.py
     * decodes that).  A reader polling at any sane rate would miss a 32 ms
     * pulse most of the time, so the shim counts the 0->1 edges as it writes
     * them and a reader compares counters.  A counter cannot be missed, only
     * coalesced - which is the same trade the Spike 2 rig's coil_publish()
     * makes, for the same reason.
     *
     * Index with JJP_RISE_INDEX; a wrapping unsigned char is enough because
     * readers only ever ask "different from last time?". */
    volatile unsigned char out_rise[JJP_BOARD_COUNT][JJP_FRAME_LEN * 8];

    volatile unsigned int read_count;
    volatile unsigned int write_count;
};

/* (frame byte, bit NUMBER 0..7) -> index into one board's out_rise row. */
#define JJP_RISE_INDEX(fb, bitno) ((fb) * 8 + (bitno))

/* The idle IN frame: every cabinet switch open, everything else open too.
 * Used wherever the block is created or reset, so a game that comes up before
 * any UI does not see a machine with every button jammed. */
static inline void jjp_in_frame_idle(volatile unsigned char *f)
{
    int i;
    for (i = 0; i < JJP_FRAME_LEN; i++)
        f[i] = (i >= JJP_DIRECT_FIRST_BYTE
                && i < JJP_DIRECT_FIRST_BYTE + JJP_DIRECT_BYTES)
               ? JJP_DIRECT_IDLE : 0;
}

#endif /* JJPSHM_H */
