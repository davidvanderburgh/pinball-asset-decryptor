"""Find the file each replacement sound or picture was made from, by CONTENT.

The Video tab finds the files a built card's clips were made from
(:mod:`.source_match`); sounds and pictures had no such search, and a tester
asked for one (PAD-443, DoomWalrus666): carry a built card's mods into a
project, "then use the search to find the original replacement assets for a
clean fresh write".  "Transfer Mods to New Version" from an extract of a
built card (the baked-mods route, :func:`mod_transfer.diff_baked_mods`) picks
the CARD'S OWN COPY of every replaced file: a sound decoded off the card after
a Write resampled it, gained it to the stock sound's loudness, trimmed or
padded it to its slot and ran it through the game's codec; a picture
stretched to its slot, maybe colour-corrected, and compressed into the card's
texture format.  A Write from those copies converts them a second time.  The
user's own files are better, but they are named nothing like the slots, so
:mod:`.folder_match` can't pair them, and :mod:`.relink` has no record of
them to look for.

This module pairs by what the files sound and look like:

* **Sounds** become a log band-energy spectrogram (:data:`N_BANDS` bands from
  100 Hz to 7 kHz, :data:`FRAMES_PER_S` frames a second) of a 16 kHz mono
  decode, measured from the file's own loudest point.  A gain change and a
  sample-rate change leave that alone, and the codec's hiss sits far below
  the loudest point.  Two are scored by the Pearson correlation of every band
  of every frame where either one sounds, lined up at their first sample (a
  Write never moves where a sound starts) give or take two frames, and must
  also agree in level band for band (:data:`MAX_LEVEL`).  A file longer than
  the copy is one "Trim / pad" cut, a shorter one was padded with silence;
  both still line up at the start, so both are found.
* **Pictures** become a :data:`PIC` x :data:`PIC` thumbnail, stretched the
  way a Write stretches a picture to its slot, its colour premultiplied by
  alpha (whatever sits under a transparent pixel is up to the last tool that
  saved it).  Scored by the correlation of their brightness, and of their
  alpha beside it, less a colour penalty: brightness shrugs off a colour
  profile's contrast / gamma change and the texture compression's blocks, and
  colour is what tells a picture from its black-and-white twin.  Pictures a
  thumbnail can't tell apart get a second look at the copy's own size
  (:func:`detail_error`).  Content alone can't tell a picture from one that
  is the same to the pixel (one letter in two font files, an animation's next
  frame), so when the real file is missing a look-alike can stand in: the
  window shows both side by side.

Every candidate is first ranked against every copy at once on a coarse
summary (one matrix product), so a folder of thousands of files costs a
decode each and only the :data:`TOP_K` closest per copy are scored in full.
When the folder holds the same file more than once (a master and an export),
the best of them is the answer, as on the Video tab.

Never offered: the card's own files -- every file an extract's
``.checksums.md5`` lists, wherever that extract sits under the folder, since a
copy off a card is what the search is getting away from -- and the app's own
folders (:data:`source_match.SKIP_DIRS`).
"""

import hashlib
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from . import checksums
from .audio import _CREATE_FLAGS, find_ffmpeg, parse_banner_duration
from .source_match import SKIP_DIRS, Cancelled

SOUND, PICTURE = "sound", "picture"

#: File types searched.  Anything ffmpeg / Pillow reads would do; these are
#: what an editor exports.
SOUND_EXTS = frozenset((".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg",
                        ".m4a", ".aac", ".opus", ".wma"))
LOSSLESS_SOUND = frozenset((".wav", ".flac", ".aif", ".aiff"))
PICTURE_EXTS = frozenset((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga",
                          ".webp", ".tif", ".tiff"))
LOSSY_PICTURE = frozenset((".jpg", ".jpeg", ".webp"))

# -- sounds -----------------------------------------------------------------
SOUND_RATE = 16000
FRAMES_PER_S = 50
_HOP = SOUND_RATE // FRAMES_PER_S          # 20 ms
_WIN = 2 * _HOP                            # 40 ms, half overlapped
N_BANDS = 20
_F_LO, _F_HI = 100.0, 7000.0
#: Band energies are measured in powers of ten below the file's loudest
#: band-frame and floored :data:`_FLOOR` below it (60 dB): quieter is silence.
_FLOOR = 6.0
#: A frame sounds when a band in it is within 45 dB of the loudest.
_ACTIVE = 4.5
#: How much of a file is fingerprinted.  Thirty seconds of a song tell it
#: from every other; the full length is kept beside it.
MAX_SOUND_S = 30.0
#: Frames either way the two are slid against each other (a resampler's
#: delay, a codec's lead-in).
MAX_LAG = 2

# -- pictures ---------------------------------------------------------------
PIC = 48
_LUMA = np.array([0.299, 0.587, 0.114], np.float32)
#: A mean colour difference of this many levels costs a whole point of score,
#: after the first _CHROMA_FLOOR (the texture compression's own colour error).
_CHROMA_SCALE = 60.0
_CHROMA_FLOOR = 3.0

