"""Clonezilla restore-image extraction — manufacturer-agnostic.

The caller (typically a plugin's IsoExtractPipeline) supplies:
  * the partition to extract (or None to auto-pick the largest ext4)
  * the subtrees to dump (e.g. ["/game", "/opt/game"])

Step 3 and 4 require Linux tools (``partclone.dd``, ``debugfs``,
``gunzip``).  We delegate via the platform-aware executor.
"""

import os
import subprocess
import sys
import tempfile

from .executor import CommandError


# ---------------------------------------------------------------------------
# ISO mounting
# ---------------------------------------------------------------------------

def mount_iso(image_path, executor=None, log_cb=None):
    """Mount an ISO; return ``(host_mount, exec_mount, cleanup_fn)``."""
    if sys.platform == "win32":
        if executor is None:
            raise ValueError("Executor is required on Windows")
        return _mount_via_wsl(image_path, executor, log_cb)
    if sys.platform == "darwin":
        return _mount_macos(image_path, log_cb)
    return _mount_linux(image_path, log_cb)


def _mount_via_wsl(image_path, executor, log_cb):
    iso_exec = executor.to_exec_path(image_path)
    exec_mount = "/tmp/pad_iso"
    distro = "Ubuntu"
    try:
        out = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        if "\x00" in out:
            out = out.encode("latin-1").decode("utf-16-le", errors="replace")
        for line in out.splitlines():
            ln = line.strip()
            if ln and not ln.startswith("Windows"):
                distro = ln
                break
    except Exception:
        pass

    host_mount = f"\\\\wsl.localhost\\{distro}\\tmp\\pad_iso"

    executor.run(
        f"umount {exec_mount} 2>/dev/null; mkdir -p {exec_mount}",
        timeout=15,
    )
    executor.run(
        f"mount -o loop,ro {iso_exec!r} {exec_mount}",
        timeout=60,
    )

    def cleanup():
        try:
            executor.run(f"umount {exec_mount} 2>/dev/null; true", timeout=15)
        except Exception:
            pass

    return host_mount, exec_mount, cleanup


def _mount_macos(image_path, log_cb):
    res = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", image_path],
        capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"hdiutil attach failed: {res.stderr}")
    mount_point = device = None
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            mount_point = parts[-1].strip()
            device = parts[0].strip()
    if not mount_point:
        raise RuntimeError("hdiutil mounted ISO but no mount point reported")

    def cleanup():
        try:
            subprocess.run(["hdiutil", "detach", device],
                           capture_output=True, timeout=30)
        except Exception:
            pass

    return mount_point, mount_point, cleanup


