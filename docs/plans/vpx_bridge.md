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

## A table from the title's own device tables (vpxgen)

David also asked for a table of another title to try, X-Men or James Bond.
James Bond LE's build ships positions for 96 switches and 393 LEDs over its
own playfield drawing (X-Men's only 55 LEDs), so `vpxgen.py` builds a table
from those: the drawing as the art, a Trigger at every rollover and opto, a
Bumper at every pop, standup and drop HitTargets, a Spinner, Kicker saucers
at the VUKs, eject and rocket locks (each wired to its coil), slingshot
walls, a Light at every positioned LED (RGB triples as one), three
flippers at the flipper coils, plunger and ball release in the shooter
lane, drain, outer walls and lane guides - 145 objects, 38 switches, 6
saucers, 86 lights for Bond - and the shadow bridge (vpxshadow.gen) over a
base script of the generator's own. The base file is Visual Pinball's own
"Nudge Test and Calibration" table, emptied of its items and collections
and resized to the drawing; the object prototypes
(`vpxgen_protos.json`) are its flipper, plunger, kicker, trigger, wall,
timer and gate, and a bumper, light, target, drop target and spinner with
every name, material, image and layer string blanked. No ramps, plastics or
sounds: the geometry made playable, for a title nobody has built a tribute
for.

Four loads taught four things: the table's own NAME must stay `Table1`,
since Visual Pinball names the script's events after it; a single-line
`If ... Then ... Else ...` inside a Sub is a compile error to VBScript's
parser here, so the flipper subs are block-form; core.vbs runs `vpmTimer`
on a Timer named `PulseTimer` (its `PulseTimer_Init` hands it over), so a
table without one has every `PulseSw` go nowhere - no coin, no hit; and
the coil table's group column is a board's PLACE in the title's node
directory, not its node (`group_node.txt`: Bond's group 7 is node 8), so
the first map reported no coil at all. The controller also looks for a
title's map in `~/.pad-vpx/maps` first, where the generator writes it,
since an installed kit's folder is not writable.

Proven 2026-10-27 23:42-23:52: Visual Pinball opened the generated Bond
table with no run up, the controller started james_bond_le on slot 3 of
PAD-Runtime and attached in 26 s; four coins (the card prices a game at
1.00) and Start began a game, the lockbar fired the auto plunger, the three
flippers fired from their coils, and the table's 86 lights agreed with the
machine's LED plane on every steady insert across four samples; closing
the table stopped what it had started. The ball itself has only the outer
walls, the lane guides and the slingshots to meet.

## Ramps and real geometry on the generated table

David (2026-10-28): "We should try to make the ramps etc in the vpx tables
instead of a flat design". The service-menu drawing is a complete line
drawing of the playfield - arch, orbit lanes, wireforms, ramp plastics,
lane guides, slings, apron - in the same coordinates as the switch and
coil positions, so a title's geometry is traced from it, by hand, into
`vpxgen_geo/<title>.json` (outline, walls, slings, ramps, ramp-riding
switches, drain, flipper placement, saucer directions), and the generator
builds it. A title without a geometry file gets an arched outline; the
automatic placing of switches, lights and coils is unchanged.

Bond's file traces the playfield arch, both orbit lanes (the right one up
the shooter side, the left one down to the left eject), the inlane guides,
both slings, the apron funnel to the drain, and the right ramp: a flat ramp
up from its enter opto (46), round the top past its exit opto (48), then a
return down the right-hand wireform's line to the right inlane. The side
ramp and the back-ramp wireform are not built: where they start and join
could not be read off the drawing, and the side ramp's enter opto (47) lies
under the right ramp as traced.

The proof is shot by shot: `vpxkeys.py shoot` fires a test ball from a spot
(a kicker off the table makes it, the script places and aims it) and the
table writes the ball's position and height every tenth of a second. Five
problems came out that way, each fixed:

* the ball's height stayed at its radius the whole way up: Visual Pinball's
  example ramp is decoration, Collidable off;
* the ball climbed to height 114, crossed 46 and 48, and rolled back down at
  the join of a flat ramp and a wireform: the return is a flat ramp now;
* a ball fired at a sling ended up rattling inside it: the polygon was
  wound clockwise on screen and Visual Pinball kicked it inwards
  (`sling_winding` reverses it and renumbers the kicking edge);
* an orbit ball wedged between the outer wall and the upper flipper: the
  flipper points down along the orbit's inner wall (the drawing's
  elongated shape) and its pivot moves a little right, and a deflector at
  the orbit's foot steers the ball off the outlane;
