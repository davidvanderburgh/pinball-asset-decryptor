# vpx - the Spike 2 emulator as a Visual Pinball controller

A Visual Pinball X table normally gets its brain from Visual PinMAME: the
table's script hands the ROM every switch a ball closes and reads back which
solenoids and lamps the ROM turned on. VPinMAME has no Spike or Spike 2 core,
so every VPX of a modern Stern is a scripted tribute or a mash-up on some older
game's ROM. This directory puts the REAL game behind such a table: the Spike 2
binary running in the rig (`tools/spike2_emu`, or the app's Emulate tab),
stock card or custom build, with its own LCD window and sound.

```
VPX table script ──Switch(n)=1──▶ PAD.Controller ──"<id> 1"──▶ swkeys.py ──▶ padsw ──▶ hwshim ──▶ the game
                 ◀─ChangedSolenoids/ChangedLamps── (poll thread) ◀── padled ◀── hwshim ◀── node bus frames
```

| file | what |
|---|---|
| `padcontroller.py` | `PAD.Controller`, an out-of-process COM server in the shape of `VPinMAME.Controller`. `--register` once (HKLM; David's PC elevates silently), `--status`, `--selftest`. |
| `PADSPIKE2.vbs` | the "system script" a table loads in place of `controller.vbs` + `SEGA.VBS`: loads VPX's own `core.vbs`, creates the controller, names the cabinet switches and flipper coils. |
| `vpxfile.py` | read, patch and RE-SIGN a .vpx: VPX refuses a file whose MD2 MAC does not match, and this reproduces the digest (proven bit-for-bit on the stock table). Writes through pywin32's structured storage. |
| `<title>.vpxmap.json` | the table-to-machine map: switch numbers, solenoid callbacks, every light's LED, the retrofit lights and triggers the table lacked. |
| `patch_godzilla.py` | applies `godzilla_le.vpxmap.json` to marty02's "Godzilla Limited Edition" v2.6: rewires the script, adds 36 lights and the Mechagodzilla magnet, re-signs. |
| `vpxshadow.py` | the patcher for a SCRIPTED tribute (no ROM): keeps its script as a shadow game, generates the bridge from `<title>.shadow.json`, neuters its own balls, makes PinUP Player optional, re-signs. |
| `rush_le.shadow.json`, `foo_fighters_pro.shadow.json`, `foo_fighters_le.shadow.json` | the maps for drhotwing's "Rush LE Tribute" 2.0.2 and JP's "Foo Fighters" beta. JP's table is a Pro's playfield (no upper playfield, no Overlord magnet), so Patch takes the Pro map, or the LE one when only an LE card is there (`padvpx patch --title` picks). |
| `vpxkeys.py` | presses keys in a running patched table through its `PadTestTimer` (a test does not depend on VPX having the keyboard); `lamps <file>` dumps every mapped light's state. |
| `padvpx.py` | the kit's command: patch a table (recognised by its map's `detect` words), register the controller, record cards, run and stop by hand, status. |
| `vpxsetup.py` | the app's Visual Pinball tab's half here: what is set up (Visual Pinball, the controller, the cards, each known table and whether it is patched), the card folder, the window layout, the Visual Pinball download, Play; one JSON line back. |
| `padlaunch.py` | starts a run for a title when Visual Pinball opens its table and none is up, and stops what it started. |
| `vpxgen.py`, `vpxgen_protos.json` | a table GENERATED from a title's own device tables (switch, coil and LED positions over the game's playfield drawing), for a title with no tribute; the prototypes are Visual Pinball's example table's objects with their strings blanked. |
| `test_controller.vbs` | `cscript //nologo test_controller.vbs [run]` - the controller from VPX's own script engine, with no VPX installed; `run` presses Start and a flipper through a live rig and expects the coils back. |

## Numbering

A Spike 2 machine has no Whitestar matrix, so a table script talks in one
convention (PADSPIKE2.vbs has the constants):

    switch   1000 + <Spike 2 switch id>          switch_list.txt `id`
    lamp     1000 + <node> * 100 + <LED index>   led_io.txt
    solenoid the SMALL number the title's map gives the coil (1..68)

Solenoids cannot be 1000+: core.vbs indexes `SolCallback(68)`,
`SolPrevState(68)` and friends by the number, so a coil needs one in that
range (`solenoids` in the map; the flippers keep core.vbs's own Consts
`sLRFlipper` 46, `sLLFlipper` 48, `sULFlipper` 36). A switch or lamp number
below 1000 goes through the map (`switch_rewrite`, `lamps`), so a table can
run on its original numbering while its map is being built.

