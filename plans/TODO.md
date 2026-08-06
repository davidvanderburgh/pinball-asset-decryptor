# Spike 2 PC emulator — task queue

**`/next` takes the OPEN item with the LEAST PROGRESS**, tie-broken on which is
easiest — the full rule lives in `.claude/commands/next.md` under "Which item
to take" and is not restated here, because two places defining one fact is how
this rig has been bitten before. An item nobody has touched is 0% and outranks
one sitting at 85%, so the queue advances on a broad front instead of grinding
one item down. **Order on this page is presentation, not priority**; it is only
the last tie-break, which is what moving lines around is still good for.

The `S1`–`S3` and `D1`–`D5` on each open item are its **severity and
difficulty, and together they break the tie** between items at the same
progress: severity first, then difficulty. **Lower is taken sooner in both** —
S1 is the worst thing, D1 is the cheapest job. Roughly, S1 breaks playing the
game, S2 costs runs or makes other items more expensive, S3 is friction with a
workaround. Both ladders live in the same place as the selection rule,
`.claude/commands/next.md`, and are not restated here for the same reason.

**Severity was added on 2026-08-06 because difficulty alone kept sending the
next pass at the cheapest item** — three severe faults in a row lost to a
settings bug, since a settings bug is always cheaper than a video fault. It
sits BELOW progress on purpose: above it, one S1 item at 90% would be ground
down while five items sat at zero.

**D is an estimate of what is LEFT**, so it moves as passes learn: a cracked
mechanism makes an item cheaper even when the percentage barely moved, and
finding out the fault will not appear on demand makes it dearer. **S moves
rarely and only on evidence** about the fault itself, never to justify the
effort an item turned out to need.

Each item's full technical detail lives in
`plans/spike2_pc_emulation_handoff.md` under **REMAINING item N** — the numbers
here are those numbers, so they stay stable as this list is reordered.

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

- [ ] **23. The game exits by itself mid-play. It is NOT a crash.** `S1 D4`
      **Observed 2026-08-06 (David), one sighting:** *"emulator just crashed
      when i clicked out into Claude"* — a game in progress, ~181 s into the
      run, and the guest process was gone. Logs preserved before the next run
      could overwrite them: `/home/david/crashlogs/gzpad_crash_1406.log` (7744
      lines), plus `padglhost_crash_1406.log` and `padvid_crash_1406.log`.
      **ESTABLISHED, and it changes what to look for: there is NO crash
      signature anywhere in the log.** Zero `SEGV`, zero `Segmentation`, zero
      `FATAL`, zero `Radium Error`, zero abort or assert. What the log ends with
      instead is the game's OWN shutdown: `[thread] #3 RETURNED body=0x4efef0`
      then `[thread] #2 RETURNED body=0x447440`, and those two were created at
      log lines 69-81, i.e. at the very start of the boot — the longest-lived
      threads in the process, returning last. Then `ExchangeData: read failed`
      (the node bus going away behind them) and the process was gone.
      **From outside, "the game exited by itself" is what a Spike machine
      REBOOTING looks like**, and on a real machine something restarts it. Do
      not go hunting a memory fault; go and find out what asks those threads to
      return.
      **The renderer was healthy the whole time and is NOT implicated:**
      `padglhost` averaged 53.3 fps over 182.9 s, was still drawing at the end,
      and only stopped when `watch.sh` tore it down after the guest had gone.
      **NOT ESTABLISHED — that clicking away caused it.** That is one sighting
      and the only evidence is that the two coincided. Against it: `padglhost`'s
      log shows nothing at all around the exit, and the last switch edge was at
      171507 ms, **ten seconds before** the guest went — so no focus-driven
      switch storm reached the merge. Do not build a focus theory before the
      instrument below exists.
      **THE FIRST JOB IS AN INSTRUMENT, WHICH IS WHY THIS IS D4 AND NOT D2.**
      Nothing anywhere records WHY the process went down — `watch.sh` prints
      "the game exited" and tails five lines of VPU firmware noise, which is the
      guest's ordinary complaint about having no hardware decoder and says
      nothing. The shim should log the exit path: an `atexit` hook, whether
      `main` returned, and any signal it took. Until that exists a repeat
      sighting teaches nothing, which is exactly the D4 line.
      **Acceptance:** state it in two parts. (a) The instrument: any exit of the
      guest prints a reason line naming the path, demonstrated by provoking one
      deliberately. (b) Then, and only then, the fault: a game survives
      clicking away and back repeatedly (state how many times), or the exit
      reproduces and the reason line names it.
      — S1 because the game dying mid-ball is the thing you are playing WITH,
      not something you play around. D4 because the instrument does not exist,
      and because a single sighting is not a repro — a pass can end having
      learned nothing, which is the D4 definition.

- [ ] **21. Ball handling, and clear feedback about how many balls are in
      play.** `S2 D4` **★ DAVID, 2026-08-06: "we will need some sophisticated
      ball handling and clear feedback about how many balls are in play. for
      example, during multiball, many balls are in play. having clear feedback
      in the 'controls' or 'virtual playfield' window is very helpful (show
      images of pinballs loaded in the trough for example)."**
      — S2 because single-ball play works, so nobody loses a ball to this; what
      it costs is every run that wants multiball, and it is a capability nothing
      else can work around. D4 for the item as a whole, but **the two halves are
      very different prices and the cheap one lands alone** — say which you did.
      **(a) THE FEEDBACK HALF IS D2 DESK WORK.** Both windows David named
      already exist and both already have what they need: `playfield.py`
      (Windows/Tk) reads `mrg[]` over 9p every frame and already draws switch
      state, and `padglhost.c`'s Controls legend is drawn in X11 beside the
      switch keys. The trough is ids 71..66 = TROUGH 1..6 and `swshow.py`
      (`e1e9cb3`) already counts and prints it. Six ball images and a
      "N balls in play" line is drawing, not discovery.
      **(b) THE HANDLING HALF IS THE D4, and it needs item 3.** There is no ball
      MODEL anywhere in this rig — `plunge.py` opens one trough switch and works
      the shooter lane, and nothing tracks where a ball is, notices a drain, or
      feeds a second ball when the game asks for one. Multiball is the game
      firing the trough eject repeatedly and expecting balls to arrive; nothing
      answers. **Item 3 is upstream:** the fire frame is decoded (`cmd 0x40`,
      one coil by index) but the trough-eject index is NOT among the five that
      item 3 confirmed — it identified 2, 3, 4, 7, 8 from a ball search, and the
      eject is one of the unlabelled 0, 1, 5, 6. Without it the rig cannot tell
      "the game just asked for a ball" from any other coil, and the auto-feed
      has to be driven blind on a timer.
      **What item 20 established that this can build on** (`e1e9cb3`): the
      trough is a STACK with a known direction — 71 TROUGH 1 is the eject end
      (it sits at x=254 beside TROUGH JAM), 66 TROUGH 6 is the far end, balls
      are taken from the far end and a returning ball fills the far end first.
      So "eject a ball" and "a ball drains" are both one switch on a known end,
      and the model is a count plus that rule.
      **Acceptance:** state both halves separately. (a) with a game running, the
      playfield window shows the six trough positions filling and emptying as
      the count changes, and says how many balls are in play; screenshot it.
      (b) a multiball starts with more than one ball genuinely in play — the
      oracle is the game's own display, not the rig's model of itself, because a
      model that feeds itself will always agree with itself.

