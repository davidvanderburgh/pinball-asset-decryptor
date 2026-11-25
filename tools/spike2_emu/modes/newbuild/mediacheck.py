"""mediacheck.py <frames dir>... - the media proof's frames judged (mediajob.sh's f0..f5 PNGs; PAD-420's media_verdict.py
rule, re-made for PAD-1555): magenta is R >= 200, G <= 60, B >= 200. The clip: a clip frame (f1, f2) >= 50% magenta.
The screen: a screen frame (f3, f4) 1-50% magenta. Before (f0) and after (f5): < 0.5%. One line per directory,
`<dir> clip pass|fail screen pass|fail - percentages`; exit 0 when every directory passes both."""
import os
import sys

from PIL import Image


def magenta(path):
    img = Image.open(path).convert("RGB").resize((320, 180))
    px = list(img.getdata())
    return 100.0 * sum(1 for r, g, b in px if r >= 200 and g <= 60 and b >= 200) / len(px)


def judge(d):
    pct = {}
    for f in sorted(os.listdir(d)):
        if f.endswith(".png") and f[:2] in ("f0", "f1", "f2", "f3", "f4", "f5"):
            pct[f[:2]] = magenta(os.path.join(d, f))
    quiet = pct.get("f0", 100) < 0.5 and pct.get("f5", 100) < 0.5
    clip = quiet and max(pct.get("f1", 0), pct.get("f2", 0)) >= 50
    screen = quiet and any(1 <= pct.get(k, 0) <= 50 for k in ("f3", "f4"))
    return clip, screen, pct


def main(dirs):
    ok = True
    for d in dirs:
        clip, screen, pct = judge(d)
        ok = ok and clip and screen
        print("%s clip %s screen %s - %s" % (os.path.basename(d.rstrip("/\\")), "pass" if clip else "fail",
                                            "pass" if screen else "fail",
                                            " ".join("%s %.1f%%" % kv for kv in sorted(pct.items()))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
