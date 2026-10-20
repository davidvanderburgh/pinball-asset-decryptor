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

## Left

Also proven (run 1): Bond LE `launch player` (run_player.sh: no launch), `launch 6` (run_t6.sh: +6013 ms), a 4 s
start clip (run_clip.sh: launched at +4544 ms, as it ended); Bond Pro 1.06 (run_pro.sh, proof_pro.sh, rig_pro/:
skill shot wrapped, launch +2010 ms, gate 100 ms later with the left flipper button 63 held).

1. Every other build with challenges (59): a rigbatch sweep from PAD-619's kit (C:/tmp/PAD-619 job619.sh +
   proof619d.sh, stage_menu mode files, RIGSRC -> this worktree) WITHOUT the `plunge` step after Start, verdict
   "challenge ball: launched for the player" in mode.log (and the auto plunger's coil in gzwatch.log, PAD_COIL_PROBE=1).
   Builds whose menu cannot be driven get the Default Game Mode route (PAD-615 memory) or the game-play index.
2. A `CHALLENGE_LAUNCH_PROVEN` note per build in mode_project.py (comment, like CHALLENGE_MENU_PROVEN) once swept.
