# Dutch Pinball (`dp`) — Architecture

> Dutch Pinball ships two games whose on-disk formats have almost nothing in common, yet both live under one plugin: **The Big Lebowski (TBL)** distributes plain, unencrypted `.zip` "delta" software updates (cumulative, version-folder layout, with custom `.cdmd` colour-DMD video), while **Alice's Adventures in Wonderland (AAIW)** ships as a Clonezilla auto-installer `.img` carrying a partclone-v2 + zstd ext4 SSD image. The plugin detects which game an input is and routes to a TBL or AAIW pipeline; it also exposes a Direct-SSD read/write path that mounts a physically-connected game SSD for either game. Nothing here is encrypted — the work is format reconstruction (partclone/zstd, dirty-rectangle video) plus version-aware delta merging so a rebuilt TBL update reinstalls cleanly.

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/dp/`
- **Key:** `dp`  ([manufacturer.py:18](../../pinball_decryptor/plugins/dp/manufacturer.py#L18))
- **Display:** `Dutch Pinball`  ([manufacturer.py:19](../../pinball_decryptor/plugins/dp/manufacturer.py#L19))

### Supported games

The game DB ([games.py:15](../../pinball_decryptor/plugins/dp/games.py#L15)) defines exactly two games. Both `Game` objects are built without `supported=False` ([manufacturer.py:11](../../pinball_decryptor/plugins/dp/manufacturer.py#L11)), so neither is greyed out. Detection is content-based (zip layout / MBR), not just filename — see [Detection](#detection).

| key | display | format | supported? | write? | notes |
|-----|---------|--------|------------|--------|-------|
| `tbl` | The Big Lebowski | plain `.zip` (`pyprocgame` build; `.wav` + `.cdmd`) | yes | **yes** — rebuild update `.zip` | `format: "zip"`, `asset_root: "assets"` ([games.py:16](../../pinball_decryptor/plugins/dp/games.py#L16)). Full delta/`.cdmd`/chain-delta support |
| `aaiw` | Alice's Adventures in Wonderland | Clonezilla `.img` (partclone-v2 + zstd, ext4) | yes (extract) | **no** — edit-in-place only | `format: "clonezilla_img"`, asset subtree `/opt/assets/alice` ([games.py:24](../../pinball_decryptor/plugins/dp/games.py#L24)). Re-imaging the SSD to install mods is not supported ([pipeline.py:237](../../pinball_decryptor/plugins/dp/pipeline.py#L237)) |

Both games are *also* reachable through the Direct-SSD path (which auto-detects which game the mounted partition holds — [ssd.py:99](../../pinball_decryptor/plugins/dp/ssd.py#L99)).

### Input extensions / InputSpec

- **InputSpec:** label `"Dutch Pinball files"`, extensions `(".zip", ".img")`  ([manufacturer.py:29](../../pinball_decryptor/plugins/dp/manufacturer.py#L29))
- `.zip` → TBL, `.img` → AAIW. Direct-SSD takes no file (a physical-drive path instead).

### Capabilities

Declared at [manufacturer.py:21](../../pinball_decryptor/plugins/dp/manufacturer.py#L21):

| flag | value | meaning |
|------|-------|---------|
| `extract` | True | TBL unzip + cdmd decode; AAIW image reconstruction |
| `write` | True | Rebuild a TBL update `.zip` (TBL-only; AAIW write raises) |
| `modpack` | True | Standard changed-vs-baseline mod-pack export/import (core feature, baseline is `.checksums.md5`) |
| `apply_delta` | True | Overlay a single TBL delta `.zip` onto an extracted assets folder ([pipeline.py:571](../../pinball_decryptor/plugins/dp/pipeline.py#L571)) |
| `decode_dmd` | True | Optional video-processing toggle on Extract. For TBL: a dot-matrix shader on the decoded `.cdmd` videos. For AAIW: ProRes `.mov` → `.mp4` convert (the *same* checkbox, relabelled per game) |
| `chain_deltas` | True | Optional "updates to merge on top" multi-file picker on Extract. Supply a complete base `.zip` + delta(s); Extract merges them in version order (TBL-only) |
| `direct_ssd` | True | Read from / write to a physically-connected game SSD (radio toggle swaps the file picker for a drive picker + "Force partition #") |
| `replace_audio` | True | Replace-Audio tab. DP audio is loose `.wav`/`.ogg`; `audio_slot_dirs()` is not overridden, so the whole extract tree is scanned (the registry default — [registry.py:283](../../pinball_decryptor/core/registry.py#L283)) |

Unset / default-False capabilities: `iso`, `capture`, `transcribe`, `asset_filters`, `write_version_date`.

Note the registry's per-game capability *overrides* — `decode_dmd` and `chain_deltas` are gated at runtime per input (see [Detection](#detection)): `decode_dmd_applies` returns True for both games ([manufacturer.py:70](../../pinball_decryptor/plugins/dp/manufacturer.py#L70)), but `chain_deltas_applies` is TBL-only ([manufacturer.py:81](../../pinball_decryptor/plugins/dp/manufacturer.py#L81)), and `decode_dmd_label_for` swaps the checkbox text per game ([manufacturer.py:75](../../pinball_decryptor/plugins/dp/manufacturer.py#L75)).

### Prerequisites

Only one prereq is *declared* for the badge probe ([manufacturer.py:55](../../pinball_decryptor/plugins/dp/manufacturer.py#L55)):

| tool | probe | why |
|------|-------|-----|
| `WSL2` | `echo ok` (under the `wsl` executor) | AAIW `.img` extraction *fallback*, and the Direct-SSD mount path. 7-Zip is preferred for AAIW and needs no WSL |

Other tools are discovered ad-hoc (not surfaced as badges):

- **7-Zip** — preferred AAIW reader; reads MBR partitions *and* ext4 directly so the whole flow is local NTFS I/O, ~15× faster than WSL (the WSL↔Windows boundary caps ~30 MB/s, dominating the ~11 GB copy). Discovered via `find_7z()` (`7z`/`7zz`/`7za` on PATH, then the standard Program Files locations — [aaiw.py:49](../../pinball_decryptor/plugins/dp/aaiw.py#L49)).
- **partclone / zstd** — *not* external binaries: handled in pure Python by `core/partclone.py` (zstd via the `zstandard` Python package). The comment at [manufacturer.py:53](../../pinball_decryptor/plugins/dp/manufacturer.py#L53) is explicit about this.
- **ffmpeg** — needed to build `.cdmd` → MP4 (TBL) and ProRes → MP4 (AAIW). Discovered with a resilient PATH + winget/scoop/choco search ([cdmd.py:63](../../pinball_decryptor/plugins/dp/cdmd.py#L63)). Optional: without it, multi-frame `.cdmd` clips fall back to a last-frame PNG, and `.mov` files are left as-is.
- **Pillow** — required for `.cdmd` decode (already a project dependency).

### Phase labels

- **Extract (TBL & AAIW share these 4):** `Detect`, `Extract`, `Decode`, `Finalize`  ([manufacturer.py:51](../../pinball_decryptor/plugins/dp/manufacturer.py#L51))
- **Write (TBL):** uses the default 4-step `WRITE_PHASES` (not overridden). The TBL write pipeline calls `_set_phase(0..3)`: Detect → Scan → Repack → Finalize ([pipeline.py:352](../../pinball_decryptor/plugins/dp/pipeline.py#L352)–[pipeline.py:413](../../pinball_decryptor/plugins/dp/pipeline.py#L413)).
- **Direct-SSD extract (2):** `Copy from SSD`, `Checksums`  ([manufacturer.py:27](../../pinball_decryptor/plugins/dp/manufacturer.py#L27))
- **Direct-SSD write (2):** `Scan`, `Write to SSD`  ([manufacturer.py:28](../../pinball_decryptor/plugins/dp/manufacturer.py#L28))

---

## Formats — TBL vs AAIW

### TBL — plain `.zip` software update

Every TBL download is a `.zip` whose entries are all wrapped under a single `<version>/` top folder (e.g. `1.01/assets/...`). Inside is a Linux `pyprocgame` build; the moddable media are `.wav` audio and `.cdmd` colour-display video under `assets/` ([games.py:5](../../pinball_decryptor/plugins/dp/games.py#L5)). No encryption.

**Detection of the version folder** — `top_version(names)` returns the leading `<version>/` shared by *all* entries, or None if the layout isn't single-version ([formats.py:52](../../pinball_decryptor/plugins/dp/formats.py#L52)).

**Full vs delta** — both "full" and "delta" downloads are `.zip`s; the difference is a `<version>/delta` marker file. `delta_info()` returns `(version, compatible_bases)`: it reads the `<version>/delta` marker (comma/newline-separated list of base versions this delta installs onto) for a *delta*, or `compat = None` for a *full* image (no marker) ([formats.py:94](../../pinball_decryptor/plugins/dp/formats.py#L94)). Per the in-app guidance, the large "complete" downloads still carry a `delta` marker but contain everything; the user is told to start from a complete base (v1.10, the ~997 MB "from 0.58+" variant) and add the newest delta ([manufacturer.py:41](../../pinball_decryptor/plugins/dp/manufacturer.py#L41)).

**Version arithmetic** — `version_key("1.10") → (1, 10)` for sorting ([formats.py:71](../../pinball_decryptor/plugins/dp/formats.py#L71)); `bump_version("1.15") → "1.16"`, width-preserving (`"1.09" → "1.10"`), used so a rebuilt update is labelled one step newer and the machine's USB-update gate (which only applies a *newer* version) accepts it ([formats.py:79](../../pinball_decryptor/plugins/dp/formats.py#L79)).

**Cumulative delta semantics** — TBL deltas are cumulative: a single recent delta usually carries everything changed since the base, so one delta on top of a complete base reaches the latest version. Each delta wraps files under its *own* version folder (e.g. `1.15/...`), so applying it onto a `1.01/` base requires remapping the version prefix (see [Mod Pack / delta](#mod-pack--delta)).

### AAIW — Clonezilla auto-installer `.img`

AAIW ships as `AAIW_x.xx_full_image.img`, an MBR-partitioned Clonezilla USB auto-installer ([aaiw.py:1](../../pinball_decryptor/plugins/dp/aaiw.py#L1)):

```
AAIW_x.xx_full_image.img            (MBR)
  partition 1  small SYSLINUX/FAT boot
  partition 2  ext4  ->  /pinball-image/   (Clonezilla backup of the SSD)
      sda1.vfat-ptcl-img.zst          (game ESP, ~16 MB)
      sda2.ext4-ptcl-img.zst          (game root — assets live here)
