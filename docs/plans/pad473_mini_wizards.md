# The game's own mini-wizards on every latest Spike 2 build (PAD-473)

Follow-up of PAD-420 ("I don't want any yellow text for any game"). PAD-436 let a mode hand the player the game's
own mini-wizard and proved it on James Bond LE 1.06 only; every other latest build showed "The app has not found
X's own mini-wizards" in yellow. The work: per title, find whether the game has mini-wizards of its own, land and
prove them where it does, and leave the section out where it has none.

This is several runs of work. Each run adds what it proved here.

## The census (2026-10-09)

Two sources per title: the game program's own modes (the C++ titles' mode table read by `stock_scan_cpp`, the
strings naming a wizard; `C:/tmp/PAD-473/modecensus.txt`, `wizstrings.txt`) and the community rulesheets
(pinballrulesheets.com, where the Tilt Forums wiki now redirects; summaries in `C:/tmp/PAD-473/rulesheets.md`).
"Mini-wizard" = a wizard mode below the final one, as the rulesheet or the game itself names it.

| Game (latest builds) | Mini-wizards | Program (class / route) | Status |
|---|---|---|---|
| James Bond LE 1.06 | Chaos at Crab Key, Ahoy Mr. Bond, Goldfinger's Jackpot, Duel on the Disco Volante | plain C: the wizard table | PAD-436 / PAD-457 |
| James Bond Pro 1.06 | the same four | the LE's code, 0xfcc lower | **proven** (run 1) |
| James Bond 60th LE 1.11 | none: 007 Mode is its only wizard | | **left out** (run 1) |
| The Munsters LE / Pro 1.28 | none: Munster Madness is its final wizard | `cmunster_madness*` | **left out** (run 1) |
| Star Wars Home (ELG) 1.10 | none: Jedi Multiball is its only wizard | | **left out** (run 1) |
| Aerosmith / LE 1.16 | Medley Tour Multiball (left scoop; the glass's name) | plain C: 0x8c15c / LE 0x8c054, flag 57, earned check hooked | **proven** (run 3, before the launch) |
| Avengers Infinity Quest LE / Pro 1.10 | Soul Gem Quest, Black Order Multiball, Battle Royale (right ramp; fixed order) | `cmode_soul_gem`, `cmode_black_order_multiball`, `cmode_battle_royale` | **proven** (run 1, mode route) |
| Batman '66 1.14 | Batusi, Gas Attack, Holy Multiballs (the program's Minor Villain Wizard Modes 1-3) | plain C: 0x1368ec, 0x13b050, 0x141f08; flags 84, 86, 87 | **proven** (run 2, function route) |
| The Beatles 1.29 | Beatlemania Multiball (the rulesheets' Help / Beatlemania: level 3 in all five modes; Taxman is the final) | plain C: 0x39270 r0 1, flag 81 | **proven** (run 3) |
| Deadpool LE / Pro 1.16 | Mr. Sinister: Megakrakolodonus Rex, Clone Multiball (scoop) | `cmrsinister_rex`, `cmrsinister_clones` | **proven** (run 1, mode route) |
| Dungeons & Dragons LE / Pro 1.10 | Tiny's Dice Game, Tavern Brawl (center spinner) | `ctinys_dice_game`, `ctavern_brawl` | Pro **proven**; LE lines written, no game on the rig |
| Elvira's House of Horrors 1.13 | House Party, They Came From Space (the House) | Rule classes | open |
| Foo Fighters LE / Pro 1.04 | Austin, D.C. (left ramp, van map) | `cmode_austin_wizard`, `cmode_dc_wizard` | **proven** (run 1, mode route) |
| Godzilla LE / Pro 1.16 | Monster Zero, Terror of Mechagodzilla (building), Planet X Multiball (City Select) | `cmode_monster_zero`, `cmode_terror_of_mechagodzilla`, `cmode_planet_x_multiball` | **proven** (run 1, mode route) |
| Guardians / LE 1.15 | Cherry Bomb Multiball, Immolation Initiative (right scoop) | plain C: Cherry Bomb 0x2f704, flag 52, earned check hooked | Cherry Bomb **proven** (run 3, before the launch); Immolation Initiative not found |
| Iron Maiden LE / Pro 1.18 | 2 Minutes to Midnight, Number of the Beast ("MINI-WIZARD MODE CHAMPIONS" in the program) | `cmode_two_minutes_to_midnight`, `cmode_number_of_the_beast` | **proven** (run 1, mode route) |
| Jaws LE / Pro 1.02 | 4th of July, Super Cast 'n Catch, Say Ah! (LE; centre ramp), Rescue / Search Multiball, Great White Multiball | `cmode_fourth_of_july`, `cmode_cast_n_catch_super`, `cmode_say_ah`, `cmode_rescue_multiball`, `cmode_search_multiball`, `cmode_great_white_multiball` | **proven** (run 1, mode route) |
| John Wick LE / Pro 1.02 | Red Circle Reckoning, The Staircase, The Duel (left eject / crate; fixed order) | `crule_wizard_modes`, `cmode_the_staircase`, `cmode_the_duel` | **proven** (run 1, mode route) |
| Jurassic Park LE / Pro 1.16 | Visitor's Center, Museum Mayhem (left ramp), Secure Control Room | C++ (start slot 21 from the older build) | **proven** (run 1, mode route) |
| Jurassic Park Home 1.05 | Escape Nublar, Restore Power (T-Rex) | rule methods: 0x35270 / 0x68090, r0 the rule 0x592250 / 0x592300 | **proven** (run 3) |
| King Kong LE / Pro 0.97 | Crash the Gate, T-Rex Battle, T-Rex Boss Battle (gong) | `cmode_crash_the_gate`, `cmode_trex_battle`, `cmode_trex_boss_battle` | **proven** (run 1, mode route) |
| Led Zeppelin LE / Pro 1.22 | Mothership, World Tour, Top of the Charts Multiballs | `cmothership_multiball`, `cworld_tour_multiball`, `ctop_of_the_charts_multiball` | **proven** (run 1, mode route) |
| The Mandalorian LE / Pro 1.45 | Precious Cargo, You Have What I Want, I Like Those Odds | `crazor_crest_wizard`, `cyou_have_what_i_want`, ... | **proven** (run 1, mode route) |
| Metallica Remastered 1.04 | Blackened Multiball, The End of the Line (scoop) | plain C: 0xa2010 (flag 50), 0x140fe4 (process 0xdf) | **proven** (run 2, function route) |
| Rush LE / Pro 1.19 | Cygnus X-1 Book 1, Book 2 (Time Machine) | `cmode_cygnus_book_1_multiball`, `_book_2_` | **proven** (run 2: waits for the ball to drain first) |
| Star Wars LE / Pro 1.31 | Lightsaber Duel (left ramp); the four planet Finals | C++ (start slot 8 from the older build) | **proven** (run 1, mode route) |
| Stranger Things / LE 1.13 | Season One, Season Two Wizard Mode (the program's names; also Total Isolation 1 / 2 multiballs) | plain C: 0x111fa0 / 0x11d344 (LE 0x12efac / 0x13a334), r0 1; flags 72, 78 | **proven** (run 2, function route) |
| Black Knight: Sword of Rage LE / Pro 1.19 | KNIGHT Multiball, The King's Ransom (left spinner lane; the program's "retro" and BK2K wizard multiballs) | `cmode_original_mball`, `cmode_bk2k_mball` | **proven** (run 1, mode route) |
| TMNT LE / Pro 1.59 | Team-Up Multiball (left ramp) | `cteam_up` (lit by `cteam_up_ready`) | **proven** (run 1, mode route) |
| Uncanny X-Men LE / Pro 0.98 | The Future, Save Senator Kelly | singletons: enable-and-start 0x7970c / 0x9930c (Pro 0x75f70 / 0x95b50), r0 the object | **proven** (run 3) |
| Venom LE / Pro 1.07 | Toxin Team-Up (scoop) | C++ | **proven** (run 1, mode route) |

## How a game with none shows

`mode_project.NO_GAME_WIZARDS` (by game directory, with what the game has instead) puts "wizard" in the profile's
`absent`: the Mode page and the blocks palette leave the section out, as PAD-420's MACHINE_HARDWARE does for a
machine part the machine lacks. A port that names some always wins (the test).

## The C++ titles: the mode route (run 1)

Bond's route is its own table and per-player words. Most other titles are C++ (`cmode` / `crule` classes): a rule
starts one of its modes by calling the mode object's START virtual (`value stock_slot_start`, read per title by
`stock_scan_cpp`), e.g. TMNT 1.59 `getter(0x18)->v[39]()` with only `this`; the ACTIVE virtual (`value
stock_slot_active`) says it runs.

