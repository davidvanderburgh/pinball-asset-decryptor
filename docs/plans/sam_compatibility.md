# Stern SAM: what PAD can do with it (PAD-582, PAD-583)

David's ask: a full analysis of SAM compatibility, replacing audio first,
ideally as complete as BoF or JJP support.  This is that analysis, and the
audio half of it is built: **Extract every sound, Replace Audio, Write the
game file back**, on all 24 SAM titles tried (WPT 2006 to The Walking Dead
2014).

## What a SAM game is

One file: the code update Stern ships for the USB stick (`.bin`; TWD 1.05
alone `.ebi`), 5 to 120 MB, which is byte for byte the flash image the CPU
board runs (and the ROM PinMAME loads, `src/wpc/sam.c`).  The CPU is an
AT91 ARM7; there is no sound board: the game code mixes up to eight voices
in software and hands 24 kHz samples to an FPGA DAC.  So everything --
code, DMD art, every sound -- is in that one file, readable without an
emulator.

Layout (file offsets; TRON LE 1.74 as the example):

| range | what |
|---|---|
| `0 .. 0x11FFFF` | ARM code (the first 1 MB is also copied to RAM at boot) |
| `0x120000` | section checksum table: `(start, end, ~bytesum)` triplets |
| `0x120048 ..` | the data area: sound table, font table, picture table, then DMD art (fonts, stills, animations) |
| `0x84B4C0 .. end` | the sound samples, packed end to end |
| last 4 bytes | (2010 on) `~bytesum` of everything before them |

**Pointers** in the data are bank-encoded: `bank << 24 | offset`, 8 MB
banks (the board's flash window), so file offset =
`(p >> 24) << 23 | (p & 0xFFFFFF)`.

## Sound (built)

Worked out from the game code with a disassembler (and the code's own
dispatch tables run under an ARM emulator to measure each opcode):

- **The sound table** is the long run of pointers at the start of the data
  area: one entry per sound number per language (TRON: 5,580 entries = 1,116
  sounds x 5 languages).  Each points to a *script*.
- **A script** is `05 <voice mask> <voices needed> <u32>` and then byte
  code for a small sequencer: play a sample on a voice, set volume / pan,
  envelope, loop, wait, wait for voices, stop.  The opcode that matters is
  PLAY: a voice and a pointer to a sample.  There are **four generations**
  of the engine (14, 15, 17 and 18 opcodes: WPT/Pirates/Family Guy/WOF; the
  2008-2011 titles; 2010+; the 128 MB titles), which differ only in which
  opcodes exist.  PAD carries the four argument-length tables and takes the
  one that parses every script of a file and finds its samples.
- **A sample** is an 8-byte header (`u32 count`, three bytes, `kind`) and
  its data.  Kind 1/2/3 is **IMA ADPCM** (4-bit, low nibble first, standard
  step tables, predictor and index starting at 0) played at **24 / 12 /
  8 kHz**, mono; kind 0 would be 16-bit PCM (no title uses it).  Effects and
  music are 24 kHz; most speech is 12 kHz.  The decoder is bit-exact with
  the game's own routine (run under the emulator against PAD's on four
  titles across the generations: 0 differences in 20,000 samples each).
- Samples tile the sound area end to end, no overlaps, never across an
  8 MB bank; the only gaps are the bank ends.

