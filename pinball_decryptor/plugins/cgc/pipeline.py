"""Extract + Write pipelines for CGC `.img` installer files.

Both pipelines walk three layers of nested disk images:

    installer.img --[MBR]-> P3 (ext4) --[debugfs dump]-> emmc.img
    emmc.img      --[MBR]-> P2 (ext4) --[debugfs rdump]-> assets

Extract goes top->bottom and writes asset files to the user's output dir.
Write reverses the chain: replaces files in P2 with debugfs `-w`, writes
the modified emmc.img back into installer P3, then patches the modified
P3 bytes back into the original installer.img -- giving a USB-flashable
installer.img with the user's audio/binary/logo changes baked in.

We never re-create the .img from scratch -- it'd lose the FAT16 boot
partition's uBoot binaries.  We only patch the bytes inside the existing
ext4 partitions, preserving everything else byte-for-byte.

All ext4-aware work happens in the executor (WSL on Windows, native on
Linux, Docker on macOS) since Python has no in-tree ext4 writer.
"""

import os
import shutil
import subprocess
import sys

from ...core.checksums import (CHECKSUMS_FILE, generate_checksums,
                               md5_file, read_checksums)
from ...core.executor import CommandError, create_executor
from ...core.pipeline_base import BasePipeline, PipelineError
from ...core.transcribe import CALLOUTS_CSV
from .formats import (detect_game, find_data_partition, find_game_partition,
                      is_img_file, read_mbr_partitions)
from .games import GAME_DB


# Path of emmc.img inside the installer's P3 ext4 partition.  Same for
# every CGC title we've inspected -- package.dat hardcodes it.
EMMC_INNER_PATH = "/emmc.img"

# Subtree under the staging dir where we keep extracted partition images.
# Lives on the executor side (in WSL: /tmp/cgc_stage_<pid>/).


def _stage_dir_for(executor, run_id):
    """Return an executor-side staging path; safe for parallel runs."""
    return f"/tmp/cgc_stage_{run_id}"


# ---------------------------------------------------------------------------
# Extract pipeline
# ---------------------------------------------------------------------------