- [ ] **17. Keyboard switch input needs holding longer than a keystroke, and
      does not repeat.** `S1 D3` ← IN PROGRESS *(**D4 → D3 on 2026-08-06:** the
      mechanism is cracked, the instrument is built and validated, and the fault
      now reproduces on demand from a script — so a pass can no longer end
      having learned nothing. What is left needs a run, not a new instrument.)*
      **★★ MEASURED AND FIXED 2026-08-06. 35 of 72 closures reached the game
      before; 72 of 72 after — 4/4 at every duration on both nodes, including
      10 ms.** Long form: `spike2_pc_emulation_handoff.md`, REMAINING item 17.
      **The item's own suspicion was right in effect and wrong in location, and
      the location decides the fix. There is NO minimum closure width and NO
      debounce problem — there is a SAMPLING RATE, and it is the game's.**
      `swladder.py` poked switch 34 (node 1) and 46 (node 8) at
      10/20/30/50/80/120/200/400/900 ms, four rounds each, read off the game's
      own `entry[+24]` via `PAD_SW_PEND`. **Every failure had ZERO samples
      inside it** — the game had never looked at that node — and **every closure
      it did look at registered, down to 10 ms, off ONE scan with the switch
      made.** `0x11` is REQUEST-driven: the game asks per node when its service
      loop gets round to it, so the rate is entirely the game's, and the gap
      between two scans of one node **ran to 670 ms in attract**. Holding a key
      longer only buys more chances to be looked at.
      **Fixed (`sw_owed[]` in `hwshim.c`): a closure is OWED a scan.** Merged
      state going 1→0 having never been on the wire as made defers the release
      until the next scan of that switch's own node. One scan is enough —
      measured, not assumed. `PAD_SW_MINSCANS` raises it, `PAD_SW_LATCH=0` A/Bs
      it, `[swlatch]` prints the closure width and the wait each time it saves a
      press (**42 saves in the verification run**). One change fixes the
      keyboard and the scripts, because both writers land in the same merge.
      **WHAT IS NOT DONE, and it is why the box is open:**
      **(a) nobody has played it.** This is the script path; the keyboard shares
      the merge so the same latch applies, but David's hands are the final
      oracle and this fault is defined by how it feels. **(b) The "repeat" half
      is untouched, and its premise is now in doubt** — see the ruled-out list.
      **(c) The latch makes a press land LATE**, by up to the scan gap, which is
      strictly better than losing it but is a latency the real machine does not
      have. `nb_next_node()` already emits the whole node list per cycle, so the
      shim is not the limit; the service loop is the game's.
      **RULED OUT, with numbers, so nobody pays twice:**
      • **the X drain.** `win_pump()` drains from the idle poll as well as per
      frame (200 us for 16 empty polls then 2 ms) and the frame rate is 50-60
      fps over 301 samples — ~2-20 ms granularity, which cannot swallow a 60 ms
      keystroke. The SUSPECTED mechanism this item was filed with is dead.
      • **the auto-repeat peek eating the game's repeat.** It keeps `key_down`
      at 1 for the whole hold, and the GAME already auto-repeats a held cabinet
      switch (`padsw.h`, measured on the Main Menu; the whole `tap_reads` region
      exists for it). So "does not repeat" is NOT the peek, and the repeat half
      must not be built on that guess. **Ask David which key and which screen
      before writing any of it.**
      • **a flat inter-poke gap.** It phase-locks the ladder to the sampler:
      the first run had 400 ms missing 4/4 on node 8 while 10 ms landed 4/4 on
      node 1. `swladder.py` jitters now.
      **Two instrument faults, both of which cost a reading:** `PAD_SW_PEND`
      claimed 1 ms sampling and was on the SPI loop's ~20 ms coarse tick (fixed,
      now per transfer); and `swwidth.py` shipped with **the oracle inverted** —
      these levels are ACTIVE LOW, MADE is 0 — plus a 250 ms window that closed
      *before* the latched answer arrived, so the first read of the verification
      run wrongly said the fix had not worked. Window now runs to the next press.
      **New tools:** `swladder.py`, `swwidth.py`, and `[key]` in padglhost (the
      X event time per key edge — the third of this item's three timestamps, and
      the only one that knows how long a key was really held; the three clocks
      are never aligned, only differenced within themselves).
      **Committed:** `979b940` (measurement + latch + instruments).
      **Resume:** put hands on the keyboard. Play a ball with `[key]` and `[sw]`
      both on and diff each key edge's X-time width against the closure the
      guest was handed; a normal keystroke must register every time. Then ask
      David what "does not repeat" means concretely — which key, which screen —
      because the obvious answer is ruled out above.
      — S1 because unreliable input is not a defect
      you play around, it is the thing you play WITH.
      **Observed 2026-08-06:** a normal-length keystroke sometimes does not
      register; the key has to be held noticeably longer than typing. Wanted:
      immediate like typing, plus hold and repeat.
      **NOT a regression of item 7, and not a duplicate of it.** Item 7 fixed
      WHO writes the switch array (three regions, one writer each, last edge
      wins); this is WHEN the game looks at it.
      **Acceptance:** a tap of ordinary keystroke length registers as a switch
      close in the guest every time (state the length you tested, do not assume);
      a held flipper key stays closed as long as it is held; a held menu/service
      key repeats. Oracle is the guest's own `[sw]` lines against the X event
      times, plus David's hands, since this fault is defined by how it feels.
      **The script half of that is now met: 10 ms, 72/72.**

- [ ] **16. Log replay mode: re-run a session's switch inputs from its log.**
      `S2 D4` ← IN PROGRESS — S2 because play works without it; what it costs is
      every other item's runs. D4 because the parse and the driver are desk work
      on a primitive that is already
      validated, but confirming it takes runs, the log needs a new field first
      (a guest-side change and a rebuild), and the comparator does not exist yet.
      **★ DAVID, 2026-08-06: "in order for the replay to be effective we need the
      performance issue worked out completely... if there is any slowdown or
      stutter or lag then the replay will not work effectively." He is right,
      and it decides the CLOCK the replay runs on.**
      This rig has already proven the point in miniature: `padsw.h` records that
      a menu press expressed in MILLISECONDS is a lottery — on the Main Menu
      120 ms and 200 ms moved the cursor 0 rows, 250 ms moved 1 or 2, 300 ms
      moved 3 — because what decides it is how many SPI transfers land inside the
      hold. That is why `tap_reads` counts TRANSFERS. **A replay scheduled in ms
      inherits that lottery for every edge, not just the menu ones.**
      **And the guest clock does NOT fix it, which is the trap worth writing
      down before someone builds on it.** `pad_ms()` is CLOCK_MONOTONIC, so the
      guest's millisecond is wall time; `guest_t0_ms` removes drift between the
      driver and the guest as two PROCESSES, and does nothing about the guest
      falling behind the wall. The lag-tolerant unit is the same one item 17
      already found: **the guest's own SPI transfer count**, which advances with
      the game rather than with the clock. Offer both, default to transfers, and
      state which was used in the diff.
      **So items 18 and 11 are upstream of this one**, and 18 is S2 from today
      for that reason.
      **Established this pass, offline, from logs already on disk:**
      • `gz_item15.log` is 1611 edges over 591 s and is **almost entirely
      scripted** — 4 edges are autoattract's switch 28, the rest are longplay.sh
      pokes at ~90 ms plus plunge.py's coin/start/plunge. A replay of it replays
      a random walk, which makes it a fine test vehicle and a poor demo.
      • the two-way keyboard/script split does NOT give provenance:
      **autoattract.sh presses Service Back through `swpoke.py`**, so the rig's
      own boot press is a script edge like any other.
      **RULED OUT / CORRECTED — this item's own text was wrong:** it claimed
      "the launch line is logged verbatim with `PAD_CARD=`". It is not. **watch.sh
      never echoes its own configuration**, and `PAD_CARD` appears in zero recent
      run logs. The config gap is real and is a second thing to close, not a
      thing already done.
      **★ THE INSTRUMENT HALF IS DONE AND CONFIRMED ON A LIVE RUN**
      (`gz_item16.log`, 3 min attract, `alive.sh` 0 after). Every `[sw]` edge now
      carries the letter of whoever moved it:
      • `[sw] 21191 ms +28a` — autoattract's Service Back, tagged `a`, which is
      the exact case the keyboard/script split could NOT resolve;
      • `[sw] 160692 ms +59r` — a direct writer under `PAD_SW_SRC=r`;
      • `kbd_src` read `w` live — padglhost's window-open latch, distinct from a
      key press.
      **The clock is exact, measured on four edges: asked at guest_ms 105099 →
      logged 105100 (1 ms), 105251 → 105251, 160692 → 160692, 160844 → 160844
      (0 ms).** A host script can schedule against the guest's own millisecond
      with no log to tail.
      **RULED OUT — the "second gap" this item listed is a non-issue, and it was
      verified rather than argued.** The window-open latch (`[cabchg] 0 ms
      ff0f0f...`) produces NO `[sw]` line at all, because `sw_shm_edges()` primes
      its `prev[]` before the latch lands. A replay driven from `[sw]` therefore
      cannot re-apply it. Nothing to skip; do not build a skip for it.
      **AND THE RUN FOUND A BUG THE OFFLINE TESTS COULD NOT.** `PAD_SW_SRC` was
      only read inside `padsw.set_source()`, so anything importing `padsw`
      directly — a `python3 -c`, and the replay driver that does not exist yet —
      was tagged `?` however carefully its caller set the variable. The offline
      test missed it because it went through `swpoke.py`, which does call
      `set_source`. Read at import now. Both readings are in the run's log, which
      is a usable before/after: `moved by [?r]`.
      **Also shipped:** `[watch] cfg` lines (argv, game, minutes, and every set
      `PAD_*` — the run above recorded `PAD_NB_SILENT=2`, which changes what the
      run IS), and `swlayout.sh`, which proves the three hand-kept copies of the
      switch block agree and was validated by breaking an offset on purpose in
      both directions.
      **Committed:** `145e79b` (provenance + clock + cfg + swlayout),
      `52e3703` (the live confirmation and the PAD_SW_SRC fix).
      **Resume:** write `swreplay.py` and the comparator — but decide the CLOCK
      first, per the star above, and that decision wants item 18's profile.
      Everything the driver needs to READ now exists and is confirmed.
      **The want:** point the rig at a previous run's log and have it re-deliver
      that run's switch inputs at the same offsets, so getting back to a fault
      does not mean re-doing coin/start/plunge and a hundred flipper presses by
      hand. **The sample log is already MOSTLY enough**, which is the useful
      finding: `[sw] 24141 ms +28` / `-28` is the whole input stream (signed
      switch id on the guest ms clock), the launch line is logged verbatim with
      `PAD_CARD=` and the `watch.sh 120` backstop so the configuration replays
      too, and the zero point is derivable (run start 08:21:25 wall against
      `[sw] 24141 ms` at 08:21:49).
      **The one gap worth enriching is PROVENANCE.** `[sw]` does not say whether
      an edge came from the keyboard, from a script (`swpoke.py` / `swhold.py` /
      `plunge.py`), or from the rig pressing Service Back itself under
      `PAD_AUTO_ATTRACT`. Replaying all of them re-injects what the next run will
      generate again, so auto-advance would be doubled. **Item 7 already built
      the structure that knows the answer** — padsw has three regions with one
      writer each (keyboard / scripts / merged) — so emitting the region in the
      `[sw]` line closes it. Emitter is `sw_shm_edges()` in
      `tools/spike2_emu/hwshim.c` (item 8).
      **Second gap:** the window-open latch. `[cabchg] 3016 ms ff0f0f0000000000
      (was 0000000000000000)` is padglhost latching the coin door and six trough
      balls when the window opens; a replay must not re-apply those.
      **Injection is solved and measured:** item 7 got a 3000 ms ask delivered as
      3003 ms, so the driver is "parse the log, call the existing pokers".
      **Be honest about "exactly", because the acceptance test depends on it:
      input replay is not run replay.** The guest is a real ARM binary under
      qemu-user, and the two video faults this rig has already fixed both turned
      on timing — item 6 (now DONE) on a three-pipeline burst inside 130 ms,
      item 15 (now DONE) on channel assignment order. The same inputs will NOT
      give the same run, and a replay cannot make a rare taunt fire. What it buys
      is the manual labour, not determinism. **That both are closed does not
      weaken the point** — they are cited as proof that this guest's behaviour
      depends on timing the replay cannot reproduce, and being fixed does not
      make them less timing-dependent.
      **Acceptance:** a captured log replays with no keyboard use; the new run's
      own `[sw]` lines diffed against the source log show every edge re-delivered
      within a stated tolerance (measure it and state it, do not assume); and the
      run reaches a game where the source log reached one.
      **Related: item 13** is the checkpoint/restore route to a nearby goal and
      is blocked on CRIU; this is the input-replay route and needs no checkpoint.
      They may partly substitute for each other — do not build both blind.