# -- deciding ---------------------------------------------------------------
#: Candidates scored in full per copy, after the coarse ranking.
TOP_K = 24
#: Lowest score that is a match, lowest that needs no second look, and how far
#: the best must clear the best DIFFERENT file to need none.
MATCH = {SOUND: 0.85, PICTURE: 0.85}
SURE = {SOUND: 0.90, PICTURE: 0.95}
SURE_MARGIN = {SOUND: 0.04, PICTURE: 0.03}
#: Two candidate files this alike are the same content (a master and its
#: export); the best of them is the answer.  Only candidates within
#: GROUP_WINDOW of the best score are asked.
SAME = {SOUND: 0.97, PICTURE: 0.985}
GROUP_WINDOW = 0.06
#: The share of a copy's sound a shorter file must cover to count.
MIN_COVERAGE = 0.8
#: How far apart two sounds' band energies may be, on average once one is
#: brought to the other's loudness (in powers of ten: 0.4 = 4 dB), to be
#: one sound at all, and to be one with no second look.  Correlation alone
#: let a noisy sound (a jet fly-by) "match" a third of a tester's card at
#: 0.75-0.88: its shape follows anything loud, but its levels don't.
#: Measured on Godzilla 1.16: one file written by two separate Writes (a
#: tester's V1.5 and V1.93 cards) 0.00-0.32, mostly under 0.05; a file and
#: a copy through a harsher codec (Vorbis q1) 0.09-0.30; unrelated sounds
#: 0.43 and up.
MAX_LEVEL = 0.40
SURE_LEVEL = 0.30
#: What running on past the copy costs a sound in the ranking: a file that
#: is the copy's own length beats one a "Trim / pad" Write would have had to
#: cut, when they sound the same that far (one sound is often the start of a
#: longer one: TANK FIRE DOUBLE FAST 1 and 2).
LONGER_COST = 0.01
#: What a different shape costs a picture, per unit of log aspect ratio.
ASPECT_COST = 0.25
#: Pictures whose thumbnails score within REFINE_WINDOW of the best (at most
#: REFINE_MAX of them) are told apart at the copy's own size, up to
#: DETAIL_SIDE pixels on its long side: neighbouring frames of an animation,
#: or one glyph in two cuts of a font, are one thumbnail.
REFINE_WINDOW = 0.05
REFINE_MAX = 8
DETAIL_SIDE = 256
#: At the copy's size: two candidates this close to each other (levels per
#: pixel) are the same picture, and the best is certain when the next
#: different one is this many times further from the copy.
SAME_DETAIL = 1.5
SURE_DETAIL_RATIO = 1.3

