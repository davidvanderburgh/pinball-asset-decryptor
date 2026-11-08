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
  and then what it does, in turn; the flippers walk (taken ones skipped), Action takes it, 20 s takes the one shown
  (PAD-1044: 30 s by default, `pick_time`, counted down on the glass; PAD-1066: a flipper press starts it again).
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

## Run 3 (2026-11-06): visible proofs; jets/tanks not yet

Rig kit additions: `rig/memrd.py <dump> <addr>...` reads THIS slot's game memory (guest at +0x10000 in the host
process; guestmem.py takes the first `game` on the box), job4.sh (proof job), job5/6.sh (counts).
- Ally (run gz_run4, mem.txt): LIGHT ALLY's object 0x7b2e28 (LE), ally vector at +0x1c, 16-byte entries, word
  (player - 1): before the pick 0/0/0, after the gift 0/0/1 - it lights the next unlit ally in the game's own order
  (0x121c28), not a random one (the ability says so).
- Easier battles: battle rule 0x7b0c70 (+0x14 difficulty, +0x24/+0x34 left/right ramp still needed, player 1): the
  control teammate's one left ramp left 1/1 and the map said SHOOT RAMPS TO LIGHT BATTLE; GODZILLA 1985 (held 0):
  one left ramp -> 0/0 and the map said BATTLE READY; the next teammate: difficulty back to 1. Proof frames in
  artifacts\PAD-1031\proof_*.png.
- Double power-ups (gz_run3): ADD 1 POWERUP through the gift path, boosted: "the game adds 1, 2 with the boost" and
  the power-up meter filled two segments.
- Building: same mechanism as battles (held 0, given back); the rig's BUILDING DIFFICULTY is already 0, so no visible
  difference to show.
- `count:<name>+<n>` is in the runtime (site coop_count_<name> = the rule's game-start method, hooked; value
  coop_count_<name>_at = this + player x 4 + at). NOT in any port yet: jets at the method 0x15c7a8 (LE; Pro
  0x159084) +0xa4 wrote 4, but the bonus (0x197260: rule 0x15 + p*4 + 0xa8) and the champion getter (0x6425c: via
  0x3386e0(player)) index the player differently - prove which slot is read (the PAD-1028 champion award's count, or
  the bonus page) before shipping. Tanks: 0x180e44 (Pro 0x17d46c) +0x14 is NOT the map's TANKS n/10 (it stayed 0/10);
  no rig press killed a tank (scoop, Godzilla target, left ramp) - find what does, then diff the rule (job6.sh).

## Left (run 4+)

- Jets and tanks fields (above), then their port lines on LE 1.16 and Pro 1.16.
- Spot a shot in a battle on Action; tier 2 after STARTING a tier-1 battle.
- The pick's screen, and the Characters dialog's pictures/preview (David: DoomWalrus666 iterates the look himself).

## Run 4 (2026-11-06): jets and tanks

- Tanks: a diff of the tank rule (0x7b0d68 on LE) across 64 shots: +0x48 went 0 -> 1 with the map's TANKS 1/10, so the
  count is this + (player - 1) x 4 + 0x48 (port `value coop_count_tanks_at 0x44`; +0x18 was wrong). gz_run9: 4 at the
  pick, three tanks killed by shots, the map read TANKS 7/10 (proof_tanks_4_plus_3.png). The count is the game's per
  ball/city one: it was 0/10 again in teammate 2's turn, as the game resets it.
- Jets: the game's readers (JET FIGHTER CHAMPION's getter 0x6425c, the bonus 0x197260) use rule_table[0x15] (LE table
  0x7b4aa8, Pro 0x7a83f0; 0x3386e0 only checks the player is 1-4) + player x 4 + 0xa8. The hooked method 0x15c7a8 is
  another rule's. The runtime takes `data coop_count_<name>_rule` (where the game keeps the rule's pointer: LE
  0x7b4afc, Pro 0x7a8444). gz_run9: rule 0x7b5b20, 0x7b5bcc = 4 after the pick.
- Pro 1.16 lines: tank method 0x17d46c (+0x18 / +0x48 stores matched), jets getter 0x63de4 (rule 0x15, +0xa8).

## Left (run 5+)

