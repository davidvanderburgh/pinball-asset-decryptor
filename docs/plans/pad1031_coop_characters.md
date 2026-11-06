# PAD-1031: co-op characters - each teammate picks one, each one plays differently

DoomWalrus666 (Godzilla): at the start of each player's ball 1 the battle selection screen comes up with versions of
Godzilla (1954, GMK, 2000, 1985, Destroy All Monsters, Burning ...) in its tiles and portrait; each player picks one
(or Random), no two the same, and each has its own ability:

    longer ball save                       easier to light battles          starts with 4 jets destroyed
    ball save on the Action button         starts with a random ally        starts with 4 tanks destroyed
    easier to light the heat ray           spot a shot in a battle (Action) Tier 2 unlocked by STARTING a Tier 1 battle
    easier power-ups                       easier to start Building Multiball

daveyvandy: a customization of PAD-1017's co-op, Godzilla-specific, "but the user needs the ability to customize
co-op mode like this for other games as well ... a generic entry point ... deliver the co-op customization file
adjacently".

## The shape

Co-op plays ONE player for the team (PAD-1017): the progress is shared, the runtime knows whose turn it is. So a
character is a set of abilities that hold **while its teammate is up**, and a one-time gift at its teammate's first
ball. Nothing per player has to be copied.

- **coop.cfg** (generic; the Write tab writes it from the project's sidecar `coop_play.characters`):

      pick on                                  each teammate picks at their first ball (RANDOM is offered last)
      left 60                                  the left flipper button (the pick walks with both flippers)
      action 34                                the Action button (the pick; the ball save ability)
      character adj:94=15 GODZILLA 1954|LONGER BALL SAVE
      character save:10 GODZILLA 2000|ACTION BALL SAVE
      character adj:195=4 GODZILLA GMK|EASIER HEAT RAY

  `adj:<id>=<v>`: the game's adjustment `id` reads `v` while the teammate is up (the getter, `site adjustment`, is
  wrapped; NVRAM is never written). `save:<s>`: a double press of the Action button gives an `s` second ball save,
  once a ball. Godzilla's own (run 2): `gift:<id>` one of the game's own one-shot feature adjustments fired at the
  teammate's first ball (the adjustment-changed handler 0x595b8 on Pro 1.16: LIGHT ALLY 311, ADD 1 POWERUP 312,
  LIGHT SELECT CITY 310 ...), `jets:<n>`, `tanks:<n>`, `spot`, `tier2`.
- **The pick** (generic): the game's top line ("BALL %d", PAD-1017's borrow) reads `PLAYER 2 PICK: GODZILLA 1954`
  and then what it does, in turn; the flippers walk (taken ones skipped), Action takes it, 20 s takes the one shown.
  RANDOM takes one nobody has.
- **Godzilla's look** (run 3): the battle selection screen (PAD-707's tiles, portraits and cursor walk) dressed with
  the characters' pictures while a teammate picks.
- **The customization file**: `coop_presets/<title stem>.json` beside coop_play.py (Godzilla's: the eleven abilities,
  names after the reporter's list; pictures are the owner's), loaded in the Modes tab's Characters... dialog; any
  game gets the generic abilities its program's adjustments allow.

## Godzilla's adjustments (Pro 1.16 / LE 1.16 ids)

| ability | how | id |
|---|---|---|
| longer ball save | AD_BALL_SAVE_TIME at its max (15) | 94 |
| easier heat ray | AD_HEAT_RAY_SPINS_PER_LEVEL at its min (4) | 195 |
| easier battles | AD_LIGHT_BATTLE_DIFFICULTY at its min (0) | 173 |
| easier Building Multiball | AD_BUILDING_DIFFICULTY at its min (0) | 168 |
| random ally | gift: LIGHT ALLY (0x11f318 on the ally object) | 311 |
| easier power-ups | run 2: the power-up add (0x149654(obj, n)) counts double while up | - |

## Runs

1. Generic: coop.cfg lines, the runtime's pick and abilities (adj, save), coop_play.py's catalog and cfg lines,
   tests, emulator proof on Godzilla LE 1.16 (the pick walk, the adjustment read while up, the Action save).
2. Godzilla's own: gift, power-ups, jets, tanks, spot a shot, tier 2 (RE in the emulator).
3. The Modes tab's Characters... dialog and the preset; Godzilla's battle selection screen as the pick; docs.

## Run 1 (2026-11-06): done, emulator-proven

