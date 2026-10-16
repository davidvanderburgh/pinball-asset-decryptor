# Extra sound banks on a title that ships with one (PAD-595)

David, 2026-10-16: "I want to be able to have unlimited number of new sounds
and songs on any Spike 2 game ... make the app build new ones."

## The limit

A Spike 2 game opens `image.bin` with the 32-bit calls, so a sound bank past
2 GiB reads no sounds (PAD-175/176), and a loader patch that opens a bigger
one (PAD-593) still played a sound stored past the 2 GiB mark as white noise:
the game streams long sounds with 32-bit reads. So on a title with ONE bank,
every appended sound -- a longer replacement, the modes' own calls and music
beds, a music mode's files -- shares whatever `image.bin` has left under 2 GiB.
The tester's Heisei V1.99D card is a 2.01 GB `image.bin` (2643 records) and
David's eleven modes want 250 MB more.

## What the game does with banks (Godzilla LE 1.16, read from its program)

Six music titles keep their songs in `image-scNN.bin` banks beside `image.bin`
(`spike2/category.py`). The boot tail (`0x4d6318`) does, after
`MASTERDIR_DECODE(0)`:

    n = hdr0[0x68]                       # 0x3b5a68: image.bin's category count
    for i in 0..n-1:
        cat = hdr0[0x6c + 4*i]           # 0x3b5a88: the id array, in image.bin's header
        load_category_assets(cat)        # 0x3b5aac: open "image-sc%02d.bin" % cat, fstat, mmap,
                                         #           copy its first 0x68 bytes, keep base + size
        MASTERDIR_DECODE(cat)            # 0x4d4c4c: decode its directory, band-build every record
        release(cat)                     # 0x3b5758: munmap it (cat 0 is never released)

`load_category_assets` builds the file name from the id alone and reads
nothing of the bank but its first 0x68 bytes (the header) and its size. Header
fields are reached through `container_get(cat, field)` (counts at
`hdr+0x50/0x54/0x30/0x5c/0x60/0x64`) and `container_ptr(cat, field)` =
`base + hdr[8*field]` (field 5 = `hdr[0x28]`, the fragment table; 8 =
`hdr[0x40]`, the master directory; 9 = `hdr[0x48]`). A released bank is
mapped again on its first play through the same loader (`container_ptr`'s
not-mapped branch), so each bank is its own 2 GiB window.

A vendor bank's header (Deadpool LE 1.16, 16 banks) is 0x68 bytes of mostly
zeros: `0x28 = 0x68` (the fragment table follows the header), `0x38 = size -
4`, `0x40 = md_off`, `0x48` = where the data after the fragment table starts,
`0x5c` = fragments, `0x60` = records. The fragment table is 40 whitened bytes
per fragment: the descriptor index the resolver (`get_asset_descriptor`) reads
for a sid of that category. `image.bin`'s own header is the same layout plus
the tables at `0x08..0x20`, the category count at `0x68` and the id array at
`0x6c` (Godzilla: header 0xb0 bytes, fragment table at 0xf8, so 18 free id
slots between them; Deadpool: 0xf0 / 0x138, the same 18). The V1.99D card's
`0x38` still says the stock file end, so that word is not checked.

**A record's container key carries its category.** Measured on Deadpool LE
1.16 by capturing the find key the band build registers (`keys.py`, this
ticket's scratch): bank 55's one record keys `d4eb405f 8ae606e0`, bank 1's
second record `d4eb405f 8a2600e0` -- the same w1, w2 differing only in bits
13..28 = 0x37 / 0x01, the category id; cat-0 records have 0 there. The
resolver's callers assemble `key.w2 = (payload.w2 & mask) | ((sid >> 16) << 13)`
(engine `_repoint_descriptors`), so a descriptor for a cat-0 sid can only ever
name a cat-0 record: re-pointing a play table at a bank record is impossible.
What reaches a bank record is a key handed to the game's record lookup --
exactly what the mode runtime's `sound_lookup` hook does (`pm_sound_swap`,
item 163): every lookup of the carrier's stock key takes ours, eight bytes,
category bits included.

**The format is accepted.** `bank_e1.py` (scratch) wrote a one-record
`image-sc01.bin` for stock Godzilla LE 1.16 -- header as above with
`0x5c = 0` fragments and `0x28 = 0x48 = 0x68` (no fragment table, no data
block), a copy of stock record 1898 with its geometry replaced, the stock body
repeated as a scaffold, the directory packed by `masterdir.write_directory`
(the cipher is the firmware's, not the file's) -- and the firmware's own
`load_category_assets(1)` + `MASTERDIR_DECODE(1)` registered it, derived its
row (`body_off 0x78, length 397190, stereo`) with key `5bf98007 d73e0000`
(cat bits = 1), and `decode_cat` decoded it.

