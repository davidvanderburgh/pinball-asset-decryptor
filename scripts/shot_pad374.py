"""PAD-374 proof shots: a mode made of blocks that plays its own clips and sounds.

    python scripts/shot_pad374.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). Writes <prefix>_blocks_editor.png into <out_dir>: the RAMP FRENZY starter
open in the block editor. On a tree that has PAD-374 the mode also carries two clips and two
sounds of its own (tiny stand-in files) and scripts that play them, as the KING GHIDORAH
example does: an intro full screen and a loop behind the HUD when it starts, a clip behind
the HUD and a call on the jackpot shot, and a call (else the game's Time is up) at the end.
"""

import os
import struct
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as R  # noqa: E402
import webui_shot  # noqa: E402


def _wav(path, seconds=0.5):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(struct.pack("<h", 0) * int(22050 * seconds))


def _media(BM, project, slug):
    """The starter with clips and sounds of its own, as the editor's pickers would leave it."""
    folder = os.path.join(project, "modes", slug)
    for name in ("intro.mp4", "city_loop.mp4", "sever.mp4"):
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"\0" * 64)                       # the editor only names them
    for name in ("roar.wav", "lost.wav"):
        _wav(os.path.join(folder, name))
    prog = BM.load(project, slug)
    prog["clips"] = [{"name": "intro", "file": "intro.mp4"}, {"name": "city_loop", "file": "city_loop.mp4"},
                     {"name": "sever", "file": "sever.mp4"}]
    prog["sounds"] = [{"name": "roar", "file": "roar.wav", "priority": 4},
                      {"name": "lost", "file": "lost.wav", "priority": 4}]
    sc = prog["scripts"]
    start = next(s for s in sc if s["hat"]["kind"] == "mode_start")
    start["do"] = [{"op": "clip", "clip": "intro", "where": "full"},
                   {"op": "clip", "clip": "city_loop", "where": "loop"}] + start["do"]
    jack = next(s for s in sc if s["hat"]["kind"] == "shot" and s["hat"]["when"] == "running")
    jack["do"] += [{"op": "clip", "clip": "sever", "where": "behind"}, {"op": "sound", "sound": "roar"}]
    end = next(s for s in sc if s["hat"]["kind"] == "mode_end")
    end["do"] = [{"op": "sound", "sound": "lost", "fallback": "time_up"}] + end["do"]
    BM.save(project, slug, prog)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM
    print("repo", repo, "PAD-374 in it:", hasattr(BM, "CLIP_WHERE"), flush=True)
    scratch = tempfile.mkdtemp(prefix="pad374-")
    project = R._project(scratch, "GZ 1.15 Pro Extract")
    slug, _path = BM.new_blocks_mode(project, "RAMP FRENZY", example="ramps")
    if hasattr(BM, "CLIP_WHERE"):
        _media(BM, project, slug)
    proc, url = R._serve(repo, scratch, project)
    try:
        def blocks(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            out = os.path.join(out_dir, "%s_blocks_editor.png" % prefix)
            page.screenshot(path=out, full_page=True)
            print("shot", out, flush=True)
            # the scripts that play them, and the palette's last group
            for shot, hat in (("blocks_play", "When the mode starts"), ("blocks_sound", "is made")):
                page.evaluate("""(hat) => {
                  const hats = [...document.querySelectorAll('.bk-script .bk-hat')];
                  const all = hats.filter((h) => h.textContent.includes(hat));
                  const it = all[all.length - 1];
                  if (it) it.scrollIntoView({ block: 'start' });
                  const pal = document.querySelector('.bk-palette');
                  const head = [...document.querySelectorAll('.bk-pal-h')].find((h) => /show and sound/i.test(h.textContent));
                  if (pal && head) pal.scrollTop = head.offsetTop - pal.offsetTop - 8;
                }""", hat)
                time.sleep(1)
                out = os.path.join(out_dir, "%s_%s.png" % (prefix, shot))
                page.screenshot(path=out, full_page=True)
                print("shot", out, flush=True)
        R._shoot(url, blocks, height=1250)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
