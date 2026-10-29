# Spare switches and coils for modes (PAD-826)

## The ask

RobF on Pinside (post #420): *"Do you think it's possible to unmask unused
switches and coils? This could be a mod maker's dream come true."* David,
2026-10-29: tackle it in this ticket.

A mod maker wires a new target to a switch input the game never reads, or a new
coil, flasher or toy to a driver output the game never fires, and a PAD mode
uses it: the switch as a shot, the output held for a moment with the same
limits as the mode coils (PAD-381 / PAD-420).

## What the game does, read from its code

Godzilla Pro 1.15 (`spike2root/games/godzilla_pro/game`) and 1.16
(`godzilla_pro-1_16_0_spike2.raw`). The node-bus library is shared framework
code, so the shapes below should hold on every Spike 2 build. The census
script checks that build by build.

### Switch inputs

Every board's switches come back as 64 bits per node on command 0x11
(`0x59ef60` on 1.15). The switch service `0x1e78f4(node, bits[8])` keeps one
160-byte block per node inside the switch struct (1.15: `0x7a958c`, the struct
hwshim calls SW_STRUCT; +0 is the entry array):

| block offset (from struct + 16 + node*160) | what |
|---|---|
| +12 | the previous 8 bytes of input bits |
| +20 | the current 8 bytes, as read off the board (electrical level) |
| +28 | u16[64]: switch id per input bit; **0 = the game has no switch there** |

The service walks the changed bits and skips every bit whose id is 0, so a
spare input's level is in memory and nothing in the game ever acts on it. A
mode can read it from `+20` without touching the game's switches.

Bit numbering is the switch list's: byte = bit / 8, mask = 1 << (bit % 8)
(Godzilla Pro: node 8 bit 8 = Skill Shot).

### Driver outputs

The coil request (`coil_fire`) only fills the coil's record in the coil table
(1.15: pointer at `0x7bcc98`, count at `0x7e4578`, mutex `0x7bcc9c`). The
coil service thread (`0x403df4` on 1.16) sends the fire frame through
`0x5a9afc(node, spec)`:

    spec: +0 u8 coil, +1 u8 pulse power, +2 u16 pulse ms, +4 u8 hold power,
          +6 u16 hold ms, +8 u16 x (0)

`0x5a995c` turns the ms into board ticks itself (the node's tps from
`0x5a9164`; 0 = the board is not registered and nothing is sent), and builds
`8n 0b 40 <coil> <pp> <pt lo hi> <hp> <ht lo hi> <x lo hi> <ck>`, the frame
hwshim's `[coildrive]` decodes. The frame goes out through the bus transfer
`0x5a3a44`, which takes the bus mutex itself (lock, tcflush, write, read,
unlock), so a game process of ours can call the wrapper directly.

The wrapper refuses any coil above 8 (`ldrb r3,[r1]; cmp r3,#8; bls`), so a
driver board has outputs 0..8 as far as the game's framework goes. A spare
output = a node that has coil records (a driver board) and an index 0..8 that
no record names. Godzilla Pro: node 8 uses 0-8 (none spare), node 9 uses 1, 2,
3, 6, 7 (spare: 0, 4, 5, 8).

The board ends the command by itself at pulse + hold, so one bounded command
of ours needs nothing from the game to stop. No record means the game never
sends that output anything, neither an OFF nor a fire.

## The design

- Port lines, per build, found by `modes/spare_io.py` from the build's own
  binary: `site coil_frame` (the wrapper, its first words checked like every
  site) and `data sw_struct`. Where a port has no `coil_table`/`coil_count`
  yet, the same script adds them.
- Runtime (`pad_mode_runtime.c`):
  - spare outputs are worked out at run time from the coil table (node with
    records, index 0..8 with none), so no list per build can go stale.
  - `pm_spare_coil(node, coil, power, ms)`: ONE bounded command, at most
    5000 ms (the MAGNET_MAX_MS rules: 3 s between, 6 a minute, only while the
    mode runs, in a game, not tilted), refused for an output the game uses.
    Let go early with an all-zero fire (power 0 for 0 ms), as the game's
    OFF.
  - `pm_spare_switch(node, bit)`: 1 closed, 0 open, -1 not a spare input.
    Edges reach a mode as shots ("Spare 9:4"), debounced over two ticks.
    A spare input reads closed when its bit is 0 (Stern's switches are active
    low, hwshim's sw_inactive_level) unless the mode asks for active high.
- Blocks: a "spare switch" shot and a "pulse spare output" action.

## Proof

In the emulator: the spare switch set with PAD_NB_SW reaches the mode as a
shot. The spare output appears in `[coildrive]` as `node N coil M`, with its
time, and nothing of the game's lands on it. Census over every port.

## Where it stands (2026-10-29, end of run 2)

- **Newer framework, 59 builds**: every port has `coil_frame`, `coil_off`, `sw_struct`, `coil_count`,
  `coil_table` (`modes/spare_io.py --write`; `--census` lists them; tests/test_pad826_spare_io.py checks every
  port against the finder when the binaries are in /var/tmp/pad826/elf). The switch service keeps **32** node
  blocks (its mutex follows at +0x1410 = 16 + 32 * 160). A spare input = no id in the map AND no switch entry
  naming that node and bit (Deadpool LE 1.14's 8:14: an entry the map does not route, which read 1 at rest and
  changed in attract - the runtime now walks the entry array too).
- **Proven** in the emulator: Godzilla Pro 1.16 by hand (spare_job.sh) and as a Blocks mode (blocks_job.sh, the
  app's own C); the library by `spare_sweep_job.sh` (rigbatch), whose builds go into mode_project.SPARE_IO_PROVEN.
- **Older framework, 10 builds** (aerosmith_le 1.15, avengers_infinity_le 1.09, batman 1.13, guardians_le 1.14,
  iron_maiden_le 1.16, mando_le 1.44, rush_le 1.18, stranger_things_le 1.12, sword_of_rage_le 1.18, turtles_pro
  1.58): the fire wrapper is there (`site coil_frame` written), but no switch service struct, no 32-byte switch
  entries (findent.py finds none) and no coil table of the newer shape. What is known, Mando LE 1.44:
  - the 0x11 scan is `0x51fdc0` (wrapper `0x51fed0`), called from `0x3a4044(node, ...)`, which hands the 8 bytes
    to `0x453368` and `0x3a3eb0`;
  - `0x3a3eb0`: board object = `[0x743fb0 + 144 + node * 4]`; it stores `scan ^ [board + 584..591]` at
    `board + 576..583` (adds of 572 / 580, +3, then a pre-incrementing walk) and flags `board + 592` on a change; then `0x3a1bb8(board)` processes it;
  - `0x1e396c(node, bits)`: a listener table at `0x6b47bc` (+268 count, +12 entries of 8 bytes: [0] -> a record
    whose byte 0 is the node, [4] -> a list of listeners with +16/+17 previous/current level, +8/+12 counts).
  Left: which (node, bit) the game uses there (the listener records), and the coil records' shape (for the OFF
  wrapper too: `coil_off` was not found on them).
  - Outputs on the older framework (Mando LE 1.44): `0x3a1c6c(node, coil, pulse power, pulse ms, hold power, hold
    ms)` is its fire by address (refuses node > 30, coil > 8; fills the spec and calls the wrapper `0x5246f4`);
    `0x3a1710(node, coil)` is "the game has a coil there": it walks the device records (`[0x665674]`, 56 bytes
    each, count `[0x6b8be8]`; +32 the device id -> `0x20a624` -> +20 kind (2 = coil), +18 its index, +16 ->
    `0x416a8c` -> +14 the node) - a pure query, usable as `site coil_used`. The newer framework's board test calls
    the same kind of query (`0x1d5414` on Godzilla Pro 1.15). There is NO OFF frame on these builds (no
    `mov rX,#0x4d` into a frame anywhere): the runtime's OFF there is the fire with every power and time 0, which
    hwshim's [coildrive] reads as off.
  - Inputs on the older framework: the board's bits are at `board + 576` (`board = [0x743fb0 + 144 + node * 4]`),
    already XORed with the board's per-bit mask at +584. "The game has a switch there" is still to find: the same
    device records with the switch kind are the likely route.
  - The older framework's switches (Mando LE 1.44, the registration at `0x1e3100`): switch records `[0x663e8c]`,
    44 bytes each, count `[0x6b4f28]`; record +26 the device id -> `0x20a624` -> +20 its input (refused when 0 or
    at/above `[0x577fd8]`), +16 -> `0x416a8c` -> +14 the node; each is appended to its node's entry in the listener
    table (`0x6b47bc`, +12: 8-byte entries [board record, list]). So "the game has a switch there" = some switch
    record with that node and input. Next: the numbering of +20 against the bits at board + 576 (a known switch of
    the switch list, e.g. a flipper button, pressed in the emulator), then the finder (the registration's two
    movw/movt tables and the 44/56 strides) over the ten builds.
