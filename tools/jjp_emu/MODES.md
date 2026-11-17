# JJP mode SDK: custom modes for JJP games (PAD-1335, PAD-1337)

A custom mode runs **inside** a retail Jersey Jack game, from outside its
binary: started by the game's own switches, timed by the game's own mode timer,
scored through the game's own scoring, lit through the game's own lamp layers,
drawn with the game's own fonts, and stepping aside for the game's own modes.
No game code is patched. How and why it works: `docs/plans/jjp_custom_modes.md`.

| Piece | File |
|---|---|
| Runtime, preloaded into the game | `jjpmodes.c` (build: `buildmods.sh`) |
| What a title offers, read off its binary | `jjpport.py` -> `modes/ports/<title>.json` |
| Starter modes per title | `modes/examples/<title>/` |
| Install ISO with modes, for a real machine | `mkjjpmodes.py build` |
| Check a mode folder | `mkjjpmodes.py check --modes DIR --port PORT.json` |
| Change the game's OWN modes | `<name>.stock` files in the same folder (PAD-1351, below) |
| A running game's mode globals and shot names | `jjpstock.py live` -> `modes/ports/<title>.live.json` |
| Starter `.stock` file per title | `modes/stock_examples/<title>/` |
| Make, check and build them in the app | the **Modes** tab on a JJP game (`webui/modes_jjp.py`, PAD-1350) |
| A mode's own rules in C++ (or blocks that write it) | `code = <name>`, `modes/sdk/jjp_mode.h`, `build_code.sh` (PAD-1384, below) |

## In the app (PAD-1350)

On a Jersey Jack game the app's **Modes** tab is this SDK's editor. It lists every
title whose port report is in `modes/ports/`, the ones that can run modes first
(the others greyed, with why). Picking one opens the person's own mode folder for
it, kept in the app's settings folder (`jjp_modes/<title>/`) and seeded from the
title's starter folder the first time. Each mode is a form over the keys below:
every switch, lamp, lamp group, sound and font is picked from the port report's
lists, so a mode cannot name something the game lacks; an empty key shows what it
inherits (title.cfg, else the runtime default). Every edit is saved to the `.mode`
file at once and checked with `check_modes` against the port report. **Hear
sounds from** points at the title's extract folder: a game's `se_X` is the
extract's `X.wav` (2,690 of Wonka's 2,723 match). A mode's own sound, music,
picture and video files go in that folder (**Open the mode folder**); the sound
keys then offer them beside the game's sounds, and the **Picture and video** group
and the music key pick from them (PAD-1352). **Build** runs `mkjjpmodes.py
build` as root in the app's Linux on the stock ISO it finds beside the Select card
pick (or `D:\Pinball\images\JJP`), with its scratch in
`/var/tmp/pad_jjpmodes_work`; Cancel stops it inside Linux, where it unmounts and
deletes its scratch.

**Write to USB stick** (PAD-1375) writes the stick below from the same folder:
the stick is the first removable drive Windows has (or any folder, to copy to
one), and **The stick** picks install, off, on or remove; the card lists the
steps at the machine. An install stick needs the runtime built against the
game's glibc: the tab runs `mkjjpmodes.py runtime` as root in the app's Linux on
the stock ISO picked under Build, once per ISO (kept as
`jjp_modes/.runtime/<iso>-<key>.so`, the key over the ISO's path, size and date
and `jjpmodes.c`, so a new runtime source builds again); the stick itself is
plain files written in-process. A stick carrying a hot fix that is not one of
ours is never written over; one of ours is replaced.

## A mode folder

One folder per title: `title.cfg` (optional, title-wide defaults) and one
`<name>.mode` per mode, up to 24, loaded in file-name order. Both are
`key = value` lines; `#` starts a comment. Names (switches, lamps, sounds,
fonts) are the game's own exported symbol names: the title's port JSON lists
every one, and `mkjjpmodes.py check --port` catches a typo before it reaches a
machine.

```
# 1_jam_session.mode
name = Jam Session
title = JAM SESSION
start = switch_target_jam
shots = switch_target_jam switch_ramp_left_made switch_prox_ramp_right_made
points = 1000000
seconds = 25
complete = 3
complete_points = 5000000
sound_start = se_FX_GnR_GenericCrowds_IncreasinglyLargerCheerExcitement_3
sound_shot = se_Fanfare_GnR_Amps_Jackpot
sound_complete = se_Fanfare_GnR_Amps_TripleJackpot
sound_end = se_FX_GnR_GenericCrowds_DifferentLengthCheers_3sec
lamps = lp_target_jam lp_center_loop_arrow
lamp_color = ff2000
lamp_blink = 4
```

### Mode keys (also allowed in title.cfg as defaults)

