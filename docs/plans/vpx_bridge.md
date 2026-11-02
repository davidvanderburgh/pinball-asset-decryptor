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
  px). Aerosmith had Batman's lamp-stealing loop. (Jurassic Park's map was
  dropped by PAD-860 since - its table is not a faithful Jurassic Park - and
  its mend went with it; PAD-887 below has the table that replaced it.)
* **Names**: audit also compares each lamp's insert with what the build calls
  its LED. Two maps were wrong at the root: Guardians LE (the map the table
  prefers) carried the Pro's LED numbers, so on the LE card it lit other
  inserts - rebuilt by insert name onto the LE's RGB triples; and TMNT Pro's
  eight episode lights all sat on EPISODE 2 and its Foot Combo lights on
  FOOT COMBO 1.
* **Left as they are**: Stranger Things is an original layout on its own
  art; its unshown Stern inserts are the centre cluster of mode names, which
  the table has no inserts for, so none is placed by guess. Metallica's
  unshown ones are the Remastered machine's additions (UV lights, sling
  skulls, the hardwired lane lights) the 2013-layout table lacks. Backpanel
  lights (JAWS' Quint's bash toy, JP's M-A-P) are off the playfield.

On the rig (7 builds, attract and a game, rigbatch): lit inserts the table
shows went Guardians LE 36% -> 90% (and the 36% were the wrong inserts),
JAWS 65% -> 95%, Iron Maiden 77% -> 97%, Star Wars 81% -> 100%, Jurassic
Park 62% -> 79%, Deadpool 98% -> 100%, TMNT Pro 81% -> 84%.

Proof: rig frames of each mode, drawn through the controller and the map on
the table's art (`vpxlamps.py lit`), before and after; a cscript run of the
generated lamp code with stand-in lights; every patched table re-signs.

## Jurassic Park, on a faithful table (PAD-887)

A user pointed at JPSalas & marty's "Jurassic Park Pro Le" 4.02 (VPUniverse
20502) and David said to integrate it in place of the dropped one. Unlike
marty's Limited Edition it is the real machine: its playfield picture is
Stern's own Jurassic Park art, and fitted to the rig's drawing on seven
anchors (outlanes, return lanes, the three pops) it holds at 8 table units
(about 2 drawing px). Every Pro switch but the flipper EOS has a table
object within ~60 units, most within 20, and the table's lights fit the
build's LED places at 1.8 px. Its rules are JPSalas's usual template
(battles, jackpots), which the bridge never lets run; its ball paths are the
machine's.

Two maps, the Foo Fighters way: `jurassic_park_pro` (preferred; the table's
T-Rex, raptor pit and helicopter are scripted, and the Pro needs none of the
LE's mechs) and `jurassic_park_le`, which adds the raptor pit lock
(PyramidKicker as a saucer on LOCK-RAPTOR PIT), K7 as the left ramp's mouth
(its teleport sub kept) and Targetraptor as the motor bank's target. Three
switches are guesses: TARGET-LITE ESCAPE (the only target near it), RAPTOR
PIT-UP L (the target lane beside the pit) and the two Newton ball optos (the
table's jeep stands there). All 85 placed inserts are shown, 11 of them by
retrofit lights; the shadow game's 32 own insert lights are held dark.

**A spinner where the machine has an opto.** The table spins a spinner at
the right orbit's mouth and in the right half pipe, both optos on the
machine; a ball through either spins it a dozen times. `"event": "pass"`
pulses once a pass (every spin restarts a 600 ms quiet time).

On the rig (rigbatch, both builds): the patched table lights every insert
the machine lights, 19 of 19 in the Pro's attract, 10 of 10 in the LE's and
17-18 of 17-18 in an LE game, the RGB arrows in their colours. Both
patched tables re-sign, and their scripts compile under Windows Script Host
(the first runtime stop is `Table1`, which only Visual Pinball has).

## John Wick, on JPSalas & marty's table (PAD-905)

David added JPSalas & marty's "John Wick" 3.0 (the `John_Wick_Legend` pack:
table, backglass, PuP pack). Its playfield picture is Stern's John Wick art
and its lower half is the machine's: fitted to the rig's drawing on fifteen
switches (lanes, the left and right ramp targets, the pop and five of its
targets, the VUK) it holds at 17 table units, and its lights fit the build's
LED places at 1.2 px. The top is JPSalas's template moved onto that art: the
center ramp climbs to a guide (`guideramp`) that sends the ball either right
and down the long wire to the left inlane or left into the arch's lock (a
teleport from Karche into KArche1-3), the right ramp's top hops the ball
onto the right return wire (Kramploop), and the VUK and the crate are
teleports too.

