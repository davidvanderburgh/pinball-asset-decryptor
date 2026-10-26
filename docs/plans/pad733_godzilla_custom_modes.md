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

## David's v24 feedback (2026-10-26, Emulate on the v24 set)

- **"the character select is going wonky for a frame or two briefly showing the wrong character when transitioning
  with the right flipper"**. His recording, frame by frame: right off KUMONGA showed BIOLLANTE for 6 frames (30 fps)
  before DESTROYAH; right off MINILLA showed DESTROYAH before GIGAN. The game changes its portrait in two steps
  (Premium/LE 1.16 0x190acc, every frame with the cursor; its state word 0x7bb480: 4 shown, 5 going out, 3 coming
  in, the next word the place shown): the shown place's OUT, then the new place's IN, from the slot table's labels.
  A new monster stands on its place's portrait, so the game's out played on the PLACE's portrait (BIOLLANTE's under
  KUMONGA) while the runtime had already taken the new monster down. Now the monster left for another place stays
  drawn, its place's portrait hidden, until the game's out is over (`data roster_portrait_state`), and goes in the
  very step that starts the next place's in (`site roster_portrait_step`, wrapped; from the tick alone it went a tick
  late, its name over the incoming one for a frame). The other way round had its own (his recording too, GIGAN ->
  MINILLA on the left flipper: GIGAN's name going out showed round MINILLA's for 4 frames): a monster arriving from
  another place is drawn when that place's out is over, in the step that starts its own place's in - the game's
  own rhythm, the old one out, then the new one. LE 1.16 and Pro 1.16 read off their programs (Pro 0x18ce2c,
  0x7aedc0); Pro 1.15's program is not on this PC, so that port changes the portrait at once, as before.
- **"these HUD indicators need to duck when in super train loops (or whenever another mode has indication that is
  here)"**: the progress panel (PAD-680, the badges at the right edge) stepped down only for the game's battles.
  His Emulate log had `aside: a stock mode is running` for the whole of SUPER TRAIN LOOPS (95 s) with the panel up
  under its TIME LEFT. The panel is down now while any mode of the game's runs (`pm_aside`: a battle, a multiball,
  a timed mode), still up through the game's shot screens.
- **v25: "a failed mode (like king caesar) needs to track its shots that were successful so when we start the next
  time it resumes from where we were. this count also needs to show on the monster select screen like the other
  monsters"**: the card build gives each new tile a copy of place 0's "0/4" text (`PadSel_<slug>_Prog`, in the
  overlay, placed as the game's sits on its tile); `pm_roster_more_progress(done, of)` keeps the calling mode's count
  per player until the game ends and writes it at each opening (none before a report, none on a locked place); the
  blocks' *Selection screen count* (`roster_progress`). A variable reset each game keeps a battle's hits across its
  attempts (desk: lost at 1/2, picked again, resumed at 1/2).
- **A lost battle's count on its tile.** A battle lost is HELD by the city it was lost in (the game's slot state 3:
  0 open, 1 locked, 2 completed), and the game stamps that city - with its own "0/5" - on the PLACE's tile, the
  monsters booked against it padlocked: run fb3 (KING CAESAR lost with 2 hits in Tokyo, the screen in New York)
  showed TOKYO 0/5 on DESTROYAH's tile. Now the monster's tile wears the stamp and its count, the place's own tile a
  padlock of its own (`PadSel_Lock<n>`, its box hidden, its words blank). The stamps are lettered as PICTURES by the
  card build over place 4's box's stamp boxes: a copy of the box's text drawn outside the box stopped the game (run
  fb5 with blank copies, fb6 with their own words; fb7 with pictures ran on: TOKYO 2/5). His three battles report
  their count at every ball start too (a `ball_start` event script), so a tile shows 0/5 from the first ball, as the
  game's own do (run fb8).
