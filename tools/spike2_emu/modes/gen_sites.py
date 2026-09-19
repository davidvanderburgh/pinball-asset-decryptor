#!/usr/bin/env python3
"""Emit padmode_sites.h: every address padmode.c hooks or calls, with the two
instruction words it expects to find there, read out of the game ELF it is built for.

The words are the safety check. At run time padmode.so compares them before touching
anything, so the same .so preloaded under another title or another build of Godzilla
refuses and logs instead of patching an unrelated function. It refuses at BUILD time
too: a site whose first two instructions are not position-independent cannot be
relocated into a trampoline, and this exits non-zero rather than emit it.

Usage: gen_sites.py <game_elf> > padmode_sites.h
One header for both .so files (padmode.c the probe, mode.c our mode). Item 125.
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rtti_tree as rt  # noqa: E402

# name, VA on godzilla Pro 1.15 (tools/spike2_emu/modes/MODE_API.md), hooked?
SITES = [
    ("TICK", 0x4EC828, True),         # tick_body_60hz - the probe's clock and trigger poll
    ("STARTED", 0xD246C, True),       # cmode_manager_started(mgr, id)
    ("STOPPED", 0xD24C4, True),       # cmode_manager_stopped(mgr, id, reason)
    ("V15", 0x7D2B0, True),           # cmode::v[15] on_shots - who delivers shots
    ("TESLA_V41", 0x10D0BC, True),    # cmode_tesla_strike::v[41] on_shot
    ("SCORE_ADD", 0x4B8CF4, True),    # score_add(p, v64)
    ("CAWARD_ADD", 0x2FACC, True),    # caward_add(aw, _, v64, idx)
    ("SOUND", 0x2A3108, True),        # sound_request_play(req)
    ("CALLOUT", 0x187F44, True),      # callout_play(req)
    ("SHOW", 0x4F34E0, True),         # show_start(id)?
    ("EVPOST", 0x2555DC, True),       # event_post_replacing(id, handler, flags)
    ("TEXT", 0x3BA540, True),         # 0x3ba540(n, a, b, obj) - text screen?
    ("FX", 0x185E9C, True),           # 0x185e9c(n, a, b) - lights/flash?
    ("DISPATCH", 0xD1A9C, True),      # cmode_manager::v[7](mgr, _, mask64, x) - every shot
    ("BALLEND", 0xD3DCC, True),       # every mode's v[4] - the end-of-ball broadcast
    ("MSG", 0x34A764, True),          # msg_lookup(id) -> string, 1079 callers
    ("SOUND_NTH", 0x2A32BC, True),    # sound_request_play_nth(req, n) - the countdown's path
    ("GET", 0xD1C10, False),          # cmode_manager_get(mgr, id) - called, not hooked
    ("CALLOUT_NTH", 0x18800C, False), # callout_play_nth(req, n) - called, not hooked
    ("SHOW_KILL", 0x255DD4, False),   # kill every running instance of show id - called
    ("SHOW_RUNNING", 0x255D7C, False),# is show id running - called
    ("BLELE_RUN", 0x1C3454, False),   # run a blele/blela light command (owner, group, str, 0) - called
    ("LAMP_GROUP", 0x4BF294, False),  # lamp group from light-set table 0x7257a8 (set 0 = empty) - called
    ("SHOW_PRIO", 0x4F3740, False),   # the running show's lamp priority, off the current event - called
    ("GROUP_FREE", 0x3C15CC, False),  # give a lamp group back (the pool is 48, 0x3c1700) - called
    ("SOUND_START", 0x2A2044, True),  # the channel START, after the arbitration and after
                                      # hook_dispatch(0xac)'s veto at 0x2a2abc. Hooked to answer
                                      # the one question left in item 130: when a callout is
                                      # fired and its sid's tree node has been retargeted, is a
                                      # channel ever started at all? A sound that never starts
                                      # cannot be changed by retargeting any record.
    ("SOUND_LOOKUP", 0x33C0D8, True), # sound_lookup(map, key8) -> the sound container entry.
                                      # bucket = uidivmod(key.w1, map[1]), then find 0x2a25e0.
                                      # HOOKED so a mode can point r1 at a key of its OWN: the
                                      # bucket is computed INSIDE this function from *r1, so the
                                      # substitution has to happen here and not at the find (item 130)
    ("BLELE_PARSE", 0x1C2B6C, True),  # the light command parser itself. The runner 0x1c3454 is a
                                      # single `b` into it, which cannot be relocated into a
                                      # trampoline, so the GAME's own light commands are watched here
    # item 131, scenelog.c: the scene.radium reader. cereal PortableBinaryInputArchive's
    # loadBinary<N>(this, data, bytes) - all four share `ldr r3,[r0,#0x7c]` (itsStream)
    # then sgetn through vtable +0x20; <2>/<4>/<8> byte-swap when [this+0x80] is set
    ("LB1", 0x27316C, True),
    ("LB2", 0x283274, True),
    ("LB4", 0x2744C8, True),
    ("LB8", 0x27F230, True),
    ("SIZETAG", 0x27F4E0, True),      # cereal size tag: loadBinary<8> into *r1, archive at [r0,#4]x4
    ("CHILD_RESIZE", 0x28E4A0, True), # vector<16-byte>::resize(n); a node's child vector (0x290838),
                                      # where the authored-node boots threw _M_default_append
    ("SCENE_GET", 0x3BAC44, True),    # resource by name (&std::string id, kind, 0): kind 1 = the attract
                                      # scene 394c4a03, 0 = gameplay scenes, 3 = nk_spi_system
    ("FIND_NODE", 0x578A2C, True),    # node by dotted path (&out shared_ptr, parent, &std::string), 236 callers
    ("SET_TEXT", 0x55C1F4, True),     # a text node's string (node, &std::string)
    ("STR_CTOR", 0x16908, False),     # PLT std::string(const char *, const allocator &) - called, not hooked
    ("FIND_TEXT", 0x5784C8, False),   # find_node for TEXT nodes: FIND_NODE is a TYPED find (generic 0x577a4c then
                                      # __dynamic_cast) and returns null for a Text; the HUD fills the node it
                                      # hands SET_TEXT with this one (0x1ad0e4 -> [r4+0x90] -> 0x1ad2d0) - called
    ("RES_GET", 0x443DE4, False),     # resource manager get (mgr [0x7db220], &std::string id, kind) - called
    ("DYNCAST", 0x16308, False),      # PLT __dynamic_cast(ptr, src typeinfo, dst typeinfo, hint) - called
    # item 132: a clip of our own. Every in-game clip goes through one call on the video bank
    # scene 60ed7e50's VideoSurface; end-of-ball bonus is ("EndOfBallBonus_BackgroundLoop", 1,
    # "SquareCrop") at 0x65c54
    ("PLAY_CLIP", 0x528A4, False),    # play_clip(const char *name, int loop, const char *crop label, 0 = "Normal") - called
    ("STOP_CLIP", 0x52B04, False),    # stop the in-game video surface - called
    # ...and DRAWING it, which play_clip does not do (run 1: decoded to end of stream, never on
    # the glass). A scene is drawn in immediate mode: whoever owns it calls advance + draw every
    # frame, e.g. 0x22d50: while (state(surface) == 2) { 0x3ba938(player, lap ms);
    # 0x3ba964(player, 3); yield }
    ("VIDEO_PLAYER", 0x52694, False), # the video bank's scene player, created on first use - called
    ("VIDEO_SURFACE", 0x526B8, False),# its VideoSurface node - called
    ("SURFACE_STATE", 0x56B758, False),  # state(surface): 2 = playing - called
    ("PLAYER_ADVANCE", 0x3BA938, False), # advance(player, f32 ms since the last frame) -> 0x4eea24 - called
    ("DISPLAY_DRAW", 0x4EEB08, False),# draw(display [0x7db1a0+0x7c], player, layer 0|1) this frame. 0x3ba964
                                      # wraps it for the CURRENT EVENT's layer and logs error 0x101 without one - called
]


def pc_dependent(w):
    if (w & 0x0E000000) == 0x0A000000:                 # b / bl / blx imm
        return True
    if (w >> 26) & 3 == 1 and ((w >> 16) & 0xF) == 15:  # ldr/str based on pc
        return True
    if (w >> 26) & 3 == 0 and (((w >> 16) & 0xF) == 15 or ((w >> 12) & 0xF) == 15):
        # data processing reading or writing pc (movw/movt have imm4 there: skip them)
        return (w & 0x0FB00000) != 0x03000000
    if (w & 0x0E108000) == 0x08108000:                 # ldm ... pc (a return); bit 15 is pc.
        # It compared against 0x08100000 until item 131, which flagged every ldm that
        # does NOT load pc (0x28e4a0's `ldm r0,{r2,r5}`) and passed the ones that do.
        return True
    return False


def main(argv):
    elf = argv[0]
    b = open(elf, "rb").read()
    va2off, _ = rt.make_mappers(rt.load_segments(b))
    print("/* padmode_sites.h - GENERATED by gen_sites.py, do not edit.")
    print(" * from %s (%d bytes, sha1 %s) */" % (os.path.basename(elf), len(b), hashlib.sha1(b).hexdigest()))
    bad = 0
    for name, va, hooked in SITES:
        w0, w1 = struct.unpack_from("<II", b, va2off(va))
        if hooked and (pc_dependent(w0) or pc_dependent(w1)):
            sys.stderr.write("gen_sites: %s 0x%x starts %08x %08x - not relocatable\n" % (name, va, w0, w1))
            bad += 1
        print("#define SITE_%s 0x%08xu\n#define SITE_%s_W0 0x%08xu\n#define SITE_%s_W1 0x%08xu"
              % (name, va, name, w0, name, w1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
