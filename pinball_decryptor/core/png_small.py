"""The smallest lossless PNG of a picture (PAD-1547).

Sonic-era Jersey Jack games hold every asset at its original byte length: a
replacement PNG may be padded up to it (``plugins.jjp.pipeline.fit_png_to_size``)
but never cut down.  Their small LED art was packed by a stronger optimiser than
Pillow's own ``optimize=True``: re-saving the 6,403 untouched Sonic 0.926
``graphics/Mini LED`` pictures with Pillow came out bigger than the original for
128 of them, so a picture edited in the pixel editor could not go back into the
slot it came from.  Trying every PNG row filter with several zlib strategies
(what optimisers like OptiPNG do) brings that down to 3, all large sprite sheets.

Every candidate is lossless: the pixels decode to exactly the picture given.
The only liberty taken is the colour stored under a fully transparent pixel,
which nothing can see, set to black (PNG compresses runs of it far better).
"""

import io
import struct
import zlib

#: Pictures with more pixels than this skip the filter search (pure Python,
#: about a second per 200 x 200 picture) and take Pillow's result.
SEARCH_MAX_PIXELS = 512 * 512

_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _filter_row(row, prev, bpp, kind):
    if kind == 0:
        return bytes(row)
    out = bytearray(len(row))
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        if kind == 1:
            pred = a
        elif kind == 2:
            pred = b
        elif kind == 3:
            pred = (a + b) >> 1
        else:
            pred = _paeth(a, b, prev[i - bpp] if i >= bpp else 0)
        out[i] = (x - pred) & 0xFF
    return bytes(out)


def _filtered(raw, w, h, bpp):
    """``{filter: scanline bytes}`` for the five fixed filters and the
    per-row "minimum sum of absolute differences" pick."""
    stride = w * bpp
    rows = {k: bytearray() for k in (0, 1, 2, 3, 4, "adaptive")}
    prev = bytes(stride)
    for y in range(h):
        row = raw[y * stride:(y + 1) * stride]
        each = [_filter_row(row, prev, bpp, k) for k in range(5)]
        for k in range(5):
            rows[k].append(k)
            rows[k] += each[k]
        best = min(range(5), key=lambda k: sum(v if v < 128 else 256 - v for v in each[k]))
        rows["adaptive"].append(best)
        rows["adaptive"] += each[best]
        prev = row
    return rows


def _searched(im):
    """The smallest PNG of the filter x zlib-strategy search, as bytes."""
    mode = im.mode
    colour_type, bpp = {"RGBA": (6, 4), "RGB": (2, 3)}[mode]
    w, h = im.size
    best = None
    for data in _filtered(im.tobytes(), w, h, bpp).values():
        data = bytes(data)
        for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_RLE):
            for mem in (8, 9):
                c = zlib.compressobj(9, zlib.DEFLATED, 15, mem, strategy)
                z = c.compress(data) + c.flush()
                if best is None or len(z) < len(best):
                    best = z
    return (_SIG + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, colour_type, 0, 0, 0))
            + _chunk(b"IDAT", best) + _chunk(b"IEND", b""))


def _pillow(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def prepared(im):
    """*im* as the RGB or RGBA picture the encoders take: RGB when every pixel
    is opaque (a quarter fewer bytes to compress), and black under fully
    transparent pixels."""
    im = im.convert("RGBA")
    alpha = im.getchannel("A")
    lo, hi = alpha.getextrema()
    if lo == 255:
        return im.convert("RGB")
    if lo == 0:
        from PIL import Image
        black = Image.new("RGBA", im.size, (0, 0, 0, 0))
        clear = alpha.point(lambda a: 255 if a == 0 else 0)
        im.paste(black, (0, 0), clear)
    return im


def smallest_png(im, budget=None):
    """The smallest lossless PNG of PIL picture *im*, as bytes.

    With *budget*, the filter search is skipped once Pillow's own result is
    already within it (the common case, and the cheap one).
    """
    im = prepared(im)
    best = _pillow(im)
    if budget is not None and len(best) <= budget:
        return best
    if im.size[0] * im.size[1] <= SEARCH_MAX_PIXELS:
        searched = _searched(im)
        if len(searched) < len(best):
            best = searched
    return best
