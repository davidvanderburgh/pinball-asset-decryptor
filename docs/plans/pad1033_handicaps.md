# PAD-1033: a handicap for each player

DoomWalrus666 (Godzilla): "select a handicap level on single player or multiplayer. 0 = standard settings, 1 = qualify
battle is easy, ballsave slightly longer, 2 = same as 1 plus easier to qualify heat ray, longer ballsave, easier to start
building multiball, 3 = same as 2 plus easier to start tanks and bridge multi-ball, qualifying allies is easier ...
-1 = harder ... -3 = hardest. This should be able to be selected by player. So player one could be set to zero, but
player two could be set to 2." In the Discord thread: no disconnecting from Insider Connected ("You can change this
difficulty settings in the service menu"). Later: "PAD can estimate what settings make the most sense for each
difficulty handicap setting, I just gave some examples".

## The shape

- **A level is the game's own adjustments read easier or harder while that player is up.** The adjustment getter
  (`site adjustment`, on the 53 latest builds) is wrapped; NVRAM never changes. Like the operator's own settings it
  keeps the card on Insider Connected: a card of handicaps alone arms before the score gate (`only`, as PAD-1022's
  inactivity pausing does).
- **Each player picks at their first ball.** A spare service-menu setting per player is not there to take: every latest
  build has 3 DEPRECATED adjustments (Iron Maiden Pro 2), shared with MUSIC MODE, EDITION, the picture settings and
  CO-OP PLAY. So the game's top line (`BALL %d`, PAD-1017's borrow) reads `P2 HANDICAP 0`, the flipper buttons walk
  it (left harder, right easier, -3..+3, starting at that player's last game's level), the ball's first score takes
  it. One spare setting is a HANDICAP row (Off/On, On to start with) to switch the pick off.
- **The levels are the app's** (`plugins/stern/handicap.py`): Godzilla's after the reporter's list; any other game's
  worked out of its program - ball save 2 s a level (none at -3) and its `..._DIFFICULTY` adjustments (<= 10 steps,
  the lowest the easiest, as every menu has them) in by thirds.
- **Records.** Godzilla reads eight of its difficulties once, at a player's first ball, into the player's own record
  of each rule. The getter's answers after that never reach them, so the app finds those methods in the program by
  their shape and handicap.cfg names them (`record`); the runtime hooks them and writes the player's record at the
  pick. Found on Godzilla (8), Avengers (2-3), Foo Fighters (2), Jaws (4-5), Rush (1-2).
- **Ball 1's ball save** is read as the ball is served, before the pick shows: a player's level holds from the game's
  first read in their first ball, so ball 1's save is the level the pick opened at (the one they kept).

## Proof (Godzilla LE 1.16, emulator)

Rig kit `C:\tmp\PAD-1033\rig` (job.sh PLAYERS / GAMES / BALLS / PICKS / PICKS2, go.sh <list> <out> as root in Ubuntu;
`/dump/handlog.on` logs the first read of each adjustment by each player on each ball).

- r1: two players, -1 and +3: battle record 2 / 0 (the operator's 1), heat ray 8 (own 20) in player 2's turns only,
  ball save 11 / 15 (own 12) from ball 2. The census showed the eight difficulties read only at each player's ball 1
  (before the pick), the ball save at each ball's serve, the heat ray all the time.
- r2: the records found in the program, all eight seen and written; a second game, ball 1's save at the kept level.

## Left

- The other games' difficulties are read in play (the getter's answer plays) or kept in a shape the finder does not
  know: an emulator census per title would say which. Not needed for the reporter's game.
- Merging with PAD-1031 (co-op characters, unmerged): both wrap the adjustment getter with `hook_wrap`, which cannot
  wrap a function twice; whichever merges second chains its answer through the other's wrapper.
