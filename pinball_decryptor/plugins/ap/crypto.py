"""AES-256-CBC encryption/decryption for American Pinball .pkg files.

American Pinball game-code updates ("*-gamecode_*.pkg") use the same
length-prefixed AES-CBC container as Spooky's P-ROC titles — both descend
from the ``pkgprocess`` helper shipped on their Linux game images:

    [8B origsize LE uint64][16B IV][AES-256-CBC ciphertext]

The plaintext is a ZIP of the game tree.  Decryption truncates the output to
``origsize`` to drop the block padding (pkgprocess never inspects the padding
bytes — it just ``truncate``\\s to the declared size).
"""

import os
import struct

from Crypto.Cipher import AES

from .games import AP_AES_KEY, AES_CHUNK_SIZE


def decrypt_aes_pkg(in_path, out_path, key=AP_AES_KEY, progress_cb=None):
    """Decrypt an American Pinball AES-256-CBC .pkg to a ZIP archive on disk.

    Args:
        in_path: Path to the .pkg file.
        out_path: Path to write the decrypted ZIP.
        key: AES-256 key (32 bytes); defaults to the universal AP key.
        progress_cb: Optional callback(bytes_done, total_bytes).

    Raises:
        ValueError: if the output isn't a valid ZIP (wrong key / corrupt input).
    """
    file_size = os.path.getsize(in_path)
    with open(in_path, "rb") as infile:
        origsize = struct.unpack("<Q", infile.read(8))[0]
        iv = infile.read(16)
        decryptor = AES.new(key, AES.MODE_CBC, iv)

        total = file_size - (8 + 16)
        bytes_done = 0
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

    # Validate ZIP magic — the cheapest correctness check that the key fit.
    with open(out_path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04":
        raise ValueError(
            f"Decryption produced invalid ZIP (magic: {magic.hex()}). "
            "Wrong key or corrupt input.")


def encrypt_aes_pkg(in_path, out_path, key=AP_AES_KEY, progress_cb=None):
    """Encrypt a ZIP archive into an American Pinball AES-256-CBC .pkg.

    Args:
        in_path: Path to the ZIP file.
        out_path: Path to write the .pkg.
        key: AES-256 key (32 bytes); defaults to the universal AP key.
        progress_cb: Optional callback(bytes_done, total_bytes).
    """
    origsize = os.path.getsize(in_path)
    iv = os.urandom(16)
    encryptor = AES.new(key, AES.MODE_CBC, iv)

    total = origsize
    bytes_done = 0
    with open(out_path, "wb") as outfile:
        # Header: [8B origsize LE][16B IV]
        outfile.write(struct.pack("<Q", origsize))
        outfile.write(iv)

        with open(in_path, "rb") as infile:
            while True:
                chunk = infile.read(AES_CHUNK_SIZE)
                if not chunk:
                    break
                # Only the final chunk can be short (AES_CHUNK_SIZE is a
                # multiple of 16).  pkgprocess space-pads it to the block
                # size; the size header lets the machine truncate it back.
                if len(chunk) % 16 != 0:
                    chunk += b" " * (16 - len(chunk) % 16)
                outfile.write(encryptor.encrypt(chunk))
                bytes_done += len(chunk)
                if progress_cb:
                    progress_cb(bytes_done, total)


def looks_like_ap_pkg(path, key=AP_AES_KEY):
    """Return True if *path* is an AES .pkg that decrypts to a ZIP with *key*.

    A key-validated probe: it reads only the header + first ciphertext block,
    so it's cheap enough to run during auto-detect.  Because the AP key won't
    turn another maker's ciphertext into ``PK\\x03\\x04``, this never
    false-claims (e.g.) a Spooky package.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(8 + 16 + 16)
    except OSError:
        return False
    if len(head) < 8 + 16 + 16:
        return False
    # Bytes [4:8] are the high dword of the 64-bit size — zero for every
    # real (<4 GiB) package; a cheap pre-filter before the AES probe.
    if struct.unpack("<I", head[4:8])[0] != 0:
        return False
    try:
        plain = AES.new(key, AES.MODE_CBC, head[8:24]).decrypt(head[24:40])
    except (ValueError, KeyError):
        return False
    return plain[:4] == b"PK\x03\x04"
