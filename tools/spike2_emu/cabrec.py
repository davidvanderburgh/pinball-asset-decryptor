#!/usr/bin/env python3
"""cabrec.py - record the running game's cabinet lights (PAD-1516; pinball_decryptor/plugins/stern/cab_rec.py).

    cabrec.py <padled> <out.bin> <seconds> <period ms> <map>

<map>: the lights to record, in the order the app wants them: one light a `;`, its LED channels `node:channel` by
`,` (R, G, B, or the one). Samples the shim's LED block (dump/padled) every <period> ms on the wall's clock, here
beside the guest (read from Windows across 9p the block drops updates: ledrate.py), and writes the recording
(PADCREC1, u32 period, u32 frames, u32 lights, frames x lights x RGB). Prints `rec <done>/<total>` as it goes and
`saved <frames> <lights> <changes>` at the end; exit 2 when there is no LED block (no game running), 3 when the
lights never changed (nothing to record).
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coilmap  # noqa: E402


def parse_map(text):
    out = []
    for light in text.split(";"):
        out.append([tuple(int(v) for v in nc.split(":")) for nc in light.split(",") if nc])
    return out


def sample(data, lights):
    b = bytearray()
    for chans in lights:
        lv = [coilmap.strip_level(data, n, c) or 0 for n, c in chans]
        b += bytes(lv * 3 if len(lv) == 1 else (lv + [0, 0, 0])[:3])
    return bytes(b)


def main(argv):
    led, out, seconds, period, mp = argv[1], argv[2], float(argv[3]), int(argv[4]), argv[5]
    lights = parse_map(mp)
    total = max(1, int(seconds * 1000 / period))
    if not os.path.isfile(led):
        print("no LED block at %s: is the game running in the emulator?" % led, flush=True)
        return 2
    frames, changes, last = [], 0, None
    t0 = time.monotonic()
    for i in range(total):
        wait = t0 + i * period / 1000.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            with open(led, "rb") as f:
                data = f.read()
        except OSError:
            data = b""
        if not data:
            print("the LED block went away at %.1f s: the game stopped" % (i * period / 1000.0), flush=True)
            return 2
        fr = sample(data, lights)
        changes += last is not None and fr != last
        last = fr
        frames.append(fr)
        if i % max(1, 5000 // period) == 0:
            print("rec %d/%d" % (i, total), flush=True)
    if not changes:
        print("the lights did not change in %.0f s: nothing to record" % seconds, flush=True)
        return 3
    tmp = out + ".part"
    with open(tmp, "wb") as f:
        f.write(b"PADCREC1" + struct.pack("<III", period, len(frames), len(lights)) + b"".join(frames))
    os.replace(tmp, out)
    print("saved %d %d %d" % (len(frames), len(lights), changes), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
