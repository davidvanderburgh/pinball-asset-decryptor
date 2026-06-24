# Data East / Sega DMD ROM reverse-engineering journal

Goal: extract the DMD (dot-matrix) animation art from Data East / Sega
classic-DMD games **cleanly** — following the ROM's own animation index
instead of blindly slicing the ROM into fixed frames (which interleaves
real art with controller code / tables / padding that decode to "static").

Reference hardware: PinMAME `src/wpc/dedmd.c`. Worked example: **Lethal
Weapon 3** (`lw3_208.zip`, GEN_DEDMD32, 128×32).

## Controller architecture (from dedmd.c)

| Generation | Display | DMD CPU | ROM region |
|-----------|---------|---------|------------|
| DEDMD16   | 128×16  | **Z80**     | 2× banked, last 16KB = static code |
| DEDMD32   | 128×32  | **M6809**   | 512KB = 32×16KB banks; window 0x4000-0x7fff; static 0x8000-0xffff |
| DEDMD64   | 192×64  | **M68000**  | 1MB (2×512K), MRA16 |

- The **last 32KB of the ROM region is the CPU firmware** (dedmd.c memcpy's
  it into the static window 0x8000-0xffff at init). A CRTC6845 drives the
  panel; the firmware copies frame bitmaps into display RAM.
- Main CPU sends the DMD CPU an **image/animation number** via an IO latch
  (0x3000-0x3fff window); the firmware looks it up and renders.

## LW3 (DEDMD32) ROM layout — SOLVED

Two 256KB ROMs concatenate into the 512KB region as **`region = drom1 + drom0`**:
- **drom1 = LOW half** (region 0x00000-0x3ffff): data tables (strings,
  animation index, …). First-32K entropy 6.84.
- **drom0 = HIGH half** (region 0x40000-0x7ffff): **drom0 START = raw frame
  data** (entropy 4.50 — these are the clean frames a naive decode finds);
  **drom0 LAST 32KB = M6809 firmware** (entropy 6.57; reset vector at region
  end). 

Confirmed `drom1`/`drom0` are **independent** content, NOT two grayscale
planes (drom0 frame 441 = garbled, drom1 frame 441 = clean "WHOOPS!";
drom0 460 = static, drom1 460 = clean face). Combining = garbage.

## Pointer tables — LOCATED

Pointers are **3-byte big-endian raw region offsets**. A scan of the 512KB
region for monotonic-ish in-range 3-byte runs (len≥24) found 11 tables:

- `@0x00015` (×39) and `@0x0008a` (×185) → **ASCII string tables** (operator
  menu: lamp-colour names "BLU #38", "YEL-GRN", "RED-VIO" …). NOT frames.
- **`@0x0063c` (×33)** and **`@0x006ea` (×32)** → targets in drom0's frame
  region (0x64xxx / 0x74xxx) at frame-like fill (21-40%). **These are the
  animation/frame index.**

### Frames are COMPRESSED (key finding)

For table `@0x63c`, the 33 pointers have **variable gaps of 62-640 bytes**
(mostly < a raw 512-byte 128×32 frame). Rendering the targets as raw 512B
gives garbage. So frames are **variable-length compressed**, and the gap
pattern (frame 0 largest at 640B, later frames as small as 62B) points to
**keyframe + delta** encoding (full first frame, then per-frame deltas).

First target bytes (`region[0x64202]`):
`f0 00 07 fc 3f e0 00 00 7c 7f e0 00 03 fc ff c0 00 03 f9 ff 80 …`

### Brute-force attempts (did NOT crack it)

Tried on the `@0x63c` keyframe (640B at region 0x64202), scoring output by
image cleanliness (low transitions/row), rendering best candidates:
- raw at 128×40 / 160×32 / 128×32 (with 4/16/128-byte header skips) / LSB-first
  / column-major → all the same horizontal-streak garbage. NOT a layout issue.
- RLE families: hi-bit run/literal (both polarities), (count,value) pairs,
  0x00-run zero-RLE → none render as clean art (hi-bit-literal variant did
  hit outlen≈517≈512B, lit 29%, but still garbled).
Conclusion: **non-standard codec; blind brute-force without ground truth is a
dead end.** Need the algorithm (M6809 disasm) OR a PinMAME-captured frame to
validate candidate decoders against. Keyframe is >raw-512B so output is likely
a 2-plane (4-shade, 1024B) frame.

### Alternative that does NOT need the codec (pragmatic)

The index also tells us what to **skip**: mark every byte range covered by a
pointer table's targets (compressed animations + strings) plus the firmware
(last 32KB) and the table regions, then decode only the **uncovered** region as
raw 512B frames. drom0 demonstrably contains clean uncompressed frames
(VICTORY/skyline decode raw); structural skipping of the compressed/code
regions should remove the bulk of the junk the per-frame heuristic can't.
Cleanliness depends on how much of the ROM is uncompressed.

## Remaining work (next session)

1. **Crack the decompression codec.** Best path: disassemble the M6809
   firmware (drom0 last 32KB → CPU 0x8000-0xffff) and find the decompress
   routine the latch handler calls. Need an M6809 disassembler (capstone
   has none — write a small one or find a lib). Alternatively, brute the
   delta/RLE format from compressed-bytes↔known-output pairs (we can get
   ground-truth frames from a PinMAME capture to compare against).
2. Confirm the per-animation structure (does a table entry = one frame, or
   one animation header with a frame count? gaps suggest per-frame).
3. Repeat for **Z80 (DEDMD16, e.g. TMNT)** and **M68000 (DEDMD64, Sega
   192×64)** — different CPUs, likely the same compression family.
4. Integrate into `plugins/pinmame_classic/dmd.py`: parse the index →
   decompress → emit clean per-animation PNG/MP4. Replaces the interim
   heuristic `classify_frame` noise filter.

## RESOLUTION: capture-only (static decode removed)

The "remaining work" above was **not pursued** — PinMAME already solves the
compression by emulating the firmware. The libpinmame capture produces clean
4-shade animations + audio (43 real animations on LW3 vs the static decode's
19 half-junk clips like `anim_00350`, which is raw decode wandering into a
compressed region). The static raw-decode could never cleanly separate junk
from real frames (proven statistically inseparable).

So `plugins/pinmame_classic` is now **capture-primary**: `Capabilities(
extract=False, capture=True)`; `capture.py` runs libpinmame in attract mode →
`captured/anim_*.mp4`. The static decoder (`dmd.py` + `pipeline.py`) was
deleted; the GUI hides "Basic extract" for capture-primary plugins
(`caps.capture and not caps.extract`).

This journal stays as the reference if the offline static path is ever wanted:
the animation index is pointer tables (LW3 `@0x63c`, `@0x6ea`), frames are
keyframe+delta compressed, and decoding needs the per-generation firmware
decompressor (M6809 / Z80 / M68000).
