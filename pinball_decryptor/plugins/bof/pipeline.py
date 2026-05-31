"""Decrypt and modify pipelines for BOF Asset Decryptor."""

import hashlib
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import zipfile

from .games import (
    GAME_DB, FUN_FILE_TO_GAME, DECRYPT_PHASES, MODIFY_PHASES,
    GPG_DECRYPT_TIMEOUT, TAR_EXTRACT_TIMEOUT, GDRE_TIMEOUT,
    CHECKSUM_TIMEOUT, GPG_ENCRYPT_TIMEOUT, TAR_PACK_TIMEOUT,
)
from .executor import CommandError

CHECKSUMS_FILE = ".checksums.md5"

# BOF's newer Godot builds (May 2026 onward) rename the embedded PCK magic
# from the stock "GDPC" to "GBOF" — likely to defeat off-the-shelf tools
# like GDRE.  The PCK format is otherwise identical, so a 4-byte swap at the
# header and trailer offsets is enough to make tools recognise it again.
# DecryptPipeline patches the output binary (so the user / GDRE can browse
# the PCK); ModifyPipeline patches the in-flight temp binary before calling
# GDRE and then swaps the new binary back to GBOF before re-packaging so the
# game still loads its PCK on the real machine.
_BOF_PCK_MAGIC = b"GBOF"
_GODOT_PCK_MAGIC = b"GDPC"

# Inline python3 script executed via the shell to swap the 4-byte PCK magic
# at both occurrences (PCK header + trailer) in an embedded-PCK Godot binary.
# Returns one of:  "patched:..." | "skip:..." | "error:..."
_PATCH_MAGIC_SCRIPT = r"""
import os, struct, sys
path, from_m, to_m = sys.argv[1], sys.argv[2].encode(), sys.argv[3].encode()
size = os.path.getsize(path)
if size < 12:
    print("skip:too_small"); sys.exit(0)
with open(path, "r+b") as f:
    f.seek(size - 4); trailer = f.read(4)
    if trailer == to_m:
        print("skip:already_" + to_m.decode()); sys.exit(0)
    if trailer != from_m:
        print("skip:trailer=" + repr(trailer)); sys.exit(0)
    f.seek(size - 12); pck_size = struct.unpack("<Q", f.read(8))[0]
    header_off = size - 12 - pck_size
    if header_off < 0 or header_off >= size - 12:
        print("skip:bad_offset=" + str(header_off)); sys.exit(0)
    f.seek(header_off); header = f.read(4)
    if header != from_m:
        print("skip:header=" + repr(header)); sys.exit(0)
    f.seek(header_off); f.write(to_m)
    f.seek(size - 4); f.write(to_m)
print("patched:offset=" + str(header_off) + ",size=" + str(pck_size))
"""


def _patch_pck_magic(executor, exec_path, from_magic, to_magic, log_cb=None):
    """Swap the Godot PCK magic in *exec_path* (a path on the executor's
    filesystem) from *from_magic* to *to_magic*.  Both magics must be exactly
    4 printable ASCII bytes.

    Returns the raw status string from the helper script (caller may inspect
    or log).  Never raises — the patch is best-effort; if the binary doesn't
    have an embedded PCK or the magic doesn't match, this no-ops.
    """
    import base64 as _b64
    assert len(from_magic) == 4 and len(to_magic) == 4
    script_b64 = _b64.b64encode(_PATCH_MAGIC_SCRIPT.encode()).decode()
    from_s = from_magic.decode()
    to_s = to_magic.decode()
    try:
        out = executor.run(
            f"echo {script_b64!r} | base64 -d | "
            f"python3 - {exec_path!r} {from_s!r} {to_s!r} 2>&1",
            timeout=120,
        ).strip()
    except Exception as e:
        out = f"error:{e}"
    if log_cb:
        if out.startswith("patched"):
            log_cb(f"  Patched PCK magic {from_s} -> {to_s} ({out})", "info")
        elif out.startswith("skip:already_"):
            log_cb(f"  PCK magic already {to_s}, no patch needed.", "info")
        elif out.startswith("skip"):
            log_cb(f"  Skipped PCK magic patch: {out}", "info")
        else:
            log_cb(f"  PCK magic patch failed: {out}", "warning")
    return out


