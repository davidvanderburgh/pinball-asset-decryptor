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
| Aerosmith / LE 1.16 | Medley Multiball (left scoop) | plain C | open |
| Avengers Infinity Quest LE / Pro 1.10 | Soul Gem Quest, Black Order Multiball, Battle Royale (right ramp; fixed order) | `cmode_soul_gem`, `cmode_black_order_multiball`, `cmode_battle_royale` | **proven** (run 1, mode route) |
| Batman '66 1.14 | Batusi, Robin's Holy, Gas Attack Multiballs (left orbit, chosen) | plain C | open |
| The Beatles 1.29 | Hard Day's Night / Beatlemania Multiball (upper magnet) | plain C | open |
| Deadpool LE / Pro 1.16 | Mr. Sinister: Megakrakolodonus Rex, Clone Multiball (scoop) | `cmrsinister_rex`, `cmrsinister_clones` | **proven** (run 1, mode route) |
| Dungeons & Dragons LE / Pro 1.10 | Tiny's Dice Game, Tavern Brawl (center spinner) | `ctinys_dice_game`, `ctavern_brawl` | Pro **proven**; LE lines written, no game on the rig |
| Elvira's House of Horrors 1.13 | House Party, They Came From Space (the House) | Rule classes | open |
| Foo Fighters LE / Pro 1.04 | Austin, D.C. (left ramp, van map) | `cmode_austin_wizard`, `cmode_dc_wizard` | **proven** (run 1, mode route) |
| Godzilla LE / Pro 1.16 | Monster Zero, Terror of Mechagodzilla (building), Planet X Multiball (City Select) | `cmode_monster_zero`, `cmode_terror_of_mechagodzilla`, `cmode_planet_x_multiball` | **proven** (run 1, mode route) |
| Guardians / LE 1.15 | Cherry Bomb Multiball, Immolation Initiative (right scoop) | plain C | open |
| Iron Maiden LE / Pro 1.18 | 2 Minutes to Midnight, Number of the Beast ("MINI-WIZARD MODE CHAMPIONS" in the program) | `cmode_two_minutes_to_midnight`, `cmode_number_of_the_beast` | **proven** (run 1, mode route) |
| Jaws LE / Pro 1.02 | 4th of July, Super Cast 'n Catch, Say Ah! (LE; centre ramp), Rescue / Search Multiball, Great White Multiball | `cmode_fourth_of_july`, `cmode_cast_n_catch_super`, `cmode_say_ah`, `cmode_rescue_multiball`, `cmode_search_multiball`, `cmode_great_white_multiball` | **proven** (run 1, mode route) |
| John Wick LE / Pro 1.02 | Red Circle Reckoning, The Staircase, The Duel (left eject / crate; fixed order) | `crule_wizard_modes`, `cmode_the_staircase`, `cmode_the_duel` | **proven** (run 1, mode route) |
| Jurassic Park LE / Pro 1.16 | Visitor's Center, Museum Mayhem (left ramp), Secure Control Room | C++ (start slot 21 from the older build) | **proven** (run 1, mode route) |
| Jurassic Park Home 1.05 | Escape Nublar, Restore Power (T-Rex) | plain C | open |
| King Kong LE / Pro 0.97 | Crash the Gate, T-Rex Battle, T-Rex Boss Battle (gong) | `cmode_crash_the_gate`, `cmode_trex_battle`, `cmode_trex_boss_battle` | **proven** (run 1, mode route) |
| Led Zeppelin LE / Pro 1.22 | Mothership, World Tour, Top of the Charts Multiballs | `cmothership_multiball`, `cworld_tour_multiball`, `ctop_of_the_charts_multiball` | **proven** (run 1, mode route) |
| The Mandalorian LE / Pro 1.45 | Precious Cargo, You Have What I Want, I Like Those Odds | `crazor_crest_wizard`, `cyou_have_what_i_want`, ... | **proven** (run 1, mode route) |
| Metallica Remastered 1.04 | Blackened, End of the Line (scoop) | plain C | open |
| Rush LE / Pro 1.19 | Cygnus X-1 Book 1, Book 2 (Time Machine) | `cmode_cygnus_book_1_multiball`, `_book_2_` | lines written; Book 1 starts but its intro waits (below) |
| Star Wars LE / Pro 1.31 | Lightsaber Duel (left ramp); the four planet Finals | C++ (start slot 8 from the older build) | **proven** (run 1, mode route) |
| Stranger Things / LE 1.13 | Total Isolation 1 / 2, Send it Back, Light the Fire (left ramp) | plain C | open |
| Black Knight: Sword of Rage LE / Pro 1.19 | KNIGHT Multiball, The King's Ransom (left spinner lane; the program's "retro" and BK2K wizard multiballs) | `cmode_original_mball`, `cmode_bk2k_mball` | **proven** (run 1, mode route) |
| TMNT LE / Pro 1.59 | Team-Up Multiball (left ramp) | `cteam_up` (lit by `cteam_up_ready`) | **proven** (run 1, mode route) |
| Uncanny X-Men LE / Pro 0.98 | The Future, Save Senator Kelly | `Mode_Future_Mini_Wizard`, `Mode_Save_Senator_Kelly_Wizard` | open |
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