- **Tried first** (`C:/tmp/PAD-473/gen/wizgo.c`, an instrument calling a named object's START): on Godzilla LE 1.16
  Monster Zero's START made it active at once and its own intro played ("SHOOT GREEN ARROWS TO LIGHT LOCK ...").
- **The runtime** (`pad_mode_runtime.c` "the MODE route", `wizm_*`): `data wizard_obj_<n>` per mini-wizard (and an
  optional `data wizard_ready_<n>`, the game's own mode that lights it). START when nothing of the game's is in its
  way (the `stack no` walk, less base play and ready modes; no mode of ours holding the game's modes off), else
  waiting, 250 ms tries, that ball. LIGHT = start the ready mode; none = started instead. The game's own rules are left
  alone (no claims). MODE_SDK.md "The game's own mini-wizards on the other titles".
- **Found on the rig**: the arm runs ~2 ms after load, before the game's static constructors write the objects'
  vtables, so every object first read as "not this build's". The arm now checks only that each object is in the
  game's memory; the vtable and both slots' functions are checked at every hand-over.
- **The lines**: `C:/tmp/PAD-473/lines` - `objs.py <key>` lists a build's mode objects (class, object, START and
  ACTIVE functions by the port's slots); `spec.py` the mini-wizards per game (class, name, what earns it, ready
  class); `gen.py --write` writes each port's section and the proof stage. 32 C++ builds have lines.
- **The proof** (`C:/tmp/PAD-473/gen`): `wizexp_job.sh` (rigbatch: fresh NVRAM, Guided Setup left, a game, then the
  steps), stage `stage2/<key>` = the runtime + `mode_file.c` + `wizgo.c` (watches the objects' ACTIVE), the port, and
  two mode files `game_wizard start <wizard 1 / 2>` started by their trigger files; `judge.py <tag>` reads each
  build's log. The job must not set PAD_CARD_CACHE=0 (it then boots the card off D: under load: King Kong's boot
  segv).

## Run 1's result (2026-10-09)

33 of the 53 latest builds hand over their own mini-wizards, emulator-proven: James Bond LE and Pro (the table
route), and 31 C++ builds (the mode route: `WIZARDS_PROVEN`, each with its evidence; sweeps `C:/tmp/PAD-473/gen/out/p3`,
`p4`, `p4light`). On every one the first `game_wizard start` file started the game's own mini-wizard (ACTIVE 1, its own
intro on the glass - Monster Zero's "SHOOT GREEN ARROWS", PRECIOUS CARGO, ...; the multiball ones served their balls:
Mothership and Precious Cargo 4, KNIGHT 3), and a second file while it ran waited ("... is in its way"); no abort.
Light proven on Star Wars LE and Pro (the game's own clightsaber_duel_ready, then the Left ramp opto started
Lightsaber Duel). Four builds leave the section out (no mini-wizards of their own).

Two titles needed more than the START (sweep `p4`): Foo Fighters LE / Pro 1.04's START returns at once unless the
player's enabled byte is set (its v[46] reads obj + player + 0x83; v[42], the base class's enable, sets it), so `value
wizard_slot_enable 42` makes the runtime call v[42] first - Austin then started, four balls. Jurassic Park LE / Pro
1.16: Visitor's Center from the scanner, Museum Mayhem and Secure Control Room from the block lines' objects (the Pro's
0xfb90 lower, each checked by its references) - Visitor's Center started, two balls, Museum Mayhem waited.

