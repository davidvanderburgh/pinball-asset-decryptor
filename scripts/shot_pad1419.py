"""PAD-1419 proof shots: the Modes tab on Looney Tunes (the Godot runtime's modes).

    python scripts/shot_pad1419.py <repo> <out_dir> <before|after>

scripts/shot_pad1417.py with the Looney Tunes 2025.10.08 update in the library selected (only
read).  Before (ticket 1, Unity only) the tab says it does not know this game.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1417 as S  # noqa: E402

S.CARD = r"D:\Pinball\images\Spooky\2025.10.08.looney"

if __name__ == "__main__":
    S.main()
