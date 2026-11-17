# Multi-boot: swap one image in place (PAD-1386)

pb_lawww (Pinside, Godzilla stock + Heisei multi-boot): "is there a detailed
description how to update one of the multi boot images of a project to replace only
the changed files? I believe when I swapped images, the whole card was re-built."

## What was there

`mkmulticard.py update` (item 93) already wrote a card in place from its record
(`trees.json`): a source edited at the same path was diffed file by file, and the
tab's Build / flash dialog already offered "Update the loaded card in place" for an
image-list change.  Three things stood in the way of a swap:

1. **A swapped image was "remove + new".**  `treesync.match_trees` knows a recorded
   tree by its source path or stamp; a newer build at another path matched neither,
   so the slot's tree was removed and the new one written whole.  On a real card
   (stock Godzilla LE + Heisei v36, parts layout) swapping in Heisei v38 needed
   9.84 GB in p7 with 5.47 GB free: main's tool refused it ("build a fresh card").
2. **The tab said the opposite of the dialog.**  The sentence under the card path
   said an image change needed a fresh card (in red), and Apply refused it with the
   same advice - over a card the dialog would update in place.
3. **Modes stayed behind.**  The update re-injected the menu (which carries each
   image's custom modes) only when the image list or menu text moved, so a swapped
   image booted the OLD image's modes.

## What changed

- `update` pairs a new image nothing else claimed with the removed tree in its own
  slot, AFTER the same-tree matching (so an image that only moved is still kept or
  renamed).  The diff writes only the files that differ; the row says `replace`.
  Parts, multi and store layouts alike.
- `mode_sets_moved` compares every image's modes with `MODES_DIR/img<N>` on the card;
  any difference re-injects.
- The tab: `edit_status_text` / `card_path_state(updatable=...)` name the in-place
  update on a Stern card with a record (not from the reader, not refused by the
  tool), and `apply_to_card` hands such a change to `update_card`.

## Proof

- Selftest (WSL root): parts, multi and store each swap one image for a copy at
  another path with one extra file, and back: one file written each way, `replace`
  rows, no new/remove, full verify PASS.  Part 9 pins the modes comparison.
- Real card, `/var/tmp/pad1386/gz.multi.raw` (LE 1.16 + Heisei v36, 22.4 GB parts
  layout, built in 76 s from the card cache): swap to Heisei v38 = 390 files,
  4.29 GB, 45 s, menu re-injected with v38's modes, full verify PASS; main's tool
  on the same card: refused (no room).  A second update: nothing to write.
- Emulator (rig 1, hidden, muted, x4): image 0 `[select] chose 0 Godzilla`, attract
  at 144 s; image 1 `[select] chose 1 Heisei` (p7, bound over /games/godzilla_le),
  attract at 133 s; clean teardown both.
