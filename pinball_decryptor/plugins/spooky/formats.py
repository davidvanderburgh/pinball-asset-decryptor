"""File-format detection + archive helpers for Spooky game files."""

import io
import os
import struct
import tarfile
import zipfile

from ...core.checksums import NON_ASSET_DIRS, read_baseline_any
from .games import (GAME_DB, KNOWN_GAMES, PKG_FILENAME_PATTERNS,
                    ZIP_GAME_PATTERNS)

# Folders the app writes into a project that were never in the game archive:
# the engine derivatives Extract generates (Unity/Godot/P3 loose assets) and
# the raw Godot PCK dump they are converted from, plus the project-level
# scratch every plugin shares (``core.checksums.NON_ASSET_DIRS`` — the build
# output, the hydrate parking lot, the mod-pack import copies, the session
# log).  A repack has to leave all of it out: the derivatives are our copies
# of bytes that already live inside a container in the same tree (gigabytes
# of them on a Unity title), and "build" is where Write puts its own output,
# so packing it would fold the previous update file into the next one.
# ``GENERATED_DIRS`` is also what the Replace-Video scan skips, for the
# matching reason — nothing writes those files back.
GENERATED_DIRS = frozenset(NON_ASSET_DIRS) | {"_extracted_assets",
                                              "_pck_contents"}


def generated_at_root(source_dir):
    """Names at the root of *source_dir* that the app put there, not the game.

    :data:`GENERATED_DIRS` always, plus the project sidecars — which are all
    dot-entries (``.checksums.md5``, ``.spooky_meta``, ``.hashcache.json``,
    ``.staged_changes.json``, ``.extract_source.json``, ``.modpack.json``,
    ``.pinproj``, ``.orig/``, ``.modpack_card/``) and none of which the
    Extract baseline knows about, since they are written outside it.  So a
    root dot-entry the baseline doesn't list is ours.

    The baseline check is what keeps that from being a guess: no Spooky game
    archive ships a root dotfile today, but a blanket "dots at the root are
    ours" would silently drop one from the update the day a game does, and
    that failure surfaces on the machine rather than here.
    """
    skips = set(GENERATED_DIRS)
    try:
        names = os.listdir(source_dir)
    except OSError:
        return skips
    if not any(n.startswith(".") for n in names):
        return skips
    shipped = {rel.split("/")[0] for rel in read_baseline_any(source_dir)}
    skips.update(n for n in names
                 if n.startswith(".") and n not in shipped)
    return skips


class GameFile:
    """Detected game file metadata."""

    def __init__(self, path, game_key, game_name, format_type, ext):
        self.path = path
        self.game_key = game_key
        self.game_name = game_name
        self.format_type = format_type
        self.ext = ext


def detect_game(path):
    """Detect game type from file extension, filename, and magic bytes.

    Returns ``GameFile`` or ``None`` if unrecognized.
    """
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    basename = os.path.basename(path)

    # 1. Unique extensions (.ed, .scooby, .beetlejuice, .looney)
    if ext in KNOWN_GAMES:
        game_key, fmt = KNOWN_GAMES[ext]
        display = GAME_DB[game_key]["display"]
        return GameFile(path, game_key, display, fmt, ext)

    # 2. .pkg files — filename + magic byte detection
    if ext == ".pkg":
        return _detect_pkg(path, basename)

    # 3. .zip files — could be game update (P3) or Clonezilla image
    if ext == ".zip":
        return _detect_zip(path, basename)

    # 4. .iso files — always Clonezilla
    if ext == ".iso":
        return GameFile(path, None, "Restore Image", "clonezilla", ext)

    return None


def _detect_pkg(path, basename):
    basename_lower = basename.lower()

    # Filename patterns first (they encode the right key for decryption)
    for pattern, game_key, fmt in PKG_FILENAME_PATTERNS:
        if pattern.lower() in basename_lower:
            display = GAME_DB[game_key]["display"]
            return GameFile(path, game_key, display, fmt, ".pkg")

    # Fall back to magic bytes
    try:
        with open(path, "rb") as f:
            magic = f.read(16)
    except OSError:
        return None

    fmt = detect_pkg_format_from_magic(magic)
    if fmt == "tar_gz":
        return GameFile(path, None, "Unknown Game (.pkg tar.gz)", "tar_gz",
                        ".pkg")
    if fmt == "gpg_symmetric":
        return GameFile(path, None, "Unknown Game (.pkg GPG encrypted)",
                        "gpg_symmetric", ".pkg")
    if fmt == "aes_pkg":
        return GameFile(path, None, "Unknown Game (.pkg AES encrypted)",
                        "aes_pkg", ".pkg")

    return None


def detect_pkg_format_from_magic(magic_bytes):
    """Determine .pkg format from the first 16 bytes."""
    if len(magic_bytes) < 2:
        return None

    # gzip magic
    if magic_bytes[:2] == b"\x1f\x8b":
        return "tar_gz"

    # GPG symmetric: tag 3 (Symmetric-Key Encrypted Session Key)
    if magic_bytes[0] in (0x8c, 0x8d, 0xc3):
        return "gpg_symmetric"

    # AES-CBC .pkg: [8-byte LE uint64 orig_size][16-byte IV]
    if len(magic_bytes) >= 8:
        upper = struct.unpack("<I", magic_bytes[4:8])[0]
        if upper == 0:
            return "aes_pkg"

    return None


