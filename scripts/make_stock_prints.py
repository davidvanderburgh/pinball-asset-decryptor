"""Build the official Stern stock fingerprint table (PAD-426).

    python scripts/make_stock_prints.py D:\\Pinball\\images\\Stern\\spike2 [--all] [--no-verify]
    python scripts/make_stock_prints.py D:\\Pinball\\images\\Stern\\spike2 --add-videos

Reads every official Spike 2 card in the folder (Stern's own file names:
``<title>-<1_16_0>[_spike2].Release.<size>.sdcard.raw``) and writes
``pinball_decryptor/plugins/stern/data/stock_prints.json.xz``.  Only the
LATEST Release build of each title is read unless ``--all`` is given (only
the newest build of each game is supported).  Each card is checked against
its own validation manifest first -- every file's size, and the bytes of
every file up to 32 MB (scenes, pictures, program; ``--full-verify`` reads
the videos and the sound bank too) -- and a card with a ``.pad-build.json``
beside it is refused, so a card that was written to is not recorded as
stock.

``--add-videos`` fills in the ``videos`` of a table made before PAD-626
(which of each release's files are videos) by reading each release's own
card again, without re-hashing anything; the table is saved after each.

Progress is kept in ``stock_prints.partial.json`` beside the table, so a run
that is stopped picks up where it was.  Nothing of Stern's is written: file
paths, sizes and truncated MD5s only.
"""

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pinball_decryptor.plugins.stern import stock_prints as sp  # noqa: E402

_NAME = re.compile(r"^(?P<folder>[a-z0-9_]+?)-(?P<ver>\d+(?:_\d+)+)(?:_spike2)?"
                   r"\.Release\.\d+G\.sdcard\.raw$")


def official_cards(folder, every=False):
    """``[path, ...]`` of the official cards to read: the newest Release
    build per game folder (or all of them with *every*)."""
    best = {}
    for name in sorted(os.listdir(folder)):
        m = _NAME.match(name)
        if not m:
            continue
        ver = tuple(int(x) for x in m.group("ver").split("_"))
        key = m.group("folder") if not every else name
        if key not in best or ver > best[key][0]:
            best[key] = (ver, os.path.join(folder, name))
    return [p for _v, p in sorted(best.values(), key=lambda t: t[1])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--full-verify", action="store_true",
                    help="re-hash the videos and sound bank too (slow)")
    ap.add_argument("--out", default=sp.TABLE_PATH)
    ap.add_argument("--add-videos", action="store_true",
                    help="only fill in each release's videos (PAD-626)")
    args = ap.parse_args()
    if args.add_videos:
        return add_videos(args.folder, args.out)
    partial = os.path.splitext(os.path.splitext(args.out)[0])[0] \
        + ".partial.json"
    done = {}
    if os.path.isfile(partial):
        with open(partial, "r", encoding="utf-8") as f:
            done = json.load(f)
    cards = official_cards(args.folder, args.all)
    print("%d official card(s) to read" % len(cards), flush=True)
    failed = []
    for i, card in enumerate(cards):
        base = os.path.basename(card)
        if any(r.get("card") == base for r in done.values()):
            print("[%d/%d] %s: already read" % (i + 1, len(cards), base))
            continue
        t = time.time()
        try:
            key, rel = sp.make_release(
                card, verify=not args.no_verify,
                verify_max=None if args.full_verify else sp.VERIFY_MAX)
        except Exception as e:                       # noqa: BLE001
            print("[%d/%d] %s: REFUSED - %s" % (i + 1, len(cards), base, e),
                  flush=True)
            failed.append(base)
            continue
        done[key] = rel
        with open(partial, "w", encoding="utf-8") as f:
            json.dump(done, f)
        print("[%d/%d] %s -> %s (%d files, %d pictures, %.0f s)"
              % (i + 1, len(cards), base, key, len(rel["files"]),
                 len(rel["pictures"]) // sp.PICTURE_DIGITS, time.time() - t),
              flush=True)
    sp.save_table(done, args.out)
    print("table: %s (%d releases, %d bytes)"
          % (args.out, len(done), os.path.getsize(args.out)))
    if failed:
        print("refused: %s" % ", ".join(failed))
    return 1 if failed else 0


def add_videos(folder, out):
    """Give every release in the table at *out* its ``videos``, read from
    its own card in *folder*."""
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.info import _walk_partition
    table = sp.load_table(out)
    todo = sorted((k for k, r in table.items() if sp.video_set(r) is None),
                  key=lambda k: table[k]["card"])
    print("%d of %d release(s) to read" % (len(todo), len(table)), flush=True)
    failed = []
    for i, key in enumerate(todo):
        rel = table[key]
        card = os.path.join(folder, rel["card"])
        t = time.time()
        try:
            with CardImage(card) as img:
                parts = sorted((p for p in img.partitions() if p.browsable),
                               key=lambda p: p.size, reverse=True)
                reader = None
                for p in parts:
                    r = img.reader(p.index)
                    found = _walk_partition(r, sniff=False)
                    if os.path.basename(found["sidx_path"]).lower() == key:
                        reader = r
                        break
                if reader is None:
                    raise ValueError("no %s on the card" % key)
                rel["videos"] = sp.release_videos(reader, rel["files"])
        except Exception as e:                       # noqa: BLE001
            print("[%d/%d] %s: FAILED - %s" % (i + 1, len(todo), key, e),
                  flush=True)
            failed.append(key)
            continue
        sp.save_table(table, out)
        print("[%d/%d] %s: %d videos (%.0f s)"
              % (i + 1, len(todo), key, len(rel["videos"]), time.time() - t),
              flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