class ExtractPipeline(BasePipeline):
    """Extract assets from a CGC installer `.img`.

    Phase 0: Detect game from filename.
    Phase 1: Extract installer P3 -> staging, dump emmc.img out of it.
    Phase 2: Extract emmc.img P2 -> staging, rdump asset subtree to output.
    Phase 3: Generate baseline checksums + done.
    """

    def __init__(self, img_path, output_dir,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.img_path = img_path
        self.output_dir = output_dir
        self.executor = create_executor()

    def _exec_to_host(self, exec_path):
        """Inverse of ``executor.to_exec_path`` for our /tmp/cgc_stage_*
        staging paths.

        On Windows/WSL, ``/tmp/cgc_stage_<pid>`` on the WSL side is
        reachable from Windows at
        ``\\\\wsl.localhost\\<distro>\\tmp\\cgc_stage_<pid>``.  We can't
        ask the executor for the distro name without a subprocess call,
        but we can list the WSL distros once and cache.
        """
        if not exec_path.startswith("/"):
            return exec_path
        # Windows/WSL: \\wsl.localhost\Distro\<unix-path>
        import sys
        if sys.platform != "win32":
            return exec_path
        if not hasattr(self, "_wsl_distro"):
            self._wsl_distro = _detect_wsl_distro() or "Ubuntu"
        return rf"\\wsl.localhost\{self._wsl_distro}{exec_path.replace('/', os.sep)}"

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game from filename...", "info")
        if not is_img_file(self.img_path):
            raise PipelineError("Detect",
                f"Not a CGC installer .img: {os.path.basename(self.img_path)}\n"
                f"Expected a raw MBR-partitioned disk image (.img) shipped by "
                f"Chicago Gaming Company.")
        game_key = detect_game(self.img_path)
        if game_key is None:
            raise PipelineError("Detect",
                f"Cannot identify CGC game from filename: "
                f"{os.path.basename(self.img_path)}\n\n"
                f"Recognised hints: MedievalMadness, AttackFromMars, "
                f"MonsterBash, PulpFiction (case-insensitive).")
        info = GAME_DB[game_key]
        self._log(f"Game detected: {info['display']}", "success")
        self._log(f"  Platform: {info['platform']}", "info")
        self._check_cancel()

        _verify_executor_tools(self.executor)

        os.makedirs(self.output_dir, exist_ok=True)

        # Locate installer P3 (data) via the MBR — no executor calls needed.
        data_part = find_data_partition(self.img_path)
        self._log(
            f"  Installer P3 at sector {data_part['start_lba']} "
            f"({data_part['size_bytes'] / (1024 ** 3):.2f} GiB ext4)",
            "info")

        self._set_phase(1)
        run_id = os.getpid()
        stage = _stage_dir_for(self.executor, run_id)
        img_exec = self.executor.to_exec_path(self.img_path)
        p3_exec = f"{stage}/p3.img"
        emmc_exec = f"{stage}/emmc.img"

        try:
            self._log("Extracting installer data partition (P3)...", "info")
            self._progress(0, 100, "dd P3")
            self.executor.run(f"mkdir -p {stage} && rm -f {p3_exec}",
                              timeout=30)
            self.executor.run(
                f"dd if={img_exec} of={p3_exec} "
                f"bs=1M skip={data_part['start_bytes'] // (1024 ** 2)} "
                f"count={data_part['size_bytes'] // (1024 ** 2)} status=none",
                timeout=900,
            )
            self._progress(50, 100, "dump emmc.img")
            self._log("Dumping emmc.img from P3...", "info")
            self.executor.run(
                f"debugfs -R 'dump {EMMC_INNER_PATH} {emmc_exec}' "
                f"{p3_exec} 2>&1",
                timeout=900,
            )
            emmc_size = int(self.executor.run(
                f"stat -c%s {emmc_exec}", timeout=10).strip())
            self._log(
                f"  emmc.img: {emmc_size / (1024 ** 3):.2f} GiB",
                "info")
            self._progress(100, 100, "")
            self._check_cancel()

            self._set_phase(2)
            self._log("Locating inner game partition (emmc.img P2)...",
                      "info")
            # find_game_partition uses local file - we need to read the MBR
            # of the emmc.img.  Since it lives in WSL we have to copy just
            # the first 512 bytes back to host... or stat via executor.
            # Easier: read the partition table on the executor side.
            mbr_hex = self.executor.run(
                f"xxd -s 446 -l 64 -c 64 -p {emmc_exec}", timeout=10).strip()
            inner_part = _parse_mbr_for_linux(mbr_hex)
            self._log(
                f"  emmc P2 at sector {inner_part['start_lba']} "
                f"({inner_part['size_bytes'] / (1024 ** 3):.2f} GiB ext4)",
                "info")

            inner_exec = f"{stage}/inner.img"
            self._log("Extracting inner game partition...", "info")
            self._progress(0, 100, "dd inner")
            self.executor.run(
                f"dd if={emmc_exec} of={inner_exec} "
                f"bs=1M skip={inner_part['start_bytes'] // (1024 ** 2)} "
                f"count={inner_part['size_bytes'] // (1024 ** 2)} status=none",
                timeout=900,
            )
            self._progress(50, 100, "rdump assets")
            self._log(
                f"Dumping {info['asset_subtree']!r} to staging...",
                "info")

            # rdump into a no-space staging path on the executor side.
            # debugfs's mini-parser splits args on whitespace and doesn't
            # honor double-quoted paths reliably, so if the user picks an
            # output folder with a space in it (e.g. ".../afm cgc"),
            # rdumping straight to that path drops every file silently.
            # Stage to /tmp first, then copy with Python (which handles
            # spaces fine).
            rdump_stage_exec = f"{stage}/rdump_out"
            self.executor.run(
                f"rm -rf {rdump_stage_exec} && mkdir -p {rdump_stage_exec}",
                timeout=30)
            rdump_out = self.executor.run(
                f"debugfs -R 'rdump {info['asset_subtree']} "
                f"{rdump_stage_exec}' {inner_exec} 2>&1",
                timeout=1800,
            )
            # debugfs returns 0 even when rdump fails; verify at least
            # one file landed.
            subtree_basename = info["asset_subtree"].rsplit("/", 1)[-1]
            file_count_str = self.executor.run(
                f"find {rdump_stage_exec}/{subtree_basename} -type f 2>/dev/null "
                f"| wc -l", timeout=60).strip()
            try:
                file_count = int(file_count_str)
            except ValueError:
                file_count = 0
            if file_count == 0:
                raise PipelineError("Extract",
                    f"debugfs rdump produced no files. Output:\n{rdump_out}")
            self._log(f"  Staged {file_count} file(s).", "info")

            self._log("Copying assets to output folder...", "info")
            host_stage = self._exec_to_host(rdump_stage_exec)
            host_nested = os.path.join(host_stage, subtree_basename)
            _copy_tree_into(host_nested, self.output_dir,
                            log_cb=self._log,
                            progress_cb=self._progress)

            self._progress(100, 100, "")
            self._check_cancel()

        finally:
            # Best-effort cleanup of executor-side stage.
            try:
                self.executor.run(f"rm -rf {stage}", timeout=30)
            except Exception:
                pass

        # Pulp Fiction post-step: explode each `.bnk` JPS sound bank into
        # its constituent WAVs + manifest.json so users can hear and
        # selectively replace individual sounds.  The .bnk stays in place
        # (Write pipeline will re-pack from the exploded subdir).  Other
        # CGC games (WPC remakes) have direct .wav assets already.
        if game_key == "pulp_fiction":
            self._explode_jps_banks()

        self._set_phase(3)
        self._log("Generating baseline checksums...", "info")
        n = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress)

        self._log("Done.", "success")
        self._done(True,
            f"{info['display']} assets extracted.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n}\n\n"
            f"Modify any audio (.wav / .bnk), ROM, or logo files, then use "
            f"the Write tab to build a new installer.img.")

    def _explode_jps_banks(self):
        """Extract each .bnk under the assets dir into a sibling subdir
        of decoded WAVs + manifest.json.

        Layout after:
            data/
              pfsndui.bnk
              pfsndui/
                pfsndui_sound_000.wav
                ...
                pfsndui.manifest.json
              pfsndfx.bnk
              pfsndfx/
                ...
        """
        from .jps_bnk import extract_bnk
        bnks = []
        for dirpath, _, filenames in os.walk(self.output_dir):
            for fn in filenames:
                if fn.lower().endswith(".bnk"):
                    bnks.append(os.path.join(dirpath, fn))
        if not bnks:
            return
        self._log(f"Decoding {len(bnks)} JPS sound bank(s) to WAV...",
                  "info")
        total_buffers = 0
        for i, bnk_path in enumerate(sorted(bnks)):
            self._check_cancel()
            stem = os.path.splitext(os.path.basename(bnk_path))[0]
            target_dir = os.path.join(os.path.dirname(bnk_path), stem)
            try:
                contents = extract_bnk(bnk_path, target_dir)
            except Exception as e:
                self._log(f"  {os.path.basename(bnk_path)}: "
                          f"decode failed ({e})", "error")
                continue
            n = len(contents.buffers)
            dur_min = sum(b.duration_seconds for b in contents.buffers) / 60
            self._log(
                f"  {os.path.basename(bnk_path)}: "
                f"{n} sound(s), {dur_min:.1f} min audio "
                f"-> {os.path.basename(target_dir)}/",
                "info")
            total_buffers += n
            self._progress(i + 1, len(bnks),
                           f"{stem} ({n} sounds)")
        self._log(f"  Total: {total_buffers} sounds across "
                  f"{len(bnks)} bank(s).", "success")