## Still open

- **Rush LE / Pro 1.19**: Book 1's START works (ACTIVE 1, its own CYGNUS X-1 BOOK 1 intro and FLIGHT CONDITIONS on the
  glass), but the runtime's in-game check (`mode_mask` & 0x210) reads busy from that instant and stayed so for over a
  minute on the intro (`out/p5`): it most likely waits for the ball in the Time Machine, its own start shot (the rules:
  "lock a ball in the Time Machine ..."). Find what the intro waits on (the Time Machine's ball-held state, or a
  display-done event) and hand it over with that in place - or hand it over only while a ball sits in the Time
  Machine - before it is offered.

- **Uncanny X-Men LE / Pro 0.98** (its own C++ framework, `Mode_` classes with a Singleton): `Mode_Future_Mini_Wizard`,
  `Mode_Save_Senator_Kelly_Wizard` (block lines 11 and 13 on the LE). On the LE the Future's object is the singleton
  0x645b18; `0x79738()` (no arguments) builds it if need be and calls `0x7970c(obj)`, which sets the player's enabled
  byte (obj + player + 0xd7) and tail-calls the start 0x792f8, which returns at once without that byte - the same
  shape as Foo Fighters' enable + START, as plain functions. A "function route" (a no-argument start per mini-wizard,
  `site wizard_go_<n>`, and a running query) fits it and the plain-C titles.
- **D&D LE 1.10** starts no game on the rig at all (a known rig limit, PAD-420): its lines stay unproven unless a
  machine run proves them.
- **The plain-C titles** (Aerosmith, Batman '66, The Beatles, Guardians, Stranger Things, Metallica, Jurassic Park
  Home, Elvira): no mode objects. Their modes start through plain functions (PAD-363's `cstarts`) and set a game flag
  each (`mode_flag_<n>`); a third route would call the mini-wizard's start function and read its flag. Their
  mini-wizards are multiballs, not among the block lines (multiballs are never blocked), but PAD-363's start finder
  kept them as rejected candidates (`tools/spike2_emu/modes/sdk/cstarts/json/<key>.json`, "rejected"): Aerosmith
  1.16 Medley Multiball 0x8c15c (and "Wizard Mode Multiball" 0x125c1c, Final Tour), Batman 1.14 Minor Villain Wizard
  Modes 1-3 0x1368ec / 0x13b050 / 0x141f08, Guardians 1.15 Cherry Bomb 0x2f704 (and "Wizard Mode Multiball"
  0x115074), Metallica 1.04 Blackened Multiball 0xa2010 (End of the Line not located: counted from data), Stranger
  Things 1.13 "Wizard Mode Multiball" 0x1772d8, JP Home 1.05 Restore Power 0x68090, X-Men LE 0.98 Future (mini
  wizard) 0x792f8 and Save Senator Kelly 0x990e4. Bond's own start calls its table's starts with r0 = 0. But a start
  may check its own qualification first: Aerosmith's Medley start calls 0x8983c and returns 0 when it is not earned,
  so a plain-C hand-over has to set what qualifies it (per title), not only call the start.
- A mini-wizard named on the rulesheet whose class was not found: John Wick's Red Circle Reckoning (run by
  `crule_wizard_modes`), The Mandalorian's I Like Those Odds.
