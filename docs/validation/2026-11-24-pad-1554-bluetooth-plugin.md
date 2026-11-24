# PAD-1554: Bluetooth headphones plugin, proof on a real card and in the emulator (2026-11-24)

Everything here is Stern Spike 2. The scripts are in `C:\tmp\PAD-1554\rig\` (`mkcard.sh`, `mkcard.py`, `btjob.sh`,
`stockjob.sh`, `run.sh`); their output is in `rig\out\` and `rig\out_stock\`.

## The app, against the author's real project

`scripts/shot_pad1554.py` served the branch on a scratch settings folder and a project made from
`godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw`:

- the Plugins tab listed v0.3.0 (tested), v0.2.0, v0.1.2, v0.1.1, v0.1.0, read live from gitlab.com;
- Install fetched v0.3.0, the two archives matched the hashes pinned in `core/bluetooth_card.py`, and the store
  held `SHA256SUMS`, `installed.json` and the two archives under `<settings>\pinball_decryptor\plugins\bluetooth`;
- the card read as "no Bluetooth headphones (as shipped)", and the project's tick saved.

## The card

`mkcard.sh` (WSL Ubuntu) copied the library card and ran the code a build runs
(`remote_buttons.apply_to_build`, then `bluetooth_card.apply_to_build`) on the copy:

- before: `enabled False, hooked False, files False`; after: `enabled True, hooked True, release v0.3.0`, remote
  buttons still `enabled`;
- every byte outside the system partition equals the original's (hash of both, the partition skipped);
- pulled back off the card in the rig, `sha256sum -c SHA256SUMS` in `/usr/local/spikebt` says OK for all nine of
  the author's files, with `run-live.sh`, `radio-start.sh`, `rollback.sh` and `spikebt` at 755.

## The start-up chain, in the emulator's ARM guest

The rig starts `./game` itself and never runs a card's `game_monitor`, so `btjob.sh` ran the card's own
`/etc/init.d/game_monitor` in the guest (busybox sh under qemu) with a stand-in for the game that writes down what
it was started with:

| Card state | What happened | The game's `LD_PRELOAD` |
| --- | --- | --- |
| Bluetooth + remote buttons | `run-live.sh` ran, `radio-start.sh` said "Unsupported kernel; Bluetooth unchanged" (the rig's kernel is not the Wandboard one, so no module load is tried), the launcher fell back to the plain game through `pad-bt-game` | `padmenu.so:pad-buttons.so` |
| the same with a mode runtime on the card | the same | `padmenu.so:pad-buttons.so:mode.so` |
| the plugin's `enabled` file removed | the launcher is not used: the block's own old path | `padmenu.so:pad-buttons.so` |

In each case `/proc/<pid>/maps` of the stand-in shows every listed object loaded, and the sh that carried them
ran to its end: the app's preloads are safe in the wrapper's shell. (`padmenu.so` is the rig root's own.)

Found on the way: with `SPIKEBT_BACKEND` set to a value `run-live.sh` does not know, it exits 2 **without
starting the game**, and `game_monitor` loops. The card never sets that variable on Spike 2, so this cannot
happen there; a Spike 3 hook that sets it must spell `bluez5` exactly.

## The menu, in the game

The same job started the author's helper with its demo backend (as his `scripts/cabinet/run-demo.sh` does) and
booted Godzilla Pro 1.16 from the card with `/usr/local/spikebt/menu.so` preloaded:

- the game reached attract, and its process maps hold `/usr/local/spikebt/menu.so`;
- Service, Select, Select: the Stern main menu has a ninth row, **Bluetooth** ("Manage cabinet Bluetooth
  headphones"); the stock card's menu ends at Redemption Menu (`stockjob.sh`, same presses);
- Select on it opens the author's menu: Search for headphones, Unauthenticated headphones, Allow player cabinet
  volume adjust, Cabinet speakers, Cabinet volume, Back, marked SIMULATED (the demo backend).

Not provable in the emulator: a real radio. The live path needs the Wandboard kernel, BlueZ 4 and an adapter; the
author covers that on machines, and his launcher's failure path is the one shown above.
