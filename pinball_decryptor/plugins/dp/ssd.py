r"""Direct read/write of a physically-connected Dutch Pinball game SSD.

The modder pulls the game's SSD (or boots from it over USB) and connects it
to their PC.  This module mounts the SSD's Linux root partition and either
copies the game asset subtree out (Extract) or writes modified files back
in place (Write) — no ISO / .img intermediate.

Asset subtree, auto-detected per game so the same code serves both:
  * Alice's Adventures in Wonderland -> ``/opt/assets/alice``
  * The Big Lebowski                 -> the game's ``.../assets`` dir
    (located by finding ``assets/sequences`` with ``.cdmd`` files)

Mounting a raw physical disk needs OS help and elevation:
  * Windows: ``wsl --mount \\.\PHYSICALDRIVEn --partition N --type ext4``
    (the disk is taken offline first so Windows releases it).  Requires
    Administrator + WSL2.
  * Linux:   ``mount /dev/sdXN`` (sudo).

SAFETY: before writing anything we content-verify that the mounted
partition actually contains a Dutch Pinball asset subtree, and Write only
copies files that differ from the Extract baseline.  Still — writing to a
physical disk is destructive; always work from a backup.

NOTE: the ext4 mount / read / write / tar-stream mechanics are validated
against loop images, but the physical-drive *attach* path can only be
exercised with a real connected SSD.
"""

import os
import subprocess
import sys
import tarfile

from ...core.executor import CommandError
from ...core.tar_utils import safe_member

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Where, inside the mounted root, each game's moddable assets live.
_AAIW_SUBTREE = "/opt/assets/alice"


# ---------------------------------------------------------------------------
# Host-level helpers (run outside the WSL bash wrapper)
# ---------------------------------------------------------------------------

def _run_host(args, timeout=120):
    """Run a host command; return ``(returncode, stdout, stderr)``."""
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, creationflags=_NO_WINDOW)
        return r.returncode, r.stdout or "", r.stderr or ""
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def _disk_number(device_path):
    r"""Extract the integer disk number from ``\\.\PHYSICALDRIVEn``."""
    tail = device_path.rstrip("\\").upper().split("PHYSICALDRIVE")[-1]
    return tail if tail.isdigit() else None


def _set_disk_offline(disk_num, offline):
    state = "$true" if offline else "$false"
    _run_host(["powershell", "-NoProfile", "-Command",
               f"Set-Disk -Number {disk_num} -IsOffline {state}"], timeout=20)


def _windows_partition_candidates(disk_num):
    """Linux/ext4-looking partitions on *disk_num*, largest first.

    Falls back to a plain 1..8 sweep if Get-Partition gives nothing useful.
    """
    rc, out, _ = _run_host(
        ["powershell", "-NoProfile", "-Command",
         f"Get-Partition -DiskNumber {disk_num} | "
         f"ForEach-Object {{ '{{0}}|{{1}}|{{2}}' -f "
         f"$_.PartitionNumber, $_.Size, $_.Type }}"], timeout=20)
    parts = []
    for line in out.splitlines():
        f = line.strip().split("|")
        if len(f) >= 2 and f[0].strip().isdigit():
            try:
                parts.append((int(f[0]), int(f[1]) if f[1].strip() else 0))
            except ValueError:
                pass
    if parts:
        # Skip tiny (<256 MB) boot/ESP partitions; largest first.
        big = [p for p in parts if p[1] == 0 or p[1] >= 256 * 1024 * 1024]
        big.sort(key=lambda p: p[1], reverse=True)
        return [p[0] for p in big] or [p[0] for p in parts]
    return [2, 1, 3, 4, 5, 6, 7, 8]


# ---------------------------------------------------------------------------
# Asset-subtree detection (game-agnostic)
# ---------------------------------------------------------------------------

