# PAD-474: the shaker on every latest Spike 2 build that has one

Follow-up of PAD-420 ("Mode support for all latest versions ... I don't want any yellow text for any game"). PAD-414
found Godzilla Premium/LE 1.16's own shake call and let a mode shake the cabinet through it; every other latest build
whose machine has a shaker showed it yellow ("The app has not found how X shakes its cabinet"). This makes the
shaker work on them, from the game's own program, and proves each one in the emulator.

## The game's one shake routine, on any build

`tools/spike2_emu/modes/sdk/shaker_lines.py <game ELF> [--port <port>]` (PAD-420's desk reader from the deleted
`ticket/PAD-420-shaker`, kept in C:/tmp/PAD-483/pad420-helpers.bundle; its lines renamed to PAD-414's). Every Spike 2
framework has ONE routine that shakes the cabinet; it is the only one that loads both the operator adjustment
AD_SHAKER_MOTOR (its index in the AD_ name table) and the error "Shaker motor shake duration out of range" (its
index in the error text table). On Godzilla LE 1.16 it is PAD-414's `site shake` 0x189a54, its stop 0x189b08 and
its drive_left 0x3e8bcc, the setting table 0/100/334/500/5000 ms and powers 51/36/31/23/3 - the reader finds every
one of them (`test_the_reader_finds_the_ports_lines_in_the_games_program`). It comes in three shapes, all ending in
the framework's `coil_fire(drive 7, power, ms, 0, 0, 0)`, ONE timed command the board ends by itself:

| Shape (`text shake_call`) | The call | Titles |
|---|---|---|
| `ms strength force` (none) | the setting (0..4) cuts `ms` to a u32 table; a busy mask (0x310) holds it off unforced; the strength picks the power from a byte table 0x14 past the time table; `site shake_stop` (an all-zero coil_fire) sits right after it | Godzilla, Led Zeppelin, Rush |
| `ms force` | the same at ONE power, 51/255, no strength | TMNT, Mandalorian, Munsters, Venom |
| `drive` | `shake(kind, min level)`: shakes only when the setting (0..3) is not 0 and at least the call's level, for the kind's time (a u16 table), at one power (Elvira: 255/6 = 42 through an inner routine; Sword of Rage an inner `(ms)`) | Aerosmith, Guardians, Elvira, Sword of Rage |

The last shape takes a kind, not a time, so a mode's "shake for 0.8 s" cannot go through it. The runtime sends that
shake the way the call sends its own (what is left after the kind lookup): the operator's setting not 0, the drive
not running a longer one, then `coil_fire(drive, value shake_power, ms)`. The setting table the port carries is 0,
then the longest kind for every level above (the setting gates; it does not cut). A mode's shake counts as one of
the game's most important (min level 1: it shakes whenever the shaker is on). The two later shapes have no stop
beside their call; the stop is then the game's OFF, the all-zero coil_fire that `site shake_stop` sends on the first.

What the reader writes per build: `site shake` / `shake_stop` (first shape) / `drive_left` / `adjustment` /
`coil_fire`, `value shake_adj` / `shake_drive` / `shake_power` (drive), `text shake_call`, `text shake_setting_ms`,
`text shake_max_ms` (the longest CONSTANT the game's calls pass at each strength, never past the setting table's
top; 0 for a strength it never uses: on the one-power shapes strength 0 only) and the game's own shakes by length
(`tap` <= 150 ms, `short` <= 300, `medium` <= 700, `long` <= 1600, `rumble`: in each band the one the game calls
most). Godzilla Pro 1.16 is LE 1.16's routine instruction for instruction (same stop, tables and 179 constant calls),
so it carries the LE's own lines (PAD-414's census names: hit, big_hit, jackpot, rumble, multiball_start) at its own
addresses. Note: the constants census finds `shake(1900, 1)` once on Godzilla (a video-timed sequence at 0x11355c),
past PAD-414's "strength 1 never runs past 1000 ms"; its port keeps PAD-414's limit (conservative, proven).

## The app

- `pad_mode_runtime.c` "the shaker": `text shake_call` -> `shk.call`; `shake_send` calls the game's
  `shake(ms, strength, 0)` / `shake(ms, 0)`, or (drive) `shake_coil(power, ms)` after the setting and the drive's
  time left; `shake_let_go` uses the game's stop when the port names one, else `shake_coil(0, 0)`; `shake_arm`
  needs a stop (either) and, for drive, `site coil_fire` and a power; one-power shapes zero strengths 1..3.
- `mode_project.py`: `SHAKER_NEEDS` loses `shake_stop` (a stop is the game's or its OFF), `SHAKE_CALLS` per shape,
  `_shaker_lines_found`, labels for the length names with the build's own length ("the game's short shake (0.2 s)"),
  `validate_shakes` names only the strengths the game uses; `SHAKER_PROVEN` += the 20.
- The Modes tab offers only the strengths a game shakes at (form and blocks; a block's strength the game does not
  use is a problem: "... which this card's game does not use: hard."); the tooltips no longer say Godzilla's numbers.

## Proof

Emulator, every build on its stock card, hidden, muted, `PAD_COIL_PROBE=1`, the ticket's pinned mode.so, through
`rigbatch.sh` (job C:/tmp/PAD-474/shake_job.sh, verdict shake_verdict.py). A mode FILE with `shake start <its longest
at 0> 0`, `shake shot game <its short shake> <every shot>` and `shake end <=600 <its softest used strength>`:
A start, stopped ~0.5 s in; B start, run out, then a switch hit; C stop. The verdict finds on ONE board coil, in
order, the start shake at the game's power for its length (cut to the setting's), an OFF within 1.5 s, the start
again, the game's own shake on the hit, the end shake - and no OFF while that one runs out.

