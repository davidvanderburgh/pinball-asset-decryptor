# CGC Cactus Canyon (remake) — Card / Asset Reverse-Engineering Notes

Working notes for investigating a **physical factory microSD master card** for the
Chicago Gaming Company *Cactus Canyon* remake (the user's card is branded
"Cactus Canyon Revisited"). Unlike the four titles the existing `cgc` plugin
handles (Medieval Madness / Attack From Mars / Monster Bash / Pulp Fiction —
all distributed as downloadable `*Installer.img` files), this title is **only
distributed on a physical card** (paid expansion, no web download), and its
asset packaging is **new** to this repo.

**Status (session 1, 2026-06-03):** Card imaged, full nested-image chain mapped,
asset inventory complete, formats triaged by moddability. No extraction tool
written yet. Audio (DCS) + logos are the tractable near-term targets; the big
`cgc.so`/`usb.so` blobs are encrypted/packed and need `pin`-binary RE.

## The card image

- Source: USB microSD reader (NORELSYS 1081CS0), Windows `\\.\PhysicalDrive3`.
- Imaged via elevated PowerShell raw `FileStream` read (WSL `--mount` refused the
  USB reader with `0x8007000f`). Card declares 15,931,539,456 bytes; the reader
  faulted on the final ~1.5 MB of **unallocated** tail, so the image is
  15,929,966,592 bytes (14.84 GB) — **all partitions fully captured**.
- Stored at `images/CGC/CactusCanyon_cc113_9-2-25_card.img` (gitignored).
- Investigate from WSL by loop-mounting read-only:
  `losetup -fP --show <img>` → `mount -o ro <loop>p2 …` etc.
  (See `c:\tmp\cc_image\explore*.sh` scratch scripts.)

## Nested-image chain (identical shape to CGC installer `.img`)

The physical card is structured exactly like a CGC **installer** image — it IS a
factory installer/master that flashes the machine's internal eMMC:

```
card.img  (MBR, msdos)
  P1  FAT16  64 MB   @ sector 2048      BeagleBone Black boot (MLO, u-boot.img,
                                        3.8.13-bone40.1.zImage, /dtbs, uEnv.txt)
                                        + empty marker dir  cc113_9-2-25
  P2  ext4   3.3 GB  @ sector 133120    installer Debian rootfs
                                        /home/ubuntu/{cgc,pinstall}, make_master, dcfldd
  P3  ext4   3.0 GB  @ sector 7096320   "data" partition:
        ├── emmc.img         (2.35 GB regular file — the GAME image)
        ├── package.dat      VERSION = 1.1.3 SALOON ; PACKAGE_FILE = emmc.img
        ├── config.dat       active:  MMR_EXEC = pin    @ /mnt/home/debian/pin/
        ├── Xconfig.dat      disabled: MMR_EXEC = emumm @ /mnt/home/debian/emumm/
        └── emmc.img  (MBR)
              P1  FAT16  96 MB           game boot
              P2  ext4   1.7 GB          GAME rootfs — assets under /home/debian/pin/
```

Key facts:
- **Engine = `pin`** (the CGC-original SDL/OpenGL-ES engine, same binary family as
  Pulp Fiction — NOT the `emumm` WPC emulator the MM/AFM/MB remakes use). The
  `emumm` path exists but is disabled (`Xconfig.dat`). `pin` is `ELF 32-bit ARM
  EABI5, dynamically linked, **not stripped**` (symbols present → RE-friendly).
- `package.dat` "Medieval Madness Remake" text is CGC's **templated boilerplate**
  reused across every title — not meaningful. The real title marker is
  `VERSION = 1.1.3 SALOON` ("SALOON" = the Cactus Canyon western theme / I/O-board
  codename; appears in `pin` strings as "USB SALOON").
- This means the existing `cgc` plugin's whole dd/debugfs nested-chain
  (`installer P3 → emmc.img → inner P2`) is directly reusable; what's new is the
  **game** (not in the game DB) and its **asset formats**.

## Game asset inventory  (`emmc.img:P2:/home/debian/pin/`)

