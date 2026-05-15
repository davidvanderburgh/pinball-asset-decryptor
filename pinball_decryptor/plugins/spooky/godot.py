"""Godot PCK extraction for Looney Tunes (and future Godot-based Spooky games).

Looney Tunes is built on Godot 4.1.3. All game assets (~3,895 files) are
embedded in a ~953 MB Godot PCK archive appended to the main.x86_64 ELF
binary. The PCK is not encrypted.

Asset types and conversions:
- .ogv (171) — Ogg Theora video, copied as-is
- .oggvorbisstr (90) — Godot music resource, stripped to plain .ogg
- .ctex (1,022) — Godot compressed texture, embedded PNG/WebP extracted
- .sample (544) — Godot audio sample resource, converted to .wav
- .gd (237) — GDScript source files, copied as-is
- Other (~1,831) — .import, .scn, .tres, etc., extracted raw only
"""

import os
import struct
import io


# ---------------------------------------------------------------------------
# PCK format constants
# ---------------------------------------------------------------------------
PCK_MAGIC = b"GDPC"
PCK_HEADER_SIZE = 100  # 4+4+12+4+8+64+4 bytes
CHUNK_SIZE = 65536


# ---------------------------------------------------------------------------
# PCK locator and parser
# ---------------------------------------------------------------------------

def _find_pck_offset(f):
    """Find the start offset of an embedded PCK in an ELF binary.

    Godot appends the PCK to the end of the ELF, followed by:
      [8 bytes] PCK data size (uint64 LE)
      [4 bytes] "GDPC" magic

    So the last 12 bytes let us compute where the PCK starts.
    """
    f.seek(0, 2)
    file_size = f.tell()

    if file_size < 12:
        raise ValueError("File too small to contain an embedded PCK")

    # Read the trailing 12 bytes: [data_size:u64][magic:4]
    f.seek(file_size - 12)
    trailer = f.read(12)

    data_size = struct.unpack_from("<Q", trailer, 0)[0]
    magic = trailer[8:12]

    if magic != PCK_MAGIC:
        raise ValueError(
            f"No embedded PCK found (expected GDPC at end, got {magic!r})")

    pck_start = file_size - data_size - 12
    if pck_start < 0:
        raise ValueError(
            f"Invalid PCK data size ({data_size}) exceeds file size ({file_size})")

    # Verify header magic at the computed start
    f.seek(pck_start)
    header_magic = f.read(4)
    if header_magic != PCK_MAGIC:
        raise ValueError(
            f"PCK header magic mismatch at offset {pck_start} "
            f"(got {header_magic!r})")

    return pck_start


def _parse_pck_header(f, pck_start):
    """Parse the PCK v2 header (100 bytes).

    Returns dict with: version, godot_ver, flags, file_base, file_count.
    """
    f.seek(pck_start)
    raw = f.read(PCK_HEADER_SIZE)

    if len(raw) < PCK_HEADER_SIZE:
        raise ValueError("Truncated PCK header")

    magic = raw[0:4]
    if magic != PCK_MAGIC:
        raise ValueError(f"Bad PCK magic: {magic!r}")

    version = struct.unpack_from("<I", raw, 4)[0]
    godot_major = struct.unpack_from("<I", raw, 8)[0]
    godot_minor = struct.unpack_from("<I", raw, 12)[0]
    godot_patch = struct.unpack_from("<I", raw, 16)[0]
    flags = struct.unpack_from("<I", raw, 20)[0]
    file_base = struct.unpack_from("<Q", raw, 24)[0]
    # 64 bytes reserved (offset 32-95)
    file_count = struct.unpack_from("<I", raw, 96)[0]

    return {
        "version": version,
        "godot_ver": (godot_major, godot_minor, godot_patch),
        "flags": flags,
        "file_base": file_base if file_base else pck_start,
        "file_count": file_count,
        "header_end": pck_start + PCK_HEADER_SIZE,
    }


