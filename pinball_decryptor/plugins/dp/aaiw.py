"""Alice's Adventures in Wonderland extraction.

AAIW ships as a Clonezilla USB *auto-installer* ``.img``:

    AAIW_x.xx_full_image.img            (MBR)
      partition 1  small SYSLINUX/FAT boot
      partition 2  ext4  ->  /pinball-image/   (Clonezilla backup of the SSD)
          sda1.vfat-ptcl-img.zst          (game ESP, 16 MB)
          sda2.ext4-ptcl-img.zst          (game root — the assets live here)

``sda2.ext4-ptcl-img.zst`` is a partclone-v2 native image, zstd-compressed.
We reconstruct it to a raw ext4 image with the pure-Python
:mod:`...core.partclone` reader (no ``partclone``/``zstd`` binaries needed).

Two read paths, fastest first:

* **7-Zip (preferred).**  7-Zip reads MBR partitions *and* ext4 directly, so
  the whole flow runs as local NTFS I/O — extract the ext partition, pull the
  ``.zst`` out, reconstruct, then extract the asset subtree.  No WSL needed,
  and ~15x faster (the WSL<->Windows boundary caps at ~30 MB/s, which makes
  moving ~11 GB across it the dominant cost).

* **WSL fallback.**  When 7-Zip isn't installed, loop-mount the images with
  the kernel ext4 driver via the executor and stream the assets out.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

from ...core import partclone
from ...core.executor import CommandError
from ...core.tar_utils import safe_member
from .formats import find_ext_partition
from .games import GAME_DB

_OUTER_MNT = "/tmp/pad_aaiw_outer"
_INNER_MNT = "/tmp/pad_aaiw_inner"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# 7-Zip discovery + helpers
# ---------------------------------------------------------------------------

def find_7z():
    """Return a 7-Zip executable path, or None."""
    for name in ("7z", "7zz", "7za"):
        path = shutil.which(name)
        if path:
            return path
    if sys.platform == "win32":
        for cand in (r"C:\Program Files\7-Zip\7z.exe",
                     r"C:\Program Files (x86)\7-Zip\7z.exe"):
            if os.path.isfile(cand):
                return cand
    return None


def _run_7z(args, timeout=3600):
    """Run 7-Zip and return its CompletedProcess (no raising).

    7-Zip uses exit 1 for warnings and even returns exit 2 when listing an
    ext4 image that contains an inode it can't represent (e.g. a special
    file) — while still producing a perfectly usable listing/extraction.
    Callers therefore verify success by the presence of expected output
    rather than the exit code alone.
    """
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, creationflags=_NO_WINDOW)


def _7z_list(sevenzip, archive):
    """Return ``[(path, size), ...]`` for the entries in *archive*.

    Tolerant of non-zero exit codes: parses whatever entries 7-Zip prints.
    """
    res = _run_7z([sevenzip, "l", "-slt", archive], timeout=300)
    entries, path, size = [], None, None
    for line in res.stdout.splitlines():
        if line.startswith("Path = "):
            path = line[7:].strip()
        elif line.startswith("Size = "):
            try:
                size = int(line[7:].strip())
            except ValueError:
                size = 0
        elif line == "" and path is not None:
            # The first record is the archive itself; skip size-less rows.
            if size is not None:
                entries.append((path, size))
            path, size = None, None
    if not entries:
        raise RuntimeError(
            f"7-Zip could not list {os.path.basename(archive)} "
            f"(exit {res.returncode}): {(res.stderr or res.stdout)[-300:]}")
    return entries


# ---------------------------------------------------------------------------
# Preferred path: 7-Zip, all local
# ---------------------------------------------------------------------------

def _extract_via_7z(sevenzip, img_path, output_dir, log, progress, cancel_cb):
    subtree = GAME_DB["aaiw"]["asset_subtree"].lstrip("/")  # opt/assets/alice
    work = tempfile.mkdtemp(prefix="pad_aaiw_")
    try:
        # 1. Extract the (largest) partition — the ext4 game/installer carrier.
        progress(0, 4, "Reading installer image...")
        log("Reading installer image with 7-Zip...", "info")
        import glob
        parts = _7z_list(sevenzip, img_path)
        part_name = max(parts, key=lambda e: e[1])[0]
        _run_7z([sevenzip, "e", img_path, part_name, f"-o{work}", "-y"])
        part_img = os.path.join(work, os.path.basename(part_name))
        if not os.path.isfile(part_img):
            raise RuntimeError("7-Zip could not extract the carrier partition.")
        if cancel_cb and cancel_cb():
            raise RuntimeError("Cancelled.")

        # 2. Pull the ext4 partclone image out of the carrier partition.
        #    Extract by wildcard rather than listing the ext4 first — 7-Zip's
        #    listing of an ext4 image can exit non-zero on an odd inode.
        _run_7z([sevenzip, "e", part_img, "pinball-image/*.ext4-ptcl-img.zst",
                 f"-o{work}", "-y"])
        os.remove(part_img)
        zsts = glob.glob(os.path.join(work, "*.ext4-ptcl-img.zst"))
        if not zsts:
            raise RuntimeError(
                "No ext4 partclone image (sda2.ext4-ptcl-img.zst) inside the "
                "partition — not an AAIW Clonezilla installer.")
        zst_path = zsts[0]
        log(f"  Found {os.path.basename(zst_path)}.", "info")
        if cancel_cb and cancel_cb():
            raise RuntimeError("Cancelled.")

        # 3. Reconstruct the raw ext4 partition (pure-Python partclone+zstd).
        progress(1, 4, "Reconstructing SSD image...")
        log("Reconstructing game SSD from partclone image...", "info")
        raw_path = os.path.join(work, "sda2.raw.img")

        def blk_progress(done, total):
            progress(1, 4, f"Reconstructing: {100 * done // max(total, 1)}%")

        partclone.restore_zst(zst_path, raw_path, progress_cb=blk_progress,
                              cancel_cb=cancel_cb, log_cb=log)
        os.remove(zst_path)
        if cancel_cb and cancel_cb():
            raise RuntimeError("Cancelled.")

        # 4. Extract the asset subtree from the reconstructed ext4.
        progress(2, 4, "Extracting assets...")
        log(f"Extracting {subtree} ...", "info")
        assets_tmp = os.path.join(work, "assets")
        _run_7z([sevenzip, "x", raw_path, subtree, f"-o{assets_tmp}", "-y"])
        os.remove(raw_path)

        progress(3, 4, "Finalizing...")
        src = os.path.join(assets_tmp, *subtree.split("/"))
        if not os.path.isdir(src):
            raise RuntimeError(
                f"Asset subtree /{subtree} not present in the image.")
        os.makedirs(output_dir, exist_ok=True)
        for child in os.listdir(src):
            dst = os.path.join(output_dir, child)
            if os.path.exists(dst):
                shutil.rmtree(dst, ignore_errors=True) if os.path.isdir(dst) \
                    else os.remove(dst)
            shutil.move(os.path.join(src, child), dst)

        n_files = sum(len(fs) for _, _, fs in os.walk(output_dir))
        progress(4, 4, "Done")
        log(f"Extracted {n_files} asset file(s).", "success")
        return n_files
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Fallback path: WSL loop-mount + stream
# ---------------------------------------------------------------------------

def _mount(executor, image_exec, exec_mount, offset=None):
    opts = "loop,ro" + (f",offset={offset}" if offset else "")
    executor.run(f"umount {exec_mount} 2>/dev/null; mkdir -p {exec_mount}",
                 timeout=20)
    executor.run(f"mount -o {opts} {image_exec!r} {exec_mount}", timeout=120)

    def cleanup():
        try:
            executor.run(f"umount {exec_mount} 2>/dev/null; true", timeout=20)
        except Exception:
            pass

    return cleanup


def _extract_via_wsl(img_path, output_dir, executor, log, progress, cancel_cb):
    subtree = GAME_DB["aaiw"]["asset_subtree"]
    part = find_ext_partition(img_path)
    if not part:
        raise RuntimeError(
            f"{os.path.basename(img_path)} has no MBR Linux partition — "
            f"this does not look like an AAIW installer image.")
    offset, _size = part
    img_exec = executor.to_exec_path(img_path)
    os.makedirs(output_dir, exist_ok=True)

    work = tempfile.mkdtemp(prefix="pad_aaiw_")
    raw_host = os.path.join(work, "sda2.raw.img")
    raw_exec = executor.to_exec_path(raw_host)
    unmount_outer = unmount_inner = None
    try:
        progress(0, 4, "Mounting installer image...")
        log("Mounting Clonezilla carrier partition (WSL)...", "info")
        unmount_outer = _mount(executor, img_exec, _OUTER_MNT, offset=offset)
        img_dir_exec = f"{_OUTER_MNT}/pinball-image"
        try:
            listing = executor.run(
                f"ls {img_dir_exec}/ 2>/dev/null | grep 'ext4-ptcl-img.zst'",
                timeout=30)
        except CommandError:
            listing = ""
        names = [ln.strip() for ln in listing.splitlines() if ln.strip()]
        if not names:
            raise RuntimeError(
                "No ext4 partclone image found in pinball-image/.")
        src_exec = f"{img_dir_exec}/{names[0]}"
        log(f"  Found {names[0]}.", "info")

        progress(1, 4, "Reconstructing SSD image...")
        log("Reconstructing game SSD from partclone image...", "info")

        def blk_progress(done, total):
            progress(1, 4, f"Reconstructing: {100 * done // max(total, 1)}%")

        cat = executor.popen_binary(f"cat {src_exec!r}")
        try:
            partclone.restore_zst_fileobj(
                cat.stdout, raw_host, progress_cb=blk_progress,
                cancel_cb=cancel_cb, log_cb=log)
        finally:
            try:
                cat.stdout.close()
            except OSError:
                pass
            cat.wait()
        try:
            unmount_outer()
        finally:
            unmount_outer = None

        progress(2, 4, "Mounting game filesystem...")
        unmount_inner = _mount(executor, raw_exec, _INNER_MNT)
        try:
            executor.run(f'test -d "{_INNER_MNT}{subtree}"', timeout=20)
        except CommandError:
            raise RuntimeError(f"Asset subtree {subtree} not present.")

        progress(3, 4, "Copying assets...")
        log(f"Streaming {subtree} -> output...", "info")
        tar_proc = executor.popen_binary(
            f"tar cf - -C {_INNER_MNT}{subtree!r} .")
        n_files = 0
        try:
            with tarfile.open(fileobj=tar_proc.stdout, mode="r|") as tar:
                for member in tar:
                    if cancel_cb and cancel_cb():
                        raise RuntimeError("Cancelled.")
                    if not (member.isfile() or member.isdir()):
                        continue
                    safe = safe_member(member, output_dir)
                    if safe is None:
                        continue
                    tar.extract(safe, output_dir, set_attrs=False)
                    if member.isfile():
                        n_files += 1
                        if n_files % 50 == 0:
                            progress(3, 4, f"Copied {n_files} files...")
        finally:
            try:
                tar_proc.stdout.close()
            except OSError:
                pass
            tar_proc.wait()

        progress(4, 4, "Done")
        log(f"Extracted {n_files} asset file(s).", "success")
        return n_files
    finally:
        if unmount_inner:
            unmount_inner()
        if unmount_outer:
            unmount_outer()
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# Optional ProRes -> H.264 conversion (AAIW uses ProRes .mov for alpha video,
# which most Windows players can't open).
# ---------------------------------------------------------------------------

def convert_movs_to_mp4(output_dir, log_cb=None, progress_cb=None,
                        cancel_cb=None):
    """Transcode every ``.mov`` under *output_dir* to a playable H.264 .mp4.

    AAIW stores some videos as Apple ProRes (for an alpha channel) which
    Windows' built-in players can't open.  Replaces each ``.mov`` with an
    ``.mp4``.  Returns ``(converted, failed)``.
    """
    from .cdmd import find_ffmpeg

    def log(t, level="info"):
        if log_cb:
            log_cb(t, level)

    ffmpeg = find_ffmpeg()
    movs = [os.path.join(r, f)
            for r, _d, fs in os.walk(output_dir)
            for f in fs if f.lower().endswith(".mov")]
    if not movs:
        return 0, 0
    if not ffmpeg:
        log("ffmpeg not found — leaving ProRes .mov files as-is "
            "(install ffmpeg to auto-convert them).", "warning")
        return 0, 0

    total = len(movs)
    log(f"Converting {total} ProRes video(s) to MP4...", "info")
    ok = fail = 0
    for i, mov in enumerate(movs):
        if cancel_cb and cancel_cb():
            log("ProRes conversion cancelled.", "warning")
            break
        out = os.path.splitext(mov)[0] + ".mp4"
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-nostats", "-i", mov,
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
               "-c:v", "libx264", "-crf", "20", "-preset", "fast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=900,
                                 creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            res = None
        if res is not None and res.returncode == 0 and os.path.isfile(out):
            try:
                os.remove(mov)
            except OSError:
                pass
            ok += 1
        else:
            fail += 1
            log(f"  Failed to convert {os.path.basename(mov)}", "warning")
        if progress_cb:
            progress_cb(i + 1, total, os.path.basename(mov))
    log(f"Converted {ok}/{total} ProRes video(s) to MP4"
        + (f", {fail} failed." if fail else "."),
        "success" if ok else "warning")
    return ok, fail


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def extract(img_path, output_dir, executor,
            display_name=None, log_cb=None, progress_cb=None, cancel_cb=None):
    """Extract the AAIW game asset subtree from a Clonezilla installer img.

    Prefers the fast local 7-Zip path; falls back to WSL when 7-Zip is
    unavailable.  Returns the number of files written to *output_dir*.
    """
    def log(t, level="info"):
        if log_cb:
            log_cb(t, level)

    def progress(c, t, d=""):
        if progress_cb:
            progress_cb(c, t, d)

    sevenzip = find_7z()
    if sevenzip:
        try:
            return _extract_via_7z(sevenzip, img_path, output_dir,
                                   log, progress, cancel_cb)
        except RuntimeError as e:
            ok, _msg = executor.check_available()
            if not ok:
                raise
            log(f"7-Zip path failed ({e}); falling back to WSL...", "warning")
            # Clear any partial output before the fallback re-extracts.
            for child in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
                p = os.path.join(output_dir, child)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) \
                    else os.remove(p)

    ok, msg = executor.check_available()
    if not ok:
        raise RuntimeError(
            "AAIW extraction needs either 7-Zip (fast, recommended) or WSL2.\n"
            + msg + "\nInstall 7-Zip from https://www.7-zip.org/")
    return _extract_via_wsl(img_path, output_dir, executor,
                            log, progress, cancel_cb)
