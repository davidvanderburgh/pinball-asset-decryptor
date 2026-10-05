#!/usr/bin/env python3
"""coildecode.py <log> - coil traffic on the node bus, decoded and named.

Point it at a run captured with PAD_COIL_PROBE=1 (see hwshim.c). It needs no
PAD_NB_LOG: the probe writes one line per CHANGED frame on nodes 8 and 9, which
is a few thousand lines for a whole run instead of a few million.

THE FRAME (every field named from the game's serialiser in PAD-381 - see
coil_drive_note() in hwshim.c for the addresses)

    88 0b 40 <IDX> <PULSE PWR> <PULSE T lo hi> <HOLD PWR> <HOLD T lo hi> <X lo hi> <cksum> 00

`cmd 0x40` addresses ONE COIL BY INDEX and the index is the device table's own.
Node 8 carries 0..8 and node 9 carries 6 - exactly the ten playfield coils the
table lists under groups 6 and 7, in the same order. The two powers are 0..255:
the AUTO PLUNGER pulses at 0x96 where everything else is 0xff, and the service
menu's "Trough Eject Power 225 (88%)" is the same scale. The two times are in
BOARD TICKS, ms * tps / 1000, tps being what the board claims at [8..9] of its
0xfe identity (the rig: NB_HWID_DEFAULT, 100, or PAD_NB_HWID). X is sent as
pulse power * 256 / X ticks; its use is not established. The checksum is the
two's complement of the sum of the preceding bytes.

OFF is a different frame, `8n 03 4d <IDX> <cksum> 00`, and `8n 03 40 <IDX>
<cksum> 00` (the short 40) fires a coil by its cmd 41 rule.

HOW IT WAS PINNED DOWN, and this is the part worth keeping.

COILS CANNOT BE WATCHED CASUALLY. 48V is interlocked to the coin door and the
game says so on screen: "48V DISABLED / CLOSE COIN DOOR OR PULL INTERLOCK SWITCH
TO RESTORE POWER". The door has to be CLOSED for a coil to fire - and the
service buttons are locked out while it is closed, so the obvious plan of
walking into Diagnostics and running a coil test is a contradiction. Two earlier
sessions were lost to menu navigation; a third would have been.

THE GAME WILL LABEL THE EXPERIMENT ITSELF IF ASKED. Close the door, open the
trough switches so the balls appear to be gone, press Start. The game puts up
LOCATING PINBALLS and runs a ball search on an 8.3 s cycle:

    88 0b 40 03 ff 00 00 ff 00 00 00 00 2c 00     LEFT SLINGSHOT
    88 0b 40 02 ff 00 00 ff 00 00 00 00 2d 00     RIGHT SLINGSHOT
    88 0b 40 07 ff 00 00 ff 00 00 00 00 28 00     POP BUMPER
    88 0b 40 04 96 00 00 00 00 00 00 00 93 00     AUTO PLUNGER, at 150/255
    88 0b 40 08 ff 00 00 00 00 00 00 00 26 00     RIGHT SCOOP

Indices 2, 3, 4, 7, 8 are exactly the coils a ball search fires, and exactly not
the three flippers (0, 5, 6) or the trough eject (1). Five hits and three
correct absences, against a table derived from the binary months earlier.

BYTE 7 IS THE HOLD POWER. It was read for months as "undecoded - on/off, hold
power or board self-fire", because those captures were all this tool had. The
serialiser settled it (PAD-381): 0xff on the slingshots and pop bumper is a full
second phase, 0 on the plunger and scoop is none. Every time in these captures
reads 0 because the rig then claimed a tick rate of 1 (NB_HWID_DEFAULT before
2026-08-26), and ms * 1 / 1000 is 0 for anything under a second.
"""
import collections
import re
import sys

import coilmap
import devicexy
import gameinfo

LINE = re.compile(r"\[coil\] node (\d+) cmd ([0-9a-f]{2}) ([0-9a-f]+)")
STAMP = re.compile(r"\[(\d+\.\d+)\]")

#: Device-table group -> node, the lookup ledio.py verified against the wire.
#: coilmap.py owns it; this alias keeps the name that the text above uses.
GROUP_NODE = coilmap.GROUP_NODE

COIL_CMD = 0x40
COIL_LEN = 14
OFF_CMD = 0x4d
#: the rig's boards claim this tick rate unless PAD_NB_HWID says otherwise
RIG_TPS = 100


def checksum_ok(frame):
    """Every byte up to and including the checksum sums to 0 mod 256."""
    return len(frame) >= 3 and sum(frame[:-1]) & 0xFF == 0


