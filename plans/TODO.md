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
- **`alive.sh` must print 0 after every run.** Confirm it, do not assume it —
  **and confirm it FROM INSIDE WSL.** `wsl -e bash .../alive.sh`, never from
  Git Bash: Git Bash's `pgrep` sees only Windows processes, so every pattern
  misses and it prints `TOTAL STILL RUNNING : 0  (clean)` over a fully live
  rig. `killgame.sh` the same way prints `killed 0; still running: 0`, which
  reads like success. On 2026-08-06 that pair of confident zeros led to a
  SECOND full run being started on top of a live one — two guests, two
  padglhosts, two padvidhosts on one ring. Both scripts now test for a
  readable `/proc` and **refuse with exit 2** rather than reassure.
- **Never let two scripts define the same fact.** `alive.sh` vs `killgame.sh`
  disagreed about what a running rig is; `autoattract.sh` vs `status.sh`
  disagreed about what "past Tech Alerts" means, so the app showed "Waiting at
  Tech Alerts" for a whole run while the game sat in attract mode. Both are now
  single-sourced (`alive.sh --total/--procs`, `gamestate.sh`).
- **Anything a run starts goes into `alive.sh` the same day.** It is the rig's
  only definition of "clean", and it has been wrong twice. `killgame.sh` and
  `status.sh` ask it (`--total` / `--procs`) rather than keeping their own
  lists, so there is exactly one place to add to.
- **Never run two measurement runs at once.** `killgame.sh` is global, so the
  older script's teardown kills the newer run mid-boot.
- **David pushes straight to main. No PRs.**

## Queue

