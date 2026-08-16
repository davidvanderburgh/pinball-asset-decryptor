#!/usr/bin/env python3
"""lednames.py [out.txt] - the game's own lamp names, found by shape.

WHERE THEY ARE AND HOW THEY WERE FOUND. Not by searching for a string: this
binary is stripped and every .rodata reference is a pc-relative literal, so
`litref.py` and `findref.sh` both come back empty for a name address (the
handoff records the same dead end for the coil names). The way in is the
RECORD SHAPE. A message record is 0x18 bytes: five pointers to a string, then
a null word. The five are language slots, and these strings are not
translated, so all five hold the SAME pointer - a fingerprint strong enough to
scan the whole image for, which is what find_tables() does. It locates 105
message tables in godzilla_pro 1.15.0 and needs no address at all.

Each RGB fixture appears as three records suffixed -R, -G and -B, so a record
is a CHANNEL and not a fixture. Both are counted.

★ WHAT THIS FILE USED TO CLAIM, AND WHY IT WAS WRONG (item 50, 2026-08-16):

  * It read from `TABLE_VA = 0x766000`, godzilla_pro's address, for EVERY
    title - so it died on the first smaller binary it met, turtles_pro, with
    `struct.error: ... offset 7725056 (actual buffer size is 6457552)`.
  * That address is not the start of anything. It is record 73 of the run
    beginning at 0x765928, and it lands on 'Heat Ray 9-G' - the middle of a
    family of lamps. Every "channel index" it printed was offset by an
    arbitrary 73.
  * There is no single LED table to point at. godzilla's lamp names are spread
    over at least five runs (125, 104, 43, 27, 27 records), and names run
    DESCENDING within a run: 'Heat Ray 11-G', '10-B', '10-R', '10-G', '9-B'.

So this now reports the candidate RUNS and says plainly that the index it
prints is within a run and is not the game's channel number. Establishing that
join needs the game's own `Diagnostics -> Single LED Test`, which names one
lamp against one index and one board - see queue item 54.

  python3 lednames.py                 # to stdout
  python3 lednames.py led_names.txt   # to a file
"""
import array
import re
import struct
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

GAME = gameinfo.elf()

#: Message-table base for godzilla_pro 1.15.0, found by the pointer scan
#: described above. KEPT AS A CROSS-CHECK, NOT AS THE ANSWER: it is one
#: title's address and this file used it for every title, so lednames.py died
#: on turtles_pro with `struct.error: ... offset 7725056 (actual buffer size is
#: 6457552)` - it walked off the end of a smaller binary. find_table() locates
#: the table from its SHAPE instead; main() reports when the two disagree on
#: the title this constant belongs to.
TABLE_VA = 0x766000
#: Five language slots plus a null word.
STRIDE = 0x18
#: This build maps its read-only segment at file offset + 0x8000.
VA_BIAS = 0x8000

_CHAN = re.compile(r"^(.*)-([RGB])$")


def _cstr(data, va):
    off = va - VA_BIAS
    if off < 0 or off >= len(data):
        return None
    end = data.find(b"\0", off)
    if end < 0 or end - off > 60:
        return None
    try:
        text = data[off:end].decode("ascii")
    except UnicodeDecodeError:
        return None
    if not text or not all(32 <= ord(c) < 127 for c in text):
        return None
    return text


#: The table's own terminator. Past it the same region holds short hex-ish
#: scraps ('8b', '9a', '9c') that are not LED names at all.
#:
#: Do NOT try to recognise a fixture by its shape instead. The first attempt
#: here required a channel suffix or a space, which looks reasonable until the
#: table reaches 'Tanks', 'London' and 'NY' - real single-word insert names that
#: it cut the table off at, silently, reporting 87 channels where there are 273.
TERMINATOR = "INVALID"


#: A plausible message string: printable, null-terminated, not absurdly long.
#: The same test devicexy.py's seeds() applies, and for the same reason - a
#: stripped binary with pc-relative literals cannot be searched by reference.
_STRINGS = re.compile(rb"(?:^|\0)([\x20-\x7e]{2,60})\0")


def _string_vas(data):
    return {m.start(1) + VA_BIAS for m in _STRINGS.finditer(data)}


def find_tables(data, min_records=8):
    """Every message table in the image, as [(base_va, [name, ...])].

    ★ FOUND BY SHAPE, NOT BY ADDRESS (item 50, 2026-08-16). A record is 0x18
    bytes: FIVE pointers to a string, then a null word. The five are language
    slots, and these strings are not translated, so all five hold the SAME
    pointer - which is a far stronger fingerprint than "a pointer to a string"
    and is what makes this scan cheap enough to be unconditional. Runs of those
    records at an exact 0x18 stride are the tables.

    Requiring the five to be EQUAL is what keeps it honest. Accepting "five
    pointers that each resolve to some string" would match any pointer array in
    .rodata, and this image has several; devicexy.py records the same lesson
    from the other direction - it only accepts a device record as part of a RUN
    at an exact stride, because a lone plausible match is noise.

    Little-endian is assumed, as everywhere else in this rig (ARM LE guest).
    """
    vas = _string_vas(data)
    n = len(data) // 4
    w = array.array("I")
    w.frombytes(data[:n * 4])
    lo = VA_BIAS
    hi = len(data) + VA_BIAS

    def starts(i):
        """Is word index i the head of a five-slot record?"""
        p = w[i]
        if p < lo or p >= hi or p not in vas:
            return False
        return (w[i + 1] == p and w[i + 2] == p and w[i + 3] == p
                and w[i + 4] == p and w[i + 5] == 0)

    ok = bytearray(n)
    for i in range(n - 6):
        if starts(i):
            ok[i] = 1

    tables, i = [], 0
    while i < n - 6:
        if not ok[i]:
            i += 1
            continue
        run, j = [], i
        while j < n - 6 and ok[j]:
            name = _cstr(data, w[j])
            if name is None:
                break
            run.append(name)
            j += 6                      # 0x18 bytes = six words
        if len(run) >= min_records:
            tables.append((i * 4 + VA_BIAS, run))
        i = max(j, i + 1)
    return tables


