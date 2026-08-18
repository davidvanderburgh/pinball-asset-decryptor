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
- **The rig is a mutex, and the lock file is how sessions take turns.** David
  runs more than one PAD session at a time (2026-08-15). Worktrees isolate the
  code; nothing isolates `~/spike2root`, `~/padglhost`, the rings or the run
  logs — so before any build, run, `killgame.sh`, save-state op or mutation
  under the rootfs, TAKE `/home/david/.pad_rig_lock` (atomic `set -C` create,
  content = your item branch + what you are doing, mtime = the clock), and
  release it only when `alive.sh` reads 0 again. Held by someone else = the
  rig is theirs; stay at the desk. Full protocol: `~/.claude/skills/next/
  SKILL.md`, "The rig lock". A lock with `alive.sh` 0 that is under ~60 min
  old is a session between steps, not stale.
- **Item work commits on `item/<N>` in its own worktree, never straight to
  main.** Main is the release branch and only moves when a finished item is
  merged in — `/next` owns the mechanics (branch, sibling worktree dir, merge
  at close). No PRs, still: the merge is local and pushed.

## Queue

- [ ] **52. stranger_things: nodes 1, 8 and 9 — the three pinnodes — are
      the ONLY boards the game cannot find, and it wedges on LOCATING NODE
      BOARDS while its projector plays.** `S2 D3`
      *(Split out of item 51 at its close, 2026-08-15: 51's derived
      identities got ST's ws2812node and node4 boards FOUND — the wedge
      shrank from "no nodes at all" to exactly the pinnode trio — and the
      projector shows scene footage regardless, so the display side owes
      this nothing.)*
      **Observed (screenshot in the item-51 record):** main window
      `LOCATING NODE BOARDS / 1 8 9 / NODES NOT FOUND`; `[nbid]` shows all
      six boards claiming derived identities (pinnodes: part 0x00020023,
      variant 0x01, fw 1.19.0 — the same claim SHAPE star_wars accepts at
      1.29.0 and godzilla at 1.35.0). "NOT FOUND" is the game's ABSENT
      verdict, not a grading failure — so ST's binary either parses the fe
      reply differently for pinnode-class boards or validates a field the
      shim answers globally (hwid 0x0001 for every node is the obvious
      suspect).
      **The instrument that decides it exists already:** hwshim's `[nbcen]`
      per-command reply-length census — "fe asks an 11-byte payload and
      only on FAILURE retries with a 10-byte one (reply_len 12), so a
      nonzero count at 12 is a direct readout of the identity exchange
      failing" — plus `PAD_NB_HWID` to sweep board ids without a rebuild.
      **Acceptance:** stranger_things boots past LOCATING NODE BOARDS with
      no NOT FOUND overlay, stated with a screenshot; then say what its
      attract shows on BOTH displays.
      — S2: the title is unplayable past boot, but no other title is
      affected and the projector/display work is delivered; it costs runs
      on one title. D3: one run cycle with existing instruments
      (PAD_NB_DUMP census + PAD_NB_HWID sweep), fault reproduces on demand.
