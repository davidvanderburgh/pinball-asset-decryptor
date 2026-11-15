# Custom modes on a Stern Spike 3 card (PAD-1272)

PAD-1269 built the mode runtime for Spike 3's 64-bit ARM games (`prebuilt/mode64.so`), gave
s3run.sh a preload hook (`PAD_S3_MODE_SO`) and made the Modes tab name a Spike 3 card. This is
the plumbing that puts a project's modes ON a Spike 3 card and runs them in Try it. A title's
port (PAD-1271 for Star Wars ELG) is the only thing a Spike 3 build still needs.

## Where the modes go

A Spike 2 card carries them on the system partition (`/usr/local/padmode`, game_monitor
hooked: `tools/spike2_emu/modehook.py`). A Spike 3 card's rootfs is LUKS2 like every partition
but it is the signed image's, and a Write changes only the games partition (p6), so:

| on p6 | what |
|---|---|
| `pad/padmode/mode.so` | mode64.so, 0755 root |
| `pad/padmode/game.port`, `mode.cfg`, `mode1.cfg` ..., `stock.cfg`, `pad_modes.zip` | as on Spike 2, 0644 root |
| `pad/padmode/padmode.sh` | the hook, 0755 |
| `pad/padmode/game.target` | where `/games/game` pointed on the stock card |
| `game` | `-> pad/padmode/padmode.sh` |

`/etc/init.d/S95game` -> `game_monitor` runs `/games/game` in a restart loop and reads its
exit code. The hook appends the runtime to `LD_PRELOAD` and `exec`s the program `game.target`
names, so game_monitor reads the game's own code and conagent (its own monitor) never sees the
runtime - Spike 3 multi-boot's road from the same link (`tools/spike3_emu/MULTIBOOT.md`). A hook
with no target runs the card's first game program stock: never a dead machine. A multi-boot
card takes no modes (each image is a whole games tree; modes are made for one build).

The runtime's sources name `/usr/local/padmode/<file>` everywhere; the 64-bit build alone wraps
`open()` so those paths open `/games/pad/padmode/<file>` (pad_mode_runtime.c, `pm_card_open`).
The Spike 2 mode.so is byte-identical.

## Write (spike3_write -> spike3_modes)

1. `spike3_modes.plan` - the preview switch, code modes (left out: compiled for Spike 2's
   32-bit ARM), `card_refusal` (no port / no Insider gate), a multi-boot card, then
   `mode_write.plan` against the card's own 64-bit program (`/games/game`'s target; the port
   check reads ELF64); a mode's own sounds and end sound go into the card's image.bin
   (PAD-1296, below).
   `p2_payload(arch="a64")` stages mode64.so as `mode.so`.
2. A mode that cannot be built stops the Write before the 62 GB copy; a refusal leaves the
   modes out with the reason and writes the rest, as on Spike 2.
3. The scenes the modes' screens and clips rewrite go on whole with the grown files (their
   `.sidx` records refreshed by the existing loop).
