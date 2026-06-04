"""Cactus Canyon display-art → animation MP4s (colour dot-matrix shader).

The colour LCD images decoded from ``cgc.so`` (``display_art/*.png``) include
many animation sequences — frames named ``<base>_NN`` / ``<base>NN`` (e.g.
``bandelero_hit_01..08``, ``Combo5_1..7``, ``cowboy_intro04..``).  This module
groups those sequences and renders each to an MP4, running every frame through
the same colour dot-matrix "DMD" shader the other CGC/DP videos use
(``dp.cdmd.render_dmd`` — each pixel becomes a round LED dot with bloom on a
black bezel), then assembling the frames with ffmpeg
(``williams.dmd_render.render_pngs_to_mp4``).

Output is extract-only (there are no video files inside the eMMC — the engine
renders the display live), so the ``videos/`` dir is excluded from the Write
baseline like the other derived dirs.
"""

from __future__ import annotations

import glob as _glob
import os
import re
import shutil
import tempfile
from typing import Callable, Dict, List, Optional

# display_art names are "<artidx:04d>_<name>.png"; an animation frame's <name>
# ends in an optional separator + a frame number.
_FRAME_RE = re.compile(r"^(\d+)_(.+?)[ _-]?(\d+)$")

CC_ANIM_FPS = 15          # preview rate (the engine's true timing isn't shipped)
_MIN_FRAMES = 2           # a "video" needs at least two frames


def _sanitize(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


def group_frames(display_art_dir: str) -> Dict[str, List[str]]:
    """Group ``display_art`` PNGs into ``base -> [frame paths in order]``.

    Only multi-frame sequences whose frame numbers form a reasonably dense run
    are returned (guards against false-grouping unrelated stills that merely
    share a stripped base)."""
    buckets: Dict[str, List[tuple]] = {}
    for p in _glob.glob(os.path.join(display_art_dir, "*.png")):
        stem = os.path.splitext(os.path.basename(p))[0]
        m = _FRAME_RE.match(stem)
        if not m:
            continue
        base, frame = m.group(2), int(m.group(3))
        buckets.setdefault(base, []).append((frame, p))
    out: Dict[str, List[str]] = {}
    for base, items in buckets.items():
        if len(items) < _MIN_FRAMES:
            continue
        items.sort(key=lambda t: t[0])
        frames = [t[0] for t in items]
        # Density guard: reject sparse/coincidental groups.
        if (frames[-1] - frames[0]) > len(frames) * 2:
            continue
        out[base] = [p for _, p in items]
    return out


def render_animations(display_art_dir: str, out_dir: str,
                      log_cb: Optional[Callable[[str, str], None]] = None,
                      progress_cb: Optional[Callable[[int, int, str], None]]
                      = None, fps: int = CC_ANIM_FPS) -> int:
    """Render every animation sequence in *display_art_dir* to an MP4 in
    *out_dir*, with the colour dot-matrix shader.  Returns the MP4 count
    (0 if ffmpeg is missing or there are no sequences)."""
    from PIL import Image

    from ..dp.cdmd import render_dmd
    from ..williams.dmd_render import find_ffmpeg, render_pngs_to_mp4

    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    if find_ffmpeg() is None:
        log("  ffmpeg not found — skipping display-art video render "
            "(install ffmpeg to enable).", "warning")
        return 0
    groups = group_frames(display_art_dir)
    if not groups:
        return 0
    os.makedirs(out_dir, exist_ok=True)

    made = 0
    items = sorted(groups.items())
    for gi, (base, paths) in enumerate(items):
        # Keep only frames sharing the most common source size (an MP4 needs
        # uniform dimensions).
        by_size: Dict[tuple, List[str]] = {}
        for p in paths:
            try:
                by_size.setdefault(Image.open(p).size, []).append(p)
            except Exception:
                continue
        if not by_size:
            continue
        frames = max(by_size.values(), key=len)
        if len(frames) < _MIN_FRAMES:
            continue
        tmp = tempfile.mkdtemp(prefix="cc_anim_")
        try:
            rendered = []
            for i, p in enumerate(frames):
                img = Image.open(p).convert("RGBA")
                fp = os.path.join(tmp, f"f_{i:06d}.png")
                render_dmd(img).save(fp)
                rendered.append(fp)
            render_pngs_to_mp4(
                rendered, os.path.join(out_dir, f"{_sanitize(base)}.mp4"),
                fps=fps)
            made += 1
        except Exception as e:
            log(f"  {base}: video render failed ({e})", "warning")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if progress_cb:
            progress_cb(gi + 1, len(items), base)
    return made
