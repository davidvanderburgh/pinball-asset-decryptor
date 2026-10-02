# pinHeck game-CPU emulator (PAD-320, work in progress)

Spooky's DMD games (America's Most Haunted, Rob Zombie's Spookshow
International, Domino's Spectacular Pinball Adventure, Jetsons) run on Ben
Heck's **pinHeck System**: a PIC32MX795F512L runs the game from
`<GAME>_Vnnn.PRG`, and a Parallax Propeller does the DMD and sound from
`PRP_Vnnn.BIN` and the SD card. This tool runs the PRG unmodified on
Unicorn and stands in for the Propeller at the packet level.
Plan and findings: `docs/plans/spooky-pinheck-emulator.md`.

```
python -m tools.pinheck_emu.run <GAME_Vnnn.PRG> [seconds] --nvram <dir> --sheet <png> [--quiet]
```

prints every packet the game sends the Propeller and the game's serial
monitor; `--sheet` saves one DMD frame of every video the game played,
drawn from the card's own `DMD/_D?/*.VID`; `--nvram` keeps both EEPROMs
between runs (on a blank one the game behaves as just updated - Domino's
asks for a restart - so run twice). It is headless and silent; it opens no
window and plays nothing. `--closed 32,34,35 --tap coin@14 --tap start@15`
holds switches and presses buttons (Jetsons: a game starts). There is no
live DMD view, text/score overlay, sound, coil/ball model, rig or Emulate
tab yet.

| file | what |
|---|---|
| `pic32.py` | the game CPU: flash/RAM/SFRs, GPIO, UART TX, timers, interrupts (by hand, through an EPC trampoline), I2C1 master, CP0 Count |
| `proplink.py` | the bit-banged PIC <-> Propeller link: framing, the sync handshake, the Propeller-side EEPROM |
| `i2c.py` | the PIC-side I2C chips: 24LC256-style EEPROM (0x50), DS1307-style RTC (0x68) |
| `board.py` | the switch inputs: cabinet shift register (Start, Coin, ...) and the 8x8 playfield matrix |
| `av.py` | the Propeller's picture, high level: video packets -> card files -> DMD frames (via the plugin's `p3_video.py`) |
| `run.py` | boots a PRG with all of the above and logs it |

Status (2026-10-02): Jetsons V004 and Domino's V006 (second boot) run their
attract cycles; the sheets show the real attract art (the Jetsons logo and
"PRESENTS", Domino's "FawzmaGames"). About 1.5x real time (40 s in
26-27 s), with the idle skip in `pic32.py`.

Tests: `tests/test_pinheck_emu.py` (synthetic, no game files).
