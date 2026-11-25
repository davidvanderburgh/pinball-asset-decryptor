# GPU encode and decode for preview copies (PAD-1578)

David's performance idea 6 of 10 (2026-11-25): every encode in the app was
libx264 on the CPU. Preview copies never go on a machine, so they may use the
PC's GPU.

## Scope

One encode makes every preview copy: `webui.video_helpers.browser_proxy`,
used by the Video tab's preview pane, Video Compare (up to four at once), the
Audio tab's player, Modes "how" clips and the Jukebox intro videos. That is
the only place changed.

Untouched on purpose, so their bytes do not change:

- everything that goes onto a card (`core.video._ENCODERS`, `transcode_video_to`,
  mode assets, attract items);
- files the user keeps: scene video export, machine-screen recordings,
  extraction outputs (DP ProRes/cdmd, Williams, Spooky).

## How it works (`core/preview_encoder.py`)

- **Encoder**: NVENC, Quick Sync, AMF on Windows; VideoToolbox on macOS; NVENC
  on Linux; else libx264 with the old flags. The ffmpeg encoder list is not
  trusted: each candidate makes a one-frame MP4 from raw frames on stdin with
  its real preview flags, first time a preview is made, once per run
  (0.25 s here). On this PC NVENC and AMF pass, QSV fails.
- **Decoder**: `-hwaccel` (D3D11VA / VideoToolbox / CUDA), tested once with a
  one-frame decode, and only used when the preview is short of CPU threads
  (at most 4 threads each: a small PC, or Compare making four at once) and the
  clip is big enough to pay the ~0.5 s start-up. Raw-frame (`.cdmd`) clips
  never get it.
- **Fallback**: a GPU encode or decode that fails on a real clip is redone on
  the CPU (x264, or VP8 for WebM) at once; the GPU part is dropped for the run
  only if its one-frame test now fails too (a passing test means the clip or a
  busy moment, e.g. NVENC's session limit, was to blame).
- `PAD_PREVIEW_ENCODER=x264` / a candidate name, `PAD_PREVIEW_DECODE=cpu`
  override.

Quality: NVENC `-cq 30` scored SSIM 0.968 against the source vs x264 crf 23's
0.964, at about the same size (cq 23 was 4x bigger).

## Measurements (RTX 5090, 16 threads; real Stern clips from D:\Pinball\videos)

Interleaved A/B, median of 3-5 rounds, through `browser_proxy` itself; old =
`PAD_PREVIEW_ENCODER=x264 PAD_PREVIEW_DECODE=cpu`, which is main's command.
"4 cores" pins the process (and its ffmpeg) to 4 logical CPUs to stand in for
a smaller PC. The PC was in use, so absolute times wander between runs.

Single clip, all 16 threads (GPU decode gated off: NVENC only):

| clip | old (x264) | new |
|---|---|---|
| Guardians GrootMultiball, 554 s 1360x768 | 12.42 s | 5.47 s |
| Elvira HouseParty, 93 s 800x600 | 1.95 s | 1.18 s |
| ABBA KnowingMe loop, 82 s 1080p | 2.38 s | 1.69 s |
| Godzilla NewYork loop, 90 s 1360x768 | 2.87 s | 2.93 s |
| Deadpool tutorial, 26 s 1360x768 | 1.33 s | 1.17 s |
| ABBA Voyage BG, 10 s 1080p | 0.42 s | 0.49 s |

Four threads, the app told it has four (Windows Python ignores the pin, a
real 4-thread PC reports 4), so big clips decode on the GPU too: Godzilla
5.42 -> 3.14 s, Deadpool (CPU decode, too short) 1.99 -> 1.45 s. Pinned but
the app seeing 16 (NVENC only): Elvira 3.63 -> 2.06, ABBA 4.63 -> 3.25,
Voyage 0.77 -> 0.63; Guardians 25.07 -> 12.74 in an earlier quieter run.

Video Compare, four copies at once through browser_proxy threads (Godzilla,
Deadpool, Elvira, ABBA loop): all threads 5.16 -> 4.61 s; four threads
14.38 -> 9.08 s.

ffmpeg CPU seconds per clip, NVENC vs x264 (no GPU decode): Guardians 95.7 ->
48.2, Godzilla 16.1 -> 12.4, Elvira 14.2 -> 7.0: the CPU the app's own
windows get back while a preview is made.

GPU decode on its own (NVENC encode both sides, single clip):

| threads | Guardians 554 s | Godzilla 90 s | ABBA 82 s 1080p |
|---|---|---|---|
| 16 | 6.25 -> 9.96 s (loses) | 2.75 -> 2.38 | 1.66 -> 2.89 (loses) |
| 6 | 8.05 -> 9.00 (loses) | | 2.98 -> 3.16 |
| 4 | 11.68 -> 11.21 | 3.99 -> 2.70 | 2.74 -> 2.74 |
| 2 | 24.56 -> 16.96 | 7.64 -> 4.32 | 5.31 -> 4.06 |
| 4 clips at once, 4 threads | 11.13 -> 6.85 | | |

Hence the threads-per-preview gate. Bench scripts: `C:\tmp\PAD-1578\`
(`ab.py`, `dec.py`, `e2e.py`, `e2e_par.py`).