def find_game_subtree(executor, mount_point):
    """Return the absolute asset-subtree path inside *mount_point*, or None.

    Recognises AAIW (``/opt/assets/alice``) and TBL (a ``.../assets`` dir
    holding ``sequences/*.cdmd``).
    """
    # AAIW: fixed path.
    try:
        executor.run(f'test -d "{mount_point}{_AAIW_SUBTREE}"', timeout=15)
        return _AAIW_SUBTREE
    except CommandError:
        pass
    # TBL: find an assets/sequences dir that contains .cdmd files.
    try:
        out = executor.run(
            f"find {mount_point} -maxdepth 6 -type d -path '*/assets/sequences' "
            f"2>/dev/null | head -20", timeout=60)
    except CommandError:
        out = ""
    for seq_dir in (ln.strip() for ln in out.splitlines() if ln.strip()):
        try:
            executor.run(f"ls {seq_dir}/*/*.cdmd {seq_dir}/*.cdmd "
                         f"2>/dev/null | head -1 | grep -q .", timeout=20)
        except CommandError:
            continue
        assets_dir = seq_dir[:-len("/sequences")]  # strip trailing /sequences
        # Return relative-to-mount absolute path (drop the mount prefix).
        return assets_dir[len(mount_point):] if assets_dir.startswith(
            mount_point) else assets_dir
    return None


# ---------------------------------------------------------------------------
# Mount / unmount a physical game partition
# ---------------------------------------------------------------------------

def mount_game_ssd(executor, device_path, read_only, log,
                   partition_override=None):
    """Mount the SSD's game partition; return ``(mount_point, subtree, cleanup)``.

    Tries candidate partitions until one mounts AND content-verifies as a
    Dutch Pinball asset tree.  Raises RuntimeError if none match.
    """
    if sys.platform == "win32":
        return _mount_windows(executor, device_path, read_only, log,
                              partition_override)
    return _mount_linux(executor, device_path, read_only, log,
                        partition_override)


def _mount_windows(executor, device_path, read_only, log, partition_override):
    disk_num = _disk_number(device_path)
    if disk_num is None:
        raise RuntimeError(f"Unrecognised Windows device path: {device_path}")

    _run_host(["wsl", "--unmount", device_path], timeout=20)
    log("Taking disk offline so WSL can attach it...", "info")
    _set_disk_offline(disk_num, True)

    candidates = ([partition_override] if partition_override
                  else _windows_partition_candidates(disk_num))
    opts = "ro" if read_only else "rw"
    attached_part = None
    last_err = ""
    for part in candidates:
        mount_cmd = ["wsl", "--mount", device_path, "--partition", str(part),
                     "--type", "ext4", "--options", opts]
        rc, _out, err = _run_host(mount_cmd, timeout=40)
        if rc != 0:
            last_err = (err or "").strip()
            if "ALREADY" in last_err.upper():
                _run_host(["wsl", "--shutdown"], timeout=30)
                _set_disk_offline(disk_num, True)
                rc, _out, err = _run_host(mount_cmd, timeout=40)
            if rc != 0:
                continue
        mount_point = f"/mnt/wsl/PHYSICALDRIVE{disk_num}p{part}"
        subtree = find_game_subtree(executor, mount_point)
        if subtree:
            attached_part = part
            log(f"  Mounted partition {part} at {mount_point}; "
                f"assets at {subtree}.", "info")

            def cleanup():
                _run_host(["wsl", "--unmount", device_path], timeout=30)
                _set_disk_offline(disk_num, False)

            return mount_point, subtree, cleanup
        # Not the game partition — detach and try the next.
        _run_host(["wsl", "--unmount", device_path], timeout=20)

    _set_disk_offline(disk_num, False)
    raise RuntimeError(
        "Could not find a Dutch Pinball game partition on the selected "
        "drive (tried partitions: "
        f"{', '.join(map(str, candidates))}).\n"
        + (f"Last mount error: {last_err}\n" if last_err else "")
        + "Make sure you selected the game SSD and are running as "
          "Administrator.")


def _mount_linux(executor, device_path, read_only, log, partition_override):
    base = device_path.rstrip("0123456789")
    candidates = ([partition_override] if partition_override else [2, 1, 3, 4])
    mount_point = "/mnt/pad_dp_ssd"
    opts = "ro" if read_only else "rw"
    executor.run(f"mkdir -p {mount_point}", timeout=15)
    for part in candidates:
        dev = f"{base}{part}"
        try:
            executor.run(f"mount -o {opts} {dev} {mount_point}", timeout=30)
        except CommandError:
            continue
        subtree = find_game_subtree(executor, mount_point)
        if subtree:
            log(f"  Mounted {dev}; assets at {subtree}.", "info")

            def cleanup():
                try:
                    executor.run(f"umount {mount_point} 2>/dev/null; true",
                                 timeout=20)
                except Exception:
                    pass

            return mount_point, subtree, cleanup
        executor.run(f"umount {mount_point} 2>/dev/null; true", timeout=20)
    raise RuntimeError("Could not find a Dutch Pinball game partition on "
                       f"{device_path}.")


