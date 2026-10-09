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

- **Step 3 (2026-10-05): the mode file, the tab, and a grab that actually holds.**
  - `magnet <ms> [mask]` in a mode file: while the mode runs, every hit of the port's `value magnet_shot`
    (the Godzilla target: the device nearest the magnet on the playfield picture, 6 px) holds the ball for
    `<ms>`, the starting hit included, through `pm_magnet_grab`. Mode > Magnet on the Modes tab (seconds,
    0.1-5), greyed per build until `MAGNET_PROVEN`; `magnet_ms` in the mode's JSON. The tab sits behind the
    preview code with the rest of the Modes tab.
  - **The first grab never held.** Proving the mode file in the emulator, `[coildrive]` showed the game's
    OFF 1 ms after every grab (step 2's proof had read only the runtime's log). A call probe with return
    addresses named it: ControlCoil::v[38] (`0x4ffc8`, the coil's update, run on events such as a target
    hit) switches a coil off (v[54] -> v[58] -> cmd 4d) unless a game PROCESS controls it (+44) or an
    on-time was asked for (+36, `v[36]`). The game's own grabs take control from a process.
  - So the grab is now a game process of ours (`value magnet_proc` 13185, used by no create/exists/kill
    call in either program): create-if-absent `0x3ab0fc`, take control `0x5079c`, one bounded command,
    sleep `0x3ab22c` a tick at a time, give control back `0x50860` (the game's update then switches the
    magnet off). The on-time route was rejected: `v[55]` re-fires the operator's pulse and hold while an
    on-time is set ("held until told").
  - **The game ends a process by throwing through its stack** (`do_stack_unwind_exception_t`, at a drain
    or a tilt; kill-all masks 0x100/0x200/0x400/0x80/0x1000). Our frame had no unwind tables and the first
    drain test ABORTED the game. `build_mode.sh` now compiles with `-funwind-tables` (an EXIDX segment);
    the same drain then ended the grab's process cleanly and the exit hook switched the magnet off.
  - Emulator-proven on the stock Pro 1.16 and Premium/LE 1.16 cards (MODE_SDK.md "The magnet"): held to
    its end, a mid-grab hit refused with no game OFF, a mode stop and a drain mid-grab let go early, no
    abort; on the LE a game magnet process started by the first hit made the grab stand aside.

- **Step 4 (2026-10-05): a ball held in the scoop.** The scoop is a framework ball device; its game process
  calls the GAME's handler (`0x7cd94`, `right_scoop_event_handler`) through a pointer in the device record
  (`0x74b480`, RW data) with an event in r0. A call probe on a landing ball: 21 switch closed, **2 settled**
  (the game's own hold loops there), 13 a display wait, 16/17 the kick (coil_fire(10, adj 351, 64 ms); every
  adj-352th retry a burst of five), 18 gone. The runtime swaps the pointer (checked first) for a wrapper that
  runs the handler and then, on event 2, sleeps in the device's own process for the mode's hold (100-10000 ms)
  - so the kick-out stays the game's and nothing fires a coil. `pm_scoop_hold` / `pm_scoop_release`, a mode
  file's `scoop_hold <ms>`, Mode > Scoop on the tab; `SCOOP_PROVEN` = Pro and LE 1.16. LE: handler `0x7d8e4`,
  slot `0x7570a4`. Emulator: control 1782/1785 ms to the kick, hold 4000 -> 5776/5770, a mode stop and a tilt
  let go, no abort (MODE_SDK.md "The scoop").

- **Step 5 (2026-10-05): the Premium's other coils - Mechagodzilla magnet and bridge.** The magnet's runtime
  became a table of held coils the port names (`text held_coils`), one code path and one set of limits; the powers
  come from the coil object's own v[29..31]. Premium/LE: MechagodzillaMagnet (device 14, getter `0x1d9410`, adj
  380-383; the shield rule grabs with it, `v[36](1875)`), BridgeDiverter (device 12, getter `0x1d7174`, 255 for
  300 ms then 25). `coil_hold <name> <ms> [mask]`, Mode > Other mechanisms. Emulator-proven (9ee4ab1a).

