# Spooky Pinball (`spooky`) — Architecture

> The `spooky` plugin handles the widest format spread of any manufacturer in the app: six distinct file extensions, four encryption/signing schemes (AES-256-CBC, GPG symmetric, GPG signed, plus plaintext), two game engines (Unity and Godot 4), Ben Heck's P3/Multimorphic DMD video format, and Clonezilla disk-image restore archives. Most of its load-bearing decoders are **byte-for-byte lifts** from the standalone `spooky_decryptor` repo (a regression firewall enforced by [`tests/verify_no_upstream_regression.py`](../../tests/verify_no_upstream_regression.py)); only `formats.py` and `pipeline.py` are re-orchestrated for the unified `BasePipeline` contract. Extract decrypts/decompresses any supported input to a folder of loose assets (+ engine-specific PCK/asset extraction); Write re-encrypts a modified folder back into an installable machine-update file.

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/spooky/`
- **Key / display:** `spooky` / "Spooky Pinball" — [manufacturer.py:31-32](../../pinball_decryptor/plugins/spooky/manufacturer.py#L31)
- **Registration:** [`__init__.py`](../../pinball_decryptor/plugins/spooky/__init__.py) calls `register_manufacturer(SpookyManufacturer())`; load order in [registry.py:19-31](../../pinball_decryptor/core/registry.py#L19) places `spooky` **after** `ap` (see [Detection](#detection)).

### Supported games

Game DB lives in [games.py:52-123](../../pinball_decryptor/plugins/spooky/games.py#L52). `supported=False` is set only for Total Nuclear Annihilation ([manufacturer.py:14-27](../../pinball_decryptor/plugins/spooky/manufacturer.py#L14)).

| key | display | supported? | engine / format | notes |
|---|---|---|---|---|
| `rick_and_morty` | Rick and Morty | yes | P-ROC / pyprocgame, `rm_pkg` (AES) | also raw-ext4 Clonezilla path |
| `evil_dead` | Evil Dead | yes | Warden, `tar_gz` (`.ed`) | plain tar.gz |
| `scooby_doo` | Scooby-Doo | yes | Unity, `tar_gz` (`.scooby`) | |
| `beetlejuice` | Beetlejuice | yes | Unity, `gpg_tar_gz` (`.beetlejuice`) | GPG-**signed** (not encrypted) |
| `texas_chainsaw` | Texas Chainsaw Massacre | yes | Unity, `tar_gz` (`tcm-*.pkg`) | |
| `alice_cooper` | Alice Cooper's Nightmare Castle | yes | P-ROC, `ac_pkg` (AES) | key known |
| `total_nuclear` | Total Nuclear Annihilation | **no** | P-ROC, `aes_pkg` | AES-256-CBC key unknown; no Clonezilla image either |
| `halloween_78` | Halloween | yes | Unity, `h78_pkg` (GPG symmetric) | |
| `ultraman` | Ultraman | yes | Unity, `um_pkg` (GPG symmetric) | |
| `americas_most_haunted` | America's Most Haunted | yes | P3 DMD, `plain_zip` | `.VID` 4bpp |
| `rob_zombie` | Rob Zombie's Spookshow International | yes | P3 DMD, `plain_zip` | `.VID` 8bpp |
| `dominos` | Domino's Spectacular Pinball Adventure | yes | P3 DMD, `plain_zip` | `.VID` 8bpp |
| `jetsons` | Jetsons | yes | P3 DMD, `plain_zip` | `.VID` 8bpp interleaved |
| `legends_of_tera` | Looney Tunes | yes | Godot 4.1.3, `plain_tar` (`.looney`) | PCK embedded in ELF |

Note the key/display mismatch for Looney Tunes: the internal key is `legends_of_tera`, display "Looney Tunes" ([games.py:118](../../pinball_decryptor/plugins/spooky/games.py#L118)).

### Input extensions / InputSpec

[manufacturer.py:38-42](../../pinball_decryptor/plugins/spooky/manufacturer.py#L38): label "Spooky game files", extensions `.pkg .ed .scooby .beetlejuice .looney .iso .zip`.

### Capabilities

[manufacturer.py:34-37](../../pinball_decryptor/plugins/spooky/manufacturer.py#L34):

- `extract=True` — decrypt/decompress to a loose-asset folder.
- `write=True` — re-pack a modified folder into an installable update file.
- `modpack=True` — Mod Pack tab is exposed (see [Mod Pack](#mod-pack--delta--direct-ssd)).
- `iso=True` — input picker accepts `.iso` (Clonezilla restore images).
- `replace_audio=True` — "Replace Audio" tab scans the extract for loose `.wav`/`.ogg` slots.
- `apply_delta=False` — no delta-merge path.

### Prerequisites

[manufacturer.py:49-70](../../pinball_decryptor/plugins/spooky/manufacturer.py#L49). Host tools are invoked directly via `subprocess`; WSL tools only matter for the Clonezilla path.

| tool | where | why | probe |
|---|---|---|---|
| `gpg` | host | UM/H78 `.pkg` decrypt + Beetlejuice signing | `gpg --version` |
| `ffmpeg` | host | audio resampling + P3 VID→MP4 | `ffmpeg -version` |
| `partclone` | wsl | Clonezilla restore-image extraction | `which partclone.ext4` |
| `debugfs` | wsl | ext4 filesystem extraction | `which debugfs` |
| `zstd` | wsl | zstd-compressed Clonezilla images (BJ, LT) | `which zstd` |

(`gpg`/`ffmpeg` are also probed/located internally by [gpg.py:27](../../pinball_decryptor/plugins/spooky/gpg.py#L27) and [audio.py:35](../../pinball_decryptor/plugins/spooky/audio.py#L35) / [p3_video.py:63](../../pinball_decryptor/plugins/spooky/p3_video.py#L63) with extra fallback search paths.)

### Phase labels

- **Extract:** `Detect → Decrypt → Checksums → Done` ([manufacturer.py:45](../../pinball_decryptor/plugins/spooky/manufacturer.py#L45)).
- **Write:** `Detect → Scan → Repack → Done` ([manufacturer.py:46](../../pinball_decryptor/plugins/spooky/manufacturer.py#L46)).

Phase indices `phase(0..3)` are emitted by the pipelines; the pipeline comments reference the core default labels ("Decrypt"/"Cleanup") but the plugin's own labels above are what render in the GUI.

## Container & format(s)

Format detection produces a `format_type` string ([formats.py:23](../../pinball_decryptor/plugins/spooky/formats.py#L23), table in [games.py:40-50](../../pinball_decryptor/plugins/spooky/games.py#L40)). The handlers are dispatched on it in both pipelines.

### AES-256-CBC `.pkg` (`rm_pkg`, `ac_pkg`, `aes_pkg`)

Custom binary container — **not** a standard format ([crypto.py:17-55](../../pinball_decryptor/plugins/spooky/crypto.py#L17)):

```
[ 8 bytes ] original plaintext size — little-endian uint64
[16 bytes ] AES-256-CBC IV
[ N bytes ] AES-256-CBC ciphertext of a ZIP archive
```

Decrypt streams in 24 KiB chunks ([games.py:21](../../pinball_decryptor/plugins/spooky/games.py#L21) `AES_CHUNK_SIZE`), then `truncate(origsize)` to drop the CBC padding. Plaintext is validated against the ZIP local-file magic `PK\x03\x04` ([crypto.py:50-55](../../pinball_decryptor/plugins/spooky/crypto.py#L52)). Encrypt zero-pads the final block to 16 bytes ([crypto.py:84-86](../../pinball_decryptor/plugins/spooky/crypto.py#L85)). Keys are embedded constants recovered from on-disk `pkgprocess` scripts:

- `RM_AES_KEY` (Rick & Morty) — an ASCII passphrase, 32 bytes ([games.py:14](../../pinball_decryptor/plugins/spooky/games.py#L14)).
- `AC_AES_KEY` (Alice Cooper) — 32-byte hex-looking ASCII ([games.py:18](../../pinball_decryptor/plugins/spooky/games.py#L18)).
- `total_nuclear` uses the same container shape but its key is unknown → `aes_pkg` → unsupported. `AES_KEYS` only maps `rm_pkg`/`ac_pkg` ([crypto.py:11-14](../../pinball_decryptor/plugins/spooky/crypto.py#L11)).

### GPG symmetric `.pkg` (`um_pkg`, `h78_pkg`)

Password-encrypted tar.gz produced by `gpg --passphrase=… -c` on the machine ([gpg.py:460-591](../../pinball_decryptor/plugins/spooky/gpg.py#L460)). Decrypt/encrypt shell out to the host `gpg` binary in a throwaway `--homedir` temp dir; encrypt pins `--cipher-algo AES256 --s2k-digest-algo SHA256 --s2k-mode 3` ([gpg.py:557-560](../../pinball_decryptor/plugins/spooky/gpg.py#L557)). Output validated against gzip magic `\x1f\x8b`. Passphrases are string constants recovered from `Assembly-CSharp.dll` on the Clonezilla images ([games.py:25-31](../../pinball_decryptor/plugins/spooky/games.py#L25)).

### GPG-signed `.beetlejuice` (`gpg_tar_gz`)

A tar.gz wrapped in a GPG **signed** (not encrypted) message — extractable without any private key. Packet structure ([gpg.py:1-16](../../pinball_decryptor/plugins/spooky/gpg.py#L1)):

```
Compressed Data (tag 8, algo 1 = raw DEFLATE) wrapping:
  One-Pass Signature (tag 4)
  Literal Data (tag 11)  ← the tar.gz payload
  Signature (tag 2)
