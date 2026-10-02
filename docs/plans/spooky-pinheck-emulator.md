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

`tools/pinheck_emu/boot_probe.py` loads the PRG into
[Unicorn](https://www.unicorn-engine.org/) (MIPS32 LE, already installed),
maps flash/RAM/SFRs, bumps `millis()` every 80 000 instructions (in place of
the core-timer interrupt), and prints UART1:

| Game | Result |
|---|---|
| Jetsons `JET_V004.PRG` | runs crt0 + Arduino setup, prints `PROPELLER SYNC CHECK......`, then polls PORTF (the SDI line) for the Propeller's answer |
| Domino's `DOM_V006.PRG` | same, `PROPELLER SYNC CHECK........` |

Speed: 400 M instructions in 6-8 s of wall time (~55-65 MIPS) with Python
MMIO hooks - about real time for an 80 MHz M4K. Unicorn reports a spurious
`UC_ERR_READ_UNMAPPED` when an instruction-count slice ends; the probe
ignores it while PC is in flash.

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
- A. handshake answered: PRG prints `HANDSHAKE DONE` and the version banner
  (needs the sync reply format - from the PRP's `MCU:SYNC` code path).
- B. attract: packet log shows the attract video commands; DMD shows the VIDs.
- C. coin + start + a ball with switch pokes; scores drawn; sound (muted, from
  the level log).
- D. AMH / Rob Zombie once their update files are on disk (none on D: today).

## Grade

S3 (these games cannot be tried at all today, but nothing breaks). D4 after
this pass: the mechanism is known and the CPU half is shown to run; what is
left is a new instrument (the rig) plus reverse-engineering the closed colour
Propeller protocol over several runs.