- **Step 6 (PAD-395, 2026-10-05): blocks.** A blocks mode has a Mechanisms group: *Hold the <mechanism> for N
  ms* (`pm_coil_hold`, any value, clamped to 100-5000 in the C and again by the runtime), *Hold the next ball /
  every ball in the scoop for N ms* (`pm_scoop_hold`; "the next ball" switches the hold off once that ball has
  been held and gone, watched each tick through `pm_scoop_holding`), and *Let go of* one mechanism, the scoop,
  or everything it holds. The mechanisms offered are the form's: the magnet where `can("magnet")`, the port's
  proven held coils where `can("coils")`; the scoop where `can("scoop")`. Elsewhere the palette greys the block
  with the form's reason, and a saved block naming one is a problem. Every other limit stays the runtime's.
  The desk harness models the holds (its limits, `scoop`, `HOLD`/`LET GO`/`SCOOP` lines).
  Emulator-proven on the stock Premium/LE 1.16 card (rig 1, hidden, muted, `PAD_COIL_PROBE=1`), a blocks mode
  started by its trigger: the Mechagodzilla magnet held 2000 ms as it started (`[coildrive]` node 9 coil 7: 255
  for 250 ms then 80 for 1750, OFF at its end); the next ball in the scoop held 4012 ms and then kicked by the
  game (node 8 coil 8), the hold switched off after it ("scoop: no hold"), and the next landing kicked at the
  game's own time; a Maser target hit asked for the magnet and stood aside for the game's magnet process (as in
  every LE emulator run), a second hit refused; the bridge held (255 for 300 ms then 25) and Let go of
  everything cut it with 1115 ms left; no abort.

- **The shield and the building: what is known, nothing shipped.**
  - Shield: ShieldMotor -> SingleDirectionCoilMotor (node 9 coil 2), a static object at `0x7bbf88` (vptr
    `0x6502a8`), run to SHIELD MOTOR OPEN (86, matrix 41) or CLOSED (87, matrix 42). The rig already models it
    (the shim's coil-motor: `[motor] node 9 coil 2: runs until input 22`). `0x1da004(obj, sw)` is NOT a move: it is
    called by the OPEN/CLOSED SWITCH HANDLERS (`0x18db10` / `0x18db44`, in the switch table at `0x777870`) and
    records the position reached (+50), then restarts process 200/201. A first attempt called it as a move: the
    emulator showed no motor run, the code was withdrawn (scratch patch kept). The move looks like
    `ShieldMotor::v[16](obj, position switch)` (its self-test `0x1d99b4` loops the position table at `0x650330`
    with it); motors also need process CONTROL ("caller not a process", "control function called without
    control") - find the motor's take/give like the coils' `0x508ec`/`0x509b0`. The shield rule reads +44 == 87.
  - Building: BuildingStepper -> StepperMotor (`0x7bbe64`), BUILDING UP/DOWN switches 92/93 on node 10. The game
    polls it ~2000 times a run and never moved it in the rig: the rig most likely does not model this stepper,
    so it needs an emulator model before anything can be proven.

- **Step 7 (PAD-393, 2026-10-05): the building.** The rig did not model the stepper: with the zero reply the
  game re-sent its HOME (`34 00 00`) ~3600 times a run, polled the status (`38`) ~42000 times and never sent a
  move. The board's commands, read from LE 1.16: 32 configure (byte 7 = 0x40|input of 93 DOWN, byte 8 = of 92
  UP), 34 home, 31 a relative move (s16 steps, then speed/accel/decel u32s), 38+motor status -> u16, u16,
  flags (0x02 moving, 0x04 homed, 0x08/0x10 fault). hwshim.c now plays it (home = BUILDING UP, a guess; 5000
  steps/s; `PAD_STEPPER=0` off). The game's floors (`0x1d77d8`): 0 beside home (-bias, -150 on a stock card),
  1..3 2500/5000/7500 steps further. The game moves it with `0x1d79fc(obj, floor)` (a target and the speed
  adjustments, no process control); its update sends the steps. `pm_building(floor)` / `pm_building_floor()`
  with the coils' limits, and a put-back at the mode/ball/game end. Emulator-proven on LE 1.16 (MODE_SDK.md
  "The building"); no mode file keyword or Modes-tab control yet; not machine-tested.
- **PAD-394 (2026-10-05): the other titles.** Godzilla Pro 1.15 gets the magnet and the scoop (drafted from Pro
  1.16; emulator-proven); King Kong LE 0.97 and Jaws LE 1.02, whose ControlCoil is Godzilla's, get held coils (the
  spider magnet and two diverters; the inlane up posts; emulator-proven). The census of every other build, the
  generations that cannot follow yet and why: `docs/plans/mode_coils_census.md`.
