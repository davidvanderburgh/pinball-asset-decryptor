# Every parameter a mode has

"What are all the parameters we have access to?" This file answers that in one place,
read off the code, with what has been MEASURED about each one. A mode has three layers:

1. **`mode.json`**, what the Modes tab saves in the card project (`ModeSpec` in
   `pinball_decryptor/plugins/stern/mode_project.py`). A person picks shots by name.
2. **The runtime mode file** (`mode.cfg`, `mode1.cfg` .. `mode7.cfg`), which the build
   generates from `mode.json` and `mode_file.c` reads inside the game. Shots are masks here.
3. **The SDK calls** in `pad_mode.h`, which `mode_file.c` and any mode written in C use.

"Measured" means emulator-proven on Godzilla Pro 1.15 unless it says otherwise, by the
item named (its entry in `plans/TODO.md`, and `MODE_API.md` / `MODE_SDK.md` for detail).
"Desk" means proven only by the item 141 host harness (`mode_file.c` compiled on the PC
against stub calls). "Not measured" means no run has exercised it.

## 1. The runtime mode file (`mode_file.c`)

**Format.** One key per line, then its value. `#` starts a comment line; blank lines are
skipped. Numbers are decimal or `0x` hex. A text value runs to the end of the line
(trailing spaces dropped). A key given twice keeps the last value, except the repeatable
ones. **An unknown key is logged (`unknown key, skipped: ...`) and skipped**, so a newer
editor never breaks an older `mode.so`. A mode is armed only with `seconds` and a trigger
count (`loaded ... - NOT VALID, it needs seconds and a trigger count` otherwise), or, with
`starts_on event`, `seconds` and an event the port names (item 147).

**Limits** (the `#define`s at the top of `mode_file.c`):

| Limit | Value | What happens past it |
|---|---|---|
| `CFG_MAX` | 4096 bytes per file | the rest of the file is not read |
| a line | `STR_MAX` + 64 = 288 bytes (287 characters) | the rest of the line is dropped |
| `STR_MAX` | 224 (223 characters) | `title_words`, `total_words`, `light_on`, `light_off` are cut |
| `CALLOUT_AT_MAX` | 8 `callout_at` lines | later ones are ignored, silently |
| `SHOT_AWARD_MAX` | 16 `shot_award` lines | later ones are ignored, with a log line |
| `MODES_MAX` | 8 slots | `mode.cfg`, `mode1.cfg` .. `mode7.cfg` |
| `TICKS_PER_S` | 60 | the clock every time value runs on |
| `POLL_TICKS` | 30 | files and trigger files are checked twice a second |
| `CLIP_AFTER_SHOT_TICKS` | 30 | a clip a shot starts (trigger shot, end shot) waits this long, then plays from the tick (item 141) |

Other text fields: `name` 63 characters, `screen_scene` 47, `screen_node` 95,
`screen_text` 127, `clip_start` / `clip_end` 95. Masks and points are 64-bit; every other
number is 32-bit.

### The keys

"Tab" is what the Modes tab writes for it (section > control), or "no" when nothing in the
app generates it.

