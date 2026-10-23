# PAD-691: the Godzilla example modes out of the app

David, 2026-10-23: "we don't need game-specific demo modes like this committed to the app ... if we make logic that
can be generic and reusable for title, then we commit it." TARGET RUSH (generic, on the card's own shots) stays as the
one example.

## What left the app

- **Form examples**: `mode_project.example_specs` / `example` / `EXAMPLE_SHAKES` (KAIJU RUSH, ATOMIC BREATH, MOTHRA'S
  SONG, MECHAGODZILLA). `examples_for(p)` is TARGET RUSH on every title, Godzilla included.
- **C examples**: `code_modes.EXAMPLES` and everything that existed only for them - the film recipes
  (`film_recipes.json`, `FILMS`, `FILM_TITLES`, `recipe_films`, `recipe_lines`, `find_film`, `film_dirs`,
  `example_spec`, `add_example`, `cut_example`, `recut_example`, `compose_art`, `missing_words`, `bed_file`), the
  Modes tab's code-example rpc (`code_example`, `add_code_example`, `cut_films`, `recut_code_modes`,
  `_films_needed`, `_code_examples_ok`), the code page's "Choose your films folder" banner and Film recipe row, the
  wizard's "Or start from an example in C" column (now the SDK guide's link with a line on what it holds), and
  `mode_from_card`'s bring-back of a card's code mode that was an app example (a card's code modes never carry C,
  so they are all named as not loadable, as any other code mode was).
- **Blocks examples**: the SDK's `blocks_examples/` folder and block_modes' loader (`EXAMPLES`, `example`,
  `example_names`, `adapt`, `fits`, `without_media`, `add_example`). The app offered only TARGET RUSH since PAD-675.
- **The stock-rewrite template**: `ebirah_rewrite.c` (Godzilla's battle vs Ebirah) was the only template;
  `stock_rewrite.TEMPLATES` is empty, so every rule's row says to write a rewrite against `pad_stock.h`.
  `TEMPLATE_DIR` lets a test hand it one.
- **`powerline_blitz.c`** (unused) and **`tools/spike2_emu/modes/film_pack/`** (item 143's Godzilla film mode pack,
  unreferenced) - both shipped under `{app}\tools\spike2_emu`.

## What stayed (generic)

- `sdk/examples/intricate_kit.h` and `kit_shipped.txt` (blocks modes include the kit; `refresh_kit` keeps project
  copies current) and `desk_harness.c` (plays any mode at the desk). The folder's README is now about those.
- The form mode's "Cut from a video" film cutter (`film_cut.py`, `modes_filmcut.py`): any video, any title.
- `CodeAssets.film` stays a field, so an older project's `assets.json` still loads; nothing reads it.
- The legacy padmode rig's `kaiju_rush*.mode` files: data for the pre-SDK `padmode.c` rig (`ensuremode.sh`,
  MODE_API.md), not something the app offers.

## Test material, moved under `tests/` (never shipped)

- `tests/mode_examples/form.py`: the four form modes exactly as the app had them (`example_specs`, `example`,
  `godzilla_examples` for the per-title shakes).
- `tests/mode_examples/c/`: the eleven C modes, `ebirah_rewrite.c` and `film_recipes.json`. test_spike2_intricate_modes
  stages them beside the SDK's kit (as the app puts a kit beside a code mode's C) and goes on proving the kit,
  the runtime and the desk harness with them.
- `tests/mode_examples/blocks/`: the fifteen blocks programs, `make_examples.py`, `hud_fit.py`, `blk.py`, `pack.py`,
  `recipes/`, and `examples.py` (block_modes' old loader and `adapt`). The block compiler's test material.
- Tests that only checked an example as the app offered it are gone: the code examples' menu, adding one
  with/without films, cutting a recipe, the recipe's sentences and JSON, the README's rules sheets.
