# Modes that fire the scoop and the magnet, with hard safety limits (PAD-381)

## The ask

David, 2026-10-04: *"right now, can our custom modes interact with solenoids?
For example: putting the ball in the scoop during a mode, or activating the
magnet? we need to have this flexbiility and access to these controls. However,
we need guardrails on this since these are physical high voltage things and we
can't be breaking anything or causing any fires"*.

Today they cannot. Nothing in `pad_mode.h`, the runtime, `mode_file.c` or any
port names a coil. Modes reach coils only through the game's own code: a
multiball (the trough eject and plunger), a ball save, and the scoop's normal
kick-out.

## What the game does, read from its code (Godzilla Pro 1.16)

Everything here comes from the game's own builders (`armxref.py` on
`gzpro116_stock.elf`), not from captures.

**The coil objects.** `ControlCoil -> HookListener` (vtable 0x6299c8, 59
virtuals) and `GodzillaMagnet -> ControlCoil` (0x629ad8).

| ControlCoil slot | what it does |
|---|---|
| v[29] .. v[32] | pulse power, pulse ms, hold power, hold ms (defaults from the object at +14, +16, +18, +20) |
| v[56] 0x4fe3c | fire: pulse, then hold, with those four |
| v[57] 0x4ff28 | hold only, no pulse; the hold is at least 5500 ms (`cmp #5499; movls #5500`) |
| v[58] 0x4fc7c | off: an all-zero request |

All three go through `0x402ff4 -> 0x4029cc(coil, pulse power, pulse ms, hold
power, hold ms, x ms)`, which stores the request on the coil's record. The coil
service (`0x403df4`) sends it and counts the coil busy for **pulse + hold**,
no longer (`0x403fa0`).

**The wire.** `0x5a995c` serialises a fire:

    8n 0b 40 <coil> <pulse pwr> <pulse t lo hi> <hold pwr> <hold t lo hi> <x lo hi> <cksum> 00

Times are BOARD TICKS, `ms * tps / 1000`. `tps` is the u16 the board claims at
[8..9] of its 0xfe identity reply (`0x5a9164`). So **byte 7 is the hold power**:
0xff on the slingshots and pop bumper, 0 on the plunger and scoop, 0x32 on the
magnet. `x` goes out as pulse power * 256 / x ticks; ControlCoil always passes
0 and its use is not established.

**Off is a different command.** An all-zero request is flagged by `0x4029cc`, and
the service sends `8n 03 4d <coil> <cksum> 00` (`0x5a5be8`). The short
`8n 03 40 <coil>` (`0x5a5b90`) fires a coil by its cmd 41 rule.

MPF's Spike platform (`CoilFireRelease`) lays the 14-byte frame out the same
way. That is agreement, not the evidence.

**What this means for safety.** A hold is bounded by the command that asked for
it. Holding longer means sending again, so a held magnet stays on only while the
game keeps re-sending. If the game process stops, the last hold runs out within
its hold time. That is the game's reading of the board. Nothing in this rig has
watched a real board.

**The magnet is driven by its own process.** `GodzillaMagnet::v[56]` and `v[58]`
do nothing while process 360, 362 or 363 exists (`0x3ab72c` walks the process
list). The magnet's grab, hold and release are a process with its own
adjustments (LO/HI DRAW and HOLD POWER and TIME, RELEASE NUM PULSES, ...). A
plain off is refused while that process runs. A mode's release therefore has to
go through the magnet's own release, not `ControlCoil::v[58]`.

**The board protects itself too.** It reports overcurrent ("Node board error:
overcurrent", error 0xb8; "Overcurrent Detected on this coil!" in the coil
test). This is a last line of defence, not a guardrail of ours.

## The guardrails (none of them trusts the mode file)

1. **Named actions only, never raw coils.** `scoop_eject`, `scoop_hold`,
   `magnet_grab <ms>`, `magnet_release`. Each goes through the game's own
   object, so Stern's pulse and hold settings and the operator's power
   adjustments still apply. A mode never sends a coil index or a power value.
2. **The port decides which coils a mode may touch.** Flippers, trough,
   slingshots and pop bumpers are never on its list.