- [ ] **11. Background video stutters every ~7 seconds.** `S2 D3` ← IN PROGRESS
      — S2 because you can still play through it, though 60.0 → 17.7 fps is
      nearer a malfunction than a quality defect and S2 is being held only
      because nobody loses a ball to it. **D3 → D2 on 2026-08-06:** the caller
      is now named (below), so the fix has a location instead of a choice; the
      storm reproduced twice inside one three-minute game, so it is no longer a
      fault you have to wait for; and **item 20 is CLOSED as of `e1e9cb3`**, so
      a stable game is no longer in the way — coin/Start/`plunge.py plunge`
      held Ball 1 for a full five minutes. What is left is a local change plus
      one confirming run.
      **★★ THE OPEN QUESTION IS ANSWERED: `caller=rewind`.** Read off a game
      David played on the current build 2026-08-06 and handed over as a crash
      report — **no run was spent on it.** Both storms in that session say the
      same thing, verbatim:
      `[vid] ch2 RE-ARM STORM: 8 prepares of ...35.asset/1.asset in a row, each
      delivering <=1 frame, caller=rewind` and the same for `35.asset/6.asset`;
      they ran **93 and 56 prepares**. So the runaway is `pad_vid_seek()` — the
      game's **EOS handler looping the clip** — and NOT
      `gst_element_set_state(PAUSED)` re-arming a pipeline it already has. Those
      two wanted opposite fixes (`gstvid.c:182`) and the guess is no longer
      needed. (The `caller=state` on the *ended* line is not a contradiction:
      `prepare_why` is one static naming the LAST prepare, so only the START
      line names the runaway.)
      **Two more facts from the same log, both free:** the storms were on
      **ch2, the 520x294 TV inset**, not on the 1360x768 background — the inset
      took **158 serves against ch0's 55** in three minutes; and the storm fires
      on the build that already has the ffprobe cache, so **caching the probe
      did not stop it** and was never going to. It made each prepare cheap; the
      loop is still there.
      **★ DAVID'S THEORY — "it stutters when LOGS ARE WRITTEN, maybe a separate
      logging thread" — IS RULED OUT, and the measurement that killed it also
      found the real cause.** Of 24 video stalls in his screen recording, **16
      are surrounded ONLY by video-pipeline churn and 0 are switch-only**; the
      single `[sw]`-only log burst in the whole recording was **smooth (8/9
      advances)**. The log line is the symptom. **Do not build a logging
      thread.**
      **Established, from two independent instruments that agree:**
      • **Every `serving` line is one `pad_vid_prepare`, and prepare BLOCKS THE
      GAME'S OWN UI THREAD** on `ack_gen` (`gstvid.c`), while the host did a
      full **ffprobe spawn before acking** — measured on this machine, idle:
      **23.4 ms** at 149 KB, 27.5 ms at 16 MB, **38.6 ms** at 60 MB.
      • In gameplay one channel re-served **the same file 17 times a second**;
      **116 of that run's 140 serves died after exactly ONE frame**.
      • **Screen recording** (outside WSL): 19 of 24 stalls within ±33 ms of a
      log write against a 16.7% chance rate; 19 two-second buckets with zero
      serves averaged **26.0 fps**, 5 buckets with ≥10 serves **20.0 fps**.
      • **eglshim, inside the guest**: 61 zero-serve buckets **58.7 fps**
      (mostly exactly 60.0), 4 busy buckets **31.1 fps**, worst **17.7**.
      corr(serves, guest fps) = **−0.622**.
      **★ THE ITEM'S OWN "NOT the clip loop boundary" RULING WAS WRONG, and it
      was wrong because it measured the WRONG CLIP.** It timed the background
      `264.asset/0.asset` (1965 frames, 65.78 s). The clip actually on screen in
      attract is **`2.asset/55.asset`, 240 frames = 8.00 s**, and it re-serves
      every 8 s — which fits David's "~7 seconds" far better than 65.78 s does.
      Confirmed on a 3 min attract run this pass: 14 loops, all of that one clip.
      **RULED OUT, with numbers, so nobody pays twice:**
      • **a separate logging thread** (above).
      • **`ffmpeg ended` → `serving` as the hole.** It measures 140 ms and looks
      damning, but the ring is `SLOTS`=4 deep and the guest is still playing
      those frames out at 33.3 ms each — **4 × 33.3 = 133 ms**. The picture is
      moving through all of it. The real hole is the other side of the re-arm:
      **ffmpeg cold start to first frame = 35 ms** (min 33, max 38).
      • **eglshim as the instrument for ATTRACT.** It counts the GAME'S RENDER
      LOOP, so it sees a blocked guest (the gameplay storm, 17.7 fps) and
      **cannot see a frozen video texture** — the game happily redraws a stale
      frame at 60 fps. Across 178 s of attract it held **60.1 fps median with
      one dip**, which is not evidence attract is smooth. Attract needs the
      screen-recording differ, not eglshim.
      **Shipped this pass:** the ffprobe is **cached per (path, size, mtime)** —
      a repeat serve now costs ~1 µs instead of 23-39 ms of blocked UI thread,
      verified on the real storm asset including that an mtime change
      re-probes; the host's idle poll goes **10 ms → 1 ms while a channel is
      hot**, which was up to 10 ms per serve of pure latency on the game's
      critical path; and both ends grew a **runaway detector** — the host logs
      `chN STORM` after 8 serves of one file, the guest logs `chN RE-ARM STORM`
      with **`caller=state` vs `caller=rewind`**, which is the one fact the host
      cannot see and the fact that decides the fix. Both stayed silent through
      attract (the negative control).
      **★ DAVID, 2026-08-06, watching live: "the video stuttering [is] most
      right before the next video comes in. like the last 500ms - 1 second of a
      video stutters before the next one loads in." THE LOG AGREES AND NAMES
      THE MECHANISM — marked CANDIDATE until a fixed build is watched:** at a
      transition the game re-arms the OUTGOING pipeline (`caller=state`
      prepare, same file) before setting the new location, and prepare()
      always restarts ffmpeg from frame 0 because the host cannot seek — so
      the outgoing clip visibly JUMPS BACK to its own start and replays while
      the UI thread eats blocking prepares. His crash log, 110.0 s: ch0 was
      283 frames into `2.asset/290.asset`, got re-armed and re-served the
      SAME file from 0, and the real next clip only arrived at 111.3 s —
      1.3 s of churn, matching the reported 0.5-1 s. This also re-frames the
      original "~7 s" attract stutter: the attract clip is 8.00 s, one
      transition per 8 s, and the stutter IS the transition.
      **★ THE REWIND-PATH STORM IS FIXED AND CONFIRMED (run 2, uncommitted):
      host STORM lines 2 → 0, ch2 serves 158 (crash run) → 75 (narrow absorb)
      → 13 (widened), max 3 serves per file, clips playing to real ends
      (162/200/242/168 frames), one burst absorbing 148 redundant rewinds.
      The absorb predicate is `playing && same path` — the first version
      (`delivered <= 1`) was MEASURED TOO NARROW: the game seeks every 33 ms
      tick for the whole scene step, not just until frames flow, so the
      narrow guard only slowed the storm (re-arm, absorb 4, re-arm; host
      storms still fired twice).**
      **THE STATE PATH TURNED OUT TO CARRY TWO DEFECTS, both now built and
      on run 3 as this is written:** (a) the same-file mid-play re-arm
      restarting ffmpeg from 0 — absorbed by the same predicate in
      `pad_vid_prepare`; (b) **the armed-but-unplayed stall**: after a real
      re-arm, `pad_vid_play` declined while the DOOMED old thread's
      `s->playing` was still 1 (it wakes up to 33 ms later), so the new arm
      filled a 4-slot ring nobody drained — that is the ubiquitous
      `superseded while throttled after 4 frames` line and the serve-PAIRS at
      every transition; fixed by clearing `s->playing` in the committed
      re-arm path so play-after-prepare always starts the thread.
      **★ DAVID, same session: "the stutter might be lining up with queued
      sound effects too. it seems whenever something happens, there is
      stuttering."** Consistent with everything above — "something happens" is
      when the UI thread does event work (prepares are PROVEN blocking; sfx
      asset loads are a CANDIDATE, unmeasured). If stutter still tracks
      sound effects after the video fixes are judged, that residual is a
      separate blocking source. CONFOUND to control: his session ran
      PAD_CARD (fuse2fs), the measurement runs are extracted — asset I/O
      cost differs between them.
      **★ DAVID WATCHED RUN 3 LIVE (all three fixes active) AND STILL SEES
      STUTTER, refined by two answers that redirect the hunt:** (1) **"only
      the video content"** hitches — overlays/score/LEDs stay smooth — so the
      game's render loop is exonerated and the residual is gaps in frame
      DELIVERY to the texture; (2) it is **intermittent and "sometimes looks
      more like screen tearing"** (his earlier screen recording is the
      reference). Run 3's own live numbers confirm the fixes work AND the
      residual is real: absorbs firing, superseded-after-1 down 170 → 33,
      throttled-4 down to 9, but padglhost dips 60 → 53/49.9 fps in busy
      stretches.
      **TWO NAMED CANDIDATES for the residual, neither yet measured:**
      • **Fragment-cut cold starts.** During events the game chains
      sub-second clip fragments (live log: `329.asset` cut after 14 frames =
      0.36 s, `316.asset` after 30 = 0.75 s) and every cut pays ffmpeg spawn
      + ~35 ms cold start — freeze-gaps peppering exactly the moments David
      reports. **The census instrument for this is BUILT and arms on the
      next run** (padvidhost.py: `first frame consumed N ms after serve
      start` + `guest consume STALLED N ms at frame F`, budgeted).
      • **Ring-slot reuse race → TEARING.** The guest hands the game a
      POINTER into the shared ring (no copy), padglhost reads those pixels
      LATER at its own pace, but the guest frees the slot the moment the
      handoff returns and the ring is 4 deep — a lagging upload reads a slot
      ffmpeg is overwriting. Fits "intermittent, worse when things happen,
      looks like tearing". **Detector designed, not built:** stamp each slot
      with its frame number host-side, have padglhost verify the stamp at
      upload time and log mismatches — spans the GL bridge, next pass.
      **RUN 3 FINAL, and the three fixes are COMMITTED (`cef2627`):** storms
      0/0 on both detectors, state-absorb 72 bursts, rewind-absorb 5,
      superseded-after-1 185 → 108 (what remains is the game's own
      loop-then-advance at clip ends), throttled-4 everywhere → 29, 75 full
      plays, rig clean after.
      **A LIVE RUN may be up when this is read: run 4** (watch.sh 20 min,
      census armed, NO longplay — the window is David's to play; started
      ~15:25 2026-08-06). Its padvid.log is the first with the census lines.
      **★ THE CADENCE FIX LANDED AND DAVID CONFIRMED IT LIVE** ("the
      stuttering on this city loop is gone"), `a6d9ce1`: vid_thread now
      schedules frame N at t_epoch + N*period instead of sleeping a period
      after each frame's work, so pacing error cannot accumulate. The census
      agreed: ZERO mid-clip stalls the whole run. **Instrument lessons paid
      for in the same commit:** a 30-on-30 screen capture is phase-ambiguous
      and freezedetect on near-static content measures its own threshold
      (300 "freezes" before AND 306 after the fix — both garbage); a
      change-detection histogram read 25% of a PRISTINE extract as stalls.
      Change detection is the wrong class for this footage; David's pure
      extracts (`OneDrive\Desktop\gz\video`, 659 named clips) enable
      ground-truth frame MATCHING instead — `framematch.py` in the session
      scratchpad, designed, unvalidated.
      **★ THEN THE BALL-2 REGRESSION, David live: "now the stutter is back...
      on ball 2 this stutter is very obvious" — WHILE EVERY DELIVERY COUNTER
      READ CLEAN** (padglhost flat 60, zero stalls, healthy serves). The log
      names the suspect: MY OWN widened rewind absorb swallowed a seek at
      **delivered=1780** — at a ball change the game deliberately seeks its
      still-playing backgrounds to 0, a mid-play seek can never be an EOS
      loop (EOS stands the stream down first), and refusing it plays the
      picture mid-clip against a game timeline that thinks it restarted.
      **Fix COMMITTED (`dba987d`): the discriminator is SEEK RATE, not
      delivered-count** — absorb only a seek within 3 frame periods (100 ms)
      of the previous seek on that stream, so the FIRST seek of any burst
      re-arms: a restart is honoured, a storm pays one re-arm instead of 93.
      Three predicates tried, each killed by measurement: `delivered<=1` too
      narrow (storm survived), `playing+same-path` too wide (ball-2 restarts
      refused), burst-only is the third.
      **RUN 6 IS LIVE on that build as this is written** (watch.sh 30 min,
      census armed, game started, ~15:35 2026-08-06) — David is playing
      through a ball change as the acceptance test.
      **★★ MEASURED AT LAST, OFF DAVID'S OWN SCREEN RECORDING, AGAINST A
      PRISTINE CONTROL — and it relocates the fault out of everything fixed
      so far.** `Recording 2026-08-06 154107.mp4` (Ball 2, MechaGodzilla
      barrier, 21.8 s) against its extract `gz\video\MechaGodzilla_Loop.mp4`:
      | | repeated frames | held events | longest |
      | capture | **22.7%** (148/653) | 97 | **1500 ms** |
      | pristine control | **0.0%** (0/1995) | — | — |
      The control is what makes it real: that clip NEVER repeats a frame, so
      all 22.7% is the emulator. **TWO DISTINCT FAULTS, told apart by their
      time distribution:** (a) a STEADY ~4.5 single-frame holds per second,
      uniform across every 2 s bucket (9-11 holds, ~1 frame each) — a rate
      loss, NOT event-driven; (b) ONE 1500 ms freeze at 10.03 s.
      **AND THE RUN'S OWN LOGS WERE CLEAN THROUGHOUT** (run 6, same minutes:
      0 storms, 0 consume stalls, 57 healthy serves, padglhost 59.4 fps avg).
      **So the loss is DOWNSTREAM of decode and of guest delivery** — between
      the guest handing a frame over and pixels reaching the screen. Same
      shape as the audio fault this rig already solved: every instrument
      inside WSL read perfect while the room heard breakage, and the answer
      was the WSLg→Windows hop.
      **★★ REPRODUCED WITHOUT DAVID AND LOCALISED, 2026-08-06 (runs 7-8).**
      Agent-driven capture of its own gameplay: **18.7% repeated frames, 306
      held events, 5.6/s** — matching David's 22.1% / 6.6/s, so it is the
      same fault and it no longer needs his hands to study.
      **STAGE COUNTERS NOW EXIST AT BOTH ENDS OF THE BOUNDARY** (`[vid] chN
      handed the game N frames ... /s` in gstvid.c, `vid N uploads/s N NEW/s`
      beside padglhost's fps line) and they name the mechanism:
      • healthy seconds: guest 30.0/s → padglhost 30.0 uploads/s, all NEW,
        60.0 fps.
      • bad seconds: guest **27.4/s** → padglhost **25.5 uploads/s** at
        **54.0 fps**. **The guest handoff and the renderer dip in the SAME
        seconds.**
      **FOUR CANDIDATES RULED OUT BY MEASUREMENT, so nobody pays twice:**
      • **WSLg/RDP presentation.** David: only the VIDEO hitches while scene
        art and overlays stay smooth — one window, one swap, so a dropping
        RAIL hop would take everything with it. The per-swap tick was
        designed for this and is NOT needed.
      • **CPU starvation.** 67% idle, load 0.99 on 6 vCPUs, during the dips.
      • **Decode starvation.** New `RING EMPTY` counter (gstvid.c, fires when
        a frame is due and the ring has none): **0 events** across a whole
        gameplay run. The host decoder is never behind.
      • **The recorder perturbing it.** The dips are identical with no
        capture running (one window fell to 14.3/s).
      **★ GL BACK PRESSURE IS ALSO RULED OUT — runs 9-10 timed it.**
      padglhost's per-frame cost is **conv 0.70-0.85 ms + swap 3.70-3.83 ms
      against a 16.7 ms budget**, flat in the bad seconds as well as the
      good. It is never the bottleneck; when its fps reads 55-57 it is
      WAITING for guest commands, so **padglhost's fps is a readout of the
      GUEST's render rate, not of the renderer.** Do not re-time it.
      **GUEST HANDOFF SPACING IS NOW MEASURED, and it splits by condition:**
      • idle game: **worst gap 33 ms, 0 late, 0 early** — textbook.
      • under scene churn (longplay): **exactly ONE late gap per 2 s, of
        46-223 ms**, rate 27.1-29.9/s.
      So the guest contributes a real but INTERMITTENT hiccup, roughly
      0.5-3 frames/s, and the screen shows **5.6 holds/s**. Those do not
      reconcile, so **something after the handoff is still unaccounted for**
      and it is the last unmeasured link.
      **★★ MEASURED, run 11, AND IT IS THE PRESENTATION HOP — every stage
      inside the rig is now proven clean and the screen still is not.**
      padglhost's swaps-per-video-frame histogram is essentially PERFECT:
      `2x` on 53-60 frames per 2 s window, **HOLDS 0.0-1.0/s**. Over the same
      seconds the screen showed **5.72 holds/s**.
      **A 60 fps capture makes it unambiguous** (perfect 30-on-60 delivery
      MUST read exactly 2 refreshes per frame):
      | 1 refresh (too short) | **18.4%** |
      | 2 refreshes (perfect) | **48.4%** |
      | 3+ refreshes (a hold) | **33.1% = 8.50 holds/s**, longest 250 ms |
      So padglhost gives each frame exactly two SWAPS while the desktop shows
      it for one or three REFRESHES. The swaps are right; their PRESENTATION
      is uneven. The loss is after `eglSwapBuffers`, in the WSLg/RAIL/RDP hop
      to Windows.
      **★ AND THIS OVERTURNS THIS ITEM'S OWN EARLIER RULING, which was mine
      and was wrong.** Presentation was "ruled out" from David's report that
      only the video hitches while scene art and overlays stay smooth. That
      inference does not hold: static or slow overlays CANNOT reveal an
      uneven present, only 30 fps motion can. The observation was right and
      the deduction from it was not. **The same shape as the audio fault this
      rig already solved** - every instrument inside WSL read perfect, the
      room heard breakage, and the answer was to bypass the WSLg hop
      (PortAudio on the Windows side, `13c4410`).
      **★★★ RETRACTED THE SAME DAY, BY THE TICK. THE PRESENTATION HOP IS
      INNOCENT AND THE SCREEN-CAPTURE NUMBERS ABOVE ARE CONTAMINATED.**
      `PAD_GL_TICK=1` draws the low byte of the swap counter as 8 black/white
      blocks (padglhost, bottom-left - GL's origin, which cost one decode
      attempt). Decoded off a 60 fps capture, 256 distinct values seen:
      **the counter advances 1798 over 1799 captured frames in 30 s = 59.9
      swaps/s, exactly padglhost's rate. NO SWAP IS EVER LOST.** The deltas
      spread 36.8% at 0, 32.9% at 1, 30.3% at 2+, netting to exactly 1.0 -
      **that is the GRABBER sampling unevenly, not the desktop dropping
      frames.**
      **SO THE INSTRUMENT HAD A HOLE AND EVERY SCREEN NUMBER IN THIS ITEM
      INHERITS IT.** `dupcensus.py` compared a CAPTURE against a FILE: the
      file has no capture jitter and the capture has ~37% double-samples, so
      the "22.7% excess repeats" measured a real fault PLUS the recorder's
      own jitter and cannot separate them. The 18.7%, 19.1%, 5.72/s and the
      60 fps 1x/3x split are all unreliable AS MAGNITUDES. Treat them as
      "something is wrong", never as a size, and never as a before/after.
      **WHAT SURVIVES, and it is not nothing:** David sees the stutter with
      his own eyes, which no sampler artefact explains; and the guest-side
      hiccup is measured INSIDE the rig where no grabber is involved -
      **one late handoff gap per 2 s of 46-223 ms under scene churn**, rate
      27.1-29.9/s against a target of 30. That is now the only trustworthy
      quantitative handle on the fault.
      **★★ BUILT AND MEASURED: `tickcensus.py`, and THE NUMBERS FINALLY
      RECONCILE.** It decodes the tick beside the content and keeps ONLY the
      pairs where the tick advanced by exactly 1 - genuinely adjacent swaps,
      nothing missed, nothing double-sampled (75.1% of pairs were discarded
      as jitter, which is the size of the hole in the old number).
      **Baseline is 50%, NOT 0** - video is 30 fps over 60 Hz swaps, so
      identical content across two adjacent swaps is CORRECT half the time,
      and reading "repeats are bad" here calls a healthy pipeline 50% broken.
      **Measured on a scene-driven game: 52.9%, i.e. +2.9 points = 1.76
      holds/s** - about a third of the contaminated 5.72/s.
      **AND 1.76/s IS WHAT THE GUEST-SIDE HICCUP PREDICTS** (one late handoff
      gap per 2 s, 46-223 ms, plus a rate shortfall of 27.1-29.9 against 30).
      Before this the screen said 5.72/s and the guest said ~0.5-3/s and they
      did not reconcile, which is what drove two passes downstream. They
      reconcile now: **there is nothing unexplained after the handoff.**
      **SO THE WHOLE REMAINING FAULT IS THE GUEST'S LATE HANDOFF UNDER SCENE
      CHURN**, and the mechanism is narrowed by what is already excluded -
      not CPU (67% idle), not decode (RING EMPTY = 0), not renderer cost
      (4.5 ms of 16.7), not presentation (tick: no swap ever lost).
      **CANDIDATE, unproven:** the handoff itself blocks. It calls the game's
      callback, which uploads and emits into the padgl ring; a scene change
      uploads fresh textures, so a momentarily full ring would block the
      video thread exactly when scenes churn. Test by timing the handoff call
      in `vid_thread` (wrap `s->handoff(...)` and report the worst) before
      changing anything - that single number confirms or kills it.
      **INSTRUMENT LEDGER — four built, ONE trustworthy, and the failures
      matter more than the successes here:** `dupcensus.py` (TRUSTWORTHY:
      consecutive-frame repeats over the moving region, needs no alignment,
      calibrated at 0.0% on a pristine extract); `screenrec.py` (capture is
      fine, its freezedetect analysis is phase-ambiguous at 30-on-30 — it
      read 300 freezes before a fix and 306 after); `framematch.py`
      (ground-truth matching, correct in principle, FAILED in practice — the
      game bakes overlays into the picture so capture and extract have
      differently-shaped moving regions, margin collapsed to 0.05 and it
      claimed 40 loop wraps inside 21.8 s of a 66 s clip; do not revive
      without solving alignment); a change-interval histogram (read 25% of a
      PRISTINE extract as stalls — change detection is the wrong class for
      this footage).
      **Transition cold starts also remain, census-priced:** 35-40 ms (ch0),
      64-71 ms (the 65 s background, also at every loop wrap). Fix
      candidates unbuilt: host pre-arm at location-set, loop-flash suppress.
      **Resume:** time the `s->handoff(...)` call in `vid_thread` and report
      the worst per window; that confirms or kills the blocking-handoff
      candidate in one run. **Judge every fix with `tickcensus.py` against
      its 50% baseline** (needs `PAD_GL_TICK=1`, a 60 fps capture and a scene
      with real motion) - NEVER with a raw screen-repeat percentage, which
      carries the grabber's jitter. The agent can run the whole
      loop unattended: `watch.sh`, `run5game.sh` (scratchpad) to start a
      game, `longplay.sh` to drive scenes, gdigrab at 30 fps over
      `1492x914+0+0`, then `dupcensus.py`. **Judge with `dupcensus.py`, and
      only on scenes with real motion** — it refuses low-motion content on
      purpose, and the idle city loop is one of those (it reads 1.8% true
      repeats and is NOT a valid test bed).
      **Resume:** fix the REWIND path in `gstvid.c` — `pad_vid_seek()` re-arming
      the host on every EOS, when the previous arm delivered ≤1 frame, is the
      loop. Then judge the picture with the screen-recording differ, **not
      eglshim** (it counts the render loop and cannot see a frozen texture).
      **The recipe that reaches a stable game, verified 2026-08-06:**
      `plunge.py reset`, wait 8 s, `plunge.py coin`, `swpoke.py 36 900`, wait
      8 s, `plunge.py plunge` — then the game holds Ball 1 indefinitely.
      **The crash log that answered `caller=` is kept at
      `/home/david/crashlogs/gzpad_crash_1406.log`** — it is a gameplay session
      with two storms in it, so a fix can be checked against a stored before.
      **Related, raised by David 2026-08-06: the playfield LED markers are
      choppy too, "probably all related".** In GAMEPLAY that follows — the game
      publishes LEDs from the same loop that eglshim measured at 17.7 fps, so
      they must go choppy with it. In ATTRACT it does NOT follow, because that
      same loop held 60.1 fps, so attract's LED choppiness is a separate thing
      and is undiagnosed. Do not fold the two together.

- [ ] **3. The coil map.** `S3 D3` — S3: nothing is broken, this is a map that
      is half confirmed. D3 — one run; the instrument exists and is validated,
      but the Coil Test menu has not been reached yet so the navigation is
      unknown.
      **★ THIS ENTRY WAS STALE UNTIL 2026-08-06 AND SAID "a map that does not
      exist yet". Half of it exists and is confirmed by a labelled experiment.**
      `313bb53` (2026-08-04) decoded the fire frame: `cmd 0x40` on nodes 8/9
      addresses ONE coil by index, the index is the device table's own (node 8
      carries 0..8, node 9 carries 6 — exactly the ten playfield coils
      `device_xy.txt` lists under groups 6 and 7), and byte 4 is drive strength
      on the same scale as the menu's "Trough Eject Power 225 (88%)".
      `coil_publish()` in `hwshim.c` is the decoder, `coildecode.py` its Python
      twin, `PAD_COIL_PROBE=1` the instrument (use it, NOT `PAD_NB_LOG`, which
      at 1.5M lines makes the boot take 4+ minutes).
      **How five of the ten were confirmed WITHOUT the menu, which is why this
      is not a guess:** door closed, trough emptied, Start pressed → the game put
      up LOCATING PINBALLS and ran a ball search, and the frames that appeared
      carried indices 2, 3, 4, 7 and 8 = right slingshot, left slingshot, auto
      plunger, pop bumper, right scoop. Precisely the coils a ball search fires
      and precisely not the three flippers or the trough eject. The game
      labelled its own experiment.
      **WHAT IS LEFT, and it is the whole reason the box is open:**
      **(a) byte 7 is NOT decoded** — 0xff for the slingshots and pop bumper,
      0x00 for the plunger and scoop, 0x32 for the magnet; on/off, hold power and
      board-self-fire all still fit. **(b) the other five coils** (three
      flippers, trough eject, coin enable, magnet) have no labelled experiment.
      **(c) `Diagnostics → Coil Test` has still never been reached**, and it is
      the one-at-a-time oracle that would close (b) by name.
      `coilread.py` (run on WINDOWS) diffs nonzero `(node,index,count,lvl)`
      around a fire. **48V needs the door CLOSED again (`swhold.py 33 1`)**
      before anything will fire.

