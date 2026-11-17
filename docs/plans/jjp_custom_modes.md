# JJP custom modes (PAD-1335)

Status 2026-11-16: **emulator-proven on two titles, Guns N' Roses 3.03 and
Wonka 03.03**, each with its own key. A custom mode, loaded from outside the
game binary, runs inside a live game: it starts on a target, plays a game sound,
shows a countdown banner, scores 1,000,000 a hit through the game's own scoring
(the game draws its own floating "1,000,000"), lights a lamp on its own layer
over the game's and hands it back when it ends, and finishes on the game's own
mode timer or on completion. The game plays on. No game code is patched. The
runtime is the one unchanged `jjpmodes.so` on both titles (it finds everything
by exported name), which is what shows the SDK is generic across JJP games;
`tools/jjp_emu/MODES.md` has the per-title table (PAD-1347).

## Why it works on JJP

The retail `game` is a Sentinel LDK Envelope: about 7,000 of its functions are
ciphertext at rest, and each decrypts itself on first call through a shared
trampoline. Calling them works. They stay decrypted in memory, so they can be
read through `/proc/<pid>/mem`, which never trips the anti-debug gate. Never
attach gdb or strace.

The binary **exports its whole C++ engine** in `.dynsym` (22,265 names on GnR;
`jjpelf.py` rebuilds it, since the section headers are stripped). A mode needs
nothing that isn't an exported function or a plain data pointer.

| Piece | What the engine has | How we use it |
|---|---|---|
| Mode | `Mode::Mode(name, id, ModeManager*, Lamp*, run_id, grace_id, grace_grace_id, Audit*, Audit*)`; 280-byte objects; `vtable for Mode` (24 slots) | Build one in our own memory and point it at a **copy** of Mode's vtable with three slots replaced |
| Lifecycle | `Mode::start` calls `proc_create(run_id, start_run_func)`. `run_proc` ticks at 125/s (+0x48 seconds, +0x4c ticks) and calls `hook_tick_work` (+0xa8), `hook_do_mode_start_choreo` (+0xb0), `is_timer_paused` (+0x38), then the total choreo (+0xb8), grace and `end` | Unchanged: the game runs our mode exactly as it runs Slash Solo |
| Trigger | Each `Switch` is a 104-byte global: +0 id, +8 name, +0x10 dispatch fn, run as a proc by `Switch::do_dispatches` | Wrap the dispatch pointer (one aligned 8-byte store) and call the original first |
| Points | `Mode::score_and_total` (+0x88) | Scores and totals like any game mode |
| Sound | 2,342 `se_*` `SoundEffect` globals; `play` is virtual on GnR (`GnrSoundEffect`) | Find `play` in the object's vtable and call it |
| Screen | Allegro 5 is a shared library the game imports | Interpose `al_flip_display` and draw on the backbuffer before the real flip |
| Events | ~80 `Hook<HookX_, Arg>::list` globals (ball start, switch dispatch, score, render, keyboard, state change...). Each is a `FastLinkedList`: head `{first, magic 0x45}`, node `{prio, &desc, name, next}`, desc `{fn, name}` | Not used yet; this is how the SDK will take game events |

`ModeManager::manager_list` is empty on GnR: modes are **named globals**
(`slash_solo`, `song_mode`, 22 `SongMode_*` songs, `tour_mode1..3`,
`no_sympathy_for_the_devil`, ...). `jjpmodelist.py` lists all 33 live ones
with name, id and proc id, on any title.

## The SDK (PAD-1337)

Status 2026-11-16: **modes are data, and a PAD-written install ISO carries
them to a real machine.** Proven on Guns N' Roses 3.03 and Wonka 03.03 in the
emulator, same runtime on both. How to write modes: `tools/jjp_emu/MODES.md`.