def _mount_linux(image_path, log_cb):
    mount_point = tempfile.mkdtemp(prefix="pad_iso_")
    res = subprocess.run(
        ["sudo", "mount", "-o", "loop,ro", image_path, mount_point],
        capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        os.rmdir(mount_point)
        raise RuntimeError(f"mount failed: {res.stderr}")

    def cleanup():
        try:
            subprocess.run(["sudo", "umount", mount_point],
                           capture_output=True, timeout=30)
            os.rmdir(mount_point)
        except Exception:
            pass

    return mount_point, mount_point, cleanup


# ---------------------------------------------------------------------------
# Partition discovery
# ---------------------------------------------------------------------------

def find_image_dir(mount_point):
    candidate = os.path.join(mount_point, "home", "partimag")
    if not os.path.isdir(candidate):
        return None
    for entry in sorted(os.listdir(candidate)):
        full = os.path.join(candidate, entry)
        if os.path.isdir(full):
            return full
    return None


def read_parts(image_dir):
    parts_file = os.path.join(image_dir, "parts")
    if not os.path.isfile(parts_file):
        return []
    with open(parts_file, "r", encoding="utf-8") as f:
        return f.read().split()


def read_blkdev_list(image_dir):
    f_path = os.path.join(image_dir, "blkdev.list")
    if not os.path.isfile(f_path):
        return []
    rows = []
    with open(f_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines or not lines[0].lower().startswith("kname"):
        return []
    headers = [h.lower() for h in lines[0].split()]
    for ln in lines[1:]:
        cols = ln.split()
        if len(cols) < 4:
            continue
        try:
            name = cols[headers.index("name")] if "name" in headers else cols[1]
            size = cols[headers.index("size")] if "size" in headers else cols[2]
            type_ = cols[headers.index("type")] if "type" in headers else cols[3]
            fstype = (cols[headers.index("fstype")]
                      if "fstype" in headers and len(cols) > headers.index("fstype")
                      else "")
        except (ValueError, IndexError):
            continue
        clean_name = name.lstrip("|`-")
        rows.append({
            "name": clean_name,
            "size_bytes": _parse_size(size),
            "type": type_,
            "fstype": fstype,
        })
    return rows


def _parse_size(size_str):
    s = size_str.strip().upper()
    if not s:
        return 0
    suffix = s[-1]
    multipliers = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    if suffix in multipliers:
        try:
            return int(float(s[:-1]) * multipliers[suffix])
        except ValueError:
            return 0
    try:
        return int(s)
    except ValueError:
        return 0


def pick_game_partition(image_dir, preferred_partition=None):
    parts = read_parts(image_dir)
    blk = read_blkdev_list(image_dir)

    if preferred_partition and preferred_partition in parts:
        return preferred_partition

    candidates = [
        (r["size_bytes"], r["name"])
        for r in blk
        if r["name"] in parts and r.get("fstype", "").lower() in ("ext4",)
    ]
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    sized = [(r["size_bytes"], r["name"]) for r in blk if r["name"] in parts]
    if sized:
        sized.sort(reverse=True)
        return sized[0][1]
    return None


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def check_prerequisites(executor):
    results = []
    ok, msg = executor.check_available()
    backend = type(executor).__name__.replace("Executor", "")
    results.append((backend, ok, msg))
    if not ok:
        for tool in ("debugfs", "gunzip"):
            results.append((tool, False, f"requires {backend}"))
        return results

    for tool, label, install_hint in [
        ("debugfs", "debugfs", "apt-get install e2fsprogs"),
        ("gunzip", "gunzip", "(part of gzip — usually pre-installed)"),
    ]:
        try:
            executor.run(f"command -v {tool} >/dev/null 2>&1", timeout=10)
            results.append((label, True, "available"))
        except CommandError:
            results.append((label, False, f"not found — install: {install_hint}"))
        except Exception:
            results.append((label, False, f"could not check for {tool}"))
    return results


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract(iso_path, output_dir, executor,
            preferred_partition=None,
            subtrees=("/game", "/opt/game"),
            display_name=None,
            log_cb=None, progress_cb=None):
    """Extract subtrees from a Clonezilla ISO into *output_dir*.

    Args:
        iso_path: Path to the .iso.
        output_dir: Host directory to extract files into.
        executor: A :class:`CommandExecutor` (WSL/Mac/Native).
        preferred_partition: Optional partition name (e.g. ``"sda2"``).
            If unset or not present in the ISO, picks the largest ext4
            partition.
        subtrees: Iterable of absolute paths inside the partition to
            ``rdump``.  Only those that exist are extracted.
        display_name: Optional name for log messages.
        log_cb / progress_cb: standard callbacks.

    Returns the partition name that was extracted.
    """
    def log(t, level="info"):
        if log_cb:
            log_cb(t, level)

    def progress(c, t, d=""):
        if progress_cb:
            progress_cb(c, t, d)

    name = display_name or os.path.basename(iso_path)

    progress(0, 4, "Mounting ISO...")
    log("Mounting ISO...", "info")
    host_mount, exec_mount, unmount = mount_iso(
        iso_path, executor=executor, log_cb=log)
    log(f"  Mounted at {host_mount}", "info")

    try:
        progress(1, 4, "Locating partition image...")
        image_dir = find_image_dir(host_mount)
        if not image_dir:
            raise RuntimeError(
                f"Could not find home/partimag/* inside {os.path.basename(iso_path)}.\n"
                f"This does not look like a Clonezilla restore ISO.")
        image_name = os.path.basename(image_dir)
        log(f"  Image directory: home/partimag/{image_name}/", "info")

        partition = pick_game_partition(image_dir, preferred_partition)
        if not partition:
            raise RuntimeError(
                f"Could not identify a game partition inside {image_name}.\n"
                f"Inspect manually: home/partimag/{image_name}/parts")
        log(f"  Using partition: {partition}", "info")

        prefix = f"{partition}.dd-ptcl-img.gz."
        segments = sorted(
            f for f in os.listdir(image_dir) if f.startswith(prefix)
        )
        if not segments:
            raise RuntimeError(
                f"No partclone images found for {partition} in {image_dir}.\n"
                f"Expected files like {partition}.dd-ptcl-img.gz.aa")
        log(f"  Found {len(segments)} segment(s): {', '.join(segments)}",
            "info")

        progress(2, 4, "Decompressing partition image...")
        log("Decompressing partition image (this can take several minutes)...",
            "info")

        image_dir_exec = f"{exec_mount}/home/partimag/{image_name}"
        raw_path_exec = "/tmp/pad_raw.img"
        cat_pattern = f"{image_dir_exec}/{partition}.dd-ptcl-img.gz.*"
        cmd = (
            f"set -o pipefail && "
            f"rm -f {raw_path_exec} && "
            f"cat {cat_pattern} | gunzip -c > {raw_path_exec}"
        )
        try:
            executor.run(cmd, timeout=7200)
        except CommandError as e:
            raise RuntimeError(
                f"Decompression failed:\n{e.output}\n\n"
                f"Make sure 'gzip' is installed in the executor environment.")

        try:
            size = executor.run(
                f"stat -c%s {raw_path_exec} 2>/dev/null || echo 0",
                timeout=10,
            ).strip()
            log(f"  Raw partition size: {int(size) / (1024 ** 3):.2f} GiB",
                "info")
        except Exception:
            pass

        progress(3, 4, "Extracting files from ext4...")
        log("Extracting game files via debugfs rdump...", "info")
        os.makedirs(output_dir, exist_ok=True)
        out_exec = executor.to_exec_path(output_dir)

        found = []
        for cand in subtrees:
            try:
                executor.run(
                    f'debugfs -R \'stat "{cand}"\' {raw_path_exec} 2>/dev/null '
                    f'| grep -q "^Inode: "',
                    timeout=30,
                )
                found.append(cand)
            except CommandError:
                continue

        if not found:
            raise RuntimeError(
                f"None of the expected subtrees exist in the partition: "
                f"{', '.join(subtrees)}.\n"
                f"This doesn't look like a {name} Clonezilla image; if you need "
                f"the full filesystem dump, run debugfs rdump manually.")

        log(f"  Extracting subtree(s): {', '.join(found)}", "info")

        for cand in found:
            debug_cmd = (
                f'debugfs -R \'rdump "{cand}" "{out_exec}"\' {raw_path_exec} '
                f'2>&1 | grep -v "^debugfs " | head -200'
            )
            try:
                for line in executor.stream(debug_cmd, timeout=7200):
                    line = line.strip()
                    if line:
                        log(f"  {line}", "info")
            except CommandError as e:
                n = sum(len(fs) for _, _, fs in os.walk(output_dir))
                if n == 0:
                    raise RuntimeError(f"debugfs rdump failed: {e.output}")

        try:
            executor.run(f"rm -f {raw_path_exec}", timeout=10)
        except Exception:
            pass

        n_files = sum(len(fs) for _, _, fs in os.walk(output_dir))
        log(f"Extracted {n_files} files.", "success")
        progress(4, 4, "Done")
        return partition

    finally:
        try:
            unmount()
            log("ISO unmounted.", "info")
        except Exception:
            pass
