#!/usr/bin/env python3
"""spare_io.py - the port lines a mode needs for the game's SPARE switch inputs and driver outputs (PAD-826).

    spare_io.py <game_elf> [--port <file>]          # the lines this build gets, and how they were found
    spare_io.py --census <elf dir> <ports dir>      # every port: found / not found, one row each
    spare_io.py --write <elf dir> <ports dir>       # put the lines into every port that has them

What it finds, read from the build's own binary (docs/plans/mode_spare_io.md has the disassembly):

  site coil_frame   the node-bus library's "fire a coil by its board address" wrapper (0x5a9afc on Godzilla
                    Pro 1.16): fire(node, spec) with spec {u8 coil, u8 pulse power, u16 pulse ms, u8 hold
                    power, -, u16 hold ms, u16 x}. It refuses a coil above 8 itself and turns the ms into the
                    board's ticks; the coil service thread calls it for every record. The shape is eight fixed
                    words, so it is found by them: ldrb r3,[r1]; cmp r3,#8; bls; mov r0,#0; bx lr; mov r2,#0;
                    mov r3,r2; b <the frame builder>.
  data sw_struct    the switch service's struct (Godzilla Pro 1.15: 0x7a958c, hwshim's SW_STRUCT): +16 is one
                    160-byte block per node, +20 in it the board's current 64 input bits, +28 a u16 switch id per
                    bit (0 = no switch of the game's there). Found by the service's per-node arithmetic: a
                    movw/movt base B, `add rX, rN, rN, lsl #2` then `lsl rY, rX, #5` (node x 160) and `add rZ, B,
                    #16` within one function. The runtime checks the layout against the game's own switch entries
                    before it reads a bit (pad_mode_runtime.c, spare_sw_check), so a wrong find costs the feature
                    for a run, never a wrong switch.
  data coil_count / coil_table   (only where the port has none yet) the coil table the runtime walks to tell
                    which outputs the game uses: the two movw/movt pairs at the top of the coil request function
                    `site coil_fire` branches to (count first, then the table's pointer), or, with no coil_fire,
                    the record indexing every request function shares (find_coil_table_shape). Checked
                    2026-10-29 against the 46 ports that already named the table: the same pair on all 46.

The ten builds of the OLDER framework (Mando 1.44, Rush 1.18, Turtles Pro 1.58, ...) have the fire wrapper but
neither the switch service's struct nor this coil table; they keep switches and coils their own way, and get
their lines from find_old_* below.
"""
import argparse
import os
import re
import struct
import sys


def load(path):
    """(words {va: u32} over every executable PT_LOAD, data reader) from a 32-bit LE ARM ELF."""
    with open(path, "rb") as f:
        b = f.read()
    if b[:4] != b"\x7fELF" or b[4] != 1 or b[5] != 1:
        raise ValueError("not a 32-bit little-endian ELF: %s" % path)
    phoff, = struct.unpack_from("<I", b, 0x1c)
    phentsize, phnum = struct.unpack_from("<HH", b, 0x2a)
    text = []
    for i in range(phnum):
        p_type, off, va, _pa, filesz, _memsz, flags, _al = struct.unpack_from("<8I", b, phoff + i * phentsize)
        if p_type == 1 and flags & 1:
            text.append((va, b[off:off + filesz]))
    return text


def words(text):
    for va, blob in text:
        n = len(blob) // 4
        yield va, struct.unpack_from("<%dI" % n, blob, 0)


def movw_movt(w):
    """(reg, imm16, kind) for movw/movt, else None."""
    if w & 0x0ff00000 == 0x03000000 and w >> 28 == 0xe:
        return (w >> 12) & 15, ((w >> 4) & 0xf000) | (w & 0xfff), "w"
    if w & 0x0ff00000 == 0x03400000 and w >> 28 == 0xe:
        return (w >> 12) & 15, ((w >> 4) & 0xf000) | (w & 0xfff), "t"
    return None


def pairs(ws, i, lo, hi):
    """{reg: value} of the movw/movt pairs completed in ws[lo..hi) (a movt after its movw)."""
    got, low = {}, {}
    for k in range(max(lo, 0), min(hi, len(ws))):
        m = movw_movt(ws[k])
        if not m:
            continue
        r, imm, kind = m
        if kind == "w":
            low[r] = imm
        elif r in low:
            got[r] = (imm << 16) | low[r]
    return got


#: the wrapper, word by word (None = the branch, any target)
FRAME = (0xe5d13000, 0xe3530008, 0x9a000001, 0xe3a00000, 0xe12fff1e, 0xe3a02000, 0xe1a03002, None)


