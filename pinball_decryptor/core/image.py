"""Image processing for replacement assets — probing, format-matched scaling,
thumbnails for the embedded preview, and byte-budget recompression.

The Replace-Image GUI tab lets users swap a game's loose image files.  A
replacement of (almost) any format is matched to the slot it replaces — scaled
to the slot's pixel dimensions and saved in the slot's container — then written
over the original so the normal Write pipeline repacks it.  This is the Pillow
layer beneath that (the image analogue of :mod:`core.video`'s ffmpeg layer):

  - Metadata detection (format / WxH / mode / alpha)
  - A thumbnail for the in-tab preview pane
  - Scaling an arbitrary input into the slot's format + resolution
  - Recompressing to fit a byte budget (for size-neutral in-place patching,
    e.g. Stern Spike 2)

Pillow is optional; every entry point degrades gracefully (returns None / a
clear ``(False, msg)``) when it's missing, so importing this module never
requires it.
"""

import io
import os

try:
    from PIL import Image
    _PIL_OK = True
except Exception:                       # pragma: no cover - Pillow optional
    Image = None
    _PIL_OK = False

# Image containers we treat as replaceable slots.
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp")

# Replacement inputs the user may drop in (Pillow reads more than we list as
# slots; this is just the picker's file filter).
REPLACEMENT_EXTS = IMAGE_EXTS + (".tiff", ".tif", ".ico")

# Pillow save format per output extension.
_EXT_FORMAT = {
    ".png": "PNG", ".bmp": "BMP", ".gif": "GIF", ".tga": "TGA",
    ".webp": "WEBP", ".jpg": "JPEG", ".jpeg": "JPEG",
}


def pil_available():
    """True when Pillow is importable (the Replace-Image tab needs it)."""
    return _PIL_OK


class ImageInfo:
    """Metadata for an image file (from Pillow)."""

    def __init__(self, path, fmt="", width=0, height=0, mode="",
                 has_alpha=False):
        self.path = path
        self.fmt = fmt              # "PNG", "JPEG", …
        self.width = width
        self.height = height
        self.mode = mode            # "RGBA", "RGB", "P", …
        self.has_alpha = has_alpha

    def __repr__(self):
        return (f"ImageInfo({self.fmt}, {self.width}x{self.height}, "
                f"{self.mode}{', alpha' if self.has_alpha else ''})")


def _has_alpha(im):
    return im.mode in ("RGBA", "LA", "PA") or (
        im.mode == "P" and "transparency" in im.info)


def detect_image_info(path):
    """Detect image metadata via Pillow, or ``None`` when unavailable / not an
    image Pillow understands (the slot still lists, just without dimensions)."""
    if not _PIL_OK or not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as im:
            return ImageInfo(path, im.format or "", im.width, im.height,
                             im.mode, _has_alpha(im))
    except Exception:
        return None


# The image editors' transparency checkerboard: both black and white art
# reads against it in either app theme (a black font glyph on the dark theme
# was invisible — the preview canvas matched the glyph).
_CHECKER_LIGHT = (204, 204, 204, 255)
_CHECKER_DARK = (153, 153, 153, 255)
_CHECKER_SQ = 8


