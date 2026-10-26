# PAD-733: Godzilla custom modes - the pick's choreography, the rematch line, the battles' shape

David, 2026-10-25 (his own ticket, emulator runs of his Heisei 1.99D card v23, then notes added while it was worked):

1. "when we do a monster selection the frame that is shown is always showing biolante being selected when the menu is
   closing"
2. "if a mode is failed and you come back to start it again it still says fight biolante again when it's supposed to be
   kumunga"
3. "the custom modes that start at the scoop through monster selection should no longer increment and be shown on the
   HUD for getting them accessible by the means we had before" (the KING CAESAR and MINILLA countdowns)
4. "analyze frame by frame how regular monster modes are started and imitate them for our custom modes ... after
   selecting the custom monster in the menu I seen it flashed to the hud before showing the video" - "make sure the
   custom mode choreography looks extremely clean (transitions are flawless)"
5. "I also failed out of the Minilla custom mode mission and chose to stay in Tokyo and after that I could not relight
   the scoop to start the mode again"
6. "check the logs and make it so that you can replay exactly what I saw ... look for inconsistencies in how screens
   transition and fix them"
7. "some of the modes are too similar too each other with too many stages. The custom battles don't need so many
   stages. Make it similar number of shots to the other original modes"

Every finding below is from the emulator (muted, hidden rigs) on the Heisei 1.99D card with Try it's set of David's
project, built once from main and once from this branch (C:\tmp\PAD-733, runs out_*), filmed at 0.25x where it is a
transition. Stock Premium/LE 1.16 and Pro 1.16 were filmed for the game's own pick.

## What was found

- **1 was fixed on main already (PAD-730, v1.258.2).** David's card v23 was built at 09:30, before PAD-730, and the
  emulator runs a card's own runtime. Main's code on the same card keeps KUMONGA on the screen through its whole fade.
- **4 - the game's own pick, frame by frame** (Heisei, LE 1.16 and Pro 1.16 alike): the screen fades (gone by 0.44 s),
  the map zooms into the frame and holds, and 2.0 s after the pick the battle is on the glass in its full-screen
  intro, its title lettered over it - no HUD before it. The close is one of the game's DISPLAY EFFECTS (LE 1.16: 132,
  priority 196, from the pick to +1983 ms; 133 after a STAY on the city screen, +1517 ms); as it ends the game pauses
  its video player. **A new monster on main**: the same fade and map, then the city's HUD from 2.1 s, the mode's HUD
  over the city from 3.06 s (`roster_start_after_ms 3000`), and its intro only at 3.57 s (a blocks mode's full-screen
  clip waits `PA_CLIP_AFTER_MS`, 500 ms, for a shot's own clip - there is no shot at a pick). David's own log says
  the same: pick 123387, START 126405. Started at the pick itself, the intro hides the close (run a0); started at
  1.95 s it is gone with the close's end (a1950: "the game built 1 frame while our full-screen clip played").
- **2 - the words are the city screen's.** `STAY IN:` / `TRAVEL TO:` / `TO REMATCH %s` are numbered lines 3748-3750
  of the game's text table on Heisei 1.99D, Premium/LE 1.16, Pro 1.16 and Pro 1.15 (read off each program), the `%s`
  the held battle's own name. Main, MINILLA lost in a city already beaten: `TO REMATCH DESTROYAH` (run b5b).
- **5 - a clock that ran out was a WIN.** David's three monster battles had no "End the mode, the battle won" block,
  so by PAD-706's rule the mode's own end (its clock) won the battle: on main MINILLA's clock ran out, the player saw
  MINILLA CRIES, and the game played its won-battle sequence (ANGUIRUS JOINS THE BATTLE, the power-up pick), the map
  said GODZILLA CONTROLS TOKYO and the next city screen offered `TO CONTINUE BUILDING CARNAGE BONUS` - nothing left to
  replay (run b6b). (A drain was a loss and did replay: runs b4, b5b.)
- **3**: on main the old starts still counted in normal play: the mecha lane put up HIT THE POP BUMPERS - 28 TO WAKE
  KING CAESAR, and corner countdowns for MINILLA and KING CAESAR (run hudb).
- **7**: all three were the same four-stage shape (a first stage of shots, then three more, a pot cashed at the
  scoop); the game's battles are SHOT PROGRESS n / 5 on a 60 s battle clock.
- **6**: his last emulator session's logs (C:\tmp\PAD-733\david_run: mode.log, gzwatch.log with every switch change
  on the game's clock) show the 3 s gap at both his picks. A replay driver (C:\tmp\PAD-733\rig\swreplay.py, a proof.sh
  step) drives his 315 switch changes into a rig on the guest's own clock: run rep1 on his v23 card started the game
  and opened the selection screen at his exact moments (+4.56 s alignment, within a few ms), then diverged at his
  first pick - the rig's saved machine state (NVRAM: the last place played) is not his, so the cursor started
  elsewhere. An exact replay needs the NVRAM as the session started, which nothing records yet (follow-up).