_WORKERS = max(2, min(8, (os.cpu_count() or 4) // 2))
#: Bumped when a fingerprint's recipe changes, so old cache entries are not
#: read as new ones.
_FP_VERSION = 1


@dataclass
class Candidate:
    """A file in the user's folder: where it is and what it is."""
    path: str
    size: int = 0
    mtime_ns: int = 0
    duration: float = 0.0       # sounds: seconds, the whole file
    end: float = 0.0            # sounds: where its sound ends
    rate: int = 0
    channels: int = 0
    width: int = 0              # pictures
    height: int = 0
    lossless: bool = True


@dataclass
class Match:
    """The answer for one copy.

    *best* is the file to use (None when nothing matched), *score* its
    similarity and *sure* whether it needs no second look.  *same* are the
    other files holding the same content (copies, exports, masters of lower
    quality), *variants* (sounds) the same sound at another length -- a
    longer take that starts the same -- and *runner_up* the best-scoring
    different file's score.
    *longer*: *best* runs on past where the copy's sound ends (a "Trim / pad"
    Write cut it).  *identical*: *best* has the very bytes of the copy (it
    went on to the card untouched, or it is another copy of the copy).
    *ref* is the copy's own facts."""
    key: str
    ref: Optional[Candidate] = None
    best: Optional[Candidate] = None
    score: float = 0.0
    sure: bool = False
    same: List[Candidate] = field(default_factory=list)
    variants: List[Candidate] = field(default_factory=list)
    runner_up: Optional[float] = None
    longer: bool = False
    identical: bool = False


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------

#: An extract's top-level folders that hold its own generated state (the
#: build output, the mod-pack import's copies of a sender's card files).
_EXTRACT_SKIP = frozenset(("build", ".hydrate", "card_files", "logs",
                           ".write_cache"))


class CardFiles:
    """Which files are an extract's own -- listed in the ``.checksums.md5``
    of an extract folder they sit in.  Baselines are read once each."""

    def __init__(self):
        self._roots: Dict[str, Optional[frozenset]] = {}

    def _baseline(self, folder):
        key = os.path.normcase(folder)
        if key not in self._roots:
            names = None
            if checksums.is_other_extract(folder):
                try:
                    names = frozenset(
                        r.lower() for r in checksums.read_baseline_any(folder))
                except OSError:
                    names = frozenset()
            self._roots[key] = names
        return self._roots[key]

    def extract_root(self, folder, levels=12):
        """The nearest folder at or above *folder* that is an extract."""
        cur = os.path.abspath(folder)
        for _ in range(levels):
            if self._baseline(cur) is not None:
                return cur
            up = os.path.dirname(cur)
            if up == cur:
                break
            cur = up
        return None

    def is_card_file(self, path, root=None):
        """True when *path* is a file an extract holds of its card's."""
        root = root or self.extract_root(os.path.dirname(path))
        if not root:
            return False
        try:
            rel = os.path.relpath(os.path.abspath(path), root)
        except ValueError:                  # another drive
            return False
        rel = rel.replace(os.sep, "/")
        top = rel.split("/", 1)[0]
        if top == "..":
            return False
        if top in _EXTRACT_SKIP:
            return True
        return rel.lower() in (self._baseline(root) or frozenset())


def list_files(roots: Sequence[str], exts, cancel: Optional[Callable] = None,
               cards: Optional[CardFiles] = None, limit: int = 200000):
    """``(paths, card_files)``: every file under *roots* with a type in
    *exts*, sorted, and how many were left out as an extract's own."""
    cards = cards or CardFiles()
    out, seen, skipped = [], set(), 0
    for top in roots:
        top = os.path.abspath(top)
        roots_of = {}
        for dirpath, dirnames, filenames in os.walk(top):
            if cancel and cancel():
                raise Cancelled()
            if dirpath == top:
                root = cards.extract_root(dirpath)
            elif cards._baseline(dirpath) is not None:
                root = dirpath
            else:
                root = roots_of.get(os.path.dirname(dirpath))
            roots_of[dirpath] = root
            keep = []
            for d in sorted(dirnames):
                if d.lower() in SKIP_DIRS:
                    continue
                if root and os.path.normcase(dirpath) == \
                        os.path.normcase(root) and d in _EXTRACT_SKIP:
                    continue
                keep.append(d)
            dirnames[:] = keep
            for fn in filenames:
                if fn.startswith(".") or \
                        os.path.splitext(fn)[1].lower() not in exts:
                    continue
                p = os.path.join(dirpath, fn)
                k = os.path.normcase(p)
                if k in seen:
                    continue
                seen.add(k)
                if root and cards.is_card_file(p, root):
                    skipped += 1
                    continue
                out.append(p)
                if len(out) >= limit:
                    return sorted(out), skipped
    return sorted(out), skipped


# --------------------------------------------------------------------------
# Sounds
# --------------------------------------------------------------------------

def _band_matrix():
    freqs = np.fft.rfftfreq(_WIN, 1.0 / SOUND_RATE)
    edges = np.geomspace(_F_LO, _F_HI, N_BANDS + 1)
    m = np.zeros((len(freqs), N_BANDS), np.float32)
    for b in range(N_BANDS):
        sel = (freqs >= edges[b]) & (freqs < edges[b + 1])
        if not sel.any():
            sel = np.abs(freqs - (edges[b] + edges[b + 1]) / 2) == np.min(
                np.abs(freqs - (edges[b] + edges[b + 1]) / 2))
        m[sel, b] = 1.0
    return m


_BANDS = _band_matrix()
_HANN = np.hanning(_WIN).astype(np.float32)

_AUDIO_STREAM_RE = re.compile(r"Audio:[^\n]*?(\d+) Hz, ([^,\n]+)")


def _channels(word):
    word = word.strip().lower()
    if word == "mono":
        return 1
    if word.startswith("stereo"):
        return 2
    m = re.match(r"(\d+)(?:\.(\d+))?", word)
    if m:
        return int(m.group(1)) + int(m.group(2) or 0)
    return 0


def sound_features(samples: np.ndarray) -> Optional[np.ndarray]:
    """``(frames, N_BANDS)`` float16 log band energies of *samples* (mono
    float at :data:`SOUND_RATE`), 0 at the loudest band-frame and floored
    :data:`_FLOOR` below it; None for a silent file."""
    x = np.asarray(samples, np.float32)
    if len(x) < _WIN:
        x = np.pad(x, (0, _WIN - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, _WIN)[::_HOP]
    spec = np.abs(np.fft.rfft(frames * _HANN, axis=1)) ** 2
    e = spec.astype(np.float32) @ _BANDS
    peak = float(e.max()) if e.size else 0.0
    if not peak > 1e-9:
        return None
    return np.log10(e / peak + 10.0 ** -_FLOOR).astype(np.float16)


def decode_sound(path: str, max_seconds: float = MAX_SOUND_S,
                 cancel: Optional[Callable] = None):
    """``(samples, duration, rate, channels)`` of *path*: its first
    *max_seconds* as mono float at :data:`SOUND_RATE`, its whole length, and
    its own sample rate and channel count (None when ffmpeg can't read it)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("need ffmpeg to compare sounds")
    if cancel and cancel():
        raise Cancelled()
    cmd = [ffmpeg, "-nostdin", "-nostats", "-t", "%.3f" % max_seconds,
           "-i", path, "-vn", "-sn", "-dn", "-ac", "1",
           "-ar", str(SOUND_RATE), "-f", "s16le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120,
                           creationflags=_CREATE_FLAGS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    data = r.stdout or b""
    if len(data) < 2:
        return None
    x = np.frombuffer(data[:len(data) // 2 * 2], "<i2").astype(
        np.float32) / 32768.0
    banner = (r.stderr or b"").decode("utf-8", "replace")
    total = parse_banner_duration(banner)
    got = len(x) / SOUND_RATE
    if not total or total < got:
        total = got
    rate = channels = 0
    m = _AUDIO_STREAM_RE.search(banner)
    if m:
        rate, channels = int(m.group(1)), _channels(m.group(2))
    return x, total, rate, channels


def _active(f: np.ndarray) -> np.ndarray:
    return f.max(axis=1) > -_ACTIVE


def _end_seconds(f: np.ndarray, duration: float) -> float:
    """Where the sound in *f* ends: its last frame that sounds, or the whole
    length when *f* is a cut-short fingerprint of a longer file."""
    if duration > MAX_SOUND_S + 0.5:
        return duration
    act = np.nonzero(_active(f))[0]
    return float(act[-1] + 1) / FRAMES_PER_S if len(act) else 0.0


def _pearson(x, y):
    x = x - x.mean()
    y = y - y.mean()
    d = float(np.sqrt(float((x * x).sum()) * float((y * y).sum())))
    return float((x * y).sum()) / d if d > 1e-9 else 0.0


def sound_score(a: np.ndarray, b: np.ndarray, max_lag: int = MAX_LAG):
    """``(score, coverage, level)`` of *b* as the file *a* was made from,
    both lined up at their first frame (give or take *max_lag*).

    *score* is the Pearson correlation of every band of every frame in the
    overlap where either sounds; *coverage* the share of *a*'s sounding
    frames inside the overlap (below 1 only for a shorter *b*); *level* the
    mean difference of those band energies, in powers of ten, once the two
    are brought to one loudness."""
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    act_a, act_b = _active(a), _active(b)
    total = int(act_a.sum())
    if total == 0:
        return 0.0, 0.0, float(_FLOOR)
    # Below the level where a frame counts as sounding is hiss (a codec's,
    # a quiet room's), not the sound: one level for all of it.
    a = np.maximum(a, -_ACTIVE)
    b = np.maximum(b, -_ACTIVE)
    best = (0.0, 0.0, float(_FLOOR))
    for lag in range(-max_lag, max_lag + 1):
        ia, ib = max(0, -lag), max(0, lag)
        n = min(len(a) - ia, len(b) - ib)
        if n <= 0:
            continue
        m = act_a[ia:ia + n] | act_b[ib:ib + n]
        if int(m.sum()) < 2:
            continue
        x, y = a[ia:ia + n][m], b[ib:ib + n][m]
        r = _pearson(x.ravel(), y.ravel())
        if r > best[0]:
            d = x - y
            best = (r, float(act_a[ia:ia + n].sum()) / total,
                    float(np.abs(d - d.mean()).mean()))
    return best


#: The coarse summary: 2 x 2 pooled frames x bands, the first PRE_FRAMES.
_PRE_FRAMES = 50


def _sound_summary(f: np.ndarray) -> np.ndarray:
    f = np.asarray(f, np.float32)
    n = (min(len(f), 2 * _PRE_FRAMES) + 1) // 2
    g = np.full((2 * n, N_BANDS), -_FLOOR, np.float32)
    g[:min(len(f), 2 * n)] = f[:2 * n]
    return g.reshape(n, 2, N_BANDS // 2, 2).mean(axis=(1, 3))


def _sound_ranks(refs, cands, k):
    """``{ref index: [candidate index, ...]}``, the *k* candidates whose
    opening seconds correlate best with each ref's."""
    if not cands:
        return {i: [] for i in range(len(refs))}
    width = N_BANDS // 2
    m = np.full((len(cands), _PRE_FRAMES, width), -_FLOOR, np.float32)
    for j, f in enumerate(cands):
        s = _sound_summary(f)
        m[j, :len(s)] = s
    flat = m.reshape(len(cands), -1)
    # running sums over frames give each candidate's mean and spread over
    # any opening length without slicing it again
    per = m.sum(axis=2)
    per2 = (m * m).sum(axis=2)
    s1 = np.concatenate([np.zeros((len(cands), 1), np.float32),
                         np.cumsum(per, axis=1)], axis=1)
    s2 = np.concatenate([np.zeros((len(cands), 1), np.float32),
                         np.cumsum(per2, axis=1)], axis=1)
    by_len: Dict[int, List[int]] = {}
    sums = [_sound_summary(f) for f in refs]
    for i, s in enumerate(sums):
        by_len.setdefault(len(s), []).append(i)
    out = {}
    for n, idxs in by_len.items():
        size = n * width
        x = np.stack([sums[i].ravel() for i in idxs])
        x = x - x.mean(axis=1, keepdims=True)
        nx = np.sqrt((x * x).sum(axis=1))
        dots = flat[:, :size] @ x.T                    # (C, len(idxs))
        var = s2[:, n] - s1[:, n] ** 2 / size
        ny = np.sqrt(np.maximum(var, 1e-9))
        r = dots / (ny[:, None] * np.maximum(nx[None, :], 1e-9))
        kk = min(k, len(cands))
        for col, i in enumerate(idxs):
            top = np.argpartition(-r[:, col], kk - 1)[:kk]
            out[i] = [int(j) for j in top[np.argsort(-r[top, col])]]
    return out


# --------------------------------------------------------------------------
# Pictures
# --------------------------------------------------------------------------

def picture_fingerprint(path: str):
    """``(thumb, width, height)``: a :data:`PIC` x :data:`PIC` premultiplied
    RGBA uint8 thumbnail of *path* stretched to the square, and its own size
    (None when Pillow can't read it)."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
            if (im.format or "").upper() == "JPEG":
                im.draft("RGB", (PIC * 2, PIC * 2))
            im = im.convert("RGBA").convert("RGBa")
            t = im.resize((PIC, PIC), Image.BILINEAR)
            return np.asarray(t, np.uint8).copy(), w, h
    except Exception:                                   # noqa: BLE001
        return None


def _pic_parts(fp):
    f = np.asarray(fp, np.float32)
    y = f[..., :3] @ _LUMA
    c = np.stack([f[..., 2] - y, f[..., 0] - y])
    return y, f[..., 3], c


def picture_score(a: np.ndarray, b: np.ndarray) -> float:
    """How alike two thumbnails are: brightness correlation (with alpha's
    beside it when both have any), less the colour difference after a
    saturation fit.  1.0 is the same picture."""
    ya, aa, ca = _pic_parts(a)
    yb, ab, cb = _pic_parts(b)
    if ya.std() < 1.0 and yb.std() < 1.0:
        # two flat pictures: alike as far as their level is
        r = max(0.0, 1.0 - abs(float(ya.mean() - yb.mean())) / 32.0)
    else:
        r = _pearson(ya.ravel(), yb.ravel())
    if aa.std() > 2.0 and ab.std() > 2.0:
        r = (r + _pearson(aa.ravel(), ab.ravel())) / 2.0
    den = float((cb * cb).sum())
    s = float(np.clip((ca * cb).sum() / den, 0.7, 1.3)) if den > 1e-6 else 1.0
    diff = float(np.abs(ca - s * cb).mean())
    return r - max(0.0, diff - _CHROMA_FLOOR) / _CHROMA_SCALE


def _pic_summary(fp):
    """``(shape, level)``: a picture's 16 x 16 brightness and alpha, centred
    and scaled to length 1 (zero for a flat picture), and its mean
    brightness and alpha (all a flat one has to tell it by)."""
    y, a, _c = _pic_parts(fp)
    s = PIC // 16
    ys = y.reshape(16, s, 16, s).mean(axis=(1, 3)).ravel()
    al = a.reshape(16, s, 16, s).mean(axis=(1, 3)).ravel()
    v = np.concatenate([ys - ys.mean(), al - al.mean()])
    n = float(np.sqrt((v * v).sum()))
    flat = float(y.std()) < 1.0 and float(a.std()) < 1.0
    return (v / n if n > 1e-6 and not flat else np.zeros_like(v),
            np.array([ys.mean(), al.mean()], np.float32))


def _picture_ranks(refs, cands, k):
    if not cands:
        return {i: [] for i in range(len(refs))}
    cs = [_pic_summary(f) for f in cands]
    m = np.stack([v for v, _l in cs])
    mlev = np.stack([lv for _v, lv in cs])
    mflat = ~m.any(axis=1)
    kk = min(k, len(cands))
    out = {}
    rs = [_pic_summary(f) for f in refs]
    x = np.stack([v for v, _l in rs])
    for lo in range(0, len(refs), 256):
        r = x[lo:lo + 256] @ m.T
        for row in range(r.shape[0]):
            i = lo + row
            v, lev = rs[i]
            if not v.any():
                # a flat picture ranks flat candidates by how near their
                # level is, ahead of everything with a shape
                r[row] = np.where(mflat, 1.0 - np.abs(mlev - lev).sum(
                    axis=1) / 510.0, -1.0)
            top = np.argpartition(-r[row], kk - 1)[:kk]
            out[i] = [int(j) for j in top[np.argsort(-r[row, top])]]
    return out


def _aspect_cost(ref: "Candidate", c: "Candidate") -> float:
    """What a different shape costs.  A Write stretches a picture to its
    slot, so a file of another shape CAN be the one -- but a replacement is
    nearly always made at its slot's shape, and stretched to a square
    thumbnail a narrow 0 is a wide O."""
    if not (ref.width and ref.height and c.width and c.height):
        return 0.0
    off = abs(np.log((ref.width / ref.height) / (c.width / c.height)))
    return ASPECT_COST * max(0.0, float(off) - 0.03)


def picture_detail(path: str, width: int, height: int):
    """*path* stretched to *width* x *height* (at most :data:`DETAIL_SIDE` on
    its long side, the shape kept) the way a Write stretches a picture to its
    slot, as premultiplied float RGBA; None when Pillow can't read it."""
    from PIL import Image
    scale = min(1.0, DETAIL_SIDE / float(max(width, height, 1)))
    w = max(1, int(round(width * scale)))
    h = max(1, int(round(height * scale)))
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA").convert("RGBa")
            if im.size != (w, h):
                im = im.resize((w, h), Image.LANCZOS)
            return np.asarray(im, np.float32)
    except Exception:                                   # noqa: BLE001
        return None


def detail_error(x: np.ndarray, y: np.ndarray) -> float:
    """How far *y* is from *x*, both from :func:`picture_detail` at one
    size, in levels per pixel: brightness once *y*'s is fitted to *x*'s (a
    colour profile's gain and offset), plus alpha, plus half the colour
    difference after a saturation fit."""
    lx, ax, cx = _pic_parts(x)
    ly, ay, cy = _pic_parts(y)
    vy = float(ly.var())
    g = float(np.clip(((lx - lx.mean()) * (ly - ly.mean())).mean() / vy,
                      0.5, 2.0)) if vy > 1e-6 else 1.0
    o = float(lx.mean() - g * ly.mean())
    e = float(np.abs(lx - (g * ly + o)).mean())
    e += float(np.abs(ax - ay).mean())
    den = float((cy * cy).sum())
    s = float(np.clip((cx * cy).sum() / den, 0.7, 1.3)) if den > 1e-6 \
        else 1.0
    return e + 0.5 * float(np.abs(cx - s * cy).mean())


_GLYPH_RE = re.compile(r"u\+[0-9a-f]{4,6}", re.IGNORECASE)


def _name_like(key: str, path: str) -> bool:
    """*path* is named like the slot *key* (its name, or a glyph's code)."""
    a = os.path.splitext(os.path.basename(key))[0].lower()
    b = os.path.splitext(os.path.basename(path))[0].lower()
    if a == b:
        return True
    ga, gb = _GLYPH_RE.search(a), _GLYPH_RE.search(b)
    return bool(ga and gb and ga.group(0) == gb.group(0))


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

class FingerprintCache:
    """Fingerprints on disk under *folder*, keyed by a file's path, size and
    modification time, so a second search of the same folder decodes only
    what changed.  ``None`` folder = memory only."""

    def __init__(self, folder: Optional[str] = None):
        self.folder = folder
        self._mem: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(kind, cand):
        ident = "%s|%s|%d|%d|v%d" % (
            kind, os.path.normcase(os.path.abspath(cand.path)), cand.size,
            cand.mtime_ns, _FP_VERSION)
        return hashlib.sha1(ident.encode("utf-8")).hexdigest()

    def get(self, kind, cand):
        k = self._key(kind, cand)
        if not self.folder:
            with self._lock:
                return self._mem.get(k)
        try:
            with np.load(os.path.join(self.folder, k + ".npz"),
                         allow_pickle=False) as z:
                return z["fp"], json.loads(str(z["meta"]))
        except (OSError, ValueError, KeyError):
            return None

    def put(self, kind, cand, fp, meta):
        k = self._key(kind, cand)
        if not self.folder:
            with self._lock:
                self._mem[k] = (fp, meta)
            return
        try:
            os.makedirs(self.folder, exist_ok=True)
            tmp = os.path.join(self.folder, k + ".tmp.npz")
            with open(tmp, "wb") as f:
                np.savez(f, fp=fp, meta=np.array(json.dumps(meta)))
            os.replace(tmp, os.path.join(self.folder, k + ".npz"))
        except OSError:
            pass


def _stat_candidate(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    ext = os.path.splitext(path)[1].lower()
    return Candidate(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns,
                     lossless=(ext in LOSSLESS_SOUND) if ext in SOUND_EXTS
                     else ext not in LOSSY_PICTURE)


def fingerprint_file(kind: str, path: str, cache: FingerprintCache,
                     cancel: Optional[Callable] = None):
    """``(Candidate, fingerprint)`` for *path*, or None when it can't be
    read (or is silence)."""
    cand = _stat_candidate(path)
    if cand is None:
        return None
    hit = cache.get(kind, cand)
    if hit is not None:
        fp, meta = hit
        for k, v in meta.items():
            setattr(cand, k, v)
        return (cand, fp) if fp.size else None
    if kind == SOUND:
        got = decode_sound(path, cancel=cancel)
        fp = sound_features(got[0]) if got else None
        if got:
            cand.duration, cand.rate, cand.channels = got[1], got[2], got[3]
        if fp is not None:
            cand.end = _end_seconds(fp, cand.duration)
        meta = {"duration": cand.duration, "end": cand.end,
                "rate": cand.rate, "channels": cand.channels}
    else:
        got = picture_fingerprint(path)
        fp = got[0] if got else None
        if got:
            cand.width, cand.height = got[1], got[2]
        meta = {"width": cand.width, "height": cand.height}
    if got is None:
        return None
    cache.put(kind, cand, fp if fp is not None else np.zeros(0, np.uint8),
              meta)
    return (cand, fp) if fp is not None else None


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _longer(c: Candidate, ref: Candidate) -> bool:
    return c.end > ref.end + max(0.3, 0.03 * ref.end)


def _md5(path):
    try:
        return checksums.md5_file(path)
    except OSError:
        return None


def _same_sound(a, b):
    """Two candidate files are one sound: ``"same"`` (the same length, and
    alike), ``"variant"`` (one starts with all of the other), or None."""
    (ca, fa), (cb, fb) = a, b
    if ca.end > cb.end:
        (ca, fa), (cb, fb) = (cb, fb), (ca, fa)
    r, cov, _lv = sound_score(fa, fb)
    if r < SAME[SOUND] or cov < 0.9:
        return None
    if cb.end - ca.end > max(0.3, 0.03 * cb.end):
        return "variant"
    return "same"


def _decide_sound(key, ref, rfp, js, cands) -> Match:
    scored, closest = [], 0.0
    for j in js:
        r, cov, level = sound_score(rfp, cands[j][1])
        if cov < MIN_COVERAGE:
            continue
        if level > MAX_LEVEL:
            closest = max(closest, min(r, MATCH[SOUND] - 0.01))
            continue
        rank = r - (LONGER_COST if _longer(cands[j][0], ref) else 0.0)
        scored.append((rank, r, j, level))
    scored.sort(key=lambda t: -t[0])
    m = Match(key=key, ref=ref)
    if not scored or scored[0][1] < MATCH[SOUND]:
        m.score = max([closest] + [t[1] for t in scored])
        return m
    top, raw, top_j, top_level = scored[0]
    group, variants, others = [top_j], [], []
    for rank, _r, j, _lv in scored[1:]:
        how = (_same_sound(cands[top_j], cands[j])
               if rank >= top - GROUP_WINDOW else None)
        if how == "same":
            group.append(j)
        elif how == "variant":
            # the same sound at another length is no rival to it
            variants.append(j)
        else:
            others.append(rank)

    def quality(j):
        c = cands[j][0]
        return (c.lossless, min(c.rate, 192000), c.channels,
                _name_like(key, c.path), c.size, c.path)

    pick = max(group, key=quality)
    m.best = cands[pick][0]
    m.score = raw
    m.same = [cands[j][0] for j in group if j != pick]
    m.variants = [cands[j][0] for j in variants]
    m.runner_up = others[0] if others else None
    m.sure = raw >= SURE[SOUND] and top_level <= SURE_LEVEL and (
        m.runner_up is None or top - m.runner_up >= SURE_MARGIN[SOUND])
    m.longer = _longer(m.best, ref)
    return m


def _decide_picture(key, ref, rfp, js, cands) -> Match:
    scored = sorted(((picture_score(rfp, cands[j][1])
                      - _aspect_cost(ref, cands[j][0]), j) for j in js),
                    key=lambda t: -t[0])
    m = Match(key=key, ref=ref)
    if not scored or scored[0][0] < MATCH[PICTURE]:
        m.score = scored[0][0] if scored else 0.0
        return m
    top = scored[0][0]
    score_of = {j: r for r, j in scored}
    near = [j for r, j in scored if r >= top - REFINE_WINDOW][:REFINE_MAX]
    beyond = next((r for r, j in scored if j not in near), None)
    err = {}
    if len(near) > 1:
        # Thumbnails can't tell these apart: look at them at the copy's own
        # size, the way the Write that made it stretched the file.
        x = picture_detail(ref.path, ref.width, ref.height)
        if x is not None:
            h, w = x.shape[:2]
            for j in near:
                d = picture_detail(cands[j][0].path, w, h)
                if d is not None and d.shape == x.shape:
                    err[j] = (detail_error(x, d), d)
    if not err:
        best_j = near[0]
        group, others = [best_j], [j for j in near[1:]]
        m.runner_up = score_of[others[0]] if others else beyond
        m.sure = top >= SURE[PICTURE] and (
            m.runner_up is None or top - m.runner_up >= SURE_MARGIN[PICTURE])
    else:
        order = sorted(err, key=lambda j: err[j][0])
        best_e = err[order[0]][0]
        # a file named like the slot wins a dead heat (glyphs: U+0030)
        tie = [j for j in order if err[j][0] <= best_e * 1.05 + 0.05]
        named = [j for j in tie if _name_like(key, cands[j][0].path)]
        best_j = named[0] if named else order[0]
        best_e = err[best_j][0]
        group, others = [best_j], []
        for j in order:
            if j == best_j:
                continue
            if err[j][0] <= best_e * 1.25 + 0.3 and \
                    detail_error(err[best_j][1], err[j][1]) <= SAME_DETAIL:
                group.append(j)
            else:
                others.append(j)
        runner_e = err[others[0]][0] if others else None
        m.runner_up = score_of[others[0]] if others else beyond
        # (a different file outside the window is REFINE_WINDOW behind)
        m.sure = score_of[best_j] >= SURE[PICTURE] and (
            runner_e is None or runner_e >= best_e * SURE_DETAIL_RATIO + 0.3)

    def quality(j):
        c = cands[j][0]
        px = max(1, c.width * c.height)
        # clearly bigger (by a fifth) wins; within that, one named like the
        # slot, then the closest
        return (c.lossless, int(np.log(px) / np.log(1.2)),
                _name_like(key, c.path), -(err[j][0] if j in err else 0.0),
                c.path)

    pick = max(group, key=quality)
    m.best = cands[pick][0]
    m.score = score_of[pick]
    m.same = [cands[j][0] for j in group if j != pick]
    return m


def find_originals(kind: str, refs: Dict[str, str], roots: Sequence[str],
                   cache_dir: Optional[str] = None,
                   log: Optional[Callable] = None,
                   progress: Optional[Callable] = None,
                   cancel: Optional[Callable] = None) -> dict:
    """Match each copy in *refs* (``{key: path}``) to a file under *roots*.

    Returns a dict:

    ``matches``     ``{key: Match}`` (a key whose own file can't be read is
                    left out)
    ``sources``     how many files under *roots* were compared
    ``card_files``  how many were left out as an extract's own
    ``unreadable``  keys whose own file couldn't be read
    """
    if kind not in (SOUND, PICTURE):
        raise ValueError("kind must be %r or %r" % (SOUND, PICTURE))
    log = log or (lambda *a, **k: None)
    progress = progress or (lambda *a: None)
    cancel = cancel or (lambda: False)
    noun = "sound" if kind == SOUND else "picture"
    exts = SOUND_EXTS if kind == SOUND else PICTURE_EXTS
    cache = FingerprintCache(cache_dir)
    mem = FingerprintCache(None)        # the copies change: never on disk

    progress(0, 0, "Listing the files in the folder...")
    paths, card_files = list_files(roots, exts, cancel)
    log("%d %s file(s) to compare against%s." % (
        len(paths), noun,
        (" (%d more are files off a card, in an extract, and are left out)"
         % card_files) if card_files else ""), "info")

    def run_all(items, label, fn):
        out = [None] * len(items)
        done = [0]
        lock = threading.Lock()

        def one(i):
            if cancel():
                raise Cancelled()
            out[i] = fn(items[i])
            with lock:
                done[0] += 1
                progress(done[0], len(items), label)

        with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
            for f in [ex.submit(one, i) for i in range(len(items))]:
                f.result()
        return out

    keys = sorted(refs)
    got_refs = run_all(keys, "Reading the files picked now",
                       lambda k: fingerprint_file(kind, refs[k], mem, cancel))
    unreadable = [k for k, g in zip(keys, got_refs) if g is None]
    live = [(k, g) for k, g in zip(keys, got_refs) if g is not None]
    got_cands = run_all(paths, "Reading your files",
                        lambda p: fingerprint_file(kind, p, cache, cancel))
    cands = [g for g in got_cands if g is not None]
    if cancel():
        raise Cancelled()

    # The pick itself is never its own answer.  A file elsewhere with the
    # same bytes is fair game: a file that went on to the card untouched is
    # its own copy, and a better one of the same picture still wins.
    where = {os.path.normcase(os.path.abspath(c.path)): j
             for j, (c, _fp) in enumerate(cands)}
    itself = {k: where.get(os.path.normcase(os.path.abspath(rc.path)))
              for k, (rc, _fp) in live}

    progress(0, 0, "Comparing...")
    ref_fps = [fp for _k, (_c, fp) in live]
    cand_fps = [fp for _c, fp in cands]
    ranks = (_sound_ranks if kind == SOUND else _picture_ranks)(
        ref_fps, cand_fps, TOP_K)
    decide = _decide_sound if kind == SOUND else _decide_picture

    def one(n):
        k, (rc, rfp) = live[n]
        m = decide(k, rc, rfp,
                   [j for j in ranks.get(n, []) if j != itself.get(k)],
                   cands)
        if m.best is not None and m.best.size == rc.size:
            m.identical = _md5(m.best.path) == _md5(rc.path)
        return m

    matches = {m.key: m for m in run_all(list(range(len(live))),
                                         "Comparing", one)}

    found = sum(1 for m in matches.values() if m.best is not None)
    sure = sum(1 for m in matches.values() if m.sure)
    log("Found the file behind %d of %d %s(s) (%d certain, %d worth a look)."
        % (found, len(matches), noun, sure, found - sure),
        "success" if found else "warning")
    return {"matches": matches, "sources": len(cands),
            "card_files": card_files, "unreadable": unreadable}
