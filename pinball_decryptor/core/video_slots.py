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
.mp4/.mov, Spooky's loose .webm, BoF standalone .ogv in the PCK tree).  Plugins
whose video can't round-trip don't enable the ``replace_video`` capability,
so their dead-end files never surface here.

This mirrors :mod:`core.audio_slots`.  A replacement that already matches the
slot's container / codec / resolution / frame rate / alpha / pixel format /
profile is copied through verbatim (no conversion); one that matches in
everything but the container it's wrapped in is repackaged (a stream copy —
still no quality lost); anything else is a re-encode.  The last two need
ffmpeg.
"""

import copy
import os
import shutil
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

from .audio_slots import replace_with_retry
from .checksums import NON_ASSET_DIRS, is_other_extract
from .video import (VIDEO_EXTS, VideoInfo, backend_for, detect_video_info,
                    encode_replacement, find_ffmpeg, isobmff_brand,
                    profile_rank, remux_video_to, same_pix_fmt,
                    transcode_video_to)


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
        if d < 1:
            # Sub-second clips are ordinary on a Spike 2 card -- a sixth of
            # Batman's 6331 slots are, right down to one-frame stills -- and
            # m:ss rendered every one of them "0:00", which reads as an empty
            # slot or a failed probe rather than a short clip (a field
            # report).  Show the milliseconds instead, the same m:ss.mmm the
            # audio tab's Length column uses.
            return "0:00.%03d" % int(d * 1000)
        # Floor, don't round: the preview player's readout floors, and the
        # two disagreeing on the same clip (25.5 s showing 0:26 in the list
        # but 0:25 in the player) read as a bug (feedback batch 14).
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
    :data:`core.video.VIDEO_EXTS`).  BoF passes ``(".ogv",)`` because Ogg
    Theora is the one video form it ships.

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
            # Same prune as audio_slots: dot-dirs + the project's top-level
            # generated / staged folders (checksums.NON_ASSET_DIRS).
            dirs[:] = [d for d in dirs
                       if not d.startswith(".")
                       and not is_other_extract(os.path.join(root, d))
                       and not (d in NON_ASSET_DIRS
                                and os.path.normcase(os.path.normpath(root))
                                == os.path.normcase(
                                    os.path.normpath(assets_dir)))]
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


def _clip_bitrate(path: str) -> Optional[float]:
    """Bits per second of the clip at *path* (trailing padding discounted), or
    ``None`` when it isn't an MP4/QuickTime clip that can be measured.  Read
    from the ``moov`` box alone, so it costs no ffprobe."""
    if not path or not os.path.isfile(path):
        return None
    from .video_quality import quality_of_file
    q = quality_of_file(path)
    if q.error or q.bitrate <= 0:
        return None
    return q.bitrate


def _remove(path: str) -> None:
    """Delete *path* if it's there, ignoring an OS that says otherwise."""
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _stream_mismatch(slot: VideoSlot, ri: Optional[VideoInfo],
                     match_length: bool = False,
                     fps_tol: float = 0.05) -> Optional[str]:
    """The ONE property that stops the probed replacement *ri* from being the
    same VIDEO as the slot's own clip — codec, resolution, frame rate, alpha,
    pixel format and (H.264) profile, ignoring the container it is wrapped in.
    ``None`` when it is a match.

    The string is written to be read in the log by whoever assigned the clip:
    "it's 640x480 and this slot's clip is 720x540".  Without it a re-encode is
    invisible — a tester watching 228 clips go through one asked outright why
    the app was converting files it had itself just extracted, and the log had
    no answer beyond the resolution it converted them TO.

    Deliberately strict: any unknown/ambiguous field counts as a mismatch so we
    fall back to a (lossy but correct) re-encode rather than staging a file that
    might not drop cleanly into the slot.  Pixel format and profile are part of
    the test because the machine's decoder is an embedded VPU, not a desktop
    player: hand it 10-bit, 4:2:2, or a profile above the one the slot's clip
    proves it accepts, and the demuxer still finds the sound (which plays)
    while the picture stays **black**.  A profile BELOW the slot's is fine —
    the ceiling is what matters.
    """
    si = slot.info
    if si is None or not si.width or not si.height:
        # Can't prove a match → re-encode.
        return "the app couldn't read this slot's own video settings"
    if ri is None:
        return "the app couldn't read your file's video settings"
    if (ri.width, ri.height) != (si.width, si.height):
        return ("it's %dx%d and this slot's clip is %dx%d"
                % (ri.width, ri.height, si.width, si.height))
    if (ri.vcodec or "").lower() != (si.vcodec or "").lower():
        return ("it's %s and this slot's clip is %s"
                % ((ri.vcodec or "an unknown codec").upper(),
                   (si.vcodec or "an unknown codec").upper()))
    if si.fps > 0 and abs(ri.fps - si.fps) > fps_tol:
        return ("it runs at %.4g fps and this slot's clip is %.4g fps"
                % (ri.fps, si.fps))
    if bool(ri.has_alpha) != bool(si.has_alpha):
        return ("it has transparency and this slot's clip has none"
                if ri.has_alpha else
                "it has no transparency and this slot's clip has it")
    if not same_pix_fmt(ri.pix_fmt, si.pix_fmt):
        return ("it's %s and this slot's clip is %s"
                % (ri.pix_fmt or "an unknown pixel format",
                   si.pix_fmt or "an unknown pixel format"))
    rank, slot_rank = profile_rank(ri), profile_rank(si)
    if rank is not None and slot_rank is not None and rank > slot_rank:
        return ("it's H.264 %s profile and this slot's clip is %s"
                % (ri.profile, si.profile))
    if match_length and si.duration > 0 and abs(ri.duration - si.duration) > 0.05:
        return ("it runs %.3g s and this slot's clip is %.3g s (lengths are "
                "being matched)" % (ri.duration, si.duration))
    return None


