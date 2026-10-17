"""Pictures and clips saved as files of their own with their color profile
baked in (PAD-604, DragonRR: "bake in a file color profile to a video or set
of videos and then save that video, or that set of videos as individual
files ... the same also applies to images").

Each file gets exactly what a build bakes into it: the same
:class:`core.colour_profile.Profile` maths (Pillow for a picture, the
profile's ffmpeg filters for a clip), so a saved copy matches the card.
Nothing in the project is touched; the copies go to a folder of the user's.
"""
import os

#: picture formats kept as they are; anything else is saved as a PNG
IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
                 ".bmp": "BMP", ".webp": "WEBP", ".tif": "TIFF",
                 ".tiff": "TIFF"}


def image_ext(src):
    """The extension a saved copy of picture *src* gets: its own where it
    can be written back as it was, else ``.png``."""
    ext = os.path.splitext(src)[1].lower()
    return ext if ext in IMAGE_FORMATS else ".png"


def video_ext(src):
    """The extension a saved copy of clip *src* gets: its own where ffmpeg
    can encode that container, else ``.mp4``."""
    from . import video
    ext = os.path.splitext(src)[1].lower()
    return ext if video.encoder_codec(ext) is not None else ".mp4"


def out_ext(kind, src):
    return image_ext(src) if kind == "images" else video_ext(src)


def plan_names(kind, sources, folder, replace=False):
    """``[dst path, ...]`` for *sources* saved into *folder*, in order: each
    under its own file name, a second file of the same name numbered
    ("name (2).png").  A file already in *folder* is written over with
    *replace*, else the copy is numbered too.  A source itself is never a
    destination (picking the folder a replacement lives in leaves it be)."""
    taken = set()
    out = []
    srcs = {os.path.normcase(os.path.abspath(s)) for s in sources}
    for src in sources:
        stem = os.path.splitext(os.path.basename(src))[0] or "file"
        ext = out_ext(kind, src)
        n = 1
        while True:
            name = stem + ext if n == 1 else "%s (%d)%s" % (stem, n, ext)
            path = os.path.join(folder, name)
            key = os.path.normcase(os.path.abspath(path))
            busy = (key in taken or key in srcs
                    or (not replace and os.path.exists(path)))
            if not busy:
                break
            n += 1
        taken.add(key)
        out.append(path)
    return out


def existing(kind, sources, folder):
    """How many of *sources* would land on a file already in *folder*."""
    srcs = {os.path.normcase(os.path.abspath(s)) for s in sources}
    names = {os.path.splitext(os.path.basename(s))[0] + out_ext(kind, s)
             for s in sources}
    return sum(1 for n in names
               if os.path.exists(os.path.join(folder, n))
               and os.path.normcase(os.path.abspath(os.path.join(folder, n)))
               not in srcs)


def _part_path(dst):
    """Where a copy is written before it takes its name: a cancelled or
    failed save never leaves half a file under the real one."""
    folder, name = os.path.split(dst)
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, "~%s.saving%s" % (stem, ext))


def save_image(src, dst, prof):
    """Picture *src* with *prof* baked in, written to *dst* (its format by
    the extension; transparency kept where the format has it)."""
    from PIL import Image
    with Image.open(src) as im:
        im.load()
        out = prof.apply_image(im) if prof is not None else im.copy()
    fmt = IMAGE_FORMATS.get(os.path.splitext(dst)[1].lower(), "PNG")
    tmp = _part_path(dst)
    try:
        if fmt == "JPEG":
            out.convert("RGB").save(tmp, fmt, quality=95)
        elif fmt == "BMP" and out.mode not in ("RGB", "L", "P", "1"):
            out.convert("RGB").save(tmp, fmt)
        else:
            out.save(tmp, fmt)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save_video(src, dst, prof, cancel_cb=None):
    """Clip *src* with *prof* baked into every frame, written to *dst*: the
    same size, frame rate and sound as *src*, at the Best quality encode
    (the clip is decoded and encoded again, so not a byte-for-byte copy).
    Returns ``(ok, error)``."""
    from . import video
    if video.backend_for(src) is not None:
        return False, "this kind of clip can only be read, not saved"
    info = video.detect_video_info(src)
    if info is None or not (info.width > 0 and info.height > 0):
        return False, "ffprobe could not read this clip"
    tmp = _part_path(dst)
    try:
        ok, actions = video.transcode_video_to(
            src, tmp, info, best_quality=True, colour=prof,
            cancel_cb=cancel_cb)
        if not ok:
            return False, actions
        os.replace(tmp, dst)
        return True, ""
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save_all(kind, items, log_cb=None, progress_cb=None, cancel_cb=None):
    """Save every ``(rel, src, dst, prof)`` in *items* (*kind* "images" or
    "videos"), one after another.  *progress_cb(done, total, rel)* before
    each; *cancel_cb()* truthy stops before the next (and a clip's encode
    at once).  Returns ``{"saved": [(rel, dst)], "failed": [(rel, why)],
    "cancelled": bool}``."""
    saved, failed = [], []
    total = len(items)
    for i, (rel, src, dst, prof) in enumerate(items):
        if cancel_cb is not None and cancel_cb():
            return {"saved": saved, "failed": failed, "cancelled": True}
        if progress_cb is not None:
            progress_cb(i, total, rel)
        try:
            if kind == "images":
                save_image(src, dst, prof)
                ok, why = True, ""
            else:
                ok, why = save_video(src, dst, prof, cancel_cb)
        except Exception as e:                          # noqa: BLE001
            ok, why = False, str(e) or e.__class__.__name__
        if ok:
            saved.append((rel, dst))
            if log_cb is not None:
                log_cb("Saved %s with %s → %s" % (
                    rel, ("its color profile (%s)" % prof.label()
                          if prof is not None else "its own colors"),
                    os.path.normpath(dst)), "info")
        elif cancel_cb is not None and cancel_cb():
            return {"saved": saved, "failed": failed, "cancelled": True}
        else:
            failed.append((rel, why))
            if log_cb is not None:
                log_cb("Could not save %s: %s" % (rel, why), "warn")
    if progress_cb is not None:
        progress_cb(total, total, "")
    return {"saved": saved, "failed": failed, "cancelled": False}
