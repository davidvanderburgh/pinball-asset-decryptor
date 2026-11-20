# Custom modes on Spooky Pinball (PAD-1387)

## The ask

Pinballpal on Pinside: "Can you change the rules on Spooky's games?" David,
2026-11-18: we have modes on JJP, Spike 2 and Spike 3, do it for Spooky too;
there are several architectures; start the work here and split the rest into
about 10 tickets at most.

## The four code worlds

Every Spooky title PAD knows runs in one of four engines. Every one of them
already runs in a PAD emulator, so every one can be proven there.

| engine | titles | rules are | rig |
|---|---|---|---|
| Unity 2019/2022 Mono (C#) | Scooby-Doo, Beetlejuice, Texas Chainsaw Massacre, Evil Dead, Halloween, Ultraman | `Assembly-CSharp.dll` | `tools/spooky_emu` (Warden, Pinotaur) |
| Godot 4.1 (GDScript) | Looney Tunes | scripts in the PCK inside the ELF | `tools/spooky_emu` (Warden) |
| P-ROC / SkeletonGame (Python 2.7) | Rick and Morty, Alice Cooper's Nightmare Castle | `.pyc` + plain `.py` in the .pkg | `tools/spooky_emu/proc` |
| pinHeck System (PIC32 MIPS, compiled C) | Jetsons, Domino's, Rob Zombie's Spookshow | `<GAME>_Vnnn.PRG`, raw flash | `tools/pinheck_emu` |

Not possible today: **Total Nuclear Annihilation** (its .pkg key is unknown),
**America's Most Haunted** (its update is the SD card only, with no PIC32
program in it; changing its rules needs the PIC dumped with a programmer).

## The design: one mode format, four runtimes

JJP's design carries over (`docs/plans/jjp_custom_modes.md`): a mode is a
small `key = value` file, a title has a port report (its switches, lamps,
sounds, fonts, the game's own modes), and a runtime loaded beside the game
runs the modes through the game's own machinery. Spooky's runtimes read the
**same `.mode` keys as JJP's** (`tools/jjp_emu/MODES.md`: `start`,
`start_count`, `shots`, `points`, `seconds`, `complete`, `sound_*`, `lamps`,
`picture`, `video`, `multiball`, `coil_*`...), so the Modes tab's JJP editor
(`webui/modes_jjp.py`, `plugins/jjp/custom_modes.py`) becomes the editor for
Spooky too, fed by each title's port report. A key a runtime cannot do yet is
refused by the check, by name, never silently ignored.

## What each engine offers (proven here, in the emulator)

### Unity (Scooby-Doo v2025.12.01.09)

