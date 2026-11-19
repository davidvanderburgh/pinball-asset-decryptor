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
off is refused. **Library sweep: all 53 newest builds pass** (2 to 4 flipper rules each: 21 builds 8.0/8.5, 12
8.0/8.5/8.7, 11 8.0/8.5/8.6, 9 all four; King Kong LE crashed once in boot, before any game, and passed on its rerun;
the first sweep's King Kong Pro start-of-game crash did not repeat either). Two findings on the way:

- **D&D LE/Pro 1.10 and Metallica 1.04 clear a rule with the short frame** `41 <coil>` (`88 03 41 05 2f 00`), where
  X-Men sends the whole rule with power 0 (PAD_NB_TRACE). hwshim's rule table (padled v7, which the VPX bridge reads
  for live coils too) never saw those clears: `coil_rule_note` takes the short form now.
- **Metallica's own flipper policy turned them back on.** The framework re-decides each flipper by asking its listeners
  (bus hook 0x40; answer 1 off, 2 on; X-Men LE 0x38a260 = flippers_on + 0x78), and Metallica's listener says on: with
  the runtime switching them off each tick, its flipper board got ~950 off/on rule pairs a second and the flippers
  stayed live. `site flipper_query_call` (that policy's call, flippers_on + 0xbc, on all 53) is wrapped by the runtime,
  which answers 1 while a mode has them off - the game's own decision route, no fight.

## Done (run 2): X-Men's own devices

The framework's ball-device table on X-Men (the balls-in-play count walks it: Pro count `0x5305c8`, 40-byte entries at
`0x60a9cc`; LE `0x539460` / `0x614f00`) holds only TROUGH and AUTO PLUNGER (devprobe.c in the emulator): X-Men has no
framework lock or scoop. Its toys are its own classes (Device_Cerebro, Sentinel_Jaw/Hand/Finger/Head_Motor/
Kicking_Target, Magnet, Ramp_Diverter, Right_Return_Post), each driven by coil_fire at the operator's adjustments.
From the coil_fire calls that read those adjustments (C:/tmp/PAD-1406/firescan.py) and the board addresses in the
game's own coil records (devprobe ctab):

| device | LE adj | Pro adj | device id | board | longest |
|---|---|---|---|---|---|
| Cerebro post | 171-174 | 171-174 | 16 / 14 | 9.6 | 3500 ms |
| Sentinel jaw | 188-191 | 175-178 | 11 | 9.2 | 5000 ms |
| Sentinel hand ramp | 176-179 | - | 18 | 9.7 | 3000 ms |
| Sentinel finger | 180-186 | - | 15 | 9.8 | 3000 ms |
| Sentinel kicking target (bash toy, one pulse) | 192-194 | 179-181 | 12 | 9.3 | pulse |

- Held coils marked `value <name>_own_game 1`: pm_coil_hold refuses them to any mode but the whole game's
  (COILS_MAX 6 -> 10). Profile.own_game_coils (OWN_GAME_COILS_PROVEN); the Blocks Hold list shows them "(whole game)".
- `pm_coil_pulse(name)`: the game's own fire function (`site sentinel_kick_fire`, LE 0x337dc, Pro 0x30148), whole
  game only, 1 s apart, 20 a minute, the operator's disabled honoured. Profile.pulse_coils; Blocks *Fire the ...*.
- The magnet stays at the game's own longest command (LE 2.5 s, Pro 1.2 s): "beyond 5 s" is not the game's own.

Proof (coiljob.sh, PAD_COIL_PROBE): LE and Pro, each hold ONE command at the game's powers on its board address
([coildrive] 9.6 128/82 ms then 82 for 3410 ms; 9.2 192/60 then 56; LE 9.7, 9.8), capped at the game's longest; the
kick 255 for 60 ms on 9.3 twice, a second one at once refused; both refused once the mode gave the rules back.

