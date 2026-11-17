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

1. `spike3_modes.plan` - the preview switch, code modes (PAD-1295: compiled for the card's
   64-bit ARM, below), `card_refusal` (no port / no Insider gate), a multi-boot card, then
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
| **score feed** | scorefeed.cfg | **goes on (files alone)** | tick, hook_dispatch, game_start / ball_start / game_over, u64 scores: all live, and the Insider logins since PAD-1326 (`coop_play.insider_users_a64`; the runtime reads the tables pointer-sized, the manager moved by the PIE's load address) |
| random clips | clips.cfg, clips in the video bank | **goes on (PAD-1323)** | done: the clip v2 route asks for no `string_new` (the runtime builds the name), the name read as an 8-byte pointer, surfaces compared at full width. A port with the clip v2 lines: Star Wars ELG's today |
| screen times | `stime` lines in clips.cfg | **goes on (PAD-1323)** | done: the slot read and written as 8 bytes, moved by the PIE's load address; screen_time.py reads 64-bit programs (Fallout LE, Pokemon LE, Transformers LE have the screens) |
| music modes | sounds.cfg, bank records, MUSIC MODE row | **goes on (PAD-1324)** | done: the files appended to image.bin (a music-bank song's to its own bank, PAD-1358), the record key swapped at the lookup while the setting says the mode (`mswap`), MUSIC MODE on Audio Content (found by name) in game.pad, which the hook runs; Star Wars ELG 1.10, Fallout LE 0.82 and Transformers LE 0.96 (PAD-1359) (below) |
| editions | EDITION row, codeselect's `edition=` | **goes on (PAD-1325)** | done: `spike3_menu` grows the 64-bit program's menu (Attract Mode, found by its name); `mks3multi --editions`; nvm.c reads the Spike 3 store (tools/spike3_emu/MULTIBOOT.md). ELG 1.10, Fallout 0.81/0.82, Transformers 0.96 take it |
| picture settings | picture.cfg, 3 menu rows | left out | 8-byte GOT writes in a PIE; menu rows; switched off for every card anyway (OFFERED False) |
| co-op play | coop.cfg, CO-OP PLAY row, HUD screens, clips | left out | the player sites, a 64-bit message table, the menu row (the switch edges are there since PAD-1322) |
| handicaps | handicap.cfg, HANDICAP row | left out | `coop_player`, the menu row; handicap.py reads 32-bit code (the flipper edges are there since PAD-1322) |
| Prolonged Competition | comp.cfg | **goes on (PAD-1327)** on every Spike 3 title with a port | done there: the 64-bit `hook_full`, the menu's sites in its Spike 3 port, an 8-byte entry name, comp.cfg read off 64-bit programs. The newer titles' menus are of game-mode indices (Spike 2's Godzilla shape): their round is next |
| records on the high scores | records.cfg | **goes on (PAD-1327)** on every Spike 3 title with a port | points records (the whole game or a mode of the owner's); the champion in attract on ELG and WDR (round 5); counts wait on 64-bit readers |
| attract items | attract.cfg, clips | **goes on (PAD-1371) on Star Wars ELG 1.10** | tables read (PAD-1328) on five titles; the item's page shows the bank's scene as the game's own clip pages do. The 'stall' was the runtime's 32-bit hold of the scene show's address (below). Walking Dead Remastered, Star Wars 2025 LE / Pro and Pokemon wait on a clip route (their ports' video_bank scene is not named: `attract_items.title_refusal` says NO_CLIPS); Pokemon has no show pair either |
| inactivity pausing | idle.cfg | **no Spike 3 game needs it (PAD-1328)** | census of the 64-bit adjustment tables: Fallout LE (176), Star Wars 2025 LE (182) and Transformers LE (174) read AD_INACTIVE_TIMER once, in an `adjustment(id) == 1` check before their timer test; ELG, Pokemon, WDR and Star Wars 2025 Pro have no such setting. `idle_pause.title_refusal` says which (NO_NEED / NO_SETTING) |
| expression light shows | cabshow.cfg | left out | `cablamp` lines (ELG has no cabinet lights), the game's show table as 64-bit, voice count measured |

The operator-menu rows (MUSIC MODE, EDITION, CO-OP PLAY, HANDICAP, the picture rows) all wait on
one piece: adjustments.py / menu_settings.py writing a 64-bit program. Co-op, handicaps and the
attract / shot sounds of music modes waited on a 64-bit switch-edge source too: PAD-1322 (below) is it. So
the order the rest lands in: the 64-bit menu rows; random clips with screen times; music
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

## Random clips and screen times on Spike 3 (PAD-1323)

Both go on now, beside the runtime as on Spike 2 (`clips.cfg`), built by `spike3_modes.plan` like the score
feed: `variants_wanted` (quiet: the engine's `_variants_for_build` has said why not) puts the project's clips in
the title's video bank, read off the card's games volume, and `screen_times_wanted` reads the card's own 64-bit
program for the screens that show a replaced clip for a fixed time (the engine's `_screen_times_from`, so the
log says the same lines; on Spike 3 the engine leaves them to this build). A multi-boot card takes none, said.

- **The runtime.** `clipv_arm`'s clip v2 route asks for `PM_STRING_SITE` (resource_get on 64-bit: the program
  imports no string constructor and `std_string` builds the C++11 object), `on_clipv_set_video` /
  `on_clipv_layer` read the name's first word as a `pm_addr` (the COW string on Spike 2, `_M_p` on Spike 3) and
  compare the surface as a `pm_reg`, `on_clipv_play` hands the name back in the whole register. A `stime` line's
  vtable, slot and word are link-time addresses: each is moved by `game_base` (0 on Spike 2), the slot is a
  `pm_addr` (8 bytes, 8-aligned on Spike 3) and gets `stime_get`'s whole address.
- **The clip route.** `clip_variants.hook_route` needs `resource_get` in place of `string_new` on a Spike 3 port
  (`mode_runtime.port_arch`), so Star Wars ELG's offers random clips on the Video tab (671 of its 932 clips; the
  rest are not played by name). The drafted Spike 3 ports carry no clip v2 lines yet: their titles say so.
- **The screens, 64-bit** (`screen_time.screens_a64`). Godzilla's screen framework is on Fallout LE 0.82 (25
  screens, 14 that end on their time), Pokemon LE 0.82 (12, 5) and Transformers LE (5, 1); the Star Wars titles
  and Walking Dead have none. Read the same way as the 32-bit one, AArch64 encodings: string getters `adrp x0 /
  add x0, x0 / ret`, float getters `fmov s0, #imm / ret` (or a word moved in), the length field from the
  whole-function done checks `ldp s0, s1, [x0, #f] / fcmpe s1, s0 / cset w0, gt / ret` (Fallout +0xe0, Pokemon
  +0xc8: Pokemon has more unrelated float compares than screens), the time slot from the start code that loads it
  (`ldr x1, [x2, #0xe0]` = slot 28 on Fallout, 26 on Pokemon), compares it with the base's own getter and stores
  `s0` there. Vtables are R_AARCH64_RELATIVE relocations (the file's words are 0). Fallout names clip / crop /
  loop flag in slots 17 / 18 / 19; Pokemon has no crop, so its loop flag is the slot after the clip.
- **The Video tab** reads a Spike 3 card's program (`title_reader.spike3_game_program`) for the screen-time tag,
  and its other-bank check opens the card's encrypted games volume.

Tests: tests/test_pad1323_spike3_clips_stime.py (a synthetic 64-bit program; the real Fallout / Pokemon programs
with PAD_S3_PROGRAMS).

## Prolonged Competition on Spike 3 (PAD-1327)

Round 1 of "Prolonged Competition with records". Goes on a Star Wars ELG 1.10 Spike 3 card; the five newer Spike 3
titles (Fallout, Pokemon, Star Wars 2025 LE/Pro, Walking Dead Remastered, Transformers) say "The app does not know
<title>'s start menu yet" as before.

- **hook_full on 64-bit** (hook_a64.h): PAD-1322's callee step with ONE array by register number - a[0..8] = x0..x8,
  a[19..28] = x19..x28, a[30] = x30, a[31] = the hooked function's sp - every one but the sp written back. FULL_SP /
  FULL_REG_LAST name the layout on both machines (32-bit: regs + 14, r12), HOOK_SP a plain hook's caller sp.
- **Star Wars ELG 1.10's Spike 3 menu** (function 0x158bb0, reached through a pointer): entries {u32 kind, u16
  caption, u64 name} 16 bytes each at sp+0xf8, room for 7; the count in w22 until 0x159a10 (`sub w1, w22, #1`) keeps
  the LAST index at sp+164 for the loop - `site challenge_menu` there, once per menu, hook_full, `value
  challenge_menu_count_reg 22`. Every frame 0x159c34 loads the kind under the cursor into w1 and the kind's flags
  follow (0 Standard clears 17-20, 1 COMPETITION sets 17, a kind past 6 clears them as Standard does) - `site
  challenge_menu_pick` at 0x159c38, `value challenge_menu_pick_reg 1` (r3 on every Spike 2 port, the default).
  The captions are Spike 2's ids (1914 STANDARD, 1919 COMPETITION, 1921 CHALLENGE, ...).
- **The runtime's menu code** writes and compares the entry's name as a pm_addr (8 bytes, 8-aligned on Spike 3) and
  copies Standard's "fourth word" only on 32-bit (on Spike 3 it is the name's high half).
- **comp.cfg off a 64-bit program**: `prolonged_comp.card_lines` reads the FG_ name table (8-byte entries from
  FG_INVALID) and the message table (one relocated pointer per id to a record whose first pointer is the English
  text, from CHOOSE YOUR MODE OF PLAY's record). All seven Spike 3 programs read: ELG 17 / 1919 / 1914, Fallout and
  Transformers 17 / 1920 / 1915, Pokemon and SW 2025 LE 16 / 1913 / 1911, SW 2025 Pro 16 / 1909 / 1907, WDR 17 /
  1918 / 1913.
- **The build**: `spike3_modes.comp_wanted` (quiet; the engine's `_comp_for_build` says why one is left out) hands
  comp.cfg to `mode_write.plan` with the rest, or alone (`only`). The Play options tab offers the tick on ELG's
  Spike 3 project (its port is `port_ready`).
- **How the menu is worked on this build** (read off its button reader 0x275cc0): both flipper buttons open it; it
  stays while the attract timer (operator setting 92, sped up 15x while one flipper is held without the other) or
  the start-pending timer (9 s, reset by each press) runs; both buttons down with a fresh press answers 0xc0 (leave,
  with the cancel sound), so letting go of both at once closes it. A rig job holds both, lets go of the right one a
  second before the left, then steps with the right one.

Proof (2026-11-16, Spike 3 rig slot 132, hidden and MUTED, the library card, the set `spike3_modes.plan` built from
it: mode64.so, game.port, comp.cfg `flag 17 / caption 1919 / caption_end 1914 / only`): `prolonged competition:
armed - on the start menu at ...9a10`; the menu opened as `entry 3 of 3 (UNTIL POWERED OFF) - kinds 0 6 512`
(this fresh card's menu is STANDARD and DJ MIXER), the right flipper stepped Standard -> DJ Mixer -> ours (`UNTIL
POWERED OFF picked on the menu`), Start: `ON until the machine is switched off - game 1 plays as Competition (flag 17
was 0)`; at its end `flag 17 is 1; prolonged on`; game 2 from a plain Start `plays as Competition`, at its end flag 17 still 1; the menu again showed the entry as
STANDARD / ENDS PROLONGED COMPETITION (`ENDS PROLONGED COMPETITION picked on the menu`), Start: `OFF - game 3 plays
as the menu picked (flag 17 was 0)`.
Tests: tests/test_pad1327_spike3_prolonged_comp.py (the menu append and the 64-bit hook_full lifted and run at
Spike 3's word size; the real programs with PAD_S3_PROGRAMS).

**Round 2 (Fallout LE, the index menus).** `comp_menu_frame` takes the Spike 3 index menus: hooked just after the
frame's press moved the cursor (`value comp_menu_frame_moved 1`, so no buttons are read), the list and count in the
frame or in a register (`comp_menu_frame_list_reg` / `_count_reg`, hook_full's numbers), and a loop's copy of the
last index kept in step (`comp_menu_frame_last_at`, Pokemon's sp+140). Lettering UNTIL POWERED OFF needs the 64-bit
message table: a u64 count (`data message_count`), a pointer variable to the u16 remap (`data message_remap`, as on
Spike 2) and a table of 8-byte record pointers (`data message_table`; a record is a 0-ended list of per-language
strings, as Spike 2's). `message_slot` steps it by pointer size and makes a 64-bit table page writable.

| title | frame point | list | count | cursor | room | Competition (name msg) | Standard (name msg) |
|---|---|---|---|---|---|---|---|
| Fallout LE 0.82 | 0x485a08 `ldr w23, [x26, w20, sxtw #2]` | sp+0x1b8 (x26) | w22 | w20 | 12 | 2 (1921) | 1 (1916) |
| Pokemon LE 0.82 | 0x4cc050 `ldr w24, [x0, w21, sxtw #2]` | sp+0xd8 | sp+136, last index sp+140 | w21 | 12 | 6 (1914) | 1 (1912) |
| Star Wars 2025 LE 0.96 | 0x27e788 `ldr w22, [x24, w20, sxtw #2]` | sp+0x1c0 (x24) | w23 | w20 | 10 | 2 (1914) | 1 (1912) |
| Star Wars 2025 Pro 0.84 | 0x1d1f1c `ldr w21, [x0, w22, sxtw #2]` | sp+0x168 | sp+156 | w22 | 4 | 2 (1910) | 1 (1908) |

Walking Dead Remastered LE 0.92 has Star Wars ELG's shape instead: entries {kind, caption, name} 16 bytes at sp+0x128
(room for 8), the count in w22 until 0x1ef564, the kind under the cursor in w0 at 0x1ef5f0 (its kind 2 sets flag 17).
Star Wars 2025 Pro's bus ids are one lower than LE's from 57 on (read off the calls into its dispatch): game_start 0x4c,
ball_start 0x25.

**The freeze at Fallout's first game start, and its cause.** With Prolonged Competition armed Fallout stopped with
DISPATCH TIMEOUT about 10 s after its game_start event, even with a frame logger that did nothing; stock and score-feed
runs played on. The ports s3port drafted from Star Wars ELG's (Fallout, Pokemon, Star Wars 2025 LE / Pro, Walking Dead
Remastered, Transformers) had lost `value game_flags_at 0`: GAME_VALUE took it for the reference game's own content,
so the runtime read the flag bitmap's pointer at Spike 2's +4 when comp_game_start read flag 17. Every Spike 3 port
carries it now, the 64-bit runtime's default is 0 (`GAME_FLAGS_AT`), and s3port keeps it from a Spike 3 reference (and
leaves a start menu's numbers, `challenge_menu_*` / `comp_menu_*`, as the reference title's own).

Proof (2026-11-16, Spike 3 rig slot 132, hidden and MUTED, alone on the machine, the set spike3_modes.plan built from
the library card): `on the start menu as entry 9 of 9 (game-mode index 2, UNTIL POWERED OFF; cursor 0)`, the game's own
menu showing COMPETITION / UNTIL POWERED OFF on our entry, `UNTIL POWERED OFF picked on the menu`, Start: `ON until
the machine is switched off - game 1 plays as Competition (flag 17 was 1)` (the game made it a Competition game from
our duplicated index), the game playing on (ball 1, scoring) where it had frozen. (The rig's drains did not end
Fallout's ball 1, so the off cycle is ELG's proof and the host test of the index-menu code.)

**Round 3: every Spike 3 title with a port.** The "start menu did not open" finding of round 2 was the rig's: the newer
titles name their flipper buttons LEFT / RIGHT FLIPPER BUTTON, and the proof script pressed L / R FLIPPER BUTTON, which
s3press refused (`no switch named`), so the chord never reached Pokemon, Star Wars 2025 LE or Walking Dead Remastered.
The titles' proof files (`tools/spike3_emu/proofs/titles/*.env`) now name them (FLIP_SWS, which PROOF=edge uses too).
With the right buttons every title's start menu opened in attract on fresh settings. Transformers LE (its port came
from main) has Fallout's index shape: frame point 0x2809d0 `ldr w23, [x27, w20, sxtw #2]`, list sp+0x1d0 (room for
12), count w22, cursor w20, Competition index 3 (name 1921), Standard 1 (1916).