- [ ] **1d. The a2 / b4 / b5 payload.** `S3 D4` — S3: the lamps already work,
      this is the last undecoded slice. D4 — the capture rate is the problem:
      ~15 frames in 60 s, and the oracle (`Diagnostics → LED Tests`) needs a run
      it has never been driven through.
      All that is left of the LED wire that
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

- [ ] **13. Save and load save states.** `S2 D5` — S2 for the same reason as
      item 16: play works, but every run pays for its absence. D5 — the only
      candidate tool is not
      installed, the kernel is missing `INET_DIAG_DESTROY`, and the restore
      surface crosses into native Windows. Budget more than one pass.
      Freeze a live game and resume it later
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

- [ ] **19. Save and load a replay from the game window itself.** `S3 D4` — S3
      because item 16's command line is the workaround and nobody loses a run to
      typing it; D4 because it cannot start until 16 ships the engine and the
      file format, and because its trigger is a KEY PRESS in the WSLg window,
      which this rig has recorded twice as un-injectable (SendInput is
      UIPI-blocked — items 7 and 12), so confirming it needs David's hands or a
      keysim rather than a script.
      **David picked the game window and its Controls legend** (`padglhost.c`,
      C/X11), asked and answered 2026-08-06, over the virtual playfield and the
      app's Emulate tab. One key saves the session's replay, one key loads and
      plays one back, both listed in the legend beside the switch keys.
      **The structural thing in the way:** `binds[]` (`padglhost.c:646`) has no
      concept of a key that is not a switch — every row carries an `ids[]` and
      goes through `sw_publish()`. A replay key is the first binding that does
      something else, so the table and `legend_open`'s drawing of it grow a new
      kind of row. No function key is bound today, so F9/F10 are free.
      **Depends on item 16, and must not invent a second format:** whatever
      16's driver reads is what this writes.
      **Acceptance:** with no shell and no helper scripts, a key in the game
      window writes a replay of the session so far and says so in the log; a
      second key plays one back on a fresh run; the replayed run's `[sw]` stream
      matches the saved one within item 16's stated tolerance. Both keys appear
      in the Controls legend.

