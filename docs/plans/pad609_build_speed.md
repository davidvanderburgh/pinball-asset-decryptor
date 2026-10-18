# PAD-609: long builds faster still

David: *"Need to be able to build and modify large images even faster, add
modes to builds faster, etc."* Follows PAD-599 (`pad599_build_speed.md`).

Measured on the app's own Write path (staging calls + `engine.write_image`),
main against the branch, from a fresh copy of each project:

- **Godzilla Premium 1.16 Heisei Kaiju**: 11 modes, their music and calls in
  11 sound banks, a 16 GB card.
- **Godzilla LE 1.16, 80 replaced sounds**: one of them a 205 s song (9.0 M
  stereo samples), the next longest 93 s.
- **TMNT 1987 retheme**: 298 clips, 2,331 pictures.

## Where the time went, and what changed

1. **The emulator paid Python for work it did not need** (`5286cfa6`). The
   decode that checks each encoded song ran with the keystream recovery's
   per-sample capture hooks still on (86 million calls); every emulator
   boot ran under the per-instruction global hook (57 boots a build); each
   mode's loudness reference was decoded before the encode even when the
   body cache then served it; the mode clip cache (40 clips) was smaller
   than one build's 76; the final check decoded the replaced sounds one
   after another. Each is fixed; `PAD_BOOT_HOOKS=global` is the old boot.
2. **The sound banks were encoded one after another** (`9a69ab8d`): the rest
   go to worker processes, a quarter of the cores at a time, their log lines
   said in bank order. `PAD_STERN_BANK_WORKERS=1` is the old way.
3. **Every replaced picture BC3-decoded its stock picture** (`020e52de`) to
   decide a premultiply only one of 2,330 needed.
4. **One long song was the encode's tail on one core** (`7399a9d0`). The
   cat-0 pool encodes a sound a worker, longest first; the 205 s song ran a
   minute after the other 79 were done. A sound that alone holds more than
   an even share of the samples is encoded in the app with PAD-599's block
   workers, on the cores the pool leaves, beside the pool
   (`engine._cat0_long_split`, `_Cat0LongRun`). Every emulator's codec warm
   treats the Write's whole list as edited, as the pool's always did.
5. **The first bank went alone** only to settle the firmware's
   map-revalidation stub. A game program with one candidate (Godzilla) has
   nothing to settle: every bank goes to the workers at once, biggest first
   (`bank_build.known_revalidate`).
6. **Memory**. A Spike 2 emulator process commits the guest memory it maps
   for image.bin up front on Windows: 2.6 GB on Godzilla, of which it
   touches ~0.15 GB. The side-by-side banks ran four workers of two
   emulators and three block workers each, some 60 GB of commit, and a
   build beside a game on a nearly full C: failed with `UC_ERR_NOMEM`. Every
   pool of emulators now takes what `spike2.parallel.commit_room()` has
   room for (`emulators_that_fit`, 4 GB kept for everything else) and says
   so when that is fewer than the cores': the commit Windows has free now
   and three quarters of what the page files can still grow by (a
   system-managed page file grows to three times the RAM, at most an eighth
   of its drive, as far as the drive's free space allows, and shrinks back
   between builds: 80 GB of commit limit idle here, 125 GB mid-build). Linux
   and macOS commit a page when it is touched and are not held back.

## Results

| | main | branch |
|---|---|---|
| Godzilla 80 sounds | 266 s | 111 s |
| Godzilla, the 205 s song alone | 184 s | 70 s |
| Godzilla 80 sounds, commit held to a 16 GB PC's | | 167 s |
| Godzilla Heisei 11 modes, cold | 7 min 29 s | 2 min 58 s |
| Godzilla Heisei 11 modes, second build | 3 min 4 s | 1 min 21 s |
| TMNT retheme, second build (engine) | 82 s | 77 s |

## Proof

- Godzilla 80 sounds (normal, and with the commit budget held to 14 GB) and
  the 205 s song alone: every one of the card's 5,384 files identical to
  main's build.
- Godzilla Heisei 11 modes: every one of 5,540 files identical to main's
  except `pad_modes.zip`, whose entries are identical and whose entry dates
  are the build time (two main builds differ the same way).
- TMNT: the card's pictures byte-identical to main's (clips differ run to
  run on main too: x264 here is not deterministic).
- A first comparison of the 80-sound build differed from main in idx 0 and
  4; a stale earlier run of the same benchmark was still writing the same
  project and output. A clean re-run was identical, and so was idx 0
  encoded alone on both trees, twice each.
- Tests: `tests/test_pad609_build_speed.py` (narrow boot, capture hooks,
  lazy references, clip cache, final-check pool, banks in order and
  failing, the long-song split and its fallback, block workers warmed with
  the Write's list, the known stub, biggest bank first, the commit budget
  and page-file growth; card-gated: a long song's bytes with block workers
  equal an encode worker's), `tests/test_stern_parallel_encode.py`.
