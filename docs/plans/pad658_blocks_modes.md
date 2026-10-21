# Godzilla modes in blocks: King Caesar, Kumonga, Minilla, Kamacuras, and every C example rebuilt (PAD-658)

David, 2026-10-20: "Go through all of the godzilla films and scope out new modes from clips. Get some modes and clips
together for the creatures on the game playfield that don't have anything featured: king caesar, kumonga, minila.
see how these characters are featured on the right side of the playfield? use their shots in the modes for them.
make the modes in blocks so that I can edit it at will. I want to see some super cool light shows and shaker motor
integration for them. and we should use Lyman Sheets code as a baseline - make the modes go deeper and deeper, or
have a "cash-out" shot to end early and players should be rewarded with different rules and shots as they progress
into the modes. Also while we are at it, modify the Kamacuras mode to require more to start it and make its shots
more obvious. I'd like to convert all of our existing "intricate modes" to blocks so that I can play around with them
in more detail. Indicate to me what is lost by this back-conversion."

## What there is now

- **Blocks examples.** New mode ▸ Blocks lists whole modes made of blocks for the card's title, in two lists: the new
  ones, and the SDK's C examples rebuilt in blocks. Picking one adds it with its own clips, sounds and music cut from
  the person's own films, exactly as the C examples are (the same recipes and cutter); without the films it is added
  with the game's own callouts in their place. Only the examples that build on the card are offered (Godzilla
  Premium/LE 1.16 gets all 15; Pro 1.16 the ones whose shots and features a Pro has; Pro 1.15, an older build with no
  switch shots, shakes or game light shows, only GODZILLA ANGRY).
