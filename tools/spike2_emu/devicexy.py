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
import array
import collections
import os
import re
import struct
import sys

#: NUL-terminated printable runs, the shape an image name has. 2..70 matches
#: the length limit cstr() already applies.
_STRINGS = re.compile(rb"([\x20-\x7e]{2,70})\x00")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

VA_BIAS = 0x8000
STRIDE = 0x30

#: Offset of THIS record's name. Negative: see the header - the pointer at
#: +0x24 is the previous device's name, so the name for the position at +0x10
#: lives 0x30 earlier, i.e. at +0x24 - 0x30.
NAME_OFF = 0x24 - STRIDE

#: The image name a playfield device carries ON THE TITLES THIS WAS BUILT
#: AGAINST, and what seeds the search below. It is NOT the same word in every
#: title, which is what the comment here used to claim - see layout_image().
PLAYFIELD_IMAGE = "playfield"

#: ★ ARTWORK-LESS BUILDS SHIP THE SAME TABLE WITH THE DRAWING LEFT OUT, and
#: until 2026-08-28 this file could not see one at all. led_zeppelin_le 1.22.0
#: carries all 388 records - class, (group, index) and NAME, every field this
#: rig actually joins on - with the image name pointing at the shared EMPTY
#: string and x/y/w/h and the connector and part pointers all zero. Nothing was
#: subtly wrong with the parse: `seeds()` looks for pointers to an image NAME
#: and there is none, so the table was never seeded, and `_one()`'s
#: `0 < w <= 200` would have refused every record even if it had been.
#:
#: The cost of that was not the artwork, which this title genuinely does not
#: have. It was the NAMES. swnames.py fills a title whose own message-table
#: read comes back `?` from this table, so Led Zeppelin's 51 playfield switches
#: stayed `?`, and padglhost's binds_playfield() - which matches keys to
#: switches BY NAME - built no playfield rows at all. The arrow keys were dead
#: and the trough ids were unknown, which is why no game could be started.
#:
#: A blank-image record is therefore accepted, but on TIGHTER terms than a
#: positioned one, because the image name is the evidence a positioned record
#: is validated by: every one of x, y, w, h, conn and part must be zero, and
#: the class must be a real one. A run of four of those at a true 0x30 stride
#: is not something a data blob produces by accident.
BLANK_IMAGE = ""

#: How many times a word must appear before it is taken for a candidate shared
#: empty string. The pointer is repeated once per record and once more per
#: record from the neighbouring field, so a table worth finding is in the
#: hundreds; 32 is well below any real table and well above a coincidence.
#: Candidates that are not really strings cost only a rejected seed.
BLANK_MIN_REFS = 32


def read_table(path):
    """device_xy.txt back into records. The inverse of text(), below.

    THE FILE IS THE DESK-SIDE COPY OF THE ELF'S TABLE, and reading it costs no
    game binary. That matters for a title run FROM A CARD: its ELF lives on a
    FUSE mount that only exists during a run, while mktables has already
    written this text file beside the switch list. coilmap.py made the same
    move for the coil rows and says why at more length; this is the whole
    table, so a caller that wants switches or LEDs does not need a fourth
    parser.

    Fields are counted FROM THE RIGHT because the NAME is the multi-word one:
    `class NAME... x y w h grp index conn image`. Counting from the left read
    `h` as the group for a whole release.
    """
    out = []
    try:
        f = open(path)
    except OSError:
        return out                  # no table: several titles ship none at all
    with f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            p = line.split()
            if len(p) < 10:
                continue
            try:
                out.append(dict(
                    kind=p[0], name=" ".join(p[1:-8]),
                    x=int(p[-8]), y=int(p[-7]), w=int(p[-6]), h=int(p[-5]),
                    group=int(p[-4]), index=int(p[-3]),
                    conn="" if p[-2] == "-" else p[-2],
                    image="" if p[-1] == "-" else p[-1]))
            except ValueError:
                continue
    return out


