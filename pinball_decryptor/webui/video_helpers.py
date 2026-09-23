"""Replace Video: the Tk tab's logic that has no Tk in it, moved here so the
web tab (``tabs/video.py``) runs it unchanged once ``gui/`` is gone.

Every function below is a port of the ``MainWindow`` method named in its
docstring (gui/main_window.py), with the same branch order and the same
user-visible wording.  The ffmpeg / ffprobe work itself stays in
``core.video`` and ``core.video_slots``; nothing here re-decides what those
modules decide.

The one new piece is :func:`browser_proxy`: the Tk panes decoded frames
with ffmpeg and carried the sound with ffplay, so they could show any clip
ffmpeg reads.  A web page plays a ``<video>`` element, which takes only the
codecs its engine ships (Qt WebEngine on Linux has no H.264, no engine has
ProRes or a custom ``.cdmd``).  For those the page asks for a preview copy
it CAN play, made with the same ffmpeg (or, for a custom backend, from the
backend's own frame stream + sibling audio, exactly the sources the Tk pane
used).
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import threading

# ---------------------------------------------------------------------------
# Convert column values (MainWindow._VIDEO_CONV_*)
# ---------------------------------------------------------------------------
CONV_ASIS = "As-is"
CONV_REENC = "Re-encode"
CONV_REPACK = "Repackage"
CONV_REJECT = "✗ wrong format"
CONV_WRONG_TYPE = "✗ needs %s"
CONV_ASIS_NOISY = "As-is ⚠ audio"
#: Convert answers that mean "the machine will get something it can play".
CONV_GOOD = (CONV_ASIS, CONV_REENC, CONV_REPACK, CONV_ASIS_NOISY)

#: MainWindow._NOT_ON_CARD_MARK
NOT_ON_CARD_MARK = "⚠ not on this card"
#: gui/main_window.py _CHANGE_SCAN_NOTE
CHANGE_SCAN_NOTE = "  ·  still checking…"
#: MainWindow._CHANGE_FILTER_VALUES
CHANGE_FILTER_VALUES = ("All", "Changed", "Unchanged")
#: MainWindow._FOLDER_MATCH_EXTS["video"]
FOLDER_MATCH_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".ogv", ".avi", ".mkv",
                     ".mpg", ".mpeg", ".wmv", ".flv", ".ts", ".3gp", ".gif")
#: the one-slot picker's filter (MainWindow._video_assign_rel)
PICK_FILETYPES = [("Video files",
                   "*.mp4 *.mov *.m4v *.webm *.ogv *.avi *.mkv *.mpg "
                   "*.mpeg *.wmv *.flv *.ts *.3gp *.gif"),
                  ("All files", "*.*")]
#: MainWindow._video_sort_cfg: (column, header, default descending)
SORT_CFG = (("#0", "Original Video", False), ("len", "Length", True),
            ("res", "Resolution", True), ("fmt", "Format", False),
            ("aud", "Audio", False), ("rep", "Replacement", False),
            ("conv", "Convert", False))


# ---------------------------------------------------------------------------
# Playability (MainWindow._video_playability_conflict & co)
# ---------------------------------------------------------------------------
def playability_conflict(slot, path, stock_path=None):
    """MainWindow._video_playability_conflict: why the machine wouldn't play
    *path* in *slot*, or None.  Geometry / frame rate / profile are measured
    against the STOCK clip (*stock_path*, the slot's ``.orig`` snapshot)
    whenever one exists.  Best-effort: no ffprobe, or an unreadable file,
    answers None."""
    from ..core import video as _video
    name = os.path.basename(path)
    info = _video.detect_video_info(path)
    if info is None:
        return None
    codec = (info.vcodec or "").lower()
    if codec and codec != "h264":
        return ("%s is %s and the machine plays H.264"
                % (name, codec.upper()))
    pix = info.pix_fmt or ""
    if pix and pix not in _video.SAFE_PIX_FMTS:
        return ("%s is %s and the machine's decoder handles only 8-bit "
                "4:2:0" % (name, pix))
    sinfo = _video.detect_video_info(stock_path) if stock_path else None
    whose = "this slot's stock clip" if sinfo is not None \
        else "this slot's clip"
    if sinfo is None:
        sinfo = getattr(slot, "info", None)
    if sinfo is None or not sinfo.width or not sinfo.height:
        return None
    if info.width and info.height and (
            (info.width, info.height) != (sinfo.width, sinfo.height)):
        return ("%s is %dx%d and %s is %dx%d"
                % (name, info.width, info.height, whose,
                   sinfo.width, sinfo.height))
    if sinfo.fps > 0 and info.fps > 0 and abs(info.fps - sinfo.fps) > 0.5:
        return ("%s runs at %.3g fps and %s is %.3g fps"
                % (name, info.fps, whose, sinfo.fps))
    rank = _video.profile_rank(info)
    slot_rank = _video.profile_rank(sinfo)
    if rank is not None and slot_rank is not None and rank > slot_rank:
        return ("%s is H.264 %s profile and %s is %s — above "
                "what the slot proves the machine decodes"
                % (name, info.profile, whose, sinfo.profile))
    return None


def extra_audio(slot, path):
    """MainWindow._video_extra_audio: why *path*'s soundtrack is a problem
    for *slot* (a silent slot getting a noisy replacement), or None."""
    from ..core import video as _video
    sinfo = getattr(slot, "info", None)
    if sinfo is None or sinfo.has_audio:
        return None
    info = _video.detect_video_info(path)
    if info is None or not info.has_audio:
        return None
    return ("%s carries an audio track and this slot's clip has none, so "
            "the machine will play it over the game's own sound"
            % os.path.basename(path))


def slot_unplayable(mfr_key, slot):
    """MainWindow._slot_unplayable: whether the slot's CURRENT clip is a
    format the machine can't decode.  Stern only (a Spike 2 VPU fact)."""
    if mfr_key != "stern":
        return None
    info = getattr(slot, "info", None)
    if info is None:
        return None
    from ..core import video as _video
    if _video.backend_for(slot.abs_path) is not None:
        return None
    codec = (info.vcodec or "").lower()
    if codec and codec != "h264":
        return "is %s and the machine plays H.264" % codec.upper()
    pix = info.pix_fmt or ""
    if pix and pix not in _video.SAFE_PIX_FMTS:
        return ("is %s and the machine's decoder handles only 8-bit "
                "4:2:0" % pix)
    return None


def fmt_cell(mfr_key, slot):
    """MainWindow._video_fmt_cell."""
    s = slot.format_summary()
    return (s + "  ⚠") if slot_unplayable(mfr_key, slot) else s


def noconv_conflict(slot, rel, path, stock_path=None, deep=True):
    """MainWindow._video_noconv_conflict: why *path* can't be copied through
    as-is for slot *rel*, or None.  *deep* adds the ffprobe-backed half."""
    if slot is None:
        return None
    from ..core.video_slots import backend_for
    if backend_for(slot.abs_path) is not None:
        return ("%s is a custom %s format that always needs a re-encode"
                % (rel, slot.ext))
    rep_ext = os.path.splitext(path)[1].lower()
    if rep_ext != slot.ext:
        return ("%s needs a %s file, but %s is %s" % (
            rel, slot.ext, os.path.basename(path),
            rep_ext or "extension-less"))
    if not deep:
        return None
    return (playability_conflict(slot, path, stock_path)
            or extra_audio(slot, path))


def conv_mode(slot, path, no_conversion, trim, stock_path=None):
    """MainWindow._video_conv_mode: what Write will do with *path* for
    *slot* (touches no UI state, so the Convert pass calls it off-loop)."""
    from ..core.video_slots import (_already_matches, _remuxable,
                                    backend_for, find_ffmpeg)
    if slot is None or not path:
        return ""
    rep_ext = os.path.splitext(path)[1].lower()
    if no_conversion:
        if backend_for(slot.abs_path) is not None:
            return CONV_REJECT
        if rep_ext != slot.ext:
            return CONV_WRONG_TYPE % slot.ext
        if playability_conflict(slot, path, stock_path):
            return CONV_REJECT
        if extra_audio(slot, path):
            return CONV_ASIS_NOISY
        return CONV_ASIS
    if backend_for(slot.abs_path) is not None:
        return CONV_REENC
    try:
        matches = _already_matches(slot, path, rep_ext, match_length=trim)
    except Exception:                                   # noqa: BLE001
        return ""
    if matches:
        return CONV_ASIS
    if find_ffmpeg():
        try:
            repack = _remuxable(slot, path, match_length=trim)
        except Exception:                               # noqa: BLE001
            repack = False
        return CONV_REPACK if repack else CONV_REENC
    if rep_ext == slot.ext:
        return CONV_ASIS
    return ""


def conversion_note(slot, rel, path, no_conversion, trim, stock_path=None):
    """MainWindow._video_conversion_note: the pick-time log note on what
    Write will DO to *path* ("" when it can't be told)."""
    if slot is None:
        return ""
    from ..core.video_slots import (_already_matches, _remuxable,
                                    backend_for, find_ffmpeg)
    rep_ext = os.path.splitext(path)[1].lower()
    if no_conversion:
        return ("will be copied in as-is — no conversion"
                if noconv_conflict(slot, rel, path, stock_path) is None
                else "")
    if backend_for(slot.abs_path) is not None:
        return "will be converted to the game's %s format" % slot.ext
    try:
        matches = _already_matches(slot, path, rep_ext, match_length=trim)
    except Exception:                                   # noqa: BLE001
        return ""
    if matches:
        return "already matches this slot — will be copied in, no re-encode"
    if find_ffmpeg():
        try:
            repack = _remuxable(slot, path, match_length=trim)
        except Exception:                               # noqa: BLE001
            repack = False
        if repack:
            return ("already this slot's video — only its %s container "
                    "will be repackaged, no re-encode" % slot.ext)
        return "will be re-encoded to match this slot"
    if rep_ext == slot.ext:
        return "will be copied in unchanged (no ffmpeg — not re-encoded)"
    return ""


def folder_match_list(names, cap=10):
    """MainWindow._folder_match_list."""
    shown = ", ".join(names[:cap])
    if len(names) > cap:
        shown += ", and %d more" % (len(names) - cap)
    return shown


def same_dir(a, b):
    """Two folder paths name the same folder (the Tk code's normcase +
    normpath comparison)."""
    return (os.path.normcase(os.path.normpath(a or ""))
            == os.path.normcase(os.path.normpath(b or "")))


def reveal_menu_label():
    """MainWindow._reveal_menu_label."""
    if sys.platform == "darwin":
        return "Reveal in Finder"
    if sys.platform == "win32":
        return "Show in File Explorer"
    return "Show in File Manager"


def reveal_in_file_manager(path):
    """MainWindow._reveal_in_file_manager: open the OS file manager with
    *path* selected (its folder on Linux).  Returns None, or the error text
    the Tk version showed in its "Couldn't open file manager" warning."""
    if not path:
        return None
    path = os.path.abspath(path)
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        if sys.platform == "win32":
            if os.path.isfile(path):
                subprocess.Popen(
                    'explorer /select,"%s"' % os.path.normpath(path))
            else:
                os.startfile(folder)                    # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-R", path] if os.path.isfile(path)
                else ["open", folder])
        else:
            from ..core import desktop
            ok, err = desktop.open_path(folder)
            if not ok:
                raise RuntimeError(err)
    except Exception as e:                              # noqa: BLE001
        return str(e) or e.__class__.__name__
    return None


