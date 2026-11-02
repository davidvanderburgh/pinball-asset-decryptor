# Visual Pinball tables of the other platforms (PAD-943)

David, 2026-11-02: "Add other manufacturer VPX table support. Spike 1, SAM,
etc. Also find links to the VPX tables that we can download and integrate in
(just like what was done for Spike 2)."

The Spike 2 kit (`tools/spike2_emu/vpx`, docs/plans/vpx_bridge.md) puts the
real game behind a Visual Pinball table through PAD.Controller. This is the
record of what exists for every other platform PAD reads, what was built for
it, and what is still to do.

## What exists out there (surveyed 2026-11-02, `catalog.json`)

* **Stern Spike 1**: scripted tributes of the machine's own layout for Game
  of Thrones (VPW 1.2.1, FlexDMD), KISS (masonm 2.0), Whoa Nellie
  (HauntFreaks 2.1.4), Primus and Can Crusher (Drummer72, on Whoa Nellie's
  code); WWE is a reskin of Gottlieb's Tag Team ROM; Ghostbusters has JP's
  "Slimer" original only (the faithful LE table was withdrawn); nothing for
  the 2012 home game. VPinMAME has no Spike core, so each is the Spike 2
  case again: a shadow game to bridge to the real one.
* **Stern SAM**: every title in the library has a table that runs the REAL
  game through VPinMAME's SAM core (24 of them, ROM set names in the
  catalogue; 24 is `twenty4_150`, not `24_150`). Nothing to bridge: PAD's
  edited game goes into the ROM set.
* **Spider-Man Vault Edition** is a SAM game (`smanve_101`), not Spike 1.
* **JJP**: Wonka, Godfather and Wizard of Oz tributes (marty02, MachWon); a
  Data East GnR reskin; nothing for the rest - the community does not
  recreate machines still on sale (Hobbit, Dialed In, TS4, Elton John,
  Pirates, Harry Potter, Sonic all say so in their threads).
* **American, Spooky, Dutch, Barrels of Fun, Pinball Brothers**: themed
  originals and reskins, a few on the layout (TNA, AMH, Alice Cooper WIP,
  Hot Wheels WIP); Turner and Multimorphic: nothing at all.
* **Chicago Gaming** remakes run their WPC ROMs through VPinMAME; Pulp
  Fiction has a film tribute only.

VPUniverse and VPForums downloads take a free account; the kit links, the
person downloads (PAD ships no table, as before).

## What was built

**A platform layer in the kit.** A map's `platform` (default `spike2`) picks
the rig behind PAD.Controller. `s1bridge.py` is the Spike 1 half:

* The run is found on the board as `spike1-0.run`; `rigboard.sh` now posts
  the run's work dir as `root` (`RIGBOARD_ROOT`, set by spike1's start.sh),
  and a record without one falls back to the app's data disk.
* Lamps and coils OUT: `s1hw.state`, read over `\\wsl.localhost` like
  padled; switches IN: `s1sw.input`, the bitmap the app's switch window
  writes (no 9p race here: the responder reads the file each frame).
* Numbering: switches `1000 + node*64 + index`, lamps `1000 + node*100 +
  index`, coils `1000 + node*64 + index`. Flipper coils are held while
  their buttons are (no rule plane), `game_on` always armed, pause a no-op.
* `padlaunch.Spike1Launch` starts a run the way the app's tab does (start.sh,
  `wsl -u root`, S1_WORK on the data disk, S1_PIVOT=1); one rig, another
  title's run is refused. `padvpx run/stop <title>` follow the platform;
  `padvpx` finds a Spike 1 card in the kit's `libraries[spike1]` or the
  `spike1` folder beside the Spike 2 library.

