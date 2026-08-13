#!/usr/bin/env python3
"""menuprobe.py - count service-menu VALUE TOGGLES in a screenrec.py recording,
with timestamps, so a held +/- button's consumption rate is read off the same
signal David's eyes get.

    py menuprobe.py toggles rec.mkv [outdir]

WHY THIS EXISTS (item 17). The menu's consumption of a switch is not the same
fact as the game recording the closure - run 3 measured delivery 20/20 and
consumption 0/20 on one screen - and the only honest oracle for consumption is
the game's own display changing. In the Quick Adjustments value editor the
"Set new value:" preview is the one thing that moves when a +/- press is
consumed, and it is drawn in a colour nothing else on that screen uses (the
cyan value text). So: hold Plus for ten seconds, record the window, and every
change in the cyan region is one consumed sample. The toggle count over the
hold IS the consumer's rate, with no shim instrumentation in the loop at all.

HOW IT MEASURES. Frames are extracted with ffmpeg (same binary screenrec.py
uses), the right-hand pane is cropped, and cyan-ish pixels (B and G high, R
low - the value text; the header text is white, the help line is white, the
Current/Default lines are green) are counted per frame. A toggle is a frame
whose cyan-pixel count differs from the previous frame's by more than a noise
floor. Yes/No have different glyph areas, so even a binary adjustment toggles
the count; numeric values change it too. The report is toggle times in video
seconds plus inter-toggle gaps - the gaps are the consumer's period.

The window must be unoccluded while recording, same rule as screenrec.py.
"""
import os
import subprocess
import sys
import tempfile


def cyan_mask(path):
    """WHERE the cyan value text is, not how much of it there is.

    The first version counted cyan pixels and failed its own labelled
    example: "No" and "Yes" cover a near-identical AREA at this font (290 vs
    294 sampled pixels), so an equal-area value swap was invisible. Glyph
    SHAPES always differ, so the oracle is the symmetric difference of the
    pixel-position sets - large for any text change, ~0 between two frames of
    the same value.
    """
    from PIL import Image
    im = Image.open(path).convert('RGB')
    w, h = im.size
    # right pane, below the title band: where the value editor draws
    box = im.crop((w // 2, int(h * 0.30), w, int(h * 0.80)))
    px = box.load()
    bw, bh = box.size
    m = set()
    for y in range(0, bh, 2):
        for x in range(0, bw, 2):
            r, g, b = px[x, y]
            if b > 160 and g > 120 and r < 110:   # the cyan value text
                m.add((x, y))
    return m


def toggles(video, outdir=None):
    outdir = outdir or tempfile.mkdtemp(prefix='menuprobe_')
    os.makedirs(outdir, exist_ok=True)
    fps = 15  # 66.7 ms resolution - a consumer near the node-scan rate
              # (~2 Hz) or the 0x70 metronome (12.15 Hz) both resolve
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video,
                    '-vf', f'fps={fps}', os.path.join(outdir, 'f%05d.png')],
                   check=True)
    frames = sorted(f for f in os.listdir(outdir) if f.endswith('.png'))
    masks = [(i / fps, cyan_mask(os.path.join(outdir, f)))
             for i, f in enumerate(frames)]
    if not masks:
        print('no frames extracted')
        return 1
    floor = 30  # sampled positions; validated: same-value shots XOR at 0,
                # a No->Yes swap XORs in the hundreds
    events = []
    prev = masks[0][1]
    for t, m in masks[1:]:
        d = len(m ^ prev)
        if d > floor:
            events.append((t, d))
        prev = m
    print(f'frames={len(masks)} fps={fps} cyan px first={len(masks[0][1])} '
          f'last={len(masks[-1][1])}')
    print(f'toggles={len(events)}')
    for i, (t, d) in enumerate(events):
        gap = f'  gap={t - events[i-1][0]:.3f}s' if i else ''
        print(f'  t={t:7.3f}s  xor={d:4d}{gap}')
    if len(events) >= 2:
        gaps = [events[i][0] - events[i-1][0] for i in range(1, len(events))]
        gaps.sort()
        print(f'inter-toggle gaps s: min={gaps[0]:.3f} '
              f'median={gaps[len(gaps)//2]:.3f} max={gaps[-1]:.3f}')
    return 0


def validate():
    """The labelled-example gate, runnable at the desk: two shots of the SAME
    value must read as no toggle, and the one KNOWN consumed press (run 3's
    800->2000 ms Plus pair) must read as one. Exits nonzero on failure so it
    can sit in front of any run that trusts this tool."""
    base = r'C:\tmp\item17'
    same = len(cyan_mask(os.path.join(base, 'menu_check.png')) ^
               cyan_mask(os.path.join(base, 'tap1_after.png')))
    diff = len(cyan_mask(os.path.join(base, 'plus800.png')) ^
               cyan_mask(os.path.join(base, 'plus2000.png')))
    ok = same <= 30 < diff
    print(f'same-value xor={same} (must be <=30), '
          f'consumed-press xor={diff} (must be >30): '
          f'{"PASS" if ok else "FAIL"}')
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == 'validate':
        return validate()
    if len(sys.argv) < 3 or sys.argv[1] != 'toggles':
        print(__doc__)
        return 2
    return toggles(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)


if __name__ == '__main__':
    sys.exit(main())   # guarded, unlike the poke scripts: cyan_count() is
                       # imported by its own validation and by tests
