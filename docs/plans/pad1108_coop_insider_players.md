# PAD-1108: co-op teammates on Insider Connected (DoomWalrus666)

Report (2026-11-10, Discord): a 3-player co-op game. Achievements earned by players 2 and 3 were shown as
earned by Player 1; Player 1's Insider username was on the End of Ball Bonus for all three players; the high
score went to Player 1 only.

## Why (desk findings, run 1)

Co-op (PAD-1017) plays ONE game player for the team and the runtime takes the teammates in turn. The game
asks "which Insider user is player N" with the game's player number, and that is always 1 in co-op, so
every Insider-facing thing the game does in a co-op game is Player 1's.

Addresses below are from `C:/tmp/godzilla_game.elf` (a Godzilla Pro program, 7 884 188 bytes); every
other build needs its own (a finder, see the plan).

- **The user for a player:** `0x475d2c user_for_player(player 1..4, flag)` - looks the player's user uuid up
  in the user manager (`0x7a8ae0`, `0x496a78`), then the user by uuid (`0x496bf8`). 19 call sites.
- **The achievement award:** `0x235954 award(table, uuid*, index, verified)` marks entry *index* of a 32-byte
  entry table, sends game event 0x7d (`0x4bb42c`), shows the award overlay (`0x44ab2c`, NEW INSIDER
  ACHIEVEMENT!) and adds 1 to audit 7 (`AUD_CONNECTIVITY_ACHIEVEMENTS_GIVEN`, `0x422de4`). Its callers are
  per player: `0x2375b0` walks two pending bitmasks at `0x7b1264` / `+4` (bits 1..4 = game player) and calls
  `0x237444(player)` / `0x237240(player)`, which call `user_for_player(player, 0)` first.
- **Why the gate let achievements through:** PAD-698 holds back the achievement list query
  (`GAME_ACHIEVEMENT_QUERY`, type 28). The game sends it from the network connection's outgoing queue
  (`QET_QUERY_ACHIEVEMENT_DESCRIPTORS`, sender `0x359470`, dispatcher `0x36a588`; the site that queues it is
  not found yet), and nothing seen re-asks per game: the session-begin reply's `descriptor_version` only
  bumps audit 0x29 and stores the version (`0x35b4e4`). Run 2: find the queueing site to confirm. On a
  card of co-op and nothing else the gate holds only while CO-OP PLAY is Classic/Enhanced, and the row
  ships at 0 (Off): a machine that booted at Off and was switched to co-op in the service menu already has
  the list, and awards achievements all game - to player 1. The achievements never reach Insider (the
  game-event stream is held), so NEW INSIDER ACHIEVEMENT! there is false either way.
- The emulator has no conagent, so no Insider login can be made there as things stand.

## Plan (decisions recorded in the ticket)

1. **Achievements held at the award, not only at the query.** While the gate holds, veto the award
   (`hook_veto` on the award, or on its two per-player callers) and log it once, so no achievement shows
   whenever the list was loaded. Finder: the one function that calls `audit_add` with r0 =
   `AUD_CONNECTIVITY_ACHIEVEMENTS_GIVEN`'s id (the app already reads audit ids, `stock_scan_c.audit_ids`), on the
   desk at Write time -> a coop.cfg / port line; check it on every Spike 2 build with Insider.
2. **Names follow the teammate up.** Wrap `user_for_player`: in a co-op game (coop_teammates() > 1), a call
   for player 1 answers with the user of the teammate up (coop.turn); team games map the game's player 1/2 to
   the team player up. Then the bonus header, the award (if ever let through) and anything else per player is
   the teammate's. Finder: by its shape (the user-manager uuid lookup then the by-uuid fetch) - work out on
   several builds before trusting it.
3. **The team's high score names the team:** the co-op board's record takes every teammate's Insider name
   (or P2/P3 for one not logged in), joined and cut to the record's 20 bytes, instead of player 1's alone.
4. **Proof:** an emulator stand-in login (write a user into the user manager from a probe mode, as PAD-698's
   probe called agent_begin) - then a 3-teammate co-op game shows each teammate's name on their bonus, and an
   award call made while the gate holds is refused.