- [ ] **22. Start Emulator leaves the game window BEHIND the app.** `S3 D3`
      **Observed 2026-08-06 (David):** pressing Start Emulator in the app's
      Emulate tab should bring **all** the emulator windows out over the PAD
      application. The **game window comes up behind the app**, while the
      **Controls window comes up above it**. A run opens three top-level
      Windows windows, and `shotwin.py` sees all three by title:
      `godzilla_pro - Stern Spike 2 emulator (Ubuntu)` and
      `Controls - Spike 2 emulator` (both X11 out of `padglhost.c`, RAIL-proxied
      by msrdc.exe) and `godzilla_pro - virtual playfield` (`playfield.py`, an
      ordinary Windows Tk process started through interop by `watch.sh`).
      **The asymmetry is the clue and it is worth keeping as observed rather
      than diagnosed:** the two that disagree come from the SAME process and are
      mapped the same way, `XMapWindow` at `padglhost.c:989` (legend) and in
      `win_open()` at `:1048`, with `legend_open(scr)` called from `:1121`.
      **GUESS, not established:** they are mapped at different TIMES — the game
      window waits for the guest's first frame, ~15 s into the boot, by which
      point the app has been clicked and holds the top, while the legend is
      created inside the same `win_open()` path. Nobody has read the actual
      z-order, so this is a hunch and must not be treated as a finding.
      **★ THE OBVIOUS FIX IS BANNED HERE, and this is why the item says so up
      front. `SetWindowPos` on an emulator window is a standing non-negotiable**
      (top of this file): it froze David's windows once, and the handoff records
      a programmatic `SetWindowPos` growing the frame while the picture stayed
      1360x768 in the corner, because a RAIL proxy and the X client then
      disagree about the window. `SetForegroundWindow` is the same shape.
      So the raise has to come **from inside X** (`XRaiseWindow` on padglhost's
      own two windows, the same rule item 5 landed on for MOVING them), and the
      playfield is our own Tk process so Tk's own `lift()` is native there and
      is not the RAIL trap. **A third option needs no window manipulation at
      all and may be the right one:** have the APP stop holding the top after
      the button press, rather than having three other windows fight it.
      **Acceptance:** press Start Emulator and, once the game window appears,
      all three emulator windows are above the app with no clicking — verified
      by reading the real z-order, not by eye. `shotwin.py` already enumerates
      the windows by title; `EnumWindows` returns them IN z-order, so the
      instrument is a few lines on top of what exists. State whether dragging
      and the window-position restore (item 5, `19e1b85`) still work afterwards,
      because that is exactly what the banned fix broke.
      — S3: nothing is broken and the workaround is one click. D3: it needs a
      run and it should show every time, the instrument is a small extension of
      `shotwin.py`, but the cheap fix is forbidden and the safe one crosses the
      X/Windows boundary.

