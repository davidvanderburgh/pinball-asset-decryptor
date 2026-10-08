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
    * Metallica 1.04: a game IS on screen (PLAYER 1, credits taken) but mode.log never sees in_game - the port's
      `data mode_mask 0x07000012` / busy 0x210 stays busy, as on Jaws Pro. Added to chain33's mask probe (its port
      copied to C:/tmp/PAD-420/clean/). Every Metallica mode feature waits on this.
    * Lights (11 builds): their inserts sit in LED-only device-table groups (King Kong Pro group 1 = "EXPRESSIVE
      LIGHTING" 96 RGB, group 9 = 227 channels) with no connector named, so coilmap.group_node cannot join them to a
      bus node (it joins on switch names) and the LED view draws them dark; the title's node directory has four
      ws2812node boards (King Kong Pro nodes 2, 7, 12, 14) they must belong to. Emulator work (the LED view, PAD-311's
      area): map an LED-only group to its ws2812 node by what the game sends each node.
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
| shows | every title but Godzilla Premium/LE (50 builds; the largest part left) | run 9: no static test picks a title's shows out. On Godzilla LE 304 of the 329 lamp-lighting process bodies have a show's own shape (show_priority, then lamp_group, then a player: `C:/tmp/PAD-420/shows/showsig.py`), the ten known shows rank anywhere by size, and the game's show_start ids are another kind of show (`showids.py`). So each build's ~70-340 registry candidates (`shows/cands/<key>.json`) are played one by one and measured at the LED view - 6-8 s each with a quiet baseline before, the biggest movers kept, each named from what it does (its colours, strobe / fade / chase) - about 30-40 rig-minutes a build, ~10 rig-hours for all; not possible on the 11 builds whose inserts the rig has no board for (the lights row). `shows/scan_job.sh` and `mkscan.py` exist; the judge needs the longer windows and the naming |
| scoop | proven (run 7) on Avengers LE 1.10, D&D LE 1.10, Guardians LE 1.15, Iron Maiden LE 1.18, Aerosmith LE 1.16 (the mechanisms helper's runs); 25 more staged (chain19) | Deadpool LE/Pro and James Bond Pro: the handler never saw a settled ball (a call probe of the device's handler next); Aerosmith Pro, Batman, JB 60th: the job closed the wrong switch (fix `mechs_conf.SCOOP`) |
| held coils | PROVEN (run 8-9, `HELD_COILS_PROVEN`): Led Zeppelin Pro 1.22, Star Wars ELG 1.10, Sword of Rage LE/Pro 1.19, Deadpool LE 1.16 (their gates; generation B, the board-address route with the object taken). Re-running (chain23): Deadpool Pro, Led Zeppelin LE, Iron Maiden LE/Pro (up posts), Avengers LE/Pro (tower magnet, tower post), Jurassic Park LE/Pro (T-Rex magnet, up posts) | A' and B are staged; C (the Device framework, most titles) needs the powers its gate service uses read first (docs/plans/mode_coils_census.md). Every hold power is the game's own |
| magnet (Mode > Magnet) | Godzilla only | the magnet part also needs `magnet_shot`; a title's magnet can be offered as a held coil first |
| shaker | none here | PAD-414 (awaiting approval) adds the shaker part; `ticket/PAD-420-shaker` is a duplicate and is not merged |
| countdown | Aerosmith, John Wick, Elvira: the voice never says a number | `COUNTDOWN_NO_NUMBERS`: decide with David whether a countdown there is a number on screen only, with the section saying so in grey |

Helper branches from the first run (pushed, not merged): `ticket/PAD-420-lights`, `ticket/PAD-420-balls` (a runtime
guard: a port's mode table that is not the game's is left out instead of crashing it; changes the prebuilt object,
needs a library sweep before it lands), `ticket/PAD-420-mechs` (WIP), `ticket/PAD-420-shaker` (superseded by PAD-414).
