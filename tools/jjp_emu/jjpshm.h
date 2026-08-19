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
#define JJP_SHM_MAGIC   0x4a4a5031u          /* "JJP1" */
#define JJP_SHM_VERSION 1

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

/* The 128-switch matrix sits at bytes 4..19 of the 64-byte IN frame, LSB
 * first.  Derived from the live Switch objects and re-verified on every
 * swdump.py run - see that file's docstring for the derivation.
 *
 *     switch_NNN -> byte 4 + (N-1)/8, bit 1 << ((N-1)%8)
 */
#define JJP_MATRIX_FIRST_BYTE 4
#define JJP_MATRIX_BYTES      16
#define JJP_MATRIX_SWITCHES   128
#define JJP_FRAME_LEN         64

struct jjp_shm {
    unsigned int magic;
    unsigned int version;
    unsigned int game_pid;

    /* Driver -> game.  Bit set = switch closed.  Written by the UI, read by
     * the shim on every read() of the I/O board. */
    volatile unsigned char switches[JJP_MATRIX_BYTES];

    /* Cabinet switches (coin door, start, flipper buttons) ride the CAB board. */
    volatile unsigned char cabinet[JJP_MATRIX_BYTES];

    /* Game -> driver.  Last OUT frame per board: coil drives, lamp pages. */
    volatile unsigned char out[JJP_BOARD_COUNT][JJP_FRAME_LEN];

    /* Coils are PULSES, not levels.  A 30 ms slingshot falls between UI polls
     * about half the time, so the shim publishes a monotonic change counter
     * per board and the UI must read EDGES from it, never sample out[] and
     * call it state.  This is the same mistake the Spike 2 rig made once with
     * its coil view. */
    volatile unsigned int out_changes[JJP_BOARD_COUNT];

    volatile unsigned int read_count;
    volatile unsigned int write_count;
};

#endif /* JJPSHM_H */
