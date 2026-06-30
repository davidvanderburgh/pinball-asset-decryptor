"""Audio-slot scanning + replacement staging for the 'Replace Audio' GUI tab.

A *slot* is an audio file (.wav / .ogg) that already exists in an extracted
assets folder.  The GUI lists every slot with its original name + format,
lets the user assign a replacement file of *any* audio format, and then this
module *stages* those assignments: each replacement is format-matched to the
slot it replaces (codec / channels / sample-rate / bit-depth, optionally
duration) and written over the original file in the assets folder.

Because the staged file lands at the original's exact path + name, the
existing per-manufacturer Write pipeline picks it up as a changed asset and
repacks it — no manual copy-paste-and-rename by the user.  This module is
manufacturer-agnostic; it only relies on every file-based plugin laying its
audio down as loose .wav/.ogg files (JJP, Spooky, American Pinball, Pinball
Brothers, Dutch Pinball).
"""

import os
import shutil
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .audio import (AudioInfo, detect_audio_info, find_ffmpeg,
                    process_modified_audio, transcode_to)

# Audio containers we treat as replaceable slots.
AUDIO_EXTS = (".wav", ".ogg")


def replace_with_retry(src, dst, attempts=6, base_delay=0.1):
    """``os.replace(src, dst)`` hardened against transient Windows sharing
    locks.  Shared by the audio / video / image slot stagers (see
    :mod:`core.video_slots`, :mod:`core.image_slots`).

    On network shares (SMB / NAS — e.g. ``//server/...``) and machines with
    antivirus, the Search indexer, or a media preview holding the destination,
    the atomic rename can fail with ``PermissionError`` ([WinError 5] Access is
    denied, or [WinError 32] the file is in use) even when nothing is durably
    wrong: the lock clears in a fraction of a second.  Retry a few times with a
    short exponential backoff; if it still won't rename, fall back to
    overwriting the destination's *contents* in place (copy + unlink the temp),
    which doesn't have to delete the destination first and so survives a
    lingering reader.  Re-raises the last error only if every path fails."""
    last = None
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:               # WinError 5 / 32 -> PermissionError
            last = e
            time.sleep(base_delay * (2 ** i))
    # Last resort: overwrite contents (no destination unlink, so a held read
    # handle on the original no longer blocks us).
    try:
        shutil.copyfile(src, dst)
        try:
            os.remove(src)
        except OSError:
            pass
        return
    except OSError:
        pass
    raise last

# Replacement inputs the user may drop in (we transcode the rest via ffmpeg).
REPLACEMENT_EXTS = (".wav", ".ogg", ".mp3", ".flac", ".m4a", ".aac",
                    ".opus", ".wma", ".aiff", ".aif")


@dataclass
class AudioSlot:
    """One replaceable audio file found in an extracted assets folder."""
    rel_path: str                  # forward-slash path relative to assets_dir
    abs_path: str
    ext: str                       # ".wav" / ".ogg"
    info: Optional[AudioInfo]      # None if the header couldn't be parsed
    size: int

    @property
    def folder(self) -> str:
        """Parent folder of the slot (\"\" for files at the assets root)."""
        return os.path.dirname(self.rel_path)

    @property
    def duration(self) -> float:
        """Length in seconds (0.0 when the header couldn't be parsed)."""
        return self.info.duration if self.info else 0.0

    def format_summary(self) -> str:
        """One-line, human-readable format string for the slot list."""
        if self.info is None:
            return self.ext.lstrip(".").upper()
        i = self.info
        parts = [self.ext.lstrip(".").upper()]
        if i.sample_rate:
            parts.append(f"{i.sample_rate / 1000:.1f}kHz".replace(".0kHz", "kHz"))
        if i.channels:
            parts.append("mono" if i.channels == 1
                         else "stereo" if i.channels == 2
                         else f"{i.channels}ch")
        if i.bit_depth:
            parts.append(f"{i.bit_depth}-bit")
        return " ".join(parts)

    def duration_str(self) -> str:
        d = self.duration
        if d <= 0:
            return "—"
        # Show milliseconds (m:ss.mmm).  Users who trim tracks to an exact
        # length rely on the ms to line a replacement back up if the title
        # later moves the slot around.
        total_ms = int(round(d * 1000))
        m, rem = divmod(total_ms, 60000)
        s, ms = divmod(rem, 1000)
        return f"{m}:{s:02d}.{ms:03d}"


