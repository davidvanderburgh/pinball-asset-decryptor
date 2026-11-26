# PAD-1588: settings and score backups by themselves

David (2026-11-25), from a list of feature ideas: automatic settings and score backups of the machines on the
network. PAD-1467 made Back up / Restore of `/data/nv` (adjustments, audits, high scores) over remote access, but
only on a button press; a card written whole loses them and nobody remembers to back up first.

## What it does

`core/machine_backups.py`:

* **By itself.** Every 30 minutes (first 90 s after start) My machines looks at each machine it can log in to whose
  game is a My machines row's game (the row's release key, e.g. `godzilla_le`, is the game folder the machine's
  `/games/game` names). One whose settings were last read more than a day ago and that answers is read: first only
  the sha1 of each `/data/nv` file (`SUMS`), and a backup (the PAD-1467 zip) is kept only when those differ from
  every kept backup. Nothing changed: no file, only the time it looked (`state.json`), so it isn't read again for a
  day. Only reads: no hold, no restart, nothing written on the machine.
* **Kept per machine** under `machine_backups/<id>/` beside the settings, `<id>` from the machine's host key, so a
  machine the router moves keeps its backups. The owner picks how many (keep 1/3/5/10/20/50, default 5); older ones
  are deleted after each new one, and at once when the count is lowered. Each zip's record says when and what took
  it (`auto`, `send`, `write`, `by hand`).
* **A restored backup is the machine's settings again**: a later read that matches any kept backup keeps no copy,
  and that backup counts as the one last seen, so it is the last pruned (found on the stand-in: comparing only with
  the newest kept a duplicate after a restore).
* **Before a Send** (`SendPipeline`, right after it logs in, before the game is held) and **before a whole-card
  write** (the flash thread, before the pipeline runs; the image's game from its fingerprint, every reachable
  machine running it), one is taken whatever the last one's age, none when nothing changed. A backup that fails is
  said in the log and never stops the Send or the write.
* **The switch** (My machines header, "Back up settings and scores by itself", default on) turns all of these off.

My machines: the row of a machine PAD reaches says "settings backed up <date>" (or "no settings backup yet"); its
More menu has Back up settings now and Restore settings from (each kept backup, with its date and what took it).
Restore is PAD-1467's `restore_settings` (asked first; holds the game, swaps the folder keeping the old one beside
it, checks every file, starts the game again).

## Proof

* `tests/test_machine_backups.py`: the rules (no click, same day not even logged in to, no duplicate, prune,
  restored settings, before a Send/write, the switch), the Send pipeline's order, and the page's calls through the
  web harness.
* Emulator stand-in (`docs/validation/2026-11-25-pad-1588-auto-backups/`, the PAD-1427/1531 recipe): a card from the
  stock Godzilla LE 1.16 card's own boot and system partitions with remote access set up by `ssh_card`, its own
  dropbear (its boot hook) and its own `game_monitor` running a stand-in game under qemu-arm, `/data/nv` = the
  Spike 2 emulator's own Godzilla LE settings (55 files), all in a private network. The app's own code: backed up
  without a click (every file byte for byte, game PID unchanged, only `cat boot_id` and the tar run), the same day
  not logged in to, a day later unchanged (sums only, no copy), four days of changed scores pruned to 3, a restore
  of day 3's backup brings day 3's scores back, and a Send's backup after that keeps no duplicate. `proof.txt`.
