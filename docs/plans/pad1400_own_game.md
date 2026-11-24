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

## The rules on every build (run 2)

Three more hold-backs, so the game's rules hear nothing on builds without one `shot_dispatch`:

- `rule_dispatch` (Foo Fighters LE, Venom LE / Pro): Foo Fighters Pro's dispatcher, located strict in each program,
  named apart because those builds' modes take their shots from `switch` lines. Refused, nothing handed on.
- `switch_spawn` (19 newest builds: the framework switch drain's `ldr r1,[sl]; cmp r1,#0; beq; ldrh r2,[sl,#24];
  ldrh r0,[sl,#32]; bl <start>`, once in every program): wrapped where it is made; a handler whose descriptor flags
  have none of the low 10 bits (a rule's: it runs in play only) is not started. Device, cabinet and service handlers
  start as always. The rule handlers are read from the switch records at arm time (a `maps_read()` first: the
  records are the game's heap). Rush LE: 21 rule handlers of 105 switches.
- `drain_rule_call` (all 53 newest builds): the trough's drain asks the game's own callback (event 10, `mov rN, #10;
  blx reg`) whether to serve the drained ball back; the call is skipped with r0 = 0, the framework's own no-callback
  answer, so the drain ends the ball. Star Wars LE served every drained ball back for ever (probe: serve reason 5,
  its video-mode branch); the framework's ball saver and playfield validation stay the game's.
- The game's points are no longer refused: `score_add` runs with 0 points (Star Wars LE validates its playfield
  through a score), from the bus's `ball_start` (Elvira's launch award came before any rule handler).

## Library sweep (53 newest builds, the shipped prebuilt object, hidden, muted, 4x)

C:/tmp/PAD-1400 mklist.py, sweepjob.sh (one player: each ball the safe playfield switches, then a drain, to game
over). PASS = the mode had the whole game from the game's start, ball 1's score was exactly the mode's awards, and
the game ended with the mode. 50 of 53 pass:

- 47 in the plain sweep (batch21/batch23).
- Star Wars LE, Star Wars Pro and The Beatles pass with a quiet spell after the switches (sweepjob_bs.sh: 30 game
  seconds before the drain). The job presses their Right Eject / Top Magnet switches, a ball "goes in", and under the
  whole game no rule kicks it back; the game's own ball search frees it in the quiet, as on a machine. Star Wars LE's
  ball-start ball save also covers about three drains (its saver's countdown pauses while none of its own modes
  runs; a stock game ends it at once).
- Not passing: Dungeons & Dragons LE 1.10 (the job's stock comparison, an ordinary mode, also logged no ball end:
  the job cannot end a ball there - the dragon hold), TMNT LE and Pro 1.59 (the stock comparison ends its balls;
  under the whole game the first launch already finds no ball in the lane and the rig's drain writes do not take:
  its turtle select / van at game start, not yet looked at).

## Award screens and light shows: only from callers that throw the result away (run 3)

TMNT Pro crashed in the sweep (segv at 0x147d20): its `show_start(178)` caller at 0x147cf0 keeps the show in r5 and
stores into it (`str r2,[r5,#168]`), and a refused 0 is a null pointer. Every build has such callers.
C:/tmp/PAD-1400/scan_ret_use.py follows r0 after every call to `show_start` and `award_screen` in each program: used
as a base, stored, passed on or returned = the caller uses it. Each of the 53 newest ports lists those callers
(`value own_ret_scanned 1`, `value own_pass_<k> <bl address>`, 7-57 a build) and pm_own_game never refuses them (they
are counted); a port that was not scanned (the older versions) only counts the two.

## Final sweep (run 3: the committed prebuilt object, all 53 newest builds, a 30 s quiet spell after the switches)

52 of 53 pass (C:/tmp/PAD-1400 batch34-36): the mode had the whole game from the game's start, ball 1's score was
exactly the mode's awards, and the game ended with the mode.

- In batch34 four more failed and passed on a rerun. Metallica and Mando Pro died in boot before any mode ran (rig
  instability). Led Zeppelin Pro did not reach game over in the job's time. King Kong Pro crashed once at a game's
  start: a virtual call through a corrupt listener in a broadcast loop at 0x79cb8. Six more King Kong Pro runs were
  clean, so it is one crash in seven, not reproduced.
- TMNT LE passes (its locks hold balls until the game's ball search frees them, as on a machine). TMNT Pro passes
  since the per-caller rule above.
- Dungeons & Dragons LE 1.10 is not proven: the stock game, an ordinary mode through the same job, never ends a ball
  on this rig either (a ball always back in the shooter lane, even with the upper shooter switch passed). D&D Pro 1.10
  passes.

## What is not covered

- The older-version ports (archival cards, not read): 11 without `show_start`, and the older ports with neither
  `shot_dispatch` nor `switch_spawn`. On them award screens and light shows are counted only, and their rules may
  still count shots silently. A port derived on the user's machine from their own card gets the newest build's sites
  only where the derivation places them.

## D&D LE (PAD-1555)

The rig could not end a ball on D&D LE (its drain counted the dragon's balls out of the trough's six); fixed in
PAD-1555, and a whole-game mode through three balls on D&D LE 1.10 passes (newbuild/ownjob.sh: 759 light shows and 79
award screens of the game's refused, no crash). The lost scan_ret_use.py is plugins/stern/ret_use.py now.