def _parse_file_table(f, header):
    """Parse the PCK file table.

    Returns list of dicts: path, offset, size, md5, flags.
    """
    f.seek(header["header_end"])
    file_base = header["file_base"]
    entries = []

    for _ in range(header["file_count"]):
        # Path length (4 bytes, LE)
        raw_len = f.read(4)
        if len(raw_len) < 4:
            break
        path_len = struct.unpack("<I", raw_len)[0]

        # Path string (padded to 4-byte alignment)
        padded_len = path_len + (4 - path_len % 4) % 4
        path_raw = f.read(padded_len)
        path = path_raw[:path_len].decode("utf-8", errors="replace").rstrip("\x00")

        # Offset (8 bytes), Size (8 bytes), MD5 (16 bytes), Flags (4 bytes)
        meta = f.read(36)
        if len(meta) < 36:
            break

        offset = struct.unpack_from("<Q", meta, 0)[0]
        size = struct.unpack_from("<Q", meta, 8)[0]
        md5 = meta[16:32]
        flags = struct.unpack_from("<I", meta, 32)[0]

        entries.append({
            "path": path,
            "offset": file_base + offset,
            "size": size,
            "md5": md5,
            "flags": flags,
        })

    return entries


def _extract_files(f, file_table, output_dir, progress_cb=None, log_cb=None):
    """Extract all files from the PCK to output_dir.

    Strips the res:// prefix and preserves directory structure.
    Returns list of extracted relative paths.
    """
    extracted = []
    total = len(file_table)

    for i, entry in enumerate(file_table):
        path = entry["path"]

        # Strip res:// prefix
        if path.startswith("res://"):
            path = path[6:]

        # Sanitize path separators
        path = path.replace("\\", "/")
        if path.startswith("/"):
            path = path.lstrip("/")

        out_path = os.path.join(output_dir, path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        # Stream the file in chunks
        f.seek(entry["offset"])
        remaining = entry["size"]
        with open(out_path, "wb") as out_f:
            while remaining > 0:
                chunk = f.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                out_f.write(chunk)
                remaining -= len(chunk)

        extracted.append(path)

        if progress_cb and (i % 50 == 0 or i == total - 1):
            progress_cb(i + 1, total, os.path.basename(path))

    return extracted


# ---------------------------------------------------------------------------
# Asset conversion helpers
# ---------------------------------------------------------------------------

def _convert_oggvorbisstr(src_path, dst_path):
    """Convert Godot AudioStreamOggVorbis (.oggvorbisstr) to standard .ogg.

    Godot 4 stores Ogg Vorbis audio as a binary resource (RSRC) containing
    individual Vorbis packets in an OggPacketSequence, not a raw Ogg stream.
    We extract the packets and granule positions, then reconstruct a valid
    Ogg container.
    """
    with open(src_path, "rb") as f:
        data = f.read()

    if not data.startswith(b"RSRC"):
        # Maybe it's a raw Ogg file
        ogg_pos = data.find(b"OggS")
        if ogg_pos >= 0:
            with open(dst_path, "wb") as f:
                f.write(data[ogg_pos:])
            return True
        return False

    # Find the Vorbis identification header to locate the packet_data start.
    # The packet_data property is stored as nested typed arrays inside the RSRC.
    # Structure: [prop_name_idx:u32] [variant_type:u32] [array_type:u32] [packed_info:u32]
    #   then per page: [0x1e:u32] [count:u32] [0x1f:u32 len:u32 data pad]...
    vorbis_id_pos = data.find(b"\x01vorbis")
    if vorbis_id_pos < 0:
        return False

    # Work backwards from the Vorbis ID header to find the page array start.
    # Layout: ...prop_header(16)... [0x1e] [count=1] [0x1f] [len=30] [\x01vorbis...]
    # The [0x1f][len] is at vorbis_id_pos - 8, the [0x1e][count] is at -16,
    # and the prop_header(16 bytes) is before that.
    pages_start = vorbis_id_pos - 16  # Start of first page's [0x1e][count]

    # Parse all pages of packets
    pages = _parse_ogg_packet_pages(data, pages_start)
    if not pages:
        return False

    # Parse granule positions (follows immediately after packet_data)
    # Find where packet parsing ended
    pos = pages_start
    for page in pages:
        pos += 8  # skip [0x1e][count]
        for pkt in page:
            pos += 8 + len(pkt)  # [0x1f][len][data]
            if len(pkt) % 4:
                pos += 4 - (len(pkt) % 4)  # padding

    # At pos: [name_idx:u32] [variant_type:u32] [packed_info:u32] [granule_data...]
    granule_positions = _parse_granule_positions(data, pos, len(pages))

    # Extract Vorbis stream info from the ID header
    id_packet = pages[0][0] if pages and pages[0] else None
    if not id_packet or len(id_packet) < 16 or id_packet[:7] != b"\x01vorbis":
        return False

    channels = id_packet[11]
    sample_rate = struct.unpack_from("<I", id_packet, 12)[0]

    # Reconstruct Ogg stream
    ogg_data = _build_ogg_stream(pages, granule_positions)
    if not ogg_data:
        return False

    with open(dst_path, "wb") as f:
        f.write(ogg_data)
    return True


def _parse_ogg_packet_pages(data, start):
    """Parse Godot's nested Array of PackedByteArray packets.

    Each page: [0x1e:u32 array_marker] [count:u32] then per packet:
               [0x1f:u32 pba_marker] [length:u32] [bytes...] [padding to 4]

    Returns list of pages, where each page is a list of packet byte strings.
    """
    pos = start
    pages = []

    while pos < len(data) - 8:
        marker = struct.unpack_from("<I", data, pos)[0]
        if marker != 0x1e:  # Array type marker
            break

        count = struct.unpack_from("<I", data, pos + 4)[0]
        if count > 1000:  # sanity check
            break
        pos += 8

        page_packets = []
        for _ in range(count):
            if pos >= len(data) - 8:
                break
            pba_type = struct.unpack_from("<I", data, pos)[0]
            if pba_type != 0x1f:  # PackedByteArray
                break
            pkt_len = struct.unpack_from("<I", data, pos + 4)[0]
            pos += 8
            if pos + pkt_len > len(data):
                break
            page_packets.append(data[pos:pos + pkt_len])
            pos += pkt_len
            # Pad to 4 bytes
            if pkt_len % 4:
                pos += 4 - (pkt_len % 4)

        pages.append(page_packets)

    return pages


def _parse_granule_positions(data, pos, expected_count):
    """Parse the granule_positions PackedInt64Array from the RSRC.

    At pos: [name_idx:u32] [array_type:u32] [packed_info:u32] [int64 values...]
    The packed_info encodes the count.
    """
    granules = []

    if pos + 12 > len(data):
        return [0] * expected_count

    # Skip name_idx and array_type marker
    pos += 4  # name_idx
    variant_type = struct.unpack_from("<I", data, pos)[0]
    pos += 4

    if variant_type == 0x1d:
        # PackedInt64Array: [count:u32] [int64 values...]
        count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        for i in range(min(count, expected_count)):
            if pos + 8 > len(data):
                break
            granules.append(struct.unpack_from("<q", data, pos)[0])
            pos += 8
    elif variant_type == 0x30:
        # Typed Array variant (Godot 4): [packed_info:u32] [int64 values...]
        packed_info = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        for i in range(expected_count):
            if pos + 8 > len(data):
                break
            granules.append(struct.unpack_from("<q", data, pos)[0])
            pos += 8

    # Pad to expected count if needed
    while len(granules) < expected_count:
        granules.append(0)

    return granules


def _build_ogg_stream(pages, granule_positions):
    """Build a valid Ogg bitstream from Vorbis packets and granule positions.

    Creates proper Ogg pages with headers, segment tables, and CRC checksums.
    """
    serial_number = 0x5370  # arbitrary
    result = bytearray()
    page_sequence = 0

    for page_idx, packets in enumerate(pages):
        if not packets:
            continue

        granule = granule_positions[page_idx] if page_idx < len(granule_positions) else 0

        # Determine flags
        flags = 0
        if page_idx == 0:
            flags |= 0x02  # beginning of stream
        if page_idx == len(pages) - 1:
            flags |= 0x04  # end of stream

        # Build segment table and data
        segments = []
        page_data = bytearray()

        for pkt_idx, pkt in enumerate(packets):
            pkt_len = len(pkt)
            # Each packet is split into 255-byte segments + remainder
            while pkt_len >= 255:
                segments.append(255)
                pkt_len -= 255
            segments.append(pkt_len)
            page_data.extend(pkt)

        if len(segments) > 255:
            # Ogg page can have at most 255 segments; split if needed
            # In practice, Godot pages are small enough that this won't happen
            pass

        # Build page header
        header = bytearray()
        header.extend(b"OggS")                                  # capture pattern
        header.append(0)                                         # version
        header.append(flags)                                     # header type
        header.extend(struct.pack("<q", granule))                # granule position
        header.extend(struct.pack("<I", serial_number))          # serial number
        header.extend(struct.pack("<I", page_sequence))          # page sequence
        header.extend(struct.pack("<I", 0))                      # CRC (placeholder)
        header.append(len(segments))                             # number of segments
        header.extend(bytes(segments))                           # segment table

        # Compute CRC over header + data
        full_page = bytes(header) + bytes(page_data)
        crc = _ogg_crc(full_page)
        # Write CRC into the header at offset 22
        struct.pack_into("<I", header, 22, crc)

        result.extend(header)
        result.extend(page_data)
        page_sequence += 1

    return bytes(result)


def _ogg_crc(data):
    """Compute the Ogg CRC-32 checksum."""
    crc = 0
    for byte in data:
        crc = ((crc << 8) ^ _OGG_CRC_TABLE[((crc >> 24) & 0xFF) ^ byte]) & 0xFFFFFFFF
    return crc


# Pre-computed Ogg CRC lookup table (polynomial 0x04c11db7)
_OGG_CRC_TABLE = []
for i in range(256):
    r = i << 24
    for _ in range(8):
        if r & 0x80000000:
            r = ((r << 1) ^ 0x04c11db7) & 0xFFFFFFFF
        else:
            r = (r << 1) & 0xFFFFFFFF
    _OGG_CRC_TABLE.append(r)


def _convert_ctex(src_path, dst_path_base):
    """Extract embedded PNG or WebP from a Godot .ctex (CompressedTexture2D).

    Godot .ctex files start with GST2 (or GDST) magic. The actual image data
    (PNG or WebP) is embedded after the texture header. We scan for the
    image signatures and extract.

    Returns the final output path (with correct extension), or None on failure.
    """
    with open(src_path, "rb") as f:
        data = f.read()

    # Try to find embedded PNG
    png_sig = b"\x89PNG\r\n\x1a\n"
    png_pos = data.find(png_sig)
    if png_pos >= 0:
        # Find PNG end (IEND chunk)
        iend_pos = data.find(b"IEND", png_pos)
        if iend_pos >= 0:
            # IEND chunk: 4 len + 4 type + 4 CRC = ends 8 bytes after "IEND"
            end = iend_pos + 8
            dst_path = dst_path_base + ".png"
            with open(dst_path, "wb") as f:
                f.write(data[png_pos:end])
            return dst_path

    # Try to find embedded WebP
    riff_pos = data.find(b"RIFF")
    if riff_pos >= 0 and data[riff_pos + 8:riff_pos + 12] == b"WEBP":
        # RIFF size is at offset 4 (LE uint32), total = size + 8
        riff_size = struct.unpack_from("<I", data, riff_pos + 4)[0]
        end = riff_pos + 8 + riff_size
        dst_path = dst_path_base + ".webp"
        with open(dst_path, "wb") as f:
            f.write(data[riff_pos:end])
        return dst_path

    return None


def _convert_sample(src_path, dst_path):
    """Convert a Godot .sample resource (AudioStreamWAV) to WAV.

    Parses the Godot RSRC binary resource format to extract:
    - data: PackedByteArray of raw PCM samples
    - format: 0=8-bit, 1=16-bit, 2=IMA-ADPCM
    - mix_rate: sample rate (e.g. 44100)
    - stereo: bool
    Then builds a standard WAV file header.
    """
    with open(src_path, "rb") as f:
        data = f.read()

    if not data.startswith(b"RSRC"):
        return False

    # Parse the RSRC string table to build name_idx -> name mapping.
    # RSRC header: magic(4) + big_endian(4) + use_real64(4) + godot_ver(8)
    #              + format_ver(4) + type_string + metadata...
    # We need to find where properties start by parsing the header.
    result = _parse_rsrc_audio_properties(data)
    if result is None:
        return False

    audio_data, mix_rate, channels, bits_per_sample = result

    # Build WAV header
    byte_rate = mix_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(audio_data)

    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # fmt chunk size
        1,   # PCM format
        channels,
        mix_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )

    with open(dst_path, "wb") as f:
        f.write(wav_header)
        f.write(audio_data)

    return True


