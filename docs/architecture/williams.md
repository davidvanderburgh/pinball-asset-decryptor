# Williams (`williams`) — Architecture

> The Williams plugin handles WPC/WPC-S/WPC-95-era Williams & Bally pinball ROMs supplied as MAME-format `.zip` files. It is **extract-only** — there is no Write/repack path. It exposes two complementary extraction paths: a **static** decode that walks the WPC master tables directly out of the game ROM to emit DMD scene PNGs, animation MP4s, and font sheets (and, for DCS-era titles, per-track audio WAVs), and a **runtime-capture** path that boots the game under libpinmame (PinMAME), scripts an attract-mode/gameplay tour, and records the composed DMD display + real audio into per-cinematic MP4s. An optional Whisper-based transcribe path emits `callouts.csv` for DCS-era audio.

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/williams/`
- **Key / display:** `key = "williams"`, `display = "Williams"` ([manufacturer.py:22](../../pinball_decryptor/plugins/williams/manufacturer.py#L22))
- **Badge:** `"EXTRACT ONLY"` — takes precedence over the default beta badge ([manufacturer.py:28](../../pinball_decryptor/plugins/williams/manufacturer.py#L28))

### Supported games

Games come from `GAME_DB` in [games.py:31](../../pinball_decryptor/plugins/williams/games.py#L31). The plugin's `games` tuple is built from every `GAME_DB` entry ([manufacturer.py:14](../../pinball_decryptor/plugins/williams/manufacturer.py#L14)); none are marked unsupported, so all advertise `supported=True` at the registry level. "DCS?" below indicates whether *static* audio decode applies — this is a **runtime** property (probed by `dcs_decode.is_dcs_rom`, see below), not a static field, so the table reflects the `platform` tag and DCS reality rather than a per-row flag in the code.

| key | display | DCS audio? | supported | notes (platform, year) |
|-----|---------|-----------|-----------|------------------------|
| `fish_tales` | Fish Tales | No (pre-DCS YM2151) (unverified per-title) | yes | WPC-DCS, 1992 — has rich capture script (`_ft_moments`) |
| `white_water` | White Water | No (pre-DCS) (unverified) | yes | WPC-DCS, 1993 — rich capture script |
| `twilight_zone` | Twilight Zone | varies | yes | WPC-DCS, 1993 (Bally) — rich script |
| `indiana_jones` | Indiana Jones | varies | yes | WPC-DCS, 1993 — rich script |
| `judge_dredd` | Judge Dredd | varies | yes | WPC-DCS, 1993 (Bally) — rich script |
| `star_trek_tng` | Star Trek: The Next Generation | varies | yes | WPC-DCS, 1993 — rich script |
| `addams_family` | The Addams Family | varies | yes | WPC, 1992 (Bally) — rich script |
| `creature_black_lagoon` | Creature from the Black Lagoon | varies | yes | WPC, 1992 (Bally) — generic script |
| `doctor_who` | Doctor Who | varies | yes | WPC, 1992 (Bally) |
| `dr_dredd` | Dirty Harry | varies | yes | WPC-S, 1995 |
| `bram_stokers_dracula` | Bram Stoker's Dracula | varies | yes | WPC-Fliptronics II, 1993 — rich script |
| `demolition_man` | Demolition Man | varies | yes | WPC-DCS, 1994 — rich script |
| `flintstones` | The Flintstones | varies | yes | WPC-Security, 1994 |
| `popeye` | Popeye Saves the Earth | varies | yes | WPC-Fliptronics II, 1994 |
| `world_cup_soccer` | World Cup Soccer | varies | yes | WPC-DCS, 1994 (Bally) |
| `hurricane` | Hurricane | varies | yes | WPC, 1991 |
| `black_rose` | Black Rose | varies | yes | WPC, 1992 (Bally) |
| `gilligans_island` | Gilligan's Island | varies | yes | WPC, 1991 (Bally) |
| `the_getaway` | The Getaway: High Speed II | varies | yes | WPC, 1992 |
| `terminator_2` | Terminator 2: Judgment Day | varies | yes | WPC, 1991 — rich script |
| `slugfest` | SlugFest | varies | yes | WPC, 1991 |
| `no_fear` | No Fear: Dangerous Sports | varies | yes | WPC-S, 1995 |
| `indianapolis_500` | Indianapolis 500 | varies | yes | WPC-S, 1995 (Bally) |
| `who_dunnit` | Who Dunnit | varies | yes | WPC-S, 1995 (Bally) |
| `jackbot` | Jack*Bot | varies | yes | WPC-S, 1995 |
| `shadow` | The Shadow | varies | yes | WPC-S, 1994 (Bally) |
| `corvette` | Corvette | varies | yes | WPC-S, 1994 (Bally) |
| `congo` | Congo | varies | yes | WPC-S, 1995 |
| `roadshow` | Red & Ted's Road Show | varies | yes | WPC-Security, 1994 — rich script |
| `theatre_of_magic` | Theatre of Magic | DCS | yes | WPC-95, 1995 (Bally) — rich script |
| `attack_from_mars` | Attack From Mars | DCS | yes | WPC-95, 1995 (Bally) — richest script (`_afm_moments`) |
| `scared_stiff` | Scared Stiff | DCS | yes | WPC-95, 1996 (Bally) — rich script |
| `junkyard` | Junk Yard | DCS | yes | WPC-95, 1996 |
| `tales_of_arabian_nights` | Tales of the Arabian Nights | DCS | yes | WPC-95, 1996 |
| `safe_cracker` | Safe Cracker | DCS | yes | WPC-95, 1996 (Bally) |
| `nba_fastbreak` | NBA Fastbreak | DCS | yes | WPC-95, 1997 (Bally) |
| `no_good_gofers` | No Good Gofers | DCS | yes | WPC-95, 1997 — rich script |
| `medieval_madness` | Medieval Madness | DCS | yes | WPC-95, 1997 — rich script (`_mm_moments`) |
| `cirqus_voltaire` | Cirqus Voltaire | DCS | yes | WPC-95, 1997 (Bally) |
| `champion_pub` | The Champion Pub | DCS | yes | WPC-95, 1998 (Bally) |
| `monster_bash` | Monster Bash | DCS | yes | WPC-95, 1998 |
| `cactus_canyon` | Cactus Canyon | DCS | yes | WPC-95, 1998 (Bally) |
| `johnny_mnemonic` | Johnny Mnemonic | DCS | yes | WPC-S, 1995 |
| `ticket_tac_toe` | Ticket Tac Toe | DCS | yes | WPC-95, 1996 (Bally) |

The "DCS audio?" column is authoritative only at runtime: `audio_export_supported()` probes the actual ROM via DCSExplorer (`is_dcs_rom`) rather than reading the `platform` string. Some titles tagged `WPC-DCS` in `GAME_DB` (e.g. Fish Tales, White Water) actually used the pre-DCS YM2151 sound board and yield no static audio — the `platform` field is "preserved for reference" only and is explicitly *not* used to gate the pipeline ([games.py:26](../../pinball_decryptor/plugins/williams/games.py#L26)). Treat per-title DCS flags above as **(unverified)** except where confirmed by code comments (Fish Tales / White Water are named in the pre-DCS comment at [manufacturer.py:144](../../pinball_decryptor/plugins/williams/manufacturer.py#L144) and [dcs_decode.py:19](../../pinball_decryptor/plugins/williams/dcs_decode.py#L19)).

Detection is data-driven: more WPC titles can be added by appending `GAME_DB` entries with no code change ([games.py:13](../../pinball_decryptor/plugins/williams/games.py#L13)).

### Input extensions / InputSpec

```python
InputSpec(label="Williams MAME ROM zips", extensions=(".zip",))
```
([manufacturer.py:42](../../pinball_decryptor/plugins/williams/manufacturer.py#L42)) — input is a MAME-format ROM `.zip` (e.g. `ft_l5.zip`, `afm_113b.zip`).

### Capabilities

Declared at [manufacturer.py:29](../../pinball_decryptor/plugins/williams/manufacturer.py#L29):

| flag | value | meaning |
|------|-------|---------|
| `extract` | **True** | Static asset-extract pipeline (WPC master-table decode) |
| `capture` | **True** | Runtime-capture pipeline via libpinmame — boots the game, records composed DMD frames + audio, emits per-cinematic MP4s |
| `transcribe` | **True** | faster-whisper over extracted WAVs → `callouts.csv` |
| `write` | **False** | No write/repack — ROM is read-only, the source of truth is the user's MAME zip |
| `modpack`, `apply_delta`, `iso`, `direct_ssd`, `asset_filters`, `write_version_date`, `decode_dmd`, `chain_deltas`, `replace_audio` | False | Not used |

Note: although `transcribe=True` is declared statically, the per-path visibility is overridden by `audio_export_supported()` so the Auto-transcribe control and the "Extract audio" phase only appear for DCS-era ROMs ([manufacturer.py:142](../../pinball_decryptor/plugins/williams/manufacturer.py#L142)). There is **no Replace-Audio tab** — `replace_audio` is unset because the audio is ROM-resident (not loose editable `.wav`/`.ogg`), and there is no Write pipeline to repack into.

### Prerequisites

Declared at [manufacturer.py:54](../../pinball_decryptor/plugins/williams/manufacturer.py#L54):

- **ffmpeg** (`where="host"`, probe `ffmpeg -version`) — encodes DMD frame PNGs into MP4 videos. Required by both the static animation/browse render and the capture per-clip render. Install hints for winget/brew/apt.
- **faster-whisper** (`where="host"`, probe `python:faster_whisper` — an in-process import check) — drives the Auto-transcribe checkbox. The ~75 MB `tiny.en` model downloads on first transcribe run and is cached in the user's HF cache.
- **libpinmame** — *intentionally not listed* as a prereq. The GUI renders missing prereqs in red, and libpinmame is only needed for the optional capture path; the capture pipeline surfaces its own clean install hint when invoked without it ([manufacturer.py:73](../../pinball_decryptor/plugins/williams/manufacturer.py#L73), [pinmame_capture.py:1590](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1590)).
- **DCSExplorer** — bundled (Windows binary in `vendor/`) or found on PATH; not surfaced as a host prereq ([dcs_decode.py:78](../../pinball_decryptor/plugins/williams/dcs_decode.py#L78)).

### Phase labels

Four distinct phase sets, chosen by the GUI based on which path the user runs:

- **Static extract** (`PHASES`, [pipeline.py:41](../../pinball_decryptor/plugins/williams/pipeline.py#L41)): `Detect → Unzip → Find tables → Decode scenes → Render animations → Extract audio → Cleanup`. The "Extract audio" phase is only entered for DCS ROMs; non-DCS games renumber so Cleanup becomes phase 5 instead of 6 ([pipeline.py:139](../../pinball_decryptor/plugins/williams/pipeline.py#L139)).
- **Capture** (`CAPTURE_PHASES` = `capture_pipeline.PHASES`, [capture_pipeline.py:37](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L37)): `Detect → Probe libpinmame → Capture → Segment + render → Cleanup`.
- **Combined** (`COMBINED_PHASES`, [capture_pipeline.py:49](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L49)): `Detect → Static extract → Probe libpinmame → Capture → Segment + render → Cleanup`. Used when "Use PinMAME runtime capture" is ticked (capture is additive on top of static).
- **Transcribe** (`("Load model", "Transcribe", "Rename", "Write CSV")`, [manufacturer.py:53](../../pinball_decryptor/plugins/williams/manufacturer.py#L53)).

## ROM & audio format

### WPC game ROM structure

WPC game ROMs are 256 KB, 512 KB, or 1 MB ([wpc_decode.py:92](../../pinball_decryptor/plugins/williams/wpc_decode.py#L92)) and divide into 16 KB pages ([wpc_decode.py:51](../../pinball_decryptor/plugins/williams/wpc_decode.py#L51)):

- The **top two pages** (last 32 KB) are *non-paged*: permanently mapped at 6809 addresses `0x8000–0xFFFF`. Reset vectors and the master pointer tables live here.
- All other pages are *paged*: banked into `0x4000–0x7FFF` by writing the page number to a WPC ASIC register.

The first ROM byte is the base page index the bank-switch code expects (`base_page_index`, [wpc_decode.py:102](../../pinball_decryptor/plugins/williams/wpc_decode.py#L102)) — though for some games (e.g. AFM) that byte is actually a 6809 opcode and the true base page is brute-forced by maximizing how many master-table pointers resolve ([wpc_decode.py:200](../../pinball_decryptor/plugins/williams/wpc_decode.py#L200)).

**Master tables.** Three tables of pointers (Font, Graphics, Animation) live in the non-paged area, located by signature-scanning the ROM for the 6809 instruction sequence that loads the Font Table pointer ([wpc_decode.py:184](../../pinball_decryptor/plugins/williams/wpc_decode.py#L184)):

```
BE xx xx 3A 58 3A D6 yy 34 04 [F6|BD] zz zz [BD|F6] ww ww
```

`xx xx` after the `BE` (LDX immediate) is the WPC address of the Font Table pointer. Graphics and Animation pointers follow as the next 2-or-3-byte WPC pointers ([wpc_decode.py:192](../../pinball_decryptor/plugins/williams/wpc_decode.py#L192)). The decoder is a Python port of `permartinson/wpcedit.js` (itself a TS port of Garrett Lee's WPC Edit) ([wpc_decode.py:1](../../pinball_decryptor/plugins/williams/wpc_decode.py#L1)).

**DMD frame format.** The DMD is 128×32 dots. One 1-bit plane is `DMD_PAGE_BYTES = 512` bytes (`128*32/8`) ([wpc_decode.py:48](../../pinball_decryptor/plugins/williams/wpc_decode.py#L48)). Bytes are **LSB-first within each byte** — bit 0 is the leftmost pixel of its 8-pixel group ([dmd_render.py:80](../../pinball_decryptor/plugins/williams/dmd_render.py#L80)). A 4-shade frame stacks two planes (1024 bytes): the per-pixel brightness is `(low_bit + 2*high_bit) / 3`, giving {0%, 33%, 66%, 100%} ([dmd_render.py:60](../../pinball_decryptor/plugins/williams/dmd_render.py#L60)).

**Image encodings.** Each image entry carries an encoding type byte. Valid encodings are `0x00–0x0B` plus `0xFF` ([wpc_decode.py:63](../../pinball_decryptor/plugins/williams/wpc_decode.py#L63)). Notable types: `0x00` monochrome (raw 512-byte copy — the simplest, used as the byte-for-byte decode sanity test), `0xFE` bicolor-indirect (one plane inline + a pointer to the other), `0xFF` bicolor-direct (both planes inline), and `0xFD` an Indiana-Jones-specific oddity treated as mono ([wpc_decode.py:67](../../pinball_decryptor/plugins/williams/wpc_decode.py#L67)). The higher encodings are RLE / XOR-delta / multi-plane-mask compressed (`decode_image_to_plane`, [wpc_decode.py:365](../../pinball_decryptor/plugins/williams/wpc_decode.py#L365)); unimplemented encodings are tallied and skipped rather than fatal ([wpc_extract.py:194](../../pinball_decryptor/plugins/williams/wpc_extract.py#L194)).

### DCS (Digital Compression System) audio

DCS is a proprietary compressed digital-audio format on the sound ROMs of Williams/Bally games ~1993–1998 ([dcs_decode.py:1](../../pinball_decryptor/plugins/williams/dcs_decode.py#L1)). A DCS "track" is a complete audio program (music cue, voice line, or SFX) addressable by the numeric command the WPC board sends the sound board. The plugin does **not** implement a DCS decoder itself — it shells out to **DCSExplorer**, an open-source (BSD-3-Clause) native decoder by Michael J. Roberts ([vendor/DCSExplorer-LICENSE.txt](../../pinball_decryptor/plugins/williams/vendor/DCSExplorer-LICENSE.txt)).

- **DCS detection** (`is_dcs_rom`): runs `DCSExplorer --info <zip>` (60 s timeout, cached per path) and returns True iff the output contains `"U2 Signature:"` and not `"could be identified as ROM U2"` ([dcs_decode.py:130](../../pinball_decryptor/plugins/williams/dcs_decode.py#L130)).
- **Extraction** (`extract_dcs`): runs `DCSExplorer --extract-tracks=<dir>/track <zip>` (600 s timeout), producing `track_<hex-id>.wav` per track plus a `manifest.json` (`format: dcs_tracks_v1`) describing track id, WAV filename, duration, sample rate, channels, and PCM size ([dcs_decode.py:168](../../pinball_decryptor/plugins/williams/dcs_decode.py#L168), manifest at [dcs_decode.py:263](../../pinball_decryptor/plugins/williams/dcs_decode.py#L263)). A non-DCS ROM is returned as `is_dcs=False` with a clean message (not an error), and an empty output dir is removed.

Pre-DCS games (~1990–1992, YM2151 sound board) cannot be decoded statically — their audio is only recoverable through the runtime-capture pipeline ([dcs_decode.py:19](../../pinball_decryptor/plugins/williams/dcs_decode.py#L19)).

## Static extract pipeline

`ExtractPipeline` ([pipeline.py:45](../../pinball_decryptor/plugins/williams/pipeline.py#L45)), built by `make_extract_pipeline` ([manufacturer.py:92](../../pinball_decryptor/plugins/williams/manufacturer.py#L92)). Phase by phase:

0. **Detect** — `detect_game(zip)` scores each `GAME_DB` entry by how many of its ROM filenames appear inside the zip (+1 for a filename hint) and returns the highest-scoring key, or raises `PipelineError` with a list of known games ([pipeline.py:55](../../pinball_decryptor/plugins/williams/pipeline.py#L55), [formats.py:26](../../pinball_decryptor/plugins/williams/formats.py#L26)).
1. **Unzip** — `list_game_roms` resolves which contained files are game vs sound ROMs (catalogue match, with a fallback that picks the largest 256K/512K/1M `.rom`/`.bin` as the game ROM and treats leftover `.l1`/`.rom`/`.512`/`.bin` as sound ROMs) ([formats.py:57](../../pinball_decryptor/plugins/williams/formats.py#L57)). Selected ROMs are extracted into `<game_key>/roms/` ([pipeline.py:89](../../pinball_decryptor/plugins/williams/pipeline.py#L89)).
2. **Find tables / 3. Decode scenes / 4. Render animations** — the first game ROM's bytes are handed to `wpc_extract.extract_dmd_assets`, which bumps phases 3 and 4 via callbacks ([pipeline.py:100](../../pinball_decryptor/plugins/williams/pipeline.py#L100)). A `WpcDecodeError` (no font/graphics table) becomes a friendly `PipelineError` ([pipeline.py:111](../../pinball_decryptor/plugins/williams/pipeline.py#L111)).
5. **Extract audio** — DCS games only: `_extract_dcs_audio` calls `dcs_decode.extract_dcs` into `<game_key>/sounds/`; pre-DCS games skip the phase entirely (and the GUI omits it) ([pipeline.py:135](../../pinball_decryptor/plugins/williams/pipeline.py#L135)).
6. **Cleanup** — `generate_checksums` over the game dir; emits a rich done-summary ([pipeline.py:146](../../pinball_decryptor/plugins/williams/pipeline.py#L146)).

### `wpc_extract.extract_dmd_assets`

[wpc_extract.py:93](../../pinball_decryptor/plugins/williams/wpc_extract.py#L93) — the reusable "phase 2-4 core" (also consumed by the CGC plugin's WPC remakes, hence the `pixel_size` parameter). It:

- Builds `WpcRom`, finds tables, resolves the Graphics master table (raising `WpcDecodeError` if the font signature matched but the graphics pointer didn't decode) ([wpc_extract.py:138](../../pinball_decryptor/plugins/williams/wpc_extract.py#L138)).
- Walks every image index (`decode_image_to_plane`), stopping after `MAX_CONSECUTIVE_INVALID = 8` out-of-range entries or `MAX_IMAGE_INDEX = 4000`. Each valid plane → `scene_NNNN_encXX_OFFSET.png`; consecutive odd/even indices are paired into 4-shade `pairs/pair_NNNN.png` ([wpc_extract.py:183](../../pinball_decryptor/plugins/williams/wpc_extract.py#L183)).
- Writes `dmd_scenes/scenes.json` (encoding distribution + per-scene offsets) and a `browse.mp4` flipping every scene at 2 fps ([wpc_extract.py:243](../../pinball_decryptor/plugins/williams/wpc_extract.py#L243)).
- Detects **scene-sequences** — runs of consecutive 4-shade frames within `SCENE_SEQ_MAX_DIFF_RATIO = 0.30` pixel diff, ≥4 frames — and renders each as `animations/anim_scene_NNN_*.mp4` ([wpc_extract.py:330](../../pinball_decryptor/plugins/williams/wpc_extract.py#L330)).
- Enumerates animation sub-tables; sub-tables with non-zero `table_height` are **fonts** rendered as 16-glyph-per-row sheets (`fonts/font_*.png`), others are **animations** (`anim_*.mp4`) with leading blank frames trimmed and a min of 3 frames ([wpc_extract.py:277](../../pinball_decryptor/plugins/williams/wpc_extract.py#L277)).

### Output layout

```
<output_dir>/<game_key>/
  dmd_scenes/  scene_NNNN_encXX_OFFSET.png, pairs/pair_NNNN.png, browse.mp4, scenes.json
  animations/  anim_*.mp4 (scene-sequences + sub-table animations)
  fonts/       font_*.png
  sounds/      track_*.wav, manifest.json     (DCS games only)
  roms/        <extracted game + sound ROMs>
  scan_summary.txt
