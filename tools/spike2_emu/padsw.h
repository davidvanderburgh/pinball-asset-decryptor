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
 * There is deliberately no locking. A writer writes bytes and then bumps its
 * generation; the guest reads the generation, reads the bytes, and re-reads the
 * generation. A torn read costs one frame of a switch being wrong, which is far
 * cheaper than any of the alternatives and is indistinguishable from ordinary
 * switch bounce.
 *
 * ---- THREE REGIONS, ONE WRITER EACH. This is the whole point of the layout.
 *
 * There used to be ONE array, and both the keyboard and the scripts wrote it.
 * padglhost REBUILDS its picture of the switch matrix from scratch on every key
 * event - deliberately, so two keys bound to one switch cannot leave it stuck -
 * so every key press erased every byte swpoke.py, plunge.py, swhold.py or a
 * virtual-playfield click had put there. That is REMAINING item 7: a scoop
 * click that did not register, and a plunge that looked dead, both because
 * David's hands were on the flipper keys at the time.
 *
 *   held[]     KEYBOARD    written only by padglhost, `gen` its counter
 *   scr_held[] SCRIPTS     written only by the .py helpers, `scr_gen`
 *   mrg[]      THE ANSWER  written only by the guest shim, `mrg_gen`
 *
 * The shim merges the first two by LAST EDGE WINS, PER ID - not by OR. An OR
 * cannot work here: padglhost latches the coin door (C) and all six trough
 * balls (B) ON when its window opens, because that is a machine at rest, so
 * under an OR plunge.py could never take a ball OUT of the trough again.
 * Last-edge-wins means a writer only ever moves the ids it actually changed,
 * and a rebuild that re-asserts what was already there moves nothing.
 *
 * mrg[] is what the game is ACTUALLY handed, published back so a reader outside
 * the guest (playfield.py, over 9p) can see it without having to guess at the
 * merge. Reading held[] instead is reading one of the two inputs.
 */
#ifndef PADSW_H
#define PADSW_H

#define PADSW_MAGIC   0x53444150u        /* 'PADS' little-endian */
#define PADSW_MAX_ID  256
#define PADSW_BYTES   4096

struct padsw_shm {
    unsigned magic;
    unsigned gen;                        /* KEYBOARD generation; padglhost only */
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

    /* ---- THE SCRIPT REGION. Everything that is not a key press writes here:
     * swpoke.py, swhold.py, plunge.py, coilact.py, swinit.py, and the virtual
     * playfield through them. padglhost never touches these two fields, and
     * never zeroes them - not even in its own init, which is why it checks the
     * magic first rather than memsetting the whole block. */
    unsigned scr_gen;                    /* scripts bump after every change    */
    unsigned char scr_held[PADSW_MAX_ID];

    /* ---- WHAT THE GAME IS ACTUALLY BEING HANDED, published by the guest.
     * Written only by hwshim's sw_shm_merge(); read by anyone who wants the
     * truth rather than one of the two inputs. This is a diagnostic output, so
     * nothing in the input path may ever read it back. */
    unsigned mrg_gen;
    unsigned char mrg[PADSW_MAX_ID];

    /* ---- PROVENANCE AND THE CLOCK. Both exist for REMAINING item 16, replaying
     * a session's switch inputs from its log, and both answer a question the
     * `[sw]` line could not.
     *
     * WHY THE REGION IS NOT ENOUGH, which is the whole reason these are here.
     * "Keyboard or script" falls straight out of which array moved, and it is
     * the wrong split: autoattract.sh presses Service Back through swpoke.py,
     * so the rig's own boot press is a SCRIPT edge, indistinguishable from a
     * flipper poke. A replay that re-delivers it doubles up with the
     * autoattract of the new run. The other half is the same shape from the
     * other side - padglhost latches the coin door and six trough balls when
     * its window opens, and that lands in the KEYBOARD array looking exactly
     * like David pressing C and B.
     *
     * So each writer says who it is, in the byte below its own region, BEFORE
     * it bumps its generation. The shim reads the tag in the same pass that
     * observes the change and attributes it to every id that moved. One letter:
     *
     *   k  a real key event          w  padglhost's window-open latch
     *   K  PAD_SW_KEYSIM             a  autoattract.sh's Service Back
     *   p  swpoke.py                 h  swhold.py
     *   l  plunge.py                 c  coilact.py
     *   i  swinit.py                 f  a virtual-playfield click
     *   g  longplay.sh's gameplay    r  swreplay.py re-delivering a log
     *   b  ballfeed.py, answering the game's own trough eject
     *   ?  nobody said
     *
     * THE ONE HONEST LIMIT: the shim attributes per MERGE, not per write. Two
     * scripts that both write and bump between two merges collapse into one
     * tag, and the later one wins. In practice autoattract has exited before
     * longplay starts and the playfield is a human clicking, so this has no
     * overlap to lose - but it is an approximation and not a receipt.
     *
     * `guest_t0_ms` is the shim's pad_ms() origin: CLOCK_MONOTONIC in ms, the
     * same clock and the same truncation. A host-side script that reads it can
     * compute the guest's own millisecond WITHOUT tailing a log and without
     * drifting, because qemu-user runs on this same host clock - the two are
     * not merely close, they are the same counter with a different zero. */
    unsigned kbd_src;                    /* padglhost's tag for its last publish */
    unsigned scr_src;                    /* the scripts' tag for theirs          */
    unsigned guest_t0_ms;                /* the shim writes; everyone else reads */
};

#endif