| Key | Default | Meaning |
|---|---|---|
| `name` | file name | the mode's name (log, engine Mode name) |
| `title` | `name` | the line drawn at the top of the mode panel. A game font may lack punctuation: GnR's Slash Solo font draws `-` and `!` as other marks |
| `start` | none | switch(es) that start the mode, space separated. A mode needs this or one of the start rules below |
| `start_count` | 1 | starts needed: start-switch hits, or times a start rule fires (e.g. `start_after = gobstopper_mb` with `start_count = 2`: after the second Gobstopper multiball) |
| `start_count_reset` | game | `game`: the count carries over between balls and resets at a new game; `ball`: it resets every ball |
| `start_on` | none | start on a game event, any of: `ball_start`, `first_ball`, `last_ball`, `valid_playfield` (the first playfield switch of a ball), `ball_saved`, `extra_ball` (one awarded), `multiball_end` |
| `start_after` | none | start when one of these game modes ends: the game's mode globals (e.g. `mtv_mode`) or Mode classes, or `any` |
| `start_score` | none | start when the player up's score reaches this, once per player per game |
| `start_combo` | none | two or more switches hit in this order, each within `combo_seconds` of the one before |
| `combo_seconds` | 5 | whole seconds |
| `start_once` | no | `ball` or `game`: start at most once a ball or once a game |
| `shots` | `start` | switches that score while it runs |
| `points` | 1000000 | per scoring shot, through the game's own Mode::score_and_total |
| `seconds` | 20 | the game's own mode timer |
| `complete` | 0 | scoring shots that complete the mode (0 = it runs to time) |
| `complete_points` | 0 | added on completion |
| `sound_start`, `sound_shot`, `sound_complete`, `sound_end` | none | the game's `se_*` sounds, or a sound file of the mode's own in the folder (`.wav`, `.ogg`, `.flac`, `.opus`) |
| `sound_channel` | fanfare | the game channel the mode's own sound files play on: `fanfare`, `fx`, `speech` or `music` (its volume and ducking) |
| `sound_like`, `music_like` | none | a game `se_*` whose settings (channel, gain, play mode) the mode's own sounds or music take, instead of the channel's first |
| `music` | none | a music file of the mode's own (`.ogg`, `.wav`...): the game's music while the mode runs, the game's own music back after |
| `picture` | none | a picture of the mode's own (`.png`, `.jpg`), drawn while the mode runs |
| `picture_at` | 0 0 100 100 | where: `x y w h` in percent of the screen; the picture keeps its shape, centred in that box |
| `video` | none | a video of the mode's own (`.webm` VP8/VP9, the game's own clip format; `.mkv`, `.mp4` H.264 also play), silent, drawn under the picture |
| `video_at` | 0 0 100 100 | where, as `picture_at` |
| `video_loop` | yes | `no` plays it once and keeps its last frame |
| `lamps` | none | `lp_*` lamps (or `ls_*` lamp groups) the mode lights |
| `lamp_color` | ffffff | rrggbb |
| `lamp_blink` | 4 | flashes a second; 0 = solid |
| `font_title`, `font_value`, `font_timer` | none (built-in font) | the game's `font_*` fonts for the title, the mode total and the seconds left |
| `title_color`, `value_color`, `timer_color` | ffffff, ffdc00, ffffff | rrggbb or rrggbbaa |
| `panel_color` | 000000b0 | the panel behind the text, rrggbbaa |
| `panel` | middle | `middle`, `bottom` or `top` (the game's score panel is at the bottom on most titles), or `none` (no text panel: the mode's picture or video says it) |
| `game_modes` | hold | `hold` (PAD-1348): while this mode runs, a start of the game's that goes through its class's start or restart (on Wonka 03.03: the multiballs, proven with the Gobstopper multiball) is refused and the game carries on as if it was not asked. Some game modes start another way (Wonka's Oompa hurry-up, Wonka Wash Frenzy) and are not held: this mode pauses for them, as `pause` does, and resumes after. Or the older choices for when a game mode or multiball runs: `pause` (timer held, shots not scored, panel hidden, lamps handed back), `end`, or `ignore` (none of these refuse the game's starts) |
| `hold_multiballs` | yes | with `hold`: `no` lets the game's multiballs start (and pause this mode) |
| `allow_game_modes` | none | with `hold`: the game's mode globals or classes (e.g. `mtv_mode`, `OompaHurryUp`) that may still start |
| `multiball` | none | `<balls> [ball save s]` (PAD-1353): 2-6 balls in play, ball save 0-120 s (10 when absent). When the mode starts the game serves balls until that many are in play, and serves back any that drain inside the ball save. One ball (or none) for 2 s, once the ball save and 3 s more have passed, ends the mode (`one ball left`). With `seconds = 0` the mode has no clock: only that, or the ball's end, ends it |
| `multiball_on` | the start | with `multiball`: switch(es) whose first hit while the mode runs serves the balls, instead of the start. The mode's `seconds` is the time to hit it; once the balls come the clock stops and one ball left ends it |
| `add_ball` | none | `<switches> [times]`: each hit while the mode runs asks the game for one more ball, up to `times` (1-6, 1 when absent) a run, with the multiball's ball save (2 s, the game's own, when shorter). Works in a mode without a `multiball` line too |
| `ball_save` | none | `<s>` (1-120): when the mode starts, a ball that drains in that time is served back. Ends with the mode, unless the game raised the save past ours (then the game's runs on) |
| `coil_start`, `coil_shot`, `coil_complete` | none | `<coil> [ms]`: pulse that coil when the mode starts, on each scoring shot, on completion. `ms` can only shorten the coil's own pulse (the time the game built it with) |
| `coil_hold` | none | `<coil> <ms> [power]`: hold a magnet, diverter, post, gate, shaker or light on for 100-5000 ms, on `power` of every 32 steps (1-16, 8 when absent). Off at its time, at the mode's end or pause, at the ball's end. Needs `coil_holds = on` in title.cfg |
| `coil_hold_on` | shots | `shots` (each scoring shot), `start`, or switch(es) of its own |

### title.cfg only

| Key | Meaning |
|---|---|
| `game` | the title's GAMENAME (e.g. `GunsNRoses`). The modes load only into that game: a mode ISO made from a multi-boot ISO hooks root A, which also starts image 1's game |
| `ingame_state` | the `jjpe_state_get()` value meaning "a ball is in play" (5 on Guns N' Roses). Without it the runtime learns it on the first ball: the state that holds for a second while the game's own ball-in-play flag is set (logged) |
| `background_modes` | game modes that are always on and must not make a custom mode yield. Without it, the game modes already running two seconds into a ball count as always-on |
| `coil_holds` | `on` lets this title's modes hold coils (`coil_hold`). Off by default: a hold is a coil kept energised, so it is turned on per title once it has been watched on that machine. `mkjjpmodes.py check` names a `coil_hold` without it |

## Balls and coils (PAD-1353)

Everything goes through the game's own engine, the same exported calls on every
title that can run modes (`can_balls` and `can_coils` in its port report):

* **Balls.** The engine keeps one ball saver: "keep N balls in play for T".
  `mb_request_balls_into_play(N, T)` starts it or raises either, and while it
  runs it serves balls until N are in play and serves back any that drain. Read
  off Wonka's decrypted code, the game's own ball save is that call with the
  balls in play now, and its add-a-ball is `mb_add_balls_into_play(1, 2 s)`; a
  mode's `multiball`, `ball_save` and `add_ball` are the same calls. A multiball
  of the mode's own does not make it pause (the game's multiballs still do).
* **Coils.** A coil is a named `coil_*` global in the engine's `coil_table`. A
  pulse is `Coil::coil_pulse`; a hold is `Coil::coil_duty(ms, pattern, 32)`:
  the game's realtime loop plays the 32-step on/off pattern for that long and
  then turns the coil off itself, so the engine bounds every hold even if the
  runtime stopped (measured on Wonka 03.03). The runtime ends a hold sooner
  when it should, and at its time at the latest, from a watchdog thread of its
  own that checks every 5 ms and does not depend on the mode ticking (the game
  stops a mode's run proc at the ball's end); `Coil::coil_off` turns it off.

The limits are in the runtime; no mode file can raise them (the guardrails of
Spike 2's PAD-381):

| Limit | Value |
|---|---|
| Coils a mode may never fire | the game's own ball handling, flippers and power, by name: `flipper`, `trough`, `autolaunch`, `auto_launch`, `autoplunge`, `plunger`, `sling`, `jet`, `bumper`, `stepper`, `relay`, `power`, `ticket`, `null`, `motor` (the shaker motor excepted), and whatever coil the game's `hook_trough_coil`, `hook_autoplunger_coil` or `hook_trough_jam_coil` names |
| Coils a mode may hold | names with `magnet`, `divert`, `post`, `gate`, `shaker`, `flash`, `lamp`, `light` or `led`; every other allowed coil is pulse only |
| A pulse | never longer than the coil's own pulse (1000 ms at most); 250 ms between two pulses of one coil; 20 a minute per coil |
| A hold | 100-5000 ms, timed by the engine itself; at most 16 of 32 steps on; 3 s off between holds of one coil; 6 a minute per coil |
| Off | at its time, the mode's end or pause, the ball's end (tilt included), from the watchdog |
| The game always wins | a coil the game is driving is not fired or held (`the game is driving it`); a hold the game takes over is left to the game, with no off sent over it |
| No ball in play | nothing is fired or held |

The port report lists every named coil with what a mode may do (`coils`:
`pulse`, `hold`), by the same name rules (`jjpport.py` `COIL_NEVER`,
`COIL_HOLDABLE`, `COIL_ANYWAY`; a test keeps them equal to the runtime's), and
`mkjjpmodes.py check --port` refuses a coil the mode may not use.

## A mode's own rules: C++ and blocks (PAD-1384)

A mode file's keys are its settings. Rules of its own (a bonus that grows, a shot
it takes over, more time at the fifth shot, a start of its own) are C++: the
line `code = <name>` makes the runtime load `<name>.so` from the mode folder,
built from `<name>.cpp` against `modes/sdk/jjp_mode.h`:

```cpp
#include "jjp_mode.h"
static long long bonus;
static void start() { bonus = 0; jm_title("CODE RUSH"); }
static void scored(const char *sw) { bonus += 250000; jm_score(bonus); }   // after the form scored it
static int shot(const char *sw) {                                         // any switch while it runs
    if (jm_is(sw, "switch_ramp_left_made")) { jm_score(7777777); return JM_TAKEN; }
    return JM_GO_ON;                                                      // the form's own handling goes on
}
JM_REGISTER({ .api = JM_API, .start = start, .shot = shot, .scored = scored });
```

| Callback | When |
|---|---|
| `start()` | it has just started (after the form's start sound, multiball, coil) |
| `shot(sw)` | any switch while it runs: `JM_TAKEN` = the form scores nothing for this hit |
| `scored(sw)` | after the form scored one of its scoring shots |
| `tick()` | ten times a second while it runs (not while paused) |
| `end(why)` | it is over: `time`, `completion`, `its code`, `ball end`... |
| `idle(sw)` | any switch in a game while it is NOT running: `jm_start()` starts it (no start rule needed) |

Calls: `jm_score`, `jm_total`, `jm_hits`, `jm_switch_hits`, `jm_seconds_left`,
`jm_set_seconds`, `jm_add_seconds`, `jm_ms`, `jm_end`, `jm_start`, `jm_running`,
`jm_title` (the panel's title this run), `jm_sound`, `jm_lamp` / `jm_lamp_off`
(the mode's own lamp layer), `jm_coil` (the coils a mode may fire, with the
form's limits), `jm_multiball`, `jm_ball_save`, `jm_log`. Each acts on the mode
whose callback is running, on the game's proc thread.

**Built to load on every image.** `modes/sdk/build_code.sh` (or `mkjjpmodes.py
code --modes DIR`, which builds the changed ones and installs g++ as root the
first time) links the library against nothing: its libc calls and the
runtime's `jm_*` bind inside the game's process, so one build loads whatever
glibc the image has. No C++ standard library, exceptions, RTTI or new/delete
(the build refuses them by name); classes, templates and statics are fine. The
runtime finds the switches and coils a mode's code uses from its string
literals (it wraps and resolves them like the form's), and `check` reads the
same literals in the `.cpp` against the port report. A stick or an ISO carries
`<name>.so`, never the source; `check` refuses one not built or older than its
`.cpp`.

**Blocks.** The Modes tab's Blocks editor (the Stern one, with a JJP palette)
keeps `<name>.blocks.json` beside the mode and writes `<name>.cpp` from it at
every change (`plugins/jjp/block_modes.py`): When the mode starts / ends, a
switch is hit (while it runs, or before it to start it), a scoring shot is
made, every N seconds, N seconds left; score, variables, If, the clock,
multiball, ball save, the game's sounds, lamps and coils, the panel's title.

**In the app**, New mode offers the Stern tab's three ways: Blocks, C++ or the
form. A Blocks or C++ mode has the form too, as its Settings page. The tab
builds a changed mode's C++ in the app's Linux after each save, and Check shows
how that went.

**Proof, Wonka 03.03 in the emulator (hidden, muted), 2026-11-17.** A C++ mode
took a switch the form does not score (7,777,777 on the left ramp), added a
growing bonus after each form-scored shot, took the clock from 20 to 46 s
and ended itself from `tick()` ("ENDED by its code", `end("its
code")`); a mode with no start rule was started by its own `idle()` on the
second hit of a target and ran its 6 s; a drain reached `end("ball end")`.
Then the modes the app itself made through New mode (a Blocks starter and the
C++ template, built by the app) ran the same way: the blocks' bonus 250,000
then 500,000 and their "5 seconds left" script; the template's bonus on five
shots and +10 s at the fifth.

## A mode's own sounds, music, picture and video (PAD-1352)

The files sit in the mode folder beside the `.mode` files and travel with them
(`mkjjpmodes.py build` and `stick` copy every sound, picture and video file in it; `check`
says when one a mode names is missing).

```
# 3_candy_rush.mode
start = switch_target_tv
sound_start = rush_start.wav       # our own, on the game's fanfare channel
sound_shot = se_Fanfare_Jackpot    # the game's own still work
music = rush_loop.ogg
picture = rush_logo.png
picture_at = 2 4 30 18
video = rush.webm
video_at = 25 4 50 58
panel = bottom
```

* **Sounds play through the game's own sound engine.** A sound file becomes a
  `SoundEffect` of the game's own (a copy of one of its sounds on that channel,
  holding our sample), played by the game's own `play`, so the game's volume
  settings, channel levels and ducking treat it like the game's sounds.
* **Music takes over the game's music the game's way.** The runtime adds one
  rule at the head of the game's music list (`Update<UpdateBGMusic_>`): while the
  mode runs it names the mode's music, so the game stops its own and plays ours
  on the music channel; when the mode ends, pauses for a game mode, or the ball
  drains, the rule steps aside and the game's own music comes back. Music
  loops. The whole file is held in memory, so keep it a loop of a minute or two.
* **Pictures and video** are drawn under the mode's text panel, video first.
  Video is decoded by the game's own FFmpeg; it pauses with the mode. Keep it
  the screen's size or smaller (1360x768 on Wonka): decoding a bigger one costs
  the game frames.
* Formats: what the game's own libraries read - sounds `.wav` `.ogg` `.flac`
  `.opus`, pictures `.png` `.jpg` `.bmp` `.tga`, video `.webm` (VP8/VP9),
  `.mkv`, `.mp4` (H.264). Video has no sound: give the mode a `sound_start` or
  `music` for that.
* Every JJP title that runs modes has these pieces (`media` in its port
  report: `can_play_own_media`).

**Emulator, Wonka 03.03** (hidden, muted; the game's sound measured through
`audio.sh`'s `JJP_AUDIO_CAPTURE` and `jjpaudiocap.py`, test tones 880 Hz start,
1500 Hz shot, 330 Hz music). The runtime read the `SoundEffect` layout off the
game's code itself (sample +0x58, channel +0x18, loaded +0xd8, stream +0xf0, flags
+0x54) and made the two sounds on the fanfare channel and the music on the music
channel. At the start the 880 Hz tone played; from then on the mix was our 330 Hz
music alone (the game stopped its own), ducked by the game to a twentieth for
about 1.5 s when a ramp shot played the 1500 Hz tone with the game's own callouts,
then back up. The picture and the VP9 clip drew in their boxes (the clip at 30
frames a second, its counter moving between shots). When the timer ran out, and
in another run when three shots completed the mode, our rule stepped aside and
the game's own music came back within a second. With `game_modes = pause` and
the game's `mtv_mode` started under it, our music handed back at once and the
screen showed only the game's mode. The other seven titles are matched
statically: the same exports, the same 264-byte `SoundEffect`, the same FFmpeg 4.4
and Allegro libraries, and the runtime loads with every import bound on each
cached root (glibc 2.34).

## The game's own modes, changed: `.stock` files (PAD-1351)

A `<name>.stock` file in the mode folder changes one of the GAME's modes: its timer,
its points and which shots count for it. No game code is patched; the runtime points
a few slots of that mode's class vtable at its own functions, which call the game's.
A folder may hold `.stock` files only, `.mode` files only, or both (up to 32 `.stock`).

```
# candy_lane.stock - Wonka 03.03 (modes/stock_examples/Wonka-v03.03)
mode = cl_mode
seconds = 60
points_x = 3
shots_off = target_ul_flipper
shots_add = switch_ramp_right_made:target_tv
```

| Key | Meaning |
|---|---|
| `mode` | (required) the game's mode: its global (`cl_mode` is Wonka's Candy Lane; a title's port report lists them under `stock.objects` once read off a live game) or its class (`CandyLaneMode`; every title's report lists them under `stock.classes`) |
| `seconds` | the mode's timer when it starts, in place of the game's own (Candy Lane's is 45, 30 or 15 by the Wonka Bar timer adjustment) |
| `points` | every award the mode makes becomes this many points |
| `points_x` | every award the mode makes times this (`2`, `1.5`, `0.5`); `points` wins if both are set |
| `shots_off` | shots that no longer count for this mode (the game's other modes still get them) |
| `shots_add` | `switch:shot` pairs: while the mode runs, hitting the switch also gives the mode that shot |

Shots are the game's own shot names: on Wonka 03.03 the 41 in
`modes/ports/Wonka-v03.03.live.json` (`ramp_left`, `loop_center`, `target_tv`,
`g_target`, ...), or a shot's number. On a title read only statically, the runtime
logs its shot table on the machine (`jjpmodes.log`, the `shots:` line), and
`mkjjpmodes.py check` leaves shot names unchecked there. Everything the file does is
logged with `STOCK`: each award with the game's own figure beside it, each shot let by
or added, and when the mode starts and ends.

How each works, read off Wonka 03.03's decrypted engine:

* **Timer.** `Mode::start` sets a default and each class then sets its own (the Wonka Bar
  award modes from an adjustment, 60 - 15 x the setting, into a timer the class keeps
  itself). The mode's run proc is started through the class's `run_proc` slot, so the
  runtime runs first there and calls the class's own `set_time`. With the run proc
  alive, `set_time`'s restart does nothing, as when the game sets a time itself. The
  timer then runs (or holds) by the game's own rules.
* **Points.** Every award goes through `this->score_and_total`. The game's call sites
  check whether the slot still holds the class's own function and call the slot when it
  does not, so the runtime sees every award.
* **Shots.** A made shot reaches each mode by a direct call to its class's
  `shot_dispatch`, which reads the shot from its proc argument and first asks
  `this->is_running` (or `_or_grace`, `_or_grace_grace`) through the vtable. The
  runtime answers that question "not running" when it comes from inside that class's
  own `shot_dispatch` (the return address) about a shot in `shots_off`. For `shots_add`
  it sets the shot id in the switch's proc (`shot_set_proc_shot_id`; Wonka has no
  setter, so the proc argument `shot_get_proc_shot_id` reads) and calls the class's
  `shot_dispatch`. A class with no `shot_dispatch` of its own takes no shot keys
  (the port report's `shots: false`; the runtime logs it).
* **Shot names.** The game's shot table (one entry per shot id, each pointing at its
  exported `shot_made_<name>` handler) is ciphertext in the file. The runtime finds it
  in memory by those handlers' addresses; `jjpstock.py` does the same on a live game.
  A shot is named after its handler; where several shots share one (Wonka's slings,
  jets and 3-bank) each takes the game's display name instead (`left_sling`,
  `top_bumper`, `g_target`).

**Emulator, Wonka 03.03** (hidden, muted, `C:\tmp\PAD-1351\proof.sh`): Candy Lane
started by the test hook (`JJP_MODS_TEST_GAMEMODE=cl_mode`), then the same shots on two
boots. Without changes: the game's timer read 30 s (`WonkaBarAwardModes::wba_timer`),
awards 5,000 at the start and 2,550 a target, the upper-left flipper target scored,
the right ramp did nothing for it. With `candy_lane.stock`: the timer read 60 s, awards
15,000 and 7,650 (x3), `target_ul_flipper goes by it`, and `switch_ramp_right_made gives
it shot target_tv` scored 7,650. The same file naming the class (`mode = CandyLaneMode`)
does the same. The countdown is the game's own
`WonkaBarAwardModes::timer_run_proc`, which takes a second off that same `wba_timer`
each second unless `game_timers_paused()` (the ball saver's pause, with every ball in
play held in a lock or the shooter lane). On the hidden rig no ball rolls, so the
game held the timer in both runs alike; the file changed the value it counts down
from.

### Every title, statically

`jjpport.py` reports, per title, what a `.stock` file can do (`stock` in the port
report): the vtable slots, how the shot id is read and set, and per Mode class whether
its timer and points are its own and whether it takes shot keys. Checked 2026-11-16 on
each title's game program; every one has the same slots as Wonka (run_proc 0x90,
set_time 0x28, score 0x88, is_running 0x48 / 0x50 / 0x58) and `shot_get_proc_shot_id`:

| Image | Mode classes | Take shot keys | Own timer | Own points | Shot id set by | Shot handlers | Starter |
|---|---|---|---|---|---|---|---|
| Wonka 03.03 | 25 | 17 | 5 | 10 | the proc argument | 38 | `candy_lane.stock`, emulator-proven |
| Guns N' Roses 03.03 | 33 | 30 | 0 | 30 | `shot_set_proc_shot_id` | 51 | `AFDMode.stock` |
| Elton John 02.03 | 31 | 29 | 0 | 28 | `shot_set_proc_shot_id` | 36 | `PianoRampMode.stock` |
| Godfather 02.03 | 16 | 13 | 0 | 15 | `shot_set_proc_shot_id` | 57 | `BoxingMode.stock` |
| Pirates of the Caribbean 01.01 | 2 | 0 | 0 | 0 | `shot_set_proc_shot_id` | 46 | none: its two Mode classes take no shots; its play is multiballs |
| Dialed In 02.02 | 17 | 14 | 0 | 0 | `shot_set_proc_shot_id` | 27 | `DisasterMode_AcidRain.stock` |
| The Hobbit 04.02 | 33 | 32 | 0 | 32 | `shot_set_proc_shot_id` | 31 | `BookMode.stock` |
| Toy Story 02.04 | 21 | 19 | 0 | 16 | `shot_set_proc_shot_id` | 41 | `BottleBlastMode.stock` |

"Own timer 0" means the class times itself through `Mode::set_time` (the engine's own
timer, which the runtime sets the same way). Each starter folder passes `mkjjpmodes.py
check` against its title's report, and the runtime loads with every import bound
(`LD_BIND_NOW`) on each cached image's own glibc 2.34 (Wonka, Guns N' Roses, Dialed In,
Hobbit, Toy Story). What is generic: the slots, the shot accessors, the shot table rule,
and the class-name lookup. What needs a live game per title: the mode globals' names
and the shot names (`jjpstock.py live`), both of which the runtime learns by itself on
the machine. The CHAKA GnR LE image is a custom Guns N' Roses build and takes GnR's
files.

## How a mode behaves

* A custom mode runs while a ball is in play and ends with the ball, as the
  game's own modes do (the game stops a mode's run proc at ball end). Start
  shots counted toward `start_count` carry over between balls and reset when a
  new game starts (`start_count_reset = ball`: every ball).
