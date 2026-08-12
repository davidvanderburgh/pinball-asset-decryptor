#!/usr/bin/env python3
"""modewatch.py - publish the game's own "am I in the service menu" word to the
video shim, by reading it HOST-SIDE out of /proc/<guest>/mem (item 43).

WHY THIS EXISTS AT ALL, because it looks like a detour and is not:

The 4.28 service page picks TEXT/dots vs the broken video "band" from what the
backdrop pipeline's caps say at ONE read, and that read happens on the FIRST
long Select - at menu-SYSTEM entry, before the menu has drawn a single frame.
That timing is what killed the renderer-side detector (padglhost classifying
draws by shader program): its verdict is correct and stable, but it cannot
exist until a menu frame is drawn, which is AFTER the latch. Run-proven twice
on 2026-08-12 - every page banded with the renderer flag alone, in the service
flow and in David's own attract -> Select x2 flow.

The game's app-mode word flips to "menu" BEFORE that latch (that is how the
memory diff found it in the first place), so it is the one signal that arrives
in time. What it is NOT is readable from inside the shim: the guest's own load
of that address returns 0 in every state, while /proc/<pid>/mem reads the true
enum at the same instant, in the same single-threaded-address-space process
(one pid, 21 threads, no fork, guest_base=0 proven by the ELF magic at
0x18000; 314,316 host samples across a 60 s window, value 1 throughout, zero
transitions, while two in-guest stamps in that same window both said 0).
Unexplained - and worked around here rather than waited on, because the host
read is provably correct and costs one small helper.

So: poll the word, keep the SAW-ATTRACT latch that stops it firing at boot
(boot is also mode==0, and a lie during boot is the prepare storm this item
already paid for once), and publish the verdict into the padgl ring header the
video shim already maps. The per-title address stays CONFIG (PAD_VID_MENUMODE)
and never enters a shim that also runs other titles.
"""
import os
import struct
import subprocess
import sys
import time

# padgl_hdr layout (padgl.h): magic,version,ring_bytes,guest_alive (4x4=16),
# head,tail,frame_seq,frame_ack (4x8=32, so 16..48), fb_w,fb_h,host_ready,
# host_error (48..64), menu_flag (64), mode_flag (68).
MODE_FLAG_OFF = 68
PADGL_MAGIC = 0x4C477061

ATTRACT, GAMEPLAY = 1, 3          # values that mean "not in the menu system"
POLL_S = 0.0002                   # 5 kHz: the latch is ms-scale work


def say(msg):
    print(f"[modewatch] {msg}", flush=True)


def guest_pid():
    """The qemu-user process running the game, or None. Same patterns as
    padpath.sh's pad_guest_up - comm=game first, then the binfmt names."""
    for cmd in (["pgrep", "-x", "game"], ["pgrep", "-f", "arm-binfmt|qemu-arm"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout.split()
        except OSError:
            continue
        for p in out:
            if p.isdigit() and os.path.exists(f"/proc/{p}/mem"):
                return int(p)
    return None


def main():
    addr = os.environ.get("PAD_VID_MENUMODE", "")
    ring = os.environ.get("PAD_GL_BRIDGE_HOST") or os.environ.get("PAD_GL_BRIDGE")
    if not addr or not ring:
        say("no PAD_VID_MENUMODE or ring path - nothing to watch")
        return 0
    addr = int(addr, 16 if addr.lower().startswith("0x") else 16)

    # Wait for BOTH ends: the ring is created by padglhost, the memory by the
    # guest. Neither is up when watch.sh starts its helpers.
    deadline = time.time() + 180
    pid = None
    while time.time() < deadline and (pid is None or not os.path.exists(ring)):
        pid = pid or guest_pid()
        time.sleep(0.5)
    if pid is None or not os.path.exists(ring):
        say("guest or ring never appeared - giving up (the door gate still works)")
        return 1

    try:
        rf = open(ring, "r+b", buffering=0)
        hdr = rf.read(8)
        if len(hdr) < 8 or struct.unpack("<I", hdr[:4])[0] != PADGL_MAGIC:
            say("ring magic mismatch - not publishing")
            return 1
        mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
    except OSError as e:
        say(f"cannot attach ({e}) - the door gate still works")
        return 1

    say(f"watching 0x{addr:x} in pid {pid}, publishing to {ring}+{MODE_FLAG_OFF}")
    saw_attract = False
    published = None
    misses = 0
    while True:
        try:
            mem.seek(addr)
            val = struct.unpack("<I", mem.read(4))[0]
        except OSError:
            misses += 1
            if misses > 20:            # the guest went away; so do we
                say("guest gone")
                return 0
            time.sleep(0.2)
            continue
        misses = 0
        if val in (ATTRACT, GAMEPLAY):
            saw_attract = True
        # ARMED always (bit 1) so the shim can tell "watching, not in the menu"
        # from "nobody is watching" and fall back only in the second case.
        flag = 2 | (1 if (val == 0 and saw_attract) else 0)
        if flag != published:
            rf.seek(MODE_FLAG_OFF)
            rf.write(struct.pack("<I", flag))
            if published is not None or (flag & 1):
                say(f"mode word {val} -> menu={flag & 1}")
            published = flag
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
