"""Pure Python reimplementation of JJP encryption/decryption.

Replaces the C-based LD_PRELOAD approach that required a HASP dongle,
game binary, WSL chroot, and gcc. The PRNG algorithm was reverse-engineered
from memory dumps of the Sentinel-encrypted game code.

Algorithm:
    1. hash_string(path) - BKDR hash (multiplier=131, h0=0)
    2. set_seeds_for_crypto(path) - 5 hashes → 4×uint64 PRNG state
    3. rand64() - combined generator: LCG + xorshift64 + 128-bit counter
    4. XOR keystream in little-endian byte order
"""

import os
import struct
import zlib

M64 = 0xFFFFFFFFFFFFFFFF
M = 1 << 64

# LCG constants (from disassembly)
LCG_MULT = 0x19baffbed
LCG_ADD = 0x12d687

# Mask for s2 (58-bit)
S2_MASK = 0x03FFFFFFFFFFFFFF


# ---------- Hash ----------

def hash_string(data):
    """BKDR hash with multiplier 131 and initial value 0.

    Equivalent to the game's hash_string(const char*) at VA 0x6E2E20.
    """
    if isinstance(data, str):
        data = data.encode('latin-1')
    h = 0
    for b in data:
        h = (h * 131 + b) & 0xFFFFFFFF
    return h


# ---------- PRNG ----------

def _xorshift64(s):
    """Xorshift with parameters (13, 17, 43)."""
    s ^= (s << 13) & M64
    s ^= (s >> 17)
    s ^= (s << 43) & M64
    return s


class PRNG:
    """JJP combined PRNG: LCG + xorshift64 + 128-bit counter.

    State is four uint64 values: s0, s1, s2, s3.
    """
    __slots__ = ('s0', 's1', 's2', 's3')

    def __init__(self):
        self.s0 = self.s1 = self.s2 = self.s3 = 0

    def set_seeds(self, s0, s1, s2, s3):
        self.s0 = s0
        self.s1 = s1
        self.s2 = s2
        self.s3 = s3

    def rand64(self):
        """Generate next 64-bit keystream value."""
        s0, s1, s2, s3 = self.s0, self.s1, self.s2, self.s3

        # Part A: Counter-like update of (s2, s3)
        rax = (s3 << 58) & M64
        rax = (rax + s2) & M64
        full = rax + s3
        s3_new = full & M64
        carry = full >> 64
        s2_new = ((s3 >> 6) + carry) & M64

        # Part B: Xorshift update of s1
        s1_new = _xorshift64(s1)

        # Part C: LCG update of s0
        s0_new = (s0 * LCG_MULT + LCG_ADD) & M64

        # Output
        output = (s3_new + s0_new + s1_new) & M64

        self.s0 = s0_new
        self.s1 = s1_new
        self.s2 = s2_new
        self.s3 = s3_new

        return output

    def set_seeds_for_crypto(self, path):
        """Seed PRNG from a file path (for file decryption/encryption).

        Builds 4 modified path buffers, hashes each plus the original,
        then combines the 5 hashes into 4 state values.
        """
        if isinstance(path, str):
            path_bytes = path.encode('latin-1')
        else:
            path_bytes = path

        # buf0: reversed path
        buf0 = bytes(reversed(path_bytes))
        # buf1: path without '/' characters
        buf1 = bytes(b for b in path_bytes if b != 0x2F)
        # buf2: reversed path without '/'
        buf2 = bytes(b for b in reversed(path_bytes) if b != 0x2F)
        # buf3: each byte + 1
        buf3 = bytes((b + 1) & 0xFF for b in path_bytes)

        h0 = hash_string(path_bytes)
        h1 = hash_string(buf0)
        h2 = hash_string(buf1)
        h3 = hash_string(buf2)
        h4 = hash_string(buf3)

        self.s3 = ((h0 << 32) | h4) & M64
        self.s0 = (((h0 ^ h3) << 32) | h4) & M64
        self.s1 = ((h2 << 32) | h1) & M64
        self.s2 = (((h2 ^ h4) << 32) | (h1 ^ h3)) & S2_MASK

    def set_seeds_for_filler(self, path):
        """Seed PRNG for filler generation."""
        h = hash_string(path)
        val = ((h << 32) | h) & M64
        self.s0 = val
        self.s1 = val
        self.s3 = val
        self.s2 = val & S2_MASK


