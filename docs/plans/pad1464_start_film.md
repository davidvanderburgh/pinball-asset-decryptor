# Menus at a game's start wait for its start film (PAD-1464)

Found by PAD-1410: a menu opened as a game starts (a whole-game mode's roster, a blocks mode's Open the menu at its
start) was drawn under the game's own start-of-game film and ran out its time unseen. Uncanny X-Men 0.98's GameIntro
runs about 15 s, no flipper skips it, and `pm_display_covered`, `pm_game_words` and `pm_clip_playing` read 0 all
through it. A C port could wait a fixed time (PAD-1410's did, 17 s); a blocks maker could not.

## What shipped

- `pm_start_film()` (pad_mode.h; pad_mode_runtime.c "PAD-1464: the game's own start-of-game film"): 1 while the
  game's start film plays, and in the first 1.5 s of a game before the game has asked for it; 0 otherwise.
- The runtime watches the clips the game asks for from its start (its `game_start` broadcast), through whichever call
  the build plays its clips with: `surface_set_video` (the video bank's surface; `surface_play` says a clip is
  looped), `clip_play` (taken as its own surface where the port has `video_surface`), `layer_video`.
  - the first clip asked within 1.5 s of the start, on the bank's surface, not looped and not named a loop, is the
    film; one asked up to 0.4 s before the broadcast counts when its name says film (X-Men Pro asks for GameIntro
    86 ms before it, Black Knight its title 137 ms before);
  - the next clip on its surface carries the film on when its name says film (intro, start or title, any case, and
    not loop: Avengers' GameIntro after its splash), and ends it otherwise;
  - it is over when its surface has stopped playing for 1 s, or after 120 s at most (Star Wars ELG's crawl is 86 s).
  - a port may name its films (`text start_film_clips <names>`, a trailing `*` a prefix: PAD-1114's line), which
    then count on any surface and looped, and alone; `text start_film_clips -` says the title's Start plays none over
    the HUD.
- The kit's menu (`intricate_kit.h` `kit_menu`) waits for it: opened under the film it is not drawn, its time is held
  and its buttons stay the game's; when the film is over it comes up with its whole time. A lane menu's plunge under
  the film takes the item it opened on. Blocks modes build on the kit, so Open the menu waits too.
- PAD-1114's co-op intro read `start_film_clips` as "the port names films": `-` is not, so it is unchanged there.
- The PAD-1410 worked example drops its fixed 17 s wait; MODE_SDK.md, MODE_PARAMETERS.md and MPF_PORTING.md say so.
- Port lines added: James Bond LE/Pro 1.06 `-` (GLDFNGR_Intro1 plays in the TV, under a mode's screens), John Wick
  LE 1.01/1.02 and Pro 1.02 `-` (NY_Night is the background), Jurassic Park The Pin 1.05 `-` (ScoreframeMap), Black
  Knight LE 1.18/1.19 and Pro 1.19 `BlackKnight_PhotoShoot_TitleScreen` (looped, 7.4 s), Jaws LE/Pro 1.02
  `game_intro_start` (its game_intro_loop after the film is under the HUD's skill shot), King Kong LE/Pro 0.97
  `Kong_Intro_*` (on a surface of its own, about 22 s).

## The census (emulator, every newest Spike 2 build; C:/tmp/PAD-1464 census_job.sh)

Each build booted hidden and muted with the runtime, its port and `cliplog.on`; credits and Start, no plunge; every
clip the game asked for logged and the glass shot every 3 s for 30 s (110 s for the long ones). Which titles' Start
covers the glass (no HUD on the shots):

| Start of game | Builds |
|---|---|
| a film over the whole glass | Uncanny X-Men LE/Pro (GameIntro 15 s), Avengers LE/Pro (splash + GameIntro 14 s), Jurassic Park LE/Pro (24 s), Jaws LE/Pro (44 s), King Kong LE/Pro (22 s), Star Wars ELG (crawl 86 s), Godzilla LE/Pro (intro, 8-9 s), Black Knight LE/Pro (title 7.4 s), Foo Fighters LE/Pro (7-8 s), The Beatles (Game_Start1 11 s) |
| the game's own chooser (its flippers, its time) | Aerosmith, D&D, Guardians, Iron Maiden, James Bond 60th, Led Zeppelin, Metallica, Munsters, Rush, Star Wars LE/Pro, TMNT |
| nothing over the HUD | Batman (a 3 s logo, no clip), Deadpool, Elvira, James Bond LE/Pro (in the TV), John Wick, JP The Pin, Mando, Stranger Things (both: the LE's title loops inside the HUD), Venom |

A game's own chooser is not a film: a menu of a mode's at the same moment shares the flippers with it, which is the
chooser's own business (the game's start menu work, PAD-615/1449), not this ticket's.

## Proof (emulator, hidden, muted)

- Every newest build (`census_job.sh`, a kit menu of 5 s opened on the game's start tick, rigbatch at 4x): see the
  final table below - the menu comes up when the film ends and runs its whole 5 s from then; with no film, 1.5 s after
  the start.
- Uncanny X-Men LE and Pro 0.98, the PAD-1410 port without its wait, built by the app's own Write
  (`C:/tmp/PAD-1464/xm`, xm_job.sh, 1x): the roster opens as FUTURE begins, waits 14.9 s for GameIntro (not drawn at
  4 s and 10 s, a right flipper press under the film not the menu's), comes up with its whole 10 s, a right flipper
  and Action pick STORM. Before (the branch's base, the same port): the roster ran out its 10 s under the film and
  took CYCLOPS unseen.
- King Kong LE 0.97 crashed in attract when the runtime logged from inside the game's `surface_play`; nothing is
  logged there now (the same build without that line passes).

## The final sweep (the committed runtime, C:/tmp/PAD-1464 go.sh s4 + s5)

A kit menu of 5 s opened on each game's start tick (rigbatch, 4x, 5 rigs, 53/53): "up" is how long after its open it
came up, "time" how long it then ran before its time took the item (5 s each).

| Build | The film | Over | Up after | Time |
|---|---|---|---|---|
| Uncanny X-Men LE / Pro 0.98 | GameIntro | 15.3 / 15.3 s, CityStreetMainPlay | 15.4 / 15.4 s | 5.0 s |
| Avengers LE / Pro 1.10 | GameStartSplashScreen, GameIntro | 14.1 / 14.2 s, MainplayBG_Taunt_MG | 14.2 / 14.3 s | 5.0 s |
| Jurassic Park LE / Pro 1.16 | JawsIntroToIsland_Title | 24.1 / 24.1 s, JawsMapProgressBGLooping | 24.2 / 24.1 s | 5.0 s |
| Jaws LE / Pro 1.02 | game_intro_start (port) | 44.3 / 44.1 s, game_intro_loop | 44.3 / 44.2 s | 5.0 s |
| King Kong LE / Pro 0.97 | Kong_Intro_Pod<N> (port) | 19.7 / 23.1 s, Kong_Island_Bg_02_SepiaFx | 19.7 / 23.2 s | 5.0 s |
| Star Wars ELG 1.10 | SW4_SCENE_001_edited | 86.3 s, SWUI01_Starfield_loop | 86.4 s | 5.0 s |
| Black Knight LE / Pro 1.19 | BlackKnight_PhotoShoot_TitleScreen (port, looped) | 7.4 / 7.7 s, MainplayV1 | 7.4 / 7.6 s | 5.0 s |
| The Beatles 1.29 | Game_Start1 | 11.0 s, its surface stopped | 11.0 s | 5.0 s |
| Godzilla LE / Pro 1.16 | intro<N> (port) | 8.4 / 10.4 s, its surface stopped | 8.4 / 10.4 s | 5.0 s |
| Foo Fighters LE / Pro 1.04 | GameStart.GameStart_part1 | 7.1 / 7.0 s, its surface stopped | 7.1 / 7.0 s | 5.0 s |
| Stranger Things LE 1.13 | (StrangerThings_Title loops inside the HUD: none) | 0.7 s | 0.8 s | 5.0 s |
| James Bond LE / Pro 1.06, John Wick LE / Pro 1.02, JP The Pin 1.05 | none (port: `-`) | - | at once | 5.0 s |
| the other 31 builds | none asked for | 1.5 s | 1.3-1.5 s | 5.0 s |

The 18 older shipped ports (and ports derived on a user's machine) take the same rule; the titles needing a line have
it on every shipped version (Black Knight 1.18, John Wick 1.01). The library's older builds are archival and were not
booted.
