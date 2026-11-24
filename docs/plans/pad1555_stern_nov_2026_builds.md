# Stern's November 2026 Spike 2 builds, and node board firmware 1.42 (PAD-1555)

David, 2026-11-24: *"The last days, Stern updated a lot of spike 2 games, like king kong, with nodeboard update 1.42,
does that impact pad? Check new sd-card images from Stern's website. Download ones we don't have and analyze
differences."*

## What Stern published (sternpinball.com/support/sd-cards/, 2026-11-24)

The code-watch skill's Stern source found 14 images newer than `D:\Pinball\images\Stern`:

| Build | Held before | Kind |
|---|---|---|
| King Kong LE 1.01 / Pro 1.01 | LE 1.00, Pro 0.97 | Spike 2 |
| Avengers: Infinity Quest LE / Pro 1.12 | 1.10 | Spike 2 |
| Foo Fighters LE / Pro 1.05 | 1.04 | Spike 2 |
| Dungeons & Dragons LE / Pro 1.11 | 1.10 | Spike 2 |
| Metallica Remastered 1.05 | 1.04 | Spike 2 |
| Pokemon LE 0.87, Star Wars 2025 LE / Pro 0.98, Transformers LE 0.98, Walking Dead Remastered LE 0.94 | older | Spike 3 (LUKS) |

The nine Spike 2 zips are in `D:\Pinball\incoming\PAD-1555` (each is a Zip64 wrapper around the `.raw`: Windows
`tar` skips the 15 GB member silently, Python's zipfile extracts it).

## Node board firmware 1.42: what it means for PAD

- **It is not new to the library.** King Kong LE 1.00 (Nov 17, already in the library) carried the ten
  `*-1_42_0.hex` node images too; its release notes say "Updated to nodeboard firmware/protocol v1.42.0" under 1.00.
  1.01 is a rules hotfix ("Holiday Hotfix", Nov 24): system "Remains on V4.41.0 on OS: V2.7.0".
- **PAD never flashes or ships node firmware.** The `.hex` files are the game's own (encrypted per build: the same
  1.42 file has a different md5 on 1.00 and 1.01). The emulator's node boards (`hwshim.c` `nb_fw_title`) take the
  version they claim from the `.hex` file name on the card, so a 1.42 card is answered as 1.42 without a change;
  the per-board identity (`nb_idents[]`, `node_ident.txt`) is what would need a change if a build brought a new
  board type, which 1.42 does not on King Kong (the same ten node images as 1.00).
- **Card layout is unchanged**: King Kong LE 1.00 vs 1.01 have the same partition table, a byte-identical OS
  partition (`/etc/version` 202209050216), and 33 of 1345 games-partition files differ (the game program, the
  `image.bin` asset container, the per-build node images, the release notes, `conagent`, the `.sidx` index).

## What does change for PAD: every new build is a new game program

Mode support is per game BUILD (`<game>-<version>` keys). For a build with no shipped port the app derives one on
the card's first read (`port_derive.ensure_port`, about 3 minutes), marked NOT RUN; the Modes tab then says the app
worked the build out itself, **Write leaves modes off the card until "Check this game" has run on that PC**, and every
proven-set part (lights, screen, clip, stack, multiball, ball save, coils, place, done, with, shaker) is greyed with
"has not yet seen ... in the emulator". King Kong LE 0.97's shipped port greys 5 parts (hardware the game lacks);
the derived King Kong LE 1.01 port greys 18. The derived port itself is close: same 55 shots, 109 lamps, 119 cabinet
lamps and 6 events as the 0.97 port.

## Plan (each step proven on the emulator, rig sweeps through rigbatch.sh)

1. Analysis of all nine against their predecessors (program, node images, OS, release-note headline).
2. Extract and Write on each new card through the app's own pipelines (headless, `C:\tmp\PAD-1555\xw.py`), with a
   replaced sound and picture read back.
3. Boot + game start on the rig for each new card (`startcheck.sh`).
4. Ship a port per build: derived, merged with the same title's proven port, `gamecheck.sh play full`, recipe.
5. Join each build to the proven sets it can, with an emulator proof per set, and to TITLE_SCENES / editions /
   music where the predecessor was.
6. Library: the new cards into `D:\Pinball\images\Stern\spike2`, the replaced builds into `older versions`.

## Status

### Run 1 (2026-11-24)

