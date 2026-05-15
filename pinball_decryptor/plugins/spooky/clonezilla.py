"""Clonezilla restore image extraction.

Extracts game files from Spooky Pinball Clonezilla restore images.
Uses a platform-specific executor for Linux tools (partclone, debugfs):
- Windows: WSL2
- macOS: Docker container (Alpine)
- Linux: Native execution

Supported image types:
- Clonezilla ISO with zstd-compressed partclone images (BJ, ED, LT)
- Clonezilla ZIP with gzip/zstd-compressed partclone images (many games)
- Direct ext4 ISO (R&M autoflash)

Extraction pipeline:
1. Mount/extract ISO or ZIP to access partclone images (host-side)
2. Decompress (zstd or gzip) to get partclone image (executor)
3. partclone.restore to convert to raw ext4 (executor)
4. Extract files from raw ext4 via debugfs (executor)
"""

import os
import shutil
import subprocess
import sys
import tempfile

from .executor import CommandError, DockerExecutor


# Known partition layouts for each game.
# Multiple entries can exist per game when different hardware variants exist
# (e.g., eMMC mmcblk0 vs mmcblk1 vs SSD sda).
#
# The detect function matches filename patterns to the right entry.
PARTITION_MAP = {
    # --- Warden / SSD games (zstd, sda) ---
    "beetlejuice": {
        "device": "sda",
        "game_partition": "sda4",
        "fs_type": "ext4",
        "compression": "zstd",
        "game_paths": ["/code/uptest/main_Data/"],
        "description": "Beetlejuice game partition (Unity game + assets)",
    },
    "evil_dead": {
        "device": "sda",
        "game_partition": "sda4",
        "fs_type": "ext4",
        "compression": "zstd",
        "game_paths": ["/"],
        "description": "Evil Dead game partition",
    },

    # --- Scooby-Doo (eMMC, gzip) ---
    "scooby": {
        "device": "mmcblk1",
        "game_partition": "mmcblk1p3",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Scooby-Doo GAME partition",
    },

    # --- Texas Chainsaw Massacre (eMMC mmcblk0, gzip) ---
    "texas_chainsaw": {
        "device": "mmcblk0",
        "game_partition": "mmcblk0p3",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Texas Chainsaw Massacre game partition",
    },

    # --- Alice Cooper (eMMC mmcblk0, gzip) ---
    # 4 partitions: p1=vfat, p2=dd-img, p3=ext4, p4=ext4
    "alice_cooper": {
        "device": "mmcblk0",
        "game_partition": "mmcblk0p4",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Alice Cooper game partition",
    },

    # --- Legends of Tera: two hardware variants ---
    # LT_AK3V_CLONEZILLA_A: mmcblk1 (eMMC, gzip)
    "legends_of_tera_emmc1": {
        "device": "mmcblk1",
        "game_partition": "mmcblk1p3",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Legends of Tera game partition (eMMC mmcblk1)",
    },
    # LT_AK3V_CLONEZILLA_B: mmcblk1 (eMMC, zstd)
    "legends_of_tera_emmc1_zst": {
        "device": "mmcblk1",
        "game_partition": "mmcblk1p3",
        "fs_type": "ext4",
        "compression": "zstd",
        "game_paths": ["/"],
        "description": "Legends of Tera game partition (eMMC mmcblk1, zstd)",
    },
    # LT_clonezilla_kamrui: sda (SSD, zstd)
    "legends_of_tera_ssd": {
        "device": "sda",
        "game_partition": "sda4",
        "fs_type": "ext4",
        "compression": "zstd",
        "game_paths": ["/"],
        "description": "Legends of Tera game partition (SSD)",
    },

    # --- Halloween H78: three hardware variants ---
    # H78_Image_108a_128: sda (128GB SSD, gzip)
    "halloween_78_ssd": {
        "device": "sda",
        "game_partition": "sda3",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Halloween H78 game partition (SSD 128GB)",
    },
    # H78_Image_108a_64: mmcblk1 (64GB eMMC, gzip)
    "halloween_78_emmc1": {
        "device": "mmcblk1",
        "game_partition": "mmcblk1p3",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Halloween H78 game partition (eMMC mmcblk1)",
    },
    # h78_image_108a: mmcblk0 (eMMC, gzip)
    "halloween_78_emmc0": {
        "device": "mmcblk0",
        "game_partition": "mmcblk0p4",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Halloween H78 game partition (eMMC mmcblk0)",
    },

    # --- Ultraman: two hardware variants ---
    # UM_Image_64_108a: mmcblk1 (eMMC, gzip)
    "ultraman_emmc1": {
        "device": "mmcblk1",
        "game_partition": "mmcblk1p3",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Ultraman game partition (eMMC mmcblk1)",
    },
    # um_image_108a: mmcblk0 (eMMC, gzip)
    "ultraman_emmc0": {
        "device": "mmcblk0",
        "game_partition": "mmcblk0p4",
        "fs_type": "ext4",
        "compression": "gzip",
        "game_paths": ["/"],
        "description": "Ultraman game partition (eMMC mmcblk0)",
    },

    # --- Rick and Morty: raw ext4 filesystem image (not Clonezilla) ---
    "rick_and_morty": {
        "device": "raw",          # raw ext4 image, not partitioned
        "game_partition": "raw",
        "fs_type": "ext4",
        "compression": "none",    # no partclone/compression — use directly
        "game_paths": ["/"],
        "description": "Rick and Morty game partition (raw ext4)",
    },
}