Godzilla LE 1.16, 3 teammates, rig kit `C:\tmp\PAD-1031\rig` (job.sh, gz.cfg, go.sh l1.txt <out> as root):
teammate 1 picked GODZILLA 1954 with Action (each join re-opens teammate 1's pick: the joiner's held right flipper had
walked it to the 2nd character in the first run); the ball out got its save at the pick (`ball save: 15 s`); the
getter answered 94 -> 15 (its own 12) at each later save; teammate 2 picked 2000 and two Action presses gave a 10 s
save that gave a drain back; teammate 3's left walked past 2000 and 1954 (taken) to RANDOM, right back to GMK, and the
heat ray read 195 -> 10 (its own 20) at every spin. No faults. The Modes tab's Characters... dialog and Load
Godzilla's set work (shots in artifacts\PAD-1031).

Learned: the game's top line ("BALL %d") is small on Godzilla and a long name runs into CREDITS - the pick needs a
display of its own (run 3). LIGHT BATTLE DIFFICULTY and BUILDING DIFFICULTY are copied into the player's record at the
game's start (Pro 1.16 0x12175c / 0x12b7a4: `str adj, [this + player*4 + 0x10]` / `+4`), so the getter alone does not
change them: run 2 writes the record while the teammate is up. The one-shot "feature" adjustments 309-334 (LIGHT ALLY,
ADD 1 POWERUP, LIGHT SELECT CITY ...) are acted on by the adjustment-changed handler (Pro 1.16 0x595b8, `{u16 id}` in
r0), which then sets them back to 0: run 2 calls it with the getter answering 1.

## Left

2. Godzilla's own: battles + building (the player record), random ally (LIGHT ALLY through 0x595b8), easier power-ups
   (the power-up add 0x149654 counts double while up), 4 jets / 4 tanks destroyed at the first ball, spot a shot in a
   battle on Action, tier 2 after STARTING a tier 1 battle. Ports: Pro 1.16, LE 1.16, Pro 1.15.
3. The pick's look. David (2026-11-06): the design is open-ended, so DoomWalrus666 approves it - better, he can iterate
   it on his side without blocking a release. So: each character's picture (his own files, never bundled) in the
   Characters dialog, a still preview of the pick screen there (battle_select.preview's way), and on Godzilla the
   battle selection screen dressed with them (PAD-707's tiles/portraits/cursor walk) while a teammate picks; any other
   game a screen of the runtime's own (the build's mode-screen node) in place of the top line.

## Run 2 (2026-11-06): Godzilla's ally, battles, building, power-ups - mechanics emulator-proven

Runtime kinds: `boost:<pct>` (`site coop_boost`, the title's add-n call, n scaled while up), `gift:<id>` (`site
coop_adj_changed`, called with {u16 id} at the pick while the getter answers 1 once) and the record holds (`site
coop_cache_<id>` hooked to learn the rule's object, `value coop_cache_<id>_at`; held at what the getter would answer
while up, given back as the harder of the team's own and what play made of it). Port lines on LE 1.16 and Pro 1.16
(Pro 1.15 has no co-op: none). LE 1.16 / Pro 1.16: adj-changed 0x598b4 / 0x595b8, power-up add 0x14cb3c / 0x149654,
battle record 0x12406c / 0x12175c (+0x10), building record 0x12e168 / 0x12b7a4 (+0x4).

Rig run r3 (job2.sh, gz2.cfg, 4 teammates): the battle rule at 0x7b0c70 and building rule at 0x7b1d10 seen at the
game's start; DESTROY ALL MONSTERS' gift: "the game's own feature 311 given (it read it)"; GODZILLA 1985: the battle
record held 0 (team's 1) in each of its turns, back to 1 at their end; MOTHRA: building held 0 (team's 0); no fault.
No power-up was earned in that play, so the boost never fired.

## Left (run 3+)

- Visible proofs: an ally lit after the gift (lamps/ally state), a battle lit by ONE ramp while GODZILLA 1985 is up
  (two for the others), a power-up counted twice (a play that earns one, or the ADD 1 POWERUP gift `gift:312` with
  `boost:200` in a test cfg: "the game adds 1, 2 with the boost").
- Jets / tanks at the first ball: JET FIGHTER count = rule 0x15 (manager 0x7b0ce4 lookup 0xd3fa0) + p*4 + 0xa8 (LE),
  a bonus/champion count; the TANKS n/10 qualify is the tank rule's record (init 0x180e44 on LE: +4 qualify difficulty,
  +(p-1)*4+0x18 cleared) - find the kill increment and what qualifies, then a `count:` kind (record += n at the pick).
- Spot a shot in a battle on Action; tier 2 after STARTING a tier-1 battle (PAD-706's battle progression code).
- The pick's screen (run 1's note) and the Characters dialog's pictures/preview.
