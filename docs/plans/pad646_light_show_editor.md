# PAD-646: the light-show editor

David (2026-10-20): "We need a way to create light-shows from scratch in a beautiful and elegant way. Having
pre-programmed presets (like spiral outwards, fade up, left, whatever) with timing options and a way to preview
it in the App. It needs to be very sophisticated and transferable to the game. We should also be able to have
multiple light shows throughout a mode and make it very easy to use."

## What was there

A blocks mode's Run the light show block (PAD-376) picked one of eight ready-made shows, or "its own steps…":
up to ten rows of pattern / ms / two colours / place / pace / GI under the block, in the Blocks tab, with no
preview and no name. A second block wanting the same show copied the rows. The C engine (`block_modes._SHOW_C`,
the kit's `kit_show`) painted every placed insert each tick from the port's `at X,Y` places.

## What this ticket adds

**A mode's own shows.** `blocks.json` gains `shows: [{name, steps, repeat}]` (`block_modes._norm_shows`, up to
24 shows of up to 32 steps). A Run the light show block runs one by name
(`{"op": "show", "show": "mine", "name": "Kaiju roar"}`) from any rule, so one show serves the start, a shot and
the end, and a mode can have as many as it likes through its life. The ready-made shows and a block's own steps
still work as they were; the Light shows page offers to bring an own-steps block in as a named show.

**The Light shows page** (`modes_lightshows.js`, a tab beside Playfield over the one program and its undo):
- left: the mode's shows (a colour strip of each, its length, how many rules run it); New (blank, or from any
  ready-made show), Duplicate, Delete, rename (every block naming it follows);
- middle: the game's own playfield picture (PAD-612's `modes.blocks_playfield`) PLAYING the show - every placed
  insert painted by a JS mirror of the C engine, integer for integer (`fxColour`/`fxBlend`), the GI's setting
  dimming or flashing the picture; Play/Pause, Stop, Loop, a scrubber, the clock;
- right: the show's name and how many times it runs (once, N times, over and over until the mode ends); the
  steps as a timeline (a bar per step, as wide as it is long, its two colours, a hatch for its blend-in, a
  playhead); the step picked: pattern (grouped Rings / Sweeps / Beams / Flashes / Fades), time, blend-in,
  colours with a swatch row, centre (a place, or a point of its own picked on the picture), pace, GI; move,
  duplicate, delete; Runs: the rules that run it, and Run it when… to put it at the end of a rule or in a new one.

**The engine.** Six patterns more (a spiral outwards and closing in, ripples, a beam side to side, a fade up from
dark, one colour held), a per-step `blend` (the step mixes in from the one before over its first ms; the first
step from dark), a per-step point (`at: "xy"`, `x`, `y`), `repeat` (the show runs N times, or 0 = until the mode
ends: `show_last_pass()` in `end()` lets the pass it is in finish). The C keeps one table per show the blocks run.
`intricate_kit.h` (the examples' own copy of the engine) is untouched: a mode written in C keeps the kit it had.

**Presets.** Seven more ready-made shows as starting points: a spiral outwards, a spiral closing in, a fade up,
a sweep to the left, to the right, ripples, a beam side to side.

## Proof

- `tests/test_pad646_light_shows.py`: normalize / problems / notes / the C / the script text; the desk harness
  running a show twice, one until the mode ends (finishing its pass at the end, or replaced by the end's own
  show); the JS preview against the C engine colour for colour over every pattern (node + gcc); the wiring.
- `tests/test_stern_block_modes.py` light-show tests (PAD-376) still pass with the new engine.
- Before/after shots: `scripts/shot_pad646.py` (Godzilla Pro 1.15, the stock card's playfield picture).
