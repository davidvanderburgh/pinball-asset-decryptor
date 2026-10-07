# Every parameter a mode has

"What are all the parameters we have access to?" This file answers that in one place,
read off the code, with what has been MEASURED about each one. A mode has three layers:

1. **`mode.json`**, what the Modes tab saves in the card project (`ModeSpec` in
   `pinball_decryptor/plugins/stern/mode_project.py`). A person picks shots by name.
2. **The runtime mode file** (`mode.cfg`, `mode1.cfg`, `mode2.cfg` ...), which the build
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
| `MODES_MAX` | 64 slots | `mode.cfg`, `mode1.cfg` .. `mode63.cfg`; after the first sweep only the slots up to one past the last file are re-read |
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
| `end_shot` | bits | 0 | a shot in `bits` ends the mode. It scores first if it is a scoring shot, and no shot after it pays; the mode ends on the next tick: `END (end shot)`, `clip_end` 500 ms later from the tick, no time-up callout. PAD-314: the tab's "any shot that does not score" is one mask of every playfield shot that is not the mode's own | Mode > Ends on > and sooner, on (Advanced > Ends early when hit before PAD-314) | item 141 runs 1-3: Shield target left +10M, then `END (end shot)` 16 ms later (the next tick), with the second clip. Run 3: Shield target left and Building pressed together reached the mode Building first (+5M, then Shield +4M, `END`, 2 shots); a scoring shot AFTER the end shot in one frame paying nothing is desk only (`endpay.script`) |
| `shot_penalty` | `<bits> <points>`, repeatable (16) | none | PAD-314: a shot in `bits` TAKES `points` away each time it is hit while the mode runs, as a flat amount (no ladder, no multiplier), through `pm_score_sub`: never below 0 (`penalty shot <bits>: -N (asked M), L lost, score S`). A shot that also scores pays and takes nothing (said at load). The END line carries `lost L, total N` and the own screen's TOTAL is net of the losses (`TOTAL -N` when they took more; a borrowed total message shows 0 then). An older `mode.so` logs the key `unknown key, skipped` and takes nothing | Scoring > Points per shot, a minus number | PAD-314, desk only (tests/test_spike2_mode_sequence.py); the score table write and the 0-point add that follows it are NOT measured in the emulator |
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
| `aside` | `hide` or `keep` | hide | PAD-347: while one of the game's own modes runs beside the mode (`pm_aside`), the middle of the screen is the game's: `hide` hides the mode's own screen until the game's mode ends (`<name>: its screen steps aside - a stock mode has the middle of the screen`, then `its screen is back`), also while its total is still showing; `keep` leaves it up, for a screen laid out clear of the game's words. Anything else logs and means hide. A port that cannot tell keeps every screen up | no | PAD-347, desk (tests/test_spike2_mode_aside.py) and the machine report that asked for it (MODE_SDK.md "Stepping aside") |
| `game_modes` | `stack`, `give_way` or `block` | block | PAD-363: what the mode does about the game's own modes. `stack`: it runs beside them (its screen steps aside, `aside`). `give_way`: it starts only while none of the game's modes runs (`<name> not started (<why>): one of the game's modes is running - its trigger count is kept`) and one of them beginning ends it (`END (the game's own mode began)`). `block`: as give_way, and while it runs the game's modes in `block_modes` (or every one the port names) cannot start (`pm_block_game_modes`), and every rule of the game's the port names sees no shots but the ones in `keep_rules` (`pm_block_rules_keep`); a port that cannot hold them off says so once and it gives way. PAD-398 (David, 2026-10-05: "when our custom modes start, we should ONLY be in those modes unless explicitly noted"): `block` is the default, and anything else logs and means block | The game's own modes > While it runs, the game's modes | PAD-363, desk (tests/test_spike2_mode_aside.py) |
| `block_modes` | the game's mode ids, 0-127, spaces or commas | every one the port names | PAD-363: with `game_modes block`, the game's modes it holds off - the ids of the port's `block_start_<id>` lines, named by its `text block_name_<id>` (the Modes tab lists them by name). A word or an id from 128 up logs and is left out | The game's own modes > the ticks under "cannot start" | PAD-363, desk |
| `keep_rules` | the port's rule numbers, 0-31, spaces or commas | none | PAD-398: with `game_modes block`, the game's rules (its features: Godzilla's Destruction Jackpot, building locks, bridge, cities...) that go on counting their shots while it runs - the numbers of the port's `block_rule_<n>` lines, named by its `text block_rule_name_<n>` (the Modes tab lists them by name); every other rule the port names sees no shot until the mode ends. A word or a number from 32 up logs and is left out | The game's own modes > The game's features that keep counting while it runs | PAD-398, desk (tests/test_spike2_mode_aside.py) |
| `multiball` | `<balls> [ball save s]`: 2-6 balls, 0-120 s (10 when absent) | no multiball | item 167: when the mode starts the game serves balls until that many are in play, through the framework's own start-a-multiball (`pm_multiball_start`), with that ball save; if the game refuses (no game in play, a tilt, a port without `multiball_serve`) the mode is not started (`not started (<why>): the game did not serve its balls`) and its trigger count is kept. While it runs the mode watches the framework's count of the balls in play: one ball (or none) for 2 s, once the ball save and 3 s more have passed, ends it (`END (one ball left)`, or `no second ball was served` when two were never seen). With `seconds 0` the mode has no clock: only that, the last ball's drain or its end shot ends it. The game's own end of ball comes only when the last ball drains | Multiball > A multiball (item 167) | item 167, emulator-proven 2026-09-26 on all 36 shipped builds (`MULTIBALL_PROVEN`): served 3 on the start, both jackpot shots paid, the rig's drains took the count 4, 3, 2, 1 and ended it `one ball left`, then the game's own end of ball (MODE_SDK.md "A multiball of your own") |
| `add_ball` | `<mask> [times]`: a shot, 1-6 times (1 when absent) | no add-a-ball | item 167: while the multiball runs, each hit of the shot asks the game for one more ball (`pm_multiball_add`), up to `times` a run; the ball save and its grace run again from the add. The shot still scores if it is a scoring shot | Multiball > Add a ball on (item 167) | item 167, emulator-proven 2026-09-26 on all 36 shipped builds: one hit asked for a fourth ball (`4 ball(s) in play`) |
| `ball_save` | `<seconds>`: 1-120 s | no ball save | PAD-225: with no `multiball` line, when the mode starts the game's own ball saver is on for that many seconds (`pm_ball_save`): a ball that drains in that time is served back and the ball does not end. A refusal (no game in play, a tilt, a port without `multiball_serve`) does not stop the mode: `BALL SAVE: <s> s - the game refused, so none`. Ignored beside a `multiball` line, which has its own | Ball save > A ball save when it starts (PAD-225) | PAD-225 (MODE_SDK.md "A ball save of your own"); the builds seen in the emulator are `BALL_SAVE_PROVEN` |
| `magnet` | `<ms> [mask]`: 100-5000 ms | no grab | PAD-381: while the mode runs, every hit of the shot the magnet sits at - the port's `value magnet_shot` (Godzilla: the Godzilla target), or `<mask>` - holds the ball on the magnet for that long, the hit that starts the mode included (`pm_magnet_grab`: the runtime clamps the time, takes the powers from the operator's magnet settings and holds its own limits). A refused hit is logged (`magnet shot ... - no grab`) and the mode carries on | Mode > Magnet > Hold the ball on the magnet (PAD-381) | PAD-381 (MODE_SDK.md "The magnet"); the builds seen in the emulator are `MAGNET_PROVEN` |
| `scoop_hold` | `<ms>`: 100-10000 ms | no hold | PAD-381: while the mode runs, a ball that settles in the scoop is held there that long once the game is done with it (its own awards and screens come first), then the game kicks it out as it always does - its own 64 ms kick at the operator's SCOOP KICK POWER, with its own retries (`pm_scoop_hold`). The hold ends at its time, when the mode ends, and when the game ends or tilts. Nothing fires a coil | Mode > Scoop > Hold a ball that lands in the scoop (PAD-381) | PAD-381 (MODE_SDK.md "The scoop"); the builds seen in the emulator are `SCOOP_PROVEN` |
| `shield` | `toward` | left alone | PAD-392: while the mode runs the shield targets face the player: Godzilla Premium/LE's platform turns 1.5 s after it starts (the ball that started it clear of the platform first) and the runtime keeps it there (`pm_shield_keep`: a platform the game's ball search left elsewhere for 1.5 s is turned back), never while one of the game's own modes or multiballs runs, 1.5 s between moves and 12 a minute at most; the game's own background return to its resting place waits meanwhile (PAD-409); it turns back where it was when the mode ends, the ball ends, or the game ends or tilts, unless the game has turned it itself. Kept only while the game's own shield feature (the port's `text shield_rule`, Mechagodzilla Shield) sees no shots - while it counts, the game turns the platform back about 2 s after every move - so `validate` refuses it with `game_modes` other than block or with that feature in `keep_rules`. Anything but `toward` logs and is ignored | Mode > Shield targets > Turn the shield targets toward the player while it runs | PAD-392, emulator (stock Premium/LE 1.16, rig 1: a form mode kept it toward 18.5 s through six shield hits and put it back at its end); `SHIELD_PROVEN` in mode_project.py |
| `coil_hold` | `<name> <ms> [mask]`: up to 4 lines | none | PAD-381: one of the port's held coils (`text held_coils`; a Godzilla Premium/LE: `mg_magnet` the Mechagodzilla magnet, `bridge` the bridge diverter, `magnet`) held `<ms>` (100-5000) through `pm_coil_hold`, with the magnet's limits: on every hit of `<mask>` while the mode runs (the starting hit included), or once as the mode starts with no mask. A refused hold is logged and the mode carries on | Mode > Other mechanisms (PAD-381) | PAD-381 (MODE_SDK.md "Held coils"); the coils seen held in the emulator are `HELD_COILS_PROVEN` |
| `multiball_on` | a shot mask | the balls come at the start | PAD-228: with a `multiball` line, the balls are NOT served when the mode starts: the first hit of this shot while the mode runs serves them (`pm_multiball_start`, the line's balls and ball save) - "press the Action button now for a multiball". Until then the mode's clock is the time to hit it: time up ends the mode with no multiball (`END (time ran out)`). Once served (`MULTIBALL on <mask> with N s left`) the clock stops and one ball left ends it, as `seconds 0` does. A refusal logs and keeps waiting. `light_shots` lights this shot too. Without a `multiball` line it logs and is ignored | Multiball > Balls come (PAD-228) | PAD-228, emulator-proven 2026-09-27 on Godzilla Pro 1.15, Pro 1.16 and Premium/LE 1.16 (rig 2): `the multiball waits for 10000000_00000000 (30 s to hit it)` at the start, the Action button press 7.2 s later `MULTIBALL on 10000000_00000000 with 23 s left: 3 balls asked for`, and on the Pros `END (one ball left)` after the drains, the clock stopped (30.8 s wall for a 30 s mode); `light_shots` held the Action button solid red for the whole run (the shim's LED view, node 1) |
| `starts_on` | `shot`, `sequence` (PAD-314: the `trigger_seq` shots in order) or `event <name> [N]` | shot | `event`: the mode starts on the N-th firing (1 when absent) of an event the port names, counted per player across a game and cleared by the port's `game_start`. The `trigger` line is ignored (`starts_on event: the trigger shots are ignored`) and the tab writes none, so a `mode.so` older than events logs the file NOT VALID instead of starting it on a shot. An event the port does not name leaves it NOT VALID. Fired with no game in play: retried for 3 s, then dropped. `sequence`: the `trigger_seq` lines start it and the `trigger` line is ignored, as with an event. Anything else logs and means shot | Starts and ends > Starts on: Its shot / These shots, in order / An event | item 147, Godzilla Pro 1.15 (run2b) and Premium 1.16 (run3c, run3d): `START (event ball_start)` in the same millisecond as the game's ball start; `START (event multiball_start)` on a forced godzilla multiball; Premium run3c: a multiball start with no game in play logged `still no game in play after 3 s`. A count N above 1 was not in any run's file (MODE_SDK.md "Events") |
| `trigger_also` | `<bits> <count>` | none | PAD-227: another shot to hit `count` times (1 when 0) in one ball as well as the `trigger` line's, in any order; up to 3 lines (a 4th logs and is skipped). The mode starts on the shot that meets the last of them (`its trigger is met - waiting for its other shots` until then). Counted per player, zeroed at the mode's start and at every end of ball, as `trigger`'s are. With `starts_on event` the event starts it only if every `trigger_also` is met by then (`waiting for its other shots`, and the event count starts again). An older `mode.so` logs `unknown key, skipped` and starts on the `trigger` line alone | Mode > Starts on > And also | PAD-227, desk only (tests/test_spike2_mode_more_conditions.py) |
| `after` | `ball <mode name>` or `game <mode name>` | none | PAD-227: the mode's own shots and events count toward starting it only once the named mode (another of the card's modes, matched on its `name`) has started for this player this ball, or this game (`shot not counted - <name> has not run this ball`). Only one of a card's modes runs at a time, so a mode whose start is met while that one still runs starts on its next start shot after it ends. A name no mode on the card has logs once and the mode never starts. Anything but `ball`/`game` logs and is skipped. A trigger file starts it anyway | Mode > Starts on > Only after | PAD-227, desk only (tests/test_spike2_mode_more_conditions.py) |
| `trigger_seq` | bits, repeatable (8) | none | PAD-314, with `starts_on sequence`: one line per shot, in the order to make them; the mode starts when one player makes them in that order in one ball (`START (shot sequence)`). A step is met by a shot in its mask (`<name> sequence N of M`). A shot of the sequence made out of turn sends the player back to the start (`is not shot N of M - back to the start`; it counts as step 1 if it is step 1's shot); a shot in no line is ignored. The progress is per player, cleared when the mode starts and at every end of ball. Once the last shot is made the sequence is met, and `trigger_also` and `after` gate it as they gate the `trigger` line. A 9th line logs and is skipped; none leaves the file NOT VALID. An older `mode.so` logs the key `unknown key, skipped` and, with no `trigger` line, the file NOT VALID | Mode > Starts on > These shots, in order | PAD-314, desk only (tests/test_spike2_mode_sequence.py) |
| `trigger_seq_reset` | bits | 0 | PAD-314: a shot in these, made when it is not the step wanted, sends the player back to the start as well (the tab writes every playfield shot of the game that is not in the sequence; never the cabinet buttons). Logged at load as `a shot in <bits> out of turn starts the sequence over` | Mode > Starts on > any other shot starts the sequence over | PAD-314, desk only (tests/test_spike2_mode_sequence.py) |
| `ends_on` | `drain`, `clock` or `event <name>` | drain | `drain`: its clock or the end of the ball, as before the key. `clock`: its clock only; at the end of a ball it logs `the ball ended - running on (ends_on clock)`. `event`: that event, its clock or the end of the ball; an event the port does not name logs and means drain. Anything else logs and means drain | Starts and ends > Ends on: Its clock, or the ball draining / Its clock only / An event | item 147: `ends_on clock` ran through a drain and ended `time ran out` (Pro 1.15 run2b, 60,773 ms); `END (event multiball_end)` on Pro 1.15 when the game stopped the multiball at the end of its ball, and on Premium 1.16 when the probe called the stop function (run3d) |
| `roster_slot` | a slot 0-6 of Godzilla's battle roster (0 Ebirah, 1 Titanosaurus, 2 Gigan, 3 Megalon, 4 King Ghidorah, 5 Megalon & Gigan, 6 King Ghidorah & Gigan) | none | the mode takes that slot's place on the BATTLE SELECTION screen: picking the slot starts the mode (after the port's `roster_start_after_ms`) and the game's battle for it never starts; the mode's end lights the ramps again. The file needs `seconds` but no trigger. A pick while it runs is taken and restarts nothing; a pick while another of our modes runs starts it when that one ends; a pick it cannot start, or a ball ending first, gives the pick back. A number above 15, `-1` or a word logs and claims nothing. The slot's name and art on the screen are a card edit (`roster_entry.py`), not this key. A port with no roster logs `NOT claimed` | no | item 146, Godzilla Pro 1.15 (runs 3, 4, 6; run6 with the runtime's hook alone) and Premium 1.16 (run5): `MOTHRA START (roster pick)` about 3,000 ms after the pick, `battle over for player 1` at its end, a stock slot still started the game's battle. Pick while it runs, pick while KAIJU RUSH runs, two players: run4. Cannot start, ball ends first, a pick lapsing: desk only (MODE_SDK.md "A monster in the roster") |
| `roster_callout` | a sound request id 0-65535 | the claimed slot is silent | what the selection screen plays when the cursor lands on the held slot (the game's own is the old monster's name, which a claim silences). Re-applied when the file is reloaded; removing the file puts the game's id back. Anything else logs and leaves the slot silent | no | item 146 run6, Pro 1.15: the slot table's id read back 1888 -> 0 at the claim, 207 after `roster_callout 207`, 1888 when the file was removed (`PAD_PEEK`). Premium 1.16 run7 and Pro 1.15 run8: the same three reads. Not heard (the rig is muted) |
| `sound_start` | `<request> [ms]` | 0: none | plays a CARRIER request (a stock request the game never plays, re-pointed by the build at a sound of the mode's own, `mode_sounds.py`) when the mode starts, at voice-bus priority 4, WITHOUT the steal flag (item 150 follow-up: nothing cuts it while it sounds). The game's lower-priority speech on the voice bus is faded out first (60 ms) and the call plays 70 ms later; held off by an equal or higher one it waits up to 1.5 s, then logs `NOT played`. `ms` is the sound's own length: the carrier is faded out (40 ms) and stopped once `ms` + 1/8 + 120 ms have passed, so the silence after a sound shorter than the carrier's record does not hold the bus | Sounds of its own > When it starts (Write builds the bank and picks the carrier, item 149) | item 150 RUN 5 / 7, Godzilla Pro 1.15 and Premium 1.16: heard in the capture (corr 0.86-0.92), `1251 p4 f1 b02` in the channel dump. `ms`: see item 150's TODO entry (RUN 8) |
| `sound_shot` | `<request> [every] [ms]` | 0: none | plays a carrier on every scored shot, or every Nth, at priority 3 without the steal flag: skipped while its own previous call still sounds (`skipped - its previous call still sounds`), waits up to 0.8 s under the game's priority-3 speech, fades the game's ordinary speech first. `ms` as above | Sounds of its own > On a scoring shot, every N | item 150 RUN 5 run C, RUN 7A / 7B: three shot calls heard (corr 0.61-0.90); RUN 5 run B: shots under the game's 1997 (p3 f0) not played, as designed |
| `sound_end` | `<request> [ms]` | 0: none | plays a carrier when time runs out, INSTEAD of `callout_end`, at priority 4 without the steal flag (a shot call still sounding is faded out first, 60 ms). `ms` as above; the stop outlives the mode | Mode > When time is up: My sound | item 150 RUN 5 / 6 / 7: heard (corr 0.989) on both titles |
| `music` | `<request> [sid]` | 0: none | starts a music carrier with the mode on the music bus, clears its steal flag so the game's music cannot take the bus back, starts it again whenever no channel plays it. With a `sid` (item 150 follow-up) the carrier is pointed at that sound id while the mode runs (`pm_sound_sid`): the mode's OWN bed, which the build bound to a sid no request names. The game's music is faded out (250 ms) before it starts, any request of the game's music class (priority 1) playing during the mode is faded out, and at every end the music FADES (400 ms, `pm_sound_fade`), the carrier's own list is put back and the game's music that played at the start is played again. The build makes the WAV a seamless loop on the 10 ms grid, repeated so the record outlasts the mode (its `seconds` + 3, at most 150 s) | Sounds of its own > Music underneath | item 150 RUN 5 / 6 / 7: one serial on bus 0x01 START to END, 0 restarts, in phase with one loop, nothing after END; RUN 3 (steal flag kept): 11 restarts. Tiled music: see item 150's TODO entry (RUN 8) |
| `swap` | `<request> <stock key> <our key>` (keys 16 hex digits), up to 4 | none | item 163: the build appended the sound as a record NO descriptor names; while it plays on `request` the carrier's own record key takes ours (`pm_sound_swap`), so no stock sound id changes at all. A call swaps for that play only, the music for as long as the mode runs. A swap that cannot be armed (no sound_lookup site) is not played (`NOT played - its own record could not be swapped in`) | Sounds of its own (Write writes the line) | not measured on a machine yet; the emulator's per-title sound-call runs (item 163) |
| `light` | `<shots> <colour> [pattern] [ms]`, up to 8 light lines in all | none | holds the inserts the port's `lamp` lines tie to these shot bits (MODE_SDK.md "Lights: named inserts") from the mode's START to its END, whatever ends it, in the colour and pattern given: `colour` is `rrggbb` (a `#` before it is fine) or red, green, blue, yellow, orange, purple, cyan, white, pink; `pattern` solid (the default), blink, pulse or chase; `ms` its period (0 or absent: blink 500, pulse 1600, chase 150 a step). Everything the mode does not hold keeps the game's own light shows. A line with no bits, no colour or an unknown pattern is logged and ignored; on a port without lamps the mode logs `lights: this game's port names no inserts` and lights nothing | no | item mode-leds RUN 5, Premium 1.16: the decoded node bus (MODE_SDK.md "Lights: named inserts") |
| `light_insert` | `<colour> <pattern> <ms> <name>[,<name>...]` | none | the same for inserts by the game's own name (a port `lamp` line's name, any case), several separated by commas; a chase runs across them in that order. An unknown name is logged and skipped | no | item mode-leds RUN 5 (a mode file lit both ramps, BIG LOOP and the powerlines, handed back at END) |
| `light_shots` | `<colour> [pattern] [ms]` | none | the AUTOMATIC form: every insert of every shot that scores in this mode (`shots` and each `shot_award`) is held while it runs, so a player sees what pays | On the playfield and the screen > Light the shots that score, its colour and Solid / Blink / Pulse / Chase (item 157) | item mode-leds RUN 5 (a mode file lit both ramps, BIG LOOP and the powerlines, handed back at END) |
| `light_all` | `<colour> [pattern] [ms]` | none | every insert the port names is held in the colour while it runs (`pm_lamp_all`): a mode's Lights on a title without the game's light language (no `light_run`) | On the playfield and the screen > Lights, on a title whose Lights go through its inserts (`light_route` "inserts"): the tab writes `light_all <colour> pulse` | item 164 (the shim's LED view: every addressed RGB insert in the held colour while it ran, none before or after) |
| `light_priority` | 1-255 | 255 | the priority of the lamp layer the mode's inserts sit in (`pm_lamp_priority`): 255 is above every show the game ran in the runs measured (its highest was 145); lower, and a game show of a higher priority covers the mode's inserts while it lights them. Outside 1-255 logs and means 255 | no | item mode-leds RUN 5 (`prio 1` under a battle: MASER went to the game's own layer) |
| `priority` | 0-255, the game's display-effect scale | 0: none | PAD-353: NOTED ONLY. It used to make the game's displays that did not beat it wait (`pm_display_priority`); on a Godzilla Premium the Magna-Grab's screen waited for 180 and the game kept its magnet on until the machine was switched off. Now the game's displays play as they come and the runtime only watches them (`pm_display_covered`); `display priority N asked`/`given up` lines still mark the mode's run. Above 255 logs and means 255; not a number logs and is ignored | On the playfield and the screen > Display priority | item 154/157 (the hold), withdrawn by PAD-353 (MODE_SDK.md "Display priority") |

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
| `screen_layout` | {} (placed automatically) | Screen > Lay out on the screen... (the Scenes editor, PAD-323) | where the screen node goes in the HUD scene, every key optional: `x`, `y` the picture's top-left on the 1360x768 glass; `scale` the whole screen's size (1 = as made); `words_x`, `words_y` the words' place on the picture (both or neither); `words_scale` the words' own size; `order` the HUD scene's root child the screen is drawn under (0 = under all of the HUD's own pictures; absent = over them, as before). A key not given stays automatic, so a mode without it builds byte for byte as before. A change rebuilds the scene: never a settings-only Try it. A code mode's `assets.json` takes the same key |
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
| `shot_award` | [] | Scoring > Points per shot (blank = the usual award; PAD-314: a minus number takes points away) | `shot_award <bits> <points>` per row, or `shot_penalty <bits> <points>` for a minus number. `validate` refuses 0, and a minus number on a shot that scores |
| `end_shot` | "" | Mode > Ends on > and sooner, on: (no shot) / (any shot that does not score) / (these shots) + a tick per shot (Advanced > Ends early when hit, one shot, before PAD-314) | `end_shot <bits>`: a single name's mask (files from before PAD-314), the OR of a LIST of names (`end_shot_list`: the ticks; `[]` is refused as "tick a shot"), or (`END_SHOT_OTHERS`) the OR of every playfield shot that is not the mode's own (`other_shots`: not the shots that score, nor in a multiball the add-a-ball shot and the shot the balls come on; never the cabinet buttons). `validate` refuses it when every shot scores; `retarget` keeps it, it names no shot |
| `clip_both` | {} | Advanced > Second clip: none / the same clip / a title card / my video | the other end's `clip_start` / `clip_end`; a title card or video is built as `PadMode_<folder>_Clip2`. The same clip does not play again at the end while its start is still playing (item 141 run 3: FIXED TEST stopped 3 s into its 4 s clip; the clip ran on to its end, no second play, the HUD 1.2 to 2.5 s after `END`). A second clip of its own has its own name and plays |
| `callout_at` | [] | Advanced > Callouts at chosen seconds (seconds left, id, Pick) | `callout_at <seconds> <id>` per row, after the countdown's |
| `restore_after` | 6 | Advanced > Screen stays up | `restore_after` |
| `starts` | "unlimited" | How often it can start: once a game / once a ball / any number / up to N times a game | `starts <policy or N>` (nothing when unlimited) |
| `cooldown` | 0 | How often it can start > Wait N seconds | `cooldown <seconds>` (nothing when 0) |
| `stack` | true | The game's own modes > Can run during the game's own modes | `stack no` when off (nothing when on) |
| `game_modes` | "block" | The game's own modes > While it runs, the game's modes (may start / may start, and end this one / cannot start) | `game_modes give_way` or `game_modes stack` (nothing at block, the runtime's default since PAD-398) |
| `block_modes` | [] | The game's own modes > the ticks under "cannot start" (the title's modes its port can hold off, by name; a mode moved to another title keeps them by name; the last tick stays) | `block_modes <ids>` with `game_modes block` ([] = every one the port names, nothing written) |
| `keep_rules` | [] | The game's own modes > The game's features that keep counting while it runs (the title's rules its port names, by name; a mode moved to another title keeps the ones that title has) | `keep_rules <numbers>` with `game_modes block` (nothing when none is kept) |
| `multiball` | false | Multiball > A multiball: the game serves more balls (item 167; when it starts unless Balls come names a shot, PAD-228) | `multiball <balls> <ball_save>` when on (nothing when off, or on a title that cannot: `validate` says so) |
| `balls` | 3 | Multiball > Balls in play, 2-6 | the first word of `multiball` |
| `ball_save` | 10 | Multiball > Ball save, 0-60 s | the second word of `multiball` |
| `start_ball_save` | 0 | Ball save > A ball save when it starts, 1-60 s (0 = none) | `ball_save <s>` when not 0 and the mode is not a multiball (nothing on a title that cannot: `validate` says so) |
| `magnet_ms` | 0 | Magnet > Hold the ball on the magnet when the <shot> is hit, for 0.1-5 seconds (0 = never) | `magnet <ms> <the profile's magnet_shot mask>` when not 0 (nothing on a title that cannot: `validate` says so) |
| `scoop_hold_ms` | 0 | Scoop > Hold a ball that lands in the scoop for 0.1-10 seconds (0 = never) | `scoop_hold <ms>` when not 0 (nothing on a title that cannot: `validate` says so) |
| `coil_holds` | [] | Other mechanisms > Hold the <mechanism> for 0.1-5 seconds, as it starts or on a shot (one row per proven coil) | `coil_hold <name> <ms> [mask]` per row (nothing on a title that cannot: `validate` says so) |
| `shield` | false | Shield targets > Turn the shield targets toward the player while it runs | `shield toward` when true (nothing on a title that cannot: `validate` says so, and refuses it unless `game_modes` is block and `keep_rules` leaves out the title's shield feature) |
| `models` | {} | (none: kept by Port to... and by opening, copying or building on the game's other model, PAD-396) | nothing: the mode's shots and mechanisms on each OTHER model of its game (`{"pro": {...}}`), put back when it goes back there |
| `ported` | {} | (none) | nothing: the shots and mechanisms the last port to this model made, so Port to... can tell an edit made since from them |
| `add_ball_shot` | "" | Multiball > Add a ball on (a shot name, or none) | `add_ball <mask> <add_ball_max>` when a shot is picked; dropped by a retarget to a title without the shot |
| `multiball_on_shot` | "" | Multiball > Balls come ((when it starts), or a shot name) | `multiball_on <mask>` when a shot is picked and the mode is a multiball; `validate` wants a shot the title has and `seconds` above 0 (the window to hit it); dropped by a retarget to a title without the shot |
| `add_ball_max` | 1 | Multiball > up to N times, 1-6 | the second word of `add_ball` |
| `clip_source`, `clip_from`, `clip_length` | "", 0.0, 0.0 | From a film > Clip... (item 142) | nothing in the runtime file: the film, the second the clip was cut at and its length (up to 30 s). The cut itself is `clip_file` |
| `sound_source`, `sound_from`, `sound_length` | "", 0.0, 0.0 | From a film > Sound... (item 142) | nothing: where the end sound was cut; the cut is `end_sound` |
| `art_source`, `art_from` | "", 0.0 | From a film > Picture... (item 142) | nothing: the film and the second of the frame; the frame is `screen_art` |
| `clip_crop`, `art_crop` | "" | the film dialog's letterbox / fill (item 142) | nothing: how the clip and the picture were cropped, so the dialog reopens on it |
| `starts_on` | "shot" | Starts and ends > Starts on: Its shot / These shots, in order (PAD-314) / An event (item 147) | `starts_on event <name>` in place of the `trigger` line (nothing when "shot"); `starts_on sequence` and the `trigger_seq` lines in its place with "sequence". `validate` names an event the title's `TitleProfile.events` does not carry |
| `start_also` | [] | Mode > Starts on > And also (up to 2 rows; the file takes 3) | one `trigger_also <bits> <count>` per `[shot name, count]` (nothing when empty). `validate`: up to 3, a shot the title has, a count of 1-20. `retarget` drops a shot the new title lacks |
| `after` | "" | Mode > Starts on > Only after | `after <after_when> <name>` (nothing when ""): another mode of the project, by its NAME. `validate` refuses the mode's own name; the tab names one no mode of the project has (`after_problems`) |
| `after_when` | "game" | Mode > Starts on > has run this ball / this game | `ball` or `game` in the `after` line |
| `start_sequence` | [] | Mode > Starts on > These shots, in order (up to 8 lists; the next appears as the last is filled) | PAD-314, with `starts_on` "sequence": one `trigger_seq <bits>` per name, in order. `validate`: 2 to 8 names, each a shot the title has (`SEQUENCE_MIN`, `SEQUENCE_MAX`). `retarget` drops a shot the new title lacks and says so |
| `sequence_reset_any` | false | Mode > Starts on > any other shot starts the sequence over | `trigger_seq_reset <bits>` of every playfield shot not in the sequence (`playfield_shots`: the cabinet buttons left out) when true and the mode starts on a sequence; nothing otherwise |
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
| `shot` | every shot dispatch, with the 64-bit mask; and, from the tick, each hit of a switch the port's `switch` lines map (MODE_SDK.md "Shots from switches", not run yet) | items 125, 134-138 (Godzilla: `0x1`, then the bit) |
| `ball_end` | the end-of-ball broadcast (event hook 0x34) | items 125, 138 (a drain on Deadpool Pro); a multiball drain or ball save is not measured |
| `event` | from the tick, within a tick of the game's own broadcast, once per firing of an event the port names, with its id (item 147) | item 147 on Godzilla Pro 1.15 and Premium 1.16 (`[pad] events: 11 of 11 named events armed, dispatch hooked`; `census_mode.c` and `mode_file.c` got game_start, ball_start, skill_shot, multiball_start and end, tilt_warning, tilt on both; on Pro also ball_end, bonus_start/end, game_over). MODE_SDK.md "Events" |

Capability flags, for `pm_can()`: `PM_CAN_CALLOUT`, `PM_CAN_LIGHTS`, `PM_CAN_SCREENS`,
`PM_CAN_CLIPS`, `PM_CAN_OWN_SOUND`, `PM_CAN_MESSAGES`, `PM_CAN_AWARD_SCREEN`, and
`PM_CAN_EVENTS` (item 147: set when at least one named event is armed), `PM_CAN_ROSTER`
(item 146: the port names the battle roster and its start is hooked), `PM_CAN_LAMPS` (item mode-leds:
the port has `lamp` lines and the game's lamp layer, and their light ids fit the game's), `PM_CAN_BLOCK_GAME` (PAD-347: the port names the starts of the game's modes a mode may refuse, and its mode table), `PM_CAN_DISPLAY_PRIORITY` (item 154 display: the port names the display lines, so the runtime can watch the game's displays; PAD-353: it never holds one back), `PM_CAN_BACKDROP` (hud-layers: the port names the background element's draw, `scene_show` and the city's vtable, both sites matched and hooked, so a mode's clip can loop behind the HUD), `PM_CAN_SWITCH_SHOTS` (the port's `switch` lines and a `switch_hit` or `switch_edge` site that matched and is hooked: a switch's hit comes to `shot` from the tick; emulator-proven on The Beatles 1.29), `PM_CAN_STOCK_RULES` (item 160: the port names the game's own rules, the manager's get and the shot slot, so a rule's shot handler can be wrapped), `PM_CAN_MULTIBALL` (item 167: the port names the framework's serve call `multiball_serve` and its count `balls_in_play`, so a mode can be a multiball of its own), `PM_CAN_SHIELD` (PAD-379: the port names Godzilla Premium/LE's shield platform motor, `site shield_move` and `data shield_motor`, so a mode can turn the shield targets toward the player; PAD-392: and keep them there while the game's own shield feature, `text shield_rule`, sees no shots), `PM_CAN_COILS` (PAD-381: the port names the coil send, `site coil_fire`, and the magnet, `value magnet_dev`, so a mode can grab with the magnet and hold the port's `held_coils`), `PM_CAN_SCOOP` (PAD-381: the port names the scoop's handler, `site scoop_handler`, its slot `data scoop_slot` and the settled-ball event `value scoop_event`, so a mode can hold a ball in the scoop), `PM_CAN_BUILDING` (PAD-393: the port names the game's building move `site building_move`, its "not now" `site building_busy`, the stepper object `data building_stepper` checked against `value building_vptr`, and its floors, so a mode can move Godzilla Premium/LE's building), `PM_CAN_GAME_SHOWS` (PAD-411: the port names the game's own light shows, `site show_<n>` with `text show_name_<n>`, and the process calls `site proc_create`, `proc_exists` and `event_cancel` with `value show_proc`, so a mode can play one of them). A port that
lacks a function switches off only its own flag (the boot log's `armed: ... can ...` line).

Kinds, for `pm_stock_mode_running()` (item 140): `PM_STOCK_ANY`, `PM_STOCK_MULTIBALL`,
`PM_STOCK_BATTLE`.

The 119 calls. "Used by": T = `template_mode.c`, P = `examples/powerline_blitz.c`,
F = `mode_file.c`, R = the runtime's own stock-rules section (item 160).

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
| `pm_running_name(name)` | PAD-363: after `pm_begin`, the name the runtime's own lines give this mode while it runs (`block: ... - BLOCKTEST is running`), for one mode object that runs several; `pm_end` forgets it | F | PAD-363, emulator (Deadpool LE 1.14) |
| `pm_begun()` | PAD-413: how many times one of our modes has begun. A mode remembers it at its end; when it moves while the ending is on the glass (its TOTAL, its own screen, a note) the ending is dropped at once. `pm_begin` also stops a full-screen clip another mode played | F | PAD-413, desk only (tests/test_spike2_mode_ending_gives_way.py, test_spike2_intricate_modes.py, test_stern_block_modes.py) |
| `pm_score_add(player, points)` | through the game's scoring and its multiplier; returns what was added | T P F | items 125-134; the multiplier's effect not measured separately |
| `pm_score_sub(player, points)` | PAD-314: takes points away - written into the game's score table, cut to the score (never below 0: the scores are unsigned, so below 0 would read as an enormous number), then the game's add is called with 0 points for its on-change work; returns what was taken | F | not measured (desk only: the harness stubs it) |
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
| `pm_aside()` | PAD-347: the kind of the game's own mode running for the player up (battle, then multiball, then any), 0 none: while it is not 0 the middle of the screen is the game's and a mode moves its words aside. Asks the game at most five times a second; 0 outside a game and on a port that cannot tell (logged once). Each change is logged (`aside: a battle is running - ...`) | F | PAD-347 (MODE_SDK.md "Stepping aside"): the examples' HUDs and a mode file's screen step aside on it |
| `pm_block_game_modes(on)` | PAD-347: while the running mode runs, the game's own modes the port names do not START: each named start (`site block_start_<id>`, the mode's own `v[8]`) is refused at its entry, checked against the game's mode table (`data block_mode_table`, `value block_mode_count`), so the mode never begins and the rule that asked carries on. On Godzilla Premium 1.16: Jet Fighter Attack and Tesla Strike (started by rules' shot handlers); and where the port names the battle rule's shot handler (`site block_battle_shots`, `value block_battle_lo` / `block_battle_hi`), it is shown the shot without the ramps and the scoop, so no battle is lit and its select screen never opens. A multiball is never refused. 1 = blocking; 0 stops; ends by itself with the mode; 0 without `PM_CAN_BLOCK_GAME`. Each refusal is logged once a hold (`block: the game's mode 21 did not start - MASER BARRAGE is running`) | `examples/intricate_kit.h` (`kit_isolate`) | PAD-347, emulator (Premium 1.16): JET FIGHTER ATTACK forced while MASER BARRAGE blocked |
| `pm_block_list(ids, n)` | PAD-363: the running mode's own list of the game's modes to hold off - n of the game's mode ids, 0-127 (the port's `block_start_<id>` lines; `text block_name_<id>` names each; an id the port does not name is left out); called before `pm_block_game_modes(1)`; n = 0: every one the port names (PAD-398; the port's `text block_default <ids>` is no longer read). 1 = taken; 0 without `PM_CAN_BLOCK_GAME` | `examples/intricate_kit.h` (`kit_isolate_list`), `mode_file.c` (`block_modes`) | PAD-363, desk |
| `pm_block_rules_keep(ns, n)` / `pm_block_rules_keep_names(names)` | PAD-398: while the calling mode blocks (from its next `pm_block_game_modes(1)`), every rule of the game's the port names (`site block_rule_<n>`, the rule's shot handler `v[25]`, hooked at its entry and shown the shot without any bit; `text block_rule_name_<n>`) sees no shots - nothing of the game's lights, locks, counts or awards - except these: n of the port's rule numbers, 0-31, or a comma-separated list of their names, any case (a blocks mode's C, written without knowing its game). Kept per mode of ours; set from the mode's own files as they are read (a mode file's `keep_rules`, a code mode's assets file), so no example needs a new call. 1 = taken; 0 without `PM_CAN_BLOCK_GAME` | `mode_file.c` (`keep_rules`), `pad_mode_assets.h` (`keep_rules`), a blocks mode's C (`KEEP_RULES`) | PAD-398, desk; the rule lines are read from each program (`game_mode_blocks.read_rules`, `rule_lines.py`) |
| `pm_multiball_start(balls, ballsave_s)` | the game serves balls until `balls` (2-6) are in play, with a ball save of that many seconds, through the framework's own start-a-multiball (`site multiball_serve`, its words read off every build's own multiballs); 1 serving, 0 refused (no game in play, a tilt) or no `PM_CAN_MULTIBALL` | F | item 167, emulator-proven 2026-09-26 on all 36 shipped builds (a mode file's `multiball` line; the item 164 provers had called the same function by hand on eleven builds) |
| `pm_multiball_add(n, ballsave_s)` | `n` more balls than are in play now, the same way | F | item 167, emulator-proven 2026-09-26 on all 36 shipped builds (the add-a-ball shot) |
| `pm_ball_save(seconds)` | a ball save with no multiball: the same call as `pm_multiball_start`, asking for the balls in play now (at least 1), with `seconds` (1-120) of ball save, as the game's own one-ball saves do (Godzilla Pro 1.15 `0xf49d0`, `0xd6a90`); 1 saving, 0 refused or no `PM_CAN_MULTIBALL` | F | PAD-225 (a mode file's `ball_save` line) |
| `pm_shield(where)` | PAD-379: Godzilla Premium/LE's shield platform: `PM_SHIELD_TOWARD` turns the shield targets to the flippers, `PM_SHIELD_AWAY` back to the game's home (the spinner side to the player), through the game's own motor's go-to (`site shield_move`, the object `data shield_motor`, checked against `value shield_motor_vptr` before every move); 1 turning (about a second) or already there, 0 the motor switched off in the adjustments, no platform (a Pro: its shields are fixed) or no `PM_CAN_SHIELD`. PAD-392: the runtime's limits, none the mode's to raise - only the running mode, in a game, never while one of the game's own modes or multiballs runs (`pm_aside`); 1.5 s from one move's start to the next and 12 moves a minute (a call that finds it already there moves nothing and counts for neither); refused = 0 and the reason in mode.log. When the mode ends, the ball ends, or the game ends or tilts, the runtime turns it back where it was before the mode's first move, unless the game has sent it somewhere of its own or one of its modes or multiballs runs. PAD-409: from the mode's first move until then, the motor's own background return to the game's resting place (`site shield_update`, ShieldMotor `v[0]`, every ~3 s) is skipped for the shield motor - not while one of the game's modes or multiballs runs, and never its ball search or its own motor processes | `examples/intricate_kit.h` (`kit_shields_in` / `kit_shields_out`) | PAD-379; the limits and the put-back PAD-392, emulator (`shield_test_mode.c`) |
| `pm_shield_position()` | `PM_SHIELD_AWAY` / `PM_SHIELD_TOWARD` once the platform has stopped there (the switch the motor last stopped on is the one it was sent to), 0 while it turns, -1 no platform | `examples/intricate_kit.h` (`kit_shields_reachable`) | PAD-379 (MODE_SDK.md "The shield platform") |
| `pm_shield_keep(where)` | PAD-392: `pm_shield(where)` now, and the platform KEPT there while the mode runs: found resting elsewhere for 1.5 s (the game's ball search swings it toward and away every 12 s while no switch closes, and leaves it away) it is turned back, within `pm_shield`'s limits. Only while the game's own shield feature sees no shots (the port's `text shield_rule`, one of its `block_rule_name_<n>`: blind while a mode of ours blocks and does not keep it counting, PAD-398) - while it counts, the game turns the platform back about 2 s after every move, and the mode turns it once and leaves it to the game rather than fight it ("shield: left AWAY - the game's own shield feature counts shots"). 0 = stop keeping (it stays where it is); the mode's end stops it too and the put-back follows. 1 = keeping; 0 = no platform or not the running mode | `mode_file.c` (`shield`), a blocks mode's C (Turn the shield targets), `shield_test_mode.c` | PAD-392 and PAD-409 (the background return held: kept toward 30 s after 30 spins of the shield ramp spinner, where without it the game turned it back every ~3 s), emulator (stock Premium/LE 1.16: kept through two ball searches and three shield hits; with Mechagodzilla Shield kept counting the game turned it back in 2 s and it was left there) |
| `pm_building(floor)` | PAD-393: Godzilla Premium/LE's building to a floor, 0 (where the game rests it, beside its home switch) to 3 (the furthest the game sends it), through the game's own move (`site building_move`, the object `data building_stepper`, checked against `value building_vptr` before every move), at the operator's building speed settings, so it never goes past the game's own travel. Refused (the reason in mode.log) unless the mode runs in a game, while the game says not now (`site building_busy`: moving, homing, one of its own building sequences), when the building is switched off or faulted, within 3 s of the last move, past 6 a minute, or to a floor outside 0-3; put back on the floor it was at before the mode's first move when the mode, the ball or the game ends, unless the game has moved it since. 1 sent (or already there), 0 refused or no building (a Pro, or a port without the building lines) | `building_test_mode.c` | PAD-393, emulator (a stepper model in the rig, tests/test_spike2_stepper.py); MODE_SDK.md "The building" |
| `pm_building_floor()` | the floor the building is stopped at, -2 while it moves (or before the game has homed it), -1 with no building | `building_test_mode.c` | PAD-393 |
| `pm_game_show(n)` | PAD-411: plays the game's own light show n of the port's list (`site show_<n>`: a show process's body, run as the runtime's process `value show_proc`, so its timing, colours and clean-up are the game's). One at a time (a new one replaces one still playing); stopped at the port's `value show_secs_<n>` (20 s at most: some run until stopped). Only while the mode runs, or in the first 2 s after it ended (its ending's show), in a game, and not in the 3 s after a ball ends (the game stops every process of its own then). 1 = playing | the ten Godzilla examples (through `kit_game_show`), `show_reel_mode.c` | PAD-411, emulator (stock Premium/LE 1.16: every listed show played from a mode, what each did to the LEDs measured) and David's Premium (two machine tests) |
| `pm_game_show_named(name)` | the same by the port's name for it (`text show_name_<n>`, any case); 0 when this game names no such show | the ten Godzilla examples | PAD-411 |
| `pm_game_show_stop()` | stops the show playing now: the game's own exit hook takes its lights away | `show_reel_mode.c` | PAD-411 |
| `pm_game_show_playing()` | 1 while a show of the runtime's plays | `show_reel_mode.c` | PAD-411 |
| `pm_game_shows()` | how many shows the port names (0 = none on this game) | `show_reel_mode.c` | PAD-411 |
| `pm_balls_in_play()` | the framework's count of the balls in play (while a multiball is being served, the balls it asked for); -1 without `site balls_in_play` | F | item 164 (the stack route on the titles with no cmode rules, 12 builds), item 167 |
| `pm_magnet_grab(ms)` | PAD-381: the playfield magnet for `ms` (100-5000, the draw included) as ONE coil command the board ends by itself: the operator's LO draw power for the draw time, then the LO hold power; never re-sent. Refused (0, the reason in mode.log) unless the running mode, in a game, the magnet not disabled, none of the game's magnet sequences running, no grab holding, 3 s since the last ended, fewer than 6 in the last minute. Sent from a game process of the runtime's (`value magnet_proc`) that takes control of the magnet the way the game's own grabs do, so the game's coil update does not switch it off; it gives control back to let go, and the game's update then switches the magnet off. Let go at the end, on `pm_magnet_release`, mode end, ball end, game end or tilt, and when the game ends the process (a drain); gives the magnet back when the game's own magnet starts | `magnet_test_mode.c`, `mode_file.c` (`magnet`) | PAD-381, emulator (Pro 1.16 and Premium/LE 1.16): held to its end, a hit mid-grab refused with no OFF from the game, a mode stop and a drain mid-grab let go early with no abort; the clamp and the refusals (the first, tick-fired version was switched off by the game 1 ms in: MODE_SDK.md "The magnet") |
| `pm_magnet_release()` / `pm_magnet_holding()` | let go now (an OFF); 1 while a grab holds | `magnet_test_mode.c` | PAD-381 |
| `pm_coil_hold(name, ms)` / `pm_coil_release(name)` / `pm_coil_holding(name)` / `pm_coil_known(name)` | PAD-381: the magnet's hold for any held coil the port names: ONE command at the coil object's own powers (its v[29] pulse power, v[30] pulse ms, v[31] hold power), 100-5000 ms, from a process of the runtime's that controls the coil; refused while the operator has it disabled (v[40]) and while the game uses it (a process of the game's controls it, +44; the game asked for an on-time, +36; or a process the port names, `text <name>_procs`); given back at once when the game wants it mid-hold. `pm_magnet_grab(ms)` is `pm_coil_hold("magnet", ms)` | `mode_file.c` (`coil_hold`) | PAD-381, emulator (Premium/LE 1.16): the Mechagodzilla magnet and the bridge held to their ends, a hit mid-hold refused, a mode stop let go |
| `pm_scoop_hold(ms)` | PAD-381: while the running mode runs, a ball that settles in the scoop is held `ms` (100-10000; 0 = no hold, and a held ball goes) once the game's own handler is done with it, then the game kicks it out. The runtime swaps the pointer to the game's handler in the scoop's device record (`data scoop_slot`, checked to point at `site scoop_handler`) for a wrapper that runs the handler, then on the settled-ball event (`value scoop_event`) sleeps a tick at a time in the device's own process. 1 = set; 0 not the running mode or no `PM_CAN_SCOOP` | `mode_file.c` (`scoop_hold`) | PAD-381, emulator (Pro 1.16 and Premium/LE 1.16): held its time, the control kicked at the game's own time, a mode end and a tilt let go, no abort |
| `pm_scoop_release()` / `pm_scoop_holding()` | let a held ball go now (the game kicks it); 1 while a ball is held | none | PAD-381 |
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
| `pm_sound_swap(request, stock, ours, priority, ms)` | for ONE play, every lookup of the carrier's own record key `stock` takes `ours` instead (a record the build appended that no descriptor names) and `request` plays at `priority` without the steal flag; the key and priority come back by themselves once `ms` (+1/8 +1 s; 10 s when 0) have passed. Call it right before `pm_sound(request)`; `ours` must be no longer than the carrier's own record. 1 = armed; 0 without the port's sound_lookup site (then do NOT play) | F | not measured on a machine yet; the emulator's per-title sound-call runs (item 163) |
| `pm_hit_sound(n)` | PAD-415: plays the n-th of the port's rising run of the game's own hit sounds (`value hit_sound_<n>`; past the last, the last), never two within 100 ms. While one of ours runs the game's rules see no shots and play none of their own sounds for them. 1 = played | F (a scoring shot: one higher a hit), the kit's `kit_hit` | PAD-415: on Premium/LE 1.16 the Sound Test's PITCHED HIT ORCH 1-8 (367-374), the menu ids proven to be the requests by a census of the stock game's shots; emulator (six KIRYU hits played 367 to 372) |
| `pm_hit_sounds()` | how many hit sounds the port names (0 = none: nothing plays) | F, the kit | PAD-415 |
| `pm_sound_playing(requests, buses, max)` | the request and bus bits of every channel playing now; how many play, -1 without the port's `data sound_channels` | F | desk; the same channel fields read by `sound_fire_mode.c`'s dump in X1 (`ch 7:125 p1 f1 b01`, `ch 7:1251 p2 f0 b02`) |
| `pm_lamp_count()` | how many inserts the port's `lamp` lines name; 0 without `PM_CAN_LAMPS` | `lamp_probe.c` | item mode-leds RUN 5: 88 on Premium 1.16 |
| `pm_lamp_at(i, &shots)` | the i-th insert's name and the shot bits the game ties to it | `lamp_probe.c` | desk (`tests/test_spike2_mode_lamps.py`) |
| `pm_lamp_find(name)` | an insert's index by name, any case; -1 | none | desk |
| `pm_lamp_set(names, rgb, pattern, ms)` | holds one insert or a comma-separated list in a colour (`PM_RGB(r, g, b)`) and a pattern (`PM_LAMP_SOLID`, `PM_LAMP_BLINK`, `PM_LAMP_PULSE`, `PM_LAMP_CHASE` across the list); returns how many it holds. Held inserts show that over the game's shows; everything else stays the game's | F `lamp_probe.c` | item mode-leds RUN 5 on Premium 1.16: the decoded node bus (MODE_SDK.md) |
| `pm_lamp_shot(shots, rgb, pattern, ms)` | the same for every insert the port ties to these shot bits | F `lamp_probe.c` | item mode-leds RUN 5 |
| `pm_lamp_all(rgb, pattern, ms)` | the same for every insert the port names (a mode's Lights on a title without the light language) | F `mode_file.c` (`light_all`) | item 164 (19 builds, the shim's LED view) |
| `pm_lamp_xy(i, &x, &y)` | the i-th insert's place on the playfield picture, from the port's lamp comment (`at X,Y`); 0 when the port does not say | `examples/intricate_kit.h` (light shows) | hud-layers run t1/t6: 83 of Premium 1.16's inserts placed, the shows swept across them |
| `pm_lamp_paint(i, rgb)` | holds ONE insert solid in a colour, quietly (no log line): a light show's frame | `examples/intricate_kit.h` (light shows) | hud-layers run t1/t6 (the shim's LED view: the start and end shows over 83 inserts and 4 GI strings) |
| `pm_lamp_release(names)` | hands inserts the calling mode holds back to the game at once; how many | `lamp_probe.c` | item mode-leds RUN 5 |
| `pm_lamp_release_shot(shots)` | the same for a shot's inserts | none | desk |
| `pm_lamp_release_all()` | every insert the calling mode holds | F `lamp_probe.c` | item mode-leds RUN 5 |
| `pm_lamp_flash(shots, rgb, ms)` | PAD-415: a hit answers - the inserts of `shots` strobe `rgb` (60 ms on, 60 off) for `ms` (480 when 0, 2000 at most) over whatever the mode holds them in, then show it again; one it does not hold is held for the strobe only and handed back after it; one it releases mid-strobe finishes the strobe first. How many strobe | F (a scoring shot), the kit's `kit_hit` (every example's counted hit) | PAD-415, emulator (stock Premium/LE 1.16 card build: the shim's LED view had the hit insert's three channels flip 11 times in the 1.2 s after the hit) |
| `pm_lamp_priority(p)` | the calling mode's lamp layer priority, 1-255 (255 when never called); its held inserts move to that layer | F `lamp_probe.c` | item mode-leds RUN 5 (`prio 1` put the game's own layer back on MASER in a battle) |
| `pm_lamp_layers(prio, max)` | the game's lamp layers now, bottom to top, 0x100 added for ours; -1 without the port's layer list | `lamp_probe.c` | item mode-leds RUN 5 (the layer lists in MODE_SDK.md) |
| `pm_display_priority(priority)` | PAD-353: the running mode's display priority (1-255) is NOTED, 0 gives it up; nothing of the game's is ever made to wait, refused, dropped or hidden for it (a held Magna-Grab screen kept Godzilla's magnet on). 1 = noted (the runtime watches the game's displays for `pm_display_covered`); 0 without the port's display lines or when the mode is not running | F | item 154 display: Premium 1.16 r2-r6, Pro 1.15 r5 (the hold); withdrawn by PAD-353 (MODE_SDK.md "Display priority") |
| `pm_display_covered()` | 1 while a display of the game's has the screen - an effect over the layered display, or any layered foreground (a framed award's words sit where a mode's title does) - for the mode that noted a priority; a mode keeps its words off the glass while it is 1 | none (`display_test_mode.c`); `examples/intricate_kit.h` (PAD-353) | item 154 display r4; PAD-353 (every game display counts now: none is held back) |
| `pm_end_holding(ms)` | the running mode ends (as `pm_end`: another may begin at once) and `pm_display_covered` keeps watching for `ms` more, for its ending clip and total; given up when the time is over, another mode begins or the game ends. Nothing of the game's waits for it (PAD-353) | `examples/intricate_kit.h` (`kit_end_after`) | hud-layers run t8; PAD-353 (nothing of the game's waits for it) |
| `pm_backdrop(name)` | loops the named clip BEHIND the HUD, in the main-play background's place (the game's own background route); `0` or "" takes it away. 1 = asked for; 0 without `PM_CAN_BACKDROP` | `pad_mode_assets.h` (a mode's `loop` clip) | hud-layers h12 and b1 (Premium 1.16: the clip full screen under the score panel and top bar, no render gap) |
| `pm_backdrop_once(name)` | plays a clip once in the loop's place, then the loop again | `pad_mode_assets.h` (`pa_clip_event`) | hud-layers b1, t6 (the sever, barrage, jackpot clips behind the HUD) |
| `pm_backdrop_showing()` | 1 while the backdrop is on the glass | `backdrop_test_mode.c` | hud-layers b1 |
| `pm_stock_rule_count()` | how many of the game's own rules the port names (`rule` lines); 0 without `PM_CAN_STOCK_RULES` | none | item 160: desk (the port readers in `tests/test_spike2_stock_remap.py`); 2 on both Godzilla ports |
| `pm_stock_rule_at(i, &id, &label)` | the i-th rule's id and label | none | item 160: desk |
| `pm_stock_rule_object(rule)` | the rule's object through the manager's get, checked against the port's vtable word; 0 until the manager is built | R | item 160: Premium 1.16 (the wrap line `rule 12 Battle vs Ebirah obj 0x7b53f0 vtable 0x636d78: shot v[42] 0x816e8 wrapped`); see MODE_SDK.md "Counts as" for the run |
| `pm_stock_rule_active(rule)` | the rule's own active query for the player up: 1 / 0, -1 unknown | R | item 160: Premium 1.16 (the stand-in insert follows it: held while the battle runs, handed back at its stop) |
| `pm_stock_rule_field(rule)` | the rule's per-player lit mask (the u64 at obj + `stock_field` + 8 x player) | R | item 160: Premium 1.16 (the field in every `counts as` / `passed through` line matches the probe's) |
| `pm_stock_rule_hook(rule, fn)` | wraps the rule's shot handler for the caller: `fn(rule, &shot, obj)` sees every shot first, may change it, returns 1 to run the game's handler with it or 0 to keep it from running (item 161's route) | none | item 160: desk only (the wrap itself is the counts-as wrap, proven in the run; a C hook has not run) |
| `pm_stock_rule_unhook(rule)` | the hook is gone; the wrap stays and passes through | none | item 160: desk only |
| `pm_stock_counts_as(rule, from, to)` | a counts-as row from C, kept across `stock.cfg` reloads; `to` = 0 removes; `to` must be ONE bit outside `from` | none | item 160: desk only (the file's rows go through the same table and decision, proven in the run) |

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

## 4b. `stock.cfg`: the game's own rules take another shot (item 160)

Not a mode file: one file beside them (`/usr/local/padmode/stock.cfg` on a card, `/dump/stock.cfg` in
the rig), read by the runtime itself twice a second and re-parsed when its bytes change, so an
edit lands in a running game. The Modes tab's "Counts as…" table writes it (the rows live in the
project as `modes/stock.json`; Write and Try it carry the rendered file with the modes). A `#` at the
start of a line, or after a blank on a row, begins a comment (the runtime strips it before reading
the row). MODE_SDK.md "Counts as" says how it works and what was measured.

| Key | Value | Absent | What it does | Tab | Measured |
|---|---|---|---|---|---|
| `counts_as` | `<rule id> <shot> -> <shot>` (shots: the port's names, any case, or `0x` masks), up to 16 rows | none: every rule stock | while the rule runs and the target bit is lit in its own mask, a dispatch whose bits are all inside the first shot is REPLACED by the target bit (one bit; never ORed in); once the rule clears the bit the shot passes through untouched. A rule the port does not name, a shot it does not name, a target of more than one bit or one inside the first shot is logged and ignored | Counts as… > Add | item 160 on Premium 1.16 (MODE_SDK.md "Counts as": the Left ramp entering Ebirah's handler as 0x200, the count falling, the file removed and put back mid-battle) |
| `light` | `<rule id> <colour> [solid\|blink\|pulse] [ms] [on ms]` | yellow blink 500 ms, 300 on | the stand-in's inserts (the first shot's, from the port's `lamp` lines) while the target bit is lit, on the runtime's own lamp layer at priority 255; handed back when the bit clears or the rule stops | no | item 160: the default (LEFT RAMP yellow while 0x200 is lit; off once the count is 0) in the run; a `light` line: desk only |

## 4c. `pad_stock.h`: a rule's shot logic rewritten in C (item 161)

Beside the counts-as table, a CODE MODE of the project may replace one rule's shot handler outright:
`PM_STOCK_HANDLER(<rule id>, fn)` (or a `struct pm_stock_handler` record with `started` / `stopped`
callbacks) in `modes/<folder>/<folder>.c`, against `pad_stock.h`. The handler returns `PM_STOCK_DONE`
(the game's handler is not run for that shot) or `PM_STOCK_PASS`; `pm_stock_call_original` replays the
game's own handler with a shot of the C code's choosing. Every accessor (the rule's lit mask, its own
counters, an award as the handler pays one, a show, a game event, STOP; Ebirah's stage award and final
blow; tank's records) reads its slot, offset or address from the port's `stock_*`, `ebirah_*` and `tank_*`
lines. The Modes tab's "Rewrite in C..." dialog makes such a folder from the SDK's example for the rule
(`examples/ebirah_rewrite.c`); Write carries it as every code mode. MODE_SDK.md, "Rewriting a stock rule's
shot logic", has the calls and what is emulator-proven.

## 5. Keys other items reserve (not in this runtime yet)

Each lands as its own rows in sections 1 and 2 when its item merges (item 139's `starts`
and `cooldown`, item 140's `stack`, item 142's film fields, item 147's `starts_on` and
`ends_on` and item 150's own sounds have: they are rows above now).

| Key / field | Item | What it is for |
|---|---|---|
| (none left) | | |


## 6. The game's own modes: their shots as data (item 159)

The Modes tab's "The game's own modes" dialog edits numbers of the modes the game shipped with
(item 145: awards, timers). Item 158 measured that the lit mask it could also stage does nothing for
tank attack multiball (its shots are a path table the tanks walk) and battle vs Ebirah (its start
rebuilds the mask from spin counts). Item 159 replaces that with what the two rules really play,
on Godzilla Premium/LE 1.16 and Pro 1.15; see MODE_SDK.md, "Stock mode shots as data (item 159)".

| Row (Modes tab) | Value | Stock | What it does | Measured |
|---|---|---|---|---|
| Tank Attack Multiball, Position 1..6 | a shot picked by name, or none (positions 2 and 4 only; 1, 5, 6 are where tanks appear and 3 is where they head: read-only, the row says why) | bit 35, Left ramp, Godzilla target, Top spinner, Right ramp, bit 37 | the six-entry path the tanks walk toward position 3; a hit on the entry a tank stands on destroys it. None = the entry copies its neighbour away from the goal, so the walk skips it. The counted-shots words and the spot list follow | position 4 = none: emulator-proven on Premium/LE 1.16 (item 158 live-3, item 159 edited1); another shot: desk only |
| Battle vs Ebirah, Left / Top / Shield ramp spinner spins | 1 to 255 | 15 / 40 / 15 | how many spins of that spinner the battle needs before its stage award (5M / 10M / 15M by completion order) | left = 5: emulator-proven on Premium/LE 1.16 (item 159 edited1); top and shield: the same one-word edit, desk |

The rows go through the one patch set every Write path shares (the image Write, Direct SD, the
emulator's override set), behind the preview switch; back to stock writes the stock words byte for
byte, the family's included.
