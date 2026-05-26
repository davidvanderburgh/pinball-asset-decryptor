"""Convert BOF-extracted imported assets back to their source formats.

After ``may_extractor`` writes the imported binaries (``.ctex``,
``.sample``, ``.oggvorbisstr``, ``.fontdata``), this module re-decodes
each one into a player/editor-friendly format under
``pck/_EDITABLE ASSETS/``:

  * ``.ctex`` with ``GST2`` header → ``.webp`` (or ``.png`` if the embedded
    payload is PNG-encoded) — drag into any image viewer
  * ``.ctex`` with ``OggS`` magic   → ``.ogv``  — BOF stores some animation
    loops as Theora video under the texture extension; play with VLC
  * ``.sample`` (Godot AudioStreamWAV) → ``.wav``  — strip the RSRC wrapper,
    extract PCM, wrap in a standard 44-byte RIFF/WAVE header
  * ``.oggvorbisstr`` (Godot AudioStreamOggVorbis) → ``.ogg``  — extract
    the embedded OGG packet sequence and rebuild a playable OGG container
  * ``.fontdata`` (Godot FontFile)    → ``.ttf`` / ``.otf``  — read the
    raw font binary out of the FontFile resource's ``data`` property

Output is dropped under a sibling ``_EDITABLE ASSETS/`` folder so the
original ``.godot/imported/`` tree stays intact for the Write pipeline:

    pck/
      .godot/imported/foo.png-HASH.ctex     (imported binary, untouched)
      _EDITABLE ASSETS/foo-HASH6.webp       (player-friendly copy)
      _EDITABLE ASSETS/_README.txt          (workflow hint for users)

The leading underscore sorts the folder to the top of Explorer /
Finder listings and the all-caps name draws the eye — modders
shouldn't have to hunt for this.

Filename collisions across different imported variants of the same
source asset are resolved by appending the first 6 hash chars.
"""

import os
import re
import struct


# Folder name for the player/editor-friendly decoded copies.  Picked
# for visibility: leading underscore sorts to the top of Windows
# Explorer + Finder alphabetical listings, all-caps + plural noun
# tells the user what to do at a glance.  Pre-May ``source/``
# extracts used the lowercase name; we accept both on Write so
# existing extracts still work.
EDITABLE_DIR_NAME = "_EDITABLE ASSETS"
LEGACY_DIR_NAMES = ("editable", "source")


# `<orig_basename>.<orig_ext>-<32-hex-md5>.<imported_ext>`
_IMPORTED_NAME_RE = re.compile(
    r"^(?P<base>.+)-(?P<hash>[a-f0-9]{32})\.(?P<ext>ctex|sample|fontdata|oggvorbisstr)$",
    re.IGNORECASE,
)


def _parse_imported_name(filename):
    """Return ``(orig_basename_with_ext, hash6)`` from a Godot imported
    file name like ``foo.png-1c4a29c1874032b7a7a4d19647d0c93e.ctex``.
    Returns ``(None, None)`` if the name doesn't match the pattern."""
    m = _IMPORTED_NAME_RE.match(filename)
    if not m:
        return None, None
    return m.group("base"), m.group("hash")[:6]


# ---------------------------------------------------------------------------
# .ctex decoders — Godot Stream Texture 2 (GST2) wraps either a WebP image
# (most common), a PNG, or — in BOF May code — raw OGG Theora video bytes.
# ---------------------------------------------------------------------------