## Done (run 3): switches by the game's own name; drain to one on every build

- `sw_by_name(name)` / `sw_level(id)` (pad_mode_runtime.c, before the PAD-733 section): the game's own switch entries
  (`data sw_struct` -> the entries, SW_ENT bytes each by id) name themselves - device pointer (SW_ENT_P2) +16 the name's
  language row, its first word the English name, as hwshim's [sw] dump reads it; compared upper-cased (X-Men: "Shooter
  Lane", "Trough 1"). SW_ENT_LEVEL is the logical level.
- Drain to one: the shooter lane is the port's `value shooter_lane_switch`, else the game's "Shooter Lane" / "Shooter
  Lane Opto"; with no Trough shot the trough is "Trough 1".."Trough 6" read as levels (a change = a ball home), and the
  shooter lane's rises are counted from its level where the edge hook counts no hits. The run-1 gate is gone.
- Sweep (flipjob.sh: flippers + a 2-ball multiball drained to one, drained a ball at a time): 52 of 53 newest builds
  pass with the drain to one over by the last ball home or the served ball, never the 30 s cap. Dungeons & Dragons LE:
  its flippers pass, the drain to one starts with dead flippers, but the rig's ball feed cannot finish it (plunge.py
  says a ball is in play, drain says one sits in the shooter lane - its dragon lock in the rig's ball model); the 30 s
  cap brought the flippers back there. D&D Pro, the same code, passes. King Kong LE crashed once in boot again and
  passed on its rerun.

## Done (run 4): the game's ball devices - locks, scoops, ejects

- Every build's framework ball-device table (the balls-in-play count's: `data ball_devices`, 40-byte entries; `data
  ball_device_count`) is static data: each entry +0 the device object (+0x19 the balls it keeps, +0x1a the balls in
  it), +8 its ball switches, +0x1c its name, +0x24 its kind, +0x25 its capacity. Survey (C:/tmp/PAD-1406 devnames.py):
  92 lockable devices across the 53 newest builds; X-Men, Jaws, Beatles, Avengers Pro, Iron Maiden Pro, Jurassic Park
  Pro, Sword of Rage Pro and Foo Fighters have none the call takes.
- The game holds and lets go of them through ONE framework call, keep(device, n, 1) (`site ball_device_keep`,
  Turtles Pro 0x16b044, placed on the other 52 by code, its device-count address checked against each build's table):
  keep n, the rest ejected the device's own way. Its own jump table takes kinds 2, 3, 6, 8 on every build (VUKs that
  cannot hold are other kinds).
- `pm_device_keep(name, n)` / `pm_device_balls` / `pm_device_known`; whole game only, never the trough or the plunger;
  the game's keep put back at the mode's end. Ports name the devices (`text ball_device_names`); Profile.ball_devices
  (virtual vapor/jam devices left out); Blocks *Hold the balls in* / *Let go of the balls in*.
- Proof: Godzilla Pro's scoop held 22 s under keep 1 (no kick), then kicked at the game's power on keep 0; Turtles
  Pro's upper lock: keep 0 fired its release (coil 8.8) that never fired while held; every allowed device of all 53
  newest builds held and let go with the game running on (lockall.sh, 53/53).

## Done (run 5): kickbacks

- The framework's tilt/dead-flipper all-off switches three kinds (kinds.py): kickbacks, pops, slings, each a list with a
  static count. Kickbacks exist only on Guardians of the Galaxy Pro and LE 1.15 (two each); Sword of Rage's is a rule of
  its own, Bond's "kick back" names eject powers, Iron Maiden's is an up post.
