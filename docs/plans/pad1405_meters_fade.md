# PAD-1405: bar meters and a screen fade

Rows 9 and 10 of the PAD-1398 analysis (`pad1398_xmen20_gap_analysis.md`): health bars per character, an energy
meter, and X-Men 2.0's fade to black with a red glow before the Optic Blast, without a clip.

## What was there

The HUD (`mode_hud.py`) has three counters, a timer badge and one gauge, and is built only into Godzilla's slide-outs
scene. Every other title gets a mode's screens (`scene_write.screen`, `add_screens`) in its port's `hud` scene, and the
runtime can only find, show/hide (`pm_show`, a Sprite's own visibility virtual) and word (`pm_set_text`) a node.

## Design

Both are SCREENS, so they go on every title that takes a mode's screens (X-Men LE and Pro included):

- `mode_meters.py`: a meter `PadMode_<slug>_Meter<k>` (up to 4) = a frame picture, its words in the game's words font,
  and 20 fill levels `..._L<j>`; a fade `PadMode_<slug>_Fade<k>` (up to 3, one per colour and look a mode's blocks
  use) = 16 strengths of one colour, a few pixels stretched over the whole glass, `flat` or `glow` (edges only).
- `scene_write.screen(layers=...)`: more pictures in the screen's group, each a Sprite holding its Bitmap (5 ids).
  `add_screens` moves the carried font's ids past the screens when they need more than `FONT_ID_GAP` (refused beside
  a Godzilla HUD, whose ids start at `FONT_BASE_GAP`). The layers use the plain class ids: the art and the group,
  written first, carry any inline class registration (`new_poly`).
- Pictures are PREMULTIPLIED (the game blends them so: run 2 showed a red glow as a solid red screen and the bars'
  empty part lit, both colour under clear pixels added to the glass).
- Kit (`intricate_kit.h`): `struct kit_meter` / `kit_meter_set` / `kit_meter_hide` / `kit_meter_tick`;
  `struct kit_fade` / `kit_fade_to(percent, ms)` / `kit_fade_off` / `kit_fade_tick`. Found twice a second, every
  level hidden at once, then only changes written.
- Blocks: `meters` in the program (label, colour, value, most = 100 unless said, numbers, at), shown while it runs and
  hidden as the info line is (under a layer, a game display, aside, at its end); the `fade` block (colour, flat/glow,
  to %, over ms); fades clear at its end. `CodeAssets.meters` / `.fades` carry what the build needs.
- Editor: a "meters" tick and a Meters list in the mode's settings; "Fade the screen" under Show and sound.

"Form" in the ticket is read as the blocks editor's settings form, where the HUD gauge is set up: a form mode (the
fixed-field kind run by `mode_file.c`) has no values a meter could follow.

## Proof (emulator, `C:\tmp\PAD-1405`)

`build_set.py` rebuilds the card's stock X-Men HUD scene with the build's own `mode_assets._code_screens` +
`scene_write.add_screens` into an override set, and the OPTIC blocks mode (`block_modes.to_c`, built with
`mode_file.c`) into the stage; `job.sh` (rigbatch, x1) starts a game and the mode and grabs frames on its fade lines.

- r1 (bare Bitmap levels): the groups and words found, no level found - all drawn, every bar full.
- r2 (Sprite levels): 3 meters x 20 levels, 3 fades x 16 steps found on LE and Pro; the colours wrong (not premultiplied).
- r3: both PASS. CYCLOPS 3/5 at 60 %, ENERGY 90 %, TIME draining; the black fade with the red edge glow and back; a red
  tint at once and clear; everything gone at its end.
