# PAD-1400: a mode that is the whole game

Rows 1, 3 and 6 of the PAD-1398 gap analysis (docs/plans/pad1398_xmen20_gap_analysis.md): a maker building a whole
new game on Stern's own board and program (20SidedDies' Uncanny X-Men 2.0) needs Stern's rules switched off under
his mode, every point his own, and a mode that does not end at a drain.

## What it is

- **`pm_own_game(on)`** (pad_mode.h, pad_mode_runtime.c, "the whole game"). While the running mode has it and a ball
  is in play, the game's OWN calls are refused at the entry of sites every Spike 2 port names:
  - `shot_dispatch`: the game's rules hear no shot (the veto hands the shot to our modes' `.shot`).
  - `score_add` / `score_add32`: no points of the game's.
  - `callout` / `callout_nth`: no calls (on Uncanny X-Men `sound_play` is the same function: no sound requests).
  - `multiball_serve`: no multiball or rule ball save of the game's.
  - `award_screen`: no award screen or video of the game's.
  - `show_start`: no light show of the game's (a show of ours, `pm_game_show`, still plays: its process is the
    game's code, so `show_start` passes while it runs).
  A refused call answers 0, as each function's own failures do. It also holds the game's modes and rules off as
  `pm_block_game_modes(1)` does.
  A call is the game's when its return address is outside our object and none of our own calls into the game is
  running (`OG_SELF` around the runtime's serve, award-screen and show calls). `display_effect_start` (the score
  display's own effects, ~200 a ball) and `sound_play` (sound effects, music beds) are hooked to COUNT the game's
  calls only. The vetoes go in on the first `pm_own_game(1)`, on top of a logger already hooked at the same site
  (`og_chaining`: only these vetoes may; every other veto is refused there as before).
- What stays the game's: ball handling, trough, ball search, tilt (3 s from the `tilt_warning` bus event, and a
  tilted ball to its end), node bus, display, audio, each ball's start up to its first switch, the end of each ball,
  and the end of the game with its high-score entry.
- **`game_modes own_game`** (mode_file.c): valid with no trigger or clock; starts on the game's first tick; runs
  through every drain and every player's turn, each player's hits and total kept; ends with the game.
- **Blocks**: "are off: this is the whole game" (`GAME_MODES 3` in the generated C): the same lifetime.
- **Modes tab**: the fourth choice under "The game's own modes" on a form mode and in the Blocks editor, offered
  where the title's port names a score and a callout site and its mode starts (`Profile.own_game`: all 71 Spike 2
  profiles).

## Proof

Emulator, Uncanny X-Men LE 0.98 (rigs 3 and 5, hidden, muted, 4x), a two-player game, every named shot scoring
1000 (fixed), the same 30-odd playfield switches pressed each ball (C:/tmp/PAD-1400/ownjob.sh):

