# PAD-1052: team play picked on the game's start menu, as stock Stern does it

**Done** (b1603afa4): the plan below was followed with two changes found in the emulator - the fill runs at ball 1's
`ball_start` through the runtime's own bus hook (the tick hung Iron Maiden LE 1.18; Godzilla's menu-started game
dispatches no `game_start`; a second bus hook never ran there), and the lines are said three times over (Godzilla's
game-start film hid the first 10 s). Proven on Godzilla LE 1.16, Iron Maiden LE 1.18, Foo Fighters LE 1.04.

## The ask

- DoomWalrus666: with CO-OP PLAY at Team 2v2 you press Start four times; one press should add all four and say
  "4 players added: Team 1: Player 1 and Player 3, Team 2: Player 2 and Player 4" (Team 2v1: "3 players added:
  Team 1: Player 1 and Player 3, Team 2: Player 2"). Then: "maybe this doesn't make sense because you still want to
  be able to play 1 player. Please advise what would be more clear."
- daveyvandy: "Make it work like stock Stern co-op 2v2 games work (if that's an option on them)."

## What stock does (TMNT, symbol build `reference/spike2 decompile/Game_with_Symbols/game_154.gzf`)

Ghidra headless kit: `C:/tmp/PAD-1052/gh` (`TeamPlay.java`, `TeamRefs.java`; project `proj`, program `game_154`;
run `analyzeHeadless.bat C:\tmp\PAD-1052\gh proj -process game_154 -noanalysis -readOnly -scriptPath
C:\tmp\PAD-1052\gh -postScript TeamRefs.java <out> <0xaddr|function name>...` from PowerShell).

- Team play is a pick on the start menu (hold both flipper buttons in attract: "TO CHANGE MODE, HOLD BOTH FLIPPER
  BUTTONS FOR MENU"): TEAM PLAY 2 VS 2 "TWO PLAYERS PER TEAM (4 CREDITS REQUIRED)", TEAM PLAY 2 VS 1 "TWO PLAYERS
  VERSUS ONE PLAYER (3 CREDITS REQUIRED)", TEAM PLAY 3 VS 1 "(4 CREDITS REQUIRED)", COOPERATIVE "SHARED PROGRESS AND
  SCORE", COOP + COMPETITION, then "PRESS START NOW".
- `start_button_start_game(credits_needed, credits_taken, tournament, competition, players)` (0x1f5100) refuses
  without the credits, starts the game and then adds players 2..`players` itself
  (`sys_player_check_add_player` + 0x1f4c20). So ONE Start makes the whole team game; a plain Start (no pick) is the
  one-player game as always.
- `team_play_get_player_score(p)` (0x141a68), team type at 0x4dece4: 1 = 2v2, players 1 and 3 one team, 2 and 4
  the other (the numbering this ticket already uses); 3 = 2v1, players 1 and 2 against 3; 2 = 3v1, 1-3 against 4.
  Scores are per team (0x4dece8 / 0x4decf0). The rule is `cteam_play` (hooks 0x45, 0x44, 0x37, 0x87).

## Done on the branch (commit 300562388), still wanted

- Numbering in play order: team 1 = P1, P3; team 2 = P2, P4 (`coop_team_of`, `coop_team_player`); turns P1 P2 P3
  P4. Matches stock 2v2. (2v1 keeps the reporter's P1+P3 against P2, who plays both of team 2's turns.)
- `coop_team_fill`: the game's own add called for every player left, stopping when the game adds no one (credits);
  `coop_join_words` / `coop_join_tick`: "4 PLAYERS ADDED", "TEAM 1: P1 AND P3", "TEAM 2: P2 AND P4" on the top line,
  2 s each, then player 1's pick. Tests: tests/test_pad1042_team_play.py (WSL: they need an ELF linker).
- The trigger is the second Start in the first ball. THAT is what changes.

## Next run: the trigger becomes a start-menu pick

1. With CO-OP PLAY at 2 or 3 (or coop.cfg `teams ...`), the game's start menu gets TEAM PLAY 2 VS 2 and TEAM PLAY
   2 VS 1 entries (both, whatever the row says: stock lets the player pick at the machine; the row only allows team
   play - put that in `decisions`). Picked: a STANDARD game, not a challenge game. Plain Start with no pick: the
   game's own one-player game, and Start in ball 1 adds a competing player as stock (drop the second-Start fill).
2. At the game's start with a team pick pending, fill the teams once the game has one player on ball 1 (a tick
   check like an uncommitted first draft had: `fill_game`/`fill_seen`, COOP_FILL_MS 0.8 s, from `coop_tick`; it
   was never committed, so write it again), then the join lines. Stock refuses
   to start short of credits; ours adds what the credits buy (say so in Help).
3. Menu shapes (portchallenge.py writes the lines; runtime `challenge_menu` / `challenge_menu_pick` /
   `challenge_menu_frame`):
   - Bond-style list (49 ports, `site challenge_menu`): 12-byte entries `{u32 kind, u16 caption, char *name}`,
     `pm_challenge_add` appends kind `0x100 + k`; at `challenge_menu_pick` an own entry is turned into kind 3 (a
     challenge game). Team entries: append with our own kind, and at the pick make it kind 0 (Standard) and remember
     the team pick. Room: cap 9 (Bond uses 7) - log "no room" like the challenges do.
   - Godzilla-style index list (`site challenge_menu_frame`, Godzilla LE/Pro 1.16, Pro 1.15): u32 game-mode
     indices; MODE CHALLENGE appends KOTM's index again and letters `challenge_name_msg_0` while the cursor is on it.
     Team entries: append Standard's index (`challenge_mode_plain`, 1) and letter Standard's name message while the
     cursor is on it - the port needs that message id (new `value` line from portchallenge.py: read it off the
     game-mode table entry for index 1).
   - Ports with neither (John Wick, Metallica, X-Men, ...): keep the second-Start fill there, or no team entry - check
     which of them take co-op at all (coop_play.title_refusal).
4. Help, Modes tab note, SDK guide, coop_play.TEAMS_HOW: say "hold both flipper buttons in attract, pick TEAM PLAY
   2 VS 2, press Start".
5. Proof (emulator, root launcher: slot job dirs can be root-owned): `C:/tmp/PAD-1052/rig` (job.sh, list.txt,
   go.sh; run as `wsl -u root`). Needs a menu step: both flipper buttons held 3 s in attract, step to the entry
   (PAD-615 rig kit: menujob.sh keys), Start. Godzilla LE 1.16 and one Bond-style title. A stock TMNT LE run of its own
   TEAM PLAY 2 VS 2 for the look to match (TMNT rig notes: memory tmnt-le-rig-game-start).
