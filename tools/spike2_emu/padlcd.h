/* padlcd.h - live VILLAIN VISION display state, published by the shim, read by
 * the playfield window. Item 83.
 *
 * Same host-path/guest-path split as padled.h: a 4096-byte file under
 * spike2root/dump/ that the chrooted guest opens by its /dump path and a
 * native process opens by its WSL path. Single writer (the guest), gen counter
 * so a reader can tell it moved without diffing the page.
 *
 * WHAT THIS IS. batman's node 24 is an lcdnode ("VILLAIN VISION", 3 LCD
 * INSERT, 320x240) - three little TVs on the playfield showing '66 episode
 * art. The game renders NOTHING to them over the bus: it sends tiny
 * DISPLAY-ID frames (cmd f2 sub 0x98) naming which stored clip each insert
 * shows, and the id is the asset number inside the card's villain-TV scene
 * store (assets/lcd/auto_loaded/<sha1>/scene.assets/137.asset/<id>.asset,
 * 3,069 QuickTime H.264 assets, all 240x180 - mapping VERIFIED by eyeball
 * 2026-08-24: id 54 = Robin in the Batmobile, id 919 = a wall-climb cameo,
 * ids 3047+ = the per-villain portraits the radium labels name).
 *
 * THE FRAME (measured off a live game, gzwatch.lcdcap.log):
 *     98 <ilen> f2 98 <start> <id lo> <id hi> 00 00 [<id lo> <id hi> 00 00
 *     ...] <cksum> <replylen>
 * ids are LE16 at stride 4 after the start byte; a frame carrying N ids sets
 * displays start..start+N-1. The attract cycles single-id frames every 5.2 s;
 * game start sends one 3-id frame (919/928/106 - one per insert). Sub 0x02
 * frames (`f2 98 02`, no ids) are a commit/refresh marker and change nothing
 * here. Sub 0x80/0x90 are the node-update walk, not display traffic.
 *
 * WHY THE SHIM AND NOT A LOG READER: same reason as padled.h - the shim
 * already serves every node-bus frame, and PAD_NB_LOG quadruples the boot.
 *
 * OFFSETS, since the Python reader has to hard-code them: magic 0, version 4,
 * gen 8, decoded 12, id[4] at 16 (u32 each), ms[4] at 32, ring_head 48,
 * ring at 52, ring stride 16, PADLCD_RING 64.
 */
#ifndef PADLCD_H
#define PADLCD_H

#define PADLCD_MAGIC    0x44434c50u     /* 'PLCD' */
#define PADLCD_VERSION  1
#define PADLCD_DISPLAYS 4               /* 3 fitted; one spare, same reasoning
                                         * as padled's flat [16][96]          */
#define PADLCD_RING     64
#define PADLCD_BYTES    4096

struct padlcd_shm {
    unsigned magic;
    unsigned version;
    unsigned gen;                       /* bumped after every decoded frame   */
    unsigned decoded;                   /* display-id frames decoded, ever    */
    unsigned id[PADLCD_DISPLAYS];       /* current display id per insert      */
    unsigned ms[PADLCD_DISPLAYS];       /* guest CLOCK_MONOTONIC ms at change */
    /* Raw sub-0x98 payloads, a lossy ring for RE and debugging - a slow
     * reader loses old frames rather than blocking the shim. */
    unsigned ring_head;                 /* frames written, ever; index = %64  */
    struct padlcd_raw {
        unsigned ms;
        unsigned char len;              /* payload bytes captured, <= 11      */
        unsigned char b[11];            /* from the start byte onward         */
    } ring[PADLCD_RING];
};

#endif