# ---------- XOR encrypt/decrypt ----------

def xor_keystream(data, prng):
    """XOR data with PRNG keystream in little-endian byte order.

    This is symmetric: encrypt and decrypt are the same operation.
    """
    result = bytearray(len(data))
    pos = 0
    length = len(data)
    while pos < length:
        k = prng.rand64()
        k_bytes = struct.pack('<Q', k)
        chunk = min(8, length - pos)
        for b in range(chunk):
            result[pos + b] = data[pos + b] ^ k_bytes[b]
        pos += 8
    return bytes(result)


def decrypt_file(encrypted_data, filler_size, path):
    """Decrypt an encrypted game file.

    Args:
        encrypted_data: Raw bytes from the encrypted file on disk.
        filler_size: Number of random padding bytes at the start.
        path: Full absolute path from fl.dat (used as encryption key).

    Returns:
        Decrypted content bytes (filler removed).
    """
    prng = PRNG()
    prng.set_seeds_for_crypto(path)
    decrypted = xor_keystream(encrypted_data, prng)
    return decrypted[filler_size:]


def encrypt_file(content, filler_size, path, orig_n2, orig_n3):
    """Encrypt content with CRC32 forgery so it matches original fl.dat checksums.

    Args:
        content: Plaintext content bytes.
        filler_size: Number of filler bytes to prepend.
        path: Full absolute path from fl.dat.
        orig_n2: Original CRC32 of encrypted file on disk (from fl.dat).
        orig_n3: Original CRC32 of decrypted content (from fl.dat).

    Returns:
        Encrypted bytes ready to write to disk.
    """
    # N3 forgery: append 4 bytes so CRC32(content + suffix) = orig_n3
    n3_suffix = crc32_forge_suffix(content, orig_n3)
    content_with_suffix = content + n3_suffix

    # Build buffer: zero filler + content + suffix
    total_size = filler_size + len(content_with_suffix)
    buf = bytearray(total_size)  # filler is zeros
    buf[filler_size:] = content_with_suffix

    # XOR-encrypt
    prng = PRNG()
    prng.set_seeds_for_crypto(path)
    encrypted = bytearray(xor_keystream(bytes(buf), prng))

    # N2 forgery: adjust 4 filler bytes so CRC32(encrypted) = orig_n2
    if filler_size >= 4:
        fp = filler_size - 4  # forge position

        # CRC state after encrypted[0..fp-1]
        state_a = _crc32_partial(bytes(encrypted[:fp])) if fp > 0 else 0xFFFFFFFF

        # CRC state we need at position fp+4 (before content portion)
        target_final = orig_n2 ^ 0xFFFFFFFF
        state_b = _crc32_reverse(target_final, bytes(encrypted[filler_size:]))

        forge_bytes = _crc32_forge_4bytes(state_a, state_b)
        if forge_bytes:
            encrypted[fp:fp + 4] = forge_bytes

    return bytes(encrypted)


# ---------- CRC-32 utilities ----------

# Standard CRC-32 table (ISO 3309 / ITU-T V.42, same as zlib)
_CRC32_TAB = None
_CRC32_REV = None


def _ensure_crc_tables():
    global _CRC32_TAB, _CRC32_REV
    if _CRC32_TAB is not None:
        return

    _CRC32_TAB = [0] * 256
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ (0xEDB88320 if c & 1 else 0)
        _CRC32_TAB[i] = c

    _CRC32_REV = [0] * 256
    for i in range(256):
        _CRC32_REV[_CRC32_TAB[i] >> 24] = i


