"""AES-256-CBC encryption/decryption for Spooky .pkg files."""

import os
import struct

from Crypto.Cipher import AES

from .games import RM_AES_KEY, AC_AES_KEY, AES_CHUNK_SIZE

# Map format_type to AES key
AES_KEYS = {
    "rm_pkg": RM_AES_KEY,
    "ac_pkg": AC_AES_KEY,
}


def decrypt_aes_pkg(in_path, out_path, key, progress_cb=None):
    """Decrypt an AES-256-CBC .pkg file to a ZIP archive on disk.

    Binary format: [8B origsize LE uint64][16B IV][AES-CBC ciphertext]

    Args:
        in_path: Path to .pkg file.
        out_path: Path to write decrypted ZIP.
        key: AES-256 key (32 bytes).
        progress_cb: Optional callback(bytes_done, total_bytes).
    """
    file_size = os.path.getsize(in_path)
    with open(in_path, "rb") as infile:
        origsize = struct.unpack("<Q", infile.read(8))[0]
        iv = infile.read(16)
        decryptor = AES.new(key, AES.MODE_CBC, iv)

        data_start = 8 + 16
        bytes_done = 0
        total = file_size - data_start

        with open(out_path, "wb") as outfile:
            while True:
                chunk = infile.read(AES_CHUNK_SIZE)
                if not chunk:
                    break
                outfile.write(decryptor.decrypt(chunk))
                bytes_done += len(chunk)
                if progress_cb:
                    progress_cb(bytes_done, total)
            outfile.truncate(origsize)

    # Validate ZIP magic
    with open(out_path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04":
        raise ValueError(
            f"Decryption produced invalid ZIP (magic: {magic.hex()}). "
            "Wrong key or corrupt input.")


def encrypt_aes_pkg(in_path, out_path, key, progress_cb=None):
    """Encrypt a ZIP archive into an AES-256-CBC .pkg file.

    Args:
        in_path: Path to ZIP file.
        out_path: Path to write .pkg file.
        key: AES-256 key (32 bytes).
        progress_cb: Optional callback(bytes_done, total_bytes).
    """
    origsize = os.path.getsize(in_path)
    iv = os.urandom(16)
    encryptor = AES.new(key, AES.MODE_CBC, iv)

    bytes_done = 0
    total = origsize

    with open(out_path, "wb") as outfile:
        # Write header
        outfile.write(struct.pack("<Q", origsize))
        outfile.write(iv)

        with open(in_path, "rb") as infile:
            while True:
                chunk = infile.read(AES_CHUNK_SIZE)
                if not chunk:
                    break
                # Pad last chunk to AES block size
                if len(chunk) % 16 != 0:
                    chunk += b"\x00" * (16 - len(chunk) % 16)
                outfile.write(encryptor.encrypt(chunk))
                bytes_done += len(chunk)
                if progress_cb:
                    progress_cb(bytes_done, total)


# Backwards-compatible wrappers
def decrypt_rm_pkg(in_path, out_path, progress_cb=None):
    return decrypt_aes_pkg(in_path, out_path, RM_AES_KEY, progress_cb)


def encrypt_rm_pkg(in_path, out_path, progress_cb=None):
    return encrypt_aes_pkg(in_path, out_path, RM_AES_KEY, progress_cb)
