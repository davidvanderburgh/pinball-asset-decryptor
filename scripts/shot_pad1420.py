"""PAD-1420 proof shots: the Modes tab on Rick and Morty (the P-ROC runtime's modes).

    python scripts/shot_pad1420.py <repo> <out_dir> <before|after>

scripts/shot_pad1417.py with Rick and Morty's game code (rm-gamecode-20220902.pkg) in the library
selected (only read).  Before (tickets 1-3: Unity and Godot only) the tab says it does not know
this game.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1417 as S  # noqa: E402

S.CARD = r"D:\Pinball\images\Spooky\rm-gamecode-20220902.pkg"

if __name__ == "__main__":
    S.main()
