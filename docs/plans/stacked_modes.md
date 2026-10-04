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

## Any title: keeping the game's own modes out (PAD-363)

David, 2026-10-04: "is there a way to extend this kind of thinking to other games? like beatles, deadpool,
etc.? it would be good to have this generic logic (or at least the levers built in for the user to handle)".

- **Where the game starts a mode.** On the C++ rule titles a rule starts one of its modes through a virtual
  of the mode's object at the title's start slot (Godzilla 8, Deadpool 13; the vptr is the vtable + 8). The
  app's stock scanner already finds the slot and every mode's object, vtable and name, so
  `game_mode_blocks.py` (and `sdk/block_tool.py`) write one veto per mode into the port: `site
  block_start_<id>`, `data block_obj_<id>`, `text block_name_<id>`, `text block_default <ids>`. Never a
  multiball. Mode ids run to 127 (D&D's map modes, Venom's minis); a mode outside the game's table takes a
  free id. A start whose first two words cannot run in the trampoline is left out, except `push {.., lr}; bl`,
  which the runtime relocates (hook_veto_bl).
- **Plain-C titles** (and Jurassic Park LE / Rush, whose start slot the scanner misses): `sdk/cstarts/` -
  `find_c_starts.py` finds each mode's start as the function that counts its STARTED audit (at its true
  entry; never a multiball; never one that counts another mode's), `c_port_tool.py` writes the section. A start
  whose caller goes on when it returns non-zero (The Beatles' song select, the story chapters of Stranger
  Things and James Bond) is refused with 0 (`value block_ret_<id> 0`); a start with no object is told apart by
  which hook fired.
- **Rules that are not modes.** Godzilla's Saucer Attack (David's Premium, 2026-10-04: "overlapping text for
  saucer mode feedback under Ghidorah") is fed by the pop bumper and puts its words over ours: `site
  block_rule_<n>` + masks hide those shots from that rule alone while a mode blocks, as the battle rule's.
- **The lever.** A mode file's `game_modes stack|give_way|block` and `block_modes <ids>`; in the Modes tab,
  "The game's own modes > While it runs, the game's modes": may start (this one moves aside), may start and
  end this one, or cannot start, with a tick for each of the title's modes its port names (a mode moved to
  another title keeps its ticks by name). A title with no block lines greys "cannot start" and says why.
- **The log.** `pm_running_name` lets the runtime's own lines name a mode file's mode (`block: the game's
  mode 21 (Chimichanga) did not start - BLOCKTEST is running`).
- **Emulator (deadpool_le 1.14, muted, hidden, rig 2).** A mode file with `game_modes block` holds off
  Chimichanga and Berserker Rage forced through the game's own start (`C:\tmp\PAD-363\stock_force_any.c`,
  an instrument that never goes on a card); with it stopped, the same start runs Chimichanga (the game's
  any-mode query 0 -> 4, its screen up). Ninja Mball's own start declines when forced cold (it wants its
  locks), so the multiball pass-through stays proven on Godzilla only.

## The library check (emulator, 2026-10-04)

Every shipped build, muted and hidden, through `rigbatch.sh` (job `C:\tmp\PAD-363\blockcheck*.sh`): a mode
file with `game_modes block` listing every mode the port names runs; each named mode is started through the
game's own start (`stock_force_any.c`, an instrument that never goes on a card) and must be refused; then the
blocking mode stops and the game's modes are started again until one RUNS (the control: the start found is the
start, and an unblocked start still works through the hook).

| Builds | Named | Result |
|---|---|---|
| Godzilla LE 1.16, Pro 1.15, Pro 1.16 | 15, 15, 14 | pass (control Planet X Hurry Up) |
| Deadpool LE 1.14 / Pro 1.16 | 19 each | pass (Bashpool Hurry Up) |
| Venom 1.07 | 55 | pass (Host Hurry Up, id 56) |
| D&D 1.00 | 29 | pass on its dragon-less settings (Mimic Hurry Up) |
| Avengers, Foo Fighters, Iron Maiden, Jaws, King Kong, Led Zeppelin LE / Pro, Munsters, Star Wars LE, Mandalorian, Sword of Rage, John Wick, TMNT LE 1.59 / Pro 1.59 | 8-28 | pass |
| TMNT Pro 1.58 | 25 | refused 25/25; control by screenshot (its query sees multiballs only) |
| Jurassic Park LE 1.16, Rush 1.18 | 15, 9 | pass (start slots 21, 40) |
| The Beatles 1.29 | 5 | pass (refused with 0; All My Loving ran unblocked) |
| Aerosmith, Guardians, Bond 60th, Bond 1.06, Metallica 1.03 / 1.04, Stranger Things | 1-28 | pass |
| Batman 1.13 | 22 | refused 22/22; control by screenshot (a hurry-up with its clock) |
| X-Men 0.98 | 14 | refused 14/14; control with the mode objects (Future Hurry Up) |
| Jurassic Park The Pin 1.05 | 6 | refused 6/6; control Stegosaurus (through the relocated bl) |
| Star Wars ELG 1.10 | 3 | pass (Inner Loop, through the relocated bl) |
| Elvira 3 1.13 | 1 (every House) | refused 1/1 in the one run that reached a game; the rig crashes Elvira before a game 5 runs in 6, with or without modes (a task of its own) |

Not named anywhere: multiballs (by design), and a few starts the veto cannot take or that nothing calls
(D&D's Finish State / Map Orange 2a / 2b / Purple 1 Hurry Up, Munsters' Madness Hurry Up, TMNT's Pizza
Eating Contest Ready; the plain-C rejects in `sdk/cstarts/json`). A refused start may use up what lit it on
some titles (Stranger Things' award table counts the award before it calls the mode).

## Still to do

- The Scenes editor's "Beside a game mode" view: a mode's screen laid out a second time for when a game
  mode runs (a second screen node the runtime shows instead of hiding).
- Elvira 3's Houses one by one (the House manager's start holds off every House at once today).
- The tab names a C++ mode by its class (Avengers' "Marvel Hurry Up" shows on the glass as "Binary Hurry Up").
