# Video tab: Played in and clip sounds on every Spike 2 title (PAD-624)

## What was wrong

A Pinside user on v1.212.2 with an Uncanny X-Men project saw neither the Video tab's clip sounds
box (PAD-592) nor its Played in column and mode filter (PAD-444). The tab never said why.

- **Played in** knew only Godzilla-style `cmode_*` rule classes. Titles whose rule classes are
  named freely (Venom's `ccarnage_mball`, Mandalorian, Star Wars, TMNT, D&D, Led Zeppelin,
  Munsters) or are singletons (X-Men's `Mode_Stopping_A_Juggernaut`) read no modes at all.
- **Clips in a scene that is no clip bank** were never named: a scene whose library holds several
  Videos (Batman 66 keeps its clips this way, Elvira 3, Star Wars, Godzilla's Xilien broadcast).
  PAD-627 made such clips say "a scene plays it on its own", even where the program names them.
- **A card the tab can't read** (not on this PC, unreadable, or no modes told apart) showed nothing
  and gave no reason. A project extracted from a physical card or a card file since moved is the
  likely case for the Pinside user: the clip sounds were in fact read for X-Men whenever the card was
  on the PC (`clip_modes.read_card` with the project's rows: 201 clips with sounds, 160 sure).

## What changed

1. `clip_modes._mode_classes`: besides `cmode_*` leaves, any class deriving from `cmode` that
   none derives from or that the game builds an object of (less the framework bases), and on a
   title with no `cmode`, each rule class that is its own `Singleton<>` (less the shared parts:
   `NOT_MODES`). Godzilla-style titles read exactly as before.
2. `clip_modes.read_card`: a scene directory that is no video bank has its clips named by the
   scene element that references them, as Extract names their files (`engine._parse_radium`),
   within the same 12 most-clips folders. Such a clip is named (Played in, sounds) only where the
   program names it; one it never names keeps PAD-627's words. Never in "Not played".
3. The Video tab's toolbar says in one line, with a tooltip, when the card gives it nothing: the
   card is not on this PC, could not be read, or this game's modes can't be told apart (and whether
   its clip sounds are still shown). de/es/fr strings.
4. `sound_census.c` (the instrument) logs each clip a surface is given (`surface_set_video`), so
   clip sounds can be proven on titles with no `clip_play` site.

## Census: every Spike 2 card on D:\Pinball\images\Stern\spike2 (90 cards)

`clip_modes.read_card` on each card with the rows Extract writes for it (every clip on the card,
named from its scene), main (v1.215.1) against the branch. "Clips with Played in" counts project
clips that get a mode, "named" those the tab can read anything for, "sounds" those with at least
one sound listed, "sure" those with a record / next / name sound, "scene-only" those that keep
"a scene plays it on its own". Where a cell has one number, main and the branch agree.

On every card, every pair main lists is listed by the branch unchanged (checked pair by pair on
Godzilla Pro 1.16, Elvira 3 1.13, Star Wars LE 1.31, Munsters LE 1.28, King Kong Pro 0.97,
Stranger Things LE 1.13 and TMNT LE 1.59); the branch only adds pairs for clips main left unnamed.

| Card | Clips | Modes | Clips with Played in | Clips named | Clips with sounds | of them sure | Scene-only clips | Why nothing |
|---|---:|---|---|---|---|---|---|---|
| Godzilla Premium 1.15 Heisei Custom V1.0 | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| Godzilla Premium 1.16 Heisei Custom V1.5 Orchestral Edition | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| Godzilla Premium 1.16 Heisei Custom V1.5 Standard Edition | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| Godzilla Premium 1.16 Heisei Custom V1.6 Orchestral Edition.multi | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| aerosmith-1_16_0 | 163 | 0 | 0 | 163 | 63 | 12 | 0 | modes not told apart |
| aerosmith_le-1_15_0 | 163 | 0 | 0 | 163 | 61 | 12 | 0 | modes not told apart |
| aerosmith_le-1_16_0 | 163 | 0 | 0 | 163 | 63 | 12 | 0 | modes not told apart |
| avengers_infinity_le-1_09_0 | 274 | 20 | 101 | 268 | 118 | 87 | 0 |  |
| avengers_infinity_le-1_10_0 | 274 | 20 | 101 | 268 | 117 | 86 | 0 |  |
| avengers_infinity_pro-1_10_0 | 274 | 20 | 101 | 268 | 119 | 89 | 0 |  |
| batman-1_13_0 | 6331 | 0 | 0 | 15 → 18 | 0 → 3 | 0 | 6316 → 6313 | modes not told apart |
| batman-1_14_0 | 6331 | 0 | 0 | 15 → 18 | 0 → 3 | 0 | 6316 → 6313 | modes not told apart |
| beatles-1_29_0 | 354 | 0 | 0 | 353 | 19 | 10 | 0 | modes not told apart |
| beatles-1_29_0.i107-variant-a | 354 | 0 | 0 | 353 | 19 | 10 | 0 | modes not told apart |
| beatles-1_29_0.i107-variant-b | 354 | 0 | 0 | 353 | 19 | 10 | 0 | modes not told apart |
| deadpool_le-1_14_0 | 99 | 0 | 0 | 99 | 57 | 53 | 0 | modes not told apart |
| deadpool_le-1_16_0 | 99 | 0 | 0 | 99 | 57 | 53 | 0 | modes not told apart |
| deadpool_pro-1_16_0 | 99 | 0 | 0 | 99 | 57 | 53 | 0 | modes not told apart |
| dungeons_and_dragons_le-1_00_0 | 581 | 0 → 35 | 0 → 321 | 575 | 217 | 201 | 0 |  |
| dungeons_and_dragons_le-1_10_0_spike2 | 581 | 0 → 35 | 0 → 321 | 575 | 218 | 202 | 0 |  |
| dungeons_and_dragons_pro-1_10_0_spike2 | 581 | 0 → 28 | 0 → 287 | 575 | 217 | 201 | 0 |  |
| elvira3-1_11_0 | 5416 | 0 | 0 | 5141 → 5299 | 75 → 233 | 28 → 186 | 268 → 110 | modes not told apart |
| elvira3-1_13_0 | 5416 | 0 | 0 | 5141 → 5299 | 71 → 229 | 28 → 186 | 268 → 110 | modes not told apart |
| foo_fighters_le-1_03_0 | 615 | 9 | 90 | 609 | 60 | 34 | 0 |  |
| foo_fighters_le-1_04_0 | 615 | 10 | 92 | 609 | 60 | 34 | 0 |  |
| foo_fighters_pro-1_04_0 | 615 | 10 | 92 | 609 | 63 | 37 | 0 |  |
| godzilla_le-1_13_0 | 658 | 25 | 288 → 290 | 607 → 638 | 337 → 356 | 313 → 331 | 45 → 14 |  |
| godzilla_le-1_16_0_spike2 | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| godzilla_pro-1_15_0_spike2 | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| godzilla_pro-1_16_0_spike2 | 658 | 25 | 288 → 290 | 607 → 638 | 339 → 358 | 314 → 332 | 45 → 14 |  |
| guardians-1_15_0 | 200 | 0 | 0 | 200 | 98 | 11 | 0 | modes not told apart |
| guardians_le-1_14_0 | 200 | 0 | 0 | 200 | 99 | 11 | 0 | modes not told apart |
| guardians_le-1_15_0 | 200 | 0 | 0 | 200 | 99 | 11 | 0 | modes not told apart |
| iron_maiden_le-1_16_0 | 231 | 14 | 107 | 225 | 66 | 58 | 0 |  |
| iron_maiden_le-1_18_0 | 231 | 14 | 107 | 225 | 66 | 58 | 0 |  |
| iron_maiden_pro-1_18_0 | 231 | 14 | 107 | 225 | 67 | 59 | 0 |  |
| james_bond_60th_le-1_10_0 | 19 | 0 | 0 | 19 | 0 | 0 | 0 | modes not told apart; no sounds: no clip's code asks for a sound by a fixed number |
| james_bond_60th_le-1_11_0 | 19 | 0 | 0 | 19 | 0 | 0 | 0 | modes not told apart; no sounds: no clip's code asks for a sound by a fixed number |
| james_bond_le-1_06_0 | 1483 | 0 | 0 | 1474 | 166 | 125 | 0 | modes not told apart |
| james_bond_pro-1_06_0 | 1483 | 0 | 0 | 1474 | 160 | 124 | 0 | modes not told apart |
| jaws_le-1_01_0 | 650 | 33 | 400 | 644 | 448 | 433 | 0 |  |
| jaws_le-1_02_0 | 650 | 33 | 402 | 644 | 448 | 433 | 0 |  |
| jaws_pro-1_02_0 | 650 | 33 | 402 | 644 | 448 | 433 | 0 |  |
| john_wick_le-1_01_0 | 681 | 20 | 94 | 649 | 64 | 48 | 0 |  |
| john_wick_le-1_02_0 | 721 | 20 | 105 | 680 | 71 | 55 | 0 |  |
| john_wick_pro-1_02_0 | 721 | 20 | 105 | 680 | 71 | 55 | 0 |  |
| jurassic_park_le-1_15_0 | 337 | 20 | 144 | 337 | 116 | 101 | 0 |  |
| jurassic_park_le-1_16_0 | 337 | 21 | 149 | 337 | 116 | 103 | 0 |  |
| jurassic_park_pro-1_16_0 | 337 | 21 | 149 | 337 | 117 | 104 | 0 |  |
| jurassic_park_the_pin-1_05_0 | 165 | 0 | 0 | 165 | 70 | 53 | 0 | modes not told apart |
| king_kong_le-0_96_0 | 454 | 29 | 278 | 420 → 429 | 21 → 30 | 18 → 27 | 28 → 19 |  |
| king_kong_le-0_97_0 | 454 | 29 | 278 | 420 → 429 | 21 → 30 | 18 → 27 | 28 → 19 |  |
| king_kong_pro-0_97_0 | 454 | 29 | 278 | 420 → 429 | 21 → 30 | 18 → 27 | 28 → 19 |  |
| led_zeppelin_le-1_20_0 | 163 | 0 → 10 | 0 → 38 | 157 | 63 | 52 | 0 |  |
| led_zeppelin_le-1_21_0 | 163 | 0 → 10 | 0 → 39 | 157 | 64 | 52 | 0 |  |
| led_zeppelin_le-1_22_0 | 163 | 0 → 10 | 0 → 39 | 157 | 65 | 53 | 0 |  |
| led_zeppelin_pro-1_20_0 | 163 | 0 → 9 | 0 → 36 | 157 | 64 | 52 | 0 |  |
| led_zeppelin_pro-1_22_0 | 163 | 0 → 9 | 0 → 37 | 157 | 64 | 52 | 0 |  |
| mando_le-1_44_0 | 539 | 0 → 20 | 0 → 345 | 531 | 89 | 67 | 0 |  |
| mando_le-1_45_0 | 539 | 0 → 20 | 0 → 345 | 531 | 89 | 67 | 0 |  |
| mando_pro-1_45_0 | 539 | 0 → 20 | 0 → 345 | 531 | 86 | 67 | 0 |  |
| metallica_spike-1_03_0 | 287 | 0 | 0 | 287 | 59 | 47 | 0 | modes not told apart |
| metallica_spike-1_04_0 | 287 | 0 | 0 | 287 | 60 | 47 | 0 | modes not told apart |
| munsters_le-1_27_0 | 454 | 0 → 14 | 0 → 256 | 215 → 377 | 72 → 79 | 53 → 60 | 232 → 70 |  |
| munsters_le-1_28_0 | 454 | 0 → 14 | 0 → 256 | 215 → 377 | 74 → 81 | 53 → 60 | 232 → 70 |  |
| munsters_pro-1_28_0 | 454 | 0 → 14 | 0 → 256 | 215 → 377 | 74 → 81 | 53 → 60 | 232 → 70 |  |
| rush_le-1_18_0 | 305 | 16 | 21 | 298 | 131 | 101 | 0 |  |
| rush_le-1_19_0 | 305 | 16 | 145 | 298 | 132 | 102 | 0 |  |
| rush_pro-1_19_0 | 305 | 16 | 21 | 298 | 131 | 101 | 0 |  |
| star_wars_elg-1_10_0_spike2 | 932 | 0 | 0 | 670 | 506 | 500 | 262 | modes not told apart |
| star_wars_le-1_30_0 | 988 | 0 → 25 | 0 → 302 | 611 → 870 | 490 → 720 | 473 → 703 | 368 → 109 |  |
| star_wars_le-1_31_0 | 988 | 0 → 26 | 0 → 303 | 611 → 871 | 491 → 722 | 475 → 705 | 368 → 108 |  |
| star_wars_pro-1_31_0 | 988 | 0 → 26 | 0 → 303 | 611 → 871 | 491 → 722 | 475 → 705 | 368 → 108 |  |
| stranger_things-1_13_0 | 568 | 0 | 0 | 562 | 117 | 23 | 0 | modes not told apart |
| stranger_things_le-1_12_0 | 715 | 0 | 0 | 562 → 572 | 122 → 132 | 25 → 30 | 147 → 137 | modes not told apart |
| stranger_things_le-1_13_0 | 715 | 0 | 0 | 562 → 572 | 122 → 132 | 25 → 30 | 147 → 137 | modes not told apart |
| sword_of_rage_le-1_18_0 | 152 | 14 | 76 | 146 | 97 | 91 | 0 |  |
| sword_of_rage_le-1_19_0 | 152 | 14 | 76 | 146 | 96 | 90 | 0 |  |
| sword_of_rage_pro-1_19_0 | 152 | 13 | 75 | 146 | 94 | 90 | 0 |  |
| turtles_le-1_58_1.1987 | 359 | 2 → 24 | 25 → 184 | 353 | 135 | 112 | 0 |  |
| turtles_le-1_59_0 | 359 | 2 → 25 | 25 → 224 | 353 | 134 | 112 | 0 |  |
| turtles_pro-1_58_0 | 359 | 2 → 24 | 25 → 184 | 353 | 135 | 112 | 0 |  |
| turtles_pro-1_59_0.1987-upscaled | 359 | 2 → 25 | 25 → 224 | 353 | 134 | 111 | 0 |  |
| turtles_pro-1_59_0 | 359 | 2 → 25 | 25 → 224 | 353 | 134 | 111 | 0 |  |
| uncanny_xmen_le-0_97_0 | 388 | 0 → 11 | 0 → 168 | 388 | 199 | 158 | 0 |  |
| uncanny_xmen_le-0_98_0 | 393 | 0 → 11 | 0 → 165 | 393 | 202 | 162 | 0 |  |
| uncanny_xmen_pro-0_98_0 | 393 | 0 → 11 | 0 → 165 | 393 | 201 | 160 | 0 |  |
| venom_le-1_06_0 | 407 | 0 → 24 | 0 → 188 | 401 | 190 | 139 | 0 |  |
| venom_le-1_07_0 | 407 | 0 → 24 | 0 → 188 | 401 | 185 | 139 | 0 |  |
| venom_pro-1_07_0 | 407 | 0 → 24 | 0 → 188 | 401 | 185 | 138 | 0 |  |

Still no Played in (the toolbar says so): the plain-C titles (Aerosmith, Batman 66, Beatles,
Elvira 3, Guardians, Bond 60th, James Bond 1.06, Jurassic Park the Pinball, Metallica, Star Wars
ELG, Stranger Things), whose programs carry no class per mode, and Deadpool, whose award clips are
filled into tables by static initialisers the build places away from its 26 mode classes. Their
clip sounds are still read. Bond 60th's 19 clips get no sound: its program names 2 of them and
asks for no sound near either.

## Proof on the emulator

`sound_census.so` preloaded on a hidden, muted rig (slot 1), the title's port, `session2.sh`:
coin, start, plunge, every playfield shot switch 3 times twice round, drains. A listed pair counts
when its request reached the sound worker within 1 s of a showing of its clip (V line), as the
Godzilla proof did (record 38 of 38, next 16 of 18, name 56 of 59; function 6 of 28).

- **Uncanny X-Men Pro 0.98** (14 min, 83 showings of 44 clips, 333 requests): record 5 of 5
  pairs (median 0 ms after the clip), next 11 of 14 (median 4 ms), function 9 of 42. The kinds
  the tab shows as sure: 16 of 19. `function` stays a "may be", as on Godzilla.
- **Godzilla Pro 1.16** (13 min, one game): record 7 of 9, name 4 of 4, part 2 of 2, next 1 of 3
  (the end-of-ball loop, shown 61 times in a row), so 12 of 16 sure pairs at 1 s. Two of the scene
  clips the branch names showed (the Xilien broadcast, on the first shots of a game):
  ToThePeopleOfTheEarth_VO7 -> request 2002 and EarthWillContinue_VO7 -> 2005, both "kept with the
  clip". Each fired 3.2 s and 2.5 s after its clip appeared (the broadcast scene speaks its line a
  few seconds into the clip, past the 1 s window), and of the broadcast's 14 voice requests (1995 to
  2008) these two were the only ones that fired. The PAD-455 Godzilla LE 1.16 log agrees: in its
  broadcast only 2003 and 1318 fired, the two requests listed for AttentionInhabitants_VO8.
- **Elvira 3 1.13** (16 min, 129 showings of 44 clips): only 2 shown clips have a listed sound
  (next 1 of 1; one attract-background record 0 of 1). None of its 158 newly named scene clips
  (pop-up and trailer quips) came up in a game driven by switches alone.

Files: `work/artifacts/PAD-624/emulator/` (the logs, `correlate.py`, `session2.sh`, `up.sh`, the
census json and `census_table.md`).

