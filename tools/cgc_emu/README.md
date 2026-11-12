# Chicago Gaming emulator rig (the WPC remakes)

Runs Chicago Gaming's remakes of the Williams WPC-95 games on this PC from
the card images CGC publishes: the machine's own ARM program under
`qemu-arm`, on hardware this rig makes up (`cgcshim.so`).  It boots to
attract mode and takes switches: coins are booked, Start serves a ball from
the trough, the launch button fires the autoplunger, drains return balls
(PAD-273).  Always hidden (the screen is a file; `shot.sh` makes a picture)
and muted.

| title | card image | status (2026-09-30) |
|---|---|---|
| Medieval Madness 3.0 | `MedievalMadness300Installer.img` | attract, coins, serve, launch, drain, ball save |
| Attack From Mars 1.0 | `AttackFromMars100Installer.img` | attract, coins, serve (bootcheck pass) |
| Monster Bash 1.03 | `MonsterBash103Installer.img` | attract, coins, serve, launch, poppers, Dracula, drain, ball 2 (PAD-1174, below) |
| Cactus Canyon 1.13 | `CactusCanyon_cc113_9-2-25_card.img` | attract, coins, serve, plunge, poppers, drain, full games (PAD-1170, Z5 engine below) |

The Emulate tab for these is a follow-up ticket; nothing in the app calls
this rig yet and the installer does not ship it.

## What the machine is

A BeagleBone Black (TI AM335x, armhf, Debian 7.5, glibc 2.13).  The card's
third partition holds `/emmc.img`, the image the installer writes to the
eMMC; its second partition is the game's Debian, and `/home/debian/emumm`
is the game: `emumm` (Steve Ellenoff's WPC-95 emulator - a 6809 running the
original Williams ROM, PinMAME's WPC core underneath - with CGC's colour
LCD, menus and DCS-replacement sound on top), the ROM, `cgc.so` (CGC's
art), `*data/` (sounds).  The program keeps its symbols.