| title | engine | samples | minutes |
|---|---|---|---|
| World Poker Tour 1.40 | v14 | 1,120 | 29.6 |
| Pirates of the Caribbean 6.00 | v14 | 850 | 35.6 |
| Family Guy 12.00 | v14 | 1,540 | 59.6 |
| Wheel of Fortune 5.00 | v14 | 1,627 | 53.3 |
| Shrek 1.41 | v15 | 742 | 45.7 |
| Batman (Dark Knight) 2.94 | v15 | 857 | 43.4 |
| Indiana Jones 2.10 | v15 | 854 | 34.9 |
| CSI 2.40 | v15 | 951 | 54.9 |
| 24 1.50 | v15 | 1,147 | 50.5 |
| Big Buck Hunter Pro 1.70 | v15 | 1,200 | 46.3 |
| The Rolling Stones 1.10 LE | v15 | 718 | 48.4 |
| Spider-Man 2.61 | v17 | 590 | 27.9 |
| Iron Man 1.83 VE | v17 | 1,027 | 40.4 |
| Avatar 2.00 | v17 | 1,256 | 50.0 |
| TRON: Legacy 1.74 LE | v17 | 1,103 | 46.5 |
| X-Men 1.50 LE | v17 | 1,018 | 51.2 |
| AC/DC 1.60 / 1.68 LE | v17 | 3,689 / 5,206 | 102.5 / 154.1 |
| The Avengers 1.70 | v18 | 983 | 38.3 |
| Star Trek 1.61 LE | v18 | 1,864 | 69.9 |
| Mustang 1.45 LE | v18 | 1,308 | 80.3 |
| Metallica 1.64 / 1.70 | v18 | 1,457 / 1,459 | 126.6 |
| The Walking Dead 1.56 LE | v18 | 3,331 | 122.0 |

Every one decodes to clean audio (speech checked by transcription on each:
"Super Jackpot!", "That is the Ark of the Covenant.", "Charlie Oscar, gun
runner standing by.").

### Checksums

- The **section table** sums each section's bytes (`~sum`).  Some shipped
  files' sums don't match their own bytes (TRON: 3 of 5 sections), so the
  game evidently doesn't hold the image to them; PAD moves each sum by
  exactly what a write changed, so whatever held before still holds.
- From 2010 on the **file ends in `~bytesum`** of everything before it.
  Every title whose update code shows "VERIFYING IMAGE..." / "CHECKSUM NOT
  FOUND" carries it and no other title does (24 of 24), so it is the USB
  update's check.  PAD recomputes it from the written bytes.

### What the app does now

- **Extract** (the Basic box on a SAM file) decodes every sample to
  `audio/idxNNNN.wav` (`NNNN` = its place in the file), at its own rate,
  in seconds (TRON: 1,103 WAVs in 8 s).  Auto-name call-outs / music and
  Length-prefix names work as on Spike 1.  Ticking Capture too runs the
  PinMAME DMD capture after it, into the same project.
- **Replace Audio** lists them; **Write** re-encodes each changed WAV into
  its own slot: resampled to the slot's rate, mixed to mono, fit to its
  exact length (longer trimmed with a short fade, shorter padded), loudness-
  matched to the original (soft-limited; Advanced audio options' levers and
  the per-clip level box apply), then the checksums.  The output is the
  same size as the input: a `.bin` that goes on a USB stick and is picked
  from the update screen like Stern's own (the service manual: the screen
  lists the files on the stick).  Revert and Mod Pack work as on Spike 1.
- Proven in PinMAME on TRON (v17), WPT (v14), Batman (v15) and Mustang
  (v18): coins dropped in the stock game identify the coin sound by
  correlation (TRON: 0.995 against PAD's decode of one sample); the same
  sample replaced through the app's own Extract + Write plays the new sound
  (correlation 1.0); and with every sample replaced the game boots and plays
  only the new audio.

## Limits (audio)

- **Length is the slot's.**  Samples are packed end to end, so a longer
  replacement is trimmed.  Growing one is possible in principle (put it at
  the end of the file and repoint the script's PLAY), but the file size is
  bounded by the board's flash (32 MB SAM1 titles; 128 MB for the later
  ones) and it hasn't been tried on a machine.  Not built.
- **Quality is the game's**: 4-bit ADPCM, mono, 24 kHz (12 or 8 kHz for
  most speech).  Moving a 12 kHz slot to 24 kHz doubles its bytes, the same
  growth problem.
- **Music** is often several samples a script chains or loops; each is its
  own WAV, so a new song is cut to those pieces.
- **Which sound plays what** (the scripts: volumes, layering, loops) is
  readable but not editable in the app.
- Real-machine check: PinMAME doesn't emulate the USB update, so the
  update's own check is reasoned from the file format (above), not run.

## Pictures and fonts (built, PAD-583)

Worked out from the files, checked against the renderer by PAD-584 (which
decodes the animations) and against PinMAME's own DMD output.