* One custom mode runs at a time. A start shot is refused (and logged as
  "yielded to <mode>") while a game mode or a multiball runs.
* A start rule (`start_on`, `start_after`, `start_score`, `start_combo`) does not
  start the mode on the spot: it raises the start, and the mode starts at the
  first moment that ball when the ball is in play, no other custom mode runs and
  nothing it yields to runs. A raised start not done by the end of the ball is
  dropped (logged). Several rules on one mode: any of them starts it.
* A multiball is more than one ball in play for half a second (the count blips).
* The mode's lamps live in a lamp layer of their own, above the game's mode
  layers and below its award, tilt and diagnostic layers. When the mode ends,
  or pauses for a game mode, the lamps go back to the game.
* The game draws its own floating score for every scoring shot; the panel shows
  the title, the mode total and the seconds left.
* Everything is logged to `/jjpe/temp/jjpmodes.log` on the machine.

## On a real machine

Two ways in. Both put the same files in the game's root (`/jjpe/gen1/padmodes/`,
`scripts/padmodes.sh`, one guarded line in `scripts/rungame.sh` after
`runonce.sh`), and `/jjpe/perm/padmodes.off` turns the modes off either way.

**A USB stick, no reinstall (PAD-1349, the everyday way).**
`mkjjpmodes.py stick --out <stick> --modes <folder>` writes a `hotfix` folder
(plain files, no root, any OS) to copy to the top of a FAT32 stick. On the
machine: service menu > Utilities > Software Update > USB Update, stick in. The
screen says "No update data was found". **Hold the left flipper button** and
press Plus, Minus, Plus, Minus: it asks "Press ENTER to apply HOTFIX". ENTER,
ENTER: the game runs the stick's `hotfix/runme.sh` through its own
`scripts/hotfix.sh` and reboots. Scores, audits and settings are not touched.
`runme.sh` refuses another title (`title.cfg`'s `game`), checks every file's
sha256 before copying, refuses a `rungame.sh` it does not know, and writes what
it did to `padmodes_install.log` on the stick and in `/jjpe/temp`. The same
command with `--action off`, `on` or `remove` writes a stick that turns the
modes off, back on, or takes them out (`rungame.sh` back exactly as shipped).
Changing a mode = edit the folder, write the stick again, apply it again.
`stick` takes the runtime from `--so`; with `--iso <stock>.iso` instead (root,
WSL) it builds it against that ISO's glibc first, which is also
`mkjjpmodes.py runtime --iso <stock>.iso --out <file>.so` on its own: the ISO's
root from the rig-shaped root cache (`/var/tmp/jjp_<label>/sda3.raw`, restored
the first time, about 20 minutes from a Windows drive, with a progress line
every 2%), mounted read-only with no journal replay, `buildmods.sh` against its
`/lib/x86_64-linux-gnu`. With neither, buildmods.sh's `/var/tmp/jjpmodes.so`.

How the hot fix was found: the Update USB screen (`DiagUpdateUSB`) counts
Plus/Minus presses only while a flag is set, and the only code that sets it is
a handler on `HookLeftFlipperDebounced` (named `du_hlfd`, "hot fix") that sets it
while the flipper is held, the game is in test mode and the USB Update item is
the current one. `hotfix.sh` runs `/mnt/usb/hotfix/runme.sh` if there is one
(else it rsyncs `hotfix/` over `$JJPEDIR`), then `sync` and `reboot`. Nothing is
verified. (The screen's full "delta" update, a `wonka_update/` folder, goes
through a `ui.dat` the game verifies; the hot fix needs none of that.)

**An install ISO.** `mkjjpmodes.py build --iso <stock>.iso --modes <folder>
--out <new>.iso` (as root in WSL) writes the stock ISO again with the modes in
its root pieces. Install it the way the stock ISO is installed (dongle in, and
like any full install it resets scores and settings). Left without `--so`,
the build compiles the runtime from `jjpmodes.c` against the glibc in that ISO's
own root (`buildmods.sh` with `JJP_MODS_LIBDIR`; gcc in the WSL distro), so
nothing prebuilt can go stale (PAD-1350); `--so` takes one built already.

**Proof, Wonka 03.03 in the emulator (hidden, muted, Wonka's own key), 2026-11-17.**
*ISO:* `build` on the stock Wonka ISO (51 s, 3.2 GB, e2fsck clean); the rig
restored and booted the built ISO with no rig-side preload, so the runtime came
only from the ISO's own hook (`[rig] image hook padmodes.sh:
LD_PRELOAD=/jjpe/gen1/padmodes/jjpmodes.so`, "PAD custom modes: 1 mode(s)
loaded"). PAD Mode started on the TV target, scored 1,000,000 on each of five
shots and COMPLETED at 10,000,000; with `/jjpe/perm/padmodes.off` present the
same ISO booted with an empty `LD_PRELOAD`, no `jjpmodes.log`, and played stock.
*Stick:* on the stock Wonka ISO, the menu walk above (driven with `jjppoke.py`)
ran the stick: "INSTALLED 1 mode(s): PAD Mode", `hotfix.sh` asked for its reboot;
after the restart PAD Mode played to COMPLETED (10,000,000). An `off` stick
created `padmodes.off` and the next boot loaded no runtime; a `remove` stick left
no `padmodes` and `rungame.sh` byte-identical to the image's. Inside `/jjpe` the
hot fix wrote only the padmodes files, the hook and its log.
*Every other title:* `build` against its stock ISO and starter folder: Guns N'
Roses 03.03, CHAKA's LOTLJ GnR LE 3.03, Elton John 02.03, Godfather 02.03 and
Pirates 01.01 all build, stage and e2fsck clean (`rungame.sh` has the one
`runonce.sh` anchor on each), and `inspect` lists their modes.

The rig: `JJP_USB=<folder>` (jail.sh) binds a folder at the jail's `/mnt/usb`
with the automount's mode (0777), so the game sees an inserted stick, and
run_game.sh replaces the jail's `reboot`/`poweroff`/`halt`/`shutdown` (links to
systemctl) with a note in `/jjpe/temp/rig_reboot.log`: a script of the game's
can never reboot WSL. A proof restarts the game where the machine would reboot.

## Titles

`jjpport.py` reports, per title, whether its engine has every piece the
runtime needs (`can_run_modes`). `modes/ports/` holds the report for every JJP
image in the library and `modes/examples/` a starter folder for each title that
can run modes. Checked 2026-11-15 on every image in `D:\Pinball\images\JJP`, and
2026-11-16 on the five added since (PAD-1350, PAD-1364):

| Image | Engine exported | Runs modes | Library loads |
|---|---|---|---|
| Guns N' Roses 03.03 | 22,265 names | yes, emulator-proven | yes |
| CHAKA's LOTLJ GnR LE 3.03 | 22,265 | yes | yes |
| Elton John 02.03 | 22,295 | yes | yes |
| Godfather 02.03 | 21,498 | yes | yes |
| Wonka 03.03 | 18,717 | yes, emulator-proven | yes |
| Pirates of the Caribbean 01.01 | 18,693 | yes | yes |
| Dialed In! 02.02 | 17,044 | yes | yes |
| The Hobbit 04.02 | 14,855 | yes | yes |
| Toy Story 4 02.04 | 21,996 | yes | yes |
| The Wizard of Oz 08.02 | 12,260 (older engine, no Mode class) | yes, on the proc engine (static) | yes |
| Harry Potter 01.26 | 233 (no engine) | **no** | yes |
| Avatar 01.03 | 245 (no engine) | **no** | yes |
| Sonic 00.925, 00.926 | 246 (no engine) | **no** | yes |

"Runs modes" for a title other than GnR means its binary exports every engine
piece the runtime uses and its Mode vtable resolves to the same slots as GnR's
(read statically), and its starter modes pass `mkjjpmodes.py check` against its
report. Each title needs its own Sentinel key to run, and a key is per-title (it
carries the AES key that decrypts that game's code; GnR's key `H0007`s on Wonka).

**Guns N' Roses and Wonka are the two emulator-proven titles** (PAD-1335/1337,
PAD-1347). The runtime is the same `jjpmodes.so` on both and needed no change
for Wonka: everything is found by exported name, so a second title boots the
same code. On Wonka 03.03 with Wonka's own key the `Wonka-v03.03` example
started on `switch_target_tv`, scored 1,000,000 a shot through the game's own
scoring (five shots, `COMPLETED` +5,000,000, mode total 10,000,000), ran out the
20 s game timer when left alone, drew its panel in the game's `font_wba_*` fonts
(`screen: allegro ok, game text ok`), resolved all three `se_*` sounds, lit
`lp_gi_tv` our `ff2000` (red, blinking 4/s) in the game's own `lb_rendered`
composite and handed the lamp back to the game's white when the mode ended,
yielded a start shot to a running game mode (`yielded to mtv_mode`), and
confirmed `ingame_state` 5 (a ball in play). The runtime-resolved pieces that
static analysis could not settle all held on Wonka unchanged: the lamp-layer
`active` byte offset off the decrypted `render_all`, the `play` slot in the
sound object's vtable, the `ingame_state` value and the empty `background_modes`
(no always-on mode on a plain Wonka ball). Proof harness: `wonka_proof.sh`,
`lamp_yield.sh`, `lamp_lifecycle.sh`.

**The other four "yes" titles** (CHAKA's LOTLJ GnR LE, Elton John, Godfather,
Pirates) are static-matched: their port reports diff against GnR's with the same
Mode vtable slots, the same `Switch` object size and every required SDK piece
present, and their starter folders pass `check --port`. Two independent titles
booting the one unchanged runtime - GnR and Wonka, built from different games -
is what shows the SDK is generic, so these four are taken as runs-modes without a
separate live run each; any one can be run the same way with its own key.

**Dialed In!, The Hobbit and Toy Story 4** (PAD-1350, PAD-1364) are mapped from Wonka the same way:
their Mode vtable slots, hold slots and 104-byte `Switch` match Wonka's, every required
SDK piece is exported, and their starter folders pass `check --port`. Dialed In has
84 named shot switches, 216 lamps, 1,286 sounds and 17 Mode classes; The Hobbit
104, 131, 1,501 and 33; Toy Story 82, 670, 2,231 and 21. Dialed In has no lamp
named for a target, so its starter lights none (add `lamps =` by hand).
A starter's lamp is the one whose name shares the most words with the start
switch (`switch_u_target_1` lights `lp_upper_target_1`), which since PAD-1364 also
moved Elton John's, Godfather's and Pirates' starter lamps onto their start shots.

"Library loads" means the one `jjpmodes.so` loads with every import bound
(`LD_BIND_NOW`) on that image's own glibc, checked in a chroot of its root - 2.34 on all fourteen.

### Our modes run alone (PAD-1348)

With `game_modes = hold` (the default) the runtime points the start and restart
slots of every class derived from `Mode` or `MultiballRule` at its own gate: while
one of ours runs, the gate refuses the start, and the game reads that as "did not
start". The classes are found from the game's own exported typeinfo, so each title
brings its own. `jjpport.py` reports what the gate covers on a title (`hold` in its
port report), read from the file the same way the runtime reads it in the game.

| Image | Mode classes | Multiball classes | Slots (start, restart; multiball start, restart) | Library loads (2026-11-16 build) |
|---|---|---|---|---|
| Guns N' Roses 03.03 | 33 | 9 | 0x10, 0x18; 0x88, 0x90 | yes |
| Elton John 02.03 | 31 | 9 | same | glibc 2.34, as the build checks |
| Godfather 02.03 | 16 | 8 | same | glibc 2.34, as the build checks |
| Pirates of the Caribbean 01.01 | 2 | 10 | same | glibc 2.34, as the build checks |
| Wonka 03.03 | 25 | 8 | same | yes |
| Dialed In 02.02 | 17 | 10 | same | yes |
| The Hobbit 04.02 | 33 | 8 | same | yes |
| Toy Story 02.04 | 21 | 7 | same | yes |

**Emulator, Wonka 03.03** (hidden, muted, `C:\tmp\PAD-1348\proof3.sh`): four rounds of
the 40 named shots while PAD Mode ran. The Gobstopper multiball's start was refused
three times (`HELD OFF the game's multiball gobstopper_mb`), and once PAD Mode's timer
ran out the same shots started it (`went ahead`). The game's own modes stack on
JJP titles, and some start without going through these slots: the Oompa hurry-up
started while PAD Mode ran, PAD Mode paused for it (`PAUSED for oompa_hurryup (it
started past the hold)`) and resumed when it was over. On Wonka Wonka Wash Frenzy also
starts this way. Pirates has only two Mode classes: most of what it runs are
multiballs, which the gate holds. The CHAKA GnR LE image is a custom Guns N' Roses
build, covered by Guns N' Roses.

### Start rules from the game's hook lists (PAD-1354)

The engine announces its events through about 70 `Hook<HookX_, Arg>::list`
globals, each a linked list of the game's own callbacks it walks wherever that
event happens. The runtime adds one node of its own at the end of each list a
mode's rules need (the game's callbacks run first, ours never stops the walk),
and starts raised modes on the game's own proc thread from its lamp-render,
update and switch-dispatch lists. No game code is patched.

| `start_on` word | Game hook list | Notes |
|---|---|---|
| `ball_start` | `HookBallStart_` | every ball, every player |
| `first_ball` | `HookFirstBall_` | each player's first ball |
| `last_ball` | `HookLastBall_` | the game runs it just before the player's last ball; the runtime also takes the game's balls-left count reaching 0 at ball start (either one, once a ball) |
| `valid_playfield` | `HookValidPlayfield_` | the ball's first playfield switch |
| `ball_saved` | `HookBallSave_` | the game's ball save |
| `extra_ball` | `HookExtraBallAwarded_` | run from `ExtraBall::award()` |
| `multiball_end` | `HookMultiballEnd_` | the game runs this list every time its ball count settles, one ball or several; the runtime takes it as a multiball's end only after a multiball (more than one ball for half a second) |

`start_score` reads `score_get_player_score(game_flow_get_player_up())` as the
game scores (`HookScore_`); `start_after` watches the game's mode objects (the ones
`game_modes` yields to) for one that stops running; combos are counted in the
shot wrappers.