def _stream_matches(slot: VideoSlot, ri: Optional[VideoInfo],
                    match_length: bool = False, fps_tol: float = 0.05) -> bool:
    """Whether the probed replacement *ri* is the same VIDEO as the slot's own
    clip — see :func:`_stream_mismatch`, which is this test plus the reason."""
    if _stream_mismatch(slot, ri, match_length=match_length,
                        fps_tol=fps_tol) is not None:
        return False
    return True


def _same_container(a: str, b: str) -> bool:
    """Whether two files are wrapped in the same kind of container.

    The extension isn't the answer: ``.mov`` and ``.mp4`` are both ISO-BMFF and
    a ``.mov`` some encoder wrote with an MP4 brand is a different wrapper than
    the QuickTime one the card uses.  Files that aren't ISO-BMFF at all (.webm,
    .ogv) have no brand to read, so their extension is all there is.
    """
    ba, bb = isobmff_brand(a), isobmff_brand(b)
    if ba is None and bb is None:
        return True
    if ba is None or bb is None:
        return False
    return (ba == b"qt  ") == (bb == b"qt  ")


def _already_matches(slot: VideoSlot, replacement_path: str, rep_ext: str,
                     match_length: bool = False, fps_tol: float = 0.05) -> bool:
    """True when *replacement_path* is already in the slot's exact container,
    codec, resolution, frame rate, alpha, pixel format and profile (and, when
    *match_length*, also its duration) — so it can be copied through verbatim
    rather than re-encoded.  See :func:`_stream_matches` for the video half."""
    if rep_ext != slot.ext:
        return False
    if not _stream_matches(slot, detect_video_info(replacement_path),
                           match_length=match_length, fps_tol=fps_tol):
        return False
    return _same_container(replacement_path, slot.abs_path)


def _remuxable(slot: VideoSlot, replacement_path: str,
               match_length: bool = False, fps_tol: float = 0.05) -> bool:
    """True when *replacement_path* is the slot's clip in the wrong wrapper —
    identical video stream, different container — so repackaging it is enough
    and a re-encode would only cost a generation of quality.

    Only reached once :func:`_already_matches` has said no, so a True here
    means the container (extension or ISO-BMFF brand) is the *only* difference.
    """
    return _remux_verdict(slot, replacement_path, match_length=match_length,
                          fps_tol=fps_tol)[0]


