#!/usr/bin/env python3
"""lamp_map.py - the playfield inserts of a Spike 2 game, read out of its program, as port `lamp` lines.

    lamp_map.py <game ELF>                      every lamp: id, kind, lights, names, node board slot
    lamp_map.py <game ELF> --port [--image playfield]
                                                the port's `lamp` lines (MODE_SDK.md, "Lights: named inserts")
    lamp_map.py <game ELF> --lights             every LIGHT (one colour channel), with its device

The reading itself is pinball_decryptor/plugins/stern/lampmap.py (the app drafts ports with it
too); this is its command line, and every name it has is importable from here as before.
"""
import argparse
import os
import sys

# the package this file ships beside (a checkout or an install: four folders up)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if os.path.isdir(os.path.join(_ROOT, "pinball_decryptor")) and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from pinball_decryptor.plugins.stern import lampmap as _lib  # noqa: E402

globals().update({k: v for k, v in vars(_lib).items() if not k.startswith("__")})


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("elf")
    ap.add_argument("--port", action="store_true", help="print the port's lamp lines")
    ap.add_argument("--lights", action="store_true", help="print every light")
    ap.add_argument("--image", default=None, help="the picture (default: the title's playfield picture)")
    a = ap.parse_args(argv)
    elf = _lib.Elf(a.elf)
    if a.port:
        print("\n".join(_lib.port_lines(elf, a.image)))
        return 0
    t = _lib.find_tables(elf)
    if a.lights:
        for k, d in enumerate(t["lights"]):
            if d:
                print("%4d %-34s group %2d index %3d class %d %s" % (k, d["name"], d["group"], d["index"], d["cls"], d["image"]))
        return 0
    bits, how = _lib.shot_lamps(elf)
    shot_of = {}
    for m, l in (bits or {}).items():
        shot_of[l] = shot_of.get(l, 0) | m
    print("# %d lights, %d lamps; shots: %s" % (len(t["lights"]) - 1, t["lamp_count"], how))
    for l in t["lamps"]:
        names = [t["lights"][i]["name"] if 0 < i < len(t["lights"]) else "?" for i in l["lights"]]
        print("%3d kind %d %-14s %-10s %s" % (l["lamp"], l["kind"], ",".join(map(str, l["lights"])),
                                             "0x%x" % shot_of[l["lamp"]] if l["lamp"] in shot_of else "",
                                             " / ".join(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
