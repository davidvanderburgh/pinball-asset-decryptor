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

## The downloads in the folder (David, 2026-11-02, interactive)

"I just added a handful of VPX original tables to the folder, but the app
is not showing them (KISS, GoT, GB, etc.). It should ideally update the
table listing live, or require 'Check again' to be pressed and react to
that." The Tables card listed only the kit's known tables and the (PAD)
copies; a download of the person's in the folder was invisible. Now every
.vpx in the tables folder that is not a (PAD) copy is listed at once
(`vpxsetup.downloads_in`), read once per file on the extras thread
(`vpxsetup.py downloads`: which listed map fits its script, which
catalogue table its name is, kept in `~/.pad-vpx.downloads.json` by size
and mtime), a download a known table's map fits goes on that table's row
(its Patch takes the file without a dialog), and the rest are rows of their
own: "Stern Spike 1 game: no map yet" with the catalogue's name. The tab
watches the folder every 3 s while it is up (`_watch_folder`) and re-reads
the kit's state when a table comes, goes or changes, so a download dropped
in shows by itself; Check again does the same by hand.

## The five Spike 1 tables in David's folder, mapped (David, 2026-11-02, interactive)

"We need to map the files that are 'no map yet' that I have added to my
library." Five maps, each generated from the game's own program and the
rig's curated switch map (the generators are the record of how each table's
objects were matched; the maps carry the result with GUESS marks):

* **got_le** (VPW's GOT LE 1.2.1): the table numbers its switches as Stern's
  manual does, so each trigger was matched by its script's meaning and
  place to the rig's names (40 switches, the throne saucer, the trough, the
  shooter lane); its lights are named li<N> after the LE's own LED table (an
  RGB insert = three LEDs in a row), so 85 lights came straight out of the
  program; the game's coils (trough, auto launch, both drop resets, the
  elevator diverter, the throne). The elevator and the dragon scoop keep
  the table's script (no switch for them on the rig's walk).
* **kiss_le** (masonm's KISS 2.0): its sw<N> are the program's switch N
  (sw42 = DEMON EJECT); the lights i<N> are the Pro manual's lamp numbers =
  the LE program's lamp N + 32, and LED L - 2 drives lamp L (checked on
  seven named lamps); the Starchild and scoop saucers, the Demon's lock lane
  (LOCK 1-3, let out through sw42TOP), the centre drop's up/down coils.
  Eight switches the curated map lacks (right outlane, right return lane,
  both orbits, the four ARMY targets) keep the table's subs: the registry
  walk (s1swmap.py) could name them, but it looks for a guest with
  comm=game and does not find a pivoted (S1_PIVOT=1) run - the rig's own
  gap, not the map's.
