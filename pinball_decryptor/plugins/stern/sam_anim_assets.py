"""Stern S.A.M. DMD animation frames as project files: Extract, Write
(patch), Revert -- the animation half of the art; the still pictures and
fonts are :mod:`.sam_images` (PAD-583).

The format is :mod:`..pinmame_classic.sam_anim`.  Every graphics-table
record that isn't a plain picture -- the run-length and delta frames, and
any keyframe a delta builds on -- is one ``animations/imgNNNN.png``
(``NNNN`` = its place in the graphics table, the numbering the pictures
use too, so an animation's frames sort together across both folders):
8-bit grey + alpha, shade ``v`` as ``v * 17``, transparent as alpha 0.
The game plays an animation by stepping through record numbers, so the
frames of one are consecutive numbers.

Write re-encodes each changed PNG (and every delta frame after it, so
the frames the game shows are the edited ones and the original ones
everywhere else) in the shortest exact form its place allows, into its
own bytes or the bytes of the run of frames around it
(:func:`sam_anim.plan_write`).  The art area is full, so a frame that
can't fit even then is written with fewer shades, or keeps its original
picture; the log names each one.
"""

import os
import re

import numpy as np

from ...core import checksums
from ...core.longpath import ext as _lp
from ..pinmame_classic import sam_anim

FOLDER = "animations"
_NUM_RE = re.compile(r"img(\d{4,5})(?![0-9])", re.IGNORECASE)


class SamAnimAssetError(Exception):
    pass


_FORMAT_WORDS = {0: "raw", 12: "4-bit", 1: "run-length", 7: "run-length",
                 8: "run-length", 3: "delta", 9: "delta", 10: "delta"}


def png_name(number):
    return "img%04d.png" % number


def parse_png_stem(stem):
    m = _NUM_RE.search(stem)
    return int(m.group(1)) if m else None


def to_la(frame):
    """``uint8 [h, w, 2]`` grey + alpha of a decoded frame."""
    out = np.empty(frame.shape + (2,), np.uint8)
    clear = frame == sam_anim.TRANSPARENT
    out[..., 0] = np.where(clear, 0, np.minimum(frame, 15) * 17)
    out[..., 1] = np.where(clear, 0, 255)
    return out