| the machine | the rig |
|---|---|
| the BeagleBone | `qemu-arm-static -L <build>/sysroot` (the card's own libraries) |
| McSPI + 4 GPIO banks through `/dev/mem` | `/dev/zero`-backed memory; the once-a-millisecond board exchange (`io()` on MM, `sam_io()` on AFM/MB) returns at once, patched at its entry by name |
| the SPI FRAM (the game's NVRAM: settings, audits, high scores) | a model of the chip at the program's `spix`/`spi_cs_*` byte exchange, backed by `$CGC_ROOT/nv<slot>/<title>/fram.bin`, kept |
| the 1280x768 LCD (libdrm dumb buffers on `/dev/dri/card0`) | the `drm*` calls answered by the shim; the three RGB565 buffers live in `$CGC_RIG/fb` with a header naming the one on screen (`cgcshot.py`) |
| the playfield and backbox boards | the program's own switch array, written by the shim: `sw.py` |
| the speakers | SDL's dummy audio driver |
| `/tmp/z4.log` | a private `/tmp` per rig (`$CGC_RIG/tmp`) |

`prepare.sh` mounts the card **read-only** on two nested loop devices and
copies only the game folder and the ~50 libraries it loads (~270-320 MB a
title).  PAD-Runtime's disk is small: check `df -h /var/tmp` first.

## The board (cgcshim.c)

* **Switches.**  A set bit in the array is a closed switch, except an opto,
  which reads set when clear.  At power-up the program leaves the array as
  the machine at rest (balls home, coin door closed); MB's leaves its optos
  blocked and its ROM then says CHECK FUSES F101 AND F109 ... OPTO 12V
  SUPPLY, so the board clears every opto it knows before the balls go home.
* **Names.**  `cgcroms.py` reads the switch, flipper and coil names out of
  the Williams ROM's own test-menu tables (English page; entry 0 of each
  table is its "invalid number" text - MM's coil 1 is AUTO PLUNGER, coil 2
  TROUGH EJECT).  `sw.py list` prints them.
* **Balls** - counting, not physics.  `cgctitles.py` builds `$CGC_BALLS`
  from those names: the trough (TROUGH BALL 1-4, closed = a ball), the
  TROUGH EJECT coil (kicks position 1 at once, the rest roll down after
  400 ms, the ball reaches the SHOOTER LANE after 600 ms - a game that sees
  nothing move re-kicks; a second kick stacks a ball behind one already in
  the lane, as on the machine), the AUTO PLUNGER coil (shooter lane -> in play),
  kickouts (MM: LEFT POPPER, RIGHT EJECT, CATAPULT; CC: MINE and SALOON
  POPPER on coils 6 and 8; MB: RIGHT POPPER 16, LEFT EJECT 15), two-position
  motors (MM drawbridge; MB bank and Frankenstein table; `mechs=coil:rest:far`,
  optionally `:leave:travel` in ms, default 60 and 700), and a toy on a track
  (MB's Dracula: `tracks=fwd:back:pos1/pos2/...`, home first; it moves while
  its coil is ON, 150 ms of that per position, so a game's PWM drive moves it
  too).  Coil pulses are read at 1 kHz; `$CGC_RIG/events` logs one line per
  pulse, and one per motor or track reaching or leaving a switch.
* **Debugging the model.**  `CGC_BALLS='<line>' run_game.sh` runs a ball model
  by hand instead of the title's; `CGC_TRACE=1` adds every coil's release to
  `events` with how long it was on (`<ms> sol <n> off <on-ms>`).
* **First boot.**  A new FRAM makes the ROM restore factory settings and
  wait; `run_game.sh` presses ENTER, then ESCAPE until the lamps run, as an
  operator would, once per slot and title.
* **Ready.**  Every WPC ROM here ignores Start for a while after its lamps
  run (MM, AFM: ~450 frames from power-up; the rig's 5 s settle covers it).
  Monster Bash's does for ~1740 frames (~29 s of game time) whatever the board
  says, so its title entry has `ready_frames` and `run_game.sh` returns only
  once the game is past it: a Start pressed then is taken.

## Monster Bash (PAD-1174)

What PAD-273 and PAD-1170 took for the Frankenstein table was three other
things, each proven on the rig:

* **Its coil numbers.**  The ROM's coil-name table leaves out solenoid 4
  (unused on this machine): its entries run 1, 2, 3, 5, 6 ..., so LEFT GATE
  and every coil after it is one higher than its place in the table.  The
  ROM's own solenoid test (T.4) shows it: "09 TROUGH EJECT" fires coil 9,
  "01 AUTO PLUNGER" coil 1, 04 and 07 (KNOCKER) are skipped.  `cgctitles.py`
  carries the gap (`coil_gaps`) and the rig's `names.json` uses the machine's
  numbers.  MM's and AFM's tables have no gap.
* **The right popper.**  Its switch (36) is an opto the program powers up
  reading blocked: the game saw a ball there and kicked coil 16 (the popper)
  every 1.5 s - the pulse that read as FRANK. MOTOR through the gap.  It is
  now an opto read empty, kicked out by 16; LEFT EJECT (28) by 15.
* **Start.**  The ROM ignores Start for its first ~29 s (above); the rig
  pressed it at ~8 s.  `bootcheck.sh` and every later press now land after it.

Dracula rides a track: DRAC. MTR. FORWD. (21) and BCKWD. (22) over DRAC.
POSITION 1 (78, home) to 5 (74).  A ball in the left eject sends him forward,
and the eject waits for him to move.  The Frankenstein table (FRANK. MOTOR 17,
TABLE DOWN 83 at rest / UP 84) and the up/down bank (18, UP 81 at rest / DOWN
82) keep the two-position model; nothing in the runs here asked either to
move.

## Cactus Canyon: the Z5 engine (PAD-1170)

Cactus Canyon runs `/home/debian/pin`, CGC's own C engine ("Z5": no 6809;
the Williams ROM `ccdata/rom/cc_g11.1_3` is there for its names and text).
The shim finds `z5_main` and takes a second hook map (cgcshim.c, "Z5"):

* **FRAM**: `z5_spix` / `z5_spi_cs_*` - the same chip model, 8 KiB used.
* **Playfield switches**: `z5_spi_packet_xfer` is answered with the
  playfield PIC's reply (0x43, 12 data bytes, their sum; bytes 1-8 the
  matrix, active low).  Without a valid reply pin never reads the matrix.
