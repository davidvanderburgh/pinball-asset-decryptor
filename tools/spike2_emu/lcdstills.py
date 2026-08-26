#!/usr/bin/env python3
"""lcdstills.py <game> - build the villain board's STILL SET and its map.

Item 83. The Villain Vision is a STILLS board: it holds one stored image
per command id and fades between them - measured from tripod footage of
the real machine (bm attract.mp4 / bm gameplay.mp4, 2026-08-26): the
attract cycle is 11 stills at ~5.3 s matching the wire's 11-command
62.7 s rotation one-for-one, gameplay rests on the green BATMAN logo
card while the wire hammers asset 54 (the anchor that fixes the whole
alignment), and the machine's own service menu carries an "update the
images" diagnostic under TV settings - the board's set is UPLOADED, the
ids are keys into it. No clip ever plays on it.

★ CARD-ONLY, NOTHING DISTRIBUTED (David's rule, 2026-08-26: "run
everything off the card and not distribute any assets from the image
ourselves"). Every still this writes is EXTRACTED AT RUNTIME from the
mounted card on the user's own machine - no image ships in the repo. An
earlier cut median-stacked David's phone footage for the images no card
store holds and committed the PNGs; that violated the rule twice (video
screenshots, and shipped assets) and is gone.

★ THE BOARD HAS ITS OWN IMAGE STORE, id-mapped INDEPENDENTLY of the clip
store - the architecture David deduced. The Villain Vision is a node-24
LCD with local image storage; the service menu's UPDATE TV IMAGES routine
writes that store from the card, and in-game the wire sends only an id
which the board renders from its store. The mapping is NOT the clip
store's: the board image for wire-id 591 (Batmobile) is a frame of clip
27, and 601 (Gotham sign) is another frame of that SAME clip 27 - wire
ids 591/601 and clip id 27 are unrelated numbers. So the board set cannot
be derived by "extract clip <wire-id>"; the id->image binding lives in
the upload, not in any file the card unpacks to disk. Byte-exact board
images AND their ids both surface in ONE place: the UPDATE TV IMAGES
routine run on the rig with the node bus logged (it no-ops "NO UPDATE
AVAILABLE" when the board is current, so the capture must force a
stale-board state). That is the recorded path to a complete card-only
set - TODO item.

Provenance of the entries below, all CARD-SOURCED at runtime:
  clip  - the still equals frame N of store clip C (content matched, eye
          verified); extracted from the mounted card. Which frame was
          found with footage's help, but the shipped pixels are the
          card's.
  logo  - the card's own unique 1280x720 scene texture (lcdlogo.py).
The seven ids whose board image is in NO card store (the two
game-rendered cards + Penguin / Penitentiary / Riddler / fur sign /
umbrella sign) are intentionally OMITTED until the upload capture names
them; the panel falls back to the clip still for those rather than
showing footage.

Writes <PAD_TABLES>/<game>/lcd/stills/{<name>.png, map.txt}. A title
with no table here gets nothing, and the panel keeps playing clips -
the map's existence is what tells it the display is a stills board.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

STORE_GLOB = "~/card/*/%s/assets/lcd/auto_loaded/*/scene.assets/137.asset"

#: id -> (file, label, source). Sources: ("clip", store_id, frame_n) or
#: ("logo",) - both CARD-derived at runtime. Wire ids from the item-82
#: lcdcap capture; the clip+frame each still equals was content-matched
#: against David's footage and eye-verified.
BATMAN = {
    54:   ("logo.png",        "BATMAN logo card",     ("logo",)),
    591:  ("batmobile.png",   "the Batmobile",        ("clip", 27, 45)),
    601:  ("gotham_sign.png", "Gotham City 14 Miles", ("clip", 27, 65)),
    2359: ("joker.png",       "the Joker",            ("clip", 305, 21)),
    3026: ("catwoman.png",    "Catwoman",             ("clip", 503, 0)),
}
TABLES = {"batman": BATMAN}


def _store(game):
    import glob
    hits = glob.glob(os.path.expanduser(STORE_GLOB % game))
    return hits[0] if hits else None


def _extract_clip_frame(store, cid, n, dst):
    tmp = dst + ".tmp"
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", os.path.join(store, "%d.asset" % cid),
         "-vf", "select=eq(n\\,%d)" % n, "-vsync", "vfr", "-frames:v", "1",
         "-f", "image2", "-c:v", "png",   # .tmp hides the format, name it
         tmp, "-y"], capture_output=True)
    if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp):
        os.replace(tmp, dst)
        return True
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: lcdstills.py <game>")
    game = sys.argv[1]
    table = TABLES.get(game)
    if not table:
        print("lcdstills.py: no measured still table for %s" % game,
              file=sys.stderr)
        return 1
    lcd_dir = os.path.join(padpath.tables() or "", game, "lcd")
    out_dir = os.path.join(lcd_dir, "stills")
    os.makedirs(out_dir, exist_ok=True)
    store = _store(game)

    made, missing = [], []
    for i, (fn, label, src) in sorted(table.items()):
        dst = os.path.join(out_dir, fn)
        if os.path.isfile(dst):
            made.append((i, fn, label))
            continue
        ok = False
        if src[0] == "clip":
            ok = store and _extract_clip_frame(store, src[1], src[2], dst)
        elif src[0] == "logo":
            logo = os.path.join(lcd_dir, "logo.png")
            if os.path.isfile(logo):
                import shutil
                shutil.copyfile(logo, dst)
                ok = True
        if ok:
            made.append((i, fn, label))
        else:
            missing.append((i, label))

    tmp = os.path.join(out_dir, "map.txt.tmp")
    with open(tmp, "w", encoding="utf8") as f:
        f.write("# villain board still map - CARD-derived (see lcdstills.py);"
                " ids without a card-store image await the UPDATE TV IMAGES"
                " capture\n")
        for i, fn, label in made:
            f.write("%d\t%s\t%s\n" % (i, fn, label))
    os.replace(tmp, os.path.join(out_dir, "map.txt"))
    print("stills: %d mapped from the card, %d await the upload capture%s"
          % (len(made), len(missing),
             " (%s)" % ", ".join(l for _, l in missing) if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
