#!/usr/bin/env python3
"""ledreplay.py <log> [<log> ...] - replay the shim's LED accept path over a
captured node bus log, and say WHY a title decodes nothing.

    python3 ledreplay.py /var/tmp/item43_*.log
    python3 ledreplay.py ~/i50_gz.log --frames

WHY THIS EXISTS. A title whose virtual playfield stays dark gives you two
numbers out of the padled block - `decoded` and `skipped` - and they are the
same two numbers for several completely different faults:

  * the lamp commands never appear on the wire at all          -> 0 / 0
  * they appear on a board the decoder does not read            -> 0 / 0
  * they appear on the right board but the per-LED ENUMERATION
    never did, so every frame fails its index check             -> 0 / >0
  * they appear and decode                                      -> >0 / 0

Only the third is visible from the counters alone, and telling the first from
the second needs the frames. This walks a capture and reports each stage, so a
dark title can be diagnosed at the DESK from a log somebody already took,
instead of costing a run. That distinction is the whole reason star_wars_le was
settled without booting it: 619 lamp frames land on its insert nodes and decode
to nothing, because it never sends the 6-byte enumeration.

WHAT IT MODELS, and where it stops. The gates below are hwshim.c's, read off
led_publish() (entry guard, the node gate, the enumeration branch, the command
gate) - those decide whether a frame is even a candidate, and they are what
this tool is for. It then classifies the accepted commands by SHAPE far enough
to say whether the index checks would pass; it does NOT reproduce every payload
layout byte for byte, and it does not write a padled block. If you need the
exact decoded levels, that is leddecode.py's job on the same log.

VALIDATED ON A LABELLED POSITIVE, which is this rig's standing rule for a new
instrument. Against C:/tmp/item27/led_trace_1d.log (godzilla_pro, 34530 frames)
it derives the enumeration as node 1: 6 indices, node 8: 56, node 9: 71 - which
is EXACTLY what the real shim prints as [ledenum] on that title. The
enumeration half is therefore faithful, and that is the half every "why is this
title dark" question turns on.

THE SHAPE HALF IS APPROXIMATE AND ITS SKIP COUNT IS INFLATED. On that same
capture it reports 510 would-decode against 749 would-skip, because the a6
bitmap (hwshim.c:6277-6303) and the long a2 layouts are not reproduced here.
Read "would decode" as a floor and "would skip" as a ceiling. Nothing in the
verdicts below rests on the split - they turn on whether lamp commands ARRIVE
and whether the enumeration RAN, both of which are exact.

THE FRAME FORMAT it reads is the rig's own log lines, either shape:

    [nb] TX len=6 81038501f600
    [nbts] t=8123 node=1 cmd=85 len=6 81038501f600

PAD_NB_TRACE=1 produces the second and is unbudgeted; the plain [nb] TX lines
are BUDGETED (nb_budget_init, hwshim.c:2685), so a log without the trace
carries only the first ~162 frames of a run - all boot handshake - and an
absence of lamp commands in one of those proves nothing at all. This tool says
so in its output rather than letting the silence be read as a result.
"""
import collections
import glob
import os
import re
import sys

#: hwshim.c:5953 led_insert_node() - the ONLY definition in C, and it is
#: godzilla's board numbering. leddecode.py:52 is its twin.
INSERT_NODES = (1, 8, 9)

#: hwshim.c:6139-6140 / leddecode.py:44. A frame whose command is not one of
#: these returns before anything is counted - neither decoded nor skipped.
LAMP_CMDS = (0x97, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xB4, 0xB5)

#: hwshim.c:6131-6138. EXACTLY six bytes, index at p[3], on an insert node.
#: Nothing else populates led_known[], and without it every index check fails.
ENUM_CMDS = (0x84, 0x85)
ENUM_LEN = 6

#: [nbts] t=8123 node=1 cmd=85 len=6 81038501f600 - PAD_NB_TRACE's line. The
#: node/cmd fields are the SHIM's own parse; the trailing hex is the frame, and
#: this reads the hex rather than the fields so the replay is independent of
#: them (node=-1 on a broadcast frame is the shim saying "no node byte").
_TS = re.compile(r"\[nbts\][^0-9a-fA-F]*t=\d+\s+node=-?\d+\s+cmd=[0-9a-fA-F]+"
                 r"\s+len=\d+\s+([0-9a-fA-F]+)\s*$")
#: [nb] TX len=6 81038501f600 - the budgeted line.
_TX = re.compile(r"\[nb\]\s+TX\s+len=\d+\s+([0-9a-fA-F]+)\s*$")


def frames(path):
    """(ts_or_None, bytes) for every TX frame in a rig log."""
    out = []
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("latin-1").rstrip()
            if "TX-reply" in line:
                continue        # replies are not writes; led_publish never sees them
            m = _TS.search(line) or _TX.search(line)
            if not m:
                continue
            h = m.group(1)
            if len(h) % 2:
                continue
            try:
                out.append((None, bytes.fromhex(h)))
            except ValueError:
                pass
    return out