* **Cabinet switches** (coin door, Start, flipper buttons):
  `z5_gpio_xfer`'s two input bytes.
* **Numbers**: pin's own tables at power-up map WPC numbers to its inputs
  and outputs (`z5_sw_wms_to_cgc_map`, `z5_sol_`, `z5_flash_`, `z5_lp_`),
  so `sw.py` and `$CGC_BALLS` speak WPC numbers as for the other titles.
  `shim.log` lists the switch map.
* **Optos**: every input carries pin's flags: 0x20 an opto, which the game
  reads *active when blocked*, 0x10 its contact inverted.  The shim sets
  what the game should read (closed = a ball there) through both, so the
  ROM's `*` marks are not used.  Getting this backwards is what trips a
  hand-made board: with the trough read inverted pin serves at power-up,
  with the poppers inverted it kicks both of them in a ball search.  At
  rest: 32-35 a ball each, 31 (TROUGH EJECT) clear - all five alike is
  OPTO TROUGH BAD - poppers 41/42 empty, 22 and 24 closed.
* **Lamps**: the drive bit (+0x2e of each lamp entry); `z5_lamp_get` reads
  a field that stays 0.  pin lights a few lamps as its tables load, so
  `run_game.sh` takes attract as the lamps *moving* once the board rests.
* **Unaligned LDRD/STRD/LDM/STM**: pin stores scores with STRD at 2-aligned
  addresses (`bcd_clear`, every ball start).  The BeagleBone's kernel fixes
  those up; qemu-arm raises SIGBUS, so the shim's handler does the access
  byte by byte and steps past it, as the kernel would (`shim.log`: "fixed
  up").
* No USB saloon kit (the Bart toy mech): pin says SALOON MECH NOT FOUND at
  ball start and plays on without it.

## Using it

As root in PAD-Runtime (`wsl -d PAD-Runtime -u root`), with `PAD_SLOT` and
`PAD_LABEL=PAD-n` set as for every rig:

```bash
bash tools/cgc_emu/prepare.sh /mnt/d/Pinball/images/CGC/MedievalMadness300Installer.img
bash tools/cgc_emu/build.sh                  # developers: rebuild cgcshim.so
bash tools/cgc_emu/run_game.sh <build>       # returns at attract (15 s; 65 s the first time)
python3 tools/cgc_emu/sw.py coin 4
python3 tools/cgc_emu/sw.py tap start
python3 tools/cgc_emu/sw.py tap "launch button"
python3 tools/cgc_emu/sw.py tap "left slingshot"   # any name from `sw.py list`
python3 tools/cgc_emu/sw.py drain
python3 tools/cgc_emu/sw.py on enter         # coin door: D1..D8, flippers F1..F8
bash tools/cgc_emu/shot.sh /mnt/c/tmp/mm.png --scale 2
bash tools/cgc_emu/status.sh
bash tools/cgc_emu/killgame.sh
bash tools/cgc_emu/bootcheck.sh <build>      # VERDICT: attract, coins booked, a ball served
```

`CGC_FRESH=1` on `run_game.sh` starts the slot's settings over.  Never
`pkill qemu-arm`: other rigs run it; every stop here goes by `CGC_MARK`.

## Not done yet

* The colour: the shots show CGC's green DMD dots; whether the card's
  default is a colour palette (`cgc.so` replacement art) was not checked.
* A visible window, sound, and the Emulate tab (with a switch window).