- Spot a shot in a battle on Action; tier 2 after STARTING a tier-1 battle (the game unlocks tier 2 on a WON city:
  CBattle::stop's bookkeeping, MODE_SDK "A monster in the roster").
- The pick's screen: per character a screen (picture + words) in the HUD scene, as a mode's own (scene_write.
  add_screens via mode_assets.build), shown by the runtime while that character is the pick's; coop_plan has no
  build today (build=None) - a co-op card with characters needs one. Pictures are the owner's (Characters dialog),
  with a preview there so DoomWalrus666 can iterate the look himself.

## Run 5 (2026-11-06): the pick's own screens

- Build: one screen per character (`PadCoop_<n>`) and `PadCoop_Random` in the HUD scene (scene_write.add_screens, as a
  mode's own screen): the owner's picture (Characters dialog, Picture...; copied to `<project>/coop/`) or a generated
  panel with the name; the words "<NAME> - <WHAT IT DOES>". With modes they go into mode_assets.build's pass; co-op
  alone, coop_into rewrites the HUD from the stock one (the engine now reads the HUD for a co-op pick: fixed the bank
  path it cleared with it, found by the end-to-end build). coop.cfg `screens <scene>`.
- Runtime: finds the 12 nodes once the scene is up, hides them, shows the one the pick is on; the top line then says
  only PLAYER n PICK (it overflowed into CREDITS with names and abilities).
- Proof: engine.write_overrides on a scratch project (Write's own path; C:\tmp\PAD-1031\tryset2.py -> ovr2), rig
  jobpick.sh with PAD_OVERRIDE_DIR: "12 of the pick's 12 screens found ... hidden"; the stand-in picture with GODZILLA
  1954 - LONGER BALL SAVE; right -> the GODZILLA 2000 panel; left x2 -> RANDOM; Action -> gone. artifacts
  before_/after_pick_screen.png, proof_pick_*.png.
- Dialog: Picture... / clear / preview (coop_play.preview: the screen on a dark glass) per character.

## Left (run 6+)

- Spot a shot in a battle on Action; tier 2 after STARTING a tier-1 battle.
- MODE_SDK.md / help: the new kinds (boost, gift, count, caches, screens) and the pick screens.

## Run 6 (2026-11-06): spot a shot, tier 2, docs

- Spot: `spot:<rules>`: two Action presses during a running battle (rules 12-18, `pm_stock_active`) send its lowest
  lit shot through Godzilla's own shot dispatch (0xd3e2c LE: a static walk of every rule's v[15] with the mask in
  r2:r3 and a factor on the stack), once a ball. gz_spot3: rule 15's lit 0x800 -> spotted -> lit 0x0.
- Tier 2: the selection screen's slot state (LE 0x122ae8) reads UNLOCK ALL MONSTER BATTLES (334) live; `unlock:334@
  0xf000` answers 1 once a tier-1 battle has started on the teammate's turn. gz_spot3: places at the pick 0 0 0 0 1 1 1
  (tier 2 locked), after rule 15 started 0 0 0 0 0 0 0.
- MODE_SDK.md (every kind, the screens, the proofs), help text, the Characters dialog's shot.

- Pro 1.16 (gz_pro4, rig kit C:/tmp/PAD-1031/rig jobpro2.sh / gzpro2.cfg: one test character with every
  port-dependent kind, all in teammate 1's turn - the Pro rig's drains never ended a ball): the boost (1 -> 2), the
  ADD 1 POWERUP and LIGHT ALLY gifts read, tanks and jets +4, both difficulty records held 0 (team's 1), places 0 0 0 0
  1 1 1 -> all 0 after Ebirah started, the spot sent Ebirah's 0x200. No fault.

## Done

All eleven abilities on Godzilla LE 1.16 and Pro 1.16, the generic pick (every co-op game), its screens, the
Characters dialog and Godzilla's customization file. Pro 1.15 has no co-op.

## The cards and the Discord bundle (2026-11-06, David)

David: "production quality" and "render the character selects with the examples he provided in discord ... bundle
those assets on the discord chat on release (not bundle them in the app)". coop_play.pick_card draws one finished
select card per character (header, lit portrait frame, name, ability badge + CARD_LINES, roster strip, controls; 2x,
flattened over an opaque body and premultiplied: ImageDraw replaces pixels and the game blends premultiplied). The
eleven stills are cut from his collage (artifacts\PAD-1031\mail, 8x4 tiles: 0 1954, 3 KingGoji, 8 DAM, 10 MosuGoji,
16 1985, 17 BioGoji, 19 1993, 21 Burning, 22 2000, 23 GMK, 31 Shin minus the watermark) into
artifacts\PAD-1031\discord\godzilla_characters (+ .zip, README): NEVER in the repo (Toho stills). The dialog's
Pictures from folder... (coop_play.pictures_from_folder: files named picture_file_name(name)) installs the bundle in
one click. Emulator rc4: the cards with his stills on Godzilla LE 1.16, 12 of 12 found. On release: attach the zip to
the Discord thread.

## Round 2 (2026-11-07, DoomWalrus666 on the thread)

Three abilities in place of three of the set (and offered to everyone in the builder): ADD A BALL (`addball:1`:
Action x2 in regular play, pm_multiball_add through the game's serve; proven: "2 balls asked for (2 in play now) ...
the game serves it"), MASER ALWAYS LIT (`yes:maser`: the tank rule's "in the Maser phase" check, LE 0x108d20 / Pro
0x1064e8, used by its lit-shot query 0x10953c and its handler 0x10a058, answers 1 while up), EASIER BRIDGE + TANKS/JETS
x2 (`adj:176=0` through a record hold, cache site LE 0x1349c4 / Pro 0x1316a0 at +4, proven held; `double:tanks,jets`:
each rise of one the game makes gets one more from the tick; proven 4 -> 6 -> 8 -> 10 -> 12).
Open: Tank Attack did not start at 10 or 12 in the rig (neither organic nor doubled) - the goal check is not in the
tank rule's own code (the reads of +0x48 with a `cmp #9` are the bridge rule's); the Maser proof needs Tank Attack.
Godzilla's set: GODZILLA 1985 -> addball, GODZILLA VS BIOLLANTE -> maser, GODZILLA VS MECHAGODZILLA -> bridge; the
old three stay in the builder. The eleven stills zip must sit at the TOP of artifacts\PAD-1031 (pad_bot posts a
top-level <name>.zip after the reply; in discord\ it was never seen).
Later in round 2: Tank Attack LIGHTS at TANKS 10/10 (the tank rule's +0x18 goes 0 -> 1, a doubled count trips it
too) and STARTS on the Godzilla target with the scoop held (+0x18 = 2); the Maser check is only asked while it runs
(proof_tank_attack_doubled_maser.png).

## Round 3 (2026-11-07, DoomWalrus666 on the thread)

Three sharpenings. MASER AT ALL TIMES: `lit:maser=0x8000000` beside `yes:maser` - `site coop_lit_maser` is the
base-play rule's shot handler (LE 0x1645ac / Pro 0x160bd8, the rule that pays MASER CANNON AWARD), hooked to learn
the object; the tick ORs the Maser bit into its lit u64 (this + stock_field 0x18 + 8 x player) and keeps the player's
charge word (+0x14 + 4 x player, `coop_lit_maser_at`/`_min`) at least 1, since the award wants it non-zero; taken
out at the turn's end. Proven LE and Pro: lit lo = 0x8000000, charge 1, and on LE the Maser cannon fired on the target
hit in regular play (proof_maser_regular_play.png). AN ALLY EVERY BALL: coop_chars_turn gifts again at each later
turn of the teammate (gift:311 -> LIGHT ALLY). TIER 2 ALWAYS OPEN: `unlock:<id>` without @rules reads 1 whenever the
teammate is up (UNLOCK ALL MONSTER BATTLES 334, read live by the selection screen's slot state), so every battle,
tier 2 included, is open at any battle select of theirs. Words in the dialog, help and SDK follow.
Proven on LE with two teammates: LIGHT ALLY given at the pick and again when teammate 1 came back for ball 2 (the
ally list went 0 0 1 -> 1 0 1), and all seven battle places open at the pick. The LE rig ends a ball on a drain only
once the ball has been played a while (plunge, a minute of switch hits, then the trough): a drain straight after the
pick, or 20 s after the plunge, is ignored (run 6's "no pick for teammate 2" was the same).

## Round 4 (2026-11-07, DoomWalrus666 on the thread, seven messages)

The reporter is designing the characters live: in one evening the ally-every-ball and tier-2-always asks (done in
round 3), then the BUILDING ability doubling building damage and Mechagodzilla's spins and shield hits, the HEAT RAY
ability ready at the start and a 4X super spinner, the LONGER BALL SAVE ability with 2x Oxygen Destroyer and
Destruction Jackpot timers and +5 s on battles, SPOT A SHOT without the once-a-ball limit, the MASER ability with Magna
Grab and Rage Combo lit and powerlines double, and the POWER-UPS ability with saucer double, a standing Destruction
Jackpot multiplier, rampage letters and trains double. Found so far (Godzilla LE 1.16; Pro by xmatch):

- Memory diffs on the rig (rig/memdump.py dumps 0x7a0000-0xa00000 between stimuli, rig/diffdumps.py) are the way to
  find a count: a known number of switch pulses, then the words that rose by that much. swspin.py rips are too fast
  for the game's spin counting (84 audit closures = 4 rule spins); swpoke pulses 25 ms every 0.15-0.5 s count 1:1.
- The Mechagodzilla rule is one object (LE 0x7b29f8 / Pro 0x7a6360; its game-start copy LE 0x15c7a8 / Pro 0x159084
  stores SHIELD DIFFICULTY at +4 + 4p and SPINS DIFFICULTY at +0x14 + 4p, p 1-based). Spins toward ONLINE at
  +(p-1)*4 + 0x78 (goal at +0xd0: 20 on difficulty 1); after ONLINE the right spinner again raises the shield: the
  u64 at +8p + 0x30 is 0x80000000 (shield up) with the hits LEFT in its high word (+0x3c for p=1; 3 on difficulty 1).
  `double:spins` (proven: 10 pulses = 20, ONLINE) and `double:shield` (hits left fall two a hit; `_stride 8`).
- The building rule is one object (LE 0x7b1d10 / Pro 0x7a56d8): +0x2c -> a vector of six words, a percent byte per
  player (100 = the step done): the game's default BUILDING DIFFICULTY does a step a shot (STABILITY 83% after one), so
  the old "easier building" ability changed nothing on a stock machine. Ramps fill words 0-3, building hits 4-5.
  `steps:building` completes the step after each one the game completes.
- The heat ray rule is one object (LE 0x7b2d68 / Pro 0x7a66d0): level at +0x14 + 4p, spins at +0x28 + 4p, needed =
  HEAT RAY SPINS PER LEVEL + 8 x level; HEAT RAY READY sets the word at +4 + 4p to 1 (SPINNER MAXED, HOLD DOWN ACTION
  BUTTON). `count:heatray=1` sets it at the pick (proven in memory); the Action hold did not fire the heat ray from
  the set flag alone - the fire's own state is elsewhere (open).
- The battle timers (212-218), O2 DESTROYER TIMER (193) and BALL SAVE TIME are read live through the adjustment
  getter when the mode starts, so `adj:<id>+5` and `adj:<id>x200` (new + and - ops) cover them. The Destruction
  Jackpot has a named timer but no adjustment; its countdown word was not found yet (gift:309 lit it; the shot that
  collects it is not known - open).
- Magna Grab: MAGNA GRAB LIT AT GAME START (194) is copied at game start by LE 0x155cdc into the word at +0x14 + 4p
  of the object 0x7b1d4c (open: hold it at 1). Rage combo: messages 0xca4/0xcac, rule not found (open). Powerlines:
  rule's game-start copy LE 0x1685a4 (QUALIFY DIFFICULTY 178 at +4 + 4p, DIFFICULTY 179 at +0x14 + 4p; targets 78/79/80)
  - counts not found yet (open). Saucer, Destruction Jackpot multiplier, rampage letters, trains: not started.
- The runtime's character line token was 128 bytes: a Godzilla character's abilities now run past 200 (raised to 384).

Proven (LE and Pro, runs 8-9): two building steps a shot, Mecha spins and shield hits doubled, the heat ray READY word
set at the pick, BALL SAVE TIME x2 and a battle timer + 5 read live. The runtime grew: 8 count slots, 12 adjustment
slots, a 384-byte ability token, `_obj`/`_stride` count values, `double:` on falling counts and multi-step rises,
`count:<name>=<n>`, `steps:`, `adj +/-`, spot without the once-a-ball flag. The dialog's and help's words follow.

Next run (DoomWalrus666's remaining asks, all Godzilla):
1. Heat ray: the fire on the Action hold with READY set at the pick (find the fire's own state next to the READY word;
   the game's READY transition at 0x151d40 also sets a byte at +0x8a of another object). Then the 2X super spinner
   after the heat ray at 4X (find the multiplier word with a dump after a real fire).
2. Destruction Jackpot: which shot collects it once LIGHT DESTRUCTION JACKPOT (309) is given, its countdown word
   (dumps a second apart), then a stretch of the countdown x2 for the longer-save character, and a standing +1x
   multiplier for the power-ups character ("1X/2X DESTRUCTION JACKPOT" messages).
3. Maser character: Magna Grab lit (hold the word at +0x14 + 4p of 0x7b1d4c, set from adjustment 194 at game start, at
   1), Rage Combo lit (messages 0xca4/0xcac; find the rule), powerlines double (rule's game-start copy LE 0x1685a4;
   targets 78/79/80; find the targets/sets count with dumps).
4. Power-ups character: saucer shots double (the right scoop 53 / VUK 82?), rampage letters x2, two trains at a time
   (find each count with dumps).
5. Pro proofs for each, the dialog shot, the C harness and Windows tests, then the reply.

## Round 4, batch 2 (2026-11-07 late)

Found and proven on LE (runs 10-13): the saucer is the pop bumper (rule 0x7b0de8, hits +4+4p; `double:saucer`), the
powerline set's three targets are words in rule 0x7b0b90 at +0x38 (`steps:powerline` with `_inline 1 _done 1 _width 4`:
each hit lights two targets, a set in two hits), MAGNA GRAB lit is the word 0x7b1d4c + 0x14 + 4p (`keep:magna=1`), and
the heat ray's READY comes when its level word (+(p-1)*4+0x28) reaches 4: `count:heatlevel=3,count:heatspins=9` at the
pick puts it one spin from READY and the game's own transition lights it. Pro objects are the LE ones - 0xc638 (saucer
0x7a47b0, powerline 0x7a4558, magna 0x7a5714, heat ray 0x7a66d0), confirmed in the Pro disassembly (C:/tmp/PAD-1031/
pro_all.txt). The game's rule table 0x7b4aa8 (Pro 0x7a83f0), 27 pointers named by the port's block_rule_name_N, holds
the base-play rules; the per-player feature state lives in the feature objects found by memory diffs.
New runtime: keep:<name>=<v>, steps _inline/_done/_width, count _width 1 and _stride 0, adj parts with their own
bounds (a doubled timer past the setting's top: O2 x200:8:40, RODAN x200:40:120 for the ally character).
Open: the heat ray's fire from the Action hold on the rig (the game's own; READY is reached the game's way) and the 4X
super spinner after it; the Destruction Jackpot timer and a standing multiplier; Rage Combo lit; rampage letters and
trains x2 (the inlane rollovers 56/57 and loops 84/74 did not move a count in run 11); Mothra saving either outlane
(eighth message).

## Round 4, batch 3 (2026-11-07 night)

Rampage letters: a byte a player in the Monster Rampage rule (0x7b2cfc LE / 0x7a6664 Pro, +0xb + p), advanced by the
skill shot while ADVANCE RAMPAGE is lit; `double:rampage` proven (2 -> 4 on one skill shot with 317 given). The
power-ups character now has it. Found but not yet proven: the Train rule (0x7b2d24 / 0x7a668c, trains at +0x2c + 4p,
incremented at LE 0x188640 - the loop did not award one even with LIGHT TRAIN given; find the lit train shot), the
Destruction Jackpot rule (0x7b1c78 / 0x7a5640; 309's handler sets a lit byte at +0xb + p behind the flags word
0x7b1d88 & 1 - the gift did not light it on the rig). Still open: Rage Combo, Mothra saving either outlane, the 4X
super spinner, the heat ray's fire from the Action hold on the rig (3 s and 6 s holds left READY set).
Next run: trains (315 + candidate shots 50/51/56/84 with dumps of 0x7b2d54), the jackpot (why 0x7b1d88 & 1 is clear
on the rig; then its timer and multiplier words), Rage Combo (no adjustment; find its rule through the RAGE insert's
shot), Mothra (the allies list at *(0x7b2e28 + 0x1c)), then Pro proofs, the reply.

## Round 4, batch 4 (2026-11-07 night)

The Destruction Jackpot multiplier step (0x7b1c78 / 0x7a5640 + 0xc + 4p, 0 = 1X, raised at each light) is kept at
least 1 for the power-ups character (`keep:djmult>=1`, a floor form of keep); proven on LE with 309 given at the pick
(lit byte 1, step 1 for the whole ball). No countdown runs while the jackpot sits lit (38 dumps a second apart), so
its timer is a later phase (open). Trains: the award (0x1886fc, two per-player words +4 and +0x2c) is only reached
through the mystery award path in the code I can see; the loop and the Mecha lane did not award one with LIGHT TRAIN
given (open). Rage Combo, Mothra saving either outlane and the 4X super spinner remain open; the heat ray's fire from
the Action hold does not happen on the rig (the game's own switch handling).
Rig: slot 1 is wedged (killgame hangs on two leftovers; a WSL restart clears it) - hold it with a park label
(riglock.sh take --slot 1 PAD-1031-park ...) before launching so rigbatch takes the next slot.