| Piece | What it does |
|---|---|
| `jjpmodes.c` | The runtime. Reads `title.cfg` + `*.mode` from `JJP_MODS_DIR` (default: `modes/` beside the library) and runs each mode as an engine Mode: start shots and a start count, scoring shots, points, the game's timer, completion, sounds, lamps, the game's fonts, a `game_modes` policy |
| `mkjjpmodes.py` | `build`: a stock install ISO in, the same ISO out with the runtime, the modes and one guarded `rungame.sh` line; `check`: a mode folder against a title's port report; `inspect`: what an ISO carries |
| `jjpport.py` | What a title offers, statically from its binary: can it run modes, its Mode vtable, shot switches, lamps, sounds, fonts, Mode classes, starter defaults |
| `modes/ports/`, `modes/examples/` | The report and a starter mode folder per JJP title in the library |
| `run_game.sh` | `JJP_MODS_SO` + `JJP_MODS_DIR` preload the runtime on the rig; an image carrying `scripts/padmodes.sh` gets it sourced exactly where `rungame.sh` does |
| `buildmods.sh` | Builds the runtime against an image's glibc (`JJP_MODS_LIBDIR` picks one) |

What was learned on the way, all on GnR 3.03:

* **Vtable slots by address, not offset.** The compiler folded identical empty
  virtuals: `Mode::is_timer_paused` has the same address as
  `ModeManager::hook_start_final_mode`, and the start and total choreo hooks
  are one body (slots 0xb0 and 0xb8). The runtime matches addresses in
  `_ZTV4Mode` and tells equal ones apart by declaration order.
* **Lamps are layers.** `LampBuffer::render_all` walks `LampBuffer::lblist`
  (191 layers, sorted by priority: `lb_rendered` 0, `lb_background` 1, modes
  ~0x400-0x4ff, `lb_award` 1e9, tilt, diagnostics, Bluetooth) and blends each
  light (24-byte `rgb_led_t`, indexed by `hook_lamp_table` position) by alpha
  into `lb_rendered`. A layer is skipped unless its public `active` byte (+0x2c)
  is set; no exported call sets it, so the runtime reads the offset off the
  decrypted `render_all` (`cmpb $0x0,0x2c(%rbp)`). Ours sits at 0x7fff. Proof:
  `lb_rendered` carries our colour at the mode's lights, blinking at the
  requested rate, and the game's own colour after the mode.
* **The rig's LED shared memory is not a lamp proof.** It holds the last 64-byte
  frame per LED board only (128 bytes on GnR); read `lb_rendered` instead.
* **Timing by the clock.** The hidden rig draws 4-7 frames a second (software
  GL); a blink or debounce counted in frames aliases. Everything timed uses
  CLOCK_MONOTONIC.
* **The game's threads.** Game logic runs on the proc thread (`game:procDispat`),
  drawing on the main thread. Mode::start and scoring happen in our switch
  wrappers (procs). An end asked for from the frame hook is done in the
  mode's own `hook_tick_work` (its run proc), where the game ends a mode.
* **State 5 is a ball in play**, not "a game is on": it leaves 5 at every ball
  end, and the game stops our mode's run proc there (no `end()` call). A
  custom mode ends with the ball, as the game's own do.
* **Yielding.** The game's modes are found by walking the game's own `.dynsym`
  in memory for objects whose vtable carries `Mode::is_running` (33 on GnR).
  A test-only hook (`JJP_MODS_TEST_GAMEMODE`/`_SWITCH`) starts Slash Solo from a
  switch: Jam Session's start shot was refused ("yielded to slash_solo") and a
  running Jam Session paused under it and resumed after. The balls-in-play
  count blips (6 for one frame with a ball in the shooter lane), so a
  multiball is >1 ball for 500 ms.
* **Old glibc.** glibc 2.38+ headers turn `atoi`/`strtol` into
  `__isoc23_strtol`, which an image's glibc lacks; the runtime parses numbers
  itself and `buildmods.sh` refuses any `__isoc23_` import.
* **The hostname leak.** A GnR run renames the WSL host
  (`SPI-SWH-000000`); the proof scripts put `Eagle` back.
* **Killed games can pin their memory.** On 2026-11-15 a plain `sync` in WSL
  hung (one superblock never answers; all distros share the kernel). The
  game's persistence thread calls sync(2) through an import the protected
  binary resolves itself, so no preload can catch it, and every killed rig game
  stayed a zombie holding its memory (20 held 16 GB, WSL in full swap).
  `killgame.sh` now says so; only `wsl --shutdown` frees it.