# ---------------------------------------------------------------------------
# Preview: the poster still (_VideoPreviewPane._render_representative_poster)
# ---------------------------------------------------------------------------
#: _VideoPreviewPane.POSTER_FRACTIONS
POSTER_FRACTIONS = (0.5, 0.25, 0.75, 0.08)
#: the poster/proxy box the page draws into (the Tk pane was 320x180; the
#: web pane is wider, so the still is rendered at twice that)
POSTER_W, POSTER_H = 640, 360

NOTE_ALL_BLACK = ("Every frame sampled is black — this clip may be an "
                  "overlay that only shows over the scene behind it. "
                  "Press ▶ to play it through.")
NOTE_NO_FRAME = ("Couldn't decode a frame from this clip — check that "
                 "ffmpeg is installed and that the file plays in a video "
                 "player.")
NOTE_NO_FFMPEG = ("Video preview needs ffmpeg / ffplay on your PATH.\n\n"
                  "Install ffmpeg to preview clips before staging.")

_cache_lock = threading.Lock()


def cache_dir():
    d = os.path.join(tempfile.gettempdir(), "pad-video-preview")
    os.makedirs(d, exist_ok=True)
    return d


def prune_cache(max_age_days=7):
    """Drop preview stills / copies nobody has used for a week, so the
    cache in the temp folder never grows without bound."""
    import time
    d = os.path.join(tempfile.gettempdir(), "pad-video-preview")
    if not os.path.isdir(d):
        return
    cutoff = time.time() - max_age_days * 86400
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        try:
            if os.path.isfile(p) and os.path.getatime(p) < cutoff                     and os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass


