# Rig slots: several Spike 2 emulator rigs on one PC, and seeing who holds each

## What and why

David, 2026-09-27: *"why do we impose rig locks when triaging or working on
items that need the emulator? i have 4 conversations going right now, and one
has locked the rig. can we spin up multiple instances so that we are not
locking others?"* and then: *"ideally, i want to visualize the locks somehow
too (each window that pops up should say what ticket it's coming from, we
should have feedback in the triage app that the emulator rig is locked, etc.).
having some visual feedback is really important to me"*.

Until this branch there was ONE rig per PC. Worktrees gave each session its
own code, but every session shared one guest rootfs (`~/spike2root`: builds,
NVRAM, tables, save states and the rings in `dump/`), one renderer build, one
set of run logs in `~`, and a `killgame.sh` / `alive.sh` pair that saw every
rig process on the machine. The single lock file (`~/.pad_rig_lock`) made
sessions take turns so that one session's Stop would not kill another's run.
Two sessions that did not take turns got two guests and two renderers sharing
one ring (2026-08-06).

## Design

### A rig slot is a complete rig, layered over the ordinary one

`PAD_SLOT=N` (1..`PAD_SLOTS_MAX`, default 5 since PAD-649, 4 before) selects slot N; unset or 0 is the
ordinary rig, exactly as before. All of it is derived in `padpath.sh`
("RIG SLOTS"):

| | slot 0 (unchanged) | slot N |
|---|---|---|
| guest rootfs `PAD_ROOT` | `~/spike2root` | `~/padslots/N/root`, an **overlayfs**: lower `~/spike2root`, upper `~/padslots/N/upper` |
| rings, NVRAM, tables, save states, shim, GL bridge, selector | under the rootfs | under the rootfs, so in the slot's upper layer |
| renderer build `PAD_GLHOST_BIN` | `~/padglhost` | `~/padslots/N/padglhost` |
| build stage `PAD_STAGE`, override stage | `~/emusrc`, `~/override` | `~/padslots/N/emusrc`, `.../override` |
| run logs `PAD_LOGDIR` | `~` | `~/padslots/N` |
| card mountpoints `PAD_CARDS` | `~/card` | `~/padslots/N/card` |
| audio relay port `PAD_AUDIO_PORT` | 45997 | 45997 + N |
| window position files | `~/.pad_windows`, `%USERPROFILE%\.pad_playfield.json` | `.pad_windows.rigN`, `.pad_playfield.rigN.json` |
| `.pad_env` instrument knobs | `~/.pad_env` | `~/padslots/N/.pad_env` |

