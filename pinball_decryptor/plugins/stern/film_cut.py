"""THE MOVIE CUTTER: a clip, a sound and a still cut from a film (item 142).

A film is 70 to 140 minutes and about 3 GB; a mode wants seconds. The Modes tab's "My
video..." copies a whole file into the mode's folder, which is right for a clip and wrong
for a film. This module cuts a SPAN instead, straight into what the card needs, and the
project keeps only the cut (``clip.mp4``, ``end.wav``, ``art.png``), never the film.

* :func:`cut_clip` - a span as a clip in the video bank's format: H.264 Constrained
  Baseline 3.0, 8-bit 4:2:0, the bank's size (1360x768 on Godzilla), 30 fps, silent
  (:func:`mode_assets._encode_args`, the encoder every mode clip goes through). The
  crop is the person's: keep the film's letterbox (the whole picture, bars added) or
  fill the frame (the picture scaled up and the sides cut off).
* :func:`cut_sound` - a span's audio as a WAV in the shape of the record it becomes:
  44.1 kHz, 16-bit PCM, the record's channel count (a mode's own record is mono), its
  loudness brought to a stock callout's inside the CODEC's range (:data:`PEAK_RANGE`, so
  the file sounds quieter than full scale on a PC) and LIMITED, not capped, then faded in and out
  over 40 ms so neither edge clicks (``reference_spike2_wav_level``: a gain capped at
  the ceiling is a measured no-op, and a limiter that runs when nothing passed the
  ceiling makes the sound quieter).
* :func:`grab_still` - a frame as the screen's PNG art, 640 wide by default, both sides
  a multiple of 4 (BC3), so it fits where the screen draws it, unscaled at x=360 y=200
  on a 1360x768 display.
* :func:`preview_frame` - the frame at a time as the clip will show it, small, for the
  dialog.

WHAT EVERY CUT DOES WITH A FILM. The films carry a cover PNG as a second video stream
and often a subtitle stream, so every cut names its stream (``0:V:0`` is the first
video stream that is not an attached picture, ``0:a:0`` the first audio). ``-ss`` goes
BEFORE ``-i`` so ffmpeg seeks by the index instead of decoding an hour of film to get
there (a preview frame measured 0.29 s), and a film is only ever read.

Only the app's own ffmpeg (``core.audio.find_ffmpeg``) and ffprobe are used.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import wave
from dataclasses import dataclass

import numpy as np

from ...core import audio as _audio
from . import mode_assets as MA

MAX_SECONDS = 30.0
CLIP_SIZE = (1360, 768)          # the Godzilla in-game video bank's frame
CROPS = ("letterbox", "fill")
RATE = 44100
STILL_WIDTH = 640
EDGE_FADE_MS = 40.0
#: A stock Godzilla mono callout peaks at the codec's whole range with a crest factor of
#: about 2.6 (peak over active RMS; ``reference_spike2_wav_level``). A cut is gained to
#: that active RMS.
STOCK_CREST = 2.6
CEILING = 0.97                   # of the peak range; the soft limiter never reaches it
#: The peak range a cut is levelled into, by channel count: the sound codec's own range
#: (``engine._MONO_RANGE`` / ``_STEREO_RANGE``), not 16-bit full scale. MEASURED 2026-09-16
#: (item 142, in-process Spike2Emu on the Premium 1.16 stock image.bin, a 4 s cut encoded
#: into an appended mono record and decoded back): the sound path takes a WAV's samples as
#: they are, so a full-scale cut (peak 31757) decoded clipped at 11147 - correlation 0.940,
#: peak error 20611, 29% of samples off by more than 100 - while the same cut levelled into
#: 11147 (peak 10802) came back bit-exact (peak error 0, correlation 1.0), as did the KAIJU
#: RUSH level (peak 9000). Measured again the same day on the tab's own 6 s end.wav (peak
#: 10744, bit-exact; scaled to full scale it clipped at 11147) and on a STEREO cut encoded
#: over a stock stereo record (scale 21): at this level (peak 20679) bit-exact in both
#: channels; at full scale (peak 31587) clipped at 21453, correlation 0.989.
PEAK_RANGE = {1: 11147, 2: 21452}
_NO_WINDOW = _audio._CREATE_FLAGS


class FilmCutError(ValueError):
    """A cut that cannot be made as asked. The message is a sentence for the person."""


# ---- what a film is ------------------------------------------------------------------
@dataclass
class FilmInfo:
    path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    audio_channels: int = 0
    audio_rate: int = 0

    def summary(self):
        """``1920x800, 23.976 fps, 2:03:07, sound 6 ch`` for the dialog."""
        parts = []
        if self.width and self.height:
            parts.append("%dx%d" % (self.width, self.height))
        if self.fps:
            parts.append("%s fps" % ("%.3f" % self.fps).rstrip("0").rstrip("."))
        if self.duration:
            parts.append(format_time(int(self.duration)))
        parts.append(("sound %d ch" % self.audio_channels if self.audio_channels else "sound")
                     if self.has_audio else "no sound")
        return ", ".join(parts)


def _fps(rate):
    try:
        if "/" in (rate or ""):
            num, den = rate.split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(rate or 0)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _from_ffprobe(path, data):
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        return None
    sound = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return FilmInfo(path=path, duration=duration, width=int(video.get("width") or 0),
                    height=int(video.get("height") or 0),
                    fps=_fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate")),
                    has_audio=sound is not None,
                    audio_channels=int((sound or {}).get("channels") or 0),
                    audio_rate=int((sound or {}).get("sample_rate") or 0))


def probe(path):
    """What the film is: its length, frame and sound. The app's ffprobe; without one, the
    banner ``ffmpeg -i`` prints (``core.video.detect_video_info``). Raises
    :class:`FilmCutError` for a file that is not a video."""
    if not path or not os.path.isfile(path):
        raise FilmCutError("There is no film at %s." % (path or "(no file chosen)"))
    ffprobe = _audio.find_ffprobe()
    if ffprobe:
        try:
            r = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json", "-show_format",
                                "-show_streams", path], capture_output=True, timeout=60,
                               stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            data = json.loads(r.stdout.decode("utf-8", "replace")) if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError, ValueError):
            data = None
        info = _from_ffprobe(path, data) if isinstance(data, dict) else None
        if info is not None:
            return info
    from ...core import video as _video
    v = _video.detect_video_info(path)
    if v is None or not v.width:
        raise FilmCutError("%s is not a video ffmpeg can read." % os.path.basename(path))
    return FilmInfo(path=path, duration=float(v.duration or 0), width=v.width, height=v.height,
                    fps=float(v.fps or 0), has_audio=bool(v.has_audio),
                    audio_channels=int(v.audio_channels or 0), audio_rate=int(v.audio_rate or 0))


# ---- times ------------------------------------------------------------------------------
def parse_time(text):
    """Seconds from ``"95"``, ``"1:35"``, ``"1:35.5"`` or ``"1:01:35"``. Raises
    :class:`FilmCutError` with a sentence for anything else."""
    s = str(text if text is not None else "").strip()
    bad = FilmCutError("%r is not a time like 1:35 or 1:01:35." % s)
    if not s:
        raise FilmCutError("Give a time like 1:35.")
    parts = s.split(":")
    if len(parts) > 3 or any(not p.strip() for p in parts):
        raise bad
    try:
        secs = float(parts[-1])
        whole = [int(p) for p in parts[:-1]]
    except ValueError:
        raise bad from None
    if secs < 0 or secs != secs or any(w < 0 for w in whole):
        raise bad
    if whole and secs >= 60:
        raise bad
    if len(whole) == 2 and whole[1] >= 60:
        raise bad
    total = secs
    for i, w in enumerate(reversed(whole)):
        total += w * 60 ** (i + 1)
    return total


def format_time(seconds):
    """``m:ss`` (``h:mm:ss`` past an hour), with milliseconds only when there are any."""
    ms = int(round(max(0.0, float(seconds)) * 1000))
    whole, frac = divmod(ms, 1000)
    h, rem = divmod(whole, 3600)
    m, sec = divmod(rem, 60)
    tail = "%02d" % sec + (("%.3f" % (frac / 1000.0))[1:].rstrip("0") if frac else "")
    return "%d:%02d:%s" % (h, m, tail) if h else "%d:%s" % (m, tail)


def span_problems(start, length, duration=None):
    """Every reason ``length`` seconds from ``start`` is not a span a mode can use, as
    sentences. Empty = fine. ``duration`` (the film's, when known) keeps it inside."""
    out = []
    try:
        start, length = float(start), float(length)
    except (TypeError, ValueError):
        return ["The start and length are numbers of seconds."]
    if start < 0:
        out.append("The start is at 0:00 or later.")
    if length <= 0:
        out.append("The length has to be more than zero.")
    elif length > MAX_SECONDS:
        out.append("A cut is at most %d seconds." % MAX_SECONDS)
    if duration:
        if start >= duration:
            out.append("The film is only %s long." % format_time(duration))
        elif start + length > duration + 0.05:
            out.append("That span runs past the end of the film (%s)." % format_time(duration))
    return out


# ---- helpers -------------------------------------------------------------------------
def _secs(x):
    return "%.3f" % float(x)


def _same_file(a, b):
    try:
        if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _check(film, start, length, out):
    if not film or not os.path.isfile(film):
        raise FilmCutError("There is no film at %s." % (film or "(no file chosen)"))
    if _same_file(film, out):
        raise FilmCutError("The cut would overwrite the film itself; a film is only ever read.")
    problems = span_problems(start, length)
    if problems:
        raise FilmCutError(" ".join(problems))


def _run(cmd, what, film):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=900, stdin=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise FilmCutError("ffmpeg could not %s %s: %s" % (what, os.path.basename(film), e)) from None
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        if "matches no streams" in err:
            kind = "sound" if "sound" in what else "picture"
            raise FilmCutError("%s has no %s to cut." % (os.path.basename(film), kind))
        raise FilmCutError("ffmpeg could not %s %s: %s" % (what, os.path.basename(film), err[-300:]))
    return r.stdout


def _ffmpeg(ffmpeg):
    ff = ffmpeg or _audio.find_ffmpeg()
    if not ff:
        raise FilmCutError("Cutting from a film needs ffmpeg, and none was found.")
    return ff


def _replace(tmp, out):
    try:
        os.replace(tmp, out)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ---- black bars burned into the film ------------------------------------------------------
#: MEASURED 2026-09-17 with this function over all 35 films of the collection: all seven
#: 1920x1080 frames carry the picture inside black bars burned into the frame (1964 and
#: 1969 1920x800 at y=140, 1965 1920x784 at y=148, 1967 1920x790 at y=148, 1974 1918x806
#: at 2,130, 1975 1920x746 at y=170, 1985 1916x1034 at 2,22); 1954 (1488x1080) has 4 px
#: side edges and 1973, 2001 and 2002 (1920x824) 4 px top edges; the other 24 (1440x1080,
#: and 1920x792 to 1920x1040) none. "Fill the frame" on a barred film would fill it with
#: the film's own bars, so the picture is found first.
BAR_POINTS = (0.1, 0.3, 0.5, 0.7, 0.9)     # where in the film to look, as fractions


def detect_picture(film, ffmpeg=None, duration=None, points=BAR_POINTS, seconds=1.0):
    """The picture inside black bars burned into ``film``, as ``(w, h, x, y)``, or None when
    the film has no bars (or they cannot be told apart). cropdetect runs for ``seconds`` at
    each point and the boxes are UNITED: bars are the same all film long, and a dark scene
    only ever makes one sample's box smaller."""
    ff = _ffmpeg(ffmpeg)
    info = probe(film)
    duration = duration or info.duration
    fw, fh = info.width, info.height
    if not (fw and fh):
        return None
    boxes = []
    for p in points:
        at = max(0.0, min(duration * p, duration - seconds)) if duration else 0.0
        try:
            r = subprocess.run([ff, "-v", "info", "-nostdin", "-ss", _secs(at), "-i", film,
                                "-map", "0:V:0", "-t", _secs(seconds), "-an", "-sn", "-dn",
                                "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"],
                               capture_output=True, timeout=120, stdin=subprocess.DEVNULL,
                               creationflags=_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            continue
        found = re.findall(rb"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
        if found:
            w, h, x, y = (int(v) for v in found[-1])
            if w > 0 and h > 0:
                boxes.append((x, y, x + w, y + h))
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    if w >= fw - 4 and h >= fh - 4:
        return None                                  # no bars
    if w < fw * 0.5 or h < fh * 0.5:
        return None                                  # too much to be bars: a dark film, not a frame
    return (w, h, x0, y0)


def _picture_crop(picture):
    if not picture:
        return ""
    w, h, x, y = picture
    return "crop=%d:%d:%d:%d," % (w, h, x, y)


# ---- the clip ---------------------------------------------------------------------------
def frame_filter(size, crop, picture=None):
    """The filter that puts a film frame into a ``size`` frame: ``letterbox`` keeps the
    whole picture and pads it; ``fill`` scales it up to cover the frame and cuts off what
    hangs over. Square pixels either way. ``picture`` (:func:`detect_picture`) cuts the
    film's own burned-in bars off first."""
    w, h = size
    if crop == "letterbox":
        vf = ("scale=%d:%d:force_original_aspect_ratio=decrease:force_divisible_by=2,"
              "pad=%d:%d:(ow-iw)/2:(oh-ih)/2" % (w, h, w, h))
    elif crop == "fill":
        vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (w, h, w, h)
    else:
        raise FilmCutError("The crop is letterbox or fill, not %r." % (crop,))
    return _picture_crop(picture) + "scale=iw*sar:ih," + vf + ",setsar=1"


def cut_clip(film, start, length, out, ffmpeg=None, size=CLIP_SIZE, crop="letterbox", picture=None):
    """``length`` seconds of ``film`` from ``start`` as a clip the bank plays, at ``out``.
    ``picture`` is the film's own picture inside burned-in bars (:func:`detect_picture`)."""
    _check(film, start, length, out)
    ff = _ffmpeg(ffmpeg)
    tmp = out + ".part"
    head, tail = MA._encode_args(ff, tmp)
    cmd = (head + ["-nostdin", "-ss", _secs(start), "-i", film, "-t", _secs(length),
                   "-map", "0:V:0", "-sn", "-dn", "-vf",
                   frame_filter(size, crop, picture) + ",fps=%d" % MA.FPS] + tail)
    try:
        _run(cmd, "cut the clip from", film)
        if not os.path.isfile(tmp) or not os.path.getsize(tmp):
            raise FilmCutError("ffmpeg made no clip from %s; is the start inside the film?"
                               % os.path.basename(film))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _replace(tmp, out)
    return out


# ---- the sound ---------------------------------------------------------------------------
@dataclass
class SoundCut:
    path: str
    channels: int
    frames: int
    gain_db: float
    limited: bool
    peak: int
    active_rms: float


def level(pcm, peak_range, crest=STOCK_CREST, ceiling=CEILING):
    """``pcm`` (float, frames x channels) gained to a stock callout's active RMS within
    ``peak_range``, soft-limited ONLY when that pushed a peak past the ceiling. The gain is
    bounded absolutely (20x), so a near-silent span is not raised into its noise.
    Returns (levelled, gain, limited)."""
    from . import engine as E
    a = np.asarray(pcm, np.float64)
    arms = E._active_rms(a, np)
    if arms <= 0:
        return a, 1.0, False
    gain = min((peak_range / crest) / arms, E._MATCH_MAX_GAIN)
    y = a * gain
    # a whole count under the ceiling: tanh of a far-over transient is exactly 1.0 in
    # floating point, and a rounded sample must still sit below the ceiling
    top = float(int(peak_range * ceiling) - 1)
    limited = float(np.abs(a).max()) * gain > top
    if limited:
        y = E._soft_limit(y, top, np)
    return y, gain, limited


def edge_fade(pcm, ms=EDGE_FADE_MS, rate=RATE):
    """A raised-cosine fade in over the first ``ms`` and out over the last, both edges
    landing exactly on zero (halved on a cut too short for two)."""
    a = np.array(pcm, np.float64, copy=True)
    n = min(len(a) // 2, int(round(ms * rate / 1000.0)))
    if n > 1:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n))
        shape = (n,) + (1,) * (a.ndim - 1)
        a[:n] *= ramp.reshape(shape)
        a[len(a) - n:] *= ramp[::-1].reshape(shape)
    return a


def cut_sound(film, start, length, out, ffmpeg=None, channels=1, peak_range=None, leveled=True):
    """``length`` seconds of the film's sound from ``start`` as a WAV at ``out``: 44.1 kHz,
    16-bit, ``channels`` (1 or 2; a 5.1 track is downmixed by ffmpeg), levelled
    (:func:`level`) and edge-faded. Returns a :class:`SoundCut`."""
    _check(film, start, length, out)
    if channels not in (1, 2):
        raise FilmCutError("A sound record is mono or stereo, not %r channels." % (channels,))
    ff = _ffmpeg(ffmpeg)
    raw = _run([ff, "-v", "error", "-nostdin", "-ss", _secs(start), "-i", film, "-t", _secs(length),
                "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", str(channels), "-ar", str(RATE),
                "-c:a", "pcm_s16le", "-f", "s16le", "-"], "cut the sound from", film)
    pcm = np.frombuffer(raw[:len(raw) // (2 * channels) * 2 * channels], "<i2")
    pcm = pcm.astype(np.float64).reshape(-1, channels)
    if not len(pcm):
        raise FilmCutError("That span of %s has no sound; is the start inside the film?"
                           % os.path.basename(film))
    rng = float(peak_range or PEAK_RANGE[channels])
    gain, limited = 1.0, False
    if leveled:
        pcm, gain, limited = level(pcm, rng)
    pcm = edge_fade(pcm)
    ints = np.clip(np.round(pcm), -32768, 32767).astype("<i2")
    tmp = out + ".part"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(ints.tobytes())
    _replace(tmp, out)
    from . import engine as E
    return SoundCut(path=out, channels=channels, frames=len(ints),
                    gain_db=float(20 * np.log10(gain)) if gain > 0 else 0.0, limited=bool(limited),
                    peak=int(np.abs(ints.astype(np.int64)).max()),
                    active_rms=E._active_rms(ints, np))


# ---- a music loop (a code mode's own music bed) ---------------------------------------------
#: A loop is a whole number of these samples at 44.1 kHz: the game declares a sound's duration in
#: 1/4000 s, so only a multiple of 441 samples (10 ms) loops exactly (mode_sounds.LOOP_STEP).
LOOP_STEP = 441
LOOP_XFADE_MS = 60.0


def cut_loop(film, start, length, out, ffmpeg=None, channels=2, leveled=True):
    """``length`` seconds of the film's SCORE from ``start`` as a seamless MUSIC LOOP at ``out``:
    44.1 kHz, 16-bit, ``channels`` (a music bed is stereo), a whole number of 10 ms steps long,
    the audio that FOLLOWS the loop's end crossfaded (equal power, 60 ms) onto its head so its end
    runs into its start with no step, and levelled like :func:`cut_sound` - but NOT edge-faded:
    a loop has no edges. The build repeats it to outlast its mode
    (``mode_sounds.loop_wav``, which keeps a loop like this one as it is). Returns a
    :class:`SoundCut`."""
    _check(film, start, length, out)
    if channels not in (1, 2):
        raise FilmCutError("A sound record is mono or stereo, not %r channels." % (channels,))
    ff = _ffmpeg(ffmpeg)
    n = int(round(float(length) * 100)) * LOOP_STEP
    xf = int(round(LOOP_XFADE_MS * RATE / 1000.0))
    if n < RATE // 2:
        raise FilmCutError("A music loop runs half a second at least.")
    raw = _run([ff, "-v", "error", "-nostdin", "-ss", _secs(start), "-i", film,
                "-t", _secs(n / float(RATE) + 0.2), "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-ac", str(channels), "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "s16le", "-"],
               "cut the music from", film)
    y = np.frombuffer(raw[:len(raw) // (2 * channels) * 2 * channels], "<i2")
    y = y.astype(np.float64).reshape(-1, channels)
    if len(y) < n + xf:
        raise FilmCutError("That span of %s is shorter than the loop; is the start inside the film?"
                           % os.path.basename(film))
    body = y[:n].copy()
    w = np.linspace(0.0, 1.0, xf)[:, None]
    body[:xf] = y[:xf] * np.sqrt(w) + y[n:n + xf] * np.sqrt(1.0 - w)
    gain, limited = 1.0, False
    if leveled:
        body, gain, limited = level(body, float(PEAK_RANGE[channels]))
    ints = np.clip(np.round(body), -32768, 32767).astype("<i2")
    tmp = out + ".part"
    with wave.open(tmp, "wb") as wv:
        wv.setnchannels(channels)
        wv.setsampwidth(2)
        wv.setframerate(RATE)
        wv.writeframes(ints.tobytes())
    _replace(tmp, out)
    from . import engine as E
    return SoundCut(path=out, channels=channels, frames=len(ints),
                    gain_db=float(20 * np.log10(gain)) if gain > 0 else 0.0, limited=bool(limited),
                    peak=int(np.abs(ints.astype(np.int64)).max()),
                    active_rms=E._active_rms(ints, np))


# ---- a still, and a preview --------------------------------------------------------------
def still_filter(width, crop, frame=CLIP_SIZE, picture=None):
    """``letterbox``: the film's whole picture; ``fill``: cut to the clip frame's shape
    (what ``fill`` keeps of it). ``width`` wide, the height a multiple of 4."""
    w, h = frame
    vf = _picture_crop(picture) + "scale=iw*sar:ih,"
    if crop == "fill":
        vf += "crop='min(iw,ih*%d/%d)':'min(ih,iw*%d/%d)'," % (w, h, h, w)
    elif crop != "letterbox":
        raise FilmCutError("The crop is letterbox or fill, not %r." % (crop,))
    return vf + "scale=%d:-4,setsar=1" % width


def _one_frame(film, at, ffmpeg, vf, fmt):
    ff = _ffmpeg(ffmpeg)
    return _run([ff, "-v", "error", "-nostdin", "-ss", _secs(at), "-i", film, "-map", "0:V:0",
                 "-frames:v", "1", "-an", "-sn", "-dn", "-vf", vf] + fmt + ["-"],
                "take a frame from", film)


def grab_still(film, at, out_png, ffmpeg=None, width=STILL_WIDTH, crop="letterbox", picture=None):
    """The frame at ``at`` seconds as the screen's PNG art at ``out_png``: ``width`` wide
    (a multiple of 4), the film's aspect kept. Returns the (width, height) written."""
    if not film or not os.path.isfile(film):
        raise FilmCutError("There is no film at %s." % (film or "(no file chosen)"))
    if _same_file(film, out_png):
        raise FilmCutError("The picture would overwrite the film itself; a film is only ever read.")
    if float(at) < 0:
        raise FilmCutError("The picture's time is 0:00 or later.")
    if width < 4 or width % 4 or width > CLIP_SIZE[0]:
        raise FilmCutError("A picture is 4 to %d pixels wide, in steps of 4." % CLIP_SIZE[0])
    from PIL import Image
    data = _one_frame(film, at, ffmpeg, still_filter(width, crop, picture=picture),
                      ["-c:v", "png", "-f", "image2pipe"])
    if not data:
        raise FilmCutError("There is no frame at %s in %s." % (format_time(at), os.path.basename(film)))
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if img.height > CLIP_SIZE[1]:
        raise FilmCutError("That picture would be taller than the display.")
    tmp = out_png + ".part"
    img.save(tmp, format="PNG")
    _replace(tmp, out_png)
    return img.size


def preview_size(box, frame=CLIP_SIZE):
    """The largest even size of the clip frame's shape inside ``box``."""
    bw, bh = box
    s = min(bw / float(frame[0]), bh / float(frame[1]))
    return max(2, int(frame[0] * s) // 2 * 2), max(2, int(frame[1] * s) // 2 * 2)


def preview_frame(film, at, ffmpeg=None, box=(480, 270), crop="letterbox", frame=CLIP_SIZE, picture=None):
    """The frame at ``at`` seconds as the clip will show it (the crop applied inside the
    clip frame), fitted in ``box``, as a PIL RGB image."""
    if not film or not os.path.isfile(film):
        raise FilmCutError("There is no film at %s." % (film or "(no file chosen)"))
    from PIL import Image
    w, h = preview_size(box, frame)
    data = _one_frame(film, at, ffmpeg, frame_filter((w, h), crop, picture),
                      ["-pix_fmt", "rgb24", "-f", "rawvideo"])
    if len(data) < w * h * 3:
        raise FilmCutError("There is no frame at %s in %s." % (format_time(at), os.path.basename(film)))
    return Image.frombytes("RGB", (w, h), data[:w * h * 3])


# ---- the command line (for scripts such as item 143's mode pack) ---------------------------
def main(argv=None):
    """``python -m pinball_decryptor.plugins.stern.film_cut FILM --out-dir DIR [--from T]
    [--length S] [--crop letterbox|fill] [--clip] [--sound] [--still [T]] [--channels N]
    [--force]``

    Cuts into ``DIR`` only, under the tab's names (``clip.mp4``, ``end.wav``, ``art.png``).
    The output folder is always named explicitly, is never the film's own folder, and an
    existing cut is replaced only with ``--force``: a film is only ever read."""
    import argparse
    ap = argparse.ArgumentParser(prog="film_cut", description="Cut a clip, a sound and a still from a film.")
    ap.add_argument("film")
    ap.add_argument("--out-dir", required=True, help="the folder the cuts go into (never the film's own)")
    ap.add_argument("--from", dest="start", default="0:00", help="start time, m:ss or h:mm:ss")
    ap.add_argument("--length", default="6", help="seconds, up to %d" % MAX_SECONDS)
    ap.add_argument("--crop", choices=CROPS, default="letterbox")
    ap.add_argument("--clip", action="store_true", help="cut clip.mp4")
    ap.add_argument("--sound", action="store_true", help="cut end.wav")
    ap.add_argument("--still", nargs="?", const="", default=None, metavar="T",
                    help="grab art.png at T (default: the start)")
    ap.add_argument("--channels", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="replace cuts already in the folder")
    args = ap.parse_args(argv)
    try:
        film = os.path.abspath(args.film)
        out_dir = os.path.abspath(args.out_dir)
        if not os.path.isfile(film):
            raise FilmCutError("There is no film at %s." % film)
        if os.path.normcase(out_dir) == os.path.normcase(os.path.dirname(film)):
            raise FilmCutError("The output folder is the film's own folder; name another one.")
        if not (args.clip or args.sound or args.still is not None):
            raise FilmCutError("Say what to cut: --clip, --sound and/or --still.")
        start, length = parse_time(args.start), parse_time(args.length)
        info = probe(film)
        problems = span_problems(start, length, info.duration) if (args.clip or args.sound) else []
        at = parse_time(args.still) if args.still else start
        if args.still is not None and info.duration and at >= info.duration:
            problems.append("The still: the film is only %s long." % format_time(info.duration))
        names = [n for n, on in (("clip.mp4", args.clip), ("end.wav", args.sound),
                                 ("art.png", args.still is not None)) if on]
        there = [n for n in names if os.path.exists(os.path.join(out_dir, n))]
        if there and not args.force:
            problems.append("%s already in %s (use --force to replace)." % (", ".join(there), out_dir))
        if problems:
            raise FilmCutError(" ".join(problems))
        os.makedirs(out_dir, exist_ok=True)
        ff = _ffmpeg(None)
        picture = detect_picture(film, ff, duration=info.duration) if (args.clip or args.still is not None) else None
        print("film: %s%s" % (info.summary(), "; picture %dx%d inside bars" % picture[:2] if picture else ""))
        if args.clip:
            cut_clip(film, start, length, os.path.join(out_dir, "clip.mp4"), ff, crop=args.crop, picture=picture)
            print("clip.mp4: %s for %g s, %s" % (format_time(start), length, args.crop))
        if args.sound:
            cut = cut_sound(film, start, length, os.path.join(out_dir, "end.wav"), ff, channels=args.channels)
            print("end.wav: %s for %g s, %d ch, gain %+.1f dB%s" % (format_time(start), length, cut.channels,
                                                               cut.gain_db, ", limited" if cut.limited else ""))
        if args.still is not None:
            size = grab_still(film, at, os.path.join(out_dir, "art.png"), ff, crop=args.crop, picture=picture)
            print("art.png: the frame at %s, %dx%d" % (format_time(at), size[0], size[1]))
    except FilmCutError as e:
        print("film_cut: %s" % e)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