- Each example is one JSON file in `tools/spike2_emu/modes/sdk/blocks_examples/`, written from readable Python
  (`src_<slug>.py`, with `blk.py`'s short words for every block) by `make_examples.py`, which also checks each one
  against the card (`block_modes.problems`) and plays its desk scenarios. Its film recipe is `recipes/<slug>.json`.
- **The ports.** Godzilla Premium/LE 1.16 and Pro 1.15/1.16 name two playfield switches the game's shot dispatch never
  sends (MODE_API.md's census: the scoop sends nothing, Mecha Exit Top only 0x1) as shots: `Right scoop` (switch 53)
  and `Mecha exit top` (50). Proven on the emulator (below).

## Where the three live on the playfield (the right side)

Read off the playfield picture with the port's lamp places (`C:\tmp\PAD-658\lampov.png`): KING CAESAR stands beside
the POP BUMPER at the foot of the MECHA LANE (the right lane: Mecha Exit Bottom, switch 51); KUMONGA clings above the
right scoop on the shield platform's rim, where the Shield ramp spinner turns and the Big loop passes; MINILLA sits
beside the Mechagodzilla toy at the top of the Mecha lane (Mecha Exit Top, switch 50); KAMACURAS is under the right
scoop's three lights (SCOOP BB-*, switch 53). Each mode uses those shots.

## The four new modes (Lyman Sheats' rules as the baseline)

The baseline is PAD-379's Lyman-inspired pack (docs/plans/lyman_modes.md): a start that costs more each time
(Metallica's Sparky), stages with their own rules and shots (EHoH's House), regrowth that pushes back (TWD's walkers,
KING GHIDORAH's heads), hurry-ups, supers worth your history, cash out or push on (Metallica's Crank It Up, Batman '66's
cash the super or take +1x), and failing still pays.

Common to the three deeper-and-deeper modes:
- **A POT.** Each stage puts points in a pot; shots also score a little as you go.
- **CASH OUT** at the right scoop (it chases white with its own inserts once a stage is done): pays the pot and ends
  the mode. Finish all four stages for the pot twice over and a super. A drain or the clock (45 s a stage, fresh at
  every stage) pays a quarter of it.
- **Each time it costs more** to light again, and the stages get harder (faster beams, quicker regrowth, more strands).
- **Light shows** of their own for every moment (waking, each hit, each stage, the win, the cash-out, the loss), centred
  on the character's own place on the playfield; **the shaker** on every hit (soft to hard by weight), the game's own
  jackpot shake at each stage and its multiball shake at the win.
- Their HUD at the glass's edges: STAGE n OF 4, the POT ("CASH AT SCOOP"), this stage's count (its label changes with
  the stage), the clock in a badge; the ending title says how it ended ("KING CAESAR SLEEPS", "MECHAGODZILLA DEFEATED").

**KING CAESAR** (Godzilla vs. Mechagodzilla, 1974). The prayer: Pop bumper 1, Right return lane 2, the Mecha lane 3;
25 lights the Mecha lane (+15 each time). AWAKENING: the Pop bumper, Right ramp and Mecha lane each crack the shrine.
REFLECT: Mechagodzilla's beam moves across the Left ramp, Big loop, Right ramp and Building (faster each time he
wakes); its shot absorbs it (up to 3 charges), the Mecha lane fires them back, 5M a charge, three times. TAG TEAM: the
Godzilla target opens 6 s for a King Caesar shot: 8M, 16M, 24M. THE FINAL BLOW: three Building hits take
Mechagodzilla's head off.

**KUMONGA** (Son of Godzilla, 1967). 40 Shield ramp spins light the Big loop (+20 each time). THE WEB: the shield
platform turns toward the player; both shields, the centre powerline and both ramps are webbed (purple chase); each
torn pays more than the last, and she webs one again every 10 s (7, 5 the more she has been fought). STRANDS: every
spin of every spinner cuts one, 60 (+20). THE STING: a hurry-up at the Big loop from 20M down to 5M. FIRE: the Building
(Godzilla's ray) then the Right ramp (Minilla's) within 8 s, three times: KUMONGA BURNS.

**MINILLA** (Son of Godzilla, 1967; All Monsters Attack, 1969). Dad's call: 3 Godzilla target hits (+2) light the top
of the Mecha lane. SMOKE RINGS: four cyan shots, each ring twice the last. TAIL STOMP: the Godzilla target stomps his
tail, then a 12 s hurry-up at the Building, his first ray (or it sputters). GABARA: the bully moves between the ramps
and the Big loop every 5 s, 5 hits (+1), and gets one back if left alone 15 s. FATHER AND SON: a two-ball multiball, DAD
jackpots (Godzilla target, Building) and SON jackpots (Mecha exit top, Right ramp); a DAD then a SON is a HUG; back to
one ball, the pot and 20M a hug.

**KAMACURAS, reworked** (it was DESTOROYAH re-worded in the Heisei project: 30 Top spinner spins, +10, starting at once).
- *Requires more to start:* 50 Top spinner spins (+20 each time) light the RIGHT SCOOP, its own corner, and the scoop
  starts it.
- *Its shots are more obvious:* each mantis's shot CHASES in its ring's colour (far green, near yellow, close red,
  faster the closer), the HUD's line names where it is ("MANTIS AT THE LEFT RAMP"), and each one swoops in with its own
  clip (a mantis landing), screech and a ripple light show.
- The rules otherwise are DESTOROYAH's (Lyman's Horde): two at a time, 1x/2x/4x the closer the kill, waves of 3, 4, 5
  kills each paying its kills again, three strikes on Godzilla and the swarm wins, the biggest mantis at the Building
  for 25 s and a super worth every kill.