## The kit: `padvpx`

Nothing here needs the app running. `padvpx.py` is the whole kit, run with
the app's own Python (`{app}\python\python.exe tools\spike2_emu\vpx\padvpx.py`
on an installed app; the venv's in a checkout):

    padvpx setup "<your table.vpx>" <card.raw>
                                           THE one step: controller registered if it is not,
                                           the table recognised and patched beside itself, its card recorded
    padvpx register                        PAD.Controller in the registry (the installer does this)
    padvpx library D:\cards                a directory of card images: a title's newest build is its card
    padvpx patch "<your table.vpx>" [--card <image>]
                                           recognise the table, write "<name> (PAD).vpx" beside it
    padvpx card <title> <image>            which card a title boots (padvpx card: list them)
    padvpx lcd top | monitor 2 | <x y w h> | off
                                           where the game's LCD window goes (below)
    padvpx run <title> | stop <title>      a run by hand, the way the controller starts one
    padvpx status | tables                 what is registered, recorded, up, and patchable

On an installed app the command is `padvpx.cmd` in the app folder, and the
installer registers the controller itself.

**The app's Visual Pinball tab** (a preview feature since PAD-802, the
preview code's feature `vpx`) is everything above with buttons, for somebody
who is not going to type any of it: the PAD runtime (the Emulate tab sets it
up), Visual Pinball (found, chosen, or the 10.8.0 release downloaded and
unpacked), the controller (registered by the installer; a Register button
repairs it), the card folder (which of the kit's titles it has a card for),
the tables the kit knows (each one named with its author and where it is
downloaded, and a Patch button that writes the "(PAD)" copy of the user's
own download into Visual Pinball's tables folder), a window layout for the
screens found, and Play. The tab runs `vpxsetup.py` (state and settings,
one JSON line back) and `padvpx.py` (patch, register) with the app's Windows
Python, so the kit's pywin32 and DPI awareness stay out of the app; it
writes only what the commands write: `~/.pad-vpx.json` and Visual Pinball's
ini. NO BUILD SHIPS A TABLE: the separate setup window (`padvpx wizard`)
and the beta installer that carried two patched tables are gone.

**The game window, borderless and on its own monitor (PAD-811).** One
setting places the game's display for every run, desktop and cabinet alike:
`padvpx display monitor 2` fills monitor 2, borderless; `padvpx display
monitor 1 window 0 0 1360 768` is a borderless window at that monitor's
corner; `padvpx display border on` puts the frame back; `padvpx display
free` returns it to wherever it was left (`padvpx display` lists the
monitors: 1 is the main one, then left to right). The app's Emulate tab has
the same choices. It is `display.conf` on the rig board, written by
`tools/spike2_emu/padisplay.py`, and the renderer (padglhost) of every
visible run reads it twice a second, so a change moves a running game's
window at once. The renderer does the moving, on the X side: a window moved
from Windows (SetWindowPos) cannot be dragged afterwards (padglhost.c, "THE
DELAYED MOVE"), so with a display setting the controller only keeps the
LCD on top of Visual Pinball. `padvpx lcd ...` below now writes this
setting.

**The LCD window.** Visual Pinball comes up full screen and would cover the
game's LCD window, so when the controller starts a run it puts that window
where the kit says and ON TOP: by default the upper middle of the main
screen, 40% of its width in the LCD's 16:9; `padvpx lcd monitor 2` fills
a second screen (a backglass monitor); `padvpx lcd 100 0 960 540` is a
rectangle; `padvpx lcd off` leaves it alone. ONCE: a WSLg window puts
itself back at the screen's top-left a few seconds after it opens, so for
its first fifteen seconds a window found there is placed again, and from
then on it is the user's to drag anywhere (the first version re-placed it
whenever it had moved, which read as a window stuck under the mouse). A
pause Visual Pinball sends while one of these windows is in front (the
user clicked it) leaves the game running; only a pause with Visual Pinball
itself in front freezes the rig. A full-screen Visual Pinball must be the
windowed kind for anything to show over it: its "Force exclusive
fullscreen" option stays off.

**Visual Pinball's own playfield window.** In windowed mode it is borderless,
so it cannot be dragged, and 10.8 ignores the `WindowPosX/Y` its ini
carries; `padvpx player 100 0` (or `player 100 0 900 1350`, or `player
monitor 2`) has the controller move it there once when a table opens, for
any run, its size Visual Pinball's own unless given. `padvpx playfield on`
asks for the rig's own virtual playfield window as well (off by default;
nobody needs it beside Visual Pinball), placed like the LCD, under it.

**Sharing a table with somebody else.** The kit never ships a table or a
card. What the other person needs: the PAD installer (the emulator, its
runtime distro, the bundled Python with pywin32, and this kit - all in it),
Visual Pinball 10.8, their own download of the tribute table from where its
author put it, and their own card image of the title. Then one command,
`padvpx setup "<their table.vpx>" <their card.raw>`, and the (PAD) copy
beside the table opens in Visual Pinball. A patched table could be handed
over as a file, since it is the whole original plus the bridge, but that
is the author's table to hand out, not ours - the kit's maps and patchers
are what we share.

Then open the patched table in Visual Pinball. The table names its title,
the controller looks for a run of it on the rig board (`~/.pad-rig/slot-N.run`)
and, finding none, STARTS one (`padlaunch.py`): the title's card, in
PAD-Runtime when that distro is installed (else the default distro), on a
rig slot of its own taken as `PAD-VPX` (the take as root too, on the app's
board in the Windows profile and in the app's rig on its data disk, so an
installed app's runs and the controller agree on both - PAD-803), as
`wsl -u root` with the user's HOME and `PAD_PIVOT=1` (the app's own launch
shape, so save states work),
visible (the LCD window on the desktop, for the backglass monitor) and with
sound, but without the rig's virtual playfield window (Visual Pinball is the
playfield, and that window would take the keyboard from it). `Run` returns
at once; the table plays once the game is up, half a minute to a minute
later, and `Controller.Stop` (Visual Pinball closing the table) stops what it
started and gives the slot back. A run started any other way (the app's
Emulate tab, `watch.sh`) is attached to and left alone; with several runs of
a title up, the newest is taken. The kit's record is `~/.pad-vpx.json`
(cards, library, distro, rig); `PAD_VPX_CARD` and `PAD_VPX_LIBRARY` override
it, and `PAD_WSL_DISTRO` / `PAD_ROOT_WSL` / `PAD_SLOT` name a run outright
when VPX is started from a shell that has them.

