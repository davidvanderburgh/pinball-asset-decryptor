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
| `start` | (required) | switch(es) that start the mode, space separated |
| `start_count` | 1 | start-switch hits needed to start it |
| `shots` | `start` | switches that score while it runs |
| `points` | 1000000 | per scoring shot, through the game's own Mode::score_and_total |
| `seconds` | 20 | the game's own mode timer |
| `complete` | 0 | scoring shots that complete the mode (0 = it runs to time) |
| `complete_points` | 0 | added on completion |
| `sound_start`, `sound_shot`, `sound_complete`, `sound_end` | none | the game's `se_*` sounds |
| `lamps` | none | `lp_*` lamps (or `ls_*` lamp groups) the mode lights |
| `lamp_color` | ffffff | rrggbb |
| `lamp_blink` | 4 | flashes a second; 0 = solid |
| `font_title`, `font_value`, `font_timer` | none (built-in font) | the game's `font_*` fonts for the title, the mode total and the seconds left |
| `title_color`, `value_color`, `timer_color` | ffffff, ffdc00, ffffff | rrggbb or rrggbbaa |
| `panel_color` | 000000b0 | the panel behind the text, rrggbbaa |
| `panel` | middle | `middle`, `bottom` or `top` (the game's score panel is at the bottom on most titles) |
| `game_modes` | pause | when a game mode or multiball runs: `pause` (timer held, shots not scored, panel hidden, lamps handed back), `end`, or `ignore` |

### title.cfg only

| Key | Meaning |
|---|---|
| `game` | the title's GAMENAME (e.g. `GunsNRoses`). The modes load only into that game: a mode ISO made from a multi-boot ISO hooks root A, which also starts image 1's game |
| `ingame_state` | the `jjpe_state_get()` value meaning "a ball is in play" (5 on Guns N' Roses). Without it the runtime learns it on the first ball: the state that holds for a second while the game's own ball-in-play flag is set (logged) |
| `background_modes` | game modes that are always on and must not make a custom mode yield. Without it, the game modes already running two seconds into a ball count as always-on |

## How a mode behaves

* A custom mode runs while a ball is in play and ends with the ball, as the
  game's own modes do (the game stops a mode's run proc at ball end). Start
  shots counted toward `start_count` carry over between balls and reset when a
  new game starts.
* One custom mode runs at a time. A start shot is refused (and logged as
  "yielded to <mode>") while a game mode or a multiball runs.
* A multiball is more than one ball in play for half a second (the count blips).
* The mode's lamps live in a lamp layer of their own, above the game's mode
  layers and below its award, tilt and diagnostic layers. When the mode ends,
  or pauses for a game mode, the lamps go back to the game.
* The game draws its own floating score for every scoring shot; the panel shows
  the title, the mode total and the seconds left.
* Everything is logged to `/jjpe/temp/jjpmodes.log` on the machine.

## On a real machine

`mkjjpmodes.py build --iso <stock>.iso --modes <folder> --out <new>.iso` (as
root in WSL) writes the stock ISO again with the runtime, the modes and one
guarded line in `scripts/rungame.sh`. Install it the way the stock ISO is
installed. To turn the modes off without reinstalling, create
`/jjpe/perm/padmodes.off`; delete it to turn them back on.

## Titles

`jjpport.py` reports, per title, whether its engine has every piece the
runtime needs (`can_run_modes`). `modes/ports/` holds the report for every JJP
image in the library and `modes/examples/` a starter folder for each title that
can run modes. Checked 2026-11-15 on every image in `D:\Pinball\images\JJP`:

| Image | Engine exported | Runs modes | Library loads |
|---|---|---|---|
| Guns N' Roses 03.03 | 22,265 names | yes, emulator-proven | yes |
| CHAKA's LOTLJ GnR LE 3.03 | 22,265 | yes | yes |
| Elton John 02.03 | 22,295 | yes | yes |
| Godfather 02.03 | 21,498 | yes | yes |
| Wonka 03.03 | 18,717 | yes, emulator-proven | yes |
| Pirates of the Caribbean 01.01 | 18,693 | yes | yes |
| Harry Potter 01.26 | 233 (no engine) | **no** | yes |
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

"Library loads" means the one `jjpmodes.so` loads with every import bound
(`LD_BIND_NOW`) on that image's own glibc - 2.34 on all nine.

**Harry Potter and Sonic are built without the engine's exports**: their
binaries export only C library and Allegro names. The runtime finds everything
by name, and their code is ciphertext until the title's own key decrypts it,
so nothing can be mapped without that key. Custom modes on them need their keys.
