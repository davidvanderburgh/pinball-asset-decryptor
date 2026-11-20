"""PAD-1422 proof shots: the Modes tab on Jetsons (the pinHeck runtime's modes).

    python scripts/shot_pad1422.py <repo> <out_dir> <before|after>

scripts/shot_pad1417.py with the stock Jetsons update in the library selected (only read).
Before (main) the tab does not know this game.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1417 as S  # noqa: E402

S.CARD = r"D:\Pinball\images\Spooky\Jetsons_Code.zip"

if __name__ == "__main__":
    S.main()
