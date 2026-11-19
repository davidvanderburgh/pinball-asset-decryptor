# A user's card cache on a disk of its own, sharing identical blocks (PAD-1459)

David, 2026-11-19 (after PAD-1453): performance work for other users. A user has no card store (`cardstore.ps1` is a
developer's script), so their Spike 2 cards were cached inside a Linux disk (`$PAD_HOME/cardcache`: the app's data
disk or `~/cardcache`, 64 GB limit, PAD-739) whose file only ever grows on C:. The cache is mostly the same blocks
over and over: a custom build is the stock card with a few files changed, an LE card shares 73-80% with its Pro.

## What changed

| Piece | What it does |
|---|---|
| `core/rigdata.py` `ensure_cache_disk` | Makes `pad-cardcache.vhdx` beside the other disks (diskpart, no administrator), sized from the old cache: its limit, or what it holds if more, + 32 GB for one copy in flight (96 GB for the default 64). Formats it bare through `cachedisk.sh mkfs` (XFS, reflink, label `padcache`), attaches it by name at `/mnt/wsl/padcache` (every distro), deletes the file again if the format failed. Never on a machine with the card store. |
| `tools/spike2_emu/storexfs.sh` | mkfs.xfs pinned: on Ubuntu 24.04 amd64 (PAD-Runtime) the three packages come by URL from the runtime's own snapshot (`tools/runtime/Dockerfile` `SNAPSHOT`) and are refused unless their SHA-512 matches. Another release falls back to `apt-get download`; an installed mkfs.xfs wins. |
| `tools/spike2_emu/cachedisk.sh move` | Once: the old cache into `<disk>/cardcache.moving` (storededupe ingest: shares blocks as it lands, skips what an earlier pass copied), byte-compares, and only with nothing using the old cache renames it into place and deletes the old one; exit 3 = in use, try later. A cache that is a link is never touched. |
| `cardmount.sh` | Cache kind `disk`: caches there once `<disk>/cardcache` exists (after the store, before the distro's own); the limit counts the disk's real use (df less the empty filesystem's `.base_kb`), not du; keeps 2 GB free; a card on the disk boots where it lies; the copier runs `storededupe.py dedupe --quiet-s 0` after each copy at the lowest CPU/IO priority, one at a time (flock), after the copy is published. After an eviction on the disk it waits for XFS to finish freeing (`cache_settle`). |
| Emulate tab | On Start (no store): the disk is made once / re-attached, the move runs in the background. Every Stop runs the move again until it has switched. The Cache window shows the disk's real use and names the disk. |
| Manage disk space, Reclaim, padcompact | The disk is listed and movable (kept off hard disks, like the store); Reclaim space to Windows trims and compacts it with the distro's; `padcompact.ps1` compacts it. |

## Measured (2026-11-19, emulator machine, PAD-Runtime, a test disk with no store in reach)

* Disk made, formatted with the pinned mkfs.xfs and attached: 27 s, once; the empty 96 GB disk is a 138 MB file
  (df: 1.96 GB used by the empty filesystem, which `.base_kb` takes off).
* Move: an old cache of Godzilla LE + Pro (12.6 GB by du) moved in 60 s and takes 7.7 GB on the disk.
* Six builds of one title (stock LE and Pro, Heisei V1.0, V1.5 Orchestral, V1.5 Standard, V1.6 Orchestral multi),
  each cached through `cardmount.sh --cache-now` (14-39 s a copy, 7-22 s of sharing after it): **38.0 GB by du, 16.8
  GB on the disk: 2.3x the builds under the same limit.** The four Heisei builds alone: 25.4 GB by du, 9.0 GB real
  (2.8x). Every cached card byte-identical to its source after sharing and evictions.
* Eviction: the first run, measuring straight after each delete, emptied the cache under a 10 GB limit - XFS frees a
  shared card's extents in the background (9.7 GB still "used" for about a minute after all six were deleted). With
  `cache_settle` a 7 GB limit took exactly the least recently booted build (8.6 -> 7.0 GB in 3 s) and stopped.
* Boot to attract, Heisei V1.5 Standard, rig 1, real time, interleaved: from the cache disk 27 (cold), 23, 23, 24,
  24 s; from the card store 20, 21, 23, 24, 24 s. Unchanged (PAD-966: 20-23 s on the ext4 store).
