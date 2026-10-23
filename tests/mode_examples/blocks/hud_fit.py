"""hud_fit.py - does every word a blocks example can put on Godzilla's glass fit its place on the HUD (PAD-658)?

    python hud_fit.py <card image> [slug ...]

David: "make sure ... there is no overlapping text anywhere". A HUD's pieces sit at fixed places (mode_hud.py): three
counters 200 px wide at the glass's left edge, middle and right edge, the title and the line across the middle above
the score panel, the award and its sub over them, the timer badge under the left counter. A word longer than its
place runs into its neighbour. This measures each string in the game's OWN font (the battle scene's, read off the
card exactly as Write carries it) at the size the HUD letters it, and says which do not fit.

A value that follows words (``hud_text`` with a value, an award with a value) is measured with the widest number the
mode can put there: 13 digits with commas ("1,234,567,890,123") for points, unless the block names a small count.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import examples as BX  # noqa: E402
from pinball_decryptor.plugins.stern import block_modes as BM  # noqa: E402
from pinball_decryptor.plugins.stern import mode_hud as MH  # noqa: E402

#: (variant, px, the width it may take) per HUD piece: mode_hud.hud_group's own sizes and places
PLACES = {                                          # mode_hud.hud_group: variant, size (k-th), room (px)
    "title": ("GameFont_Secondary", 0, 1150),       # centred above the score panel
    "line": ("GameFont_Primary", 2, 1250),
    # centred at y 262 / 356: wider than this it runs over the timer badge (left, y 267-369) and the gauge
    # (right, from y 300)
    "award": ("GameFont_Secondary", 1, 950),
    "awardsub": ("GameFont_Primary", 2, 950),
    # counters: each centred on its 200 px column; the left one meets the glass's edge past ~230 px, the right
    # one past ~260 px; the middle one has the room between them
    "label1": ("GameFont_Primary", 1, 230), "value1": ("GameFont_Secondary", 1, 230), "sub1": ("GameFont_Primary", 0, 230),
    "label2": ("GameFont_Primary", 1, 420), "value2": ("GameFont_Secondary", 1, 420), "sub2": ("GameFont_Primary", 0, 420),
    "label3": ("GameFont_Primary", 1, 260), "value3": ("GameFont_Secondary", 1, 260), "sub3": ("GameFont_Primary", 0, 260),
}
BIG = "123,456,789"        # a realistic award: hundreds of millions


def font_from_card(card):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
    from pinball_decryptor.plugins.stern.formats import parse_mbr_partitions_bytes
    with open(card, "rb") as f:
        parts = [(lba * 512, n * 512) for _i, _t, lba, n in parse_mbr_partitions_bytes(f.read(512))]
        for off, size in parts:
            try:
                r = Ext4Reader(f, off, size)
                for game in ("godzilla_le", "godzilla_pro"):
                    node = MW.lookup(r, "%s/%s" % (game, MH.GAME_FONT_SCENE))
                    if node is not None:
                        return MH.GameFont(bytes(r.read_file_bytes(node)))
            except Exception:                           # noqa: BLE001 - not an ext partition
                continue
    raise SystemExit("no Godzilla battle scene on %s" % card)


def width(font, text, place):
    variant, k, _room = PLACES[place]
    _sid, px, glyphs = sorted(font.sizes[variant], key=lambda t: t[1])[k]   # the k-th size, as the HUD takes it
    w = 0.0
    for ch in text:
        g = glyphs.get(ord(ch)) or glyphs.get(ord(ch.upper()))
        w += g[0][4] if g else px * 0.3
    return w


def strings(program):
    """(place, text, where) for every word the program can put on the HUD."""
    h = program["hud"]
    out = [("title", program["name"], "the name"), ("line", h["line"], "the HUD's line")]
    for k, c in enumerate(h["counters"], 1):
        if c["label"]:
            out.append(("label%d" % k, c["label"], "counter %d's label" % k))
            out.append(("sub%d" % k, c["sub"], "counter %d's line" % k))
    for s in program["scripts"]:
        for b in BM._walk(s.get("do") or []):
            op = b.get("op")
            if op == "hud_text":
                t = (b.get("text") or "") + (" " + BIG if b.get("value") is not None else "")
                out.append(("title" if b.get("which") == "title" else "line", t, "a %s block" % b.get("which")))
            elif op == "hud_award":
                # the words big; with a value, the number under them with the sub (block_modes' hud_award)
                if b.get("value") is not None and b.get("text"):
                    out.append(("award", b["text"], "an award"))
                    out.append(("awardsub", BIG + ("  -  " + b["sub"] if b.get("sub") else ""), "an award's line"))
                else:
                    t = (b.get("text") or "") + (" " + BIG if b.get("value") is not None else "")
                    out.append(("award", t, "an award"))
                    if b.get("sub"):
                        out.append(("awardsub", b["sub"], "an award's line"))
            elif op == "hud_counter":
                k = int(b.get("counter") or 1)
                if b.get("sub"):
                    out.append(("sub%d" % k, b["sub"], "counter %d's line" % k))
                if b.get("label"):
                    out.append(("label%d" % k, b["label"], "counter %d's label" % k))
    return out


def check(font, ex):
    bad = []
    for place, text, where in strings(ex["program"]):
        if not text or not text.strip():
            continue
        w = width(font, text, place)
        room = PLACES[place][2]
        if w > room:
            bad.append("%s %r: %d px in a %d px place (%s)" % (where, text, w, room, place))
    return bad


def main(argv):
    font = font_from_card(argv[0])
    only = argv[1:]
    n = 0
    for ex in BX.EXAMPLES:
        if only and ex["slug"] not in only:
            continue
        bad = check(font, ex)
        n += len(bad)
        print("%-18s %s" % (ex["slug"], "fits" if not bad else "%d too wide" % len(bad)))
        for t in bad:
            print("    " + t)
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
