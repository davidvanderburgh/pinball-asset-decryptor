# A sound bank with more sounds than its game was built for (PAD-445)

## The failure

Found 2026-10-07 building a Godzilla Premium 1.16 card with all 11 Modes-tab
code-mode examples. The Write failed after its twenty-minute encode with
*"Modes: the music carrier, request 125, plays 0 sound ids; a music bed needs
one to copy"*.

`image.bin`'s header carries two plaintext count words
(`info.container_counts`): `u32 @0x5c`, the sound fragments (the sound ids the
game's resolver hands out), and `u32 @0x60`, the sounds (the master-directory
records, `masterdir.HDR_COUNT`). On every vendor card fragments >= sounds:
stock Godzilla LE/Premium 1.16 is 2599 / 2534, so 65 to spare.

Every grow appends one record and rewrites only the sounds word. The 11
examples append 69 (11 music beds + 58 calls), so the grown bank reads 2603
sounds over 2599 fragments, and `container_counts` refused the pair. The
request-table locator takes the fragment word as its sid ceiling, so with the
pair refused it found no table, and every lookup through it (the modes' music
carrier) came back empty.

## What the game does with the two words (Godzilla LE 1.16, read from its code)

`image.bin`'s header is copied into a container object (the header at
object +0x18) and read through two accessors:

| accessor | what it returns |
|---|---|
| `0x3b5968 container_get(id, field)` | a count: field 0 = hdr+0x50, 1 = hdr+0x54, 2 = hdr+0x30, **3 = hdr+0x5c (fragments)**, **4 = hdr+0x60 (sounds)**, 5 = hdr+0x64 |
| `0x3b5c80 container_ptr(id, field)` | `base + hdr[8*field]` (field 8 = the master directory, hdr+0x40) |

The whole program calls `container_get` three times: field 4 from the bank
decode (`0x4d4c4c`, which mallocs `align16(24 * sounds)` and walks that many
records), field 0 and field 1 from two lazily built lookup tables. **Nothing
asks for field 3**, and nothing in the container module reads the fragment
word at object +0x74. The unicorn derive saw no direct read of either header
word while the firmware booted and decoded the bank either. So no table the
game builds is sized by the fragment count; the sounds word sizes the record
array it decodes, whatever it says.

A grow never extends the sound-id space anyway: a grown sound is reached by
re-pointing an existing id's play table at the appended record (the modes'
music beds, a longer replacement) or by the modes' key swap (their calls).

## The change: no limit

`container_counts` accepts a grown bank: the sounds word only has to be a
record count a bank can hold (1 << 16). The fragment word is still the card's
own, so the request table is found and the music carrier resolves on a
2603-record bank
(`test_the_music_carrier_is_found_on_a_bank_grown_past_its_fragments`).

**Nothing in a Write counts the records it appends** (David, 2026-10-07: "We
need to be unlimited"). A first pass of this ticket held the bank to
`fragments - sounds` until a machine had proven more - refusing the modes'
own sounds past it, trimming longer replacements - and David lifted it after
the emulator proof below. `test_a_bank_with_no_room_left_still_takes_every_new_sound`
pins it: a bank whose header has no room left still takes a mode's own
sound. The one ceiling left on the bank is its size: the 2 GB the game can
open (`_grows_within_bank_limit`, PAD-175/176).

A different ceiling is not this one: each mode's own music bed rides on a
spare sound id no request plays (`mode_sounds` carriers' `beds`), and
Godzilla LE 1.16 has 12. A 13th mode with music of its own is refused by
`mode_sounds.assign` before any record is counted.

## Proof on the emulator (2026-10-07)

The 11 examples on stock Godzilla LE 1.16, built into Try it's set by Write's
own code (`mode_write.build_tryit_set`, with no limit - as it is now): 69
appended records, `image.bin` 2599 fragments / 2603 sounds, the build's
integrity check passed, and the firmware's own decode chain (the unicorn
derive) encoded records 2599-2602 like any other. The records past the line:

| record | sound | how the game reaches it |
|---|---|---|
| 2599 | FINAL WARS music bed | re-pointed play table (sid 555) |
| 2600 | GODZILLA ANGRY music bed | re-pointed play table (sid 422) |
| 2601 | KIRYU won | the modes' key swap (request 1186) |
| 2602 | OXYGEN DESTROYER collect | the modes' key swap (request 1174) |

Booted on rig 2 (hidden, muted, the card cached on the WSL disk), a game
started, and each mode was run by its trigger file. No segv, no fatal signal,
the stock 6 throws. The mode log shows each swap taking the card's new key.
The game's own PCM (`/dump/audio.raw`, nothing reaches a speaker) was matched
against each WAV by normalised cross-correlation (`match.py`, PAD-445 scratch):

| sound | record | peak | where | the mode log |
|---|---|---|---|---|
| FINAL WARS music bed | 2599 | 0.76 | 33.8 s | START at 34.4 s |
| OXYGEN DESTROYER collect | 2602 | 0.87 | 62.8 s | COLLECTED at 63.9 s |
| KIRYU won | 2601 | 0.87 | 92.4 s | END at 92.6 s |
| GODZILLA ANGRY music bed | 2600 | 0.97 | 108.3 s | START at 109 s |
| KIRYU ready (below the line) | 2535 | 0.84 | 82.6 s | READY at 83.3 s |
| four WAVs no mode played | - | 0.05-0.13 | | |

So the game plays sounds on records past its fragment count, through both
ways a grow is reached. No machine has booted such a card yet: the first
card built past its fragments is that test.

Three runs of this bank. The cached one above played all four. A second,
booted straight off the card on D: like the first, played 2599 (0.77), 2601
(0.94) and 2602 (0.87) again; GODZILLA ANGRY started only in its capture's
last seconds (the uncached run fell behind real time), so 2600 had nothing to
match there. The first run froze at Start, before any mode or own sound, and
the game's own 10 s watchdog ended it (GAME EXIT DISPATCH TIMEOUT, as in
PAD-200). That freeze is the rig's, not the bank's: it is in 9 of the 26
watch logs other sessions left in C:\tmp, stock Godzilla Pro 1.16 straight
off D: (PAD-373) and stock LE 1.16 (PAD-412) among them, and at Start nothing
reads a record past the line.

## If a machine disagrees

Should a card past its fragments misbehave on a machine (a sound past the
line silent, a reboot when one plays), the bank's own header says how far
past it is: Image Info shows both counts. The fix would then be the room
`fragments - sounds` per title, held at the moment a Write's grows are
settled (`_compute_patches`, beside `_grows_within_bank_limit`).
