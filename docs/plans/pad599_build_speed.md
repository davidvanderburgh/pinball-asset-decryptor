# PAD-599: faster large builds

David: *"When there's many videos or audio files going into a build, it takes
a very long time to prep the image. It needs to be much faster any way
possible."*

## Where the time went

Two real projects, measured from the app's own Write path (staging calls +
`engine.write_image`), cold (first build) and warm (the build after it):

- **TMNT 1987 retheme**: 298 clips, 2,331 pictures, 8 GB card.
- **Godzilla Premium 1.16 Heisei Kaiju**: 60 long replaced sounds, 11 modes,
  a 2 GB grown sound bank, 16 GB card.

Everything ran one item after another on one core: clip conversions, the
same clip probed with ffprobe again and again, every picture's BC3 block
encode, every assigned sound converted again on every build, every
200-sample block of every long sound's keystream recovery, and every file
copied onto the card through debugfs a few KB at a time across WSL's 9p
mount.

## What changed

- **Clips** convert several at once (`video_slots.staging_workers`: half the
  cores, at most 6; `PAD_STAGE_WORKERS` overrides, 1 = the old way). Their
  log lines are held and said whole, in order.
- **Probes** (`video.detect_video_info`, `audio.probe_duration`) are kept per
  (path, size, mtime, prober).
- **Pictures** stage on a thread pool; the engine's BC1/BC3 block encodes for
  textures and radium images run on a pool and are placed in order.
- **Sounds**: a staging cache (`.write_cache/audio_staged.json`) keeps a sound
  converted from the same file the same way; conversions run on threads.
- **Long sounds**: `spike2.parallel.BlockPool` — a long sound's blocks after
  the first are recovered and encoded by worker processes booted like the
  parent's encoder (block keystreams depend only on codec parameters and
  position). Chain-appended sounds an earlier build encoded from the same
  inputs are reused (`_chain_body_cache`).
- **Card copy** (`ext4_grow.grow_files_pinned`): one stat session, one
  `debugfs -w` session for every job, one size read-back — 3 opens instead of
  ~400 for 81 files. On Windows, a file of 32 MiB or more
  (`NATIVE_MIN`) is only *allocated* by debugfs (`fallocate`, size, then
  `extent_open` / `goto_block` / `replace_node` to mark the extents written)
  and its bytes are written by Python straight into the image at the blocks
  the extents name. debugfs wrote into the image over 9p at ~27 MB/s: the
  2 GB bank alone was 75 s. `PAD_PINNED_NATIVE=0` turns it off.

## Results

| | before (main) | after |
|---|---|---|
| TMNT cold | 479 s | 193 s |
| TMNT warm | 16 s | 8 s |
| Godzilla cold | 21 min 49 s | 12 min 13 s (with the old card copy; the new one saves ~85 s more) |
| Godzilla warm | ~5 min 46 s | 3 min 16 s |
| Godzilla card copy | 1 min 48 s | 14 s |

## Proof

- Godzilla: every one of the card's 5,530 files is identical between main's
  build and the branch's (cold, and warm with the native card copy); the only
  file whose bytes differ is `pad_modes.zip`, whose 81 entries are identical
  and whose entry timestamps are the build time (so two main builds differ
  the same way). `e2fsck -fn` clean. The card boots to attract on a rig
  (rigbatch, 26 s).
- TMNT: all 4,181 staged picture files identical to main's. Clip bytes differ
  run to run **on main too** (x264's output is not deterministic here: two
  runs of main's staging of the same 8 clips gave different bytes and
  different decoded frames), with the same arguments to every conversion.
- Tests: `tests/test_pad599_build_speed.py` (probe memo, sound cache, worker
  ordering, block-pool bytes equal the serial encode, chain cache keys),
  `tests/test_ext4_grow_pinned.py` (three opens; a file written twice; the
  native path byte-identical twice with clean fsck; refusing extents that miss
  a block) — run in WSL with real e2fsprogs; full suite green.