- **The machine's own SD card** (read once elevated, read only: its /dump, /data and system partitions copied to
  C:\tmp\PAD-733\sd): its mode runtime is byte for byte the v23 card's (md5 625ed5d3...), so the machine ran the
  pre-PAD-730 code. Its mode.log (2026-10-25 19:37-20:00, three games) shows the same faults: every pick started 3.0 s
  after it (MINILLA 244427 -> START 247456, KUMONGA 504160 -> 507175, MINILLA 813611 -> 816627); in the third game
  MINILLA ended `time ran out` and the game logged `MINILLA's battle won ... counts as beaten in city 0 ... completed 1`
  - ask 5; KUMONGA lost by a drain did come back by the city pick (`plays again`, 610512), the rematch that read
  TO REMATCH BIOLLANTE; KING CAESAR and MINILLA's old idle scripts ran in normal play (`PAD-690 - the plunge: not
  counted` at every plunge) - ask 3. No error, crash or refusal in its 1560 lines.

## What changed

- **Runtime** (`pad_mode_runtime.c`): `pm_roster_closing()` (pad_mode.h) - after a pick a mode took, the effect that
  has the screen (above the idle priority) is the close, and the screen counts as closed the tick another has it; the
  port's `roster_start_after_ms` (now 2500) is only the most it waits; checked before the modes' ticks. The game
  pauses its player a moment after the effect ends (within ~45 ms: run g_kumonga's intro was over 44 ms in and the
  backdrop loop took its place under the HUD), so a full-screen clip it stops in its first 300 ms, started within 300 ms
  of the close, is played again once at once - it stays on meanwhile, so neither the HUD nor the loop gets a frame. The city
  screen's rematch line (`value roster_rematch_line 3750`, a `TITLE_VALUES` value) names a new monster lost in the
  player's city while that city holds its battle; put back otherwise and at the game's end. A lost monster replays
  only in the city it was lost in. `message_borrow` (by line) split out of `pm_message_set`.
- **Blocks** (`block_modes.py`): a battle pick's script runs on `!pm_roster_closing()`, its start clip in that same
  tick (`clip_after` 0, then `own_clip_due()`). **Mode files** (`mode_file.c`): the same wait, no clock.
- **Ports**: LE 1.16, Pro 1.16, Pro 1.15 - `roster_start_after_ms 2500`, `roster_rematch_line 3750`; recipes rebuilt
  (LE and Pro 1.16 from their programs; Pro 1.15's archival card was not copied: its recipe's entries hash updated -
  a recipe holds only sites, globals and scenes, which did not change, as the LE rebuild showed key for key).
- **David's project** (`HEISEI v1.99D + daveyvandy modes`, the originals in its `PAD-733 notes`): KUMONGA, KING CAESAR
  and MINILLA rebuilt as the game's battles - 5 hits on a 60 s clock, the 5th the final blow (End the mode, the battle
  won), the clock or a drain a loss - each with its own pattern: KUMONGA's five webs lit at once (any order); KING
  CAESAR one lit shot at a time in order (pop bumpers, right ramp, mecha lane, left ramp, the Building); MINILLA one
  lit shot that roves around the ramps, the big loop and the Building every 4 s. Their old idle starts are gone (ask
  3). Clips, sounds, shows, music and HUD look kept.

## Proof (after, this branch's set)

The PAD-733 artifacts hold the before/after strips (pick_transition, stay_transition, rematch_line, clock_out,
old_start_hud, battle_shape; reference_stock_pick_transition is the game's own pick). Final set (tryit_after5):
- h_kumonga: `the selection screen has closed 1983 ms after the pick (its display effect 132 is over)`, START and its
  intro in that tick, `"PadMode_kumonga_Intro" was paused 27 ms in by the game's close ... played again`, the whole
  intro on the glass (276 frames, none without it), then the five webs: `KUMONGA's battle won`.
- h_minilla: the same at the pick (1998 ms, replayed 27 ms in); lost by a drain in a beaten city: `the city screen's
  rematch line names MINILLA`; STAY: effect 133 over at 1517 ms, replayed 29 ms in; five roving hits:
  `MINILLA's battle won`, `the rematch line is the game's own again`.
- h_clock: `MINILLA END (time ran out)` -> `battle lost` -> TO REMATCH MINILLA -> it plays again.
- x_caesar (after3): the five shots in order, won, then the game's own GODZILLA CONTROLS TOKYO.
- hudb / huda: the old start shots' HUD on main / nothing after.
