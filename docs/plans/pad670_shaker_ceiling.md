# PAD-670: the shaker's 30 s a minute, measured

From PAD-658 (released): "The 30 s a minute shaker ceiling is still a guess." PAD-658 had replaced PAD-414's
unmeasured 20 shakes / 15 s a minute with 30 s of the motor running the modes' shakes in any minute - also picked,
not measured. This ticket looks for something to stand it on, and fixes what the looking turned up.

## What there is to measure

- **The game's own call has no limit a minute** (PAD-658, read from Godzilla LE 1.16's `0x189a54`): only its
  per-shake ones - the operator's SHAKER MOTOR setting (default Maximal Use: 5000 ms a shake), the strength's power
  (51/36/31/23/3 of 255), one at a time with the longer taking over.
- **No published rating.** Stern's kit (502-5027-01 on Spike 2) and its motor carry no duty cycle anywhere public;
  the parts listings disagree even on its voltage. The node board drives it as a timed PWM command on coil 0 of the
  cabinet board, from the 48 V line.
- **Stern's own test** (service menu, Diagnostics > Coil Tests): the shaker is not in the Single Coil Test; the
  Cycling Coil Test gives it 1000 ms at 42/255 once a pass of every coil (~16 s) - nothing like a ceiling.
- **The game's own shaking, measured** - the one number there is to stand on.

## The measurement (emulator, stock Godzilla LE 1.16, real time, muted, `PAD_COIL_PROBE=1`)

Rig 2, hidden. The slot's SHAKER MOTOR adjustment read **None** and Oxygen Destroyer Off (an earlier ticket's
settings): both put back to the game's defaults (Maximal Use, Hard) in the service menu first - with the shaker
off the first run saw no shakes at all. Then 15 min of longplay.sh's unattended play (one ball kept alive, a ramp,
a return lane and a target or a spinner every ~1.5 s, faster than a person) until the game ended by itself after
6.7 min. `tools/spike2_emu/coilduty.py` on the board's `[coildrive]` lines:

| | |
|---|---|
| motor running in all | 42.0 s in 401.8 s (10 %) |
| **busiest 60 s** | **13.5 s** |
| minutes | 4.3, 3.1, 5.3, 9.3, 9.4, 7.4, 3.3 s |
| longest unbroken run | 5.1 s (a 5000 ms rumble at 23/255) |
| what it sent | 59 x 100 ms and 20 x 200 ms at 31/255, 8 x 200 ms at 51, rumbles of 1-5 s at 23 (the softest) |

So the game itself keeps its motor under a quarter of any minute, runs it long only at its softest power, and never
more than one 5 s shake unbroken.

## What changed

1. **The 30 s counts the whole motor.** It counted the modes' shakes only, so with the game busy the motor could run
   30 s of ours plus 13.5 s of the game's. Heat does not care who asked: the runtime now reads the drive's time left
   every tick (`shake_watch`, `site drive_left`) and counts the game's own shakes as they run, against the same
   30 s (`shake_count`/`shake_add`). A game shake taking ours over ends ours' count; ours taking the motor ends the
   game's; nothing is counted twice.
2. **What ran, not what was asked.** The emulator showed the game's own stop (its OFF, cmd 4d, at its own events)
   cutting three of six 5 s shakes of ours 3.5, 4.0 and 0.5 s short, and the runtime counting all six whole - so
   the "counted as it runs" promise was not kept. A drive at 0 once ours has had 150 ms (`SHAKE_SEEN_MS`) to reach
   it is ours stopped, counted no longer (straight after a send the drive still reads 0 for a moment: no stop).
3. **The number stays 30 s, now with a reason**: twice the game's own busiest minute (13.5 s), so the game alone
   never meets it and a mode keeps at least 16 s in the game's busiest minute; and never more on than off in any
   minute. A refusal now says "the shaker has run 30 s in the last minute already (the game's and ours)".
4. `tools/spike2_emu/coilduty.py` (+ `tests/test_spike2_coilduty.py`): the tally above, for the next time.

Docs: MODE_SDK.md "The shaker" (and its PAD-670 run), pad_mode.h, MODE_LIMITS.md, MODE_PARAMETERS.md,
mode_file.c; the Modes tab's two shaker tooltips (the form's Shaker section, the Shake the cabinet block).

## Proof

Emulator, rig 2, stock Godzilla LE 1.16 at Maximal Use, real time: `sdk/shake_test_mode.c` asking 5000 ms at
strength 3 every 5.5 s for 80 s while longplay's shots go on, once with main's runtime and once with this branch's
(`C:\tmp\PAD-670\proof.sh`, tallied by `window.py`: at each ask, the board's motor time in the minute before, ours
and the game's).

| | main's runtime | this branch |
|---|---|---|
| asks / shook / refused | 15 / 9 / 6 | 15 / 10 / 5 |
| first "30 s" refusal | the board's minute 29.4 s, ours 22.0 s - yet "the modes have run the shaker for 30 s" (ours counted whole after the game's OFFs) | the board's minute 26.2 s (ours 23.0, the game's 3.2) + the 5 s asked = 31.2 s |
| last shake let through before it | - | the board's minute 24.8 s + 5 = 29.8 s |
| the motor's busiest minute (board) | 29.5 s | 27.6 s |
| segv / fatal | 0 / 0 | 0 / 0 |

The branch's answers match the board's own tally at every ask.
