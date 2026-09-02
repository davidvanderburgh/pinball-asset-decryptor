#!/usr/bin/env python3
"""selectmedia.py - media preparation for the Spike 2 boot selector (item 90, v2).

The boot selector (tools/spike2_emu/codeselect/) can show a picture and an
animation per image, play a sound when the highlight moves, a sound on
confirm, and a music bed while an image is highlighted.  This tool turns card
images and loose files into the flat media directory the card builder
(mkmulticard.py --media-dir DIR) injects into /usr/local/codeselect/media/:

    art<N>.png     still art, PRE-SCALED to the panel size (RGBA)
    anim<N>.gif    animated GIF <= 512x288, <= 30 frames, <= 1.5 MB
    music<N>.wav   music bed, RIFF pcm_s16le 44100 Hz stereo
    move.wav       played on every LEFT/RIGHT/-/+ edge
    confirm.wav    played on START/SELECT, to completion, before the game boots
    confirm<N>.wav image N's OWN confirm sound; an image without one falls back
                   to confirm.wav
    media.json     the manifest (contract B of the v2 design):
                   {"images":[{"art":..,"anim":..|null,"music":..|null,"confirm":..|null},...],
                    "sound_move":..|null,"sound_confirm":..|null,"volume":50}

Subcommands (every one runs under WSL python3 and Windows python; ffmpeg is
used where it exists, PIL is the fallback for stills, nothing here derives
codec parameters - a cold card is REFUSED, not derived for minutes):

    logo  <card.raw> <out.png> [--size WxH]
          the title's own logo off the games partition (GameLogo.png,
          GameLogos/backglass_<model>.png, ALGameLogo.png), trimmed at IEND,
          scaled to the panel size.
    anim  <source> <out.gif> [--size WxH] [--seconds 3] [--fps 10] [--start 0]
          source = a video file, or '<card.raw>:attract' = the clip the card's
          scene data names attract_background; ffmpeg two-pass palette GIF,
          shrunk along a fixed ladder until it fits 1.5 MB / 30 frames.
    sound <card.raw> <idx> <out.wav> [--max-seconds 2] [--fade-ms 200]
          ONE sound decoded off the card with the Spike 2 emulator; needs the
          Extract-time params cache for that card (never derives).
    synth click|chime <out.wav>
          the built-in fallbacks (pure python, no ffmpeg needed).
    wav   <in> <out.wav>
          any audio file -> the selector's WAV format.
    prepare --primary P --extra E... --out DIR [...]
          the whole set + media.json.  Per-image specs:
            --art  N=auto | none | PATH (a still) | VIDEO@T (the frame T seconds into
                   an .mp4/.mov/.mkv/.avi)
            --anim N=auto | none | PATH | '<card.raw>:attract', each optionally
                   '@START[:SECONDS[:FPS]]' (START seconds into the clip; the
                   defaults are --start/--seconds/--fps)
            --music N=PATH | none
            --sound-confirm  a BARE auto|synth|none|PATH is the menu-wide sound
                   (confirm.wav); 'N=auto|synth|none|PATH' gives image N its own
                   confirm<N>.wav.  'auto' there is that IMAGE's own card sound
                   (not the primary's), 'auto@IDX' another index of the same
                   catalog, and 'none' means "no sound of its own" - image N
                   falls back to confirm.wav.  Both forms may be given together.
          --visual-only skips the sounds (sound_move/sound_confirm null, no WAV
          work; --music entries are still honoured) - the GUI's preview path.
          Every art<N>.png / anim<N>.gif / confirm<N>.wav gets a sidecar
          '<name>.src.json' {source, mtime, size, params}; when the sidecar still
          matches the source file and the parameters the file is kept and
          'cached' is printed, so a preview after a text-only change costs
          nothing (and a per-image confirm never re-boots the emulator).
          media.json records each image's 'art_source' / 'anim_source' /
          'confirm_source' (the spec strings) for the GUI to round-trip.  A
          synthetic sound is never cached: it is the fallback a cold params
          cache leaves behind, and the next run must try the card again.
          Leftovers of an earlier, bigger set are swept AFTER the targets are
          decided - a file the run keeps or regenerates is never deleted; a
          --visual-only run sweeps only art/anim leftovers (it says nothing
          about the sounds).
    check <DIR>
          validate a media directory against the contract, print the table
          (the .src.json sidecars are ignored: only what media.json names counts).
    info  <FILE>...
          dimensions / frames / duration / peak of media files.

See DESIGN.md ('Media') for the contract; mkmulticard.py consumes media.json.
"""
import argparse
import array
import hashlib
import json
import math
import os
import pickle
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# ============================================================================ the contract
MEDIA_BUDGET = 20 << 20                     # the whole set, bytes
MEDIA_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
GIF_MAX_BYTES = 1536 * 1024                 # 1.5 MB
GIF_MAX_FRAMES = 30
GIF_MAX_W, GIF_MAX_H = 512, 288
GIF_DEFAULT_DELAY_MS = 100                  # what the selector uses when a frame says 0
WAV_RATE = 44100
PANEL_SIZES = {2: (512, 288), 3: (384, 216)}   # 4+ -> PANEL_SIZE_MANY
PANEL_SIZE_MANY = (256, 144)
PANEL_SIZE_ONE = (512, 288)
DEFAULT_VOLUME = 50
# Where the sound defaults come from (turtles_pro 1.59 catalog; the art report):
MOVE_IDX = 1717                 # 0.079 s stereo transient
MOVE_MAX_SECONDS = 0.5
CONFIRM_IDX = 350               # 'SOUND: STINGER' 1.54 s
CONFIRM_SECONDS = 1.5
CONFIRM_FADE_MS = 200
ATTRACT_CLIP = "attract_background"
LOGO_CANDIDATES = ("assets/lcd/GameLogo.png",
                   "assets/lcd/GameLogos/backglass_{model}.png",
                   "assets/lcd/ALGameLogo.png")
FORBIDDEN_OUTPUT_PREFIXES = ("/mnt/d/Pinball/images", "D:/Pinball/images", "D:\\Pinball\\images")
PARAMS_CACHE_DIRNAME = "pinball_spike2_params"
PARAMS_REV_TAG = ".r2"
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi")          # an art spec 'PATH@T' grabs a frame of these
SIDECAR_SUFFIX = ".src.json"                            # art<N>.png.src.json / anim<N>.gif.src.json
STILL_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "PNG"), (b"\xff\xd8\xff", "JPEG"), (b"GIF87a", "GIF"),
                    (b"GIF89a", "GIF"), (b"BM", "BMP"), (b"II*\x00", "TIFF"), (b"MM\x00*", "TIFF"))
STILL_KINDS = "PNG/JPEG/GIF/BMP/TIFF/WebP"
_NUM_RE = r"\d+(?:\.\d+)?"
ANIM_PARAMS_RE = re.compile(r"^(%s)(?::(%s)(?::(\d+))?)?$" % (_NUM_RE, _NUM_RE))   # START[:SECONDS[:FPS]]
ART_AT_RE = re.compile(r"^%s$" % _NUM_RE)                                             # T
SOUND_AT_RE = re.compile(r"^\d+$")                                                    # auto@IDX
STALE_FULL_RE = re.compile(r"^(?:(?:art|anim|music)\d+\.(?:png|gif|wav)"
                           r"|confirm\d+\.wav|(?:move|confirm)\.wav)$")
STALE_VISUAL_RE = re.compile(r"^(art|anim)\d+\.(png|gif)$")


class Refused(Exception):
    """A request the tool will not carry out; the message says why."""


def say(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ============================================================================ pure helpers
def parse_size(s):
    """'512x288' -> (512, 288)."""
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", s or "")
    if not m:
        raise Refused("size must be WxH, not %r" % (s,))
    w, h = int(m.group(1)), int(m.group(2))
    if w < 8 or h < 8:
        raise Refused("size %dx%d is too small" % (w, h))
    return w, h


def panel_size_for(n_images):
    """The still-art panel for an n-image menu: 512x288 for 2, 384x216 for 3, 256x144 for 4+."""
    if n_images <= 1:
        return PANEL_SIZE_ONE
    return PANEL_SIZES.get(n_images, PANEL_SIZE_MANY)


def is_png(data):
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def trim_png(data):
    """The PNG up to and including its IEND chunk.

    A slot-replaced logo (the 1987 card) is a 71,925-byte PNG zero-padded to
    the original's 379,645 bytes; stb stops at IEND so it decodes, but the
    padding wastes card space and confuses digests.  Raises Refused when the
    bytes are not a PNG or have no IEND."""
    if not is_png(data):
        raise Refused("not a PNG (no signature)")
    pos = 8
    n = len(data)
    while pos + 8 <= n:
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4:pos + 8]
        end = pos + 8 + length + 4
        if end > n:
            break
        if ctype == b"IEND":
            return bytes(data[:end])
        pos = end
    raise Refused("PNG has no IEND chunk (truncated?)")


