# Emulating Spooky's pinHeck DMD games (PAD-320)

America's Most Haunted, Rob Zombie's Spookshow International, Domino's
Spectacular Pinball Adventure and Jetsons do not run Linux. They run on Ben
Heck's **pinHeck System** board (2011-2016): two microcontrollers and an SD
card. `games.py` used to call them "P3 / Multimorphic"; that was wrong
(Multimorphic's P3 is a different, PC-based machine). The `P3_`/`p3_` names in
the code stay as they are (p3_video.py is an upstream-identical lift).

## What is on the board

| Part | Chip | Job | File in the update |
|---|---|---|---|
| Game CPU | PIC32MX795F512L, 80 MHz MIPS32 M4K (chipKIT Max32 core) | rules, switch matrix, coils, lamp matrix (Timer2 ISR drives LATB), servos, settings menus, a serial monitor on UART1 | `<GAME>_Vnnn.PRG` = raw program flash from 0x9D000000 (vectors at +0x180/+0x200, app `_reset` at 0x9D001000; chipKIT bootloader not needed) |
| A/V | Parallax Propeller P8X32A, 104 MHz (6.5 MHz x16) | reads the SD card, plays `DMD/_D?/*.VID` + sprites (`.SPR`) + fonts (`.FNT`), draws scores/text over them, drives the DMD panel, mixes `SFX/_F?/*.wav` to a DAC, keeps settings/audits in its EEPROM | `PRP_Vnnn.BIN` = 32 KB Propeller EEPROM image (header checks: clock 104 000 000, mode 0x6F, checksum OK) |

Proof: the PRG's strings say `pinHeck System 2011-2016 / Benjamin J
Heckendorn, Parker Dillmann, ...`, `HardwareSerial` (chipKIT/Arduino), and
`PROPELLER SYNC CHECK`, `HANDSHAKE DONE`; the BIN holds `MCU:SYNC`, `GFX
UPDATED`, `LAYER0/1`, `FRAME`. The SFRs the PRG touches are PIC32MX7 ones
(PORTA..G at 0xBF886000.., UARTs at 0xBF806000..).

The two chips talk over a **bit-banged clocked serial link** (SDO/CLK/SDI,
chipKIT pins 16/15/14): the PIC clocks out 16-byte packets, last byte = the
command code (0x01 play SFX, 0x02 play video, sprites, numbers, scores, music,
volume, high-score entry, EEPROM read/write with a checksum...), and clocks 16
bytes back at the same time.

## Public sources (reference only, never bundled)

- [benheck/AMH](https://github.com/benheck/AMH): the full America's Most
  Haunted code - `amh_pic32_ver023.pde` (PIC32 game, 18 600 lines; `sendData`,
  `video()`, `playSFX()` show the packet format) and `amh_AV_prop_rev23/`
  (Propeller A/V kernel in Spin: `Interpret` is the command decoder,
  `SD_Engine_0`, `roy_DAC_4` audio, `dmd_IO_driver_128x32_16shade`).
- [LonghornEngineer/Pinheck_Pinball_System](https://github.com/LonghornEngineer/Pinheck_Pinball_System):
  board schematics (Eagle), Max32 bootloader, test code.
- Jetsons and Domino's are later builds of the same system with a colour DMD
  (8bpp RGB332 VIDs) and newer Propeller code; there is **no public source for
  their Propeller side**, so its command set has to be read out of
  `PRP_V002.BIN` / `PRP_V008.BIN` (Spin bytecode, decompilable).

## Feasibility: proven for the game CPU

Pass 1 booted the PRG on [Unicorn](https://www.unicorn-engine.org/) (MIPS32
LE, already installed) as far as `PROPELLER SYNC CHECK...`, where it waits
for the A/V chip. Unicorn reports a spurious `UC_ERR_READ_UNMAPPED` when an
instruction-count slice ends; it is ignored while PC is in flash.

## Pass 2 (2026-10-02): handshake answered, attract running

`tools/pinheck_emu/` (README there) now has the game CPU (`pic32.py`), the
Propeller link (`proplink.py`) and the I2C chips (`i2c.py`);
`python -m tools.pinheck_emu.run <PRG> [seconds]` prints the serial monitor
and every packet sent to the Propeller.

| Game | Result (emulated seconds) |
|---|---|
| Jetsons `JET_V004.PRG` | `PROPELLER SYNC CHECK...OK`, Propeller EEPROM read/written and verified, the full `pinHeck System 2011-2016` banner, the RTC time, then the attract cycle: videos ZMA, ATK, ATD, KJB, KGB, ATR, ATE (all on its card under `DMD/_D?/`), the TOP 5 HIGH SCORES text, number and sound packets - 40-60 s, repeating |
| Domino's `DOM_V006.PRG` | `PROPELLER SYNC CHECKOK`, `NAMING GAME`, default scores written, first attract video (`KAC`); then a quiet main loop for the rest of 45 s - not yet known whether it waits for a Propeller status or a timer |

What it took (all in `pic32.py` / `proplink.py` docstrings):
- **Link pins**: SDO = RF5, CLK = RF12, SDI = RF13; LSB first, 16 bytes.
  The **sync** packet is `AA '0'..'=' '#'`; the Propeller answers the pattern
  moved to bytes 0..13 plus `AA AA` (Domino's checks the pattern, Jetsons only
  the AAs). Everything else is AMH's format: command in byte 15, `FF` = plain
  exchange; EEPROM `20`/`21`/`22` exactly as AMH's `Interpret`.
- **Interrupts**: delivered by hand at slice boundaries through a 4-word
  trampoline in boot flash that loads EPC (Unicorn has no API for it, and a
  handler that `eret`s to an unset EPC jumps to 0); stopped at the handler's
  `eret`. chipKIT vectors jump through a RAM table at 0xA0001CD0. Live: T2
  (lamps, 8 kHz), T3 (switches, 2 kHz), T4, I2C1 master. A handler that
  never returns is an error, not a silent stack leak (that leak ate the
  vector table once).
- **CP0 Count**: Unicorn's never moves and `delayMicroseconds()` (inside the
  switch handler) spins on it: the three `mfc0 rt,$9` in each PRG are
  patched to nops and a hook supplies clock/2.
- **I2C on the PIC side**: a 24LC256-style EEPROM at 0x50 (the game's own
  settings, read 4 bytes at a time; the game hangs forever if it NAKs) and a
  DS1307-style RTC at 0x68. I2C completions are flagged after the handler
  returns, as the real bus takes time.
- **Inputs idle high**: with them low the game read the menu buttons as held
  and went into its service menu.

Packets seen (Jetsons; Domino's puts the video name in bytes 0..2 instead):
`02` video (bytes 1..3 = file name, `ZMA` = `DMD/_DZ/ZMA.VID`; bytes 0, 7,
8 and 14 vary and are not decoded yet), `01` sound (`C01` = `SFX/_FC/C01.wav`), `12`
text line (byte 0 = slot, then ASCII), `0e` high-score entry (rank, score
LE, initials), `10` volume/settings, `04`, `06`, `09`, `0c`, `0f`, `13`,
`23`, `27`, `29` not decoded yet.

Speed: about 0.5x real time (60 s emulated in 114 s) after pass 2, nearly
all of it Unicorn running instructions (~42 MIPS for an 80 MHz part). Pass 4
measured where they go: 74% in `while (millis() == last);` and most of boot
in `delay()`, against 2% in interrupt handlers. Both loops are now found by
their code and parked until the next millisecond (interrupts still run on
time): Jetsons 40 s in 26.8 s and Domino's in 25.9 s, ~1.5x real time, with
the same packets and serial output as a full run (only the random attract
picks differ, the game seeds them from timing).

## Pass 3 (2026-10-02): the DMD shows the attract art

`tools/pinheck_emu/av.py` follows the video packets and draws the DMD from
the card's own VIDs with the plugin's `p3_video.py`; `run.py --sheet` saves
one frame per video played. Jetsons shows its logo and "PRESENTS"; several
videos start at the same instant (a queue - the 0x06-style enqueue is not
modelled, so the sheet shows the queued ones too).

Domino's "stall" was the game, not the emulator: on a blank EEPROM it
writes its version (`600BAFA`) and shows the video `KAC` - "System has been
updated / Please restart your machine" - and waits. `run.py --nvram DIR`
now keeps both EEPROMs between runs, and the second boot prints `Version:
006`, loads high scores and runs attract (`ATT` "FawzmaGames", `WBJ`, ...).
Domino's sends `ff 00.. 02` to stop a video, and names `AT0`, which is not
on its card (`DMD/_DA` has AT1, AT9, ATI, ATS.. but no AT0) - the real
machine presumably shows nothing there either.

## Pass 5 (2026-10-02): switches - a Jetsons game starts

`board.py`: the cabinet buttons come through a 16-bit shift register read
in houseKeeping() (coil enable RG15, GI data RG7, clock RE0, data RF0,
latch RG8, twice a millisecond), bit numbers as AMH's gs_pins.h (Door 1,
RFlip 3, LFlip 4, Menu 5, Enter 6, Coin 7, Tilt 8, Start 12); the playfield
matrix is LATD's high byte (row, active low) and PORTD's low byte (columns)
in the Timer3 handler, switch = row * 8 + column. Checked against the
game's own serial dump: UART1 receive now works, and `[E99000]` returns
`00 02` idle (door shut), `10 02` with Start, `00 82` with Coin, and the
right row byte for matrix switches 0, 10 and 63.

With a coin and Start and no balls, Jetsons plays `ADD` ("MISSING BALLS").
Trying each matrix row from a snapshot of the running machine found the
trough: switches 34 and 35 must both be closed, and 32 is the shooter lane.
`run.py --closed 32,34,35 --tap coin@14 --tap start@15` gives `ADD`, then
`GET` ("GET READY!!") and `SK1` ("SKILL SHOT / LEFT SPINNER / HOLD LAUNCH
BUTTON FOR POWER") - a game has started. Next: the coils (the trough eject
should move a ball to 32 by itself) and the rest of the switch map.

## Recommended design

1. **Game CPU: emulate it** (Unicorn), running the user's own PRG unmodified.
   Model only the PIC32MX795 parts the game uses: GPIO ports A-G with
   CLR/SET/INV shadows, core timer + Timer2..5 and the interrupt controller
   (Unicorn has no EIC: deliver vectors by hand - EBASE+0x200+n*0x20, set
   EPC/EXL, `eret` returns), UART1 (serial monitor - free debug channel and a
   test hook: `[E00000]` version, `[E99000]` switch dump), I2C if the
   board's EEPROM turns out to be on the PIC side. Then the board: switch
   matrix + dedicated switches into ports, coil/lamp/servo outputs out.
2. **A/V chip: high-level, not cycle-level.** A Propeller emulator (spinsim
   etc.) cannot keep up: 8 cogs x 26 MIPS bit-banging a DMD scan, an SD card
   and an audio DAC. Instead decode the 16-byte packets and do the work
   natively: VIDs through the existing `p3_video.py` decoder, wavs through
   the mixer the other emulators use, scores/fonts/sprites from the `.FNT` /
   `.SPR` files, settings in a host file. AMH's `Interpret` gives the
   command set for the 16-shade games (AMH, Rob Zombie); for Jetsons and
   Domino's it must be recovered from the PRP binaries plus watching what the
   PRG sends - that is the unknown part of this ticket.
3. **Rig**: a new `tools/pinheck_emu/` rig on the rig-slot protocol, hidden +
   muted, its DMD on the rig board, switches via the usual poke tool, an
   Emulate tab in the Spooky manufacturer like the Warden one.

Milestones, each its own run of proof:
- A. handshake answered: DONE in pass 2 (Jetsons and Domino's).
- B. attract: DONE as stills - both games' attract videos drawn from the
  card (pass 3). Left: a live DMD (frame timing, the video queue, the 0x12
  text and score overlays from the `.FNT` files), and the commands still
  undecoded.
- C. coin + start + a ball with switch pokes; scores drawn; sound (muted, from
  the level log).
- D. AMH / Rob Zombie once their update files are on disk (none on D: today).

## Grade

S3 (these games cannot be tried at all today, but nothing breaks). D4 after
pass 1: the mechanism is known and the CPU half is shown to run. Still D4
after pass 2: the game CPU now runs a colour game's attract unaided, but
what is left is the DMD/sound side, switches and the rig - several runs.
