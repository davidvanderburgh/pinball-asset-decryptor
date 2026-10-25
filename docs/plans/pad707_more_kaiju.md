# PAD-707: new monsters on Godzilla's battle selection screen (MORE KAIJU)

David, 2026-10-24: "we know that people are going to want to add monsters to the selection menu. How can we do that",
then: "redesign the new menu to look more like the original heisei ... add in a new monster to the existing menu but
modify the menu to fit it elegantly", "use the heisei scene as a starting point", three new monsters, the monster
artwork of the Heisei mod's kind.

The screen's seven places are compiled into the game (MODE_SDK.md "A monster in the roster", item 146). The first
build put a LIST behind one place with a selection screen of our own; David asked for the game's own screen instead.
This is that: the card build adds tiles to the game's screen, and the runtime drives the game's own cursor.

## What changed

- **The scene** (`battle_select.py`, new; `more_kaiju.py` now its bookkeeping): the card's own selection scene
  (`auto_loaded/cac32730...`, Heisei's on a Heisei card) read with `scene_tree`, laid out again: two columns (left: the
  places in groups - each game place, then the new monsters booked against it, a gap between groups holding new
  ones (David: "pick A | B, C | D, E, F") - split into two columns where the taller is shortest), smaller when they
  must be (three new: two columns of five at ~0.8),
  each place's lit tile, state box and "n/m" moved with its tile, the grey sheet hidden and each place's grey tile cut
  out of it. Per new monster: its grey tile, and Sprite groups `PadSel_<slug>_Lit/_Lock/_Done/_Portrait` (the card's
  own tile and portrait frames with the picture, the card's padlock and claw, the name lettered in Heisei's orange
  with katakana, fitted to the card's own name), and a `PadSel_Cover<n>` per place a new monster stands in. At most 5.
  `preview()` draws a still of it (the Modes docs' and the tests' look).
- **The runtime** (`pad_mode_runtime.c`, the section rewritten; `pad_mode.h`): `pm_roster_more(slot, name, page,
  callout, on_pick)` - each monster in its OWN place now. The screen's switch handler is vetoed for the two flippers
  (`site roster_screen_keys`) and the runtime walks the screen's order itself (the game's guards, sounds, clock bump
  and callout kept; locked places skipped); on a new monster the game's cursor is parked on its place, its groups shown
  and the place's portrait hidden. The game's own pick (`site roster_screen_pick` notes the tile) starts the place's
  battle, which the monster under the cursor takes. The old screen of our own, its scoop hold and its button
  routing are gone.
- **The build**: the engine reads the card's selection scene when the project has new monsters (`more_kaiju.wanted`),
  `mode_write.plan(stock_select=)` -> `mode_assets.build` writes it back with them on. `CodeAssets.has_assets` counts
  a new monster (a blocks monster with nothing else was left out of Try it's set: "no modes to try").
- **Ports**: LE 1.16, Pro 1.16, Pro 1.15 - seven sites, five values, the scene and node names (MODE_SDK.md); recipes
  recompiled; `portgen.TITLE_VALUES` carries the values.
- **Words**: "A new monster, in <battle>'s place" (blocks hat, form mode), the tips, de/es/fr.
- **Art**: the Heisei portraits are Toho's official Godzilla.jp stills repainted by DragonRR (Yandex: Destoroyah
  matched; SpaceGodzilla and Gigan pose for pose). The same stills for nine new monsters are in David's project folder
  `HEISEI v1.99D + daveyvandy modes\PAD-707 monster art` (his card's, never the app's).

## Proof (emulator, muted, hidden; C:\tmp\PAD-707\rig run7-run10)

- **Heisei 1.99D base card, run8** (Try it's own set): the screen re-laid, the walk Biollante -> Destoroyah -> Gigan ->
  SpaceGodzilla -> KAMACURAS -> KIRYU -> KUMONGA -> Biollante (tier 2 skipped), each new monster with its tile,
  portrait and name and the place's own hidden; Action on KUMONGA took slot 0's battle, two Buildings won it
  (`completed 1, wins 1, city 0's mask 0 -> 2`). Run7: the same mechanics, but the new pictures all on the glass -
  the game's lookup finds Sprites only (fixed: each shown picture in a group).
- **Stock Pro 1.16, run9 + run11** (the same three monsters as C, the stock card's scene built with them - the stock
  scene is byte-identical on Premium/LE 1.16 and Pro, md5 fceccfeb): the screen re-laid with Stern's own art, the
  cursor (which opens on the last place played there, Megalon) walked onto KAMACURAS, KIRYU and KUMONGA with their
  tiles, portraits and names; a pick of Gigan's own tile: `slot 2 picked (mode id 14): claimed but not taken - the
  game's battle runs`; run11: the screen's own 13 s timer picked KAMACURAS (`the selection screen picks KAMACURAS (in
  slot 1's place)`), its START 3000 ms later, two Buildings: `completed 1, wins 1, city 0's mask 0 -> 2`.
- **Stock Premium/LE 1.16, run10 + run13**: the same walk and look; run13: KUMONGA picked with Action (`the selection screen picks KUMONGA (in slot 0's
  place)`), its START, two Buildings: `the pick ends as a WON battle ... completed 1, wins 1, city 0's mask 0 -> 2`.
- No segv in any run. Runs from the D: card stalled at the game's start when two rigs read it at once (the known D:
  stall); every run here booted a copy in the rigs' card cache. Not run: Pro 1.15 (archival card; its sites read off
  its program, every one's words checked).

## Decisions

- Each new monster stands in one place, and its battle is that place's (won: the place is done in that city; lost:
  the city pick replays the monster). The place's own battle stays on the screen.
- The game draws, times and picks; the runtime only moves the cursor and shows our groups. Nothing in the program
  changes but hooks.
- Order: the monsters' names, both sides.

## Not done

- King of the Monsters starts the tier-1 battles itself (PAD-706): inside it a place's own battle runs.
- Premium/LE 1.13 has no roster. Pro 1.15 is desk-read (its card is archival).
- The new pictures are the person's: the build does not repaint a still into a card's style.