def _checkerboard(size):
    """An RGBA checkerboard of *size*, drawn only behind the image itself so
    its true bounds stay visible against the canvas."""
    w, h = size
    bg = Image.new("RGBA", size, _CHECKER_LIGHT)
    dark = Image.new("RGBA", (_CHECKER_SQ, _CHECKER_SQ), _CHECKER_DARK)
    for y in range(0, h, _CHECKER_SQ):
        for x in range(0, w, _CHECKER_SQ):
            if (x // _CHECKER_SQ + y // _CHECKER_SQ) % 2:
                bg.paste(dark, (x, y))
    return bg


def thumbnail_png(path, max_w, max_h):
    """Return PNG bytes of *path* scaled to fit ``max_w`` x ``max_h`` (aspect
    preserved), for the tab's preview pane, or ``None`` on failure.

    An image smaller than the pane (font glyph slices are usually a few dozen
    pixels) is upscaled by a whole-number factor with nearest-neighbour so it
    stays crisp and inspectable; anything with transparency is composited
    over the standard checkerboard."""
    if not _PIL_OK or not path or not os.path.isfile(path):
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            max_w = max(1, int(max_w))
            max_h = max(1, int(max_h))
            if im.width > max_w or im.height > max_h:
                im.thumbnail((max_w, max_h))
            else:
                k = min(max_w // im.width, max_h // im.height)
                if k >= 2:
                    im = im.resize((im.width * k, im.height * k),
                                   Image.NEAREST)
            if im.getchannel("A").getextrema()[0] < 255:
                bg = _checkerboard(im.size)
                bg.alpha_composite(im)
                im = bg
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except Exception:
        return None


def _format_for(ext):
    return _EXT_FORMAT.get(ext.lower())


def _prep_mode(im, fmt, alpha):
    """Return *im* in a mode the target *fmt* can save (JPEG has no alpha)."""
    if fmt == "JPEG":
        return im.convert("RGB")
    if alpha:
        return im.convert("RGBA") if im.mode != "RGBA" else im
    # Keep palette images as-is for PNG/GIF/BMP; otherwise normalise to RGB(A).
    if im.mode in ("RGBA", "RGB", "P", "L"):
        return im
    return im.convert("RGBA" if _has_alpha(im) else "RGB")


def transcode_image_to(src_path, dst_path, original_info):
    """Scale *src_path* to *original_info*'s pixel dimensions and save it into
    *dst_path*, whose extension selects the output format.  Preserves alpha
    where the target format supports it.  Returns ``(ok, detail)``."""
    if not _PIL_OK:
        return False, "need Pillow to convert images"
    ext = os.path.splitext(dst_path)[1].lower()
    fmt = _format_for(ext)
    if fmt is None:
        return False, f"unsupported target format {ext}"
    try:
        with Image.open(src_path) as im:
            im.load()
            actions = []
            alpha = bool(original_info and original_info.has_alpha)
            if (original_info and original_info.width > 0
                    and original_info.height > 0
                    and (im.width != original_info.width
                         or im.height != original_info.height)):
                im = im.resize((original_info.width, original_info.height),
                               Image.LANCZOS)
                actions.append(f"→{original_info.width}x{original_info.height}")
            im = _prep_mode(im, fmt, alpha)
            save_kw = {}
            if fmt == "PNG":
                save_kw = {"optimize": True}
            elif fmt == "JPEG":
                save_kw = {"quality": 92}
            im.save(dst_path, fmt, **save_kw)
        return True, ", ".join(actions)
    except (OSError, ValueError) as e:
        return False, str(e)


def recompress_image_to_size(src_path, dst_path, max_bytes,
                             original_info=None):
    """Save *src_path* into *dst_path* (same format / dimensions) at no more
    than *max_bytes*.

    Used for size-neutral in-place patching (Stern Spike 2): the new image must
    fit the original file's byte slot.  PNG is squeezed via max compression then
    palette quantization (fewer colours); JPEG via lower quality.  Returns
    ``(ok, detail)`` — *detail* is the final byte size on success, else an error.
    The caller pads the (``<= max_bytes``) result up to the exact slot size.
    """
    if not _PIL_OK:
        return False, "need Pillow to shrink images"
    if max_bytes <= 0:
        return False, "no byte budget"
    ext = os.path.splitext(dst_path)[1].lower()
    fmt = _format_for(ext)
    if fmt is None:
        return False, f"unsupported target format {ext}"
    try:
        with Image.open(src_path) as im:
            im.load()
            alpha = bool(original_info and original_info.has_alpha) or _has_alpha(im)

            def _write(image, **kw):
                buf = io.BytesIO()
                image.save(buf, fmt, **kw)
                data = buf.getvalue()
                return data

            attempts = []
            if fmt == "JPEG":
                base = im.convert("RGB")
                for q in (92, 85, 75, 60, 45, 30):
                    attempts.append(lambda q=q: _write(base, quality=q,
                                                       optimize=True))
            elif fmt == "PNG":
                base = im if im.mode in ("RGBA", "RGB", "P", "L") else \
                    im.convert("RGBA" if alpha else "RGB")
                attempts.append(lambda: _write(base, optimize=True,
                                               compress_level=9))
                for colors in (256, 128, 64, 32, 16):
                    attempts.append(
                        lambda c=colors: _write(
                            base.convert("RGBA" if alpha else "RGB").quantize(
                                colors=c,
                                method=getattr(Image, "FASTOCTREE", 2)),
                            optimize=True, compress_level=9))
            else:
                attempts.append(lambda: _write(im, optimize=True))

            best = None
            for make in attempts:
                try:
                    data = make()
                except Exception:
                    continue
                if 0 < len(data) <= max_bytes:
                    with open(dst_path, "wb") as f:
                        f.write(data)
                    return True, str(len(data))
                if best is None or len(data) < best:
                    best = len(data)
        return False, (f"smallest re-encode was {best} > {max_bytes} bytes"
                       if best else "could not re-encode to fit")
    except (OSError, ValueError) as e:
        return False, str(e)
