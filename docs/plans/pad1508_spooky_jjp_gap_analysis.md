# PAD-1508: what Spike 2 modes can do that JJP and Spooky modes cannot

David, 2026-11-22: "Any features that we can add to Spooky and JJP that we have made on
Spike 2 we need to consider adding."

## Where each family stands

* **Spike 2** (`tools/spike2_emu/modes/sdk/MODE_PARAMETERS.md`): about 120 keys, a runtime
  inside the game program, the Modes tab's full form, blocks and C.
* **JJP** (`tools/jjp_emu/MODES.md`, PAD-1335 on): one `.mode` key set, the runtime
  `jjpmodes.c`, `.stock` files for the game's own modes, C++ (`code =`).
* **Spooky** (`docs/plans/spooky_modes.md`, PAD-1387 on): the **same `.mode` key set as
  JJP** (PAD-1424, PAD-1469 brought every runtime to JJP parity), run by four runtimes:
  Unity (`PadModes.cs` + a glue per title), Godot (`pad_modes.gd`), P-ROC
  (`padmodes_proc.py`) and pinHeck (`padheck.c`), checked by `mkspkmodes.py`.

So one gap list covers both: whatever Spike 2 has that the shared JJP/Spooky key set lacks.

## The gap, feature by feature

"Built" = added here, in the shared key set, on every runtime that can do it.

| Spike 2 feature (its key) | JJP / Spooky before | Decision |
|---|---|---|
| Points per shot (`shot_award`) | one `points` for every shot | **Built**: `shot_points = <switches> <points>`, up to 8 lines; such a switch scores even if it is not in `shots` |
| Rising award ladder (`award_ladder`) | every shot pays the same | **Built**: `points_ladder = rising` (the Nth scoring shot pays N x its value); `fixed` stays the default, as JJP modes have always played |
| A shot that ends the mode (`end_shot`) | only `complete` (a count) or time | **Built**: `end_shots = <switches>` |
| How often it can start (`starts N`) | `start_once` ball / game only | **Built**: `start_max = N` starts a game |
| Cooldown (`cooldown`) | none | **Built**: `cooldown = <seconds>` after its end; a new game clears it |
| Several shots to start, any order (`trigger_also`) | one start list and a count | **Built**: `start_also = <switches> [count]`, up to 3 lines, on top of `start` |
| Ordered shots with no time limit (`starts_on sequence`) | `start_combo` within `combo_seconds` | **Built**: `combo_seconds = 0` means no time limit (an out-of-turn combo switch still starts it over) |
| Only after another mode of mine (`after`) | `start_after` = the game's modes only | **Built**: `start_needs = <my mode> [ball|game]` |
| Callouts at seconds left (`callout_at`, `callout_count`) | sounds at start / shot / complete / end only | **Built**: `sound_at = <seconds left> <sound>`, up to 8 lines (the game's sound or a file of the mode's own) |
| Shot sound every Nth shot (`sound_shot ... every`) | every shot | **Built**: `sound_shot_every = N` |
| Light patterns (`light ... solid/blink/pulse/chase`) | blink at a rate, or solid | **Built**: `lamp_pattern = solid / blink / pulse / chase`, `lamp_blink` its rate |
| Shot penalty (`shot_penalty`) | none | **Built where the game can take points away**: Spooky's P-ROC titles (SkeletonGame's `game.score` subtracts). JJP's engine exports only `score_add_to_player_up` (Wonka 03.03, read 2026-11-22), and the Unity, Godot and pinHeck award calls only add, so their checks refuse `penalty` and say why |
| Light the shots that score (`light_shots`) | `lamps` by name | Not built: needs a switch-to-insert map per title, which no JJP or Spooky port report has. `lamps` names them by hand |
| Modes inside modes (`inside`; `layer` priorities) | ours run one at a time | **Built** on Spooky (`inside = <my mode>`: starts only while it runs, ends with it); Spooky's runtimes already run ours side by side, so Spike 2's `layer` priorities have nothing to order. JJP's check refuses it: ours run one at a time there (PAD-1348) |
| Take the place of a game mode (`in_place_of`; Stern's `roster_slot`, `challenge`) | `game_modes = hold` refuses the game's starts; `.stock` changes a game mode | **Built** where the runtime sees the game's start before it happens: JJP (its hold gate) and Spooky's P-ROC (SkeletonGame's mode queue). Unity, Godot and pinHeck only see a game mode once it runs: refused there by name, `start_after` offered. The roster and challenge menus are Stern's own |
| Mode survives a drain (`ends_on clock`) | the ball's end ends it | Not built: on JJP the game stops every mode's run proc at the ball's end whatever we do (MODES.md); a carried-over clock is a different feature |
| The game's own light shows (`show_start/end/hit`) | none | Not built: Stern's show table has no counterpart found in JJP's or Spooky's engines yet |
| Cabinet light shows, shaker (`cab_show`, `shake`) | `coil_hold` on a shaker motor coil (`coil_motor_shaker` on GnR LE, Dialed In) | Already covered for the shaker; cabinet expression lights are Stern hardware |
| Building, shield, magnet, scoop hold, game wizards, online counts | coils by name (`coil_*`) | Title hardware and Stern Insider Connected: no counterpart. The coils route covers the hardware a JJP/Spooky title has |
| Own screen nodes, clips (`screen_*`, `clip_*`) | `picture`, `video`, the text panel | Already covered |
| Multiball, add a ball, ball save | same | Already at parity (PAD-1353, PAD-1424) |
| Multi-boot editions (PAD-495) | JJP `mkjjpmulti.py`, Spooky `mkspkmulti.py` (Linux titles) | Already at parity |
| MUSIC MODE song menu (PAD-494) | a mode's own `music` | Not built: it is the game's own song-select menu on Stern, and neither JJP nor Spooky titles have one to extend (GnR's song modes are game modes `.stock` can change) |

## One format, six runtimes

The new keys are the same words on every runtime, read by the same check
(`mkjjpmodes.py` on JJP, `mkspkmodes.py` on Spooky, which takes JJP's tables), so the
Modes tab's one JJP/Spooky editor offers them everywhere. A key a runtime cannot do is
refused by its check by name, never silently ignored.

Proofs: each Spooky runtime in its emulator; P-ROC by its stand-in SkeletonGame in the tests;
JJP on Wonka 03.03 once the Sentinel key is in this PC.

## Progress

* Run 1 (2026-11-22): the analysis; the rule keys on all six runtimes, both checks and both
  editors (a "Rules from Spike 2" section; the keys given a line each get a multi-line box).
  Proven: Scooby-Doo (Unity) and Looney Tunes (Godot) on their rigs, Jetsons (pinHeck) in the
  PIC32 emulator, P-ROC and pinHeck's compiled runtime in the tests. JJP's emulator run needs the
  purple Sentinel key plugged into this PC; it was not (`usbipd list` shows no 0529:0001).
* Run 2: `inside` on the four Spooky runtimes (proven on Scooby-Doo, Looney Tunes, Jetsons and
  P-ROC's stand-in), `in_place_of` on JJP and P-ROC (proven on Rick and Morty's rig: its Skillshot
  held off, ours in its place). pinHeck now packs an empty `points`/`seconds` as the documented
  1,000,000 and 20 s, as every other runtime does. Left: the JJP emulator run, which needs the key.