def layout_image(recs):
    """The image a title's LAYOUT is drawn on, or None if it has none.

    ★ THE LITERAL "playfield" IS ONE TITLE FAMILY'S SPELLING, NOT A CONSTANT,
    and every consumer in this rig hard-coded it (item 50, 2026-08-16).
    Godzilla Pro, Jaws and John Wick all name the image `playfield`;
    **james_bond_60th_le names the same thing `Test/scaled_playfield`**, so a
    filter on the literal dropped ALL 138 of its positioned devices - 73 LEDs,
    49 switches and 16 coils, every one at a distinct position - and the title
    fell through to the no-positions switch list. It was filed as "Bond has no
    playfield layout". Bond has a complete one.

    THE RULE IS THE MOST DEVICE CLASSES, THEN THE MOST DEVICES, and the first
    half is what makes it safe. A playfield is the one image a title draws
    switches AND coils AND lamps on; a topper or a backbox carries lamps alone,
    and a cabinet front carries a handful of each. Picking on COUNT alone would
    hand Jaws its topper (198 LEDs) over its playfield (143), and elvira3 - the
    one title here whose only positioned records are 275 topper LEDs - would
    look identical to a real playfield. It is not asked to tell those apart:
    with one class present it returns the only layout the title has, and the
    caller says which image it is drawing rather than calling it the playfield.

    Returns the image NAME, which is a key into the records - not a file. What
    artwork, if any, matches it is gameinfo's question and a separate one: the
    name in the table and the name of the png on the card need not agree.
    """
    per = {}
    for r in recs:
        # ★ BLANK_IMAGE is the ABSENCE of a drawing, not a drawing every device
        # shares. Counted as one it would win this vote outright on an
        # artwork-less title - every record carries it - and hand the playfield
        # renderer 388 markers stacked on (0, 0).
        if r["image"] == BLANK_IMAGE:
            continue
        per.setdefault(r["image"], []).append(r)
    if not per:
        return None
    img, _ = max(per.items(),
                 key=lambda kv: (len({r["kind"] for r in kv[1]}), len(kv[1]),
                                 kv[0] == PLAYFIELD_IMAGE))
    return img

#: Fallback artwork size, used only when the title's own drawing cannot be
#: found. Godzilla Pro's, and the right order of magnitude for any Spike 2.
PF_W, PF_H = 313, 710


def playfield_size(game=None):
    """The artwork's real pixel size, read from the PNG the game ships.

    NOT a constant. It was 313x710 here and that is Godzilla Pro's drawing;
    another title has its own, and hard-coding one title's would silently move
    every marker on the next.
    """
    art = gameinfo.playfield_png(game)
    if art and os.path.exists(art):
        wh = gameinfo.png_size(art)
        if wh:
            return wh
    return PF_W, PF_H


def load(path=None):
    path = path or gameinfo.elf()
    if not path:
        raise SystemExit("devicexy: no game binary - set PAD_GAME, or start a run")
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


def blank_str(d, va):
    """True if `va` points at an EMPTY C string inside this binary.

    cstr() cannot answer this: it returns None both for "not a string here" and
    for "a string of length zero", and a blank-image record needs the two told
    apart. See BLANK_IMAGE.
    """
    o = va - VA_BIAS
    return 0 <= o < len(d) and d[o] == 0


def _one(d, cstr, va):
    """Parse a record at `va`, or None if it does not validate."""
    o = va - VA_BIAS
    if o < 0 or o + STRIDE > len(d):
        return None
    imgva = struct.unpack_from("<I", d, o)[0]
    img = cstr(imgva)
    blank = False
    if img is None:
        # ★ The artwork-less variant - see BLANK_IMAGE. Everything a positioned
        # record proves with its image name, this one has to prove by being
        # entirely empty where a positioned record is full.
        if not blank_str(d, imgva):
            return None
        img, blank = BLANK_IMAGE, True
    elif "/" not in img and img != PLAYFIELD_IMAGE:
        return None
    name = cstr(struct.unpack_from("<I", d, o + NAME_OFF)[0])
    if not name:
        return None
    x, y = struct.unpack_from("<hh", d, o + 0x10)
    w, h = struct.unpack_from("<hh", d, o + 0x14)
    conn = struct.unpack_from("<I", d, o + 0x18)[0]
    part = struct.unpack_from("<I", d, o + 0x1C)[0]
    cls = struct.unpack_from("<h", d, o + 0x08)[0]
    if blank:
        if x or y or w or h or conn or part or cls not in (1, 2, 3):
            return None
    elif not (0 <= x <= 4000 and 0 <= y <= 4000
              and 0 < w <= 200 and 0 < h <= 200):
        return None
    grp, idx = struct.unpack_from("<hh", d, o + 0x04)
    return dict(va=va, image=img, x=x, y=y, w=w, h=h, group=grp, index=idx,
                cls=cls, kind={1: "switch", 2: "coil", 3: "led"}.get(cls, "?"),
                conn=cstr(conn) or "", part=cstr(part) or "",
                name=name)