def png_size(data):
    """(w, h) from the IHDR, or None."""
    if not is_png(data) or len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack_from(">II", data, 16)


def gif_info(data):
    """{'w','h','frames','delays_ms','bytes','duration_ms'} of a GIF, parsed by hand
    (no PIL): walks every block; a frame's delay is the Graphic Control Extension
    that precedes it (0 -> the selector's 100 ms, reported as such)."""
    if data[:6] not in (b"GIF89a", b"GIF87a"):
        raise Refused("not a GIF")
    w, h, packed = struct.unpack_from("<HHB", data, 6)
    pos = 13
    if packed & 0x80:
        pos += 3 * (2 << (packed & 7))
    delays = []
    pending = None
    n = len(data)

    def skip_subblocks(p):
        while p < n:
            ln = data[p]
            p += 1
            if ln == 0:
                return p
            p += ln
        return p

    while pos < n:
        b = data[pos]
        if b == 0x3B:
            break
        if b == 0x21:
            label = data[pos + 1]
            if label == 0xF9 and pos + 7 < n:
                pending = struct.unpack_from("<H", data, pos + 4)[0] * 10
            pos = skip_subblocks(pos + 2)
        elif b == 0x2C:
            lp = data[pos + 9]
            pos += 10
            if lp & 0x80:
                pos += 3 * (2 << (lp & 7))
            pos += 1                       # LZW min code size
            pos = skip_subblocks(pos)
            delays.append(pending if pending else GIF_DEFAULT_DELAY_MS)
            pending = None
        else:
            raise Refused("GIF: unknown block 0x%02x at %d" % (b, pos))
    return {"w": w, "h": h, "frames": len(delays), "delays_ms": delays,
            "bytes": len(data), "duration_ms": sum(delays)}


def check_media_name(name):
    if not MEDIA_NAME_RE.match(name or ""):
        raise Refused("media name %r: only [A-Za-z0-9._-] are allowed (flat, no directories)" % (name,))
    return name


def model_from_title(title):
    """'turtles_pro' -> 'pro' (the GameLogos/backglass_<model>.png suffix); '' when unknown."""
    m = re.search(r"_(le|prem|pro)$", title or "")
    return m.group(1) if m else ""


def split_source(s):
    """A video path, or '<card.raw>:<clip>' -> (path, clip|None).  Windows drive
    letters are not clips: the prefix must be an existing file."""
    if os.path.isfile(s):
        return s, None
    if ":" in s:
        path, tok = s.rsplit(":", 1)
        if tok and "/" not in tok and "\\" not in tok and os.path.isfile(path):
            return path, tok
    raise Refused("source %r is neither a file nor '<card.raw>:attract'" % (s,))


def split_index_spec(spec, n):
    """The grammar every per-image flag shares: 'N=value' -> (N, 'value'), a bare
    'value' -> (None, 'value').  Refuses an index outside 0..n-1."""
    if "=" not in spec:
        return None, spec
    idx, val = spec.split("=", 1)
    idx = idx.strip()
    if not idx.isdigit() or not (0 <= int(idx) < n):
        raise Refused("image index in %r must be 0..%d" % (spec, n - 1))
    return int(idx), val.strip()


def parse_index_spec(specs, n, default):
    """['1=auto', '0=none'] (or a bare 'none' for every image) -> a list of n values.
    Refuses an index outside 0..n-1 and a spec without '='."""
    out = [default] * n
    for spec in specs or []:
        idx, val = split_index_spec(spec, n)
        if idx is None:
            out = [val] * n
        else:
            out[idx] = val
    return out


def parse_sound_specs(specs, n, default):
    """--sound-confirm's mixed forms -> (menu_wide, [per_image|None, ...]).

    A BARE value ('auto', 'synth', 'none', a path) is the menu-wide sound - the one
    every image falls back to; 'N=value' is image N's OWN sound.  The two forms may be
    given together and in any order; the last bare value wins, as does the last entry
    for an index.  An image nobody named gets None: no sound of its own.  This is the
    one place the per-image grammar differs from --art/--anim/--music, where a bare
    value applies to every image - here it names the fallback instead."""
    wide = default
    per = [None] * n
    for spec in specs or []:
        idx, val = split_index_spec(spec, n)
        if idx is None:
            wide = val
        else:
            per[idx] = val
    return wide, per


# ---- per-image specs (pure: nothing here touches the filesystem) ---------------------------
def _split_at(spec):
    """'X@tail' -> ('X', 'tail') when the tail looks like parameters (digits, dots,
    colons - possibly empty), else (spec, None): a path holding a literal '@'
    ('clip@home.mp4') stays a path."""
    if "@" in spec:
        head, tail = spec.rsplit("@", 1)
        if re.match(r"^[\d.:]*$", tail):
            return head, tail
    return spec, None


def is_video_path(path):
    return (path or "").lower().endswith(VIDEO_EXTS)


def parse_anim_spec(spec, start=0.0, seconds=3.0, fps=10):
    """One --anim value -> {'kind': 'none'} or
    {'kind': 'auto'|'file', 'source': PATH|'<card>:clip'|None, 'start', 'seconds', 'fps', 'spec'}.

    'auto' / 'auto@START[:SECONDS[:FPS]]' = the card's attract clip; 'PATH' / 'PATH@...'
    a video file; '<card.raw>:attract' / '...:attract@...' a clip off another card.
    START is seconds into the source; SECONDS and FPS fall back to the run's
    --seconds/--fps (the GIF budget ladder clamps them like before)."""
    spec = (spec or "").strip()
    if not spec:
        raise Refused("animation spec is empty (use none, auto, or a path)")
    if spec == "none":
        return {"kind": "none", "spec": spec}
    if spec.startswith(("auto@", "none@")):
        head, tail = spec.split("@", 1)          # a keyword's '@' is always the separator
    else:
        head, tail = _split_at(spec)
    p = {"start": float(start), "seconds": float(seconds), "fps": int(fps)}
    if tail is not None:
        m = ANIM_PARAMS_RE.match(tail)
        if not m:
            raise Refused("animation %r: after '@' comes START[:SECONDS[:FPS]], not %r" % (spec, tail))
        p["start"] = float(m.group(1))
        if m.group(2):
            p["seconds"] = float(m.group(2))
        if m.group(3):
            p["fps"] = int(m.group(3))
    if p["seconds"] <= 0 or p["fps"] <= 0:
        raise Refused("animation %r: seconds and fps must be positive" % (spec,))
    if p["start"] < 0:
        raise Refused("animation %r: start must be >= 0" % (spec,))
    if head == "none":
        raise Refused("animation %r: 'none' takes no parameters" % (spec,))
    if head == "auto":
        return dict(kind="auto", source=None, spec=spec, **p)
    if not head:
        raise Refused("animation %r: no source before '@'" % (spec,))
    return dict(kind="file", source=head, spec=spec, **p)


def parse_art_spec(spec):
    """One --art value -> {'kind': 'none'|'auto'} or {'kind': 'file', 'source': PATH} or
    {'kind': 'video', 'source': PATH, 'at': T} ('VIDEO@T' = the frame T seconds into an
    .mp4/.mov/.mkv/.avi; a bare video path is its first frame).  Every dict carries 'spec'."""
    spec = (spec or "").strip()
    if not spec:
        raise Refused("art spec is empty (use none, auto, or a path)")
    if spec in ("none", "auto"):
        return {"kind": spec, "spec": spec}
    head, tail = _split_at(spec)
    if tail is not None:
        if not ART_AT_RE.match(tail):
            raise Refused("art %r: after '@' comes the time in seconds, not %r" % (spec, tail))
        if not is_video_path(head):
            raise Refused("art %r: '@T' picks a frame of a video (%s), and %s is not one"
                          % (spec, "/".join(e[1:] for e in VIDEO_EXTS), head or "''"))
        return {"kind": "video", "source": head, "at": float(tail), "spec": spec}
    if is_video_path(head):
        return {"kind": "video", "source": head, "at": 0.0, "spec": spec}
    return {"kind": "file", "source": head, "spec": spec}


