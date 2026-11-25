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
