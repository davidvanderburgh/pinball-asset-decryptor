# PAD-1404: menus picked with the flippers

Row 8 of the PAD-1398 analysis (`pad1398_xmen20_gap_analysis.md`): a mode shows a list and the player picks with the
flippers (move) and Action or Start (choose), with a timeout default, the ball held or the game waiting while it is
open, as Stern's own choose screens do. For Uncanny X-Men 2.0's episode pick through the portal and a mutant or roster
pick at the game's start, and any "choose your mode". X-Men has no challenge route and the team start menu skips it,
so this is the mode's own.

## What was there

- PAD-1403: the Action, flipper and Start buttons are button shots on every title (`buttons.cfg`, the switch ids read
  off the card's own program).
- PAD-1405: a mode's screens beyond its one panel (meters, fades) built into the title's HUD scene, driven by the kit.
- PAD-1051: the runtime can hold a switch back from the game (the co-op pick's hider), used only by co-op.

## Design

- **Screens** (`mode_menus.py`): per menu (two a mode) a panel `PadMode_<slug>_Menu<k>` (dark glass, a rim and a line in
  the menu's colour, the title its words), five rows `..._R<j>` (an item's words over a highlight bar layer `_Hi`) and a
  foot `..._Foot` (what the buttons do, the seconds left). Drawn last: over every other screen of the modes'.
  Premultiplied. Words centred by offsetting their scaled box.
- **Kit** (`intricate_kit.h` `kit_menu`): open (title, items by pointer, default, ms, hold), shot (left up, right down,
  both wrapping; Action or Start takes; the menu's buttons never reach the mode), tick (finds the screens, draws what
  changed, scrolls a window of five, counts down, renews the hide, answers the item taken once), close.
  Time out takes the one HIGHLIGHTED: it opens on the default, so doing nothing gives the default (decision below).
- **Hold**: `lane` (a ball's start: the launch button is the menu's; a named playfield shot - the plunge - takes the one
  shown), `scoop` (pm_scoop_hold, kick-out at most 10 s after it settled, so the time is cut to 9 s; refused by
  `problems` on a title without a scoop), `none`. The blocks mode's clock waits while a menu is open (Stern's choose
  screens pause the mode). X-Men has no scoop in its ports, so its portal pick uses `lane` or `none`.
- **Runtime** (`pm_button_hide(shots)`): the switches behind those button shots go through PAD-1051's hider
  (`coop_hides` now asks `btn_hides` first; the edge hook runs the hider while a hide is asked). Renewed every tick;
  lapses after 500 ms; 0 = off at once. The button shots still count (btn_edge runs before the hider). Works where the
  hider does: `switch_desc_via` and the level byte after the edge (59 of the 69 ports); elsewhere it answers 0 and the
  game sees the presses too.
- **Blocks**: `menus` in the program (name, title, items, default, seconds 3-60, hold, colour), Open the menu / Close the
  menu, the hat When the player picks from a menu, the value the item picked (1..n, the player up's last this game).
  The mode's end (before When the mode ends) and the ball's end close an open menu with nothing picked. Script view,
  Story (a pick rule is "any time"), node graph (a menu is a thing), timeline (screen lane).
- **Absorbed**: `CodeAssets.has_assets()` ignored PAD-1405's meters and fades and PAD-547's info line, so Try it compiled
  such a mode in alone and its screens never showed; it now counts them (and menus).

## Proof

Emulator, stock Uncanny X-Men LE and Pro 0.98, built through the app's own Write (`C:\tmp\PAD-1404\mkset.py`:
engine.write_overrides with a blocks EPISODE PICK mode), run by `go.sh` / `job.sh` (rigbatch, x1).

- **X-Men LE and Pro 0.98, the whole job** (`job.sh`, run r4, both PASS). The game started by coin + Start, so the ball
  waits in the shooter lane. The menu found (5 rows, title, foot) and drawn in the middle of the glass on the default
  (DARK PHOENIX); right x2, left x4 wrapped to MOJOVERSE with the list scrolled; Action took it (the game did not see
  switch 34: no launch, the ball still in the lane); opened again, Start took it and the game added no player (switch 36
  held back; the frame shows PLAYER 1 alone); again, its 12 s ran out and the highlighted one was taken; again, the
  plunge and the ball's first hit (the Xjet target, switch 50) took the one shown. Controls after: Action reached the
  mode's own Action script, and Start added Player 2. Score 12,000 = the three picks' 7,000 + 2,000 + 3,000.
  Frames: `C:\tmp\PAD-1404\out_le`, `out_pro`; the ticket's artifacts `after_in_game*.png`.
- **Every newest Spike 2 build** (`build_all.py`, `sweepjob.sh`; 53 cards each built by the app's Write): 53 of 53
  PASS - the menu found with 5 rows on all 53, Action (Start on The Beatles, JP The Pin, Star Wars ELG) took the one
  highlighted after a right flipper press, and its time took it again; the game kept from seeing all 4 buttons on 50
  and the 3 there are on the three with no Action button. Round 1 lost 30 jobs to rig 2's stale `ballfeed.off` (the park lapsed: rig locks are
  5-minute leases, so the rerun renewed it) and failed Godzilla LE/Pro 1.16, whose Action and flipper buttons are the
  port's PAD-228 `switch` lines, not buttons.cfg: `pm_button_hide` now maps those too (only Godzilla's ports have them).
  TMNT LE 1.59 needed the rig's full game start (its first boot ignores coin + Start).

Found on the way: the menu first took a button's RELEASE shot as the ball moving on; every button shot (press,
release, hold, combo: every name with "button") is now the menu's, and only a named shot that is not a button's moves
the ball on; that pick names the shot ("the ball moved on: Xjet tgt").

## Decisions

- When the time runs out the HIGHLIGHTED item is taken, not always the default (it opens on the default, so doing
  nothing still gives the default; a player who moved the cursor and waited gets what they were looking at).
- The game does not see the menu's buttons while it is open (Stern's own choose screens); the flippers still flip.
- Holds: lane (default), scoop, none; the mode's clock always waits while it is open. No game-timer pause: the runtime
  has no generic one (PAD-1022's is Guardians-only), and with the ball held nothing of the game's runs down meanwhile.

