# PAD-1041: Prolonged Competition on every game's start menu

Joe_Blasi (Pinside, post #462): "can the prolonged comp (in player menu) be added to all games?"

## What the games do

String census of the 53 latest shipped programs (`C:/tmp/PAD-1041/elfs`, read with the app's own ext4 reader):

- Only **Venom** (LE/Pro 1.07) and **Dungeons & Dragons** (LE/Pro 1.10) have it: `GPM SELECT PROLONGED COMP`,
  `PROLONGED COMPETITION` / `COMPETITION GAME PLAY UNTIL POWERED OFF`, `PROLONGED COMPETITION SUCCESSFUL`,
  `PROLONGED COMPETITION INACTIVE` / `STANDARD MODE NOW AVAILABLE` (D&D also `FG_PLAYER_PROLONGED_COMPETITION`).
  Picked once on CHOOSE YOUR MODE OF PLAY, every game is a Competition game until the machine is switched off.
- Every Spike 2 program has the one-game **COMPETITION** entry and `FG_PLAYER_COMPETITION_MODE_ACTIVE`, flag **17** on
  all 53 latest builds. On the kind-jump menus (`portchallenge._case_flags` over every case) the Competition case sets
  that flag and nothing else (Tournament 16, Challenge 18, Co-op, Jukebox, Impossible, Monster are other kinds).
- Every program's message table has the menu's captions right after `CHOOSE YOUR MODE OF PLAY`: STANDARD 1914 /
  COMPETITION 1919 with ALL RANDOMNESS REMOVED under it (Foo Fighters LE and D&D one higher).

Control (emulator, Deadpool Pro 1.16): the game's own COMPETITION pick has flag 17 set at the game's start and still
set at its game over; the next plain Start's game starts with it clear. So a Competition game is that flag, one game.

## The shape

- **The entry** (`pad_mode_runtime.c` "Prolonged Competition on the start menu"): appended to the start menu through
  the challenges' menu sites (`site challenge_menu`, `site challenge_menu_pick` and their values: the kind-jump,
  compare-chain, wide and live menus of PAD-619). The game's own COMPETITION caption over `UNTIL POWERED OFF`; once on,
  its STANDARD caption over `ENDS PROLONGED COMPETITION`. Picked, the game plays it as Standard (kind 0) and the next
  game's start turns it on, or off.
- **While on**: at the event bus's dispatch of `game_start` (before the game's handlers) the flag is set; a ball start
  that finds it clear sets it again. Turned off: cleared at that game's start. It lives in the runtime's memory, so it
  ends when the machine is switched off, as on Venom.
- **The card**: the Modes tab's **Prolonged Competition** tick (sidecar `prolonged_comp: {"on": true}`) puts `comp.cfg`
  beside the runtime: `comp on`, `flag <id>`, `caption <msg>`, `caption_end <msg>`, read off the card's own program
  (`plugins/stern/prolonged_comp.py`), and `only` on a card with no modes: armed before the score gate and nothing
  else, so the card stays on Insider Connected as the game's own Competition does.
- Venom and D&D keep their own (refused with "has Prolonged Competition on its start menu already").

Scope (David's co-op call, PAD-1017: "just the latest versions"): the latest builds. The tick is offered wherever the
port knows the start menu, which is also every older build PAD-619 ported (49 ports).

## Proof (emulator, hidden, muted; rig kit `C:/tmp/PAD-1041/rig`: job.sh PICK=ours|menu|control, COOPBTN=, go.sh)

- Deadpool Pro 1.16 (kind-jump menu), the whole cycle: the menu showed COMPETITION / UNTIL POWERED OFF as its third
  entry (kinds 0 2 512), picked, `ON - game 1 plays as Competition (flag 17 was 0)`, game 1 over with flag 17 set,
  game 2 started with the flag clear (the game does not prolong) and the runtime set it, game 2 over with it set,
  picked again: `OFF - game 3 plays as the menu picked`.
- Star Wars Pro 1.31 (compare-chain menu): picked, game 1 a Competition game.
- With co-op on the same card (`COOPBTN=62`: the full gate, so the challenges' code hooks the same menu sites and the
  event bus too; the hooks chain): the same whole cycle on Deadpool Pro 1.16.
- The sweep (`l4.txt`, PICK=menu, 4 rigs at 4x): all **37** latest builds whose start menu the app knows showed the
  entry, took the pick and started game 1 as Competition: Aerosmith Pro/LE 1.16, Avengers LE/Pro 1.10, Batman 66 1.14,
  The Beatles 1.29, Deadpool LE/Pro 1.16, Elvira 1.13 (count in a register), Foo Fighters LE/Pro 1.04 (live menu),
  Guardians Pro/LE 1.15, Iron Maiden LE/Pro 1.18, Bond LE/Pro 1.06 (Bond's own menu), JP LE/Pro 1.16, JP The Pin 1.05,
  Led Zeppelin LE/Pro 1.22, Mandalorian LE/Pro 1.45, Munsters LE/Pro 1.28, Rush LE/Pro 1.19, Star Wars ELG 1.10, LE/Pro
  1.31 (compare chain), Stranger Things 1.13 / LE 1.13, Sword of Rage LE/Pro 1.19, TMNT LE/Pro 1.59 (wide entries).
  The first pass failed six on the job's own stepping (menus of 9 to 13 entries, a game still on its boot splash);
  their reruns (r7, r8: shorter steps, PREWAIT=30) passed. Star Wars Pro's whole-cycle job never ends a game there
  (its playfield needs more than the job's switches), so its cycle is not shown; the game-to-game part is the same
  code on every menu.
- Shots: `artifacts/PAD-1041` before/after_start_menu (stock last entry COMPETITION / ALL RANDOMNESS REMOVED; ours
  COMPETITION / UNTIL POWERED OFF), the Modes tab tick.

## Left (round 2)

The menus PAD-619 does not hook as a list yet, so the tick is not offered there:

1. Godzilla (LE/Pro 1.16): the menu of game-mode table indices (`site challenge_menu_frame`, PAD-686, LE only); the
   way in is Competition's index a second time with its subtitle message said as UNTIL POWERED OFF while the cursor is
   on it (as PAD-686's MODE CHALLENGE entry steps through the modes' own).
2. Jaws, John Wick, Metallica, King Kong, X-Men: the GamePlayModes index menus (`portchallenge.gpm_lines`): no menu
   sites in their ports; their start menus' frames are to be found first.
3. Bond 60th LE 1.11: its start menu is an object list built by calls (fn 0x5cf38, `0x5cef0(list, kind, ?, flag,
   caption, text)`), so the entry is one more call after the builder.
