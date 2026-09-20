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

A SECOND KIND OF LINE, "cab <name> <level>", holds one of the boot menu's
buttons BY NAME (padsw.h's cab[], written to the scripts' half). A title's
first run has no switch list yet, so the ids above do not exist for the menu's
flippers or Action; the name always does. Same release-on-EOF discipline.

EOF RELEASES EVERYTHING STILL HELD. The stuck-switch failure is the same one
item 24 guards against: if the playfield dies mid-flipper, its exit closes
this stdin, and the finally below opens whatever was left closed - the game
must never inherit a phantom held switch from a window that no longer exists.
"""
import sys

import padsw

padsw.set_source('p')   # the playfield's keyboard; PAD_SW_SRC overrides


def parse(line):
    """One stdin line as ('sw', id, level) or ('cab', name, level); None for
    anything that is not a well-formed edge (a helper must never die of a
    malformed line: the playfield keeps writing after it)."""
    p = line.split()
    try:
        if len(p) == 3 and p[0] == "cab":
            if p[1] not in padsw.CAB_NAMES:
                return None
            return ("cab", p[1], int(p[2]))
        if len(p) == 2:
            sw, val = int(p[0]), int(p[1])
            if 0 < sw < padsw.MAX_ID:
                return ("sw", sw, val)
    except ValueError:
        pass
    return None


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
    cab_held = {}
    try:
        for line in sys.stdin:
            edge = parse(line)
            if edge is None:
                continue
            kind, what, val = edge
            if kind == "cab":
                padsw.set_cab(m, what, val)
                cab_held[what] = val
            else:
                padsw.take(m, (what,))
                padsw.set_held(m, what, val)
                held[what] = val
    finally:
        for sw, val in held.items():
            if val:
                padsw.set_held(m, sw, 0)
        for name, val in cab_held.items():
            if val:
                padsw.set_cab(m, name, 0)
        m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
