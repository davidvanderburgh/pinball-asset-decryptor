"""Extract / Write / Apply-delta pipelines for Dutch Pinball games.

TBL updates are plain ``.zip`` archives; AAIW ships as a Clonezilla
installer ``.img`` (see :mod:`.aaiw`).  Neither is encrypted.
"""

import os
import zipfile

from ...core.checksums import (generate_checksums, md5_file, read_checksums)
from ...core.executor import CommandError, create_executor
from ...core.pipeline_base import BasePipeline, PipelineError
from ...core.tar_utils import format_size
from . import aaiw, cdmd, ssd
from .formats import detect_game
from .games import GAME_DB

# Decoded cdmd videos land here (kept out of the modding baseline so they
# are never re-packed into a built update).
DECODED_DIR = "_DECODED VIDEOS"


# ---------------------------------------------------------------------------
# Shared zip helpers
# ---------------------------------------------------------------------------

def _safe_zip_targets(zf, dest_dir):
    """Yield ``(ZipInfo, abs_target)`` for entries that stay inside *dest_dir*."""
    dest_abs = os.path.abspath(dest_dir)
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            yield info, None
            continue
        target = os.path.abspath(os.path.join(dest_dir, *name.split("/")))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            yield info, None
            continue
        yield info, target


# ---------------------------------------------------------------------------
# TBL Extract (.zip → folder, then decode .cdmd videos)
# ---------------------------------------------------------------------------

