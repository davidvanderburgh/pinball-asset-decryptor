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

## Blocks modes get the same lever (PAD-373)

David, 2026-10-04: "Ideally the blocks provide the same amount of integration as the C code". A blocks
mode's `blocks.json` carries `game_modes` (stack, the default and what every blocks mode did before;
give_way; block) and `block_modes` (ids; [] = the port's checked defaults), and its editor shows the form's
row and ticks. The generated C does what the examples do with the kit: a Start the mode waits while one of
the game's modes runs or two balls are in play (kit_wait_game; the tab's Start mode now does not wait), it
calls pm_block_list + pm_block_game_modes after pm_begin (kit_isolate_list) and lets go in end, and one of
the game's modes beginning ends it at once (kit_game_began) - except that its own Multiball block's balls
are not taken for the game's multiball while they are in play.

- **Emulator (godzilla_pro 1.16, muted, hidden, rig 1; `C:/tmp/PAD-373/job.sh`).** MASER BARRAGE's
  isolation rebuilt in blocks (the Maser target starts it, block 21 23): the Maser target switch started it
  and the runtime said "keeps the game's modes 21 23 (its own list) from starting"; Jet Fighter Attack and
  Tesla Strike forced through the game's own start were refused; Planet X Hurry Up (not ticked) ran and
  ended ours in the same tick ("lets the game's modes start again"); a Maser target during the hurry-up
  logged "not started (a block): a stock mode is running" and did not start it.

## Still to do

- The Scenes editor's "Beside a game mode" view: a mode's screen laid out a second time for when a game
  mode runs (a second screen node the runtime shows instead of hiding).
- Elvira 3's Houses one by one (the House manager's start holds off every House at once today).
- The tab names a C++ mode by its class (Avengers' "Marvel Hurry Up" shows on the glass as "Binary Hurry Up").

## Our modes run alone (PAD-398)

David, 2026-10-05, after three sessions on his Premium with ten examples: "we still need to work on isolating our
multi-balls and modes. while in those, we cannot start other modes (destruction jackpot, scoop, bridge multi-ball,
etc.) this causes issues. when our custom modes start, we should ONLY be in those modes unless explicitly noted."
And on the plan: "Yes confirmed do that. As long as our users will have that flexibility in the app to customize it
how they like."

- **What went wrong on the machine.** SPACEGODZILLA's crystal multiball was ended 20 s in by the game's own
  multiball, twice, with its balls still in play; the game's Destruction Jackpot then sat in the scoop with the
  lights held. Its towers are on the Building and the ramps, and the game's rules counted those shots all along -
  most likely its building locks lit and locked its own multiball. DESTOROYAH was ended 4 s in by a game mode.
  The PAD-363 isolation refused only the port's two checked defaults (Jet Fighter Attack, Tesla Strike) and hid
  shots from two rules (battle, Saucer Attack).
- **What a blocking mode does now.** It refuses every mode of the game's the port names (all 15 on each Godzilla),
  and every rule of the game's that reads shots - 24 on each Godzilla, read from the program by
  `game_mode_blocks.read_rules` (RTTI `Rule*` classes whose v[25] reads shots; the battle rule stays
  block_battle_shots) - sees each shot without any bit. Nothing of the game's lights, locks, counts or awards, so no
  multiball of the game's can be qualified while ours runs; its progress waits and goes on after.
- **The default.** "cannot start" (block) for form modes, block modes and code modes; a mode file or blocks
  program that says nothing blocks; an unknown value reads as block.
- **The levers (David: flexibility in the app).** The Modes tab's "While it runs, the game's modes" keeps may start
  / end this one / cannot start; under cannot start, the game's modes ticked (all, the last tick stays) and "The
  game's features that keep counting while it runs" (none ticked: only this mode counts). The blocks editor has the
  same two lists. A code mode's assets.json takes `keep_rules` (names). In the files: `keep_rules <numbers>` (mode
  file, assets file), `KEEP_RULES "<names>"` (a blocks mode's C).
- **Proof (emulator, Premium/LE 1.16, rig 1, muted, hidden; C:/tmp/PAD-398).** A form mode with the default, the
  same 42 shots before, during and after it: before, POWERLINE ATTACK came up; during, the HUD's TANKS 1/10 and
  BRIDGE 75% 15/30 did not move and the log said once that the rules saw none of the shots; after, JET FIGHTER
  ATTACK started at once. With `keep_rules` naming the bridge and the tanks, the bridge went on (15/30 to 15/40)
  while the rest stood still.
- **Not measured.** A lock lit before ours began and a ball arriving in it while ours runs (the game's multiball
  start is still not refused: theirs would start and end ours); every Godzilla feature shot by shot; the other
  C++ rule titles (PAD-400, below).

## Our modes run alone on the other titles too (PAD-400)

The open item from PAD-398: the rule lines existed only on the three Godzilla ports, because the reader took
Godzilla's shot handler (`Rule::v[25]`) as every title's.

- **What is generic.** Every C++ rule title's rules are singletons of one rule base - `Rule` (Godzilla, Avengers,
  Deadpool, Jaws, King Kong), `crule` (Venom, Mandalorian, D&D, John Wick, Foo Fighters, Sword of Rage, where the
  game's modes are crules too and are left out: their starts are refused already) - and each hears a shot in ONE
  virtual of that base, the 64-bit shot mask in r2:r3. Only the slot differs: Godzilla 25, Avengers 28, Deadpool LE
  31 / Pro 32, Jaws and King Kong 27, and on every crule title its base's second-last (Venom and John Wick 40, D&D
  43, Mandalorian 31, Sword of Rage 23, Foo Fighters 34). `game_mode_blocks.shot_slot` reads it from the program:
  the base virtual most rule classes override with a function that reads r2 and r3 before writing them (three or
  more, a fifth of the rules, and more than any other slot). The runtime needed nothing.
