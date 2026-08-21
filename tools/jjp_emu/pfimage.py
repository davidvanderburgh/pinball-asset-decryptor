#!/usr/bin/env python3
"""Pull the playfield photograph out of whichever JJP game is mounted.

Every JJP title ships a photo of its own assembled playfield at
``<Game>/edata/graphics/Game Tests/pf_image.png``, encrypted like every other
asset.  That is what the switch/LED matrix draws its markers on.

The rig used to ship a checked-in ``wonka_pf_image.png``, which meant the
matrix showed a Wonka playfield no matter which title was running.  This
decrypts the real one at run time instead, so the rig is title-agnostic — there
should be nothing in it that contains the word "Wonka".

Decryption is PAD's own (``plugins/jjp/crypto.py``); the key is the file's
absolute path inside the image, which is why the path is passed through
unchanged rather than being made relative.
"""

import argparse
import os
import sys

#: The repo root, so PAD's own crypto can be imported when this runs inside WSL
#: from a /mnt/c checkout.
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

#: Where a title keeps its playfield images.
PF_DIR = "edata/graphics/Game Tests"

#: The name every title has - but NOT always the one to use.  See pick_pf().
PF_FALLBACK = "pf_image.png"

#: Which edition's artwork to prefer when a title ships several.  CE and LE
#: share one image, SE and SE666 the other (read out of a running Guns N' Roses:
#: game_pf_image_ce and _le both name GNR_playfield_LE.png, _se and _se666 name
#: GNR_playfield_SE.png).  They are the same playfield geometrically - 338 vs
#: 339 px wide - so this is a cosmetic choice, and ``JJP_PF_NAME`` overrides it
#: outright.
PF_EDITION = os.environ.get("JJP_PF_EDITION", "LE").upper()

#: Kept so existing callers and docs still resolve; pick_pf() is the real answer.
PF_REL = PF_DIR + "/" + PF_FALLBACK


def pick_pf(game_dir):
    """The playfield image the SWITCH COORDINATES are drawn in, not just any.

    ``pf_image.png`` is the obvious choice and it is wrong on at least one
    title.  Guns N' Roses ships THREE images in Game Tests - a bare
    **whitewood** photo as ``pf_image.png``, plus ``GNR_playfield_LE.png`` and
    ``GNR_playfield_SE.png`` - and the game's device positions are in the
    ARTWORK's pixel space, not the whitewood's.  Checked by overlay: the three
    pop-bumper switches land dead-centre on the bumper caps in LE/SE and
    between them on the whitewood, and the keyboard inserts sit exactly along
    the top of the piano-key graphic in LE/SE and on a bare bracket in the
    whitewood.  Drawing on the whitewood put every marker in the wrong place
    while looking plausible enough to be believed.

    (Do not be fooled by the trough, which is what fooled me: those six
    switches are a synthetic 45-degree line and they lie neatly along a 45
    degree ball guide on the whitewood.  The trough is UNDER the playfield and
    cannot appear in a top-down image at all, so it can never be evidence.)

    Wonka ships only ``pf_image.png``, and there it IS the finished playfield -
    so the rule is "prefer a named playfield, else fall back", never "always
    take pf_image.png".
    """
    d = os.path.join(game_dir, PF_DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return os.path.join(d, PF_FALLBACK)

    forced = os.environ.get("JJP_PF_NAME")
    if forced and forced in names:
        return os.path.join(d, forced)

    art = [n for n in names
           if n.lower().endswith(".png") and "playfield" in n.lower()]
    if art:
        for n in art:                       # this edition's, if it is there
            if PF_EDITION in n.upper():
                return os.path.join(d, n)
        return os.path.join(d, art[0])
    return os.path.join(d, PF_FALLBACK)


def find_game_dir(root, jjpedir="/jjpe/gen1"):
    """The mounted image's game directory — the one with an executable ``game``."""
    base = os.path.join(root, jjpedir.lstrip("/"))
    try:
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if os.path.isfile(os.path.join(d, "game")):
                return d, name
    except OSError:
        pass
    return None, None


def extract(root, out_path, jjpedir="/jjpe/gen1"):
    from pinball_decryptor.plugins.jjp import crypto

    game_dir, title = find_game_dir(root, jjpedir)
    if not game_dir:
        raise SystemExit("pfimage: no game directory under %s%s" % (root, jjpedir))

    enc_path = pick_pf(game_dir)
    if not os.path.isfile(enc_path):
        raise SystemExit("pfimage: %s ships no playfield image (looked in %s)"
                         % (title, PF_DIR))

    # The KEY is the file's absolute path as it exists inside the image, not on
    # our filesystem — strip the mount point back off.
    key_path = "/" + os.path.relpath(enc_path, root).replace(os.sep, "/")

    with open(enc_path, "rb") as fh:
        data = fh.read()

    filler = crypto.detect_filler_size(data, key_path)
    if filler is None:
        raise SystemExit("pfimage: could not determine the filler size for %s"
                         % key_path)
    plain = crypto.decrypt_file(data, filler, key_path)

    if not plain.startswith(b"\x89PNG"):
        raise SystemExit("pfimage: decrypted %s is not a PNG (filler=%s)"
                         % (key_path, filler))

    with open(out_path, "wb") as fh:
        fh.write(plain)

    # IHDR is always the first chunk: width/height are big-endian at offset 16.
    w = int.from_bytes(plain[16:20], "big")
    h = int.from_bytes(plain[20:24], "big")
    print("%s: %s %dx%d (%d bytes)" % (title, out_path, w, h, len(plain)))
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True,
                    help="the mounted game filesystem (…/root)")
    ap.add_argument("--out", required=True, help="where to write the PNG")
    ap.add_argument("--jjpedir", default="/jjpe/gen1")
    args = ap.parse_args(argv)
    extract(args.root, args.out, args.jjpedir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
