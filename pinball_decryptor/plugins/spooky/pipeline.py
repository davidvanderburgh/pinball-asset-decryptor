"""Extract and Write pipelines for all Spooky game formats.

These mirror the Spooky-specific decryption/encryption flow but are wired
into the unified app's :class:`BasePipeline` contract.
"""

import hashlib
import json
import os
import threading

from ...core.checksums import generate_checksums
from ...core.pipeline_base import BasePipeline as _CoreBasePipeline
from ...core.pipeline_base import PipelineError  # re-exported for callers
from .crypto import AES_KEYS, decrypt_aes_pkg, encrypt_aes_pkg
from .formats import (GameFile, create_tar, create_tar_gz, create_zip,
                      detect_game, extract_tar_gz, extract_zip)
from .games import (GAME_DB, GODOT_GAMES, GPG_PASSPHRASES, P3_GAMES,
                    UNITY_GAMES, USB_NAMING)
from .gpg import (decrypt_gpg_symmetric, encrypt_gpg_symmetric,
                  sign_beetlejuice, strip_gpg_signature)


META_FILE = ".spooky_meta"


# ---------------------------------------------------------------------------
# Spooky-flavored base pipeline
# ---------------------------------------------------------------------------
# The unified BasePipeline uses ``self._log`` / ``self._set_phase`` etc.
# Spooky's pipeline code reads more naturally with short aliases plus a
# threading.Event-based cancel that supports being passed into helpers
# (e.g. p3_video.convert_all_vids).

