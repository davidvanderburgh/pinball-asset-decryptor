"""Find the file each replaced clip on a built card was made from, by CONTENT.

A project records the file behind every replacement (``.staged_changes.json``
maps each slot to a source path), and :mod:`.relink` re-finds those files by
NAME after a move.  Neither helps when the recording never happened or no
longer says anything useful: a card built on another PC, a modder who picked
hundreds of clips by hand from files named nothing like the slots, or a
project that only ever pointed at intermediate exports.  What is left is the
card itself -- and the clips on it are re-encodes (scaled to the slot,
converted to its frame rate, held to a bitrate), so no hash of theirs matches
anything on disk.

This module matches by what the clips LOOK like.  Every clip and every
candidate file is reduced to a fingerprint: tiny colour thumbnails sampled at
fixed times (:data:`SAMPLE_FPS`), taken through the same letterbox the
conversion applies, so a 4:3 source compares against the pillarboxed clip it
became.  Two fingerprints are scored on luma correlation (which ignores the
brightness/contrast drift a re-encode or a range conversion introduces) less a
chroma penalty (which is what tells a colour clip from its black-and-white
twin: their luma is all but identical).

Two properties decide which file is "the" source when several match:

* **The same content at different quality is one answer.**  A folder that
  holds a 4K master, a 1080p export and a 720p proxy of one edit matches all
  three almost equally; the one to use is the best of them
  (:func:`quality_key`), because the point of finding it is to rebuild the
  clip from better material.  Whether two files ARE the same content is
  asked of the two files (:data:`SAME_FILE`), never read off how close their
  scores against the lossy clip are.
* **A different edit is a different answer.**  Files that are the same
  footage but not the same edit -- a variant with a brief slash effect, a
  version a frame longer under another name -- are told apart by a
  frame-by-frame pass over just the frames where they differ
  (:func:`_refine`), and only the one the clip agrees with is offered.

Candidates are narrowed by duration first (a clip is its source's length
unless the build trimmed or padded it), so a folder of thousands of files
costs a probe each and a decode of only the few that could be the one.  Clips
still unmatched after that are compared against every longer file by their
opening seconds, which is what a "Trim / pad" build leaves.

Pure numpy + ffmpeg; the card side (which clips were replaced, reading them
off the image) belongs to the plugin that knows the card.
"""

import hashlib
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from .audio import _CREATE_FLAGS, find_ffmpeg
from .video import detect_video_info

#: Thumbnails per second of video.  Two catches every shot of any length a
#: pinball clip is cut from while keeping a 30-second clip at 60 thumbnails.
SAMPLE_FPS = 2.0

#: Thumbnail size.  16:9, like every Spike 2 slot measured (1360x768,
#: 1366x768, 1920x1080, 520x294, 454x256).
THUMB_W, THUMB_H = 48, 27
FRAME_BYTES = THUMB_W * THUMB_H * 3

#: File types searched for sources.  Anything ffmpeg decodes would do; these
#: are the ones an editor exports or a downloader saves.
VIDEO_EXTS = frozenset((
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg",
    ".ts", ".mts", ".m2ts", ".mxf", ".flv", ".ogv", ".3gp",
))

#: A clip and a candidate this close in length are compared whole.
DURATION_TOLERANCE_S = 0.35
DURATION_TOLERANCE_FRAC = 0.02

#: The lowest score that is a match at all, and the lowest that needs no
#: second look.  Calibrated on real cards (docs/plans/source_video_quality.md).
MATCH_SCORE = 0.80
SURE_SCORE = 0.93

#: Two candidate files whose fingerprints agree this well are the same
#: content (a copy, a proxy, a master); the best QUALITY among them is the
#: answer.  Only candidates within GROUP_WINDOW of the best score are asked.
SAME_FILE = 0.985
GROUP_WINDOW = 0.06

#: ...and whose thumbnails differ by no more than this many luma levels once
#: brightness and contrast are matched (:func:`_affine_mad`).  Correlation
#: alone can't tell a re-export from a reprocessed version: on a real TMNT
#: card an upscaled clip and the original it was upscaled from correlated at
#: 0.981-0.995 but differed by 2.8-3.8 levels, while a master and its
#: export, two names for one file, and a 1080p master and a card copy of it
#: differed by 0.05-0.97.
SAME_FILE_MAD = 1.8

#: How far the best must clear the best DIFFERENT content to need no second
#: look -- or, failing that, how many times further off than the best the
#: runner-up must be, pixel for pixel (:func:`_affine_mad` against the clip).
SURE_MARGIN = 0.015
SURE_MAD_RATIO = 1.4