def _parse_rsrc_audio_properties(data):
    """Parse a Godot RSRC binary resource to extract AudioStreamWAV properties.

    Scans for the property block containing 'data' (PackedByteArray),
    'format' (int), 'mix_rate' (int), and 'stereo' (bool).

    Returns (audio_data, mix_rate, channels, bits_per_sample) or None.
    """
    # Build the string table: maps index -> property name
    # String table starts after the RSRC type string.
    # We find string names by scanning for known property names.
    string_table = _parse_rsrc_string_table(data)
    if not string_table:
        return None

    # Build reverse lookup: name -> index
    name_to_idx = {name: idx for idx, name in string_table.items()}

    data_idx = name_to_idx.get("data")
    format_idx = name_to_idx.get("format")
    mix_rate_idx = name_to_idx.get("mix_rate")
    stereo_idx = name_to_idx.get("stereo")

    if data_idx is None:
        return None

    # Scan for the 'data' property: [name_idx:u32] [variant_type=0x1f:u32] [len:u32] [bytes]
    # The property block is typically in the latter portion of the file.
    audio_bytes = None
    mix_rate = 44100
    channels = 1
    audio_format = 1  # 0=8bit, 1=16bit

    # Scan byte-by-byte for the data property: [data_idx:u32][0x1f:u32][len:u32]
    # RSRC strings are NOT padded, so properties start at non-4-aligned offsets.
    pos = 0
    data_prop_pos = -1
    while pos < len(data) - 12:
        idx = struct.unpack_from("<I", data, pos)[0]
        variant = struct.unpack_from("<I", data, pos + 4)[0]
        if idx == data_idx and variant == 0x1f:
            pba_len = struct.unpack_from("<I", data, pos + 8)[0]
            if pba_len > 0 and pos + 12 + pba_len <= len(data):
                audio_bytes = data[pos + 12:pos + 12 + pba_len]
                data_prop_pos = pos
                break
        pos += 1

    if audio_bytes is None:
        return None

    # Parse remaining properties sequentially after the audio data.
    # Property format: [name_idx:u32] [variant_type:u32] [value...]
    # Variant types: 1=Bool(4B), 2=Int(4B), 3=Float(4B), 0x82=Int64(8B)
    pos = data_prop_pos + 12 + len(audio_bytes)

    while pos < len(data) - 8:
        idx = struct.unpack_from("<I", data, pos)[0]
        if idx == 0x7FFFFFFF:  # end marker
            break
        if idx >= len(name_to_idx) + 5:  # beyond any reasonable string index
            break

        variant = struct.unpack_from("<I", data, pos + 4)[0]
        val_offset = pos + 8

        if val_offset + 4 > len(data):
            break

        val = struct.unpack_from("<I", data, val_offset)[0]

        if variant in (1, 2, 3):  # Bool, Int, Float (all 4-byte values)
            if format_idx is not None and idx == format_idx:
                audio_format = val
            elif mix_rate_idx is not None and idx == mix_rate_idx:
                if 1000 <= val <= 192000:
                    mix_rate = val
            elif stereo_idx is not None and idx == stereo_idx:
                if val:
                    channels = 2
            pos = val_offset + 4
        elif variant == 0x82:  # Int64
            pos = val_offset + 8
        else:
            pos += 4  # skip unknown, try to recover

    if audio_bytes is None or len(audio_bytes) < 64:
        return None

    # Determine bits per sample from format
    if audio_format == 0:
        bits_per_sample = 8
    else:
        bits_per_sample = 16

    return audio_bytes, mix_rate, channels, bits_per_sample


