"""PAD-1423 proof shots: the Modes tab on Domino's and Rob Zombie (the pinHeck runtime's modes).

    python scripts/shot_pad1423.py <repo> <out_dir> <before|after> <dominos|rob_zombie>

scripts/shot_pad1417.py with that game's stock update in the library selected (only read);
writes <out_dir>/<kind>_modes_<game>.png and <kind>_modes_build_<game>.png.  Before (main) the
tab does not know these games.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1417 as S  # noqa: E402

CARDS = {"dominos": r"D:\Pinball\images\Spooky\DOM_v6.zip",
         "rob_zombie": r"D:\Pinball\images\Spooky\rzupdate_V26.zip"}

if __name__ == "__main__":
    game = sys.argv.pop(4)
    S.CARD = CARDS[game]
    S.main()
    out_dir, kind = os.path.abspath(sys.argv[2]), sys.argv[3]
    for shot in ("modes", "modes_build"):
        src = os.path.join(out_dir, "%s_%s.png" % (kind, shot))
        if os.path.isfile(src):
            os.replace(src, os.path.join(out_dir, "%s_%s_%s.png" % (kind, shot, game)))
