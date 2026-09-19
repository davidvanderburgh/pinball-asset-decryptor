#!/usr/bin/env python3
"""shot_census.py - turn a census run into a port's `shot` lines (item 135).

    shot_census.py <mode.log> <switch_list.txt> [--ref-port <port>] [-o <shots file>]

Reads census_mode.c's log (`mark <switch id>` then the `shot 0x...` masks the game
dispatched after that press) and the title's switch table, and prints, per pressed
switch, the shot bits it made. A switch's shot is every bit it dispatched except 0x1
("a playfield switch was hit"). The `shot` lines name each bit after the switch that
made it - or, with --ref-port, keep the reference port's name wherever the reference
has that same bit, so a port for another build of the same game keeps its names.

The census writes a mark and presses its switch at least --press-after ms later
(MODE_SDK.md waits 400); a shot logged sooner than that is credited to the switch before.

A bit two switches share (a loop's enter and exit) gets both names joined, and a switch
that made several bits (a spinner) is listed with all of them - it is reported, not
split up, because which bit "is" the shot is a decision for whoever writes the port.
"""
import argparse
import re
import sys
from collections import OrderedDict


def switch_names(path):
    names = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#"):
            continue
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit():
            names[int(parts[0])] = parts[4].strip()
    return names


def ref_shots(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^shot\s+(0x[0-9a-fA-F]+|\d+)\s+(.+?)\s*$", line)
        if m:
            out[int(m.group(1), 0)] = m.group(2)
    return out


def tidy(name):
    """'L Ramp Made Opto' -> 'L ramp made opto': the switch's own words, sentence case."""
    return name[:1].upper() + name[1:].lower()


# a switch table's abbreviations, so "Pwrline Left Tgt" agrees with "Powerline left"
_WORDS = {"l": "left", "r": "right", "c": "center", "ctr": "center", "pwrline": "powerline",
          "tgt": "target", "targ": "target"}


def _words(name):
    return {_WORDS.get(w, w) for w in re.findall(r"[a-z0-9]+", name.lower())}


def agrees(ref_name, switch_name):
    """Does the switch's own name say what the reference name says? Every word of the
    reference name must be in it. Godzilla LE has THREE shield targets where Pro has two,
    so Pro's "Shield target right" is LE's centre bit - and "right" is not in "Shield
    Target Center", which is how that gets caught."""
    return _words(ref_name) <= _words(switch_name)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log")
    ap.add_argument("switch_list")
    ap.add_argument("--ref-port")
    ap.add_argument("-o", "--out")
    ap.add_argument("--press-after", type=int, default=300, metavar="MS",
                    help="the census presses a switch at least this long after writing its "
                         "mark; a shot sooner than that is the previous switch's (default 300)")
    args = ap.parse_args(argv)
    names = switch_names(args.switch_list)
    ref = ref_shots(args.ref_port) if args.ref_port else {}
    by_switch = OrderedDict()
    current = previous = None
    marked = 0
    for line in open(args.log, encoding="utf-8", errors="replace"):
        t = re.match(r"\s*(\d+) ", line)
        m = re.search(r"\[census\] mark (\S+)", line)
        if m:
            # any mark that is not a switch id (`end`) stops attributing: what comes after
            # it is not the census's presses
            previous, current = current, int(m.group(1)) if m.group(1).isdigit() else None
            marked = int(t.group(1)) if t else 0
            if current is not None:
                by_switch.setdefault(current, [])
            continue
        m = re.search(r"\[census\] shot (0x[0-9a-f]+)", line)
        if not m:
            continue
        # A shot logged before this switch can have been pressed is the LAST switch's late
        # one (a Jaws LE shot 1.5 s after its switch landed on the next mark).
        owner = current
        if t and int(t.group(1)) - marked < args.press_after:
            owner = previous
        if owner is not None:
            by_switch[owner].append(int(m.group(1), 16))
    bits = OrderedDict()                     # bit -> [switch ids]
    print("%-5s %-32s %s" % ("id", "switch", "shots after the press (0x1 dropped)"))
    for sid, masks in by_switch.items():
        shot = 0
        for mk in masks:
            shot |= mk & ~1
        print("%-5d %-32s %s" % (sid, names.get(sid, "?"),
                                 " ".join("0x%x" % mk for mk in masks) or "(nothing)"))
        for b in range(64):
            if shot >> b & 1:
                bits.setdefault(1 << b, []).append(sid)
    lines = []
    for bit, sids in sorted(bits.items()):
        own = " / ".join(tidy(names.get(s, "switch %d" % s)) for s in sids)
        if bit in ref and any(agrees(ref[bit], names.get(s, "")) for s in sids):
            name, how = ref[bit], "the reference port's name"
        elif bit in ref:
            name, how = own, "RENAMED - the reference calls this bit %r, but its switch here is %r" % (ref[bit], own)
        else:
            name, how = own, "NEW - named after its switch"
        lines.append("# switch %s: %s" % (", ".join(str(s) for s in sids), how))
        lines.append("shot 0x%-10x %s" % (bit, name))
    missing = [m for m in ref if m not in bits]
    for m in missing:
        lines.append("# the reference's shot 0x%x (%s) was NOT made by any pressed switch" % (m, ref[m]))
    text = "\n".join(lines) + "\n"
    print()
    print(text)
    if args.out:
        open(args.out, "w", encoding="utf-8", newline="\n").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
