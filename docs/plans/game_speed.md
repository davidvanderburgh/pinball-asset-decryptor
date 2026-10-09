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
9. **The card cache reads only what a card uses** (`cardcopy.py`). The cache's copy was `dd conv=sparse`: the holes
   landed as holes, but every byte was READ, through 9p, off the spinning D:. A Spike 2 card is half empty (the 8 GB
   newest builds hold 1.5-6.0 GB). Now the partition table (`sfdisk -J`) says where each partition is, each ext
   partition's own bitmaps (`dumpe2fs`, metadata only) say which blocks are used, and those are read in long runs (a
   free gap under 4 MB read through, not seeked over); everything outside the ext partitions - the table, the FAT
   boot partition, the extended partition's links - is copied whole. A partition whose bitmaps do not add up to its
   group counts is copied whole; anything else that fails falls back to the old dd (`PAD_CARD_COPY_USED=0` forces
   it). Not `e2image -ra`: it reads one block per call, which over 9p is the latency the cache exists to avoid.
   - Cold, 8 GB cards: Munsters LE 1.28 in 24.0 s (3.10 GB read), Sword of Rage Pro 1.19 in 25.5 s (3.06 GB); the
     old dd took 126.7 s (Led Zeppelin LE 1.22) and 57.9 s (Star Wars Pro 1.31), and 78-101 s a card in the 4x sweep
     below.
   - Sword of Rage Pro's copy against its card: every ext partition `e2fsck -fn` clean and file for file the same
     (3453 files in the root partition, 358 in the game's), the 13.6 MB outside them byte for byte.

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

The same check over seven newest builds (Godzilla Pro 1.16, Guardians 1.15, Stranger Things LE 1.13, Deadpool LE
1.16, Mando LE 1.45, Iron Maiden LE 1.18, Jaws LE 1.02), through rigbatch:

| | wall | the jobs one after another | passed |
|---|---|---|---|
| main's tools as PAD-420 ran them (cards staged to C:, 1x), one rig | 25m15s | 18m29s | 7/7 |
| this branch, cards cached, 1x, one rig | 15m09s | 14m56s | 7/7 |
| this branch, 4x, one rig (the cards copied into the cache on the way, by dd) | 21m23s | 9m01s | 6/7 * |
| this branch, cached, 4x, **four rigs** | **2m57s** | 9m15s | 7/7 |
| the same, llvmpipe held to 2 threads | 2m47s | 8m43s | 7/7 |

\* Iron Maiden LE 1.18 on a rig holding an older build's switch list - item 8, fixed since; it passed on that rig in
the four-rig sweeps.

From nothing cached: eight more newest builds (Avengers Pro 1.10, Bond 60th LE 1.11, Jurassic Park Pro 1.16, Iron
Maiden Pro 1.18, Guardians LE 1.15, Aerosmith 1.16, Stranger Things 1.13, Star Wars LE 1.31), four rigs at 4x, every
card copied in by cardcopy.py on the way: **8/8 in 8m19s**, the copies 16-59 s each (1.5-6.0 GB read) but one
(Guardians LE, 5.95 GB, 149 s while four rigs ran). Every one of the 22 four-rig jobs passed.

**Where four rigs' CPU goes** (whole VM, 5 s samples, `cpuall.py` in the ticket's scratch): while all four are in a
game the VM is at 9.2-9.7 of its 10 cores - the renderers 300-450% of a core between them, the four games ~210%,
everything else (fuse2fs, ffmpeg, the harness's python) under 1. The renderers manage 8.5-12 frames a second there,
and the time goes on presenting: `swap 5-17 ms/f` in padglhost's own log, against 2 ms with one rig. Every hidden
run also logs `MESA: error: Failed to attach to x11 shm`, so each frame goes to Xvfb through the X socket, not shared
memory. llvmpipe's own threads are not it (held to 2: 205% against 229%).

## A cheaper hidden renderer (PAD-488)

Measured first, on one hidden rig in Godzilla Pro 1.16's attract (`slotcpu.py`/`thrcpu.py` in the ticket's scratch,
C:\tmp\PAD-488): the renderer took **108% of a core and the game 16%**. All of it was llvmpipe's ten raster threads
(105%); padglhost's own thread was under 5%. Two of the guesses above were wrong:

- **No frame was presented at all.** In 30 s, 900 of 900 frames logged `Failed to attach to x11 shm`, and Mesa drops a
  frame whose attach fails (`swrastPutImageShm`, platform_x11.c) - it never fell back to the X socket. The cause:
  rigs 1-4's displays :71-:74 were Xvfbs in the **PAD-Runtime** distro (root, from app runs), and the sweeps ran in
  **Ubuntu**. The WSL distros share one network namespace, so watch.sh found the other distro's abstract socket in
  /proc/net/unix and reused it; they do not share SysV IPC, so the X server could not attach Ubuntu's segment. A
  plain client copying Mesa's attach (0600 `IPC_PRIVATE`, `IPC_RMID` at once) worked against a root and a user Xvfb
  in the same distro. Fixed: `pad_hidden_display` (padpath.sh) passes over a display whose Xvfb is not a process in
  this distro, for :1070+N, then :2070+N. With shared memory working the renderer took **105%** - unchanged, because
  presenting was never where the core went.
