# PAD-654: a game starts on Munsters LE, D&D LE and TMNT LE

PAD-645's final sweep passed 50 of the 53 newest builds; these three reached attract and never
started a game on the rig, so every sweep's in-game check skipped them. Three different causes,
all in the rig's model of the machine, none in the games.

Reproduced first (2026-10-20, `startcheck.sh` through `rigbatch.sh`, 4x): 0/3,
"no game started after three tries" on each.

## Munsters LE 1.28: a switch list with its trough unnamed

`plunge.py` said "trough 0/6". The title's `switch_list.txt` had 29 `?` names, all of node 8 -
the six trough switches and the shooter lane among them - so the ball tools fell back to
Godzilla Pro's compiled ids and watched switches the game does not use.

The names were there before. PAD-619 (`mktables._dump_over_binary`) replaces a list read out of
the binary with the run's own dump once one arrives. The binary list was fully named (by
swnames' static-table source) and carried the `# static-names:` memo saying that source had
been asked. The dump's rows are new and on this title come back `?` (the shim's message-table
address, item 29); `fill()` was called with the memo's answer, skipped the static table, and the
rewritten list kept the memo - so no later run ever asked again.

Fix:
- the dump's `?` rows take the replaced list's names by the wire (node, bit) - the static
  table's own join, at no cost;
- the memo carries a revision (`swtable.STATIC_MEMO_REV` = 2). A list written by the old code is
  asked once more, which heals every list that already went wrong (proven: the slot lists healed
  on their next boot, "filled 29").

## D&D LE 1.10: the dragon hold

The attract eject loop (PAD-483, PAD-474): a coil and switch log of attract shows TROUGH +
DIVERTER, then AUTO PLUNGER, every ~8 s. The diverter sends the launch into the dragon's hold
(DRAGON HOLD 1-4 and DRAGON HOLD STACK, let out by DRAGON VUK); on the rig the ball came back to
the trough and the game tried again for ever.

Measured, one change at a time:
- one ball closing DRAGON HOLD STACK: attract goes quiet for good;
- Start fills the hold to FOUR the same way (STACK, 4, 3, 2), then serves ball 1 with NO
  diverter fire - so the diverter alone says whose ball it is, in attract or a game (a rule keyed
  on Start sent the diverted balls onto the playfield and the trough emptied into a ball search);
- with six balls the trough reads 2/6 once the hold has its four, and the game let one out and
  loaded again, round and round (one game in three tries, three minutes in). With the hold's
  balls on top of the trough's six it served at once - the TMNT LE van's story (eight balls
  installed, a six-ball trough);
- the first Start only loads the dragon: nothing is served for 120 game-seconds after it, and a
  second Start serves ball 1 within two seconds.

Fix: `ballmodel.HOLDS` / `Hold` (matched by name, like the van and the drop banks): a launch
within `HOLD_FEED_S` of the feed coil goes into the hold's free place nearest the release end;
the release coil lets the ball at that end out (a ball in play) and the rest roll down; the
hold's `balls` (4) are queued behind the trough (`PAD_BALL_EXTRA` still overrides).

Not done, and not needed for a game: the dragon toy's motors. The game drives the dragon left /
right and up / down (DRAGON LR AWAY / LR HOME / UD HOME, node 10, with LR / UD RESET DETECTED
inputs) and nothing answers it, so a game shows "OPERATOR ALERT! Dragon Jam - DEVICE
MALFUNCTION". The game plays on. A follow-up, because it is a board nobody has modelled yet:
`PAD_NB_TRACE=1` on node 10 (C:/tmp/PAD-654/dragon.sh) shows none of the motor protocols the rig
answers (cmd 51/53/54 board motors, cmd 41 + short 40 coil motors; docs/plans/node_board_motor.md).
At Start the game configures two axes with a 23-byte cmd 32 (`32 01 c8 e1 00 42 ...` and `32 00 00
e1 00 41 40 ...`), then cmd 34 / 36, and from then on polls cmd 38 and 39 about 1000 times a second
(62360 of each in 60 game-seconds): a stepper driver waiting for a status nobody gives.
Done in PAD-656: it is PAD-393's stepper with two axes (`docs/plans/pad656_dragon_stepper.md`).

## TMNT LE 1.59: the van stocks the glider

The log shows attract's van cycle (item 167) - VAN DOOR, three balls in through VAN ENTER OPTO,
UPPER LOCK, LOWER LOCK, out - every ~20 s for as long as the rig ran, with GLIDER DIVERTER SERVO
firing between, and GLIDER LOCK OPTO never closing. A Start during it was mostly ignored
(PAD-420 and PAD-619 needed 3-5 tries and 90 s waits).

Measured: the van's first attract release sent into the glider lock (GLIDER LOCK OPTO closed)
and the cycle ended at once; the next Start served a ball that waited in the lane - a game on
try 1. The control run, same build and job, failed all three tries.

Fix: `ballmodel.VAN_CATCH`: an attract ball the van lets out fills an empty glider lock; the
rest roll home as before. Its ball is neither home nor in play (`Feeder.held`, `plunge.py drain`
through `ballmodel.lock_ids`).

## The job: wait for the game's own serve

`plunge.py game` launched 5 s after Start or said "no game". These titles serve ball 1 late (a
lock filled first, TMNT's turtle select), and the job's retry pressed coin and Start into the game.
Now `wait_serve`: up to 90 game-seconds (`PAD_START_SERVE_S`) for a ball that SITS 1.5 s in the lane
(the game's own launches - attract, a lock being loaded - fire the auto plunger within ~0.5 s,
and a hand launch of one of those took it from its lock); and 12 s after the game's own launches
stop with no ball 1, it gives up so the caller presses Start again (D&D LE's second Start).

## Proof

All in the emulator, hidden and muted, newest builds, `rigbatch.sh` at 4x:
- `startcheck.sh` on the three: 3/3 pass, three times over (Munsters LE and TMNT LE on try 1,
  TMNT once on try 2; D&D LE on try 2 by design - the first Start loads the dragon).
- with the stock mode runtime loaded so `mode.log` says the game's own `in_game 0 -> 1`
  (C:/tmp/PAD-654/gprobe.sh): 6/6 over two rounds.
- the whole library (53 newest builds) through `startcheck.sh` on the branch head, 2026-10-20: 51/53 in
  one pass (Munsters LE, D&D LE's Pro, TMNT LE, Godzilla LE and King Kong LE among them); the two
  others (D&D LE, Iron Maiden Pro) ended during boot, before attract and before anything this changes,
  and passed 6/6 when run again (three each).
- King Kong LE 0.97's occasional `[segv]` while starting a game happens on main too (A/B, same job:
  main 4 of 6, branch 4 of 5; only the segv failed either side). Not this ticket's.

Harness (C:/tmp/PAD-654): `iolog.py` (every named coil fire and switch edge), `gprobe.sh`
(in_game verdict), `sel.sh` (screens between Start and ball 1).