| Key | Value | Absent | What it does | Tab | Measured |
|---|---|---|---|---|---|
| `name` | text | "" | the mode's name in every log line | Mode > Name | item 126 (a rewrite mid-game renamed the next start) |
| `trigger` | `<bits> <count>` | 0 0: not valid | starts the mode when one player makes `count` shots in `bits` in one ball. Counts are per player, zeroed at the mode's start and at every end of ball. Bits 0 = only a start file starts it | Mode > Starts on, times in one ball | items 125, 126, 133 (its own trigger), 134 (refused while another mode runs) |
| `seconds` | seconds | 0: not valid | how long it runs, on the 60 Hz tick | Mode > Runs for | items 125 (30 s), 126 (ended at 11,984 ms of 12 s), 134 (20.09 s) |
| `shots` | bits | 0 | the shots that score while it runs | Shots that score | items 125, 131-134 |
| `award` | points | 0 | what a scoring shot pays: the Nth pays N x this (see `award_ladder`) | Mode > First shot pays | items 125-134 (+1M, +2M); 133 (+18M = 2 x 9M after a reload) |
| `shot_award` | `<bits> <points>`, repeatable (16) | none | the shots in `bits` pay `points` instead of `award`, and score even when they are not in `shots`. The first matching line wins. The ladder still applies | Advanced > Points per shot | item 141 runs 1, 2: Building +10M (5M x 2), Godzilla target +9M (3M x 3), Shield target left +10M (2M x 5, not in `shots`) |
| `end_shot` | bits | 0 | a shot in `bits` ends the mode. It scores first if it is a scoring shot, and no shot after it pays; the mode ends on the next tick: `END (end shot)`, `clip_end` 500 ms later from the tick, no time-up callout | Advanced > Ends early when hit | item 141 runs 1-3: Shield target left +10M, then `END (end shot)` 16 ms later (the next tick), with the second clip. Run 3: Shield target left and Building pressed together reached the mode Building first (+5M, then Shield +4M, `END`, 2 shots); a scoring shot AFTER the end shot in one frame paying nothing is desk only (`endpay.script`) |
| `award_ladder` | `fixed` or `rising` | rising | rising: the Nth scoring shot pays N x its value (what every file before item 141 does). fixed: every shot pays its value once. Anything else logs and means rising | Advanced > Award ladder | item 141 runs 1, 2: rising +1M, +10M, +9M, +4M, +10M; fixed 1M, 1M, 5M |
| `screen_type` | number | 0 | the game's award-screen family for the borrowed-message screen (122 on Godzilla) | no | item 125 run 5. Superseded by own screens (item 131) |
| `title_msg` | message id | 0 | a stock message whose words are replaced by `title_words` at the start, and the award screen each shot shows. Used only without `screen_node` | no | item 125 run 5 |
| `total_msg` | message id | 0 | the same for `total_words` and the end total | no | item 125 run 5 |
| `title_words` | text | "" | words put behind `title_msg` | no | item 125 run 5 |
| `total_words` | text | "" | words put behind `total_msg` | no | item 125 run 5 |
| `restore_after` | seconds | 0 | own screen: how long it stays up after the end (0 means 4). Borrowed messages: when they are given back (0 means never) | Advanced > Screen stays up N s (6 before item 141) | item 131 (screen hidden `restore_after` s after the end); item 141 run 2: `restore_after 8` hid it 8,016 ms after `END` |
| `light_owner` | owner id | 0: the port's | the rule a light command runs as (538 on Godzilla) | Lights on: the title's owner | item 125 run 14 |
| `light_on` | a light command | "" | runs at the start, under a live show event | Lights > Colour, or Lights > Advanced > On command | item 125 run 14 (lamps 413-420, the ones tesla strike's own award writes) |
| `light_off` | a light command | "" | runs at the end | Lights > Advanced > Off command | item 125 run 14 |
| `callout_at` | `<seconds left> <id>`, repeatable (8) | none | plays callout `id` when the seconds left reach that number. Never fires at exactly `seconds`; 0 fires in the last tick, with the end | Sound > Count down (`10 <ten seconds>`), and Advanced > Callouts at chosen seconds | item 125 (the countdown's call at 10 s). Item 141 runs 1, 2: `callout 1291 at 30 s left` and `callout 1295 at 20 s left` 15,065 and 25,065 ms after a 45 s start, `callout 1291 at 8 s left` in a 15 s mode (the rig is muted: the call is logged, not heard) |
| `callout_count` | callout id | 0: none | at 5, 4, 3, 2, 1 s left plays that callout's variant 4..0 | Sound > Count down | variants 0..4 proven (MODE_SDK.md); others not measured |
| `callout_end` | callout id | 0: none | plays when time runs out (not on an end shot, a drain or `mode.stop`) | always, the title's time-up call | item 125 |
| `sound_key` | 16 hex digits | none | the container key of a sound appended to `image.bin` (item 130). With `sound_callout`, time up plays it instead of `callout_end` | Sound > My sound (after Write builds it) | item 130; the KAIJU RUSH card of items 128-129 |
| `sound_callout` | callout id | 0 | the stock callout that carries the own sound | with `sound_key` | item 130 |
| `screen_scene` | a scene role or 40-hex id | "": `hud` | where the own screen node lives | Screen on: the title's HUD scene | item 131 |
| `screen_node` | node path | "": no own screen | the mode's own screen, found and hidden at load, shown at the start, hidden after the end | Screen on: `PadMode_<folder>_Screen` | items 131, 134 |
| `screen_text` | text node path | "" | the words on it: "1,000,000 A SHOT", "+N" per shot, "TOTAL N" at the end. The words themselves are written by `mode_file.c` and are not a parameter (no key sets them; left for a later item) | Screen on: `..._Screen.PadMode_<folder>_Screen_Words` | items 131, 134 |
| `clip_start` | clip name | "" | a clip from the video bank, played full screen at the start | Clip > Plays when it starts (and Advanced > Second clip when the first plays at the end) | item 132 run 3, item 134; item 141: inside a trigger shot it lost the video surface (run 1), so it now waits 500 ms after the shot and plays from the tick (run 2: on the glass at +1, +2, +3 s) |
| `clip_end` | clip name | "" | a clip played at every end: time up, end shot, drain, `mode.stop`. One clip waits at a time and the newest wins: an end clip still waiting when the next mode's start clip is asked for is dropped (`dropped before it played`), and so is a start clip still waiting when its mode ends | Clip > Plays when it ends (and Advanced > Second clip) | item 141 runs 1-3: after an end shot (waiting 500 ms in runs 2 and 3) and after time ran out, on the glass. Run 3: an end shot's clip still waiting when the next mode started by trigger file logged `dropped before it played: a newer clip played at once`, and the new mode's clip was on the glass at +0.8 and +2 s. A drain not measured |
| `clip_label`, `clip_layer` | anything | | accepted and ignored: the SDK plays clips with the Normal crop on layer 0 (layer 1 was measured to show nothing) | no | item 132 (layer 1 shows nothing) |
| `starts` | `once_per_game`, `once_per_ball`, `unlimited` or N (1-99 a game) | unlimited | how often the mode can start, counted per player when it starts; a ball's counts clear at every end of ball, a game's at a new game. A trigger file starts it anyway, uncounted. Anything else logs and means unlimited | How often it can start | item 139 (per player with two players; once a ball across a real end of ball; the new-game witness; MODE_SDK.md "How often a mode can start") |
| `cooldown` | seconds | 0: none | not again until this long after its END, wall clock, through an end of ball; a new game clears it | How often it can start > Wait N seconds | item 139 (`cooling down, 7 s left` on the next ball); cleared by a new game with time left: desk only |
| `stack` | `yes` or `no` (also `y`/`n`, `1`/`0`) | yes | `no`: the mode does not start while the game's own battle or multiball is active (`<name> not started (<why>): a battle is running`), keeps its trigger count, and the first start shot after the game's mode ends starts it. A trigger file does not bypass it. A port that cannot tell logs that once and starts it as `yes`. Anything else logs and means yes | The game's own modes > Can run during the game's own modes | item 140, Godzilla Pro 1.15 and Premium 1.16: refused during a battle and a Godzilla multiball, started by the next start shot once each ended (MODE_SDK.md "The game's own modes") |
| `starts_on` | `shot`, or `event <name> [N]` | shot | `event`: the mode starts on the N-th firing (1 when absent) of an event the port names, counted per player across a game and cleared by the port's `game_start`. The `trigger` line is ignored (`starts_on event: the trigger shots are ignored`) and the tab writes none, so a `mode.so` older than events logs the file NOT VALID instead of starting it on a shot. An event the port does not name leaves it NOT VALID. Fired with no game in play: retried for 3 s, then dropped. Anything else logs and means shot | Starts and ends > Starts on: Its shot / An event | item 147, Godzilla Pro 1.15 (run2b) and Premium 1.16 (run3c, run3d): `START (event ball_start)` in the same millisecond as the game's ball start; `START (event multiball_start)` on a forced godzilla multiball; Premium run3c: a multiball start with no game in play logged `still no game in play after 3 s`. A count N above 1 was not in any run's file (MODE_SDK.md "Events") |
| `ends_on` | `drain`, `clock` or `event <name>` | drain | `drain`: its clock or the end of the ball, as before the key. `clock`: its clock only; at the end of a ball it logs `the ball ended - running on (ends_on clock)`. `event`: that event, its clock or the end of the ball; an event the port does not name logs and means drain. Anything else logs and means drain | Starts and ends > Ends on: Its clock, or the ball draining / Its clock only / An event | item 147: `ends_on clock` ran through a drain and ended `time ran out` (Pro 1.15 run2b, 60,773 ms); `END (event multiball_end)` on Pro 1.15 when the game stopped the multiball at the end of its ball, and on Premium 1.16 when the probe called the stop function (run3d) |
| `roster_slot` | a slot 0-6 of Godzilla's battle roster (0 Ebirah, 1 Titanosaurus, 2 Gigan, 3 Megalon, 4 King Ghidorah, 5 Megalon & Gigan, 6 King Ghidorah & Gigan) | none | the mode takes that slot's place on the BATTLE SELECTION screen: picking the slot starts the mode (after the port's `roster_start_after_ms`) and the game's battle for it never starts; the mode's end lights the ramps again. The file needs `seconds` but no trigger. A pick while it runs is taken and restarts nothing; a pick while another of our modes runs starts it when that one ends; a pick it cannot start, or a ball ending first, gives the pick back. A number above 15, `-1` or a word logs and claims nothing. The slot's name and art on the screen are a card edit (`roster_entry.py`), not this key. A port with no roster logs `NOT claimed` | no | item 146, Godzilla Pro 1.15 (runs 3, 4, 6; run6 with the runtime's hook alone) and Premium 1.16 (run5): `MOTHRA START (roster pick)` about 3,000 ms after the pick, `battle over for player 1` at its end, a stock slot still started the game's battle. Pick while it runs, pick while KAIJU RUSH runs, two players: run4. Cannot start, ball ends first, a pick lapsing: desk only (MODE_SDK.md "A monster in the roster") |
| `roster_callout` | a sound request id 0-65535 | the claimed slot is silent | what the selection screen plays when the cursor lands on the held slot (the game's own is the old monster's name, which a claim silences). Re-applied when the file is reloaded; removing the file puts the game's id back. Anything else logs and leaves the slot silent | no | item 146 run6, Pro 1.15: the slot table's id read back 1888 -> 0 at the claim, 207 after `roster_callout 207`, 1888 when the file was removed (`PAD_PEEK`). Premium 1.16 run7 and Pro 1.15 run8: the same three reads. Not heard (the rig is muted) |
| `sound_start` | `<request> [ms]` | 0: none | plays a CARRIER request (a stock request the game never plays, re-pointed by the build at a sound of the mode's own, `mode_sounds.py`) when the mode starts, at voice-bus priority 4, WITHOUT the steal flag (item 150 follow-up: nothing cuts it while it sounds). The game's lower-priority speech on the voice bus is faded out first (60 ms) and the call plays 70 ms later; held off by an equal or higher one it waits up to 1.5 s, then logs `NOT played`. `ms` is the sound's own length: the carrier is faded out (40 ms) and stopped once `ms` + 1/8 + 120 ms have passed, so the silence after a sound shorter than the carrier's record does not hold the bus | Sounds of its own > When it starts (Write builds the bank and picks the carrier, item 149) | item 150 RUN 5 / 7, Godzilla Pro 1.15 and Premium 1.16: heard in the capture (corr 0.86-0.92), `1251 p4 f1 b02` in the channel dump. `ms`: see item 150's TODO entry (RUN 8) |
| `sound_shot` | `<request> [every] [ms]` | 0: none | plays a carrier on every scored shot, or every Nth, at priority 3 without the steal flag: skipped while its own previous call still sounds (`skipped - its previous call still sounds`), waits up to 0.8 s under the game's priority-3 speech, fades the game's ordinary speech first. `ms` as above | Sounds of its own > On a scoring shot, every N | item 150 RUN 5 run C, RUN 7A / 7B: three shot calls heard (corr 0.61-0.90); RUN 5 run B: shots under the game's 1997 (p3 f0) not played, as designed |
| `sound_end` | `<request> [ms]` | 0: none | plays a carrier when time runs out, INSTEAD of `callout_end`, at priority 4 without the steal flag (a shot call still sounding is faded out first, 60 ms). `ms` as above; the stop outlives the mode | Mode > When time is up: My sound | item 150 RUN 5 / 6 / 7: heard (corr 0.989) on both titles |
| `music` | `<request> [sid]` | 0: none | starts a music carrier with the mode on the music bus, clears its steal flag so the game's music cannot take the bus back, starts it again whenever no channel plays it. With a `sid` (item 150 follow-up) the carrier is pointed at that sound id while the mode runs (`pm_sound_sid`): the mode's OWN bed, which the build bound to a sid no request names. The game's music is faded out (250 ms) before it starts, any request of the game's music class (priority 1) playing during the mode is faded out, and at every end the music FADES (400 ms, `pm_sound_fade`), the carrier's own list is put back and the game's music that played at the start is played again. The build makes the WAV a seamless loop on the 10 ms grid, repeated so the record outlasts the mode (its `seconds` + 3, at most 150 s) | Sounds of its own > Music underneath | item 150 RUN 5 / 6 / 7: one serial on bus 0x01 START to END, 0 restarts, in phase with one loop, nothing after END; RUN 3 (steal flag kept): 11 restarts. Tiled music: see item 150's TODO entry (RUN 8) |
| `light` | `<shots> <colour> [pattern] [ms]`, up to 8 light lines in all | none | holds the inserts the port's `lamp` lines tie to these shot bits (MODE_SDK.md "Lights: named inserts") from the mode's START to its END, whatever ends it, in the colour and pattern given: `colour` is `rrggbb` (a `#` before it is fine) or red, green, blue, yellow, orange, purple, cyan, white, pink; `pattern` solid (the default), blink, pulse or chase; `ms` its period (0 or absent: blink 500, pulse 1600, chase 150 a step). Everything the mode does not hold keeps the game's own light shows. A line with no bits, no colour or an unknown pattern is logged and ignored; on a port without lamps the mode logs `lights: this game's port names no inserts` and lights nothing | no | item mode-leds RUN 5, Premium 1.16: the decoded node bus (MODE_SDK.md "Lights: named inserts") |
| `light_insert` | `<colour> <pattern> <ms> <name>[,<name>...]` | none | the same for inserts by the game's own name (a port `lamp` line's name, any case), several separated by commas; a chase runs across them in that order. An unknown name is logged and skipped | no | item mode-leds RUN 5 (a mode file lit both ramps, BIG LOOP and the powerlines, handed back at END) |
| `light_shots` | `<colour> [pattern] [ms]` | none | the AUTOMATIC form: every insert of every shot that scores in this mode (`shots` and each `shot_award`) is held while it runs, so a player sees what pays | On the playfield and the screen > Light the shots that score, its colour and Solid / Blink / Pulse / Chase (item 157) | item mode-leds RUN 5 (a mode file lit both ramps, BIG LOOP and the powerlines, handed back at END) |
| `light_priority` | 1-255 | 255 | the priority of the lamp layer the mode's inserts sit in (`pm_lamp_priority`): 255 is above every show the game ran in the runs measured (its highest was 145); lower, and a game show of a higher priority covers the mode's inserts while it lights them. Outside 1-255 logs and means 255 | no | item mode-leds RUN 5 (`prio 1` under a battle: MASER went to the game's own layer) |
| `priority` | 0-255, the game's display-effect scale | 0: none | while the mode runs it is, to the game's display arbitration, a display of this priority (`pm_display_priority` at the start, before the screen and the clip; given up at every end): the game's effects that do not beat it wait or are refused, its full-screen layered displays wait unless they are a mode start or total (counted as 184), its framed ones wait only while the mode's clip plays (since item 157 a layered display that would wait is dropped instead, on a port with `site layered_waiter`: a waiting one stopped the game's drawing for up to 8 s). Above 255 is 255; a word or a negative number logs and holds nothing. 180 is a mode's value (MODE_SDK.md "Display priority") | On the playfield and the screen > Display priority (item 157) | item 154 display, Premium 1.16 (runs r2, r3, r4, r6) and Pro 1.15 (r5): the start clip played through Big loop and Maser shots, no LOOPS or BATTLE IS LIT over the screen at 180, the tilt warning and a multiball start came through, what waited played at the release; desk: the harness in `tests/test_spike2_mode_display.py` |

### Files, slots and test triggers

| What | Where | Measured |
|---|---|---|
| slot 0 | `/usr/local/padmode/mode.cfg` (a card), then `/dump/mode.cfg` (the rig) | items 126, 128 |
| slots 1-7 | `modeK.cfg` in the same two places | item 133 |
| reload | each file is re-read twice a second and re-parsed when its bytes change; a running mode logs `reloaded while running - the new file is live` | items 126, 133 |
| a file that disappears | `mode file gone: slot K ("NAME") is not armed` | item 133 |
| `/dump/mode.start`, `/dump/modeK.start` | starts slot 0 / slot K (the file is deleted) | items 126, 133 |
| `/dump/mode.stop` | ends whichever mode runs: `END (trigger file)` | item 141 run 3 (`FIXED TEST END (trigger file)`) |
| `/dump/mode.clip` | `<name> [layer]` plays any clip in the bank; the layer is ignored | item 132 |

A mode also ends when the game leaves play or the player changes (`END (left the game, or
the player changed)`) and on the end of ball (`END (ball ended)`, items 125, 138). One of
our modes runs at a time: a start while another runs logs `<name> not started (<why>):
<other> is running` (items 133, 134).

## 2. `mode.json`: what the tab saves

Every `ModeSpec` field, its default, the control that edits it and the runtime lines it
becomes. A key a newer editor wrote is kept in `extra` and written back, never dropped.

| Field | Default | Tab | Becomes |
|---|---|---|---|
| `format` | 1 | | refused when newer than the app |
| `name` | "NEW MODE" | Mode > Name | `name` |
| `title` | `godzilla_pro_1_15` | | which `TitleProfile`: shot masks, callout ids, scenes |
| `start_shot` | "Maser target" | Mode > Starts on | `trigger` bits |
| `start_count` | 3 | Mode > times in one ball | `trigger` count |
| `seconds` | 30 | Mode > Runs for | `seconds` |
| `scoring_shots` | Left ramp, Right ramp | Shots that score | `shots` |
| `award` | 1000000 | Mode > First shot pays | `award` |
| `screen` | true | Screen > Show a screen | `screen_scene`, `screen_node`, `screen_text`, `restore_after` |
| `screen_title` | "" (the name) | Screen > Title | the panel art |
| `screen_art` | "" (a generated panel) | Screen > My picture | the panel art |
| `panel_color`, `title_color` | #146e28, #ffe600 | Screen > Panel, Title | the panel and title-card colours |
| `clip` | "none" | Clip > None / A title card / My video | `clip_start` or `clip_end` = `PadMode_<folder>_Clip` |
| `clip_title` | "" (the name) | Clip > Card title | the title card |
| `clip_file` | "" | Clip > My video | the converted clip |
| `clip_seconds` | 4.0 | Clip > seconds | the title card's length (1-30) |
| `clip_when` | "start" | Clip > Plays | which of `clip_start` / `clip_end` |
| `countdown` | true | Sound > Count down | `callout_at 10 <ten seconds>`, `callout_count` |
| `end_sound` | "" | Sound > My sound | `sound_key` + `sound_callout` once built; else `callout_end`; or `sound_end <carrier> <ms>` once carried (item 150) |
| `lights` | true | Lights > Sweep the playfield | `light_owner`, `light_on`, `light_off` |
| `light_color` | #00ff00 | Lights > Colour | the sweep command's colour |
| `light_on_raw`, `light_off_raw` | "" | Lights > Advanced | `light_on`, `light_off` verbatim |
| `award_ladder` | "rising" | Advanced > Award ladder | `award_ladder fixed` (nothing when rising) |
| `shot_award` | [] | Advanced > Points per shot (blank = the usual award) | `shot_award <bits> <points>` per row |
| `end_shot` | "" | Advanced > Ends early when hit | `end_shot <bits>` |
| `clip_both` | {} | Advanced > Second clip: none / the same clip / a title card / my video | the other end's `clip_start` / `clip_end`; a title card or video is built as `PadMode_<folder>_Clip2`. The same clip does not play again at the end while its start is still playing (item 141 run 3: FIXED TEST stopped 3 s into its 4 s clip; the clip ran on to its end, no second play, the HUD 1.2 to 2.5 s after `END`). A second clip of its own has its own name and plays |
| `callout_at` | [] | Advanced > Callouts at chosen seconds (seconds left, id, Pick) | `callout_at <seconds> <id>` per row, after the countdown's |
| `restore_after` | 6 | Advanced > Screen stays up | `restore_after` |
| `starts` | "unlimited" | How often it can start: once a game / once a ball / any number / up to N times a game | `starts <policy or N>` (nothing when unlimited) |
| `cooldown` | 0 | How often it can start > Wait N seconds | `cooldown <seconds>` (nothing when 0) |
| `stack` | true | The game's own modes > Can run during the game's own modes | `stack no` when off (nothing when on) |
| `clip_source`, `clip_from`, `clip_length` | "", 0.0, 0.0 | From a film > Clip... (item 142) | nothing in the runtime file: the film, the second the clip was cut at and its length (up to 30 s). The cut itself is `clip_file` |
| `sound_source`, `sound_from`, `sound_length` | "", 0.0, 0.0 | From a film > Sound... (item 142) | nothing: where the end sound was cut; the cut is `end_sound` |
| `art_source`, `art_from` | "", 0.0 | From a film > Picture... (item 142) | nothing: the film and the second of the frame; the frame is `screen_art` |
| `clip_crop`, `art_crop` | "" | the film dialog's letterbox / fill (item 142) | nothing: how the clip and the picture were cropped, so the dialog reopens on it |
| `starts_on` | "shot" | Starts and ends > Starts on: Its shot / An event (item 147) | `starts_on event <name>` in place of the `trigger` line (nothing when "shot"). `validate` names an event the title's `TitleProfile.events` does not carry |
| `ends_on` | "drain" | Starts and ends > Ends on: Its clock, or the ball draining / Its clock only / An event (item 147) | `ends_on clock` or `ends_on event <name>` (nothing when "drain") |
| `sound_start` | "" | Sounds of its own > When it starts (item 150) | `sound_start <carrier> <ms>`: Write picks the carrier, grows its record and writes the line (`runtime_cfg(own_sounds=, own_sound_ms=)`); nothing when this card cannot carry it |
| `sound_shot` | "" | Sounds of its own > On a scoring shot (item 150) | `sound_shot <carrier> <every> <ms>` on the carrier Write picked |
| `sound_shot_every` | 1 | Sounds of its own > every N scoring shot(s) (item 150) | the `every` of `sound_shot` |
| `music` | "" | Sounds of its own > Music underneath (item 150) | `music <carrier> <bed sid>`: every mode's music on a bed of its own (item 150 follow-up), made a seamless loop by the build (`mode_sounds.loop_wav`); `music <carrier>` on a title with no beds |
| `priority` | 0 | On the playfield and the screen > Display priority (item 157), 0-255; the tab suggests 180 | `priority <n>` (nothing when 0). `validate` names a value outside 0-255 |
| `light_shots` | "" (off) | On the playfield and the screen > Light the shots that score, and its colour (item 157) | `light_shots <rrggbb> <pattern>` (nothing when off). `validate` names a colour that is not `#rrggbb` |
| `light_shots_pattern` | "blink" | On the playfield and the screen > Solid / Blink / Pulse / Chase (item 157) | the pattern of `light_shots` (the pattern's own period: blink 500 ms, pulse 1600, chase 150 a step). `validate` names another word |
| `extra` | {} | | kept and written back |

The Advanced fields write nothing at their defaults, so a mode that never opens Advanced
generates the bytes it did before item 141 (KAIJU RUSH included).
`validate_parameters` names every bad value: an unknown shot, points below 1, a shot with
two amounts, more than 16 rows, a second clip with no first clip, a title card outside 1-30
seconds, a missing video, a callout at or past the mode's length, a callout id outside the
title's request table (`CALLOUT_REQUESTS`), more callouts than the runtime's 8 less the
countdown's one, `restore_after` outside 1-60 (only with the mode's own screen, the only time
it is written). A hand-edited value the Advanced section cannot show (an unknown ladder, end
shot or second clip, a shot name that is not text, a second amount for one shot, a callout
row that is not `[seconds, id]`) is named, kept and written back until its control is set.

**The callouts a person can pick by name** (`callout_choices`): only the ids measured to
play, per title. Godzilla Pro 1.15: 1291 "ten seconds left", 1295 "time is up" (item 125).
Any other id can be typed; what it says is not measured. The list is the measured ids only:
the port's countdown callout (1287 on Pro 1.15) is not offered, because the countdown plays it
as numbered variants and what a plain `pm_callout(1287)` says is not measured (the rig is
muted). **How many ids there are** is read
from the game ELF's sound request table (`sound_requests.locate_sound_requests`): Godzilla
Pro 1.15 has **2030** requests (ids 0-2029; item 141, on the stock 1.15 card, where request
1295 chains to sid 1998 as item 130 found, 1291 to five sids and the countdown's 1287 to ten).

## 3. The SDK calls (`pad_mode.h`)

A mode is a `struct pm_mode` registered with `PM_REGISTER`:

| Member | Called | Measured |
|---|---|---|
| `name` | log prefix `[name]` | item 134 |
| `init` | once, on the game's first tick (never from a constructor: that crashed the game at boot) | item 134 |
| `tick` | 60 times a second, on the game's scheduler thread | items 125, 134; thread logged every boot |
| `shot` | every shot dispatch, with the 64-bit mask | items 125, 134-138 (Godzilla: `0x1`, then the bit) |
| `ball_end` | the end-of-ball broadcast (event hook 0x34) | items 125, 138 (a drain on Deadpool Pro); a multiball drain or ball save is not measured |
| `event` | from the tick, within a tick of the game's own broadcast, once per firing of an event the port names, with its id (item 147) | item 147 on Godzilla Pro 1.15 and Premium 1.16 (`[pad] events: 11 of 11 named events armed, dispatch hooked`; `census_mode.c` and `mode_file.c` got game_start, ball_start, skill_shot, multiball_start and end, tilt_warning, tilt on both; on Pro also ball_end, bonus_start/end, game_over). MODE_SDK.md "Events" |

Capability flags, for `pm_can()`: `PM_CAN_CALLOUT`, `PM_CAN_LIGHTS`, `PM_CAN_SCREENS`,
`PM_CAN_CLIPS`, `PM_CAN_OWN_SOUND`, `PM_CAN_MESSAGES`, `PM_CAN_AWARD_SCREEN`, and
`PM_CAN_EVENTS` (item 147: set when at least one named event is armed), `PM_CAN_ROSTER`
(item 146: the port names the battle roster and its start is hooked), `PM_CAN_LAMPS` (item mode-leds:
the port has `lamp` lines and the game's lamp layer, and their light ids fit the game's), `PM_CAN_DISPLAY_PRIORITY` (item 154 display: the port names the display arbitration and it is hooked). A port that
lacks a function switches off only its own flag (the boot log's `armed: ... can ...` line).

Kinds, for `pm_stock_mode_running()` (item 140): `PM_STOCK_ANY`, `PM_STOCK_MULTIBALL`,
`PM_STOCK_BATTLE`.

The 68 calls. "Used by": T = `template_mode.c`, P = `examples/powerline_blitz.c`,
F = `mode_file.c`.

| Call | What | Used by | Measured |
|---|---|---|---|
| `pm_can(what)` | 1 if every flag is available | T P | item 134 (all flags on Godzilla Pro 1.15); items 136-138 (lights, screens, clips off on Jaws, TMNT, Deadpool) |
| `pm_game()` | the port's game | T P | items 134-138 |
| `pm_version()` | the port's version | T P | items 134-138 |
| `pm_in_game()` | a player is up and no `mode_mask_busy` bit is set | T P F | items 125-138; the busy bits are not fully decoded |
| `pm_player()` | 1-4, 0 with no game | T P F | items 125-138; one player only (no multi-player game measured) |
| `pm_score(player)` | a player's score | T P F | items 125, 134 (the END line's score before and after) |
| `pm_shot(name)` | a named shot's mask | T P | items 134-138 |
| `pm_shot_name(mask)` | the first named shot in a mask | T P | item 134 |
| `pm_shot_count()` | how many named shots | T | items 134-138 (template unchanged on each port) |
| `pm_shot_at(i, &mask)` | the i-th named shot | T | items 134-138 |
| `pm_begin()` | 1 = this mode is now the one running | T P F | items 133, 134 (refusals both ways) |
| `pm_end()` | this mode stopped | T P F | items 133, 134 |
| `pm_running()` | this mode is the one running | none | not measured |
| `pm_score_add(player, points)` | through the game's scoring and its multiplier; returns what was added | T P F | items 125-134; the multiplier's effect not measured separately |
| `pm_callout_id(role)` | `ten_seconds`, `countdown`, `time_up` from the port | T P | item 134; ids on Jaws read from its code (136); TMNT has none |
| `pm_callout(id)` | one of the game's own callouts; 0 does nothing | T P F | item 125 (1291, 1295); item 141 runs 1, 2 (each `callout_at` logged at its second; muted) |
| `pm_callout_nth(id, n)` | a numbered variant | T P F | variants 0..4 (item 125); others not measured |
| `pm_callout_own_sound(carrier, key)` | an appended sound through a stock carrier | F | item 130 (the countdown carrier); other carriers not measured |
| `pm_lights(command)` | a light command as the port's owner; 1 only under a live show | T P F | item 125 run 14 |
| `pm_lights_as(owner, command)` | the same with an owner id | F | item 125 run 14 (538) |
| `pm_scene_id(role)` | the port's scene id for a role | none | not measured |
| `pm_node(scene, path)` | a picture or group node, 0 until the scene loads | T P F | items 131, 134 |
| `pm_text(scene, path)` | a text node | T P F | items 131, 134 |
| `pm_show(node, on)` | show or hide (hiding always works; showing needs the timeline too) | T P F | items 131, 134 |
| `pm_set_text(text, words)` | write the words; only a CHANGE reaches the game (item 154 display), so it may be called every tick | T P F | items 131, 134; item 154 display r2: 1,500 calls in 25 s, the words on the glass changing (15.6 / 14.3 / 13.0 / 11.2 / 9.6 s); the change-only rule is a lifted desk test |
| `pm_clip(name)` | a bank clip, drawn every tick until it ends, or until the game plays a clip of its own (item 154 display) | T F | items 132, 134 (from the tick; on a Maser shot the game's own clip can take the surface); item 141 run 1 (played inside the Maser trigger shot: never on the glass) and run 2 (500 ms later from the tick: on the glass) |
| `pm_clip_playing()` | a clip of ours is still drawing | F | item 141 run 2: 1 after 1 s for both waiting clips, which were on the glass. It stays 1 while the surface plays ANY clip, so it cannot tell ours from the game's |
| `pm_clip_stop()` | stop it | none | not measured |
| `pm_message_set(id, words)` | borrowed message words | F | item 125 run 5 |
| `pm_message_restore(id)` | give them back | F | item 125 run 5 |
| `pm_award_screen(type, id, value)` | the game's award screen with a value | F | item 125 run 5 |
| `pm_port_text(name)` | a port `text` line | T P | item 134 (`example_clip`) |
| `pm_port_value(name, fallback)` | a port `value` line | none (the runtime uses it) | items 134-138, inside the runtime |
| `pm_log(fmt, ...)` | a line in `/dump/mode.log` | T P F | every item |
| `pm_ms()` | milliseconds since boot | F | item 126 (the END line's wall time) |
| `pm_trigger(name)` | 1 once when `/dump/<name>` appears | T P F | items 126, 133, 134 |
| `pm_read_file(path, buf, cap)` | a whole file | F | items 126, 133 |
| `pm_trigger_text(name, out, cap)` | the same, with its first line | P F | items 132 (`mode.clip`), 134 (POWERLINE BLITZ's shot trigger) |
| `pm_commas(out, cap, value)` | 1234567 -> "1,234,567" | T P F | items 131, 134 (the screen's words) |
| `pm_snprintf(out, cap, fmt, ...)` | formatting without libc stdio | T P F | items 126-134 |
| `pm_stock_mode_running(kinds)` | the first of the kinds asked for that the game has active (battle, then multiball, then any); 0 none; -1 this port cannot tell | F | item 140 on Godzilla Pro 1.15 and Premium 1.16: 0 in plain play, battle during a battle, multiball during a Godzilla multiball, 0 again once each ended (the port's any query answered 1 in both too); `PM_STOCK_ANY` is asked by no mode |
| `pm_stock_mode_what(kind)` | "a battle", "a multiball", "a stock mode" | F | item 140 (the `not started ... a battle is running` / `a multiball is running` lines) |
| `pm_event(name)` | the id of an event the port names and the runtime armed; -1 otherwise | F | item 147 on Godzilla Pro 1.15 and Premium 1.16 (`starts on event ball_start (id 37)` at load; the event starts and ends above) |
| `pm_event_name(id)` | the port's name for an event id, or 0 | `census_mode.c` | item 147 (census `event ball_start (0x25)`, `event skill_shot (0xd0)` on both builds) |
| `pm_roster_slots()` | how many battle roster slots the port names; 0 without a roster | none (the runtime's boot line) | item 146: `[pad] roster: 7 slots, the battle start at ... is hooked` on Pro 1.15 and Premium 1.16 |
| `pm_roster_claim(slot, on_pick)` | 1 = the mode holds the slot: when it is picked, `on_pick(slot)` runs on the game's thread; returning 1 skips the game's battle, 0 lets it run. The slot is made silent | F | item 146 runs 3-6 (Pro 1.15, Premium 1.16): `claimed - the game's battle does not start`; the unsigned bound (7, 3e9, -1 refused): desk, a lifted test |
| `pm_roster_release(slot)` | gives the slot back, with its callout id | F | item 146 run6: `roster slot 0 released`, the slot's callout id 1888 again |
| `pm_roster_done()` | the pick is over: the ramps light again, for the player who picked, and (with the port's `roster_city_*` lines) the pick counts as the battle of the player's city; waits while another player is up, nothing after the game; called at that ball's end if the mode never did | F | item 146 runs 3-6: `battle over for player 1`, the ramps qualified again and the selector reopened. The city: runs 7 (Premium 1.16) and 8 (Pro 1.15), `the pick counts as the battle of player 1's city 0 (its mask 0 -> 2)`, and in run8 a drained stock battle set the same bit. The waiting and after-the-game cases: desk only (lifted test) |
| `pm_roster_callout(slot, id)` | the sound the selection screen plays for a held slot; 0 = silent; 1 = written | F | item 146 run6 and run8 on Pro 1.15, run7 on Premium 1.16 (`PAD_PEEK` 0 -> 207); not heard (muted) |
| `pm_sound(request)` | plays a sound request through the port's `sound_play` (no city variant); 0 without the site | F | item 150 RUN 1 census and RUN 3-7, Godzilla Pro 1.15 and Premium 1.16 (every own call and the music) |
| `pm_sound_active(request)` | 1 while a channel plays it | F | item 150 RUN 1 (`active 84` 1 at 0.7, 51 and 63 s, 0 after the stop), RUN 3 |
| `pm_sound_stop(request)` | stops every channel playing it (0 = all); 1 if any stopped | F | item 150 RUN 1 (`STOP 84 rc 1`, then inactive), RUN 5-7 (the music at END) |
| `pm_sound_priority(request, priority, flags)` | sets a request's bus priority (-1 keeps it) and flags (bit 0: an equal priority may take the bus); returns the old priority << 8 or flags, -1 without the port's request table | F | item 150 RUN 4-7 on both titles: the dump shows `p4 f1` / `p3 f1` calls and `p1 f0` music |
| `pm_sound_sid(request, sid)` | points a request at ONE sound id (its sid list, +8 of its record, at a list of ours) until called with sid 0, which puts its own list back; 1 = done, 0 without the port's request table | F | item 150 follow-up X1 (Premium 1.16, attract): request 125 pointed at sid 618 played sid 618's stock record (corr 0.973 in the capture, 0.086 against 125's own), put back it played its own again (0.988). The bus and the loop are the SID's descriptor's: that effect sid played on bus 0x04, once - so the build rewrites a bed's descriptor as music (engine._music_template_writes) |
| `pm_sound_fade(request, ms)` | fades every channel playing the request down to -86 dB over `ms` (the codec's volume step on each voice, 1/3 dB a step), then stops it; 1 if one was playing; without the port's channel and voice offsets it stops at once | F | item 150 follow-up X1: 125 (music) faded over 500 ms and 1251 (a call) over 300 ms, the capture's 20 ms RMS falling smoothly from ~6000 / ~10000 to 0 and the channel stopped at the end (`vol 125: 7.0:0` at the start, `(none playing)` 534 / 349 ms later) |
| `pm_sound_playing(requests, buses, max)` | the request and bus bits of every channel playing now; how many play, -1 without the port's `data sound_channels` | F | desk; the same channel fields read by `sound_fire_mode.c`'s dump in X1 (`ch 7:125 p1 f1 b01`, `ch 7:1251 p2 f0 b02`) |
| `pm_lamp_count()` | how many inserts the port's `lamp` lines name; 0 without `PM_CAN_LAMPS` | `lamp_probe.c` | item mode-leds RUN 5: 88 on Premium 1.16 |
| `pm_lamp_at(i, &shots)` | the i-th insert's name and the shot bits the game ties to it | `lamp_probe.c` | desk (`tests/test_spike2_mode_lamps.py`) |
| `pm_lamp_find(name)` | an insert's index by name, any case; -1 | none | desk |
| `pm_lamp_set(names, rgb, pattern, ms)` | holds one insert or a comma-separated list in a colour (`PM_RGB(r, g, b)`) and a pattern (`PM_LAMP_SOLID`, `PM_LAMP_BLINK`, `PM_LAMP_PULSE`, `PM_LAMP_CHASE` across the list); returns how many it holds. Held inserts show that over the game's shows; everything else stays the game's | F `lamp_probe.c` | item mode-leds RUN 5 on Premium 1.16: the decoded node bus (MODE_SDK.md) |
| `pm_lamp_shot(shots, rgb, pattern, ms)` | the same for every insert the port ties to these shot bits | F `lamp_probe.c` | item mode-leds RUN 5 |
| `pm_lamp_release(names)` | hands inserts the calling mode holds back to the game at once; how many | `lamp_probe.c` | item mode-leds RUN 5 |
| `pm_lamp_release_shot(shots)` | the same for a shot's inserts | none | desk |
| `pm_lamp_release_all()` | every insert the calling mode holds | F `lamp_probe.c` | item mode-leds RUN 5 |
| `pm_lamp_priority(p)` | the calling mode's lamp layer priority, 1-255 (255 when never called); its held inserts move to that layer | F `lamp_probe.c` | item mode-leds RUN 5 (`prio 1` put the game's own layer back on MASER in a battle) |
| `pm_lamp_layers(prio, max)` | the game's lamp layers now, bottom to top, 0x100 added for ours; -1 without the port's layer list | `lamp_probe.c` | item mode-leds RUN 5 (the layer lists in MODE_SDK.md) |
| `pm_display_priority(priority)` | the running mode becomes, to the game's display arbitration, a display of `priority` (1-255); 0 gives it up. 1 = held; 0 without the port's display lines or when the caller is not the running mode | F | item 154 display: Premium 1.16 r2-r6, Pro 1.15 r5 (MODE_SDK.md "Display priority") |
| `pm_display_covered()` | 1 while a display of the game's that beat the held priority has the screen | none (`display_test_mode.c`) | item 154 display r4: 1 when the tilt warning (241) beat 230 (`covered by a game display that beat the priority`) |

## 4. Item 141's proof

**At the desk.** `mode_file.c` compiled with the PC's gcc against stub `pm_*` calls that
print every call, driven with shots and ticks the way Godzilla dispatches them (`0x1`, then
the shot bit):

- The KAIJU RUSH file that ran on a machine scores and makes the same calls as the
  `mode_file.c` before item 141, with two differences: the new `callout 1291 at 10 s left`
  line, and its `clip_start`, which fires on the trigger shot, now plays 30 ticks (500 ms)
  later from the tick (`waits 500 ms`, `played (mode start, from the tick)`, `still
  drawing`) instead of inside the shot. That delay is the run 1 fix below, and it applies to
  every old file whose start clip fires on a trigger shot.
- PARAM TEST (rising; ramps 1M; Building 5M, Godzilla target 3M and Shield target left 2M
  of their own; Shield target left ends it): Left ramp +1M, Building +10M, Godzilla target
  +9M, Right ramp +4M, callouts at 30 and 20 s left, Shield target left +10M then
  `END (end shot)` one tick later, the second clip 500 ms after `END` from the tick, no
  time-up callout, the screen hidden 8 s after.
- Two clips close together (two slots, `edge.script`): an end shot's clip still waiting
  when the next mode's trigger shot starts it is dropped (`dropped before it played: a
  newer clip waits instead`) and the new start clip plays; one still waiting when the next
  mode starts by trigger file is dropped before that mode's clip plays at once, never over
  it; a start clip still waiting when its mode is stopped is dropped (`the mode ended`).
  Before this fix the first was lost with no log line and the second played over the new
  mode's clip.
- FIXED TEST (fixed, the same table): 1M, 1M, 5M, 3M; a callout at 8 s left; `END (time
  ran out)` with the same clip at both ends.
- An end shot and a drain in the same tick end the mode as `ball ended`, and the next start
  runs its whole clock.
- An end shot, then a scoring shot in the same frame (`endpay.script`): the scoring shot pays
  nothing and `END` counts 1 shot. Before this rule it paid (+10M, 2 shots). A scoring shot
  dispatched BEFORE the end shot in that frame still pays.
- The `mode_file.c` before item 141 logs `unknown key, skipped` for each new key and pays
  the old ladder.

**In the emulator** (Godzilla Pro 1.15, a card COPY carrying PARAM TEST's screen and three
new clips; the rig boots it clean and gets `mode.so`, the port and the two mode files through
`PAD_MODE_SO` + `/dump`; muted). Run 2 used the runtime with item 139 merged in; the second
block below is an excerpt of its `mode.log` (left out: both `still drawing 1 s after it
started` lines and FIXED TEST's `callout 1291 at 10 s left`). Health: segv 0, fatal 0 (throw 6, as on every overnight boot).
**Run 3** (2026-09-17 02:59-03:03) repeated run 2's steps on the object with items 139 and
140 merged, the dropped-clip rule and the end-shot pay rule, and every line of run 2's log
below came back the same (Maser x2 start with the clip 518 ms later from the tick, +1M, +10M, +9M, +4M,
callouts at 30 and 20 s left, Shield +10M and `END (end shot)` 17 ms later, Clip2 539 ms
after `END`, the own screen hidden 8,017 ms after it; FIXED TEST 1M, 1M, 5M, callouts at 10
and 8 s left, `END (time ran out)`), with the same glass. It added two cases:

```
192232 [mode] PARAM TEST START (trigger file): slot 1, player 1, 45 s, score 41826320
194792 [mode] shot 00000000_80000000: +2000000 (asked 2000000), 1 shots, 2000000 awarded
194808 [mode] clip "PadMode_param_test_Clip2" waits 500 ms after the end shot (mode end)
194808 [mode] PARAM TEST END (end shot): 1 shots, awarded 2000000, score 41826320 -> 43826650, 2600 ms wall
195208 [mode] clip "PadMode_param_test_Clip2" (mode end) dropped before it played: a newer clip played at once
195231 [mode] clip "PadMode_fixed_test_Clip" played (mode start)
195231 [mode] FIXED TEST START (trigger file): slot 0, player 1, 15 s, score 43826650
198208 [mode] clip "PadMode_fixed_test_Clip" played (mode end)
198208 [mode] FIXED TEST END (trigger file): 0 shots, awarded 0, score 43826650 -> 43826650, 3000 ms wall
...
212309 [mode] shot 00000000_00400000: +5000000 (asked 5000000), 1 shots, 5000000 awarded
212310 [mode] shot 00000000_80000000: +4000000 (asked 4000000), 2 shots, 9000000 awarded
212325 [mode] PARAM TEST END (end shot): 2 shots, awarded 9000000, score 43826650 -> 55352310, 2617 ms wall
```

The dropped clip: FIXED TEST, started by its file 423 ms after PARAM TEST's `END`, showed
"FIXED BOTH ENDS" at +0.8 and +2 s, never "PARAM END". The same clip at both ends: FIXED
TEST stopped by `mode.stop` 3 s into its own 4 s start clip; the game's video log shows no
new clip, the start clip ran to its end, and the glass showed the HUD 1.2 to 2.5 s after
`END`.
Shield target left and Building pressed in one switch update reached the mode Building
first, so both paid (right: the end shot came second).

```
 44923 [mode] params: award ladder rising, 3 shot award(s), end shot 00000000_80000000
101631 [mode] PARAM TEST trigger 2 of 2 (player 1)
101631 [mode] clip "PadMode_param_test_Clip" waits 500 ms after the trigger shot (mode start)
101632 [mode] PARAM TEST START (trigger shot): slot 1, player 1, 45 s, score 175000
102168 [mode] clip "PadMode_param_test_Clip" played (mode start, from the tick)
105631 [mode] shot 00000000_00100000: +1000000 (asked 1000000), 1 shots, 1000000 awarded
107814 [mode] shot 00000000_00400000: +10000000 (asked 10000000), 2 shots, 11000000 awarded
110013 [mode] shot 00000000_00080000: +9000000 (asked 9000000), 3 shots, 20000000 awarded
112198 [mode] shot 00000000_00200000: +4000000 (asked 4000000), 4 shots, 24000000 awarded
116697 [mode] callout 1291 at 30 s left
126697 [mode] callout 1295 at 20 s left
127715 [mode] shot 00000000_80000000: +10000000 (asked 10000000), 5 shots, 34000000 awarded
127715 [mode] end shot 00000000_80000000: the mode ends on the next tick
127731 [mode] clip "PadMode_param_test_Clip2" waits 500 ms after the end shot (mode end)
127731 [mode] PARAM TEST END (end shot): 5 shots, awarded 34000000, score 175000 -> 34650990, 26100 ms wall
128266 [mode] clip "PadMode_param_test_Clip2" played (mode end, from the tick)
135747 [mode] own screen hidden
140238 [mode] clip "PadMode_fixed_test_Clip" played (mode start)
140238 [mode] FIXED TEST START (trigger file): slot 0, player 1, 15 s, score 34650990
142614 [mode] shot 00000000_00100000: +1000000 (asked 1000000), 1 shots, 1000000 awarded
144814 [mode] shot 00000000_00200000: +1000000 (asked 1000000), 2 shots, 2000000 awarded
147014 [mode] shot 00000000_00400000: +5000000 (asked 5000000), 3 shots, 7000000 awarded
147197 [mode] callout 1291 at 8 s left
155226 [mode] clip "PadMode_fixed_test_Clip" played (mode end)
155226 [mode] FIXED TEST END (time ran out): 3 shots, awarded 7000000, score 34650990 -> 41926320, 15029 ms wall
```

On the glass (screenshots looked at): "PARAM START" at +1, +2 and +3 s after the start,
"PARAM END" at +1.4 and +2.9 s after the end shot, the HUD with the own screen gone and
34,650,990 after 8 s, and "FIXED BOTH ENDS" after FIXED TEST's start and after its end.

**Run 1 found one thing:** the same PARAM TEST start, with its clip played INSIDE the Maser
trigger shot (`played (mode start)` 29 ms after the trigger line), showed the HUD and the
own screen at +1.5 and +3 s, never the clip; the clips played from the tick (FIXED TEST's
two, and PARAM TEST's end clip one tick after its end shot) all showed. So a clip a shot
starts (the trigger shot's `clip_start`, the end shot's `clip_end`) now waits 30 ticks and
plays from the tick; any other start or end plays at once, and a start clip still waiting
when the mode ends never plays (desk). Run 1's scoring, callouts, end shot and screen timing
matched run 2's line for line.

## 5. Keys other items reserve (not in this runtime yet)

Each lands as its own rows in sections 1 and 2 when its item merges (item 139's `starts`
and `cooldown`, item 140's `stack`, item 142's film fields, item 147's `starts_on` and
`ends_on` and item 150's own sounds have: they are rows above now).

| Key / field | Item | What it is for |
|---|---|---|
| (none left) | | |
