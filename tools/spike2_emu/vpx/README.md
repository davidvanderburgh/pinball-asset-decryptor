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
| `test_controller.vbs` | `cscript //nologo test_controller.vbs [run]` - the controller from VPX's own script engine, with no VPX installed; `run` presses Start and a flipper through a live rig and expects the coils back. |

## Numbering

A Spike 2 machine has no Whitestar matrix, so a table script talks in one
convention (PADSPIKE2.vbs has the constants):

    switch   1000 + <Spike 2 switch id>          switch_list.txt `id`
    solenoid 1000 + <node> * 16 + <coil index>   device_xy.txt coil (group->node)
    lamp     1000 + <node> * 100 + <LED index>   led_io.txt

Numbers below 1000 go through the title's map (`switch_rewrite`,
`solenoids`, `lamps`), so a table can run on its original numbering while
its map is being built.

## Running a table

1. Start the game in the rig (the app's Emulate tab, or `watch.sh`); the
   controller finds the run on the rig board (`~/.pad-rig/slot-N.run`) by the
   title the table names, or through `PAD_WSL_DISTRO` / `PAD_ROOT_WSL` /
   `PAD_SLOT` when VPX is started from a shell that has them.
2. `python padcontroller.py --register` (once).
3. Put `PADSPIKE2.vbs` beside the patched table and open it in VPX.

While a table is attached, `dump/ballfeed.off` tells the rig's `ballfeed.py`
to leave the trough alone: the table's own `cvpmBallStack` owns the balls.

## What the machine does that a ROM would not

* **Flippers, slingshots and pop bumpers are fired by the BOARD.** The game
  installs a rule per coil once (cmd 41: power, and the input whose closing
  fires it) and sends nothing per flip. `padled` version 7 publishes the rule
  (`hwshim.c coil_rule_note`, `coilmap.rule`), the controller reports such a
  coil ON while its switch is made, and synthesises solenoid 1999 "flippers
  armed" for core.vbs's `GameOnSolenoid` so VPX flips from the key
  (`UseSolenoids=2`).
* **Motors the table has no object for** (`switch_fakes`): the controller
  answers their end stops itself, the way hwshim does for node-board motors.
* **The LCD and the sound are the rig's.** Nothing to bridge; put the game
  window on the backglass monitor.

## Mapping another table (Foo Fighters, Rush, ...)

`vpxfile.py items <table.vpx>` lists every object with its position; the
rig's `dump/tables/<title>/switch_xy.txt` and `led_io.txt` give the machine's.
Fit the two (the Godzilla map's header has the transform), match by position,
decide the rest by hand, write `<title>.vpxmap.json`, and a patcher like
`patch_godzilla.py` for the script's own conventions. A scripted tribute
(no ROM) has its rules in the script: those go, the hit subs stay and get
their Spike 2 numbers.