* **ghostbusters_le** (JP's Slimer v602): JP's own layout, loosely Stern's:
  the six lanes, the pop lane, the loops, the bumpers, the scoops as
  saucers on LEFT EJECT and SUBWAY, the storage lock on LOCK #1-3 with
  LOCK POST, the Scoleri brothers as the two 1-bank drops with their up
  and down coils; targets by place, GUESS. JP's lights are his own: not
  mapped.
* **primus**, **can_crusher** (Drummer72's, one script, Whoa Nellie's
  layout): the lanes, the top lanes, the standups and star rollovers by
  place, the five bumpers, the top eject as a saucer, one ball in the
  trough; the authors' lights carry no numbering of the game's: not mapped.
  Neither table loads core.vbs, so vpxshadow now loads it before
  Table1_Init when a script lacks it, and their timers are cloned from the
  table's ResetTimer (no PulseTimer).

All five patch (`vpxfile verify` OK) and their (PAD) copies are in David's
tables folder; the page lists them as patched with Play. What a game on
each table will tell: every GUESS mark (vpxauthor's checklist lists them).

## The once-over on coverage (David, 2026-11-02, interactive)

"Do a once-over on all the VPX tables to improve the coverage ... get the
coverage as high as possible. Also remove Stranger Things (not a valid
table at all)." Stranger Things' map is gone. KISS went 62% -> 86%: its
lights follow the Pro manual in three blocks (6-8 the lanes, 9-24 the
sixteen bonus inserts as RGB triples, 25+ = the LE's number - 32), plus the
bumper caps and the right ramp arrow. The metric itself was counting what
no table can have: a mech's own position switches (motor home/away,
encoder optos, reel homes), switches and coils the game leaves unnamed
("SWITCH #71", "COIL #38"), meters, ticket drives, the cabinet's LEDs on a
Spike 1 title - `owed_switch` / `owed_coil` in vpxauthor say what a table
owes, and summary_for and gaps both use them. Every map moved up a little
(Bond LE 83 -> 85, Batman 92 -> 94, Godzilla 96 -> 98 ...). What is left,
per the gaps: parts the tables do not have (Bond's rocket, JAWS' shark
positions, Metallica's 6-ball trough on a 4-ball table), flashers and
hardwired GI, and a handful of inserts on Rush, the Turtles, Guardians,
Foo Fighters and Metallica that `vpxlamps.py suggest` refuses to place
(the fit does not hold on those tables): those are by-eye work with the
playfield, one table at a time. Primus and Can Crusher (24%) and JP's
Ghostbusters (26%) stay low because their authors' lights carry no
numbering of the game's and Drummer72's tables have no standup targets.

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

## The Coverage column is kept between sittings (David, 2026-11-02, interactive)

"It seems like the coverage metric is recalculated every time the app
restarts? Can't we cache it?" It was, on every start, not only a dev
launch: `_want_coverage` began True and the column lived in the page store
only, so each start paid `vpxauthor.py coverage` (~7 s over WSL). Now the
last read is written to `vpx_coverage.json` beside `vpx_state.json` with a
key of what it was read from - every `*.shadow.json` in the kit and
`vpxauthor.py` (their mtimes: a map edited or the app updated with new
owed rules reads again) and the titles with tables on this PC (a title
played for the first time reads again). A new sitting draws the column at
once from the cache, before the kit has answered, and reads nothing when
the key still matches; Check again reads it anyway (the button sets
`_want_coverage`; opening the tab no longer does). When the kit's titles
cannot be read (WSL down) the cache is neither trusted nor rewritten.

## Whose controller a table calls (David, 2026-11-02, interactive)

JP's Ghostbusters (a Spike 1 title) stopped on "PAD.Controller: no Spike 2
run is up for ghostbusters_le ... the library D:\Pinball\images\Stern\spike2".
Two things:

1. PAD.Controller is one COM registration per PC (HKLM, `PythonCOMPath`),
   and on David's PC it names the MAIN checkout's kit - every table,
   whichever copy of the app patched it, calls that one, and main has no
   Spike 1 yet. So a Spike 1 table cannot start from Visual Pinball until
   this ticket is merged (or the ticket's kit is registered, which the
   worktree's removal after the release would then break). The emulator
   proof of the Spike 1 path drives `Bridge` from Python for that reason.
   The tab now says so: `vpxsetup.py state` carries `registered_to` and
   `registered_here` (the registered folder is THIS kit's), and the
   controller row reads "Registered to another copy of the app: <path>
   ... Register" with the button, instead of a plain "Registered."
2. The refusal named the Spike 2 library only: `card_places(title,
   platform)` names the platform's libraries (for Spike 1 the `spike1`
   sibling too).

Seen in the same sitting, not this ticket's: Metallica's machine-screen
window (WSLg) up on the taskbar but blank. WSLg's weston.log says
`rdp_allocate_shared_memory: Failed to open "/mnt/shared_memory/{...}":
Input/output error` thirty times a second from the moment the window
opened, and `/mnt/shared_memory` (the virtiofs share WSLg hands frames to
Windows through) returns I/O error inside the VM: a WSL fault, every WSLg
window blank until `wsl --shutdown` (David's call: it ends every run).

## The tab on every manufacturer the app emulates (David, 2026-11-02, interactive)

"We should add the Visual Pinball tab to the other manufacturers that we are
adding support for." The rail's gate (`window._gate`) was `emulate` (Stern
Spike 2) only; it is now any emulator capability (`emulate`, `emulate_spike1`,
`emulate_jjp`, `_ap`, `_bof`, `_dp`, `_spooky`, `_pb`). The tab follows the
manufacturer through `on_manufacturer`: `platform_of_manufacturer` gives
Stern's era (spike2 / spike1; SAM and Whitestar have no emulator, so no tab)
or the manufacturer's key, which is its platform key in catalog.json. The
page then shows that machine's own: the Tables rows of that platform
(known_tables rows carry `platform`; a download's from its catalogue match;
another platform's (PAD) copy is not a row), the authors' card's titles of
that platform (`vpxauthor.py titles` returns `platforms` for the titles that
are not Spike 2's), the catalogue block of that platform as "More <machine>
tables", and a line under the Tables naming where the other machines' tables
went. A platform with no bridge yet (`BRIDGED` = spike2, spike1) says so in a
note at the top, and its Setup hides the Controller and Card images rows,
Patch a folder and the authors' card: the tables listed play as their authors
wrote them. The intro no longer says "Stern".

## Restart WSL… on the tab (David, 2026-11-02, interactive)

"We should have the Restart WSL… button on the Visual Pinball tab too": the
Emulate tabs' cure, beside Check again. `restart_wsl` asks first (the dialog
names the three cases: the game's screen gone blank on the desktop while the
table still plays - WSLg's frame share dead, as Metallica's was - a window
that will not close, crackly sound; and that it closes every game on every
tab), then `wsl --shutdown` on the tab's job thread, the page saying
"Restarting WSL", and the state read again after.

## Every table played (David, 2026-11-02, interactive)

Pabst Can Crusher stopped on "Line 2344: Wrong number of arguments:
bsTrough.InitSw". core.vbs's `cvpmBallStack.InitSw` takes exactly seven
switches (`InitSw8` eight) and the one-ball trough of Can Crusher and Primus
passed one. `vpxshadow.trough_init` pads to seven (InitSw8 for eight, more
refused) the way a lock lane's stack already was; both tables re-patched and
re-signed in David's folder; an arity pass over every (PAD) script in the
folder found no other such call.

David: "make sure you try and run each and every game in the list to ensure
it can load and at least play one or two balls." `scripts/vpx_play_each.py`
does that in the real Visual Pinball: each (PAD) table opened as Play opens
it, the controller's log watched for the attach (or a Run failure), Visual
Pinball's dialogs (class #32770: a script error, the patch's MsgBox) read
off the desktop, then coin + Start + plunge sent to the player window and
the trough's kicks (solenoid 1) counted until the asked balls were served;
the player window closed cleanly so the controller stops the run it
started; a report on stdout and as JSON. `--this-kit` registers THIS
checkout's PAD.Controller for the current user (HKCU\Software\Classes
wins over HKLM in HKCR, no elevation) for the run and removes it after: the
way to play the Spike 1 tables from the worktree without touching the
machine-wide registration. It refuses to start while Visual Pinball is
open. NOT RUN YET in this sitting: it takes the desktop for an hour, David
was playing, and every WSLg window on the PC was blank (the frame share
fault above) until a WSL restart; it is the next step once he says so.

## The play-through's results (2026-11-02, evening)

`scripts/vpx_play_each.py` ran all 22 (PAD) tables on David's desktop
(four passes; `work/artifacts/PAD-943/vpx_play_each_pass{1..4}.json`,
merged by `vpx_play_each_merge.py` into `vpx_play_each_final.md`):

* **Stern Spike 2, 17 of 17 play two balls** through the real table:
  Aerosmith, Batman, Black Knight, Iron Maiden, JAWS, Deadpool, Foo
  Fighters, Jurassic Park LE and Pro, Metallica, Rush, Turtles, Bond, Star
  Wars on the first pass; Guardians (a runtime error that came with a stale
  controller feeding it another table's switches: clean on a retest), John
  Wick (balls counted from the Start press) and The Beatles (its trough is
  solenoid 10) on retests.
* **Stern Spike 1, 5 of 5 load and the game begins, none serves a ball.**
  Every table attaches, boots to attract, takes the coins (a 600 ms pulse
  now; the one-tick PulseSw never counted) and Start, and the DMD shows
  BALL 1 - but the game never serves the ball the table holds in the
  trough: Ghostbusters fires no coil at all for five minutes, Primus and
  Can Crusher go into a ball search that reaches the trough kicker a
  hundred seconds in (Primus got one ball that way), GOT's table hands the
  game five of its seven trough switches. The experiment on the rig with
  the trough held through the bridge's own pipe got as far as BALL 1 the
  same way. So the open item is the bridge's trough hand-off on Spike 1:
  what the game sees of the table's trough switches at Start (the ids, the
  optos' sense, the jam) - a rig session with the switch window, not more
  Visual Pinball runs. GOT needed FlexDMD and KISS UltraDMD: both stand in
  as null objects now and those tables load.

What the runner learned on the way is in its docstring and the commits:
the controller attaches a minute before attract; a killed Visual Pinball
leaves a PAD.Controller server that attaches to the next run; keys need
the real foreground; "Preparing Table" is not an error; dialog text comes
only by WM_GETTEXT; a kick at attach is the game's own check.

## Still to do

The Spike 1 ball serve (above): a rig session on what the game sees of the
table-held trough at Start. Until then a Spike 1 table loads and the game
starts, and no ball comes.

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
