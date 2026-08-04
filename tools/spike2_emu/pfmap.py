#!/usr/bin/env python3
"""pfmap.py [out.png] [scale] - draw the extracted LED positions on the playfield.

This is the VERIFICATION step for ledxy.py, and it is the only one that actually
settles the question. A coordinate table can be parsed perfectly and still be
read one field over, or be measured in a different image's pixels, and a text
dump of numbers looks equally convincing either way. Drawn on the game's own
playfield artwork, a wrong table is scattered nonsense and a right one is a
pinball machine.

  python3 pfmap.py /tmp/pfmap.png 3
"""
import sys

from PIL import Image, ImageDraw

import devicexy as ledxy

PF = ("/home/david/spike2root/games/godzilla_pro/assets/nuk/images/Test/"
      "scaled_godzilla_pro_playfield.png")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pfmap.png"
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    d, cstr = ledxy.load()
    recs = [r for r in ledxy.records(d, cstr) if r["image"] == "playfield"]

    img = Image.open(PF).convert("RGB")
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    dr = ImageDraw.Draw(img)

    # Colour by DEVICE CLASS, which is also how the classification gets checked:
    # switches should land on lanes, targets, optos and the trough; coils on the
    # slingshots, pop, scoop and plunger; LEDs on the inserts.
    colour = {"switch": (0, 140, 255), "coil": (255, 40, 40), "led": (255, 200, 0)}
    for r in recs:
        cx, cy = r["x"] * scale, r["y"] * scale
        rad = max(3, (r["w"] * scale) // 4)
        c = colour.get(r["kind"], (160, 160, 160))
        if r["kind"] == "coil":                  # squares, so they read apart
            dr.rectangle([cx - rad, cy - rad, cx + rad, cy + rad], outline=c, width=3)
        else:
            dr.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=c, width=2)

    img.save(out)
    print("%d playfield markers -> %s (%dx%d)" % (len(recs), out, img.width, img.height))


if __name__ == "__main__":
    main()