## The change

**Where a sound goes.** `image.bin` keeps what fits, as today (the path every
machine has proven); the modes' own sounds that would take it past the game's
2 GiB go into a bank of their own, `image-scNN.bin` (NN the lowest id the card
does not use), one or more, each under 2 GiB. The user's longer replacements
and the music modes' files still need a re-pointed descriptor, so they stay in
`image.bin` and are trimmed as before when it is full; the budget's words say
what went where.

**How a bank sound is played.** Every bank sound is a SWAP: the mode file's
`swap <request> <stock key> <our key>` names the carrier's stock record key
and the bank record's. A call already swaps on every title. A music bed keeps
its `music <request> <sid>` line (the carrier is pointed at the bed sid) AND
gets a swap line (the bed's stock key -> the bank record's), which mode_file.c
already supports together (its `music.sid` and `music.swap`); the bed sid's
descriptor is still rewritten as the carrier's looping music descriptor with
the bank record's duration, but keeps its STOCK key, since the swap supplies
the bank's.

**How a bank is built.** `spike2/soundbank.py`: the header layout, the
category slots in `image.bin`'s header, the plan (`plan_bank`: one record per
sound, a copy of its host record with the bank geometry, bodies scaffolded
from the host's stock audio) and the file (`write_bank`). The records are
derived along the firmware's own chain for THAT bank (`CatEmu.derive_bank`,
with `after_step` as `derive_params` has it) and encoded along it
(`_chain_encode_bank`, the bank's `_chain_encode_appended`), so every window
holds the sound's own audio and every key is the one the finished bank
registers. `image.bin`'s header gains the id (`0x68` + 1, `0x6c + 4n`), as an
in-place patch or in the staged grown bank. The bank goes on the card as a new
file with a manifest record, as the modes' clips do, and into a Try it set the
same way (`overrides.new`). The bank's trailer word is `PADB`, so Extract
knows it for this app's and does not decode it as a music bank of songs.

**Proof.** Emulator: the synthetic bank above; the chain encode decoded back
bit-exact; a Try it set of the Heisei modes on stock Godzilla LE 1.16 with the
bank ceiling lowered (`PAD_STERN_BANK_CAP`) so the modes spill into a bank,
booted on a rig, each spilled bed and call matched in the game's own PCM; then
the real case, the V1.99D card with the eleven modes. See "Runs" below.

## Runs

Headless, 2026-10-16, all on stock Godzilla LE 1.16 (`C:\tmp\PAD-595`, scratch):

- `keys.py` (Deadpool LE 1.16): the category id in a bank record's key, above.
- `bank_e1.py`: the one-record synthetic bank the firmware's own loader and
  directory decode accept (above).
- `hdr_e3.py`: `image.bin` with `0x68 = 1, 0x6c = 1` written over the first of
  the 17 words after the (empty) id array -- the boot, the first 30 records'
  codec objects and keys, and 13 descriptors resolved through
  `get_asset_descriptor` are byte-identical to the stock header's. Those 17
  words (and the 0x48-byte block `hdr[0x00]` points at, which follows them)
  are not read by anything the boot, the derive or the resolver runs; the
  block is reached through `hdr[0x00]`, not by position. The V1.99D card's
  stale `0x38` says the vendor's own tools leave such words alone too.
- `bank_e2.py`: `bank_build` end to end: a two-record bank (KIRYU's music.wav
  on stereo record 1898, fire.wav on mono record 1147) staged, encoded along
  the bank's chain (scales 13 and 6, as the chain gives them), the finished
  file re-derived to the same codec objects and keys, and decoded back:
  normalised cross-correlation with the WAVs 0.99 (mono), 0.987 / 0.999
  (stereo, at 0 s and 10 s), lengths exact.
- The first Try it set with the cap at 1.70 GB failed with "the firmware did
  not register sound bank image-sc01.bin": the bank's directory had been
  packed under a 32-byte key. Nothing had read a directory on that emulator,
  so `keygen` guessed the key length from the key's shape, and Godzilla's
  AES-192 key schedule leaves non-zero words past byte 24. `stage_bank` now
  reads `image.bin`'s directory first (the checksum confirms the length), and
  `write_directory` refuses an unsettled key length outright.
- The second Try it build encoded its nine beds in 136, 355 and 816 s and
  counting: `CatEmu` paged the bank window in 4 KiB pieces, and the chain
  encode writes whole bodies into that window, so every later guest access
  searched thousands of tiny regions -- the quadratic trap
  `Spike2Emu._map_card_window` documents for `image.bin`. The bank window is
  now backed in one piece the same way (a private copy-on-write view); the
  same nine beds then took 106, 87, 84 s each.
