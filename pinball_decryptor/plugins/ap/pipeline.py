"""Extract / Write pipelines for American Pinball `.pkg` game-code files.

AP `.pkg` files are AES-256-CBC encrypted ZIPs (see :mod:`.crypto`).  Extract
= Detect -> Decrypt -> Checksums -> Done; Write = Detect -> Scan -> Repack ->
Done, re-zipping the modified asset tree and re-encrypting with the same key.
"""

import os

from ...core.checksums import generate_checksums, md5_file, read_checksums
from ...core.pipeline_base import BasePipeline, PipelineError
from ...core.tar_utils import format_size
from .crypto import decrypt_aes_pkg, encrypt_aes_pkg
from .formats import create_zip, detect_game, extract_zip


# ---------------------------------------------------------------------------
# Extract pipeline (.pkg → folder)
# ---------------------------------------------------------------------------

class ExtractPipeline(BasePipeline):
    """Decrypt + unzip an American Pinball `.pkg` into the output directory."""

    def __init__(self, pkg_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.pkg_path = pkg_path
        self.output_dir = output_dir

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        gf = detect_game(self.pkg_path)
        if gf is None:
            raise PipelineError("Detect",
                f"Cannot identify an American Pinball package from: "
                f"{os.path.basename(self.pkg_path)}\n\n"
                f"Expected an AES-encrypted '*-gamecode_*.pkg' update file.")
        self._log(f"Game detected: {gf.game_name}", "success")
        if gf.notes:
            self._log(f"  ({gf.notes})", "info")
        try:
            self._log(f"  Package size: {format_size(os.path.getsize(self.pkg_path))}",
                      "info")
        except OSError:
            pass
        self._check_cancel()

        os.makedirs(self.output_dir, exist_ok=True)

        self._set_phase(1)
        self._log("Decrypting AES-256-CBC package...", "info")
        temp_zip = os.path.join(self.output_dir, "_ap_decrypted.zip")
        try:
            decrypt_aes_pkg(
                self.pkg_path, temp_zip,
                progress_cb=lambda d, t: self._progress(d, t, "Decrypting..."))
            self._log("Decryption OK — valid ZIP archive.", "success")
        except ValueError as e:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            raise PipelineError("Decrypt", str(e))
        except Exception:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            raise

        self._check_cancel()

        self._log("Extracting ZIP contents...", "info")
        try:
            files = extract_zip(
                temp_zip, self.output_dir,
                progress_cb=lambda d, t, n: self._progress(d, t, n))
        finally:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
        self._log(f"  {len(files)} files extracted.", "success")
        self._check_cancel()

        self._set_phase(2)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress)

        self._set_phase(3)
        self._log("Done.", "success")
        self._done(True,
            f"{gf.game_name} extracted successfully.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n}")


# ---------------------------------------------------------------------------
# Write pipeline (assets folder → .pkg)
# ---------------------------------------------------------------------------

class WritePipeline(BasePipeline):
    """Re-zip a modified asset tree and re-encrypt it into a new `.pkg`."""

    def __init__(self, original_pkg, assets_dir, output_pkg,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_pkg = original_pkg
        self.assets_dir = assets_dir
        self.output_pkg = output_pkg

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        gf = detect_game(self.original_pkg)
        game_name = gf.game_name if gf else "American Pinball"
        self._log(f"Game: {game_name}", "success")

        if not os.path.isdir(self.assets_dir):
            raise PipelineError("Detect",
                f"Assets folder not found: {self.assets_dir}")

        self._set_phase(1)
        self._log("Scanning for modified files...", "info")
        baseline = read_checksums(self.assets_dir)
        if not baseline:
            raise PipelineError("Scan",
                f"No baseline checksums found in:\n  {self.assets_dir}\n\n"
                f"Run the Extract tab first to create them.")

        changed = {}
        for rel, orig_md5 in baseline.items():
            abs_path = os.path.join(self.assets_dir, rel)
            if os.path.isfile(abs_path) and md5_file(abs_path) != orig_md5:
                changed[rel] = abs_path

        if changed:
            self._log(f"  {len(changed)} modified file(s):", "info")
            for rel in sorted(changed)[:25]:
                self._log(f"    {rel}", "info")
            if len(changed) > 25:
                self._log(f"    ... and {len(changed) - 25} more", "info")
        else:
            self._log("  No modified files found — output will be a faithful "
                      "rebuild of the original package.", "info")
        self._check_cancel()

        self._set_phase(2)
        self._log(f"Building {os.path.basename(self.output_pkg)}...", "info")
        os.makedirs(os.path.dirname(self.output_pkg) or ".", exist_ok=True)
        temp_zip = self.output_pkg + ".tmp.zip"
        try:
            create_zip(self.assets_dir, temp_zip,
                       progress_cb=lambda d, t, n: self._progress(d, t, n))
            self._log(f"  ZIP staged: {format_size(os.path.getsize(temp_zip))}",
                      "info")
            self._check_cancel()
            self._log("Encrypting with AES-256-CBC...", "info")
            encrypt_aes_pkg(
                temp_zip, self.output_pkg,
                progress_cb=lambda d, t: self._progress(d, t, "Encrypting..."))
        finally:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)

        self._set_phase(3)
        self._log(f"  Output size: {format_size(os.path.getsize(self.output_pkg))}",
                  "info")
        self._log("Done.", "success")
        self._done(True,
            f"{game_name} package built successfully.\n\n"
            f"Output: {self.output_pkg}\n"
            f"Modified files: {len(changed)}\n\n"
            f"Copy to a FAT32 USB drive named like "
            f"'<game>-gamecode_YYYY.MM.DD.pkg' and run the in-game "
            f"code update from the coin-door menu.")
