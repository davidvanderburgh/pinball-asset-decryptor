# PAD-656: D&D LE's dragon steppers (node 10)

After PAD-654 a game started on D&D LE 1.10, but a Start in attract brought up
"OPERATOR ALERT! Dragon Jam - DEVICE MALFUNCTION": nothing answered the dragon.

## What the wire says

It is not a new protocol. It is PAD-393's board-run stepper (godzilla_le's
building: cmd 32 configure, 34 home, 31 relative move, 38+motor status), here
with two axes (`PAD_NB_TRACE=1`, 2026-10-20):

| frame | what |
|---|---|
| `32 01 c8 e1 00 42 00 ...` | motor 1 = up-down: byte 7 = 0x40\|2 UD HOME, byte 8 = none |
| `32 00 00 e1 00 41 40 ...` | motor 0 = left-right: byte 7 = 0x40\|1 LR HOME, byte 8 = 0x40\|0 LR AWAY |
| `34 01 01`, `34 00 01` | home both, direction 1 (godzilla's building: `34 00 00`) |
| `31 00 +50`, then `31 01 +69` / `31 00 -15` and back, every ~2 s | the attract swing |
| `38`, `39` ~1000 a second | each motor's status: the game's normal rate, not a retry |

The PAD-393 model said no to both axes:
- it took a cmd 32 only with BOTH ends named, so the up-down axis (one switch)
  was never configured and answered zeros for ever;
- it homed every stepper to byte 8 (PAD-393's guess for the building), so the
  left-right axis homed onto LR AWAY;
- it stopped every move at home, keeping positions at or below it (the
  building's floors are negative), so every dragon move (positive) was held
  at 0.

## The rule (stepper_ends)

cmd 34's last byte is the way home: 1 = byte 7's input, 0 = byte 8's. D&D
names its byte 7 switches HOME and homes with 1; the building homes with 0,
which keeps PAD-393's pick (BUILDING UP) exactly. An axis with one input homes
to it. A cmd 32 is a stepper's when either end is an input.

No stop at home any more: positions go either side of it, as the game asks.
The side is the title's, not the direction's - godzilla (0) moves negative,
James Bond 60th LE (0) and the dragon (1) positive - and the game asks only for
places the mechanism can reach.

## Other titles

The wider rule answers three more titles' one-input steppers, unanswered
(zeros) before: James Bond 60th LE (node 6, four motors, byte 8, home 0),
Rush LE (node 10, two, byte 7, home 1) and John Wick LE / Pro (node 13, one,
byte 7, home 1) - all of them consistent with the direction rule. A/B, start
a game and 60 game-s (C:/tmp/PAD-656/ab.sh): no title re-sends a home or a
config in a loop on either side, and all start a game.

## Proof

- `tests/test_spike2_stepper.py`: the real hwshim.c functions fed D&D's own
  frames (both axes home on their HOME inputs, never LR AWAY; +69 lifts off UD
  HOME and -69 lands back), Bond 60th's (byte 8, a +60 move from home) and
  godzilla's (unchanged).
- Emulator, D&D LE 1.10, coin + Start in attract, a picture every 4 game-s for
  2 minutes (C:/tmp/PAD-656/sel.sh): main showed the Dragon Jam alert in 2 of
  2 runs, the branch in 0 of 3. The branch's log: both axes homed, then the
  attract swing with the UD HOME switch opening and closing.
- The whole library (53 newest builds) through startcheck's boot + game start
  on the branch: 53/53.
