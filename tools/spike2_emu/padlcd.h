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
 * ★ WHERE THE PIXELS ACTUALLY COME FROM (RE 2026-08-25, 10-agent pass,
 * adversarially verified - this closes the mystery). Node 24 is a CONTROL
 * channel, not a pixel channel: it is an LPC1113 (24KB flash, 8KB RAM,
 * cannot decode H.264) and the bus frame builder 0x515f8c hard-caps every
 * frame at 200 bytes (no bulk path exists; the only large transfer in the
 * whole binary is the one-time node FLASH PROGRAMMER at 0x51cb54, 128 B a
 * frame). The villain TVs' VIDEO is drawn by the MAINBOARD GPU: the game
 * has a full "secondary display" render-to-texture subsystem (rodata
 * 0x554d28 "Attempting to render to secondary display, but no secondary
 * display enabled.", 0x665ab4 "...secondary_render_to_texture->get_id()")
 * that composites the VillainTvsCombo scene (element-name tree at
 * 0x59e3c8: TV1_Instance.TV1_Animation.VideoSurface, per TV) onto a second
 * EGL surface from fbGetDisplayByIndex(2).
 *
 * ★ AND THAT SUBSYSTEM IS COMPILED-IN BUT HARD-DISABLED IN THIS BUILD.
 * The second EGL surface is created only at 0x412a14 (fbGetDisplayByIndex
 * index 2), gated at 0x4129fc on renderer-context field +0xf0 (the
 * second-display object) being non-null. That field is written ONLY by the
 * context ctor 0x4126c0 (str r6,[r4,#0xf0] @0x41275c) from its 3rd arg, and
 * the ctor's SOLE caller 0x1e79d0 passes r2=#0 (@0x1e79c8) - unconditional
 * NULL. So batman never calls fbGetDisplayByIndex(2), never makes a second
 * surface, and the four villain gst channels (137.asset, pre-armed at
 * game/attract) die at 0 frames because there is no target to composite
 * onto. Making the game itself draw the villain combo would mean
 * INSTANTIATING that whole second-display object (valid geometry at +16/
 * +20 and more) - a subsystem the binary deliberately never builds, not a
 * flag - and is out of scope for a live mirror. The host side (padglhost
 * item 44 second window, eglshim PAD_GL2_W/H) already exists if that is
 * ever taken on.
 *
 * So THIS block - the node-bus command stream - is the faithful, complete
 * record of what node 24 (the villain display's controller) is told to
 * show, and the panel that renders it is the truthful live mirror. It can
 * never BE the game's own composite (that is a separate, disabled render
 * target) but it shows the same clips, by the same ids, on the same live
 * commands.
 *
 * ★ GROUND TRUTH, and it CONFIRMS the composite finding (David's video of
 * the real machine, 2026-08-25, attract then a game). Measured from it:
 *   - ONE TV, bezel-printed "Villain Vision", one full-screen image.
 *   - Each item holds ~5-7 s, and a FULLY BLACK frame sits between items -
 *     the 0x80 brightness dip, which is why the panel now blanks on
 *     bright < 128 rather than showing footage through the gap.
 *   - The content is motion video, one clip at a time.
 *   - ...AND it includes GAME-RENDERED CARDS: a "Game Over" card and the
 *     BATMAN logo on green (the one David kept asking for). Neither exists
 *     anywhere in the 3,069-clip store - three independent scans (first
 *     frame green-dominance, mid-frame green-dominance, flat-graphic
 *     colour-count) all come back empty.
 * That last point is the proof, from the machine rather than the ELF, that
 * the real display is COMPOSITED by the game and not merely "play stored
 * clip N". A node-bus mirror can never show those cards, and pretending
 * otherwise would be the fourth invented story on this protocol. What the
 * mirror does show - the commanded clip, the cadence, the fade, the
 * one-shot hold - is now verified against the machine itself.
 *
 * ★ VERSION 3 STOPS NAMING FIELDS WE HAVE NOT PROVEN. v1 invented three
 * displays. v2 fixed that but replaced one guess with another: it read the
 * 14-byte payload as "first asset .. last asset @ rate" and captioned it
 * that way on screen. The QUEUE STRUCT says otherwise - see below. Only
 * one field in that payload is proven, and it is the one v2 called
 * `first`. The rest are recorded under neutral names until something
 * names them.
 *
 * THE FRAME, as the game builds it (builders 0x51a6e8-0x51aa38, wire
 * framing 0x515f8c):
 *
 *     [0x80|node] [ilen] [0xf2] [selector] [payload...] [cksum] [replylen]
 *
 * ★ ilen IS THE BUILDER'S LENGTH PLUS ONE, and that +1 is not a guess:
 * 0x516188-0x516190 in the transmit path reads the length byte, does
 * `add r2,r2,#1`, and stores it back before the frame goes out. So the
 * builders' 3/7/13/23 reach the wire as 4/8/14/24. (v2 asserted these
 * numbers from a capture; this is where they actually come from.)
 *
 * The SELECTOR carries the display number in its low 2 bits (0x51a968:
 * `~((~display) & 0x67)` == 0x98|display), and the shape of the payload is
 * disambiguated BY LENGTH, not by any sub-code:
 *
 *   sel        ilen  payload                                    builder
 *   0x98|d       4   [verb]                                     0x51a9e0
 *   0x98|d       8   [0x00] [u32 A]                             0x51a968
 *   0x98|d      14   [flags] [u32 A] [u32 D] [u16 rate]         0x51a7c0
 *   0x98|d      24   [flags] [u32 A] [u32 D] [u16 rate]
 *                        [u32 B] [u32 C] [u16 E]                0x51a86c
 *   0x80|d       7   [brightness] [fade] [2 junk]               0x51a6e8
 *   0x88|d       7   3 bytes                     (0 call sites) 0x51a750
 *   0x90         7   [display] [3 junk], wants a 12-BYTE REPLY  0x519a60
 *   0xb8|d       7   none                        (0 call sites) 0x51aa38
 *
 * ★ A IS THE ASSET ID, AND THAT IS PROVEN. All four play commands are
 * emitted by one dispatcher, the per-display service routine at
 * 0x37e49c. It switches on a COMMAND KIND at display[+20] through the
 * jump table at 0x37e4b4, and every kind that carries content points at
 * the SAME queued request struct at display[+24]:
 *
 *   kind 4 (0x37e540)  ldr r2,[r6,#24]   -> 0x51a968  the u32 AT struct+0
 *   kind 2 (0x37e5b0)  add r2,r6,#24     -> 0x51a7c0  reads struct+0,+12,+18,+20
 *   kind 3 (0x37e578)  add r2,r6,#24     -> 0x51a86c  reads those +4,+8,+16
 *
 * Kind 4 hands struct+0 to the builder whose whole payload is one asset
 * number. So struct+0 - the field that lands at payload offset 1 in the
 * 8, 14 and 24-byte forms alike - IS the clip to play, in every form.
 * That is why `asset` below is set from all three and why the panel draws
 * it without apology.
 *
 * WHAT IS *NOT* PROVEN, and is therefore not named: struct+12 (`aux`).
 * v2 called it the range's LAST asset on the strength of one capture
 * where it read 928; v3 swung to "not a range" - and that was TOO HARD.
 * 0x37e2fc is a range-DURATION helper: (first, last, rateidx) ->
 * (last - first + 1) x the 0x5c9340 period, so an inclusive-range
 * consumer exists in this very family. What remains untraced is whether
 * THESE two payload fields feed it, and what the board does with the
 * range (playlist / flipbook / pick). So `aux` stays a number in the
 * caption - a name needs the caller that connects the fields to the
 * helper, nothing less. Both mis-namings of this protocol came from
 * skipping exactly that step.
 *
 * THE VERB is also not a "mode". 0x51a9e0 sends a single payload byte and
 * FIVE dispatch kinds call it with five different values - 1 and 2 from
 * the kinds that then send content (display[+48] chooses between them, so
 * they read as play-looping / play-once), and 3, 4, 5 from kinds 7, 5 and
 * 6 which send nothing after. Those three are almost certainly stop /
 * pause / clear, in some order, and until that order is known the panel
 * prints the number rather than picking a word. v2 stored this as `mode`
 * and silently showed nothing for 3/4/5, which is how a "stop" looked
 * identical to "carry on playing".
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
 * emit 0x99 or 0x9a.
 *
 * ★ AND THERE IS ONLY ONE PHYSICAL TV. Earlier versions of this comment
 * said "the three physical TVs are fed from one logical display - the
 * node board splits or mirrors them", which was invented to rescue the
 * fixture NAME ("3 LCD INSERT") after v1's three-screen decode died.
 * David's 2026-08-25 video of the real machine settles it: the playfield
 * carries ONE retro TV with "Villain Vision" printed on its bezel, showing
 * ONE full-screen image. Nothing splits or mirrors anything. (The fixture
 * name is not three displays - a 3-inch insert is the likelier reading -
 * and the display count of 1 above was always the load-bearing fact.)
 *
 * WHY THE SHIM AND NOT A LOG READER: same reason as padled.h - the shim
 * already serves every node-bus frame, and PAD_NB_LOG quadruples the boot.
 *
 * OFFSETS, since the Python reader hard-codes them: magic 0, version 4,
 * gen 8, decoded 12, asset 16, aux 20, rate 24, verb 28, x1 32, x2 36,
 * x3 40, bright 44, fade 48, ms 52, ring_head 56, ring at 60. Ring entry:
 * ms 0, last 4, rep 8 (u16), sel 10, len 11, b 12, stride 36 (v3 rings,
 * still readable in preserved blocks, were ms 0, sel 4, len 5, b 6,
 * stride 28). PADLCD_RING 64.
 */
#ifndef PADLCD_H
#define PADLCD_H

#define PADLCD_MAGIC    0x44434c50u     /* 'PLCD' */
#define PADLCD_VERSION  4               /* v1: 3 displays. v2: a fake range.
                                         * v3: 60 Hz polls ate the ring     */
#define PADLCD_RING     64
#define PADLCD_RAW      22              /* the 24-byte form's payload is 21 */
#define PADLCD_BYTES    4096

struct padlcd_shm {
    unsigned magic;
    unsigned version;
    unsigned gen;                       /* bumped after every decoded frame */
    unsigned decoded;                   /* play commands decoded, ever      */
    /* WHAT THE ONE DISPLAY WAS LAST TOLD TO SHOW. `asset` is struct+0 and
     * is the clip, whichever of the three content forms carried it. */
    unsigned asset;                     /* the clip to play, 0 = none       */
    unsigned aux;                       /* struct+12. UNNAMED. Not a range  */
    unsigned rate;                      /* fps, decoded from the period code*/
    unsigned verb;                      /* 1,2 = play (loop/once); 3,4,5 =
                                         * sent with no content; 0 = unseen */
    unsigned x1, x2, x3;                /* the 24-byte form's extra fields
                                         * struct+4, +8, +16. UNNAMED.      */
    unsigned bright;                    /* last 0x80 brightness             */
    unsigned fade;                      /* last 0x80 fade                   */
    unsigned ms;                        /* guest CLOCK_MONOTONIC ms at change*/
    /* Raw payloads for EVERY cmd-f2 selector this node sees, a lossy ring
     * for RE - v1 ringed only what it already understood, which is exactly
     * why its mis-decode survived a live capture. watch.sh AND killgame.sh
     * preserve this page at run end (dump/padlcd.last) because a ring that
     * dies with the run cannot settle an argument about what the game sent.
     *
     * ★ v4 COALESCES IDENTICAL CONSECUTIVE FRAMES, because the first live
     * reading (2026-08-25) showed the 0x90 status poll arriving at 60 Hz -
     * every 17 ms, constant payload - which made 64 raw slots hold barely
     * ONE SECOND of history and flushed every play command out of the ring
     * within a second of it happening. A frame that matches the previous
     * slot's selector and payload bumps that slot's `rep` and refreshes
     * `last` instead of taking a new slot; a quiet poll stretch is one
     * line, and the ring spans minutes of play. Every frame is still on
     * record - as a count, which is what a 60 Hz constant IS. ring_head
     * counts SLOTS, not frames; sum rep for frames. */
    unsigned ring_head;                 /* slots written, ever; index = %64 */
    struct padlcd_raw {
        unsigned ms;                    /* first time this frame arrived    */
        unsigned last;                  /* latest time (== ms when rep 1)   */
        unsigned short rep;             /* arrivals coalesced here, sat.max */
        unsigned char sel;              /* the selector byte after 0xf2     */
        unsigned char len;              /* payload bytes captured           */
        unsigned char b[PADLCD_RAW];    /* from the byte after the selector */
        unsigned char pad[2];           /* explicit: stride is 36, say so   */
    } ring[PADLCD_RING];
};

#endif
