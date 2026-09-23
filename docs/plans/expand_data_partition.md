# Build a Spike 2 card for a bigger SD card (grow the games partition)

## What and why

David, 2026-09-23, after PAD-176: *"it would be nice to be able to expand the
data partition so that we have more room to use on the SD card. investigate
getting that done and prove it e2e that it is safe to do."*

PAD-176 was a modder's build (542 replaced videos plus a grown sound bank)
that encoded for twenty minutes and then failed with "not enough free space".
The partition that fills up is the card's **games partition**, p3, where every
file a build copies on whole lands. On an 8 GB class card it has only what
Stern left free: **368 MB on a stock Godzilla Pro 1.16** (89,975 free 4 KiB
blocks). The SD card in the machine is usually 16 or 32 GB, and the rest of it
goes unused. PAD-176 made the failure say how far over the build is. This
branch gives the build the room instead. (It is not the /data partition, p5,
which holds the machine's settings; that one moves, unchanged.)

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
sector count and entry 4's start LBA. CHS is capped (03 e0 ff) in every class,
and both EBRs are byte-identical because they are relative to p4. The MBR disk
id also differs by class, but Stern's own 8G cards already ship with two ids
and nothing on the machine reads it, so a grown card keeps its original's. The
p3 filesystems share one feature set (4 KiB blocks, no 64bit, no
metadata_csum), and an 8G p3's 408 reserved GDT blocks cover growth to 32G
with nothing relocated.

**Mechanism** (`pinball_decryptor/plugins/stern/card_size.py`, called from
`engine.write_image` / `engine._expand_card`):

1. **Before anything is copied or encoded:** `target_for` checks the original
   is laid out exactly like the table above: a Stern class size, two logicals,
   not a multi-boot card (a store card looks stock from its table, so
   `multiimage` is asked), and no games-partition journal waiting to be
   replayed. `check_tools` checks the loop device and e2fsprogs, only when a
   whole build will really grow (an update of an already-grown build needs
   neither).
2. The build copies the original and writes its in-place patches as always.
   Those offsets come from the ORIGINAL's extents, and p3 starts where it did.
3. **`expand_image`, after the in-place patches and before the whole-file
   copies:**
   - grow the file sparsely (on Windows: sparse flag plus the last byte;
     `truncate` would write every zero, 29 s for 8 GB);
   - copy [p4 start, image end) back to front to its new place, never
     writing zeros over zeros, and read both copies back to compare them;
   - **commit:** rewrite the two MBR fields and re-read the layout;
   - zero the vacated old range (a hole on NTFS);
   - `e2fsck -fp`, `resize2fs <p3 sectors>s`, `e2fsck -fn`, in one script
     against a **loop device bounded to p3** (`losetup -o OFF --sizelimit
     SIZE`, any stale loop on the image detached first). The clock is pinned
     to the original p3's epoch and the new inode tables are zeroed
     (`RESIZE2FS_FORCE_ITABLE_INIT=1`).
   - The file must keep its class size to the byte and read back as the
     planned table.
4. `check_blocks_unmoved`: every regular file on p3 has the extent map it had
   on the original. Any failure discards the output. A cancel is a cancel.
5. The build record keeps the ORIGINAL's partitions and adds `card_size`.
   `build_update_reason` builds whole when the size differs, and
   `_update_plan` compares against `card_size.output_parts`.
6. The option is `PAD_STERN_CARD_SIZE` (`16G` / `32G` / unset), set by the
   Write tab's **SD card size** control (not offered on macOS, for a
   multi-boot card, for a 32 GB original or on a direct SD write).
7. A no-space failure says to build for a bigger card when the Write tab
   would offer one for this original.
8. **Room is checked before the encode** (PAD-176's other half, `engine._SpaceCheck`,
   design in `docs/architecture/stern.md` "Room on the games partition"). The
   build adds up what it copies whole against the games partition's usable
   room at its SD card size, before anything is encoded or written. That
   covers each assigned clip (settled to the file that will really go on),
   the grown sound bank at its exact length, and upper bounds for mode files.
   Longer sounds are trimmed to fit. A build whose videos don't fit is refused
   with the numbers and the smallest SD card size that fits. The file at the
   output is left untouched, because the copy over it starts only once the
   check passes. An update that fits only as a whole build becomes one.
   `write_preflight` refuses even earlier, before the app converts any clip,
   when a floor of the need can't fit. The Write tab's note gives the real
   free room at each size. The texts about longer sounds and full-size
   videos name both limits: the game's 2 GB bank, and the partition's room,
   which only a bigger card raises.

**Never `resize2fs IMG?offset=N`.** Handed a regular file, resize2fs 1.47.0
finishes by truncating it to the filesystem's length, offset or not
(resize/main.c:683). The first real-card run cut a Godzilla image off 365 MB
into the grown p3, taking the moved /data and /dump with it, and the
`e2fsck -fn` after it still passed. That is why the loop device, the size
check and the table re-read exist.

**What it deliberately does not do:** shrink; grow a multi-boot card (the
Multi-boot tab sizes those); grow on macOS (no loop devices; an `hdiutil`
route is possible but untested); choose the size by itself; touch a card in a
reader; size to the physical card (always a Stern class size, which fits any
card of that class).

## Status