- [ ] **24. Press-and-hold a switch on the virtual playfield.** `S2 D2`
      **★ DAVID, 2026-08-06: "we need to be able to press and hold a switch on
      the virtual playfield to keep it held down (like for shooting the scoop
      it needs to remain in the scoop while i hold the switch)."**
      A playfield click today is a fixed-length PULSE: `playfield.py:559` binds
      `<Button-1>` only — there is no ButtonRelease binding anywhere — and
      `on_click` (`playfield.py:668`) shells out `swpoke.py <id> PRESS_MS` as a
      subprocess. A ball device like the scoop needs the switch held for as
      long as the mouse button is down, which is a different shape: press →
      close, release → open.
      **The pieces already exist.** `swhold.py` is the latching writer (the
      coin door uses it: `swhold.py 33 1`), and item 6's longplay work held the
      scoop "like a real ball device" through exactly that path. The keyboard
      half already behaves this way — a held key is a held switch — so this is
      the playfield's click surface catching up to the keyboard, not new
      machinery. Bind `<ButtonPress-1>`/`<ButtonRelease-1>`, hold via the
      swhold path, keep the `f` provenance tag (padsw.h) either way.
      **Two things to respect, both already written down:** switch input goes
      through subprocesses ON PURPOSE (`playfield.py:31` — a Windows write into
      the padsw block would race the guest; do not "optimise" the hold into a
      direct write), and each event is a WSL interop subprocess spawn, so
      measure the press-to-close and release-to-open latency and state it —
      a release that lands hundreds of ms late would feel like a stuck switch.
      **A tap must stay a tap:** a quick click should still deliver the item
      17-guaranteed minimum closure, not a 20 ms blip (the `sw_owed[]` latch
      covers that, but say so in the test rather than assume it).
      **Acceptance:** hold a playfield switch — the scoop — and `swshow.py`
      reads its `mrg` at 1 for the whole hold and 0 promptly on release
      (state the measured latencies); a quick click still registers every
      time; a held scoop during a game keeps the ball in the scoop the way
      David described. His hands are the final oracle, since this is a feel
      item.
      — S2, armchair: play works today via keyboard and `swhold.py`, so nobody
      loses a run, but a whole class of shots cannot be played from the
      playfield at all, which is a capability gap rather than friction. D2,
      armchair: one script, the fault (a pulse where a hold should be)
      reproduces on demand every time, and only the feel half needs a run.