- **His v25 asks for the modes** (the v25 versions in `PAD-733 notes\modes before v25 feedback`): KAMACURAS starts at
  the Right ramp (none of the game's 24 shot rules reads it; the Big loop is Super Train Loops, the Mecha lane Saucer
  Attack), lit lime; KING CAESAR's clock back up to 15 s on any lit shot or pop; its multiplier on the right counter's
  label, NEXT SHOT 1X/2X/3X, the middle cleared; the three battles keep their hits for the game (KUMONGA's torn webs
  stay torn, KING CAESAR resumes at its next shot) - runs out_fb_kamacuras2, out_fb_caesar3, out_fb_rematch_*.
- **v26 (his project): "hitting any shot of the mode (including spinners) when below 15 seconds should bring it back
  up to 15 seconds"** - KUMONGA (a web still up, every spin) and MINILLA (its lit shot), as KING CAESAR's (KAMACURAS
  has no clock, it ends on a drain): runs fb9_clk_ku (10 -> spin -> 15; 10 -> web -> 15) and fb9_clk_mi (10 -> 15).
  **"i just resumed kumonga with 4/5 shots already done, but only the spinners were lit"**: his log has the web left
  lit (`1 insert(s) held (shots 00000000_20000000): b040ff chase`) - Powerline center, a ONE-lamp white insert (lamp
  362), a small blinking light that cannot show purple; the other webs are three-lamp colour inserts. That web is on
  the Big loop now (lamps 386-388), and with one web left the line names it (TEAR THE LAST WEB: BIG LOOP); desk:
  resumed at 4/5, the Big loop lit purple when the start show ends, made: 5/5, won. Card v27.
- **v27: "For custom mode shots then, we should use shots that can be colored. Exceptions are for shots that are
  named on the screen."** The title profile carries `white_shots` (every insert of the shot one light: on Godzilla
  the Powerlines, Maser and Godzilla targets, Skill shot, return lanes, Shield ramp spinner) and the Modes tab notes
  each one a mode lights in a colour without a screen line naming it (`block_modes.white_shot_notes`). His 13 modes
  against it: KAMACURAS's mantis map moved off its four white spots (lane 1 Left ramp / Shield target center /
  Left spinner, lane 2's far ring the Top spinner; desk: the mantis over them, a kill on the Left ramp); SUPER X2
  names its Shield ramp spinner (CHARGE: SHIELDS OR SHIELD RAMP SPINNER); the rest light colour shots or name the
  white ones (SHOOT THE CENTER POWERLINE, FIRE: SHOOT THE MASER TARGET). Card v28.
- **v28 (his project): KING CAESAR "the final blow video ... it's showing mecha godzilla. also, the intro video audio
  screech seems like it's being cut short"; "there is only one Pop Bumper in the game (not plural)".** The final
  blow's award says BEAM REFLECTED, but its full-screen clip (won.mp4) was Godzilla tearing Mechagodzilla's head off
  with no King Caesar in it: reflect.mp4 (King Caesar bouncing the beam back) plays there now. The start's only
  sound was roar.wav, 1.35 s against a 6.0 s intro: rise.wav, four roars built from it (0, 1.25, 2.75, 4.25 s, the
  later ones lower), an echo, a fade to 6.0 s, its peak matched to roar.wav (-9.6 dB). POP BUMPERS / POPS -> one
  pop bumper (KING CAESAR, SHIN GODZILLA). Card v29.
