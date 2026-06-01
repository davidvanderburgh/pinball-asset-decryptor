# American Pinball (`ap`) — Architecture

> The `ap` plugin extracts and repacks American Pinball game-code update files (`*-gamecode_*.pkg`), which are AES-256-CBC-encrypted ZIP archives of the on-machine P-ROC / pyprocgame Python tree. Decryption uses a single static key recovered from `/usr/bin/pkgprocess` on the machine's restore images, shared across the entire 2020–2024 product line. The flow is pure-Python (pycryptodome for AES + stdlib `zipfile`) with no external tools, and supports both Extract (`.pkg` → folder) and Write (folder → `.pkg`), plus loose-file Replace-Audio. Its detector is **key-validated** and must load before Spooky, whose generic AES-magic fallback would otherwise claim AP packages.

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/ap/`
- **`key`:** `ap` — [manufacturer.py:17](../../pinball_decryptor/plugins/ap/manufacturer.py#L17)
- **`display`:** `American Pinball` — [manufacturer.py:18](../../pinball_decryptor/plugins/ap/manufacturer.py#L18)

### Supported games

All entries below decrypt with the single universal key, so every `GAME_DB` title is supported for Extract/Write. Titles are sourced from `GAME_DB` ([games.py:37](../../pinball_decryptor/plugins/ap/games.py#L37)); detection is by filename substring via `PKG_FILENAME_PATTERNS` ([games.py:84](../../pinball_decryptor/plugins/ap/games.py#L84)).

| key | display | supported? | notes |
|---|---|---|---|
| `houdini` | Houdini: Master of Mystery | yes | Key recovered from this title's restore image; 2021 package ZIP-verifies end-to-end |
| `oktoberfest` | Oktoberfest: Pinball on Tap | yes | Matches `oktoberfest` or `okto` |
| `hot_wheels` | Hot Wheels | yes | Matches `hotwheels` / `hot_wheels` / `hot-wheels` |
| `legends_of_valhalla` | Legends of Valhalla | yes | Matches `valhalla` / `lov` |
| `galactic_tank_force` | Galactic Tank Force | yes | Matches `galactic` / `gtf` / `tank` |
| `bbq` | Barry-O's BBQ | yes | 2024 title; nests under a top-level `bbq/` and adds `ApiLib/` + `apiav/`. Marketed name behind the `bbq` code name is unverified (referred to as "Barry-O's BBQ" in the RE notes) |

An unrecognized but key-valid `.pkg` is still claimed, surfaced as game key `ap_pkg` / display "American Pinball (.pkg)" with the note "detected via universal key" — [manufacturer.py:41](../../pinball_decryptor/plugins/ap/manufacturer.py#L41), [formats.py:47](../../pinball_decryptor/plugins/ap/formats.py#L47).

### Input extensions / `InputSpec`

`InputSpec(label="American Pinball game files", extensions=(".pkg",))` — [manufacturer.py:24](../../pinball_decryptor/plugins/ap/manufacturer.py#L24). Only `.pkg` is recognized; the Clonezilla `.iso` restore images are **not** wired up (see Mod Pack / delta / direct-SSD) — [formats.py:30](../../pinball_decryptor/plugins/ap/formats.py#L30).

### Capabilities

Declared at [manufacturer.py:20](../../pinball_decryptor/plugins/ap/manufacturer.py#L20):

- `extract=True` — decrypt + unzip a `.pkg` to a folder.
- `write=True` — re-zip + re-encrypt a modified folder into a new `.pkg`.
- `replace_audio=True` — surfaces the Replace-Audio tab; AP's audio is loose `.wav`/`.ogg` in the extract output.
- (`modpack`, `apply_delta`, `iso` all False; all other capability flags default False — no capture, transcribe, direct-SSD, asset filters, DMD decode, chain-deltas.)

### Prerequisites

**None** — `prerequisites = ()` ([manufacturer.py:33](../../pinball_decryptor/plugins/ap/manufacturer.py#L33)). The flow is pure-Python: pycryptodome (`Crypto.Cipher.AES`) for the cipher and stdlib `zipfile` for the archive. No `gpg`, `partclone`, `ffmpeg`, etc. required for the core extract/write path. (ffmpeg may be involved only when the optional Replace-Audio tab transcodes a non-matching replacement format — a shared `core` concern, not an `ap` prerequisite.)

### Phase labels

- Extract: `("Detect", "Decrypt", "Checksums", "Done")` — [manufacturer.py:30](../../pinball_decryptor/plugins/ap/manufacturer.py#L30)
- Write: `("Detect", "Scan", "Repack", "Done")` — [manufacturer.py:31](../../pinball_decryptor/plugins/ap/manufacturer.py#L31)

## Container & encryption format

AP game-code packages use the same length-prefixed AES-CBC container as Spooky's P-ROC titles — both descend from the `pkgprocess` helper shipped on their Linux game images (the well-known PyCrypto "encrypt a file in CBC chunks" recipe). See [AP_PKG_RE.md](../AP_PKG_RE.md) for the full reverse-engineering write-up.

### On-disk layout

```
offset 0    8 bytes    plaintext (ZIP) length   — uint64, little-endian
offset 8   16 bytes    AES-CBC IV               — random per file (os.urandom)
offset 24   N bytes    AES-256-CBC ciphertext   — space-padded to a 16-byte multiple
```

Total file size = `8 + 16 + roundup16(plaintext_length)`. There is **no magic number, signature, or MAC** anywhere — every byte is `8 + 16 + ciphertext`, so integrity rests entirely on key secrecy. The header is parsed in `decrypt_aes_pkg` with `struct.unpack("<Q", ...)` for the size and a 16-byte IV read — [crypto.py:36](../../pinball_decryptor/plugins/ap/crypto.py#L36).

### Cipher parameters

- **Algorithm:** AES-256-CBC (`AES.new(key, AES.MODE_CBC, iv)`) — [crypto.py:38](../../pinball_decryptor/plugins/ap/crypto.py#L38).
- **Key:** `b"2f5fc7a0cae8aaf63aef767ceb998b7f"` — `AP_AES_KEY` at [games.py:22](../../pinball_decryptor/plugins/ap/games.py#L22). **No key derivation.** `pkgprocess` passes the 32-character ASCII string *verbatim* to `AES.new`, so the 32 ASCII bytes **are** the key → AES-256 (not the 16 hex-decoded bytes). It is a single static key shared across the whole product line (byte-identical in `/usr/bin/pkgprocess` on the Houdini, Oktoberfest, and Hot Wheels restore images, and it also decrypts the 2024 BBQ package).
- **IV:** random per file, stored in the clear at offset 8. On encrypt it is `os.urandom(16)` — [crypto.py:72](../../pinball_decryptor/plugins/ap/crypto.py#L72).
- **Chunk size:** `AES_CHUNK_SIZE = 24 * 1024` (24 KiB), matching the original `pkgprocess` — [games.py:25](../../pinball_decryptor/plugins/ap/games.py#L25). 24 KiB is a multiple of 16, so only the final chunk can be short.

### Padding

CBC requires block-aligned data. `pkgprocess` **space-pads** (ASCII `0x20`) the final short chunk up to a 16-byte boundary; the 8-byte size prefix lets the consumer truncate it back. This plugin's encrypt mirrors that exactly — `chunk += b" " * (16 - len(chunk) % 16)` — [crypto.py:90](../../pinball_decryptor/plugins/ap/crypto.py#L90). On decrypt it never inspects padding; it simply `outfile.truncate(origsize)` to the declared plaintext length — [crypto.py:51](../../pinball_decryptor/plugins/ap/crypto.py#L51). (Note: Spooky's near-identical `encrypt_aes_pkg` pads with NUL bytes instead of spaces; AP matches `pkgprocess`'s space-padding. Because the receiver truncates to `origsize`, the pad byte value is functionally irrelevant — but AP stays byte-faithful to the original tool.)

### How the key was recovered (summary)

1. Blind analysis of a `.pkg`: ~7.997 bits/byte entropy after an 8-byte header whose first dword ≈ filesize and `(filesize − 24)` is a 16-byte multiple → AES-CBC with explicit IV + block padding.
2. The Clonezilla restore ISO was opened with `7z`; the `sda5` (root) partclone image was reconstructed to a raw ext4 image and read with Sleuth Kit. `sda4` mounts at `/game`, `sda5` at `/`.
3. `/usr/bin/pkgprocess` turned out to be a plaintext Python 2 script containing the algorithm and `PACKAGE_SIGNING_KEY`. The USB update handler (`/usr/bin/codeupdate`) copies `*-gamecode*.pkg` to `/game/tmp/` and runs `pkgprocess`, which decrypts → unzips → `mv` into `/game/<title>/`.

Full detail: [AP_PKG_RE.md](../AP_PKG_RE.md).

### Plaintext payload

The decrypted ZIP is the P-ROC / pyprocgame (SkeletonGame) game tree: e.g. `houdini.py`, `procgame/`, `assets/`, `config.yaml`. Newer titles (BBQ) nest under a top-level directory (`bbq/`) and add `ApiLib/` + `apiav/`. The machines run a Python 2 / pyprocgame stack on an Arch/Linux SSD ([games.py:31](../../pinball_decryptor/plugins/ap/games.py#L31)).

## Extract pipeline

`ExtractPipeline` ([pipeline.py:21](../../pinball_decryptor/plugins/ap/pipeline.py#L21)), a `BasePipeline` subclass ([core/pipeline_base.py:18](../../pinball_decryptor/core/pipeline_base.py#L18)). Phases map to the four `extract_phases` labels.

1. **Detect** (`_set_phase(0)`) — `detect_game(pkg_path)` ([pipeline.py:33](../../pinball_decryptor/plugins/ap/pipeline.py#L33)). On `None`, raises `PipelineError("Detect", …)`. Logs the resolved game name, any detection note, and the package size via `format_size`. Then `os.makedirs(output_dir, exist_ok=True)`.
2. **Decrypt** (`_set_phase(1)`) — decrypts to a temp ZIP `_ap_decrypted.zip` inside the output dir via `decrypt_aes_pkg` ([pipeline.py:55](../../pinball_decryptor/plugins/ap/pipeline.py#L55), [crypto.py:22](../../pinball_decryptor/plugins/ap/crypto.py#L22)). `decrypt_aes_pkg` validates the result by reading the first 4 bytes and requiring `PK\x03\x04`, raising `ValueError` on mismatch — the cheapest correctness check that the key fit ([crypto.py:53](../../pinball_decryptor/plugins/ap/crypto.py#L53)). A `ValueError` is rethrown as `PipelineError("Decrypt", …)`; the temp ZIP is removed on any failure. Then `extract_zip` unzips the archive into `output_dir` ([pipeline.py:72](../../pinball_decryptor/plugins/ap/pipeline.py#L72)); `ZipFile.extract` sanitizes member paths (strips leading slashes, rejects `..` traversal — [formats.py:58](../../pinball_decryptor/plugins/ap/formats.py#L58)). The temp ZIP is deleted in a `finally`.
3. **Checksums** (`_set_phase(2)`) — `generate_checksums(output_dir, …)` writes `.checksums.md5` next to the extracted tree, recording each non-dotfile's relative path + MD5 ([pipeline.py:83](../../pinball_decryptor/plugins/ap/pipeline.py#L83), [core/checksums.py:22](../../pinball_decryptor/core/checksums.py#L22)). This is the modding baseline used later by Write. Symlinks, dotfiles, and unreadable files are skipped.
4. **Done** (`_set_phase(3)`) — terminal `_done(True, …)` with the game name, output path, and file count.

### On-disk output layout

The extracted directory mirrors the ZIP exactly (the game tree, e.g. `procgame/`, `assets/`, top-level `houdini.py` / `config.yaml`, or a nested `bbq/` for newer titles), plus a single `.checksums.md5` manifest at the output root. There is no `manifest.json` or other AP-specific sidecar — the MD5 baseline is the only generated artifact.

## Write / repack pipeline

`WritePipeline` ([pipeline.py:98](../../pinball_decryptor/plugins/ap/pipeline.py#L98)). Takes the original `.pkg` (for game identification), the edited assets folder, and an output `.pkg` path. Phases map to `("Detect", "Scan", "Repack", "Done")`.

1. **Detect** (`_set_phase(0)`) — `detect_game(original_pkg)` to recover the display name (falls back to "American Pinball" if `None`); verifies `assets_dir` exists ([pipeline.py:111](../../pinball_decryptor/plugins/ap/pipeline.py#L111)).
2. **Scan** (`_set_phase(1)`) — **change detection** against `.checksums.md5`. `read_checksums(assets_dir)` loads the baseline; if empty, raises `PipelineError("Scan", …)` instructing the user to run Extract first. For each baseline entry it re-hashes the on-disk file (`md5_file`) and flags it as changed when the MD5 differs ([pipeline.py:121](../../pinball_decryptor/plugins/ap/pipeline.py#L121)). The changed list is logged (first 25 shown). If nothing changed, it logs that the output will be a faithful rebuild and proceeds anyway. Note: the change list is **informational** — repack always re-zips the *entire* current tree, not just changed files.
3. **Repack** (`_set_phase(2)`) — `create_zip(assets_dir, temp_zip)` builds a deflate ZIP of the whole folder, with files sorted by relative path and the `.checksums.md5` baseline **excluded** so it never lands inside the package ([pipeline.py:149](../../pinball_decryptor/plugins/ap/pipeline.py#L149), [formats.py:76](../../pinball_decryptor/plugins/ap/formats.py#L76)). Then `encrypt_aes_pkg(temp_zip, output_pkg)` re-encrypts with the same universal key (fresh random IV) into the final `.pkg` ([pipeline.py:155](../../pinball_decryptor/plugins/ap/pipeline.py#L155), [crypto.py:62](../../pinball_decryptor/plugins/ap/crypto.py#L62)). The temp ZIP (`<output>.tmp.zip`) is removed in a `finally`.
4. **Done** (`_set_phase(3)`) — logs output size; `_done(True, …)` with the install hint.

### Output naming

The output path is whatever the caller passes; the user is told to name it like the original — `<game>-gamecode_YYYY.MM.DD.pkg` ([pipeline.py:170](../../pinball_decryptor/plugins/ap/pipeline.py#L170)). Because the receiving machine never verifies a signature, a rebuilt package installs identically to an official one.

### Install instructions

From `write_install_help` ([manufacturer.py:62](../../pinball_decryptor/plugins/ap/manufacturer.py#L62)):

1. Copy the output `.pkg` to a USB drive formatted FAT32.
2. Name it like the original (`<game>-gamecode_YYYY.MM.DD.pkg`).
3. Insert the USB drive and run **CODE UPDATE** from the coin-door menu.
4. The machine decrypts, unzips, and reboots into the new code.

(On the machine, `/usr/bin/codeupdate` copies the `.pkg` to `/game/tmp/` and invokes `pkgprocess`, which decrypts → unzips → `mv` into `/game/<title>/` — see RE notes.)

## Audio assets

- **Formats / location:** AP audio ships as **loose `.wav` / `.ogg`** files inside the extracted game tree (typically under `assets/`). There is no indexed sound bank or container — files are real, individually-replaceable assets, which is exactly why `replace_audio=True` is set ([manufacturer.py:22](../../pinball_decryptor/plugins/ap/manufacturer.py#L22); rationale at [core/registry.py:105](../../pinball_decryptor/core/registry.py#L105)).
- **How Replace-Audio applies:** AP does **not** override `audio_slot_dirs`, so it returns the default `None` ([core/registry.py:283](../../pinball_decryptor/core/registry.py#L283)). The Replace-Audio tab therefore calls `scan_audio_slots(assets_dir, roots=None)`, which walks the **entire** extracted tree and lists every `.wav`/`.ogg` (skipping dot-folders and `*.stage.*` temp files) as a named slot ([core/audio_slots.py:77](../../pinball_decryptor/core/audio_slots.py#L77); GUI wiring at `gui/main_window.py:1393`). The user assigns a replacement per slot; `stage_replacement` transcodes it into the slot's native container (`.wav`→`.wav`, `.ogg`→`.ogg` are passthrough; other formats convert via ffmpeg) and writes it over the file in place ([core/audio_slots.py:119](../../pinball_decryptor/core/audio_slots.py#L119)).
- **Write repack:** because staging overwrites the file on disk, its MD5 diverges from the `.checksums.md5` baseline — so the normal Write pipeline detects it as changed and re-zips/re-encrypts it into the rebuilt `.pkg` with no AP-specific audio handling. Audio replacement is just ordinary file modification from the pipeline's point of view.

## Other asset types

The decrypted payload is the full P-ROC/pyprocgame source + asset tree. Beyond audio, this includes Python source (`*.py`, `procgame/`, `ApiLib/`/`apiav/` on newer titles), `config.yaml`, and image/video/font assets under `assets/`. The plugin treats all of these uniformly as opaque files: Extract writes them verbatim, the checksum baseline tracks them, and Write re-zips whatever is present. There is **no per-type decoding** (no DMD decode, no image/video transform) in the `ap` plugin — the GUI's generic edit tip mentions images (`.webp`) and video (`.ogv`) are directly editable as loose files, but those go through the same checksum-diff → re-zip path, not any AP-specific code.

## Mod Pack / delta / direct-SSD

**N/A.** `modpack=False`, `apply_delta=False`, `iso=False`, and no direct-SSD capability ([manufacturer.py:20](../../pinball_decryptor/plugins/ap/manufacturer.py#L20)). The plugin implements only `make_extract_pipeline` and `make_write_pipeline`.

One reserved/future item: the Clonezilla `.iso` full-restore images are recognized in `GAME_DB` only as `iso` filename hints and are explicitly **not** extractable — `detect_game` rejects any non-`.pkg` extension ([formats.py:30](../../pinball_decryptor/plugins/ap/formats.py#L30)). AP images store partitions as `sdaN.ext4-ptcl-img.gz.*` (partclone), unlike the raw `.dd-ptcl-img` images `core/clonezilla.py` currently handles, so a partclone→raw step would be needed first (cf. `jjp/partclone_to_raw.py`). This is tracked as a TODO in the RE notes, not implemented here.

## Detection

`detect_game(path)` ([formats.py:23](../../pinball_decryptor/plugins/ap/formats.py#L23)) → `_detect_pkg` ([formats.py:36](../../pinball_decryptor/plugins/ap/formats.py#L36)):

1. **Extension gate:** non-`.pkg` → `None`.
2. **Filename hint:** lowercased basename is matched against `PKG_FILENAME_PATTERNS` (ordered, first match wins). A hit immediately returns the mapped game with `format_type="aes_pkg"` ([formats.py:40](../../pinball_decryptor/plugins/ap/formats.py#L40), [games.py:84](../../pinball_decryptor/plugins/ap/games.py#L84)). This path does **not** decrypt — the filename is trusted to encode the right title — but the universal key works for all titles, so correctness doesn't depend on the name being right.
3. **Key-validated probe:** for an unknown name, `looks_like_ap_pkg(path)` confirms ownership before claiming ([formats.py:47](../../pinball_decryptor/plugins/ap/formats.py#L47), [crypto.py:98](../../pinball_decryptor/plugins/ap/crypto.py#L98)). The probe is cheap: it reads only `8 + 16 + 16` bytes, then (a) sanity-checks the declared `origsize` against `8 + 16 + roundup16(origsize) == filesize` (rejecting `origsize == 0` or any size mismatch), and (b) AES-decrypts just the first ciphertext block with the AP key and requires the result to start with `PK\x03\x04` ([crypto.py:121-129](../../pinball_decryptor/plugins/ap/crypto.py#L121)). A match returns a generic "American Pinball (.pkg)" `GameFile` with note "detected via universal key".

The plugin's `detect` wrapper ([manufacturer.py:35](../../pinball_decryptor/plugins/ap/manufacturer.py#L35)) maps the `GameFile` to a `Game` (using `ap_pkg` as the key when no specific title matched).

### Load-order subtlety vs Spooky

AP is registered **before** Spooky in `_PLUGIN_MODULES` ([core/registry.py:19-31](../../pinball_decryptor/core/registry.py#L19)), and `detect_manufacturer` returns the **first** plugin whose `detect` claims the path ([core/registry.py:385](../../pinball_decryptor/core/registry.py#L385)). This ordering is load-bearing:

- Spooky's `.pkg` detector falls back to a **magic-only** check: `detect_pkg_format_from_magic` returns `aes_pkg` whenever bytes `[4:8] == 0` (i.e. the high 32 bits of the little-endian size prefix are zero — true for essentially every real package) ([spooky/formats.py:96-101](../../pinball_decryptor/plugins/spooky/formats.py#L96)). It does **not** decrypt to verify the key, so it would happily claim an AP package as "Unknown Game (.pkg AES encrypted)".
- AP instead **key-probes** (decrypt the first block → expect `PK\x03\x04`), so it only ever claims files that genuinely decrypt with the AP key.

If Spooky loaded first, it would intercept AP packages with the wrong key and a useless display name. Putting AP first means the key-validated detector wins for true AP files; non-AP AES packages fail AP's probe and fall through to Spooky as before. This ordering and rationale are documented inline at [core/registry.py:20-23](../../pinball_decryptor/core/registry.py#L20) and in [AP_PKG_RE.md](../AP_PKG_RE.md).

## Gotchas & non-obvious details

- **Load order is mandatory** — AP must precede Spooky (above). Reordering would silently mis-detect AP packages.
- **The key is 32 ASCII bytes, not 16 hex bytes.** `b"2f5fc7a0cae8aaf63aef767ceb998b7f"` is used verbatim → AES-**256**. Treating it as hex (16 bytes → AES-128) would not decrypt anything ([games.py:22](../../pinball_decryptor/plugins/ap/games.py#L22)).
- **No integrity protection on the machine side.** There is no signature/MAC; a repacked `.pkg` installs exactly like an official one. Security relies entirely on the (now-published) key.
- **Padding byte differs from Spooky.** AP space-pads (matching `pkgprocess`); Spooky NUL-pads. Functionally identical because the receiver truncates to `origsize`, but AP stays byte-faithful.
- **Pure-Python, no external tools.** Only pycryptodome + stdlib. No `gpg`/`partclone`/`debugfs`. This is why `prerequisites = ()` and the install path is fully cross-platform.
- **Write re-zips the whole tree**, not a delta. The `.checksums.md5` diff is informational/logging only; the rebuilt ZIP contains every current file (minus the baseline file itself). With zero changes, Write still produces a valid faithful rebuild.
- **`.checksums.md5` is excluded from the repack** ([formats.py:85](../../pinball_decryptor/plugins/ap/formats.py#L85)) so the modding baseline never ships inside the package; it is also re-creatable only by re-running Extract (Write does not regenerate it).
- **Fresh random IV per encrypt** means a rebuilt package is never byte-identical to the original even with no asset changes (different IV + ZIP entry ordering/timestamps). Equivalence is semantic (same plaintext tree), not bitwise.
- **`.iso` restore images are recognized in metadata but not extractable** — partclone layout is unimplemented (TODO in RE notes).
- **`bbq` marketed title is unverified** — the code name "Barry-O's BBQ" is a working label.

## Key files

- [`pinball_decryptor/plugins/ap/__init__.py`](../../pinball_decryptor/plugins/ap/__init__.py) — `register()` entry point; instantiates and registers the manufacturer.
- [`pinball_decryptor/plugins/ap/manufacturer.py`](../../pinball_decryptor/plugins/ap/manufacturer.py) — `AmericanPinballManufacturer`: key/display, games, capabilities, `InputSpec`, phase labels, `detect`, pipeline factories, and the input/install help text.
- [`pinball_decryptor/plugins/ap/games.py`](../../pinball_decryptor/plugins/ap/games.py) — `AP_AES_KEY`, `AES_CHUNK_SIZE`, `GAME_DB`, and `PKG_FILENAME_PATTERNS`.
- [`pinball_decryptor/plugins/ap/crypto.py`](../../pinball_decryptor/plugins/ap/crypto.py) — `decrypt_aes_pkg`, `encrypt_aes_pkg`, and the key-validated `looks_like_ap_pkg` probe.
- [`pinball_decryptor/plugins/ap/formats.py`](../../pinball_decryptor/plugins/ap/formats.py) — `detect_game` / `_detect_pkg`, and the ZIP `extract_zip` / `create_zip` helpers.
- [`pinball_decryptor/plugins/ap/pipeline.py`](../../pinball_decryptor/plugins/ap/pipeline.py) — `ExtractPipeline` and `WritePipeline`.

Shared `core` modules this plugin relies on:

- [`pinball_decryptor/core/registry.py`](../../pinball_decryptor/core/registry.py) — `Manufacturer` base contract, `Capabilities`/`Game`/`InputSpec`, plugin load order, `detect_manufacturer`.
- [`pinball_decryptor/core/pipeline_base.py`](../../pinball_decryptor/core/pipeline_base.py) — `BasePipeline` / `PipelineError`.
- [`pinball_decryptor/core/checksums.py`](../../pinball_decryptor/core/checksums.py) — `generate_checksums` / `read_checksums` / `md5_file` and `CHECKSUMS_FILE`.
- [`pinball_decryptor/core/audio_slots.py`](../../pinball_decryptor/core/audio_slots.py) — `scan_audio_slots` / `stage_replacement` driving the Replace-Audio tab.

## Related docs

- [AP_PKG_RE.md](../AP_PKG_RE.md) — reverse-engineering notes: container format, padding scheme, static key recovery, and the plugin-mapping table.