- **Two tables name the art.**  The code keeps four words in a row --
  `font count, font table, picture count, picture table` (World Poker Tour:
  the two pairs swapped) -- with the picture table starting right where the
  font table's 20-byte records end, so a plain scan of the first 2 MB finds
  them on all 24 titles.  The picture table is one bank pointer per
  *picture number*, the number the game code draws by (TRON: 8,181).
- **A record** is a header and data.  2007 on: `u32 id, u32 flags, s16 w,
  s16 h, u8 format` (13 bytes); World Poker Tour, Family Guy, Pirates and
  Wheel of Fortune: `s16 w, s16 h, u8 format` (5 bytes).  Formats: **0** one
  byte per pixel, row by row; **12** four bits per pixel, low nibble first
  (`ceil(w*h/2)` bytes; the spare nibble of an odd count is left alone);
  1/7 run-length and 3/9 delta frames (8/10 on the 2008 titles) are the
  animations.  A pixel is a shade 0..15 or 0xFF transparent.
- **Plain pictures** are the format 0/12 records whose bytes are all shades
  (or 0xFF), that end before the next record, and that no delta frame
  builds on (a delta patches the cached record whose id's low half is one
  less; those keyframes are left to the animation side).  The id's high
  half is no guide to "still or frame": Metallica 1.64 sets it on every
  still, 1.70 on none.
- **Fonts**: a font record is `u32 end, u32 start` of its glyph array, then
  the height; each glyph entry is `(bank pointer to a picture, s16 dx, s16 dy)`,
  8 bytes, 12 from the 2012 titles on.  On TRON the start/end words carry no
  bank (`0x254d0` is file `0x8254d0`), so each bank is tried.  The fonts do
  not share one character map (some leave out `&`, some carry a glyph past
  `Z`), and the map is in the code, so glyphs are named by number only.

| title | plain pictures | fonts / glyphs |
|---|---|---|
| World Poker Tour 1.40 | 2,650 | 31 / 1,335 |
| Family Guy 12.00 | 2,148 | 30 / 1,248 |
| Pirates of the Caribbean 6.00 | 2,448 | 31 / 1,346 |
| Wheel of Fortune 5.00 | 2,713 | 32 / 1,451 |
| Shrek 1.41 | 2,460 | 27 / 1,189 |
| Batman (Dark Knight) 2.94 | 3,719 | 27 / 1,189 |
| Indiana Jones 2.10 | 1,712 | 28 / 1,200 |
| CSI 2.40 | 1,622 | 27 / 1,189 |
| 24 1.50 | 2,092 | 34 / 1,266 |
| Big Buck Hunter Pro 1.70 | 2,366 | 28 / 1,222 |
| The Rolling Stones 1.10 LE | 1,438 | 27 / 1,211 |
| Spider-Man 2.61 | 3,426 | 28 / 1,251 |
| Iron Man 1.83 VE | 3,987 | 30 / 1,325 |
| Avatar 2.00 | 4,561 | 27 / 1,211 |
| TRON: Legacy 1.74 LE | 4,031 | 44 / 1,639 |
| X-Men 1.50 LE | 1,531 | 27 / 1,211 |
| AC/DC 1.60 / 1.68 LE | 3,002 / 3,033 | 30 / 1,340 |
| The Avengers 1.70 | 1,966 | 27 / 1,211 |
| Star Trek 1.61 LE | 1,840 | 31 / 1,334 |
| Mustang 1.45 LE | 1,743 | 29 / 1,286 |
| Metallica 1.64 / 1.70 | 2,050 | 39 / 1,683 |
| The Walking Dead 1.56 LE | 2,682 | 42 / 1,771 |

Every title's pictures were looked at as contact sheets (icons, title
cards, fonts, four-bit frames all whole and upright).  (PAD-584: the 2008-2010 engine's format 8 is a whole run-length frame,
not a delta, so the pictures before one are plain ones too: 3 more on CSI,
1 on Indiana Jones, 8 on 24.)

### What the app does

- **Extract** writes each plain picture to `images/pictures/imgNNNN.png` and
  each glyph to `images/fonts/fontNN (H px)/imgNNNN.png` (`NNNN` = picture
  number), gray + alpha: shade `s` is gray `s * 17`, transparent is alpha 0
  (TRON: 4,031 PNGs in ~10 s, after the sounds).  A file whose tables can't
  be found still extracts its sounds.
