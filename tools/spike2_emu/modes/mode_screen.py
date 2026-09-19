#!/usr/bin/env python3
"""mode_screen.py - item 131: build a mode's OWN SCREEN into a stock scene file.

    mode_screen.py <stock scene.radium> <out.radium> --title "KAIJU RUSH" --words "1,000,000 A SHOT"
                   [--name KaijuRush_Screen] [--art art.png] [--x 360 --y 200]

Splices a Sprite holding our art (a BC3 texture the card never had) and a Text with
our words into a scene this repo has MEASURED (scene_write.PROFILES; today the Godzilla
Pro 1.15 in-game HUD scene 32e6ae28 and its attract scene). With no --art, the title is
drawn on a panel. Prints the md5, where the file goes, and the three mode-file lines
mode.so needs to find, show, write and hide it.

EMULATOR-PROVEN, not hardware-proven: KAIJU RUSH showed and updated this screen in a
game (TODO item 131). The one hazard: the screen is authored VISIBLE and it is mode.so
that hides it, so never install the scene without the mode.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from pinball_decryptor.plugins.stern import scene_write as SW  # noqa: E402

FONTS = (r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def panel(title, w=640, h=160):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, w - 5, h - 5), radius=28, fill=(20, 110, 40, 235),
                        outline=(255, 230, 0, 255), width=8)
    font = None
    for path in FONTS:
        if os.path.exists(path):
            font = ImageFont.truetype(path, 92)
            break
    font = font or ImageFont.load_default()
    tw = d.textlength(title, font=font)
    d.text(((w - tw) / 2, 22), title, font=font, fill=(255, 230, 0, 255))
    return np.asarray(img)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scene")
    ap.add_argument("out")
    ap.add_argument("--name", default="Mode_Screen")
    ap.add_argument("--title", default="")
    ap.add_argument("--words", required=True)
    ap.add_argument("--art", help="an RGBA PNG, both sides a multiple of 4")
    ap.add_argument("--x", type=float, default=360.0)
    ap.add_argument("--y", type=float, default=200.0)
    args = ap.parse_args(argv)
    if os.path.abspath(args.scene) == os.path.abspath(args.out):
        sys.exit("refusing to overwrite the stock scene in place: give another output path")
    art = np.asarray(Image.open(args.art).convert("RGBA")) if args.art else panel(args.title or args.name)
    data = open(args.scene, "rb").read()
    try:
        new, info = SW.add_screen(data, args.name, art, args.words, x=args.x, y=args.y)
    except SW.SceneWriteError as e:
        sys.exit("mode_screen: %s" % e)
    with open(args.out, "wb") as f:
        f.write(new)
    print("wrote %s (%d -> %d bytes), md5 %s" % (args.out, len(data), len(new), info["md5"]))
    print("goes to  assets/lcd/%s/%s/scene.radium" % (info["tree"], info["screen_scene"]))
    if not info["in_game"]:
        print("NOTE: this scene is not drawn during a game")
    print("mode file lines:")
    print("  screen_scene   %s" % info["screen_scene"])
    print("  screen_node    %s" % info["screen_node"])
    print("  screen_text    %s" % info["screen_text"])
    print("the screen is authored visible: install it only together with the mode.so that hides it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