- [ ] **6. Scene video noise in the TV inset.** ← IN PROGRESS
      The inset draws pink/green horizontal noise where character footage should
      be. Long form: `spike2_pc_emulation_handoff.md`, item 6.
      **★★ THE BYTES ARE A 1360-WIDE RASTER. MEASURED, WITH A CONTROL, OFFLINE.**
      `tools/spike2_emu/framewidth.py` inverts the converter and re-folds the
      recovered Y at every width, scoring vertical smoothness. On the known-good
      frame it returns **520 (2.66 against a shuffled control of 34.31)** — that
      is the labelled example it had to agree with first. On the noise capture it
      returns **1360 (2.02 against 23.84)**, a sharp minimum (1356→2.42,
      1440→7.79), and the width it was actually READ at, 520, scores **22.34
      against a control of 23.80 — no better than noise.** Refolded at 1360 the
      capture comes back as a coherent picture with smooth gradients and a
      vertical edge (`C:\tmp\spike2_item6\refold_1360.png`).
      **So the inset uploads 229,320 bytes taken from the START of a 1360x768
      I420 frame** and converts them as 520x294: its Y is that frame's top ~112
      rows, and its U and V are two further slices of that frame's Y plane, which
      is why the result is chroma-dominated and why the tint is just how bright
      the big frame happened to be there. The item's own "big frame read as
      small" control render has the identical stripe structure.
      **This closes the item's central question — the pixels are another
      stream's — and it re-opens ONE thing an earlier pass closed too broadly:**
      "the size theory is dead" is true of the converter, the negotiated caps and
      the draw, and FALSE of which bytes reach the converter.
      **★ THE DRAW IS FINE. CONFIRMED LIVE 2026-08-05 ON THE REAL INSET.** With
      `PAD_VID_TESTPAT=520x294`, the TV monitor in the Planet X Controller scene
      rendered the pattern **perfectly**: square white grid every 32 texels, red
      rising left-to-right, green rising top-to-bottom, no shear, no doubling.
      That is this item's own decision table, and it says **the pixels were
      wrong and the draw is fine.** Screenshot: `C:\tmp\spike2_item6\HIT_screen.png`.
      **So these are now CLOSED, not merely unlikely:** the quad's UVs, the
      render-target/FBO path, client-side vertex arrays, mipmap/LOD, and every
      remaining form of the size/stride theory. The pattern is injected AFTER
      conversion (padglhost.c says so), so a clean pattern exonerates the draw
      and upload and deliberately tells you nothing about the data — which is
      exactly the half that is left.
      **★ AND THE REASON IT TOOK FIVE RUNS WAS NOT THE TRIGGER. IT WAS CREDITS.**
      A machine with no credits ignores the Start button *silently*: the switch
      reaches the game (`+36`/`-36` logged at the asked-for duration) and no game
      starts. Every instrument said the press was delivered, so "the press
      worked" and "a game started" looked like one claim. Three Start presses
      over ten minutes left this run in **attract mode** — screenshot-confirmed,
      and only video channel 0 ever streamed. Coins in (`plunge.py coin`, switch
      39) and a game came up: 4 players, a real score, GODZILLA POWERUP LEVEL 1.
      **The taunt then fired three times in fifteen minutes**, against one
      sighting in ~25 attempts across five previous runs. It was never rare. The
      game was never in a game. Use **`plunge.py game`** (coin, start, plunge).
      **★ THE NEW PRIME SUSPECT: the inset arrives on a SHARED, RESIZED ring
      channel.** It streamed on **ch3**, and ch3 carried **63 clips at 1360x768
      and 3 at 520x294**, switching size back and forth within seconds, while
      ch0 streamed 1360x768 concurrently. Every measurement that ever declared
      this chain healthy used **one channel at one size**: `vidcheck.py`
      offline, the attract background, and `PAD_VID_FORCE_SIZE=520x294` on
      attract. **The variable was never the size — it was how many channels are
      live and whether one is being reused at a new size.** Next: re-run with
      `PAD_VID_TESTPAT` OFF and `PAD_VID_SNAP=520x294`, and compare the uploaded
      RGBA against what `padvidhost` decoded for that channel and generation.
      **Ruled out with a control:** the noise rows are not rows of our source
      frame. Best-match cost **186.7** real vs **186.7** against a SHUFFLED
      source, collapsing onto 3 unique target rows of 294. Consistent with the
      test-pattern result: the texture is sampled correctly, the data in it is
      not ours.
      **Ruled out as an offline test:** correlating the inset against the rest
      of the screen to test the FBO theory. The two existing captures' surrounds
      correlate **+1.000**, so the control has no power. Do not re-run it.
      **Instrument fixes this pass, both from being bitten:** the new-video-size
      burst was **20 frames — one third of a second** — and all 20 missed the
      inset, because the clip starts seconds before the element draws; it is now
      600 frames (`PAD_VID_BURST`). And `PAD_GL_DUMP`'s `dump_max=40` is spent in
      the first 20 s, so any frame read later in a run is stale — a 20-second-old
      Tech Alerts screen read as "the game is stuck" until the log said otherwise.
      `shotwin.py` also falls back to **COPY MODE** on these RAIL windows and
      grabs whatever is on top: it returned the *Controls* window while reporting
      it had found the game window. A plain desktop `CopyFromScreen` is what
      worked.
      **★★ AND THE MECHANISM IS CHANNEL TAKEOVER, measured live 2026-08-06.**
      Two facts, both from the log rather than from reading code: **the game asks
      for caps ONCE per pipeline and never again** (one `caps 1360x768 -> its own
      pad` line, then NINE `streaming` lines with the size changing underneath
      it — it loops by SEEKING, so its texture geometry is frozen for the life of
      the pipeline), and **every new pipeline steals a channel** (four channels,
      `pipeline` is never cleared, so after four clips every new one takes the
      slot of a stream that is not currently `playing` — which a clip that just
      hit EOS is, while its decoder is still on screen). The inset negotiates
      520x294, its clip ends, its channel is handed to a 1360x768 background
      clip, and its decoder keeps uploading from a ring now full of someone
      else's frames. That is why ch3 carried 63 big clips and 3 small ones.
      **★★ AND IT NOW REPRODUCES IN ATTRACT, EVERY RUN, WITHOUT A GAME.**
      `PAD_VID_ALT_SIZE=520x294` printed the fault in its exact real-world
      direction: `** WRONG-SIZE VIDEO UPLOAD ** 520x294 (229320 bytes) read from
      ch0 slot0, but ch0 is serving 1360x768 (1566720 bytes)`. Same 229,320-byte
      read landing on a 1360x768 frame that `framewidth.py` measured off the real
      capture. **The taunt is no longer needed to work on this item.** Be honest
      about the flag's limit: it changes size under a LIVE pipeline, which real
      playback never does, so it reproduces the fault but not the route to it.
      **Fixed:** `gstvid.c` records the size the GAME was told (`told_w/told_h`,
      set in `pad_vid_get_int` — NOT at prepare(), which re-runs on every rewind
      and would keep the field uselessly in step with the channel) and refuses to
      hand over a frame once the channel serves something else, holding the last
      good frame instead; channel stealing is now least-recently-used rather than
      first-in-array; and `padglhost` drops a mismatched upload outright
      (`PAD_VID_NOSIZEGUARD=1` to A/B it on one build).
      **★★ CONFIRMED ON THE REAL TAUNT, IN A REAL GAME.** The 520x294 clips
      served were `4e0bf266.../scene.assets/35.asset/0.asset` and `1.asset` —
      the Planet X Controller taunt itself — and both guards fired on it:
      `[vid] ch2 NOT MINE ANY MORE: the game holds 520x294 but this channel now
      serves 1360x768. Holding the last frame after 0.` plus the host's
      `WRONG-SIZE ... read from ch2 slot2`. So the route IS channel takeover,
      not merely something that produces the same disagreement.
      **"After 0" is the sting:** the taunt lost its channel before it played a
      single frame, so the corruption is gone but the inset was blank rather
      than playing. The cause is a burst — the scene builds THREE pipelines in
      130 ms (padvid at 223.49/223.56/223.62) — against only four channels.
      Hence `PADVID_CHANNELS` 4 → 8 (padvid.h **v3**, header 4096 → 8192 because
      eight 564-byte structs no longer fit; the static assert caught it).
      **Fixed:** `gstvid.c` records the size the GAME was told (`told_w/told_h`,
      set in `pad_vid_get_int` — NOT at prepare(), which re-runs on every rewind
      and would keep the field uselessly in step with the channel) and refuses
      to hand over a frame once the channel serves something else; a **request-
      generation check** beside it catches a SAME-SIZE takeover, which the size
      check cannot see and which most of this game's clips would be; stealing is
      least-recently-used **with fresh streams protected** (bumping `last_use` on
      create and prepare — without that, LRU picks the NEWEST stream, which was
      my own regression and the exact wrong end for a 130 ms burst); and
      `padglhost` drops a mismatched upload outright (`PAD_VID_NOSIZEGUARD=1`).
      **Committed:** `longplay.sh` (`355e0bd`), the control-tested findings
      (`11a8b44`), `PAD_VID_BURST` + `plunge.py coin`/`game` (`4dab1ad`),
      `framewidth.py` + the 1360 finding (`ccce594`), the guards (`36d82a1`),
      8 channels + the alive.sh safety fix (`c389572`).
      **Verified so far:** normal attract unbroken (12 streams, video playing,
      zero guard trips, `fix_normal_1.png`); ALT_SIZE reproduction goes from
      repeated wrong-size uploads to **zero**, caught by the guest guard; and an
      in-game 520x294 upload measures **TRUE WIDTH 520 (2.57 vs shuffled 35.37)**
      on `framewidth.py`, against 1360 before.
      **Resume:** the last acceptance test is whether, with 8 channels, the
      taunt now PLAYS — `serving 520x294` followed by frames actually consumed
      and NO `NOT MINE`. Run `watch.sh` then `longplay.sh <log> 13 520x294`.
      **A 15-minute clean run on the 8-channel build did NOT see the taunt at
      all** (zero 520x294 clips, and the game fell back to attract partway), so
      budget more than one run for this — it fired ~223 s into one run and not
      once in another. Nothing was learned about the fix from that run beyond
      "attract still healthy, zero guard trips".
      If it still gets stolen when it does fire, the next lever is not more
      channels but releasing a stream's slot when its pipeline is torn down —
      `pipeline` is never cleared, so every slot is permanently "occupied" and
      stealing is unavoidable no matter how many channels there are.

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