def _parse_rsrc_string_table(data):
    """Parse the string table from a Godot RSRC binary resource.

    Returns dict of {index: name_string}.
    """
    if len(data) < 28:
        return None

    # Skip: magic(4) + big_endian(4) + use_real64(4) + godot_major(4) + minor(4) + format_ver(4) = 24
    format_ver = struct.unpack_from("<I", data, 20)[0]
    pos = 24

    # Type string: [length:u32] [string bytes] (NOT padded to 4 in RSRC format)
    if pos + 4 > len(data):
        return None
    type_len = struct.unpack_from("<I", data, pos)[0]
    pos += 4 + type_len

    # importmd_offset (8 bytes)
    pos += 8
    # flags (4 bytes, format >= 2)
    if format_ver >= 2:
        pos += 4
    # uid (8 bytes, format >= 4)
    if format_ver >= 4:
        pos += 8
    # 11 reserved u32 fields (44 bytes)
    pos += 44

    # String table: [count:u32] then [len:u32 string pad]...
    if pos + 4 > len(data):
        return {}
    str_count = struct.unpack_from("<I", data, pos)[0]
    pos += 4

    if str_count > 1000:
        return {}

    table = {}
    for i in range(str_count):
        if pos + 4 > len(data):
            break
        s_len = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if pos + s_len > len(data):
            break
        name = data[pos:pos + s_len].decode("utf-8", errors="replace").rstrip("\x00")
        table[i] = name
        pos += s_len

    return table