## Run 2: Rush (2026-10-09)

- **Rush LE / Pro 1.19** proven (sweep `p6`). Book 1's START (0xfc43c on the LE) asks the game's flag 0x1d (most likely the
  ball held in the Time Machine, its own start shot): set, it works the Time Machine's device; not set, it sets the
  mode mask's 0x202 (0x200 is one of the runtime's busy bits, so in-game reads 0), calls what looks like the flippers'
  off, and leaves a process (0xfdd80) waiting before the intro goes on and the mask is cleared (0xfdd30). On
  the rig nothing drains a ball, so in `p5` the intro stood on CYGNUS X-1 BOOK 1 for over a minute; with the rig's
  drain (`plunge.py drain`, a new `drain` step in `wizexp_job.sh`) 9 s after the start the game was in play again
  14 s after it, Book 1 ACTIVE 1, FLIGHT CONDITIONS then CYGNUS - BOOK 1 / CHOOSE A PLANET on the glass and the Book I
  jackpot on the HUD; Book 2 waited while it ran ("a multiball (cmode_cygnus_book_1_multiball) is in its way"). So a
  hand-over away from the Time Machine waits for the ball to drain before the intro - the game's own path, said in
  MODE_LIMITS.md (whether the game also turns the flippers off meanwhile - 0x238fd8 walks three device kinds with 0,
  then hook 0xb1 - is not proven).

## Run 2: the plain-C titles' function route (2026-10-09)

