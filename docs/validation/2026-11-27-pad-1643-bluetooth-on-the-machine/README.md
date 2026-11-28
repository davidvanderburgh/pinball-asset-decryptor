# PAD-1643: Bluetooth headphones straight onto a running machine (2026-11-27)

David: "i don't want to have to re-build my card to have bluetooth headphones on it. can we make a feature for
updating the card over remote access to enable bluetooth?"

The Plugins tab's **Put it on the machine now** (and **Take it off the machine**) make the changes a card write
makes, over remote access: `bluetooth_card.to_machine`. This is its proof, on stand-in machines made from real
cards. The real v0.3.0 release was used throughout, copied from this PC's plugin store.

## What a stand-in machine is

A real card's system partition mounted as `/` **read-only**, in a private network, mount and process namespace
(`unshare -n -m -p -f`), run by the card's own busybox under qemu. Its own boot hook starts its own dropbear, and
the app's own code (`remote_send.SshMachine`, then `bluetooth_card`) talks to it at 127.0.0.1 with this proof's
own PAD key. Nothing leaves the PC. `reboot` only writes down that it was asked; the proof then does what a
restart does for the game (ends `game_monitor`, starts the card's own one again, traced with `sh -x`).

For comparison each run also makes a **twin**: the same card with the plugin put on by the card-write code
(`bluetooth_card.apply_to_build` / `prepare_rootfs`).

## Spike 2: Godzilla Pro 1.16 (`run.sh`, `boot.sh`, `proof.py`; output `proof.txt`)

The card is the library card's real boot and system partitions with remote access put on by `ssh_card`. The
machine's `/games/game` leads to the real Godzilla Pro 1.16 game program (7.9 MB, pulled off the library card by
`extract_game.py`); `game_monitor` runs a stand-in that writes down how it was started.

All 24 checks pass. The ones that matter:

- **Put it on the machine now**: 14 files in 12.8 s; the restart asked for once.
- **The machine's card equals the twin, file for file**: 4498 entries compared (bytes, mode, owner), none differ.
  Only `/usr/local/spikebt/*`, `/usr/local/bin/pad-bt-game` and `/etc/init.d/game_monitor` changed.
- The author's own `SHA256SUMS` checks out on the machine (9 files OK); nothing is left half written.
- **The game check**: the app read the machine's game program and said "This machine's game is one
  spike-pinball-bluetooth v0.3.0 knows: Godzilla Pro - v1.16.0."
- **After the restart** the card's `game_monitor` runs `/usr/local/spikebt/run-live.sh /games/standin`. The
  launcher's `radio-start.sh` says "Unsupported kernel; Bluetooth unchanged" (the PC's kernel is not the
  Wandboard one) and the game starts all the same: its failure path, as in the PAD-1554 proof.
- The launcher's switched-off mark (`/dump/spikebt/disabled`), put there first, is gone.
- **Again**: "already has ...; nothing was changed", no write, no restart.
- **Take it off the machine**: the card equals the card before, file for file; `game_monitor` starts the game
  directly again.
- **A card Stern's own updater brought up to date** (`game_monitor` a link into `/spk/packages`, PAD-1619): the
  link stays, its file gets the block, and `game_monitor` runs the launcher.
- With the plugin not installed on this PC it is refused and the machine is untouched.
- Afterwards the system partition is a clean filesystem (`e2fsck -fn`) and the app's own card inspector reads it
  as "spike-pinball-bluetooth v0.3.0, started with the game".

Found on the way: straight after the change the card stays writable until the restart. The running
`game_monitor` still holds its replaced script file open, and the kernel will not make a filesystem read-only
while a deleted file on it is open. The files are synced first and the restart follows two seconds later; once
the old `game_monitor` has ended the same remount succeeds (checked).

The menu itself (Service, Bluetooth) was shown in the game for exactly these bytes in the PAD-1554 proof
(`2026-11-24-pad-1554-bluetooth-plugin.md`): the machine's card here equals a written card file for file.

## Spike 3: Fallout LE 0.82 (`run_s3.sh`, `boot_s3.sh`, `make_s3.py`, `proof_s3.py`; output `proof_s3.txt`)

The system partition was unlocked on the Windows side with the user's own key (`ssh_spike3.export_rootfs`; the
library card is only read) and given remote access by `ssh_card.prepare_rootfs`. It runs under qemu-aarch64.

All 14 checks pass: the machine is told apart as Spike 3 by its own answers; the arm64 release goes on (no
driver, no wrapper); the card equals the twin file for file (6437 entries); `game_monitor` runs
`SPIKEBT_BACKEND=bluez5 /usr/local/spikebt/run-live.sh $GAME`; the author's `SHA256SUMS` checks out (7 files);
again changes nothing; Take it off puts the card back exactly; the filesystem is clean afterwards.

The start-up chain for those bytes (launcher, exit codes) is the PAD-1554 Spike 3 proof.

## Not provable here

A real radio, as before: the author covers that on machines.

## To run again

`extract_game.py` (Windows Python), then as root in WSL Ubuntu `run.sh` and `run_s3.sh`. They expect the scripts
in `C:\tmp\PAD-1643\standin\`, paramiko in `/var/tmp/pad1643/py`, and the plugin installed on this PC. They
clear `/var/tmp/pad1643` and `/var/tmp/pad1643s3` when they start; delete both, and the unlocked Spike 3
partition file, when done.