def seeds(d):
    """Candidate record addresses: every word that points at an image name.

    THE ADDRESS WINDOW USED TO BE A CONSTANT - 0x750000..0x790000 - which is
    where Godzilla Pro 1.15.0 happens to keep this table and tells you nothing
    about any other title or build. Seeding from the data instead costs two
    linear passes and works on a binary nobody has looked at:

      * find every string that could be an image name, which is the same test
        _one() applies: "playfield", or anything with a "/" in it;
      * find every 4-byte little-endian word pointing at one of them.

    A record begins with that pointer, so each hit is a candidate start. The run
    check below still decides what is really a table, so a false seed costs
    nothing but a few microseconds.

    SEEDING ON "playfield" ALONE IS NOT ENOUGH, and it looks like it is. The
    playfield devices all came out right - 164 records, every self-check
    passing - while the count quietly fell from 575 to 288, because a run made
    up entirely of TOPPER or CABINET records contains no pointer to "playfield"
    and was never seeded at all. The six cabinet switches went with it. A check
    that only looks at what it found cannot see that.

    ★ A POINTER CAN LAND IN THE MIDDLE OF A STRING, and until 2026-08-21 this
    looked only at where each string STARTS. The linker merges a string that is
    a SUFFIX of another into it and points at the tail, and godzilla_le V1.14.0
    keeps exactly ONE NUL-terminated `playfield` in the whole binary - at the
    end of `Test/scaled_godzilla_le_playfield` - which is the address its table
    carries. That address was never in `want`, so a run made up entirely of
    playfield records had no seed at all: the title's 59 playfield switches and
    every coil, all present and all parsing, were never reached, and the virtual
    playfield fell back to the switch list. 61 playfield LEDs DID come out,
    which is what made it look like a thin table rather than an unseeded one -
    they sit inside a longer run that a neighbouring image name seeded.

    Godzilla Pro hides the bug completely: it happens to keep a SECOND,
    standalone NUL-terminated `playfield` at 0x6061f0 and its table points at
    THAT one, so the same code found all 575 of its records. One title's string
    pool is not a constant either - the same lesson layout_image() already
    learned about the NAME.

    Measured over all 40 card images in `images/Stern/spike2` (cardaudit.py):
    ONE of them changes under this fix, and the other 39 - including all ten
    that already had working tables - are byte-for-byte identical. Note that
    the device table is a property of the BUILD: godzilla_le 1.13.0 ships none
    at all, so the card that shows this bug is V1.14.0 specifically.

    So seed every SUFFIX that would itself pass the image test above, not just
    the whole string. Written without slicing (a rfind and an endswith per
    string) because this runs over every printable run in an 8 MB binary.
    """
    want = blank_seeds(d)
    pf = PLAYFIELD_IMAGE.encode()
    for m in _STRINGS.finditer(d):
        s, base = m.group(1), m.start(1) + VA_BIAS
        # Every suffix that still holds the LAST "/" passes "/ in s", so each
        # is a legal image name and therefore a legal merge target. i == 0 is
        # the whole string, which is what this used to add on its own.
        cut = s.rfind(b"/")
        for i in range(cut + 1):
            want.add(base + i)
        # ...and a tail that is exactly the bare playfield name passes too.
        # This is the godzilla_le case, where the tail starts AFTER the slash.
        if s.endswith(pf) and len(s) - len(pf) > cut:
            want.add(base + len(s) - len(pf))
    if not want:
        return []
    out = []
    for o in range(0, len(d) - 4, 4):
        if struct.unpack_from("<I", d, o)[0] in want:
            out.append(o + VA_BIAS)
    return out


def blank_seeds(d):
    """Candidate addresses of a SHARED EMPTY STRING, for the artwork-less table.

    An artwork-less record (BLANK_IMAGE) names no image, so the seeding above
    has nothing to look for: there is no `playfield`, no path, no `part:` and
    no connector anywhere in led_zeppelin_le's table. What it does have is one
    empty string that every record's image field points at, which is a linker
    artefact rather than a name - so it cannot be found by reading strings, only
    by noticing that a great many pointers agree on it.

    Hence a frequency pass. Words are counted with `array`, which does the whole
    binary in well under a second, and a candidate is any repeated word landing
    on a NUL byte. Most survivors are not strings at all - a run of 0x00FFFF00
    in a data blob lands on a NUL as readily as a pointer does - and that is
    fine: a candidate only ever costs a seed that `_one()` rejects, and the
    run-of-four rule is what actually decides where a table is. Nothing here can
    invent a record.

    Returned as a SET merged into seeds()' `want`, so both variants are found in
    the one linear pass that function already makes; a title with a normal
    positioned table gets the same answer it always did.
    """
    n = len(d) // 4
    if not n:
        return set()
    a = array.array("I")
    a.frombytes(d[:n * 4])
    if sys.byteorder != "little":
        a.byteswap()                # the records are little-endian, always
    return {w for w, refs in collections.Counter(a).items()
            if refs >= BLANK_MIN_REFS and blank_str(d, w)}


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
    for va in seeds(d):
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


