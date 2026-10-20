# The shared card store: the Spike 2 library lives in WSL once (PAD-651)

David, 2026-10-20: *"is it just going to be faster long term to have all the spike2 images on the c drive instead
of the D drive? this constant copying them back and forth is inefficient in many ways. especially because we
aren't cleaning up after ourselves. or, can we have wsl use our d drive instead?"* Then: *"we only ever need the
newest builds of spike 2 images anyways. we only keep around old versions for posterity."*

## Why the copies existed, and why neither of his two ideas ends them

- A card on ANY Windows drive, C: included, is read through 9p under fuse2fs and is latency-bound: Godzilla Pro
  1.16 reached attract in 79-130 s from C: and in 23 s from a copy on the WSL ext4 disk (PAD-484,
  docs/plans/game_speed.md). So raw images on C: keep the copies; they only make them faster.
- Several rigs reading several images off the spinning D: (ST4000DM005) seek until a read stalls past the game's
  own watchdog: 5 of 12 builds died that way before staging existed (rig_slots.md). Attaching D: to WSL (`wsl
  --mount` of a physical disk) takes the disk away from Windows while it is attached and keeps the seeking.
- So every sweep copied its cards into cardmount.sh's cache first - and there were THREE caches, one per place
  the rig runs (Ubuntu's `~/cardcache`, 123 GB in a 256 GB distro disk; the app's runtime `/home/pad/cardcache`;
  the app's data disk `/mnt/wsl/paddata/spike2/cardcache`), each too small for the library and each evicting
  least-recently-booted with 30 GB kept free. A 78-build sweep re-copied most of the library every pass, and two
  tickets in two distros copied the same card twice, off one spinning disk, at 6 MB/s (measured 2026-10-20 with
  PAD-643 and PAD-645 both sweeping).

## The library is the newest build of every title

Measured (newest image per title, used blocks from the cache's copy or cardcopy.py's plan): 57 newest images =
320 GB of used blocks (607 GB as raw images); 53 stock titles = 293 GB, the other 27 GB the four Godzilla Heisei
custom builds. Rush LE/Pro and Metallica are the biggest at ~11.7 GB each; Jurassic Park the Pin, Bond 60th and
Beatles the smallest at 1.3-2.0 GB.

David, the same afternoon: *"move any image that has a later version of it to the older versions folder. we
should never use these images in this folder (they are for archival purposes only)."* Done: 33 images, 321 GB,
moved within D: to `D:\Pinball\images\Stern\spike2\older versions` (`moved.log` beside them names each). The
spike2 folder is now exactly the library: 56 images (60 `.raw` files with the Heisei customs), one per title.
Nothing reads `older versions`: not a sweep list, not the cache, not the app's picker.

## What was built

1. **`cardstore.ps1`** (Windows side), made the app's own way: `core/rigdata.py` had already measured on this
   Windows 11 Home box that `diskpart create vdisk` and `wsl --mount --vhd` need no administrator (New-VHD is a
   Hyper-V cmdlet and is absent), so nothing here elevates. `create` makes an expandable VHDX beside the app's work
   disk - `%LOCALAPPDATA%\pinball_decryptor\data\pad-cards.vhdx`, 400 GB maximum, grows as used - attaches it bare,
   has Ubuntu format it ext4 with rigdata's inode-sparing flags (`-i 1048576 -J size=64 -m 0`, lazy init: the
   defaults would materialise ~7 GB of inode tables on a 400 GB volume), detaches it and attaches it again with
   `--name cards`, which puts it at **/mnt/wsl/cards in every distro at once** (Ubuntu and PAD-Runtime, the app's
   runtime). A mount does not survive a reboot, so `create` also writes a Startup-folder entry, **`PAD card
   store.cmd`**, that runs `cardstore.ps1 mount` at logon (`schtasks /Create /SC ONLOGON` is "Access is denied"
   unelevated; pad-triage autostarts from the same folder); it names the main checkout's copy of the script, which
   outlives a ticket's worktree. `status` shows the file's size on disk, the mount in each distro, the cache's use
   and the logon entry. A separate file rather than a bigger work disk because the work disk's point is to be a
   unit of reclaim the user can delete in one action: so is this one, without taking save states with it.
2. **The app attaches it at every rig start** (`rigdata.ensure_cards` / `attach_cards` / `cards_attached`, called
   from the Emulate tab where it re-attaches the work disk after a WSL restart), so a restart never silently sends
   a run back to copying off D:. Never created by the app: 400 GB is a decision made with the script. Missing or
   failing to attach is a line in the log, not a refusal - a run then copies into the runtime's own cache as before.
3. **cardmount.sh keeps its cache in the store when it is there**: `/mnt/wsl/cards/cardcache` when that is a
   mount, else `$PAD_HOME/cardcache` as before (a machine without the store, a reboot before anything attached
   it); `PAD_CARD_CACHE_DIR` names another; `cardmount.sh --cache-dir` says which. cardstage.sh's "did the copy
   land in the cache" check and mkmulticard.py's copier check know the store too. The copier, the stamps, the
   `.boot` sidecars and the eviction are unchanged - there is just one of each now, for every distro.
4. **`precache.sh`** copies every `.raw` in the library folder (never its `older versions` subfolder) into the
   cache, one at a time under the machine-wide copy lock the sweeps use, skipping what is cached and valid, and
   reports each card to the dashboard (`PAD_PROGRESS=PAD-n`).
5. **`cachemigrate.sh`** moves the VALID entries of an old per-distro cache into the store (sparse-preserving,
   NVMe to NVMe, the old entry removed once the new one matches), drops entries whose image is gone or changed
   (the older versions), and leaves a card a run has mounted alone - so the 123 GB Ubuntu had already copied
   were not read off D: again.

## Measured

- `cardstore.ps1 create`: the file made, formatted and attached by name in about a minute; 393 GB usable;
  `mountpoint /mnt/wsl/cards` true in Ubuntu and in PAD-Runtime.
- PAD-Runtime's cache: 2 valid entries (8 GB) moved into the store in 18 s.
- (filled in as the pre-cache completes)

## What it leaves

- The old caches: Ubuntu's `~/cardcache` and PAD-Runtime's two are emptied by the migration; the Ubuntu distro
  disk file shrinks the next time it is compacted (`/prune`).
- Cards on E: or elsewhere, or an older version a ticket must boot on purpose: copied on first use as before and
  evicted first, since the pre-cached newest builds are booted more recently.
- A new image arriving in the spike2 folder: `precache.sh` again (seconds for everything already there), or the
  first run copies it.
