#!/usr/bin/env python3
"""lcdlogo.py <game> - pull the attract logo card off the game's own card.

Item 83. The real Villain Vision opens attract with a full-screen card -
the BATMAN logo on green, held ~5 s (David's video of the machine,
t=3-7 s) - and that card is a SCENE TEXTURE on the render path this build
disables, so the wire never names it and the clip store does not hold it.
David found the artwork himself in his extraction
(radimg_Shape_1280x720_...): it is the card's ONLY 1280x720 lcd texture,
measured across every assets/lcd scene (auto_loaded and demand_loaded
both) - one hit, card-wide. That uniqueness IS the selection rule: no
name hashes hard-coded, no colour heuristics, and if a card ever carries
two such textures this script refuses rather than guesses.

Writes, once, to <PAD_TABLES>/<game>/lcd/logo.png. The panel shows it for
one beat when the wire's shape says a game just ended (playfield.py
LcdPanel documents the trigger and its admitted approximation). A title
with no such texture gets no file and the panel simply never interposes
a card - honest, like every other lazily-derived artifact here.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

SCENE_GLOB = "~/card/*/%s/assets/lcd/*/*/scene.radium"
W, H = 1280, 720

APP = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _app_bits():
    if APP not in sys.path:
        sys.path.insert(0, APP)
    from pinball_decryptor.plugins.stern.engine import parse_radium_images
    from pinball_decryptor.plugins.stern import dds
    return parse_radium_images, dds


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: lcdlogo.py <game>")
    game = sys.argv[1]
    out_dir = os.path.join(padpath.tables() or "", game, "lcd")
    png = os.path.join(out_dir, "logo.png")
    if os.path.isfile(png):
        print(png)
        return 0

    hits = glob.glob(os.path.expanduser(SCENE_GLOB % game))
    if not hits:
        print("lcdlogo.py: no scene.radium (card not mounted?)",
              file=sys.stderr)
        return 1
    try:
        parse_radium_images, dds = _app_bits()
        from PIL import Image
    except Exception as e:                       # app not importable here
        print("lcdlogo.py: %s" % e, file=sys.stderr)
        return 1

    found = []
    for path in hits:
        with open(path, "rb") as f:
            data = f.read()
        for im in parse_radium_images(data):
            if im["disp_w"] == W and im["disp_h"] == H:
                found.append((path, im, data))
    if len(found) != 1:
        # Zero: a title with no card - normal, no file. More than one:
        # the uniqueness rule broke and picking one would be a guess.
        print("lcdlogo.py: %d textures at %dx%d, need exactly 1"
              % (len(found), W, H), file=sys.stderr)
        return 1

    path, im, data = found[0]
    raw = data[im["data_off"]:im["data_off"] + im["length"]]
    try:
        dec = dds.decode_bc3 if im["fmt"] == 5 else dds.decode_bc1
        px = dec(raw, im["pad_w"], im["pad_h"])
        img = Image.frombytes(
            "RGBA", (im["pad_w"], im["pad_h"]), bytes(px)
        ).crop((0, 0, W, H)).convert("RGB")
    except Exception as e:                       # noqa: BLE001 - one texture,
        print("lcdlogo.py: decode failed: %s" % e, file=sys.stderr)
        return 1                                 # so any failure is fatal

    os.makedirs(out_dir, exist_ok=True)
    tmp = png + ".tmp"                  # atomic, like every artifact here
    img.save(tmp, format="PNG")         # ...which .tmp hides from PIL
    os.replace(tmp, png)
    print("%s (from %s)" % (png, os.path.basename(os.path.dirname(path))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