def _cache_name(path, tag, ext):
    try:
        st = os.stat(path)
        ident = "%s|%d|%d|%s" % (os.path.abspath(path), st.st_size,
                                 st.st_mtime_ns, tag)
    except OSError:
        ident = "%s|%s" % (os.path.abspath(path), tag)
    digest = hashlib.sha1(ident.encode("utf-8", "replace")).hexdigest()[:20]
    return os.path.join(cache_dir(), digest + ext)


def disp_size(info, max_w=POSTER_W, max_h=POSTER_H):
    """_VideoPreviewPane._compute_disp_size: aspect-fit, even-numbered."""
    if info and info.width > 0 and info.height > 0:
        w, h = info.width, info.height
    else:
        w, h = 16, 9
    scale = min(max_w / w, max_h / h)
    dw = max(16, int(w * scale))
    dh = max(16, int(h * scale))
    return dw - (dw % 2), dh - (dh % 2)


def poster_spots(dur):
    """The positions _render_representative_poster tries, in order."""
    if dur > 0.2:
        spots = [dur * f for f in POSTER_FRACTIONS]
    elif dur > 0:
        spots = [0.0]
    else:
        spots = [0.5]
    if spots[-1] > 0:
        spots.append(0.0)
    return spots


def _is_black(png):
    """True when the PNG is solid black (PIL's getbbox() is None); False
    when it has content or Pillow is missing (nothing to judge with)."""
    try:
        import io

        from PIL import Image
        return Image.open(io.BytesIO(png)).convert("RGB").getbbox() is None
    except Exception:                                   # noqa: BLE001
        return False


