"""Video-slot scanning + replacement staging for the 'Replace Video' GUI tab.

A *slot* is a video file (.mp4 / .mov / .webm / .ogv / …) that already exists
in an extracted assets folder.  The GUI lists every slot with its original
name, length, resolution + format, lets the user assign a replacement clip of
*any* video format, and then this module *stages* those assignments: each
replacement is format-matched to the slot it replaces (container / codec,
resolution, frame rate, alpha, optionally duration) and written over the
original file in the assets folder.

Because the staged file lands at the original's exact path + name, the
existing per-manufacturer Write pipeline picks it up as a changed asset and
repacks it — no manual copy-paste-and-rename by the user.  This module is
manufacturer-agnostic; it relies on the plugin laying its video down as loose
files the Write step repacks (JJP loose containers, Dutch Pinball AAIW
.mp4/.mov, Spooky Godot .ogv).  Plugins whose video can't round-trip (Dutch
Pinball TBL .cdmd, BoF .ctex with no inverse encoder yet) don't enable the
``replace_video`` capability, so their dead-end files never surface here.

This mirrors :mod:`core.audio_slots`; the video equivalent always needs
ffmpeg (matching resolution / codec is a re-encode), whereas audio could copy
same-format files through.
"""

import os
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional

from .video import (VIDEO_EXTS, VideoInfo, backend_for, detect_video_info,
                    encode_replacement, find_ffmpeg, transcode_video_to)


@dataclass
class VideoSlot:
    """One replaceable video file found in an extracted assets folder."""
    rel_path: str                  # forward-slash path relative to assets_dir
    abs_path: str
    ext: str                       # ".mp4" / ".mov" / ".webm" / ".ogv" / …
    info: Optional[VideoInfo]      # None if ffprobe couldn't read it
    size: int

    @property
    def folder(self) -> str:
        """Parent folder of the slot (\"\" for files at the assets root)."""
        return os.path.dirname(self.rel_path)

    @property
    def duration(self) -> float:
        """Length in seconds (0.0 when ffprobe couldn't read it)."""
        return self.info.duration if self.info else 0.0

    def resolution_str(self) -> str:
        if self.info and self.info.width and self.info.height:
            return f"{self.info.width}×{self.info.height}"
        return "—"

    def format_summary(self) -> str:
        """One-line, human-readable format string for the slot list."""
        base = self.ext.lstrip(".").upper()
        if self.info is None:
            return base
        parts = [base]
        # Skip the codec when it just restates the container (e.g. CDMD/cdmd).
        if self.info.vcodec and self.info.vcodec.lower() != base.lower():
            parts.append(self.info.vcodec)
        if self.info.fps:
            parts.append(f"{self.info.fps:.0f}fps")
        if self.info.has_alpha:
            parts.append("alpha")
        return " ".join(parts)

    def duration_str(self) -> str:
        d = self.duration
        if d <= 0:
            return "—"
        m, s = divmod(int(round(d)), 60)
        return f"{m}:{s:02d}"


def scan_video_slots(assets_dir: str, roots=None, exts=None) -> List[VideoSlot]:
    """Walk *assets_dir* and return a VideoSlot for every video file, sorted
    by relative path.  Hidden dot-folders and our own ``*.stage.*`` temp files
    are skipped.

    *roots* optionally restricts the walk to specific subdirectories (still
    reporting paths relative to *assets_dir*) — used by plugins whose editable
    video lives in a known surface.  ``None`` scans the whole tree.

    *exts* optionally narrows which video extensions count as slots (default
    :data:`core.video.VIDEO_EXTS`).  Spooky passes ``(".ogv",)`` so only its
    repackable Godot videos surface, not Unity ``.webm`` pulled from bundles.
    """
    slots: List[VideoSlot] = []
    if not assets_dir or not os.path.isdir(assets_dir):
        return slots

    allowed = tuple(e.lower() for e in exts) if exts else VIDEO_EXTS
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
                info = detect_video_info(abs_path)
                # Custom-backend formats (.cdmd) reuse one extension for both
                # video clips and non-video data (font glyphs, single-frame
                # stills); the backend returns None for the latter, so drop
                # them rather than offering a dead slot.
                if info is None and backend_for(abs_path) is not None:
                    continue
                rel = os.path.relpath(abs_path, assets_dir).replace(os.sep, "/")
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    size = 0
                slots.append(VideoSlot(
                    rel_path=rel, abs_path=abs_path, ext=ext,
                    info=info, size=size))

    slots.sort(key=lambda s: s.rel_path.lower())
    return slots


def stage_replacement(slot: VideoSlot, replacement_path: str,
                      trim_to_length: bool = False):
    """Stage a single replacement over *slot*.

    The replacement is re-encoded into the slot's container / codec, scaled to
    the slot's resolution (preserving alpha for formats that carry it), and
    written atomically over ``slot.abs_path``.  Slots in a custom-backend
    format (``.cdmd``) are routed to that backend's encoder instead.  When
    ffmpeg is unavailable a same-extension replacement is copied as-is (best
    effort, no conversion); any other case fails with a clear message.

    Returns ``(ok, detail)`` — on success *detail* summarises the conversions
    applied (may be empty); on failure it's an error message.
    """
    if not os.path.isfile(replacement_path):
        return False, "replacement file not found"

    rep_ext = os.path.splitext(replacement_path)[1].lower()
    tmp = slot.abs_path + ".stage" + slot.ext
    has_backend = backend_for(slot.abs_path) is not None

    try:
        if has_backend:
            ok, detail = encode_replacement(
                replacement_path, tmp, slot.info, slot.abs_path,
                match_length=trim_to_length)
            if not ok:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return False, detail
        elif find_ffmpeg():
            ok, detail = transcode_video_to(
                replacement_path, tmp, slot.info,
                match_length=trim_to_length)
            if not ok:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return False, detail
        elif rep_ext == slot.ext:
            # No ffmpeg, but the user supplied the same container — copy it
            # through unchanged (it won't be resolution/codec-matched).
            shutil.copy2(replacement_path, tmp)
            detail = "copied (no ffmpeg — not re-encoded)"
        else:
            return False, (
                f"need ffmpeg to convert {rep_ext or 'this file'} "
                f"→ {slot.ext}")

        os.replace(tmp, slot.abs_path)
        return True, detail
    except (OSError, ValueError) as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False, str(e)


def stage_replacements(slots_by_rel: Dict[str, VideoSlot],
                       assignments: Dict[str, str],
                       trim_to_length: bool = False,
                       log_cb=None, progress_cb=None):
    """Stage every assignment in *assignments* (rel_path -> replacement path).

    *slots_by_rel* maps the same rel_path keys to their VideoSlot.  Returns
    ``(staged, failures)`` where *failures* is a list of ``(rel_path, error)``.
    Optional *log_cb(text, level)* and *progress_cb(current, total, desc)*
    drive the GUI log + progress bar.
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
        ok, detail = stage_replacement(slot, rep, trim_to_length=trim_to_length)
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
