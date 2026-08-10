# Spike 2 PC emulator — task queue

**`/next` takes the OPEN item with the LEAST PROGRESS**, tie-broken on which is
easiest — the full rule lives in `~/.claude/skills/next/SKILL.md` under "Which
item to take" and is not restated here, because two places defining one fact is
how this rig has been bitten before. An item nobody has touched is 0% and outranks
one sitting at 85%, so the queue advances on a broad front instead of grinding
one item down. **Order on this page is presentation, not priority**; it is only
the last tie-break, which is what moving lines around is still good for.

The `S1`–`S3` and `D1`–`D5` on each open item are its **severity and
difficulty, and together they break the tie** between items at the same
progress: severity first, then difficulty. **Lower is taken sooner in both** —
S1 is the worst thing, D1 is the cheapest job. Roughly, S1 breaks playing the
game, S2 costs runs or makes other items more expensive, S3 is friction with a
workaround. Both ladders live in the same place as the selection rule,
`~/.claude/skills/next/SKILL.md`, and are not restated here for the same
reason.

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
  guest can kill it (SIGBUS), and `padglhost` cannot be relinked while it runs
  at all (ETXTBSY). `build.sh` / `buildbridge.sh` only between runs.
  `ensurebuild.sh` — which `watch.sh` and `runbridge.sh` now go through, so a
  start builds what is missing and rebuilds what is stale — asks `alive.sh
  --total` before every build and refuses rather than risk it.
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
- **Item work commits on `item/<N>` in its own worktree, never straight to
  main.** Main is the release branch and only moves when a finished item is
  merged in — `/next` owns the mechanics (branch, sibling worktree dir, merge
  at close). No PRs, still: the merge is local and pushed.

## Queue

- [ ] **38. A run can strand its windows, and then EVERY later run is
      INVISIBLE — the game plays perfectly with no window, and every
      instrument in the rig says it is healthy.** `S2 D3`
      **Found 2026-08-10 during item 22's pass, with `zorder.py`, `shotwin.py`
      and `alive.sh`. Established, in order:**
      **(1) A run left two windows behind after a clean teardown.** The run was
      `watch.sh` on a title with no extracted game ELF, so the guest never
      started; teardown printed `TOTAL STILL RUNNING : 0  (clean)` and
      `star_wars_le - Stern Spike 2 emulator (Ubuntu)` plus `Controls - Spike 2
      emulator (Ubuntu)` stayed on the desktop as msrdc RAIL proxies. They are
      REAL windows, not leaked handles: `shotwin.py` grabbed one — PrintWindow
      1, 4.1% non-black — an empty black window with a working title bar and
      close button. **They ignore `WM_CLOSE`**, which makes sense: there is no
      X client left to receive `WM_DELETE_WINDOW`.
      **(2) The NEXT run then had no game window at all.** `padglhost` logged
      `window opened 1445x827 on DISPLAY=:0` and rendered **13997 frames in
      239.6 s (58.4 fps avg), swap 3.83 ms/f** — a flawless render loop — while
      `zorder.py --all` showed that no such window existed anywhere on the
      desktop. The guest played, video was handed over at 30.0/s, audio ran,
      `alive.sh` counted a full healthy run. The picture simply was not there
      and **nothing anywhere said so**.
      **(3) `wsl --shutdown` cleared it completely** and the next run's windows
      appeared normally, above the app, first time.
      **NOT ESTABLISHED — do not build on it: WHICH run wedged it, and whether
      the zombie is cause or symptom.** After run (2), `alive.sh` reported
      `zombies (cannot be killed, only reaped): 1` for the guest, held by a WSL
      interop Relay, and named `wsl --shutdown` as the only cure — but the
      windows were ALREADY stranded before that, at a moment when `alive.sh`
      had printed a clean 0. So the zombie is a second symptom at best.
      **Why this is worth more than it looks:** every oracle this rig owns
      reports healthy. Renderer fps, guest video rate, `alive.sh`, the run log
      — all normal. The one thing wrong is that there is no picture, and the
      rig cannot currently tell.
      **The cheapest first job is DETECTION, not a cure**, and the rig is
      already on the right side of the boundary to do it: `watch.sh` starts the
      playfield through Windows interop, so it can run `zorder.py` a few
      seconds after `window opened` and say "the game window never appeared on
      the desktop — `wsl --shutdown`" instead of leaving it to be discovered.
      **Second, unexplained and possibly the same wedge:** while stranded, an X
      client printed `your 131072x1 screen size is bogus. expect trouble`, and
      that line landed INSIDE `alive.sh`'s output, eating the
      `guest (comm=game)` label off its first line. `alive.sh` is the rig's only
      definition of clean, so a stray writer corrupting its first row is its own
      small bug.
      **Acceptance:** force the repro (a run on a title with no game ELF, then a
      normal run) and have the rig SAY the picture is missing rather than let it
      be discovered; then state whether the strand still happens once teardown
      is fixed, and on how many repeats.
      — S2: play itself is not broken and one command cures it, so it is not
      S1; what it costs is that the emulator can be silently unusable and every
      other item's runs are measured through it. Arguable as S1 for anyone who
      does not know the trick. D3: it needs a run, it reproduces on demand, and
      all three instruments already exist.

