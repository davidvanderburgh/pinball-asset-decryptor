# Remote access, made friendly (PAD-1427)

David: "make the setup of remote access way more friendly, especially for users who don't know what they're doing.
Modify an attached SD card with the push of a button and inject the remote access tooling; no secrets or keys to
enter, it's just stored in PAD (and survives app updates). On the connection, a scan button that finds and
remembers the machine so we don't enter the IP address. The manual steps can stay behind advanced settings."

## What the user does (Network tab)

* **Remote access** card: the machine's SD card in this computer's reader is listed (the same drive list the
  Extract tab uses, SD-sized drives only, the likeliest picked); **Set up remote access on this card** asks once,
  then does it. **Use a card image file…** does the same to an image, in place. There is nothing to type: the card
  trusts PAD's own key (`core/pad_ssh_key.py`, kept beside settings.json in the app's settings folder, so app
  updates keep it). Windows asks for administrator access to change the card.
* With a project open, **Keep remote access on cards I write from this project** (the PR #38 setting) is ticked
  for the user after a setup, since writing a card without it takes remote access off the machine again.
  The public-keys box for the user's own SSH programs, with its warning, is under **Advanced**.
* **Your machine(s)** card (Send to machine): **Find my machine** scans the home network and remembers every
  machine that lets PAD in, each by its identity and game (David, while this was being built: "I can have MANY
  machines on my network (deadpool, guardians, bond, etc.) so I need a way to connect to a specific one").
  With one it reads "Your machine: Deadpool LE at 192.168.1.57"; with several, **Send to** picks the one Check
  connection and Send an image use. **Send to machine on the Write tab picks the machine that runs that card's
  game by itself** (the one known machine whose `/games/game` names the card's game), else the one picked.
  Devices that answer but don't let PAD in are listed greyed only when no machine does. Typing an address and
  Forget this machine (the one picked) are under **Advanced**.
* The tab no longer needs a project (`rail_needs` "none"): setting up a card and finding the machine don't.

## How

* `core/remote_setup.py` `set_up(path)`: works on an image file or a raw device (`ssh_spike3.open_stream`:
  `RawDeviceFile` for a device). The system partition's plain filesystem (Spike 2 p2; Spike 3 through its LUKS
  volume, unlocked by the user's own board key, which `key_for` uses for a device as it has no file name for a
  per-card key) is copied to a scratch file, `ssh_card.prepare_rootfs` adds and checks the files (the same code a
  build uses), the 1 MiB blocks that differ are written back, and the whole partition is read back and compared.
  The card's existing trusted keys are kept. Already set up and letting PAD in: nothing is written. The device
  write is held as a flash holds it (`_disk_offline_for_write`, `_locked_volumes`). Cancel works until the first
  block is written; after that it finishes, never half a card.
* `set_up_with_privileges`: a device when the app isn't administrator goes to the elevated flash helper as a new
  job, `mode: "remote_access"` (`elevated_flash._remote_access_helper`), with PAD's public key line in the job.
* `core/machine_scan.py` `scan()`: the /24 around each of this computer's private IPv4 addresses, port 22,
  128 at a time (0.6 s each), the SSH banner read; each SSH server is then logged in to with PAD's key and asked
  `readlink /games/game` (the game). Nothing is remembered by the scan itself.
* `pad_ssh_key` machines.json: `{"current", "machines": [{"address", "host_key", "game"}]}` (the PAD-1397 one-address
  file reads as a list of one). `remember_machine` matches by identity first, so a machine at a new address is the
  same entry, moved (still the one picked if it was); `select_machine`, `forget_machine`, `machine_for_game`.
* `remote_send.connect`: an address nothing answers at (`Unreachable`, now said after 5 s, not 15) that is the
  remembered machine is looked for by its identity (`machine_scan.find_moved`) and remembered at its new address,
  so Check connection and every Send survive the router handing out another address.

## Proof

* Stock `deadpool_le-1_16_0` 8G card copied; `set_up` on it: 4.0 s, 8 MiB blocks changed, all inside p2 (every
  other MiB of the card byte-identical to the stock image); `inspect_image` reads remote access on, trusting
  exactly PAD's key; a second press says it is already set up and writes nothing.
* That card booted in the PAD-1397 machine stand-in (`C:\tmp\PAD-1427\standin.sh`, the card's own rootfs under
  qemu-arm, its own `/etc/rc5.d/S30sshd`): the injected dropbear started from the card's own boot hook.
  From Windows, `machine_scan.scan` of the stand-in's network found it in 1.7 s, logged in with PAD's key and named
  the game `deadpool_le`; `remote_send.connect` to it worked; with the machine remembered at a dead address,
  `connect` found it again at its real one in 6.5 s and remembered it there.
* A scan of this PC's real home networks (two /24s) took 4.8 s.
* Spike 3: a stock `fallout_le-0_82_0` 64G card (sparse copy named `s3card.raw`, so only the user's own board key
  from `~/.pad` could open it, as for a plugged-in card): set up in 6.2 s through its LUKS volume, 10 MiB of the
  root filesystem changed, read back re-encrypted; it reads remote access on, trusting PAD's key; again: already.
* `tests/test_remote_setup.py` (17, the card ones under WSL with real e2fsprogs, the device path through
  `RawDeviceFile`), `tests/test_webui_network.py`, and the SSH/flash/send suites.
