# Jersey Jack Pinball (`jjp`) — Architecture

> JJP games ship as a Clonezilla `.iso` containing a gzip-split [partclone](https://partclone.org) image of an **ext4** game partition. Inside that filesystem the asset tree (`edata/`) is per-file XOR-encrypted with a path-keyed PRNG keystream, and a `fl.dat` manifest holds, for every file, a random-filler size plus two CRC32 checksums (encrypted-on-disk + decrypted-content). Extract decrypts the tree to loose PNG/WAV/OGG files; Write re-encrypts modified files using **CRC32 forgery** so the doctored bytes still satisfy `fl.dat`'s checksums *without rewriting `fl.dat`*. Everything Linux-side (partclone, debugfs, xorriso) runs through a platform executor (WSL on Windows, Docker on macOS, native on Linux). A separate **Direct-SSD** path reads/writes the physical game SSD with no ISO intermediate.

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/jjp/`
- **Key / display:** `jjp` / "Jersey Jack Pinball" — [manufacturer.py:163](../../pinball_decryptor/plugins/jjp/manufacturer.py#L163)
- **Registration order:** 5th of 8 (`pb, ap, spooky, bof, jjp, cgc, williams, dp`) — [registry.py:19](../../pinball_decryptor/core/registry.py#L19)

### Supported games

The GUI "Detected:" badge is driven by `GAME_DB`, a superset of the runtime-detected `config.KNOWN_GAMES`. Every entry is marked `supported: True`; detection is a case-insensitive substring match of `filename_prefixes` against the ISO basename — [games.py:11](../../pinball_decryptor/plugins/jjp/games.py#L11).

| key | display | supported? | notes |
|-----|---------|------------|-------|
| `wonka` | Willy Wonka & the Chocolate Factory | yes | prefix `wonka` |
| `guns_n_roses` | Guns N' Roses | yes | prefixes `gunsnroses`, `gnr` |
| `elton_john` | Elton John | yes | prefixes `eltonjohn`, `elton` |
| `the_hobbit` | The Hobbit | yes | prefix `hobbit` |
| `the_godfather` | The Godfather | yes | prefix `godfather` |
| `avatar` | Avatar | yes | prefix `avatar` |
| `sonic` | Sonic the Hedgehog | detect only | prefix `sonic`; assets do **not** decrypt yet — see below |
| `pirates_of_the_caribbean` | Pirates of the Caribbean | yes | prefixes `pirates`, `potc` |
| `wizard_of_oz` | The Wizard of Oz | yes | prefixes `wizardofoz`, `woz` |
| `toy_story` | Toy Story 4 | yes | prefix `toystory` |
| `dialed_in` | Dialed In! | yes | prefix `dialedin` |
| `harry_potter` | Harry Potter | yes | prefix `harrypotter` |

Only the first six appear in `config.KNOWN_GAMES` (the names the runtime decryptor maps inside the mounted filesystem). That table is a verbatim upstream lift the regression check pins byte-for-byte ([verify_no_upstream_regression.py:143](../../tests/verify_no_upstream_regression.py#L143)), so new titles go in `GAME_DB` only — `KNOWN_GAMES` is just a fast path for the Direct-SSD `debugfs` probe, which falls back to listing `/jjpe/gen1` when no name matches ([pipeline.py:5977](../../pinball_decryptor/plugins/jjp/pipeline.py#L5977)). The others light the badge from the filename but still decrypt via the generic dongle-free path (the crypto is game-independent — the file *path* is the key). The standalone pipeline auto-detects the actual game folder from the mount regardless of `GAME_DB`.

#### Sonic: a new asset encryption (unsolved as of 2026-07-21)

`Sonic-v00.925.iso` mounts, detects and walks fine (16,207 files under `/jjpe/gen1/Sonic/edata`), but **not one asset decrypts**. Measured on the mounted image:

- Every encrypted file — all 16,440 across `edata` *and* the shared `ecoredata` tree — has a size that is an exact multiple of 8. The old container has no such alignment (filler + content + 4-byte CRC suffix lands anywhere). `fl.dat` itself is *not* 8-aligned, so it sits outside whatever the new wrapper is.
- 1,680 combinations of key-path derivation × seeding mode (`set_seeds_for_crypto` / `set_seeds_for_filler`, absolute/relative/case-folded/backslashed paths) produce zero magic-byte hits across 27 sample files spanning png/jpg/wav/ogg/webm/ttf.
- The failure is not title-scoped: the shared `ecoredata` tree, whose paths are identical across JJP titles, is equally undecryptable on this card.
- Not a block cipher in ECB — zero repeated 16-byte blocks in 33 MB WAVs — and not a global keystream: assuming the magic sits at any fixed offset (0/4/8/16/32/64) yields a different implied keystream for every file, so the key is still per-file.
- The `game` ELF is still Sentinel/HASP-wrapped (`strings` shows the LDK runtime), so the routine is not statically visible — the same reason the original scheme had to be recovered from memory dumps.

Recovering this needs the original dynamic-analysis approach against the Sonic binary. Until then the plugin detects the title, and both the ISO and Direct-SSD decrypt phases fail loudly rather than reporting a complete run over an empty folder ([pipeline.py](../../pinball_decryptor/plugins/jjp/pipeline.py) `_nothing_decrypted_message`). `full_dump` (the Extract tab's **File System** box) still works — the unencrypted side of the card is unaffected.

### Input extensions / InputSpec

- `InputSpec(label="JJP game ISOs", extensions=(".iso",))` — [manufacturer.py:179](../../pinball_decryptor/plugins/jjp/manufacturer.py#L179)
- Direct-SSD mode swaps the file picker for a drive picker; the "input" is then an OS-native physical-disk path (`\\.\PHYSICALDRIVEn` / `/dev/diskN` / `/dev/sdX`).

### Capabilities

`Capabilities(...)` — [manufacturer.py:166](../../pinball_decryptor/plugins/jjp/manufacturer.py#L166):

| flag | value | meaning |
|------|-------|---------|
| `extract` | True | Decrypt an ISO → loose assets |
| `write` | True | Re-encrypt modified assets and rebuild the ISO |
| `modpack` | True | Export/import a delta ZIP of only-changed files (`export_mod_pack` / `import_mod_pack`) |
| `apply_delta` | False | No upstream delta-update concept |
| `iso` | True | Input is an ISO container |
| `direct_ssd` | True | Read/write the physical game SSD directly — surfaces the "From ISO / From SSD" radio on Extract + Write |
| `asset_filters` | True | Graphics / Sounds / File System checkboxes → `extract_graphics` / `extract_sounds` / `full_dump` |
| `replace_audio` | True | Replace-Audio tab scans the extract for loose `.wav`/`.ogg` slots |

`audio_slot_dirs()` is not overridden, so Replace-Audio scans the whole extract for loose `.wav`/`.ogg` (registry default returns `None`) — [registry.py:283](../../pinball_decryptor/core/registry.py#L283).

### Prerequisites

Probed inside the executor (WSL/Docker/native) — [manufacturer.py:197](../../pinball_decryptor/plugins/jjp/manufacturer.py#L197), checked again per-run by `check_prerequisites` — [pipeline.py:8345](../../pinball_decryptor/plugins/jjp/pipeline.py#L8345):

| tool | where | why |
|------|-------|-----|
| `partclone` (`partclone.ext4`) | wsl/container | compress/decompress the ext4 partition image in/out of the ISO |
| `debugfs` (`e2fsprogs`) | wsl/container/native | read & write files in the ext4 image **without mounting** (Write path) |
| `xorriso` | wsl/container | splice new partition chunks into the original ISO; fallback ISO extraction when loop mounts fail |
| `pigz` | wsl/container | parallel gzip — speeds the partclone re-compress (falls back to `gzip`) |
| `ffmpeg` | wsl/container | audio sample-rate / OGG conversion during Write |

The host backend itself (WSL2 / Docker Desktop / native sudo) is the implicit top-level prereq — [config.py:139](../../pinball_decryptor/plugins/jjp/config.py#L139). A bundled `partclone_to_raw.py` pure-Python decoder is the *primary* ISO→raw method, so `partclone` is only needed for the Write re-compress in practice — [pipeline.py:672](../../pinball_decryptor/plugins/jjp/pipeline.py#L672).

### Phase labels

- **ISO Extract:** `Extract → Mount → Decrypt → Cleanup` — [config.py:98](../../pinball_decryptor/plugins/jjp/config.py#L98) / [manufacturer.py:186](../../pinball_decryptor/plugins/jjp/manufacturer.py#L186)
- **ISO Write:** `Scan → Extract → Prepare → Encrypt → Convert → Build ISO → Cleanup` — [config.py:105](../../pinball_decryptor/plugins/jjp/config.py#L105) / [manufacturer.py:187](../../pinball_decryptor/plugins/jjp/manufacturer.py#L187)
- **Direct-SSD Extract:** `Mount → Decrypt → Cleanup` — [config.py:116](../../pinball_decryptor/plugins/jjp/config.py#L116)
- **Direct-SSD Write:** `Scan → Mount → Encrypt → Cleanup` — [config.py:122](../../pinball_decryptor/plugins/jjp/config.py#L122)

(`config.py` also defines `PHASES` / `MOD_PHASES` — the longer dongle/chroot/compile flows — which are **not exposed** by the manufacturer; see [Container & encryption](#container--encryption-format) and [Gotchas](#gotchas--non-obvious-details).)

## Container & encryption format

### ISO → partclone → ext4 `edata` tree

The `.iso` is a Clonezilla restore image. Under `/home/partimag/img` (`config.PARTIMAG_PATH`) it holds the game partition `sda3` as a split, gzip-compressed partclone v2 stream named `sda3.ext4-ptcl-img.gz.aa`, `.ab`, … — [config.py:25](../../pinball_decryptor/plugins/jjp/config.py#L25). `partclone_to_raw.py` reconstructs the raw ext4 image from the partclone header + block bitmap + data blocks (reading the `image_head_v2` magic `partclone-image`, little-endian `0xC0DE` endianness marker, block size, and per-block bitmap) — [partclone_to_raw.py:56](../../pinball_decryptor/plugins/jjp/partclone_to_raw.py#L56).

Inside the ext4 filesystem the game lives at `/jjpe/gen1/<GameName>/` (`config.GAME_BASE_PATH = /jjpe/gen1`). The encrypted assets are under `<GameName>/edata/` with `graphics/` and `sound/` subtrees, plus `edata/fl.dat` — [config.py:9](../../pinball_decryptor/plugins/jjp/config.py#L9).

### `fl.dat` layout

`fl.dat` is itself encrypted (see below). Decrypted, it is plain `latin-1` text, one CSV line per file:

```
<absolute_path>,<n1 filler_size>,<n2 enc_crc>,<n3 dec_crc>
```

Parsed right-to-left (`rsplit(',', 3)`) so paths containing commas survive — [filelist.py:20](../../pinball_decryptor/plugins/jjp/filelist.py#L20). `FileEntry` fields — [filelist.py:11](../../pinball_decryptor/plugins/jjp/filelist.py#L11):

- `path` — full absolute path, e.g. `/jjpe/gen1/Wonka/edata/graphics/foo.png`
- `filler_size` (**n1**) — count of random padding bytes prepended before real content
- `crc_encrypted` (**n2**) — CRC32 of the *encrypted* bytes as they sit on disk
- `crc_decrypted` (**n3**) — CRC32 of the *decrypted* content after filler removal

The `edata` prefix (e.g. `/jjpe/gen1/Wonka/edata/`) is recovered from the first entry by locating `/edata/` — [filelist.py:61](../../pinball_decryptor/plugins/jjp/filelist.py#L61).

### File stream cipher (`jcrypt_rand64` XOR)

Each `edata` file is XORed with a 64-bit keystream whose seed is derived from the file's absolute path — symmetric, so the same routine encrypts and decrypts. Reimplemented in pure Python from the game's reverse-engineered RNG — [crypto.py:54](../../pinball_decryptor/plugins/jjp/crypto.py#L54):

1. `hash_string` — BKDR hash, multiplier 131, 32-bit — [crypto.py:31](../../pinball_decryptor/plugins/jjp/crypto.py#L31).
2. `set_seeds_for_crypto(path)` builds four derived path buffers (reversed, slash-stripped, reversed+slash-stripped, each-byte+1), hashes the original + all four, and packs the five 32-bit hashes into four `uint64` state words `s0..s3` (`s2` masked to 58 bits) — [crypto.py:98](../../pinball_decryptor/plugins/jjp/crypto.py#L98).
3. `rand64()` is a combined generator per 64-bit output: a 128-bit counter update on `(s2,s3)`, an xorshift64 on `s1` (shifts 13/17/43), and an LCG on `s0` (`mult 0x19baffbed`, `add 0x12d687`); output = `(s3_new + s0_new + s1_new) & M64` — [crypto.py:70](../../pinball_decryptor/plugins/jjp/crypto.py#L70).
4. `xor_keystream` packs each `rand64()` word **little-endian** and XORs it over the next 8 bytes — [crypto.py:141](../../pinball_decryptor/plugins/jjp/crypto.py#L141).

`decrypt_file(enc, filler_size, path)` = `xor_keystream(enc)[filler_size:]` — the filler is decrypted along with everything else, then sliced off — [crypto.py:159](../../pinball_decryptor/plugins/jjp/crypto.py#L159).

### `fl.dat` decryption (`dongle_decrypt_buffer`)

`fl.dat` uses a *different*, dongle-specific routine (`dongle_decrypt_buffer`) — **not** the path-keyed `jcrypt` stream. The pure-Python port does not reimplement it; instead the plugin reads the **already-decrypted** `fl_decrypted.dat` that the Decrypt phase produced (the embedded-C decryptor, when used, calls the real `dongle_decrypt_buffer` from the game binary). In the dongle-free standalone path, when no `fl_decrypted.dat` is present the plugin *reconstructs* the metadata by scanning the filesystem (`scan_edata_files` / `detect_filler_size`) instead of decrypting `fl.dat` — [filelist.py:75](../../pinball_decryptor/plugins/jjp/filelist.py#L75), [crypto.py:481](../../pinball_decryptor/plugins/jjp/crypto.py#L481). The embedded-C `dongle_decrypt_buffer` call lives in `do_decrypt`/`do_encrypt` — [resources.py:100](../../pinball_decryptor/plugins/jjp/resources.py#L100).

### Dongle-free filler detection

Without `fl.dat`, `detect_filler_size` recovers each file's `n1` from the *decrypted* bytes: magic-byte signatures for binary types (PNG/OGG/WAV/JPEG/WebM/…) — [crypto.py:330](../../pinball_decryptor/plugins/jjp/crypto.py#L330) — and an entropy-transition + word-score heuristic for text files (filler is ~37% printable noise, content is ~100% printable) — [crypto.py:481](../../pinball_decryptor/plugins/jjp/crypto.py#L481). The docstring claims 100% accuracy across 26,446 files from Hobbit/GnR/Elton John (unverified beyond the comment).

## Extract pipeline

The manufacturer exposes `StandaloneDecryptPipeline` via `_ExtractWrapper` (auto-scan: `fl_dat_path=None`) — [manufacturer.py:64](../../pinball_decryptor/plugins/jjp/manufacturer.py#L64). It runs `Extract → Mount → Decrypt → Cleanup` — [pipeline.py:3173](../../pinball_decryptor/plugins/jjp/pipeline.py#L3173).

**Phase 0 — Extract** (`_phase_extract`, [pipeline.py:590](../../pinball_decryptor/plugins/jjp/pipeline.py#L590)): loop-mount the ISO read-only (fall back to `xorriso -osirrox` extraction when loop devices are unavailable, e.g. Docker/VirtioFS), enumerate the `sda3` partclone parts, and reconstruct the raw ext4 image into a deterministic cache path `/var/tmp/jjp_raw_<iso>.img` (`/var/tmp` chosen so systemd-tmpfiles-clean won't delete it mid-mount). Primary converter is the bundled `partclone_to_raw.py`; native `partclone.restore` is the fallback (and is auto-truncate-extended to the full superblock size) — [pipeline.py:719](../../pinball_decryptor/plugins/jjp/pipeline.py#L719).

**Phase 1 — Mount** (`_phase_mount`, [pipeline.py:833](../../pinball_decryptor/plugins/jjp/pipeline.py#L833)): `mount -o loop` the raw image at `/mnt/jjp_<uuid>`. If a cached image fails to mount it is deleted and re-extracted once.

**Game detection** (`_detect_game`, [pipeline.py:3255](../../pinball_decryptor/plugins/jjp/pipeline.py#L3255)): `ls /jjpe/gen1/`, pick the subdir that contains a `game` binary.

**Phase 2 — Decrypt** (`_phase_decrypt_standalone`, [pipeline.py:3281](../../pinball_decryptor/plugins/jjp/pipeline.py#L3281)): the heart of the dongle-free flow. `crypto.py` + `filelist.py` are copied into the executor's `/tmp`, and a templated `_DECRYPT_SCRIPT` ([pipeline.py:172](../../pinball_decryptor/plugins/jjp/pipeline.py#L172)) runs as a single in-WSL Python process — decrypting straight from the mounted ext4 to the Windows/host output folder. This avoids per-file cross-OS round-trips. Two modes:
  - **With `fl_decrypted.dat`** (cached): use known filler sizes — fast.
  - **Without** (auto-scan): `os.walk(edata)`, detect filler sizes via `detect_filler_size`, and write a freshly-`computed` `fl_decrypted.dat` (with real `n3` values) at the end so a later Write has the metadata.

Progress is parsed out of `TOTAL_FILES=` / `Progress: … (ok= fail= skip=)` / `Total: …` log lines.

**Asset-filter categories** are applied inside the decrypt script: a relative path under `graphics/` is gated by `EXTRACT_GRAPHICS`, under `sound/` by `EXTRACT_SOUNDS`, everything else (config files) always kept — [pipeline.py:228](../../pinball_decryptor/plugins/jjp/pipeline.py#L228). If neither category is selected, decryption is skipped entirely — [pipeline.py:3221](../../pinball_decryptor/plugins/jjp/pipeline.py#L3221). The **File System** checkbox maps to `full_dump`, which runs `_phase_copy_full_filesystem` ([pipeline.py:3420](../../pinball_decryptor/plugins/jjp/pipeline.py#L3420)): a `tar | tar` stream of every non-`edata`, non-virtual directory into `system/` (game binary, libs, OS configs — *unencrypted*, not in `fl.dat`).

**Checksums:** after all assets+system files land, `_generate_checksums` streams `md5sum` over the output (excluding dotfiles, `fl_decrypted.dat`, `*.img`) into `.checksums.md5` — the baseline that Write's Scan diffs against — [pipeline.py:344](../../pinball_decryptor/plugins/jjp/pipeline.py#L344).

### Output layout

```
<output>/
  graphics/…           # decrypted PNG/JPG/WebM
  sound/…              # decrypted WAV/OGG
  <other edata files>  # configs, lua, etc.
  system/…             # full filesystem dump (only if File System checked)
  fl_decrypted.dat     # the file-list metadata Write needs
  .checksums.md5       # baseline for change detection
```

Decrypted files are written with the `edata/` prefix stripped, so `…/edata/graphics/foo.png` lands at `graphics/foo.png` — [pipeline.py:267](../../pinball_decryptor/plugins/jjp/pipeline.py#L267).

## Write / repack pipeline

Exposed via `StandaloneModPipeline` wrapped by `_WriteWrapper` — [manufacturer.py:81](../../pinball_decryptor/plugins/jjp/manufacturer.py#L81). Phases `Scan → Extract → Prepare → Encrypt → Convert → Build ISO → Cleanup` — [pipeline.py:3611](../../pinball_decryptor/plugins/jjp/pipeline.py#L3611). (The `Convert`/`Build ISO` steps run only for ISO input; Direct-SSD skips them.)

**Scan** (`_phase_scan`, [pipeline.py:2198](../../pinball_decryptor/plugins/jjp/pipeline.py#L2198)): MD5 every tracked file in the assets folder against `.checksums.md5`; only differing files are written. Untracked siblings with a matching stem but a different extension (e.g. user dropped `song.mp3` next to `song.ogg`) are surfaced as a likely "format mismatch / Windows hid the extension" error. If nothing changed, the run ends early.

**Extract / Prepare:** re-extract the raw ext4 image from the ISO (cached), then `_phase_mount_rw` ([pipeline.py:3772](../../pinball_decryptor/plugins/jjp/pipeline.py#L3772)) prepares it for **debugfs** access — no actual mount; files are read/written in the image via `debugfs dump` / `rm` / `write`.

**Encrypt** (`_phase_encrypt_standalone`, [pipeline.py:4378](../../pinball_decryptor/plugins/jjp/pipeline.py#L4378)): the core of Write. `system/…` files are written verbatim via debugfs (no encryption — not in `fl.dat`). For each changed `edata` file:

1. Look up its `FileEntry` (`filler_size`, `n2`, `n3`) — fails loudly if no `fl_decrypted.dat` is present, since the CRCs are mandatory.
2. **Audio format-match** if `.wav`/`.ogg` (see [Audio](#audio-assets)).
3. `encrypt_file(content, filler_size, path, orig_n2, orig_n3)` — pure-Python CRC32 forgery — [crypto.py:176](../../pinball_decryptor/plugins/jjp/crypto.py#L176).
4. Round-trip verify: recompute `n2` (CRC of encrypted bytes) and `n3` (CRC of re-decrypted content) and require both to equal the originals; bail the file on mismatch.
5. `debugfs rm` then `debugfs write` the new bytes; verify the on-disk size.

### CRC32 forgery — why `fl.dat` is never rewritten

The game validates each asset against the **original** `n2`/`n3` in `fl.dat`. Rather than re-derive and re-sign `fl.dat` (which would require the dongle's `dongle_decrypt_buffer`/re-encrypt), Write forges the modified file so its checksums match the originals byte-for-byte — [crypto.py:176](../../pinball_decryptor/plugins/jjp/crypto.py#L176):

- **n3 forgery (content):** append 4 bytes to the plaintext so `CRC32(content + suffix) == orig_n3`. `crc32_forge_suffix` solves the 4 bytes via `_crc32_forge_4bytes` — [crypto.py:317](../../pinball_decryptor/plugins/jjp/crypto.py#L317).
- **n2 forgery (encrypted on disk):** build `[zero filler][content][n3 suffix]`, XOR-encrypt it, then adjust the **last 4 filler bytes** (positions `n1-4 .. n1-1`) so `CRC32(encrypted) == orig_n2`. Requires `filler_size >= 4` — [crypto.py:203](../../pinball_decryptor/plugins/jjp/crypto.py#L203).
- **The 4-byte solver** (`_crc32_forge_4bytes`, [crypto.py:279](../../pinball_decryptor/plugins/jjp/crypto.py#L279)) is **meet-in-the-middle**: enumerate all `(b0,b1)` forward into a table keyed by the intermediate CRC state, reverse two steps back from the target, and match — `O(2 × 256²)` instead of `2³²`. Standard reflected CRC-32 (poly `0xEDB88320`) with a reverse-lookup table `rev[tab[i]>>24]=i` for un-stepping.

Because both checksums are forged, `fl.dat` is left **completely untouched** — the encrypted bytes are crafted to satisfy it. The embedded-C encryptor even re-restores the original `fl.dat` bytes verbatim and samples 20 unmodified files to confirm the ext4 pipeline (journal/e2fsck) didn't perturb anything — [resources.py:960](../../pinball_decryptor/plugins/jjp/resources.py#L960).

### Tab-separated manifest

In the **embedded-C** (dongle) Write path the changed files are staged into the chroot and a manifest of `game_relative_path\treplacement_path` lines is written to `/tmp/jjp_manifest.txt` (env `JJP_MANIFEST`); the LD_PRELOAD'd encryptor reads it line by line — [pipeline.py:2449](../../pinball_decryptor/plugins/jjp/pipeline.py#L2449), parsed in `do_encrypt` — [resources.py:696](../../pinball_decryptor/plugins/jjp/resources.py#L696). The exposed pure-Python Standalone path does **not** use a manifest file — it iterates `changed_files` directly and calls `encrypt_file` in-process.

### ISO rebuild

**Convert** (`_phase_convert_standalone`, [pipeline.py:4797](../../pinball_decryptor/plugins/jjp/pipeline.py#L4797)): `e2fsck -fy` the modified image, then `partclone.ext4 -c` → `pigz`/`gzip` → `split` back into `sda3.ext4-ptcl-img.gz.*` chunks (split size matched to the original first chunk). **Build ISO** (`_phase_build_iso`, [pipeline.py:2879](../../pinball_decryptor/plugins/jjp/pipeline.py#L2879)): `xorriso -indev <orig> -outdev <new> -boot_image any replay` to clone the original ISO's boot structure (MBR/El Torito/EFI/Syslinux), then `-find … -exec rm` the old chunks and `-map` the new ones in. The result is verified to actually differ from the original partition data — [pipeline.py:3022](../../pinball_decryptor/plugins/jjp/pipeline.py#L3022).

### Output naming & install

Upstream writes `<assets_folder>/<iso_basename>_modified.iso`. `_WriteWrapper._move_output` then `shutil.move`s it to the user's chosen Output Folder (cross-drive safe), preferring the stashed `_output_iso_path` — [manufacturer.py:112](../../pinball_decryptor/plugins/jjp/manufacturer.py#L112). Install help: write the ISO to USB with Rufus (**ISO mode, not DD**) / Etcher, boot the machine from USB, let Clonezilla restore — [manufacturer.py:287](../../pinball_decryptor/plugins/jjp/manufacturer.py#L287), with linked JJP PDF instructions — [pipeline.py:3695](../../pinball_decryptor/plugins/jjp/pipeline.py#L3695).

## Audio assets

Audio lives loose under `edata/sound/` as `.wav` (effects/callouts, varying mono/stereo & 44.1k/48k) and `.ogg` Vorbis (song-select previews). `audio.py` does format detection + matching — [audio.py:1](../../pinball_decryptor/plugins/jjp/audio.py#L1).

During Write, before encryption, replacements are coerced to the **original** file's exact format and duration so the game accepts them:

- **WAV** (`_maybe_convert_audio`, [pipeline.py:3835](../../pinball_decryptor/plugins/jjp/pipeline.py#L3835)): read+decrypt the original from the image, compare `nchannels/sampwidth/framerate`. Pure-Python `convert_wav_python` handles bit-depth (8/24/32→target) and channel (mono↔stereo, multi→stereo/mono) changes — [audio.py:69](../../pinball_decryptor/plugins/jjp/audio.py#L69); sample-rate changes need ffmpeg (`needs_ffmpeg`) via `_convert_wav_ffmpeg`. Then `_resize_wav_to_duration` trims/pads to the original frame count (pure Python) — [pipeline.py:4033](../../pinball_decryptor/plugins/jjp/pipeline.py#L4033). Compressed-WAV codecs are routed through ffmpeg.
- **OGG** (`_maybe_convert_ogg`, [pipeline.py:4100](../../pinball_decryptor/plugins/jjp/pipeline.py#L4100)): parse the Vorbis identification header (`\x01vorbis`) for channels/sample-rate/bitrate — [audio.py:176](../../pinball_decryptor/plugins/jjp/audio.py#L176). Channel/rate mismatches are re-encoded with ffmpeg (`_convert_ogg_ffmpeg`); `_resize_ogg_to_duration` matches length. Magic-byte and header sanity checks guard against the user supplying a non-OGG file.

Duration matching can be disabled via `skip_duration_match` (pipeline ctor flag) — [pipeline.py:4041](../../pinball_decryptor/plugins/jjp/pipeline.py#L4041).

**Replace-Audio tab** complements this: because `replace_audio=True` and `audio_slot_dirs()` returns `None`, the tab scans the whole extract for loose `.wav`/`.ogg`, lets the user assign+preview a replacement per slot, and stages the assignment over the extracted file. The normal Write Scan then sees it as a changed file and the in-Write format-match above converts it on repack — so the user can drop in an arbitrary-format track and Write fixes the format/duration automatically.

## Other asset types

- **Graphics (PNG/JPG/WebM):** decrypted straight to `graphics/`; magic-byte filler detection in dongle-free mode (`_MAGIC_TABLE`) — [crypto.py:330](../../pinball_decryptor/plugins/jjp/crypto.py#L330). On Write they are size-warned (any size delta is logged) but not transformed — only CRC-forged.
- **Full filesystem dump (`system/`):** the entire ext4 tree minus `edata` and virtual dirs (`proc/sys/dev/run/tmp/lost+found`), copied via a `tar | tar` stream — game binary, shared libs, scripts, OS config, kernel modules. Unencrypted, not in `fl.dat`; on Write these are written back verbatim via debugfs (`_write_system_files_debugfs` / `_write_system_files_ssd`) — [pipeline.py:4617](../../pinball_decryptor/plugins/jjp/pipeline.py#L4617). System files are only change-tracked if Extract was run with **File System** checked (else they're untracked and Scan notes it).

## Direct-SSD

Read/write the physically-connected JJP game SSD with no ISO intermediate. `DirectSSDDecryptPipeline` subclasses the standalone Decrypt; `DirectSSDModPipeline` subclasses the standalone Mod — [pipeline.py:5227](../../pinball_decryptor/plugins/jjp/pipeline.py#L5227), [pipeline.py:7013](../../pinball_decryptor/plugins/jjp/pipeline.py#L7013). Factories: `make_direct_ssd_extract_pipeline` / `make_direct_ssd_write_pipeline` — [manufacturer.py:243](../../pinball_decryptor/plugins/jjp/manufacturer.py#L243).

**Device paths & enumeration:** drives are listed per-OS by `list_disk_devices` — Windows WMI (`Win32_DiskDrive`, boot disk excluded, **USB/external only**), macOS `diskutil`, Linux `lsblk` (**USB/removable only**) — [executor.py:583](../../pinball_decryptor/plugins/jjp/executor.py#L583). Device IDs: `\\.\PHYSICALDRIVEn` / `/dev/diskN` / `/dev/sdX`.

**Mount per OS** (`_mount_ssd`, [pipeline.py:6301](../../pinball_decryptor/plugins/jjp/pipeline.py#L6301)):
- **Windows** (`_mount_ssd_windows`, [pipeline.py:6115](../../pinball_decryptor/plugins/jjp/pipeline.py#L6115)): clean stale mounts, `Set-Disk -IsOffline $true` to release Windows drive-letter holds, then `wsl --mount "<device>" --partition N --type ext4` (with `--options ro` for Extract) for each candidate, finding the mount at `/mnt/wsl/<diskname>` and **content-verifying** `/jjpe/gen1` is present before committing; stale `ALREADY_MOUNTED` triggers a `wsl --shutdown` retry.
- **macOS** (Docker path): `diskutil unmountDisk`, then either **native debugfs** (Homebrew e2fsprogs) on the raw `/dev/rdiskNsM` device — no Docker, no partition copy — or fall back to copying the partition. Raw access needs root → elevated mode via osascript "with administrator privileges" (`_debugfs_run_elevated`, password cached once) — [pipeline.py:6328](../../pinball_decryptor/plugins/jjp/pipeline.py#L6328), [pipeline.py:1836](../../pinball_decryptor/plugins/jjp/pipeline.py#L1836).
- **Linux** (native): single pick + validate.

**Elevation:** Direct-SSD on **Windows requires Administrator** — both `Set-Disk -IsOffline` and `wsl --mount <physical drive>` fail elevation otherwise. `core/admin.py:is_admin()` gates the UI (warning banner + disabled buttons when not elevated); the standard "Run as administrator" flow is recommended over the kept-but-unwired `relaunch_as_admin` — [admin.py:1](../../pinball_decryptor/core/admin.py#L1). macOS uses the cached osascript admin prompt; Linux uses sudo/native root.

**Partition auto-discovery / override** (`_discover_partitions`, [pipeline.py:5767](../../pinball_decryptor/plugins/jjp/pipeline.py#L5767)): every partition is enumerated and logged (per-OS parsers `_parse_{windows,macos,linux}_partitions`, module-level + unit-tested). Auto-pick = **largest `linux`-fs partition** (game data dwarfs OS/boot); EFI/swap/MSR/NTFS are filtered out. A manual **"Force partition #"** field (`partition_override`) bypasses discovery entirely — [pipeline.py:5865](../../pinball_decryptor/plugins/jjp/pipeline.py#L5865). On Windows the mount loop tries candidates largest-Linux-first and content-verifies each (`_build_partition_candidates`, fixing the "Habo" bug where a smaller boot-Linux partition enumerated before the game slot).

**A/B partition layout:** JJP firmware can boot from either of two same-sized Linux slots. Same-sized peers (within 5%, >1 GB) are detected as `_ab_partitions` — [pipeline.py:5965](../../pinball_decryptor/plugins/jjp/pipeline.py#L5965). On **Write**, after the primary slot is updated, the same encrypt pass is replayed against each partner (`_mirror_writes_to_partner_slots_windows` on Windows; raw `/dev/rdiskNsM` debugfs on macOS) so both slots match regardless of which the firmware boots — [pipeline.py:7104](../../pinball_decryptor/plugins/jjp/pipeline.py#L7104), [pipeline.py:7376](../../pinball_decryptor/plugins/jjp/pipeline.py#L7376). The `_edata_is_populated` probe distinguishes the live slot (files at leaves) from an inactive skeleton slot (empty `graphics/`/`sound/`).

**Phase sets:** Direct Extract = `Mount → Decrypt → Cleanup`; Direct Write = `Scan → Mount → Encrypt → Cleanup` (no ISO Extract/Convert/Build) — [config.py:116](../../pinball_decryptor/plugins/jjp/config.py#L116). The native-debugfs Extract path uses `_phase_decrypt_native` (dump each file via debugfs, decrypt in-process) — [pipeline.py:5342](../../pinball_decryptor/plugins/jjp/pipeline.py#L5342).

**Safety:** `_PreventSystemSleep` keeps the host awake for the ~30-min run — [pipeline.py:18](../../pinball_decryptor/plugins/jjp/pipeline.py#L18). `_wrote_to_ssd` gates the post-run `e2fsck`/writeback so read-only Extract never fscks the drive. Cleanup brings the disk back online (`Set-Disk -IsOffline $false`) and unmounts — [pipeline.py:6009](../../pinball_decryptor/plugins/jjp/pipeline.py#L6009), [pipeline.py:6657](../../pinball_decryptor/plugins/jjp/pipeline.py#L6657). On success the user is told to eject + reinstall the SSD — **no USB flashing needed** — [pipeline.py:7128](../../pinball_decryptor/plugins/jjp/pipeline.py#L7128).

## Mod Pack / delta

`modpack=True`, `apply_delta=False`. There is no upstream incremental-update format; the "mod pack" is the plugin's own delta-ZIP for sharing edits:

- `export_mod_pack` — [pipeline.py:8211](../../pinball_decryptor/plugins/jjp/pipeline.py#L8211): MD5-diff the assets folder against `.checksums.md5`, ZIP only the changed files **plus `fl_decrypted.dat` and `.checksums.md5`** (the recipient needs `fl_decrypted.dat` for CRC forgery and the checksums to stack further mods).
- `import_mod_pack` — [pipeline.py:8308](../../pinball_decryptor/plugins/jjp/pipeline.py#L8308): extract the ZIP over an existing extract folder; the normal Write Scan then picks the changed files up.

`apply_delta()` is not implemented (raises `NotImplementedError` from the base class).

## Detection

`detect(path)` — [manufacturer.py:220](../../pinball_decryptor/plugins/jjp/manufacturer.py#L220): require a `.iso` extension, then `detect_iso_game` does a case-insensitive substring match of the basename against every game's `filename_prefixes` — [games.py:71](../../pinball_decryptor/plugins/jjp/games.py#L71). Returns a `Game` or `None`. This is filename-only — it does **not** crack the ISO open; the actual game folder is detected later from the mounted filesystem. JJP sits 5th in the registry's detect order, after the AES-magic plugins, which is fine since `.iso` is specific to it (and CGC/DP, which detect by content).

## Gotchas & non-obvious details

- **Two parallel code paths.** `config.py` and `pipeline.py` still carry the *original* dongle pipelines (`DecryptionPipeline` / `ModPipeline`, phases `Extract/Mount/Chroot/Dongle/Compile/Decrypt/Copy/Cleanup`) that LD_PRELOAD a runtime-compiled C hook into the real game binary (`al_install_system` override, `fm_process_filelist` patch) calling the genuine `jcrypt_*` / `dongle_decrypt_buffer` symbols — [resources.py:290](../../pinball_decryptor/plugins/jjp/resources.py#L290). These need a HASP dongle and are **not exposed** by the manufacturer. The shipped flow is entirely the **pure-Python `crypto.py`** reimplementation (Standalone + Direct-SSD). The embedded C in `resources.py` is effectively reference/legacy — but it documents the exact algorithm and the symbol mangling (`_Z27jcrypt_set_seeds_for_cryptoPKc`, `_Z13jcrypt_rand64v`, `_Z21dongle_decrypt_bufferPvj`).
- **`fl.dat` is never rewritten.** The single most important invariant: modified files are CRC-*forged* (n2 over filler tail, n3 over content suffix) so the original `fl.dat` still validates them. This dodges re-signing `fl.dat` (which needs the dongle's `dongle_decrypt_buffer`). See [CRC32 forgery](#crc32-forgery--why-fldat-is-never-rewritten).
- **Filler bytes are load-bearing twice.** The random prefix is (a) decrypted+stripped on Extract and (b) the place where the n2 forgery hides its 4 solver bytes on Write — so n2 forgery requires `filler_size >= 4` ([crypto.py:204](../../pinball_decryptor/plugins/jjp/crypto.py#L204)); the content gets +4 suffix bytes for n3, so the re-encrypted file is 4 bytes larger than the plaintext.
- **The path IS the key.** `set_seeds_for_crypto` hashes the file's absolute path — so a file decrypts correctly only under its real `/jjpe/gen1/<Game>/edata/...` path, and the crypto is game-independent (why unlisted `GAME_DB` titles still work).
- **`rand64` is little-endian.** Keystream words are emitted LE byte order; mismatching endianness silently corrupts every file.
- **Executor model.** All Linux tooling runs through `create_executor()` — WSL on Windows, a privileged Alpine **Docker** container on macOS (bind-mounting host paths under `/host`, cache dir as `/tmp`), native `sudo`/root on Linux — [executor.py:543](../../pinball_decryptor/plugins/jjp/executor.py#L543). `wsl.exe` emits UTF-16LE, decoded specially. WSL only sees drives present at WSL-start; a USB drive plugged in later silently writes into WSL's vfs unless `wsl --shutdown` (`check_path_accessible`) — [executor.py:190](../../pinball_decryptor/plugins/jjp/executor.py#L190).
- **debugfs, not mount, for Write.** The modified ext4 image is edited file-by-file via `debugfs rm`/`write` (no kernel mount of a writable image), with size-verify after each write and a final `e2fsck -fy`.
- **`/var/tmp`, not `/tmp`,** for the big raw image — systemd-tmpfiles-clean can delete `/tmp` files while they're still loop-mounted — [pipeline.py:577](../../pinball_decryptor/plugins/jjp/pipeline.py#L577).
- **Dongle-free metadata is reconstructed,** not decrypted: without a cached `fl_decrypted.dat`, fillers come from `detect_filler_size` heuristics, and the `n3` written into the regenerated `fl_decrypted.dat` is computed from the decrypted content (`n2` from the encrypted bytes) — [pipeline.py:272](../../pinball_decryptor/plugins/jjp/pipeline.py#L272).
- **`updater.py` is vestigial** — it points at the unified repo only to avoid the deprecated standalone `jjp-decryptor` feed misleading users — [updater.py:1](../../pinball_decryptor/plugins/jjp/updater.py#L1).

## Key files

- [manufacturer.py](../../pinball_decryptor/plugins/jjp/manufacturer.py) — `JJPManufacturer`: capabilities, phases, prereqs, detect, the four pipeline factories, and the `_ExtractWrapper`/`_WriteWrapper` adapters.
- [pipeline.py](../../pinball_decryptor/plugins/jjp/pipeline.py) — **~8,500 lines**, all pipelines: dongle `DecryptionPipeline`/`ModPipeline` (legacy), `StandaloneDecryptPipeline`/`StandaloneModPipeline` (shipped), `DirectSSDDecryptPipeline`/`DirectSSDModPipeline`, `RestoreToSSDPipeline`, partition parsers, mod-pack import/export, `check_prerequisites`, and the embedded `_DECRYPT_SCRIPT` template.
- [resources.py](../../pinball_decryptor/plugins/jjp/resources.py) — **the large embedded-C blobs** `DECRYPT_C_SOURCE` / `ENCRYPT_C_SOURCE` (and `STUB_C_SOURCE`): the LD_PRELOAD `fm_process_filelist` hook, `jcrypt_rand64` XOR, `dongle_decrypt_buffer` call, and the C implementation of the CRC32 meet-in-the-middle forgery. Compiled at runtime by the dongle pipelines only.
- [crypto.py](../../pinball_decryptor/plugins/jjp/crypto.py) — pure-Python port: BKDR hash, the LCG+xorshift+counter `PRNG`, `xor_keystream`, `decrypt_file`/`encrypt_file`, the CRC32 forgery (`_crc32_forge_4bytes`, `crc32_forge_suffix`), and dongle-free `detect_filler_size`.
- [filelist.py](../../pinball_decryptor/plugins/jjp/filelist.py) — `fl.dat` parser (`FileEntry`, `parse_fl_dat`), edata-prefix detection, `scan_edata_files`, `write_fl_dat`.
- [audio.py](../../pinball_decryptor/plugins/jjp/audio.py) — WAV/OGG header parsing, format match/diff, pure-Python WAV bit-depth/channel conversion.
- [games.py](../../pinball_decryptor/plugins/jjp/games.py) — `GAME_DB` + `detect_iso_game` (filename badge detection).
- [config.py](../../pinball_decryptor/plugins/jjp/config.py) — paths (`/jjpe/gen1`, `sda3`, `/home/partimag/img`), timeouts, all phase-label lists, `KNOWN_GAMES`, platform prereq names.
- [executor.py](../../pinball_decryptor/plugins/jjp/executor.py) — `CommandExecutor` (WSL/Native/Docker), `create_executor`, `to_exec_path`, `DiskInfo` + `list_disk_devices`, `find_usbipd`.
- [partclone_to_raw.py](../../pinball_decryptor/plugins/jjp/partclone_to_raw.py) — pure-Python partclone-v2 → raw ext4 reconstructor (the primary ISO→raw decoder).
- [wsl.py](../../pinball_decryptor/plugins/jjp/wsl.py) — thin backward-compat re-export shim over `executor.py`.
- [updater.py](../../pinball_decryptor/plugins/jjp/updater.py) — vestigial update-check stub.
- [core/admin.py](../../pinball_decryptor/core/admin.py) — `is_admin` / `relaunch_as_admin` gating Direct-SSD on Windows.

## Related docs

- [ap.md](ap.md), [pb.md](pb.md), [spooky.md](spooky.md), [bof.md](bof.md), [cgc.md](cgc.md) — sibling manufacturer plugins.
- Base plugin contract: [`core/registry.py`](../../pinball_decryptor/core/registry.py) (`Manufacturer`, `Capabilities`, `Game`, `InputSpec`).
