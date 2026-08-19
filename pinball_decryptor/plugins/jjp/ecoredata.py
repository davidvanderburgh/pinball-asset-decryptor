"""The shared engine trees under ``jjpe/gen1`` that the asset pipeline skips.

Extract decrypts exactly one tree — the game's own ``jjpe/gen1/<Game>/edata``.
Everything else is copied byte-for-byte by the system dump, which means
``ecoredata`` (the engine's shared assets: the sound-test clips, menu SFX,
system graphics) lands in ``system/`` still encrypted.  Encrypted files carry
no container magic and no readable header, so they read as *corrupt* rather
than as ciphertext: ``ffprobe`` reports "Invalid data found", every search and
fingerprint scan skips over them, and an asset that is plainly present looks
absent.  That is how a JJP sound-test music clip stayed unfindable through a
full asset audit.

Both cipher schemes already understand these trees — scheme 2 keys them by the
path alone, and scheme 3 keys them by the literal ``core``
(:func:`crypto_v3.crypto_key`).  Only the plumbing was missing, so this module
is deliberately thin: it locates the trees, works out which files are actually
encrypted, and hands each one to the existing crypto.

Encryption round-trips without ``fl.dat``.  The loader checks two CRCs that
normally come from that (dongle-encrypted) file list, but both are recoverable
from the original asset itself: ``n2`` is the CRC of the ciphertext on disk and
``n3`` the CRC of the decrypted content.  Re-encrypting against those values
reproduces checksums the machine accepts, which is what lets a user swap an
engine asset and have the game load it.
"""

import os
import zlib
from dataclasses import dataclass

from .crypto import _MAGIC_TABLE, _PRINTABLE, _TEXT_EXTS

#: Trees shared by every title on the machine, rather than owned by one game.
#: Scheme 3 keys all three by ``core``; keep this in step with
#: :func:`crypto_v3.crypto_key`, which is the authority on that mapping.
SHARED_TREES = ("ecoredata", "JJPECore", "miscfiles")

#: Every crypto key is the file's absolute path on the machine, and the
#: shared trees always sit directly under this prefix.
GEN1_PREFIX = "/jjpe/gen1/"

#: Folder name used for the decrypted output, as a peer of ``graphics/`` and
#: ``sound/`` rather than buried in the ``system/`` mirror.
OUTPUT_DIRNAME = "ecoredata"


@dataclass
class SharedEntry:
    """One file in a shared tree, with everything needed to re-encrypt it."""

    source: str          # absolute path of the encrypted file on disk
    rel: str             # path relative to gen1 (e.g. "ecoredata/sound/x.wav")
    crypto_path: str     # the key: "/jjpe/gen1/ecoredata/sound/x.wav"
    scheme: int          # 2 or 3, from crypto_v3.detect_scheme
    filler_size: int     # lead pad before the content
    crc_encrypted: int   # n2: CRC32 of the bytes on disk
    crc_decrypted: int   # n3: CRC32 of the decrypted content
    encrypted: bool      # False => already plaintext, copy it through


#: Extract-relative prefixes that identify a shared-tree asset.  The output
#: folder is named after the tree it came from, so an extract-relative path
#: ("ecoredata/sound/x.wav") is also its gen1-relative path — which makes the
#: Write reverse-mapping exact instead of guesswork.
SHARED_OUTPUT_PREFIXES = tuple(t + "/" for t in SHARED_TREES)


def crypto_path_for(rel):
    """The absolute path that keys *rel* (a path relative to ``gen1``)."""
    return GEN1_PREFIX + rel.replace(os.sep, "/").lstrip("/")


def is_shared_rel(rel):
    """True when an extract-relative path belongs to a shared engine tree.

    Write needs this to tell an engine asset from a game asset: the two are
    keyed differently and live under different roots on the image, so routing
    one down the other's path composes an absolute path that does not exist.
    """
    return _norm_rel(rel).startswith(SHARED_OUTPUT_PREFIXES)


def _norm_rel(rel):
    r = rel.replace(os.sep, "/")
    while r.startswith("./"):
        r = r[2:]
    return r.lstrip("/")


def output_rel_for_image_path(crypto_path, edata_prefix):
    """Where an in-image asset lands inside the extract.

    The inverse of :func:`image_path_for_rel`.  Shared assets keep their tree
    name so the two directions compose exactly; game assets lose the
    ``<Game>/edata/`` prefix as they always have.
    """
    for tree in SHARED_TREES:
        root = GEN1_PREFIX + tree + "/"
        if crypto_path.startswith(root):
            return tree + "/" + crypto_path[len(root):]
    if edata_prefix and crypto_path.startswith(edata_prefix):
        return crypto_path[len(edata_prefix):]
    return crypto_path


