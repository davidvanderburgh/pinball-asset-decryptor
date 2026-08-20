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

#: Relative to the game directory.  The engine falls back to a flat grey
#: placeholder when a title ships none, so a missing file is a real answer
#: rather than an error.
PF_REL = "edata/graphics/Game Tests/pf_image.png"


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

    enc_path = os.path.join(game_dir, PF_REL)
    if not os.path.isfile(enc_path):
        raise SystemExit("pfimage: %s ships no playfield image (%s)"
                         % (title, PF_REL))

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
