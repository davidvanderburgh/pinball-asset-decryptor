# Sweeping a Spike 2 image much faster (PAD-484)

David, 2026-10-09: *"Need a way of sweeping a spike 2 image much much faster. Consider using my GPU (RTX 5090) and
having a way to speed up emulation (by up to 10x for example). Right now, we are bottlenecked on speed for analyzing
modes on spike 2 images. Consider how long PAD-420 took to finish (over 2 days)."*

PAD-420's sweep of the newest builds was 581 rigbatch jobs, 52 rig-hours, a mean of 321 s a job.

## Where the time went (measured first)

- **The CPU was not the bottleneck.** A hidden rig in a game costs about half a core: the guest ~26% of one (its
  busiest thread, the node bus, ~5%), the renderer ~9%, the video host and ffmpeg ~16%. The game is WAITING - on Tech
  Alerts, a ball saver, a 30 s mode, a drain - on its own clock.
- **The GPU cannot take the work that matters.** The game's own code is ARM, run by qemu-user's CPU emulation; no GPU
  can run it. What a GPU can do is draw the picture: a VISIBLE run's renderer is on the RTX 5090 (PAD-117/127,
  `gpupick.py`), but a hidden run's - every sweep job's - is on Mesa's software rasteriser. Xvfb has no DRI3, so
  d3d12's EGL fails (`DRI3 error: Could not get DRI3 device`, `eglInitialize failed`) and watch.sh falls back to
  llvmpipe; Mesa's software loader will not take d3d12 either (`LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=d3d12`:
  `eglInitialize failed`; tried with the rig's own renderer on a hidden display, 2026-10-09). At ~9% of a core a rig
  that is not where the time is, and neither is video decode (ffmpeg, which NVDEC could take, ~5-15%).
