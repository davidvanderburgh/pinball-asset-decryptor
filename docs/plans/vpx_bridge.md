# The Spike 2 emulator behind a Visual Pinball table (PAD-775)

David, 2026-10-27: "i've downloaded a godzilla VPX table. i want to wire in
our emulator to it to be able to play our emulated godzilla images (custom or
stock) on it. it should have everything that our emulator can do (lights,
screen, switches, solenoids, etc.)" - and, once the survey was in: "Build it
on the marty02 table. Retrofit any switches or lights as needed." Mid-way:
"birdman-pin tells me there's also some vpx tables floating around for Foo
Fighters and Rush. we can add those to the test cases here too."

Everything that runs is in `tools/spike2_emu/vpx/` (its README is the user's
guide); this is the record of what was found and decided.

## What exists out there

VPinMAME has no Spike or Spike 2 core, so no VPX table of a 2016+ Stern runs
the real game. The Virtual Pinball Spreadsheet database (filtered for Stern
2016+ and for Originals named after our library's titles) shows two kinds:
scripted tributes with their own VBScript rules and no ROM (VPW's Iron Maiden,
GotG Pro, Aerosmith Pro, JP's Deadpool, marty02's Jurassic Park / Mandalorian
/ Jaws 50th / Bond 60th, Rush LE Tribute, Munsters, BKSOR, Led Zeppelin,
Batman 66 Premium), and mash-ups that borrow an OLDER game's ROM.

David's download, marty02's "Godzilla Limited Edition" v2.6 (VPUniverse 8449),
is the second kind: "a remix of Sega's Godzilla table and Stern's Godzilla
playfield". Its script loads `SEGA.VBS` on ROM `godzilla` (Whitestar, 1998)
- but its playfield texture is a photo of the real Stern Premium/LE playfield
and its objects follow it (building, bridge, Mechagodzilla, Godzilla toy, 35
triggers, 7 targets, 3 spinners, 11 kickers, 183 lights). Laid next to the
rig's `dump/tables/godzilla_le/playfield.png`, the layouts match. Right body,
wrong brain: the best host there is.

## The design

A VPX table talks to its brain through one COM object with a fixed shape
(`VPinMAME.Controller`), and `core.vbs` does all the talking. So the bridge is
that object, backed by the rig instead of a ROM:

* **PAD.Controller** (`padcontroller.py`): switches in through the rig's
  `padsw` block - written from INSIDE WSL by one `swkeys.py` per session,
  because a Windows write to the guest's mmap races it across 9p (the
  playfield window's rule); lamps and coils out by re-reading `padled` over
  `\\wsl.localhost` ~100 times a second. The LCD is the game's own window.
* **One numbering** for every table: switch 1000+id, solenoid 1000+node*16+
  index, lamp 1000+node*100+index. Below 1000 the title's map translates.
* **The table is patched, not rewritten**: `vpxfile.py` reads the compound
  file, swaps the script, appends cloned GameItems for the lights and the
  trigger the table lacked, and RE-SIGNS it - VPX refuses a file whose MD2
  MAC does not match. The digest rule was read out of pintable.cpp /
  BiffReader.cpp (key, version, TableInfo strings, CustomInfoTags, GameData
  records as tag+payload with CODE's length word left out, collections) and
  reproduces the stock table's MAC bit for bit.
* **The map** (`godzilla_le.vpxmap.json`) was built by fitting the drawing
  (313x710) to VP units (952x2362) on twelve anchor pairs (flippers, outlanes,
  the pop bumper, spinners, targets; residual under 52 VP units), matching
  every Stern LED to the nearest table light, and deciding the switches by
  eye over the two overlays. 70 of 115 playfield LEDs land on an existing
  insert; the other 36 are retrofit lights cloned from `L21` at the Stern
  position. Switch edges with no Stern counterpart (Sega's extra rollovers)
  are dropped (number 0).

## What the machine does that a ROM would not

The first live test said it: the Start button reached the game and the
TROUGH coil came back, but a held flipper button produced no coil at all.
On Spike 2 the game installs a RULE per coil once (cmd 41: power, and in
byte 26 the input whose closing fires it) and the BOARD fires flippers,
slingshots and pop bumpers from their own switches - nothing crosses the bus
per flip. So `padled` grew a version 7 (`rule_pwr`, `rule_in`, published by
`hwshim.c coil_rule_note`), the controller reports such a coil ON while its
switch is made and the rule is live, and synthesises solenoid 1999 "flippers
armed" for core.vbs's `GameOnSolenoid` so the table flips from the key
(`UseSolenoids=2`), exactly as the board would.

Motors with no table object (Mechagodzilla's shield) get their end stops
answered by the controller (`switch_fakes`), as hwshim answers node-board
motors. The building is a node-board stepper the shim already plays.

While a table is attached the rig's `ballfeed.py` stands aside
(`dump/ballfeed.off`): the table's `cvpmBallStack` owns six balls on
TROUGH 1..6 + JAM.

## Proof

* `vpxfile.py verify` on the stock table: computed MAC == file MAC.
* `cscript test_controller.vbs`: creation, every property core.vbs reads,
  ChangedLamps as a 2-D (number, state) array, Empty when nothing changed.
* `cscript test_controller.vbs run` against a hidden godzilla_le run: Start
  -> TROUGH coil (1129) on/off; the guest's `[sw]` log shows the edges tagged
  `v`; the flipper coil (1133) once padled v7 was in.
* `tests/test_vpx_bridge.py`: the digest rule, the CODE record, cloning, the
  v7 offsets against padled.h, the map's consistency, the patcher's rewrites.
* Visual Pinball itself: not installed on David's PC at the time of writing;
  the patched table and `PADSPIKE2.vbs` are staged beside the original pack.

## Next tables

Foo Fighters (Ryguy417 v2.0, VPU 14455; JP's 0.5.0, VPForums 19519) and Rush
(Rush LE Tribute 2.0.2, VPU 32514) are scripted tributes: their rules live in
the script and go, their hit subs stay and take Spike 2 numbers; each gets a
`.vpxmap.json` against `foo_fighters_le` / `rush_le`'s device tables and a
patcher for its own conventions. Same controller, same signer.
