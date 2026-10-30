# Spike 1 DMD pictures, fonts and animations (PAD-870)

Extract every picture a Stern Spike 1 game draws on its 128x32 DMD to a PNG,
and write edited ones back into the card. Code: `plugins/stern/spike1_images.py`
on top of S.A.M.'s frame codec (`plugins/pinmame_classic/sam_anim.py`).

## The format

The Spike 1 game program carries S.A.M.'s image engine unchanged (`image.cpp`:
`sys_image_render`, `image_op_table`, the keyframe list). Checked instruction
by instruction on KISS LE 1.41's decompressors:

- Record: `u32 id, u32 flags, s16 width, s16 height, u8 format`, then data.
- Formats 0 raw bytes; 1 / 7 run-length ("whitespace") in column / row order;
  3 / 9 delta on the cached keyframe; 12 raw 4-bit ("row_16"), low nibble
  first. Run-length codes and delta codes are S.A.M.'s exactly.
- Flag 4 keeps a keyframe cached; a delta finds the cached frame whose id
  (low 16 bits) is its own id - 1 or its own; flags 2 / 4 keep a delta cached.

Where it is:

- `hook_image_table_flash_offset` (u64) and `hook_image_table_entry_count`
  (u32) in the game ELF's `.data` name the picture table in `image.bin`:
  that many u64 **file offsets**, records 8-byte aligned. `sys_image_render(id)`
  reads `g_flashmem + table[id]` (the top byte is a bank number, 0 on every
  card). Every Spike 1 program on hand ships its symbol table.
- `hook_font_table_flash_offset` / `_entry_count`: 32-byte fonts
  `{u64 charset, u64 glyph array, u64 size word, 0}`. The charset is `lo, hi`
  byte pairs ending in 0; the glyph array holds one 16-byte entry per
  character (`u64 record offset, i64`), each pointing at a picture-table
  record. The size word's low 16 bits are the height; fonts come in plain /
  outlined pairs (font10 = plain, font11 = its outline, drawn under it).

| Title | Pictures | Glyphs (fonts) | Free front page |
|---|---|---|---|
| KISS LE 1.41 | 24,195 | 1,520 (53) | 1.15 MB |
| Game of Thrones LE 1.37 | 17,159 | 1,406 (32) | 1.15 MB |
| Ghostbusters LE 1.17 | 11,667 | 1,443 (33) | none |
| WWE LE 1.35 | 7,369 | 1,211 (27) | 1.15 MB |
| Whoa Nellie 1.55, Can Crusher 1.01, Primus 1.03 | ~1,460 | ~1,211 | 1.15 MB |

## Where the PNGs go

- `images/fonts/fontNN (H px)/imgNNNN-<char>.png`: a font's glyphs, named by
  their character (`x2C` for a comma).
- `images/pictures/imgNNNN.png`: raw records no delta builds on.
- `animations/imgNNNN.png`: everything else (run-length, 4-bit, deltas and
  their keyframes).

`NNNN` is the table place; five digits on a table of 10,000 or more so the
files sort in the game's order. Grey + alpha, shade `s` as grey `s * 17`.

## Writing

`sam_anim.plan_write` re-encodes each edit in the shortest exact form its place
allows (alone or sharing the run of adjacent movable records), and re-encodes
every delta after an edited keyframe so the DMD shows the edit and nothing else
changes. New for Spike 1 (`ArtTable.entry/align/bank`, `plan_write(spare=)`):

- **The free front page.** `image.bin` on every title but Ghostbusters starts
  with a page shipped erased: 0x38 (or 0) to 0x120000, 0xFF throughout, and no
  `hook_*_flash_offset` points into it. `[0x1000, 0x11F000)` is handed out to
  edited keyframes that don't fit their own bytes (table entry repointed),
  before any picture loses shades. A second build counts the records an
  earlier one put there as held.
- Glyphs are pinned (their font's array points at them): edited in place only.
- A replacement of another size is scaled to the picture's (LANCZOS), as on
  S.A.M.
- The game's power-up flash check is compiled off
  (`framework_powerup_verify_flash_image_check` returns 0), so, as for the
  audio, only the card's `.sidx` record for `image.bin` is refreshed.

## Proof (KISS LE 1.41, Spike 1 emulator)

- **Extract:** attract-mode DMD frames matched against the PNGs: the Stern
  logo (picture 1667, 128x73, scrolled: 198 of 198 frames), the KISS logo
  frames with band silhouettes (`img07549`, `img07562`, `img07585`) and the
  attract text glyphs, all exact.
- **Write:** a card built from edited PNGs showed on the DMD: `img07549`
  replaced by a test pattern (461 bytes, moved to free space at 0x1000),
  `img07562` mirrored (in place), font10 `E` boxed (in place, on the "LEARN
  MORE ABOUT STERN PINBALL" screen); the stock originals no longer appear.
- The power-up screen (title, version, language) draws with fonts built into
  the program: editing image.bin's font09 `E` leaves it unchanged.

Rig: `C:\tmp\PAD-870\rig` (private work dir `/root/s1pad870`, hidden, muted),
matchers in `C:\tmp\PAD-870\scripts` (`matchsprites.py`, `findedits.py`).