def parse_sound_spec(spec, idx=None):
    """One --sound-move / --sound-confirm value (bare or the right of 'N=') ->
    {'kind': 'none'|'synth'|'auto'|'file', 'source': PATH|None, 'idx': int|None, 'spec': ...}.

    'none' = no sound, 'synth' = the built-in click/chime, 'auto' = the catalog sound
    the tool picked for that slot off the card, 'auto@IDX' another index of the same
    catalog ('selectmedia.py sound <card.raw> IDX out.wav' auditions one), and anything
    else an audio file.  A path holding a literal '@' stays a path: only digits after
    it are an index, exactly as --art's '@T' only takes a number."""
    spec = (spec or "").strip()
    if not spec:
        raise Refused("sound spec is empty (use none, synth, auto, or a path)")
    if spec in ("none", "synth", "auto"):
        return {"kind": spec, "source": None, "idx": None if spec != "auto" else idx, "spec": spec}
    if spec.startswith(("auto@", "synth@", "none@")):
        head, tail = spec.split("@", 1)          # a keyword's '@' is always the separator
    else:
        head, tail = _split_at(spec)
    if tail is None:
        return {"kind": "file", "source": spec, "idx": None, "spec": spec}
    if not SOUND_AT_RE.match(tail):
        raise Refused("sound %r: after '@' comes the catalog index, not %r" % (spec, tail))
    if head != "auto":
        raise Refused("sound %r: '@IDX' picks a sound off the card, so it needs 'auto'" % (spec,))
    return {"kind": "auto", "source": None, "idx": int(tail), "spec": spec}


def still_kind(path):
    """'PNG'/'JPEG'/'GIF'/'BMP'/'TIFF'/'WebP' by signature, or None (a card image, a
    video, a text file...).  Sniffed BEFORE any decoder sees the file, so a 7.8 GB
    card handed in as art is refused in microseconds."""
    with open(path, "rb") as f:
        head = f.read(16)
    for sig, kind in STILL_SIGNATURES:
        if head.startswith(sig):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WebP"
    return None


# ---- the sidecar cache ----------------------------------------------------------------------
def sidecar_path(target):
    return target + SIDECAR_SUFFIX


def source_stamp(path):
    """{'source': abspath, 'mtime', 'size'} of a source file (a still, a video, or a
    whole card - stat only, never opened)."""
    st = os.stat(path)
    return {"source": os.path.abspath(path), "mtime": st.st_mtime, "size": st.st_size}


def _json_norm(params):
    return json.loads(json.dumps(params))


def cache_matches(sidecar, stamp, params):
    """True when a sidecar dict records exactly this source (path, mtime, size) and
    these generation parameters (compared after a JSON round trip: tuples == lists)."""
    if not isinstance(sidecar, dict):
        return False
    return (sidecar.get("source") == stamp["source"] and sidecar.get("mtime") == stamp["mtime"]
            and sidecar.get("size") == stamp["size"] and sidecar.get("params") == _json_norm(params))


