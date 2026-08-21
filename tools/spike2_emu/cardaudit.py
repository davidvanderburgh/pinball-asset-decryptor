#!/usr/bin/env python3
"""cardaudit.py [card.raw ...] - what device table each Spike 2 card SHIPS.

    cardaudit.py                       # every .raw in images/Stern/spike2
    cardaudit.py path/to/card.raw ...  # named images (a custom card, say)
    cardaudit.py --json out.json       # machine-readable, same run

For each card image it reports the title's own device table read straight out
of the game ELF: how many records, of which classes, which image the layout is
drawn on (devicexy.layout_image), what playfield art the card carries, and
whether that art is big enough to hold the coordinates - which is the same test
playfield.layout_art() applies before it agrees to draw on a picture.

WHY THIS EXISTS, AND WHY IT DOES NOT MOUNT ANYTHING. The catalogue audit used to
mean booting each title on the rig, and that is what poisoned the table cache:
the sweep of 2026-08-19 ran with most cards absent, wrote a zero-record
device_xy.txt for each, and mtime then made those permanent (item 61). It also
cannot be done at all while someone is playing - `cardmount.sh` mounts under one
fixed path and copies 7 GB into the card cache first.

None of that is necessary. The repo already carries a read-only ext4 reader for
these cards - `plugins/stern/explorer.CardImage`, the Partition Explorer's own
engine - so the ELF can be pulled out of the .raw in a couple of hundred
milliseconds with no mount, no root, no WSL, no lock and no effect whatsoever on
a live run. 40 images take about two minutes.

WHAT IT ESTABLISHED (2026-08-21). The device table is a property of the BUILD,
not of the title: `godzilla_le` 1.13.0 ships no `Test` directory and no records,
while V1.14.0 ships both, and `jaws_le` (1.01 -> 1.02) and `elvira3`
(1.11 -> 1.13) cross the same line. A verdict recorded against a title is
therefore not durable; README.md's Titles table names builds because of this.
"""
import argparse
import json
import os
import re
import struct
import sys
import tempfile

