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
switch is made and the rule is live, and synthesises solenoid 40 "flippers
armed" (the map's `game_on`) for core.vbs's `GameOnSolenoid` so the table
flips from the key (`UseSolenoids=2`), exactly as the board would.

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
* Visual Pinball 10.8.0 (the GitHub release zip, unpacked to
  `C:\Visual Pinball`, David's say-so): the patched table loads (its MAC
  accepted), the script creates PAD.Controller, Start serves a ball through
  the table's trough, the game auto-launches it, the table's switches reach
  the game, both flipper buttons press AND release with their coils
  following, and the emulator's LCD shows BALL 1 of a game started from VPX
  (the picture on the ticket). Keys were fed through the table's
  `PadTestTimer` (`vpxkeys.py`), since VPX polls its keyboard itself.
  Six things VPX turned up on the way are in the README's last section:
  the truncated clones, core.vbs's load order, its `Dim`s, the key
  handlers, `SolCallback(68)`, and the pywin32 by-reference Null.

## The scripted tributes: Rush and Foo Fighters

drhotwing's "Rush LE Tribute" 2.0.2 (VPU 32514) and JP's "Foo Fighters" beta
(VPForums 19519) have no ROM: their rules are their script, wound through
every hit sub, timer and light. Rewriting that is a table of its own, so
`vpxshadow.py` does the smaller thing: the whole script stays and runs as a
SHADOW GAME that never gets a Start (its lights, sounds and ramp shows stay
lively), every switch object the map names gets a new event sub that hands
the edge to the controller and then calls the original (renamed `_orig`),
the ball goes where the REAL game says (Drain feeds a `cvpmBallStack` on the
trough switches, each scoop is a saucer stack whose coil the game fires, the
auto plunger fires on the game's coil, posts and drop resets follow theirs),
and the tribute's own ball creation and auto-launch lines are commented out.
The map is `<title>.shadow.json`; both are in this directory.

Three things these two turned up:

* **The flippers are the machine's coils, not the keyboard's.** JP's table
  flips from the key only while HIS game is in play, which it never is; the
  generated script sets `SolCallback(sLLFlipper/sLRFlipper)` to the table's
  own `SolLFlipper` / `SolRFlipper` (their flipper tricks and sounds stay),
  and the flipper keys stop reaching the shadow game. Stern's right button
  closes the upper flipper's switch too.
* **PinUP Player is optional.** Rush dies at `CreateObject("PinUpPlayer.
  PinDisplay")` on a machine without it; the patcher scans every `PuPlayer.`
  call, writes a `PadNoPuP` class with those methods and argument counts,
  and wraps the CreateObject so the class stands in.
* **Use the RIG's switch table.** The first Rush map was built from an older
  reading of the title that numbered every switch one higher: the table
  pressed Tournament Start for Start and filled the jam opto for TROUGH 1,
  and the game sat in attract. `dump/tables/<title>/switch_list.txt` from
  the run the table will attach to is the only numbering that counts.

Proven in VPX against hidden runs (2026-10-27): on both, Start (after a coin
on Foo Fighters, whose card had none) serves a ball through the trough, the
lockbar key (Left Alt, VPX's default) fires the auto plunger, both flippers
flip from their coils, the pops fire from the board, a drain feeds the next
ball (Foo Fighters' ball save re-served it), and the LCD shows the game
played: Rush at 430,160 on ball 1 charging the time machine, Foo Fighters at
109,760 on ball 2 picking a song.

## Lamps on the tributes

The rig's `led_io.txt` names every LED of both titles (170 and 176 off the
speakers and topper) even though these builds ship no positions, so the
tables' lights were matched to inserts by what each script does with a
light (JP's eight city lights follow his `ModeName` order; drhotwing's
colour-changing "planet" and "album" lights are the SHOOT ME and RECORD
arrows of whichever lane's hit sub checks them; pops, lanes, targets,
rock-o-meter, foobot, mods by place) - 102 lights on Rush, 117 on Foo
Fighters, the uncertain ones marked GUESS in the maps. The generated script
keeps a dictionary from lamp number (1000 + node*100 + first LED) to the
lights and fills it from `ChangedLamps` every tick through core.vbs's
`LampCallback`, with `UseLamps = 0` so core's 260-entry `Lights()` stays
out of it. The tribute's own light shows are quieted (`quiet_subs`, every
`LightSeq` stopped at init) and its hit subs are no longer called
(`orig_hits: false`, slingshots kept for their rubber animation): the real
game's LCD and sound say what a hit was worth.

Proof (2026-10-27): six times through a game on each table, the machine's
`padled` plane was sampled just before and just after a dump of every
mapped light (`vpxkeys.py lamps`); an insert reading the same in both
samples is steady and must agree. Rush: every steady insert agreed in all
six samples (89, 56, 88, 98, 87, 98 lights, the rest pulsing). Foo
Fighters: 112, 112, 107, 106, 107 and 116 agreed, the handful that did not
(an overlord target, a rock-o-meter step, the lockdown button) were inserts
the machine had just lit, caught before the next poll. Two things the
check turned up: Rush's `GIUpdateTimer_Timer` turns GI off by the number
of balls on the table (quieted); and with another ticket's library sweep
running foo_fighters_le on a second slot, the controller's title match
took the sweep's rig - `board_run` now takes the newest run of a title.
The generated script also puts the machine's last state back on every
mapped light twice a second, so a light show the shadow game still runs
cannot keep a light wrong for longer than that.

Ryguy417's Foo Fighters v2.0 (VPU 14455) is a second Foo Fighters table and
would take a map of its own.

## The kit: Visual Pinball starts the emulator

David (2026-10-27, bedtime): the app should not have to start the
emulator; Visual Pinball should, and PAD should only provide the patches.
The emulator already runs without the app (watch.sh in the pinned
PAD-Runtime distro), so this is a launcher, not a container:

* `padlaunch.py`: when the table's title has no run on the board, the
  controller starts one - the title's card (`~/.pad-vpx.json`, the kit's
  library directory's newest build, or `PAD_VPX_CARD`), a slot taken as
  `PAD-VPX`, `wsl -u root` + HOME + `PAD_PIVOT=1` exactly as the app's
  Windows launch does (a plain user launch refused on a slot whose NVRAM an
  earlier elevated run had left to root), visible and audible, with
  `PAD_PLAYFIELD=0` so the rig's own playfield window does not take the
  keyboard from Visual Pinball. `Run` returns at once and the poll thread
  attaches when padled carries the magic; the switch table is read again
  until the rig has written it (it comes a few seconds after the game).
  `Stop` kills what it started and releases the slot.
* `padvpx.py`: `register`, `library`, `patch` (the map's `detect` words say
  which table a file is), `card`, `run`, `stop`, `status`, `tables`.
* pywin32 joins requirements-windows.txt so the app's bundled Python can
  host the COM server; the vpx folder already ships with the rig.

Proven 2026-10-27 23:01: Visual Pinball alone, opening the Rush table with
no run up, brought rush_le up on slot 1 of PAD-Runtime (board entry in 8 s,
attached in 56 s), Start served a ball and the lockbar launched it; closing
the table stopped the run and emptied the board.
