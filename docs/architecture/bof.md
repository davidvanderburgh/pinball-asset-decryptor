# Barrels of Fun (`bof`) — Architecture

> Barrels of Fun ships its games as Godot Engine 4.5 titles whose assets live in a PCK embedded inside a GPG-symmetric-encrypted `.fun` update file. The plugin decrypts the `.fun`, extracts the embedded Godot binary's PCK, and converts the imported asset binaries (`.sample`/`.oggvorbisstr`/`.ctex`/`.fontdata`) into editable `.wav`/`.ogg`/`.webp`/`.ogv`/`.ttf` files under `pck/_EDITABLE ASSETS/`. Write inverse-converts edits back into the imported binaries, repacks the PCK, re-encrypts to `.fun`, and stamps a climbing version date so the machine accepts the build. Two PCK code paths exist: a pre-May-2026 path that drives GDRE Tools, and a native May-2026+ path (`may_extractor`/`may_packer`) that handles BoF's custom RSCC + Zstd anti-modding format which GDRE cannot read.

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/bof/`
- **Key:** `bof`  ([manufacturer.py:79](../../pinball_decryptor/plugins/bof/manufacturer.py#L79))
- **Display:** `Barrels of Fun`  ([manufacturer.py:80](../../pinball_decryptor/plugins/bof/manufacturer.py#L80))

### Supported games

The game DB ([games.py:3](../../pinball_decryptor/plugins/bof/games.py#L3)) defines exactly three games. All are marked supported (the `Game` objects are built without `supported=False` — [manufacturer.py:16](../../pinball_decryptor/plugins/bof/manufacturer.py#L16)). Detection is filename-based, so support is effectively per-`.fun`-filename.

| key | display | `.fun` file | passphrase | supported? | notes |
|-----|---------|-------------|------------|------------|-------|
| `labyrinth` | Jim Henson's Labyrinth | `lab.fun` | `funkey` | yes | Arch Linux / FAST hardware / Godot 4.5 custom build |
| `dune` | Dune | `dune.fun` | `dunekey` | yes | The reverse-engineering reference build; May-2026 custom PCK format |
| `winchester` | Winchester Mystery House | `winchester.fun` | `winchesterkey` | yes | April-2026 variant: stock `GDPC` magic but BoF custom inline-sidecar layout |

There is no Dune/Winchester/Labyrinth "unsupported" entry — all three are present and supported. The extract-help text names "Labyrinth, Dune, Winchester" explicitly ([manufacturer.py:170](../../pinball_decryptor/plugins/bof/manufacturer.py#L170)). (Note: the per-game `passphrase` is a static, hardcoded GPG symmetric passphrase, not a public/private key — see Container & format.)

### Input extensions / InputSpec

- **InputSpec:** label `"Barrels of Fun game files"`, extensions `(".fun",)`  ([manufacturer.py:94](../../pinball_decryptor/plugins/bof/manufacturer.py#L94))

### Capabilities

Declared at [manufacturer.py:82](../../pinball_decryptor/plugins/bof/manufacturer.py#L82):

| flag | value | meaning |
|------|-------|---------|
| `extract` | True | Decrypt `.fun` → extract PCK → editable assets |
| `write` | True | Edit-back → repack PCK → re-encrypt `.fun` |
| `modpack` | True | Export/import a zip of only files changed vs the `.checksums.md5` baseline ([pipeline.py:318](../../pinball_decryptor/plugins/bof/pipeline.py#L318), [pipeline.py:360](../../pinball_decryptor/plugins/bof/pipeline.py#L360)) |
| `apply_delta` | False | — |
| `iso` | False | — |
| `write_version_date` | True | Surfaces the Write-tab "Update version date" control (Auto checkbox + editable `YYYY.MM.DD`). The game only applies a `.fun` whose embedded date is *newer* than what's installed; the field shows the date Write will stamp and lets the user override it (e.g. force official code over a higher-dated mod). app.py passes `version_date_override` (None in Auto mode) to `make_write_pipeline` (capability doc: [registry.py:80](../../pinball_decryptor/core/registry.py#L80)) |
| `replace_audio` | True | Replace-Audio tab. BoF audio is imported Godot binaries; Extract writes editable `.wav`/`.ogg` under `pck/_EDITABLE ASSETS/` and `audio_slot_dirs()` restricts the scan to those folders ([manufacturer.py:144](../../pinball_decryptor/plugins/bof/manufacturer.py#L144)) |

Unset/default-False capabilities: `capture`, `transcribe`, `direct_ssd`, `asset_filters`, `decode_dmd`, `chain_deltas`.

### Prerequisites

Probed on a worker thread when the user picks BoF; rendered as `[✓]/[✗]` badges. All run "where=wsl" (WSL on Windows; the same bash commands run natively via `MacExecutor`/`NativeExecutor` on macOS/Linux). Declared at [manufacturer.py:108](../../pinball_decryptor/plugins/bof/manufacturer.py#L108):

| tool | probe | why |
|------|-------|-----|
| `gpg` | `which gpg` | `.fun` GPG decryption + re-encryption |
| `tar` | `which tar` | tar.gz pack/unpack of the `.fun` payload |
| `gdre_tools` | `test -x /opt/gdre_tools/gdre_tools.x86_64` | Godot RE Tools — required to repack the PCK on Write for **pre-May** binaries; also used for the pre-May extract path and `.gd` script recompilation. (Probe checks the canonical install path directly because the old `which` probe traversed the slow appended Windows PATH and failed intermittently.) |
| `xvfb-run` | `which xvfb-run` | Headless X server GDRE needs on Linux/WSL |

A second prereq list in `check_prerequisites()` ([pipeline.py:228](../../pinball_decryptor/plugins/bof/pipeline.py#L228)) additionally probes `cwebp` (optional, for `.png`/`.jpg` → `.ctex` texture reimport in the **pre-May** Write path). The May-format native paths (extract/pack) and the pure-Python audio conversions need none of GDRE/xvfb/cwebp — only `zstandard` (a Python package, lazily imported by `rscc_decoder`/`may_packer`).

### Phase labels

- **Extract (5):** `Detect`, `Decrypt`, `Extract`, `Checksums`, `Cleanup`  ([manufacturer.py:101](../../pinball_decryptor/plugins/bof/manufacturer.py#L101))
- **Write (5):** `Decrypt`, `Patch`, `Repack`, `Encrypt`, `Cleanup`  ([manufacturer.py:102](../../pinball_decryptor/plugins/bof/manufacturer.py#L102))

The base `Manufacturer` default is 4 phases; BoF overrides both to 5 because the upstream `DecryptPipeline`/`ModifyPipeline` call `phase_cb(0..4)` ([registry.py:144](../../pinball_decryptor/core/registry.py#L144) note).

## Container & format

### The `.fun` (GPG) → tar.gz → Godot binary chain

A `.fun` file is a **GPG symmetric-encrypted (AES256) gzip tarball**. Decryption uses a per-game static passphrase ([games.py:3](../../pinball_decryptor/plugins/bof/games.py#L3)) via `gpg --batch --yes --passphrase=… --decrypt` ([pipeline.py:464](../../pinball_decryptor/plugins/bof/pipeline.py#L464)). Re-encryption uses `gpg --batch --yes --passphrase=… --symmetric --cipher-algo AES256` ([pipeline.py:1859](../../pinball_decryptor/plugins/bof/pipeline.py#L1859)). The decrypted tar.gz, when extracted, contains (among other files):

- A Godot export binary `*.x86_64` (the game executable with an **embedded PCK** appended) — located via `find … -name '*.x86_64'` ([pipeline.py:537](../../pinball_decryptor/plugins/bof/pipeline.py#L537)).
- An `md5` file (a `md5sum` of the binary) which Write regenerates ([pipeline.py:1795](../../pinball_decryptor/plugins/bof/pipeline.py#L1795)).
- Update-gate scripts `updated_bash_profile` and `updated_updatecode` ([pipeline.py:781](../../pinball_decryptor/plugins/bof/pipeline.py#L781)).

### The Godot embedded-PCK structure

The PCK is appended to the end of the binary. The **last 12 bytes** are the trailer: `<u64 LE pck_data_size><4-byte magic>` ([may_extractor.py:81](../../pinball_decryptor/plugins/bof/may_extractor.py#L81), constants [may_extractor.py:64](../../pinball_decryptor/plugins/bof/may_extractor.py#L64)). The PCK section therefore spans `[size-12-pck_data_size, size-12)`. The PCK header is 96 bytes (`4 magic + 4 ver + 12 engine + 4 flags + 8 file_base + 64 reserved`) followed by 8 zero pad bytes ([may_extractor.py:66](../../pinball_decryptor/plugins/bof/may_extractor.py#L66)).

### PCK magic: GDPC vs GBOF

Stock Godot uses magic `GDPC`. **BoF's May-2026+ builds rename it to `GBOF`** at both the header and trailer offsets to defeat off-the-shelf tools ([pipeline.py:23](../../pinball_decryptor/plugins/bof/pipeline.py#L23)). `_patch_pck_magic()` ([pipeline.py:62](../../pinball_decryptor/plugins/bof/pipeline.py#L62)) swaps the 4-byte magic in place via an inline base64'd python3 script ([pipeline.py:37](../../pinball_decryptor/plugins/bof/pipeline.py#L37)):

- It reads the trailer to find `pck_size`, computes `header_off = size - 12 - pck_size`, validates both the header and trailer magic match `from_magic`, then writes `to_magic` at both. No-ops cleanly if already patched, magic absent, or file too small (verified by [test_bof_pck_magic.py](../../tests/test_bof_pck_magic.py)).
- **Extract** patches `GBOF → GDPC` on the output binary so GDRE / Godot tooling can read it ([pipeline.py:553](../../pinball_decryptor/plugins/bof/pipeline.py#L553)).
- **Write** (pre-May path only) patches `GBOF → GDPC` on the in-flight temp binary before GDRE, then restores `GDPC → GBOF` on the output so the real machine still finds its PCK ([pipeline.py:1704](../../pinball_decryptor/plugins/bof/pipeline.py#L1704), [pipeline.py:1788](../../pinball_decryptor/plugins/bof/pipeline.py#L1788)). The round-trip is byte-exact (verified by `test_patch_round_trip`).

### The May-2026 custom anti-modding format (4 layers)

Confirmed empirically against the Dune May build `GDHarvest_202600513.x86_64` (2.74 GB, 4703 path refs, 2481 sidecar entries) ([may_extractor.py:1](../../pinball_decryptor/plugins/bof/may_extractor.py#L1)). The four layers:

1. **Magic rename** `GDPC → GBOF` (Layer 1; patched back by `_patch_pck_magic` before extraction).
2. **`PACK_DIR_ENCRYPTED` flag bit set** as a tripwire — *no actual AES*; the directory is not encrypted, the flag is purely to make tools refuse the PCK.
3. **No traditional Godot file-directory table.** Files are stored **sequentially**, each `.import` sidecar stored inline. Addressing is by walking forward, not by an offset table.
4. **Fonts wrapped in a custom `RSCC` Zstd container** ([rscc_decoder.py](../../pinball_decryptor/plugins/bof/rscc_decoder.py)). Other files (textures, audio, scripts, scenes) are stored as raw bytes.

**Two sidecar flavours** drive extraction ([may_extractor.py:20](../../pinball_decryptor/plugins/bof/may_extractor.py#L20)):

- **Adjacent (imported) sidecars** contain `importer="…"` + `type=…` + `uid=…` + `path="res://.godot/imported/…"`. File data lives **immediately before** the sidecar, optionally separated by an 8-byte `RSCC\x00\x00\x00\x00` separator. Covers `.ctex`, `.sample`, `.fontdata`, `.oggvorbisstr` (~1781 files in Dune).
- **Simple sidecars** contain only `path="res://…"` (no `importer=`). File data is **not** adjacent — it lives in a separate contiguous block earlier in the PCK, paired sequentially by file type/magic. Covers `.gdc` (compiled scripts), `.scn` (binary scenes), `.res` (binary resources) (~700 files).

The **Winchester (April-2026)** variant uses the same custom inline-sidecar layout and RSCC containers but keeps stock `GDPC` magic and does *not* set the encrypted-flag tripwire (no anti-tooling obfuscation, just the format itself) ([may_extractor.py:102](../../pinball_decryptor/plugins/bof/may_extractor.py#L102)).

**Format detection** — `is_may_format(pck_buf)` ([may_extractor.py:102](../../pinball_decryptor/plugins/bof/may_extractor.py#L102)): accepts `GDPC` or `GBOF` magic; requires the u32 at offset 96 (where stock Godot has a positive `file_count`) to be 0; then walks past zero padding from offset 96 and checks the first non-zero region begins with a known imported magic — `RSCC` (tightened to v2: bytes `02 00 00 00` follow) or one of `GST2`/`RIFF`/`OggS`/`RSRC`. This single-byte discriminator distinguishes BoF's no-directory layout from stock Godot's file-count directory.

### RSCC container layout

`RSCC` is a block-Zstd container ([rscc_decoder.py:19](../../pinball_decryptor/plugins/bof/rscc_decoder.py#L19)):

```
offset   size    field
0        4       magic "RSCC"
4        4       version (always 2 observed)
8        4       uncompressed block size (always 4096 observed)
12       4       total uncompressed size
16       4*N     per-block compressed sizes (N = ceil(total/blk))
16+4*N   …       N back-to-back Zstd frames
```

`is_rscc_at()` filters the ~50 incidental `RSCC` byte matches inside high-entropy Zstd data by also checking `version==2 && blk_size==4096` ([rscc_decoder.py:50](../../pinball_decryptor/plugins/bof/rscc_decoder.py#L50)). `decompress()` decodes each block to a max of `block_size+1024` and validates the total against the header ([rscc_decoder.py:102](../../pinball_decryptor/plugins/bof/rscc_decoder.py#L102)). `zstandard` is a lazily-imported optional dependency. Decompressing yields a standard Godot binary resource (e.g. a `FontFile`); BoF **strips the leading `RSRC` magic** before compressing, restored on extract ([may_extractor.py:242](../../pinball_decryptor/plugins/bof/may_extractor.py#L242)). Round-trip and spurious-match filtering verified by [test_bof_rscc.py](../../tests/test_bof_rscc.py).

### Imported-binary formats

| imported ext | Godot resource class | container | decodes to |
|--------------|----------------------|-----------|------------|
| `.sample` | `AudioStreamWAV` | `RSRC` binary; `data` PBA holds raw PCM, **QOA** (`qoaf`), or OGG (`OggS`) | `.wav` (or `.qoa` if decoder unavailable, `.ogg` passthrough) |
| `.oggvorbisstr` | `AudioStreamOggVorbis` | `RSRC` binary wrapping an `OggPacketSequence` sub-resource (vorbis packets + granules + sample rate) | `.ogg` |
| `.ctex` | `CompressedTexture2D` | `GST2` header wrapping RIFF/WebP or PNG; or raw `OggS` Theora video | `.webp` / `.png` / `.ogv` |
| `.fontdata` | `FontFile` | `RSCC`-Zstd `RSRC` binary; font in a `data` PBA | `.ttf` / `.otf` |

### QOA codec

`qoa_codec.py` is a pure-Python implementation of QOA (Quite-OK Audio), a ~3.2:1 lossy 16-bit PCM codec; BoF stores ~70% of Dune's audio as QOA inside the `.sample` `data` PBA ([qoa_codec.py:1](../../pinball_decryptor/plugins/bof/qoa_codec.py#L1)). Layout (big-endian): `qoaf` magic + `total_samples` u32 + frames; each frame carries `channels` u8, `samplerate` u24, `samples_per_chan` u16, `frame_size` u16, then per-channel 16-byte LMS state (4 history + 4 weights, s16 BE) and `ceil(spc/20)` 8-byte slices (4-bit scalefactor + 20× 3-bit residuals). `decode()` ([qoa_codec.py:80](../../pinball_decryptor/plugins/bof/qoa_codec.py#L80)) and `encode()` ([qoa_codec.py:238](../../pinball_decryptor/plugins/bof/qoa_codec.py#L238)) use the reference `_SF_TAB` / `_DEQUANT` tables and LMS predictor (`pred = Σ h·w >> 13`, weights updated by `dequant>>4 · sign(history)`). Round-trips are acoustically clean (<100 LSB mean error on a sine, verified by [test_bof_qoa_codec.py](../../tests/test_bof_qoa_codec.py)).

## Extract pipeline

`DecryptPipeline._run()` ([pipeline.py:430](../../pinball_decryptor/plugins/bof/pipeline.py#L430)), wrapped to the unified factory signature by `_ExtractWrapper` (always `unpack_pck=True`, [manufacturer.py:23](../../pinball_decryptor/plugins/bof/manufacturer.py#L23)).

**Phase 0 — Detect** ([pipeline.py:431](../../pinball_decryptor/plugins/bof/pipeline.py#L431)): `detect_game()` maps the lowercased basename to a game key via `FUN_FILE_TO_GAME`; unknown filenames raise. Verifies the output dir is accessible from the executor (`check_path_accessible`, important on WSL where unmounted drives fail).

**Phase 1 — Decrypt** ([pipeline.py:455](../../pinball_decryptor/plugins/bof/pipeline.py#L455)): `gpg --decrypt` the `.fun` to `/tmp/bof_<game>.tar.gz`. Progress is polled by watching the temp file's size grow against the `.fun` size (`_poll_file_progress`, [pipeline.py:148](../../pinball_decryptor/plugins/bof/pipeline.py#L148)).

**Phase 2 — Extract** ([pipeline.py:476](../../pinball_decryptor/plugins/bof/pipeline.py#L476)): `tar -xzf` to `/tmp/bof_<game>_extracted`, `cp -r` into the output dir, locate the `*.x86_64` binary, then patch `GBOF → GDPC` on the local binary. Then, if `unpack_pck`:

- **May-format probe** ([pipeline.py:562](../../pinball_decryptor/plugins/bof/pipeline.py#L562)): read the first 200 bytes of the PCK section and call `is_may_format()`.
  - **May path** ([pipeline.py:587](../../pinball_decryptor/plugins/bof/pipeline.py#L587)): `may_extractor.extract_pck(binary, pck/)` (extract drives 0–80% of the bar) then `source_converter.convert_imported_tree()` (80–100%). GDRE is skipped entirely.
  - **Pre-May (GDRE) path** ([pipeline.py:655](../../pinball_decryptor/plugins/bof/pipeline.py#L655)): `gdre_tools --recover=<binary> --output=pck/`, streaming GDRE's `\r`-separated progress and polling the Windows-side `pck/` file count. GDRE decompiles scripts and converts textures to PNG itself.

**`may_extractor.extract_pck()`** ([may_extractor.py:254](../../pinball_decryptor/plugins/bof/may_extractor.py#L254)): reads the PCK into memory, scans for every `[remap]\n` sidecar marker, parses each, classifies adjacent vs simple. For adjacent entries it computes file bounds `[prev_sidecar_end, this_sidecar_start)`, trimming the `RSCC` separator + zero padding and skipping interleaved `GDSC` script blobs ([may_extractor.py:314](../../pinball_decryptor/plugins/bof/may_extractor.py#L314)); RSCC payloads are decompressed; font magic restored. Simple sidecars are paired sequentially by magic: `.gdc` by `GDSC` occurrence order; `.scn`/`.res` by scanning `RSRC` starts and reading the embedded class name (`PackedScene` for `.scn`; any non-adjacent class for `.res`) ([may_extractor.py:430](../../pinball_decryptor/plugins/bof/may_extractor.py#L430)). Returns stats: `files_written`, `adjacent_count`, `sequential_count`, `rscc_count`, `unpaired_simple`, `total_bytes`. Recovers ~97% on Dune; remaining ~3% are `.scn`/`.res` (open work). Windows long paths handled with the `\\?\` prefix ([may_extractor.py:222](../../pinball_decryptor/plugins/bof/may_extractor.py#L222)).

**Editable-assets conversion — `source_converter.convert_imported_tree()`** ([source_converter.py:613](../../pinball_decryptor/plugins/bof/source_converter.py#L613)): walks `pck/` for every `.ctex`/`.sample`/`.oggvorbisstr`/`.fontdata` and decodes each into a player-friendly file under `pck/_EDITABLE ASSETS/`, bucketed by type into `audio/`, `images/`, `video/`, `fonts/` ([source_converter.py:540](../../pinball_decryptor/plugins/bof/source_converter.py#L540)). Decoders: `_decode_ctex` (GST2→webp/png, OggS→ogv), `_decode_sample` (QOA→wav / OGG→ogg / raw PCM→wav), `_decode_oggvorbisstr` (rebuilds an OGG container from the packet sequence, computing OGG CRC-32), `_decode_fontdata` (TTF/OTF out of the `data` PBA). Output filenames are `<stem>-<hash6><ext>` where `hash6` is the first 6 chars of the imported file's 32-hex MD5 — this is the key Write uses to pair edits back. A per-game **consensus sample rate** pre-pass scans up to 100 `.sample` trailers and takes the mode (Dune's is 48000, vs Godot's 44100 default) so `.sample` files with no embedded `mix_rate` decode at the right speed ([source_converter.py:648](../../pinball_decryptor/plugins/bof/source_converter.py#L648)). A `_README.txt` workflow hint is dropped in the folder. The leading-underscore all-caps `_EDITABLE ASSETS` name sorts to the top of Explorer/Finder.

**Phase 3 — Checksums** ([pipeline.py:743](../../pinball_decryptor/plugins/bof/pipeline.py#L743)): `_generate_checksums()` walks the whole output dir (skipping dotfiles) and writes `.checksums.md5` at the assets root as `<rel_path>\t<md5>` lines ([pipeline.py:381](../../pinball_decryptor/plugins/bof/pipeline.py#L381)). This is the baseline Write diffs against.

**Phase 4 — Cleanup** ([pipeline.py:750](../../pinball_decryptor/plugins/bof/pipeline.py#L750)): removes the `/tmp` tar + extract dirs.

### Output layout

```
<output>/
  <game>.x86_64            (Godot binary, GBOF→GDPC patched)
  md5                      (md5sum of the binary)
  updated_bash_profile     (version-gate script)
  updated_updatecode       (version-gate script)
  .checksums.md5           (extract baseline)
  pck/                     (unpacked PCK tree)
    .godot/imported/…      (imported binaries — what actually ships)
    .autoconverted/…       (GDRE/script .gdc cache)
    _EDITABLE ASSETS/      (editable copies — EDIT THESE)
      audio/  *.wav *.ogg *.qoa
      images/ *.webp *.png
      video/  *.ogv
      fonts/  *.ttf *.otf
      _README.txt
  .bof_modversion          (written by Write, not Extract)