* the eject's handler called `PlaySoundAt`, which the base script lacked.

Proven 2026-10-28 11:58-12:19 on slot 1 of PAD-Runtime, the run started by
Visual Pinball itself: right-ramp shots at three speeds close 46, 48 and
the right return lane (61); right-orbit shots close 108, 81 and 92 and
reach the left eject (53), which the game empties; both slings kick out. A
real game: four coins and Start served a ball (trough switches moved, the
trough coil fired), the lockbar fired the auto plunger, the ball ran
108-81-92 into the eject and out to the side ramp target, the three
flippers fired from their coils, and the LCD showed 3,117,950 on ball 1.

The run started for a table brings up the game's LCD window, which took
the foreground - and Visual Pinball pauses the moment it loses it. The
controller now hands the foreground back to the player window it was given
in `Run` - ONCE, the first time the LCD window takes it (a second version handed it back for five minutes and so pushed the window away every time David clicked it to look at the game), and only from a window whose title
carries the kit's PAD-VPX label: proven in the same session (the log line
`foreground: [... PAD-VPX ...] -> the player again`, four seconds after the
launch).

## The LCD window over a full-screen Visual Pinball; sharing the kit

David (2026-10-28): the generated Bond table is not worth more; the two
tributes should be more usable, starting with the game's LCD window, which
a full-screen Visual Pinball covers; and the whole thing should be
shareable with somebody who has their own card image.

* When the controller starts a run it now puts the run's LCD window where
  the kit says and ON TOP (`padvpx lcd top | monitor 2 | x y w h | off`;
  the default is the upper middle of the main screen, 40% of its width in
  the LCD's 16:9). Two things it took: the controller process declaring
  itself DPI aware (a non-aware process's coordinates are virtualised, and
  the WSLg window landed at the top-left at the scaled size), and
  patience - a WSLg window re-places itself a few seconds after it opens,
  undoing a move that read back fine, so the placement is checked once a
  second and re-applied until it has stayed put for five checks (nine
  checks on this machine). Exclusive full screen would still hide it; the
  windowed kind is what Visual Pinball 10.8 uses by default.
* Sharing: the installer now registers PAD.Controller (HKLM, which only it
  can write) and ships `padvpx.cmd` with a Start-menu entry; `padvpx setup
  "<table.vpx>" <card.raw>` is the one step for the other person, who
  brings the PAD installer, Visual Pinball, their own download of the
  tribute and their own card. The kit shares maps and patchers, never a
  table.

## An all-in-one installer with a setup wizard

David (2026-10-28): the README had too many steps; the installer should
handle the prerequisites and the setup, with a wizard stepping through
where the windows appear; a clean, easy handoff.

* `padvpx wizard` (tools/spike2_emu/vpx/padwizard.py) is that window: six
  pages (machine, Visual Pinball, cards, tables, windows, play), each one
  a check with a button that fixes it. WSL 2 by `wsl --install
  --no-distribution` elevated; the runtime by the app's own
  `runtime.install` (with its replace-consent for a stale one, worded on the
  page); the controller by an elevated `padvpx register`; Visual Pinball by
  the 10.8.0 release zip (proven: 37 MB, unpacked flat, scripts/core.vbs and
  a tables folder in place); the tables copied from the build's own folder;
  the layout presets computed from the monitors found (a 2:3 playfield at
  full height on the left and the LCD in the rest at 16:9; a second screen
  for the LCD when there is one; Visual Pinball's own place) and written as
  the kit's `player`/`lcd` plus Width/Height/FullScreen=0 in the ini.
* The installer: `installer\vpx_tables\*.vpx` ships as `{app}\vpx\tables`
  when the folder exists at build time (gitignored; the beta build has the
  two tributes in it), a Start-menu "Visual Pinball setup", and a postinstall
  entry for the wizard, `runascurrentuser` because it writes the user's kit
  and ini and imports into the user's WSL; ticked by default only in a build
  that ships tables.
* Proven by stepping the page through all six pages under a harness that
  captures each (scratch wizshots.py), the download into a scratch folder
  with the kit redirected, and five tests on the pure parts (cards folder,
  table titles, one listing per shipped table, the presets, the kit and ini
  the layout writes, Visual Pinball found from the kit first).

## In the app, as a preview feature (PAD-802)

David (2026-10-28), after a tester's updates fought the beta installer (it
carried an old app stamped v1.273.1, so every update replaced it): put the
kit IN the app as a beta feature behind a preview code, with the mechanisms
to patch the known tables, and never distribute the tables themselves.

* `core/preview.py` FEATURES `vpx` ("Visual Pinball"); `tools/preview_code.py
  issue --name ... --feature vpx` makes a code. The rail shows the Visual
  Pinball tab (Play group, after Emulate) with a code, on Windows, for a
  manufacturer the Spike 2 emulator runs; unlocking or removing a code shows
  or hides it at once.
* The tab (`webui/tabs/vpx.py`, `static/js/tabs/vpx.js`) replaces the setup
  window: padwizard.py is gone, its pure parts are `vpxsetup.py`. WSL 2 and
  the runtime are the Emulate tab's job, so the tab only reports them.
* Each map names the download it fits: `table` {name, by, where}; the
  godzilla map gained the `output` name the patcher writes.
* The installer ships no table (`installer/vpx_tables` is gone from the
  script), has no Start-menu wizard and no postinstall wizard, and an update
  deletes the two Start-menu shortcuts v1.279.x made. It still registers
  the controller on every install.
* Proven: the tab's state on this PC (Visual Pinball, controller, runtime,
  card folder of 53 titles, the three tables with their cards), Patch through
  the tab's own code on drhotwing's Rush LE 2.0.2 and JP's Foo Fighters beta
  downloads (both "(PAD)" copies written), unlock and remove at run time,
  hidden without a code; tests/test_vpx_tab.py and the setup tests in
  tests/test_vpx_bridge.py.