- [ ] **1d. The a2 / b4 / b5 payload.** All that is left of the LED wire that
      might carry lamp data: **~0.25 frames a second in attract**, 15 in a
      60 s window. `cmd a2` with a 6-byte body is the bulk of it and its
      SHAPE is known — `(start_lamp, 0x80|end_lamp, then 4 payload bytes)`,
      the same range prefix as the 2-byte frames, verified 45/45 on both
      positions. The four payload bytes are NOT understood: patterns like
      `00 ff 0a 00` and `ff 00 00 0a` look like (from, to, rate, ...) but
      nobody has shown it, so nothing is decoded. The longer a2 bodies and
      `b4`/`b5` are a different shape again — **ruled out: the a6 bitmap
      layout at payload width 1, 2, 3 and 4** (a2 fits at best 7 of 40).
      Capture with `PAD_LED_SKIP_LOG=N`; the oracle for confirming any of it
      is `Diagnostics → LED Tests`.

- [ ] **13. Save and load save states.** Freeze a live game and resume it later
      at the same ball, score and mode. David picked this reading explicitly
      over the two cheaper ones: it is NOT a boot skip (`autoattract.sh`
      already reaches attract in ~14.5 s) and NOT an NVRAM/card rollback.
      **`savevm`/`loadvm` DO NOT EXIST HERE** — the rig is qemu-**user**
      (`qemu-arm-static` under binfmt_misc, `run_game.sh:2`), and snapshots are
      a qemu-**system** + qcow2 feature. Do not spend a pass hunting a monitor.
      **CRIU is the only standing candidate and it is not installed.** The
      kernel does not block it (`CONFIG_CHECKPOINT_RESTORE=y`, WSL2
      6.6.87.2-microsoft-standard) but **`CONFIG_INET_DIAG_DESTROY is not
      set`**, and a live run holds a TCP connection from `padrelay.py`
      (`0.0.0.0:<port>`) to a **native Windows** `padplay.py` that is not in the
      checkpoint at all — so a whole-tree checkpoint/restore is off the table
      before it is tried. **GUESS, not established:** checkpoint only the guest
      side (`arm-binfmt` + `game` + its shm rings) and RE-START every host-side
      helper on restore. The restore surface is everything `alive.sh` counts —
      13 process shapes plus the `fuse2fs` card mount and the padled/padsw/
      padgl/padvid rings. Detail in the handoff under **REMAINING item 13**.
      **Acceptance:** save mid-ball, restore, and the ball number, score and
      running mode match; play continues 60 s; `alive.sh` prints 0 after.
      Oracle is `shot.py` before and after. **Name collision:** `save_state` in
      `playfield.py` is the WINDOW POSITION save — grep will mislead you.