## The game's own modes (PAD-1351)

Status 2026-11-16: **a `.stock` file changes one of the game's own modes - its timer,
its points, which shots count - emulator-proven on Wonka 03.03's Candy Lane** (timer
30 s to 60 s, awards x3, a shot taken off it, a switch giving it a shot) and mapped
statically on every title. How to write one: `tools/jjp_emu/MODES.md` ("The game's own
modes, changed").

What the engine showed (Wonka 03.03, read through `/proc/<pid>/mem` of a running game):

* Each stock mode is one global per class (`cl_mode` CandyLaneMode, `wbc_mode`
  WonkaBarCraze, `mtv_mode` MikeTeaveeMode, ...). Shots are `shot_id_t` numbers. Each
  switch's dispatch calls `switch_do_dispatch_work(shot)`, which puts the shot in
  argument 4 of its proc and calls the table's `shot_made_<name>()`. That function
  calls every interested mode's `shot_dispatch()` **directly** (Candy Lane hears
  12 of the 41 shots).
* Calls a class makes on `this` are speculatively devirtualised: "if the slot still
  holds my own function, call it inline, else call the slot". Replacing a slot is
  therefore enough to catch `score_and_total`, `set_time` and the is_running checks
  from inside a class. A call on a known global (`shot_made_*` -> `X::shot_dispatch`)
  is fully direct, so `shot_dispatch` itself cannot be caught; its opening
  `this->is_running*()` can, and the return address says who asked.
* `Mode::restart` re-creates the run proc only when it is gone, so `set_time` from
  inside the run proc's first entry (`start_run_func` jumps through the `run_proc`
  slot) is as safe as the game's own `set_time` right after `start`.
* The Wonka Bar award modes keep one timer for the class family
  (`WonkaBarAwardModes::wba_timer`, from `adj_wba_timer_difficulty`: 60 - 15 x the
  setting) and count it down in `timer_run_proc` unless `game_timers_paused()`.
* The shot table is ciphertext in the file and lives in an `rwxp` mapping of the game
  (the Envelope's), so it is found at run time by the handler pointers, never
  statically.

## Files (PAD-1335 proof, superseded by the SDK above)

- `tools/jjp_emu/jjpmodelist.py`: the live mode roster.
- `tools/jjp_emu/jjppoke.py`: press a switch by name (hidden runs).

## Run it

```
wsl -u root -- bash tools/jjp_emu/buildmods.sh
wsl -u root -- env PAD_HIDDEN=1 JJP_MODS_SO=/var/tmp/jjpmodes.so JJP_MODS_DIR=$PWD/tools/jjp_emu/modes/examples/GunsNRoses-v03.03 bash tools/jjp_emu/watch.sh /mnt/d/Pinball/images/JJP/GunsNRoses-v03.03.iso
wsl -u root -- python3 tools/jjp_emu/jjppoke.py dswitch_coin_1 dswitch_start
wsl -u root -- python3 tools/jjp_emu/jjppoke.py switch_target_jam
# a machine:
wsl -u root -- python3 tools/jjp_emu/mkjjpmodes.py build --iso <stock>.iso --modes <folder> --out <new>.iso
```

## Rig fixes made on the way (PAD-1335)

- **The JJP scripts killed other rigs' games.** `killgame.sh` ran
  `pkill -9 -x game`, and `status.sh` / `swdump.py` counted or read any
  process called `game`, which includes a Spike 2 rig slot's game (a Turtles
  run on rig 2 at the time). They now keep to processes rooted in the JJP jail
  (`jjp_rig_pids`, `swdump.find_pid`).
- **Hidden runs.** `PAD_HIDDEN=1` now gives the JJP rig a private Xvfb, opens
  no switch matrix, and still refreshes the device dump
  (`jjpsw_launch.sh --dump-only`). A stale dump from an older GnR build had
  seeded an empty trough, so Start only asked for money.
