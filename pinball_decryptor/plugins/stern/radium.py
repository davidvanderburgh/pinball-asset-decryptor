"""Editable display-text strings inside Stern Spike 2 ``.radium`` scene files.

Spike 2 stores its LCD on-screen UI text inside ``*.radium`` scene files on the
card's ext4 data partition.  A radium scene is a flat stream of nodes; strings
are stored **length-prefixed** with an 8-byte little-endian length followed by
the raw (latin1/ascii) bytes.  Strings come in several roles:

  * element-type names    -- ``Text`` ``Sprite`` ``Font`` ``Bitmap`` ``Pattern``
  * instance / object ids  -- ``credits_text`` ``Line_Anchovies`` ``player1``
  * font names             -- ``HelveticaNeueBlack`` ``Stern_Impact`` ``*_Glyphs``
  * asset references        -- ``2.asset/0.asset``
  * **display text**       -- ``Credits 50`` ``SEEK AND DESTROY`` ``Player 1``
                              (what the player sees -- the editable strings)

Discriminator (validated on TMNT + Metallica + Godzilla cards):

  - A *named handle* string (element-type / instance-id / asset-ref) is framed
    by a 4-byte node handle whose top byte is ``0x80`` either immediately
    *before* the length prefix (``xx xx xx 80``) or immediately *after* the
    body.  These are NOT display text.

  - A *display-text* string is a Variant value: the bytes immediately before its
    length prefix are float32 anchor/offset coordinates and the 4 bytes right
    before the length are NOT a ``0x80`` handle.  Font names and a few
    content-name strings are split out by name hints / identifier shape.

``enumerate_strings`` returns every length-prefixed ascii string with its exact
byte offset + length, tagged by :func:`classify`.  Only ``display-text`` entries
are user-editable.  A replacement must be **<= the original byte length** and is
**space-padded to the original length**, so the file size and every other offset
stay byte-identical -- the same size-neutral in-place patch the image / video
Replace paths use.  The same display string is stored many times in a radium
(once in the ``Text`` element, then once per keyframe of the parent ``Sprite``
timeline -- e.g. "Shoot Left Ramp" can appear 121x), so callers must overwrite
**every** occurrence whose value matches the original.

Ported verbatim (logic-identical) from the format reverse-engineering prototype
``radium_text.py``; see the Spike 2 assets memory notes for the wider context.
"""

import struct

MAXLEN = 8192          # ignore absurd "lengths" (false 8-byte hits)
_FONT_HINT = ("Glyphs", "Impact", "Vera", "Helvetica", "Neue", "Arial",
              "_Regular", "Bitstream")
_ELEM_TYPES = {"Text", "Sprite", "Font", "Bitmap", "Pattern", "VideoSurface",
               "Video", "Group", "Node", "Scene", "Mask", "Particle"}


def find_strings(data):
    """Yield ``(prefix_off, body_off, length, body_bytes)`` for every 8-byte-LE
    length-prefixed printable-ascii string.  ``prefix_off`` points at the length
    field; ``body_off = prefix_off + 8`` points at the first text byte."""
    n = len(data)
    out = []
    i = 0
    while i + 8 <= n:
        ln = struct.unpack_from("<Q", data, i)[0]
        if 1 <= ln <= MAXLEN and i + 8 + ln <= n:
            body = data[i + 8:i + 8 + ln]
            if all(32 <= b < 127 or b in (9, 10, 13) for b in body):
                out.append((i, i + 8, ln, body))
                i += 8 + ln
                continue
        i += 1
    return out


def _handle_before(data, pre_off):
    """The 4 bytes immediately before the length prefix form a node handle
    (top byte 0x80): the string is a NAMED handle (instance/property id)."""
    return pre_off >= 4 and data[pre_off - 1] == 0x80


def _handle_after(data, body_off, ln):
    """The 4 bytes immediately after the body form a node handle (top byte
    0x80): the string is a key/identifier that *introduces* a node."""
    a = data[body_off + ln:body_off + ln + 4]
    return len(a) == 4 and a[3] == 0x80