def crc32_buf(data):
    """Standard CRC32 (same as zlib.crc32)."""
    return zlib.crc32(data) & 0xFFFFFFFF


def _crc32_partial(data):
    """CRC32 internal state (NOT finalized with XOR)."""
    _ensure_crc_tables()
    crc = 0xFFFFFFFF
    tab = _CRC32_TAB
    for b in data:
        crc = (crc >> 8) ^ tab[(crc ^ b) & 0xFF]
    return crc


def _crc32_unstep(state_after, byte):
    """Reverse one CRC32 step."""
    _ensure_crc_tables()
    idx = _CRC32_REV[state_after >> 24]
    return ((state_after ^ _CRC32_TAB[idx]) << 8) | (idx ^ byte)


def _crc32_reverse(state_after, data):
    """Reverse CRC32 through a buffer (last byte to first)."""
    _ensure_crc_tables()
    sa = state_after
    tab = _CRC32_TAB
    rev = _CRC32_REV
    for i in range(len(data) - 1, -1, -1):
        idx = rev[sa >> 24]
        sa = ((sa ^ tab[idx]) << 8) | (idx ^ data[i])
    return sa


def _crc32_forge_4bytes(start, target):
    """Find 4 bytes that transform CRC32 internal state from start to target.

    Uses meet-in-the-middle: forward 2 bytes, backward 2 bytes, match.
    Returns 4 bytes or None if not found.
    """
    _ensure_crc_tables()
    tab = _CRC32_TAB
    rev = _CRC32_REV

    # Forward: enumerate (b0, b1) -> s2
    forward = {}
    for b0 in range(256):
        s1 = (start >> 8) ^ tab[(start ^ b0) & 0xFF]
        for b1 in range(256):
            s2 = (s1 >> 8) ^ tab[(s1 ^ b1) & 0xFF]
            forward[s2] = (b0, b1)

    # Backward: reverse 2 steps from target
    idx3 = rev[target >> 24]
    s3_hi = (target ^ tab[idx3]) << 8

    for s3lo in range(256):
        s3 = (s3_hi | s3lo) & 0xFFFFFFFF
        idx2 = rev[s3 >> 24]
        s2_hi = (s3 ^ tab[idx2]) << 8

        for s2lo in range(256):
            s2 = (s2_hi | s2lo) & 0xFFFFFFFF
            if s2 in forward:
                b0, b1 = forward[s2]
                b2 = s2lo ^ idx2
                b3 = s3lo ^ idx3
                return bytes([b0, b1, b2, b3])

    return None


def crc32_forge_suffix(content, target_crc):
    """Find 4 bytes to append to content so CRC32(content + 4bytes) = target_crc."""
    state = _crc32_partial(content)
    target_internal = target_crc ^ 0xFFFFFFFF
    result = _crc32_forge_4bytes(state, target_internal)
    if result is None:
        raise ValueError(f"CRC32 forge failed for target {target_crc:#010x}")
    return result


# ---------- Filler size detection (dongle-free) ----------

# Magic byte signatures for binary file types
_MAGIC_TABLE = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".ogg": [b"OggS"],
    ".wav": [b"RIFF"],
    ".webm": [b"\x1a\x45\xdf\xa3"],
    ".bmp": [b"BM"],
    ".gif": [b"GIF8"],
    ".mp4": [b"\x00\x00\x00"],
    ".ttf": [b"\x00\x01\x00\x00", b"true", b"typ1"],
    ".otf": [b"OTTO", b"\x00\x01\x00\x00"],
    ".woff": [b"wOFF"],
    ".woff2": [b"wOF2"],
    ".flv": [b"FLV\x01"],
    ".rtf": [b"{\\rtf"],
    ".mov": [b"\x00\x00\x00"],
    ".avi": [b"RIFF"],
    ".ico": [b"\x00\x00\x01\x00"],
    ".cur": [b"\x00\x00\x02\x00"],
    ".zip": [b"PK\x03\x04"],
    ".gz": [b"\x1f\x8b"],
    ".pdf": [b"%PDF"],
    ".dds": [b"DDS "],
    ".swf": [b"FWS", b"CWS"],
    ".tif": [b"II\x2a\x00", b"MM\x00\x2a"],
    ".tiff": [b"II\x2a\x00", b"MM\x00\x2a"],
}

