# PAD-685: Beatles jukebox (one image, a song drawn at every song mode's start)

Ben (Beatles 1.29, 60+ late-era songs) answered the easy/medium/hard ask on 2026-10-23:

- One image, no menu, no choice: "You boot it up and throw the dice". Stackable in a multi-boot later.
- A new pick each power-up or each game is all he needs.
- 95% of songs fit any of the five song modes (the game clips them at the mode's end).
- Weighted: about 65% common songs, a few obscure ones now and then, never the same song twice in a game.
- Each song is ONE audio file and ONE intro video with the song name in it; the mode screens, other videos
  and the "... Champion" text he makes generic.

## What the emulator showed (Beatles 1.29, stock card, a trace build of the runtime)

- A song mode starts at its start function (the port's `block_start_0..4`, the song descriptor table
  0x4b60e0, 0x38 a song, start at +0xc); song select 0x3ddc4 runs when the FAB (switches 52-54), FOUR
  (78-81) and centre (85-88) drop banks are complete.
- Its intro is a clip of the video bank asked for by name on the bank's surface, 0-3 s after the start
  (before or after the music): `FeatureStarts.<Frenzy|Orbits|DropTarget|Spinner|POP>_Start`, with a short
  version `Feature_Starts_Short.<...>_Start_Short` the game may ask for instead.
- Its music is request 89/87/85/83/84 (the descriptor's +0x34): an opening record then a body record that
  loops (All My Loving 419 + 848, Drive My Car 200 + 417, I Should Have Known Better 753 + 669, Ticket to
  Ride 722 + 431, It Won't Be Long 42 + 667).
- The game plays a record it is handed WHOLE: a 55 s record swapped into Drive My Car's 19.7 s opening
  played to its end, and the body was looked up 55 s later. So a song is never cut; swapping every record
  of the mode gives the song whole, then again while the mode lasts.

## What was built

- Runtime (pad_mode_runtime.c "the jukebox"): `jmode <start site> <intro clips> <record keys>` and
  `jsong <weight> <record key> <clip>` lines in sounds.cfg; each start site hooked draws a song (weighted,
  none of the last five), and until the next start every record of the mode and every intro clip of it
  plays that song's.
- `plugins/stern/jukebox.py`: the project's songs (`jukebox` sidecar key), the title table, the Audio
  tab's offer.
- Write: songs' audio built whole as records of their own (the sounds in turn's road, pseudo modes
  `sound_modes.juke_mode`), intro videos added to the video bank as `PadJukebox<k>` (the random clips'
  road), jmode/jsong lines, the pre-flight sizes the videos, the card record keeps each song (`#jsong`)
  so an extract brings the jukebox back.
- Audio tab: Jukebox button and window (add songs, intro video, Common / Normal / Rare, play, order,
  take out). Help topic and de/es/fr words.

## Proof (work/artifacts/PAD-685)

- Stock songs dealt among their modes (runtime only): Drive My Car drew It Won't Be Long, intro and audio
  swapped (r 0.992 against the stock capture).
- Write-built override set from the stock extract, three songs: starts drew 1, 3, 2; PadJukebox1 (the
  Taxman clip) on the glass in place of "I Should Have Known Better"; each song heard (r 0.93-0.96 against
  its file, others under 0.08); song 3 (81 s) looked up again 81 s in. Write's "only" cfg arms it too.
- Before/after shots of the Audio tab.

## Pools (PAD-1007)

Ben asked for "X pools, each with its own song/audio list", restricting which songs replace which of the
game's music, a song wanted in two pools added to each. Beatles 1.29 has nine musics (sound ids 952-960, one
opening + body record pair each; the request table):

- **Song modes** (pool 0): the five above.
- **Special modes** (pool 1), the two multiballs: Beatlemania Multiball, the four-ball one, sid 952 (request
  90, records 461 + 370; emulator: its own start, wizard_go_1, showed `Taxman_Start` and looked 952 up ~20 s
  in), and the jackpot multiball, sid 955 (request 82, records 574 + 797; called from the multiball start's
  other branch and beside the `Multiball_A` clips: intro `Multiball_feature.Multiball_A_Start`).
- **Background music** (pool 2): sids 958 (148 + 311, "MUSIC: MULTIBALL READY") and 956 (294 + 494). No intro.

`jmode` / `jsong` lines end in their pool's number (none for 0, so an old cfg reads as before); a music draws
only its pool's songs, none of that pool's last five; a pool with no song leaves its musics alone (no jmode
line). The four new musics have no start site: they draw at the first ask, again at each new game
(game_start) or after JUKE_GAP. JUKE_MODES went 8 -> 16. The sidecar's songs carry `"pool"` (none = song
modes), the card's `#jsong` record a trailing pool key, so an extract puts each song back in its pool. The
Jukebox window shows one pool at a time (a picker over the list); Add songs and Clear all work on that pool.

## One song in two pools (PAD-1012)

Ben asked that a song added to more than one pool is not played twice in a game ("if song A was played as one
of the 5 main modes, it will not be picked ... when special mode or background music starts"), telling them
alike by name. Each pool's copy is its own jsong line (one file in two pools shares one record, a second file
of that name has its own), so the runtime could not tell. Write now joins a song's copies, alike by name
(`jukebox.song_key`, the file's name without extension, case ignored) or played from one record, and gives
each copy the first one's k as a 6th field after the pool (`jsong <w> <key> <clip> <pool> <same>`, the pool
then written even when 0). The runtime keeps the songs drawn since the game started (reset when the
game_start count moves) and a draw passes over a song whose copy in ANOTHER pool is among them; the pool's
last-five window then counts only the songs left, so a song played last game comes back before one played
earlier in this one; when every song of the pool was played elsewhere it draws as before (the song again,
not the game's own music). The same pool's rule is unchanged. The log says "passed over a song played in
another pool this game".
