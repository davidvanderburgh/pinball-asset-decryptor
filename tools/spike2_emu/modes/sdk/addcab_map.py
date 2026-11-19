#!/usr/bin/env python3
"""addcab_map.py - the `addcab_*` lines of the ports that name no cabinet lights (PAD-1448).

    addcab_map.py <elf dir> [port ...]      rewrite each port's "added cabinet lights" block from its own program
                                            (<elf dir>/<port name without .port>); every port with no `cablamp`
                                            line when none are named

A title with no blades and no speaker lights still lists node 2, "Cabinet Lights", in its node directory, with
nothing on it. A card's addcab.cfg makes the runtime add lights of the game's own there (MODE_SDK.md, "Cabinet lights
your cabinet adds"); the block says where this build keeps its light and device tables and the counts its
start-up copies (lampmap.added_cabinet_lines). The lines are the build's own, so recipes never carry them.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if os.path.isdir(os.path.join(_ROOT, "pinball_decryptor")) and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from pinball_decryptor.plugins.stern import lampmap  # noqa: E402

PORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ports")
HEAD = "# ---- added cabinet lights (PAD-1448)"


def rewrite(text, block):
    """*text* with its added-cabinet block replaced by *block* (or put after its last `lamp` line, else at the end)."""
    lines = text.rstrip("\n").split("\n")
    out, skip = [], False
    for line in lines:
        if line.startswith(HEAD):
            skip = True
            continue
        if skip and (line.startswith("data addcab_") or line.startswith("value addcab_")
                     or line.startswith("# not on this build:")):
            continue
        skip = False
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    at = max((i for i, l in enumerate(out) if l.startswith("lamp ")), default=len(out) - 1) + 1
    return "\n".join(out[:at] + [""] + block + ([""] if at < len(out) and out[at] != "" else []) + out[at:]) + "\n"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    elfdir, names = argv[0], argv[1:]
    if not names:
        names = sorted(f for f in os.listdir(PORTS) if f.endswith(".port")
                       and not any(l.startswith("cablamp") for l in open(os.path.join(PORTS, f), encoding="utf-8")))
    bad = 0
    for name in names:
        path = os.path.join(PORTS, name if name.endswith(".port") else name + ".port")
        elf = os.path.join(elfdir, os.path.basename(path)[:-5])
        if not os.path.exists(elf):
            print("%-30s no program in %s" % (os.path.basename(path), elfdir))
            bad += 1
            continue
        block = lampmap.added_cabinet_lines(lampmap.Elf(elf))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = rewrite(text, block)
        if new != text:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new)
        print("%-30s %s" % (os.path.basename(path), block[1] if block[1].startswith("# not") else "%d lines" % len(block)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