**Why an overlay.** The rootfs is tens of GB and the disk has 8 GB free, so a
copy per slot is impossible, and a hard-linked copy is worse than none (a
build rewriting `hwshim.so` in place would rewrite every slot's). A fresh
slot's upper layer is empty and a full boot writes ~54 MB into it.

**Mounting takes root**, so it happens where root already is: the app's runs,
`slot.sh up N`, and `riglock.sh take` run through `wsl -u root`. `watch.sh`
refuses a slot that is not mounted and prints the one line that mounts it.
The mount lasts until WSL restarts; the upper layer survives.

**The lower layer is live.** A slot 0 build or `mktables` changes what every
slot sees for files the slot has not written itself. That is intended (a slot
starts from the current rig), and it is why `ensurebuild.sh` refuses a slot 0
rebuild while ANY slot's guest is up: truncating the base `hwshim.so` under a
slot's mapped copy would SIGBUS someone else's run.

### Every process knows its slot: `PAD_SLOT` in its environment

`PAD_SLOT` is exported by `padpath.sh`, so every child inherits it, the guest
included (`run_game.sh` never clears the environment). `padslot.sh` reads it
back from `/proc/<pid>/environ`:

- `pad_slot_of`, `pad_pids`, `pad_count`, `pad_pkill` replace every `pgrep` /
  `pkill` in the run path: `killgame.sh`, `alive.sh`, `status.sh`, `watch.sh`
  (teardown, renderer checks, the main loop), `runbridge.sh`, the save/load
  scripts, `slots.sh`, `restorestate.sh`, `autoattract.sh`, `swexercise.sh`,
  `longplay.sh`, `cardmount.sh`, `modes/gamecheck.sh`, `modes/soak.sh`.
- `padglhost.c` (`pid_in_my_slot`) and `pausekeep.py` pause only their own
  slot's game; before this, Pause froze every guest on the machine.
- **Unreadable = another account's process = slot 0.** A check run as the
  desktop user cannot read a root run's environment. Counting those as slot 0
  keeps a slot-free machine exactly as before (the app's status poll runs as
  the user and must keep seeing the root run it started). A slot >= 1 check
  never counts them; run it as root for an exact answer.
- **Gone is not unreadable.** `watch.sh` forks short-lived subshells whose
  command line is `watch.sh`'s; one that exits between `pgrep` and the read is
  `-`, nobody's. (First live run: those read as two phantom slot 0 runs.)
- **Windows processes** have no environment the rig can read, so the slot is
  on the command line: the audio player's port, and `--pad-slot=N` on a slot's
  playfield window (`playfield.py` ignores it). Slot 0's Stop matches only
  playfield windows WITHOUT the marker.
- `audioreset.sh` keeps a machine-wide count on purpose: `wsl --shutdown` ends
  every slot's run.

### The board: who holds which slot, readable from everywhere

`%USERPROFILE%\.pad-rig\` (from WSL: `/mnt/c/Users/<name>/.pad-rig`; derived
from the rig's own Windows path, or `PAD_BOARD`). It is on the Windows side
because every reader is somewhere else: the sessions' rig runs in Ubuntu, the
app's in PAD-Runtime (a different distro that cannot see Ubuntu's files or
processes), and the app window and the triage dashboard run on Windows.

- `slot-N.lock`: one line of JSON, `{"slot","who","what","distro","user","taken"}`.
  mtime = the holder's last word. Written by `riglock.sh`.
- `slot-N.run`: one line of JSON, `{"slot","game","label","distro","root","pid","started"}`,
  written by `watch.sh` at start, touched every ~10 s by its main loop, removed
  by its teardown and by `killgame.sh`. A record whose mtime stops moving is a
  run that died hard.

`riglock.sh take --any <who> [what]` takes the first free slot (atomic `set -C`,
proven O_EXCL on drvfs), `note`, `release` (refused while a run is up in the
slot, judged by the run record's heartbeat AND `alive.sh`), `list [--json]`,
`free`. **Slot 0 also writes the pre-slot `~/.pad_rig_lock`**, so a session on
the old protocol still sees the ordinary rig as held.

### A lock is a lease: held only while the rig is used (PAD-229)

David, 2026-09-27, after merging a ticket whose rig was still locked: "i would
expect that it only locks when it is ACTIVELY using it in conversation". The
board at that moment had every rig held and one running: three app windows
held a rig each from the moment they opened, one of them for a ticket already
merged.

- **States.** A held slot is `running` (a run record with a heartbeat; on
  slots >= 1 also `alive.sh`), `active` for `PAD_LOCK_IDLE` seconds (default
  300) after its last use, and `lapsed` after that. Last use = the newest of
  the lock's mtime, the run record's and (slot 0) the legacy file's; the lock
  is touched by `take`, `note`, `use`, and watch.sh's teardown (so the clock
  starts when a run ENDS, not when the slot was taken).
- **A lapsed lock is CLEARED, by itself.** David, the same day: the tickets
  must "auto-clear them themselves when they are not in use". Every
  `take`, `use`, `free` and `list` sweeps lapsed locks first, and so do the
  app's board reads (`rigslot.board`, every few seconds on the Emulate tab)
  and the triage dashboard's (pad-triage v0.9.1 `rigboard.clear_lapsed`,
  which polls all day - the reader that always runs). The clear is a rename,
  judged again after the move and put back if its holder used the rig in
  between. The slot's upper layer (NVRAM, builds, save states) stays; the
  holder's next command takes the slot back if nobody else did.
- **Use takes the slot back.** `riglock.sh use N <who>` renews my lease,
  takes a free or lapsed slot, and refuses one someone else is using.
  `pad_slot_use` (padpath.sh) says it before watch.sh starts, killgame.sh
  stops and restorestate.sh restores - so a session whose lease lapsed while
  it read logs, and whose slot was taken meanwhile, cannot Stop the new
  holder's run. Who is asking is `PAD_LABEL`, `PAD_TICKET` or the branch
  (`pad_own_label`, never the holder); nobody to name (main, an installed
  app) skips it, as does a child of a process that already said it, and a
  test with no board of its own (`PYTEST_CURRENT_TEST` without `PAD_BOARD`).
  rigbatch passes its `--who` to its own killgame calls, and keeps its
  leases warm while a worker waits for a staged card.
- **The app takes its rig at Start, not when its window opens**
  (`rigslot.claim_for_run`, was `claim_for_ticket` at start-up): the rig it
  ran on last first, then a free one, then a lapsed one; none in use -> the
  Start is refused with who holds what. Stop gives it back
  (`release_claimed`, never while a run of ours is up). The title names the
  ticket; the rig number is on the rig strip and every run window. The
  Emulate tab's strip counts a lapsed hold as free and shows `idle Nm`.
- **Deliberately not done:** no release hook at merge in pad-triage's
  engine. The dashboard's clear frees a merged ticket's rigs within five
  minutes of their last use anyway, and the engine had another session's
  work in flight.

### Who is it for: the label, on every window

`pad_label` (padpath.sh) = `PAD_LABEL`, else the holder of this slot's lock,
else `PAD_TICKET` (the triage app sets it), else the branch of the checkout the
rig runs from (read off `.git` files, since git in WSL cannot follow a Windows
worktree pointer; `ticket/PAD-n` shows as `PAD-n`, main shows nothing).
`watch.sh` fixes it once per run and exports `PAD_TITLE_TAG`:

- **Renderer windows** (`padglhost.c` `title_tag()`): `[rig 1: item/48] godzilla_pro - Stern Spike 2 emulator`,
  the legend and the second display the same way. The tag goes at the FRONT,
  because a taskbar button cuts the end off. Plain ASCII, because X11's WM_NAME
  is Latin-1.
- **Playfield window** (`playfield.py`): the same prefix on its title (which
  also makes `raise_existing()` per slot: before, two sessions on one title got
  one window, the first session's), plus a **coloured band across the top and
  a chip in the status bar** (`pfpage/pf.css` `--rig-N`, `pf.js`). Six
  colours: rig 0 grey, 1 cyan, 2 violet, 3 coral, 4 green, 5 amber (PAD-649);
  the app and the triage dashboard use the same ones.
- David's own runs from main in rig 0 have no label, and their titles are
  exactly as before.

"rig", not "slot", in everything a human reads: the app already calls save
states "slots".

### A hidden run: nothing on the desktop (PAD-230)

David, 2026-09-27: agent rigs popping game windows onto his desktop is "very
disruptive"; the triage dashboard's rig pill names the game instead.

- `PAD_HIDDEN=1 watch.sh` starts (or reuses) a private Xvfb for the rig,
  display `:70+N`, and points the renderer at it; `PAD_PLAYFIELD=0` for the
  Windows-side playfield. `bootcheck.sh` (so every `rigbatch.sh` sweep) is
  hidden by default; `PAD_HIDDEN=0` to watch one.
- The renderer still opens a REAL window, just on a display nobody looks at.
  Its own no-window mode would skip `win_open()`, which is where the coin door
  is shut and the trough filled - a different machine (48V disabled, no
  balls). Same GPU path too: d3d12 renders on Xvfb (presented by XPutImage).
- WSLg mounts `/tmp/.X11-unix` READ-ONLY, so Xvfb listens on the abstract
  socket only; `pad_display_state` answers `hidden` rather than looking for a
  socket file. Readiness is Xvfb's `-displayfd`. An idle Xvfb costs nothing
  and is left up for the rig's next hidden run.
- Pictures: `glshot.sh` (the FBO, no window involved). Switches: `swpoke.py`
  / `padsw.py`. Stop: `killgame.sh`.
- The run record carries `"hidden":true`; the dashboard pill reads
  `rig N · Godzilla Pro` while a run is up (pad-triage `rigboard.game_title`).
- Proven 2026-09-27, rig 4, godzilla_pro: attract at 59.7 fps on d3d12, no
  48V banner in the glshot frame, no PAD-230 window among the desktop's
  top-level windows (three PAD-225 sweep windows were).

### Hidden unless asked, and no window outlives its run (PAD-309)

David, 2026-10-01: "the emulator rigs need to clean up their 'virtual
playfield' windows too when they are done with the rigs. also, shouldn't the
rigs always be headless (no window) when running?" On his desktop at the time:
rig 3's `PAD-306-check` run, visible and sounding (`"hidden":false,
"audio":true`) for a ticket already released, plus an Edge playfield window
from that run's previous start whose server was gone - an orphan.

- **The orphan.** pfweb's third window rung (`AppBackend`, a Chromium
  `--app` window, taken whenever the Python running the playfield has no
  pywebview - an agent's or a worktree's Python) is a browser process of its
  own. Windows does not end a child with its parent, and every hard stop
  ends the host without its cleanup: killgame.sh's `Stop-Process -Force`,
  the Spike 2 tab's `proc.kill()` after its grace, a crash. 61 dead
  `padpf-*` profiles sat in %TEMP%, one per such stop. Now each window goes
  into a kill-on-close job object whose only handle is the host's
  (`_KillWithUs`), so the kernel ends the window with the host however the
  host ends; and the first window of a host sweeps the dead profiles (a live
  browser's `lockfile` refuses removal; Windows only). Every emulator's
  playfield rides pfweb, so this is all of them; the AP-family tabs' own
  close-stdin-then-kill-tree stays as the polite path.
- **Hidden by default, on the rig.** A run with a label (Spike 2's
  `pad_label`: PAD_LABEL, the slot's holder, PAD_TICKET, a ticket branch) or
  on a rig >= 1 is hidden unless it says `PAD_HIDDEN=0` / `PAD_VISIBLE=1`.
  Spike 2's watch.sh decides it after the label is fixed; every other
  emulator's watch.sh asks `rigboard_visible` (tools/rigboard.sh), which
  honours PAD_VISIBLE, then PAD_HIDDEN, then the label - the app's own
  `PAD` label is nobody's. An unlabelled run (David's own rig from main, a
  terminal) is seen, as before. JJP has no hidden display (Xephyr is a
  window by design) and is unchanged; Spike 1's viewers are in the app page.
- **Hidden and muted in a session's app.** Claude Code sets `CLAUDECODE=1`
  in every command it runs, so an app a session starts knows it
  (`rigslot.agent_driven`). Every Emulate tab's Start ends its env with
  `rigslot.quiet_env()` - env(1) applies assignments in order, so they win
  over the tab's `PAD_VISIBLE=1` / `PAD_AUDIO=1` - and the AP / BoF / DP /
  PB / Spooky tabs open no playfield window for a hidden run. `PAD_HIDDEN=0`
  (and `PAD_AUDIO=1`) in the app's environment show (and sound) it when
  David asks. Otherwise the app says `PAD_HIDDEN=0` out loud, because a
  ticket's app (the dashboard's launch, which drops CLAUDECODE) labels its
  runs and must still show David the change.

### What it deliberately does not do

- Per-slot CPU limits. Each guest is ~1.5 cores; `PAD_SLOTS_MAX` is the only
  brake.
- The card image CACHE (`~/cardcache`) stays shared: it is a cache of an image
  file, and two slots mounting one card each get their own read-only fuse
  mount over it.
- `padwinpos.py` / `zorder.py` (diagnostic window recorders, not in the run
  path) still match by title needle with no slot filter.

## Status

**2026-09-27, pass 1: the rig core, emulator-proven with two concurrent rigs.**

Proven on real titles, `godzilla_pro` in rig 1 and `turtles_pro` in rig 2, both
booted at the same time (Ubuntu, Xvfb :7 because this VM's WSLg X server was
down, muted):

- one `game` process per rig, each with its own `PAD_ROOT`; one renderer per
  rig on its own `padgl` ring (two separate 64 MB rings in the two upper
  layers); ~54 MB written per upper layer for a full boot
- `status.sh` per rig: rig 1 `state=attract fps=52`, rig 2 `state=techalerts
  fps=55.5`, each from its own log
- `alive.sh`: rig 0 = 0, rig 1 = 13, rig 2 = 13 with both up
- renderer titles on the X display: `[rig 1: feature/rig-slots] godzilla_pro -
  Stern Spike 2 emulator` and `[rig 2: ...] turtles_pro - ...`
- playfield windows on Windows: `[rig 1: feature/rig-slots] godzilla_pro -
  virtual playfield` and the rig 2 one
- **`PAD_SLOT=1 killgame.sh` killed rig 1's 13 processes and left rig 2
  running** (still `running=1 state=attract fps=60.5` afterwards); its board
  run record was removed and rig 2's kept; then rig 2's own Stop cleaned it
  to 0
- `riglock.sh take/list/release` for slots 0-2, including the legacy lock file

Seen during the test, and the reason this branch matters: another session's
app run in PAD-Runtime stopped and restarted (metallica, then munsters) while
my rigs were up, and both of my playfield windows disappeared. The old
`killgame.sh`'s Windows backstop kills every `playfield.py` on the PC, across
distros. After merge, rig 0's Stop matches only unmarked windows.

**2026-09-27, pass 2: the app, the triage dashboard, save states in a rig.**

- **The app** (`core/rigslot.py`): every rig command carries `PAD_SLOT` and
  `PAD_LABEL` (through `emulate_core._rig_env`). A copy launched for a triage
  ticket (`PAD_TICKET`, no `PAD_SLOT`) claims the first free rig on the board
  at startup and gives it back on exit, so two ticket windows never share a
  rig; its title bar says `[rig 2: PAD-231]`. The playfield window the app
  opens itself gets the marker and label. The **Emulate tab** shows an
  "Emulator rigs" strip (each rig's colour chip, holder, what it is doing;
  this window's rig outlined) whenever this window has a rig of its own or
  another rig is held or running. Checked in a capture against a sample board
  (`webui_shot.py --tab emulate`, zero page errors).
- **The playfield page's band and chip**, captured with `playfield_demo.py`
  as rig 1 / item/48: cyan band across the top, `rig 1 · item/48` chip.
- **The triage dashboard** (`pad-triage` v0.8.19, commit `f28989a`, pushed):
  `rigboard.py` reads the board (file reads only, cached 2 s); the header has
  one square per rig in its colour (filled when held, pulsing while a game
  runs) and "emulator: N of 5 rigs busy"; the list has an "Emulator rigs"
  panel with each holder linked to its ticket; a ticket holding a rig shows a
  chip on its card and its tab; `/api/rig`. Every claude session it spawns
  (headless, browser terminal, console window) gets `PAD_TICKET=PAD-n` with
  `PAD_TICKET/u` in WSLENV, so the rig titles its windows with the ticket.
  The live dashboard shows it after a restart (tray: Restart).
- **Save states in a rig, emulator-proven.** Checkpointable run (root,
  `PAD_PIVOT=1`) of godzilla_pro in rig 1: `savegame.sh` wrote the slot into
  rig 1's own `saves/` (48 MB, nothing in the base rig's); the first
  `loadgame.sh` FAILED - `restorestate.sh` sweeps every mount out of the
  restore's namespace, a rig's rootfs IS a mount, and criu was handed an empty
  root ("Can't stat mountpoint .../dev/shm", both mount engines). Fixed by
  keeping `$R` when it is a mountpoint (rig 0, a plain directory, unchanged).
  Then, over a live rig 1 run: `[restore] ok`, the restored guest carries
  `PAD_SLOT=1`, `status.sh` rig 1 `state=attract fps=59.9`, rig 0 still 0.
- Tests: `tests/test_rigslot.py` (app side) and more in
  `tests/test_spike2_rig_slots.py`; 52 pass under WSL, 50 + 2 `/proc` skips
  under Git Bash; the diff's targeted zones (7661 tests) pass.

**2026-09-27, pass 3: one ticket, many rigs - library sweeps in parallel.**

David: *"a ticket needs to test emulated changes in our whole spike 2 library.
right now, it's going one by one"*. Every sweep so far was a throwaway serial
loop (`mb_batch.sh` for the multiball proof: 36 builds, median 3.0 min each,
p90 6.5 min, ~2 h a pass). Nothing ties a rig to a session, so one ticket can
take several; what was missing was something to spread a list across them.

- **`rigbatch.sh [-n RIGS] [--who PAD-n] <list> [-- command...]`**: the list
  is the sweeps' own `key|card|ENV=v` format; one worker per rig takes the
  next build off a shared queue (flock) and runs the ticket's command as
  `command key card` with that rig's `PAD_SLOT`; results.tsv, progress.txt
  and a log per build; each rig is noted on the board as it starts a build,
  so the dashboard shows the sweep live; a rig left running is stopped before
  its next build; Ctrl-C stops and frees every rig. Default rigs = the CPU's
  (`nproc*10/28`, a rig ~2.8 cores): over-committing starves the emulated
  games and healthy builds fail on timing, so more than that is a warning.
- **`bootcheck.sh key card`**: the default job and the template for a ticket's
  own - boot the card (read-only in place, no cache copy, muted, no playfield
  window), wait for attract, stop the rig, print one `VERDICT` line.
- **WSL cores 6 -> 10** (`~/.wslconfig`, David's call): three rigs at full
  speed instead of two. Takes effect at the next `wsl --shutdown`.
- **Proof, 4 real card images** (aerosmith_le 1.15, batman 1.13,
  stranger_things_le 1.12, guardians_le 1.14), Ubuntu, 6 cores, Xvfb +
  llvmpipe: one rig after another took 7 m 33 s of job time; on 2 rigs the
  same four passed 4/4 in **5 m 04 s**, each build's time matching its
  single-rig run (aerosmith 54 s vs 73 s, batman 151 vs 152, stranger_things
  88 vs 93, guardians 145) - so two rigs on six cores cost no build any time.
  A list of four splits unevenly; over 36 builds 2 rigs is ~2x, 3 rigs ~3x.
- Seen once: stranger_things_le 1.12 segfaulted into its own watchdog in rig
  1's first boot; it passed on rig 0 (control) and on rig 1 again, and in the
  parallel run. A one-off, noted in case it recurs.
- Tests: `test_rigbatch_spreads_a_list_across_rigs_and_frees_them` (stub rigs,
  Linux only - rigbatch needs setsid and flock like the rig itself).

**2026-09-27, pass 4: merged, 10 cores, and cards staged off the hard disk.**

- Merged to main (`a0ecce09`); the `/next` skill's rig section is the
  riglock.sh protocol; `wsl --shutdown` made the 10 cores live (`nproc` 10)
  and brought WSLg back.
- **The 3-rig library sweep FAILED 5 of 12 builds** (avengers_infinity_le,
  mando_le, deadpool_pro, dungeons_and_dragons_le, sword_of_rage_le), every
  one on the game's own watchdog ("GAME EXIT DISPATCH TIMEOUT"), two of them
  13 s apart on different rigs. vmstat: 3-4 processes in disk wait at every
  sample, 16-21 % iowait. D: is a SPINNING disk (ST4000DM005): three rigs
  reading three images made it seek until a read stalled past ten seconds.
  The morning's one-rig stranger_things crash was the same thing on a cold
  read. Not the rig slots: the load was I/O, not CPU (load 8 on 10 cores).
- **`cardstage.sh`**, run by rigbatch whenever it uses more than one rig and
  a card is on a Windows drive other than C:: ONE copier moves each card to
  `/mnt/c/tmp/pad_cardstage` (the NVMe) a few builds ahead of the rigs - a
  long sequential read, the one thing a hard disk does well - and each rig
  boots its copy. robocopy (91 s for 8 GB against 111 s for cp). Copies are
  kept for the next sweep up to `--stage-keep` GB (default 100), least
  recently used out first, never one in use; 30 GB of the disk is always left
  free (`PAD_STAGE_SPARE_GB`). `--stage DIR` / `--no-stage`.
- **Proof: the five failed builds plus iron_maiden_le, 3 rigs, staged: 6/6
  pass**, renderer at ~60 fps, 36-91 s to attract. The copies (7.5 GB in
  46-90 s, ~100-160 MB/s) are now the floor: a cold full-library sweep reads
  327 GB, about an hour, against ~2 h one build at a time; a re-run of
  anything staged in the last 100 GB starts at once.

**Owed**

- The full 33-card sweep on 3 rigs, staged (about an hour, copy-bound), when
  the machine is quiet.
- If sweeps get re-run a lot: a bigger `--stage-keep` (the NVMe has ~300 GB
  free; the whole library is 327 GB).
- `plans/TODO.md`'s rig-lock non-negotiable still describes the single lock
  (the `/next` skill and the memory were moved to riglock.sh at merge; the
  queue itself is being retired into tickets - docs/plans/ticket_intake.md).
- An app-driven run in a claimed rig in PAD-Runtime (the app's own distro).
  Not run in this pass: another session was running the app in PAD-Runtime on
  main's code, whose Stop is still machine-wide within that distro and on the
  Windows side.
- WSLg: this VM's X server was down all day (no socket in `/mnt/wslg`), so the
  renderer windows were proven on a private Xvfb (`:7`) by title, not seen on
  the desktop. The playfield windows were seen on the desktop.

**2026-09-27 - PAD-229: leases.** Everything under "A lock is a lease" above.
Proven by tests (test_rigslot.py: the app holds nothing until Start, Start
takes free-then-lapsed and the same rig first, Stop gives it back, a run up
keeps it; test_spike2_rig_slots.py: lapse and `list`, take --any's order and
the seize, a run keeps a stale lock live, `use` renew/take/refuse, the
refusal in pad_slot_use, the pytest guard) and by `list` on the real board,
which read the three app-window locks as LAPSED and PAD-225's sweep as
running. Owed: an app-driven Start/Stop on a claimed rig in PAD-Runtime
(the app windows open at the time run the old code until reopened).

**2026-10-20 - PAD-649: sweeps run faster.** David: "we need to be able to run
sweeping tickets (like 645 and 643) faster. they shouldn't be taking hours upon
hours to go through all of the games. i remember we had a 4x playback in
emulator rigs before". Measured on the board and the two sweeps' batch logs
that afternoon: both ran at 1x (nobody passed `--speed`); PAD-645's passing
builds took 110-150 s, ~66 s of it the job's own wall-clock sleeps, and its
FAILING builds 605-1023 s each (a loop waiting 600 s for a runtime line);
its one-rig batches staged one card ahead, so each rig sat idle 70-110 s
through every copy; each ticket wrote a chunk-and-poll driver of its own
because rigbatch took its rigs once at start and never picked up a rig the
other ticket freed; and the two tickets' card copies ran AT ONCE off the
spinning D: (the copy lock was in `/tmp`, which is per distro: PAD-643 in
PAD-Runtime, PAD-645 in Ubuntu), 72-108 s a card against the 24 s a copy
takes alone. PAD_SLOTS_MAX was 4, so rigbatch's own fit of 5 rigs was never
reached.

- **rigbatch runs every job at 4x by default** (PAD-484's game speed;
  `--speed 1` or a line's `PAD_SPEED=1` opts out). The rig's helpers already
  keep the game's time; a job's own `sleep` does not, which is what rigjob.sh
  is for.
- **rigjob.sh**, the library a sweep job is written on: `job_begin`,
  `job_boot`, `job_wait_attract` (Guided Setup left on a first boot),
  `job_press`, `job_sleep` (game seconds), `job_wait_log` (a deadline in game
  seconds), `job_start_game` (a game is on when the ball was launched),
  `job_shot`, `job_pass` / `job_fail`. Every wait ends the moment the run
  dies; a job that ends any other way still stops the rig and prints a
  VERDICT fail. `startcheck.sh` (boot, then a game started) is the example
  and rigbatch's second stock job.
- **Every job is capped**: `--job-cap S` (600; a line's `PAD_JOB_CAP=S`
  wins; 0 = none). The job is a session of its own (setsid), stopped whole;
  the rig's run with it.
- **The rigs join as they free**: `-n` is a ceiling. The batch starts on the
  rigs free now (waits for the first, saying so once a minute; `--no-wait`
  gives up), looks every `PAD_RIGBATCH_GROW_S` (20 s) for another while
  builds are queued, and a worker gives its rig back the moment the queue is
  empty. No chunk drivers.
- **The copier runs two builds ahead per rig** (`<out>/ahead`, raised as rigs
  join), so a copy overlaps the job on a one-rig batch too.
- **One card copy at a time across every distro**: the copy lock is
  `/mnt/wsl/pad-cardstage-copy.lock` - WSL mounts one tmpfs there in every
  distro (proven: an flock held in Ubuntu refused `flock -n` in PAD-Runtime,
  same inode) - and `/tmp` where there is no `/mnt/wsl`.
- **Five rigs** (`PAD_SLOTS_MAX` 5): rigbatch fits `nproc*10/20` = 5 on this
  VM's 10 cores. Rig 5's colour (amber, `#e8c04a`) is on the playfield page,
  the app's rig strip (`core/rigslot.py`) and the triage dashboard
  (pad-triage v0.42.0 `rigboard.py`; the running dashboard shows it after a
  restart). Mount it once per WSL boot: `wsl -u root -e bash <rig>/slot.sh up 5`.
- **Proof on the emulator, rig 5, four cached builds through `rigbatch.sh -n 2
  --who PAD-649 ... -- startcheck.sh` with nothing else passed** (so at 4x,
  15 fps, job cap 600 s; the other four rigs held by PAD-643 and PAD-645's
  sweeps the whole time, so it ran on one): **4/4 pass in 7m27s**. Godzilla
  Pro 1.16 162 s (the title's FIRST boot in a fresh rig: tables built, Guided
  Setup left by the library at 126 s, attract 129 s, a game on at 152 s),
  Jaws LE 1.02 **47 s** (attract 33 s, a game on at 37 s), John Wick Pro
  1.02 99 s, Jurassic Park Pro 1.16 129 s (Guided Setup again, left at 97 s);
  `dump/padspeed` read `x4.000`, padspeed.log "the game took it up"; every
  job left 0 processes and the rig was given back the moment the queue was
  empty; the pictures are real games (Jaws: Skill Shot, player 1 in play).
  Against PAD-645's job at 1x: 110-150 s a passing build, 605-1023 s a
  failing one. The batch first started on four UNCACHED builds, and its
  copy crawled at 0.4 MB/s beside the other two tickets' copies off D: (each
  on the old per-distro lock) - the collision the shared lock is for.