- **Replace Images** lists them (the tab is on for SAM; it scans `images/`
  and PAD-584's `animations/`).  **Write** takes each PNG that differs from
  the extract's baseline, scales it to the picture's size, takes its grays to
  the nearest shade (alpha under half: transparent; a four-bit picture has no
  transparency, so black) and writes it over the record in place, then the
  same checksum fix as the sounds -- one build carries both.  **Revert**
  re-decodes the original.
- Proven in PinMAME on TRON: 83 extracted pictures and glyphs are found
  pixel for pixel in the stock attract mode's DMD frames; a 348x128 color
  picture staged through the Images tab over picture 1440 (87x32) and a
  whole font (15, the attract mode's GAME OVER) drawn as boxes, written by
  the app's Write, showed on the DMD exactly in place of the originals.

### Limits (pictures)

- **A picture keeps its size**: records are packed end to end.  A bigger
  picture means moving it and repointing the table, the animation side's
  repack (PAD-584) territory.
- **16 shades of one color**, as the DMD shows them.
- **Glyphs by number**: which character a glyph draws is in the code's
  per-font map, not read yet.

## The rest of SAM (not built)

| area | state | effort |
|---|---|---|
| DMD animations | captured as MP4 by PinMAME (PAD-577) | -- |
| DMD animations as data | **built** (PAD-584, below) | -- |
| Text / messages | plain ASCII in the code area, 5 languages; same-length edits only | small |
| Default settings | the adjustment names are plain; their defaults are in the code's tables, as on Spike 1 | medium |
| Emulate | PinMAME runs every title PAD can identify; a play tab with switches would build on the capture | medium |

So SAM is now at Spike 1's level for audio (Extract, Replace, Write,
Revert, Mod Pack).  To reach BoF / JJP completeness the next steps are, in
order of value for effort: text.  Still pictures and fonts are built
(PAD-583, above), and the animations (PAD-584, below).

## DMD animations (built, PAD-584)

Worked out from TRON 1.74's renderer (`0x2b194`: it reads the record's
format byte and calls through a 16-byte-per-format function table in RAM,
`0x40d8638` = file `0xd8638`, four variants per format: opaque, and the
transparent / coloured blits), then checked on every title.

**The graphics table.**  Four code literals, `font count, font table,
graphics count, graphics table`, with `graphics table = font table + 20 *
font count` (TRON: `0x36f44`; one scan of the first 2 MB finds them on 23
of 24 titles, all but WPT).  The graphics table is bank pointers to
records:

| bytes | what |
|---|---|
| u32 | id: the frame cache matches its low 16 bits; the high half is a group (not a reliable still/frame flag: Metallica 1.64 sets it on every still, 1.70 on none) |
| u32 | flags: 4 = keep the decoded frame cached; 1 / 2 = more delta frames follow |
| s16, s16 | width, height (87 x 32 next to the score panel, 128 x 32 full screen; a few are taller and scroll) |
| u8 | format |

Decoded, every pixel is one byte, row by row: 0-15 shades, 0xFF clear.

| format | what |
|---|---|
| 0 | raw bytes |
| 12 | raw 4-bit, low nibble first |
| 1 / 7 | run-length, down the columns / along the rows: byte `c` (0 ends), `n = c >> 2`; `c & 3` = 0: `n` literal bytes, 1: `n` zeros, 2: `n` x 0x0F, 3: one byte repeated `n` times |
| 3 / 9 | delta on the previous frame, columns / rows: signed byte (0 ends), negative = skip that many pixels, positive = that many literal bytes |

The 2008-2010 engine (CSI, Indiana Jones, Shrek, 24) numbers the row-order
formats 8 and 10; their code is byte for byte format 7's and 9's.  The
2006-2008 titles (WPT, Pirates, Family Guy, Wheel of Fortune) have only raw
pictures with a 5-byte header (w, h, format) and no animation data.

