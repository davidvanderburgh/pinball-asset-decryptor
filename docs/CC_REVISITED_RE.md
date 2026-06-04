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

## Encrypted/packed blobs — cgc.so / usb.so

- **`cgc.so`** (71 MB): Shannon entropy **8.000** over the first 2 MB = effectively
  random → **encrypted** (or already-compressed-then-encrypted). Custom header
  `42 51 5D 43 43 43 47 43 25 20 31 03 …` = `"BQ]CCCGC% 1\x03…"` (note the "CCCGC"
  magic). No gzip/zlib/zstd magic. `pin` loads `ccdata/cgc.so`.
- **`usb.so`** (185 MB): entropy ~7.06 (structured/compressed, not pure random).
  `pin` loads `ccdata/usb.so`. Despite the name + nearby USB strings, 185 MB is far
  too large for I/O firmware — together cgc.so+usb.so (256 MB) dominate the 301 MB
  `ccdata`, so the **bulk of new content (new speech/music and/or color animation
  frames) almost certainly lives here** *(hypothesis, unverified)*.
- The `.so` extension is misdirection (none are ELF). `pin` strings include
  `usbcp_decrypt_rx` / `usbcp_encrypt_tx` — there's a crypto path in the binary.
- **Next step for these:** disassemble `pin` (it's *not stripped*) around the
  `cgc.so`/`usb.so` open/read sites to recover the container format + key/cipher.

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

**Still to do for a full repo tool:** (a) wire the nested-image ROM pull + zip-naming +
DCSExplorer call into a `cc` plugin extract pipeline; (b) map the `_<...>_<addr>.wav` names
to friendly names (cross-ref `dcsrom.c`'s `dcs_sample[]`, or run the existing
faster-whisper transcribe step); (c) repack via `DCSEncoder.exe` and inject ROMs back into
the nested image (Write pipeline). Bundling: DCSExplorer/Encoder are Win32 binaries; Linux/mac
would build from source (the project already has per-OS executors).

## Open questions / next sessions

1. DCS sample table fields 3 & 4 semantics; confirm DCS address→ROM mapping and
   write a DCS extractor (ROM + dcsrom.c index → 629 WAVs) and repacker.
2. `pin` disassembly: locate `cgc.so`/`usb.so` loaders → container + cipher.
3. `wmsimg.bin` / `newimg.bin` structure (header/offset table; pixel format).
4. Confirm whether new audio is in DCS, in cgc.so/usb.so, or both.
5. Machine round-trip: can a modified card be re-flashed (`make_master`/`dcfldd`
   flow seen in installer P2 `pinstall/`) and boot? (hardware needed).