def _detect_zip(path, basename):
    basename_lower = basename.lower()

    # Known P3 game update ZIPs
    for pattern, game_key, fmt in ZIP_GAME_PATTERNS:
        if pattern.lower() in basename_lower:
            display = GAME_DB[game_key]["display"]
            return GameFile(path, game_key, display, fmt, ".zip")

    if _is_clonezilla_zip(path):
        return GameFile(path, None, "Restore Image", "clonezilla", ".zip")

    return GameFile(path, None, "Unknown Game (ZIP)", "plain_zip", ".zip")


def _is_clonezilla_zip(path):
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if "partimag" in name or "ptcl-img" in name:
                    return True
    except (zipfile.BadZipFile, OSError):
        pass
    return False


# ---------------------------------------------------------------------------
# Archive helpers (extract / create)
# ---------------------------------------------------------------------------

def extract_zip(zip_path, output_dir, progress_cb=None):
    """Extract a ZIP archive to *output_dir*."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        total = len(members)
        extracted = []
        for i, member in enumerate(members):
            zf.extract(member, output_dir)
            extracted.append(member)
            if progress_cb:
                progress_cb(i + 1, total, member)
    return extracted


def extract_tar_gz(tar_path, output_dir, progress_cb=None):
    """Extract a tar.gz (or plain tar) archive with path-traversal protection."""
    abs_output = os.path.abspath(output_dir)
    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        total = len(members)
        extracted = []
        for i, member in enumerate(members):
            member_path = os.path.normpath(
                os.path.join(abs_output, member.name))
            if not member_path.startswith(abs_output):
                continue  # skip suspicious paths
            tf.extract(member, output_dir)
            extracted.append(member.name)
            if progress_cb:
                progress_cb(i + 1, total, member.name)
    return extracted


def create_zip(source_dir, out_path, progress_cb=None, pad_modes=None):
    """Create a ZIP archive from *source_dir*.  *pad_modes* as :func:`create_tar_gz` (PAD-1420:
    Rick and Morty's game code is a ZIP; its ``pad/`` goes in the game's folder, and the rewrite
    adds the runtime's line to its config.yaml).  A pinHeck card's (PAD-1422) has no ``pad/``
    folder: its rewrite turns the card's PRG into the modes PRG (``rewrite.names``)."""
    all_files, _all_dirs = _scan_for_modes(source_dir, pad_modes)

    total = len(all_files)
    names = {n.upper() for n in getattr(pad_modes[1], "names", ())} if pad_modes else set()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if pad_modes and pad_modes[2]:
            _add_pad_modes_zip(zf, pad_modes)
        for i, (full, rel) in enumerate(all_files):
            arc = rel.replace("\\", "/")
            if names and os.path.basename(rel).upper() in names:
                with open(full, "rb") as fh:
                    data = fh.read()
                new = pad_modes[1](arc, data)
                if new != data:
                    zi = zipfile.ZipInfo.from_file(full, arc)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(zi, new)
                    if progress_cb:
                        progress_cb(i + 1, total, rel)
                    continue
            zf.write(full, rel)
            if progress_cb:
                progress_cb(i + 1, total, rel)


def _add_pad_modes_zip(zf, pad_modes):
    """The custom modes' folder in a ZIP (PAD-1420), and their top files."""
    import time
    files, _rewrite, folder = pad_modes[:3]
    now = time.localtime()[:6]
    for d in (folder, folder + "/modes"):
        zi = zipfile.ZipInfo(d + "/", now)
        zi.external_attr = (0o40755 << 16) | 0x10
        zf.writestr(zi, b"")
    entries = [(folder + "/" + rel, src, fmode) for rel, src, fmode in files]
    entries += list(pad_modes[3] if len(pad_modes) > 3 else ())
    for arc, src, fmode in entries:
        if isinstance(src, bytes):
            data = src
        else:
            with open(src, "rb") as fh:
                data = fh.read()
        zi = zipfile.ZipInfo(arc, now)
        zi.external_attr, zi.compress_type = (0o100000 | fmode) << 16, zipfile.ZIP_DEFLATED
        zf.writestr(zi, data)


def create_tar_gz(source_dir, out_path, progress_cb=None, pad_modes=None):
    """Create a tar.gz archive from *source_dir*.  *pad_modes* (PAD-1417): ``(files, rewrite,
    folder[, top])`` - the custom modes' ``pad/`` files (``[(rel, bytes or path, mode)]``) added
    under *folder* (beside main.x86_64: ``pad`` or ``uptest/pad``), any ``pad/`` the source has
    left out, and ``rewrite(rel, data) -> data`` run on every file (the launch lines, a Mono
    config); ``top`` (PAD-1419) files added at the archive's top in place of the source's own
    (Looney Tunes' override.cfg)."""
    all_files, all_dirs = _scan_for_modes(source_dir, pad_modes)
    total = len(all_files) + len(all_dirs)
    _create_tar_impl(out_path, "w:gz", all_files, all_dirs, total, progress_cb, pad_modes)


def create_tar(source_dir, out_path, progress_cb=None, pad_modes=None):
    """Create a plain (uncompressed) tar archive from *source_dir*; *pad_modes* as
    :func:`create_tar_gz` (Looney Tunes' update is a plain tar, PAD-1419)."""
    all_files, all_dirs = _scan_for_modes(source_dir, pad_modes)
    total = len(all_files) + len(all_dirs)
    _create_tar_impl(out_path, "w:", all_files, all_dirs, total, progress_cb, pad_modes)


def _scan_for_modes(source_dir, pad_modes):
    """:func:`_scan_for_tar` without what the custom modes replace: the source's ``pad/`` folder
    and, at its top, the files the modes put there."""
    all_files, all_dirs = _scan_for_tar(source_dir)
    if pad_modes:
        folder = pad_modes[2]
        tops = {t[0] for t in (pad_modes[3] if len(pad_modes) > 3 else ())}
        def inside(rel):                            # folder may be nested (uptest/pad, PAD-1418)
            if not folder:                          # a pinHeck card: no pad/ (PAD-1422)
                return False
            rel = rel.replace("\\", "/")
            return rel == folder or rel.startswith(folder + "/")
        all_files = [x for x in all_files if not inside(x[1]) and x[1].replace("\\", "/") not in tops]
        all_dirs = [x for x in all_dirs if not inside(x[1])]
    return all_files, all_dirs


def _scan_for_tar(source_dir):
    """``(files, dirs)`` to pack, each a list of ``(abs_path, arcname)``.

    What the app generated (:func:`generated_at_root`) is dropped — but only
    where the app puts it, at the root of the project, so a game that happens
    to ship a folder of the same name deeper in its tree still packs.
    """
    root_key = os.path.normcase(os.path.normpath(os.path.abspath(source_dir)))
    skips = generated_at_root(source_dir)
    all_files = []
    all_dirs = []
    for root, dirs, files in os.walk(source_dir):
        if os.path.normcase(os.path.normpath(os.path.abspath(root))) == root_key:
            dirs[:] = [d for d in dirs if d not in skips]
            files = [f for f in files if f not in skips]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, source_dir)
            all_files.append((full, rel))
        for d in dirs:
            full = os.path.join(root, d)
            rel = os.path.relpath(full, source_dir)
            all_dirs.append((full, rel))
    return all_files, all_dirs


