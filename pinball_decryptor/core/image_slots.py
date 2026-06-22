"""Image-slot scanning + replacement staging for the 'Replace Image' GUI tab.

A *slot* is an image file (.png / .jpg / .bmp / …) that already exists in an
extracted assets folder.  The GUI lists every slot with its original name,
dimensions + format and a thumbnail, lets the user assign a replacement image
of *any* format, then this module *stages* those assignments: each replacement
is scaled to the slot's pixel dimensions and saved in the slot's format, written
over the original file in the assets folder.

Because the staged file lands at the original's exact path + name, the existing
per-manufacturer Write pipeline picks it up as a changed asset and repacks it.
This mirrors :mod:`core.audio_slots` / :mod:`core.video_slots`; the image
equivalent always needs Pillow (matching dimensions / format is a re-encode).
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .image import (IMAGE_EXTS, ImageInfo, detect_image_info, pil_available,
                    transcode_image_to)


@dataclass
class ImageSlot:
    """One replaceable image file found in an extracted assets folder."""
    rel_path: str                  # forward-slash path relative to assets_dir
    abs_path: str
    ext: str                       # ".png" / ".jpg" / …
    info: Optional[ImageInfo]      # None if not yet probed / Pillow failed
    size: int
    probed: bool = False           # True once Pillow has been attempted

    @property
    def folder(self) -> str:
        """Parent folder of the slot (\"\" for files at the assets root)."""
        return os.path.dirname(self.rel_path)

    def resolution_str(self) -> str:
        if self.info and self.info.width and self.info.height:
            return f"{self.info.width}×{self.info.height}"
        return "—"

    def format_summary(self) -> str:
        """One-line, human-readable format string for the slot list."""
        base = self.ext.lstrip(".").upper()
        if self.info is None:
            return base
        parts = [self.info.fmt or base]
        if self.info.has_alpha:
            parts.append("alpha")
        return " ".join(parts)


def scan_image_slots(assets_dir: str, roots=None, exts=None,
                     probe: bool = True) -> List[ImageSlot]:
    """Walk *assets_dir* and return an ImageSlot for every image file, sorted
    by relative path.  Hidden dot-folders and our own ``*.stage.*`` temp files
    are skipped.

    *roots* optionally restricts the walk to specific subdirectories (still
    reporting paths relative to *assets_dir*).  ``None`` scans the whole tree.
    *exts* optionally narrows which extensions count as slots (default
    :data:`core.image.IMAGE_EXTS`).  *probe* controls whether Pillow metadata
    (dimensions / format) is read during the walk; the GUI passes ``False`` to
    list slots instantly and fills metadata in afterwards on a background pass.
    """
    slots: List[ImageSlot] = []
    if not assets_dir or not os.path.isdir(assets_dir):
        return slots

    allowed = tuple(e.lower() for e in exts) if exts else IMAGE_EXTS
    walk_roots = [r for r in (roots or [assets_dir]) if os.path.isdir(r)]
    seen = set()
    for walk_root in walk_roots:
        for root, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in allowed or ".stage." in fn:
                    continue
                abs_path = os.path.join(root, fn)
                if abs_path in seen:
                    continue
                seen.add(abs_path)
                info = detect_image_info(abs_path) if probe else None
                rel = os.path.relpath(abs_path, assets_dir).replace(os.sep, "/")
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    size = 0
                slots.append(ImageSlot(
                    rel_path=rel, abs_path=abs_path, ext=ext,
                    info=info, size=size, probed=probe))

    slots.sort(key=lambda s: s.rel_path.lower())
    return slots


def stage_replacement(slot: ImageSlot, replacement_path: str):
    """Stage a single replacement over *slot*.

    The replacement is scaled to the slot's pixel dimensions, saved in the
    slot's format, and written atomically over ``slot.abs_path``.  Returns
    ``(ok, detail)`` — on success *detail* summarises the conversions (may be
    empty); on failure it's an error message.
    """
    if not os.path.isfile(replacement_path):
        return False, "replacement file not found"
    if not pil_available():
        return False, "need Pillow to convert images"

    tmp = slot.abs_path + ".stage" + slot.ext
    try:
        info = slot.info or detect_image_info(slot.abs_path)
        ok, detail = transcode_image_to(replacement_path, tmp, info)
        if not ok:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return False, detail
        os.replace(tmp, slot.abs_path)
        return True, detail
    except (OSError, ValueError) as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False, str(e)


def stage_replacements(slots_by_rel: Dict[str, ImageSlot],
                       assignments: Dict[str, str],
                       log_cb=None, progress_cb=None):
    """Stage every assignment in *assignments* (rel_path -> replacement path).

    *slots_by_rel* maps the same rel_path keys to their ImageSlot.  Returns
    ``(staged, failures)`` where *failures* is a list of ``(rel_path, error)``.
    """
    items = [(rel, rep) for rel, rep in assignments.items()
             if rep and rel in slots_by_rel]
    total = len(items)
    staged = 0
    failures: List = []

    for i, (rel, rep) in enumerate(items):
        slot = slots_by_rel[rel]
        if progress_cb:
            progress_cb(i, total, rel)
        if log_cb:
            log_cb(f"Staging {rel}  ←  {os.path.basename(rep)}", "info")
        ok, detail = stage_replacement(slot, rep)
        if ok:
            staged += 1
            if log_cb:
                msg = f"  ✓ {rel}" + (f"  ({detail})" if detail else "")
                log_cb(msg, "success")
        else:
            failures.append((rel, detail))
            if log_cb:
                log_cb(f"  ✗ {rel}: {detail}", "error")

    if progress_cb:
        progress_cb(total, total, "")
    return staged, failures
