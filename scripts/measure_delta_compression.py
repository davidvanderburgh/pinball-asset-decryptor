"""PAD-1580: zlib-9 vs zstd on real delta-update packs (docs/plans/zstd_update_deltas_pad1580.md).

usage: scripts/measure_delta_compression.py MANIFEST PACK [MANIFEST PACK ...]
For each pack, every blob the manifest places in it is unpacked, then
repacked with zstd at several levels; sizes summed, decompression timed.
"""
import gzip, json, sys, time, zlib, os
import zstandard

LEVELS = [3, 9, 19, 22]


def blobs(mpath, ppath):
    m = json.loads(gzip.open(mpath).read())
    pname = os.path.basename(ppath)
    idx = [i for i, p in enumerate(m["packs"]) if p["name"] == pname
           or pname.startswith("base_") and p["tag"] in pname]
    seen = set()
    with open(ppath, "rb") as f:
        pack = f.read()
    for r in m["files"]:
        if r[3] in idx and r[4] not in seen:
            seen.add(r[4])
            b = pack[r[4]:r[4] + r[5]]
            raw = zlib.decompress(b) if r[6] == 1 else b
            yield r[0], raw, b, r[6]


def main(pairs):
    tot = {}
    for mpath, ppath in pairs:
        rows = list(blobs(mpath, ppath))
        raw_n = sum(len(r[1]) for r in rows)
        z9 = sum(len(r[2]) for r in rows)
        t = time.perf_counter()
        for _, raw, b, meth in rows:
            if meth == 1:
                zlib.decompress(b)
        tz = time.perf_counter() - t
        line = ["%-44s files %5d raw %9d zlib9 %9d (unz %6.3fs)"
                % (os.path.basename(ppath)[:44], len(rows), raw_n, z9, tz)]
        tot.setdefault("raw", 0); tot["raw"] += raw_n
        tot.setdefault("zlib9", 0); tot["zlib9"] += z9
        tot.setdefault("tz", 0); tot["tz"] += tz
        for lv in LEVELS:
            c = zstandard.ZstdCompressor(level=lv)
            d = zstandard.ZstdDecompressor()
            t0 = time.perf_counter()
            packed = []
            for _, raw, _, _ in rows:
                p = c.compress(raw)
                packed.append(p if len(p) < len(raw) else None)
            tc = time.perf_counter() - t0
            n = sum(len(p) if p is not None else len(r[1])
                    for p, r in zip(packed, rows))
            t1 = time.perf_counter()
            for p in packed:
                if p is not None:
                    d.decompress(p)
            td = time.perf_counter() - t1
            line.append("  zstd%-2d %9d (%+5.1f%%, pack %5.1fs, unz %6.3fs)"
                        % (lv, n, 100.0 * (n - z9) / max(z9, 1), tc, td))
            for k, v in (("z%d" % lv, n), ("tc%d" % lv, tc), ("td%d" % lv, td)):
                tot[k] = tot.get(k, 0) + v
        print("\n".join(line), flush=True)
    print("TOTAL raw %d zlib9 %d unz %.3fs" % (tot["raw"], tot["zlib9"], tot["tz"]))
    for lv in LEVELS:
        print("  zstd%-2d %d (%+.1f%%) pack %.1fs unz %.3fs" % (
            lv, tot["z%d" % lv], 100.0 * (tot["z%d" % lv] - tot["zlib9"]) / tot["zlib9"],
            tot["tc%d" % lv], tot["td%d" % lv]))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(list(zip(a[0::2], a[1::2])))