def find_coil_frame(text):
    hits = []
    for va, ws in words(text):
        for i in range(len(ws) - len(FRAME)):
            if all(want is None or ws[i + k] == want for k, want in enumerate(FRAME)):
                if (ws[i + 7] >> 24) == 0xea:            # b <frame builder>
                    hits.append((va + 4 * i, ws[i], ws[i + 1]))
    return hits


#: the OFF wrapper (`8n 03 4d <coil>`, 0x5a5be8 on Godzilla Pro 1.16): off(node, coil). Its neighbour, the rule
#: fire (`8n 03 40 <coil>`), opens with the same five words; the 0x4d (mov r2,#77) is what tells them apart.
OFF = (0xe3510008, 0xe1a02001, 0x9a000001, 0xe3a00000, 0xe12fff1e, 0xe52de004, 0xe24dd00c, 0xe3a0c000)
OFF_CMD = 0xe3a0204d


def find_coil_off(text):
    hits = []
    for va, ws in words(text):
        for i in range(len(ws) - 16):
            if all(ws[i + k] == want for k, want in enumerate(OFF)) and OFF_CMD in ws[i + 8:i + 16]:
                hits.append((va + 4 * i, ws[i], ws[i + 1]))
    return hits


def find_sw_struct(text):
    """{struct address: hits} from the switch service's node x 160 arithmetic."""
    found = {}
    for va, ws in words(text):
        for i, w in enumerate(ws):
            # add rX, rN, rN, lsl #2  (cond E, ADD reg, shift imm 2 LSL)
            if w & 0xfff00ff0 != 0xe0800100 or ((w >> 16) & 15) != (w & 15):
                continue
            x = (w >> 12) & 15
            for k in range(i + 1, min(i + 10, len(ws))):
                v = ws[k]
                # mov rY, rX, lsl #5
                if v & 0xffff0ff0 == 0xe1a00280 and (v & 15) == x:
                    break
            else:
                continue
            base = pairs(ws, i, i - 16, i + 2)
            # the block's own offsets nearby: +20 (the current bits) and +12 (the previous ones), as immediates
            near = ws[max(i - 16, 0):i + 24]
            if not any(v & 0xfff000ff == 0xe2800014 for v in near) or not any(v & 0xfff000ff == 0xe280000c for v in near):
                continue
            for k in range(i - 16, min(i + 24, len(ws))):
                if k < 0:
                    continue
                v = ws[k]
                # add rZ, B, #16
                if v & 0xfff00fff == 0xe2800010 and ((v >> 16) & 15) in base:
                    a = base[(v >> 16) & 15]
                    found[a] = found.get(a, 0) + 1
    return found


def find_coil_table(text, coil_fire):
    """(count, table) from the coil request function `coil_fire` branches to, or None."""
    for va, ws in words(text):
        if not va <= coil_fire < va + 4 * len(ws):
            continue
        i = (coil_fire - va) // 4
        for k in range(i, i + 12):
            w = ws[k]
            if w >> 24 == 0xea:                           # b <request>
                off = w & 0xffffff
                if off & 0x800000:
                    off -= 0x1000000
                tgt = va + 4 * k + 8 + 4 * off
                j = (tgt - va) // 4
                # the request function: movw/movt ip (count) just before or at its start, then the table
                got = []
                low = {}
                for q in range(j - 2, j + 24):
                    m = movw_movt(ws[q])
                    if not m:
                        continue
                    r, imm, kind = m
                    if kind == "w":
                        low[r] = imm
                    elif r in low:
                        got.append((imm << 16) | low.pop(r))
                if len(got) >= 2:
                    return got[0], got[1]
                return None
    return None


def find_coil_table_shape(text):
    """{(count, table): hits} from the coil records' indexing, for a build whose port names no coil_fire: the
    request functions load the count (movw/movt, then ldr and cmp r0 against it), then the table's pointer
    (movw/movt), and index a 0x68-byte record: add rA, r0, r0, lsl #1; add rC, r0, rA, lsl #2; lsl rC, rC, #3."""
    found = {}
    for va, ws in words(text):
        for i, w in enumerate(ws):
            # add rA, r0, r0, lsl #1
            if w & 0xffff0fff != 0xe0800080:
                continue
            a = (w >> 12) & 15
            ok = False
            for k in range(i + 1, min(i + 8, len(ws))):
                v = ws[k]
                # add rC, r0|rX, rA, lsl #2
                if v & 0xfff00ff0 == 0xe0800100 and (v & 15) == a:
                    c = (v >> 12) & 15
                    for q in range(k + 1, min(k + 8, len(ws))):
                        if ws[q] == (0xe1a00180 | (c << 12) | c):
                            ok = True
                            break
                    break
            if not ok:
                continue
            got, low = [], {}
            for q in range(max(i - 14, 0), i + 6):
                m = movw_movt(ws[q])
                if not m:
                    continue
                r, imm, kind = m
                if kind == "w":
                    low[r] = imm
                elif r in low:
                    got.append((imm << 16) | low.pop(r))
            if len(got) == 2:
                found[tuple(got)] = found.get(tuple(got), 0) + 1
    return found