```

`sda2.ext4-ptcl-img.zst` is a **partclone image-format v2** stream, **zstd-compressed**. The pure-Python `core/partclone.py` reconstructs it to a raw ext4 image with no `partclone`/`zstd` binaries: it parses the v2 header (`image_head_v2` 36 B + `file_system_info_v2` 52 B + `image_options_v2` 18 B + CRC), the used-block bitmap, then writes only used blocks (CRC interleaved every `blocks_per_checksum`). `restore_zst()` / `restore_zst_fileobj()` wrap a `zstandard` stream reader ([partclone.py:210](../../pinball_decryptor/core/partclone.py#L210), [partclone.py:184](../../pinball_decryptor/core/partclone.py#L184)). Once reconstructed, the assets at `/opt/assets/alice` are ordinary `.mp4` / `.mov` / `.wav` / `.png` ([games.py:9](../../pinball_decryptor/plugins/dp/games.py#L9)).

**MBR parsing** is filesystem-free: `parse_mbr_partitions()` reads only the 512-byte MBR (`0x55AA` signature, four 16-byte entries, `<II` LBA-start + sector count — [formats.py:119](../../pinball_decryptor/plugins/dp/formats.py#L119)); `find_ext_partition()` picks the largest Linux (`0x83`) partition, falling back to the largest of any type ([formats.py:141](../../pinball_decryptor/plugins/dp/formats.py#L141)).

### `.cdmd` colour-DMD video format (TBL)

TBL's LCD plays full-colour clips stored in a custom, unencrypted container. Reverse-engineered layout (all uint32 little-endian — [cdmd.py:1](../../pinball_decryptor/plugins/dp/cdmd.py#L1)):

```
File header (16 bytes):
  [0:4]   magic = 01 02 15 20
  [4:8]   nframes
  [8:12]  canvasW   (observed 272)
  [12:16] canvasH   (observed 102)
