#!/usr/bin/env python3
"""Read, write and snapshot the running game's memory from the HOST side.

WHY THIS IS A HOST TOOL AND NOT A SHIM FUNCTION, which looks backwards and is
not: the guest cannot read its own globals. The shim's in-guest load of
0x650744 returns 0 in every state while a read of the same address in the same
process through /proc/<pid>/mem returns the true enum - one pid, 21 threads, no
fork, guest_base 0, the disassembly showing a literal load. Unexplained, and
worked around rather than waited on (modewatch.py publishes the host read into
the padgl ring for the shim to use). Every memory question in this rig therefore
goes through /proc.

WHAT IT IS FOR. Item 43 spent a week asking "what does the game read to decide
the service menu's picture?" and answering it with theories. This answers it
with causation instead: snapshot the two states, diff them, then POKE a
band-state word to its dots-state value and look at the screen. A picture that
flips names the cause; 273 words that do nothing name 273 consequences. Proven
to work 2026-08-12 - poking 0x6046e0 drove the game straight out of its service
menu, which is a write landing in a running ARM guest from Windows-side Python.

  python3 guestmem.py snap  <outfile>
  python3 guestmem.py read  0x650744 0x663958
  python3 guestmem.py poke  0x69133c=1 0x6046e0=0
  python3 guestmem.py zero  0x64bb2c:0x64bb88      (inclusive word range)

Every poke reads back and says whether it stuck: a write that silently failed
looks exactly like a poke that changed nothing on screen, and those are opposite
conclusions.

The window snapshotted is 0x5f8000..0x6e8000, the static-globals region where
the app-mode word (0x650744) and the in-service-menu boolean (0x663958) both
live. NOTE THE LIMIT, paid for on 2026-08-12: item 43's decision variable is NOT
in this window - every non-pointer difference between the two states was poked
at once and the picture did not move - so the thing that chooses dots-vs-video
lives in a heap object, where a cross-run diff cannot follow it because the
addresses move. A future pass wanting the heap needs a different instrument.
"""
import os
import struct
import subprocess
import sys

LO, HI = 0x5F8000, 0x6E8000


def guest_pid():
    """The qemu-user process running the game. Same patterns as padpath.sh's
    pad_guest_up, so this agrees with the rest of the rig about what is up."""
    for cmd in (["pgrep", "-x", "game"], ["pgrep", "-f", "arm-binfmt|qemu-arm"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout.split()
        except OSError:
            continue
        for p in out:
            if p.isdigit() and os.path.exists(f"/proc/{p}/mem"):
                return int(p)
    return None


def opened(write=False):
    pid = guest_pid()
    if not pid:
        print("no guest running")
        sys.exit(2)
    try:
        return open(f"/proc/{pid}/mem", "r+b" if write else "rb", buffering=0)
    except OSError as e:
        print(f"cannot open guest memory: {e}")
        sys.exit(3)


def cmd_snap(args):
    if not args:
        print("usage: guestmem.py snap <outfile>")
        return 2
    with opened() as m:
        m.seek(LO)
        buf = m.read(HI - LO)
    if len(buf) != HI - LO:
        print(f"short read: {len(buf)} of {HI - LO}")
        return 3
    d = os.path.dirname(args[0])
    if d:
        os.makedirs(d, exist_ok=True)
    with open(args[0], "wb") as f:
        f.write(buf)
    # Always stamp which state the snapshot is FROM. A mislabelled snapshot is
    # the one way a differential scan lies to you, and it lies convincingly.
    mode = struct.unpack_from("<I", buf, 0x650744 - LO)[0]
    inmenu = struct.unpack_from("<I", buf, 0x663958 - LO)[0]
    print(f"{args[0]}  {len(buf)} bytes  mode={mode} inmenu={inmenu}")
    return 0


def cmd_read(args):
    with opened() as m:
        for a in args:
            addr = int(a, 16)
            m.seek(addr)
            print(f"0x{addr:x} = {struct.unpack('<I', m.read(4))[0]}")
    return 0


def do_writes(m, pairs):
    for addr, val in pairs:
        m.seek(addr)
        before = struct.unpack("<I", m.read(4))[0]
        try:
            m.seek(addr)
            m.write(struct.pack("<I", val))
        except OSError as e:
            print(f"0x{addr:x}  WRITE FAILED: {e}")
            continue
        m.seek(addr)
        after = struct.unpack("<I", m.read(4))[0]
        print(f"0x{addr:x}  {before} -> {after}"
              f"  ({'ok' if after == val else 'DID NOT STICK'})")


def cmd_poke(args):
    pairs = []
    for a in args:
        addr, val = a.split("=")
        pairs.append((int(addr, 16), int(val, 0)))
    with opened(True) as m:
        do_writes(m, pairs)
    return 0


def cmd_zero(args):
    pairs = []
    for a in args:
        lo, hi = (int(x, 16) for x in a.split(":"))
        pairs += [(x, 0) for x in range(lo, hi + 1, 4)]
    with opened(True) as m:
        do_writes(m, pairs)
    return 0


CMDS = {"snap": cmd_snap, "read": cmd_read, "poke": cmd_poke, "zero": cmd_zero}

if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
    print(__doc__)
    sys.exit(2)
sys.exit(CMDS[sys.argv[1]](sys.argv[2:]))