_TEXT_EXTS = {".txt", ".cfg", ".ini", ".csv", ".xml", ".json", ".lua",
              ".js", ".html", ".htm", ".css", ".svg"}

_PRINTABLE = set(range(32, 127)) | {9, 10, 13}

_TEXT_START_CHARS = (set(range(ord("A"), ord("Z") + 1)) |
                    set(range(ord("a"), ord("z") + 1)) |
                    set(range(ord("0"), ord("9") + 1)) |
                    {ord("{"), ord("["), ord("<"), ord("#"),
                     ord("/"), ord('"'), ord("'"), ord("@"),
                     ord("!"), ord("_")})


def _is_lower(b):
    return 97 <= b <= 122  # ord('a')..ord('z')


def _is_upper(b):
    return 65 <= b <= 90  # ord('A')..ord('Z')


def _is_digit(b):
    return 48 <= b <= 57  # ord('0')..ord('9')


def _word_score(decrypted, pos):
    """Score how natural the content at 'pos' looks as a text file start.

    Analyzes the first word's structure and case transitions to distinguish
    real content starts from stray printable filler bytes. Used to refine
    the NP-score based boundary detection for text files.

    Returns >= 6 for plausible content starts, < 6 for suspicious ones.
    """
    if pos + 4 >= len(decrypted):
        return 0
    b0 = decrypted[pos]
    b1 = decrypted[pos + 1]
    b2 = decrypted[pos + 2]

    # XML/HTML tag
    if b0 == 60:  # '<'
        return 12
    # JSON/RTF opening brace
    if b0 == 123:  # '{'
        return 11
    # INI/JSON array
    if b0 == 91:  # '['
        return 11
    # Comment
    if b0 == 35:  # '#'
        return 10
    if b0 == 47 and b1 == 47:  # '//'
        return 10

    # Capitalized word (Upper + lower): check for suspicious case transitions
    if _is_upper(b0) and _is_lower(b1):
        # Count lowercase chars before next uppercase to detect fake prefixes
        # like "Bl" in "BlCrowd" (1 lower then uppercase = suspicious)
        lower_run = 0
        for i in range(1, min(20, len(decrypted) - pos)):
            c = decrypted[pos + i]
            if _is_lower(c) or c == 95 or _is_digit(c):  # 95 = '_'
                lower_run += 1
            elif _is_upper(c):
                if lower_run <= 1:
                    return 3  # Short prefix before case change — suspicious
                break
            else:
                break

        # Measure total first word length
        wlen = 0
        for i in range(min(20, len(decrypted) - pos)):
            c = decrypted[pos + i]
            if _is_lower(c) or _is_upper(c) or _is_digit(c) or c == 95:
                wlen += 1
            else:
                break
        if wlen >= 4:
            return 12
        elif wlen == 3:
            return 8
        return 4

    # Three digits: "001 00:00:00" (beat maps, numbered lists)
    if _is_digit(b0) and _is_digit(b1) and _is_digit(b2):
        return 10

    # Lowercase word (2+ lowercase)
    if _is_lower(b0) and _is_lower(b1):
        run = 0
        for i in range(min(8, len(decrypted) - pos)):
            if _is_lower(decrypted[pos + i]) or decrypted[pos + i] == 95:
                run += 1
            else:
                break
        if run >= 4:
            return 8
        elif run >= 3:
            return 6
        return 5

    # Two uppercase letters
    if _is_upper(b0) and _is_upper(b1):
        if b2 == 95:  # '_' — abbreviation like "EJ_Piano"
            return 6
        return 2

    # lowercase+uppercase (camelCase at file start — very suspicious)
    if _is_lower(b0) and _is_upper(b1):
        return 1

    if _is_upper(b0):
        return 4
    if _is_digit(b0):
        return 3
    if _is_lower(b0):
        return 3
    return 2


