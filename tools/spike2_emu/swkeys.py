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

A THIRD, "pause", is the Pause / F9 key (PAD-204): one press of it, a step
of padsw's pause_req, which padglhost polls and toggles the freeze on. There
is nothing to hold, so nothing to release.

EVERY SWITCH EDGE IS READ BACK (PAD-1306). The guest merges by last edge wins
with no lock, so an edge can be lost (a take collapsing, a write the shim took
as its baseline before the game's first read); the holder reads the merge back
and writes the edge again until the game has it, without holding up the next
line. padsw.Confirmer says how.

EOF RELEASES EVERYTHING STILL HELD. The stuck-switch failure is the same one
item 24 guards against: if the playfield dies mid-flipper, its exit closes
this stdin, and the finally below opens whatever was left closed - the game
must never inherit a phantom held switch from a window that no longer exists.
"""
import os
import sys

import padsw

padsw.set_source('p')   # the playfield's keyboard; PAD_SW_SRC overrides


def parse(line):
    """One stdin line as ('sw', id, level), ('cab', name, level) or
    ('pause', None, None); None for anything that is not a well-formed edge (a
    helper must never die of a malformed line: the playfield keeps writing
    after it)."""
    p = line.split()
    if p == ["pause"]:
        return ("pause", None, None)
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


class Holder:
    """What this helper holds, and the writes behind it: padsw.Confirmer for
    the switches (PAD-1306: each edge is read back off the merge and written
    again until the game has it), the cabinet bytes as they were. padlink.py
    takes its lines through the same holder."""

    def __init__(self, m, on_lost=None):
        self.m = m
        self.sw = padsw.Confirmer(m, on_lost=on_lost)
        self.cab_held = {}

    def handle(self, edge):
        kind, what, val = edge
        if kind == "pause":
            padsw.request_pause(self.m)
        elif kind == "cab":
            padsw.set_cab(self.m, what, val)
            self.cab_held[what] = val
        else:
            self.sw.set(what, val)

    def tick(self):
        self.sw.tick()

    def release(self):
        self.sw.release()
        for name, val in self.cab_held.items():
            if val:
                padsw.set_cab(self.m, name, 0)
        self.cab_held.clear()


def lines(stdin, tick, idle_s=0.004):
    """stdin's lines, with `tick()` run between them while it is quiet (a
    switch waiting on the game is checked every few ms even when no key
    moves). A stand-in stdin with no file behind it is read as it comes."""
    import select
    try:
        fd = stdin.fileno()
    except (AttributeError, OSError, ValueError):
        for line in stdin:
            yield line
            tick()
        return
    buf = b""
    while True:
        r, _w, _x = select.select([fd], [], [], idle_s)
        if r:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield line.decode("ascii", "replace") + "\n"
        tick()
    if buf:
        yield buf.decode("ascii", "replace")


def main():
    m = padsw.open_block()
    if m is None:
        print("no switch block", file=sys.stderr)
        return 1
    # The parent waits for this line before trusting the pipe, so a missing
    # block fails its first key edge into the spawn fallback rather than
    # silently eating every press.
    print("ready", flush=True)
    hold = Holder(m, on_lost=lambda sw, val: print(
        "switch %d never reached %d in the game" % (sw, val), file=sys.stderr, flush=True))
    try:
        for line in lines(sys.stdin, hold.tick):
            edge = parse(line)
            if edge is not None:
                hold.handle(edge)
    finally:
        hold.release()
        m.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