The games share one framework (Spooky's, in `Assembly-CSharp`): `Machine`,
`Modes` (`Modes.modes`, `Modes.add_mode`, `Machine.modes_loaded`), a `Mode`
base class (`init`, `update`, `process_message(int[])`), messages
(`Messages.switch_active`, `ball_start`, `end_of_ball`, `new_game_started`,
`mode_started`/`mode_stopped`), `Switches.get_switch_name`, scoring
`Mode.score_points(points, tags)` -> `Game.score_points`, `popup_text`.

How our code gets in: `padunity.so` (LD_PRELOAD) waits for the game's Mono
domain, attaches, loads `PadModes.dll` (compiled against the title's own
`Managed/`) and calls `Loader.Init`. Init only subscribes to
`Application.onBeforeRender`; on the main thread, once `Machine.modes_loaded`,
it registers a `Mode` subclass of ours with the game's `Modes.add_mode`. No
game file changes. On a machine, the update carries the game's own launch line
(`sway_config` / `i3_config`: `exec /game/code/uptest/main.x86_64`), which a
PAD-written update starts with the preload.

Proof (`tools/spooky_emu/modes/unity/run_proof.sh`, slot 4, hidden, muted):

```
[native] preloaded into /game/code/uptest/main.x86_64
[managed] loaded: PadModes in domain "Unity Root Domain"
[managed] registered ProbeMode as mode 9001 via Modes.add_mode; now 59 modes
[managed] switch_active 87 "start_button"
[managed] new_game_started
[managed] ball_start (data -1)
[managed] mode_started 51 SKILLSHOT ... 64 GREEN GHOUL
[managed] switch_active 20 "right_inlane"
[managed] scored via Mode.score_points(1000000, base): returned 10000000, player 1 score 10000 -> 10010000
```

Three hits, and the game's own score panel showed 30,016,000. Note the game
scales points x10 inside `score_points` (1,000,000 asked, 10,000,000 given):
the runtime must divide by the title's scale, which its port report records.

### Godot (Looney Tunes 2025.10.08)

Engine 4.1.2-rc custom build; autoloads `Logger, Delays, SpriteCache, Warden,
Settings, Audits, Data, Switches, Coils, Leds, Servos, Audio, Game, Events,
Values, Modes, Flippers, Replay`. 68 game modes in `Modes.all_modes`, each with
a type (BALL...) and priority; modes get `sw_<name>_active` and `evt_*`
calls, timers through `Delays`, points through `Game.score`.

How our code gets in: `override.cfg` beside `main.x86_64` adds one autoload
(`PadModes="*/game/code/uptest/pad/pad_modes.gd"`); Godot reads it at start.
Our autoload adds its modes to `Modes.all_modes`. No game file changes, and
the update is a plain tar PAD writes anyway.

Proof (the PAD-1387 probe, slot 3, hidden, muted; PAD-1419 made it the runtime and `unity/rigrun.sh` drives it):

```
loaded: /game/code/uptest/pad/pad_modes.gd, engine 4.1.2-rc (custom_build), game LOONEY TUNES 2025.10.08
pad_probe added to Modes.all_modes (BALL, priority 116)
game_started
pad_probe: started by the mode manager; running modes: sw_monitor, trough, coinop, ...
pad_probe: evt_ball_started (shoot again false)
pad_probe: 2 s timer (Delays) fired, ball 1, score 0
pad_probe: sw_spinner_active #1: Game.score(12340) -> 12340, score 0 -> 12340
pad_probe: sw_spinner_active #3: Game.score(12340) -> 12340, score 28540 -> 40880
```

### P-ROC (Rick and Morty 2022-09-02, Alice Cooper 1.1.0.5)

Both are SkeletonGame with their own procgame copy; modes are
`procgame.game.advancedmode.AdvancedMode` (System/Ball/Game/Manual), events
`evt_<name>`, switches `sw_<name>_active` / `add_switch_handler`, timers
`delay`, coils `game.coils.<name>.pulse()`, lights `game.LEDs` / `LEDshow`,
sound `game.sound.play(key)`. They differ in scoring (`RMGame.score` vs
`mf._score`) and screen: Rick and Morty draws SkeletonGame layers
(`HDTextLayer`), Alice Cooper sends `||{'cmd':...}` messages to its Unity
player on 127.0.0.1:9999 (SCENE, QUICK_VIDEO, APPEND_TEXT, ADD_IMAGE...).

How our code gets in: `GameController.create_pinproc()` imports the class
named by `config.yaml`'s `pinproc_class`; one added line
(`pinproc_class: padmodes_proc.PinPROC`) loads `padmodes_proc.py` beside the
launcher, which hands back the real board, finds the game and adds its modes
once the game is up. No bytecode changes; the Spooky Write pipeline
re-encrypts the whole .pkg, so it carries the file and the line.

SkeletonGame keeps only a `weakref` to each registered mode
(`notify_mode_registered`), so the runtime must hold its modes itself: the
first run's mode was collected and Start crashed the game
("'NoneType' object has no attribute 'priority'").

Proof (`tools/spooky_emu/modes/proc/mkprobe.sh` + `proc/run_game.sh`, Ubuntu
slot 3, hidden, muted; PAD-Runtime's py27 env is gone):

```
loaded: pinproc_class hook in RMGame (RMGame.pyc)
made mode Pad_probe (AdvancedMode.Game, priority 200) on switch slingRight
mode started: probe; active modes: [... 'Pad_probe', 'ScoreDisplay', 'DimensionController', ...]
evt_ball_starting: ball 1
switch slingRight active (hit 1): game.score(4321) -> 4400, player score 300 -> 4700
sound.play(u'hs_forward'): known=True enabled=True
text layer shown: u'PAD MODE HIT 1'
delay() timer fired 1.0 s after hit 1
switch slingRight active (hit 2): game.score(4321) -> 4400, player score 5300 -> 9700
```

The game's own sling scoring still runs between our hits (4700 -> 5300), and
`RMGame.score` rounds to 100 (4321 -> 4400). Alice Cooper's adapter
(`mf._score`, the Unity player's `append_text`) is written, not yet run.

### pinHeck (Jetsons V004, Domino's V006, Rob Zombie V026)

Compiled C on a PIC32MX795; no mode engine to borrow, so the runtime is ours
(MIPS C in free flash). Room: free flash 320 KB (Jetsons), 314 KB (Domino's),
211 KB (Rob Zombie); ~115 KB free RAM each. Functions found per title
(Jetsons, as an example: link send 0x9D028BD8, video 0x9D02E58C, playSFX
0x9D02F684, numbers 0x9D02E538, SetScore 0x9D02EB4C, AddScore 0x9D02BE84,
score array 0xA000271C + 4 x player); Domino's and Rob Zombie's equivalents
are in the PAD-1387 commit's `pinheck_poc.py` notes. Ticket 6 (below) found the
rest by reading the game's state instead of its switch handlers.

How our code gets in: a `jal` to a game function is re-pointed at a
trampoline in free flash that calls the original and then ours. The PRG has
no header or checksum. On a machine, Service -> UPDATE CODE flashes the
card's `*.PRG` into the PIC (settings reset). Every build has its own
addresses, so `build` refuses a PRG it does not know.

Proof (`python -m tools.pinheck_emu.modes.pinheck_poc build|prove`): switch
0's AddScore(150) re-pointed; on the hit the packets show the game's 150,
then our 1,000,000, our video `EB0` and sound `EB0`; the game plays on
(second hit: its own SDA/SKF video and sound); final score 2,000,300 against
300 stock; the DMD frame at 27.3 s shows EB0.

## Ticket 1 done: the Unity runtime and Scooby-Doo (PAD-1417)

What there is now, and the facts the other tickets build on.

**The runtime** (`tools/spooky_emu/modes/unity`): `padunity.so` (preloads only into
`main.x86_64`, never the topper) loads `PadModes.dll`, which adds one Mode of ours
(`PadRuntime`, mode 9001) with the game's `Modes.add_mode` and runs every `pad/modes/*.mode`
beside it: start switches and hit count, scoring shots, points, seconds (0: until the ball
ends), completion and its bonus, the four sounds, and a panel (title, the mode's total, its
time left) on a canvas of ours above the game's, in the game's TextMeshPro fonts. A mode ends
on time, on completion, at the end of the ball, on tilt and when the game goes back to attract;
start counts reset at every new game. `pad/modes/off` turns them all off. Prebuilt in
`unity/prebuilt/` (`padunity.so`, `scooby_doo/PadModes.dll`, built against the title's own
`Managed/` by `build.sh`); `rigrun.sh` drives a proof.

Scooby-Doo's facts, read from its code (IL) and proven in the game:

- **Switches**: `Switches.name` holds labels ("RIGHT INLANE"); `Switches.get_switch_name(n)` the
  symbols the game uses itself ("right_inlane"). Mode files and the port use the symbols.
- **Points**: `Game.score_points` multiplies by `score_multiplier`, by balls in play unless the
  tags hold `bonus`, by tag bonuses (character, clue, trap), then by 10, and rounds to 100. It
  logs an error unless exactly one *mode* tag is given (`base` is one, `bonus` is not). The
  runtime asks for points / 10 tagged `base` + `bonus`: 250,000 asked, 250,000 scored. The check
  refuses points that are not a multiple of 100 (Mathf.Round: half to even).
- **Sounds**: `Callouts` holds 1,437 static string fields (name -> `Resources` path);
  `Callouts.get(path)` is `Resources.Load<AudioClip>`, `Machine.enqueue_callout` queues it and
  the queue sets `voice_channel.clip` and plays it when the channel is free. The runtime logs
  each of ours the voice channel takes.
- **Launch line**: `sway_config` (6.1 kernels) and `i3_config` (5.10) both end with
  `exec --no-startup-id /game/code/uptest/main.x86_64`. A PAD build makes it
  `exec --no-startup-id env LD_PRELOAD=/game/code/uptest/pad/padunity.so /game/code/uptest/main.x86_64`.
  The game md5-compares these files with the installed copies at every start, copies a changed
  one in and reboots once: so the machine takes up the modes on its second start after the
  update, and the stock update takes them out again the same way.

**The port report** (`modes/ports/scooby_doo-2025.12.01.09.json`) is the runtime's own read of
the running game (`PADMODES_PORT`, `rigrun.sh --port`): 80 switches (symbols, labels, numbers),
119 lights, 1,437 callouts with their paths, 58 game modes, 10 fonts, the score tags and the
points scale measured with one 1,000-point award (10,000 scored), plus the title's starter picks.

**mkspkmodes.py**: the checker (JJP's grammar and value checks, Spooky's own key list; every
other JJP key refused by name, "not on Spooky games yet"), `stage` (the `pad/` folder) and
`build` (the stock `.scooby` streamed into a new one with `pad/` added and both launch lines
patched; 23 s for Scooby-Doo's 1.8 GB). A rebuilt modes update keeps one preload.

**The rig**: `run_game.sh` preloads whatever the update's own launch line preloads, and takes
`SPK_PAD_OVERLAY=<folder>` (Try it: the folder becomes the run's `uptest/pad`, preloaded the same
way, no new update); `prepare.sh` keeps a modes update's build beside the stock one
(`<title>_<version>_padmodes`), never in its place.

**The app**: the Modes tab on a Spooky update is the JJP page's form with Spooky's keys
(`webui/modes_spooky.py`, `plugins/spooky/custom_modes.py`; the page's calls go to
`modes.spk_*`), Try it (the Emulate tab on the stock update with the staged folder), Build (in
the app, no Linux needed), and Write carries the modes for that title with any asset changes
(modes with problems stay out and the log says so).

Proof (slot 1/4, hidden, muted): the starter modes staged as Try it does, and the same modes in
a `.scooby` PAD built, booted as an update with no overlay. Snack Attack: two inlane hits start
it, three slings score 250,000 each, the third completes it with the 2,000,000 bonus. Target
Rush: a standing target starts it, it ends after 8 s. Every callout found and played on the
game's voice channel; the panel on the screen in the game's Ghoul font.

What the next tickets take from here: the other Unity titles need their own `PadModes.dll`
(built against their `Managed/`), a port report each (`rigrun.sh --port`), and their own
scoring facts (their `score_points` may differ); `mkspkmodes.py` and the Modes tab are ready
for any port report with `engine` and `runtime_dll`.

## Ticket 2: the other five Unity titles (PAD-1418)

**Three more frameworks.** The runtime does not compile against any of the five as Scooby-Doo's
code was written, so `PadModes.cs` is now the core (mode files, the mode logic, the panel, the port
report) and how it joins a game is one glue file per framework (`unity/glue_*.cs`; `build.sh
<Managed> <out> <framework>`). Every glue gives the core the same `Glue` class (Ready, Ensure,
Poll, the switches, the score and the scoring call, the callouts, lights, modes) and a `Hook : Mode`.

| framework | titles | joins with | switches | game / ball | points | callouts |
|---|---|---|---|---|---|---|
| scooby | Scooby-Doo | `Modes.add_mode` once `Machine.modes_loaded` | `int[]` messages | messages | `score_points(/10, base bonus)` | `Callouts` + `enqueue_callout` |
| bj | Beetlejuice | `Modes.add_mode` (`Mode(float)`, abstract `Load`) | `Message.Event.switch_active` | messages (`end_of_game`) | `ScorePoints(p, null, 0)`: 1:1 | `Media` VOICE fields + `CalloutEnqueue` (2,976) |
| pc | Halloween, Ultraman | `AddMode(m, 0)` once `soundmanager.finishedLoading <= -2` | `sw_any(n, sym, state)` (first in the list) | polled (`gameStarted`, ball, player, `tiltmode.tilted`) + `evt_ball_ending(msg)` | `Score(p, force)`: 1:1 | `audioHelper.playVoice` (495 / 670 wavs) |
| pc-tcm | Texas Chainsaw (Unity 2019) | `add_mode` once `finishedLoading == -2`; again after the menu drops it | a generated `sw_<sym>_active` per switch at the end of its private method cache (walked last to first: ours first, before any mode can stop the switch) | polled + `evt_ball_ending(msg)` | `addScore(p, 0, notValidForComboBet)`: x the 2X playfield | `audioHelper.playVoice` (804) |
| ed | Evil Dead | `add_mode` once `loaderCheck.loadProgress >= 10` | `sw_any(n, sym, bool)` | polled (no game/ball broadcast) + `evt_ball_ending_mode()` | `addScore(p, applyMux: false)`: 1:1 | `audio.playVoice` (1,759) |

A handler returning false stops a switch or event for the modes after it on the pinballController
titles: every one of ours returns true. Halloween's `Mode` makes every mode `bail_on_tilt`; ours is
not. Texas Chainsaw calls `evt_game_started` with no argument and Halloween with one, which is why
the game's start and its balls are polled there (`PadRuntime.Track`).

**The way in: dllmap.** None of the five updates carries a launch line (Texas Chainsaw, Evil Dead,
Halloween and Ultraman are started by the machine's image; Beetlejuice's `_profile` just runs
`sway`). Every one opens its board through Mono's `SerialPort`, which loads `MonoPosixHelper`; the
update's own `main_Data/MonoBleedingEdge/etc/mono/config` maps that library, and a modes update maps
it to `/game/code/uptest/pad/padunity.so` (`padunity_dllmap.so`: the same loader, NEEDing the real
`libMonoPosixHelper.so` beside the game by its RUNPATH, so Mono finds the serial functions through
it). Mono loads it when the game opens its board; its thread finds the domain and calls
`Loader.Init` as the preload does. Proven on Evil Dead (a hand-made build: the loader logged from
inside the game with no preload anywhere). Port reports say `"load": "dllmap"`; Scooby-Doo stays on
its launch line (`preload`). `Unity 2022.3`'s `RuntimeInitializeOnLoads.json` would have done for
four of the five, not for Texas Chainsaw's 2019.3 (its list is inside `globalgamemanagers`).

**Containers.** `mkspkmodes.build` unwraps and wraps with the plugin's own GPG code
(`update_container`): Beetlejuice signed again with PAD's key (the machine asks, as for any Write
update), Halloween and Ultraman encrypted again with their passphrase (`gpg_format`). The Write tab
carries modes for those containers too, `pad/` beside `main.x86_64` (`uptest/pad` on the four).

**Ports** (`ports/<label>.json`, the runtime's own read, `rigrun.sh --port`; empty switch slots
left out): `beetlejuice-2026.09.15.11` (63 switches, 118 lights, 2,976 callouts, 60 modes, 67
fonts), `texas_chainsaw-1.00` (69, 98, 804, 29, 4), `evil_dead-2026.07.15` (83, 129, 1,759, 33, 6),
`halloween_78-1.18.1` (66, 146, 495, 55, 8), `ultraman-1.18` (66, 146, 670, 55, 5). Every one
measured 1:1 (1,000 asked, 1,000 scored; Texas Chainsaw 2 s into the ball, after its own
ball-started event set the multiplier). The dateless names (`tcm-1_00.pkg`, `code_H78.pkg`,
`code_UM.pkg`) are found by `update_name` + `update_size` (else the game's only port), extracts by
`version_match` (`TCM V1.00`, `version_118.txt`, `version_1_18.txt`).

**Rig fixes made on the way.** `prepare.sh` holds `flock` on the cache's `.prepare.lock`: two
tickets' prepares at once deleted each other's `unpack.partial` ("could not unpack ... damaged"),
and its default cache keeps 6 builds (1-2 GB each), not 2, which another ticket's prepare used to
evict a build a queued run was about to boot. `gpg._find_gpg` prefers GnuPG's own `gpg.exe` on
Windows: Git for Windows' MSYS gpg on the PATH fails on Windows paths.

**Proven** (rig, hidden, muted): on all five, the runtime (Try it overlay) joined the game's mode
list, saw the game start and the first ball, scored through the game's own call and wrote the port.
Then every title's modes update, built from the library's stock update as the app's Build does
(Scooby-Doo's on the refactored runtime too), booted with no overlay: the runtime loaded from the
update itself (`preload` on Scooby-Doo, `dllmap` on the five), mode 1 started on its start switches,
scored each shot and paid its completion bonus, mode 2 started and ended when its time ran out,
callouts went to the game's voice channel, and the panel (title, total, timer in the title's fonts
and colors) showed over the game's screen (`artifacts/PAD-1418/after_rig_panels_six.png`). An
unpack from D: in the Ubuntu rig takes 4-7 minutes, longer than rigrun's wait for the runtime:
run `prepare.sh` first.

## Ticket 3 done: the Godot runtime and Looney Tunes (PAD-1419)

**The runtime** (`tools/spooky_emu/modes/godot/pad_modes.gd`, GDScript, no build step): one
more autoload, named by an `override.cfg` beside `main.x86_64`
(`[autoload] PadModes="*/game/code/uptest/pad/pad_modes.gd"`), which Godot reads at start. It
runs every `pad/modes/*.mode` with the same keys and rules as the Unity runtime (start switches
and hit count, shots, points, seconds, completion and bonus, the four sounds, the panel; ends on
time, completion, the end of the ball, tilt and the end of the game; start counts reset at a new
game; `pad/modes/off` turns them off). No game file changes. Log: `/game/tmp/pad_modes.log`.

Looney Tunes' facts, read from its GDScript (the PCK) and proven in the game:

- **Switches**: `Switches.items[n].name` ("inlane_left"), `display_name` the label. The runtime
  hears `Warden.sw_active(n)`, which Warden emits for every switch after the game's own
  `sw_<name>_active` events, and counts a switch only while a ball is in play
  (`Game.gameplay_active`, not tilted, not the switch test). The game's mode manager finds a
  mode's handlers by method name, so a mode of ours cannot take switches named in a file that
  way; the signal needs nothing from the game.
- **Points**: `Game.score(points)` multiplies by the playfield multiplier (`Game.multiplier`)
  and a shot's special multiplier and rounds to 10 (`snapped(..., 10)`): scale 1, measured
  (1,000 asked, 1,000 scored). The check refuses points that are not a multiple of 10. The
  multiplier counts for a mode's points as for the game's own awards (the Unity runtime keeps
  Scooby-Doo's `score_multiplier` too).
- **Sounds**: `Audio.voice_lines` (key -> `res://` path, played with `Audio.play_voice(key,
  PLAY_QUEUED)`: the voice channel, queued behind whatever it is saying) and `Audio.sfx` (key ->
  preloaded stream, `Audio.play_sfx`). The port lists both, voice first. The runtime logs each
  callout of ours when the voice channel starts it.
- **Panel**: a `CanvasLayer` (layer 128) over the game's screen, a `Panel` and three `Label`s in
  the game's fonts (`res://assets/fonts/*.ttf|otf`, by file name), each shrunk to its row (Godot
  4.1's Label has no auto-size). Mode timers stand still while `Game.timers_paused`.
- **Install**: the in-game updater untars the `.looney` (a plain tar) into `/game/update`; at
  the next power-up the profile empties `/game/code/uptest/*` and copies the update in
  (`docs/plans/pad980_research/research_looney_proc.md`), so the modes are in from that start,
  and a stock update takes `override.cfg` and `pad/` out again.

**Port reports**: `rigrun.sh --port` has the runtime write the game's own read
(`PADMODES_PORT`); `mkspkmodes.py port` makes it the shipped file. Both Looney Tunes builds
in the library have one: 2025.10.08 (96 switches, 107 lights, 1,101 sounds of which 918 voice,
68 game modes, 12 fonts) and 2025.03.01 (the same switches and lights, 1,019 sounds, 66 game
modes, 11 fonts: no `digital-7 (mono)`, no `bugs_count_one`, so its starter folder ends Spinner
Frenzy on `times_up1`).

**mkspkmodes.py** follows the port's `engine`: Godot ships `pad/pad_modes.gd` and the top-level
`override.cfg`, rewrites no launch line, and `build` writes a plain-tar stock update as a plain
tar (a gzip one as gzip); a rebuilt modes update keeps one `override.cfg` and one `pad/`.
**Write** packs the modes into plain-tar updates too (`formats.create_tar(pad_modes=...)`, an
extract's own `pad/` and `override.cfg` replaced). **The rig**: `run_game.sh` takes a Godot Try
it folder (`pad_modes.gd` in it) as `uptest/pad` and writes the same `override.cfg`;
`prepare.sh` keeps a Godot modes update beside the stock one, and now unpacks one update at a
time (a lock on the cache: two rigs preparing at once wiped each other's `unpack.partial`).
**The app**: the Modes tab knows Looney Tunes (both builds), its Build card says how a Looney
Tunes update installs, and the help gives each game's rounding.

Proof (hidden, muted, slots 1/2/5): Try it on 2025.10.08 and 2025.03.01, and PAD-built updates
of both booted with no overlay. Carrot Chase: both inlanes start it, three slings score 250,000
each and complete it with the 2,000,000 bonus (the game's score panel agrees); started again, it
ends when the ball drains, and on tilt. Spinner Frenzy: the drop target starts it, the spinner
scores 50,000 a hit, it ends after 10 s. Every callout found and played on the game's voice
channel; the panel on the screen in CCHeroSandwichMeat / Truculenta-Bold.

## Ticket 6 done: the pinHeck runtime and Jetsons (PAD-1422)

**The runtime** (`tools/spooky_emu/modes/pinheck/padheck.c`, MIPS32 C, 4.6 KB): linked per game
build into the free flash after the program (`build.sh`, WSL `gcc-mipsel-linux-gnu`; no C library,
no start-up code, every variable in one struct in RAM the game never writes). It joins the game
through **one re-pointed call**: the `jal houseKeeping` inside the function every one of the
game's loops calls to wait for the next millisecond (attract, play, bonus count, tilt, service).
Its entry runs houseKeeping and then the modes, once per millisecond whatever the game is doing.
The modes are data packed after it (`pinheck.py`, struct `pad_data`), so the app writes a modes
PRG with no compiler. Same keys and rules as the Unity and Godot runtimes (start / start count,
shots, points, seconds, completion and bonus, the four sounds, the panel); a mode ends on time, on
completion, when the ball ends, on tilt and when the game ends; start counts reset at a new game.
Its log is `[pad] ...` lines on the game's own serial monitor (UART1). Fonts and colours are
refused by name (`keys_not_here` in the port report): the panel is the game's own text on the DMD.

**Jetsons V004's hook table** (`pinheck/hooks.py`; every function also checked by its first bytes,
the PRG by its sha1, so another build is refused, never patched blind). gp = 0xA0008200, the link
object `this` = gp - 0x7BA8:

| what | where | how it was found |
|---|---|---|
| tick | jal 0x9D018BB4 (houseKeeping) at 0x9D02EFC8, in the ms-wait 0x9D02EFC0 | `find_idle_loops`; callers' $ra per phase (attract 0x9D0144C0, play 0x9D0146FC, bonus 0x9D0207D8) |
| switches | 0xA0000740: 8 row bytes, switch n = bit n & 7 of byte n >> 3, set while closed | RAM diff per ms around a held switch; byte 4 = 12 in attract (trough 34, 35) |
| ball / player | 0xA0000720 (0 between games), 0xA00006E6 (1-based) | RAM diffs over whole games (PAD-1423 confirmed game over) |
| ball live | 0xA0000690: 0 from the drain through the bonus count | the same |
| phase | 0xA00006C3: 1 serving, 2 shooter lane, 3 in play | the same |
| tilt | 0xA000073C set by tilt() 0x9D01F8A4; warnings 0xA000073D | the cabinet-switch handler's TL1/TL2 videos and tilt() |
| AddScore | 0x9D02BE84 (points in a0): score[player] += points, no multiplier, no rounding | its code; asked 250,000, scored 250,000 |
| sound | playSFX 0x9D02F684 (this, channel, folder, clip0, [16] clip1, [20] priority) | the POC |
| text | text 0x9D02A314 (this, 0, column, line, s, [20] colour): packet 0x12, byte 0 = column << 3 \| line (4-pixel columns, 8-pixel lines, 128x64 DMD); 13 03 xx shows/hides the layer (0x9D02FC3C); 06 n ff.. clears line n | the service menu's text calls |
| coils | fireCoil 0x9D02CE5C (this, coil, time), coil table 0xA0002280 | the one writer of the coil pins (0x9D02A9D8) and its caller |
| lamps | 0xA0002384: 64 brightness bytes the lamp interrupt (0x9D024F2C) multiplexes; houseKeeping fills it every ms | the Timer2 handler |
| free | flash 0x9D030000-, RAM 0xA0002F48..0xA001DF48 untouched over a whole game | a canary fill |

Coils and lamps are in the table for ticket 8; no key uses them yet. A value written to the lamp
table after houseKeeping (where the runtime runs) holds for that millisecond.

**The build**: `mkspkmodes.py` takes `engine: pinheck` - `stage` writes the modes PRG from the stock
update (Try it), `build` writes the stock zip again with only its PRG replaced (9 s for Jetsons'
0.35 GB); a modes PRG given as stock is cut back to the stock one first. On the machine:
Service -> UPDATE CODE flashes the card's PRG into the PIC (research_pinheck.md); the stock update
takes the modes out the same way. The modes PRG keeps the game's version, so the game keeps its
settings. **Write** packs the modes into a Jetsons update (`create_zip` with the PRG rewritten), and
finds the title of an extract by its PRG's name. **Try it**: the pinHeck window takes `--prg`
(the modes PRG on the update's own card); the Emulate tab passes Try it's PRG. The window's unpack
cache now always takes the program from the zip it was given (a modes update has the stock one's
name and shares its folder). The Modes tab hides the font and colour fields on Jetsons; its Build
card says how a pinHeck update installs.

**Port report** (`ports/jetsons-V004.json`): the games' switch test shows numbers only, so the
switches are `switch_0`..`switch_63` (32 shooter lane, 34/35 trough); the card's 100 sounds by
their three-letter names; points scale 1, no rounding.

Proof (`pinheck/prove.py`, headless, muted): the PAD-built `Jetsons_Code.zip`, unpacked by the
emulator's own unpacker, no Try it. Astro Rush: two hits on switch 20 start it, three shots score
250,000 each (the game's own 150/250 first), the third completes it with the 2,000,000 bonus
(score packets 250,252 -> 2,750,652). Sprocket Spin (no timer) keeps running through two ball-save
drains and ends when the ball ends, at the bonus count. A timed mode ends on time; a mode ends on a
real tilt (third warning). Every sound went out as the game's sound packet (EB0, C01, G00, H00,
J00); the panel is on the DMD over the game's video. Tests: `tests/test_spooky_modes_pinheck.py`
runs the shipped runtime binary on Unicorn against a stand-in game (no game files).

## Rig fix made on the way

Both Spooky rigs now stub `sync` (logging no-op on the game's PATH): WSL's
shared kernel has a superblock that never answers, every `sync` hangs for
good, and Scooby-Doo, Looney Tunes, Rick and Morty and Alice Cooper all run
`sync` at boot. That hang, not our code, is what stopped the first Unity and
P-ROC probe runs right after `bash command: sync`.

## The split (8 tickets)

Each runtime ticket delivers a mode made in the app running on its title in
the emulator, from an update file PAD wrote, with the core `.mode` keys
(start, start count, shots, points, timer, completion, the game's sounds, a
text panel). The last ticket brings the rest of the keys to every runtime.

1. **Unity runtime + Scooby-Doo, end to end.** `padunity.so` + `PadModes.dll`
   as a real runtime reading `.mode` files; Scooby-Doo's port report from its
   `Assembly-CSharp` (switches, lamps, sounds, the game's modes, the points
   scale); Write builds a `.scooby` whose launch line preloads the runtime;
   the Modes tab on Spooky (the JJP editor, fed by the port report) and Try it
   on the Spooky rig. This ticket also builds the shared Spooky Modes-tab
   wiring the others reuse.
2. **Unity: the other five titles.** Beetlejuice (GPG-signed update),
   Texas Chainsaw (Unity 2019), Evil Dead, Halloween and Ultraman (Pinotaur):
   port reports, per-title framework differences, each proven on the rig.
3. **Godot runtime + Looney Tunes, end to end.** `pad_modes.gd` reading
   `.mode` files, the port report from the PCK, Write adds `override.cfg` +
   `pad/`, Modes tab and Try it.
4. **P-ROC runtime + Rick and Morty, end to end.** `padmodes_proc.py` reading
   `.mode` files, port report from the machine yaml and asset lists, Write
   adds the file and the `config.yaml` line inside the re-encrypted .pkg.
5. **Alice Cooper on the P-ROC runtime.** Its score call and its Unity
   player's screen messages; port report; rig proof.
6. **pinHeck runtime + Jetsons, end to end.** The C runtime in free flash,
   modes compiled into the PRG as data, Jetsons' hook table (ball start/end,
   lamps, coils found by the dynamic method), Write puts the patched PRG on
   the update; the emulator proof.
7. **pinHeck: Domino's and Rob Zombie.** Their hook tables and proofs.
8. **Spooky modes to JJP parity.** Lights on the game's lamp/LED layers,
   a mode's own sounds, music, picture and video, multiball and ball save,
   coil pulses and holds, start rules, on every runtime that can do them.

Out: Total Nuclear Annihilation (no key), America's Most Haunted (no PIC
program on its card).