- **v29 (on his machine, the card's own /dump read back):**
  - **"During the monster selection screen when I overlay the selected monster the respective indicators need to be
    blinking on the play field"**: the game blinks the shots of the battle under its cursor (the lamp probe: slot 0's
    Left spinner, Attack Mecha and Top spinner; slot 1's three powerlines; ffff00); on a new monster it blinked its
    place's battle's (KUMONGA, in slot 0's place) or nothing. A mode now names its monster's shots
    (`pm_roster_more_shots`; a block mode: every shot its Light a shot blocks light while it runs), and while the
    cursor is on its tile those inserts blink ffff00, every other shot insert on the playfield is dark (the Action
    button and the inserts of no shot stay the game's), and the game has them back as the cursor leaves, at the pick
    and at the ball's end. KING CAESAR: Pop bumper, Right ramp, Mecha lane, Left ramp, Building; KUMONGA: its five
    webs and both spinners; MINILLA: its four roving shots.
  - **"when the final mode video plays the scene text plays after that but only for a very brief portion of a
    second"**: two cuts. At a drain (three of his four KING CAESAR ends) the end of ball waited the TOTAL's 6 s and
    the lost clip took 5.7 of them: the TOTAL showed 0.25 s (card log: clip 262577-267773, ball end 268023). Now a
    drain whose ending plays a clip waits for the clip and then the TOTAL's 3 s, as the clock's end does (10 s, the
    runtime's most). And the final blow asked its clip and then ended, so its 3 s TOTAL ran out under the clip, and
    the battle's hand-back after the clip brought the game's battle-over display within 15 ms (run fb2_caesar): a clip
    asked as a mode ends counts as its ending's now (the TOTAL 3 s after it), and the battle is handed back once the
    mode's ending hold is over, not at the clip's end.
  - **"The game also randomly went into ball search mode when I restarted King Caesar for the second time"**: the
    game's ball-search countdown (Premium/LE 1.16 0x7d36a4, 10 s) runs on while a ball sits in the scoop; its own
    holds put it off every tick (`ball_search_delay`, 0x379f0c), ours did not. A pick's 6 s start clip left about 4 s
    at the kick-out, so a ball that scored nothing in the next 4 s set the search off (his third start held 6067 ms;
    the building's floor moves after it fit search steps). Both of our holds now put it off every tick
    (`site ball_search_delay`, `data ball_search_time`; LE 1.16 and Pro 1.16): rig runs bs_long (a 16 s hold searched
    with the ball still in the scoop) / bs_long_fix (10.0 s left at the kick-out), bs_hits (search 3.4 s after the
    kick-out) / bs_hits_fix (none).
- **v25: "the cursor needs to start in the top-left most mode. right now, it's in the top-right most mode"**: the
  game's open (0x1911dc) puts the cursor on the next open place after the one last played. With new monsters on the
  screen it is wrapped: the game's open runs, then the cursor goes on the first open entry in the screen's order (the
  top-left tile, or the first after it a pick can take), before the screen's first step.
- **His project's modes** (the v24 versions in its `PAD-733 notes\modes before v24 feedback`), saved through
  `block_modes.save`, checked with `problems()` and the card's checks, emulator-proven (out_fb_kumonga,
  out_fb_kamacuras, out_fb2_caesar, the stock Heisei 1.99D card, no aborts):
  - KUMONGA ("i miss the 'shoot the spinner to tear the web'"): the Left and Top spinners blink white as an optional
    shot; each spin adds 100,000 to the next web torn (the final blow too), shown as NEXT WEB +, then back to 0; a cue
    every 10 spins. Not the Shield ramp spinner: KUMONGA turns the shield toward the player, its spinner side away.
    Run: 12 spins -> SPINNER BONUS 1,200,000 on the next web; total 19,000,000 as designed.
  - KAMACURAS ("should not start at the scoop ... screechy ... two-ball multi-ball and end the mode if a ball
    drains"): the Top spinner lights the Big loop (the scoop is the game's battle selection; no other mode starts at
    the loop), a 2-ball multiball with a 10 s ball save, and after the save a ball down to one ends it as lost (two
    checks a second apart; the blocks have no "save over" hat and its 8 timers are used). The screech was
    swoop.wav, 95% of its energy over 2 kHz, on every ring a mantis came closer: now only on a landing, an octave
    lower and low-passed. Waves of 2/3/4 kills (were 3/4/5) so the boss is in reach of one multiball.
  - KING CAESAR ("hitting the pop bumpers at any time increases the value of the next shot (up to 3x ...)"): a pop
    makes the next lit shot 2X, a second 3X (the most); used by the next lit shot, the final blow too, then 1X. Run:
    three rapid pops raised it once to the cap; total 42,000,000 as designed.
