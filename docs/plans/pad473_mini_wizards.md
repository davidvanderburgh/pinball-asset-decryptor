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
| Avengers Infinity Quest LE / Pro 1.10 | Soul Gem Quest, Black Order Multiball, Battle Royale (right ramp; fixed order) | `cmode_soul_gem`, `cmode_black_order_multiball`, `cmode_battle_royale` | open |
| Batman '66 1.14 | Batusi, Robin's Holy, Gas Attack Multiballs (left orbit, chosen) | plain C | open |
| The Beatles 1.29 | Hard Day's Night / Beatlemania Multiball (upper magnet) | plain C | open |
| Deadpool LE / Pro 1.16 | Mr. Sinister: Megakrakolodonus Rex, Clone Multiball (scoop) | `cmrsinister_rex`, `cmrsinister_clones` | open |
| Dungeons & Dragons LE / Pro 1.10 | Tiny's Dice Game, Tavern Brawl (center spinner) | `ctinys...`, `cmode` Tavern multiball | open |
| Elvira's House of Horrors 1.13 | House Party, They Came From Space (the House) | Rule classes | open |
| Foo Fighters LE / Pro 1.04 | Austin, D.C. (left ramp, van map) | `cmode_austin_wizard`, `cmode_dc_wizard` | open |
| Godzilla LE / Pro 1.16 | Monster Zero, Terror of Mechagodzilla (building), Planet X Multiball (City Select) | `cmode_monster_zero`, `cmode_terror_of_mechagodzilla`, `cmode_planet_x_multiball` | open |
| Guardians / LE 1.15 | Cherry Bomb Multiball, Immolation Initiative (right scoop) | plain C | open |
| Iron Maiden LE / Pro 1.18 | 2 Minutes to Midnight, Number of the Beast ("MINI-WIZARD MODE CHAMPIONS" in the program) | `cmode_two_minutes_to_midnight`, `cmode_number_of_the_beast` | open |
| Jaws LE / Pro 1.02 | 4th of July, Super Cast 'n Catch, Say Ah! (LE; centre ramp), Rescue / Search Multiball, Great White Multiball | `cmode_fourth_of_july`, `cmode_cast_n_catch_super`, `cmode_say_ah`, `cmode_rescue_multiball`, `cmode_search_multiball`, `cmode_great_white_multiball` | open |
| John Wick LE / Pro 1.02 | Red Circle Reckoning, The Staircase, The Duel (left eject / crate; fixed order) | `crule_wizard_modes`, `cmode_the_staircase`, `cmode_the_duel` | open |
| Jurassic Park LE / Pro 1.16 | Visitor's Center, Museum Mayhem (left ramp), Secure Control Room | C++ (start slot 21 from the older build) | open |
| Jurassic Park Home 1.05 | Escape Nublar, Restore Power (T-Rex) | plain C | open |
| King Kong LE / Pro 0.97 | Crash the Gate, T-Rex Battle, T-Rex Boss Battle (gong) | `cmode_crash_the_gate`, `cmode_trex_battle`, `cmode_trex_boss_battle` | open |
| Led Zeppelin LE / Pro 1.22 | Mothership, World Tour, Top of the Charts Multiballs | `cmothership_multiball`, `cworld_tour_multiball`, `ctop_of_the_charts_multiball` | open |
| The Mandalorian LE / Pro 1.45 | Precious Cargo, You Have What I Want, I Like Those Odds | `crazor_crest_wizard`, `cyou_have_what_i_want`, ... | open |
| Metallica Remastered 1.04 | Blackened, End of the Line (scoop) | plain C | open |
| Rush LE / Pro 1.19 | Cygnus X-1 Book 1, Book 2 (Time Machine) | C++ (start slot 40 from the older build) | open |
| Star Wars LE / Pro 1.31 | Lightsaber Duel (left ramp); the four planet Finals | C++ (start slot 8 from the older build) | open |
| Stranger Things / LE 1.13 | Total Isolation 1 / 2, Send it Back, Light the Fire (left ramp) | plain C | open |
| Black Knight: Sword of Rage LE / Pro 1.19 | KNIGHT Multiball, The King's Ransom (left spinner lane; the program's "retro" and BK2K wizard multiballs) | `cmode_original_mball`, `cmode_bk2k_mball` | open |
| TMNT LE / Pro 1.59 | Team-Up Multiball (left ramp) | `cteam_up` (lit by `cteam_up_ready`) | open |
| Uncanny X-Men LE / Pro 0.98 | The Future, Save Senator Kelly | `Mode_Future_Mini_Wizard`, `Mode_Save_Senator_Kelly_Wizard` | open |
| Venom LE / Pro 1.07 | Toxin Team-Up (scoop) | C++ | open |

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

## Still open

- **Jurassic Park LE / Pro 1.16** (C++): its port's block lines name Museum Mayhem (`block_obj_20` 0x738e64 on the
  LE) and Secure Control Room (`block_obj_21` 0x739058), and the scanner found `cmode_visitor_center` (0x738afc); the
  Pro's objects sit 0xfb90 lower in that region (Escape Nublar, Visitor's Center, the T-Rex modes all do) - check
  each by its references before writing them.
- **Uncanny X-Men LE / Pro 0.98** (its own C++ framework, `Mode_` classes with a Singleton): `Mode_Future_Mini_Wizard`,
  `Mode_Save_Senator_Kelly_Wizard` (block lines 11 and 13 on the LE).
- **The plain-C titles** (Aerosmith, Batman '66, The Beatles, Guardians, Stranger Things, Metallica, Jurassic Park
  Home, Elvira): no mode objects. Their modes start through plain functions (PAD-363's `cstarts`) and set a game flag
  each (`mode_flag_<n>`); a third route would call the mini-wizard's start function and read its flag. Their
  mini-wizards are multiballs mostly not among the block lines (multiballs are never blocked), so their starts must
  be found first.
- A mini-wizard named on the rulesheet whose class was not found: John Wick's Red Circle Reckoning (run by
  `crule_wizard_modes`), The Mandalorian's I Like Those Odds.