```
pin                 2.6 MB   ARM ELF, not stripped — the game engine
fram.bin            8 KB     FRAM/NVRAM snapshot (audits/settings)
init.sh service.sh gpio.sh spi.sh          launch scripts (service.sh runs ./pin, nice -20)
ccdata/
  rom/
    cc_g11.1_3      1 MB     original Bally WPC-95 GAME CPU ROM ("Copyright 1995-1990
                             Williams… System Software by Larry DeMar & Ted Estes"); ".1_3" = v1.3
    s2.rom .. s7.rom 6×1 MB  original DCS SOUND ROM set ("Cactus Canyon Sounds (AV)
                             (c) 1998 Williams")
  dcsrom.c          469 KB   ASCII C source — DECODED DCS sound map (see below)
  art/
    wmsimg.bin      31 MB    "Williams images" — packed display-art library (custom)
    newimg.bin      5.5 MB   "new images" — CGC's added Revisited art (custom)
    gels.bin        573 KB   color "gels"/cels (custom; head = uniform 0xBAF8 RGB565 fill)
    desktop.ini              (stray Windows turd)
  cgc.so            71 MB    misnamed (file magic = "data", NOT ELF) — ENCRYPTED blob,
                             entropy 8.000; header magic bytes "BQ]CCCGC% 1.\x03!\x08\x02"
  usb.so            185 MB   misnamed "data" — packed blob, entropy 7.06 (compressed-ish)
  i2c.so            42 KB    misnamed "data", low entropy — small table/firmware
  font/*.bmp        ~740 KB  DMD/score fonts as Windows BMPs (font_NNhi_table.bmp, score_font_*)
  logo.bmp          77 KB    320×80×24 BMP
  bally.raw bootlogo.raw  800 KB each  640×320 RGBA raw logos
```

`pin` also references `ccdata/attract.bmp`, `ccdata/userlogo.bmp`, `/home/data/{attract,userlogo}.bmp` (custom-logo/attract hooks).

## dcsrom.c — the DCS sound map (the big find)

A complete, human-readable decode of the Cactus Canyon DCS sound ROM, evidently
produced by a CGC/community DCS disassembler. Two structures:

1. **747 command scripts** — `unsigned char dcs_command_XXXX[]` arrays, each a
   byte-annotated DCS command program, e.g.:
   ```
   0x00, 0x00, 0x01, 0x00, 0x4F, 0x1D, 0xD4, 0x01,   // Play sample 4F1DD4 on channel 0 once
   0x00, 0x00, 0x07, 0x00, 0x76,                       // Set channel 0 volume 118
   ```
   `#define DCS_NUM_COMMANDS 747`, `#define DCS_MAX_COMMAND 0x08B7`.
   A `dcs_command[]` pointer array lists `dcs_command_0000 … dcs_command_08B6`.

2. **629-entry sample table** — the audio index:
   ```c
   #define NUM_DCS_SAMPLES 629
   dcs_sample_t dcs_sample[629] = {
   { 0x0000CF20, "CC_00CF20.wav", 1, 267, },   // {rom_addr, suggested_wav_name, field3, field4}
   { 0x0000EDD6, "CC_00EDD6.wav", 2, 222, },
   ...
   { 0x00AFE716, "CC_AFE716.wav", 2, 168, },
   };
   ```
   - `rom_addr` = 24-bit byte address into the DCS sample ROM space (range
     0x00CF20 … 0xAFE716). *(Note: max addr ≈ 11.5 MB exceeds the 6 MB of s2–s7;
     DCS sample addressing / which ROMs are populated needs confirming — unverified.)*
   - field3 ∈ {1,2,4} — likely **channel** or rate/bank selector *(unverified)*.
   - field4 (~120–3222) — likely **length** in frames/blocks *(unverified)*.

   This table is effectively a ready-made extraction manifest: ROM address →
   output filename, for all 629 samples.

`pin` strings confirm a live DCS player: `dcs_load_samplefile`, `dcs_load_samples`,
`dcs_frame_pre_wait_NNNN`. So the original 1998 audio is played from the DCS
`s*.rom` set at runtime (standard Williams DCS), and **DCS extract/replace is the
most tractable audio mod path** — the codec (DCS ADPCM) and ROM layout are
well-documented WPC-95 territory, and dcsrom.c hands us the index.

## Display / animation

