# Stern's November 2026 Spike 2 builds, and node board firmware 1.42 (PAD-1555)

David, 2026-11-24: *"The last days, Stern updated a lot of spike 2 games, like king kong, with nodeboard update 1.42,
does that impact pad? Check new sd-card images from Stern's website. Download ones we don't have and analyze
differences."*

## What Stern published (sternpinball.com/support/sd-cards/, 2026-11-24)

The code-watch skill's Stern source found 14 images newer than `D:\Pinball\images\Stern`:

| Build | Held before | Kind |
|---|---|---|
| King Kong LE 1.01 / Pro 1.01 | LE 1.00, Pro 0.97 | Spike 2 |
| Avengers: Infinity Quest LE / Pro 1.12 | 1.10 | Spike 2 |
| Foo Fighters LE / Pro 1.05 | 1.04 | Spike 2 |
| Dungeons & Dragons LE / Pro 1.11 | 1.10 | Spike 2 |
| Metallica Remastered 1.05 | 1.04 | Spike 2 |
| Pokemon LE 0.87, Star Wars 2025 LE / Pro 0.98, Transformers LE 0.98, Walking Dead Remastered LE 0.94 | older | Spike 3 (LUKS) |

The nine Spike 2 zips are in `D:\Pinball\incoming\PAD-1555` (each is a Zip64 wrapper around the `.raw`: Windows
`tar` skips the 15 GB member silently, Python's zipfile extracts it).

## Node board firmware 1.42: what it means for PAD

- **It is not new to the library.** King Kong LE 1.00 (Nov 17, already in the library) carried the ten
  `*-1_42_0.hex` node images too; its release notes say "Updated to nodeboard firmware/protocol v1.42.0" under 1.00.
  1.01 is a rules hotfix ("Holiday Hotfix", Nov 24): system "Remains on V4.41.0 on OS: V2.7.0".
- **PAD never flashes or ships node firmware.** The `.hex` files are the game's own (encrypted per build: the same
  1.42 file has a different md5 on 1.00 and 1.01). The emulator's node boards (`hwshim.c` `nb_fw_title`) take the
  version they claim from the `.hex` file name on the card, so a 1.42 card is answered as 1.42 without a change;
  the per-board identity (`nb_idents[]`, `node_ident.txt`) is what would need a change if a build brought a new
  board type, which 1.42 does not on King Kong (the same ten node images as 1.00).
- **Card layout is unchanged**: King Kong LE 1.00 vs 1.01 have the same partition table, a byte-identical OS
  partition (`/etc/version` 202209050216), and 33 of 1345 games-partition files differ (the game program, the
  `image.bin` asset container, the per-build node images, the release notes, `conagent`, the `.sidx` index).

## What does change for PAD: every new build is a new game program

Mode support is per game BUILD (`<game>-<version>` keys). For a build with no shipped port the app derives one on
the card's first read (`port_derive.ensure_port`, about 3 minutes), marked NOT RUN; the Modes tab then says the app
worked the build out itself, **Write leaves modes off the card until "Check this game" has run on that PC**, and every
proven-set part (lights, screen, clip, stack, multiball, ball save, coils, place, done, with, shaker) is greyed with
"has not yet seen ... in the emulator". King Kong LE 0.97's shipped port greys 5 parts (hardware the game lacks);
the derived King Kong LE 1.01 port greys 18. The derived port itself is close: same 55 shots, 109 lamps, 119 cabinet
lamps and 6 events as the 0.97 port.

## Plan (each step proven on the emulator, rig sweeps through rigbatch.sh)

1. Analysis of all nine against their predecessors (program, node images, OS, release-note headline).
2. Extract and Write on each new card through the app's own pipelines (headless, `C:\tmp\PAD-1555\xw.py`), with a
   replaced sound and picture read back.
3. Boot + game start on the rig for each new card (`startcheck.sh`).
4. Ship a port per build: derived, merged with the same title's proven port, `gamecheck.sh play full`, recipe.
5. Join each build to the proven sets it can, with an emulator proof per set, and to TITLE_SCENES / editions /
   music where the predecessor was.
6. Library: the new cards into `D:\Pinball\images\Stern\spike2`, the replaced builds into `older versions`.

## Status

### Run 1 (2026-11-24)