Proof (2026-11-16, Spike 3 rig slots 132 / 134, hidden and MUTED, each title's set built by spike3_modes.plan from its
library card): each logged `on the start menu as entry N of N`, showed COMPETITION / UNTIL POWERED OFF in the game's own
menu, `UNTIL POWERED OFF picked on the menu`, and at Start `ON until the machine is switched off - game 1 plays as
Competition` - Pokemon LE (entry 3 of 3, index 6, flag 16), Star Wars 2025 LE (8 of 8, flag 16), Walking Dead
Remastered LE (3 of 3 on ELG's route, flag 17), Transformers LE (6 of 6, index 3, flag 17) and Star Wars 2025 Pro (3 of
3, flag 16; its game_start 0x4c seen on the bus). Pro's cursor goes from the first entry straight to the last on the LEFT
flipper and its menu window is short: a rig job steps left at once after the chord.

**Round 4: records on the high scores.** The champion framework has the same shapes on all seven Spike 3 programs, its
words the size of a pointer: a category table object {base, count, stride 72} (the lookup is `base + id * stride`),
each 72-byte category's value getter at +8 and its entry-id list at +56; 64-byte entries (record +0, default initials
+8, name +40, titles +48, the award u16 +56); 96-byte records with the initials at +32, the score a u64 (at +80 on Star
Wars ELG, +72 on the others) and the check ~(the byte sum of the first 88) at +88; the end-of-game high scores take no
arguments of their own; before filing a player the game asks the bus question 91 (90 on Star Wars 2025 Pro) with
{player +0, category +2, entry +4} - Spike 2's gate. HIGHEST SCORES is category 1 (GRAND CHAMPION, HIGH SCORE #1-#4).
The runtime's champion code reads categories and entries as pm_addr words (`CHG_DESC_SIZE`, `CHG_ENT_SIZE`,
`CHG_ENT_AWARD`), the wrapped end-of-game functions and the gate pass whole registers (`chg_fn4`), and co-op's champion
counts read the getter through `rec_cat_value`. The attract mode's champion pages are not armed on Spike 3 (their page
and text wraps are 32-bit): a record's champion shows in the game's initials entry and is kept, not yet in attract.
`tools/.../champ_find.py`-style reading (C:/tmp/PAD-1327/champ_find.py: ELG's two functions paired across by s3port's
matcher, then the table objects, the record reset and the gate read off each program) gave every port's lines.
`spike3_modes.records_wanted` carries records.cfg; `mode_records.choices` offers a 64-bit program no counts or game
modes yet, so a Spike 3 record counts points, in the whole game or in a mode of the owner's.

Proof (2026-11-16, rig slots 132 / 134, hidden and MUTED, each title's set built by spike3_modes.plan from its card with
one record, BIG SCORE: points in the whole game): `records: BIG SCORE - <score> beats 0: the game's initials entry under
its name`, the game's own "Player 1 - Enter Initials / BIG SCORE" screen, and `BIG SCORE's new record ...` kept in
/dump/pad_challenge_scores - Star Wars ELG (194530), Walking Dead Remastered LE (201190), Pokemon LE (540), Transformers LE (245220), Star Wars 2025 LE (24464360) and Pro (13962240), Fallout LE (8311590). Rig notes: a
title's own shot switches (its titles/*.env SHOT_SWS) must be hit after the plunge, or the ball save never starts and every
drain is served back (Star Wars 2025); Pokemon's frame dumps stop late in a game while the game runs on.

**Round 5: a record's champion in the attract mode.** PAD-663's champion pages run on Spike 3: the page wraps take and
pass x0-x7 and read the entry at pointer width (PAD-660's single page, its text and yield wraps 32-bit, stays Spike 2's).
Each title's attract champion screen was traced on the rig (a scratch runtime logging the entry lookup's and the ask's
callers in attract), with three shapes:
- **a page per champion** (Star Wars ELG: 0x13cee0 asks, looks up and reads the titles at +48; Walking Dead Remastered
  LE: 0x1b7880, every category): named `challenge_pages_0` (ELG also `_1`, 0x16c2a0); the record shows after the Grand
  Champion's page under its own title. Proven: ELG "BIG SCORE / AAAAAAA / 194,530", WDR "BIG SCORE / AAA / 202,550"
  between GRAND CHAMPION and HIGH SCORE #1.
- **one list page** (Star Wars 2025 LE 0x2253f0, Pro 0x199210: all five HIGHEST SCORES rows, their labels the scene's
  own): run again with the record in the first row it read as GRAND CHAMPION (rig-seen), so no page is named; the page
  is a comment in the port.
- **scene screens through binding thunks** (Fallout LE, Pokemon LE, Transformers LE: the champion screens ask each
  category through small thunks, e.g. Transformers' 0x24d350 .. 0x24d3f0): no page function to run again.
For the last two kinds the records dialog adds `mode_records.NO_ATTRACT` ("the attract mode does not show these records
yet: a player who beats one still enters their initials for it, and it is kept"): `attract_note` whenever a title's port
names no champion page.

**PAD-1327 round 6: counts on Spike 3 records.** A record can count shots and goals on a Spike 3 card, as on Spike 2:
- `site audit_add` in all 7 Spike 3 ports: the callee handed the most distinct `movz w0, #id` + `movz w1, #1` pairs
  (`s3port.audit_add_a64`; Star Wars ELG 0x42d880 takes 132 ids, the next callee 12). The 64-bit hook relocates its
  opening `adrp` (ELG's `tst; b.eq`), so the records' `on_rec_audit` reads x0 / x1 as on Spike 2.
- The audits' names and ids: `mode_records.audit_ids_a64` - the AUD_ names' relocated pointer table (from
  "AUD_INVALID") and the record `{table, count, 48}` of 48-byte descriptors, the id the code passes the halfword at
  +0x22 (Spike 2: +0x12 of 28). It is not the name's place: ELG's AUD_LEFT_SLINGSHOT is 202 on both machines, its
  name the 216th on Spike 3.
- The game's own champion counts: `mode_records.champions_a64` - the port's `challenge_scores_table` (72-byte
  descriptors, getter +8, titles +48) up to `challenge_scores_count`, from category 2, the high-score, co-op and
  fastest-time boards left out (Fallout: 23, Star Wars 2025 LE: 33).
- `choices()` on a 64-bit program offers them (`count_choices(game_elf, port)`; audits only where the port names
  the audit add); the dialog's choice cache is version 3. Shot labels drop Fallout's `ID_` (AUD_SHOT_ID_LEFT_OUTLANE).
- Rig (Fallout LE 0.82, slot 3): records of the right slingshot audit (147), slingshot + radio tower (147 + 164) and
  the JUNK champion. 4 balls, each a radio tower hit and 5 slingshot presses: SLINGS 35, RADIO SLING 39 = 35 + the 4
  radio tower hits exactly, JUNK 0 (none earned); each filed with the game's initials entry. A control game with no
  slingshot presses: SLINGS 18 over 5 balls - the game's own slingshot audit rises about 3.6 a ball by itself, so the
  20 presses were all counted.
- Rig (Walking Dead Remastered LE 0.92, slot 4): a record of the game's own WALKERS KILLED champion count (category
  2, its 64-bit getter called per player): 3 balls on the walker targets gave 3, filed as WALKERS with the game's own
  "PLAYER 1 - ENTER INITIALS" screen.

**Left as it is:** the game's own modes in the dialog (`game:<id>`) stay Spike 2 only - their objects are read by
the 32-bit stock scanner; a Spike 3 record counts in the whole game or in a mode of the project's own. Possibly later:
a record's champion on the list-page and scene titles' attract screens (a different design: a row or a scene of our
own).

## A mode's own challenge on the start menu, on Spike 3 (PAD-1330)

PAD-619's "a challenge of its own" (a mode listed on CHOOSE YOUR MODE OF PLAY, picked, plays a one-ball challenge game) on
Star Wars ELG 1.10's Spike 3 card. ELG is a plain-challenge title (its own challenges come only from Insider Connected),
so `challenge_menu_slot -1`: nothing of the game's to stop, the ball's start hands the game to the mode.

What its Spike 3 program does, read off its own code (`star_wars_elg.game`, objdump):
- **the menu's kinds** at the pick 0x159c38: 1 sets flag 17 (COMPETITION), **2 clears 17, sets 18, clears 19-20** (the
  plain challenge game: `value challenge_menu_kind 2`), 3 sets 17 and 18, 4 sets 19; past 4 as Standard. CHALLENGE is
  message 1921 as on Spike 2; FG_PLAYER_CHALLENGE_MODE_ACTIVE is 18 (the FG_ names), the plunger flags 12 / 13.