Two maps. `john_wick_pro` (preferred): the table's car does not move and
its lock is scripted, and the Pro has neither (its CAR HIT OPTO is the
car's nose, below; its locks virtual) nor the drop target at the pops,
held down here. `john_wick_le` adds the arch's lock as a stack on LOCK 1-3
behind the LOCK POST (lockarche), the DIVERTER turning the guide, the drop
target (DROP TRIP/RESET; its opto is made while it is down) and the car's
front and hold optos; its motor's end stops are the rig's, as on any LE run.

**A kicker that teleports keeps its exit.** A saucer's new `kick_from`
names the kicker the ball leaves by: the VUK takes the ball in at
Krampcoude and the RIGHT VUK coil pops it out of Krampcoude1 onto the wire,
as the table's own timer did; the LE's lock takes it in at Karche and the
post lets it out of KArche3.

Mission triggers the shadow game keeps disabled are made live where they
are the machine's (SKILL SHOT 1/2 in the shooter lane), the life-ring
target where MID RIGHT TGT BOT is is made solid, and the return lane posts'
triggers are switched off (the machine has no posts). The machine switches
with no object here: POP TARGET 6/7, POP ENTER and the flipper EOS. One is
a guess: MID RIGHT TGT TOP (the crate face's top target).

**The Continental and the car (PAD-922).** Two of those guesses were wrong.
Laid over the machine's drawing, the table's self-kicking hole (`lock`) sits
at the mouth of the Continental's lane, where the machine's CAPTIVE BALL TGT
is, and the "lane round the car" is not there: the table walls its car in
(Ramp012 round its sides, the invisible Ramp034 across its nose), so a car
shot hit a wall no switch was on and a Continental shot reported the car.
`lock` is now CAPTIVE BALL TGT on both maps, `CapTrigger1` (the table's own
captive ball, top right, past the right orbit) is nothing, and the car is a
new trigger on its nose, `PadCarHit`: `retrofit_triggers` clones a trigger,
gives it its own drag points (`vpxfile.reshape_item`), switches it on, draws
it as nothing and puts it on the playfield (the obvious clone, the arch's
Tarche2, sits on Ramp023). It is the band 5 to 50 units in front of
Ramp034's face, so a ball touching the car's nose is inside it: CAR HIT OPTO
on the Pro, CAR FRONT OPTO on the LE (beside Target11). The LE's CAR HOLD
OPTO has no object now; the table's car never holds a ball.

On the rig (both 1.02.0 builds, rigbatch): the patched table lights every
insert the machine lights in every sample (the Pro's attract 54/54, 17/17,
69/69 and game 11/11, 13/13, 18/18; the LE's, whose first boot stayed in
Guided Setup there, 16/16, 39/39, 17/17, 19/19, 11/11).
Through PAD.Controller on the Pro map (hidden, muted): the first boot's
Guided Setup walked with the table's service keys (Plus to Save & Exit,
Select), coins and Start started a game (flippers armed, the trough coil),
the left flipper flipped, ten table objects reached the switches they are
named for, and a ball held on LEFT EJECT and on RIGHT VUK OPTO was kicked
by its coil. Both patched tables re-sign and their scripts compile under
Windows Script Host (the first runtime stop is a table object).

## The Beatles, on a Seawitch ROM table (PAD-926)

A user asked for "The Beatles" (Original 2018) v007 (VPForums; its archive
password was the user's to give, the table itself is not locked). Its body
is Stern's Beatles, which is a Seawitch playfield, and its brain was Stern's
1980 Seawitch ROM (`seawitfp`) under VPinMAME, with a script of the author's
own on top: five modes and Beatlemania, a ball save that destroys and
creates balls, a lock behind a post that makes a ball of its own, mystery,
three skill shots, extra points scored by pulsing the star rollover while a
wall holds the ball in play, and a PinUP pack. Fitted to the rig's drawing
(beatles 1.29.0) on 29 switches it holds at 18 table units (about 6 drawing
px); every one of the machine's 46 playfield switches has a table object, and
every placed insert a table light but JACKPOT (a cloned light).

So it is a ROM table, patched the Godzilla way: `beatles.vpxmap.json` and
`patch_beatles.py`. PADSPIKE2.vbs takes controller.vbs + stern.vbs's place;
Seawitch's switch numbers go to beatles' ids (both spinners pulsed Seawitch's
5: each its own now, by object); the tribute's own targets and triggers that
sent nothing become the machine's switches (`switch_subs`: the two orbit
targets, the mystery and super jackpot targets, the star as SKILL SHOT
ROLLOVER, the plunger rest as SHOOTER LANE, the orbit triggers as the orbit
optos); the drop banks' InitDrop numbers and the trough (four balls on TROUGH
1-6 + JAM) are rewritten. The upper flippers are their own coils (UP LEFT /
UP RIGHT FLIPPER on sULFlipper / sURFlipper) and their buttons (UP LT / UP RT
FLIPPER BUTTON) close with the lower ones' keys, as on the machine's one
button. The top magnet follows MAGNET-TOP; the record gets a magnet of its
own on a trigger cloned from the turntable's, on MAGNET-RECORD, and the
turntable turns on the two LED channels the drawing puts at the record
(MOTOR A0 / A1 DRIVER: one alone turns it one way, the other the other way).
The author's rules are emptied (`quiet_subs`: their callers stay, the subs do
nothing), PinUP Player is off (`PadNoPuP` stands in: the game's LCD is the
display) and the flasher domes and spinner flashes are lamp calls.