**The frame cache.**  Formats 1 / 7 / 12 first drop any cached frame with
id - 1 or id, decode into a fresh buffer, and cache it when flag 4 is set.
A delta finds the cached frame with id - 1, patches it in place, re-ids it,
and keeps it cached while flags 2 or 4 are set.  So an animation is a
keyframe followed by deltas.  Which frames play when is in the game code
(loops over record numbers: TRON's logo is `for n in 1440..1475: draw(n,
x=41); wait(5)`), not in the data.

**Proof.**  Every compressed record of every title run through that
title's own decompressors under an ARM emulator (Unicorn; the dispatch
table and decompressors found automatically per title): 88,143 records on
19 titles, 0 differ.  In PinMAME, attract-mode screens match decoded frames
pixel for pixel (TRON's logo animation: 37 frames, every format).

| title | records | animation frames |
|---|---|---|
| TRON: Legacy 1.74 LE | 8,181 | 4,150 |
| Indiana Jones 2.10 | 9,414 | 7,702 |
| Star Trek 1.61 LE | 8,620 | 6,780 |
| The Walking Dead 1.56 LE | 9,474 | 6,792 |
| X-Men 1.50 LE | 7,116 | 5,585 |
| Metallica 1.64 / 1.70 | 6,987 | 4,937 |
| AC/DC 1.68 LE | 7,362 | 4,329 |
| Iron Man 1.83 VE | 7,555 | 3,568 |
| The Avengers 1.70 | 5,409 | 3,443 |
| Mustang 1.45 LE | 4,802 | 3,059 |
| Big Buck Hunter Pro 1.70 | 4,610 | 2,244 |
| Spider-Man 2.61 | 5,643 | 2,217 |
| 24 1.50 | 3,641 | 1,549 |
| CSI 2.40 | 2,918 | 1,296 |
| The Rolling Stones 1.10 | 2,630 | 1,192 |
| Avatar 2.00 | 5,405 | 844 |
| Shrek 1.41 | 2,632 | 172 (its fonts' glyphs) |
| Batman 2.94 | 3,719 | 0 (all raw pictures) |

**What the app does.**  Extract writes every frame that isn't a plain
picture to `animations/imgNNNN.png` (8-bit grey + alpha, shade `v` as
`v * 17`, clear as alpha 0): the run-length and delta records, and any raw
keyframe a delta builds on.  The plain raw pictures (format 0 / 12, no
delta after them) are Replace Images' stills and fonts (PAD-583,
`images/`); both use the same numbers.

Write re-encodes each changed PNG, and every delta after it (against the
frame now under it), with exact optimal encoders (dynamic programs over
the stream grammar; never longer than Stern's own data; 347 of the first 600 TRON
frames come out smaller) in the shortest format the record's place allows
without changing what the frame cache does: a run-length keyframe may be
either order or 4-bit; a delta may be either delta order, or a whole frame
when its flags let the cache end the same way (flag 4, or no 2 / 4); raw
stays raw; only formats the file already uses.

**Space.**  The art area is packed solid (records end to end with 0-3
bytes of padding, ~100 bytes free before the sounds), and the file can't
grow (PinMAME loads each romset at its fixed size, and the 2006-2008
boards have 256 Mbit flash).  So a frame goes into its own bytes, or, for
records that nothing but the table points at (glyph arrays point at font
records; a chance match only pins a record), the frames of a run of
adjacent records share the run's bytes and the table is repointed.  When
the edits still don't fit, the largest edited frame steps down to fewer
shades (8, 4, 2) and then to its original, one frame at a time, until they
do; the log names each one.  On all 18 titles, inverting the three longest
animations and mirroring a frame wrote 2,081 frames exactly and one with
8 shades; the written files decode the same through each game's own code.
Through the app, inverted / stamped / mirrored animations played exactly as
written in PinMAME on TRON (formats 1/3/7/9/12), Indiana Jones (8/10) and
Mustang (2014, 128 MB).  Checksums: the section sums move by what changed
and the file's own sum is recomputed, as for the sounds.

**Limits.**  A whole new animation as busy as the original fits; one much
busier loses shades.  Frame sizes and counts are the game's (the code
draws each record at its own place).  Which animation plays where is in the
code, not editable.