def _has_letter(s):
    return any(c.isalpha() for c in s)


def _is_identifier_like(s):
    """A space-less token that is an internal identifier / object name / key
    rather than player-facing display text:

      * snake_case / SCREAMING_CASE with underscores  (ATTRACT_LOOP1)
      * dotted path / key                              (video.in_attract_videos)
      * CamelCase concatenation -- an internal lower->Upper transition

    Single dictionary words (all-caps JACKPOT, or Title-case Replay / Pro) and
    numbers are NOT identifier-like -> they stay display-text.
    """
    if "_" in s or "." in s:
        return True
    # CamelCase: an internal lowercase-then-uppercase boundary
    for a, b in zip(s, s[1:]):
        if a.islower() and b.isupper():
            return True
    return False


def classify(data, pre_off, body):
    """Return one of: ``'display-text'``, ``'asset-ref'``, ``'font'``,
    ``'element'``, ``'name'``, ``'value'`` for the string ``body`` whose length
    prefix begins at ``pre_off`` in ``data``.

    The radium serializer frames named handles (element types, instance ids,
    map keys, asset refs) with a 4-byte handle whose top byte is ``0x80`` either
    immediately before the length prefix (a stored handle reference) or
    immediately after the body (a key that introduces the next node).  A
    *Variant string value* -- the editable display text -- has neither.
    """
    s = body.decode("latin1")
    body_off = pre_off + 8
    ln = len(body)

    if ".asset" in s:
        return "asset-ref"
    if s in _ELEM_TYPES:
        return "element"

    handle_b = _handle_before(data, pre_off)
    handle_a = _handle_after(data, body_off, ln)

    # named handle: a stored reference or a key that introduces a node
    if handle_b or handle_a:
        return "name"

    # not handle-framed -> a Variant value.  Split fonts / asset-like / text.
    if any(h in s for h in _FONT_HINT):
        return "font"

    # editable display text: a value string with letters, length >= 2, that is
    # not a bare snake_case identifier-with-no-spaces (those are object names
    # stored as values in a few config scenes).
    has_space = any(c in s for c in " \n\t")

    if _has_letter(s) and ln >= 2 and (has_space or not _is_identifier_like(s)):
        return "display-text"

    # identifier-shaped value (object name, dotted key, enum like On/Off)
    return "value"


def enumerate_strings(data):
    """Return a list of dicts ``{offset, prefix_offset, length, text, kind}`` for
    every length-prefixed ascii string in ``data``.

    ``offset`` is the byte offset of the **text body** (the bytes to overwrite),
    ``prefix_offset`` the byte offset of its 8-byte length field, ``length`` the
    body's byte length (= the size-neutral replacement budget), and ``kind`` the
    :func:`classify` role.  Only ``kind == "display-text"`` entries are
    user-editable.
    """
    out = []
    for pre_off, body_off, ln, body in find_strings(data):
        kind = classify(data, pre_off, body)
        out.append({
            "offset": body_off,
            "prefix_offset": pre_off,
            "length": ln,
            "text": body.decode("latin1"),
            "kind": kind,
        })
    return out


def display_texts(data):
    """Just the ``display-text`` entries of :func:`enumerate_strings`."""
    return [e for e in enumerate_strings(data) if e["kind"] == "display-text"]