`jjpport.py` reports per title which hook lists it has (`hooks`, `start_rules` in
its port report), and `mkjjpmodes.py check` refuses a `start_on` word a title's
report says it lacks. Every title that runs modes has all twelve lists the rules
use: Guns N' Roses (and CHAKA's GnR LE), Elton John, Godfather, Pirates, Wonka,
Dialed In, The Hobbit and Toy Story, read off each title's own game program. The
runtime loads with every import bound (`LD_BIND_NOW`) on the Guns N' Roses,
Dialed In, Hobbit and Toy Story roots; Elton John, Godfather and Pirates use the
same glibc 2.34 the build checks against.

**Emulator, Wonka 03.03** (hidden, muted, `C:\tmp\PAD-1354\proof.sh`,
`proof2.sh`, `proof5.sh`): 13 of our nodes went onto the game's lists. The game's
first ball raised and started `start_on = ball_start` (on the proc thread, once
the ball was in play); five 1,000,000 shots in it took the score past 4,000,000
and raised `start_score = 4,000,000`, which waited for the running mode and
started when it ended; ramps hit centre, left, centre started
`start_combo = switch_ramp_left_made switch_ramp_center_made` (the wrong order did
not); the game's Oompa hurry-up, started and then ended through its own `Mode::end` (a test-only switch, `JJP_MODS_TEST_END_SWITCH`; it did not time out inside 90 s on the rig), started `start_after = oompa_hurryup`; on
ball 2 `start_once = game` refused the ball-start mode; on the last ball
`start_on = last_ball` started (balls left 2, 1, 0). `first_ball` and
`valid_playfield` were logged as the game ran them; `multiball_end` came at every
drain with one ball and was turned down. `ball_saved` and `extra_ball` were not
seen live: the hidden rig cannot drain a ball inside its save window or earn an
extra ball. They are the same mechanism, one list each, and the port reports
show both lists on every title.

