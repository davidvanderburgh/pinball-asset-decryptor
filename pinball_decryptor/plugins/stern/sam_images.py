"""Stern S.A.M. (2006-2014) pictures and fonts: Extract every still picture
and font glyph of a code update to PNGs, and write edited ones back.

The format lives in :mod:`..pinmame_classic.sam_art`; this is the
Extract / Write / Revert contract over it (the sounds' twin is
:mod:`.sam_audio`, whose ``write_image`` calls :func:`patch`):

* Extract writes each plain picture to
  ``images/pictures/imgNNNN.png`` and each font glyph to
  ``images/fonts/fontNN (H px)/imgNNNN.png`` (``NNNN`` = the game's
  picture number; a font's glyphs are numbered in its character order), as grey
  + alpha: shade ``s`` of the DMD's 16 is grey ``s * 17``, a transparent
  pixel is alpha 0.
* Write takes the PNGs that differ from the extract's checksum baseline,
  fits each to its picture's size, takes its grey to the nearest shade
  (alpha under half to transparent) and writes it over the picture in
  place.  The file doesn't move or grow.
"""

import os
import re

import numpy as np

from ...core import checksums
from ...core.longpath import ext as _lp
from ..pinmame_classic import sam_art

_IMG_RE = re.compile(r"img(\d{4,5})(?![0-9])", re.IGNORECASE)
IMAGES = "images"


class SamImagesError(Exception):
    pass


class SamImagesCancelled(SamImagesError):
    pass


def parse_stem(stem):
    """The picture number in an extracted PNG's stem, or None."""
    m = _IMG_RE.search(stem)
    return int(m.group(1)) if m else None


def read_art(data):
    try:
        return sam_art.read_art(data)
    except sam_art.SamArtError as e:
        raise SamImagesError("this file's pictures can't be read (%s)" % e)


def rel_path(art, number):
    """Where picture *number* goes under the project folder."""
    stem = "img%04d" % number
    hit = art.glyph_of.get(number)
    if hit is None:
        return "%s/pictures/%s.png" % (IMAGES, stem)
    font = next(f for f in art.fonts if f.number == hit[0])
    return "%s/fonts/font%02d (%d px)/%s.png" % (IMAGES, font.number,
                                                 font.height, stem)


def _save(path, data, bm):
    from PIL import Image
    la = sam_art.to_la(sam_art.pixels(data, bm))
    tmp = path + ".part.png"
    Image.fromarray(la, "LA").save(_lp(tmp), format="PNG")
    os.replace(_lp(tmp), _lp(path))


def extract_all(data, output_dir, log=None, progress=None, cancel=None):
    """Write every plain picture of *data* (the game file's bytes) under
    ``output_dir/images``.  Returns ``{"pictures", "fonts", "glyphs"}``."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    art = read_art(data)
    log("Picture table: %d pictures, %d of them plain (still pictures and "
        "font glyphs), %d fonts" % (art.entries, len(art.bitmaps),
                                    len(art.fonts)))
    n = len(art.bitmaps)
    made = set()
    for i, bm in enumerate(art.bitmaps.values()):
        if check():
            raise SamImagesCancelled("cancelled")
        path = os.path.join(output_dir, *rel_path(art, bm.number).split("/"))
        d = os.path.dirname(path)
        if d not in made:
            os.makedirs(_lp(d), exist_ok=True)
            made.add(d)
        _save(path, data, bm)
        if progress and (i % 32 == 0 or i == n - 1):
            progress(i + 1, n, "Decoding pictures (%d/%d)" % (i + 1, n))
    glyphs = sum(1 for b in art.bitmaps if b in art.glyph_of)
    log("Decoded %d PNGs: %d pictures, %d font glyphs in %d fonts"
        % (n, n - glyphs, glyphs, len(art.fonts)))
    return {"pictures": n - glyphs, "fonts": len(art.fonts),
            "glyphs": glyphs}


def _changed_pngs(assets_dir, log):
    """``{picture number: path}`` for every PNG under images/ changed vs
    the extract's baseline."""
    baseline = checksums.read_checksums(assets_dir)
    out = {}
    root = os.path.join(assets_dir, IMAGES)
    if not os.path.isdir(root):
        return out
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fn in sorted(files):
            if not fn.lower().endswith(".png") or ".stage." in fn \
                    or ".part." in fn or fn.startswith("."):
                continue
            number = parse_stem(os.path.splitext(fn)[0])
            if number is None:
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, assets_dir).replace(os.sep, "/")
            base = baseline.get(rel)
            if base is not None and checksums.md5_file(p) == base:
                continue
            if number in out:
                log("  note: %s and %s are the same picture; using %s"
                    % (os.path.basename(out[number]), fn,
                       os.path.basename(out[number])))
            else:
                out[number] = p
    return out


