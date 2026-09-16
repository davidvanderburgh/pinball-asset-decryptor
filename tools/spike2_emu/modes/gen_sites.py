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
]


def pc_dependent(w):
    if (w & 0x0E000000) == 0x0A000000:                 # b / bl / blx imm
        return True
    if (w >> 26) & 3 == 1 and ((w >> 16) & 0xF) == 15:  # ldr/str based on pc
        return True
    if (w >> 26) & 3 == 0 and (((w >> 16) & 0xF) == 15 or ((w >> 12) & 0xF) == 15):
        # data processing reading or writing pc (movw/movt have imm4 there: skip them)
        return (w & 0x0FB00000) != 0x03000000
    if (w & 0x0E108000) == 0x08100000:                 # ldm ... pc (a return)
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
