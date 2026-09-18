"""Quality audit of the video clips that are ALREADY on a card.

The Write pipeline warns, once per clip, when a replacement had to be squeezed
into a fixed-size slot hard enough that "it will look very blocky"
(``plugins.stern.engine._fit_video_payload``).  That warning is a *build-time*
line in the log: read it then or lose it.  A user who has been building
editions for months and wants to know which clips on a finished card are below
that bar has no way to ask — the log of the Write that made the card may be
long gone, and a clip that went on intact was never mentioned at all.

This module measures a clip the way that warning does, from bytes that are
already there:

    bits-per-pixel-per-second = (payload bytes x 8 / duration)
                                / (width x height x fps)

and calls anything under :data:`BLOCKY_BPP` blocky.  Using the identical rule
and the identical constant is the point: a report that disagreed with the
warning it is named after would be worse than no report.

Two details decide whether the number means anything.

*Payload, not file size.*  A clip PAD fitted into a slot is padded back up to
the slot's exact byte length with a trailing ``free`` box
(:func:`core.video.pad_isobmff_to_size`), so its file size is the *stock*
clip's size and the bitrate computed from it would be the stock clip's
bitrate — flattering, and wrong.  The trailing padding is subtracted.

*No ffmpeg, no temp files.*  Everything here comes from the ``moov`` box, read
through a caller-supplied random-access ``read_at(offset, length)``.  That is
what lets the same code measure a loose file on disk and an ``N.asset`` sitting
inside a card image's ext4 filesystem, without extracting several GB first (a
whole 658-clip Godzilla card reads in a few seconds).  ``ffprobe`` agrees with
it to the digit on resolution, frame rate and duration.

Only MP4 / QuickTime (ISO-BMFF) is understood, which is every Spike 2 clip;
anything else comes back with :attr:`ClipQuality.error` set and is reported as
"couldn't read" rather than silently dropped.
"""

import os
import struct
from dataclasses import dataclass

# H.264 looks poor below ~0.03 bits per pixel per second regardless of the
# absolute bitrate, which is why the measure is resolution-aware.  THE SAME
# constant the Write-time warning uses -- engine._fit_video_payload imports it
# from here so the two can never drift apart.
BLOCKY_BPP = 0.03

# Boxes that may legally open an ISO-BMFF file (mirrors core.video's own list;
# used here to recognise a container before walking it).
_FIRST_BOXES = frozenset((b"ftyp", b"styp", b"moov", b"mdat", b"wide",
                          b"free", b"skip", b"pnot"))

# Padding boxes: a decoder skips them, so they are not part of the clip.
_PAD_BOXES = frozenset((b"free", b"skip"))

# A moov big enough to be a decompression bomb is not a moov.  Stern's largest
# is well under a megabyte (one u32 per frame in ``stsz``); this caps what a
# corrupt size word can make us allocate.
_MAX_MOOV = 64 << 20