def _parse_import_remap(import_file_path):
    """Parse a Godot .import file and return the dest path (relative to pck root).

    Returns None if the file doesn't exist or has no remap path.
    """
    if not os.path.isfile(import_file_path):
        return None
    try:
        with open(import_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("path="):
                    path = line.split("=", 1)[1].strip('"').strip("'")
                    if path.startswith("res://"):
                        path = path[len("res://"):]
                    return path
    except Exception:
        pass
    return None

class _nullctx:
    """No-op context manager."""
    def __enter__(self): return self
    def __exit__(self, *exc): pass


class PipelineError(Exception):
    def __init__(self, phase, message):
        self.phase = phase
        self.message = message
        super().__init__(message)


class _BasePipeline:
    def __init__(self, log_cb, phase_cb, progress_cb, done_cb):
        self._log = log_cb
        self._phase_cb = phase_cb
        self._progress = progress_cb
        self._done = done_cb
        self._cancelled = False
        self.log_link = None  # optional: fn(text, url)

    def cancel(self):
        self._cancelled = True

    def _check_cancel(self):
        if self._cancelled:
            raise PipelineError("Cancelled", "Operation cancelled by user.")

    def _set_phase(self, index):
        self._phase_cb(index)

    def _poll_file_progress(self, wsl_path, expected_bytes, label=""):
        """Return a context manager that polls a WSL file's size in a
        background thread and updates the progress bar as a percentage
        of *expected_bytes*.  Stops automatically on ``__exit__``."""
        parent = self
        stop = threading.Event()

        def _poll():
            while not stop.is_set():
                try:
                    out = parent.executor.run(
                        f"stat -f%z {wsl_path!r} 2>/dev/null || stat -c%s {wsl_path!r} 2>/dev/null || echo 0",
                        timeout=5,
                    ).strip()
                    cur = int(out)
                except Exception:
                    cur = 0
                if expected_bytes > 0:
                    pct = min(int(100 * cur / expected_bytes), 99)
                    parent._progress(pct, 100,
                                     f"{label} {pct}%" if label else f"{pct}%")
                stop.wait(1.0)

        class _Ctx:
            def __enter__(self_ctx):
                self_ctx._t = threading.Thread(target=_poll, daemon=True)
                self_ctx._t.start()
                return self_ctx
            def __exit__(self_ctx, *exc):
                stop.set()
                self_ctx._t.join(timeout=3)

        return _Ctx()

    def _resolve_gpg(self):
        """Return full path to gpg, ensuring it's found even in macOS .app bundles."""
        # 1. On macOS/Linux: check common paths directly from Python (no bash)
        if sys.platform != "win32":
            for candidate in [
                "/opt/homebrew/bin/gpg",
                "/usr/local/bin/gpg",
                "/usr/local/MacGPG2/bin/gpg",
                "/opt/local/bin/gpg",
                "/usr/bin/gpg",
            ]:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate

        # 2. Ask the executor (goes through bash/WSL)
        try:
            path = self.executor.run(
                "command -v gpg 2>/dev/null || which gpg 2>/dev/null",
                timeout=10,
            ).strip()
            if path and path != "gpg":
                return path
        except Exception:
            pass
        return "gpg"  # last resort

    def _gdre_prefix(self):
        """Return the shell prefix to invoke GDRE Tools headlessly."""
        if sys.platform == "darwin":
            install_dir = os.path.expanduser("~/.local/share/gdre_tools")
            return (
                "GODOT_SILENCE_ROOT_WARNING=1 "
                f"'{install_dir}/Godot RE Tools' --headless "
            )
        # Linux / WSL: needs xvfb for headless display
        return (
            "DISPLAY= WAYLAND_DISPLAY= "
            "GODOT_SILENCE_ROOT_WARNING=1 "
            "LD_LIBRARY_PATH=/opt/gdre_tools "
            "xvfb-run -a /opt/gdre_tools/gdre_tools.x86_64 --headless "
        )

    def run(self):
        raise NotImplementedError


def check_prerequisites(executor):
    """Check that gpg is available in the executor environment.

    Returns a list of (name, passed, message) tuples.
    """
    results = []

    # Executor availability
    ok, msg = executor.check_available()
    executor_name = type(executor).__name__
    if "Wsl" in executor_name:
        label = "WSL2"
    elif "Mac" in executor_name:
        label = "macOS"
    else:
        label = "System"
    results.append((label, ok, msg))

    if not ok:
        return results

    # gpg — check common paths directly from Python first (avoids bash PATH issues)
    gpg_path = None
    if sys.platform != "win32":
        for candidate in [
            "/opt/homebrew/bin/gpg", "/usr/local/bin/gpg",
            "/usr/local/MacGPG2/bin/gpg", "/opt/local/bin/gpg", "/usr/bin/gpg",
        ]:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                gpg_path = candidate
                break
    if gpg_path:
        results.append(("gpg", True, gpg_path))
    else:
        try:
            executor.run("gpg --version > /dev/null 2>&1", timeout=10)
            gpg_path = executor.run(
                "command -v gpg 2>/dev/null || which gpg 2>/dev/null || echo gpg",
                timeout=10,
            ).strip()
            results.append(("gpg", True, gpg_path))
        except Exception:
            if sys.platform == "darwin":
                msg = "Not found — install with: brew install gnupg"
            else:
                msg = "Not found — install with: apt-get install gnupg"
            results.append(("gpg", False, msg))

    # tar
    try:
        executor.run("tar --version > /dev/null 2>&1", timeout=10)
        results.append(("tar", True, "available"))
    except Exception:
        results.append(("tar", False, "Not found — install with: apt-get install tar"))

    # gdre_tools (optional — for Godot PCK extraction)
    try:
        local_bin = os.path.expanduser("~/.local/bin/gdre_tools")
        path = executor.run(
            f"which gdre_tools 2>/dev/null || "
            f"(test -x '{local_bin}' && echo '{local_bin}') || "
            f"echo MISSING",
            timeout=10,
        ).strip()
        if "MISSING" in path or not path:
            results.append(("gdre_tools", False,
                            "Optional — click Install Missing to download automatically"))
        else:
            results.append(("gdre_tools", True, path.strip()))
    except Exception:
        results.append(("gdre_tools", False,
                        "Optional — click Install Missing to download automatically"))

    # cwebp (for texture reimport during Write)
    try:
        executor.run("cwebp -version > /dev/null 2>&1", timeout=5)
        results.append(("cwebp", True, "available"))
    except Exception:
        results.append(("cwebp", False,
                        "Optional — click Install Missing to download automatically"))

    return results


def detect_game(fun_path):
    """Return the game key for a given .fun file path, or None if unknown."""
    filename = os.path.basename(fun_path).lower()
    return FUN_FILE_TO_GAME.get(filename)


def export_mod_pack(assets_folder, zip_path, log_cb=None, progress_cb=None):
    """Package only modified files (per .checksums.md5) into a zip.

    Returns (num_changed, zip_path).
    """
    checksums_file = os.path.join(assets_folder, CHECKSUMS_FILE)
    if not os.path.isfile(checksums_file):
        raise FileNotFoundError(f"No {CHECKSUMS_FILE} found in {assets_folder}")

    baseline = {}
    with open(checksums_file, "r") as f:
        for line in f:
            line = line.strip()
            if "\t" in line:
                path, md5 = line.rsplit("\t", 1)
                baseline[path] = md5

    changed = []
    for rel_path, orig_md5 in baseline.items():
        abs_path = os.path.join(assets_folder, rel_path)
        if not os.path.isfile(abs_path):
            continue
        current_md5 = _md5_file(abs_path)
        if current_md5 != orig_md5:
            changed.append(rel_path)

    if not changed:
        raise ValueError("No modified files found. Modify some files first.")

    if log_cb:
        log_cb(f"Packing {len(changed)} modified file(s)...", "info")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, rel_path in enumerate(changed):
            abs_path = os.path.join(assets_folder, rel_path)
            zf.write(abs_path, rel_path)
            if progress_cb:
                progress_cb(i + 1, len(changed), rel_path)

    return len(changed), zip_path


def import_mod_pack(zip_path, assets_folder, log_cb=None, progress_cb=None):
    """Extract a mod pack zip into the assets folder. Returns number of files."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if log_cb:
            log_cb(f"Importing {len(names)} file(s)...", "info")
        for i, name in enumerate(names):
            zf.extract(name, assets_folder)
            if progress_cb:
                progress_cb(i + 1, len(names), name)
    return len(names)


def _md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_checksums(folder, log_cb, progress_cb):
    """Walk folder and write .checksums.md5. Returns file count."""
    files = []
    for dirpath, _, filenames in os.walk(folder):
        for fn in filenames:
            if fn.startswith("."):
                continue
            abs_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(abs_path, folder).replace("\\", "/")
            files.append((rel_path, abs_path))

    checksums_path = os.path.join(folder, CHECKSUMS_FILE)
    with open(checksums_path, "w") as out:
        for i, (rel_path, abs_path) in enumerate(files):
            md5 = _md5_file(abs_path)
            out.write(f"{rel_path}\t{md5}\n")
            if progress_cb:
                progress_cb(i + 1, len(files), rel_path)

    if log_cb:
        log_cb(f"Checksums written for {len(files)} file(s).", "success")
    return len(files)


# ---------------------------------------------------------------------------
# Decrypt pipeline
# ---------------------------------------------------------------------------

class DecryptPipeline(_BasePipeline):
    """GPG decrypt a .fun file and extract the Godot binary (and optionally unpack PCK)."""

    def __init__(self, fun_path, output_dir, executor,
                 log_cb, phase_cb, progress_cb, done_cb,
                 unpack_pck=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.fun_path = fun_path
        self.output_dir = output_dir
        self.executor = executor
        self.unpack_pck = unpack_pck
        self._tmp_dir = None

    def run(self):
        try:
            self._run()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            self._done(False, f"Unexpected error: {e}")

    def _run(self):
        # Phase 0 — Detect
        self._set_phase(0)
        self._log("Detecting game...", "info")
        game_key = detect_game(self.fun_path)
        if game_key is None:
            raise PipelineError("Detect",
                f"Unrecognised file: {os.path.basename(self.fun_path)}\n"
                f"Expected one of: {', '.join(FUN_FILE_TO_GAME.keys())}")
        game_info = GAME_DB[game_key]
        self._log(f"Game detected: {game_info['display']}", "success")
        self._check_cancel()

        # Verify output path is accessible from executor
        os.makedirs(self.output_dir, exist_ok=True)
        ok, msg = self.executor.check_path_accessible(self.output_dir)
        if not ok:
            raise PipelineError("Detect", msg)

        passphrase = game_info["passphrase"]
        fun_wsl = self.executor.to_exec_path(self.fun_path)
        out_wsl = self.executor.to_exec_path(self.output_dir)
        gpg_bin = self._resolve_gpg()
        self._log(f"Using gpg: {gpg_bin}", "info")

        # Phase 1 — Decrypt
        self._set_phase(1)
        self._log(f"Decrypting {os.path.basename(self.fun_path)} with GPG...", "info")
        self._progress(0, 100, "GPG decrypting...")

        fun_size = os.path.getsize(self.fun_path)
        tmp_tar_wsl = f"/tmp/bof_{game_key}.tar.gz"
        try:
            with self._poll_file_progress(tmp_tar_wsl, fun_size, "Decrypting..."):
                self.executor.run(
                    f"{gpg_bin} --batch --yes --passphrase={passphrase!r} "
                    f"--decrypt --output {tmp_tar_wsl!r} {fun_wsl!r} 2>&1",
                    timeout=GPG_DECRYPT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Decrypt",
                f"GPG decryption failed:\n{e.output}\n\n"
                f"Check that the .fun file is not corrupted.")
        self._log("GPG decryption complete.", "success")
        self._check_cancel()

        # Phase 2 — Extract tar
        self._set_phase(2)
        self._log("Extracting archive...", "info")
        self._progress(0, 100, "Extracting tar.gz...")

        # Get compressed size to estimate extraction progress.
        # Uncompressed is typically ~2x the .tar.gz; we poll du -sb on the
        # output directory vs that estimate.
        tar_size = 0
        try:
            tar_size = int(self.executor.run(
                f"stat -f%z {tmp_tar_wsl!r} 2>/dev/null || stat -c%s {tmp_tar_wsl!r} 2>/dev/null || echo 0",
                timeout=10,
            ).strip())
        except Exception:
            pass
        estimated_uncompressed = tar_size * 2 if tar_size else 0

        tmp_extract_wsl = f"/tmp/bof_{game_key}_extracted"
        try:
            self.executor.run(
                f"rm -rf {tmp_extract_wsl!r} && mkdir -p {tmp_extract_wsl!r}",
                timeout=30,
            )
            with self._poll_file_progress(
                tmp_extract_wsl, estimated_uncompressed, "Extracting..."
            ) if estimated_uncompressed else _nullctx():
                self.executor.run(
                    f"tar -xzf {tmp_tar_wsl!r} -C {tmp_extract_wsl!r} 2>&1",
                    timeout=TAR_EXTRACT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Extract", f"Archive extraction failed:\n{e.output}")

        # List extracted contents
        try:
            contents = self.executor.run(
                f"ls -lh {tmp_extract_wsl!r}", timeout=10
            ).strip()
            for line in contents.split("\n"):
                if line.strip():
                    self._log(f"  {line.strip()}", "info")
        except Exception:
            pass

        self._log("Archive extracted.", "success")
        self._check_cancel()

        # Copy extracted files to output directory
        self._log(f"Copying to output folder...", "info")
        try:
            self.executor.run(
                f"cp -r {tmp_extract_wsl!r}/. {out_wsl!r}/ 2>&1",
                timeout=120,
            )
        except CommandError as e:
            raise PipelineError("Extract", f"Copy to output failed:\n{e.output}")

        # Find the Godot binary
        binary_name = ""
        try:
            binary_name = self.executor.run(
                f"find {out_wsl!r} -name '*.x86_64' -type f | head -1",
                timeout=15,
            ).strip()
            if binary_name:
                size = self.executor.run(
                    f"du -h {binary_name!r} | cut -f1", timeout=10
                ).strip()
                self._log(f"Godot binary: {os.path.basename(binary_name)} ({size})",
                          "success")
        except Exception:
            pass

        # Patch BOF's custom "GBOF" PCK magic back to stock "GDPC" so the
        # output binary works with GDRE Tools and any other Godot tooling.
        # No-op for older BOF releases that still use GDPC.
        if binary_name:
            self._log("Checking PCK magic for BOF custom marker...", "info")
            _patch_pck_magic(self.executor, binary_name,
                             _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC, self._log)

        # Optional: unpack PCK
        if self.unpack_pck:
            self._set_phase(2)  # still in extract phase visually

            # First — check whether this is BOF's May 2026+ custom PCK
            # format.  If so, GDRE Tools can't read it and our own
            # may_extractor handles it natively.
            local_binary = (os.path.join(self.output_dir,
                                          os.path.basename(binary_name))
                            if binary_name else None)
            use_may_extractor = False
            if local_binary and os.path.isfile(local_binary):
                try:
                    from .may_extractor import is_may_format, find_pck_section
                    pck_start, pck_end = find_pck_section(local_binary)
                    # Read just enough to detect format (first 200 bytes
                    # of PCK section is sufficient).
                    with open(local_binary, "rb") as f:
                        f.seek(pck_start)
                        pck_head = f.read(200)
                    if is_may_format(pck_head):
                        use_may_extractor = True
                        self._log(
                            "Detected BOF May 2026+ custom PCK format "
                            "— using native extractor (GDRE can't read this format).",
                            "info")
                except Exception as _e:
                    pass  # Fall through to GDRE

            if use_may_extractor:
                from .may_extractor import extract_pck
                from .source_converter import convert_imported_tree
                pck_win = os.path.join(self.output_dir, "pck")
                try:
                    # Extract phase drives the progress bar over the first
                    # 80% of the range; the source converter (much faster
                    # but still 2-5s of work on a Dune-sized PCK) gets the
                    # last 20%.  Without the split the bar would jump
                    # from 100% (after extract) back down — confusing.
                    def _extract_progress(cur, total, label):
                        pct = int(80 * cur / max(total, 1))
                        self._progress(pct, 100, label)

                    def _convert_progress(cur, total, label):
                        pct = 80 + int(20 * cur / max(total, 1))
                        self._progress(pct, 100, label)

                    stats = extract_pck(local_binary, pck_win,
                                        log_cb=self._log,
                                        progress_cb=_extract_progress)
                    self._log(
                        f"PCK extracted: {stats['files_written']} files "
                        f"({stats['adjacent_count']} imported + "
                        f"{stats['sequential_count']} scripts/scenes, "
                        f"{stats['rscc_count']} Zstd-decompressed, "
                        f"{stats['total_bytes'] / 1024 / 1024:.1f} MB).",
                        "success")
                    if stats["unpaired_simple"]:
                        self._log(
                            f"  {len(stats['unpaired_simple'])} sidecar paths "
                            f"had no extractable file data.", "warning")

                    # Convert imported binaries into editable formats
                    # (.wav/.ogg/.webp/.ogv/.ttf/.otf) so the user can
                    # play / view / edit them in standard tools.  Saves
                    # under pck/_EDITABLE ASSETS/ alongside the imported tree.
                    self._log(
                        "Converting imported assets to editable formats "
                        "(audio→wav, textures→webp, video→ogv, fonts→ttf/otf)...",
                        "info")
                    from .source_converter import EDITABLE_DIR_NAME
                    src_dir = os.path.join(pck_win, EDITABLE_DIR_NAME)
                    conv_stats = convert_imported_tree(
                        pck_win, src_dir, log_cb=self._log,
                        progress_cb=_convert_progress)
                    if conv_stats["success"]:
                        ext_summary = ", ".join(
                            f"{n} {ext}" for ext, n in
                            sorted(conv_stats["by_ext"].items(),
                                   key=lambda kv: -kv[1]))
                        self._log(
                            f"Editable files: {ext_summary}",
                            "success")
                        self._log(
                            f"To mod the game, edit any file in "
                            f"{src_dir} and switch to the Write tab.",
                            "success")
                        if self.log_link:
                            self.log_link(
                                f"Open {os.path.basename(src_dir)}/ folder",
                                src_dir)
                    self._progress(100, 100,
                                   f"{stats['files_written']} files extracted")
                except Exception as e:
                    self._log(
                        f"BOF May extractor failed: {e}", "error")
                # Skip GDRE path entirely
            else:
                self._log("Unpacking Godot PCK with GDRE Tools...", "info")
                self._progress(0, 100, "Starting...")
                try:
                    pck_out = f"{out_wsl}/pck"
                    binary_wsl = binary_name if binary_name else f"{out_wsl}/GDCraze.x86_64"
                    gdre_prefix = self._gdre_prefix()

                    # GDRE outputs phase progress as "Phase name... [===] XX%" separated
                    # by \r (not \n), so we split each streamed line on \r and parse.
                    # Poll the Windows-side pck folder in a background thread.
                    # We parse "Verified X files" from GDRE output to set the extraction
                    # total; the export phase writes additional converted files beyond that.
                    pck_win = os.path.join(self.output_dir, "pck")
                    os.makedirs(pck_win, exist_ok=True)
                    baseline = sum(len(fs) for _, _, fs in os.walk(pck_win))
                    _stop_poll = threading.Event()
                    _last_count = [0]
                    _extract_done = [False]
                    _extract_snap = [0]
                    _LOG_EVERY = 500

                    def _poll_pck():
                        prev_logged = 0
                        while not _stop_poll.is_set():
                            raw = sum(len(fs) for _, _, fs in os.walk(pck_win))
                            count = max(0, raw - baseline)
                            _last_count[0] = count
                            if _extract_done[0]:
                                converted = max(0, count - _extract_snap[0])
                                self._progress(0, 0,
                                               f"Converting resources... {converted} converted")
                                if converted - prev_logged >= _LOG_EVERY and converted > 0:
                                    prev_logged = (converted // _LOG_EVERY) * _LOG_EVERY
                                    self._log(f"  {converted} resources converted...", "info")
                            else:
                                self._progress(0, 0, f"Extracting... {count} files")
                                if count - prev_logged >= _LOG_EVERY and count > 0:
                                    prev_logged = (count // _LOG_EVERY) * _LOG_EVERY
                                    self._log(f"  {count} files extracted...", "info")
                            _stop_poll.wait(1.0)

                    poll_thread = threading.Thread(target=_poll_pck, daemon=True)
                    poll_thread.start()

                    _extracted_re = re.compile(r'Extracted (\d+) files')
                    _skip = ("Godot Engine", "input_file", "Input files", "GDRE Tools",
                             "Ubuntu", "Loading import", "Loading GDScript",
                             "Reading PCK", "Extracting files", "Exporting resources",
                             "Reading folder", "Generating filesystem")
                    try:
                        for raw in self.executor.stream(
                            f"mkdir -p {pck_out!r} && "
                            f"{gdre_prefix} --recover={binary_wsl!r} --output={pck_out!r} 2>&1",
                            timeout=GDRE_TIMEOUT,
                        ):
                            for chunk in raw.split('\r'):
                                chunk = chunk.strip()
                                if not chunk:
                                    continue
                                em = _extracted_re.search(chunk)
                                if em:
                                    _extract_done[0] = True
                                    _extract_snap[0] = _last_count[0]
                                    self._log(f"  {chunk}", "info")
                                    self._log("  Converting resources to source formats"
                                              " (decompiling scripts, textures → PNG, etc.)...",
                                              "info")
                                    continue
                                if any(chunk.startswith(s) for s in _skip):
                                    continue
                                if any(tag in chunk for tag in ("ERROR", "WARN")):
                                    self._log(f"  {chunk}", "warning")
                                else:
                                    self._log(f"  {chunk}", "info")
                    finally:
                        _stop_poll.set()
                        poll_thread.join(timeout=2)

                    final = _last_count[0]
                    self._progress(100, 100, f"{final} files extracted")
                    self._log(f"PCK unpacked to pck/ subfolder ({final} files).",
                              "success")
                except CommandError as e:
                    self._log(
                        f"GDRE Tools failed (PCK may still be usable as binary): {e.output}",
                        "error")

        # Phase 3 — Checksums
        self._set_phase(3)
        self._log("Generating baseline checksums...", "info")
        _generate_checksums(self.output_dir, self._log,
                            lambda c, t, d: self._progress(c, t, d))
        self._check_cancel()

        # Phase 4 — Cleanup
        self._set_phase(4)
        self._log("Cleaning up temporary files...", "info")
        try:
            self.executor.run(
                f"rm -rf {tmp_tar_wsl!r} {tmp_extract_wsl!r} 2>/dev/null; true",
                timeout=30,
            )
        except Exception:
            pass
        self._log("Cleanup complete.", "success")

        self._done(True,
            f"{game_info['display']} decrypted successfully.\n\n"
            f"Output: {self.output_dir}\n\n"
            f"Game assets extracted to the pck/ subfolder.")


# ---------------------------------------------------------------------------
# Modify (re-encrypt) pipeline
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Update-version date helpers
# ---------------------------------------------------------------------------
# The game applies a .fun only when the YYYY.MM.DD on line 2 of the embedded
# updated_bash_profile / updated_updatecode (the line after "Godot Code looks
# for the date on the next line") is newer than what's installed.  Extract
# copies those files into the assets folder, so the GUI can read the baseline
# host-side; the Write pipeline bumps it executor-side at build time.

_UPDATE_VERSION_FILES = ("updated_bash_profile", "updated_updatecode")
_UPDATE_VERSION_RE = re.compile(r"(20\d{2})\.(\d{2})\.(\d{2})")
# Per-game working-folder marker remembering the last date Write emitted, so
# successive rebuilds from the same folder keep climbing instead of colliding.
MODVERSION_FILE = ".bof_modversion"


def parse_update_date(text):
    """Return the ``datetime.date`` embedded in *text* (YYYY.MM.DD), or None."""
    import datetime as _dt
    m = _UPDATE_VERSION_RE.search(text or "")
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def peek_next_update_version(assets_dir):
    """Host-side preview of the update-version dates for *assets_dir*.

    Returns ``(baseline_date, next_date_str)`` where ``baseline_date`` is the
    stock version embedded in the extracted files and ``next_date_str`` is the
    ``YYYY.MM.DD`` the next auto Write would stamp (one day past the later of
    the baseline and the last-emitted marker).  Returns ``(None, None)`` when
    the folder has no readable BOF update-version files (e.g. a non-BOF or
    partial extract).  The GUI uses this to show the concrete date; the Write
    pipeline computes the same value executor-side at build time.
    """
    import datetime as _dt

    baseline = None
    for fname in _UPDATE_VERSION_FILES:
        try:
            with open(os.path.join(assets_dir, fname), "r",
                      encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        d = parse_update_date(lines[1]) if len(lines) >= 2 else None
        if d:
            baseline = d if baseline is None else max(baseline, d)

    if baseline is None:
        return None, None

    last = None
    try:
        with open(os.path.join(assets_dir, MODVERSION_FILE), "r",
                  encoding="utf-8") as f:
            last = parse_update_date(f.read())
    except OSError:
        pass

    floor = baseline if last is None else max(baseline, last)
    return baseline, (floor + _dt.timedelta(days=1)).strftime("%Y.%m.%d")


class ModifyPipeline(_BasePipeline):
    """Patch modified assets into a copy of the original .fun file."""

    def __init__(self, original_fun, assets_dir, output_fun_path, game_key,
                 executor, log_cb, phase_cb, progress_cb, done_cb,
                 version_date_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_fun = original_fun
        self.assets_dir = assets_dir
        self.output_fun_path = output_fun_path
        self.game_key = game_key
        self.executor = executor
        # Optional explicit "YYYY.MM.DD" the user typed in the Write tab's
        # version field (Auto unchecked).  None => auto-climb.  Used to
        # force-install, e.g. stamping official code above a higher-dated mod.
        self.version_date_override = version_date_override

    # ------------------------------------------------------------------
    # BOF May 2026+ custom-format detection + native packer
    # ------------------------------------------------------------------

    def _detect_may_format(self, binary_wsl):
        """Sniff a binary's PCK header (via the executor) to decide if
        this is BOF's May 2026+ custom format that needs our native
        packer instead of GDRE Tools."""
        import base64 as _b64
        import struct as _struct
        try:
            trailer_b64 = self.executor.run(
                f"tail -c 12 {binary_wsl!r} | base64",
                timeout=30,
            ).strip()
            trailer = _b64.b64decode(trailer_b64)
            if len(trailer) != 12 or trailer[8:12] not in (b"GDPC", b"GBOF"):
                return False
            pck_size = _struct.unpack("<Q", trailer[:8])[0]
            # Grab the first 200 bytes of the PCK section.  tail+head pipe
            # is portable across macOS / Linux without needing dd seeks.
            pck_head_b64 = self.executor.run(
                f"tail -c $(({pck_size} + 12)) {binary_wsl!r} | "
                f"head -c 200 | base64",
                timeout=30,
            ).strip()
            pck_head = _b64.b64decode(pck_head_b64)
            # is_may_format checks magic GDPC, but BOF binaries may still
            # have GBOF here; normalise before checking.
            if pck_head[:4] == b"GBOF":
                pck_head = b"GDPC" + pck_head[4:]
            from .may_extractor import is_may_format
            return is_may_format(pck_head)
        except Exception:
            return False

    def _bump_update_version(self, tmp_dir_wsl):
        """Advance the update-version date inside the extracted .fun so the
        game treats this build as *newer* code and actually applies it.

        The running game reads the ``YYYY.MM.DD`` on line 2 of
        ``updated_bash_profile`` / ``updated_updatecode`` (the line after
        "Godot Code looks for the date on the next line") and only installs
        the .fun when that date is newer than what's already running.  We
        re-tar those files unchanged otherwise, so a mod of the current code
        would ship the current date and the game would just log "no new
        code" and skip it.

        Two modes:

        * **Explicit** (``version_date_override`` set — the user typed a date
          in the Write tab with Auto unchecked): stamp exactly that date.
          This is the escape hatch for force-installing, e.g. putting
          official code that's dated *older* than an installed mod back on
          the machine by stamping it above the mod.
        * **Auto** (default): ``new = max(embedded_dates, last_emitted) + 1``.
          Climbing from the embedded baseline (not "today") keeps the mod
          version-adjacent to stock, so any genuine future BOF release still
          out-dates it and installs over the top — the machine is never
          locked out of official code.  The last date we emitted is tracked
          in ``assets_dir/.bof_modversion`` so successive rebuilds from the
          same folder keep climbing instead of reproducing the same date
          (which the game would reject as "not newer").

        The arithmetic is done in Python — the executor's ``date`` is GNU on
        WSL/Linux but BSD on macOS, and ``date -d '+1 day'`` isn't portable;
        ``sed`` is.
        """
        import datetime as _dt

        # Highest embedded date across the two files = the stock baseline.
        baseline = None
        present = []  # (fname, exec_path) for files that actually exist
        for fname in _UPDATE_VERSION_FILES:
            path = f"{tmp_dir_wsl}/{fname}"
            try:
                line2 = self.executor.run(
                    f"sed -n '2p' {path!r}", timeout=15).strip()
            except CommandError:
                continue  # file absent in this code variant — skip quietly
            embedded = parse_update_date(line2)
            if embedded is None:
                self._log(
                    f"  {fname}: no version date on line 2 — left as-is.",
                    "info")
                continue
            present.append((fname, path))
            baseline = embedded if baseline is None else max(baseline, embedded)

        if baseline is None:
            self._log(
                "  No update-version date found — nothing to bump.", "info")
            return

        override = parse_update_date(self.version_date_override)
        if self.version_date_override and override is None:
            self._log(
                f"  Ignoring invalid version date "
                f"{self.version_date_override!r} — falling back to auto.",
                "error")

        if override is not None:
            new_date = override
            self._log(
                f"  Using explicit update version {override.strftime('%Y.%m.%d')}"
                f" (stock baseline {baseline.strftime('%Y.%m.%d')}).", "info")
        else:
            # Climb one day past whichever is later: the stock baseline or
            # the last date we emitted for this folder (across rebuilds).
            last_emitted = self._read_last_modversion()
            floor = (baseline if last_emitted is None
                     else max(baseline, last_emitted))
            new_date = floor + _dt.timedelta(days=1)
        new_str = new_date.strftime("%Y.%m.%d")

        for fname, path in present:
            # Replace line 2 wholesale, preserving the original "# <date> "
            # shape (trailing space) the BOF template uses.
            try:
                self.executor.run(
                    f"sed -i '2s|.*|# {new_str} |' {path!r}", timeout=15)
            except CommandError as e:
                self._log(
                    f"  Warning: could not bump version in {fname}: "
                    f"{e.output}", "error")
                continue
            self._log(f"  {fname}: update version -> {new_str}", "info")

        self._write_last_modversion(new_str)
        if override is None:
            self._log(
                f"  (stock baseline {baseline.strftime('%Y.%m.%d')}; this "
                f"build is {new_str} — any later official BOF release still "
                f"supersedes it.)", "info")

    def _read_last_modversion(self):
        """Return the last update-version date emitted for this assets
        folder, or None.  Stored host-side (not via the executor) since
        ``assets_dir`` is a plain host path."""
        try:
            marker = os.path.join(self.assets_dir, MODVERSION_FILE)
            with open(marker, "r", encoding="utf-8") as f:
                return parse_update_date(f.read())
        except OSError:
            return None

    def _write_last_modversion(self, date_str):
        try:
            marker = os.path.join(self.assets_dir, MODVERSION_FILE)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(date_str + "\n")
        except OSError:
            pass  # best-effort; iteration still works if installs advance it

    def _may_pack_binary(self, binary_wsl, pck_dir, changed_pck):
        """Use our native may_packer to replace the modified files
        directly inside a BOF May 2026+ binary, in place via the
        executor's filesystem.

        Because may_packer needs to read the full binary, we read it
        via the executor (works on both WSL and native macOS) and
        write back the modified result to the same path.
        """
        import base64 as _b64
        import tempfile
        from .may_packer import pack_pck

        # Read the original binary out of the executor's /tmp.  On
        # Windows this is via WSL's /mnt/c bridge; on macOS the path
        # is local.  Either way, we copy to a Windows-side temp file
        # for the packer.
        local_tmp_in = tempfile.NamedTemporaryFile(
            delete=False, suffix=".x86_64").name
        local_tmp_out = tempfile.NamedTemporaryFile(
            delete=False, suffix=".x86_64").name
        try:
            self._check_cancel()
            # cp via executor — fastest path on macOS, acceptable on WSL
            in_local_wsl = self.executor.to_exec_path(local_tmp_in)
            self.executor.run(
                f"cp {binary_wsl!r} {in_local_wsl!r}",
                timeout=600,
            )
            self._check_cancel()
            self._log(
                f"Packing {len(changed_pck)} file(s) into binary (native)...",
                "info")

            # Wrap log_cb so the packer's per-loop log calls also act
            # as a cancellation polling point.  Without this the user
            # has to wait until the next phase boundary for Cancel to
            # take effect.
            def _packer_log(msg, sev="info"):
                self._check_cancel()
                self._log(msg, sev)

            stats = pack_pck(local_tmp_in, pck_dir, local_tmp_out,
                             log_cb=_packer_log,
                             cancel_cb=lambda: self._cancelled)
            self._check_cancel()
            self._log(
                f"  Replaced {stats['files_replaced']} files "
                f"({stats['new_pck_size']} bytes PCK, "
                f"{stats['new_binary_size']} bytes binary).",
                "info")
            # Copy back into the executor's path
            out_local_wsl = self.executor.to_exec_path(local_tmp_out)
            self.executor.run(
                f"cp {out_local_wsl!r} {binary_wsl!r} && "
                f"chmod +x {binary_wsl!r}",
                timeout=600,
            )
        finally:
            for p in (local_tmp_in, local_tmp_out):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Asset reimport helpers
    # ------------------------------------------------------------------

    def _reimport_assets(self, changed_pck, pck_dir, pck_dir_wsl):
        """For changed source files with .import sidecars, regenerate the
        imported version and return additional relative paths to patch."""
        _IMPORTABLE = (".wav", ".ogg", ".png", ".jpg", ".jpeg")
        audio_jobs = []    # (rel_source, dest_rel, ext)
        texture_jobs = []  # (rel_source, dest_rel)
        script_jobs = []   # rel_source paths for .gd files

        for rel in changed_pck:
            lower = rel.lower()
            # GDScript: .gd → .gdc in .autoconverted/
            if lower.endswith(".gd"):
                gdc_rel = ".autoconverted/" + rel + "c"  # e.g. .autoconverted/scripts/main.gdc
                gdc_abs = os.path.join(pck_dir, gdc_rel)
                if os.path.isfile(gdc_abs):
                    script_jobs.append(rel)
                continue
            if not any(lower.endswith(ext) for ext in _IMPORTABLE):
                continue
            import_file = os.path.join(pck_dir, rel + ".import")
            dest_rel = _parse_import_remap(import_file)
            if not dest_rel:
                continue
            # Verify original imported file exists (we need its header for textures)
            dest_abs = os.path.join(pck_dir, dest_rel)
            if not os.path.isfile(dest_abs):
                self._log(f"  Warning: imported file missing: {dest_rel}", "error")
                continue
            if lower.endswith((".wav", ".ogg")):
                audio_jobs.append((rel, dest_rel, "wav" if lower.endswith(".wav") else "ogg"))
            else:
                texture_jobs.append((rel, dest_rel))

        extra = []
        if audio_jobs:
            self._reimport_audio(audio_jobs, pck_dir, pck_dir_wsl)
            extra.extend(d for _, d, _ in audio_jobs)
        if texture_jobs:
            self._reimport_textures(texture_jobs, pck_dir, pck_dir_wsl)
            extra.extend(d for _, d in texture_jobs)
        if script_jobs:
            compiled = self._recompile_scripts(script_jobs, pck_dir, pck_dir_wsl)
            extra.extend(compiled)
        return extra

    @staticmethod
    def _wav_to_sample(wav_path, sample_path):
        """Convert WAV to Godot AudioStreamWAV .sample (RSRC binary format).

        Pure Python — no Godot binary needed.  Produces byte-identical output
        to Godot 4.4's ResourceSaver for uncompressed 8/16-bit PCM WAV files.
        """
        import wave as _wave

        with _wave.open(wav_path, "rb") as w:
            channels = w.getnchannels()
            sample_rate = w.getframerate()
            sample_width = w.getsampwidth()
            pcm = w.readframes(w.getnframes())

        godot_fmt = 1 if sample_width == 2 else 0  # 0=8bit, 1=16bit
        stereo = 1 if channels == 2 else 0

        # --- RSRC header (334 bytes) ---
        # Reverse-engineered from Godot 4.4.1 ResourceSaver output.
        # This is the fixed preamble for every AudioStreamWAV resource.
        # Exact 334-byte RSRC header for AudioStreamWAV, extracted from
        # Godot 4.4.1 ResourceSaver output.  Everything before the PCM
        # data length field.
        import base64 as _b64
        _HEADER = _b64.b64decode(
            "UlNSQwAAAAAAAAAABAAAAAQAAAAGAAAADwAAAEF1ZGlvU3RyZWFtV0FWAAAA"
            "AAAAAAAAAwAAAP//////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAAAAAAAAAAAAAAAAAAAAAKAAAAGAAAAHJlc291cmNlX2xvY2FsX3RvX3Nj"
            "ZW5lAA4AAAByZXNvdXJjZV9uYW1lAAUAAABkYXRhAAcAAABmb3JtYXQACgAA"
            "AGxvb3BfbW9kZQALAAAAbG9vcF9iZWdpbgAJAAAAbG9vcF9lbmQACQAAAG1p"
            "eF9yYXRlAAcAAABzdGVyZW8ABwAAAHNjcmlwdAAAAAAAAQAAAB0AAABsb2Nh"
            "bDovL0F1ZGlvU3RyZWFtV0FWX2JnaThmAC8BAAAAAAAADwAAAEF1ZGlvU3Ry"
            "ZWFtV0FWAAUAAAACAAAAHwAAAA=="
        )

        # --- Trailer (48 bytes): properties after PCM data ---
        # format(int) + mix_rate(int) + stereo(bool) + script(nil) + sentinel
        trailer = bytearray(48)
        struct.pack_into("<III", trailer, 0, 3, 3, godot_fmt)     # format
        struct.pack_into("<III", trailer, 12, 7, 3, sample_rate)  # mix_rate
        struct.pack_into("<III", trailer, 24, 8, 2, stereo)       # stereo
        # script(nil) + RSRC sentinel
        struct.pack_into("<II", trailer, 36, 9, 1)
        trailer[44:48] = b"RSRC"

        header = _HEADER
        with open(sample_path, "wb") as f:
            f.write(header)
            f.write(struct.pack("<I", len(pcm)))
            f.write(pcm)
            f.write(trailer)

    @staticmethod
    def _ogg_to_oggvorbisstr(ogg_path, output_path):
        """Convert OGG Vorbis to Godot 4 AudioStreamOggVorbis .oggvorbisstr.

        Pure Python — no Godot binary needed.  Builds a valid RSRC binary
        resource containing an OggPacketSequence sub-resource (with the
        raw vorbis packets, granule positions and sample rate) and an
        AudioStreamOggVorbis sub-resource that references it.
        """
        import base64 as _b64

        ogg_data = open(ogg_path, "rb").read()

        # ── Parse OGG pages ─────────────────────────────────────────
        pages = []          # list of (granule, [packet_bytes, ...])
        pos = 0
        carry = b""         # partial packet carried from previous page
        while pos + 27 <= len(ogg_data):
            if ogg_data[pos:pos + 4] != b"OggS":
                break
            header_type = ogg_data[pos + 5]
            continued = bool(header_type & 0x01)
            granule = struct.unpack_from("<q", ogg_data, pos + 6)[0]
            num_segments = ogg_data[pos + 26]
            seg_table = ogg_data[pos + 27:pos + 27 + num_segments]
            data_start = pos + 27 + num_segments
            total_data = sum(seg_table)

            packets = []
            buf = carry if continued else b""
            if continued and not carry:
                buf = b""  # discard if we have nothing to continue
            elif not continued and carry:
                # Previous page ended mid-packet but this page doesn't
                # continue — discard the partial data (shouldn't happen
                # in well-formed files).
                carry = b""

            seg_offset = data_start
            for seg_size in seg_table:
                buf += ogg_data[seg_offset:seg_offset + seg_size]
                seg_offset += seg_size
                if seg_size < 255:
                    packets.append(buf)
                    buf = b""

            carry = buf  # non-empty if last segment was 255
            pages.append((granule, packets))
            pos = data_start + total_data

        if not pages:
            raise ValueError("No OGG pages found in " + ogg_path)

        # ── Extract sample rate from Vorbis identification header ───
        first_pkt = pages[0][1][0] if pages[0][1] else b""
        if len(first_pkt) < 16 or first_pkt[1:7] != b"vorbis":
            raise ValueError("First OGG packet is not a Vorbis ID header")
        sample_rate = struct.unpack_from("<I", first_pkt, 12)[0]

        # ── Helper: pad length for binary variant encoding ──────────
        def _pad(n):
            """Bytes needed to pad *n* data bytes to a 4-byte boundary."""
            extra = 4 - (n % 4)
            return extra if extra < 4 else 0

        # ── Build packet_data variant (Array[Array[PackedByteArray]])
        VTYPE_ARRAY = 0x1E
        VTYPE_PBA = 0x1F

        pkt_buf = bytearray()
        pkt_buf += struct.pack("<I", len(pages))        # outer array count
        for _granule, pkts in pages:
            pkt_buf += struct.pack("<II", VTYPE_ARRAY, len(pkts))
            for p in pkts:
                pkt_buf += struct.pack("<II", VTYPE_PBA, len(p))
                pkt_buf += p
                pkt_buf += b"\x00" * _pad(len(p))

        # ── Build granule_positions variant (PackedInt64Array) ──────
        VTYPE_PACKED_INT64 = 0x30
        gran_buf = bytearray()
        gran_buf += struct.pack("<I", len(pages))
        for g, _pkts in pages:
            gran_buf += struct.pack("<q", g)

        # ── Build OggPacketSequence sub-resource ────────────────────
        oggpkt_type = b"OggPacketSequence\x00"  # 18 bytes
        oggpkt_nprops = 4  # packet_data, granule_positions, sampling_rate, script

        oggpkt = bytearray()
        oggpkt += struct.pack("<I", len(oggpkt_type))
        oggpkt += oggpkt_type
        oggpkt += struct.pack("<I", oggpkt_nprops)
        # prop 0: packet_data (string index 2), Array
        oggpkt += struct.pack("<II", 2, VTYPE_ARRAY)
        oggpkt += pkt_buf
        # prop 1: granule_positions (string index 3), PackedInt64Array
        oggpkt += struct.pack("<II", 3, VTYPE_PACKED_INT64)
        oggpkt += gran_buf
        # prop 2: sampling_rate (string index 4), float
        oggpkt += struct.pack("<IIf", 4, 4, float(sample_rate))
        # prop 3: script (string index 5), nil
        oggpkt += struct.pack("<II", 5, 1)

        # ── Build AudioStreamOggVorbis sub-resource ─────────────────
        asov_type = b"AudioStreamOggVorbis\x00"  # 21 bytes
        asov = bytearray()
        asov += struct.pack("<I", len(asov_type))
        asov += asov_type
        asov += struct.pack("<I", 2)                # num_props = 2
        # prop 0: packet_sequence (idx 6), Object internal ref, index 0
        asov += struct.pack("<IIII", 6, 0x18, 2, 0)
        # prop 1: script (idx 5), nil
        asov += struct.pack("<II", 5, 1)
        # RSRC sentinel
        asov += b"RSRC"

        # ── Build RSRC header ───────────────────────────────────────
        # Pre-string-table preamble (always the same for OGG resources).
        _PRE = _b64.b64decode(
            "UlNSQwAAAAAAAAAABAAAAAQAAAAGAAAAFQAAAEF1ZGlvU3Ry"
            "ZWFtT2dnVm9yYmlzAAAAAAAAAAAAAwAAAP//////////AAAA"
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        )
        # String table (12 entries, always the same property names).
        _STRINGS = _b64.b64decode(
            "DAAAABgAAAByZXNvdXJjZV9sb2NhbF90b19zY2VuZQAOAAAA"
            "cmVzb3VyY2VfbmFtZQAMAAAAcGFja2V0X2RhdGEAEgAAAGdy"
            "YW51bGVfcG9zaXRpb25zAA4AAABzYW1wbGluZ19yYXRlAAcA"
            "AABzY3JpcHQAEAAAAHBhY2tldF9zZXF1ZW5jZQAEAAAAYnBt"
            "AAsAAABiZWF0X2NvdW50AAoAAABiYXJfYmVhdHMABQAAAGxv"
            "b3AADAAAAGxvb3Bfb2Zmc2V0AA=="
        )

        # Internal resource paths (use short fixed names)
        int_path_0 = b"local://OggPacketSequence_1\x00"  # 27 bytes
        int_path_1 = b"local://AudioStreamOggVorbis_1\x00"  # 31 bytes

        # Compute internal resource offsets
        res_table = bytearray()
        res_table += struct.pack("<I", 0)  # external resource count
        res_table += struct.pack("<I", 2)  # internal resource count
        # Entry 0: OggPacketSequence
        header_size_before_res0 = (
            len(_PRE) + len(_STRINGS) + 4 + 4  # ext_count + int_count
            + 4 + len(int_path_0) + 8           # entry 0
            + 4 + len(int_path_1) + 8           # entry 1
        )
        res0_offset = header_size_before_res0
        res1_offset = res0_offset + len(oggpkt)
        res_table += struct.pack("<I", len(int_path_0))
        res_table += int_path_0
        res_table += struct.pack("<Q", res0_offset)
        res_table += struct.pack("<I", len(int_path_1))
        res_table += int_path_1
        res_table += struct.pack("<Q", res1_offset)

        # ── Write output ────────────────────────────────────────────
        with open(output_path, "wb") as f:
            f.write(_PRE)
            f.write(_STRINGS)
            f.write(res_table)
            f.write(oggpkt)
            f.write(asov)

    def _reimport_audio(self, jobs, pck_dir, pck_dir_wsl):
        """Convert wav/ogg source files to Godot imported formats.

        WAV → .sample: pure Python (no external dependencies).
        OGG → .oggvorbisstr: pure Python (no external dependencies).
        """
        wav_jobs = [(s, d, e) for s, d, e in jobs if e == "wav"]
        ogg_jobs = [(s, d, e) for s, d, e in jobs if e == "ogg"]

        # --- WAV conversion (pure Python) ---
        if wav_jobs:
            self._log(f"  Converting {len(wav_jobs)} WAV file(s) to .sample...", "info")
            for rel_src, dest_rel, _ in wav_jobs:
                src_abs = os.path.join(pck_dir, rel_src)
                dest_abs = os.path.join(pck_dir, dest_rel)
                try:
                    self._wav_to_sample(src_abs, dest_abs)
                    self._log(f"    OK {dest_rel}", "success")
                except Exception as e:
                    self._log(f"    FAIL {rel_src}: {e}", "error")

        # --- OGG conversion (pure Python) ---
        if ogg_jobs:
            self._log(f"  Converting {len(ogg_jobs)} OGG file(s) to .oggvorbisstr...", "info")
            for rel_src, dest_rel, _ in ogg_jobs:
                src_abs = os.path.join(pck_dir, rel_src)
                dest_abs = os.path.join(pck_dir, dest_rel)
                try:
                    self._ogg_to_oggvorbisstr(src_abs, dest_abs)
                    self._log(f"    OK {dest_rel}", "success")
                except Exception as e:
                    self._log(f"    FAIL {rel_src}: {e}", "error")

        # Verify all converted files were actually written
        failed = set()
        for rel_src, dest_rel, ext in jobs:
            dest_abs = os.path.join(pck_dir, dest_rel)
            src_abs = os.path.join(pck_dir, rel_src)
            src_mtime = os.path.getmtime(src_abs)
            if not os.path.isfile(dest_abs) or os.path.getmtime(dest_abs) < src_mtime:
                self._log(f"    WARNING: reimport failed for {rel_src}", "error")
                failed.add(dest_rel)
        jobs[:] = [(s, d, e) for s, d, e in jobs if d not in failed]

    def _recompile_scripts(self, gd_rels, pck_dir, pck_dir_wsl):
        """Recompile modified .gd scripts to .gdc bytecode using GDRE Tools.

        Returns list of additional relative paths (the .gdc files) to patch.
        """
        # Parse bytecode version from gdre_export.log
        export_log = os.path.join(pck_dir, "gdre_export.log")
        bytecode_ver = None
        if os.path.isfile(export_log):
            with open(export_log, "r", errors="replace") as f:
                for line in f:
                    if "Detected Bytecode Revision:" in line:
                        # e.g. "Detected Bytecode Revision: 4.5.0-stable (ebc36a7)"
                        bytecode_ver = line.split(":", 1)[1].strip().split()[0]
                        break
        if not bytecode_ver:
            self._log("  Warning: could not detect bytecode version from export log", "error")
            self._log("  Skipping script recompilation", "error")
            return []

        self._log(f"  Recompiling {len(gd_rels)} script(s) (bytecode {bytecode_ver})...",
                  "info")

        gdre_prefix = self._gdre_prefix()
        compiled = []
        tmp_out = "/tmp/bof_gdc_compile"

        for rel in gd_rels:
            src_wsl = f"{pck_dir_wsl}/{rel}"
            gdc_rel = ".autoconverted/" + rel + "c"
            gdc_abs = os.path.join(pck_dir, gdc_rel)

            try:
                self.executor.run(
                    f"rm -rf {tmp_out} && mkdir -p {tmp_out} && "
                    f"{gdre_prefix} "
                    f"--compile='{src_wsl}' "
                    f"--bytecode={bytecode_ver} "
                    f"--output={tmp_out} 2>&1",
                    timeout=60,
                )
                # Find the compiled .gdc
                gdc_name = os.path.basename(rel) + "c"
                tmp_gdc = f"{tmp_out}/{gdc_name}"
                # Copy to the pck directory
                gdc_wsl = self.executor.to_exec_path(gdc_abs)
                self.executor.run(
                    f"cp -f '{tmp_gdc}' '{gdc_wsl}'",
                    timeout=10,
                )
                self._log(f"    OK {gdc_rel}", "success")
                compiled.append(gdc_rel)
            except CommandError as e:
                self._log(f"    FAIL {rel}: {e.output}", "error")

        if compiled:
            # Clean up temp dir
            try:
                self.executor.run(f"rm -rf {tmp_out}", timeout=10)
            except Exception:
                pass

        return compiled

    def _reimport_textures(self, jobs, pck_dir, pck_dir_wsl):
        """Convert png/jpg source files to Godot .ctex using cwebp + GST2 header."""
        import base64 as _b64
        import struct as _struct

        self._log(f"  Reimporting {len(jobs)} texture(s)...", "info")
        for rel_src, dest_rel in jobs:
            dest_abs = os.path.join(pck_dir, dest_rel)

            # Read original ctex header (everything before the RIFF/WebP data)
            try:
                with open(dest_abs, "rb") as f:
                    orig_data = f.read()
                riff_offset = orig_data.find(b"RIFF")
                if riff_offset < 0:
                    self._log(f"    Skipping {rel_src}: ctex not WebP-based", "error")
                    continue
                header = bytearray(orig_data[:riff_offset])
            except Exception as e:
                self._log(f"    Skipping {rel_src}: {e}", "error")
                continue

            # Convert source image to WebP lossless, get size, assemble ctex
            src_wsl = f"{pck_dir_wsl}/{rel_src}"
            dest_wsl = self.executor.to_exec_path(dest_abs)
            tmp_webp = "/tmp/bof_tex.webp"
            header_b64 = _b64.b64encode(bytes(header)).decode()

            try:
                # cwebp convert + assemble in one shot
                self.executor.run(
                    f"cwebp -lossless -quiet '{src_wsl}' -o {tmp_webp} 2>&1",
                    timeout=60,
                )
                # Get WebP size and update the length field in the header
                webp_size = int(self.executor.run(
                    f"stat -f%z {tmp_webp} 2>/dev/null || stat -c%s {tmp_webp}",
                    timeout=5,
                ).strip())
                _struct.pack_into("<I", header, len(header) - 4, webp_size)
                header_b64 = _b64.b64encode(bytes(header)).decode()

                # Write header + WebP data to the imported ctex file
                self.executor.run(
                    f"echo {header_b64!r} | base64 -d > '{dest_wsl}' && "
                    f"cat {tmp_webp} >> '{dest_wsl}'",
                    timeout=30,
                )
                self._log(f"    OK {dest_rel}", "info")
            except CommandError as e:
                self._log(f"    Failed {rel_src}: {e.output}", "error")

    def run(self):
        try:
            self._run()
        except PipelineError as e:
            self._done(False, e.message)
        except Exception as e:
            self._done(False, f"Unexpected error: {e}")

    def _run(self):
        game_info = GAME_DB[self.game_key]
        passphrase = game_info["passphrase"]
        game_key = self.game_key
        gpg_bin = self._resolve_gpg()
        self._log(f"Using gpg: {gpg_bin}", "info")

        fun_wsl = self.executor.to_exec_path(self.original_fun)
        out_fun_wsl = self.executor.to_exec_path(self.output_fun_path)
        tmp_tar_wsl = f"/tmp/bof_{game_key}_mod.tar.gz"
        tmp_dir_wsl = f"/tmp/bof_{game_key}_repack"

        # Phase 0 — Decrypt original .fun → tar.gz → extract to temp dir
        self._set_phase(0)
        self._log(f"Decrypting original {os.path.basename(self.original_fun)}...",
                  "info")
        self._progress(0, 100, "Decrypting original...")

        fun_size = os.path.getsize(self.original_fun)
        try:
            with self._poll_file_progress(tmp_tar_wsl, fun_size, "Decrypting..."):
                self.executor.run(
                    f"{gpg_bin} --batch --yes --passphrase={passphrase!r} "
                    f"--decrypt --output {tmp_tar_wsl!r} {fun_wsl!r} 2>&1",
                    timeout=GPG_DECRYPT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Decrypt",
                f"GPG decryption failed:\n{e.output}\n\n"
                f"Check that the original .fun file is valid.")
        self._log("Original decrypted.", "success")

        # Extract tar to temp dir (preserves original structure)
        self._progress(0, 100, "Extracting original...")
        try:
            self.executor.run(
                f"rm -rf {tmp_dir_wsl!r} && mkdir -p {tmp_dir_wsl!r} && "
                f"tar -xzf {tmp_tar_wsl!r} -C {tmp_dir_wsl!r} 2>&1",
                timeout=TAR_EXTRACT_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Decrypt",
                f"tar extract failed:\n{e.output}")
        self._log("Original extracted to temp dir.", "success")
        self._check_cancel()

        # Phase 1 — Patch: find changed PCK files and patch the binary
        self._set_phase(1)

        pck_dir = os.path.join(self.assets_dir, "pck")
        has_pck = os.path.isdir(pck_dir)

        # Find the Godot binary in the temp extract
        binary_wsl = ""
        try:
            binary_wsl = self.executor.run(
                f"find {tmp_dir_wsl!r} -name '*.x86_64' -type f | head -1",
                timeout=15,
            ).strip()
        except Exception:
            pass
        if not binary_wsl:
            raise PipelineError("Patch",
                "No Godot binary (.x86_64) found in the extracted archive.")

        self._log(f"Binary: {os.path.basename(binary_wsl)}", "info")

        # Detect changed PCK files by MD5 against the .checksums.md5
        # baseline emitted at Extract time.  Mtime-based detection
        # was unreliable: even with no user edits, re-extract and
        # cross-tool file-touching events shifted mtimes past the
        # baseline and the pipeline patched every file in the binary.
        changed_pck = []
        if has_pck:
            # .checksums.md5 lives at the OUTPUT (assets_dir) root,
            # not inside pck/ — it covers the whole extract.  Each
            # line is `<rel_path_from_assets_dir>\t<md5>`.
            checksums_file = os.path.join(self.assets_dir, ".checksums.md5")
            baseline_md5 = {}
            if os.path.isfile(checksums_file):
                with open(checksums_file, "r", encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if "\t" in line:
                            path, md5 = line.rsplit("\t", 1)
                            baseline_md5[path.replace("\\", "/")] = md5

            # First: re-encode anything the user edited under
            # pck/_EDITABLE ASSETS/ back into the corresponding imported
            # binary in pck/.godot/imported/.  This is the May-format
            # workflow — pre-May extracts won't have an editable folder
            # so the call no-ops.  We pass the checksums file's mtime
            # as the baseline so inverse-conversion fires only for
            # files the user really touched after Extract.
            try:
                from .inverse_converter import apply_source_edits
                baseline_mtime_for_edits = (
                    os.path.getmtime(checksums_file)
                    if os.path.isfile(checksums_file) else 0)
                apply_source_edits(
                    pck_dir,
                    baseline_checksums_path=checksums_file,
                    baseline_mtime=baseline_mtime_for_edits,
                    log_cb=self._log,
                    progress_cb=self._progress,
                    cancel_cb=lambda: self._cancelled)
            except ImportError:
                pass

            _skip_names = {"gdre_export.log", ".checksums.md5", ".DS_Store",
                           "Thumbs.db", "desktop.ini", "_README.txt"}
            from .source_converter import (
                EDITABLE_DIR_NAME, LEGACY_DIR_NAMES)
            _editable_names = (EDITABLE_DIR_NAME,) + LEGACY_DIR_NAMES

            self._log("Comparing pck/ MD5s against extract baseline...",
                      "info")
            n_checked = 0
            # Pre-walk to get a file count for progress + cancel checks
            all_files = []
            for root, _dirs, files in os.walk(pck_dir):
                if ".autoconverted" in root:
                    continue
                rel_root = os.path.relpath(root, pck_dir)
                if any(rel_root == n or rel_root.startswith(n + os.sep)
                       for n in _editable_names):
                    continue
                for fname in files:
                    if fname in _skip_names:
                        continue
                    all_files.append(os.path.join(root, fname))

            for i, abs_path in enumerate(all_files):
                # Respect Cancel between every file — MD5-hashing a
                # 1.5 GB binary takes several seconds and the user
                # shouldn't have to wait for that on a cancelled run.
                self._check_cancel()
                rel_from_pck = os.path.relpath(
                    abs_path, pck_dir).replace("\\", "/")
                rel_from_assets = "pck/" + rel_from_pck
                saved_md5 = baseline_md5.get(rel_from_assets)
                if not saved_md5:
                    changed_pck.append(rel_from_pck)
                    continue
                current_md5 = _md5_file(abs_path)
                n_checked += 1
                if current_md5 != saved_md5:
                    changed_pck.append(rel_from_pck)
                if (i + 1) % 25 == 0:
                    self._progress(
                        i + 1, len(all_files),
                        f"MD5-checking {i+1}/{len(all_files)}...")
            self._log(
                f"  MD5-compared {n_checked} file(s); "
                f"{len(changed_pck)} changed since Extract.",
                "info")

        if changed_pck:
            self._log(f"Found {len(changed_pck)} modified source file(s):", "info")
            for f in changed_pck[:20]:
                self._log(f"  {f}", "info")
            if len(changed_pck) > 20:
                self._log(f"  ... and {len(changed_pck) - 20} more", "info")

            # Reimport: for files with .import sidecars, regenerate the
            # imported version (.sample, .oggvorbisstr, .ctex) so Godot
            # picks up the change at runtime.
            pck_dir_wsl = self.executor.to_exec_path(pck_dir)
            self._log("Reimporting assets for Godot...", "info")
            self._progress(0, 0, "Reimporting assets...")
            extra = self._reimport_assets(changed_pck, pck_dir, pck_dir_wsl)
            if extra:
                self._log(f"Reimported {len(extra)} imported asset(s)", "success")
                changed_pck.extend(extra)

            self._log(f"Patching {len(changed_pck)} file(s) into binary...", "info")
            self._progress(0, 100, "Patching PCK...")

            # Detect BOF May 2026+ custom PCK format BEFORE patching the
            # GBOF magic.  May-format binaries can't be patched by GDRE
            # Tools — we use our own may_packer below.  We need the
            # local Windows-side binary path for that (not the WSL
            # executor path); the local copy lives in tmp_dir on the
            # executor's filesystem, which on Windows is reachable via
            # /mnt/c or \\wsl$\Ubuntu\... — both equivalent.
            use_may_packer = self._detect_may_format(binary_wsl)

            # GDRE only recognises stock "GDPC" magic.  If this is a newer
            # BOF binary with "GBOF" magic, temporarily swap it so GDRE can
            # read the embedded PCK; we restore "GBOF" on the output binary
            # further down so the game still loads on the real machine.
            # Skip the swap for May format — our packer handles GBOF natively.
            if not use_may_packer:
                magic_status = _patch_pck_magic(
                    self.executor, binary_wsl,
                    _BOF_PCK_MAGIC, _GODOT_PCK_MAGIC, self._log,
                )
                was_bof_magic = magic_status.startswith("patched")
            else:
                was_bof_magic = True   # will be preserved by may_packer

            if use_may_packer:
                self._log(
                    "Detected BOF May 2026+ custom PCK format — using "
                    "native packer (GDRE Tools can't write this format).",
                    "info")
                self._may_pack_binary(binary_wsl, pck_dir, changed_pck)
                # may_packer preserves the GBOF magic natively, so no
                # post-patch magic restore is needed.
            else:
                pck_dir_wsl = self.executor.to_exec_path(pck_dir)
                tmp_binary_wsl = f"/tmp/bof_{game_key}_patched.x86_64"
                gdre_prefix = self._gdre_prefix()

                # Write patch args to a temp script to avoid quoting / arg-length limits
                import base64 as _b64
                patch_script = f"/tmp/bof_{game_key}_patch.sh"
                script_lines = [
                    "#!/bin/bash",
                    "set -e",
                    f'{gdre_prefix} \\',
                    f"  --pck-patch={binary_wsl!r} \\",
                    f"  --output={tmp_binary_wsl!r} \\",
                    f"  --embed={binary_wsl!r} \\",
                ]
                for i, rel in enumerate(changed_pck):
                    local_path = f"{pck_dir_wsl}/{rel}"
                    cont = " \\" if i < len(changed_pck) - 1 else ""
                    script_lines.append(
                        f"  --patch-file='{local_path}=res://{rel}'{cont}"
                    )
                script_b64 = _b64.b64encode(
                    ("\n".join(script_lines) + "\n").encode()
                ).decode()

                self.executor.run(
                    f"echo {script_b64!r} | base64 -d > {patch_script} && "
                    f"chmod +x {patch_script}",
                    timeout=30,
                )

                try:
                    for chunk in self.executor.stream(
                        f"bash {patch_script} 2>&1", timeout=GDRE_TIMEOUT
                    ):
                        for part in chunk.split("\r"):
                            part = part.strip()
                            if not part:
                                continue
                            pct_match = re.search(r'(\d+)%', part)
                            if pct_match:
                                pct = int(pct_match.group(1))
                                self._progress(pct, 100, f"Patching... {pct}%")
                            elif part:
                                self._log(f"  {part}", "info")
                except CommandError as e:
                    raise PipelineError("Patch",
                        f"GDRE patch failed:\n{e.output}\n\n"
                        f"Make sure GDRE Tools is installed and the changed files "
                        f"are valid Godot assets.")

                # Replace binary in the temp extract with the patched one
                try:
                    self.executor.run(
                        f"mv -f {tmp_binary_wsl!r} {binary_wsl!r} && "
                        f"chmod +x {binary_wsl!r}",
                        timeout=600,
                    )
                except CommandError as e:
                    raise PipelineError("Patch",
                        f"Failed to replace binary:\n{e.output}")

                # GDRE's output uses stock "GDPC" magic.  If the source binary
                # originally used BOF's "GBOF" marker, restore it on the new
                # binary before md5/tar — otherwise the game can't find its own
                # PCK at runtime.
                if was_bof_magic:
                    _patch_pck_magic(self.executor, binary_wsl,
                                     _GODOT_PCK_MAGIC, _BOF_PCK_MAGIC, self._log)

            # Update the md5 checksum file to match the patched binary
            binary_basename = os.path.basename(binary_wsl)
            try:
                self.executor.run(
                    f"cd {tmp_dir_wsl!r} && "
                    f"md5sum {binary_basename!r} > md5",
                    timeout=120,
                )
                self._log("Updated md5 checksum.", "info")
            except CommandError:
                self._log("Warning: could not update md5 file.", "error")

            self._log("Binary patched.", "success")
        else:
            self._log("No modified PCK files — using original binary.", "info")
        self._check_cancel()

        # Advance the update-version date so the game accepts this build as
        # newer code (otherwise it logs "no new code" and skips the .fun).
        self._log("Bumping update version date...", "info")
        self._bump_update_version(tmp_dir_wsl)
        self._check_cancel()

        # Phase 2 — Repack: re-tar the temp dir (same structure as original)
        self._set_phase(2)
        self._log("Repacking archive...", "info")
        self._progress(0, 100, "Creating tar.gz...")

        repack_tar_wsl = f"/tmp/bof_{game_key}_repack.tar.gz"
        try:
            # Use * glob (not .) to avoid ./ prefix and ./ directory entry,
            # matching the original tar structure exactly.
            self.executor.run(
                f"cd {tmp_dir_wsl!r} && "
                f"tar -czf {repack_tar_wsl!r} * 2>&1",
                timeout=TAR_PACK_TIMEOUT,
            )
        except CommandError as e:
            raise PipelineError("Repack", f"tar repack failed:\n{e.output}")

        # Get tar size for encrypt progress
        tar_bytes = 0
        try:
            out = self.executor.run(
                f"stat -f%z {repack_tar_wsl!r} 2>/dev/null || "
                f"stat -c%s {repack_tar_wsl!r} 2>/dev/null || echo 0",
                timeout=10,
            ).strip()
            tar_bytes = int(out)
            size_h = self.executor.run(
                f"du -h {repack_tar_wsl!r} | cut -f1", timeout=10
            ).strip()
            self._log(f"Archive created ({size_h}).", "success")
        except Exception:
            self._log("Archive created.", "success")
        self._check_cancel()

        # Phase 3 — Encrypt: GPG encrypt → output .fun
        self._set_phase(3)
        self._log(f"Encrypting to {os.path.basename(self.output_fun_path)}...", "info")
        self._progress(0, 100, "GPG encrypting...")

        os.makedirs(os.path.dirname(self.output_fun_path) or ".", exist_ok=True)
        try:
            with self._poll_file_progress(
                out_fun_wsl, tar_bytes, "Encrypting..."
            ) if tar_bytes else _nullctx():
                self.executor.run(
                    f"{gpg_bin} --batch --yes --passphrase={passphrase!r} "
                    f"--symmetric --cipher-algo AES256 "
                    f"--output {out_fun_wsl!r} {repack_tar_wsl!r} 2>&1",
                    timeout=GPG_ENCRYPT_TIMEOUT,
                )
        except CommandError as e:
            raise PipelineError("Encrypt", f"GPG encryption failed:\n{e.output}")
        self._log("GPG encryption complete.", "success")
        self._check_cancel()

        # Phase 4 — Cleanup
        self._set_phase(4)
        try:
            self.executor.run(
                f"rm -rf {tmp_tar_wsl!r} {tmp_dir_wsl!r} {repack_tar_wsl!r} "
                f"/tmp/bof_{game_key}_patch.sh /tmp/bof_convert.gd "
                f"/tmp/bof_tex.webp 2>/dev/null; true",
                timeout=30,
            )
        except Exception:
            pass
        self._log("Cleanup complete.", "success")

        self._done(True,
            f"{game_info['display']} re-packed successfully.\n\n"
            f"Output: {self.output_fun_path}\n\n"
            f"Copy this .fun file to a USB drive (FAT32) and insert it "
            f"into the machine to install the update.")
