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

## Where the 32 new ports stand (end of run 2, 2026-10-07 09:45)

- **Shipped, full build check passed (15):** Aerosmith LE 1.16, Avengers LE and Pro 1.10, Deadpool LE 1.16,
  Dungeons & Dragons LE and Pro 1.10, Foo Fighters Pro 1.04, Guardians Pro and LE 1.15, Iron Maiden LE and Pro 1.18,
  James Bond Pro 1.06, John Wick LE 1.02, Star Wars Pro 1.31, Stranger Things LE 1.13.
- **Still in the emulator when the run ended, or not yet re-run on a quiet machine (13):** John Wick Pro 1.02,
  Jurassic Park Pro 1.16, King Kong Pro 0.97, Mandalorian LE and Pro 1.45, Venom Pro 1.07, Uncanny X-Men Pro 0.98,
  Sword of Rage LE and Pro 1.19, Star Wars LE 1.31, Stranger Things Pro 1.13, Munsters Pro 1.28, Aerosmith Pro 1.16.
  Most of these failed only with the game's 10 s watchdog (exit 5) while the machine was over-committed (below).
  Their candidate ports are `C:	mp\PAD-420\clean\<key>.port`; the results land in `C:	mp\PAD-420\check3\<key>`.
- **Real faults to look at:** Batman 1.14 (no drain ends a ball on any of its ports: it moved to the newer
  framework, so its end-of-ball event ids and handler need proving), Jaws Pro 1.02 (no game starts after Guided
  Setup, twice), Rush LE / Pro 1.19 (stopped or crashed on every quiet-machine try so far; the 191 MB debug program).

**Lesson for the next run:** the previous run's helper agents left jobs running in WSL after they were stopped (a
shaker proof, a ball-save pilot, a light-show scan, a mechanisms proof). They held a fourth rig, the machine feeds
three, and every check on the starved rigs died on the game's own watchdog. Before a batch: `riglock.sh list`, and
stop anything not yours; run nothing CPU-heavy (pytest, screenshots, recipes with 4 workers) while rigs run.

Tools (scratch, `C:	mp\PAD-420`): `jobs/check_job2.sh` (the check per build), `run_check3.sh` (rigbatch),
`stamp.py <key>...` (the proof header, from check3), `recipes.py` (`RW=1` for one core), `portslist.py` (the test's
port list), `limits_table.py` (MODE_LIMITS.md's games table), `clean2.py` (how a candidate port is made).

## Left, per part (the next runs)

| part | what is left | how |
|---|---|---|
| screen, clip | the 32 new builds: a screen and a clip seen on the glass | `TITLE_SCENES` `screen_proven` / `clip_proven`; the item-164 proof (a mode with a screen and a clip, `glshot.sh`) |
| multiball, ball save, stack | the 32 new builds (plus Elvira, Venom LE, TMNT LE, Godzilla LE ball save) | `MULTIBALL_PROVEN`, `BALL_SAVE_PROVEN`, `STACK_BALLS_PROVEN`: `C:\tmp\pad_generic\mb\mb_batch.sh`, `bs\bs_job.sh` through `rigbatch.sh` |
| lights | the new builds whose `lamp` lines are not yet tied (Pro siblings of an LE port), and `LAMPS_PROVEN` for all 32 | the lights helper's branch `ticket/PAD-420-lights` ties 15 shipped builds' inserts to their shots (desk; its emulator trials failed to boot, not yet proven) |
| shows | every title but Godzilla Premium/LE | per title: the show processes in its registry, each played by `show_reel_mode.c` and measured at the LED view (MODE_SDK.md "The game's own light shows"); scratch in `C:\tmp\PAD-420\shows` |
| magnet, scoop, held coils | every title outside generation A (census: docs/plans/mode_coils_census.md) | A' and B: align the ControlCoil vtable slots; C (the Device framework, most titles): `ticket/PAD-420-mechs` has an unbuilt, unproven WIP that holds a coil by its node-board address |
| shaker | none here | PAD-414 (awaiting approval) adds the shaker part; `ticket/PAD-420-shaker` is a duplicate and is not merged |
| countdown | Aerosmith, John Wick, Elvira: the voice never says a number | `COUNTDOWN_NO_NUMBERS`: decide with David whether a countdown there is a number on screen only, with the section saying so in grey |

Helper branches from the first run (pushed, not merged): `ticket/PAD-420-lights`, `ticket/PAD-420-balls` (a runtime
guard: a port's mode table that is not the game's is left out instead of crashing it; changes the prebuilt object,
needs a library sweep before it lands), `ticket/PAD-420-mechs` (WIP), `ticket/PAD-420-shaker` (superseded by PAD-414).
