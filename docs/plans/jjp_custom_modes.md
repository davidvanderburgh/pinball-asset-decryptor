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
| Events | ~80 `Hook<HookX_, Arg>::list` globals (ball start, switch dispatch, score, render, keyboard, state change...). Each is a `FastLinkedList`: head `{first, magic 0x45}`, node `{prio, &desc, name, next}`, desc `{fn, name}`; next is at +0x18, nodes sort by prio (the game's at 1, 1000, 2000), and the game walks a list as `node->desc->fn(arg)`, stopping at a return > 0 | Start rules (PAD-1354): one node of ours at the tail of each list a rule needs, returning 0. See "Start rules" below |

`ModeManager::manager_list` is empty on GnR: modes are **named globals**
(`slash_solo`, `song_mode`, 22 `SongMode_*` songs, `tour_mode1..3`,
`no_sympathy_for_the_devil`, ...). `jjpmodelist.py` lists all 33 live ones
with name, id and proc id, on any title.

## The SDK (PAD-1337)

Status 2026-11-17: **modes are data, and they reach a real machine two ways:
a USB stick applied through the game's own Update USB hot fix (no reinstall,
scores kept), or a PAD-written install ISO.** Proven on Guns N' Roses 3.03 and
Wonka 03.03 in the emulator, same runtime on both; on Wonka both delivery ways
were run end to end through the game itself (PAD-1349, MODES.md "On a real
machine"). How to write modes: `tools/jjp_emu/MODES.md`.

| Piece | What it does |
|---|---|
| `jjpmodes.c` | The runtime. Reads `title.cfg` + `*.mode` from `JJP_MODS_DIR` (default: `modes/` beside the library) and runs each mode as an engine Mode: start shots and a start count, scoring shots, points, the game's timer, completion, sounds, lamps, the game's fonts, a `game_modes` policy |
| `mkjjpmodes.py` | `build`: a stock install ISO in, the same ISO out with the runtime, the modes and one guarded `rungame.sh` line; `check`: a mode folder against a title's port report; `inspect`: what an ISO carries; `stick`: a USB stick folder whose `hotfix/runme.sh` installs the modes (or turns them off/on, or removes them) when the service menu's USB Update hot fix runs it (hold left flipper, Plus Minus Plus Minus, ENTER ENTER) |
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

## In the app (PAD-1350)

Status 2026-11-16: **a mode made only in the app runs on the Wonka emulator
from an ISO the app built.** On a JJP game the Modes tab is the SDK's editor
(`webui/modes_jjp.py`, `plugins/jjp/custom_modes.py`, `tabs/modes_jjp.js`;
how to use it: `tools/jjp_emu/MODES.md` "In the app"). It lists the nine titles
whose port reports can run modes; Dialed In 02.02, Hobbit 04.02 and Toy Story
02.04 got their reports and starter folders here (same Mode vtable slots as
Wonka, starters pass `check --port`, the runtime loads with every import bound
in a chroot of each image's root), and Wizard of Oz 08.02 and Avatar 01.03 got
reports saying they cannot.

The proof, 2026-11-16, Wonka 03.03 with Wonka's own key:

* In the real page (Edge, clicked): the starter deleted, **New mode**, then
  "Golden Ticket" set field by field through the pickers - start
  `switch_target_gobstopper` x2, shots gobstopper target / left loop / spinner,
  750,000 a shot, 25 s, complete 4 (+3,000,000), four of the game's Golden
  Ticket sounds, `lp_gobstopper` + `ls_golden_tickets` in ffd700 at 2 a second,
  gold title, panel at the bottom. The check: no problems.
* The page's **Build**: `Wonka-v03.03.modes.iso`, 3.2 GB in 268 s, the
  runtime compiled during the build against the ISO's own glibc.
* That ISO on the rig with nothing preloaded by the rig: its own `rungame.sh`
  hook loaded the runtime ("PAD custom modes: 1 mode(s) loaded"); the first
  gobstopper hit counted "1 of 2", the second STARTED it for 25 s; the panel
  drew GOLDEN TICKET in gold at the bottom with the total and the timer; four
  shots COMPLETED it, mode total 6,000,000 (4 x 750,000 + 3,000,000).
* Its lamps, sampled from the game's final composite (`lb_rendered`) while it
  ran: `lp_gobstopper` and the five lights of `ls_golden_tickets`
  (`lp_ticket_1`..`5`) ffd700 in 37 of 74 samples, black in the rest (2 a
  second); `lp_gi_tv`, not in the mode, the game's white throughout; no light
  gold before the mode or after it (handed back to the game).

Fixed on the way: the build's scratch went beside the output on a Windows
drive (a 16 GB sparse root through WSL's file bridge) - it is in
`/var/tmp/pad_jjpmodes_work` now; `jail.sh` reused a mounted jail whose lower
was another image's root (two tickets' runs crossed and the rig booted plain
Wonka with no error) - it rebuilds it when idle and refuses while a game runs;
the checker refused lamp groups in `lamps`, which the runtime takes - but the
runtime lit nothing with them: an `ls_*` group is a `LampString`, not a `Lamp`,
and `Lamp::set` on one wrote through the wrong layout (on Wonka,
`lp_gobstopper` beside `ls_golden_tickets` stayed dark for the whole mode,
while `lp_gobstopper` with `lp_gi_tv` both blinked ffd700 at 2 a second). A
group now goes through `LampString::on` / `LampString::transparent` (exported
on every title that can run modes whose binary was at hand: Wonka, Dialed In,
Hobbit, Toy Story); a game without them drops the group with a log line. And
the rig booted the old restore of an ISO written again under the same name (the
Build overwrites `<title>.modes.iso`): `mount.sh` restores it again when the
ISO is newer than its cached root.

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

## Start rules (PAD-1354)

A mode can start on a game event (`start_on`: ball start, first / last ball, valid
playfield, ball saved, extra ball, multiball end), when a game mode ends
(`start_after`), at a score (`start_score`) or on a combo (`start_combo`), with
`start_once` and `start_count_reset` to limit it. The events come from the game's
own `Hook<...>::list` globals: one node of ours at the tail of each list, our fn
returning 0. A rule only raises the start; it is done on the game's proc thread
(our nodes on `HookLampRender_`, `HookUpdate_`, `HookSwitchDispatchStart_`) once
the ball is in play and nothing the mode yields to runs. Learned on Wonka 03.03:

* The lists are walked as `node->desc->fn(arg)`, next at +0x18, sorted by prio
  (the game's own at 1, 1000, 2000); a return > 0 stops the walk.
* `HookMultiballEnd_` runs every time the ball count settles
  (`MultiballDevice::system_stabilize_proc`), one ball or not, so the runtime takes
  it as a multiball's end only after a multiball.
* `HookFirstBall_` is each player's first ball. `HookLastBall_` carries no game
  callback on Wonka but the game does run it before the last ball; the balls-left
  count (`game_flow_get_balls_left_player_up`, 2, 1, 0) backs it up.
* The score hook fires inside our own scoring, so the runtime's lock is recursive.

Proof and per-title table: `tools/jjp_emu/MODES.md`, "Start rules from the game's
hook lists".

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