def build(game=None, elf_path=None):
    """Every device record for a title, from its game binary alone.

    Split out of main() so mktables.py can call it in process. Nothing here
    touches the wire, a log or a running game: this table is static data in the
    ELF, which is why the artwork half of the playfield window needs no run.

    `game` IS PASSED THROUGH TO gameinfo, and the first version of this did not
    do that - it called `gameinfo.elf()` with no argument, so asking for one
    title's records handed back whichever title was ACTIVE. Building
    `turtles_pro` returned Godzilla's 575 records, its 313x710 artwork size and
    its 31/31 left-right check, all of which look like a healthy result, and 18
    of TMNT's switch names collided with Godzilla's well enough to place markers
    on a playfield TMNT does not have.
    """
    d, cstr = load(elf_path or gameinfo.elf(game))
    return sorted(records(d, cstr), key=lambda r: r["va"])


def checks(keep, pf_w, pf_h):
    """The self-checks, as lines of text. They RUN on every build, on purpose.

    Each one is here because a plausible-looking table was wrong in a way only
    it could see:

      * positions must land inside the artwork they name - outside means the
        record is being read one field over, or the coordinates belong to some
        other image.
      * 31 playfield devices are named LEFT-something or RIGHT-something, and a
        correct table puts every one on the correct side of the centreline. The
        wrong name offset scored 21/31 and looked fine to a human reading rows.
      * -R/-G/-B of one stem are three channels of ONE physical LED, so they
        should share a position. Splits mean a misaligned record.

    ★ 2026-08-19 (item 57): this used to filter on the literal `image ==
    "playfield"` directly, the same hard-coded spelling `layout_image()`'s
    own docstring already says is one title family's, not a constant. That
    made THIS function - the one whose own text is the "N playfield
    records, N outside" line `watch.sh` prints - blind to any title using a
    different spelling, exactly the way "Bond has no playfield layout" was
    filed wrongly before `layout_image()` existed (item 50). Caught on
    `king_kong_le`/`metallica_spike`: `layout_image()` was already being
    used by `playfield.py`'s actual renderer, correctly, while THIS
    function kept reporting "0 playfield records" about titles whose
    devices (`TestMode/Rodeo_LE_Service_Playfield_Wireframe_300dpi_
    cropped`, `metallica_playfield_with_handle_cropped`) were positioned
    fine the whole time - the rendering was never broken, only this
    self-check's own count was.
    """
    img = layout_image(keep)
    pf = [r for r in keep if img is not None and r["image"] == img]
    out = [r for r in pf if not (0 <= r["x"] <= pf_w and 0 <= r["y"] <= pf_h)]
    lines = ["%d playfield records, %d outside the %dx%d artwork"
             % (len(pf), len(out), pf_w, pf_h)]
    # ★ Say when the positional checks below had nothing to check. All three
    # PASS vacuously on an artwork-less table (BLANK_IMAGE): every device sits
    # at (0, 0), so no name is on the wrong side of a centreline and no RGB
    # stem is split. Reporting "0 WRONG" without this line would read as a
    # table that had been verified, which is the one thing this function
    # exists not to do.
    blank = sum(1 for r in keep if r["image"] == BLANK_IMAGE)
    if blank:
        lines.append("%d of %d records carry no artwork (name + wire only) - "
                     "the position checks below do not apply to them"
                     % (blank, len(keep)))

    mid, ok, wrong = pf_w / 2.0, 0, []
    for r in pf:
        u = r["name"].upper()
        if u.startswith("LEFT "):
            ok, wrong = (ok + 1, wrong) if r["x"] < mid else (ok, wrong + [r["name"]])
        elif u.startswith("RIGHT "):
            ok, wrong = (ok + 1, wrong) if r["x"] > mid else (ok, wrong + [r["name"]])
    lines.append("left/right names on the correct side: %d ok, %d WRONG%s"
                 % (ok, len(wrong), (" - " + ", ".join(wrong[:4])) if wrong else ""))

    stems = {}
    for r in keep:
        if r["name"][-2:-1] == "-":
            stems.setdefault(r["name"][:-2], set()).add((r["x"], r["y"]))
    split = sum(1 for pts in stems.values() if len(pts) > 1)
    lines.append("%d of %d -R/-G/-B stems have channels at different positions"
                 % (split, len(stems)))
    return lines


