/* padlcd.h - live VILLAIN VISION display state, published by the shim, read by
 * the playfield window. Item 83.
 *
 * Same host-path/guest-path split as padled.h: a 4096-byte file under
 * spike2root/dump/ that the chrooted guest opens by its /dump path and a
 * native process opens by its WSL path. Single writer (the guest), gen counter
 * so a reader can tell it moved without diffing the page.
 *
 * WHAT THIS IS. batman's node 24 is an lcdnode - the fixture the ELF calls
 * "3 LCD INSERT" / "LCD 320X240", the playfield's little TVs showing '66
 * episode footage. The game renders NOTHING to them over the bus: it names
 * stored ASSET NUMBERS in the card's villain-TV scene store
 * (assets/lcd/auto_loaded/<sha1>/scene.assets/137.asset/<id>.asset, 3,069
 * QuickTime H.264 assets, all 240x180).
 *
 * ★ VERSION 2 CORRECTS A MIS-DECODE. v1 read the byte after `f2 98` as a
 * starting DISPLAY INDEX and the payload as a list of u16 ids at stride 4,
 * so it believed in three independently addressable screens and published
 * id[4]. Disassembly of the game's own frame builders (2026-08-24) says
 * otherwise, and the numbers v1 produced for a game start - "displays
 * 0/1/2 = assets 54/928/106" - were one PLAY-RANGE command misread: 54 and
 * 928 are the range's first and last asset, and 106 is a frame-rate code.
 *
 * THE FRAME, as the game builds it (game.elf, builders 0x519a60-0x51aa38,
 * wire framing 0x515f8c):
 *
 *     [0x80|node] [len+1] [0xf2] [selector] [payload...] [cksum] [replylen+2]
 *
 * The SELECTOR carries the display number in its low 2 bits (0x51a968:
 * `~((~display) & 0x67)` == 0x98|display), and the shape of the payload is
 * disambiguated BY LENGTH, not by any sub-code:
 *
 *   sel        ilen  payload                                    builder
 *   0x98|d       4   [mode]  1 = loop, 2 = one-shot             0x51a9e0
 *   0x98|d       8   [0x00] [u32 asset]                         0x51a968
 *   0x98|d      14   [flags] [u32 first] [u32 last] [u16 rate]  0x51a7c0
 *   0x98|d      24   as above + [u32][u32][u16]  (0 call sites) 0x51a86c
 *   0x80|d       7   [brightness] [fade] [2 junk]               0x51a6e8
 *   0x88|d       7   3 bytes                     (0 call sites) 0x51a750
 *   0x90         7   [display] [3 junk], wants a 12-BYTE REPLY  0x519a60
 *   0xb8|d       7   none                        (0 call sites) 0x51aa38
 *
 * The rate is a frame PERIOD code indexing the table at 0x5c9340 =
 * {43,53,64,80,84,106,128,160} in 1/1280 s, i.e. {30,24,20,16,15,12,10,8}
 * fps - which is why 106 can never be an asset id: it is 12 fps.
 *
 * ★ ONE DISPLAY, NOT THREE, and this is the load-bearing fact for the
 * window. lcd_init (0x37dcf0) is the only place a display number is ever
 * assigned; it reads the device-LCD table at 0x717e94 (entry 1 =
 * "VILLAIN VISION", fixture 1, display number 0) and bounds it against the
 * fixture table at 0x717ed4, whose DISPLAY COUNT is 1. All 299 LCD call
 * sites in the binary pass the same device index, so no code path can
 * emit 0x99 or 0x9a. The three physical TVs are fed from one logical
 * display - the node board splits or mirrors them, which is board
 * firmware we cannot see from here.
 *
 * WHY THE SHIM AND NOT A LOG READER: same reason as padled.h - the shim
 * already serves every node-bus frame, and PAD_NB_LOG quadruples the boot.
 *
 * OFFSETS, since the Python reader hard-codes them: magic 0, version 4,
 * gen 8, decoded 12, asset 16, first 20, last 24, rate 28, mode 32,
 * bright 36, fade 40, ms 44, ring_head 48, ring at 52, stride 24,
 * PADLCD_RING 64.
 */
#ifndef PADLCD_H
#define PADLCD_H

#define PADLCD_MAGIC    0x44434c50u     /* 'PLCD' */
#define PADLCD_VERSION  2               /* v1 believed in 3 displays        */
#define PADLCD_RING     64
#define PADLCD_RAW      18              /* longest payload is 23 - clipped  */
#define PADLCD_BYTES    4096

struct padlcd_shm {
    unsigned magic;
    unsigned version;
    unsigned gen;                       /* bumped after every decoded frame */
    unsigned decoded;                   /* play commands decoded, ever      */
    /* WHAT THE ONE DISPLAY WAS LAST TOLD TO SHOW. A single-asset command
     * sets `asset` and clears the range; a range command sets first/last/
     * rate and clears `asset`. Exactly one of the two is live. */
    unsigned asset;                     /* single-asset play, 0 = none      */
    unsigned first;                     /* range play: first asset, 0 = none*/
    unsigned last;                      /* range play: last asset           */
    unsigned rate;                      /* range play: fps (already decoded
                                         * from the 0x5c9340 period code)   */
    unsigned mode;                      /* 1 = loop, 2 = one-shot, 0 unseen */
    unsigned bright;                    /* last 0x80 brightness             */
    unsigned fade;                      /* last 0x80 fade                   */
    unsigned ms;                        /* guest CLOCK_MONOTONIC ms at change*/
    /* Raw payloads for EVERY cmd-f2 selector this node sees, a lossy ring
     * for RE - v1 ringed only what it already understood, which is exactly
     * why the mis-decode above survived a live capture. */
    unsigned ring_head;                 /* frames written, ever; index = %64*/
    struct padlcd_raw {
        unsigned ms;
        unsigned char sel;              /* the selector byte after 0xf2     */
        unsigned char len;              /* payload bytes captured           */
        unsigned char b[PADLCD_RAW];    /* from the byte after the selector */
    } ring[PADLCD_RING];
};

#endif