- **The route** (`pad_mode_runtime.c` "the FUNCTION route", `wizf_*`; MODE_SDK.md "The plain-C titles"): `site
  wizard_go_<n>` (the start, its words checked as the port loads), `value wizard_flag_<n>` (its ACTIVE game flag in the
  item-164 bitmap; the flag ids from the game's own FG_ name table, FG_INVALID = 0, each checked against a start that
  sets it - `C:/tmp/PAD-473/flagid.py`, `flagsetters.py`), or `value wizard_proc_<n>` / `data wizard_running_<n>`;
  optional `value wizard_arg_<n>` (r0) and `site wizard_earned_<n>` (the start's own earned check, hooked to answer 1
  only during the runtime's call). START waits for nothing of the game's in its way (the stack's query) and then calls
  it; a 0 back with the flag down is the game's own rules saying not now: called again every 250 ms that ball.
- **The probe** (`gen/wizfn.c`: call a function, peek, watch; sweep `p7`): Batman's Minor Villain Wizard Mode 1 start
  returned 1 and served its balls, and Mode 2's started ON TOP of it (its own check asks only its own flag 86):
  the runtime's in-the-way check is what keeps two apart. Metallica's End of the Line started on top of Blackened
  the same way. Aerosmith LE's Medley returned 0 (its check 0x89724 wants every song played - 0x1240f8 - and none of
  seven of its things running, 0xa0c94, no multiball, 0x4a388, not played, flag 58); Guardians' Cherry Bomb the same
  (0x2eb94: four of eight - 0x10ead0 - then 0xb88f8, 0x42280, flag 53).
- **Proven** (sweep `p8`): Batman 1.14 (Batusi started, flag 84 up, 6 balls, its 5 MORE SHOTS screen; Gas Attack
  waited), Metallica 1.04 (Blackened started, 4 balls, BLACKENED / PLAYFIELD MULTIPLIED BY BALLS IN PLAY; The End of
  the Line waited), Stranger Things 1.13 and LE 1.13 (Season One Wizard Mode started, flag 72, 3 balls, 3,000,000 and
  its Demogorgon scene; Season Two waited). The Batman names: the adjustments' descriptors are id-indexed 44-byte
  records, AD_MINOR_VILLAIN_WIZARD_MODE_2_* at the GAS ATK. ones and _3_ at the HOLY ones.
- **Not yet** (sweeps `p8`, `p10`): Aerosmith LE's Medley and Guardians' Cherry Bomb, earned check hooked, still
  refused by the rest of their own check at game start (the runtime says "the game's own start would not start it
  now" and tries again): something of theirs runs from the ball's start (Aerosmith: one of the seven at 0x50d000 + 0x4c
  each, its +0x1c a running query). The `p10` probe called each at game start: the fourth, 0xae390 (= 0xcb79c(0x50e4d8),
  a mode's running query), answered 1, the rest 0, the multiballs' 0x4a388 0, the earned check 0x1240f8 0 (no song
  played) - so a mode of its own runs from the ball's start. Until it is known what that is and when it ends in play,
  they stay "found, not yet seen". Aerosmith Pro 1.16 started no game in this job at all (`p7`, `p9`: Guided Setup
  never seen, six tries), though PAD-420's jobs played it: its fresh NVRAM is the difference to look at.
- **X-Men LE 0.98**: the Future's singleton (0x645b18, its guard 0x645c10) is built by a game's start (guard 1,
  vtable 0x558b80 at the probe). The probe called 0x79738 - mid-function: the function opens at 0x79730 (movw/movt r0
  = its guard), so r0 was 0 and the game died (state off). `0x7970c(0x645b18)` (enable + start) is the call to try,
  with r0 the object (`value wizard_arg_1 0x645b18`); its running query is still to be found (the start sets +0xdc).
- **A finding outside this ticket**: Stranger Things 1.13 / LE 1.13's `value mode_flag_3..5` (37, 136, 116, PAD-420's
  "LE 1.12's moved up 5") are not those modes' running flags - the game's names are FG_CENTER_DROP_TARGET_BANK_REQUEST_UP,
  FG_FORCE_MUSIC_TO_START_AT_BEGINNING and FG_BULLSHIT_SCORING_PLAYED, flags the starts set as a side effect - so the
  stack can read one of the game's modes running when none is. Left as they are here (they did not hold the hand-overs
  off); a ticket of its own.

## Run 3 (2026-10-09): the rest of the function route

