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

This mirrors :mod:`core.audio_slots`.  A replacement that already matches the
slot's container / codec / resolution / frame rate / alpha is copied through
verbatim (no conversion); otherwise matching it is a re-encode and needs
ffmpeg.
"""

import os
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional

from .audio_slots import replace_with_retry
from .video import (VIDEO_EXTS, VideoInfo, backend_for, detect_video_info,
                    encode_replacement, find_ffmpeg, transcode_video_to)


@dataclass
class VideoSlot:
    """One replaceable video file found in an extracted assets folder."""
    rel_path: str                  # forward-slash path relative to assets_dir
    abs_path: str
    ext: str                       # ".mp4" / ".mov" / ".webm" / ".ogv" / …
    info: Optional[VideoInfo]      # None if not yet probed / ffprobe failed
    size: int
    probed: bool = False           # True once ffprobe has been attempted

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
        # Floor, don't round: the preview player's readout floors, and the
        # two disagreeing on the same clip (25.5 s showing 0:26 in the list
        # but 0:25 in the player) read as a bug (monkeybug batch 14).
        m, s = divmod(int(d), 60)
        return f"{m}:{s:02d}"


def scan_video_slots(assets_dir: str, roots=None, exts=None,
                     probe: bool = True) -> List[VideoSlot]:
    """Walk *assets_dir* and return a VideoSlot for every video file, sorted
    by relative path.  Hidden dot-folders and our own ``*.stage.*`` temp files
    are skipped.

    *roots* optionally restricts the walk to specific subdirectories (still
    reporting paths relative to *assets_dir*) — used by plugins whose editable
    video lives in a known surface.  ``None`` scans the whole tree.

    *exts* optionally narrows which video extensions count as slots (default
    :data:`core.video.VIDEO_EXTS`).  Spooky passes ``(".ogv",)`` so only its
    repackable Godot videos surface, not Unity ``.webm`` pulled from bundles.

    *probe* controls whether ffprobe metadata (duration / resolution / codec)
    is read during the walk.  Probing spawns one ffprobe process per file,
    which is far too slow for a folder of hundreds of clips, so the GUI passes
    ``probe=False`` to list slots instantly and fills metadata in afterwards on
    a background thread (each unprobed slot has ``probed=False`` until then).
    Custom-backend files
    (``.cdmd``) are *always* probed — their info is pure-Python (a 16-byte
    header read) and also tells us whether the file is a real clip vs. a font
    glyph / single-frame still that should be dropped.
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
                is_backend = backend_for(abs_path) is not None
                if is_backend:
                    # Cheap pure-Python info; also filters non-video .cdmd
                    # (font glyphs, single-frame stills) — drop those.
                    info = detect_video_info(abs_path)
                    if info is None:
                        continue
                elif probe:
                    info = detect_video_info(abs_path)
                else:
                    info = None
                rel = os.path.relpath(abs_path, assets_dir).replace(os.sep, "/")
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    size = 0
                slots.append(VideoSlot(
                    rel_path=rel, abs_path=abs_path, ext=ext,
                    info=info, size=size, probed=is_backend or probe))

    slots.sort(key=lambda s: s.rel_path.lower())
    return slots


def _already_matches(slot: VideoSlot, replacement_path: str, rep_ext: str,
                     match_length: bool = False, fps_tol: float = 0.05) -> bool:
    """True when *replacement_path* is already in the slot's exact container,
    codec, resolution, frame rate and alpha (and, when *match_length*, also its
    duration) — so it can be copied through verbatim rather than re-encoded.

    Deliberately strict: any unknown/ambiguous field returns False so we fall
    back to a (lossy but correct) re-encode rather than copying through a file
    that might not drop cleanly into the slot.  Pixel-format/profile nuances
    aren't compared, so a hardware decoder *could* still object — but the user
    supplied a byte-for-byte-format-matching clip, which is exactly the
    "no conversion" path they asked for.
    """
    if rep_ext != slot.ext:
        return False
    si = slot.info
    if si is None or not si.width or not si.height:
        return False                      # can't prove a match → re-encode
    ri = detect_video_info(replacement_path)
    if ri is None:
        return False
    if (ri.width, ri.height) != (si.width, si.height):
        return False
    if (ri.vcodec or "").lower() != (si.vcodec or "").lower():
        return False
    if si.fps > 0 and abs(ri.fps - si.fps) > fps_tol:
        return False
    if bool(ri.has_alpha) != bool(si.has_alpha):
        return False
    if match_length and si.duration > 0 and abs(ri.duration - si.duration) > 0.05:
        return False
    return True