PAD ships no table: the kit patches the copy the user downloaded, and a
map's `detect` words say which table it is for.

While a table is attached, `dump/ballfeed.off` tells the rig's `ballfeed.py`
to leave the trough alone: the table's own `cvpmBallStack` owns the balls.
Keys are VPX's usual ones: 1 Start, 5 coin, the Shift keys flip, Esc
leaves. The launch button is Enter on Godzilla (marty02 wired it to the
plunger key) and the lockbar key, Left Alt by VPX's default, on Rush and Foo
Fighters (their scripts wired the Action button to `LockBarKey`).
`%TEMP%\padcontroller.log` says what the controller did;
`%TEMP%\padspike2.log` what the system script's load did.

A scripted tribute (Rush, Foo Fighters) is patched by `vpxshadow.py
<title>.shadow.json "<table.vpx>" <out dir>`; it needs no PADSPIKE2.vbs
beside it (its own script already loads core.vbs). The patched table is
`<output>` from the map, in the out dir.

## Testing without hands

Visual Pinball polls its keyboard itself, so a test cannot hand it a key from
outside reliably. The patched table carries a `PadTestTimer` that reads
`%TEMP%\padvpx_keys.txt` (one `down <code>` / `up <code>` per line, DirectInput
codes) every 100 ms and feeds the table's own key handlers; `vpxkeys.py start
launch lflip 400 rflip 400` writes those lines with the holds between them.
A whole play test is then a script: `cscript test_controller.vbs run` for the
controller alone, `vpxkeys.py` for the table in VPX, with the controller log
and the guest's `[sw]` log as the record.

The player window renders through DirectX and is not capturable by GDI,
`PrintWindow` or Desktop Duplication from a tool on this machine; the proof
picture of a run is the emulator's own LCD (`glshot.sh`) while VPX plays it.

## What Visual Pinball itself turned up (2026-10-27)

* **Every GameItem must close.** A light's shape is a run of DPNT drag points
  each with its own ENDB; a cloner that stops at the first ENDB writes a
  truncated item and VPX sits in "Loading" for ever. `vpxfile.item_records`
  walks the nesting.
* **core.vbs must load AFTER the table's Consts** (from `LoadVPM`, as
  controller.vbs + SEGA.VBS do): its load-time `IsEmpty(Eval("BallSize"))`
  brings an undefined `BallSize` into being, and the table's own
  `Const BallSize = 50` then dies of "Name redefined".
* **`Dim`s that core.vbs owns** (`Controller`, `vpmShowDips`) are set in
  `LoadVPM` after the load, never at the top of PADSPIKE2.vbs.
* **The system script owns `vpmKeyDown` / `vpmKeyUp`**; core.vbs's
  `KeyDownHandler` only calls them.
* **A VBScript variable handed to an indexed property put comes back Null**
  from a pywin32 server unless the put returns its arguments: `Controller.
  Switch(sw) = True` emptied `sw`, so every switch held through a variable
  died after its first use (the flipper stayed up, Start never released).
  `PadController._dynamic_` returns `tuple(args)` for every put.

## What the machine does that a ROM would not

* **Flippers, slingshots and pop bumpers are fired by the BOARD.** The game
  installs a rule per coil once (cmd 41: power, and the input whose closing
  fires it) and sends nothing per flip. `padled` version 7 publishes the rule
  (`hwshim.c coil_rule_note`, `coilmap.rule`), the controller reports such a
  coil ON while its switch is made, and synthesises solenoid 40 "flippers
  armed" (the map's `game_on`) for core.vbs's `GameOnSolenoid` so VPX flips
  from the key (`UseSolenoids=2`).
* **Motors the table has no object for** (`switch_fakes`): the controller
  answers their end stops itself, the way hwshim does for node-board motors.
* **The LCD and the sound are the rig's.** Nothing to bridge; put the game
  window on the backglass monitor.

## Scripted tributes (Rush, Foo Fighters)

A tribute has no ROM: its rules are its script. `vpxshadow.py` keeps that
script whole as a SHADOW GAME that never gets a Start (its lights, sounds and
shows stay lively), renames every event sub the map names to `_orig`,
generates a bridge that hands each edge to the controller and then calls the
original, and lets the real game own the balls: Drain feeds a `cvpmBallStack`
on the trough switches, each scoop is a saucer stack whose coil the game
fires, the auto plunger fires on the game's coil, posts and drop resets
follow theirs (`extra_vbs` in the map), and the tribute's own ball creation
and auto-launch lines are commented out (`neuter`). Three lessons:

* **The flippers are the machine's coils.** JP's table flips from the key
  only while HIS game is in play, which it never is: the bridge sets
  `SolCallback(sLLFlipper / sLRFlipper)` to the table's own `SolLFlipper` /
  `SolRFlipper` (their tricks and sounds stay) and the flipper keys stop
  reaching the shadow game. Stern's right button closes the upper flipper's
  switch too, so the key goes to both.
* **PinUP Player is optional** (`pup_stub`): Rush dies at
  `CreateObject("PinUpPlayer.PinDisplay")` on a machine without it, so the
  patcher scans every `PuPlayer.` call, writes a `PadNoPuP` class with those
  methods and argument counts, and wraps the CreateObject so the class
  stands in.
* **DOF stays on B2S.Server** (PAD-841): a tribute's `LoadEM` puts
  B2S.Server in `Controller`, and controller.vbs's `DOF` sub sends through
  `Controller.B2SSetData`. The bridge's Table1_Init keeps that object as
  `PadB2S` before `Controller` becomes PAD.Controller; every
  `Controller.B2S...` in the script, and in controller.vbs as it loads
  (`PadB2SText`), goes to it, and Table1_Exit stops it.
* **Use the RIG's switch table.** The first Rush map came from an older
  reading of the title that numbered every switch one higher: the table
  pressed Tournament Start for Start and filled the jam opto, and the game
  sat in attract. `dump/tables/<title>/switch_list.txt` from the run the
  table will attach to is the numbering that counts.

**Lamps** (`lamps` in the map, the Godzilla map's format: table light ->
the insert's LEDs, an RGB insert being lit when any of its three is): the
rig's `led_io.txt` names every LED of both titles even where it has no
positions, so each table light was matched by what its script does with it
(JP's city lights follow his `ModeName` order, drhotwing's planet and album
lights are the SHOOT ME and RECORD arrows of the lane whose hit sub checks
them) and the rest by place; the ones marked GUESS want a look at the
machine. The generated script keeps a dictionary from lamp number to the
lights, fills it from `ChangedLamps` every tick through core.vbs's
`LampCallback` (with `UseLamps = 0`, so core's own 260-entry `Lights()` is
never touched), and the tribute's own light shows are quieted
(`quiet_subs`: its attract sequences, GI and insert effects, Rush's GI
timer, every `LightSeq` stopped at init) with its hit subs no longer called
(`orig_hits: false`; `orig_keep` names the slingshots, whose originals
animate the rubbers). `vpxkeys.py lamps <file>` makes the table write every
mapped light's state, to compare with the machine's `padled` plane.

## A table from nothing: `vpxgen.py <title> <rig tables dir> <out dir>`

A title with no tribute still says where everything is. The rig's
`dump/tables/<title>/` holds `switch_xy.txt` (every playfield switch's
position, joined to the running game's ids), `device_xy.txt` (the coils),
`led_io.txt` (every LED, RGB triples and all) and `playfield.png`, the game's
own service-menu drawing of the playfield. The generator puts a flat table
under that drawing: a Trigger at every rollover and opto, a Bumper at every
pop, a standup or drop HitTarget at every target, a Spinner, a Kicker
saucer at every VUK / eject / lock whose coil the game fires, slingshot
walls, a Light at every LED with a position (an RGB insert is one light),
flippers at the flipper coils, plunger and ball release in the shooter
lane, a drain, outer walls and lane guides, and the shadow bridge over a
base script of its own. No ramps, plastics or sounds: the title's geometry
made playable. The base file is Visual Pinball's own "Nudge Test and
Calibration" table (`PAD_VPX_BASE` names another), whose items and
collections are dropped and whose GameData is resized to the drawing. The
map it writes goes beside the table and to `~/.pad-vpx/maps/<title>.shadow.json`,
where the controller looks first.

**Ramps, orbits and guides: `vpxgen_geo/<title>.json`.** The drawing is a
full line drawing of the playfield, so a title's geometry is TRACED from it
into a geometry file (drawing coordinates, heights in Visual Pinball
units): the `outline` (with the playfield's arch), `walls` (an open path is
a guide `thick` units wide; a `closed` polygon with a `slingshot` edge and
its `switch` is a sling), `ramps` (`flat` or `wire`, height linear from
`h0` to `h1`, so a ramp that climbs and comes back is two or three ramps
end to end), `switch_surface` (a switch that rides a ramp), `drain`,
`flippers` (an upper flipper's pivot and angles) and `saucer_dir`. A title
without one gets an arched outline and the rest as before. Bond's
(`james_bond_le.json`): the arch, both orbit lanes, inlane guides, slings,
the apron funnel, and the right ramp (up from its enter opto, round the top
past its exit opto, back down to the right inlane). Five things the live
tests taught: Visual Pinball's example ramp is decoration (Collidable off,
set on here); a flat ramp into a wireform threw the ball back at the join,
so returns are flat ramps; a sling polygon wound clockwise on screen kicks
the ball INTO itself, so `sling_winding` reverses it; the upper flipper
points down along the left orbit and narrowed the lane below a ball's
width where it stood at its coil; and the bridge's saucer and drain subs
call `PlaySoundAt`, which every tribute defines and the base script now
does. `vpxkeys.py shoot <x> <y> <angle> <speed>` fires a test ball from
any spot (table units) and the table traces its path to
`%TEMP%\padshoot.log`, which is how each shot was proven. What the first
loads taught: the table's
NAME stays `Table1` (the script's events are named after it), a Timer
named `PulseTimer` must exist (core.vbs runs `vpmTimer` on it, and without
it no `PulseSw` reaches the game), and a coil's group in `device_xy.txt` is
a place in the title's node directory, translated through `group_node.txt`.

## Mapping another table

`vpxfile.py items <table.vpx>` lists every object with its position; the
rig's `dump/tables/<title>/switch_list.txt` (and `switch_xy.txt`, `led_io.txt`
where the build ships positions) give the machine's. Fit the two (the
Godzilla map's header has the transform), match by position or by the
table's own comments, decide the rest by hand. A ROM mash-up (Godzilla on
Sega's ROM) gets a `<title>.vpxmap.json` and a patcher like
`patch_godzilla.py` for the script's conventions; a scripted tribute gets a
`<title>.shadow.json` and `vpxshadow.py` as it is.