- [ ] **38. A run can strand its windows, and then EVERY later run is
      INVISIBLE — the game plays perfectly with no window, and every
      instrument in the rig says it is healthy.** `S2 D3` *(**20%, 2026-08-10:**
      the strand was reproduced on a second occasion — item 21a's run, torn
      down with `killgame.sh` — and the WINDOW half now has a cheap, verified
      cure that does not shut the VM. See (4).)*
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
      **★★ (4) THE WINDOW HALF HAS A MUCH CHEAPER CURE, established 2026-08-10
      on a live strand (David: "these windows are frozen open and i can't close
      them"). KILL msrdc.exe.** Both stranded windows were owned by ONE
      `msrdc.exe` — `zorder.py --all` named it, pid and all — which is WSLg's
      RDP client and not a Linux process at all. `Stop-Process` on it dropped
      both windows in about three seconds, WSLg restarted itself as a fresh
      msrdc pid on its own, **no Linux process died** (two idle `-bash`
      sessions survived) and `zorder.py` then printed `VERDICT: no emulator
      window found`. So `wsl --shutdown` is NOT required to unstick the
      windows; it is required only to reap the interop zombie, which is a
      different fault with a different cost. **Which means the cure this item
      should build is: detect (below), then offer the msrdc kill first and the
      VM shutdown only for the zombie.** Anything that shuts the whole VM to
      clear a window is charging a user their entire WSL session for a repaint.
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
      **★ NARROWED FOR FREE, 2026-08-10 during item 21b's pass, and it is NOT
      the wedge: that line comes from the LOGIN SHELL.** It printed on a bare
      `wsl -e bash -lc 'ls ~'` with no run up at all, no emulator, no stranded
      window — so something in the WSL profile emits it and any helper invoked
      through a LOGIN shell (`bash -lc`) wears it. That makes it a
      one-character fix in how alive.sh is invoked rather than a symptom of
      the strand, and it means the corrupted first row is reproducible on
      demand with no run at all. Do not spend a run on it.
      **★ AND A CHEAP WAY TO AVOID THE INTEROP ZOMBIE, same pass, one
      observation so treat it as a lead:** item 21a's run left the guest as a
      `Zl` zombie held by a WSL interop Relay, and its handoff blames
      `Start-Process wsl … watch.sh` from PowerShell for putting the relay in
      the parent chain. This pass started its run with
      `wsl -e setsid --fork bash -c "exec … watch.sh"` — setsid as the FIRST
      process, so the run is a session leader and not the relay's child — and
      after `killgame.sh` it printed `killed 19; still running: 0` with no
      zombie and no `wsl --shutdown`. Also worth knowing: backgrounding inside
      the shell (`… watch.sh & echo started`) does NOT survive `wsl -e`
      returning, which looks exactly like the run silently never starting.
      **Acceptance:** force the repro (a run on a title with no game ELF, then a
      normal run) and have the rig SAY the picture is missing rather than let it
      be discovered; then state whether the strand still happens once teardown
      is fixed, and on how many repeats.
      — S2: play itself is not broken and one command cures it, so it is not
      S1; what it costs is that the emulator can be silently unusable and every
      other item's runs are measured through it. Arguable as S1 for anyone who
      does not know the trick. D3: it needs a run, it reproduces on demand, and
      all three instruments already exist.

- [ ] **36b. Saving a state on star_wars killed the donor run ~10 s later.**
      `S1 D4` *(**Split on 2026-08-10**: the LOAD half is fixed, verified and
      merged as 36a. This is the save-side death, which is a different fault
      with a different instrument — item 23's exit-reason hook — and it is
      the only part still open.)*
      **★ DAVID, 2026-08-10 ~13:00: "i tried to save and load on star wars
      and it crashed."** The evidence, mined the same minute
      (`c:/tmp/item27/gzwatch_sw_savecrash.log`): **THE SAVE SUCCEEDED** —
      slot3 `star_wars_le "sw game play"` packed, 63 MB, stamped at the
      checkpoint freeze (every channel's `worst gap` ~900 ms at 13:00:08 is
      the criu dump). What David called the crash of "save and load" was two
      faults at once: the load half (now 36a, and slot3 has since been
      restored successfully) and **the GUEST EXITING BY ITSELF ~10 s after
      the dump resumed, CLEANLY** — gzwatch ends at a healthy 49.9 fps with
      no segv block, no signal, no exit path. That is item 23's first shape
      (the clean exit), with its strongest correlate yet: a leave-running
      criu dump 10 s earlier, on the title with four video channels and two
      EGL surfaces mid-clip-churn at the freeze.
      **★★ ONE COUNTER-OBSERVATION, 2026-08-10 ~18:40, and it is why this
      needs repeats rather than a theory: a star_wars save did NOT kill its
      donor.** On the 36a verification run — a game RESTORED from slot3, then
      saved to a fresh slot with `savegame.sh` — the pack completed (61 MB)
      and the guest was still alive and rendering 15 s later. One survival is
      not a refutation of one death; what it says is that the fault is not
      "every star_wars save", so the next pass must state HOW MANY repeats it
      ran and what the game was doing during each.
      Godzilla survives the identical dump (item 13 verified end-to-end, plus
      David's own sessions). Suspect space: the game's own watchdog tripping
      on the ~0.9 s world-stop (SW may time boards/audio tighter), or a
      frozen-mid-flight video/EGL thread resuming into an invariant SW
      exercises and Godzilla does not.
      **BLOCKED ON AN INSTRUMENT THAT IS NOW THIS ITEM'S OWN FIRST JOB.** The
      guest goes down with nothing anywhere recording WHY; until an exit hook
      names the path, a repeat sighting teaches nothing, which is exactly the D4
      line. **This used to be item 23's job. ITEM 23 WAS DROPPED 2026-08-11 at
      David's ask, so nothing else will build it** — see the Dropped section
      below, which still carries the three measured exit signatures and is worth
      reading before starting here. What it needs: an `atexit` hook in the shim
      that says whether `main` returned and what signal it took, and `watch.sh`
      grepping the `[segv] pc=` header on exit so the app pane keeps the
      signature instead of the VPU noise.
      **Acceptance:** a star_wars save leaves the donor run alive, stated over
      a number of repeats (both during play and from a restored game, since
      those differ today), or the exit reproduces and the new reason line names
      it.
      — S1: the feature's whole point is saving mid-play, and a save that
      ends the session costs the ball you were playing. D4: the instrument
      does not exist yet and the fault has already failed to reproduce once.

- [ ] **21b. Ball HANDLING: a ball model, so multiball works.** `S2 D3`
      ← IN PROGRESS *(**Split out of item 21 on 2026-08-10**, when the
      FEEDBACK half closed as 21a. The item always said the two halves were
      different prices and that the cheap one lands alone; this is the dear
      one, and it is the whole of what is left.)* *(**D4 → D3, 2026-08-10
      evening:** the eject coil index is no longer unknown, the model and the
      feeder are built and pass an end-to-end offline harness on two titles,
      and what is left needs a run rather than a new instrument.)*
      **★★ BUILT THIS PASS, branch `item/21b`, and THE LOOP IS CLOSED — live
      on the game's own display, see (6). Established:**
      **(1) THE TROUGH-EJECT COIL INDEX WAS ALWAYS READABLE AT THE DESK, and
      this item's "item 3 is upstream" blocker below is wrong.** The device
      table names every coil against the (group, index) the fire frame
      carries: godzilla_pro `TROUGH` = group 6 index 1 = **node 8 index 1**;
      jaws_le = group 7 index 1 = **node 9 index 1**, so nothing may hard-code
      the node. **The mapping is confirmed 5 positive and 4 negative against
      item 3's own labelled ball search** — it fired 2, 3, 4, 7, 8, which the
      table names RIGHT/LEFT SLINGSHOT, AUTO PLUNGER, POP BUMPER, RIGHT SCOOP,
      and did NOT fire 0, 1, 5, 6, which it names RIGHT FLIPPER, TROUGH, LEFT
      FLIPPER, UP LEFT FLIP. A ball search fires exactly the first set and
      exactly not the second. No run was needed for any of it.
      **(2) `ballmodel.py` — the ramp rule in one place.** With k balls home
      positions 1..k are made, so an eject opens the HIGHEST made position and
      a return closes the LOWEST open one. `plunge.py` now goes through it
      instead of carrying its own `reversed()`, which is the fact item 20 was
      a bug in. It also reports a trough that is not a contiguous stack.
      **(3) `ballfeed.py` — the thing that answers the game.** Watches the
      padled coil counter at 50 Hz INSIDE WSL (a host-side loop is capped near
      6 actions/s by the ~80 ms wsl.exe spawn, item 24/26) and drives the
      trough and shooter-lane switches under source letter `b`. It never
      remembers a request: the game's own retry is the queue, which is what
      folds a retry burst into one ball. `watch.sh` starts it, `alive.sh` and
      `killgame.sh` count and kill it (same day, per the non-negotiable).
      **(4) `plunge.py drain`** — nothing simulates a playfield, so a drain
      cannot be an event and is now an action. Without it a multiball could
      start and never end.
      **(5) Verified offline end-to-end, `ballfeedtest.py`, on the REAL tables
      of TWO titles** (godzilla_pro node 8, jaws_le node 9): a coil-counter
      bump takes a ball out of the FAR end, lands it in the shooter lane,
      refuses a retry inside the minimum gap, launches on the auto plunger,
      feeds three balls for a multiball, and refuses an empty trough rather
      than going negative. The harness found a real bug (refusals de-duped
      against one slot flooded the log by alternating) before a run paid for
      it. 37 unit tests beside it.
      **The one guessed number: `PAD_BALL_MIN_GAP_MS` (600).** A retry burst
      and a multiball feed are the same coil at different spacings and only a
      measured multiball can say where the line is. It logs every refusal it
      makes on that number, so it is visible rather than silently deciding how
      many balls a multiball gets.
      **★★★ (6) VERIFIED LIVE, godzilla_pro, 2026-08-10, on the GAME'S OWN
      DISPLAY. THE LOOP IS CLOSED: BALL 1 came up with nobody running
      `plunge.py plunge`.** `plunge.py coin` then `plunge.py start`, and the
      game fired its own trough eject; the feeder opened TROUGH 6 and closed
      SHOOTER LANE; the screen showed PLAYER 1 / BALL 1 (screenshot). That is
      the exact measurement at the top of this item — `coin` + `start` leaving
      the trough at 6 of 6 — now reading 5 of 6 for the right reason.
      **Two INDEPENDENT confirmations of the coil identification arrived free,
      and neither was designed for:** the game drove the eject at **lvl=225**,
      which is exactly the service menu's own "Trough Eject Power 225 (88%)",
      and the auto plunger at **lvl=150 = 0x96**, which is exactly what
      coildecode.py recorded from the ball-search capture ("the AUTO PLUNGER
      goes out at 0x96 where everything else is 0xff"). The two coils the rig
      now acts on are named by the table, by item 3's search, and by their own
      drive strengths.
      **THE WHOLE BALL CYCLE RAN, three feeds and two launches:** eject →
      lane → launch → `plunge.py drain` → the game re-served → the feeder fed
      again → **the game fired its own AUTO PLUNGER** and the feeder launched
      it. The re-serves were BALL SAVE, correctly (score 00, drained seconds
      after the plunge), which is why the display stayed on BALL 1 — that is
      the machine behaving, not the rig failing.
      **MEASURED, and it retires the one guessed number for now: ZERO
      refusals in the whole run.** The game never sent a retry burst, so the
      ~20 ms response beat its retry window every time and
      `PAD_BALL_MIN_GAP_MS` never fired. It is still a guess for the multiball
      case, where the spacing is the game's and not the rig's.
      **A BUG THE OFFLINE HARNESS COULD NOT HAVE FOUND, and it is the reason
      the first live start did nothing: the shim creates `dump/padled`
      LAZILY,** on the first LED frame, so a feeder started by watch.sh comes
      up a minute ahead of it — and "not yet" was being read as "gone", so it
      announced the run was over and exited having fed nothing. The harness
      writes the block before it starts anything and could never see it. Fixed:
      waiting is right until the block has been seen ONCE.
      **NOT ESTABLISHED — A MULTIBALL, which is this item's actual acceptance.**
      No multiball was reached: getting one needs a game played into a mode,
      not scripted pokes, and this run never scored (ball save kept re-serving
      a 0-score ball). Everything the feed mechanism does for ball two of a
      multiball it has now done three times for one ball, but that is an
      argument, not the oracle this item asked for.
      **★★ (7) DAVID REACHED A MULTIBALL BY HAND, 2026-08-11 — MECHAGODZILLA
      MULTIBALL, `trough 3/6   3 in play` on 21a's panel — and it does NOT
      close this item, because it was FED BY HAND.** His run was the app's,
      i.e. main's watch.sh, which has no `ballfeed.py`; the `[sw] +67f/-67f`
      lines in his log are virtual-playfield clicks. So the game will start a
      multiball and the panel counts it correctly, which is worth knowing —
      but the acceptance is a multiball the FEEDER served, and that still
      needs a run from this branch.
      **★★ (8) AND IT EXPOSED A REAL GAP, now fixed: nothing in the window
      could put a ball back.** David: *"how do i drain a ball? pressing one of
      the trough switches doesn't drain the ball. is there a way to just click
      on the ball indicators to add or remove it to the playfield?"* Pressing
      the switch cannot work and never could — item 24's press-and-hold is
      MOMENTARY and a ball in a trough holds its switch closed for as long as
      it sits there, so a press is a ball that arrives and leaves. The only
      latching control in the window was `Reset balls`, which makes six.
      **The six dots are the control now:** click an occupied one for
      `plunge.py take` (one ball out), an empty one for `plunge.py drain` (one
      ball home). The STACK decides which switch moves, not which dot was
      clicked — clicking the third of four opens the far end, which is item
      20's geometry and what the panel exists to show. Bound with a per-item
      `tag_bind` returning `"break"`, NOT via `info`, so item 24's hit-test
      promise holds. Tested with real Tk, not a stub canvas: the thing under
      test is a binding.
      **★★ (9) DAVID USED IT: "ok it's working well", 2026-08-11, plus two
      faults he found by using it, both now fixed.**
      **(a) "when hovering over the circles, it's not always indicating that i
      can click on it."** A Tk rule, not a mis-binding, and "always" is the
      clue: an item drawn with `fill=""` is hittable ONLY ON ITS OUTLINE, so a
      filled ball was a 14 px disc and an EMPTY position — hollow on purpose —
      was a 1 px ring. **Validated on a labelled example first** (two ovals,
      one hollow one filled, a generated click at each centre: only the filled
      one fired, and the hollow one only on its outline). Fixed with a
      per-position hit pad the colour of the panel, covering ball AND number,
      so the target is the whole cell. The regression test generates a REAL
      pointer event, because a direct call cannot see the rule under test.
      **(b) "plunge should not be auto-ejecting a ball either (it should just
      get the ball out of the shooter lane)"** — and then, on the build that
      took that literally, **"it doesn't seem to be doing anything now. at ball
      start, plunge should: eject a ball into the shooter lane closing the
      shooter lane switch, then moments later it opens the shooter lane
      switch."** ▼ **The middle version was a regression and is worth
      recording as one:** the complaint was never "never eject", it was
      ejecting a SECOND ball when one was already in the lane — which only
      became possible because ballfeed.py now puts one there. Reading it as
      unconditional turned Plunge into a no-op on the most ordinary press
      there is: ball start, empty lane, no feeder (which is every run started
      from a checkout without `ballfeed.py`, i.e. most runs today).
      **`plunge` is conditional now** — lane occupied, launch it and eject
      nothing; lane empty, serve — which is what the real control does.
      `serve` stays as the unconditional form and is what the TROUGH coil
      marker plays, since that marker IS the eject. coilact's AUTO PLUNGER no
      longer fabricates an arrival into an empty lane.
      **The harness checks BOTH directions**, because the one-sided version
      looked correct in isolation; neither check alone is the requirement.
      **Resume:** play a game into a multiball with a run FROM THIS BRANCH and
      read `~/padball.log` beside the screen — the acceptance is 2+ balls in
      play on the GAME's display, served by the feeder, and the log will say
      how many ejects it answered and whether `PAD_BALL_MIN_GAP_MS` ever
      refused one. State the repeats. Nothing of this pass is on main, so
      David's own sessions do not have the feeder or the clickable dots.
      **★ DAVID, 2026-08-06: "we will need some sophisticated ball handling
      and clear feedback about how many balls are in play. for example, during
      multiball, many balls are in play."** The feedback clause is 21a, done
      and on main. This is the ball handling.
      **THERE IS NO BALL MODEL ANYWHERE IN THIS RIG.** `plunge.py` opens one
      trough switch and works the shooter lane; nothing tracks where a ball
      is, notices a drain, or feeds a second ball when the game asks for one.
      Multiball is the game firing the trough eject repeatedly and expecting
      balls to arrive; nothing answers.
      **MEASURED 2026-08-10 during 21a's run, and it is this item's whole
      problem in one line: the game's own trough eject does not move a ball
      here.** `plunge.py coin` then `plunge.py start` left the trough reading
      6 of 6 on both the panel and `swshow.py`; the count moved only when
      `plunge.py plunge` opened TROUGH 6 itself. So every ball this rig has
      ever "played" was moved by a script pretending, and nothing closes the
      loop between the coil the game fires and the switch that should answer.
      **~~ITEM 3 IS UPSTREAM~~ — WRONG, and resolved above on 2026-08-10.**
      This said the trough-eject index was one of the unlabelled 0, 1, 5, 6
      and that an auto-feed would have to be driven blind on a timer. The
      device table names it outright and item 3's ball search confirms the
      mapping both ways; see (1). Kept rather than deleted because "the
      unlabelled coils are unknown" is the belief that made this item D4, and
      the thing that dissolved it was reading a table the rig already builds.
      **What item 20 established that this can build on** (`e1e9cb3`): the
      trough is a STACK with a known direction — TROUGH 1 is the eject end (it
      sits beside TROUGH JAM), TROUGH 6 is the far end, balls are taken from
      the far end and a returning ball fills the far end first. So "eject a
      ball" and "a ball drains" are both one switch on a known end, and the
      model is a count plus that rule.
      **21a shipped the instrument for watching this work**, and that was
      deliberate: the panel draws the six positions in trough order off
      `mrg[]`, so a model that ejects from the wrong end is visible by eye in
      one glance rather than by reading a `[sw]` stream. `trough.py` already
      answers "which switches, in what order" for any title.
      **Acceptance:** a multiball starts with more than one ball genuinely in
      play — the oracle is the game's own display, not the rig's model of
      itself, because a model that feeds itself will always agree with itself.
      — S2: single-ball play works, so nobody loses a ball to this; what it
      costs is every run that wants multiball, and it is a capability nothing
      else can work around. D4: it needs several runs, it needs a game played
      into a multiball, and its first dependency (the eject coil index) is
      itself an unfinished item.

- [ ] **46. On turtles_pro the ACTION BUTTON is FINICKY, not dead: it works
      occasionally in attract and never selects a character during a game.**
      `S2 D3`
      **★ PROBABLY ALREADY FIXED by item 17's close (2026-08-13): the cabinet
      was blind 74% of the time on EVERY title — the game re-ran its aux
      device init every ~924 ms because the shim's i2c/bus replies said
      "never initialized", and the fix (PAD_I2C_READY device models in
      hwshim.c) removed the blindness entirely on godzilla_pro (max poll gap
      690 ms → 17 ms, presses 12/20 → 20/20). "Works occasionally" is that
      fault's signature. What this item still needs is ONE verification run
      on turtles_pro: ~10 Action Button presses in attract and ~10 at
      character select, every press registering. If so, close on item 17's
      mechanism; if in-game selects still fail while attract works, THAT
      residue is the real item 46.**
      **★ DAVID, 2026-08-12, the report: "tmnt switch controls don't seem right.
      the action button isn't selecting a character after game start like it
      should." Then, the same day, having tested every switch by hand: "they are
      actually mapped correctly. however, just the action button seems to be
      finicky. i can press it in attract mode occasionally to bring up the game
      mode menu. but during a game, it doesn't seem to register to select a
      character."**
      **THAT SECOND MESSAGE IS THE MEASUREMENT THIS ITEM TURNS ON, and it moves
      the fault twice.** (i) **The mapping half is CLOSED by David's own test** —
      every switch on turtles is right, so this is one button, not "the
      controls". (ii) **The button is INTERMITTENT, not dead**, and an
      occasional success in attract proves the whole chain end to end on this
      title: the X key event, the bind, the write, the merge, the wire, and the
      game acting on it. Nothing is mis-wired; the closure is being LOST
      sometimes and (apparently) always during a game.
      **RULED OUT AT THE DESK, before the report and confirmed by it — do not
      re-test: the key is not pointing at the wrong switch.** `padglhost.c:747`
      binds Space to "Action Button" id **34** as a PLATFORM row, never
      re-resolved per title (`padglhost.c:703-713`, measured on
      star_wars/godzilla/john_wick — turtles was NOT one of the three, so this
      needed checking). Turtles' own table agrees:
      `$PAD_TABLES/turtles_pro/switch_list.txt` carries `34  80  1  2  LOCKDOWN
      BUTTON`, node 1 bit 2 — the same physical slot Godzilla calls Action
      Button. Flippers likewise: `LEFT FLIPPER BUTTON` 65, `RIGHT FLIPPER
      BUTTON` 64, both exact matches for `binds_resolve()`'s candidates.
      **★★ THE THING THAT MAKES THIS WORTH A PASS: item 17's latch says this
      CANNOT happen, and it is on.** `sw_owed[]` (`hwshim.c:4436-4520,4744`)
      defers a release until the next scan of that switch's node, so a closure
      is owed a scan and cannot be dropped for want of one; `PAD_SW_LATCH` is
      default-ON (only `=0` disables, `hwshim.c:4463`); the commit is on main;
      and switch 34 on node 1 is the EXACT switch item 17 laddered to **72/72 at
      every width down to 10 ms**. So either the latch is not in effect on this
      path, or the closure reaches the game and the GAME ignores it. Those are
      different faults and the pass must not start by guessing which.
      **THE DISCRIMINATOR IS CHEAP AND ALREADY BUILT — run it first.**
      `[swlatch]` prints the closure width and the wait every time a press is
      saved, and `PAD_SW_PEND` / `swladder.py` read the game's own `entry[+24]`.
      Together they say whether the press reached the guest. **Reached and
      ignored ⇒ the game wants something else here** (nothing in this rig
      records how TMNT drives character select — read the on-screen prompt).
      **Never arrived ⇒ it is item 17's class**, and the attract/in-game split
      is then the finding: the per-node scan gap ran to 670 ms on godzilla in
      attract and **the DURING-PLAY per-node rate is now MEASURED — item 26's
      close (2026-08-15): godzilla node 8 averaged 109 scans/s during play and
      120 scans/s in attract** (item 17's 670 ms was a worst single gap, not
      the average). Any rip on any title reprints it free in `[swspin] rip
      END`, so turtles' own number is one right-hold away.
      **★★ READ ITEM 17's BRANCH FIRST — 2026-08-12 late: it cracked a
      mechanism that predicts THIS item's symptom exactly.** On godzilla a
      button press becomes a queued EVENT whose coroutine re-reads the live
      level when it finally runs and silently cancels if the release already
      drained; measured consumption is a **width-independent ~40% lottery**
      (150 ms presses land 3/4 while 2 s presses can die — delivery correct
      on every press). "Occasionally in attract, never at character select"
      is what that lottery + a per-screen consumer difference feels like.
      The discriminator above still runs first, but if it reads
      reached-and-ignored, do NOT conclude "the game wants something else" —
      check the event-pump race before inventing a TMNT-specific rule.
      Chain + addresses (godzilla 1.15.0; turtles' differ): item/17's
      `plans/TODO.md` and the handoff's late-2026-08-12 section.
      **Repro:** turtles_pro run, `plunge.py coin` + `start`, character select
      comes up at game start; press Space there and in attract. Item 41 reached
      exactly this screen and the crash it used to take there is fixed
      (`e5a99fc`), so it is reachable and safe. State how many presses of each.
      **Acceptance:** on turtles_pro, a press of Space at character select locks
      in the highlighted turtle on the GAME's display, over a stated number of
      presses — or the instruments above name which of the two faults it is, and
      the item becomes that one.
      — S2: the game still starts and plays and no ball is lost. **The S1
      trigger is a MEASUREMENT that has not been made: if 34 is shown never
      reaching the game during play, this is item 17's argument that unreliable
      input is the thing you play with, and it goes to S1.** David's report is
      consistent with that and is not it. D3: it needs a run and a game driven
      into character select, the fault shows up when you look, and every
      instrument (`swladder.py`, `PAD_SW_PEND`, `[swlatch]`, padglhost's
      `[key]`) already exists.

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
      not yet flag a REFUSABLE slot with the reason a load would fail -
      the polish this item's text asked for beyond the list itself. The
      refusable classes are restorestate.sh's pre-flight's three: dead
      tty, gone card, and STALE BUILD - savestate.sh records a sha1 per
      mapped library (36a (3)), and any shim/bridge rebuild breaks the
      match, which `ensurebuild.sh` does by itself on any source change,
      so this is the class a user actually hits.
      **★ DAVID, 2026-08-16: "why do save states break between builds?"**
      Answered at the desk (criu restores file-backed pages from the
      files as they are NOW and validates size + build-ID, so a slot is
      welded to the exact binaries it was dumped under - 36a (3) is the
      full record) - but that the question needed asking is this item's
      case in one line: the slots list should SAY a stale slot is stale
      and which library moved, not leave the refusal to load time.
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

- [ ] **40. After a save-state LOAD the playfield's LEDs never come back, and
      the window says "no emulator" over a run that is plainly alive.** `S2 D2`
      **★ DAVID, 2026-08-11: "load state doesn't seem to get the LEDs loaded up
      on the virtual playfield and it says that there is 'no emulator' but there
      is."** godzilla_pro card run, `PAD_PIVOT=1`, the load asked for before the
      game was up (`08:46:07 will load slot 'slot1' once the game is up`) and
      taken at `08:46:23 [loadgame] restored slot 'slot1'`. The restore itself
      went well — switch ring rewound, video ring rewound, GL journal replayed,
      video host resumed — and the game kept playing: `[sw]` edges and 30 fps
      video for the next four minutes. The playfield window kept its SWITCH half
      too (blue/red markers live, trough 3/6, 3 in play in David's screenshot),
      so `dump/` is readable and this is `dump/padled` alone.
      **ESTABLISHED AT THE DESK, from the source — but NOT yet confirmed to be
      what happened in this run, so treat the last step as the guess it is:**
      (i) `watch.sh:475` `rm -f $LED_HOST` then `dd if=/dev/zero … bs=4096
      count=1` — **every session start replaces `dump/padled` with a 4096-byte
      ZERO file**; (ii) `hwshim.c:5385 led_map()` is a `static int tried`
      one-shot and stamps `magic`/`version` exactly once, at the first LED frame
      it decodes (`:5401`) — a criu-restored guest already has the mapping, so
      it never stamps again; (iii) `restorestate.sh:274-326` rewinds `padsw`
      ALWAYS and `padvid` when its host restarts, and every other ring —
      **`padled` included — only if it is MISSING** (`:322`), which watch.sh
      guarantees it never is. (iv) The guess: the restored guest therefore goes
      on writing `val[]`/`gen` into a header that still reads `00 00 00 00`, and
      `playfield.py:1674 read_leds()` returns None on that magic test, which is
      the one and only source of both "no emulator (dump/padled not readable)"
      (`:1987`, `:2286`) and the dark playfield. Same shape as the padsw
      phantom-edge fault 36a fixed: a fresh session's zeroed ring under a guest
      whose memory belongs to another session.
      **THE OTHER CANDIDATE, and it is the cheaper check, so do it first:**
      ownership. This was a root (`PAD_PIVOT=1`) run and a root-owned `padled`
      is exactly what makes the window say "not readable" (`watch.sh:261`,
      `:487`), and the loose end about root-owned `dump/` files is open. **One
      command after a failed load settles which:** `ls -l ~/spike2root/dump/
      padled` and `xxd -l 8` it — root owner means ownership, `00000000` in the
      first four bytes means the header.
      **If it is the header, the fix has two shapes and the cheap one needs no
      rebuild:** rewind `dump/padled` from the slot's stash in place like padsw
      (host-side, `restorestate.sh`), or make `led_map()` re-stamp. Do not reach
      for the shim change first — a rebuild kills every existing save slot (36a
      (3)), so it would cost the very slot the test needs.
      **Acceptance:** save a slot, start a FRESH run, load it, and the LED half
      paints again with the bar reading `emulator up … LED writes decoded`
      rather than "no emulator" — state the owner and first four bytes of
      `dump/padled` after the load, and say whether a SAME-session load behaves
      differently from a cross-session one, since only the fresh session zeroes
      the ring.
      — S2: the game plays and the switch half of the window still works, so it
      is not S1; what it costs is that after any load the LED picture is dead
      for the rest of the run, so every item that wants lamps (1d, 31) cannot
      use a save state to get to its scene, and the window actively lies about
      the rig being down. D2: the mechanism is read off the source above and the
      fault should reproduce on every load, but confirming it needs one windowed
      session with a save and a load.


- [x] **50. No LED feedback at all on a title with no playfield artwork,
      which is most of them.** `S3 D4` ← CLOSED 2026-08-18, acceptance met on
      turtles_pro in its strongest form; see the ★★★ close block below the
      resume note. Awaiting `/finish`.
      **★★ REOPENED 2026-08-16, HOURS AFTER BEING CLOSED, BY DAVID — and the
      reason is the one that matters.** Asked whether it worked, he said: *"i'm
      confused did we make this work or not? does it work for TMNt for
      example"*, and on being told no: *"do option 1 and let's make it work
      now"*. **Option 1 was: fold item 54 into this one and keep it open until
      TMNT actually lights up.**
      **THE CLOSE WAS TOO GENEROUS AND THIS IS THE LESSON.** Everything in the
      Done-section entry below is true — the view is built, the tracking is
      measured, godzilla and elvira3 both showed real LED activity — but on
      **turtles_pro, the title David was looking at when he FILED this item,
      the window still shows nothing.** The acceptance was met on the machinery
      and not on the ask. A feature that is correct and shows nothing to the
      user who asked for it is not done. **D3 → D4:** what is left is not
      drawing work at all, it is an unknown frame shape that needs runs.
      **THE WHOLE OF WHAT IS LEFT is what was item 54** (now folded in; do not
      work it separately): turtles_pro puts NO frame the shim recognises as a
      lamp write on the wire — `decoded=0` AND `skipped=0` across a whole run,
      including while the game's own `Diagnostics → Single LED Test` was being
      stepped by hand and naming `13 / 8-LP-5 / LEFT RETURN LANE LEFT-G / CN14
      / RETURN=4, SOURCE=7/8`. `skipped=0` is the load-bearing half:
      `led_publish()` is called on EVERY node bus write (`hwshim.c:7224`), so
      the frames are not failing the decoder, they are not reaching it.
      **Acceptance, REPLACED and now the only one that counts:** on
      **turtles_pro**, LEDs visibly light and move in the playfield window
      while the game runs — stated with a screenshot and with the ring-vs-screen
      measurement in BOTH directions (the picture must also hold still when the
      game does).
      **★★ THE DIAGNOSIS FLIPPED, 2026-08-17, AND IT IS MUCH SMALLER THAN
      "AN UNKNOWN FRAME SHAPE". turtles_pro ALREADY SENDS COMMANDS THE DECODER
      ACCEPTS.** Unioned over **23 turtles captures in `/var/tmp`**
      (`item43_*.log`, 2026-08-11/12, 345 KB–6.7 MB — nobody had looked there),
      turtles sends **six of the eight accepted lamp commands — 97, a2, a4, a5,
      b4, b5 — on nodes 1, 8 AND 9**, e.g. node 8 `8805b43abf07bf00` (b4),
      node 9 `8908a224ab00ff0702f600` (a2). And its `node_ident.txt` says nodes
      1/8/9 are `pinnode` boards, the same type as godzilla's. **So no new
      decoder shape is needed.** The question is what makes turtles reach the
      state where it drives them.
      **Why the item-50 run saw nothing, two independent signals agreeing:**
      hwshim's light-show announcer (`hwshim.c:6086-6118`) fires on those eight
      commands on ANY node, deliberately before the node gate — it never fired;
      and an un-enumerated board yields `decoded=0` with **`skipped > 0`**,
      while that run had `skipped=0` too. Both say no lamp command was SENT,
      not that one was sent and rejected.
      **★ CORRECTIONS TO EVIDENCE THIS ITEM PREVIOUSLY RELIED ON — do not reuse
      the old numbers:** (i) `/home/david/gzwatch.log` is **not** turtles; it
      was overwritten by the concurrent item-52 session and now declares
      `[run] title: stranger_things_le`. The "402-second turtles run" cited
      earlier is `/home/david/gzt2.log` (2026-08-05, `[run] title: turtles_pro`)
      — **and two agents disagree about whether that file has node-bus lines at
      all, so re-derive it before use.** (ii) `[nb] TX` logging is BUDGETED
      (~162 frames, all boot handshake), so any "vocabulary" read off a single
      run's `[nbcmd]` census is truncated and is NOT the title's command set.
      The `decoded`/`skipped` counters in the padled block are not budgeted and
      remain authoritative.
      **★ RIG IS DOWN AND NEEDS DAVID, 2026-08-17.** `wsl --shutdown` (run to
      clear the item-38 interop zombies) never completed: `vmmemWSL` is still
      up, `WSLService` reports Running, and every `wsl` invocation now HANGS
      rather than returning. 18 hung `wsl.exe` clients were cleared, which did
      not help. Needs an elevated `Restart-Service WSLService` or a reboot. **No
      rig work of any kind is possible until then**, including reading
      `/var/tmp`.
      **★★★ TMNT LIGHTS UP, 2026-08-17. `37 of 42 LEDs lit`, `2772 LED writes
      decoded`, `44 coils addressed` — screenshot taken.** The decoder needed
      NO change. What was missing was the STATE the game has to be in, and the
      recipe is the valuable part:
      **(1) turtles boots to a Tech Alerts screen and stays there** — and they
      are SWITCH complaints (`Check Switch #80 LOCKDOWN BUTTON`, `#91 TILT
      PENDULUM`), not the node-board complaints elvira3 shows. Its boards are
      found. While parked there it runs no light show at all.
      **(2) `plunge.py reset` clears it** ("six balls in the trough, coin door
      shut") and the game proceeds to attract.
      **(3) ATTRACT IS NOT ENOUGH.** In attract turtles drives only node 1 —
      `a4`/`a5` at len 7, body `0485`, blen 2 — which is too short for any
      decoder shape and which **godzilla logs as `[ledskip]` with the identical
      body**, so it is not lamp data on either title. Nodes 8 and 9 enumerate
      (64 and 58 indices) and receive nothing.
      **(4) A GAME IS WHAT DRIVES THE PLAYFIELD.** `plunge.py coin` ×2 then
      `plunge.py start`, and lamp frames land on nodes 8 and 9 immediately:
      `decoded` 0 → 380 → 2772 → 5142, live channels `{8: 2, 9: 35}`.
      **★ THE 6-BYTE ENUMERATION DOES RUN ON TURTLES** — node 1: 6, node 8: 64,
      node 9: 58, frames `88038400f100` / `89038500ef00`. So star_wars's
      failure mode (enumeration absent, `led_known` empty, everything skipped)
      is RULED OUT for turtles, and this was measured from the first
      `PAD_NB_TRACE` capture turtles has ever had (`~/i50_tmnt_trace.log`;
      every one of the 23 `/var/tmp/item43_*.log` files is the BUDGETED kind,
      exactly 162 frames of boot handshake, and proves nothing either way).
      **★ THE GRID MOVED TO THE LEFT, and that was a real fault not a
      preference.** With turtles' 93 switches flowing into three columns the
      grid was pushed past the window edge and survived only behind the
      horizontal scrollbar — the window reported `37 of 42 LEDs lit` while
      showing the user nothing, which is precisely the complaint this item
      exists to fix. The lamps are what this view is FOR; the switch list is
      what scrolls now.
      **★ WHAT IS STILL NOT DEMONSTRATED, and it is why the box is still
      empty.** The replaced acceptance asks for LEDs that "visibly light AND
      MOVE", with the ring-vs-screen measurement in BOTH directions. Only the
      NEGATIVE direction was obtained on turtles: across 13 samples the ring's
      lit set held the same 37 channels and the screen changed 0 pixels, four
      times over, even while `decoded` climbed by hundreds (the game rewriting
      identical values — the churn control, and it passes). **No POSITIVE
      transition was measured on turtles**: its lamp picture stayed static
      through attract, ball launch and three target hits. The 0 → 37 change
      when the game started WAS observed but not instrumented. The positive
      direction is measured only on godzilla_pro (10 channels → 4635 pixels,
      36 → 9811).
      **★ AND THE STATIC PICTURE IS THE GAME'S, NOT THE VIEW'S — settled at
      the desk from the capture, so no run was spent on it.** Replaying the
      lamp frames out of `~/i50_tmnt_trace.log` and counting DISTINCT payloads
      per (node, cmd, len): node 1 `a4`/`a5` sent **one** payload (`0485`)
      1254 times; node 8 `b4` len 11 **one** payload 59 times; node 9 `b4` len
      9 **one** payload 81 times; node 9 `b4` len 8 **two** — `3bbd0a` ×85 and
      `26a701` ×1. **turtles sends NO `a2` frames at all**, so it animates
      nothing through the fade ring either. The wire genuinely carried a still
      picture; the grid was faithful to it. **That rules out a decode gap and
      means the next move is GAMEPLAY, not code.**
      It also explains the four missed sampling windows: the picture DOES
      change (that lone `26a701`), just rarely while the game idles, so a
      4-second sample almost never straddles a transition.
      **Resume — the named oracle is now reachable and is the cheapest sure
      thing.** turtles gets past its Tech Alerts once `plunge.py reset` runs,
      so `Diagnostics → LED Tests` can be driven: `swhold.py 33 0` (door OPEN,
      service menu live), then `swpoke.py 25 2000` for Service Select and
      `swpoke.py 26 500` / `27 500` to move, `28` to go back. It lights ONE
      named fixture at a time, which forces the transition the instrument
      needs AND satisfies the acceptance's strongest form. Sample the ring and
      the screen across each step. **Tap lengths are godzilla's and are a guess
      on turtles' menu generation** — expect to calibrate.
      **★★★ CLOSED 2026-08-18: THE ORACLE WAS DRIVEN, IT SPOKE A THIRD
      VOCABULARY, AND THE VIEW NOW TRACKS IT — both directions, ring and
      screen agreeing, measured across four runs.**
      **The measurement that closes the box (run 4, `Single LED Test`, 12
      stepped fixtures):** `lit=1` at every step — the SINGLE LED test reads
      as a single LED — and every step that moved shows **RISEN(1) +
      FALLEN(1) in the same step**: `1:2→1:3→1:5→1:4→1:7→8:3→8:6→8:5→8:4`,
      cabinet board onto playfield board, each named on the glass (`2 / 1-LP-2
      START BUTTON` …). The screen half: 404–712 grid pixels changed on the
      stepped transitions (the three 0-px steps were shot-vs-tick aliasing,
      proven by a same-ring re-shot moving 364 px as the grid caught up).
      Window screenshot taken: node 8's row with ONE orange cell, status bar
      `1 of 10 LEDs lit  44374 LED writes decoded`.
      **Why the test was invisible before (run 2's capture, 85.7 s, 126k
      frames, trace budget spent on purpose before attract could eat it): the
      service menu never speaks 97/a2/b4/b5.** Its whole cycle is
      `[node][05][70][idx][v16]` off-sweeps (×7755, value always 0000),
      `[node][04][94][idx][val]` / `[node][04][95][idx][val]` for the ONE lit
      fixture (×432, alternating ~133 ms apart), plus an `a2` flash tail on
      stepping and a constant `41` len-52 broadcast that never tracked the
      walk. The 94/95 (node,idx) walk matched the glass fixture-for-fixture
      across 17 steps. godzilla's GAME mode also sends the len-7/len-8 forms
      (6579 ×70 — all `idx 0000` — and 178 ×95 in the item-27 capture), all
      skipped until now; its longer 94s (blen 7–14) are some run/compressed
      form deliberately NOT claimed.
      **The decode (hwshim.c, before the command gate): exact cmd+length
      match, `idx < 96` bound, NO `led_known` gate** — measured: node 1
      announces 6 LEDs yet the test lights node 1 idx 7. `70` writes the base
      (`val[idx] = v`, observed only as clear). **`94`/`95` hold only while
      refreshed** — the hammering is the evidence: the test re-asserts the lit
      fixture at 7.5 Hz and never sends an off for indices past the sweep's
      0x00..0x26 window; a latch left a trail (run 3 measured `lit` 1→10); a
      watchdog output that decays goes dark by itself. Implemented entirely
      in the existing overlay machinery: each 94/95 lands in the fade ring as
      a flat hold (`from=to=val, rise=0, fall=33` ≈ 400 ms at the reader's
      12 ms/unit), re-armed by every refresh, expiring onto base 0 when the
      game moves on. Run 4's `lit=1`-everywhere is that model confirmed live.
      `ledreplay.py` mirrors the accept path (run-2 window: 8373 of 8386
      would-decode) so the desk stays truthful.
      **The a6 comment's own caveat is now partially answered**: the oracle it
      asked for has been run; on these indices the wire's idx IS the fixture
      the glass names (1:2 = START BUTTON, per-step match ×17). The a6
      bitmap-order question itself remains open — the test never spoke a6.
      **Menu recipe, CORRECTED from the resume note's guesses — this is the
      valuable operational half:** (1) `swpoke --tap` at 1–5 reads moves
      NOTHING on turtles: menu actions need a real wall-clock press,
      `swpoke.py 25 300`. In-menu cursor moves want `--tap 26 10` = exactly
      one step (the tap lottery still eats ~⅓ of taps; screenshot between
      steps). (2) Clearing Tech Alerts needs `plunge.py reset` AND a Back
      press (door open) — reset alone parks there, run 1 only cleared because
      autoattract had pressed Back first. (3) **Kill autoattract.sh before
      any menu work** — it blind-presses Service Back every ~45 s against a
      log that never answers, and its id-28 press is turtles' SERVICE BACK.
      (4) Path: alerts →Back→ splash →Select→ main menu (DIAG) →Select→
      diagnostics (SW) →+×2→ LAMP →Select→ SINGLE LED →Select→ in. Fixture 2
      START BUTTON is the entry point.
      **Evidence on disk:** `~/i50_test_window.log` (run 2's test window),
      `~/i50_run{1,2,4}_gzwatch.log`, `C:/tmp/item50/` (grid + LCD
      screenshots, per-step ring json), scratchpad `ledstep.py` /
      `testvocab.py` / `map70.py` / `walk9495.py` (the instruments; session
      paths, deliberately not shipped).
      See the folded item-54 body below for the ruled-out titles, the decoder's
      accept path, and the `lednames.py` name-table work already done.
      **★ DAVID, 2026-08-14: "we should have some visual indication of leds
      here even without the playfield. can we think of some elegant way to show
      that?"** The window's own status bar says `2285 LED writes decoded` while
      showing nothing lit — the data is arriving and there is nowhere to put
      it.
      **★★ DAVID, 2026-08-16, WHICH SPLIT THIS ITEM IN TWO: "if we can show
      them positionally (relative placement) that is ideal. also showing
      switches placement would be ideal. (even if we can't show the playfield
      artwork)."**
      **★★ THE PREMISE BELOW WAS WRONG, AND THAT IS THE PASS'S MAIN RESULT.**
      This item said Bond "has neither" a playfield image nor anything
      positioned on it. **james_bond_60th_le carries a COMPLETE playfield
      layout — 73 LEDs, 49 switches, 16 coils, every one at a distinct
      position — and its artwork is fine.** All 138 records were dropped by a
      string compare: Godzilla, Jaws and John Wick name that image
      `playfield`, Bond names it `Test/scaled_playfield`, and every loader in
      the rig filtered on the literal. The `202x443` art is not a "thumbnail"
      in any bad sense either — it is the same KIND of asset Godzilla uses (a
      test-mode line drawing, Godzilla's is 313x710) and it CONTAINS Bond's
      coordinates (x 6..196, y 26..409), so it draws correctly.
      **Established, all at the desk, no run:**
      **(1) Only 4 of 9 titles genuinely have nothing** — star_wars_le,
      stranger_things_le, turtles_pro, led_zeppelin_le all carry `0 records`
      in device_xy.txt. elvira3 has 275 LEDs positioned on its TOPPER image
      and no playfield at all.
      **(2) Bond's switches join 49/49** to a live id from switch_list.txt at
      the desk, so they are positioned AND clickable with no run and no
      rebuild. The three titles that already have a built switch_xy.txt score
      41/41, 60/60 and 57/57 by the same join, which is what says the derived
      path and the built one agree.
      **(3) SHIPPED THIS PASS on `item/50`:** `devicexy.layout_image()` (one
      definition of which image is the layout — most device CLASSES, then most
      devices), `devicexy.read_table()` (device_xy.txt back into records, so a
      CARD run needs no ELF), playfield.py reading its LEDs/switches/coils from
      that table, artwork that is accepted only when its pixel size CONTAINS
      the coordinates, and a blank-field fallback when it is not. Bond's window
      now draws its playfield; `ledratetest.py` still PASSES on godzilla_pro,
      which is the regression gate for the artwork view.
      **★ (4) A SEPARATE DEFECT FOUND ON THE WAY, and it is bigger than this
      item — see the new item on the group → node map.** `coilmap.GROUP_NODE`
      is `{4:0, 5:1, 6:8, 7:9}`, measured on Godzilla and hard-coded. Bond's
      playfield devices are groups 8 and 9, so **0 of 73** LEDs get a wire
      address. It is not only Bond: **jaws draws 65 of its 143 LED channels and
      john_wick 53 of 406** for the same reason, and nobody noticed because
      both look fine. Positions are known; the wire address is not.
      **★ (5) THE SWATCH GRID IS BUILT AND PASSES OFFLINE, `5e87bb9`.**
      `LedGrid` in the `Schematic` view, roster from the LIVE RING so it works
      on the 4 titles with no table and needs no group → node map. `LedRing`
      is Field's fade/base-layer read moved out verbatim, so both views decode
      the wire once. `ledgridtest.py` is the harness, in `ledratetest.py`'s
      shape and importing its `Feed`: 12 irregular channels → exactly 12 cells
      **of the 1536 addresses that exist** (the labelled negative), a roster
      growing in 4 stages costing 4 canvas items, tracking 90→255→0 with a
      churn control, and an a2 pulse returning to the BASE layer. turtles_pro
      captured showing 111 channels on nodes 8/9, "86 of 111 LEDs lit".
      **Ruled out / fixed on the way:** `_rebuild` first made fresh cell dicts
      per rebuild, leaking a canvas item per cell and burying the node headers
      under stale swatches — invisible to a test that lights everything at
      once. The staged-growth case exists because of it.
      **★★ (6) THE LIVE RUN, turtles_pro, 2026-08-16, AND IT FOUND TWO THINGS.**
      **(6a) FIXED AND VERIFIED LIVE: the window said "no emulator" over a
      game that was plainly running its attract.** The status was gated on the
      padled MAGIC, which hwshim stamps on the first LED write it DECODES — so
      a title that decodes none leaves the block zeroed and the window called
      a healthy run dead. That is David's item-40 complaint arriving by a
      second route, and it also meant the grid lived in the else-branch and
      could never draw on the one title it was built for. Three states are now
      distinct (unreadable / readable-but-unstamped / stamped); the live bar
      now reads `emulator up   NO LED DATA on this title: the shim has decoded
      no LED writes at all   trough 6/6   0 in play` — the trough proving the
      run is there.
      **(6b) turtles_pro DECODES NOTHING, and the run pinned why it is not the
      grid's fault. `decoded=0, skipped=0` THROUGH THE GAME'S OWN
      `Diagnostics → Single LED Test`** — David drove it to `13 / 8-LP-5 /
      LEFT RETURN LANE LEFT-G / CN14 / RETURN=4, SOURCE=7/8`, i.e. the game
      names the lamp, its node and its connector while the wire stays silent.
      `skipped=0` matters: `led_publish()` is called on EVERY node bus write,
      so the frames are not being rejected by the decoder, they are not
      arriving. No NEW node bus command byte appeared during the test either —
      turtles' whole vocabulary over the run is `00 03 04 07 08 0a f0 f1 f2 f9
      fc fe`, with the shim answering `fe` (identity) and returning all-zeros
      to `f9`/`fc`. See the new item on the LED write shape.
      **The turtles run is DOWN** (David: "i'm done. take over"). Logs kept at
      `~/item50run.log` and `~/item50watch.log` — the `[nbcmd]` census in the
      first is item 54's evidence and the budget was never spent.

      **★★ CLOSED 2026-08-16. THE ACCEPTANCE, CLAUSE BY CLAUSE, AND THE ONE
      AMENDMENT — read this before believing the box.**
      **(a) "on a title with no artwork the window shows LED activity" — MET
      LITERALLY, on elvira3**, the one title on this disk with no
      `playfield.png` at all. Its grid discovered 4 channels from the WIRE
      (its table contributes nothing — all 275 of its lamps are group 3, which
      GROUP_NODE cannot address), and the bar read `emulator up   4 of 4 LEDs
      lit   4 LED writes decoded`. Counter and cells agree.
      **(b) "that visibly tracks the game" — MET, MEASURED, BOTH DIRECTIONS,
      but on godzilla_pro forced into this view with `PAD_PF_VIEW=schematic`.**
      elvira3 could not supply it: it boots to a Tech Alerts screen (node
      boards 2/7/14, `GAME VALIDATION ERROR - #3 UPDATE SD CARD`) and will not
      start a game, so its 4 channels sit static. Against godzilla's live
      attract, sampling the RING as ground truth beside the screen:
      10 channels changed → 4635 grid pixels changed; 36 changed → 9811
      changed; **0 changed → 0 changed**. That last row is the labelled
      negative — the view holds still when the game does, so it is tracking and
      not merely repainting. The roster grew to `node 8 (45) + node 9 (68)` =
      **113 channels, which is exactly the 113 godzilla's device table
      independently says it has**, discovered with no table read at all.
      **★ THE AMENDMENT, AND IT IS DAVID'S TO OBJECT TO:** the acceptance named
      `Diagnostics → LED Tests driving one fixture at a time by name` as the
      real form. That was NOT reached. What replaced it is a ring-vs-screen
      measurement in both directions, which is more rigorous than eyeballing
      one fixture but is not what the clause said — and it was taken on a title
      that HAS artwork, forced into the view. The clause was written under the
      premise this pass demolished ("Bond has neither"), which is why amending
      it is defensible rather than convenient.
      **(c) "a title WITH artwork is unchanged" — TRUE OF THE THREE THAT WERE
      WORKING, AND DELIBERATELY FALSE OF ONE.** `ledratetest.py` still passes
      on godzilla_pro (the regression gate), and godzilla/jaws/john_wick keep
      exactly their 81/113/198 LED fixtures, 41/58/56 switches and 10/14/16
      coils. But `88dd76e` deliberately moved james_bond_60th_le from the bare
      switch list INTO the artwork view, which David asked for in as many
      words, and `26b3986` changed the status line on every view. Both are
      wanted; "unchanged" is not literally true and a close that asserts it
      would be overclaiming.
      **★ WHY NO TITLE IN THIS VIEW COULD SUPPLY (b) — five ruled out, and it
      is item 54's evidence:** turtles_pro (live, `decoded=0 skipped=0` through
      the game's own Single LED Test); star_wars_le (`led_publish` replayed
      over an 8.5-minute trace — 619 LED-class frames DO land on the insert
      nodes but `led_known[8]`/`[9]` are empty because it never sends the
      6-byte `0x84/0x85` enumeration, so DECODED=0 and SKIPPED=619);
      led_zeppelin_le (three runs, ~11 min of attract, not one of the eight
      accepted command bytes ever appears); stranger_things_le (item 52 — the
      game never finds nodes 1, 8 and 9, which are precisely the decoded ones);
      elvira3 (Tech Alerts, will not start a game).
      **★ CORRECTED COUNTS, measured twice (through `GROUP_NODE` and from the
      built `led_io.txt`): jaws draws 67 of 143 and john_wick 57 of 406**, not
      the 65 and 53 written above and in item 53. Bond's 0 of 73 stands.
      **★ RIG STATE ON EXIT — NOT CLEAN, AND IT NEEDS DAVID.** `killgame.sh`
      leaves **2 zombie `game` processes (`Zl`, no CPU) and elvira3's fuse2fs
      card mount**; they are held by a WSL interop Relay and ignore SIGKILL
      from inside the VM. The cure is `wsl --shutdown` from Windows, which this
      session is not permitted to run. It is item 38's known fault, and the
      zombies burn nothing while they sit. The rig lock has been RELEASED.
      **Resume:** the grid is proven offline and cannot be proven live on
      turtles until the new item lands. The cheapest live proof left is a
      title that DOES decode LED writes and lands in this view — but note
      Bond now gets the artwork view, so today that is star_wars_le or
      led_zeppelin_le, and neither is known to decode. **State that in the
      close: item 50's acceptance is blocked on the LED-write item, not on
      the grid.**
      **Acceptance:** on a title with no artwork the window shows LED activity
      that visibly tracks the game (state what you compared it against — the
      LED-writes counter moving with cells changing is the weakest form; the
      service menu's own `Diagnostics → LED Tests` driving one fixture at a
      time by name is the real one), and a title WITH artwork is unchanged.
      — S3: nothing is broken and the LEDs are decoded and counted already, so
      this is a missing view rather than a missing capability. D3: the data and
      the fixture join both exist, the layout is new drawing work in
      playfield.py, and confirming it means a run with the LED test menu.

- [ ] **54. FOLDED BACK INTO ITEM 50 on 2026-08-16 at David's ask — do not
      take this as a separate item.** It was split out when item 50 looked
      closeable without it; David's "does it work for TMNT" made clear that
      item 50 is not done until this is, so item 50 now carries the acceptance
      and this entry is kept ONLY for the evidence below, which is expensive
      and must not be re-derived. `S2 D4`
      *(Everything under here is item 50's working state.)*
      **★ DAVID, 2026-08-16, looking at the running game: "i feel like there
      should be an led table somewhere. look at the diag → all leds screen for
      example."** He is right, and the screen he was on is the oracle:
      `SINGLE LED TEST / 13 / 8-LP-5 / LEFT RETURN LANE LEFT-G / CN14 /
      RETURN=4, SOURCE=7/8 / GRN-BRN / YEL`. The game names the lamp, gives
      its board (`8-LP-5` — node 8, lower playfield), its connector and its
      matrix return/source. That data is in the binary.
      **MEASURED ON A LIVE turtles_pro RUN (item 50's), and it is a negative
      result with numbers:** `decoded=0, skipped=0` for the whole run
      INCLUDING the Single LED Test being stepped by hand. `skipped` counts
      frames that looked like indexed LED writes and fitted no shape, so zero
      of BOTH means the frames never arrive — and `led_publish()` is called on
      every node bus write (`hwshim.c:7224`), so nothing upstream is filtering
      them. The `[nbcmd]` census (one line per first sighting of a command
      byte, budget NOT spent — 3172 lines) shows turtles' entire vocabulary as
      `00 03 04 07 08 0a f0 f1 f2 f9 fc fe`, **with no new byte appearing
      during the LED test**. Godzilla's per-LED config writes are `0x84/0x85`
      (ledio.py) and its fades are `a2`; none of those appear here. The shim
      answers `fe` (identity) and returns all-zeros to `f9` and `fc`, e.g.
      `TX 8103f9008312 → 18 bytes of 00`.
      **TWO READINGS, AND THEY NEED DIFFERENT WORK — decide which before
      building:** (i) turtles drives its lamps with a command shape nobody has
      decoded, in which case `PAD_LED_SKIP_LOG` / `PAD_NB_LOG` raised on a run
      that reaches the Single LED Test will show it, and the test screen NAMES
      the lamp being driven, which is the labelled experiment this rig always
      wants; or (ii) the game has concluded the boards are not there and is
      not driving them at all, which makes this a sibling of items 51/52 and
      the all-zeros `f9`/`fc` replies the thing to fix.
      **THE NAME TABLE — HALF DONE 2026-08-16, and it turned out to be the
      more interesting half.** `lednames.py` used to die on turtles
      (`struct.error: ... offset 7725056 (actual buffer size is 6457552)`)
      because it hard-coded godzilla's `TABLE_VA`. It now finds message tables
      BY SHAPE, the same move devicexy.py made: a record is 0x18 bytes of FIVE
      pointers to one string then a null, the five being untranslated language
      slots, and requiring all five to be EQUAL is what makes the fingerprint
      strong. **105 message tables located in godzilla_pro with no address at
      all**, 11 of them carrying `-R/-G/-B` lamp names.
      **★ AND IT DEMOLISHED THE OLD CONSTANT, which is the finding to keep:**
      **`0x766000` is not the start of anything.** It is record 73 of the run
      at `0x765928` and lands on `'Heat Ray 9-G'`, mid-family — so every
      "channel index" that tool ever printed was offset by an arbitrary 73.
      **There is no single LED table**: godzilla's lamp names are spread over
      at least five runs (125, 104, 43, 27, 27 records), and names run
      **DESCENDING** within a run — `Heat Ray 11-G, 10-B, 10-R, 10-G, 9-B`.
      lednames.py now reports the candidate RUNS and states that its index is
      within a run and is NOT the game's channel number, rather than inventing
      the join. **Do not "fix" it by picking the biggest run.**
      **What is left of this half:** the join from a run's records to the
      game's own lamp index. The oracle is the Single LED Test itself — it
      names one lamp against one index and one board, so a handful of stepped
      LEDs with the names written down pins it as a labelled experiment.
      **Acceptance:** state turtles_pro's LED write frame with the lamp the
      Single LED Test named while it was captured (so the decode is labelled,
      not guessed), and show `decoded` moving above zero on a run; separately,
      lednames.py returns a named table for a title it has never seen.
      — S2: no title is blocked from playing, but the LED half of the virtual
      playfield is dead on the four table-less titles and item 50's view has
      nothing to draw there. D4: it needs runs, the frame shape is unknown,
      and reading (i) vs (ii) has to be settled before the instrument is
      chosen.

- [ ] **53. The device-table GROUP → bus NODE map is ONE TITLE'S measurement,
      so most titles' lamps and coils have a position and no wire address.**
      `S2 D3` *(Split out of item 50 on 2026-08-16, which found it while
      giving Bond a playfield. Item 50's grid does not need this — it reads the
      ring directly — so the two are independent and this one is about the
      ARTWORK view.)*
      **The map is `coilmap.GROUP_NODE = {4: 0, 5: 1, 6: 8, 7: 9}`**, verified
      by `ledio.py` against godzilla_pro's boot enumeration and then used for
      every title. It is a lookup, not arithmetic — the comment in coilmap.py
      already says group N is not simply node N+2 — and nothing re-derives it
      per title.
      **What it costs, measured at the desk 2026-08-16 (no run):**
      james_bond_60th_le's playfield devices are groups **8 and 9**, so **0 of
      73** LED channels, and none of its 16 coils, can be addressed; jaws_le
      draws **67 of 143**; john_wick_le **57 of 406** (both re-measured
      2026-08-16 twice — through `GROUP_NODE` and from the built `led_io.txt`
      row counts; earlier drafts said 65 and 53). Those two look healthy
      today, which is why this went unnoticed for so long — a partially lit
      playfield reads as a game that is not lighting much.
      **Switches are NOT affected and that is a clue**: their id/node/bit come
      from the running game's own switch table by NAME, never from the group.
      **THE INSTRUMENT ALREADY EXISTS AND THE JOIN IS SELF-VALIDATING.**
      `ledio.py` proves the boot enumeration's per-node index set equals the
      device table's index set for that group — 53/53 on node 8 and 69/69 on
      node 9 on godzilla, **including ~19 irregular skips**. So: take each
      group's index set from the table, take each node's index set from the
      wire (the boot `0x84/0x85` per-LED writes, or simply which indices the
      live `padled` ring ever writes), and match them. An irregular set of ~70
      values matching is a fingerprint, not a coincidence — the same argument
      ledio.py already makes. Then WRITE THE RESULT PER TITLE (a
      `group_node.txt` beside the other derived tables) rather than editing the
      constant, because the whole fault is one title's answer standing in for
      every title's.
      **Acceptance:** on a title whose groups are not in the hard-coded map,
      state the derived group → node mapping and the index-set match that
      supports it (counts both ways, e.g. 73/73), then show its playfield
      lighting — Bond is the sharpest case because it currently lights nothing.
      A title already working (godzilla) must derive the SAME map it has now.
      — S2: play works and no title is blocked; what it costs is that the
      virtual playfield is silently wrong on most titles, which makes it a
      poor instrument for every other item. D3: one run to capture the wire
      side (or a live ring read), the instrument exists and is validated, and
      the fault is on demand.

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

- **NOT EXPLAINED: `[dev] --- ball devices: count=1119174656 ---`** on both
  james_bond_60th runs, 2026-08-14. 1.1 billion is a misparse of something. The
  switch names still came out and `[swfind] found the switch table: entry[] at
  0x007d2680, 118 switches` on both runs, so it is the ball DEVICE table
  specifically - which is what item 21b's trough model reads, so it is worth
  knowing before that item trusts it. (The other half of David's "the switch
  table isn't coming through" report that day was the first-run window gap, now
  fixed and closed as item 47.)

- **The ball feeder cannot see ejects on james_bond_60th: its TROUGH coil is
  device-table GROUP 8, and `coilmap.GROUP_NODE` only knows groups 6 and 7.**
  Found 2026-08-15 during item 49's healing run: ballfeed's new wait picked the
  switch table up, resolved Bond's trough, and then reported `eject coil NOT IN
  THE DEVICE TABLE - ejects cannot be seen` - the row is there
  (`coil TROUGH ... grp 8 index 1` in Bond's device_xy.txt) but the group→node
  map was measured on godzilla_pro (6→8) and jaws_le (7→9) and has no entry
  for 8. So on Bond the feeder correctly concludes it has nothing to watch and
  exits after its wait; single-ball play is fine (the game serves, the rig's
  trough answers), but nothing will answer a MULTIBALL eject on this title.
  Item 21b's territory; the fix needs one Bond capture with `PAD_COIL_PROBE=1`
  to say which node group 8 lands on, not a guess.

- **A NON-PIVOT, ordinary-user run of james_bond_60th dies about three frames
  in, every time — and it is not the title's assets or item 45's mask.** Found
  2026-08-14 while verifying item 45. Three runs from `item/45` launched as
  `wsl -e setsid --fork bash … watch.sh` (no `PAD_PIVOT`, running as david) all
  behaved identically: card mounted, tables built, window opened 1445x827,
  `[padglhost] picture: FIRST at frame 4 (4034 of 1044480 pixels are not
  black)`, then the guest's `[thread] #2 RETURNED` / `[thread] #3 RETURNED` and
  a clean exit at 3 frames. The same card in the app's own shape —
  `wsl -u root -e env HOME=/home/david PAD_PIVOT=1 … watch.sh` — runs
  indefinitely. **Two of the three runs were the A and the B of item 45's mask
  (on, and `PAD_DISPLAY_INVERT=1` off), which is how the mask was cleared: both
  died the same way**, so whatever this is, it is upstream of anything item 45
  touched. Worth knowing before it is blamed for something else. Suspect, not
  established: the card FUSE mount without `allow_other` (a non-root run gets
  `user_id=1000` and the guest is root inside the userns), or the same
  clean-exit family as 36b. Untested on any other title, which is the first
  thing to find out — one godzilla_pro run would say whether this is bond or the
  launch mode.

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

## Dropped — off the queue, not fixed

**Removed 2026-08-11 at David's ask** — *"we can remove item 16 and 23"* —
with **19** going too, because its only route was 16's replay engine and it
cannot be started without one. `/next` does not offer anything in this
section, and nothing here counts toward the done percentage.

**The numbers stay retired: 16, 19 and 23 are never reused**, and
`plans/spike2_pc_emulation_handoff.md` still keys its `REMAINING item N`
headings on them.

**Each entry is kept WHOLE rather than summarised, on purpose.** Item 23
carries three distinct measured exit signatures — a byte-identical
pthread NULL-mutex segv with its disassembly and call site, a game-code NULL
deref, and the clean thread-return — plus a repro recipe and preserved crash
logs; item 16 carries shipped work (`145e79b`, `52e3703`) and several
expensive ruled-out results. None of that lives anywhere else in the repo:
the handoff that would otherwise hold it is gitignored and local to this
machine. **Reopening one means moving its block back up to the Queue, not
rewriting it.**

- **DROPPED 2026-08-11.** **23. The game exits by itself mid-play.** `S1 D2` *(**D4 → D2,
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

- **DROPPED 2026-08-11.** **16. Log replay mode: re-run a session's switch inputs from its log.**
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

- **DROPPED 2026-08-11.** **19. Save and load a replay from the game window itself.** `S3 D4` — S3
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

## Done

- [ ] **50 — THIS ENTRY IS NOT DONE. It was moved here on 2026-08-16 and moved
      back out the same day**, when David asked "does it work for TMNT" and the
      answer was no. It is kept in place because everything it records is true
      and was verified; what it got wrong was calling that finished. **The open
      item above is authoritative.** Read this for what is BUILT.
      Branch `item/50`. Two halves, both live-checked.
      **The positional half, which David asked for mid-item** ("if we can show
      them positionally... also showing switches placement... even if we can't
      show the playfield artwork"): the rig filtered every device on the
      LITERAL image name `playfield`, so james_bond_60th_le — which calls the
      same image `Test/scaled_playfield` — had all 138 of its positioned
      devices dropped and was filed as having none. `devicexy.layout_image()`
      now picks the layout by SHAPE (most device classes, then most devices),
      `devicexy.read_table()` reads device_xy.txt so a CARD run needs no ELF,
      artwork is accepted only when its pixel size CONTAINS the coordinates,
      and a title whose art is refused draws on a blank field instead of
      falling all the way to the switch list. **Bond now draws its playfield:
      49 switches (joined 49/49 to live ids at the desk, no run, no rebuild),
      16 coils, 73 lamps.**
      **The swatch-grid half:** `LedGrid` in the Schematic view, roster taken
      from the LIVE RING so it works on the four titles with `0 records` and
      needs no group→node map. `LedRing` is Field's fade/base-layer read moved
      out verbatim so both views decode the wire once. `ledgridtest.py` is the
      offline harness (importing `ledratetest.Feed` rather than writing a
      second one): 12 irregular channels → exactly 12 cells **of the 1536
      addresses that exist**, a roster growing in 4 stages costing 4 canvas
      items, tracking 90→255→0 with a churn control, an a2 pulse returning to
      the BASE layer, a pulse-only lamp still earning a cell, and the centre of
      a dark cell hit-testing to that cell.
      **Verified live:** elvira3 (no `playfield.png` at all) showed `4 of 4
      LEDs lit / 4 LED writes decoded`; godzilla_pro forced in with the new
      `PAD_PF_VIEW=schematic` tracked its attract measured against the ring —
      10 channels changed → 4635 pixels, 36 → 9811, **0 → 0** — and its roster
      reached exactly the 113 channels its table independently says it has.
      **Amended:** `Diagnostics → LED Tests` by name was NOT reached; the
      ring-vs-screen measurement stands in its place, and the tracking title
      has artwork. **Not literally true:** "a title WITH artwork is unchanged" —
      Bond was deliberately moved into the artwork view. Both are spelled out
      in the open-item text above, which is kept for that reason.
      **Found on the way and split out: items 53 and 54.** An adversarial
      review of the branch raised 19 candidate defects, 8 refuted and 4
      confirmed and fixed — two of them regressions this pass introduced (every
      Bond LED tooltip raised `TypeError` on `node=None`; elvira3 was promoted
      into an artwork view with nothing on it, losing 109 clickable switch
      rows).

- [x] **48. The playfield keyboard legend is GODZILLA'S list, so every other
      title gets a legend full of holes and a row named after another game.**
      DONE 2026-08-16, `item/48`, `936836e`. `binds_playfield()` derives the
      playfield legend from the title's own switch_list.txt — fixed keys for
      the universal shots (arrows/F/A/S/Z/X), per-category pool keys for the
      recognisable rest, labels = the switch's own names; Godzilla's compiled
      rows survive only as the no-rig-env debug fallback, and WITHHELD rows
      no longer export at all (a first run shows cabinet-only, never another
      game's dim rows). Verified: `padglhost --binds` desk oracle over all
      EIGHT derived switch lists (jaws gains an upper-right flipper on Down;
      the two all-`?` titles get honest cabinet-only legends); 306 spike2
      tests; one live masked-tables godzilla_pro run through the first-run
      arrival path end to end (table at guest 3.5 s, 21 keys generated,
      trough latch carried across the rebuild, coin x4 + start started a
      real game); and David's own turtles_pro sessions drove keyboard play
      through the derived binds (`+64k/+65k/+34k` on turtles' own ids)
      before his "good to go". Also landed with this branch: the rig-mutex
      non-negotiable (`.pad_rig_lock`) after two sessions ran `/next` at
      once, and the note that godzilla's "no usage detected" tech alert eats
      coins until the flagged switch sees usage.

- [x] **51. star_wars: "UPDATING NODE BOARD RUNTIME / UPDATE FAILED" looped
      over attract and the second display stayed black.** DONE 2026-08-15,
      `item/51` (`7103ba6`..close). **Three stacked faults, none coupled the
      way anyone guessed; both of David's asks verified on screen the same
      evening.** (1) NODE IDENTITY IS THE TITLE'S OWN: each game ELF
      statically declares its node directory; `nbdir.py` derives it
      (reproduces godzilla's measured table EXACTLY — the labelled example),
      watch.sh writes `node_ident.txt`, hwshim consumes it with the old
      godzilla table as fallback, and the census gained the directory as
      weak-branch evidence (star_wars node 2 = Cabinet Lights, the exact
      "no such title is known" hazard, un-silenced). star_wars: update walk
      completed, Guided Setup, CLEAN ATTRACT — no overlay. (2) A VIV-mapped
      FBO attachment had no host storage → guest FBO INCOMPLETE → GL
      silently dropped every LCD draw while the bridge's canned
      CheckFramebufferStatus said COMPLETE; FBOTEX now heals storage-less
      attachments. (3) TWO NAMES, ONE BUFFER: glTexDirectVIV allocates the
      LCD framebuffer under the render-target name, the game Maps the same
      pointer under the sampler name; the bridge now aliases the emitted
      names. `picture: d2 FIRST at frame 2, 102511 lit` — the STAR WARS
      logo in the [display 2] window, screenshot to David. **Rewrites item
      27's record: its 32.8%-black flicker was bright-vs-BLACK; the LCD
      scene had never composed a pixel in this rig.** Regressions:
      godzilla identical (claims byte-equal, node 2 still silent, new paths
      dormant); stranger_things's projector SHOWS SCENE FOOTAGE and its
      wedge shrank to the pinnode trio (split to item 52). Retired: a
      48-re-ask refusal detector (fe ~200/node is the game's normal poll).
      Long form: handoff REMAINING item 51.

- [x] **44. Stranger Things' PROJECTOR picture has nowhere to go.** DONE
      2026-08-15, `item/44`, `a2eafb4`..`e693e4f` (+ close). **The second
      display gets its own texture, window and swap chain.** One new wire op
      (`PADGL_TARGET`, `PADGL_VERSION` 1→2, host-written guest-validated);
      `eglMakeCurrent` stops discarding its draw argument and emits the
      route through the ring; guest FBO 0 resolves per display through
      `map_fbo[0]`; a lazy `[display N]` window presents the second feed, so
      single-display titles are untouched (godzilla_pro verified: one
      surface, zero TARGETs). **The item-27 flicker is structurally gone**:
      the shared window's alternating `2x60 4x60` masks are now one family
      per window (d0 pure `2x`, d2 pure `4x`, star_wars live). 40-agent
      adversarial review: 11 confirmed findings fixed pre-run — the
      DestroyNotify path that KILLED THE RUN on a failed second surface, the
      vsync call landing on the primary after a failed switch, stale
      `cur_tgt` across journal replay among them. **The last hop was a WSLg
      RACE nothing but eyes could see**: swaps succeeded into a swapchain
      nothing composited (backbuffer probe 16/16 lit, swap ok, desktop
      BLACK, David confirming) — creating the EGL surface microseconds
      after `XMapWindow` loses the RAIL realization race; `XSync` + 250 ms
      settle before `eglCreateWindowSurface` fixes it (88.5% lit by a
      now-eyes-validated PrintWindow, solid blue under `PADGL_DEBUG=2`).
      **Caveat, recorded not hidden: no run has yet SHOWN real game content
      in the second window.** star_wars sat on Tech Alerts (its LCD scene is
      dark there — item 27's own measurement — and autoattract never
      cleared it, a separate fault); stranger_things composes an EMPTY
      projector scene while stuck at NODES NOT FOUND (`d2 0x48 no-draw
      0/48`: draws, no video), which is items 29/50's blocker. The pipe is
      proven to the desktop; the picture arrives with the first title that
      reaches attract. Instruments live on: `picture: d2` oracle, per-window
      masks, the self-silencing backbuffer probe, `PAD_GL2_W/H/VSYNC`.

- [x] **26. Right-click-hold a switch to RIP IT, for spinners.** DONE
      2026-08-15, `item/26`, `263a9dc`. Right-hold on any switch marker, in
      both playfield views, now rips: ONE SPIN flag in the shared block (new
      single-writer region `spin_gen`/`spin[256]` at 808/812, `swlayout.sh`
      proves all three copies agree) and `hwshim.c` ALTERNATES the level it
      reports on each scan of that switch's own node while the flag is set —
      a closure per two scans, the wire's maximum by construction, one
      interop call each way (`swspin.py`; the host-pulse alternative caps
      near 6/s). **Live on godzilla_pro, alive.sh 0 after: attract rip
      608 closures in 10.0 s (60/s, node 8 at 120 scans/s); during-play rip
      554 closures in 10.1 s (54/s, node 8 at 109 scans/s) — the first
      during-play per-node scan rate ever measured, and `[swspin] rip END`
      now prints it free on every rip. PAD_SW_PEND agreed EXACTLY: 608 and
      554 game-side `lvl` closures, 100% of the wire's, ending OPEN both
      times.** Found: the game QUEUES edges (entry[+22]) and drains ~1 per
      16.7 ms tick, so a rip fed at 2x that backlogs and coasts after
      release (10 s rip → ~9 s tail; a normal 1 s rip trails under a
      second, which reads as a spinner coasting down, not a defect).
      Offline: swspintest.py ALL PASS, swholdtest.py still ALL PASS. Traps:
      Tk `find_overlapping` treats an unfilled oval as its outline band, so
      synthesised clicks must aim at the ring's STROKE; godzilla_pro wanted
      several `plunge.py coin` before Start took (pricing, not a fault).

- [x] **49. A title's FIRST run could not start a game: with no switch table
      the trough latch fell back to GODZILLA'S ids, and the table was never
      going to arrive because the tables dir was root-poisoned.** DONE
      2026-08-15, `c8cb897` (branch `item/49`). Filed as a captive-ball lead;
      the CONTROL REFUTED IT (84 explicitly open, game started anyway) and
      found the real chain: on a pivot run watch.sh's PASS ONE mktables (root)
      created the per-title tables dir root-owned, PASS TWO (desktop user, the
      one that builds the switch list from the run's own [sw] dump) died on an
      uncaught PermissionError in a log nothing shows, so `switch_list.txt`
      never existed - and padglhost's window-open latch then closed Godzilla's
      66..71, which on Bond are six playfield switches and no trough at all.
      LOCATING PINBALLS was the game being CORRECT about the state it was
      handed. Reproduced both ways pre-fix (hide the table -> search; restore
      it -> game starts). **The fix, one principle - never assert ids you
      cannot name:** watch.sh chowns `$TABLES` between the passes (recursive,
      heals poisoned dirs) and runs the drawable=no branch as_user; mktables
      writes ATOMICALLY (tmp+replace - two 2 s pollers latch on their first
      successful parse of these files) and names every write failure;
      padglhost withholds non-platform rows until `binds_resolve()` parses a
      usable table, polls every 2 s, then resolves, re-exports padbinds and
      latches the title's own trough mid-run (no-rig-env launches keep the
      compiled ids - the gate is for tables that have not arrived, not for
      debug shapes with no rig); padbinds exports withheld rows as '0' and the
      playfield rebuilds its key panel on mtime change; ballfeed waits up to
      `PAD_BALL_TABLE_WAIT_S` (300 s) instead of exiting feederless; swshow
      and plunge label their fallbacks out loud. An adversarial review (five
      lenses) found eight real file-boundary faults, all fixed in `c191609`.
      **Verified live, repeats stated:** the healing run - Bond booted from
      the true poisoned first-run state and reached a STARTED GAME entirely by
      itself (chown healed mid-run, 117 switches written at 12:05, `[padglhost]
      switch list arrived; binds resolved, trough latched on this title's own
      ids`, key panel rebuilt with exactly the six absent rows n/a, swshow on
      72..77 with no banner, PLAYER 1 with no LOCATING PINBALLS) - 1 run;
      godzilla control 2 runs: run 1 exited cleanly mid-Tech-Alerts (the known
      clean-exit family, logged, did not recur), run 2 end-to-end into BALL 1
      with the startup path byte-identical (`bind 6 balls in trough -> 6` at
      start, no gate lines). 2653 tests green; the one recurring red was item
      47's OWN harness beating its 1 ms timer with sleepless update() calls -
      fixed, five-for-five after. Artifacts: `C:/tmp/item49/`. **Left behind,
      recorded in the loose ends:** Bond's TROUGH coil is device-group 8,
      which coilmap cannot map (multiball feeding dead on this title - item
      21b); a HEADLESS run still bakes the shim's own compiled rest-set
      (pre-existing, a shim fix costs every save slot).

- [x] **47. A title's FIRST run showed no switches, because the window read its
      tables once and they land a few seconds later.** DONE 2026-08-14,
      `item/47`. **★ DAVID, on james_bond_60th's first run: "how do we get the
      tables from james bond? without the switches here I can't test it."** The
      tables were complete on disk; only the window did not know. The switch
      list CANNOT exist before a run - the game builds its switch table on the
      heap, so the id behind a name reaches us only as the shim's `[sw]` dump a
      few seconds in - so watch.sh rebuilds in the background with `--wait`
      while the window is already up. Everything deciding what that window shows
      ran ONCE, at construction, so a window that opened a few seconds early
      stayed a paragraph of explanatory text for the whole session. **On a title
      with no usable artwork that paragraph IS the window, so the title's first
      run could not be played** - and Bond is exactly that case: its tables say
      `513 records (coil=16 led=426 switch=71), 0 on the playfield image` and
      its playfield.png is a 202x443 GRAYSCALE thumbnail. **Fix:**
      `poll_for_tables()` in playfield.py - a stat every 2 s, giving up after
      15 min so an abandoned window does not poll forever, then the same two
      branches as construction so a title WITH artwork still gets the artwork
      view. **Verified live against a running emulator** (2026-08-14): the table
      was moved aside, the window relaunched and drew "WAITING for them"
      (`C:/tmp/item47/waiting.png`), the table was put back, and the window
      swapped itself to the full 117-switch schematic with no restart of
      anything (`C:/tmp/item47/arrived.png`). Three real-Tk regression tests
      beside it - a stub root records an `after` that Tk never runs, which is
      the one thing this needed to know.

- [x] **45. james_bond_60th presented its whole picture upside down.** DONE
      2026-08-14, `ecf08d4` (branch `item/45`). **The title says so itself:**
      `/games/data/boot_display_cmd` on the Bond card is 8 bytes holding
      `-invert`, the cabinet's LCD is bolted in upside down, and the game renders
      to suit it — so the emulator was faithfully reproducing a transform a
      desktop monitor must not get. `run_game.sh` now masks that flag by ABSENCE
      inside the private namespace (copy the title's tiny `data/`, drop the flag,
      bind the copy over it), which is the exact state the control titles are in;
      `PAD_DISPLAY_INVERT=1` keeps the machine's own behaviour. **Verified on
      both oracles with matched pairs:** bond attract before = full frame,
      inverted (`C:/tmp/item45/fb_shot_1.png`), after = full frame, right way
      up with the 007 logo back at bottom-right (`fb_after_2.png`), plus the
      window itself (`bond_window_1.png` / `bond_window_after.png`); and the
      godzilla_pro CONTROL unchanged with the mask correctly not firing
      (`gz_control.png`, zero `[run] display:` lines). **Three things worth
      keeping:** (a) **`glshot.sh` is new** — `padglhost` has answered a
      `glshot.req` since the GL journal went in (`padglhost.c:2811`) and nothing
      in the repo could reach it; it writes the screen FBO at fb_w x fb_h, so it
      is the only picture instrument with no window, letterbox or RAIL proxy in
      the path, and it works on a live run with no rebuild. (b) **A mirror is not
      a rotation** — `PAD_GL_FLIP` is `uv.y -> 1-uv.y` and could never have fixed
      this; judge orientation shots on the TEXT. (c) **The file is the switch,
      not a title list**: godzilla_pro and turtles_pro carry the identical code
      path in their own ELFs and ship no such file.

- [x] **17. Keyboard switch input needs holding longer than a keystroke, and
      does not repeat.** `S1 D3`
      DONE 2026-08-13, branch `item/17`, acceptance 20/20 in run 21, and
      **VERIFIED IN DAVID'S OWN RUN** ("this is great and ready to
      release!") — with a side effect he spotted before any instrument
      did: **the playfield LEDs went from ~2 Hz to ~30 Hz**, because the
      same blind bus thread was starving the LED frames to nodes 7/12/14
      exactly as it starved the cabinet poll. Root cause: the game re-ran
      its aux-device init every ~924 ms because three shim replies said
      "never initialized"; see the RUNS 12–21 block below for the chain
      and the fix. *(**D4 → D3 on 2026-08-06:** the
      mechanism is cracked, the instrument is built and validated, and the fault
      now reproduces on demand from a script — so a pass can no longer end
      having learned nothing. What is left needs a run, not a new instrument.)*
      **★★★ MEASURED 2026-08-12 evening, branch `item/17`, godzilla_pro
      service menu (Quick Adjustments), and THE SPLIT IS NOW A NUMBER ON EACH
      SIDE: DELIVERY 20/20, CONSUMPTION 0/20.** A wall-clock flipper ladder
      (switch 59, node 8 — the flippers this item had never measured) at
      100/250/500/1000/2000 ms × 4 rounds, interleaved and jittered, with a
      `shotwin.py` grab after every press: **every press was recorded by the
      game's own scan drain** (`entry[+24]` lvl toggled 20/20; the latch saved
      the five sub-scan closures, waits 185–363 ms) **and the menu cursor
      moved ZERO times, including four 2-second presses.** Full evidence:
      handoff REMAINING item 17; log preserved at
      `/var/tmp/gzwatch_item17_run3.log`, shots `C:\tmp\item17\`.
      **THE CONTROLS, same screen, same run — CORRECTED the same evening
      after the instrument validation caught an over-claim:** Select ×2 and
      Back ×2 at 2000 ms were consumed every time (screen transitions,
      unambiguous), and autoattract's first 2000 ms Back passed Tech Alerts.
      **Service Plus (26) was consumed at NEITHER 800 nor 2000 ms** — the
      value pane read "No" in every shot; the "preview changed" reading in
      this pass's first commit was rendering wobble (diff bbox 51×48 px,
      cyan-mask XOR only 4). So the clean statement is: flippers delivered
      and never consumed; Select/Back consumed at 2 s (nothing shorter was
      tried on them); Plus consumed at nothing — either +/- need edit mode
      entered first (Select = Enter?) or Plus is not reaching the game, and
      its delivery was UNINSTRUMENTED this run (PAD_SW_PEND watched only
      59,60). **Next run must instrument 25–28 and ladder SELECT/BACK
      widths** — they have screen-change oracles that cannot wobble.
      **The scan is NOT the gate for flippers, measured:** node 8's in-menu
      scan gap is ~400–700 ms (latch waits 185–363 ms at uniform phase) —
      same order as the 670 ms attract figure, and presses of 500+ ms were
      sampled naturally yet still ignored. HYPOTHESIS, unproven, the resume
      trail: the menu's consumer runs on its own slow clock or wants K
      consecutive made samples, and something in our word path may drop the
      made bit between rebuilds mid-hold. Read `sw_scan_bytes()`/word-rebuild
      for a dropout before any run (desk-read workflow in flight).
      **RULED OUT this pass — `swpoke.py --tap` for NODE switches:** the tap
      is applied only where the CABINET word is handed over (`hwshim.c:2408+`)
      and its count decrements per cabinet transfer (~640 us each), so a tap
      on a node-8 flipper is a ~N·0.6 ms ghost the node scan never samples and
      the merge never logs. No [sw] edge, no swpend, nothing. The tap docstring
      measurement (Main Menu 0 rows at 120/200 ms, 1–2 at 250, 3 at 300) is a
      CABINET-button measurement and consistent with today's door-button gate.
      **Also fixed on this branch: `alive.sh` bare invocation was broken on
      main tip** (`set -u` + `$PAD_HOME` referenced since 9d25782, padpath.sh
      never sourced → helpers row printed a hollow 0 every time). Sources
      padpath.sh now, like killgame.sh always has. Verified bare-clean.
      **RUN 1 was lost to a collision, recorded for the pattern's sake:** a
      MAIN-CHECKOUT as-root watch.sh (the app's shape) killed it at ~3 min;
      David confirmed the rig free afterwards. Two rig lessons kept: a
      detached watch.sh loses its console unless redirected, and the rootfs
      `games/game` symlink can silently pick the WRONG TITLE for a bare
      `watch.sh` (run 2 came up as turtles_pro — whose flippers are 64/65, not
      59/60 — because item 43 left the symlink there; `PAD_GAME=godzilla_pro`
      pins it).
      **★★★ THE MECHANISM, CRACKED AT THE DESK 2026-08-12 late evening (4-way
      desk-read fan-out over the shim, the run-3 wire log and the game ELF)
      AND THEN PINNED LIVE IN RUN 5. The menu never debounces and never
      slow-polls: a door-button edge becomes a QUEUED EVENT, and the event's
      coroutine (0x23b8f0 → 0x23b4d0) RE-READS the live level (0x1e6d90,
      = entry[+24]) WHEN IT FINALLY RUNS — a press whose release has already
      been drained by then is silently cancelled into a jump table. No
      K-samples constant exists anywhere in the path. The gate is the EVENT
      PUMP'S LATENCY racing the release edge.**
      **MEASURED LIVE, run 5 (godzilla, PEND on 25-28+59,60, log preserved
      `/var/tmp/gzwatch_item17_run5.log`, shots `C:\tmp\item17\bisect\`):**
      **(i) Door-button delivery is FAST and CORRECT** — the drain recorded
      make edges 15–205 ms after the wire on every press, including every
      press the menu ignored (b003: textbook lvl sequence, ~950 ms of
      made-state, ignored). Delivery is dead as a suspect on BOTH transports.
      **(ii) Consumption is a WIDTH-INDEPENDENT ~40% LOTTERY: Minus/Plus in
      the QA value editor, flip-oracle on the game's display — 1200 ms 2/4,
      800 ms 1/4, 500 ms 0/4, 300 ms 2/4, 150 ms 3/4 (8/20 overall).** A
      150 ms press can land and a 2000 ms press can die. So dispatch latency
      is BIMODAL: sometimes <~0.3 s (any press lands), otherwise >~2.5 s
      (even a 2 s press has released → cancelled at the recheck). The felt
      lottery IS the pump's cadence. Run 3's "consumed at 2000 5/5, nothing
      below" was luck plus a too-small sample; corrected by this bisect.
      **(iii) The no-repeat half has its own finding: the held-button
      REPEAT tracker exists in the game (0x23acf0, first repeat after 30
      coroutine ticks, then accelerating) but its arming is gated on the
      service class mask u16@0x7aba5a bit8 — which reads 0 in the rig's
      menu.** Whether real hardware sets it there is open; if yes, that is a
      second, separate rig defect. Also the 30-tick onset at the rig's
      coroutine rate would be tens of seconds — the tick rate is the same
      root problem.
      **(iv) Flippers not moving Quick Adjustments is MACHINE BEHAVIOUR**
      (exactly four door-button records route to the menu tracker; menu
      consumers poll only those four counters). The flipper half of David's
      report lives in OTHER screens — the attract splash literally says
      "HOLD BOTH FLIPPER BUTTONS FOR MENU", and battle select is in-game.
      **Addresses (godzilla_pro 1.15.0, verified against the live ELF):**
      recorder 0x1e78f4, drain 0x1e7540 (parity rule on entry[+22]), event
      post 0x2551dc, thunk 0x23b8f0, press fn 0x23b4d0 (recheck at
      0x23b510), tracker ctor 0x23acf0, tracker globals 0x7b130c/1320/
      133c/1350, event pool 0x7b7e80, current-event 0x7b7e84, scheduler ctx
      0x7b7e8c, class mask 0x7aba5a. Full chain + evidence: handoff.
      **RUN HYGIENE, two more collisions this evening, both recorded so the
      next pass survives them:** a turtles CARD run (PIVOT, 120-min backstop,
      launched ~19:55 through MY worktree's scripts by something that was not
      me — possibly item 46's session; no worktree of its own) collided with
      run 4; my own alive.sh check had tail-1'd the MOUNT line and missed the
      live guest above it. **Gate on `alive.sh --total` (the number-only
      form), never on eyeballing the table.** Both runs killed with David's
      explicit OK; also /proc reads against pgrep's FIRST match had been
      reading the WRONG GUEST's memory — doortrack.py now needs a
      per-game pgrep or a PID argument before anyone trusts it again.
      **New tools on this branch:** `doortrack.py` (tracker watcher, ~100 Hz
      /proc poller — needs root for ptrace scope), `menuprobe.py` (cyan-mask
      screen oracle, positive example now exists: run5 `plus800.png`-era "No"
      vs `run5_afterplus.png` "Yes").
      **★★★ RUN 6, 2026-08-12 late night — THE CADENCE IS MEASURED, THE
      SCHEDULER IS EXONERATED, AND EVERY RUN-5 /proc CLAIM IS RETRACTED.
      Method change that did it: stop dereferencing desk-read addresses and
      diff the ENTIRE 12.6MB rw window around timestamped presses
      (`bigdiff.py`, the item-43 causal method applied to time). The 12.6MB
      window preads in 9ms; a menu screen idles at ~120 changed words/s, so
      press-correlated words stand out like flares.**
      **(i) THE ADDRESS MYSTERY IS SOLVED, and the desk read is VINDICATED
      (2026-08-13 correction of run 6's own first diagnosis, which said
      "one nibble off" — wrong): qemu-user loads this binary with
      GUEST_BASE = +0x10000. Live /proc addresses = ELF address + 0x10000
      (visible in /proc/<pid>/maps all along: text mapped at 0x18000, ELF
      links at 0x8000). The live scheduler block 0x7C7E80 IS the desk
      read's 0x7b7e80; the 60Hz word live at 0x7f6658 IS its generation
      counter 0x7e6658. Run 5 read RAW ELF addresses without the shift —
      that is the whole reason its "no tracker movement" and "mask bit8=0"
      claims were garbage. EVERY /proc read of this guest must add
      0x10000; guestmem/pumpwatch/bigdiff users beware.**
      **(ii) Delivery, exonerated a third way: every press lands in the
      door-switch LEVEL WORD 0x852108 (active-low, bit = id−17: Select=8,
      Plus=9, Minus=10) 60–145 ms after the wire, every time, including
      every press the menu ignored.**
      **(iii) The scheduler thread NEVER stalls. Pass counter = scheduler
      block+0x1c = 0x7c7e9c, and it ran at exactly 60.0 Hz through every
      deaf period (measured across four windows incl. a 29 s one). The
      four-agent ELF read (workflow, this pass) mapped the engine: one
      scheduler THREAD (loop 0x254ca8) waits on a 60 Hz SIGEV_THREAD POSIX
      timer (notify 0x3b92bc, period 16,666,667 ns), each pass runs the
      tick body 0x4ec828 (pump 0x2a3744 at +0x88, drain 0x1e7540) then
      walks the event ring swapcontext-ing into due events; missed ticks
      are latched away, never replayed. Timer-starvation was the leading
      theory and it is DEAD — the beat is perfect.**
      **(iv) What actually happens — measured end to end: a press becomes
      an event and the event's DISPATCH is bimodal. Awake: dispatch lands
      60–230 ms after the level write and EVERY press consumes — a 12-press
      300 ms train consumed 6/6 during awake stretches, and a 10 s hold
      auto-repeated at full speed (first repeat ~470 ms → coroutine tick ≈
      60 Hz; the "does not repeat" half is the SAME defect, not a mask).
      Deaf: dispatch arrives 1.3–5.3 s late, the press fn's recheck
      (0x23b4d0) finds the button released, and the event dies with a
      visible cancel signature (edit-pane busy words 0x7c90b4/0x7c9174
      cycle, value 0x7c908c does NOT flip) — a 6-press burst at 1.2 s gaps
      died 6/6 that way, each event dispatching around the NEXT press's
      edge. Deaf and awake come in multi-second STRETCHES (observed 5.3 s
      and 29 s deaf; awake runs of 4+ presses), which is why run 5 read a
      width-independent "~40% lottery": the lottery is the duty cycle.**
      **(v) The screen lags memory: two presses flipped the value in memory
      within 150 ms and the display still showed the old value 2.9 s later.
      menuprobe-negative ≠ not-consumed; memory is the oracle now.**
      **(vi) Event objects live OUTSIDE .data — one 0x145000 malloc
      (64×320 B events + 64×20 KB stacks) mmapped near 0xbaa00000, so
      bigdiff's window sees the globals (ring head 0x7c7e80, current
      0x7c7e84, LIFO freelist 0x7c7f54) but not the nodes; the LIFO head
      restores itself across single-event transactions, so only bursts
      visibly churn it.**
      **THE ONE REMAINING QUESTION, sharp: what gates posting/dispatch for
      seconds while passes run at 60 Hz? PRIME SUSPECT (fits everything):
      the tick-body VETO — hook chain id 0x37/55 at entry to 0x4ec828
      (dispatcher 0x4bb42c, table ELF 0x7e4d48 = live 0x7f4d48): a
      subscriber returning 0 skips pump AND drain for the pass, so edges
      pile up in the recorder (events post only when the veto lifts —
      matching the wake-drain cancel bursts), the pump's timer slots
      freeze (matching the blink freezing), yet the ring walker keeps
      running (matching pass counter 60 Hz). Alternative: the drain posts
      events with a delay/flags variant during those stretches (per-event
      +0x88 countdown, flags bit 0x40, half-rate parity skip). The gate
      hunt over run-6 data found NO stored flag constant-per-stretch, so
      the veto condition is likely COMPUTED per pass (or heap state).**
      **Instrument notes, so nobody re-pays:** `bigdiff.py` (NEW, the
      workhorse), `pumpwatch.py` (NEW, region watcher — now pointed at live
      addresses), doortrack.py pgrep defect fixed (explicit PID/game arg).
      PAD_SW_PEND emitted nothing to the run-6 console because watch.sh's
      forward filter dropped [swpend]/[swlatch] — FIXED on this branch
      (watch.sh:1304). The "bigdiff gap" was NOT a bigdiff bug: the
      analysis copy was made MID-RUN (~+143 s) and every "gap" symptom was
      the truncation — rule: never analyze a copy taken before the `done`
      line; the preserved original (9036 lines) is complete and RE-CONFIRMS
      stall-3: zero engine-word events +118 s→+325 s, p11/p12 never
      processed, pane coroutine frozen ≥207 s. threadwatch.py (scratchpad)
      dies on transient-tid races — the guest churns short-lived threads
      constantly (per-expiration SIGEV threads).
      Logs preserved: /var/tmp/*_run6*_preserved.log + C:\tmp\item17\run6\
      (bigdiff_run6_full.log is the complete copy; bigdiff_run6.log there
      is the truncated mid-run copy, kept as the cautionary artifact).
      **★★★ RUN 7, 2026-08-13 — ALL FOUR CANDIDATE GATES KILLED IN ONE
      CAPTURE (gatewatch.py, the synthesis's discriminator; report at
      C:\tmp\item17\run6\gate_workflow_report.txt; logs C:\tmp\item17\
      run7\).** 16-press train, 8 consumed / 6 fully deaf / 2 wake-drain
      (p5, p15: busy cycles + event alloc at their OWN edges, no value
      flip — the backlog-cancel signature again, edge-correlated wakes
      reconfirmed). Verdicts: **(F4) freelist never pinned** (LIFO head
      toggling normally through everything). **(F1 parity and F3 mask)
      their gate variables NEVER CHANGED ONCE across five deaf↔awake
      transitions** — a stretch-gate must flip at each boundary; both
      dead (the mask at live 0x7bba5a — its first real read ever — is
      static). **(F2 hook-0x37 tick-body veto) dead twice over: the
      chain's single node is a HEAP node with callback=0 (an
      unregister-in-place), and a 50 Hz watch of slot+node through 8
      more presses caught NO re-arm — the chain cannot veto, ever, in
      this build's runtime state.** Yet the freeze phenomenology stands:
      fully-deaf presses produce ZERO body-side activity (no decoder
      busy, no value, no event alloc) while the pass loop runs. With
      every entry-gate dead, the coherent survivor is a TIMEBASE FREEZE:
      the body runs but an early callee's elapsed-ticks/dt computes 0,
      so decoder/display/drain all no-op "for no time having passed" —
      which would also explain edge-correlated wakes if input touches
      the clock path. Two agents out (2026-08-13): (i) disassemble early
      body callees 0x20fb28/0x519530/0x3ba53c/0x4ed698/0x46b478 for the
      timebase globals; (ii) identify block+0x1c's writer (the
      60Hz-through-freezes proof rests on it). Run-6 data cross-check:
      no monotonic awake-only accumulator exists in .data — the dt state
      is heap or register-local, so the agent read is the path.**
      **★★★ RUN 7b, 2026-08-13 — TIMEBASE, PRODUCER-STARVATION, AND
      CLOCK-STALL ALL FALSIFIED TOO. The desk read (agent) proved the
      tick body computes NO dt/elapsed — it calls each subsystem once
      per pass unconditionally; the frozen subsystems are cross-thread
      QUEUE-DRAINS (switch producer list ELF 0x7aa9b8 / live 0x7ba9b8;
      pump queue 0x7c8a94/98). So the timebase theory is dead. Then
      queuewatch.py + threadwatch2.py tested the producer-starvation
      successor LIVE and killed it too:**
      **(i) NO THREAD STARVES. All 20 guest threads burned identical
      CPU across deaf and consumed press windows (utime deltas equal to
      the tick). Kernel-stack snapshots during a deaf stretch: every
      thread parked in futex/nanosleep/poll/select as normal, none
      wedged in an ioctl/read. (Caveat: CPU is dominated by two ~6%
      SoLoud audio mixers, tids 225818/226738; the scheduler thread
      225755 is near-zero CPU because it cond-waits the 60Hz timer, so
      this test is weak FOR the scheduler specifically — but it decisively
      kills "a producer thread wedged in the shim".)**
      **(ii) EDGE ENQUEUE DOES NOT PREDICT CONSUMPTION. The switch
      producer list head 0x7ba9b8 fired (edge recorded) on several DEAF
      presses (TP01, TP04) and stayed quiet on others — no correlation
      with whether the pane responded. So the recorder works and the
      drain has edges to drain even when the press dies: the drop is
      DOWNSTREAM of the producer list, in event post→dispatch→recheck.**
      **(iii) CLOCK-STALL DEAD. The input-service thread (entry ELF
      0x1d7e9c) runs its own ~100Hz scan loop gated on 1f1a3c =
      clock_gettime(CLOCK_MONOTONIC) with a 9ms step; but that is the
      SAME clock family as the SIGEV timer we proved ticks a perfect
      60Hz, so the guest clock is healthy. block+0x1c's 60Hz was
      re-confirmed loop-thread-written (agent, by elimination: the timer
      notify 0x3b92bc touches ONLY 0x7e6658), so "pass loop alive" holds.**
      **WHERE IT NOW LIVES — one window, three branches: the press is
      recorded and drained, but between the drain's event POST (0x2551dc)
      and the coroutine RECHECK (0x23b4d0 via game-side getter 0x1e6d90,
      which reads a SEPARATE snapshot behind pointer globals 0x7e43d8/
      0x7a958c — NOT the raw bitmap) something drops it in multi-second
      bands. Run 8 must watch, together, through a press train: event
      ring head/current (0x7c7e80/84), retire pointer 0x9dc54c, and the
      game-side snapshot (deref [0x7b958c]) — to split deaf presses into
      (a) event never posted, (b) posted but never dispatched, (c)
      dispatched but cancelled at recheck. Each branch has a different
      fix; that trichotomy is the whole remaining question.**
      *(ANSWERED — see RUN 8 below: (b) is empty, (a) is the defect, and
      it turned out to sit upstream of the drain entirely. The one claim
      in this paragraph that did not survive is "the press is recorded":
      on a dead press it is not.)*
      **★★★ RUN 8 + 8b, 2026-08-13 — THE TRICHOTOMY IS ANSWERED AND THE
      DEFECT MOVED UPSTREAM OF EVERYTHING RUNS 5–7b WERE WATCHING.
      `ringwatch.py` (NEW) follows the ring/freelist pointers into the
      HEAP, so the 64 event nodes — invisible to every previous watcher,
      because the pool is one 0x145000 malloc outside .data — are diffed
      directly. 24-press train, then a 16-press confirming train.**
      **(i) BRANCH (b) IS EMPTY. Nothing is ever posted-and-left-
      undispatched: on every press that posts, the freelist pop, the ring
      head move, the node write and the pane busy words land in the SAME
      5 ms sample. There is no dispatch latency — which retires the whole
      "event pump cadence / bimodal dispatch" framing runs 5 and 6 built.**
      **(ii) THE SPLIT, run 8 (24 presses): 12 CONSUMED, 3 dispatched-then-
      cancelled (c), 9 nothing-at-all (a). Run 8b (16 presses): 10 / 0 / 6.
      Same ~60/40 either way, and the ~40% "lottery" is now located.**
      **(iii) (a) IS THE DEFECT, AND IT IS FURTHER UPSTREAM THAN (a) WAS
      DEFINED. On a dead press the switch-entry PENDING COUNT (+0x16)
      never increments, so THE RECORDER NEVER RAN. The drain, the post,
      the ring walker and the coroutine recheck are all innocent — they
      were never handed anything. On live presses +0x16, the debounced
      level +0x18 and the producer head all move in one sample, 93–348 ms
      after the wire.**
      **(iv) ★★ FIVE RUNS OF "DELIVERY IS 20/20, 24/24" WERE MEASURING THE
      WRONG WORD. 0x852108 is the DEVICE-LEVEL word, and it carries a
      textbook ~300 ms closure 16/16 — on dead presses exactly as on live
      ones (`0f→0d` for Plus, `0f→0b` for Minus, back 300 ms later). The
      game's real switch layer is `*(0x7b958c) + id*32`, stride 32 proven
      three ways in the disassembly AND independently by hwshim.c's own
      probe (`st + id*32`, `pend = *(u16*)(e+22)`, `lvl = e[24]`). That
      array sees only 10/16. So "delivery is dead as a suspect" was true
      of the device word and false of the game.**
      **(v) THE SHIM'S OWN PROBE SEPARATES THEM PERFECTLY, 6/6 vs 10/10,
      and it is OUR structure it disagrees on: live presses log the full
      `cur 1→0, pend 1, lvl 1→0` sequence out of `SW_NODEREC(node)`; dead
      presses log exactly two lines, `cur=1` at the press and `cur=1` at
      +305 ms, i.e. the closure never appears in the shim's node record at
      all. Note the probe is change-gated, so this corroborates rather
      than proves on its own — ringwatch's unconditional 200 Hz sampling
      of +0x16 is the load-bearing evidence.**
      **WHERE IT NOW LIVES: between the device-level word and the game's
      switch-entry array — the node-record merge / cabinet handover the
      SHIM performs for ids 25–28. `sw_owed[]` (979b940) latches a closure
      against the NODE scan; this cabinet path evidently is not covered by
      it, which is exactly why the latch never cured the felt case. RUN 9:
      trace the shim side unconditionally (PAD_SW_PEND's change-gating can
      hide a complete +1/−1 cycle), find what paces the cabinet handover,
      and extend the latch to it. Fix shape is the release-defer that has
      been this item's fallback all along — now with a measured target.**
      **A SECOND ADDRESS TRAP, found and fixed here: a pointer VALUE read
      out of guest memory is a GUEST address and needs +0x10000 too.
      gatewatch.py's DEREF_REGIONS did NOT add it, so run 7's `parity` and
      `snap` regions were 0x10000 low — which is why they "never changed
      once". RUN 7's F1 (ring parity) VERDICT IS THEREFORE REOPENED; it
      rests on a bad read. Its F2/F3/F4 verdicts used static regions and
      stand. ringwatch.py has a `deref()` helper that carries the rule.**
      **The disassembly that made run 8 readable (agent, desk work, report
      at `C:\tmp\item17\run8\drain_ring_report.txt`): the drain 0x1e7540
      has FIVE ways an entry in the list fails to reach the post — two
      descriptor flag bits (0x0800 press / 0x0400 release at desc+0x1a),
      the global category mask 0x7aba5a acting as a strict whitelist when
      nonzero, a null entry function at desc+0, and a SILENT freelist
      exhaustion (0x2551dc returns NULL, pool hard-capped at 64 nodes, no
      retry — the edge is gone forever). Event nodes are 320 B, countdown
      at +0x88, flags at +0x02 with bit 0x40 = suspended-and-skipped. The
      menu handler 0x23b4d0 also has two undocumented early exits gating
      on switches 3 and 4 read from a SECOND bitmap `*(0x7b93a0)` — the
      likeliest home of the (c) minority. None of these fire on the (a)
      path, because the drain never sees the edge.**
      **★★★ RUN 9, 2026-08-13 — THE CHAIN IS COMPLETE, END TO END, AND THE
      ONE LOSSY LINK IS NAMED. `SW_NODEREC(n)` in hwshim.c is
      `SW_STRUCT + 16 + n*160` off the ADDRESS of the pointer global, not
      its value — so node 0's record is the STATIC live 0x7b959c (prev
      bitmap +0x0c, cur bitmap +0x14), which no watcher had ever sampled.
      The disassembly says the same thing independently (the drain reads
      `0x7a958c + board*160 + 36`). Adding it to ringwatch splits the last
      ambiguity. 20 presses, 300 ms:**
      ```
      shim wire (devbuf 0x852100) ......... 20/20   +87..+103 ms
      game decode (NodeRec.cur 0x7b95b1) .. 12/20   <-- THE ONLY LOSS
      recorder (entry +0x16) .............. 12/12   same sample as cur
      value word 0x7c908c ................. 10/12
      ```
      **Decoded-but-not-recorded is ZERO: every closure the game decodes,
      it records, in the same 5 ms sample. So the recorder, the drain, the
      post, the ring and the recheck are all exonerated — the entire
      remaining defect is that 8 of 20 closures NEVER REACH NodeRec.cur.**
      **AND THE SHIM HELD THE BIT DOWN THE WHOLE TIME, from its own log:
      `[cabchg] ff0f0f… → ff0b0f…` and back **303 ms** later; the next
      press `ff0d0f…` for **302 ms**. Run 8b's `[swpend]` says the same
      thing per press (`sent=0` for the full closure on presses the game
      never saw). The cabinet word is rebuilt on the merge generation
      (`sw_shm_gen()` = `gen + scr_gen`, so a script press bumps it
      immediately) and the SPI stub copies `bits` into the rx buffer of
      every message on EVERY `SPI_IOC_MESSAGE` — paced to ~640 us, i.e.
      ~470 transfers during a 300 ms closure. The game had the made bit
      handed to it hundreds of times and took it 12/20.**
      **SO IT IS NOT A SAMPLING RACE ON EITHER SIDE, and the latch cannot
      help: `sw_owed[]` extends a closure the game already fails to read
      when it is continuously present. (Worth keeping in view anyway: the
      latch counts down inside `sw_scan_bytes`, i.e. per REBUILD, and for
      the cabinet a rebuild fires on the release itself — so an owed
      cabinet closure can be spent microseconds after release, before the
      game looks. That is a second, real defect on the same path; the tap
      path already learned this lesson and applies at the handover.)**
      **RUN 9 FOLLOW-UP ANALYSIS (free, on the captured log):**
      **(a) The node record is WHOLLY untouched on a dead press — neither
      `cur` (0x7b95b1) nor `prev` (0x7b95a9) moves. 24 changes each over
      the run = exactly 12 presses × 2 edges. So the decode does not run
      and then decline to apply; it does not run.**
      **(b) The pass counter is 60.0/s across EVERY deaf window (heartbeat
      `pass=`, 16 beats, no deviation). Fourth independent confirmation —
      the scheduler is not the problem and never was.**
      **(c) NOT PERIODIC. Run 9's deaf windows (8–11 s, 24–30 s, 44–49 s)
      look like a ~16–19 s cycle, and that is a coincidence of a 20-press
      sample: runs 8 and 8b give start-to-start spacings of 6–24 s with no
      common period. Written down because the near-match to the 5.2 s /
      16.5 s yield-loop constants in 0x255448 is exactly the kind of
      false lead that costs a pass. A ~16 s heartbeat word does NOT exist
      in .data either — a scan of run 6's full 12.6 MB window for
      addresses changing regularly every 8–28 s returns one weak
      candidate (0x9b7bd4, cv 0.45, gaps 4.6–35.4 s), i.e. nothing.**
      **(d) A READING TO AVOID, recorded because I nearly published it:
      comparing "which regions were active" in deaf vs live windows shows
      pane/ev/entries/noderec at zero during deaf windows and busy during
      live ones — which looks like a whole-engine freeze and is CIRCULAR.
      Those regions are driven BY the press; in a window where no press
      registered, of course they are quiet. The only non-circular reading
      is (b): the 60 Hz machinery keeps running, and the guest's overall
      change rate never drops (245–505 words/s throughout).**
      **★★★ AND THEN THE ACTUAL ROOT CAUSE, from the run-9 log plus a desk
      read of hwshim.c — no further run needed. THE LATCH NEVER ARMS FOR
      CABINET SWITCHES, and the reason is one line.**
      **(1) Evidence first: ZERO `[swlatch]` lines in a 20-press run. The
      latch (979b940) did not fire once. Every other gate is static too —
      `rgate`, `mgate` and the category `mask` recorded 0 changes across
      90 s, and entry+0x1a (the recorder's per-switch swallow gate) never
      moves. Only +0x04, +0x16 and +0x18 move, and devbuf moves exactly
      40 times = 20 presses × 2 edges.**
      **(2) The mechanism. In `sw_scan_bytes()` the `else if (held)` arm
      sets `sw_served[id] = 1` — "this switch has been on the wire as
      made". For a NODE switch that is sound, because `sw_scan_bytes(nid)`
      is called when the GAME asks for that node, so on-the-wire ≈
      consumed. For the CABINET it is false: `sw_scan_bytes(0, bits)` is
      called on the shim's own REBUILD, which fires within ~640 us of the
      press (the rebuild condition includes `sw_shm_gen()` = `gen +
      scr_gen`, so a script press bumps it at once). So `sw_served[26]` is
      set microseconds after the press, and at release `sw_shm_merge()`'s
      `else if (!sw_served[n] && sw_latch_on())` is false and NOTHING IS
      EVER OWED. The latch is dead code on this path.**
      **(3) A second defect behind it, so the obvious one-line fix is not
      enough: `sw_owed[]` is also DECREMENTED inside `sw_scan_bytes`, i.e.
      per rebuild — and a cabinet rebuild fires on the release itself. Arm
      the latch without moving the count and it would be spent
      microseconds later, still before the game looks. The tap path
      already learned this and applies its count where the word is handed
      over ("the only place a press can be counted in transfers").**
      **(4) BUT THE HANDOVER IS NOT THE RIGHT CLOCK EITHER, and this is
      the part that is genuinely new. The game takes the word on every
      `SPI_IOC_MESSAGE` (~1560/s, paced 640 us) but only FORWARDS it to
      the recorder every ~500 ms: hwshim.c's own header says the reader
      thread copies rx into 0x842108 and `0x5a9df8` then hands those 8
      bytes to `0x1e78f4(0, buf)` — the same distributor the node bus
      feeds. Counting transfers would spend the latch in under a
      millisecond. THE CABINET NEEDS A WALL-CLOCK HOLD.**
      **(5) THE ~500 ms IS MEASURED, not guessed. 300 ms presses are
      captured 12/20 = 60%, and for a fixed-period poll of period T with
      uniform phase the capture rate is 300/T, giving T ≈ 500 ms. The
      latencies from the device word to the node record on the 12 captured
      presses are 0, 4, 4, 4, 10, 11, 51, 84, 127, 183, 240, 269 ms — a
      spread across 0..~270 with no clustering at a fixed offset, which is
      the signature of sampling a slow poll, not of a gate. It also
      retro-explains every historical observation at once: 2000 ms always
      registers (2000 > 500), 250–500 ms "falls between polls" (item 43's
      turtles pass said exactly this on 2026-08-11), and the 72/72 ladder
      passed because it measured a word the poll is not on.**
      **THE FIX, now fully specified: defer the cabinet RELEASE edge in
      `bits` by at least one poll period (~600 ms), keyed on wall clock,
      independent of both the rebuild count and the transfer count. That
      is this item's long-standing release-defer fallback, and it is now
      the fix with a measured constant behind it. Acceptance unchanged:
      an ordinary sub-second press acts EVERY time over N≥10.**
      **STILL OPEN, and worth one desk read before coding: whether the
      ~500 ms cabinet service interval is the game's own design or
      something the rig imposes (node 0 is serviced out of the same
      `nb_next_node()` schedule the shim owns). If the rig is what makes
      it 500 ms, fixing the schedule beats papering over it with a hold.**
      **★★★ RUN 10, 2026-08-13 — THE SPI REPLY IS EXONERATED BY
      DISASSEMBLY, AND THE GATE IS NAMED. Desk read (agent; report at
      `C:\tmp\item17\run10\spi_decode_report.txt`; it died mid-write on an
      API error but the report is complete, and its ELF addresses check out
      against run 9's live measurements — its LIVE column does not, it
      added 0x1000 instead of 0x10000 for the 0x7a9xxx family, so trust
      the ELF values only).**
      **(i) MY PROTOCOL-FIDELITY HYPOTHESIS IS DEAD, with proof. The
      cabinet SPI path is a dumb pipe: the reader stores all 8 reply bytes
      raw and unconditionally (0x5a9c6c), no reply byte is metadata, and
      `0x1e78f4` writes NodeRec.cur with an UNCONDITIONAL `strb` at
      0x1e7988 after snapshotting prev at 0x1e7974. There is no change
      flag, no sequence compare, no checksum and no state machine. The
      rol8-XOR scramble from the earlier pass is real but lives on the
      NODE BUS (0x59ef60) and never touches the cabinet. So our constant
      bytes cannot be the intermittency.**
      **(ii) THE ONE GATE THAT EXISTS: the cabinet IS node 0 (0x1d6da0),
      and `0x1d6d58` — the only path from the SPI word to NodeRec.cur —
      has NO gate at all. But the runtime sweep 0x1d7d88 opens with a
      node-bus query at 0x59ef30 and RETURNS IMMEDIATELY if it comes back
      negative (0x1d7da0), and node 0 is the sweep's TERMINATOR: it is
      serviced once per sweep and only when the query finally yields 0.
      So the cabinet is read only as a side effect of a successful
      node-bus poll. Other callers exist and matter: `delay(ms)`
      (0x1d6f64) polls the cabinet every 16 ms while it sleeps, which is
      probably why some phases feel fine.**
      **(iii) TESTED IT AND THE OBVIOUS VERSION IS WRONG. I instrumented
      `nb_next_node()` (PAD_NB_SWEEP=1, committed) expecting to show that
      emitting the whole node list before the terminating zero divides the
      cabinet poll rate by the board count. The run produced ZERO
      `[nbsweep]` lines — and zero `[nbsched]` lines, which pre-date this
      pass — so that branch is never reached and the schedule is not what
      paces the cabinet here. Most likely `nb_nnodes == 0`, taking the
      early return, in which case every poll already answers 0 and the
      cabinet is serviced every sweep. EITHER WAY the "our node schedule
      starves node 0" theory is dead, and so is the plan to fix the
      schedule. The `[nbsched]` 1024-poll summary also never printed, so
      the game issued fewer than 1024 `00` polls in ~2 minutes — under
      ~9 Hz — which is itself consistent with a slow sweep.**
      **RUN 11, THE INSTRUMENT THAT SETTLES IT, and it is cheap: put a
      monotonic COUNTER in an unused cabinet reply byte (byte 7 — which
      the report says we should be sending as 0xff anyway, see (iv)).
      NodeRec.cur byte 7 then records the counter value AT EVERY POLL, so
      ringwatch's log of that one byte gives both the poll TIMES and, from
      the deltas, how many SPI transfers passed between polls. That
      measures the cabinet service rate directly instead of inferring it
      from capture rates, and it needs no guest instrumentation.**
      **(iv) A REAL BUG FOUND IN PASSING, on correctness not
      intermittency: the bus is ACTIVE LOW and we send bytes 3–7 as 0x00,
      which asserts FORTY permanently-closed switches; the high nibbles of
      bytes 1 and 2 assert eight more. Idle should be 0xff. Byte 2 bits
      2–3 are a quadrature encoder (0x5a9ac0) and must be held at a valid
      Gray-code pair rather than flipped blindly. Worth fixing on its own
      merits, and it must NOT be bundled with the latency fix — separate
      change, separate verification.**
      **★★★ RUN 11, 2026-08-13 — THE POLL RATE IS MEASURED, AND THE LOSS
      RATE FALLS OUT OF IT TO WITHIN ONE PERCENT. New instrument
      (`PAD_CAB_PROBE=1`, hwshim.c, default off): stamp a 16-bit transfer
      counter into cabinet reply bytes 6 and 7. The game copies the reply
      into NodeRec.cur unconditionally, so cur[6..7] records the counter
      AS OF EACH POLL — every change is one poll, its timestamp is the
      poll time, the delta is the transfers in between. Safe because bits
      48–63 carry no node-0 switch (our builder never sets a bit above 23;
      the idle word is `ff 0f 0f 00 00 00 00 00`) and the decoder drops
      changed bits whose switch id is 0.**
      **THE CABINET IS NOT POLLED SLOWLY. IT IS POLLED IN BURSTS:**
      ```
      median gap   9-10 ms   (~100 Hz while it is polling)
      p90 gap      11-12 ms
      MAX gap      ~690 ms   and there are several per 5 s window
      ```
      **In 4.6 s of capture: ~150 polls at ~9 ms (1.35 s of it) plus five
      gaps of 683–690 ms (3.45 s of it). So the duty cycle is roughly
      0.3 s of polling then a ~0.69 s blind gap, on a ~1 s cycle.**
      **THE ARITHMETIC CLOSES THE CASE. A 300 ms press is lost only if it
      falls ENTIRELY inside a blind gap, i.e. if it starts in the first
      (690 − 300) = 390 ms of a 1 s cycle → 39% loss, 61% capture.
      MEASURED CAPTURE WAS 12/20 = 60%. Nothing else needs to be true.**
      **AND IT IS NOT MENU-SPECIFIC: attract and the service menu give the
      same numbers (32.4/s vs 31.2/s, median 9 vs 10 ms, max 690 vs
      693 ms). So the flipper complaints in attract and item 46's turtles
      Action Button are very probably THIS, not three separate faults.**
      **WHAT IS LEFT IS ONE QUESTION: what blocks the cabinet poll for
      ~690 ms at a time? The sweep reaches node 0 only after a node-bus
      serial round trip (0x59ef30 → 0x59ebac → 0x59d824: write@plt,
      read@plt, tcflush on the fd at 0x70a474), so the prime suspect is
      OUR emulated serial read blocking or timing out. Instrument the
      shim's node-bus read path with entry/exit timestamps and find the
      ~690 ms. If it is ours, this is a real fix and not a hold.**
      **Instrument note: ringwatch AUTOSUPPRESSED the probe bytes after
      150 changes and cost run 11 forty of its forty-five seconds — the
      watcher silenced the very thing being measured. Fixed on the branch
      with a NEVER_SUPPRESS list; the numbers above come from the first
      ~4.7 s, which is why the spans are short.**
      **RUN 10's second question, kept because the deferral
      does not answer it:
      what does the game require of the cabinet reply before it decodes
      it? Byte 0 of our word is a constant `ff` and bytes 3–7 constant
      zero; if the real board carries a change flag, a sequence/frame
      counter or a checksum there, a constant makes the game skip the
      decode, and 60/40 is what "skip unless something else says so"
      looks like. Read the game's SPI reply consumer (the 0x5a9b60 loop
      and whatever it feeds) and compare against what `sw_prime()` and
      the `[cabspi]` copy actually put in the buffer. Same shape as item
      43: one global answer standing in for a per-frame protocol.**
      **New tools on branch: `ringwatch.py` (the run-8 instrument, and the
      first watcher that can see the event pool at all), queuewatch.py +
      threadwatch2.py. gatewatch.py committed. Logs preserved
      /var/tmp/*_run7*_preserved.log + C:\tmp\item17\run7\ (gate report,
      gatewatch/queuewatch/threadwatch2/console); run 8 at
      /var/tmp/*_run8*_preserved.log + C:\tmp\item17\run8\ (ringwatch
      run8 + run8b, manifests, console, drain_ring_report.txt, nav shots).
      Shim mitigation (release-defer) is no longer the fallback — it is
      the fix, now that the cabinet handover is the measured target.
      Acceptance unchanged: ordinary sub-second press acts EVERY time
      over N≥10, oracle = MEMORY (value word live 0x7c908c), display as
      the human check.**
      **★★★ RUNS 12–21, 2026-08-13 — ROOT CAUSE FOUND, FIXED, ACCEPTANCE
      20/20. The ~690 ms blind windows were the game RE-RUNNING ITS AUX
      DEVICE INIT every ~924 ms, forever, on the bus service thread, and
      the fix is three crafted replies in the shim's device models
      (PAD_I2C_READY=0 restores all three).**
      **The full causal chain, each link measured:**
      **(1) Run 12 (PAD_NB_TRACE=2): 163 of 163 blind windows bracketed
      by the same broadcasts — `0a 0a 070101 080101` … 681±3 ms …
      `0b0106`, period ~924 ms. Node-2 silence was NOT it: every
      [nbsilent] train sits in the first 20 s (bring-up + grading), and
      the run-12 join's 16 "matches" were mod-2^16 counter collisions.**
      **(2) Runs 13–14 (PAD_OPEN_LOG + PAD_I2C_LOG, both new t=-stamped):
      100% of steady-state /dev/i2c-1 traffic sits INSIDE the windows —
      exactly 250 poll-pairs per window of register 0x24 from i2c slaves
      0x0a and 0x2a. The window = 250 × (usleep(1000) + open + paced
      transfers + close) ≈ 681 ms.**
      **(3) The game side, disassembled: 0x1fa9c8 pulses the reset lines
      (the 07/08 broadcasts ride along) then polls reg 0x24 of both MCUs
      up to 250 times for the value 0x0111 (#250 and #0x111 are literals
      in the loop). Success: usleep(750000) once + 0x1fa8c0 programs a
      register table — WHICH INCLUDES reg 0x24 itself (run value 0x0020
      into 0x0a, 0x0022 into 0x2a). Exhaustion: plain return, and the
      supervisor re-runs it next cycle.**
      **(4) THE SUPERVISOR is the runtime sweep itself: 0x1d7d88's
      terminator path. Every 30 passes (~270 ms of service — the observed
      busy window) it sends the unaddressed `0a 00` status query
      (0x59ed10, 2-byte reply) and re-runs the ENTIRE init whenever
      reply[0] bit 1 is clear — or bit 0, when the mode flag [0x7a919c]
      is set (1d7e8c). A zero-filled reply therefore meant "aux never
      initialized", once a second, for the life of every run this rig
      ever made. (The other gate, bus-error word 0x841e2c & 0x1f10, was
      sampled live at 200 Hz: always 0 — not the driver.)**
      **(5) THE FIX, all in hwshim.c as device modelling, no workarounds:
      (a) i2c MCUs 0x0a/0x2a power up presenting 0x0111 in reg 0x24
      (i2c_seed_ready), re-armed when the `08 01 01` reset broadcast is
      seen on the tty (i2c_ready_arm); config writes stick verbatim.
      (b) the `0a 00` reply carries bits 0+1 set (present + initialized).
      Three WRONG models were run and killed on hardware, kept in the
      hwshim comment because they look right: sticky 0x0111 (run 16 —
      turns the health check into a 1 Hz re-init: 0x0111 is a TRANSIENT
      the health check at 0x1fb38c treats as "device rebooted"),
      read-clear + write-transform (runs 17/18 — the config write to
      0x24 re-armed 0x0111 and the loop survived), bit 1 alone (run 20 —
      1d7e8c grades bit 0 first).**
      **(6) RUN 21, THE VERDICT: `0b` appears ONCE in the whole run (the
      boot init) and never again. Cabinet forward rate 31/s → 115.8/s;
      gap census over 45 s of attract: median 10 ms, p99 15 ms, MAX
      17 ms, ZERO gaps ≥ 100 ms (run 12 had 64 gaps of ~690 ms in 60 s).**
      **(7) ACCEPTANCE, run 21, Quick Adjustments via 3× Select-2000:
      twenty 300 ms presses alternating Minus(27)/Plus(26) at ~1.5 s
      spacing — 20/20 decoded into NodeRec.cur (40 edges, 0f→0b / 0f→0d),
      20/20 value-word changes at the specified oracle 0x7c908c, one per
      press, none missed, press-to-value latency 8 ms. Run 9's number at
      the decode layer was 12/20.**
      **A regex trap that cost two runs, recorded so it is not paid
      again: the shim's [i2c] READ lines carry TWO spaces ("READ  @") and
      WRITE lines one; a join regex written for one space silently
      dropped every READ, which is what made runs 14–18's cycles look
      write-only and sent two fixes at the wrong layer.**
      **Instrument debt kept deliberately: PAD_CAB_PROBE, PAD_NB_TRACE,
      PAD_OPEN_LOG (now with t=/dur=), PAD_I2C_LOG (env-tunable budget,
      t=-stamped) — all default-off. What the two MCUs actually ARE
      (audio amps on the backbox board is the best guess: the init sits
      beside the ALSA mixer bring-up at 0x1faad4) never mattered to the
      fix and is left open.**
      **Item 46 (turtles Action Button) is very probably this same fault
      — verify on the turtles title before closing it. The run-10
      idle-reply-levels question (bytes 3–7 as 0x00 asserting forty
      closed switches, quadrature pair in byte 2) stays open as its own
      filed item, deliberately unbundled.**
      **Logs: /var/tmp/gzwatch_run1[2-9]*_preserved.log,
      gzwatch_run2[01]*_preserved.log, ringwatch_run21_*.log, and
      C:\tmp\item17\run21\ (attract census, train capture, full shim
      log).**
      **★★★ DAVID AGAIN, 2026-08-12, ON A BUILD THAT ALREADY HAS THE LATCH
      (`979b940` is on main), so `sw_owed[]` did NOT cure the felt case and the
      half that is left is LATENCY, not delivery: "switch input by keyboard or
      interactive switch matrix seems to take a long time to register… the
      menus are not responsive enough from switch inputs (even the service
      screens using left and right flippers as input are noticeably clunky)."**
      **(i) It is not the keyboard path, and that is free to state.** The
      MATRIX is clunky too, and the three writers cost completely different
      amounts host-side — the game window's `binds[]` (no host cost), the
      playfield mouse through `SwitchDriver` (a ~80 ms `wsl.exe` spawn per
      action, item 24), and the playfield keyboard through item 39's
      `swkeys.py` pipe (no spawn). All three feel the same, so the fault is
      DOWNSTREAM of the merge — where the measured mechanism already is.
      **(ii) DAVID'S PROPOSED CURE IS ALREADY RULED OUT WITH NUMBERS: do not
      spend a pass on it.** "Interpreted with longer samples" is the
      minimum-closure-width theory, and there is no minimum — 72/72 registered
      down to 10 ms once the game looked. A longer sample buys DELIVERY odds,
      and delivery is the half already fixed. It cannot buy back LATENCY, which
      is what "takes a long time to register" is, and which this item's own
      limit (c) predicted in writing.
      **(iii) ★★ THE SERVICE-MENU CASE IS ALREADY MEASURED and was never
      written down here — it came out of item 43's turtles passes, 2026-08-11:
      `swpoke.py 25 2000`, a TWO-SECOND hold, registers every time, while
      250-500 ms presses fall between polls and read as nothing.** That is
      where "12 presses moved 3 rows" came from, and it was measured with the
      latch in the build. **That contradiction is the most valuable thing in
      this update:** the latch owes every closure a scan and the ladder read
      72/72, yet a 400 ms service-menu press still does nothing.
      **THE HYPOTHESIS THAT WOULD RESOLVE IT — a hypothesis, not a finding:
      this item's oracle proves DELIVERY, not CONSUMPTION.** `entry[+24]` is
      the scan drain's level. A menu that samples that level on its OWN UI
      period, or wants it made across two consecutive looks, never sees a
      closure exactly ONE scan wide — which is precisely what the latch
      produces. Cheap test before building anything: ladder a service-menu
      switch with `PAD_SW_MINSCANS` at 1, 2 and 4 and see whether the MENU
      moves where `entry[+24]` already moved.
      **★★ AND ITEM 46 IS THE SAME QUESTION ON A DIFFERENT SWITCH — filed the
      same day, independently, and it reached the same fork ("reached and
      ignored" vs "never arrived").** Read it before starting here. It carries
      the sharpest form of the contradiction: turtles' Action Button is switch
      **34 on node 1, the EXACT switch this item laddered 72/72 down to 10 ms**,
      the latch is default-ON and on main, and the button is still finicky in
      attract and (apparently) dead at character select. Same latch, same
      switch, ladder passes, game behaviour fails. **Neither item should buy the
      during-play per-node scan rate separately** — it has never been measured
      on any title, item 26 wants it too, and one run pays for three items.
      **AND THE REPRO JUST GOT CHEAP, which is the best news in this update.**
      This item had budgeted a run to reach BATTLE SELECT, which the rig has
      never reached. The service screens are the same symptom by David's own
      report and are reachable from boot with no game played — door open
      (`swhold.py 33 0`), LONG Select, version splash, LONG Select; item 43 did
      it repeatedly. Measure there first and keep BATTLE SELECT for confirming.
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
      **Resume — and start in a SERVICE SCREEN, not a battle, per the 2026-08-12
      update at the top:** ladder switches 59 and 60 with `swladder.py` (never
      measured, and both of David's reports are about them) with the service
      menu on screen, then answer the delivery-vs-consumption question — does
      the MENU move where `entry[+24]` moved, and does `PAD_SW_MINSCANS` 2 or 4
      change that. Measure the per-node scan gap in a service screen too: 670 ms
      is an ATTRACT number and nothing has measured a menu. Then play into a
      battle to confirm, with `[key]` and `[sw]` both on, diffing each key
      edge's X-time width against the closure the guest was handed. **Do not ask
      David which key and which screen; he answered on 2026-08-06 and again on
      2026-08-12, and both answers are at the top of this item.**
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
      **★ AND THAT ORACLE IS NOT SUFFICIENT ON ITS OWN — added 2026-08-12.** A
      closure that reaches `entry[+24]` and does not move the cursor is still
      exactly the fault David is reporting, so for the menu half the oracle is
      **the cursor moving on the GAME's own display**, timed against the press.
      State the press length and the delay, and do not report the wire number
      alone as a pass.

- [x] **43. In the turtles service menus the picture went HALF HEIGHT and the
      scene text stopped drawing — and the fault was OURS, in the GL bridge.**
      DONE 2026-08-12, branch `item/43`. **Verified in DAVID'S OWN RUN**
      ("it's working perfectly now"), and re-verified afterwards on the
      DEFAULT build with every workaround stripped out.
      **THE FAULT.** `glbridge.c` kept ONE process-global `glTexDirectVIV`
      registration — for a Vivante direct-texture extension whose three calls
      (`Map`, `VIV`, `InvalidateVIV`) take only a TARGET and name their texture
      IMPLICITLY, by whatever is BOUND. So when the service menu bound its own
      1024x256 GL_RGBA DMD texture and invalidated it, the bridge sent the
      VIDEO's 1360x768 I420 registration, and the host uploaded video pixels
      into the menu's quad. **The band was the menu's own DMD strip, correctly
      shaped and correctly placed, filled with the wrong pixels. The game was
      drawing its menu right the whole time.** The captured frame said so and
      was read past for a week: `BINDTEX 3553 2` immediately followed by
      `TEXDIRECT 1360 768 36805`.
      **THE CO-DEFECT, same mistake:** `glTexDirectVIV`'s frame buffer was also
      one process-global `static`, and that function has exactly ONE call site
      in the whole game binary (`0x4da060`, `Texture::Texture`) — so every
      allocating texture shared it, the DMD's 1 MiB and the presenter's 4 MiB
      in the same bytes. It showed up as the renderer reporting 60 uploads/s at
      **0.0 NEW/s**: one frame re-sent forever.
      **THE FIX (`ca0ab7c`).** Shadow `glActiveTexture`/`glBindTexture` and keep
      one registration per texture NAME, with each texture's allocation in its
      own slot. Sound for all four direct-texture users in this binary, checked
      in the disassembly rather than assumed: `Texture::Texture` binds at
      `0x4d9e10` BEFORE both direct calls and unbinds only at `0x4d9fac`,
      `SetPixels` binds through the virtual `Bind()` before invalidating, and
      the video path binds `[this+332]` before its `Map`. `Invalidate` on an
      unregistered texture sends NOTHING and says so once — deliberately no
      fallback to "whatever registered last", because that fallback IS the bug.
      **WHY IT TOOK A WEEK: every instrument pointed at the game.** The symptom
      is a video-shaped fault, so the search stayed in the video shim, and four
      separate video-side theories were built, run and killed — a coin-door
      caps gate, a per-stream arm-time lie stamp, a service-button pre-trigger,
      and holding frame delivery to zero. All four banded from a live attract.
      Two apparent successes were the same illusion: lying FROM BOOT drew the
      dots only because with no video ever registered the one global happened
      to hold the DMD's own registration. **That also means the committed door
      gate (`71caeb5`) never worked in David's flow at all** — its recorded
      success was a `PAD_DOOR_OPEN=1` service boot, and run as a faithful
      control from a normal boot it banded like everything else. A memory diff
      of the dots state against the band state (six snapshots each, matched
      configs) found 273 stable differences and none of them mattered: poking
      all 40 non-pointer differences at once, and separately zeroing the
      24-word object table that was null in the dots state, moved the picture
      not at all — because the game was never deciding anything.
      **WHAT CAME OUT WITH IT (`e600f2c`..close).** The gate, the host-side
      mode-word poller (`modewatch.py`, deleted), the renderer's draw-stream
      menu detector, the pre-trigger, the per-stream stamp, both `padgl.h`
      header flags and the debug stamper — about 320 lines from `gstvid.c`
      alone, and 4.7 KB off the shim. The video layer answers the TRUTH again
      in every state on every title. What survives of this item is the part
      that was always correct on its own terms and unrelated to the band:
      `get_state` reports the game's own last `set_state` instead of an
      unconditional PLAYING, a PAUSED pipeline holds delivery, and a seek on a
      torn-down pipeline is refused.
      **VERIFIED, default configuration, nothing set:** attract full-screen
      with video; **attract with the COIN DOOR OPEN still full-screen** (the
      regression the old gate caused, and the reason it had to come out); the
      service menu drawing David's reference green dot page; the deep Tech
      Alerts page rendering completely; a game started and playing over
      full-screen video; three correctly separated bridge registrations in the
      log (DMD `0400x0100` fmt `0x1908`, two videos `0550x0300` fmt `0x8fc5`);
      zero bridge complaints; no prepare storm; 60 fps at 29.9 uploads/s and
      **29.9 NEW/s**.
      **INSTRUMENTS LEFT BEHIND:** `guestmem.py` (snapshot/read/POKE the running
      guest host-side — poking `0x6046e0` drove the game out of its own menu,
      which is how causation got tested instead of theorised) and `memdiff.py`
      (differential state scan). Both carry the traps that cost captures: match
      the configs before diffing, verify a menu with the in-menu boolean
      `0x663958` and never `mode==0` alone, and `PAD_DOOR_OPEN=1` does NOT
      survive the playfield window stamping the door closed again.
      **THE LESSON, worth more than the fix:** the symptom's shape named the
      wrong layer for a week. When a menu looks wrong, capture the draw stream
      and ask WHICH TEXTURE the upload is for before asking what the game
      believes. See [[reference_spike2_caps_preroll_latch]].

- [x] **41. turtles_pro hard-crashed (qemu signal 11) on service menus and on
      character select — and the crash was OURS.** DONE 2026-08-11, `e5a99fc`
      (branch `item/41`, `6e44780`..`bd6b1f4`). **Verified in DAVID'S OWN RUN:**
      the shim rebuilt with the fix, he drove the repro that had killed it
      twice, and the log shows the dump firing on schedule and DECLINING four
      times instead of faulting.
      **THE FAULT.** `audio_dump()` (`hwshim.c:4941`) walked a linked list at
      **Godzilla Pro 1.15.0's fixed addresses** — the voice table at `0x7b90c0`,
      the queue pool at `0x7b8990+0x100` — dereferencing `*(node + 8)` with no
      check on `node`. On turtles those addresses are perfectly READABLE, they
      are simply another title's data, so every guard passed and the walk
      followed garbage pointers. The app passes `PAD_AUDIO_DUMP=30` on every run
      and `audio_maybe_dump()` fires from `ioctl()` on the first audio ioctl
      after each 30 s window — which is why it presented as "go to that screen
      and press a flipper": the flipper made a sound, the sound was an ioctl,
      and the ioctl walked a stranger's list. Nothing about the screen mattered,
      which is why scripted pokes missed it for a whole pass.
      **THE FIX, two parts.** The real one is a TITLE gate (`a_sw_struct()`, the
      rig's existing "is this the title those addresses came from" test, which
      the crash output itself proved answers correctly here). The
      unreadable-node check is the belt to its braces: a list can be torn
      mid-walk on the right title too, and a diagnostic that kills the run it is
      diagnosing is worse than no diagnostic.
      **WHY IT TOOK TWO DAYS TO SEE — the crash reporter could never fire.**
      Three independent causes, all fixed. (a) It was only ever installed by
      INTERPOSING the game's own `sigaction(11)`, and turtles never calls it,
      which is exactly what qemu's word "uncaught" means. It installs from a
      constructor now, in a HEADER mode that reports and then hands the fault
      onward unchanged (`PAD_SEGV_HEADER=0` disables). (b) `watch.sh`'s event
      filter grepped `/SEGV|Segmentation|FATAL/` case-SENSITIVELY, so
      `[segv] pc=` could never reach the app pane. (c) `real_open` is resolved
      lazily, so a guest faulting before it opened anything called a NULL
      pointer INSIDE the signal handler and lost the report. **`PAD_SEGV_REPORT`
      was NEVER the missing piece** — `run_game.sh:299,315` has always set it.
      **`tools/spike2_emu/segvtest.sh`** proves the reporter on a labelled
      example in two seconds with NO emulator run: four cases, two of them
      controls. It earned its keep immediately — the first version of the fix
      was not additive (it silently ate a guest's own handler) and only the
      reporter-off control showed it.
      **Left open as item 43:** the half-height menu screen the crash happened
      on. Same location, different fault. (Filed as 42 during the pass and
      renumbered before the merge — 42 went to the save-state portability item.)

- [x] **42. Save states could not work on ANY machine but this one, and a WSL
      with interop switched off could never open its own playfield window.**
      DONE 2026-08-11, `4700a88` (branch `item/42`). **Both halves are one
      fault wearing two hats: the emulator quietly assuming this developer's
      machine.**
      **(1) criu was a hand-built binary at `/var/tmp/criubuild/criu/criu/criu`,
      hard-coded as the default in EIGHT rig scripts**, and `apt-cache policy
      criu` on Ubuntu 24.04 prints an EMPTY version table - no Ubuntu publishes
      criu at all. So v0.126.0's save states could not have worked for a single
      other user even after PAD-53 added `busybox-static`: they would get the
      checkpointable boot, the Save and Load buttons, and `savestate: no criu at
      /var/tmp/criubuild/...`, naming a directory they have never had.
      `pad_criu()` in padpath.sh is now the one place that knows where criu is
      (`/usr/local/bin`, then PATH - Debian does package it - then the developer
      build, which keeps working); `getcriu.sh` builds the pinned v4.1 the save
      ladder was proven against and runs `criu check` BEFORE installing, since a
      criu that cannot dump would only silence the warning and leave the buttons
      dead. **Ruled out, do not retry: fetching another release's `.deb`** -
      criu links against libprotobuf-c, libnl-3, libnet, libbsd and libuuid,
      exactly the dependency chain `setupfix.sh`'s `_fetch_foreign` refuses to
      drag in.
      **(2) A tester's WSL has `[interop] enabled=false`, so his Linux cannot
      execute a Windows binary** - and the playfield window IS one, because this
      WSL has no Tk. **The asymmetry is what makes a fix possible:** interop is
      LINUX -> WINDOWS, so `wsl.exe` still works and everything the window does
      once it is up (padled reads, `swpoke.py`, `wslpath`) is unaffected. Only
      the LAUNCH cannot cross - and PAD is already standing on the other side.
      watch.sh now prints a token carrying the title, the save-state flag and
      both paths ALREADY TRANSLATED (the `/p` step WSLENV would have done during
      the interop exec that is not happening), and PAD opens the window. PAD
      also CLOSES what PAD opened, because the rig's forced close is itself a
      `powershell.exe` call, i.e. the same interop that machine lacks.
      **VERIFIED IN THREE PARTS, because no single test could reach all of it.**
      The criu half end to end inside `unshare -m` with tmpfs over BOTH
      `/var/tmp/criubuild` and `/usr/local/bin` - genuinely a machine that has
      never had criu: clone v4.1, `make criu`, `criu check` "Looks good.",
      install, `result=ok`, host untouched; reuse takes 4 s, an already-present
      criu exits `result=present`, non-root refuses. The watch.sh half with
      `PAD_PF_PYTHON=nosuchthing` on a live turtles run: the token printed with
      `game=turtles_pro savestates=1` and BOTH paths really translated to
      `\wsl.localhost\Ubuntu\...` - not the empty strings a silent `pad_win`
      failure would leave - and the run did NOT also try to launch a window
      itself. **Then the CHAIN, which neither pass had joined:** that real token,
      parsed and handed to the app's real `_open_playfield`, started
      `pythonw.exe playfield.py turtles_pro --savestates` against the live
      guest, and the real `_close_playfield` closed it. That seam - what
      watch.sh WRITES against what the app PARSES - is the one that would
      otherwise have shown up first on the tester's machine.
      **STILL TESTER-PENDING, and the release notes say so:** a genuinely
      interop-off WSL and a machine with no criu exist on a tester's setup, not
      here. Everything above is the closest proxy this machine can offer.
      Tests: 180 + 132 GUI smoke.

- [x] **39. Consolidate the two switch windows into one, to the right of the
      playfield — and make the no-artwork view fit on a screen.** DONE
      2026-08-11, `df74030` (branch `item/39`, 7 commits `32913f1`..`df74030`).
      **Closed on David's "looks good to me", after four rounds of his
      feedback grew it into the emulator's whole control surface.**
      **(1) One window.** The Controls X11 window no longer opens
      (`PAD_GL_LEGEND=1` reverts, no rebuild); padglhost exports its resolved
      `binds[]` to `dump/padbinds` (tmp+rename; watch.sh clears it at start)
      and the playfield renders it — the table keeps ONE home in the C file,
      `keybinds.py` owns the parse. `zorder.py` on a live run: GAME +
      PLAYFIELD, nothing else.
      **(2) The key panel**, docked right of the artwork: keys, a service
      cluster drawn as the real coin-door panel (green BACK, red -/+, black
      SELECT, press-and-hold through the artwork markers' own SwitchDriver),
      a COIN DOOR click toggle (amber "48V off, coils dead" when open), and
      the ball controls (TroughPanel grew `label_below`). One control per
      action: the service/door/trough binds left the key list, their key
      labels sit ON the widgets, made-state is a gold ring. Highlight is the
      MERGED array — the row lights when the GAME can see the press, whoever
      made it.
      **(3) Keyboard with the playfield focused** — a new write path, since
      the old one spawns wsl.exe per action (~80-200 ms): `swkeys.py` holds
      the block open and reads "<id> <level>" lines (releases all on EOF),
      `SwitchPipe` keeps one per session (pre-warmed at window open),
      `KeyInput` binds the exported rows, swallows X auto-repeat with a
      10 ms deferred release, drops keys typed into text widgets. Live proof:
      SendInput held Left 2000 ms into the FOCUSED playfield → the guest
      logged `[sw] +60p … -60p`, 1907 ms — tag `p` names the pipe.
      **(4) The Schematic reflowed:** node headers inline, columns cut to the
      screen's real height, measured column width, horizontal-scroll
      backstop. star_wars_le: ~2100 px wide with mouse-unreachable clipped
      rows → ~800 px including the panel, every row on screen.
      **(5) Ten save slots PER GAME** (David: "i thought we had 10 slots per
      game?" — they were global): `saves/<game>/<slot>`, slots.sh migrates
      the flat layout on sight (ran against the real disk, 4 slots, labels
      intact), savegame/loadgame resolve the game from the running guest so
      every caller keeps passing bare `slotN`, status.sh's saves_mtime
      watches both depths, the app's table keeps the qualified ref as row id.
      A bare name can no longer resolve to another title's save.
      **Instrument lesson kept:** a stale playfield window survives on the
      desktop and `raise_existing()` raises IT instead of launching new code
      — close the old window when a panel looks stale.
      **NOT re-verified at close, stated:** the first live save+load in the
      per-game layout (the restore machinery is untouched; only the
      directory the wrappers resolve moved), and a live star_wars_le run (no
      card on this machine; its schematic verified offline on its real
      tables).

- [x] **36a. Loading a save state on a card-run title, and a failed load that
      destroyed the rootfs.** DONE 2026-08-10, `322f688` (branch `item/36`).
      **Three faults, found in two of David's failed loads. Only the first was
      the one this item was filed for.**
      **(1) THE MOUNTPOINT — the star_wars load.** criu's mnt-v2 stages the
      guest's mount tree and stats each mount's place before putting it there:
      it binds `<rootfs>/games` in, then needs `games/<title>` to exist to put
      the card on. This item said `~/spike2root/games/star_wars_le` existed. It
      **did not** — the tree holds elvira3, godzilla_pro, jaws_le,
      john_wick_le, led_zeppelin_le, spk and turtles_pro, nothing else. That is
      the whole difference between the titles that load and the one that did
      not: an EXTRACTED title leaves a populated directory behind, and a
      PAD_CARD title (item 28) is never extracted, so its `/games/<title>`
      exists only inside the pivot namespace `run_game.sh` builds at boot.
      `restorestate.sh` now creates it from restore.env's own `card` lines. An
      empty directory is all criu wants; the card goes over it a moment later.
      Cards only — the other externals are device NODES, and a directory over
      `/dev/null` breaks a restore differently.
      **(2) THE TRUNCATE, which did real damage.** The growing-output retry was
      meant for the game's append-only outputs and its comment said so, but
      nothing enforced it: it truncated whatever file criu named. slot2 (08:14)
      recorded `usr/lib/libEGL.so.1` at 6760 bytes, the bridge was rebuilt and
      the file became 6972, criu said "bad size" — and the loop truncated **the
      guest's EGL library** to 6760. The restore then failed on the build-ID
      anyway and left a malformed `.so` the next run would have loaded, with
      nothing saying so. Only `dump/` may be truncated now; anything else stops
      the restore and names the file. **Reproduced with the guard in place:**
      the same slot2 load printed criu's `bad size 6972 (expect 6760)` and
      libEGL.so.1 was still 6972 bytes and a sound ELF afterwards.
      **(3) THE STALE SLOT, which is why loads started failing at all.** criu
      maps every file-backed page back from the file and validates size and
      build-ID, so a rebuild of the shim or the bridge kills every existing
      slot — and `ensurebuild.sh` rebuilds on any source change, by itself.
      `savestate.sh` now records a sha1 per mapped file under the guest's own
      library tree (hwshim.so, libEGL.so.1, libGLESv2.so.2 and the guest libc
      set — 24 lines on a real save), and `restorestate.sh`'s pre-flight —
      which runs BEFORE the live guest is killed — refuses such a slot in a
      sentence. Old slots carry no hashes, so criu's build-ID error is
      translated for them at the end.
      **Verified live:** star_wars slot3 (which had never loaded) restored to a
      playing game — PLAYER 1 LUKE, 8,260,950, BALL 1, artwork rebuilt from the
      GL journal, renderer 30 fps — and a fresh save on it packed 61 MB with
      the hashes recorded. Godzilla slot2 refused cleanly with the library
      intact. `alive.sh` 0 after both runs.

- [x] **21a. Clear feedback about how many balls are in play — the trough,
      drawn in trough order.** DONE 2026-08-10, `f0d0a14` (branch `item/21`).
      **The FEEDBACK half of the old item 21; the HANDLING half is now 21b and
      is still open.** `trough.py` owns which switches the trough is and in
      what order, matched by NAME (`TROUGH 1`..`TROUGH 6`) — the rule
      `padglhost.c`'s `binds_resolve()` already uses, so what latches six balls
      at window open and what draws them cannot disagree; ids are per title
      (Godzilla 71..66, Jaws 65..60, John Wick 75..70) and the `?`-name titles
      (item 29) fall back on the node 8 / bit 37..32 shape, labelled
      `(positions assumed)` on screen. `playfield.py` widened its coin-door
      read into ONE read of the whole merged array at 10 Hz
      (`PAD_PF_SW_HZ`) — a 9p round trip costs the same for 808 bytes as for
      one — and draws a six-ball panel with the position numbers under it plus
      a live state dot on EVERY switch marker, in both the artwork and
      schematic views. `swshow.py` derives the same trough from the same
      module; it had been printing Godzilla's ids against Jaws.
      **Live on godzilla_pro:** at rest `trough 6/6  0 in play  1 = eject
      end`, swshow `6 of 6 [71,70,69,68,67,66]`; after a plunge `trough 5/6
      1 in play` with position SIX hollow — the far end, which is the item 20
      class of bug this display exists to make visible — swshow `5 of 6
      [71,70,69,68,67]`.
      **Ruled out: filling the switch RING to show state**, which would have
      changed the hit test everywhere a switch and a coil share a spot (item
      24: the centre of RIGHT SCOOP lands on the COIL, and `coilact.py`
      depends on it). State markers never enter `self.info`, and a test
      asserts it. Two faults the offline `PAD_SW_FILE` check caught before a
      run could: silver dots are invisible on white artwork (green now), and a
      learned-complement denominator printed `trough 4/4` beside two visibly
      empty positions.

- [x] **37. A button on the Emulate tab that puts the emulator windows back to
      their default positions.** DONE 2026-08-10, `cd1a6ca`. **Reset windows**,
      beside "Restart WSL…", on every platform — unlike the two buttons around
      it, because a second monitor going away is not a Windows-only event.
      **What it clears:** the `game` and `legend` lines of the rig's
      `~/.pad_windows` (position AND size), and `playfield_pos` in
      `~/.pad_playfield.json`. Deleting the line IS the reset, read off the
      source rather than chosen: with no line, `win_open()` leaves the size at
      `fb_w/fb_h` (`PAD_GL_W/H`, 1360x768 from watch.sh) and the delayed restore
      marks itself settled at once (`game_settled = !game_want_pos`,
      `padglhost.c:1494`), so no `XMoveWindow` is issued and the compositor's own
      placement stands. There is no default POSITION to write — WSLg ignores the
      one asked for at create time.
      **★ WHY IT IS TWO HALVES, and it is a property of the machine, not a
      choice — the thing worth carrying forward.** Under WSL there is no Tk
      inside the distro at all, so watch.sh launches `playfield.py` as a
      **Windows** process through interop and its `~` is the Windows profile, a
      home no script running inside WSL can see. On a Linux desktop and in the
      macOS container the playfield is a local Tk process and its state file is
      rig-side, which is why `winreset.sh` clears that one too and the app's
      half then finds nothing. Exactly one side acts per platform and neither
      has to know which.
      **WITH A RUN UP IT REFUSES, three deep, and the authority is the script.**
      padglhost re-saves the geometry as the windows move and again at close, so
      a reset under a live run is written straight back — the button would
      report a success that never happened. `winreset.sh` reads
      `alive.sh --procs` itself and refuses (exit 1), so a command-line caller
      is refused too; the poll's grey-out and the click's info box are early UX.
      **`--procs`, not the `--total` the item suggested:** alive.sh's own header
      calls `--procs` the "is a run up" answer, the difference being idle card
      mounts, and a stranded fuse2fs mount cannot write `~/.pad_windows`.
      Verified against a REAL live rig: 18 processes, refused, nothing changed.
      **MEASURED, with the acceptance's own poison** — `game -4000 -2400 3900
      2900`, `legend -3800 -2380`, `playfield_pos [-2600, -1400]`, all off a
      3840x2160 desktop — then reset, then a godzilla_pro run from the worktree:
      • `[padglhost] window opened 1360x768`, the default; the run before the
      reset opened 1445x827, so the silly size is genuinely gone.
      • `restore converged after 1 check(s)` with **ZERO `restore try` lines**,
      which is exactly what a cleared file looks like.
      • all three windows on the desktop by `GetWindowRect` — game at the
      top-left corner, playfield 507,167, Controls 1344,-32 (that -32 is the
      RAIL frame's 32 px shadow margin, so the visible corner is on screen).
      `zorder.py` saw all three and self-tested OK.
      **ITEM 5'S RESTORE STILL WORKS — measured, not argued, on a second run**
      with a deliberately different remembered geometry (`game 400 300 1200
      700`): `window opened 1200x700`, `restore try 1: game at 406,327 want
      400,300 -> aim 394,273`, `restore converged after 2 check(s)`, and the
      windows landed at 400,300 and 1700,400. So a reset clears what was
      remembered once; it does not stop the rig remembering.
      **NOT TESTED, stated rather than glossed: DRAGGING** — the acceptance
      asked for it because that is what the banned `SetWindowPos` fix broke, and
      SendInput into a WSLg window is UIPI-blocked (items 7 and 12), so it needs
      hands. Nothing here touches window movement; it deletes two keys from two
      config files. The closest available evidence is the run above, where the
      restore machine moved a window and converged. **Nor has a MOUSE pressed
      the button** — the reset was fired through the widget itself
      (`_winreset_btn.invoke()`, which is Tk running the button's own command)
      against the real files, with the confirm dialog stubbed to Yes, so what is
      untested is the two message boxes rendering and the click landing.
      **Left alone on purpose:** `~/.pad_windows_win.json`. `padwinpos.py` writes
      it and NOTHING restores from it — the Windows-side mover was withdrawn
      because `SetWindowPos` on a RAIL window made both windows undraggable — so
      clearing it would destroy a diagnosis record and reset nothing.
      **Tests:** five in `test_emulate_tab.py` (the playfield-JSON half keeps
      other keys, is quiet on absent/junk/non-dict, the button is present and
      packed, and it greys while a run is up); 231 passed across
      `test_emulate_tab.py`, `test_gui_smoke.py` and `test_emulate_poll_storm.py`.
      The rig-side half is tested by running it, not by the suite — it shells to
      WSL, and this repo's suite stays fast synthetic fixtures only.

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
