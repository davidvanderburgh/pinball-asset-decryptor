# PAD-643: a mode's challenge ball launched for the player, and started as every other ball

luvthatapex (Bond LE), on the two challenges of his own (PAD-615 round 2): "autoplunge at start after initial movie
plays or a set time", and "allow diverter to open the main loop when plunging if left flipper is held in like every
other start of ball". MODE_SDK.md "A mode in the game's Challenge list" has the design; this file is the work list.

## Done (run 1, 2026-10-20, commits d2905595, 47c67950)

- Cause of the diverter: Bond's skill shot set-up on the ball's serve (bus 34, LE `0x18dd50`, Pro `0x18c560`) asks
  `FG_PLAYER_CHALLENGE_MODE_ACTIVE` first and skips everything in a challenge game - the super skill shot's process
  (353, body `0x18d198`) that keeps `0x81eb90 + 10` at 3904 while the left flipper button is held, and so the
  launch path's gate decision `0x1aff18` (`0x18db00` armed -> take the top control gate `0x81fad8`, device 9 coil 6).
- Runtime: `site challenge_plain_<k>` wrapped with the challenge flag cleared for the call in a mode's challenge game;
  `site ball_launch` (framework launch-button handler, bus 197) called from the tick once the mode's start clip is
  over / a set time / never (`pm_challenge_launch`). `value ball_launch_flag` / `ball_launch_wait_flag` (12 / 13 on
  most builds, 11 / 12 on the older ones).
- portchallenge.launch_lines (61 of 61 challenge builds, one hit each), plain_lines (Bond LE / Pro only); the shipped
  ports carry them (C:/tmp/PAD-643/addports2.py), derived ports get them from find().
