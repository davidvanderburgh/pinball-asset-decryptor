# Send to machine (PAD-1397)

Changes go to a Stern Spike 2 or Spike 3 machine over its home network instead of writing the SD card.
Builds on remote access (PR #38, `core/ssh_card.py`): a card built with Remote access on runs a key-only
dropbear as root.

## What the user does

* **Network tab, Send to machine card**: the machine's address (remembered on this computer), **Check
  connection** (logs in and names the game), **Send an image to the machine…** (any card image: a new Stern
  code version, a custom code card, a multi-boot card, a PAD build) and **Forget this machine** (a card written
  from scratch has a new host identity).
* **Write tab, Send to machine**: builds the project to the Write tab's destination as usual, then sends the
  fresh build (`App._start_write(chain_send=…)`, consumed in `_on_done`, like Build / flash's chained flash).
* Remote access needs no key of the user's own any more: PAD makes one Ed25519 key per computer
  (`core/pad_ssh_key.py`, beside settings.json) and `card_extras.configuration` adds its public half to every
  card built with Remote access on. Host keys are trusted on first use and remembered.

## How a Send works (`core/remote_send.py`)

Both platforms mount the game partition read-only at `/games` and the system partition at `/`; root may
remount them; `/etc/init.d/game_monitor` (Spike 2 and Spike 3 alike) runs `/games/game` in a loop.

**Quick Send** (a finished PAD build of the card the machine runs, `open_plan`):
1. Plan from the build and its original, both read here: every inode of `/` and `/games` whose metadata differs
   (size, times, mode, owner, blocks, link target; then bytes, so a moved file is no change), plus the in-place
   byte ranges the build record names (`inplace` on Spike 2; `send_ranges` on Spike 3, which `spike3_write`
   now records from `GamesVolume.written`). Refused: a changed boot partition, a build without remote access or
   without this computer's key.
2. Check the machine runs that card: every game file the build leaves alone is there at its size; every file
   it changes is the original's or what an earlier Send put there (`/data/pad/remote_send.json`, written
   `pending` first so a cut-off Send is finished by the next).
3. Upload changed files beside their destination (`.name.pad-send`), sha1 checked on the machine, then remount
   rw, rename into place, write the in-place ranges (read back), remove what the build removed, sync.
4. Restart the game: `kill -9` of the process the kernel names `game` (not pidof: Spike 2's is sysvinit's and
   goes by the command line; not `pkill -f`, which matches its own shell); game_monitor starts it on the new
   files. Spike 3's crash mark in `/tmp/game_restarts` is taken off again (5 clear the connectivity cache, 10
   reboot). Remount read-only (retried: the old game held replaced files).
5. No room for a second copy: the game is stopped and the game files the machine has are changed in place, only
   the blocks that differ (the delta, below); the machine reboots at the end. System files never go in place (below).

**Full Send** (any other image, or a build of a card the machine doesn't run, `open_target` + `sync`):
partition layout must match the machine's (`/sys/block/mmcblk0`); every file of `/`, `/games` and a multi-boot
card's unmounted game-image partitions (mounted under `/run/pad-send/pN` for the send) is compared with the
machine (size, then sha1 in batches); the machine's own partitions (`/data`, `/dump`, `/connectivity`) are never
touched; remote access files are kept where the image has none. The game and game_monitor are stopped; files the
machine has are changed by **delta** (David: "space is scarce on the SD card"): 1 MiB block sha1s on the machine
(`dd | sha1sum`), only differing blocks written, then the whole file checked; new files upload whole; the boot
partition is written whole from a checked copy on `/data` when it differs; then the machine reboots.

**The session runs on the card it changes** (David, 2026-11-18: how can a full Send work when the card needs remote
access running during it?). Everything a Send runs on the machine lives on `/`: busybox (the shell and every tool
used), dropbear, libc. A program changed in place under its running copy breaks, and a file cut off half-written
would break the next boot. So on `/` nothing is changed in place: a changed file is copied on the machine
(`cp -p`, no network), the delta goes into the copy, and the copy is renamed over it (`delta_replace`); new files
go up beside and are renamed. Running programs keep their old copy (the open inode) until the reboot at the end, so
the session never sees a change, and each file is always either old or new. System files are removed only after
every new one is in place. Room is checked before the game is stopped: new files, plus each replaced file a running
program holds (`/proc/*/exe`, `maps`, `fd`: its old copy stays until the restart), plus the largest other one (its
old copy goes at its rename); without it the Send is refused and the card must be written. Game files (game
stopped) and unmounted game-image partitions still change in place.

Machine-side quirks found on the stand-in and handled: the session PATH lacks `/sbin`; the file server reports
no owners; dropbear drops command lines past ~9000 bytes (long scripts go as files in `/run`).

## Proof (emulator stand-in)

`C:\tmp\PAD-1397\standin.sh`: a built card loop-attached in WSL, its own rootfs as `/` (ro), p3 at `/games` (ro,
as its fstab), p5 at `/data`, `/dev/mmcblk0pN` + `/sys/block/mmcblk0` named as on the machine, the card's own
`/etc/rc5.d/S30sshd` (dropbear on port 22 under qemu-arm) and its own `game_monitor` running a stand-in game;
`/sbin/reboot` answers with a log line. The app's own code (`send.py` → `connect` + `send_image`) sends to it, and
`compare.py` compares the machine card with the build file by file. Results in the ticket's report.
