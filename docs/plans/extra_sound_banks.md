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

**How a bank sound is played -- the swap route FAILED on the rig (2026-10-16,
run1/run2s below).** The game's record lookup took the bank record's key for
seven of nine spilled beds, and every one of them played as white noise
(spectral flatness 0.56, no left/right correlation; the two beds left in
`image.bin` matched their WAVs at 0.95). A qemu syscall trace of one bed
(`QEMU_STRACE=1`, run2s) shows why: the game `munmap`s the bank after its
boot-time decode and never opens it again; while the bed played it streamed
with `pread64` from `image.bin`'s own fd at the BANK record's body offsets
(99.38 MB..100.4 MB, 44800 bytes a call), so it decoded `image.bin`'s bytes
there. The file a long sound streams from is chosen by the CATEGORY OF THE
SID being played (the key's category bits come from `sid >> 16`, so a bank
song's sid is `cat << 16 | n`), not by the record the lookup found. A swap
that hands the lookup a bank record under a cat-0 sid therefore streams the
wrong file. Short sounds read through the cat-0 mapping the same way.

So a bank sound is played the vendor's way: a sid of the bank's own
category. **How the game resolves a bank sid** (`get_asset_descriptor`,
Deadpool LE 1.16 `0x3c928c`, Godzilla LE 1.16 `0x43c104`, driven in `CatEmu`
with the bank registered, `frag_probe*.py` in scratch):

    cat = sid >> 16; table = container_ptr(cat, 5)            # hdr[0x28]
    stride = byte 7 of container_ptr(0, 2)                     # 5 on every card seen
    variant = a global (random 0..4 when it is 5)              # fn 0x2e4bf8
    slot = (sid & 0xffff) * stride + variant                   # 8 bytes each
    off = slot.lo ^ vf2[((slot >> 6) & 0x3f) << 8 | (slot & 0x7f) .. +4]
    out[0] = VF2 + ((off ^ X) & M)        # Godzilla: off & 0x2a6; Deadpool: (off ^ 0xb8162db5) & 0xb95
    return bank base + off                 # the descriptor, whitened with vf2 at out[0]

So a fragment is `stride` 8-byte slots (the game picks one at random: all
five name the same descriptor), the descriptor can lie anywhere in the bank
(the vendor keeps them just before the directory; so do we), and its
keystream offset follows from its offset by a per-build rule that
`bank_build.resolver_rule` measures off the card's own cat-0 sids. The
descriptor is a copy of the sound's carrier's (a bed's carrier is a looping
tune, a call's the call it rides in on) with the declared duration set to the
bank record's and the op11 key the bank record's own key VERBATIM: on the
vendor pairs (Deadpool bank 55 sid 0x370000, bank 1 sids 0x10000/0x10001)
the record key equals the payload with a few bits cleared and the category's
bits set, and a key the band build registered already has both.

**How the mode plays it.** A bed: `music <request> <bank sid>` (the line the
runtime already had; `pm_sound_sid` points the carrier's request at a 32-bit
sid). A call: a new line, `sid <request> <bank sid> [call:<cue>]`
(`mode_file.c`, `pad_mode_assets.h`): the carrier is pointed at the bank sid
before the play and its own list put back when the call's stop fires. No
swap line for a bank sound. Proven on the desk harness
(`test_a_call_in_a_sound_bank_points_its_carrier_at_the_banks_sid_for_that_play`)
and headless (`bank_e3.py`: a two-record bank on stock Godzilla LE 1.16,
both sids resolved through the game's own resolver to our descriptors and
records, `verify_tables`).

The committed bank build (records, chain encode, verify, header ids) stands:
the game registered every record and found it by key.

(The original design, kept for the record.) Every bank sound was a SWAP: the mode file's
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
- run1 (rig 1, Try it set of the nine spilled beds): booted, 0 segv, the
  lookup took the bank key for 7 beds (JET JAGUAR's bus was held by the game's
  music; ZILLA never started). `bedcheck.py` on `audio.raw`: the two
  image.bin beds 0.95/0.94, every bank bed <= 0.09 -- white noise in their
  windows. run2s: the same boot under `QEMU_STRACE=1`, one bed: the trace
  above (`C:	mp\PAD-595
ig
uns
un2s\game.out`, `stracecheck.py`).
- The real case (`tryit595b.py`, the tester's V1.99D card + the eleven
  modes, no proof knob) needs PAD-593's branch (merged here): main itself
  stops on that card with "idx 31: no descriptor ... names this sound's
  record" (a card builder's longer sound), and the spill has to be measured
  from the FILE END (`image_grow_geometry`): the header alone said 1.9 GB
  where the file would come to 2.26 GB. With both: "5 of the modes' own
  sound(s) go into image-sc01.bin (135.9 MB): image.bin would come to
  2260 MB, past the 2147 MB the game can open; 60 stay in image.bin."
- run3 (rig 1, 2026-10-16, the same nine-bed set rebuilt with the play
  tables; `rig/bankcheck.py`): the game booted and started a game (0 segv);
  every mode that reached its bed pointed request 125 at its bank sid
  (`plays its own bed, sound id 65540` ...), and in the capture all seven
  of those bank beds match their WAVs at 0.97-0.98, the same as the two
  beds left in image.bin (run1 had the bank beds at 0.09: noise). JET
  JAGUAR ended the instant it started (its entrance waits for the game's
  battle screen) and ZILLA was refused (no multiball ready), in run1 too:
  drive conditions, not bank ones.
- The finished-bank check: a full `derive_bank` of the real nine-bed bank
  (211 MB of encoded audio) left the bank emulator unable to run the
  resolver afterwards (sid 1 and bank sids alike ran off into data at
  0x43c78c), where the scaffold banks of `bank_e3.py`/`bank_e4.py` and a
  stock image padded to 1.9 GB did not; reproduced offline on the kept Try
  it inputs (`C:/tmp/PAD-595/keep`, `repro_keep.py`, `bisect*.py`). The
  check now registers the bank through the game's loader alone
  (`CatEmu.register_bank`: `load_category_assets` and the count, no
  directory replay) and resolves every bank sid on that; the records are
  `verify_bank`'s business. The emulator maps a bank right after image.bin's
  window, so a bank is split at the room left under 4 GiB
  (`soundbank.emulator_bank_room`, about 400 MB beside a 2 GB image.bin).
- run5, THE REAL CASE (rig 1, 2026-10-16): the tester's Godzilla Premium 1.16
  Heisei Custom V1.99D Kaiju Edition card (image.bin 2.01 GB, 2643 records)
  with David's eleven modes, no proof knob (`tryit595b.py`, `tryit2`): five
  beds spilled into `image-sc01.bin` (135.9 MB; "image.bin would come to
  2260 MB, past the 2147 MB the game can open"), 60 sounds stayed in
  image.bin, all five bank sids resolved through the game's resolver, the
  card booted on the rig and started a game (0 segv), and the three bank
  beds whose modes reached them (KAMACURAS, GODZILLA ANGRY, MELTDOWN) match
  their WAVs at 0.97 in the capture, the same as the six beds left in
  image.bin; JET JAGUAR and ZILLA did not reach theirs for the same gameplay
  reasons as on the stock card.
- run6, CALLS (rig 1, 2026-10-16, `tryit4`, ceiling 1.5 GB): every one of the
  modes' 69 own sounds in `image-sc01.bin` (251 MB), nothing of theirs in
  image.bin (the path where image.bin grows nothing of its own). 0 segv;
  all nine beds that played match at 0.97; the four bank calls the drive
  triggered (each mode's lost call, `sid <request> <bank sid> call:lost`,
  "played (sound id N, its own in a sound bank)") match their WAVs at
  0.85-0.95 in the capture: a short bank sound, read through the bank's
  mapping rather than streamed, plays too.

## Every Spike 2 title (David, 2026-10-16: "Need it to work on all spike 2 games")

Headless sweep over the 49 current builds on hand (`sweep_lib.py`, results
in `docs/plans/pad595/library_headless.tsv`): per build, image.bin's
category slots and stride read, a two-record scaffold bank staged, the
firmware's own loader and directory decode asked to register it
(`derive_bank`: both records registered with keys), the resolver found and
its keystream rule measured (`resolver_rule`), the play tables written and
every bank sid resolved through the game's own resolver on the finished
file (`verify_tables`). **49 of 49 pass.** Every build has its own rule
(`(off ^ X) & M`: Aerosmith `^0x880 &0xcc0`, Jaws Pro `^0x6 &0xf8e`, X-Men
Pro `^0x4 &0x64` ...), so a hard-coded one would have failed all but one
title; the stride is 5 everywhere; the music titles take the first id past
their own banks (Deadpool 2, Metallica 25, D&D 30). Godzilla LE 1.16 is
proven separately on the rig above.

Rig sweep (`rig/bankboot.sh` through `rigbatch.sh`, `rig/prep_ovr.py`): each
title boots its stock card with an override set holding image.bin with the
header naming the bank, the bypassed game program, the scaffold bank, and a
CONTROL bank under an id the header does not name; an inotify watch on each
staged file says what the game opened. Aerosmith 1.16 dry run: the named
bank OPENED 8 s into the boot, the control never.

Full rig sweep, 2026-10-16 15:00-16:20, four rigs
(`docs/plans/pad595/library_rig.tsv`): **49 of 49 titles opened the named
bank at boot (8-24 s in) and none opened the CONTROL bank.** 36 of 49 came
up (attract, or Tech Alerts a stock boot does not leave on a rig either:
Aerosmith, Batman, D&D, Guardians, Iron Maiden, Jurassic Park, Mando Pro,
Munsters Pro, Sword of Rage, X-Men, King Kong Pro). 13 runs died 40-180 s
into the boot, after the bank was opened and released: Avengers LE,
Elvira 3, Foo Fighters Pro, Bond Pro, Jaws Pro, John Wick Pro, King Kong
LE, Munsters LE, Rush LE and Pro, Star Wars LE, Stranger Things LE, Venom
LE; eight by a segv, five by the game's own watchdog (GAME EXIT DISPATCH
TIMEOUT). Their siblings (Venom Pro, Bond LE, John Wick LE, Foo LE ...)
passed, so it is not a code path. Venom LE's segv (rig 3's log survived):
pc 0x4ae5d8 inside a 64-byte-block hash routine (`0x4ae3a4` compress,
`0x4af25c` update, called from `0x4af4fc` out of the 0x376d20 code), the
data pointer in a thread mapping, right after the audio device opened.
Prime suspect is the sweep's scaffold, not the feature: `sweep_lib.py`
copied only the first 256 KB of each picked record but kept the record's
real length in the directory (Avengers LE's picks are 258 MB each), so a
boot-time read of a bank body past the file's end faults. The Write
pipeline copies whole bodies, and the three Godzilla LE rig runs above,
with real banks, had 0 segv. Elvira 3 passed on a second run with the same
set, so some of the 13 are rig flakes too. Started and not finished (both
jobs were stopped by the host for memory): `sweep_lib2.py` rebuilds the
scaffold banks with whole bodies (Avengers LE done, 500 MB bank, its sids
resolve), and `rig/bankboot_ctl.sh` reboots the 13 with the rebuilt banks.
The "control" attempt was no control: the env var that was to leave the
header stock never reached `python.exe` (WSL passes nothing to a Windows
process without WSLENV), so it was a plain second run of the same sets.
As such it says the failures are mostly reproducible per title (Avengers
LE, Foo Fighters Pro, Bond Pro, Jaws Pro, John Wick Pro, King Kong LE died
the same way again) and partly flaky (Elvira 3 and Rush LE passed the
second time).

Resolution, 2026-10-16 18:31-18:55 (`docs/plans/pad595/library_rig_rerun.tsv`):
the scaffold banks rebuilt with whole record bodies (`sweep_lib3.py`: the
body sized by the gap to the next record's body; the record's +16 word is
an encoded length word, not a byte count, so the first rebuild attempt
with it was wrong), and **all 13 titles boot with the named bank: 11 to
attract, Foo Fighters Pro and Munsters LE alive in Tech Alerts at the
deadline, 0 died.** The six that had died twice the same way (Avengers LE,
Foo Fighters Pro, Bond Pro, Jaws Pro, John Wick Pro, King Kong LE) all
come up. Together with the first sweep: **49 of 49 titles open a sound
bank of the app's own at boot and come up.** The crash was the test
scaffold's: Venom LE's segv site (`0x4af4fc` out of the 0x376a40 routine,
std::map + mlock + a 0x200-byte hash window placed from the record's
length over the mapped body) reads body windows the record's length
promises, and a 256 KB scaffold body under a longer record left those
windows past the file's end: a fault on a machine, zeros in the emulator
(whose mapping covers the whole window), which is why `derive_bank`
registered those banks without complaint. The Write pipeline copies whole
bodies, as the Godzilla LE runs did. Second run of the first sets
(`library_rig_second_run.tsv`): 6 died again, 7 passed, so the shorter
records sat near the boundary.

## The game's own sounds in a bank (PAD-606)

David, 2026-10-17: a longer replacement of one of the GAME's own sounds (the Audio
tab) still had to stay in `image.bin`, so those were bounded by its room (about
2.14 GB beside a bank). Now they can go into a bank too.

**How the game plays it.** A game sound reaches its record through the
descriptor of the sid that plays it, and a cat-0 sid's descriptor can only name
an `image.bin` record (above: the key's category bits come from the sid). So a
banked game sound gets a sid of the bank's category, as a mode's own sound does,
with a descriptor copied from the game sid's OWN descriptor (its bus, its
script, the declared duration moved by the growth as a re-pointed one is), and
the game is made to play that sid: the request table's sid lists
(`spike2/sound_requests.py`), which the play worker reads at every play, name
the bank sid where they named the game's. That is how the music titles play
their own banks' songs (their lists carry `cat << 16 | n` sids). The lists are
plain data in the game program, so the words are written like the score
colours' (PAD-507): into the staged program, or in place with the validator
bypass refreshing the `.sidx` record over them (`engine._sound_list_writes`).

**Which sounds can move** (`bank_build.game_sound_sids`): exactly one game sid
plays the record, that sid's descriptor names nothing else, a request list
names the sid, and no mode of the same Write uses that request. Stock Godzilla
LE 1.16: 2438 of 2534 (96%); the rest are 62 records two sids play, 29 sids the
game never plays (no list names them: PAD-784), and 5 multi-part sids. No fragment on
that card has variants that differ (all five slots name one descriptor), so a
bank fragment's five equal slots lose nothing. A sound that cannot move stays in
`image.bin`, trimmed there when it is full, and the log says why.

**How many banks can be mapped at once** (Godzilla LE 1.16's code): a sound's
start takes a reference on its sid's bank (`0x43cdcc` -> `0x3b583c`), its stop
drops it (`0x43c254` -> `0x3b5884`), and mapping a bank unmaps only the OTHER
banks with no reference (`0x3b57d8`, called from the loader at `0x3b5b1c` and
`0x3b5b64`). So every bank with a sound playing stays mapped beside
`image.bin`, up to one per sound channel (the voice loop at `0x43c210` runs
8). PAD-593's check (`image.bin` + the biggest bank <= `MAPPED_MAX`) assumed
one; now banks are cut at `(MAPPED_MAX - image.bin) / 8` (and Stern's 40 MB), a
game sound too long for that stays in `image.bin`, a mode's sound too long for
it gets a bank of its own sized by the middle rule below, and a build whose
`image.bin` and its 8 biggest banks pass `MAPPED_MAX` is refused with the
reason.

**With PAD-607's long-song bank (merge, David 2026-10-18: "the middle
rule").** PAD-607 sized a long song's bank to all of `MAPPED_MAX - image.bin`,
on the reading that only one bank is ever mapped; its own rig proof played the
song under a GODZILLA ANGRY call from another bank, two banks live at once, as
the code above says. So a long sound's bank gets the room left beside
`image.bin` once the 7 biggest OTHER banks (the ones that can play beside it,
one a channel less its own) are counted, never past `alone_bank_room`
(`BANK_MAX_SEEN`, the emulator's window); the longest is placed first, and one
that does not fit is refused by name with the minutes it may have.

**A later Write of the same card.** Each bank carries a sid map
(`soundbank.SID_MAP_MAGIC`, between the descriptors and the directory; nothing
the game runs reads it): which game sid each fragment stands in for. A Write
reads the card's banks' maps (`bank_build.card_sid_map`) and treats a list
place holding an earlier bank sid as the game sid it stands for: a sound this
Write replaces again gets this Write's bank sid, or its own sid back when it
stays in `image.bin`; a sound it leaves alone keeps the earlier bank's.

**Also fixed here:** a build whose only edits all went into banks was refused
as "Nothing could be written", and its Write summary counted 0 sounds.
## How big a bank is (PAD-593, PAD-607)

The game maps `image.bin` for good and the bank it is playing beside it, both
whole, in its 32-bit address space (the boot tail maps and releases every bank
in turn, so only ONE bank is mapped with image.bin at boot -- but in play every
bank with a sound playing stays mapped, PAD-606 above, so the middle rule there
sizes the long-song bank: Rush 1.19's
image.bin and all 17 of its banks come to 3,049 MiB). A Godzilla custom card
at 2,125 MB + one 136 MB bank died on the machine at its first bank sound
("FATAL: error 232 (Flash memory init mmap failed)", PAD-593), while every
Stern card plays. What Stern ships (`banksizes.py`, every Spike 2 card on D:,
MiB):

| title | image.bin | banks | largest bank | image.bin + largest |
|---|---|---|---|---|
| Dungeons & Dragons 1.10 | 2,043 | 29 | 37 | **2,080** (the largest pair: `MAPPED_MAX`) |
| Rush 1.19 | 1,751 | 17 | **208** (218,349,330 bytes: `BANK_MAX_SEEN`) | 1,959 |
| James Bond 1.06 | 1,456 | 5 | 205 | 1,662 |
| Foo Fighters 1.04 | 1,269 | 16 | 129 | 1,399 |
| Metallica 1.04 | 734 | 24 | 98 | 832 |
| Deadpool 1.16 | 1,541 | 16 | 76 | 1,618 |
| John Wick 1.02 | 1,497 | 14 | 52 | 1,549 |

The failure is the PAIR, not the bank: Rush plays a 208 MiB bank, PAD-593's
card died on a 130 MiB one with a bigger image.bin. So:

* PAD-593: every bankable sound leaves image.bin once one has to, and banks
  are cut at `BANK_SLICE` (40 MB, D&D's size).
* PAD-607: a sound too long for a slice (a whole song as a mode's music: past
  ~3.8 min stereo) gets a bank to itself, `alone_bank_room(image.bin)` =
  `MAPPED_MAX - image.bin`, no bigger than `BANK_MAX_SEEN` (or the build
  emulator's window). Every pair then stays within D&D's and every bank within
  Rush's, both shipped and played on machines. David's Heisei build (image.bin
  2,010 MB) has 171 MB, about 16 minutes of stereo; a longer sound is refused
  by name, with the minutes it may have.

Proof (2026-10-17, `C:\tmp\PAD-607`): David's Heisei project with MASER BARRAGE's
music made a 9-minute stereo song (95 MB; every 4-s window unique: the beds
sped up under seeded noise) and the mode's clock 400 s. Main refuses it ("sound
idx 973 alone (95 MB) is bigger than a sound bank can be"); this branch builds a
16 GB card with the song alone in `image-sc03.bin` (95.3 MB, sid 0x30000;
image.bin 1,917 MiB + 90 MiB = 2,008 MiB, under D&D's 2,081) beside eight
slices. Rig 1, hidden and muted: the mode plays sound id 196608 = 0x30000, and
`songcheck.py` finds every window of the song at its own place in the capture
(song 1..290 s at capture +46.9 s, NCC 0.92-0.94; 200 s at 0.48 under a
GODZILLA ANGRY call), so the bank streams in order past 227 s, where a 40 MB
slice would have ended. No segv, no fatal. The rig cannot show the machine's
mapping limit (it gives the game 4 GiB); the sizes above are what keep every
pair and every bank within ones Stern's own cards play.

## The music modes' files and the sounds in turn in a bank (PAD-608)

The music modes (PAD-494) and the sounds in turn (PAD-565) switch their files at RUN
time: a mode's file by a descriptor the runtime hands the resolver (`get_asset_descriptor`
wrapped), a file in turn by a record key swapped at the lookup. Both name a record under
the game's own cat-0 sid, so both could only reach `image.bin` records, and a file that
did not fit was left out. PAD-606's route (the request lists rewritten in the program)
does not reach them: which file plays is decided while the game runs.

**At build time** (`engine._sound_modes_for_banks`, `_bank_mode_descs`): a host (one
file; one file in several modes of a slot is one host) can move when every game sid that
plays its slot -- and, for a song in parts (PAD-511), the sids that play the song without
its opening -- is a plain `image.bin` sid a request list names, plays the slot alone or
as the song it opens, and is not one a mode of the same Write plays. Such hosts are
bankable beside the modes' own sounds and the longer game sounds (`_plan_sound_banks`
`sm_frags`; a long one gets a bank to itself, as a mode's music does). In the bank the
host is ONE record and one FRAGMENT per (mode or turn, game sid): the first fragment is
the record's own, the rest come after the records (`soundbank.plan_bank(aliases=...)`,
`BankPlacement.record`; the header's fragment count covers them, the directory and the
sid map count records only). Each fragment's descriptor is the game sid's own,
rewritten by `_mode_descriptor_table` (so a song plays the file in place of every part,
once or looped as the song was) with every payload naming the bank record's key
verbatim (`_bank_descriptor`; a descriptor that still names another record cannot be a
bank sid's, so that sid plays its own). The music modes' sids are left out of PAD-606's
static list rewrite (`exclude_sids`), since the runtime swaps them.

**At run time** (`pad_mode_runtime.c` "IN A SOUND BANK"): `sounds.cfg` lines
`bsid <mode> <list id> <bank sid>` and `tsid <k> <slot key> <list id> <bank sid>`
(`list id` is what the request lists hold: the game sid, or an earlier Write's bank sid
for a sound this one leaves alone, `_list_ids`). At start the runtime finds every request
whose sid list names one of those ids (`blist_arm`) and hooks the play worker
(`site sound_worker`, which every shipped port but Turtles Pro 1.58 names; the sound log
shares the hook). At the worker's entry (`blist_play`) the request is pointed at a copy
of its own list with each id swapped for the bank sid the setting (or the turn) wants
now, or at its own list again -- `pm_sound_sid`'s pointer at +8 of the record, which the
worker reads at every play; a pointer someone else put there is left alone. A slot with a
file in turn in a bank takes its turns from the worker (`sndt_play`: a play of a request
naming the slot moves the turn on, `SNDT_GAP` apart), and the record lookup only swaps in
the turn's image.bin file, so the first play after power-on is now the sound's own.
Any request priority: Godzilla LE 1.16's request 12 has priority byte 253 (the first rig
run skipped it under `pm_sound_sid`'s `<= 9` guard).

**Read back** (PAD-553's record): a file in a bank names its record `<bank>:<record>` on
its `#file` / `#turn` line (an app before PAD-608 skips the line: the field is not a
number). An extract reads the card's `sounds.cfg` first (`engine._card_bank_records`) and
decodes just those records of the app's own banks (`category.extract_category_audio_parallel
(only=...)`) into `Music mode files/.from_card`, which the read-back copies from and
removes.

**Proof** (2026-10-17, `C:\tmp\PAD-608`, `artifacts/PAD-608/emulator/RESULTS.txt`): stock
Godzilla LE 1.16, image.bin's ceiling lowered to the stock file (`PAD_STERN_BANK_CAP`):
TUNE 16 (idx 2241) with a Music Mode 2 file (a 30 s 880 Hz pulsed tone) and idx 1239
(sid 16, request 12) replaced by a 500 Hz tone with two files in turn (1000 / 2000 Hz).
`write_overrides` put all three in `image-sc01.bin` (5.5 MB): TUNE 16's file as one record
with four fragments, 0x10000 / 0x10003-0x10005 for the game's 2500 / 2536 / 2541 / 2587,
the turn files 0x10001 / 0x10002; every one resolves through the game's resolver. Rig 1,
hidden and muted, the sound_fire instrument firing requests by hand: Music Mode 2 --
request 12 six times sounded 500, 1000, 2000, 500, 1000, 2000 Hz, and requests 94, 95,
152, 153 each played the 880 Hz file for their whole 12 s; Music Mode 1 -- the same turns,
and TUNE 16's opening (request 94) and its NO INTRO body (95) are the game's own (NCC
0.97 / 0.98; 0.02 in mode 2). 0 segv, 0 fatal in all three runs.

## Songs in parts in a bank (PAD-779)

Iron Maiden plays its songs as sequences: a sound id's descriptor names an intro, the song
and an outro (15 of its 22 songs), or chains songs (medleys). PAD-606 moved a longer game
sound only when one sound id played it alone, so a longer Iron Maiden song stayed in
`image.bin` and, with a card full of them, was trimmed (PAD-777).

**Which songs move** (`bank_build.game_sound_groups`): every sound id whose descriptor plays
a longer song, and every record those name, go into ONE bank (a bank sound id's descriptor
can only name records of its own bank). Songs that share a sound id (a medley) are one
group. A group moves only when every one of its sound ids is a plain `image.bin` id a request
list names, none is a mode's of the same Write, every part is a record of the card's
directory that nothing else of this Write uses, and no script is longer than
`soundbank.DESC_SLOT_MAX`; otherwise the whole group stays in `image.bin`, and the log says
why. The descriptors are read through their own end (`engine._wide_descriptors`: the play
tables read 80 bytes, and sound id 974 plays its fourth record, idx 919, at byte 76).

**In the bank** the group's longer songs are their user files, the game's own parts copies
of the stock sounds (decoded off `image.bin` at build time and encoded along the bank's
chain; a part the user replaced at its own length keeps the user's file, in `image.bin`
too). Each record gets a fragment; a sound id that opens with a record takes that record's
fragment, every other sound id a fragment past the records (`bank_build.seq_fragments`,
`plan_bank(aliases=...)`), and a record no sound id opens with a descriptor nothing plays.
Each sound id's descriptor is its own, every payload naming the bank copy's key verbatim
and the declared duration moved by the longer parts' growth (`bank_build.seq_descriptor`).
A bank with such a script gets descriptor slots up to 0x60 bytes (`plan_bank(desc_slot=)`;
the game's own descriptors run to 108 bytes, at keystream offsets from the same rule).
The request lists name the bank sound ids as PAD-606's do, and the sid map's extension
(`SID_MAP_EXT_MAGIC`, before the map) names the game sid of every fragment past the
records, so a later Write can put the lists back. A group is placed whole
(`soundbank.split_units`); one too big for a bank stays in `image.bin` whole.

**Iron Maiden LE 1.18** (PAD-777's shape: 20 longer songs of 55 MB, four 38 MB Option B
files): 13 of the 20 now go into banks (10 groups, 16 of the game's own parts copied),
where none did; image.bin 1,531 MB beside them. The other 7 are played by sound ids the
game starts other than through its request lists (954, 978, 267, 969), which PAD-606's
route cannot reach.

**Proof** (2026-10-27, `artifacts/PAD-779/emulator`): the real Iron Maiden LE 1.18 card, idx 150
(63 s) replaced by a 70 s 700 Hz tone and idx 618 (138 s) by a 145 s 1100 Hz one, image.bin's
ceiling lowered to the stock file (`PAD_STERN_BANK_CAP`), an override set (`write_overrides`):
`image-sc01.bin` (43.3 MB) holds 618, 150 and the game's own 919 and 222; its 5 fragments
resolve through the game's resolver, and requests 555 / 554 / 552 name 0x10003 / 0x10001 /
0x10004 for sound ids 974 / 960 / 976. Rig 3, hidden and muted, the sound_fire instrument:
request 555 played the game's intro (idx 222, NCC 0.81 against its stock decode) 0-7 s, the
700 Hz file 7-78 s, the 1100 Hz file 78-223 s, the game's outro (idx 919, NCC 0.81) from 223 s;
554 the 700 Hz file for 70 s, then the 1100 Hz one; 552 the intro, then the 700 Hz file. Both
files whole, past their stock lengths. 0 segv, 0 fatal. (The capture is 44.1 kHz.)

## Sound ids no request names (PAD-784)

PAD-779 kept 7 of Iron Maiden LE 1.18's 20 longer songs in `image.bin` because a sound id
that plays them (954, 978, 267, 969) is in none of the game's request lists, taken for one
the game starts some other way. It starts none that way. The game's descriptor resolver
(`site sound_resolve`, 0x1403a4) has five callers on Iron Maiden LE 1.18 and five at the same
places of the shared sound code on Godzilla LE 1.16 (0x43c104), no pointer to it anywhere: the
play worker (`site sound_worker`), which resolves the sound id it picks from the request's
list; a query that walks a request's list; one that reads a request record's list; a query of
one sound id's descriptor flags (its caller stores a flag, plays nothing); and the bank
loader, which walks a category's ids at load. Only the resolver and the loader read the
descriptor keystream (0x5d759c). The request table's lists are static data (all 572 point
into the file) and nothing writes the table; the four ids appear nowhere in the program, and
no descriptor names a sound id. So 954, 978, 267 and 969, like the other 127 of the card's 983
ids no list names, never play.

`bank_build.never_played` names such ids (plain `image.bin` ids no list names and no mode of
the Write plays; none when the request table cannot be read), and `game_sound_sids`,
`game_sound_groups` and `engine._sound_modes_for_banks` leave them out: a song moves with the
ids that do play it, and the idle id keeps naming `image.bin`'s record. A song only idle ids
play stays where it is, and the log says the game never plays it.

**Iron Maiden LE 1.18**, PAD-777's shape again: 17 of the 20 songs plan into banks (12
groups), where 13 did; idx 205 moves with 949 and 956 (954 left), idx 895 with 962 (978
left; 281 and 426 join it as a medley through 979). The 3 left, idx 612, 786 and 930, are
played only by 267, 978 and 969: the game never plays them.

## A music mode's file for a song in parts in a bank (PAD-791)

PAD-608 banked a music mode's file only when every sound id that plays its slot plays it
alone (or as the song it opens, PAD-511). Iron Maiden plays most songs as intro, song and
outro sequences and medleys, so 7 of the PAD-777 reporter's 8 "Swapped Songs Version" files
(slots 150, 178, 492, 575, 618, 623, 880) stayed in `image.bin` and were left out when it
filled.

**Which files move** (`engine._sound_modes_for_banks`, `bank_build.mode_seq_groups`): a host
whose sound ids play its slot together with other records is no longer refused for that; its
sound ids are read through their own end (`engine._wide_descriptors_once`, the same read
PAD-779's songs use, done once a Write). Each (mode, sound id) is a LINE; hosts one line
plays (a medley's two songs with files in the same mode: 150 and 618 under 960, 974, 976)
are one group, placed whole (`soundbank.split_units`). The group's bank gets a COPY of every
other record its lines play: the game's own decoded off `image.bin`, the user's same-length
file, or the user's longer replacement at its length (`ModeSeq.grown`; 492's intro 307). A
line for a file that plays in place of a whole song (PAD-511 `song` / `bodies`) needs none.
A group moves only when every line's sound id is a plain listed `image.bin` id no mode of the
Write plays, its script fits `DESC_SLOT_MAX`, and no part is another file's host, a mode's
own grown sound or a record of several variants; otherwise its files stay in `image.bin`, and
the log says why.

**In the bank** each file's record and each copy is a record; a line takes its host's own
fragment when it is the first to open with it, and every other line a fragment past the
records (`bank_build.mode_seq_fragments`; a copy never gives a line its own fragment, since a
PAD-779 song in the same bank may share the copy). Each line's descriptor is
`_mode_descriptor_table`'s for that mode, off the game's own descriptor through its own end
(`ends=`), every slot of that mode it plays swapped for its file, then every payload pointed
at the bank's records (`bank_build.seq_descriptor`; a longer copy moves the declared
duration). A line whose descriptor would name a record outside the bank plays the game's own
(logged); a fragment no line plays gets a descriptor naming its record. The runtime is
unchanged: `bsid <mode> <list id> <bank sid>`, one line per (mode, sound id) (`_bank_sid_lines`
drops the medley's duplicate).

**The game's longer song on the same slot** (the reporter lengthened those songs too): the
sound ids of a music mode's file used to be kept out of PAD-606/779's banks altogether
(`exclude_sids`), so those songs stayed in `image.bin`; with the files' banks taking memory
beside it, a first run of this ticket cut 8 of them (PAD-777 cut 2). Now only the sound ids of a file that stays in
`image.bin` (and of the files the runtime swaps by key: files in turn of a mode's file, the
attract flipper sounds, the jukebox) are kept out; a game song on a banked file's sound ids
goes into a bank of its own, its request lists name its bank id, and the file's `bsid` line
names that id (`_list_ids`), which the runtime swaps from in the file's mode. If the planner
then keeps such a file in `image.bin` after all (too big), the song stays with it
(`_sm_kept_sids`): the runtime plays that file under the game's own id.

**The file's host record** (`_sound_mode_host`, `parts=`) is a record the game plays in a
sequence only when nothing else fits: such a host cannot be a part's copy as well, and on the
reporter's card 5 of the 8 hosts were parts (919 kept the 150/618 medley's files out; 91 kept
idx 70's song out). The sequences are read off the descriptors whole before the hosts are
picked (Iron Maiden's 974 plays idx 919 past the play tables' 80 bytes); `_wide_descriptors_once`
keeps that read for the planner (5.8 s on Iron Maiden).

**A record in two banks**: a part's copy can sit in a music mode's bank and, as the user's
longer song, in PAD-779's bank of the game's (307, 492's intro). Banks know their groups by
the units placed in them, not by record idx (an idx match put 307's song in the file's bank
too, whose descriptors then failed: KeyError 492).

**Iron Maiden LE 1.18**, the reporter's shape (17 longer songs, 8 Option B files, 16 GB card,
`his777.py` through the app's Write): all 8 files go into banks where 1 did (0 left out,
PAD-777 left out 7), and his longer songs on those slots into banks of the game's beside
them: 17 banks, all verified and every bank sound id resolving through the game's resolver,
together at most 2,172 MB with image.bin (Stern's largest 2,181 MB); 1 song trimmed, idx 930,
which the game never plays (PAD-777 trimmed 2).

**Proof** (2026-10-28, `artifacts/PAD-791/emulator/RESULTS.txt`): stock Iron Maiden LE 1.18,
music mode 2 files of pure tones on the 7 slots (30 s each), the user's longer intro 307
(300 Hz, 19 s) and longer 150 (450 Hz, 70 s), image.bin capped a little past stock, an
override set: 4 banks verified, every sound id resolving. Rigs 1 and 2, hidden and muted, the
sound_fire instrument, `force 2` then `force 1` in sounds.cfg. Mode 2: request 554 (960)
played the 500 Hz file then the 700 Hz one; 555 (974) the game's intro 222, both files, the
outro 919; 571 (945) 900 Hz then 94; 568 (975) 900 Hz; 535 (935) the longer 307 then 1100 Hz
then 212; 543 (940) 1300 then 1500 Hz then 935; 539 (958) 818, 1700 Hz, 758. Every copied part
matched its stock decode (NCC 0.89-0.96; noise 0.02, the wrong part at most 0.44). Mode 1:
554 played the longer 150 whole (70 s) from the game's bank, then 618 (NCC 0.95); 555 222,
the longer 150, 618; 535 the longer 307, then 492 (NCC 0.95). 0 segv, 0 fatal.
