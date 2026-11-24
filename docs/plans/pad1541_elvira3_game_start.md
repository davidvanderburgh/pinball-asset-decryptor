# PAD-1541: Elvira 3 1.13 would not start a game on the rig

## What it was

Not a rig regression and not the mode runtime. The rig called a title "in attract" as soon as its light show ran
(`gamestate.sh`, `[led] light show running`) and pressed Start five game seconds later. Elvira 3 starts its lamps
first and loads its attract scene (`54589bdb...`, the first clip on video channel 0) afterwards, and that load runs
on the card and the CPU, not the game's clock: 9 s to over 60 s of the wall after the lamps, the longer with several
rigs busy, at 1x and at 4x alike. A Start inside that gap kills the game: its Start handler (0x1c96ec, on the
object at 0x87b6cc) calls through a scene member at +0x84 that is still null (segv pc 0x1c96fc, `ldr r3, [r0]`).
With a fresh NVRAM the same Start hangs the dispatch thread instead (GAME EXIT DISPATCH TIMEOUT).

Evidence (every run on the stock card, hidden, muted):

| run | Start, after the lamps | first attract clip before Start | result |
|---|---|---|---|
| 4x, stock startcheck (x5, incl. the 2026-10-20 rig tree) | ~3 game s | no | segv 0x1c96fc |
| 4x, fresh NVRAM | ~3 game s | no | dispatch watchdog |
| 1x, +5 / +10 / +15 / +20 s | 8-23 s | no | segv 0x1c96fc (all four) |
| 1x, +30 s | 30 s | yes | game on |
| 4x, +120 game s | 30 wall s | yes | game on |
| 1x, after the clip (fix) | 23 s | yes | game on (x3) |
| 4x, after the clip (fix, 3 rigs busy) | 63 wall s | yes | game on (x2) |

The same game time (147.6 s vs 147.8 s) crashed without the clip and started with it, so the clip is the signal.
Across ~120 saved rig runs of the other titles the first attract clip always opened before Start, which is why only
Elvira 3 showed it. PAD-643's Elvira "pass" came through its challenge menu, never a plain Start.

## The fix

`gamestate.sh` `gs_show_up`: past the light show AND a `[vid] chN owns source` / `location ->` line after it.
`gs_wait_show <log> [cap]` waits for it, 120 s of the wall by default (`PAD_SHOW_WAIT`); a title with no attract clip
goes on at the cap. Every path that presses Start after attract waits for it: `rigjob.sh` `job_wait_attract` (every
rigbatch job), `motorcheck.sh`, `modes/gamecheck.sh`, `longplay.sh`. The app's own Emulate tab presses nothing.

## Elvira 3's intro and outro (PAD-1537's gate)

PAD-1537's plain-C proof calls the game's start of a mode with no arguments (`PAD_TEST_PLAIN_START`). Elvira 3's one
start is the House manager's (0xdd12c), which takes the manager, so that call dies too (segv pc 0xdbe68). Proven
through the game instead: in a game, the House Lock switch (89) started the selected House, `FOLLOW 0 START (the
game's Houses ... started)`, and its 8 s clock ended it. `elvira3-1.13` joins `mode_project.WITH_PROVEN` (53 of 69).

Rig 2 still carries a stale `dump/ballfeed.off` (2026-10-27), so these runs held it out.