def _decode_ctex(data):
    """Decode a ``.ctex`` payload.

    Returns ``(extension, source_bytes)`` where ``extension`` is one of
    ``.webp`` / ``.png`` / ``.ogv``, or ``(None, None)`` if the format
    isn't recognised.
    """
    if data.startswith(b"OggS"):
        return ".ogv", data
    if not data.startswith(b"GST2"):
        return None, None
    # GST2 layout:
    #   magic (4) + version (4) + width (4) + height (4) + flags (4)
    #   + format (4) + mipmaps (4) + ... + mipmap data starting around
    #   byte 56-64.  Each mipmap is u32 size + N data bytes.  For
    #   WebP-encoded textures the data starts with RIFF/WEBP magic.
    riff = data.find(b"RIFF")
    png = data.find(b"\x89PNG\r\n\x1a\n")
    # Pick whichever appears earlier (and is plausible — within first 256 bytes
    # of the file).
    candidates = [(p, ext, magic_len) for p, ext, magic_len in
                  [(riff, ".webp", None), (png, ".png", None)]
                  if 0 < p < 256]
    if not candidates:
        return None, None
    pos, ext, _ = min(candidates, key=lambda c: c[0])
    # For RIFF/WEBP: the RIFF chunk's u32 size tells us the WebP payload size
    if ext == ".webp" and len(data) >= pos + 8:
        riff_size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        # RIFF chunk size = file_size - 8 (covers everything after the size field)
        webp_end = pos + 8 + riff_size
        return ".webp", bytes(data[pos:min(webp_end, len(data))])
    if ext == ".png":
        # PNG ends with IEND chunk; find it
        iend = data.find(b"IEND\xaeB`\x82", pos)
        if iend > 0:
            return ".png", bytes(data[pos:iend + 8])
        return ".png", bytes(data[pos:])
    return None, None


# ---------------------------------------------------------------------------
# .sample decoder — Godot AudioStreamWAV
# ---------------------------------------------------------------------------

# Godot Variant type IDs (from core/variant/variant.cpp).  Only those
# we actually parse from RSRC properties are listed.
_VTYPE_BOOL = 0x01
_VTYPE_INT = 0x02
_VTYPE_PBA = 0x1F


def _find_data_pba(data, class_name):
    """Locate the ``data`` PackedByteArray inside a Godot RSRC binary
    resource of the named class.

    Returns ``(payload_bytes, payload_offset, payload_end_in_file)`` or
    ``(None, None, None)`` if not found.  The fixed-header approach
    we tried first breaks on resources with extra string properties
    (the string table grows the preamble) or unusual class layouts,
    so we look it up structurally:

      1. find the class name string `<u32 len><class_name>\0`
      2. after that comes ``num_props`` (u32) and a list of
         ``(string_idx, variant_type, value)`` triples
      3. the value we want is the first ``VTYPE_PBA`` after the class
         name — that's the audio payload
    """
    needle = struct.pack("<I", len(class_name) + 1) + class_name + b"\x00"
    # The class name appears TWICE in a Godot RSRC binary: first in the
    # resource header as the type declaration, and again immediately
    # before the internal-resource property list.  The second occurrence
    # is the one we need; use rfind to skip past the header copy.
    p = data.rfind(needle)
    if p < 0:
        return None, None, None
    # Skip class name; next u32 is the property count.
    p += len(needle)
    if p + 4 > len(data):
        return None, None, None
    num_props = struct.unpack("<I", data[p:p+4])[0]
    if num_props == 0 or num_props > 64:
        return None, None, None
    p += 4
    # Walk properties looking for the first PBA value.
    for _ in range(num_props):
        if p + 8 > len(data):
            break
        # string_idx + variant_type
        _str_idx = struct.unpack("<I", data[p:p+4])[0]
        vtype = struct.unpack("<I", data[p+4:p+8])[0]
        p += 8
        if vtype == _VTYPE_PBA:
            if p + 4 > len(data):
                return None, None, None
            pba_len = struct.unpack("<I", data[p:p+4])[0]
            if pba_len < 0 or p + 4 + pba_len > len(data):
                return None, None, None
            payload = bytes(data[p+4:p+4+pba_len])
            payload_end = p + 4 + pba_len
            # PBAs are padded to 4-byte alignment
            payload_end += (4 - (pba_len % 4)) % 4
            return payload, p + 4, payload_end
        elif vtype in (_VTYPE_BOOL, _VTYPE_INT):
            # 4-byte value (Godot stores ints/bools as u32 after the marker pair)
            # But the actual on-disk layout is: variant marker + value u32 = 8 bytes
            # Some int32 variants store an extra "marker" u32 first — fall through
            # to a generic skip that reads next u32 and skips that many bytes.
            p += 4   # generic value size
        else:
            # Unknown variant — bail (we'll let the heuristic fallback try)
            return None, None, None
    return None, None, None


