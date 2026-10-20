# PAD-619 - Challenge modes on every Spike 2 build

PAD-615 gave James Bond LE/Pro 1.06 and Stranger Things a mode in a challenge's place, and Bond's start menu our
names and challenges of our own. This ticket takes the feature to every Spike 2 title and version.

## What a "challenge" is on each build (census, 2026-10-19)

Every Spike 2 build carries the framework's Player Challenge game: `FG_PLAYER_CHALLENGE_MODE_ACTIVE` (18; 16 on the
1.13-era builds) and the start menu CHOOSE YOUR MODE OF PLAY (both flipper buttons held in attract; message 1911,
1894 on the older builds). What the game does with it differs by generation:

| family | builds | the menu | its challenges |
|---|---|---|---|
| Bond's generation, named | Bond LE/Pro 1.06, Stranger Things 1.13 / LE 1.12 / LE 1.13, Rush LE 1.18 / 1.19 / Pro 1.19, Sword of Rage LE 1.18 / 1.19 / Pro 1.19 | list on the stack, jump on the entry's kind | one kind per challenge, each setting 18 + a flag of its own (Bond 185-189, ST 144-147, Rush 29-31 Cygnus Book 1 / 2 / 2112, SoR 67/68 Retro / Ransom) |
| Bond's generation, plain | Aerosmith (3), Avengers (3), Batman 66 (2), The Beatles, Deadpool (3), Guardians (3), Iron Maiden (3), JP The Pin, Led Zeppelin (2), The Munsters (2), Star Wars ELG | the same | one plain kind setting 18 alone - the entry the menu adds only when Stern Insider Connected has sent a challenge (its name is the download's); with flag 18 alone the game plays its normal length (Deadpool: ball 2 followed) |
| Bond's generation, count in a register | Elvira 1.13 | the same, but the loop keeps the count in r5 | plain |
| index list (Godzilla's) | Godzilla 1.15/1.16, Jaws, John Wick, King Kong, Metallica, X-Men | a list of game-mode table indices; selecting one applies its flags live | a static game-mode table (Godzilla 32-byte entries with a second flag: KOTM 40, Time Attack 41; Jaws/JW/Metallica/Venom `<x>_cm_<name>` entries, 28 bytes, one flag - the pick is the index) |
| other | D&D, Foo Fighters, Jurassic Park LE/Pro, Mando, Star Wars LE/Pro 1.30/1.31, TMNT, Venom, Bond 60th | not found yet | TMNT/Venom: Default Game Mode switches with calls, not flags; Bond 60th: a timed whole game |

## Round 1 (this run): Bond's generation - done

- `portchallenge.py`: `flag_lines` (the flag bitmap holder and size, from the flag functions' one shape, every
  build), `menu_generic` (the menu: every-frame site, the kind jump, list place, entry size 12/16, count, room, the
  kind ours become, CHALLENGE caption), named challenges from the menu's kinds where no handler of PAD-615's shape
  exists (`value challenge_flag_<n>` without a site), `balls_lines` (`site challenge_balls`, the framework's
  balls-per-game getter, every build).
- Runtime: challenges by their flag alone - at the dispatch of `event ball_start`, on the game's thread before its
  handlers, a challenge game with the held challenge's flag set has the flag cleared and the mode's on_pick called;
  the start menu's every-frame append (idempotent), 16-byte entries, the plain challenge kind (`challenge_menu_slot
  -1`: nothing of the game's to stop, the ball's start hands it over); `challenge_balls` says 1 while a mode's
  challenge game runs (Deadpool would otherwise play three balls).
- Rig: `C:\tmp\PAD-619` (proof.sh, job619.sh for rigbatch, rig/ch619.c flag watcher). Gotchas: Rush's switch list
  ids are 529 high (DIP 1 = 546; the job rewrites the run's list); Guided Setup rows move with SERVICE PLUS; a
  plain flag-18 game does not end after one ball without `challenge_balls`.

## What is left (next runs)

1. Elvira 1.13: hook the menu where the builder has stored the count, before the loop loads it into r5.
2. The index-list family (the framework's `GamePlayModes` singleton, typeinfo `13GamePlayModes`, on Godzilla, Jaws,
   John Wick, JP LE/Pro, King Kong, Metallica, X-Men; not on Bond's generation): take a challenge's place (Godzilla: clear flag 40/41 as the ball starts - the flag route
   as it is; Jaws/JW/Metallica: the pick is the game-mode index, needs a per-title stop), our names (message ids:
   `pm_message_set` on the entry's name message), challenges of our own (the table's accessors are bounded to its
   entries - an entry of ours needs the accessors hooked or a spare entry borrowed).
3. The other family: find each title's menu and what its challenge kinds do; Bond 60th's timed game says so in its
   cannot sentence.

## Findings, round 2 (2026-10-19)

- Avengers LE/Pro 1.10 run one of their own modes at every ball's start, so a challenge pick refused at once ("one of
  the game's modes is running"). The pick now waits for it to end (the ball's end lapses it), and the refusal names the
  mode in the way. Generic: any build's pick waits the same way.
- Batman 66 (and others): slings and pops alone are not a valid playfield, the drains were ball-saved and the one-ball
  game never ended in the job; the rerun job (job619b.sh) also hits ramps, loops and spinners.
- Jaws Pro 1.02: `GamePlayModeAdapter` (vtable 0x6d78e8) over a table at 0x859ea0 + 0x18, 14 entries of 28 bytes
  `{u32 0, u32 index, u16 flag, u16 msg, u16 msg, u16 msg, u32 kind, u8, u8}`, accessors `cmp r1,#13; rsbls r1,r1,r1,lsl
  #3; movwls/movtls tbl; addls r1,r3,r1,lsl #2; ldr.. [r1,#off]`. The challenge games (4th of July 8, Shark Hunter 9,
  Jaws the Revenge 11, The Shark is Broken 12) all set flag 18 alone: the pick is the current game-play-mode index,
  held by the GamePlayModes singleton. Next: find that index on the rig (memory diff before/after picking 4th of July
  on the start menu), then decide the take-over (switch the index to a plain entry at the ball's start, or hook the
  challenge's own start).
- The current game-play-mode index (Jaws Pro 1.02): the `GamePlayModes` singleton at 0x855368 (guard 0x85538c, built by
  0x5e960, which stores the vptr 0x6d77b0), word +8; getter 0x5e9f0 (`ldr r3,[guard]; tst r3,#1; ... ldr r0,[single,#8]`),
  and 0x5ea6c tests it against 7. That getter shape matches other singletons too (C:/tmp/PAD-619/gpmcur.py): the finder
  must keep the one whose constructor stores the GamePlayModes vptr. Plan for the index family: `data game_play_mode`
  + `value challenge_mode_<n>` (the entry's index); at the ball's start of a challenge game whose index is a held
  challenge's, set the index to Standard's (1) and hand the ball to the mode - to prove on the rig that the game's
  challenge (e.g. 4th of July, OB_JWS_FOURTH_OF_JULY_CHALLENGE_START) has not already started at the game's start.

## Round 3 (2026-10-19, afternoon)

- GamePlayModes builds, by index (portchallenge.gpm_lines): Jaws LE/Pro (4th of July 8, Shark Hunter 9, Jaws the
  Revenge 11, The Shark Is Broken 12; 10 is a video-mode test), John Wick LE 1.01 (Tick Tock 5) / 1.02 (Red Circle
  Reckoning 4, The Staircase 5, The Duel 6, Special Assignment 7, Tick Tock 9), Metallica 1.03 (7-13, flag 17) / 1.04
  (8-14). Standard is 1. King Kong 0.97, X-Men 0.98: no challenge among their game modes.
- Venom (portchallenge.adapter_lines): the adapter keeps the current mode in a global (+4) and u16 arrays; Challenge
  Mode Low / Medium / High = 11-13, Standard 0. D&D's adapter: no challenge.
- Jaws' Default Game Mode reaches only entries 3-7 (0x5ec90: value v -> [0x6d7824 + 4 (v - 1)]), so a challenge game
  comes only from the start menu (unlocked by shark teeth). The rig proof sets the index in attract as the pick does
  (rig/ch619.c `gpm` / `set`, jobgpm.sh / jobgpm4.sh with AT= and PLAIN=).
- PROVEN: Jaws Pro 1.02 (8 -> 1 at the ball's start, mode started, one ball, GAME OVER; control: the game's own 4th
  of July). Godzilla Pro 1.16: KOTM taken by its flag (40 never set; control set it) but the mode waited the whole
  ball on the game's "any mode running" - the pick now waits at most 3 s (CHALLENGE_GRACE_MS); rerun pending.
- Plain-challenge titles (only sys_challenge, Insider's): TMNT, Star Wars LE/Pro, Mando, Foo Fighters, Bond 60th,
  Elvira, JP LE/Pro. All have CHOOSE YOUR MODE OF PLAY (message 1911, CHALLENGE 1921); their menu picks with a chain
  of compares (Star Wars Pro 1.31 0x5fc40: kind 1/2/3 -> set flag 16/17/18 via 0x18dd50), not Bond's jump table:
  menu_generic needs that shape for "a challenge of its own". TMNT's FG_PLAYER_ALL_TURTLE_CHALLENGE_ACTIVE is an
  in-game feature flag, not a menu challenge (to confirm).
- Rig notes: cards on D: copy at ~9 MB/s while another ticket reads D:; never stage from two batches at once (the
  cache refused a card and it booted uncached and crashed); Tech Alerts boots must wait for the game loop (proof619c).
- Star Wars LE 1.30/1.31, Pro 1.31: done in code (a4fe926b) - compare-chain pick hooked a word early, ours by name
  pointer, Standard's kind, `challenge_menu_sets_on`; list sized for the game's own (cap 3/4). Rig proof queued.
- The other plain-challenge menus (C:/tmp/PAD-619/menuscan.py <key> <va near message 1911's use>):
  Elvira 1.13 fn 0x99198: frame 0x99764, Bond's jump at 0x99900 (`ldr r3,[r3,#-0x350]; sub; cmp #6; ldrls pc`) -
  menu_generic misses only its count (kept in r5); JP Pro 1.16 fn 0xe29dc: frame 0xe382c, count sp+0x3c, chain at
  0xe3960 (`ldr r3,[r3,#-0xb8]; cmp #1; beq; cmp #2`); Foo Fighters Pro 1.04 fn 0xcc15c: frame 0xcd220, count sp+0x28,
  pick not in this function; Mando Pro 1.45 fn 0x103114: count sp+0x40, kind test at 0x1046a4 (`ldr r3,[r3,#-0xcc];
  cmp #1; movne`); TMNT Pro 1.59 fn 0xa7710: frame 0xa8f40, kinds compared to 10 and 12 (0xa8f94, 0xa9368); Bond 60th
  LE 1.11: message 1911 not loaded by an immediate - find its menu another way.
- Proofs so far this round: Jaws Pro 1.02, John Wick Pro 1.02 (mode run; control pending).
- Elvira 1.13: done in code (8572738e) - count in r5, hook_full on the frame. Rig proof queued (list_next).
- JP Pro 1.16 pick at 0xe3954: entry = sp+0x2c0 + 4*(r6+r4) - 0xb8 with its kind at +0 and a word at -4 (0xe39a4
  `ldr r1, [r6, #-0xbc]`), so its entries are laid out differently from Bond's {kind, caption, name}: the append
  hook needs per-port field offsets before JP can take ours. Kinds 1, 2, 3 (3 guarded by r0 <= 3).
- Proven this round: Jaws Pro 1.02, John Wick Pro 1.02 (mode + control).
- Queued (C:/tmp/PAD-619/list_next.txt, chained after batch_all by sweep_next.sh): Godzilla Pro 1.16 rerun (grace),
  Venom Pro 1.07 + control, Jaws LE 1.02, Venom LE 1.07, Godzilla LE 1.16 / Pro 1.15, Star Wars Pro 1.31 (own menu
  entry), Elvira 1.13 (own menu entry).

## Round 4 (2026-10-19, evening)

- Proven: Metallica 1.04 (Lux Aeterna Combo Challenge by index; control: the game's Combo Challenge); own challenges
  on the start menu of Aerosmith LE 1.16, Batman 66 1.14, Deadpool LE 1.14/1.16, Pro 1.16, Guardians 1.15 / LE 1.15,
  Iron Maiden LE/Pro 1.18, Munsters LE/Pro 1.28 (CHALLENGE_MENU_PROVEN).
- Fixed: a challenge-picked mode does not give way to the game's modes (run.by_challenge) - Avengers 1.10 / Led
  Zeppelin started it past the game's ball-start mode, which then ended it at once.
- Sweep failures left (rerun list_r5 with job619d's `hitall`): Avengers x3, Beatles, Led Zeppelin x2 (no ball end: the
  drains were re-served - a playfield switch the old job never hit), Batman 1.13 and Iron Maiden LE 1.16 (the ball
  ended, GAME OVER did not: these older builds do not end a game through the balls-per-game getter - Batman 1.13
  never called it; candidate 0x1ddb84 = adj(79) + adj(80) per player, reached by pointer 0x6efd24; the same shape on
  Aerosmith LE 1.15, Avengers 1.09, Guardians LE 1.14, Mando LE 1.44, Rush LE 1.18, ST LE 1.12, SoR LE 1.18, TMNT Pro
  1.58 - veto it on the rig and see), JP The Pin 1.05 (no menu line).
- TMNT Pro 1.59 start menu: 24-byte entries at sp+0x2e0 {+0 u8, +4 kind, +8/+0xa caption, +0xc char *, +0x14 u32},
  count sp+0x3c, frame 0xa8f40; kinds 10 TRAINING RESET, 11 FINAL BATTLE CHALLENGE (a named challenge - likely
  FG_PLAYER_ALL_TURTLE_CHALLENGE_ACTIVE), 13 DJ MIXER; the pick on Start at 0xa9368 (kind 12 special). JP Pro 1.16:
  kind at +4 too. The append hook needs per-port field offsets (kind/caption/name) and a template copy.
- Batches: the chain (chain_all.sh: batch_all -> batch_next -> list_r5) runs from this session's background task; a
  new session must re-arm it (workers survive, rigbatch's main and the chain do not).

## Round 5 (2026-10-19, night)

- Proven: Venom LE/Pro 1.07 (Challenge Mode Low by index 11 -> 0; control: the game's own), Jaws LE 1.02, Star Wars
  Pro 1.31's compare-chain menu (own entry as Standard). In CHALLENGE_PROVEN / CHALLENGE_MENU_PROVEN.
- Found: Avengers / The Beatles / Led Zeppelin / Godzilla / Iron Maiden LE 1.16 challenge games never ended because
  these games re-serve every drain in a challenge game until the challenge itself ends the ball. PAD-630's
  `site challenge_end_ball` (one shape, 59 builds) is now written on every build (fc5dd5ea), not only the handler
  builds; the taker's end ends the ball. Rerun in batch_r6.
- TMNT LE/Pro 1.59 (and Pro 1.58): menu_wide - 24-byte entries, kind at +4, name at +12, plain kind = FINAL BATTLE
  CHALLENGE (11; 1.58: 10); the runtime's append/pick take the port's field offsets and copy a game entry (49aa4e6c).
  TMNT Pro 1.58's shipped port names no events (thin port), so its menu stays the game's. Proof queued (chain7).
- Still open: JP LE/Pro 1.16 (its pick is not the 0xe3960 chain - that is text building), Mando LE/Pro 1.44/1.45,
  Foo Fighters LE/Pro 1.04, Bond 60th LE 1.11 (menu not yet found), D&D (adapter, no challenge; menu?), Elvira's game
  end, the rig re-runs. Chains: chain6.sh (batch_r6) then chain7.sh (batch_r7); re-arm both after a restart.
- Bond 60th LE 1.11: one challenge, a timed whole game ("CHALLENGE MODE ENDS", its own champion score) - nothing a
  mode can stand in for, so its profile's cannot sentence should say that; its start menu is an object list built
  by calls (fn 0x5cf38: `0x5cef0(list, kind, ?, flag, caption msg, text msg)` per entry: Standard 0x77a/0x77b, flag
  0x10 Tournament 0x77c/0x77d, ...) - a challenge of a mode's own there means calling 0x5cef0 after the builder and
  finding its pick.

## Round 6 (2026-10-19, late)

- Proven: Batman 66 1.13, JP The Pin 1.05, Iron Maiden LE 1.16 start menus (the older builds' pick kept past the
  game's start; JP The Pin's buttons are L/R FLIPPER BUTTON). Foo Fighters LE/Pro 1.04 and Mando LE/Pro 1.45: in code
  (menu_live: live-applied menus, ours as Standard), rig proof to run. Bond 60th: cannot sentence (timed whole game).
- A port without a game_over event (IM LE 1.16, Elvira, Avengers LE 1.09) is judged by in_game's LAST transition
  going to 0 and no further ball start (C:/tmp/PAD-619/reverdict.sh) - the end-of-ball call flickers in_game.
- TMNT 1.59: our entry is appended (13 entries) and picked (made FINAL BATTLE's kind 11, flag 18 set live), but Start
  (bit 0x80) goes straight to 0xa9918, which clears flags 16-20 / 40 / 41 and leaves the menu - the CONTROL (the
  game's own FINAL BATTLE picked the same way) also played a Standard game. How TMNT starts that challenge is not in
  this function (a confirm step, or the choice read elsewhere at the game's start): to find before TMNT can be proven.
- Proven later in round 6: Aerosmith LE 1.15, Avengers LE 1.09, Guardians LE 1.14, Sword of Rage LE 1.18, Elvira 1.13
  (40 menus in all). The game's end-of-ball call is now told from its lookalikes (argument in r4, flippers off) and
  found on all 69 builds (4ff6ef1c) - Rush LE 1.19's challenge game had played on without it; rerun queued (r11).
- Open: Star Wars ELG 1.10 plays a second ball (the balls-per-game getter is never asked; its game length is decided
  elsewhere); Rush LE 1.18's menu does not open on the rig with the flipper buttons held (settings as 1.19's);
  Aerosmith 1.16's rig sat with the coin door open (48V disabled) - rerun queued; TMNT's real pick; JP LE/Pro 1.16 and
  Mando LE 1.44 menus; Foo Fighters / Mando 1.45 proofs running (r10).

## Round 7 (2026-10-20)

- The rig's switch list: pass one (no run) reads a title's list out of the binary, and pass two kept it "(cached)"
  without looking at the dump the same run printed. On Star Wars LE 1.30 (70 of 103 ids) and Aerosmith 1.16 (93 of
  93) the binary's numbering is not the game's own table's, so Start, both flipper buttons and the trough feeder
  poked other switches - "the menu does not open", "no ball leaves the trough". mktables now records a list's source
  and replaces a binary one with the dump; the feeder re-resolves when it is replaced; the shim's at-rest door and
  trough go by wire (bd661a08, e5ac0eda). Star Wars LE 1.30's menu proven with it.
- Mando LE 1.44: not "the cursor resets every frame" - the loop returns past that `mov r6, #0`. Its menu keeps the
  buttons and the cursor in registers and picks with a byte; menu_live reads it. Proven: GAME OVER after the one ball.
- Star Wars ELG 1.10's second ball was an EXTRA BALL earned 17 s into the challenge game (its count at 0x600114 went
  0 -> 1): the ball's end takes it before asking the balls getter. `site challenge_extra_ball` (all 61 challenge
  ports) says none while a mode's challenge game runs.
- TMNT: its challenges are locked until a player unlocks them ("PLAY AS ALL FOUR TURTLES TO UNLOCK"); Start on a
  locked one plays Standard, which is why the game's own FINAL BATTLE pick (the control) did too. Ours now play as
  Standard (kind 0, sets_on) and the ball's start hands the game to the mode.
- reverdict.sh's in_game rule was fooled by the end-of-ball call's flicker (Aerosmith 1.16 sat on BALL 1); it now
  needs a ball_end first. Rechecked every saved run: Star Wars LE 1.31's proof had never ended the ball (the mission
  select waits for the Action Button) - taken off the list, rerun with the button pressed.

## Status by build (2026-10-20)

- Start menus proven (CHALLENGE_MENU_PROVEN, 46): Aerosmith 1.16, LE 1.15/1.16, Avengers LE 1.09/1.10, Pro 1.10,
  Batman 66 1.13/1.14, The Beatles 1.29, Bond LE/Pro 1.06, Deadpool LE 1.14/1.16, Pro 1.16, Elvira 1.13, Foo Fighters
  LE/Pro 1.04, Guardians 1.15, LE 1.14/1.15, Iron Maiden LE 1.16/1.18, Pro 1.18, JP The Pin 1.05, JP LE/Pro 1.16, Led
  Zeppelin LE/Pro 1.22, Mando LE 1.44/1.45, Pro 1.45, Munsters LE/Pro 1.28, Rush LE 1.18/1.19, Pro 1.19, Star Wars ELG
  1.10, LE 1.30/1.31, Pro 1.31, Stranger Things 1.13, LE 1.12/1.13, Sword of Rage LE 1.18/1.19, Pro 1.19.
- A mode in a challenge's place proven (CHALLENGE_PROVEN, 18): Bond LE/Pro, Stranger Things x3, Rush Pro 1.19, Jaws
  LE/Pro, John Wick LE 1.01/1.02, Pro 1.02, Metallica 1.03/1.04, Venom LE/Pro, Godzilla LE 1.16 / Pro 1.15 / 1.16.
- Not proven, the app says so ("has found its challenges but has not yet seen a mode of yours start from one"): TMNT
  LE/Pro 1.59, Pro 1.58. Ours plays as Standard now (its challenges are locked until unlocked); on Pro 1.59 the pick
  started the mode at the ball's start, but the ball never ended - every drain was served back and the challenge's
  end-of-ball call does nothing in what the game takes for a Standard game; on LE 1.59 Start on our entry ("CHALLENGE /
  PAD CHALLENGE" on the glass) left the menu up - its lock test (0x194298's value against the entry's last word)
  refuses it. Pro 1.58's port is thin (no events): nothing to judge a rig run by.
- Open (next run): Star Wars LE 1.31 sits in its mission select ("USE THE ACTION BUTTON TO SELECT YOUR MISSION", the
  countdown stopped at 9, nothing logged) when playfield switches are hit after the challenge's end-of-ball call -
  reproduced twice (batch_r27, r31; C:/tmp/PAD-619/job619s.sh). Our runtime's scoop wrapper logged nothing. With the
  Action Button pressed after the hits (job619v.sh, batch_r32) the ball did end (ball_end, the balls getter said 1) but
  66 s later and the end shot still showed the select - not settled whether the press closed it. The proof runs play
  only until the mode has run out (job619t.sh). To find: what opens the select there, and whether a mode's challenge
  should keep the game's mode starts blocked until the ball has really ended.
- No challenge, said so: King Kong 0.97, X-Men 0.98, D&D x3, Bond 60th (a timed whole game).
