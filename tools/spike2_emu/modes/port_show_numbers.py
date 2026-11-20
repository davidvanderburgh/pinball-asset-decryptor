#!/usr/bin/env python3
"""PAD-1476: write the lines that let a mode (and a co-op intro) play ANY of the game's light shows by its own
number into every port - the shows the game's own modes start (clip_shows.ShowReading.modes, PAD-1475).

For each ``sdk/ports/<game>-<version>.port`` whose game program is in the folder given, it reads off that program:

* ``site show_start`` - the game's show starter, ``show_start(n)`` (kept where the port has it; else located by
  its shape, clip_shows.locate_starter);
* ``site show_stop_number`` - the game's "stop every show with this number" (clip_shows.locate_stopper; James
  Bond LE/Pro 1.06's ports named it by hand for PAD-642, and the locator lands on the same two);
* ``value show_count`` - how many numbers the starter's table has (a number at or past it is the game's error).

and appends them in a block headed "PAD-1476", leaving a line the port already has as it is. Ports with no
program in the folder, or no starter or stopper found, are reported and left alone.

Usage: port_show_numbers.py <folder of <game>-<maj>_<min>_0[_spike2].elf> [--dry]
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
from pinball_decryptor.plugins.stern import clip_shows as SH  # noqa: E402
from pinball_decryptor.plugins.stern import stock_scan as S  # noqa: E402

PORTS = os.path.join(HERE, "sdk", "ports")
HEAD = ("# ---- PAD-1476: the game's light shows by its own number (pad_mode_runtime.c pm_game_show_number): the\n"
        "# starter, the game's \"stop every show with this number\" (found off the starter: it walks the same\n"
        "# running-show list and ends each record whose number matches) and how many numbers the starter's table has\n")


def elf_for(folder, game, version):
    maj, mnr = version.split(".")
    for path in sorted(glob.glob(os.path.join(folder, "%s-%s_%s_0*.elf" % (game, maj, mnr)))):
        if re.match(r"^%s-%s_%s_0(_spike2)?\.elf$" % (re.escape(game), maj, mnr), os.path.basename(path)):
            return path
    return ""


def site_line(prog, name, va):
    return "site %-20s 0x%08x 0x%08x 0x%08x" % (name, va, prog.word(va), prog.word(va + 4))


def main(argv):
    folder = argv[1]
    dry = "--dry" in argv
    for port in sorted(glob.glob(os.path.join(PORTS, "*.port"))):
        base = os.path.basename(port)[:-5]
        game, _, version = base.rpartition("-")
        path = elf_for(folder, game, version)
        if not path:
            print("%-32s no program" % base)
            continue
        prog = S.Program(open(path, "rb").read())
        text = open(port, encoding="utf-8").read()
        lines = [ln.split("#", 1)[0].split() for ln in text.splitlines()]
        have = {(p[0], p[1]) for p in lines if len(p) >= 2}
        starter = 0
        for p in lines:
            if len(p) >= 5 and p[:2] == ["site", "show_start"]:
                starter = SH._site(prog, p) or 0
        if ("site", "show_start") in have and not starter:
            print("%-32s its show_start line is not this program's: left alone" % base)
            continue
        starter = starter or SH.locate_starter(prog)
        stopper = SH.locate_stopper(prog, starter) if starter else 0
        count = SH.starter_table(prog, starter)[0] if starter else 0
        if not (starter and stopper and count):
            print("%-32s starter %#x stopper %#x count %d: left alone" % (base, starter, stopper, count))
            continue
        add = []
        if ("site", "show_start") not in have:
            add.append(site_line(prog, "show_start", starter) + "   # show_start(n) -> the show's record, or 0")
        if ("site", "show_stop_number") not in have:
            add.append(site_line(prog, "show_stop_number", stopper) + "   # (n): every show numbered n ends")
        if ("value", "show_count") not in have:
            add.append("value %-19s %d" % ("show_count", count))
        print("%-32s starter %#x stopper %#x count %d: %d line(s)" % (base, starter, stopper, count, len(add)))
        if add and not dry:
            with open(port, "a", encoding="utf-8", newline="\n") as f:
                f.write(("" if text.endswith("\n") else "\n") + HEAD + "\n".join(add) + "\n")


if __name__ == "__main__":
    main(sys.argv)