def stage_replacement(slot: VideoSlot, replacement_path: str,
                      trim_to_length: bool = False, no_conversion: bool = False,
                      cancel_cb=None):
    """Stage a single replacement over *slot*.

    With *no_conversion* set, the replacement is copied through verbatim and
    must already be in the slot's container (no re-encode at all — the user
    vouches it's playable); a different container is rejected, and a custom
    backend format (``.cdmd``) can't be copied as-is so it's rejected too.

    Otherwise: when the replacement is *already* in the slot's exact container /
    codec / resolution / frame rate / alpha (see :func:`_already_matches`) it's
    copied through verbatim — no re-encode, no generation loss.  Failing that
    it's re-encoded into the slot's container / codec, scaled to the slot's
    resolution (preserving alpha for formats that carry it), and written
    atomically over ``slot.abs_path``.  Slots in a custom-backend format
    (``.cdmd``) are routed to that backend's encoder instead.  When ffmpeg is
    unavailable a same-extension replacement is copied as-is (best effort, no
    conversion); any other case fails with a clear message.

    Returns ``(ok, detail)`` — on success *detail* summarises the conversions
    applied (may be empty, or note a copy-through); on failure it's an error
    message.
    """
    if not os.path.isfile(replacement_path):
        return False, "replacement file not found"

    rep_ext = os.path.splitext(replacement_path)[1].lower()
    tmp = slot.abs_path + ".stage" + slot.ext
    has_backend = backend_for(slot.abs_path) is not None

    try:
        if no_conversion:
            # User forced 'use my file as-is'.  Only a verbatim copy is allowed,
            # so the container must match and custom formats (which *require* an
            # encode) are refused with a clear reason.
            if has_backend:
                return False, (
                    f"'no conversion' can't be used for {slot.ext} (a custom "
                    f"format that must be re-encoded) — uncheck it for this clip")
            if rep_ext != slot.ext:
                return False, (
                    f"'no conversion' needs a {slot.ext} file (got "
                    f"{rep_ext or 'this file'}) — uncheck it to convert")
            shutil.copy2(replacement_path, tmp)
            detail = "copied as-is (no conversion)"
        elif has_backend:
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
        elif _already_matches(slot, replacement_path, rep_ext,
                              match_length=trim_to_length):
            # No conversion needed — the clip already matches the slot's
            # container/codec/resolution/fps/alpha, so copy it through verbatim
            # (no quality loss, and far faster than a re-encode).  Tried before
            # the re-encode branch; the probe it relies on needs ffprobe, so
            # without ffmpeg this is False and the same-ext copy below applies.
            shutil.copy2(replacement_path, tmp)
            detail = "copied through (already matches — no re-encode)"
        elif find_ffmpeg():
            ok, detail = transcode_video_to(
                replacement_path, tmp, slot.info,
                match_length=trim_to_length, cancel_cb=cancel_cb)
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

        replace_with_retry(tmp, slot.abs_path)
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
                       no_conversion: bool = False,
                       log_cb=None, progress_cb=None, assets_dir=None,
                       cancel_cb=None):
    """Stage every assignment in *assignments* (rel_path -> replacement path).

    *slots_by_rel* maps the same rel_path keys to their VideoSlot.  Returns
    ``(staged, failures)`` where *failures* is a list of ``(rel_path, error)``.
    Optional *log_cb(text, level)* and *progress_cb(current, total, desc)*
    drive the GUI log + progress bar.

    *assets_dir*, when given, snapshots each slot's pristine bytes under
    ``.orig/`` before the first overwrite so the edit can be reverted without a
    full re-extract (see :mod:`core.staged_originals`).

    *cancel_cb* (returns truthy to abort) stops before the next item and is
    also polled inside each re-encode, so a user Cancel takes effect within
    seconds even mid-encode of a long clip.
    """
    from .checksums import read_baseline_any
    from . import staged_originals

    items = [(rel, rep) for rel, rep in assignments.items()
             if rep and rel in slots_by_rel]
    total = len(items)
    staged = 0
    failures: List = []
    baseline = read_baseline_any(assets_dir) if assets_dir else {}

    for i, (rel, rep) in enumerate(items):
        if cancel_cb is not None and cancel_cb():
            if log_cb:
                log_cb("Cancelled — skipping the remaining video "
                       "replacement(s).", "error")
            break
        slot = slots_by_rel[rel]
        if progress_cb:
            progress_cb(i, total, rel)
        if log_cb:
            log_cb(f"Staging {rel}  ←  {os.path.basename(rep)}", "info")
        if assets_dir:
            staged_originals.snapshot(assets_dir, rel, baseline.get(rel))
        ok, detail = stage_replacement(slot, rep, trim_to_length=trim_to_length,
                                       no_conversion=no_conversion,
                                       cancel_cb=cancel_cb)
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