On the rig (beatles 1.29.0, hidden and muted, driven through PAD.Controller on
the map as the table drives it): every switch the map sends is in the run's
own switch table under the name the map gives it; coins and Start started a
game (flippers armed, the trough coil); all four flipper coils came back from
their buttons; each drop bank held down was reset by its own coil (LEFT 3 on
8, CENTER 4 on 7, RIGHT 4 on 9); the orbit optos and the top magnet opto made
the game fire MAGNET-TOP (and MAGNET-RECORD); the ball search fired the
slings, pops and auto plunger under the map's numbers; and 80 of the map's 85
inserts were lit at some point. Not seen lit in attract or a game: the record
motor's two channels and three flasher domes (RIGHT SLING, TOP MAGNET, UP
RIGHT FLIPPER; LEFT SLING, the same kind, was). That the motor channels turn
the record is a guess from the drawing; if the game never lights them, the
record stays still. The patched table re-signs and its script compiles under
Windows Script Host.

`padvpx` copies a backglass with a name of its own, too: the one
`.directb2s` in the download's `b2s` folder (The Beatles ships
`b2s\The-Beatles-Original-2018.directb2s`), or the only one beside a table
that is its folder's only table.

### PAD-933: four balls, and the playfield window of a bare `Controller.Run`

"Always ejects two balls": The Beatles counts **4 balls installed**, and the
table's trough held six. The game takes the balls in play as the balls
installed less those home, so at Start six home read as none in play and it
fired TROUGH again and again until the trough read 3. On the rig, driven
through PAD.Controller with core.vbs's ball stack played as the table plays
it (C:/tmp/PAD-933/proof3.py): six balls, three TROUGH fires at Start whether
SHOOTER LANE stayed made or opened again; four balls, one fire and none in
the 45 s after. The map's `switch_holds.balls` is the table's ball count now.

