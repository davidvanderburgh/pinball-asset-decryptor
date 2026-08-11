#!/usr/bin/env python3
"""swkeys.py - a stdin-driven switch holder: the playfield keyboard's writer.

REMAINING item 39. David: "the keyboard inputs are not working unless the
emulator window is focused. it should work with the virtual playfield
focused." The playfield is a Windows Tk process, and its existing write path
spawns wsl.exe PER ACTION (~80-200 ms, measured in item 24) - fine for a
mouse hold, hopeless for a flipper key. This is the fix's other half: the
playfield spawns ONE of these for the whole session and writes "<id> <level>"
lines down its stdin, so a key edge costs a pipe write instead of a process.

It is deliberately nothing but swhold.py in a loop - same padsw module, same
take-then-set discipline, same script region. The rig's one-writer-per-region
rule holds: everything host-side still funnels through padsw's script array,
and the guest merges by last edge wins exactly as before.

EOF RELEASES EVERYTHING STILL HELD. The stuck-switch failure is the same one
item 24 guards against: if the playfield dies mid-flipper, its exit closes
this stdin, and the finally below opens whatever was left closed - the game
must never inherit a phantom held switch from a window that no longer exists.
"""
import sys

import padsw

padsw.set_source('p')   # the playfield's keyboard; PAD_SW_SRC overrides


def main():
    m = padsw.open_block()
    if m is None:
        print("no switch block", file=sys.stderr)
        return 1
    # The parent waits for this line before trusting the pipe, so a missing
    # block fails its first key edge into the spawn fallback rather than
    # silently eating every press.
    print("ready", flush=True)
    held = {}
    try:
        for line in sys.stdin:
            p = line.split()
            if len(p) != 2:
                continue
            try:
                sw, val = int(p[0]), int(p[1])
            except ValueError:
                continue
            if not 0 < sw < padsw.MAX_ID:
                continue
            padsw.take(m, (sw,))
            padsw.set_held(m, sw, val)
            held[sw] = val
    finally:
        for sw, val in held.items():
            if val:
                padsw.set_held(m, sw, 0)
        m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
