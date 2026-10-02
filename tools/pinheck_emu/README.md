# pinHeck game-CPU emulator (PAD-320, work in progress)

Spooky's DMD games (America's Most Haunted, Rob Zombie's Spookshow
International, Domino's Spectacular Pinball Adventure, Jetsons) run on Ben
Heck's **pinHeck System**: a PIC32MX795F512L runs the game from
`<GAME>_Vnnn.PRG`, and a Parallax Propeller does the DMD and sound from
`PRP_Vnnn.BIN` and the SD card. This tool runs the PRG unmodified on
Unicorn and stands in for the Propeller at the packet level.
Plan and findings: `docs/plans/spooky-pinheck-emulator.md`.

**To play**: the Emulate tab (Spooky Pinball) - pick `Jetsons_Code.zip`,
`DOM_v6.zip` or `rzupdate_V26.zip` (or a game's PRG) and Start; the game
opens in its own window: the DMD, Coin / Start / flippers / Launch or
Plunge / Drain / Tilt and the service buttons (keys 5, 1, Z, /, Enter,
Space, D, T, M, E), every playfield switch (click a hit, right-click to hold),
the lamps, the scores, the coils firing, the sound (following the app's
Volume / Mute), Pause and Power cycle. Or run the window directly:

```
python tools/pinheck_emu/window.py <update.zip | GAME_Vnnn.PRG> [--mute]
```

Domino's and Rob Zombie ask for a restart on their very first boot (a blank
EEPROM looks like a fresh update): press Power cycle. Their EEPROMs and the
unpacked zip live under `%LOCALAPPDATA%\PinballAssetDecryptor\pinheck`.

Headless, for tests and reverse engineering:

```
python -m tools.pinheck_emu.run <GAME_Vnnn.PRG> [seconds] --nvram <dir> --sheet <png> [--quiet]
```

prints every packet the game sends the Propeller and the game's serial
monitor; `--sheet` saves one frame of every video played, `--frames`
the screen every N seconds, `--sound-log` what started and how loud (mixed,
never played); `--closed` / `--tap` hold switches and press buttons.

| file | what |
|---|---|
| `pic32.py` | the game CPU on Unicorn: flash/RAM/SFRs, GPIO, UART, timers, interrupts (through an EPC trampoline), I2C1, CP0 Count, the idle skip |
| `proplink.py` | the PIC <-> Propeller link: framing, the sync handshake, the Propeller-side EEPROM |
| `i2c.py` | the PIC-side I2C chips: 24LC256-style EEPROM (0x50), DS1307-style RTC (0x68) |
| `board.py` | switches (cabinet shift register, 8x8 matrix), the balls (trough, shooter lane, play, drain on the game's coils), the lamps |
| `games.py` | per game: coil names (from each game's SOLENOID TEST), trough, shooter, launch |
| `av.py` | the Propeller's picture: videos from the card (two layouts), text, scores |
| `tinyfont.py` | a 3x5 font standing in for the colour games' .FNT fonts |
| `audio.py` | the Propeller's sound: a mixer of the card's wavs |
| `machine.py` | a game in real time on a thread, for the window |
| `window.py`, `page/` | the game window (the rig windows' web host, tools/spike2_emu/pfweb.py) |
| `run.py` | headless runs |

Status (2026-10-02): Jetsons V004, Domino's V006 and Rob Zombie V26 boot,
run attract and play - coins, Start, the ball served by the game's own
coils, launched, scored, drained and re-served - at real time with sound.
Approximate, from watching the games rather than the Propeller's code: the
colour games' video slots, text positions and font, scores (listed beside
the DMD, not drawn on it), and the commands not decoded (sprites, numbers,
0x04, 0x0a, 0x0c ...). America's Most Haunted cannot run: its update holds
no game program. See docs/plans/spooky-pinheck-emulator.md.

Tests: `tests/test_pinheck_emu.py` (synthetic, no game files) and
`tests/test_webui_emulate_spooky.py`.
