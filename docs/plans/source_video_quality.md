# Best quality from your own video files (feature/source-video-quality)

## What and why

David, 2026-09-23: "we need a feature that tracks down our source video files
from a built image and uses them in as high quality as possible. That should
now be possible with additional space that we unlocked." A tester put every
video into his Godzilla retheme by hand, from files named nothing like the
slots, and found clips "downsampled and mangled". We need to map the card back
to his source files ("they exist in a specified root directory and we need to
do the work to find which files are the exact ones he used"), and "if they are
already mapped in the project file ... a one-click 'use the highest possible
quality videos from my sources'". If the mapping isn't there, "we need to be
able to easily generate it".

**Where the quality went (measured on his V1.93 image vs stock Godzilla
Premium 1.16):** 542 of 658 clips replaced (510 full screen, 32 at 520x294),
4,349 s of video, median 2.1 Mbps against 6.1 Mbps for the stock clips in the
same slots. Only 1 clip was squeezed into its stock slot; the loss is the
CONVERSION. Every replacement that isn't already a drop-in is re-encoded at
the stock clip's bitrate (PAD-171; before that, x264's CRF 23), even though a
Write can already put a bigger clip on the card (whole-file copy) and the SD
card size option gives the room.

## Design

**Best quality (the option).** `video_best_quality` in the project's
`.staged_changes.json`, set by a "Best quality" checkbox on the Video tab.
`core.video.transcode_video_to(best_quality=True)` encodes H.264 at CRF 16
with a peak of 0.64 bpp of the slot's pixel rate (20 Mbps at 1360x768/30,
1.5x the highest-rate stock clip measured, 13.3 Mbps), Lanczos scaling. The
x264 preset, profile ceiling, level, pixel format and audio shape are what a
conversion has always used, so the stream is shaped exactly like the ones the
machine plays; only the bits differ. A pinned byte budget (JJP) still wins.
Drop-ins still go on untouched. `app._stage_pending_video` reads the option
from the sidecar, so a Write, a mod-pack export and Emulate's apply agree.
`mod_transfer` carries it as a toggle.

**Conversion cache.** `core.video_slots.StagedCache`
(`<project>/.write_cache/video_staged.json`): a slot whose file is still what
the same source + options produced last time is not converted again. The
recipe is the source's path/size/mtime, the pristine `.orig` snapshot's
identity (a probe of the last conversion can differ in a level or profile),
and every option that reaches the encoder; the result is the slot file's size
and mtime. Without this every Write re-encoded every clip, which at best
quality on a 500-clip retheme is most of an hour, and a Write refused for room
(`card_size.WontFit`) would pay it again on the retry with a bigger card.

**Find the source files (content matching).** `core/source_match.py`
(generic) + `plugins/stern/source_find.py` (the card side). The card side
diffs the built card against the stock card (same size -> byte compare), names
each replaced clip by the project's `video/manifest.txt`, and reads it off the
image to a temp file when fingerprinted. The matcher:

- Fingerprint = 48x27 RGB thumbnails at 2 per second, through the same
  letterbox the conversion applies (`setpts=PTS-STARTPTS,fps=2,scale,pad`,
  loop filter skipped). Cached per file identity under
  `<project>/.write_cache/fingerprints/`.
- Score = Pearson correlation of luma over all thumbnails, minus a chroma
  penalty after a 0.7-1.3 saturation fit and a 1.5-level noise floor. Chroma is
  what separates a colour clip from its black-and-white twin.
- Pass 1: only files within 0.35 s / 2% of the clip's length are decoded.
  Pass 2 (unmatched clips only): opening seconds of every longer file (a
  Trim / pad build). A longer file never replaces a same-length match (a real
  TMNT card's drop-ins lost to cuts with half a second of handle on the front).
- Same content = the two FILES agree (`same_content`: correlation >= 0.985,
  same length +-1 sample, and <= 1.8 luma levels apart after a
  brightness/contrast fit). Correlation alone can't tell an upscale from its
  original (0.981-0.995 on TMNT) but the level difference can (2.8-3.8 against
  0.05-0.97 for copies/exports/masters).
- Among same-content files: clearly better quality wins (1.2x pixels, or 1.5x
  bitrate); within that, the clip's own length to the frame, then the name
  most like the slot's.
- Refine: a same-content group with more than one distinct file is compared
  frame by frame at the clip's rate (+-1 frame tolerance) to split edits that
  differ for a few frames; card copies take no part.
- Certain = score >= 0.93 and (margin >= 0.015 over the best different file,
  or that file is >= 1.4x further off pixel for pixel).
- `Match.card_copy`: the best file is identical to the card's clip and no
  better (a drop-in, or an extract of a built card). Reported, not hidden; a
  card copy never replaces a pick the project already has.

**UI (web).** Video tab: "Best quality" checkbox in the options row and a
"Best quality…" button (Stern Spike 2, `capabilities.video_source_search`).
The window (`webui/video_best.py`, a mixin of the tab service; page
`BestWindow` in `static/js/tabs/video.js`) says what the project records, has
the option, and "Find your source files": built card (defaults to the Write
tab's output), stock card (Write tab's original, else the project's recorded
stock), your videos folder. Results list every replaced clip with the file
found, match %, resolution, bitrate and notes (worth a look, copies, other
versions, same as the clip on the card, longer: needs Trim / pad), tickable.
"Use these files at best quality" makes the ticked files the slots'
replacements and turns the option on; longer files ask to turn Trim / pad on.

**Not done / deliberately not:** no size estimate before a Write (the Write's
own room check refuses and offers the bigger card, and the cache makes the
retry cheap); no per-clip quality setting; no match against clips cut from
the middle of a long file (the TMNT upscale pipeline's problem, not this one).

## Status

- 2026-09-23: matcher, card side, best-quality encode, conversion cache, web
  window. Unit tests: `tests/test_source_match.py` (21),
  `tests/test_video_slots.py` (+7). Real-input proof below.

**Real-input proof (scratchpad scripts, 2026-09-23):**

| Card / folder | Result |
|---|---|
| TMNT 1987 LE upscaled card, sidecar = truth, folder = D:\TMNT1987_Upscale (1,684 files: pre-upscale originals, regrabs, segments, enhanced masters) + .assets, card clips degraded to 1.5 Mbps | 296 exact + 2 the enhanced master the exact file was encoded from; 0 wrong, 0 missed, 298 certain |
| Same, card clips as built | 296 exact + 2 masters; 0 wrong; 297 certain |
| Real plugin path (`SternManufacturer.find_video_sources`), TMNT LE project, folder = the project | 298/298 byte-identical to the recorded file (9 are the same bytes under another name); 297 certain; 34 s cold |
| Tester's Heisei V1.93 card, 542 real card clips; folder = 542 1080p stand-in masters (random names, 77 of them 3 s longer) + 658 clips of an older Heisei build | 444 masters + 17 duplicate slots (two slots, one video); 81 flagged "same as the clip on the card" (older-build extracts); 0 wrong |

Owed: a best-quality Write of a real card (size, bitrate, the clips in the
emulator); David's check in the app from the tree selector.

## How to test

- `python -m pytest tests/test_source_match.py tests/test_video_slots.py -n 0`
- In the app (tree selector -> this branch): open a Stern Spike 2 project with
  videos extracted, Video tab -> Best quality… -> pick a built card, the stock
  card and a folder -> Find -> Use these files at best quality -> Write with an
  SD card size that fits.
- Real input: the scratchpad scripts `tmnt_calib.py` (DEGRADE=1500k for the
  lossy case), `heisei_match.py`, `plugin_e2e.py`.
