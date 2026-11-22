# Spike 3 card library stored compact (PAD-1507)

## The problem

`D:\Pinball\images\Stern\spike3` held eight card images, each the whole 64 GB
card (61.9 GB): 462 GB. Measured on Pokemon LE 0.82, only **3.35 GB** of a card
is data; the other 58.6 GB is zeros (never-written LUKS space). Zip or xz would
shrink them but make them useless to develop against: the rig opens the card
in place, the app seeks around it, builds copy it.

## The answer: sparse files

A sparse file is still the card: the same `.raw`, the same path, the same
bytes. NTFS stores only the clusters with data, and the zero runs become holes
that take no space. Every reader sees the same bytes back: the app,
`/mnt/d` in WSL, `losetup -r` and `cryptsetup`. Holes read as zeros without
touching the disk, so reads also get faster.

`pinball_decryptor/core/sparse_card.py`:

* **Compact the library in place** (lossless; only ranges just read back as
  zeros are turned into holes; an already-compact card is skipped in seconds,
  because only allocated ranges are read):

      python -m pinball_decryptor.core.sparse_card D:\Pinball\images\Stern\spike3

  Subfolders (`older versions`) are left alone unless `--recursive` is given.
  The tool works on any folder of card images, Spike 2 included.

* **Add a new card compact**, from a `.raw`/`.img` or straight out of the
  downloaded `.zip`/`.xz`/`.gz`/`.bz2`. It is never full size on disk, even
  while unpacking:

      python -m pinball_decryptor.core.sparse_card --into D:\Pinball\images\Stern\spike3 C:\Downloads\new_card.zip

  A card dropped into the folder the ordinary way can also just be compacted
  afterwards with the first command. Only the new card is read.

## Builds stay compact too

* The Write tab's Spike 3 card copy (`spike3_write._Copier`) used
  `shutil.copyfile` (CopyFileEx), which wrote all 62 GB back out. It now uses
  `sparse_copy`. Only the source's allocated ranges are read, and only blocks
  with data are written: a build card costs its data, and copying from a
  compact library card takes seconds.
* The multi-boot maker (`tools/spike3_emu/mks3multi.py`) skipped zero blocks
  with a seek. Writing onto a Windows drive from WSL, drvfs zero-fills every
  such gap (measured: 300 MB written for 128 KB of data). The destination is
  now made sparse by Windows first (`fsutil sparse setflag/setrange`, with no
  elevation needed) and then sized. Writes through drvfs allocate only what
  they land on. If fsutil refuses, the old plain copy is used.

## Proof (2026-11-22)

* `sparse_copy` of the real `pokemon_le-0_82_0.Release.64G.sdcard-secure.raw`:
  61.9 GB card, **3.35 GB on disk**. The SHA-256 of the whole file matches the
  original. Hashing the compact copy took 42 s; the full original takes
  minutes.
* The Spike 3 rig's store, rebuilt from the compact copy into a scratch store
  (`s3store.py build`: losetup -r, LUKS decrypt, ext4 mount over `/mnt/c`),
  gives the same card id. All 5,466 files have the same SHA-256 as the store
  tree built from the full-size original.
* In-place `compact_file` on an ordinary (non-sparse) 8 GB slice of the card:
  8.59 GB down to 0.66 GB in 4 s, hash unchanged. A second pass freed nothing
  and read nothing.
* drvfs: a WSL write into a Windows-made sparse file keeps its holes (128 KB on
  disk for a 300 MB file with two 64 KB writes).

## In the app (David, 2026-11-22: "compact the images from the app and then also expand them from the app")

Settings > Manage disk space > **Card images** (`webui/shellx_cards.py`, the
dialog in `static/js/shellx_dialogs.js`):

* **Compact a folder…** compacts every card image in a folder, but not its
  subfolders. **Compact cards…** compacts the picked files.
* **Add a card compact…** adds a .raw/.img or a .zip/.xz/.gz/.bz2 download to
  a folder. It is never full size on disk.
* **Expand to full size…** answers Yes with a full-size copy elsewhere (needed
  for exFAT/FAT32 drives such as most USB sticks, or for a program that copies
  the whole file), and No by making the card itself full size again. Both check
  that the drive has room first.

Nothing has to be expanded before building: builds, the emulator, extracting
and flashing read compact cards as they are. The CLI has the same operations
as `--expand` and `--expand-to DIR`.

Proof: on a real 8 GB Pokemon card slice, compacting took it from 8.59 GB to
0.66 GB. `expand_copy` (17 s) and `expand_file` (12 s, 7.93 GB filled in) both
hash identical to the original, are not compact, and the sparse flag is
cleared.
