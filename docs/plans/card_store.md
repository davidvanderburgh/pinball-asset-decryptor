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
- Ubuntu's cache: 20 valid entries (101 GB) moved into the store NVMe to NVMe in about five minutes
  (6-17 s a card); 7 stale entries - the older versions moved to the archive folder that afternoon - dropped.
- `precache.sh` over the library's 60 `.raw` files: **38 copied off D: and 22 already there, 0 not cached, 27
  minutes** (22-84 s a card, the 16 GB Rush and Bond images the slowest), with the two sweeps paused so D: had one
  reader. The store then held 60 cards, 300 GB used of 393, and the file was 324 GB on disk; C: went from 552 GB
  free to 219 GB and the Ubuntu distro disk is compacted straight after (its old 123 GB cache is empty).

- The compaction after it (/prune's compact.ps1: fstrim, `wsl --shutdown`, diskpart): Ubuntu's distro disk
  **194.4 GB -> 57.7 GB**, PAD-Runtime's 21.8 -> 13.8, the work disk unchanged at 21.3; 144.7 GB back to Windows,
  C: at 367 GB free with the whole library resident (249 GB free that morning with none of it).
- The file was first made as `C:\wsl\cards.vhdx` by an ELEVATED diskpart and moved into the data folder after the
  pre-cache (a same-volume rename, 331 GB in a second). `wsl --mount` then refused it, "Access is denied": the
  file had kept the ACL it inherited under C:\wsl (Administrators and SYSTEM full control, the user only
  Modify), and attaching a disk needs the user to be able to change its permissions - the service adds the VM's
  own SID to the file, which is what pad-data.vhdx's ACL shows. `icacls /setowner` + full control for the user
  (one elevated step) and the attach went through; a file `cardstore.ps1 create` makes unelevated is the user's
  from the start, so this is a note for anyone moving a disk file made another way.
- Attached from its new home: `/mnt/wsl/cards` a mountpoint in Ubuntu and in PAD-Runtime, 60 cards; PAD-Runtime's
  `cardmount.sh <card> --cache-now` answered "using local cache /mnt/wsl/cards/cardcache/jaws_le-1_02_0.raw" in
  0 s - the app's distro reads what Ubuntu's sessions cached, no copy.
- The emulator proof (Ubuntu, rig 1, `rigbatch.sh -n 1 --who PAD-651 ... -- startcheck.sh` over Godzilla Pro
  1.16, Rush LE 1.19 and Venom Pro 1.07, all from the store): **3/3 pass in 3m02s**, the stager found all three
  cached and copied nothing ("3 cached on the WSL disk, 0 booted where they lie"); Godzilla Pro started 2 s after
  the batch did and passed in 34 s (attract 26 s, a game at 29 s), Venom Pro in 40 s, Rush LE in 101 s (its first
  boot in that rig: Guided Setup); every watch.log reads "[card] using local cache /mnt/wsl/cards/cardcache/...".
  Against this morning: 70-110 s of idle per build waiting for a copy, and 6 MB/s copies when two tickets read D:.
- PAD-643 and PAD-645, let go afterwards: PAD-643 had four rigs in a game within 40 s of its resumed batch's
  start, no copy record on the board; PAD-645 queued its remaining 40 newest builds as one rigbatch waiting for
  rigs. Their worktrees run the older cardmount.sh, which only knows ~/cardcache: that path is a symlink to the
  store in both distros until this ticket merges (harmless after - the store is preferred when mounted).

## What it leaves

- The old caches: Ubuntu's `~/cardcache` and PAD-Runtime's two are emptied by the migration; the Ubuntu distro
  disk file shrinks the next time it is compacted (`/prune`).
- Cards on E: or elsewhere, or an older version a ticket must boot on purpose: copied on first use as before and
  evicted first, since the pre-cached newest builds are booted more recently.
- A new image arriving in the spike2 folder: `precache.sh` again (seconds for everything already there), or the
  first run copies it.

## Permanent: the library is never evicted (PAD-727)

David, 2026-10-25, watching PAD-723's 53-build census copy cards off D: again: *"Why are we copying so many images
over? They should be cached on c"*, and the ticket: *"Need a permanent spike 2 cache on c for dev"*.

The store IS on C: (`pad-cards.vhdx` in `%LOCALAPPDATA%`), and on 2026-10-20 it held all 60 library cards. But its
eviction was still plain least-recently-booted, and on 2026-10-24 tickets that booted older versions on purpose
(PAD-714's older builds: Batman 1.13, D&D LE 1.00, Elvira 3 1.11, Foo Fighters LE 1.03, ...) and two 15 GB Heisei
custom builds from the Desktop filled it: every new copy evicted the least recently booted newest builds. PAD-723's
census (2026-10-25 08:58) then found 16 of its 53 cached and copied 37 off D:, 1-6 minutes each, evicting more
(both Turtles, both Venoms, both King Kongs, Star Wars ELG) to make room.

What changed:

1. **cardmount.sh pins the library** (`cache_pinned`): an entry whose `.src` image is a file directly in the library
   folder (`PAD_CARD_LIBRARY`, default `/mnt/d/Pinball/images/Stern/spike2`, the folder precache.sh fills; the repo's
   `images/` junction spelling counts too) and still has the entry's stamp is never evicted. A newer build replacing
   it, or the image moving to `older versions`, makes it an ordinary entry again. A machine without the folder pins
   nothing: a user's cache works as before.
2. **Dead entries go first**: an entry whose image is gone or changed can never be booted from again, so
   `cache_make_room` takes those before any least-recently-booted one. When only the library is left, the card being
   asked for boots where it lies ("nothing evictable (N library cards kept) - running off the original").
3. **The store keeps a 2 GB margin, not 30**: the 30 GB cardstage.sh asks was the distro's own room on a distro disk;
   the store holds nothing but the cache (`PAD_STORE_KEEP_FREE_GB`). With ~300 GB of library pinned in 393 GB, that
   is ~90 GB for older versions and customs rather than ~60.
4. **The app's 30-day clean-up leaves the library alone**: `--cache-list` adds a `pinned <label>` line after a pinned
   entry (a line of its own, so the old row format is unchanged), `parse_cache_list` sets `pinned`, and
   `space_keeper.plan_cards` skips it. Manage disk space can still delete one by hand.
5. **Every attach at logon tops the library up**: `cardstore.ps1 mount` (the Startup entry) runs `cardstore.ps1 fill`
   after a real attach - precache.sh, detached and hidden, as root, under the machine's one copy lock, logging to
   `/mnt/wsl/cards/precache.log`. Seconds when nothing is new; a new image dropped into the library is copied without
   anyone remembering to. `-NoFill` skips it. `status` says "library: N of M newest builds held, never evicted".

Measured 2026-10-25: before, the worktree's `--cache-list` held 53 of the 60 library cards (the four Heisei customs,
both Beatles i107 variants and Turtles Pro 1987-upscaled had been evicted). `cardstore.ps1 fill` copied those 7 in
9 minutes and found the other 53 in seconds: "library: 60 of 60 newest builds held, never evicted", 75 entries,
6.7 GB free. A dry run of `cache_make_room` over a shadow of the real store's entries (their real `.src` and `.boot`,
empty sparse copies, `df` from the real sizes) asked for 60 GB evicted ten older versions by boot date; asked for
200 GB it evicted the other five non-library entries (Led Zeppelin 1.20 x2, Venom LE 1.06, Heisei v21 and v22) and
then answered "nothing evictable (60 library cards kept) - running off the original", the 60 library cards untouched.