- **What is hooked.** A rule's own handler (not the base's, not a no-op), when the runtime's plain hook can move
  its first two words (`hookable`: a literal load is relocated; a `push; bl` start is refused, which the veto test
  `movable` let through). A handler several rules share is listed once, named for the class that defines it
  (Deadpool's four team-ups: Team Up Shot; an abstract base when every rule under it shares it). Names read as
  features: cdragon_rule -> Dragon, ctinys_dice_game_rule -> Tinys Dice Game, AtticAttackMultiballRule -> Attic
  Attack Multiball; two of one name are told apart (Venom: Host Combo, Host Combo Rule).
- **Ports.** Avengers 23, Deadpool LE / Pro 12, D&D 18, Foo Fighters 17, Jaws 22, John Wick 20, King Kong 21,
  Mandalorian 12, Sword of Rage 14, Venom 19 (sdk/rule_lines.py); the three Godzilla ports read back identical.
  A drafted port gets its own the same way (portgen block_section). Recipes rebuilt: unchanged (no rule lines).
- **Not covered.** Iron Maiden, Jurassic Park, Elvira, TMNT, Star Wars: their rule base has no virtual that takes a
  shot mask (Iron Maiden's and Jurassic Park's rules are HookListeners - they hear switches; Elvira's base has 15
  virtuals) - nothing is guessed, they get no rule lines; that needs a switch-hook route. X-Men's `Rule_*` classes
  have no base. Led Zeppelin, Munsters, Rush (crule) show no mask handler either. Plain-C titles: sdk/cstarts.
- **Proof (emulator, stock cards, rigs 1-3, muted, hidden; C:/tmp/PAD-400, rigbatch + job400.sh).** A form mode
  with the default on each title, started by trigger as soon as the ball was in play, every safe playfield switch
  worked (swexercise) during and after it. 11 of 12 pass: every rule the port names hooked (none refused), the
  mode started, and the runtime said the rules saw no shots, each first one a shot bit (Avengers Hawkeye Combo
  0x01000000, Venom Multipliers 0x1000, Jaws Pipit 0x00200000_00000001, King Kong Banana Combos...). On the HUD:
  Avengers' 80 spins / 50 pops / 3 shots stood still during and the same switches locked a ball after; Venom
  stayed at Level 2 and 1,113,980 during, and reached Level 5, ball 2 locked, 6,354,790 after. Godzilla Pro 1.16
  passed as the control. Deadpool LE 1.14: its 12 sites hooked, but no game starts on this rig (the same with
  main's port, no rule lines - a rig matter); Deadpool Pro 1.16, the same code, passed.

