#!/usr/bin/env python3
"""pflive.py <nblog> [out.png] [t] - the playfield with its LEDs as the wire left them.

The end of the chain: node bus bytes -> (node, index) -> a named fixture at a
known playfield position -> a lit dot on the game's own artwork.

  python3 pflive.py ~/gzwatch.log /tmp/pflive.png 60

Brightness is the decoded value. Switches and coils are drawn as outlines for
reference. Undecoded fixtures are drawn dim - the decoder covers the insert
boards (nodes 1, 8, 9) and NOT the strip boards (7, 12, 14), so a dark area may
mean "no data" rather than "off". leddecode.py prints the coverage; read it.
"""
import sys

from PIL import Image, ImageDraw

import devicexy
import ledframes
import ledio
import leddecode

PF = ("/home/david/spike2root/games/godzilla_pro/assets/nuk/images/Test/"
      "scaled_godzilla_pro_playfield.png")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    log = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/pflive.png"
    until = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
    scale = 3

    frames = ledframes.read(log)
    wire = ledio.wire_enumeration(log)
    d, cs = devicexy.load()
    recs = devicexy.records(d, cs)

    GROUP = {1: 5, 8: 6, 9: 7}
    info = {}
    for node, group in GROUP.items():
        for r in recs:
            if r["kind"] == "led" and r["group"] == group:
                info[(node, r["index"])] = r

    state = {}
    for t, b in frames:
        if t > until:
            break
        node = b[0] & 0x3F
        if node not in leddecode.INSERT_NODES or node not in wire:
            continue
        got = leddecode.decode_frame(b, wire[node])
        if got:
            for i, v in got:
                state[(node, i)] = v

    img = Image.open(PF).convert("RGB")
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    dr = ImageDraw.Draw(img)

    lit = 0
    for r in recs:
        if r["image"] != "playfield":
            continue
        cx, cy = r["x"] * scale, r["y"] * scale
        rad = max(3, (r["w"] * scale) // 4)
        if r["kind"] != "led":
            dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                       outline=(150, 150, 150), width=1)
            continue
        key = next((k for k in state if info.get(k) is r), None)
        v = state.get(key, None) if key else None
        if v is None:
            dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                       outline=(70, 70, 70), width=1)
        else:
            lit += 1
            c = (255, int(60 + 195 * v / 255), 0)
            dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=c,
                       outline=(0, 0, 0))

    img.save(out)
    print("%d playfield LEDs decoded and drawn -> %s" % (lit, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
