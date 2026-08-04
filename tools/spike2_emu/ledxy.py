#!/usr/bin/env python3
"""ledxy.py [out.txt] - every LED's NAME, IMAGE and XY POSITION, from the game.

THE GAME KNOWS WHERE ITS LEDS ARE. It has to: it authors spatial light shows
(`blele --sweep N --lts <id> --direction ...`), and its own LED test draws each
fixture on the playfield artwork. So the positions are data, not something to be
placed by hand or inferred from the order a sweep lights things in.

The record is **0x30 bytes**, not the 0x18 lednames.py walks - 0x18 is only the
five-language name slot inside it, which is why scanning at that stride turns up
`playfield / 8b / playfield` and looks like three different tables:

    +0x00  char*  image name: "playfield", "Test/scaled_godzilla_topper",
                  "System/TestMode/spike_2_speaker_panel_cropped"
    +0x04  i16,i16  (group, index)
    +0x08  i16,i16
    +0x0c  u32    constant 0x0aa00a71 across the playfield rows
    +0x10  i16,i16  **X, Y** in the image's own pixels
    +0x14  i16,i16  **W, H** of the marker (20x20 on the playfield)
    +0x18  char*  connector, e.g. "8b"
    +0x1c  char*  part number, e.g. "part:520-8531-00"
    +0x20  0
    +0x24  char*  NAME, uppercase, e.g. "FIGHTER RIGHT 1"
    +0x28  char*
    +0x2c  char*

The coordinates land inside 313x710, which is exactly the size of
`assets/nuk/images/Test/scaled_godzilla_pro_playfield.png`, and they agree with
the names - FIGHTER RIGHT 1..3 sit at x=225..239 of 313, on the right.

Nothing here is reachable by findref.sh or litref.py: every reference to this
table goes through the GOT. It was found structurally, by noticing that a
0x18-stride scan kept landing on a different field of one repeating record.
"""
import struct
import sys

GAME = "/home/david/spike2root/games/godzilla_pro/game"
VA_BIAS = 0x8000
STRIDE = 0x30
LO, HI = 0x750000, 0x790000

#: The playfield artwork these coordinates are in, and its size.
PLAYFIELD_PNG = "assets/nuk/images/Test/scaled_godzilla_pro_playfield.png"
PF_W, PF_H = 313, 710


def load(path=GAME):
    d = open(path, "rb").read()

    def cstr(va):
        o = va - VA_BIAS
        if o < 0 or o >= len(d):
            return None
        e = d.find(b"\0", o)
        if e < 0 or e - o > 70:
            return None
        try:
            t = d[o:e].decode("ascii")
        except UnicodeDecodeError:
            return None
        return t if t and all(32 <= ord(c) < 127 for c in t) else None

    return d, cstr


def _one(d, cstr, va):
    """Parse a record at `va`, or None if it does not validate."""
    o = va - VA_BIAS
    if o < 0 or o + STRIDE > len(d):
        return None
    img = cstr(struct.unpack_from("<I", d, o)[0])
    if img is None or ("/" not in img and img != "playfield"):
        return None
    name = cstr(struct.unpack_from("<I", d, o + 0x24)[0])
    if not name:
        return None
    x, y = struct.unpack_from("<hh", d, o + 0x10)
    w, h = struct.unpack_from("<hh", d, o + 0x14)
    if not (0 <= x <= 4000 and 0 <= y <= 4000 and 0 < w <= 200 and 0 < h <= 200):
        return None
    grp, idx = struct.unpack_from("<hh", d, o + 0x04)
    return dict(va=va, image=img, x=x, y=y, w=w, h=h, group=grp, index=idx,
                conn=cstr(struct.unpack_from("<I", d, o + 0x18)[0]) or "",
                part=cstr(struct.unpack_from("<I", d, o + 0x1C)[0]) or "",
                name=name)


def records(d, cstr):
    """Records found as RUNS at a true 0x30 stride.

    ALIGNMENT MATTERS AND GETTING IT WRONG LOOKS FINE. The first version of this
    scanned every 4 bytes, accepted anything that pattern-matched and then
    de-duplicated by distance. That yields a table which reads perfectly
    plausibly - until you notice POP BUMPER-R at x=178 while POP BUMPER-G and -B
    are at x=251. The three channels of one RGB fixture are one physical LED and
    MUST share coordinates; the mismatch was a misaligned record being read one
    field over. So: only accept a record if it is part of a run of them at exact
    0x30 spacing, and let the run establish the phase.
    """
    seen, out = set(), []
    for va in range(LO, HI, 4):
        if va in seen or _one(d, cstr, va) is None:
            continue
        # Walk back to the true start of this run, then forward through it.
        start = va
        while _one(d, cstr, start - STRIDE) is not None:
            start -= STRIDE
        run, cur = [], start
        while True:
            r = _one(d, cstr, cur)
            if r is None:
                break
            run.append(r)
            seen.add(cur)
            cur += STRIDE
        if len(run) >= 4:                 # a lone match is noise, a run is a table
            out.extend(run)
    return out


def main():
    d, cstr = load()
    keep = sorted(records(d, cstr), key=lambda r: r["va"])
    pf = [r for r in keep if r["image"] == "playfield"]

    # SELF-CHECK. Positions must land inside the artwork they name; anything
    # outside means the record is being read one field over, or the coordinates
    # are in some other image's pixels.
    out = [r for r in pf if not (0 <= r["x"] <= PF_W and 0 <= r["y"] <= PF_H)]
    print("# %d playfield records, %d outside the %dx%d artwork"
          % (len(pf), len(out), PF_W, PF_H))

    # NOT a check, because the obvious version of it is WRONG. -R/-G/-B of one
    # name often carry DIFFERENT positions, and the first version of this called
    # that a misalignment bug and "found" 119 of 146 broken. The records are
    # perfectly aligned - dump 0x760af8/0x760b28/0x760b58 with ledrec.py and they
    # are structurally identical with genuinely different x,y. Drawn with
    # pfmap.py they all land on real inserts. So these suffixes are not always
    # three channels of one physical LED; sometimes they are separate
    # single-colour inserts that share a stem name. Report it, do not "fix" it.
    stems = {}
    for r in keep:
        if r["name"][-2:-1] == "-":
            stems.setdefault(r["name"][:-2], set()).add((r["x"], r["y"]))
    split = sum(1 for pts in stems.values() if len(pts) > 1)
    print("# %d of %d -R/-G/-B stems have channels at different positions"
          % (split, len(stems)))

    lines = ["# Godzilla Pro device positions, from the game binary.",
             "# %d records, %d of them on the playfield image." % (len(keep), len(pf)),
             "# playfield image: %s (%dx%d)" % (PLAYFIELD_PNG, PF_W, PF_H),
             "# %-34s %5s %5s %4s %4s  %-6s %s" %
             ("name", "x", "y", "w", "h", "conn", "image")]
    for r in keep:
        lines.append("%-36s %5d %5d %4d %4d  %-6s %s"
                     % (r["name"], r["x"], r["y"], r["w"], r["h"],
                        r["conn"], r["image"]))
    text = "\n".join(lines) + "\n"

    if len(sys.argv) > 1:
        open(sys.argv[1], "w").write(text)
        print("%d records (%d on the playfield) -> %s"
              % (len(keep), len(pf), sys.argv[1]))
        xs = [r["x"] for r in pf]
        ys = [r["y"] for r in pf]
        if xs:
            print("playfield x %d..%d (image %d), y %d..%d (image %d)"
                  % (min(xs), max(xs), PF_W, min(ys), max(ys), PF_H))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
