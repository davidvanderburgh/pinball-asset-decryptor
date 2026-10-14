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
| Indiana Jones 2.10 | 1,711 | 28 / 1,200 |
| CSI 2.40 | 1,619 | 27 / 1,189 |
| 24 1.50 | 2,084 | 34 / 1,266 |
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
cards, fonts, four-bit frames all whole and upright).

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
| DMD animations as data | the other ~5 MB of the art area, not decoded | large |
| Text / messages | plain ASCII in the code area, 5 languages; same-length edits only | small |
| Default settings | the adjustment names are plain; their defaults are in the code's tables, as on Spike 1 | medium |
| Emulate | PinMAME runs every title PAD can identify; a play tab with switches would build on the capture | medium |

So SAM is now at Spike 1's level for audio (Extract, Replace, Write,
Revert, Mod Pack).  To reach BoF / JJP completeness the next steps are, in
order of value for effort: text, then the animation format (PAD-584).
Still pictures and fonts are built (PAD-583, above).