```
([pipeline.py:9](../../pinball_decryptor/plugins/williams/pipeline.py#L9))

### The `audio_export_supported` override

[manufacturer.py:142](../../pinball_decryptor/plugins/williams/manufacturer.py#L142) overrides the base class (which would tie audio export to the static `transcribe` flag). Williams returns `is_williams_zip(path) and dcs_decode.is_dcs_rom(path)` — so the Auto-transcribe controls and the "Extract audio" phase are hidden for pre-DCS YM2151 titles, which have no statically decodable audio.

## Runtime-capture pipeline (PinMAME)

Built by `make_capture_pipeline` ([manufacturer.py:98](../../pinball_decryptor/plugins/williams/manufacturer.py#L98)). The kwarg `also_run_static` (default True) selects `StaticPlusCapturePipeline` (static then capture into the same folder) vs `CapturePipeline` (capture only). Other kwargs: `duration_seconds` (default 180), `simulate_gameplay` (default True), `frame_cb` (live preview), `capture_ready_cb` (switch-matrix hook).

### `CapturePipeline` phases ([capture_pipeline.py:76](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L76))

0. **Detect** — `detect_game`; ROM short name guessed from the zip basename (`ft_l5.zip` → `ft_l5`) ([capture_pipeline.py:258](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L258)).
1. **Probe libpinmame** — `find_libpinmame()`; raises with `install_hint()` if absent. Output goes to `<game_key>_capture/`.
2. **Capture** — constructs `PinmameCapture` and `CaptureConfig` (sample rate 48000, audio+DMD on) and calls `cap.run(...)` ([capture_pipeline.py:140](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L140)). Errors map to `PipelineError`; an empty frame list is treated as a hard failure with a "may not have a DMD" hint.
3. **Segment + render** — if the scripted playthrough produced `script_clips`, frames are sliced per named moment (`_slice_frames_for_script_clips`); otherwise the capture is segmented into clips by scene-boundary detection (`_segment_into_clips`). Each clip → `<name>.mp4` with a sliced audio track. Writes `capture_summary.txt`.
4. **Cleanup** — checksums + done-summary.

### How libpinmame is driven (`pinmame_capture.py`)

**Loading.** libpinmame is located across platform-specific candidate paths (`%USERPROFILE%\pinmame`, VPinMAME under Program Files, Homebrew, `/usr/lib`, etc.) and loaded via `ctypes.CDLL` ([pinmame_capture.py:63](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L63), [pinmame_capture.py:415](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L415)). The full C ABI is bound by hand: `PinmameConfig` struct, callbacks for state/display/audio/mech/solenoid/console/log/sound, and `IsKeyPressed` ([pinmame_capture.py:275](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L275)). Callback objects are stashed on `self._callbacks` so the C side's references stay alive.

**vpmPath.** The user's zip is copied into `<base>/roms/<rom_name>.zip` (LOCALAPPDATA/`pinball_decryptor/pinmame_vpm` on Windows) with `nvram/` and `cfg/` siblings; the path is returned with a trailing separator ([pinmame_capture.py:1501](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1501)). MAME ROMs are **never bundled** — the user supplies their own ([pinmame_capture.py:21](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L21)).

**Boot.** DMD mode is set to **RAW** (one byte per pixel, brightness 0..(2^depth−1)) so the renderer controls brightness mapping ([pinmame_capture.py:1126](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1126)). On a ROM's first ever run there is no NVRAM, which WPC reads as a battery-failure / factory-restore lock screen — so a **throwaway priming boot** runs once to flush a valid `<rom>.nv`, then the real capture boots warm ([pinmame_capture.py:1150](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1150), [pinmame_capture.py:1352](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1352)). NVRAM is deliberately persisted across captures.

**Switch matrix seeding.** After reaching the running state, `_seed_boot_switch_state` seeds a clean attract state from the per-game script: coin door closed, trough full, shooter-lane empty, eject staged or empty depending on whether the switch name contains "jam" ([pinmame_capture.py:562](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L562)). Without this the ROM reads an all-zero matrix as "balls missing" and wedges in ball-search/diagnostics.

**Attract vs simulate_gameplay.** When `simulate_gameplay=True` a daemon thread runs `_gameplay_simulation_loop` ([pinmame_capture.py:802](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L802)): wait out self-test, close the coin door (KEYCODE_END BITTOG toggle), insert 8 coins, press Start up to 3× (acceptance detected by watching for a *new* mechanism-range solenoid sol#1–16 firing within a 1.2 s post-press window), wait out the PLAYER 1 / BALL 1 splash, simulate the ball's trough→shooter-lane→playfield journey, confirm the ball with inlane/sling pulses, then run the per-game script. Cabinet keys (Start, Coin, Coin Door) are driven through the **keyboard** layer (`_press_key` → `_keys_pressed` set → `IsKeyPressed` callback returns 1) because WPC's `SWITCH_UPDATE` handler re-reads those bits from keyboard inports every ~16 ms and would overwrite a raw `PinmameSetSwitch` ([pinmame_capture.py:676](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L676)). With `simulate_gameplay=False` it captures attract mode only.

**DMD frame callback + live preview.** `_cb_display_updated` ([pinmame_capture.py:473](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L473)) appends a `CaptureFrame(timestamp_ms, width, height, depth, data)` per update. libpinmame passes NULL when the frame is unchanged (to save a memcpy) — the previous buffer is re-used so the timeline stays continuous. The frame callback is throttled (~50 ms / ~20 fps) and wrapped in try/except so GUI errors can't corrupt the C stack ([pinmame_capture.py:520](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L520)). The timing origin is reset when the game reaches running state.

**Capture duration / early stop.** The main loop blocks until `duration_seconds` elapses, the emulator stops, or the scripted playthrough finishes plus a 5 s grace window for trailing end-of-ball/game-over animations ([pinmame_capture.py:1406](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1406)). Default duration is 180 s — the scripted tour is ~14 moments × ~10 s plus ~25 s boot overhead ([capture_pipeline.py:62](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L62)).

**Switch-matrix hook.** `capture_ready_callback` fires once with `(manual_press_fn, active_script)` so the GUI can build a diagnostic switch-matrix widget keyed to that game's switch map; `manual_press` pulses a switch high then low and is thread-safe ([pinmame_capture.py:660](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L660), [pinmame_capture.py:1268](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L1268)).

### Per-game scripts (`game_scripts.py` + `wpc_profiles.py`)

Each game's switch map (trough range, shooter lane, launch button, eject, plus a full `raw` name→number map) comes from `wpc_profiles.WPC_GAME_PROFILES`, auto-generated from PinMAME's `src/wpc/sims/wpc/{full,prelim}/<rom>.c` source ([wpc_profiles.py:1](../../pinball_decryptor/plugins/williams/wpc_profiles.py#L1)). A `GameScript` pairs that profile with an ordered list of `GameMoment`s — each a sequence of `SwitchEvent`s (momentary press or sustained set/clear) that the rules say triggers a specific cinematic ([game_scripts.py:130](../../pinball_decryptor/plugins/williams/game_scripts.py#L130)).

- **Rich per-game factories** (`_MOMENTS_FACTORIES`, [game_scripts.py:2220](../../pinball_decryptor/plugins/williams/game_scripts.py#L2220)) are hand-tuned against the rule sheets — AFM, MM, ToM, Fish Tales, White Water, Twilight Zone, Addams Family, ST:TNG, Indiana Jones, Judge Dredd, No Good Gofers, Terminator 2, Demolition Man, Road Show, Scared Stiff, Bram Stoker's Dracula. E.g. `_afm_moments` fires made-ramp/loop sequences, locks, multiball, then clusters all mode-starts at the end (because starting all 4 modes auto-triggers Total Annihilation whose JACKPOT ticker would otherwise dominate every later clip) ([game_scripts.py:649](../../pinball_decryptor/plugins/williams/game_scripts.py#L649)).
- **Generic factory** (`_generic_moments`, [game_scripts.py:412](../../pinball_decryptor/plugins/williams/game_scripts.py#L412)) applies the AFM-derived pattern to any game using only the switch profile: light each ramp/loop with 3 made shots, normal-play moments (saucers/drops/jets/slings/singletons identified by name pattern), mode-starts clustered at the end, plus sparse-data fallbacks that fire every defined playfield switch and the conventional WPC switch ranges.
- Every script is auto-decorated with an `end_of_ball` drain moment so it finishes with the EOB bonus cinematic and signals early-stop ([game_scripts.py:2260](../../pinball_decryptor/plugins/williams/game_scripts.py#L2260)). `get_script_for_rom` matches by exact ROM short name then by prefix, falling back to a generic WPC profile ([game_scripts.py:2315](../../pinball_decryptor/plugins/williams/game_scripts.py#L2315)).
- `run_script` walks the moments against `PinmameSetSwitch`, recording per-moment `MomentClip(name, start_ms, end_ms)` on the same clock as the frame timestamps so the pipeline can slice frames + audio per scene ([game_scripts.py:2350](../../pinball_decryptor/plugins/williams/game_scripts.py#L2350)).

### Per-cinematic MP4 output

`_render_clip` ([capture_pipeline.py:361](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L361)): each captured frame is rendered to a PNG via `_render_brightness_frame` (RAW byte → amber dot at `v/levels` intensity, [capture_pipeline.py:442](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L442)); audio between the clip's start/end ms is sliced to a 16-bit WAV (`_slice_audio_to_wav`, byte-offset by `ms/1000 * sr * ch * 2`, sample-aligned, [capture_pipeline.py:403](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L403)); ffmpeg muxes PNGs (`-framerate` = inverse median inter-frame interval, clamped 8–60 fps) + WAV into an MP4 (`libx264 crf 20`, `aac 128k`, `-shortest`). Scene-cut segmentation (no-script fallback) uses `SCENE_CUT_THRESHOLD = 0.35` pixel diff and an 8-frame blank-gap to break clips, dropping clips under 6 frames or 500 ms ([capture_pipeline.py:69](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L69), [capture_pipeline.py:274](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L274)).

### Combined static + capture (`StaticPlusCapturePipeline`)

[capture_pipeline.py:488](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L488). Runs `ExtractPipeline._run()` first (phase 1, internal phase callbacks swallowed; a static failure is logged as a warning and capture still proceeds), then a `CapturePipeline` whose internal phases 0..4 are remapped to combined 2..5. It overrides `run()` (not `_run()`) and delegates the terminal `done_cb` to the inner capture so the final callback fires exactly once; `cancel()` forwards into whichever sub-pipeline is active ([capture_pipeline.py:515](../../pinball_decryptor/plugins/williams/capture_pipeline.py#L515)).

## DMD / video rendering

`dmd_render.py` is the shared rasterizer for the **static** path (the capture path has its own `_render_brightness_frame` for one-byte-per-pixel RAW frames).

- **Scenes → PNG.** `_render_planes(low, high, pixel_size, color)` ([dmd_render.py:60](../../pinball_decryptor/plugins/williams/dmd_render.py#L60)) draws a 128×32 grid where each lit dot is a `pixel_size−1` square at brightness `level/3` for 4-shade (or full-on for mono). Bytes are decoded LSB-first. `render_scene_png` / `render_plane_to_png` are thin wrappers ([dmd_render.py:99](../../pinball_decryptor/plugins/williams/dmd_render.py#L99)).
- **Animations → MP4.** `render_pngs_to_mp4` copies PNGs into a temp dir as `frame_%06d.png` and runs ffmpeg (`libx264`, `crf 20`, `preset fast`, `yuv420p`) ([dmd_render.py:137](../../pinball_decryptor/plugins/williams/dmd_render.py#L137)); `render_group_to_mp4` renders directly from ROM offsets ([dmd_render.py:182](../../pinball_decryptor/plugins/williams/dmd_render.py#L182)). ffmpeg is located via `spooky.p3_video.find_ffmpeg` ([dmd_render.py:37](../../pinball_decryptor/plugins/williams/dmd_render.py#L37)); the console window is suppressed on Windows (`CREATE_NO_WINDOW`).
- **Fonts.** `_render_font_strip` lays proportional-width glyphs in a 16-per-row grid ([wpc_extract.py:510](../../pinball_decryptor/plugins/williams/wpc_extract.py#L510)).
- **Tint / scaling.** Default color is dark amber `(191, 87, 0)` and default dot size is 12 px (→ a 1536×384 PNG); CGC's WPC remakes reuse this code with `pixel_size≈30` to approximate the LCD backbox ([dmd_render.py:46](../../pinball_decryptor/plugins/williams/dmd_render.py#L46), [wpc_extract.py:108](../../pinball_decryptor/plugins/williams/wpc_extract.py#L108)). The static montage/browse default is slow (2–8 fps) because WPC per-frame hold counts are decided by 6809 code that can't be read statically ([dmd_render.py:22](../../pinball_decryptor/plugins/williams/dmd_render.py#L22), [wpc_extract.py:42](../../pinball_decryptor/plugins/williams/wpc_extract.py#L42)).

## Audio assets

Three audio facets, all read-only:

- **Static DCS decode** — DCS-era ROMs yield per-track WAVs + `manifest.json` under `sounds/` via DCSExplorer (see ROM & audio format above).
- **Capture audio slices** — the runtime path records 48 kHz int16 PCM from libpinmame's audio callback and slices a WAV per cinematic, muxed into each clip's MP4. This is the **only** way to recover audio for pre-DCS YM2151 games ([dcs_decode.py:23](../../pinball_decryptor/plugins/williams/dcs_decode.py#L23)).
- **Transcribe** — `make_transcribe_pipeline` builds the shared `core.transcribe.TranscribePipeline` over the extracted WAVs → `callouts.csv` ([manufacturer.py:135](../../pinball_decryptor/plugins/williams/manufacturer.py#L135)). Visibility is DCS-gated via `audio_export_supported`.

**No Replace-Audio.** `replace_audio` is unset and there is no Write pipeline. The audio is ROM-resident (decoded out of the sound ROMs or captured at runtime), not loose editable files staged for repacking — so the Replace-Audio tab (used by JJP/Spooky/AP/PB/DP) does not apply. Williams is fundamentally extract-only.

## Detection

`detect(path)` ([manufacturer.py:80](../../pinball_decryptor/plugins/williams/manufacturer.py#L80)): returns None unless `is_williams_zip(path)` (the file is a readable `.zip` containing at least one ROM filename listed in any `GAME_DB` entry's `game_roms`/`sound_roms`, [formats.py:9](../../pinball_decryptor/plugins/williams/formats.py#L9)), then `detect_game(path)` scores each game by matching ROM-filename count plus a +1 filename-hint bonus and returns the winner ([formats.py:26](../../pinball_decryptor/plugins/williams/formats.py#L26)). The returned `Game` carries a `notes` badge of `"<platform>, <year>"`.

Williams is registered **second-to-last** in the plugin load order, before `dp` ([registry.py:29](../../pinball_decryptor/core/registry.py#L29)); auto-detect walks plugins in that order. There is **no Clonezilla / disk-image input path** — the hint about Clonezilla in the task does not apply here; the input is strictly MAME ROM zips. (unverified — no clonezilla/ISO handling exists anywhere under `plugins/williams/`).

## Gotchas & non-obvious details

- **Extract-only, no repack.** `write=False`, no `make_write_pipeline`, no Replace-Audio. The user's MAME zip is the source of truth; nothing is written back. The card shows an `"EXTRACT ONLY"` badge.
- **DCS-only audio & transcribe.** Pre-DCS YM2151 titles have no statically decodable audio; `audio_export_supported` hides the audio phase + transcribe controls for them, and the static pipeline renumbers its phases when audio is skipped. The `platform` string in `GAME_DB` is reference-only and does *not* gate DCS — the runtime DCSExplorer probe does.
- **libpinmame licensing.** BSD-3-Clause, invoked as a shared library (no source bundled, no redistribution); MAME ROMs are never shipped ([pinmame_capture.py:17](../../pinball_decryptor/plugins/williams/pinmame_capture.py#L17)). DCSExplorer is likewise BSD-3-Clause (binary bundled in `vendor/`).
- **Capture timing/overhead.** First-run NVRAM priming adds a ~20 s throwaway boot; the real capture defaults to 180 s; Start acceptance is detected heuristically by mechanism-solenoid firings; ctypes display/audio callbacks must never throw (they'd corrupt the C stack).
- **Switch matrix is per-game.** Trough/shooter/eject/launch numbers differ wildly per title and are sourced from PinMAME's per-game sim source via `wpc_profiles.py`. A wrong seed wedges the ROM in ball-search. Cabinet keys must be driven via the keyboard `IsKeyPressed` layer, not raw switch sets, because WPC re-polls them each tick.
- **Beta / actively tuned.** The capture pipeline + per-game scripts are still being tuned per title; the static path is the stable half ([manufacturer.py:25](../../pinball_decryptor/plugins/williams/manufacturer.py#L25)).
- **Platform constraints.** The DCSExplorer binary is bundled only for Windows (other platforms must have it on PATH); libpinmame discovery covers Windows/macOS/Linux but the lib must be installed separately.
- **Unimplemented WPC encodings** are skipped (tallied in `scenes.json`/`scan_summary.txt`), not fatal — a game can extract partially.

## Key files

- [`manufacturer.py`](../../pinball_decryptor/plugins/williams/manufacturer.py) — `WilliamsManufacturer`: capabilities, games, prereqs, pipeline factories, `audio_export_supported` override.
- [`__init__.py`](../../pinball_decryptor/plugins/williams/__init__.py) — `register()` entry point.
- [`games.py`](../../pinball_decryptor/plugins/williams/games.py) — `GAME_DB`: per-title ROM filename patterns, sound ROMs, filename hints, platform/year.
- [`formats.py`](../../pinball_decryptor/plugins/williams/formats.py) — `is_williams_zip`, `detect_game` (scoring), `list_game_roms`.
- [`pipeline.py`](../../pinball_decryptor/plugins/williams/pipeline.py) — `ExtractPipeline` (static), DCS-audio sub-phase, output layout.
- [`wpc_extract.py`](../../pinball_decryptor/plugins/williams/wpc_extract.py) — `extract_dmd_assets`: scenes/pairs/scene-sequences/sub-table animations/fonts (shared with CGC).
- [`wpc_decode.py`](../../pinball_decryptor/plugins/williams/wpc_decode.py) — WPC ROM model, master-table signature scan, address conversion, image-encoding decoders (port of wpcedit.js).
- [`dmd_render.py`](../../pinball_decryptor/plugins/williams/dmd_render.py) — plane → PNG / PNG-sequence → MP4 rasterizer, amber tint, ffmpeg glue.
- [`dcs_decode.py`](../../pinball_decryptor/plugins/williams/dcs_decode.py) — DCSExplorer wrapper: `is_dcs_rom`, `extract_dcs`, manifest.
- [`capture_pipeline.py`](../../pinball_decryptor/plugins/williams/capture_pipeline.py) — `CapturePipeline` + `StaticPlusCapturePipeline`: phases, segmentation, per-clip MP4 render.
- [`pinmame_capture.py`](../../pinball_decryptor/plugins/williams/pinmame_capture.py) — libpinmame ctypes binding, capture session, switch seeding, gameplay simulation, NVRAM priming.
- [`game_scripts.py`](../../pinball_decryptor/plugins/williams/game_scripts.py) — `GameScript`/`GameMoment`/`SwitchEvent`, generic + rich per-game factories, `run_script`, registry.
- [`wpc_profiles.py`](../../pinball_decryptor/plugins/williams/wpc_profiles.py) — auto-generated per-game switch maps (from PinMAME sim source).
- [`vendor/DCSExplorer.exe`](../../pinball_decryptor/plugins/williams/vendor/DCSExplorer.exe) + [`vendor/DCSExplorer-LICENSE.txt`](../../pinball_decryptor/plugins/williams/vendor/DCSExplorer-LICENSE.txt) — bundled BSD-3-Clause DCS decoder.
- [`tests/test_williams_e2e.py`](../../tests/test_williams_e2e.py) — detect(), ROM-size validation, signature-scan on noise, `decode_00` byte-for-byte roundtrip, address conversion, ffmpeg-gated end-to-end.

## Related docs

- [`ap.md`](./ap.md), [`pb.md`](./pb.md), [`spooky.md`](./spooky.md), [`bof.md`](./bof.md) — sibling manufacturer architecture docs.
- Core contract: [`pinball_decryptor/core/registry.py`](../../pinball_decryptor/core/registry.py) (`Manufacturer`, `Capabilities`, `Game`, `InputSpec`).
- CGC plugin reuses `wpc_extract`/`wpc_decode`/`dmd_render` for its bundled-Williams-ROM WPC remakes (MM/AFM/MB).