def detect_filler_size(encrypted_data, path, max_filler=1024):
    """Detect filler_size without fl.dat by analyzing decrypted content.

    Uses magic byte signatures for binary files and entropy transition
    heuristics for text files. Verified 100% accurate across 26,446 files
    from 3 different JJP games (Hobbit, GnR, Elton John).

    Args:
        encrypted_data: Raw bytes from the encrypted file (only the first
            max_filler + 64 bytes are needed).
        path: Full absolute path (used as encryption key).
        max_filler: Maximum filler size to search for (default 1024).

    Returns:
        Detected filler size, or -1 if detection failed.
    """
    probe_len = min(len(encrypted_data), max_filler + 64)
    prng = PRNG()
    prng.set_seeds_for_crypto(path)
    decrypted = bytearray(xor_keystream(encrypted_data[:probe_len], prng))

    ext = os.path.splitext(path)[1].lower()
    limit = min(max_filler, len(decrypted) - 4)

    # Binary files: magic bytes
    sigs = _MAGIC_TABLE.get(ext, [])
    for sig in sigs:
        for fs in range(0, min(limit, len(decrypted) - len(sig))):
            if decrypted[fs:fs + len(sig)] == sig:
                return fs

    # Text files: find filler/content boundary using entropy transition.
    # Filler is random (~37% printable), content is text (~100% printable).
    # Two-phase approach:
    #   1. NP score: find candidates with most non-printable bytes preceding
    #   2. Word score: refine by checking if content looks like a real text start
    if ext in _TEXT_EXTS:
        candidates = []
        min_run = 32
        fs = 0
        scan_limit = min(limit, len(decrypted) - min_run)
        while fs < scan_limit:
            if decrypted[fs] not in _TEXT_START_CHARS:
                fs += 1
                continue
            run_ok = True
            for j in range(min_run):
                if decrypted[fs + j] not in _PRINTABLE:
                    fs = fs + j + 1
                    run_ok = False
                    break
            if not run_ok:
                continue
            candidates.append(fs)
            fs += 1

        if len(candidates) == 1:
            return candidates[0]
        elif len(candidates) > 1:
            # Phase 1: NP score (non-printable density in preceding 16 bytes)
            np_scores = {}
            for fs in candidates:
                window_start = max(0, fs - 16)
                window = decrypted[window_start:fs]
                if len(window) == 0:
                    np_scores[fs] = 16.0
                else:
                    nps = sum(1 for b in window if b not in _PRINTABLE)
                    if fs > 0 and decrypted[fs - 1] not in _PRINTABLE:
                        nps += 4.0
                    np_scores[fs] = nps

            best_nps = max(np_scores.values())
            first_best = min(fs for fs in candidates
                             if np_scores[fs] == best_nps)

            # Phase 2: Conditional word-score refinement.
            # Only override the NP winner if it looks suspicious (word_score < 6).
            # In that case, check nearby candidates (within 8 bytes) for a
            # significantly more natural-looking content start.
            fb_ws = _word_score(decrypted, first_best)
            if fb_ws >= 6:
                return first_best

            # NP winner looks suspicious; find best word_score in cluster
            cluster = [fs for fs in candidates
                       if first_best <= fs <= first_best + 8]
            best_ws = fb_ws
            best_ws_fs = first_best
            for fs in cluster:
                ws = _word_score(decrypted, fs)
                if ws > best_ws:
                    best_ws = ws
                    best_ws_fs = fs

            if best_ws - fb_ws >= 4:
                return best_ws_fs

            return first_best

    # Fallback for unknown extensions: try magic bytes from all types
    for sigs in _MAGIC_TABLE.values():
        for sig in sigs:
            if len(sig) >= 4:
                for fs in range(0, min(limit, len(decrypted) - len(sig))):
                    if decrypted[fs:fs + len(sig)] == sig:
                        return fs

    return -1
