# PAD-1587: remote access, Send, logs and backups on Jersey Jack Pinball

Remote access (PAD's key-only server on the machine), finding the machine, Send to machine of a build's changed
files, status, logs, and backup and restore of the settings, audits and high scores, on a JJP install. Proven on
Willy Wonka v03.03 (`D:\Pinball\images\JJP\Wonka-v03.03.iso`) with the app's own code, end to end, on 2026-11-25.
Scripts and logs: `2026-11-25-pad-1587-jjp-remote-access/`.

## What a JJP machine gets

A JJP machine is an x86-64 PC running Ubuntu 21.10 with systemd; its install ISO carries the root (`sda3`: the
system and `/jjpe`) as gzip-split partclone, and the game keeps its settings, audits and scores on its own
partition, `/jjpe/perm` (`vf/`).

- **Payload**: Dropbear 2025.88 and PAD's SFTP server, static x86-64, password logins compiled out: the same
  versions and options as Spike 2 and Spike 3 (`resources/ssh/build-x86_64.sh`, pins in `core/ssh_jjp.py`).
- **In the root**: `/usr/local/bin/dropbear`, `dropbearkey`, `/usr/local/libexec/pad-sftp-server`,
  `/usr/local/sbin/pad-sshd` (the Stern start script, host keys in `/var/lib/pad/dropbear`), the unit
  `/etc/systemd/system/pad-sshd.service`, its `multi-user.target.wants` link, and `/root/.ssh/authorized_keys`
  (0600, folder 0700). JJP's own OpenSSH stays off: its host keys are baked into the ISO, so every machine would
  share one identity. A build refuses an install that already enables a server on port 22.
- **Build**: the JJP Write (`StandaloneModPipeline`) writes it with debugfs after the changed files, reads every
  file back (bytes, mode, owner) and checks the hook. It then leaves a **Send record** beside the ISO
  (`<iso>.pad-send/`): each changed file's final bytes, path, sha1, mode and owner, read out of the finished root,
  and three unchanged files that identify the install (the game program and both `fl.dat`). The record moves with
  the ISO to the chosen output.
- **Send** (`core/remote_send_jjp.py`, reached through the usual `send_image`): checks the machine is JJP, runs the
  same game and the same install; holds the game (JJP's loop is `rungame.sh`, frozen as Stern's `game_monitor`
  is), checks the hold took, keeps each file's original in `/var/lib/pad/send/orig` and its ledger before changing
  anything, uploads beside, checks sha1 on the machine, renames in, puts back what an earlier Send changed and this
  build does not, and lets the loop start the game. On the machine's screen it uses JJP's own message tool (`jimg`).
- **Care** (`core/machine_care.py`): status (game, Ubuntu, uptime, Wi-Fi from NetworkManager, network, room on the
  system and settings partitions); logs (`/jjpe/temp/*.log`, syslog, kern.log, Xorg, dmesg, the systemd journal,
  and a report); backup = `/jjpe/perm` (all but lost+found) as a checked zip; restore empties and refills
  `/jjpe/perm` with the game held, keeps the replaced contents as `/var/lib/pad/perm.pad-old.tar`, checks every
  file and rolls back on a mismatch. A Stern backup is refused on a JJP machine and the other way round.
- **Discovery**: the scan's login probe and `describe` name the game from `/jjpe/gen1/setenv.sh` when there is no
  `/games/game`.
- **UI**: the Network tab is in the rail for JJP, its wording says install, not card (no SD-card button, no live
  screen view, no mode-log follow: those are Stern's); the Write tab has Send to machine. Write to SSD logs that it
  does not change remote access.

## The proof

1. **Build** (`build.py`, `build.log`): the app's own JJP Write on Wonka v03.03, project = one changed system file
   (the machine's message picture, stamped "PAD-1587") with remote access on for a throwaway client key and this
   PC's PAD key. Remote access written and read back; ISO built (3.2 GB); Send record of 8 entries (`send.json`).
2. **Stand-in machine** (`standin.sh`, `standin.log`): the built ISO restored by the emulator's own
   `tools/jjp_emu/mount.sh`, the root as a writable overlay, perm as a writable copy of the install's `sda4`, in its
   own mount, UTS and network namespaces (192.168.77.50; the client at .1 in another namespace; nothing on the
   host's network). PAD's server was started by the **systemd unit's own ExecStart**, found through the
   `multi-user.target.wants` link; the **install's own `rungame.sh`** ran the game loop. The game program is a
   stand-in that logs which message picture it sees: the real one needs the Sentinel key, which was not attached.
3. **Client** (`client.py`): WSL Python with the app's code (paramiko from wheels), its own throwaway key. Setup
   puts the install's original picture back and restarts the game (the machine as installed once with remote
   access alone). Then:

| Step | Result |
|---|---|
| found on the network (the app's scan, no address given) | 192.168.77.50, `SSH-2.0-dropbear_2025.88`, lets in, game Wonka |
| status | Game Wonka, System Ubuntu 21.10, uptime |
| Send (SendPipeline -> send_image -> JJP Send) | "Sent 1 changed file (673.4 KB) to the machine; the game restarted on them." |
| game restarted on it | the loop started the game again; it saw the new picture (a06c7acb) |
| original kept | ledger `{PIC: saved}`, `/var/lib/pad/send/orig` holds the install's picture (e7c0a567) |
| same build again | "The machine already has this build: nothing to send." |
| logs pulled | zip: README, report, `jjpe/temp/game.log`, the game's own log, journal |
| settings backed up | 3 files of `perm/vf` |
| settings restored | after changing two and adding one: back exactly as backed up, old contents kept in the tar |
| game back after restore | the loop started the game again |
| restart the game (Machine care) | `PAD_SEND_RESTARTED` |

All 11 passed in seven runs, including one straight after a fresh boot of the stand-in (`client-fresh-boot.log`)
and two with the held check (`client-held-check.log`). `probe5.py`: an unknown key, a password and no
authentication are all refused; port 22 is open only in the stand-in's namespace.

**The one miss, and what it changed.** The very first run, straight after the stand-in's first boot, failed
"game restarted on it": the loop started the game at the moment the hold began, so the old game kept running
through the Send and nothing restarted after it. Six later runs, 15 restarts, 16 holds and a deliberate race test
(`probe4.py`, the hold started 0 to 1.1 s into a restart) never repeated it, with the old or new hold. Two guards
went in regardless: the hold now checks the loop is stopped and ends any game that started as it began (shared
with Stern), and the JJP Send checks on the machine that the loop is stopped and no game runs before it changes a
file, and otherwise stops with "nothing was changed".

Not exercised here: the real game program on the sent build (needs the Sentinel key; the files a Send puts are
the build's own bytes, as the USB install would put them), and NetworkManager Wi-Fi in the status (the stand-in
has no NetworkManager running; parsing is unit-tested).

## The other makers

Remote access needs PAD to write the machine's **system root** (the server and the start-up hook live there),
and the machine to run Linux with a network port. What PAD builds for each maker today decides it:

| Maker | Machine | What PAD builds | Remote access |
|---|---|---|---|
| Spooky (Unity / Godot / P-ROC titles) | Linux x86-64 PC | game update files only (`.pkg`, `.ed`, zip...); Clonezilla images are extract-only | **Can**, once PAD builds their Clonezilla restore image the way it builds JJP's (the same partclone root) |
| Spooky (Jetsons, Domino's, Rob Zombie) | pinHeck: PIC32 + Propeller, no Linux | update files | **Cannot**: no operating system to run a server |
| Barrels of Fun | Linux (Arch on Labyrinth), Godot | the `.fun` game update only | **Can only with a system image**: the `.fun` update never reaches the root, and PAD has no image of it |
| Dutch Pinball, Alice in Wonderland | Linux, ext4 SSD | Write to SSD edits the docked SSD's root | **Can**: the same files could go on the docked SSD's root (no Send record yet: that needs a build of the whole root) |
| Dutch Pinball, Big Lebowski | Linux, pyprocgame | the update `.zip` | **Cannot** with what PAD builds: the update carries game files only |
| Pinball Brothers, Alien / Queen / ABBA | Linux PC board | the `.upd` game update; the install `.iso` is extract-only | **Can**, once PAD builds the install ISO (Clonezilla), as for JJP |
| Pinball Brothers, Predator | custom C++ on FAST hardware | the `.upd` game update | **Cannot** today: no system image route |
| American Pinball | Arch Linux SSD, pyprocgame | the encrypted `.pkg` game update; Clonezilla restore images not wired | **Can**, once PAD builds the restore ISO |

None was built here (David: "say which ... rather than building them all").