3. **Hard limits in the runtime that a mode cannot raise:** a ceiling on magnet
   on-time (no longer than the game's own longest grab), a cool-down between
   uses, a cap on fires per minute.
4. **Release on everything:** mode end, ball end, tilt, slam, game end, coin
   door open, a mode file reload, a crash, plus a deadline that releases the
   coil even if the mode stops ticking.
5. **The game always wins.** If one of the game's rules wants that coil (ball
   search, a scoop eject), our action steps aside (PAD-353).

## Done so far

- The frame is decoded from the serialiser. `hwshim.c` `coil_drive_note()`
  publishes each coil's drive in padled v5 (`drive_until`, powers, times in
  ticks, the tick rate). Under `PAD_COIL_PROBE=1` it logs `[coildrive]` lines
  in ms, and an OFF that cuts a hold short says by how much.
  `coildecode.decode()` is its Python twin. `tests/test_spike2_coil_drive.py`
  compiles the real C and holds both to the same frames and offsets.
- **Emulator-proven (2026-10-04, rig slot 1, default Godzilla Pro, ball search:
  trough 66-71 open, Start).** Two runs, the boards claiming 100 and then 1000
  ticks/s:

  | coil | 100 ticks/s | 1000 ticks/s |
  |---|---|---|
  | slings 8:2 8:3, pop 8:7 | pulse 255, 6 ticks; hold 255, 0 | pulse 255, 64 ticks; hold 255, 0 |
  | auto plunger 8:4 | pulse 150, 6 ticks | pulse 150, 64 ticks |
  | right scoop 8:8 | pulse 255, 6 ticks, five times 250 ms apart | pulse 255, 64 ticks, the same |
  | magnet 9:6 | pulse 255, 35; hold 50, 550 | pulse 255, 350; hold 50, 5500 |

  The magnet's 350 ms and 5500 ms are the same at both rates, so the times are
  ms scaled by the claimed rate, as the serialiser says. The ball search's
  magnet grab ends with cmd 4d about 516 ms after it starts (`OFF (cmd 4d),
  5335 ms of its last command left`), plus a second 4d about 517 ms later. The
  64 ms pulses show at 100 ticks/s as 60 ms: the rig's default rate rounds a
  time down to 10 ms.

- **Step 2 (2026-10-05): a mode's own magnet grab, with the limits in the runtime.** What the game's
  magnet does, read from its code:
  - `0x286e00` is get-adjustment. GodzillaMagnet::v[29..32] read the LO or HI draw/hold power and time
    live (363-366 LO, 367-370 HI; the adjustment name table). 343 is GODZILLA MAGNET DISABLED.
  - The game's process calls: create `0x3ab00c`, create-if-absent `0x3ab0fc`, kill `0x3ab37c`, exists
    `0x3ab72c`. The rules start process 363 (entry `0x51dc8`) or 362 (`0x52034`) after `magnet->v[36](3750)`.
    Each loops a tick at a time while game conditions hold (display effects, other processes), pushing
    ball search back, then runs the release `0x51a68`. Nothing in the loop caps the time: PAD-353.
  - `0x514d8` is the game's own release (kills 363/362, coil off).
  - LE 1.16: the same adjustment ids; the magnet is device 13 (Pro: 11); the calls found by code.

  The runtime (`pad_mode_runtime.c` "the magnet"): `pm_magnet_grab(ms)` sends ONE bounded command (LO
  draw power for the draw time, LO hold power for the rest; 100-5000 ms in all), never re-sent; refuses
  outside a game, when disabled, while a game magnet process runs, while holding, within 3 s of the last
  end, past 6 a minute; lets go at its end, on release, mode end, ball end, game end or tilt; steps aside
  without an OFF if the game's magnet starts. Ports: Pro and LE 1.16. `sdk/magnet_test_mode.c` drives it.
  Emulator-proven on the Pro 1.16 card (MODE_SDK.md "The magnet" has every line); desk tests in
  `tests/test_spike2_mode_magnet.py`.

## Next

1. The mode-file key (`magnet <ms>` on a shot) and the Modes tab control, behind the preview code.
2. The scoop: its eject is a ball device of the framework's, not a ControlCoil; find the eject and the
   hold-in-scoop flag (FG_KING_OF_THE_MONSTERS_BOUNTY_COLLECT_HOLD_BALL_IN_SCOOP shows the game has one).
3. A supervised machine test, short grab first.