class _BasePipeline(_CoreBasePipeline):
    def __init__(self, log_cb, phase_cb, progress_cb, done_cb,
                 indeterminate_cb=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.log = log_cb
        self.phase = phase_cb
        self.progress = progress_cb
        self.done = done_cb
        self.indeterminate = indeterminate_cb or (lambda desc="": None)
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    def run(self):
        try:
            self._run_phases()
        except Exception as e:
            self.log(f"Error: {e}", "error")
            self.done(False, str(e))


# ---------------------------------------------------------------------------
# Extract pipeline (any Spooky input → folder of decrypted assets)
# ---------------------------------------------------------------------------

class ExtractPipeline(_BasePipeline):

    def __init__(self, input_path, output_dir, log_cb, phase_cb, progress_cb,
                 done_cb, indeterminate_cb=None, convert_vids=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb,
                         indeterminate_cb)
        self.input_path = input_path
        self.output_dir = output_dir
        self.game_file = None
        self.convert_vids = convert_vids

    def _run_phases(self):
        # Phase 0: Detect
        self.phase(0)
        self.log("Detecting game format...")

        self.game_file = detect_game(self.input_path)
        if not self.game_file:
            ext = os.path.splitext(self.input_path)[1]
            self.done(False, f"Unrecognized file format: {ext}")
            return

        fmt = self.game_file.format_type
        if fmt == "clonezilla":
            return self._run_clonezilla()

        self.log(f"Detected: {self.game_file.game_name} "
                 f"({self.game_file.ext})", "success")
        self.log(f"Format: {fmt}")
        try:
            file_size = os.path.getsize(self.input_path)
            self.log(f"File size: {file_size / (1024**3):.2f} GB")
        except OSError:
            pass

        if fmt == "aes_pkg":
            self._handle_encrypted_unsupported()
            return

        if self.cancelled:
            self.done(False, "Cancelled")
            return

        # Phase 1: Decrypt / strip signature
        self.phase(1)
        os.makedirs(self.output_dir, exist_ok=True)

        if fmt in ("rm_pkg", "ac_pkg"):
            self._extract_aes_pkg()
        elif fmt in ("um_pkg", "h78_pkg"):
            self._extract_gpg_symmetric_pkg()
        elif fmt in ("tar_gz", "plain_tar"):
            self._extract_tar_gz()
        elif fmt == "gpg_tar_gz":
            self._extract_gpg_tar_gz()
        elif fmt == "plain_zip":
            self._extract_plain_zip()
        else:
            self.done(False, f"Unknown format type: {fmt}")
            return

        if self.cancelled:
            self.done(False, "Cancelled")
            return

        # Engine-specific loose-asset extraction
        if self.game_file.game_name in UNITY_GAMES:
            self._extract_unity_assets_from_output()
        if self.game_file.game_name in GODOT_GAMES:
            self._extract_godot_pck_from_output()
        if self.convert_vids and self.game_file.game_name in P3_GAMES:
            self._convert_p3_vids()

        # Phase 2: Checksums
        self.phase(2)
        self.log("Generating checksums...")
        self.indeterminate("Generating checksums...")
        n = generate_checksums(self.output_dir,
                               log_cb=self.log, progress_cb=self.progress)
        self._write_meta(self.output_dir)

        # Phase 3: Done
        self.phase(3)
        self._log_summary_from_dir(self.output_dir)
        self.done(True,
            f"Successfully extracted {n} files from "
            f"{self.game_file.game_name} to:\n{self.output_dir}")

    # ------------------------------------------------------------------
    # Format-specific decrypt/extract handlers
    # ------------------------------------------------------------------

    def _handle_encrypted_unsupported(self):
        name = self.game_file.game_name
        self.log(f"This .pkg file ({name}) uses AES-256-CBC encryption "
                 f"with an unknown key.", "error")
        self.done(False,
            f"{name}: AES-256-CBC encrypted with unknown key.\n\n"
            f"This game's encryption key has not been found. "
            f"Use the Clonezilla restore image instead to extract assets.")

    def _extract_aes_pkg(self):
        fmt = self.game_file.format_type
        key = AES_KEYS[fmt]
        self.log("Decrypting AES-256-CBC...")
        temp_zip = os.path.join(self.output_dir, "_temp_decrypted.zip")
        try:
            decrypt_aes_pkg(
                self.input_path, temp_zip, key,
                progress_cb=lambda d, t: self.progress(d, t, "Decrypting..."))
            self.log("Decryption successful - valid ZIP archive", "success")
        except Exception:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            raise

        if self.cancelled:
            os.remove(temp_zip)
            self.done(False, "Cancelled")
            return

        # We're already in phase 1 (Decrypt); the inline ZIP extract that
        # follows lives within the same logical phase.
        self.log("Extracting ZIP archive...")
        try:
            files = extract_zip(
                temp_zip, self.output_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"Extracted {len(files)} files", "success")
        finally:
            os.remove(temp_zip)

    def _extract_gpg_symmetric_pkg(self):
        fmt = self.game_file.format_type
        passphrase = GPG_PASSPHRASES[fmt]
        self.log("Decrypting GPG symmetric (password-encrypted)...")
        temp_tar = os.path.join(self.output_dir, "_temp_decrypted.tar.gz")
        try:
            decrypt_gpg_symmetric(
                self.input_path, temp_tar, passphrase,
                progress_cb=lambda d, t: self.progress(d, t, "Decrypting..."))
            self.log("Decryption successful - valid tar.gz archive", "success")
        except Exception:
            if os.path.exists(temp_tar):
                os.remove(temp_tar)
            raise

        if self.cancelled:
            os.remove(temp_tar)
            self.done(False, "Cancelled")
            return

        self.log("Extracting tar.gz archive...")
        try:
            files = extract_tar_gz(
                temp_tar, self.output_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"Extracted {len(files)} files", "success")
        finally:
            os.remove(temp_tar)

    def _extract_tar_gz(self):
        self.log("No encryption - extracting archive directly...")
        if self.cancelled:
            self.done(False, "Cancelled")
            return
        files = extract_tar_gz(
            self.input_path, self.output_dir,
            progress_cb=lambda d, t, n: self.progress(d, t, n))
        self.log(f"Extracted {len(files)} files", "success")

    def _extract_gpg_tar_gz(self):
        self.log("Stripping GPG signature...")
        temp_tar = os.path.join(self.output_dir, "_temp_stripped.tar.gz")
        try:
            strip_gpg_signature(
                self.input_path, temp_tar,
                progress_cb=lambda d, t: self.progress(d, t, "Stripping GPG..."))
            self.log("GPG signature stripped", "success")
        except Exception:
            if os.path.exists(temp_tar):
                os.remove(temp_tar)
            raise

        if self.cancelled:
            os.remove(temp_tar)
            self.done(False, "Cancelled")
            return

        self.log("Extracting tar.gz archive...")
        try:
            files = extract_tar_gz(
                temp_tar, self.output_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"Extracted {len(files)} files", "success")
        finally:
            os.remove(temp_tar)

    def _extract_plain_zip(self):
        self.log("No encryption - extracting ZIP directly...")
        if self.cancelled:
            self.done(False, "Cancelled")
            return
        files = extract_zip(
            self.input_path, self.output_dir,
            progress_cb=lambda d, t, n: self.progress(d, t, n))
        self.log(f"Extracted {len(files)} files", "success")

    # ------------------------------------------------------------------
    # Clonezilla path
    # ------------------------------------------------------------------

    def _run_clonezilla(self):
        from .clonezilla import (PARTITION_GAME_KEY, check_errors,
                                 detect_clonezilla_game, extract_clonezilla,
                                 get_game_key_for_partition)
        from .executor import DockerExecutor, create_executor

        part_key, part_info = detect_clonezilla_game(self.input_path)
        if part_key is None:
            self.done(False,
                f"Cannot identify game from filename: "
                f"{os.path.basename(self.input_path)}\n\n"
                f"Rename the file to include a game name (e.g., 'beetlejuice', "
                f"'evil_dead', 'scooby', 'tcm', 'acnc', 'h78', 'um', 'lt', "
                f"'rick_and_morty').")
            return

        game_key = get_game_key_for_partition(part_key)
        game_display = GAME_DB.get(game_key, {}).get("display", part_key)

        self.log(f"Detected Clonezilla restore image: {game_display}",
                 "success")
        self.log(f"Partition: {part_info['game_partition']} "
                 f"({part_info['compression']})")

        executor = create_executor()
        backend = type(executor).__name__.replace("Executor", "")
        self.log(f"Checking {backend} prerequisites...")
        errors = check_errors(executor)
        if errors:
            for err in errors:
                self.log(f"  Missing: {err}", "error")
            self.done(False,
                f"{backend} prerequisites not met. Clonezilla extraction "
                f"requires partclone and debugfs.\n\n" + "\n".join(errors))
            return
        self.log(f"{backend} prerequisites OK", "success")

        if self.cancelled:
            self.done(False, "Cancelled")
            return

        os.makedirs(self.output_dir, exist_ok=True)
        self.phase(1)
        try:
            extract_clonezilla(
                self.input_path, self.output_dir,
                executor=executor, game_key=part_key,
                progress_cb=lambda s, t, d: self.progress(s, t, d),
                log_cb=self.log,
                indeterminate_cb=lambda desc: self.indeterminate(desc))
        except Exception as e:
            self.done(False, f"Clonezilla extraction failed: {e}")
            return
        finally:
            if isinstance(executor, DockerExecutor):
                executor.stop_container()

        if self.cancelled:
            self.done(False, "Cancelled")
            return

        if game_display in UNITY_GAMES:
            self.log("Detected Unity game - extracting loose assets...")
            self._extract_unity_from_dir(self.output_dir)
        if game_display in GODOT_GAMES:
            self.log("Detected Godot game - extracting PCK assets...")
            self._extract_godot_from_dir(self.output_dir)

        self.phase(2)
        self.log("Generating checksums...")
        self.indeterminate("Generating checksums...")
        n = generate_checksums(self.output_dir,
                               log_cb=self.log, progress_cb=self.progress)

        meta = {
            "game": game_display,
            "game_key": game_key,
            "format": "clonezilla",
            "ext": os.path.splitext(self.input_path)[1],
            "source": os.path.basename(self.input_path),
        }
        with open(os.path.join(self.output_dir, META_FILE), "w") as f:
            json.dump(meta, f, indent=2)

        self.phase(3)
        self._log_summary_from_dir(self.output_dir)
        self.done(True,
            f"Successfully extracted {n} files from {game_display} to:\n"
            f"{self.output_dir}")

    # ------------------------------------------------------------------
    # Engine-specific loose-asset extraction
    # ------------------------------------------------------------------

    def _extract_unity_assets_from_output(self):
        from .unity import check_unitypy, extract_unity_assets

        if not check_unitypy():
            self.log("UnityPy not installed - skipping loose asset extraction",
                     "warning")
            self.log("Install with: pip install UnityPy", "warning")
            return

        data_dir = self._find_unity_data_dir(self.output_dir)
        if not data_dir:
            self.log("No Unity main_Data directory found - skipping", "warning")
            return

        self.log(f"Extracting Unity assets from "
                 f"{os.path.relpath(data_dir, self.output_dir)}...")
        assets_dir = os.path.join(self.output_dir, "_extracted_assets")
        try:
            extracted = extract_unity_assets(
                data_dir, assets_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n),
                log_cb=self.log)
            self.log(f"Extracted {len(extracted)} loose assets "
                     f"(video/audio/textures)", "success")
        except Exception as e:
            self.log(f"Unity extraction error: {e}", "error")

    def _extract_unity_from_dir(self, output_dir):
        from .unity import check_unitypy, extract_unity_assets

        if not check_unitypy():
            self.log("UnityPy not installed - skipping loose asset extraction",
                     "warning")
            return

        data_dir = self._find_unity_data_dir(output_dir)
        if not data_dir:
            self.log("No Unity main_Data directory found in extracted files",
                     "warning")
            return

        assets_dir = os.path.join(output_dir, "_extracted_assets")
        try:
            extracted = extract_unity_assets(
                data_dir, assets_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n),
                log_cb=self.log)
            self.log(f"Extracted {len(extracted)} loose assets", "success")
        except Exception as e:
            self.log(f"Unity extraction error: {e}", "error")

    @staticmethod
    def _find_unity_data_dir(root_dir):
        for root, _dirs, files in os.walk(root_dir):
            if os.path.basename(root) == "main_Data":
                if any(f.endswith(".assets") for f in files):
                    return root
        return None

    def _extract_godot_pck_from_output(self):
        from .godot import extract_godot_pck

        binary_path = self._find_godot_binary(self.output_dir)
        if not binary_path:
            self.log("No main.x86_64 found - skipping Godot PCK extraction",
                     "warning")
            return

        try:
            extracted = extract_godot_pck(
                binary_path, self.output_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n),
                log_cb=self.log)
            self.log(f"Extracted {len(extracted)} Godot assets", "success")
        except Exception as e:
            self.log(f"Godot PCK extraction error: {e}", "error")

    def _extract_godot_from_dir(self, output_dir):
        from .godot import extract_godot_pck

        binary_path = self._find_godot_binary(output_dir)
        if not binary_path:
            self.log("No main.x86_64 found in extracted files", "warning")
            return
        try:
            extracted = extract_godot_pck(
                binary_path, output_dir,
                progress_cb=lambda d, t, n: self.progress(d, t, n),
                log_cb=self.log)
            self.log(f"Extracted {len(extracted)} Godot assets", "success")
        except Exception as e:
            self.log(f"Godot PCK extraction error: {e}", "error")

    @staticmethod
    def _find_godot_binary(root_dir):
        for root, _dirs, files in os.walk(root_dir):
            for f in files:
                if f == "main.x86_64":
                    return os.path.join(root, f)
        return None

    def _convert_p3_vids(self):
        from .p3_video import convert_all_vids, find_ffmpeg

        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            self.log("ffmpeg not found - skipping VID to MP4 conversion",
                     "warning")
            return
        self.log(f"Using ffmpeg: {ffmpeg_path}")

        vid_count = 0
        for root, _dirs, files in os.walk(self.output_dir):
            if "_extracted_assets" in root.split(os.sep):
                continue
            for f in files:
                if f.upper().endswith(".VID"):
                    vid_count += 1

        if vid_count == 0:
            return

        self.log(f"Converting {vid_count} VID files to MP4...")
        generated_dir = os.path.join(self.output_dir, "_extracted_assets")
        converted = convert_all_vids(
            self.output_dir, generated_dir,
            progress_cb=lambda d, t, n: self.progress(d, t, n),
            log_cb=self.log,
            cancel_event=self._cancelled)
        if converted:
            self.log(f"Converted {len(converted)}/{vid_count} VID files",
                     "success")

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    def _write_meta(self, output_dir):
        meta = {
            "game": self.game_file.game_name,
            "game_key": self.game_file.game_key,
            "format": self.game_file.format_type,
            "ext": self.game_file.ext,
            "source": os.path.basename(self.input_path),
        }
        with open(os.path.join(output_dir, META_FILE), "w") as f:
            json.dump(meta, f, indent=2)

    def _log_summary_from_dir(self, output_dir):
        ext_counts = {}
        for root, _dirs, files in os.walk(output_dir):
            for f in files:
                if f.startswith("."):
                    continue
                _, ext = os.path.splitext(f)
                ext = ext.lower()
                if ext:
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1

        if not ext_counts:
            return
        self.log("--- Extracted Content Summary ---")
        for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1])[:15]:
            self.log(f"  {ext}: {count} files")
        if len(ext_counts) > 15:
            self.log(f"  ... and {len(ext_counts) - 15} more types")


