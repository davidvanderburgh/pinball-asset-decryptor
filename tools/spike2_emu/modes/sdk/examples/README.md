# The kit and the desk harness

Two files every mode written in C (or made of blocks) can build with (read `../MODE_SDK.md` first). There
are no example modes here: the app ships no mode written for one title (PAD-691). A new code mode starts
from the SDK's template (`../template_mode.c`, TARGET RUSH), which runs on any title's own shots.

| File | What it is |
|---|---|
| `intricate_kit.h` | The kit: a shot debounce, the mode's HUD at the glass's edges, the playfield's inserts, light shows, the display priority, a countdown, a new-game witness and a pack ledger. A blocks mode's C includes it (the app copies it beside the C at every save); a code mode includes it when it wants it. |
| `kit_shipped.txt` | One sha256 per `intricate_kit.h` the app has shipped: a mode folder's copy that is one of them is brought up to the app's kit at the next build, an edited one is left as it is (PAD-390). |
| `desk_harness.c` | Plays modes at the DESK, without the game (below). |

## The kit

- **a debounce**: one shot counts once in 250 ms. A target that bounces, or is hit twelve times in
  a second, pays at most four times (`... again 83 ms after the last: counted once` in the log);
- **the HUD** (`struct kit_hud`): the mode's title and line above the score panel, counters across the
  top, a timer badge, a gauge on the right edge, in the game's own font (MODE_SDK.md, "A mode that looks
  like the game's own"), stepping aside while one of the game's own modes has the middle of the screen
  (MODE_SDK.md, "Stepping aside");
- **the playfield's inserts** (`struct kit_lamps`): every tick a mode says which SHOTS are lit and how
  (a colour, a pattern, a speed), and only a change reaches the game. They are held in one layer at
  priority 200, over every light show the game runs, and handed back the moment the mode ends, a drain,
  or a tilt. SOLID = lit, no clock; BLINK = lit with a clock, faster as it runs out; PULSE = optional;
  DIM = in a sequence, not next yet;
- **light shows** (`struct kit_show`): a few steps - a burst or an implosion from a place, a sweep -
  over the inserts the port places (`pm_lamp_xy`, `pm_lamp_paint`);
- **the display priority** (`kit_display`): taken right after the mode starts and given up before
  `pm_end`; the mode's words wait while a display of the game's covers them (`pm_display_covered`);
- **the tilt**: a mode ends on the game's tilt event;
- **a countdown** with the game's own "ten seconds" and 5..1 voice;
- **a new-game witness** (player 1's score back to 0) for per-game counts;
- **the pack ledger**: which modes each player played and won this game. The ledger, the running mode
  and the screen up are WEAK definitions in the header, so every file that includes it shares one copy
  inside `mode.so`, and a file built alone still links.

## Play a mode at the desk

`desk_harness.c` stands in for the game: it calls every mode the way the runtime does and prints
every score, word, light command, insert held or handed back, display priority and callout
(`covered 1` makes a display of the game's cover the mode's words; `lamps` lists what is held). Its
head comment lists every command. It needs a Linux (ELF) C compiler.

```bash
gcc -std=gnu17 -I.. -I. -o harness desk_harness.c ../template_mode.c
./harness new_game shot "Left ramp" shot "Left ramp" shot "Left ramp" secs 12 ball_end
```

The block compiler's tests play their programs this way (`tests/test_stern_block_modes.py`, and the
Godzilla programs kept as test material under `tests/mode_examples/`).
