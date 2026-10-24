# PAD-707: MORE KAIJU - more monsters on Godzilla's battle selection screen

David, 2026-10-24: "we know that people are going to want to add monsters to the selection menu. How can we do that"

The screen's seven places are compiled into the game (MODE_SDK.md "A monster in the roster", item 146): a place can
be taken, not added. Route 1 of the ticket, built: one place HOSTS A LIST of the card's own monsters, and a pick of it
opens a selection screen of ours. Routes 2 (rotating a place) and 3 (a real 8th place) are not needed.

## What changed

- **Runtime** (`pad_mode_runtime.c`, "PAD-707: MORE KAIJU"; `pad_mode.h`): `pm_roster_more(slot, name, page, callout,
  on_pick)` joins the list behind a place (the runtime claims the place for it; one list per game; a place a mode
  claimed itself cannot host one; 16 monsters), `pm_roster_more_leave`, `pm_roster_more_count`, `pm_roster_more_picked`,
  `pm_roster_start_after`. The pick of the place (or the city pick's replay of a lost one) is taken by the list; once the
  game's screen has closed (`roster_start_after_ms`) the list's screen opens as an internal mode (pm_begin as "MORE
  KAIJU", display priority 200): the build's page per monster shown, its words the seconds left; the cabinet buttons'
  switch shots are the list's (`more_buttons` in `switches_deliver`): flippers move the cursor with the game's own sounds
  271/272 and the monster's callout, Action or 13 s pick with 236. The ball waits in the scoop throughout (the scoop
  wrap holds it after the game's own event-2 hold returns, while `more_holding()`), until the monster's mode begins.
  The monster gets `on_pick(slot)` like a claimed place's pick, and its `pm_roster_over` is PAD-706's (the place's
  battle, won or lost). A lost monster is remembered per player: the city pick replays it with no list. The ball ending,
  another player up, another of our modes running, or a monster refusing gives the pick back as a lost battle. The list
  is kept in its monsters' names' order (the pages are drawn in that order); the building's lock is not closed for it.
- **Mode files** (`mode_file.c`): `roster_more [page]` with `roster_slot <n>` joins the list instead of claiming the place
  (`roster_callout` is the list's callout for it); a pick on the list starts it 300 ms later.
- **Blocks** (`block_modes.py`, `modes_blocks.js`): the battle hat's list offers every place twice - the battle, and
  "MORE KAIJU, in <battle>'s place" (`{"kind": "battle", "slot": n, "more": true, "picture": "monster.png"}`), with a
  Picture… button (`modes.blocks_pick("monster")` copies a PNG in as `monster.png`); the C joins the list
  (`BATTLE_MORE`, `MORE_PAGE`); assets.json carries `more`.
- **Form modes** (`mode_project.py`, `modes.js`, `webui/tabs/modes.py`): Starts on: the player picking "MORE KAIJU, in
  <battle>'s place" (`roster_more`), written as `roster_more PadMode_<slug>_More`.
- **The pages** (`more_kaiju.py`, called from `mode_assets.build`): one full-glass page per monster in the HUD scene
  (680x384 drawn, shown x2; title, portrait, name, "n OF m", the hint, the timer's box, the row of tiles with this one
  lit, eight at a time). Picture: `monster.png`, else the mode's screen picture, else `badge.png`, else lettered.
- **Ports**: Premium/LE 1.16, Pro 1.16 and Pro 1.15 `value roster_left_sound 271 / roster_right_sound 272 /
  roster_pick_sound 236 / roster_select_ms 13000`, read from each program's selection-screen switch handler (LE
  `0x191048`, Pro `0x18d3a8`; the Heisei 1.99D program the same as LE); `portgen.TITLE_VALUES` carries them.
- de/es/fr words; MODE_SDK.md (the roster section), MODE_PARAMETERS.md (the key, the field, five calls).

## Proof (emulator, muted, hidden; C:\tmp\PAD-707\rig, out_run*)

PROOF

## Decisions

- Which place: any (the hat says); one list per card (the build refuses two places, the runtime a second).
- A monster won completes the place's battle (PAD-706's progression), so after a win the place is Completed like any
  won battle; a lost monster replays through the city pick, no list.
- The place's own tile/portrait/name on the game's screen stay the card's (Heisei carries its own art); the Scenes tab
  changes them. Its callout is silent while the list holds it.
- Order: the monsters' names (both the build's pages and the runtime's cursor), not the project's order.

## Not done

- King of the Monsters starts the tier-1 battles itself (PAD-706): inside it a MORE KAIJU place plays the stock battle.
- Premium/LE 1.13 has no roster. Pro 1.15 is desk-read (its card is archival).