def from_image(img):
    """A frame from a PIL image: any mode; alpha < 128 is transparent, the
    rest the nearest of the 16 shades."""
    if img.mode not in ("L", "LA"):
        img = img.convert("LA" if "A" in img.getbands()
                          or "transparency" in img.info else "L")
    a = np.asarray(img)
    if a.ndim == 2:
        grey, alpha = a, None
    else:
        grey, alpha = a[..., 0], a[..., 1]
    frame = np.minimum((grey.astype(np.int32) + 8) // 17, 15).astype(np.uint8)
    if alpha is not None:
        frame[alpha < 128] = sam_anim.TRANSPARENT
    return frame


def _save(path, frame):
    from PIL import Image
    tmp = path + ".part"
    Image.fromarray(to_la(frame), "LA").save(_lp(tmp), format="PNG")
    os.replace(_lp(tmp), _lp(path))


def _read(data):
    try:
        art = sam_anim.read_table(data)
    except sam_anim.SamAnimError:
        return None
    return art


def extract_all(data, output_dir, log=None, progress=None, cancel=None):
    """Write every animation frame of the image *data* to
    ``output_dir/animations``.  Returns the number written (0 for a title
    with no animation data)."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    art = _read(data)
    if art is None:
        log("No animation frames in this file (its pictures are all "
            "plain ones)")
        return 0
    frames = sam_anim.decode_all(data, art)
    mine = sorted(sam_anim.animation_numbers(data, art))
    if not mine:
        log("No animation frames in this file (its pictures are all "
            "plain ones)")
        return 0
    out_dir = os.path.join(output_dir, FOLDER)
    os.makedirs(_lp(out_dir), exist_ok=True)
    n = len(mine)
    for i, num in enumerate(mine):
        if check():
            raise sam_anim.SamAnimError("cancelled")
        _save(os.path.join(out_dir, png_name(num)), frames[num])
        if progress and (i % 32 == 0 or i == n - 1):
            progress(i + 1, n, "Decoding animations (%d/%d)" % (i + 1, n))
    log("Decoded %d animation frame(s) of %d graphics records"
        % (n, len(art.records)))
    return n


def _changed_pngs(assets_dir, log):
    """``{number: path}`` for every animation PNG changed vs baseline."""
    baseline = checksums.read_checksums(assets_dir)
    folder = os.path.join(assets_dir, FOLDER)
    out = {}
    if not os.path.isdir(_lp(folder)):
        return out
    for fn in sorted(os.listdir(_lp(folder))):
        if not fn.lower().endswith(".png") or ".stage." in fn:
            continue
        num = parse_png_stem(os.path.splitext(fn)[0])
        if num is None:
            continue
        p = os.path.join(folder, fn)
        base = baseline.get(FOLDER + "/" + fn)
        if base is None or checksums.md5_file(p) != base:
            if num in out:
                log("  note: %s and %s are the same frame; using %s"
                    % (os.path.basename(out[num]), fn,
                       os.path.basename(out[num])))
            else:
                out[num] = p
    return out


def patch(image, data, assets_dir, log=None, progress=None, cancel=None):
    """Write the changed animation PNGs into *image* (a bytearray copy of
    the original *data*).  Returns ``(changes, written, skipped)``:
    ``[(start, end, byte-sum delta)]`` for the checksums, the number of
    frames written, and the names left out."""
    from PIL import Image

    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    changed = _changed_pngs(assets_dir, log)
    if not changed:
        return [], 0, []
    art = _read(data)
    if art is None:
        names = [os.path.basename(p) for p in changed.values()]
        log("  ! this file has no animation data - %d animation PNG(s) "
            "skipped" % len(names), "warning")
        return [], 0, names
    mine = sam_anim.animation_numbers(data, art)
    frames = sam_anim.decode_all(data, art)
    log("Changed animation frames: %d" % len(changed))
    edits = {}
    skipped = []
    for num, path in sorted(changed.items()):
        if check():
            raise sam_anim.SamAnimError("cancelled")
        name = os.path.basename(path)
        if num >= len(art.records) or num not in mine:
            skipped.append(name)
            log("  ! %s: no such animation frame in this file - skipped"
                % name, "warning")
            continue
        rec = art.records[num]
        try:
            with Image.open(_lp(path)) as img:
                img.load()
                frame = from_image(img)
        except Exception as e:
            skipped.append(name)
            log("  ! %s could not be read (%s) - skipped" % (name, e),
                "warning")
            continue
        if frame.shape != (rec.height, rec.width):
            skipped.append(name)
            log("  ! %s is %dx%d; this frame is %dx%d - skipped"
                % (name, frame.shape[1], frame.shape[0], rec.width,
                   rec.height), "warning")
            continue
        if rec.fmt == 12:
            # 4-bit frames have no transparency
            frame[frame == sam_anim.TRANSPARENT] = 0
        if np.array_equal(frame, frames[num]):
            continue
        edits[num] = frame
    if not edits:
        return [], 0, skipped
    try:
        plan = sam_anim.plan_write(data, art, frames, edits, mine)
    except sam_anim.SamAnimError as e:
        raise SamAnimAssetError(str(e))
    for num in sorted(edits):
        how = plan.how.get(num, "exact")
        name = png_name(num)
        rec = art.records[num]
        fmt, size = plan.written.get(num, (rec.fmt, rec.length))
        if how == "original":
            skipped.append(name)
            log("  ! %s is too detailed to fit this frame's place even with "
                "two shades - it keeps its original picture" % name,
                "warning")
        elif how != "exact":
            log("  %s: %dx%d, simplified to %s to fit (%s, %d bytes)"
                % (name, rec.width, rec.height, how, _FORMAT_WORDS[fmt],
                   size), "warning")
        else:
            log("  %s: %dx%d (%s, %d bytes)"
                % (name, rec.width, rec.height, _FORMAT_WORDS[fmt], size))
    followers = len(plan.written) - len(edits)
    if followers > 0:
        log("  %d following delta frame(s) re-encoded on the new pictures"
            % followers)
    if plan.moved:
        log("  %d frame(s) moved within their animation's bytes"
            % len(plan.moved))
    changes = sam_anim.apply_plan(image, art, plan)
    written = sum(1 for n in edits if plan.how.get(n) != "original")
    if progress:
        progress(len(edits), len(edits), "Encoding animations")
    return changes, written, skipped


def revert(data, assets_dir, rels, log=None):
    """Re-decode the original PNGs for *rels* (``animations/imgNNNN.png``)
    from the image *data*.  Returns ``(reverted, failed)``."""
    log = log or (lambda *a, **k: None)
    art = _read(data)
    reverted, failed = [], []
    if art is None:
        return reverted, list(rels)
    mine = sam_anim.animation_numbers(data, art)
    frames = sam_anim.decode_all(data, art)
    for rel in rels:
        num = parse_png_stem(os.path.splitext(os.path.basename(rel))[0])
        if num is None or num not in mine:
            failed.append(rel)
            log("  ! %s: no matching animation frame in the source file"
                % rel)
            continue
        _save(os.path.join(assets_dir, rel.replace("/", os.sep)),
              frames[num])
        reverted.append(rel)
        log("  restored %s" % rel)
    return reverted, failed