`pin` is full of `anim_*` and `*_frame` symbols — the color-LCD "DMD" is rendered
from packed art at runtime (framebuffers via libdrm; `dmd.c`, `dmd_load_screen`,
`Created 3 frame buffers of %dx%d`, `LDMD`). Examples:
`anim_train`, `anim_horse`, `anim_lasso(+_mask)`, `anim_gun`, `anim_quikdraw`,
`anim_raft`, `anim_order_table`, plus mode builders `build_showdown_first_frame`,
`ccc_high_noon_backy_first_frame`, `ccc_topper_*`, `polly_peril`, `stampede`,
`bionic_backy`. The `ccc_*` prefixes + these mode names strongly suggest the card
runs **Cactus Canyon Continued (CCC)**-style code on the CGC remake *(inferred)*.

The art bytes live in `art/wmsimg.bin` (original Williams DMD art) and
`art/newimg.bin` (CGC/CCC new art) — custom packed formats:
- `wmsimg.bin` head: `01 00 00 00` then a long run of zeros → looks like a
  count/header followed by an offset/size table (entries currently zero in the
  first 128 B — real entries likely further in). Needs structural RE.
- `newimg.bin` head: 16-bit little-endian values (`81 fd 81 fd 82 fd …`) →
  looks like raw RGB565 pixel data (0xFD81 etc.), possibly headerless framebuffer
  tiles. Needs RE.
- `gels.bin`: uniform `f8 ba` (0xBAF8 RGB565) → solid-color gel/cel data.

## Display art — SOLVED (session 3, 2026-06-04): cgc.so IS the art archive

