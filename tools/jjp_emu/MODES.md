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
extract's `X.wav` (2,690 of Wonka's 2,723 match). **Build** runs `mkjjpmodes.py
build` as root in the app's Linux on the stock ISO it finds beside the Select card
pick (or `D:\Pinball\images\JJP`), with its scratch in
`/var/tmp/pad_jjpmodes_work`; Cancel stops it inside Linux, where it unmounts and
deletes its scratch.

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
| `game_modes` | hold | `hold` (PAD-1348): while this mode runs, a start of the game's that goes through its class's start or restart (on Wonka 03.03: the multiballs, proven with the Gobstopper multiball) is refused and the game carries on as if it was not asked. Some game modes start another way (Wonka's Oompa hurry-up, Wonka Wash Frenzy) and are not held: this mode pauses for them, as `pause` does, and resumes after. Or the older choices for when a game mode or multiball runs: `pause` (timer held, shots not scored, panel hidden, lamps handed back), `end`, or `ignore` (none of these refuse the game's starts) |
| `hold_multiballs` | yes | with `hold`: `no` lets the game's multiballs start (and pause this mode) |
| `allow_game_modes` | none | with `hold`: the game's mode globals or classes (e.g. `mtv_mode`, `OompaHurryUp`) that may still start |

### title.cfg only

| Key | Meaning |
|---|---|
| `game` | the title's GAMENAME (e.g. `GunsNRoses`). The modes load only into that game: a mode ISO made from a multi-boot ISO hooks root A, which also starts image 1's game |
| `ingame_state` | the `jjpe_state_get()` value meaning "a ball is in play" (5 on Guns N' Roses). Without it the runtime learns it on the first ball: the state that holds for a second while the game's own ball-in-play flag is set (logged) |
| `background_modes` | game modes that are always on and must not make a custom mode yield. Without it, the game modes already running two seconds into a ball count as always-on |

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
2026-11-16 on the five added since (PAD-1350):

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
| The Wizard of Oz 08.02 | 12,260 (older engine, no Mode class) | **no** | yes |
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

"Library loads" means the one `jjpmodes.so` loads with every import bound
(`LD_BIND_NOW`) on that image's own glibc, checked in a chroot of its root (2.34 on the first
nine; the five added 2026-11-16 load the same way).

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

**Harry Potter and Sonic are built without the engine's exports**: their
binaries export only C library and Allegro names. The runtime finds everything
by name, and their code is ciphertext until the title's own key decrypts it,
so nothing can be mapped without that key. Custom modes on them need their keys.