- **2026-09-23: done on the branch, emulator-proven. Owed: a hardware boot.**
  Commits: `b2e6dd0d` core, `711cda6f` loop device (the truncation fix),
  `7ce92190` Write tab, `1c8403d5` hardening, then the final review's fixes.
- Proven on real cards (scratchpad scripts `e2e_stageA*.py`, `e2e_stageB_*.py`,
  `e2e_stageC_build.py`):
  - **Stage A** (78/78 checks): godzilla_pro 8G→16G, 8G→32G and jaws_le
    16G→32G. Partition tables are byte-identical to Stern's own card of the
    class, every p3 file is byte-identical and in its original blocks, p1, p2
    and u-boot are unchanged, /data and /dump are identical at their new LBAs,
    e2fsck is clean on p3/p5/p6, and the kernel mounts them. Free space on p3
    goes from 368 MB to 7.87 GB (16G) or 22.5 GB (32G).
  - **A2:** a /data holding 1,333 real settings/NVRAM files and 51 MB of logs
    moves hash-identical.
  - **A3:** two expansions with the pinned clock are byte-identical, and so is
    the final code's output against the earlier revision's. 108 of 108 inode
    tables are zeroed, as on Stern's 16G card. The card's OWN e2fsck 1.42.9
    (ARM, under qemu) passes. The pending-journal library card
    (turtles_le 1.58.1 "1987") is refused in 0.04 s.
  - **Stage B** (real builds through `SternWritePipeline`, 20 replaced clips
    growing p3 by 1.6 GB): at 8G it fails with PAD-176's numbers and the
    bigger-card hint. At 16G it builds in 70 s with every clip byte-identical
    to its source. A changed clip updates in place in 7 s, and choosing 32G
    rebuilds whole.
  - **Stage C** (emulator, rig lock held, muted): the 16G build boots through
    Guided Setup to attract, and a game plays (Big Loop shots register). The
    game decoded a grown clip, and all 28 grown files hash-identical through
    the rig's own fuse2fs mount, 20 of them entirely in block groups the 8G
    filesystem never had.
- A review sweep (engine, app, machine rootfs, resize2fs source, critic) and a
  final adversarial review (4 lenses, each finding put to a skeptic) found no
  data-safety defect in the final code. Their fixes are in.
- **Owed before calling it hardware-confirmed:** flash a 16G build and a 32G
  build to real SD cards and boot a machine. Check that the game reaches
  attract, settings and audits survive (p5 moved verbatim), a Stern `.spk`
  update installs onto /games, and a power cycle's boot fsck is clean. The rig
  never runs the card's kernel 3.14 or its init, so the emulator cannot prove
  those.
- **2026-09-23, second pass: the room check before the encode.**
  - Checkpoint commit `753673a3`, then the review fixes. Three reviewers found
    12 confirmed defects in the first cut, then 10 more in the fixes, and
    each was put to a skeptic. All 22 are fixed with tests.
  - The worst one: a refused whole build waited out the 7.8 GB copy and then
    deleted the build already at the output.
  - Proven on the real card (scratchpad `e2e_stageD_build.py`, project
    `C:\tmp\expand_e2e\gzproj2`, Godzilla Pro 1.16 audio + video, four songs
    lengthened to 10 min):
    - At 8G the bank budget trimmed one song, named 16 GB, and built.
      The partition used exactly the predicted 77,522 blocks plus 1 block of
      slack. The bank on the card is exactly the predicted 1,967,189,954 bytes.
      e2fsck is clean.
    - With 20 clips (+1.61 GB) at 8G, the final code refuses a whole build over
      an existing build in 0.9 s (it was 49 s). The copy never starts, and that
      build stays byte-identical (sha256, mtime, record). An update onto it is
      refused in 0.5 s with the whole build's numbers (352 MB here, 7.87 GB at
      16 GB). The refusal is logged, and it names the clips by their project
      file names.
    - At 16G with four songs and 20 clips, the pre-flight kept all four songs
      whole (bank 2,073 MB of the game's 2,147 MB) and measured 2.03 GB needed
      of 7.87 GB. The build encoded everything, then the grow step failed
      because WSL on the dev PC wedged (19:42, the second time that evening).
      The build discarded the output and said why.
  - **Still owed:** that 16G build run to the end (prediction vs actual use),
    and its update in place (`e2e_stageD_build.py d16 dupd`), once WSL is back.
- Follow-up (not this branch): a grown build used as a multi-boot primary
  (mkmulticard's store sizing and the Multi-boot tab's size strip), filed as
  a separate task.

## How to test it

- Targeted: `python -m pytest -q -p no:cacheprovider tests/test_stern_card_size.py tests/test_webui_card_size.py tests/test_pad176_no_space_report.py tests/test_stern_space_preflight.py tests/test_stern_space_hook_preflight.py tests/test_stern_space_port.py tests/test_stern_space_text_notes.py`
  (also run them under WSL: new test modules have failed on CI at first contact).
- Real input: the scratchpad stage scripts above. Each copies 8-30 GB to
  C:\tmp\expand_e2e, and they never write under D:\Pinball\images.
- In the app: Write tab, SD card size "16 GB card", Build. The log says "This
  build is for a 16 GB SD card" and "The card is a 16 GB card now", and the
  build is 15.49 GB.