# --------------------------------------------------------------------------
# Font glyph tables: which atlas rectangle each character's bitmap lives in
# --------------------------------------------------------------------------
# A radium Font node stores (validated on TMNT + Led Zeppelin cards, every
# radium, zero mis-parses):
#
#   char-code array:  [u64 N][N x u16 unicode code points, strictly ascending]
#   ...variable font-header fields (name string, metrics floats, handles)...
#   glyph table:      [u64 N] then N records, chars matching the array 1:1:
#       u16  char code
#       u32  node handle          (top byte 0x80)
#       7x f32 metrics            (bitmap w/h, bearing, advance...; not needed
#                                  for slicing -- the UV rect is ground truth)
#       u8   flag
#       4x f32 UV rect            (u0 v0 u1 v1, normalized by the atlas texture
#                                  dims, top-down, x1/y1 exclusive)
#       u32  texture              0 = no bitmap (e.g. space) | top byte 0x80 =
#                                 the atlas image record follows INLINE (its
#                                 first user introduces it) | else = back-
#                                 reference to an already-introduced handle
#         inline atlas: [u32 texW][u32 texH][u32 fmt(4|5)][u32 0][u32 0]
#                       [u32 length][length bytes of BC1/BC3 blocks]
#       8x u8 zeros
#
# The atlas images themselves are exactly the inline BC3/BC1 images
# ``engine.parse_radium_images`` already finds (the introducing handle sits 28
# bytes before each image's block data), so a glyph resolves to one of those
# parses and the existing atlas PNG extract/patch codec is reused unchanged.
# Some glyphs are stored ROTATED 90 degrees in the atlas (the packer's choice);
# they are sliced/pasted as stored.
MAX_GLYPHS = 4096
_GLYPH_HEAD = struct.Struct("<HI")          # char, handle
_GLYPH_RECT_OFF = 2 + 4 + 28 + 1            # head + 7 metrics floats + flag
_GLYPH_TEX_OFF = _GLYPH_RECT_OFF + 16       # + UV rect
_INLINE_ATLAS = struct.Struct("<6I")        # texW texH fmt 0 0 length


def _find_char_arrays(data, skip_ranges):
    """Yield ``(offset, chars)`` for every ``[u64 N][N ascending u16]``
    char-code array in *data*.  Candidates are anchored on the count's six
    zero high bytes (cheap C-speed ``find``); *skip_ranges* is a sorted list of
    ``(start, end)`` byte ranges to ignore (the inline image block data, where
    zero runs are plentiful and meaningless)."""
    n = len(data)
    ri = 0
    p = data.find(b"\x00\x00\x00\x00\x00\x00")
    while p >= 0:
        i = p - 2                       # count u64 starts 2 bytes before
        while ri < len(skip_ranges) and skip_ranges[ri][1] <= i:
            ri += 1
        if ri < len(skip_ranges) and skip_ranges[ri][0] <= i:
            p = data.find(b"\x00\x00\x00\x00\x00\x00",
                          skip_ranges[ri][1] + 2)
            continue
        if i >= 0:
            cnt = struct.unpack_from("<Q", data, i)[0]
            if 2 <= cnt <= MAX_GLYPHS and i + 8 + 2 * cnt <= n:
                chars = struct.unpack_from("<%dH" % cnt, data, i + 8)
                if (chars[0] >= 0x20
                        and all(a < b for a, b in zip(chars, chars[1:]))):
                    yield i, chars
        p = data.find(b"\x00\x00\x00\x00\x00\x00", p + 1)