def counts(keep):
    out = {}
    for r in keep:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out


def binary_id(elf_path):
    """`<basename> <size>`, the identity a cached table records for its source.

    ★ WHY A SIZE AND NOT AN MTIME (2026-08-21). mktables decided a cached
    table was current by comparing mtimes, and that answered YES to two files
    it should have refused. A card's files carry the mtimes of the IMAGE, not
    of the copy, so a different card for the same title is routinely OLDER than
    the table built from a previous one - the swap is invisible. And a table
    built when no binary was reachable at all names no source, so an empty
    device_xy.txt written by a sweep that could not open an ELF looked exactly
    like the legitimate empty a title with no device table gets. 17 of 30
    cached titles here were carrying one, godzilla_le among them, and nothing
    was ever going to rebuild them.
    """
    try:
        return "%s %d bytes" % (os.path.basename(elf_path),
                                os.path.getsize(elf_path))
    except (OSError, TypeError):
        return None


def text(game, keep, art, pf_w, pf_h, elf=None):
    """device_xy.txt, as a string."""
    pf = [r for r in keep if r["image"] == layout_image(keep)]
    c = counts(keep)
    lines = ["# %s device positions, from the game binary." % game,
             "# binary: %s" % (binary_id(elf) or "(unknown)"),
             "# %d records (%s), %d on the playfield image."
             % (len(keep), " ".join("%s=%d" % kv for kv in sorted(c.items())),
                len(pf)),
             "# playfield image: %s (%dx%d)"
             % (os.path.basename(art) if art else "(not found)", pf_w, pf_h),
             "# %-7s %-34s %5s %5s %4s %4s %4s %5s  %-6s %s" %
             ("class", "name", "x", "y", "w", "h", "grp", "index", "conn", "image")]
    for r in keep:
        # "-" rather than "" for a missing connector, so EVERY row has the same
        # number of whitespace-separated fields. It did not here: coils carry no
        # connector, an empty column made their rows one field short, and the
        # only reader - which counts fields from the right, because the NAME is
        # the multi-word one - silently read `h` as the group and the group as
        # the index. Every coil tooltip said "group 20 index 6".
        # The IMAGE gets the same "-" treatment as the connector, and for the
        # same reason: an artwork-less record (BLANK_IMAGE) names none, and an
        # empty last column would leave the row one field short for a reader
        # that counts from the right.
        lines.append("%-9s %-34s %5d %5d %4d %4d %4d %5d  %-6s %s"
                     % (r["kind"], r["name"], r["x"], r["y"], r["w"], r["h"],
                        r["group"], r["index"], r["conn"] or "-",
                        r["image"] or "-"))
    return "\n".join(lines) + "\n"


def main():
    game = gameinfo.active()
    if not game:
        print(__doc__)
        print("no active title - set PAD_GAME, or start a run.")
        return 1
    art = gameinfo.find_playfield_art(game)
    pf_w, pf_h = playfield_size(game)
    keep = build(game)
    pf = [r for r in keep if r["image"] == layout_image(keep)]
    print("# %s: %d records from %s" % (game, len(keep), gameinfo.elf(game)))
    for line in checks(keep, pf_w, pf_h):
        print("# %s" % line)
    print("# by class: %s"
          % ", ".join("%s=%d" % kv for kv in sorted(counts(keep).items())))

    dest = sys.argv[1] if len(sys.argv) > 1 else gameinfo.table("device_xy.txt", game)
    d_dir = os.path.dirname(os.path.abspath(dest))
    if not os.path.isdir(d_dir):
        os.makedirs(d_dir)
    with open(dest, "w", newline="") as f:      # newline='': LF even on Windows
        f.write(text(game, keep, art, pf_w, pf_h, gameinfo.elf(game)))
    print("%d records (%d on the playfield) -> %s" % (len(keep), len(pf), dest))
    xs = [r["x"] for r in pf]
    ys = [r["y"] for r in pf]
    if xs:
        print("playfield x %d..%d (image %d), y %d..%d (image %d)"
              % (min(xs), max(xs), pf_w, min(ys), max(ys), pf_h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
