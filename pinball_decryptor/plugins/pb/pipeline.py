"""Extract / Write / ISO-extract pipelines for Pinball Brothers `.upd` files.

PB `.upd` files are plain gzip+tar archives — no encryption.
"""

import os
import tarfile

from ...core import clonezilla
from ...core.checksums import (CHECKSUMS_FILE, generate_checksums,
                               md5_file, read_checksums)
from ...core.executor import CommandError, create_executor
from ...core.pipeline_base import BasePipeline, PipelineError
from ...core.tar_utils import format_size, safe_member, truncation_hint
from .formats import detect_game, detect_iso_game
from .games import GAME_DB


# ---------------------------------------------------------------------------
# Extract pipeline (.upd → folder)
# ---------------------------------------------------------------------------

class ExtractPipeline(BasePipeline):
    """Decompress + untar a `.upd` file into the output directory."""

    def __init__(self, upd_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.upd_path = upd_path
        self.output_dir = output_dir

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        game_key = detect_game(self.upd_path)
        if game_key is None:
            raise PipelineError("Detect",
                f"Cannot identify game from: {os.path.basename(self.upd_path)}\n\n"
                f"The file does not match any known PB game layout.\n"
                f"Expected internal paths under one of: "
                f"{', '.join(info['internal_dir'] for info in GAME_DB.values())}.")
        info = GAME_DB[game_key]
        self._log(f"Game detected: {info['display']}", "success")
        self._check_cancel()

        os.makedirs(self.output_dir, exist_ok=True)

        self._set_phase(1)
        self._log("Extracting archive...", "info")

        try:
            with tarfile.open(self.upd_path, "r:gz") as tar:
                members = tar.getmembers()
                total = len(members)
                self._log(f"  {total} entries found.", "info")
                for i, m in enumerate(members):
                    self._check_cancel()
                    safe = safe_member(m, self.output_dir)
                    if safe is None:
                        self._log(f"  Skipping unsafe entry: {m.name}", "error")
                        continue
                    tar.extract(safe, self.output_dir, set_attrs=True)
                    if i % 25 == 0 or i == total - 1:
                        self._progress(i + 1, total, safe.name)
        except (tarfile.TarError, EOFError) as e:
            raise PipelineError("Extract",
                truncation_hint(self.upd_path, e,
                    "Try re-downloading from Pinball Brothers' support portal:\n"
                    "  https://www.pinballbrothers.com/games/<game>/updates/"))
        except OSError as e:
            msg = str(e)
            if "Compressed file ended" in msg or "unexpected end" in msg.lower():
                raise PipelineError("Extract",
                    truncation_hint(self.upd_path, e,
                        "Try re-downloading from Pinball Brothers' support portal."))
            raise PipelineError("Extract", f"Filesystem error: {e}")

        self._log("Archive extracted.", "success")
        self._check_cancel()

        self._set_phase(2)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress)

        self._set_phase(3)
        self._log("Done.", "success")
        self._done(True,
            f"{info['display']} extracted successfully.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n}")


# ---------------------------------------------------------------------------
# Clonezilla ISO extract pipeline
# ---------------------------------------------------------------------------

class IsoExtractPipeline(BasePipeline):
    """Extract game files from a Pinball Brothers Clonezilla ISO."""

    def __init__(self, iso_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.iso_path = iso_path
        self.output_dir = output_dir
        self.executor = create_executor()

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game from ISO filename...", "info")
        game_key = detect_iso_game(self.iso_path)
        if game_key is None:
            raise PipelineError("Detect",
                f"Cannot identify game from ISO: "
                f"{os.path.basename(self.iso_path)}\n\n"
                f"Recognised filename hints: alien40, queen.")
        info = GAME_DB[game_key]
        iso_cfg = info.get("iso") or {}
        self._log(f"Game detected: {info['display']}", "success")
        self._check_cancel()

        prereq = clonezilla.check_prerequisites(self.executor)
        missing = [(n, m) for n, ok, m in prereq if not ok]
        if missing:
            lines = "\n".join(f"  {n}: {m}" for n, m in missing)
            raise PipelineError("Detect",
                f"Missing prerequisites:\n{lines}\n\n"
                f"On Windows, install in WSL with:\n"
                f"  wsl -u root apt-get install -y e2fsprogs gzip")

        os.makedirs(self.output_dir, exist_ok=True)

        self._set_phase(1)
        try:
            clonezilla.extract(
                self.iso_path, self.output_dir, self.executor,
                preferred_partition=iso_cfg.get("partition"),
                subtrees=iso_cfg.get("subtrees", ["/game", "/opt/game"]),
                display_name=info["display"],
                log_cb=self._log, progress_cb=self._progress,
            )
        except RuntimeError as e:
            raise PipelineError("Extract", str(e))
        except CommandError as e:
            raise PipelineError("Extract", f"Executor error: {e}")

        self._check_cancel()

        self._set_phase(2)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress)

        self._set_phase(3)
        self._log("Done.", "success")
        self._done(True,
            f"{info['display']} extracted from Clonezilla ISO.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n}\n\n"
            f"Scoped to the game subtree(s) — system files and symlinks are "
            f"skipped so Windows Explorer can manage the folder cleanly.")


