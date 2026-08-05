# Spike 2 PC emulator — task queue

**`/next` takes the first unchecked box below.** Each item's full technical
detail lives in `plans/spike2_pc_emulation_handoff.md` under **REMAINING item
N** — the numbers here are those numbers, so they stay stable as this list is
reordered. Reorder by moving lines; the queue is the order on the page.

## Non-negotiables for any work in this rig

These have each been violated at least once and each cost a run or a window:

- **NEVER `SetWindowPos` an emulator window.** RAIL divergence froze David's
  windows. Move them from inside X (`XMoveWindow`) or not at all.
- **NEVER rebuild while a run is live.** Overwriting `hwshim.so` under a mapped
  guest can kill it. `build.sh` / `buildbridge.sh` only between runs.
- **NEVER wrap a run in `timeout`.** It leaks 140%-CPU processes forever. Use
  `runlim.sh` / `killgame.sh`.
- **`alive.sh` must print 0 after every run.** Confirm it, do not assume it.
- **Never run two measurement runs at once.** `killgame.sh` is global, so the
  older script's teardown kills the newer run mid-boot.
- **David pushes straight to main. No PRs.**

## Queue

- [ ] **12. Closing the game window leaks processes and strands a ghost window.**
      Hit David directly 2026-08-05: he X'd the emulator window and it froze
      there. **It sits at the top of the queue because it breaks the safety net
      the rest of this list depends on** — move it down if the playfield matters
      more.
      - **`alive.sh` LIES, and that is the serious part.** It printed
        `TOTAL STILL RUNNING : 0 (clean)` while **seven leaked interop stubs**
        for `playfield.py` (6 godzilla_pro, 1 turtles_pro, oldest ~2.5 h) and
        **three orphaned `fuse2fs` processes** were live. It counts only the
        five shapes it knows about. "alive.sh must print 0" is only as strong as
        what it counts.
      - **`killgame.sh` cannot finish the job.** The game left a **zombie**
        (`[game] <defunct>`) whose parent is a WSL interop relay (`/init`,
        `Relay(NNN)`) that **ignores SIGKILL from inside the VM**. killgame.sh
        reported "killed 0; still running: 1" and gave up, with no hint that no
        signal could ever fix it.
      - **The Controls legend survives as a WSLg ghost.** `padglhost` exits but
        the RAIL window stays painted by `msrdc.exe` with no X client behind it,
        so clicking X does nothing — there is nothing left to receive the close.
        `msrdc` is protected (`Stop-Process` → Access denied), so the only cure
        found was **`wsl --shutdown`**.
      - Fix direction: closing the window should tear down the whole run
        (playfield, Controls, card mounts); `alive.sh` should count interop
        stubs and `fuse2fs` orphans; `killgame.sh` should recognise a zombie
        held by an interop relay and say plainly that only `wsl --shutdown`
        clears it, instead of reporting a number and stopping.

- [ ] **9. Virtual playfield needs real bandwidth.** David asked directly: at
      least **30 fps** feedback on coil, LED and switch state, **LED brightness
      shown by BOTH transparency and size**, and "full bandwidth to this virtual
      playfield". Tk canvas has no alpha, so transparency has to be faked by
      blending the fill toward the background colour. 9p round trips are the
      suspect for the current rate; a socket transport is the recommended fix.
      *Note: the old stake that playfield polling was degrading WSLg audio is
      GONE — item 10 removed WSLg from the audio path entirely.*

- [ ] **7. Switch input unreliable during keyboard play.** A playfield-window
      scoop click did not register and plunge looked dead. Prime suspect is the
      two-writers clobber `swhold.py` already documents: **padglhost rebuilds
      the whole `held[]` array from its own key state on ANY key event**, so
      anything another writer put in `padsw` is wiped the moment David touches
      the keyboard. This one breaks *playing the game*, which is why it sits
      above the two cosmetic video items.

- [ ] **6. Scene video noise in the TV inset.** The inset draws pink/green
      horizontal noise where character footage should be — NOISE, not black, so
      the frames arrive and are drawn but interpreted wrongly. The log points at
      SIZE: the inset clips are the only **520x294** streams
      (`4e0bf266…/35.asset/0.asset` and `14.asset`). Suspect stride/pitch
      handling for a width that is not a tidy multiple.

- [ ] **11. Background video stutters every ~7 seconds.** Regular, periodic,
      visible on the main game screen. **NOT the clip loop boundary** — that is
      the obvious guess and it is wrong: the background is `264.asset/0.asset`,
      1965 frames, re-serving every **65.78 s**. A frame-rate beat between the
      clip and the 60 fps present is the standing candidate.

- [ ] **3. The coil map.** `Diagnostics → Coil Test` fires one drive at a time
      and the 10 device-test coils already have names and positions in
      `device_xy.txt`. Coil Test itself has not been reached yet. Use
      `coilread.py` (run on WINDOWS) to diff nonzero `(node,index,count,lvl)`
      around a fire. **48V needs the door CLOSED again (`swhold.py 33 1`)**
      before anything will fire.

- [ ] **1b. LED fade decode.** Second half of playfield LED rendering; 1a (stem
      joining, 113 channels → 81 fixtures) is done.

- [ ] **4. Boot buzz — PARKED, deliberately.** ~20 Hz stutter in the first ~10 s.
      Balanced rather than fixed: `PAD_NB_RESET_US=1000000` takes it from 118
      voice restarts to 3 at no cost in boot time. Now sits at 5, at the bar.
      **The metric is a race** (0.1 s = 118, 1.0 s = 3, 2.0 s = 17), so treat
      3 vs 5 as noise, not a trend. Do not reopen without a reason.

## Done

- [x] **10. Audio.** SOLVED 2026-08-05, `13c4410` / `7a81cb1` / `5ec9681`, David:
      "this is working great". The WSLg → Windows hop was destroying the audio
      (+16.4 dB residual, error louder than signal); the rig now plays through
      **PortAudio** (`padplay.py`), scoring -14.7 dB, level with Windows playing
      the file directly. **The lasting lesson is about measurement:** a tone test
      and three click-counters all declared that path healthy. `audioscore.py`
      is the instrument that works.
- [x] **8. Switch-input logging.** Built and live; `sw_shm_edges()` in hwshim.c.
- [x] **5. Window position + size restore.** Drag-verified across a run restart.
- [x] **2. Attract audio.** Measured; it is correct machine behaviour.
- [x] **1a. Playfield LED stem joining.** 113 channels → 81 fixtures.