- `site kickback_set` (set(index, on, 0): the record's enable byte, answering the old one; LE 0x21c25c, Pro 0x39effc),
  `data kickback_count`. pm_kickback(on) / pm_kickback_known; whole game only; each saved and put back at the mode's end.
  Profile.kickbacks; Blocks Kickbacks on / off.
- Proof (kbjob.sh): Guardians LE and Pro - rule 8.6 (input 12, off as the game had it) and 9.8 (input 23, on) both on,
  both off, both on, then back as the game had them when the rules were given back; Sword of Rage LE refused cleanly.

## Done (run 6): the Sentinel head, and the final sweep

- `pm_toy(name, action)` / `pm_toy_known`: a toy's own moves through the game's own command for each (`text toys`,
  `text <name>_actions`, `site <name>_<action>` on `data <name>_obj`, checked by `value <name>_vtable`). X-Men LE 0.98:
  `sentinel_head` up / down = the service menu test page's own 0x32f34 / 0x32f78 on Sentinel_Head_Motor (0x644cb8,
  vtable 0x555d18), found from TestMenuPageDiagGameSentinelHead's vtable. The game refuses a move while the head moves,
  while a head process runs, unless it sits at the other end, and while its kick target check says no (switch 91).
  The X-Men Pro has no head motor. Profile.toys (TOYS_PROVEN); Blocks *Move the ...*.
- Proof (toyjob.sh, the end switch and switch 91 held): the move started the game's own head motor run - node 9 coil 5
  at the game's 86/255, stopped and retried by the game (the rig cannot carry the head onto its switch); a second
  move inside 1 s and any move after the rules were given back refused.
- Final regression (flipjob.sh, the finished runtime): 52 of 53 newest builds pass flippers and drain to one; D&D LE
  again only its drain to one, the rig's ball feed (its flippers pass; D&D Pro passes).

## What stays as it was

- The magnet past 5 s: X-Men's own longest magnet command is 2.5 s (LE) / 1.2 s (Pro); a hold is never longer.
- Other titles' own motor toys: the pm_toy route takes any title's toy by port lines; X-Men's are wired and proven. Their
  posts, diverters and magnets were already held through the held-coil route (PAD-381/420) where proven.

## Earlier plan (runs 1-5)

1. ~~**Switch names at run time.**~~ Done in run 3. The game builds its switch table on the heap (mktables.py); the shim already reads
   names from it. A runtime reader of the switch descriptors' names (per framework generation, as the switch-edge
   lines are) gives each build its SHOOTER LANE, TROUGH n and lock/kickback switches with no per-port value: lifts
   the drain-to-one gate on every title and feeds 2 and 3.
2. ~~**Ball devices: hold, release, eject**~~ Done in run 4 (titles whose framework ball-device table has scoops and locks: Godzilla's
   scoop, King Kong, Jaws...; X-Men has none). MODE_LIMITS today: in a whole-game mode a ball in a scoop or lock stays
   until ball search frees it. The framework's ball devices call the game's handler with events (21 switch closed,
   2 settled, 16/17 kick, 18 left: the scoop hold, mode_coils.md); the eject is the device's own (its retries, its
   power adjustment). Generalise the scoop wrap to every ball device record the framework lists, and add the device's
   own eject request: `pm_device_hold(name, on)`, `pm_device_eject(name, n)`.
3. ~~**Kickbacks**~~ Done in run 5: the game's own enable/disable (Godzilla's dead-flipper feature turns kickbacks, pops and slings off
   at 0x3f04cc beside the flipper pair: find the framework's per-kind switch and the kickback's own enable).
4. **Diverters, posts, magnets beyond 5 s**: the held-coil route (PAD-381/420) with a whole-game mode's cap raised
   to the game's own longest command on that coil (`<name>_max_ms`, or the drive's last word), never past it.
5. **Toys**: X-Men's Sentinel head motor (up/down, Sentinel_Head_Motor), then the other titles' toys and posts
   through their own device code (census as mode_coils_census.md did for held coils), each proven like X-Men's.

The older archival versions (not the newest build of their title) carry none of these lines: their cards are not
read (as PAD-1400); a port derived from a user's own older card gets them where its newest build's recipe places them.