"Cannot move or resize the virtual playfield window": the tribute's script
calls a bare `Controller.Run` (TMNT's mash-up does too), so the bridge never
had the player window and PlayerGrips never came up (the log had no "player
grips on" for the Beatles, where John Wick and Deadpool had one). With no
window handed over, the bridge now looks the player up by its title once a
second while the run's windows are watched, as `_keep_player_front` already
did, and the grips, the placing and the size watch follow it.

### PAD-939: Patch again on every patched table

"Still getting two balls ejected... no button to do that in the app": the
fix for the trough (PAD-933) is in the patcher, and David's copy was patched
at 20:30 on Nov 1, before it (its script still had `bsTrough.Balls = 6`). The
tab gave a patched table only Play; Patch again came up only for a copy
patched for another model (PAD-900). Now:

* every patched table the kit knows has **Patch again**;
* a patch writes `<name> (PAD).patch.json` beside the table with the download
  it ran on (`padvpx.remember_patch`), and Patch again runs on that download
  without the file dialog while it is still there (a copy patched before the
  record asks for it, as the first Patch did);
* a map's `repatch` lists `{"old", "why"}`: a line only an earlier patcher
  wrote, and what patching again mends. The script written beside the copy
  is read for it (`vpxsetup.missed_fixes`, whitespace and case ignored), and
  the row says "Your copy was patched before a fix: <why>". The Beatles has
  one: `bsTrough.Balls = 6`, "it serves two balls at Start". A mark must be
  a line the current patcher never writes (tests/test_vpx_bridge.py checks).

Repatching David's download (`originals\beatles\The Beatles_007.vpx`) into a
scratch folder: `bsTrough.Balls = 4`, the record names the download, the mark
clears, and `vpxfile.py verify` says OK.

## What a table of a title needs: the author's checklist (PAD-941)

David (2026-11-02): "helpful game by game, table by table help to authors of
VPX tables on what is needed to complete integration, whether from scratch or
from existing work they've done: a checklist of all the switches and mechs
needed, and the lights that are missing from the integration."

The game sees a table only through its own numbers, and every one of them is
in the title's device tables the rig writes on its first run
(`dump/tables/<title>/`: device_xy.txt and led_io.txt out of the binary,
switch_list.txt out of the running game's heap, group_node.txt the coils'
addresses). `vpxauthor.py` reads them and writes one Markdown checklist
(`padvpx checklist <title> [--table x.vpx] [--out DIR]`; the tab's "For table
authors" card runs it and opens the file):

* every playfield switch with its id (the number the table sends + 1000),
  its service-menu number, node/bit, kind (lane, target, drop, opto, spinner,
  saucer, lock, magnet, mech end stop...) by its name, its place on the
  game's drawing, and what a table does for one of its kind (the map key
  and event); the flipper EOS marked as the board's; the cabinet switches
  PADSPIKE2.vbs presses set apart; the game's own virtual ones listed;
* every coil with node/index and the small solenoid number the map gives
  it, its kind, and what fires it: the node boards from their own switch
  (flippers, slings, pops: the table owes the switch, never the coil) or the
  game, which the table acts on through `solenoids`;
* every insert as one row per LED group (an RGB insert's three channels
  together), with its lamp number (1000 + node*100 + first index), the
  cabinet, speaker and topper LEDs set aside.

Against a table (`--table`), `padvpx.fitting` finds the kit's map, and the
same checklist carries a yes/NO column from what the map wires (every place a
map names a part: `switches`, the rewrite tables, `switch_subs`, holds,
fakes, trough, plunger, saucers, cabinet; `solenoids` with a callback or a
flipper number, `game_on`, the trough's kick; `lamps`, `lamp_calls`,
retrofit lights, GI and disc LEDs), with the gaps summed at the top of each
section, the coils the map lists with no table action ("listed"), the map's
GUESS marks collected, the table's own inventory (triggers, kickers,
targets, bumpers, spinners, flippers, lights, and whether its brain is a ROM,
a script or already PAD) and, when the map's switch names disagree with
this PC's switch table at the same id, the list of them - Rush's first map
was one off, and a stale switch_list.txt reads the same the other way. A
table no map fits gets `<title>.starter.shadow.json` beside the checklist:
every part of the machine in the shape vpxshadow.py reads, each under a
`TODO_<NAME>` key to rename to the table's object, the trough, plunger,
cabinet and flipper numbers filled in.

Where the tables are: `table_dirs` tries PAD_TABLES, the rig board's run
(padcontroller.Rig), the launch distro's rig (the app's data disk or its
home) and each slot's root, then every other distro's default rig; each
file is taken from the newest place that has it (`find_tables`). A build
that ships no positions (rush_le 1.19 read by reader 1) lists its parts
with none; one whose table names no coil or LED takes them from the map.

Proven on this PC's real tables and David's downloads (2026-11-02): Bond's
table against the LE map (63 switches, 19 the Pro table has no object for:
the jetpack optos, rocket locks and targets, tank targets; 86 of 86 inserts
shown; 10 GUESS marks); Rush (54 switches, 7 unwired: the drum clock and
lift ramp homes, the topper's four buttons, RUS(H) target...; 24 of 94
inserts no light shows); John Wick LE (10 switches the Pro-shaped table
lacks); TMNT Pro (19 inserts no light shows: the flasher domes and pop
lights); The Beatles (every switch, coil and insert wired); Godzilla LE
against Visual Pinball's own Nudge table (no map: a 46-switch, 14-coil,
90-insert starter map); and the stale Ubuntu-rig copy of rush_le's switch
table, where the checklist names all 25 ids the map numbers otherwise.
tests/test_vpx_author.py pins the readers, the coverage of every map shape,
the gap rules and the starter's shape; tests/test_vpx_tab.py the card.

David, on seeing it (2026-11-02): the card goes ABOVE the tables, every table
row gets a Coverage cell, and the checklist lives IN the app, themed, with
CSV export. So `vpxauthor.py data` hands the tab everything as JSON (the
parts with their marks, the summary, the notes, the GUESS and id lists, the
table's inventory, the starter map, and the same checklist as Markdown and
CSV), and the tab shows it as a sheet (a modal in the app's own tables, "Only
what is missing" to narrow it to the NO rows; Export CSV, Save Markdown, Save
starter map write the texts out). `vpxauthor.py coverage` gives each mapped
title's percentage (wired switches, game-fired coils and inserts over what
the table owes) from this PC's tables; the tab reads it once per sitting
and on Check again (ten seconds over WSL's share for twenty titles), and a
row's cell is the button that opens that table's sheet, checked against the
download it was patched from (or its (PAD) copy). On this PC: Beatles and
Jurassic Park 99%, John Wick 97%, Godzilla LE and Sword of Rage 96%, Bond LE
83%, TMNT 81%, Rush 78%, Stranger Things 76%.
