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
  own code plays: nothing for PAD to bridge.
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

## SAM: nothing to build (David, 2026-11-02, interactive)

"Aren't Stern SAM games stock emulation already supported in virtual
pinball machines? We don't need to reinvent the wheel. Spike 1 and 2 and
other modern pinball machines are what we want to support." VPinMAME has
the SAM core, so a SAM table already runs the real game from its ROM set;
the hand-off of PAD's edited game file into that ROM set built in run 2
(vpxsam.py, `padvpx sam`) was taken out again (reverted), and the SAM
block came out of the catalogue too (with Chicago Gaming's WPC remakes,
which run their Williams ROMs the same way): the card is the modern
machines only. The focus is Spike 1, Spike 2 and the other modern
machines.

## JJP: the security key, up front (David, 2026-11-02, interactive)

"The JJP games may be misleading: you need the security dongle on the
machine to emulate those, so we should be up front about that." The JJP
game is decrypted by its own Sentinel HL key (tools/jjp_emu/README.md:
"the dongle is not a check, it is the decryption key"; one per title,
H0007 without it), so no bridge could play the real game behind a table
without the machine's key on the PC. The catalogue's platform entry
carries `needs`, and the card shows it on the Jersey Jack block as a
warning chip and a line.

## The Spike 1 author's checklist (run 2)

`vpxauthor.machine_for(title)` reads a Spike 1 title from its game ELF and
switch map when it has no device tables: `spike1_works()` (PAD_S1_WORK, the
app's data disk, each distro's ~/s1emu), `spike1_titles()` (every
`cache/<CARD>/game/<exe>` there, the card stem lowercased as the title),
`spike1_sources()` (the rig's curated `switchmaps/<CARD>.json`, else the
run's s1switches.json), `read_machine_spike1()` in read_machine's shape
(switch id = slot, coils and LEDs from `s1elf --coils/--leds`, nothing
placed). The tab's authors' card offers the Spike 1 titles (got_le, kiss_le,
wn, wwe_le, primus, can_crusher, ghostbusters_le, transformers_pin on this
PC), the sheet and the Markdown say it is a Spike 1 title and how it is
numbered, and a starter map carries `platform: spike1`. GOT LE: 62
playfield switches, 10 cabinet, 24 coils, 246 LEDs.

Fitting a Spike 1 table's lamps will need the matrix channel of each named
insert (the lamp table's column/row to the node's channel): read from a
run against the table's own light names when VPW's GOT download is on the
PC, the way the Spike 2 maps were matched (vpxlamps.py).

## The tab opens at once (David, 2026-11-02, interactive)

"The table view in the Visual Pinball window takes so long to load. It needs
to be instant and any bits that need loading can lazy load in after render
with a loading skeleton." Measured: `vpxsetup.py state` 0.5 s,
`vpxauthor.py titles` 2.1 s (asks WSL), `vpxauthor.py coverage` 7.1 s - and
the page waited for all three before showing a table. Now `_load` puts the
page up on the state alone (and, on a PC that has opened the tab before,
on the LAST state seen - `vpx_state.json` beside the pictures' cache -
before the kit has even answered), the titles and the coverage come in on
a thread of their own (`_start_extras`, the newest load wins) with the
authors' card saying "Finding the games on this PC…" and the Coverage cells
shimmering until they are in, and until the first state is in the Tables
card shows four skeleton rows instead of "Checking…". The buttons work
while the slow parts load (`_busy` is not held).

## Still to do

Nothing of this ticket: the remaining piece, a map for VPW's Game of
Thrones table (and KISS, Whoa Nellie, Primus, Can Crusher), needs the
download (VPUniverse account) and is a fit like any shadow map's - the
checklist and the starter are its starting point.

Was:

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
