# PAD-1647: spike-pinball-bluetooth v0.4.4 with the app (2026-11-27)

David: "there are new tags on the bluetooth repo - we should always promote the latest version and test that as
well to make sure it integrates." The app pinned v0.3.0; its author has published v0.3.1, v0.4.0 to v0.4.4 since.
v0.4.4 is now the tested release (`core/bluetooth_card.py`, hashes pinned), and this is its proof. The release
files used throughout are the two archives of the v0.4.4 release, whose hashes are the ones now pinned.

## What changed in his releases that touches the app

| Release | Change | What the app does about it |
| --- | --- | --- |
| v0.3.1 | launcher takes `SPIKEBT_PRELOAD`; keeps itself on after Spike 3's normal exit codes | nothing: the card's own block still hands it `pad-bt-game` and clears the mark after 1, 3, 6, which works with both old and new launchers |
| v0.4.0, v0.4.1 | the menu finds the game's interfaces on the machine instead of knowing exact game programs | the tab no longer says a game program its author does not list "will have no Bluetooth entry" (`finds_games`, `_not_listed`) |
| v0.4.2, v0.4.3 | more titles | nothing |
| v0.4.4 | Spike 3: `install-bluez5-bond-retention.sh`, one line of `/etc/init.d/S40bluetoothd`, so paired headphones survive a power-off | the card build and "Put it on the machine now" make that change (`s3_keep_bonds_text`), reading the line and its replacement out of the release's own script; Off puts the script back |

## Spike 3's saved pairings: the same bytes his installer makes (`s40check.sh`, `s40check.txt`)

The real Fallout LE 0.82 `S40bluetoothd` (out of the system partition, unlocked with the user's own key) has the
clean-up line his installer looks for. His installer was run on a staged copy with a real `sh`, as his docs say
to patch an image. The app's change equals his output byte for byte, the copy kept is the script as it was,
taking it back out gives the original, and a second pass changes nothing: 4 of 4.

## Onto a machine, and onto a card (the PAD-1643 stand-in machines, rerun with v0.4.4)

The scripts are PAD-1643's (`docs/validation/2026-11-27-pad-1643-bluetooth-on-the-machine/`), pointed at this
branch and a store holding v0.4.4; `proof_s3.py` here is the one with the new checks.

- **Spike 2, Godzilla Pro 1.16** (`proof.txt`): 22 of 22, then the filesystem check and the card inspector.
  Put it on the machine now, 18 s; the machine's card equals one the card-write path made, file for file (4498
  entries); the author's `SHA256SUMS` checks out on the machine (9 files); after the restart `game_monitor` runs
  his v0.4.4 launcher, which falls back to the plain game on this PC's kernel; Take it off puts the card back
  exactly; the card reads as "spike-pinball-bluetooth v0.4.4, started with the game".
- **Spike 3, Fallout LE 0.82** (`proof_s3.txt`): 15 of 15. The machine's card equals the card-write twin, file
  for file (6440 entries). Changed: `game_monitor` and `S40bluetoothd`; added: the plugin's folder and
  `/etc/init.d/.spikebt-originals/S40bluetoothd` (folder 700, root). `S40bluetoothd` on the machine is what his
  own installer, run there on a staged copy, makes of it; the machine's own shell reads it (`sh -n`). Take it
  off puts the card back exactly as it was.

## In the game (the emulator, `bt44job.sh`, `runs.list`; rigbatch `--speed 1`, hidden, muted)

The armv7 archive as the store holds it is unpacked into the guest's `/usr/local/spikebt` (his own `SHA256SUMS`
checked there), his helper runs on its demo backend, and `menu.so` is preloaded into the card's own game.

| Card | His log | Bluetooth |
| --- | --- | --- |
| Godzilla Pro 1.16, stock | discovery compatible (scan), 128 ms; menu hooks armed | Service has the Bluetooth row; the menu opens; Search finds four headphones; one connects ("Headphones connected: 1"); its submenu and volume slider open; Unauthenticated headphones turns On; holding the left flipper in attract offers Bluetooth |
| Godzilla Premium Heisei V1.99D + the card's own 13 modes, runtime left of his menu (the card's order) | discovery compatible (scan), 70 ms; godzilla_le-1.16: menu hooks armed | the row, the menu, Search and connect, the same |

The pictures in the tab's guide (`webui/static/img/plugins/`) are frames of the stock Godzilla Pro run.

## The Godzilla at home that showed no Bluetooth menu

Read over remote access, nothing written: the plugin (v0.3.0) was on the card, the launcher had run, the adapter
was found (BCM20702A0), `btusb` loaded, `bluetoothd` and the helper running. `/tmp/spikebt-game.log`:
`spikebt: no validated profile for executable; stock game unchanged`. The machine's game program (sha256
915c814c...) is a Godzilla LE 1.16 build this app has changed, and v0.3.0 admits exact game programs only. So the
install was whole and the release declined the game.

The author's own discovery probe (`tests/discovery_probe.c` at v0.4.4, built for this PC) on that exact file,
copied off the machine: `found=1 profile=godzilla_le-1.16`, 60 addresses, the same count as the stock Godzilla
Pro 1.16 control (`godzilla_pro-1.16`). v0.4.4 finds what it needs in it.

## Not shown

A real radio, as before: the emulator and the stand-in machines have none, and the helper runs its demo backend.
Whether the saved pairings survive a real cold boot is the author's to prove on a cabinet (his docs say the
same). The Spike 3 game was not booted with v0.4.4 here; what the app puts on a Spike 3 card is proven above.
