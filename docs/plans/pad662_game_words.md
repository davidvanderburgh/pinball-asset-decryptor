# PAD-662: a mode's HUD words never sit on the game's own words

## The case

PAD-658, emulator run kiryu_r2 frame k15 (Godzilla LE 1.16): SUPER X2's instruction line lettered over the game's own
SHOOT TARGETS TO DISABLE BARRIER. That is Mechagodzilla's DEFENSE NEO BARRIER, a qualifying screen of the game's that
`pm_aside()` (battles, multiballs, the port's timed modes) does not know, and that is no foreground display
(`pm_display_covered()`), so neither moved our words.

## What the probe found (emulator, runs probe1/probe2, a temporary set_text logger since removed)

- The barrier is a BACKGROUND of the layered display (element 0x007b8db8, vtable 0x00645de8, the game's own looped
  clip MechaGodzilla_Loop), in the city's place. The game writes SHOOT TARGETS TO DISABLE BARRIER into a text node of
  that background's own scene (set_text from 0x15bc1c).
- Its other words come as foregrounds already covered: MECHAGODZILLA: OFFLINE / N MORE SPINS TO BRING ONLINE,
  MECHAGODZILLA: ONLINE / DEPLOYING TO BATTLEFIELD, DEFENSE NEO BARRIER ACTIVATED (the HUD waited for each).
- Since PAD-658 a mode that blocks the game's modes gets the barrier's place for its clip: `scene_show` of that scene
  is swapped for the video player, so the barrier's words are not drawn (why kiryu_r2's k15 does not come back with
  the blocking KIRYU). A mode that does not block (`give_way`, a mode file beside the game's modes, a qualification
  note) is drawn over them: run before1 p04, KIRYU with `game_modes give_way`.

## The watch

Every screen of the game's other than the main play comes up as such a background, so the runtime counts what is
DRAWN rather than a list of states: `pm_game_words()` is 1 while a background of the game's that is not the city has
its `scene_show` let through (not swapped for a clip of ours in its place, not under a full-screen clip of ours).
Decided once a tick (`gw_tick`): up after 300 ms of shows, gone after 4 ticks and 400 ms with none (a pause of the
whole machine is not "gone": run after1 flipped at 96150/96160 before this).

While it is 1:

- the kit HUD (examples and blocks modes) moves its title and line into the award line (y 262-405, which Stern's own
  screens keep clear) and hides its counters; the badge stays in its own slot (the second slot is a battle's only);
- a qualification note goes in the award line instead of the title place;
- a mode file's own screen is hidden (`aside keep` keeps it up), and a blocks mode's own screen and info line too.

Unlike `pm_aside()` it never ends a `give_way` mode and never holds a start.

## Proof

- Emulator, Godzilla LE 1.16, rig steps C:\tmp\PAD-662\steps\barrier.txt: before1 (base runtime, KIRYU give_way) p04
  shows the overlap; after2/after3 (this branch) p04 show KIRYU's lines in the award line over the barrier, counters
  aside; block1 (KIRYU blocking, this branch): its clip in the barrier's place, the HUD in its own places.
- Desk: tests/test_pad662_game_words.py (blocks HUD, give_way, the battle aside unchanged, notes, a mode file's
  screen, the runtime watch).