def load_pixels(path, bm):
    """A PNG (or any picture Pillow reads) as *bm*'s pixels: fit to its
    size, grey to the nearest shade, alpha under half to transparent.
    Returns ``(pixels, note)``; *note* says what had to change."""
    from PIL import Image
    note = []
    with Image.open(_lp(path)) as im:
        im.load()
        rgba = im.convert("RGBA")
    if rgba.size != (bm.width, bm.height):
        note.append("scaled from %dx%d to %dx%d" % (rgba.size + (bm.width,
                                                                 bm.height)))
        rgba = rgba.resize((bm.width, bm.height), Image.LANCZOS)
    la = np.asarray(rgba.convert("LA"))
    px = sam_art.from_la(la, transparent=bm.fmt == sam_art.RAW8)
    if bm.fmt == sam_art.RAW4 and (la[..., 1] < 128).any():
        note.append("transparent pixels made black (this picture has no "
                    "transparency)")
    return px, ", ".join(note)


def patch(image, data, assets_dir, log=None, progress=None, cancel=None):
    """Write the changed PNGs under ``assets_dir/images`` into *image* (a
    bytearray copy of *data*).  Returns ``(changes, written, skipped)``:
    ``[(start, end, byte-sum delta)]`` for the checksums, the count
    written, the names skipped."""
    log = log or (lambda *a, **k: None)
    check = cancel or (lambda: False)
    changed = _changed_pngs(assets_dir, log)
    if not changed:
        return [], 0, []
    log("Changed pictures: %d" % len(changed))
    art = read_art(bytes(image))
    changes, skipped = [], []
    items = sorted(changed.items())
    for n, (number, path) in enumerate(items):
        if check():
            raise SamImagesCancelled("cancelled")
        name = os.path.basename(path)
        bm = art.bitmaps.get(number)
        if bm is None:
            skipped.append(name)
            log("  ! %s: no such picture in this file - skipped" % name,
                "warning")
            continue
        try:
            px, note = load_pixels(path, bm)
            delta = sam_art.replace(image, bm, px)
        except Exception as e:                       # noqa: BLE001
            skipped.append(name)
            log("  ! %s could not be written (%s) - skipped, the picture "
                "stays as it was" % (name, e), "warning")
            continue
        changes.append((bm.data_offset, bm.data_offset + bm.data_size,
                        delta))
        log("  img%04d <- %s (%dx%d%s)"
            % (number, name, bm.width, bm.height, ", " + note if note else ""))
        if progress:
            progress(n + 1, len(items), "Writing pictures")
    return changes, len(changes), skipped


def revert(data, assets_dir, rels, log=None):
    """Re-decode the original PNGs for *rels* (``images/...``) from *data*.
    Returns ``(reverted, failed)``."""
    log = log or (lambda *a, **k: None)
    art = read_art(data)
    reverted, failed = [], []
    for rel in rels:
        number = parse_stem(os.path.splitext(os.path.basename(rel))[0])
        bm = art.bitmaps.get(number) if number is not None else None
        if bm is None:
            failed.append(rel)
            log("  ! %s: no matching picture in the source file" % rel)
            continue
        _save(os.path.join(assets_dir, rel.replace("/", os.sep)), data, bm)
        reverted.append(rel)
        log("  restored %s" % rel)
    return reverted, failed
