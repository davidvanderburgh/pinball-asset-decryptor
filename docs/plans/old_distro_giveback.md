# PAD-1599: what the app left in the previous Linux

## The gap

Once the app runs its tools in its own Linux (PAD-Runtime), everything it left
in the machine's previous default distro is never reached again: the Spike 2
card cache (`~/cardcache`, up to 64 GB), every emulator's games, runs and Python
(`/var/tmp/pad_*`), Jersey Jack images and staging (`/var/tmp/jjp_*`, `/tmp/...`).
The space keeper, Reclaim and the give-back at close act on the app's own
disks only, and a distro's disk file never shrinks by itself.

## What it does

`core/old_distro.py`, shown as a section at the top of Settings > Manage disk
space (`webui/shellx_olddistro.py`):

1. **Which distro.** The machine's default distro, only while the app has a
   Linux of its own (`runtime.wsl_distro() == PAD-Runtime`); never PAD-Runtime
   or Docker's. `PAD_OLD_DISTRO` names another (support, proof).
2. **Look once.** One root pass in that distro lists the app's names only: each
   user's `~/cardcache` (a real folder on that distro's own filesystem: not a
   link, not a mount such as the shared card store), the rigs' entries as the
   Emulators' files list has them (never `nv*`, `home`, `lower`, `loctmp`),
   and the staging names (`cgc_stage_*`, `bof_*`, `jjp_*`, `pad_aaiw_*`).
3. **Never while the app still works there**: a PAD checkout in it (run from
   source), an emulator game running, a listed path held open, or anything of
   the app's in it, kept things included (`~/padslots`, `~/.pad-rig`,
   `~/s1emu`, a rig's `nv*`), written or read in the last 14 days. Then the
   section does not appear, and the distro is looked at again after a week.
4. **One-time.** Nothing found: never looked at again. Space given back: never
   again. Records live in the space keeper's state (`old_distro`).
5. **One press** (asks first, listing every item): a fresh look, then only
   what it still offers is removed (rig roots asked again whether a game
   runs), then `fstrim /`.
6. **The disk file.** WSL keeps a stopped distro's disk attached until the whole
   VM shuts down. Measured on WSL 2.6.1: after `wsl --terminate` the file stayed
   locked for 2 minutes, `CompactVirtualDisk` answered error 32, and even
   `wsl --export --vhd` was refused with a sharing violation. So the press
   shuts WSL down and compacts (`virtdisk_compact`, no Administrator), but
   only when the give-back's fail-closed checks pass: no Linux program open on
   Windows, no fresh rig lease, no other distro running, nothing running in
   the app's Linux, and nobody in the old distro (a terminal, VS Code).
   Otherwise the compact is **owed**: the section offers "Give the space
   back…" alone, and the give-back at close takes the owed disk whatever its
   spare or the week (`disk_giveback.disks()` / `due()` / `run()`).

## Proof

`scripts/pad1599_old_distro_proof.py` builds a throwaway distro from the
runtime's base tarball and fills it with what an older app left (aged 60 days),
plus the user's own `~/cardcache_mine` and save states. `run` drives
check -> remove -> compact; `compact-when-idle` waits for an idle WSL.
`scripts/shot_pad1599_disk.py` is the window, with `--press`.

## Found on the way: the close helper compacted the wrong distro

The give-back at close (`--disk-giveback`, PAD-1458) ran on its main thread,
where `runtime.status()` never asks wsl.exe (the guard that keeps a UI from
freezing). So `runtime.wsl_distro()` was None and every lookup fell back to the
machine's default distro: on David's PC `disks()` listed his Ubuntu (222 GB) as
"the app's Linux", the busy scan and fstrim ran there, PAD-Runtime counted as
"another distro running", and the record "Ubuntu 217 -> 206 GB" is that helper
compacting the user's distro. The helper now runs on a worker thread
(`_off_main_thread`); measured on David's PC it lists PAD-Runtime (78.75 GB),
the data disk, the card store and the owed old disk.