- [ ] **36. Saving a state on star_wars kills the donor run ~10 s later.**
      `S1 D4`
      **★ DAVID, 2026-08-10 ~13:00: "i tried to save and load on star wars
      and it crashed."** The evidence, mined the same minute
      (`c:/tmp/item27/gzwatch_sw_savecrash.log`): **THE SAVE SUCCEEDED** —
      slot3 `star_wars_le "sw game play"` packed, 63 MB, stamped at the
      checkpoint freeze (every channel's `worst gap` ~900 ms at 13:00:08 is
      the criu dump). **THE LOAD NEVER RAN** — no restore artifacts in
      slot3, no `[emulate] loading` line, no `dump/reloading` flag raised;
      what David called the crash of "save and load" is the GUEST EXITING
      BY ITSELF ~10 s after the dump resumed, CLEANLY: gzwatch ends at a
      healthy 49.9 fps with no segv block, no signal, no exit path — item
      23's first shape (the clean exit), now with its strongest correlate
      yet: **a leave-running criu dump 10 s earlier, on the title with four
      video channels and two EGL surfaces mid-clip-churn at the freeze.**
      Godzilla survives the identical dump (item 13 verified end-to-end,
      plus David's own sessions). Suspect space: the game's own watchdog
      tripping on the ~0.9 s world-stop (SW may time boards/audio tighter),
      or a frozen-mid-flight video/EGL thread resuming into an invariant SW
      exercises and Godzilla does not.
      **★★ THE LOAD HALF IS DIAGNOSED TO ONE CRIU LINE, 2026-08-10 13:08 —
      David tried Launch-into-slot3 and the restore failed BEFORE any guest
      ran:**
      ```
      criu/mount-v2.c:628: Can't stat mountpoint
        /tmp/.criu.mntns.*/mnt-0000000427/star_wars_le: No such file or dir
      cr-restore.c:2320: Restoring FAILED.   [loadgame] FAILED
      ```
      criu's mnt-v2 replay stages the guest's mount tree (`Bind
      mnt-421/games to mnt-427`, card mount 430 accepted as external) and
      then needs `games/star_wars_le` to EXIST as a directory to place the
      card bind on — it does not. **WHY GODZILLA LOADS AND STAR_WARS DOES
      NOT: `~/spike2root/games/godzilla_pro` is a POPULATED, PERSISTENT
      directory** (extracted long ago), so the mountpoint always stats;
      a PAD_CARD title runs with NO extraction (item 28's design) and its
      `/games/<title>` mountpoint exists only transiently inside the pivot
      namespace run_game.sh assembles at boot. **Suspect fix: pre-create
      the `games/<title>` mountpoint somewhere criu's staging can see it**
      — either run_game mkdirs it in the persistent rootfs games/ (cheap,
      matches why godzilla works; note `~/spike2root/games/star_wars_le`
      EXISTS but apparently not in the mount criu stages — verify which fs
      mnt-421 resolves to from the dump's mountpoints img before choosing),
      or loadgame/restorestate mkdir it just before `criu restore`. Full
      log: the 13:08 app pane (David's paste, in the transcript) +
      `c:/tmp/item27/gzwatch_sw_savecrash.log` for the save-side twin.
      **The SAVE-side death (the original sighting) is a SEPARATE fault**
      and still needs item 23's exit instrument: save succeeded, guest died
      cleanly 10 s later. Do not let the load fix close the item alone —
      acceptance is BOTH: (a) a star_wars save leaves the donor run alive
      (state how many repeats), and (b) Launch-into-slot restores a
      PAD_CARD title to a playing game on its own screen, cross-checked
      still working on godzilla.
      — S1: the feature's whole point is saving mid-play; saving kills the
      play and loading fails outright on card-run titles. D4 → D3 for the
      load half (one criu line, suspect fix in hand, needs runs); the save
      half keeps D4 until the exit instrument exists.

- [ ] **23. The game exits by itself mid-play.** `S1 D2` *(**D4 → D2,
      2026-08-06 evening, off item 11's runs:** a SECOND fault shape now has
      a signature, a call site, a disassembly, a minutes-scale repro AND a
      designed fix — see the starred block below. The original signatureless
      exit remains as described.)* *(**2026-08-10: item 36 is a fourth,
      PROVOKED sighting of the clean-exit shape** — a leave-running criu
      dump preceded it by 10 s on star_wars; the exit-reason instrument this
      item's acceptance (a) demands is now blocking BOTH items.)*
      **★★★ THE ORIGINAL SIGNATURELESS EXIT NOW HAS A NAMED PRECURSOR, and
      this entry's claim that "nothing anywhere records WHY the process went
      down" is CORRECTED. David's log, 2026-08-06 21:33, godzilla_pro,
      727 s (~12 min) into a run he was playing** (keyboard `k` and playfield
      `f` edges throughout). The last three video lines before the exit:
      ```
      [padvid 727.43] ch0 serving 1360x768 457 frames ... 2.asset/102.asset
      [vid] ch0 could not start the streaming thread
      [padvid 727.43] ch0 guest stopped mid-read after 0 frames
      ```
      then `[watch] the game exited` 10 s later, with **NO segv block** — the
      tail is the usual VPU firmware noise. So this is the FIRST shape (the
      clean exit), not the pthread churn segv and not the game-code NULL
      deref, and it now has a line naming a guest-side resource failure.
      **ESTABLISHED AT THE DESK, from the source, not guessed:** that message
      is `gstvid.c:1277`, printed when the `pthread_create` at `gstvid.c:1274`
      FAILS — the guest shim could not make a thread. And **`gstvid.c`
      contains no `pthread_detach` and no `pthread_join` anywhere** (grep: one
      `pthread_create`, zero of either). Every `vid_thread` is therefore
      created JOINABLE and never reaped, so each one holds its descriptor and
      its stack for the life of the process, and `pad_vid_play` makes one per
      clip serve.
      **ARITHMETIC, NOT A MEASUREMENT, so treat it as the reason to go and
      look rather than as a result:** a 32-bit ARM guest has ~3 GB of user
      address space and the default thread stack reserves 8 MB, so a few
      hundred leaked threads exhaust it. This one 727 s run shows well over a
      hundred serve/play cycles. That fits an exit that arrives after minutes
      of play and never at boot.
      **The candidate fix is one line** — detach the thread (or create it
      detached) at `gstvid.c:1274`. It is a shim change, so it needs a rebuild
      and no run may be live. **Do NOT let it stand as proven by the absence
      of a repeat:** the acceptance below wants a stated number of minutes.
      **NOT ESTABLISHED: that thread exhaustion is what ended THIS process.**
      The failure line and the exit are 10 s apart and nothing links them yet;
      `pad_vid_play` LOGS the failure and returns, so the shim itself does not
      die of it. What to measure first, and it needs no run: count live
      threads in the guest over a long session (`/proc/<pid>/status` Threads),
      and confirm it climbs with clip serves rather than sitting flat.
      **THIS EXPLAINS ONE SHAPE ONLY.** It cannot be the pthread NULL-mutex
      churn segv (that one faults, this one exits clean) and it cannot be the
      game-code NULL deref. Report against the signature, never against "the
      crash".
      **The renderer was healthy to the last line again:** 60.0 / 59.9 /
      60.4 fps with 30.0 NEW/s, and `alive.sh` printed 0 after teardown.
      **★★ ESTABLISHED BY ITEM 11'S RUNS (2026-08-06 evening): a
      REPRODUCIBLE churn-provoked SEGV, distinct from the original clean
      exit — do not merge them.** Five sightings in one evening (runs 2, 3,
      8, 9, 10 of item 11's pass), all during `longplay.sh` scene churn,
      three of them ~15 s in; runs with only 2 min of churn sometimes
      survive, so it is probabilistic with exposure. **Byte-identical every
      time: `pc=libpthread+0x8858` = pthread_mutex_lock, `lr=0x4db77c`,
      `r0=0x48`, `fault=0x0`.** The disassembly at the call site:
      `4db76c: add sl, r1, #72` → `pthread_mutex_lock(r1+0x48)` **with r1
      == NULL** — the game locks a queue object's mutex without a null
      check, something tears the object down under churn.
      **THE DESIGNED FIX, not yet built: the game CHECKS the lock's return
      value** (`4db780: bne 4db8fc` — a real error path). The shim is
      LD_PRELOADed, so interpose `pthread_mutex_lock`: argument below one
      page ⇒ return EINVAL instead of faulting. The game then takes its own
      error branch instead of dying. Verify by running the longplay-churn
      repro to survival, several times.
      **The instrument half of this item's acceptance is DEMONSTRATED** —
      the segv handler printed pc/lr/map/stack on every sighting; that is
      how all of the above was learned. The ORIGINAL sighting had ZERO segv
      output, so the clean-exit shape (threads asked to return, below) is a
      DIFFERENT path and still needs its exit-reason hook.
      **Crash logs preserved:**
      `~/crashlogs/gzpad_item11_run{8,9,10_control}.log` (run 10 = the
      control: cache off, same crash).
      **Repro recipe:** watch.sh 4 + the verified game recipe + longplay
      2 min; expect the exit within ~15 s of churn about half the time —
      run twice before calling anything fixed.
      **★ A THIRD SHAPE, CONFIRMED REPEATING 2026-08-06 20:02:38** (the
      end of David's own play session — the same run that reported item
      11's tearing — ~23.6 min in, renderer healthy to the last line at
      60 fps / 30 NEW/s, teardown clean). The app pane caught only the
      stack TAIL and the next run truncated gzpad.log before it could be
      preserved — but the five captured stack values are BYTE-IDENTICAL
      to `~/crashlogs/gz_item11_fix2.log` (stack[1]=0x4bb464,
      [5]=0x3cab40, [7]=0x230000, [13]=0x4ec8e4, [17]=0x254d14), whose
      COMPLETE block is preserved: **`pc=0x51ef7c` = game text +
      0x516f7c, `lr=0x6a48c`, `r0=0x0`, `fault=0x0` — a NULL deref in
      GAME code, NOT the pthread shape, so the designed EINVAL interpose
      would not catch this one.** Two sightings now, both 2026-08-06
      (the fix2 run, then this). Item 23 therefore holds THREE distinct
      exits — the clean thread-return, the pthread NULL-mutex churn
      segv, and this game-code NULL deref — and a fix for one is not a
      fix for the others; report against the signature, never against
      "the crash".
      **Instrument gap, noted not fixed (a run was live at the time):
      watch.sh's exit tail prints only the LAST lines of the segv block,
      so the pc/lr header scrolls off before the app pane sees it — it
      should grep the `[segv] pc=` header on exit so the pane always
      carries the signature.
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
      (Windows/Tk) reads `mrg[]` over 9p and `padglhost.c`'s Controls legend is
      drawn in X11 beside the switch keys.
      **CORRECTED 2026-08-06 by item 24: this entry said playfield.py "reads
      `mrg[]` every frame and already draws switch state". It does not.** It
      reads mrg for the COIN DOOR ALONE and every 8th tick at that
      (`DOOR_EVERY`); no switch marker is drawn from live state, and `tick()`
      touches only inserts and coils. So the trough display is a new reader and
      a new drawing path, not a re-colour of something already on screen.
      **Also from item 24, and it will bite this item: THE COIL MARKER SITS ON
      TOP OF THE SWITCH MARKER.** `_hit()` at the centre of RIGHT SCOOP returns
      the coil — the switch oval is not even in `find_overlapping` there,
      because it is drawn as an unfilled outline. Any per-switch drawing or
      interaction this item adds must not assume a click lands on the switch.
      The trough is ids 71..66 = TROUGH 1..6 and `swshow.py` (`e1e9cb3`)
      already counts and prints it. Six ball images and a "N balls in play"
      line is drawing, not discovery.
      **★ DAVID, 2026-08-06, and it SHARPENS (a) rather than adding to it:
      "i want to see visual indication of trough switches being correctly
      closed or open (probably part of our todo item that shows balls in play
      feedback)."** He is right that it belongs here. What it changes is the
      acceptance: a COUNT is not enough. Each of the six must read closed or
      open individually, **drawn in trough order — 71 TROUGH 1 the eject end
      through 66 TROUGH 6 the far end** — because the question he is asking is
      whether the state is CORRECT, and correctness for a trough is about
      WHICH position is empty, not how many are.
      **Why that ordering is the whole point, from this queue's own history:**
      item 20 was exactly a wrong-end bug — `plunge.py` opened TROUGH 1, the
      eject end, where a ball leaving can only ever open TROUGH 6 — and it took
      reading the guest's `[sw]` stream to see it (`-71l` gave the game
      `[70,69,68,67,66]`, `-66l` gave `[71,70,69,68,67]`). Six markers in
      trough order would have shown that by eye in one glance. This display is
      therefore a diagnostic for the ball model in (b), not only a comfort.
      **Read `mrg[]`, not `scr_held[]`** — what the GAME IS HANDED, per
      padsw.py's own rule, and confirmed as the right oracle by item 24.
      **Generalisation worth taking, but say if you do:** mrg is ONE read for
      all 256 ids, so drawing live state on every switch marker costs the same
      transport as drawing it on six. The trough is what David asked for; doing
      all of them is nearly free and makes the whole window honest.
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
      playfield window shows the six trough positions **individually closed or
      open, in trough order**, filling and emptying as the count changes, and
      says how many balls are in play; screenshot it, and include a shot with a
      ball REMOVED so the empty position is visibly at the far end and not the
      eject end. The cross-check is `swshow.py` on the same moment: the picture
      and the `mrg` row must agree.
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
      **★★ THE BLOCKING QUESTION IS ANSWERED. DAVID, 2026-08-06: "the left and
      right flipper buttons when needed to navigate the game options does not
      seem to react very well. it's hard to determine if i need to press it over
      and over again or hold it (for example: when selecting a battle). are the
      flipper keys working? (left and right arrows)"** This item's own Resume
      line asked which key and which screen before any of the repeat half was
      written. **The key: LEFT/RIGHT FLIPPER — 60 and 59 — bound to the left and
      right arrows in padglhost's `binds[]`. The screen: in-game option
      navigation, worked example BATTLE SELECT.**
      **The symptom is not "it does nothing", it is "the rule is not legible" —
      and this rig has ALREADY MEASURED exactly that, so start there rather than
      from scratch.** `padsw.h`: on the Main Menu a hold of 120 ms and 200 ms
      moved the cursor 0 rows, 250 ms moved 1 or 2, and 300 ms moved 3, because
      what decides it is how many SPI transfers land inside the hold. A rule
      that changes with the transfer phase is a rule a human cannot learn, which
      is precisely "hard to determine if I press it over and over or hold it".
      **NOT ESTABLISHED, and it is David's actual question: whether the flipper
      keys work AT ALL on that screen.** `swladder.py` laddered switch 34
      (node 1) and 46 (node 8) — **not 59 or 60** — so the flippers have never
      been through the instrument, and the 72/72 result does not cover them.
      Ladder 59 and 60 first; a flipper is on a different node from either
      switch already tested, and the sampling gap is per node.
      **New cost this exposes: BATTLE SELECT has never been reached by this
      rig**, the way `Diagnostics → Coil Test` has not (item 3). It needs a game
      played into a mode, not attract, so budget the run for that and say how
      you got there.
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
      **Resume:** ladder switches 59 and 60 with `swladder.py` — they have never
      been measured and David's report is about them. Then play into a battle
      and put `[key]` and `[sw]` both on, diffing each key edge's X-time width
      against the closure the guest was handed. **Do not ask David which key and
      which screen; he answered on 2026-08-06 and the answer is at the top of
      this item.**
      **The acceptance for the repeat half needs writing before it is built, and
      the bar David set is LEGIBILITY, not just delivery:** one press moves one
      row, and a hold repeats at a rate a human can predict — not 0 rows at
      200 ms and 3 rows at 300 ms. State the rule the fix gives and show it
      holds at several hold lengths.
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

- [ ] **1d. The a2 / b4 / b5 payload — WIRE DECODE SHIPPED; the item stays
      open for the NODE-BOARD FIRMWARE RE.** `S3 D5` *(**D3 → D5, 2026-08-07
      evening:** the wire half is done and released, and what David kept the
      item open FOR is a different and much harder job — decrypting LPC node
      firmware. Budget more than one pass and say so up front.)*
      **★★ DAVID'S VERDICT ON THE SHIPPED BUILD, 2026-08-07, after watching a
      live run: "i mean it's much better than it was. we can ship it for now,
      but the RE work on the firmware should keep this item open."** His eyes
      were the acceptance oracle for the rendering half and they passed it.
      **SHIPPED IN v0.117.0** (the tag landed on top of this work; the release
      notes credit it). Three decodes in one day, all live-verified: the a2
      pulse envelopes (`2520d44`), the b4/b5 bank fades (`d145083`), the form A
      multi-lamp steps (`c950da3`/`4a3eda1`).
      **SO THE REMAINING SCOPE IS EXACTLY TWO THINGS**, and neither is the
      payload census this item was originally about:
      **(a) THE NODE-BOARD FIRMWARE, which is the reason the item is open.**
      The true fade CURVES and the rate UNIT live in the boards, not on the
      wire — David's own diagnosis, and it is correct. Everything known about
      the attack surface is in the assessment below; it is a fresh Stern
      firmware-crypto crack.
      **(b) The header-prefixed long forms**, still skipped — 51 unique bodies
      in 25 (cmd, blen) groups across the whole capture, so smaller than it
      looks and independent of (a). `ledcensus.py` (committed with this) scores
      any capture against all six known forms and prints exactly these.
      **★ LEAD, noticed 2026-08-07 while validating that tool, NOT established:
      the long a2 bodies it cannot claim carry FORM A's OWN SIGNATURE.** e.g.
      `…0f0f00000f0f0f00000f | faf1f1f1a6aea0a0a0e9` — a `0f/00` FROM region
      followed by a TO region with value TRIPLES (`f1f1f1`, `a0a0a0`,
      `676767`, `e3e3e3`), which is the RGB-fixture tell that identified form A
      in the first place. **The value triples are real; the layout is not yet
      known, and the two obvious readings are now both DEAD.**
      **Ruled out (i): a fixed 3-byte header + form A.** `8f 19 f8 …` (the same
      opener `a6` uses) makes blen 27/30/33/36 land on 3N — but 29, 37 and 43
      do not.
      **Ruled out (ii), WITH A CONTROL, 2026-08-07: `[3 header][mask][FROM ×
      popcount][TO × popcount]`** — the a6 bitmap layout carrying two value
      regions, i.e. a bitmap FADE. Every qualitative sign was right (the first
      frame fitted exactly at 3+6+10+10=29, FROM came out of the 0f/00 level
      alphabet, TO carried the triples) **and it is still wrong: 38 of 152 real
      bodies fit (25%) against 20 of 152 for RANDOM bodies of the same lengths
      (13%), and the RGB tell scored 62% where form A scored ~100%.** Scanning
      the mask length is a free parameter, and a free parameter buys 13% of
      noise before explaining anything. The numbers and the reasoning are in
      `ledcensus.py`'s header as the worked example of why a control is
      mandatory here. **Whatever is tried next must beat that 13% floor.**
      **What is NOT left: the rendering.** The window already animates
      envelopes per channel, expires them onto the base, and reports its own
      picture rate honestly. When the curves are known they replace a linear
      ramp and a constant; no new plumbing.
      **★★ THE blen=6 SLICE IS DECODED AND SHIPPED, 2026-08-07, `2520d44` —
      NOT yet live-verified; the shim is unbuilt (a run was live all session)
      and ensurebuild rebuilds it at the next start.**
      **Established, from 93 captured frames across every c:/tmp capture:**
      `[start][0x80|end][FROM][TO][RISE][FALL]` — a ONE-SHOT PULSE ENVELOPE
      over the range: FROM→TO at the rate slot for the direction, back to
      FROM on the other slot, 0 = instant. 93/93 fit (86 fit the naive
      directional split; all 7 exceptions are one frame, `00ff0002` = flash
      with a decay tail). **Ruled out: chaining** (0 of 23 successive fades on
      a range join end-to-start — each command restarts its sweep, ×8 repeats
      = re-triggered blinks). **Ruled out: the pulses move the base level**
      (later base writes agree with TO only 57/651 — they are an OVERLAY, so
      the shim does not touch `val[]`). **The semantic confirmation:** joined
      against `led_io.txt`, the mid-level payloads land on the BUILDING FIRE
      banks — 72..86 -R gets `11→0f fall 6d` (ember) and `0f→ee rise 92`
      (flare), the -G bank fades out. The fire got fire commands.
      **Shipped:** padled version 3 fade ring (head @2076, 96×12B entries);
      `playfield.py` runs the envelopes per channel on top of the base
      picture; envelope frames do not count as picture updates so `LED Hz`
      stays honest; base-step smoothing dropped 200→80 ms (the "laggy" half
      of David's report). Offline: `ledratetest.py` ENVELOPE case — one
      12-byte command sweeps a fixture up and back and lands at base, 31
      distinct paints. **Also ruled out this pass, with numbers: David's
      throughput theory.** The bus idles at 150-200 transfers/s; the lamp
      slice is 2-39 writes/s by phase. Bandwidth was never the fault.
      **★★★ SECOND DECODE SAME DAY, `d145083`, LIVE-VERIFIED: b4/b5 blen=3/4
      are RANGE FADES (b4 up, b5 down, `[start][0x80|end][rate]`) and the
      indexed decoder had been eating them as ONE DIM DOT per bank sweep —
      rate bytes written as brightness.** Census 44/44 + 22/22, zero with the
      0x0f gap byte genuine single writes carry (97: 71/80); the 2N+1 shape
      now REQUIRES that gap byte at cnt=1, which also stops the a4/a5 pair
      frames (`3637bb`) becoming garbage lamp values. b4/b5 move the BASE:
      the shim writes the target into val[] and the ring envelope expires
      onto it — zero new window code. **Live, two runs, alive 0 after both:
      skip log shows ZERO a2-6/b4/b5-3/4 escaping; the window read LED
      4-6.7 Hz, worst gaps ≤0.91 s, 200-390 repaints/s of fade animation**
      (morning baseline: 2.6/s with 2.83 s freezes). David's 13:54 recording
      predates b4/b5 — a2 pulses visibly animate in it (runs of 9-11
      consecutive changed frames), freezes 1.2-3.6 s between.
      **Trace preserved: `/var/tmp/led_trace_1d.log`** — 44581 lines, full
      `PAD_NB_TRACE` with timestamps, plus 656 ledskip bodies. **Two
      instrument traps recorded in `d145083`'s message so nobody repays
      them: the guest log is `$LOG` = `gzwatch.log` NOT `gzpad.log`, and a
      UNC path quadruple-backslashed through bash reaches Python with ONE
      backslash — both ring-watchers polled a ghost file and read as "the
      ring never fills" while the window was animating the whole time.**
      **WHAT IS LEFT:** **(a) The rate UNIT is a guess** —
      `PAD_PF_FADE_UNIT_MS` (default 12, reader-side, tunes live). Ruled
      out: calibrating it from re-trigger periods (they cluster on the
      SHOW's schedule — 7.5 s and 115 s = the attract cycle — not the fade).
      Oracle: `Diagnostics → LED Tests`, or David's eyes vs the real
      machine. **(b) The longer a2/b4/b5 bodies** — still skipped, now
      CAPTURED with timestamps in the preserved trace; tails carry
      value-triple runs (`c7c7c7`) and index runs (`4c 4d 4e`) = multi-lamp
      fade programs. **Ruled out: the a6 bitmap layout at payload width
      1-4** (a2 fits at best 7 of 40). Note the strip boards (nodes 12/14)
      also carry b4/b5 in a DIFFERENT layout (`c00b000a`, bit7 on byte 0) —
      the insert-node gate keeps them out of the decoder, correctly.
      **★★★ THIRD DECODE, `c950da3`, live-verified: FORM A — the long a2
      bodies are `[refs…, last|0x80][FROM×N][TO×N]`, blen==3N**, a multi-lamp
      fade step. It signs itself: three CONSECUTIVE refs ⇒ an identical value
      TRIPLE in the TO region (an RGB fixture fading to one colour). Moves the
      base like b4/b5. **After a 4-min run: ZERO long a2 bodies left in the
      skip log.** What still skips: 389 a4/a5 blen=2 (lamp REFERENCES, no
      lamp data by construction), 26 blen=3 the gap-byte gate correctly
      pushed out, ~7 header-prefixed b4/b5 long forms.
      **★ RULED OUT, and it was the best remaining suspect: `cmd 0x70`.** It
      is the most common command on the insert boards (3483 node 8, 1935 node
      9, 1161 node 1) and is not in the decoder's gate, so it read as a whole
      missing lamp stream. It is not: body is ALWAYS `(index, 00, 00)` in
      6579/6579 frames, rlen 0, and it runs at a dead-constant 243 frames per
      20 s bucket from boot to teardown regardless of the light show. A
      brightness stream varies with the show; a 12.15 Hz metronome carrying no
      value is a refresh or keepalive. Do not decode it as lamp data.
      **★ DAVID's NODE-BOARD RE PROPOSAL, 2026-08-07, assessed not dismissed:
      "maybe if the fade curve logic lives in the node boards (and there's
      sparse data fed to them), we just need to look into the node board logic
      to RE what the curves are."** The premise is CORRECT and the firmware
      ships on the card — `games/<title>/*.hex`, and the LED ones are
      `coil4_lednode-LPC1313`, `ws2812node-LPC1313`, `ws2812pinnode-LPC1313`,
      `hdmi_ws2812node-LPC1313`. **But they are ENCRYPTED, measured:** valid
      Intel HEX (400/400 checksums) wrapping ciphertext — **entropy 7.992
      bits/byte, 0.4% zero bytes, all 256 values present, no plausible
      Cortex-M vector table** (word 0 = 0x7ce94728, not an LPC1313 stack
      pointer). **Ruled out: repeating-key XOR** — index of coincidence is
      0.0039 (= random) at every period 1…1024 — and **a shared-plaintext
      crib between siblings**: `ws2812node` vs `hdmi_ws2812node` are the same
      length and share only 0.4% of bytes, i.e. no aligned common code. Note
      the four non-data records at the top (types 06/07, 58 bytes total) are
      unexplained and are the obvious place a header/IV would live. **So this
      is a real project (a new Stern firmware-crypto crack), not an
      afternoon** — worth its own queue item if David wants the true curves;
      until then the curve is linear and the unit is a knob.
      **Resume — and it is the FIRMWARE now, not the wire.** Start at the four
      non-data Intel HEX records (types 06/07, 58 bytes total) at the top of
      each `.hex`: they are the only unexplained structure in the file and are
      where a header, key id or IV would live. Compare them ACROSS the four LED
      node files and across titles — `~/spike2root/games/*/`, and every title's
      card carries the same `1_35_0` firmware set, so a repeated block is a
      constant and a varying one is per-image. Then, before any crypto: check
      whether a plaintext LPC image of the same part exists anywhere (NXP
      bootloader stubs, an unencrypted older Spike release) to give a known
      pair. **Already ruled out, do not repeat: repeating-key XOR** (IC 0.0039
      at every period 1…1024) **and a sibling crib** (`ws2812node` vs
      `hdmi_ws2812node`: same length, 0.4% shared bytes).
      **The cheap fallback if the crypto holds:** the curve is only two
      unknowns — shape and unit — and both are visible from OUTSIDE the board.
      `Diagnostics → LED Tests` drives one fixture at a time by name; filming
      a real machine, or David's eye against ours, calibrates
      `PAD_PF_FADE_UNIT_MS` and says whether the ramp is linear or gamma'd,
      with no firmware at all. Do that first if a pass has to produce
      something. Trace for any wire question: `/var/tmp/led_trace_1d.log`.

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

- [ ] **26. Right-click-hold a switch to RIP IT, for spinners.** `S3 D4`
      **★ DAVID, 2026-08-06: "for switches, let's also add a right click hold
      function that 'rips the spinner' as long as the click is held."**
      The sibling of item 24: left-hold closes a switch and keeps it closed,
      right-hold should make it close over and over for as long as the button
      is down, the way a ball spinning a spinner does. **Godzilla's three
      spinners: 47 LEFT SPINNER (node 8 bit 9), 83 TOP SPINNER (node 9 bit 21),
      84 RIGHT SPINNER (node 9 bit 28).** No `<Button-3>` binding exists
      anywhere in `playfield.py` today.
      **★★ ESTABLISHED AT THE DESK, from `hwshim.c`, and it decides the whole
      shape — do NOT build a host-side pulse loop.** The `0x11` switch scan
      replies with a per-switch LEVEL, not a closure count: `hwshim.c:4464` is
      `if (held) level = !level` into a bitmap. So the game counts spins by
      DIFFING successive scans, which caps the rip at **one closure per scan of
      that switch's own node** however fast anything pulses. Two rates bound it
      and they are not the same number: the poll itself is described as a
      37.5 Hz scan (`hwshim.c:5665`), but item 17 measured the gap between two
      scans of ONE node running to **670 ms in attract**. The during-play
      per-node rate has never been measured and is the first thing to find out.
      **Which also kills the obvious implementation.** Each host action is a
      ~80 ms `wsl.exe` spawn (item 24, measured) and each closure needs two, so
      a host-side ripper tops out near 6 closures/s while saturating
      SwitchDriver's queue and blocking every other switch action including a
      release.
      **THE DESIGN THIS POINTS AT, not yet built:** a SPIN flag in the shared
      block, and `hwshim.c` flips the reported level on each scan of that node
      while the flag is set. That delivers the maximum rate the wire can carry
      by construction and costs ONE interop call on press and one on release,
      exactly like `swhold.py`. Right-click then rides item 24's `SwitchDriver`
      queue unchanged.
      **What makes it D4 rather than D2: it spans the boundary.** A new flag
      means `padsw.h`, `padsw.py`, a new `swspin.py`, `hwshim.c` and
      `playfield.py` — and the block layout is THREE hand-kept copies, which is
      what `swlayout.sh` (item 16, `145e79b`) exists to prove agree. Run
      `swlayout.sh` before believing any of it. A rebuild is needed, so no run
      may be live. The ladder would call a boundary-spanning change D5; it is
      D4 because the mechanism above is already read off the source and the
      design is written down, which is what D5 usually pays for.
      **Acceptance, and the oracle must be on the GAME's side of the wire:** a
      right-hold on a spinner produces many closures the GAME SEES, not many
      writes this rig made. Count them with item 17's `PAD_SW_PEND` /
      `swladder.py`, which read the game's own `entry[+24]`, and state the
      achieved closures per second against the measured per-node scan rate.
      Left-click hold must still behave as item 24 shipped it, and a right-hold
      must end OPEN — the stuck-switch failure is the same one, and
      `swholdtest.py` is the harness that already checks for it.
      — S3: nothing is broken and a spinner can still be closed once per click,
      so no shot is unreachable; what is missing is the magnitude. D4, armchair
      beyond the desk work above.

- [ ] **29. Switch names come back as `?` on most titles, so the schematic
      playfield is a list of numbers and switch positions cannot be joined.**
      `S2 D3` **← 75%, and the USER-FACING half is DONE.** *(**S2 → S1 → back to
      S2 within one day, 2026-08-10, and both moves were on evidence.** Up: the
      Jaws run showed `?` names BLOCK PLAY, because nothing could find the
      trough and the game sat on LOCATING PINBALLS. Down: item 27's `6d19946`
      then supplied the names from the title's own device table, so nothing is
      blocked any more. D4 → D3: the instrument this item said had to be built
      first is no longer on the critical path.)*
      **★★ WHAT IS ALREADY SOLVED, in item 27, do not redo it: `swnames.py`
      fills the names WITHOUT fixing the reader** — the device table carries a
      name for every playfield switch, and the join is on ORDER within a node
      (not the number, which this item correctly ruled out). Validated by
      blanking and refilling the two titles that have real names: **godzilla_pro
      86/0 wrong, john_wick_le 102/0 wrong; jaws_le fills 105 of 108.** The
      schematic therefore shows real names, and because `switch_xy` joins on the
      NAME, the positions this item's part (b) asked for should now join too —
      **unverified, and it is the cheapest thing left to check.**
      **WHAT REMAINS IS THE READER ITSELF**, which is still wrong and is why 3
      switches per title stay `?`: they are the virtual/extra switches with no
      device record (Jaws's bits 61-63 on node 9). Fixing `msg_row`/`MSG_LANG`
      would name those and anything else that goes through the message table.
      **Corrected by item 27's runs: star_wars_le is NOT in the failing set — it
      has 104 real names and NO device table**, the mirror image of Jaws. So the
      two name sources are independent, and this item's title census should be
      re-read with that in mind.
      **MEASURED 2026-08-06 across four card runs, and the split is clean:**
      Led Zeppelin LE 1.22.0 **96 of 96 rows `?`**, Elvira's HoH 1.13.0 **109 of
      109 `?`**, Jaws LE 1.02.0 **108 of 108 `?`** — and **John Wick LE 1.01.0
      0 of 105**, real names (`QR SCANNER STATUS READY`, …). Godzilla is also
      fine. So this is per title, not universal, and at least two titles prove
      the reader itself works.
      **WHAT IT COSTS, and it is two separate things.** (a) The schematic view
      draws 96 rows that all say `?`, so you cannot tell which switch you are
      about to close — see the screenshot behaviour in item 27's sense of "see a
      switch layout". (b) `switch_xy` is joined on the NAME, so a title with a
      perfectly good device table gets **no clickable positions at all**: Jaws
      has 78 switch records with names and coordinates in its binary and scored
      `NONE of the 108 switches matched a device-table name`.
      **ESTABLISHED AT THE DESK, from `hwshim.c`:** the name is
      `msg_row(*(nameobj + 16))` at `hwshim.c:3574`, and `msg_row` (`:3219`)
      opens with `if (!MSG_LANG) return 0;`. `MSG_LANG` is
      `TITLE_ADDR(a_msg_lang, "PAD_MSG_LANG", 0x708330u)` — a **Godzilla Pro
      1.15.0** address (`:2960`).
      **BUT THE OBVIOUS ONE-LINE FIX IS PROBABLY NOT IT, and this is the trap
      worth writing down before someone spends a pass on it.** `title_addr()`
      (`:1267`) returns the default whenever it is merely READABLE, and this
      file already records that trap for the switch table: *"EHOH's binary is
      big enough to cover Godzilla Pro's 0x7a958c, so a_sw_struct() returned an
      address … and the shim read a switch table out of somebody else's data."*
      So on these titles `MSG_LANG` is most likely non-zero-but-wrong, the
      early-out never fires, and `msg_row` is instead failing one of its two
      range checks on `row` or `row[0]`. **Making `!MSG_LANG` fall back to
      language slot 0 is therefore a guess, not a fix** — and note `msg_row`
      ALREADY tolerates a garbage `lang` (it validates `lang < 5` and the
      resulting pointer, falling back to slot 0), which is more evidence the
      early-out is not where this dies.
      **FIRST JOB IS AN INSTRUMENT, WHICH IS THE D4.** Print `nameobj`, `row`,
      `row[0]` and `MSG_LANG`'s value for the first few switches on a title that
      fails and on John Wick, which does not. That says in one run whether the
      name object is absent, at a different offset, or pointing at a message
      table this shim cannot resolve. Only then choose between a per-title
      `PAD_MSG_LANG`, a shape-based finder like `sw_find_table`, and reading the
      names some other way.
      **RULED OUT — joining on the NUMBER instead.** `switchxy.py`'s own header
      says why: the device table's `index` is a sequential position within its
      board and not the hardware bit (node 8 runs bits 9,10,11… against index
      8,9,10…, then the hardware skips 21-23 and the index does not), so a
      numeric join "produces a map that looks right and presses the wrong
      switch". Do not reach for it as a workaround.
      **Acceptance:** on a title that fails today, the schematic shows real
      switch names, and a title that also ships a device table gets its switches
      placed on the artwork. State which titles you checked and include one that
      already worked (John Wick or Godzilla) as a regression control.
      — S2: the playfield opens, is clickable and the keyboard works, so nobody
      is blocked from playing; what it costs is that the switch layout is
      unreadable on three of the four titles tried and that positions are
      unavailable on a title whose binary has them. Arguable as S1 against item
      27's wording, which asked to "see a switch layout". D4: the mechanism is
      NOT established, the leading theory is explicitly marked above as probably
      wrong, and it needs a guest-side instrument and a run before anything can
      be chosen.

- [ ] **30. In the container, a run ends by itself after about 60 seconds.**
      `S2 D3`
      **MEASURED 2026-08-07, Docker Desktop on WINDOWS (not the target - see
      below). Everything about the run is healthy until it stops.** Guest
      producing **57.1 fps** (`[eglshim] 3460 frames in 60559 ms`), renderer
      59.9/59.6 fps and 56.5 avg, card mounted, tables built from the card,
      playfield window open, teardown clean and `alive.sh` 0 after. Then at
      ~62 s: `[watch] stopping...` and nothing else.
      **ESTABLISHED, and it rules out the obvious causes.** `watch.sh`'s poll
      loop has exactly three exits and **NONE of their messages printed** —
      not `renderer exited (window closed)`, not `the game exited`, not
      `N min backstop reached` — and the script never reached the
      `grep -aE 'fps|stopped' "$HOSTLOG"` line that sits between the loop and
      the end of the script. So the loop did not break: the script took a
      SIGNAL, and one whose trap could still run (`[watch] stopping...` is
      printed BY teardown), so SIGINT or SIGTERM and not SIGKILL. `cfg MINS=3`
      is in the log, so the backstop was 180 s and not 60.
      **RULED OUT:** the test harness (it happens with the PowerShell pipeline
      removed and output going to a file); anything the rig starts (grepped
      `autoattract.sh`, `gamestate.sh`, `status.sh` — no `kill` anywhere); the
      guest exiting on its own (teardown had to SIGKILL it, so it was alive);
      the wall-clock backstop; and the OOM killer, which sends SIGKILL and
      would not have let the trap run.
      **THE TEST PLATFORM IS NOT THE TARGET, and that has to be settled first.**
      This was Docker Desktop on **Windows**, which runs containers inside a
      WSL2 VM. macOS uses a completely different VM layer. The container is
      identical; the thing around it is not. So the FIRST job is to find out
      whether this reproduces on a Mac at all — it may be an artefact of the
      Windows host and no macOS user would ever see it.
      **Second, cheaper job if it does reproduce:** put a signal trap in
      `watch.sh` that names what it received (`trap 'echo "[watch] got SIG$s"'`
      for INT/TERM/HUP), which turns one run into an answer. HUP is the
      candidate worth suspecting given a container's session semantics.
      **Related and unexplained: NO VIDEO in the container.** `padvidhost.py`
      came up (`ready: /pad/rootfs/dump/padvid (95 MB, 8 channels x 4 slots)`)
      but zero clips streamed in either run, where a WSL run of the same card
      streams continuously. Not investigated at all.
      **Acceptance:** a container run reaches its wall-clock backstop and says
      so, on the platform it is for. State which host you tested on, because
      this item exists because that distinction was not controlled for.
      — S2: the emulator runs at full speed in the container, so nothing is
      broken outright and this is not S1; what it costs is that no macOS
      session lasts longer than a minute, which is most of the value. D3: it
      needs a run, it reproduces every time, and the instrument is a one-line
      trap - the unknown is which host it belongs to, not how to see it.

- [ ] **32. Stretching the game window brings the emulation to a crawl.**
      `S2 D3`
      **★ DAVID, 2026-08-07: "stretching the display size for the stern spike 2
      emulator window brings the emulation to a crawl (like when I make it 3 or
      four times larger)."** The desktop is 3840x2160 at 120 Hz, so "3 or four
      times" the default 1360x768 is at or past maximised.
      **ESTABLISHED AT THE DESK, FROM THE SOURCE, AND IT NARROWS THE SEARCH
      BEFORE ANY RUN: the guest's own drawing does NOT grow with the window.**
      `fb_w`/`fb_h` are set once from `PAD_GL_W`/`PAD_GL_H` (`padglhost.c:2079`)
      and the guest renders into `tex_screen` at that size whatever the window
      does. The only thing that scales is `win_present()` (`padglhost.c:1367`):
      one textured quad letterboxed into `win_w x win_h`, then `eglSwapBuffers`.
      **ARITHMETIC, NOT A MEASUREMENT, so treat it as a reason to look further
      rather than as a result — and it says the GPU fill is NOT enough on its
      own.** `gpuprobe` measured the default adapter (the AMD iGPU, item 18) at
      **1.096 ms/frame for 4 full-screen 1080p quads = 8.29 Mpixel**. The blit is
      1.04 Mpixel at 1360x768 and ~8.3 Mpixel maximised, i.e. **~0.14 ms →
      ~1.1 ms against a 16.7 ms budget**. That is real but it is not a crawl, so
      do not stop at "it is the integrated GPU". The untested suspects are
      downstream of the quad: the per-frame **cross-adapter copy** to a display
      the NVIDIA card owns, the **msrdc RAIL present** of a much larger surface,
      and whether either back-pressures the guest through the swap.
      **RELATED MEASUREMENT, so nobody re-derives it: item 18 found msrdc CPU is
      not pixel-proportional** — a quarter of the pixels moved it 72.1 → 70.3.
      **But that was tested DOWNWARD from the default and never above it**, which
      is the whole range this item is about.
      **EVERY INSTRUMENT NEEDED ALREADY EXISTS AND THE THREE SEPARATE THE TWO
      HALVES:** `[eglshim] N frames in M ms = X fps` is the GUEST's own rate,
      `padglhost`'s `fps` line is the HOST's, and item 11's `swap_us` says how
      long `eglSwapBuffers` blocks. Guest fps falling with host fps while
      `swap_us` balloons is back-pressure; host fps falling alone is a display
      cost only. **A free fourth oracle needs no instrument at all: audio does
      not go through the renderer** (`padplay.py`, Windows side), so if the sound
      crawls too, the guest genuinely slowed.
      **REPRO WITHOUT TOUCHING A WINDOW, which matters because `SetWindowPos` on
      an emulator window is a standing non-negotiable:** item 5 (`19e1b85`) made
      `.pad_windows` lines `key x y [w h]` and padglhost CREATES at the saved
      size — so write a big size in and start the run. If a resize DURING a run
      is wanted, item 5's verified technique is a SendInput corner drag from a
      DPI-aware process, not a programmatic move.
      **Two levers exist but are knobs awaiting an A/B, not fixes:**
      `PAD_GL_ADAPTER` (built for item 18, **unset by default**) points Mesa at
      the NVIDIA card, and `PAD_GL_WIN_EVERY` presents every Nth frame.
      **Acceptance:** state the window size in pixels and all three rates (guest
      `[eglshim]`, host `fps`, `swap_us`) at the default size and at ~4x, on the
      same run recipe — that pair alone is the finding, and it is worth a commit
      even if no fix follows. A FIX means the guest's own fps holds at ~4x within
      a stated margin of its default-size figure, with the picture still correct
      and letterboxed, and dragging plus the item 5 size restore still working
      afterwards — that is exactly what the banned fix broke.
      — S2: play works at the default size so nobody is blocked outright, which
      is why it is not S1; what it costs is playing at a viewable size on a 4K
      desktop, and it makes every item whose oracle is David's eyes (1d's fade
      curves, 21's trough markers) dearer by pinning the window small. Arguable
      as S1 if you read "the game visibly misbehaves while you are playing it" as
      covering a size the user chose. D3: needs a run, it shows up the moment you
      look, and all three instruments exist and are validated — the unknown is
      which stage of the present path pays, not how to see it.

- [ ] **33. Save-state slots are invisible: nothing shows what exists or what
      it costs.** `S3 D2` **★ DAVID, 2026-08-09: "maybe our save states are not
      being pruned?... we should have clear visibility of what kind of space
      they're taking up."** Asked while chasing that day's startup freeze, which
      turned out to be unrelated (v0.120.3, a poisoned log line) — but the
      visibility gap he tripped over is real: the only way to see slots today
      is `du -sh` inside WSL.
      **Measured 2026-08-09:** slots live in `<rootfs>/saves/<slot>` (criu
      dumps, `savegame.sh:48`); on this machine `/home/david/spike2root/saves`
      = quicksave 511 MB + wtest 475 MB = 985 MB. **Pruning is NOT broken and
      is not the job** — `savegame.sh` `rm -rf`s a slot before each re-dump, so
      growth is bounded per slot name; what is missing is the LIST. The GUI
      half rides on item 13's StateOps mixin (both playfield views' Save/Load
      buttons), and any slot browser must respect restorestate.sh's pre-flight
      rules (a dead-tty or gone-card slot is refusable, and saying WHY in the
      list would save a failed load).
      **Related cleanup found the same day, David to confirm before anyone
      deletes:** `/home/david/wtest.log` is 13 GB of watch.sh test debris;
      `~/cardcache` is 43 GB and is EXPECTED (per-title tables), keep it.
      **★ THE CORE ASK SHIPPED 2026-08-10 with item 13's GUI batch (~90%):
      the Emulate tab's Save states manager lists every slot with name,
      game, size and date, totals them against the WSL disk's free space,
      and Renames/Deletes** (slots.sh, root, guarded). David can now
      delete `wtest` himself from the tab. REMAINING here: the list does
      not yet flag a REFUSABLE slot (dead-tty / gone-card per
      restorestate.sh's pre-flight) with the reason a load would fail -
      the polish this item's text asked for beyond the list itself.
      **Acceptance:** wherever Save/Load already lives (playfield bar and/or
      Emulate tab), the user can see every slot with its size and save time
      plus a total, and can delete a slot from there; the numbers match `du`
      on the same moment. — S3: a `du` in WSL answers it today, nothing is
      broken. D2: the mechanism is fully known (list a directory, stat, rm),
      but the UI half wants a windowed session to verify, which is what keeps
      it off D1.

- [ ] **34. Booting the same card from a different path re-copies the whole
      image, so "first run only" slowness comes back.** `S3 D2`
      **Observed 2026-08-09 (David's godzilla_pro session):** "Startup In
      Progress" for ~3 min — first frame at 177 s against the ~15 s a cached
      boot takes — with input laggy while the copy competed with the boot's own
      9p reads, and the placeholder-looking attract screens that follow a boot
      nobody advances confused the whole session.
      **ESTABLISHED AT THE DESK, from the source:** `cardmount.sh`
      `cache_pick()` validates the local copy against a stamp of
      `stat -c "%n %s %Y"` — the PATH is part of the identity. David has the
      byte-identical card (size 7861174272, mtime Jul 28 12:45:11) at three
      paths — a D: shortcut target, repo `images/Stern/spike2/`, and the
      OneDrive Desktop — and every path switch invalidates the stamp and
      re-runs the full 7.3 GB dd while the game boots off the un-cached 9p
      mount. `~/cardcache/godzilla_pro-1_15_0_spike2.log` carries EIGHT
      "local cache complete" lines, and the stamp was watched flipping
      repo → Desktop within 13 minutes on 2026-08-09.
      **Fix:** compare size+mtime only (fields 2-3 of the stamp), keeping
      invalidation for a genuinely new build — a re-exported card gets a new
      size/mtime and still re-copies. **The trade, and say it in the commit:**
      two DIFFERENT cards sharing a label AND coincidentally identical
      size+mtime would wrongly share a cache — vanishingly unlikely for card
      images, but it is a real narrowing of the identity.
      **Acceptance:** boot one card from two different paths back to back; the
      second boot logs `using local cache` and starts no copier; then touch the
      image's mtime and confirm that boot DOES re-copy. State the
      boot-to-first-picture time of the second boot.
      — S3: nothing is broken and the workaround is total (launch from one
      consistent path); what it costs is a ~3 min boot and a confusing session
      whenever paths alternate. D2: the change is a few characters in one
      comparison, established from the source above; the acceptance needs one
      confirming session of two boots plus the negative case, which is what
      keeps it off D1.

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
- **`/var/tmp/led_trace_1d.log`** (inside WSL) — item 1d's evidence: 44581
  lines of `PAD_NB_TRACE=1` with guest-ms timestamps plus 656 `[ledskip]`
  bodies, from a 2026-08-07 godzilla_pro attract run. It is what all three
  lamp-frame decodes were scored on, and `ledcensus.py` defaults to
  `/var/tmp/led_trace*.log` for that reason. Machine-local rather than
  committed because it is 3.5 MB of one machine's run; **re-capture with
  `PAD_NB_TRACE=1 PAD_LED_SKIP_LOG=3000 watch.sh N` if it is ever lost**, and
  note `/var/tmp` and not `/tmp`, which this WSL wipes on restart.
- **`/var/tmp/criubuild/criu/criu/criu`** (inside WSL) — item 13's CRIU, v4.1,
  **built from source because criu is NOT PACKAGED for Ubuntu 24.04** (zero apt
  candidate with universe enabled). `criuladder.sh` defaults to this path and
  takes `CRIU=` to override. Rebuild with `git clone --depth 1 --branch v4.1
  https://github.com/checkpoint-restore/criu.git && make -j8`; the build needs
  the documented deps **plus `uuid-dev`**, which it aborts on without naming,
  and `libaio-dev` + `python3-yaml` for its own tests. It needs root to run, and
  `wsl -u root` gives that with no password on this machine. Not committed
  because it is a 6 MB binary built for one kernel.
- **`plans/spike2_pc_emulation_handoff.md`** — gitignored on purpose, local to
  this machine. The deep detail behind every numbered item above.

## Loose ends worth a look, not yet worth a queue slot

- **The Linux path has never been run on a real Linux desktop, and the one part
  that cannot be tested from here is the playfield WINDOW.** Everything else was
  exercised with `PAD_FORCE_NATIVE=1` on 2026-08-07 and works: the pulse audio
  sink is chosen rather than the Windows bridge, the `/mnt/wslg` wait is skipped
  (0 mentions in the log), the game boots and the renderer averaged **57.9 fps
  over 120 s**, `alive.sh` printed 0. The window is the gap because THIS WSL has
  no tkinter at all — which is the entire reason the Windows workaround exists —
  so the native branch can only be seen refusing correctly and naming the
  package. Someone with a Linux machine and a card image closes this in one run.
- **macOS needs a decision, not effort.** `qemu-user` translates *Linux*
  syscalls, and `unshare`, user namespaces and `chroot` into an ELF rootfs are
  Linux kernel features, so there is no port — only "run Linux there", via
  Docker or Lima. **The obvious objection is wrong and worth writing down:
  software rendering is NOT the blocker.** The handoff's own measured table has
  llvmpipe at **214 fps** on the real workload against 914 on the GPU; the 1.0
  fps figure people remember is `glraster.c` INSIDE the emulated ARM guest,
  which the bridge design already replaced and which a container would not use.
  The real unknown is the display transport — Docker on macOS has no display, so
  frames cross X11 to XQuartz — and nobody has measured that. It is an
  afternoon: run `padglhost` against XQuartz and read the fps it already prints.

- **PROMOTED TO ITEM 31 on 2026-08-07 — "Playfield LED markers choppy in
  ATTRACT, undiagnosed"** sat here unnumbered from item 11's closure because it
  had no acceptance condition. It has one now, and a measurement: 2.6 visual
  updates a second against a status bar reading 30 fps. What this bullet said
  and item 31 must not lose: in GAMEPLAY the choppiness followed the game's
  render loop, so item 11's fixes plausibly cover that half; in ATTRACT it did
  NOT — that loop held 60.1 fps while the LEDs still looked choppy.

- **`watch.sh` with no `PAD_GAME` currently cannot start, and the error does not
  say why.** `GAME` falls back to `readlink games/game`, and that symlink is left
  pointing at whatever ran last — after item 36's star_wars card session it reads
  `star_wars_le/game`, and `~/spike2root/games/star_wars_le` **does not exist at
  all**, because a `PAD_CARD` title runs with no extraction (item 28). A bare
  `watch.sh` therefore dies with `[run] no game ELF at
  .../games/star_wars_le/game` and lists the extracted titles, which reads like
  the rootfs is broken rather than like a stale symlink. Seen 2026-08-10.
  Either point the fallback at a title that exists, or say "the last run was a
  card run; pass PAD_GAME".

- **A `PAD_PIVOT` (root) run leaves root-owned files in `dump/` that later user
  runs cannot write.** Seen 2026-08-10 after item 36's save-state session:
  `watch.sh` printed `dump/boot.id: Permission denied` twice at the start of
  every subsequent ordinary run. Harmless so far — the run continues — but it is
  a root/user split in a directory both launches write, and boot.id is what
  identifies a boot.

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

- [x] **22. Start Emulator leaves the game window BEHIND the app.** DONE
      2026-08-10, `6f3a907` (branch `91ffa1d`..`6f3a907`). **Closed on David's
      own Start Emulator press: "ok, looks like it is resolved now".**
      **The fix is `win_raise_all()` in `padglhost.c`:** `XRaiseWindow` on both
      windows **from inside X** (never `SetWindowPos` — the standing
      non-negotiable), restack only with no `XSetInputFocus`, and crucially as
      a **RETRYING SCHEDULE** — once when the position restore settles, then at
      8, 16, 24, 32, 40, 50, 60, 75 and 90 s. `PAD_GL_RAISE=0` reverts with no
      rebuild.
      **THE SCHEDULE IS THE FIX, NOT THE RAISE.** A single raise does nothing —
      David caught that build himself, a screenshot of the app on top of the
      game window from a run whose log carried `raised both windows above the
      desktop` — and a 4-deep schedule out to 30 s also failed. What that
      bought is the shape of the fault: **there is a period after user input
      during which the emulator's window cannot come to the front, and a raise
      inside it is spent. After it lapses a raise lands AND STICKS.**
      **Settled by a single-variable A/B**, both runs with the other window
      activated **under a second** before launch (what a real button press
      creates): `PAD_GL_RAISE=0` → game window BELOW, unchanged over 115 s;
      `PAD_GL_RAISE=1` → ABOVE from 8 s, stable over 115 s. Re-confirmed on
      shipped defaults with no override: PLAYFIELD 1, CONTROLS 2, GAME 3.
      **New instrument, `tools/spike2_emu/zorder.py`**, which is the half of
      the acceptance that asked for the order to be READ and not eyeballed:
      walks `GetTopWindow` + `GW_HWNDNEXT` (the documented z-order) rather than
      `EnumWindows` (which only promises an enumeration) and prints any
      disagreement; self-tests every reading against `GetForegroundWindow`;
      `--baseline` marks NEW against windows stranded by an earlier run;
      `--watch N` prints a line per change.
      **RULED OUT, do not re-test.** (i) This item's own theory, that the two
      windows are mapped at different TIMES with the game waiting for the first
      frame — they are mapped microseconds apart in the same function, before
      EGL is initialised. (ii) `eglSwapBuffers` re-asserting the stacking every
      frame — suppressing presents let a raise stick where it had not, which is
      what pointed at it, but the winning run has a raise landing with swaps at
      full rate and holding for two minutes. (iii) A raise at the FIRST present
      (~0 s, before the compositor has placed the window) — the build carrying
      one is the build whose retries failed. (iv) Any foreground-RIGHTS story:
      the legend held the FOREGROUND while the game window could not beat a
      plain Notepad, and both belong to the same msrdc process.
      **THE METHODOLOGY LESSON, which cost this pass two wrong conclusions and
      is why it is written here: a test MUST activate the other window
      IMMEDIATELY before the run.** With a ~40 s stale activation the fault
      does not reproduce at all, and a broken fix reads as working — that is
      exactly how this pass twice believed it was finished.
      **Split out: item 38** (a run stranding its windows, after which every
      later run is invisible).

- [x] **27. Any Spike 2 title should load, show a switch layout, start a game,
      and play with correct video.** DONE 2026-08-10, `332ed6a` (11 commits,
      `3c95b49`..`332ed6a`), item 35 absorbed. **The whole item was one
      disease five times over: a per-title fact hard-coded to Godzilla Pro.**
      The node census derives silenced boards from the title's own tables
      (device table, switch-list fallback); switch NAMES fill from the device
      table by discovered per-node order-shift (188/192 refill, zero wrong);
      switch POSITIONS join list x device table on the name with no run
      involved (jaws 58 placed, john_wick 57/57, godzilla 41/41 self-test);
      padglhost's key binds and window-open latch resolve by name per title
      (star_wars flippers, David: "flippers work now"); the shim's boot-time
      machine-at-rest set resolves its trough per title - THE Jaws
      start-refusal, because the game decides at boot whether its ball
      devices have balls. The video flicker was two EGL surfaces (backbox +
      star_wars's real playfield LCD) collapsed into one swap chain -
      presenting only the primary ended it (32.8% black frames -> 5.0%
      content fades, luma churn 9.71 -> 0.59, David: "the flickering is gone
      i can confirm"). Verified on the game's own screens: star_wars attract
      + flippers by David's hands; jaws PLAYER 1 game started, 58 switch
      markers + 60 inserts + 14 coils live on its artwork. The light-show
      RATE signal (30 lamp cmds / 3 s) is gamestate's "past Tech Alerts";
      autoattract GAP 45 s. Long form: handoff REMAINING item 27 (three
      dated sections). Leads left behind: playfield-LCD feed as a second
      window (/add candidate); swshow.py still prints Godzilla names
      (cosmetic); one new item-23 segv signature preserved
      (gzwatch_swverify_segv.log).

- [x] **13. Save and load save states.** DONE 2026-08-10, shipped in
      **v0.121.0** — the opt-in GUI (toggle + cost tooltip), ten named
      slots, zstd-packed slots (~5% of raw size), the Launch button, and
      the cross-session GL journal + switch-state + mid-clip-video fixes
      all landed and released together. **2026-08-08 night: THE WINDOWED
      FLOW WORKS END TO END, David watching: "it looks like from my
      point of view that the save / load state feature works 🙂 audio
      and video and everything."**
      **★★ REVERTED, THEN RE-LANDED 2026-08-09 — the app-launch flow in (1)
      below was PULLED from main in v0.120.1** (v0.120.0 shipped a startup
      freeze; the GUI went back to v0.119.7, so the Emulate-tab
      checkpointable launch, `kill_cmd()` and the cold-WSL thaw were all off
      main while this entry still said "live-verified"; the playfield
      Save/Load buttons stayed but reported "not checkpointable"). The
      freeze was then root-caused ELSEWHERE — v0.120.2 log-pane line COUNT,
      v0.120.3 NUL-flood line LENGTH — so the revert's reason was gone, and
      David asked for it back: "we don't have the app freeze issue anymore.
      let's turn it back on for me to try it out." **Re-landed on item/13 by
      reverting both reverts** (44a133e GUI, 74d9339 README) and merging
      against v0.120.2-6. Two conflict resolutions worth recording: BOTH
      attribute blocks kept (`_poll_busy` AND `_setup_ticks`/
      `_setup_said_boot` — the post-revert async poll and the re-landed
      cold-WSL machinery coexist), and `_restart_wsl` keeps v0.120.5's
      `pre_kill` structure but calls **`kill_cmd()`** — v0.120.5 was written
      on the reverted file, so its pre-kill was the user-level killgame that
      a ROOT guest ignores. 251 tests green in the worktree, including
      `test_log_pane_freeze` + `test_emulate_poll_storm` (the freeze fixes'
      own regressions — proof the merge kept them) and the re-added
      `test_tab_switch_disk_freeze`. Merged to main (`bc96678`). **Release
      HELD, deliberately: David validates from main FIRST** — his 2026-08-09
      rule, now written into `/next`'s SKILL.md ("Releasing"): a pass never
      releases without his explicit yes, and trying the build IS the
      validation, so it comes before the release, not from it.
      **★★★ AND HIS FIRST VALIDATION TRY REPRODUCED HIS CRASH (2026-08-09
      19:10) — the third core was decisive exactly as this item predicted,
      and the fault is now located AT THE INSTRUCTION.** Save during the
      big ch1 clip, load, padglhost SIGSEGV ~1 s after the restore's
      log-replay burst; teardown clean, alive 0. The core
      (`wsl-crash-1786317041-…padglhost-11.dmp`): **identical signature**
      (memcpy src=0x8 len=0x58 inside libgallium, return address =
      `main+6507`, the instruction after `call dispatch` in the padgl ring
      loop) and **NO "ring counters rewound" line — the guard never fired,
      which kills the stale-counters-parse theory outright.**
      **THE MECHANISM, read from `glbridge.c` and consistent with every
      observed fact:** `emit()` writes its payload at an offset `reserve()`
      captured from the head, but publishes with `hdr->head += need` — a
      load-add-store of the LIVE shared head. A leave-running save can
      freeze the guest INSIDE emit() (most likely precisely when a busy
      scene emits ~30 commands/frame — the condition all three of David's
      crashes share and the five calm surviving loads lacked); the
      not-yet-killed guest then advances head for the 10-20 s David keeps
      playing, and the restored guest completes its write at the SAVE-time
      offset while `+=` publishes `need` bytes at the LIVE head. The host
      parses lap-old ring bytes as a command — garbage data pointer, an
      88-byte memcpy from near NULL — and head only ever moved forward, so
      the guard stays silent. Race odds scale with GL traffic, which is why
      only David's busy-scene loads lost it.
      **FIX SHIPPED (this commit): `resv_base` in glbridge.c.** reserve()
      captures the head it reserved at; emit() publishes
      `hdr->head = resv_base + need` — ABSOLUTE, not `+=`. Identical
      semantics in normal single-producer operation; a mid-emit restore now
      steps head BACKWARD to the guest's true position, which is exactly
      the state padglhost's rewound-counters guard resyncs on: one command
      dropped, renderer lives. Built into the shared rootfs
      (`buildbridge.sh --guest`, encoder 18832 bytes) — **both checkouts
      share that build, so main had to carry this commit before any retry
      from main, or ensurebuild would hash-mismatch and rebuild the OLD
      encoder back in.**
      **Verification left: David's next save/load under a busy clip.** A
      `ring counters rewound` line in padglhost.log is now the EXPECTED
      trace of a mid-emit restore, not a fault; a fourth identical core
      would falsify this mechanism too. Crash logs preserved:
      `~/crashlogs/{padglhost,gameout,padvid}_relandcrash_1910.log`.
      **★★★ THE SCOPE VERDICT, DAVID 2026-08-09 evening, three messages
      quoted so the next pass builds the right thing:** *"i need you to
      test e2e the flow i'm doing... it cannot crash"*; *"you need to
      check that the scene and game video renders look correct too...
      missing data"*; *"we shouldn't have cross-session issues at all.
      that's the whole point of save states. most of them will be cross
      session for users to gauge how specific modes or events look with
      alternate assets."* Cross-session load is the PRIMARY case, the
      oracle is the PICTURE, and the asset-swap loop must be quick.
      **LANDED AND VALIDATED THE SAME NIGHT (fixed renderer, three e2e
      runs, all inputs by script through the same spawns the app uses):**
      • **The crash class is DEAD in both shapes.** The DELBUF graveyard
      plus a DRAW GUARD: per-VAO tracking of enabled-vs-buffer-backed
      attribs + the element binding; a draw that would hand Mesa a client
      pointer is SKIPPED and counted (`[padglhost] draw skipped`). Run A:
      fresh boot → cross-session load of a two-sessions-old save →
      renderer + guest alive 45+ s, zero segv, ~2100 poisoned draws/s
      absorbed. Normal play: ZERO skips through boot + attract, so the
      guard has no false positives. Plus the four same-session restores
      of the earlier gauntlet.
      • **DELTEX graveyard (256, textures are MB-scale) and BOTH
      graveyards now KEEP the guest-name mapping** — entries are
      (name, object), wrap-free scrubs the map only if the name was not
      re-genned — so a restored guest's stale re-binds resolve to live
      objects and a same-session load should render COMPLETE, textures
      included. Built and compiled; NOT yet pixel-verified (gap below).
      • **boot.id session identity.** watch.sh stamps `dump/boot.id`;
      savestate copies it into the slot THROUGH `/proc/PID/root` (trap
      recorded: padpath's `$ROOT` is wrong under root's HOME — the first
      version compared through it and mis-warned on a same-session
      load); restorestate reads the live guest's copy the same way and
      prints an honest cross-session NOTE.
      **★★★ THE GL WORLD JOURNAL IS BUILT AND E2E-VALIDATED (this
      commit, 2026-08-09 night) — cross-session loads render FULLY.**
      padglhost shadows every state-defining wire command (jgl_note,
      content-compacted: BUFSUBDATA/TEXSUBIMAGE applied into shadow
      copies, latest uniform per (prog,slot)), serializes the world AS
      PADGL WIRE COMMANDS on a request file (savestate.sh touches
      dump/glstate.req AFTER the criu dump → glstate.bin → the slot; the
      post-dump order makes the journal a SUPERSET of the checkpoint —
      requested before it, freeze-window uploads would be missing from
      every restore of the slot, forever), and replays it through its
      own dispatch on load (restorestate.sh stages glreplay.bin + .req
      with the guest dead, BEFORE criu restore; two-phase ack: the
      renderer CLAIMS the req before the reset+replay, writes
      glreplay.ok after, so a timeout can tell never-looked from
      mid-replay). Replay = jgl_reset_world (delete every host object,
      maps, graveyards, dispatch shadows, journal itself) then dispatch
      of the file — which rebuilds name maps, draw-guard masks and
      min-filter shadows exactly as a live guest would, and repopulates
      the journal so a second-generation save carries the full world.
      TEXDIRECT pixels excluded; the last VIDSHM header IS journaled so
      a load shows the save-time video frame (the padvid rewind makes
      the offset resolve). Startup unlinks stale request files.
      **A 20-agent adversarial review before the rig run confirmed 16
      real defects in the first draft — all fixed, three of note:**
      (1) the ring-head preset I designed was WRONG — glbridge's
      reserve() re-reads hdr->head fresh per command, so a cleanly
      frozen guest adopts drained counters with zero loss and the
      preset bought nothing, while a guest frozen INSIDE emit()
      republishes its later head absolutely and the preset would have
      defeated the rewind resync (stale-parse hang/crash). DELETED; the
      drain loop also now rejects impossible headers (op>=MAX or
      len>ring) with a resync — converts any residual stale parse into
      the documented one-command-drop recovery. (2) replay order:
      MIN_FILTER is emitted BEFORE level uploads and dispatch's FORCED
      completeness params are journaled too (jgl_force_param), or a
      replay reconstructs different wrap modes than live (CLAMP vs the
      REPEAT a tiling texture relies on). (3) the journal file is the
      first UNTRUSTED producer dispatch ever had — per-record validation
      (jgl_rec_ok min-len table + subtraction-form count checks), 64-bit
      framing math, honest -1 on truncation (no ok-file → the script's
      honest NOTE).
      **E2E, three sessions, two slots, four loads, ZERO crashes, ZERO
      skipped draws (the pre-journal cross-session baseline was ~2100
      skips/s forever):** attract slot jtest (journal 54M, 38 tex/45
      buf/22 shaders/11 progs/3 vaos serialized in 47 ms; replayed 636
      commands in 85-92 ms, GL err 0) loaded same-session AND
      cross-session, picture complete both ways (98.3% non-black vs
      98.1% at save). In-game slot jgame (69M, second-generation save of
      a restored guest): same-session load G1-vs-G2 = 2.8% pixels
      differ (near-identical, score/mode progress exact: 2,335,990,
      BRIDGE 11/20, TANKS 1/10); cross-session load = the same complete
      game picture, video back at 30.0 NEW/s / perfect 2-swap cadence /
      0 holds, game responds to switches. A fresh GAME was also started
      and played ON a cross-session-restored guest.
      **THE PICTURE ORACLE EXISTS: dump/glshot.req → padglhost
      glReadPixels of the guest screen FBO → dump/glshot.png** (write
      at frame boundary; the idle site defers mid-frame unless the
      guest has been quiet ~1 s). PrintWindow/RAIL never worked; this
      is the standing acceptance instrument, used for every claim
      above. Compare tool: scratchpad pngcmp.py pattern (stdlib PNG
      read, non-black % + mean diff).
      **★ THE 48V BANNER IS FIXED (2026-08-10, this commit): the padsw
      ring rewinds from the slot stash on every load,** the same
      in-place dd shape as the padvid rewind. The MECHANISM, read out
      of padsw.h rather than guessed: the shim merges held[] (keyboard)
      and scr_held[] (scripts) by LAST EDGE WINS PER ID against edge
      memory that lives in GUEST memory — which the checkpoint
      restores. watch.sh deletes dump/padsw at session start, so a
      fresh session's script region is ALL ZERO, while the save's
      session had plunge.py holding the coin door (33) and trough
      (66-72) there: the restored guest diffs its save-time memory
      against the fresh ring and sees a phantom RELEASE edge on every
      script-held switch — the door "opens" (the banner), trough balls
      "leave" (a ball-accounting time bomb nobody had tied to this),
      and tap_gen/guest_t0_ms mismatch the same way. The rewind
      restores the whole 4 KB block — both regions, all generations —
      to exactly what the restored guest's memory is consistent with,
      so NO edge fires. The sw_publish clobber question ANSWERED in
      code and then by test: it rewrites ONLY held[], rebuilt from the
      window-open latches (door closed, balls in trough — the values
      the save carried), and a session booted with PAD_SW_KEYSIM=1000
      republishing every second for 20 s after a cross-session load
      kept the banner gone. VALIDATED session D: fresh boot, NO reset
      run (the trigger condition), cross-session load of jgame → no
      banner, picture 2.8% from the save-time reference — the SAME
      number the same-session pair scores, so cross-session load now
      EQUALS same-session load on the picture oracle; video 28.5
      NEW/s; switches respond; a same-session re-load through the
      rewind path scored 2.6% with zero skips (no regression); zero
      draw skips, zero crashes; teardown to alive TOTAL 0.
      **★ SLOTS ARE PACKED NOW (2026-08-10, this commit): a save costs
      ~5% of what it did.** David asked "any way to compact or reduce
      the size"; measured first on the real jgame slot: 1.23 GB raw ->
      64 MB at zstd -3 in 2 s (59% of guest RAM pages are zeros, the
      ring stashes are mostly stale bytes, the GL journal is texture
      pixels - everything crushes; decompress <1 s). savegame.sh now
      tars+zstds the slot AFTER the thaw (off the freeze window; the
      save feels identical; PAD_SAVE_NOPACK=1 skips; no zstd = raw with
      a loud note), keeping slot.meta PLAIN beside slot.tar.zst so
      slots.sh and loadgame list without unpacking. loadgame.sh unpacks
      a packed slot into a /var/tmp staging dir (mktemp; NOT /tmp -
      the tmpfs trap; ~1 s), points restorestate at the stage, and the
      EXIT trap removes it on every path; raw (old) slots pass through
      untouched. slots.sh grew `pack <slot>` for pre-packing-era slots.
      Slot names are path-guarded in loadgame too now. VALIDATED live:
      a fresh save packed itself to 36 MB; a staged load of it restored
      (journal replayed, guest alive, video 60 Hz cadence, 0 skips,
      staging cleaned); a pre-packed old slot loaded the same way; the
      saves dir went 4.0 GB -> 1.38 GB with only David's quicksave +
      wtest left raw (his call, the manager can delete or `slots.sh
      pack` them). Tooltip + help now say 50-150 MB per slot and that
      a save briefly needs ~1.5 GB free while it packs. Cross-slot
      dedup and criu incremental chains were CONSIDERED AND REJECTED:
      they make slots depend on each other (delete one, corrupt
      another) for savings that no longer matter at 64 MB a slot.
      **★ THE OPT-IN GUI SHIPPED (2026-08-10, this commit), David's
      spec verbatim: a toggle, a cost tooltip, 10 nameable slots, and
      a manager.** "Enable save states" lives on the Emulate tab,
      DEFAULT OFF, persisted with the project (anchor `emulate_savestates`,
      the exact rail emulate_card rides: quit-time anchor write, global
      settings fallback, project save/open, startup restore). The toggle
      picks the LAUNCH SHAPE: on = the checkpointable root/PAD_PIVOT
      boot; off = the plain user launch this tab always had, and
      watch.sh then starts the playfield WITHOUT its state controls
      (--savestates argv, defaulting on for any PAD_PIVOT boot so
      hand-run rig sessions keep their buttons). The tooltip (widgets'
      _Tooltip, side-placed per its own combobox rule) names the cost:
      0.7-1.5 GB per slot, a multi-second freeze per save, slots stay
      until deleted. The playfield's Save/Load buttons grew a 10-slot
      picker (slot1..slot10, labels shown, "(empty)" otherwise); Save
      opens a small name dialog and passes the label to savegame.sh,
      which stores it IN slot.meta so names travel with the slot. The
      tab's manager (works with the toggle OFF, deliberately - turning
      the feature off is when you reclaim disk) lists every slot with
      name/game/size/date via the new slots.sh (root; list|label|delete,
      name-whitelisted, only-real-slots guarded), with Rename/Delete/
      Refresh and a totals line against WSL free space. NO wsl spawn at
      tab build (the cold-VM freeze class): the list loads on demand.
      Labels are sanitised to a safe charset because wsl.exe expands $
      and backticks even in -e argv (the executor lesson). savegame.sh
      also rejects path-shaped slot names now - a GUI feeds the arg
      that reaches rm -rf. VALIDATED: 93 emulate tests + 75 app smokes
      green (new test: toggle-off = the ordinary launch); slots.sh
      list/label round-trip with spaced labels through the real wsl
      argv path; a pivot boot brought the playfield up WITH the picker
      (process alive through attract) and `savegame.sh slot1 "picker
      test save"` saved 705 MB with the label listed back. THIS ALSO
      DELIVERS ITEM 33's core ask (the list + the space visibility).
      **★ MID-CLIP VIDEO RESUME FIXED (2026-08-10, this commit): the
      save now dumps --leave-stopped and takes the ring stash + GL
      journal INSIDE the freeze, then SIGCONTs.** The stand-down was a
      counter deadlock born of stash timing: the old order stashed the
      rings BEFORE the dump, so the padvid counters trailed criu's
      freeze by its startup (~3-15 frames at 30 fps); the restored
      guest's stream thread — its `consumed` count on its own stack
      (gstvid.c:673), restored at the freeze value — waited for frames
      PAST the stashed write_idx while resume_serve (which starts at
      the stashed write_idx) waited for the guest to drain frames it
      had already consumed; 3 s later the host stood the channel down.
      Freeze-exact stashes end it: the resume starts at exactly the
      frame the guest wants next. VALIDATED both shapes: save mid-clip
      in attract → same-session load AND cross-session load each show
      "RESUME mid-clip at frame 57 of 240 → skipped in ~75 ms →
      resume: EOS after 240 frames" — the guest consumed the clip's
      remaining 183 frames straight through, the game's own loop
      re-requested, first frame consumed in ~40 ms, 29.9 NEW/s at
      perfect 2-swap cadence, zero stand-downs, zero skips. SIGCONT on
      the pidns init thaws the tree cleanly (verified /proc state +
      resumed fps/video within seconds; a failed dump CONTs on its
      error path so it can never leave the game frozen). Bonus
      exactness: the GL journal and padsw stash now describe the
      checkpointed instant precisely (the old superset/trailing drift
      documented in earlier passes is gone). The honest cost, in the
      script header: the game is visibly frozen and audio underruns
      for the stash + journal beat (~2-4 s) on top of the dump's own
      freeze — a save was never free; it is now exact. PAD_SAVE_STOP=1
      now ends the guest via SIGKILL after the stash (same outcome as
      the old criu-default kill).
      **THE DESIGN LIMIT the asset-swap question exposes, answered
      2026-08-09 night:** PAD's own writes are SIZE-NEUTRAL, so a rebuilt
      card does not shift file offsets and a restored guest's open fds
      stay coherent — save → swap assets → load is SOUND for STREAMED
      assets: **videos** (padvidhost re-reads the card per clip, so the
      saved mode plays the NEW clips — the exact want) and on-demand
      audio. But **scene ART built before the save is BAKED into guest
      memory** — a loaded state shows the OLD art until the game rebuilds
      that scene, and the journal cannot change that (it replays
      save-time pixels by design). For image comparison the honest tools
      are the scene-texture previews or a fresh boot; save states cover
      the video/audio half. Also in the loop: a rebuilt card re-copies
      the 7.3 GB cache — item 34 is part of "quick to gauge".
      **Rig note:** the last teardown left ONE leftover alive.sh counts —
      a zombie `game` held by a WSL interop relay (the v0.120.5 class);
      only `wsl --shutdown` clears it (David's call), a new run is
      unaffected, TOTAL reads 1 until then.
      **★★★ AND IT WAS FALSIFIED THE SAME EVENING — David's retry crashed
      WITH the ring fix live (verified: the deployed lib is byte-identical
      to the fixed build for all mapped bytes), and the REAL mechanism is
      now PROVEN by prediction → reproduction → fix → survival:**
      **THE CRASH IS DELETED VERTEX BUFFERS, NOT THE RING.** The 19:24 core
      gave `dispatch(op=43 PADGL_DRAWARRAYS, len=12)` with Mesa memcpy'ing
      88 bytes from address 0x8. glDeleteBuffers on a buffer referenced by
      the bound VAO ZEROES that attachment, and the attribute's recorded
      byte OFFSET (8) silently becomes a CLIENT pointer. Leave-running
      save → the pre-kill guest crosses a scene TEARDOWN (ball drain, mode
      end) and deletes the scene's VBOs → load → the restored guest draws
      its save-time scene → Mesa reads client address 8 → padglhost SIGSEGV
      ~1 s after the load. Explains every fact: all four cores (David's
      88 B = 11 verts × 8; my repro's 760 B = 95 × 8, same libgallium
      frame), the busy-scene bias, the calm-load survivals, the silent
      resync guard.
      **REPRODUCED ON DEMAND (first time ever off David's machine):**
      start game → play → save → POKE 58 (outlane drain, forcing the
      ball-end scene teardown) → load → renderer dead, same core. This is
      the item's repro recipe now.
      **THE FIX, live-validated: PADGL_DELBUF defers.** padglhost parks
      deleted host buffer objects in a 4096-entry FIFO graveyard instead
      of freeing them — the VAO attachment and its DATA stay alive, so a
      post-restore draw is CORRECT, not just non-fatal (~KB per VBO, few
      MB worst case). glbridge's resv_base absolute-publish stays too —
      real window, just not this crash.
      **VALIDATED, one session, fixed renderer: FOUR restores survived** —
      (A) the exact crash recipe save→drain→load, (B) a second-generation
      save of a restored guest → drain → load, (C) save mid-ball →
      targets+drain → load → IMMEDIATE second load. Renderer 60 fps /
      30 NEW/s after every restore, ZERO fatal signals in its log,
      teardown to alive 0 (card umount needed root: plain
      `umount <cardmnt>`; `cardmount.sh --umount` wants the image arg).
      **Two rig-discipline lessons paid for tonight:** my buildbridge ran
      while David's own retry run was live (his crash report arrived
      mid-turn; he retried while I was still building) and the install
      clobbered the mapped lib — killed his run-1 guest at 19:23:31 and
      left the lib tail-truncated (18804 of 18832 bytes; section headers
      only, runtime-harmless, which is why run-2 played fine). alive.sh
      goes IMMEDIATELY before any build, not at turn start. And
      `wsl -u root` + `Select-Object` PS quoting ate `$?`/`$()` twice —
      bash probes go in script files.
      **NOT crash-related, seen once tonight: `[padvid] ch0 resume: the
      guest has not consumed for 3 s - standing the channel down` after a
      drain-load** — the shipped stand-down doing its job; fresh serves
      followed. The guest vid_thread question from the earlier Resume
      stands.
      **No live run. The windowed session's 25-min backstop fired and
      teardown was CONFIRMED: alive.sh printed TOTAL 0 after it, including
      the restored guest (a pidns init — SIGKILL teardown held) and the
      resume-mode padvidhost (the pattern kill caught it, as designed).**
      **★★★ WINDOWED SAVE/LOAD VERIFIED LIVE 2026-08-08 night, David's eyes
      plus the instrument:** save during live play at **86.4% non-black** →
      20 s more play → `loadgame.sh` → **86.1% non-black**, renderer 59.9 fps
      with video at 29 NEW/s, guest delta 60 fps. The previously-uncaptured
      windowed `Restoring FAILED` did NOT reproduce — the ring stash from
      `bd79b8e` had already fixed it — and restorestate now prints the raw
      tail of restore.log on any failure so the next one cannot go uncaptured.
      **THE VIDEO REATTACH IS SHIPPED, and it is a RESUME, not just a
      restart** (this pass's commit): a bare restart cannot work because
      padvidhost's startup acks every pending gen and the restored guest,
      seeing gen move under its stream thread, exits WITHOUT posting EOS
      (`gstvid.c:759` TAKEN OVER path) — background frozen forever, which was
      David's "text but no background". So `restorestate.sh` stops the video
      host, **rewinds dump/padvid to the slot's stash** (the one ring where
      "newer" belongs to the dead guest), restores the guest, and restarts
      padvidhost with **`PAD_VID_RESUME=1`**: each channel the guest thinks is
      mid-clip gets its serve CONTINUED at the saved write_idx (measured live:
      `RESUME mid-clip at frame 18 of 240`, skip 56 ms, superseded at frame
      199 by the game's own next request — normal attract from there).
      Requests in flight at the save are deliberately NOT pre-acked so
      chan_loop serves them fresh. Known tolerated race: the stash is taken
      moments before the freeze, so indexes can trail by a few frames; the
      ring math self-heals (comment in resume_serve).
      **AUDIO REATTACHES BY ITSELF — nothing to build.** playaudio.sh holds
      its own writer on the fifo (`sleep infinity >`), so the relay and the
      Windows player ride through the guest swap, and criu re-opens the
      guest's fifo fd by path onto the same live fifo. David heard it.
      **The nodebus wrinkle is understood and is a non-problem** (comment in
      restorestate.sh): run_game's nodebus EOF-exits the moment the guest is
      killed, so a windowed load always starts a fresh one for the tty
      external; it dies again when the restored guest reopens its tty, and
      none of it matters because nodebus only RECORDS — all 1520 ExchangeData
      timeouts in the post-load log predate the save, zero new after restore.
      **Also fixed: the video-host user detection** — `pgrep | head -1`
      matched the root runuser wrapper, so the first restart ran as root and
      logged to /root/padvid.log; it now matches the python process and
      restarts as the desktop user (fix committed untested-live; the mechanism
      is identical bar the uid).
      **Last pass's "4.1% vs 42.7% non-black" mystery is moot** — this run
      sampled 86% on both sides of the load; the 4.1% was a dark scene at the
      sample moment.
      **★★ GUI CONTROLS SHIPPED SAME NIGHT — David: "i'd like to have gui
      controls to set and load a save state." Surface asked and answered: the
      virtual playfield,** over the game window's legend and the Emulate tab.
      `Save state` / `Load state` buttons bottom-LEFT of the artwork view
      (state controls deliberately apart from the plunger cluster — a
      misclicked Load yanks the game back), spawning `wsl.exe -u root -e bash
      …/savegame.sh|loadgame.sh quicksave` off the Tk thread with both
      buttons disabled while one runs and the result on the status bar
      (a tick-proof override; tick rewrites the bar every frame). NOT on
      SwitchDriver's queue — a flipper release must not wait behind a 10 s
      restore. **The SCHEMATIC view has the same pair, top-right of its bar**
      (David asked; verified rendering on elvira3, a real no-artwork title) —
      both views share one StateOps mixin, and the wrappers know nothing
      about drawings, so any title that gets a playfield window gets working
      save/load controls. A title that gets NO window at all is item 27's
      silent skip; when 27(a) lands, the buttons ride in with the schematic.
      **Verifying the buttons' exact spawn found and fixed THREE real faults,
      all live-verified in one session (save → load → repeat load, video at
      29.9-30.5 NEW/s after each, host as david):**
      • **the restarted video host died with the wsl session** — runuser
      WAITS and FORWARDS signals, so when loadgame's wsl.exe ended, SIGHUP
      reached the fresh host ("Hangup" in padvid.log; window frozen at
      0.0 NEW/s while sampling 86% non-black — the held frame fooled the
      content metric, the rate instrument caught it). Fix: background the
      host inside a `bash -c '… &'` so runuser returns before the teardown.
      • **a second load of one slot always failed** — criu opens its pidfile
      O_EXCL and the stale `restored.pid` from the last load was still in
      the slot ("Can't write pidfile: File exists"); every earlier load had
      a fresh slot because savegame rm -rf's it. restorestate clears it.
      And the failure was expensive: the guest was already killed, so
      watch.sh tore the whole session down (leaked the audio pair;
      killgame.sh reaped them, alive 0 confirmed).
      • **the restart gate was too narrow** — it keyed on a running video
      host, so a load after a failed restart found a renderer with no host
      and left it frozen. The gate is now "is padglhost up" (the definition
      of windowed), with the helper user taken from the renderer when no
      host exists.
      **★★ SAVE→LOAD NOW CHAINS INDEFINITELY — the dead-tty bug, David's
      "load state failed" (2026-08-09 09:07), is fixed and verified over
      THREE chained cycles on one card session.** His slot recorded
      `tty 49 … /dev/pts/26 (deleted)`: a SECOND-generation save (a save of
      an already-restored guest) taken while the guest's node-bus tty was
      DEAD — nodebus EOF-exited whenever its slave count dipped, so every
      load left the restored guest on a masterless, deleted pty; criu dumps
      a dead tty without complaint and dies restoring it ("tty: Corrupted
      master peer"). THE FIX, three parts, all live-verified: **nodebus.py
      HOLDS its pty for the session's life** (EIO/EOF → sleep-and-continue,
      never exit; proven in isolation with a close/reopen and live across
      loads 2 and 3 printing "reusing the running node bus pty" — the reuse
      branch's first firings ever); **restorestate's nodebus restart is
      setsid'd HUP-proof** like the video host's (a plain background child
      died with loadgame's wsl session); **savestate REFUSES to create an
      unloadable save** (a "(deleted)" tty target aborts with the reason)
      and **restorestate pre-flights the slot BEFORE killing the guest**
      (dead-tty and gone-card-mount slots are refused while the game is
      still running — a failed restore after the kill costs the whole
      session, paid twice already). After cycle 3: 60 fps, 30.0 NEW/s,
      alive 0 (the card mount needs `cardmount.sh --umount` with the
      desktop HOME after a killgame teardown — watch.sh's own backstop
      teardown unmounts it itself).
      **★ AND THE LAST CRASH: the ring rewind was TRUNCATING a file the
      RENDERER had mmapped.** David's next load (09:23) killed padglhost —
      "Segmentation fault (core dumped)" as the last line of its log, mid
      "video upload from ch1 slot0" — because `cp -f` truncates the 95 MB
      padvid ring to zero before rewriting it, and a mapped page past EOF
      is a fatal signal. A RACE: three verification loads won it, David's
      load (big clip actively on screen = ring pages touched at 30/s) lost
      it. Fix: `dd conv=notrunc` rewinds the ring IN PLACE, so the mapping
      never sees a shrunken file; a torn byte for one tick is tolerated,
      a lost page is not. Verified: two more save→load cycles with video
      actively serving, renderer alive with zero fatal signals in its log,
      30.0 NEW/s after each, nodebus reused on cycle 2, alive 0 after
      teardown.
      **★★ 2026-08-09 AFTERNOON — THE RENDERER CRASH DID NOT RECUR, and the
      remaining video fault is now located EXACTLY.** Two loads through the
      new `savetest.cmd` launcher: guest restored and rendering both times,
      **padglhost alive with ZERO fatal signals in its log** (the resync
      guard is in the rebuilt binary), teardown clean. So the crash David hit
      three times is either fixed by the guard or still unprovoked here —
      his next load is the tiebreak, and the guard logs a line if it fires.
      **WHAT IS STILL BROKEN, and it is NOT the host: after a load the
      GUEST'S OWN VIDEO STREAM THREAD DOES NOT COME BACK.** The ring says it
      outright — `write_idx 129, read_idx 126, playing 1, eos 0`: a gap of
      exactly SLOTS-1, i.e. the host filled the ring and the guest never took
      another frame. The guest's MAIN loop is fine (it keeps requesting
      clips — fresh serves at 38 s, 46 s, 54 s) and its GL drawing is fine
      (51.8 fps eglshim, renderer 59.6 fps); only the thread that drains the
      video ring and hands frames to the game is gone, so `vid 0.0 NEW/s`
      forever. That is why "restart the video host" was never going to be
      enough — every earlier theory was about the HOST side of a ring whose
      GUEST side is what died.
      **Shipped with that finding: the resumed serve now STANDS THE CHANNEL
      DOWN** after `RESUME_STALL_S` (3 s) of a guest that is not draining,
      instead of holding a full ring with `playing=1` forever and wedging the
      channel for the rest of the session. Verified live: the stand-down line
      printed at 3.12 s and fresh serves resumed immediately after it.
      **Resume for the next pass:** find out why the guest's `vid_thread`
      does not survive the restore — criu restores its threads (19-20 of
      them, counted), so the question is whether the thread is restored but
      parked in a syscall it cannot come back from, or exited during the
      dump. `gstvid.c`'s stream loop is the code; the ring counters above are
      the instrument, and they are decisive in one read.
      **★ OPEN — THE ONE FAULT STILL ONLY DAVID CAN REPRODUCE: his loads
      kill padglhost with SIGSEGV; five of my loads across three shapes
      (calm attract, ch1 big-clip mid-flight, a STARTED GAME with a plunged
      ball) survive with zero divergence.** BOTH his crashes are CAPTURED —
      `C:\Users\david\AppData\Local\Temp\wsl-crashes\wsl-crash-*padglhost-11.dmp`
      — and the backtrace is identical: **Mesa (libgallium) memcpy from
      SOURCE ADDRESS 0x8, length 0x58, called from padglhost main()** — an
      88-byte copy from a near-NULL pointer, i.e. a dispatched GL command
      carrying a garbage data reference, NOT a pixel upload (frame = 1.5 MB).
      Last logged act both times: "video upload 1360x768 from ch1 slot0
      (ch1 serving, write_idx=4)". **Defensive guard SHIPPED and rebuilt
      into padglhost:** head < tail (or a gap wider than the ring) is a
      RESTORED GUEST, not data — resync tail := head and log "ring counters
      rewound" instead of parsing stale bytes. The guard never fired in my
      five loads, so the guest shim evidently reads the shared head fresh
      (no divergence on this machine) and the true trigger on David's box
      is still unidentified. **The next crash is decisive either way: the
      new core + presence/absence of the resync line in padglhost.log
      splits the hypothesis space in half.**
      **Two instrument traps from this pass, recorded so nobody repays
      them:** `kill -0` as the wrong user reads EPERM as "dead" (a healthy
      root nodebus was reported DIED for 30 minutes); and PowerShell's
      `Select-Object -First N` CANCELS the upstream pipeline — it killed
      wsl.exe mid-loadgame, which killed a restore mid-flight and tore a
      session down. Use -Last or capture to a variable.
      **Residual curiosity, not blocking: the BOOT-time nodebus still died
      during the first load of its session** (cause unfound; its log is
      clobbered by each successor — `open(LOG_FILE, "w")`). The steady
      state self-heals: every load leaves a setsid'd holder the next load
      reuses, so only the first load of a session pays the START branch.
      **A FOURTH, found by alive.sh across both sessions' teardowns:
      watch.sh had NO kill pattern for `padrelay.py`** — in a PAD_PIVOT
      session the runuser wrapping breaks the AUDPG group kill that catches
      it in ordinary runs, so the relay plus the Windows padplay leaked
      identically twice (2/2 pivot load-sessions; ordinary runs get it via
      group ancestry). One pattern kill added beside playaudio's; killing
      the relay closes the socket and takes the Windows player with it.
      **CONFIRMED 2026-08-09: the first pivot teardown carrying the fix
      (David's app-launched card session, two loads in it) came down to
      alive.sh TOTAL 0, audio player included.**
      **★★★ THE REAL GAME SAVES AND RESTORES, headless, closed loop, twice
      (alive.sh 0 after each, the ~509 MB dumps reclaimed).** `savetest_real.sh`
      (committed): boot godzilla_pro under `PAD_PIVOT=1` → `savestate.sh`
      (41 images, 509 MB) → `restorestate.sh` → **eglshim frames RESUME past
      the frozen point (1660 → 2080 → 2260), the restored guest still
      rendering** — a resume, not a restart.
      **THE DESIGN CHOICE THAT CLOSED IT — option (a): a checkpointable guest
      runs as ROOT with NO user namespace.** run_game.sh drops `unshare -r`
      when euid==0 (real root already has CAP_SYS_ADMIN/CAP_SYS_CHROOT). That
      deletes the whole userns failure class at once — the setgroups BUG, the
      tty-owner EPERM, the mount-engine inversion all came from david's
      unprivileged 1000→0 userns forcing setgroups off, and criu could not
      restore into it. A root guest has no userns, so restore is the simple
      case. It is also how the game runs on the real Spike machine.
      **✓ THE REAL GAME BOOTS AND RUNS UNDER PAD_PIVOT — 55.8 fps, node bus
      live (`[nbcmd]`), 19 threads.** pivot_root + explicit qemu vs binfmt was
      the biggest unknown and it works.
      **✓ comm STAYS "game" — a fix this exposed.** Explicit qemu made comm
      `qemu-arm-static`, so `pgrep -x game` (the rig's ONE guest identifier)
      found nothing. Fixed: qemu is copied to `/.padqemu/game` and exec'd by
      that path, so the kernel sets comm=game. Without it the boot ran fine but
      every count read 0.
      **✓ savestate.sh auto-discovers all 12 device externals + the held tty
      from the live mountinfo; the guest holds NO sockets** (confirmed on the
      real fd list — every fd is a device bind, the pty, or a rootfs file).
      **The recipe, now the DEFAULT in the scripts** (three knobs the earlier
      userns dead-ends forced, each keeping the restore moving):
      • **mount-v2** is the restore engine (`PAD_RESTORE_COMPAT=1` forces the
      old one) — a no-userns guest BUG's the compat engine on `pivot_root`;
      • **`PAD_SAVE_STOP=1`** stops the guest at dump so the log fd stops
      growing (criu's fd-size check fails otherwise). A real save that must not
      pause play needs the log fd handled instead;
      • nodebus at restore runs as the guest's user (root here), so criu can
      set the restored pty's owner.
      **★★★ THE RIG NOW SAVES AND RESTORES ITS OWN GUEST, offline, end to end
      (2026-08-08).** `savetest.sh` (root, no real game, no GL/video/audio — so
      NOT a measurement run) boots a stub guest through the REAL
      `run_game.sh PAD_PIVOT=1`, then drives `savestate.sh` and
      `restorestate.sh`; the stub RESUMED its counter twice (67 → 82 → 87), not
      restarted. Three new tools + a gated run_game.sh change:
      **`run_game.sh` grew a `PAD_PIVOT=1` branch, fully gated (default path
      byte-for-byte unchanged — verified from the diff).** It pivot_roots
      instead of chroot, self-binds `$R` first, `setsid`s the guest into its
      own session (else criu: "session leader outside its pid namespace"),
      execs an explicit rootfs-local qemu instead of binfmt, closes the wsl.exe
      ptmx fds, and **reopens stdio onto `/dump/game.out` after the pivot**
      (the caller's log is on a host mount that leaves the namespace — criu
      then refuses fd 1). It copies a static busybox + qemu into the rootfs for
      the post-pivot umount and exec.
      **`savestate.sh`** reads the guest's ACTUAL `/proc/PID/mountinfo` and
      generates one `--external` per mount criu can't resolve — **classified by
      FSTYPE, not path** (the first bug the offline loop caught: `/dev/shm` is a
      tmpfs, not a device bind, and must NOT be external). devtmpfs → the host
      node, devpts → the pty, fuse → the card. It finds the held tty fd and
      writes `restore.env` (the one place that owns the mapping).
      **`restorestate.sh`** restarts nodebus.py for a fresh pty, replays
      `restore.env`'s externals (resolving `@PTY@`), and runs criu restore
      inside the stripped nsclean namespace with `--root --mntns-compat-mode`.
      **★★★ ALL SEVEN RUNGS PASS IN ONE RUN (2026-08-08): A ordinary, B
      qemu-user, C +threads, D the full unshare -r -m -p -f + pivot_root
      container, E executed FROM a fuse2fs card bound in from outside, F
      holding a pty slave whose MASTER a host process keeps — restored onto a
      NEW pty from a RESTARTED holder — and G a file-backed MAP_SHARED ring
      a host writer kept advancing straight through the checkpoint.**
      Every rung resumes its counter (container rungs 70 → 85 → 90, margin 60
      over a restart).
      **What F establishes (the node bus):** TWO externals, one per layer —
      the slave's bind mount (`--external mnt[/dev/ttymxc1]:ttybind`, without
      which the dump dies "doesn't have a proper root mount") AND the held fd
      (`--external tty[rdev:dev]`, hex st_rdev:st_dev). At restore the mnt
      external points at the NEW slave and `--inherit-fd fd[9]:tty[old:key]`
      hands criu an fd to it — the restart-the-helpers flow, working. The
      subject opens with **O_NOCTTY, deliberately**; whether the real game
      acquires ttymxc1 as controlling tty is an open question that would drag
      session semantics into the dump.
      **What G establishes (the rings):** not just that the mapping restores
      — that it reattaches to the LIVE page. The judge requires the restored
      subject's view to OVERTAKE the value the page held before the restore
      (81 → 100 read through the restored mapping while the writer never
      stopped); a stale copy restored from images fails that gate. **The restore RECIPE, each part measured as necessary
      on this WSL, is baked into `criuladder.sh` with the failure that forced
      it beside each line:**
      • **pivot_root, not chroot** — criu refuses a chroot'd task twice over
      (`No parent found for mountpoint` on a plain dir; `root task has another
      root than mntns` on a self-bound one). The task's root must BE the
      mntns root. **run_game.sh must switch to pivot_root** — which also lets
      one lazy umount drop all 39 inherited WSL mounts (four 9p, four
      overlay, iso9660, /init...) out of the checkpoint.
      • **binaries the container needs post-pivot must live IN the rootfs** —
      the subject is exec'd through the rootfs's own qemu copy, because via
      binfmt it would be the host's `arm-binfmt-P` (flags POF), whose text
      mapping criu cannot resolve once the host tree is gone. The real rig
      runs the game via that binfmt today and needs the same treatment. Ditto
      a STATIC busybox for the post-pivot umount (`busybox-static`; noble's
      busybox-initramfs is dynamic).
      • **device binds go external** — `--external mnt[/dev/null]:devnull` at
      dump, `--external mnt[devnull]:/dev/null` at restore; one pair per
      device bind, and the card is the same shape (`mnt[/card]:card` →
      `mnt[card]:<cardmnt>`), with cardmount.sh re-mounting BEFORE restore.
      • **`--mntns-compat-mode`** — criu 4.1's default mount-v2 engine
      BUG_ONs (mount.c:48 `service_mountpoint`) and segfaults its restorer on
      this namespace.
      • **`--root <rootfs>`** — the single flag that made restore possible at
      all: prepare_mnt_ns() SKIPS its cleaning phase when --root is given.
      Without it the restorer umounts a namespace copy from INSIDE the
      restored userns, where every copied mount is MNT_LOCKED — even a fresh
      proc of our own — and dies on EINVAL after EINVAL (/init, /dev/pts,
      /dev, /proc, in discovery order).
      • **restore runs inside `unshare -m` with everything stripped**
      (`nsclean.sh`: detach all but / and /proc, then /proc LAST — umount(1)
      reads /proc/self/mountinfo, and the first version detached /proc
      mid-loop so every later umount silently failed — then fresh proc, then
      re-bind the rootfs, keeping the card mount for the external).
      **★ A TEARDOWN TRAP, MEASURED, AND IT APPLIES TO THE RESTORED GAME: a
      container-restored process is PID 1 OF ITS PID NAMESPACE and silently
      IGNORES SIGTERM.** `pkill -f` reported success and killed nothing,
      three restored subjects piled up across ladder runs, and rung E then
      read rung D's leftover counter (168 vs its own frozen 70) and failed
      its "original still alive" check — the harness caught its own leak.
      SIGKILL from an ancestor namespace works; any teardown of a restored
      guest must -9 it. criu's `--pidfile` now gives the ladder a
      deterministic kill target.
      **★★ THE ITEM'S CENTRAL ASSUMPTION IS NOW TESTED RATHER THAN ASSUMED,
      AND IT HELD. Nobody had ever pointed criu at a qemu-user process; the
      whole design rested on it. It works.** `criuladder.sh` (root, no
      emulator run, ~90 s): rung A dumps and restores an ordinary x86-64
      process, rung B does the same to a static ARM binary under
      `qemu-arm-static` (13 images, 3.7 MB), and **rung C does it to a THREADED
      ARM binary** (16 images, 4.5 MB) — which matters because the real guest
      is multithreaded and qemu-user maps guest threads onto host threads.
      **All three resumed their own counter (frozen 60 → 75 → 80) rather than
      restarting**, by a margin of 50 over what a fresh start could have
      reached. Rung C writes the **minimum** of its three worker counters, not
      the sum, so the file only advances if EVERY thread came back — a sum
      would have passed a restore that quietly lost one.
      **The harness passes a LABELLED NEGATIVE CONTROL that runs first and
      aborts the script if it fails:** a deliberate restart is scored FAIL
      (fresh reached 20 against a frozen 60). The first version of the
      discriminator was too weak and would have passed a restart — it froze at
      10 where a fresh process reaches ~15 in the observation window — so the
      subject now runs ~12 s before the dump. **A metric that cannot fail its
      own negative case has scored nothing.**
      **★ CRIU IS NOT PACKAGED FOR UBUNTU 24.04 — "needs installing" is not an
      apt install.** Zero candidate with universe enabled and lists fresh (the
      only criu-named package is a Go binding). **Built from source instead:
      v4.1 at `/var/tmp/criubuild/criu/criu/criu`**, and the deps it wants
      beyond the obvious are `uuid-dev`, `libaio-dev`, `python3-yaml`.
      **`criu check` says "Looks good"** on WSL2 6.6.87.2, and **every
      REQUIRED kernel row is present** — the handoff's five-row table was a
      sample, not the requirement list. `criu check --all` fails only on
      nftables locking and one dev:ino check.
      **★★ A REAL BLOCKER FOUND, WITH ITS FIX, AND IT APPLIES TO THE REAL
      GUEST: every process started through `wsl.exe` inherits TWO stray
      `/dev/ptmx` master fds on 7 and 10**, from WSL's own `login`/`bash` on
      pts/1 (sid 299, pgid 368). criu refuses such a process outright —
      `Found dangling tty with sid N pgid M (ptmx) on peer fd 7` — and
      **neither `setsid` nor `</dev/null` helps, because what it objects to is
      the inherited FD.** The guest is started by `watch.sh` through that same
      chain, so anything that checkpoints it must close these first. Fix is a
      close loop before exec; `criuladder.sh` carries it.
      **RULED OUT, so the design stops carrying it: `INET_DIAG_DESTROY` does
      NOT bite the guest-only plan.** That row killed a WHOLE-TREE checkpoint,
      which is already off the table. **`hwshim.c` opens no sockets at all**
      (grep: no `socket(`, no `connect(`, no `AF_INET`/`AF_UNIX`), so the
      guest holds no TCP to restore. The `padrelay.py` connection belongs to a
      HOST helper, which this design restarts rather than restores.
      **ESTABLISHED, and it makes the rings a non-problem:** they are
      file-backed `MAP_SHARED` mappings of ordinary files under `dump/`
      (`hwshim.c:4118` `PAD_SW_SHM`, `:5294` `PAD_LED_SHM`), and the led one
      even `close()`s the fd after mapping. criu re-opens such a mapping from
      the file, and **the content lives in the file, so the rings survive a
      checkpoint without being in it.**
      **STILL UNTESTED, and each is the next rung rather than an assumption:**
      the LD_PRELOADed shim and the game's real thread count, the subject
      running as david (the ladder runs as root, userns 0→0; the rig maps
      1000→0), a tty opened WITHOUT O_NOCTTY, and whether the game survives
      its node bus, audio sink and GL bridge being restarted underneath it.
      **★ CONTROLS SHIPPED: `savegame.sh` / `loadgame.sh` (slot-based), tested
      on the real game.** Save while PLAYING (leave-running, the game does not
      pause), keep playing, then load and it jumps BACK to the save: measured
      godzilla_pro saved at frame 1340, played on to 2260, `loadgame` reloaded
      to 1780 and climbed — a real quicksave/quickload. The rootfs and title
      come from the guest's own `/proc/PID/environ`, so the wrappers need no
      paths. **A leave-running save grows every append-only output** (game.out,
      audio.raw, audio.raw.center) past the size criu recorded; `restorestate.sh`
      now truncates each file criu names to the exact expected size and retries
      (bounded, only on that error) — this is what makes keep-playing saves
      restorable at all.
      **Committed:** `26f8f19`/`6f3242d`/`b8f99cc`/`4d255c1` (the ladder),
      `6b3882e` (run_game.sh PAD_PIVOT + save/restore, offline), `255f73e`
      (comm=game, watch.sh/alive.sh wiring, live boot+save), `f5fc6c0`
      (option (a): root guest, no userns; mount-v2 default; CLOSED LOOP), this
      commit (`savegame.sh`/`loadgame.sh` + the growing-output retry).
      **Resume — the windowed flow is DONE and David-accepted; what is left
      is making the APP's own flow reach it, none of it an unknown
      mechanism:**
      **(1) ★★ LIVE-VERIFIED ON DAVID'S OWN SESSION 2026-08-09 ~09:20: the
      app's Emulate tab launches the CHECKPOINTABLE boot and a card run
      saves, loads, and resumes its video.** David restarted the app, hit
      Start Emulator (his log: `wsl.exe -u root -e env HOME=/home/david
      PAD_PIVOT=1 … watch.sh 120`, "running the guest as root, helpers as
      david"), and the sequence ran on that session: save → load → renderer
      30.0 NEW/s, video host as david with PAD_VID_ROOT on the card, guest
      up. `watch_cmd()` in emulate_tab.py owns the launch (home probed via
      whoami+getent — NO `$` through wsl.exe's re-parse); `kill_cmd()` makes
      every killgame call root (a root guest ignores the user's pkill); a
      failed home probe degrades to the old user launch. 5 launch tests +
      72 app smokes green. savegame.sh also DETECTS the chroot case
      (`readlink /proc/PID/root` != "/") and puts the reason on the status
      bar; the playfield's status picker prefers a line that says something
      over a bare FAILED.
      **THE ONE FAULT THE LIVE RUN FOUND, fixed in place: fuse2fs registers
      as `fuse.ext4`, and savestate's `fuse|fuseblk` case never matched it**
      — no card external was recorded and criu died "doesn't have a proper
      root mount". Uncatchable earlier: no card save had ever run (passes
      five and six were extracted-tree). The case is `fuse*)` now.
      **(2) ★★ same verification: card-run save/load.** savestate
      records the card's actual HOST path (guest mountinfo major:minor
      matched against /proc/self/mountinfo, plus the bind's fs-root subdir)
      as a new `card` restore.env kind; restorestate verifies the path is
      STILL a live fuse mount (findmnt) — cardmount setsids fuse2fs so the
      mount survives the guest swap — keeps it out of nsclean's strip list
      (rung E's lesson), and errors legibly on a cold load. THREE traps
      found at the desk and fixed with it: **a root-made FUSE mount is
      invisible to david's helpers** (FUSE default denies all other users —
      cardmount now mounts with `allow_other` when root, and its
      unreadable-mount check remounts a plain user mount a root run
      inherits); **the resume video host lost PAD_VID_ROOT** (card clips
      live on the card, not the rootfs — restorestate now reads it from the
      dying host's environ and passes it through); **root runs left
      root-owned files in cardcache/** (give_back() chowns them to the HOME
      owner, same fix watch.sh's logs got). A PAD_GAME_DIR (folder-run)
      bind is still unclassified by savestate.
      **(3) DONE — the formal acceptance read, via the NATIVE oracle
      instead of `shot.py`.** `shot.py`'s PrintWindow never worked under
      WSLg RAIL (returned 0 on every attempt); the standing replacement
      is `dump/glshot.req` → padglhost's own `glReadPixels` → `glshot.png`,
      used for every claim in this item from the GL-journal pass onward.
      Read against it: save mid-ball (slot `jgame`), restore, and score
      + mode match EXACTLY (2,335,990, BRIDGE 11/20, TANKS 1/10) in both
      a same-session load and a cross-session load into a cold boot;
      play continued past the load (switches answered, video streamed
      at 28.5-30 NEW/s); `alive.sh` printed TOTAL 0 after every teardown.
      **(4) DONE — leave-running:** demonstrated on a live load:
      restorestate's truncate-retry fired on game.out, audio.raw and
      audio.raw.center and the restore proceeded; play was never paused at
      the save.
      — S2 for the same reason as
      item 16: play works, but every run pays for its absence.
      Freeze a live game and resume it later
      at the same ball, score and mode. David picked this reading explicitly
      over the two cheaper ones: it is NOT a boot skip (`autoattract.sh`
      already reaches attract in ~14.5 s) and NOT an NVRAM/card rollback.
      **`savevm`/`loadvm` DO NOT EXIST HERE** — the rig is qemu-**user**
      (`qemu-arm-static` under binfmt_misc, `run_game.sh:2`), and snapshots are
      a qemu-**system** + qcow2 feature. Do not spend a pass hunting a monitor.
      **CRIU is the only standing candidate. It is now BUILT — see the top of
      this item, which supersedes the "not installed" reading this paragraph
      used to carry.** A WHOLE-TREE checkpoint remains off the table, and for
      the reason given here rather than the one usually quoted: a live run
      holds a TCP connection from `padrelay.py` (`0.0.0.0:<port>`) to a
      **native Windows** `padplay.py` that is not in the checkpoint at all.
      `INET_DIAG_DESTROY` is a second reason for the same verdict and, per the
      ruled-out note above, does not touch the guest-only design.
      **STILL A GUESS, and the rungs above have not reached it:** checkpoint
      only the guest side (`arm-binfmt` + `game` + its shm rings) and RE-START
      every host-side helper on restore. Whether the game survives having its
      node bus, audio sink and GL bridge replaced underneath it is untested.
      The restore surface is everything `alive.sh` counts — 13 process shapes
      plus the `fuse2fs` card mount and the padled/padsw/padgl/padvid rings.
      Detail in the handoff under **REMAINING item 13**.
      **Acceptance: MET**, 2026-08-10 — save mid-ball, restore, and the
      ball number, score and running mode match; play continues past the
      load; `alive.sh` prints 0 after. Oracle is the native `glshot`
      picture dump (see (3) above), not `shot.py` — that tool's Windows
      capture never worked under WSLg RAIL, and the oracle it was meant
      to provide is what padglhost's own `glReadPixels` request now does.
      **Name collision, for anyone grepping the old history above:**
      `save_state` in `playfield.py` is the WINDOW POSITION save, unrelated
      to this feature.

- [x] **28. The rig is welded to one machine, and its per-title tables are
      checked in instead of derived from the card.** DONE 2026-08-07, David's
      call. **The derivation half shipped in `5d895c8` and was measured then;
      what was still open was the PORTABILITY half, and the CONTAINER work
      closed it rather than a `PAD_ROOT` run on this machine.**
      **The derivation, from `5d895c8` and unchanged since:** `padpath.py` /
      `padpath.sh` are the only files that know a path, `mktables.py` builds all
      five tables from the title, `rootfs.sh` + `parts.py` build the rootfs from
      any card with no root and no hard-coded offsets. It reproduced the
      hand-made tables exactly, which is the only thing that made deleting them
      safe: `device_xy.txt` **byte-identical** (66642 bytes), `switch_xy.txt`
      **41/41 positions identical**, and the window drew **132 markers at
      coordinates identical to HEAD's**, A/B'd through a git worktree.
      **The tables really are gone: `git ls-files tools/spike2_emu/games`
      returns NOTHING.** Every title's artwork, device table, LED map and switch
      layout is built from the card during the run.
      **THE PORTABILITY HALF WAS CLOSED BY THE CONTAINER, and it is a stronger
      proof than the acceptance asked for.** `docker/Dockerfile:82` sets
      **`PAD_ROOT=/pad/rootfs` and `HOME=/pad/home`** — not this machine's
      defaults, on a machine that is not this one, with `PAD_TABLES` following
      `PAD_ROOT` by the design's own rule. Item 30's measured run records the
      whole chain working there: card mounted, **tables built from the card**,
      playfield window open, guest at 57.1 fps. Shipped as **v0.110.0** (Linux
      native), **v0.111.0** (macOS in a container over VNC) and **v0.117.0**
      (macOS end to end).
      **★ THE ACCEPTANCE GREP AS WRITTEN FAILS, AND THE TEST WAS WRONG RATHER
      THAN THE CODE — worth keeping, because it is a trap any "remove the
      hard-coded X" item will hit.** `git grep -E 'home/david|Users/david|
      wsl\.localhost'` over the rig still returns **15 hits in 9 files** — and
      **every one is a comment, a docstring or README prose describing the fix
      itself** (`padpath.py:4` "THIS EXISTS BECAUSE THE RIG WAS WELDED TO ONE
      MACHINE", `playfield.py:175` naming the literal it replaced, and so on).
      Zero are executable. A fix whose own documentation must name the thing it
      removed can never pass a bare `grep -l`, so **the honest check is the same
      grep restricted to non-comment lines**, and that returns nothing.
      **NOT CLAIMED: that `PAD_ROOT`/`PAD_TABLES` have been pointed elsewhere
      under WSL on this machine.** They have not. The container is the evidence,
      and it exercises more of the surface than that run would have — a
      different rootfs, a different `HOME`, a different display path and a
      different renderer. **Item 30 stays open** and is the container's own
      fault (a run ending after ~60 s), not this item's.
      **A REAL BUG THIS ITEM'S OWN TESTING FOUND, kept because it is the kind
      that passes every self-check:** `devicexy.build()` ignored the title it
      was asked for and loaded whichever was ACTIVE, so `turtles_pro` came back
      with Godzilla's 575 records and **18 of TMNT's switch names collided with
      Godzilla's** well enough to place markers on a playfield TMNT does not
      have. Fixed, with a regression test.
      **Four titles ran from their cards with nothing committed** — Led Zeppelin
      LE, Elvira's HoH, Jaws LE and **John Wick LE, a title with nothing in the
      repository at all, which drew a full artwork playfield**: 503 device
      records, 63 inserts, 56 switches placed, live coils, 30 fps.
      **Two faults the runs caught:** a `pkill` line whose double quote was
      closed by a single one swallowed the rest of `watch.sh`'s teardown — **and
      `bash -n` cannot see it**, because a later quote rebalances the parse,
      which is why it shipped and leaked four playfield stubs; and Jaws's
      artwork was missed because `find_playfield_art` matched `*_playfield.png`
      while Jaws spells it `jaws_le_playfield_scaled.png`. The LE/Pro choice is
      made on WHOLE WORDS now — the old substring test picked that pair
      correctly only by accident, because "scaLEd" contains "le".
      **The 25 s switch-dump budget was wrong in the worst possible way:** it
      caught the dump on one pass of four titles and missed it on the next pass
      of two, which reads as a property of the title. The shim publishes the
      table about a MINUTE in, consistently. The build is two passes now —
      everything needing no run first, then a wait that BLOCKS only when there
      is nothing to draw meanwhile (`mktables.py --drawable`, `PAD_PF_WAIT` 120).
      **Follow-on: item 29**, the `?` switch names, was filed out of these runs
      and is still open.

- [x] **31. The playfield claims "30 fps" while the LEDs actually move 2.6
      times a second, in bursts and freezes.** DONE 2026-08-07, `a77eb56` (the
      fix and the instruments) + this commit (the run's numbers). Two runs,
      `alive.sh` 0 after both.
      **(a) The claim is fixed and verified live:** the bar now reads
      `LED 1.3 Hz (…writes, …dropped) … poll 30 fps` — the picture rate and the
      poll rate, each labelled, and when data outruns the picture it says so in
      place: screenshotted DURING the fault, `LED 0.3 Hz of 2.3 Hz data
      (941 writes, 3 dropped)  11 coils addressed  poll 30 fps`. Counted over a
      3 s sliding window, never smoothed. `PAD_PF_LOG` carries
      `LED/data/worst gap` per second, the gap a maximum not a mean.
      Validated offline by `ledratetest.py` (~20 s, no emulator): drives the
      real `Field` against a fake padled it paces itself — 5 Hz with a 2 s hole
      reads 4.0 Hz / gap 2.20 s, and the labelled NEGATIVE control (30 Hz of
      churn writing values already on screen) reads LED 0.0 Hz where the old
      bar said 30 fps.
      **(b) The fault is DIAGNOSED AND IT IS NOT THE RIG'S: the wire really is
      bursts and freezes.** The subtraction ran on both sides of the VM
      boundary over the same minute of the same run. ATTRACT: `ledrate.py`
      inside WSL (200 Hz sampler) read **1.97 Hz of LED frames, max gap
      4.59 s**; the window read **1.98 Hz data, worst gap 4.57 s** — identical,
      so the `\\wsl.localhost` crossing drops nothing and holds nothing stale.
      Steady-state attract picture: ~1.3 Hz typical with stretches to 6.5 s,
      and one 11.9 s stillness mid-attract with the poll pinned at 30.2 fps
      through all of it. GAMEPLAY (coin/start/plunge, FREE PLAY BALL 1
      screenshot-confirmed, idle ball): the DATA is steady — 4.18 Hz of frames,
      **no gap over 0.97 s** — but the picture moved 0.22 Hz because in-game
      writes mostly rewrite already-drawn values. So the loose end's split is
      now measured: in a game the lamp stream is continuous; the multi-second
      holes are attract's own drive.
      **What remains visually is item 1d's, not this item's:** the only lamp
      traffic the rig discards is the undecoded a2/b4/b5 slice (measured here:
      5 frames/60 s attract, 0 in the game minute; ~1.1/s in the recording's
      attract phase, every one coinciding with zero picture change). If a2 is
      the suspected range-fade, each dropped frame is a missing ANIMATION, so
      decoding it is the one further smoothness this window can gain.
      **Instrument notes for whoever reuses these:** `ledrate.py` runs inside
      WSL and polls at 200 Hz because a sampler at the rate it measures cannot
      tell a burst from a stream; the offline harness must pin `PAD_TABLES`
      before moving `PAD_ROOT` (or the window opens tableless and measures
      nothing) and must call `fine_timers()` like the real main (or Tk rounds
      to 15.6 ms and the loop reads 25 fps). Item 21 should build its trough
      markers on `mrg[]`, not this block — but its "the display updates
      2.6 times/s" worry is now answered: switch data is not the LED stream,
      and the LED stream itself is honest at every rate it actually has.
      Logs kept: `/var/tmp/pf31_attract.log`, `/var/tmp/pf31_game_kept.log`,
      `/var/tmp/ledrate31_attract.csv`, `/var/tmp/ledrate31_game.csv`.
      **SAME-DAY FOLLOW-UP off David's first look, `a955b10`:** (1) the
      two-rate bar's conditional `of N Hz data` field made the WINDOW RESIZE
      ITSELF to fit the text — fixed by always showing both rates and
      `width=1` on both status labels so text can never size the window;
      (2) the poll went 30 → 60 fps at his ask (the 3.4 ms read is a ~147 fps
      ceiling; 30 was only the written acceptance bar), with `GONE_POLLS`
      derived from the rate so the ~2 s close-with-the-run grace survived;
      (3) fixtures now TWEEN between states over `PAD_PF_FADE_MS` (200 ms
      default, 0 = snap) because the real LED boards render fades locally and
      the wire only carries steps — see item 1d for the true durations. The
      bar's LED Hz counts state changes, never tween frames, and
      `ledratetest.py` grew a FADE case that fails on a snap (12 distinct
      paints each way, lands exactly; CHURN still reads 0.0 Hz).

- [x] **24. Press-and-hold a switch on the virtual playfield.** DONE
      2026-08-06, `68a18c5`. **David, on the shipped build: "item 24 looks good
      to me"** — his hands were the acceptance oracle the item named, and the
      only thing three passes of measurement could not settle.
      **The diagnosis was right about the binding and WRONG ABOUT THE PATH, and
      fixing only what the item named would have left David's own worked example
      behaving exactly as before.** Pressing the middle of RIGHT SCOOP does not
      hit the switch marker — `_hit()` resolves it to the COIL drawn over it
      (measured: at canvas 447,642 the switch oval is not even in
      `find_overlapping`, because it is an unfilled outline) — and a coil click
      went to `coilact.py`, whose `RIGHT SCOOP` action was a hard-coded
      `PULSE_MS = 120` poke of switch 53. That pulse was the fault.
      **Fixed in two places, deliberately split:** `<ButtonPress-1>` /
      `<ButtonRelease-1>` on both canvases drive a hold, and `coilact.py` grew
      `hold_switch()` so a coil that FOLLOWS a switch (scoop, slingshots, pop,
      flippers, magnet) holds it while a coil that MOVES a ball (trough eject,
      auto plunger) stays a click — there is nothing to hold in a sequence.
      **Measured offline, then CONFIRMED LIVE against `mrg[]`, the array the
      GAME IS HANDED**, which is what the acceptance named. Live, one 4-minute
      run, `alive.sh` 0 after: press → mrg closed in **74.5 ms**, **231 of 231
      samples closed across a 2 s hold**, release → mrg open in **82.0 ms**;
      three quick clicks all reached mrg 78-96 ms wide; 20 fast actions strictly
      alternating, ending open. Before the fix the same test on the same switch
      read **182 of 198 samples OPEN**.
      **`SwitchDriver` is ONE serialised worker and that is the whole safety
      story.** Every action is a ~80 ms `wsl.exe` spawn, so a fast click queues
      the release while the press is still starting; on two threads the release
      can WIN and the switch latches closed with nothing left to open it. Plus
      `release_all()` on window close.
      **An 80 ms closure is safe because of item 17's `sw_owed[]` latch**, which
      owes every closure a scan and was measured 72/72 down to 10 ms. This item
      relied on that rather than re-proving it, and says so.
      **New instrument that needs NO run: `swholdtest.py`.** It builds the real
      `Field` and synthesises the button events on its canvas, so the hit test,
      the hold bookkeeping and the queue are all shipping code; `PAD_SW_FILE`
      points the helpers at a fake block. **Validated on a labelled example:**
      `--pulse` drives the pre-fix gesture and the test must FAIL, and does. It
      has since paid for itself as item 25's regression check.
      **Two instrument faults caught, both of which had produced a wrong
      reading:** the ORDER check polled for "switch is open" and passed in 3 ms
      over twenty pending actions — a metric satisfiable BEFORE the work starts,
      now it waits on the queue — and the harness passed its switch id as
      `sys.argv[1]`, which `playfield.py` reads as the GAME name.

- [x] **25. Move Start / Plunge / Reset balls next to the plunger, and drop the
      "click a switch or a coil" line.** DONE 2026-08-06, `bc7c3a2`. **No run
      spent.** The three buttons are `create_window` widgets on the canvas,
      right-aligned along its bottom edge under the shooter lane; the whole
      `bar` Frame and its label are gone.
      **Real `tk.Button` widgets, not canvas items,** as the item insisted: a
      window item IS in `find_overlapping` but is not in `self.info`, so
      `_hit()` skips it and the widget eats the click before the canvas binding
      runs. **The first reading of David's words was taken** — buttons ON the
      artwork, no window resize — so item 5 is untouched; the other reading (a
      strip to the RIGHT of the artwork) is still a small change if he wants it.
      **A ROW, NOT A STACK, and the markers decided it.** The lowest marker is
      RIGHT FLIPPER BUTTON at table y=656, leaving 54*scale px under it: three
      stacked buttons (~86 px) cover that marker on a 1080p screen, one row
      (~26 px) clears it at every scale including `PAD_PF_SCALE=1`.
      **RULED OUT WITH A NUMBER, so nobody re-does it: `pick_scale`'s chrome
      170 → 140.** Reclaiming the ~30 px the button row used works — the artwork
      goes 1270 → 1300 on 5120x1440 and the status bar still fits — but it moves
      every marker, and `_hit()` at a marker's own CENTRE resolves to whatever
      NEIGHBOUR overlaps there, because a switch oval is unfilled and a click in
      its middle never finds the switch itself. **20 of 51 switch and coil
      centres changed, one of them a real loss:** the POP BUMPER coil centre
      stopped resolving to a switch and started resolving to an insert, i.e. a
      click there would do nothing. 2.3% more artwork is not worth perturbing
      the hit test item 24 just stabilised. The reasoning is in `pick_scale`'s
      own docstring, where the next person to try it will read it.
      **THE INSTRUMENT IS A DIFF AGAINST THE PREVIOUS COMMIT, not a judgement of
      the new file, and that is the lesson worth keeping.** Scored on its own
      the hit test reads as 27-38 "failures" at every scale on code nobody
      touched — the unfilled-oval reason above. Run against
      `git show HEAD:...playfield.py` as a baseline it answers the only question
      that means anything: at 1.0 / 1.28 / 1.789 and at the default scale, every
      button is inside the canvas, **0 of 132 markers is covered, and the hit
      map is IDENTICAL at all 51 points.**
      **Also verified:** `swholdtest.py` (item 24's harness) ALL PASS — hold
      268/268 samples closed, three taps 71-74 ms, 10 fast clicks end open; each
      button `invoke()`d with `run_plunge` stubbed delivers start / plunge /
      reset in that order (a button that looks right and does nothing is exactly
      what a screenshot cannot see).
      **One instrument trap paid for:** `shotwin.py` opts into per-monitor DPI
      awareness because it grabs WSLg windows, and on this DPI-unaware Tk window
      it returned an 863x1994 bitmap with the picture in the top-left and 620
      rows of black under it. The in-process `snap()` pattern from
      `scripts/take_screenshots.py` is the one that fits, and gives 559x1321.

- [x] **11. Background video stutters every ~7 seconds.** DONE 2026-08-06,
      David live on the final build: **"the video stuttering and tearing all
      seems gone"** — his eyes were the acceptance oracle throughout, and the
      last two fixes landed off his own pasted logs with no run spent. The
      item opened as one ~7 s attract stutter and closed as SIX distinct
      mechanisms, each measured, fixed, and confirmed separately. The full
      pass-by-pass narrative — every ruled-out candidate with its numbers —
      is this file's own history through `248a35d`; what follows is the
      record that earns its keep.
      **(1) Re-arm storms.** The game's EOS reflex and state churn re-armed
      pipelines up to 93 times per clip, every prepare blocking its UI
      thread. Absorbed by predicate — third iteration right: the
      discriminator is SEEK RATE, not delivered-count, so a ball-change
      restart is honoured and a storm pays one re-arm (`cef2627`,
      `dba987d`).
      **(2) Cadence drift.** vid_thread slept a period after each frame's
      work, so error accumulated one slipped frame at a time. Absolute
      schedule, frame N at t_epoch + N*period (`a6d9ce1`); David live: "the
      stuttering on this city loop is gone".
      **(3) Transition cost, ~60 ms → ~2 ms, decomposed into four parts:**
      the first-sight ffprobe spawn (25-40 ms — replaced by a native MP4
      header parse, validated identical on all 658 clips, `76363db`);
      serve()'s deaf readinto through ffmpeg's cold start (select-gated at
      2 ms); synchronous corpse reaping (~30 ms — daemon-thread reap); and
      the first-frames head cache, 6 frames instant on any re-serve
      (`f08e814`).
      **(4) The blind serve.** serve() re-read req_gen after chan_loop had
      already acked; a request landing in that few-ms gap was never served
      and the game's UI thread sat out its full 3 s prepare timeout —
      David's "logs pause for a significant amount of time, then catch up",
      ~8 freezes of 3.3-3.9 s in one run, 3 loud `host did not answer`.
      serve() now trusts the gen chan_loop acked (`9a7c32b`).
      **(5) The ring-slot display race.** padglhost reads the on-screen
      frame straight out of the shared ring at ~60 Hz — the zero-copy
      design — and a re-serve reset the ring and rewrote the displayed slot;
      the head cache made that a microseconds-fast slam where ffmpeg's
      ~35 ms cold start used to shield the picture by accident: David's
      "severe tearing" at the L-ramp opto. Fixed by the SLOTS-1 throttle
      (one slot of distance between write head and display) plus the
      display guard on the previous request's on-screen slot (`9a7c32b`).
      **(6) The channel machinery underneath it all:** hwchan indirection —
      stream-to-channel is a permutation, two streams can never drive one
      channel (`d1a7b8d`) — and pre-arm adoption, 100% adoption, 0 wasted
      across three runs. **PAD_VID_PREARM stays OPT-IN:** with the probe
      free its edge is the 2-5 ms arm→prepare head start, within noise.
      **ACCEPTED RESIDUAL, named:** when the on-screen slot IS slot 0
      (~25% of transitions) frame 0 must overwrite it, so a single-frame
      seam can still flash there. Erasing it needs ring-phase continuation
      across serves (a guest change — vid_thread's `consumed` starts at 0
      by design) or the persistent seekable decoder. **The persistent
      decoder is NOT BUILT, and David's confirmation is the decision that
      it need not be.** Revive either only if the seam ever bothers a
      session.
      **The instrument ledger is the lesson worth keeping.** A 30-on-30
      screen capture is phase-ambiguous, and the grabber double-samples
      ~37% of frames — every uncorrected screen magnitude in the early
      passes measured the recorder, not the fault. The two trustworthy
      tools: `tickcensus.py` (swap-tick-gated, 50% repeat baseline — video
      is 30 fps on 60 Hz swaps, so "repeats are bad" calls a healthy
      pipeline half broken) and `dupcensus.py` (calibrated 0.0% on a
      pristine extract). eglshim cannot see a frozen texture, and the
      guest's own delivery log can read flawless while nothing is delivered
      (the in-place pre-arm proved it) — judge video with tickcensus,
      never the guest log.
      **What the passes paid for elsewhere:** item 23's churn-segv repro
      and its second and third shapes fell out of this item's runs, and
      runs are 4 minutes now (`watch.sh 4`, recipe, 2 min longplay).

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
