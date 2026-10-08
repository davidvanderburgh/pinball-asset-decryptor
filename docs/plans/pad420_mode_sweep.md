# Modes on every newest Spike 2 build (PAD-420)

David, 2026-10-07: *"We now have all the latest versions and models in the spike 2 image folder. Do a sweep to
support them all for modes. Every element including lighting, mechs, shaker, etc. I don't want any yellow text for
any game."*

"Yellow text" is every "Not on this game..." / "has not yet seen..." line the Modes tab shows. Each comes from
`TitleProfile.cannot` (`mode_project.profile_from_port`): a part is offered when the build's port names what the
runtime needs AND the build is in that part's proven set (an emulator run). The scope is the NEWEST build of each of
the 53 models in `D:\Pinball\images\Stern\spike2` (older builds keep what they have).

This is several runs of work. Each run adds what it proved here.

## Done on this branch

1. **Hardware a machine does not have is left out, not yellow** (692b5199): `mode_project.MACHINE_HARDWARE` (from
   each newest build's device-table coil names) -> `TitleProfile.absent`; the form and the blocks palette hide the
   magnet / scoop / held-coil / shield / shaker sections of a machine without one.
2. **The 32 newest builds that had no shipped port now have one** (every model's newest build opens in the Modes
   tab; before, the app derived an unproven port on the card's first read, and Rush Pro 1.19's crashed the game). How each was made:
   - `port_derive` drafted each build from its framework generation's references, and `port_tool.py` drafted it
     from the same title's proven port (`transfer`); the two were merged (core sites from the build itself, shots,
     callouts, lamps and events from the same title).
   - **Other titles' features taken out**: the generation references carried other titles' FEATURE lines into the
     drafts (Godzilla's rule values, shield, building, show and hit-sound lines, King Kong's and Jaws's coil devices,
     plain-C titles' per-mode flags). Those are dropped; the framework lines stay. Title values
     (`portgen.TITLE_VALUES`: countdown, clip-surface) are the source port's or left out (620b4cdc stops a
     derivation copying them).
   - **Tried and backed out**: keeping only the names the same title's older port has. Rush 1.19, Munsters Pro 1.28
     and Aerosmith 1.16 then crashed or hung (a segfault in a lock call, the game's 10 s watchdog): Rush moved to
     the newer framework generation between 1.18 and 1.19, so its newer switch and frame lines are needed and 1.18's
     switch layout values are wrong for it. A build whose generation changed is never cut to its old port's names.
   - Aerosmith LE 1.16 carries 1.15's `lamp` lines (the same machine, the same lights; it passed with them).
   - `port_words.py`: 0 problems on all 32. Each has a current recipe.
   - **Emulator**: a full build check per build (`gamecheck.sh play <game> full`, hidden, muted, stock card): the
     runtime hooked the game, the switches gave shots, a drain ended each ball, a tilted ball and three balls to the
     game's end. The result per build is in each port's header.
3. **Each new build's HUD profile, scenes and sound carriers** (7ebbfab3, desk-measured from the cards).

## Where the 32 new ports stand (end of run 3, 2026-10-07 11:00)

- **Shipped, build check passed in the emulator (30):** every new build but two. Run 2's checks were full games
  (`play full`); run 3's re-runs on a quiet machine were the standard check (start, every playfield switch, a drain
  ending a ball). Each port's header says which. King Kong sends each shot with its X1 bit set as well, so its shots
  count by bit (35 of 55, as on King Kong LE). Star Wars LE 1.31's draft found only 4 switch shots; its switch table
  is 1.30's machine id for id, so it carries 1.30's 42 (40 came from their switches).
- **Open (2):**
  - Batman 1.14: game start and ball start fire, but after each drain a ball comes back and no end of ball ever
    comes (three tries, two ports). 1.13 had no trough eject coil (the rig served balls by hand); 1.14 has one, so
    the rig's ball feeder answers the eject. Look at the rig's drain on this title first (`padball.log`, a glshot
    after a drain), then the derived `site ball_end 0x499e0c` / event 0x34.
  - Jaws Pro 1.02: the game does start (a glshot shows PLAYER 1, credits taken), but the runtime never sees it:
    `mode.log` says in_game 0 with player 1, so `data mode_mask 0x89e53e` & `value mode_mask_busy 0x210` (copied
    from Jaws LE) stays busy. Read the mask in a running Pro game and fix the address or the busy bits.
  Their candidate ports: `C:/tmp/PAD-420/clean/<key>.port`; check logs `C:/tmp/PAD-420/check3..5/<key>`.