def port_value(port, kind, name):
    if not port:
        return None
    with open(port) as f:
        for line in f:
            p = line.split()
            if len(p) >= 3 and p[0] == kind and p[1] == name:
                return int(p[2], 0)
    return None


def lines_for(elf, port=None):
    """(lines, notes): the port lines this build gets."""
    text = load(elf)
    out, notes = [], []
    fr = find_coil_frame(text)
    if len(fr) == 1:
        a, w1, w2 = fr[0]
        out.append("site coil_frame            0x%08x 0x%08x 0x%08x" % (a, w1, w2))
    else:
        notes.append("coil_frame: %d matches" % len(fr))
    off = find_coil_off(text)
    if len(off) == 1:
        a, w1, w2 = off[0]
        out.append("site coil_off              0x%08x 0x%08x 0x%08x" % (a, w1, w2))
    else:
        notes.append("coil_off: %d matches" % len(off))
    sw = find_sw_struct(text)
    if len(sw) == 1:
        out.append("data sw_struct             0x%08x" % next(iter(sw)))
    else:
        notes.append("sw_struct: %s" % (", ".join("0x%x x%d" % kv for kv in sorted(sw.items())) or "none"))
    if port and port_value(port, "data", "coil_table") is None:
        cf = port_value(port, "site", "coil_fire")
        tab = find_coil_table(text, cf) if cf else None
        shape = find_coil_table_shape(text)
        if not tab and len(shape) == 1:
            tab = next(iter(shape))
        elif tab and shape and tab not in shape:
            notes.append("coil_table: coil_fire's request says 0x%x/0x%x, the record indexing says %s" % (
                tab[0], tab[1], ", ".join("0x%x/0x%x" % k for k in shape)))
            tab = None
        if tab:
            out.append("data coil_count            0x%08x" % tab[0])
            out.append("data coil_table            0x%08x" % tab[1])
        else:
            notes.append("coil_table: not found")
    return out, notes


HEADER = ("# ---- PAD-826: spare switch inputs and driver outputs (modes/spare_io.py --write, from this build's binary;\n"
          "# docs/plans/mode_spare_io.md). coil_frame = the node-bus fire-by-address wrapper; sw_struct = the switch\n"
          "# service's struct (+16 one 160-byte block per node: +20 its 64 input bits, +28 the switch id per bit)\n")


def write(port, lines):
    with open(port) as f:
        body = f.read()
    body = re.sub(r"\n# ---- PAD-826: spare switch.*?(?=\n(?!site coil_frame|site coil_off|data sw_struct|data coil_count|data coil_table|# )|\Z)",
                  "", body, flags=re.S)
    if not body.endswith("\n"):
        body += "\n"
    body += "\n" + HEADER + "".join(l + "\n" for l in lines)
    with open(port, "w", newline="\n") as f:
        f.write(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("elf", nargs="?")
    ap.add_argument("--port")
    ap.add_argument("--census", nargs=2, metavar=("ELFDIR", "PORTDIR"))
    ap.add_argument("--write", nargs=2, metavar=("ELFDIR", "PORTDIR"))
    a = ap.parse_args()
    if a.census or a.write:
        elfdir, portdir = a.census or a.write
        bad = 0
        for name in sorted(os.listdir(portdir)):
            if not name.endswith(".port"):
                continue
            b = name[:-5]
            elf = os.path.join(elfdir, b + ".elf")
            port = os.path.join(portdir, name)
            if not os.path.exists(elf):
                print("%-30s no binary" % b)
                bad += 1
                continue
            lines, notes = lines_for(elf, port)
            print("%-30s %s%s" % (b, " | ".join(l.split()[1] + "=" + l.split()[2] for l in lines),
                                  ("   !! " + "; ".join(notes)) if notes else ""))
            bad += bool(notes)
            if a.write and lines:
                write(port, lines)
        print("%d port(s) with something not found" % bad)
        return 1 if bad else 0
    if not a.elf:
        ap.error("an ELF, --census or --write")
    lines, notes = lines_for(a.elf, a.port)
    print("\n".join(lines))
    for n in notes:
        print("# not found: " + n, file=sys.stderr)
    return 1 if notes else 0


if __name__ == "__main__":
    sys.exit(main())