_PLAUSIBLE_RATES = (8000, 11025, 16000, 22050, 32000, 44100, 48000, 88200,
                    96000)


def _parse_sample_trailer(trailer_bytes):
    """Best-effort parse of the trailer's (format, sample_rate, stereo)
    triple.

    BOF's .sample files use a mix of variant encodings for the
    AudioStreamWAV properties — vtype values vary across QOA-payload
    files (5 props, vtype=7) and raw-PCM files (4 props, vtype=3 for
    format and vtype=2 for stereo).  Rather than chase every variant,
    we look up properties by their string-table index pattern:

      * sample rate: any LE u32 anywhere in the trailer matching a
        known audio rate (8000-96000 Hz).
      * stereo: scan for the property *marker* — the bytes
        ``08 00 00 00`` (str_idx=8 = "stereo" per Godot's standard
        AudioStreamWAV layout) followed by a vtype u32 and a u32
        value of 0 or 1.

    Format always assumed = 16-bit PCM (FORMAT_16_BITS=1); all BOF
    .sample files we've seen use 16-bit.
    """
    sample_rate = 0
    # Walk the trailer in 4-byte windows looking for any value that
    # could be a real sample rate.  Use the first hit.
    for i in range(0, len(trailer_bytes) - 4, 4):
        v = struct.unpack("<I", trailer_bytes[i:i+4])[0]
        if v in _PLAUSIBLE_RATES:
            sample_rate = v
            break

    # Stereo: look for the property marker (str_idx=8 = "stereo") +
    # vtype + value=0/1.  This works even when sample_rate isn't
    # encoded — stereo is independent.  Scan all 4-byte-aligned
    # offsets for the pattern.
    stereo = 0
    STEREO_MARKER = struct.pack("<I", 8)   # str_idx for "stereo"
    for i in range(0, len(trailer_bytes) - 12, 4):
        if trailer_bytes[i:i+4] == STEREO_MARKER:
            # Next 4 bytes are vtype (any of 1=BOOL or 2=INT in
            # observed BOF variants), then a 4-byte 0/1 value.
            val = struct.unpack("<I", trailer_bytes[i+8:i+12])[0]
            if val in (0, 1):
                stereo = val
                break

    godot_fmt = 1
    return godot_fmt, sample_rate, stereo