- **X-Men LE / Pro 0.98**: both mini-wizards are mode singletons with an enable-and-start of their own (the Future
  0x7970c: the player's byte at +0xd7, then the start 0x792f8, which returns at once without it; Save Senator Kelly
  0x9930c: +0xa7, then 0x990e4; the Pro's 0x75f70 / 0x95b50 found by the same code shape), called with the object in
  r0 (`value wizard_arg_<n>`; LE 0x645b18 / 0x644e90, Pro 0x63ae90 / 0x63a368). The game builds both itself (C++ local
  statics), so `data wizard_built_<n>` names each guard (built by a game's start on the rig: guard 1, vtable in place)
  and the runtime does not call through one unbuilt. Running: the object's own byte (+0xdc set by the Future's start,
  cleared by its constructor 0x7621c and 0x77e84 / 0x77f68; +0xac for Kelly, cleared by 0x98838 / 0x99380). The probe
  (`p11`) started Kelly on top of the Future (neither a multiball, neither among the port's running bytes), so the
  function route now holds one off while another of the port's own runs ("The Future (another of its mini-wizards) is in
  its way"). Proven (`p13`): the Future started (its HELP KITTY PRYDE ESCAPE THE CITY RUINS), Kelly waited.
- **The Beatles 1.29**: its mini-wizard is the rulesheets' Help / Beatlemania multiball (level 3 in all five modes;
  Taxman Multiball is the final wizard) - the program's Main Multiball, its adjustments named Beatlemania Multiball.
  Start 0x39270(r0): 1 starts it (its upper magnet's shot handler passes 1), 0 asks the modes' levels; flag 81
  FG_MAIN_MULTIBALL_ACTIVE (the flag functions 0x139e8c set / 0x139f24 get, the bitmap [0x5b28d8 + 4], now in the port).
  Proven: 4 balls, TAXMAN PLAYED BEFORE BEATLEMANIA.
- **Jurassic Park Pin 1.05**: Escape Nublar and Restore Power are rule methods (0x35270 / 0x68090, r0 the rule:
  0x592250 / 0x592300, their guards 0x5923a4 / 0x5923a8; the shot handlers 0x3f39c / 0x71e2c call them once lit).
  Running: the rule's +0x4c / +0x5c, which each start sets. Proven: Escape Nublar, 4 balls, its BREAKING NEWS ALERT;
  Restore Power waited.
- **Aerosmith / LE and Guardians / LE**: the songs (Aerosmith, seven queries at 0x50d000) and the modes (Guardians,
  eight at 0x4fdf40) their own starts wait out run from a ball's launch - the launch picks one (the rulesheet: "at the
  start of any ball, if a mode is not running, you can choose to start any mode") - and on the rig, where no shot is
  made, one ran for the five minutes watched (`p11`). On a machine a mode times out (61 s and the like) or is won, so
  a hand-over waits for that; proven here by a file started with the ball still in the shooter lane (`NOLAUNCH=1`,
  `p12` / `p13`): Medley Tour Multiball (the glass's name for Medley) 3 balls, Cherry Bomb 6 balls and its 60-second
  TIME REMAINING, with no song played and no mode completed (the earned checks hooked). Aerosmith Pro started a game
  only on PAD-420's NVRAM past Guided Setup (`/home/david/pad420_nv/aerosmith`, from slot 1; `NVSEED=1`).
- The probe and proofs ran as root: slots 1-4 had ~3,300 root-owned entries given back to david afterwards.

## Still open

Shots: `work/artifacts/PAD-473` (bondpro, kong, kongstart, munsters, turtles: run 1; batman: run 2).

After run 3: 51 of the 53 latest builds are done - 47 proven (Bond LE and Pro; 33 C++ builds on the mode route; 10
plain-C builds and X-Men LE / Pro on the function route) and 4 leave the section out - and 2 are open:

- **D&D LE 1.10** starts no game on the rig at all (a known rig limit, PAD-420): its lines stay unproven unless a
  machine run proves them.
- **Elvira 1.13** (House Party, They Came From Space): C++ rule objects (`HousePartyRule`, `TheyCameFromSpaceRule` at
  0x885e28, House 25; their running test the port's `mode_rule_slot` 15). A House starts through the House manager
  (0xdd12c: the player's selected house, its rule's v[22], then the manager's played bits), so a hand-over either sets
  the player's selected house first or calls the rule's v[22] and does the manager's bookkeeping itself - neither yet
  understood well enough to call. House Party (a multiball) not located.
- Guardians' Immolation Initiative: no FG_ flag of its own - its start and running query not found.
- A mini-wizard named on the rulesheet whose class was not found: John Wick's Red Circle Reckoning (run by
  `crule_wizard_modes`), The Mandalorian's I Like Those Odds.