**Major correction:** the loose `art/wmsimg.bin` / `newimg.bin` / `gels.bin` files are
**truncated, incomplete copies** (a red herring). The authoritative art lives inside
**`ccdata/cgc.so`** — i.e. the "encrypted" blob above is actually CGC's obfuscated **art
archive**, not audio. Fully reverse-engineered from the `pin` loader and extracted:
**2044/2044 images → PNG** (verified visually; `c:\tmp\cc_image\agent_art\`, copied to
`D:\Cactus Canyon Revisited\art_png\`).

**Container `cgc.so` — custom "CCCG" archive:**
- `[0:4]` stored CRC32; `[4:8]` magic `"CCCG"`; `[8:0x10]` header words; `[0x10:]` obfuscated body.
- Body = sequential members, each a 32-byte header `{char name[16]; u32 size@0x10; u32
  dataptr@0x14 (runtime); u32 @0x18; u32 @0x1c}` + `size` payload bytes. Members (true sizes):
  `wmsimg.bin` 31,419,388 · **`newimg.bin` 40,775,382** · `gels.bin` 1,015,808 ·
  `cc_font.bin` 422,622. Loaded by `z5_ramfile_tarload` (pin vaddr 0x7da48; magic + CRC checked).
- **De-obfuscation** (`z5_ramfile_tarload`): a **stateless per-byte cipher** over bytes `[0x10:]`
  — each output byte depends only on its input byte and absolute index (XOR against index-modulo
  byte tables at .rodata `0xc79c4–0xc79f4` + an index-parity bit-rotate). Reproduced byte-exactly
  by Unicorn emulation of the inner loop (`emu_deobf.py` → `cgc_deobf.bin`); decoded magic/member
  table confirm correctness. *(Not yet simplified to a closed-form pure-Python cipher — needed for
  a plugin integration without a Unicorn dependency.)*

**Image index = static `cc_art` array compiled into `pin`** (vaddr `0xfc694`, **2044 entries ×
60 bytes** — NOT in the .bin members):
- `+0x00 char name[32]` · `+0x20 u32 width` · `+0x24 u32 height` · `+0x28 u32 flag` (0x18/0x20 =
  colourise/blit mode) · `+0x2c u32 data_off` (offset into the pixel buffer, **in 16-bit words**) ·
  `+0x30` three u32 (sub-frame/parallax, usually 0). Accessors `z5_art_get(i)=cc_art+i*60`,
  `z5_art_getpix(i)=pixbase + data_off*2`.
- **Pixel buffer = the `newimg.bin` member** (set by `cgc_image_powerup` @0x4ec28 from
  `z5_ramfile_get(1)`); cc_art's max byte offset == newimg size exactly.
- **Pixel format: 16-bit little-endian RGB565**, row-major `width*height`, no per-image header;
  `0x0000` = transparent. Most images **256×64** (1908/2044 — CGC's 2× upscale of the original
  128×32 Williams DMD); rest are small sprites (50×50 guns, 78×58 riders, 24×24, etc.). Names span
  every mode (bandelero, marksman, high_noon, tumbleweed, topper_bart, …).
- `gels.bin` (colour-cel/tint data, consumed by `text_color_gel*`/`gel_table`) and `cc_font.bin`
  (glyph data) members are decoded but **not** indexed by `cc_art` — they need separate descriptor
  logic to render.

### Two pixel encodings — raw vs RLE (session 4, 2026-06-04)

A frame's encoding is selected by **`cc_art[i].extra[0] & 0x10000`** (the u32 at entry +0x30;
verified against `z5_art_blit` @ pin 0x6dfb0: `ldr r6,[r0,#0x30]; ands fp,r6,#0x10000; bne …RLE`):
- **bit clear → RAW**: `w*h` LE RGB565 words at `newimg + doff*2` (1206 frames).
- **bit set → RLE sprite** (838 frames — `hn_celebration_*`, `hu_eject_*`, etc., with
  transparency): a 16-bit LE token stream, `budget = w*h` pixels:
  - `tok & 0x8000` → **transparent run** of `tok & 0x7FFF` pixels (no payload words);
  - `tok == 0` → no-op;
  - else → **literal run**: the next `tok` words are RGB565, copied verbatim.
  Each RLE frame consumes exactly the byte-spacing to the next frame (independent correctness
  check). Reading an RLE frame as raw gave the "colour noise" that earlier extracts showed.
- `extra[0] & 0x20000` = a horizontal-mirror render hint (raw path); the decoder leaves the
  stored data as-is (visually fine), so the flip isn't applied/needed for extract.

**Integrated** in [cc_art.py](../pinball_decryptor/plugins/cgc/cc_art.py) (`_decode_rle_words`,
`_frame_words`, `read_cc_art` now returns `extra0`). All 2044 frames decode cleanly. **Repack
caveat:** only RAW frames are editable (fixed size, spliced in place). RLE sprites are
variable-length packed *and* their offsets live in `pin` (not the archive), so editing one would
shift every following frame + the baked-in `cc_art` table — `repack_art` skips RLE edits and warns.

### Display-art videos (session 4)

[cc_video.py](../pinball_decryptor/plugins/cgc/cc_video.py): groups `display_art/` frames into
animation sequences (by `<base>_NN` naming; 228 sequences) and renders each to `videos/<base>.mp4`
through the colour dot-matrix shader (`dp.cdmd.render_dmd`) + ffmpeg
(`williams.dmd_render.render_pngs_to_mp4`) — same DMD look as the other CGC/DP videos. Wired to the
"Decode DMD scenes" extract checkbox for Cactus Canyon (off by default; needs ffmpeg). Extract-only
(the engine renders the display live; there are no video files in the eMMC).

## usb.so — SOLVED (session 3): the NEW audio, as raw PCM

`ccdata/usb.so` (193,860,184 B) is **encrypted** (a custom byte transform, NOT compressed
at the container level). Loaded by `dcs_load_samplefile` @ pin 0x52174 → decrypted **in place**
by **`dcs_decrypt` @ 0x52300**. Three stages over the whole buffer (all verified byte-exact vs a
Unicorn emulation of the pin loop):
1. word-level byte-shuffle exchanging the lower/upper file halves;
2. XOR every 32-bit word with `dcsxor13_keys_32[i % 13]` (key object @ VA 0x11a5a8, 13 words:
   `0x53697ca5, 0x1b2d3a4e, …`);
3. a 16-bit running prefix-sum over all halfwords.
Decryption oracle passes exactly: decrypted `hdr[8]^hdr[0xc] == filesize`.

**Decrypted container = a sound bank:** 16-byte header + **756 records of 0x58 bytes**
(`filename`@+0x04, `data_off`@+0x44, `decoded_len`@+0x4C, `sample_count`@+0x50) followed by the
concatenated audio payloads. **VERIFIED the payloads are raw 48 kHz 16-bit mono PCM, NOT
DCS-compressed** (`decoded_len == 2*sample_count` for **756/756**; each record's on-disk gap ≈
`decoded_len`; `silence_100ms.wav` decodes to silence, `mu_DCS0002_muMainPlayLim.wav` is a 45.7 s
music track with a real waveform). So usb.so is **directly extractable to WAV** — slice
`data[off : off+decoded_len]` and wrap in a 48 kHz/mono/16-bit WAV header; no codec needed.
Names confirm this is CGC's **added** content: music (`mu_DCS####_*`), the Continued-style modes
(`StampedeMultiball`, `ShowdownIntro`), speech callouts (`MC_*`, `BOSS_*`, `CC_*`), SFX, loops.
Working decoder: `c:\tmp\cc_image\agent_blobs\decode_all.py` → `usb.dec` + `usb_manifest.txt`.

## i2c.so — SOLVED (session 3): plaintext DCS playlist index

`ccdata/i2c.so` (42,137 B) is **plaintext** (loaded raw by `dcs_load_plfile` @ 0x5225c — two plain
`fread`s, no decrypt). A flat array of little-endian `uint32`: groups of small ascending indices
separated by `0xffffffff` sentinels — the **DCS playlist / sound-group table** mapping sound events
to sample indices in usb.so.

## cgc.so cipher — closed form (for pure-Python plugin port)

(Container/content covered in "Display art" above.) The blob agent derived the de-obfuscation in
**closed form** (the art agent's Unicorn emulation matches it): 16-byte plaintext header
(`+0x00` CRC32 of magic+payload, IEEE table @ pin `crc32Table` 0x1d46c0 seed 0xffffffff no final
invert; `+0x04` magic `"CCGC"` = 0x43474343; `+0x08`/`+0x0c` version/flags, e.g. 0x03312025 /
0x00020821), payload from `+0x10`. Per payload byte `i` (i=0 at file offset 0x10):
```
plain[i] = enc[i] ^ key1[i%3] ^ key2[i%7] ^ key3[i%13] ^ key4[i%17] ^ key5[i%19]
if (i % 5) is odd:  plain[i] = ROL8(plain[i], 3)
```
Keys are pin .rodata objects (prime lengths 3/7/13/17/19) at VAs
`0xc79c4 / 0xc79c8 / 0xc79d0 / 0xc79e0 / 0xc79f4`:
`key1=[10,67,194]`, `key2=[189,94,176,23,207,155,99]`,
`key3=[231,226,119,144,165,34,204,208,36,199,166,20,133]`, `key4=[17,55,116,…,145]` (17),
`key5=[112,163,…,243]` (19). Matches the real pin loop byte-for-byte. This is a stateless function
of `(byte, index)` → portable to pure Python with no Unicorn dependency.

## All surfaces — status

| Surface | Files | Status | Output |
|---|---|---|---|
| Original DCS audio | `rom/s2..s7.rom` | ✅ **in plugin** (extract) | 735 tracks → `dcs_audio/` (DCSExplorer) |
| New audio | `usb.so` | ✅ **in plugin** (extract) | 756 raw-PCM WAVs → `new_audio/` ([cc_usb_audio.py](../pinball_decryptor/plugins/cgc/cc_usb_audio.py)) |
| Color art + fonts | `cgc.so` (`wmsimg/newimg/gels/cc_font`) | ✅ **in plugin** (extract) | 2044 RGB565 PNGs → `display_art/` ([cc_art.py](../pinball_decryptor/plugins/cgc/cc_art.py)) |
| Sound playlist index | `i2c.so` | ✅ understood | uint32 group table (plaintext) |
| Game ROM (rules/DMD) | `rom/cc_g11.1_3` | ✅ known | WPC-95; Williams decoder reads it |
| Logos / fonts | `*.bmp`, `*.raw` | ✅ trivial | plain BMP / 640×320 RGBA |

**Repack / Write — DONE (session 4, 2026-06-04).** All three surfaces round-trip in software
(extract → edit → Write → re-extract → verified; no-op Write is byte-for-byte). Wired as a
`_repack_modified_cc_assets` Write pre-step (mirrors the JPS `_repack_modified_jps_bnks`):
- **DCS** ([cc_dcs.py](../pinball_decryptor/plugins/cgc/cc_dcs.py)): extract now produces
  addressable **streams** (`DCSExplorer --extract-streams`, filename carries the ROM `$ADDR`).
  Repack re-decodes the current ROMs to diff which streams changed, emits a DCSEncoder script
  (`Stream s "<wav>" replaces $ADDR;` — **stride-form** address, e.g. `$4F1DD4`; the folded form
  is rejected), runs `DCSEncoder --patch --rom-size=*` and unzips the new `s2..s7.rom`. Edits to
  any stream rewrite the whole ROM set (DCSEncoder rebuilds it); verified: silencing one stream
  re-extracts silent, others preserved.
- **new audio** ([cc_usb_audio.py](../pinball_decryptor/plugins/cgc/cc_usb_audio.py)):
  `_dcs_encrypt` is the exact inverse (un-prefix-sum → XOR → un-shuffle); `encrypt(decrypt(file))
  == file` verified byte-exact. Repack splices edited PCM (trimmed/padded to the record's original
  length, so the size-check word stays valid) and re-encrypts.
- **art** ([cc_art.py](../pinball_decryptor/plugins/cgc/cc_art.py)): `cgc_reobfuscate` = inverse
  (conditional `ROR8(,3)` → XOR); edits detected in rendered-RGBA space (RGB565→RGBA isn't
  idempotent, so untouched images keep exact bytes), re-encoded to RGB565 into the `newimg`
  member, re-obfuscated, header CRC32 fixed. Edited PNGs must keep their original dimensions.

`DCSEncoder.exe` (v1.1) is bundled alongside `DCSExplorer.exe` in `williams/vendor/`
(`dcs_decode.find_dcs_encoder`). The rebuilt `s*.rom`/`usb.so`/`cgc.so` are real eMMC files, so
the existing CGC debugfs Write injects them unchanged. **Still unverified on real hardware**
(software round-trip only).

## Moddability triage (historical — see "All surfaces" above for current status)

## Moddability triage (for tool-building priority)

| Target | Files | Difficulty | Value | Notes |
|---|---|---|---|---|
| Custom logos / attract | `logo.bmp`, `userlogo.bmp`, `attract.bmp`, `bootlogo.raw`, `bally.raw` | **Trivial** | Low-med | Plain BMP / 640×320 RGBA; drop-in replace |
| DCS audio | `rom/s2..s7.rom` + `dcsrom.c` | **Med** | **High** | Standard WPC-95 DCS; full sample index already decoded |
| Game rules | `rom/cc_g11.1_3` | Med-hard | Med | WPC-95 CPU ROM; risky; advanced |
| Display art | `art/wmsimg.bin`, `newimg.bin`, `gels.bin` | Med-hard | High | Custom packed formats; need structural RE |
| New content blobs | `cgc.so`, `usb.so` | **Hard** | High | Encrypted/packed; need `pin` disasm to crack |

## Reusable from the existing `cgc` plugin

- The nested dd/debugfs chain (installer `P3` → `emmc.img` → inner `P2`) and the
  Write-by-patch-in-place approach apply unchanged — only detection + game DB +
  per-title asset post-steps differ.
- New work: (a) accept a **physical-card image** (or whole-card `.img`) as input —
  detection here can't rely on a `<Game><ver>Installer.img` filename; it should
  read `package.dat`/`config.dat` from P3; (b) add a Cactus Canyon game entry with
  `asset_subtree=/home/debian/pin`; (c) build the per-format extract/repack tools
  above.

## DCS audio extraction — SOLVED (session 2, 2026-06-03)

Approach chosen: **integrate mjrgh's DCSExplorer** (BSD, the same tool that almost
certainly generated `dcsrom.c`). Prebuilt Windows binary:
`DCSExplorer.exe` v1.1 → `https://github.com/mjrgh/DCSExplorer/releases/download/v1.1/DCSExplorer.exe`
(kept locally at `c:\tmp\cc_image\tools\DCSExplorer.exe`). `DCSEncoder.exe` from the
same release is the repack counterpart for later.

**Verified ROM address mapping** (all 629 samples obey it): the `dcsrom.c` global
address packs the ROM at a 2 MB stride —
`rom_file = s[(addr>>21)+2]`, `offset = addr & 0xFFFFF` (bit 20 never set).
`field3` = stream format/channel; `field4` = frame count (~30 compressed bytes/frame,
240 samples/frame @ 31250 Hz). DCSExplorer's own listing uses a *contiguous* 1 MB-stride
flat address instead (its "folded" form), so its stream addresses = `(addr>>21)*0x100000
+ (addr&0xFFFFF)`.

**The DCSExplorer recipe that works:**

1. Pull `ccdata/rom/s2.rom … s7.rom` out of the inner emmc.img P2 (nested dd/debugfs
   chain). Keep the `sN.rom` names — the loader needs the chip digit in the filename.
2. **Zip them into a file whose basename matches `^cc_\d.*`** (e.g. `cc_113.zip`).
   This is REQUIRED: DCSExplorer maps zip files to U2–U9 by *filename digit + an internal
   "S/U<digit> dd/dd/dd" signature* ([DCSDecoderZipLoader.cpp:168-203]). Cactus Canyon's
   **U7 ROM is internally mislabeled "SAV6"** (a Williams factory error — `s7.rom` head =
   `SAV6_8 06/04/98`, same digit as `s6.rom`). The loader has a special case to accept a
   digit-6 signature as U7 *only when the zip basename matches `^cc_\d.*`*. A zip named
   anything else (e.g. `cc_dcs_roms.zip`) silently **drops s7 / loses 90 samples**.
3. Decode all samples to WAV:
   ```
   DCSExplorer.exe -I --silent --terse --extract-streams="<outdir>\" cc_113.zip
   ```
   `-I` ignores checksum mismatches (CGC's set won't match PinMAME CRCs). Output:
   **629 WAVs, 0 errors, 21.1 min, 31250 Hz mono 16-bit PCM**, ~75 MB. Files are named
   `_<track>_<streamidx>_<romaddr>.wav` (romaddr = DCSExplorer flat/folded address).
   `--extract-tracks=` instead exports the assembled command-program tracks.

DCSExplorer auto-recognizes the set: "Known pinball machine: Cactus Canyon / DCS-95 A/V
board, Software 1.05 (1997) / catalog $06000 / max track $08B6 / 6 channels."

**Plugin integration — DONE (session 3, 2026-06-04).** Cactus Canyon is now a game in the
existing `cgc` plugin (reusing the nested dd/debugfs chain), not a separate plugin:
- `games.py` — `cactus_canyon` entry (`asset_subtree=/home/debian/pin`, `data_dir=ccdata`,
  filename hints incl. `cactuscanyon`/`cc113`).
- `pipeline.py` — Phase-3 branch `_extract_dcs_audio(info)`: collects `ccdata/rom/s2..s7.rom`
  (regex `_DCS_ROM_RE`, excludes the WPC game ROM), zips them as `_DCS_ZIP_NAME = cc_113.zip`
  (the `^cc_\d.*` rule), calls the **reused** `williams/dcs_decode.extract_dcs(...,
  ignore_checksum=True)` → `dcs_audio/track_*.wav` + `manifest.json`. `dcs_audio/` is added to
  the checksum `exclude_dirs` and pruned from the Write diff (extract-only; no repack yet).
- `williams/dcs_decode.py` — added an `ignore_checksum` param (default off, Williams unchanged)
  that passes DCSExplorer's `-I`.
- Reuses the already-bundled `williams/vendor/DCSExplorer.exe` — no new binary to ship.
- Tests: `tests/test_cgc_cactus_canyon.py` (detection, ROM selector, zip-name rule, Write-diff
  exclusion). Verified end-to-end on the real card image: detect → nested extract (49 files) →
  **735 DCS tracks** → checksums with 0 `dcs_audio/` entries.

**Still to do:** (a) friendly-name tracks (faster-whisper transcribe already works; or cross-ref
`dcsrom.c`); (b) DCS **repack** via `DCSEncoder.exe` + a Write path that injects edited ROMs back
into the nested image; (c) the other surfaces below (art `*.bin`, encrypted `cgc.so`/`usb.so`).
Bundling note: DCSExplorer/Encoder are Win32 binaries; Linux/mac build from source.

## Open questions / next sessions

1. DCS sample table fields 3 & 4 semantics; confirm DCS address→ROM mapping and
   write a DCS extractor (ROM + dcsrom.c index → 629 WAVs) and repacker.
2. `pin` disassembly: locate `cgc.so`/`usb.so` loaders → container + cipher.
3. `wmsimg.bin` / `newimg.bin` structure (header/offset table; pixel format).
4. Confirm whether new audio is in DCS, in cgc.so/usb.so, or both.
5. Machine round-trip: can a modified card be re-flashed (`make_master`/`dcfldd`
   flow seen in installer P2 `pinstall/`) and boot? (hardware needed).