class TblExtractPipeline(BasePipeline):
    """Unzip a TBL update and decode its ``.cdmd`` videos to MP4/PNG."""

    def __init__(self, zip_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb, dmd=False,
                 deltas=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.zip_path = zip_path
        self.output_dir = output_dir
        self.dmd = dmd
        self.deltas = list(deltas or [])

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        if detect_game(self.zip_path) != "tbl":
            raise PipelineError("Detect",
                f"{os.path.basename(self.zip_path)} is not a recognised "
                f"Big Lebowski update zip.")
        self._log("Game detected: The Big Lebowski", "success")
        os.makedirs(self.output_dir, exist_ok=True)
        self._check_cancel()

        self._set_phase(1)
        self._log("Extracting update archive...", "info")
        try:
            with zipfile.ZipFile(self.zip_path) as zf:
                entries = list(_safe_zip_targets(zf, self.output_dir))
                total = len(entries)
                self._log(f"  {total} entries found.", "info")
                for i, (info, target) in enumerate(entries):
                    self._check_cancel()
                    if target is None:
                        self._log(f"  Skipping unsafe entry: {info.filename}",
                                  "error")
                        continue
                    if info.is_dir():
                        os.makedirs(target, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                    if i % 25 == 0 or i == total - 1:
                        self._progress(i + 1, total, info.filename)
        except (zipfile.BadZipFile, OSError) as e:
            raise PipelineError("Extract", f"Failed to extract zip: {e}")
        self._log("Archive extracted.", "success")
        self._check_cancel()

        base_version = _detect_base_version(self.output_dir)

        # Baseline checksums of the *pristine* base, BEFORE applying any
        # deltas — so a later Build picks up the deltas' changes (and the
        # user's edits) as modifications and folds them into the update.
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress,
            exclude_dirs=[DECODED_DIR])

        # Auto-apply any supplied delta updates on top of the base, in
        # version order, remapping each onto the base's version folder.
        applied = []
        compatible = []
        if self.deltas:
            self._log(f"Merging {len(self.deltas)} update(s) on top of "
                      f"{base_version or 'the base image'}...", "info")
            try:
                applied, compatible = chain_deltas(
                    self.output_dir, self.deltas,
                    log_cb=self._log, progress_cb=self._progress)
            except ValueError as e:
                raise PipelineError("Extract", str(e))
            if applied:
                self._log(f"Merged up to version {applied[-1]}.", "success")
        self._check_cancel()

        # Record how this was merged so Build can label the rebuilt update one
        # version newer than the merged version (and list the right bases).
        merged_version = applied[-1] if applied else base_version
        if not compatible:
            from .formats import delta_info, version_key
            try:
                _bv, base_compat = delta_info(self.zip_path)
            except Exception:
                base_compat = None
            seed = set(base_compat or [])
            if base_version:
                seed.add(base_version)
            compatible = sorted(seed, key=version_key)
        if base_version:
            write_build_meta(self.output_dir, base_version, merged_version,
                             compatible)

        # Phase 2: decode .cdmd colour-display videos (post-merge content).
        self._set_phase(2)
        if self.dmd:
            self._log("Decoding .cdmd videos with dot-matrix effect "
                      "(this is slower)...", "info")
        else:
            self._log("Decoding .cdmd videos...", "info")
        decoded_dir = os.path.join(self.output_dir, DECODED_DIR)
        try:
            n_ok, n_fail = cdmd.convert_all_cdmd(
                self.output_dir, decoded_dir,
                progress_cb=self._progress, log_cb=self._log,
                cancel_cb=lambda: self._cancelled, dmd=self.dmd)
        except Exception as e:
            self._log(f"  Video decode step failed: {e}", "warning")
            n_ok = 0
        self._check_cancel()

        self._set_phase(3)
        # base_version can be None when the base zip carries no detectable
        # version (e.g. a full image) — every other use of it guards for that,
        # and this summary join must too, or it raises "sequence item 0:
        # expected str instance, NoneType found" after a successful extract.
        chain = [base_version or "base image"] + [a for a in applied if a]
        merged = (f"\nMerged updates: {' -> '.join(chain)}"
                  if applied else "")
        self._done(True,
            f"The Big Lebowski extracted successfully.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n}{merged}\n"
            f"Decoded videos: {n_ok} (in '{DECODED_DIR}')")


# ---------------------------------------------------------------------------
# AAIW Extract (Clonezilla installer .img → folder)
# ---------------------------------------------------------------------------

class AaiwExtractPipeline(BasePipeline):
    """Reconstruct the AAIW SSD image and copy its asset subtree out."""

    def __init__(self, img_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb, convert_video=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.img_path = img_path
        self.output_dir = output_dir
        self.convert_video = convert_video
        self.executor = create_executor()

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        if detect_game(self.img_path) != "aaiw":
            raise PipelineError("Detect",
                f"{os.path.basename(self.img_path)} is not a recognised "
                f"AAIW installer image.")
        self._log("Game detected: Alice's Adventures in Wonderland", "success")

        # The extractor prefers local 7-Zip (fast, no WSL) and falls back to
        # WSL; it raises a clear error if neither is available — so no hard
        # WSL pre-check here.
        if aaiw.find_7z():
            self._log("Using 7-Zip (fast local extraction).", "info")
        else:
            self._log("7-Zip not found — using WSL fallback "
                      "(slower; install 7-Zip for a big speed-up).", "info")
        self._check_cancel()

        self._set_phase(1)
        try:
            n = aaiw.extract(
                self.img_path, self.output_dir, self.executor,
                display_name="Alice's Adventures in Wonderland",
                log_cb=self._log, progress_cb=self._progress,
                cancel_cb=lambda: self._cancelled)
        except RuntimeError as e:
            raise PipelineError("Extract", str(e))
        except CommandError as e:
            raise PipelineError("Extract", f"Executor error: {e}")
        self._check_cancel()

        # Optional: convert ProRes .mov videos to playable H.264 .mp4.
        if self.convert_video:
            self._set_phase(2)
            aaiw.convert_movs_to_mp4(
                self.output_dir, log_cb=self._log,
                progress_cb=self._progress,
                cancel_cb=lambda: self._cancelled)
            self._check_cancel()

        self._set_phase(3)
        self._log("Generating baseline checksums...", "info")
        n_ck = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress)

        self._done(True,
            f"Alice's Adventures in Wonderland assets extracted.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n_ck}\n\n"
            f"Standard .mp4 / .mov / .wav / .png assets — edit in place. "
            f"(Re-imaging the SSD to install mods is not yet supported.)")


# ---------------------------------------------------------------------------
# Direct-SSD Extract / Write (read/write a physically-connected game SSD)
# ---------------------------------------------------------------------------

class DpDirectSsdExtractPipeline(BasePipeline):
    """Copy the game asset subtree directly off a connected game SSD."""

    def __init__(self, device_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.output_dir = output_dir
        self.partition_override = partition_override
        self.executor = create_executor()

    def _run(self):
        self._set_phase(0)  # Mount
        try:
            ssd.extract_from_ssd(
                self.device_path, self.output_dir, self.executor,
                partition_override=self.partition_override,
                log_cb=self._log, progress_cb=self._progress,
                cancel_cb=lambda: self._cancelled)
        except RuntimeError as e:
            raise PipelineError("Extract", str(e))
        except CommandError as e:
            raise PipelineError("Extract", f"Executor error: {e}")
        self._check_cancel()

        self._set_phase(1)  # Checksums
        self._log("Generating baseline checksums...", "info")
        n_ck = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress)
        self._done(True,
            f"Extracted {n_ck} asset file(s) directly from the game SSD.\n\n"
            f"Output: {self.output_dir}\n\n"
            f"Edit files in place, then use Write -> \"Write to SSD\" to apply "
            f"them. Always keep a backup of the machine first.")


class DpDirectSsdWritePipeline(BasePipeline):
    """Write modified asset files directly back onto a connected game SSD."""

    def __init__(self, device_path, assets_dir,
                 log_cb, phase_cb, progress_cb, done_cb,
                 partition_override=None):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.device_path = device_path
        self.assets_dir = assets_dir
        self.partition_override = partition_override
        self.executor = create_executor()

    def _run(self):
        self._set_phase(0)  # Scan
        self._log("Scanning for modified files...", "info")
        baseline = read_checksums(self.assets_dir)
        if not baseline:
            raise PipelineError("Scan",
                f"No baseline checksums in:\n  {self.assets_dir}\n\n"
                f"Run \"Extract from SSD\" first to create them.")
        changed = []
        for rel, orig_md5 in baseline.items():
            abs_path = os.path.join(self.assets_dir, rel)
            if os.path.isfile(abs_path) and md5_file(abs_path) != orig_md5:
                changed.append((rel, abs_path))
        if not changed:
            self._done(True,
                "No modified files — the SSD already matches your assets "
                "folder. Nothing written.")
            return
        self._log(f"  {len(changed)} modified file(s):", "info")
        for rel, _ in sorted(changed)[:25]:
            self._log(f"    {rel}", "info")
        if len(changed) > 25:
            self._log(f"    ... and {len(changed) - 25} more", "info")
        self._check_cancel()

        self._set_phase(1)  # Mount + Write
        try:
            written = ssd.write_to_ssd(
                self.device_path, changed, self.executor,
                partition_override=self.partition_override,
                log_cb=self._log, progress_cb=self._progress,
                cancel_cb=lambda: self._cancelled)
        except RuntimeError as e:
            raise PipelineError("Write", str(e))
        except CommandError as e:
            raise PipelineError("Write", f"Executor error: {e}")

        self._done(True,
            f"Wrote {written} modified file(s) directly to the game SSD.\n\n"
            f"Reboot the machine to load the changes. If anything misbehaves, "
            f"restore from your backup.")


# ---------------------------------------------------------------------------
# TBL Write (assets folder → new update .zip)
# ---------------------------------------------------------------------------

class TblWritePipeline(BasePipeline):
    """Rebuild a TBL update zip, swapping in modified files from the folder."""

    def __init__(self, original_zip, assets_dir, output_zip,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_zip = original_zip
        self.assets_dir = assets_dir
        self.output_zip = output_zip

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        if detect_game(self.original_zip) != "tbl":
            raise PipelineError("Detect",
                f"{os.path.basename(self.original_zip)} is not a TBL update "
                f"zip. (Write-back is supported for The Big Lebowski only; "
                f"AAIW SSD re-imaging is out of scope.)")
        if not os.path.isdir(self.assets_dir):
            raise PipelineError("Detect",
                f"Assets folder not found: {self.assets_dir}")
        self._log("Game: The Big Lebowski", "success")
        self._check_cancel()

        self._set_phase(1)
        self._log("Scanning for modified files...", "info")
        baseline = read_checksums(self.assets_dir)
        if not baseline:
            raise PipelineError("Scan",
                f"No baseline checksums in:\n  {self.assets_dir}\n\n"
                f"Run Extract first to create them.")
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
            self._log("  No modified files — output will rebuild the original.",
                      "info")
        self._check_cancel()

        self._set_phase(2)
        from .formats import bump_version, top_version
        with zipfile.ZipFile(self.original_zip) as _z0:
            base_version = top_version(_z0.namelist())
        meta = read_build_meta(self.assets_dir) or {}
        merged_version = meta.get("merged_version") or base_version
        compatible = meta.get("compatible_bases") or (
            [merged_version] if merged_version else [])
        target_version = bump_version(merged_version) if merged_version else None
        if target_version:
            self._log(f"Labeling the built update version {target_version} — "
                      f"one newer than {merged_version}, so the machine's USB "
                      f"update will accept it.", "info")
            if compatible:
                self._log(f"  Installs onto machines running: "
                          f"{', '.join(compatible)}.", "info")

        self._log(f"Building {os.path.basename(self.output_zip)}...", "info")
        try:
            os.makedirs(os.path.dirname(self.output_zip) or ".", exist_ok=True)
            self._rebuild(changed, base_version, target_version, compatible)
        except (zipfile.BadZipFile, OSError) as e:
            raise PipelineError("Repack", f"Repack failed: {e}")
        self._check_cancel()

        self._set_phase(3)
        size = os.path.getsize(self.output_zip)
        self._log(f"  Output size: {format_size(size)}", "info")
        ver_line = f"New version: {target_version}\n" if target_version else ""
        name_tip = (f"Name the file TBL-v{target_version}.zip. " if target_version
                    else "")
        self._done(True,
            f"The Big Lebowski update built successfully.\n\n"
            f"Output: {self.output_zip}\n"
            f"{ver_line}"
            f"Modified files: {len(changed)}\n\n"
            f"{name_tip}Copy it (do not unzip) to the root of a USB stick and "
            f"install from Service -> Software -> USB Update.")

    def _rebuild(self, changed, base_version, target_version, compatible):
        # Remap the base version prefix to the (newer) target version so the
        # machine treats the build as a fresh update, and write a fresh delta
        # marker listing the versions it can install onto.
        def remap(name):
            norm = name.replace("\\", "/")
            if (base_version and target_version
                    and norm.startswith(base_version + "/")):
                return target_version + "/" + norm[len(base_version) + 1:]
            return norm

        delta_marker = f"{base_version}/delta" if base_version else None
        with zipfile.ZipFile(self.original_zip) as src:
            members = src.infolist()
            total = len(members)
            orig_names = {m.filename.replace("\\", "/") for m in members}
            with zipfile.ZipFile(self.output_zip, "w",
                                 zipfile.ZIP_DEFLATED) as dst:
                for i, m in enumerate(members):
                    self._check_cancel()
                    rel = m.filename.replace("\\", "/")
                    # Drop the original delta marker — we write a fresh one.
                    if rel == delta_marker:
                        continue
                    out_name = remap(rel)
                    # Preserve the original member's mode/mtime under the
                    # remapped name (writestr with a copied ZipInfo).
                    zi = zipfile.ZipInfo(out_name, date_time=m.date_time)
                    zi.external_attr = m.external_attr
                    zi.internal_attr = m.internal_attr
                    zi.create_system = m.create_system
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    if m.is_dir():
                        dst.writestr(zi, b"")
                    elif rel in changed:
                        with open(changed[rel], "rb") as f:
                            dst.writestr(zi, f.read())
                    else:
                        dst.writestr(zi, src.read(m.filename))
                    if i % 25 == 0 or i == total - 1:
                        self._progress(i + 1, total, out_name)

                # Fresh delta marker so the machine knows which installed
                # versions this build can be applied on top of.
                if target_version and compatible:
                    dst.writestr(f"{target_version}/delta", ",".join(compatible))

                extras = self._find_extra_files(orig_names)
                if extras:
                    self._log(f"  Appending {len(extras)} new file(s).", "info")
                    for j, (rel, abs_path) in enumerate(extras):
                        self._check_cancel()
                        dst.write(abs_path, arcname=remap(rel))
                        if j % 25 == 0 or j == len(extras) - 1:
                            self._progress(j + 1, len(extras), f"append: {rel}")

    def _find_extra_files(self, original_names):
        extras = []
        for dirpath, dirnames, filenames in os.walk(self.assets_dir):
            rel_dir = os.path.relpath(dirpath, self.assets_dir).replace("\\", "/")
            if rel_dir == ".":
                rel_dir = ""
            # Never re-pack the derived decoded-videos folder.
            dirnames[:] = [d for d in dirnames
                           if (f"{rel_dir}/{d}" if rel_dir else d) != DECODED_DIR]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                abs_path = os.path.join(dirpath, fn)
                if os.path.islink(abs_path):
                    continue
                rel = (os.path.relpath(abs_path, self.assets_dir)
                       .replace("\\", "/"))
                if rel not in original_names:
                    extras.append((rel, abs_path))
        extras.sort()
        return extras


# ---------------------------------------------------------------------------
# Apply delta (overlay delta .zip(s) onto an extracted assets folder)
# ---------------------------------------------------------------------------
#
# TBL deltas wrap their files under their *own* version folder (e.g.
# ``1.15/...``) which differs from the full image's (``1.01/...``).  To
# overlay correctly we remap each delta entry's version prefix onto the base
# image's version folder, so the changed files land on top of the base tree
# instead of in a sibling folder.

def _detect_base_version(assets_folder):
    """Return the single ``<version>/`` folder in an extracted TBL tree."""
    try:
        entries = os.listdir(assets_folder)
    except OSError:
        return None
    versions = [e for e in entries
                if e and e[0].isdigit() and e != DECODED_DIR
                and os.path.isdir(os.path.join(assets_folder, e))]
    return versions[0] if len(versions) == 1 else None


def _apply_delta_zip(assets_folder, delta_zip_path, delta_version,
                     base_version, log_cb=None, progress_cb=None):
    """Overlay one delta zip, remapping ``delta_version/`` -> ``base_version/``.

    Returns ``(overwritten, added, total)``.
    """
    dest_abs = os.path.abspath(assets_folder)
    overwritten = added = total = 0
    with zipfile.ZipFile(delta_zip_path) as zf:
        infos = zf.infolist()
        total = len(infos)
        for i, info in enumerate(infos):
            norm = info.filename.replace("\\", "/").lstrip("/")
            # Remap the version prefix; drop the bare 'delta' marker.
            if (base_version and delta_version
                    and norm.startswith(delta_version + "/")):
                rest = norm[len(delta_version) + 1:]
                if rest in ("", "delta"):
                    continue
                rel = f"{base_version}/{rest}"
            else:
                rel = norm
            if not rel or ".." in rel.split("/"):
                continue
            target = os.path.abspath(os.path.join(assets_folder, *rel.split("/")))
            if target != dest_abs and not target.startswith(dest_abs + os.sep):
                if log_cb:
                    log_cb(f"  Skipping unsafe entry: {info.filename}", "error")
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            existed = os.path.exists(target)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            overwritten += existed
            added += not existed
            if progress_cb and (i % 25 == 0 or i == total - 1):
                progress_cb(i + 1, total, rel)
    return overwritten, added, total


def apply_delta(assets_folder, delta_zip_path, log_cb=None, progress_cb=None):
    """Overlay a single TBL delta update onto an extracted assets folder.

    Validates the delta is compatible with the extracted base version and
    remaps its version prefix so files overlay correctly (instead of landing
    in a sibling version folder).  Returns ``(overwritten, added, total)``.
    """
    from .formats import delta_info

    if not os.path.isdir(assets_folder):
        raise ValueError(f"Assets folder does not exist: {assets_folder}")
    if not os.path.isfile(delta_zip_path):
        raise ValueError(f"Delta file not found: {delta_zip_path}")

    dver, compat = delta_info(delta_zip_path)
    base = _detect_base_version(assets_folder)
    if compat is not None and base is not None and base not in compat:
        raise ValueError(
            f"Update {dver} can't be applied on top of version {base}.\n"
            f"It requires a base of one of: {', '.join(compat)}.\n"
            f"Extract a full image of a compatible version first.")

    if log_cb:
        label = dver or os.path.basename(delta_zip_path)
        log_cb(f"Applying update {label}"
               + (f" onto {base}" if base else "") + "...", "info")
    ov, ad, total = _apply_delta_zip(assets_folder, delta_zip_path, dver, base,
                                     log_cb=log_cb, progress_cb=progress_cb)
    if log_cb:
        log_cb(f"Update applied: {ad} new file(s), {ov} overwritten.", "success")
    return ov, ad, total


def chain_deltas(assets_folder, delta_paths, log_cb=None, progress_cb=None):
    """Apply several deltas in ascending version order onto a base tree.

    Each delta is validated against the running version (TBL deltas are
    cumulative, so the base usually satisfies all of them) and remapped onto
    the base version folder.  Returns ``(applied_versions, compatible_bases)``
    where *compatible_bases* unions the base, every applied version, and each
    delta's own compat list (the set of installed versions the merged result
    can later be installed onto).  Raises ValueError on an incompatible delta.
    """
    from .formats import delta_info, version_key

    base = _detect_base_version(assets_folder)
    metas = []
    for path in delta_paths:
        try:
            dver, compat = delta_info(path)
        except Exception as e:
            if log_cb:
                log_cb(f"  Skipping unreadable update "
                       f"{os.path.basename(path)}: {e}", "warning")
            continue
        if compat is None:
            if log_cb:
                log_cb(f"  {os.path.basename(path)} looks like a full image, "
                       f"not a delta — skipping.", "warning")
            continue
        metas.append((version_key(dver), dver, compat, path))
    metas.sort(key=lambda m: m[0])

    applied = []
    compat_union = {base} if base else set()
    running = base
    for _key, dver, compat, path in metas:
        if running is not None and running not in compat:
            raise ValueError(
                f"Update {dver} can't be applied on top of version {running}.\n"
                f"It needs one of: {', '.join(compat)}.\n"
                f"Supply a full image (or earlier delta) of a compatible "
                f"version.")
        if log_cb:
            log_cb(f"Applying update {dver} onto {running or 'assets'}...", "info")
        ov, ad, _tot = _apply_delta_zip(assets_folder, path, dver, base,
                                        log_cb=log_cb, progress_cb=progress_cb)
        if log_cb:
            log_cb(f"  {dver}: {ad} new, {ov} overwritten.", "info")
        applied.append(dver)
        compat_union.update(compat)
        compat_union.add(dver)
        running = dver
    compat_union.discard(None)
    return applied, sorted(compat_union, key=version_key)


# ---------------------------------------------------------------------------
# Build metadata — records how an extract was merged so the Write step can
# label the rebuilt update one version newer (and list the right bases).
# ---------------------------------------------------------------------------

BUILD_META = ".dp_build.json"


def write_build_meta(out_dir, base_version, merged_version, compatible_bases):
    import json
    data = {"base_version": base_version,
            "merged_version": merged_version,
            "compatible_bases": list(compatible_bases or [])}
    with open(os.path.join(out_dir, BUILD_META), "w", encoding="utf-8") as f:
        json.dump(data, f)


def read_build_meta(assets_dir):
    import json
    path = os.path.join(assets_dir, BUILD_META)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
