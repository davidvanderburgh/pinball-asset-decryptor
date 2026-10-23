# PAD-685: Beatles jukebox (one image, a new set of songs every game)

Ben (Beatles 1.29, 60+ late-era songs) answered the easy/medium/hard ask on 2026-10-23:

- One image, no menu, no choice: "You boot it up and throw the dice". Stackable in a multi-boot later.
- A new pick each power-up or each game is all he needs; "randomly choosing X songs at the start of
  each game would be really interesting".
- 95% of songs fit any of the five song modes (the game clips them at the mode's end). A few are
  shorter than the longest mode; he will pad those himself.
- Weighted: about 65% common songs, a few obscure ones now and then. Listing a common song 3x was his
  workaround, but it could repeat a song in one game, which he does not want.
- Each song is ONE audio file and ONE intro video with the song name in it. The mode screens, other
  videos and the "... Champion" text he makes generic, so they are the same for every song.

## What exists (checked on this branch)

- Audio: sounds in turn / at random (PAD-565/638) swap a slot's record at `sound_lookup`;
  `beatles-1.29` is in `sound_modes.TURN_PROVEN`. Each slot picks on its own (`sndt_next`), at most
  `SNDT_MAX` 16 files, uniform, "any but the last". No link to anything else.
- Video: clip variants (PAD-446) swap a bank clip by name; Beatles has no `clip_play`, but the port has
  the clip v2 surface route (`surface_find`, `surface_set_video` 0x4250ec; a clip seen on the glass,
  item 164). `clip_variants.PROVEN` is Godzilla only. Ben's album card differs in 82 clips of the video
  bank `60ed7e50...` (and 172 pictures of Element_4x3 `08065a0c...`, which he is making generic), so
  his song videos are bank clips the game plays by name.
- Song modes: `cstarts/json/beatles-1.29.json`, five return-checked starts (All My Loving 0x4b220,
  Drive My Car 0x4da44, Should Have Known Better 0x50558, Ticket to Ride 0x52cdc, It Won't Be Long
  0x5567c) through song select 0x3ddc4 / descriptor table 0x4b60e0.

## Design (the recommendation built on)

A JUKEBOX in the project: a list of songs, each `{audio, intro clip, weight 1..3}`.

1. At each GAME START the runtime deals one song to each of the five song modes: weighted draw
   without replacement, so no song twice in a game, common songs more often. One setlist per game,
   shared by its players (Ben's "each game"); a new game deals again.
2. When a song mode's music is looked up, `sound_lookup` hands the game the dealt song's record (the
   sndt road, but the index comes from the deal, not `sndt_next`).
3. When that mode's intro clip is asked for by name, the clip v2 surface hook plays the dealt song's
   clip (the clip variants road, the index from the same deal), so the video always matches the song.
4. Records: one per song, whole (the game stops it at the mode's end); in a sound bank when image.bin
   has no room (PAD-607/608 road). Clips: one bank clip per song (`__PadVar` naming).
5. Text: none per song (Ben burns the name into the intro video and goes generic elsewhere).

## Steps

1. Emulator, Beatles 1.29: per song mode, which sound request / slot is its music and which bank clip
   is its intro (start each mode, log `sound_lookup` keys and `surface_set_video` names).
2. Prove clip v2 swaps on Beatles 1.29 (one bank clip, one variant, on the glass); add it to
   `clip_variants.PROVEN` once seen.
3. Runtime: `jukebox.cfg` (songs: per mode the stock music key + stock clip name; per song its record
   key per mode and clip name, weight); deal at game start (the game-start hook the challenge list
   uses); feed the deal to the sndt and clipv picks.
4. Write: build the records and clips, write `jukebox.cfg`, lift the 16-file cap for jukebox songs.
5. GUI: a Jukebox list (song audio, intro video, Common/Rare); before/after shots in
   work/artifacts/PAD-685.
6. Proof: two games in the emulator deal different setlists, no repeats, heard record and clip on the
   glass match; targeted tests for cfg and the build.
