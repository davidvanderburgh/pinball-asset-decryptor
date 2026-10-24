# PAD-699: alternate shots for the game's own Godzilla battles

David, 2026-10-23 (internal): "On our daveyvandy custom code, I know we're going to be asked to change the rules
for the modes like gigan and biollante and space Godzilla etc. Go ahead and make modifications to those main
monster modes that make thematic sense. Choose alternate shots and integrate into the modes."

The Heisei 1.99D card renames the game's own battles (read off its numbered lines 3257-3265): Ebirah ->
BIOLLANTE, Titanosaurus -> DESTOROYAH, Gigan -> GIGAN, Megalon -> SPACEGODZILLA, King Ghidorah, Megalon and
Gigan multiball -> MEGAGUIRUS, Ghidorah and Gigan -> BATTRA.

## What the app does now (generic)

- **`instead_of` rows** (runtime stock-rules section, stock_remap, the Modes tab's Shots): a shot of your choosing
  counts as one of the rule's own AND the old shot no longer counts while it is lit. MODE_SDK.md "Instead of".
- **The light moves with the shot**: the new shot's inserts show the game's own light for the old one, every
  tick; the old ones are dark.
- **The 0x1 switch-hit bit rides along**, so the Big loop (`0x1000000001`) can stand in.
- **Every one of the game's own modes is named** in the three Godzilla ports (`rule` lines, 25-26 of them) and in
  a derived port (portgen REVISION 6), so every battle's page has Shots.
- **The shot slot is the build's own.** Pro 1.16's port had Premium/LE's 42 / 45; its vtables have 41 / 44
  (`game_mode_blocks.stock_shot_slot` reads it off the shot entry v[15]; portgen sets it on a derived port).
- **A project on a card whose name carries no version** (David's Heisei raws) gets its Shots from the build the
  tab read off the game program.

## What David's project carries (not the app)

`HEISEI v1.99D + daveyvandy modes`: `modes/stock.json` (12 rows) and `text/strings.tsv` (15 instruction lines),
explained in its "PAD-699 notes/what changed.md".

| Battle | old shot(s) | new shot(s) | why |
|---|---|---|---|
| BIOLLANTE | Pop bumper final blow | Godzilla target (the captive ball) | breath into her maw |
| DESTOROYAH | Powerline L / C / R | Left ramp / Big loop / Right ramp (Maser finish kept) | it evolves and takes flight; the freeze ray ends it |
| GIGAN | both ramps | Big loop, Building | the cyborg flies and slashes the city |
| SPACEGODZILLA | the ramps (when his shot hops there) | Shield target left / right | the crystal spires; his tower is the Building |
| KING GHIDORAH | ramps and Building | the three shield targets | three heads; RGB inserts keep its arrow colours |
| MEGAGUIRUS | Building jackpot | Big loop | the dragonfly's speed |
| BATTRA | - | unchanged | its first phase pays shots with no lit field: a move cannot land |

## Proof

Emulator (muted, hidden, rig 1): stock Premium/LE 1.16, David's Heisei 1.99D v20 card (the app-rendered
stock.cfg), Pro 1.16 (Gigan and Ebirah). Details in MODE_SDK.md. Scratch: C:\tmp\PAD-699 (rig/ jobs, ghidra/
decompiles of the six handlers, text_patch.py).
