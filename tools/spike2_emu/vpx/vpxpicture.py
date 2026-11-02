#!/usr/bin/env python3
"""vpxpicture.py - a picture of a Visual Pinball table, out of the table itself.

    python vpxpicture.py <out_dir> <table.vpx>... [--size N]

The app's Visual Pinball tab shows each table with a small picture and a
large one on hover (PAD-942). PAD SHIPS NO PICTURE of any table, the same as
it ships no table: the picture is read from the person's own copy, once,
and kept as a JPEG in the app's cache.

What a .vpx holds (vpxfile.py has the file's shape):

* the playfield image, the picture shown: GameData's IMAG names it, and
  `GameStg/Image<n>` whose NAME it is holds it as records NAME, PATH, WDTH,
  HGHT, then JPEG (empty) and the file's own bytes under DATA (PNG, JPEG or
  WebP, whatever the author imported) - or BITS, Visual Pinball's own LZW
  of raw pixels, which this does not read (none of the tables the kit knows
  uses it for the playfield). A table whose playfield is baked into
  primitives has none to show (VPW's Metallica names a ball texture, an
  HDR file).
* when that is not a picture: an image named like a playfield (`pf...`,
  `...playfield...`), then `TableInfo/Screenshot` (the picture the author put
  under Table > Table Info, the bytes of the file as they were; whatever
  the author chose - TMNT's is the instruction card), then the biggest
  image named `backglass`, so a baked table still shows the game's art
  (David, PAD-942: a guess beats an empty outline; the LARGEST image is
  never taken, on Metallica it is a cabinet-side strobe texture).

Each table's picture goes to <out_dir>/<name>.jpg with the long side at
most --size (1200) px, and a line `picture {json}` is printed as each is
done (the tab's progress); the last line is one JSON object:
{"pictures": {<table path>: {"file", "w", "h", "source"}}, "errors": {<table
path>: <why>}}. <name> is the table file's own name, so a cache keyed by
the file stays readable.
"""
import io
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import vpxfile      # noqa: E402

SIZE = 1200
MAGICS = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"BM")


def image_streams(ole):
    """(name, stream) for every GameStg/Image<n>, its NAME read off the head
    of the stream (the whole image is not read for that)."""
    i = 0
    while ole.exists("GameStg/Image%d" % i):
        head = ole.openstream("GameStg/Image%d" % i).read(512)
        name = ""
        for tag, payload, _ in vpxfile.biff_records(head, 0):
            if tag == "NAME":
                name = payload[4:4 + struct.unpack_from("<I", payload)[0]].decode("latin1")
                break
            if tag in ("JPEG", "BITS", "LINK"):
                break
        yield name, "GameStg/Image%d" % i
        i += 1


def image_bytes(data):
    """The picture file inside one Image stream (the DATA record under JPEG),
    or None for a BITS (raw) or linked image."""
    for tag, payload, _ in vpxfile.biff_records(data, 0):
        if tag == "DATA":
            return payload if payload.startswith(MAGICS) else None
        if tag in ("BITS", "LINK"):
            return None
    return None


def playfield_name(ole):
    gd = ole.openstream("GameStg/GameData").read()
    for tag, payload, _ in vpxfile.biff_records(gd, 0):
        if tag == "IMAG":
            n = struct.unpack_from("<I", payload)[0]
            return payload[4:4 + n].decode("latin1")
    return ""


def open_table(path):
    import olefile
    return olefile.OleFileIO(path)


def picture_of(path):
    """(PIL image in RGB, where it came from) for the table at *path*, or
    raises ValueError saying why there is none."""
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    ole = open_table(path)
    try:
        # In order (David, PAD-942): the playfield GameData names; an image
        # named like a playfield when that one is not a picture (a table whose
        # playfield is baked into primitives names a ball texture there); the
        # author's screenshot (whatever they put there: TMNT's is the
        # instruction card); last, the backglass image, so a baked table (VPW's
        # Metallica) still shows the game's art. Never the largest image: on
        # Metallica that is a cabinet-side strobe texture.
        images = list(image_streams(ole))
        want = playfield_name(ole).lower()
        tries = []
        for name, stream in images:
            if want and name.lower() == want:
                tries.append(("playfield", stream))
        for name, stream in images:
            low = name.lower()
            if (low.startswith("pf") or "playfield" in low) and not (want and low == want):
                tries.append(("playfield", stream))
        if ole.exists("TableInfo/Screenshot"):
            tries.append(("screenshot", "TableInfo/Screenshot"))
        # the biggest backglass-named image: VPW keeps a small one too
        backs = sorted((ole.get_size(stream), name, stream) for name, stream in images
                       if "backglass" in name.lower())
        for _, name, stream in reversed(backs):
            tries.append(("backglass", stream))
        for source, stream in tries:
            data = ole.openstream(stream).read()
            if source != "screenshot":
                data = image_bytes(data)
            if not data:
                continue
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
            except Exception:                   # noqa: BLE001 - a format PIL lacks, a broken file
                continue
            if img.mode in ("RGBA", "LA", "P"):
                # transparent corners of a playfield cut-out: over black, as on the table
                img = img.convert("RGBA")
                back = Image.new("RGBA", img.size, (0, 0, 0, 255))
                back.alpha_composite(img)
                img = back
            img = img.convert("RGB")
            if source == "backglass":
                # a backglass texture is drawn dark, lit by the table's own
                # lights in play (Metallica's mean is 45 of 255): lift it to
                # look lit, never more than 2.5x
                from PIL import ImageEnhance, ImageStat
                mean = ImageStat.Stat(img.convert("L")).mean[0]
                if 0 < mean < 100:
                    img = ImageEnhance.Brightness(img).enhance(min(2.5, 100.0 / mean))
            return img, source
    finally:
        ole.close()
    if not tries:
        raise ValueError("the table has no screenshot and names no playfield image")
    raise ValueError("the table's %s is not a picture the kit reads"
                     % " or ".join(dict.fromkeys(s for s, _ in tries)))


def write_picture(path, out_dir, size=SIZE):
    """The table's picture, scaled to *size* on its long side, as JPEG; the
    record the tab keeps."""
    img, source = picture_of(path)
    w, h = img.size
    img.thumbnail((size, size))
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + ".jpg")
    img.save(out, "JPEG", quality=85, optimize=True)
    return {"file": out, "w": img.size[0], "h": img.size[1], "source": source, "full": [w, h]}


def main(argv):
    size = SIZE
    if "--size" in argv:
        i = argv.index("--size")
        size = int(argv[i + 1])
        del argv[i:i + 2]
    if len(argv) < 2:
        print(__doc__)
        return 2
    out_dir = argv[0]
    os.makedirs(out_dir, exist_ok=True)
    pictures, errors = {}, {}
    for path in argv[1:]:
        try:
            got = write_picture(path, out_dir, size)
            pictures[path] = got
            print("picture " + json.dumps({"table": path, **got}), flush=True)
        except Exception as exc:                            # noqa: BLE001
            errors[path] = str(exc)
            print("picture " + json.dumps({"table": path, "error": str(exc)}), flush=True)
    print(json.dumps({"pictures": pictures, "errors": errors}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