4. After the copies, `spike3_modes.install` runs over the volume through dm-crypt
   (`ext4_grow.run_on_luks`: the grow script's mount with a body of its own).
5. A card an earlier build put modes on, written now with none, has them taken off
   (`/games/game` back to `game.target`, `pad/padmode` gone).

The engine (`_compute_patches`) no longer builds the Spike 2 mode family onto a Spike 3 volume:
modes are spike3_write's, and so is the score feed (PAD-1297, below); every other part a project
asks for is left out with a sentence of its own (`spike3_modes.FAMILY_LEFT_OUT`).

## The family on Spike 3 (PAD-1297)

On Spike 2 thirteen parts ride the modes' delivery: the runtime on p2 with a cfg of their own
beside it, and for some a game-program patch (an operator-menu row) or bank records. On Spike 3
the runtime and its files go in `/games/pad/padmode` (above) and each cfg is read there through
`pm_card_open`; what decides is whether the 64-bit runtime can do the part and whether the Python
that writes it reads a 64-bit program. Census against `ports/spike3/star_wars_elg-1.10.port`
(the only Spike 3 port) and pad_mode_runtime.c, 2026-11-15:

| part | Spike 2 card pieces | on Spike 3 | what it needs |
|---|---|---|---|
| **score feed** | scorefeed.cfg | **goes on (files alone)** | tick, hook_dispatch, game_start / ball_start / game_over, u64 scores: all live. Only the Insider login ids are 32-bit (the user-manager finder `coop_play.insider_users`, an `unsigned` address in `feed_login`): reports name no logins, and the log says so |
| random clips | clips.cfg, clips in the video bank | left out | the clip v2 route's `string_new` site (64-bit builds its own strings), the clip name read as a 4-byte pointer, surface compares cut to 32 bits |
| screen times | `stime` lines in clips.cfg | left out | rides random clips' arm; the vtable slot read and written as 4 bytes; screen_time.py reads 32-bit vtables |
| music modes | sounds.cfg, bank records, MUSIC MODE row | left out | off on 64-bit by design (32-bit asset descriptors); Spike 3's songs are image.bin records (PAD-1296 appends them); a 64-bit menu row |
| editions | EDITION row, codeselect's `edition=` | left out | no runtime: a 64-bit operator-menu row (adjustments.py refuses ELF64) and the Spike 3 multi-boot reading EDITION |
| picture settings | picture.cfg, 3 menu rows | left out | 8-byte GOT writes in a PIE; menu rows; switched off for every card anyway (OFFERED False) |
| co-op play | coop.cfg, CO-OP PLAY row, HUD screens, clips | left out | every switch edge (`switch_edge`: Spike 3's drain makes none), the player sites, a 64-bit message table, the menu row |
| handicaps | handicap.cfg, HANDICAP row | left out | flipper edges (as co-op), `coop_player`, the menu row; handicap.py reads 32-bit code |
| Prolonged Competition | comp.cfg | left out | the challenge-menu sites (not placed); `hook_full`, 0 on 64-bit; 4-byte entry name, 32-bit frame |
| records on the high scores | records.cfg | left out | the champion framework's sites (not placed) and its 64-bit record |
| attract items | attract.cfg, clips | left out | `attract_table` / `attract_sleep` (not on ELG's Spike 2 port either), 4-byte table pointers |
| inactivity pausing | idle.cfg | left out | `timers_paused` / `song_track` (ELG pauses its own timers: its gate says so) |
| expression light shows | cabshow.cfg | left out | `cablamp` lines (ELG has no cabinet lights), the game's show table as 64-bit, voice count measured |

The operator-menu rows (MUSIC MODE, EDITION, CO-OP PLAY, HANDICAP, the picture rows) all wait on
one piece: adjustments.py / menu_settings.py writing a 64-bit program. Co-op, handicaps and the
attract / shot sounds of music modes wait on a 64-bit switch-edge source. So the order the rest
lands in: the 64-bit menu rows; the switch-edge source; random clips with screen times; music
modes; editions; co-op with handicaps (and the feed's logins, the same user-manager finder);
Prolonged Competition with records; attract items, idle and light shows with the first Spike 3
title whose port has them. Picture settings stay off on every card.

**The score feed on Spike 3.** `spike3_modes.feed_wanted` is the feed's own gate, quiet (the
engine's `_feed_for_build` has said why one is left out); `spike3_modes.plan` hands it to
`mode_write.plan` with the modes, or alone (`modes_on=False`: a card of the feed by itself gets
the runtime, the port and scorefeed.cfg with `only`, and the hook). It needs no mode-maker
preview, as on Spike 2; a multi-boot card takes none, said in its own sentence.

Proof (2026-11-15, Spike 3 rig slot 1, hidden and MUTED): the set planned by `spike3_modes.plan`
from the library's Star Wars ELG 1.10 card (mode.so = prebuilt/mode64.so, game.port, scorefeed.cfg
`only`), the address 10.77.0.1 put on the game's own loopback (s3run's private network) with a
stand-in server listening there. The runtime armed it alone (`armed: score feed only (scorefeed.cfg
says the card has no modes) - nothing else is hooked`, at the game's game_over; bus 0x4d game, 0x25
ball, game_over); one player, every ball drained (`s3press.py drain`); at the game's own game_over
`game 1 over - 1 player(s): 208740` and 0.1 s later `game 1 posted ... (HTTP 200)`, the server
receiving `{"source":"PAD score feed","game":"Star Wars ELG 1.10 (Spike 3)","port":"star_wars_elg
1.10","game_number":1,...,"players":1,"scores":[208740],"insider":[null]}` - the score the game's
own attract screen then showed as Player 1's. (A first try with the server down said `no way to the
server's address` on each try, and the game played on.) A rig note: every Start press in a game adds
a player, so a job starts one game with one held Start (first-boot GAME SETUP) and one press.
Tests: tests/test_pad1297_spike3_family.py.

## The Modes tab and Try it

- The tab's card read (`title_reader`) opens a Spike 3 card's games partition with the user's
  key and reads `/games/game`'s program. `port_derive.ensure_port` takes, for a 64-bit program,
  the listed port of its game whose every site is the program's own (never one derived here).
  **Star Wars ELG 1.10 has a Spike 2 build of the same game folder and version** whose shipped
  port is passed over by that test. PAD-1277: a Spike 3 port ships in `ports/spike3/` under the
  same `<game>-<version>.port` name; `mode_runtime.port_arch` reads the machine off that folder,
  `port_paths` lists both, and every lookup by build asks for one machine (`port_file(...,
  arch)`, `profile_for_card(..., arch)` with `mode_project.card_arch(card)`, `find_port` by the
  program's ELF class). The Spike 3 profile is keyed `<game>_<version>_spike3`, labelled
  "(Spike 3)", and reads the proof tables under `<game>-<version>/spike3`, so none of the
  Spike 2 build's emulator proofs (lamps, multiball, ...) carry over.
- Try it on a Spike 3 card: the Modes tab builds the same set from the card
  (`_tryit_prepare_s3`), and the Emulate tab's Spike 3 start now runs the prepare (it skipped
  it) and hands `--mode-so` / `--mode-files` to s3launch.sh -> `PAD_S3_MODE_SO` /
  `PAD_S3_MODE_FILES`. PAD-1284: the scenes the modes' screens and clips rewrite (and a clip's
  new file) go into the rig slot's /games for the run, whole (`games.patch`, below).
- s3run.sh on a card with modes: a plain run (binfmt) runs the card's own hook; a
  checkpointable run or the explicit qemu runs programs only, so s3run does the hook's two
  steps (the target program, the card's mode.so preloaded); with `PAD_S3_MODE_SO` (Try it) the
  card's is not loaded too. Its host-side readers (switch list, bridge, playfield) read the
  program the hook names.

## Proof (2026-11-14)

Star Wars ELG 1.10 from the library + a copy of PAD-1271's draft port (process-only):
`write_card` copied the card (595 s), planned PAD TEST against the card's 64-bit program and
installed 4 files; read back through the card's own encryption: `/games/game -> pad/padmode/
padmode.sh`, `game.target = star_wars_elg/game`, root-owned 0755/0644, mode.so = mode64.so.
Booted on rig slot 72 (muted, hidden): plain run - the card's hook started the game and the
runtime logged `port /games/pad/padmode/game.port`; checkpointable run - s3run started
`/games/star_wars_elg/game` with the card's mode.so; with a port naming only `tick` the game ran
to the cap (61 frames, 6 node boards, its Game Setup screen) with the runtime inside it ("Nothing
is hooked; the game runs stock"). Try it: the tab's prepare built the set from the card and the
stock card ran it with the runtime reading `/dump/game.port` (7 sites). The draft port's own
crash 0.8 s in (seen in PAD-1271's runs too) is the port's, not the delivery's.

## The first Spike 3 port (PAD-1271)

`ports/spike3/star_wars_elg-1.10.port`, drafted by `tools/spike3_emu/s3port.py` from the
proven Spike 2 port of the same build (`s3port.py <S2 game> <S2 port> <S3 game> -o <port>`):
functions paired by vtable slot, unique strings and call-graph growth (both programs are
stripped), globals by what the paired functions load through the GOT, switches renumbered by
name from the program's own device table (Spike 3's ids are one lower), scores 64-bit. It
carries only what the 64-bit runtime has been run with: the tick, event dispatch (ball end is
bus event 0x34), score_add, the two switch_hit sites, the Insider gate, and cur_player /
scores / score_mult / mode_mask. Every other placed site is written as a comment with its
address: the runtime features that use them still read the game's structs at 32-bit offsets,
and arming them stopped the game (the "crash 0.8 s in" above was the full draft). Each is
carried when its feature is made 64-bit and proven. The runtime fixes it needed are in
hook_a64.h (hidden template labels, a branch as a hooked first instruction, a veto read from w0)
and pad_mode_runtime.c (a 64-bit achievement-query scan, the switch id masked to 16 bits).

Proof: a TRENCH RUN mode (3 trigger shots, 30 s, 5 award shots) on the Spike 3 emulator, slot
41, muted and hidden, with `prebuilt/mode64.so` and this port: it started on the third trigger,
scored 1M..5M on five shots (score 26,630 -> 15,080,990) and ended when its time ran out, the
game running on to the cap. Tests: tests/test_pad1271_spike3_port.py.

## Callouts and sounds on Spike 3 (PAD-1282)

The six sound sites (callout, callout_nth, sound_play, sound_nth, sound_active, sound_stop) are plain calls into
the game with a u16 request in w0 and were 64-bit already; what crashed was the runtime's sound features around
them, which read the engine's structs at Spike 2's offsets. The Spike 3 engine has the same structs with 8-byte
pointers, read in Star Wars ELG 1.10's own code and the same in Pokemon LE 0.82, Fallout LE 0.82 and Star Wars
2025 LE 0.96 (every Spike 3 title in the library):

| struct | Spike 2 | Spike 3 |
|---|---|---|
| request record | 20 bytes: 3 pointers, sid list at +8, priority +16, flags +17, +19 = 0 | 32 bytes: sid list at +16, priority +28, flags +29, +31 = 0 (the same 8 tail bytes as the Spike 2 build's, for every request) |
| channel (8 of them) | 196 bytes: request +184, voice bits +188, bus +189, voice pointers (4 bytes) +92 | 288 bytes: request +272, voice bits +276, bus +277, voice pointers (8 bytes) +144 |
| voice | volume step u16 +48 | +56 |

pad_mode_runtime.c takes the record layout from `REQ_*` (pointer-sized, so Spike 2's constants fold to what they
were), reads the voice pointers as `pm_addr`, holds the request table in a `pm_addr` (a PIE's addresses do not fit
an `unsigned`), and masks the worker's request to w0's u16. **sound_lookup** on Spike 3 is the bank map's find,
and takes the 8-byte record key BY VALUE in x1 (Spike 2: its address in r1): every lookup hook reads and swaps
the key through `LOOKUP_KEY` / `LOOKUP_TAKE`. Two 32-bit-only pieces stay off on 64-bit, each logging so: the
own-sound "which of these plays" patch (32-bit instruction match) and music modes (32-bit asset descriptors;
music modes ride Spike 2's delivery anyway). Spike 2's mode.so is byte-identical.

s3port.py could not pair sound_worker / sound_resolve / sound_lookup; `sound_engine()` reads them off the program
from the placed callout (the worker is the callout's call; resolve the worker's call that takes a stack slot;
lookup the find called after the record key's bank bits are ORed in), with the request table and count (the
worker's GOT loads) and the channel table (sound_stop's, checked against sound_active's +272). The channel values
are carried with it. Spike 3's request ids are Spike 2's + 2 on ELG 1.10 (two requests added early):
`request_shift` reads that off the constant ids both builds pass to the callout (112 of 130 at +2), and the
callouts are carried renumbered (countdown 168 -> 170, step -1).

Proof (2026-11-14, Spike 3 rig slot 82, hidden and MUTED, `PAD_S3_AUDIO_OUT=1` keeping the PCM): a mode file
SOUND CHECK (prebuilt mode64.so) started on three Death Star hits, played request 153 at its start (sound_play;
its record read priority 3 flags 1, the card's bytes), callout 168 at 15 s left and the countdown 166..170 at
5..1 s (callout_nth), each taken by the game's own worker (`[pad] sound <request>`, the 64-bit worker hook) with
the engine's record lookups after them (the 64-bit lookup hook). The SDK's sound_fire_mode.c in attract: request
153 on bus 0x04 active while it played and 0 after; callout 168 and callout_nth 170 n=2 / n=4 (= 168 / 166) on
the voice bus 0x02; sound_stop cut 153 within 80 ms; a 1500 ms fade of request 24 ramped the PCM from 67 dB to
silence over exactly 1.5 s (the voice volume at +56), where a stop of the same sound cut it in under 100 ms.
Tests: tests/test_pad1282_spike3_sound.py.

## A mode's own sounds and end sound on Spike 3 (PAD-1296)

Spike 2 carries them in its whitened sound bank; Spike 3's `image.bin` is plain PCM behind a plaintext directory
(spike3_replace.md), so each sound is a **record appended to it**, and the mode swaps it in on a carrier exactly
as item 163 does on Spike 2 (`swap <request> <stock key> <our key>` in the mode file; the 64-bit lookup hook takes
the key the bank map's find is handed, PAD-1282).

- **The record key is the directory's +0x08/+0x0c words** (flags_lo, param), little-endian: Star Wars ELG 1.10's
  lookups logged `46000220 02002060`, `4a000220 000060e0` ..., each exactly one record's, and all 1038 pairs on
  the card are unique. A sound id's descriptor names its recordings by the same 8 bytes (spike3_requests).
- **The game's bank map takes every directory record**, appended ones too: four records after the last (count
  1038 -> 1042) were found and played.
- **A new key** (`spike3_write.free_key`) keeps the carrier's flags word (channel bit and the rest) and takes the
  nearest param no record has with it, changing only param bits other records already vary, never bits 0-1;
  param2 (an id) is any unused value.
- **Appending** (`spike3_write._stage_grown`, `adds`): the bodies after the old body region (after any grown
  replacement), the directory moved past them with a record per sound, the header's count (0x60), directory
  (0x40) and tail word (0x38) moved, the trailer's CRC32 over the new directory. The container goes on whole
  (a grow job), its `.sidx` record refreshed - one file with the project's replaced sounds.
- **Carriers** (`mode_sounds.TITLES_A64`, `profile_carriers`): requests the game never plays. Star Wars ELG
  1.10: the Spike 2 build's census carriers two request ids on (request_shift +2), each the same recording -
  calls 135 202 201 74 238 (mono, 2.40 .. 1.64 s, longest first as on Spike 2), music 70 345 73 78 (Spike 2's
  344 is 343's record, so 346 is left out: one swap would take both). None was played by the game in the two
  emulator games run with the sound log on. The stock key is the record the carrier's first sound id names
  (read off the card).
- **The end sound always rides a carrier** on Spike 3 (`mode_write.end_on_carrier`): nothing re-points a
  request of the 64-bit program. So every mode can have its own.
- **A call plays whole past its carrier's length** (a 3.5 s start call on a 2.4 s carrier was heard to its
  end), and the music loops past its record (a 20 s file under a 26 s mode).
- **Try it** carries them too (its "leave out own sounds" box honoured): `spike3_modes.stage_try_it_sounds`
  stages each container as a PATCH - the card's file cut at its old directory, a tail (bodies, directory,
  trailer) and a new 0x80-byte header - in the mode files' `games.patch/` (4 MB for ELG, not 1 GB), and s3run.sh
  builds the file in the rig slot's /games overlay from the store's copy (`games.patched` takes it away at the
  next run's start). Code modes stay Spike 2's.
- mode_file.c's "NOT played - the game's own speech held the voice bus" now names what held it (request,
  priority, bus). A call waits for the voice bus (start and end 1.5 s, shot 0.8 s) and is dropped when the
  game's own higher-priority sound outlasts that, as on Spike 2: a shot call was held by the mode's own 3.5 s
  start call; on ELG the end call is held when the game's 13 s line 478 (priority 7) still plays at time-up.

Proof (2026-11-14, Spike 3 rig slot 96, hidden, MUTED, `PAD_S3_AUDIO_OUT=1` keeping the PCM): a SOUND CHECK
mode whose sounds are pure tones the game never makes - start 1500 Hz 3.5 s, shot 1000 Hz 1 s, end 2500 Hz
2 s, music 700 Hz 20 s stereo. Each run logged `[pad] sound swap: request N looked up <stock>, took <ours>` for
135 / 201 / 70 / 202 and the tones were found in the game's own output (end call 95% of it). Runs: a hand-built
image.bin (two; all four heard in the second), Try it's patch built by s3run (two; all four heard in the
second), and the card the real Write wrote (`spike3_write.write_card`, 890 s: the four records appended, the
container grown through dm-crypt, the mode installed) booted through its own hook: the runtime read the
card's port, the start call and the music were swapped in and heard, the end call was held by 478 (above).
Tests: tests/test_pad1296_spike3_own_sounds.py.

## Lamps and light shows on Spike 3 (PAD-1283)

The lamp layer (a mode's named inserts: `light_insert`, `light_all`, `light_shots`) and the game's own light shows
(`show_start` / `show_end` / `show_hit`, played as a process of the runtime's) read the game's structs with 4-byte
pointers. The Spike 3 engine has the same code with 8-byte ones, read in Star Wars ELG 1.10's own allocator, compositor
and process code:

| struct | Spike 2 | Spike 3 |
|---|---|---|
| lamp layer heads (`data lamp_layers`) | free list, active list: 4 bytes each | 8 bytes each (the active list at +8) |
| lamp group (48 of them) | slots +0, priority +4, owner event +16, next +20 | slots +0, priority +8, period +12, a callback +16, owner +24, next +32 |
| lamp slot | 40 bytes: light +0, level +2, alpha +3, fade +8, used +36 | the same 40 bytes (its callback and u64 time were already 8-aligned) |
| event / process record | next +0x84, show id +0x96, exit hooks {fn, arg} x4 at +0xd0 (8 bytes a hook) | 376 bytes: next +232, show id +258, exit hooks x4 at +0x138 (16 bytes a hook) |
| light count (`data light_count`) | u32 | u64 |

pad_mode_runtime.c reads every one of those pointers as `pm_addr` (the layer list, a group's slot array and next,
`event_current`, the show process record `proc_create` returns, the exit-hook slots strided by two pointers), and
passes the allocator its four arguments pointer-sized: the 64-bit allocator keeps the fourth as a callback at +16 that
its compositor calls when it is not 0, so a 32-bit 0 there (x3's upper half whatever it held) would be called. The
stock-rule calls (`show_start`, `event_post_replacing`, `event_cancel`, ...) hold their sites as `pm_addr` too, and
`pm_stock_display_event` takes its handler as an `unsigned long`. Spike 2's mode.so is byte-identical.

s3port.py reads it all off a Spike 3 program (`light_engine`): the lamp layer from the call `lamp_group` makes (the
heads, the group's priority / next / owner, the light count and the 40-byte slot from its memset), `lamp_free_owner`
(the function after the allocator that walks the groups by owner; nothing calls it directly, so the bodies are cut at
their nop padding), the process list, record and exit hooks from `proc_create` and the exit loop beside it, the show
flag and id from `show_priority`. The Spike 2 port's shows are carried by their record in the show table (`show_start`
reads it: Spike 2 137 records of 12 bytes, Spike 3 128 of 16; a show is carried when the same record holds the same
kind and flags), renumbered from 1 - ELG's show_5 and show_6 are records 130 and 134, past Spike 3's 128, so ELG
carries five (a mode asks for a show by name). Its `lamp` lines are carried by name: a lamp of Spike 3's device table
(its I/O group and index written from there) whose light ids one of the light table's records holds - every one of
ELG's 67 (the light ids are unchanged; MILLENNIUM FALCON (OPTIONAL) is not on the Spike 3 build). The `show_proc` id is
kept when no instruction of the program loads it.

Proof (2026-11-14, Spike 3 rig slot 1, hidden and MUTED, the bridge publishing dump/padled): a mode file's
`light_insert white blink 400 DEATH STAR (X2),LEFT OUTLANE,RAMP 6` blinked the three on the playfield board (padled
board 8, indices 51 / 3 / 64) from the mode's start to its end, LEFT OUTLANE and RAMP 6 dark before and after and
DEATH STAR (X2) back to the game's own 0.5 s blink; `light_all ff00ff solid` held all 67 inserts at 255 for its 12 s;
`light_shots cyan blink` blinked the three inserts tied to its scoring shots (LEFT LUKE ARROW at our 255 over the
game's own 192). The game's shows 1-5 each played as process 13201 at a mode's start or end, the long ones stopped at
their length through `event_cancel`; a layer watch (pm_lamp_layers twice a second) saw each show's own group appear and
go as it ended or was stopped, the game's list back to the same five every time. No run crashed. The Modes tab offers
the sweep, the shot lights and the game's shows on the Spike 3 card (`LAMPS_PROVEN` has `star_wars_elg-1.10/spike3`).
Tests: tests/test_pad1283_spike3_lights.py.

## Screens, words and clips on Spike 3 (PAD-1284)

A mode's own screen (a node the build grafts into the game's `hud` scene), its words (set_text on the screen's text
node) and its clip (the video bank's `VideoSurface`, clip v2) ran on Spike 2's 32-bit idioms. Star Wars ELG 1.10's
64-bit program has the same scene engine with these differences, read in its own code:

| what | Spike 2 | Spike 3 |
|---|---|---|
| std::string | the COW ABI: one pointer, made by the imported constructor (`site string_new`) | the C++11 ABI: 32 bytes {data, length, capacity}, no constructor imported (built inline) |
| a node finder's result (find_node, find_text, surface_find) | its shared_ptr into memory named by the first argument | through x8 (AAPCS64: not trivially copyable) |
| the scene lookup | resource_get(manager, &id, 0), __dynamic_cast 6IScene -> 11RadiumScene, the scene at +0x10 (its mutex +0x18) | the same (resource_get 0x217030, the manager at 0x712bf8 behind a logging wrapper), the scene at +0x38 (its mutex +0x48) |
| the node visibility setter | Sprite vtable slot 42 (`strb r1, [r0, #296]`), value 0xa8 | slot 42 (`strb w1, [x0, #464]`), 8 bytes a slot: 0x150 |
| the video surface | set_video / play / stop / state / seek / duration / position | the same calls (set_video 0x4dcc40, position 0x4d77d0, duration 0x4d7b50) and **no seek**: the player's clock is set by its own decoder thread only |

- **The runtime** (pad_mode_runtime.c): a `pm_str` is the COW word on Spike 2 (`&s` passed, as it always was) and on
  Spike 3 the address of a C++11 string `std_string` builds (the words in a malloc'd copy, capacity = length, leaked
  as Spike 2's are); every game call that takes one takes `const std::string &` and copies it (resource_get, the
  finders, set_text, surface_set_video). The finders are called through `find_x8`, typed to return a struct of more
  than 16 bytes so C passes x8; `pm_show` indexes the vtable by pointer size; the screen / clip gates name
  `resource_get` where Spike 2's name `string_new` (`PM_STRING_SITE`). The co-op intro's finder hook reads (root,
  name) in x0/x1 on 64-bit. Spike 2's mode.so is byte-identical.
- **s3port.py** `scene_engine` reads it all off a 64-bit program: the `__dynamic_cast` PLT stub; the two typeinfos by
  the Spike 2 port's names; the game's own scene lookups (casts from the resource typeinfo to the scene player's), the
  wrapper called before them and in it the first call on a manager loaded from a global (resource_get, checked by its
  `cmp w2, #2` mode switch); the scene field read under the player's mutex after a cast; the Sprite vtable's
  setter / getter pair at Spike 2's slot; the surface's set_video (the call before surface_play that tests the same
  "set up" byte as the surface's other methods), position and duration (the game's progress read: two such calls,
  then surface_state and `cmp w0, #2`, which is surface_playing); the hud and video_bank scene ids when the program
  names them. The matcher's find_node / find_text / set_text / surface_* placements are carried with them. A site
  no feature uses on the Spike 2 port of the same build either says so (Star Wars ELG: award_screen and display
  priority lack their values there, display_draw / player_advance belong to the clip_play path it does not use).
- **The scenes**: the Spike 3 card's video bank is the Spike 2 build's file (895f74e5...); its HUD differs from the
  Spike 2 build's in 3 bytes of one texture block (0x7eaf7), so `scene_write.PROFILES` carries it (be374b87...) with
  the Spike 2 profile's shape, and `TITLE_SCENES["star_wars_elg-1.10/spike3"]` names both.
- **The Write**: a mode's clip is the first file a Spike 3 Write puts on the card new, and a file the `.sidx` manifest
  does not list fails Stern's SD validation; `spike3_write._sidx_new_files` appends its record
  (`mode_write.compose_manifest`, as Spike 2's mode Write does) and the manifest goes on whole with the other files.
- **Try it**: `spike3_modes.stage_try_it_scenes` stages the rewritten scenes and the new files whole in
  `games.patch` (`<path>|whole|<file>|`), which s3run.sh puts in the slot's /games for the run and takes away at
  the next run's start, like the sound patches.

Proof (2026-11-14, Spike 3 rig slot 84, hidden and MUTED): a mode SCREEN TEST (three Death Star target hits, 40 s, a
generated magenta screen with its words, a 6 s title clip at its start). Try it on the library card (this build's
prebuilt mode64.so and port, the three files staged whole): the runtime armed `screens clips`, found the screen and
its text node in the HUD, played the clip ("still drawing 1 s after it started") and hid the screen after the end;
in the frames the clip filled 44% of the glass in magenta, then the screen 18% (its words under it), off where the
game's own multiball video covers the HUD. The card `write_card` wrote (the HUD and bank grown, the clip's asset
added, the mode installed), started through its own hook: the same log and the same frames (6 clip, 16 screen).
The same mode with the previous runtime and port: `can callout own-sound game-shows`, "own screen not found", no
magenta in any frame. Tests: tests/test_pad1284_spike3_screens.py.

## Multiball, held coils and blocks on Spike 3 (PAD-1285)

The sites a mode's own multiball, a held coil and a block of the game's modes use were placed by s3port.py's matcher
but written as comments: their features read the game's structs with 4-byte pointers. Read in Star Wars ELG 1.10's own
code:

| what | Spike 2 | Spike 3 |
|---|---|---|
| balls_in_play, multiball_serve, proc_sleep, adjustment, coil_fire | plain calls; the serve's and coil_fire's last two arguments on the stack | the same calls, every argument in w0-w5; the game's own one-ball saves pass (1, 0, 312, 0xbb) as on Spike 2 |
| the coil records (coil_fire's writer) | 0x68 bytes: request id +0x14, link +0x10, state +0x22, board +0x24, coil +0x1a, powers +0x29..+0x30 | the same record; the table's pointer (0x749300) and its count (a u64, 0x73e1d8) 8 bytes |
| a device object (the right control gate, a static built by 0x184030(obj, 9, 0, 186)) | device u16 +4, exit hook +28, controlling process +32; update vtable slot 28, "disabled" slot 30 | device +8, exit hook +36, controlling process +40; the same slots, 8 bytes each: slot 30 = adjustment(obj+12) == 1 |
| coil_take / coil_give | 0x7aa14 / 0x7aad8 | 0x184180 / 0x1842d0 (the same code; two other device families have a pair of this shape: the gate's constructor names its own) |
| the game's mode starts (block_start_*) | Inner Loop 0x6bcc0 (flag 86), Orbits 0x6ad3c (88), Ramps 0x5eff0 (87) | 0x17a820, 0x1798b0, 0x173430: the same flags, set through 0x316940 |
| the game flags | the bitmap pointer at holder + 4 | the global is the pointer (`value game_flags_at 0`); count 102 at 0x5a37c8 |

- **The runtime** (pad_mode_runtime.c): a held coil's object and record are `pm_addr`, a vtable is indexed by pointer
  size, the coil table's pointer read pointer-sized; take / give are typed (pm_addr, unsigned). The block keeps the
  starts' addresses (`block_hooked`, `place_from`, `block_obj`) as `pm_addr` - the 32-bit `unsigned` cut a PIE's
  address. Spike 2's code is unchanged by these (the struct keeps its layout there).
- **A mode's own multiball read as the game's** (Spike 2 too): the count route (`balls_in_play`, titles with no mode
  table) sees only balls, so three seconds after our serve it said "a multiball is running" and the mode that asked
  for it ended - "the game's own mode began" - since block / give-way became the default (PAD-398). The runtime now
  remembers the serve (`ours_mb_at`) and answers no multiball of the game's until the balls are back to one
  (OURS_MB_GRACE_MS after the serve). PAD-420's Spike 2 notes "our own multiball stopped with its three balls in play"
  were this.
- **Not on Spike 3**: `switch_edge` - the 64-bit drain has no per-switch edge call, it calls switch_hit / switch_hit2
  itself by the switch's handler bits, and the shots come through those sites; the every-edge features (attract
  flipper sounds, game mode shot sounds, co-op) ride Spike 2's delivery. `ball_end` - the end of a ball is the bus's
  event 0x34 through hook_dispatch (Spike 2's site is that event's handler). `player_advance` - the clip_play path,
  not this title's.
- **s3port.py** `play_engine` reads it all off a 64-bit program: carries the matcher's five plain calls, the coil
  records off coil_fire's writer (`coil_records`), every take / give pair (`coil_control`), a held coil's object by
  its constructor's call with its device id and the vtable slot that asks the adjustment getter (`device_object`),
  the flag set (`flag_set`) and each Spike 2 block start by the game flag it sets (`mode_starts`).
- **The Modes tab** offers on the Spike 3 card: Multiball, "Hold the Right control gate", the game's three modes a
  mode keeps from starting, and "waits while the game's modes run" (MULTIBALL_PROVEN, HELD_COILS_PROVEN,
  STACK_BALLS_PROVEN, STACK_FLAGS_PROVEN). Ball save stays greyed: on this rig the game's trough-eject retry at a
  game's start is served as another ball, so balls stay in play and no drain ends a ball, with or without a save.

Proof (2026-11-14, Spike 3 rig slots 85-87, hidden and MUTED, this build's prebuilt mode64.so and the drafted port;
ELG's first-boot GAME SETUP screen takes a held Start). Three Death Star hits start ELG's own multiball, so the
modes start on Top lane center:
- a mode file's `multiball 3 10`: served through the game's serve (balls_in_play 3), ran its 40 s, drains 3-2-1,
  "multiball: ours is over" at one ball; meanwhile the game's Orbits start was refused ("block: the game's mode 1
  (Orbits) did not start"). Before the fix the same mode ended 3 s in.
- `coil_hold right_gate 2000` and `... 1500 <shots>`: node 8 coil 2 = the game's device 9, its object taken, ONE
  command each on the bus (`n8 40 02 ff 06 00 80 c1 00`: 255 for ~60 ms, then 128 for 1.93 s; `.. 8f 00` for a
  1.5 s hold), given back at its time or 483 ms early as the mode ended; refused while the game's own 20 s commands
  (`d0 07`) held the gate; no abort. A mode started on Death Star gave way to the game's multiball 3 s in (correct).
- `stack no` on Top lane center in the game's Death Star multiball: "not started: a multiball is running" twice,
  then started after two drains. A probe mode (block_probe_mode.c) called the game's Ramps start as its rules do:
  while a mode blocked, "the game's mode 2 (Ramps) did not start" and flag 87 stayed clear; with none, the start ran,
  set flag 87, and a `stack no` mode was refused for it 21 times.
- Spike 2 (Star Wars ELG 1.10's Spike 2 card, rigbatch, 4x, hidden, muted, s2 job: the same `multiball 3 10` mode
  started by its trigger file): main's mode.so ended it 3.08 s in ("the game's own mode began"); this build's was
  still running 20 s after its multiball.
Tests: tests/test_pad1285_spike3_play.py.
