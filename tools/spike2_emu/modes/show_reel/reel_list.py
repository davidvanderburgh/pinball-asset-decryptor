#!/usr/bin/env python3
"""PAD-1476: the show reel's rigbatch list - one line per port: ``<key>|<card>|NUMS=<the shows its game's own modes
start, comma-separated>`` - for the builds whose game program and card are found.

    reel_list.py <folder of <game>-<maj>_<min>_0[_spike2].elf> <cards folder> [--all] [<key>...] > list.txt

--all reels every number of the game's show table (PAD-1475 reopened: a mode can play any of them by its number, and
the Modes tab lists the ones seen lighting), not only the ones the game's own modes start.

The cards folder is searched (and its "older versions" folder) for ``<game>-<maj>_<min>_0*.raw``. Ports already
carrying ``text show_lit`` are left out unless named. Builds missing a program, a card or any mode show are reported
on stderr.
A build with more shows than one reel plays (CHUNK, the runtime's REEL_MAX) gets a line per CHUNK of them, keyed
``<key>``, ``<key>~2``, ``<key>~3`` ...; reel_verdict.py merges them.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
sys.path.insert(0, os.path.dirname(HERE))
from pinball_decryptor.plugins.stern import clip_modes as CM  # noqa: E402
from pinball_decryptor.plugins.stern import clip_shows as SH  # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402

CHUNK = 128                # pad_mode_runtime.c REEL_MAX (and 128 numbers fit its 800-byte read of the file)
# shows that stop the game when a mode of ours plays them (emulator: the game logs nothing more after "#n on"); left
# out of the reel so the rest of the chunk is measured - never lit, so never offered
NEVER = {"batman": {293}}  # Batman 1.13 and 1.14 (2026-11-20)
import port_show_numbers as PSN  # noqa: E402


def card_for(cards, game, version):
    maj, mnr = version.split(".")
    for sub in ("", "older versions"):
        got = sorted(glob.glob(os.path.join(cards, sub, "%s-%s_%s_0*.raw" % (game, maj, mnr))))
        if got:
            return got[0]
    return ""


def wsl(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/mnt/%s%s" % (p[0].lower(), p[2:]) if len(p) > 1 and p[1] == ":" else p


def main(argv):
    elves, cards = argv[1], argv[2]
    every = "--all" in argv[3:]
    only = {a for a in argv[3:] if a != "--all"}
    for port in sorted(glob.glob(os.path.join(PSN.PORTS, "*.port"))):
        key = os.path.basename(port)[:-5]
        if only and key not in only:
            continue
        if not only and "\ntext show_lit" in open(port, encoding="utf-8").read():
            continue
        game, _, version = key.rpartition("-")
        elf, card = PSN.elf_for(elves, game, version), card_for(cards, game, version)
        if not elf or not card:
            sys.stderr.write("%s: no %s\n" % (key, "program" if not elf else "card"))
            continue
        ctx = {}
        CM.analyse(open(elf, "rb").read(), set(), ctx=ctx)
        reading = SH.analyse(game=game, version=version, ctx=ctx)
        nums = set(range(1, reading.count)) if every else {n for rows in reading.modes.values() for n, _a, _c in rows}
        hangs = MP._show_hangs(MP.read_port(port))         # PAD-1475: the port's own list of them
        nums = sorted(nums - NEVER.get(game, set()) - set(hangs))
        if not nums:
            sys.stderr.write("%s: no mode shows (%s)\n" % (key, reading.note))
            continue
        for k in range(0, len(nums), CHUNK):
            print("%s|%s|NUMS=%s" % (key + ("~%d" % (k // CHUNK + 1) if k else ""), wsl(card),
                                     ",".join(map(str, nums[k:k + CHUNK]))), flush=True)


if __name__ == "__main__":
    main(sys.argv)
