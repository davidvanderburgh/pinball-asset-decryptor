# Stern Spike 2: update the last build instead of rebuilding it

Branch `feature/stern-build-update`, worktree
`../pinball-asset-decryptor-wt/stern-build-update`. Created with `/branch`
2026-09-14. Merges via David or `/finish feature/stern-build-update`.

## What and why

David, 2026-09-14: *"is there a way to speed up stern spike 2 image builds?
like just updates? for example, doom walrus is just updating a few things
here and there for his HEISEI image, but he has to rebuild the whole thing
and on his machine that takes 2.5 hours."*

A Spike 2 build always started from the stock image and redid the entire
retheme: the 7+ GB copy, every replaced video probed twice with ffprobe and
copied into the card through the WSL loop mount (488 of them on the Heisei
retheme), the master-directory restore, the firmware integrity derive and
the final decode of every replaced sound. Only the encoded sound bodies
survived between builds (`_AudioBodyCache`, v0.166.0). The engine's own
timing logger already cites the Heisei build at ~110 minutes per image on
the modder's rig.

## Design

Two independent pieces, both in `pinball_decryptor/plugins/stern/engine.py`.

**1. The build record + update in place** (`write_image`, `update=`).
Every build writes `<output>.pad-build.json` beside its output: the stock
card's stamp, the project folder, the app version, every in-place write
traced back to its card file (`_CardIndex.map_writes`, keys
`"<partition offset>:/<path>"`, merged file-relative ranges), every file
copied whole with its source md5 + size, and the output's size/mtime taken
last. The next build of the same project onto the same file, when
`build_update_reason` answers `None`, skips the copy and runs `_update_plan`:

- stock bytes go back over every range the last build patched in place;
- this build's in-place writes go in on top (they are recomputed from the
  stock card exactly as before, so they are the same bytes a whole build
  would write);
- whole-file copies run only for sources whose digest changed; unchanged
  ones stay; a file the last build replaced whole that this build does not
  gets the stock file back (extracted from the stock image into scratch,
  copied in through the driver);
- the record is rewritten at the end; a stub (`building: true`) goes down
  before the first byte so a killed build is never updated over.

The safety rule: every in-place patch was resolved through the STOCK card's
extent maps, so a file patched in place by either build must still sit in
exactly the blocks it had on the stock card. `_update_plan` compares the
extents of every such file between the stock image and the last build and
raises `_CannotUpdate` on any difference (also: partition table differs, a
patch no file covers, a source that can't be read, a file the last build
rewrote whole that this build patches in place). The caller then builds
whole and the log says why. Other refusals (`build_update_reason`): no
record, build did not finish, different app version, record incomplete
(a copy failed), different original or original changed, different project,
output changed since, multi-boot original.

GUI: `WriteApp._confirm_build_over` asks "Update the last build?"
(yes/no/cancel) when the record vouches for the file, else the plain
overwrite question with the reason. The answer rides through
`Manufacturer.make_write_pipeline(update=)` into `SternWritePipeline` and
`engine.write_image`. `Manufacturer.supports_build_update` /
`build_update_reason` are the hooks (Stern Spike 2 only). The Build
button's own duplicate "File exists" prompt in `main_window` was removed;
the app's is the one prompt.

**2. The verified-audio cache** (`_FinalAudioCache`,
`<assets>/.write_cache/audio_final.bin`). The last RESTORED + VERIFIED set of
sound bodies, keyed on `_audio_cache_base_key` (shared with the body cache)
plus a digest of every `(offset, body)` going in. A build whose encoded set
matches replays it and skips the master-directory restore, the integrity
derive and the final decode. Not used for a grown bank or the blip-free
cave. `PAD_STERN_AUDIO_CACHE=0` disables both caches.

Not done, deliberately: the intact-video ffprobe verdicts are still probed
per build (twice per replaced video); a per-source cache is a follow-up.
Direct-SD writes are untouched. Other plugins build whole as before.

## Status

- 2026-09-14: engine, pipeline, manufacturer hooks, app prompt, help tip,
  README + architecture doc, tests written on the branch. Unit-tested
  against the fake ext4 reader (record, plan, restore, copies, refusals,
  failure accounting) and the caches.
- 2026-09-14, **proven on real input** (`engine.write_image` driven from
  the worktree, TMNT Pro 1.59 stock image + a copy of the 1987 project:
  298 assigned replacement videos, 1 replaced image, 2331 in-scene radium
  images, no audio; output on D:):

  | build | mode | time | copied whole |
  |---|---|---|---|
  | 1 | whole | 4 min 57 s (the 7.8 GB copy alone 3 min 45 s) | 298 |
  | 2 | update, nothing changed | 57 s | 0 (298 unchanged) |
  | 3 | update, one clip's source changed | 1 min 1 s | 1 (297 unchanged) |
  | 4 | whole, same edits as 3, second file | 2 min 6 s (warm copy) | 298 |

  The output's size+mtime stamp survived the WSL loop-mount copy step
  (build 2 took the update path 14 s after build 1's record was written).
  Per-file sha256 of every regular file on both ext partitions of build 3's
  image vs build 4's: 4838 files, 0 differ, none missing — an updated build
  is the same card as a whole build of the same edits. Block placement is
  allowed to differ (the driver allocates a re-copied file where it lands),
  so a raw `cmp` is not the oracle; file contents are.

  What an update still pays: the change scan (~10 s), preparing the videos
  (~21 s of ffprobe over 298 clips: the per-source verdict cache is the
  follow-up), the in-place patch of the radium edits (~3 s), the
  validation-manifest refresh (~20 s). Not exercised on real input: an
  audio edit (the verified-set cache is unit-tested only), the boot-screen
  partition, a taken-back video (unit-tested), the GUI prompt itself
  (unit-tested at the method).

## How to test it

```
python scripts/testpick.py stern -- -k "build_update or final_audio"
python -m pytest tests/test_stern_build_update.py -q
```

Manual: launch the worktree from the dev tree selector, open a Spike 2
project with a few replaced videos and one replaced sound, Build; change
one video, Build again onto the same file and answer Yes to "Update the last
build?". The log should show "Updating the build already at", one video
copied whole, the others "unchanged since the last build", and "Audio
checks: ... reused". Delete the `.pad-build.json` beside the output to force
a whole build. Compare `cmp` of the updated file against a whole build of
the same edits: identical except the ext4 metadata the driver's copies
touch.
