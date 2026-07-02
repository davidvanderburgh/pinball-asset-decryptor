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
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile

from ...core.checksums import (CHECKSUMS_FILE, generate_checksums,
                               md5_file, read_checksums)
from ...core.executor import CommandError, create_executor
from ...core.pipeline_base import BasePipeline, PipelineError
from ...core.rawdevice import (FlashCancelled, FlashError,
                              flash_image_to_device, format_size,
                              is_device_path)
from ...core.staged_originals import ORIG_DIR
from ...core.transcribe import CALLOUTS_CSV
from ..williams import wpc_extract
from .formats import (detect_game, find_data_partition, find_game_partition,
                      is_img_file, read_mbr_partitions)
from .games import GAME_DB


# CGC's WPC remakes (MM/AFM/MB) ship the original Williams WPC ROM
# inside their assets.  We decode that ROM into PNG scenes + MP4
# animations + font sheets just like the Williams plugin -- the
# data is identical bytes.  Rendered at pixel_size=15 each 128x32
# DMD becomes a 1920x480 PNG, matching the LCD-backbox width on
# the actual CGC cabinet (the original 128x32 DMD area letterboxed
# in a 1920x1080 panel).  The colorization layer is real-time GPU
# code in emumm and is *not* shipped as data, so the output stays
# monochrome amber -- same look as the original Williams DMD.
CGC_DMD_PIXEL_SIZE = 15

# Subdir under the CGC output folder that holds derived DMD assets.
# Kept separate from the eMMC asset mirror so the Write pipeline
# can ignore it -- it has no counterpart inside the inner ext4.
DMD_SUBDIR = "dmd"

# Subdir under the CGC output folder that holds decoded DCS audio
# (Cactus Canyon).  Like ``dmd/`` it's a derived asset excluded from the
# checksum baseline + Write diff: the WAVs are decoded from the s*.rom
# DCS sound ROMs and don't correspond to any path inside the inner ext4.
# DCS *repack* (edited WAVs -> ROMs via DCSEncoder) is future work, so for
# now the decoded audio is listen/transcribe-only and must never be
# written back as loose files.
DCS_SUBDIR = "dcs_audio"

# Name of the throwaway zip handed to DCSExplorer for Cactus Canyon's DCS
# ROMs.  The basename MUST match ``^cc_\d.*`` -- DCSExplorer's ROM loader
# only applies its Cactus-Canyon special case (s7.rom's internal signature
# is factory-mislabeled "U6") when the zip is named like a PinMAME cc_*
# romset; any other name silently drops s7.rom and loses ~90 samples.
# See docs/CC_REVISITED_RE.md and DCSDecoderZipLoader.cpp.
_DCS_ZIP_NAME = "cc_113.zip"

# DCS sound ROMs inside Cactus Canyon's ccdata/rom/ are named s2.rom..s7.rom.
# (cc_g11.* is the WPC-95 game CPU ROM, not a DCS sound ROM -- excluded.)
_DCS_ROM_RE = re.compile(r"^s\d+\.rom$", re.IGNORECASE)

# Cactus Canyon's other decoded surfaces (top-level output subdirs):
#   new_audio/    -- CGC's added music/speech/SFX decoded from ccdata/usb.so
#   display_art/  -- the 2044 colour images decoded from ccdata/cgc.so
NEW_AUDIO_SUBDIR = "new_audio"
ART_SUBDIR = "display_art"
VIDEO_SUBDIR = "videos"

# All derived/decoded output subdirs.  Excluded from the checksum baseline and
# pruned from the Write diff -- they're decoded from eMMC files (the s*.rom DCS
# ROMs, usb.so, cgc.so, the WPC ROM) and don't correspond to inner-ext4 paths,
# so they must never be written back as loose files.  (Repack of each format
# back into its source blob is separate, future work.)
_DERIVED_SUBDIRS = (DMD_SUBDIR, DCS_SUBDIR, NEW_AUDIO_SUBDIR, ART_SUBDIR,
                    VIDEO_SUBDIR)


# Path of emmc.img inside the installer's P3 ext4 partition.  Same for
# every CGC title we've inspected -- package.dat hardcodes it.
EMMC_INNER_PATH = "/emmc.img"

# Subtree under the staging dir where we keep extracted partition images.
# Lives on the executor side (in WSL: /var/tmp/cgc_stage_<pid>/).