def _organize_assets(raw_dir, assets_dir, raw_files, log_cb=None):
    """Organize converted assets from raw PCK contents into _extracted_assets/.

    Returns list of asset paths relative to assets_dir.
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    os.makedirs(assets_dir, exist_ok=True)
    video_dir = os.path.join(assets_dir, "video")
    audio_dir = os.path.join(assets_dir, "audio")
    texture_dir = os.path.join(assets_dir, "textures")
    script_dir = os.path.join(assets_dir, "scripts")

    for d in (video_dir, audio_dir, texture_dir, script_dir):
        os.makedirs(d, exist_ok=True)

    extracted = []
    stats = {"ogv": 0, "ogg": 0, "wav": 0, "texture": 0, "gd": 0,
             "ogg_fail": 0, "wav_fail": 0, "tex_fail": 0}

    for rel_path in raw_files:
        src = os.path.join(raw_dir, rel_path)
        basename = os.path.basename(rel_path)
        name, ext = os.path.splitext(basename)
        ext_lower = ext.lower()

        if ext_lower == ".ogv":
            # Copy Ogg Theora video as-is
            dst = os.path.join(video_dir, basename)
            _copy_file(src, dst)
            extracted.append(os.path.relpath(dst, assets_dir))
            stats["ogv"] += 1

        elif ext_lower == ".oggvorbisstr":
            # Strip header to produce plain .ogg
            dst = os.path.join(audio_dir, name + ".ogg")
            if _convert_oggvorbisstr(src, dst):
                extracted.append(os.path.relpath(dst, assets_dir))
                stats["ogg"] += 1
            else:
                stats["ogg_fail"] += 1

        elif ext_lower == ".ctex":
            # Extract embedded PNG/WebP
            dst_base = os.path.join(texture_dir, name)
            result = _convert_ctex(src, dst_base)
            if result:
                extracted.append(os.path.relpath(result, assets_dir))
                stats["texture"] += 1
            else:
                stats["tex_fail"] += 1

        elif ext_lower == ".sample":
            # Convert to WAV
            dst = os.path.join(audio_dir, name + ".wav")
            if _convert_sample(src, dst):
                extracted.append(os.path.relpath(dst, assets_dir))
                stats["wav"] += 1
            else:
                stats["wav_fail"] += 1

        elif ext_lower == ".gd":
            # Copy GDScript source
            dst = os.path.join(script_dir, basename)
            _copy_file(src, dst)
            extracted.append(os.path.relpath(dst, assets_dir))
            stats["gd"] += 1

    # Log summary
    log(f"  Videos: {stats['ogv']} .ogv copied")
    log(f"  Music:  {stats['ogg']} .oggvorbisstr -> .ogg"
        + (f" ({stats['ogg_fail']} failed)" if stats["ogg_fail"] else ""))
    log(f"  Audio:  {stats['wav']} .sample -> .wav"
        + (f" ({stats['wav_fail']} failed)" if stats["wav_fail"] else ""))
    log(f"  Textures: {stats['texture']} .ctex -> PNG/WebP"
        + (f" ({stats['tex_fail']} failed)" if stats["tex_fail"] else ""))
    log(f"  Scripts: {stats['gd']} .gd copied")

    return extracted


def _copy_file(src, dst):
    """Copy a file using chunked reads."""
    with open(src, "rb") as f_in, open(dst, "wb") as f_out:
        while True:
            chunk = f_in.read(CHUNK_SIZE)
            if not chunk:
                break
            f_out.write(chunk)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_godot_pck(binary_path, output_dir, progress_cb=None, log_cb=None):
    """Extract and convert assets from a Godot PCK embedded in an ELF binary.

    Args:
        binary_path: Path to main.x86_64 (or similar ELF with embedded PCK).
        output_dir: Base output directory.
        progress_cb: Optional callback(files_done, total_files, current_name).
        log_cb: Optional callback(text, level) for logging.

    Returns:
        List of extracted asset paths (relative to output_dir/_extracted_assets).
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    log("Parsing Godot PCK from binary...")

    with open(binary_path, "rb") as f:
        # Find and parse the PCK
        pck_start = _find_pck_offset(f)
        file_size = f.seek(0, 2)
        pck_size_mb = (file_size - pck_start) / (1024 * 1024)
        log(f"Found PCK at offset {pck_start} ({pck_size_mb:.0f} MB)")

        header = _parse_pck_header(f, pck_start)
        gv = header["godot_ver"]
        log(f"PCK version {header['version']}, "
            f"Godot {gv[0]}.{gv[1]}.{gv[2]}, "
            f"{header['file_count']} files")

        file_table = _parse_file_table(f, header)
        log(f"Parsed {len(file_table)} file entries")

        # Extract raw files to _pck_contents/
        raw_dir = os.path.join(output_dir, "_pck_contents")
        os.makedirs(raw_dir, exist_ok=True)

        log("Extracting PCK contents...")
        raw_files = _extract_files(f, file_table, raw_dir,
                                   progress_cb=progress_cb, log_cb=log_cb)
        log(f"Extracted {len(raw_files)} raw files to _pck_contents/", "success")

    # Convert and organize assets into _extracted_assets/
    assets_dir = os.path.join(output_dir, "_extracted_assets")
    log("Converting and organizing assets...")
    extracted = _organize_assets(raw_dir, assets_dir, raw_files, log_cb=log_cb)
    log(f"Organized {len(extracted)} converted assets to _extracted_assets/", "success")

    return extracted
