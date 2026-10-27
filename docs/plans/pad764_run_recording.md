# PAD-764: record a run so it replays exactly

David (PAD-733) asked to replay exactly what he saw in his last emulator games. A switch-log replay
(swreplay.py, then only in C:\tmp\PAD-733) matched his session to the millisecond until his first pick,
then went its own way: the game read the machine's memory (the last place played, the audits) and the
rig's memory was not his. Nothing kept his: the NVRAM goes on changing as the game plays, and
gzwatch.log is truncated by the next boot.

## What a run records now

Every Spike 2 boot - the Emulate tab's, a session's rig, Restart game's second boot - gets a folder
under `<logdir>/runs/<YYYYmmdd-HHMMSS>-<title>/` (`<logdir>` is the rig owner's home on rig 0, so
David's are `~/runs` in the distro the app uses; a slot's are `~/padslots/N/runs`):

| | |
|---|---|
| `nvram/` | the title's NVRAM as the game is about to read it: `data/nv/<title>`, `data/nvram-<title>.bin`, the boot selector's `codeselect.last`/`.color`, an edition's own store `nv.own/*/<title>` (~0.5 MB) |
| `modes/` | the modes the LAUNCH brought (the Emulate tab's edits, Try it), as `tryit.sh install` takes them; a card's own modes come from the card on every boot |
| `run.json` | the title, the card (path, size), every `PAD_` setting, the edits folder and its `overrides.json` hash, a Restart game's switch levels, why it ended early (a save-state load) |
| `switches.log` | the boot's `[sw]` edges, `[swspin]` rips and `[pause]` totals, as the shim logged them |

`watch.sh`'s `launch_game` starts it (`runrec.py start`) before anything of the last boot's log goes;
the switch log is written when the boot ends - `killgame.sh` (the app's Stop, which kills watch.sh
before its teardown), the teardown, the next Restart game, a save-state load (`loadgame.sh`: what the
restored game does is not this boot's), or as a backstop the next boot's start. The newest 20 stay
(`PAD_RUN_KEEP`); `PAD_RECORD=0` records nothing.

The shim now lasts a session: the `[sw]` budget was 2000 lines (David's ten minutes were 315), now
200000; rips 20000. It also logs `[pause] <ms> ms frozen <total> ms in all` at boot and on every
change, because every `[sw]` stamp is the raw CLOCK_MONOTONIC while a Pause takes its length off the
game's clocks.

## Replaying one

    wsl -u root -e env HOME=<rig owner's home> bash tools/spike2_emu/replayrun.sh <recording> [--slot N]
    python3 tools/spike2_emu/runrec.py list <logdir>        # which ones there are

It takes a free rig (never rig 0: the replay replaces the title's NVRAM there), puts the recorded NVRAM
in, installs the run's own modes, boots the same card with the same settings - hidden, muted, the ball
feeder and autoattract OFF, since every edge they made is in the record - and hands the game every
switch at its game time (`swreplay.py`: raw stamp less frozen time, on both sides; each change
confirmed by the merge). Run it in the distro the recording names; it warns when the card or the
project's edits changed since. `--keep-nvram` replays on the rig's own NVRAM (what PAD-733 did);
`-- --film MS:N` films the glass at a game ms.

## Proof (PAD-Runtime, rig 1, Godzilla Premium 1.16 Heisei V1.99D + daveyvandy modes v33)

- Recorded sessions: start, city pick, a minute of flippers and slings; one with an 8 s Pause in the
  middle. Each recording holds the NVRAM and 133-144 switch changes.
- Replays on the recorded NVRAM: every change landed at most 1 ms after its game time, none missed;
  the glass at the original's end moment (game ms 86361, and 86215 after the pause) shows the same
  score, credits and HUD as the original's own shot; the modes runtime's log from the game start on is
  identical.
- The same record on another machine's Godzilla NVRAM (`--keep-nvram`, rig 0's old one from Ubuntu):
  the game is in FREE PLAY where the original said CREDITS 29 - the machine's memory, not the
  switches, decides what the game shows, which is the PAD-733 divergence.
- Not exact, and not made to be: the node-board command stream (lamp frames, the boot's motor homing)
  differs by up to ~100 ms between any two boots, replay or not - the emulated boot is CPU-timed. What
  the game decides (score, modes, picks) follows the switches and the NVRAM.