- [ ] **4. Boot buzz — PARKED, deliberately.** ~20 Hz stutter in the first ~10 s.
      Balanced rather than fixed: `PAD_NB_RESET_US=1000000` takes it from 118
      voice restarts to 3 at no cost in boot time. Now sits at 5, at the bar.
      **The metric is a race** (0.1 s = 118, 1.0 s = 3, 2.0 s = 17), so treat
      3 vs 5 as noise, not a trend. Do not reopen without a reason.

## Reference material that is NOT in this repo

- **`C:\tmp\spike2_audio_ref\`** — the audio calibration set, with its own
  README. The source WAV plus three captures David has already labelled
  (flawless / crackly / fixed) and their expected `audioscore.py` scores.
  **Any new audio metric must reproduce that ordering before it is trusted** —
  three metrics built on 2026-08-05 failed exactly that check. Also holds
  `fullplay.sh`, which drives the real `playaudio.sh` end to end, and `feed.py`,
  which paces a WAV into a FIFO at exactly the right byte rate (`ffmpeg -re`
  runs ~3.6% slow and starves the player, which then scores as damage).
- **`plans/spike2_pc_emulation_handoff.md`** — gitignored on purpose, local to
  this machine. The deep detail behind every numbered item above.

## Loose ends worth a look, not yet worth a queue slot

- **`padrelay.py` accepts in a `while True` loop and never exits**, where the
  `audiotcp.py` it replaced did not. `playaudio.sh` ends on `wait $SRV`, so the
  script may now outlive a run instead of returning when the player goes away.
  Teardown pkills it either way, and `alive.sh` counts it now, so a leak would
  at least be visible — but it was not deliberate and it is untested.
- **`playaudio.sh`'s `win_kill` can shoot itself.** Its `Stop-Process` filter
  matches on CommandLine only, and its own command line contains the pattern,
  so powershell.exe is a match for itself. It has always worked in practice
  (the real player is enumerated first), and the two backstops added in item 12
  avoid it by also requiring `Name -like 'python*'`. Same shape, one line.
- **The coin door now lags up to 250 ms** on the virtual playfield: it is read
  every 8th frame instead of every frame, because it is a second round trip
  across the VM boundary for a switch a human flips by hand. If that ever feels
  wrong in use, the fix is to read it on demand after a click rather than to
  raise the rate.
- **RESOLVED 2026-08-05: attract-mode LED churn has been watched end to end,
  and the static half of it is fixed.** The game reaches attract (screenshot:
  the high-score attract screen); the lamps moved 21 marker clusters per 3 s
  with half the frames being dropped, and **33 per 3 s** once the a6 fade
  frames decoded (item 1b). What still drops is item 1d, and it is now
  ~0.25 frames a second.
- **The playfield's polite close failed in one card run out of three.** Removing
  `dump/padled` is meant to make `playfield.py` leave within ~2 s; once it was
  still up after 5 s and had to be closed the hard way, which loses nothing now
  but is unexplained. Suspect `\\wsl.localhost` read caching hiding the removal.
- **New dependency on a fresh machine:** the Windows-side player needs
  `py -m pip install sounddevice`. Without it `playaudio.sh` falls back to WSLg
  audio and says so loudly, so it degrades visibly rather than silently.

## Done

- [x] **7. Switch input unreliable during keyboard play.** DONE 2026-08-05, `26c9ebf`.
      **A 3000 ms `swpoke` press was reaching the game as 334/465/437/420 ms —
      14% of what was asked. It is now 3003/3002/3002/3003 ms.** The clobber was
      exactly what this item suspected: `sw_publish()` in padglhost memsets and
      rebuilds `held[]` from key state alone, over the one array the scripts also
      wrote. `padsw` now has **three regions with one writer each** — keyboard,
      scripts, and the merged answer the guest publishes back — and the shim
      merges by **LAST EDGE WINS PER ID**.
      **Not an OR, and that is the whole design.** padglhost latches the coin
      door and all six trough balls ON at window open, so an OR would have left
      `plunge.py` permanently unable to take a ball out of the trough: a stomp
      swapped for a deadlock, and the deadlock looks deliberate. Last-edge-wins
      means a rebuild that re-asserts what was already there moves nothing,
      while a key that genuinely moves still wins instantly (both directions
      confirmed live).
      **It could not be measured before, which is why it sat this long.** The
      trigger is a key press and a key press cannot be injected — SendInput into
      WSLg is UIPI-blocked and this WSL has no X tools. `PAD_SW_KEYSIM=<ms>`
      makes padglhost call the same `sw_publish()` on a timer, so the fault
      reproduces on demand; that is what produced the before numbers above.
      **Also fixed end to end:** `plunge` used to log `-71` then a `+71` nobody
      asked for 376 ms later (ball back in the trough before the shooter lane
      had even closed) and now runs its real 450/1200 ms story; a script-latched
      coin door survived 6584 ms and ~13 republishes with the game drawing its
      own `48V DISABLED` banner, screenshot-verified both ways.
      **Bonus, and a stale comment killed:** padglhost's source claimed the
      PLAYFIELD keys were inert (`live = 0`). They are not — holding 59+60
      opened the game's own `CHOOSE YOUR MODE OF PLAY` and released back to
      attract. The legend text had been corrected; the comment had not.

- [x] **1c. The LED frame shapes that were still dropped.** DONE 2026-08-05, `4695bbd`.
      **`skipped` in attract went 225 → 15 per 60 s** (and decoded held at
      834), because 88% of what was still being counted as "not decoded" was
      never lamp data at all.
      **The 2-byte a4/a5 frames are a RANGE, not (index, value):** body[0] is
      an announced lamp 318/318, `body[1] & 0x7f` is an announced lamp
      318/318, bit 7 is set 318/318, and `body[1] & 0x7f == body[0] + 1` in
      90% (the rest are wider spans, 23→47, 30→38). **The one-line `{0,0}`
      shape this item proposed would have been WRONG** — it would have written
      a lamp NUMBER into a brightness. What hid it: the second byte never dips
      below 0x85 in 399 samples because it is `0x80 | a lamp number`, and my
      own first test asked whether the RAW byte was an index, got 0/399, and
      concluded "it must be a value". A rigged question — bit 7 is set in
      every sample, so that test could never have said yes.
      These frames are now recognised and NOT counted as skipped, so the
      playfield's "N frames NOT decoded" stops being a permanent false alarm.
      They still show up under `PAD_LED_SKIP_LOG`. Remainder is item 1d.

- [x] **1b. LED fade decode.** DONE 2026-08-05, `b5bb67a`. The fade frames are **`cmd a6`
      on the insert boards**, and the format is
      **3 payload bytes, then a BITMAP over the board's own enumerated LED
      list (LSB-first, truncated after the last set bit), then one level byte
      per set bit**, levels `0x00 / 0x7f / 0xff`. Decoded in `hwshim.c`.
      **Attract, before → after: `decoded` +229 vs `skipped` +225 → `decoded`
      +684..851 vs `skipped` +203..212 in the same 60 s window**, and LED bytes
      moving in a busy 20 s window went from single digits to 306. The
      playfield's visible change rate went from 21 to 33 marker clusters per
      3 s. `1a` (stem joining, 113 channels → 81 fixtures) was already done.
      **How the mapping was established without the operator menu**, because
      "it looks plausible" is the trap this item warned about:
      - the split is forced — 44 of 45 frames have exactly ONE split whose
        level region is drawn purely from {00,7f,ff}, and scanning mask length
        upward and taking the first fit lands on that same split, so the
        decoder needs no heuristic;
      - **raw index is dead**: node 9 announced 71 LEDs at indices 0,1,8..87
        and has NO lamp at 2..7, so a raw reading addresses hardware that is
        not on the board **21% of the time** (160 of 769 bits) against 2/769
        for the enumerated-list reading, and a 9-byte mask is exactly
        ceil(71/8), the longest ever seen;
      - **against a control**, because the first test tried (overlap with the
        indexed path) had NO power — a shuffled control scored the same, 26%
        vs 26%. Shuffling the announced list keeps every lamp valid and
        destroys the structure: complete RGB triples addressed in one frame go
        **23 (this mapping) vs 1 (shuffled) vs 4 (raw)**.
      **The one thing still unproven:** that the k-th announced LED is the
      lamp the TABLE calls index k. This is verified against the BOARD, not
      against the physical playfield, so a systematic permutation within a
      board would render a coherent-looking light show and still be wrong.
      The oracle for that remains `Diagnostics → LED Tests`, one fixture at a
      time BY NAME. Also: 1 frame in 45 first-fits to the wrong split and
      writes wrong values for that frame; the next frame corrects it.

- [x] **9. Virtual playfield needs real bandwidth.** DONE 2026-08-05, `19e1b85`.
      **15 fps → 30.3 fps**, measured the same way on identical input, and
      brightness now shows as marker SIZE and opacity (blended toward the
      artwork sampled behind each insert, since Tk has no alpha). **The
      queued diagnosis was wrong and the measurement was cheap:** 9p is
      3.4 ms a read regardless of size, a 147 fps ceiling, so the socket
      publisher was not needed and was not built. The time was going to
      Windows' 15.6 ms scheduler tick (Tk's `after(29)` delivered 35 ms until
      `timeBeginPeriod(1)`) and to repainting all 81 fixtures every frame
      whether or not anything changed. **Holding the file handle open, listed
      as a cheap partial fix, is a trap: it reads a client-side cache and
      returned 0 for a whole test while the truth reached 188.** The rate is
      now measured and shown in the status bar, with `PAD_PF_LOG` for detail.

- [x] **12. Closing the game window leaked processes and stranded a ghost
      window.** MOSTLY CLOSED 2026-08-05, `227cab6`. `alive.sh` counted 5 of the 13 things
      a run starts and reported "clean" over seven leaked interop stubs and
      three orphaned card mounts; it now counts all of them and is the single
      list `killgame.sh` and `status.sh` ask (`--total` / `--procs`). Teardown
      closes the playfield (Windows side FIRST — killing the stub leaves the
      Windows process alive, the reverse is clean) and unmounts the card it
      mounted; a zombie held by an interop relay is now named as unkillable
      with `wsl --shutdown` as the cure. **The ghost window itself is UNPROVEN:
      it did not reproduce, and it CANNOT be driven from a script — WM_CLOSE
      and SC_CLOSE to a RAIL window are both ignored by msrdc (UIPI), and this
      WSL has no X tools to close from the other side. Reopening it needs
      David to click the X while someone watches.** The Emulate tab's button is
      now "Restart WSL…" and names the stranded window, since `wsl --shutdown`
      remains the only known cure.

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
