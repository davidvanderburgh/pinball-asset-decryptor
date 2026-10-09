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
    Run 8: on Deadpool, Led Zeppelin, Sword of Rage and Star Wars ELG the gate objects are built by a STATIC
    INITIALIZER with no getter (Iron Maiden, Avengers and Jurassic Park have guarded getters); calling it as a getter
    built them again and the game died as the mode started (Deadpool Pro exit 4). The runtime now takes `data
    <name>_obj` (the object's address, `coils/bobj.py`); `mkstage_b.py STATIC_OBJ`. Never re-run mkstage_b.py on a
    build whose job is running: it wipes coils/b/<key> (Avengers LE's first run was lost so). chain23 (replaced
    chain22) re-runs every build `coils/rerun_keys.py` finds not fully PROVEN, then the stack batch, then writes
    RIGS_DONE (after COILS_DONE); the transcription waits for RIGS_DONE.
    Run 8, why games did not start in the rig jobs (coil, scoop, media, checks: "no game started after three
    tries"): a first boot shows Guided Setup (`bs/guided.sh` leaves it by Save & Exit: Led Zeppelin LE needed it);
    a loaded host brings the game's loop up late (Jurassic Park LE: 127 s), so wait for mode.log's "game: in_game"
    first; and put credits in before Start (`plunge.py coin 8`). The coil and scoop jobs do all three now and keep
    a frame (`nogame.png`) when no game starts; the media job leaves Guided Setup before its census. And the
    [coildrive] lines need `PAD_COIL_PROBE=1` (the coil and scoop jobs export it).
    And a slot's NVRAM for a title can go bad: Avengers Pro in slot 2 hit FATAL 246 ("NVMigration: REGISTERED_DATA
    hash is NOT UNIQUE") and the game's watchdog ended it before any Start. The coil, scoop, media and stack jobs now
    wipe the title's NVRAM in their slot (never slot 0) before booting (the coil and scoop jobs only); Guided Setup is then left by guided.sh, and its Save & Exit RESTARTS the game (in the emulator the old one hangs and the watchdog ends it), so those jobs boot the stage again after it. The media and stack jobs keep the slot's NVRAM.
    chain26 (after chain25) runs one more round of coil re-runs (rerun_keys.py).
  - `t2/voices_speedup.py` (detached) restarts the transcription with four threads at normal priority once
    RIGS_DONE appears.
  - The two builds with no port, probes queued after RIGS_DONE (`C:/tmp/PAD-420/jawspro`): chain24 runs
    `probe_job.sh` on Jaws Pro 1.02 (its candidate port, `clean/jaws_pro-1.02.port`, and `mask_probe.c` logging the
    mode mask word and player in attract and in a game: "maskprobe:" in run/<key>/mode.log). The mask ADDRESS is
    right (`coils/masktest.py`: the Pro tests 0x89e53e against #0x210 in the same two places the LE tests
    0x874d0e), so it is the busy BITS the Pro sets in play; set `value mode_mask_busy` from the probe. chain25 runs
    `batman_job.sh` on Batman 1.14 (frames after the plunge and each drain, the rig's padball.log, the coil log): the
    ball never ends on a drain there.
  - Run 8: the transcription no longer waits. `t2/voices_all.py` runs NOW at Windows idle priority, its children too
    (creationflags IDLE_PRIORITY_CLASS) and one whisper thread (`T2_THREADS=1`, voices.py), so the rigs keep the CPU.
    Land each transcribed build with `t2/apply_new.sh`, tests, commit; t2/VOICES_DONE when all are done.
  - The app's sound derive fails on D&D LE 1.10 ("registration did not reach band-build ... could not map this
    firmware build's audio codec"); the media sets of D&D LE/Pro 1.10, Star Wars LE/Pro 1.31 and Avengers Pro 1.10
    were built without sound for the same reason. That is the Audio tab's decoder on these builds, beyond modes;
    retry their transcripts with `PAD_DERIVE_HOOKS=global` (the older, slower derive) after the main pass, and if
    that fails too it is its own ticket.
  - Run 8 findings: John Wick LE/Pro 1.02's ports had the same wrong video getter as Iron Maiden 1.18 (John Wick
    LE 1.01's port says it answers 60ed7e50's surface): left off, both stages refreshed for chain18's retry.
    Generation C (the Device framework): each class has its own take/give (`coils/takegive.py`: control at +0x18 /
    +0x1c / +0x20 per class), but its gates are driven through another service (Aerosmith LE ControlGate v[28]:
    0x332c7c with a byte at +4, a time and a callback), not `coil_fire`, so their powers are not in the code; do not
    hold a C coil by `coil_fire` until the powers that service uses are read (magnets do call `coil_fire`: Aerosmith
    LE's toy box magnet 255 for 1 s, then 16). Deadpool's scoop handler does take event 2 (its jump table), so
    the wrap of its slot never takes effect (its ball-device table is another generation: "Trough"): a call probe.
  - Lights on the 11 builds still yellow for lights / lit shots (Avengers LE/Pro, Foo Fighters Pro, John Wick LE/Pro,
    King Kong Pro, Mandalorian LE/Pro, Munsters Pro, Rush LE/Pro): their ports' lamp lines and shot ties are there
    (Rush LE: 28 of 38 shots tied), but most of their inserts sit in device-table groups the rig has NO node for
    (the slot's tables/<title>/group_node.txt: King Kong Pro group 1 = 288 LEDs and group 9 = 227, Rush LE group 1
    = 288, all "drawn dark"), so the LED view never shows them and judge.py sees a handful of channels (King Kong
    Pro 0 of 9 RGB). Iron Maiden LE's inserts are on nodes 8/9 and pass 42/42. Proving these needs the rig to
    present those LED boards (emulator work, PAD-311's area), not port work.
  - Stack on the mode-table titles (`C:/tmp/PAD-420/st3`, chain23 after the coil batch and its re-runs, one rig): run 6's starter
    began with a MULTIBALL entry (Avengers' Thor Multiball), which the game switched off in 0.5 s. st3's
    `stack_starter3.c` starts a BATTLE through the port's block starts (each mode's START slot, never a multiball)
    and drops /dump/mode.start in the same tick; `st3_job.sh` follows item 164's order (WAITER started with nothing
    running and stopped, then the battle and WAITER refused); `st3_verdict.py`. Land a pass with
    `prove_set.py STACK_PROVEN st3/rb/results.tsv "<evidence>"`.
    Run 9: the first two (Avengers LE/Pro) failed because nothing had scored on the ball yet - the battle's own start
    was the ball's first score, so the runtime (rightly) took it for the game's base play (a mode running when the
    ball first scores, plus 2 s, is not counted). st3_job now taps a few playfield switches after the plunge and
    waits 6 s; Deadpool LE passed at once (Battle Mystique). chain27 re-runs the builds that did not pass once
    chain26 and the stack batch are done.
    Stack batch result (run 10): 11 of 22 proven (Deadpool LE, D&D LE, Foo Fighters Pro, Iron Maiden LE/Pro, John
    Wick Pro, Munsters Pro, Rush LE, Sword of Rage LE/Pro). Most of the rest never reached the test: on slot 2 the game
    died at boot while crun4 waited past its tech alerts (Venom Pro, Mandalorian Pro, Jurassic Park Pro) or right
    after Start (Star Wars LE), a segv in libpthread (a mutex at a null object + 0x18) from the game's own code, the
    same address on four titles. Not the port (Venom Pro's media run used the same port and played), no NVRAM error.
    chain27 re-runs them; if they die again, move st3 onto the coil job's harness (watch.sh direct, its own game
    start), the one thing they share being crun4's boot.
    Done in run 10 before chain27 ran: st3_job.sh is now on the direct harness (fresh NVRAM, Guided Setup reboot,
    credits, the game-loop wait, the ball scored by switch pokes), stack3.so rebuilt on the current runtime.
  - chain28 (after chain27): a third media round on two rigs for every build not both screen and clip PROVEN,
    with `FRESH_NV=1` (proof_job2.sh's prep boot: the title's NVRAM in the slot started fresh and Guided Setup
    left, then the normal run). D&D LE's retry hit an NVRAM FATAL 256 in its slot (no game ever started); Aerosmith
    LE's game hit its watchdog during the census presses.
  - "Clip played but not seen" (run 9-10): King Kong Pro, Rush LE, Stranger Things Pro, John Wick Pro (after its
    getter fix) log `clip ... played` yet no frame shows it; Stranger Things LE (same route as its Pro) and the
    others proved. John Wick Pro's retry ran its mode on player 2's turn (Start pressed again before the first game
    was logged added a player); proof_job2 now waits up to 30 s after each Start. If round 3 still misses them, look
    at what covers the clip on those builds (the bank drawn under the HUD's own video, or the frame times).
  - The whole queue, in order: chain18 (media retries, 2 rigs) -> chain19 (scoop, 2 rigs) -> chain21 COILS_DONE;
    chain23 (rig 2: stack batch) -> RIGS_DONE -> chain24 (Jaws Pro probe) -> chain25 (Batman probe) -> chain26
    (coil re-runs 2) -> chain27 (stack re-runs) -> chain28 (media round 3). Transcription: idle now, 4 threads after
    RIGS_DONE.
  - **Run 12 (2026-10-08 01:15-) - why so many rig runs died, and the third rig.**
    * "fail slot" 9 s in (JW Pro scoop, D&D Pro map): watch.sh REFUSING root-owned title NVRAM in slots 1, 3, 4
      (1300+ entries each), left by `bs/crun4.sh`, which runs the game as root (the ball-save and early stack jobs).
      Given back to david (watch.sh's own fix); no queued job uses crun4 now.
    * The game dies AT START with a segv in libpthread (a mutex at null + 0x18): D&D Pro, Guardians, JB LE in the
      scoop batch, and the stack batch's four. On D&D Pro the null is `dynamic_cast<RadiumScene*>` of a scene the game
      looks up by id at game start: the scene was not loaded yet. scoop_job.sh and cmap/mapjob.sh (and proof_job2.sh
      through media_job.sh) booted the ORIGINAL card on the spinning D: disk - their conf/json overrode the NVMe copy
      rigbatch stages - so two or three rigs plus the stager read one disk and stalled (rigbatch's own warning). All
      three now boot the staged copy (`CARD=${2:-$CARD}`; proof_job2's third argument). chain31 re-runs the scoop
      builds whose game never started.
    * Elvira 1.13 starts no game on the direct harness: glshot.sh fails on it, so guided.sh cannot see Guided Setup
      (its earlier runs went through crun4). Open.
    * A third rig (slot 3) beside the queue's two: chain29 (`cmap/`, every coil device's board address on the builds
      whose ports had no coil table) and then chain30 (`coils/c/`, generation-C held coils: cgen.py stages, fill_c.py
      on the rig, coil_job_c.sh, c_verdict.py), each started only while every held PAD-420 slot shows its holder active.
    * Generation C, by the board address and no object: 21 builds whose coil_fire calls carry a CONSTANT device and a
      hold (mechs/holds: Mandalorian's posts 255/64 then 128 for 1.5 s, Munsters' magnet 255/1200 then 18, Star Wars
      LE's 255/500 then 56 ...); fill_c.py learns each coil's device from the first boot's coil list and takes that
      device's own command; the eight older ports' process calls from port_tool (strict, Godzilla Pro 1.16 the
      reference; `C:/tmp/PAD-420/procs`). The `_drive` line's new last word caps a hold at the game's own longest
      command (commit 57e37eae). NOT on this route: the ControlGate class (Aerosmith LE's up/down gate, Guardians LE's
      orbit gates): the game drives it through a 40-slot driver at FULL power in 250 ms chunks up to 187 x 16 = 2992 ms
      (its activation's cap), which never touches the coil records - so "the game wins" would need the gate object's
      own active flag (+0xc) and no OFF of ours when the game takes it. Next, per title.
    * Voice: eight more builds' callouts from their own transcripts (ST LE's countdown by hand); a time-up line on
      eleven builds that have no "time's up" (tu_wide.py): Avengers 635, Iron Maiden 315, JP 915, Mandalorian 768, SoR
      LE 514, Foo Fighters 878; then the last three transcripts (SoR Pro, X-Men Pro, Venom Pro) and SoR Pro's 514.
      Transcription is DONE for every build (voices_all.log "ALL DONE"). Still no time-up line: Elvira, Turtles, John
      Wick, Deadpool, Led Zeppelin, Star Wars, Beatles, X-Men, JP the Pin (none among their transcribed lines).
    * Scoop batch result: 15 more PROVEN (JW LE, KK LE, Mandalorian LE/Pro, Munsters LE/Pro, Rush LE/Pro, Stranger
      Things Pro/LE, Sword of Rage LE/Pro, Venom LE/Pro, and D&D Pro on its re-run from the staged card). Star Wars
      LE/Pro held and let go right but the game kept the ball 12.7-15.6 s after the mode (its own) - re-run. LZ Pro
      and Metallica: the handler was wrapped but never held (another "settled" event) - chain32 probes them with
      `value scoop_log 1` (f2b66047). chain31 re-runs the builds whose game never started (Guardians, JB LE, JW Pro,
      KK Pro, LZ LE, Metallica). Elvira: no game on the direct harness.
    * Staging, the second half of the start crashes: a one-rig rigbatch does not stage at all (now `--stage` in every
      queued one-rig chain), and a batch's end emptied the SHARED .partial - the scoop batch's end deleted the C
      batch's card 20 minutes into its copy. Fixed in rigbatch.sh / cardstage.sh (aa960787: each batch's copies under
      `.inflight/<hash of its out dir>`); chain30 restarted on it. C: is ~98% full (the stage keeps 100 GB).
    * Yellow census after run 12's landings: shows 50, coils 34, magnet 28, stack 21, sound 18, scoop 15, film 15,
      clip 14, lights 11, screen 10, own_music 3, no port 2 (Batman 1.14, Jaws Pro: chain24/25 probes), ball_save 2.
    * The two probes (chain24/25): Jaws Pro started NO game - the rig's trough read 0 of 6 ("a ball is in play", an
      attract ball search), so its mask never moved (0x0010 throughout). Every queued job now runs `plunge.py reset`
      (six balls home, the door shut) before its coins; chain33 runs the Jaws Pro probe again. Batman 1.14: a game,
      and after each of three drains the game fired its trough eject again (node 8 coil 1 at 162, 190, 218 s) - the
      ball given back, the probe having hit no playfield switch (a saver that starts on the first switch never runs
      out). gamecheck.sh does hit three switches after a saved drain and waits 15 s, yet three checks never ended a
      ball; chain34 (batman_job2.sh) hits six playfield switches and waits 30 s before each drain.
    * Generation C, first result (Guardians 1.15's orbit gates, node 9 coil 0, the ControlGate route): at the
      first start the game was raising the gate itself (its 255 / 250 ms chunks) and the hold was REFUSED off the gate's
      active flag (`_ctl 12`) - the game wins; the second start held ONE command, 255 for 250 ms then 255 for 1230 ms
      (cut to the game's own 1488 ms), and the mode stop sent the game's OFF 500 ms in; no abort. No full hold yet
      (the collision): coil_job_c.sh now waits 8 s after the plunge, and c_verdict.py finds OUR commands from the
      runtime's "HOLD for" lines (a ControlGate's drive is the game's own chunk, so powers cannot tell them apart).
      chain36 re-runs every C build with nothing proven once the batch is done.
    * Guardians LE 1.15's orbit gates PROVEN (7779f74d): a full 1480 ms hold, and when the game raised the gates 32 ms
      into a second hold (it does so as a mode starts) the hold let go with no OFF of its own and the game's
      activation ran untouched. c_verdict.py counts that (TAKEN) or a mode stop's OFF (STOP) as the let-go evidence.
    * King Kong Pro 0.97 dies in its scoop runs even on the staged card: a segv in a game listener (0x79de8, `ldrb r3,
      [r0,#0x3c]` with r0 null from a table) called from hook_dispatch (0x378ef0, which the runtime hooks for its
      events) - its media runs played games with the same port minus the scoop lines. Open: compare the scoop stage's
      lines (the handler wrap, the slot) with a media run's.
    * Queue at run 13's end (each one rig, --stage): chain30 (C coils, rig 3, 25 builds) -> chain36 (C re-runs:
      nothing proven yet, staging/boot failures); chain27 (stack re-runs, 12) -> chain28 (media round 3, 2 rigs);
      chain32 (scoop probes: KK Pro, LZ LE, LZ Pro with scoop_log) -> chain33 (mask probe: Jaws Pro, Metallica) ->
      chain34 (Batman probe 2) -> chain35 (B/A' coil re-runs: Avengers Pro, JP Pro). Notes per build in
      C:/tmp/PAD-420/RERUNS.txt. Land: scoop `scoop_verdict.py --write`, C coils `c_verdict.py` + `c_land.py --write`,
      B coils `coil_verdict.py` + `coil_land.py --write`, stack `st3_verdict.py` + prove_set, media `land_all.sh`;
      scoop handler events: `scoop/scoop_events.py <key>` on outp/.
    * Run 14: the test modes never said `game_modes`, so they took PAD-398's default (block), which refuses a start
      while one of the GAME's modes runs ("not started (trigger file): one of the game's modes is running"). That is
      why LZ LE/Pro's scoop runs never held (their first landing starts the game's own scoop mode; the probe shows the
      handler does get event 2 ~0.8 s after landing, the same "settled" event as Godzilla) and why Sword of Rage LE's
      media proof never started its mode. Every test mode now says `game_modes stack`: the 32 media proof modes
      (try/set-modes, before round 3), fill_c.py / fill_b.py and King Kong Pro's stage; chain38 re-runs the scoop on
      LZ LE/Pro, Star Wars LE/Pro and JB LE that way (scoop/stage3, scoop_job3.sh, out3; `scoop_verdict.py
      --out=out3`).
    * King Kong Pro 0.97's coils on Godzilla's ControlCoil route (as King Kong LE): port_tool placed the spider pit
      magnet's and the log/river diverter's getters strictly from King Kong LE's port; the getters build devices 10
      and 12 (LE: 10 and 13); no center ramp diverter on the Pro. chain37 (coils/k0, coil_job_k0.sh) proves them.
    * Magnet part, the candidates the playfield layout gives (devicexy, the switch nearest the magnet coil): Avengers
      LE's tower magnet sits at the TOWER OPTOs (distance 1; its port's four "Tower" shots are bits 32-35, which the
      app writes into the mode line itself), Beatles' top magnet at its TOP MAGNET OPTO, King Kong LE's spider magnet
      near the PIT TARGETs. Most other titles' magnets have no position. Each needs `magnet` named in its port and a
      rig proof of a `magnet` line grabbing on that shot.
    * The two "no port" builds, run 14: Jaws Pro 1.02's mode mask read 0x0010 in attract and 0x0110 "in a game" -
      WRONG: that probe never had a game (its picture is the first boot's Guided Setup). Run 20 measured a real game:
      0x0010 in attract, 0x0000 in a game, as Jaws LE, so its port keeps LE's busy 0x210 and `value mode_mask_game`
      (5d3776bc) went back out of the runtime (16ebedb9). Batman 1.14 (probe 2): with six
      playfield switches hit and 30 s waited before each drain, its ball ended at once and its game after three, so
      gamecheck.sh now waits a giving-back saver out longer each time (60abadb6). chain39 runs Check this game on both
      (jobs/check_job3.sh: fresh NVRAM, balls reset); a pass lands each port (the port into ports/, its recipe, then
      the parts like any new build).
    * Run 14 landings: held coils on Mandalorian LE/Pro (3 each), Munsters LE/Pro (post, magnet), Star Wars LE
      (control gates, outlane gate), Star Wars Pro (gates), Stranger Things Pro/LE (left down post, 416 ms - its own
      longest), Avengers Pro (tower magnet and post), Jurassic Park Pro (3 posts), King Kong Pro (spider pit magnet,
      river diverter: Godzilla's ControlCoil route from King Kong LE's port, its slot's own NVRAM); the scoop on Led
      Zeppelin LE/Pro and Star Wars LE/Pro; stack on Avengers LE/Pro, D&D Pro, JP Pro, Rush Pro, Star Wars LE/Pro, Venom
      Pro. Census now: coils 24 (was 34 at run 12's start), scoop 9 (30), stack 15 (21).
      c_verdict.py: our commands found from the runtime's "HOLD for" lines; PROVEN = a full hold plus a mode stop's OFF,
      or a game takeover with no OFF of ours, or nothing more where the coil's own longest is under the 0.7 s stop.
      scoop_verdict.py: an after-mode landing the game keeps itself (Star Wars: 12.7-15.5 s) passes when the runtime
      held nothing once the mode had ended; the hold is then weighed against the no-mode kick. JB LE's game keeps a
      landed ball ~8 s on its own, longer than the 4 s test hold: it needs a 10 s hold run.
    * Stack, run 14: Mandalorian LE/Pro and John Wick LE start a mode of their own on the first shots that runs on
      (bounty mission one; a location), so WAITER asked after the taps never started. st3_job.sh now asks for WAITER
      right after the plunge (what runs from the ball's start is base play), then taps, then starts the game's mode;
      chain40 re-runs them after media round 3.
    * Fresh NVRAM: the jobs' `rm -rf .../nv/<title>` (added against a FATAL that was really root-owned NVRAM) and
      Guided Setup break King Kong Pro (a null listener object at Start: segv 0x79de8 under hook_dispatch) and
      Metallica (CREDITS 3/4 - coins lost). NOWIPE=1 on a list line keeps the slot's own NVRAM (coil_job_c.sh, coil_job
      .sh, coil_job_k0.sh, scoop_job3.sh, st3_job.sh); King Kong Pro's coils proved that way. Media round 3 runs
      without FRESH_NV.
    * Metallica 1.04: its mode mask is right (the probe: 0x0010 in attract, 0x0000 in a game, in_game 1). Its failures
      are elsewhere: after a fresh NVRAM's Guided Setup and reboot the screen reads CREDITS 3/4 - most of the job's
      coins never counted, so Start is ignored (scoop, C coils); and its scoop runs' mode.log stops 8 s in, right after
      the scoop handler is wrapped - the helper's scoop lines for it are not landed.
    * Metallica 1.04: a game IS on screen (PLAYER 1, credits taken) but mode.log never sees in_game - the port's
      `data mode_mask 0x07000012` / busy 0x210 stays busy, as on Jaws Pro. Added to chain33's mask probe (its port
      copied to C:/tmp/PAD-420/clean/). Every Metallica mode feature waits on this.
    * Lights (11 builds): their inserts sit in LED-only device-table groups (King Kong Pro group 1 = "EXPRESSIVE
      LIGHTING" 96 RGB, group 9 = 227 channels) with no connector named, so coilmap.group_node cannot join them to a
      bus node (it joins on switch names) and the LED view draws them dark; the title's node directory has four
      ws2812node boards (King Kong Pro nodes 2, 7, 12, 14) they must belong to. Emulator work (the LED view, PAD-311's
      area): map an LED-only group to its ws2812 node by what the game sends each node.
    * Run 15 (2026-10-08 05:30-): four rigs (one sometimes PAD-450's). Landed: Venom LE up post; James Bond LE/Pro
      control gate and the LE's jet pack magnet; stack on King Kong Pro, Mandalorian LE/Pro, John Wick LE; media on
      Foo Fighters Pro, John Wick LE/Pro, King Kong Pro.
      - **Batman 66 1.14 has a port** (9ec8ce31). Its checks failed because Check this game pressed "Turntable Pos.
        #2" / "Crane Pos. #5" (mechanism sensors, past the POSITION rule): the ball stayed in play for ever, a drain
        filling the trough with no ball end and no serve. gamecheck.sh skips `POS\.` now and says each drain's own
        answer (96f19732). chain45 runs its media, multiball, ball save, stack (ball count) and lights proofs; block,
        magnet, scoop and coils need deriving (1.13's block sites are not on 1.14).
      - **John Wick's locations are base play** (440aecb0, `text stack_base_names cmode_location_`): one runs for
        nearly all of a ball, so a stack-no mode waiting for it would hardly ever start. LE and Pro re-proven on it
        (Tick Tock refused the mode; the runtime named John Wick's House as base play).
      - **Mode > Magnet by a held coil** (2b2ca35f, `text magnet_coil <coil>`, `value magnet_shot` = the shot nearest the
        magnet on the playfield picture, `magnet/near.py` over lights/dxy): PROVEN on Jurassic Park LE (T-Rex mouth
        magnet, Left ramp enter opto) and James Bond LE (jet pack magnet, Tank hood target) - `magnet/magnet_job.sh`,
        `magnet_verdict.py` (two grabs, a stop mid-grab, and NOTHING else of the game's on the coil's address while
        it held). Taken back out of King Kong (the game pulses its spider magnet 4 x 20 ms on a pit target hit - each
        ends a hold, mode.log still said held) and Avengers (a tower opto makes the game grab the ball in its tower;
        our grab gives way): 021b504b. Most other magnets have no picture position; where a name gives the shot away
        ("... MAGNET OPTO") the game likely uses the magnet there itself - a question for David.
      - Batman 66 1.14 after its port: block lines (the plain-C start finder: the same 22 starts as 1.13; Check this
        game passed again with them hooked), multiball, ball save (bs_job.sh skips `Pos.` and plunges a saved ball;
        Batman passed only with NOPF - pressing its Penguin VUK / Top Eject over and over left a drain that never
        ended the ball), stack by its ball count, lights (6/6 RGB, 82/82). Left on it: screen/clip (round 4, the
        census no longer presses `Pos.`), coils (chain36), scoop (Penguin VUK not derived), lit shots, shows, the
        flags route (its draft's mode flags 86/88 unchecked; 1.13's were 58/71).
      - James Bond LE's scoop with a 10 s hold (scoop_job4.sh, STOP_AFTER=9): its game reports a ball settled ~3 s in
        and keeps it ~5 s itself; a hold replaces that keep (landed by hand, `scoop/land_jb10.py`). Aerosmith LE's
        upper gate, Guardians 1.15's orbit gates landed from the C batch.
      - Media: a ball-start selection screen covers a mode's screen and clip on Rush (song) and Star Wars (path and
        hero); proof_job2.sh takes PRE_PRESS=pf (two playfield switches first) - chain49 round 4.
      - test_stern_mode_ball_save had been red since 10-07 (Munsters Pro's ball save proven, its multiball not):
        now a named exception (6a2c155a). All 40 mode-related test files: 819 passed.
    * Run 16 (2026-10-08 07:30-):
      - **Lights on the 11 LED-heavy builds** (re-run with the ball launched and 15 s settled) - three causes, none
        the runtime's lamp layer as such: (a) LED-only expressive-lighting chains the LED view cannot show (the
        shim's padled plane is 96 channels a node; John Wick's group 1 is 86 RGB lamps, Foo Fighters Pro's group 6
        23) - their SHOT lights are proven (King Kong Pro, John Wick LE/Pro: lit-shots PROVEN); (b) a game layer at
        priority 255 over ours (Avengers Pro 2/36, King Kong Pro's light_all, Mando LE 1.45 - whose lamp ids ARE
        its program's: 79/80 by lampmap; 1.44 passed 92/92 with the ball still in the lane). Next: the LED view for
        long ws2812 chains (emulator); and a question for David - should a mode's lights sit above the game's own
        top-priority layer (it would mean relinking the game's layer list)?
      - **X-Men Pro's other modes**: its mode objects' running bytes, each object found through its own class's
        constructor as on X-Men LE (`coils/running_objs.py`: 10 of 11; 9 shifted by the same 0xac88 the uniform
        prediction gave) - in st3/ports16 (contiguous pairs: the runtime stops at the first missing N), chain56.
      - James Bond 60th's gates landed (d9c59ae8): a 940 ms hold ends before the job's stop is read (~1 s in);
        c_verdict.py counts that as nothing left to let go.
      - Card copies: a hung robocopy interop wrapper held the copy lock 24 min with three rigs idle; robocopy runs
        under `timeout` now (c8522077).
      - Landed from the object-class drives: John Wick LE's ramp diverter (adj 209/150, adj 210: 150 and 16 on the
        stock card), Rush LE's up post (adj 171/64, adj 172: 255 and 64), Batman 1.14's control gate and turntable
        diverter. Munsters Pro's lights (5/5 RGB, 60/60 single). Rush Pro: no class drive (its ramp diverter and
        magnet are a generic coil class with per-object powers) - left as "has not found".
      - Stack routes: Aerosmith Pro 1.16 with LE 1.15's record ids - "none of the game's modes would start" (its
        two block starts made no record the ids name): not proven, nothing landed. The other six run on (chain56).
      - Scoop (9 left): six have no scoop lines (Aerosmith Pro, Batman 1.14, Deadpool LE/Pro, James Bond 60th and
        Pro: their handler derivations failed before - the wrong switch, or no settled ball seen); King Kong Pro
        crashes in scoop runs, Metallica's handler is wrong, Elvira has no game on the direct harness.
    * Run 17 (2026-10-08 08:37-): **ONE RIG** (David, 08:43: other tickets need rigs - slot 2 released at once,
      slot 1 after its last coil job; everything left runs serially on slot 4: chain56 -> chain58 -> chain59 ->
      chain60).
      - Landed: X-Men LE's magnet (255 for adj 196 ms then 82), diverter (adj 163/164/165) and return post (its
        hold-only command, adj 169 for 0 ms then 169: the runtime wants a draw power), X-Men Pro's return post,
        Star Wars Pro's screen and clip (round 4, two playfield switches first).
      - **Stack routes**: the starter (stack_starter3) only started C++ mode objects; a plain-C title's block start
        has none - st3/stack4.so calls it with r0 0. And the record ids MOVED: each plain-C block start's first word
        is `mov r0, #<its first record id>`, and on Guardians 1.15 / Aerosmith 1.16 every id is the older build's
        + 4 (Guardians LE 1.15's first run "passed" naming Super Scoring for a Headphone Hurryup it started) -
        route_transfer16.py shifts them; nothing lands until a run names the mode it started. chain58 re-runs the
        failures, chain59 re-runs Guardians LE first. James Bond Pro PASSED with James Bond LE's flags (flag 141 set
        by Bullshit Scoring's start): landed (19512b3f) with `st3/land_route.py <key> <SET> "<evidence>"`, which
        copies that build's route block from st3/ports16 into its port and adds the proven-set entry.
      - Rush LE's clip is under its centre song video (its port lacks the clip frame hand-over lines - a full-screen
        clip is drawn from the tick); Star Wars LE's path/hero choice stayed through two switch presses (round 5:
        PRE_WAIT=15).
      - cgen's hold parser takes no adjustment as a TIME (X-Men's magnet/diverter were "no constant hold command");
        preset_drives.py sets them; X-Men Pro's magnet (dev 13, 255 for adj 182 ms then 82) in chain60 with TMNT
        LE on its slot's own NVRAM. c_land.py's evidence formats an adjustment time now.
      - Left running for the next run: chain57 (X-Men LE magnet/diverter/return post, X-Men Pro return post),
        chain56 (stack routes: Aerosmith LE, Guardians, Guardians LE, JB Pro, ST, ST LE, X-Men Pro), check13 (Jaws
        Pro event census), chain49 (media round 4). Land with c_verdict/c_land, st3_verdict + prove_set into
        STACK_RECORDS/FLAGS/BYTES_PROVEN (and copy that build's lines from st3/ports16 into its port), the census
        ids into jaws_pro's candidate port, media_verdict + scenes_prove (re-date round 4 by hand).
      - Batman 1.14's shots tied (33/43, autotie + 1.13's hand ties): 285861a8; chain55 proves light_shots.
      - Landed coils the C batch had proven but nobody landed: Foo Fighters LE (3), JP Pin gate, TMNT Pro pizza
        magnet (17f63898). Every PROVEN coil is in HELD_COILS_PROVEN now (checked).
      - **Coils the game drives only through objects of their own classes** (fill: "no constant hold command"):
        each class's constructor stores the DEVICE at +4 (`coils/classdev.py`), its coil_fire has the game's own
        powers - Batman LeftControlGate dev 16 (255/64, 96), TurntableDiverter dev 13 (255/64, 16), Rush LE
        DoubleUpPost dev 10 (adj 171/64, adj 172), John Wick LE RampDiverter dev 16 (adj 209/150, adj 210); X-Men
        LE's magnet / diverter / return post from constant-device commands the fill passed over (`preset_drives.py`
        into info.json). chain57 runs them (coil_job_c.sh).
      - **Stack's other modes on the ball-count titles**: the newest ports name the records and the flag table but
        left the ids out; st3/ports16 carries the older sibling's record ids (Aerosmith, Guardians) / mode flags
        (James Bond, Stranger Things) - NOT in the worktree until a stack run on each proves them (chain56,
        st3_job16.sh). X-Men Pro needs its mode objects' addresses (build-specific), Batman 1.14 its flags.
      - **Jaws Pro**: its 56 playfield switches had no names (35a2ab26: Jaws LE's names by the wire, each checked
        against Jaws Pro's own device table); its dispatch runs but none of Jaws LE's event ids come -
        `value event_census 1` (ed389422) logs the ids it does fire; check13 runs it.
      - Media round 3 landed Sword of Rage LE, Stranger Things LE (both), Rush Pro (screen); round 4 (chain49) has
        Rush, Star Wars (PRE_PRESS=pf), Batman 1.14, Venom Pro, Stranger Things Pro.
      - cardstage.sh stages a card only whole (1b52e9b1): a refused rename out of .inflight had left an EMPTY card
        that Munsters Pro's multiball job booted. chain43 re-runs that job with TAKE=2 (four balls home): its two
        runs went 2 -> 0 in play with four balls home, a four-ball game on the rig's six?
      - Hung WSL interop wrappers (robocopy.exe, powershell.exe under killgame.sh) still happen; killing the
        `/init /mnt/c/Windows/...` wrapper lets a batch go on (that build then fails staging and is re-run).
      - `tests/test_spike2_rig_slots.py::test_rigbatch_boots_staged_copies_and_reuses_them` fails under Git Bash
        (rigbatch.sh needs setsid); it passes in WSL - not a regression.
    * Run 18 (2026-10-08 08:50-): one rig until David's 09:00 "you can use more rigs now", then three (slots 2-4;
      slot 1 is PAD-455's). chain59/60 (waiting behind the serial chain) were replaced by chain61/62 at once.
      - Landed: Aerosmith Pro/LE 1.16 and Guardians LE 1.15 stack records (each start's ids + 4: Super Scoring
        named and the waiting mode refused), X-Men Pro's magnet (255 for adj 182 = 1000 ms, then 82).
      - **Mode flags moved by 5 on the newer framework**: Batman 1.14's (1.13's 58 / 71 -> 63 / 76) and Stranger
        Things 1.13's (1.12's 78 / 80 / 32 / 131 / 111 / 99 / 109 -> + 5). Each build's own set / clear / get are
        found by `coils/flagfuncs.py <key> <game_flags holder>` (Batman 1.14: set 0x488e90, clear 0x488e48, get
        0x488f28 - the 0x488ee0 of run 17 was inside the write function; ST 1.13: 0x2840ac / 0x284064 / 0x284144,
        ST LE 1.13: 0x4836e8 / 0x4836a0 / 0x483780) and `coils/flagwrites.py <key> <fn> [lo hi]` reads the flag
        each start sets. Batman 1.14's draft 86 / 88 were wrong; its episodes have flags too (51-60, each start
        asks first, sets, its stop clears), so its test port lists 12 (st3/ports16, Batphone Hurry Up's start left
        out of the test: it takes r0-r3 and sets none). Runs: chain63 (Batman, `STARTER=stack5.so`: the starts
        called with r1-r3 0), chain65 (ST, ST LE, Guardians Pro again - a multiball was on at its first ask).
      - X-Men Pro's block starts are METHODS: called with no object its Fastball Special segv'd. stack4.so now
        skips object-less starts on a title whose block lines name objects; its test port has `data block_obj_N`
        for the eight battles (running_objs.py's objects).
      - **D&D LE/Pro held coils**: their posts, diverter and magnet are objects of `cup_post` (device 11),
        `cdiverter` (14), `cmagnet` (13) - each constructor hardcodes its device at +8, and processes spawned with
        the object drive it: 255 for 64 ms then 128 to 1500 ms (posts, diverter: Mandalorian's proven gate's
        command), the magnet's grab 255 for 64 then 128 to 800 ms. `coils/cgen.py` PRESET stages them; chain64.
      - Magnet part (27 builds "has not found how X drives its magnet"): the held-coil alias works where a magnet
        coil is proven (X-Men LE/Pro, Munsters LE/Pro, TMNT Pro) but each also needs the shot its magnet sits at;
        Munsters' and TMNT's magnets have no place on the playfield map and X-Men's nearest switch is 67 px away,
        so their shot has to come from the switch the game's own magnet rule answers.
      - Later in run 18, all landed: stack on Batman 1.14 (Catwoman's start set flag 51), Stranger Things Pro / LE
        (Bullshit Scoring: flags 116 + 136), Guardians Pro, X-Men Pro (A Fiery Assault started with its object) -
        **stack is yellow only on Beatles now** (a song always runs: a game limit). D&D Pro / LE held coils and
        Mode > Magnet (the bottom right orbit opto, 24.5 px; `magnet/magnet_verdict2.py` allows the board's 10 ms
        ticks - a 64 ms draw shows as 60 - and a magnet whose own longest ends before the 1 s stop). Venom Pro's
        top post (ctop_post_device: the same post class code as D&D's). Scoops by their LE TWIN
        (`scoop/twin.py <src key> <src handler> <dst key>`: same first words, same event jump table, the one data
        word pointing at it): James Bond Pro (its game keeps a ball ~5 s itself, as the LE) and Aerosmith Pro.
        King Kong Pro's scoop lines already were its LE's twin - its segv under hook_dispatch is something else.
      - Magnets by their own classes (static objects: the device at +4, its own grab command): Beatles TopMagnet
        (device 15, 190 for 1000 ms then 22; TOP MAGNET OPTO 25 px away for Mode > Magnet), Led Zeppelin LE
        ElectricMagicMagnet (device 17, 255 for 2000 then 64 to 2500 ms; ELECTRIC MAGIC MAGNET OPTO), Aerosmith
        LE / Pro ToyBoxMagnet (device 17 / 16, 255 for 1000 then 16; the toy box switches). Staged by cgen PRESET,
        running (chain70, chain73). Rush's TimeMachineMagnet takes its device from its caller (not traced yet).
      - Those magnets' results: Aerosmith LE toy box, Led Zeppelin LE Electric Magic and Mandalorian LE Child magnet
        (cthe_child_magnet, device 14: 255 for 800 then 20) PROVEN and landed as held coils. Aerosmith Pro: the game
        pulses its own toy box magnet during our hold (taken). Beatles: the game sends an OFF 0.3-0.5 s into the
        first hold, twice - not landed. Staging lessons: the runtime reads the FIRST `text held_coils` line, so
        fill_c.py now drops the stage A port's own line (a port that already held coils kept only those, and the
        new magnets were never armed); `coils/c_verdict2.py` takes a hold the draw alone covers (the board's hold
        phase `0/255 for 0 ms`) as ours. Mode > Magnet on Mandalorian LE runs with the Child opto (the switch named
        for it; no place on the map) - chain77. Led Zeppelin LE's magnet opto is no port shot (its shots are the
        game's shot table), Aerosmith's toy box switch for the magnet not picked yet.
      - Not reachable this run: Metallica (its stage already has the loop post's own commands; only the game start
        fails - credits not counted after Guided Setup), Elvira (no game on the direct harness), TMNT LE (no game
        after its reboot; its up post / van diverter are not object-driven like D&D's), Jaws Pro (the game never
        serves a ball on the rig), Rush / Stranger Things Pro / Venom Pro clips (clip v2: the game draws the
        surface and the frame hand-over needs the player route's sites, never found on these).
    * Run 19 (2026-10-08 10:40-, up to three rigs):
      - **Lights on the LED-heavy builds**: `lights/lights_job2.sh` adds a later light_all window (step C, h_all)
        and `lights/judge2.py` counts the playfield INSERTS only - the cabinet's own lighting (expressive-lighting
        strip, speaker, backbox, topper lamps) takes only the game's shows, never ours, as Rush 1.18's proof
        counted. Rush LE / Pro PROVEN (17/17 RGB, every single-colour insert, shots 16/16 / 14/14), landed. The
        later window changed nothing elsewhere: it is not the game's top layer for a while. On John Wick LE / Pro,
        King Kong Pro and Foo Fighters Pro light_all misses inserts that light_shots (the same layer, a few
        seconds later) lights - King Kong Pro's shot inserts keep the game's blue under light_all and turn cyan
        under light_shots. Testing whether the cabinet lamp lines in the held set cause it: `lights/stage_ins.py`
        stages without them, `lights_job3.sh SUFFIX=_ins`, chain81. Avengers LE / Pro 1.10 show almost nothing of
        ours in any step (1.09 was proven 121/121); Mando Pro this run showed none of ours where run 16 showed
        8/13 - the LED view's read of it looks flaky.
      - Scoops via the mechanisms helper's lines on scoop_job4 (`scoop/stage19.py`, the switches mechs_conf now
        names): Batman 1.14's Penguin VUK and Deadpool LE's Hellhouse eject PROVEN, landed. James Bond 60th: the
        runtime held 4 s, but the game kicked at 5.1 s anyway - its kick runs outside that handler's event 2.
      - Batman 1.14 media: its census game ends at the first drain (the serve fault) and the mode game never
        started; `media/proof_job3.sh NOCENSUS=1` goes straight to the mode game (chain80).
      - Stranger Things Pro / Venom Pro clips: the clip plays (clip v2) but never shows over the HUD; their HUD
        profiles have no Video class measured, so the graft (Batman's, Metallica's route) is not open to them yet.
        Star Wars LE: the ball-start "choose your path / choose a hero" screen stays up over everything.
      - **Lights: the LED view, not the runtime.** On John Wick / King Kong Pro light_all missed inserts that a
        small hold lit (King Kong Pro: light_insert of its 9 shot inserts in magenta 9/9; light_all in cyan 0/9 -
        neither the colour, the mode's shots nor the cabinet lamp lines). A node-bus trace (`PAD_NB_TRACE=1`,
        `lights/buscheck.py`) showed our colour ON THE WIRE on all 9 in both light_all windows: holding many inserts
        makes the game send bulk frames the shim's padled plane does not publish. `lights/busjudge.py` judges from
        the wire (each frame to nodes 8/9 through leddecode; the windows from the runtime's own hold lines, the same
        clock; before / 1.5 s after) - the observable item mode-leds proved Godzilla's lights on. All eight left
        PROVEN and landed (4ed6d076): Avengers LE / Pro, Foo Fighters Pro, John Wick LE / Pro, King Kong Pro,
        Mandalorian LE / Pro. **Lights and lit shots are yellow on no newest build now.**
      - Batman 1.14 media PROVEN (NOCENSUS: screen, and the clip in its HUD graft) and landed; Deadpool Pro's
        scoop too (as the LE). Star Wars LE: the flippers drive its ball-start choice but nothing ends it.
    * Run 20 (2026-10-08 11:40-):
      - **Harness**: coins one at a time, 1 s apart (`coils/coil_job_c2.sh`, as PAD-306) - Metallica had counted 3
        of 8 dropped 0.7 s apart; its loop up post PROVEN (cdevice_loop_diverter, device 22: 170/32 then 68, 1032
        ms), landed. TMNT LE starts a game on FRESH NVRAM (not on the one a run leaves): pizza magnet PROVEN,
        landed; its check (check_job4) scored 25 shots, so its ball save runs through `jobs/wipe_then.sh JOB=bs_job.sh`.
        Jaws Pro: `jobs/check_job4.sh` leaves Guided Setup (`bs/guided.sh` after the tables, then a second boot) -
        but Jaws Pro's Guided Setup opens with the cursor in the language VALUES (English in cyan, the left row
        blinking), where `menurow.py` sees no menu and BACK does not leave it; `jobs/guided_probe.sh` walks it with
        SELECT, a frame per press (gprobe/).
      - **Clips grafted into the HUD** (the Pros / Rush draw no video bank in play, or draw it under the song
        video): each HUD's Video class and key read off the scene with `scene_tree.parse` - a free class id, one
        past the library's highest symbol key (the same reading gives Iron Maiden's measured (6, 103)): Stranger
        Things Pro (5, 56), Venom Pro (5, 21), Rush LE / Pro (6, 26); TITLE_SCENES bank = the HUD, the port's
        `scene video_bank` = the HUD scene, `value clip_surface_hide 1`. All four PROVEN (magenta 72-84%), landed.
        Clips are yellow only on Star Wars LE now (its ball-start choice screen never ends on the rig).
      - Harness, next: TMNT LE's stage A game runs, its stage B boot (same NVRAM) shows CREDITS 10 1/2 and ignores
        Start (balls the game still counts in the van?); Metallica counts 3 of 8 coins after Guided Setup (coins
        120 ms closed, 0.7 s apart); Elvira has no game on the direct harness.
      - **Every game now starts** with three harness rules, all in the scratch jobs (`*_job*.sh` with `wait_attract`):
        (1) coins one at a time, 1 s apart; (2) no coin or Start until `status.sh` says attract - Jaws Pro and Elvira
        show a tech-alert screen after each boot that ignores both for about a minute, and BACK / SELECT there opens
        the operator menu; (3) a title whose Guided Setup is slow to appear (Jaws Pro: about a minute after the version
        screen, its cursor pulsing) is left by `bs/guided.sh` retried every 15 s, or skipped: the NVRAM a passing run
        left is kept in `/home/david/pad420_nv/<title>` (copied as root, the guest's modes unreadable to david, then
        `chmod u+rwX`) and `jobs/seed2_then.sh` seeds a slot with it.
      - **Jaws Pro 1.02 ships a port** (6364624c): its full check passed (23 of 24 shots, a tilt, three balls, all
        seven events). Jaws LE's three upper-playfield shots are left out (a Pro has no upper playfield). Its inlane
        up posts PROVEN (c884bc9f: Jaws LE's getters found on the Pro by their code, `coils/jawsposts.py`; devices 12
        and 11). Then, each on the saved NVRAM: screen and clip (de669c71), stack (the table route, Cast N Catch 1),
        ball save (4719715c), multiball (9507ec4e), lights and lit shots (492dd26c, the shots on the node bus). **Jaws
        Pro is yellow only for shows now.**
      - **Elvira 1.13**: ball save PROVEN (4fb29522), its Crypt VUK scoop (a112d7b1), its control gate (273deb67: the
        same 24-virtual ControlGate as James Bond's, its static object at +0x80 of 0x87ed04). Elvira's frame grab
        works: the old note was wrong. Only shows and sound (David's questions) are yellow there now.
      - Foo Fighters Pro's van up post PROVEN (e84cb35b: the Pro has one of the LE's three; device 12, its command the
        twin of the LE's). Mode > Magnet on Uncanny X-Men LE / Pro PROVEN (1d66ce81, 54e94ded: their held magnet on
        the Right ramp tgt; the Pro's magnet ends at its own 1200 ms, so its stop came 0.4 s in - `STOP_IN`).
      - **Magnets still to do, and why** (Mode > Magnet needs a held magnet, its shot and a run):
        * no held magnet yet, the magnet a class of its own: Batman 1.14 TurntableMagnet (device 14), Guardians /
          Guardians LE OrbMagnet (16; LE 17 + left 15), Sword of Rage LE / Pro MagnaSaveMagnet (15), Rush LE / Pro
          TimeMachineMagnet (config at +0x24, device from its caller). The class's only constant command is
          "hold 16 for 5000" with no draw (`coils/magcls.py <key> <Class>`), plus 255-for-20 ms pulses from other
          functions: a 6% hold is how the game KEEPS a caught ball, not how it grabs one. Do not stage it as the
          grab: trace what the game sends when it uses the magnet (a rig run with PAD_COIL_PROBE through the
          feature that uses it) and take that.
        * held magnet proven, no shot: TMNT LE / Pro (pizza magnet 9:6), Munsters LE / Pro (9:7), Led Zeppelin LE
          (Electric Magic 9:7: its MAGNET OPTO makes no port shot). No place on the playfield picture. The magnet
          census (`magnet/magcensus_job.sh` + `magcensus.py`: every playfield switch pressed once in a game, the
          check object marking each, [coildrive] on the magnet after each press) found the game never fires TMNT
          LE's pizza magnet on a single press - it uses it inside a feature. Results for the others: chain115.
        * the game drives it itself (questions for David): Aerosmith Pro / LE toy box, Avengers LE / Pro tower, King
          Kong LE / Pro spider (pulses), Beatles top magnet (an OFF into our hold). Metallica's coffin magnet is
          never exposed (it flings the ball).
      - Metallica 1.04's scoop PROVEN (scoop_job6): its old "wrong handler" note came from a run with no game (fast
        coins). Its 32 GB card's staging failed once on a Windows lock at the move; the copy (head/tail md5 checked)
        was filed by hand. Munsters LE's magnet census had no game: 3 of 8 coins counted (CREDITS 3/4, coins a
        quarter each) with its state still techalerts after 3 min - a title needing more coins and a retry.
    * Run 21 (2026-10-08 14:03-):
      - Scoops are yellow on no newest build: James Bond 60th LE (f9026cfe: run 19's run read again on one clock -
        the hold kept the game's kick back; run 19 had compared the job's 5.1 s with the control's 3.3 s) and King
        Kong Pro (8cb33c65: its LE twin; run 18's segvs were the D: card stall, gone on the staged card). Star Wars LE
        screen and clip PROVEN (57a4a0ab): its ball-start hero / path choice is confirmed with the Action Button
        (`PRE_PRESS=34,34,34`); clips are yellow on no newest build either.
      - **Magnet census 2** (`magnet/magcensus2_job.sh`: `BTN` held 2 s three times, then every playfield switch;
        `magnet/magcensus.py <key> <node> <coil>` reads it; every [coildrive] line is kept): the GAME's own grabs -
        * Batman 1.14: the Bat Phone Target (shot 0x8000000000) made it fire its magnet (9:0) 255 for 1000 ms, then 16
          for 5000. The class's call asks for no draw (`coil_fire(dev, 0, 0, 16, 5000)`): the board uses the coil's own
          configured draw - so the static reading of these classes (Guardians, Sword of Rage, Rush) shows no draw.
        * Rush LE: the Lift ramp opto (0x400000) made it fire 9:7 255 for 80 ms, then 100 (for 20 s), OFF 2 s later.
        * Munsters LE: the Herman opto (0x40000) made it pulse its magnet (9:7) - the magnet's shot.
        * Sword of Rage LE / Pro, Led Zeppelin LE: only OFFs on the magnet (the magna-save is not lit at a game's
          start). Guardians / LE: only 255-for-60 ms pulses on the top magnet (after the lockdown button and the right
          scoop), no grab. TMNT LE / Pro: nothing on a single press (the pizza magnet is a feature's process: 0x129860,
          started by 0x129164 from the process 0xf51dc).
        cgen PRESET has Batman's and Rush's grabs; their held-coil runs (coil_job_c3) and then Mode > Magnet (Batman
        on the Bat Phone Target, Rush on the Lift ramp, Munsters on the Herman opto) are chain127 / chain129 / chain128.
      - bs_job2.sh's wait for attract comes BEFORE Guided Setup is left: on a fresh NVRAM its coins go in while the
        menu is up (TMNT LE: no game). Use it only on seeded NVRAM; bs_job.sh otherwise. TMNT LE's ball save with two
        balls stocked in the van (`PAD_BALL_VAN_STOCK=2`; the TMNT LE has 8 balls) is chain130.
      - Own music on Beatles / Deadpool LE / Pro: their carrier census found no stereo music request the game never
        plays (`mode_sounds._SWAP` music = ()): a game limit, with the sound question for David.
      - Landed later in run 21: held magnets at the game's own grab - Batman (44786692), Rush LE (01b04ad2), Rush Pro
        (589abac6), Beatles' top magnet (6547e750: its holds 25 s into the game, `coil_job_c3.sh SETTLE=25`; run 18's OFF
        was the game's ball-start release). Mode > Magnet: Beatles (dbffaa72: a new `switch 71` line for its Top magnet
        opto, flags 0x1400 like the standups'), Rush LE (2a8941da, the Lift ramp opto). TMNT LE's ball save (e61201a8:
        `PAD_BALL_VAN_STOCK=2`, `bs_job3.sh MAX_MIN=16`). Foo Fighters Pro's magnet section hidden (16643607: no
        Overlord magnet on a Pro). **Coils, scoops, screens, clips and ball saves are yellow on no newest build.**
      - Mode > Magnet where the GAME uses the magnet at that shot (the runtime gives way - "the game wants it" / "the
        game sent the coil a command of its own" - safe, but no clean hold to prove): Munsters LE / Pro (the Herman
        opto: the game pulses it), Batman (both the Bat Phone Target and Joker target 1, nearest on the picture), Rush
        Pro (the Center ramp opto; the retry 30 s into the ball met the same). Led Zeppelin LE: of its Electric Magic
        optos only the spinner's is broadcast (a trial with switch lines 80-82), and on it the game sends the magnet an
        OFF 1 ms after our grab - it keeps that magnet off outside its own feature. Metallica: COFFIN MAGNET DOWN may
        hold the coffin, not a ball (grave marker / electric chair fling) - a question for David whether its magnet
        section should be hidden.
      - Run 22, the magnets used only inside a feature: Guardians / LE (OrbMagnet), Sword of Rage LE / Pro (the
        MagnaSaveMagnet, a player's magna-save), TMNT LE / Pro (pizza magnet), Foo Fighters LE (Overlord magnet: no
        command at all in a game's census). None has a place on the playfield picture, and the game never used them on
        a single switch press or the lockdown button at a ball's start. Their classes' hold asks for no draw
        (`coil_fire(dev, 0, 0, 16, 5000)`); Batman's identical call went out as 255 for 1000 ms, but neither the coil
        record (coils/coilrec_probe.c: the 0x68-byte records carry no default) nor the boot configuration frames
        (coils/bootcfg_job.sh, PAD_NB_TRACE: node 9 coil 0's is power 255, time 0) holds the 1000 ms, so the draw is
        not read here for the others - each needs its feature run on the rig, or David's word on where the magnet sits.
      - **Light shows, run 22 pilot** (the last big yellow, 52 builds): `shows/scan_job2.sh` + `showbus_job.sh` play
        each candidate (pm_game_show) with the node bus traced; `shows/busshow.py` measures each from the bus. On
        Godzilla LE 1.16's ten NAMED shows: its lamps go out on node 14 (cmds 0x72 / 0x84-0x92 / 0xa6), not 8-11, and
        with every node decoded each show "moves" 140-190 channels against the 3.5 s before it - the game's own lamp
        animation never stops, so a before/after window cannot tell a show from the game (run 6's finding, now on
        exact data). PAD-411 measured its shows at the LIGHT RUNNER (`site light_run`): the commands the show's own
        process (show_proc) sends, which no other lamp of the game's touches. Next: that instrument (a hook on
        light_run logging the commands whose process is show_proc - not in the repo, PAD-411's was scratch), then per
        title the registry's candidates (`shows/cands`, `mkscan.py`) scanned with it, each named from what it sends
        (colours, how many lamps, how long) as PAD-411 named Godzilla LE's, and landed as `site show_<n>` + name /
        kind / secs lines.
      - **Light shows, run 23: the instrument, and the route for every build.** `C:/tmp/PAD-420/shows/rt` is a
        scratch copy of the runtime (never committed: SHOWS_MAX 400, N_SITES 1024 so a scan port can name every
        candidate) with two recorders, built as `shows/scanlog.so` / `scanlog2.so`: (a) a hook on the light
        runner (`site light_runner`, the target of `light_run`'s branch) logging each command the show process
        sends (`lightlog:`), and (b) a walk of the game's lamp groups every 3 ticks logging the levels of the
        groups the show process owns (a group's +16 is the process record that made it; `lampshow:`). The light
        language exists only on Godzilla 1.16, Jaws 1.02 and King Kong 0.97; the other 47 builds light their shows
        through lamp groups alone (Aerosmith's candidate 1: `lamp_group(0x60, ...)`, then 33 on/off steps 2 ticks
        apart). `shows/scan_job3.sh` plays every candidate (`mklog.py` ports, coins one at a time after attract,
        a candidate silent for 1.5 s stopped); `showname.py` (commands), `lampname.py` (lamp groups) and
        `finalname.py` (both) name each from its colours, strobe / fade / sweep / chase and length; on Godzilla
        LE's ten the kinds agree with PAD-411's. `landshows.py <key>` writes the port's block (at most 12 shows,
        one per name, flashy first). On the older framework the first recorder logged nothing: their process
        records are on the heap, outside the memory map the recorder read at load, so every group's owner looked
        unreadable; scanlog2.so re-reads the map once per walk (Aerosmith's candidate 1, silent before: a 24-light
        strobe in its own group). LE / Pro pairs share too little show code to scan one for both (`pairmap.py`:
        25-70% of candidates the same code), so every build is scanned.
      - **A leak in every show the runtime plays (since PAD-411), fixed: 072a46d4.** Every scan went dead 24-33
        candidates in (every show "over after 16 ms"); King Kong LE's candidate 22 played 120 times
        (`logports/kkle_rep22.port`, LAMPLOG 2 counting the groups) died after 26 plays as the game's lamp groups
        went 22 -> 48. A show the game starts itself is flagged 0x20 in its process record, and the game's exit
        (Godzilla LE 0x3f2d0c) then frees the groups it owns (0x1f3a68 -> 0x3a619c); the runtime's proc_create
        process is not flagged, so its groups stayed. The runtime now puts an exit hook in a free slot of the show's
        record (the game does the same for its own processes, e.g. 0x3f3e18) calling the game's free-by-owner;
        `shows/procexit.py` found both on all 55 builds. Proven: King Kong LE's rescan matches the old one for the
        first 23 and plays on past them.
      - Scans now: `shows/lane.sh` x3 (chainL1-3, `lane1-3.keys`, scanlog3.so = recorders + the fix, WAIT 10 s: a
        show still going at 10 s is offered for 8 s) over all 52 builds, the five light-language ones first. Then
        per build: `showname.py` (light-language builds), `lampname.py`, `finalname.py`, `landshows.py`, recipes,
        tests, commit. `shows/autoland.py` does the naming and landing of every finished scan; it also runs
        `showsafe.py` (a candidate whose direct calls reach the game's sound / callout / score / award / clip /
        coil / multiball / event sites is never offered: Godzilla LE's ten machine-tested shows reach none but a
        settings read) and `sibling.py` (a Pro's candidates that are its LE's landed shows - the same light-runner
        commands, or 75%+ of the same lights for as long - take the LE's names, so modes move between models;
        Godzilla Pro takes eight of PAD-411's names by `cmdmatch.py`); crash candidates (crashers.txt) are left
        out. Godzilla Pro's candidate 300 (Insert chase's match) killed the game during play: chainV1 replays it
        and 268 three times each after the retry lane (laneR: Elvira and Jaws Pro with their saved NVRAM; Jaws Pro
        started without it after all). Eight ports had no `site event_cancel` (no show could play: Avengers LE's
        first scan was all refused): `findcancel.py` found it in each, 45 references agreeing. From 19:00 the scan
        wait is 6 s (showlog4_job.sh), about a fifth faster; David asked about a GPU - no help, the shows play in
        the game's own real time - and whether to take the 4th rig is his call.
      - **Run 24 (2026-10-08 evening).** `shows/batch.sh <n>` waits for n scans, lands every finished one
        (autoland), rebuilds recipes, regenerates the "Which games" table (help_content now lists "light shows"
        in Also for a port that names them: 4ad15964) and runs the targeted tests; the commit stays by hand.
        Lane 2's long tail is shared with lane 4 (`lane4.keys`, the same builds from the end, after lane 1;
        `runs/<key>.lock` keeps them apart). Builds waited ~25 min each for their card copies (one copier, every
        build its own rigbatch): `shows/prestage.sh` (detached, log C:/tmp/PAD-420/prestage.log) copies each
        lane's next card ahead under the same copy lock and .src stamp, so rigbatch reuses it. TMNT LE starts a
        game only on fresh NVRAM (`wipe.titles`, wipe_then.sh): retry lane R (Elvira seeded, TMNT LE wiped) after
        lanes 1 and 3; chainV1 (Godzilla Pro's candidates 300 / 268 replayed) after R.
      - **Run 24 end: every latest build has the game's own light shows.** 47 ports land a PAD-420 block (plus
        Godzilla Premium/LE's PAD-411 ten): twelve on most; fewer where the game has fewer worth offering (James Bond
        60th six, Jurassic Park the Pin five, Star Wars ELG seven, Batman eight - no fade among them on the first
        three or on Aerosmith 1.16). A show lighting under 6 lights is not offered (fedca138). Godzilla Pro's Insert
        chase match (candidate 300) killed the game 3 of 3 replays (`runs/godzilla_pro-1.16.verify`), as did 268:
        neither is offered. Elvira's scan stopped at 310 of 340 after 13 crash restarts; its twelve come from those.
        TMNT LE starts a game only on fresh NVRAM with its van stocked (`PAD_BALL_VAN_STOCK=2`,
        `PAD_BALL_VAN_STOCK_AT=lower`), boots to Tech Alerts, and its game begins well after Start: scan_job3.sh now
        boots past Tech Alerts and takes `INGAME_WAIT` (90 s there; chainT.sh). Card copies were serialised behind
        one copier: `shows/prestage.sh` copied each lane's next card ahead, and `jobs/copy_watchdog.sh` freed a
        hung robocopy wrapper (Elvira's card). Not proven on a machine yet: the shows of builds other than Godzilla
        Premium/LE, and the lamp-group clean-up (072a46d4) - the next machine test of any build with shows should
        play a dozen mode starts/ends in one game and see the game's own lighting stay right.
        The clean-up proven again with the SHIPPED runtime source (scanship.so: the SDK's pad_mode_runtime.c and
        mode_file.c, no recorders; chainS.sh): King Kong LE's candidate 22 played 63 times in one game (the
        runtime's SHOWS_MAX caps a port at 63; the other 57 were refused for that), every play running until the
        scan stopped it - where before 072a46d4 every play from the 27th died at once.
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
| lights | the new builds whose `lamp` lines are not yet tied (Pro siblings of an LE port), and `LAMPS_PROVEN` for all 32 | the lights helper's branch `ticket/PAD-420-lights` ties 15 shipped builds' inserts to their shots: on main as 740ee80c (its lamp lines and test identical), and all 15 are in `LAMPS_PROVEN` (PAD-483) |
| shows | none left: every latest build names the game's own light shows (run 24; TMNT LE the last) | done in the emulator; a machine test of a non-Godzilla build's shows and of the lamp-group clean-up is the open proof |
| scoop | proven (run 7) on Avengers LE 1.10, D&D LE 1.10, Guardians LE 1.15, Iron Maiden LE 1.18, Aerosmith LE 1.16 (the mechanisms helper's runs); 25 more staged (chain19) | Deadpool LE/Pro and James Bond Pro: the handler never saw a settled ball (a call probe of the device's handler next); Aerosmith Pro, Batman, JB 60th: the job closed the wrong switch (fix `mechs_conf.SCOOP`) |
| held coils | PROVEN (run 8-9, `HELD_COILS_PROVEN`): Led Zeppelin Pro 1.22, Star Wars ELG 1.10, Sword of Rage LE/Pro 1.19, Deadpool LE 1.16 (their gates; generation B, the board-address route with the object taken). Re-running (chain23): Deadpool Pro, Led Zeppelin LE, Iron Maiden LE/Pro (up posts), Avengers LE/Pro (tower magnet, tower post), Jurassic Park LE/Pro (T-Rex magnet, up posts) | A' and B are staged; C (the Device framework, most titles) needs the powers its gate service uses read first (docs/plans/mode_coils_census.md). Every hold power is the game's own |
| magnet (Mode > Magnet) | Godzilla only | the magnet part also needs `magnet_shot`; a title's magnet can be offered as a held coil first |
| shaker | Godzilla LE only (PAD-414); the other latest builds with a shaker are PAD-474 | `ticket/PAD-420-shaker` duplicated PAD-414's runtime and was deleted (PAD-483); its desk reader `shaker_lines.py` (the game's own shake routine on any build) is noted on PAD-474 |
| countdown | Aerosmith, John Wick, Elvira: the voice never says a number | `COUNTDOWN_NO_NUMBERS`: decide with David whether a countdown there is a number on screen only, with the section saying so in grey |

Helper branches from the first run (pushed, not merged): `ticket/PAD-420-lights`, `ticket/PAD-420-balls` (a runtime
guard: a port's mode table that is not the game's is left out instead of crashing it; changes the prebuilt object,
needs a library sweep before it lands), `ticket/PAD-420-mechs` (WIP), `ticket/PAD-420-shaker` (superseded by PAD-414).

**PAD-483 (2026-10-09) landed or retired all four.** All four heads are kept in `C:/tmp/PAD-483/pad420-helpers.bundle`
(`git fetch <bundle> refs/remotes/origin/ticket/PAD-420-<name>:refs/heads/<name>` brings one back).
- `lights` (51a62936): on main as 740ee80c (the same lamp lines and test), and its reader fix as d1b86d37; all 15
  builds are in `LAMPS_PROVEN`. Deleted.
- `mechs` (7263ce38, WIP): every piece is on main - `COIL_ROUTE_NEEDS`, `_drive_ok`, the runtime's board-address
  route (route 1, `coil_drive`, `coil_disabled`, `c->ctl`) - and proven on the builds in `HELD_COILS_PROVEN`. Deleted.
- `shaker` (268ef0d3): its runtime duplicated PAD-414's (on main, Godzilla LE). Deleted; its desk reader
  `shaker_lines.py` (the game's own shake routine, found by `AD_SHAKER_MOTOR` and its error text, on any build) is
  noted on PAD-474 with the restore command.
- `balls` (40807736): NOT on main, and still needed - `port_derive` still copies `value stock_mode_count` from another
  title (it counts as a framework value). Landed on ticket/PAD-483 (d95b8be5) with one fix, then the helper branch
  and its worktree deleted:
  * **The crash it guards, reproduced** (Venom LE 1.07, main's runtime, `C:/tmp/PAD-483/runs`): a port with the table
    count 160 (94 real), another title's table address, or a code address: all three games segfault in `stock_class`
    (pad_mode.so +0x7f10 / +0x7f7c) as the first ball starts. With the guard all three play the check to the end.
  * **The first cut was wrong on real tables** - the "library sweep" caveat was right: it asked the ACTIVE slot before
    the class, and a real table holds the title's other rules too (30 of Venom LE 1.07's 94 entries are crule
    objects - lanes, bonus, skill shot - with shorter vtables). On Venom's own port it left 19 of them out as "not a
    mode object" and counted them toward turning the route off. Fixed (04902924): the object and its typeinfo word
    first, then the class, and only a MODE's slot must be code; a rule is class 0 as before the guard.
  * **The three wrong tables again, with the fix** (`C:/tmp/PAD-483/runs2`): the count past the table (160) - 57 of
    the 66 words past it left out, the route kept for the 94 real entries (its base-play modes named as usual); a
    code address - 48 left out and the route turned off ("the port's mode table is not this game's"); another
    title's table address - its entries are objects here, none of them a mode (class 0): nothing called, nothing
    said, and the route sees no game mode running (a quiet answer, not "cannot tell"). All three play the check to
    the end; main's object segfaults on all three.
  * **Library sweep**: every one of the 43 shipped ports that carries a mode table takes the table route (none names
    both of the manager's sites), so the walk runs on all of them. `jobs/guard_job.sh` (`C:/tmp/PAD-483/rb_sweep`,
    the log `rb_sweep.log`): the port and the fixed object staged, the title's NVRAM fresh, Check this game; pass =
    the check passed and the guard said nothing. The table's readability is checked every tick, in attract too, so all
    43 say their table is readable here. The entries themselves are checked while a game is on (every entry at the
    ball's start), so a build counts only when its check played a game:
    - Round 1 (all 43): 34 passed; TMNT LE 1.59 played 20 of its 29 switches and the guard said nothing (its check
      then never saw a drain end a ball - the ball saver kept giving it back). 35 proven.
    - The other 8 never started a game. Not the guard: the table read as readable, and they sat in attract, Tech
      Alerts, or the game the check's own Save & Exit had left hung (that Save & Exit restarts the game). Round 2
      (`guard_job2.sh`, the title's EEPROM image set aside: it is shared by every build of a title on a slot)
      changed nothing - Guided Setup came back after each Save & Exit. Round 3 (`guard_job3.sh`, PAD-420's
      harness rules: Guided Setup left by `bs/guided.sh`, the stage booted AGAIN, coins one at a time): Avengers LE
      1.09, Iron Maiden LE 1.16, Mando LE 1.44, Rush LE 1.18, Sword of Rage LE 1.18 and Pro 1.19 all played their
      check (20 to 40 switches, a ball drained) with nothing left out. 41 proven.
    - D&D LE 1.10 and 1.00 start no game on today's rig, with the fix OR with main's object (the control,
      `C:/tmp/PAD-483/rerun6`), on a fresh NVRAM, a seeded one (slot 4's, `jobs/guard_job5.sh`) or with no ball reset
      (`jobs/guard_job6.sh`): in attract the game ejects a ball and auto-plunges it every ~8 s, the feeder brings it
      home "untouched", and the game never takes Start (`padball.log`; the feeder's notes on D&D LE's attract search,
      `ballfeed.py`, say it should settle - here it never does). PAD-420's D&D LE 1.10 check on 2026-10-07
      (`C:/tmp/PAD-420/check7`) DID play, on the same table (0x00717758, 75 entries, slot 56) with the unguarded walk:
      no crash, its base-play modes named. The fixed guard refuses only what that walk could not have followed (an
      unreadable or misaligned object or typeinfo word; a mode whose ACTIVE slot is not code), so D&D LE 1.10 is
      covered by that run. D&D LE 1.00 (not the latest build) has no game on record anywhere: only its table's
      readability is proven. The D&D LE rig start is its own problem, for a ticket of its own.
    So **42 of the 43 proven** (41 in a game with the fix, D&D LE 1.10 by its unguarded game), D&D LE 1.00 readable
    only. Jobs and logs: `C:/tmp/PAD-483/jobs`, `rb_*` and `rerun*`.