**The nine builds against the ones they replace** (`C:	mp\PAD-1555nalyze.py` over each card's `<title>/game`,
`*.hex` names and `data/*release_notes.txt`; only King Kong carries release notes on the card, and Stern's site
loads its notes by script, so the others' change lists are not readable here):

| Build | Replaces | Node firmware | Node board images | Game program |
|---|---|---|---|---|
| King Kong LE 1.01 | 1.00 | 1.42 -> 1.42 | same 17 | +19 KB ("Holiday Hotfix", Nov 24: T-Rex gate, climb fixes, 7 Instant Info pages; System V4.41.0, OS V2.7.0) |
| King Kong Pro 1.01 | 0.97 | 1.33 -> 1.42 | same 17 | -18 KB |
| Avengers LE / Pro 1.12 | 1.10 | 1.33 -> 1.42 | same 17 | -207 / -228 KB |
| Foo Fighters LE / Pro 1.05 | 1.04 | 1.33 -> 1.42 | same 17 | +397 / +367 KB |
| D&D LE / Pro 1.11 | 1.10 | 1.37 -> 1.41 | same 17 | +7 / +18 KB |
| Metallica Remastered 1.05 | 1.04 | 1.33 -> 1.42 | same 17 | +15 KB |

So the node-board move is 1.33 (or 1.37) to 1.41/1.42 with no new board type. **Proven on the emulator: every
new build re-derived its node identity from its own node directory ("N boards derived from <title>'s own node
directory"), booted to attract and started a game** (`startcheck.sh` through rigbatch, stock cards, hidden, muted):
King Kong LE 1.01 attract 30 s / game 34 s, King Kong Pro 1.01 54/92, Avengers LE 1.12 28/31, Avengers Pro 1.12
40/44, Foo Fighters LE 1.05 40/157, Foo Fighters Pro 1.05 109/224; no node update walk, no version-mismatch alert.

**Extract and Write** (the app's own `SternExtractPipeline` / `SternWritePipeline`, headless): King Kong LE 1.01
extracted whole (2617 sounds, 6150 pictures, 469 videos, checksums); a Write with one sound and one scene picture
replaced built a 15.5 GB card in 12 min: the sound bank re-encoded and grown, the firmware's sound-record count
patch site found, 50 FINF validation records refreshed.

**Ports**: `port_derive.ensure_port` derives every one of the nine with nothing missing (`C:	mp\PAD-1555\derive`);
each greys the same 18 parts until proven. `tools/spike2_emu/modes/newbuild/checkjob.sh` is the Modes tab's Check
this game as a rigbatch job (the first piece of the new-build kit).

**Library**: the nine new cards are in `D:\Pinball\images\Stern\spike2`, the ten builds they replace (King Kong LE
0.97 and 1.00 both) in `older versions`; the card store holds the nine (`cardstore.ps1 fill`). Non-library cards get
only 25 GB of the store (`PAD_STORE_CACHE_MAX_GB`), so a sweep of cards outside the library re-copies them off D:
for every job.

**Rig 2** still has the stale `dump/ballfeed.off` (Oct 27): every batch parks it (`riglock.sh use 2 park-ballfeed`).

## Proving a new build's parts: what each proven set needs (gathered 2026-11-24)

The jobs that filled the proven sets (PAD-420's `bs_job`, `mb_job`, `lights_job`, `proof_job2`; PAD-710's
`place_job2` and `p710test.c`; PAD-747; PAD-474's `shake_job`; PAD-473's `wizgo.c`; PAD-1406's `coil_job`) lived in
`C:\tmp` and are gone. Nothing carries from a title's proven build to its next version: each key is proven again.
What each set's evidence lines say was seen (the recipe a job in `tools/spike2_emu/modes/newbuild/` re-creates):

| Set | Test mode lines | Proof |
|---|---|---|
| LAMPS_PROVEN | `light_all ff00ff solid`, a trigger | the shim's LED view (`dump/padled`) magenta on the addressed inserts during the mode only |
| MULTIBALL_PROVEN | `multiball 3 10`, `add_ball <mask> 1`, `shots <jackpots>`, `game_modes stack` | `multiball: 3 balls asked for`, a 4th ball, drains 4-3-2-1, `END (one ball left)`; tap a switch every ~1.5 s against ball search |
| BALL_SAVE_PROVEN | `ball_save 10`, `game_modes stack` | the drain served back with the mode running and scoring, a later drain `END (ball ended)`; a control run without the line ends on the first drain |
| STACK_PROVEN | `stack no` | `not started ...: one of the game's modes (<class>) is running` while a game battle runs (started through `block_start_<id>`) |
| PLACE_PROVEN | `in_place_of <id>`, `seconds 8` | `the game started its <name> (mode <id>) - this starts now in its place`, the game's STOP after, completion recorded |
| DONE_PROVEN | A: `in_place_of <id>`; B: `starts_on completed 1` | `done: player 1 completed the game's <mode>` and B's start |
| WITH_PROVEN | `starts_on with_game <id>` | `follow: ... started` / `START (the game's <name> started)` / `END (the game's <name> stopped)` |
| SHAKER_PROVEN | `shake start/shot/end` | `PAD_COIL_PROBE=1` `[coildrive]` pulses paired with the runtime's `shaker:` lines |
| WIZARDS_PROVEN | `game_wizard start <name>` in two files | `game wizard N (name): the game started it`, the second file refused |
| HELD_COILS_PROVEN | `coil_hold <name> 2000` | one `[coildrive]` command at the coil's own powers, the game's OFF ~2 s on |
| MAGNET / SCOOP | `magnet 2000` / `scoop_hold 4000` | `[coildrive]` hold and release times against a no-mode control |
| TITLE_SCENES | own screen + clip | HUD/bank md5s (`scene_write.profile_for`, `video_bank.parse`), magenta in glshot frames |

Install: a stage folder with `pad_mode.so` (= `modes/sdk/prebuilt/mode.so`), `game.port`, `mode.cfg`;
`PAD_SLOT=n tryit.sh install <stage>` before `job_boot`; `tryit.sh start K` / `stop`. Clear `dump/gamecheck.on`.