def image_path_for_rel(rel, edata_prefix):
    """Absolute in-image path for an extract-relative asset.

    Write reverses the mapping Extract applied.  Game assets had the
    ``<Game>/edata/`` prefix stripped and get it back; shared engine assets
    kept their tree name, so their gen1 path is recoverable exactly.  Anything
    not in a shared tree is composed exactly as before, so this cannot change
    where an existing game asset is written.
    """
    if is_shared_rel(rel):
        return crypto_path_for(rel)
    return "%s%s" % (edata_prefix, rel)


def looks_plaintext(data, path):
    """True when *data* is already decrypted and must be passed through.

    Encryption is not uniform across trees or releases — POTC ships
    ``miscfiles`` as ordinary PDFs and PNGs while ``ecoredata`` beside it is
    ciphertext.  Deciding by tree name would corrupt whichever half guessed
    wrong, so decide per file: real content starts with its format's magic at
    offset 0, whereas ciphertext starts with the random lead pad.
    """
    if not data:
        return True
    ext = os.path.splitext(path)[1].lower()
    for sig in _MAGIC_TABLE.get(ext, []):
        if data[:len(sig)] == sig:
            return True
    if ext in _TEXT_EXTS:
        head = data[:512]
        if head and all(b in _PRINTABLE for b in head):
            return True
    return False


def _detect(data, crypto_path, game_name):
    """``(scheme, filler_size)`` for an encrypted file, or ``(0, -1)``."""
    from .crypto_v3 import detect_scheme
    try:
        scheme, filler = detect_scheme(data, crypto_path, game_name)
    except Exception:                                    # noqa: BLE001
        return 0, -1
    if filler is None or filler < 0:
        return 0, -1
    return scheme, filler


def decrypt_content(data, entry, game_name):
    """Plaintext content of *entry*, filler removed."""
    if not entry.encrypted:
        return data
    from .crypto_v3 import SCHEME_V3, decrypt_file as decrypt_v3
    if entry.scheme == SCHEME_V3:
        return decrypt_v3(data, entry.filler_size, entry.crypto_path,
                          game_name)
    from .crypto import decrypt_file
    return decrypt_file(data, entry.filler_size, entry.crypto_path)


def encrypt_content(new_content, entry, original_data, game_name):
    """Re-encrypt *new_content* so the machine's CRC checks still pass.

    *original_data* is the untouched ciphertext, which scheme 3 needs in order
    to rebuild the file around its original pads.
    """
    if not entry.encrypted:
        return new_content
    from .crypto_v3 import SCHEME_V3, reencrypt_asset
    if entry.scheme == SCHEME_V3:
        return reencrypt_asset(original_data, new_content, entry.crypto_path,
                               game_name, filler_size=entry.filler_size)
    from .crypto import encrypt_file
    return encrypt_file(new_content, entry.filler_size, entry.crypto_path,
                        entry.crc_encrypted, entry.crc_decrypted)


def scan_shared_trees(gen1_dir, game_name, trees=SHARED_TREES,
                      progress_cb=None):
    """Describe every file in the shared trees under *gen1_dir*.

    Returns a list of :class:`SharedEntry`.  Files that fail detection are
    reported as plaintext pass-throughs rather than dropped: copying a file we
    could not decrypt still leaves the user no worse off than today, whereas
    omitting it would silently shrink the extract.
    """
    entries = []
    for tree in trees:
        root = os.path.join(gen1_dir, tree)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in sorted(filenames):
                src = os.path.join(dirpath, name)
                rel = os.path.relpath(src, gen1_dir).replace(os.sep, "/")
                cpath = crypto_path_for(rel)
                try:
                    with open(src, "rb") as fh:
                        head = fh.read(2048)
                except OSError:
                    continue
                if looks_plaintext(head, cpath):
                    entries.append(SharedEntry(
                        source=src, rel=rel, crypto_path=cpath, scheme=0,
                        filler_size=0, crc_encrypted=0, crc_decrypted=0,
                        encrypted=False))
                else:
                    scheme, filler = _detect(head, cpath, game_name)
                    entries.append(SharedEntry(
                        source=src, rel=rel, crypto_path=cpath,
                        scheme=scheme, filler_size=max(filler, 0),
                        crc_encrypted=0, crc_decrypted=0,
                        encrypted=filler >= 0))
                if progress_cb:
                    progress_cb(len(entries))
    return entries


def extract_entry(entry, game_name, dest_root):
    """Decrypt one *entry* to ``dest_root`` and fill in its CRCs.

    The CRCs are computed here, while both representations are in hand, so a
    later replace can forge against them without re-reading the image.
    """
    with open(entry.source, "rb") as fh:
        data = fh.read()
    content = decrypt_content(data, entry, game_name)
    entry.crc_encrypted = zlib.crc32(data) & 0xFFFFFFFF
    entry.crc_decrypted = zlib.crc32(content) & 0xFFFFFFFF
    dest = os.path.join(dest_root, entry.rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(content)
    return dest