#: The frame-by-frame pass that tells same-footage variants apart: a frame
#: where two candidates' thumbnails differ by this many luma levels (and by
#: four times their typical difference) is one where the edits differ.
EDIT_FRAME_MAD = 6.0
MAX_DENSE_FPS = 30.0

#: How much of the clip a shorter source must cover to count (a "Trim / pad"
#: build pads a short source with its last frame).
MIN_COVERAGE = 0.6

#: Longest stretch of any one file that is ever decoded.  Pinball clips are
#: seconds long; a feature-length film that happens to be in the folder
#: should cost a bounded read, not a full decode.
MAX_FINGERPRINT_S = 240.0

# Luma weights (BT.601) for the correlation, and the chroma scale: a mean
# difference of this many levels in Cb/Cr costs a whole point of score.  The
# first _CHROMA_FLOOR levels cost nothing: a re-encode moves colour by about
# one level (it is subsampled and quantised hardest), and charging for it put
# a 1080p master 0.02 below the card copy it was the same picture as.  A
# colour clip against its black-and-white twin differs by 15-30.
_LUMA = np.array([0.299, 0.587, 0.114], np.float32)
_CHROMA_SCALE = 60.0
_CHROMA_FLOOR = 1.5

_WORKERS = max(2, min(8, (os.cpu_count() or 4) // 2))


class Cancelled(Exception):
    """Raised out of a search when its cancel callback said so."""


@dataclass
class SourceFile:
    """A candidate file: where it is and what it is."""
    path: str
    size: int = 0
    mtime_ns: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""

    @property
    def bitrate(self) -> float:
        return (self.size * 8 / self.duration) if self.duration > 0 else 0.0


@dataclass
class Clip:
    """A clip to find the source of: *key* is the caller's name for it (a
    slot), *path* a readable copy of it, *duration* its length."""
    key: str
    path: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: float = 0.0


@dataclass
class Candidate:
    source: SourceFile
    score: float
    coverage: float


@dataclass
class Match:
    """The answer for one clip.

    *best* is the file to use (None when nothing matched), *score* its
    similarity, *sure* whether it needs no second look.  *same* are the other
    files holding the same content (copies, proxies, masters of lower
    quality), *variants* files of the same footage that are a different edit,
    and *runner_up* the best-scoring different content -- all for the report.
    *card_copy*: *best* is the card's clip itself and no better a file (one
    that went on untouched, or an extract of a built card).  *trimmed*: it
    is longer than the clip, which a "Trim / pad" build cut down.
    """
    key: str
    best: Optional[SourceFile] = None
    score: float = 0.0
    sure: bool = False
    same: List[SourceFile] = field(default_factory=list)
    variants: List[SourceFile] = field(default_factory=list)
    runner_up: Optional[Candidate] = None
    trimmed: bool = False
    card_copy: bool = False
    group: List[Candidate] = field(default_factory=list, repr=False)


# --------------------------------------------------------------------------
# Probing and fingerprinting
# --------------------------------------------------------------------------

#: Folders never searched: the app's own (a project's ``.orig/`` holds its
#: stock clips, ``.write_cache/`` its conversions) and the usual system ones.
#: Other hidden folders are: a real TMNT project keeps its sources in
#: ``.assets/``.
SKIP_DIRS = frozenset((".orig", ".write_cache", ".hydrate", ".git", ".svn",
                       "$recycle.bin", "system volume information"))


def list_video_files(root: str, cancel: Optional[Callable] = None,
                     limit: int = 200000) -> List[str]:
    """Every file under *root* with a :data:`VIDEO_EXTS` type, sorted
    (:data:`SKIP_DIRS` aside)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        if cancel and cancel():
            raise Cancelled()
        dirnames[:] = sorted(d for d in dirnames
                             if d.lower() not in SKIP_DIRS)
        for fn in filenames:
            if fn.startswith("."):
                continue
            if os.path.splitext(fn)[1].lower() in VIDEO_EXTS:
                out.append(os.path.join(dirpath, fn))
                if len(out) >= limit:
                    return sorted(out)
    return sorted(out)


def probe_source(path: str) -> Optional[SourceFile]:
    """A :class:`SourceFile` for *path*, or None when it holds no video."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    info = detect_video_info(path)
    if info is None or info.duration <= 0:
        return None
    return SourceFile(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns,
                      duration=float(info.duration), width=int(info.width),
                      height=int(info.height), fps=float(info.fps),
                      codec=(info.vcodec or "").lower())


def _letterbox(width: int, height: int):
    """``(w, h)`` of the picture inside a THUMB_W x THUMB_H canvas, fitted the
    way the conversion fits a source into its slot (scale down, keep the
    aspect, bars on the short side).  A picture within 3% of the canvas's
    aspect fills it: 1360x768 is 1.771:1 against 16:9's 1.778, and a bar of a
    fraction of a thumbnail pixel would only blur the comparison."""
    canvas = THUMB_W / THUMB_H
    if width <= 0 or height <= 0:
        return THUMB_W, THUMB_H
    aspect = width / height
    if abs(aspect - canvas) / canvas < 0.03:
        return THUMB_W, THUMB_H
    if aspect > canvas:
        return THUMB_W, max(2, int(round(THUMB_W / aspect)))
    return max(2, int(round(THUMB_H * aspect))), THUMB_H


def fingerprint(path: str, width: int = 0, height: int = 0,
                max_seconds: Optional[float] = None,
                cancel: Optional[Callable] = None,
                sample_fps: float = SAMPLE_FPS) -> Optional[np.ndarray]:
    """``(n, THUMB_H, THUMB_W, 3)`` uint8 thumbnails of *path*, one every
    ``1/sample_fps`` seconds from its first frame, or None when ffmpeg can't
    read it.  *width*/*height* are the picture's own size (for the
    letterbox); *max_seconds* stops the decode early."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("need ffmpeg to compare video")
    w, h = _letterbox(width, height)
    vf = ["setpts=PTS-STARTPTS", "fps=%g" % sample_fps,
          "scale=%d:%d:flags=area" % (w, h), "format=rgb24"]
    if (w, h) != (THUMB_W, THUMB_H):
        vf.append("pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (THUMB_W, THUMB_H))
    limit = min(max_seconds or MAX_FINGERPRINT_S, MAX_FINGERPRINT_S)
    # The loop filter is skipped: it only smooths block edges, which a
    # 48x27 thumbnail averages away, and it is a large share of H.264 decode.
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-skip_loop_filter", "all",
           "-t", "%.3f" % limit, "-i", path, "-an", "-sn", "-dn",
           "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL,
                                creationflags=_CREATE_FLAGS)
    except OSError:
        return None
    chunks = []
    try:
        while True:
            if cancel and cancel():
                proc.kill()
                raise Cancelled()
            buf = proc.stdout.read(FRAME_BYTES * 16)
            if not buf:
                break
            chunks.append(buf)
    finally:
        proc.stdout.close()
        proc.wait()
    data = b"".join(chunks)
    n = len(data) // FRAME_BYTES
    if n == 0:
        return None
    return np.frombuffer(data[:n * FRAME_BYTES], np.uint8).reshape(
        n, THUMB_H, THUMB_W, 3)


class FingerprintCache:
    """Fingerprints on disk under *folder*, keyed by a file's path, size and
    modification time, so a second search of the same folder decodes only
    what changed.  ``None`` folder = memory only."""

    def __init__(self, folder: Optional[str] = None):
        self.folder = folder
        self._mem: Dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(identity: str, sample_fps: float = SAMPLE_FPS) -> str:
        return hashlib.sha1(("%s|%dx%d|%g" % (identity, THUMB_W, THUMB_H,
                                              sample_fps)).encode("utf-8")
                            ).hexdigest()

    def get(self, identity: str, need_seconds: float,
            sample_fps: float = SAMPLE_FPS) -> Optional[np.ndarray]:
        k = self.key(identity, sample_fps)
        fp = None
        if self.folder:
            try:
                fp = np.load(os.path.join(self.folder, k + ".npy"),
                             allow_pickle=False)
            except (OSError, ValueError):
                fp = None
        else:
            with self._lock:
                fp = self._mem.get(k)
        if fp is None:
            return None
        # A fingerprint cut short by an earlier, shorter need is only good
        # for needs it covers.  A file that simply ended sooner is marked by
        # its full flag (the last row), see put().
        full = bool(fp[-1].ravel()[0])
        frames = fp[:-1]
        if full or len(frames) >= need_seconds * sample_fps - 1:
            return frames
        return None

    def put(self, identity: str, frames: np.ndarray, full: bool,
            sample_fps: float = SAMPLE_FPS) -> None:
        marker = np.zeros((1,) + frames.shape[1:], np.uint8)
        marker.ravel()[0] = 1 if full else 0
        fp = np.concatenate([frames, marker])
        k = self.key(identity, sample_fps)
        if not self.folder:
            # Held in memory only when there is nowhere to keep them; with a
            # folder, a search of thousands of files would hold them twice.
            with self._lock:
                self._mem[k] = fp
        else:
            try:
                os.makedirs(self.folder, exist_ok=True)
                tmp = os.path.join(self.folder, k + ".tmp.npy")
                np.save(tmp, fp, allow_pickle=False)
                os.replace(tmp, os.path.join(self.folder, k + ".npy"))
            except OSError:
                pass


def source_identity(src: SourceFile) -> str:
    return "%s|%d|%d" % (os.path.normcase(os.path.abspath(src.path)),
                         src.size, src.mtime_ns)


def _source_fp(src: SourceFile, need_seconds: float, cache: FingerprintCache,
               cancel=None, sample_fps: float = SAMPLE_FPS
               ) -> Optional[np.ndarray]:
    ident = source_identity(src)
    fp = cache.get(ident, need_seconds, sample_fps)
    if fp is not None:
        return fp
    want = min(max(need_seconds, 1.0), MAX_FINGERPRINT_S)
    whole = src.duration <= want + 0.5
    fp = fingerprint(src.path, src.width, src.height,
                     max_seconds=None if whole else want, cancel=cancel,
                     sample_fps=sample_fps)
    if fp is None:
        return None
    cache.put(ident, fp, whole, sample_fps)
    return fp


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _features(fp: np.ndarray):
    f = fp.astype(np.float32)
    y = f @ _LUMA                                # (n, h, w)
    cb = f[..., 2] - y
    cr = f[..., 0] - y
    return y, cb, cr


def compare(clip_fp: np.ndarray, src_fp: np.ndarray):
    """``(score, coverage)`` of *src_fp* as the source of *clip_fp*, both
    aligned at their first frame.

    *score* is the Pearson correlation of the luma of every thumbnail pixel
    over the overlap, less the mean chroma difference over
    :data:`_CHROMA_SCALE`; 1.0 is the same pictures.  *coverage* is the
    share of the clip the source spans (below 1 only for a shorter source).
    """
    n = min(len(clip_fp), len(src_fp))
    if n == 0 or len(clip_fp) == 0:
        return 0.0, 0.0
    cy, ccb, ccr = _features(clip_fp[:n])
    sy, scb, scr = _features(src_fp[:n])
    a = cy.ravel() - cy.mean()
    b = sy.ravel() - sy.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    corr = float((a * b).sum() / den) if den > 1e-6 else (
        1.0 if float(np.abs(cy - sy).mean()) < 4 else 0.0)
    # The chroma is compared after the best saturation scale between the two
    # (held to 0.7..1.3): a range slip in a conversion washes every colour
    # out by a seventh, which is no reason to doubt the match, while a black
    # and white clip against its colour twin still differs by all of it.
    den_c = float((scb * scb).sum() + (scr * scr).sum())
    k = (float((ccb * scb).sum() + (ccr * scr).sum()) / den_c
         if den_c > 1e-6 else 1.0)
    k = min(1.3, max(0.7, k))
    chroma = float((np.abs(ccb - k * scb).mean()
                    + np.abs(ccr - k * scr).mean()) / 2)
    score = corr - max(0.0, chroma - _CHROMA_FLOOR) / _CHROMA_SCALE
    return score, n / len(clip_fp)


def _affine_mad(a: np.ndarray, b: np.ndarray) -> float:
    """Mean luma difference between two fingerprints (over their overlap)
    after the brightness/contrast fit that best maps *b* onto *a*."""
    n = min(len(a), len(b))
    if n == 0:
        return 255.0
    x = _luma(a[:n]).ravel().astype(np.float64)
    y = _luma(b[:n]).ravel().astype(np.float64)
    vy = float(((y - y.mean()) ** 2).mean())
    slope = (float(((x - x.mean()) * (y - y.mean())).mean()) / vy
             if vy > 1e-9 else 0.0)
    fit = x.mean() + slope * (y - y.mean())
    return float(np.abs(x - fit).mean())


def same_content(a: np.ndarray, b: np.ndarray) -> bool:
    """Whether two candidate files are one picture (:data:`SAME_FILE`,
    :data:`SAME_FILE_MAD`) -- a copy, a master and its export -- rather than
    two versions of one scene."""
    pair, _cov = compare(a, b)
    return (pair >= SAME_FILE and _same_length(a, b)
            and _affine_mad(a, b) <= SAME_FILE_MAD)


def _same_length(a: np.ndarray, b: np.ndarray) -> bool:
    """Whether two fingerprints span the same stretch of time, give or take
    the sample a frame-rate conversion can gain or lose at the end."""
    la, lb = len(a), len(b)
    return abs(la - lb) <= max(1, int(0.05 * max(la, lb)))


def quality_key(src: SourceFile, slot_w: int = 0, slot_h: int = 0):
    """Sort key, best last, for files holding the same content: one that
    fills the slot's resolution beats one that must be upscaled, then the
    most bits per second, then the most pixels."""
    fills = (src.width >= slot_w * 0.95 and src.height >= slot_h * 0.95) \
        if slot_w and slot_h else True
    return (fills, src.bitrate, src.width * src.height)


# --------------------------------------------------------------------------
# The search
# --------------------------------------------------------------------------

def _close_in_length(clip: Clip, src: SourceFile) -> bool:
    tol = max(DURATION_TOLERANCE_S, DURATION_TOLERANCE_FRAC * clip.duration)
    return abs(src.duration - clip.duration) <= tol


def _decide(clip: Clip, cands: List[Candidate], trimmed: bool,
            src_fps: Dict[str, Optional[np.ndarray]],
            clip_fp: Optional[np.ndarray] = None) -> Match:
    """The :class:`Match` for *clip* from its scored *cands*.

    "The same content" is judged between the CANDIDATES, not by how close
    their scores to the clip are: two files are one piece of content when
    their own fingerprints agree (:func:`same_content`: a copy, a proxy, a
    re-export of one master do; an upscaled or re-graded version of the same
    edit does not).  The clip on the card is a lossy copy, so how close two
    scores against it are says little -- a pre-upscale original scored 0.955
    against the 1.000 of the upscaled master it was replaced by on a real
    TMNT card, well inside any window loose enough to absorb encode noise.

    A file identical to the card's clip is kept unless a better file passes
    that same strict test against it.  It may be an extract of a built card
    lying in the folder (the right picture, and a poor file to rebuild
    from), but it may just as well be the user's own file that went onto
    the card untouched -- the exact file used, at full quality -- and a
    looser test swapped a real TMNT card's drop-ins for pre-upscale
    originals and for cuts with half a second of handle on the front.
    """
    m = Match(key=clip.key, trimmed=trimmed)
    cands = [c for c in cands if c.coverage >= MIN_COVERAGE]
    if not cands:
        return m
    cands.sort(key=lambda c: c.score, reverse=True)
    top = cands[0]
    if top.score < MATCH_SCORE:
        m.score = top.score
        return m
    top_fp = src_fps.get(top.source.path)
    group, others = [top], []
    for c in cands[1:]:
        same = False
        if c.score >= top.score - GROUP_WINDOW and top_fp is not None:
            fp = src_fps.get(c.source.path)
            if fp is not None:
                same = same_content(top_fp, fp)
        (group if same else others).append(c)
    m.group = group
    m.score = max(c.score for c in group)
    m.runner_up = others[0] if others else None
    margin = m.score - (m.runner_up.score if m.runner_up else 0.0)
    clear = margin >= SURE_MARGIN
    if not clear and clip_fp is not None and top_fp is not None:
        # Close on correlation, but the runner-up may still be plainly the
        # other picture pixel for pixel: a pre-upscale original a TMNT card
        # clip correlated with to within 0.01 was 1.6-4x as far off.
        rfp = src_fps.get(m.runner_up.source.path)
        if rfp is not None:
            near = _affine_mad(clip_fp, top_fp)
            clear = _affine_mad(clip_fp, rfp) >= SURE_MAD_RATIO * max(near,
                                                                      0.25)
    m.sure = m.score >= SURE_SCORE and clear
    _choose(clip, m, group, [])
    return m


def _is_card_copy(c: Candidate, clip: Clip) -> bool:
    """Whether candidate *c* is the card's own clip: the same picture to
    within a re-mux, and no better a file than the clip itself."""
    return c.score >= 0.998 and not _improves_on_clip(c.source, clip)


def _frames_off(clip: Clip, src: SourceFile) -> int:
    """How many of the clip's frames *src* is longer or shorter by.  A
    conversion keeps a source's length, so of two same-content files the one
    of the clip's own length is the one that was used (a real TMNT card had
    the same 1.7 s clip under two names, one a frame shorter)."""
    fps = clip.fps if clip.fps > 0 else 30.0
    return int(round(abs(src.duration - clip.duration) * fps))


#: Of two same-content files, one is only BETTER with half as many bits
#: again (or more pixels, where the slot can use them); closer than that
#: they are a tie.  A file's bitrate is read from its size, which counts its
#: audio too: a variant with a different soundtrack is not a better picture.
QUALITY_TIE = 0.67


def _pixels(src) -> int:
    return max(0, src.width) * max(0, src.height)


def _better(a: SourceFile, b: SourceFile, clip: Clip) -> bool:
    """Whether *a* is clearly a better picture than *b* of the same content:
    it fills the slot and *b* doesn't, or it has a fifth more pixels without
    starving them (half *b*'s bits or more), or half as many bits again at
    about the same size.  Anything closer is a tie -- see
    :data:`QUALITY_TIE`."""
    fa = quality_key(a, clip.width, clip.height)[0]
    fb = quality_key(b, clip.width, clip.height)[0]
    if fa != fb:
        return fa
    pa, pb = _pixels(a), _pixels(b)
    if pa >= 1.2 * pb and a.bitrate >= 0.5 * b.bitrate:
        return True
    return pa >= 0.9 * pb and b.bitrate > 0 and \
        a.bitrate * QUALITY_TIE >= b.bitrate


def _improves_on_clip(src: SourceFile, clip: Clip) -> bool:
    """Whether *src* is any better than the clip on the card itself.  A
    file that isn't -- an extract of the card lying in the same folder --
    is the right picture, but a longer file the clip was trimmed from may
    be the source worth finding."""
    if clip.bitrate <= 0:
        return True
    if _pixels(src) > 1.1 * clip.width * clip.height:
        return True
    return src.bitrate > 1.25 * clip.bitrate


def _name_likeness(slot_key: str, path: str) -> float:
    """0..1 similarity of a file's name to the slot's -- the last word
    between files whose pictures and quality are the same."""
    from difflib import SequenceMatcher
    a = os.path.splitext(os.path.basename(slot_key.replace("\\", "/")))[0]
    b = os.path.splitext(os.path.basename(path))[0]
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _choose(clip: Clip, m: Match, pool: List[Candidate],
            variants: List[Candidate]) -> None:
    """Set *m.best* to the best of *pool* (files that are all the same
    content as the clip).

    Clearly better quality wins outright: a master over the export it was
    cut to, a 1080p original over a copy of the card's own clip that sits in
    the same folder.  Between files of about the same quality, the one of
    the clip's own length (unless the build trimmed it), then the name most
    like the slot's.
    """
    qk = lambda c: quality_key(c.source, clip.width, clip.height)
    tied = [c for c in pool
            if not any(_better(o.source, c.source, clip) for o in pool)] \
        or list(pool)

    def exactness(c):
        return 0 if m.trimmed else -_frames_off(clip, c.source)
    chosen = max(tied, key=lambda c: (exactness(c),
                                      _name_likeness(clip.key, c.source.path),
                                      qk(c)))
    m.best = chosen.source
    m.same = [c.source for c in pool if c is not chosen]
    m.variants = [c.source for c in variants]
    m.card_copy = _is_card_copy(chosen, clip)


def _luma(fp: np.ndarray) -> np.ndarray:
    return fp.astype(np.float32) @ _LUMA


def _frame_diff(a_y: np.ndarray, b_y: np.ndarray) -> np.ndarray:
    """Per-frame mean luma difference of *a_y* against the nearest of *b_y*'s
    frames i-1, i, i+1.  Two files sampled at one rate can land a frame apart
    in places -- a 24 fps clip and the 30 fps conversion of it repeat frames
    in different spots -- and a one-frame slip in a moving shot is not a
    different edit."""
    n = min(len(a_y), len(b_y))
    if n == 0:
        return np.empty(0, np.float32)
    a, b = a_y[:n], b_y[:n]
    best = np.abs(a - b).mean(axis=(1, 2))
    if n > 1:
        prev = np.abs(a[1:] - b[:-1]).mean(axis=(1, 2))
        nxt = np.abs(a[:-1] - b[1:]).mean(axis=(1, 2))
        best[1:] = np.minimum(best[1:], prev)
        best[:-1] = np.minimum(best[:-1], nxt)
    return best


def _edit_frames(a_y: np.ndarray, b_y: np.ndarray) -> np.ndarray:
    """Indices of the frames where two same-footage files show different
    pictures: well above both a fixed floor and their typical difference (a
    master and its export differ a little everywhere; two edits differ a lot
    somewhere)."""
    d = _frame_diff(a_y, b_y)
    if len(d) == 0:
        return np.empty(0, np.int64)
    thr = max(EDIT_FRAME_MAD, 4.0 * float(np.median(d)))
    return np.nonzero(d > thr)[0]


def _error_on(clip_y: np.ndarray, m_y: np.ndarray, frames: np.ndarray):
    d = _frame_diff(clip_y, m_y)
    frames = frames[frames < len(d)]
    if len(frames) == 0:
        return None
    return float(d[frames].mean())


def _refine(clip: Clip, m: Match, clip_dense: Optional[np.ndarray],
            dense: Dict[str, Optional[np.ndarray]]) -> None:
    """Split *m*'s same-content group into edits, frame by frame, and keep
    the edit the clip shows.

    Two thumbnails a second apart can miss a two-frame effect entirely, so
    the group is looked at again at the clip's own frame rate.  Files whose
    frames never differ markedly are one edit (a copy, a master and its
    export); where two differ, the clip's own frames there say which edit it
    was made from.  A decision that is close leaves the match unsure.

    A copy of the card's own clip takes no part: it agrees with the clip on
    every frame by being it, which says nothing about which edit the clip
    was made from, and would out-vote the master it is a copy of.
    """
    if clip_dense is None or len(m.group) < 2:
        return
    copies = [c for c in m.group if _is_card_copy(c, clip)]
    clip_y = _luma(clip_dense)
    ys = {}
    for c in m.group:
        fp = dense.get(c.source.path)
        if fp is not None and c not in copies:
            ys[c.source.path] = _luma(fp)
    members = [c for c in m.group if c.source.path in ys]
    if len(members) < 2:
        return
    edits: List[List[Candidate]] = []
    for c in members:
        for e in edits:
            if len(_edit_frames(ys[e[0].source.path], ys[c.source.path])) == 0:
                e.append(c)
                break
        else:
            edits.append([c])
    if len(edits) == 1:
        return
    champion, beaten = edits[0], []
    for e in edits[1:]:
        a, b = ys[champion[0].source.path], ys[e[0].source.path]
        frames = _edit_frames(a, b)
        err_a = _error_on(clip_y, a, frames)
        err_b = _error_on(clip_y, b, frames)
        if err_a is None or err_b is None:
            beaten += e
            continue
        if err_b < err_a:
            champion, e = e, champion
        beaten += e
        if min(err_a, err_b) > 0.8 * max(err_a, err_b):
            m.sure = False
    unread = [c for c in m.group if c.source.path not in ys]
    _choose(clip, m, champion + unread, beaten)


def find_sources(clips: Sequence[Clip], sources: Sequence[SourceFile],
                 clip_fp: Callable[..., Optional[np.ndarray]],
                 cache: Optional[FingerprintCache] = None,
                 progress: Optional[Callable] = None,
                 cancel: Optional[Callable] = None) -> Dict[str, Match]:
    """``{clip.key: Match}`` for every clip in *clips*.

    *clip_fp(clip, sample_fps)* returns the clip's fingerprint at that rate
    (the caller knows where the clip's bytes live; a card clip is read out of
    the image).  *progress(done, total, text)* is called as work completes.
    """
    cache = cache or FingerprintCache()
    cancel = cancel or (lambda: False)
    progress = progress or (lambda *a: None)
    clips = list(clips)
    sources = [s for s in sources if s and s.duration > 0]

    # Pass 1: each clip against the files of its own length.
    plan = {c.key: [s for s in sources if _close_in_length(c, s)]
            for c in clips}
    need: Dict[str, SourceFile] = {}
    for cands in plan.values():
        for s in cands:
            need[s.path] = s
    total = len(clips) + len(need)
    done = [0]
    lock = threading.Lock()

    def tick(text):
        with lock:
            done[0] += 1
            progress(done[0], total, text)

    clip_fps: Dict[str, Optional[np.ndarray]] = {}
    src_fps: Dict[str, Optional[np.ndarray]] = {}

    def do_clip(c):
        if cancel():
            raise Cancelled()
        clip_fps[c.key] = clip_fp(c, SAMPLE_FPS)
        tick("Reading clip %s" % c.key)

    def do_src(s, secs=None):
        if cancel():
            raise Cancelled()
        src_fps[s.path] = _source_fp(s, secs or s.duration, cache, cancel)
        tick("Reading %s" % os.path.basename(s.path))

    with ThreadPoolExecutor(_WORKERS) as pool:
        for f in [pool.submit(do_clip, c) for c in clips] + \
                 [pool.submit(do_src, s) for s in need.values()]:
            f.result()

    results: Dict[str, Match] = {}
    for c in clips:
        fp = clip_fps.get(c.key)
        if fp is None:
            results[c.key] = Match(key=c.key)
            continue
        cands = []
        for s in plan[c.key]:
            sfp = src_fps.get(s.path)
            if sfp is None:
                continue
            score, cov = compare(fp, sfp)
            cands.append(Candidate(s, score, cov))
        results[c.key] = _decide(c, cands, False, src_fps, fp)

    # Pass 2: what is still unmatched may have been trimmed to its slot's
    # length (or padded past a short source): compare opening seconds with
    # every file long enough to have been cut down to it.  Only what is
    # unmatched: a file of the clip's own length that matched is a certain
    # answer, and a longer one whose opening looks the same is a guess (a
    # real TMNT card's drop-ins were "beaten" that way by cuts with half a
    # second of handle on the front, over shots too still to tell).
    left = [c for c in clips
            if clip_fps.get(c.key) is not None
            and results[c.key].best is None]
    if left and not cancel():
        longest = max(c.duration for c in left) + 1.0
        pool_srcs = [s for s in sources
                     if any(s.duration >= c.duration * MIN_COVERAGE
                            and not _close_in_length(c, s) for c in left)]
        total = done[0] + len(pool_srcs)
        with ThreadPoolExecutor(_WORKERS) as pool:
            for f in [pool.submit(do_src, s, min(s.duration, longest))
                      for s in pool_srcs]:
                f.result()
        for c in left:
            fp = clip_fps[c.key]
            cands = []
            for s in pool_srcs:
                # Files of the clip's own length had their turn in pass 1.
                if s.duration < c.duration * MIN_COVERAGE \
                        or _close_in_length(c, s):
                    continue
                sfp = src_fps.get(s.path)
                if sfp is None:
                    continue
                score, cov = compare(fp, sfp)
                cands.append(Candidate(s, score, cov))
            m = _decide(c, cands, True, src_fps, fp)
            if m.best is not None or m.score > results[c.key].score:
                results[c.key] = m

    # Refine: a same-content group of more than one distinct file is looked
    # at frame by frame, in case it holds more than one edit.
    todo = []
    for c in clips:
        m = results[c.key]
        reps, copy_of = _distinct(m.group, src_fps)
        reps = [r for r in reps if not _is_card_copy(r, c)]
        if len(reps) > 1:
            todo.append((c, m, reps, copy_of))
    if todo and not cancel():
        total = done[0] + len(todo)

        def do_refine(item):
            c, m, reps, copy_of = item
            if cancel():
                raise Cancelled()
            fps = min(MAX_DENSE_FPS, c.fps if c.fps > 0 else 30.0)
            clip_dense = clip_fp(c, fps)
            dense = {}
            for cand in reps:
                dense[cand.source.path] = _source_fp(
                    cand.source, c.duration + 1.0, cache, cancel, fps)
            for path, rep in copy_of.items():
                dense[path] = dense.get(rep)
            _refine(c, m, clip_dense, dense)
            tick("Comparing versions of %s" % c.key)

        with ThreadPoolExecutor(_WORKERS) as pool:
            for f in [pool.submit(do_refine, it) for it in todo]:
                f.result()
    return results


def _distinct(group: List[Candidate], src_fps):
    """``(representatives, {copy path: representative path})`` for *group*:
    files of one size whose fingerprints are identical are byte copies as
    far as this search can tell, and need looking at once."""
    reps: List[Candidate] = []
    copy_of: Dict[str, str] = {}
    for c in group:
        fp = src_fps.get(c.source.path)
        for r in reps:
            rfp = src_fps.get(r.source.path)
            if (r.source.size == c.source.size and fp is not None
                    and rfp is not None and fp.shape == rfp.shape
                    and np.array_equal(fp, rfp)):
                copy_of[c.source.path] = r.source.path
                break
        else:
            reps.append(c)
    return reps, copy_of


def probe_sources(paths: Sequence[str], progress=None, cancel=None
                  ) -> List[SourceFile]:
    """:func:`probe_source` over *paths*, in parallel, dropping non-video."""
    cancel = cancel or (lambda: False)
    out: List[Optional[SourceFile]] = [None] * len(paths)
    done = [0]
    lock = threading.Lock()

    def one(i):
        if cancel():
            raise Cancelled()
        out[i] = probe_source(paths[i])
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], len(paths),
                         "Checking %s" % os.path.basename(paths[i]))

    with ThreadPoolExecutor(_WORKERS * 2) as pool:
        for f in [pool.submit(one, i) for i in range(len(paths))]:
            f.result()
    return [s for s in out if s is not None]