@dataclass
class ClipQuality:
    """One clip's measurements, plus the verdict the Write warning would give.

    *size* is what the file occupies; *payload* is what is left once trailing
    padding is discounted.  They differ only for a clip PAD fitted into a slot,
    which is exactly the case this report exists for.
    """
    name: str = ""
    card_path: str = ""
    size: int = 0
    payload: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    padded: bool = False           # ends in free/skip -> fitted into its slot
    error: str = ""

    @property
    def bitrate(self):
        """Bits per second of real clip data, 0.0 when it can't be worked out."""
        if self.duration <= 0 or self.payload <= 0:
            return 0.0
        return self.payload * 8 / self.duration

    @property
    def bpp(self):
        """Bits per pixel per second, or ``None`` when a term is missing.

        ``None`` is not 0: a clip whose duration or resolution we could not
        read is *unjudged*, and lumping it in with the bad ones would put
        unreadable clips on a list the user is about to re-encode.
        """
        if not (self.width > 0 and self.height > 0 and self.duration > 0):
            return None
        fps = self.fps if self.fps > 0 else 30.0     # engine's own fallback
        denom = self.width * self.height * fps
        if denom <= 0:
            return None
        return self.bitrate / denom

    @property
    def is_blocky(self):
        bpp = self.bpp
        return bpp is not None and bpp < BLOCKY_BPP

    @property
    def verdict(self):
        """``"blocky"`` / ``"ok"`` / ``"unknown"`` — the row's headline."""
        if self.error or self.bpp is None:
            return "unknown"
        return "blocky" if self.is_blocky else "ok"

    def resolution_str(self):
        if self.width and self.height:
            return "%dx%d" % (self.width, self.height)
        return "—"

    def length_str(self):
        if self.duration <= 0:
            return "—"
        if self.duration < 60:
            return "%.1fs" % self.duration
        return "%d:%02d" % (int(self.duration // 60), int(self.duration % 60))

    def bitrate_str(self):
        br = self.bitrate
        if br <= 0:
            return "—"
        if br >= 1e6:
            return "%.1f Mbps" % (br / 1e6)
        return "%d kbps" % round(br / 1000)

    def quality_str(self):
        """The Quality cell: the verdict, and why it is not the whole story."""
        if self.error:
            return "couldn't read"
        bpp = self.bpp
        if bpp is None:
            return "—"
        if bpp < BLOCKY_BPP:
            return "blocky (squeezed to fit)" if self.padded else "blocky"
        return "fitted, looks OK" if self.padded else "OK"


# ---------------------------------------------------------------------------
# ISO-BMFF walking (random access, whole-file reads avoided)
# ---------------------------------------------------------------------------

def _iter_boxes(read_at, start, end):
    """Yield ``(type, box_start, body_start, box_end)`` for the boxes in
    ``[start, end)``.  Stops rather than raising on a size word that doesn't
    fit — a truncated or non-standard tail is common and is not a reason to
    lose the boxes already read."""
    off = start
    while off + 8 <= end:
        hdr = read_at(off, 8)
        if len(hdr) < 8:
            return
        size = struct.unpack_from(">I", hdr, 0)[0]
        typ = hdr[4:8]
        body = off + 8
        if size == 1:                      # 64-bit size follows the type
            ext = read_at(off + 8, 8)
            if len(ext) < 8:
                return
            size = struct.unpack_from(">Q", ext, 0)[0]
            body = off + 16
        elif size == 0:                    # "to the end of the file"
            size = end - off
        if size < (body - off) or off + size > end:
            return
        yield typ, off, body, off + size
        off += size


def _find_box(read_at, start, end, path):
    """Depth-first ``(body_start, body_end)`` of the box *path* (a list of
    four-byte types), or ``None``."""
    want = path[0]
    for typ, _o, body, box_end in _iter_boxes(read_at, start, end):
        if typ != want:
            continue
        if len(path) == 1:
            return body, box_end
        found = _find_box(read_at, body, box_end, path[1:])
        if found:
            return found
    return None


def _full_box_times(data):
    """``(timescale, duration)`` from an ``mvhd`` / ``mdhd`` body."""
    if len(data) < 4:
        return 0, 0
    if data[0] == 1:                       # version 1: 64-bit times
        if len(data) < 32:
            return 0, 0
        return (struct.unpack_from(">I", data, 20)[0],
                struct.unpack_from(">Q", data, 24)[0])
    if len(data) < 20:
        return 0, 0
    return (struct.unpack_from(">I", data, 12)[0],
            struct.unpack_from(">I", data, 16)[0])


def _track_dimensions(data):
    """``(width, height)`` from a ``tkhd`` body — the last two 16.16 fields.

    These are the track's *display* size, which a non-square pixel aspect makes
    wider than the frames really are (7 of Godzilla's 658 clips are coded
    1360x768 and presented as 1365x768).  Only the fallback, therefore; the
    coded size in :func:`_coded_dimensions` is what the bitrate has to buy.
    """
    if len(data) < 8:
        return 0, 0
    w = struct.unpack_from(">I", data, len(data) - 8)[0] >> 16
    h = struct.unpack_from(">I", data, len(data) - 4)[0] >> 16
    return w, h


def _coded_dimensions(read_at, tstart, tend):
    """``(width, height)`` of the coded frames, from the first sample entry in
    ``stsd`` — the two ``u16`` at +32 / +34 of a VisualSampleEntry.  ``(0, 0)``
    when the box isn't there or is too short to hold them."""
    box = _find_box(read_at, tstart, tend,
                    [b"mdia", b"minf", b"stbl", b"stsd"])
    if not box:
        return 0, 0
    body, end = box
    entry = body + 8                       # version/flags + entry_count
    if entry + 36 > end:
        return 0, 0
    data = read_at(entry, 36)
    if len(data) < 36:
        return 0, 0
    return (struct.unpack_from(">H", data, 32)[0],
            struct.unpack_from(">H", data, 34)[0])


def _sample_count(read_at, tstart, tend):
    """Number of samples (= video frames) in a track, from ``stsz``."""
    box = _find_box(read_at, tstart, tend,
                    [b"mdia", b"minf", b"stbl", b"stsz"])
    if not box:
        return 0
    body = read_at(box[0], min(16, box[1] - box[0]))
    if len(body) < 12:
        return 0
    return struct.unpack_from(">I", body, 8)[0]


def _handler(read_at, tstart, tend):
    """A track's handler type (``b"vide"`` / ``b"soun"`` / …)."""
    box = _find_box(read_at, tstart, tend, [b"mdia", b"hdlr"])
    if not box:
        return b""
    body = read_at(box[0], min(12, box[1] - box[0]))
    return body[8:12] if len(body) >= 12 else b""


def read_clip_quality(read_at, size, name="", card_path=""):
    """Measure one ISO-BMFF clip through *read_at* ``(offset, length) -> bytes``.

    *size* is the clip's byte length.  Never raises for a file that isn't what
    we hoped: an unreadable or non-MP4 clip comes back with ``error`` set, so a
    card with one odd asset on it still produces a full report.
    """
    clip = ClipQuality(name=name, card_path=card_path, size=size,
                       payload=size)
    try:
        head = read_at(0, 8)
        if len(head) < 8 or head[4:8] not in _FIRST_BOXES:
            clip.error = "not an MP4/QuickTime clip"
            return clip

        tops = list(_iter_boxes(read_at, 0, size))

        # Trailing padding: a `free`/`skip` run that reaches the end of the
        # file is what a fit-in-place Write leaves behind.  Padding anywhere
        # ELSE (ffmpeg's faststart reservation after `ftyp`, say) is ordinary
        # and must not be subtracted.
        tail = 0
        for typ, box_start, _body, box_end in reversed(tops):
            if typ in _PAD_BOXES and box_end == size - tail:
                tail += box_end - box_start
            else:
                break
        clip.payload = size - tail
        clip.padded = tail > 0

        moov = next(((b, e) for t, _o, b, e in tops if t == b"moov"), None)
        if moov is None:
            clip.error = "no moov (metadata) box"
            return clip
        mstart, mend = moov
        if mend - mstart > _MAX_MOOV:
            clip.error = "metadata box implausibly large"
            return clip

        # The moov is small and every field below lives in it, so buy it once
        # and parse in memory rather than seeking the card per field.
        blob = read_at(mstart, mend - mstart)
        if len(blob) < mend - mstart:
            clip.error = "metadata box is truncated"
            return clip

        def mem_at(off, n):
            # Bounds-checked: a negative index would silently serve bytes from
            # the WRONG END of the moov rather than nothing, and a corrupt size
            # word is exactly what this function has to survive.
            i = off - mstart
            return blob[i:i + n] if (i >= 0 and n > 0) else b""

        mvhd = _find_box(mem_at, mstart, mend, [b"mvhd"])
        if mvhd:
            ts, dur = _full_box_times(mem_at(mvhd[0], mvhd[1] - mvhd[0]))
            if ts:
                clip.duration = dur / ts

        for typ, _o, tstart, tend in _iter_boxes(mem_at, mstart, mend):
            if typ != b"trak" or _handler(mem_at, tstart, tend) != b"vide":
                continue
            clip.width, clip.height = _coded_dimensions(mem_at, tstart, tend)
            if not (clip.width and clip.height):
                tkhd = _find_box(mem_at, tstart, tend, [b"tkhd"])
                if tkhd:
                    clip.width, clip.height = _track_dimensions(
                        mem_at(tkhd[0], tkhd[1] - tkhd[0]))
            # The MEDIA duration (mdhd), not the movie's: an edit list can
            # make them differ, and the frame rate is frames over the media's
            # own clock.
            mdhd = _find_box(mem_at, tstart, tend, [b"mdia", b"mdhd"])
            vdur = clip.duration
            if mdhd:
                ts, dur = _full_box_times(mem_at(mdhd[0], mdhd[1] - mdhd[0]))
                if ts and dur:
                    vdur = dur / ts
                    if clip.duration <= 0:
                        clip.duration = vdur
            frames = _sample_count(mem_at, tstart, tend)
            if frames and vdur > 0:
                clip.fps = frames / vdur
            break
        else:
            clip.error = "no video track"
    except Exception as e:                 # a corrupt asset is a row, not a crash
        clip.error = str(e) or e.__class__.__name__
    return clip


def quality_of_file(path):
    """:func:`read_clip_quality` for a clip sitting on disk.

    The handle stays open for the whole measurement and every read is a seek on
    it — which is why ``read_at`` closes over ``f`` rather than reopening.
    """
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            def read_at(off, n):
                f.seek(off)
                return f.read(n)
            return read_clip_quality(read_at, size, name=name, card_path=path)
    except OSError as e:
        return ClipQuality(name=name, card_path=path, error=str(e))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize(clips):
    """``(total, blocky, squeezed, blocky_squeezed, unreadable)`` for *clips*."""
    total = len(clips)
    blocky = [c for c in clips if c.is_blocky]
    squeezed = [c for c in clips if c.padded]
    return (total, len(blocky), len(squeezed),
            len([c for c in blocky if c.padded]),
            len([c for c in clips if c.error]))


def summary_lines(clips):
    """The two or three sentences that go above the list.

    The split between "below the bar" and "squeezed into its slot" is the
    whole point of the report: a clip PAD had to squeeze is one a rebuild can
    fix.  A clip that is simply small is EITHER the user's own file, which a
    rebuild will not change, or PAD's format-matched conversion, which it will
    -- and the card cannot say which (Stern's own clips carry the same x264
    signature PAD's conversions do), so the line names both.
    """
    total, blocky, squeezed, both, bad = summarize(clips)
    if not total:
        return ["No video clips found on this card."]
    out = []
    if blocky:
        out.append("%d of %d clip(s) are below the quality bar (under %.2f "
                   "bits per pixel per second) and may look blocky."
                   % (blocky, total, BLOCKY_BPP))
    else:
        out.append("All %d clip(s) are at or above the quality bar (%.2f bits "
                   "per pixel per second)." % (total, BLOCKY_BPP))
    if squeezed:
        out.append("%d clip(s) were squeezed into the slot they replaced by a "
                   "Write; %d of those are below the bar. Building an image "
                   "file (not a direct-SD write) with WSL working puts them on "
                   "at full quality instead." % (squeezed, both))
    elif blocky:
        # This used to say they were the user's own files at their own size
        # and to re-export them.  On the card that reported it (PAD-171) all
        # 533 replaced clips were the app's own conversions: a replacement
        # that isn't an exact match for its slot goes on as a converted copy,
        # and that conversion ran at x264's default quality.  The user
        # re-exported at a higher bitrate as told, and the build converted it
        # straight back down.
        out.append("None of them were squeezed to fit their slot. A "
                   "replacement that isn't an exact match for its slot goes "
                   "on as a converted copy, and older versions converted at "
                   "far below Stern's bitrate; build again from your original "
                   "replacement files to convert them at the bitrate of the "
                   "clip they replace. A clip that went on as your own file "
                   "keeps the bitrate you exported it at.")
    if bad:
        out.append("%d clip(s) could not be read." % bad)
    return out


def as_text(clips, title=""):
    """The whole report as plain text, for the Copy button."""
    lines = []
    if title:
        lines += [title, "=" * len(title), ""]
    lines += summary_lines(clips)
    lines.append("")
    lines.append("%-46s %8s %11s %11s  %s"
                 % ("Clip", "Length", "Resolution", "Bitrate", "Quality"))
    for c in clips:
        lines.append("%-46s %8s %11s %11s  %s"
                     % (c.name[:46], c.length_str(), c.resolution_str(),
                        c.bitrate_str(), c.quality_str()))
    return "\n".join(lines) + "\n"


def sort_worst_first(clips):
    """Blocky clips first (worst bpp first), then the rest by name.

    Unreadable rows sort with the readable ones by name rather than to the top:
    they are a footnote, not the answer to the question asked.
    """
    def key(c):
        bpp = c.bpp
        if bpp is not None and bpp < BLOCKY_BPP:
            return (0, bpp, c.name.lower())
        return (1, 0.0, c.name.lower())
    return sorted(clips, key=key)
