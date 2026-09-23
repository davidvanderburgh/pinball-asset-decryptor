"""Media files the Replace Audio tab hands the page through ``/media``.

The Tk tab drew its spectrogram strip from PNG bytes in memory and played
through ffplay.  The page shows pictures and plays sound from URLs, so this
keeps both as files in one temporary folder for the session:

* :func:`spectrogram_file` - the strip ``core.audio.render_spectrogram_png``
  draws, written once per (file, size, loudness offset);
* :func:`playable_copy` - a plain 16-bit WAV of a file the page's player
  cannot decode (WMA, AIFF...), made with the same ffmpeg the app converts
  replacements with.

Nothing here writes outside that folder; :func:`cleanup` removes it when
the window closes.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading

_lock = threading.Lock()
_dir = None


def cache_dir():
    """The session's scratch folder (created on first use)."""
    global _dir
    with _lock:
        if _dir is None or not os.path.isdir(_dir):
            _dir = tempfile.mkdtemp(prefix="pad-audio-")
        return _dir


def _key(path, *extra):
    try:
        st = os.stat(path)
        sig = "%s|%d|%d" % (os.path.normcase(os.path.abspath(path)),
                            st.st_size, st.st_mtime_ns)
    except OSError:
        sig = str(path)
    text = "|".join([sig] + [str(e) for e in extra])
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:24]


def spectrogram_file(path, width=800, height=90, gain_db=0.0):
    """Path of a PNG spectrogram of *path* (rendered by
    ``core.audio.render_spectrogram_png``), or ``None`` when ffmpeg is
    missing or the render failed."""
    from ..core import audio
    gain = round(float(gain_db or 0.0), 2)
    out = os.path.join(cache_dir(), "spec-%s.png"
                       % _key(path, int(width), int(height), gain))
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    png = audio.render_spectrogram_png(path, width, height, gain_db=gain)
    if not png:
        return None
    tmp = out + ".%d.tmp" % threading.get_ident()
    try:
        with open(tmp, "wb") as f:
            f.write(png)
        os.replace(tmp, out)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
    return out


def playable_copy(path):
    """A 16-bit PCM WAV copy of *path* for a player that cannot decode the
    original, or ``None`` (no ffmpeg, or ffmpeg could not read it)."""
    from ..core import audio
    if not path or not os.path.isfile(path):
        return None
    ffmpeg = audio.find_ffmpeg()
    if not ffmpeg:
        return None
    out = os.path.join(cache_dir(), "play-%s.wav" % _key(path))
    if os.path.isfile(out) and os.path.getsize(out) > 44:
        return out
    tmp = out + ".%d.tmp.wav" % threading.get_ident()
    cmd = [ffmpeg, "-v", "error", "-y", "-i", path, "-vn",
           "-acodec", "pcm_s16le", tmp]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300,
                           creationflags=getattr(audio, "_CREATE_FLAGS", 0))
        if r.returncode != 0 or not os.path.isfile(tmp):
            return None
        os.replace(tmp, out)
        return out
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def cleanup():
    """Remove the session's scratch folder."""
    global _dir
    with _lock:
        d, _dir = _dir, None
    if d:
        shutil.rmtree(d, ignore_errors=True)