- **Step 8 (PAD-392, 2026-10-06): the shield, from the form and from blocks.** PAD-379's `pm_shield` asked the
  game's own motor go-to with no limit of ours. Measured first (`shield_test_mode.c`, stock LE 1.16): with the
  game's rules seeing shots, the game turned the platform back AWAY about 2 s after every move of ours, hit or no
  hit, and again 1.4 s after our mode ended - its Mechagodzilla Shield feature (kept counting under a blocking
  mode, it did the same); with the rules blind (PAD-398's default) the platform stayed toward 17 s through shots
  and hits on all three shield targets (switches 89/90/91: 0x80000000, 0x100000000, 0x200000000). The game's
  ball search (every 12 s while no switch closes) swings it toward and away and leaves it away. So: `pm_shield`
  gets the runtime's limits (the running mode, in a game, never while a game mode or multiball runs, 1.5 s
  between moves, 12 a minute) and a put-back at the mode/ball/game end unless the game has turned it since;
  `pm_shield_keep(where)` keeps it - turned back 1.5 s after the game left it elsewhere - only while the port's
  `text shield_rule` feature sees no shots, and otherwise turns once and leaves it to the game. Form modes: the
  Modes tab's Shield targets ("Turn the shield targets toward the player while it runs", mode file `shield
  toward`, turned 1.5 s after the start as the kit does); blocks: Turn the shield targets toward the player /
  away / where they are. Both refused (`validate`, `problems`) unless the game's modes cannot start and the
  shield feature is not kept counting. Emulator-proven (rig 1, muted, hidden): a form mode turned it 1.5 s after
  its start and kept it toward for 18.5 s through six shield-target hits (all six scored), then put it back
  AWAY; a blocks mode turned it, turned it back once after the game swung it, stopped keeping it with 20 s
  left, and at time up found the game had moved it and left it there; the ball ending put it back; no abort.
- **Machine test and PAD-409 (2026-10-06): the game's background return to rest.** On David's Premium the
  shield turned in every mode that asked and was put back at every end, but the game flipped it back 2-3 times
  early in each mode - "it looked bad on the playfield ... doesn't give us real control of the mech. better to
  not physically break it though". A watcher hook on the go-to (callers by return address), then on the list it
  runs (0x1dae20, reached from the game's UpdateObject loop every ~3 s), found the job: the shield motor's own
  `v[0]` (0x1da978 -> SingleDirectionCoilMotor update 0x1db830). Unless a motor process owns the motor (+60),
  it asks `v[1]` (0x1d9c24) for the resting place - picked from the game's rules (rule 1's state: AWAY, or
  TOWARD in parts of Mechagodzilla; a fresh game has none, which is why the first proofs held) - and sends the
  platform there. Faking the owner was ruled out (the game's own motor processes check it and would skip
  themselves); instead the runtime skips that one pass for the shield motor while a mode of ours has moved it,
  not during the game's modes or multiballs, and ends the hold the moment the mode, ball or game ends. Emulator:
  after 30 spins, kept toward 30 s (before: turned back every ~3 s); only the ball search's 12 s jiggles moved it.

- **Step 9 (PAD-414, 2026-10-06): the shaker.** David: "We also should be able to have control over Shaker motor
  effects"; his Premium has one fitted. Read from LE 1.16 (no class: a plain drive). Every shake of the game's goes
  through one call, `shake(ms, strength, force)` (`0x189a54`): it reads adjustment 335 (AD_SHAKER_MOTOR, 0 off .. 4),
  cuts the time to that setting's table (`0x6487f4`: 0/100/334/500/5000 ms; past 4 is error 317, the "shake duration
  out of range" assert), does nothing unforced while the mode mask has 0x310, nothing when what is left of the running
  shake is longer, then `coil_fire(7, power, ms)` at the strength's power (`0x648808`: 51/36/31/23/3). Drive 7 is the
  SHAKER MOTOR device record (board index 5 coil 0: the cabinet board, beside the coin and ticket meters on coils 2
  and 3). `0x189b08` stops it (an OFF). A census of the ~340 calls (with their classes and strings) named the game's
  shakes: 200 ms at 0 on a battle's or multiball's shot, 334 ms at 0 on a bigger one, 500 ms at 0 on every super
  jackpot and Destruction Jackpot, 3000 ms at 3 in O2 Destroyer, the Godzilla Multiball start's five (its video at
  0.27-4.0 s: 334/100/500/1000/5000 ms at 2), and video-timed sequences (the 0x42xxx and 0x47axx process scripts).
  Strength 0 and 1 never run past 1000 ms; 2 and 3 to 5000. Pro 1.16 has the same call (not ported).
  - The runtime ("the shaker"): `pm_shake(ms, strength)`, `pm_shake_game(name)` (the port's `text shake_<name>`
    steps, later ones sent by the tick), `pm_shake_stop`, `pm_shaking`, `pm_shake_outlast`. Limits: the game's own
    call only, never forced (so the operator's setting always applies); the running mode, in a game; refused with the
    setting 0, over the game's own shake (`drive_left`, `0x3e8bcc`) or one of the mode's; 100 ms .. the game's own
    longest at that strength; 20 shakes and 15 s of shaking a minute; the game's own stop at the mode, ball or game
    end - unless the game has asked for a longer one since, and except the mode's ending shake (outlast).
  - The drive's time left reads 0 straight after the call (the game's coil service sends the request a moment later),
    so the first run thought no shake was running and the stop never fired; the runtime now counts its shake from
    the request, cut to the setting (`text shake_setting_ms`).
  - Mode file `shake start|shot|end <ms> <strength> [mask]` / `... game <name> [mask]`; Mode > Shaker on the form
    (`shakes`); blocks *Shake the cabinet for N ms* and *Shake it the game's way* (in When the mode ends, it runs
    out); MECHAGODZILLA's example starts with the multiball start and shakes the jackpot on the Godzilla target;
    `final_wars.c` and `destoroyah.c` shake their jackpots. `SHAKER_PROVEN` = LE 1.16.
  - Emulator-proven (rig 1, stock LE card, muted, hidden, `PAD_COIL_PROBE=1`): every shake reached the board as
    `[coildrive] node 1 coil 0` at the strength's power for the time asked (3000 at 0 cut to 1000); the multiball
    start's steps on time; `pm_end` mid-shake sent the game's OFF with 4001 ms left; refusals as designed; a mode
    file's and a blocks mode's start/shot/end shakes, the end one running out after the END with no OFF.
  - Owed: a machine test on David's Premium (how hard each strength feels; that SHAKER MOTOR is on there).
  - Seen on the rig (PAD-424): the virtual playfield's side panel has a SHAKER MOTOR box - SHAKING/IDLE, a 60 fps
    scrolling trace of the drive power (padled v5's drive table, `coilmap.drive`), time left, shakes this run - and
    the playfield picture jiggles while it runs. The coil is the table's SHAKER MOTOR row, else group 5 index 0 when
    the table has no group 5 at all (godzilla), none on the Home Editions (`coilmap.shaker_address`).
  - PAD-474 (2026-10-09): the same routine on every other latest build with a shaker, read by `shaker_lines.py`,
    in three shapes (`text shake_call`); all 20 emulator-proven - docs/plans/pad474_shaker.md.

## Machine test (2026-10-05, David's Godzilla Premium 1.16)

His card's p2 was backed up, the branch's pinned `mode.so`, its `godzilla_le-1.16.port` and one mode file from
`runtime_cfg` put on it with `mode_install.py`, written back over the p2 range and read back by SHA-256; each
round's exact files ran in the emulator first. The results come from the card's `/dump/mode.log`.

- **Round 1 (1 s holds; the mode started on the Maser target, 90 s):** nothing seen. The log: the first game
  never hit the Maser target, so the mode never ran; in the second it ran 27 s before the drain. In that time
  the Mechagodzilla magnet (twice, at the starts) and the Godzilla magnet (once) were held 1 s and let go on
  time; the left ramp and the scoop were not hit. The test, not the code, failed: it needed a shot to start,
  showed nothing on the glass, ended at the drain, and a magnet with no ball near it does nothing visible.
- **Round 2 (the first slingshot of every ball starts it, it runs to the drain; magnets 2 s, bridge 3 s, scoop
  5 s):** two runs (230 s and 66 s), each started by the ball on a slingshot. Held and let go on time: the
  bridge 8 times (3000-3019 ms), the Mechagodzilla magnet 4 times (2000-2016 ms; two at the starts, two on the
  building), the Godzilla magnet 3 times (2000-2004 ms), a ball in the scoop once (5021 ms). Refused as
  designed: a building hit mid-hold ("a grab is already holding"), three Godzilla target hits while the game's
  own magnet worked, and one grab that stood aside before it began because the game wanted the magnet. Both runs
  ended at the drain. David: the bridge, the scoop and the magnet "seemed to work".

Learned: the game's own magnet process on a Premium is busy only some of the time (in the LE emulator it was
busy on every hit), so the Godzilla target grab does happen on a Premium. Not covered on the machine: a drain
or tilt in the middle of a hold (both drains came between holds); the emulator's drain proof stands.

## Next

1. Done: the supervised machine test (above). Then the card goes back to David's own modes (p2 restored from
   the backup).
2. Shield: done in the emulator (step 8), through the motor's own go-to rather than a take-control: the game
   keeps no hold on the motor between moves, and its own feature that moves it is blind while ours blocks. Owed:
   a machine test (the platform with a ball on it, the real turn time).
3. Building: done in the emulator (step 6). Owed: a machine test (which switch is home, the real speed,
   whether a move with balls locked in the building is safe for the game's lock count), then a mode file
   keyword and a Modes-tab control.
