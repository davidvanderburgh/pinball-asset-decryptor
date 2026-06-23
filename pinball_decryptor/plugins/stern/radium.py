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
