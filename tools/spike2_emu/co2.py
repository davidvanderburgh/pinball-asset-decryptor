#!/usr/bin/env python3
"""co2.py - map node bus COMMAND BYTE -> the function that sends it.

Every per-command function builds the request struct on its own stack:
    buf[0] = 0x80|node   (built with the mvn/lsl#25 + mvn/lsr#25 idiom)
    buf[1] = payload_len
    buf[2] = command byte
    ...
    buf[last] = reply payload length
then calls the exchange wrapper 0x59ebac.  The stack offset of buf[0] differs in
every function, so it is found from the node idiom rather than assumed, and the
command byte is the strb two bytes above it.

The constant a register holds is snapshotted AT THE STORE, not at the end of the
function - an earlier version read the whole function first and mis-named half
the table, because these functions reuse r2/r3 for the reply length after the
command byte is already stored.

Static, so it names commands no run has happened to send yet.
"""
import re, collections

DIS = "/home/david/game.dis"
LO, HI = 0x59d000, 0x5a9000

line_re = re.compile(r"^\s*([0-9a-f]+):\t[0-9a-f ]+\t(\S+)\s*(.*)$")

rows = []
with open(DIS, errors="replace") as f:
    for ln in f:
        m = line_re.match(ln)
        if not m:
            continue
        va = int(m.group(1), 16)
        if LO <= va <= HI:
            rows.append((va, m.group(2), m.group(3).split("@")[0].strip()))

calls = [i for i, (_, op, ar) in enumerate(rows)
         if op.startswith("bl") and "59ebac" in ar]

out = []
for ci in calls:
    lo = max(0, ci - 140)
    start = lo
    for i in range(ci, lo, -1):
        if rows[i][1].startswith("push"):
            start = i
            break
    consts, stores, node_off = {}, {}, None
    for i in range(start, ci + 1):
        va, op, ar = rows[i]
        mi = re.match(r"^(\w+), #(\d+)$", ar)
        if op in ("mov", "mov.w", "movs") and mi:
            consts[mi.group(1)] = int(mi.group(2)) & 0xFF
        elif op in ("mvn", "mvn.w") and mi:
            consts[mi.group(1)] = (~int(mi.group(2))) & 0xFF
        elif op in ("mov", "mov.w") and re.match(r"^(\w+), (\w+)$", ar):
            a, b = re.match(r"^(\w+), (\w+)$", ar).groups()
            if b in consts:
                consts[a] = consts[b]
            else:
                consts.pop(a, None)
        elif re.match(r"^(\w+),", ar) and op not in ("cmp", "cmn", "tst", "teq",
                                                    "strb", "str", "strh", "push"):
            consts.pop(re.match(r"^(\w+),", ar).group(1), None)
        ms = re.match(r"^(\w+), \[sp(?:, #(\d+))?\]$", ar)
        if op == "strb" and ms:
            off = int(ms.group(2) or 0)
            stores[off] = consts.get(ms.group(1))
            if "lsr #25" in rows[i - 1][2] or "lsr #25" in rows[i - 2][2]:
                node_off = off
        if op in ("mvn", "mvn.w") and "lsr #25" in ar:
            nreg = ar.split(",")[0]
            for j in range(i, min(ci + 1, i + 24)):
                mj = re.match(r"^" + nreg + r", \[sp(?:, #(\d+))?\]$", rows[j][2])
                if rows[j][1] == "strb" and mj:
                    node_off = int(mj.group(1) or 0)
                    break
    if node_off is None:
        out.append(("--", rows[start][0], rows[ci][0], "unaddressed"))
        continue
    cv = stores.get(node_off + 2)
    lv = stores.get(node_off + 1)
    out.append(("%02x" % cv if cv is not None else "??",
                rows[start][0], rows[ci][0],
                "payload_len=%s" % (lv if lv is not None else "?")))

for k, s, c, n in sorted(out):
    print("cmd %s  fn 0x%06x  (bl at 0x%06x)  %s" % (k, s, c, n))