# ---------------------------------------------------------------------------
# Write pipeline
# ---------------------------------------------------------------------------

class WritePipeline(BasePipeline):
    """Rebuild a CGC installer `.img` with modified assets baked in.

    Phase 0: Detect game, diff modified files against baseline.
    Phase 1: Copy original .img to output path (the byte stream we'll patch).
    Phase 2: Extract P3 + emmc.img + emmc-P2 to staging.
    Phase 3: debugfs -w write each modified file into emmc-P2;
             re-pack emmc-P2 bytes back into emmc.img;
             re-pack emmc.img bytes back into P3;
             re-pack P3 bytes back into the output .img.
    """

    def __init__(self, original_img, assets_dir, output_img,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.original_img = original_img
        self.assets_dir = assets_dir
        self.output_img = output_img
        self.executor = create_executor()

    def _run(self):
        self._set_phase(0)
        self._log("Detecting game...", "info")
        game_key = detect_game(self.original_img)
        if game_key is None:
            raise PipelineError("Detect",
                f"Cannot identify CGC game from: "
                f"{os.path.basename(self.original_img)}.")
        info = GAME_DB[game_key]
        self._log(f"Game: {info['display']}", "success")

        if not os.path.isdir(self.assets_dir):
            raise PipelineError("Detect",
                f"Assets folder not found: {self.assets_dir}")

        baseline = read_checksums(self.assets_dir)
        if not baseline:
            raise PipelineError("Scan",
                f"No baseline checksums found in:\n  {self.assets_dir}\n\n"
                f"Run the Extract tab first to create them.")

        changed, missing = _diff_assets(self.assets_dir, baseline)
        if not changed:
            self._log(
                "  No modified files found -- output will be a byte-for-byte "
                "copy of the original .img (useful as a smoke test).", "info")
        else:
            self._log(f"  {len(changed)} modified file(s):", "info")
            for rel in sorted(changed)[:25]:
                self._log(f"    {rel}", "info")
            if len(changed) > 25:
                self._log(f"    ... and {len(changed) - 25} more", "info")
        if missing:
            self._log(
                f"  {len(missing)} file(s) listed in baseline but missing on "
                f"disk -- ignored.", "info")

        _verify_executor_tools(self.executor)
        self._check_cancel()

        # Copy original -> output.  Patching happens against the copy.
        self._set_phase(1)
        os.makedirs(os.path.dirname(self.output_img) or ".", exist_ok=True)
        if os.path.abspath(self.original_img) != os.path.abspath(
                self.output_img):
            self._log(
                f"Copying {os.path.basename(self.original_img)} -> "
                f"{os.path.basename(self.output_img)}...", "info")
            size = os.path.getsize(self.original_img)
            _copy_with_progress(self.original_img, self.output_img,
                                size, self._progress)
        self._check_cancel()

        if not changed:
            self._set_phase(3)
            self._log("Done (no changes applied).", "success")
            self._done(True,
                f"{info['display']} installer rebuilt (no modifications).\n\n"
                f"Output: {self.output_img}")
            return

        # Stage the nested partitions on the executor side.
        self._set_phase(2)
        data_part = find_data_partition(self.output_img)
        run_id = os.getpid()
        stage = _stage_dir_for(self.executor, run_id)
        out_exec = self.executor.to_exec_path(self.output_img)
        p3_exec = f"{stage}/p3.img"
        emmc_exec = f"{stage}/emmc.img"
        inner_exec = f"{stage}/inner.img"

        try:
            self.executor.run(f"mkdir -p {stage} && rm -f {p3_exec} "
                              f"{emmc_exec} {inner_exec}", timeout=30)

            self._log("Extracting installer P3 from output .img...", "info")
            self.executor.run(
                f"dd if={out_exec} of={p3_exec} "
                f"bs=1M skip={data_part['start_bytes'] // (1024 ** 2)} "
                f"count={data_part['size_bytes'] // (1024 ** 2)} status=none",
                timeout=900,
            )
            self.executor.run(
                f"debugfs -R 'dump {EMMC_INNER_PATH} {emmc_exec}' "
                f"{p3_exec} 2>&1", timeout=900)
            mbr_hex = self.executor.run(
                f"xxd -s 446 -l 64 -c 64 -p {emmc_exec}", timeout=10).strip()
            inner_part = _parse_mbr_for_linux(mbr_hex)
            self.executor.run(
                f"dd if={emmc_exec} of={inner_exec} "
                f"bs=1M skip={inner_part['start_bytes'] // (1024 ** 2)} "
                f"count={inner_part['size_bytes'] // (1024 ** 2)} status=none",
                timeout=900,
            )

            self._set_phase(3)
            self._log("Writing modified files into inner ext4 via debugfs...",
                      "info")
            inner_root_to_assets_root = info["asset_subtree"]
            self._write_modified_files(
                inner_exec, changed, inner_root_to_assets_root)

            self._log("Re-packing emmc.img (inner P2 -> emmc.img)...", "info")
            self.executor.run(
                f"dd if={inner_exec} of={emmc_exec} "
                f"bs=1M seek={inner_part['start_bytes'] // (1024 ** 2)} "
                f"count={inner_part['size_bytes'] // (1024 ** 2)} "
                f"conv=notrunc status=none", timeout=900)

            self._log("Re-packing installer P3 (emmc.img into P3)...", "info")
            self.executor.run(
                f"debugfs -w -R 'rm {EMMC_INNER_PATH}' {p3_exec} 2>&1 "
                f"|| true", timeout=120)
            self.executor.run(
                f"debugfs -w -R 'write {emmc_exec} {EMMC_INNER_PATH}' "
                f"{p3_exec} 2>&1", timeout=900)

            self._log("Re-packing installer .img (P3 into output)...", "info")
            self.executor.run(
                f"dd if={p3_exec} of={out_exec} "
                f"bs=1M seek={data_part['start_bytes'] // (1024 ** 2)} "
                f"count={data_part['size_bytes'] // (1024 ** 2)} "
                f"conv=notrunc status=none", timeout=1800)

        finally:
            try:
                self.executor.run(f"rm -rf {stage}", timeout=30)
            except Exception:
                pass

        self._log("Done.", "success")
        self._done(True,
            f"{info['display']} installer rebuilt with "
            f"{len(changed)} modification(s).\n\n"
            f"Output: {self.output_img}\n\n"
            f"Flash to a USB drive with Rufus / Etcher / dd, plug it into "
            f"the machine's USB port, and follow CGC's on-screen installer "
            f"prompt.")

    def _write_modified_files(self, inner_exec, changed,
                              inner_root_to_assets_root):
        """Replace each modified file inside the inner ext4 via debugfs -w.

        ``changed`` is ``{rel_path_under_assets_dir: abs_host_path}``.
        The corresponding path inside the ext4 is
        ``inner_root_to_assets_root + "/" + rel``.
        """
        total = len(changed)
        for i, (rel, abs_host) in enumerate(sorted(changed.items())):
            self._check_cancel()
            inner_path = f"{inner_root_to_assets_root.rstrip('/')}/{rel}"
            src_exec = self.executor.to_exec_path(abs_host)
            self._progress(i, total, rel)
            self._log(f"  -> {inner_path}", "info")
            # Need rm + write as TWO separate -R invocations -- debugfs's
            # -R takes one command per flag; ';' inside the string is
            # treated as a literal char, not a separator, so 'rm X; write
            # Y Z' would feed rm three args and print a usage error.
            # We still want rm to be best-effort (a brand-new file under
            # an existing dir is allowed), so the failure-tolerant pass
            # is the rm; the write is the must-succeed step.
            self.executor.run(
                f"debugfs -w -R 'rm {_quote_dbg(inner_path)}' "
                f"{inner_exec} 2>&1 | grep -vE '^debugfs |^$' || true",
                timeout=120,
            )
            try:
                out = self.executor.run(
                    f"debugfs -w -R 'write {_quote_dbg(src_exec)} "
                    f"{_quote_dbg(inner_path)}' {inner_exec} 2>&1 "
                    f"| grep -vE '^debugfs |^$' || true",
                    timeout=600,
                )
            except CommandError as e:
                raise PipelineError("Write",
                    f"debugfs write failed for {rel}: {e.output}")
            if out.strip():
                # debugfs write echoes "Allocated N blocks ..." -- noisy
                # but informative; surface as info-level.
                self._log(f"    {out.strip()}", "info")
        self._progress(total, total, "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_mbr_for_linux(hex_str):
    """Parse a 64-byte MBR partition table (hex-encoded) and return the
    first Linux (0x83) entry as a dict matching :func:`read_mbr_partitions`.
    """
    raw = bytes.fromhex(hex_str.replace("\n", "").replace(" ", ""))
    import struct
    for i in range(4):
        entry = raw[i * 16:(i + 1) * 16]
        boot, _, _, _, ptype, _, _, _, start_lba, sectors = struct.unpack(
            "<BBBBBBBBII", entry)
        if ptype == 0x83 and sectors > 0:
            return {
                "index": i + 1,
                "boot": boot == 0x80,
                "type": ptype,
                "start_lba": start_lba,
                "sectors": sectors,
                "start_bytes": start_lba * 512,
                "size_bytes": sectors * 512,
            }
    raise ValueError("No Linux (0x83) partition in MBR table")


def _diff_assets(assets_dir, baseline):
    """Return ``(changed, missing)``.

    ``changed`` maps **the inner-ext4 relative path** (as it appears in
    the baseline ``.checksums.md5``) to the absolute on-disk path that
    should be written there.  ``missing`` is the list of baseline paths
    we still can't account for after rename detection.

    Rename detection (Option A from the design):
      A baseline file at ``foo/bar.wav`` that's missing on disk gets a
      second-chance lookup for siblings matching ``foo/bar - *.wav`` --
      the convention emitted by ``TranscribePipeline`` when its
      rename-after step runs ("Joust Champion!" -> "S0216_C6 - Joust
      Champion!.wav").  A unique match is treated as a stand-in for
      the original:
        * If its bytes still match the baseline md5, it's unchanged --
          skip it (don't write anything).
        * If the md5 differs, the user has edited the renamed file --
          write the new bytes back to the **original** inner-ext4 path
          so the game engine (which looks up samples by the original
          name) actually picks up the change.

    The rename-aware lookup applies whether the rename happened via
    the chained transcribe step or by hand in Explorer, so users who
    prefer to rename outside our tool aren't penalized.
    """
    # CGC pre-step (Pulp Fiction): if the user edited any WAV inside
    # a `<bnk>/` decoded subdir, rebuild the parent `.bnk` so the
    # baseline-md5 diff below picks up the .bnk as changed.  WAVs
    # under those subdirs are derived assets -- they never go to the
    # eMMC, so we also gather their rel-paths into ``jps_subdir_files``
    # for filtering further down.
    jps_subdir_files = _repack_modified_jps_bnks(assets_dir)

    changed = {}
    missing = []
    consumed_on_disk = set()  # rel paths already accounted for by baseline
    for rel, orig_md5 in baseline.items():
        rel_norm = rel.replace("\\", "/")
        # Skip baseline entries that live under a `<bnk>/` decoded
        # subdir -- their .bnk parent now reflects any edits.
        if rel_norm in jps_subdir_files:
            consumed_on_disk.add(rel_norm)
            continue
        abs_path = os.path.join(assets_dir, rel)
        if os.path.isfile(abs_path):
            consumed_on_disk.add(rel_norm)
            if md5_file(abs_path) != orig_md5:
                changed[rel_norm] = abs_path
            continue
        # Original path is gone -- look for a renamed sibling.
        renamed_abs = _find_renamed_sibling(assets_dir, rel)
        if renamed_abs is None:
            missing.append(rel)
            continue
        renamed_rel = os.path.relpath(
            renamed_abs, assets_dir).replace("\\", "/")
        consumed_on_disk.add(renamed_rel)
        if md5_file(renamed_abs) != orig_md5:
            # Edited rename -- write the new bytes to the ORIGINAL
            # inner path so emumm finds them.
            changed[rel_norm] = renamed_abs
        # else: untouched rename, nothing to do for Write.
    # Capture brand-new files too (everything not claimed above).
    # callouts.csv + JPS decoded subdirs (sound_*.wav, manifest.json)
    # are plugin metadata -- the game engine doesn't read them, so don't
    # waste eMMC space shipping them back.
    for dirpath, _, filenames in os.walk(assets_dir):
        for fn in filenames:
            if (fn == CHECKSUMS_FILE
                    or fn == CALLOUTS_CSV
                    or fn.startswith(".")):
                continue
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, assets_dir).replace("\\", "/")
            if rel in jps_subdir_files:
                continue
            if rel not in consumed_on_disk:
                changed[rel] = abs_path
    return changed, missing


def _repack_modified_jps_bnks(assets_dir):
    """Find every `<X>.bnk` with a sibling `<X>/` decoded subdir, and
    if any WAV inside has been edited, repack the `.bnk` in-place.

    Returns the set of relative paths (forward-slash, relative to
    *assets_dir*) of every file under any `<X>/` subdir, so the caller
    can exclude them from the assets-to-write set (they're plugin
    decode artifacts, not eMMC payloads).
    """
    from .jps_bnk import repack_bnk
    decoded_subdir_files = set()
    for dirpath, dirnames, filenames in os.walk(assets_dir):
        for d in dirnames:
            bnk_sibling = os.path.join(dirpath, d + ".bnk")
            if not os.path.isfile(bnk_sibling):
                continue
            subdir_path = os.path.join(dirpath, d)
            # Collect every file under <X>/ so callers can skip them.
            for sub_dirpath, _, sub_files in os.walk(subdir_path):
                for fn in sub_files:
                    abs_p = os.path.join(sub_dirpath, fn)
                    rel = os.path.relpath(
                        abs_p, assets_dir).replace("\\", "/")
                    decoded_subdir_files.add(rel)
            # If any WAV inside differs from what the .bnk currently
            # encodes, repack the .bnk in-place.  ``repack_bnk`` is
            # PCM-diff-aware -- a no-op repack copies the original
            # bytes verbatim, so calling it unconditionally is safe.
            tmp_path = bnk_sibling + ".repack_tmp"
            try:
                summary = repack_bnk(bnk_sibling, subdir_path, tmp_path)
            except Exception:
                # Leave the .bnk untouched if anything goes wrong -- the
                # main Write pipeline will still ship the unmodified
                # version.
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                continue
            if summary.get("modified_count", 0) > 0:
                # User actually edited something -- replace .bnk.
                try:
                    os.replace(tmp_path, bnk_sibling)
                except OSError:
                    pass
            else:
                # Nothing changed -- discard the temp (identical to
                # the original anyway).
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
    return decoded_subdir_files


def _find_renamed_sibling(assets_dir, baseline_rel):
    """Look for a ``<stem> - *<ext>`` sibling of *baseline_rel* on disk.

    Returns the absolute path of a unique match, or None if zero or
    multiple matches.  Multiple matches are treated as ambiguous --
    we'd rather surface ``baseline_rel`` as missing than guess wrong
    and write the wrong bytes into the inner ext4.
    """
    import glob
    parent_rel, base = os.path.split(baseline_rel)
    stem, ext = os.path.splitext(base)
    parent_abs = os.path.join(assets_dir, parent_rel)
    if not os.path.isdir(parent_abs):
        return None
    # The transcribe rename uses " - " (space dash space) as the
    # separator; be strict about that to avoid matching "S0001-LP.wav"
    # when searching for "S0001".
    pattern = os.path.join(
        glob.escape(parent_abs), f"{glob.escape(stem)} - *{glob.escape(ext)}")
    matches = glob.glob(pattern)
    if len(matches) == 1:
        return matches[0]
    return None


def _copy_tree_into(src_root, dst_root, log_cb=None, progress_cb=None):
    """Copy the contents of *src_root* into *dst_root*.

    Distinct from shutil.copytree because:
      * dst_root may already exist (Extract creates it).
      * Skips entries that already exist in dst_root, with a warning.
    """
    if not os.path.isdir(src_root):
        raise FileNotFoundError(f"Source staging dir missing: {src_root}")
    entries = []
    for dirpath, dirs, files in os.walk(src_root):
        for d in dirs:
            entries.append((os.path.join(dirpath, d), True))
        for f in files:
            entries.append((os.path.join(dirpath, f), False))
    total = len(entries)
    for i, (abs_src, is_dir) in enumerate(entries):
        rel = os.path.relpath(abs_src, src_root)
        abs_dst = os.path.join(dst_root, rel)
        if is_dir:
            os.makedirs(abs_dst, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
            if os.path.exists(abs_dst):
                if log_cb:
                    log_cb(f"  Skipping (exists in output): {rel}", "info")
                continue
            shutil.copyfile(abs_src, abs_dst)
        if progress_cb and (i % 50 == 0 or i == total - 1):
            progress_cb(i + 1, total, rel)


def _quote_dbg(p):
    """Quote a path for debugfs -R commands.

    debugfs's mini-parser uses '"..."' for paths with spaces.  Reject
    anything with embedded double-quotes or backticks since we can't
    safely escape them and the inputs are all CGC-typical paths.
    """
    if '"' in p or "`" in p or "$" in p:
        raise ValueError(f"Refusing to pass shell-unsafe path to debugfs: {p}")
    return f'"{p}"'


def _detect_wsl_distro():
    """Return the default WSL distro name, or None if WSL isn't running.

    Cached lookup so we don't shell out repeatedly during file copies.
    """
    if sys.platform != "win32":
        return None
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True, timeout=10, creationflags=flags,
        ).stdout
        # wsl.exe outputs UTF-16-LE
        if b"\x00" in out:
            out = out.decode("utf-16-le", errors="replace")
        else:
            out = out.decode("utf-8", errors="replace")
        for line in out.splitlines():
            name = line.strip().lstrip("﻿")
            if name and not name.startswith("Windows"):
                return name
    except Exception:
        pass
    return None


def _verify_executor_tools(executor):
    ok, msg = executor.check_available()
    if not ok:
        raise PipelineError("Detect",
            f"Executor not available: {msg}\n\n"
            f"On Windows, install WSL2 via: wsl --install -d Ubuntu")
    for tool in ("debugfs", "dd", "xxd"):
        try:
            executor.run(f"command -v {tool} >/dev/null", timeout=10)
        except CommandError:
            raise PipelineError("Detect",
                f"Missing tool: {tool}\n\n"
                f"Install in WSL: apt-get install e2fsprogs xxd coreutils")


def _copy_with_progress(src, dst, total_bytes, progress_cb,
                        chunk=64 * 1024 * 1024):
    copied = 0
    with open(src, "rb") as r, open(dst, "wb") as w:
        while True:
            buf = r.read(chunk)
            if not buf:
                break
            w.write(buf)
            copied += len(buf)
            progress_cb(min(copied, total_bytes), total_bytes,
                        f"{copied / (1024 ** 3):.2f} / "
                        f"{total_bytes / (1024 ** 3):.2f} GiB")
    progress_cb(total_bytes, total_bytes, "")