**The Spike 1 rig publishes what the DMD era does.** `nodebus.py` answered
switches only; `s1hw.state` was written on the early era alone (PAD-235).
`DmdFrames` reads the lamp and coil frames into `s1early.HwStateWriter`
(now with `lamp_level`, `coil_on(seconds)`, `coil_off`). The shapes came
out of GOT LE 1.37's ELF, not guessed: `NODEBUS_SetLED(node, idx, level,
time)` @0xc1530 sends `[0x80|idx][time][level]` (idx > 63: `[0xc0][lo][hi]
[time][level]`), `NODEBUS_SetLEDMultiple` the same with a run of levels;
cmd 0x70 is the base-layer write Spike 2 has (`level70`); cmd 0x40 is
Spike 2's coil drive frame (coildecode.py), 0x41 the rule, 0x4d OFF. The
whole GOT capture replays: 576 lamps written, every coil of nodes 1 and
8-12. A hold with no end time is kept 2 s per frame (the game re-sends
while it holds), not for ever.

**The ball keeper stands aside** (`s1ball.off` in the work dir): the
table's trough owns the balls, as `ballfeed.off` does on Spike 2.

**A title's coils and LEDs from its ELF** (`s1elf.py --coils`, `--leds`):
the device chain the switch walk already used, read for the `cl` and `led`
device tables (layout in s1elf.py). GOT: 24 coils named and placed (TROUGH
UP-KICKER 9,2, AUTO LAUNCH 9,1, RIGHT FLIPPER POWER 8,7 ...; the left
flipper's driver is not on the node bus), 246 LEDs placed, one named
(TOURNAMENT START BUTTON): the inserts are matrix channels the lamp table
does not link to its LEDs, so they are mapped by watching a run.

**`got_le.shadow.json`**, the first Spike 1 map: the cabinet (from the
curated switch map) and the coils (from the ELF), `listed: false` and no
`detect` words: VPW's table is not fitted yet (its download is the user's;
none is on this PC).

**The catalogue in the app**: `catalog.json` rides `vpxsetup.py state`,
and the Visual Pinball tab shows it under the tables as "Tables of other
machines" (a block per platform, each table a link to its download, who
made it, layout or themed, what plays behind it).

## Proof

On the Spike 1 rig (PAD-Runtime, the app's data disk), GOT LE 1.37 started
by `padvpx run got_le --mute` with the worktree's rig (`PAD_VPX_RIG`): the
board record carried `root`, `s1hw.state` was live (29 lamps lit in
attract, 1947 lamp changes reached ChangedLamps in 2 s), the bridge
attached from a Python drive of `Bridge` (the COM shape is unchanged), the
keeper stood aside and came back, a held flipper button showed the flipper
coils (46, 48) on and off, and with the trough held through the bridge,
three coins and Start the game went to CHOOSE YOUR HOUSE (the DMD, decoded
from spi0.cap) and fired TROUGH UP-KICKER, reported as solenoid 1 on/off
nine times (the table has no ball to serve). `test_controller.vbs` took the
same arguments for the COM path (`run got_le 1075 1515 1578 1519 "1521,
...,1526" 1080`).

## Still to do (the next runs of PAD-943)

1. **SAM hand-off**: PAD's edited SAM game into the table's VPinMAME ROM set
   (replace the game's .bin in the zip in VPinMAME's roms folder, set the
   game's `ignore_rom_crc` so VPinMAME does not stop on the changed sum),
   proven by booting the written set under libpinmame (the app's PinMAME
   capture) - the same core VPinMAME runs. A button on the SAM Write side
   and `padvpx sam`.
2. **The Spike 1 author's checklist**: `vpxauthor.py checklist` for a Spike
   1 title from its ELF (`s1elf --coils/--leds` + the switch map) and the
   starter map from it, so VPW's GOT table (and KISS, Whoa Nellie, Primus,
   Can Crusher) can be fitted the day the download is on the PC.
3. **The Spike 1 inserts**: which matrix channel is which lamp (the lamp
   table's column/row to the node's channel), from the ELF or a run.
