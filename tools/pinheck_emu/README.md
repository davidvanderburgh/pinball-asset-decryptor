# pinHeck game-CPU emulator (PAD-320, work in progress)

Spooky's DMD games (America's Most Haunted, Rob Zombie's Spookshow
International, Domino's Spectacular Pinball Adventure, Jetsons) run on Ben
Heck's **pinHeck System**: a PIC32MX795F512L runs the game from
`<GAME>_Vnnn.PRG`, and a Parallax Propeller does the DMD and sound from
`PRP_Vnnn.BIN` and the SD card. This tool runs the PRG unmodified on
Unicorn and stands in for the Propeller at the packet level.
Plan and findings: `docs/plans/spooky-pinheck-emulator.md`.

```
python -m tools.pinheck_emu.run <GAME_Vnnn.PRG> [seconds]
```

prints every packet the game sends the Propeller and the game's serial
monitor. It is headless and silent; it opens no window and plays nothing.
There is no rig, DMD view, switch input or Emulate tab yet.

| file | what |
|---|---|
| `pic32.py` | the game CPU: flash/RAM/SFRs, GPIO, UART TX, timers, interrupts (by hand, through an EPC trampoline), I2C1 master, CP0 Count |
| `proplink.py` | the bit-banged PIC <-> Propeller link: framing, the sync handshake, the Propeller-side EEPROM |
| `i2c.py` | the PIC-side I2C chips: 24LC256-style EEPROM (0x50), DS1307-style RTC (0x68) |
| `run.py` | boots a PRG with all of the above and logs it |

Status (2026-10-02): Jetsons V004 gets through the handshake and settings
and runs its attract cycle (videos, high-score text, sounds as packets).
Domino's V006 gets through the handshake and settings and starts attract.
About 0.5x real time.

Tests: `tests/test_pinheck_emu.py` (synthetic, no game files).
