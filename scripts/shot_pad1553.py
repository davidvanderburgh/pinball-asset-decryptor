"""PAD-1553 proof shots: Editions and Music Mode on Pokemon Pro 0.87 (Spike 3), before and after.

    python scripts/shot_pad1553.py <repo> <out_dir> <project> [--after]

<project> is a Pokemon Pro 0.87 audio extract whose .extract_source.json names the card (PAD1553 setup: its
stereo songs of 20 s or more given a tone for modes 2 and 3, editions "Standard, Dark Side"). Writes
<before_|after_>audio_music_menu.png (scripts/shot_pad1359.py's rig: a song's right-click menu, its Music modes
submenu, and the "Why not this sound?" answer when it offers one) and <before_|after_>write_editions.png
(scripts/shot_pad1325.py's rig: the Write tab's Editions row).

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import subprocess
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1359 as A  # noqa: E402


def main():
    repo, out_dir, project = (os.path.abspath(a) for a in sys.argv[1:4])
    tag = "after_" if "--after" in sys.argv else "before_"
    os.makedirs(out_dir, exist_ok=True)
    # the Audio tab: the project's first song first in the list, mode 2's tone on it
    A.SOUNDS = ["idx%04d" % i for i in (14, 0, 1, 2, 3, 5)]
    A.TONE = os.path.join(os.path.dirname(project), "tones", "tone700.wav")
    scratch = tempfile.mkdtemp(prefix="pad1553-")
    try:
        proj = A._project(os.path.join(scratch, "p"), project, "pokemon_pro_087")
        A._shoot(repo, proj, os.path.join(out_dir, tag + "audio_music_menu.png"), why=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    subprocess.run([sys.executable, os.path.join(HERE, "shot_pad1325.py"), repo,
                    os.path.join(out_dir, tag + "write_editions.png"), project, "write"], check=False)


if __name__ == "__main__":
    main()
