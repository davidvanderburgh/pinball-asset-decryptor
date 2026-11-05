# Co-op play on every Spike 2 game (PAD-1017)

daveyvandy: "Add Spike 2 co-op to games without it. Should work like games that do have co-op (like TMNT). Should
have its own high score boards and share progress 2-4 players."

## What the games with co-op do

Eight titles ship co-op: TMNT, Venom, Mandalorian, D&D, Jaws, Jurassic Park, King Kong, Bond 60th (string census of
the 53 shipped programs in `C:/tmp/PAD-1010/elfs`). Every Spike 2 program carries the framework's
`AD_PLAYER_COOP_MODE` (id 105, 0..1, default 1) and `FG_PLAYER_COOP_MODE_ACTIVE`, but on the other titles nothing of
the title's own reads them.

TMNT is the symbol build in `reference/spike2 decompile/Game_with_Symbols/game_154.gzf` (Ghidra project in
`C:/tmp/PAD-1017/gh`, scripts `C:/tmp/PAD-1017/scripts` FindSyms.java / Decomp.java). Its co-op is title code:

- `ccoop_play::hook_score_end` copies the player up's score to every other player after each score, so all players
  show the team score;
- some 70 call sites of `ccoop_play::CoopPlayActive` in the title's rules (`cepisodes::CopyForCoop`, weapon and
  turtle selection, hurry-ups, ...) copy or share their own per-player state;
- separate boards: COOP GRAND CHAMPION + COOP HIGH SCORE #1-#4 (TMNT, Venom, Mando, D&D; one record with up to four
  names), or one board per team size (Jaws, JP, King Kong: 2P / 3P / 4P COOP).

None of that is reusable elsewhere: each title keeps its progress in objects of its own, one per player.

## The design: one shared player, teammates in turn

The game plays ONE player. Its progress, score, lights and flags are the team's, because there is only one of each.
The runtime takes the teammates in turn, one ball each, so every teammate plays ball 1, then ball 2, and so on.

The framework's player code has the same shape on all 53 shipped builds (`pinball_decryptor/plugins/stern/portcoop.py`,
`tests/test_pad1017_coop_lines.py`):

| line | what | Godzilla LE 1.16 |
|---|---|---|
| `site coop_player_change` | the player change at the ball's end (asks the extra-ball test, then the players and balls) | 0x338950 |
| `site coop_add_player` | add a player (Start in the first ball; AD_MAX_PLAYERS_PER_GAME, hooks, `strbne` the count) | 0x338790 |
| `data coop_player` | the player up's byte; the ball in play is the NEXT byte | 0x713b94 (= the port's `cur_player`) |
| `data coop_players` | the count of players | 0x7d116c |

The player change (Godzilla LE, read in the disassembly): extra ball taken -> same player, same ball. Otherwise
`next = player + 1`; when `next > players`: if `balls_per_game(player) > ball` then ball++ and player 1, else game over.

### Runtime plan (pad_mode_runtime.c, next run)

1. **Teammate turns.** Wrap `coop_player_change`. In a co-op game with N teammates, turn t:
   - t < N: ball byte - 1 before the game's call. The game then puts it back (ball++), so the ball number does not
     move. If the ball byte is still one down after the call, the game took an extra ball: put it back, and the turn
     stays with the same teammate. Otherwise t + 1.
   - t == N: the game's call as it is. If the ball moved, t = 1. Game over comes only after the last teammate's
     last ball.
   - Side effect: the game's "ball 2 starts" coin-door bonus-pricing reset runs once per teammate on ball 2.
     Harmless; prove it on the rig.
2. **Teammates join.** Wrap `coop_add_player`. In a co-op game, let the game's own call run (credits, its hooks,
   max players). Then put the count back to 1 and count a teammate (up to 4). Prove on the rig that the title's
   "player added" handlers seeing 2 players leave no second score panel. If they do, set the count to 0 before the
   call instead, so the game counts 0 -> 1.
3. **Whose turn.** At each turn change, show "PLAYER n" on the screen (award screen / message, whichever the port
   has) and in mode.log.
4. **High scores.** Reuse PAD-640/663 (`chg_scores_wrap`: on every build, a record of the runtime's own goes in a
   champion entry's place, with the game's own records shut for that game). Boards: 2-, 3- and 4-PLAYER CO-OP,
   records in `/dump/pad_coop_scores`. Attract pages: PAD-660/663 pages.
5. **Choosing co-op.** A Write tab option "Co-op play" (sidecar `coop: {on: true}` -> `coop.cfg` beside mode.so,
   carried by mode_install / cardmodes / tryit like `attract.cfg`). On the machine: hold the RIGHT flipper button
   and press Start to add a teammate; plain Start adds a competing player, as stock. Needs `value coop_button
   <switch id>` from each build's switch names (records + level are on all 69 ports: `switch_records`,
   `switch_level_at`).

### Coverage

- 53 of 53 shipped programs give all four lines. Next: add `portcoop.lines` to portgen, as the challenge lines are
  added (portgen.py "portchallenge.py" list). Then append the lines to the 69 shipped ports and the derived older
  builds, and check each older port's lines against its own program.
- Emulator proof: Godzilla LE 1.16 first (2 and 4 teammates: turns, shared progress, game over after N x balls,
  extra ball, the co-op board). Then a rigbatch sweep over every build.