def representative_poster(path, info=None, dur=0.0):
    """Render the representative still for *path*: mid-clip first, then the
    other POSTER_FRACTIONS while the frame comes back black, frame 0 last.
    Returns ``(png_path or None, note)`` where *note* is what the Tk pane
    drew on the canvas when no still could be shown ("" when one was)."""
    from ..core import video as _video
    w, h = disp_size(info)
    all_black = False
    for pos in poster_spots(dur):
        png = _video.extract_frame_png(path, pos, w, h)
        if not png:
            continue
        if _is_black(png):
            all_black = True
            continue
        out = _cache_name(path, "poster%dx%d@%.3f" % (w, h, pos), ".png")
        try:
            with _cache_lock:
                if not os.path.isfile(out):
                    tmp = out + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(png)
                    os.replace(tmp, out)
        except OSError:
            return None, NOTE_NO_FRAME
        return out, ""
    if all_black:
        return None, NOTE_ALL_BLACK
    if _video.backend_for(path) is None and not _video.find_ffmpeg():
        return None, NOTE_NO_FFMPEG
    return None, NOTE_NO_FRAME


# ---------------------------------------------------------------------------
# Preview: a copy the page's <video> element can play
# ---------------------------------------------------------------------------
_proxy_locks = {}


def _proxy_lock(key):
    with _cache_lock:
        lk = _proxy_locks.get(key)
        if lk is None:
            lk = _proxy_locks[key] = threading.Lock()
        return lk