def _decode_sample(data, fallback_rate=44100):
    """Decode a Godot AudioStreamWAV ``.sample`` into a player-friendly
    audio file.

    BOF stores .sample payloads in three different encodings:

      * **Raw PCM** — wrap in a 44-byte RIFF/WAVE header → ``.wav``
      * **QOA** ("qoaf" magic, Quite-OK Audio) — preserve as ``.qoa``
        (a small audio codec; mpv / qoaconv / online players accept it)
      * **OGG** ("OggS" magic) — preserve as ``.ogg``

    ``fallback_rate`` is used when the file is raw PCM AND the trailer
    doesn't encode a mix_rate property (BOF emits ``num_props=4``
    samples without mix_rate, relying on the engine to default to
    44100 — but in Dune the actual consensus rate is 48000, so callers
    should pass the game's consensus rate when known).

    Returns ``(extension, audio_bytes)`` or ``(None, None)``.
    """
    if not data.startswith(b"RSRC"):
        return None, None

    payload, payload_off, payload_end = _find_data_pba(data, b"AudioStreamWAV")
    if payload is None:
        return None, None

    # Check payload's own magic — non-PCM formats either get decoded
    # to WAV (QOA) or pass through (OGG).
    if payload.startswith(b"qoaf"):
        wav = _decode_qoa_to_wav(payload)
        if wav is not None:
            return ".wav", wav
        # Decoder unavailable / failed — fall back to preserving as-is
        return ".qoa", payload
    if payload.startswith(b"OggS"):
        return ".ogg", payload

    # Raw PCM — parse trailer for sample rate / format / stereo.  If
    # the structural scan returns rate=0 (no plausible rate value
    # anywhere in the trailer), fall back to BOF's default 22050 mono
    # 16-bit rather than producing a WAV with byte_rate=0 (causes
    # "27-hour" duration in every player).
    trailer = data[payload_end:]
    godot_fmt, sample_rate, stereo = _parse_sample_trailer(trailer)
    if sample_rate <= 0:
        # Also scan the bytes BEFORE the payload — some BOF variants
        # store the rate in the resource header instead of the trailer.
        for i in range(0, max(0, payload_off - 32), 4):
            v = struct.unpack("<I", data[i:i+4])[0]
            if v in _PLAUSIBLE_RATES:
                sample_rate = v
                break
    if sample_rate <= 0:
        # Caller-provided fallback (the per-game consensus rate, when
        # available).  Without that we default to 44100 (Godot's
        # AudioStreamWAV.mix_rate constructor default).
        sample_rate = fallback_rate
    if sample_rate > 192000:
        return None, None
    channels = 2 if stereo else 1
    sample_width = 2 if godot_fmt == 1 else 1
    return ".wav", _wrap_wav(payload, channels, sample_rate, sample_width)


def _wrap_wav(pcm, channels, sample_rate, sample_width):
    """Build a standard 44-byte RIFF/WAVE PCM header around raw PCM bytes."""
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    bits_per_sample = sample_width * 8
    data_chunk_size = len(pcm)
    riff_size = 36 + data_chunk_size
    wav = bytearray()
    wav += b"RIFF"
    wav += struct.pack("<I", riff_size)
    wav += b"WAVE"
    wav += b"fmt "
    wav += struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                       byte_rate, block_align, bits_per_sample)
    wav += b"data"
    wav += struct.pack("<I", data_chunk_size)
    wav += pcm
    return bytes(wav)