**Harry Potter and Sonic are built without the engine's exports**: their
binaries export only C library and Allegro names. The runtime finds everything
by name, and their code is ciphertext until the title's own key decrypts it,
so nothing can be mapped without that key. Custom modes on them need their keys.
Avatar is built the same way.

### The Wizard of Oz: the proc engine (PAD-1365)

**Wizard of Oz 08.02 is JJP's first engine generation**: it exports 12,260 names, 120
shot switches, 149 lamps and 633 sounds, but has no `Mode` class. Its modes are plain
functions run on procs, in families named like the later Mode class's own procs:
`ecmb_run_proc` / `ecmb_grace_proc` / `ecmb_grace_grace_proc` (Emerald City multiball),
`haunted_`, `sotr_`, `rescue_mb_`, `witch_melt_`, `fireball_frenzy_`, `hurry_build_`,
`twister_mode_proc_run`, and `mmf_proc`, `mml_proc`, `mmm_proc`, `mmw_proc`, `tnplh_proc`,
`cbm_proc` (each with its own `<x>_proc_kill_func`).

There the runtime runs a mode on a **proc of its own** (`engine: our own procs` in the log),
built the way the engine's `Mode::start` runs one, read off Wonka 03.03's decrypted code:

| Piece | Mode engine (every other title) | Proc engine (The Wizard of Oz) |
|---|---|---|
| Run | `Mode::start` -> `proc_cret(run_id, Mode::start_run_func, 0)` | `proc_cret(0x7e00 + 3n, our run proc, 0)` (= `proc_create` flag 2, no survive flag) |
| Clock | `Mode::run_proc`: `proc_sleep(1)`, 125 ticks to the second | the same loop, our own seconds |
| Points | `Mode::score_and_total` -> `score_add_to_player_up(points, false)` | `score_add_to_player_up(points, false)` |
| End | `Mode::end`; the ball end kills the run proc | the run proc returns; the ball end kills it (`proc_id_exists` says so) |
| Lamps, sounds, screen, balls, coils, start rules, own media | the same | the same |
| Yield | the game's Mode objects (`Mode::is_running`) | live procs running one of the game's mode functions (below) |
| Hold | the game's Mode / MultiballRule starts gated | **not possible** (no Mode class): `game_modes = hold` runs as `pause`; the checker says so and the app offers pause |
| `.stock` files | yes | no (no Mode class to change) |

