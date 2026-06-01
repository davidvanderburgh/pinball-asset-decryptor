# Pinball Brothers (`pb`) — Architecture

> Pinball Brothers ships four games (ABBA, Alien, Queen, Predator), all running custom C++ on FAST Pinball hardware. Their update format is the dead-simple `.upd` file: a **plain gzip+tar archive with no encryption** that the GUI extracts and repacks using nothing but the Python standard library. There is also an optional `.iso` path for the Alien/Queen Clonezilla restore images, which *does* need WSL + e2fsprogs/debugfs. Write is fully supported (untar → edit → re-tar with baseline-checksum change detection), and the plugin also exposes Mod Pack, Apply Delta, and Replace-Audio. The headline gotcha: there are two completely different extract code paths (`.upd` stdlib vs `.iso` Clonezilla), and the `.iso` path silently requires Linux tooling the `.upd` path never touches.

## At a glance

- **Plugin dir:** [`pinball_decryptor/plugins/pb/`](../../pinball_decryptor/plugins/pb/)
- **`key`:** `pb` — [manufacturer.py:19](../../pinball_decryptor/plugins/pb/manufacturer.py#L19)
- **`display`:** `Pinball Brothers` — [manufacturer.py:20](../../pinball_decryptor/plugins/pb/manufacturer.py#L20)

### Supported games

The game list is built from `GAME_DB` and sorted by display name — [manufacturer.py:11](../../pinball_decryptor/plugins/pb/manufacturer.py#L11), [games.py:12](../../pinball_decryptor/plugins/pb/games.py#L12).

| Game key | Display | Supported? | Notes |
|---|---|---|---|
| `abba` | ABBA | Yes (`.upd` only) | `internal_dir = game/abba`, prefix `pbap`; no `iso` block, so no Clonezilla path — [games.py:13](../../pinball_decryptor/plugins/pb/games.py#L13) |
| `alien` | Alien | Yes (`.upd` + `.iso`) | `internal_dir = game/alien`, prefix `pbap`; Clonezilla image `alien40`, partition `sda2` — [games.py:20](../../pinball_decryptor/plugins/pb/games.py#L20) |
| `queen` | Queen | Yes (`.upd` + `.iso`) | `internal_dir = game/queen`, prefix `pbq`; Clonezilla image `queen20d`, partition `sda2` — [games.py:32](../../pinball_decryptor/plugins/pb/games.py#L32) |
| `predator` | Predator | Yes (`.upd` only) | `internal_dir = opt/game`, prefix `pbpp`; no `iso` block — [games.py:44](../../pinball_decryptor/plugins/pb/games.py#L44) |

All four are marked supported (the `Game` objects are built without `supported=False`); `Game.supported` defaults to `True` — [registry.py:48](../../pinball_decryptor/core/registry.py#L48). Note `predator`'s `internal_dir` is `opt/game` (no game-name subfolder), unlike the others under `game/<name>`.

### Input extensions / `InputSpec`

```python
input_spec = InputSpec(label="PB game files", extensions=(".upd", ".iso"))
```

— [manufacturer.py:26](../../pinball_decryptor/plugins/pb/manufacturer.py#L26). The Extract tab's file dialog filters to `.upd` and `.iso`.

### Capabilities

Declared at [manufacturer.py:22](../../pinball_decryptor/plugins/pb/manufacturer.py#L22):

| Flag | Value | Meaning |
|---|---|---|
| `extract` | True | Extract tab is shown — untar a `.upd` (or extract a Clonezilla `.iso`). |
| `write` | True | Write tab is shown — repack a modified assets folder into a new `.upd`. |
| `modpack` | True | Mod Pack export/import (zip of changed-only files) is offered. |
| `apply_delta` | True | Apply-Delta tab — overlay a delta `.upd` onto an extracted folder. |
| `iso` | True | The input picker accepts `.iso` and routes to the Clonezilla pipeline. |
| `replace_audio` | True | Replace-Audio tab scans the extract for loose `.wav`/`.ogg` slots. |

All other capability flags (`capture`, `transcribe`, `direct_ssd`, `asset_filters`, `write_version_date`, `decode_dmd`, `chain_deltas`) default to **False** — [registry.py:52](../../pinball_decryptor/core/registry.py#L52). PB does **not** override `beta` or `badge`, so the picker card shows no special badge.

### Prerequisites

Declared at [manufacturer.py:32](../../pinball_decryptor/plugins/pb/manufacturer.py#L32):

| Tool | Where | Why |
|---|---|---|
| `debugfs` | `wsl` | Alien/Queen Clonezilla `.iso` extraction (probe `which debugfs`; install hint `apt-get install e2fsprogs` in WSL). |

This is the **only** declared `Prerequisite`, and it matters only for the `.iso` path. The `.upd` extract/write/delta paths are pure stdlib and have no prerequisites — the GUI's prereq indicator will show `debugfs` regardless, but a user only doing `.upd` work can ignore a red `debugfs`. The probe runs inside WSL via `wsl -u root -- bash -c 'which debugfs'` ([prereqs.py:143](../../pinball_decryptor/core/prereqs.py#L143)); on macOS/Linux the WSL probe returns a friendly "n/a (non-Windows)" pass ([prereqs.py:144](../../pinball_decryptor/core/prereqs.py#L144)).

The ISO pipeline does its **own** deeper prereq check at runtime via `clonezilla.check_prerequisites`, which verifies the executor backend plus `debugfs` and `gunzip` — [clonezilla.py:219](../../pinball_decryptor/core/clonezilla.py#L219), invoked from [pipeline.py:122](../../pinball_decryptor/plugins/pb/pipeline.py#L122).

### Phase labels

PB does not override `extract_phases` / `write_phases`, so it uses the core 4-step defaults ([config.py:8](../../pinball_decryptor/core/config.py#L8)):

- **Extract:** `Detect → Extract → Checksums → Cleanup` (`EXTRACT_PHASES`). Both `ExtractPipeline` and `IsoExtractPipeline` emit `_set_phase(0..3)` against this shape.
- **Write:** `Detect → Scan → Repack → Cleanup` (`WRITE_PHASES`).
- No capture / transcribe / direct-SSD phases (those capabilities are off).

## Container & file format

### `.upd` — gzip + tar (POSIX/GNU tar)

A PB `.upd` file is a **plain gzip-compressed tar archive** — there is no encryption, no custom header, no manufacturer wrapper. The module docstring states this outright: "PB `.upd` files are plain gzip+tar archives — no encryption" ([pipeline.py:3](../../pinball_decryptor/plugins/pb/pipeline.py#L3)).

- **Magic:** the file begins with the gzip magic `\x1f\x8b` (`GZIP_MAGIC`) — [formats.py:8](../../pinball_decryptor/plugins/pb/formats.py#L8). `is_upd_file()` reads the first two bytes and checks for exactly this — [formats.py:12](../../pinball_decryptor/plugins/pb/formats.py#L12). (Extension is not required for the content check; detection works on raw bytes.)
- **Container:** opened with `tarfile.open(path, "r:gz")` — standard Python gzip+tar. No segmentation, no custom block format.
- **On-disk layout (inside the tar):** members are normal POSIX file entries whose names begin with the game's `internal_dir`, optionally with a leading `./`. The detector normalises names by stripping a leading `./` and converting backslashes ([formats.py:75](../../pinball_decryptor/plugins/pb/formats.py#L75)). Example internal roots: `game/abba/…`, `game/alien/…`, `game/queen/…`, `opt/game/…` (Predator).
- **Write format:** when repacking, the output tar is written with `format=tarfile.GNU_FORMAT` ([pipeline.py:255](../../pinball_decryptor/plugins/pb/pipeline.py#L255)). The original may be POSIX or GNU; the repack standardises to GNU. Member mode/uid/gid/uname/gname/type are carried over from the source member for unchanged and changed files so permissions survive the round-trip.

The on-machine application of a `.upd` is performed by the pinball machine itself (coin-door GAME UPDATE menu); this tool only builds the artifact.

### `.iso` — Clonezilla restore image (Alien / Queen only)

The optional `.iso` input is a **Clonezilla restore ISO** (ISO 9660). It contains a `home/partimag/<image>/` directory holding a partclone image of the game's eMMC, split into gzip segments.

- **Magic:** ISO 9660 `CD001` at offset `0x8001` — `ISO9660_MAGIC` ([formats.py:9](../../pinball_decryptor/plugins/pb/formats.py#L9)); validated by `is_iso_file()` which seeks `0x8001` and reads 5 bytes ([formats.py:22](../../pinball_decryptor/plugins/pb/formats.py#L22)).
- **Inner structure** (handled by the shared `core/clonezilla.py`):
  - `home/partimag/<image_name>/` — the Clonezilla image dir (auto-discovered; `image_name` in `GAME_DB` is informational only) — [clonezilla.py:123](../../pinball_decryptor/core/clonezilla.py#L123).
  - `parts` — list of partition names in the image — [clonezilla.py:134](../../pinball_decryptor/core/clonezilla.py#L134).
  - `blkdev.list` — table with size/type/fstype used to pick the game (ext4) partition — [clonezilla.py:142](../../pinball_decryptor/core/clonezilla.py#L142).
  - `<partition>.dd-ptcl-img.gz.aa`, `.ab`, … — gzip-split partclone image of the ext4 partition.
- **Decompression:** the segments are concatenated and gunzipped into a raw `.img` (`cat <part>.dd-ptcl-img.gz.* | gunzip -c > /tmp/pad_raw.img`) — [clonezilla.py:319](../../pinball_decryptor/core/clonezilla.py#L319). Note: this gunzips the partclone container directly; the code does **not** invoke `partclone.restore` — it relies on `debugfs` being able to read the resulting image (see Gotchas).
- **File extraction:** `debugfs -R 'rdump "<subtree>" "<out>"'` pulls the game subtrees out of the ext4 image — [clonezilla.py:367](../../pinball_decryptor/core/clonezilla.py#L367). Subtrees default to `/game` and `/opt/game` ([pipeline.py:138](../../pinball_decryptor/plugins/pb/pipeline.py#L138), [games.py:30](../../pinball_decryptor/plugins/pb/games.py#L30)).

## Extract pipeline

Two pipeline classes; `make_extract_pipeline` picks by extension ([manufacturer.py:52](../../pinball_decryptor/plugins/pb/manufacturer.py#L52)): a `.iso` (case-insensitive suffix) routes to `IsoExtractPipeline`, everything else to `ExtractPipeline`.

### `ExtractPipeline` (`.upd` → folder) — [pipeline.py:23](../../pinball_decryptor/plugins/pb/pipeline.py#L23)

Phase by phase (the `_run` at [pipeline.py:32](../../pinball_decryptor/plugins/pb/pipeline.py#L32)):

1. **Phase 0 — Detect.** Calls `detect_game(upd_path)` ([pipeline.py:35](../../pinball_decryptor/plugins/pb/pipeline.py#L35)). On failure raises a `PipelineError("Detect", …)` that lists every known `internal_dir` so the user can see what was expected ([pipeline.py:37](../../pinball_decryptor/plugins/pb/pipeline.py#L37)).
2. **Phase 1 — Extract.** Opens `tarfile.open(upd_path, "r:gz")`, enumerates `getmembers()`, and extracts each member through `safe_member()` (path-traversal guard) ([pipeline.py:52](../../pinball_decryptor/plugins/pb/pipeline.py#L52)). Unsafe entries are logged and skipped; the rest are extracted with `set_attrs=True` (preserves mode/mtime). Progress is reported every 25 members ([pipeline.py:63](../../pinball_decryptor/plugins/pb/pipeline.py#L63)). Tar/EOF and "compressed file ended" errors are turned into a friendly *truncated download* message via `truncation_hint`, with a link to the PB support portal ([pipeline.py:65](../../pinball_decryptor/plugins/pb/pipeline.py#L65)).
3. **Phase 2 — Checksums.** `generate_checksums(output_dir, …)` walks the output and writes `.checksums.md5` ([pipeline.py:83](../../pinball_decryptor/plugins/pb/pipeline.py#L83)). Returns the count of files hashed.
4. **Phase 3 — Cleanup/Done.** Logs and calls `_done(True, summary)` with the output path and file count ([pipeline.py:87](../../pinball_decryptor/plugins/pb/pipeline.py#L87)).

**Output layout the user gets:** the tar's internal tree extracted verbatim under `output_dir` — e.g. `output_dir/game/alien/…` (or `output_dir/opt/game/…` for Predator), plus a `.checksums.md5` file at the **root** of `output_dir`. The checksum file is hidden-dotted and is itself excluded from future checksum runs (the walk skips names starting with `.` — [checksums.py:48](../../pinball_decryptor/core/checksums.py#L48)).

### `IsoExtractPipeline` (`.iso` → folder) — [pipeline.py:98](../../pinball_decryptor/plugins/pb/pipeline.py#L98)

`_run` at [pipeline.py:108](../../pinball_decryptor/plugins/pb/pipeline.py#L108). Constructs an executor via `create_executor()` ([pipeline.py:106](../../pinball_decryptor/plugins/pb/pipeline.py#L106)) — WSL on Windows, native on Linux, Mac on macOS.

1. **Phase 0 — Detect & prereqs.** `detect_iso_game(iso_path)` matches the filename against `filename_hints` ([pipeline.py:111](../../pinball_decryptor/plugins/pb/pipeline.py#L111)). Unknown → error listing recognised hints (`alien40`, `queen`). Then `clonezilla.check_prerequisites(executor)`; any missing tool aborts with WSL install instructions (`apt-get install -y e2fsprogs gzip`) ([pipeline.py:122](../../pinball_decryptor/plugins/pb/pipeline.py#L122)).
2. **Phase 1 — Extract.** Delegates to `clonezilla.extract(...)` passing `preferred_partition` and `subtrees` from the game's `iso` block ([pipeline.py:135](../../pinball_decryptor/plugins/pb/pipeline.py#L135)). That helper: mounts the ISO (loop, read-only) → finds `home/partimag/<image>` → picks the ext4 game partition (prefers `sda2`, else largest ext4) → concatenates+gunzips the partclone segments to `/tmp/pad_raw.img` → `debugfs rdump`s the `/game` and/or `/opt/game` subtrees into `output_dir` → unmounts. `RuntimeError`/`CommandError` are re-raised as `PipelineError("Extract", …)`.
3. **Phase 2 — Checksums.** Same `generate_checksums` as the `.upd` path ([pipeline.py:151](../../pinball_decryptor/plugins/pb/pipeline.py#L151)).
4. **Phase 3 — Done.** Summary notes the output is scoped to the game subtree(s); system files and symlinks are skipped ([pipeline.py:156](../../pinball_decryptor/plugins/pb/pipeline.py#L156)).

**Output layout:** `debugfs rdump "/game" "<out>"` writes the subtree's *contents* such that you get `output_dir/game/…` (and/or `output_dir/opt/game/…`), again with `.checksums.md5` at the root. The set of files mirrors what's on the running machine for those subtrees — note this is the **on-disk install layout**, which may differ from the `.upd`'s tar layout for the same game.

## Write / repack pipeline

`WritePipeline` ([pipeline.py:168](../../pinball_decryptor/plugins/pb/pipeline.py#L168)) takes `(original_upd, assets_dir, output_upd)`. The **original `.upd` is required** — it is the template the repack streams from, so unchanged members are copied byte-for-byte rather than re-derived from disk. `make_write_pipeline` just constructs it ([manufacturer.py:62](../../pinball_decryptor/plugins/pb/manufacturer.py#L62)).

`_run` ([pipeline.py:178](../../pinball_decryptor/plugins/pb/pipeline.py#L178)):

1. **Phase 0 — Detect.** `detect_game(original_upd)` to confirm the game and validate the assets folder exists ([pipeline.py:180](../../pinball_decryptor/plugins/pb/pipeline.py#L180)).
2. **Phase 1 — Scan (change detection).** `read_checksums(assets_dir)` loads the `.checksums.md5` baseline; **absence is a hard error** telling the user to run Extract first ([pipeline.py:196](../../pinball_decryptor/plugins/pb/pipeline.py#L196)). For each baseline entry still present on disk, it re-hashes (`md5_file`) and flags any whose digest differs as `changed` ([pipeline.py:203](../../pinball_decryptor/plugins/pb/pipeline.py#L203)). Up to 25 changed paths are logged. If nothing changed, the build proceeds anyway and the output is a byte-for-byte rebuild (a useful smoke test) ([pipeline.py:217](../../pinball_decryptor/plugins/pb/pipeline.py#L217)).
3. **Phase 2 — Repack.** `_repack(changed)` ([pipeline.py:245](../../pinball_decryptor/plugins/pb/pipeline.py#L245)) streams the original tar member-by-member into the new `w:gz` GNU-format tar:
   - **Changed regular file:** a fresh `TarInfo` is built with the new size/mtime but the **original** mode/uid/gid/uname/gname/type, then the on-disk file's bytes are added ([pipeline.py:262](../../pinball_decryptor/plugins/pb/pipeline.py#L262)). Matching is done on a normalised member name (`_norm_member_name`: strip leading `./`, backslashes → `/`) **and** a backslash-only alternate, so the baseline's `/`-separated keys line up with the tar's possibly-`./`-prefixed names ([pipeline.py:259](../../pinball_decryptor/plugins/pb/pipeline.py#L259), [pipeline.py:310](../../pinball_decryptor/plugins/pb/pipeline.py#L310)).
   - **Unchanged regular file:** copied straight from the source tar's stream ([pipeline.py:276](../../pinball_decryptor/plugins/pb/pipeline.py#L276)).
   - **Non-file members** (dirs, symlinks, etc.): the original `TarInfo` is re-added as-is ([pipeline.py:283](../../pinball_decryptor/plugins/pb/pipeline.py#L283)).
   - **Extra files** — anything on disk **not** in the original tar (e.g. files added by an Apply-Delta) is detected by `_find_extra_files` ([pipeline.py:314](../../pinball_decryptor/plugins/pb/pipeline.py#L314)) and appended. Dot-files and symlinks are skipped; new members get uid/gid 0, empty uname/gname, `REGTYPE`, and a mode guessed by `_guess_mode` ([pipeline.py:331](../../pinball_decryptor/plugins/pb/pipeline.py#L331)) — `0o755` for `pinprog`/`vidprog`/`*.sh` or anything the OS marks executable, else `0o644`. The new member name preserves the original tar's leading-`./` convention (`name_prefix`) ([pipeline.py:294](../../pinball_decryptor/plugins/pb/pipeline.py#L294)).
4. **Phase 3 — Cleanup/Done.** Reports the output size (`format_size`) and a summary with the modified-file count and install instructions ([pipeline.py:233](../../pinball_decryptor/plugins/pb/pipeline.py#L233)).

**Output naming:** entirely caller/UI-driven — `output_upd` is whatever path the GUI passed; the pipeline just `makedirs` the parent and writes there ([pipeline.py:226](../../pinball_decryptor/plugins/pb/pipeline.py#L226)). There is no auto-versioning or date-stamping (contrast BOF).

**Install instructions** shown in the UI come from `write_install_help()` ([manufacturer.py:77](../../pinball_decryptor/plugins/pb/manufacturer.py#L77)) and the done-summary ([pipeline.py:238](../../pinball_decryptor/plugins/pb/pipeline.py#L238)):
1. Copy the output `.upd` to a **FAT32** USB drive.
2. Insert it into the running machine.
3. Coin-door menu → GAME UPDATE → ENTER.
4. The machine reboots automatically when done.

> Note: PB's Write has **no checksum-newer gate** and no version field — unlike BOF, any modified `.upd` installs. The baseline `.checksums.md5` is used purely for change detection during repack; it is **not** rewritten by Write, and the machine does not consult it.

## Audio assets

PB audio assets are **loose `.wav` / `.ogg` files** living inside the game tree of the extract (e.g. somewhere under `game/<name>/…` or `opt/game/…`). PB does not override `audio_slot_dirs`, so it inherits the base behaviour of returning `None` ([registry.py:283](../../pinball_decryptor/core/registry.py#L283)) — meaning the **Replace-Audio tab scans the entire extract** for loose `.wav`/`.ogg`, rather than restricting to a curated slot directory. The registry comment explicitly lists Pinball Brothers among the loose-file plugins for which a whole-tree scan is correct ([registry.py:104](../../pinball_decryptor/core/registry.py#L104), [registry.py:288](../../pinball_decryptor/core/registry.py#L288)).

How the round-trip works:
1. Extract writes `.checksums.md5` covering every file (audio included).
2. The Replace-Audio tab lists each loose audio file as a slot and lets the user stage a format-matched replacement **over** the extracted file on disk.
3. Because the staged file's bytes now differ from the baseline MD5, the normal Write `Scan` phase flags it as `changed` and the `_repack` swaps it into the new `.upd` ([pipeline.py:203](../../pinball_decryptor/plugins/pb/pipeline.py#L203), [pipeline.py:262](../../pinball_decryptor/plugins/pb/pipeline.py#L262)).

There is **no audio decode/transcode in this plugin** — `transcribe` is off, and Replace-Audio relies on the user supplying a same-format track. The exact audio container/codec and on-machine directory naming are game-specific and not enumerated in code; the slot list is purely whatever loose `.wav`/`.ogg` the extract happens to contain *(specific subdirectory paths: unverified — not hard-coded in the plugin)*.

## Other asset types

The plugin is **format-agnostic** about non-audio assets — it treats the game tree as opaque files and never parses graphics, video, or data formats. There are no PB-specific decoders for images/video/DMD (no `decode_dmd`, no `.cdmd`-style handling here). Whatever the machine ships (textures, scripts, the `pinprog`/`vidprog` executables, config/data files) is extracted verbatim and repacked verbatim. The only place a *type* matters is `_guess_mode`, which keeps `pinprog`, `vidprog`, and `*.sh` executable when re-adding new files ([pipeline.py:331](../../pinball_decryptor/plugins/pb/pipeline.py#L331)) — implying those are the platform's launcher/runner binaries.

## Mod Pack / delta / direct-SSD

### Mod Pack — supported (`modpack=True`)

PB exposes Mod Pack via the capability flag; the actual logic is the **manufacturer-agnostic** `core/modpack.py`. `export_mod_pack` diffs the assets folder against `.checksums.md5` and zips **only changed files** (DEFLATE), preserving relative paths ([modpack.py:13](../../pinball_decryptor/core/modpack.py#L13)). `import_mod_pack` unzips a mod-pack into an assets folder ([modpack.py:46](../../pinball_decryptor/core/modpack.py#L46)). Export raises if there's no baseline or no changes. This is the portable "share just my edits" format; turning it into an installable `.upd` still requires running Write afterward.

### Apply Delta — supported (`apply_delta=True`)

`apply_delta(assets_folder, delta_upd_path, …)` ([pipeline.py:348](../../pinball_decryptor/plugins/pb/pipeline.py#L348)) untars a **delta `.upd`** (same gzip+tar format) on top of an already-extracted assets folder. Each member goes through `safe_member` (traversal guard) and is extracted with `set_attrs=True`. It tracks whether each target pre-existed (`os.path.lexists`) to report `(overwritten, added, total)` ([manufacturer.py:68](../../pinball_decryptor/plugins/pb/manufacturer.py#L68), [pipeline.py:378](../../pinball_decryptor/plugins/pb/pipeline.py#L378)). Crucially it **does not touch `.checksums.md5`** — so the delta's overlaid files read as modifications on the next Write and get folded into the output `.upd` (and any *new* files become "extras" appended by `_repack`) ([pipeline.py:391](../../pinball_decryptor/plugins/pb/pipeline.py#L391)).

### Direct-SSD — **N/A** (`direct_ssd=False`). PB has no direct-drive read/write path; the only "raw image" path is the read-only Clonezilla `.iso` extract.

### Chain-deltas-into-extract — **N/A** (`chain_deltas=False`). Deltas are applied via the separate Apply-Delta tab, not chained during extract.

## Detection

`PBManufacturer.detect(path)` ([manufacturer.py:39](../../pinball_decryptor/plugins/pb/manufacturer.py#L39)) branches on extension:

- **`.iso`** → `detect_iso_game(path)`: lowercases the **filename** and matches each game's `iso.filename_hints` as a substring ([formats.py:35](../../pinball_decryptor/plugins/pb/formats.py#L35)). Hints: `alien40`/`alien4` → alien; `queen10`/`queen20`/`queen` → queen ([games.py:28](../../pinball_decryptor/plugins/pb/games.py#L28), [games.py:40](../../pinball_decryptor/plugins/pb/games.py#L40)). (This is filename-only; the ISO9660 magic check in `is_iso_file` is available but `detect_iso_game` does not call it.)
- **Anything else** → `detect_game(path)` ([formats.py:48](../../pinball_decryptor/plugins/pb/formats.py#L48)), a **content-first** probe:
  1. `_detect_from_contents`: confirms gzip magic (`is_upd_file`), opens the tar, and scans up to **200** members; the first member whose normalised name starts with a game's `internal_dir` wins ([formats.py:65](../../pinball_decryptor/plugins/pb/formats.py#L65)). Names are normalised (strip `./`, backslashes → `/`) before comparison.
  2. **Fallback** `_detect_from_filename`: filename prefix `pbpp` → predator, `pbq` → queen ([formats.py:56](../../pinball_decryptor/plugins/pb/formats.py#L56)). (Note: ABBA/Alien's `pbap` prefix is **not** in this fallback — those rely on content detection. Predator/Queen are the only two with a filename fast-path.)

The returned `Game` carries `notes="Clonezilla ISO"` for `.iso` inputs (rendered as a badge), empty otherwise ([manufacturer.py:48](../../pinball_decryptor/plugins/pb/manufacturer.py#L48)).

PB is registered **first** in `_PLUGIN_MODULES` ([registry.py:20](../../pinball_decryptor/core/registry.py#L20)), so during auto-detect its `detect` runs before all others. Because its `.upd` detector is content-gated (requires gzip magic *and* a matching internal dir) and its `.iso` detector is filename-hint-gated, it won't grab unrelated archives.

## Gotchas & non-obvious details

- **Two extract code paths, very different requirements.** `.upd` is pure stdlib (gzip+tar) and works on any platform with zero external tools. `.iso` needs WSL + `e2fsprogs`/`debugfs` + `gzip` and can take *minutes* (the partclone image is gunzipped to a multi-GiB raw file in `/tmp`). A user only handling `.upd` files can ignore the `debugfs` prereq indicator entirely.
- **ISO path gunzips the partclone container directly** and reads it with `debugfs` — it does **not** run `partclone.restore` ([clonezilla.py:319](../../pinball_decryptor/core/clonezilla.py#L319)). This works because the underlying ext4 is readable from the (gunzipped) partclone payload for `debugfs rdump`'s purposes, but it's a non-obvious shortcut a maintainer expecting a full restore would miss. The raw image is dumped to `/tmp/pad_raw.img` and removed afterward ([clonezilla.py:383](../../pinball_decryptor/core/clonezilla.py#L383)).
- **Predator's `internal_dir` is `opt/game`**, not `game/predator` ([games.py:47](../../pinball_decryptor/plugins/pb/games.py#L47)) — easy to assume the `game/<name>` pattern holds for all four. It doesn't.
- **`pbap` prefix is shared** by ABBA and Alien, so it's deliberately **absent** from `_detect_from_filename` (it couldn't disambiguate) — those two depend on content detection ([formats.py:56](../../pinball_decryptor/plugins/pb/formats.py#L56)). If a `pbap` `.upd` is truncated/unreadable, content detection fails and there is no filename fallback for it.
- **Path-traversal safety:** every tar extraction (extract, apply-delta) routes members through `safe_member`, which rejects absolute paths, Windows drive letters, and `..` components ([tar_utils.py:6](../../pinball_decryptor/core/tar_utils.py#L6)). Repack does not call `safe_member` (it copies trusted original members and disk files), but `_find_extra_files` skips symlinks and dot-files ([pipeline.py:318](../../pinball_decryptor/plugins/pb/pipeline.py#L318)).
- **Checksum file format flavour:** `.checksums.md5` is **`<rel_path>\tab<md5>`** per line, `/`-separated paths, UTF-8 — a *tab-separated* custom format, **not** the GNU `md5sum` two-space format ([checksums.py:71](../../pinball_decryptor/core/checksums.py#L71), [checksums.py:91](../../pinball_decryptor/core/checksums.py#L91)). Don't hand-edit it with `md5sum` output.
- **Write requires the original `.upd`.** It is the streaming template; you cannot rebuild from the assets folder alone. Unchanged files are copied from the original tar, so the round-trip is byte-stable for untouched members.
- **Name normalisation mismatch is handled, not assumed.** The baseline keys are `/`-separated and `./`-stripped, but tar member names may carry `./`. `_repack` checks both the normalised name and a backslash-only alternate to match changed files ([pipeline.py:259](../../pinball_decryptor/plugins/pb/pipeline.py#L259)). Extras re-add with the original tar's leading-`./` convention so the machine sees consistent paths.
- **Empty diff still builds.** A Write with no modifications produces a valid byte-for-byte `.upd` rather than erroring ([pipeline.py:217](../../pinball_decryptor/plugins/pb/pipeline.py#L217)) — handy as a smoke test, but means "build succeeded" doesn't imply "I changed something."
- **Apply-Delta intentionally leaves the baseline stale** so deltas surface as modifications on the next Write ([pipeline.py:391](../../pinball_decryptor/plugins/pb/pipeline.py#L391)). If you regenerate checksums after a delta, those changes would no longer be detected.
- **Executable bit heuristic** for *newly-added* files only covers `pinprog`/`vidprog`/`*.sh`/OS-executable ([pipeline.py:331](../../pinball_decryptor/plugins/pb/pipeline.py#L331)). A new executable with a different name on a Windows host (no exec bit) would be packed `0o644` and might not run on the machine.
- **ISO detection is filename-only.** Rename a Queen ISO to something without `queen`/`queen10`/`queen20` and `detect_iso_game` returns `None` even though the bytes are a valid Clonezilla image.

## Key files

- [`pinball_decryptor/plugins/pb/__init__.py`](../../pinball_decryptor/plugins/pb/__init__.py) — plugin entry point; `register()` adds `PBManufacturer` to the registry.
- [`pinball_decryptor/plugins/pb/manufacturer.py`](../../pinball_decryptor/plugins/pb/manufacturer.py) — the `Manufacturer` subclass: capabilities, input spec, prereqs, `detect`, pipeline factories, and UI help text.
- [`pinball_decryptor/plugins/pb/games.py`](../../pinball_decryptor/plugins/pb/games.py) — `GAME_DB`: per-game `internal_dir`, filename prefixes, platform, and Clonezilla `iso` blocks.
- [`pinball_decryptor/plugins/pb/formats.py`](../../pinball_decryptor/plugins/pb/formats.py) — magic checks (`is_upd_file`, `is_iso_file`) and detection (`detect_game`, `detect_iso_game`).
- [`pinball_decryptor/plugins/pb/pipeline.py`](../../pinball_decryptor/plugins/pb/pipeline.py) — `ExtractPipeline`, `IsoExtractPipeline`, `WritePipeline`, and `apply_delta`.

Shared core modules this plugin leans on:
- [`core/registry.py`](../../pinball_decryptor/core/registry.py) — `Manufacturer`/`Capabilities`/`Game`/`InputSpec` base contract.
- [`core/pipeline_base.py`](../../pinball_decryptor/core/pipeline_base.py) — `BasePipeline` callback contract and `PipelineError`.
- [`core/checksums.py`](../../pinball_decryptor/core/checksums.py) — `.checksums.md5` generate/read (tab-separated).
- [`core/tar_utils.py`](../../pinball_decryptor/core/tar_utils.py) — `safe_member`, `truncation_hint`, `format_size`.
- [`core/clonezilla.py`](../../pinball_decryptor/core/clonezilla.py) — all the `.iso` mount/partclone/debugfs logic.
- [`core/modpack.py`](../../pinball_decryptor/core/modpack.py) — mod-pack zip export/import.
- [`core/prereqs.py`](../../pinball_decryptor/core/prereqs.py) — `Prerequisite` + host/WSL probing.
- [`core/executor.py`](../../pinball_decryptor/core/executor.py) — `create_executor()` (WSL/Native/Mac) used by the ISO path.
- [`core/config.py`](../../pinball_decryptor/core/config.py) — default `EXTRACT_PHASES` / `WRITE_PHASES`.

## Related docs

- [Project README](../../README.md) — PB summary row ([README.md:69](../../README.md#L69)), prereqs table ([README.md:338](../../README.md#L338)), and "add a manufacturer" guide that uses `plugins/pb/` as the reference template ([README.md:435](../../README.md#L435)).
- [`docs/AP_PKG_RE.md`](../AP_PKG_RE.md) and [`docs/CGC_BNK_RE.md`](../CGC_BNK_RE.md) — sibling format reverse-engineering notes (other plugins; useful for contrast). PB has no comparable RE doc because its `.upd` format needs none (plain gzip+tar).