## Lamps that show what the machine lights (PAD-859)

David (2026-10-30): "Bond VPX lights not mapped correctly. Most of them are
not mapped or are missing (starting a cat woman mode should light the
correct indicators)" - he meant Batman, and Bond as well, and the lessons
for every other table.

* **Bond** was mapped by guess: of the LE's 105 placed playfield LEDs, 14
  inserts had no table light (the left lane and right orbit arrows, the
  rocket ring, Oddjob, the flashers) and six lights sat on the wrong one
  (the side loop arrow on a light by the pops). The rig showed what it cost:
  in Rosa Klebb's henchman mode the game lights seven RGB shot arrows, and
  the table showed four of them. The map is rebuilt by place - the table's
  own art (it is the LE's real playfield) fitted to led_io.txt on 41 inserts,
  rms 6 px - and, where the tribute repainted an area, by the insert's shape;
  12 retrofit lights fill the inserts it lacks, 23 lights it has and the
  machine does not are held dark.
* **Batman 66**'s own `LampTimer` (every frame) read `Controller.ChangedLamps`
  whenever a backglass is up, a leftover of its ROM days; with `Controller`
  being PAD.Controller it took a share of the lamp changes, and the lights
  whose change it took stayed wrong. And the Catwoman billboards, Bat
  Computer, Crime Analyzer, pops and bat signal were never wired, because
  the tribute shows them with fader bulbs, plastic images and a flasher, not
  Lights: `lamp_calls` hands those LEDs to subs of its own. On the rig, the
  Catwoman ramp shots light both billboards (R+G); the table now does too.
* **RGB colour**: Spike 2 arrows say which mode a shot belongs to by colour;
  the bridge said only on/off. Lamps marked `rgb` now arrive as their colour.
* **Every other map**, through `vpxlamps.py audit`: JAWS was missing 40
  inserts (the return lanes, the beach rescue lights, the shark and Orca
  bash toys), Jurassic Park 26, Iron Maiden 18, Star Wars 14 (the Death Star
  lasers, the pops), Deadpool 1; `suggest` mended each by its fit (rms 1-6
  px). Aerosmith had Batman's lamp-stealing loop. Stranger Things' fit does
  not hold (its layout departs from Stern's) and its unwired inserts are its
  mode names: by eye, next. The builds that place no LEDs (Rush, Foo
  Fighters, Guardians, Sword of Rage, Aerosmith, TMNT) are checked by name.

Proof: rig frames of each mode, drawn through the controller and the map on
the table's art (`vpxlamps.py lit`), before and after; a cscript run of the
generated lamp code with stand-in lights; every patched table re-signs.
