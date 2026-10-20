# Multi-band Spike 2 records (PAD-637)

## What they are

A Spike 2 sound record's codec obj carries a stride (+0x1a, words per sample
frame) and a band count (+0x1c). On every ordinary sound the band count is 1
and the stride is the channel count. A **multi-band** record has N > 1 bands
and a frame of `N * chan` words: N variants of one sound, interleaved frame by
frame (frame i = variant 1's sample i, variant 2's sample i, ...).

The game plays ONE variant per voice: the 1-based band number at voice+0x20,
chosen when the voice starts from a table of game-state tests (0x1d5f50 on
Led Zeppelin Pro 1.22), and switched live through voice+0x21, which the codec
crossfades into. Mono band k reads word `k - 1 + N * i` with keystream index
`seed + k - 1 + N * cursor`; a plain sound is the N = 1 case at band 0, which
is where the familiar delta = -1 (reading one word below the body) comes from.

The voice setup gives these records codec functions of their own:
`ldrb chan / ldrb bands / ldrb scale / clz ... add r3, base, r3, lsl #6 /
ldrne mono, [r3, #-x] / ldreq stereo, [r3, #-(x+4)]`.
`locate.find_band_codecs` reads that selector, so the slot is never guessed;
the dispatch table's 0x40-aligned base falls at a different place in each
build's rows (Led Zeppelin Pro 1.22: offset 0, Foo Fighters 1.04: 0x10),
so the slot a plain sound resolves to says nothing about the multi-band one.
Found on all 49 latest builds.

On hand (the 97 codec-parameter caches on this machine): Led Zeppelin LE/Pro 1.22 have ten mono
ones (12 variants a semitone apart, or 24 in left/right pairs: idx 31 57 65
278 286 333 338 390 517 519 on Pro), Foo Fighters LE/Pro 1.04 one stereo song
in two mixes (idx 3206 on Pro, 4:15). No other build in them has any.

## What was wrong

Read as one plain sound, a record decoded as stationary noise (flatness
~0.75) and failed the encoder's bit-exact self-test, so Write skipped it.
Worse, a multi-band record that resolved a worker's codec slot first settled
that (scale, chan) key on the wrong function, and every plain sound of that
scale in the worker decoded as noise too: 3 to 7 of Led Zeppelin Pro's plain
sounds per extract, depending on how the catalog split across workers.

## What it does now

- `emulator.bands_of / band_params / frame_bytes / emitted_total`; a decode of
  a record joins its variants in band order, each cut to its emitted run.
- `GenRecover` / `StereoRecover` drive one variant at a time (probe words in
  every lane, R advanced by the whole frame, the band in the voice) and write
  each variant into its own lane of the record's body.
- Write: a replacement file within 2% of the extracted length is that file
  edited and is cut back into its variants; any other sound becomes every
  variant, cut to one variant's length. A multi-band record is never
  lengthened (its appended copy would need every lane laid out anew); the
  mode end-sound grow falls back to the game's call on one.
- Extract writes `sound_variants.json`; the Audio tab's Format cell says
  "N variants" with a tip on how Write takes the file, and Type judges the
  sound on one variant's length.

## Proof

- Every variant of all 11 records passes the self-test (192 + 2).
- Led Zeppelin Pro 1.22 card built by write_image (idx 390 edited per
  variant, idx 31 / 57 one tone each): re-extract gives 400..1500 Hz in
  variant order and the tone in every variant; the 546 other sounds are
  byte-identical. On the emulator the game plays request 83 as idx 390's
  variant 1 (400 Hz), 86 and 373 as the new tones.
- Foo Fighters Pro 1.04 card: idx 3206's variants re-decode 500/600 Hz and
  900/1000 Hz; the emulator plays request 64 as variant 1.