def browser_proxy(path, fmt="mp4"):
    """A preview copy of *path* the page's ``<video>`` can play: H.264/AAC
    MP4 (``fmt="mp4"``: Edge WebView2, WKWebView) or VP8/Vorbis WebM
    (``fmt="webm"``: Qt WebEngine, which ships no H.264).  Scaled down to
    the pane size; cached by path, size and mtime.

    ffmpeg-readable clips are converted by ffmpeg; a custom-backend clip
    (``.cdmd``) is rebuilt from the backend's own frame stream plus its
    sibling audio (``core.video.open_raw_stream`` / ``audio_source_for``,
    the sources the Tk pane played from).  Returns the proxy path, or
    raises RuntimeError with the reason."""
    from ..core import video as _video
    fmt = "webm" if fmt == "webm" else "mp4"
    out = _cache_name(path, "proxy-" + fmt, "." + fmt)
    with _proxy_lock(out):
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            return out
        ffmpeg = _video.find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError(NOTE_NO_FFMPEG)
        info = _video.detect_video_info(path)
        w, h = disp_size(info)
        tmp = out + ".part." + fmt
        if fmt == "webm":
            vargs = ["-c:v", "libvpx", "-deadline", "realtime",
                     "-cpu-used", "8", "-b:v", "1500k", "-pix_fmt", "yuv420p"]
            aargs = ["-c:a", "libvorbis", "-q:a", "4"]
            tail = ["-f", "webm"]
        else:
            vargs = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                     "-pix_fmt", "yuv420p", "-profile:v", "main"]
            aargs = ["-c:a", "aac", "-b:a", "160k"]
            tail = ["-movflags", "+faststart", "-f", "mp4"]
        creation = getattr(_video, "_CREATE_FLAGS", 0)
        backend = _video.backend_for(path)
        try:
            if backend is None:
                cmd = [ffmpeg, "-y", "-v", "error", "-i", path,
                       "-vf", "scale=%d:%d:force_original_aspect_ratio="
                              "decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2"
                       % (w, h)] + vargs + aargs + tail + [tmp]
                r = subprocess.run(cmd, capture_output=True, timeout=900,
                                   creationflags=creation)
                if r.returncode != 0:
                    raise RuntimeError(
                        (r.stderr or b"")[-400:].decode("utf-8", "replace")
                        .strip() or "ffmpeg failed")
            else:
                _backend_proxy(ffmpeg, path, info, w, h, vargs, aargs, tail,
                               tmp, creation)
            os.replace(tmp, out)
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg took too long")
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        return out


def _backend_proxy(ffmpeg, path, info, w, h, vargs, aargs, tail, out,
                   creation):
    """Encode a custom-backend clip from its rgb24 frame stream, muxing in
    its sibling audio track when it has one."""
    from ..core import video as _video
    fps = (info.fps if info and info.fps > 0 else 30.0)
    stream = _video.open_raw_stream(path, w, h, fps, start=0.0)
    if stream is None:
        raise RuntimeError(NOTE_NO_FRAME)
    audio = _video.audio_source_for(path)
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
           "-framerate", "%.6f" % fps, "-i", "-"]
    if audio:
        cmd += ["-i", audio]
    cmd += vargs + (aargs + ["-shortest"] if audio else ["-an"]) + tail
    cmd.append(out)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=creation)
    frame = w * h * 3
    try:
        while True:
            data = stream.stdout.read(frame)
            if not data or len(data) < frame:
                break
            proc.stdin.write(data)
        proc.stdin.close()
        proc.wait(timeout=900)
    finally:
        try:
            stream.terminate()
        except Exception:                               # noqa: BLE001
            pass
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed (exit %s)" % proc.returncode)


def media_facts(path):
    """What the page needs to decide whether its engine plays *path*
    directly: container, codec, pixel format, audio, custom backend.  Plus
    the duration / size the pane's clock and poster use."""
    from ..core import video as _video
    info = _video.detect_video_info(path) if path else None
    dur = (info.duration if info and info.duration > 0
           else (_video.probe_video_duration(path) if path else 0.0))
    return info, {
        "ext": os.path.splitext(path or "")[1].lower().lstrip("."),
        "codec": (info.vcodec or "").lower() if info else "",
        "pix_fmt": (info.pix_fmt or "") if info else "",
        "alpha": bool(info and info.has_alpha),
        "has_audio": bool(info and info.has_audio),
        "backend": _video.backend_for(path) is not None if path else False,
        "width": info.width if info else 0,
        "height": info.height if info else 0,
        "dur": float(dur or 0.0),
    }
