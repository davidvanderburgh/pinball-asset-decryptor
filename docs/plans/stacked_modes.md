# Stacked modes: our words step aside for the game's own (PAD-347)

## What David saw (Godzilla Premium, 2026-10-03)

After playing every example mode on the machine card (PAD-301 + PAD-310 build):

- "during Jet Fighter, when we have a custom mode running as well, the text is overlaid in the exact
  same spot, making it impossible to read either set of text."
- "when I was in multi-ball and I did the outlane oxygen destroyer mode, it should not have triggered
  because I had multiple balls on the playfield."
- "being able to stack modes is a key point in many pinball games that makes it fun."

The card's `/dump/mode.log` agreed: OXYGEN DESTROYER started at 633 s and 784 s while the game's
multiball ran (FINAL WARS and MELTDOWN refused in the same seconds, "a multiball is running"), and the
game's "Jet Fighter" is JET FIGHTER ATTACK (`cmode_jet_fighter_attack`, id 21, a timed mode started by
`RuleJetFighters`), which is neither a battle nor a multiball: the only kinds our modes asked about.

## Why the words collided

The examples' HUD (hud-layers, `mode_hud.py`) copies the game's battle layout: three counters along the
top, the title above the score panel (y 444), the instruction line under it (y 538). The game's timed
modes use the same places. Stern never shows two modes' words at once: one mode has the middle of the
screen, the others keep to their badges at the edge (BATTLE, DOUBLE SCORING, TESLA down the left).
ANGUIRUS already stacked that way on a battle (its words in the award line, its gauge on the right).

## David's decisions

1. Stack, ours moves aside - generic for every title, with the Scenes editor as an optional override.
2. During a multiball our single-ball modes stay ready and start on the next qualifying shot after it.
3. The game starting its own multiball or battle while ours runs: ours keeps going, aside.

## What changed

- **Runtime** (`pad_mode_runtime.c`, `pad_mode.h`): `pm_aside()` = the kind of the game's mode active
  for the player up (battle, then multiball, then any) or 0, asked at most every 200 ms, each change
  logged. 0 outside a game and on a port that cannot tell.
- **The examples' HUD** (`intricate_kit.h`): while aside, the mode's title and line move into the award
  line (an award still takes it for its moment), the counters are hidden, the gauge stays, and the timer
  badge moves to a second slot (y 376) while a battle's BATTLE badge has the top one. A card built before
  has no second slot: the badge hides during a battle.
- **The card build** (`mode_hud.py`): `PadMode_<slug>_Hud_Timer2`, the badge one slot down.
- **Start rules**: KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE wait out a multiball (the game's, or
  two balls in play) and stay ready (`kit_wait_multiball`).
- **Mode files** (`mode_file.c`): the mode's own screen hides while a game mode runs and comes back after;
  `aside keep` leaves it up.

## Coverage

35 of the 37 shipped builds can tell a game mode is running (manager queries on the three Godzillas, the
mode table on 21, the balls in play plus the game's own flags/records/bytes/objects on 11). The Beatles
1.29 and TMNT Pro 1.58 see only multiballs.

## Proof

- Desk: `tests/test_spike2_intricate_modes.py` (aside layout per mode, the award line while aside, the
  badge's second slot, the multiball waits for three modes x two kinds of multiball) and
  `tests/test_spike2_mode_aside.py` (a mode file's screen).
- Emulator (godzilla_le 1.16, muted, hidden): JET FIGHTER ATTACK forced through the game's own mode manager
  (`C:\tmp\PAD-347\stock_force.c`, an instrument that never goes on a card), MASER BARRAGE started beside it;
  before (main) and after (this branch) shots of the glass.
- Machine: a card built by Write from this branch for David's Premium.

## Still to do

- The Scenes editor's "Beside a game mode" view: a mode's screen laid out a second time for when a game
  mode runs (a second screen node the runtime shows instead of hiding).
