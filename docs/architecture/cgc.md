# Chicago Gaming Company (`cgc`) — Architecture

> The `cgc` plugin extracts and rebuilds Chicago Gaming Company factory installer `.img` files — bootable, MBR-partitioned USB-flash images whose game assets live inside a triple-nested chain of disk images (`installer.img` → inner `emmc.img` → inner ext4 P2). It targets four titles: the WPC-emulator remakes Medieval Madness / Attack From Mars / Monster Bash (which ship the original Williams WPC ROM plus pre-extracted loose `.wav` audio) and the CGC-original Pulp Fiction (whose audio lives in an in-house "JPS" `.bnk` sound-bank format, fully reverse-engineered to extract → WAV and repack WAV → bank). All ext4-aware work runs in an executor (WSL on Windows, native on Linux, Docker on macOS) via `debugfs`, and audio samples can optionally be auto-transcribed to a `callouts.csv` with faster-whisper. CGC machines render all video in real time, so there are no video files to mod — only audio (and, extract-only, a decoded WPC-DMD render for the remakes).

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/cgc/`
- **Key:** `cgc` ([manufacturer.py:19](../../pinball_decryptor/plugins/cgc/manufacturer.py#L19))
- **Display:** `Chicago Gaming Company` ([manufacturer.py:20](../../pinball_decryptor/plugins/cgc/manufacturer.py#L20))

### Supported games

The game DB ([games.py:58](../../pinball_decryptor/plugins/cgc/games.py#L58)) defines four titles. All are `supported=True` (the `Game` objects are constructed with no `supported=` argument, which defaults to `True` per [registry.py:48](../../pinball_decryptor/core/registry.py#L48)).

| Key | Display | Supported? | Audio format | Notes |
|---|---|---|---|---|
| `mm_remake` | Medieval Madness Remake | Yes | WPC loose `.wav` | WPC remake; ships Williams ROM; `data_dir=appdata`, ROM typically `appdata/rom/mm_10.rom` |
| `afm_remake` | Attack From Mars Remake | Yes | WPC loose `.wav` | WPC remake; `data_dir=afmdata`, ROM `afmdata/rom/afm_113b.rom` |
| `mb_remake` | Monster Bash Remake | Yes | WPC loose `.wav` | WPC remake; `data_dir=mbdata`, ROM `mbdata/xMB_G11.rom` (no `rom/` subdir, x-prefix CGC name) |
| `pulp_fiction` | Pulp Fiction | Yes | JPS `.bnk` banks | CGC original; 6 `pf*.bnk` banks decoded to `<bnk>/*.wav` + manifest |
| `cactus_canyon` | Cactus Canyon | Yes | Williams **DCS** ROMs + CGC blobs | CGC `pin`-engine remake of the 1998 Bally game. Three editable, **round-trippable** surfaces: original DCS audio (`s2..s7.rom` → `dcs_audio/` streams, DCSExplorer/DCSEncoder), CGC's added audio (`usb.so` → `new_audio/` WAVs, custom decrypt), and the colour LCD art (`cgc.so` → `display_art/` PNGs, custom de-obfuscate). Ships only on a physical microSD master card (image the whole card to `.img`). `asset_subtree=/home/debian/pin`, `data_dir=ccdata`. Full RE: [docs/CC_REVISITED_RE.md](../CC_REVISITED_RE.md) |

The three remakes run the original Williams ROM under CGC's `emumm` emulator binary (`/home/debian/emumm/emumm`); their 1300+ DCS audio samples are already pre-extracted to loose 48 kHz mono `.wav` under `<gamedata>/wav48000/` ([games.py:17-37](../../pinball_decryptor/plugins/cgc/games.py#L17)). Pulp Fiction runs CGC's `pin` binary (SDL/OpenGL ES) and stores audio only in compiled JPS banks ([games.py:38-48](../../pinball_decryptor/plugins/cgc/games.py#L38)).

`_GAMES` is built by sorting the DB entries by lowercased display name ([manufacturer.py:11-15](../../pinball_decryptor/plugins/cgc/manufacturer.py#L11)); the `Game` objects there carry only key/display/manufacturer (no per-game `notes` or `platform`).

### Input extensions / InputSpec

```python
input_spec = InputSpec(label="CGC installer images", extensions=(".img",))
```
([manufacturer.py:38-41](../../pinball_decryptor/plugins/cgc/manufacturer.py#L38))

### Capabilities

`Capabilities(extract=True, write=True, modpack=True, apply_delta=False, iso=False, transcribe=True, decode_dmd=True, replace_audio=True)` ([manufacturer.py:22-37](../../pinball_decryptor/plugins/cgc/manufacturer.py#L22)). Flags that are `True`:

- **`extract`** — surface the Extract tab; decode an installer `.img` into a loose asset tree.
- **`write`** — surface the Write tab; rebuild a flashable installer `.img` with modified assets baked back into the nested ext4.
- **`modpack`** — surface the Mod Pack action (delta/diff packaging of changed files; generic core feature, see [Mod Pack](#mod-pack--delta--direct-ssd)).
- **`transcribe`** — surface the Auto-transcribe checkbox; run faster-whisper across extracted WAVs to emit `callouts.csv` (index-named samples have no embedded text — see [registry.py:64-68](../../pinball_decryptor/core/registry.py#L64)).
- **`decode_dmd`** — surface the "Decode DMD scenes (experimental, extract-only)" checkbox; for the WPC remakes, decode the bundled Williams ROM into PNG scenes + MP4 animations + font sheets under `dmd/`. Default OFF; output is not written back ([registry.py:90-96](../../pinball_decryptor/core/registry.py#L90)).
- **`replace_audio`** — surface the Replace-Audio tab. Both remake loose `.wav` and Pulp Fiction's decoded bank WAVs are plain `.wav` in the extract, so the default whole-tree scan is correct ([manufacturer.py:30-36](../../pinball_decryptor/plugins/cgc/manufacturer.py#L30)). The plugin does **not** override `audio_slot_dirs`, so the Replace-Audio scan walks the whole extract for loose `.wav`/`.ogg` (the `dmd/` render holds no audio, so it's harmless).

`apply_delta=False` and `iso=False`; `capture`, `direct_ssd`, `asset_filters`, `write_version_date`, `chain_deltas` all default `False`.

### Prerequisites

Probed on a worker thread when the user picks CGC ([manufacturer.py:49-67](../../pinball_decryptor/plugins/cgc/manufacturer.py#L49)):

| Name | Where | Probe | Why |
|---|---|---|---|
| `debugfs` | wsl | `which debugfs` | ext4 read/write on installer P3 + emmc.img P2 (from `e2fsprogs`) |
| `xxd` | wsl | `which xxd` | reading the inner `emmc.img` MBR partition table |
| `faster-whisper` | host | `python:faster_whisper` (in-process import on `sys.executable`) | Auto-transcribe samples → `callouts.csv`; ~75 MB `tiny.en` model downloaded on first run and cached in the HF cache |

The pipeline additionally hard-checks `debugfs`, `dd`, and `xxd` on the executor at runtime via `_verify_executor_tools` ([pipeline.py:905-917](../../pinball_decryptor/plugins/cgc/pipeline.py#L905)).

### Phase labels

- **Extract** (5): `("Detect", "Outer image", "Inner image", "Decode game data", "Checksums")` ([manufacturer.py:42](../../pinball_decryptor/plugins/cgc/manufacturer.py#L42))
- **Write** (4): `("Detect", "Copy original", "Stage partitions", "Patch")` ([manufacturer.py:44](../../pinball_decryptor/plugins/cgc/manufacturer.py#L44))
- **Transcribe** (4): `("Load model", "Transcribe", "Rename", "Write CSV")` ([manufacturer.py:45](../../pinball_decryptor/plugins/cgc/manufacturer.py#L45))

## Container & nested-image format

### The three-layer image chain

CGC ships a raw MBR-partitioned disk image that the machine's USB-boot kernel writes to its internal eMMC. The layout is consistent across all four titles ([games.py:1-16](../../pinball_decryptor/plugins/cgc/games.py#L1), [pipeline.py:1-20](../../pinball_decryptor/plugins/cgc/pipeline.py#L1)):

```
installer.img  (MBR)
  P1  FAT16  ~64 MB    uBoot + kernel + initrd   (boot — never touched)
  P2  ext4   ~3 GB     installer Debian rootfs
  P3  ext4   3-9 GB    "data" partition: emmc.img + package.dat + config.dat
        └── /emmc.img  (a regular file inside P3's ext4)
              (MBR)
              P1  FAT16  ~64 MB   game uBoot + kernel
              P2  ext4   ~1-3 GB  game Debian rootfs — contains the assets
```

Extract walks top→bottom; Write reverses the chain and re-packs bottom→top. The inner `emmc.img` path inside P3 is hardcoded to `/emmc.img` (`EMMC_INNER_PATH`, [pipeline.py:57](../../pinball_decryptor/plugins/cgc/pipeline.py#L57)) — "same for every CGC title; package.dat hardcodes it."

### Partition handling

MBR parsing is done in pure Python without `fdisk`, walking the 4 primary entries at offset `0x1BE` and unpacking each 16-byte entry with `<BBBBBBBBII` ([formats.py:50-79](../../pinball_decryptor/plugins/cgc/formats.py#L50)).

- **Outer installer P3** is found by `find_data_partition` ([formats.py:82-97](../../pinball_decryptor/plugins/cgc/formats.py#L82)): both P2 and P3 are type `0x83` ext4, and on MM/AFM/MB the installer rootfs (P2) is actually *larger* than the data partition, so "largest ext4" picks wrong — instead it selects the **highest-LBA** Linux partition (`max(... start_lba)`). This runs against the host file directly, so no executor call is needed to locate P3.
- **Inner emmc.img P2** can't be located by a host-side read because the file lives inside WSL. The pipeline reads the inner MBR table via `xxd -s 446 -l 64 -c 64 -p emmc.img` on the executor, then parses the hex with `_parse_mbr_for_linux` ([pipeline.py:185-191](../../pinball_decryptor/plugins/cgc/pipeline.py#L185), [pipeline.py:641-661](../../pinball_decryptor/plugins/cgc/pipeline.py#L641)) — returning the first Linux (`0x83`) entry. `find_game_partition` ([formats.py:100-109](../../pinball_decryptor/plugins/cgc/formats.py#L100)) is the host-side equivalent (first `0x83` entry) but the pipeline uses the executor-side `xxd` path because the emmc.img only exists on the executor.

We never recreate the `.img` from scratch — that would lose the FAT16 boot partition's uBoot binaries — only patch bytes inside the existing ext4 partitions, preserving everything else byte-for-byte ([pipeline.py:14-19](../../pinball_decryptor/plugins/cgc/pipeline.py#L14)).

### The JPS `.bnk` sound-bank format (Pulp Fiction)

Pulp Fiction's audio is stored in CGC's in-house "JPS" library (confirmed by `strings` on the `pin` binary — every error message is `jps_`-prefixed). The full reverse-engineering journal is in **[docs/CGC_BNK_RE.md](../CGC_BNK_RE.md)**; this summarizes what the shipped code keys off of. The six PF banks (`pfsndui`, `pfsnddiag`, `pfsndfx`, `pfspeech`, `pfspeechBEEPD`, `pfmusic`) all use the same container ([CGC_BNK_RE.md:13-21](../CGC_BNK_RE.md#L13)).

**File layout (high level):**

```
0x0000  filename header   null-padded source .txt name (e.g. "pfsndui.txt")
                          + mostly zeros + MSVC debug-fill (0xCC stack / 0xCD heap)
~0x2A0  per-buffer header table  68-byte entries, one per sound buffer
                          (sample-rate marker 0x0000BB80 = 48000 at entry+0)
        command region    uniform 96-byte chunks: SETV / PLAY / END / DUCK / UNDU / WAIT
                          (a PLAY's +0x20 field = buffer_index * 68)
        sound buffers     N streams, each either a zlib stream or an embedded RIFF/WAVE
```

**Two storage forms** (`SoundBuffer.storage`, [jps_bnk.py:78-104](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L78)):

- **`zlib`** — a standard zlib-DEFLATE stream (header byte `0x78`, second byte one of `0x01/0x5E/0x9C/0xDA`) wrapping a fixed **44-byte JPS magic header** followed by raw 48 kHz s16le stereo PCM. Used by UI/SFX/speech/diagnostic banks.
- **`riff`** — a standard RIFF/WAVE file embedded inline, no compression. Used by the music bank (and occasionally elsewhere — 1 of 465 buffers in `pfsndfx`). RIFF is naturally streamable and zlib wouldn't help large music ([CGC_BNK_RE.md:329-336](../CGC_BNK_RE.md#L329)).

**The 44-byte JPS magic header** (11 LE uint32; `JPS_BUFFER_MAGIC`, [jps_bnk.py:45-58](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L45)) — 9 slots are constant, 2 vary per stream:

| u32 idx | Value | Field |
|---|---|---|
| 0 | `0x0E6F07BB` | constant magic |
| 1 | varies | `hash1` (algorithm unknown — *not* CRC32/Adler32/xxHash of the PCM) |
| 2 | `0x1385CA6D` | constant |
| 3 | `0xDB8E52BF` | constant |
| 4 | `0xCBA86BDF` | constant |
| 5 | `0x3C4B88A6` | constant |
| 6 | `0x31933080` | constant |
| 7 | `0x3855CD0A` | constant |
| 8 | `0x9AC705CB` | constant |
| 9 | `0xD16487E2` | constant |
| 10 | varies | `hash2` (algorithm unknown) |

`hash1`/`hash2` are preserved verbatim during repack rather than recomputed; whether the JPS engine validates them on load is still unconfirmed on real hardware *(unverified)* ([CGC_BNK_RE.md:266-278](../CGC_BNK_RE.md#L266), [CGC_BNK_RE.md:431-439](../CGC_BNK_RE.md#L431)). After the 44-byte header, the remaining decompressed bytes are PCM, trimmed down to a whole number of `CHANNELS * SAMPLE_WIDTH_BYTES = 4`-byte frames ([jps_bnk.py:178-181](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L178)).

**ID table / event-chunk semantics** (per the RE doc, [CGC_BNK_RE.md:43-108](../CGC_BNK_RE.md#L43)): each 32-byte ID-table entry has `id / chunk_offset / chunk_count / flag / params / reserved / hash / pad`; each 96-byte command chunk starts with a 4-char ASCII tag. The shipped parser only reads the `PLAY` tag's buffer reference (it does not parse the full ID table), as described next.

**Per-buffer offset/size table:** RE session 4 verified the per-buffer header table contains **no** offsets or sizes — JPS reads buffers sequentially, relying on zlib's natural framing to advance the read pointer ([CGC_BNK_RE.md:407-413](../CGC_BNK_RE.md#L407)). Between consecutive buffers there is a preserved-but-unknown 4-byte gap (likely MSVC heap fill or an unvalidated per-buffer hash) ([CGC_BNK_RE.md:414-418](../CGC_BNK_RE.md#L414)).

## Extract pipeline

`ExtractPipeline._run` ([pipeline.py:114-311](../../pinball_decryptor/plugins/cgc/pipeline.py#L114)), 5 phases:

### Phase 0 — Detect
Validate it's an MBR `.img` (`is_img_file`), then filename-match the game (`detect_game`). Failures raise `PipelineError("Detect", ...)` with the recognised hints ([pipeline.py:115-132](../../pinball_decryptor/plugins/cgc/pipeline.py#L115)). Then `_verify_executor_tools` checks the executor and `debugfs`/`dd`/`xxd`. P3 is located host-side with `find_data_partition` ([pipeline.py:138-143](../../pinball_decryptor/plugins/cgc/pipeline.py#L138)).

### Phase 1 — Outer image
A staging dir `/tmp/cgc_stage_<pid>/` is created on the executor (`_stage_dir_for`, [pipeline.py:63-65](../../pinball_decryptor/plugins/cgc/pipeline.py#L63)). `dd` slices P3 out of the installer (`skip`/`count` in MiB) → `p3.img`, then `debugfs -R 'dump /emmc.img <out>'` pulls the inner `emmc.img` out of P3 ([pipeline.py:152-175](../../pinball_decryptor/plugins/cgc/pipeline.py#L152)).

### Phase 2 — Inner image
Read inner MBR via `xxd`, parse with `_parse_mbr_for_linux`, `dd` P2 out of `emmc.img` → `inner.img`. Then `debugfs -R 'rdump <asset_subtree> <stage>/rdump_out'` recursively dumps the per-title asset subtree ([pipeline.py:178-236](../../pinball_decryptor/plugins/cgc/pipeline.py#L178)). The subtree is `/home/debian/emumm` for the three remakes and `/home/ubuntu/pin` for Pulp Fiction ([games.py:63-86](../../pinball_decryptor/plugins/cgc/games.py#L63)). Notable robustness details:

- `rdump` is staged to a **no-space** `/tmp` path first because debugfs's mini-parser splits args on whitespace and silently drops files if the path has spaces; the files are then copied to the user's output dir with Python (`_copy_tree_into`, [pipeline.py:834-863](../../pinball_decryptor/plugins/cgc/pipeline.py#L834)).
- `debugfs` returns exit 0 even when `rdump` fails, so the pipeline counts staged files with `find ... | wc -l` and raises if zero ([pipeline.py:223-236](../../pinball_decryptor/plugins/cgc/pipeline.py#L223)).
- On Windows the executor-side `/tmp/...` is reached from the host via `\\wsl.localhost\<distro>\...` (`_exec_to_host` + `_detect_wsl_distro`, [pipeline.py:94-112](../../pinball_decryptor/plugins/cgc/pipeline.py#L94), [pipeline.py:878-902](../../pinball_decryptor/plugins/cgc/pipeline.py#L878)).

The staging dir is removed in a `finally` ([pipeline.py:248-253](../../pinball_decryptor/plugins/cgc/pipeline.py#L248)).

### Phase 3 — Decode game data (per-title post-step)
([pipeline.py:266-302](../../pinball_decryptor/plugins/cgc/pipeline.py#L266))

- **Pulp Fiction:** `_explode_jps_banks` ([pipeline.py:380-427](../../pinball_decryptor/plugins/cgc/pipeline.py#L380)) walks the output tree for every `.bnk` and runs `jps_bnk.extract_bnk(bnk, <stem>/)`, producing a sibling subdir of decoded WAVs + manifest. Per-bank decode failures are logged and skipped (the bank stays in place). Each PF extract decodes 6 banks (≈1032 buffers / ≈54 min of audio per the RE table, [CGC_BNK_RE.md:344-351](../CGC_BNK_RE.md#L344)).
- **Cactus Canyon:** three decode steps.  Each output is a top-level dir in `_DERIVED_SUBDIRS` (excluded from the checksum baseline + pruned from the Write diff like `dmd/`) — but unlike `dmd/`, edits to these dirs ARE written back, by re-encoding into the source eMMC blob at Write time (`_repack_modified_cc_assets`, see [Write](#cactus-canyon-repack)):
  - `_extract_dcs_audio` ([cc_dcs.py](../../pinball_decryptor/plugins/cgc/cc_dcs.py)) — the original 1998 Williams **DCS** audio. `cc_dcs.extract_streams` zips `ccdata/rom/s2..s7.rom` as **`cc_113.zip`** (basename MUST match `^cc_\d.*` or DCSExplorer's loader drops the factory-mislabeled `s7`/U7 ROM) and runs `DCSExplorer --extract-streams` → **629 addressable streams** to `dcs_audio/st_*.wav` (filename carries the ROM `$ADDR`). faster-whisper still names the speech streams.
  - `_extract_usb_audio` ([cc_usb_audio.py](../../pinball_decryptor/plugins/cgc/cc_usb_audio.py)) — CGC's **added** audio. Decrypts `ccdata/usb.so` (`dcs_decrypt`: half byte-shuffle + 13-word XOR + 16-bit prefix-sum, numpy) and slices the 756 records' **raw 48 kHz mono PCM** payloads → `new_audio/*.wav` (no codec — verified `decoded_len == 2*sample_count`).
  - `_extract_art` ([cc_art.py](../../pinball_decryptor/plugins/cgc/cc_art.py)) — the colour LCD images. De-obfuscates `ccdata/cgc.so` ("CCGC" archive; 5-key XOR by index + conditional ROL8, numpy), reads the `cc_art` index out of the extracted `pin` ELF (minimal in-tree ELF reader), and renders **2044 images** → `display_art/*.png`. Each frame is RGB565, in one of two encodings selected by `cc_art[i].extra[0] & 0x10000`: **raw** (`w*h` words) or an **RLE sprite** with transparency (838 frames — `_decode_rle_words`: transparent-run / literal-run tokens; reading these as raw was the old "colour noise" bug). Only raw frames are repackable in place (RLE is variable-length packed with offsets baked into `pin`), so `repack_art` skips + warns on RLE edits.
  - `_render_cc_videos` ([cc_video.py](../../pinball_decryptor/plugins/cgc/cc_video.py)) — **optional** (wired to the "Decode DMD scenes" checkbox, off by default; needs ffmpeg). Groups `display_art/` frames into animation sequences (`<base>_NN`; ~228) and renders each to `videos/<base>.mp4` through the colour dot-matrix shader (`dp.cdmd.render_dmd` + `williams.dmd_render.render_pngs_to_mp4`). Extract-only.

  Full RE (ciphers, offsets, pin addresses): [docs/CC_REVISITED_RE.md](../CC_REVISITED_RE.md). New deps: `numpy` (the usb.so/cgc.so transforms over 185 MB/70 MB would be far too slow in pure Python); `DCSEncoder.exe` bundled in `williams/vendor/` for DCS repack; `ffmpeg` (optional, for the display-art videos).
- **MM/AFM/MB with `decode_dmd` ticked:** `_extract_dmd_assets` ([pipeline.py:313-378](../../pinball_decryptor/plugins/cgc/pipeline.py#L313)) walks `<output>/<data_dir>/` for a WPC-sized `.rom` (256 KB / 512 KB / 1 MB — `WPC_ROM_SIZES`), picks the largest, and feeds its bytes to the Williams decoder `wpc_extract.extract_dmd_assets(...)` at `pixel_size=15` → `dmd/`. Decode failures (`WpcDecodeError`) downgrade to a warning. See [DMD / video](#dmd--video).
- **Otherwise:** logs that DMD decode was skipped.

### Phase 4 — Checksums
`generate_checksums(output_dir, exclude_dirs={DMD_SUBDIR})` writes the baseline `.checksums.md5` ([pipeline.py:278-286](../../pinball_decryptor/plugins/cgc/pipeline.py#L278), `CHECKSUMS_FILE = ".checksums.md5"` [checksums.py:11](../../pinball_decryptor/core/checksums.py#L11)). The `dmd/` subtree is excluded so it isn't later diffed as "new files" and uselessly written into the inner partition. The done message tells the user to modify audio/ROM/logo and use the Write tab.

### Output layout

```
<output_dir>/
  ...mirror of the asset subtree (/home/debian/emumm or /home/ubuntu/pin)...
  # Pulp Fiction only:
  data/pfsndui.bnk
  data/pfsndui/
      pfsndui_sound_000.wav ... pfsndui_sound_NNN.wav
      pfsndui.manifest.json
  data/pfsndfx.bnk
  data/pfsndfx/ ...
  # WPC remakes with decode_dmd on:
  dmd/
      dmd_scenes/scene_*.png
      animations/anim_*.mp4
      fonts/font_*.png
  callouts.csv          # only if the Auto-transcribe step ran
  .checksums.md5        # baseline (excludes dmd/)
```

## Write / repack pipeline

`WritePipeline._run` ([pipeline.py:454-591](../../pinball_decryptor/plugins/cgc/pipeline.py#L454)), 4 phases. It never rebuilds the `.img` from scratch — it copies the original and patches bytes inside the nested ext4 partitions in place.

### Phase 0 — Detect & diff
Detect the game, load the baseline `.checksums.md5` (`read_checksums`), and diff the assets dir against it via `_diff_assets` ([pipeline.py:455-489](../../pinball_decryptor/plugins/cgc/pipeline.py#L455), [pipeline.py:664-748](../../pinball_decryptor/plugins/cgc/pipeline.py#L664)). If nothing changed, Write still proceeds to produce a byte-for-byte copy (a useful smoke test).

`_diff_assets` is where the **JPS repack pre-step** runs: `_repack_modified_jps_bnks(assets_dir)` ([pipeline.py:751-806](../../pinball_decryptor/plugins/cgc/pipeline.py#L751)) finds every `<X>.bnk` that has a sibling decoded `<X>/` subdir and, if any WAV inside differs from what the bank currently encodes, repacks the `.bnk` in place via `repack_bnk`. It returns the set of all files under those subdirs so the diff loop can exclude them — the decoded WAVs and `manifest.json` are decode artifacts, never eMMC payloads. Repack is run unconditionally (a no-op repack copies original bytes verbatim) and any exception leaves the original `.bnk` untouched.

<a id="cactus-canyon-repack"></a>Right after the JPS pre-step, `_diff_assets` runs the **Cactus Canyon repack pre-step**: `_repack_modified_cc_assets(assets_dir)` re-encodes any edited decoded surface back into its source eMMC blob, in place, so the md5 diff then flags the blob as changed (and the existing debugfs `write` ships it). Like the JPS step it's no-op-safe (an unedited set reproduces the original bytes / writes nothing) and failure-isolated per surface. Three independent repackers: `dcs_audio/` streams → `ccdata/rom/s2..s7.rom` via `cc_dcs.repack` (re-decodes the ROMs to diff which streams changed, then `DCSEncoder --patch` with `Stream … replaces $ADDR;`); `new_audio/` WAVs → `ccdata/usb.so` via `cc_usb_audio.repack_usb` (splice PCM trimmed/padded to the record length, then `_dcs_encrypt`); `display_art/` PNGs → `ccdata/cgc.so` via `cc_art.repack_art` (changed-in-RGBA-space PNGs re-encoded to RGB565 into the `newimg` member, `cgc_reobfuscate`, header CRC32 fixed). Editing one DCS stream rewrites the whole `s*.rom` set (DCSEncoder rebuilds it). Verified end-to-end: extract → edit one of each → Write → re-extract reproduces every edit, untouched assets byte-identical *(software round-trip; not yet verified on hardware)*.

`_diff_assets` also does **rename-aware matching** ([pipeline.py:664-748](../../pinball_decryptor/plugins/cgc/pipeline.py#L664), `_find_renamed_sibling` [pipeline.py:809-831](../../pinball_decryptor/plugins/cgc/pipeline.py#L809)): a baseline file gone from disk gets a second-chance lookup for a `<stem> - *.<ext>` sibling (the convention `TranscribePipeline`'s rename step emits, e.g. `S0216_C6 - Joust Champion!.wav`). A unique match that differs from the baseline md5 is written back to the **original** inner-ext4 path (so the game engine, which looks up samples by original name, picks up the edit). Brand-new files are also captured, except plugin metadata: `.checksums.md5`, `callouts.csv`, dot-files, the `dmd/` subtree (pruned at the top of `os.walk`), and the JPS decoded-subdir files.

### Phase 1 — Copy original
Copy the original `.img` to the output path in 64 MiB chunks with progress (`_copy_with_progress`, [pipeline.py:920-933](../../pinball_decryptor/plugins/cgc/pipeline.py#L920)); patching happens against the copy. With no changes, it short-circuits to phase 3 and reports "no modifications" ([pipeline.py:507-513](../../pinball_decryptor/plugins/cgc/pipeline.py#L507)).

### Phase 2 — Stage partitions
Re-extract P3 → `p3.img`, dump `emmc.img`, read its inner MBR, `dd` P2 → `inner.img` — same chain as Extract phases 1-2 ([pipeline.py:516-547](../../pinball_decryptor/plugins/cgc/pipeline.py#L516)).

### Phase 3 — Patch (the reverse chain)
([pipeline.py:549-591](../../pinball_decryptor/plugins/cgc/pipeline.py#L549))

1. **Write modified files into the inner ext4** (`_write_modified_files`, [pipeline.py:593-634](../../pinball_decryptor/plugins/cgc/pipeline.py#L593)): for each changed file, the inner path is `<asset_subtree>/<rel>`. It runs a best-effort `debugfs -w -R 'rm <inner>'` then a must-succeed `debugfs -w -R 'write <src> <inner>'`. `rm` and `write` are separate `-R` invocations because debugfs's `-R` takes exactly one command and treats `;` as a literal. Paths are quoted with `_quote_dbg`, which rejects embedded `"`, backtick, or `$` ([pipeline.py:866-875](../../pinball_decryptor/plugins/cgc/pipeline.py#L866)).
2. **Re-pack inner P2 → emmc.img:** `dd ... seek=<p2_start> conv=notrunc` writes `inner.img` back into the `emmc.img` at the original partition offset.
3. **Re-pack emmc.img → P3:** `debugfs -w -R 'rm /emmc.img'` (`|| true`) then `debugfs -w -R 'write emmc.img /emmc.img'` rewrites the inner image file inside P3's ext4.
4. **Re-pack P3 → output .img:** `dd ... seek=<p3_start> conv=notrunc` writes `p3.img` back into the output image at P3's offset.

Staging is cleaned up in `finally`. The done message instructs flashing to USB with Rufus/Etcher/`dd` and the on-machine installer flow (`write_install_help`, [manufacturer.py:119-127](../../pinball_decryptor/plugins/cgc/manufacturer.py#L119)).

### JPS `repack_bnk` internals
`repack_bnk(original_bnk, modified_wavs_dir, output_bnk)` ([jps_bnk.py:376-477](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L376)):

- Parse the original bank, then preserve every byte up to the first buffer (header, ID table, command chunks, per-buffer header table) verbatim ([jps_bnk.py:416-419](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L416)).
- For each buffer in order: preserve the inter-buffer 4-byte gap, then either copy the original compressed payload verbatim or splice in a re-encoded one. A buffer is treated as modified only if its WAV's PCM **differs** from what the original decompresses to (`_wav_pcm_differs_from_buffer`, [jps_bnk.py:499-516](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L499)) — important because re-zlib of identical PCM does **not** reproduce JPS's exact compressed bytes, so unconditional re-encoding would falsely flag every buffer as changed.
- Re-encoding (`_encode_buffer_payload`, [jps_bnk.py:519-561](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L519)): for `zlib` buffers, read the WAV's PCM, glue the **original** 44-byte JPS header on the front (preserving `hash1`/`hash2`), then `zlib.compress(..., level=6)`. For `riff` buffers, write the user's WAV bytes verbatim. A sample-rate/channels/width mismatch raises `ValueError` ([jps_bnk.py:543-550](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L543)).
- **Variable-size splice:** because a re-zlib'd buffer's compressed size can differ from the original, subsequent buffers naturally shift (the new payload is appended at its true new length, and the next buffer's gap+payload follow). Overlap (a buffer starting before the previous one ended) raises. Trailing bytes after the last buffer are preserved ([jps_bnk.py:421-468](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L421)). Returns a summary dict (`buffers`, `modified_count`, `total_count`, sizes) used by callers/tests.

### Output naming
Write produces a single patched installer `.img` at the user's chosen output path (a flashable disk image). Per-bank repacks happen in place inside the assets dir (`<X>.bnk.repack_tmp` → atomic `os.replace`, [pipeline.py:779-805](../../pinball_decryptor/plugins/cgc/pipeline.py#L779)).

## Audio assets

CGC machines render all video in real time, so audio is the primary moddable surface (`extract_input_help`, [manufacturer.py:98-117](../../pinball_decryptor/plugins/cgc/manufacturer.py#L98)). Two shapes:

- **WPC remakes (MM/AFM/MB) — loose `.wav`.** The 1300+ DCS samples are already extracted to 48 kHz mono WAV under `<gamedata>/wav48000/<GAME>_*.wav` ([games.py:28-30](../../pinball_decryptor/plugins/cgc/games.py#L28)). These appear directly in the extract tree; editing one and running Write sends the new bytes straight back into the inner ext4 (md5-diff against baseline).
- **Pulp Fiction — JPS `.bnk` banks → decoded WAVs.** Each bank is exploded to `<bnk>/<bnk>_sound_NNN.wav` + `<bnk>.manifest.json` ([jps_bnk.py:286-369](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L286)). The manifest (`format: "jps_bnk_v1"`) records per-buffer storage/params/duration/sizes/offset/hash and per-event `plays_buffer` mappings so a modder can tell *which* WAV is "the witch laugh." `extract_bnk` writes a real WAV for `zlib` buffers (decompress, strip the 44-byte header, write PCM) and copies the embedded RIFF bytes verbatim for `riff` buffers.

### Replace-Audio applicability
`replace_audio=True` with no `audio_slot_dirs` override → the Replace-Audio tab scans the **whole extract** for loose `.wav`/`.ogg`. For the remakes this surfaces `wav48000/*.wav`; for Pulp Fiction it surfaces the decoded `<bnk>/*.wav`. The `dmd/` render is excluded as a practical matter because it contains no audio files ([manufacturer.py:30-36](../../pinball_decryptor/plugins/cgc/manufacturer.py#L30)). When the user replaces a PF bank WAV, the Write pre-step `_repack_modified_jps_bnks` re-encodes it back into the `.bnk` before the diff runs.

### Transcribe (faster-whisper)
Because samples are named by index with no embedded text, `TranscribePipeline` ([transcribe.py:42-211](../../pinball_decryptor/core/transcribe.py#L42)) runs `tiny.en` int8 on CPU across every WAV with Silero VAD enabled (`vad_filter=True`), emitting `callouts.csv` (`relative_path, classification, text`) at the assets-dir root; non-speech samples are logged `[no speech]`. The optional rename step renames speech WAVs to `<stem> - <transcript>.<ext>` (sanitized, capped at 80 chars), which the Write rename-aware diff later maps back to the original inner path. The plugin wires this in unchanged (`make_transcribe_pipeline`, [manufacturer.py:91-96](../../pinball_decryptor/plugins/cgc/manufacturer.py#L91)).

## DMD / video

CGC ships **no** video files — all video is rendered in real time on the machine (real-time LCD render for the remakes via `emumm`, SDL/OpenGL ES for Pulp Fiction). There is therefore nothing to mod for video.

The remakes do bundle the original Williams WPC ROM, and the optional **decode_dmd** step decodes that ROM (extract-only) using the Williams plugin's `wpc_extract.extract_dmd_assets` ([pipeline.py:367-374](../../pinball_decryptor/plugins/cgc/pipeline.py#L367)). The ROM bytes are identical to the Williams original, so the same decoder produces:

- `dmd/dmd_scenes/scene_*.png` — every still bitmap (jackpot splashes, mode-start, status panels)
- `dmd/animations/anim_*.mp4` — game cinematics
- `dmd/fonts/font_*.png` — DMD glyph atlases

Rendered at `pixel_size=15` (`CGC_DMD_PIXEL_SIZE`, [pipeline.py:47](../../pinball_decryptor/plugins/cgc/pipeline.py#L47)), so each 128×32 DMD becomes a 1920×480 PNG matching the LCD backbox width. The output is **monochrome amber** — CGC's runtime LCD colorization is GPU code in `emumm`, *not* shipped as data, so it isn't applied here ([pipeline.py:38-47](../../pinball_decryptor/plugins/cgc/pipeline.py#L38)).

**Why it's not written back:** the renders are derived from the ROM and don't correspond to any path inside the inner ext4. They're excluded from the baseline checksums (`exclude_dirs={DMD_SUBDIR}`) and pruned at the top of the Write diff's `os.walk`, so they're never diffed or written into the partition ([pipeline.py:282-286](../../pinball_decryptor/plugins/cgc/pipeline.py#L282), [pipeline.py:734-736](../../pinball_decryptor/plugins/cgc/pipeline.py#L734)). The step is default-OFF because the render is slow (a few minutes). The in-game machine renders the DMD live from the ROM — there is no `.mp4` in-game.

## Mod Pack / delta / direct-SSD

- **Mod Pack** — `modpack=True`. This is the generic core "package only the changed files" feature, keyed off the baseline `.checksums.md5` the Extract step writes; the CGC plugin enables the capability but adds no plugin-specific mod-pack code (no override in `manufacturer.py`).
- **Apply-delta** — `apply_delta=False`. N/A (no `apply_delta` implementation).
- **Chain-deltas** — `chain_deltas` defaults `False`. N/A.
- **Direct-SSD** — `direct_ssd` defaults `False`. N/A — CGC works only against installer `.img` files, not a physically-connected game drive.

## Detection

`detect()` ([manufacturer.py:69-75](../../pinball_decryptor/plugins/cgc/manufacturer.py#L69)) delegates to `detect_game(path)` ([formats.py:33-42](../../pinball_decryptor/plugins/cgc/formats.py#L33)):

1. `is_img_file` — the path is a regular file, ends in `.img`, and has a valid `55 AA` MBR signature at offset 510 ([formats.py:19-30](../../pinball_decryptor/plugins/cgc/formats.py#L19)).
2. Lowercase the basename and match against each game's `filename_hints` (case-insensitive substring): `medievalmadness/mm_remake/mmremake`, `attackfrommars/afm_remake/afmremake`, `monsterbash/mb_remake/mbremake`, `pulpfiction`, `cactuscanyon/cactus_canyon/cc113/cc_113/ccrevisited/cactus` ([games.py:60-86](../../pinball_decryptor/plugins/cgc/games.py#L60)). Cactus Canyon has no factory installer-filename convention (it ships on a physical card), so the user names the imaged `.img` to contain the title.

Detection is **filename-based on purpose**: reading P3 to peek at the `package.dat` version string takes ~20 s per probe (a 3 GB `dd`), and the picker pings every plugin on every browse — unacceptable latency. CGC's images have always shipped as `<Game><version>Installer.img` (e.g. `MedievalMadness300Installer.img`), so the hints are reliable ([formats.py:1-9](../../pinball_decryptor/plugins/cgc/formats.py#L1), [games.py:49-53](../../pinball_decryptor/plugins/cgc/games.py#L49)). In the registry, `cgc` sits between `jjp` and `williams` ([registry.py:27-29](../../pinball_decryptor/core/registry.py#L27)); its detector is strict (signature + filename) so ordering isn't sensitive.

## Gotchas & non-obvious details

- **MSVC debug-fill garbage in `.bnk`.** CGC's build tool didn't zero its buffers before serializing, so banks are riddled with `0xCC` (uninitialized stack) and `0xCD` (uninitialized heap) fill interspersed with real fields. This is *not* encryption — but it means a field that "looks meaningful" might be garbage; cross-bank comparison is the only reliable defense ([CGC_BNK_RE.md:27-31](../CGC_BNK_RE.md#L27), [CGC_BNK_RE.md:189-194](../CGC_BNK_RE.md#L189)).
- **`hash1`/`hash2` are preserved, not computed.** Their algorithm is unknown (not CRC32/Adler32/xxHash of the PCM). Repack copies the original 44-byte header so the bytes match what the engine expects — but whether the engine validates them on load is **still unconfirmed on real hardware** *(unverified)* ([jps_bnk.py:385-398](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L385), [CGC_BNK_RE.md:455-463](../CGC_BNK_RE.md#L455)).
- **Same-format audio constraint.** A replacement WAV for a `zlib` buffer must match the original's 48 kHz / stereo / 16-bit params or `repack_bnk` raises `ValueError` — there is no transcode step (would need ffmpeg) ([jps_bnk.py:543-550](../../pinball_decryptor/plugins/cgc/jps_bnk.py#L543), [CGC_BNK_RE.md:470-472](../CGC_BNK_RE.md#L470)). The test `test_repack_rejects_mismatched_audio_format` covers this ([test_cgc_jps_bnk.py:205-222](../../tests/test_cgc_jps_bnk.py#L205)).
- **Re-zlib isn't byte-identical to JPS's compiler.** Hence the PCM-diff gate: only buffers whose decoded PCM actually changed are re-encoded; everything else is copied verbatim, so a no-op repack is byte-identical to the original (`test_repack_no_changes_is_byte_identical`, [test_cgc_jps_bnk.py:145-159](../../tests/test_cgc_jps_bnk.py#L145)).
- **Nested-image tooling / elevation.** All ext4 work runs in the executor (WSL on Windows, native on Linux, Docker on macOS). `debugfs` returns exit 0 even on failed `rdump`/`write`, so the pipeline verifies file counts independently. debugfs `-R` takes exactly one command (`;` is literal), forcing separate `rm`/`write` invocations, and its mini-parser mishandles paths with spaces (hence the no-space `/tmp` staging + Python copy) ([pipeline.py:208-236](../../pinball_decryptor/plugins/cgc/pipeline.py#L208), [pipeline.py:608-619](../../pinball_decryptor/plugins/cgc/pipeline.py#L608)).
- **`find_data_partition` quirk.** The data partition (P3) is selected by **highest LBA**, not largest size — on MM/AFM/MB the installer rootfs P2 is *larger* than the data partition, so "largest ext4" picks wrong ([formats.py:82-97](../../pinball_decryptor/plugins/cgc/formats.py#L82)).
- **decode_dmd is slow and not writable.** Off by default; output is extract-only and excluded from checksums + Write diff so it never gets written into the eMMC ([pipeline.py:90-92](../../pinball_decryptor/plugins/cgc/pipeline.py#L90), [registry.py:90-96](../../pinball_decryptor/core/registry.py#L90)).
- **Machine-level verification still open.** The software round-trip (extract → edit → repack → re-extract → byte-match) passes, but a real Pulp Fiction machine still needs to confirm the repacked `.bnk` boots and plays the modified audio (esp. if `hash1`/`hash2` turn out to be validated) *(unverified)* ([CGC_BNK_RE.md:455-463](../CGC_BNK_RE.md#L455)). Repack is also only exercised on the smallest bank (`pfsndui`) in practice; the RIFF-storage music bank and the large 465-buffer banks should work but haven't been round-tripped on hardware *(unverified)* ([CGC_BNK_RE.md:465-468](../CGC_BNK_RE.md#L465)).

## Key files

- [`__init__.py`](../../pinball_decryptor/plugins/cgc/__init__.py) — plugin entry point; `register()` registers `CGCManufacturer`.
- [`manufacturer.py`](../../pinball_decryptor/plugins/cgc/manufacturer.py) — the `Manufacturer` subclass: key/display/games, `Capabilities`, `InputSpec`, phase labels, prerequisites, `detect()`, pipeline factories, help text.
- [`games.py`](../../pinball_decryptor/plugins/cgc/games.py) — `GAME_DB`: per-title display, filename hints, platform, `asset_subtree`, `data_dir`; documents the three-layer image layout.
- [`formats.py`](../../pinball_decryptor/plugins/cgc/formats.py) — `.img` detection (`is_img_file`, `detect_game`) and MBR partition parsing (`read_mbr_partitions`, `find_data_partition`, `find_game_partition`).
- [`pipeline.py`](../../pinball_decryptor/plugins/cgc/pipeline.py) — `ExtractPipeline` + `WritePipeline`, the nested dd/debugfs chain, `_explode_jps_banks`, `_extract_dmd_assets`, `_diff_assets`, `_repack_modified_jps_bnks`, `_write_modified_files`, and helpers.
- [`jps_bnk.py`](../../pinball_decryptor/plugins/cgc/jps_bnk.py) — JPS `.bnk` parser (`parse_bnk`), extractor (`extract_bnk`), and repacker (`repack_bnk`); format constants and `SoundBuffer`/`Event`/`BnkContents` dataclasses.
- [`core/registry.py`](../../pinball_decryptor/core/registry.py) — base `Manufacturer` contract, `Capabilities`, `Game`, `InputSpec`, plugin registration/detection.
- [`core/transcribe.py`](../../pinball_decryptor/core/transcribe.py) — shared `TranscribePipeline` (faster-whisper `tiny.en` + VAD → `callouts.csv`, optional rename).
- [`plugins/williams/wpc_extract.py`](../../pinball_decryptor/plugins/williams/wpc_extract.py) — the WPC-ROM DMD decoder reused by `_extract_dmd_assets` (`extract_dmd_assets`, `WpcDecodeError`).
- [`tests/test_cgc_jps_bnk.py`](../../tests/test_cgc_jps_bnk.py) — synthetic-bnk round-trip tests for extract / no-op repack / edited repack / format-mismatch rejection.

## Related docs

- **[docs/CGC_BNK_RE.md](../CGC_BNK_RE.md)** — the full JPS `.bnk` reverse-engineering journal (sessions 1-4): header/ID-table/event-chunk/per-buffer layout, the zlib-vs-RIFF storage discovery, the `hash1`/`hash2` open question, and the repack round-trip verification status.
