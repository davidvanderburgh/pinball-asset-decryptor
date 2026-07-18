# Stern Pinball (`stern`) — Architecture

> Stern's modern games run on the **Spike** hardware platform and ship their content on an SD card as a raw, MBR-partitioned disk image. The moddable surfaces split three ways by how they're stored: **video** (H.264 clips) and **images** (PNG UI art) sit as ordinary loose files on an unencrypted ext4 partition and extract/patch like any file; **audio** is the hard part — every "category-0" sound is packed into a single `image.bin` container and encoded with a per-sample stream cipher whose keystream is produced by the game firmware itself (and licensed-music titles keep their full songs in additional per-song `image-scNN.bin` banks, decoded and re-encoded by the same codec). There is no static key to recover: the plugin boots the card's own `game_real` firmware in an ARM emulator (unicorn), drives the codec as an oracle to recover each sound's exact keystream, and inverts it analytically — so decode **and** re-encode are bit-exact across all 32 codec "scale" variants, mono and stereo, with nothing title-specific bundled. This document covers **Spike 2** (i.MX6, unencrypted ext4); Spike 1 and Spike 3 are out of scope (see [Scope](#scope--what-spike-2-is-not)).

## At a glance

- **Plugin dir:** `pinball_decryptor/plugins/stern/`
- **Key:** `stern`  ([manufacturer.py:33](../../pinball_decryptor/plugins/stern/manufacturer.py#L33))
- **Display:** `Stern Pinball`  ([manufacturer.py:34](../../pinball_decryptor/plugins/stern/manufacturer.py#L34))
- **Status:** `beta = True` / `badge = "BETA"`  ([manufacturer.py:111](../../pinball_decryptor/plugins/stern/manufacturer.py#L111))
- **Sub-engine:** `plugins/stern/spike2/` — the self-contained unicorn codec oracle (no bundled blobs).

### Supported games

`GAME_DB` lists **26** Spike 2 titles ([games.py:30](../../pinball_decryptor/plugins/stern/games.py#L30)). Crucially, **this list is not what makes a card work** — the engine is title-agnostic. Any card carrying the Spike 2 partition signature is recognised and decoded from *its own* firmware, even if it isn't in `GAME_DB`; an unlisted card is claimed under the generic key `SPIKE2_GENERIC_KEY = "spike2"` ([formats.py:27](../../pinball_decryptor/plugins/stern/formats.py#L27)) and titled from its filename. `GAME_DB` exists only to (a) give the picker a full roster and (b) show a recognised card its proper title rather than a filename-derived one. Each entry is `{display, filename_hints}` — substrings matched case-insensitively against the card filename ([games.py:30](../../pinball_decryptor/plugins/stern/games.py#L30)).

> **Audio coverage:** all 26 titles **decode and re-encode** audio (bit-exact across the codec scale variants), plus video + images. The generic locator resolves every shipped build's firmware shape. Very large builds (e.g. Foo Fighters, Led Zeppelin — large catalogs / big `image.bin`) just take **longer for the one-time params derivation** (several minutes vs ~1–2; cached afterward, so re-runs are instant). `audio_decode_supported` is still a real safety net — if a *future* build's firmware shape can't be located it returns False and that card falls back to video+image-only extraction — but no currently-shipped title hits that path. See [The generic locator](#the-generic-locator-locatepy) and [`audio_decode_supported`](#detection).

### Input extensions / InputSpec

- **InputSpec:** label `"Stern Spike SD-card images"`, extensions `(".img", ".bin", ".raw")`  ([manufacturer.py:73](../../pinball_decryptor/plugins/stern/manufacturer.py#L73)).
- File mode takes a raw card image (`.img`/`.bin`/`.raw`). Direct-SD takes no file — a physical-drive path instead (`\\.\PHYSICALDRIVEn` / `/dev/sdX`).

### Capabilities

Declared at [manufacturer.py:42](../../pinball_decryptor/plugins/stern/manufacturer.py#L42):

| flag | meaning |
|------|---------|
| `extract` | Decode `image.bin` → per-sound WAV (`audio/`) + the per-song `image-scNN.bin` music banks → `music_catNN_*.wav`, copy out videos (`video/`) + images (`images/`) |
| `write` | Re-encode edited cat-0 WAVs + music-bank songs + patch replaced videos/images back into a **copy** of the card image (size-neutral, in place) |
| `modpack` | Standard changed-vs-baseline mod-pack export/import (baseline is `.checksums.md5`) |
| `direct_ssd` | Read from / write to the **physical SD card** directly (radio swaps the file picker for a drive picker). UI wording says "SD card" |
| `replace_audio` | Replace-Audio tab — audio is loose per-sound `idxNNNN.wav` in the extract, so the per-slot tab works (Write re-encodes only the changed ones) |
| `replace_video` | Replace-Video tab — loose `.asset` H.264 clips, patched back in place |
| `replace_image` | Replace-Image tab — loose `.png` UI art, patched back in place |
| `transcribe` | "Auto-name call-outs" — faster-whisper (+VAD) renames spoken WAVs by what's said |
| `music_id` | "Auto-name music" — identify each full music track online via AcoustID + MusicBrainz |

The audio is **not** a loose file in the extract until decoded, and it's encoded — so this plugin uses a *custom* Extract (`image.bin` → per-sound `.wav`) + Write (edited `.wav` → re-encode → patch `image.bin`), not the generic loose-file repack. The Replace-Audio tab still applies because Extract writes the sounds out as loose `audio/idxNNNN.wav` that Write diffs and re-encodes.

### Prerequisites

Declared at [manufacturer.py:85](../../pinball_decryptor/plugins/stern/manufacturer.py#L85):

| tool | probe | why |
|------|-------|-----|
| `unicorn` | `python:unicorn` | Emulate the ARM `game_real` firmware to recover the codec keystream (decode + re-encode) |
| `numpy` | `python:numpy` | Audio sample math for decode / encode |
| `capstone` | `python:capstone` | Disassemble to locate the codec's companding `mul; asr #16` site (keystream recovery) and to run the generic address finder |
| `faster-whisper` | `python:faster_whisper` | **Optional** — only the "Auto-name call-outs" action needs it; extract/write work without it |

`ffmpeg` is also used (auto-named music fingerprinting via its built-in `chromaprint` muxer, and Replace-Video/Image re-encode-to-fit), discovered through `core.audio`/`core.video`; AcoustID lookup uses `urllib` over the network with a shipped application key. None of these block extract/write.

### Phase labels

- **Extract (file, 6):** `Detect`, `Locate partitions`, `Extract video`, `Extract images`, `Decode audio`, `Checksums`  ([manufacturer.py:77](../../pinball_decryptor/plugins/stern/manufacturer.py#L77)).
- **Write (file, 4):** `Detect`, `Stage`, `Re-encode`, `Patch image` ([manufacturer.py:79](../../pinball_decryptor/plugins/stern/manufacturer.py#L79)).
- **Direct-SD extract (6):** `Read SD card`, `Locate partitions`, `Extract video`, `Extract images`, `Decode audio`, `Checksums`  ([manufacturer.py:84](../../pinball_decryptor/plugins/stern/manufacturer.py#L84)). Deliberately the **same 6** as file Extract: `extract_all` drives phase indices 2–5, so the direct phases must line up (only 0/1 are reworded for the card).
- **Direct-SD write (3):** `Scan`, `Re-encode audio`, `Write to SD card`  ([manufacturer.py:87](../../pinball_decryptor/plugins/stern/manufacturer.py#L87)) — `write_device` calls `phase(0/1/2)`.

---

## Card layout & detection

A Spike 2 card is a raw MBR-partitioned disk. The boot/first-ext geometry is fixed by the firmware across every title, edition and card size (only the data + extended partitions grow), which lets detection be cheap and title-agnostic:

```
Spike 2 SD card (MBR)
  partition 0  FAT boot   (type 0x0c), LBA 8192,  16384 sectors (8 MB)   <- signature
  partition 1  Linux ext  (type 0x83), LBA 24576, ...                    <- rootfs (game_real)
  partition 2+ Linux ext  (data — image.bin, videos, images live here)
```

**`_is_spike_card` / `is_spike_card_parts`** require exactly that: an 8 MB FAT boot at LBA 8192 immediately followed by a Linux partition at LBA 24576 ([formats.py:105](../../pinball_decryptor/plugins/stern/formats.py#L105)). It's specific enough not to grab generic Linux SBC images. **`detect_game`** ([formats.py:126](../../pinball_decryptor/plugins/stern/formats.py#L126)) claims any `.img`/`.bin`/`.raw` with that signature: a `GAME_DB` key when the filename hints at a title, else `SPIKE2_GENERIC_KEY`.

MBR parsing is factored into pure byte-level helpers so the same logic serves a file path *and* a raw device's first 512 bytes: `parse_mbr_partitions_bytes` ([formats.py:58](../../pinball_decryptor/plugins/stern/formats.py#L58)), `linux_partitions_from_parts` (ext partitions as byte offset/size, largest first — [formats.py:89](../../pinball_decryptor/plugins/stern/formats.py#L89)), `is_spike_card_parts` ([formats.py:105](../../pinball_decryptor/plugins/stern/formats.py#L105)). The path-based `parse_mbr_partitions`/`linux_partitions`/`_is_spike_card` just read 512 bytes and delegate.

### The pure-Python ext4 reader (`ext4.py`)

`Ext4Reader` ([ext4.py:33](../../pinball_decryptor/plugins/stern/ext4.py#L33)) walks the ext4 data partition read-only — just enough to locate files, read them out, and **map a file byte-range to the underlying disk byte-range(s)** so a size-neutral edit can be written back in place. It handles extent-mapped inodes (modern default) with a classic direct/indirect fallback, and 32/64-bit group descriptors. It takes a *file object* + partition offset/size, so the exact same reader serves a card image (`open(path,"rb")`) or the physical device (a `RawDeviceFile`). Key methods:

- `find_spike_assets()` — locate the game directory (the one holding a regular `image.bin`) and the ARM-ELF firmware (`game`/`game_real`) next to it ([ext4.py:298](../../pinball_decryptor/plugins/stern/ext4.py#L298)). The card ships a top-level `game` *symlink* plus the real `game` ELF; the locator validates ELF magic to skip the symlink (`is_arm_elf` — [ext4.py:284](../../pinball_decryptor/plugins/stern/ext4.py#L284)).
- `extract_file()` / `read_file_bytes()` — stream a (possibly multi-GB) file out, or read it whole ([ext4.py:198](../../pinball_decryptor/plugins/stern/ext4.py#L198)).
- `disk_ranges(inode, file_off, length)` — map a file range to absolute on-disk `(offset, n)` ranges ([ext4.py:160](../../pinball_decryptor/plugins/stern/ext4.py#L160)). This is what makes the size-neutral in-place patch possible: the engine overwrites only the changed bytes at their true disk offsets.
- `iter_regular_files()` / `peek()` — depth-bounded walk + magic sniffing, used to find loose videos/images regardless of name ([ext4.py:255](../../pinball_decryptor/plugins/stern/ext4.py#L255)).

---

## The audio codec (the centerpiece)

Spike 2 audio is the reverse-engineering core of this plugin. Every cat-0 sound is a body of 16-bit words inside `image.bin`; the firmware decodes it with a **per-sample stream cipher** whose mixer applies a linear, invertible volume multiply `G(S) = (QMUL * sxth(S)) >> 16`:

```
MONO:    out[g] = G( ROR16(body16[g], rb_g) ^ K_g )
STEREO:  L      = G( ROR16(u0, rbL) ^ KL )
         R      = G( ROR16(u0, aR) ^ ROR16(u1, bR) ^ KR )   (R is joint in u0,u1)
```

where `K`/`rb` (and `aR`/`bR` for stereo) are the per-position keystream and bit-rotations, `QMUL` is the scale's volume constant, and `sxth` is sign-extend-halfword. There is **no static key**: `K`/`rb` are produced by the firmware per sound. The decode is grouped into blocks of 200 samples.

### Recovering the keystream (the oracle)

The engine boots `game_real` in unicorn (`Spike2Emu` — [emulator.py:160](../../pinball_decryptor/plugins/stern/spike2/emulator.py#L160)) and uses the real codec as an oracle. It installs a hook **right at the companding `mul`** (the `mul; asr #0x10` after the volume multiply, found by disassembly — `_find_companding_all` at [codec.py:100](../../pinball_decryptor/plugins/stern/spike2/codec.py#L100)) and reads the value `S` the firmware feeds it. Driving the codec on crafted probe bodies recovers the exact keystream (`GenRecover`/`StereoRecover` — [codec.py:126](../../pinball_decryptor/plugins/stern/spike2/codec.py#L126), [codec.py:277](../../pinball_decryptor/plugins/stern/spike2/codec.py#L277)):

- decode a **zeros** body → `S = K` (the keystream itself);
- decode a **ones** body → `S = ROR16(1, rb) ^ K`, so `rb` falls out of the one-hot delta (`_onehot_rb` — [codec.py:59](../../pinball_decryptor/plugins/stern/spike2/codec.py#L59));
- stereo needs three probes per block to separate the joint `KL, rbL, KR, aR, bR` ([codec.py:395](../../pinball_decryptor/plugins/stern/spike2/codec.py#L395)).

### Encoding back (analytic, bit-exact)

Once `K`/`rb` are known, encoding is pure inversion — no per-scale port. `invG(target)` finds the nearest 16-bit `S` whose `G(S)` is closest to the desired sample ([codec.py:69](../../pinball_decryptor/plugins/stern/spike2/codec.py#L69)), then:

```
MONO:    body16[g] = ROL16( invG(target) ^ K_g, rb_g )
STEREO:  u0 = ROL16( invG(L) ^ KL, rbL )
         u1 = ROL16( invG(R) ^ KR ^ ROR16(u0, aR), bR )
```

`encode_sound` does this per 200-sample block over the whole sound and returns `(start_off, bytes)` — the size-neutral window the hardware actually reads. On `delta = -1` keys that window starts one word/frame *below* `body_off`, so the trigger-time first sample is written too instead of leaving the stock word there (the start-of-callout click fix) ([codec.py:254](../../pinball_decryptor/plugins/stern/spike2/codec.py#L254), [codec.py:372](../../pinball_decryptor/plugins/stern/spike2/codec.py#L372)).

**The shared boundary word.** That below-`body_off` word is also the *last* word of the layout-predecessor's slot, and the machine renders a sound until its body is exhausted — one sample past the lead-out block on `delta = -1` builds — so hardware decodes that one word twice, once per keystream. Writing `enc[0]` there (v0.59.0) decoded as a random up-to-full-scale sample at the end of every complete predecessor playback (Elvira HoH spinner pair idx4447/idx4448: stock −6 → +7383, an audible pop that survived even a silent replacement). The Write path therefore re-picks that word after the encode: essentially exact for the predecessor's tail (its side is a naked pop in post-fade silence), with our own sample-0 residual absorbed by re-encoding the head of block 0 as a ~4 ms decay ramp (`pick_shared_word` — [codec.py](../../pinball_decryptor/plugins/stern/spike2/codec.py), `_resolve_shared_boundary` — [engine.py](../../pinball_decryptor/plugins/stern/engine.py)). The parallel encode workers receive the card's **full** params table (not just the edited sounds') so each edit can find its layout-predecessor.

### Two per-build calibrations (why it generalises)

The codec model is identical across all 26 builds, but two *build-specific* details are measured rather than assumed (`_calibrate` — [codec.py:177](../../pinball_decryptor/plugins/stern/spike2/codec.py#L177)):

1. **Dominant companding site.** `_find_companding_all` may return several `mul; asr #16` sites in code order; on some builds the first sits in a not-executed path. The calibration picks the site that *actually fires* (most-fired), from a probe decode.
2. **Body-word offset `delta`.** Output sample `i` reads body word `i + delta`: some builds set the body pointer at `base + (cursor-1)` words (`delta = -1`), others at `base` (`delta = 0`). A single 0xFFFF marker probe (rotate-invariant) reveals it. `encode_sound` writes at that offset and margin-fills before the block base so the first sample's keystream isn't recovered from stale memory.

This "measure the two things that vary, keep the one model" approach is what made the engine generalise from the single hand-validated build (TMNT 1.58) to all 26 titles. (Historically these two were misdiagnosed as a "different codec"/"dual-path"; both turned out to be the calibration above.)

### Deriving the per-sound params

Before any decode, the engine cold-derives the decode-params table for every cat-0 sound straight from the card by driving the firmware's own master-directory registration (`derive_params` — [emulator.py:635](../../pinball_decryptor/plugins/stern/spike2/emulator.py#L635)). Each entry is `{idx, body_off, length, chan, scale, ...}`. This is the slow step (~1–2 min for ~2000 sounds; big catalogs like D&D's ~10.5k sounds need more) so it's **cached by a fingerprint** of `game_real` + the `image.bin` master-directory region (`_fingerprint`/`_load_or_derive_params` — [engine.py:45](../../pinball_decryptor/plugins/stern/engine.py#L45), [engine.py:61](../../pinball_decryptor/plugins/stern/engine.py#L61)); re-runs are instant.

### The generic locator (`locate.py`)

The oracle needs ~20 absolute firmware addresses (boot routine, keystream/register bases, the master-directory decoder + its band-build PCs, the codec dispatch table, the body provider, the volume-multiply table). On the one hand-validated build (TMNT 1.58) these are hardcoded; for every *other* title the same routines live elsewhere, so `locate.py` finds them generically from the ELF by string xrefs + instruction-pattern matching, with **no boot required** ([locate.py:1](../../pinball_decryptor/plugins/stern/spike2/locate.py#L1)). It reproduces the TMNT constants exactly (so it's used on TMNT too, drift-free) and drives a bit-exact decode on every other shipped title — including the large Foo Fighters / Led Zeppelin builds (their master-directory decoder is found via the dedicated `_find_masterdir_decode` path). If a *future* build's shape ever can't be fully located, `locate_all` returns `None` and the engine skips audio gracefully (`firmware_build_supported`/`audio_decode_supported` — [emulator.py:134](../../pinball_decryptor/plugins/stern/spike2/emulator.py#L134), [emulator.py:145](../../pinball_decryptor/plugins/stern/spike2/emulator.py#L145)) — a safety net no currently-shipped title hits.

### Self-contained, no blobs

Everything derives from `game_real` + `image.bin`: the firmware's own boot builds the vf2 keystream and runtime tables (no captured `vf2_table.bin`/`cap8_rt_*`); `image.bin` is served to the loader through an offset-identity mmap window paged on demand; the ELF is parsed for segments + GOT import stubs (`elf.py`), and a small red-black-tree helper (`rbtree.py`) mirrors a firmware structure the boot path touches. The only firmware-version coupling is the address set, and that's what `locate.py` removes.

---

## Extract pipeline

`SternExtractPipeline._run()` ([pipeline.py:44](../../pinball_decryptor/plugins/stern/pipeline.py#L44)):

1. **Detect** — `detect_game(input)` or raise.
2. **Locate partitions** — `linux_partitions(input)` (ext partitions, largest first); raise if none.
3. **Extract video / images / Decode audio** — `engine.extract_all()` ([engine.py:303](../../pinball_decryptor/plugins/stern/engine.py#L303)) drives phases 2–5. It opens the disk, streams `game_real` + `image.bin` out to a temp dir (`_extract_inputs` — [engine.py:115](../../pinball_decryptor/plugins/stern/engine.py#L115)), then:
   - **videos** first (quick file copies): every directly-stored video (sniffed by `ftyp` magic, so name/extension don't matter) is copied to `video/`, named from its scene's `scene.radium` (e.g. `Cowabunga_Background`), with a `manifest.txt` mapping output → card path (`extract_videos`/`_parse_radium` — [engine.py:165](../../pinball_decryptor/plugins/stern/engine.py#L165), [engine.py:137](../../pinball_decryptor/plugins/stern/engine.py#L137)).
   - **images** next: every loose image file is copied to `images/`, preserving the card's directory structure, with a `manifest.txt` (`extract_images` — [engine.py:242](../../pinball_decryptor/plugins/stern/engine.py#L242)).
   - **audio** last (the long step): boot the firmware, derive/load params, then decode every cat-0 sound to `audio/idxNNNN.wav` — **across `min(cpu-2, 8)` spawned worker processes** (each boots its own emulator and writes WAVs directly), with a single-process fallback (`_parallel_decode`/`_serial_decode` — [engine.py:549](../../pinball_decryptor/plugins/stern/engine.py#L549), [engine.py:469](../../pinball_decryptor/plugins/stern/engine.py#L469)).
   - **per-song music banks** (`music_banks=True`, the default): the six licensed-music titles (Metallica, D&D, Rush, Deadpool, Foo Fighters, John Wick) keep their songs in `image-scNN.bin` banks outside cat-0. `_extract_category_banks` ([engine.py:420](../../pinball_decryptor/plugins/stern/engine.py#L420)) extracts those banks and decodes each to `audio/music_catNN_MMMM.wav` via `category.extract_category_audio_parallel` — **one task per bank** (size-ordered, `maxtasksperchild=1`), each a *fresh* `CatEmu` that derives then decodes its bank. A fresh emulator per bank is deliberate: deriving several categories on one booted emu accumulates registry state that grinds the loader (see [`spike2/category.py`](../../pinball_decryptor/plugins/stern/spike2/category.py)). 24-bank Metallica ≈ 2.8 min. Titles without banks are a fast no-op.
4. **Checksums** — `generate_checksums()` writes the `.checksums.md5` baseline so Write/Mod-Pack can tell which assets the user edited.

**Output layout:** `output_dir/audio/idxNNNN.wav` (+ `music_catNN_MMMM.wav` for licensed-music titles) + `output_dir/video/<name>.mp4|.mov` (+ `manifest.txt`) + `output_dir/images/<card path>.png` (+ `manifest.txt`) + `.checksums.md5`.

A chained **auto-name** pass runs after a successful extract when the boxes are ticked (wired in `app.py`, not the pipeline): "Auto-name call-outs" (`core/transcribe.py`) transcribes spoken WAVs and renames them `idxNNNN - <text>.wav`; "Auto-name music" (`core/musicid.py`) identifies each full music WAV online and renames it `idxNNNN - Artist - Title.wav`. See [Auto-naming](#auto-naming).

---

## Write pipeline (build an image)

`SternWritePipeline._run()` ([pipeline.py:94](../../pinball_decryptor/plugins/stern/pipeline.py#L94)) → `engine.write_image()` ([engine.py:1165](../../pinball_decryptor/plugins/stern/engine.py#L1165)) produces a **patched copy** of the card image, size-neutral and in place. The patch set is computed by the shared `_compute_patches()` ([engine.py:915](../../pinball_decryptor/plugins/stern/engine.py#L915)):

1. **Diff against the baseline.** Walk `assets_dir` for `idxNNNN.wav` (cat-0) and `music_catNN_MMMM.wav` (music banks) — both index keys survive an Auto-transcribe / Music-ID rename (`idx0651 - text.wav`, `music_cat01_0001 - Battery.wav`) — and read `.checksums.md5`. Only sounds/videos/images whose MD5 differs from the baseline are re-encoded/patched (`_changed_music_banks` — [engine.py:818](../../pinball_decryptor/plugins/stern/engine.py#L818)); an untouched (or merely renamed) asset is skipped. Empty diff → a clear "nothing to write" error.
2. **Re-encode audio** (only if audio edits, and the build's codec is locatable). Boot the emulator, load params, and for each edited sound: verify the keystream recovery round-trips bit-exact for *this* sound before trusting it (`_recovery_valid` — [engine.py:1345](../../pinball_decryptor/plugins/stern/engine.py#L1345)) — a sound whose variant can't be reproduced exactly is **skipped, never patched blind**. Then `encode_sound` yields the new body bytes (`_encode_mono`/`_encode_stereo` — [engine.py:1399](../../pinball_decryptor/plugins/stern/engine.py#L1399), [engine.py:1407](../../pinball_decryptor/plugins/stern/engine.py#L1407)).
3. **Re-encode edited music-bank songs** back into their `image-scNN.bin` banks (`_compute_music_patches` — [engine.py:1419](../../pinball_decryptor/plugins/stern/engine.py#L1419)): the same codec encode + `_recovery_valid` self-test, but on a *fresh* `CatEmu` per bank, and each patch carries its own bank inode (not `image.bin`'s). Validated bit-exact on real songs.
4. **Fit video / image** to the original's byte size (`_prepare_video_patches`/`_prepare_image_patches` — [engine.py:742](../../pinball_decryptor/plugins/stern/engine.py#L742), [engine.py:888](../../pinball_decryptor/plugins/stern/engine.py#L888)): a clip/image `<=` its slot is padded up (a trailing MP4/MOV `free` box, or trailing zero bytes for an image, both ignored by decoders); a larger one is re-encoded/re-compressed down to the byte budget; one that still won't fit is skipped with a warning.
5. **Flatten + apply.** Every patch resolves to absolute `(disk_offset, bytes)` writes via `Ext4Reader.disk_ranges` (cat-0 audio bodies inside `image.bin`'s inode; music songs inside their own `image-scNN.bin` inode; videos/images over their own inode). `write_image` copies the original image to the output, then applies the writes in place (`_apply_writes` — [engine.py:1156](../../pinball_decryptor/plugins/stern/engine.py#L1156)). A video/image-only write **skips the firmware emulator entirely**.

The GUI describes this flow in the Write tab's "?" tips window (`gui/help_dialog.py`).

---

## Direct-SD (read/write the physical card)

Direct-SD points the *same* reader + size-neutral patcher at the physical card instead of an image file — see `plugins/stern/rawdevice.py`. The GUI gates the Direct-SD buttons on Administrator (Windows) / root (POSIX) before these run.

**`RawDeviceFile`** ([rawdevice.py:46](../../pinball_decryptor/plugins/stern/rawdevice.py#L46)) is a seekable byte stream over a raw block device (`\\.\PHYSICALDRIVEn` / `/dev/sdX`) that presents the normal `seek`/`read`/`write` interface `Ext4Reader`/`engine` expect, doing **sector-aligned** I/O underneath — and **read-modify-write** for unaligned writes (block devices reject misaligned offsets/lengths). It probes the logical sector size (512 vs 4096) and clamps to the device length. `is_device_path` / `read_mbr` are the helpers ([rawdevice.py:33](../../pinball_decryptor/plugins/stern/rawdevice.py#L33), [rawdevice.py:195](../../pinball_decryptor/plugins/stern/rawdevice.py#L195)).

- **Extract:** `SternDirectSsdExtractPipeline._run()` ([pipeline.py:126](../../pinball_decryptor/plugins/stern/pipeline.py#L126)) confirms the device is a Spike card + resolves its ext partitions (`engine.device_partitions` — [engine.py:1203](../../pinball_decryptor/plugins/stern/engine.py#L1203)), then calls `extract_all` with `open_disk=lambda: RawDeviceFile(dev)`. Everything downstream is identical to the file path (game_real + image.bin still stream to a temp dir, then decode).
- **Write:** `SternDirectSsdWritePipeline._run()` ([pipeline.py:178](../../pinball_decryptor/plugins/stern/pipeline.py#L178)) → `engine.write_device()` ([engine.py:1242](../../pinball_decryptor/plugins/stern/engine.py#L1242)) computes the *same* patch set via `_compute_patches` (cat-0 audio + music banks + video + images) and applies those exact byte ranges to the card with a writable `RawDeviceFile` (no image copy).

**Safety:** `device_partitions` verifies the Spike 2 partition signature first and **refuses to extract/write the wrong drive** (or one it can't read — e.g. without Administrator, with a message that says so). **No disk-offline/dismount is needed for writes:** every patched byte lives in the **ext4** data partition, for which Windows has no filesystem driver — so it is not a mounted volume, and Windows only blocks raw writes to sectors belonging to a *mounted* volume (the FAT boot partition, which is never touched). An Administrator handle may patch the ext sectors in place. The GUI describes direct writes in the Write tab's "?" tips window (`gui/help_dialog.py`).

> **Hardware status:** the offline byte-equivalence is unit-tested (applying the patch list through a `RawDeviceFile` is byte-identical to patching an image copy). Direct-SD **extract** is verified on a real card (read-from-card == read-from-image); the round-trip **write** to a real card is the last item pending a hardware confirmation.

---

## Replacing audio — length is fixed (size-neutral)

**You cannot make a replacement longer than the original sound.** The encode is size-neutral: the new body is patched back at the original `body_off` with the original byte length (the packed container's master directory uses absolute offsets, so resizing one sound would strand every following offset). Concretely, `_encode_mono`/`_encode_stereo` fit the replacement to `p["length"]` (the original sample count) via `_fit` — **a longer track is trimmed; a shorter one is zero-padded with silence** ([engine.py:1297](../../pinball_decryptor/plugins/stern/engine.py#L1297), [engine.py:1399](../../pinball_decryptor/plugins/stern/engine.py#L1399)). The replacement is also resampled to 44100 Hz (`_load_wav` — [engine.py:1282](../../pinball_decryptor/plugins/stern/engine.py#L1282)) and amplitude-limited into the codec's range (`_amplitude_fit` — [engine.py:1306](../../pinball_decryptor/plugins/stern/engine.py#L1306)). So a longer track won't *break* the game — it's safely trimmed — but it will be **cut off** at the original's duration. This is summarised for the user by `audio_length_note()` ([manufacturer.py:138](../../pinball_decryptor/plugins/stern/manufacturer.py#L138)). The GUI forces the "Trim / pad" toggle **on and disabled** for Spike 2 (with a tooltip explaining why), since the codec always length-matches. **Both `idxNNNN.wav` (cat-0, in `image.bin`) and `music_catNN_MMMM.wav` (per-song banks, in `image-scNN.bin`) are editable and written back** by the same encode path. The same size-neutral principle governs Replace-Video/Image (fit to the original's byte size).

---

## Video & images

Both are loose files on the ext4 partition — no packing, no encryption.

- **Video:** H.264 in an MP4/QuickTime container, stored verbatim as `.asset` files. Extract sniffs the `ftyp` magic and names each from `scene.radium` scene-element identifiers ([engine.py:165](../../pinball_decryptor/plugins/stern/engine.py#L165)). Replace-Video patches the new clip over the original `.asset` inode, size-neutral: padded with a trailing `free` box if smaller, re-encoded down to the byte budget if larger, skipped if it still won't fit (`_pad_isobmff`/`_fit_video_payload` — [engine.py:634](../../pinball_decryptor/plugins/stern/engine.py#L634), [engine.py:703](../../pinball_decryptor/plugins/stern/engine.py#L703)). `video_length_note()` ([manufacturer.py:143](../../pinball_decryptor/plugins/stern/manufacturer.py#L143)).
- **Images:** loose `.png` UI art. Extract preserves the card directory tree; Replace-Image scales the replacement to the original's pixel dimensions and patches it over the inode size-neutral (pad with trailing zeros, or re-compress to fit — `_pad_image`/`_fit_image_payload` — [engine.py:775](../../pinball_decryptor/plugins/stern/engine.py#L775), [engine.py:850](../../pinball_decryptor/plugins/stern/engine.py#L850)). `image_note()` ([manufacturer.py:148](../../pinball_decryptor/plugins/stern/manufacturer.py#L148)).

---

## Auto-naming

Decoded sounds come out as `idxNNNN.wav` (the firmware stores cue ids, not human names), so two optional post-extract passes name them:

- **Voice / SFX → "Auto-name call-outs"** (`core/transcribe.py`, capability `transcribe`): faster-whisper `tiny.en` + VAD transcribes each spoken WAV and renames it `idxNNNN - <text>.wav` (+ `callouts.csv`). The `idxNNNN` prefix is preserved so Write still round-trips. Long non-speech WAVs are tagged `idxNNNN - music.wav` (the music-isolation path). Transcription **fans across a spawn pool** (one Whisper model per worker, cap 8) once there are ≥16 WAVs, with the single-process loop as the small-folder / no-pool fallback; both produce a byte-identical `callouts.csv` (`_transcribe_parallel`/`_transcribe_serial`).
- **Music → "Auto-name music"** (`core/musicid.py`, capability `music_id`): identifies each **full** jukebox track online via **AcoustID + MusicBrainz**. ffmpeg's built-in `chromaprint` muxer makes the fingerprint (no `fpcalc` to bundle); the lookup prefers the pin's band (the dominant artist across the jukebox corpus), then renames `idxNNNN - Artist - Title.wav` (+ `music_titles.csv`). Files another pass already named are **not** candidates (`_already_named`): on a band pin a long Sound-Test SFX carries a song riff, so AcoustID would otherwise stack a second label onto it ("SE FX ZEPPELIN AWARD - Immigrant Song" — monkeybug's Led Zeppelin extract); only bare decodes and the ` - music` isolation tag get titled.

Why online for music: the song→`idx` (master-directory position) binding lives in compiled game **rule logic** the codec oracle never executes — it is **not recoverable** from `game_real`/`image.bin` offline (proven exhaustively). AcoustID is the answer for music titling; do not reopen the firmware→idx RE.

**Sound-Test SFX naming is DISABLED as of v0.63.1** (`engine._load_or_build_sfx_names` returns `{}` unless `PINBALL_SFX_NAMES=1`): content validation on Led Zeppelin 1.22.0 proved the shipped menu→sound binding wrong at the foundation. Evidence, all reproducible from the scratchpad scripts: (1) Whisper found the four **speaker-test voice prompts** inside files named as target/pop blips; (2) the 36 "ELECTRIC MAGIC NOTE n" entries are **not pitch-monotonic** under either candidate mapping; (3) the ~21 shared full-song masters (LZ has **no music banks** — shot/mode events play into shared song tracks) wore arbitrary event names — "SE FX COMBO TERMINATE" on Kashmir (monkeybug's LE), "SEQ BALL SAVE LIT" on the same master (David's Pro); (4) David's known Insider Connect sound (idx0075, Pro) was named "LEFT BANK TARGET UPPER LIT". The OCR of monkeybug's menu video only ever validated *name↔displayed-number*; the broken hop is *number→resolver id*: the true ids for the speaker prompts are **30/32/36** where the displayed-number formula and the menu id-array predict 31/30/28 — no constant offset reconciles them, so the id space has unresolved structure (it appears to interleave related assets). Naming machinery (`sfx_names.py`, now with anchored-vs-broad `_descriptor_refs` + reference-census `_select_names`) is kept for the re-RE; the per-card cache moved to `.sfxnames2.json` so stale wrong-name caches never re-apply. Ground truth to collect: play specific menu numbers in a machine's Sound Test and note what sounds (monkeybug's pending hardware pass).

Two GUI features ride these passes:

- **User rename memory** (`core/name_memory.py`): Replace Audio → right-click → "Rename…" stores the chosen label against the sound's **factory content hash** (the extract-baseline md5) in `audio_names.json` next to `settings.json`. The transcribe pipeline applies these remembered names *first* — pure baseline-dictionary lookups, no hashing — so a manual correction beats Whisper mis-hearing the same clip on every extract, and survives firmware bumps whenever the sound's bytes carry over. Blank rename = restore the stock decode name + forget. Only decode-shaped names (`idxNNNN` / `music_catNN_NNNN`) are renameable; other plugins key Write by full path.
- **Type filter** (`core/audio_categories.py`): the Replace Audio "Type" dropdown (Music / Sound FX / Callouts / Other) classifies each slot after the fact from filename conventions plus `callouts.csv` / `music_titles.csv`. Filename identity (music_cat stem, "SE FX" label) outranks the CSVs — a pre-fix extract has SFX rows inside `music_titles.csv`. The dropdown hides itself when nothing classifies.

---

## Scope — what Spike 2 is *not*

- **Spike 1** (older, e.g. early Spike titles) is not implemented here.
- **Spike 3** (RPi CM4) is a *different and harder* scheme entirely: its SD data partitions are **LUKS2 / AES-XTS** keyed by the 256-bit CM4 customer OTP fuse — hardware-bound, so the key isn't on the card. That is out of scope for this plugin (Spike 2's card is unencrypted ext4).

---

## Gotchas & non-obvious details

- **Audio is the only encoded surface.** Video + images are plain loose files; only `image.bin` is packed/encoded. So a video/image-only Write (or Direct-SD write) skips booting the emulator entirely.
- **No bundled per-title data.** Every sound's params + keystream derive from the card's own `game_real` + `image.bin` at runtime; params are cached by a fingerprint of those two ([engine.py:45](../../pinball_decryptor/plugins/stern/engine.py#L45)). A brand-new Spike 2 title works as soon as its card is recognised — *if* `locate.py` can find its firmware addresses.
- **Music banks: a fresh emulator per bank.** Deriving several `image-scNN.bin` categories on one booted `CatEmu` accumulates registry state so the 3rd-and-later bank's master-directory decode grinds to its instruction cap (minutes/bank). The fix is one fresh `CatEmu` per bank (~13 s flat); decode itself is registry-stateless, so a freshly-booted emu can decode/encode a bank from just its picklable params + the bank file. This is what makes both extract (one task per bank) and write fast and parallel-safe.
- **The firmware ELF is the card-named `game`, not `game_real`.** The card ships a top-level `game` *symlink* plus the real `game` ELF next to `image.bin`; the locator validates ARM-ELF magic to pick the binary, not the symlink ([ext4.py:334](../../pinball_decryptor/plugins/stern/ext4.py#L334)).
- **Re-encode self-test gates every patched sound.** `_recovery_valid` re-decodes a freshly re-encoded sound's own audio and requires it bit-exact over the first blocks before Write trusts it; a sound that fails is skipped (left unchanged), never written blind ([engine.py:1345](../../pinball_decryptor/plugins/stern/engine.py#L1345)). The same gate runs for music-bank songs.
- **Two per-build calibrations, one codec model.** The "dominant companding site" + "body-word offset" are *measured* per build, not assumed; this is what generalised the single hand-validated build to all 26 ([codec.py:177](../../pinball_decryptor/plugins/stern/spike2/codec.py#L177)). Earlier "different codec / dual-path" theories were misdiagnoses of exactly these.
- **Parallel decode/transcribe need guarded entry points.** Decode, music-bank decode, and whisper transcription all fan out across spawned processes (`multiprocessing` "spawn"); the app's entry points are guarded so a worker re-import doesn't re-launch the GUI. A stalled pool falls back to a single process ([engine.py:549](../../pinball_decryptor/plugins/stern/engine.py#L549)).
- **Direct-SD writes need no disk-offline.** The patched bytes are all in the ext4 partition (no Windows volume there), so an admin raw handle writes them in place — unlike SSD plugins that take the disk offline / mount via WSL. The signature check refuses a non-Spike drive before any write ([engine.py:1203](../../pinball_decryptor/plugins/stern/engine.py#L1203)).
- **`rawdevice` is bundled explicitly on Linux/macOS.** It's imported lazily (like `ext4`/`spike2.*`), which PyInstaller's static analysis misses, so it's listed in `installer/build_{linux,macos}.sh --hidden-import`; the Windows `.iss` copies the whole source tree.
- **Large builds derive slowly (not "unsupported").** All 26 titles decode audio; very large builds (Foo Fighters, Led Zeppelin) just take several minutes for the one-time `derive_params` step (cached after). The "video+images only" fallback (`audio_decode_supported` False) is a safety net for a *future* build whose firmware shape can't be located — no currently-shipped title hits it ([emulator.py:145](../../pinball_decryptor/plugins/stern/spike2/emulator.py#L145)).

---

## Key files

- **`manufacturer.py`** ([manufacturer.py:1](../../pinball_decryptor/plugins/stern/manufacturer.py#L1)) — `SternManufacturer`: capabilities, InputSpec, phase labels, prereqs, the medium-aware wording hooks (`audio_length_note` and friends), pipeline factories, `detect()`.
- **`games.py`** ([games.py:1](../../pinball_decryptor/plugins/stern/games.py#L1)) — `GAME_DB` (26 titles, display + filename hints).
- **`formats.py`** ([formats.py:1](../../pinball_decryptor/plugins/stern/formats.py#L1)) — Spike-card detection + MBR/partition helpers (byte-level + path-level).
- **`ext4.py`** ([ext4.py:1](../../pinball_decryptor/plugins/stern/ext4.py#L1)) — pure-Python read-only ext4 reader + `disk_ranges` (the in-place-patch enabler).
- **`rawdevice.py`** ([rawdevice.py:1](../../pinball_decryptor/plugins/stern/rawdevice.py#L1)) — sector-aligned raw-device I/O for Direct-SD (`RawDeviceFile`, `is_device_path`, `read_mbr`).
- **`engine.py`** ([engine.py:1](../../pinball_decryptor/plugins/stern/engine.py#L1)) — orchestration: `extract_all` (cat-0 + music banks), `write_image`/`write_device`, `_compute_patches`/`_compute_music_patches`/`_apply_writes`, `device_partitions`, video/image extract + size-neutral fit, the encode helpers + re-encode self-test.
- **`spike2/category.py`** ([category.py:1](../../pinball_decryptor/plugins/stern/spike2/category.py#L1)) — per-song music banks (`image-scNN.bin`): `CatEmu` (two-window emulator), the generic loader-stub locators, and `extract_category_audio_parallel` (one fresh-emu task per bank). The same derive feeds music-bank Write (`engine._compute_music_patches`).
- **`pipeline.py`** ([pipeline.py:1](../../pinball_decryptor/plugins/stern/pipeline.py#L1)) — the four pipelines (file Extract/Write + Direct-SD Extract/Write).
- **`spike2/emulator.py`** ([emulator.py:1](../../pinball_decryptor/plugins/stern/spike2/emulator.py#L1)) — `Spike2Emu`: boot the firmware, `derive_params`, `decode`, codec-fn dispatch, build-support probes.
- **`spike2/codec.py`** ([codec.py:1](../../pinball_decryptor/plugins/stern/spike2/codec.py#L1)) — `GenRecover`/`StereoRecover`: keystream recovery + analytic bit-exact encode, per-build calibration.
- **`spike2/locate.py`** ([locate.py:1](../../pinball_decryptor/plugins/stern/spike2/locate.py#L1)) — build-independent firmware-address discovery from the ELF.
- **`spike2/elf.py`** ([elf.py:1](../../pinball_decryptor/plugins/stern/spike2/elf.py#L1)), **`spike2/rbtree.py`** ([rbtree.py:1](../../pinball_decryptor/plugins/stern/spike2/rbtree.py#L1)), **`spike2/parallel.py`** ([parallel.py:1](../../pinball_decryptor/plugins/stern/spike2/parallel.py#L1)) — ELF parsing, a firmware red-black-tree mirror, and the multiprocessing decode worker.
- **`core/transcribe.py`**, **`core/musicid.py`** — the two auto-name passes (whisper call-outs; AcoustID music).
- **`tests/test_stern_video.py`**, **`tests/test_stern_image.py`**, **`tests/test_stern_direct_sd.py`**, **`tests/test_stern_category.py`** — size-neutral padding/diff, the Replace-Video/Image patch helpers, the Direct-SD raw-device + MBR-helper + write-equivalence tests, and the music-bank helpers (cat-id parsing, edit detection, no-op skips).