SELF = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(SELF))
for p in (SELF, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import devicexy                                                     # noqa: E402
from pinball_decryptor.plugins.stern.explorer import CardImage      # noqa: E402

#: Where the card library lives when no image is named on the command line.
LIBRARY = os.path.join(REPO, "images", "Stern", "spike2")

#: The two directory names a title's service-mode art has been seen under.
#: gameinfo.find_playfield_art() knows the same pair, and item 57 exists
#: because an earlier version of it knew only the first.
ART_DIRS = ("Test", "TestMode")


def _tokens(name):
    return set(re.split(r"[^a-z0-9]+", name.lower())) - {""}


def _png_size(head):
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def pick_firmware(card):
    """(partition, path) of the TITLE's game ELF on `card`.

    NOT `CardImage.find_firmware()`, which returns the first ELF it meets and
    on every card here that is `/usr/local/spike/spike_menu/game` - 2 MB of
    boot menu on the rootfs partition, with no device table in it. Scoring
    every title a confident zero from that binary is a mistake this function
    exists to prevent. The real one is `/<title>/game` on the data partition,
    two path components, sitting beside image.bin.
    """
    best = None
    for part, path in card.find_firmwares():
        bits = path.strip("/").split("/")
        try:
            reader = card.reader(part)
            size = reader.read_inode(
                card._resolve(reader, path)[0])["size"]
        except Exception:
            size = 0
        rank = (len(bits) == 2 and bits[1] == "game", size)
        if best is None or rank > best[0]:
            best = (rank, part, path)
    return (best[1], best[2]) if best else (None, None)


def card_art(card, part, title):
    """Every `*playfield*.png` the card ships for `title`, with its pixel size.

    The size comes from the PNG header alone (33 bytes), never a full read: a
    card carries several of these and some are megabytes.
    """
    out = []
    for d in ART_DIRS:
        base = "/%s/assets/nuk/images/%s" % (title, d)
        try:
            entries = card.list_dir(part, base)
        except Exception:
            continue
        reader = card.reader(part)
        for e in entries:
            if not e.name.lower().endswith(".png"):
                continue
            if "playfield" not in _tokens(e.name):
                continue
            try:
                node = card._resolve(reader, base + "/" + e.name)[1]
                wh = _png_size(reader.peek(node, 33))
            except Exception:
                wh = None
            out.append((d + "/" + e.name, wh))
    return out


def records_of(elf_bytes):
    """devicexy's records for an ELF held in memory.

    devicexy.load() takes a path because everything else that calls it has one;
    a card's ELF does not exist as a file anywhere, so it gets one briefly.
    """
    fd, tmp = tempfile.mkstemp(suffix=".elf")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(elf_bytes)
        d, cstr = devicexy.load(tmp)
    finally:
        os.unlink(tmp)
    return sorted(devicexy.records(d, cstr), key=lambda r: r["va"])


def audit(raw):
    """One image's row. Never raises for a card it cannot read."""
    row = {"image": os.path.basename(raw)}
    try:
        with CardImage(raw) as card:
            part, fw = pick_firmware(card)
            if part is None:
                row["error"] = "no game ELF on this image"
                return row
            title = fw.strip("/").split("/")[0]
            row.update(firmware=fw, title=title)
            elf = card.read_firmware(part, fw)
            row["elf_bytes"] = len(elf)
            row["art"] = card_art(card, part, title)
    except Exception as exc:
        row["error"] = "%s: %s" % (type(exc).__name__, exc)
        return row

    recs = records_of(elf)
    img = devicexy.layout_image(recs)
    sel = [r for r in recs if r["image"] == img] if img else []
    row.update(records=len(recs), counts=devicexy.counts(recs),
               layout_image=img, on_layout=len(sel),
               kinds_on_layout=sorted({r["kind"] for r in sel}))
    if sel:
        row["extent"] = [max(r["x"] for r in sel), max(r["y"] for r in sel)]
        # The same containment test playfield.layout_art() makes, against the
        # UNPADDED extent - see layout_extent()'s docstring for why the pad
        # must be 0 when judging a picture.
        row["art_fits"] = [n for n, wh in row["art"]
                           if wh and wh[0] >= row["extent"][0]
                           and wh[1] >= row["extent"][1]]
    if recs:
        w, h = next((wh for _n, wh in row["art"] if wh),
                    (devicexy.PF_W, devicexy.PF_H))
        row["checks"] = devicexy.checks(recs, w, h)
    return row


def line(row):
    if row.get("error"):
        return "%-52s ERROR  %s" % (row["image"][:52], row["error"])
    c = " ".join("%s=%d" % kv for kv in sorted(row["counts"].items())) or "-"
    art = "yes" if row.get("art_fits") else (
        "no art" if not row.get("art") else "art too small")
    return "%-52s %-22s %5d records (%s) %d on %s  art:%s" % (
        row["image"][:52], row.get("title", "?"), row["records"], c,
        row.get("on_layout", 0), row.get("layout_image") or "-", art)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("images", nargs="*", help="card .raw files (default: the "
                                              "whole library)")
    ap.add_argument("--json", help="also write the full rows here")
    args = ap.parse_args()

    paths = args.images
    if not paths:
        if not os.path.isdir(LIBRARY):
            print("no images given and no library at %s" % LIBRARY,
                  file=sys.stderr)
            return 2
        paths = [os.path.join(LIBRARY, n) for n in sorted(os.listdir(LIBRARY))
                 if n.lower().endswith((".raw", ".img"))]

    rows = []
    for raw in paths:
        row = audit(raw)
        rows.append(row)
        print(line(row), flush=True)
        for chk in row.get("checks", []):
            print("%-52s   %s" % ("", chk))

    have = [r for r in rows if r.get("records")]
    print()
    print("%d of %d images carry a device table" % (len(have), len(rows)))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(rows, f, indent=1)
        print("wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