- **the balls per game**: Spike 2's getter (0x345428: setting 80, the player's game mode's own at +62 of its record,
  Insider Connected's through 0x338fa0) is built into each of its callers. The balls of a player 0x4177c0 and of the
  current player 0x417880 are whole functions (`site challenge_balls` / `challenge_balls_2`, vetoed to 1 as on Spike
  2); the ball-number set 0x417950 (two ways), the last-ball test 0x417a40 and the ball's end 0x417b50 read it into a
  register and compare - `site challenge_balls_at_<k>` at the compare (or where both ways join: 0x417c4c, w20) with
  `value challenge_balls_at_<k>_reg` (hook_full's numbering), which the runtime sets to 1 in a mode's challenge game.
- **the extra-ball test** 0x304ba0 (the count byte, decremented) - Spike 2's shape; **the end of the ball** 0x322180
  (end(w0, w1): status bits 0x202, devices off, PAD-630's); **the launch button's handler** 0x31b9b0 (Spike 2's
  0x103b88 with its device read built in; 0x31b400 nearby fires only on flag 13 and clears 12 / 13 otherwise - not it).

Runtime: `challenge_menu_built` / `_picked` share Prolonged Competition's 64-bit menu code (menu_count_of, the name a
pm_addr, the kind from `challenge_menu_pick_reg`); `balls_at` / `balls_at_arm` (four hook_full loggers); the
`challenge_plain_<k>` wrappers pass whole registers. A second hook on the same 64-bit site stacks (moved_word re-aims
the first one's `b`), so the menu and pick sites carry both the challenges' and Prolonged Competition's hooks.

Proof (2026-11-16, Spike 3 rig slot 230, hidden and MUTED, the set `spike3_modes.plan` built from the library card with
one mode, PAD CHALLENGE, `challenge new`; C:/tmp/PAD-1330 plan_chg.py, job.sh, play*.sh): `challenge menu: 3 entries
(1 of the modes' own) - kinds 0 6 256`, the right flipper to it (`PAD CHALLENGE on the menu - picked`), Start: `challenge
16 (PAD CHALLENGE) picked on the start menu: its mode starts as the ball starts`, `challenge ball: launched for the
player (its start clip over, 2014 ms after its mode began)` (the bridge: auto plunger), at its clock's end `the ball
ends now ... (0x...2180)` from the game's bus call; the dead ball drained: `an extra ball earned in it is not played`,
`one ball (the balls-per-game getter says 1)`, `PAD CHALLENGE's own high score ... for the game's end`, GAME OVER (no
ball served), the game's own "Player 1 - Enter Initials / PAD CHALLENGE" screen, `new high score 10011010` and the
attract mode's champion page showing it. Control: the same game with the port's balls sites taken out served BALL 2
after the drain. Rig notes: hitting DEATH STAR TARGET in a proof starts the game's own Death Star multiball (three balls:
the challenge ball then needs three drains); a drain while the mode runs is served back by the game until the mode's end
ends the ball (four drains in 28 s on a 40 s mode); the first-boot setup screen comes and goes - open the menu and
retry; finish the initials with END (left flipper from A) or the next Start presses add players.
Tests: tests/test_pad1330_spike3_challenges.py (the menu and the balls compare lifted and run at Spike 3's word size;
the real program with PAD_S3_PROGRAMS).

## The six other Spike 3 titles' challenges (PAD-1369)

A mode's own challenge on the start menu of Walking Dead Remastered LE 0.92, Fallout LE 0.82, Pokemon LE 0.82, Star Wars
2025 LE 0.96 / Pro 0.84 and Transformers LE 0.96 (Spike 3), as PAD-1330 did on Star Wars ELG.

**The challenge game's sites, every title.** ELG's PAD-1330 sites were paired across by s3port's matcher (ELG as the
reference, 64-bit to 64-bit) and each read off the target's own code by shape (C:/tmp/PAD-1369 sites.py): the balls of a
player and of the current player (whole functions), the ball-number set's two compares, the last-ball test's join and the
ball's end's join (`challenge_balls_at_0..3`, registers 19 19 19 20 on all six: the same code, setting 79 on WDR and
Pro's, 80 on the rest); the extra-ball test is the ball's end's first call after its 0x90 (Pro: 0x8f) bus question. The
matcher's pairs needed help in three places: it paired the ball-number set and the last-ball test to one function (the
next function is the test), on Star Wars 2025 Pro it paired the ball-number set onto the second balls function, and on
Fallout, Pokemon, Pro and Transformers its "end of the ball" was not it: the function that ORs 0x202 into the status
bits opens with an `adrp` and no prologue, so the scanner ran it into the function before (Fallout 0x935490, Pokemon
0x6d48c0, Pro 0x33ea50, Transformers 0x459c80 - each ~0x58e0 past the launch handler, as on ELG). Every site is the
program's own words, the extra-ball test ends `sub w1, w1, #1; strb; ret`, the launch handler reads flag 13 and fires
with 8 (tests/test_pad1369_spike3_challenges.py, with PAD_S3_PROGRAMS).

| title | challenge flag | menu | the end of the ball | launch |
|---|---|---|---|---|
| Walking Dead Remastered LE 0.92 | 18 | ELG's: kind 3 sets 18 alone (0x1f01e0), CHALLENGE 1920 | 0x36e4f0 | 0x369010 |
| Fallout LE 0.82 | 18 | index, CHALLENGE 1922, STANDARD 1915 / NORMAL PLAY 1916 | 0x935490 | 0x92ffb0 |
| Pokemon LE 0.82 | 17 | index, CHALLENGE 1915, STANDARD 1911 / 1912 | 0x6d48c0 | 0x6cef90 |
| Star Wars 2025 LE 0.96 | 17 | index, CHALLENGE 1915, STANDARD 1911 / 1912 | 0x378a30 | 0x373550 |
| Star Wars 2025 Pro 0.84 | 17 | index, CHALLENGE 1911, STANDARD 1907 / 1908 | 0x33ea50 | 0x339570 |
| Transformers LE 0.96 | 18 | index, CHALLENGE 1922, STANDARD 1915 / 1916 | 0x459c80 | 0x4543a0 |

**The index menus' game-mode tables** (64-bit, C:/tmp/PAD-1369 gpm64.py): the adapter's accessors (`cmp w1, #last;
ubfiz x1, x1, #6; adrp; add`) give a table of 64-byte entries in .bss {index +0, flag u16 +4, caption +6, name +8, balls
u32 +12}, filled by one constructor (its stores emulated). Fallout has two challenges of its own (RED MENACE, PIPFALL:
flag 18, one ball), Star Wars 2025 LE two (ESCAPE BESPIN, NEVER TELL ME THE ODDS: flag 17), Pokemon a CHALLENGE MODE
entry with Venom's words (DEFEAT KNULL) that its menu does not list, Transformers four one-ball specials with no flag,
Pro only Standard and Competition. So Godzilla's "the game's own challenge index again" fits two of the five; the entry
is **Standard's index again** on all five instead: the menu draws it with Standard's caption and name messages, which
the runtime letters CHALLENGE (the game's own message, `challenge_menu_caption`) and the mode's name while the cursor is
on it, and the game plays a plain game that the ball's start makes the mode's one-ball challenge game
(`challenge_menu_sets_on`, `challenge_menu_slot -1`).

**The runtime** (`challenge_menu_frame`, PAD-686's): the list and count in the frame or in registers
(`challenge_menu_frame_list_reg` / `_count_reg`, hook_full's numbers), Pokemon's copy of the last index
(`_last_at`), and a `moved` site (`challenge_menu_frame_moved 1`: hooked at Prolonged Competition's point, after the
frame's press moved the cursor): the press is read off the cursor's change (`challenge_frame_press`), and a press away
from our entry while a mode is left to step to puts the cursor back and steps the mode instead
(`challenge_frame_moved`, lifted by the test). The name and caption messages come back as the cursor leaves. A plain
index menu is armed with a ball-start event and `challenge_menu_frame_name_msg` (`mode_project._plain_index_menu` for the
app's offer). The two hooks on the one frame point stack (PAD-1330's moved_word).

**The app**: the six are in CHALLENGE_MENU_PROVEN (WDR: the game's own 2 of room for 8) and CHALLENGE_MENU_FRAME_PROVEN
(the five), so the Mode page offers "A new challenge of its own on the game's start menu". `known_game_dir` now reads the
shipped `ports/spike3` folder too: a Spike 3-only card (Fallout LE, ...) is named by its Stern file name, as ELG's was,
not only once the app has opened it.

Proof (2026-11-17, Spike 3 rig slots 136 / 138, hidden and MUTED, each title's set built by spike3_modes.plan from its
library card with one mode, PAD CHALLENGE, `challenge new`; C:/tmp/PAD-1369 plan_chg.py, job.sh, play_chg.sh): on every
title the mode was picked on the game's own menu (WDR: `3 entries (1 of the modes' own) - kinds 0 2 256`; the index
titles: `MODE CHALLENGE appended (entry 9 of 9 / 3 of 3 / 8 of 8 / 3 of 3 / 6 of 6)` and `MODE CHALLENGE shows PAD
CHALLENGE`), Start: `picked on the start menu: its mode starts as the ball starts`, the ball launched for the player 2 s
in, the ball ended by the mode's clock (`the ball ends now ... 0x...`) or a drain with it, `an extra ball earned in it is
not played`, `the balls-per-game getter says 1`, GAME OVER after the one ball (the index titles' Standard plays 4), and
`PAD CHALLENGE's new high score` filed with the game's own initials entry. Fallout with two modes: the game's own menu
showed CHALLENGE / PAD CHALLENGE, one right press `MODE CHALLENGE shows PAD SECOND (2 of 2)` with the cursor kept (the
frame: CHALLENGE / PAD SECOND), and PAD SECOND played. Pokemon with Prolonged Competition beside it: both appended
(MODE CHALLENGE 3 of 3, UNTIL POWERED OFF 4 of 4), ours picked, Prolonged Competition stayed off, one ball. Control (Star
Wars 2025 Pro, the port's balls sites taken out): the same pick served balls 2, 3 and 4.
Rig notes: s3run needs root (`wsl -u root`; as the user the presses find no machine); Pro steps LEFT at once after the
chord (its window is short) - from STANDARD the left press wraps straight onto our entry.

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

## A port for a Spike 3-only title (PAD-1287)

Only Star Wars ELG has a Spike 2 build to pair against; every other Spike 3 title is drafted from ELG's proven
Spike 3 port instead (`s3port.py <ELG game> ports/spike3/star_wars_elg-1.10.port <target game> -o <port> --game G
--version V`, `draft_spike3`). Every Spike 3 program is the same 64-bit framework built with one compiler around a
game's rules, so on top of PAD-1271's pairing (vtable slots, strings, call graph) the paired functions are LINED UP
instruction by instruction (difflib on the instructions with their addresses and immediates masked):

- pairs: functions whose masked instructions are the same and found once on each title seed the pairing, and the
  n-th call of a paired function pairs its callee with the n-th call of its pair (switch_hit / switch_hit2, which
  nothing else pairs, come from ELG's switch drain this way). ~9,100-9,900 of ELG's 18,297 functions pair on each of
  the six Spike 3-only titles, and on each at least half of the pairs line up instruction for instruction.
- sites: a function the reference port names is placed when its pair is at least 75% alike; a place inside one at
  the lined-up instruction; a library call by its imported name.
- globals: the target global the lined-up instructions make, voted over every paired function that makes the
  reference's (the neighbouring event_head / event_current no longer tie).
- values: the engines' readers (sound_engine, lamp_layer, processes, show_event) re-read their layouts off the
  target's own code, and every value is also checked at the lined-up instructions of the placed sites and their
  callees; a constant the alignment disagrees with is replaced, and the checks are written at the port's end.
  Layouts do move: the process record's exit hooks are at 312 on ELG, 392 on Walking Dead Remastered, 408 on Star
  Wars 2025 Pro.
- bus ids: the constant passed in w0 to a direct call of hook_dispatch, at the lined-up instruction. Only those:
  the adjustment reader's and the sound calls' ids are ELG's less one on Walking Dead Remastered, its bus ids the
  same; Star Wars 2025 Pro's game over is 0x46 where the others' is 0x47 (game_start / ball_start have no direct
  call there and are left out).
- switches: `spike3_switches` - the target's own device table, the Spike 2 shot rule (portswitch.NOT_SHOTS), none of
  the service buttons' I/O group, one shot bit each by the switch's rank in the table. On ELG it gives exactly the
  30 its proven port names; `text example_start_shot` is the first target.
- left out, for each title's own port: the reference game's shows, lamp lines, callouts, scenes (so the screen and
  clip sites are placed but written as comments: they need the title's hud / video bank scenes), held coils, mode
  flags and blocks.

A fresh draft says `NOT RUN` in its header (the app then calls it unproven) until a run proves it. Self-check: ELG
drafted from itself gives back all 103 framework entries of its proven port, none different.

**Walking Dead Remastered LE 0.92** (`ports/spike3/walking_dead_remastered_le-0.92.port`, program sha1 bcf428e1...),
proven 2026-11-15 on the Spike 3 rig (slot 37, hidden, muted): the runtime took the draft whole (29 sites, 32
shots, the Insider gate, 6 events, both switch_hit sites); template_mode.c started on three Tower target hits,
scored 6 shots through score_add (+21M), ended on the bus's end of ball and, the second time, on its clock, the game
playing on to the cap; the SDK's sound instrument played, polled, stopped and faded requests on the game's own
channels and the callout site played one; a mode.cfg `multiball 3 10` (mode_file.c) had the game serve 3 balls and
followed them down to one. Star Wars 2025 LE/Pro, Transformers, Fallout and Pokemon draft with every core entry
placed; each needs its own run (and its lamps, screens and callouts) before its port ships. The app still never
derives a 64-bit port itself (`port_derive._spike3_port`): only a port proven on the rig ships.

**Star Wars 2025 Pro 0.84** (`ports/spike3/star_wars_2025_pro-0.84.port`, program sha1 2c9070fb..., PAD-1291) drafted
the same way, every core entry placed (29 sites; game over is bus event 0x46; game start / ball start have no direct
call), but its first run never started a mode: **a switch's id is not always its rank in the device table.** The game
handed its switch_hit site 83 for Right target (rank 61) and one less than the rank for every switch after it - it
numbers Right target after all the other playfield switches - while ELG and Walking Dead Remastered number by rank.
Nothing in the static table shows it (the record bytes, name pointers and shared names were checked), so the ids are
MEASURED:

- `tools/spike3_emu/proofs/swcensus.sh` (TITLE=<game>, as root, hidden, muted) boots the card with the draft port and
  `value switch_hit_log`, starts a game and presses each switch the draft names, one at a time, waiting for the runtime's
  `switch hit: switch N` before the next; it writes `<id> <NAME>` (or `# no switch hit: <NAME>`) per switch - the
  format of PAD-1290's s3census.sh (below), which reads the ids off a probe mode's shots instead of the switch_hit log.
- `s3port.py ... --switch-ids <census>` writes the switch lines from it: each switch at its measured id, one with no hit
  or not in the census left out (as a comment), the shot bits packed over the lines written. The Pro's census is
  `proofs/titles/star_wars_2025_pro-0.84.switch_ids`: 27 switches sent an id; the slingshots, pop bumpers and drop target opto
  sent none (their descriptors broadcast nothing, as The Beatles' slings on Spike 2).

Run the census for every Spike 3 title before its first proof; a title whose census equals the ranks needs no file.
Proof (2026-11-15, Spike 3 rig slots 240-242, hidden, muted, prebuilt mode64.so; titles/star_wars_2025_pro.env): CLOCK
TEST started on the third Right target hit, scored 6 shots through score_add (+21,000,000) and ended on its 25 s clock;
MB TEST served 3 balls and ended at one; SAVE TEST's save served the drain inside it back, and the drain after it ended
the ball (SAVE CONTROL: its first drain); a stack no mode waited out the game's own 2-ball multiball (six centre ramp
shots: JUMP RAMP ENTER / EXIT OPTO, `GAME_MB_TIMES=6`) and started after the drain to one. MULTIBALL_PROVEN,
BALL_SAVE_PROVEN and STACK_BALLS_PROVEN carry `star_wars_2025_pro-0.84/spike3`; so does SWITCH_SHOTS_PROVEN: ALL SHOTS
(`PROOF=clock CFG=allshots.cfg SHOT_BITS=0x7ffffff SHOT_SWS=<every switch>`: every switch line a shot,
`game_modes stack`, `ends_on clock`; the `clock` play shoots the list twice and waits out the clock) took 54 shots for 54
presses, each switch twice. A card the app Wrote (`spike3_write.write_card`, one Form mode: Right target x3, Left orbit /
At-at target / Right orbit) read back with /games/game -> pad/padmode/padmode.sh, game.target star_wars_2025_pro/game,
the mode.cfg (trigger 0x80 x3, shots 0x800c00), and game.port and mode.so byte-identical to the repo's port and
prebuilt mode64.so. Lamps, shows, screens,
clips, callouts, held coils and the game's mode books are this title's own work, not carried. s3port.py also leaves the
reference's own mode books (place_flag / done_flag / done_audit) and a held-coil pair placed only half (PAD-1288) out.
Tests: tests/test_pad1291_spike3_2025_pro_port.py.

PAD-1292 (Walking Dead Remastered LE 0.92's own pass): the multiball and ball save proven on slot 93
(`s3proof.sh` with `modes/mb_wdr.cfg`, `save_wdr.cfg`, `savectl_wdr.cfg`: ELG's files with WDR's Tower target trigger
0x40000 and Left loop / Right loop / Right spinner shots 0x480040; `TRIGGER_SW="TOWER TARGET"`,
`SHOT_SWS="LEFT LOOP|RIGHT LOOP|RIGHT SPINNER"`, `ATTRACT_WAIT=60 COINS=4 START_HOLD_MS=0`) and in MULTIBALL_PROVEN /
BALL_SAVE_PROVEN. The Write: `spike3_write.write_card` put a mode on a copy of the card (2103 s, scratch on D:), read
back through its own encryption, and that card (into the rig's store with `PAD_SPIKE3_KEYFILE` naming the user's
`~/.pad/spike3_padkeys.json`: the copy has no sidecar) booted through its own hook and ran the mode to its clock.
Owed: STACK_BALLS (no switch route started WDR's own Blood Bath / Prison / Well multiball; play.sh's
`PROOF=explore EXPLORE_SEQ="SWITCH*hits|..."` reports the trough after each step, for the next try). The redraft
had given WDR Star Wars ELG's mode-book flags by number (`done_flag_0 66`, `place_flag_completed_2 68`: WDR's right
spinner lit and a skill-shot speech flag); PAD-1288/1289's GAME_VALUE (below) leaves them out, and
test_pad1287's redraft check holds again.

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
  next run's start). Code modes' own sounds go the same way (PAD-1295).
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
- **Not on Spike 3**: `switch_edge` as Spike 2 has it - the 64-bit drain has no per-switch edge call, it calls
  switch_hit / switch_hit2 itself by the switch's handler bits (PAD-1322 hooks a point inside its loop instead:
  "The switch edges on Spike 3", below). `ball_end` - the end of a ball is the bus's
  event 0x34 through hook_dispatch (Spike 2's site is that event's handler). `player_advance` - the clip_play path,
  not this title's.
- **s3port.py** `play_engine` reads it all off a 64-bit program: carries the matcher's five plain calls, the coil
  records off coil_fire's writer (`coil_records`), every take / give pair (`coil_control`), a held coil's object by
  its constructor's call with its device id and the vtable slot that asks the adjustment getter (`device_object`),
  the flag set (`flag_set`) and each Spike 2 block start by the game flag it sets (`mode_starts`).
- **The Modes tab** offers on the Spike 3 card: Multiball, "Hold the Right control gate", the game's three modes a
  mode keeps from starting, and "waits while the game's modes run" (MULTIBALL_PROVEN, HELD_COILS_PROVEN,
  STACK_BALLS_PROVEN, STACK_FLAGS_PROVEN). Ball save stayed greyed here: the rig served the game's trough-eject
  retry at a game's start as another ball (PAD-1286 fixed the rig and proved it, below).

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

**Fallout LE 0.82** (`ports/spike3/fallout_le-0.82.port`, program sha1 19081048...; PAD-1288), drafted from ELG's port
(9,771 of 18,297 functions paired, every core entry placed, 39 shots) and proven 2026-11-15 on the Spike 3 rig (slots
63-66, hidden, muted, `s3proof.sh TITLE=fallout_le`): CLOCK TEST started on three Junk target hits, scored 6 shots
through score_add (+21M) and ended on its 25 s clock, twice; BALL_SAVE (the drain inside the save served back, the
control ended on its first drain) and MULTIBALL (3 served, handed back at one ball) rows as in the table below; a real
card written with a mode by `write_card` (590 s; VAULT RUN, three Junk target hits) and read back through its own
encryption: `/games/game -> pad/padmode/padmode.sh`, `game.target = fallout_le/game` (sha1 19081048...), mode.so =
prebuilt mode64.so and game.port = this port byte for byte, root 0755/0644. Booted (slot 63, the card's own hook,
`PAD_S3_PIVOT=0`, store built with the app's `~/.pad/spike3_padkeys.json`): the runtime read
`/games/pad/padmode/game.port`, VAULT RUN started on the third hit, scored 2 shots (+3M) and gave way when the game's
own mode began (Fallout's modes are not held back: "never waits"). What the drafter learned:

- ELG's port gained its mode books (`place_flag_completed_*`, `done_flag_0`: PAD-1286) after Walking Dead was drafted,
  and the same numbers line up in the framework's flag code on Fallout - but they name ELG's modes, so the runtime
  would have fired "done" starts on whatever Fallout's flag 66 is. `GAME_VALUE` now counts every mode-book value as
  the reference game's own.
- `coil_give` lines up on Fallout but `coil_take` has no counterpart; the runtime arms held coils on both or neither,
  so `SITE_PAIRS` writes a lone half as a comment.
- Fallout's start on the rig: its Fat Man steppers home for ~110 s, it is not on free play, and a character select
  follows Start (ACTION BUTTON). Its title file (`proofs/titles/fallout_le.env`, PAD-1289's layout: card, port,
  `MODES=modes/fallout_le` with Fallout's shot bits) sets `ATTRACT_WAIT`, `COINS` and `AFTER_START_SWS`, which play.sh
  presses after each Start. `PROOF=mode` is the plain one: trigger, shots, the clock ends it.
- Not proven, so greyed: stacking (needs Fallout's own multiball switch for `PROOF=stackmb`), place / done (no block
  starts for its own modes), lamps, shows, screens, clips, own sounds - each its own work.

## The proof pass on a Spike 3 port (PAD-1286)

PAD-1277 keeps a Spike 2 build's proof tables off its Spike 3 twin: every `*_PROVEN` table (mode_project.py) is keyed
`<game>-<version>/spike3` for a Spike 3 build (`table_key`) and starts empty, so the Modes tab offers a feature on a
Spike 3 card only once the emulator has seen it there. The pass, per Spike 3 port (Star Wars ELG 1.10 is the worked
example; PAD-1288..1293 do the others):

1. **The port carries the feature's lines.** s3port.py writes a placed site or value as a comment while its runtime
   feature still reads 32-bit structs; a feature made 64-bit carries them (PAD-1282 sounds, 1283 lamps, 1284 screens,
   1285 multiball / held coils / blocks, 1286 the game's mode books). Redraft the port (`s3port.py <S2 game> <S2 port>
   <S3 game> -o draft.port`), keep the shipped port's proof notes at its head, and check the profile:
   `mode_project.profile_from_port(<port>).cannot` names each part greyed and why ("has not found" = the port lacks
   it; "has not yet seen ... in the emulator" = the lines are there, the proof is owed).
2. **Measure the switch ids** (`proofs/s3census.sh`, PAD-1290, or `proofs/swcensus.sh`, PAD-1291: the same file) and
   redraft with `--switch-ids` when they are not the ranks.
3. **Run the proof** with `tools/spike3_emu/proofs/s3proof.sh` (as root in WSL, hidden and muted, a free Spike 3 rig
   slot; `PROOF=` picks the play, `CFG=` / `CFG2=` the mode files in `proofs/modes/`; the title's switch names are
   play.sh's variables at its head - TRIGGER_SW, SHOT_SWS, EARLY_SWS, GAME_MB_SW, START_HOLD_MS). Logs: the runtime's
   mode.log, the bridge's bridge.log ([ball] lines), the play's own output.
4. **Add the build to the table** with a comment saying what was seen, as the Spike 2 entries do.

Before step 2 on a new title, **take its switch census** (PAD-1290): a drafted switch line's id is the switch's rank in
the device table, and that is not every title's numbering. `TITLE=<game> DRAFT=<draft port> SLOT=N OUT=<dir> bash
tools/spike3_emu/proofs/s3census.sh` starts a game twice on the rig with a port that gives every id 0-127 a bit of its
own and shot_probe_mode.c logging each shot, presses every switch line's switch once and writes `<game>.switch_ids`;
`s3port.py ... --switch-ids <that file>` redrafts with the measured ids and leaves out a switch that never reached the
modes. Keep the file in `proofs/titles/` beside the title's `<game>.env` (its card, port, start and switch names).

| table | proof | what the logs must show |
|---|---|---|
| BALL_SAVE_PROVEN | `PROOF=ballsave CFG=save.cfg`, and the control `CFG=savectl.cfg` | `[pad] ball save: 15 s ... the game is saving`; the drain inside it served back (eject + auto plunger in bridge.log) and the mode running on; shots scored on that ball; the drain after the save `END (ball ended)`. The control: `END (ball ended)` on its first drain. EARLY_SWS starts the game's own start-of-ball save right after the plunge, so it is over (40 s) before the mode starts. |
| PLACE_PROVEN, DONE_PROVEN | `PROOF=game CFG=place.cfg CFG2=done.cfg SO=<build_probe.sh's .so>` | place_probe_mode.c calls the game's Orbits start (id 1; another title: its port's block id) 25 s in: `PLACE TEST START (in place of the game's mode)`, at its end `COMPLETED flag 67 set` (the port's place_flag_completed_1), `done: player 1 completed`, then `DONE TEST START (1 of the game's modes completed)`. |
| MULTIBALL_PROVEN | `PROOF=mb CFG=mb.cfg` | `multiball: 3 balls asked for ... the game is serving`, the mode running its clock, `multiball: ours is over (1 ball in play)` |
| HELD_COILS_PROVEN | `PROOF=coil CFG=coil.cfg` | `HOLD for 2000 ms ... ONE command`, `let go - its time ran out`, a second hold on a shot; no abort |
| STACK_BALLS_PROVEN | `PROOF=stackmb CFG=stackmb.cfg` | `not started: a multiball is running` in the game's own multiball, then START after drains |
| STACK_FLAGS_PROVEN | PAD-1285's block_probe_mode.c (the game's Ramps start called while a mode blocks and while none does) | `the game's mode 2 (Ramps) did not start` while blocked; the flag set when not |
| LAMPS_PROVEN, TITLE_SCENES | PAD-1283 / PAD-1284 (padled from the bridge; the HUD frames) | see those sections |

**The rig's ball model** must serve one ball per eject for any drain-based proof: PAD-1286 found Star Wars ELG reads
its trough from TROUGH 6 and the model now learns the direction at a game's start (docs/plans/spike3_emulation.md,
"The trough's direction"). A run's bridge.log says `turned round` when it did.

**Proof (2026-11-15, Star Wars ELG 1.10, rig slots 88-90, hidden, muted, this build's mode64.so and port)**, every row
above through s3proof.sh:
- Ball save: SAVE TEST's 15 s save taken through multiball_serve; the drain 3 s in served back (eject, auto plunger);
  3 shots scored 6,000,000 on that ball; the drain after the save ended it. SAVE CONTROL (no ball_save) ended the ball
  on its first drain, 5.8 s in.
- Place / done: the game's Orbits start taken by PLACE TEST, its 8 s clock completed it - the game's COMPLETED flag 67
  set - and DONE TEST started on that completion 17 ms later; the game played on to the cap.
- Re-run on the fixed rig (PAD-1285's proofs had run with the extra balls): MB TEST served 3 through the game's serve,
  ran its 40 s, `ours is over` at one ball; COIL TEST's right_gate held 2015 ms and 1513 ms as ONE command each; STACK MB
  waited in the game's own multiball and started after its second drain.

**Not offered on the Spike 3 card yet, and why:** (spare switch inputs and driver outputs were here until PAD-1329, and
the game's challenges until PAD-1330, both below); see the ticket's report for where they go next. The game's "time is up" line
(TIME_UP_NONE) is not claimed for the Spike 3 build: the option is greyed there anyway (its port has no time-up call),
and the Spike 3 sound bank is a differently encoded image.bin (the same size, 99.6% of its bytes differ), so PAD-479's
transcription does not carry over by itself. Music modes, editions, menu settings: Spike 2's delivery only (above);
the switch edges: PAD-1322, below.
Tests: tests/test_pad1286_spike3_proofs.py, tests/test_spike3_balls.py.

### Pokemon LE 0.82 (PAD-1289)

`ports/spike3/pokemon_le-0.82.port`, drafted from Star Wars ELG 1.10's Spike 3 port (`s3port.py`, 9,333 functions
paired, 29 sites, 45 shot switches; only coil_take / coil_give unplaced). The proof rig takes a title now:
`TITLE=pokemon_le` sources `proofs/titles/pokemon_le.env` (the card, the port, `proofs/modes/pokemon_le/` for the mode
files, the switch names) and play.sh drops `COINS` before Start and again on each retry (Pokemon is not on free play: attract says
CREDITS 0, and coins dropped while the game boots are not counted). `PROOF=mode` is the plain trigger / shots / clock
play.

What the first runs found, fixed here:
- **Every switch id was 16 low.** The device table's names are UTF-8; `device_records` read them as Latin-1, so
  "POKÉ BALL SPOT" had an unprintable `\x89`, the walk stopped there and the 16 QR scanner switches before it were
  never counted (the rig's `value switch_hit_log` showed Berry target left arrive as 36, the draft said 20). Names are
  read as UTF-8 now (Latin-1 if they are not). `s3nodes.Elf.cstr` had the same decode: the rig's view of Pokemon's
  table lacked the POKÉ BALL coil and ~120 playfield lights behind that record. Star Wars ELG reads the same either way.
- **Star Wars ELG's mode-book flags were carried** (done_flag_0 66, place_flag_completed_2 68: the same numbers sat at
  lined-up instructions). They are ELG's own modes; `GAME_VALUE` leaves `place_flag_*` / `done_flag_*` out.
- **Modes off a Spike 3 card**: `mode_from_card.read_padmode` only looked for `/usr/local/padmode` on plain ext4
  partitions; a Spike 3 card keeps them in `/games/pad/padmode` inside the encrypted games volume. It opens that volume
  through the card's key now (`spike3_card.open_games`), so the Modes tab's "modes from a card" reads a Spike 3 card.

Proof (2026-11-15, rig slot 129, hidden, MUTED, the library card): POKE TEST (Berry target left x3, 20 s) started on
the third hit, scored 6 shots through score_add (+21,000,000) and ended on its clock; ball save and its control, and a
mode's multiball, as in the table above (BALL_SAVE_PROVEN, MULTIBALL_PROVEN carry `pokemon_le-0.82/spike3`). The Write:
`spike3_write.write_card` with a BERRY RUSH mode (446 s), `card_state` = modes / `pokemon_le/game`, the padmode files
read back through the card's key, `card_modes_file` gave the modes back whole and `import_modes` loaded them into a
fresh project; the written card (in the store via `s3store.py build`, `PAD_SPIKE3_KEYFILE` = the app's
`~/.pad/spike3_padkeys.json`) booted with its own hook and mode.so, and BERRY RUSH started on its trigger, scored and
ended on its clock. Not proven, so not offered: stacking on the game's own multiball (which shots start Pokemon's own
multiball is not known yet), held coils (no coil_take / coil_give), the game's own modes (place / done), lamps,
screens, clips and own sounds (this title's own content). Tests: tests/test_pad1289_pokemon_spike3_port.py.

### Star Wars 2025 LE 0.96 (PAD-1290)

`ports/spike3/star_wars_2025_le-0.96.port` (program sha1 91fb0281...), drafted from ELG's Spike 3 port: every core site
placed (29), ELG's mode-book flags (place_flag / done_flag) and the coil_take / coil_give pair left out as ELG's own
(the same s3port.py rule PAD-1288 / 1289 hit). The draft's switch lines put presses on the wrong shots: this program
numbers its RIGHT TARGET last (87) and every switch after it in the table one lower (Left orbit 63, not 64), and nothing
in the device table's records says so (the two RIGHT TARGET records are a lamp and a switch, the outlanes share names
with lamps and keep their ranks, the device objects are in table order). The census measured all 32: 27 reach the
modes, the slingshots, pop bumpers and drop target never do. The same census on ELG 1.10 and Walking Dead Remastered
0.92 found every id their ports carry right (titles/*.switch_ids), so the rank rule stays the default.

Proof (2026-11-15, Spike 3 rig slots 190-194, hidden, MUTED, prebuilt/mode64.so): CLOCK TEST (Right target x3, 25 s)
started on the third hit, scored 6 shots through score_add (+21,000,000) and ended on its clock; ball save (save taken,
the drain inside it served back, 3 shots on that ball, the next drain ended it) and its control; a mode's 3-ball
multiball through the game's serve, "ours is over" at one ball. Not proven: a `stack no` mode waiting in the game's own
multiball - the rig did not start one (Sarlacc pit exit x3, Sarlacc ramp + pit, Death Star target + locks, the locks
and Top vuk), so STACK_BALLS_PROVEN leaves it out and the tab says so. A card Written with a TRENCH RUN mode (386 s)
read back through the card's key: `/games/game -> pad/padmode/padmode.sh`, `game.target = star_wars_2025_le/game`,
root-owned 0755 / 0644, mode.cfg with the census bits, game.port this port byte for byte.
Tests: tests/test_pad1290_spike3_star_wars_2025_le.py.

### Transformers LE 0.96 (PAD-1293)

`ports/spike3/transformers_mtmte_le-0.96.port` (program sha1 a3b67ca1..., the card
`transformers_mtmte_le-0_96_0_spike3`), drafted from ELG's Spike 3 port: 9,883 functions paired, every core site placed
(30 with the switch edge), only ELG's own coil_take / coil_give left out. The census (`TITLE=transformers_mtmte_le`,
slot 160) found all 37 switch lines reach the modes, **every id 3 below its device-table rank** (Megatron target right
42, not 45) - a uniform offset, unlike Star Wars 2025's one late switch - so the port carries the measured ids
(`titles/transformers_mtmte_le-0.96.switch_ids`). The card had no row in `spike3_games.SPIKE3_DB`, so it read as the
generic key and "Transformers Mtmte LE"; it is `transformers_mtmte_le`, "Transformers LE", now (mode_project's
`_TITLE_NAMES` too).

Proof (2026-11-16, Spike 3 rig slots 160-163, hidden, MUTED, prebuilt/mode64.so): CLOCK TEST (Megatron target left x3,
25 s) started on the third hit, scored 6 shots on Right orbit, Center loop and Left orbit through score_add
(+21,000,000) and ended on its clock; ball save (the drain inside it served back, 3 shots on that ball, the next drain
ended it) and its control (ended on its first drain, 5.9 s in); a mode's 3-ball multiball through the game's serve,
"ours is over" at one ball. The Write: `spike3_write.write_card` with an AUTOBOTS ROLL mode, `card_state` = modes /
`transformers_mtmte_le/game`, the padmode files read back through the card's key, `card_modes_file` and
`import_modes` gave the mode back whole; the written card (`s3store.py build`) booted with its own hook and mode.so and
AUTOBOTS ROLL started on its trigger, scored 6 shots (+21,000,000) and ended on its 20 s clock. Not proven: a
`stack no` mode waiting in the game's own multiball (the Soundwave locks x4 did not start one on the rig), so
STACK_BALLS_PROVEN leaves it out. Tests: tests/test_pad1293_transformers_spike3_port.py.

## The switch edges on Spike 3 (PAD-1322)

Spike 2's framework drain calls one small per-switch function for every edge (`site switch_edge`), which the
runtime hooks: every switch's every edge, read off the game's tables (the shots from switches, PAD-641's attract
flipper sounds, PAD-945's shot sounds, co-op's picks, PAD-1033's held buttons). Spike 3's 64-bit drain has no such
call. Star Wars ELG 1.10's, 0x3085c0, under its mutex (state 0x7477e0): it takes the list of switch records the
node boards' reader queued (head at state + 88, next at record + 8) and for each record x19:

| record (x19) | |
|---|---|
| +0x20 u16 | switch id (w23) |
| +0x22 / +0x24 | bit and board of the raw input; +0x26 u16 the edges still queued |
| +0x28 u8 | the edge's level, WRITTEN here (0x308654) before anything reads the handler bits |
| +0x10 | the descriptor (x24): +0x2e u16 handler bits (0x800 runs on level 1, 0x400 on level 0, 0x2000 / 0x1000 call switch_hit / switch_hit2), +0x30 u16 the other flag word (bit 2 = active high, as Spike 2's polarity) |

then, by the mode mask (GOT slot -> 0x79206c, `tst` with the handler bits) and the handler bits, runs the switch's
handler and calls switch_hit / switch_hit2 itself. 0x308684 (`ldr x24, [x19, #16]`) is where every iteration
passes after the level is written and before the bits are read: the port's `site switch_edge` on Spike 3.

- **hook_a64.h `hook_callee`**: the logger needs x19, which a plain 64-bit logger cannot see (r[0..8] = x0..x8). It is
  hook_n through one shared step (`pm_a64_callee`) that stores x19..x28 as they are, hands the C logger (r, x) with
  x[0..9] = x19..x28 and loads them back. The 32-bit hook_full's layout (r4-r12 at r[4..12]) stays Spike 2's.
- **The runtime**: `on_switch_edge64` reads id / level / descriptor off the record in `value switch_record_reg`
  (19) at `switch_id_at` 0x20, `switch_level_at` 0x28, `switch_desc_via` 0x10, `switch_flags_at` 0x2e,
  `switch_polarity_at` 0x30, with `data mode_mask`; a hit is Spike 2's rule (edge_is_hit) and the consumers are the
  same. No drain range test (the site is only in the drain). `edge_hook` hooks it once for all four features.
  `switch_held` reads a switch's record as its last edge left it (remembered per id). PAD-1051's hiding stays Spike
  2's (it rewrites that generation's 32-bit descriptor table).
- **s3port.py `switch_edge_point`** reads the point and the layout off any 64-bit program's own drain (strb level;
  cbz id; ldr descriptor; the two ldrh tested at bits 11/10 and 1/2; the mode mask's GOT load) and `edge_lines` writes
  them into a draft in place of Spike 2's switch_edge / switch_drain / table lines, either reference. ONE point on
  each of the seven Spike 3 programs, the same layout on all: Fallout LE 0x71b8b4, Pokemon LE 0x59e444, Star Wars
  2025 LE 0x593414 / Pro 0x2b94d4, Star Wars ELG 0x308684, Transformers LE 0x4a49b4, Walking Dead Remastered LE
  0x2c6c94. Both Spike 3 ports carry the lines; Fallout LE 0.82's (PAD-1288) too, proven there with PROOF=edge
  (flipper buttons in attract, the Right slingshot, the trigger) and its clock run repeated on the edge source.
- With the site there, a Spike 3 port's switch shots come from the edges (Spike 2's default, `switch_edge_shots` 1),
  not the switch_hit sites: every switch line counts, the slingshots and pop bumpers too (ELG's have no handler bits,
  so switch_hit never saw them).

What still keeps co-op, handicaps and the music modes' attract / shot sounds off Spike 3 is the rest of each (table
above): the menu rows, the player sites, the 64-bit asset descriptors.

Proof (2026-11-15, Spike 3 rig slots 91 and 92, hidden and MUTED; `tools/spike3_emu/proofs` PROOF=edge, the port's
copy with `value switch_edge_log 400`, this build's prebuilt mode64.so):
- **Star Wars ELG 1.10** (modes/edge.cfg): `switch shots: 30 switch line(s) ...; the switch drain's edges (switch_edge
  0x...8684 in the drain's loop, the record in x19, the game's mode mask applied)`; 119 edges logged. In attract the
  flipper buttons (49 / 50, flags 0, polarity 0x20) pressed at level 0 with mode mask 0x0110 (its attract bit 0x10),
  in game 0 - no hits. In play TOP LANE CENTER (31, flags 0x2400) x3 started EDGE TEST; CENTER TARGET (33), HIDDEN
  TARGET (29) and LEFT LUKE ORBIT (28, flags 0x1400) scored +1M .. +6M, one hit per press on its level-0 edge, the
  release no hit; the slingshots (54 / 55) and RIGHT POP BUMPER (25), flags 0, were hits too; the game's Orbits start
  was held off as before; the mode ended on its clock.
- **Walking Dead Remastered LE 0.92** (modes/edge_wdr.cfg; a fresh WDR takes a Start only with credits and ~60 s into
  attract: COINS=4 ATTRACT_WAIT=60): TOWER TARGET (54, flags 0x1400) x3 started EDGE TEST, LEFT LOOP / RIGHT LOOP /
  RIGHT SPINNER scored six shots (+21,000,000 into the game's score), the mode ended on its clock; LEFT SLINGSHOT and
  TOP POP BUMPER (flags 0x2400 here) were edges as well.
Tests: tests/test_pad1322_spike3_switch_edges.py.

## Code modes on Spike 3 (PAD-1295)

PAD-1272 left a project's code modes out of a Spike 3 build: they were compiled for Spike 2's 32-bit ARM and the
app's Linux had no aarch64 compiler (the dev rig's `xgcc.sh` `apt-get download`ed one, which the shipped runtime
cannot do: its image keeps no apt lists). Now:

- **The kit**: `tools/spike3_emu/xgcc.pins` pins the aarch64 gcc 13.3.0 and binutils 2.42 packages by SHA-256, from
  the Ubuntu snapshot the PAD Runtime is built from (`SNAPSHOT=20260801T000000Z`), at the runtime's own toolchain
  versions (its arm cross gcc is 13.3.0-6ubuntu2~24.04.1, binutils 2.42-4ubuntu2.10), so every library they load
  is already in runtime-7. `xgcc.sh` fetches the eight .debs (about 41 MB) once, checks each hash, `dpkg-deb -x`es
  them into `/var/lib/pad-s3/xgcc` (stamped with the pins file's hash, one unpack at a time under flock) and prints
  `s3cc`, with `s3nm` beside it. binutils comes in the kit, so nothing needs installing; off x86-64 a system
  aarch64 gcc is used. The same kit builds the Spike 3 rig's shims (s3build.sh, ensures3select.sh), which on a
  user's runtime had the same dead `apt-get download`. It rebuilds `prebuilt/mode64.so` byte-identical.
- **The build**: `spike3_modes.plan` takes code modes (a code-mode-only project too) and calls `mode_write.plan`
  with `code_ok=True, arch="a64"`; `code_plan` -> `compile_code_object(..., arch="a64")` runs `build_mode.sh -a a64`,
  which with no CC takes the kit's `s3cc`. The kept object's key carries the machine and the pins file.
  `p2_payload` stages the compiled object for any machine (the pinned mode64.so without code modes).
- **build_mode.sh's nm check never ran on a64**: its nm name was derived as `${CC%gcc}nm`, nothing for `s3cc`. It
  runs now (the kit's `s3nm`), and on a64 the banned-call rule (MODE_SDK.md rule 2) is read off the modes' own
  sources compiled alone: the 64-bit runtime itself calls `malloc` for the game's std::string objects
  (`std_string`, PAD-1284), on purpose. Both prebuilt objects are byte-for-byte unchanged (only build_mode.sh's
  hash moved in SOURCES*.sha256).
- **Their sounds**: a code mode's music and calls ride carriers like the form modes' (PAD-1296):
  `spike3_modes.own_sounds(..., code=)` adds `choose_code_sounds`'s entries, each a record appended to image.bin
  and swapped in by key (`swap <request> <stock> <ours> call:<cue>` in `<slug>.assets`). `choose_code_sounds`
  read Spike 2's carrier table (`MS.carriers(game, version)`), so a `_spike3` profile had none; it takes
  `profile_carriers(prof.key)` now. A swapped music is described as "(request N)", not Spike 2's bed sid.
- Try it's note names the code modes built in, as on Spike 2.

Proof (2026-11-15, Spike 3 rig slot 95, hidden, MUTED, Star Wars ELG 1.10 from the library): a project holding
one CODE mode, BOUNTY HUNT (3 Death Star target hits start it; every named shot scores a bounty growing 250,000 a
shot; 20 s), built by `spike3_modes.plan` (`real_card=False`, Try it's) - compiled in the PAD Runtime by the kit
from a fresh unpack - and run by s3run.sh with PAD_S3_MODE_SO / PAD_S3_MODE_FILES: it started on the third hit,
scored +250,000 / +500,000 / +750,000 / +1,000,000 on four shots and ended on time 20.2 s later (score 26,630 ->
2,563,700). With its own music (700 Hz), start call (1500 Hz) and shot call (1000 Hz) in assets.json
(`PAD_S3_AUDIO_OUT=1` keeping the PCM): carried on requests 70 / 135 / 202, each `[pad] sound swap` logged, and
every tone found in the game's own output at its logged moment (the start call until the first shot call faded
it, the four shot calls, the music under them). The Write's plan (`real_card=True`) builds the same set.
Tests: tests/test_pad1295_spike3_code_modes.py (the real a64 compile under a POSIX shell).

## Insider logins on Spike 3, and what co-op still needs (PAD-1326)

**The logins.** A Spike 3 program keeps its players' Insider logins as Spike 2's does: a user manager (a function's
static) with two tables, player p's entry at table + 20p + 4 (the 16-byte uuid and a flags word). Only the code's
shape changed: the manager's lookup is `cmp w3, #1; ldp xa, xb, [x0, #A]; csel x0, .., ne; b <table lookup>` (the two
tables are 8-byte pointers, read with one ldp), the table lookup checks `sub w, w, #1; and; cmp w, #3; b.hi` and forms
the entry with `mov x1, #4; mov w0, #20; umaddl`, and every caller forms the manager with `adrp` + `add`.
`coop_play.insider_users_a64` reads that; `insider_users` hands it a 64-bit program. All seven library programs:

| program | manager | A / B |
|---|---|---|
| Fallout LE 0.82 | 0x66ca6e0 | 0x190 / 0x198 |
| Pokemon LE 0.82 | 0x32973d0 | 0x190 / 0x198 |
| Star Wars 2025 LE 0.96 | 0x98b9f8 | 0x190 / 0x198 |
| Star Wars 2025 Pro 0.84 | 0x7e5940 | 0x190 / 0x198 |
| Star Wars ELG 1.10 | 0x710c20 | 0x190 / 0x198 |
| Transformers LE 0.96 | 0xad8050 | 0x190 / 0x198 |
| Walking Dead Remastered LE 0.92 | 0x8859f8 | 0x190 / 0x198 |

The runtime (`coop_user_table`, `coop_user_table_ok`, `coop_user_entry`) reads the tables as `pm_addr` and adds
`game_base` to the manager of both `users` lines (coop.cfg's and scorefeed.cfg's); Spike 2's object is the same code
(pm_addr is 32 bits there and game_base 0). Main's runtime on a Spike 3 card says `the user manager 0x00710c20 is not
mapped` (seen on the rig, a PAD-1324 run on slot 1): the address was the program's own, not where it was loaded.
Tests: tests/test_pad1326_spike3_insider_logins.py (a synthetic 64-bit program, the seven programs, the runtime).

Proof (2026-11-16, Spike 3 rig slot 133, hidden and MUTED): the score feed set planned by `spike3_modes.plan` from the
library's Star Wars ELG 1.10 card (scorefeed.cfg `users 0x00710c20 0x190 0x198`, this branch's mode64.so), the
PAD-1297 stand-in server on the game's loopback. A side script found the game's own load address (one
R_AARCH64_RELATIVE pointer of its data, minus its addend: qemu-user's guest addresses are not always the host's) and
kept the uuid 1326c0de-0b1e-4a5e-9a77-00112233aabb in player 1's entry of both tables (manager +0x60 and +0xf8: the
tables are arrays inside the manager, both entries were all zeros). At the game's game_over: `1 player(s): 207440 0 0 0,
logged in 1000`, then `posted ... (HTTP 200)` with `"insider":["1326c0de-0b1e-4a5e-9a77-00112233aabb"]`, the server
receiving the same body. Rig notes: Spike 3 runs do not show on riglock's board (slot 1 was PAD-1324's at the same
time), and the host's /proc/<pid>/maps names the program `/games/<title>/game` or by its full overlay path depending
on the run.

**Co-op play on Spike 3 (PAD-1326, built on PAD-1325's spike3_menu).** The core of co-op goes on: the game plays one
player for the team, the runtime takes the teammates in turn (the player change and add player wrapped, the player /
ball / players bytes), every teammate's score panel the team's score, the logins swapped so the teammate up has the
game's player's. A teammate joins with the right flipper button held and Start (PAD-1017's first route): the start
menu's CO-OP PLAY / TEAM PLAY entries need the menu's frame hook, 32-bit only (`hook_full` is 0 on 64-bit); the
characters, abilities, awards and co-op videos read 32-bit code. `coop_play.cfg_text` writes a 64-bit program the core
lines alone (`coop on`, `button`, `setting`, `only`, `users`), `mode_write.coop_into` adds no pick screens or clips and
says so (`A64_LEFT_OUT`). CO-OP PLAY is Off / On on Spike 3 (`MENU_VALUES_A64`, the runtime reads 1 as Classic): it goes
on through `spike3_menu.plan` (beside EDITION; on ELG Adjustments > Machine Settings > Attract Mode, its live value at
0x70afd8), which spike3_write now plans before the modes so coop.cfg names the value.
- **The flipper buttons**: `portswitch.switches_a64` reads a Spike 3 program's device table (the port drafter's rig-
  proven reader, s3port.device_records, shipped): every library program's two buttons (ELG: right 49, left 50).
- **The runtime**: the button's edges come from the 64-bit edge hook, which co-op now installs itself (`edge_hook`; a
  card of co-op and no shots had none, so the button never read held); the scores' addresses, the CO-OP PLAY word and
  the Insider gate's copy of it are `pm_addr`, the two words moved by `game_base`; the add player's bool masked.
- **The port**: ELG 1.10 carries coop_player_change 0x417b50 / coop_add_player 0x417710 (no arguments, a bool in w0)
  and coop_player 0x6b1a1a (the ball at +1: the player code reads [#2587]) / coop_players 0x792200.

Proof (2026-11-16, Spike 3 rig slot 134, hidden and MUTED): the set planned by the Write's own calls (spike3_menu.plan
then spike3_modes.plan) from the library's Star Wars ELG 1.10 card, the grown program staged over the card's. Armed:
`co-op: armed - hold switch 49 ...`, `switched in the service menu (CO-OP PLAY, value at 0x7c2b8112afd8, now Off)` (the
program's 0x70afd8 moved), the Insider gate on the same word. CO-OP PLAY set to 1 (its value written, as the menu
would), Start, then the right flipper held and Start: `co-op: teammate 2 joins`. Every ball drained: `ball 1, teammate 1
of 2 done - the next teammate, the same ball` / `the game's player 1 has player 2's login` / `ball 1, teammate 2 of 2
done - teammate 1, the next ball` ... `ball 3, teammate 2 of 2 done - the game is over`, `the game's end counts 1
player(s)`. Rig scripts: C:/tmp/PAD-1326/rig (plan_coop.py, job_coop.sh, play_coop.sh, setval.py).

**Co-op on the other titles, the BALL line, handicaps (PAD-1326, run 2).**
- `portcoop.lines_a64`: the player change / add player / player bytes in any Spike 3 program (the add player is the one
  byte incremented after an adjustment compare; the change reads the player and the count and compares player + 1;
  each starts at the bl target before it). Its lines are ELG's paired ones exactly; Fallout and Walking Dead carry
  them, Pokemon and both Star Wars 2025 as comments (no switch edge source: co-op and handicaps refuse with NO_EDGE).
- `portcoop.message_lines_a64`: the message table (Spike 2's with 8-byte relocated pointers) and its "BALL %d" index
  (ELG 1255, its Spike 2 build's number); the runtime steps the table by pointer size (message_borrow / restore /
  coop_msg_find / coop_ball_find).
- Handicaps: handicap.py reads the wide settings table and Start off the device table, writes no 32-bit `record`
  lines; the runtime hooks the flipper edges, moves the HANDICAP word by game_base, masks the getter's id to 16 bits;
  spike3_menu places HANDICAP; the Modes / Play options tabs say what Spike 3 gets.

Proofs (2026-11-16, Spike 3 rig, hidden and MUTED, planned through spike3_menu.plan + spike3_modes.plan):
- Fallout LE 0.82 (the finder's sites, its own CO-OP PLAY row at 0x669ff40): teammate 2 joined, `ball 1..3, teammate
  1/2 of 2 done`, `the game is over`, `the game's end counts 1 player(s)`; both score panels showed the team's 190,190.
  Rig note: its hit switches must be its own names (POP TARGET-LEFT, RADIO TOWER TARGET, 3 BANK-TOP, JUNK TARGET) or
  the playfield is never validated and every drain is re-served.
- ELG with handicaps: the pick walked with the flippers (`player 1's pick +0 / -1 / -2`), the game's own line read
  `P1 HANDICAP -2` (the 64-bit message table), `the game reads adjustment 165: 2 (its own 1)`; a second player's pick
  opened at their first ball; co-op's turn line read `PLAYER 1  BALL 1` on the same line.

**Co-op and handicaps not on one Spike 3 card.** With both on, ELG's game stopped at a co-op turn change twice (once
at teammate 1's end, once at the turn into ball 2; the game's memory went unreadable at that moment, the log stopped).
Each alone plays out. So spike3_modes.hand_wanted leaves the handicaps off a card with co-op (HAND_WITH_COOP, said on
the Write and on the Play options tab), and the 64-bit runtime refuses handicaps when coop.cfg is there. The one thing
the two add together is the adjustment getter wrapped (handicaps) while co-op's player-change wrap calls into the
game's change, which reads adjustments; that is where to look to lift the gate. Rig note: a job's play script left
running after its slot is stopped keeps writing the same output file ("the bridge's ball model did not answer") -
kill job_coop.sh / play_coop.sh by pid, and give each run its own output.
After the merge with the music modes (PAD-1324) and the gate: ELG planned through the Write again played a whole co-op
game (teammate 2 joined, three balls of turns with the logins swapped, `the game's end counts 1 player(s)`), and a
handicaps-only ELG card opened and took both players' picks (P1 +1, P2 +0). Planning it caught a check the merge added
after the music modes that returned no plan for a card of co-op alone (fixed; a test pins every such check).
Rig scripts: C:/tmp/PAD-1326/rig (plan_coop.py, job_coop.sh, play_coop.sh, setval.py, watch_bytes.py, inject.py).
Tests: tests/test_pad1326_spike3_insider_logins.py.

## Music modes on Spike 3 (PAD-1324)

Spike 2's music modes (PAD-494, `sound_modes.py`) hand the game a mode's DESCRIPTOR at its resolver, because a Spike 2
voice plays as long as the descriptor declares. A Spike 3 sound plays as long as its own RECORD says (PAD-1296: a 20 s
file under a 26 s carrier looped past it), so no descriptor of the game's is needed (and its descriptors are 64-bit):

- **The files** (`spike3_music.records`): each mode file is made into its slot's format (`sound_modes.convert`, its own
  loudness offset applied) and APPENDED to image.bin as a record of its own, keyed beside the slot's record
  (`spike3_write.free_key`, after the modes' own sounds' records, whose keys it does not take). One file in several
  modes of one slot at one loudness is one record. It plays at its own length, as a Spike 3 replacement does.
- **sounds.cfg**: `setting <the value's address> <n>` (the program's own address: the 64-bit runtime adds the PIE's load
  address, as it does the port's), an `mswap <m> <slot's key> <mode m's key>` per slot and mode, `only` on a card with no
  modes, and the record lines an extract reads the modes back from. pad_mode_runtime.c (`#if PM_A64`, so the Spike 2
  object is byte-identical) swaps the key in the record lookup hook (`msw_lookup`, before the sounds in turn) while the
  setting says m, read at every lookup. A `sound` descriptor line is left alone on 64-bit, with a sentence.
- **MUSIC MODE** goes on the Audio Content page, found by the page's NAME: `menu_settings.wide_category_names` reads the
  64-bit program's page table (32-byte records numbered from INVALID, each pointing at the page's five-language name
  line; in a PIE through its R_AARCH64_RELATIVE addends; another table that starts with INVALID, ELG's 187 wire colours,
  is told apart by naming our pages). Audio Content is 13 on Star Wars ELG 1.10, Fallout LE 0.82 and Transformers LE
  0.96 (empty as shipped on ELG and Fallout; Transformers' carries Family Mode and Attract Mode Developer Credits
  Music, under which MUSIC MODE goes first); `plan()` takes a 64-bit row's category from it (`wide_category`) and says where it is
  (`Adjustments > Machine Settings > Audio Content`). The row is the PAD-1321 grow (`grow_wide_program`).
- **game.pad**: the card's own program is never touched. The grown copy goes in `/games/pad/padmode/game.pad` and the
  hook runs it in the stock one's place when it is there; a Write without music modes (or Remove) wipes pad/padmode, so
  the card gets its own program back. No Spike 3 program finds its files from its own path (only absolute /games/...
  paths; no /proc/self/exe). s3run.sh runs it too when it does the hook's steps. Try it puts it over the stock program in
  the rig slot's /games (games.patch `whole`), and the records go in as the image.bin patch.
- **The gate**: `sound_modes.title_refusal` sends a Spike 3 profile (`arch == "a64"`) to `spike3_music.title_refusal`:
  offered on `spike3_music.PROVEN` (Star Wars ELG 1.10, Fallout LE 0.82: a Spike 3 port naming sound_lookup and a program
  whose menu takes the row); Pokemon LE, both Star Wars 2025 and Walking Dead Remastered say their menu has no setting the
  game stopped using; Transformers LE 0.96 joined PROVEN with PAD-1359 once PAD-1293 gave it its port. Before, a Spike 3 ELG project passed
  the Spike 2 gate by its shared `star_wars_elg-1.10` key and the Write then dropped the modes; Fallout's was refused
  with Spike 2's "update the machine's code". The rest of the sound pane that rides sounds.cfg (sounds in turn, attract
  and shot sounds, the jukebox) says it is Spike 2's on a Spike 3 title, and a Write logs each one asked as left out.

Proof (2026-11-16, Spike 3 rig slot 1, hidden and MUTED, `PAD_S3_AUDIO_OUT=1` keeping the PCM; Star Wars ELG 1.10 from
the library): a project giving 42 music beds (every stereo sound of 20 s or more) a 700 Hz tone for mode 2 and an
1100 Hz tone for mode 3, built by `spike3_modes.plan` (`real_card=False`, Try it's: 84 records appended, game.pad
over the stock program, sounds.cfg):
- the operator menu listed **Audio Content** under Machine Settings (absent on the stock card) with the one row **Music
  Mode**, help `1 = Standard, 2 = Custom A, 3 = Custom B`, Current Value 1; set to 2 it read back 2
  (work/artifacts/PAD-1324/emulator_elg_*.png).
- the runtime armed `84 record(s) over 3 mode(s), the setting at 0x...aff8` (the load address added) and said `mode 2
  from here on` / `mode 3` / `mode 1` the moment each was set in the menu.
- with the SDK's sound_fire_mode.c beside it (a rig copy of sounds.cfg without `only`, so its tick runs; the fire file
  written through /proc/<game>/root, the run's private mount namespace): request 64 (idx 569) in mode 2 logged `record
  4e00022002004080 plays mode 2's, 4e00022002005080` and the PCM 0.5-4.5 s after was 100% 700 Hz; in mode 3 request 66
  (idx 248) took mode 3's record (the still-looping 64 took mode 3's at its next lookup too) and the PCM was 100% 1100 Hz;
  back in mode 1 request 75 played the game's own song (no swap, its own spectrum).
- **Fallout LE 0.82** the same way (its 11 stereo idx sounds of 20 s or more, 22 records; its 107 MB program grown;
  its Adjustments page starts with Pricing, so Machine Settings is its third row): Audio Content listed with Music Mode
  (set to 2, Current Value 2), `mode 2/3/1 from here on` as set; request 64 (SE FO MX VOLUME CHANGE, idx 769) in mode 2
  took `4804020002002040` and the PCM was 100% 700 Hz, request 675 (idx 1030) in mode 3 took mode 3's (91% 1100 Hz),
  request 1180 in mode 1 played the game's own (no tone).
- Each slot's record goes into its own folder's image.bin (`audio` the game's, `audio_spike_menu` the system's).
  Fallout's game music is mostly in its 137 music-bank songs (`music_catNN_NNNN`): PAD-1358 (below) gives them mode
  files too.
Tests: tests/test_pad1324_spike3_music_modes.py.

**Transformers LE 0.96 (PAD-1359)**, the same way on Spike 3 slot 251 (2026-11-17, hidden, muted, the PCM kept): its
14 stereo idx sounds of 20 s or more given the two tones (28 records, its program grown into game.pad). The runtime armed
`28 record(s) over 3 mode(s)` with the setting at the program's own address (0xa8c120) and sound_lookup at the port's
0x51fe30; Adjustments > Machine Settings (its third row, after Pricing) listed Audio Content with Music Mode first, read
back 2, 3, 1 as set and said `mode 2/3/1 from here on`; request 481 (idx0034) in mode 2 took mode 2's record and the
PCM was 100% 700 Hz, request 477 (idx2440) in mode 3 100% 1100 Hz, request 478 (idx3945) in mode 1 the game's own
song (no swap, no tone). Its extract had had no request map: its request table (1545 requests, 32-byte records, the
list at +16) reaches 66% of its 4945 sound ids, under the 90% `spike3_requests` held a table to (every other Spike 3
card reaches 96-100%, and no other registry table on any reaches 2%). Walking Dead Remastered LE 0.92 had none either:
its 817 requests reach 17% of its 7836 sound ids, yet 746 of them name a recording. The table is now the one reaching
the most sound ids, taken at half of them, or at a tenth when it reaches three times any other registry table: all
eight Spike 3 cards in the library map (Transformers 1490 of 1545, Walking Dead Remastered 746 of 817, the rest as before).
Tests: tests/test_pad1359_transformers_music_modes.py.

## Music modes for bank songs (PAD-1358)

Fallout LE 0.82 keeps most of its game music in 137 songs in 81 music banks (`image-scNN.bin` beside image.bin, decoded
as `music_catNN_NNNN.wav`, NNNN the record's index in bank NN). Read off the card:

- **A bank is a container of image.bin's own format** (count at 0x60, directory at 0x40, trailer at 0x38) whose
  header's 0x20 is 0, but it has a **descriptor table of its own**: `0x58`'s high word is its sound-id count, the
  pointers start at 0x80 and the descriptors sit just before the directory, each naming its records by key with the
  op-11 marker as image.bin's do (bank 41: sid 0 plays records 1 then 2, sid 1 records 3 then 0). No image.bin
  descriptor and no program byte names a bank key.
- **A request plays a bank song as sound id `NN << 16 | n`**: Fallout's request table lists 112 such ids
  (request 65 = bank 1's sid 0, 66 = bank 2's, 75 = bank 10's, 110 / 112 = bank 41's sid 0 / 1). That is why
  sound_requests.tsv's idx column is empty for them.
- **A bank record's key carries its bank**: the params' low 12 bits are `NN << 2` (+ a part number in bits 0-1):
  bank 02's one song is `0x82600008`, bank 41's `0x006000a4 / 0x826000a4 / 0xc01000a4 / 0xc20000a4`. No key is shared
  between containers.

So a bank song's mode files are records appended to **its own bank** (the Write's grow, PAD-1185's road for an
edited bank song; Try it's `games.patch` tail), keyed with `free_key(..., like=<every bank's records>,
keep=BANK_KEEP)`: the bits the card's bank keys vary (20-31), never the bank's number (a one-song bank varies none
of its own). The same `mswap` lines swap them at `sound_lookup`; the runtime is unchanged. `sound_modes.offer` now
offers a `music_catNN_NNNN` slot on a Spike 3 title (`slot_ok`); on Spike 2 too since PAD-1378, by another road
(extra_sound_banks.md, "Music modes for the game's own bank songs"). The record lines say `<bank>:<record>` for
such a file.

Proof (2026-11-17, Spike 3 rig slot 58, hidden and MUTED, `PAD_S3_AUDIO_OUT=1`; Fallout LE 0.82 from the library,
staged as Try it does, with sound_fire_mode.c beside the runtime): a project giving bank 02's song
(`music_cat02_0000`) and one of bank 41's a 700 Hz tone for mode 2 and an 1100 Hz one for mode 3:
- the runtime armed `5 record(s) over 3 mode(s)`; MUSIC MODE set to 2 on Audio Content; request 66 (bank 02's
  song) logged `record 4604020008006082 plays mode 2's, 4604020008007082` and the PCM after it was 100% 700 Hz;
  set to 3, its next lookup took mode 3's `...4082`; back in mode 1 request 66 played the game's own song (no tone).
- a second run with bank 41's record 1 given the files (sid 0's first part, what request 110 plays): in mode 2
  request 110 logged `record 46040200a4006082 plays mode 2's, 46040200a4007082`, the PCM 100% 700 Hz for the
  file's 5 s, then the song's second record (`0xc01000a4`, which sid 0 plays after it) on as the card has it - a
  file replaces the one record, as an idx part does; in mode 3 request 66 took `...4082`, 100% 1100 Hz; in mode 1
  request 110 played the game's own song.
- The Write's grow of the same banks (`plan_sounds` against the card): image-sc02.bin 1 -> 3 records, image-sc41.bin
  4 -> 6, each directory's CRC right, the new records keyed `...7082` / `...4082` and holding their tones.
Tests: tests/test_pad1358_spike3_bank_song_modes.py.

## Spare switch inputs and driver outputs on Spike 3 (PAD-1329)

PAD-826's spare I/O read the switch service's struct, its entries and the coil table at 32-bit offsets, and the Spike 3
ports had no node-bus fire or OFF. The same three pieces are in every 64-bit program; Star Wars ELG 1.10's addresses:

| piece | Spike 2 (ELG 1.10) | Spike 3 (ELG 1.10) |
|---|---|---|
| fire-by-address `coil_frame` (node, spec) | 0x4669ac: tail call of 0x46680c(node, spec, 0, 0) | 0x5151d0: `mov x3,#0; mov w2,#0; b 0x514fb0`, the builder refuses a coil above 8 (15 on Fallout LE, Transformers LE) |
| the board's OFF `coil_off` (node, coil) | 0x462a98 | 0x50ee60: `8n 02 4d <coil>` through the sender 0x50d330 |
| the switch service (node, bits[8]) | 0x36fa28, struct 0x601cc4 | 0x308a10, struct 0x7477e0 (+0 the entries' pointer, +8 the flags', +0x20 its mutex) |
| a switch entry | 32 bytes: +18 bit, +20 board, +24 level | 48 bytes: +16 descriptor, +24 device, +32 id, +34 bit, +36 board, +40 level |
| a node block | struct + 16 + node * 160: +12 previous, +20 current bits, +28 u16 id per bit | a table of its own, `data sw_blocks` (struct + 0x298 on all seven), node * 176: +16 its entry list, +24 previous, +32 current, +40 ids, +168 queued |

- **The runtime** (pad_mode_runtime.c) reads them with that layout on 64-bit ARM (SW_CUR, SW_IDS, SW_ENT ... under
  `#if PM_A64`), pointers 8 bytes; Spike 2's object reads what it always did. Spare inputs arm on 64-bit only with
  `sw_blocks`. A fire the node bus did not take answers 0 there and is refused ("board N is not on the bus"):
  Fallout LE's coil records on board 0 are the CPU board's own outputs, no node's.
- **The runtime's memory table** (maps_line): back-to-back mappings of one kind are one entry, and it keeps 4096.
  Fallout LE's process under the Spike 3 emulator has more than 1024 mappings; the heap holding its switch entries was
  past the end, so its struct "did not check out (110 of 110)". Any reader of that heap had the same blind spot.
- **The ports**: all seven carry `site coil_frame`, `site coil_off`, `data sw_struct`, `data sw_blocks`, read off each
  program by hand from the shapes above and checked against its words (tests/test_pad1329_spike3_spare_io.py, with
  PAD_S3_PROGRAMS). s3port.py does not draft them yet: a new Spike 3 title's port gets them the same way.
- **The rig**: `PROOF=spare` (play.sh) closes the input spare_sweep_mode.c names with `s3press.py set` twice;
  s3proof.sh keeps the bus trace (PAD_S3_NBTRACE=1). The sweep pulses the first spare output of every driver board on
  the first close, and on the second holds it (200/30 ms then 60/3000 ms) and lets go a second later (the OFF).

Proof (2026-11-16, Spike 3 rig slots 97-99, hidden, muted, this build's runtime): on all seven titles the struct
checked out (69-110 switches, each its entry's) and the spare input closed on the board came as the mode's shot twice.
Star Wars ELG has no spare output (one driver board, node 8, outputs 0-8 all the game's): spare inputs only
(mode_project.SPARE_NO_OUTPUTS). On the other six every spare output the sweep drove (Fallout 9:1; Pokemon 1:1 9:1 10:0
13:1; Star Wars 2025 LE 1:1 8:6 9:0 13:0, Pro 1:1 8:6 9:5; Transformers 1:1 9:0 13:1; Walking Dead Remastered 1:1)
was on the bus as the pulse (`nN 40 0O c8 03 ..`), the held command (`.. 3c 2c 01`) and its OFF (`nN 4d 0O`), and the
game had sent none of them anything. Tests: tests/test_pad1329_spike3_spare_io.py.

## Attract items on Spike 3 (PAD-1328, round 1)

**The table.** `s3port.attract_sequencer` reads the attract sequencer the 64-bit way: the call that makes a page a
child process (`ldr x0, [xE, #8] ; mov w1, #0 ; bl <child create> ; cbz x0 ; str wC, [x0, #0x108]`, a one-frame
`proc_sleep` after), the entry's test called through `blr x1` in the function or a helper of it, and the table base
the address with the longest run of {test 0 or code, page code} entries (RELATIVE relocations: the file holds 0).
Found on five of the seven titles and appended to their ports (`attract_lines`, also run by `draft_spike3`, which
first drops whatever the matcher carried of a reference's attract lines):

| title | table | entries | entry |
|---|---|---|---|
| Star Wars ELG 1.10 | 0x6a45c0 | 28 (a mod-28 step in its next-entry helper 0x138080) | 16 {test, page} |
| Walking Dead Remastered LE 0.92 | 0x7b5c38 | 48 | 16 |
| Star Wars 2025 LE 0.96 | 0x8b7a98 | 183 (`cmp w21, #0xb6`) | 16 |
| Star Wars 2025 Pro 0.84 | 0x754a50 | 126 | 16 |
| Pokemon LE 0.82 | 0x3198290 | 10 (to the first empty entry) | 24 {test, page, float seconds} |

Fallout LE 0.82 and Transformers LE 0.96 run attract from a director with its pages coded inline (Transformers
0x2e8590): no table, `title_refusal` says so. ELG's pages read on the Attract tab (`attract_items._read_pages_a64`,
names from the strings each page makes by adrp/add): Credits, the two Insider overlays, Attract Background Loop 1-6,
Star Wars Logo, twelve high-score / champion pages (stubs into 0x13cee0), two clip pages (0x138330). Every table is
in writable `.data`, so the runtime points an entry's page at its own as on Spike 2 (`pm_addr` slots, `pm_reg` page
and test arguments, 24/32-byte entries allowed).

**The show, and why it is gated.** ELG's own clip pages (0x138330) put the video bank on the glass themselves each
frame: `surface_set_video` / `surface_play` on the bank scene's VideoSurface, then `player_advance(player, ms)`
(0x1b4a70) ; `scene_show(player, 3)` (0x1b4aa0) ; the frame yield 0x315f80. The same pair is on WDR and both Star Wars
2025 builds (`site attract_show` / `player_advance` in their ports). The attract player (`*0x70fc58`, the one the
sequencer keeps) IS the bank's scene player. Emulator runs (Spike 3 rig slots 1/2, hidden, muted, C:/tmp/PAD-1328
run_att.sh: a Try it set from `spike3_modes.plan` with one photo item after entry 10, its clip PadAttract1 added to the
bank and staged by games.patch):
- the runtime armed it (`table 0x...a445c0, 28 entries of 16 bytes ... the process sleep 0x...315000`), the item
  page ran after Star Wars Logo and the clip reached the decoder (s3vid opened 655.asset);
- with the show, the item's page never came back from `scene_show` - any layer (3 or 0), our clip or the game's own
  (`trench`), the clip started from the tick or from the page process itself - and ~10 s on the game ended itself:
  `exit 5 = DISPATCH TIMEOUT`. The page process passes scene_show's own check (flags 0x0804 has 0x4); the hang is
  inside the manager's show (0x2d6a30, which locks the manager's mutex at +0x10 the first time a player goes on a
  layer);
- with `player_advance` alone, or nothing, the item runs its 8 s and the game plays on, but the glass keeps the
  logo: the bank's scene is not drawn in attract by itself;
- calling the game's own clip page (0x138330) from the item's page, its clip list's next name (0x6a4780[idx], idx at
  0x70fc70) pointed at the item's clip, does not hang, but it ends its play loop at once (~0.6 s, then its own
  125-frame pause), for the game's own `trench` as for ours: the surface is not "playing" (state 2) at its first
  check in this emulator.
So PAD-1328 turned attract items off on 64-bit (`title_refusal` NO_GLASS on every Spike 3 title).

**Round 2 (PAD-1371): the stall was ours.** s3run.sh's `PAD_S3_GDB=PORT` (with `PAD_S3_QEMU`, the patched qemu) makes
the game's own qemu wait for gdb in the run's network namespace (`nsenter -t <qemu pid> -n gdb-multiarch`; rig script
C:/tmp/PAD-1371/run_gdb.sh). Stopped 3 s into the item, the page's thread had taken SIGSEGV at `0x00000000eac5baa0`:
the game's scene_show 0x1b4aa0 at its load base 0x7bb2eaaa7000 (0x7bb2eac5baa0) cut to its low 32 bits. The runtime
kept `attract_show`'s address in `static unsigned ait_show_fn` (4 bytes on aarch64), the jump went into nothing, and
the game's fault handling held the dispatch thread until its watchdog ended the run (exit 5). Nothing in the manager's
show (0x2d6a30: one plain mutex at +0x10, a list hook) waits. `ait_show_fn` is a `pm_addr` now, and so is every other
local or static that held a `fn()` / `data()` address in an `unsigned` among the names a Spike 3 port carries
(`challenge_scores_count` in coop_awards_arm) and the Spike 2 stock-mode ones beside them (the 32-bit object is byte
for byte the same: `pm_addr` is `unsigned` there). The game's own clip page "ending at once" was the PAD-1328
experiment's side effect: with the fix the game's clip pages after an item play their film as before.

The runtime's 64-bit gate is now only "no way to show the bank's scene from a page" (no attract video element and no
`attract_show` / `scene_show` + `player_advance`), and `title_refusal` treats a Spike 3 title like a Spike 2 one: Star
Wars ELG 1.10 takes items; the other four titles with a table have no clip route yet (NO_CLIPS).

Proof (2026-11-17, Spike 3 rig slots 1/3, hidden and MUTED, the library's ELG 1.10 card, the set `spike3_modes.plan`
built from a project with one photo item after screen 11 (the pinned prebuilt/mode64.so, game.port, attract.cfg, the
clip in the bank by games.patch); C:/tmp/PAD-1371 run_item.sh): `item 1 ("PadAttract1", 8000 ms) after entry 10's
page`, the marker on the glass at 2 s and 5 s, `is over after 8017 ms`, then the game's own attract (its clip page and
the opening crawl) on to the run's cap with no DISPATCH TIMEOUT.
Tests: tests/test_pad1328_spike3_attract.py.

## Expression light shows on Spike 3 (PAD-1328: what the next round builds)

The census (2026-11-16, `s3port.lamp_devices` on each program): six titles have cabinet lights under Spike 3's own
names, which `lampmap.cabinet_role` (Spike 2's `EXPRESSIVE LIGHTING L n` / `SPEAKER n`) does not match yet:
`SPEAKER L 1-R` / `-G` / `-B` .. and `SPEAKER R ..` (one lamp per colour channel, a ring each side), `CABINET L-IN
UPPER` / `L-IN LOWER` / `R-IN ..` / `L-OUT` / `R-OUT` (the side strips) on Fallout, Pokemon, Transformers and WDR,
`EXPRESSION LIGHTING L` / `R` on Star Wars 2025 LE; Star Wars ELG has none. What is there already: the 64-bit lamp
layer and the per-light setter's light table (16-byte records {u16 list, kind}, `s3port.light_lists`), the lamp
lines' light ids by device name (`light_engine`), `cab_voice_count` reads the channel's voice pointers pointer-sized
(`PM_PTR`). To build: (1) the names in `cabinet_role` and `cablamp` lines drafted off the 64-bit device and light
tables (each pixel's three channel lamps folded into one `R,G,B` line); (2) the voice's played-sample offset measured
on 64-bit (`value sound_voice_played`, 12 on Spike 2); (3) `spike3_modes` carrying `cabshow.cfg` with the song's
sound ids read off the 64-bit program, and the engine's family line for it dropped; (4) a rig proof read off the node
bus (`PAD_NB_TRACE`: the speaker panel sends no lamp frames in attract on any title, docs/plans/spike3_emulation.md).

**Round 2 (PAD-1328).** Done: `lampmap.cabinet_role` knows Spike 3's names (`EXPRESSION LIGHTING L/R n` blades,
`CABINET L/R-IN UPPER|LOWER|OUT n` strips, `SPEAKER L/R n` rings) and `cabinet_strip` / `place_cabinet` give each of
a Spike 3 cabinet's strips its own run (inner x 22 / 278, outer x 4 / 296, numbered from the top down);
`s3port.cabinet_lines_a64` drafts the `cablamp` lines off the 64-bit tables: on the six newer titles each colour
channel is a lamp of the device table and a light's id is its rank among the lamps + 1 (every 3-light record of the
light table names one fixture's -R/-G/-B that way: Fallout 316/316, SW2025 LE 345/345, WDR 259/259, Pokemon 381/381,
SW2025 Pro 158/158; Transformers 241 of 261, its cabinet all among them). Six ports carry them: Fallout, Pokemon,
Transformers and WDR 184 pixels (six 24-pixel strips, two 20-pixel rings), Star Wars 2025 LE / Pro 136 (two
48-pixel blades, the rings). The runtime's cabinet range is 192 (N_CAB, was 160).

Rig (Fallout LE 0.82, slot 1, hidden, muted, C:/tmp/PAD-1328/cab run_cab.sh: cabshow.cfg `only` with a show on the
two main-play songs, sids 65536 / 131072): `expression lights: 1 show(s) of the card's over 184 cabinet light(s)`,
`show "PROOF" plays with sound 65536 and the others that start it (2 request(s))`, at the song's request (119.5 s)
the show started, our layer on top (priority 255) over all 184 lights, handed back at its end and started again with
the song. Not yet seen: the light itself. The rig's strip boards (node 2 cabinet, node 7 speakers: ws2812node, both
claimed) get from the game only `f2` reads at boot, `46 ff 01` / `48 00 00`, one walking-zero `72` channel mask, and
then the `ff` status poll once a second (answered `2d 00 ...`) - never a lamp frame, for the game's own shows as for
ours (PAD_S3_NBTRACE=1, nbtrace.log). Fallout's AD_CABINET_EXPRESSION_HARDWARE / AD_SPEAKER_EXPRESSION_HARDWARE
default to 1 (present), so the game most likely judges the emulated boards to have no strips from their answers.
Next: what the game reads in those answers (the `ff` status and the `f2` reads; the ws2812node firmware is on the
card) so the rig's strip boards take lamp frames; then the proof on padled's node 2 / 7 hi plane, the song timing
(`value sound_voice_played`: the show did not lock to the voice at 12, it ran on its own clock), the app's Spike 3
side (spike3_modes carrying cabshow.cfg and the Expression lights tab's layout from the port), and the family line.

**PAD-1370: the strips were never the node bus's.** The game sends nodes 2 / 7 (and Fallout's topper, 14) only their
bring-up there; every lamp frame for them goes to the netbridge's own WS2812 outputs as host cmd `2f` ([channel] [n]
[the node frame's cmd + body]), channel 0 = node 7, 1 = node 14, 2 = node 2 (docs/plans/spike3_emulation.md, "The
cabinet strips are the netbridge's"). s3bridge now feeds them to padled, so the rig's strips light. Left for the
shows: the song timing, the app's Spike 3 side and the family line above.