Then, per frame:
  x, y, w, h   (4 × uint32 = 16 bytes) — the changed sub-rectangle
  pixel data   = w*h*4 bytes in ARGB order (byte0=Alpha, then R, G, B)
```

Frames are **dirty rectangles**: each frame carries only the region that changed since the previous frame, composited onto a persistent canvas. Single-frame files are stills (icons, text strips); multi-frame files are animations/clips (`character_videos_*`). `parse_header()` validates magic + geometry (rejects canvas >8192 — [cdmd.py:123](../../pinball_decryptor/plugins/dp/cdmd.py#L123)); `iter_frames()` keeps a persistent RGBA canvas and `alpha_composite`s each sub-rect, yielding a full composited copy per frame ([cdmd.py:146](../../pinball_decryptor/plugins/dp/cdmd.py#L146)). ARGB→RGBA reordering is a strided byte shuffle ([cdmd.py:136](../../pinball_decryptor/plugins/dp/cdmd.py#L136)). Video clips ship a sibling `<name>.wav`; when present the MP4 frame rate is derived from the audio duration so video and sound stay synced ([cdmd.py:297](../../pinball_decryptor/plugins/dp/cdmd.py#L297)).

Some files (notably bitmap fonts under `fonts/`) reuse the `.cdmd` extension but begin with a different `dmd\0` magic — these are *not* video and are skipped ([cdmd.py:419](../../pinball_decryptor/plugins/dp/cdmd.py#L419), test `test_cdmd_rejects_non_video_magic`).

---

## Extract pipeline (TBL)

`TblExtractPipeline._run()` ([pipeline.py:58](../../pinball_decryptor/plugins/dp/pipeline.py#L58)):

1. **Phase 0 — Detect** ([pipeline.py:59](../../pinball_decryptor/plugins/dp/pipeline.py#L59)). `detect_game(zip) == "tbl"` or raise. Make `output_dir`.
2. **Phase 1 — Extract / baseline / merge** ([pipeline.py:69](../../pinball_decryptor/plugins/dp/pipeline.py#L69)).
   - **Unzip** safely: `_safe_zip_targets()` rejects absolute paths and `..` traversal (entries that escape `output_dir` yield `target=None` and are skipped — [pipeline.py:27](../../pinball_decryptor/plugins/dp/pipeline.py#L27)). Entries are streamed to disk; progress every 25 entries.
   - **Detect base version**: `_detect_base_version()` returns the single numeric `<version>/` dir in the tree (excluding `_DECODED VIDEOS`), or **None** if there isn't exactly one ([pipeline.py:516](../../pinball_decryptor/plugins/dp/pipeline.py#L516)).
   - **Baseline checksums BEFORE deltas** ([pipeline.py:97](../../pinball_decryptor/plugins/dp/pipeline.py#L97)). `generate_checksums()` runs on the *pristine* base, excluding `_DECODED VIDEOS`. This ordering is deliberate: a later Build diffs the current tree against this baseline, so the merged deltas' changes (and the user's edits) are *both* picked up as modifications and folded into the rebuilt update.
   - **Chain deltas** (only if `deltas` supplied — [pipeline.py:109](../../pinball_decryptor/plugins/dp/pipeline.py#L109)). `chain_deltas()` applies each delta in ascending version order, remapped onto the base version folder; raises `ValueError` (→ `PipelineError`) on an incompatible delta. Returns `(applied_versions, compatible_bases)`.
   - **BUILD_META** ([pipeline.py:123](../../pinball_decryptor/plugins/dp/pipeline.py#L123)). Computes `merged_version` (last applied, else base). If no `compatible` came back from the merge, it seeds the compat set from the *base zip's own* delta marker plus the base version. Writes `.dp_build.json` **only when `base_version` is truthy** ([pipeline.py:135](../../pinball_decryptor/plugins/dp/pipeline.py#L135)) — `write_build_meta(out_dir, base_version, merged_version, compatible)` ([pipeline.py:666](../../pinball_decryptor/plugins/dp/pipeline.py#L666)).
3. **Phase 2 — Decode** ([pipeline.py:139](../../pinball_decryptor/plugins/dp/pipeline.py#L139)). `cdmd.convert_all_cdmd()` walks the (post-merge) tree, decoding each video `.cdmd` into `_DECODED VIDEOS/` (mirroring relative paths), with the dot-matrix shader on iff `self.dmd`. Wrapped in try/except so a decode failure is a warning, not a pipeline abort.
4. **Phase 3 — Finalize** ([pipeline.py:157](../../pinball_decryptor/plugins/dp/pipeline.py#L157)). Builds the merge-summary and emits the success message.

**Output layout:** `output_dir/<version>/assets/...` (raw extracted tree, version prefix preserved) + `output_dir/_DECODED VIDEOS/...` (decoded MP4/PNG, kept out of the baseline so they are never re-packed) + `.checksums.md5` + `.dp_build.json`.

**base_version=None handling (the summary-join fix):** at [pipeline.py:157](../../pinball_decryptor/plugins/dp/pipeline.py#L157) the "Merged updates: a -> b" chain is built as `[base_version or "base image"] + [a for a in applied if a]`. The `or "base image"` substitution is load-bearing: when the base zip carries no detectable single version (e.g. a full image where `_detect_base_version` returns None), a raw `" -> ".join([None, ...])` would raise *"sequence item 0: expected str instance, NoneType found"* — a crash that surfaced only *after* an otherwise-successful extract. Every other use of `base_version` already guarded for None; this join is the one that was fixed.

---

## Extract pipeline (AAIW)

`AaiwExtractPipeline._run()` ([pipeline.py:187](../../pinball_decryptor/plugins/dp/pipeline.py#L187)):

1. **Phase 0 — Detect** ([pipeline.py:188](../../pinball_decryptor/plugins/dp/pipeline.py#L188)). `detect_game(img) == "aaiw"` or raise. Logs whether 7-Zip is present (no hard WSL pre-check — the extractor raises a clear error if neither tool is available).
2. **Phase 1 — Extract** ([pipeline.py:206](../../pinball_decryptor/plugins/dp/pipeline.py#L206)). Delegates to `aaiw.extract()`, which dispatches **7-Zip preferred, WSL fallback** ([aaiw.py:369](../../pinball_decryptor/plugins/dp/aaiw.py#L369)):
   - **7-Zip path** (`_extract_via_7z` — [aaiw.py:107](../../pinball_decryptor/plugins/dp/aaiw.py#L107)): (1) list MBR partitions, extract the *largest* (the ext4 carrier); (2) pull `pinball-image/*.ext4-ptcl-img.zst` out by wildcard (listing an ext4 image can exit non-zero on an odd inode, so extraction is by-name, not by-listing); (3) `partclone.restore_zst()` → raw ext4; (4) `7z x raw opt/assets/alice` → temp, then move children into `output_dir`. All intermediate files are deleted as it goes; runs in a `tempfile.mkdtemp` cleaned in `finally`.
   - **WSL fallback** (`_extract_via_wsl` — [aaiw.py:201](../../pinball_decryptor/plugins/dp/aaiw.py#L201)): loop-mount the carrier partition at `find_ext_partition()`'s byte offset (read-only); `cat` the `.zst` through `partclone.restore_zst_fileobj()` to a raw image; loop-mount that ext4; `tar cf - -C <mount>/opt/assets/alice .` streamed and extracted with `safe_member()` guarding traversal. Mounts/unmounts via the executor; cleanup in `finally`.
   - **7-Zip→WSL recovery:** if the 7-Zip path raises and WSL *is* available, partial output is cleared and the WSL path retries ([aaiw.py:386](../../pinball_decryptor/plugins/dp/aaiw.py#L386)). If 7-Zip is the *only* tool and it fails, the error propagates.
3. **Phase 2 — Decode (optional)** ([pipeline.py:219](../../pinball_decryptor/plugins/dp/pipeline.py#L219)). Only if `convert_video` (the relabelled `decode_dmd` toggle): `aaiw.convert_movs_to_mp4()` transcodes every `.mov` (Apple ProRes, used for alpha video, which most Windows players can't open) to H.264 `.mp4` via ffmpeg, padding to even dims, then deletes the `.mov` ([aaiw.py:306](../../pinball_decryptor/plugins/dp/aaiw.py#L306)). No ffmpeg → warning, files left as-is.
4. **Phase 3 — Finalize** ([pipeline.py:228](../../pinball_decryptor/plugins/dp/pipeline.py#L228)). `generate_checksums()` over the output (baseline for Replace-Audio / mod-pack diffing). Success message explicitly states re-imaging the SSD is not supported — **edit-in-place only**.

**Output layout:** `output_dir/<contents of /opt/assets/alice>` (flat copy of the subtree's children) + `.checksums.md5`. No version folder, no BUILD_META.

---

## Write / repack pipeline

**TBL only.** `TblWritePipeline._run()` rebuilds a TBL update `.zip`, swapping in modified files ([pipeline.py:351](../../pinball_decryptor/plugins/dp/pipeline.py#L351)):

1. **Detect** ([pipeline.py:352](../../pinball_decryptor/plugins/dp/pipeline.py#L352)). The original must be a TBL zip — if not, raise with an explicit message that AAIW SSD re-imaging is out of scope ([pipeline.py:357](../../pinball_decryptor/plugins/dp/pipeline.py#L357)). Assets folder must exist.
2. **Scan** ([pipeline.py:365](../../pinball_decryptor/plugins/dp/pipeline.py#L365)). Read the `.checksums.md5` baseline; a file is "changed" iff its current MD5 differs from the baseline. No baseline → error ("Run Extract first"). No changes → output rebuilds the original verbatim.
3. **Repack** ([pipeline.py:388](../../pinball_decryptor/plugins/dp/pipeline.py#L388)).
   - **Version labelling** ([pipeline.py:389](../../pinball_decryptor/plugins/dp/pipeline.py#L389)): `base_version = top_version(original namelist)`. Read `.dp_build.json` → `merged_version` (else base) and `compatible_bases`. `target_version = bump_version(merged_version)` — **one newer than the merged version**, so the machine's USB-update gate accepts it. The compat list is logged as "Installs onto machines running: …".
   - **Rebuild** (`_rebuild` — [pipeline.py:427](../../pinball_decryptor/plugins/dp/pipeline.py#L427)): re-zip every member of the original (`ZIP_DEFLATED`), `remap`ing the `base_version/` prefix to `target_version/` ([pipeline.py:431](../../pinball_decryptor/plugins/dp/pipeline.py#L431)). The original `<base>/delta` marker is dropped and a **fresh** `<target>/delta` marker is written listing `compatible` ([pipeline.py:471](../../pinball_decryptor/plugins/dp/pipeline.py#L471)). Modified members get the edited bytes; unchanged members are copied through; original mode/mtime are preserved via a copied `ZipInfo`. New files not in the original (e.g. added audio) are appended via `_find_extra_files()`, which skips `_DECODED VIDEOS/`, dotfiles, and symlinks ([pipeline.py:483](../../pinball_decryptor/plugins/dp/pipeline.py#L483)).
4. **Finalize** ([pipeline.py:413](../../pinball_decryptor/plugins/dp/pipeline.py#L413)). Reports output size + the suggested filename `TBL-v<target>.zip`, with install instructions (copy, don't unzip, to a USB stick → Service → Software → USB Update).

**Apply-Delta overlay** (separate from chain-on-extract): `apply_delta()` overlays *one* delta `.zip` onto an already-extracted assets folder ([pipeline.py:571](../../pinball_decryptor/plugins/dp/pipeline.py#L571)). It validates compatibility (the delta's `compat` list must include the extracted base) and remaps the delta's version prefix onto the base. See [Mod Pack / delta](#mod-pack--delta).

**AAIW write is NOT supported.** There is no AAIW write pipeline; `make_write_pipeline()` always returns `TblWritePipeline` ([manufacturer.py:111](../../pinball_decryptor/plugins/dp/manufacturer.py#L111)), and that pipeline rejects non-TBL input. AAIW mods are edit-in-place (or pushed via Direct-SSD write, which copies loose files but does not re-image).

---

## Direct-SSD

`ssd.py` mounts a physically-connected game SSD's Linux root partition and copies the asset subtree out (Extract) or writes modified files back in place (Write) — no `.img`/`.zip` intermediate ([ssd.py:1](../../pinball_decryptor/plugins/dp/ssd.py#L1)). Used by both games; the asset subtree is auto-detected so one code path serves both.

**Device paths:** OS-native physical-disk paths — `\\.\PHYSICALDRIVEn` (Windows), `/dev/sdX` (Linux). The `partition_override` from the GUI's "Force partition #" field is honoured; `None` means auto-discover.

**Mount (Windows)** (`_mount_windows` — [ssd.py:149](../../pinball_decryptor/plugins/dp/ssd.py#L149)): unmount any prior WSL mount; take the disk **offline** via `Set-Disk -IsOffline $true` (so Windows releases it); then for each candidate partition `wsl --mount \\.\PHYSICALDRIVEn --partition N --type ext4 --options ro|rw`. On an "ALREADY" error it `wsl --shutdown`s and retries. Candidate partitions come from `Get-Partition` (skipping <256 MB boot/ESP partitions, largest first), falling back to a `2,1,3,4,5,6,7,8` sweep ([ssd.py:69](../../pinball_decryptor/plugins/dp/ssd.py#L69)). Requires Administrator + WSL2.

**Mount (Linux)** (`_mount_linux` — [ssd.py:200](../../pinball_decryptor/plugins/dp/ssd.py#L200)): `mount /dev/sdXN` over candidates `[2,1,3,4]` (or the override). Requires sudo.

**Content verification / safety** (`find_game_subtree` — [ssd.py:99](../../pinball_decryptor/plugins/dp/ssd.py#L99)): each candidate partition is mounted and *content-verified* before use — it must contain either AAIW's fixed `/opt/assets/alice`, or a TBL `.../assets/sequences` dir holding `.cdmd` files. A partition that doesn't match is detached and the next is tried. If none match, the disk is brought back online and a clear error is raised. This guards against writing to the wrong disk. Writes are further limited to files that differ from the Extract baseline (`md5_file != baseline`), and a `sync` is issued after writing. The module header is explicit that the physical-drive *attach* path can only be exercised with a real connected SSD (mount/read/write/tar mechanics are validated against loop images).

**Extract** (`extract_from_ssd` — [ssd.py:233](../../pinball_decryptor/plugins/dp/ssd.py#L233)): mount read-only, `tar cf - -C <mount><subtree> .` streamed through `tarfile` with `safe_member()` traversal guards, cleanup in `finally`. Then the pipeline generates baseline checksums (phase "Checksums").

**Write** (`write_to_ssd` — [ssd.py:288](../../pinball_decryptor/plugins/dp/ssd.py#L288)): `DpDirectSsdWritePipeline` first scans the assets folder for files whose MD5 differs from the baseline ([pipeline.py:294](../../pinball_decryptor/plugins/dp/pipeline.py#L294)); if none differ it exits without mounting. Otherwise it mounts read-write and `cp`s each changed file to `<mount><subtree>/<rel>` (rejecting `..` paths), then `sync`s ([ssd.py:316](../../pinball_decryptor/plugins/dp/ssd.py#L316)). Reboot the machine to load changes.

---

## Audio assets

DP audio is loose, uncompressed-container `.wav`/`.ogg`, so `capabilities.replace_audio = True` and `audio_slot_dirs()` is **not** overridden — the Replace-Audio tab does a **whole-tree scan** of the extract output (registry default returns None → scan everything — [registry.py:283](../../pinball_decryptor/core/registry.py#L283)). Assigned replacements are format-matched and staged over the extracted files; the normal TBL Write pipeline then repacks them (and `_find_extra_files` appends any brand-new audio not in the original zip).

- **TBL:** `.wav` audio under `<version>/assets/` (e.g. `assets/sound/*.wav`, and `<name>.wav` siblings beside `.cdmd` clips for A/V sync) ([games.py:5](../../pinball_decryptor/plugins/dp/games.py#L5), [cdmd.py:192](../../pinball_decryptor/plugins/dp/cdmd.py#L192)).
- **AAIW:** `.wav` (plus `.mp4`/`.mov`/`.png`) under `/opt/assets/alice` ([games.py:9](../../pinball_decryptor/plugins/dp/games.py#L9)). Replace-Audio can edit these in place, but there is no AAIW write-back to the image — only Direct-SSD write reaches the real machine.

---

## DMD / video

### TBL `.cdmd` decode (`cdmd.py`)

`convert_all_cdmd()` walks the extract for `.cdmd` files, filters out non-video ones, and decodes each into `_DECODED VIDEOS/` preserving relative structure ([cdmd.py:401](../../pinball_decryptor/plugins/dp/cdmd.py#L401)). Per file (`decode_cdmd_file` — [cdmd.py:368](../../pinball_decryptor/plugins/dp/cdmd.py#L368)): `nframes <= 1` → `.png` (last frame); multi-frame + ffmpeg → `.mp4`; multi-frame, no ffmpeg → fallback last-frame `.png`. MP4 building (`cdmd_to_mp4` — [cdmd.py:297](../../pinball_decryptor/plugins/dp/cdmd.py#L297)) pipes raw RGB frames straight into ffmpeg (avoiding hundreds of intermediate PNGs), deriving FPS from a sibling `.wav` (clamped 1–60) and muxing the audio when present.

**Optional dot-matrix shader (TBL-only, via `decode_dmd` toggle):** `render_dmd()` ([cdmd.py:234](../../pinball_decryptor/plugins/dp/cdmd.py#L234)) renders each frame as a colour LED dot-matrix panel — every source pixel becomes a round dot (`DMD_CELL = 8` px pitch, `DMD_DOT_RATIO = 0.82`) on black, with an additive Gaussian-blur bloom and a black bezel (`DMD_BORDER = 8`). The per-cell dot mask is supersampled-then-downscaled and cached per geometry ([cdmd.py:207](../../pinball_decryptor/plugins/dp/cdmd.py#L207)). It upscales ~8× and adds bloom, so it is off by default (slower extract). With the shader off, frames are just flattened onto black, padded to even dims for H.264 ([cdmd.py:263](../../pinball_decryptor/plugins/dp/cdmd.py#L263)).

**Non-video `.cdmd` skipping:** bitmap fonts/glyphs reuse the `.cdmd` extension with a `dmd\0` magic. `is_cdmd()` checks the `01 02 15 20` magic ([cdmd.py:112](../../pinball_decryptor/plugins/dp/cdmd.py#L112)); non-matching files are counted as *skipped*, not *failed* ([cdmd.py:419](../../pinball_decryptor/plugins/dp/cdmd.py#L419)).

### AAIW ProRes → MP4

The same Extract checkbox, relabelled per game ([manufacturer.py:75](../../pinball_decryptor/plugins/dp/manufacturer.py#L75)), drives `convert_movs_to_mp4()` for AAIW — transcoding Apple ProRes `.mov` (alpha video) to H.264 `.mp4` so they play on Windows ([aaiw.py:306](../../pinball_decryptor/plugins/dp/aaiw.py#L306)).

---

## Mod Pack / delta

Two distinct delta mechanisms, both keyed on `version_key` ordering and the `<version>/delta` compat marker:

- **`chain_deltas` (Extract-time, capability `chain_deltas`)** — `chain_deltas()` ([pipeline.py:604](../../pinball_decryptor/plugins/dp/pipeline.py#L604)) takes a *list* of deltas supplied alongside a full-image Input. It reads each delta's `(version, compat)`, **skips** unreadable ones and full-image ones (`compat is None`), sorts ascending by `version_key`, and applies each in order. Before each apply it checks the *running* version is in that delta's compat list (raising `ValueError` if not). It returns `(applied_versions, compatible_bases)` where `compatible_bases` unions the base, every applied version, and each delta's own compat list — this union becomes the rebuilt update's future-install list.
- **`apply_delta` (post-extract overlay, capability `apply_delta`)** — `apply_delta()` ([pipeline.py:571](../../pinball_decryptor/plugins/dp/pipeline.py#L571)) overlays a *single* delta onto an already-extracted folder, validating `base in compat` and remapping.

Both call `_apply_delta_zip()` ([pipeline.py:528](../../pinball_decryptor/plugins/dp/pipeline.py#L528)), which is the crux of correct overlay: a delta wraps files under its *own* `delta_version/` folder, but they must land on the *base's* version folder. So it rewrites `delta_version/<rest>` → `base_version/<rest>`, **drops the bare `delta` marker** (it's metadata, must not leak into the tree), and rejects `..` traversal. Returns `(overwritten, added, total)`.

`version_key` ([formats.py:71](../../pinball_decryptor/plugins/dp/formats.py#L71)) is the single ordering authority for "version order" everywhere (merge order, compat-list sorting, the `1.10 > 1.9` test).

---

## Detection

`detect_game(path)` is the dispatcher ([formats.py:186](../../pinball_decryptor/plugins/dp/formats.py#L186)): `.zip` + `is_tbl_zip()` → `"tbl"`; `.img` + `is_aaiw_img()` → `"aaiw"`; else None.

- **`is_tbl_zip()`** ([formats.py:23](../../pinball_decryptor/plugins/dp/formats.py#L23)) inspects internal layout (first 4000 entries): a `<version>/delta` marker → True immediately; otherwise needs both a `.cdmd` file *and* an `assets/` dir (or just `.cdmd` as a last resort). Content-based, not filename-based.
- **`is_aaiw_img()`** ([formats.py:157](../../pinball_decryptor/plugins/dp/formats.py#L157)) requires `.img` + a valid MBR with a Linux (`0x83`) partition, then accepts on either a filename hint (`aaiw`/`alice`/`wonderland`) *or* the installer shape (exactly two partitions, the second being Linux). Cheap — never mounts.

`Manufacturer.detect()` ([manufacturer.py:85](../../pinball_decryptor/plugins/dp/manufacturer.py#L85)) returns a `Game` with a per-game `notes` badge ("Clonezilla installer image" vs "Software update").

**Per-game capability overrides** (driven by `_is_aaiw_input()`, which is purely the `.img` extension test — [manufacturer.py:65](../../pinball_decryptor/plugins/dp/manufacturer.py#L65)):

- `decode_dmd_applies(input)` → True for both ([manufacturer.py:70](../../pinball_decryptor/plugins/dp/manufacturer.py#L70)); but `decode_dmd_label_for(input)` swaps the text (dot-matrix shader vs ProRes convert — [manufacturer.py:75](../../pinball_decryptor/plugins/dp/manufacturer.py#L75)).
- `chain_deltas_applies(input)` → **TBL-only** (False for `.img` — [manufacturer.py:81](../../pinball_decryptor/plugins/dp/manufacturer.py#L81)).

These wire the GUI: the video toggle shows for both games (relabelled), the merge-updates picker only for TBL. Verified by `test_dp_game_aware_controls` and `test_aaiw_ignores_dmd_toggle`.

---

## Gotchas & non-obvious details

- **`base_version = None` for full images + the summary-join fix.** `_detect_base_version()` returns None unless there's *exactly one* numeric `<version>/` dir. Full images that aren't a clean single-version layout yield None. The Finalize merge-summary join (`[base_version or "base image"] + …`) and the `if base_version:` guard on `write_build_meta` both exist because of this — the `or "base image"` specifically fixed a *post-success* crash (`"sequence item 0: expected str instance, NoneType found"`) when joining `[None, ...]` ([pipeline.py:157](../../pinball_decryptor/plugins/dp/pipeline.py#L157)).
- **TBL deltas are cumulative.** One recent delta on a complete base usually reaches the latest version; `chain_deltas` validates each against the *running* version, not just the original base, so a single delta normally satisfies the chain ([pipeline.py:637](../../pinball_decryptor/plugins/dp/pipeline.py#L637)).
- **Baseline checksums run BEFORE deltas** so a later Build folds both the merged deltas and the user's edits into the rebuilt update ([pipeline.py:97](../../pinball_decryptor/plugins/dp/pipeline.py#L97)).
- **AAIW has no write-back.** `make_write_pipeline` always builds the TBL pipeline, which rejects `.img`. AAIW mods are edit-in-place; the only path onto a real AAIW machine is Direct-SSD write ([manufacturer.py:111](../../pinball_decryptor/plugins/dp/manufacturer.py#L111), [pipeline.py:357](../../pinball_decryptor/plugins/dp/pipeline.py#L357)).
- **7-Zip vs WSL for AAIW.** 7-Zip is ~15× faster (local NTFS I/O, no WSL boundary); WSL is fallback only. 7-Zip exit codes are unreliable on ext4 (warnings/odd inodes), so success is judged by *output presence*, and the `.zst` is pulled by wildcard rather than by listing the ext4 first ([aaiw.py:63](../../pinball_decryptor/plugins/dp/aaiw.py#L63), [aaiw.py:127](../../pinball_decryptor/plugins/dp/aaiw.py#L127)).
- **`.cdmd` font/glyph skip.** Same extension, different `dmd\0` magic — skipped as non-video (counted "skipped", never "failed") so font assets don't pollute the decode-failure count ([cdmd.py:419](../../pinball_decryptor/plugins/dp/cdmd.py#L419)).
- **`_DECODED VIDEOS/` is excluded everywhere** — from baseline checksums, from re-pack (`_find_extra_files` and the apply-delta walk), so decoded derivatives never leak back into a built update ([pipeline.py:20](../../pinball_decryptor/plugins/dp/pipeline.py#L20), [pipeline.py:489](../../pinball_decryptor/plugins/dp/pipeline.py#L489)).
- **Per-game capability gating** is by `.img` extension (`_is_aaiw_input`), not full detection, so the GUI can gate controls cheaply before a heavy detect ([manufacturer.py:65](../../pinball_decryptor/plugins/dp/manufacturer.py#L65)).
- **Direct-SSD physical-attach is unverified on hardware** — the loop-image mechanics are tested, but the `Set-Disk`/`wsl --mount` of a real SSD has not been exercised against a connected drive (module header, [ssd.py:24](../../pinball_decryptor/plugins/dp/ssd.py#L24)). *(Matches the repo's recent "untested on hardware" commit.)*
- **Build labels one version newer.** `bump_version(merged_version)` is required because the machine's USB update only applies a *newer* version; the rebuilt zip is remapped to that prefix and gets a fresh `<target>/delta` compat marker ([pipeline.py:396](../../pinball_decryptor/plugins/dp/pipeline.py#L396), [pipeline.py:471](../../pinball_decryptor/plugins/dp/pipeline.py#L471)).

---

## Key files

- **`__init__.py`** ([__init__.py:1](../../pinball_decryptor/plugins/dp/__init__.py#L1)) — `register()` entry point.
- **`manufacturer.py`** ([manufacturer.py:1](../../pinball_decryptor/plugins/dp/manufacturer.py#L1)) — `DutchPinballManufacturer`: capabilities, InputSpec, phase labels, prereqs, per-game overrides, pipeline factories, `detect()`.
- **`games.py`** ([games.py:1](../../pinball_decryptor/plugins/dp/games.py#L1)) — `GAME_DB`: `tbl` / `aaiw` metadata (format, filename hints, asset roots).
- **`formats.py`** ([formats.py:1](../../pinball_decryptor/plugins/dp/formats.py#L1)) — detection (`detect_game`, `is_tbl_zip`, `is_aaiw_img`), MBR parsing, version helpers (`top_version`, `version_key`, `bump_version`, `delta_info`).
- **`pipeline.py`** ([pipeline.py:1](../../pinball_decryptor/plugins/dp/pipeline.py#L1)) — all five pipelines (TBL/AAIW extract, TBL write, Direct-SSD extract/write), `apply_delta`/`chain_deltas`, `_apply_delta_zip`, BUILD_META read/write.
- **`aaiw.py`** ([aaiw.py:1](../../pinball_decryptor/plugins/dp/aaiw.py#L1)) — Clonezilla `.img` extraction (7-Zip + WSL paths), ProRes→MP4.
- **`ssd.py`** ([ssd.py:1](../../pinball_decryptor/plugins/dp/ssd.py#L1)) — Direct-SSD mount/extract/write, `find_game_subtree`.
- **`cdmd.py`** ([cdmd.py:1](../../pinball_decryptor/plugins/dp/cdmd.py#L1)) — `.cdmd` colour-DMD decode, dot-matrix shader, ffmpeg discovery.
- **`../../pinball_decryptor/core/partclone.py`** ([partclone.py:1](../../pinball_decryptor/core/partclone.py#L1)) — pure-Python partclone-v2 + zstd restore (used by AAIW).
- **`../../pinball_decryptor/core/registry.py`** ([registry.py:127](../../pinball_decryptor/core/registry.py#L127)) — `Manufacturer` base contract, `Capabilities`, per-game override hooks.
- **`../../tests/test_dp.py`** ([test_dp.py:1](../../tests/test_dp.py#L1)) — detection, cdmd decoder, partclone reader, TBL extract/build round-trips, delta chaining, SSD wiring.

## Related docs

- [`bof.md`](bof.md), [`ap.md`](ap.md), [`spooky.md`](spooky.md), [`pb.md`](pb.md) — sibling manufacturer plugin architectures.
- `../AP_PKG_RE.md`, `../CGC_BNK_RE.md` — format reverse-engineering notes for other plugins.
- *(unverified)* No standalone DP format-RE note exists yet under `docs/`; the `.cdmd` and partclone-v2 layouts are documented inline in `cdmd.py` and `core/partclone.py` respectively.