# ---------------------------------------------------------------------------
# Extract / Write
# ---------------------------------------------------------------------------

def extract_from_ssd(device_path, output_dir, executor,
                     partition_override=None,
                     log_cb=None, progress_cb=None, cancel_cb=None):
    """Copy the game asset subtree off the SSD into *output_dir*.

    Returns the number of files written.
    """
    def log(t, level="info"):
        if log_cb:
            log_cb(t, level)

    def progress(c, t, d=""):
        if progress_cb:
            progress_cb(c, t, d)

    progress(0, 3, "Mounting game SSD...")
    log("Mounting game SSD (read-only)...", "info")
    mount_point, subtree, cleanup = mount_game_ssd(
        executor, device_path, read_only=True, log=log,
        partition_override=partition_override)
    try:
        progress(1, 3, "Copying assets...")
        log(f"Streaming {subtree} -> output...", "info")
        os.makedirs(output_dir, exist_ok=True)
        proc = executor.popen_binary(f"tar cf - -C {mount_point}{subtree!r} .")
        n_files = 0
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                for m in tar:
                    if cancel_cb and cancel_cb():
                        raise RuntimeError("Cancelled.")
                    if not (m.isfile() or m.isdir()):
                        continue
                    safe = safe_member(m, output_dir)
                    if safe is None:
                        continue
                    tar.extract(safe, output_dir, set_attrs=False)
                    if m.isfile():
                        n_files += 1
                        if n_files % 50 == 0:
                            progress(1, 3, f"Copied {n_files} files...")
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass
            proc.wait()
        progress(3, 3, "Done")
        log(f"Extracted {n_files} asset file(s) from the SSD.", "success")
        return n_files
    finally:
        cleanup()
        log("SSD unmounted.", "info")


def write_to_ssd(device_path, changed_files, executor,
                 partition_override=None,
                 log_cb=None, progress_cb=None, cancel_cb=None):
    """Write *changed_files* (``[(rel_path, abs_host_path), ...]``) onto the SSD.

    Each file is copied to ``<subtree>/<rel_path>`` on the mounted partition.
    Returns the number of files written.
    """
    def log(t, level="info"):
        if log_cb:
            log_cb(t, level)

    def progress(c, t, d=""):
        if progress_cb:
            progress_cb(c, t, d)

    if not changed_files:
        log("No modified files to write.", "info")
        return 0

    progress(0, 3, "Mounting game SSD...")
    log("Mounting game SSD (read-write)...", "info")
    mount_point, subtree, cleanup = mount_game_ssd(
        executor, device_path, read_only=False, log=log,
        partition_override=partition_override)
    try:
        progress(1, 3, "Writing modified files...")
        total = len(changed_files)
        written = 0
        for i, (rel, abs_path) in enumerate(changed_files):
            if cancel_cb and cancel_cb():
                raise RuntimeError("Cancelled.")
            rel_norm = rel.replace("\\", "/").lstrip("/")
            if ".." in rel_norm.split("/"):
                log(f"  Skipping unsafe path: {rel}", "error")
                continue
            dest = f"{mount_point}{subtree}/{rel_norm}"
            src_exec = executor.to_exec_path(abs_path)
            executor.run(f"mkdir -p {os.path.dirname(dest)!r} && "
                         f"cp {src_exec!r} {dest!r}", timeout=300)
            written += 1
            progress(1, 3, f"Wrote {written}/{total}: {rel_norm}")
        log("Syncing writes to disk...", "info")
        executor.run("sync", timeout=60)
        progress(3, 3, "Done")
        log(f"Wrote {written} file(s) to the SSD.", "success")
        return written
    finally:
        cleanup()
        log("SSD unmounted.", "info")
