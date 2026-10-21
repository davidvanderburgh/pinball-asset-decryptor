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


### Each mode, what it lost (its example's `lost` list)

**KING GHIDORAH** (`ghidorah_heads`, Premium/LE):
- The heads' shots have no 250 ms debounce: a ball rattling on a target is several hits (the C counted one hit a quarter second per shot).
- A start from the tab's Start mode now counts as the ball's and the game's start too (the C counted only the three powerlines).
- When a run will not count (it already ran this ball, or twice this game) the powerlines say nothing; the C logged why once.
- The HUD shows a severed head's health as 0, where the C showed X; and in the final blow the left and right counters stay up (0, SEVERED) beside the SUPER JACKPOT counter, where the C hid them.
- Awards say their numbers after the words: LEFT HEAD SEVERED 5,000,000 / +10 SECONDS, where the C put 5,000,000   +10 SECONDS under LEFT HEAD SEVERED.
- The ending title (GHIDORAH DEFEATED or GHIDORAH ESCAPES) and its total stay up 3 s, the runtime's: the C kept them 10 s.
- The ending has no KING GHIDORAH TOTAL under the total: the C put those words there.
- The lit head moves on its own 8 s timer, and moves a tick after a sever (the C moved it in the same tick); its inserts change a tick after a hit too.
- The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own shows where the game has no Strobe burst or Colour fade (a Pro 1.15 has none of the game's shows, nor a MASER READY insert); a blocks program cannot ask whether the game has a show. Its own three shows are kept under Light shows (Ghidorah start, Ghidorah won, Ghidorah lost), not run, to swap in.
- The blocks pack keeps its own FINAL WARS ledger in shared variables ('ghidorah played', 'ghidorah won'), which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read the C's ledger.

**OXYGEN DESTROYER** (`oxygen_destroyer`, Premium/LE):
- The value falls on a timer the blocks keep in milliseconds, but the clock the HUD badge shows is whole seconds: a hold-off puts the clock to the next whole second above the value's time (the C counted both from one drain, and a stalled frame drained at most 100 ms).
- The Godzilla target has no 250 ms debounce: a ball rattling on the captive ball can use up two hold-offs (the C counted one hit a quarter second).
- The Left ramp blinks faster as the mode's clock runs down (the blocks' Hurry pattern) and changes colour once a second; the C's blink followed the value itself, every tick, with a flicker in the last 3 s.
- The HUD keeps one counter: HURRY-UP, then SUPER JACKPOT; the C showed a COLLECTED counter beside it in the super jackpot (a counter the HUD does not have from the start cannot appear later). Its gauge is one blue, where the C's ten segments went from deep to pale blue, and a note says SPINS TO GO 24 where the C said 24 SPINS TO GO.
- The ending title (GODZILLA IS GONE, OXYGEN DESTROYER or THE OXYGEN IS GONE) and its total stay up 3 s, the runtime's: the C kept them 10 s.
- The ending has no OXYGEN DESTROYER TOTAL under the total: the C put those words there.
- The cooldown is 15 s on a timer that a new ball clears (the C kept each player's own across balls), and a start from the tab's Start mode now counts toward the 3 a game.
- The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own shows where the game has no Playfield wave or Blue fade (a Pro 1.15 has none of the game's shows, a Pro 1.16 no Playfield wave); a blocks program cannot ask whether the game has a show. Its own three shows are kept under Light shows (Oxygen start, Oxygen won, Oxygen lost), not run, to swap in.
- The blocks pack keeps its own FINAL WARS ledger in shared variables ('oxygen played', 'oxygen won'), which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read the C's ledger.

**MASER BARRAGE** (`maser_barrage`, Premium/LE):
- The start counts every Maser target hit this ball, with no 250 ms debounce, and the chain's shots have none either: a ball rattling in the Left ramp's entrance can count twice (the C counted one a quarter second).
- The next shot's blink quickens once a second as its window closes (the C every tick), and the HUD shows the multiplier as 2 where the C showed X2, and the window as 0 with NO CLOCK YET where it showed -.
- Awards say their numbers after the words: LEFT RAMP X 2 / NOW THE RIGHT RAMP and BARRAGE JACKPOT 10,000,000 / NOW X3, where the C said LEFT RAMP X2 over 2,000,000 and 10,000,000   NOW X3 under BARRAGE JACKPOT.
- The ending's line under MASER BARRAGE TOTAL puts the count last (BEST X3  -  BARRAGES 2) where the C said 2 BARRAGES  -  BEST X3, and says BARRAGES for one too.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- The counters are in the film recipe's order (MULTIPLIER, BARRAGES, WINDOW); the C drew MULTIPLIER, WINDOW, BARRAGES.
- The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own shows where the game has no Insert chase or Colour fade (a Pro 1.15 has none of the game's shows, a Pro 1.16 no Insert chase); a blocks program cannot ask whether the game has a show. Its own three shows are kept under Light shows (Maser start, Maser won, Maser lost), not run, to swap in.
- The blocks pack keeps its own FINAL WARS ledger in shared variables ('maser played', 'maser won'), which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read the C's ledger.

**FINAL WARS** (`final_wars`, Premium/LE):
- No randomness in blocks: Monster X moves to the next target in turn (Powerline left, center, right, the Godzilla target, round again) every 3 s and when hit, where the C picked another target at random.
- The ledger is six shared variables (ghidorah / oxygen / maser played and won) the blocks KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE set; the C modes' own ledger (kit_ledger) is a different store, so the C versions of those modes do not light this blocks version, nor the other way round.
- It lights on the next shot after it qualifies (blocks only look while a shot is made), where the C looked twice a second; and the FINAL WARS IS LIT note shows then, not 7 s after the other mode's total.
- The lit Building pulses as any lit mode does (the runtime's light), where the C pulsed it only while none of our modes ran and not between balls.
- The ending title (GODZILLA WINS or THE XILIENS WIN) and its total stay up 3 s, the runtime's: the C kept them 10 s.
- The ending has no FINAL WARS TOTAL under the total: the C put those words there.
- The game's own light shows (Strobe storm, Red and blue fade) always play at the start and the end; the C played its own start/won/lost shows on a game without them (Godzilla LE has both, so the C never did there).
- The jackpot shake starts as the mode ends rather than being run out past the end (pm_shake_outlast).
- Godzilla LE only: the program names the center shield target (Godzilla Pro has two shields), where the C simply had one shield fewer there.

**ANGUIRUS** (`anguirus_assist`, Premium/LE):
- He joins on the first shot after one of the game's own modes begins (blocks only look at a shot), where the C looked twice a second; and blocks cannot tell a battle from the game's other modes: he joins any of its modes while one ball is in play (its multiballs are left out), where the C joined only kaiju battles.
- He leaves within a second of the game's mode ending (an Every second check) and his total shows at once for 3 s; the C waited for the battle's own total screen first, then kept his 4 s in view.
- As he leaves with the battle, ANGUIRUS TOTAL is the title over his total: the C put it under the total, with no title.
- Ended while the battle still runs (a stop, another of our modes), his total shows alone: the C put ANGUIRUS RETREATS under it. His HUD's title and line are the battle's while it runs, so a title block cannot say it.
- His screen is not shared in moments: with the HUD on he holds display priority 180 the whole time he runs, where the C held it only for each moment (entrance, a spike, the roll, a rolling attack) and gave the battle its own displays between them.
- His entrance (clip, music, words) comes a fixed 2 s after he joins; the C waited until the battle's start screen had gone (up to 12 s). His music starts as he joins, not with the entrance.
- The SPIKES gauge keeps its label: the C relabelled it ROLLING! while he rolls.
- The Big loop's blink quickens once a second (400, 200, 100 ms), where the C stepped it every tick.
- Godzilla LE only: the program names the center shield target; the C charged with two spikes on Godzilla Pro 1.15/1.16's two shields.
- The C's total gave way at once when another of our modes asked to start; the blocks' runtime TOTAL runs its 3 s.

**MELTDOWN** (`meltdown`, Premium/LE):
- No randomness in blocks: the HEART starts at the Left ramp and moves in turn (Left ramp, Right ramp, Building, Big loop) every 8 s and when hit, where the C picked another shot at random.
- The core is looked at once a second (an Every second script), so it rises a whole 1% or 2% each second and the MELTDOWN blink quickens on the second, where the C stepped them every tick.
- No timer badge: the MELTDOWN 20 s is a timer the line counts (SUPER JACKPOT AT THE BUILDING: 17), where the C counted it on the MELTDOWN badge (a blocks badge counts only the mode's own clock, and this mode has none).
- The HUD shows the core as a number (25), not 25%; the JACKPOTS counter has no SUPER value under it; the CORE gauge is one colour (the C's ran yellow to white-hot); the lines lost their double spaces to fit the 40 letters a blocks HUD line holds.
- The ending's line under MELTDOWN TOTAL puts the jackpots last (1 MELTDOWN SURVIVED  -  JACKPOTS 6) where the C said 6 JACKPOTS  -  1 MELTDOWN SURVIVED, says JACKPOTS for one too, and past 3 meltdowns says only the jackpots.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- The captive ball counts toward lighting it while another of our modes runs, where the C left the shot to that mode.
- The ready light is the runtime's lit mode (held ball after ball), where the C pulsed MAGNA GRAB only while nothing else owned the playfield.
- One ball left is checked once a second after 18 s (two looks in a row), the C's 2 s after the 15 s ball save and 3 s grace; and the C noted whether a second ball was ever served.
- Godzilla LE only: the program names the center shield target (Godzilla Pro has two shields).

**GODZILLA ANGRY** (`godzilla_angry`, Premium/LE):
- The RAGE meter counts only the shots this program names (the ramps, Big loop, Building, center powerline, captive ball and Maser): the blocks never see a switch's own hit, where the C counts every playfield switch. So the meter is a fifth as long (stretches of 20, 25, 30, 35, 40 hits, 5 more each after a multiball, where the C has 100 to 200 and 25 more), and the SUPER JACKPOT grows 10,000 a named shot rather than a switch.
- No points while the mode is not running: the C pays 1,000,000 (+500,000 a stretch) at each RAGE stretch's end; the blocks' Score only scores while the mode runs, so a stretch is a note, a roar and a light show only.
- The RAGE meter is not on the glass: the C draws it as a bar with GODZILLA RAGE and its percent at the top right all game; a blocks HUD shows only while the mode runs, so the meter is the notes alone (every quarter of a stretch, and RAGE n PERCENT at its end).
- No ball save: the C gives a 5 s ball save at the start and keeps one running from the first lock, so a drain with locks sends the locked balls straight into the multiball. In blocks a drain ends the chase; the place, its locks, the jackpot and the super wait for the next start at the Building (as the C does for a drain with no lock).
- No randomness: BABY starts at the Left ramp and moves to the next shot in turn (Left ramp, Right ramp, Building, Big loop) every 10 s and when hit, where the C picks another at random.
- The ending's line after a multiball puts the BABY jackpots last (5 LOCKS  -  BABY JACKPOTS 2) where the C said 2 BABY JACKPOTS  -  5 LOCKS, and says JACKPOTS for one too.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- The instruction line counts the place's shots still to make ("KYOTO: LIT SHOTS TO GO 3") where the C names them while they fit ("OSAKA: BIG LOOP, BUILDING"); the award for a shot says the place and the points, and a start on the trail says THE TRAIL AGAIN with its locks, not the place's name.
- The badge counts the place's 30 s in the chase and BABY's next move (10 s) in the multiball, where the C hides it in the multiball; a place's clock with locks turns into the multiball with a second left, not at 0.
- One display priority, 180, throughout: the C takes 190 (a wizard's) for the multiball.
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro, playing its own start and end shows where the game has no Insert chase or Ember fade; a blocks program cannot ask whether the game has a show. Its own two are kept under Light shows (Angry start, Angry end), not run, to swap in.
- No tilt rule of its own: the C stops the meter after a tilt until the next ball; here the tilted ball's shots still count.
- Another mode of ours ending on the Building does not keep it from starting this one on that same shot (the C waits 300 ms after another of ours ends).

**SPACEGODZILLA** (`spacegodzilla`, Premium/LE):
- No points while the mode is not running: the C pays 250,000 a crystal times its number (250,000, 500,000, 750,000) as it is planted; the blocks' Score only scores while the mode runs.
- A lit lock does not blink the Big loop purple: the blocks light inserts only while the mode runs, and a mode lit at a shot starts on it, so only the full set (three crystals, waiting for the game's mode to end) blinks there; the notes say LOCK IS LIT and SHOOT THE BIG LOOP.
- No badge for the super's 20 s window: the badge counts the mode's own clock, and this multiball has none, so the window shows as the line SUPER JACKPOT: SHOOT THE BIG LOOP and the Big loop blinking white fast (the C blinks it faster as the window runs out).
- The super's added ball is asked as a multiball of one more ball than are in play (the blocks have no add-a-ball block), with its 10 s ball save.
- Another mode of ours running does not stop the powerlines lighting locks or the Big loop planting crystals (the blocks cannot tell one of our other modes runs; the C waits for it). A multiball still stops them.
- The ending's line puts the jackpots last (1 SUPER  -  JACKPOTS 7) where the C said 7 JACKPOTS  -  1 SUPER, says JACKPOTS for one too, and past 3 supers says only the jackpots.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- No light show of its own at the start and the end where the game has none (the C falls back on its own when the game's Strobe storm or Blue fade will not play): the blocks play the game's.
- A tilt or the game moving on ends it as any blocks mode ends (the C also ends at once without its total).

**KIRYU** (`kiryu`, Premium/LE):
- The badge always counts the mode's 40 s clock: while the reactor overheats the C counted the overheat's 12 s there instead. The overheat's seconds now ride on the line (OVERHEATING! FIRE NOW 9).
- The counters show bare numbers: CHARGE 109 where the C showed 109%, MULTIPLIER 2 where it showed X2.
- The gauge stays one ice blue labelled CHARGE: the C shaded its ten pips from blue to white and relabelled it OVERHEAT while overheating and FIRED after the shot.
- The spin count note reads SPINS TO KIRYU 29 (the number after the words) where the C said 29 SPINS TO KIRYU.
- When the clock runs out at 100% or more Kiryu still fires on its own (x1, 10M, no bonus), but at the end itself: the C played the shot's 4-second moment (its clip and frost light show) before KIRYU WINS.
- After firing, the badge keeps counting (the clock is only held at 5 s or more) where the C stopped and hid it for the shot's moment.
- The ending (KIRYU WINS or KIRYU IS DOWN, its line and the total) stays up 3 s, the runtime's: the C kept it 10 s.
- No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks count every report.
- A hit no longer answers by itself: the C flashed every charging shot's inserts white and played the game's climbing orchestra hit (PAD-415).
- Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does for a drain or a tilt).
- Its own start and end light shows are gone: the C used them only on a game without the game's Strobe burst and Blue fade, which Godzilla Premium/LE has.
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro (its Right spinner, no Shield target center), and a blocks program names one spinner.

**BIOLLANTE** (`biollante`, Premium/LE):
- Only the port's named shots feed the sap: the C scored every playfield switch (its 0x1 switch dispatch), rollovers and other unnamed switches included.
- The counters show bare numbers: BANKS CUT 2 where the C showed 2/3, and PER SWITCH 125 over THOUSAND SAP where it showed 125K over SAP (an edge counter holds about four characters).
- The gauge stays one vine green labelled VINES: the C shaded its six pips from green to rose and relabelled it BEAST in the beast form.
- The ramp count note reads RAMPS TO BIOLLANTE 5 (the number after the words) where the C said 5 RAMPS TO BIOLLANTE.
- The shield vines light at once: the C lit them only once the shield platform had turned to face the player.
- A vine's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C waited 4 s from the last one it played.
- The ending's line puts the switches last (2 BANKS CUT  -  SWITCHES 14) where the C said 14 SWITCHES  -  2 BANKS CUT, and its SWITCHES are the named shots made (the C counted every switch).
- The ending (BIOLLANTE IS FREE or BIOLLANTE WITHERS, its line and the total) stays up 3 s, the runtime's: the C kept it 10 s.
- No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks count every report.
- A hit no longer answers by itself: the C flashed every scoring shot's inserts white and played the game's climbing orchestra hit (PAD-415).
- Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does for a drain or a tilt).
- Its own start, win and end light shows are gone: the C used them only on a game without the game's Playfield wave and Red and blue fade, which Godzilla Premium/LE has.
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro, where its shield bank is two targets.

**DESTOROYAH** (`destoroyah`, Premium/LE):
- No randomness in blocks: each aggregate's next shot is dealt in turn from a counter that runs all game (the far ring left, center, right, the near ring and the close ring likewise, skipping the shot the other aggregate stands on), where the C picked one at random. A player who learns the order can wait for it.
- Aggregates come to the shield targets at once: the C sent none there until the shield platform had turned to face the player (or ever, with the shields fixed away).
- The perfect form's 25 s are not on the badge (the blocks' badge counts the mode's clock, and this mode has none): the Building's blink still quickens as they run out.
- The counters show bare numbers: WAVE 2 OF 3 and KILLS 1 OF 4 where the C showed 2/3 and 1/4, and the KILLS counter no longer says what the wave has paid so far (WAVE 2.25M).
- The line puts the kills to go last (WAVE 2: CLOSER PAYS MORE  -  TO GO 3) where the C said WAVE 2: 3 MORE  -  CLOSER PAYS MORE.
- The gauge has five pips all along, one colour: the C showed as many pips as the wave needs (3, 4, 5, then the perfect form's 3), shaded yellow to red.
- A kill's award puts its value after the words (FAR KILL X1 1,000,000) where the C put it under them.
- A kill's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C waited 4 s from the last one it played.
- An aggregate that would advance onto the other's shot takes the next one in turn: the C waited half a second and tried again.
- The ending's line puts the kills last (WAVE 3  -  KILLS 12) where the C said 12 KILLS  -  WAVE 3.
- The ending (DESTOROYAH DEFEATED or DESTOROYAH WINS, its line and the total) stays up 3 s, the runtime's: the C kept it 10 s.
- No debounce: the C counted the same target once in 250 ms; the blocks count every report.
- A hit no longer answers by itself: the C flashed every kill's inserts white and played the game's climbing orchestra hit (PAD-415).
- Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does for a drain or a tilt).
- The super jackpot's shake is cut short at the end: the C let the game's jackpot shake run out past it.
- Its own start, win and end light shows are gone: the C used them only on a game without the game's Strobe burst and Ember fade, which Godzilla Premium/LE has.
- For Godzilla Premium/LE only: the C also ran on Godzilla Pro, with two shield targets.

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
- Emulator (`C:	mp\PAD-658ig`: build_set.py builds the Try it set with Write's own code, job658.sh drives it on
  `rigjob.sh` with real switch presses; runs and glass shots in `C:	mp\PAD-658uns\<run>`), hidden and muted,
  every run segv 0, fatal 0:
  - **Godzilla LE 1.16** (a1 without media, a2/b2 with each mode's own clips, calls and music cut from the films):
    KING CAESAR lit by 25 real pop bumper hits at the Mecha lane ("lit at Mecha exit bottom"), started by it, the
    Pop bumper, Right ramp and Mecha lane took stage 1, the right scoop cashed it out (12,000,000); KAMACURAS lit at
    the right scoop by 50 Top spinner spins and started there, the mantis HUD line and chasing lights on the glass;
    KUMONGA lit by 40 Shield ramp spins, started at the Big loop, the web torn on the shields and ramps, cashed out at
    the scoop (28,700,000); MINILLA lit by three Godzilla target hits at the top of the Mecha lane (the new switch
    shot), all four stages by real shots, the game served its two-ball multiball, two HUGs, back to one ball it ended
    won (160,500,000). Its own music bed, calls and clips (intro full screen, events behind the HUD) played.
  - **Godzilla Pro 1.16** (pa1, pb1, the same four adapted to the Pro: its Right spinner, no shield platform): every
    one started by its rule the same way, KING CAESAR and KUMONGA cashed out at the scoop, MINILLA ran all four stages
    to its multiball win (164,000,000).
  - Found on the rig and fixed: Gabara moving off the Left ramp after 5 s as designed (the drive was wrong, not the
    mode); the stage-up shake refused while a hit's shake still ran (stages now change 0.7 s after the hit); a counter
    label that could not follow the stage (the new label option); KAMACURAS's 180 s clock showing 99 on the badge (it
    has no clock now, as DESTOROYAH's C had none); the cash-out ending the mode on the scoop switch itself, so the
    game's own scoop award took the glass over the cash-out clip (the ball is now held in the scoop and the mode ends
    1.5 s later: run pa1 shows the clip full screen, the ball held, nothing of the game's over it).
