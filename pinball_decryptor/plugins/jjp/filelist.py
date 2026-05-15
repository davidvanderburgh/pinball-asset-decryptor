"""Parser for decrypted fl.dat file lists.

Also provides scan_edata_files() which can discover encrypted files
and detect their filler sizes without needing fl.dat (dongle-free mode).
"""

import os
from dataclasses import dataclass


@dataclass
class FileEntry:
    """One entry from fl.dat."""
    path: str            # full absolute path (e.g. /jjpe/gen1/Wonka/edata/img/foo.png)
    filler_size: int     # random padding bytes before actual content
    crc_encrypted: int   # n2: CRC32 of encrypted file bytes on disk
    crc_decrypted: int   # n3: CRC32 of decrypted content after filler removal


def parse_fl_dat(path_or_data):
    """Parse a decrypted fl.dat into FileEntry objects.

    Args:
        path_or_data: Either a file path (str) or raw bytes/string content.

    Returns:
        List of FileEntry objects.
    """
    if isinstance(path_or_data, bytes):
        text = path_or_data.decode('latin-1')
    elif isinstance(path_or_data, str) and '\n' in path_or_data:
        text = path_or_data
    else:
        with open(path_or_data, 'r', encoding='latin-1') as f:
            text = f.read()

    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: full_path,filler_size,n2,n3
        # Parse from right since path may contain commas (unlikely but safe)
        parts = line.rsplit(',', 3)
        if len(parts) != 4:
            continue
        try:
            entry = FileEntry(
                path=parts[0],
                filler_size=int(parts[1]),
                crc_encrypted=int(parts[2]),
                crc_decrypted=int(parts[3]),
            )
            entries.append(entry)
        except (ValueError, IndexError):
            continue

    return entries


def detect_edata_prefix(entries):
    """Detect the edata prefix from fl.dat entries.

    Returns the prefix string (e.g. "/jjpe/gen1/Wonka/edata/") or empty string.
    """
    if not entries:
        return ""
    first = entries[0].path
    idx = first.find("/edata/")
    if idx >= 0:
        return first[:idx + 7]
    return ""


def scan_edata_files(edata_root, path_prefix, progress_cb=None):
    """Scan an edata directory and build a file list without fl.dat.

    Discovers all encrypted files, detects filler sizes via magic bytes,
    and computes CRC32 values. This eliminates the HASP dongle requirement.

    Args:
        edata_root: Filesystem path to the edata directory
            (e.g. "/tmp/jjp_mnt/jjpe/gen1/Hobbit/edata").
        path_prefix: The path prefix to use for crypto keys
            (e.g. "/jjpe/gen1/Hobbit/edata/").
        progress_cb: Optional callback(current, total, path) for progress.

    Returns:
        List of FileEntry objects with detected filler sizes and CRC32 values.
    """
    from .crypto import detect_filler_size, crc32_buf, decrypt_file

    # Discover all files
    all_files = []
    for dirpath, _dirnames, filenames in os.walk(edata_root):
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, edata_root).replace("\\", "/")
            crypto_path = path_prefix + rel
            all_files.append((full, crypto_path))

    entries = []
    total = len(all_files)

    for i, (full_path, crypto_path) in enumerate(all_files):
        if progress_cb and (i % 100 == 0 or i + 1 == total):
            progress_cb(i, total, crypto_path)

        with open(full_path, "rb") as f:
            enc_data = f.read()

        if len(enc_data) < 8:
            continue

        n2 = crc32_buf(enc_data)
        filler_size = detect_filler_size(enc_data, crypto_path)

        if filler_size < 0:
            # Detection failed; skip this file
            continue

        if len(enc_data) <= filler_size:
            continue

        content = decrypt_file(enc_data, filler_size, crypto_path)
        n3 = crc32_buf(content)

        entries.append(FileEntry(
            path=crypto_path,
            filler_size=filler_size,
            crc_encrypted=n2,
            crc_decrypted=n3,
        ))

    return entries


def write_fl_dat(entries, output_path):
    """Write a file list in fl.dat format.

    Args:
        entries: List of FileEntry objects.
        output_path: Path to write the fl.dat file.
    """
    with open(output_path, "w", encoding="latin-1") as f:
        for e in entries:
            f.write("{},{},{},{}\n".format(
                e.path, e.filler_size, e.crc_encrypted, e.crc_decrypted))
