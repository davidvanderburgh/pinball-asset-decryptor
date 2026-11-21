#!/usr/bin/env python3
"""PAD-1476: sample the shim's LED view (dump/padled val[16][96] at offset 20) every 20 ms and write, per sample,
`<wall ms> <bytes changed since the last sample> <lamps lit>`; and each new mode.log line about a show or the
co-op intro as `<wall ms> LOG <line>`, so the two share one clock. Usage: ledsample.py <padled> <mode.log> <out> <secs>"""
import os
import sys
import time

padled, log, out, secs = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
OFF, N = 20, 16 * 96
HI, NH = 7356, 16 * 384               # padled.h hi[16][384]: the lamps past each board's first 96
prev = None
prev_drv = None
DRV, NDRV = 1556, 512                 # padled.h coil[16][16] fire counts + lvl[16][16] drive bytes (flashers)
pos = os.path.getsize(log) if os.path.exists(log) else 0
gz = sys.argv[5] if len(sys.argv) > 5 else ""
gpos = os.path.getsize(gz) if gz and os.path.exists(gz) else 0
t_end = time.time() + secs
with open(out, "w") as o:
    while time.time() < t_end:
        now = int(time.time() * 1000)
        try:
            with open(padled, "rb") as f:
                raw = f.read(HI + NH)
            v = raw[OFF:OFF + N] + raw[HI:HI + NH] if len(raw) >= HI + NH else None
            d = raw[DRV:DRV + NDRV] if v else None
        except OSError:
            v = None
        if v and len(v) == N + NH:
            ch = sum(1 for a, b in zip(v, prev) if a != b) if prev else 0
            dch = sum(1 for a, b in zip(d, prev_drv) if a != b) if prev_drv else 0
            o.write("%d %d %d %d\n" % (now, ch, sum(1 for a in v if a), dch))
            prev, prev_drv = v, d
        try:
            sz = os.path.getsize(log)
            if sz < pos:
                pos = 0
            if sz > pos:
                with open(log, "rb") as f:
                    f.seek(pos)
                    chunk = f.read(sz - pos)
                cut = chunk.rfind(b"\n") + 1
                pos += cut
                for ln in chunk[:cut].decode("utf-8", "replace").splitlines():
                    if "show #" in ln or "co-op intro" in ln or "SHOWTEST" in ln or "REEL" in ln or "show reel" in ln or "light show" in ln:
                        o.write("%d LOG %s\n" % (now, ln.strip()))
        except OSError:
            pass
        if gz:                                    # the shim's driver log: each [coildrive] line, wall-stamped
            try:
                sz = os.path.getsize(gz)
                if sz < gpos:
                    gpos = 0
                if sz > gpos:
                    with open(gz, "rb") as f:
                        f.seek(gpos)
                        chunk = f.read(sz - gpos)
                    cut = chunk.rfind(b"\n") + 1
                    gpos += cut
                    for ln in chunk[:cut].decode("utf-8", "replace").splitlines():
                        if "[coildrive]" in ln and ("pulse" in ln or "fired" in ln):
                            o.write("%d DRV %s\n" % (now, ln.split("[coildrive]", 1)[1].strip()))
            except OSError:
                pass
        o.flush()
        time.sleep(0.02)