def replay(fr):
    """Walk the accept path. Returns a dict of stage counts and evidence."""
    st = dict(total=len(fr), short=0, broadcast=0, lamp_any_node=0,
              off_node=0, enum=0, lamp_on_insert=0, would_decode=0,
              would_skip=0)
    known = collections.defaultdict(set)        # node -> {index}
    lamp_by_node = collections.Counter()
    lamp_examples = {}
    enum_by_node = collections.Counter()
    title_cmds = collections.Counter()

    for _ts, p in fr:
        n = len(p)
        if n < 5:
            st["short"] += 1
            continue
        if not (p[0] & 0x80):
            st["broadcast"] += 1
            continue
        node, cmd = p[0] & 0x3F, p[2]
        title_cmds[cmd] += 1

        # hwshim.c:6086-6118 - announced BEFORE the node gate, deliberately,
        # so a title whose insert boards sit elsewhere still trips it.
        if cmd in LAMP_CMDS:
            st["lamp_any_node"] += 1

        if node not in INSERT_NODES:
            if cmd in LAMP_CMDS:
                st["off_node"] += 1
            continue

        if n == ENUM_LEN and cmd in ENUM_CMDS:
            if p[3] < 96:
                known[node].add(p[3])
            st["enum"] += 1
            enum_by_node[node] += 1
            continue

        if cmd not in LAMP_CMDS:
            continue

        st["lamp_on_insert"] += 1
        lamp_by_node[(node, cmd)] += 1
        lamp_examples.setdefault((node, cmd), p.hex())

        # The index checks all reduce to "is this byte an announced index on
        # this node" (hwshim.c:6168-6170, 6209-6211, 6292, 6386, 6414-6416).
        # With led_known empty they cannot pass, whatever the payload is.
        body, blen = p[3:-2], n - 5
        if not known[node]:
            st["would_skip"] += 1
            continue
        if cmd in (0xB4, 0xB5) and blen in (3, 4):
            s0, e7 = body[0], body[blen - 2]
            if (e7 & 0x80) and (e7 & 0x7F) >= s0 \
                    and s0 in known[node] and (e7 & 0x7F) in known[node]:
                st["would_decode"] += 1
            else:
                st["would_skip"] += 1
            continue
        ok = False
        for extra in (1, 2, 3):
            if blen >= extra + 2 and (blen - extra) % 2 == 0:
                cnt = (blen - extra) // 2
                if cnt and all(body[i] < 96 and body[i] in known[node]
                               for i in range(cnt)):
                    ok = True
                    break
        st["would_decode" if ok else "would_skip"] += 1

    return st, known, lamp_by_node, lamp_examples, enum_by_node, title_cmds


def verdict(st, known):
    """The one sentence a caller actually wants."""
    if st["total"] == 0:
        return "NO FRAMES IN THIS LOG - it carries no node bus lines at all."
    if st["lamp_any_node"] == 0:
        return ("NO LAMP COMMAND ANYWHERE, on any node. Either the title never "
                "drove a lamp during this capture, or the capture is the "
                "BUDGETED [nb] kind and stopped before it did. Re-run with "
                "PAD_NB_TRACE=1 before concluding the title sends none.")
    if st["lamp_on_insert"] == 0:
        return ("LAMP COMMANDS EXIST BUT NOT ON NODES 1/8/9 (%d of them are on "
                "other boards). The decoder's node gate is godzilla's "
                "numbering; this title puts its lamps elsewhere."
                % st["off_node"])
    if not any(known.values()):
        return ("LAMP COMMANDS LAND ON THE INSERT NODES AND NOTHING CAN DECODE "
                "THEM: the 6-byte 0x84/0x85 enumeration never ran, so "
                "led_known is empty and every index check fails. This is "
                "star_wars_le's fault exactly.")
    if st["would_decode"] == 0:
        return ("ENUMERATION RAN AND STILL NOTHING DECODES - the payload shapes "
                "do not match. This is the case that would need new decoder "
                "work; read the frames below.")
    return ("DECODES: %d frames would land, %d would be skipped."
            % (st["would_decode"], st["would_skip"]))


def main(argv):
    paths = []
    show_frames = "--frames" in argv
    for a in argv[1:]:
        if a.startswith("--"):
            continue
        paths.extend(sorted(glob.glob(a)) or [a])
    if not paths:
        print(__doc__)
        return 1

    for path in paths:
        if not os.path.exists(path):
            print("%s: no such file" % path)
            continue
        fr = frames(path)
        st, known, lamp, ex, enum, cmds = replay(fr)
        print("=" * 72)
        print("%s  (%d frames)" % (path, st["total"]))
        title = None
        try:
            with open(path, "rb") as f:
                for raw in f.read(4096).splitlines():
                    s = raw.decode("latin-1")
                    if "[run] title:" in s:
                        title = s.split("title:", 1)[1].strip()
                        break
        except OSError:
            pass
        print("  title line        : %s" % (title or "(none in first 4 KB)"))
        print("  dropped early     : %d too short, %d broadcast (no node byte)"
              % (st["short"], st["broadcast"]))
        print("  lamp cmds any node: %d   of those OFF nodes 1/8/9: %d"
              % (st["lamp_any_node"], st["off_node"]))
        print("  enumeration frames: %d   -> %s"
              % (st["enum"],
                 ", ".join("node %d: %d indices" % (n, len(v))
                           for n, v in sorted(known.items())) or "NOTHING"))
        print("  lamp cmds on 1/8/9: %d" % st["lamp_on_insert"])
        for (node, cmd), c in sorted(lamp.items()):
            print("      node %-2d cmd %02x  x%-6d  %s"
                  % (node, cmd, c, ex[(node, cmd)]))
        print("  would decode      : %d      would skip: %d"
              % (st["would_decode"], st["would_skip"]))
        print()
        print("  VERDICT: %s" % verdict(st, known))
        if show_frames:
            print("  every command byte seen: %s"
                  % " ".join("%02x" % c for c in sorted(cmds)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
