# PAD-723 - random clips on every Spike 2 title

From PAD-722's survey: random clips (PAD-446, a Video tab slot plays one of several clips at random)
were offered on Godzilla Pro and Premium/LE 1.16 only (`clip_variants.PROVEN`), though the runtime's
hook route existed on most ports. The ticket: sweep the library in the emulator, then widen.

## What the sweep found

A census first (`/dump/cliplog.on`, new: the runtime logs every clip the game asks for by name and on
which surface), on the 53 newest builds, attract and a short game each:

- **Most games ask for clips from banks other than the port's `video_bank`.** A card has several
  scenes that walk as video banks (`video.in_game_videos`, `video.in_attract_videos`, ...): The Beatles
  three, John Wick two, Venom two, Bond LE a nested one. And on Venom Pro, Stranger Things Pro, The
  Munsters, Rush, Metallica, Iron Maiden and Bond 60th the port's `video_bank` is the HUD (item 164
  grafts the modes' clips there), while the game plays its own from 60ed7e50.
- **Batman 1.14** plays its TV-episode clips (`S1E003_Clips.S1E003_00-00-10-11` ...) from a59b98f2,
  a scene whose library opens with a 3139-clip Video and goes on with the screens' Shapes, Fonts and
  Sprites: `video_bank.parse` refused it.
- **Deadpool** has neither clip_play nor the clip v2 lines: it asks its full-screen video LAYER for a
  clip by name (item 164's clip layer, `site layer_video`), e.g. `LilDeadpool_Intro` when the Lil'
  Deadpool targets are made.
- **Iron Maiden 1.18's 60ed7e50 is demand-loaded**: the resource manager does not hand it back by id
  (the runtime's scene lookup returns 0), though the game plays from it.
- **Metallica 1.04** has a clip whose name has spaces ("Metallica Moth into Flame v1"), which
  `video_bank.add_clip` refused, failing the whole build.

## What changed

- `clip_variants`: no per-build list. A title offers random clips when its port has a route
  (`hook_route`: `clip_play`, `surface`, or the new `layer`); 68 of the 69 shipped ports do (TMNT Pro
  1.58, an older build, has none). On a clip v2 build a slot also varies in any other scene of the
  card that walks as a video bank (`scene_of`, `card_banks`: read off the card when the Video tab
  asks, kept per card); the build reads that scene with the engine's reader (`read_card`), grows it
  and writes it beside the port's bank (`VariantBuild.others`). Two banks' clips of one name cannot
  both vary (the runtime finds a line by name): the second is left out with the reason.
- `clips.cfg`: `sclip <scene id> <name> <variants...>` for a clip in another bank. A demand-loaded
  bank's id is written `*<id>` when the build (`scene_counts`, every scene of the card) finds the
  clip's name in that one scene alone.
- Runtime (`pad_mode_runtime.c` "clip variants"): an `sclip` swaps only on its scene's VideoSurface
  (looked up per ask: `scene(id)` + `surface_find`), or on any surface while a `*` scene cannot be
  looked up; `on_clipv_layer` hooks `layer_video` on a port with no other route (r1 is the name's
  std::string, swapped when r0 is the layer's own video); `cliplog.on` census lines.
- `video_bank.parse_scene`: `parse`, or for a scene like Batman's the library's Video walked, the
  VideoSurface map found as the one other place the Video's name is written (and taken only when it
  names exactly the library's clips in order), and the max id an over-count of every flagged u32 in
  the file. `add_clip` grows such a scene; `spaces=True` for a random clip's name.
- New messages (the Video tab): `NO_ROUTE`, `NO_CARD` (de/es/fr).

## Proof

`C:/tmp/PAD-723`: `survey.py`, `findbanks2.py` (every walkable bank on every card), `census723.sh`
(rigbatch census job), `pick.py` (each build's most-asked clips in a walkable bank), `build723.py`
(a minimal project per build - the card's record, the slots' stock clips read off the card, three
30 s magenta-with-a-white-box random clips each - written by `engine.write_overrides`, the app's own
Try-it path), `prove723.sh` (rigbatch job: after attract, wait for a NEW swap, in attract or in a
game with the playfield switches poked; eight pictures at once), `magenta.py` (the glass check).
`prove723d.sh` is the same job gated on the glass (a swap counts only when a picture taken
right after it is >= 10% the magenta clip).

Result (2026-10-25): **53 of 53 newest builds play a random clip, seen on the glass** (`glass_final.tsv`:
every build has a picture 30-83% magenta: a full-screen clip ~83%, Bond's TV ~30%, Batman's episode
window ~36%). 38 passed on the first sweep; 13 had swapped only during the boot and then drew the stock
clip (one pick in four) in the job's window, and passed on a rerun with longer windows; Avengers LE/Pro
had swapped in the log while the trailer covered it, and passed on the glass-gated job. By route:
clip_play, surface (incl. other banks: Beatles, John Wick, Venom, Bond, the HUD-bank titles, Batman's
library scene, Iron Maiden's demand-loaded bank) and layer (Deadpool LE/Pro, `LilDeadpool_Intro`).