```

- **Extract** strips the framing via `gpg --decrypt` if available, else a hand-rolled OpenPGP packet parser that raw-inflates the compressed packet and pulls out the Literal Data body ([gpg.py:43-296](../../pinball_decryptor/plugins/spooky/gpg.py#L43); `_strip_manual`).
- **Write** re-signs with a *throwaway* RSA-2048 key in a temp homedir ([gpg.py:322-379](../../pinball_decryptor/plugins/spooky/gpg.py#L322)). The BJ machine shows "GPG SIGNATURE VERIFICATION FAILED" but lets the operator click **AGREE** to proceed, because `gpg -d` extracts regardless of signature validity. If key-gen fails (e.g. Git-bundled GPG on Windows), it falls back to `_sign_manual`, which builds the packet structure by hand with a dummy signature ([gpg.py:382-457](../../pinball_decryptor/plugins/spooky/gpg.py#L382)). `BJ_GPG_KEYID` is recorded but only informational ([games.py:34](../../pinball_decryptor/plugins/spooky/games.py#L34)).

### Plain archives (`tar_gz`, `plain_tar`, `plain_zip`)

No crypto. `.ed`/`.scooby`/TCM are plain tar.gz; `.looney` is a plain (uncompressed) tar; P3 update ZIPs are plain ZIP. Archive helpers in [formats.py:135-227](../../pinball_decryptor/plugins/spooky/formats.py#L135) — tar extraction has path-traversal guards ([formats.py:157-160](../../pinball_decryptor/plugins/spooky/formats.py#L157)); ZIP create uses `ZIP_DEFLATED`.

### Clonezilla restore images (`clonezilla`)

`.iso` (always), or `.zip`/`.iso` whose archive contains `partimag`/`ptcl-img` members ([formats.py:120-128](../../pinball_decryptor/plugins/spooky/formats.py#L120)). These hold `partclone` partition images (gzip- or zstd-compressed), or a bare ext4 filesystem for the R&M autoflash ISO. Partition layouts per game/hardware-variant in [clonezilla.py:35-172](../../pinball_decryptor/plugins/spooky/clonezilla.py#L35) (`PARTITION_MAP`); see [Extract pipeline → Clonezilla](#clonezilla-path).

### Engine containers

- **Unity** (Beetlejuice, Scooby, TCM, Halloween, Ultraman) — assets in `main_Data/*.assets` with companion `.resS`/`.resource` blobs; extracted via UnityPy ([unity.py](../../pinball_decryptor/plugins/spooky/unity.py)).
- **Godot 4.1.3** (Looney Tunes) — a ~953 MB unencrypted PCK appended to the `main.x86_64` ELF; PCK v2 header is 100 bytes with a 12-byte trailer at EOF ([godot.py:24-106](../../pinball_decryptor/plugins/spooky/godot.py#L24)).
- **P3 `.VID`** — 512-byte header + frames, 4bpp monochrome or 8bpp RGB332 ([p3_video.py:1-41](../../pinball_decryptor/plugins/spooky/p3_video.py#L1)).

## Extract pipeline

`ExtractPipeline` ([pipeline.py:65-536](../../pinball_decryptor/plugins/spooky/pipeline.py#L65)). The shared `_BasePipeline` wraps the unified `BasePipeline` with short callback aliases and a `threading.Event` cancel that can be handed to helpers ([pipeline.py:35-58](../../pinball_decryptor/plugins/spooky/pipeline.py#L35)).

**Phase 0 — Detect** ([pipeline.py:77-103](../../pinball_decryptor/plugins/spooky/pipeline.py#L77)): `detect_game()` returns a `GameFile`; `clonezilla` branches to `_run_clonezilla`; `aes_pkg` (TNA) fails fast with a "use the Clonezilla image instead" message ([pipeline.py:157-164](../../pinball_decryptor/plugins/spooky/pipeline.py#L157)).

**Phase 1 — Decrypt** ([pipeline.py:108-137](../../pinball_decryptor/plugins/spooky/pipeline.py#L108)): dispatch on `format_type` to a handler that writes a `_temp_*` intermediate into `output_dir`, then extracts it and deletes the temp in a `finally`:

- `rm_pkg`/`ac_pkg` → `_extract_aes_pkg` (decrypt to `_temp_decrypted.zip`, then `extract_zip`) — [pipeline.py:166-195](../../pinball_decryptor/plugins/spooky/pipeline.py#L166).
- `um_pkg`/`h78_pkg` → `_extract_gpg_symmetric_pkg` (decrypt to `_temp_decrypted.tar.gz`, then `extract_tar_gz`) — [pipeline.py:197-224](../../pinball_decryptor/plugins/spooky/pipeline.py#L197).
- `tar_gz`/`plain_tar` → `_extract_tar_gz` (direct) — [pipeline.py:226-234](../../pinball_decryptor/plugins/spooky/pipeline.py#L226).
- `gpg_tar_gz` → `_extract_gpg_tar_gz` (strip GPG signature to `_temp_stripped.tar.gz`, then extract) — [pipeline.py:236-261](../../pinball_decryptor/plugins/spooky/pipeline.py#L236).
- `plain_zip` → `_extract_plain_zip` (direct) — [pipeline.py:263-271](../../pinball_decryptor/plugins/spooky/pipeline.py#L263).

Then **engine-specific loose-asset extraction** ([pipeline.py:130-137](../../pinball_decryptor/plugins/spooky/pipeline.py#L130)): if the game is in `UNITY_GAMES` → walk for a `main_Data/` dir with `.assets` and run UnityPy; if in `GODOT_GAMES` → walk for `main.x86_64` and parse its PCK; if `convert_vids` **and** in `P3_GAMES` → convert `.VID`→MP4.

> **`convert_vids` defaults to `False`** ([pipeline.py:68](../../pinball_decryptor/plugins/spooky/pipeline.py#L68)) and `app.py` does **not** pass it to `make_extract_pipeline` ([app.py:525](../../pinball_decryptor/app.py#L525)), so P3 VID→MP4 conversion is wired but **off in the GUI** today. (unverified whether any non-GUI caller enables it.)

**Phase 2 — Checksums** ([pipeline.py:139-144](../../pinball_decryptor/plugins/spooky/pipeline.py#L139)): `generate_checksums(output_dir)` from [core/checksums.py](../../pinball_decryptor/core/checksums.py) writes `.checksums.md5`; `_write_meta` writes `.spooky_meta` (JSON: game, game_key, format, ext, source).

**Phase 3 — Done** ([pipeline.py:146-151](../../pinball_decryptor/plugins/spooky/pipeline.py#L146)): `_log_summary_from_dir` prints a per-extension file-count summary (top 15).

### Output layout

```
output_dir/
  <decompressed game tree>          # tar/zip contents as-is
  _extracted_assets/                # Unity / Godot / P3 derivatives (organized by type)
    video/  audio/  textures/  scripts/
  _pck_contents/                    # Godot only: raw PCK files before conversion
  .checksums.md5                    # baseline for Write change-detection
  .spooky_meta                      # JSON metadata Write reads back
```

### Clonezilla path

`_run_clonezilla` ([pipeline.py:277-365](../../pinball_decryptor/plugins/spooky/pipeline.py#L277)): detect the partition key from the filename ([clonezilla.py:288-342](../../pinball_decryptor/plugins/spooky/clonezilla.py#L288)), build a platform executor, verify prereqs (`check_errors`), then `extract_clonezilla` ([clonezilla.py:473-679](../../pinball_decryptor/plugins/spooky/clonezilla.py#L473)):

1. Mount ISO host-side (PowerShell `Mount-DiskImage` / `hdiutil` / loop-mount) or pull the partclone member out of the ZIP to a temp dir.
2. Decompress (`zstandard` python first, then `zstd` CLI; or `gunzip`) to `/tmp/spooky_partclone_decompressed`.
3. `partclone.restore` → raw ext4 at `/tmp/spooky_raw.img`.
4. `debugfs -R "rdump …"` bulk-extract the game partition's paths.

The R&M autoflash ISO is a bare ext4 image (`compression: "none"`) and skips steps 2-3 via `_extract_raw_ext4` ([clonezilla.py:681-723](../../pinball_decryptor/plugins/spooky/clonezilla.py#L681)). After extraction the same Unity/Godot loose-asset passes run ([pipeline.py:338-343](../../pinball_decryptor/plugins/spooky/pipeline.py#L338)), then checksums + a `format: "clonezilla"` meta are written. **Clonezilla extracts are not re-packable** (Write rejects them — see below).

## Write / repack pipeline

`WritePipeline` ([pipeline.py:543-813](../../pinball_decryptor/plugins/spooky/pipeline.py#L543)). `original_path` is accepted for contract compatibility but discarded — Write reads format/game from `.spooky_meta` ([pipeline.py:550-553](../../pinball_decryptor/plugins/spooky/pipeline.py#L550)).

**Phase 0 — Detect** ([pipeline.py:559-582](../../pinball_decryptor/plugins/spooky/pipeline.py#L559)): load `.spooky_meta`; reject `clonezilla` and `aes_pkg` formats ("cannot be re-packaged").

**Phase 1 — Scan** ([pipeline.py:584-613](../../pinball_decryptor/plugins/spooky/pipeline.py#L584)): `_scan_changes` reads the `.checksums.md5` baseline and recomputes MD5 for every non-dotfile, yielding `(changed, added, removed)` ([pipeline.py:754-778](../../pinball_decryptor/plugins/spooky/pipeline.py#L754)). Zero changes → abort with a message. Then `_process_audio` auto-converts changed audio (below).

**Phase 2 — Repack** ([pipeline.py:615-674](../../pinball_decryptor/plugins/spooky/pipeline.py#L615)): `_build_output` dispatches on `format_type`, the inverse of Extract:

- `rm_pkg`/`ac_pkg` → `create_zip` to `.tmp.zip`, then `encrypt_aes_pkg` ([pipeline.py:676-698](../../pinball_decryptor/plugins/spooky/pipeline.py#L676)).
- `um_pkg`/`h78_pkg` → `create_tar_gz` to `.tmp.tar.gz`, then `encrypt_gpg_symmetric` ([pipeline.py:700-722](../../pinball_decryptor/plugins/spooky/pipeline.py#L700)).
- `tar_gz` → `create_tar_gz`; `plain_tar` → `create_tar`; `plain_zip` → `create_zip` (direct) — [pipeline.py:649-669](../../pinball_decryptor/plugins/spooky/pipeline.py#L649).
- `gpg_tar_gz` → `create_tar_gz` to temp, then `sign_beetlejuice` (logs the AGREE-dialog warning) — [pipeline.py:724-748](../../pinball_decryptor/plugins/spooky/pipeline.py#L724).

**Phase 3 — Done** ([pipeline.py:624-635](../../pinball_decryptor/plugins/spooky/pipeline.py#L624)): print install instructions with the per-extension USB naming convention from `USB_NAMING` ([games.py:180-186](../../pinball_decryptor/plugins/spooky/games.py#L180)), e.g. `rm-gamecode-YYYYMMDD.pkg`, `vYYYY.MM.DD.HH.scooby`.

### Audio auto-conversion during Write

`_process_audio` ([pipeline.py:780-812](../../pinball_decryptor/plugins/spooky/pipeline.py#L780)) runs only over **changed** `.wav`/`.ogg` files. For each, `detect_audio_info` is called; if the WAV is a compressed format, `_ffmpeg_convert_wav` re-encodes it to PCM. Note this in-pipeline pass is **narrower** than `process_modified_audio` — it only fixes compressed-WAV→PCM, not channel/rate/bit-depth/duration. Full format-matching against an *original* happens in the Replace-Audio flow (next section), which stages already-aligned files before Write runs.

## Audio assets

`audio.py` ([audio.py](../../pinball_decryptor/plugins/spooky/audio.py)) is an **IDENTICAL** upstream lift. It is a self-contained, dependency-light audio toolkit:

- **ffmpeg/ffprobe discovery** with cached results + Windows/macOS fallback paths ([audio.py:35-88](../../pinball_decryptor/plugins/spooky/audio.py#L35)).
- **Detection** — `detect_audio_info` → `_parse_wav_info` (walks RIFF chunks, derives codec from the format tag, computes duration from `data` size) and `_parse_ogg_info` (Vorbis ID header + last-granule duration) → an `AudioInfo` dataclass ([audio.py:95-268](../../pinball_decryptor/plugins/spooky/audio.py#L95)).
- **Pure-Python WAV ops** — `trim_wav`/`pad_wav` (duration match via silence; 8-bit uses `0x80`, signed depths use `0x00`), `convert_wav_channels` (mono↔stereo by duplication/averaging per bit depth; >2ch downmix falls to ffmpeg), `convert_wav_bit_depth` (normalize→requantize 8/16/24/32) — [audio.py:275-571](../../pinball_decryptor/plugins/spooky/audio.py#L275).
- **ffmpeg ops** — `_ffmpeg_convert_wav` (resample / codec / channel), `trim_ogg`/`pad_ogg` (libvorbis; pad via `anullsrc`+`concat`), `convert_ogg` — [audio.py:578-749](../../pinball_decryptor/plugins/spooky/audio.py#L578).
- **`process_modified_audio`** ([audio.py:756-884](../../pinball_decryptor/plugins/spooky/audio.py#L756)) — the high-level entry: against an original `AudioInfo`, it (1) decompresses WAV→PCM, (2) matches channels, (3) resamples, (4) converts bit depth, (5) trims/pads to duration (skipped when `keep_original_length=True`). OGG path re-encodes only when channels/rate differ or bitrate diverges >2×, then duration-matches. Returns a list of human-readable action strings.

### Where audio lives in extracts

- Plain/encrypted archive games: wherever the game tree puts them (loose `.wav`/`.ogg`).
- Unity games: `_extracted_assets/audio/` (decoded via fsb5, else raw `.fsb`).
- Godot (Looney Tunes): `_extracted_assets/audio/` — `.sample`→`.wav` and `.oggvorbisstr`→`.ogg`.

### Replace-Audio and the shared `core/audio.py` copy

`capabilities.replace_audio=True` and `audio_slot_dirs()` is **not** overridden, so the Replace-Audio tab scans the whole extract for loose `.wav`/`.ogg` ([registry.py:283-294](../../pinball_decryptor/core/registry.py#L283)). The tab is driven by [core/audio_slots.py](../../pinball_decryptor/core/audio_slots.py), which imports from **`core.audio`**, *not* the plugin's copy ([audio_slots.py:23-24](../../pinball_decryptor/core/audio_slots.py#L23)). `stage_replacement` ([audio_slots.py:120-164](../../pinball_decryptor/core/audio_slots.py#L120)): if the replacement's container matches the slot it copies, else `transcode_to` converts via ffmpeg into the slot's codec; then `process_modified_audio` aligns format and (optionally) length; then it atomically `os.replace`s over the slot file. Because the staged files overwrite the extracted assets in place, the normal Write change-scanner then picks them up as "modified" and repacks them.

> **Two near-identical audio modules exist.** `core/audio.py` is the same code as `plugins/spooky/audio.py` **plus** an extra `transcode_to()` (any-format→slot-codec) and an ffplay preview section ([core/audio.py:886-1004](../../pinball_decryptor/core/audio.py#L886)). The plugin copy must stay byte-identical to upstream (it's an `identical` lift); `core/audio.py` is the unified app's superset used by the cross-plugin Replace-Audio feature. Editing one does **not** change the other.

## Other asset types

### Godot PCK ([godot.py](../../pinball_decryptor/plugins/spooky/godot.py), IDENTICAL lift)

`extract_godot_pck` locates the PCK by reading the trailing `[u64 size][GDPC]` 12-byte trailer ([godot.py:33-72](../../pinball_decryptor/plugins/spooky/godot.py#L33)), parses the 100-byte v2 header + file table ([godot.py:75-148](../../pinball_decryptor/plugins/spooky/godot.py#L75)), streams every file (stripping `res://`) into `_pck_contents/`, then `_organize_assets` converts and sorts into `_extracted_assets/{video,audio,textures,scripts}/` ([godot.py:684-764](../../pinball_decryptor/plugins/spooky/godot.py#L684)):

- `.ogv` → copied (Ogg Theora video).
- `.oggvorbisstr` → `_convert_oggvorbisstr` parses the Godot RSRC `OggPacketSequence` and **rebuilds a valid Ogg bitstream** including hand-computed Ogg CRC-32 ([godot.py:198-435](../../pinball_decryptor/plugins/spooky/godot.py#L198)).
- `.ctex` → `_convert_ctex` scavenges the embedded PNG (to IEND) or RIFF/WEBP blob ([godot.py:438-475](../../pinball_decryptor/plugins/spooky/godot.py#L438)).
- `.sample` → `_convert_sample` parses the RSRC `AudioStreamWAV` (data/format/mix_rate/stereo) and emits a WAV ([godot.py:478-628](../../pinball_decryptor/plugins/spooky/godot.py#L478)).
- `.gd` → copied (GDScript source).

### Unity assets ([unity.py](../../pinball_decryptor/plugins/spooky/unity.py), IDENTICAL lift)

`extract_unity_assets` requires UnityPy (gracefully skipped if absent — [pipeline.py:374-377](../../pinball_decryptor/plugins/spooky/pipeline.py#L374)). It loads each `.assets`, then for `VideoClip` reads the external `.resource` blob at offset/size (preserving the original `video/…` subpath); for `AudioClip` tries three strategies in order — fsb5 decode (with a pyogg-DLL monkey-patch for Vorbis on Windows, [unity.py:24-67](../../pinball_decryptor/plugins/spooky/unity.py#L24)), UnityPy `data.samples` (needs FMOD), then raw `.fsb` fallback; for `Texture2D` saves a PNG via Pillow. Outputs to `_extracted_assets/{video,audio,textures}/`.

### P3 DMD video ([p3_video.py](../../pinball_decryptor/plugins/spooky/p3_video.py), IDENTICAL lift)

`convert_vid_to_mp4` parses the 512-byte VID header, **auto-detecting 4bpp vs 8bpp** by matching the frame-count hint against both candidate frame sizes, with a nibble-histogram cosine-similarity fallback ([p3_video.py:122-229](../../pinball_decryptor/plugins/spooky/p3_video.py#L122)). 4bpp renders monochrome amber dots (gamma-corrected); 8bpp decodes RGB332 (matching the chromaColor FPGA Verilog). Interleaved-half files (`hint*2 == raw_frames`, e.g. Jetsons) are reassembled by stacking even/odd raw frames vertically ([p3_video.py:376-408](../../pinball_decryptor/plugins/spooky/p3_video.py#L376)). Frames render to temp PNGs, then `ffmpeg -c:v libx264 -crf 18` assembles the MP4. As noted above, this only runs when `convert_vids` is enabled.

## Mod Pack / delta / direct-SSD

- **Mod Pack:** `modpack=True` — the Mod Pack tab is offered (the cross-plugin packaging UI; spooky exposes no plugin-specific mod-pack code beyond the capability flag).
- **Delta:** `apply_delta=False` — **N/A**; no `apply_delta` implementation.
- **Direct-SSD:** `direct_ssd` not set — **N/A** (that path is JJP-only).

## Detection

`SpookyManufacturer.detect` ([manufacturer.py:72-103](../../pinball_decryptor/plugins/spooky/manufacturer.py#L72)) delegates to `formats.detect_game` ([formats.py:23-50](../../pinball_decryptor/plugins/spooky/formats.py#L23)), which resolves in priority order:

1. **Unique extensions** `.ed/.scooby/.beetlejuice/.looney` → `KNOWN_GAMES` table ([games.py:131-136](../../pinball_decryptor/plugins/spooky/games.py#L131)).
2. **`.pkg`** → `_detect_pkg`: filename patterns first (they encode which key/format to use — `rm-gamecode`, `ac-gamecode`, `tna-gamecode`, `code_UM`, `code_H78`, `tcm-`), then a **magic-byte fallback** ([formats.py:53-102](../../pinball_decryptor/plugins/spooky/formats.py#L53)): gzip `\x1f\x8b`→tar_gz; GPG tag-3 byte `{0x8c,0x8d,0xc3}`→gpg_symmetric; otherwise if `magic[4:8]==0` (the high dword of the little-endian uint64 orig-size header is zero for any realistically-sized file) → `aes_pkg`.
3. **`.zip`** → known P3 patterns (`AMH`, `rzupdate`, `DOM_`, `Jetsons`), else a Clonezilla-member sniff, else `plain_zip` ([formats.py:105-128](../../pinball_decryptor/plugins/spooky/formats.py#L105)).
4. **`.iso`** → always `clonezilla` ([formats.py:47-48](../../pinball_decryptor/plugins/spooky/formats.py#L47)).

For `clonezilla` results `detect` re-runs the filename-based partition detector to produce a friendly game badge ([manufacturer.py:78-92](../../pinball_decryptor/plugins/spooky/manufacturer.py#L78)); a `clonezilla` image whose name matches no pattern (e.g. AMH) returns `None`. An `aes_pkg` result is badged "AES-encrypted (key unknown)".

> **Why AP must load before spooky.** Spooky's `.pkg` magic-byte fallback (step 2) is *generic* — the `magic[4:8]==0` heuristic claims essentially any AES-CBC-shaped `.pkg`, including American Pinball packages. AP's detector is **key-validated** (it only claims a `.pkg` that actually decrypts to a ZIP with the AP key), so it must run first or spooky would mis-grab AP files. This ordering is enforced in [registry.py:21-25](../../pinball_decryptor/core/registry.py#L21).

## Upstream-lift parity

The plan in [`tests/verify_no_upstream_regression.py`](../../tests/verify_no_upstream_regression.py) (PLAN dict, [lines 79-107](../../tests/verify_no_upstream_regression.py#L79)) classifies each spooky file. Upstream = the sibling `spooky/spooky_decryptor/` repo.

| file | kind | parity contract |
|---|---|---|
| `godot.py` | **identical** | byte-equal to upstream — any diff is a regression |
| `unity.py` | **identical** | byte-equal |
| `audio.py` | **identical** | byte-equal |
| `p3_video.py` | **identical** | byte-equal |
| `clonezilla.py` | **identical** | byte-equal |
| `executor.py` | **identical** | byte-equal |
| `Dockerfile` | **identical** | byte-equal |
| `crypto.py` | **import-only** | verbatim except `from .config` → `from .games` rewire |
| `gpg.py` | **import-only** | verbatim except import rewire |
| `formats.py` | **ported** | format-detection tidied, no logic change; covered by `test_spooky_e2e.py` |
| `pipeline.py` | **ported** | re-orchestrated to `BasePipeline`; covered by `test_spooky_e2e.py` |
| `__init__.py`, `games.py`, `manufacturer.py` | **new** | wrappers / carved-from-`config.py` data |

The `identical`/`import-only` set is the **regression firewall**: any accidental tweak to encryption keys, GPG packet handling, Godot PCK parsing, Unity extraction, P3 VID conversion, or the Clonezilla/partclone flow trips a byte-equal check ([verify…py:74-99](../../tests/verify_no_upstream_regression.py#L74)). The verifier accepts only `from .config import` / `from .games import` / `from ...core` rewire lines on import-only files ([verify…py:184-188](../../tests/verify_no_upstream_regression.py#L184)).

> **Do not `git checkout` / `git restore` the lifted files casually.** This repo has `core.autocrlf=true` and `.gitattributes` forces LF only on `*.sh` (not `*.py`) — confirmed in [`.gitattributes`](../../.gitattributes). A checkout would re-materialize the `.py` lifts with CRLF line endings, which changes their bytes and **fails the byte-identity check** even though the logic is untouched. Edit in place or restore with line endings preserved.

## Gotchas & non-obvious details

- **Executor backends** ([executor.py:512-520](../../pinball_decryptor/plugins/spooky/executor.py#L512)): Windows→`WslExecutor` (`wsl -u root`), macOS→`DockerExecutor` (privileged Alpine built from the bundled [Dockerfile](../../pinball_decryptor/plugins/spooky/Dockerfile)), Linux→`NativeExecutor` (`sudo bash -c`, or direct as root inside Docker). `to_exec_path` translates host paths (`C:\…`→`/mnt/c/…`; macOS→`/host/…`). WSL output may be UTF-16LE — decoded specially ([executor.py:33-43](../../pinball_decryptor/plugins/spooky/executor.py#L33)).
- **WSL drive visibility** ([executor.py:179-207](../../pinball_decryptor/plugins/spooky/executor.py#L179)): WSL2 only auto-mounts drives present at WSL startup, so a USB plugged in after boot is invisible — the executor surfaces a "run `wsl --shutdown`" hint.
- **gpg/ffmpeg discovery is duplicated** across modules with differing search lists: `gpg.py._find_gpg` (3 Windows paths), `audio.py`/`core.audio.find_ffmpeg`, and `p3_video.find_ffmpeg` (WinGet/Scoop/Choco globbing) each cache their own result. `core.audio` and `audio` (plugin) keep independent module-level caches.
- **`.pkg` magic detection is heuristic.** The `aes_pkg` test (`magic[4:8]==0`) is a structural inference, not a signature; it is *the* reason AP must load first (above). A `.pkg` matching no filename pattern and no magic returns `None`.
- **Beetlejuice signing is intentionally invalid.** Write signs with a throwaway key; the machine warns and the operator clicks AGREE. If GPG keygen fails, a hand-built dummy-signature packet is used ([gpg.py:382-457](../../pinball_decryptor/plugins/spooky/gpg.py#L382)).
- **TNA / Clonezilla are extract-only at the format level.** Both Extract (TNA) and Write (TNA + any Clonezilla) refuse to round-trip ([pipeline.py:157-164](../../pinball_decryptor/plugins/spooky/pipeline.py#L157), [577-582](../../pinball_decryptor/plugins/spooky/pipeline.py#L577)).
- **Temp files live inside `output_dir`** during Extract (`_temp_decrypted.zip`, etc.) and are removed in `finally`; an interrupted run could leave one behind.
- **AES encrypt zero-pads** the final block rather than using PKCS#7 ([crypto.py:84-87](../../pinball_decryptor/plugins/spooky/crypto.py#L85)); decrypt relies on the stored `origsize` to truncate, so round-trips are exact.
- **`keep_audio_length`** is a `WritePipeline` ctor arg ([pipeline.py:547](../../pinball_decryptor/plugins/spooky/pipeline.py#L547)) but `_process_audio` never reads it; length control is exercised via the Replace-Audio `trim_to_length` toggle instead.

## Key files

- [`manufacturer.py`](../../pinball_decryptor/plugins/spooky/manufacturer.py) — `SpookyManufacturer`: capabilities, prereqs, `detect`, pipeline factories, install help. (new)
- [`__init__.py`](../../pinball_decryptor/plugins/spooky/__init__.py) — plugin registration. (new)
- [`games.py`](../../pinball_decryptor/plugins/spooky/games.py) — game DB, keys, passphrases, detection tables, USB naming, engine routing sets. (new)
- [`formats.py`](../../pinball_decryptor/plugins/spooky/formats.py) — format detection + tar/zip archive helpers. (ported)
- [`pipeline.py`](../../pinball_decryptor/plugins/spooky/pipeline.py) — `ExtractPipeline` / `WritePipeline` orchestration. (ported)
- [`crypto.py`](../../pinball_decryptor/plugins/spooky/crypto.py) — AES-256-CBC `.pkg` encrypt/decrypt. (import-only)
- [`gpg.py`](../../pinball_decryptor/plugins/spooky/gpg.py) — GPG symmetric crypto + Beetlejuice sign/strip (binary + manual packet paths). (import-only)
- [`godot.py`](../../pinball_decryptor/plugins/spooky/godot.py) — Godot 4 PCK locate/parse + RSRC asset conversion. (identical)
- [`unity.py`](../../pinball_decryptor/plugins/spooky/unity.py) — UnityPy + fsb5 asset extraction. (identical)
- [`p3_video.py`](../../pinball_decryptor/plugins/spooky/p3_video.py) — P3 `.VID`→MP4 DMD renderer. (identical)
- [`audio.py`](../../pinball_decryptor/plugins/spooky/audio.py) — WAV/OGG detect/convert/trim/pad. (identical; superset lives in `core/audio.py`)
- [`clonezilla.py`](../../pinball_decryptor/plugins/spooky/clonezilla.py) — restore-image partition map + partclone/debugfs extraction. (identical)
- [`executor.py`](../../pinball_decryptor/plugins/spooky/executor.py) — WSL / Docker / Native command executors. (identical)
- [`Dockerfile`](../../pinball_decryptor/plugins/spooky/Dockerfile) — Alpine container with partclone/e2fsprogs/zstd/gnupg. (identical)
- [`core/audio.py`](../../pinball_decryptor/core/audio.py) — shared Replace-Audio toolkit (plugin `audio.py` + `transcode_to` + ffplay preview).
- [`core/audio_slots.py`](../../pinball_decryptor/core/audio_slots.py) — Replace-Audio slot scan + staging.
- [`tests/verify_no_upstream_regression.py`](../../tests/verify_no_upstream_regression.py) — upstream-lift parity guard.

## Related docs

- [`docs/AP_PKG_RE.md`](../AP_PKG_RE.md) — American Pinball `.pkg` reverse-engineering (relevant to the AP-before-spooky detection ordering).
- [`docs/CGC_BNK_RE.md`](../CGC_BNK_RE.md) — CGC sound-bank format (contrasts with spooky's loose-audio Replace-Audio model).
- `tests/test_spooky_e2e.py` — Extract→modify→Write→re-extract round-trip that guards the ported `formats.py`/`pipeline.py`.