**Lesson for the next run:** the previous run's helper agents left jobs running in WSL after they were stopped (a
shaker proof, a ball-save pilot, a light-show scan, a mechanisms proof). They held a fourth rig, the machine feeds
three, and every check on the starved rigs died on the game's own watchdog. Before a batch: `riglock.sh list`, and
stop anything not yours; run nothing CPU-heavy (pytest, screenshots, recipes with 4 workers) while rigs run.

Tools (scratch, `C:/tmp/PAD-420`): `jobs/check_job2.sh` (the check per build), `run_check3.sh` (rigbatch),
`stamp.py <key>...` (the proof header; `CHECKDIR` names the check folder), `recipes.py` (`RW=1` for one core), `portslist.py` (the test's
port list), `limits_table.py` (MODE_LIMITS.md's games table), `clean2.py` (how a candidate port is made).

## Run 4 (2026-10-07 afternoon): ball save, lights, multiball on the new builds

Kits in `C:/tmp/PAD-420` (all rigbatch jobs, two rigs, hidden, muted, stock cards):
- `bs/` ball save: `gen.py` writes each build's test mode (`bs/<key>/mode.cfg`, `game_modes stack`) and jackpot
  switches from its own check log (switch -> the shot it made); `bs_job.sh` (item 225's job on this worktree),
  `bs_verdict.py`; `bs/rb/results.tsv`.
- `lights/` the lights proof (`light_all ff00ff` / `light_shots`, the shim's LED view): `prep.py`, `lights_job.sh`,
  `judge.py`; `lights/rb`.
- `mb/` multiball (item 167's TWIN TERROR, served 3, add-a-ball to 4, drains 4-3-2-1): `mb_job.sh`, `mb_verdict.py`;
  `mb/rb`.
- `chain.sh` runs lights then multiball after the ball-save batch. `prove_set.py <SET> <results.tsv> "<why>"` adds
  the passes to a proven set in mode_project.py with their evidence; then `limits_table.py` and the tests.
- Gotchas found: a slot that ran Check this game keeps `dump/gamecheck.on`, and the runtime then starts no mode
  (`tables.sh` clears it); a slot may have no switch table for a title yet (`tables.sh` copies the one read from
  this exact program from another slot); the C-framework titles (Guardians...) cannot hold off their own modes, so a
  test mode under the default `game_modes block` gives way and ends when one begins (`game_modes stack` in the tests).
- **Results so far.** Ball save: 22 of 30 proven (`bs/rb`); 9 re-run with the fixes (`bs/rb2`; Venom Pro with
  `NOPF=1`: pressing every switch started the game's own multiball). Lights: 19 of 30 proven (`lights/rb`). Not proven:
  Avengers LE/Pro 1.10 (2/40 RGB magenta), John Wick LE/Pro 1.02 (3/40), Mandalorian LE 1.45 (10/15), Rush LE/Pro
  1.19 (17/67), Foo Fighters Pro 1.04 (19/47), King Kong Pro 0.97 (0/9; its light_shots IS proven). The runtime
  logs every insert held at layer 255 and the port's lamp lines equal what the program says, so look at judge.py's
  one node offset per build (a board group with another offset?) and at a game layer above ours, before the port.
  `lights/judge_groups.py` (a fit per I/O group): most of those inserts sit in a group that never changes at any
  offset (Rush group 1: 96, John Wick group 1: 86, Avengers group 6: 14), likely a light string outside the
  node-bus LED view (Rush 1.18's proof left its strip out the same way), but some observable groups stay dark too
  (Avengers group 7: 2/36, Rush group 6: 4/23, Mandalorian group 6: 1/6). Look at those with a glshot of the
  playfield view and the runtime's lamp layer during the mode before calling them proven or not.
  Mandalorian Pro and Munsters Pro booted to Tech Alerts, which the lights job did not take as booted (fixed;
  `lights/rb2`). Multiball: running (`mb/rb`), the Aerosmith pair passed 3, 4, 3, 2, 1.
- **Light shows, Godzilla Pro 1.16 first** (its only yellow left). The game's process registry has the same ids on
  both models (Pro registry 0x720c14, LE 0x72bc40, 347 entries of 12 bytes), and the LE's registry entries ARE its
  port's `site show_<n>` lines, so the Pro's bodies for the LE's ten shows are: 312 0x1cb718, 213 0x11532c, 300
  0x1c8e70, 301 0x1c8f34, 302 0x1c8ff8, 304 0x1c90bc, 330 0x1cd40c, 315 0x1d03b8, 299 0x1c8730, and the attract
  director's sweep at 0x1cb0f4 by signature (`shows/sigmatch.py`). The helper's Pro scan (`shows/runs/godzilla_pro-1.16.20`)
  says they look different on the Pro (300 is red, 304 moves nothing), and `shows/calib/res.json` is not in the LE
  port's order, so do not reuse the LE's names blind: scan just these eleven on the Pro (`mkscan.py` with an
  entries file, `scan_job.sh`, 20 s each) with a glshot of the playfield view per show, and name them from that.
  The same registry-id route gives every other title's candidates once one show per title is named by eye.
- **Jaws Pro 1.02**: the runtime reads in_game 0 with player 1 during a game, so `data mode_mask 0x89e53e` &
  `value mode_mask_busy 0x210` (copied from Jaws LE) stays busy. Needs a memory read in a running Pro game
  (a probe mode logging the mask word before and after Start); desk matching of the LE's derivation sites failed.
- **Where the proven sets stand (run 5):** ball save 28/30 (D&D Pro: no game ever started, twice; Guardians LE: no
  shot scored on the saved ball), multiball 26/30 (Munsters Pro, Star Wars LE, Stranger Things Pro, Venom Pro died
  at boot or Start under an over-committed machine: re-run on one rig, `mb/rb2`), lights 19/30.
- **Lights on Mandalorian Pro and Munsters Pro (and the other unproven ones)**: the mode held every insert at layer
  255 and the port's lamp lines are exactly what each program says (`lampmap.port_lines`), yet the shim's LED view
  shows no change: nothing judge.py can read moved. So the LED view does not decode these builds' insert frames
  (see memory PAD-311, the LED view's per-title dispatch). That is emulator tooling (hwshim's LED view), not the
  port; prove these after the view decodes them, or by a glshot of the playfield view.
- **Stack**: two routes. Ball-count titles (Aerosmith, Batman, Guardians, James Bond, Stranger Things, Uncanny
  X-Men: their older builds are in STACK_BALLS_PROVEN) are proven by `st/st_job.sh` (our own multiball stopped
  with its balls in play, a `stack no` mode refused "a multiball is running", then started at one ball; Aerosmith
  LE 1.16 passed). Mode-table titles (STACK_PROVEN: Avengers, Deadpool, D&D, Foo Fighters, Iron Maiden, Jaws, John
  Wick, Jurassic Park, King Kong, Mandalorian, Munsters, Rush, Star Wars, Sword of Rage, Venom...) ignore our own
  multiball (Avengers LE 1.10: WAITER started with three balls in play), so they need one of the GAME's modes
  running: item 164's `C:/tmp/pad_generic/t5/stack_probe.c` + `stack_e2e.sh` start a table entry through its vtable
  start slot (`stack.start "<index> <slot>"`); port that probe to this worktree's runtime (build with Ubuntu's
  arm-linux-gnueabihf-gcc), find each title's start slot as item 164 did, and add a table-route stack job.
- **Run 6: the full yellow list** (`C:/tmp/PAD-420/yellow.py` runs the tab's own `_grey_what_the_title_cannot` on
  every newest build and lists every reason line; use it to measure progress, not `TitleProfile.cannot` alone).
  On the new builds screen and clip drag six lines each (screen, clip, show_all, show_order, clip_both, film), so the
  media proof is next: `media/build_all.py` (detached Windows process) builds every new build's Try it set against
  its SHIPPED port (`build2.py`: a mode with its own magenta screen, a 4 s title-card clip, its own sounds and
  music), then `chain10.sh` runs `media/proof_job2.sh` per build on two rigs (it now leaves Check this game before
  the mode's game). `media_verdict.py` judges the frames (clip: a clip frame >= 50% magenta; screen: a screen frame
  1-50% magenta, before and after < 0.5%), `scenes_prove.py` flips TITLE_SCENES' proven flags.
- **Time-up callouts**: 36 newest builds (20 of them older proven ones: Beatles, Deadpool, Elvira, Foo Fighters,
  Iron Maiden, John Wick, Jurassic Park, Led Zeppelin, Mandalorian, Star Wars, Sword of Rage, TMNT, Uncanny
  X-Men...) have no `callout time_up`, so the Sound page shows "does not know X's time-up callout". Item 163 found
  the callouts it has by hearing them; finding the rest means picking the "time is up" voice line out of each
  title's callouts (the media proof's sound census lists the requests the game makes).
- **Avengers: Infinity Quest Pro 1.10's sound bank cannot be rewritten**: building its Try it set stopped in
  `spike2/masterdir.py _crypto_sites` ("this game version's sound-bank directory cipher could not be located in its
  firmware"). Avengers LE 1.10 builds. So on the Pro a mode's own sounds, and likely anything that rewrites its bank
  (Replace Audio), fail; worth its own ticket. Its media proof runs without the mode's own sounds (`--no-sound`).
- **D&D LE 1.10**: the proof mode's own sounds grow its bank past 2 GiB (2,166,683,134 bytes; PAD-176's limit), so
  its proof set is built without them too.
- Retries still failing: Aerosmith Pro 1.16 stack (our multiball never started on the retry), Munsters Pro 1.28
  multiball (the drains count 3-4-3-0 twice: two balls leave at once, look at its trough/drain switches), Star Wars
  LE 1.31 and Venom Pro 1.07 multiball (the game died at boot or Start on every try so far), Guardians LE 1.15 ball
  save (no shot scored on the saved ball, twice: its jackpot switches are drop targets the earlier presses left down).
- **Light shows, run 6 result: not shippable yet.** A focused scan of the eleven registry-matched Godzilla Pro shows
  (`shows/runs/gzpro11.20`) and a full one of Jaws LE's 216 candidates (`shows/runs/jaws_le-1.02.3`) ran clean, but
  the measurements do not hold still between runs (process 312 moved 34 channels on one Pro run, 6 on the next; the
  game's own lamps move 50-100 channels in the quiet window), only 2 of Jaws's 216 moved 15+ channels, and
  `showstrip.py` draws every title on Godzilla's playfield art with only the inserts it can place. Naming a show
  honestly needs, first: each title's own playfield picture and fixture map in the strip, and the game's own lamps
  quieted during a scan (e.g. scan in attract with the lamp test off, or diff against a recorded quiet baseline).
- **Venom Pro 1.07 multiball**: died ~3 s after Start on three runs (a lock call on a null object, LR 0x17d6f4), then
  passed on the fourth: the same intermittent boot/Start crash the over-committed runs showed, not the port.
- **Munsters Pro 1.28 multiball**: with KEEP (as Munsters LE needed) the drains went 3-4-3-2-0: the last two balls
  left together on the third drain. Look at its trough/drain switches (plunge.py drain) before trying again.
- **In flight at the end of run 6** (detached WSL chains in `C:/tmp/PAD-420`, logs `chainN.log`; each writes a
  rigbatch `results.tsv`; commit passes with `prove_set.py <SET> <results.tsv> "<evidence>"`, then
  `limits_table.py`, the tests, and a commit):
  - chain10 (running since 20:39): the media proofs (`media/rb`). Land them with `media_verdict.py <key>...` (clip: the
    runtime logged our clip played and a clip frame is 25%+ magenta, as a clip plays inside the HUD's frame; screen:
    logged found, the mode started, magenta while it ran and none before or after), then `scenes_prove.py`, tests,
    commit. Aerosmith Pro 1.16 landed (frames looked at: the clip's title card and the boxed screen both up).
  - Order, so nothing starves the rigs (faster-whisper on several cores beside two rigs made the games hit their
    10 s watchdog): chain10's media batch, then chain18 (re-runs every build whose media verdict is not both
    PROVEN, then writes media/RETRIES_DONE), then chain19 (the scoop batch, `scoop/SCOOP_DONE`), then chain21 (the
    held coils, `coils/COILS_DONE`), then `t2/voices_after_media.py` (it waits for COILS_DONE) starts
    the transcription. Never edit a chain or job script while it runs: bash reads it as it goes (Guardians Pro's
    first media run died on a mid-run edit of proof_job2.sh).
  - Iron Maiden LE/Pro 1.18's clip: the port carried the game's own video getter (a demand-loaded bank's surface,
    which has none of our clips), so the clip was never played; dropped (run 7), staged into both proof sets, and
    chain18 re-proves it.
  - chain19, the scoop (`C:/tmp/PAD-420/scoop`): `mkstage.py` stages the branch's port + only the scoop lines the
    mechanisms helper placed (handler, slot, event, event argument, process calls; every site and slot checked
    against the program), the pinned runtime and a 4 s hold; `scoop_job.sh` (rigbatch) times the game's kick with
    no mode, in the mode, at a mode stop and after it. Land a build when the hold kick is ~4 s after the no-mode
    one, the stop lets go at once, and mode.log says "let go after 4000 ms": add `scoop/stage/<key>.lines` to the
    port (`coils/scoop_lines.py` does it from a stage port), `SCOOP_PROVEN`, recipes, limits table, tests, commit.
  - chain21 (replaced chain20, run 8: started at once on a third rig), held coils on generations B and A'
    (`C:/tmp/PAD-420/coils`): `bderived.py <key>` reads each build's `spike::ControlCoil` getters, devices, control
    offset, take/give and each subclass's own "on" (the game's own hold command); `aderived.py <key>` the same for
    the 47-virtual ControlCoil (Avengers, Jurassic Park: the powers are the object's own fields as each getter
    builds it); `offslot.py` the "disabled" virtual (B v[30], A' v[31]: `<name>_off_slot`). `mkstage_b.py` stages
    13 builds; `coil_job.sh` boots once with `value coil_list 1` for the board addresses (`fill_b.py`), then again
    holding every coil 2000 ms as the mode starts, and once stopped 1.5 s in. `coil_verdict.py <key>...` judges
    ([coildrive] ONE command at its own powers on its address, the game's OFF ~2 s on, an early OFF at the stop,
    the runtime's device check and hold lines, no abort); `coil_land.py --write <key>...` puts the proven coils'
    lines in the port and their `HELD_COILS_PROVEN` entries; then recipes, limits table, tests, commit. A coil
    name is at most 15 characters (the runtime's and mode file's name buffers are 16). chain21 writes
    coils/COILS_DONE only after the scoop batch too: the transcription waits for it.
  - Run 8 findings: John Wick LE/Pro 1.02's ports had the same wrong video getter as Iron Maiden 1.18 (John Wick
    LE 1.01's port says it answers 60ed7e50's surface): left off, both stages refreshed for chain18's retry.
    Generation C (the Device framework): each class has its own take/give (`coils/takegive.py`: control at +0x18 /
    +0x1c / +0x20 per class), but its gates are driven through another service (Aerosmith LE ControlGate v[28]:
    0x332c7c with a byte at +4, a time and a callback), not `coil_fire`, so their powers are not in the code; do not
    hold a C coil by `coil_fire` until the powers that service uses are read (magnets do call `coil_fire`: Aerosmith
    LE's toy box magnet 255 for 1 s, then 16). Deadpool's scoop handler does take event 2 (its jump table), so
    the wrap of its slot never takes effect (its ball-device table is another generation: "Trough"): a call probe.
  - `t2/voices_all.py` (detached Windows process): transcripts for every new build; land them with
    `t2/apply_new.sh` (applies callouts, rebuilds recipes), tests, commit. Rush LE, Aerosmith Pro/LE, Avengers
    LE/Pro, Deadpool LE landed.
  - chain13: Munsters Pro multiball with KEEP (`mb/rb4`), Venom Pro multiball, Aerosmith Pro stack (`st/rb3`).
  - chain14 DONE: Check this game passed on all 15 ports that got block lines (`rb_blocks`, check7), the runtime
    logging each title's starts hooked ("block: on - a mode keeps N of the game's modes from starting").
  - chain15/16: checks of Elvira 1.13, TMNT LE 1.59, Venom LE 1.07 (check8), then their ball-save tests
    (`bs/rb_old3`, made by `bs/gen_old.py` from those checks).
- **Stack on the mode-table titles, run 6 attempt**: `C:/tmp/PAD-420/st2/stack_starter.c` (a code mode built into
  the runtime with `build_mode.sh mode_file.c stack_starter.c`) reads the port's mode table and block lines from
  `/dump/game.port`, finds the start slot (where a block line's object's vtable holds its start: 11 on Avengers LE
  1.10) and starts the first multiball entry (`cmode_mball` by its typeinfo). On Avengers LE 1.10 it started Thor
  Multiball and the runtime said "a multiball is running", but the game turned it off within 0.5 s (no balls
  served), before the runtime's next look at the trigger file, so the waiting mode started. Next try: start the
  multiball from a state where it holds (balls in its lock first, or the game's own qualifying shots), or have the
  starter and the stack check run in the same tick.
  Tried next: the starter first had the game serve two more balls (`pm_multiball_add(2, 10)`: three in play), then
  started Thor Multiball: still off within 0.5 s. Calling a mode's start alone does not set what keeps it running;
  the remaining route is to qualify a multiball the way a player does (its lock shots), per title.
- **Voice callouts on the new builds were copied, and can be wrong**: every new port's `callout` lines came from its
  older build. Rush LE 1.19's moved by five (1.18's ten_seconds 318 says "Trio Combo!" on 1.19; time-up is 267 there,
  not 262), fixed from its own transcripts. `C:/tmp/PAD-420/t2/voices_all.py` (detached) transcribes every new build's
  candidate requests (item 163's voices.py, faster_whisper, this worktree's code); then `t2/apply_callouts.py
  [--write]` sets each build's countdown / ten_seconds / time_up from its OWN lines (an old id kept only if its own
  transcript says the role), then recipes, tests, commit. The same transcripts can give the builds with no time-up
  callout one where the game has such a line. The media proof sets were built with the copied ids: their screen/clip
  proof does not depend on them.
- Lamp lines read from each program (`lampmap.port_lines`, the lights helper's reader fix cherry-picked) for the 8
  builds that had none.

## Left, per part (the next runs)

| part | what is left | how |
|---|---|---|
| screen, clip | the 32 new builds: a screen and a clip seen on the glass | `TITLE_SCENES` `screen_proven` / `clip_proven`; the item-164 proof (a mode with a screen and a clip, `glshot.sh`) |
| multiball, ball save, stack | the 32 new builds (plus Elvira, Venom LE, TMNT LE, Godzilla LE ball save) | `MULTIBALL_PROVEN`, `BALL_SAVE_PROVEN`, `STACK_BALLS_PROVEN`: `C:\tmp\pad_generic\mb\mb_batch.sh`, `bs\bs_job.sh` through `rigbatch.sh` |
| lights | the new builds whose `lamp` lines are not yet tied (Pro siblings of an LE port), and `LAMPS_PROVEN` for all 32 | the lights helper's branch `ticket/PAD-420-lights` ties 15 shipped builds' inserts to their shots (desk; its emulator trials failed to boot, not yet proven) |
| shows | every title but Godzilla Premium/LE | per title: the show processes in its registry, each played by `show_reel_mode.c` and measured at the LED view (MODE_SDK.md "The game's own light shows"); scratch in `C:\tmp\PAD-420\shows` |
| scoop | proven (run 7) on Avengers LE 1.10, D&D LE 1.10, Guardians LE 1.15, Iron Maiden LE 1.18, Aerosmith LE 1.16 (the mechanisms helper's runs); 25 more staged (chain19) | Deadpool LE/Pro and James Bond Pro: the handler never saw a settled ball (a call probe of the device's handler next); Aerosmith Pro, Batman, JB 60th: the job closed the wrong switch (fix `mechs_conf.SCOOP`) |
| held coils | the runtime holds a coil by its board address (the helper's WIP, built and pinned run 7); generation B's coils read off the programs (`coils/bderived.py`): Iron Maiden LE/Pro up posts, the orbit/control gates of Deadpool LE/Pro, Led Zeppelin LE/Pro, Sword of Rage LE/Pro, Star Wars ELG; staged (chain20) | A' (Avengers, Jurassic Park LE) and C (the Device framework, most titles): each title's classes keep the control field elsewhere (Aerosmith LE's gate +0x18, its magnet +0x14); the same reading per title, then the same route. Every hold power must be the game's own (a mode file reaches real machines) |
| magnet (Mode > Magnet) | Godzilla only | the magnet part also needs `magnet_shot`; a title's magnet can be offered as a held coil first |
| shaker | none here | PAD-414 (awaiting approval) adds the shaker part; `ticket/PAD-420-shaker` is a duplicate and is not merged |
| countdown | Aerosmith, John Wick, Elvira: the voice never says a number | `COUNTDOWN_NO_NUMBERS`: decide with David whether a countdown there is a number on screen only, with the section saying so in grey |

Helper branches from the first run (pushed, not merged): `ticket/PAD-420-lights`, `ticket/PAD-420-balls` (a runtime
guard: a port's mode table that is not the game's is left out instead of crashing it; changes the prebuilt object,
needs a library sweep before it lands), `ticket/PAD-420-mechs` (WIP), `ticket/PAD-420-shaker` (superseded by PAD-414).