# ---------------------------------------------------------------------------
# Write pipeline (assets folder → .upd)
# ---------------------------------------------------------------------------

class WritePipeline(BasePipeline):
    """Re-pack assets into a new `.upd`, preserving the original layout."""

    def __init__(self, original_upd, assets_dir, output_upd,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_upd = original_upd
        self.assets_dir = assets_dir
        self.output_upd = output_upd

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        game_key = detect_game(self.original_upd)
        if game_key is None:
            raise PipelineError("Detect",
                f"Cannot identify game from: "
                f"{os.path.basename(self.original_upd)}.")
        info = GAME_DB[game_key]
        self._log(f"Game: {info['display']}", "success")
        self._check_cancel()

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
            if not os.path.isfile(abs_path):
                continue
            if md5_file(abs_path) != orig_md5:
                changed[rel] = abs_path

        if changed:
            self._log(f"  {len(changed)} modified file(s):", "info")
            for rel in sorted(changed)[:25]:
                self._log(f"    {rel}", "info")
            if len(changed) > 25:
                self._log(f"    ... and {len(changed) - 25} more", "info")
        else:
            self._log("  No modified files found.", "info")
            self._log("  The output `.upd` will be a byte-for-byte rebuild of "
                      "the original (useful as a smoke test).", "info")

        self._check_cancel()

        self._set_phase(2)
        self._log(f"Building {os.path.basename(self.output_upd)}...", "info")
        try:
            os.makedirs(os.path.dirname(self.output_upd) or ".", exist_ok=True)
            self._repack(changed)
        except (tarfile.TarError, OSError) as e:
            raise PipelineError("Repack", f"Repack failed: {e}")

        self._check_cancel()

        self._set_phase(3)
        size = os.path.getsize(self.output_upd)
        self._log(f"  Output size: {format_size(size)}", "info")
        self._log("Done.", "success")

        msg = (f"{info['display']} update file built successfully.\n\n"
               f"Output: {self.output_upd}\n"
               f"Modified files: {len(changed)}\n\n"
               f"Copy to a FAT32 USB drive and insert it into the machine "
               f"to install.")
        self._done(True, msg)

    def _repack(self, changed):
        with tarfile.open(self.original_upd, "r:gz") as src:
            members = src.getmembers()
            total = len(members)

            orig_paths = {self._norm_member_name(m.name) for m in members}
            sample_name = members[0].name if members else ""
            name_prefix = "./" if sample_name.startswith("./") else ""

            with tarfile.open(self.output_upd, "w:gz",
                              format=tarfile.GNU_FORMAT) as dst:
                for i, m in enumerate(members):
                    self._check_cancel()

                    rel = self._norm_member_name(m.name)
                    rel_alt = m.name.replace("\\", "/")

                    if m.isfile() and (rel in changed or rel_alt in changed):
                        new_path = changed.get(rel) or changed.get(rel_alt)
                        new_size = os.path.getsize(new_path)
                        new_m = tarfile.TarInfo(name=m.name)
                        new_m.size = new_size
                        new_m.mtime = int(os.path.getmtime(new_path))
                        new_m.mode = m.mode
                        new_m.uid = m.uid
                        new_m.gid = m.gid
                        new_m.uname = m.uname
                        new_m.gname = m.gname
                        new_m.type = m.type
                        with open(new_path, "rb") as f:
                            dst.addfile(new_m, f)
                    elif m.isfile():
                        f = src.extractfile(m)
                        if f is None:
                            dst.addfile(m)
                        else:
                            dst.addfile(m, f)
                    else:
                        dst.addfile(m)

                    if i % 25 == 0 or i == total - 1:
                        self._progress(i + 1, total, m.name)

                extras = self._find_extra_files(orig_paths)
                if extras:
                    self._log(f"  {len(extras)} new file(s) on disk not in "
                              f"the original — appending to output.", "info")
                    for j, (rel, abs_path) in enumerate(extras):
                        self._check_cancel()
                        member_name = name_prefix + rel
                        new_m = tarfile.TarInfo(name=member_name)
                        new_m.size = os.path.getsize(abs_path)
                        new_m.mtime = int(os.path.getmtime(abs_path))
                        new_m.mode = self._guess_mode(abs_path, rel)
                        new_m.uid = 0
                        new_m.gid = 0
                        new_m.uname = ""
                        new_m.gname = ""
                        new_m.type = tarfile.REGTYPE
                        with open(abs_path, "rb") as f:
                            dst.addfile(new_m, f)
                        if j % 25 == 0 or j == len(extras) - 1:
                            self._progress(j + 1, len(extras),
                                           f"appending: {rel}")

    @staticmethod
    def _norm_member_name(name):
        return name.lstrip("./").replace("\\", "/")

    def _find_extra_files(self, original_paths):
        extras = []
        for dirpath, _, filenames in os.walk(self.assets_dir):
            for fn in filenames:
                if fn.startswith("."):
                    continue
                abs_path = os.path.join(dirpath, fn)
                if os.path.islink(abs_path):
                    continue
                rel = (os.path.relpath(abs_path, self.assets_dir)
                       .replace("\\", "/"))
                if rel in original_paths:
                    continue
                extras.append((rel, abs_path))
        extras.sort()
        return extras

    @staticmethod
    def _guess_mode(abs_path, rel):
        basename = os.path.basename(rel).lower()
        if basename in {"pinprog", "vidprog"} or basename.endswith(".sh"):
            return 0o755
        try:
            if os.access(abs_path, os.X_OK):
                return 0o755
        except OSError:
            pass
        return 0o644


# ---------------------------------------------------------------------------
# Apply delta (overlay a delta .upd onto an extracted assets folder)
# ---------------------------------------------------------------------------

def apply_delta(assets_folder, delta_upd_path,
                log_cb=None, progress_cb=None):
    """Untar a delta `.upd` on top of an extracted assets folder.

    Returns ``(overwritten_count, added_count, total_in_delta)``.
    """
    if not os.path.isdir(assets_folder):
        raise ValueError(f"Assets folder does not exist: {assets_folder}")
    if not os.path.isfile(delta_upd_path):
        raise ValueError(f"Delta file not found: {delta_upd_path}")

    if log_cb:
        log_cb(f"Applying delta: {os.path.basename(delta_upd_path)}", "info")

    overwritten = 0
    added = 0
    total = 0

    with tarfile.open(delta_upd_path, "r:gz") as tar:
        members = tar.getmembers()
        total = len(members)
        if log_cb:
            log_cb(f"  {total} entries in delta.", "info")
        for i, m in enumerate(members):
            safe = safe_member(m, assets_folder)
            if safe is None:
                if log_cb:
                    log_cb(f"  Skipping unsafe entry: {m.name}", "error")
                continue
            target = os.path.join(assets_folder, safe.name)
            existed = os.path.lexists(target)
            tar.extract(safe, assets_folder, set_attrs=True)
            if safe.isfile():
                if existed:
                    overwritten += 1
                else:
                    added += 1
            if progress_cb and (i % 25 == 0 or i == total - 1):
                progress_cb(i + 1, total, safe.name)

    if log_cb:
        log_cb(f"Delta applied: {added} new file(s), "
               f"{overwritten} overwritten.", "success")
        log_cb("Baseline checksums left untouched — the delta's changes will "
               "be detected as modifications and included in the next "
               "Build update output.", "info")

    return overwritten, added, total
