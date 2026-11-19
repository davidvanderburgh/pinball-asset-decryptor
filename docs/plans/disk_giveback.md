# The app's WSL disks give space back to Windows on their own (PAD-1458)

David, 2026-11-19: performance tickets for other users. The space keeper
(PAD-613) deletes unused emulator games, card copies and leftovers inside
PAD-Runtime, but a WSL disk file never shrinks (`--set-sparse` is disabled
by WSL), so a user's C: never got that space back. The only way was Manage
disk space > Reclaim: a button, Administrator, WSL shut down.

## The finding that settled the design: no Administrator needed

The ticket asked to choose between an elevated scheduled task the installer
registers and an elevated helper at exit. Neither: Windows' own
virtual-disk API (`OpenVirtualDisk` + `CompactVirtualDisk`, virtdisk.dll)
compacts an **unattached** VHDX as an ordinary user. Measured 2026-11-19 on
a scratch WSL distro, not elevated: 3084 MB file holding 2 MB after a delete
and fstrim -> 55 MB, and the compacted disk booted, read and wrote. Unattached,
the compaction is "file-system-unaware": it drops only the blocks the VHDX
marks unused (what fstrim inside WSL leaves), so it cannot damage the
filesystem. diskpart's `compact vdisk` was what needed Administrator, because
it attaches the disk first.

So: no task, no service, no UAC prompt ever. `wsl_disk.virtdisk_compact`.

## What it does

`core/disk_giveback.py`. The app's close (`App._on_close`, not an update's
close) calls `start_after_close()`: file reads only, no wsl.exe. When a
give-back may be due it starts a hidden helper (`--disk-giveback <pid>`, the
app's own Python, CREATE_NO_WINDOW) that waits for the app to be gone, then:

1. **Due**: a week since the last look (`giveback_checked` in the space
   keeper's state), and a disk file of 20 GB+ (it cannot hold 20 GB spare
   otherwise). Off with the keeper's "Clean up automatically" box, or
   `PAD_DISK_GIVEBACK=0`.
2. **Busy, Windows side** (fails closed): any `wsl.exe`/`wslg.exe` open
   (every emulator the app starts, a Linux terminal, VS Code), the app's
   window open again (a visible "Pinball Asset Decryptor" window owned by a
   Python), a rig lease touched in 10 minutes.
3. **Busy, other distros**: any distro running besides the app's own
   (Docker Desktop, the user's Ubuntu) - `wsl --shutdown` would stop them.
   wsl.exe not answering is busy.
4. **Busy, inside Linux** + measure, one pass as root in the app's distro:
   df of each disk's filesystem, then any process tagged `PAD_TICKET` /
   `PAD_SLOT` / `PAD_LABEL`, an emulator (`qemu`, `fuse2fs`, `pinmame`,
   `unicorn`), a process running a game under `/var/tmp/pad_*`/`jjp_*`,
   anything open under `/mnt/wsl` or those folders, a mounted card image. A
   scan that does not reach `SCAN_DONE` is busy.
5. Disks with 20 GB+ more file than use: fstrim, a last Windows-side look
   (the app reopened meanwhile), then per disk `wsl --shutdown` until the
   file is free (PAD-739's `_shutdown_until_free`) and compact, retried up
   to 4 times when WSL took the disk back (error 32).
6. **Record**: `giveback` / `giveback_total` in `space_keeper.json`; the
   window's automatic clean-up line ends "Gave back 23.4 GiB to Windows
   2 hours ago." Lines in `compact.log` beside it (padcompact.ps1's log).

Busy saves nothing, so the next close tries again. Nothing to give back
starts the week again.

The disks: the app's Linux (PAD-Runtime, or the default distro without it),
the rigs' data disk, the card store, the card cache - those that exist.

Manage disk space > Reclaim uses the same compaction when the app is not
elevated (elevated, still diskpart), so it no longer asks for Administrator.

## Proof

- `tests/test_pad1458_disk_giveback.py`: due rules, every busy case
  changes nothing and records nothing, retry on a held disk, the record and
  sentence, the helper start, Reclaim without Administrator.
- Real disk, real module (`C:/tmp/PAD-1458/e2e.py`): a scratch ext4 VHDX
  mounted into WSL, a 10 GB game written and deleted (file 10.1 GB). With a
  stand-in emulator running in PAD-Runtime (qemu-named, `PAD_SLOT=9`, started
  through wsl.exe): the real Windows check said "a Linux program is still
  open (wsl.exe)", the real Linux scan named the emulator, the file stayed
  10.1 GB and nothing was recorded. Emulator gone: real scan, real fstrim,
  real compact -> 10.1 GB to 0.1 GB in 2 s, "Gave back 10.0 GiB to Windows
  just now.", and the disk mounted and read afterwards. The disk was released
  with `wsl --unmount` instead of a whole-WSL shutdown, which on David's PC
  would have stopped every other ticket's rigs; the shutdown-and-wait is
  Reclaim's, in use since PAD-739.

## Not changed

`tools/spike2_emu/padcompact.ps1` stays David's own 04:00 task: it also
compacts his default Ubuntu, which users' installs leave alone.