**The nine builds against the ones they replace** (`C:	mp\PAD-1555nalyze.py` over each card's `<title>/game`,
`*.hex` names and `data/*release_notes.txt`; only King Kong carries release notes on the card, and Stern's site
loads its notes by script, so the others' change lists are not readable here):

| Build | Replaces | Node firmware | Node board images | Game program |
|---|---|---|---|---|
| King Kong LE 1.01 | 1.00 | 1.42 -> 1.42 | same 17 | +19 KB ("Holiday Hotfix", Nov 24: T-Rex gate, climb fixes, 7 Instant Info pages; System V4.41.0, OS V2.7.0) |
| King Kong Pro 1.01 | 0.97 | 1.33 -> 1.42 | same 17 | -18 KB |
| Avengers LE / Pro 1.12 | 1.10 | 1.33 -> 1.42 | same 17 | -207 / -228 KB |
| Foo Fighters LE / Pro 1.05 | 1.04 | 1.33 -> 1.42 | same 17 | +397 / +367 KB |
| D&D LE / Pro 1.11 | 1.10 | 1.37 -> 1.41 | same 17 | +7 / +18 KB |
| Metallica Remastered 1.05 | 1.04 | 1.33 -> 1.42 | same 17 | +15 KB |

So the node-board move is 1.33 (or 1.37) to 1.41/1.42 with no new board type. **Proven on the emulator: every
new build re-derived its node identity from its own node directory ("N boards derived from <title>'s own node
directory"), booted to attract and started a game** (`startcheck.sh` through rigbatch, stock cards, hidden, muted):
King Kong LE 1.01 attract 30 s / game 34 s, King Kong Pro 1.01 54/92, Avengers LE 1.12 28/31, Avengers Pro 1.12
40/44, Foo Fighters LE 1.05 40/157, Foo Fighters Pro 1.05 109/224; no node update walk, no version-mismatch alert.

**Extract and Write** (the app's own `SternExtractPipeline` / `SternWritePipeline`, headless): King Kong LE 1.01
extracted whole (2617 sounds, 6150 pictures, 469 videos, checksums); a Write with one sound and one scene picture
replaced built a 15.5 GB card in 12 min: the sound bank re-encoded and grown, the firmware's sound-record count
patch site found, 50 FINF validation records refreshed.

**Ports**: `port_derive.ensure_port` derives every one of the nine with nothing missing (`C:	mp\PAD-1555\derive`);
each greys the same 18 parts until proven. `tools/spike2_emu/modes/newbuild/checkjob.sh` is the Modes tab's Check
this game as a rigbatch job (the first piece of the new-build kit).

**Library**: the nine new cards are in `D:\Pinball\images\Stern\spike2`, the ten builds they replace (King Kong LE
0.97 and 1.00 both) in `older versions`; the card store holds the nine (`cardstore.ps1 fill`). Non-library cards get
only 25 GB of the store (`PAD_STORE_CACHE_MAX_GB`), so a sweep of cards outside the library re-copies them off D:
for every job.

**Rig 2** still has the stale `dump/ballfeed.off` (Oct 27): every batch parks it (`riglock.sh use 2 park-ballfeed`).

## Proving a new build's parts: what each proven set needs (gathered 2026-11-24)

The jobs that filled the proven sets (PAD-420's `bs_job`, `mb_job`, `lights_job`, `proof_job2`; PAD-710's
`place_job2` and `p710test.c`; PAD-747; PAD-474's `shake_job`; PAD-473's `wizgo.c`; PAD-1406's `coil_job`) lived in
`C:\tmp` and are gone. Nothing carries from a title's proven build to its next version: each key is proven again.
What each set's evidence lines say was seen (the recipe a job in `tools/spike2_emu/modes/newbuild/` re-creates):

| Set | Test mode lines | Proof |
|---|---|---|
| LAMPS_PROVEN | `light_all ff00ff solid`, a trigger | the shim's LED view (`dump/padled`) magenta on the addressed inserts during the mode only |
| MULTIBALL_PROVEN | `multiball 3 10`, `add_ball <mask> 1`, `shots <jackpots>`, `game_modes stack` | `multiball: 3 balls asked for`, a 4th ball, drains 4-3-2-1, `END (one ball left)`; tap a switch every ~1.5 s against ball search |
| BALL_SAVE_PROVEN | `ball_save 10`, `game_modes stack` | the drain served back with the mode running and scoring, a later drain `END (ball ended)`; a control run without the line ends on the first drain |
| STACK_PROVEN | `stack no` | `not started ...: one of the game's modes (<class>) is running` while a game battle runs (started through `block_start_<id>`) |
| PLACE_PROVEN | `in_place_of <id>`, `seconds 8` | `the game started its <name> (mode <id>) - this starts now in its place`, the game's STOP after, completion recorded |
| DONE_PROVEN | A: `in_place_of <id>`; B: `starts_on completed 1` | `done: player 1 completed the game's <mode>` and B's start |
| WITH_PROVEN | `starts_on with_game <id>` | `follow: ... started` / `START (the game's <name> started)` / `END (the game's <name> stopped)` |
| SHAKER_PROVEN | `shake start/shot/end` | `PAD_COIL_PROBE=1` `[coildrive]` pulses paired with the runtime's `shaker:` lines |
| WIZARDS_PROVEN | `game_wizard start <name>` in two files | `game wizard N (name): the game started it`, the second file refused |
| HELD_COILS_PROVEN | `coil_hold <name> 2000` | one `[coildrive]` command at the coil's own powers, the game's OFF ~2 s on |
| MAGNET / SCOOP | `magnet 2000` / `scoop_hold 4000` | `[coildrive]` hold and release times against a no-mode control |
| TITLE_SCENES | own screen + clip | HUD/bank md5s (`scene_write.profile_for`, `video_bank.parse`), magenta in glshot frames |

Install: a stage folder with `pad_mode.so` (= `modes/sdk/prebuilt/mode.so`), `game.port`, `mode.cfg`;
`PAD_SLOT=n tryit.sh install <stage>` before `job_boot`; `tryit.sh start K` / `stop`. Clear `dump/gamecheck.on`.

### Run 2 (2026-11-24 afternoon): a shipped, proven port per new build

- **Derive fix (port_derive.merge, portgen REVISION 12):** the references were ranked same title first but not same
  MODEL first, so King Kong LE 1.01's port copied King Kong Pro 0.97's values, shots and lamps (the Pro draft placed
  more) and the game crashed 35 s into its boot (segv in the event dispatch's handler, hook_dispatch at 0x4a5a18).
  Foo Fighters LE 1.05, Avengers Pro 1.12 and D&D Pro 1.11 had taken the other model's lines too. The same model's
  port now ranks first; REVISION 12 re-derives any port a person's PC derived with the other model's lines.
- **Shipped (9 ports, `ports/` + recipes):** King Kong LE 1.00 (never had one) and 1.01, King Kong Pro 1.01, Avengers
  LE / Pro 1.12, Foo Fighters LE / Pro 1.05, D&D Pro 1.11, Metallica Remastered 1.05: each the derived port, then a
  full build check on the stock card (`newbuild/checkjob.sh`, gamecheck.sh play full: the runtime hooked the game, shots
  from their switches, a drain ended a ball, a tilted ball 2 and a ball 3), stamped by `newbuild/stamp.py` (reads the
  run as the Modes tab's Check this game does). `port_words.py` 0 problems on each.
- **D&D LE 1.11:** no drain ends a ball in the check (the ball saver serves it back, the ball stays in the shooter
  lane); the shipped D&D LE 1.10 port, proven 2026-10-07, fails the same way on the same rigs today, so it is the rig
  or the check on this title, not the port. Fresh NVRAM changed nothing (1.10 and 1.11 both failed again; the slots'
  October NVRAM is back in place). Next: find what broke D&D LE's drain on the rig after PAD-713 (2026-10-24, the
  dragon hold fill; `git log -- tools/spike2_emu/ballmodel.py plunge.py modes/gamecheck.sh`), prove 1.10 passes again,
  then check, stamp and ship 1.11 (its derived port: `C:/tmp/PAD-1555/ports2/dungeons_and_dragons_le-1.11.port`).
- **Left (step 5):** the proven sets (lights, screen/clip, ball save, multiball, stack, place, done, with, shaker,
  wizards, held coils, magnet/scoop, title scenes) for every new build, each with its own rig proof, and the feature
  lines the predecessors carry (light-show passes, wizard objects, challenge sites, scoop/coil sites). Until then the
  Modes tab greys those parts on the new builds, but Write puts modes on their cards.
- Do not edit a job script while a sweep runs it (bash reads it as it goes: three jobs died "without a verdict").

### Run 3 (2026-11-24 evening): D&D LE, the rig's dragon, whole game on the new builds

- **D&D LE on the rig (the cause of every "no drain ended a ball", 1.10's shipped port too, and PAD-1400's unproven
  D&D LE):** `ballmodel.in_play` counted balls in play as the trough's six minus trough, lane and locked balls, but
  D&D LE's dragon balls are installed ON TOP of the six (ballfeed's PAD_BALL_EXTRA complement): ball 1 out read
  6 - 5 - 4 < 0 and every drain was refused "the ball is still in the shooter lane". `ballmodel.complement()` gives the
  title's complement; plunge.py's drain, ballfeed's way home and the playfield window's in-play line / Drain button
  count it. And gamecheck.sh pressed DRAGON HOLD 1-4 / STACK as playfield switches (the game read a jam and kicked the
  dragon): skipped now. D&D LE 1.11 and 1.10 pass the full check (`newbuild/checkjob.sh`), 1.11 ships.
- **Whole game (PAD-1400) on the new builds:** a derived port copied `value own_ret_scanned 1` from its references and
  dropped the `own_pass_*` list, so a whole-game mode would refuse EVERY award screen / light show caller, the ones that
  crash on a null among them (TMNT Pro's). `plugins/stern/ret_use.py` (PAD-1400's lost scan_ret_use.py, rebuilt: every
  caller that uses r0 after the call as a base, a store, an argument or a return, null-checked ones excepted; never
  misses a PAD-1400 caller that really uses it, lists some extra) now runs in every derivation, and the two values are
  never copied (portgen REVISION 13). The ten new ports carry their own lists; switch_spawn stays only where the same
  model's earlier port had it (Metallica). `newbuild/ownjob.sh`: a whole-game mode through three balls - all ten new
  builds pass (no crash, the game's shows and award screens refused), and so does D&D LE 1.10 (PAD-1400 could not).
- **Left (next run): the predecessors' feature lines on the new ports.** These tests are red because the new ports are
  now the latest builds and lack what latest builds carry (40 cases, every one a new port):
  test_spike2_mode_clip_back (surface seek/length/position; reel tick), test_stern_game_rules (rule lines whole),
  test_pad645_attract_every_build (switch_hit sites), test_stern_mode_shaker, test_stern_mode_magnet_part,
  test_stern_mode_game_shows, test_spike2_mode_backdrop_v2, test_pr18_stock_shot_bits, test_pad826_spare_io,
  test_pad782_attract_items, test_pad1478_serve_every_title (x2), test_pad1449_start_menu_styles, test_pad1406_flippers,
  test_pad1202_coop_up_call, test_pad1022_idle_pause. Each names a feature block the predecessor port has; carry it
  (re-placed in the new program: the derived port's sites where it has them, port_tool / the feature's own reader
  otherwise), prove it the way that feature's proven set was proven, then add the build to the set.

### Run 4 (2026-11-24 night): the earlier builds' features on the new ports

- **Correction to run 2:** King Kong LE 1.01's crash 35 s into boot (segv in an event handler under hook_dispatch) is
  INTERMITTENT, not the Pro's lines: the Pro-values port, the committed port and the current one passed 5 of 5 in a row,
  and 12 of 12 more boots (6 stock, 6 with the object) were clean; it showed only under a busy rig (4 of ~30 boots).
  PAD-1400 saw the same kind on King Kong Pro 0.97 (a corrupt listener in a broadcast loop, one in seven). The
  same-model ranking stays right on its own.
- **King Kong LE's transfer** used the 1.00 program as the 0.97 reference (prog/king_kong_le-1.01-OLD is 1.00); with the
  real 0.97 program (`prog/king_kong_le-0.97`, sha1 = the port's) it agrees 100% with the proven port, as every other
  build's does.
- **A derive leak, fixed (portgen REVISION 14):** values the primary reference lacks were copied from ANY other title
  whose name was not on the title-value list - the new ports carried Jurassic Park's raptor post, X-Men's sentinel and
  Cerebro, Godzilla's Ebirah, Guardians' timers_paused / kickbacks, Munsters Pro's stock_shot_bits, other titles' coil
  devices and message numbers. Another title's value is now the framework's only when two titles or more name it and
  every other-title reference agrees. The ten ports were cleaned the same way (220-ish values each); start-menu lines
  (comp_menu_*, serve_music) only where the earlier build has a start menu (King Kong, Metallica); other titles' NOT
  PLACED notes taken out (newbuild/carry.py --prune-only).
- **Stern's November 2026 builds changed two framework pieces** (not D&D 1.11):
  - the video player: surface_seek / duration / position at -0x1b8 / -0x1788 / -0xa4c from surface_play
    (set_video - play = 0x2168), proven by their GStreamer calls (duration, position) and on the emulator: a mode's
    clip came back after the game's at 13646 of 28766 ms and played at 14479 a second on (Foo Fighters LE 1.05,
    newbuild/clipjob.sh with modes/sdk/clipback_test_mode.c); King Kong LE read 8033 ms into a 14000 ms clip;
  - node boards with sixteen coils: the coil frame / off wrappers test `cmp rN, #15` (spare_io.py's FRAME16 / OFF16;
    a mode still drives outputs 0-8 only).
- **Light shows:** all twelve of each earlier build's shows, at the same numbers (a mode names them), from the port,
  port_tool's transfer and `newbuild/showmatch.py` (whole-body match, the tables' filled places as tie-break); all three
  agree wherever two place one. King Kong's 8-10 came from showmatch only (8/9 told apart by their tables: red and blue).
- **Kit (tools/spike2_emu/modes/newbuild/):** checkjob, ownjob, clipjob(2), shakejob, magnetjob, showjob (rigbatch
  jobs), stamp.py, carry.py, showmatch.py, scan_ret_use.py. Coil proofs read `[coildrive]` from dump/game.out.
- **Left:** per-build proofs and set entries for lights, screen / clip / TITLE_SCENES, ball save, multiball, stack,
  place, done, with, wizards (wizard_obj lines), scoop (scoop_handler / slot), held coils (coil_take / give / off),
  challenges (Avengers, Foo Fighters, Metallica: challenge_menu lines). Their recipes are in "Proving a new build's
  parts" above.
- **Operator adjustments were renumbered** in the November builds (SHAKER MOTOR: Avengers 355 -> 357, King Kong
  347 -> 357, D&D 165/164 -> 163/162): every port value that names an adjustment by number must be read off the build
  (`shake_adj` re-read by shaker_lines.py in all ten). Also still to do: the modules that list builds by key and know
  their adjustments / menus / sounds / scenes (menu_settings.py, sound_modes.py, scene_write.py, mode_project.py's
  title lists) - the new builds are not in them yet, each to be read off the build, never copied.

### Run 5 (2026-11-24 night): mini-wizards, scoop, the stack's typeinfo

- **Mini-wizards** on all ten: each `wizard_obj_<n>` placed in the new program by the method its title allows, each
  method first checked to give the earlier build's own address - `newbuild/objfind.py` (class name -> typeinfo ->
  vtable -> its constructor -> the object; King Kong's two T-Rex battles, Avengers' three), the game-mode block of
  the same name (Crash the Gate, Soul Gem, Battle Royale, Tiny's Dice Game), the mode table's index (Foo Fighters,
  D&D: every known mode keeps its index), `newbuild/globals.py` (neighbours' shift); where two methods place one they
  agree. `newbuild/wizjob.sh`: wizard 1 started, wizard 2 held while it ran - all ten (and Avengers LE 1.10 as the
  control); WIZARDS_PROVEN.
- **Scoop**: `scoop_handler` by a masked run of the earlier code, unique in both programs (it found Avengers LE 1.12's
  existing site exactly; D&D's and Metallica's agree with the whole-body match), `scoop_slot` by globals.py: King Kong
  x3, D&D x2, Metallica. Not yet proven (SCOOP_PROVEN: the scoop_hold job).
- **Stack** on King Kong / Avengers: `typeinfo_cmode_mball` and `typeinfo_vmi` by class name (GamePlayModes /
  ConnectivityObjectives, the earlier builds' own). Not yet proven (STACK_PROVEN: the stack job).
- **Challenges** (Avengers, Foo Fighters, Metallica): portchallenge.find reads none of the new builds' start menus
  ("the build names no challenge") though the flag names read - the menu code changed too (and Avengers 1.12 has a new
  FG_PLAYER_SOUL_GEM_CHALLENGE_ACTIVE). Its menu readers need the new shape.
- **Next, per build, the proofs still owed:** lights (LAMPS_PROVEN: every named insert magenta off the node bus,
  leddecode.py), ball save, multiball, stack, scoop, place, done, with, held coils, button shots, spare I/O, title
  scenes; then challenges, then the key-listed modules (menu_settings / sound_modes / scene_write).

### Run 6 (2026-11-24 night): ball save, multiball, place / done / with / stack, held coils

- **Kit:** `newbuild/bsjob.sh` (ball save), `mbjob.sh` (multiball), `gmjob.sh` (stack, place + done, with, in one game:
  `modes/sdk/gamemode_test_mode.c` makes the game start / stop its own mode, `pm_game_mode_start/stop`), `coiljob.sh`
  (every held coil: HOLD and one command on its board address in the slot's gzwatch.log). rigbatch list lines take
  several variables space-separated in the third field (`key|card|ID=27 SO=...`), never `|`-separated.
- **Proven:** multiball 10/10 (3 served, add-a-ball to 4, END one ball left); place 10/10 and done 10/10 (each title's
  mode from the earlier proof: King Kombos 27, Super Reactor 19, Super Skill Shot 8, Mimic Hurry Up 12, Map Choosen
  Ritual Singleball 53, Battery 0); with 9/10 (Metallica's plain-C Battery: its own clock, re-run with a longer wait);
  ball save 8/10 (D&D LE, Metallica: a second ball is out after the save - the job now drains every ball out); stack
  3/10 (King Kong; a `stack no` mode waits only for battles / multiballs: re-run on Soul Gem 8, Super Skill Shot 8,
  Mimic Hurry Up 12, stack phase first); held coils on D&D LE / Pro.
- **Another framework change:** the coil record grew from 0x68 to 0x70 bytes on the King Kong, Avengers, Foo Fighters
  and Metallica builds (D&D 1.11 kept 0x68; the request function's fields up to +0x25 unchanged, its tail moved +6), so
  a held coil found no record ("no one coil of the game's is node 9 coil 0") and the spare outputs read the wrong
  records. The runtime's COIL_REC_SIZE is the port's `value coil_rec_size` (default 0x68), each port's own read off
  its coil_count code (x*7*16); prebuilt mode.so / mode64.so rebuilt. King Kong's coil_give placed (masked code run).
- **Run 6 results:** multiball 10/10, place 10/10, done 10/10, with 10/10 (Metallica: Battery started with it and
  ended with the ball), ball save 9/10 (Metallica once every ball out drained; 1.04 the same), stack 9/9 that the
  earlier builds had (King Kong x3 on King Kombos 27, Avengers on Soul Gem 8, D&D on Mimic Hurry Up 12, Foo Fighters on
  Super Skill Shot 8 - with the ball scored first: until the score moves, a game mode that starts is base play,
  `stock_base_until`), held coils on every new build but King Kong LE 1.00 (Avengers / Foo Fighters / Metallica once
  the runtime read the 0x70 record; King Kong by the earlier proof's command profiles, `EXPECT=`).
- **Left from these sets:** D&D LE 1.11 ball save (after the save the game keeps a second ball out and every drain
  is "ball passing" - try D&D LE 1.10 in the same job first); King Kong LE 1.00's held coils (its ControlCoil commands
  go out with their fields shifted - "pulse 3/255 for 0 ms, hold 30" - while 1.01's are right: compare the two builds'
  take paths).

### Run 7 (2026-11-24 night): scoop, spare I/O, the start menus, Prolonged Competition, lights

- **Scoop:** D&D LE / Pro 1.11 held (4000 ms, let go 4008 ms, the game's kick node 8 coil 8). King Kong, Avengers LE
  1.12 and Metallica 1.05 held no ball at first: their ports had D&D's `scoop_event_arg 1` (D&D and Venom name it, so
  REVISION 14's "two titles agree" took it as the framework's), and their handlers take the event in the FIRST
  argument. scoop_event / scoop_event_arg are title values now (portgen REVISION 15); without it all five held
  (4005-4015 ms; Metallica 1.04 the control). `newbuild/scoopjob.sh`.
- **The two-titles rule** needs only one other title where the references hold only one (Batman derived off Godzilla
  alone had lost the framework's event list - test_spike2_switch_drain).
- **Spare I/O:** 11/11 with the Avengers LE 1.10 control (`newbuild/sparejob.sh`): the spare input closed through
  /dump/spare_in came as the instrument's pulse, output 1:1 went out as node 1 coil 1 200/30 ms.
- **The start menus:** Avengers 1.12 and Foo Fighters 1.05 no longer have the challenge_menu loop (no masked match;
  the button tests are gone from the menu code); both are menus of game-mode table indices now, like King Kong's and
  Metallica's, through the GamePlayModes adapter. Its reader learned two layouts: Foo Fighters 1.05 keeps the table
  40 bytes into the object its accessors load (the flag field says where entries start), Avengers 1.12 keeps a colour
  pair at +6 and its messages one field on (STANDARD lettered at +8). The four ports carry `frame_lines`.
- **Message ids moved:** every November build has one message more before the start menu's (1914 FLIPPERS TO
  CHANGE/START SELECTS), so STANDARD is 1915, NORMAL PLAY 1916, ALL RANDOMNESS REMOVED 1921, BALL %d 1256. King Kong's
  three and Metallica 1.05's menu values and four ports' coop_ball_msg had their earlier builds' (the runtime checks
  coop_ball_msg's words and searches, so no co-op line was wrong on a machine); all read off each build now.
- **Prolonged Competition** (`newbuild/compjob.sh` + `compcfg.py`, rigbatch --speed 1; the menu opens with both
  flipper BUTTONS held in attract - "LEFT FLIPPER" first matched UP LEFT FLIPPER EOS; one left step wraps onto our
  last entry): the whole pick on Avengers LE / Pro 1.12, Foo Fighters LE / Pro 1.05, King Kong Pro 1.01 and Metallica
  1.05 - the entry appended, picked, START, `ON until the machine is switched off - game 1 plays as Competition`.
  King Kong LE 1.00 / 1.01 show and pick the entry but START starts nothing, and the King Kong LE 0.97 control (proven
  in PAD-1041 round 2) does the same in this job: the job's, on that title's menu - a shot after START is queued.
- **D&D LE 1.11 ball save** passed in a rerun (bs6, with the 1.10 control): the earlier runs' missing END was theirs.
- **King Kong LE 1.00 held coils:** the right device and coil (spider magnet device 10 at 9:0), the vtables the same as
  1.01's, but each object reads "pulse 3 for 0 ms, hold 30" and the game takes each coil back within 11-16 ms (its
  on-time word +36 set): the game drives those coils itself at that moment on 1.00. Left: hold later in the ball.
- **Prolonged Competition, all eight offered new builds proven** (King Kong LE 1.00 / 1.01 too, and the 0.97 control):
  King Kong LE on the rig is not on free play - "ADD CREDITS 1/1.00 3/2.00": its menu shows our entry, lettered
  COMPETITION / UNTIL POWERED OFF, but START takes nothing without credits, even the game's own STANDARD (STD=1
  control); the job drops coins first (plunge.py coin 4).
- **Lights 10/10 but Avengers LE 1.12** (`newbuild/lightsjob.sh`, `lightcheck.py`, the LED view): King Kong x3, Avengers
  Pro, Metallica, D&D x2, Foo Fighters LE / Pro. Foo Fighters Pro 1.05's RGB OVERLORD had no lamp line: the derive's
  lamp_draft placed lines by name through a map that kept the LAST insert of a name, so the single OVERLORD (lamp 76)
  stood in for the RGB one (lamp 46) twice - REVISION 16, each line takes the one of its kind not taken yet. Avengers
  LE 1.12's LEFT ORBIT / LEFT RAMP / POPS GEM read white in the LED view before and during (green after): the SWELF
  bulk frames it misses - judge it on the node bus (PAD_NB_TRACE, the wide decoder) as Avengers 1.10 was.
- **The serve music moved too** (`newbuild/servejob.sh`: PAD_SOUNDLOG=1 + /dump/soundlog.on, a stock game's requests):
  King Kong 0.97 asks 192, 124, 720, 352 ...; LE 1.00 / 1.01 and Pro 1.01 ask 194, 125, 74x, 354 - serve_music 125.
  Metallica 1.04's 65 never shows in that job (143, 80, 148, 90): its music comes another way - Metallica 1.05's 65
  is unverified. Avengers 1.12 and Foo Fighters 1.05 (menus now) need theirs: mark the serve (the ball start's event,
  or the style hold's co-op run) and read the request after it - test_pad1478 is red on those two until then.
- **Left for run 8:** serve_music for Avengers LE / Pro 1.12 and Foo Fighters LE / Pro 1.05 (and Metallica's check);
  Avengers LE 1.12's lights on the bus; King Kong LE 1.00's held coils (a hold later in the ball); the challenge
  list on the new index menus (challenge_menu_frame, as Godzilla 1.16 / Pokemon 0.87); title scenes; button shots;
  the build-keyed modules (menu_settings, sound_modes, scene_write) for the new builds; merge main before release
  (three tests red at the branch's base are green there).

### Run 8 (2026-11-24 late): serve music, Avengers LE lights, screens and clips, King Kong's holds

- **Serve music** at the bus's ball_start (`servejob.sh SO=census.so`: census_mode logs game_start / ball_start
  beside the sound log): King Kong 1.0x 125 (19 ms before the event), Foo Fighters 1.05 74, Avengers 1.12 468,
  Metallica 1.05 87 (Metallica picks among its songs there: 1.04 asked 80 in one game, 87 in another - never the
  port's 65).
- **Avengers LE 1.12 lights:** our layer is on top (255) and 22/25 RGB went magenta; LEFT ORBIT, LEFT RAMP and POPS
  GEM stay the game's own (white before and through, green after) - 1.12 sets them past the layers; the 1.10 control
  held all 25. LAMPS_PROVEN with the note, as Deadpool LE's arrows.
- **Screens and clips, all ten** (`mediabuild.py` builds the Modes tab's Try it set: a magenta screen and a 4 s
  magenta title clip; `mediajob.sh` boots it; `mediacheck.py`: clip >= 50%, screen 1-50%, before / after < 0.5%):
  clips 55-95%, screens 8.9%, 0.0% before and after. King Kong's and Metallica 1.05's HUDs are their earlier
  builds' profiled shape edited in place (scene_write.SAME_SHAPE); Avengers 1.12 / D&D 1.11 / Foo Fighters 1.05's
  HUDs are the earlier files. D&D's PLAYER 1 SELECT A CHARACTER stays until the ball makes a switch (PICK=1).
- **Ports' example start shots:** Foo Fighters LE 1.05 kept 1.04's switch shot, Avengers 1.10 / 1.12 named a Right
  bullseye no shot is - a Try it on it was refused for the card. Each is one of its own now (test).
- **King Kong's held coils never held:** the November ControlCoil object's words sit one word earlier (dumped at a
  hold's start: 0.97 +0x24 0, +0x28 1, +0x2c our process; 1.01 +0x20 0, +0x24 1, +0x28 our process), so the runtime's
  on-time read (+36) saw the 1 and let every hold go 13 ms in - run 6's proofs saw only the command. `value
  ccoil_ontime_at 32` on the three; every hold ran its 2000 ms (LE 1.00 twice, LE 1.01, Pro 1.01); coiljob.sh fails a
  hold let go within 500 ms.
- **Left for run 9:**
  - Challenges on Metallica 1.05 (its list read, proof missing), Avengers 1.12 and Foo Fighters 1.05 (their menus are
    index menus now: the challenge list needs challenge_menu_frame's values, as Godzilla 1.16 / Pokemon 0.87). The
    PAD-619 proof set the game's DEFAULT GAME MODE live (ch615.c, gone from C:/tmp): re-make it or pick the
    challenge on the start menu.
  - Metallica 1.05's stack: `stjob.sh` (our multiball ended by its clock, balls out, then `stack no`) starts the
    stack mode on 1.05 AND the 1.04 control - the runtime counts only the game's own multiball: start the game's
    own multiball (Blackened) instead, as WIZARDS_PROVEN's Metallica 1.04 line did.
  - Merge main before release (three tests red at the branch's base are green there).

### Run 9 (2026-11-24 late): challenges and Metallica's stack

- **Metallica 1.05's challenges** (`chal2job.sh` + `modes/sdk/gpmset_mode.c`, PAD-619's `gpm set` re-made: the
  GamePlayModes singleton's current index set to Lux Aeterna Combo (8) in attract, as the menu's pick sets it): challenge
  0 claimed, `CH TEST START (challenge pick)`; the 1.04 control the same. CHALLENGE_PROVEN.
- **Avengers 1.12 / Foo Fighters 1.05** (index menus now): a plain MODE CHALLENGE (`challenge_menu_frame` on the comp
  frame, as Pokemon 0.87's) - and the derive had dropped the challenge game's own calls and flag (challenge_balls,
  _extra_ball, _end_ball, challenge_on_flag 18; placed by a masked match of the earlier build's, one match each).
  `chaljob.sh`: appended (entry 5 of 5 / 9 of 9), lettered CHALLENGE / PAD CHALLENGE, picked, START (challenge pick).
  CHALLENGE_MENU_FRAME_PROVEN.
- **Metallica 1.05's stack** (`stjob.sh WIZ=1`): our own multiball's balls are never the game's ("ours is over (1 ball
  in play) - two or more are the game's again"), so the game's own Blackened Multiball was handed over; `stack no`
  refused ("a multiball is running") through 5 drains, started at the 6th; 1.04 the same. STACK_BALLS_PROVEN.
- **Left for run 10 - the latest-build sets the new builds are not in yet** (each game's latest build carries them):
  BUTTON_SHOTS_PROVEN (9: PAD-1403's method), menu_settings.PROVEN (MUSIC MODE / EDITION rows, PAD-724's sweep),
  sound_modes.PROVEN and TURN_PROVEN (PAD-494 / PAD-565 sweeps), STACK_RECORDS_PROVEN and SWITCH_EDGE_PROVEN
  (Metallica 1.05), BANK_SONG_NO_ROOM (D&D 1.11: image.bin + its biggest music bank against MAPPED_MAX); the cstarts
  finder's Metallica list (find_c_starts.py names 1.04 only).

### Run 10 (2026-11-24 late): the latest-build sets

- **Button shots, ten builds** (`btnjob.sh`, each card's own buttons.cfg from its Try it set): none in attract; every
  line's shot once at its own action - 9 of 9 on King Kong, 18 of 18 on the rest. BUTTON_SHOTS_PROVEN.
- **Metallica 1.05's switch edges** (`checkjob.sh` + `edgecheck.py`): 35 of 49 switches one shot a press on a bit of
  its own, the same 14 none - 1.04 identical. SWITCH_EDGE_PROVEN.
- **D&D 1.11's bank room:** the same image.bin (2,142,352,388) and image-sc01.bin (39,598,976) as 1.10 - no room for a
  bank song of a mode file's. BANK_SONG_NO_ROOM.
- **Metallica 1.05's live records:** the derive had dropped `mode_records_1..5`; its song starts create 178 / 183 /
  188 / 193 where 1.04's create 177 / 182 / 187 / 192, so each range is 1.04's + 1 (the runtime now says it can tell the
  timed modes from the live records). The rig proof (`recjob.sh`: `stack no` refused while Enter Sandman runs) is held
  up by the second ball Metallica keeps out early.
- **Left for run 11:** STACK_RECORDS_PROVEN for Metallica 1.05 (recjob.sh); the two sound sweeps - sounds in turn
  (sound_modes.TURN_PROVEN) and MUSIC MODE / EDITION (menu_settings.PROVEN = sound_modes.PROVEN) on the nine latest
  builds. Both kits are gone (C:/tmp/PAD-724, the PAD-565 sweep): a set built by engine.write_overrides on a project
  whose `.staged_changes.json` replaces a short one-request sound with a 500 Hz tone, `sound_modes` `turns` (1000 /
  2000 Hz files) or `slots` + `editions`; the request fired by sound_fire_mode.c (`sound.fire`); $DUMP/audio.raw
  (s16le 48 kHz stereo) cut after each fire and measured by a Goertzel at 500 / 1000 / 2000 Hz
  (tools/jjp_emu/jjpaudiocap.py:31); MUSIC MODE / EDITION set to 2 by the operator-menu walk (menu_settings.menu_path)
  or an NVM write (codeselect/nvm.c's crc32), read back from /data/nv/<title>/NVM.