# Map of game_key used in PARTITION_MAP → canonical game key used in GAME_DB
PARTITION_GAME_KEY = {
    "beetlejuice": "beetlejuice",
    "evil_dead": "evil_dead",
    "scooby": "scooby_doo",
    "texas_chainsaw": "texas_chainsaw",
    "alice_cooper": "alice_cooper",
    "legends_of_tera_emmc1": "legends_of_tera",
    "legends_of_tera_emmc1_zst": "legends_of_tera",
    "legends_of_tera_ssd": "legends_of_tera",
    "halloween_78_ssd": "halloween_78",
    "halloween_78_emmc1": "halloween_78",
    "halloween_78_emmc0": "halloween_78",
    "ultraman_emmc1": "ultraman",
    "ultraman_emmc0": "ultraman",
    "rick_and_morty": "rick_and_morty",
}


def check_prerequisites(executor=None):
    """Check all Clonezilla prerequisites for the given executor.

    Args:
        executor: A CommandExecutor instance. If None, creates one for the
                  current platform.

    Returns list of (name, passed, message) tuples.
    """
    if executor is None:
        from .executor import create_executor
        executor = create_executor()

    results = []

    # Check executor backend is available
    ok, msg = executor.check_available()
    backend_name = type(executor).__name__.replace("Executor", "")
    if not ok:
        results.append((backend_name, False, msg))
        results.append(("partclone", False, f"Requires {backend_name}"))
        results.append(("debugfs", False, f"Requires {backend_name}"))
        results.append(("zstandard", False, f"Requires {backend_name}"))
        return results
    results.append((backend_name, True, "Available"))

    # For Docker executor, start a temp container to check tools
    if isinstance(executor, DockerExecutor):
        try:
            executor.start_container()
        except CommandError as e:
            results.append(("Docker container", False, str(e)))
            return results

    # Check required tools inside executor
    for tool, display_name, install_cmd in [
        ("partclone.restore", "partclone", "apk add partclone / apt install partclone"),
        ("debugfs", "debugfs", "apk add e2fsprogs-extra / apt install e2fsprogs"),
    ]:
        try:
            executor.run(f"which {tool}", timeout=10)
            results.append((display_name, True, "Available"))
        except CommandError:
            results.append((display_name, False,
                            f"Not found. Install: {install_cmd}"))
        except Exception:
            results.append((display_name, False, f"Could not check for {tool}"))

    # Check for zstd decompression
    try:
        executor.run("python3 -c 'import zstandard; print(\"ok\")'", timeout=10)
        results.append(("zstandard", True, "Available"))
    except CommandError:
        # Try zstd CLI as fallback
        try:
            executor.run("which zstd", timeout=10)
            results.append(("zstandard", True, "Available (CLI)"))
        except CommandError:
            results.append(("zstandard", False,
                            "Not found. Install: pip3 install zstandard"))
    except Exception:
        results.append(("zstandard", False, "Could not check for zstandard"))

    # Stop temp container if we started one
    if isinstance(executor, DockerExecutor):
        executor.stop_container()

    return results