def _create_tar_impl(out_path, mode, all_files, all_dirs, total, progress_cb, pad_modes=None):
    count = 0
    with tarfile.open(out_path, mode) as tf:
        if pad_modes:
            _add_pad_modes(tf, pad_modes)
        for full, rel in all_dirs:
            # recursive=False: the directory entry only.  tarfile.add()
            # recurses by default, so leaving it on wrote every file once per
            # ancestor folder AND again in the file loop below — a 5-deep
            # tree came out several times its real size, which for Halloween
            # is the difference between a 0.8 GB update file and a multi-GB
            # one the machine has to swallow off a USB stick.
            tf.add(full, arcname=rel, recursive=False)
            count += 1
            if progress_cb:
                progress_cb(count, total, rel + "/")
        for full, rel in all_files:
            if pad_modes and os.path.basename(rel) in getattr(pad_modes[1], "names", ()):
                with open(full, "rb") as fh:
                    data = fh.read()
                new = pad_modes[1](rel.replace("\\", "/"), data)
                if new != data:
                    ti = tf.gettarinfo(full, arcname=rel)
                    ti.size = len(new)
                    tf.addfile(ti, io.BytesIO(new))
                    count += 1
                    if progress_cb:
                        progress_cb(count, total, rel)
                    continue
            tf.add(full, arcname=rel)
            count += 1
            if progress_cb:
                progress_cb(count, total, rel)


def _add_pad_modes(tf, pad_modes):
    """The custom modes' folder, first in the archive (PAD-1417), and their top files."""
    import time
    files, _rewrite, folder = pad_modes[:3]
    now = int(time.time())
    for d in (folder, folder + "/modes"):              # folder: "pad", or "uptest/pad"
        ti = tarfile.TarInfo(d)
        ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, now
        tf.addfile(ti)
    for rel, src, fmode in files:
        if isinstance(src, bytes):
            data = src
        else:
            with open(src, "rb") as fh:
                data = fh.read()
        ti = tarfile.TarInfo(folder + "/" + rel)
        ti.size, ti.mode, ti.mtime = len(data), fmode, now
        tf.addfile(ti, io.BytesIO(data))
    for rel, data, fmode in (pad_modes[3] if len(pad_modes) > 3 else ()):
        ti = tarfile.TarInfo(rel)
        ti.size, ti.mode, ti.mtime = len(data), fmode, now
        tf.addfile(ti, io.BytesIO(data))