def _led_score(names):
    """How much a table looks like the LED table: -R/-G/-B suffixed names.

    THE DISCRIMINATOR, because every message table in the image has the same
    SHAPE - the coil names and the switch names are the same five-slot records.
    Only the lamps are wired as RGB channels, so only the LED table carries a
    crowd of names ending -R, -G or -B. Counted rather than required: a title
    whose inserts are all single-colour would score 0 and must not be picked by
    accident, which is why find_table() refuses rather than guessing.
    """
    return sum(1 for s in names if _CHAN.match(s))


def led_runs(data, min_score=3):
    """Candidate LED runs, best first: [(base_va, [name, ...], score)].

    ★ RUNS, PLURAL, AND DELIBERATELY NOT "THE TABLE" (item 50, 2026-08-16).
    godzilla_pro's lamp names are spread over at least five separate runs -
    125, 104, 43, 27 and 27 records - not one array, and the names run
    DESCENDING inside a run ('Heat Ray 11-G', '10-B', '10-R', '10-G', '9-B'...).
    Until something establishes how the game INDEXES across those runs, a
    function that returned one base and called its offsets channel numbers
    would be inventing the mapping, which is the class of guess this project
    keeps having to undo.

    So this reports what is there and leaves the join to whoever establishes
    it. The oracle for that is the game's own `Diagnostics -> Single LED Test`,
    which names one lamp at a time against an index and a board (David drove
    turtles_pro to `13 / 8-LP-5 / LEFT RETURN LANE LEFT-G / CN14` on
    2026-08-16) - a labelled experiment beats any amount of staring at offsets.
    """
    out = []
    for va, names in find_tables(data):
        score = _led_score(names)
        if score >= min_score:
            out.append((va, names, score))
    out.sort(key=lambda t: -t[2])
    return out


def read_table(path=GAME, base_va=None):
    """[(index_within_run, fixture_name, channel_letter)] for ONE run.

    ★ THE INDEX IS WITHIN THE RUN AND IS NOT THE GAME'S CHANNEL NUMBER - see
    led_runs(). It used to be presented as a channel index, read from a
    hard-coded `TABLE_VA = 0x766000`, and that address is not the start of
    anything: it is record 73 of the run beginning at 0x765928, landing on
    'Heat Ray 9-G' in the middle of a family of lamps. Every index that tool
    ever printed was therefore offset by an arbitrary 73.

    BOUNDED BY THE RUN, which the first version was not: walking until a
    pointer stops resolving read 564 records out of a 125-record run, straight
    through the gap into whatever followed.
    """
    data = open(path, "rb").read()
    runs = led_runs(data)
    if base_va is None:
        if not runs:
            return []
        base_va = runs[0][0]
    names = next((n for va, n, _ in runs if va == base_va), None)
    if names is None:
        names = next((n for va, n in find_tables(data) if va == base_va), [])
    out = []
    for name in names:
        if name == TERMINATOR:
            break
        m = _CHAN.match(name)
        out.append((len(out), m.group(1) if m else name, m.group(2) if m else ""))
    return out


def main():
    game = gameinfo.active()
    path = gameinfo.elf(game)
    if not path or not os.path.exists(path):
        print("lednames: no game binary for %r - set PAD_GAME, or start a run"
              % game)
        return 1
    data = open(path, "rb").read()
    all_tables = find_tables(data)
    runs = led_runs(data)
    if not runs:
        print("lednames: no lamp names found in %s.\n"
              "  %d message tables were located by shape and none carried the"
              " -R/-G/-B channel names lamps have." % (path, len(all_tables)))
        return 2

    # EVERY CANDIDATE, NOT JUST THE BIGGEST. The runs are separate and the
    # indexing across them is not established, so printing one of them as "the
    # LED table" would be a claim this file cannot support.
    print("# %s: %d message tables in the binary, %d carrying lamp names."
          % (game, len(all_tables), len(runs)))
    for va, names, score in runs[:8]:
        print("#   0x%06x  %4d records  %3d channel-suffixed  %r .. %r"
              % (va, len(names), score, names[0], names[-1]))
    print("# The index below is WITHIN ONE RUN and is not the game's own"
          " channel number.")
    print("# Diagnostics -> Single LED Test names a lamp against the game's"
          " index; that is")
    print("# the oracle that would pin the join. See queue item 54.")

    base_va = runs[0][0]
    rows = read_table(path, base_va)
    fixtures = []
    for _, base, chan in rows:
        if not fixtures or fixtures[-1][0] != base:
            fixtures.append([base, ""])
        fixtures[-1][1] += chan

    lines = ["# %s lamp names, run at 0x%x (found by shape, not by address)."
             % (game, base_va),
             "# %d records, %d fixtures." % (len(rows), len(fixtures)),
             "# in-run   fixture                              rgb"]
    for idx, base, chan in rows:
        lines.append("%7d  %-36s %s" % (idx, base, chan))
    text = "\n".join(lines) + "\n"

    if len(sys.argv) > 1:
        open(sys.argv[1], "w").write(text)
        print("%d channels / %d fixtures -> %s"
              % (len(rows), len(fixtures), sys.argv[1]))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