- Mode file `challenge_launch`, Modes tab row "its ball launched", blocks hat `launch`.
- Tests: tests/test_pad643_challenge_launch.py (Windows; the mode-file harness ones run in WSL Ubuntu).
- Emulator, Bond LE 1.06 (C:/tmp/PAD-643: proof.sh, run_a1.sh after / run_b1.sh main, rig/ch643.c, e2e_build.py with
  the owner's BON APPETIT blocks as its own challenge): after - flag 156 + left-flipper word 3904 at the serve, auto
  plunger (node 8 coil 4) 2.0 s after the mode began, the top control gate (node 9 coil 6) pulsed + held 20 s 100 ms
  after the launch. Before - none of it, the ball still in the lane 70 s on.

Also proven (run 1): Bond LE `launch player` (run_player.sh: no launch), `launch 6` (run_t6.sh: +6013 ms), a 4 s
start clip (run_clip.sh: launched at +4544 ms, as it ended); Bond Pro 1.06 (run_pro.sh, proof_pro.sh, rig_pro/:
skill shot wrapped, launch +2010 ms, gate 100 ms later with the left flipper button 63 held).

## Left

1. Every other build with challenges (59): a rigbatch sweep from PAD-619's kit (C:/tmp/PAD-619 job619.sh +
   proof619d.sh, stage_menu mode files, RIGSRC -> this worktree) WITHOUT the `plunge` step after Start, verdict
   "challenge ball: launched for the player" in mode.log (and the auto plunger's coil in gzwatch.log, PAD_COIL_PROBE=1).
   Builds whose menu cannot be driven get the Default Game Mode route (PAD-615 memory) or the game-play index.
2. A `CHALLENGE_LAUNCH_PROVEN` note per build in mode_project.py (comment, like CHALLENGE_MENU_PROVEN) once swept.

## Sweep so far (paused 2026-10-20 for David's disk clean-up)

Kit: C:/tmp/PAD-643/sw (PAD-619's jobs on this worktree's runtime and ports; chain643*.sh, lists ?643_*.txt, verdict643.py
reads each build's newest out_*/mode.log for `challenge ball: launched for the player`). Rigs released, nothing running.
At 4x (David's ask) the start-menu jobs' flipper steps never landed on our entry (Guardians LE 1.14, Munsters LE): run
menu builds at --speed 1; the game-play-mode builds (no menu) at 4x. /mnt/c/tmp/PAD-420/bs/guided.sh (the Guided
Setup walk the jobs call) had been pruned; rebuilt from modes/gamecheck.sh's guided_setup.

Launched for the player on 39 of 59 (plus Bond LE / Pro). Led Zeppelin LE / Pro 1.22: nothing to launch - the
challenge game's first ball goes to the shooter lane for the player's plunge (the auto plunger flags never set), the
game launches later balls itself; the runtime says so. Per build:

```
aerosmith-1.16               PASS started=1  launched for the player (its start clip over, 1515 ms after its mode began)
aerosmith_le-1.15            PASS started=1  launched for the player (its start clip over, 1516 ms after its mode began)
aerosmith_le-1.16            PASS started=1  launched for the player (its start clip over, 1504 ms after its mode began)
avengers_infinity_le-1.09    (not run yet)
avengers_infinity_le-1.10    PASS started=1  launched for the player (its start clip over, 7601 ms after its mode began)
avengers_infinity_pro-1.10   PASS started=1  launched for the player (its start clip over, 7565 ms after its mode began)
batman-1.13                  PASS started=1  launched for the player (its start clip over, 2515 ms after its mode began)
batman-1.14                  PASS started=1  launched for the player (its start clip over, 2012 ms after its mode began)
beatles-1.29                 PASS started=1  launched for the player (its start clip over, 1500 ms after its mode began)
deadpool_le-1.14             PASS started=1  launched for the player (its start clip over, 1501 ms after its mode began)
deadpool_le-1.16             PASS started=1  launched for the player (its start clip over, 4788 ms after its mode began)
deadpool_pro-1.16            PASS started=1  launched for the player (its start clip over, 1513 ms after its mode began)
elvira3-1.13                 (not run yet)
foo_fighters_le-1.04         PASS started=1  launched for the player (its start clip over, 1500 ms after its mode began)
foo_fighters_pro-1.04        PASS started=1  launched for the player (its start clip over, 1500 ms after its mode began)
godzilla_le-1.16             PASS started=1  launched for the player (its start clip over, 1516 ms after its mode began)
godzilla_pro-1.15            PASS started=1  launched for the player (its start clip over, 1515 ms after its mode began)
godzilla_pro-1.16            PASS started=1  launched for the player (its start clip over, 1516 ms after its mode began)
guardians-1.15               PASS started=1  launched for the player (its start clip over, 1505 ms after its mode began)
guardians_le-1.14            ---- started=0  
guardians_le-1.15            PASS started=1  launched for the player (its start clip over, 1507 ms after its mode began)
iron_maiden_le-1.16          (not run yet)
iron_maiden_le-1.18          PASS started=1  launched for the player (its start clip over, 1504 ms after its mode began)
iron_maiden_pro-1.18         PASS started=1  launched for the player (its start clip over, 1513 ms after its mode began)
jaws_le-1.02                 PASS started=1  launched for the player (its start clip over, 1508 ms after its mode began)
jaws_pro-1.02                PASS started=1  launched for the player (its start clip over, 1515 ms after its mode began)
john_wick_le-1.01            (not run yet)
john_wick_le-1.02            (not run yet)
john_wick_pro-1.02           PASS started=1  launched for the player (its start clip over, 2015 ms after its mode began)
jurassic_park_le-1.16        (not run yet)
jurassic_park_pro-1.16       (not run yet)
jurassic_park_the_pin-1.05   PASS started=1  launched for the player (its start clip over, 1513 ms after its mode began)
led_zeppelin_le-1.22         ---- started=1  no ball waited in the plunger - the player launched it
led_zeppelin_pro-1.22        ---- started=1  no ball waited in the plunger - the player launched it
mando_le-1.44                (not run yet)
mando_le-1.45                (not run yet)
mando_pro-1.45               (not run yet)
metallica_spike-1.03         (not run yet)
metallica_spike-1.04         PASS started=1  launched for the player (its start clip over, 1505 ms after its mode began)
munsters_le-1.28             ---- started=0  
munsters_pro-1.28            PASS started=1  launched for the player (its start clip over, 4017 ms after its mode began)
rush_le-1.18                 (not run yet)
rush_le-1.19                 (not run yet)
rush_pro-1.19                ---- started=0  
star_wars_elg-1.10           PASS started=1  launched for the player (its start clip over, 1516 ms after its mode began)
star_wars_le-1.30            (not run yet)
star_wars_le-1.31            PASS started=1  launched for the player (its start clip over, 1503 ms after its mode began)
star_wars_pro-1.31           PASS started=1  launched for the player (its start clip over, 1507 ms after its mode began)
stranger_things-1.13         PASS started=1  launched for the player (its start clip over, 5563 ms after its mode began)
stranger_things_le-1.12      PASS started=1  launched for the player (its start clip over, 5577 ms after its mode began)
stranger_things_le-1.13      PASS started=1  launched for the player (its start clip over, 5581 ms after its mode began)
sword_of_rage_le-1.18        (not run yet)
sword_of_rage_le-1.19        PASS started=1  launched for the player (its start clip over, 1507 ms after its mode began)
sword_of_rage_pro-1.19       PASS started=1  launched for the player (its start clip over, 1509 ms after its mode began)
turtles_le-1.59              PASS started=1  launched for the player (its start clip over, 1509 ms after its mode began)
turtles_pro-1.58             PASS started=1  launched for the player (its start clip over, 1511 ms after its mode began)
turtles_pro-1.59             PASS started=1  launched for the player (its start clip over, 1500 ms after its mode began)
venom_le-1.07                PASS started=1  launched for the player (its start clip over, 1500 ms after its mode began)
venom_pro-1.07               PASS started=1  launched for the player (its start clip over, 1516 ms after its mode began)
launched: 39 of 59
```

**Left - NEWEST build of each title only** (David, 2026-10-20: older versions are archival, never swept or used):
elvira3-1.13, john_wick_le-1.02, jurassic_park_le-1.16, jurassic_park_pro-1.16, mando_le-1.45, mando_pro-1.45,
rush_le-1.19, and reruns of munsters_le-1.28 (the rig's Start never began the game: credits stayed at 2) and
rush_pro-1.19 (the menu did not open without Guided Setup's walk). Re-derive the newest-build list before resuming;
the older versions above (Avengers LE 1.09, Guardians LE 1.14, Iron Maiden LE 1.16, John Wick LE 1.01, Mando LE
1.44, Metallica 1.03, Rush LE 1.18, Star Wars LE 1.30, Sword of Rage LE 1.18) are out.
