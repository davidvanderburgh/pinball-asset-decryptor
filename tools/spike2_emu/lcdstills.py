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

THE TABLE BELOW IS A MEASUREMENT, NOT A DERIVATION. The id -> image
pairing cannot be read off the card (the board's set is authored from
the same footage bank as the clip store, but the keys are the game's
own); each entry's provenance is one of:

  clip  - the still equals frame N of store clip C, pinned by aligned
          normalized correlation against the footage and verified by eye
          (the frame number is 0-based, ffmpeg's n).
  logo  - the card's own unique 1280x720 scene texture (lcdlogo.py).
  photo - a median-stack of the footage itself (game-rendered cards that
          exist in no store; the diagnostic upload, once captured, is
          the byte-exact replacement - recorded in TODO).

Writes <PAD_TABLES>/<game>/lcd/stills/{<name>.png, map.txt}. A title
with no table here gets nothing, and the panel keeps playing clips -
the map's existence is what tells it the display is a stills board.
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

HERE = os.path.dirname(os.path.abspath(__file__))
STORE_GLOB = "~/card/*/%s/assets/lcd/auto_loaded/*/scene.assets/137.asset"

#: id -> (file, label, source...). Sources: ("clip", store_id, frame_n),
#: ("logo",), ("photo", repo_basename). Wire ids from the item-82 lcdcap
#: capture (attract rotation + game start); display contents from the
#: 2026-08-26 footage. 919 is the game-start block's FIRST id - a block
#: command selects by it (the machine shows the IN COLOR title card).
#: Five of the photographic stills exist in NO store clip - the exhaustive
#: sweep (all ~200k frames of all 3,069 clips vs the footage) topped out
#: at wrong-content noise for penguin / penitentiary / fur-sign / riddler /
#: umbrella-sign, while the four clip-pinned entries scored 0.62-0.77 with
#: the right content. The board's set is authored from footage the clip
#: store never sampled, so those five are median-stacks of the footage
#: itself until the diagnostic upload is captured.
BATMAN = {
    2:    ("gameover.png",     "Game Over card",            ("photo", "batman_gameover.png")),
    54:   ("logo.png",         "BATMAN logo card",          ("logo",)),
    720:  ("riddler.png",      "the Riddler",               ("photo", "batman_riddler.png")),
    591:  ("batmobile.png",    "the Batmobile",             ("clip", 27, 45)),
    601:  ("gotham_sign.png",  "Gotham City 14 Miles",      ("clip", 27, 65)),
    1605: ("umbrella_sign.png", "K.G. Bird & Co.",          ("photo", "batman_umbrella.png")),
    1736: ("penguin.png",      "the Penguin",               ("photo", "batman_penguin.png")),
    2066: ("penitentiary.png", "Gotham State Penitentiary", ("photo", "batman_penitentiary.png")),
    2359: ("joker.png",        "the Joker",                 ("clip", 305, 21)),
    3004: ("fur_sign.png",     "Gato & Chat Fur Co.",       ("photo", "batman_fursign.png")),
    3026: ("catwoman.png",     "Catwoman",                  ("clip", 503, 0)),
    919:  ("incolor.png",      "BATMAN IN COLOR card",      ("photo", "batman_incolor.png")),
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
        if src is None:
            pass                        # not pinned yet: honest absence
        elif src[0] == "clip":
            ok = store and _extract_clip_frame(store, src[1], src[2], dst)
        elif src[0] == "logo":
            logo = os.path.join(lcd_dir, "logo.png")
            if os.path.isfile(logo):
                shutil.copyfile(logo, dst)
                ok = True
        elif src[0] == "photo":
            repo = os.path.join(HERE, "stills", game, src[1])
            if os.path.isfile(repo):
                shutil.copyfile(repo, dst)
                ok = True
        if ok:
            made.append((i, fn, label))
        else:
            missing.append((i, label))

    tmp = os.path.join(out_dir, "map.txt.tmp")
    with open(tmp, "w", encoding="utf8") as f:
        f.write("# villain board still map - MEASURED from machine footage"
                " (2026-08-26), see lcdstills.py\n")
        for i, fn, label in made:
            f.write("%d\t%s\t%s\n" % (i, fn, label))
    os.replace(tmp, os.path.join(out_dir, "map.txt"))
    print("stills: %d mapped, %d not yet pinned%s"
          % (len(made), len(missing),
             " (%s)" % ", ".join(l for _, l in missing) if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