- **The rig pills say 4x** (David, the same afternoon: "I want visual
  indication on the rig pills that it's running at 4x as well"). watch.sh
  writes the game's speed into the run record (`"speed":4`, from
  `dump/padspeed` once the shim has taken the ask up; only this run's file
  counts, so the boot says 1 whatever the last run was asked) and rewrites the
  record at the next heartbeat when it changes. The triage dashboard's pill
  carries a badge in the rig's colour (`rig 1 - Jaws LE [4x]`, pad-triage
  v0.43.0 `rigboard.speed_text`) and its Emulator rigs panel says "running
  7m at 4x"; the Emulate tab's rig strip (`core/rigslot.py` `run.speed`,
  emulate.js `.emu-rig-speed`) the same. Real time and an older record say
  nothing. Proven on rig 5 (Jaws LE at 4x): the record read `"speed":1` at
  8 s (Tech Alerts) and `"speed":4` from 30 s on (attract; padspeed.log "the
  game is up after 14 s: asking x4.000 ... took it up"); the dashboard pills
  rendered from the real reader and page code against a sample board, before
  and after, sent to David.
- **The rig pills say which card is copying, and how far** (David, later the
  same afternoon: "we should indicate on rig pills when card copies are
  ongoing and the percentage of them" - every rig of the two sweeps read
  "waiting for its card" for minutes with nothing saying what for). The
  copier (cardmount.sh `cache_wait`) writes `copy-<label>.json` beside the
  rigs' locks every 2 s (`card`, `who`, `state`, `done_mb`, `total_mb`,
  `pct`) and removes it at the end; cardstage.sh writes a `queued` one while
  it waits for the machine's copy lock (`cardmount.sh <card> --board-copy
  queued|clear`); rigbatch's lock note names the card's label (`waiting for
  its card: iron_maiden_le-1_18_0`) and its stager carries the batch's label,
  so the dashboards tie the record to the rig - by label, else the holder's
  running copy, else its first queued one; a record untouched for 90 s is a
  dead copier. The triage dashboard's pill reads `rig 5 - copying Iron Maiden
  LE 1.18 [60%]` and its panel "copying Iron Maiden LE 1.18 60% (4.4 of 7.3
  GB)" (pad-triage v0.44.0 `rigboard.copies` / `copy_for` / `card_title`);
  the Emulate tab's strip the same (`core/rigslot.py`, emulate.js
  `.emu-rig-copy`). Proven live: a two-card startcheck batch on rig 5 whose
  cards were not cached - the board read `"state":"copying","pct":7` a minute
  in and the pills rendered from the live board at 60%, sent to David; the
  other four rigs (PAD-643/645, old code) stayed plain, as they must.
- Tests (test_spike2_rig_slots.py, stub rigs, Linux): the batch waits for a
  rig, takes the second as it frees, gives both back, the copier's lead
  follows (2 then 4); the cap stops a job with everything it started, for
  `--job-cap` and a line's own; the defaults and the lock path by text;
  rigjob's waits by text. test_rigslot.py and pad-triage's test_rigboard.py
  take the rig count from SLOTS_MAX. `test_a_sweeps_card_copier_is_no_rigs_run_script`
  fails on main too while other tickets' rigs are up on this machine (it
  reads the live /proc).

### The protocol text for the `/next` skill, at merge

> **Rig slots - several rigs, one per session.** Take a rig of your own
> before any build, run, Stop, save-state or rootfs change:
>
>     wsl -u root -e bash <rig>/riglock.sh take --any item/<N> <what is up>
>
> It prints `slot=N` and mounts rig N. Run EVERY rig command with
> `PAD_SLOT=N` (`wsl -e bash -c "PAD_SLOT=N PAD_AUDIO=0 bash <rig>/watch.sh 8"`,
> `PAD_SLOT=N bash killgame.sh`, `PAD_SLOT=N bash alive.sh`). Say what you
> are doing as it changes: `riglock.sh note N <what>`. The lock is a lease:
> it lapses five minutes after your last use, and your next watch.sh,
> killgame.sh or restorestate.sh takes it back if nobody else did (and
> refuses if somebody is using it - then `take --any` again). Done with the
> rig for good: `riglock.sh release N item/<N>`.
> `riglock.sh list` shows every rig; David sees the same board on the triage
> dashboard and the Emulate tab. Rig 0 (`--slot 0`) is the ordinary rig and
> the base every other rig is layered over: take it only to change the base
> (a slot 0 build or `mktables`), and expect every rig's view of an unwritten
> file to change with it. A rig's Stop and counts see only that rig; a
> `wsl --shutdown` still ends every rig's run.

## How to test it

Targeted tests: `python scripts/testpick.py` on the diff.

By hand, in WSL (Ubuntu), from this worktree's `tools/spike2_emu`:

```
wsl -u root -e bash <rig>/riglock.sh take --slot 1 feature/rig-slots godzilla run
wsl -e bash -c "PAD_SLOT=1 PAD_AUDIO=0 PAD_GAME=godzilla_pro bash <rig>/watch.sh 8"
wsl -e bash <rig>/riglock.sh list
wsl -e bash -c "PAD_SLOT=1 bash <rig>/alive.sh"
wsl -e bash -c "PAD_SLOT=1 bash <rig>/killgame.sh"
wsl -e bash <rig>/riglock.sh release 1 feature/rig-slots
```

Start a second slot beside the first and check that each slot's `alive.sh`
counts only its own, and that one slot's `killgame.sh` leaves the other up.