Run 1 (`all20.list`, 4 rigs, 28 min, card copies the bottleneck): 16 of 20 passed at once - every runtime
`shaker:` line followed within ~20 ms by `[coildrive] node 1 coil 0` at the game's power for the time asked (cut to
the stock setting's longest: setting 2 on Elvira, 3 on Aerosmith, Guardians and Sword of Rage, 4 elsewhere; 10 ms
board ticks, so 1024 runs 1020); the stop's OFF with 0.4-1.5 s of the shake left (the game's own stop on Godzilla
Pro and Led Zeppelin, the all-zero coil_fire elsewhere); the game's own short shake (Godzilla Pro: its hit) on a
hit; the end shake ran out after the END with no OFF. The four that did not, and what they were:
- Rush LE / Pro: their longest shake is 500 ms, and a mode started and stopped by trigger files is stopped exactly
  one poll (500 ms) later - the shake had run out, no OFF was due. The job then starts the mode on a HIT (any time
  in the half second) and stops it at once, until a stop leaves at least 100 ms: Rush Pro 315 ms, Rush LE 266 ms
  left (its first two tries 2 and 48 ms), each an OFF on the board.
- Venom Pro: its hit landed on a switch the game itself shakes on, and the mode's game shake was refused ("one of
  the game's own shakes is running") - the limit working; the job now tries the next hit.
- TMNT LE: started its game (fresh NVRAM, the van stocked, Tech Alerts; 9 min) and then died on MY edit to the job
  script while bash was reading it. Re-run on a frozen copy: passed.
- Sword of Rage LE passed, but the first verdict paired the start with the game's OWN 2000 ms shake 13 s earlier
  (same power, same length); the verdict now pairs each runtime line with the board line that follows it within
  150 ms (the two logs share the game's clock, ~12 ms apart).

All 20 are in `SHAKER_PROVEN`, each with its board numbers. Logs: C:/tmp/PAD-474/runs_phase1/<build>/ (mode.log,
coil.log, steps.txt).

## The other titles (the ticket's "check the other titles' shaker presence")

MACHINE_HARDWARE read the shaker off the coil names in each newest build's device table (devicexy), which missed
Godzilla's own: its SHAKER MOTOR record is the test menu's (image System/TestMode/shaker_motor_cropped, help "The
shaker motor is an optional accessory for Premium games, and is included in LE editions"), not a playfield one.
Read the same way - a class-2 (coil) device record named SHAKER MOTOR, its address (group 5, index 0: the cabinet
board's coil 0) - EVERY latest build has one except the two Home Editions (Jurassic Park the Pin 1.05, Star Wars
ELG 1.10). The 19 above name it as a plain device; Godzilla and the older titles carry the test menu's record
("an optional accessory for Premium games, and is included in LE editions"; on D&D Pro, Jaws Pro, King Kong Pro and
Stranger Things Pro "... for Pro games"; Batman "an optional accessory").

The reader reads 29 more of them: Avengers LE/Pro, Batman 66, The Beatles, Deadpool LE/Pro, D&D LE/Pro, Foo
Fighters LE/Pro, Iron Maiden LE/Pro, James Bond LE/Pro, Jaws LE/Pro, John Wick LE/Pro, Jurassic Park LE/Pro, King
Kong LE/Pro, Metallica, Star Wars LE/Pro, Stranger Things Pro/LE and Uncanny X-Men LE/Pro - the three shapes above
and four variants of them:
- Deadpool: `shake(kind, level, delay)` hands a delayed shake to a process and an undelayed one to `(ms)` two
  tail-calls in (`coil_fire(7, 42, ms)`): the `drive` shape, the reader following the tail-calls.
- Iron Maiden: `ms strength force` with two powers by a branch instead of a table: strength 0 is 51/255, any other
  32/255 (and its stop beside the call).
- Metallica: the `drive` shape at the operator's own SHAKER MOTOR POWER (adjustment 315, 3..51, default 40): `value
  shake_power_adj`, which the runtime has to read at each shake as the call does.
- Dungeons & Dragons: the routine takes the setting first (`cmp r0, #4` before its push) and loads only the error;
  its wrapper `shake(ms, force)` (59 callers) reads AD_SHAKER_MOTOR and calls it - the `ms force` shape at the
  wrapper.
James Bond 60th LE 1.11 (a newer framework: no duration error, its SHAKER MOTOR "controls the intensity", and a
separate reel shaker) has no such routine; the reader stops there.

None of these 30 has "shaker" in MACHINE_HARDWARE yet, so the Modes tab hides the section on them (no yellow). The
next step on this ticket: their lines, the runtime's `value shake_power_adj`, "shaker" in MACHINE_HARDWARE for the
ones the same sweep proves, and that sweep over all of them with the 20 again on the final object.
