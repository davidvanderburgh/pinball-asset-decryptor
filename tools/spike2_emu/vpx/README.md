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
| `rush_le.shadow.json`, `foo_fighters_le.shadow.json` | the maps for drhotwing's "Rush LE Tribute" 2.0.2 and JP's "Foo Fighters" beta. |
| `vpxkeys.py` | presses keys in a running patched table through its `PadTestTimer` (a test does not depend on VPX having the keyboard). |
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

## Running a table

1. Start the game in the rig (the app's Emulate tab, or `watch.sh`); the
   controller finds the run on the rig board (`~/.pad-rig/slot-N.run`) by the
   title the table names, or through `PAD_WSL_DISTRO` / `PAD_ROOT_WSL` /
   `PAD_SLOT` when VPX is started from a shell that has them.
2. `python padcontroller.py --register` (once).
3. Put `PADSPIKE2.vbs` beside the patched table and open it in VPX
   (`VPinballX64.exe -Play "<table>.vpx"`).

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
* **Use the RIG's switch table.** The first Rush map came from an older
  reading of the title that numbered every switch one higher: the table
  pressed Tournament Start for Start and filled the jam opto, and the game
  sat in attract. `dump/tables/<title>/switch_list.txt` from the run the
  table will attach to is the numbering that counts.

Lamps on both tributes stay the tables' own until the titles' LED identities
are known (these builds carry no lamp positions or names in their device
tables).

## Mapping another table

`vpxfile.py items <table.vpx>` lists every object with its position; the
rig's `dump/tables/<title>/switch_list.txt` (and `switch_xy.txt`, `led_io.txt`
where the build ships positions) give the machine's. Fit the two (the
Godzilla map's header has the transform), match by position or by the
table's own comments, decide the rest by hand. A ROM mash-up (Godzilla on
Sega's ROM) gets a `<title>.vpxmap.json` and a patcher like
`patch_godzilla.py` for the script's conventions; a scripted tribute gets a
`<title>.shadow.json` and `vpxshadow.py` as it is.