def _decode_qoa_to_wav(qoa_bytes):
    """Decode a QOA byte string to a WAV byte string.  Returns None
    if zstandard / qoa_codec import fails or decoding errors out."""
    try:
        from .qoa_codec import decode as qoa_decode
        pcm, channels, rate = qoa_decode(qoa_bytes)
        return _wrap_wav(pcm, channels, rate, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# .oggvorbisstr decoder — Godot AudioStreamOggVorbis
# ---------------------------------------------------------------------------
# The Godot format wraps an OggPacketSequence sub-resource that holds the
# raw vorbis packets and granule positions.  We unpack the packet array
# and reconstruct OGG pages from them.

def _decode_oggvorbisstr(data):
    """Best-effort: find the raw vorbis packets inside a Godot
    .oggvorbisstr blob and rebuild a playable .ogg file.

    Returns ``(".ogg", ogg_bytes)`` if we can recover a valid stream,
    else ``(None, None)``."""
    if not data.startswith(b"RSRC"):
        return None, None

    # OggPacketSequence packet_data is an Array of Arrays of PackedByteArray.
    # Variant type IDs (from Godot 4.x core/variant/variant.cpp):
    VTYPE_ARRAY = 0x1E
    VTYPE_PBA = 0x1F
    VTYPE_PACKED_INT64 = 0x30

    # The packet_data property follows the string-table entry for
    # `packet_data` (offset 2 in the OggPacketSequence resource).  Rather
    # than fully parse RSRC, scan for the (VTYPE_ARRAY, outer_count)
    # signature followed by a plausible PackedByteArray.  Vorbis stream
    # first packet starts with `\x01vorbis`.
    sig = struct.pack("<I", VTYPE_ARRAY)
    pos = data.find(sig)
    while pos > 0:
        # Try parsing as the packet_data array
        try:
            outer_count = struct.unpack("<I", data[pos + 4:pos + 8])[0]
            if not 1 <= outer_count < 100_000:
                pos = data.find(sig, pos + 1)
                continue
            p = pos + 8
            pages = []
            for _ in range(outer_count):
                if data[p:p + 4] != struct.pack("<I", VTYPE_ARRAY):
                    break
                inner_count = struct.unpack("<I", data[p + 4:p + 8])[0]
                if not 0 <= inner_count < 1000:
                    break
                p += 8
                packets = []
                for _ in range(inner_count):
                    if data[p:p + 4] != struct.pack("<I", VTYPE_PBA):
                        break
                    pkt_len = struct.unpack("<I", data[p + 4:p + 8])[0]
                    if pkt_len < 0 or p + 8 + pkt_len > len(data):
                        break
                    packets.append(bytes(data[p + 8:p + 8 + pkt_len]))
                    # PBA is padded to 4-byte boundary
                    pad = (4 - (pkt_len % 4)) % 4
                    p += 8 + pkt_len + pad
                if len(packets) != inner_count:
                    break
                pages.append(packets)
            else:
                # All pages parsed cleanly — verify Vorbis ID
                if (pages and pages[0] and
                        pages[0][0].startswith(b"\x01vorbis")):
                    # Granule positions follow (PackedInt64)
                    granules = []
                    if data[p:p + 4] == struct.pack("<I", VTYPE_PACKED_INT64):
                        gcount = struct.unpack("<I", data[p + 4:p + 8])[0]
                        for i in range(gcount):
                            offset = p + 8 + i * 8
                            granules.append(
                                struct.unpack("<q", data[offset:offset + 8])[0])
                    return ".ogg", _build_ogg(pages, granules)
        except (struct.error, IndexError):
            pass
        pos = data.find(sig, pos + 1)
    return None, None


def _build_ogg(pages, granules):
    """Rebuild an OGG container from a sequence of vorbis packet groups.

    Each entry in *pages* is a list of vorbis packets for one OGG page,
    with the matching granule position in *granules*.  Returns bytes
    of a valid OGG file.
    """
    out = bytearray()
    serial = 0x12345678
    seq = 0
    for i, packets in enumerate(pages):
        gran = granules[i] if i < len(granules) else -1
        header_type = 0
        if i == 0:
            header_type = 0x02  # bos (beginning of stream)
        elif i == len(pages) - 1:
            header_type = 0x04  # eos
        # Build segment table
        segments = []
        for pkt in packets:
            n = len(pkt)
            while n >= 255:
                segments.append(255)
                n -= 255
            segments.append(n)
        # OGG max 255 segments per page; for simplicity assume packets
        # already fit (which they do for typical vorbis content).
        if len(segments) > 255:
            # Should never happen for normal vorbis; truncate gracefully
            segments = segments[:255]
        seg_count = len(segments)
        page_header = bytearray()
        page_header += b"OggS"
        page_header += bytes([0])              # version
        page_header += bytes([header_type])    # header_type
        page_header += struct.pack("<q", gran) # granule
        page_header += struct.pack("<I", serial)
        page_header += struct.pack("<I", seq)
        page_header += b"\x00\x00\x00\x00"     # crc placeholder
        page_header += bytes([seg_count])
        page_header += bytes(segments)
        body = b"".join(packets)
        # Compute OGG CRC32 over header (with placeholder zeroed) + body
        crc = _ogg_crc(bytes(page_header) + body)
        struct.pack_into("<I", page_header, 22, crc)
        out += page_header
        out += body
        seq += 1
    return bytes(out)


_OGG_CRC_TABLE = None


def _ogg_crc(data):
    """OGG-flavoured CRC-32 (poly 0x04C11DB7, reflected, init 0)."""
    global _OGG_CRC_TABLE
    if _OGG_CRC_TABLE is None:
        table = []
        for i in range(256):
            r = i << 24
            for _ in range(8):
                r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
                r &= 0xFFFFFFFF
            table.append(r)
        _OGG_CRC_TABLE = table
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _OGG_CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# .fontdata decoder — Godot FontFile
# ---------------------------------------------------------------------------

def _decode_fontdata(data):
    """Extract the raw TTF/OTF bytes from a Godot FontFile resource.

    FontFile stores the font binary as a PackedByteArray under its
    ``data`` property (string index 4 typically).  We search for the
    PBA signature near a ``data`` reference and pull out the bytes.

    Returns ``(".ttf"|".otf", font_bytes)`` or ``(None, None)``.
    """
    if not data.startswith(b"RSRC"):
        return None, None
    VTYPE_PBA = 0x1F
    # Look for a PBA whose payload starts with a TrueType or OpenType
    # magic.  TTF: 0x00010000 ('\\x00\\x01\\x00\\x00') or 'true' / 'OTTO'.
    sig = struct.pack("<I", VTYPE_PBA)
    pos = data.find(sig)
    while pos > 0:
        if pos + 8 > len(data):
            break
        pba_len = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if 1000 < pba_len < len(data) - pos:
            payload_start = pos + 8
            head = bytes(data[payload_start:payload_start + 4])
            ext = None
            if head == b"\x00\x01\x00\x00" or head == b"true":
                ext = ".ttf"
            elif head == b"OTTO":
                ext = ".otf"
            elif head == b"\x00\x01\x00\x00":
                ext = ".ttf"
            if ext:
                return ext, bytes(data[payload_start:payload_start + pba_len])
        pos = data.find(sig, pos + 1)
    return None, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

DECODERS = {
    ".ctex":         _decode_ctex,
    ".sample":       _decode_sample,
    ".oggvorbisstr": _decode_oggvorbisstr,
    ".fontdata":     _decode_fontdata,
}


# Subfolder under _EDITABLE ASSETS/ where each decoded format lands.
# Cuts the previously-flat 1700+-file folder into four buckets that
# match modders' workflow — audio editors / image editors / video
# editors / font tools all expect distinct file types.
EXT_FOLDERS = {
    ".wav":  "audio",
    ".qoa":  "audio",
    ".ogg":  "audio",
    ".webp": "images",
    ".png":  "images",
    ".ogv":  "video",
    ".ttf":  "fonts",
    ".otf":  "fonts",
}


_EDITABLE_README = """\
=====================================================================
  ★  EDIT THESE FILES TO MOD THE GAME  ★
=====================================================================

Every game asset from the .fun has been decoded into this folder
in a player-friendly format, organised by what tool you use to edit:

  audio/    *.wav  — voice clips, sound effects, music
                     (open in VLC, Audacity, your DAW)
            *.ogg  — long ambience / music streams
  images/   *.webp — UI graphics + textures
                     (any image viewer; Photoshop / GIMP / Affinity)
            *.png  — assets BOF stored in PNG format
  video/    *.ogv  — animation loops BOF ships as Theora video
                     (VLC / mpv / video editors)
  fonts/    *.ttf  — TrueType fonts (preview by double-click on Windows)
            *.otf  — OpenType fonts

----------------------------------------------------------------------
  How modding works
----------------------------------------------------------------------

1. Browse into a subfolder (audio/, images/, video/, fonts/), find
   the file you want to modify, and edit it in your tool of choice.

2. Save it back with the SAME FILENAME — don't rename, the hash
   suffix is how the Write pipeline pairs your edit back to the
   right slot in the .fun.  You may MOVE files between subfolders
   without breaking anything (Write walks recursively).

3. Switch to the "Write" tab in Pinball Asset Decryptor.  The
   pipeline scans this folder tree for files newer than your last
   Extract, re-encodes them into the Godot-imported format BOF
   expects, then builds a new .fun for you.

4. Copy the new .fun to a USB drive (FAT32) and install on the
   machine.

----------------------------------------------------------------------
  Tips
----------------------------------------------------------------------

* Keep audio at the same sample rate + channel count as the original
  for the cleanest result.  Sample rate is shown by Audacity / VLC's
  Tools → Codec Information.
* If your replacement .webp is much larger than the original, Godot
  will still load it but the texture takes more VRAM; smaller is fine.
* QOA-compressed audio gets re-encoded on Write, so the round-trip is
  not bit-identical — for the cleanest result use lossless source
  files (uncompressed .wav, not MP3 / AAC).
* Don't delete files from this folder — Write only touches files
  newer than the Extract baseline; deleting won't remove them from
  the .fun.

The matching imported binaries live in pck/.godot/imported/ —
those are what actually ship in the .fun.  These subfolders are just
a human-friendly view that gets re-encoded back into them on Write.
"""


def convert_imported_tree(pck_dir, source_dir, log_cb=None, progress_cb=None):
    """Walk ``pck_dir`` for every imported asset and decode each into a
    source-format file under ``source_dir``.  Returns a stats dict
    ``{success: N, failed: N, by_ext: {".wav": N, ".webp": N, ...}}``.

    Idempotent — safe to call after every Extract; overwrites prior
    output.  ``source_dir`` is created if missing.

    ``progress_cb(current, total, label)`` is optional and is called
    on every batch during the conversion loop.
    """
    import sys
    long_prefix = "\\\\?\\" if sys.platform == "win32" else ""

    def _log(msg, sev="info"):
        if log_cb:
            log_cb(msg, sev)

    def _progress(cur, total, label):
        if progress_cb:
            progress_cb(cur, total, label)

    os.makedirs(source_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Per-game consensus sample-rate detection.  For .sample files that
    # don't store a mix_rate property explicitly (BOF emits these with
    # num_props=4; Godot defaults their playback to 44100), we want to
    # use whatever rate THIS game's other .sample files use.  In Dune
    # the consensus is 48000 — using the global default of 44100 makes
    # the no-rate files play ~8 % slow.
    #
    # Pre-pass: scan a handful of .sample files in the input tree,
    # parse their trailers for any rate value, take the mode.  Capped
    # at 100 samples so a 4 GB Dune extract doesn't add minutes here.
    consensus_rate = 44100  # Godot default if pre-pass finds nothing
    rate_counts = {}
    sample_paths = []
    for dp, _, fs in os.walk(pck_dir):
        if os.path.abspath(dp).startswith(os.path.abspath(source_dir)):
            continue
        for f in fs:
            if f.endswith(".sample"):
                sample_paths.append(os.path.join(dp, f))
                if len(sample_paths) >= 100:
                    break
        if len(sample_paths) >= 100:
            break

    for p in sample_paths:
        try:
            with open(long_prefix + os.path.abspath(p), "rb") as fh:
                d = fh.read()
        except OSError:
            continue
        if not d.startswith(b"RSRC"):
            continue
        # Walk to the data PBA payload_end, then scan the trailer
        try:
            _, _, payload_end = _find_data_pba(d, b"AudioStreamWAV")
            trailer = d[payload_end:]
            _, rate, _ = _parse_sample_trailer(trailer)
            if rate > 0:
                rate_counts[rate] = rate_counts.get(rate, 0) + 1
        except Exception:
            continue
    if rate_counts:
        consensus_rate = max(rate_counts, key=rate_counts.get)
        _log(
            f"Consensus sample rate for this game: {consensus_rate} Hz "
            f"(from {sum(rate_counts.values())} probed files: {rate_counts})",
            "info")
    # Drop a workflow hint so users opening the folder in Explorer
    # immediately know what to do.  The leading underscore sorts the
    # file to the top of an alphabetical listing in most file managers.
    try:
        readme = os.path.join(source_dir, "_README.txt")
        with open(long_prefix + os.path.abspath(readme), "w",
                  encoding="utf-8") as fh:
            fh.write(_EDITABLE_README)
    except OSError:
        pass

    stats = {"success": 0, "failed": 0, "by_ext": {}, "failures": []}

    # First pass — count candidates so we have a total for the bar.
    candidates = []
    for dp, _, files in os.walk(pck_dir):
        if os.path.abspath(dp).startswith(os.path.abspath(source_dir)):
            continue
        for f in files:
            if os.path.splitext(f)[1].lower() in DECODERS:
                candidates.append((dp, f))

    total = len(candidates)
    _progress(0, total, "Decoding to source formats...")
    BATCH = max(1, total // 50)

    for idx, (dp, f) in enumerate(candidates):
        ext_lower = os.path.splitext(f)[1].lower()
        decoder = DECODERS.get(ext_lower)
        if decoder is None:
            continue
        in_path = os.path.join(dp, f)
        try:
            with open(long_prefix + os.path.abspath(in_path), "rb") as fh:
                data = fh.read()
        except OSError as e:
            stats["failed"] += 1
            stats["failures"].append((f, f"read error: {e}"))
            continue

        try:
            # The .sample decoder takes a per-game fallback sample rate;
            # everything else is a single-arg callable.
            if ext_lower == ".sample":
                new_ext, new_data = decoder(data, fallback_rate=consensus_rate)
            else:
                new_ext, new_data = decoder(data)
        except Exception as e:
            new_ext, new_data = None, None
            stats["failures"].append((f, f"decode crash: {e}"))

        if new_ext is None or new_data is None:
            stats["failed"] += 1
            if (idx + 1) % BATCH == 0:
                _progress(idx + 1, total,
                          f"Decoding to source formats... {idx+1}/{total}")
            continue

        orig_base, hash6 = _parse_imported_name(f)
        if orig_base is None:
            # Filename doesn't match the imported pattern — fall back
            # to the file's own basename without extension.
            orig_base = os.path.splitext(f)[0]
            hash6 = "xxxxxx"
        # Drop the original extension (BOF stores .png → OGV under
        # foo.png-HASH.ctex; the meaningful name is just "foo")
        stem = os.path.splitext(orig_base)[0]
        out_name = f"{stem}-{hash6}{new_ext}"
        # Bucket into the right subfolder by output extension.  Falls
        # back to the top level if the extension isn't recognised.
        sub = EXT_FOLDERS.get(new_ext, "")
        if sub:
            sub_dir = os.path.join(source_dir, sub)
            try:
                os.makedirs(long_prefix + os.path.abspath(sub_dir),
                            exist_ok=True)
            except OSError:
                pass
            out_path = os.path.join(sub_dir, out_name)
        else:
            out_path = os.path.join(source_dir, out_name)
        try:
            with open(long_prefix + os.path.abspath(out_path), "wb") as fh:
                fh.write(new_data)
        except OSError as e:
            stats["failed"] += 1
            stats["failures"].append((f, f"write error: {e}"))
            if (idx + 1) % BATCH == 0:
                _progress(idx + 1, total,
                          f"Decoding to source formats... {idx+1}/{total}")
            continue

        stats["success"] += 1
        stats["by_ext"][new_ext] = stats["by_ext"].get(new_ext, 0) + 1

        if (idx + 1) % BATCH == 0:
            _progress(idx + 1, total,
                      f"Decoding to source formats... {idx+1}/{total}")

    _progress(total, total,
              f"Decoded {stats['success']} files")
    _log(
        f"Converted {stats['success']} files to source formats "
        f"(failed: {stats['failed']}). By ext: {stats['by_ext']}",
        "success" if stats["success"] > 0 else "warning")
    return stats