def scan_audio_slots(assets_dir: str, roots=None, exts=None) -> List[AudioSlot]:
    """Walk *assets_dir* and return AudioSlot for every .wav/.ogg file,
    sorted by relative path.  Hidden dot-folders and our own ``*.stage.*``
    temp files are skipped.

    *roots* optionally restricts the walk to specific subdirectories (still
    reporting paths relative to *assets_dir*).  Plugins whose audio lives in
    a known edit surface use this — CGC points it at the decoded ``<bnk>/``
    dirs, BoF at the ``_EDITABLE ASSETS`` folder — so the list shows only the
    files Write can actually repack, not unrelated derivatives.  ``None``
    scans the whole tree (the default for loose-file plugins).

    *exts* optionally narrows which audio extensions count as slots (default
    both ``.wav`` and ``.ogg``).  BoF passes ``(".wav",)`` because its Write
    can't yet repack edited ``.ogg`` from the editable folder.
    """
    slots: List[AudioSlot] = []
    if not assets_dir or not os.path.isdir(assets_dir):
        return slots

    allowed = tuple(e.lower() for e in exts) if exts else AUDIO_EXTS
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
                rel = os.path.relpath(abs_path, assets_dir).replace(os.sep, "/")
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    size = 0
                slots.append(AudioSlot(
                    rel_path=rel, abs_path=abs_path, ext=ext,
                    info=detect_audio_info(abs_path), size=size))

    slots.sort(key=lambda s: s.rel_path.lower())
    return slots


def stage_replacement(slot: AudioSlot, replacement_path: str,
                      trim_to_length: bool = False):
    """Stage a single replacement over *slot*.

    The replacement is converted into the slot's native container/format
    (transcoding from mp3/flac/etc. via ffmpeg when needed), then written
    atomically over ``slot.abs_path``.

    Returns ``(ok, detail)`` — on success *detail* is a short string of the
    conversions applied (may be empty); on failure it's an error message.
    """
    if not os.path.isfile(replacement_path):
        return False, "replacement file not found"

    rep_ext = os.path.splitext(replacement_path)[1].lower()
    tmp = slot.abs_path + ".stage" + slot.ext
    actions: List[str] = []

    try:
        if rep_ext == slot.ext:
            # Same container — copy, then let process_modified_audio align
            # channels / sample-rate / bit-depth (and length if asked).
            shutil.copy2(replacement_path, tmp)
        else:
            # Different container — must transcode into the slot's codec.
            if not find_ffmpeg():
                return False, (
                    f"need ffmpeg to convert {rep_ext or 'this file'} "
                    f"→ {slot.ext}")
            if not transcode_to(replacement_path, tmp, slot.info):
                return False, f"ffmpeg failed converting to {slot.ext}"
            actions.append(f"{rep_ext.lstrip('.')}→{slot.ext.lstrip('.')}")

        if slot.info is not None:
            actions.extend(process_modified_audio(
                tmp, slot.info, keep_original_length=not trim_to_length))

        replace_with_retry(tmp, slot.abs_path)
        return True, ", ".join(actions)
    except (OSError, ValueError) as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False, str(e)


def stage_replacements(slots_by_rel: Dict[str, AudioSlot],
                       assignments: Dict[str, str],
                       trim_to_length: bool = False,
                       log_cb=None, progress_cb=None, assets_dir=None,
                       keep_full_rels=None):
    """Stage every assignment in *assignments* (rel_path -> replacement path).

    *slots_by_rel* maps the same rel_path keys to their AudioSlot.  Returns
    ``(staged, failures)`` where *failures* is a list of ``(rel_path, error)``.
    Optional *log_cb(text, level)* and *progress_cb(current, total, desc)*
    drive the GUI log + progress bar.

    *keep_full_rels*, when given, is a set of rel_paths exempted from
    *trim_to_length* — those slots are always staged at their replacement's full
    length (the per-slot "keep full length" override; see the JJP plugin).

    *assets_dir*, when given, enables the pristine-original snapshot: the first
    time each slot is overwritten its baseline-matching bytes are backed up under
    ``.orig/`` so the edit can be reverted later without a full re-extract (see
    :mod:`core.staged_originals`).
    """
    from .checksums import read_baseline_any
    from . import staged_originals

    items = [(rel, rep) for rel, rep in assignments.items()
             if rep and rel in slots_by_rel]
    total = len(items)
    staged = 0
    failures: List = []
    keep_full = frozenset(keep_full_rels or ())
    baseline = read_baseline_any(assets_dir) if assets_dir else {}

    for i, (rel, rep) in enumerate(items):
        slot = slots_by_rel[rel]
        if progress_cb:
            progress_cb(i, total, rel)
        if log_cb:
            log_cb(f"Staging {rel}  ←  {os.path.basename(rep)}", "info")
        if assets_dir:
            staged_originals.snapshot(assets_dir, rel, baseline.get(rel))
        slot_trim = trim_to_length and rel not in keep_full
        ok, detail = stage_replacement(slot, rep, trim_to_length=slot_trim)
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