def check_errors(executor=None):
    """Check if prerequisites are met. Returns list of error strings (empty = OK)."""
    results = check_prerequisites(executor)
    return [msg for _, passed, msg in results if not passed]


# Keep backward compat alias
check_wsl = check_errors


def _exec_run(executor, cmd, timeout=120, log_cb=None):
    """Run a command via the executor and return stdout (stripped)."""
    if log_cb:
        log_cb(f"$ {cmd}", "info")
    try:
        result = executor.run(cmd, timeout=timeout)
        return result.strip() if result else ""
    except CommandError as e:
        if log_cb and e.output:
            log_cb(f"  stderr: {e.output}", "warning")
        return ""


# Filename patterns for Clonezilla image detection.
# (pattern, partition_key)  — pattern matched case-insensitively against basename.
_CLONEZILLA_PATTERNS = [
    ("bj_",                   "beetlejuice"),
    ("beetlejuice",           "beetlejuice"),
    ("ed_clonezilla",         "evil_dead"),
    ("evil_dead",             "evil_dead"),
    ("scooby",                "scooby"),
    ("tcm_prod",              "texas_chainsaw"),
    ("tcm",                   "texas_chainsaw"),
    ("acnc",                  "alice_cooper"),
    ("ac-",                   "alice_cooper"),
    # LT variants — order matters, most specific first
    ("lt_ak3v_clonezilla_b",  "legends_of_tera_emmc1_zst"),
    ("lt_ak3v_clonezilla_a",  "legends_of_tera_emmc1"),
    ("lt_clonezilla_kamrui",  "legends_of_tera_ssd"),
    ("lt_",                   "legends_of_tera_emmc1"),  # default LT
    # H78 variants
    ("h78_image_108a_128",    "halloween_78_ssd"),
    ("h78_image_108a_64",     "halloween_78_emmc1"),
    ("h78_image_108a",        "halloween_78_emmc0"),
    ("h78_image",             "halloween_78_ssd"),  # default
    ("h78",                   "halloween_78_ssd"),
    # UM variants
    ("um_image_64",           "ultraman_emmc1"),
    ("um_image_108a",         "ultraman_emmc0"),
    ("um_image",              "ultraman_emmc1"),  # default
    ("um_",                   "ultraman_emmc1"),
    # R&M (raw ext4 filesystem image)
    ("rick_and_morty",        "rick_and_morty"),
    ("r_m",                   "rick_and_morty"),
    ("rm_",                   "rick_and_morty"),
    # AMH
    ("amh",                   None),
]


def detect_clonezilla_game(image_path):
    """Detect which Spooky game a Clonezilla image belongs to.

    Args:
        image_path: Path to .iso or .zip file.

    Returns:
        (partition_key, partition_info) tuple, or (None, None) if not recognized.
        partition_key maps to PARTITION_MAP keys.
    """
    basename = os.path.basename(image_path).lower()

    for pattern, part_key in _CLONEZILLA_PATTERNS:
        if pattern in basename:
            if part_key is None:
                return None, None  # known but no partition map (AMH)
            part_info = PARTITION_MAP.get(part_key)
            return part_key, part_info

    return None, None


def get_game_key_for_partition(partition_key):
    """Map a partition key to the canonical game key from GAME_DB."""
    return PARTITION_GAME_KEY.get(partition_key, partition_key)


def _mount_iso_host(image_path, log_cb=None):
    """Mount an ISO on the host OS. Returns (mount_point_or_drive, cleanup_fn).

    Windows: PowerShell Mount-DiskImage → drive letter
    macOS: hdiutil attach → mount point
    Linux: mount -o loop → mount point
    """
    if sys.platform == "win32":
        return _mount_iso_windows(image_path, log_cb)
    elif sys.platform == "darwin":
        return _mount_iso_macos(image_path, log_cb)
    else:
        return _mount_iso_linux(image_path, log_cb)