def _remux_verdict(slot: VideoSlot, replacement_path: str,
                   match_length: bool = False, fps_tol: float = 0.05):
    """:func:`_remuxable`, plus the reason when it says no — ``(ok, why)``,
    *why* being None when *ok*.  Staging logs it so a re-encode never happens
    for a reason the user can't see."""
    if backend_for(slot.abs_path) is not None:
        # .cdmd and friends must be encoded.
        return False, "%s is a format that has to be re-encoded" % slot.ext
    why = _stream_mismatch(slot, detect_video_info(replacement_path),
                           match_length=match_length, fps_tol=fps_tol)
    return (why is None), why


def stage_replacement(slot: VideoSlot, replacement_path: str,
                      trim_to_length: bool = False, no_conversion: bool = False,
                      cancel_cb=None, byte_budget: Optional[int] = None,
                      match_bitrate: Optional[float] = None,
                      best_quality: bool = False):
    """Stage a single replacement over *slot*.

    With *no_conversion* set, the replacement is copied through verbatim and
    must already be in the slot's container (no re-encode at all — the user
    vouches it's playable); a different container is rejected, and a custom
    backend format (``.cdmd``) can't be copied as-is so it's rejected too.

    Otherwise: when the replacement is *already* in the slot's exact container /
    codec / resolution / frame rate / alpha (see :func:`_already_matches`) it's
    copied through verbatim — no re-encode, no generation loss.  When only the
    container differs (see :func:`_remuxable`) it's repackaged with a stream
    copy, which is lossless too.  Failing both it's
    re-encoded into the slot's container / codec, scaled to the slot's
    resolution (preserving alpha for formats that carry it), and written
    atomically over ``slot.abs_path``.  Slots in a custom-backend format
    (``.cdmd``) are routed to that backend's encoder instead.  When ffmpeg is
    unavailable a same-extension replacement is copied as-is (best effort, no
    conversion); any other case fails with a clear message.

    *byte_budget*, when given, is the size the re-encode should land under
    because the slot's byte length is pinned.  Only the re-encode branch can
    honour it; a copy-through or a remux is lossless and is left alone, and
    the build's own fit still backstops all three.

    *match_bitrate*, when given, is the bitrate of the clip the slot shipped
    with, and a re-encode with no budget is held to it (see
    :func:`core.video.transcode_video_to`).  Copies and remuxes ignore it.

    *best_quality* makes a re-encode with no budget a constant-quality one
    instead (the Video tab's "Best quality"), held up to *match_bitrate* when
    the picture is simple enough to come in under it.

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
            # The clip may be the slot's own video in the wrong wrapper (a tester's
            # .mp4 for a QuickTime slot).  Repackaging keeps every coded frame
            # bit-for-bit; only a real mismatch is worth a re-encode.
            repacked = False
            can_remux, why = _remux_verdict(slot, replacement_path,
                                            match_length=trim_to_length)
            if can_remux:
                ok, detail = remux_video_to(replacement_path, tmp, slot.info,
                                            cancel_cb=cancel_cb)
                repacked = ok
                if not ok:
                    _remove(tmp)
                    if detail == "cancelled":
                        return False, detail
                    # Anything else (an ffmpeg that won't take the stream) is
                    # not fatal — fall through to the re-encode.
                    why = "ffmpeg wouldn't repackage it as-is"
            if not repacked:
                ok, detail = transcode_video_to(
                    replacement_path, tmp, slot.info,
                    match_length=trim_to_length, cancel_cb=cancel_cb,
                    max_bytes=byte_budget,
                    match_bitrate=match_bitrate,
                    best_quality=best_quality)
                if not ok:
                    _remove(tmp)
                    return False, detail
                # Say WHY the clip had to be re-encoded rather than copied or
                # repackaged.  Every other outcome names itself in *detail*;
                # this one used to report only what it converted the clip TO.
                if why:
                    detail = ("re-encoded because %s%s"
                              % (why, "; " + detail if detail else ""))
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


#: Where :func:`stage_replacements` remembers what it last staged into each
#: slot (see :class:`StagedCache`).
STAGED_CACHE = os.path.join(".write_cache", "video_staged.json")

#: Part of every staging recipe: bump it whenever what a conversion produces
#: changes (encoder flags, rate control, scaling), so a project's cached
#: conversions from an older version are made again rather than kept.
CONVERSION_REV = 2


class StagedCache:
    """What each slot of a project folder was last staged from, so a Write
    that changes nothing about a clip does not convert it again.

    Every Write, mod-pack export and Emulate apply used to re-encode every
    assigned clip from scratch -- tolerable while a conversion was held to
    the stock clip's bitrate, not once "Best quality" makes each one a
    constant-quality encode and a retheme has 500 of them.  An entry is the
    recipe (the source file's path, size and modification time, the slot's
    shape and every option that reaches the encoder) and the file it made
    (size and modification time of the slot's file afterwards).  Both have
    to still hold for the slot to be left alone: a new source, a changed
    option, a revert that put the stock clip back, or anything else that
    touched the file, and it is staged again.
    """

    VERSION = 1

    def __init__(self, assets_dir: Optional[str]):
        self.path = (os.path.join(assets_dir, STAGED_CACHE)
                     if assets_dir else None)
        self.entries: Dict[str, dict] = {}
        if self.path:
            try:
                import json
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("v") == self.VERSION:
                    self.entries = dict(data.get("slots") or {})
            except (OSError, ValueError):
                pass

    @staticmethod
    def recipe(slot: VideoSlot, rep: str, orig: Optional[str] = None,
               **options) -> Optional[str]:
        """The hash of everything that decides what staging *rep* into
        *slot* produces.  The slot is identified by its pristine snapshot
        *orig* when there is one: the clip in the slot is the last
        conversion by then, and a probe of it can differ in some detail
        (a level, a profile) from the stock clip every conversion targets."""
        import hashlib
        import json
        try:
            st = os.stat(rep)
        except OSError:
            return None
        shape = None
        if orig:
            try:
                ost = os.stat(orig)
                shape = ["orig", ost.st_size, ost.st_mtime_ns]
            except OSError:
                shape = None
        if shape is None and slot.info:
            info = slot.info
            shape = [info.vcodec, info.width, info.height,
                     round(info.fps, 3), info.profile, info.level,
                     info.has_audio, info.has_alpha, info.pix_fmt]
        blob = json.dumps([CONVERSION_REV, os.path.normcase(os.path.abspath(rep)),
                           st.st_size, st.st_mtime_ns, slot.ext, shape,
                           sorted(options.items())], default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def fresh(self, slot: VideoSlot, recipe: Optional[str]) -> bool:
        e = self.entries.get(slot.rel_path)
        if not recipe or not isinstance(e, dict) or e.get("recipe") != recipe:
            return False
        try:
            st = os.stat(slot.abs_path)
        except OSError:
            return False
        return (st.st_size == e.get("size")
                and st.st_mtime_ns == e.get("mtime_ns"))

    def record(self, slot: VideoSlot, recipe: Optional[str]) -> None:
        if not recipe:
            self.entries.pop(slot.rel_path, None)
            return
        try:
            st = os.stat(slot.abs_path)
        except OSError:
            return
        self.entries[slot.rel_path] = {"recipe": recipe, "size": st.st_size,
                                       "mtime_ns": st.st_mtime_ns}

    def forget(self, rel: str) -> None:
        self.entries.pop(rel, None)

    def save(self) -> None:
        if not self.path:
            return
        import json
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"v": self.VERSION, "slots": self.entries}, f,
                          indent=0, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            pass


#: Per-clip length choices (see :func:`stage_replacements`); a number of
#: seconds is the third.
LENGTH_STOCK = "stock"
LENGTH_FULL = "full"


def length_seconds(choice) -> float:
    """The seconds a per-clip length choice asks for, 0.0 when it isn't a
    typed length (stock, full, nothing, or garbage out of a sidecar)."""
    if isinstance(choice, bool) or not isinstance(choice, (int, float)):
        return 0.0
    return float(choice) if choice > 0 else 0.0


def _with_length(slot: VideoSlot, seconds: float) -> VideoSlot:
    """*slot* as a clip of *seconds*, so a Trim / pad conversion cuts or
    pads the replacement to that length instead of the stock clip's."""
    info = slot.info if slot.info is not None else (
        detect_video_info(slot.abs_path))
    if info is None:
        return slot
    info = copy.copy(info)
    info.duration = float(seconds)
    return replace(slot, info=info, probed=True)


def _pristine_slot(slot: VideoSlot, orig: Optional[str]) -> VideoSlot:
    """*slot* as the clip it shipped with, for a conversion to match.

    Once a build has staged a replacement, the file in the slot IS that
    replacement, and a scan probes it like any other clip.  Matching the next
    conversion to it matched the user's clip to itself: "Trim / pad" cut a
    14 s replacement for a 6 s slot to... 14 s, on every build after the
    first (PAD-215).  The ``.orig/`` snapshot is the stock clip, so its probe
    is the target whenever there is one."""
    if not orig or not os.path.isfile(orig):
        return slot
    try:
        info = detect_video_info(orig)
    except Exception:                                   # noqa: BLE001
        info = None
    if info is None:
        return slot
    return replace(slot, info=info, probed=True)


def stage_replacements(slots_by_rel: Dict[str, VideoSlot],
                       assignments: Dict[str, str],
                       trim_to_length: bool = False,
                       no_conversion: bool = False,
                       log_cb=None, progress_cb=None, assets_dir=None,
                       cancel_cb=None, pin_byte_size: bool = False,
                       asis_overrides: Optional[Dict[str, bool]] = None,
                       best_quality: bool = False,
                       length_overrides: Optional[Dict[str, object]] = None):
    """Stage every assignment in *assignments* (rel_path -> replacement path).

    *slots_by_rel* maps the same rel_path keys to their VideoSlot.  Returns
    ``(staged, failures)`` where *failures* is a list of ``(rel_path, error)``.
    Optional *log_cb(text, level)* and *progress_cb(current, total, desc)*
    drive the GUI log + progress bar.

    *asis_overrides*, when given, is ``{rel_path: bool}`` and wins over
    *no_conversion* for those slots — the per-clip answer to "use my files
    as-is".  A tester asked for it outright: "I unchecked it and noticed it is
    an all or nothing option. You can't mix and match. Any reason why?"  It
    goes both ways, so one hand-encoded clip can go on untouched in a build
    that converts everything else, and one clip can be converted in a build
    that otherwise copies files through.

    *assets_dir*, when given, snapshots each slot's pristine bytes under
    ``.orig/`` before the first overwrite so the edit can be reverted without a
    full re-extract (see :mod:`core.staged_originals`).

    *cancel_cb* (returns truthy to abort) stops before the next item and is
    also polled inside each re-encode, so a user Cancel takes effect within
    seconds even mid-encode of a long clip.

    *pin_byte_size* says this plugin's Write may hold a slot to its original
    byte length, so the re-encode is given that length as a budget and the
    build has nothing left to re-encode.  It is honoured only together with
    *trim_to_length*, and that pairing is the whole safety argument: a
    replacement held to the slot's duration AND its byte count is simply being
    given the slot's own bitrate, which is what the game ships at that
    resolution.  Budget a clip that may run to its own length and a 30-second
    replacement for a 3-second slot would be crushed into the 3-second clip's
    bytes.  The budget is a target, not a gate — a clip that misses it is
    still staged and the build's fit re-encodes it as before.

    *length_overrides*, when given, is ``{rel_path: choice}`` and wins over
    *trim_to_length* for those slots -- the per-clip answer to "how long
    should this come out": :data:`LENGTH_STOCK` (the stock clip's length),
    :data:`LENGTH_FULL` (the replacement's own length) or a number of
    seconds.  A tester's 14 s export for a 6 s slot had to be cut to 6 s,
    and one tab-wide box couldn't say that for one clip and not the next
    (PAD-215).  A typed length gets no byte budget: the stock clip's bytes
    were sized for the stock clip's length.

    *best_quality* re-encodes at constant quality, never below the stock
    clip's bitrate (see :func:`core.video.transcode_video_to`); a pinned
    budget still wins where there is one.

    With *assets_dir*, a slot whose file is still exactly what the same
    source and options produced last time is left as it is
    (:class:`StagedCache`).
    """
    from .checksums import read_baseline_any
    from . import staged_originals

    items = [(rel, rep) for rel, rep in assignments.items()
             if rep and rel in slots_by_rel]
    total = len(items)
    staged = 0
    failures: List = []
    overrides = dict(asis_overrides or {})
    lengths = dict(length_overrides or {})
    baseline = read_baseline_any(assets_dir) if assets_dir else {}
    cache = StagedCache(assets_dir)
    kept = 0

    for i, (rel, rep) in enumerate(items):
        if cancel_cb is not None and cancel_cb():
            if log_cb:
                log_cb("Cancelled — skipping the remaining video "
                       "replacement(s).", "error")
            break
        slot = slots_by_rel[rel]
        slot_noconv = bool(overrides.get(rel, no_conversion))
        if progress_cb:
            progress_cb(i, total, rel)
        if log_cb:
            note = ""
            if rel in overrides and bool(overrides[rel]) != bool(no_conversion):
                note = ("  (this clip is set to go on as-is)" if slot_noconv
                        else "  (this clip is set to be converted)")
            log_cb(f"Staging {rel}  ←  {os.path.basename(rep)}{note}", "info")
        if assets_dir:
            staged_originals.snapshot(assets_dir, rel, baseline.get(rel))
        # The budget is the PRISTINE original's length.  slot.size is only
        # that while the slot is untouched; re-staging over an earlier
        # replacement would otherwise budget against that one and ratchet the
        # quality down on every pass.  The snapshot above guarantees the
        # ``.orig/`` copy exists by now whenever assets_dir is known.
        orig = (staged_originals.snapshot_path(assets_dir, rel)
                if assets_dir else None)
        choice = lengths.get(rel)
        seconds = length_seconds(choice)
        if choice == LENGTH_FULL:
            slot_trim = False
        elif choice == LENGTH_STOCK or seconds:
            slot_trim = True
        else:
            slot_trim = bool(trim_to_length)
        budget = None
        if pin_byte_size and slot_trim and not seconds:
            if orig:
                budget = os.path.getsize(orig)
            elif slot.size > 0:
                budget = slot.size
        # A slot that is NOT held to its byte length gets a conversion at the
        # bitrate of the clip it shipped with -- the pristine one, for the same
        # ratchet reason as the budget.  A pinned slot keeps the old encode:
        # without the length matched its bytes are no guide, and a clip the
        # build then has to fit would pay a second generation for it.
        rate = None
        if not pin_byte_size:
            rate = _clip_bitrate(orig or slot.abs_path)
        recipe = cache.recipe(slot, rep, orig, trim=slot_trim,
                              length=seconds or 0,
                              noconv=slot_noconv, budget=budget,
                              rate=round(rate or 0), best=bool(best_quality))
        if cache.fresh(slot, recipe):
            staged += 1
            kept += 1
            if log_cb:
                log_cb(f"  ✓ {rel}  (already converted from this file — "
                       f"kept)", "success")
            continue
        target = _pristine_slot(slot, orig)
        if seconds:
            target = _with_length(target, seconds)
        ok, detail = stage_replacement(target, rep,
                                       trim_to_length=slot_trim,
                                       no_conversion=slot_noconv,
                                       cancel_cb=cancel_cb,
                                       byte_budget=budget,
                                       match_bitrate=rate,
                                       best_quality=best_quality)
        if ok:
            staged += 1
            cache.record(slot, recipe)
            if log_cb:
                msg = f"  ✓ {rel}" + (f"  ({detail})" if detail else "")
                log_cb(msg, "success")
        else:
            cache.forget(rel)
            failures.append((rel, detail))
            if log_cb:
                log_cb(f"  ✗ {rel}: {detail}", "error")
        cache.save()

    if kept and log_cb:
        log_cb("%d clip(s) were already converted from the same file with "
               "the same settings and were kept as they are." % kept, "info")
    if progress_cb:
        progress_cb(total, total, "")
    return staged, failures