- [ ] **4. Boot buzz — PARKED, deliberately.** `S3 D3` (not in the pool; the
      numbers are here for whenever it is reopened.) ~20 Hz stutter in the
      first ~10 s.
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
- **`C:\tmp\spike2_item18\`** — item 18's captures, both sides of the boundary:
  `winprof_idle` / `winprof_attract` (Windows) and `rigprof_idle` /
  `rigprof_attract` (WSL), as .json and .csv. **The idle pair is a reusable
  CONTROL** — `winprof.py --compare` takes it directly, so pass two does not
  have to spend 90 s re-measuring a quiet desktop. It is machine-specific, so
  it lives here rather than in the repo.
- **`plans/spike2_pc_emulation_handoff.md`** — gitignored on purpose, local to
  this machine. The deep detail behind every numbered item above.

## Loose ends worth a look, not yet worth a queue slot

- **`plunge.py game` can leave the machine UNABLE to start a game, and it looks
  like the rig is broken.** `game` is coin → start → plunge, and the plunge
  takes a ball out of the trough whether or not the Start press took. If it did
  not take, the machine is now a ball short: the next Start gets `LOCATING
  PINBALLS / PLEASE WAIT...`, the ball search fails and it drops back to
  attract, forever. `longplay.sh` then plays a full block to an attract screen —
  the exact failure its own comments warn about, from a different cause.
  **The recipe that worked 2026-08-06:** `plunge.py reset`, wait ~8 s for the
  game to settle, `swpoke.py 36 900`, and only plunge once a game is on screen.
  A `plunge.py game` that checked for a game before removing the ball would
  close this; see also item 17 on the press duration.

- **`alive.sh`'s watch.sh pattern matches ANY process whose command line
  contains it, including one that is merely WAITING for the run to end.** Seen
  2026-08-06: a shell running `until ! pgrep -f "watch.sh 3"; do sleep 5; done`
  made `alive.sh` print `run scripts (watch.sh) : 1` and `TOTAL STILL RUNNING :
  1` **with an empty "what is still up" list underneath** — the count and the
  listing disagreed, which is the one thing this script exists not to do. Same
  self-match shape as `playaudio.sh`'s `win_kill` two bullets down. Harmless
  here (the waiter was mine), but a script that greps for a run and a script
  that waits for one look identical to it.

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

- [x] **20. Plunge does not take a ball out of the trough, so the game ends
      itself.** DONE 2026-08-06, `e1e9cb3`. **It was the wrong END of the
      trough, and the item's own prime suspect was innocent.**
      A trough is a ramp: the eject kicks out the ball on Trough 1 and the five
      behind it roll DOWN one position, so the switch that OPENS is Trough 6 at
      the far end. `plunge.py` opened Trough 1 — the one place a hole cannot
      appear — leaving the game with a gap at the eject and a ball still sitting
      behind it. The game had nothing to eject, so a plunge never really took a
      ball out of play, and it later ended the game believing none was.
      One line: `next(s for s in reversed(TROUGH) if _held(m, s))`.
      **Established from the game's OWN device table, not from a guess about
      troughs** (`games/godzilla_pro/switch_xy.txt`): TROUGH 1 (id 71) is at
      x=254 beside TROUGH JAM (id 72) at x=254, and a jam switch is by
      definition at the eject; TROUGH 6 (id 66) is at x=210. David had described
      the wanted state independently and in the same terms.
      **Measured before and after on one run**, from the guest's own `[sw]`
      stream: `-71l` → the game sees 5 balls at `[70,69,68,67,66]`; `-66l` → 5
      at `[71,70,69,68,67]`. **Acceptance met with a real oracle:** the
      screenshot at t+300 s reads **FREE PLAY / BALL 1** with Player 1 active,
      the trough held at 5 for the whole five minutes, and `alive.sh` printed 0.
      "The guest process is alive" is NOT the same claim as "a game is in
      progress", which is why this was screenshotted rather than inferred.
      **BOTH "the release is being lost" theories are RULED OUT, with numbers.**
      • **item 17's `sw_owed[]` latch**, which this item named as the prime
      suspect and proposed a `PAD_SW_LATCH=0` bisect for. It arms only when
      `!sw_served[n]`, and a trough switch held since window-open has been on
      the wire as made hundreds of times. `[swlatch]` count for the whole run:
      **0**. The bisect would have cost a run and found nothing.
      • **a race in `padsw.take()`** — found while reading the merge, not
      queued. take() stages a value and bumps `scr_gen`, the caller writes the
      opposite value microseconds later, and the shim diffs `scr_held` against
      its own shadow on the ~640 µs paced SPI loop, so a pair landing inside one
      poll collapses to **no edge at all**. `padsw.h` documents exactly that
      collapse for PROVENANCE without noticing it would destroy VALUES.
      Measured rather than argued: the window is **996 µs median, 882 µs
      minimum over 200 trials**, because `m.flush()` is an msync. Real in
      principle, cannot fire as written, margin 1.4×. **Do not re-derive it**;
      if `take()` ever loses its flush, it becomes live.
      **New instrument: `swshow.py`**, all three regions of the switch block
      side by side with the three generations. `mrg[]` alone cannot tell "the
      keyboard still holds it" from "a script edge was dropped" — they are the
      same three numbers — and `scr_gen` having moved while `mrg_gen` stood
      still is what separates them.
      **NOT a regression of item 7, and the item's own regression claim was
      wrong.** Item 7 fixed WHO writes the array and its `-71` was the right
      switch by luck of the same wrong ordering; the end has been wrong since
      `plunge.py` was written. **Follow-on: item 21**, which is the ball MODEL
      this item shows the rig does not have.

- [x] **6. Scene video noise in the TV inset.** DONE 2026-08-06 — **David
      confirmed it looks fine on screen**, which is the one thing the item was
      still open for. Every instrument had already agreed the pixels were the
      inset's own; the entry said in terms *"nobody has SEEN the inset"*, and
      that has now been closed by the only oracle that could close it.
      **The mechanism was CHANNEL TAKEOVER, and it took a control to find.**
      The game asks for caps **once per pipeline and never again** (it loops by
      SEEKING, so its texture geometry is frozen for the pipeline's life), and
      every new pipeline **steals a channel** — with four channels and
      `pipeline` never cleared, a clip that has just hit EOS is still on screen
      when its slot is taken. The 520x294 inset negotiated its size, lost its
      channel to a 1360x768 background clip, and kept uploading from a ring full
      of someone else's frames.
      **How that was proven rather than guessed:** `framewidth.py` inverted the
      converter and re-folded the recovered Y at every width. The known-good
      frame scored **520 (2.66 against a shuffled control of 34.31)** — the
      labelled example it had to agree with first — and the noise capture scored
      **1360 (2.02 vs 23.84)** while the width it was actually read at, 520,
      scored **22.34 against a control of 23.80, i.e. no better than noise.**
      So the bytes were another stream's, measured with a control on both sides.
      **Fixed:** `gstvid.c` records the size the GAME was told (`told_w/told_h`,
      set in `pad_vid_get_int`, NOT at prepare() which re-runs on every rewind)
      and refuses to hand over a frame once the channel serves something else; a
      **request-generation check** beside it catches a SAME-SIZE takeover, which
      the size check cannot see; stealing is least-recently-used **with fresh
      streams protected** (without that, LRU picks the NEWEST stream — my own
      regression, and the exact wrong end for a burst); `padglhost` drops a
      mismatched upload outright; and `PADVID_CHANNELS` went 4 → 8 because the
      scene builds **three pipelines in 130 ms**.
      **Instrumented acceptance passed on the real taunt** (`44f4bc0` run): 99
      serves at 520x294 on ch3 alongside 1360x768 on ch0, **zero `NOT MINE ANY
      MORE`, zero wrong-size uploads, zero dropped frames**, clips reaching EOS
      after 194 and 196 frames rather than the "after 0" it was last left on.
      **Committed:** `355e0bd`, `11a8b44`, `4dab1ad`, `ccce594`, `36d82a1`,
      `c389572`.
      **The two lessons worth keeping.** **(1)** `PAD_VID_TESTPAT` rendered
      perfectly in the real inset, which exonerated the draw and upload and
      deliberately said nothing about the data — splitting the problem in half
      with one flag is what made the rest cheap. **(2)** The reason it took five
      runs to see was **not the trigger, it was CREDITS**: a machine with no
      credits ignores Start *silently*, every instrument reported the press as
      delivered, and "the press worked" and "a game started" looked like one
      claim. `plunge.py game` exists because of that. **See item 20** — the
      trough half of that same path has since regressed.

- [x] **18. Windows feels sluggish while a run is up.** DONE 2026-08-06,
      `d61b9dc`. **The machine is 8 physical cores, not 16, and WSL2 had been
      handed all 16 logical threads** — there was no `.wslconfig` at all, so
      defaults applied and `wsl -e nproc` returned 16. The VM's vCPU threads
      could therefore be scheduled onto **both SMT siblings of whatever physical
      core an interactive app was using**, and SMT siblings share execution
      resources: a single-threaded input-to-paint path loses real throughput
      **while no thread ever waits for a logical CPU**. That is the only
      mechanism consistent with the whole measurement history — processor queue
      length **0.00 in every capture**, no starvation, no memory, disk or GPU
      pressure, zero dropped compositor frames, and felt latency anyway.
      **Fix: `C:\Users\david\.wslconfig` with `[wsl2] processors=6,
      memory=30GB`** (memory pinned at what WSL already defaulted to, so the
      file changes one thing, not two). `nproc` 16 → 6.
      **VERIFIED WITH THE CONFOUND CONTROLLED, which is the part that makes it
      a result rather than a hope.** The Claude app also renders this session's
      tool output, so "the emulator is running" had always coincided with "the
      agent is working". David's verdict came in the **worst** condition — **in
      a game, with the agent committing, editing and running a live 90 s
      capture**: *"this test is in a game right now and the text typing seems
      absolutely fine right now."* Both variables back at bad, symptom gone.
      **It cost the emulator nothing: 60.0 / 59.9 / 59.8 fps**, the same 60 Hz
      swap cap it has always held.
      **The profile that got there, and five things it ruled out with numbers:**
      `winprof.py` (Windows, PDH via ctypes + DwmFlush + cursor probes) and
      `rigprof.py` (WSL, /proc deltas), driven by `abrun.ps1` so every A/B arm
      runs identically. **The run costs the machine 2.80 cores while its Linux
      processes account for 0.50** — vmmemWSL ~1.18 cores and **msrdc.exe ~0.70
      cores**, the WSLg RDP client, which is invisible from inside WSL and which
      no measurement in this repo had ever seen. **Ruled out:** CPU starvation
      (queue 0.00 everywhere), memory (44 GB free of 46), disk (queue 0.01), CPU
      downclocking (`% Processor Performance` goes **up**, 88 → 108), dropped
      compositor frames (0.00% late in all seven captures), the **GPU adapter**
      (a null result), **window size** (a quarter of the pixels moved msrdc
      72.1 → 70.3), and **a game being heavier than attract** (+0.18 cores).
      **THREE INSTRUMENT LESSONS, each paid for:**
      • **`gpuprobe`'s 43x was a FALSE POSITIVE.** It renders 4 full-screen
      1080p quads; the real bridge issues 2-4 draw calls a frame with kilobytes
      of data. Same shape as the tone test that once pronounced a broken audio
      path healthy — a synthetic signal believed because the number was big.
      Splitting GPU time per adapter LUID caught it, and only because that was
      added BEFORE the run.
      • **dwm CPU is NOISE and I reported it as a finding once.** 13.03 and
      13.11 with no emulator running, 4.36-16.31 with one. Reliable here:
      vmmemWSL, msrdc, context switches, DWM frame interval and late frames.
      • **Read-only subagents are not zero-load on the machine being measured.**
      One running `find /` inside WSL produced a baseline BUSIER than a real
      run (vmmemWSL 79.8%, 121,604 ctx/s), and later a survey fan-out took the
      machine to **163,138 ctx/s** — more than the emulator — and correctly made
      `abrun.ps1` refuse to start a capture David had asked for.
      **Guards left behind:** `winprof.py` self-checks every capture and prints
      `** NOT QUIET` on both sides of the boundary; `--compare` disowns an
      untrustworthy baseline; the cursor probe reports `NOT MEASURED` rather
      than a clean number when nobody moved the mouse; `killgame.sh` now kills
      `longplay.sh`, which only `watch.sh`'s own teardown ever did.
      **What is deliberately NOT claimed:** 6 was a first guess, not a tuned
      optimum, and the cursor probe has still never had a control arm with
      movement in BOTH captures, so its absolute numbers (10.7 s of movement,
      2.25 stutters/active second) cannot yet judge anything.

- [x] **14. The Emulate tab forgets the card image across a restart.** DONE
      2026-08-06, `eb1deec`. The diagnosis in the item was right: the SAVE half
      had always worked — David's own project anchor already held
      `godzilla_pro-1_15_0_spike2...raw` — and nothing ever read it back on an
      ordinary launch. `_apply_project_folder` was the only reader and it runs
      only on an explicit Project ▾ → Open; startup goes through
      `_apply_manufacturer`, which computed the folder, asked `has_anchor`, set
      the title and stopped. One call added there, beside the check it was
      already making.
      **A project's value wins ABSOLUTELY, including when it is empty**, matching
      the rule `_apply_project_folder` already follows — falling back there would
      leak the previous card into a project that never had one. The global
      `emulate_card` in `settings.json` is only for having no project open, and
      it also closes a gap the anchor could not: `_on_close`'s anchor write is
      skipped outright when the folder is not a project, so a card picked against
      a plain folder previously had nowhere to live at all.
      **Verified on REAL data with a control, not just on fixtures:** the actual
      App built against a copy of David's real `settings.json` now shows the card
      at startup, and the same startup with the new restore neutered — which is
      exactly what the old code did — shows `''`. Six regression tests in
      `tests/test_emulate_tab.py` drive `_apply_manufacturer` itself rather than
      a helper, because the bug was that nothing CALLED the restore and a helper
      test would have passed against the broken app.
      **One trap worth keeping:** the first version of those tests hand-rolled
      the anchor JSON, which `project_file.load()` rejects for having no `kind` —
      so the tests failed and blamed the app. They use the real `save()` /
      `update_anchor()` pair now.

- [x] **15. Every clip during gameplay plays the SAME video.** DONE 2026-08-06,
      `44f4bc0`. **In gameplay, ch0 went from 1 distinct clip in 59 serve
      requests over 182 s to 16 distinct clips in 66 requests over 106 s**, and
      four channels ran at once each serving its own asset path. Screenshots:
      the POWERLINE DESTROYED award drawing powerline footage, a loop award
      drawing maser footage, a Godzilla scene drawing Godzilla footage.
      **THE GAME DOES NOT BUILD A PIPELINE PER CLIP, and that is the whole
      bug.** `factory_make` in the reported run shows exactly TWO complete video
      pipelines in five minutes (`gzpad.log:5027` → ch0, `:6566` → ch1) and none
      after; every later clip change was `g_object_set(filesrc, "location", ...)`
      on a pipeline that already existed. `pad_vid_note_location()` attached the
      filename to `last_created`, which only moves on `gst_pipeline_new` — so
      from the moment the second pipeline existed, **every filename landed on
      ch1's stream whichever element it was for.** ch0 was handed a new clip four
      times, the last at 127.7 s, **seven seconds BEFORE ch1 was created**, then
      served `2.asset/383.asset` 61 times over the following 182 s while ch1
      caught the strays (`567.asset`, `446.asset`, one prepare each).
      Fix: route by the filesrc OBJECT, bound to its stream on first sight.
      `PAD_VID_NOSRCROUTE=1` restores the old behaviour on the same build.
      **Ruled out, and it was the queued theory: fallout from item 6's guards.**
      Both guards fired twice in the whole reported run, far too rarely to
      explain a continuous fault, and ch0 froze at 127.7 s before either could
      have been involved. **It was never a regression** — attract mostly runs one
      clip at a time, so `last_created` is right by luck there, and the fault
      needs the two live pipelines only a game has.
      **The lesson is about where to look first:** this was found in twenty
      minutes from logs that had been sitting on disk since the report, without
      spending a run. The `serving` line in `padvid.log` already named the file
      per channel; nobody had counted them. `vidroute.py` does that now.

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