def read_sidecar(target):
    try:
        with open(sidecar_path(target), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_sidecar(target, stamp, params):
    d = dict(stamp)
    d["params"] = _json_norm(params)
    with open(sidecar_path(target), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, sort_keys=True)
        f.write("\n")


def drop_sidecar(target):
    try:
        os.remove(sidecar_path(target))
    except OSError:
        pass


def is_cached(target, stamp, params):
    """The target exists and its sidecar matches: keep it, print 'cached'."""
    return os.path.isfile(target) and cache_matches(read_sidecar(target), stamp, params)


def check_output_dir(path):
    """Refuse an output under David's card library; return the absolute path."""
    a = os.path.abspath(path)
    n = os.path.normpath(os.path.realpath(a) if os.path.exists(a) else
                         os.path.join(os.path.realpath(os.path.dirname(a)), os.path.basename(a)))
    # the spelled path is tested too: a WSL-style /mnt/d/... typed on Windows (or the
    # reverse) must still be recognised, whatever abspath makes of it
    forms = {n.replace("\\", "/").lower(), path.replace("\\", "/").lower().rstrip("/")}
    for pre in FORBIDDEN_OUTPUT_PREFIXES:
        p = pre.replace("\\", "/").lower()
        for f in forms:
            if f == p or f.startswith(p + "/"):
                raise Refused("refusing to write under %s (David's card library): %s" % (pre, path))
    return a


# ---- the manifest ---------------------------------------------------------------------------
def build_manifest(images, sound_move=None, sound_confirm=None, volume=DEFAULT_VOLUME, sources=None):
    """images = [(art|None, anim|None, music|None[, confirm|None]), ...] -> the media.json
    dict.  A row's fourth field is the image's OWN confirm sound; null (or a 3-field row)
    means it falls back to the menu-wide sound_confirm.
    sources = [(art_spec, anim_spec[, confirm_spec]), ...] (one per image) adds
    'art_source' / 'anim_source' / 'confirm_source' - the spec strings the GUI
    round-trips; a 2-field row leaves confirm_source null."""
    vol = int(volume)
    if not (0 <= vol <= 100):
        raise Refused("volume must be 0..100")
    out = {"images": [], "sound_move": sound_move or None,
           "sound_confirm": sound_confirm or None, "volume": vol}
    if sources is not None and len(sources) != len(images):
        raise Refused("build_manifest: %d sources for %d images" % (len(sources), len(images)))
    for i, row_in in enumerate(images):
        art, anim, music = row_in[0], row_in[1], row_in[2]
        confirm = row_in[3] if len(row_in) > 3 else None
        for nm in (art, anim, music, confirm, sound_move, sound_confirm):
            if nm:
                check_media_name(nm)
        row = {"art": art or None, "anim": anim or None, "music": music or None,
               "confirm": confirm or None}
        if sources is not None:
            src = tuple(sources[i])
            row["art_source"], row["anim_source"] = src[0], src[1]
            row["confirm_source"] = src[2] if len(src) > 2 else None
        out["images"].append(row)
    return out


def validate_manifest(m):
    """Raise Refused unless *m* has exactly the media.json shape."""
    if not isinstance(m, dict) or not isinstance(m.get("images"), list):
        raise Refused("media.json: 'images' must be a list")
    if not m["images"]:
        raise Refused("media.json: no images")
    for i, im in enumerate(m["images"]):
        if not isinstance(im, dict):
            raise Refused("media.json: images[%d] is not an object" % i)
        for k in ("art", "anim", "music", "confirm"):
            v = im.get(k)
            if v is not None:
                if not isinstance(v, str):
                    raise Refused("media.json: images[%d].%s must be a name or null" % (i, k))
                check_media_name(v)
        for k in ("art_source", "anim_source", "confirm_source"):
            v = im.get(k)
            if v is not None and not isinstance(v, str):
                raise Refused("media.json: images[%d].%s must be a spec string or null" % (i, k))
        extra = set(im) - {"art", "anim", "music", "confirm",
                           "art_source", "anim_source", "confirm_source"}
        if extra:
            raise Refused("media.json: images[%d] has unknown keys %s" % (i, sorted(extra)))
    for k in ("sound_move", "sound_confirm"):
        v = m.get(k)
        if v is not None:
            if not isinstance(v, str):
                raise Refused("media.json: %s must be a name or null" % k)
            check_media_name(v)
    vol = m.get("volume", DEFAULT_VOLUME)
    if not isinstance(vol, int) or isinstance(vol, bool) or not (0 <= vol <= 100):
        raise Refused("media.json: volume must be an integer 0..100")
    return m


def manifest_files(m):
    """Every media name the manifest references, in order, without duplicates."""
    names = []
    for im in m["images"]:
        for k in ("art", "anim", "music", "confirm"):
            if im.get(k) and im[k] not in names:
                names.append(im[k])
    for k in ("sound_move", "sound_confirm"):
        if m.get(k) and m[k] not in names:
            names.append(m[k])
    return names


def check_budget(sizes):
    """{name: bytes} -> total; Refused when the set is over MEDIA_BUDGET."""
    total = sum(sizes.values())
    if total > MEDIA_BUDGET:
        raise Refused("media set is %s, over the %s budget" % (fmt_bytes(total), fmt_bytes(MEDIA_BUDGET)))
    return total


def fmt_bytes(n):
    if n >= 1 << 20:
        return "%.2f MB" % (n / float(1 << 20))
    if n >= 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%d B" % n


# ---- the GIF budget planner ---------------------------------------------------------------
class GifPlan(object):
    """One encode attempt: size, length and rate.  cost() orders the ladder."""
    __slots__ = ("w", "h", "seconds", "fps")

    def __init__(self, w, h, seconds, fps):
        self.w, self.h, self.seconds, self.fps = int(w), int(h), float(seconds), int(fps)

    @property
    def frames(self):
        return int(round(self.seconds * self.fps))

    def cost(self):
        return self.w * self.h * self.frames

    def __repr__(self):
        return "%dx%d %.1fs %dfps (%d frames)" % (self.w, self.h, self.seconds, self.fps, self.frames)

    def __eq__(self, o):
        return isinstance(o, GifPlan) and (self.w, self.h, self.seconds, self.fps) == (o.w, o.h, o.seconds, o.fps)


GIF_MIN_W = 256                 # the smallest panel the menu draws (4+ images)
GIF_MIN_SECONDS = 1.5
GIF_MIN_FPS = 5


def _even(x):
    """Nearest even integer (ffmpeg's scalers and the GIF panel want even sizes;
    rounding to nearest keeps the aspect from drifting down the ladder)."""
    return 2 * int(round(x / 2.0))


def _scaled(w, h, factor, floor_w):
    nw = max(floor_w, _even(w * factor))
    nh = max(2, _even(h * nw / float(w)))
    return nw, nh


def gif_first_plan(size, seconds=3.0, fps=10):
    """Clamp a request to the contract: <= 512x288 (aspect kept), <= 30 frames
    (rate first, then length)."""
    w, h = size
    if w > GIF_MAX_W or h > GIF_MAX_H:
        f = min(GIF_MAX_W / float(w), GIF_MAX_H / float(h))
        w, h = _even(w * f), _even(h * f)
    seconds = float(seconds)
    fps = int(fps)
    if seconds <= 0 or fps <= 0:
        raise Refused("seconds and fps must be positive")
    if round(seconds * fps) > GIF_MAX_FRAMES:
        fps = max(1, int(GIF_MAX_FRAMES // seconds))
        if round(seconds * fps) > GIF_MAX_FRAMES:
            seconds = GIF_MAX_FRAMES / float(fps)
    return GifPlan(w, h, seconds, fps)


def gif_shrink(plan):
    """The next cheaper plan, or None at the floor.  Order of the ladder: the
    frame rate down to 8 (30 -> 24 frames), the picture down in 12.5 % steps to
    320 wide, the rate to 6, the length to 2 s, the rate to 5, the picture to
    256 wide, the length to 1.5 s.  Every step strictly lowers cost()."""
    w, h, s, f = plan.w, plan.h, plan.seconds, plan.fps
    if f > 8:
        return GifPlan(w, h, s, 8)
    if w > 320:
        nw, nh = _scaled(w, h, 0.875, 320)
        return GifPlan(nw, nh, s, f)
    if f > 6:
        return GifPlan(w, h, s, 6)
    if s > 2.0:
        return GifPlan(w, h, max(2.0, s - 0.5), f)
    if f > GIF_MIN_FPS:
        return GifPlan(w, h, s, GIF_MIN_FPS)
    if w > GIF_MIN_W:
        nw, nh = _scaled(w, h, 0.875, GIF_MIN_W)
        return GifPlan(nw, nh, s, f)
    if s > GIF_MIN_SECONDS:
        return GifPlan(w, h, GIF_MIN_SECONDS, f)
    return None


def gif_ladder(plan):
    """Every plan the encoder will try, first to last."""
    out = [plan]
    while True:
        nxt = gif_shrink(out[-1])
        if nxt is None:
            return out
        out.append(nxt)


def gif_fits(info):
    """None when a gif_info() result meets the contract, else the reason."""
    if info["bytes"] > GIF_MAX_BYTES:
        return "%s > %s" % (fmt_bytes(info["bytes"]), fmt_bytes(GIF_MAX_BYTES))
    if info["frames"] > GIF_MAX_FRAMES:
        return "%d frames > %d" % (info["frames"], GIF_MAX_FRAMES)
    if info["w"] > GIF_MAX_W or info["h"] > GIF_MAX_H:
        return "%dx%d > %dx%d" % (info["w"], info["h"], GIF_MAX_W, GIF_MAX_H)
    return None


# ---- WAV ------------------------------------------------------------------------------------
def wav_info(path):
    """{'rate','channels','sampwidth','frames','seconds'} via the wave module (PCM only)."""
    with wave.open(path, "rb") as w:
        rate, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
    return {"rate": rate, "channels": ch, "sampwidth": sw, "frames": n,
            "seconds": n / float(rate) if rate else 0.0}


def wav_contract_error(info):
    """None when a wav_info() meets the contract (pcm_s16le 44100 Hz 1-2 ch), else why."""
    if info["sampwidth"] != 2:
        return "%d-bit, need 16-bit PCM" % (info["sampwidth"] * 8)
    if info["rate"] != WAV_RATE:
        return "%d Hz, need %d" % (info["rate"], WAV_RATE)
    if info["channels"] not in (1, 2):
        return "%d channels, need 1 or 2" % info["channels"]
    return None


def wav_stats(path):
    """peak and RMS in dBFS of a 16-bit WAV (pure python; fine for a few seconds)."""
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        sw = w.getsampwidth()
    if sw != 2 or not raw:
        return None, None
    a = array.array("h")
    a.frombytes(raw[:len(raw) - len(raw) % 2])
    if sys.byteorder != "little":
        a.byteswap()
    peak = max(abs(x) for x in a) if a else 0
    sq = 0
    for x in a:
        sq += x * x
    rms = math.sqrt(sq / float(len(a))) if a else 0
    to_db = lambda v: (20 * math.log10(v / 32768.0)) if v > 0 else -120.0
    return to_db(peak), to_db(rms)


def write_wav_s16(path, left, right, rate=WAV_RATE):
    """Interleave two equal-length sequences of ints (clipped to s16) into a stereo WAV."""
    n = len(left)
    inter = array.array("h", [0]) * (2 * n)
    for i in range(n):
        l, r = int(left[i]), int(right[i])
        inter[2 * i] = -32768 if l < -32768 else (32767 if l > 32767 else l)
        inter[2 * i + 1] = -32768 if r < -32768 else (32767 if r > 32767 else r)
    if sys.byteorder != "little":
        inter.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(inter.tobytes())
    return path


def apply_fade(samples, fade_ms, rate=WAV_RATE, fade_in_ms=0):
    """Linear fade-out over the last fade_ms (and a fade-in over fade_in_ms) in place-ish."""
    out = list(samples)
    n = len(out)
    fo = min(n, int(rate * fade_ms / 1000.0))
    for i in range(fo):                       # ends exactly at 0
        out[n - fo + i] = int(out[n - fo + i] * (fo - 1 - i) / float(fo))
    fi = min(n, int(rate * fade_in_ms / 1000.0))
    for i in range(fi):                       # starts exactly at 0
        out[i] = int(out[i] * i / float(fi))
    return out


# ---- synthetic sounds (pure python, no ffmpeg) ----------------------------------------------
def _tone(freq, seconds, amp, fade_in_ms, fade_out_ms, rate=WAV_RATE):
    n = int(rate * seconds)
    s = [int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    return apply_fade(s, fade_out_ms, rate, fade_in_ms)


def synth_samples(kind):
    """click = 1400 Hz, 40 ms, faded; chime = 660 Hz 150 ms then 990 Hz 250 ms, faded."""
    if kind == "click":
        return _tone(1400, 0.040, 0.5, 4, 20)
    if kind == "chime":
        return _tone(660, 0.150, 0.45, 8, 60) + _tone(990, 0.250, 0.45, 8, 120)
    raise Refused("synth kind must be click or chime, not %r" % (kind,))


def synth_wav(kind, out):
    s = synth_samples(kind)
    return write_wav_s16(out, s, s)


# ============================================================================ ffmpeg / PIL
def find_ffmpeg(name="ffmpeg"):
    try:
        from pinball_decryptor.core import audio as _audio
        p = _audio.find_ffmpeg() if name == "ffmpeg" else _audio.find_ffprobe()
        if p:
            return p
    except Exception:
        pass
    return shutil.which(name)


def run(cmd, what):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise Refused("%s failed (rc %d): %s" % (what, r.returncode, " | ".join(tail)))
    return r


def scale_png(src, out, size, seek=None):
    """Aspect-fit *src* (any image ffmpeg/PIL reads) into an RGBA WxH PNG, letterboxed
    with transparency.  ffmpeg (lanczos) when present, PIL otherwise.  seek=T grabs
    the frame T seconds into a video (ffmpeg only; refused past the end)."""
    w, h = size
    ff = find_ffmpeg()
    if ff:
        vf = ("scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos,"
              "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=#00000000,format=rgba" % (w, h, w, h))
        cmd = [ff, "-y", "-v", "error"]
        if seek is not None:
            cmd += ["-ss", "%.3f" % float(seek)]
        try:
            os.remove(out)                 # an old file must not pass for a frame ffmpeg never wrote
        except OSError:
            pass
        run(cmd + ["-i", src, "-frames:v", "1", "-vf", vf, out], "ffmpeg scale")
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            raise Refused("ffmpeg wrote no frame from %s%s (past the end of the clip?)"
                          % (src, " at %.2f s" % float(seek) if seek is not None else ""))
        return out
    if seek is not None:
        raise Refused("ffmpeg is required to grab a video frame (%s at %.2f s)" % (src, float(seek)))
    try:
        from PIL import Image
    except ImportError:
        raise Refused("neither ffmpeg nor PIL is available to scale %s" % src)
    im = Image.open(src).convert("RGBA")
    im.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    canvas.save(out, "PNG", optimize=True)
    return out


def make_gif(src, out, plan, start=0.0, workdir=None):
    """Two-pass palette GIF (palettegen stats_mode=diff, paletteuse bayer 5,
    diff_mode rectangle, -loop 0) of *plan* seconds from *start*."""
    ff = find_ffmpeg()
    if not ff:
        raise Refused("ffmpeg is required to build a GIF")
    pal = os.path.join(workdir or os.path.dirname(out) or ".", "_pal_%d.png" % os.getpid())
    pre = ["-y", "-v", "error"]
    if start:
        pre += ["-ss", "%.3f" % start]
    pre += ["-t", "%.3f" % plan.seconds, "-i", src]
    fps_scale = "fps=%d,scale=%d:%d:flags=lanczos" % (plan.fps, plan.w, plan.h)
    run([ff] + pre + ["-vf", fps_scale + ",palettegen=max_colors=256:stats_mode=diff", pal],
        "ffmpeg palettegen")
    try:
        run([ff] + pre + ["-i", pal, "-lavfi",
                          fps_scale + "[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                          "-frames:v", str(plan.frames), "-loop", "0", out], "ffmpeg paletteuse")
    finally:
        try:
            os.remove(pal)
        except OSError:
            pass
    return out


def gif_fit(src, out, plan, start=0.0, workdir=None, log=say):
    """Encode along gif_ladder(plan) until the result meets the contract.  Returns
    (gif_info, plan_used, attempts).  Says so when it had to shrink."""
    attempts = 0
    for p in gif_ladder(plan):
        attempts += 1
        make_gif(src, out, p, start, workdir)
        with open(out, "rb") as f:
            info = gif_info(f.read())
        why = gif_fits(info)
        if why is None:
            if attempts > 1:
                log("  gif: %s did not fit; shrunk to %r (%s, %d frames)"
                    % (repr(plan), p, fmt_bytes(info["bytes"]), info["frames"]))
            return info, p, attempts
        log("  gif: %r is %s - shrinking" % (p, why))
    raise Refused("GIF from %s does not fit %s / %d frames even at the ladder's floor"
                  % (src, fmt_bytes(GIF_MAX_BYTES), GIF_MAX_FRAMES))


def normalise_wav(src, out, max_seconds=None, fade_ms=0):
    """Any audio -> pcm_s16le 44100 Hz stereo (mono duplicated), optionally cut and faded.
    ffmpeg when present; without it only a 44100 Hz 16-bit PCM WAV can be rewritten."""
    ff = find_ffmpeg()
    if ff:
        cmd = [ff, "-y", "-v", "error", "-i", src]
        af = []
        if max_seconds:
            cmd += ["-t", "%.3f" % max_seconds]
        if fade_ms:
            dur = _duration_of(src)
            if max_seconds and dur:
                dur = min(dur, max_seconds)
            elif max_seconds:
                dur = max_seconds
            if dur:
                st = max(0.0, dur - fade_ms / 1000.0)
                af.append("afade=t=out:st=%.3f:d=%.3f" % (st, fade_ms / 1000.0))
        if af:
            cmd += ["-af", ",".join(af)]
        cmd += ["-ar", str(WAV_RATE), "-ac", "2", "-c:a", "pcm_s16le", out]
        run(cmd, "ffmpeg wav")
        return out
    info = wav_info(src)
    if wav_contract_error(info):
        raise Refused("no ffmpeg; %s is %s" % (src, wav_contract_error(info)))
    with wave.open(src, "rb") as w:
        raw = w.readframes(w.getnframes())
    a = array.array("h")
    a.frombytes(raw[:len(raw) - len(raw) % 2])
    if sys.byteorder != "little":
        a.byteswap()
    if info["channels"] == 2:
        L, R = a[0::2], a[1::2]
    else:
        L = R = a
    if max_seconds:
        n = int(WAV_RATE * max_seconds)
        L, R = L[:n], R[:n]
    if fade_ms:
        L, R = apply_fade(L, fade_ms), apply_fade(R, fade_ms)
    return write_wav_s16(out, L, R)


def _duration_of(path):
    try:
        return wav_info(path)["seconds"]
    except Exception:
        pass
    fp = find_ffmpeg("ffprobe")
    if not fp:
        return None
    r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(r.stdout.decode().strip())
    except ValueError:
        return None


# ============================================================================ the card
def open_card(path):
    if not os.path.isfile(path):
        raise Refused("card image %s does not exist" % path)
    from pinball_decryptor.plugins.stern.explorer import CardImage
    return CardImage(path)


def games_part(ci):
    """The browsable ext partition whose root has no 'usr' and holds a title directory."""
    for p in ci.partitions():
        if not p.browsable:
            continue
        try:
            names = {e.name for e in ci.list_dir(p.index, "/")}
        except Exception:
            continue
        if "usr" in names or "lib" in names:
            continue
        if title_dir(ci, p.index, names):
            return p.index
    raise Refused("%s: no games partition (a browsable ext4 without /usr holding <title>/game)" % ci.path)


def title_dir(ci, part, names=None):
    """The title directory of a games partition: the real directory holding a 'game' file
    ('turtles_pro' on the TMNT cards); the root 'game' symlink's target decides ties."""
    entries = ci.list_dir(part, "/")
    link = next((e.link_target for e in entries if e.name == "game" and e.is_symlink), None)
    if link and "/" in link:
        cand = link.split("/", 1)[0]
        if any(e.name == cand and e.is_dir for e in entries):
            return cand
    for e in entries:
        if not e.is_dir or e.is_symlink or e.name in ("lost+found", "spk"):
            continue
        try:
            kids = {k.name for k in ci.list_dir(part, e.path)}
        except Exception:
            continue
        if "game" in kids:
            return e.name
    return None


def logo_bytes(ci, part, title):
    """(png_bytes trimmed at IEND, card_path) of the title's logo, trying the known layouts."""
    model = model_from_title(title)
    for rel in LOGO_CANDIDATES:
        if "{model}" in rel and not model:
            continue
        path = "/%s/%s" % (title, rel.format(model=model))
        try:
            data = ci.preview(part, path, cap=64 << 20)
        except FileNotFoundError:
            continue
        if data is None:
            raise Refused("%s is not a regular file under 64 MB" % path)
        return trim_png(data), path
    raise Refused("%s: no logo under /%s/assets/lcd/ (tried %s)"
                  % (ci.path, title, ", ".join(LOGO_CANDIDATES)))


def find_clip(reader, name):
    """(card_path, node) of the video asset whose scene.radium names it *name* - the walk
    engine.extract_videos does (ftyp sniff + _parse_radium of the scene's radium)."""
    from pinball_decryptor.plugins.stern import engine
    vids = []
    radiums = {}
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if path.endswith("/scene.radium"):
            radiums[path[:-len("/scene.radium")]] = node
        elif node["size"] >= 0x1000:
            b = reader.peek(node, 12)
            if len(b) >= 12 and b[4:8] == b"ftyp":
                vids.append((path, node))
    parsed = {}
    want = name.lower()
    for path, node in vids:
        if "/scene.assets/" not in path:
            continue
        hashdir, ref = path.rsplit("/scene.assets/", 1)
        rn = radiums.get(hashdir)
        if rn is None:
            continue
        if hashdir not in parsed:
            try:
                parsed[hashdir] = (engine._parse_radium(reader.read_file_bytes(rn))
                                   if rn["size"] <= 0x2000000 else {})
            except Exception:
                parsed[hashdir] = {}
        title = parsed[hashdir].get(ref)
        if title and title.lower() == want:
            return path, node
    raise Refused("no video named %r on this card (%d videos, %d scenes)" % (name, len(vids), len(radiums)))


def extract_clip(card, name, out):
    ci = open_card(card)
    part = games_part(ci)
    reader = ci.reader(part)
    path, node = find_clip(reader, name)
    reader.extract_file(node, out)
    return path, node["size"]


# ============================================================================ the sound pull
def params_cache_candidates(extra=None):
    """Where a params cache may live, in order: the app's own temp dir, --params-cache /
    $SELECTMEDIA_PARAMS_CACHE, and under WSL every Windows user's %TEMP% copy."""
    dirs = [os.path.join(tempfile.gettempdir(), PARAMS_CACHE_DIRNAME)]
    for d in (extra, os.environ.get("SELECTMEDIA_PARAMS_CACHE")):
        if d:
            dirs.append(d)
    if os.path.isdir("/mnt/c/Users"):
        try:
            for u in sorted(os.listdir("/mnt/c/Users")):
                d = os.path.join("/mnt/c/Users", u, "AppData", "Local", "Temp", PARAMS_CACHE_DIRNAME)
                if os.path.isdir(d):
                    dirs.append(d)
        except OSError:
            pass
    seen, out = set(), []
    for d in dirs:
        a = os.path.abspath(d)
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def card_fingerprint(reader):
    """engine._fingerprint() computed off the card: sha256 of the whole game ELF + the
    first 0x20000 bytes of image.bin, read through the ext4 reader (no extract)."""
    img_ino, fw_ino = reader.find_spike_assets()
    if img_ino is None or fw_ino is None:
        raise Refused("no image.bin / game ELF on this games partition")
    fw, img = reader.read_inode(fw_ino), reader.read_inode(img_ino)
    h = hashlib.sha256()
    h.update(reader.read_file_bytes(fw))
    # the first 0x20000 bytes exactly as extract_file() lays them out (the walk
    # read_file_bytes does, stopped early; disk_ranges() is absolute-offset, for writes)
    want = min(0x20000, img["size"])
    head = bytearray(want)
    bs = reader.block_size
    for log, phys, cnt in reader._runs(img):
        for j in range(cnt):
            fo = (log + j) * bs
            if fo >= want:
                break
            n = min(bs, want - fo)
            head[fo:fo + n] = reader._read((phys + j) * bs, n)
    h.update(bytes(head))
    return h.hexdigest(), fw, img


def find_params_cache(fp, extra_dir=None):
    """The <fp32>.r2.pkl for a fingerprint, or None."""
    for d in params_cache_candidates(extra_dir):
        p = os.path.join(d, fp[:32] + PARAMS_REV_TAG + ".pkl")
        if os.path.isfile(p):
            return p
    return None


class SoundSource(object):
    """One card's sound catalog, decoded on the Spike 2 emulator - ONLY when the
    Extract-time params cache for the card exists (a cold derive is minutes)."""

    def __init__(self, card, workdir=None, params_cache=None, log=say):
        self.card = card
        self.log = log
        self.ci = open_card(card)
        self.part = games_part(self.ci)
        self.reader = self.ci.reader(self.part)
        self.fp, self.fw_node, self.img_node = card_fingerprint(self.reader)
        self.cache = find_params_cache(self.fp, params_cache)
        self.workdir = workdir
        self.emu = None
        self.params = None
        self._tmp = None

    @property
    def warm(self):
        return self.cache is not None

    def refuse_reason(self):
        return ("%s: no params cache for fingerprint %s (looked in %s); an Extract of this card "
                "on this machine would create it - this tool never derives"
                % (os.path.basename(self.card), self.fp[:32], ", ".join(params_cache_candidates())))

    def open(self):
        if self.emu is not None:
            return
        if not self.warm:
            raise Refused(self.refuse_reason())
        from pinball_decryptor.plugins.stern import engine
        from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu
        self._tmp = tempfile.mkdtemp(prefix="selectmedia_snd_", dir=self.workdir)
        gr = os.path.join(self._tmp, "game_real")
        im = os.path.join(self._tmp, "image.bin")
        t0 = time.time()
        self.reader.extract_file(self.fw_node, gr)
        self.reader.extract_file(self.img_node, im)
        self.log("  sound: streamed game ELF + image.bin (%s) off the card in %.1f s"
                 % (fmt_bytes(self.img_node["size"]), time.time() - t0))
        self.emu = Spike2Emu(gr, im)
        self.emu.boot()
        with open(self.cache, "rb") as f:
            params = pickle.load(f)
        if not params or "key0" not in params[0]:
            raise Refused("%s is a pre-SFX-naming cache the app would re-derive; refusing" % self.cache)
        own = os.path.join(tempfile.gettempdir(), PARAMS_CACHE_DIRNAME)
        if os.path.dirname(os.path.abspath(self.cache)) == os.path.abspath(own):
            params = engine._load_or_derive_params(self.emu, gr, im, lambda *a, **k: None, None)
        self.params = {p["idx"]: p for p in params}
        self.log("  sound: %d sounds from %s (boot %.1f s)" % (len(self.params), self.cache, time.time() - t0))

    def decode(self, idx, max_seconds=None):
        """(L, R) lists of ints at 44100 Hz, stereo (mono duplicated), or Refused."""
        self.open()
        p = self.params.get(int(idx))
        if p is None:
            raise Refused("idx%04d is not in this card's catalog (%d sounds)" % (int(idx), len(self.params)))
        res = self.emu.decode(p, max_secs=max_seconds)
        if res is None:
            raise Refused("idx%04d did not decode" % int(idx))
        L, R, stereo = res
        L = L.tolist()
        R = R.tolist() if stereo else L
        return L, R

    def close(self):
        if self.emu is not None:
            try:
                self.emu.close()
            except Exception:
                pass
            self.emu = None
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


def render_sound(src, idx, out, max_seconds=None, fade_ms=0):
    L, R = src.decode(idx, max_seconds)
    if fade_ms:
        L, R = apply_fade(L, fade_ms), apply_fade(R, fade_ms)
    write_wav_s16(out, L, R)
    return wav_info(out)


# ============================================================================ reporting
def describe(path):
    """One line about a media file: kind, dimensions/frames/duration, bytes."""
    name = os.path.basename(path)
    size = os.path.getsize(path)
    ext = name.lower().rsplit(".", 1)[-1]
    try:
        if ext == "png":
            with open(path, "rb") as f:
                d = f.read()
            wh = png_size(d)
            return "%-14s %9s  PNG %dx%d" % (name, fmt_bytes(size), wh[0], wh[1]) if wh else \
                   "%-14s %9s  PNG (bad header)" % (name, fmt_bytes(size))
        if ext == "gif":
            with open(path, "rb") as f:
                gi = gif_info(f.read())
            return "%-14s %9s  GIF %dx%d %d frames %.1f s (delay %d ms)" % (
                name, fmt_bytes(size), gi["w"], gi["h"], gi["frames"], gi["duration_ms"] / 1000.0,
                gi["delays_ms"][0] if gi["delays_ms"] else 0)
        if ext == "wav":
            wi = wav_info(path)
            pk, rms = wav_stats(path)
            return "%-14s %9s  WAV %d Hz %dch %d-bit %.3f s peak %.1f dBFS rms %.1f dBFS" % (
                name, fmt_bytes(size), wi["rate"], wi["channels"], wi["sampwidth"] * 8, wi["seconds"],
                pk if pk is not None else -120, rms if rms is not None else -120)
    except Exception as e:
        return "%-14s %9s  (unreadable: %s)" % (name, fmt_bytes(size), e)
    return "%-14s %9s" % (name, fmt_bytes(size))


def check_media_dir(d, log=say):
    """Validate DIR/media.json + every file it names against the contract; returns the
    manifest.  Raises Refused on the first violation; prints the table."""
    mp = os.path.join(d, "media.json")
    if not os.path.isfile(mp):
        raise Refused("%s has no media.json" % d)
    with open(mp, encoding="utf-8") as f:
        m = validate_manifest(json.load(f))
    sizes = {}
    for name in manifest_files(m):
        p = os.path.join(d, name)
        if not os.path.isfile(p):
            raise Refused("media.json names %s but it is not in %s" % (name, d))
        sizes[name] = os.path.getsize(p)
        ext = name.lower().rsplit(".", 1)[-1]
        with open(p, "rb") as f:
            data = f.read()
        if ext == "png":
            if not is_png(data) or not png_size(data):
                raise Refused("%s is not a PNG" % name)
            if len(trim_png(data)) != len(data):
                raise Refused("%s has bytes after IEND" % name)
        elif ext == "gif":
            why = gif_fits(gif_info(data))
            if why:
                raise Refused("%s: %s" % (name, why))
        elif ext == "wav":
            why = wav_contract_error(wav_info(p))
            if why:
                raise Refused("%s: %s" % (name, why))
        else:
            raise Refused("%s: only png/gif/wav belong in a media set" % name)
    total = check_budget(sizes)
    for name in sizes:
        log(describe(os.path.join(d, name)))
    own = sum(1 for im in m["images"] if im.get("confirm"))
    log("%d files, %s of the %s budget; media.json OK (%d images, move=%s confirm=%s%s volume=%d)"
        % (len(sizes), fmt_bytes(total), fmt_bytes(MEDIA_BUDGET), len(m["images"]),
           "y" if m["sound_move"] else "n", "y" if m["sound_confirm"] else "n",
           " +%d own" % own if own else "", m["volume"]))
    return m


# ============================================================================ subcommands
def cmd_logo(a):
    ci = open_card(a.card)
    part = games_part(ci)
    title = title_dir(ci, part)
    data, path = logo_bytes(ci, part, title)
    size = parse_size(a.size)
    tmp = a.out + ".src.png"
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        scale_png(tmp, a.out, size)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    src_wh = png_size(data)
    say("logo: %s (%s, %s) -> %s" % (path, fmt_bytes(len(data)),
                                    "%dx%d" % src_wh if src_wh else "?", describe(a.out)))
    return 0


def cmd_anim(a):
    src, clip = split_source(a.source)
    size = parse_size(a.size) if a.size else (GIF_MAX_W, GIF_MAX_H)
    plan = gif_first_plan(size, a.seconds, a.fps)
    work = tempfile.mkdtemp(prefix="selectmedia_anim_", dir=a.work)
    try:
        if clip:
            name = ATTRACT_CLIP if clip == "attract" else clip
            mov = os.path.join(work, "clip.mov")
            path, n = extract_clip(src, name, mov)
            say("anim: %s = %s (%s)" % (name, path, fmt_bytes(n)))
            src = mov
        info, used, tries = gif_fit(src, a.out, plan, a.start, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    say("anim: %s (%r, %d attempt%s)" % (describe(a.out), used, tries, "" if tries == 1 else "s"))
    return 0


def cmd_sound(a):
    src = SoundSource(a.card, a.work, a.params_cache)
    if not src.warm:
        raise Refused(src.refuse_reason())
    try:
        render_sound(src, a.idx, a.out, a.max_seconds, a.fade_ms)
    finally:
        src.close()
    say("sound: idx%04d -> %s" % (a.idx, describe(a.out)))
    return 0


def cmd_synth(a):
    synth_wav(a.kind, a.out)
    say("synth: %s -> %s" % (a.kind, describe(a.out)))
    return 0


def cmd_wav(a):
    normalise_wav(a.src, a.out, a.max_seconds, a.fade_ms)
    say("wav: %s -> %s" % (a.src, describe(a.out)))
    return 0


def cmd_check(a):
    check_media_dir(a.dir)
    return 0


def cmd_info(a):
    for p in a.files:
        say(describe(p))
    return 0


# ---- prepare ----------------------------------------------------------------------------------
def _card_sound(card, idx, out, max_seconds, fade_ms, synth_kind, sources, name, log):
    """One catalog sound off *card* into *out*.  Every refusal on the way - a card that
    is not there, a cold params cache (this tool NEVER derives: that is minutes), an idx
    the catalog does not hold - falls back to the built-in synth_kind and says why.
    Returns True when the card's own sound landed, False when the fallback did."""
    try:
        src = sources.get(card)
        if src is None:
            src = sources[card] = SoundSource(card, log=log)
        if not src.warm:
            raise Refused("params cache is cold for %s" % os.path.basename(card))
        render_sound(src, idx, out, max_seconds, fade_ms)
    except Refused as e:
        log("  %s: %s; synthetic %s instead" % (name, e, synth_kind))
        synth_wav(synth_kind, out)
        return False
    log("  %s: idx%04d of %s" % (name, idx, os.path.basename(card)))
    return True


def _sound_default(spec, sources, primary, idx, max_seconds, fade_ms, synth_kind, out, log):
    """Resolve PATH|auto|auto@IDX|synth|none for a MENU-WIDE sound into *out*; returns
    the name or None.  'auto' takes it off the primary card - the menu-wide sound is the
    whole menu's, so it is the primary's catalog that names it."""
    p = parse_sound_spec(spec, idx)
    name = os.path.basename(out)
    if p["kind"] == "none":
        return None
    if p["kind"] == "synth":
        synth_wav(synth_kind, out)
        log("  %s: synthetic %s" % (name, synth_kind))
        return name
    if p["kind"] == "auto":
        _card_sound(primary, p["idx"], out, max_seconds, fade_ms, synth_kind, sources, name, log)
        return name
    if not os.path.isfile(p["source"]):
        raise Refused("%s: %s is not a file" % (name, p["source"]))
    normalise_wav(p["source"], out)
    log("  %s: %s" % (name, p["source"]))
    return name


def _prepare_confirm(i, card, spec, out, sources, log=say):
    """confirm<i>.wav for one image, or None when the image has no confirm sound of its
    own and falls back to the menu-wide confirm.wav ('none', or no 'N=' spec at all).

    'auto' pulls CONFIRM_IDX off THIS image's own card - its sounds, not the primary's -
    and 'auto@IDX' another index of that card's catalog; a cold params cache falls back
    to the built-in chime rather than deriving for minutes.  Anything else is an audio
    file.  The sidecar cache keeps a file whose source and parameters have not changed,
    so a second prepare never re-boots the emulator for a sound it already has; the
    synthetic fallback is deliberately NOT cached, so the run after an Extract warms the
    params cache picks the real sound up."""
    if spec is None:
        return None
    p = parse_sound_spec(spec, CONFIRM_IDX)
    if p["kind"] == "none":
        return None
    target = os.path.join(out, "confirm%d.wav" % i)
    name = os.path.basename(target)
    if p["kind"] == "synth":
        drop_sidecar(target)
        synth_wav("chime", target)
        log("  %s: synthetic chime" % name)
        return name
    if p["kind"] == "auto":
        params = {"kind": "auto", "idx": int(p["idx"]), "seconds": CONFIRM_SECONDS,
                  "fade_ms": CONFIRM_FADE_MS}
        if os.path.isfile(card):
            stamp = source_stamp(card)
            if is_cached(target, stamp, params):
                log("  %s: cached (idx%04d of %s)" % (name, p["idx"], os.path.basename(card)))
                return name
        else:
            stamp = None                          # _card_sound will say what is missing
        drop_sidecar(target)
        if _card_sound(card, p["idx"], target, CONFIRM_SECONDS, CONFIRM_FADE_MS,
                       "chime", sources, name, log) and stamp is not None:
            write_sidecar(target, stamp, params)
        return name
    src = p["source"]
    if not os.path.isfile(src):
        raise Refused("%s: %s is not a file" % (name, src))
    stamp = source_stamp(src)
    params = {"kind": "file"}
    if is_cached(target, stamp, params):
        log("  %s: cached (%s)" % (name, src))
        return name
    drop_sidecar(target)
    normalise_wav(src, target)
    log("  %s: %s" % (name, src))
    write_sidecar(target, stamp, params)
    return name


def _prepare_art(i, img, spec, size, out, work, card, log=say):
    """art<i>.png from a parsed --art spec (or None for 'none'): the card's logo, a
    still, or a video frame; kept when the sidecar cache matches.  Returns the name."""
    if spec["kind"] == "none":
        return None
    target = os.path.join(out, "art%d.png" % i)
    name = os.path.basename(target)
    params = {"kind": spec["kind"], "size": list(size)}
    if spec["kind"] == "auto":
        src = img
        if not os.path.isfile(src):
            raise Refused("card image %s does not exist" % src)
    else:
        src = spec["source"]
        if not os.path.isfile(src):
            raise Refused("art %d: %s is not a file" % (i, src))
        if spec["kind"] == "video":
            params["at"] = float(spec["at"])
        elif still_kind(src) is None:
            raise Refused("art %d: %s is not a still image (%s by signature; %s) - a video frame is 'VIDEO@T'"
                          % (i, src, STILL_KINDS, fmt_bytes(os.path.getsize(src))))
    stamp = source_stamp(src)
    if is_cached(target, stamp, params):
        log("  %s: cached (%s)" % (name, spec["spec"] if spec["kind"] != "auto"
                                   else "auto, the logo of %s" % os.path.basename(img)))
        return name
    drop_sidecar(target)
    if spec["kind"] == "auto":
        ci, part, title = card(img)
        data, path = logo_bytes(ci, part, title)
        tmp = os.path.join(work, "logo%d.png" % i)
        with open(tmp, "wb") as f:
            f.write(data)
        scale_png(tmp, target, size)
        log("  %s: %s of %s (%s)" % (name, path, os.path.basename(img), fmt_bytes(len(data))))
    elif spec["kind"] == "video":
        scale_png(src, target, size, seek=spec["at"])
        log("  %s: the frame %.2f s into %s" % (name, spec["at"], src))
    else:
        scale_png(src, target, size)
        log("  %s: %s (%s)" % (name, src, still_kind(src)))
    write_sidecar(target, stamp, params)
    return name


def _prepare_anim(i, img, spec, size, out, work, log=say):
    """anim<i>.gif from a parsed --anim spec (or None for 'none'): the card's attract
    clip, a video file, or a clip off another card, START seconds in, SECONDS long at
    FPS, down the GIF budget ladder; kept when the sidecar cache matches."""
    if spec["kind"] == "none":
        return None
    target = os.path.join(out, "anim%d.gif" % i)
    name = os.path.basename(target)
    plan = gif_first_plan(size, spec["seconds"], spec["fps"])
    if spec["kind"] == "auto":
        src_path, clip = img, ATTRACT_CLIP
        if not os.path.isfile(src_path):
            raise Refused("card image %s does not exist" % src_path)
    else:
        src_path, clip = split_source(spec["source"])
        if clip == "attract":
            clip = ATTRACT_CLIP
    stamp = source_stamp(src_path)
    params = {"kind": spec["kind"], "clip": clip, "size": list(size), "start": float(spec["start"]),
              "seconds": float(spec["seconds"]), "fps": int(spec["fps"])}
    if is_cached(target, stamp, params):
        log("  %s: cached (%s)" % (name, spec["spec"] if spec["kind"] != "auto"
                                   else "%s, the %s clip of %s" % (spec["spec"], clip, os.path.basename(img))))
        return name
    drop_sidecar(target)
    if clip:
        mov = os.path.join(work, "clip%d.mov" % i)
        path, nbytes = extract_clip(src_path, clip, mov)
        log("  %s: %s of %s (%s)" % (name, path, os.path.basename(src_path), fmt_bytes(nbytes)))
        src = mov
    else:
        src = src_path
        log("  %s: %s" % (name, src))
    if spec["start"] or spec["seconds"] != 3.0 or spec["fps"] != 10:
        log("  %s: from %.2f s, %.2f s at %d fps" % (name, spec["start"], spec["seconds"], spec["fps"]))
    gif_fit(src, target, plan, spec["start"], work, log)
    write_sidecar(target, stamp, params)
    return name


def sweep_stale(out, manifest, visual_only=False, log=say):
    """Remove media files (and their sidecars) an earlier, bigger run left behind: files
    matching the media naming that the manifest does not reference.  Called AFTER the
    targets are decided, so a file this run kept or regenerated is never touched.  A
    visual-only run sweeps only art/anim leftovers (it says nothing about sounds)."""
    referenced = set(manifest_files(manifest))
    pat = STALE_VISUAL_RE if visual_only else STALE_FULL_RE
    removed = []
    for fn in sorted(os.listdir(out)):
        base = fn[:-len(SIDECAR_SUFFIX)] if fn.endswith(SIDECAR_SUFFIX) else fn
        if base == "media.json" or base in referenced or not pat.match(base):
            continue
        os.remove(os.path.join(out, fn))
        removed.append(fn)
        log("  removed stale %s" % fn)
    return removed


def cmd_prepare(a):
    images = [a.primary] + list(a.extra or [])
    n = len(images)
    out = check_output_dir(a.out)
    os.makedirs(out, exist_ok=True)
    size = parse_size(a.size) if a.size else panel_size_for(n)
    arts = [parse_art_spec(s) for s in parse_index_spec(a.art, n, "auto")]
    anims = [parse_anim_spec(s, a.start, a.seconds, a.fps) for s in parse_index_spec(a.anim, n, "none")]
    musics = parse_index_spec(a.music, n, "none")
    # --sound-confirm's bare value is the menu-wide fallback; 'N=' entries are per image
    confirm_wide, confirm_each = parse_sound_specs(a.sound_confirm, n, "auto")
    for spec in confirm_each:
        if spec is not None:
            parse_sound_spec(spec, CONFIRM_IDX)          # refuse a bad one before any work
    visual_only = bool(getattr(a, "visual_only", False))
    say("prepare: %d image%s, panel %dx%d, out %s%s"
        % (n, "" if n == 1 else "s", size[0], size[1], out, " (visual only)" if visual_only else ""))
    work = tempfile.mkdtemp(prefix="selectmedia_prep_", dir=a.work)
    sources = {}
    cards = {}
    rows = []
    specs = []

    def card(path):
        if path not in cards:
            ci = open_card(path)
            part = games_part(ci)
            cards[path] = (ci, part, title_dir(ci, part))
        return cards[path]

    try:
        for i, img in enumerate(images):
            art = _prepare_art(i, img, arts[i], size, out, work, card)
            anim = _prepare_anim(i, img, anims[i], size, out, work)
            music = None
            spec = musics[i]
            if spec != "none":
                if not os.path.isfile(spec):
                    raise Refused("music %d: %s is not a file" % (i, spec))
                music_out = os.path.join(out, "music%d.wav" % i)
                normalise_wav(spec, music_out)
                say("  music%d.wav: %s" % (i, spec))
                music = os.path.basename(music_out)
            rows.append([art, anim, music, None])
            specs.append((arts[i]["spec"], anims[i]["spec"], confirm_each[i]))
        if visual_only:
            move = confirm = None
            say("  sounds: skipped (--visual-only)")
        else:
            move = _sound_default(a.sound_move, sources, a.primary, MOVE_IDX, MOVE_MAX_SECONDS, 0,
                                  "click", os.path.join(out, "move.wav"), say)
            confirm = _sound_default(confirm_wide, sources, a.primary, CONFIRM_IDX, CONFIRM_SECONDS,
                                     CONFIRM_FADE_MS, "chime", os.path.join(out, "confirm.wav"), say)
            for i, img in enumerate(images):
                rows[i][3] = _prepare_confirm(i, img, confirm_each[i], out, sources, say)
    finally:
        for s in sources.values():
            s.close()
        shutil.rmtree(work, ignore_errors=True)
    m = build_manifest(rows, move, confirm, a.volume, sources=specs)
    with open(os.path.join(out, "media.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
        f.write("\n")
    # stale files from an earlier run of a bigger set would ride along in the budget
    sweep_stale(out, m, visual_only)
    say("media.json: " + json.dumps(m))
    check_media_dir(out)
    return 0


# ============================================================================ CLI
def _add_work(s):
    s.add_argument("--work", default=os.environ.get("SELECTMEDIA_WORK") or None,
                   help="scratch directory for temporaries (default: the system temp dir)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="selectmedia.py",
                                 description="media preparation for the Spike 2 boot selector (item 90)")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True

    s = sub.add_parser("logo", help="the title's logo off a card, scaled to the panel")
    s.add_argument("card")
    s.add_argument("out")
    s.add_argument("--size", default="512x288")
    s.set_defaults(fn=cmd_logo)

    s = sub.add_parser("anim", help="an animated GIF from a video or '<card.raw>:attract'")
    s.add_argument("source")
    s.add_argument("out")
    s.add_argument("--size", default=None, help="WxH (default 512x288, the contract's cap)")
    s.add_argument("--seconds", type=float, default=3.0)
    s.add_argument("--fps", type=int, default=10)
    s.add_argument("--start", type=float, default=0.0, help="seconds into the source")
    _add_work(s)
    s.set_defaults(fn=cmd_anim)

    s = sub.add_parser("sound", help="one sound decoded off a card (needs its params cache)")
    s.add_argument("card")
    s.add_argument("idx", type=int)
    s.add_argument("out")
    s.add_argument("--max-seconds", type=float, default=2.0)
    s.add_argument("--fade-ms", type=int, default=200)
    s.add_argument("--params-cache", default=None,
                   help="an extra directory to look for <fp>.r2.pkl in (e.g. the Windows %%TEMP%% copy from WSL)")
    _add_work(s)
    s.set_defaults(fn=cmd_sound)

    s = sub.add_parser("synth", help="the built-in click / chime")
    s.add_argument("kind", choices=("click", "chime"))
    s.add_argument("out")
    s.set_defaults(fn=cmd_synth)

    s = sub.add_parser("wav", help="any audio -> pcm_s16le 44100 Hz stereo")
    s.add_argument("src")
    s.add_argument("out")
    s.add_argument("--max-seconds", type=float, default=None)
    s.add_argument("--fade-ms", type=int, default=0)
    s.set_defaults(fn=cmd_wav)

    s = sub.add_parser("prepare", help="the whole media set + media.json")
    s.add_argument("--primary", required=True)
    s.add_argument("--extra", action="append", default=[])
    s.add_argument("--out", required=True)
    s.add_argument("--art", action="append", default=[], metavar="N=PATH|VIDEO@T|auto|none",
                   help="still art per image; VIDEO@T = the frame T seconds into an mp4/mov/mkv/avi")
    s.add_argument("--anim", action="append", default=[], metavar="N=PATH|auto|none[@START[:SECONDS[:FPS]]]",
                   help="animation per image; '@START[:SECONDS[:FPS]]' overrides --start/--seconds/--fps for it")
    s.add_argument("--music", action="append", default=[], metavar="N=PATH|none")
    s.add_argument("--sound-move", default="auto", metavar="PATH|auto|synth|none")
    s.add_argument("--sound-confirm", action="append", default=[],
                   metavar="PATH|auto|synth|none | N=PATH|auto|synth|none",
                   help="the menu-wide confirm sound (a bare value, the default 'auto'); "
                        "'N=...' gives image N its own confirm<N>.wav ('auto' = that image's "
                        "own card, 'none' = it falls back to the menu-wide one)")
    s.add_argument("--visual-only", action="store_true",
                   help="art/anim (+music) only: no move/confirm sounds, none pulled off a card (the GUI preview)")
    s.add_argument("--volume", type=int, default=DEFAULT_VOLUME)
    s.add_argument("--size", default=None, help="panel WxH (default by image count)")
    s.add_argument("--seconds", type=float, default=3.0, help="animation length")
    s.add_argument("--fps", type=int, default=10)
    s.add_argument("--start", type=float, default=0.0, help="seconds into the animation source")
    _add_work(s)
    s.set_defaults(fn=cmd_prepare)

    s = sub.add_parser("check", help="validate a media directory")
    s.add_argument("dir")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("info", help="describe media files")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_info)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Refused as e:
        say("refused: %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