- Whole-game run: `own game: armed on shot_dispatch, score_add, callout, callout_nth, multiball_serve, ...`; the mode
  started with the game; at each ball's end `the whole game's mode runs on (player 1: 27 hits, awarded 27000, score
  27000)`; per ball the game's 27-32 shots, 28-34 point awards and 18-26 calls were refused; player 2's first ball
  started fresh and each player resumed their own count (27 -> 54 -> 81 hits); `END (the game is over)` after
  ball 6 with the game's rules given back.
- Control (the same mode as an ordinary `stack` mode): the game scored 5,880,640 on one ball where the mode
  awarded 80,000.

## The game's bonus, and what still came through (Uncanny X-Men LE 0.98, disassembled)

With the shots, points and calls held back, a run that logged where the game's remaining calls came from showed,
per ball: award screens from 0x481b9c (a task trampoline: effect 50 or 7), light shows from 0x2ef614 (a lamp-show
rule watching the game-state mask at 0x663d12) and, between balls, the bonus: one `score_add` from 0x1a5130 with
its screen from 0x1a50c4.

- Each of those callers throws the return value away, and `award_screen` (a wrapper over display_effect_start) and
  `show_start` return 0 on their own failure paths, so refusing them with 0 is safe: they are refused since.
- The bonus is the game's end-of-ball sequence (0x1a4d6c posts bus event 41; the listener 0x210b8 totals the bonus
  object at 0x644a90 for the player up): counts x values (`[p*4+72]` x 5,710, `[p*4+56]` x 930, then 250,000,
  100,000, 500,000 and 125,000 items) plus raw points, times the bonus multiplier. The 5,710 and 930 counts are
  bumped by 0x11da30 and 0x11dc78, which ~40 small per-switch handlers (in the switch records at +0x1c) jump to right
  after their own `shot_dispatch` call: the switch layer feeds the bonus, not the rules, so refusing the dispatch does
  not stop it. 28 x 5,710 + 930 = 160,810 and 33 x 5,710 + 930 = 189,360, exactly the runs' extra points a ball.
- The ticket keeps the game's end of ball and bonus, so the bonus stays the game's (the decision is listed at the
  approval gate). Holding its count back would take a per-build site (0x11da30 / 0x11dc78 here) on every title.

## Light shows on every newest build

`site show_start` was on 22 ports. The other 36 newest builds got it from their own program (C:/tmp/PAD-1400
locate_shows.py / write_shows.py: `portgen.locate` from the 17 newest builds that had it, a strict unique match, every
reference agreeing, the same first words `e92d47f0 e2508000`), and their recipes were recompiled from the program
each was compiled from (its `elf_sha1` checked first; only the revision moved, 10 -> 11). 58 of 69 ports name it;
the 11 without are older versions (aerosmith_le-1.15, avengers_infinity_le-1.09, batman-1.13, deadpool_le-1.14,
guardians_le-1.14, iron_maiden_le-1.16, mando_le-1.44, rush_le-1.18, stranger_things_le-1.12, sword_of_rage_le-1.18,
turtles_pro-1.58), whose cards are archival: their light shows still play under a whole-game mode.

## Emulator status

Passed on the final runtime (hidden, muted, 4x):
- Uncanny X-Men LE 0.98, form mode, two players, six balls: each ball's score = the mode's awards; the game's award
  screens (1-2) and light shows (3) a ball refused as well; `END (the game is over)`.
- Uncanny X-Men Pro 0.98, form mode on the shipped prebuilt object: the newly placed `show_start` refused, score =
  awards; and a blocks mode (the "ramps" example as the whole game): ran through every ball and both players' turns,
  each with their own total (after the fix that its clock is not used: the first run ended at 30 s).
- Deadpool LE and Pro 1.16 (sweep jobs): 83-97 shots, ~110 point awards, 112-126 calls and 7 award screens refused,
  ball 1 awarded 43000 = score 43000, the game over with the mode.

The 53-build library sweep (C:/tmp/PAD-1400 mklist.py, sweepjob.sh, run5.sh) did not finish: WSL is in the stuck
`sync()` state (killed rig games stay in the kernel holding memory; `sync` blocked in super_lock), and the card store
was not mounted (mounted now), so boots took up to 6 minutes and crashed or hit the game's watchdog before the mode
ever ran. Rig 2 still has its stale `ballfeed.off`.

## Left for the next run

1. The game's rules on the 27 ports with neither `shot_dispatch` nor `block_rule` sites (aerosmith, batman,
   elvira3, guardians, iron_maiden, james_bond_60th, jurassic_park, metallica, rush, star_wars, stranger_things
   builds) still hear shots under a whole-game mode (their points, calls, screens, shows, serves and mode starts are
   held back): find each title's switch-to-rule dispatch (or its rules' shot handlers) in its program and add the
   sites, with recipes recompiled.
2. After a WSL restart (`wsl --shutdown`, David's call: it stops every other ticket's rigs), the sweep over the 53
   newest builds: `python C:/tmp/PAD-1400/mklist.py` (copies stage_own/pad_mode.so: rebuild it from the branch
   first), then `wsl -u root -e bash /mnt/c/tmp/PAD-1400/run5.sh <new batch dir>` (parks rig 2, -n 3). D&D LE's balls
   never ended in the one run it had (six balls out of the trough): check it against a stock run.
