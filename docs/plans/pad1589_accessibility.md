# PAD-1589: accessibility - color-blind insert colors and spoken scores

David (2026-11-25), idea 7 of the feature survey: no color-blind option and no speech anywhere in the app or on the
card. Spike 2 first; say what Spike 3 can take.

## What is built

Two ticks on the **Play options** tab (Stern Spike 2), each putting a row in the service menu's Custom Code page
(PAD-1382: a spare row, else one of the MORE SETTINGS rows). Neither changes a score, so a card carrying only these
stays on Insider Connected: the mode runtime runs them on its settings-only path (no score gate).

### Color-blind insert colors

- **Presets** (`plugins/stern/accessibility.py` `PRESETS`): red-green (protanopia and deuteranopia) and blue-yellow
  (tritanopia). Each is a hue map: every hue the game lights moves round the color wheel to another, in the same
  order, red and white staying put, the brightest and dimmest channel kept (so the level and every fade the game gives
  an insert stay as they are). Found by search over order-keeping maps (`C:/tmp/PAD-1589/cvd_lab2.py`), scored by the
  smallest CIE76 distance between any two of the colors Stern games light shots in (red, orange, yellow, green, cyan,
  blue, purple, magenta, white) as the Machado 2009 simulation shows them:

  | | as shipped | with the preset |
  |---|---|---|
  | red-green (protan + deutan) | 7.8 | 26.0 |
  | blue-yellow (tritan) | 16.7 | 30.4 |

  A one-color insert has one level and its own lens: it cannot change color and is left alone.
- **On the card** (`pad_mode_runtime.c` "accessibility", `access.cfg` `cvd <preset> <row>`): every tick, each RGB
  insert no mode of ours holds is read as the game shows it (`stock_game_rgb`: the game's own layers, ours left out)
  and, where the preset moves its color, held in the preset's color on a lamp layer of ours over the game's
  (`lamp_paint_as` for `acc_mode`); a color the preset leaves alone (white, grey, dark) goes back to the game. A mode's
  own colors go through the same map where `lamp_write` sends them. The COLOR BLIND row: 0 Off, 1 red-green, 2
  blue-yellow, starting on the project's preset; the runtime reads it every tick, so a change shows at once.
- **Preview**: the Modes tab's Light shows view has a Color-blind switch (Off / Red-green / Blue-yellow) beside Real
  LEDs / All RGB, and the emulator's playfield window draws the same, from one key (`cvd_preview`) in the shared
  playfield state file (`insert_colours.cvd_preview`). While a run's own card recolors (its runtime writes
  `dump/pad_cvd.now` every 2 s, in the emulator only), the window's preview stands down so nothing is recolored twice.
- The same integer maths in four places - `accessibility.remap`, the runtime's `acc_remap`, `cablights.cvd_remap`
  (the window cannot import the app) and `modes_lightshows.js` `cvdRemap` - held together byte for byte by
  `tests/test_pad1589_accessibility.py`.

### Spoken scores

- **The words** (`accessibility.WORDS`, 34: zero to nineteen, the tens, hundred, thousand, million, billion, player,
  points) are made at Write time in the computer's own voice (Windows: System.Speech; macOS: `say`; Linux: espeak-ng
  or espeak, else the tick says why), the voice's silence cut off each end (`trim_silence`: 0.18-0.62 s a word), and
  cached in the project's write cache. No recording ships with the app.
- **On the card** they ride the sound modes' road (`sound_modes` `SPEAK_BASE` 4100 + word: above the co-op sounds,
  below the jukebox, built as files in turn - the carrier's loudness, never cut), each a new record in `image.bin` on a
  carrier of their own (`engine._speak_carrier`: a request the game never plays; Godzilla LE 1.16: request 1251, sound
  idx 1920), listed in `sounds.cfg` as `sword <k> <request> <carrier key> <word key> <ms>`.
- **The runtime** (`access.cfg` `spoken <row> <left>,<right>`): at each ball's end (`on_ball_end`, or a hook of its own
  on a card of these only) it queues "player N <score>" (`acc_number`, the same words as `accessibility.number_words`),
  holds the end of the ball for it (`pm_ball_end_hold`, so the bonus waits; at most 10 s - a nine-digit score is 6.6 s)
  and plays the words one after another on the carrier, the record lookup taking each word's record in turn. A tilted
  ball comes to the ball's end twice (at the tilt and at the drain): the same player at the same score within 30 s is
  said once. In attract, the left flipper button held alone for two seconds says each player's last score; not while
  the start menu is up. SPOKEN SCORES: Off/On, Off to start with; without a row the card says no scores.

## Proof (emulator, Godzilla LE 1.16, `artifacts/PAD-1589/emulator`)

A set built by the app's own `engine.write_overrides` from a project with both ticked (`mkset.py`), run by `job.sh`
and `job4.sh` (rigbatch, x1, muted, hidden); RESULTS.txt there has the detail.

- The game's own colors held as the preset's (`colour-blind inserts: TOP SAUCER shown c00010 for the game's c00000`,
  the same values as `accessibility.remap`), switched live from the real service menu: 1 red-green, 2 blue-yellow
  (yellow ffff00 shown ffe300, blue 0000ff 002bff), 0 the game's colors back. On the wire to the insert boards
  (lamp_watch): with the preset on, reds carry its blue part (MECHA LANE cc0011) and no pure game red was seen.
- Six ball ends of a two-player game, six different scores, each said once and held for (3.7-4.9 s); the left flipper
  held in attract said both players' last scores; every sentence played word for word (`judge.py`: each word a sound
  worker play of request 1251 whose record lookup took that word's record). SPOKEN SCORES Off: the hold says nothing.
- Found on the way and fixed: a tilted ball reaches the ball's end twice (tilt, then drain); the flipper hold ignored
  the row. Godzilla's Action button light is driven outside the light layers the runtime paints over: it keeps the
  game's colors (it is no shot's light).

## Spike 3

The 64-bit runtime object (`mode64.so`) carries the same section and builds; the app refuses both ticks for a Spike 3
card for now (`accessibility.NO_SPIKE3`). What Spike 3 can take, from its ports: every one names the light layers, the
sound lookup and the scores, so the runtime side holds; inserts are named only in Star Wars ELG 1.10's port so far
(the others need their lamp lines first); the Spike 3 Write (`spike3_modes.plan`) would have to carry `access.cfg` and
the words (its sounds go by `spike3_music`'s record swap), and the menu rows are `spike3_menu`'s. A ticket of its own.