- Its film picks: the earlier recipe kept where right, its boss/won/lost clips that showed Kumonga replaced with
  Kamacuras (Final Wars' pylon death, the last mantis rearing), and the new swoop and lit cues.

## The films (scoped)

Searched by four scouts with the film toolkit (contact sheets at 10-20 s, then 0.5-1 s, the audio's roar/blast
ranking, the subtitle track for dialogue, the bed finder for loops), every pick looked at in a review sheet:
- King Caesar: Godzilla vs. Mechagodzilla (1974) whole; Final Wars' Mt. Fuji fight (1:18:40-1:20:35).
- Kumonga: Son of Godzilla (59:00-1:21:00), Destroy All Monsters (Mt. Fuji, 1:19:30), Final Wars (New Guinea, 1:13:49).
- Minilla: Son of Godzilla (hatching to the snow), All Monsters Attack (Gabara: 39:00-54:00).
- Kamacuras: Son of Godzilla, Final Wars (Paris, the pylon); All Monsters Attack's mantises are Son of Godzilla's
  stock footage.
Each recipe's "what" says what every cut shows; the scouts' notes (`C:\tmp\PAD-658\scout\<slug>\notes.md`) list
every span searched and the alternates. Other moments the films offer for later modes (`scouted.md` there): King
Caesar wrestling Mechagodzilla on the sea cliffs (mg74 1:10:40), Mechagodzilla's force field (1:14:22), the mountain
sealing with his eyes glowing (1:22:41), Final Wars' King Caesar flying kick (1:19:05); Kumonga webbing Kamacuras
and dragging it off (son67 1:11:05), Godzilla swinging Kumonga by its own strand (fw04 1:14:14); Gabara's electric
hands (ama69 47:54), Minilla flying in a dream (51:38); Kamacuras over Paris and the Eiffel Tower (fw04 22:58).

## The C examples in blocks, and what each lost

All eleven of the SDK's C examples are rebuilt (same slugs, so a project holds one or the other), each with its C's
clock, display priority, isolation from the game's modes, start rule, scoring, stages, clips/sounds/music cues, HUD and
light colours, its desk scenarios played against the C's proven flows. What is lost is in each example's `lost` list
(the JSON beside it), written per mode; the kinds that recur:

- **No random numbers in blocks.** Where the C picked a shot at random (DESTOROYAH's aggregates, KING GHIDORAH's moving
  head, MELTDOWN's heart, GODZILLA ANGRY's Baby, FINAL WARS' Monster X) the blocks take them in turn.
- **No 250 ms debounce** (the kit's): a target that bounces counts each time.
- **Fixed words.** Numbers come after the words in a line ("SPINS TO KIRYU 29"), counters show bare numbers (no "%",
  no "X2"), gauges are one colour.
- **The TOTAL is the runtime's** (3 s, the ending title and a line of fixed words) where the C wrote its own for 10 s
  with numbers in it.
- **A badge counts only the mode's clock**, not a timer of its own (KIRYU's overheat, DESTOROYAH's perfect form).
- **Every switch** is not a shot: GODZILLA ANGRY's RAGE meter and BIOLLANTE's sap count the shots the port names, so
  their counts were scaled down.
- **The kit's ledger** (which of the pack you played and won) is shared variables in blocks: the blocks FINAL WARS
  reads the blocks pack's, not the C modes'.
- Some run on Godzilla Premium/LE only where they name the centre shield or the shield platform (the C ran on a Pro
  with two shields).

## What the blocks gained on the way (any title)

- A **HUD counter block can change the counter's label** (the C modes relabel counters by stage).
- **An ending title**: a HUD title or line written in When the mode ends heads the TOTAL in the place of
  "<NAME> TOTAL".
- **The shot a lit mode starts on is that alone** (it was also a shot "while the mode is not running": KING CAESAR's
  starting Mecha lane counted 3 more prayer).
- **A Light block after the mode ended does nothing** (a timer still counting used to hold its insert for good).
- **Five more badge icons** for the blocks HUD: rage, crystal, snowflake, rose, claw (PAD-379's).

## Proof

- Desk: `tests/test_pad658_blocks_examples.py` (every example is its Python and builds on its card, the rebuilds keep
  their C's cues, the wizard's per-title list, adding with and without films, the ports' switch shots, every example's
  desk scenarios, and the generator's new pieces); the suites the generator touches (test_stern_block_modes,
  test_pad646_light_shows, test_spike2_mode_lamps, test_spike2_intricate_modes, test_pad611_mode_script).
- Emulator, stock Godzilla LE 1.16, hidden and muted, the Try it set built by Write's own code with the four new modes
  and their own clips, sounds and music cut from the films (`C:\tmp\PAD-658\rig`: build_set.py, job658.sh; runs in
  `C:\tmp\PAD-658\runs`): see the ticket's report for each run's lines.