- **The core is drawing, a third of it the window.** Presenting is the letterbox blit plus the swap, drawn in software
  like everything else. Interleaved A/B, 40 s windows, two rounds: every frame **105-108%** (the rig 131%), one frame
  in 30 **75-76%** (96%), none **74%** (94%). Nobody looks at a hidden window - glshot.sh and the picture check read
  the FBO, which gets every frame either way (served at the frame boundary, `jgl_poll`), and every window grabber in
  the rig reads the Windows desktop. So a hidden run now presents **one frame in 30** (watch.sh exports
  `PAD_GL_WIN_EVERY=30` on a hidden run; a caller's own value wins; visible runs untouched, still every frame on
  the GPU).
- The other ~74% is the game's own pictures, 30 a second in llvmpipe. Capped at 15 (`PAD_SWAP_VBLANKS=4`) the
  renderer took 39%.

**Four rigs at 4x, the 7-build check** (`rigbatch.sh -n 4 --speed 4`, cards cached, `cpuall2.py`: cpuall.py plus
reaped children), main against the branch, two interleaved rounds:

| | wall | VM in a game | busiest 30 s | peak | renderers, mean / in a game | passed |
|---|---|---|---|---|---|---|
| PAD-484 (for reference) | 2m57s | 7.7 | 9.4 | 9.7 | 229% / 298% | 7/7 |
| main | 2m50s, 2m45s | 7.2, 7.2 | 8.8, 9.0 | 9.5, 9.5 | 219%, 205% / 290%, 292% | 14/14 |
| own display + 1 in 30, at 30 fps | 3m46s, 3m08s | 5.7, 7.0 | 8.2, 9.2 | 8.6, 9.5 | 127%, 165% / 189%, 210% | 14/14 |
| the same at 15 fps | 2m42s, 2m42s | 5.5, 5.5 | 6.9, 6.9 | 8.1, 7.5 | 77%, 76% / 101%, 100% | 14/14 |
| rigbatch's own defaults (4 rigs, 15 fps) | 2m38s | 5.3 | 6.7 | 7.1 | 70% / 93% | 7/7 |

(Cores of 10; "in a game" = samples with the games at 50% or more. The 3m46s is one Mando LE whose attract show was
not seen in 60 s and whose first Start was ignored - one run of seven, and it passed.)

- **At 30 frames a second the freed core went straight back into frames**, as the ticket feared: the renderers were no
  longer starved, drew the full 30, and the games built more of them (132-179% in a game against ~145%). Only
  the cap gets the VM clearly below saturation, in both rounds.
- So **rigbatch.sh builds 15 pictures a second by default** (`--fps 60|30|20|15`, PAD_SWAP_VBLANKS=60/F to every job; a
  line's own value wins; `--fps 30` is the machine's cadence). The game's clock and logic are unchanged; it skips a
  frame build while the renderer is busy, as on a machine with a slower GPU (PAD-301) - which PAD-484's starved
  sweep already ran at (8.5-12 frames a second, 22/22 passing). bootcheck's `fps=` reads 15 under it.
- **The rig count.** A rig costs ~1.7 cores at four rigs' busiest 30 s at 15, so rigbatch now fits `nproc*10/20` rigs
  at 15 or fewer pictures a second (5 on this VM: every free rig of the 4 slots), and keeps `nproc*10/28` at 30. Untested
  beyond four rigs (PAD_SLOTS_MAX); the 1.7 says a fifth would land near 8.5 of 10 at the busiest.
- **Pictures are unchanged.** glshot.sh at the end of every check, main against the branch at 30 and at 15, all 21
  frames complete game pictures (ball 2, score, HUD, the mode's art).
- **The lights proof too.** PAD-420's lights job (a game started with the feeder, light_all held magenta, the LED view
  judged) through rigbatch's defaults, four rigs at 15: Stranger Things LE 1.13, Deadpool LE 1.16 and Iron Maiden LE
  1.18 PROVEN, as in PAD-420. Guardians 1.15 is not proven - and not on main's tools either, nor the branch at 30:
  the mode holds all 117 inserts, but the shim's LED view decodes ~440-510 frames where PAD-420's proving run
  decoded 14,540. Older than this ticket, and not about the renderer.
- **What is left in a game is mostly the harness.** With reaped children counted, the four rigs in a game at 15
  pictures a second: python3 ~1.7 cores (switch presses, the feeder), bash and what it starts ~1.7 (the check's
  loops; the sweep's own job script stamps every output line with a `date` and a `bc`), the games ~1.8, the
  renderers ~1.1. A sampler that counts live processes only never saw the first two.

## Not done, and what is next

- **More rigs at once.** Since PAD-488 rigbatch fits `nproc*10/20` rigs at its default 15 pictures a second - every
  free rig of the 4 on this VM. Beyond 4 needs PAD_SLOTS_MAX raised and a run to prove it. ~/.wslconfig gives WSL 10
  of the 9800X3D's 16 logical processors (David's choice, for the desktop's sake).
- **The harness's own processes** are now the biggest CPU in a sweep's game (PAD-488's last bullet above, ~3.4 of the
  ~5.8 busy cores): one python3 per switch press is ~80 ms of a core each.
- **Staging is still a floor**, now ~0.5-1 minute an 8 GB card. And a sweep that runs several job kinds should run them
  per BUILD in one pass (one copy, one boot), not one pass per kind over every build as PAD-420 did; the cache keeps
  30 GB of the WSL disk free and evicts least recently booted first, so a second pass over 50 builds copies again.
- **Speeding the boot itself** is unsafe as above; from the cache it is ~23 s anyway.
- Beyond 8x the harness's own latency shows (each `python3 swpoke.py` is ~80 ms of the wall).
