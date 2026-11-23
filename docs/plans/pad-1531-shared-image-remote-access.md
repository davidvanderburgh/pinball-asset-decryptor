# PAD-1531: a shared image must not carry the builder's remote access

David (2026-11-23): "if someone distributes a built image with their remote access set up on it, will another user
on the other side of the world have access to the original user's machine? we don't want that to happen."

## What was already safe

* A card only ever carries the PUBLIC half of a computer's key; the private half stays in `remote_access` beside
  settings.json (core/pad_ssh_key.py). Password login is compiled out of the bundled dropbear. Host keys are made
  on each cabinet's `/data` at first boot.

## What was not, and what changed

| Gap | Now |
|---|---|
| A card with remote access on lets the builder in to any machine that runs it. Nothing warned. | The build log and the Write tab's "Before you build" say so (`ssh_card.who_gets_in`), naming any other computer the original lets in. Writing an image that lets someone else's computer in asks first (`app._strangers_ok`). |
| No way to make a clean image for others. | **Build for sharing** (Network tab, project `extras.share`): remote access fully off, and the machine's own partitions emptied as a stock card ships them (core/share_build.py). Flash refuses an image that still carries keys or machine data while it is on. |
| Remote access "off" only removed the boot hook: the key file and PAD's programs stayed on the card. | Off removes the hook, `authorized_keys`, dropbear, dropbearkey, sftp-server and the start script, checked after (`_verify_tree`). |
| One-button setup kept every key the card already trusted, and said "already set up" while a stranger's key was there. | It takes other computers' keys off by default and names them (log + the last word on the Network tab); the project's own saved keys stay; for an image file it asks (Yes = take off, No = keep). |
| A project that never set remote access: the Network tab pre-filled its key box with the card's keys, so the first tick saved a stranger's key into the project. | The box starts empty; the card's other keys are named apart with **Take it off** (saves the project's own setting: on for this computer alone if the card let it in, else off). |

## Where a machine's own data lives (the Wi-Fi question)

Read 2026-11-23 from the cards themselves:

* Spike 2: fstab mounts `/` read-only, `/games` (p3) read-only, `/data` = p5 and `/dump` = p6 (logical, in p4), and
  `/connectivity` = `mmcblk2p1`, the board's own flash, not the SD card. The game program names
  `/data/nv/<game>/NVM` for its settings and joins Wi-Fi over wpa_supplicant's control socket (`SET_NETWORK
  ssid/psk`), never `SAVE_CONFIG`; the card's `/etc/wpa_supplicant.conf` holds no network (docs/plans/spike2-wifi-5ghz.md).
  So the only place on the SD card a machine's network, settings, scores, logs and remote access host keys
  (`/data/dropbear`) can be is p5/p6. A build for sharing empties both whole, so it does not depend on which file.
* Spike 3: every partition is LUKS; `data` (p3) and `connectivity` (p5) are the machine's (24 GB connectivity is on
  the SD card there). Both emptied the same way, through the volume's encryption (`ssh_spike3.open_volume`).
* Stock cards have all of them empty: Aerosmith 1.16 and a Godzilla build (Spike 2), Fallout 0.82 (Spike 3).
* Builds never touched p5/p6 before: a build from a dump of a used card carried its machine data through.

## Proof

* Emulator stand-in (PAD-1427's recipe: the card's own system partition read-only as `/` under qemu-arm, its own
  boot hook starting its own dropbear, all in a private network + mount namespace), three cards made from stock
  Deadpool LE 1.16's real boot and system partitions with a used /data and /dump
  (docs/validation/2026-11-23-pad-1531-shared-image/, proof.txt):
  * A, the builder's card: the builder's key logs in as root; the recipient's is refused.
  * B, A after the recipient's one-button setup (it named the builder's key and took it off): the **old builder's key
    is refused** (Permission denied (publickey)); the recipient's logs in.
  * C, A built for sharing: no boot hook, no authorized_keys, nothing listening; /data and /dump read back empty.
* tests/test_share_build.py (real e2fsprogs under WSL): the shared build reads back with no keys, no programs, no
  hook and empty /data + /dump, boot and game partitions byte-identical; an already-empty build is left byte for
  byte; flash refuses an unshared image for a sharing project; off is off; setup takes strangers off, keeps the
  project's, keeps all on request, is not "already" while a stranger is on; the Network tab never copies a card's
  keys; the image-file setup asks; the write asks.