Every function it calls is the same engine function on both generations: the same mangled
name and the same byte size on Wizard of Oz 08.02 and Wonka 03.03 (`proc_create` 1,382 bytes,
`score_add_to_player_up` 492, `Lamp::set` 139, ...). The engine's proc list (head not
exported) is read off the decrypted `proc_id_exists` at install (`mov MUTEX(%rip),%rdi;
call al_lock_mutex; mov HEAD(%rip),%rax`, then `cmp ID(%rdx)` and `testb $0x10,FLAGS(%rdx)`)
and the entry function's offset off `proc_create` (`mov %r13,FN(%rbx)`); on Wonka: head
0xdc64d0, id +0x1f0, flags +0x1fc, entry +0x1b8/+0x1e8.

A game mode is a live proc whose entry is one of the game's **mode functions**: a function of
the proc's `unsigned` argument named for a mode (`mode` in it), or named like Mode's procs
(`<x>_run_proc`, `<x>_grace_proc`, `<x>_proc_run`, `<x>_proc_grace...`), or `<x>_proc` with
an `<x>_proc_kill_func` of its own - never an attract, kill, test, diagnostic, menu, timer,
lamp effect, lamp, tilt, music, match, choreography or hook function. `jjpport.py` lists
them (`proc_modes`: 27 on Wizard of Oz) and they are the names `start_after` takes there.