def _stage_dir_for(run_id, game_key=None):
    """Return an executor-side staging path; safe for parallel runs.

    Staged under ``/var/tmp`` (not ``/tmp``): the big titles peak at 20+ GiB of
    intermediate images, and on WSL configs where systemd mounts ``/tmp`` as a
    RAM-backed ``tmpfs`` (sized to ~half of RAM) that staging truncates the
    moment it exceeds RAM -- and no amount of resizing the WSL *disk* can grow a
    ``tmpfs`` (RTS: 15 GiB ext4 root, but ``/tmp`` was a 7.58 GiB tmpfs).
    ``/var/tmp`` is always on the persistent ext4 disk, so staging there uses
    real (and resizable) disk space.

    The game key is folded into the name (``cgc_stage_<game>_<pid>``) so a
    crashed run's leftover staging is attributable per-game in the WSL
    disk-management view (:mod:`core.wsl_disk`).  Omitted -> legacy
    ``cgc_stage_<pid>`` form, still recognised by the scanner.
    """
    if game_key:
        return f"/var/tmp/cgc_stage_{game_key}_{run_id}"
    return f"/var/tmp/cgc_stage_{run_id}"


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
                 log_cb, phase_cb, progress_cb, done_cb,
                 decode_dmd=False):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.img_path = img_path
        self.output_dir = output_dir
        self.executor = create_executor()
        # Optional WPC DMD decode (experimental, extract-only).  Wired
        # to the "Decode DMD scenes" checkbox on the Extract tab.
        # Default OFF -- the render is slow (a few minutes) and the
        # output PNGs/MP4s aren't writable back to the eMMC.
        self.decode_dmd = decode_dmd

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
                f"MonsterBash, PulpFiction, CactusCanyon (case-insensitive).")
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
        stage = _stage_dir_for(run_id, game_key)
        img_exec = self.executor.to_exec_path(self.img_path)
        p3_exec = f"{stage}/p3.img"
        emmc_exec = f"{stage}/emmc.img"

        try:
            self._log("Extracting installer data partition (P3)...", "info")
            self._progress(0, 100, "dd P3")
            self.executor.run(f"mkdir -p {stage} && rm -f {p3_exec}",
                              timeout=30)
            # Byte-exact copy (skip_bytes/count_bytes): a partition whose size
            # isn't a whole number of MiB (Pulp Fiction P3 = 4607.998 MiB) would
            # otherwise lose its sub-MiB tail to whole-MiB rounding, leaving an
            # ext4 image shorter than its superblock declares ("likely corrupt"
            # per e2fsck). Harmless for a read-only extract, but the same
            # rounding in Write corrupts the round-tripped filesystem.
            self.executor.run(
                f"dd if={shlex.quote(img_exec)} of={shlex.quote(p3_exec)} "
                f"bs=1M iflag=skip_bytes,count_bytes "
                f"skip={data_part['start_bytes']} "
                f"count={data_part['size_bytes']} status=none",
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
            # p3.img is fully consumed now (emmc.img has been dumped out
            # of it) -- free it before staging inner.img so the peak
            # footprint is emmc.img+inner.img, not p3.img+emmc.img+inner.img.
            # P3 is the largest layer (3-9 GiB), so dropping it here is what
            # keeps the WSL /tmp filesystem from filling on the bigger titles
            # (Pulp Fiction).
            self.executor.run(f"rm -f {p3_exec}", timeout=30)
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
                f"dd if={shlex.quote(emmc_exec)} of={shlex.quote(inner_exec)} "
                f"bs=1M iflag=skip_bytes,count_bytes "
                f"skip={inner_part['start_bytes']} "
                f"count={inner_part['size_bytes']} status=none",
                timeout=900,
            )
            # emmc.img is consumed too now -- the rest of Extract only reads
            # inner.img (rdump of the asset subtree).  Free it so the rdump
            # staging peak is inner.img+assets, not emmc.img+inner.img+assets.
            self.executor.run(f"rm -f {emmc_exec}", timeout=30)
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

            # Guard against silent truncation: debugfs rdump exits 0 even
            # when it runs out of staging-disk space mid-copy, leaving
            # individual files truncated or 0-byte (this is what produced
            # an "empty" pfspeech.bnk and a missing uncensored-speech
            # folder). Compare every file in the title's data directory
            # against its true on-disk (inode) size and abort if any came
            # up short, so the user gets a clear disk-space error instead
            # of a quietly-incomplete extraction.
            src_data = f"{info['asset_subtree']}/{info['data_dir']}"
            staged_data = (f"{rdump_stage_exec}/{subtree_basename}/"
                           f"{info['data_dir']}")
            short = _verify_staged_sizes(
                self.executor, inner_exec, src_data, staged_data)
            if short:
                detail = "\n".join(
                    f"    {n}: staged "
                    f"{got if got >= 0 else 'MISSING'} of {sz:,} bytes"
                    for n, sz, got in short)
                raise PipelineError("Extract",
                    "Some asset files were truncated or dropped during "
                    "extraction — the staging disk ran out of space. Free "
                    "up disk space on the staging drive and re-run "
                    "Extract.\nAffected files:\n" + detail)

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

        # Decode game data (phase 3) -- per-title post-step:
        #   * Pulp Fiction: explode each `.bnk` JPS sound bank into its
        #     constituent WAVs + manifest.json so users can hear and
        #     selectively replace individual sounds.  The .bnk stays in
        #     place (Write pipeline will re-pack from the exploded
        #     subdir).
        #   * MM/AFM/MB (WPC remakes): if the user opted in via the
        #     "Decode DMD scenes (experimental)" checkbox, decode every
        #     scene + animation + font from the bundled Williams ROM
        #     into the dmd/ subdir.  Default OFF since the render is
        #     slow and the output is extract-only (not written back).
        self._set_phase(3)
        dmd_results = None
        dcs_track_count = 0
        cc_counts = None
        if game_key == "pulp_fiction":
            self._explode_jps_banks()
        elif game_key == "cactus_canyon":
            dcs_track_count = self._extract_dcs_audio(info)
            new_audio = self._extract_usb_audio(info)
            art = self._extract_art(info)
            cc_counts = {"new_audio": new_audio, "art": art, "videos": 0}
            # Optional: render the display-art animation sequences to MP4 with
            # the colour dot-matrix shader (wired to the "Decode DMD scenes"
            # checkbox; off by default — slow, needs ffmpeg).
            if self.decode_dmd and art:
                cc_counts["videos"] = self._render_cc_videos()
        elif self.decode_dmd:
            dmd_results = self._extract_dmd_assets(info)
        else:
            self._log(
                "DMD scene decode skipped (experimental — tick the "
                "\"Decode DMD scenes\" checkbox on the Extract tab to "
                "enable).", "info")

        self._set_phase(4)
        self._log("Generating baseline checksums...", "info")
        # Skip the dmd/ subtree -- its files are derived from the WPC
        # ROM, don't correspond to any path inside the eMMC ext4, and
        # would otherwise be diff'd as "new files" by the Write
        # pipeline and uselessly written into the inner partition.
        n = generate_checksums(
            self.output_dir, log_cb=self._log, progress_cb=self._progress,
            exclude_dirs=set(_DERIVED_SUBDIRS))

        dmd_help = ""
        if dmd_results is not None:
            dmd_help = (
                f"\nDMD scenes:     {dmd_results['scenes']}"
                f"\nAnimations:     {dmd_results['animations']}"
                f"\nFonts:          {dmd_results['fonts']}"
                f"\n\n  dmd/dmd_scenes/scene_*.png — every still bitmap "
                f"(jackpot splashes, mode-start screens, status panels), "
                f"rendered at 1920x480 to match the LCD width."
                f"\n  dmd/animations/anim_*.mp4 — the game cinematics that "
                f"play on the LCD during attract mode and feature shots."
                f"\n  dmd/fonts/font_*.png — DMD glyph atlases.\n  "
                f"Note: the CGC LCD colorization is applied in real time "
                f"by emumm and is not shipped as data, so these renders "
                f"are the underlying amber-DMD output.")

        dcs_help = ""
        if dcs_track_count:
            dcs_help = (
                f"\nDCS streams:    {dcs_track_count}"
                f"\n  {DCS_SUBDIR}/st_*.wav — the original 1998 Williams DCS "
                f"audio (music, voice, SFX) from s2-s7.rom, one WAV per stream. "
                f"Tick Auto-transcribe to map spoken lines to text. Edit a WAV "
                f"and Write re-encodes it back into the ROMs (DCSEncoder).")
        if cc_counts:
            if cc_counts.get("new_audio"):
                dcs_help += (
                    f"\n\nNew audio:      {cc_counts['new_audio']}"
                    f"\n  {NEW_AUDIO_SUBDIR}/*.wav — CGC's ADDED music, speech, "
                    f"and SFX (Stampede/Showdown/High-Noon modes, callouts) "
                    f"from usb.so. Edit a WAV and Write re-packs usb.so.")
            if cc_counts.get("art"):
                dcs_help += (
                    f"\n\nDisplay art:    {cc_counts['art']}"
                    f"\n  {ART_SUBDIR}/*.png — the colour LCD images from "
                    f"cgc.so (RGB565). Edit a PNG (keep its dimensions) and "
                    f"Write re-packs cgc.so.")
            if cc_counts.get("videos"):
                dcs_help += (
                    f"\n\nAnimations:     {cc_counts['videos']}"
                    f"\n  {VIDEO_SUBDIR}/*.mp4 — display-art animation "
                    f"sequences rendered with the DMD shader (extract-only "
                    f"preview).")

        self._log("Done.", "success")
        cc_edit_help = ("" if not cc_counts else
            f"\n\nTo mod Cactus Canyon, edit files under {DCS_SUBDIR}/, "
            f"{NEW_AUDIO_SUBDIR}/, or {ART_SUBDIR}/ (or any logo/ROM), then use "
            f"the Write tab — the edits are re-encoded back into their source "
            f"blobs automatically.")
        self._done(True,
            f"{info['display']} assets extracted.\n\n"
            f"Output: {self.output_dir}\n"
            f"Files:  {n}"
            f"{dmd_help}{dcs_help}"
            f"{cc_edit_help if cc_counts else ''}\n\n"
            f"Modify any audio (.wav / .bnk), ROM, or logo files, then use "
            f"the Write tab to build a new installer.img.")

    def _extract_dmd_assets(self, info):
        """Decode the WPC ROM bundled inside the CGC assets into PNG
        scenes + MP4 animations + font sheets under ``output_dir/dmd/``.

        Searches under ``<data_dir>/`` for a WPC-sized .rom file --
        each title parks the ROM somewhere different:

          MM  → appdata/rom/mm_10.rom        (clean WPC layout)
          AFM → afmdata/rom/afm_113b.rom
          MB  → mbdata/xMB_G11.rom           (no rom/ subdir, x-prefix
                                              CGC-specific filename)

        We walk the whole data_dir, take every ``.rom`` file whose size
        matches a known WPC bank (256 KB, 512 KB, or 1 MB), and pick
        the largest -- mirrors the Williams formats.list_game_roms
        fallback so we cope with any future CGC title that re-arranges
        the directory layout.

        Returns the result dict from the decoder, or ``None`` if no
        WPC-shaped ROM was found.
        """
        WPC_ROM_SIZES = {0x40000, 0x80000, 0x100000}
        data_dir = os.path.join(self.output_dir, info["data_dir"])
        if not os.path.isdir(data_dir):
            self._log(
                f"  No {info['data_dir']}/ directory found — "
                f"skipping DMD scene extraction.", "warning")
            return None
        candidates = []
        for dirpath, _, filenames in os.walk(data_dir):
            for fn in filenames:
                if not fn.lower().endswith(".rom"):
                    continue
                abs_p = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(abs_p)
                except OSError:
                    continue
                if sz in WPC_ROM_SIZES:
                    candidates.append((sz, abs_p))
        if not candidates:
            self._log(
                f"  No WPC-sized .rom file under {info['data_dir']}/ — "
                f"skipping DMD scene extraction.", "warning")
            return None
        candidates.sort(reverse=True)  # largest first
        rom_path = candidates[0][1]
        rom_name = os.path.relpath(rom_path, self.output_dir).replace(
            "\\", "/")
        self._log(f"Decoding WPC ROM: {rom_name}", "info")
        with open(rom_path, "rb") as f:
            rom_bytes = f.read()
        dmd_out = os.path.join(self.output_dir, DMD_SUBDIR)
        try:
            return wpc_extract.extract_dmd_assets(
                rom_bytes,
                dmd_out,
                pixel_size=CGC_DMD_PIXEL_SIZE,
                source_label=rom_name,
                log_cb=self._log,
                progress_cb=self._progress,
                check_cancel=self._check_cancel,
            )
        except wpc_extract.WpcDecodeError as e:
            self._log(f"  DMD decode failed: {e}", "warning")
            return None

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
        failed = []
        for i, bnk_path in enumerate(sorted(bnks)):
            self._check_cancel()
            stem = os.path.splitext(os.path.basename(bnk_path))[0]
            name = os.path.basename(bnk_path)
            target_dir = os.path.join(os.path.dirname(bnk_path), stem)
            # Guard: a 0-byte .bnk never made it through extraction (the
            # debugfs rdump / copy silently truncates files when the
            # staging disk fills). Decoding it would emit a near-empty
            # manifest and no WAVs, which looks like a successful run.
            # Flag it loudly instead.
            size = os.path.getsize(bnk_path)
            if size == 0:
                self._log(
                    f"  {name}: EMPTY (0 bytes) — this bank did not extract. "
                    f"The staging disk likely ran out of space mid-copy. "
                    f"Free disk space and re-run Extract to recover its "
                    f"sounds.", "error")
                failed.append(name)
                self._progress(i + 1, len(bnks), f"{stem} (FAILED)")
                continue
            try:
                contents = extract_bnk(bnk_path, target_dir)
            except Exception as e:
                self._log(f"  {name}: decode failed ({e})", "error")
                failed.append(name)
                self._progress(i + 1, len(bnks), f"{stem} (FAILED)")
                continue
            n = len(contents.buffers)
            # Guard: a non-empty bank that yields zero sound buffers is
            # truncated or in an unrecognized format. extract_bnk still
            # writes an (empty) manifest and no WAVs — surface that as an
            # error rather than letting it pass as "0 sound(s)".
            if n == 0:
                self._log(
                    f"  {name}: decoded 0 sounds from {size:,} bytes — the "
                    f"bank is truncated or in an unrecognized format. No "
                    f"WAVs were written. Re-run Extract (with free disk "
                    f"space) to recover its sounds.", "error")
                failed.append(name)
                self._progress(i + 1, len(bnks), f"{stem} (FAILED)")
                continue
            dur_min = sum(b.duration_seconds for b in contents.buffers) / 60
            self._log(
                f"  {name}: "
                f"{n} sound(s), {dur_min:.1f} min audio "
                f"-> {os.path.basename(target_dir)}/",
                "info")
            total_buffers += n
            self._progress(i + 1, len(bnks),
                           f"{stem} ({n} sounds)")
        self._log(f"  Total: {total_buffers} sounds across "
                  f"{len(bnks)} bank(s).", "success")
        if failed:
            self._log(
                f"  WARNING: {len(failed)} sound bank(s) did not decode: "
                f"{', '.join(failed)}. Their sounds are MISSING from this "
                f"extraction. This is almost always caused by the staging "
                f"disk filling up during a Pulp Fiction extract (it is the "
                f"largest title) — free up disk space and run Extract again.",
                "error")

    def _extract_dcs_audio(self, info):
        """Decode Cactus Canyon's original Williams DCS audio (the 1998 Bally
        sound ROMs ``<data_dir>/rom/s2..s7.rom``) into addressable per-stream
        WAVs under ``output_dir/dcs_audio/`` via :mod:`.cc_dcs` (DCSExplorer).

        Streams (not "tracks") are the editable unit: DCSEncoder's repack
        replaces audio by stream address, and each stream filename carries that
        address.  Output is excluded from the Write baseline; edits are
        re-encoded back into the ROMs by ``_repack_modified_cc_assets`` at
        Write time.  Returns the stream count (0 if ROMs/decoder absent)."""
        from . import cc_dcs
        from ..williams import dcs_decode

        rom_dir = os.path.join(self.output_dir, info["data_dir"], "rom")
        if not os.path.isdir(rom_dir):
            self._log(f"  No {info['data_dir']}/rom/ directory — skipping DCS "
                      f"audio decode.", "warning")
            return 0
        if dcs_decode.find_dcs_explorer() is None:
            self._log("  DCSExplorer not available (bundled Windows binary; on "
                      "macOS/Linux put it on PATH) — skipping DCS audio "
                      "decode.", "warning")
            return 0
        self._check_cancel()
        self._log("Decoding original DCS audio (s2-s7.rom) to streams...",
                  "info")
        out = os.path.join(self.output_dir, DCS_SUBDIR)
        try:
            n = cc_dcs.extract_streams(rom_dir, out, log_cb=self._log)
        except Exception as e:
            self._log(f"  DCS audio extraction error: {e}", "warning")
            return 0
        if n == 0:
            self._log("  No DCS streams produced — skipped.", "info")
            return 0
        self._log(f"  {n} DCS stream(s) -> {DCS_SUBDIR}/", "success")
        return n

    def _extract_usb_audio(self, info):
        """Decode Cactus Canyon's NEW audio (CGC's added music/speech/SFX)
        from the encrypted ``ccdata/usb.so`` bank into WAVs under
        ``output_dir/new_audio/``.  Extract-only (excluded from the Write
        baseline).  Returns the number of WAVs written (0 if absent/failed)."""
        from . import cc_usb_audio
        usb_path = os.path.join(self.output_dir, info["data_dir"], "usb.so")
        if not os.path.isfile(usb_path):
            self._log(f"  No {info['data_dir']}/usb.so — skipping new-audio "
                      f"decode.", "info")
            return 0
        self._check_cancel()
        self._log("Decoding new audio (usb.so)...", "info")
        out = os.path.join(self.output_dir, NEW_AUDIO_SUBDIR)
        try:
            n = cc_usb_audio.extract_usb_audio(
                usb_path, out, log_cb=self._log, progress_cb=self._progress)
        except ImportError:
            self._log("  numpy not available — skipping new-audio decode "
                      "(install numpy to enable usb.so audio export).",
                      "warning")
            return 0
        except cc_usb_audio.UsbAudioError as e:
            self._log(f"  usb.so not the expected audio bank ({e}) — skipped.",
                      "warning")
            return 0
        except Exception as e:
            self._log(f"  new-audio decode error: {e}", "warning")
            return 0
        self._log(f"  {n} new-audio track(s) -> {NEW_AUDIO_SUBDIR}/",
                  "success")
        return n

    def _extract_art(self, info):
        """Decode Cactus Canyon's colour display art from the obfuscated
        ``ccdata/cgc.so`` archive (indexed by the ``cc_art`` table inside the
        extracted ``pin`` binary) into PNGs under ``output_dir/display_art/``.
        Extract-only.  Returns the number of PNGs written (0 if absent/failed)."""
        from . import cc_art
        cgc_path = os.path.join(self.output_dir, info["data_dir"], "cgc.so")
        pin_path = os.path.join(self.output_dir, "pin")
        if not os.path.isfile(cgc_path):
            self._log(f"  No {info['data_dir']}/cgc.so — skipping art decode.",
                      "info")
            return 0
        if not os.path.isfile(pin_path):
            self._log("  No pin binary in extract — can't read the art index; "
                      "skipping art decode.", "warning")
            return 0
        self._check_cancel()
        self._log("Decoding colour display art (cgc.so)...", "info")
        out = os.path.join(self.output_dir, ART_SUBDIR)
        try:
            n = cc_art.extract_art(
                cgc_path, pin_path, out,
                log_cb=self._log, progress_cb=self._progress)
        except ImportError:
            self._log("  numpy/Pillow not available — skipping art decode.",
                      "warning")
            return 0
        except cc_art.ArtError as e:
            self._log(f"  cgc.so not the expected art archive ({e}) — skipped.",
                      "warning")
            return 0
        except Exception as e:
            self._log(f"  art decode error: {e}", "warning")
            return 0
        self._log(f"  {n} image(s) -> {ART_SUBDIR}/", "success")
        return n

    def _render_cc_videos(self):
        """Group the decoded ``display_art/`` frames into animation sequences
        and render each to an MP4 under ``output_dir/videos/`` with the colour
        dot-matrix shader (same look as the other CGC/DP videos).  Optional;
        needs ffmpeg.  Returns the number of MP4s written."""
        from . import cc_video
        art_dir = os.path.join(self.output_dir, ART_SUBDIR)
        if not os.path.isdir(art_dir):
            return 0
        self._check_cancel()
        self._log("Rendering display-art animations to MP4 (DMD shader)...",
                  "info")
        out = os.path.join(self.output_dir, VIDEO_SUBDIR)
        try:
            n = cc_video.render_animations(
                art_dir, out, log_cb=self._log, progress_cb=self._progress)
        except Exception as e:
            self._log(f"  video render error: {e}", "warning")
            return 0
        if n == 0:
            self._log("  No animation videos produced (ffmpeg missing or no "
                      "multi-frame sequences).", "info")
        else:
            self._log(f"  {n} animation video(s) -> {VIDEO_SUBDIR}/", "success")
        return n


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
        stage = _stage_dir_for(run_id, game_key)
        out_exec = self.executor.to_exec_path(self.output_img)
        p3_exec = f"{stage}/p3.img"
        emmc_exec = f"{stage}/emmc.img"
        inner_exec = f"{stage}/inner.img"

        try:
            self.executor.run(f"mkdir -p {stage} && rm -f {p3_exec} "
                              f"{emmc_exec} {inner_exec}", timeout=30)

            self._log("Extracting installer P3 from output .img...", "info")
            # Byte-exact (skip_bytes/count_bytes) — see the matching note in
            # Extract. Whole-MiB rounding here dropped P3's sub-MiB tail
            # (Pulp Fiction P3 = 4607.998 MiB), so the round-tripped ext4 came
            # out shorter than its superblock and the machine froze mounting
            # /data at power-up.
            self.executor.run(
                f"dd if={shlex.quote(out_exec)} of={shlex.quote(p3_exec)} "
                f"bs=1M iflag=skip_bytes,count_bytes "
                f"skip={data_part['start_bytes']} "
                f"count={data_part['size_bytes']} status=none",
                timeout=900,
            )
            self.executor.run(
                f"debugfs -R 'dump {EMMC_INNER_PATH} {emmc_exec}' "
                f"{p3_exec} 2>&1", timeout=900)
            # Sanity-floor the dumped payload BEFORE we build on it.  If the
            # source .img's emmc.img is empty/truncated (RTS's Pulp Fiction
            # card shipped a 0-byte emmc.img carried straight from a bad
            # source), the dump is empty too -- and the later staged-vs-
            # repacked size guard can't catch it (0 == 0 passes).  A real
            # payload is 2-4 GB; anything under 256 MB is broken.  Abort loudly
            # here rather than flash a card the machine SHELL-ERRORs on.
            self._verify_dumped_emmc(emmc_exec)
            mbr_hex = self.executor.run(
                f"xxd -s 446 -l 64 -c 64 -p {emmc_exec}", timeout=10).strip()
            inner_part = _parse_mbr_for_linux(mbr_hex)
            self.executor.run(
                f"dd if={shlex.quote(emmc_exec)} of={shlex.quote(inner_exec)} "
                f"bs=1M iflag=skip_bytes,count_bytes "
                f"skip={inner_part['start_bytes']} "
                f"count={inner_part['size_bytes']} status=none",
                timeout=900,
            )

            self._set_phase(3)
            self._log("Writing modified files into inner ext4 via debugfs...",
                      "info")
            inner_root_to_assets_root = info["asset_subtree"]
            self._write_modified_files(
                inner_exec, changed, inner_root_to_assets_root)

            # The mods were just written with debugfs -w, which exits 0 even
            # when it damages the filesystem it is editing.  This inner ext4
            # is the one the game actually boots from after install, and until
            # now it shipped unchecked (only the outer P3 was verified).
            self._verify_partition_fs(
                inner_exec, "inner game partition (emmc P2)")

            self._log("Re-packing emmc.img (inner P2 -> emmc.img)...", "info")
            # Byte-exact seek/count so the inner ext4's sub-MiB tail isn't
            # dropped (same rounding trap as the extract dd's above).
            self.executor.run(
                f"dd if={shlex.quote(inner_exec)} of={shlex.quote(emmc_exec)} "
                f"bs=1M oflag=seek_bytes iflag=count_bytes "
                f"seek={inner_part['start_bytes']} "
                f"count={inner_part['size_bytes']} "
                f"conv=notrunc status=none", timeout=900)

            self._log("Re-packing installer P3 (emmc.img into P3)...", "info")
            self.executor.run(
                f"debugfs -w -R 'rm {EMMC_INNER_PATH}' {p3_exec} 2>&1 "
                f"|| true", timeout=120)
            self.executor.run(
                f"debugfs -w -R 'write {emmc_exec} {EMMC_INNER_PATH}' "
                f"{p3_exec} 2>&1", timeout=900)

            # debugfs `write` exits 0 even when it never created the file or
            # ran P3 out of space partway.  e2fsck below can't catch that
            # either: a missing or truncated-but-consistent emmc.img is a
            # CLEAN filesystem.  On the machine it is exactly what the
            # installer's `dcfldd if=/data/emmc.img` copy trips over as a
            # "SHELL ERROR", so check presence + exact byte size here.
            self._verify_repacked_emmc(p3_exec, emmc_exec)

            # Guard the unguarded debugfs re-pack: a P3 ext4 that ends up
            # short or inconsistent makes the machine hang mounting /data at
            # power-up (a dead freeze before pinstall even draws — RTS's Pulp
            # Fiction card). debugfs exits 0 on such damage, so verify the
            # re-packed P3 read-only and abort loudly rather than shipping an
            # image the on-machine kernel can't mount.
            self._verify_partition_fs(p3_exec, "installer data partition (P3)")

            self._log("Re-packing installer .img (P3 into output)...", "info")
            self.executor.run(
                f"dd if={shlex.quote(p3_exec)} of={shlex.quote(out_exec)} "
                f"bs=1M oflag=seek_bytes iflag=count_bytes "
                f"seek={data_part['start_bytes']} "
                f"count={data_part['size_bytes']} "
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
            f"Flash the whole image to your machine's installer medium -- a "
            f"USB drive or a microSD card, depending on the unit (some CGC "
            f"machines install from a microSD master card, not USB). Easiest: "
            f"use the \"Flash image to SD card or USB drive...\" button on this "
            f"Write tab (run the app as Administrator). You can also use "
            f"Etcher / Rufus (DD mode) / Win32DiskImager. Insert it with the "
            f"machine powered off, power on, and follow CGC's on-screen "
            f"installer prompt. Keep a backup of the untouched card/drive "
            f"first.")

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
            #
            # shlex.quote the WHOLE debugfs command (and the image path) for
            # the shell.  ``_quote_dbg`` double-quotes the inner path so
            # debugfs groups spaces, but the command itself still has to reach
            # the shell as one token -- and a filename with an apostrophe
            # (e.g. "S0315_C6 We'll blow ... Martians.wav", common in
            # transcribe-named callouts) would otherwise close a naive outer
            # 'rm "..."' early ("unexpected EOF while looking for matching '").
            img_q = shlex.quote(inner_exec)
            rm_cmd = shlex.quote(f"rm {_quote_dbg(inner_path)}")
            self.executor.run(
                f"debugfs -w -R {rm_cmd} {img_q} "
                f"2>&1 | grep -vE '^debugfs |^$' || true",
                timeout=120,
            )
            try:
                write_cmd = shlex.quote(
                    f"write {_quote_dbg(src_exec)} {_quote_dbg(inner_path)}")
                out = self.executor.run(
                    f"debugfs -w -R {write_cmd} {img_q} 2>&1 "
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

    # A real CGC install payload (emmc.img) is 2-4 GB; anything under this
    # is an empty/truncated payload the machine can't install.
    _MIN_PLAUSIBLE_EMMC = 256 * 1024 * 1024

    def _verify_dumped_emmc(self, emmc_exec):
        """Reject an empty/truncated emmc.img dumped out of the source P3.

        A bad source .img (RTS's Pulp Fiction card carried a 0-byte emmc.img)
        makes the dump empty; building on it ships a payload the machine's
        installer can't copy ("SHELL ERROR"), and the staged-vs-repacked guard
        downstream compares 0 == 0 and misses it.  Catch it at the source.
        """
        size = int(self.executor.run(
            f"stat -c%s {shlex.quote(emmc_exec)}", timeout=10).strip() or "0")
        if size < self._MIN_PLAUSIBLE_EMMC:
            raise PipelineError("Stage partitions",
                f"The source installer image holds an empty or truncated "
                f"emmc.img payload ({size:,} bytes; a real payload is "
                f"2-4 GB). Building from it would produce a card the machine "
                f"rejects with a SHELL ERROR (nothing to copy). The build was "
                f"aborted; the original image is unchanged.\n\nThis almost "
                f"always means the ORIGINAL .img you selected is itself bad — "
                f"re-check or re-image your source installer, then rebuild.")

    def _verify_repacked_emmc(self, p3_exec, emmc_exec):
        """Check that ``/emmc.img`` inside the re-packed P3 exists and matches
        the staged emmc.img byte-for-byte in size.

        The on-machine installer (pinstall) has no checksum of its payload --
        it just forks ``dcfldd if=/data/emmc.img of=/dev/mmcblk1`` and shows
        "SHELL ERROR" if that exits nonzero.  A missing emmc.img fails the
        install instantly; a short one silently bricks the eMMC contents.
        Neither is visible to ``e2fsck`` (both leave a consistent filesystem),
        so compare the inode size debugfs reports against the staged source.
        """
        self._log("Verifying re-packed emmc.img inside P3...", "info")
        want = int(self.executor.run(
            f"stat -c%s {shlex.quote(emmc_exec)}", timeout=10).strip())
        out = self.executor.run(
            f"debugfs -R 'stat {EMMC_INNER_PATH}' {shlex.quote(p3_exec)} "
            f"2>&1", timeout=60)
        m = re.search(r"\bSize:\s*(\d+)", out)
        got = int(m.group(1)) if m else None
        if got != want:
            raise PipelineError("Write",
                f"The re-packed installer data partition holds a bad "
                f"emmc.img (expected {want:,} bytes, "
                f"got {f'{got:,}' if got is not None else 'NO FILE'}) -- "
                f"on the machine this fails the install with a SHELL ERROR "
                f"or a corrupt eMMC. The build was aborted; the original "
                f"image is unchanged.\n\ndebugfs stat output:\n{out.strip()}")

    def _verify_partition_fs(self, image_exec, label):
        """Read-only e2fsck of a re-packed ext4 partition image; abort on any
        inconsistency.

        The nested debugfs re-pack exits 0 even when it leaves the filesystem
        short or damaged, so without this check a corrupt build ships silently
        and only surfaces as a frozen machine.  ``e2fsck -fn`` makes no changes
        and returns 0 only for a clean filesystem; any other code (short image,
        bad superblock, unresolved inconsistency) means the image must not be
        flashed.
        """
        self._log(f"Verifying {label} filesystem...", "info")
        out = self.executor.run(
            f"e2fsck -fn {shlex.quote(image_exec)} 2>&1; echo __RC__$?",
            timeout=900)
        rc = out.rsplit("__RC__", 1)[-1].strip()
        if rc != "0":
            raise PipelineError("Write",
                f"The re-packed {label} failed its filesystem check — the "
                f"rebuilt installer would freeze the machine at power-up "
                f"(a corrupt ext4 the on-machine kernel can't mount). The "
                f"build was aborted; the original image is unchanged.\n\n"
                f"e2fsck output:\n{out.rsplit('__RC__', 1)[0].strip()}")


# ---------------------------------------------------------------------------
# Flash-image pipeline
# ---------------------------------------------------------------------------

class FlashImagePipeline(BasePipeline):
    """Flash a built CGC installer ``.img`` straight onto a card / USB drive.

    A dd-style raw block copy (via :func:`core.rawdevice.flash_image_to_device`)
    so users don't need Etcher / Rufus -- the same whole-image write, with a
    built-in "does it fit?" guard, run through the normal status area.  This is
    NOT the nested-ext4 Write above: it writes the *whole* image verbatim, so it
    works for any image the user built or backed up.  The GUI gates it on
    Administrator/root and confirms the destructive write before reaching here."""

    def __init__(self, image_path, device_path,
                 log_cb, phase_cb, progress_cb, done_cb):
        super().__init__(log_cb, phase_cb, progress_cb, done_cb)
        self.image_path = image_path
        self.device_path = device_path

    def _run(self):
        self._set_phase(0)  # Check card
        if not is_device_path(self.device_path):
            raise PipelineError(
                "Check card",
                "Flashing needs a physical drive (e.g. \\\\.\\PHYSICALDRIVE2), "
                "not a file path (got %r). Pick the card from the dropdown."
                % self.device_path)
        if not self.image_path or not os.path.isfile(self.image_path):
            raise PipelineError(
                "Check card", "Image file not found: %r" % self.image_path)
        self._check_cancel()

        self._set_phase(1)  # Write image
        try:
            written = flash_image_to_device(
                self.image_path, self.device_path,
                log=self._log, progress=self._progress,
                cancel=lambda: self._cancelled)
        except FlashCancelled:
            self._log("Flash cancelled -- the card is incomplete and must be "
                      "re-flashed before use.", "error")
            self._check_cancel()   # raises PipelineError("Cancelled", ...)
            return
        except FlashError as e:
            raise PipelineError("Write image", str(e))
        self._check_cancel()

        self._set_phase(2)  # Flush
        self._done(True, "Flashed %s onto the card (%s)."
                   % (format_size(written), self.device_path))


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
    # CGC Cactus Canyon pre-step: re-encode any edited decoded assets
    # (dcs_audio/ streams, new_audio/ WAVs, display_art/ PNGs) back into their
    # source eMMC blobs (s*.rom / usb.so / cgc.so) in place, so the baseline
    # md5 diff below picks the blobs up as changed.  No-op when those dirs
    # aren't present (other CGC titles / non-CC extracts).
    _repack_modified_cc_assets(assets_dir)

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
    # waste eMMC space shipping them back.  The dmd/ subtree is also
    # plugin-derived (decoded from the WPC ROM by the Extract step) and
    # doesn't correspond to anything inside the inner ext4 -- skip it
    # at the top of os.walk so we don't even hash the thousand+ PNGs.
    #
    # ``.orig/`` is the Replace-tabs' pristine-original snapshot store
    # (core.staged_originals) -- internal revert state, never game data.  It's
    # a dotfolder, but we only skip dot-*files* below (``fn.startswith(".")``),
    # so the dot-*directory* has to be pruned here or its snapshots get written
    # into the eMMC (and a snapshot of an apostrophe-named callout crashes the
    # debugfs write).
    _skip_top = set(_DERIVED_SUBDIRS) | {ORIG_DIR}
    for dirpath, dirnames, filenames in os.walk(assets_dir):
        if os.path.relpath(dirpath, assets_dir).replace("\\", "/") == ".":
            dirnames[:] = [d for d in dirnames if d not in _skip_top]
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


def _repack_modified_cc_assets(assets_dir):
    """Re-encode edited Cactus Canyon decoded assets back into their source
    eMMC blobs, in place, so the Write diff picks the blobs up as changed.

    Mirrors ``_repack_modified_jps_bnks``: each repacker is no-op-safe (an
    unedited set reproduces the original bytes / writes nothing), and any
    failure leaves the original blob untouched so Write still ships a valid
    (unmodified) image.  Handles three independent surfaces:

      * ``dcs_audio/`` streams  -> ``ccdata/rom/s2..s7.rom``  (cc_dcs / DCSEncoder)
      * ``new_audio/`` WAVs      -> ``ccdata/usb.so``          (cc_usb_audio)
      * ``display_art/`` PNGs    -> ``ccdata/cgc.so``          (cc_art)
    """
    data_rom = os.path.join(assets_dir, "ccdata", "rom")
    dcs_dir = os.path.join(assets_dir, DCS_SUBDIR)
    usb_so = os.path.join(assets_dir, "ccdata", "usb.so")
    new_audio = os.path.join(assets_dir, NEW_AUDIO_SUBDIR)
    cgc_so = os.path.join(assets_dir, "ccdata", "cgc.so")
    art_dir = os.path.join(assets_dir, ART_SUBDIR)
    pin_bin = os.path.join(assets_dir, "pin")

    # DCS streams -> s*.rom (DCSEncoder; writes the s*.rom set in place).
    if os.path.isdir(data_rom) and os.path.isdir(dcs_dir):
        try:
            from . import cc_dcs
            cc_dcs.repack(data_rom, dcs_dir, data_rom)
        except Exception:
            pass

    # new_audio WAVs -> usb.so (re-encrypt).
    if os.path.isfile(usb_so) and os.path.isdir(new_audio):
        try:
            from . import cc_usb_audio
            tmp = usb_so + ".repack_tmp"
            summary = cc_usb_audio.repack_usb(usb_so, new_audio, tmp)
            if summary.get("modified_count", 0) > 0 and os.path.isfile(tmp):
                os.replace(tmp, usb_so)
            elif os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            if os.path.exists(usb_so + ".repack_tmp"):
                try:
                    os.remove(usb_so + ".repack_tmp")
                except OSError:
                    pass

    # display_art PNGs -> cgc.so (re-encode RGB565 + re-obfuscate + CRC).
    if os.path.isfile(cgc_so) and os.path.isdir(art_dir) \
            and os.path.isfile(pin_bin):
        try:
            from . import cc_art
            tmp = cgc_so + ".repack_tmp"
            summary = cc_art.repack_art(cgc_so, pin_bin, art_dir, tmp)
            if summary.get("modified_count", 0) > 0 and os.path.isfile(tmp):
                os.replace(tmp, cgc_so)
            elif os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            if os.path.exists(cgc_so + ".repack_tmp"):
                try:
                    os.remove(cgc_so + ".repack_tmp")
                except OSError:
                    pass


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


def _verify_staged_sizes(executor, image_exec, src_dir, staged_dir):
    """Compare debugfs source inode sizes against the staged copies for
    every regular file in *src_dir* (one ext4 directory).

    Returns a list of ``(name, source_size, staged_size)`` for any file
    that is missing (``staged_size == -1``) or smaller than its source.
    That short-file signature is exactly what a ``debugfs rdump`` that ran
    out of staging-disk space leaves behind — debugfs still exits 0, but
    individual files come up truncated or 0-byte.

    Best-effort: if the debugfs listing can't be parsed, returns ``[]``
    rather than blocking an otherwise-good extraction. The loud
    per-bank guard in ``_explode_jps_banks`` is the backstop.
    """
    ls_out = executor.run(
        f"debugfs -R 'ls -l {src_dir}' {shlex.quote(image_exec)} 2>/dev/null",
        timeout=120)
    src = {}
    for line in ls_out.splitlines():
        toks = line.split()
        # debugfs `ls -l`: inode mode (type) uid gid size date time name
        # Regular files have a mode field beginning "100" (0100000);
        # directories start "40", symlinks "120" — skip those.
        if len(toks) < 9 or not toks[1].startswith("100"):
            continue
        try:
            src[toks[-1]] = int(toks[5])
        except (ValueError, IndexError):
            continue
    if not src:
        return []
    stat_out = executor.run(
        f"find {staged_dir} -maxdepth 1 -type f -printf '%s %f\\n' "
        f"2>/dev/null", timeout=60)
    staged = {}
    for line in stat_out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            try:
                staged[parts[1]] = int(parts[0])
            except ValueError:
                pass
    problems = []
    for name, size in sorted(src.items()):
        got = staged.get(name)
        if got is None:
            problems.append((name, size, -1))
        elif got < size:
            problems.append((name, size, got))
    return problems


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