def _parse_glyph_records(data, off, chars):
    """Parse ``len(chars)`` glyph records at *off*; every field is validated,
    so a false anchor cannot survive.  Returns ``(glyphs, end_off)`` with
    ``glyphs = [(char, (u0, v0, u1, v1), tex_ref, inline_atlas_or_None)]`` or
    ``None`` on any mismatch."""
    n = len(data)
    glyphs = []
    for want in chars:
        if off + _GLYPH_TEX_OFF + 4 > n:
            return None
        ch, handle = _GLYPH_HEAD.unpack_from(data, off)
        if ch != want or handle >> 24 != 0x80:
            return None
        u0, v0, u1, v1 = struct.unpack_from("<4f", data, off + _GLYPH_RECT_OFF)
        for v in (u0, v0, u1, v1):
            if not (-0.001 <= v <= 1.001):
                return None
        if u1 < u0 or v1 < v0:
            return None
        pos = off + _GLYPH_TEX_OFF
        tex = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        atlas = None
        if tex >> 24 == 0x80:           # first user: atlas image inlined here
            if pos + _INLINE_ATLAS.size > n:
                return None
            tw, th, fmt, z0, z1, ln = _INLINE_ATLAS.unpack_from(data, pos)
            if fmt not in (4, 5) or z0 or z1:
                return None
            pw, ph = (tw + 3) // 4 * 4, (th + 3) // 4 * 4
            if ln != (pw * ph if fmt == 5 else pw * ph // 2):
                return None
            pos += _INLINE_ATLAS.size
            if pos + ln > n:
                return None
            atlas = dict(data_off=pos, length=ln, tex_w=tw, tex_h=th, fmt=fmt)
            pos += ln
        if data[pos:pos + 8] != b"\x00" * 8:
            return None
        pos += 8
        glyphs.append((ch, (u0, v0, u1, v1), tex & 0xFFFFFF, atlas))
        off = pos
    return glyphs, off


def _nearest_name_before(data, off, window=4096):
    """The last identifier-like length-prefixed string before *off* -- the
    font's name (e.g. ``HelveticaNeueBlack``).  ``""`` when none is found."""
    best = ""
    lo = max(0, off - window)
    i = lo
    while i + 8 <= off:
        ln = struct.unpack_from("<Q", data, i)[0]
        if 2 <= ln <= 64 and i + 8 + ln <= off:
            body = data[i + 8:i + 8 + ln]
            if all(32 <= b < 127 for b in body):
                s = body.decode("latin1")
                if s not in _ELEM_TYPES and _has_letter(s):
                    best = s
                i += 8 + ln
                continue
        i += 1
    return best


def parse_glyph_tables(data, images):
    """Find every Font glyph table in a ``scene.radium``.

    *images* is :func:`engine.parse_radium_images`'s output for the same
    *data*; glyph texture references are resolved against it (each image's
    introducing handle sits 28 bytes before its block data), so a glyph's
    ``atlas`` below is one of those very dicts and maps 1:1 onto the atlas
    PNG the image extract writes.

    Returns ``[{"name", "table_off", "glyphs"}]`` with ``glyphs =
    [{"char": int, "rect": (u0, v0, u1, v1), "atlas": image-dict-or-None}]``
    (``atlas is None`` for glyphs with no bitmap, e.g. the space)."""
    by_handle = {}
    by_off = {}
    ranges = []
    for im in images:
        by_off[im["data_off"]] = im
        ranges.append((im["data_off"], im["data_off"] + im["length"]))
        hoff = im["data_off"] - 28
        if hoff >= 0:
            h = struct.unpack_from("<I", data, hoff)[0]
            if h >> 24 == 0x80:
                by_handle[h & 0xFFFFFF] = im
    ranges.sort()

    out = []
    done_until = 0
    for arr_off, chars in _find_char_arrays(data, ranges):
        if arr_off < done_until:
            continue                      # inside the previous font's table
        # The glyph table repeats the same u64 count shortly after the array
        # (a variable-size font header sits between them).
        arr_end = arr_off + 8 + 2 * len(chars)
        needle = struct.pack("<Q", len(chars))
        j = data.find(needle, arr_end, arr_end + 4096)
        while j >= 0:
            res = _parse_glyph_records(data, j + 8, chars)
            if res is not None:
                glyphs, end = res
                out.append({
                    "name": _nearest_name_before(data, j),
                    "table_off": j,
                    "glyphs": [
                        {"char": ch, "rect": rect,
                         "atlas": (by_off.get(inl["data_off"]) if inl
                                   else by_handle.get(ref) if ref else None)}
                        for ch, rect, ref, inl in glyphs],
                })
                done_until = end
                break
            j = data.find(needle, j + 1, arr_end + 4096)
    return out


def glyph_px_rect(glyph):
    """A glyph's atlas rectangle in pixels: ``(x, y, w, h)``, or ``None`` for
    a glyph with no bitmap or an empty rectangle.  UVs are normalized by the
    atlas texture dims (exact 1/dim multiples on every card checked, so
    ``round`` is exact)."""
    a = glyph["atlas"]
    if a is None:
        return None
    u0, v0, u1, v1 = glyph["rect"]
    x0 = round(u0 * a["tex_w"])
    y0 = round(v0 * a["tex_h"])
    x1 = round(u1 * a["tex_w"])
    y1 = round(v1 * a["tex_h"])
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0