**Proof.** The Wizard of Oz's key is not at hand (the rule for this work: Wonka's key stays
plugged in), so it is **not emulator-proven on The Wizard of Oz**. What is proven:

* **Emulator, Wonka 03.03, the proc engine forced** (`JJP_MODS_ENGINE=proc`, hidden, muted,
  `C:\tmp\PAD-1365\proof.sh`), 2026-11-17: the proc list read off the code; a mode
  started by a start rule at ball start ran its 6 s and ended by its clock; PAD Mode started
  on the TV target, the game scored each shot (`the game scored 1000000
  (score_add_to_player_up)`), its 20 s clock ended it; five shots completed it at
  10,000,000; `lp_gi_tv` ff2000 in our layer and in the game's composite, blinking 3 a
  second (24 changes in 4 s), the game's white after; with Candy Lane running our start
  yielded to `Mode::start_run_func`, after it ended ours started, Candy Lane starting under
  ours paused it (a shot not scored) and its end resumed it; a drain killed our run proc
  (`over`) and the next ball's rule started a mode again; a multiball with no clock asked
  for 3 balls, the game's ball saver put 3 in play, and it ran on with no clock.
* **Statically, The Wizard of Oz 08.02**: `jjpport.py` says it can run modes on the proc
  engine with every proc-engine name exported; every engine name the runtime looks up is
  exported except the Mode-class and `.stock` ones the proc engine never uses; its starter
  folder passes `mkjjpmodes.py check --port`; the runtime built against its own glibc
  loads with every import bound (`LD_BIND_NOW`) through its own loader on its own root.
  Its code is Envelope ciphertext at rest (4,863 functions), so its call signatures are
  confirmed by the mangled names and sizes, not by reading its code.