def _mount_iso_windows(image_path, log_cb=None):
    """Mount ISO via PowerShell. Returns (drive_letter + ":\\", cleanup_fn)."""
    _CREATE_FLAGS = subprocess.CREATE_NO_WINDOW

    mount_result = subprocess.run(
        ["powershell", "-Command",
         f'Mount-DiskImage -ImagePath "{image_path}" -PassThru | '
         f'Get-Volume | Select-Object -ExpandProperty DriveLetter'],
        capture_output=True, text=True, timeout=30,
        creationflags=_CREATE_FLAGS)

    if mount_result.returncode != 0:
        raise RuntimeError(f"Failed to mount ISO: {mount_result.stderr}")

    drive_letter = mount_result.stdout.strip()
    if not drive_letter:
        mount_result2 = subprocess.run(
            ["powershell", "-Command",
             f'(Get-DiskImage -ImagePath "{image_path}" | Get-Volume).DriveLetter'],
            capture_output=True, text=True, timeout=10,
            creationflags=_CREATE_FLAGS)
        drive_letter = mount_result2.stdout.strip()

    if not drive_letter:
        raise RuntimeError("ISO mounted but could not determine drive letter")

    mount_point = f"{drive_letter}:\\"

    def cleanup():
        try:
            subprocess.run(
                ["powershell", "-Command",
                 f'Dismount-DiskImage -ImagePath "{image_path}"'],
                capture_output=True, timeout=10,
                creationflags=_CREATE_FLAGS)
        except Exception:
            pass

    return mount_point, cleanup


def _mount_iso_macos(image_path, log_cb=None):
    """Mount ISO via hdiutil. Returns (mount_point, cleanup_fn)."""
    result = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-readonly", image_path],
        capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to mount ISO: {result.stderr}")

    # Parse hdiutil output — last column of last line is mount point
    mount_point = None
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            mount_point = parts[-1].strip()
            device = parts[0].strip()

    if not mount_point:
        raise RuntimeError("ISO mounted but could not determine mount point")

    def cleanup():
        try:
            subprocess.run(
                ["hdiutil", "detach", device],
                capture_output=True, timeout=30)
        except Exception:
            pass

    return mount_point, cleanup


