# Automatic disk clean-up (PAD-613)

David, 2026-10-18: "Users shouldn't have to prune and maintain the cache in
WSL. We need to be smarter about managing it automatically."

## What was wrong

Settings ▸ Manage disk space could find and delete everything the app leaves
behind, but only when someone opened it. Nothing else did. Measured on
David's PC that day:

- PAD-Runtime at 83% (17 GB free of 98 GB);
- 39 GiB in 653 leftover folders in `%TEMP%` (cancelled Stern builds,
  ffmpeg scratch);
- a 3.8 GB Dutch Pinball game (`TBL_justin_113_v10+TBL-v1.15`) the window
  never listed, because the path check refused `+`;
- the JJP emulator's restored machines (`/var/tmp/jjp_<iso>`) listed as
  "extract / write staging", inviting a multi-GB re-restore;
- the BoF multi-boot cache's unpacks listed as "Leftover".

## What it does now

`core/space_keeper.py`, run by the web UI (`webui/shellx_disk.py`) 1.5 s
after start and every 30 minutes; a full run at most every 6 hours unless
room is short. The WSL half runs only when WSL is already up.
The window's "Clean up automatically" box (on by default, saved per PC in
the keeper's state file as `auto`) stops the scheduled runs; Clean up now
still runs. `PAD_SPACE_KEEPER=0` turns everything off for support.

| What | Goes when |
|---|---|
| WSL staging leftovers (`cgc_stage_*`, `bof_*`, `pad_aaiw_*`, JJP pipeline scratch) ≥ 1 MB | nothing inside changed for a day |
| Windows temp leftovers (host_temp prefixes, not Stern's three kept caches) ≥ 1 MB | same |
| `*.partial` / `*.part` in an emulator cache | same |
| emulator games (`/var/tmp/pad_*/cache/*`, `pad_bofmulti_cache/*`, `jjp_<iso>`) | not started for 30 days |
| Spike 2 cached cards (via `cardmount.sh --cache-drop`) | not booted for 30 days |
| emulator games, least recently played first | room left < 15 GB |

Never: a root with a game running, anything a process has open or works in
(`/proc/*/cwd`, `/proc/*/fd`), a loop device's backing file, a mount point,
anything used in the last hour, `nv*`, save states, the emulators' Python,
`Leftover:` rows, JJP emulator files (`jjp_run`, `jjp_devices.json`, logs).

Room left = min(df free inside, Windows drive free + slack inside the
.vhdx), because a 1 TB virtual disk's `df` says nothing about the drive
behind it.

A PB I/O-board OS/update entry takes the `build-*` stacks whose `layers`
name it; a BoF multi-boot unpack takes its `.media` pictures. JJP's
`mount.sh` now touches `<image>/.used` so an image's age is when it was
last started.

## Not automatic

Compacting the .vhdx (handing freed space back to Windows) needs
Administrator and a WSL shutdown, so it stays a button. The clean-up stops
the disk growing further; WSL reuses the freed space inside it.

## Proof

`tests/test_space_keeper.py`; the real scan and delete run on PAD-Runtime
against `zz613` fixtures (C:/tmp/PAD-613/fixtures.sh + e2e.py): age pass
removed 6 and kept 9 exactly as the table says; low-room pass removed the
two oldest-played games and kept the one started minutes before.
