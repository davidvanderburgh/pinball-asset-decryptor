#!/usr/bin/env python3
"""devicexy.py [out.txt] - every SWITCH, COIL and LED: name, image, XY, address.

THE GAME KNOWS WHERE ITS DEVICES ARE. It has to: it authors spatial light shows
(`blele --sweep N --lts <id> --direction ...`), and its own test modes draw each
device on the playfield artwork. So the positions are data, not something to be
placed by hand or inferred from the order a sweep lights things in.

**THIS IS NOT AN LED TABLE**, which is what it was first mistaken for and
committed as. The `+0x08` field is a device CLASS and there are three of them:

    1 = SWITCH   59 records, and they are the switch list name for name -
                 DIP 2..8, Service Select/Plus/Minus/Back, the coin switches,
                 Slam Tilt, Left Spinner, Maser Target, Pop Bumper, Mecha Exit
                 Top/Bottom, the EOS switches, the outlanes and return lanes,
                 the flipper buttons, Shooter Lane, the slingshots, Trough 6..1,
                 Trough Jam, L Ramp Made Opto ... Shield Target Left/Right,
                 Godzilla Magnet Fired Virtual. Same names, same ORDER as the
                 switch ids the shim already knows, so id -> XY joins directly.
    2 = COIL     10 records: Trough, Right/Left Slingshot, Auto Plunger, Left
                 Flipper, Up Left Flip, Pop Bumper, Right Scoop, Godzilla
                 Magnet, Coin Enable.
    3 = LED      506 records, playfield and topper.

A name can legitimately appear in more than one class - LEFT OUTLANE is both a
switch and the insert lamp beside it - which is a good sign, not a collision.

The record is **0x30 bytes**, not the 0x18 lednames.py walks - 0x18 is only the
five-language name slot inside it, which is why scanning at that stride turns up
`playfield / 8b / playfield` and looks like three different tables:

    +0x00  char*  image name: "playfield", "Test/scaled_godzilla_topper",
                  "System/TestMode/spike_2_speaker_panel_cropped"
    +0x04  i16,i16  (group, index) - THE I/O ADDRESS. group 6 always carries
                  connector 8a/8b/8c and group 7 carries 9a/9b/9c, i.e. group N
                  is node N+2 and the letter picks the connector on that board.
    +0x08  i16,i16  **CLASS** in the first half: 1 switch, 2 coil, 3 LED
    +0x0c  u32    constant 0x0aa00a71 across the playfield rows
    +0x10  i16,i16  **X, Y** in the image's own pixels
    +0x14  i16,i16  **W, H** of the marker (20x20 on the playfield)
    +0x18  char*  connector, e.g. "8b"
    +0x1c  char*  part number, e.g. "part:520-8531-00"
    +0x20  0
    +0x24  char*  the name of the PREVIOUS device, NOT this one - see NAME_OFF
    +0x28  char*
    +0x2c  char*

**THE NAME AT +0x24 BELONGS TO THE RECORD BEFORE IT.** The 0x30 window is right
and every field in it parses, but it straddles the logical boundary: the name
that reads as this record's is the previous device's. `NAME_OFF` is therefore
-0x0C, not +0x24.

This shipped wrong once and a human caught it on the virtual playfield - LEFT
FLIPPER BUTTON drawn on the right, LEFT SLINGSHOT on the right, SHOOTER LANE in
the bottom-left corner. Worth saying how to catch it without eyes on a picture:
**Godzilla Pro names 31 playfield devices LEFT-something or RIGHT-something.**
With the shift, 31 of 31 land on the correct side of the centreline; without it,
10 are wrong. That check runs in main() now and costs nothing.

The earlier "-R/-G/-B of one fixture disagree on position" oddity was this same
off-by-one seen from another angle, and it was written off as real data. It was
not - and "the records are perfectly aligned" was true and beside the point,
because the alignment was never the thing that was broken.

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

#: Offset of THIS record's name. Negative: see the header - the pointer at
#: +0x24 is the previous device's name, so the name for the position at +0x10
#: lives 0x30 earlier, i.e. at +0x24 - 0x30.
NAME_OFF = 0x24 - STRIDE

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
    name = cstr(struct.unpack_from("<I", d, o + NAME_OFF)[0])
    if not name:
        return None
    x, y = struct.unpack_from("<hh", d, o + 0x10)
    w, h = struct.unpack_from("<hh", d, o + 0x14)
    if not (0 <= x <= 4000 and 0 <= y <= 4000 and 0 < w <= 200 and 0 < h <= 200):
        return None
    grp, idx = struct.unpack_from("<hh", d, o + 0x04)
    cls = struct.unpack_from("<h", d, o + 0x08)[0]
    return dict(va=va, image=img, x=x, y=y, w=w, h=h, group=grp, index=idx,
                cls=cls, kind={1: "switch", 2: "coil", 3: "led"}.get(cls, "?"),
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

    # THE CHECK THAT WOULD HAVE CAUGHT THE OFF-BY-ONE, so it runs every time.
    # 31 playfield devices are named LEFT-something or RIGHT-something, and a
    # correct table puts every one of them on the correct side of the
    # centreline. The wrong name offset scored 21/31; the right one scores 31/31.
    mid, ok, wrong = PF_W / 2.0, 0, []
    for r in pf:
        u = r["name"].upper()
        if u.startswith("LEFT "):
            ok, wrong = (ok + 1, wrong) if r["x"] < mid else (ok, wrong + [r["name"]])
        elif u.startswith("RIGHT "):
            ok, wrong = (ok + 1, wrong) if r["x"] > mid else (ok, wrong + [r["name"]])
    print("# left/right names on the correct side: %d ok, %d WRONG%s"
          % (ok, len(wrong), (" - " + ", ".join(wrong[:4])) if wrong else ""))

    # -R/-G/-B of one stem sharing a position is the other consistency signal:
    # they are three channels of one physical LED, so they should agree.
    stems = {}
    for r in keep:
        if r["name"][-2:-1] == "-":
            stems.setdefault(r["name"][:-2], set()).add((r["x"], r["y"]))
    split = sum(1 for pts in stems.values() if len(pts) > 1)
    print("# %d of %d -R/-G/-B stems have channels at different positions"
          % (split, len(stems)))

    counts = {}
    for r in keep:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    print("# by class: %s" % ", ".join("%s=%d" % kv for kv in sorted(counts.items())))

    lines = ["# Godzilla Pro device positions, from the game binary.",
             "# %d records (%s), %d on the playfield image."
             % (len(keep), " ".join("%s=%d" % kv for kv in sorted(counts.items())),
                len(pf)),
             "# playfield image: %s (%dx%d)" % (PLAYFIELD_PNG, PF_W, PF_H),
             "# %-7s %-34s %5s %5s %4s %4s %4s %5s  %-6s %s" %
             ("class", "name", "x", "y", "w", "h", "grp", "index", "conn", "image")]
    for r in keep:
        lines.append("%-9s %-34s %5d %5d %4d %4d %4d %5d  %-6s %s"
                     % (r["kind"], r["name"], r["x"], r["y"], r["w"], r["h"],
                        r["group"], r["index"], r["conn"], r["image"]))
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
