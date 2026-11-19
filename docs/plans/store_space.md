# PAD's storage on C: (PAD-1453)

David, 2026-11-19: "our pad storage on disk c has gotten way out of control. we need to reduce the amount of storage
we are using significantly... using over 500GB is insane here." Then: "let's do all 10... combine them into one
ticket." (PAD-1454, lower the store's maximum, and PAD-1455, LE/Pro dedupe, are folded in here.)

## Measured before

| What | On C: | Inside |
|---|---|---|
| `pinball_decryptor\data\pad-cards.vhdx` (card store) | 550-580 GB | 451 GB used: library 299, cardcache 103, spike3 42, pad1435 8 |
| Ubuntu `ext4.vhdx` | 242 GB | 232 GB used, 98% full; /var/tmp 159 GB |
| `pinball_decryptor\runtime\ext4.vhdx` (PAD-Runtime) | 89 GB | 61 GB used; /var/tmp 42 GB |
| `%TEMP%\pytest-of-david` | 41 GB | (1.7 TB apparent, sparse card images) |

The card store's 431 GiB of data held only **189 GiB of unique 4 KiB blocks** (library 288.5 -> 166.9, cardcache
101 -> 28.8, spike3 41.7 -> 11.8). zstd -3 on a card slice: 16%. Library cards were already at their used-block
floor (cardcopy.py), so zeroing free space inside them wins nothing.

## What changed

1. **The store is XFS with shared blocks.** `cardstore.ps1 migrate` makes `pad-cards.xfs.vhdx` (400 GB maximum:
   PAD-1454) beside the old store and copies everything in with `storededupe.py ingest`, which asks the kernel to
   share each new file's blocks with every identical block already there (FIDEDUPERANGE: byte-compared under a lock,
   never merged on a hash alone; a write to a shared block is copied first, so no file can change another). The new
   file grows only to the unique data. `swap` (nothing on the store) copies what changed, byte-compares every file,
   and puts the new file in place; the old one stays as `pad-cards.ext4-old.vhdx` until deleted. `fill` (every
   logon, after a new card) runs `storededupe.py dedupe`, which reads only files it has not seen (hashes cached in
   `.dedupe/` by inode+size+mtime). mkfs.xfs comes from this distro's own packages, unpacked privately
   (`storexfs.sh`), nothing installed.
2. **The store's card cache has a cap**: 25 GB (`PAD_STORE_CACHE_MAX_GB`); `--cache-prune` evicts down to it, least
   recently booted first.
3. **A last copy is never taken automatically.** An entry whose image was deleted from a folder of the user's own
   (Desktop, OneDrive, a games drive) reads `lost`; the copier, the prune and the app's 30-day clean-up leave it, and
   the Cache window says "may be the only copy left". Scratch folders' copies (`C:\tmp\PAD-n`, `/tmp`, `%TEMP%`)
   still go (`gone`).
4. **Done tickets' scratch everywhere** (pad-triage `scratch.py`): `/tmp/pad<n>*`, `/var/tmp/pad<n>*`,
   `/mnt/wsl/cards/pad<n>*` in every running distro and `%TEMP%\pad<n>*` go after the 24 h grace, never one in use.
5. **pytest** keeps only a failed test's `tmp_path`.
6. **`padcompact.ps1`**: a daily 04:00 task (registered elevated) that, at most weekly, compacts the store, the rigs'
   data disk, PAD-Runtime and the default distro when one holds 20+ GB more than it uses - only when nothing runs (no
   fresh rig lease, no ticket-tagged process, no emulator, nothing open under /mnt/wsl), failing closed.
7. The rig's attach (`rigdata.attach_cards`, `cardstore.ps1`) mounts the store as its own type (`<vhdx>.fstype`),
   trying the other when a moved file lost it; Manage disk space > Move carries `.fstype` along.

## Measured after (2026-11-19, David's PC)

| What | Before | After |
|---|---|---|
| **C: free** | **161.6 GB** | **582.3 GB** |
| card store file | 549.7 GB (580 at peak), ext4, 600 GB max | 283.7 GB, XFS, 400 GB max, holding 231 GB |
| Ubuntu `ext4.vhdx` | 242 GB (98% full) | 171.6 GB |
| PAD-Runtime `ext4.vhdx` | 88.9 GB | 65.5 GB |
| `%TEMP%\pytest-of-david` | 41 GB | 0 |

Swap verify: 155,089 files byte-identical, 16,941 links identical. Boot to attract from the shared-block store:
Jaws LE, Jaws Pro, Godzilla LE, Godzilla Pro, 20 s each (PAD-966: 20-23 s on the ext4 store).

Found on the way, fixed: XFS speculative preallocation stranded 4.25 GiB inside Jaws Pro's holes (the copy now sets
the size first, and `punch_zeros` returns them); `os.walk` hid 191 links to folders from the copy (verify now
compares links); an fsync per small file and a full index re-sort per file made Spike 3's 170,000 files take hours;
the installed app polls `wsl.exe` every few seconds, so a compact must shut WSL down right before each disk.

Items 7 (archive superseded library cards) and 8 (keep only the newest Spike 3 versions) were decided against: with
shared blocks those copies cost almost nothing (Spike 3: 41.7 GiB of data, 11.8 unique), and keeping them keeps old
versions bootable. Item 9 (zero free space inside cards) wins nothing: cards are already copied used-blocks-only.
