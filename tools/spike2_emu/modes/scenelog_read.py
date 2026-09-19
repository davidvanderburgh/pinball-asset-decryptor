#!/usr/bin/env python3
"""Decode a scenelog.so ring dump (item 131): the reads a scene.radium load made, in order.

    scenelog_read.py <scenelog.N.bin>                       summary per archive
    scenelog_read.py <dump> --file <scene.radium>           find which archive read that file,
                                                            and at what file offset each read landed
    ... --last 200                                          the final reads of that archive
    ... --window 0x50b000 0x50c000                          the reads inside a file range

An archive's reads are contiguous in its file, so a read's file offset is a running
sum of sizes plus one base. The base is found by matching the captured bytes (the
first 8 of each read up to 64 KB) against the file, and every read is then checked
against the file at its offset: a mismatch means a read path the recorder does not
hook, or a seek.
"""
import argparse
import struct
import sys

HDR = struct.Struct("<4s6I16s")
ENT = struct.Struct("<6I8s")
KIND = {1: "u8", 2: "u16", 4: "u32", 8: "u64", 0x10: "SIZETAG", 0x20: "RESIZE"}
FILLED = 0x100


def load(path):
    raw = open(path, "rb").read()
    magic, version, ring, head, seq, a, b, why = HDR.unpack_from(raw, 0)
    if magic != b"SCNL" or version != 1:
        sys.exit("not a scenelog v1 dump: %r %r" % (magic, version))
    body = raw[HDR.size:]
    ents = []
    for i in range(min(ring, len(body) // ENT.size)):
        arch, size, lr, dst, kind, sq, val = ENT.unpack_from(body, i * ENT.size)
        if sq:
            ents.append(dict(arch=arch, size=size, lr=lr, dst=dst, kind=kind & 0xff,
                             filled=bool(kind & FILLED), seq=sq, val=val))
    ents.sort(key=lambda e: e["seq"])
    meta = dict(ring=ring, head=head, seq=seq, a=a, b=b, why=why.rstrip(b"\0").decode("latin1"))
    return meta, ents


FILE_START_LR = 0x26AB78     # the archive's first read of a file: its 1-byte endianness flag


def streams_of(ents):
    """{(arch, n): reads} - an archive's reads split at every file start, because one
    archive object at one address is reused for file after file during boot."""
    out, seg = {}, {}
    for e in ents:
        if e["kind"] not in (1, 2, 4, 8):
            continue
        if e["kind"] == 1 and e["size"] == 1 and e["lr"] == FILE_START_LR:
            seg[e["arch"]] = seg.get(e["arch"], 0) + 1
        out.setdefault((e["arch"], seg.get(e["arch"], 0)), []).append(e)
    for key, reads in out.items():
        rel = 0
        for i, e in enumerate(reads):
            reads[i] = dict(e, rel=rel)
            rel += e["size"]
    return out


def reads_of(ents, arch):
    """All of one archive's reads as a single stream (the original behaviour)."""
    out, rel = [], 0
    for e in ents:
        if e["arch"] == arch and e["kind"] in (1, 2, 4, 8):
            e = dict(e, rel=rel)
            rel += e["size"]
            out.append(e)
    return out


def captured(e):
    n = min(e["size"], 8)
    return e["val"][:n] if e["filled"] and e["size"] <= 65536 and n else None


def align(reads, data):
    """The base that makes the most captured reads match the file; (base, matched, checked)."""
    anchors = [e for e in reads if captured(e) is not None]
    if not anchors:
        return None, 0, 0
    # a contiguous run of small reads gives a distinctive needle
    best = (None, 0, len(anchors))
    for start in range(0, min(len(anchors), 4000), 97):
        run, j = b"", start
        rel0 = anchors[start]["rel"]
        while j < len(anchors) and anchors[j]["size"] <= 8 and anchors[j]["rel"] == rel0 + len(run):
            run += captured(anchors[j])
            j += 1
            if len(run) >= 48:
                break
        if len(run) < 24:
            continue
        pos = data.find(run)
        cands = 0
        while pos >= 0 and cands < 8:
            base = pos - rel0
            hit = sum(1 for e in anchors
                      if 0 <= base + e["rel"] and data[base + e["rel"]:base + e["rel"] + len(captured(e))] == captured(e))
            if hit > best[1]:
                best = (base, hit, len(anchors))
            pos = data.find(run, pos + 1)
            cands += 1
        if best[1] == len(anchors):
            break
    return best


def line(e, base, data):
    if e["kind"] in (1, 2, 4, 8):
        off = base + e["rel"] if base is not None else None
        cap = captured(e)
        v = ""
        if cap is not None:
            v = cap.hex()
            if e["size"] in (4, 8) and len(cap) == e["size"]:
                v += " =%d" % int.from_bytes(cap, "little")
            if off is not None:
                v += "" if data[off:off + len(cap)] == cap else "   *** != file ***"
        where = "0x%07x" % off if off is not None else "rel %d" % e["rel"]
        return "%9d  %s  %-4s %6d B  lr 0x%06x  %s" % (e["seq"], where, KIND[e["kind"]], e["size"], e["lr"], v)
    if e["kind"] == 0x10:
        return "%9d  %-9s SIZETAG          lr 0x%06x  (size for the caller)" % (e["seq"], "", e["lr"])
    return "%9d  %-9s RESIZE n=%-8d  lr 0x%06x  vec 0x%08x" % (e["seq"], "", e["size"], e["lr"], e["dst"])


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dump")
    ap.add_argument("--file")
    ap.add_argument("--arch", type=lambda s: int(s, 0))
    ap.add_argument("--last", type=int, default=0)
    ap.add_argument("--window", nargs=2, type=lambda s: int(s, 0))
    args = ap.parse_args(argv)

    meta, ents = load(args.dump)
    print("dump: %s  a=0x%x b=0x%x  ring %d  entries %d  seq %d..%d"
          % (meta["why"], meta["a"], meta["b"], meta["ring"], len(ents),
             ents[0]["seq"] if ents else 0, ents[-1]["seq"] if ents else 0))
    per = {}
    for e in ents:
        if e["kind"] in (1, 2, 4, 8):
            c = per.setdefault(e["arch"], [0, 0, e["seq"], 0])
            c[0] += 1
            c[1] += e["size"]
            c[3] = e["seq"]
    print("archives (reads, bytes, first..last seq):")
    for a, (n, b, s0, s1) in sorted(per.items(), key=lambda kv: kv[1][3]):
        print("  0x%08x  %8d reads  %10d B  seq %d..%d" % (a, n, b, s0, s1))

    if not args.file:
        return 0
    data = open(args.file, "rb").read()
    arch, base = args.arch, None
    if arch is None:
        # Scored per FILE stream. A stream that starts with the file-start read must sit
        # at base 0 and cover the file; the match fraction alone would let a short stream
        # of zeros "align" anywhere.
        scored = []
        for key, reads in streams_of(ents).items():
            if len(reads) < 50:
                continue
            b0, hit, chk = align(reads, data)
            starts = reads[0]["lr"] == FILE_START_LR
            fits = b0 is not None and b0 + reads[-1]["rel"] + reads[-1]["size"] <= len(data)
            if starts and b0 != 0:
                fits = False
            frac = hit / chk if chk and fits else 0
            scored.append((frac, starts, len(reads), hit, chk, key, b0))
        scored.sort(key=lambda t: (t[0] >= 0.95, t[1], t[2], t[0]), reverse=True)
        for frac, starts, n, hit, chk, key, b0 in scored[:6]:
            print("  align 0x%08x/%d: %d reads, base %s, %d/%d captured reads match%s"
                  % (key[0], key[1], n, b0, hit, chk, "  (starts at the file start)" if starts else ""))
        if not scored or scored[0][0] < 0.95:
            print("no stream read this file")
            return 1
        frac, _st, _n, _h, _c, key, base = scored[0]
        arch, reads = key[0], streams_of(ents)[key]
    else:
        reads = reads_of(ents, arch)
        base = align(reads, data)[0]
    end = base + reads[-1]["rel"] + reads[-1]["size"] if base is not None else None
    print("\narchive 0x%08x: %d reads, file 0x%x..0x%x of 0x%x"
          % (arch, len(reads), base + reads[0]["rel"], end, len(data)))

    lo_seq, hi_seq = reads[0]["seq"], reads[-1]["seq"]
    shown = reads
    if args.window:
        shown = [e for e in reads if args.window[0] <= base + e["rel"] < args.window[1]]
    if args.last:
        shown = shown[-args.last:]
    if not shown:
        return 0
    lo_seq, hi_seq = shown[0]["seq"], shown[-1]["seq"]
    if not args.window:
        hi_seq = ents[-1]["seq"]
    extra = [e for e in ents if lo_seq <= e["seq"] <= hi_seq and e["kind"] in (0x10, 0x20)
             and (e["arch"] == arch or e["kind"] == 0x20)]
    for e in sorted(shown + extra, key=lambda e: e["seq"]):
        print(line(e, base, data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