### Balls and coils on every title (PAD-1353)

**Emulator, Wonka 03.03** (hidden, muted, the rig's ball feeder run headless so served
balls reach the playfield; `C:\tmp\PAD-1353\proof.sh`), 2026-11-17:

* `multiball = 3 8`: `3 ball(s) in play asked for (1 in play)`, the trough kicked two
  balls and the game counted 3 in play. `add_ball` took it to 4; the second hit was
  refused (`already 1 this run`). A drain inside the ball save was served straight back
  (the trough kicked within 0.6 s, the count stayed at 4). After the save, drains to one
  ball ended the mode (`ENDED by one ball left`), the game playing on. The mode did not
  pause for its own multiball.
* `ball_save = 15`: on at the start; the mode completed 1 s later and the save ended with
  it (`ball save ended with the mode`).
* Pulses: the knocker fired at the start and on each shot at its own 32 ms (`500` asked:
  `the game's own pulse is the most`). `coil_flipper_power_left` and
  `coil_motor_gobstopper` were refused and never driven (the sampler of the board's OUT
  frames saw nothing on them).
* Holds: `coil_magnet_left_lane 1500 8` drove 1520 ms at 25 % on (sampled) and went off at
  its time; a shot inside it was refused (`it is held already`), one 1 s after it
  (`3 s off between holds`). `coil_magnet_1 3000 4` (12-14 % on, sampled) went off when its
  mode completed at 1180 ms; `coil_magnet_2 5000` went off at the ball's end at 1614 ms.

**Every other title, statically** (2026-11-17): each title's port report has the ball
saver and Coil API (`can_balls`, `can_coils`), its starter folder (now with a
`2_multiball.mode`) passes `mkjjpmodes.py check --port`, and the library loads with every
import bound (`LD_BIND_NOW`) on the title's own root where it is cached:

| Image | Named coils | A mode may pulse | ...and hold | Library loads |
|---|---|---|---|---|
| Guns N' Roses 03.03 | 33 | 15 | 10 | yes |
| CHAKA's LOTLJ GnR LE 3.03 | 33 | 15 | 10 | yes |
| Elton John 02.03 | 42 | 23 | 6 | yes |
| Godfather 02.03 | 45 | 24 | 7 | glibc 2.34, as the build checks |
| Wonka 03.03 | 46 | 24 | 14 | yes, emulator-proven |
| Pirates of the Caribbean 01.01 | 50 | 28 | 13 | glibc 2.34, as the build checks |
| Dialed In 02.02 | 38 | 20 | 10 | yes |
| The Hobbit 04.02 | 68 | 43 | 13 | yes |
| Toy Story 02.04 | 43 | 22 | 8 | yes |

Coil holds stay off on every title until its `title.cfg` says `coil_holds = on`: the
emulator proves what the game was asked to drive, not what a real coil does with it.