def decode(frame, tps=RIG_TPS):
    """One coil command as a dict, or None - the twin of coil_drive_decode()
    in hwshim.c. kind is "fire", "off" or "rule"; times are given in ticks
    and in ms at `tps` ticks per second."""
    b = bytes(frame)
    if len(b) < 6 or not b[0] & 0x80 or len(b) != b[1] + 3 or not checksum_ok(b):
        return None
    d = {"node": b[0] & 0x3F, "index": b[3]}
    if b[2] == COIL_CMD and b[1] == 0x0B:
        pt = b[5] | b[6] << 8
        ht = b[8] | b[9] << 8
        d.update(kind="fire", pulse_pwr=b[4], pulse_t=pt, hold_pwr=b[7], hold_t=ht,
                 x=b[10] | b[11] << 8,
                 pulse_ms=pt * 1000 // tps if tps else 0,
                 hold_ms=ht * 1000 // tps if tps else 0)
        if not b[4] and not b[7]:
            d["kind"] = "off"
        return d
    if b[2] == COIL_CMD and b[1] == 0x03:
        d["kind"] = "rule"
        return d
    if b[2] == OFF_CMD and b[1] == 0x03:
        d["kind"] = "off"
        return d
    return None


def read(path):
    """[(t, node, cmd, frame)] from a PAD_COIL_PROBE capture."""
    out = []
    for raw in open(path, "rb"):
        s = raw.decode("latin-1")
        m = LINE.search(s)
        if not m:
            continue
        st = STAMP.findall(s[:m.start()])
        h = m.group(3)
        if len(h) % 2:
            h = h[:-1]
        out.append((float(st[-1]) if st else 0.0, int(m.group(1)),
                    int(m.group(2), 16), bytes.fromhex(h)))
    return out


def coil_names():
    """{(node, index): name} for every coil in the device table.

    The group -> node map is DERIVED per title (coilmap.group_node): the groups
    shift between titles, so the constant above is only the fallback. Reading it
    directly here is what had this tool naming dungeons_and_dragons_le's node-8
    coils as node 9.

    THIS tool has no device_xy.txt path at all - devicexy.load() reads the
    ELF of whatever title is active, the same "active" gameinfo already
    resolves for it - so asking gameinfo for that title's node_ident.txt
    HERE, explicitly, is correct. coilmap.py itself no longer guesses this on
    its own; see _playfield_nodes()'s docstring for the bug that fixed.
    """
    d, cs = devicexy.load()
    recs = devicexy.records(d, cs)
    coils = [r for r in recs if r["kind"] == "coil"]
    try:
        nodedir = gameinfo.table("node_ident.txt")
    except Exception:                          # noqa: BLE001 - never fatal here
        nodedir = None
    try:
        swlist = coilmap._maybe_lines(gameinfo.table("switch_list.txt"))
    except Exception:                          # noqa: BLE001 - never fatal here
        swlist = None
    # THE WHOLE RECORD SET, not just the coils (item 53): both derivations read
    # rows this tool does not otherwise care about - the switch names the
    # running game can confirm, and the connector column, which is "-" on every
    # coil row on this disk. Passing coils alone left the derivation blind and
    # silently back on godzilla's constant, which is the fault this function's
    # docstring already describes one layer up.
    mapping = coilmap.group_node(coils, nodedir, dev_rows=recs,
                                 switch_lines=swlist)
    out = {}
    for r in coils:
        node = mapping.get(r["group"])
        if node is not None:
            out[(node, r["index"])] = r["name"]
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    frames = read(sys.argv[1])
    names = coil_names()
    print("%d probe frames, %d coils in the device table\n"
          % (len(frames), len(names)))

    fires = collections.Counter()
    first = {}
    events = []
    for t, node, cmd, b in frames:
        if cmd != COIL_CMD or len(b) != COIL_LEN:
            continue
        key = (node, b[3])
        if key not in first:
            first[key] = t                       # the boot configuration record
            continue
        fires[key] += 1
        events.append((t, key, decode(b)))

    print("%-8s %-6s %-18s %8s %8s" % ("node", "index", "name", "config@", "events"))
    for key in sorted(set(first) | set(fires)):
        node, idx = key
        print("%-8d %-6d %-18s %8.1f %8d"
              % (node, idx, names.get(key, "(not in the table)"),
                 first.get(key, -1), fires[key]))

    if events:
        print("\nfirst 20 events (times at the rig's %d ticks/s):" % RIG_TPS)
        for t, (node, idx), d in events[:20]:
            if d is None:
                print("  %8.3f  node %d index %-2d %-18s (bad checksum)"
                      % (t, node, idx, names.get((node, idx), "?")))
                continue
            print("  %8.3f  node %d index %-2d %-18s pulse %3d for %4d ms, hold %3d for %5d ms"
                  % (t, node, idx, names.get((node, idx), "?"), d["pulse_pwr"],
                     d["pulse_ms"], d["hold_pwr"], d["hold_ms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
