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
| `patch_ghostbusters_le.py`, `ghostbusters_le_replica.vpxmap.json` | ninuzzu/tom tower/djrobx's original-layout Ghostbusters LE 1.2 on the Spike 1 game, separate from JP's Slimer conversion. |
| `patch_godzilla.py` | applies `godzilla_le.vpxmap.json` to marty02's "Godzilla Limited Edition" v2.6: rewires the script, adds 36 lights and the Mechagodzilla magnet, re-signs. |
| `patch_beatles.py`, `beatles.vpxmap.json` | "The Beatles" (Original 2018) v007 (VPForums), Stern's Beatles playfield on Stern's 1980 Seawitch ROM (`seawitfp`) with rules of its own on top (PAD-926): the switches, coils and inserts go to the machine's, the upper flippers to their own coils, the record to its magnet and motor; the tribute's own modes, ball save, lock and PinUP Player are emptied. |
| `vpxshadow.py` | the patcher for a SCRIPTED tribute (no ROM): keeps its script as a shadow game, generates the bridge from `<title>.shadow.json`, neuters its own balls, makes PinUP Player optional, re-signs. |
| `rush_le.shadow.json`, `foo_fighters_pro.shadow.json`, `foo_fighters_le.shadow.json` | the maps for drhotwing's "Rush LE Tribute" 2.0.2 and JP's "Foo Fighters" beta. JP's table is a Pro's playfield (no upper playfield, no Overlord magnet), so Patch takes the Pro map, or the LE one when only an LE card is there (`padvpx patch --title` picks). |
| `jurassic_park_pro.shadow.json`, `jurassic_park_le.shadow.json` | the maps for JPSalas & marty's "Jurassic Park Pro Le" 4.02 (VPUniverse), on Stern's own Jurassic Park playfield (PAD-887; it replaced marty's "Jurassic Park Limited Edition", PAD-860). Patch takes the Pro; the LE map adds the raptor pit lock, the left ramp's mouth and the motor bank's target. |
| `james_bond_pro.shadow.json`, `james_bond_le.shadow.json` | the maps for marty & jpsalas's "BOND for Visual Pinball X" 4.3. The table has no rocket VUK or physical rocket lock (the Pro's locks are virtual) and no jet pack magnet, so Patch takes the Pro map (PAD-900), or the LE one when only an LE card is there. |
| `john_wick_pro.shadow.json`, `john_wick_le.shadow.json` | the maps for JPSalas & marty's "John Wick" 3.0 (the `John_Wick_Legend` pack), on Stern's John Wick art (PAD-905). Its car does not move and its lock is scripted, so Patch takes the Pro map; the LE one adds the arch's lock (LOCK 1-3 behind the post, the center ramp's diverter) and the pops' drop target. |
| `munsters_pro.shadow.json` | the map for Allknowing2012's "Munsters (Original 2020)" 1.05 (VPUniverse), on the same framework as his Aerosmith (PAD-1095). The table has no lower playfield and no moving Herman, so it is the Pro: the Dragula car (a Plunger over sw29) is the DRAGULA KICKER, the DropStop wall the UP POST, SpotWall Spot's trap door, the Herman magnet the MAGNET. |
| `vpxkeys.py` | presses keys in a running patched table through its `PadTestTimer` (a test does not depend on VPX having the keyboard); `lamps <file>` dumps every mapped light's state. |
| `padvpx.py` | the kit's command: patch a table (recognised by its map's `detect` words), register the controller, record cards, run and stop by hand, status. |
| `vpxsetup.py` | the app's Visual Pinball tab's half here: what is set up (Visual Pinball, the controller, the cards, each known table and whether it is patched), the card folder, the window layout, the Visual Pinball download, Play; one JSON line back. |
| `padlaunch.py` | starts a run for a title when Visual Pinball opens its table and none is up, and stops what it started. |
| `padloading.py` | the window a run the controller started shows until the game is up (PAD-940): where the game's screen goes, then over it, a bar paced by the title's last start (`start_s` in the kit) and the step read from the run's log. Never takes the focus (Visual Pinball pauses). |
| `vpxpicture.py` | a picture of each table for the app's Visual Pinball tab (PAD-942): `vpxpicture.py <out_dir> <table.vpx>...` reads the playfield picture out of the table itself (GameData's IMAG image; when that is not a picture, an image named like a playfield, then the author's TableInfo screenshot, then the backglass image, so a table with a baked playfield still shows the game's art) and writes it as a JPEG, one `picture {json}` line per table and a JSON object last. The app ships no picture of any table: the tab reads them from the person's own (PAD) copies into its cache. |
| `vpxauthor.py` | for whoever builds or finishes a table (PAD-941): `padvpx checklist <title> [--table x.vpx]` writes a Markdown checklist of every switch, coil and insert the game has (its number, its kind, its place on the game's drawing, what a table does for it) from the title's device tables; against a table, every part the kit's map leaves out (switches with no object, coils nothing fires, inserts no light shows, GUESS marks, map ids the run numbers otherwise), or a starter `<title>.starter.shadow.json` when the kit has no map for it. The app's Visual Pinball tab shows it as a sheet ("For table authors", and each table row's Coverage cell) with CSV and Markdown export; `data` is the JSON the sheet reads, `coverage` the per-title percentages. |
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

For a ROM table (Spike 1 or Spike 2) which reads a mono channel as a mechanical position
or raw brightness, `raw_lamp_rewrite` maps its legacy lamp number to
`[node, index]`, for example `"281": [15, 63]`. `Lamp(281)` and
`ChangedLamps` then retain the channel's 0..255 value, including zero,
instead of an on/off value or a packed RGB insert colour. The number
must be below 1000 (1000 and up already name every LED directly). Normal
lamp groups and their colour handling are unchanged.

A Spike 1 map can export an encoder count to an otherwise unused mono state
channel with `encoder_lamps`, for example `"8,0": [15, 63]` for node 8's
motor 0. The launcher forwards only that map's wiring as `S1_ENCODER_LAMPS`
(`node,motor:node,LED;...`). The responder publishes the current count there
when the game reads the motor status; a `raw_lamp_rewrite` alias can feed the
table's existing mechanism animation. Choose an unused channel: this is an
adapter value, not a physical lamp or an input injected into the game. The
mono value clamps to 0..255, while the motor's protocol position remains a
signed 16-bit count. With no wiring configured, no output channel is changed.

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

**The app's Visual Pinball tab** (PAD-802; a preview feature until PAD-1136,
in every copy of the app on Windows since) is everything above with buttons, for somebody
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

**What a card costs the disk (PAD-964).** A Spike 2 game's first start
copies its card image into the emulator's card cache - only what the card
uses, not the blank half of the image (`cardcopy.py`; 6.6 GB of Batman's
7.9 GB image) - and every later start reads the copy: 36 s to attract
against 148 s read off the Windows drive through 9p. Before a run the
launch asks `cardmount.sh --cache-check` (a dry run of the copier's own
room rule: nothing copied, nothing evicted) and writes the answer into the
run's log as `[card-check] <state>: <words>`, which the loading window
shows: the card is in the cache, a copy of so many GB is made (so much
free there, older cards making room), or there is no room and the game
reads the image where it lies, a slow start. `padvpx cache` says it for
every card in the folder; `padvpx cache off` (the kit's `card_cache`, the
box on the app's Visual Pinball tab) makes every run read its image where
it lies instead (`PAD_CARD_CACHE=0`), for a PC with no room to give; `on`
puts it back. The app's Visual Pinball tab says the same under each row's
card and on its Card images row, with the cache's room and a Cache… to the
Emulate tab's cache window.

**A launcher that exits during startup.** A board record alone does not
prove that the game came up. The bridge cleans the failed run it started
and reports the failure. The kit can opt specific titles into one retry,
for example `"startup_retry_titles": ["batman"]`; the default is no retry.
The old run is stopped before the new one starts, and closing the table
during either cleanup or restart stops recovery. This applies only before
the table attaches to a live game; it does not restart a game being played.

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
and more later (a title's first boot on a slot caches and mounts its card
first), and meanwhile `padloading.py` stands where the game's screen goes
with a progress bar and the step it is on, so the wait does not look like a
hang (PAD-940); and `Controller.Stop` (Visual Pinball closing the table) stops what it
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
leaves. The coin door's service buttons are VPM's 7 8 9 0, in the coin
door's order: Back, Minus, Plus, Select (PAD-882). A title's first boot opens
its Guided Setup, which is where a player sets Free Play, and that is walked
with these. The table sends the controller's SERVICE numbers (9000 + the
button's bit on node 0), and the controller finds each button's id in the
title's own switch table: the ids differ by title, the wire does not. A table
patched before them gets them the first time the app's Play opens it. The launch button is Enter on Godzilla (marty02 wired it to the
plunger key) and the lockbar key, Left Alt by VPX's default, on Rush and Foo
Fighters (their scripts wired the Action button to `LockBarKey`). A machine
with a manual plunger keeps the plunger key on the table's own plunger and its
Action button on the lockbar key (PAD-1128: Jaws, John Wick and Jurassic Park
had the plunger key pressing the Action button, so their plunger never pulled;
Jaws' game waits with the ball in the lane until one or the other launches it).
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

## Checking a patched table without Visual Pinball (PAD-861)

Never start `VPinballX64.exe` from a test or a session to look at a table
(`-ExtractVBS`, `-Pov`, `-play`, even `-Minimized`): it runs on David's own
desktop, its "Command Line Error" boxes land in front of whatever he is
playing, and every load rewrites his `%APPDATA%\VPinballX\VPinballX.ini`
recent-tables list. A path built in the Bash tool as `"...\\load\\$t.vpx"`
reaches bash as `load\$t`, so `$t` stays literal and VPX says
`File 'C:\tmp\PAD-858\load$t.vpx' was not found`: David took that box for his
GotG table failing to start. Read the table here instead:

    python vpxfile.py verify "<table.vpx>"         # the MAC VPX checks on load
    python vpxfile.py script "<table.vpx>" out.vbs  # the script, as -ExtractVBS gives it
    python vpxfile.py items  "<table.vpx>"         # every game item closes

A load in VPX itself is David's to run, when he asks for one.

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
  A `"kind": "latch"` entry is a latched post with an `up` and a `down` coil
  (Foo Fighters' Overlord fork, PAD-968): the controller follows it, answers
  its `switch` (closed = up) and hands the table its state as the synthetic
  `solenoid`, whose `callback` the patcher wires. The game catches a ball by
  arming both coils on an opto and lets it go with the short cmd 40 (fire by
  its rule), which hwshim's `coil_publish` counts like any other fire.
* **The LCD and the sound are the rig's.** Nothing to bridge; put the game
  window on the backglass monitor. The table keeps only its PLAYFIELD sounds
  (ball rolling, flippers, rubbers, bumpers, coils): every patcher runs
  `vpxsounds.py`, which turns the table's own songs, call-outs and effects
  into 10 ms of silence under their own names and sends `PlayMusic` to an
  empty sub (PAD-858). Play quiets a table patched before that, once, in
  place. `python vpxsounds.py <table.vpx>` lists what is kept and muted.

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
  stands in. `"pup_stub": "always"` uses the silent class even when PinUP
  is installed. Batman and Iron Maiden use this mode to keep their tribute
  music and callouts from playing over the machine's audio; every creation,
  including a later LoadCoreFiles/PuPInit, uses the same silent shape.
* **DOF stays on B2S.Server** (PAD-841): a tribute's `LoadEM` puts
  B2S.Server in `Controller`, and controller.vbs's `DOF` sub sends through
  `Controller.B2SSetData`. The bridge's Table1_Init keeps that object as
  `PadB2S` before `Controller` becomes PAD.Controller; every
  `Controller.B2S...` in the script, and in controller.vbs as it loads
  (`PadB2SText`), goes to it, and Table1_Exit stops it.
* **B2S.Server starts whatever DMD the table is set to** (PAD-1094).
  Aerosmith's Table1_Init calls `LoadEM` only under `If bUseFlexDMD`, and
  ships set to PinUP (DMDMode 2), which the patch takes out: B2S.Server never
  started, so no backglass, and controller.vbs's `DOF` did nothing (B2SOn
  stays Empty until `LoadController`). A table whose every `LoadEM` is not
  unconditional (`early_b2s`) has them made `PadLoadEM` (LoadEM once, if
  B2SOn is still Empty), and the bridge's Table1_Init calls it before the
  table's own init, so its `If B2SOn` backglass set-up runs too. A table
  that calls `LoadEM` outright is patched as before. `flipper_dof`
  (`{"sLLFlipper": 101, ...}`) sends a flipper's DOF event from the machine's
  flipper coil, for a table whose script names its flipper events (in
  `SoundFXDOF(..., DOFFlippers)`) but never fires them on a flip.
  `flipper_flag` (`{"flag": "bGameInPlay"}`, PAD-1096) is for a table whose
  flipper subs DO fire them, but only behind its own game-running flag
  (Batman 66: `if bGameInPlay then PlaySoundAt SoundFXDOF(..., 101, ...)`),
  which only the table's own game sets: the machine's flipper coil holds the
  flag True just for the table's flip, then puts it back, so its flipper
  sounds and DOF play as the author wrote them.
* **A ROM table's backglass runs beside PAD.Controller** (PAD-852). There
  controller.vbs's `LoadVPM` made `Controller` a B2S.Server, which runs
  VPinMAME inside itself and shows the .directb2s; PADSPIKE2.vbs makes it
  PAD.Controller, so Metallica, Godzilla and TMNT opened with no backglass.
  `LoadVPM` now starts B2S.Server as `B2SController` (controller.vbs's own
  two-controller way, ForceDisableB2S and `B2SOff` respected), named by
  `PadB2SName`, the ROM name the patcher keeps; the table's exit sub stops
  it (`PadStopB2S`). Play brings an older PADSPIKE2.vbs beside the tables
  up to the kit's, so a table patched before a fix has it.
* **The backglass's grab of the focus is undone** (PAD-893). B2S.Server's
  window takes the foreground as it opens and hands it back only to a
  VISIBLE "Visual Pinball Player" window (formBackglass.vb
  `SetFocusToVPPlayer`, as it shows and 2 s later). Started from `LoadVPM`,
  after DOF has opened the cabinet, it could open before the playfield did
  and keep the focus, so Metallica sat paused. PAD.Controller's poll hands
  the foreground back from each "B2S Backglass" / "B2S DMD" window once,
  for any run, as it does from the started run's LCD window.
* **The table's own DOF calls come along** (PAD-847). With `orig_hits:
  false` a bumper's Hit sub never runs, and the kickers, trough and plunger
  fire on the machine's coils through cvpmBallStack, so the `DOF 107,
  DOFPulse` and `SoundFXDOF(..., 113, ...)` there were lost. `dof_calls`
  reads them from the script as written: what a stood-in event sub fires at
  its own level (not in a branch of the shadow game's rules), and per coil
  what the table fires beside `<release|saucer|plunger>.Kick/AutoFire` in
  the same branch. They become `PadDOF` calls (SoundFXDOF's toy check kept)
  in the bridge's subs and `PadSol<n>` coil wrappers. `b2s_name` renames
  cGameName, the name B2S.Server gives DOF to find the table's config
  (Rush: `rush_le`, not the script's `rushle`).
* **A ROM table's DOF is PAD.Controller's** (PAD-879). Under VPinMAME the
  DOF of Metallica, Godzilla or TMNT is B2S.Server's DOF plugin hearing the
  ROM: every solenoid, lamp and switch (S/L/W) it reports, in the numbers
  the table's DOF config (by ROM name) is keyed on. Beside PAD.Controller a
  released B2S.Server hears only the script's `B2SSetData` (E), and
  PADSPIKE2.vbs's `DOF` was empty. `LoadVPM` now asks PAD.Controller to
  host DOF (`PadDOFInit`, through `DirectOutput.ComObject` under B2S's host
  name, so the same GlobalConfig_B2SServer.xml and cabinet config) BEFORE
  it starts B2S.Server, so DOF opens the cabinet's devices first. The poll
  sends the machine's coils and lights in the ROM's numbers, the map read
  backwards (`dof_sols`: a solenoid's key, or its `dof` where the key is a
  core.vbs flipper Const - Metallica's flippers are SAM 15/16; `l<n>` =
  lamp n, `f<n>` = flasher solenoid n at its LED level; W = every table
  switch number the rewrite sends to a Spike 2 id), and the script's `DOF`,
  `DOFALT` and `SoundFXDOF` go through it (`PadDOF`), with Visual Pinball's
  sound-or-toy settings as controller.vbs reads them. No DOF installed: the
  script's DOF goes to B2S.Server as before and every sound plays.
* **DOF without its COM registration** (PAD-909). DOF's installer registers
  `DirectOutput.ComObject` per user, and on one cabinet the name vanished
  between two runs (`no DirectOutput.ComObject (Invalid class string)` in
  padcontroller.log) while B2S.Server's plugin, which loads DOF's DLLs by
  path, still started DOF - with nothing to tell it. The controller now tries
  the ProgID, then DOF's class id, then DOF's own `DirectOutputComObject.dll`
  (the folder DOF's installer saved in HKCU\SOFTWARE\DirectOutput, B2S's
  Plugins\DirectOutput, C:\DirectOutput; x64\, x86\ or an old flat folder)
  in a hidden Windows PowerShell that takes the events on its stdin. The
  log line says which: `DOF for mtl_180h: up (DOF's own ...; DOF's COM
  registration is missing)`.
* **A map whose keys are not the ROM's numbers says so per coil** (PAD-896).
  TMNT's solenoid keys are small numbers of PAD's own (11 = LEFT POP
  BUMPER), but tmnt_104's DOF config is Data East's (11 is its GI relay,
  14 a flasher), so DOF fired the wrong toys. Each TMNT coil carries its
  Data East number as `dof` (trough 2, auto plunger 4, the lock's kick 7,
  pops 17-19, slings 20-21, the Pro's pizza motor 22), and `null` where Data
  East had none.
* **TMNT's lock has two sections** (PAD-896). The Pro's Ninja Pizza Parlor
  (the LE's van) holds a ball shot in on UPPER LOCK 1-3; the UPPER LOCK coil
  drops it to LOWER LOCK, the LOWER LOCK coil lets it out. The table put
  the ball straight onto LOWER LOCK 1 and the game let it out again: no lock,
  no Ninja Pizza Multiball. On the emulator, balls on the upper section read
  BALL ONE LOCKED and three started the multiball. The Pro's LAIR lane, where
  a spelled LAIR lights Training, runs to the same lock's LOWER place: a ball
  on LOWER LOCK 1 that skipped the upper section started TRAINING LEVEL 2,
  held ~10 s before LOWER LOCK let it out. So a ball going UP the table's
  t25 lane (behind the LAIR bank, above the left outlane) goes there
  (`lair_lane`), and comes back out of the parlor.
* **UPPER LOCK is a post, held down to empty the lock** (PAD-1116). The game
  calls a lock that does not empty a DEVICE MALFUNCTION (UPPER LOCK, LOWER
  LOCK) once its kick's tries run out (`kickproc` 0x298380 in the 1.54
  symbol build, 15 tries). At Ninja Pizza Multiball it holds UPPER LOCK
  down ~5 s and wants all three balls out; the table dropped one per pulse,
  so every multiball start used the hold's full timeout and two retries. Now
  the balls roll on to LOWER LOCK (240 ms) while the post is down, LOWER
  LOCK letting each go: the game lets the post up after 3 s, no retries.
  A ball shot in crosses the free switches above its place, as on the
  machine, since the game calls a lock switch no ball crosses for many balls
  broken and stops lighting locks. The bridge reports a coil pulse that came
  and went between two ChangedSolenoids reads ON, then OFF (the lower kick is
  ~20 ms; a slow 4K frame missed it).
* **TMNT's slings reach DOF as Data East's switches 21/22** (PAD-1116).
  Data East's tables send their slings as switch 21 (left) and 22 (right),
  and a DOF config may fire the sling toys on those rather than on S20/S21;
  this table's slings sent no Data East number, so DOF heard the pops both
  ways (S17-19 and W46-48) but the slings only as S20/S21. `switch_rewrite` maps 21/22 to the Stern slings.
* **A lock lane is a stack, its post is held** (PAD-901). Deadpool's Katana
  Handle lock is one kicker in JP's table and LOCK 1-4 on the machine. As a
  saucer it held one ball on LOCK 1: the next sat unseen behind it, the game
  counted one lock and never started the multiball, and when the post dropped
  a hidden ball rolled onto LOCK 1 under it (the operator alert's "ball may be
  sticking"). A saucer's `stack` names the switches behind `switch`, and the
  kicker feeds a ball stack on all of them; `held_ms` is for a post the game
  holds down (12 s at Deadpool's multiball): a ball goes out each `held_ms`
  while it is down, where a kicker coil lets one go per pulse.
* **A kicker that teleports keeps its exit** (PAD-905). JPSalas's John Wick
  takes the VUK's ball in at Krampcoude and pops it out of Krampcoude1 on the
  return wire, and the arch lock's in at Karche (the center ramp's top) and
  shows it in KArche1-3. A saucer's `kick_from` names that exit kicker: the
  entry kicker takes the ball in (`AddBall`), and the machine's coil kicks it
  out of the exit, where the table's own timer did. With a `stack`, a full lane
  sends the ball out of the exit too.
* **A saucer's `lift`** (PAD-1094): the ball's Z just before the coil
  kicks it. Aerosmith's elevator kick, from where the ball rests, bounced
  off the elevator's roof and fell back in, every pulse the game sent; the
  table's own eject (ElevatorKickOut) raises the ball to Z 35 first, and
  the bridge's `PadLift<kicker>_Sol` does the same on the ball the kicker
  holds.
* **A switch the table has no object for** (PAD-922). John Wick's table
  walls its car in with an invisible ramp, so a car shot met no switch.
  `retrofit_triggers` clones a trigger (`clone`), gives it its own drag
  points (`shape`, table units), switches it on, draws it as nothing and puts
  it on the playfield whatever surface the clone sat on; the switches map
  names it like any table object (`PadCarHit`: the band in front of the car's
  nose, CAR HIT OPTO).
* **A table object that needs another setting** (PAD-982). `item_fields`
  gives the table's own objects new field values by their BIFF tag
  (`{"LightningTarget": {"SLGF": 300.0}}`: Foo Fighters' kick target kicks
  harder; a JSON float is written as a float, an int as an int). The object's
  GameItem stream is replaced, which the MAC does not cover.
* **A sound played at a wall stops the table** (PAD-992). JP's
  `PlaySoundAt` pans by the object's `.x`, which a wall, ramp or rubber has
  not: Foo Fighters' first KICK TARGET coil stopped Visual Pinball with
  "Object doesn't support this property or method: 'ball.x'". Play a map's
  sound at an object with a position (the kick target's sound is at
  Target004, as JP's own sub has it); the patch warns of one that is not.
* **A magnet the table has no object for** (PAD-925). drhotwing's Rush has
  no time machine magnet: the game holds MAGNET ~4.1 s after each LIFT RAMP
  OPTO (emulator), while the tribute's ball ran up Ramp011 and straight back
  down. A retrofit trigger can sit on a ramp (`surface`; on the playfield a
  ball 80 units up the ramp never meets it) with a `radius`, the reach
  core.vbs's cvpmMagnet takes from it. `PadTMMagnet` is one on Ramp011's top,
  made a cvpmMagnet in `extra_vbs` that the coil turns on and off. Its own Hit
  sub takes most of a ball's speed as it comes into a live magnet's field:
  cvpmMagnet grabs only inside 20 units, at its 10 ms update, and a fast ball
  crossed that window between two updates.
* **A scoop the ball passes an opto into** (PAD-910). Rush's side scoop is
  SIDE SCOOP OPTO on the way in and LOWER SIDE SCOOP where the ball rests;
  the game fires SIDE SCOOP only from the lower one. The saucer held the
  opto: the game held its trough lock and waited, the ball sat until a ball
  search, and the opto read stuck. A saucer's `enter` is the opto: the
  kicker pulses it as the ball comes in and holds `switch`.
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
mapped light's state, to compare with the machine's `padled` plane. A module
variable only a quieted sub ever `Set`, which running code still walks with
`For Each`, starts as an empty list (PAD-1102): Munsters' StartRainbow was all
that gave `RainbowLights` its lights, and its RainbowTimer is saved enabled, so
the first tick stopped Visual Pinball on "Object not a collection".

The plunger lane's own `_Hit` / `_UnHit` obey the same rule (PAD-1099).
They are the tribute's rules - skill shots, ball savers, songs, its own
light effects (`lighteffect 6` on JP's tables), gates - and the lane
wrapper used to call them whatever `orig_hits` said, so they ran at every
launch over the machine's lights. Their unconditional DOF calls come along
as a switch's do; a map that needs the originals names the lane trigger in
`orig_keep`. A table patched with the old wrapper is asked to patch again
(every such map's `repatch`).

**A spinner where the machine has an opto** (PAD-887): a switch's
`"event": "pass"` takes the spinner's Spin as one pulse a pass, not one a
spin: every spin restarts a 600 ms quiet time (`PadPassSw`), so the ball
through Jurassic Park's right orbit or half pipe is one opto edge.

**A ramp the ball rolls back down** (PAD-907): `"up": true` on a `hit`
switch pulses it only while the ball moves up the table
(`ActiveBall.VelY < 0`), so a shot that falls back over the trigger is one
edge, the way the machine's magnet or lift would have kept it. Rush's time
machine (`tm2`) is LIFT RAMP OPTO this way.

**Balls the tribute keeps for itself** (PAD-974): `"helper_balls"` names
the script's variables for balls it makes for its own mechanics and never
shows. A switch sub one of them runs makes and breaks nothing on the
machine (`PadHelperBall()`; a sub the script calls itself, with no ball,
still does). Batman 66's bat disc posts (`postBall1`, `postBall2`) ride the
turntable; at the phone they sat on `trgBallLock3`, the table reported
TURNTABLE LOCK 3, and the game turned the turntable home and back out
again, over and over.

**A coil is one part** (PAD-1120): name a map's coils from the game's own
adjustments before guessing. Batman 66's CONTROL GATE (6) and DIVERTER
POWER (7) are DISABLE LEFT CONTROL GATE and DISABLE TURNTABLE DIVERTER;
the map had both opening the tribute's turntable lock door, so every combo
that opened the left control gate sent the orbit ball behind the turntable,
stuck behind the Bat Phone. 6 now swings `Gate002` at the top of the orbit;
7 opens the door, and only at a face where the lane behind the turntable
leads on (the TV's lock, the Batcave), never at the Phone or while turning.

Four more map fields (PAD-859), all in the generated script:

* `"rgb": true` on a lamp whose three LEDs are an insert's -R, -G, -B: the
  controller reports it lit as its colour (VBScript `RGB()`, brightest
  channel at 255; never 0 or 1) and the light takes it as `ColorFull`, so a
  mode's shot arrows show the mode's colour. ROM tables' maps never carry
  it: their own lamp code takes 0/1. LEDs listed in another channel order
  carry the order instead, `"rgb": "BGR"` (PAD-1097: Aerosmith names
  -BLU, -GRN, -RED; Rush "X R"), and the controller reads them back as R, G,
  B; the LEDs stay as they are, so the light keeps its number.
  `vpxlamps.py rgb` reads the channels from every LED the build names,
  placed or not, and writes `true` or the order.
* `retrofit_lights`: `{"lights": {name: {"leds", "clone", "at"}}}`, a new
  Light cloned from `clone` at `at` (table units) for an insert the table
  has no light for (Bond's rocket ring and right orbit arrow).
* `dark`: lights the machine has no LED for, held off, so a light the
  shadow game left on cannot stay on.
* `lamp_calls`: `{name: {"leds", "call", "arg", "show"}}` for an insert the
  table shows with something other than a Light (Batman's Catwoman
  billboards are fader bulbs, its pops are plastic images): `call` is a sub
  of `extra_vbs`, called `(arg, value)` when the LED changes; `show` names
  the objects, for `vpxlamps.py lit`.

The patcher also empties a tribute's own reads of `Controller.ChangedLamps`
(Batman 66's and Aerosmith's `LampTimer` kept one from their ROM days): with
`Controller` being PAD.Controller, each read took changes the bridge waits
for.

**Checking a map: `vpxlamps.py`.** `audit <map> <table.vpx> <led_io.txt>
[overlay.png]` fits the table's light positions to the title's LED places
over the lights the map puts on one insert, then lists the inserts no light
shows (and, for builds without positions, the named LEDs no light shows),
the lights neither wired nor dark (GI collections and lights the script
never names left out), the wired lights far from their insert, and the
lamps whose LED the build calls something else (a map numbered for another
build: Guardians LE once carried the Pro's numbers).
`suggest ... [--write]` mends what audit found by the fit (the nearest free
light, a free light beside a shown insert, otherwise a retrofit light;
refused when the fit is over 10 px), `rgb <map>
<led_io.txt> [--write]` marks the RGB inserts, and `lit <map> <table.vpx>
<led_io.txt> <padled> <out.png>` draws what the table shows for one sample
of a rig's `dump/padled` on the table's own art.

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

Two different VPX tables can use the same native game. Give each map a
distinct `title`, matching its filename and the patched script's cGameName,
and set `game` to the rig's native title. For example, a second Ghostbusters
map can be `ghostbusters_le_replica.vpxmap.json` with
`"title": "ghostbusters_le_replica", "game": "ghostbusters_le"`. Its
`detect`, `output`, `table` credits and wiring belong to that download. Both
maps then stay separate in the tab while card discovery, rig-board matching,
launch/stop and the author's machine checklist use the native game. An
explicit card recorded for the variant wins; otherwise its native game's
card entry or library filename is used. Maps without `game` behave as before.

## Other platforms (PAD-943)

**Original-layout Ghostbusters LE 1.2.** The replica by ninuzzu, tom tower
and djrobx uses map title `ghostbusters_le_replica`, native game
`ghostbusters_le`, and output `Ghostbusters LE 1.2 (PAD).vpx`. Supply your
own original author table: the kit ships its patcher and wiring, not that
table or its assets. `padvpx patch` detects `spagb_100`, its SPA loader and
Scoleri code. JP's Slimer map remains a separate option for JP's layout.

The conversion retains the author's playfield, physics, mechanisms and
mechanical samples. PAD replaces SPA, its CPU service keys use the shared
service numbers, and direct hardware lamp numbers cannot index the table's
fixed legacy arrays. Manual lamp aliases retain intensity; Slimer's existing
animation reads the map-selected encoder position through lamp 281. Ecto
Goggles video is not integrated: that internal playfield screen stays at
standby. The real game's DMD comes from the app or a separately configured
native viewer; the conversion disables the old SPA DMD.

A map's `platform` says which rig is behind the table; `spike2` when it says
nothing. The kit's survey of what exists for every platform PAD reads is
`catalog.json` (the app's Visual Pinball tab shows it as "Tables of other
machines": each table a link to its author's download, who made it, whether
it is the machine's own layout, and what plays behind it).

**Stern Spike 1** (`"platform": "spike1"`): PAD.Controller attaches to the
Spike 1 rig's run (tools/spike1_emu) through the two files the app's switch
window uses, `s1hw.state` (switches told, lamps, coils) and `s1sw.input`
(switches in), read over `\wsl.localhost` from the work dir the run posts
on the board (`spike1-0.run`, `root`). The rig's DMD-era responder now
writes the state block (nodebus.py `DmdFrames`: the lamp and coil frames as
the GOT LE 1.37 ELF's own senders build them; the early era's s1early.py did
already), and the ball keeper stands aside while `s1ball.off` is in the work
dir (the table owns the balls). Numbering: switches `1000 + node * 64 +
index` (the rig's s1switches.json), lamps `1000 + node * 100 + index`, coils
`1000 + node * 64 + index`; the flippers are held coils while their buttons
are, `game_on` is always armed (no rule plane on this rig), and Visual
Pinball's pause leaves the game running (the rig has no pause). A title's
coils and LEDs come out of its own ELF (`s1elf.py --coils`, `--leds`: the
node and position of each, named where the game names them); the matrix
inserts are mapped by watching the run. A run is started by the controller
like a Spike 2 one (`padlaunch.Spike1Launch`: start.sh with the title's
.iso, on the app's data disk, visible and with sound; `padvpx run got_le
--mute` by hand) - ONE rig, so a run of another title is refused, not
replaced. The game's DMD is drawn by the app's Spike 1 tab, so a player keeps
the app open beside Visual Pinball. On Windows, an optional external native
viewer can instead be set in the kit's `spike1_dmd_viewers`, for example:

```json
{"spike1_dmd_viewers": {"ghostbusters_le": "C:\\Pinball\\DmdViewer.exe"}}
```

The value is an executable path, or an argument list beginning with its
executable. The launcher appends the Windows path to `spike1-0.run` and the
game title as two arguments. The viewer reads that board record's distro/root
to find the active `spi0.cap`; renderer libraries and colour data are the
viewer's own configuration, supplied separately. No helper is started unless
configured. Its output joins the title's launch log, failure to start it does
not stop the game, and the launcher reaps only the viewer process it created
when the table exits. There is no process-name search or global viewer kill.

The author's checklist (`padvpx
checklist got_le`, the tab's "For table authors") reads a Spike 1 title
from its game program and switch map in the rig's cache (every Spike 1
game extracted on the PC is offered): the switches with their slot ids,
the coils the program drives, every LED channel named where the program
names a lamp; nothing is placed (no Spike 1 build ships positions). `got_le.shadow.json` is the first Spike 1
map: the cabinet and the coils (the ELF's), not yet VPW's table
(`listed: false`, no `detect`). Proven on the rig: `test_controller.vbs run
got_le 1075 1515 1578 1519 "1521,1522,1523,1524,1525,1526" 1080` - the
trough held through the bridge, three coins and Start put the game in
CHOOSE YOUR HOUSE and its TROUGH UP-KICKER came back as solenoid 1.

**Stern SAM** (and the WPC remakes): VPinMAME runs those games from the
person's own ROM set already, so nothing for this kit to do, and they are
not in the catalogue (David, 2026-11-02: no reinventing the wheel; Spike 1,
Spike 2 and the other modern machines are the point).

**The rest** (JJP, American, Spooky, Dutch, Barrels of Fun, Pinball
Brothers, Turner, Multimorphic, Chicago Gaming's own titles): no VPinMAME
core and no rig behind a table yet; `catalog.json` says what tables exist
(few are the machine's layout) and `platforms[].bridge` is `none`.
