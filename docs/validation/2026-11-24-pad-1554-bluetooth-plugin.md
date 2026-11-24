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

## Spike 3: Fallout LE 0.82

Scripts: `C:\tmp\PAD-1554\rig\mkcard_s3.py`, `s3job.sh`, `s3stock.sh`; output in `rig\out_s3\`.

### The card (the real encrypted system partition)

`mkcard_s3.py`, run with the Windows Python as the app runs (the key files name Windows paths; from inside WSL
they do not open). The output is the card up to the end of its system partition (p2, 600 MB, ending at 664 MB),
then a hole to the card's full 59 GB: the plugin touches nothing after it.

- before: `supported True, enabled False, hooked False, platform stern-spike3`;
- `bluetooth_card.apply_to_build` with the user's key: the LUKS volume decrypted to a scratch file, changed,
  written back and read back; after: `enabled True, hooked True, release v0.3.0`;
- the first 80 MB (the signed boot partition and the LUKS header, up to the encrypted data) equal the original's;
- pulled back out of the decrypted partition: `sha256sum -c SHA256SUMS` OK for the seven arm64 files, no
  `btusb.ko`, no `radio-start.sh`;
- off again: nothing left of it, and `game_monitor` equals the original card's byte for byte.

### The start-up chain, in the emulator's ARM64 guest

The rig starts the game itself, so `s3job.sh` put the card's files into a rig slot's overlay and ran the card's
own `/etc/init.d/game_monitor` in the guest (`sh -x`), with one line added after it reads Stern's names so that
`$GAME` is a stand-in that writes down what it was started with and exits 2 (Stern's "exit requested", which
ends the loop):

| Card state | Trace | Stand-in saw | Stern's `GAME_EXIT_REASON` |
| --- | --- | --- | --- |
| plugin on | `SPIKEBT_BACKEND=bluez5 /usr/local/spikebt/run-live.sh <game>`; no BlueZ answers in the rig, so the launcher fell back to the plain game | `SPIKEBT_BACKEND=bluez5`, no preload | 2, then `break` |
| `enabled` removed | `<game>` directly | nothing set | 2 |

The exit-code rule (1, 3 and 6 are normal ends and do not leave the launcher switched off; 4, 5 and a signal do)
is proven with a real shell in `tests/test_pad1554_bluetooth_plugin.py`, against a stand-in launcher that marks
itself off the way his does. His real launcher's success path needs BlueZ 5 and BlueALSA running, which the rig
does not have.

### The menu, in the game

The same job started his helper with its demo backend and ran Fallout LE 0.82 with `menu.so` after the rig's own
preloads: the game's process maps hold `/usr/local/spikebt/menu.so`; the Stern main menu has a ninth row,
Bluetooth, and Select opens his menu (SIMULATED).

## What the two emulators cannot show

A real radio, on either platform, and his launcher's live path. Also not shown: his menu together with this app's
mode runtime or a game program this app has changed (Music Mode rows, editions). His menu acts only on a game
executable whose hash it knows, so on such a card the game runs without the Bluetooth entry.