# ---------------------------------------------------------------------------
# Write pipeline (modified assets folder → installable game file)
# ---------------------------------------------------------------------------

class WritePipeline(_BasePipeline):

    def __init__(self, original_path, assets_dir, output_path,
                 log_cb, phase_cb, progress_cb, done_cb,
                 indeterminate_cb=None, keep_audio_length=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb,
                         indeterminate_cb)
        # original_path is accepted for unified-contract compatibility but
        # is unused — Spooky reads format/game from .spooky_meta written
        # by the Extract step.
        del original_path
        self.assets_dir = assets_dir
        self.output_path = output_path
        self.keep_audio_length = keep_audio_length
        self.audio_actions = {}

    def _run_phases(self):
        # Phase 0: Detect
        self.phase(0)

        meta_path = os.path.join(self.assets_dir, META_FILE)
        if not os.path.isfile(meta_path):
            self.done(False,
                f"No {META_FILE} file found in:\n  {self.assets_dir}\n\n"
                f"Run Extract first to extract assets.")
            return
        with open(meta_path) as f:
            meta = json.load(f)

        format_type = meta["format"]
        game_name = meta["game"]
        ext = meta.get("ext", "")
        self.log(f"Game: {game_name} ({ext})")

        if format_type in ("clonezilla", "aes_pkg"):
            self.done(False,
                f"This game format ({format_type}) cannot be re-packaged.\n\n"
                f"You can view and extract the assets, but creating a valid "
                f"update file is not possible for this format.")
            return

        # Phase 1: Scan changes (the unified WRITE_PHASES is
        # ["Detect", "Scan", "Repack", "Cleanup"])
        self.phase(1)
        changed, added, removed = self._scan_changes()
        total_changes = len(changed) + len(added) + len(removed)
        if total_changes == 0:
            self.done(False,
                "No changes detected. Modify some files in the assets "
                "folder and try again.")
            return

        self.log(f"Changes detected: {len(changed)} modified, "
                 f"{len(added)} added, {len(removed)} removed", "success")
        for f in changed[:10]:
            self.log(f"  Modified: {f}")
        for f in added[:10]:
            self.log(f"  Added: {f}")
        for f in removed[:10]:
            self.log(f"  Removed: {f}")
        if total_changes > 30:
            self.log(f"  ... and {total_changes - 30} more")

        if self.cancelled:
            self.done(False, "Cancelled")
            return

        self._process_audio(changed)
        if self.cancelled:
            self.done(False, "Cancelled")
            return

        # Phase 2: Repack
        self.phase(2)
        if not self._build_output(format_type):
            return

        if self.cancelled:
            self.done(False, "Cancelled")
            return

        # Phase 3: Cleanup / Done
        self.phase(3)
        naming = USB_NAMING.get(ext, os.path.basename(self.output_path))
        self.log("--- Installation Instructions ---")
        self.log(f"1. Copy to USB drive root")
        self.log(f"2. Naming convention: {naming}")
        self.log("3. Insert USB into machine and follow update prompts")

        self.done(True,
            f"Successfully packaged modified {game_name} assets to:\n"
            f"{self.output_path}\n\n"
            f"USB naming: {naming}")

    # ------------------------------------------------------------------
    # Format dispatch
    # ------------------------------------------------------------------

    def _build_output(self, format_type):
        out = self.output_path
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

        if format_type in ("rm_pkg", "ac_pkg"):
            return self._build_aes_pkg(format_type)
        if format_type in ("um_pkg", "h78_pkg"):
            return self._build_gpg_symmetric_pkg(format_type)
        if format_type == "tar_gz":
            self.log("Creating tar.gz archive...")
            create_tar_gz(self.assets_dir, out,
                          progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"Archive created: "
                     f"{os.path.getsize(out) / (1024**3):.2f} GB", "success")
            return True
        if format_type == "plain_tar":
            self.log("Creating tar archive...")
            create_tar(self.assets_dir, out,
                       progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"Archive created: "
                     f"{os.path.getsize(out) / (1024**3):.2f} GB", "success")
            return True
        if format_type == "plain_zip":
            self.log("Creating ZIP archive...")
            create_zip(self.assets_dir, out,
                       progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"ZIP created: "
                     f"{os.path.getsize(out) / (1024**3):.2f} GB", "success")
            return True
        if format_type == "gpg_tar_gz":
            return self._build_gpg_tar_gz()

        self.done(False, f"Cannot re-package format: {format_type}")
        return False

    def _build_aes_pkg(self, format_type):
        key = AES_KEYS[format_type]
        self.log("Creating ZIP archive...")
        temp_zip = self.output_path + ".tmp.zip"
        try:
            create_zip(self.assets_dir, temp_zip,
                       progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"ZIP created: "
                     f"{os.path.getsize(temp_zip) / (1024**3):.2f} GB",
                     "success")
            if self.cancelled:
                return False
            self.log("Encrypting with AES-256-CBC...")
            encrypt_aes_pkg(temp_zip, self.output_path, key,
                            progress_cb=lambda d, t: self.progress(d, t,
                                                                  "Encrypting..."))
            self.log(f"Encrypted .pkg: "
                     f"{os.path.getsize(self.output_path) / (1024**3):.2f} GB",
                     "success")
        finally:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
        return True

    def _build_gpg_symmetric_pkg(self, format_type):
        passphrase = GPG_PASSPHRASES[format_type]
        self.log("Creating tar.gz archive...")
        temp_tar = self.output_path + ".tmp.tar.gz"
        try:
            create_tar_gz(self.assets_dir, temp_tar,
                          progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"tar.gz created: "
                     f"{os.path.getsize(temp_tar) / (1024**3):.2f} GB",
                     "success")
            if self.cancelled:
                return False
            self.log("Encrypting with GPG symmetric (AES-256)...")
            encrypt_gpg_symmetric(temp_tar, self.output_path, passphrase,
                                  progress_cb=lambda d, t: self.progress(d, t,
                                                                        "Encrypting..."))
            self.log(f"Encrypted .pkg: "
                     f"{os.path.getsize(self.output_path) / (1024**3):.2f} GB",
                     "success")
        finally:
            if os.path.exists(temp_tar):
                os.remove(temp_tar)
        return True

    def _build_gpg_tar_gz(self):
        self.log("Creating tar.gz archive...")
        temp_tar = self.output_path + ".tmp.tar.gz"
        try:
            create_tar_gz(self.assets_dir, temp_tar,
                          progress_cb=lambda d, t, n: self.progress(d, t, n))
            self.log(f"tar.gz created: "
                     f"{os.path.getsize(temp_tar) / (1024**3):.2f} GB",
                     "success")
            if self.cancelled:
                return False
            self.log("Wrapping in GPG signed message...")
            self.log("Note: signed with throwaway key - machine will show "
                     "signature warning (operator clicks AGREE to proceed)",
                     "warning")
            sign_beetlejuice(temp_tar, self.output_path,
                             progress_cb=lambda d, t: self.progress(d, t,
                                                                   "Signing..."))
            self.log(f"Signed .beetlejuice: "
                     f"{os.path.getsize(self.output_path) / (1024**3):.2f} GB",
                     "success")
        finally:
            if os.path.exists(temp_tar):
                os.remove(temp_tar)
        return True

    # ------------------------------------------------------------------
    # Change scanner + audio fixup
    # ------------------------------------------------------------------

    def _scan_changes(self):
        from ...core.checksums import read_checksums

        baseline = read_checksums(self.assets_dir)

        changed = []
        current = set()
        for root, _dirs, files in os.walk(self.assets_dir):
            for fname in files:
                if fname.startswith("."):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, self.assets_dir).replace("\\", "/")
                current.add(rel)
                if rel in baseline:
                    h = hashlib.md5()
                    with open(full, "rb") as fh:
                        for chunk in iter(lambda: fh.read(65536), b""):
                            h.update(chunk)
                    if h.hexdigest() != baseline[rel]:
                        changed.append(rel)

        added = [f for f in current if f not in baseline]
        removed = [f for f in baseline if f not in current]
        return changed, added, removed

    def _process_audio(self, changed_files):
        from .audio import detect_audio_info

        audio_exts = {".wav", ".ogg"}
        audio_files = [f for f in changed_files
                       if os.path.splitext(f)[1].lower() in audio_exts]
        if not audio_files:
            return

        self.log(f"Processing {len(audio_files)} modified audio file(s)...")
        for i, rel_path in enumerate(audio_files):
            if self.cancelled:
                return
            full_path = os.path.join(self.assets_dir, rel_path)
            if not os.path.isfile(full_path):
                continue
            current_info = detect_audio_info(full_path)
            if current_info is None:
                continue
            actions = []
            if current_info.compressed:
                from .audio import _ffmpeg_convert_wav
                if _ffmpeg_convert_wav(full_path, current_info):
                    actions.append(f"converted {current_info.codec} to PCM")
            if actions:
                self.audio_actions[rel_path] = actions
                self.log(f"  {rel_path}: {'; '.join(actions)}")
            self.progress(i + 1, len(audio_files),
                          f"Audio: {os.path.basename(rel_path)}")

        if self.audio_actions:
            self.log(f"Processed {len(self.audio_actions)} audio file(s)",
                     "success")
