#!/usr/bin/env python3
"""lcdnames.py <game> - name every VILLAIN VISION clip, once, from the card.

Item 83. The node bus names clips by NUMBER, so the panel could only ever
say "asset 54". The card's own scene file names them: a radium video record
is

    <u64 len><name><u32 id><u64 len><"137.asset/<n>.asset">

so the element name ends exactly 12 bytes before the reference it names.
Parsing that yields all 3,069 of batman's villain clips as episode +
timecode - `asset 54 -> S1E001_Clips.S1E001_00-18-32-21` - which is worth
having for two reasons:

  * IT VERIFIES THE ID MAPPING, which nothing else could. Asset 2 is named
    `PhoneScenes.S1E005_00-03-30-09_LVL_7` and asset 2's picture is the red
    Batphone. Until this the id->clip correspondence rested on eyeballing a
    couple of frames and calling it "eyeball-verified"; now every id in the
    store carries the game's own name for it, and a wrong mapping would
    show up instantly as a name that does not match the picture.
  * IT MAKES THE MIRROR CHECKABLE AGAINST THE MACHINE. "S1E001 00:18:32"
    is something a person can compare to a real Villain Vision, or look up
    in the episode; "asset 54" is not.

Written once to <PAD_TABLES>/<game>/lcd/names.txt as "<id>\\t<name>", which
the playfield panel loads lazily. Regenerating is cheap but not free (the
scene file is 14 MB), so an existing file is left alone - delete it to
rebuild.

THE PARSE IS THE SAME ONE THE APP USES (pinball_decryptor's stern engine,
_parse_radium), reimplemented here rather than imported because the rig
scripts run inside WSL against the card and must not depend on the app
package being importable from there. The framing is documented above; if
the two ever disagree, the app's copy is the reference.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import padpath

#: The store that holds a title's villain-TV clips. Same constant lcdart.py
#: carries, and for the same reason: batman is the only lcdnode title known,
#: so this is a constant with a comment rather than a table nobody else has
#: a row for.
STORE = "137"
SCENE_GLOB = "~/card/*/%s/assets/lcd/auto_loaded/*/scene.radium"

_REF = re.compile((r"%s\.asset/(\d+)\.asset" % STORE).encode())
_NAME_GAP = 4 + 8               # the u32 id plus the reference's own u64 len
_NAME_MAX = 96


def name_before(data, end):
    """The length-prefixed name ending at *end*, or None.

    Scanning forward from ln=1 cannot match early: a shorter candidate would
    have to read its length prefix out of the name's own bytes, and a small
    u64 needs seven zero bytes that printable text never contains.
    """
    for ln in range(1, _NAME_MAX + 1):
        p = end - ln - 8
        if p < 0:
            return None
        if struct.unpack_from("<Q", data, p)[0] != ln:
            continue
        body = data[end - ln:end]
        if all(32 <= b < 127 for b in body):
            return body.decode("latin1")
    return None


def scan(data):
    """{id: name} for every villain-store reference in a scene.radium."""
    out = {}
    for m in _REF.finditer(data):
        i = int(m.group(1))
        if i in out:
            continue
        nm = name_before(data, m.start() - _NAME_GAP)
        # ".asset" in the name means the framing walked into another
        # reference rather than a real element name - drop it rather than
        # publish a name that is really a path.
        if nm and ".asset" not in nm:
            out[i] = nm
    return out


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: lcdnames.py <game>")
    game = sys.argv[1]
    out_dir = os.path.join(padpath.tables() or "", game, "lcd")
    dest = os.path.join(out_dir, "names.txt")
    if os.path.isfile(dest):
        print(dest)
        return 0

    import glob
    hits = glob.glob(os.path.expanduser(SCENE_GLOB % game))
    if not hits:
        print("lcdnames.py: no scene.radium (card not mounted?)", file=sys.stderr)
        return 1

    names = {}
    for h in hits:
        try:
            with open(h, "rb") as f:
                names.update(scan(f.read()))
        except OSError as e:
            print("lcdnames.py: %s: %s" % (h, e), file=sys.stderr)
    if not names:
        print("lcdnames.py: no %s-store references found" % STORE,
              file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    tmp = dest + ".tmp"          # atomic, like every other artifact here:
    with open(tmp, "w", encoding="utf8") as f:   # a torn read would poison
        for i in sorted(names):                  # the table for the run
            f.write("%d\t%s\n" % (i, names[i]))
    os.replace(tmp, dest)
    print("%s (%d names)" % (dest, len(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
