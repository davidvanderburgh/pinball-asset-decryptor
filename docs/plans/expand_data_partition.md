# Build a Spike 2 card for a bigger SD card (grow the games partition)

## What and why

David, 2026-09-23, after PAD-176: *"it would be nice to be able to expand the
data partition so that we have more room to use on the SD card. investigate
getting that done and prove it e2e that it is safe to do."*

PAD-176 was a modder's build (542 replaced videos plus a grown sound bank)
that encoded for twenty minutes and then failed with "not enough free space on
the card's data partition". That partition is the card's games partition, p3,
where every file a build copies on whole lands. On an 8 GB class card it has
whatever Stern left free: **368 MB on a stock Godzilla Pro 1.16** (89,975 free
4 KiB blocks). The SD card in the machine is usually 16 or 32 GB, and the rest
of it goes unused. PAD-176 made the failure say how far over the build is. This
branch gives the build the room instead.

## Design

**Stern already ships the same card at three sizes.** Read off the stock
images (godzilla_pro 1.16 8G, jaws_le 1.02 16G, metallica 1.03 32G):

| | 8G | 16G | 32G |
|---|---|---|---|
| p1 FAT boot | 8192 / 16384 | same | same |
| p2 rootfs | 24576 / 688128 | same | same |
| p3 games (ext4) | 712704 / 13402110 | 712704 / 28311550 | 712704 / 57343998 |
| p4 extended | 14114816 / 1239038 | 29024256 / 1239038 | 58056704 / 1239038 |
| p5 /data, p6 /dump | 147454 and 1089534 sectors | same | same |
| image bytes | 7861174272 | 15494807552 | 30359420928 |

The only partition-table bytes that differ between classes are MBR entry 3's
sector count and entry 4's start LBA. The CHS fields are capped (03 e0 ff) in
every class, and both EBRs are byte-identical, because they hold addresses
relative to p4. The p3 filesystems share one feature set (`has_journal
ext_attr resize_inode dir_index filetype extent flex_bg sparse_super
large_file huge_file uninit_bg dir_nlink extra_isize`, 4 KiB blocks, no 64bit,
no metadata_csum). An 8G p3 has 408 reserved GDT blocks, so growing it to 32G
(219 groups) needs no metadata relocation.

**Mechanism** (`pinball_decryptor/plugins/stern/card_size.py`):

1. `preflight` at the start of `engine.write_image`: the original is a card
   laid out exactly as above (a stock class size, two logicals; a multi-boot
   card is refused, including a store card, which looks stock from its table),
   and resize2fs can run here. A refusal takes seconds, before any encoding.
2. The build copies the original and writes its in-place patches as always.
   Those offsets come from the ORIGINAL's extents.
3. `expand_image` (called from `engine._expand_card`, **after** the in-place
   patches and **before** the whole-file copies through the ext4 driver):
   - grows the file sparsely (on Windows: sparse flag plus the last byte;
     `truncate` would write every zero),
   - copies [p4 start, image end) verbatim to its new place, back to front,
     and reads both copies back to compare them,
   - **commit point:** rewrites the two MBR fields, then re-reads the layout,
   - `e2fsck -fp` p3 (resize2fs refuses a filesystem mounted since its last
     check, and every stock p3 has been mounted), `resize2fs IMG?offset=N
     <blocks>`, then `e2fsck -fn` must exit 0. All of this runs against the
     image with `?offset=`, with no loop device and no root, through the same
     executor as ext4_grow (WSL on Windows, native on Linux, Homebrew
     e2fsprogs on macOS).
4. `check_blocks_unmoved`: every regular file on p3 must have the same extent
   map as on the original. Any failure in 3 or 4 discards the output. A card
   the user asked to be bigger is never handed back at the original's size.
5. The build record (`.pad-build.json`) keeps the ORIGINAL's partitions and
   records `card_size`. `build_update_reason` builds whole when the size asked
   for differs from the recorded one. `_update_plan` compares the output
   against `card_size.output_parts` (p3 longer, p2 unchanged; the app's MBR
   reader never sees p5/p6).
6. The option is the env var `PAD_STERN_CARD_SIZE` (`16G` / `32G` / unset),
   set from a persisted Write tab setting ("SD card size") like the other
   Stern build options. When it is unset, nothing changes for any caller.
7. A no-space failure (PAD-176's message) now adds: build for a bigger card.

**What it deliberately does not do:** shrink; grow a multi-boot card (the
Multi-boot tab sizes those); pick the size by itself from the build's needs;
touch a card in a reader (Direct SD writes are unchanged); size the image to
the physical card (it is always one of Stern's class sizes, so it fits any
card of that class).

## Status

- 2026-09-23: module, engine wiring, unit tests (`tests/test_stern_card_size.py`,
  18 pass in ~26 s: Stern's own tables for 8G→16G, 8G→32G, 16G→32G, refusals,
  byte move on sparse synthetic cards, stubbed e2fsprogs). Write tab control in
  progress. Real-image end-to-end proof running (see below).

## How to test it

- Targeted: `python -m pytest -q -p no:cacheprovider tests/test_stern_card_size.py`.
- Real-image proof (scratchpad scripts, not in the suite, because each copies
  8-30 GB): Stage A runs `expand_image` on real stock cards and checks them
  against the source and Stern's own card of that class. Stage B is a real
  build that overflows 8G, built at 16G, then updated. Stage C boots the build
  in the emulator. See the Status lines for results.
- In the app: Write tab, SD card size 16 GB, Build; the log says the card was
  made a 16 GB card, and the build is 15.5 GB.