- **A boot was I/O-bound.** Godzilla Pro 1.16 took 79-130 s from start to attract with its card on C: (and the
  sweeps' staged copies are on C:). From 16 s to 88 s the game read almost nothing through `read()` while fuse2fs
  stayed busy (the validator going through the sound bank), then ~12 MB/s of scene loading to ~118 s. Every read goes
  NTFS -> 9p -> fuse2fs and is latency-bound. The same card from the WSL disk (cardmount.sh's local cache) reached
  attract in **23 s**.
- **autoattract never worked on a rig slot.** On a root run in slots 1-4 (every rigbatch sweep) the helper is dropped
  to the desktop user, reads the root guest's environment as "another account's = slot 0", and logs `[auto] the game
  is not running; nothing to do` - on all four slots. Every sweep boot sat on Tech Alerts until the game left it by
  itself (97 s on Godzilla Pro 1.16); a working autoattract presses ~15 s after the bus goes quiet.
- **The check started a game too early.** gamecheck.sh pressed Start as soon as Tech Alerts cleared, before attract;
  the game ignored it and the check spent ~30 s on `no game yet (try 1)` on every Godzilla Pro run measured.

## What was built

1. **Game speed** (hwshim.c "GAME SPEED", padsw.h `speed_req` / `speed_now`, `padspeed.py`). The shim runs every
   clock the game reads, and every way it waits, k times the wall's: `game = real - paused + off(P)`, with `off`
   growing (k - 1) times as fast as real time, continuous across a change and never running back. Interposed: the
   clocks (as PAD-204's pause), usleep, nanosleep, sleep, clock_nanosleep, select/pselect, poll/ppoll (as ppoll, for
   sub-millisecond waits), the futex timeouts glib and libstdc++ pass through `syscall()`, pthread_cond_timedwait and
   the POSIX timers (re-armed when k changes). The closed list is the time imports of the game and every library it
   loads. Nothing changes until a speed other than 1 is asked for (`w_on`).
   - **On the wall clock still:** eglshim's swap pacing (the picture is built ~30 times a REAL second at any speed;
     the game skips frame builds while the renderer is busy, as on a machine with a slow GPU - PAD-301), the GL
     bridge's ring waits and gstvid's waits on the video host (`pad_real_us` / `pad_real_sleep_us`).
   - **The watchdog guard:** a timed wait of 5 s or more keeps its real length (`PAD_SPEED_GUARD_MS`) - the dispatch
     loop's 10 s condvar wait is the PAD-200 watchdog.
   - **Never a spurious wake:** a condvar wait gets one real deadline and returns a timeout only when the game's clock
     has reached the game's deadline.
   - **From attract, not before.** Sped up from the start of the boot, Godzilla Pro 1.16 reached attract (39 s)
     before its auto-loaded scenes were in (48-64 s) - the boot interleaves waits on the game's clock with work bound
     to the wall (the validator, the scene loader) - took a Start, and died on a null scene lookup (`game+0x526f0`,
     the scene `60ed7e50...`'s `VideoSurface`) four seconds into the game, every time. At 1x attract comes after
     the loading; `padspeed.py --when-up` asks only once status.sh says attract.
2. **The harness keeps the game's time.** `padsw.game_sleep` / `padsw.GameClock` (swpoke.py's press, plunge.py's
   coins and lane, ballfeed.py's flight, retry gap and way home, swexercise.py) and `pad_gsleep` (padpath.sh, reading
   `dump/padspeed`) for gamecheck.sh's gaps, ball-saver waits and tilt. A wait FOR something stays a plain loop.
3. **watch.sh `PAD_SPEED=k`** asks for k once the game is in attract; **`rigbatch.sh --speed K`** passes it to every
   job (a list line's own `PAD_SPEED=1` wins).
4. **Sweeps boot off the WSL disk.** rigbatch stages every card on a Windows drive into cardmount.sh's local cache
   (`cardstage.sh <out> cache`, `cardmount.sh --cache-now`) for any number of rigs, and every job runs with
   `PAD_CARD_CACHE=1`. The cache keeps itself (least recently booted first, never a mounted card), 30 GB of the WSL
   disk left free. `--stage DIR` keeps the old copy-to-a-folder behaviour.
5. **autoattract and padspeed run as the game's account** on a slot run (`setsid_as_seer` in watch.sh).
6. **gamecheck.sh waits for attract** (the game's own light show) before its first Start.
7. **The card copies really take turns now.** cardstage.sh's shared lock was `exec 9> /tmp/pad-cardstage-copy.lock`;
   `/tmp` is sticky with `fs.protected_regular=2`, so a root batch could not open a lock the user's batch had made
   ("Permission denied", "flock: 9: Bad file descriptor") and the two copied at once. Opened read-only now.
8. **A sweep presses THIS build's switches.** The rig keeps a title's tables (switch list, device table) per TITLE, and
   a hidden run - every sweep job - sets `PAD_PLAYFIELD=0`, under which watch.sh never ran mktables at all. So a slot
   kept the switch list of whichever build of the title last ran there with a window, and mktables' own refusal of
   another build's list (the jurassic_park_le lesson) never ran. Iron Maiden LE 1.18 on rig 4, whose list was an
   older build's (5667584-byte binary; 1.18's is 6349656), had every id one off: autoattract's Service Back pressed
   Headphone Detect, the check's Start was Tournament Start, padglhost's coin-door latch held the wrong switch ("48V
   DISABLED / CLOSE COIN DOOR"), the feeder had no eject coil - and `no game started after three tries`.
   - watch.sh builds the tables on a hidden run too (pass two in the background; only the window is
     `PAD_PLAYFIELD`'s).
   - Pass two re-derives another build's list ~20 s into the boot, which is too late: by then padglhost had latched
     the coin door and trough and ballfeed had read the old ids (rig 2: a pass, but Start at 83 s, 142 s in all, the
     feeder watching the wrong trough). So watch.sh asks `mktables.py --current --elf <the card's binary>` before the
     renderer starts and removes a list that says another build's: the run is then the title's first run on that rig
     (item 49 - platform ids, the playfield withheld until this build's list lands).
   - gamecheck.sh waits for `mktables.py --current` (this build's list), not for the file to exist.
   - Rig 3, also holding the older list: removed at the start, autoattract on Service Back (28), coins on Left Coin
     (39), the feeder resolved 8 s in, attract at 26 s, the first Start taken; pass in 65 s.

## Measured

Godzilla Pro 1.16, the Modes tab's Check this game (start, every playfield switch, a drain ending a ball), one rig:

| | total | boot to Start |
|---|---|---|
| before (card on C:, 1x, autoattract dead) | 188 s | 67 s (and a Start ignored, retried at 108 s) |
| card cached, 1x | 136 s | 14 s (Start ignored, retried at 54 s) |
| cached, 4x, check waits for attract | **47 s** | 22 s |
| cached, 8x | **36 s** | 21 s |

At 4x the guest uses ~60% of a core in attract (3.5x its 1x load); the renderer does not grow (the picture stays on
the wall clock).

(The seven-build sweep below is being measured.)

## Not done, and what is next

- **More rigs at once.** rigbatch still fits `nproc*10/28` rigs (2.8 cores a rig was a VISIBLE run's cost, ~70% of it
  the Windows-side RDP client). A hidden rig is ~0.5 core at 1x and ~1 at 4x, but the renderer's CPU swings with GPU
  contention (two other tickets' renderers read 115-145% while four rigs ran), so the count is left alone until a
  multi-rig run at speed is measured. A renderer that does not present to the hidden display between glshots would
  take most of it away.
- **Staging is the next floor.** D: reads ~75-90 MB/s: an 8 GB card is ~1m45s to stage, and a job is now under a
  minute. Copying only the ext4 partitions' used blocks (e2image) halves a 16 GB card (13.8 GB partition, 7.8 GB used)
  and takes a 32 GB one from 29 to 12 GB. And a sweep that runs several job kinds should run them per BUILD in one
  pass (one copy, one boot), not one pass per kind over every build as PAD-420 did.
- **Speeding the boot itself** is unsafe as above; from the cache it is ~23 s anyway.
- Beyond 8x the harness's own latency shows (each `python3 swpoke.py` is ~80 ms of the wall).
