#!/usr/bin/env python3
"""lednames.py [out.txt] - the game's own LED table, by index, with channels.

WHERE IT IS AND HOW IT WAS FOUND. Not by searching for a string: this binary is
stripped and every .rodata reference is a pc-relative literal, so `litref.py`
and `findref.sh` both come back empty for a name address (the handoff records
the same dead end for the coil names). The way in is to scan the image for a
4-byte POINTER to a known name and see what shape the hits make. Pointers to
'Lower Playfield GI-Wht(X8)' land at 0x767050..0x767060 - five of them, 4 bytes
apart, then a gap - which is a 0x18 record of five language slots plus a null.
LED names are not translated, so all five slots hold the same string. That is
the same message-table shape the coil names use at 0x7150c8.

Each RGB fixture appears as three consecutive records suffixed -R, -G and -B, so
the record index is a CHANNEL index, not a fixture index. Both are printed.

The table runs on past the LEDs into unrelated strings ('INVALID', '8b', '9a'),
so it is cut at the first name that does not look like a fixture rather than at
a hardcoded length - a length would be one more number to be wrong about when a
different title is dumped.

  python3 lednames.py                 # to stdout
  python3 lednames.py led_names.txt   # to a file
"""
import re
import struct
import sys

GAME = "/home/david/spike2root/games/godzilla_pro/game"

#: Message-table base, found by the pointer scan described above.
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


def read_table(path=GAME):
    """[(channel_index, fixture_name, channel_letter)], in table order."""
    data = open(path, "rb").read()
    out = []
    va = TABLE_VA
    while True:
        ptr = struct.unpack_from("<I", data, va - VA_BIAS)[0]
        name = _cstr(data, ptr)
        if name is None or name == TERMINATOR:
            break
        m = _CHAN.match(name)
        out.append((len(out), m.group(1) if m else name, m.group(2) if m else ""))
        va += STRIDE
    return out


def main():
    rows = read_table()
    fixtures = []
    for _, base, chan in rows:
        if not fixtures or fixtures[-1][0] != base:
            fixtures.append([base, ""])
        fixtures[-1][1] += chan

    lines = ["# Godzilla Pro LED table, from the game binary at 0x%x." % TABLE_VA,
             "# %d channels, %d fixtures." % (len(rows), len(fixtures)),
             "# channel  fixture                              rgb"]
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
