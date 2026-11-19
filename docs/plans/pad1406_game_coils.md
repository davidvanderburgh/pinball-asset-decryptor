# PAD-1406: the game's coils for a mode that is the whole game

Row 11 of the PAD-1398 gap analysis (docs/plans/pad1398_xmen20_gap_analysis.md). A mode that is the whole game
(PAD-1400, `pm_own_game`) has switched off the rules that drive the game's devices, so it needs safe routes to them,
through Stern's own device code and never raw pulses: flippers on/off, ball lock hold/release and eject, kickbacks,
diverters, and toys (X-Men's Sentinel bash toy, the magnet beyond 5 s holds), each within the limits the game's own
drivers set. Every Spike 2 game and version, LE/Pro parity, proven in the emulator; X-Men LE/Pro 0.98 first.

## Done (run 1): the flippers

- **Sites on every newest build.** PAD-733's framework pair (`site flippers_off` / `flippers_on`, Godzilla 1.16 only
  until now) placed on the other 51 newest builds by portgen.locate, strict (only branch and literal offsets
  masked), every pair 0xd4 apart; checked against each program (tests/test_pad1406_flippers.py: the off clears bit 2
  of each flipper record's u16 at +6, `bic r3,r3,#2`; the on sets 6, `orr r3,r3,#6`). Recipes regenerated, so ports
  derived on a user's machine from a newest build's recipe get them too. Uncanny X-Men LE 0.98 0x38a114 / 0x38a1e8,
  Pro 0x3ca20c / 0x3ca2e0. Scratch: C:/tmp/PAD-1406/locate_site.py.
- **`pm_flippers(on)` / `pm_flippers_off()`** (pad_mode.h; pad_mode_runtime.c "PAD-1406: the flippers"). Only the
  mode that has the whole game, in a game, not tilted, not during a drain to one; on undoes only a mode's off; off is
  re-applied each tick (the game's status updates re-enable them); back on when the mode ends or gives the rules
  back mid-ball; at a ball's end the game's next ball start brings them back; a tilt leaves them to the game.
- **Blocks**: Mechanisms > *Flippers off* / *Flippers back on* (`{"op": "flippers", "to": "off"|"on"}` ->
  `pm_flippers(0|1)`); refused by the checks outside a whole-game mode and on a card whose port lacks the sites
  (`Profile.flippers`, the server's `flippers_off` reason).
- **Drain to one** (`pm_drain_to_one`) uses the same pair; it now also waits on `value shooter_lane_switch` (Godzilla
  1.16 only): on Uncanny X-Men Pro, with the pair but no shooter lane switch, the served ball sat in the lane with the
  flippers dead until the 30 s cap (emulator). It is lifted per build once the switch names below are read.

**Proof** (emulator, hidden, muted, 4x; C:/tmp/PAD-1406 flipproof.c, flipjob.sh, verdict.py, snaprules.py): a C
mode takes the whole game; trigger files switch the flippers; every coil's board rule (padled v7, cmd 41) is read
before, off, on, off again and after `pm_own_game(0)`. X-Men LE and Pro 0.98: coils 8.0, 8.5, 8.6 (inputs 24, 25, 27:
the flipper buttons) go to power 0 with the flippers off and come back on; no other rule changes; an on before any
off is refused. Library sweep: below.

## Next (runs 2+), in this order

1. **Switch names at run time.** The game builds its switch table on the heap (mktables.py); the shim already reads
   names from it. A runtime reader of the switch descriptors' names (per framework generation, as the switch-edge
   lines are) gives each build its SHOOTER LANE, TROUGH n and lock/kickback switches with no per-port value: lifts
   the drain-to-one gate on every title and feeds 2 and 3.
2. **Ball devices: hold, release, eject.** MODE_LIMITS today: in a whole-game mode a ball in a scoop or lock stays
   until ball search frees it. The framework's ball devices call the game's handler with events (21 switch closed,
   2 settled, 16/17 kick, 18 left: the scoop hold, mode_coils.md); the eject is the device's own (its retries, its
   power adjustment). Generalise the scoop wrap to every ball device record the framework lists, and add the device's
   own eject request: `pm_device_hold(name, on)`, `pm_device_eject(name, n)`.
3. **Kickbacks**: the game's own enable/disable (Godzilla's dead-flipper feature turns kickbacks, pops and slings off
   at 0x3f04cc beside the flipper pair: find the framework's per-kind switch and the kickback's own enable).
4. **Diverters, posts, magnets beyond 5 s**: the held-coil route (PAD-381/420) with a whole-game mode's cap raised
   to the game's own longest command on that coil (`<name>_max_ms`, or the drive's last word), never past it.
5. **Toys**: X-Men's Sentinel bash toy and the other titles' toys through their own device objects (census as
   mode_coils_census.md did for held coils).

The older archival versions (not the newest build of their title) carry none of these lines: their cards are not
read (as PAD-1400); a port derived from a user's own older card gets them where its newest build's recipe places them.
