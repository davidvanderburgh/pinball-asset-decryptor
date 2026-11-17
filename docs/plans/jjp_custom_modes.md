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

## A mode's own sounds, music, picture and video (PAD-1352)

How to use it: `tools/jjp_emu/MODES.md`. What was learned on Wonka 03.03 (decrypted
code read through `/proc/<pid>/mem`), and why it is built this way:

* **The game's file manager cannot take a file of ours.** Every asset load goes
  through one loader (`fm_load_file_blob` -> an unexported core) that XORs the
  whole file with a keystream seeded from its absolute path
  (`jcrypt_set_seeds_for_crypto`), drops the lead filler and checks a CRC32
  against the dongle-encrypted file list. So nothing of ours is loaded through
  `SoundEffect::do_fileload`, `JJPESprite` or `JJPEMovie`; the runtime loads its
  files with the same Allegro and FFmpeg the game links.
* **Sounds: a copy of a game `SoundEffect` with our sample.** A `SoundEffect` (264
  bytes on all eight titles) keeps its `ALLEGRO_SAMPLE*` (+0x58 on Wonka), its
  channel `se_type_t` (+0x18: 1 music (OGG, streamed), 2 fanfare, 3/4 speech, 5 fx,
  6 loops), a loaded byte (+0xd8), a stream flag (+0xf0) and flags (+0x54, bit 2
  "loaded on demand"). `create_sample_instances` makes its voices from the sample
  and attaches them to the mixer of the channel object in a table indexed by the
  type; `do_play` picks a free voice and applies the object's play mode and gain.
  The runtime copies a resting, resident game sound of the wanted channel, puts
  our sample in, clears the stream flag and calls `create_sample_instances`, so
  the game's own `play` plays it on that channel. The field offsets are read off
  the game's code each run (the `mov disp(%rbx),%rdi` before the call that reaches
  `al_create_sample_instance` through the PLT; the `movslq disp(%rbx),%rax` that
  indexes the channel table; `do_play`'s first tests; the `cmpb` whose branch calls
  `play_audio_stream`), never assumed.
* **Music: the game's music list.** `update_music()` walks
  `Update<UpdateBGMusic_>::list` (head `{first, magic 0x45}`, node `{prio, desc,
  -, next}`, desc `{fn, name}`); the first rule returning nonzero names a music
  function, and `music_request(fn)` stops the music channel
  (`JJPSoundChannel::kill_all_sounds`) and calls it; the game's music functions
  are one `se_X.play()`. Our node heads the list and answers only while a mode
  with music runs unpaused; the runtime calls `update_music()` at mode start, at
  its end (our `end` slot) and when a pause starts or ends.
* **Video: the game's FFmpeg 4.4** (libavformat 58, libavcodec 58 with libvpx
  VP8/VP9 and H.264, on all eight titles), decoded on a thread of ours, converted
  to RGBA by our own BT.601 loop, uploaded with `al_lock_bitmap` on the render
  thread. No FFmpeg headers: the few struct fields read have been stable since
  FFmpeg 3.4, and the stream's codec parameters are found by their content.
* **Muted audio proof.** `audio.sh` with `JJP_AUDIO_CAPTURE` wraps the null
  device in ALSA's file plugin; `jjpaudiocap.py` reads it from a FIFO at real time
  (the null device alone is unpaced: 178 MB in two minutes) and logs tone levels.

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

## Write to USB stick in the app (PAD-1375)

The Modes tab's **Write to USB stick** card writes the PAD-1349 stick
(`mkjjpmodes.py stick`) without the command line: the first removable drive (or
any folder), install / off / on / remove, and the steps at the machine (service
menu > Software Update > USB Update; hold the left flipper, Plus Minus Plus
Minus; ENTER ENTER). The stick is plain files written in-process; an install
stick's runtime comes from the new `mkjjpmodes.py runtime` (the stock ISO's
root from the root cache, mounted read-only - `LoopRW(readonly=True)`, `ro,noload`
- and `buildmods.sh` against its glibc), run as root in the app's Linux once
per ISO and kept in `jjp_modes/.runtime/`. `stick --iso` does the same from the
command line. A stick carrying someone else's hot fix is never written over.

Fixed on the way: the stick's README left out holding the left flipper, without
which the screen never asks to apply the hot fix; the Modes form lacked the
`hold_multiballs` / `allow_game_modes` keys PAD-1348 added and showed `pause`
as `game_modes`' default (it is `hold`); and the first use of an ISO (its game
partition unpacked, about 20 minutes from D:) printed nothing for the whole
restore - `build` and `runtime` now print a progress line every 2%.

Proof, 2026-11-17, Wonka 03.03 (hidden, muted): the app (in-process, real
services) with no runtime kept built it in its PAD-Runtime distro and wrote the
install stick in 1.6 s (the first ever use of the ISO there unpacked its root
first, 19 min); the off and remove sticks in 0.2 s each. On the rig, those
sticks through the game's own menu walk (`jjppoke.py`): "INSTALLED 1 mode(s):
PAD Mode", and after the reboot the runtime loaded from the installed hook and
PAD Mode STARTED on the TV target, scored 1,000,000 a shot and COMPLETED at
10,000,000; the off stick created `padmodes.off` and the next boot loaded no
runtime; the remove stick took `padmodes` out and left `rungame.sh` as shipped.