```

## Write / repack pipeline

`ModifyPipeline._run()` ([pipeline.py:1511](../../pinball_decryptor/plugins/bof/pipeline.py#L1511)), wrapped by `_WriteWrapper` ([manufacturer.py:40](../../pinball_decryptor/plugins/bof/manufacturer.py#L40)) which re-detects the game from the original `.fun` and threads `version_date_override` through.

**Phase 0 — Decrypt** ([pipeline.py:1523](../../pinball_decryptor/plugins/bof/pipeline.py#L1523)): gpg-decrypt the **original** `.fun` and tar-extract it to `/tmp/bof_<game>_repack` (preserving the original archive structure so the repack matches byte-for-byte where unchanged).

**Phase 1 — Patch** ([pipeline.py:1557](../../pinball_decryptor/plugins/bof/pipeline.py#L1557)):

1. **Inverse-convert editable edits** — `inverse_converter.apply_source_edits(pck_dir, …)` ([pipeline.py:1606](../../pinball_decryptor/plugins/bof/pipeline.py#L1606), [inverse_converter.py:247](../../pinball_decryptor/plugins/bof/inverse_converter.py#L247)). This scans `pck/_EDITABLE ASSETS/` (and legacy `editable/`/`source/`) for files changed vs the baseline (MD5 against `.checksums.md5`, with mtime fallback). For each changed `<stem>-<hash6>.<ext>` it finds the matching imported binary in `.godot/imported/` and re-encodes the edit into it in place: `.wav`→`.sample` (`encode_wav_to_sample`, preserving QOA vs raw-PCM encoding by re-encoding to QOA if the original payload was `qoaf`; splices the new payload into the `data` PBA — [inverse_converter.py:136](../../pinball_decryptor/plugins/bof/inverse_converter.py#L136)), `.webp`/`.png`→`.ctex` (`encode_image_to_ctex`, splices the image into the GST2 wrapper, updating the size field — [inverse_converter.py:184](../../pinball_decryptor/plugins/bof/inverse_converter.py#L184)). `.ogg`/`.ogv`/`.ttf`/`.otf` inverse encoders are **not yet implemented** (not in `ENCODERS`, [inverse_converter.py:229](../../pinball_decryptor/plugins/bof/inverse_converter.py#L229)) — those edits are skipped with a clear log warning.
2. **MD5-diff the PCK** against `.checksums.md5` ([pipeline.py:1583](../../pinball_decryptor/plugins/bof/pipeline.py#L1583)), skipping `.autoconverted/`, the editable folders, and house-keeping files. (MD5, not mtime — mtime drift falsely flagged every file.)
3. **Reimport for the GDRE path** — `_reimport_assets()` ([pipeline.py:1080](../../pinball_decryptor/plugins/bof/pipeline.py#L1080)) handles changed loose `.wav`/`.ogg`/`.png`/`.jpg` that have `.import` sidecars (`_wav_to_sample` and `_ogg_to_oggvorbisstr` are pure-Python — [pipeline.py:1125](../../pinball_decryptor/plugins/bof/pipeline.py#L1125), [pipeline.py:1178](../../pinball_decryptor/plugins/bof/pipeline.py#L1178)), changed `.gd` scripts (`_recompile_scripts` via GDRE `--compile`, [pipeline.py:1387](../../pinball_decryptor/plugins/bof/pipeline.py#L1387)), and textures (`_reimport_textures` via `cwebp` + original ctex header, [pipeline.py:1451](../../pinball_decryptor/plugins/bof/pipeline.py#L1451)). The regenerated imported files are added to the changed list.
4. **Repack the binary** — branch on `_detect_may_format(binary)` ([pipeline.py:861](../../pinball_decryptor/plugins/bof/pipeline.py#L861), sniffs the trailer + first 200 PCK bytes via the executor):
   - **May path** — `_may_pack_binary()` → `may_packer.pack_pck()` ([pipeline.py:1011](../../pinball_decryptor/plugins/bof/pipeline.py#L1011), [may_packer.py:225](../../pinball_decryptor/plugins/bof/may_packer.py#L225)). Rebuilds the PCK **sequentially** (no offset table → any file can change size); copies the ELF/PE prefix bit-for-bit, walks the PCK monotonically writing each byte once (a defensive byte-walk that avoids the old 200 GB blow-up from re-writing sequential ranges per entry), substitutes edited adjacent files (raw, or re-wrapped in a fresh RSCC v2 Zstd container for `.fontdata` via `_build_rscc_container`, [may_packer.py:55](../../pinball_decryptor/plugins/bof/may_packer.py#L55)), and updates the trailer's `pck_size`. **`GBOF` magic is preserved natively** (the original trailer magic is read and re-emitted — [may_packer.py:249](../../pinball_decryptor/plugins/bof/may_packer.py#L249), [may_packer.py:422](../../pinball_decryptor/plugins/bof/may_packer.py#L422)), so no magic swap is needed. **Sequential `.gdc`/`.scn`/`.res` replacements are skipped** — they lack stable byte boundaries in BoF's layout ([may_packer.py:371](../../pinball_decryptor/plugins/bof/may_packer.py#L371)). Two fidelity guards: **(a) unchanged fonts are left byte-for-byte verbatim** — a font's compressed PCK bytes never equal its decompressed on-disk form, so the substitution decision compares *decompressed payloads*; without this every Write re-wrapped all ~52 fonts; **(b) every size-changing substitution is zero-padded to keep its region length ≡ the original (mod 16)**, preserving the PCK's 16-byte entry alignment (see gotcha). Streams output to keep peak RSS ~1.5 GB on a 2.8 GB binary.
   - **Pre-May (GDRE) path** ([pipeline.py:1721](../../pinball_decryptor/plugins/bof/pipeline.py#L1721)): swap `GBOF→GDPC`, write a `bash` script invoking `gdre_tools --pck-patch=<binary> --output=<tmp> --embed=<binary> --patch-file='<local>=res://<rel>'` (one `--patch-file` per changed file; written via base64 temp script to dodge arg-length limits), `mv` the patched binary back, then restore `GDPC→GBOF` if it was originally GBOF.
5. Regenerate the `md5` file ([pipeline.py:1792](../../pinball_decryptor/plugins/bof/pipeline.py#L1792)).

**Version-date gate (auto-bump + override)** — `_bump_update_version()` ([pipeline.py:893](../../pinball_decryptor/plugins/bof/pipeline.py#L893)) runs after patching. The game reads the `YYYY.MM.DD` on **line 2** of `updated_bash_profile`/`updated_updatecode` (the line after "Godot Code looks for the date on the next line") and only installs the `.fun` if that date is newer than what's running. Two modes:

- **Explicit** (`version_date_override` set, Auto unchecked): stamp exactly that date. Escape hatch for force-installing (e.g. official code dated below an installed mod).
- **Auto** (default): `new = max(embedded_baseline, last_emitted) + 1 day`. The last date emitted for this folder is tracked in `assets_dir/.bof_modversion` ([pipeline.py:785](../../pinball_decryptor/plugins/bof/pipeline.py#L785)) so successive rebuilds keep climbing. Climbing from the baseline (not "today") keeps the mod version-adjacent to stock so any genuine future official BoF release still out-dates and supersedes it. Arithmetic is done in Python (BSD vs GNU `date` portability); the file edit is `sed -i '2s|.*|# <date> |'`.

The GUI preview uses `peek_next_update_version(assets_dir)` ([pipeline.py:800](../../pinball_decryptor/plugins/bof/pipeline.py#L800)), which computes the same `(baseline, next_date_str)` host-side. Date parsing/climbing verified by [test_bof_update_version.py](../../tests/test_bof_update_version.py).

**Phase 2 — Repack** ([pipeline.py:1815](../../pinball_decryptor/plugins/bof/pipeline.py#L1815)): `cd <tmp> && tar -czf <repack>.tar.gz *` (glob, not `.`, to match the original tar's no-`./`-prefix structure exactly).

**Phase 3 — Encrypt** ([pipeline.py:1849](../../pinball_decryptor/plugins/bof/pipeline.py#L1849)): `gpg --symmetric --cipher-algo AES256` → the output `.fun`.

**Phase 4 — Cleanup** ([pipeline.py:1870](../../pinball_decryptor/plugins/bof/pipeline.py#L1870)).

**Output naming:** the output `.fun` path is supplied by the caller (app.py / the unified Write tab); the pipeline does not impose a name. **Install** ([manufacturer.py:174](../../pinball_decryptor/plugins/bof/manufacturer.py#L174)): copy the output `.fun` to a FAT32 USB drive, insert into the machine, follow the on-screen update prompts.

## Audio assets

- **`.sample`** = Godot `AudioStreamWAV`, an `RSRC` binary whose `data` PackedByteArray holds raw 16-bit PCM, **QOA** (`qoaf`), or OGG (`OggS`). The pure-Python `_wav_to_sample()` ([pipeline.py:1125](../../pinball_decryptor/plugins/bof/pipeline.py#L1125)) produces byte-identical output to Godot 4.4.1's `ResourceSaver` for uncompressed PCM, using a fixed 334-byte base64'd RSRC header + a 48-byte trailer encoding `format`/`mix_rate`/`stereo`.
- **`.oggvorbisstr`** = Godot `AudioStreamOggVorbis`, an `RSRC` binary wrapping an `OggPacketSequence` sub-resource (the raw vorbis packets, per-page granule positions, and sample rate). The pure-Python `_ogg_to_oggvorbisstr()` ([pipeline.py:1178](../../pinball_decryptor/plugins/bof/pipeline.py#L1178)) parses OGG pages/packets and serialises the two sub-resources with their variant-encoded property tables.
- **Editable formats:** `.sample`→`.wav` (QOA decoded to WAV; OGG passthrough to `.ogg`; raw PCM wrapped in a 44-byte RIFF/WAVE header), `.oggvorbisstr`→`.ogg` (rebuilt container). QOA is decoded via `qoa_codec.decode` and, on Write, re-encoded via `qoa_codec.encode` if the original `.sample` payload was QOA — so QOA round-trips are not bit-identical (the `_README.txt` advises lossless WAV sources).
- **Replace-Audio:** `audio_slot_dirs(assets_dir)` ([manufacturer.py:144](../../pinball_decryptor/plugins/bof/manufacturer.py#L144)) walks the extract and returns every `_EDITABLE ASSETS` folder it finds, restricting the Replace-Audio slot scan to **just** those — so the `.godot/imported/` cache and raw PCK resources (which would be dead-ends if staged) never appear as slots. A replacement assigned to a slot overwrites the editable `.wav`/`.ogg`; the normal Write pipeline then inverse-converts it back into the imported binary (the same `apply_source_edits` path).

## Other asset types

- **Images:** `.ctex` (`CompressedTexture2D`, `GST2` header wrapping RIFF/WebP — most common — or PNG) → `.webp`/`.png`. Write: `encode_image_to_ctex` (May path) splices the new image into the GST2 wrapper; the GDRE pre-May path uses `cwebp -lossless` + the original ctex header in `_reimport_textures`.
- **Video:** `.ctex` variants whose payload is raw `OggS` Theora are exported as `.ogv` ([source_converter.py:79](../../pinball_decryptor/plugins/bof/source_converter.py#L79)). BoF stores some animation loops as video-under-the-texture-extension. `.ogv`→`.ctex` inverse encoding is described in the module docstring but **not implemented** in `ENCODERS` (skipped on Write). *(Note: standalone `.ogv` video files at the PCK top level, if present, would pass through `may_extractor` as raw bytes — only the `.ctex`-wrapped video gets the `.ogv` export. (unverified for non-ctex `.ogv`))*
- **Fonts:** `.fontdata` (`FontFile`, RSCC-Zstd wrapped) → `.ttf`/`.otf` via `_decode_fontdata` ([source_converter.py:488](../../pinball_decryptor/plugins/bof/source_converter.py#L488)). On May-path Write, `may_packer` re-wraps a modified `.fontdata` into a fresh RSCC container (stripping any restored `RSRC` magic first); but the `.ttf`/`.otf`→`.fontdata` inverse encoder itself is not implemented, so editing the editable font file does not round-trip today. (unverified end-to-end)
- **Scripts/scenes:** `.gdc` (compiled GDScript, `GDSC` magic), `.scn` (binary `PackedScene`), `.res` (binary resource). Extracted via the sequential-pairing strategy. `.gd` source recompilation to `.gdc` is supported on the **pre-May GDRE path only** (`_recompile_scripts`, needs the bytecode revision from `gdre_export.log`). The May path's `may_packer` **skips** `.gdc`/`.scn`/`.res` substitution (no stable byte boundaries).

## Mod Pack / delta / direct-SSD

- **Mod Pack:** supported (`modpack=True`). `export_mod_pack()` ([pipeline.py:318](../../pinball_decryptor/plugins/bof/pipeline.py#L318)) zips only files whose current MD5 differs from the `.checksums.md5` baseline; `import_mod_pack()` ([pipeline.py:360](../../pinball_decryptor/plugins/bof/pipeline.py#L360)) extracts a mod-pack zip over the assets folder.
- **Apply-delta:** N/A (`apply_delta=False`).
- **Direct-SSD:** N/A (`direct_ssd=False`).
- **ISO / capture / transcribe / asset-filters / decode-DMD / chain-deltas:** N/A.

## Detection

`detect(path)` ([manufacturer.py:137](../../pinball_decryptor/plugins/bof/manufacturer.py#L137)) → `detect_game(path)` ([pipeline.py:312](../../pinball_decryptor/plugins/bof/pipeline.py#L312)): lowercases the **basename** and looks it up in `FUN_FILE_TO_GAME` (`lab.fun`/`dune.fun`/`winchester.fun`). Detection is **purely filename-based** — there is no content/magic sniff at detect time (the `.fun` is GPG-encrypted, so its bytes are opaque without the passphrase). Returns the matching `Game` or `None`. In the registry order, BoF is tried after pb/ap/spooky and before jjp/cgc/williams/dp ([registry.py:19](../../pinball_decryptor/core/registry.py#L19)); because its detector only claims the three known filenames, it never grabs other manufacturers' files. The `GBOF`/`GDPC` PCK magic and the `RSCC`/`GST2`/`OggS`/`RSRC` magics are used only *after* decryption, inside the extract/write pipelines — not in `detect()`.

## Gotchas & non-obvious details

- **Version-date install gate.** A correctly-repacked `.fun` whose embedded `YYYY.MM.DD` is not newer than the installed code is silently ignored by the machine ("no new code"). Write auto-bumps it; if you re-Write from the same folder it climbs via `.bof_modversion`. To force *official* code back onto a machine running a higher-dated mod, use the manual override field to stamp a date above the mod's.
- **May vs pre-May divergence is automatic but total.** `is_may_format()`/`_detect_may_format()` select between the native extractor/packer and GDRE. The two paths share almost no code: May = pure Python + `zstandard`; pre-May = GDRE Tools + xvfb (+ cwebp for textures). Winchester (April) is a May-format-without-tripwires variant and uses the native path too.
- **GDRE + xvfb requirement (pre-May only).** GDRE is a headless Godot binary; on Linux/WSL it needs `xvfb-run` and `DISPLAY=`/`WAYLAND_DISPLAY=` cleared ([pipeline.py:208](../../pinball_decryptor/plugins/bof/pipeline.py#L208)). On macOS it's `~/.local/share/gdre_tools/Godot RE Tools`. The canonical Linux install is `/opt/gdre_tools/gdre_tools.x86_64`.
- **Imported-cache exclusion.** `pck/.godot/imported/` and `pck/.autoconverted/` are caches. Extract's editable conversion reads from `.godot/imported/`; Write's MD5 diff explicitly skips `.autoconverted/` and the editable folders ([pipeline.py:1633](../../pinball_decryptor/plugins/bof/pipeline.py#L1633)). Don't edit the imported binaries by hand — edit the `_EDITABLE ASSETS/` copies; Write re-encodes them back into `.godot/imported/`.
- **Hash-suffix pairing.** Editable filenames carry a 6-char hash (`<stem>-<hash6>.<ext>`); **renaming breaks the pair-back** (the `_SOURCE_NAME_RE` won't match, or `find_matching_imported` won't find the `.godot/imported` file). Moving files *between* the audio/images/video/fonts subfolders is fine (Write walks recursively).
- **`GBOF` must be restored on Write output.** If the binary started as `GBOF` and the pre-May GDRE path runs, the magic must be swapped back to `GBOF` after GDRE (which only writes `GDPC`) or the real machine can't find its PCK. The May packer preserves it natively.
- **Sequential-file modding is unsupported.** `.gdc`/`.scn`/`.res` edits don't round-trip through `may_packer` (no stable byte boundaries). Only adjacent imported assets (audio/textures/fonts) repack cleanly on the May path.
- **PCK 16-byte alignment is load-critical.** The real Dune PCK keeps ~96% of file/sidecar starts at offset ≡ 8 (mod 16); BoF's no-directory loader walks the PCK forward and a misaligned entry appears to make the running game fail to boot (black screen, while the update's MD5 "validated" gate still passes — that only checks USB-transfer integrity, not bootability). Two `may_packer` behaviors protect this and are easy to regress: unchanged fonts must stay verbatim (don't re-wrap on a compressed-byte compare), and any size-changing substitution must be zero-padded to keep its region length ≡ original (mod 16). Verified by `test_pack_leaves_unchanged_fonts_verbatim` and `test_pack_preserves_16byte_alignment`; a clean local proxy is the alignment-retention metric (re-read `_read_pck_entries` offsets on the repacked binary — should stay ~96%, not drop to ~49%). *(Hypothesis: the alignment break is what black-screens modded Dune builds; pending hardware/log confirmation.)*
- **Two re-import surfaces — only one handles `.ogg`.** Edits under `pck/_EDITABLE ASSETS/` go through `apply_source_edits` → `inverse_converter.ENCODERS`, which has **only** `.wav`→`.sample` and `.webp`/`.png`→`.ctex` ([inverse_converter.py:229](../../pinball_decryptor/plugins/bof/inverse_converter.py#L229)); editable `.ogg`/`.ogv`/`.ttf`/`.otf` are skipped (no effect on Write). Separately, the MD5 walk's `_reimport_assets`/`_reimport_audio` ([pipeline.py:1080](../../pinball_decryptor/plugins/bof/pipeline.py#L1080)) **does** re-encode `.ogg`→`.oggvorbisstr` via `_ogg_to_oggvorbisstr`, but only for loose source files at their Godot path with a `.import` sidecar — and that walk explicitly *excludes* the editable folder ([pipeline.py:1636](../../pinball_decryptor/plugins/bof/pipeline.py#L1636)). So the working `.ogg` encoder is never reached from the editable workflow. **Consequence for Replace-Audio:** BoF's tab is restricted to `.wav` slots (`audio_slot_exts` returns `(".wav",)`) so a staged `.ogg` can't silently dead-end. Wiring `_ogg_to_oggvorbisstr` into `apply_source_edits` would let editable `.ogg` (and Replace-Audio `.ogg`) round-trip — a worthwhile future enhancement.
- **Per-game consensus sample rate.** `.sample` files lacking an explicit `mix_rate` decode at the game's modal rate (Dune = 48000), not Godot's 44100 default — otherwise they play ~8% slow.
- **Windows long paths.** PCK `res://` paths routinely exceed `MAX_PATH`; extractor, packer, and converters all use the `\\?\` prefix on Win32 ([may_extractor.py:222](../../pinball_decryptor/plugins/bof/may_extractor.py#L222)).
- **Everything shells through the executor.** On Windows all gpg/tar/gdre/find runs go through WSL as root (`wsl -u root -- bash -c`); paths are translated `C:\…` → `/mnt/c/…` ([executor.py:142](../../pinball_decryptor/plugins/bof/executor.py#L142)). On macOS/Linux they run natively. This is why even a pure-Python operation that needs a binary copy uses `executor.run("cp …")`.
- **Static passphrases.** The GPG passphrases are hardcoded per game ([games.py:3](../../pinball_decryptor/plugins/bof/games.py#L3)); they are symmetric, not asymmetric keys.

## Key files

- [`__init__.py`](../../pinball_decryptor/plugins/bof/__init__.py) — plugin entry point; `register()` registers `BOFManufacturer`.
- [`manufacturer.py`](../../pinball_decryptor/plugins/bof/manufacturer.py) — `BOFManufacturer`: key/display/games, capabilities, prereqs, phase labels, `detect`, `audio_slot_dirs`, extract/write factory wrappers, install help.
- [`games.py`](../../pinball_decryptor/plugins/bof/games.py) — `GAME_DB` (display/`.fun` filename/passphrase/platform), `FUN_FILE_TO_GAME`, phase-name lists, op timeouts.
- [`pipeline.py`](../../pinball_decryptor/plugins/bof/pipeline.py) — `DecryptPipeline` (extract), `ModifyPipeline` (write), `_patch_pck_magic`, mod-pack export/import, checksums, version-date helpers (`parse_update_date`, `peek_next_update_version`, `_bump_update_version`), pure-Python `_wav_to_sample`/`_ogg_to_oggvorbisstr`, GDRE reimport/recompile/texture helpers.
- [`may_extractor.py`](../../pinball_decryptor/plugins/bof/may_extractor.py) — native extractor for the May/Winchester custom PCK: `find_pck_section`, `is_may_format`, sidecar parsing, adjacent + sequential pairing, `extract_pck`.
- [`may_packer.py`](../../pinball_decryptor/plugins/bof/may_packer.py) — native repacker: `_read_pck_entries`, RSCC re-wrap (`_build_rscc_container`), streaming sequential rewrite (`pack_pck`), GBOF-magic preservation.
- [`rscc_decoder.py`](../../pinball_decryptor/plugins/bof/rscc_decoder.py) — `RSCC` Zstd container: `is_rscc_at`, `parse_header`, `decompress`, `scan`.
- [`qoa_codec.py`](../../pinball_decryptor/plugins/bof/qoa_codec.py) — pure-Python QOA `decode`/`encode` (LMS predictor + scale/dequant tables).
- [`source_converter.py`](../../pinball_decryptor/plugins/bof/source_converter.py) — imported→editable decoders (`_decode_ctex`/`_decode_sample`/`_decode_oggvorbisstr`/`_decode_fontdata`), `EDITABLE_DIR_NAME`, `LEGACY_DIR_NAMES`, `convert_imported_tree`, consensus-rate pre-pass, `_README`.
- [`inverse_converter.py`](../../pinball_decryptor/plugins/bof/inverse_converter.py) — editable→imported encoders (`encode_wav_to_sample`, `encode_image_to_ctex`), filename pairing (`parse_source_name`, `find_matching_imported`), `apply_source_edits`.
- [`executor.py`](../../pinball_decryptor/plugins/bof/executor.py) — `WslExecutor`/`NativeExecutor`/`MacExecutor` + `create_executor`; path translation, streaming, `CommandError`.
- [`core/registry.py`](../../pinball_decryptor/core/registry.py) — base `Manufacturer`/`Capabilities`/`Game`/`InputSpec` contract.

## Related docs

- [`docs/CGC_BNK_RE.md`](../CGC_BNK_RE.md) — CGC indexed sound-bank reverse-engineering (different manufacturer; not cross-linked from code).
- [`docs/AP_PKG_RE.md`](../AP_PKG_RE.md) — American Pinball `.pkg` format notes.
- There is **no** standalone BoF RE markdown in `docs/`; the authoritative format notes live in the module docstrings (`may_extractor.py`, `rscc_decoder.py`, `qoa_codec.py`) and the user memory entries `reference_bof_may2026_pck_format` and `reference_bof_update_version_gate`.