def _mount_iso_linux(image_path, log_cb=None):
    """Mount ISO via loop mount. Returns (mount_point, cleanup_fn)."""
    mount_point = tempfile.mkdtemp(prefix="spooky_iso_")
    result = subprocess.run(
        ["sudo", "mount", "-o", "loop,ro", image_path, mount_point],
        capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        os.rmdir(mount_point)
        raise RuntimeError(f"Failed to mount ISO: {result.stderr}")

    def cleanup():
        try:
            subprocess.run(
                ["sudo", "umount", mount_point],
                capture_output=True, timeout=30)
            os.rmdir(mount_point)
        except Exception:
            pass

    return mount_point, cleanup


def _find_partclone_in_dir(search_root, search_files):
    """Walk a directory tree to find a partclone image file.

    Returns (found_path, found_filename) or raises FileNotFoundError.
    """
    for root, dirs, files in os.walk(search_root):
        for target in search_files:
            if target in files:
                return os.path.join(root, target), target
    raise FileNotFoundError(
        f"Could not find {search_files[0]} in {search_root}")


def extract_clonezilla(image_path, output_dir, executor, game_key=None,
                       progress_cb=None, log_cb=None, indeterminate_cb=None):
    """Extract game files from a Clonezilla restore image.

    Args:
        image_path: Path to Clonezilla .iso or .zip file.
        output_dir: Directory to extract files into.
        executor: CommandExecutor for running Linux tools.
        game_key: Optional partition key (auto-detected if None).
        progress_cb: Optional callback(step, total_steps, description).
        log_cb: Optional callback(text, level).
        indeterminate_cb: Optional callback(description) for bouncing progress.

    Returns:
        List of extracted file paths (relative to output_dir).
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    def progress(step, total, desc=""):
        if progress_cb:
            progress_cb(step, total, desc)

    def indeterminate(desc=""):
        if indeterminate_cb:
            indeterminate_cb(desc)

    # Auto-detect game
    if game_key is None:
        game_key, part_info = detect_clonezilla_game(image_path)
        if game_key is None:
            raise ValueError(
                f"Cannot identify game from filename: {os.path.basename(image_path)}")
    else:
        part_info = PARTITION_MAP.get(game_key)

    if part_info is None:
        raise ValueError(f"No partition map for game: {game_key}")

    log(f"Game: {part_info['description']}")
    log(f"Target partition: {part_info['game_partition']}")
    log(f"Compression: {part_info['compression']}")

    # Start Docker container if needed
    if isinstance(executor, DockerExecutor):
        log("Starting Docker container...")
        executor.start_container([image_path, output_dir])

    # Raw ext4 images (e.g. R&M autoflash ISO) skip decompression + partclone
    if part_info["compression"] == "none":
        return _extract_raw_ext4(
            image_path, output_dir, part_info, executor,
            progress_cb=progress_cb, log_cb=log_cb,
            indeterminate_cb=indeterminate_cb)

    total_steps = 4
    ext = os.path.splitext(image_path)[1].lower()

    # Step 1: Find the partclone image
    progress(1, total_steps, "Locating partition image...")
    log("Step 1: Finding partition image in archive...")

    partclone_img = part_info["game_partition"]
    if part_info["compression"] == "zstd":
        partclone_file = f"{partclone_img}.{part_info['fs_type']}-ptcl-img.zst"
        # Some zstd images split into .zst.aa
        partclone_file_alt = f"{partclone_file}.aa"
    else:
        partclone_file = f"{partclone_img}.{part_info['fs_type']}-ptcl-img.gz.aa"
        partclone_file_alt = None

    search_files = [partclone_file]
    if partclone_file_alt:
        search_files.append(partclone_file_alt)

    iso_cleanup = None
    temp_dir = None

    try:
        if ext == ".iso":
            log("Mounting ISO...")
            mount_point, iso_cleanup = _mount_iso_host(image_path, log_cb)
            log(f"ISO mounted at {mount_point}")

            source_path, partclone_file = _find_partclone_in_dir(
                mount_point, search_files)
            log(f"Found: {source_path}")

        elif ext == ".zip":
            import zipfile
            log("Extracting partition image from ZIP...")

            with zipfile.ZipFile(image_path, "r") as zf:
                matching = []
                for target in search_files:
                    matching = [n for n in zf.namelist() if n.endswith(target)]
                    if matching:
                        break

                if not matching:
                    raise FileNotFoundError(
                        f"Could not find partition image for {partclone_img} in ZIP.\n"
                        f"Searched for: {', '.join(search_files)}")

                zip_member = matching[0]
                log(f"Extracting {zip_member}...")

                temp_dir = tempfile.mkdtemp(prefix="spooky_cz_")
                zf.extract(zip_member, temp_dir)
                source_path = os.path.join(temp_dir, zip_member)

        else:
            raise ValueError(f"Unsupported archive format: {ext}")

        exec_source = executor.to_exec_path(source_path)

        # Step 2: Decompress to partclone image
        progress(2, total_steps, "Decompressing partition image...")
        log("Step 2: Decompressing partition image...")

        exec_tmp = "/tmp/spooky_partclone_decompressed"
        exec_raw = "/tmp/spooky_raw.img"

        # Clean up any previous files
        _exec_run(executor, f"rm -f {exec_tmp} {exec_raw}", log_cb=log)

        if part_info["compression"] == "zstd":
            log("Decompressing zstd (this may take several minutes)...")
            indeterminate("Decompressing zstd...")
            # Try python zstandard first, fall back to zstd CLI
            try:
                _exec_run(executor,
                    f'python3 -c "'
                    f"import zstandard as zstd; "
                    f"dctx = zstd.ZstdDecompressor(); "
                    f"dctx.copy_stream("
                    f"  open('{exec_source}', 'rb'), "
                    f"  open('{exec_tmp}', 'wb'))"
                    f'"',
                    timeout=600, log_cb=log)
            except CommandError:
                _exec_run(executor,
                    f"zstd -d -o {exec_tmp} '{exec_source}'",
                    timeout=600, log_cb=log)
        else:
            log("Decompressing gzip...")
            indeterminate("Decompressing gzip...")
            _exec_run(executor,
                f"gunzip -c '{exec_source}' > {exec_tmp}",
                timeout=600, log_cb=log)

        size = _exec_run(executor, f"stat -c%s {exec_tmp} 2>/dev/null")
        if size:
            log(f"Decompressed size: {int(size) / (1024**3):.2f} GB")

        # Step 3: Restore to raw ext4
        progress(3, total_steps, "Restoring to raw ext4...")
        log("Step 3: Running partclone.restore...")
        indeterminate("Restoring partition image...")

        _exec_run(executor,
            f"partclone.restore -C -L /tmp/partclone.log -s {exec_tmp} -o {exec_raw}",
            timeout=600, log_cb=log)

        raw_size = _exec_run(executor, f"stat -c%s {exec_raw} 2>/dev/null")
        if raw_size:
            log(f"Raw ext4 size: {int(raw_size) / (1024**3):.2f} GB")
        else:
            raise RuntimeError(
                "partclone.restore failed to create raw image. "
                "Check that partclone is installed correctly.")

        # Clean up decompressed partclone image
        _exec_run(executor, f"rm -f {exec_tmp}")

        # Step 4: Extract files from raw ext4
        progress(4, total_steps, "Extracting files from ext4...")
        log("Step 4: Extracting files via debugfs...")
        indeterminate("Extracting files from ext4...")

        os.makedirs(output_dir, exist_ok=True)

        extracted = []
        for game_path in part_info["game_paths"]:
            files = _extract_ext4_recursive(
                exec_raw, game_path, output_dir, executor,
                progress_cb=progress_cb, log_cb=log)
            extracted.extend(files)

        log(f"Extracted {len(extracted)} files total", "success")
        return extracted

    finally:
        # Cleanup host-side resources
        if iso_cleanup:
            try:
                iso_cleanup()
                log("ISO unmounted")
            except Exception:
                pass
        if temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


def _extract_raw_ext4(image_path, output_dir, part_info, executor,
                      progress_cb=None, log_cb=None, indeterminate_cb=None):
    """Extract files from a raw ext4 filesystem image (no partclone/compression).

    Used for images like the R&M autoflash ISO which is a bare ext4 filesystem
    (not ISO 9660, no partition table, no partclone).
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    def progress(step, total, desc=""):
        if progress_cb:
            progress_cb(step, total, desc)

    def indeterminate(desc=""):
        if indeterminate_cb:
            indeterminate_cb(desc)

    total_steps = 2

    # Step 1: Convert path for executor
    progress(1, total_steps, "Preparing raw ext4 image...")
    log("Step 1: Raw ext4 image — skipping decompress + partclone")
    exec_image = executor.to_exec_path(image_path)
    log(f"Executor path: {exec_image}")

    # Step 2: Extract files directly via debugfs
    progress(2, total_steps, "Extracting files from ext4...")
    log("Step 2: Extracting files via debugfs...")
    indeterminate("Extracting files from ext4...")

    os.makedirs(output_dir, exist_ok=True)

    extracted = []
    for game_path in part_info["game_paths"]:
        files = _extract_ext4_recursive(
            exec_image, game_path, output_dir, executor,
            progress_cb=progress_cb, log_cb=log)
        extracted.extend(files)

    log(f"Extracted {len(extracted)} files total", "success")
    return extracted


def _extract_ext4_recursive(exec_raw_img, base_path, output_dir, executor,
                            progress_cb=None, log_cb=None):
    """Recursively extract files from an ext4 image via debugfs.

    Uses debugfs 'rdump' for bulk extraction.
    """
    def log(text, level="info"):
        if log_cb:
            log_cb(text, level)

    exec_output = executor.to_exec_path(output_dir)

    # Use debugfs rdump for recursive extraction
    base = base_path.rstrip("/")
    if not base:
        base = "/"

    log(f"Extracting {base} ...")
    try:
        _exec_run(executor,
            f'debugfs -R "rdump \\"{base}\\" \\"{exec_output}\\"" {exec_raw_img} 2>/dev/null',
            timeout=600, log_cb=None)
    except (CommandError, subprocess.TimeoutExpired):
        log("rdump timed out — trying file-by-file extraction", "warning")

    # List what was extracted
    extracted = []
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, output_dir)
            extracted.append(rel)

    return extracted


def cleanup_temp_files(executor=None, log_cb=None):
    """Remove temporary extraction files from executor."""
    if executor is None:
        return
    for f in ["/tmp/spooky_partclone_decompressed", "/tmp/spooky_raw.img"]:
        try:
            executor.run(f"rm -f {f}", timeout=10)
            if log_cb:
                log_cb(f"Removed {f}", "info")
        except Exception:
            pass