## The Wizard of Oz: a second runtime path (PAD-1365)

The Wizard of Oz 08.02 is JJP's first engine generation: no `Mode` class, so the Mode route
cannot apply. Its modes are function families run on procs (`ecmb_run_proc` /
`_grace_proc` / `_grace_grace_proc`, `twister_mode_proc_run`, `mmf_proc` +
`mmf_proc_kill_func` ...). The runtime now picks an engine at install (`pick_engine`): the
Mode objects where the class is, else **our own procs** (`JJP_MODS_ENGINE=proc` forces it, to
prove it on Wonka). How to use it and the per-piece table: `tools/jjp_emu/MODES.md`, "The
Wizard of Oz: the proc engine".

Learned on Wonka 03.03 (decrypted code read through `/proc/<pid>/mem`), and why it maps to
The Wizard of Oz:

* **`Mode::start` is three engine calls**: `h = proc_cret(run_id, Mode::start_run_func, 0)`
  (`proc_cret` is `proc_create(id, fn, flag 2, survive)`), `proc_set_arg(h, 0, this)`,
  `update_all_soon()` (it only sets a flag). A proc's function gets its handle;
  `start_run_func` reads `proc_get_arg(handle, 0)`.
* **`Mode::run_proc`**: `proc_sleep(1)` a tick, 125 (0x7d) ticks to the second, the seconds
  counted in the object, the tick hook called each tick unless it is the empty default, the
  timer held while `is_timer_paused`. **`Mode::score_and_total`** is
  `score_add_to_player_up(points, false)`, which returns what was scored.
* **The engine's procs** are a list `{proc *, next}` behind an Allegro mutex; a proc has its
  entry function at +0x1b8 and +0x1e8, id +0x1f0, handle +0x1f8, flags +0x1fc (0x10 on its way
  out, 0x20 while being made), create flag +0x200, survive +0x204. The head is not exported;
  the runtime reads it off `proc_id_exists`. A ball end runs
  `proc_kill_without_survive_flag`, so a run proc made with survive 0 dies there.
* **The engine is one library**: every name the proc engine calls is exported by both
  generations with the same mangling and the same size. The Wizard of Oz's code is
  ciphertext at rest (4,863 of its functions), so this, not its code, is the static evidence.
* **Yielding without Mode objects**: a game mode is a live proc running one of the game's
  mode functions (named for a mode, named like Mode's procs, or `<x>_proc` with its own kill
  function), counted against the procs running it two seconds into the ball. Wonka's
  `WonkaBarAwardModes::timer_run_proc` runs on to the ball's end after its mode ends, so timer
  functions are left out.
* **Hold is impossible there**: the game's mode starts are plain calls, not virtual slots, so
  nothing can gate them without patching code; `game_modes = hold` runs as `pause`.
* **The blink**: a sample of the game's composite once read one phase for 8 s on both engines;
  sampled beside our own layer in the final run, both changed 24 times in 4 s (3 a second).
  The earlier reads were the sampler, not the lamps.

Fixed on the way: `buildmods.sh` now refuses an implicit function declaration (a lost
helper built with a warning and failed only at load, `undefined symbol`); a fresh start
clears an end asked for at the last ball end.

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

## Balls and coils (PAD-1353)

Read off Wonka 03.03's decrypted code, then proven in the emulator
(`tools/jjp_emu/MODES.md` "Balls and coils"):

* **One ball saver.** Proc 0x191 keeps a target number of balls in play for a
  time in hundredths of a second (`mb_request_balls_into_play(N, T)`; a request
  above 1.99 s gets 2 s of grace). The game's own ball save is that call with the
  balls in play now; its add-a-ball is `mb_add_balls_into_play(n, n * 200)`.
  `mb_kill_ballsaver()` ends it, `mb_get_ballsaver_time()` counts it down in the
  game's time (slower than the wall on the hidden rig, so the runtime compares the
  saver with itself, never with the clock).
* **Coils.** A `Coil` is 88 bytes: +0x08 label, +0x10 its own pulse ms, +0x24/+0x25
  its OUT byte and bit, +0x28 state (0 off, 3 pulse, 4 duty for +0x30 ms, 2 duty with
  no end), +0x34 the rotating pattern, +0x38 its length, +0x3c the pattern as asked.
  `coil_duty(ms, pattern, 32)` is a hold the engine ends by itself;
  `coil_get_duty_pattern(n)` is n of 32 steps on. The on/off hook lists
  (`HookCoilOn_IRQ_`, `HookCoilOff_IRQ_`) are empty on Wonka and are interrupt-context
  hooks, so `coil_off` from the runtime's watchdog thread is safe.
* **The rig.** A hidden run has no ball feeder (it lives in the matrix window), so the
  proof ran `jjpball.Feeder` headless (`C:\tmp\PAD-1353\feeder.py`) and read coil drives
  off the shim's OUT frames (`coilsample.py`).
