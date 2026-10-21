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

Round 2, the same evening: "Take a pass through our previously written modes and upgrade them to be multi-stage like
what we did here and add new clips and make the mode more intricate and interesting. Make sure that you run the modes
in emulation and there is no overlapping text anywhere from existing modes. Also make sure that new intricate
lighting. And Shaker effects are put in for each of them. Especially want the angry Godzilla multi-ball to be more
like gappa angry from Elvira House of horrors where you get different types of multi-ball modes with different clips
and music depending on how many balls you lock." Then: "we need to make the second or third time of activating a mode
more difficult for each of these. For example hitting the major Target three times for the first activation but an
additional six for the next activation." And: "make sure for the pro game we have alternate rules where needed (since
it has a slightly different layout and fewer mechs). Also, make superx2 start condition 60 spins instead of 30".

## Round 2: every older mode upgraded

The eleven rebuilt C examples are no longer straight rebuilds: each is three or four stages deep in the new modes'
way (a POT paid into by each stage, CASH OUT at the right scoop, a quarter back on failing, harder each start), with
new clips, calls and a music bed of its own cut from the films, its own light shows for every moment and the shaker
on every hit, sized by weight. What each one is now is under "Each mode now" below, generated from the examples
themselves; what each one still lacks from its C is under "what it lost".

- **Each start costs more** (`pack.need(base, counter)`: the base times the starts so far plus one). David's example
  is MINILLA: 3 Godzilla target hits the first time, 6 the second, 9 the third. KING CAESAR 25 / 50 / 75 prayer,
  KUMONGA 40 / 80 / 120 spins, KAMACURAS 50 / 100 / 150 spins, KING GHIDORAH 3 / 6 / 9 powerline hits, OXYGEN
  DESTROYER 25 / 50 / 75 spins, MASER BARRAGE 3 / 6 / 9 Maser hits, FINAL WARS 1 / 2 / 3 rounds of the pack,
  ANGUIRUS 3 / 6 / 9 shield hits, MELTDOWN 10 / 20 / 30 captive ball hits, GODZILLA ANGRY's locks, SPACEGODZILLA 1 / 2
  / 3 powerline hits a lock, KIRYU 60 / 120 / 180 spins, BIOLLANTE 6 / 12 / 18 ramps, DESTOROYAH 30 / 60 / 90 spins.
  The stages get harder too (shorter windows, faster movers, quicker regrowth).
- **SUPER X2 starts at 60 spins**: his SUPER X2 is the KIRYU example re-worded, so KIRYU itself starts at 60.
- **GODZILLA ANGRY is Gappa Angry** (Elvira's House of Horrors): the locks pick the multiball - RODAN'S NEST (one
  lock, 2 balls), MECHAGODZILLA (3), GARUDA (4), FIRE RODAN (5), SUPER MECHAGODZILLA (five locks or BABY found, 6) -
  each with its own clip, call, music bed, jackpot shots, light shows and shakes, its multiplier starting higher the
  deeper you went (x1 to x5).
- **The Pro gets its own rules where it differs.** Every example now names what a Godzilla Pro 1.16 does instead
  (`title_alt`): a stand-in shot for one the Pro has not (the centre shield is the Maser target for ANGUIRUS and
  SPACEGODZILLA, the Godzilla target for BIOLLANTE's middle vine, the Mecha lane for DESTOROYAH's close ring; Premium's
  Shield ramp spinner is the Pro's Right spinner), its own game light shows where the Pro lacks one, and what a Pro
  cannot do left out (the shield platform, the building, a hold, an insert). New mode ▸ Blocks offers an example on a
  Pro only when that adapted program checks clean; each one's desk scenarios also play on the adapted program
  (DESK_PRO), and each ran on the emulator as a Pro 1.16.
- **Music beds** (any blocks mode, any title): besides its music a mode may carry up to 6 further beds (Music bed… in
  the editor, the "Play the music" block switches to one). Each rides the mode's own music carrier, swapped in by
  name; past Godzilla Premium/LE's 12 bed sounds the swap carries it.

## On the glass: nothing over anything

Every mode ran on the emulator (Premium/LE and Pro) with its own clips; every glass shot was looked at. What was found
and fixed for every mode (the runtime, the kit or the generator, not one mode):

- **Every word fits.** `make_examples.py` measures each HUD string in the game's own font off the card
  (`hud_fit.py`): the award and its line 950 px, the title 1150, the line 1250, the counters 230 / 420 / 260. An
  example that does not fit does not build.
- **An award** says its words big and its number small under them ("BARRAGE" over "1  -  MULTIPLIER UP"): the
  number and the words together were too wide.
- **A note** (a mode not running: "3 MORE FOR MINILLA") is lettered in the title and line places above the score
  panel, not the award line in the middle, where the game's live screen has its own RAID / BRIDGE / POWER words.
- **A note waits out the game's own screens.** A mode not running had no watch on the game's displays, so
  "ANGUIRUS IS READY" lettered over the Pro's "MASER CANNON CHARGING" (run agm_pro_r3): `pm_display_covered` now
  looks with no mode running, and a note waiting keeps its time.
- **The TOTAL after an ending clip.** A full-screen clip in When the mode ends covered the TOTAL's 3 s: the TOTAL is
  held 7 s more then (the clip starts half a second in and runs up to 6 s). A clip behind the HUD there played in the
  loop the end takes away (run meltdown_r4): it plays full screen.
- **The mode's loop behind its TOTAL and its notes.** With no mode running the glass is the game's live city map, and
  its labels (RAID / SHOOT RAMPS TO LIGHT BATTLE, BRIDGE, TANKS, POWER) sat under the TOTAL's number and title (run
  meltdown_r4, md_16_end) and under a note's line (bedfix_pro_r1, bf_ready_c). The runtime now keeps a mode's loop
  behind an ending it holds (`pm_end_holding`) and takes it away with the hold; a note shows over the mode's own loop,
  as the game's own feedback screens (MASER CANNON CHARGING) letter their two lines over a clip of theirs.
- **Beds on the Pro.** A mode's bed is swapped onto its own music carrier (it took the first free one: FINAL WARS's
  rode OXYGEN DESTROYER's music).
- The game's own screens (BATTLE IS LIT, its shot awards) cover ours for their moment, as the game's always have.
  Built without its films a mode has no clip of its own to loop, and the game's live city map shows behind its HUD,
  its map labels under our words; with its clips (any build from the films, David's project) the loop covers it.

## What there is now

- **Blocks examples.** New mode ▸ Blocks lists whole modes made of blocks for the card's title, in two lists: the new
  ones, and the SDK's C examples rebuilt in blocks. Picking one adds it with its own clips, sounds and music cut from
  the person's own films, exactly as the C examples are (the same recipes and cutter); without the films it is added
  with the game's own callouts in their place. Only the examples that build on the card are offered: Godzilla
  Premium/LE 1.16 and Pro 1.16 get all 15 (each on a Pro with its Pro rules); Pro 1.15, an older build with no switch
  shots, shakes or game light shows, none (round 1 offered it GODZILLA ANGRY, which now needs the Mecha lane's switch
  shot and the shaker).
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
25 lights the Mecha lane (50 the second time, 75 the third). AWAKENING: the Pop bumper, Right ramp and Mecha lane each crack the shrine.
REFLECT: Mechagodzilla's beam moves across the Left ramp, Big loop, Right ramp and Building (faster each time he
wakes); its shot absorbs it (up to 3 charges), the Mecha lane fires them back, 5M a charge, three times. TAG TEAM: the
Godzilla target opens 6 s for a King Caesar shot: 8M, 16M, 24M. THE FINAL BLOW: three Building hits take
Mechagodzilla's head off.

**KUMONGA** (Son of Godzilla, 1967). 40 Shield ramp spins light the Big loop (80, then 120). THE WEB: the shield
platform turns toward the player; both shields, the centre powerline and both ramps are webbed (purple chase); each
torn pays more than the last, and she webs one again every 10 s (7, 5 the more she has been fought). STRANDS: every
spin of every spinner cuts one, 60 (+20). THE STING: a hurry-up at the Big loop from 20M down to 5M. FIRE: the Building
(Godzilla's ray) then the Right ramp (Minilla's) within 8 s, three times: KUMONGA BURNS.

**MINILLA** (Son of Godzilla, 1967; All Monsters Attack, 1969). Dad's call: 3 Godzilla target hits (6, then 9) light the top
of the Mecha lane. SMOKE RINGS: four cyan shots, each ring twice the last. TAIL STOMP: the Godzilla target stomps his
tail, then a 12 s hurry-up at the Building, his first ray (or it sputters). GABARA: the bully moves between the ramps
and the Big loop every 5 s, 5 hits (+1), and gets one back if left alone 15 s. FATHER AND SON: a two-ball multiball, DAD
jackpots (Godzilla target, Building) and SON jackpots (Mecha exit top, Right ramp); a DAD then a SON is a HUG; back to
one ball, the pot and 20M a hug.

**KAMACURAS, reworked** (it was DESTOROYAH re-worded in the Heisei project: 30 Top spinner spins, +10, starting at once).
- *Requires more to start:* 50 Top spinner spins (100, then 150) light the RIGHT SCOOP, its own corner, and the scoop
  starts it.
- *Its shots are more obvious:* each mantis's shot CHASES in its ring's colour (far green, near yellow, close red,
  faster the closer), the HUD's line names where it is ("MANTIS AT THE LEFT RAMP"), and each one swoops in with its own
  clip (a mantis landing), screech and a ripple light show.
- The rules otherwise are DESTOROYAH's (Lyman's Horde): two at a time, 1x/2x/4x the closer the kill, waves of 3, 4, 5
  kills each paying its kills again, three strikes on Godzilla and the swarm wins, the biggest mantis at the Building
  for 25 s and a super worth every kill.
- Its film picks: the earlier recipe kept where right, its boss/won/lost clips that showed Kumonga replaced with
  Kamacuras (Final Wars' pylon death, the last mantis rearing), and the new swoop and lit cues.

## Each mode's own sound (David: "unique soundtracks and sound effects for the modes too")

Every mode has a music bed and calls of its own, none shared with another mode of the pack (checked across all 15
recipes): KING CAESAR the 1974 film's main title (Masaru Sato), KAMACURAS Son of Godzilla's main title march, KUMONGA
Destroy All Monsters' main title march (Akira Ifukube), MINILLA Son of Godzilla's snowy father-and-son ending theme;
each with 7 or 8 calls cut from its own scenes (King Caesar's cry, the beam reflected, Kumonga's whirr and web hiss,
Minilla's chirps and smoke-ring puffs, the mantis screeches). The rebuilt C modes keep their C recipes' own. On the
rig each mode played its own bed (KING CAESAR sound id 105, KUMONGA 576: run a3).

## David's own project in blocks

`C:\Users\david\OneDrive\Desktop\heisei modes\proj blocks (PAD-658)` (written by `C:\tmp\PAD-658\deliver.py`; his
`proj` is untouched): his ten re-themed C modes as their blocks rebuilds with his words (JET JAGUAR, KING KONG, SHIN
GODZILLA, EBIRAH, SUPER X2, ZILLA, MELTDOWN's NUCLEAR GODZILLA, GODZILLA ANGRY's Godzilla chase) and the clips and
calls his project already cut; his KAMACURAS (DESTOROYAH re-worded) replaced by the reworked KAMACURAS; KING CAESAR,
KUMONGA and MINILLA added with their clips cut from his films; jjhj and his form modes copied as they are. Every mode
checks clean against Godzilla Premium/LE 1.16 with its folder. Point Write's assets at it to build it.

Round 2 wrote it again with the upgraded modes (round 1's copy is kept in `C:\tmp\PAD-658\delivered_round1`; it was
never edited). Each re-themed mode's new stages are in his words (`C:\tmp\PAD-658\heisei\<slug>_words.json`: EBIRAH's
THE BOULDER, SUPER X2's stages, GODZILLA ANGRY's five kinds as GPN CHASE, FULL METAL, AIR STRIKE, ATOMIC RAY and
MILLENNIUM, and so on), and its new clips, calls and beds are cut from his theme's own films where the scouts found
them (`<slug>_recipe_extra.json`: JET JAGUAR from Godzilla vs. Megalon, KING KONG from King Kong vs. Godzilla, EBIRAH
from Ebirah, NUCLEAR GODZILLA from The Return of Godzilla, GODZILLA ANGRY's from Godzilla 2000), else from the
example's. Every string of his words is measured against the glass too.

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

All eleven of the SDK's C examples are rebuilt (same slugs, so a project holds one or the other) and, in round 2,
taken deeper (above); each keeps its C's rules as its first stage, with its C's display priority, isolation from the
game's modes, clips/sounds/music cues and colours. What is lost is in each example's `lost` list (the JSON beside it),
written per mode and kept true for the round-2 versions; the kinds that recur:

- **No random numbers in blocks.** Where the C picked a shot at random (DESTOROYAH's aggregates, KING GHIDORAH's moving
  head, MELTDOWN's heart, GODZILLA ANGRY's Baby, FINAL WARS' Monster X) the blocks take them in turn.
- **No 250 ms debounce** (the kit's): a target that bounces counts each time.
- **Fixed words.** Numbers come after the words in a line ("SPINS TO KIRYU 29"), counters show bare numbers (no "%",
  no "X2"), gauges are one colour.
- **The TOTAL is the runtime's** (3 s, 10 s after a full-screen ending clip, the ending title and a line of fixed
  words) where the C wrote its own for 10 s with numbers in it.
- **A badge counts only the mode's clock**, not a timer of its own (KIRYU's overheat, DESTOROYAH's perfect form).
- **Every switch** is not a shot: GODZILLA ANGRY's RAGE meter and BIOLLANTE's sap count the shots the port names, so
  their counts were scaled down.
- **The kit's ledger** (which of the pack you played and won) is shared variables in blocks: the blocks FINAL WARS
  reads the blocks pack's, not the C modes'.
- **The Pro's own rules** stand in for a shot the Pro has not (above) rather than the C's runtime checks of what the
  machine has.


### Each mode now

**KING CAESAR** (`king_caesar`, Premium/LE and Pro 1.16): New (PAD-658). The prayer at his pop bumper wakes him at the
Mecha lane; four stages, each with its own shots (crack the shrine, absorb and reflect the beam, tag team with
Godzilla, the final blow); cash the pot out at the right scoop after any stage. Godzilla vs. Mechagodzilla (1974).

**KUMONGA** (`kumonga`, Premium/LE and Pro 1.16): New (PAD-658). Spin the Shield ramp spinner to wake her at the Big
loop; four stages (tear the web on the shield platform while she webs it again, cut the strands on every spinner, the
sting hurry-up, burn her with Godzilla and Minilla); cash the pot out at the right scoop. Son of Godzilla (1967).

**MINILLA** (`minilla`, Premium/LE and Pro 1.16): New (PAD-658). Dad's call (the Godzilla target) wakes him at the top
of the Mecha lane; four stages (smoke rings, the tail stomp and his first ray, beating the bully Gabara, a
father-and-son two-ball multiball); cash the pot out at the right scoop. Son of Godzilla (1967) and All Monsters
Attack (1969).

**KAMACURAS** (`kamacuras`, from destoroyah.c, Premium/LE and Pro 1.16): Reworked (PAD-658): DESTOROYAH's waves as
Kamacuras, now harder to start (50 Top spinner spins, then its own right scoop) and with its mantis shots far more
obvious (chasing in the ring's colour, the HUD naming each one, a swoop clip and light show as each lands). Son of
Godzilla (1967) and Godzilla: Final Wars (2004).

**KING GHIDORAH** (`ghidorah_heads`, from ghidorah_heads.c, Premium/LE and Pro 1.16): The C example KING GHIDORAH
rebuilt in blocks, three stages deep. Powerline hits in one ball start it (each powerline once, twice the second time,
three times the third). THE HEADS is the C's battle: only the lit head (two shots each) takes damage, it turns, a
wounded head grows back, each sever pays into the pot; THE WINGS: hit the Big loop and the Mecha lane in turn to
ground him; THE FINAL BLOW: the Maser's super jackpot and the pot twice over. Cash the pot at the right scoop once the
heads are off; failing pays a quarter.

**OXYGEN DESTROYER** (`oxygen_destroyer`, from oxygen_destroyer.c, Premium/LE and Pro 1.16): The C example OXYGEN
DESTROYER rebuilt in blocks and taken deeper (PAD-658): 25 Left spinner spins start it (50 the second time, 75 the
third). Four stages: the C's hurry-up (20,000,000 draining over 25 s, the Left ramp collects it into the pot, the
Godzilla target holds it off), the dive (hit the moving sonar ping 3 times), the descent (spin the Left spinner 20
times to lower the device), and Serizawa's choice (the Right ramp in 15 s: the pot twice over and 25M). Cash the pot
out at the right scoop after any stage; the clock or a drain pays a quarter of it.

**MASER BARRAGE** (`maser_barrage`, from maser_barrage.c, Premium/LE and Pro 1.16): The C example MASER BARRAGE
rebuilt in blocks, three stages deep: the Maser target 3 times in a ball starts it (6 the second time, 9 the third).
OPEN FIRE is the C's chain (Left ramp, Right ramp, Building, each within the window; a barrage pays 5M x the
multiplier into the pot, up to x5); CROSSFIRE puts the three powerline tanks in line and fires the Maser target (10M
x); GODZILLA IN THE SIGHTS aims at the Big loop and fires at the Godzilla target, three direct hits for the pot twice
over. Cash the pot at the right scoop after any stage; failing pays a quarter.

**FINAL WARS** (`final_wars`, from final_wars.c, Premium/LE and Pro 1.16): The C example FINAL WARS rebuilt in blocks
and taken deeper (PAD-658): a round of KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE played (or two of them won)
lights it at the Building the first time, two rounds the second, three the third. Four timed phases: save the cities,
hit the moving Monster X, break Keizer Ghidorah's three beams before Godzilla's power drains (the Mecha lane recharges
it), and GODZILLA RISES, a 2-ball multiball with jackpots and the Building super jackpot. A quick phase carries the
multiplier up (to x4); shields add time.

**ANGUIRUS** (`anguirus_assist`, from anguirus_assist.c, Premium/LE and Pro 1.16): The C example ANGUIRUS rebuilt in
blocks and taken deeper: shield hits call him (3, then 6, then 9) and he joins the game's own battle; four stages
(charge the spikes at the shields, three rolling attacks at the Big loop, three bites at the chasing ramp, the allies'
hurry-up at the Building); cash the pot out at the right scoop after any stage. Destroy All Monsters (1968) and Final
Wars (2004).

**MELTDOWN** (`meltdown`, from meltdown.c, Premium/LE and Pro 1.16): The C example MELTDOWN rebuilt in blocks and
taken deeper: captive ball hits (10, then 20, then 30) light a 3-ball multiball where the core heats by itself and
with every jackpot (x1 to x5) and the shields cool it; three stages with their own jackpot shots and music (BURNING
GODZILLA's four red shots and the moving heart, DESTOROYAH's spiral ray at the lit ramp, JUNIOR at the Big loop and
the Mecha lane), each meltdown's super at the Building worth the jackpots paid x2, x3, x4 and taking it a stage
further.

**GODZILLA ANGRY** (`godzilla_angry`, from godzilla_angry.c, Premium/LE and Pro 1.16): The C example GODZILLA ANGRY
rebuilt in blocks and made Elvira's Gappa Angry: 150 named shots fill the RAGE meter (300 the second time, 450 the
third) and light the Building; a chase through five places, each with its red shots and a lock, to BABY at the
Building; how many balls are locked picks the multiball: RODAN'S NEST (2 balls), MECHAGODZILLA (3), GARUDA (4), FIRE
RODAN (5) or SUPER MECHAGODZILLA (6, after BABY FOUND's super jackpot), each with its own clips, music, jackpot shots,
multiplier, light shows and shakes.

**KIRYU** (`kiryu`, from kiryu.c, Premium/LE and Pro 1.16): The C example KIRYU rebuilt in blocks and taken deeper
(PAD-658): 60 spins of the Mechagodzilla spinner start it (120 the second time, 180 the third); stage 1 charges the
Absolute Zero and fires it at the captive ball, x1 to x4 as the reactor overheats, the multiplier carried up; stage 2
fires the arsenal (masers, missiles, the wrist blade); stage 3 grabs Godzilla at the Mecha lane, carries him out to
sea at the Big loop and fires point blank. The pot cashes out at the right scoop after stage 1 or 2. On a Pro the
spinner is the Right spinner.

**SPACEGODZILLA** (`spacegodzilla`, from spacegodzilla.c, Premium/LE and Pro 1.16): The C example SPACEGODZILLA
rebuilt in blocks and taken deeper (PAD-658): powerline hits light the locks (one a lock the first time, two the
second, three the third), three crystals planted at the Big loop start a 3-ball multiball in three stages: CRYSTAL
TOWERS (the ramps and the Building, a super at the Big loop), M.O.G.U.E.R.A. (the shoulder crystals at the shields,
every hit a spiral grenade raising the jackpots, the super twice its sum at the Godzilla target) and SPACE BEAST (his
own music, the powerlines cut, FUKUOKA TOWER at the Building: three times the sum and every super before). Each super
adds a ball. On a Pro the Maser target is the centre shoulder crystal.

**BIOLLANTE** (`biollante`, from biollante.c, Premium/LE and Pro 1.16): The C example BIOLLANTE rebuilt in blocks and
taken deeper (PAD-658): six ramps start her (12 the second time, 18 the third) and every shot feeds the SAP JACKPOT.
Four stages: THE ROSE (cut the Shield and Powerline vine banks to collect the sap x1, x2 into the pot), ROSE ABLAZE
(burn the lit petal as Godzilla's ray moves across the ramps and the Big loop), REGROWTH (cut all six vines while she
grows them back), then her BEAST form: 20 s to land the final blow at the Building, the pot twice over. Cash the pot
out at the right scoop after any stage; the clock or a drain pays a quarter.

**DESTOROYAH** (`destoroyah`, from destoroyah.c, Premium/LE and Pro 1.16): The C example DESTOROYAH rebuilt in blocks
and taken deeper (PAD-658): 30 Top spinner spins start it (60 the second time, 90 the third). Three stages: THE SWARM
(three waves of aggregates advance from the Powerlines to the ramps and loop to the close targets, a kill paying more
the closer it is, each cleared wave into the pot), his FLYING FORM (four hits where he flies over the ramps and the
Big loop in 30 s), then his PERFECT FORM (three Building hits in 25 s, the super jackpot every kill and the pot twice
over). Cash the pot out at the right scoop once the swarm is beaten.

### Each mode, what it lost (its example's `lost` list)

**KING GHIDORAH** (`ghidorah_heads`, Premium/LE and Pro 1.16):
- The heads' shots have no 250 ms debounce: a ball rattling on a target is several hits (the C counted one hit a
  quarter second per shot).
- A start from the tab's Start mode now counts as the ball's and the game's start too (the C counted only the three
  powerlines).
- When a run will not count (it already ran this ball) the powerlines say nothing; the C logged why once. The C ran at
  most twice a game; the blocks any number of times, each start costing more.
- The HUD shows a severed head's health as 0, where the C showed X; in the final blow the counters are the POT, the
  SUPER JACKPOT and the STAGE, where the C hid all but the super jackpot; and the gauge counts the stages, where the
  C's counted the severed heads.
- Awards say their numbers under the words: LEFT HEAD over 5,000,000  -  SEVERED  +10 SECONDS, where the C said LEFT
  HEAD SEVERED over 5,000,000   +10 SECONDS; a head growing back says LEFT HEAD over GROWS BACK, where the C said LEFT
  HEAD REGROWS. A glancing blow says HIT THE LIT HEAD, where the C named it.
- The ending title (GHIDORAH DEFEATED, GHIDORAH FLEES or GHIDORAH ESCAPES) and its total stay up 3 s, the runtime's:
  the C kept them 10 s, with KING GHIDORAH TOTAL under the total.
- The lit head moves on its own timer, and moves a tick after a sever (the C moved it in the same tick); its inserts
  change a tick after a hit too.
- The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).
- Godzilla Premium/LE and Pro 1.16 only (a Pro 1.15 has no switch shots): the C also ran on a Pro 1.15. It played the
  game's Strobe burst at the start and Colour fade at the end, with its own shows where the game had none; the blocks
  run its own shows (Ghidorah start, Ghidorah won, Ghidorah lost and six more) on every title instead.
- The blocks pack keeps its own FINAL WARS ledger in shared variables ('ghidorah played', 'ghidorah won'), which the
  blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read the C's
  ledger.

**OXYGEN DESTROYER** (`oxygen_destroyer`, Premium/LE and Pro 1.16):
- The value falls on a timer the blocks keep in milliseconds, but the clock the HUD badge shows is whole seconds: a
  hold-off puts the clock to the next whole second above the value's time (the C counted both from one drain, and a
  stalled frame drained at most 100 ms).
- The Godzilla target has no 250 ms debounce: a ball rattling on the captive ball can use up two hold-offs (the C
  counted one hit a quarter second); a spinner's spins count each one, as the C's did.
- The Left ramp blinks faster as the mode's clock runs down (the blocks' Hurry pattern) and changes colour once a
  second; the C's blink followed the value itself, every tick, with a flicker in the last 3 s.
- No random numbers in blocks: the sonar ping moves in turn (Powerline left, center, right, the Big loop).
- The middle counter is the HURRY-UP, then the POT; the C showed a COLLECTED counter beside the super jackpot. Its
  gauge is one blue, where the C's ten segments went from deep to pale blue, and a note says SPINS TO GO with the
  number under it where the C said 24 SPINS TO GO.
- The ending title (GODZILLA IS GONE, THE DIVERS SURFACE, GODZILLA ESCAPES or THE OXYGEN IS GONE) and its total stay
  up 3 s, the runtime's: the C kept them 10 s, with OXYGEN DESTROYER TOTAL under the total.
- The cooldown is 15 s on a timer that a new ball clears (the C kept each player's own across balls), and a start from
  the tab's Start mode now counts toward the 3 a game.
- The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).
- It plays its own light shows (Oxygen start, Oxygen won, Oxygen lost: the C's fallback shows) on every title, where
  the C played the game's Playfield wave and Blue fade when the game had them.
- The blocks pack keeps its own FINAL WARS ledger in shared variables ('oxygen played', 'oxygen won'), which the
  blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read the C's
  ledger.

**MASER BARRAGE** (`maser_barrage`, Premium/LE and Pro 1.16):
- The start counts every Maser target hit this ball, with no 250 ms debounce, and the chain's shots have none either:
  a ball rattling in the Left ramp's entrance can count twice (the C counted one a quarter second).
- The next shot's blink quickens once a second as its window closes (the C every tick), and the HUD shows the
  multiplier as 2 where the C showed X2, and the window as 0 with NO CLOCK YET where it showed -.
- Awards say their numbers under the words: LEFT RAMP X over 2  -  NOW THE RIGHT RAMP, where the C said LEFT RAMP X2
  over 2,000,000.
- The ending's line under the title puts the count last (BEST X3  -  BARRAGES 2) where the C said 2 BARRAGES  -  BEST
  X3, and says BARRAGES for one too; it counts every jackpot of the three stages.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- The counters are MULTIPLIER, POT, WINDOW; the C drew MULTIPLIER, WINDOW, BARRAGES (a barrage now pays into the pot,
  where the C scored it at once).
- The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).
- Godzilla Premium/LE and Pro 1.16 only (a Pro 1.15 has no switch shots): the C also ran on a Pro 1.15. It played the
  game's Insert chase at the start and Colour fade at the end, with its own shows where the game had none; the blocks
  run its own shows (Maser start, Maser won, Maser lost and seven more) on every title instead.
- The blocks pack keeps its own FINAL WARS ledger in shared variables ('maser played', 'maser won'), which the blocks
  FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not read the C's ledger.

**FINAL WARS** (`final_wars`, Premium/LE and Pro 1.16):
- No randomness in blocks: Monster X moves to the next target in turn (Powerline left, center, right, the Godzilla
  target, round again) every 3 s and when hit, where the C picked another target at random.
- The ledger is six shared variables (ghidorah / oxygen / maser played and won) the blocks KING GHIDORAH, OXYGEN
  DESTROYER and MASER BARRAGE set; the C modes' own ledger (kit_ledger) is a different store, so the C versions of
  those modes do not light this blocks version, nor the other way round.
- A round counts on the next shot after it is played (blocks only look while a shot is made), where the C looked twice
  a second; and the FINAL WARS IS LIT note shows then, not 7 s after the other mode's total.
- The lit Building pulses as any lit mode does (the runtime's light), where the C pulsed it only while none of our
  modes ran and not between balls.
- The ending title (GODZILLA WINS or THE XILIENS WIN) and its total stay up 3 s, the runtime's: the C kept them 10 s,
  with FINAL WARS TOTAL under the total.
- It plays its own light shows at every moment, where the C played the game's Strobe storm and Red and blue fade (its
  own shows only on a game without them).
- Godzilla Pro 1.16 has two shields (no centre one, no platform to turn): its left and right add the time, where the C
  simply had one shield fewer there.

**ANGUIRUS** (`anguirus_assist`, Premium/LE and Pro 1.16):
- He joins on the first shot after one of the game's own modes begins (blocks only look at a shot), where the C looked
  twice a second; and blocks cannot tell a battle from the game's other modes: he joins any of its modes while one
  ball is in play (its multiballs are left out), where the C joined only kaiju battles.
- He leaves within a second of the game's mode ending (an Every second check) and his award shows at once; the C
  waited for the battle's own total screen first, then kept his 4 s in view.
- Ended while the battle still runs (a stop, another of our modes), his total shows under the runtime's ANGUIRUS
  TOTAL: the C put ANGUIRUS RETREATS under it. His HUD's title and line are the battle's while it runs, so the stage
  is said by his awards, not by a line or a counter.
- His screen is not shared in moments: with the HUD on he holds display priority 180 the whole time he runs, where the
  C held it only for each moment (entrance, a spike, the roll, a rolling attack) and gave the battle its own displays
  between them.
- His entrance (clip, music, words) comes a fixed 2 s after he joins; the C waited until the battle's start screen had
  gone (up to 12 s). His music starts as he joins, not with the entrance.
- The SPIKES gauge keeps its label: the C relabelled it ROLLING! while he rolls; from THE BITE on it stays full.
- The Big loop's chase turns to a fast blink in the window's last 2 s (looked at once a second), where the C stepped
  its blink every tick.
- On Godzilla Pro 1.16 the Maser target stands in for the center shield (a third spike to charge): the C charged with
  two spikes on the Pro's two shields.
- The C's total gave way at once when another of our modes asked to start; the blocks' runtime TOTAL runs its 3 s.

**MELTDOWN** (`meltdown`, Premium/LE and Pro 1.16):
- No randomness in blocks: the HEART starts at the Left ramp and moves in turn (Left ramp, Right ramp, Building, Big
  loop) every 8 s and when hit, where the C picked another shot at random.
- The core is looked at once a second (an Every second script), so it rises a whole 1% or 2% each second and the
  MELTDOWN blink quickens on the second, where the C stepped them every tick.
- No timer badge: the MELTDOWN window is a timer the line counts (SUPER JACKPOT AT THE BUILDING: 17), where the C
  counted it on the MELTDOWN badge (a blocks badge counts only the mode's own clock, and this mode has none).
- The HUD shows the core as a number (25), not 25%; the third counter has no SUPER value under it; the CORE gauge is
  one colour (the C's ran yellow to white-hot); the lines lost their double spaces to fit the 40 letters a blocks HUD
  line holds.
- The ending's line under MELTDOWN TOTAL puts the jackpots last (1 MELTDOWN SURVIVED  -  JACKPOTS 6) where the C said
  6 JACKPOTS  -  1 MELTDOWN SURVIVED, says JACKPOTS for one too, and past 3 meltdowns says only the jackpots.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- The ready light is the runtime's lit mode (held ball after ball), where the C pulsed MAGNA GRAB only while nothing
  else owned the playfield.
- One ball left is checked once a second after 18 s (two looks in a row), the C's 2 s after the 15 s ball save and 3 s
  grace; and the C noted whether a second ball was ever served.
- On Godzilla Pro 1.16 the two shields (left, right) cool the core and stay where they are (the Pro's do not turn);
  the C on a Pro cooled with the same two.

**GODZILLA ANGRY** (`godzilla_angry`, Premium/LE and Pro 1.16):
- The RAGE meter counts only the shots this program names (the ramps, Big loop, Building, center powerline, captive
  ball, Maser and Mecha lane): the blocks never see a switch's own hit, where the C counts every playfield switch. So
  the meter is a fifth as long (stretches of 20, 25, 30, 35, 40 hits the first time, twice that the second, where the
  C has 100 to 200 and 25 more), and the SUPER JACKPOT grows 10,000 a named shot rather than a switch.
- No points while the mode is not running: the C pays 1,000,000 (+500,000 a stretch) at each RAGE stretch's end; the
  blocks' Score only scores while the mode runs, so a stretch is a note, a roar and a light show only.
- The RAGE meter is not on the glass: the C draws it as a bar with GODZILLA RAGE and its percent at the top right all
  game; a blocks HUD shows only while the mode runs, so the meter is the notes alone (every quarter of a stretch, and
  RAGE n PERCENT at its end).
- No ball save: the C gives a 5 s ball save at the start and keeps one running from the first lock, so a drain with
  locks sends the locked balls straight into the multiball. In blocks a drain ends the chase; the place, its locks,
  the jackpot and the super wait for the next start at the Building (as the C does for a drain with no lock).
- No randomness: each multiball's JACKPOT starts on its kind's first shot, moves on to the next of its four as its
  clock runs out and back one when it is hit, where the C's BABY jumped to another of four shots at random.
- The multiballs are this blocks version's own (Gappa Angry's kinds, PAD-658 round 2): the C has ONE ANGRY MULTIBALL
  of the locks + 1 balls, BABY on the ramps, Building and Big loop, x1 to x6.
- A blocks mode holds 12 clips: each kind has its own start clip, and RODAN'S NEST, GARUDA and FIRE RODAN replay it
  behind the HUD at their jackpots (MECHAGODZILLA has the ray-at-Mechagodzilla clip, the 6-ball the red spiral ray);
  the four smaller kinds share the lost clip at their end (the 6-ball after BABY FOUND has won).
- The ending's line says JACKPOTS and the count (the C said 2 BABY JACKPOTS  -  5 LOCKS); after the chase it says
  LOCKS KEPT FOR THE TRAIL and the count (the C named the place the trail waits at).
- The ending's TOTAL is the runtime's (up 3 s, or until 9 s after the end behind a full-screen ending clip): the C
  kept it 10 s.
- The instruction line counts the place's red shots still to make ("SHOOT THE RED SHOTS: TO GO 3", the place under the
  LOCKS counter) where the C names them while they fit ("OSAKA: BIG LOOP, BUILDING"); a start on the trail says THE
  TRAIL AGAIN with its locks, not the place's name.
- The badge counts the place's clock in the chase and the JACKPOT's next move in the multiball, where the C hides it
  in the multiball; a place's clock with locks turns into the multiball with a second left, not at 0.
- One display priority, 180, throughout: the C takes 190 (a wizard's) for the multiball.
- Its own light shows replace the game's Insert chase and Ember fade that the C played on a Premium/LE (and its own on
  a Pro), so every title sees the same shows.
- Not on Godzilla Pro 1.15 (the C ran there): that older build names no switch shots (the Mecha lane, a jackpot shot
  of four of the five multiballs) and has no shaker steps.
- No tilt rule of its own: the C stops the meter after a tilt until the next ball; here the tilted ball's shots still
  count.
- Another mode of ours ending on the Building does not keep it from starting this one on that same shot (the C waits
  300 ms after another of ours ends).
- A start on the trail after a drain costs no meter (the Building stays lit until the multiball is played), as in the
  C; only the meter itself grows each time it is spent.

**KIRYU** (`kiryu`, Premium/LE and Pro 1.16):
- The badge always counts the stage's clock: while the reactor overheats the C counted the overheat's 12 s there
  instead. The overheat's seconds now ride on the line (OVERHEATING! FIRE NOW 9).
- The counters show bare numbers: CHARGE 109 where the C showed 109%, MULTIPLIER 2 where it showed X2.
- The gauge stays one ice blue labelled CHARGE: the C shaded its ten pips from blue to white and relabelled it
  OVERHEAT while overheating and FIRED after the shot.
- The spin count note reads SPINS TO KIRYU with the number under it, every 10 spins, where the C said 29 SPINS TO
  KIRYU at every spin.
- When the clock runs out at 100% or more in stage 1 Kiryu still fires on its own (x1, 10M), but at the end itself:
  the C played the shot's 4-second moment before KIRYU WINS. The C's quarter of the mode's points on top of the shot
  is now the pot (10M times the multiplier) cashed or carried on.
- The ending (its title, its line and the total) stays up 3 s, the runtime's: the C kept it 10 s.
- No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks count every
  report.
- A hit no longer answers by itself: the C flashed every charging shot's inserts white and played the game's climbing
  orchestra hit (PAD-415).
- Its ending call plays after a drain or one of the game's own modes ends it too (the C kept quiet then).
- Its own start and end light shows the C kept for a game without the game's Strobe burst and Blue fade are the mode's
  own shows here, played beside the game's.

**SPACEGODZILLA** (`spacegodzilla`, Premium/LE and Pro 1.16):
- No points while the mode is not running: the C pays 250,000 a crystal times its number (250,000, 500,000, 750,000)
  as it is planted; the blocks' Score only scores while the mode runs.
- A lit lock does not blink the Big loop purple: the blocks light inserts only while the mode runs, and a mode lit at
  a shot starts on it, so only the full set (three crystals, waiting for the game's mode to end) chases there; the
  notes say LOCK IS LIT and SHOOT THE BIG LOOP.
- No badge for the super's 20 s window: the badge counts the mode's own clock, and this multiball has none, so the
  window shows as the line (SUPER JACKPOT: THE BIG LOOP) and its shot chasing white, blinking fast in its last 6 s
  (looked at once a second).
- The super's added ball is asked as a multiball of one more ball than are in play (the blocks have no add-a-ball
  block), with its 10 s ball save.
- Another mode of ours running does not stop the powerlines lighting locks or the Big loop planting crystals (the
  blocks cannot tell one of our other modes runs; the C waits for it). A multiball still stops them.
- The ending's line says how it ended (EVERY SUPER AGAIN after the finale, CRYSTAL SHARDS: HALF THE SUM otherwise)
  where the C counted 7 JACKPOTS  -  1 SUPER.
- The ending stays up 3 s, the runtime's: the C kept it 10 s.
- No light show of its own at the start and the end where the game has none (the C falls back on its own when the
  game's Strobe storm or Blue fade will not play): the blocks play the game's (and the mode's own shows beside).
- A tilt or the game moving on ends it as any blocks mode ends (the C also ends at once without its total).
- The C's three multiballs in turn (CRYSTAL TOWERS, M.O.G.U.E.R.A., SPACE BEAST, one per start) are now the three
  stages of every multiball, and the C's first-time rule (one powerline lit every lock) is now one hit a lock.

**BIOLLANTE** (`biollante`, Premium/LE and Pro 1.16):
- Only the port's named shots feed the sap: the C scored every playfield switch (its 0x1 switch dispatch), rollovers
  and other unnamed switches included.
- The counters show bare numbers: SAP 500,000 over X1 AT A BANK, where the C showed the bank count as 2/3 and the
  switch value as 125K.
- No VINES gauge: on the glass its pips sat over the game's own POWER widget at the right edge, so the vines are
  counted on the third counter in the regrowth (the C showed six pips shaded green to rose, BEAST in the beast form).
- The ramp count note reads RAMPS TO BIOLLANTE over 5  -  THE ROSE IS GROWING (the number under the words) where the C
  said 5 RAMPS TO BIOLLANTE.
- The shield vines light at once: the C lit them only once the shield platform had turned to face the player.
- A vine's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C waited 4 s
  from the last one it played.
- No randomness in blocks: Godzilla's ray burns her petals in a fixed order (Left ramp, Big loop, Right ramp) and she
  grows back the first vine cut in a fixed order (the shields left to right, then the powerlines).
- The beast's Building blink quickens against the mode's 40 s clock (slow, then fast in its last 13 s), where the C
  quickened it across the beast's own 20 s.
- The ending (BIOLLANTE IS FREE, BIOLLANTE RETREATS or BIOLLANTE WITHERS, its line and the total) stays up 3 s, the
  runtime's: the C kept it 10 s; its SWITCHES are the named shots made (the C counted every switch).
- No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks count every
  report.
- A hit no longer answers by itself: the C flashed every scoring shot's inserts white and played the game's climbing
  orchestra hit (PAD-415).
- Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does for a drain
  or a tilt).
- On Godzilla Pro the shield bank is the left shield, the Godzilla target and the right shield (the Pro has two fixed
  shields), and the start plays the Pro's Wide yellow and white strobe: the C's bank there was the two shields alone.

**DESTOROYAH** (`destoroyah`, Premium/LE and Pro 1.16):
- No randomness in blocks: each aggregate's next shot is dealt in turn from a counter that runs all game (the far ring
  left, center, right, the near ring and the close ring likewise, skipping the shot the other aggregate stands on),
  where the C picked one at random; the flying form flies over the Left ramp, the Big loop and the Right ramp in that
  order. A player who learns the order can wait for it.
- Aggregates come to the shield targets at once: the C sent none there until the shield platform had turned to face
  the player (or ever, with the shields fixed away).
- The flying and perfect forms' seconds are a counter (SECONDS, TO STOP HIM), not the badge (the blocks' badge counts
  the mode's clock, and this mode has none): the Building's blink still quickens as they run out.
- The counters show bare numbers: STAGE 1 over WAVE 2 OF 3 where the C showed the wave as 2/3 and the kills as 1/4
  (the kills to go are on the line), and no counter says what the wave has paid so far.
- The line puts the kills to go last (WAVE 2: CLOSER PAYS MORE  -  TO GO 3) where the C said WAVE 2: 3 MORE  -  CLOSER
  PAYS MORE.
- No KILLS gauge: on the glass its pips sat over the game's own POWER widget at the right edge (the C showed as many
  pips as the wave needs, shaded yellow to red); the kills to go are on the line.
- A kill's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C waited 4 s
  from the last one it played.
- An aggregate that would advance onto the other's shot takes the next one in turn: the C waited half a second and
  tried again.
- The ending (DESTOROYAH DEFEATED, DESTOROYAH WITHDRAWS or DESTOROYAH WINS, its line and the total) stays up 3 s, the
  runtime's: the C kept it 10 s, with the kills and the wave in its line.
- No debounce: the C counted the same target once in 250 ms; the blocks count every report.
- A hit no longer answers by itself: the C flashed every kill's inserts white and played the game's climbing orchestra
  hit (PAD-415).
- Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does for a drain
  or a tilt).
- On Godzilla Pro the close ring's middle shield is the Mecha lane (the Pro has two fixed shields): the C dealt
  aggregates to the Pro's two shields only.

## What the blocks gained on the way (any title)

- A **HUD counter block can change the counter's label** (the C modes relabel counters by stage).
- **An ending title**: a HUD title or line written in When the mode ends heads the TOTAL in the place of
  "<NAME> TOTAL".
- **The shot a lit mode starts on is that alone** (it was also a shot "while the mode is not running": KING CAESAR's
  starting Mecha lane counted 3 more prayer).
- **A Light block after the mode ended does nothing** (a timer still counting used to hold its insert for good).
- **Five more badge icons** for the blocks HUD: rage, crystal, snowflake, rose, claw (PAD-379's).
- Round 2: **music beds** (Music bed… and the Play the music block, up to 6, each on the mode's own music carrier);
  **an award's number under its words**; **notes in the title and line places**, waiting out the game's own screens,
  over the mode's loop; **the loop behind the TOTAL**; **the TOTAL after an ending clip**; **an ending's clip behind
  the HUD plays full screen** (with a note in the editor); **Pro rules** per example (`title_alt`); and in the
  examples' own tooling, `pack.need` (each start costs more) and the glass-fit check (`hud_fit.py`).

## Proof

- Desk: `tests/test_pad658_blocks_examples.py` (every example is its Python and builds on its card, the rebuilds keep
  their C's cues, the wizard's per-title list, adding with and without films, the ports' switch shots, every example's
  desk scenarios, and the generator's new pieces); the suites the generator touches (test_stern_block_modes,
  test_pad646_light_shows, test_spike2_mode_lamps, test_spike2_intricate_modes, test_pad611_mode_script).
- Emulator (`C:\tmp\PAD-658\rig`: build_set.py builds the Try it set with Write's own code, job658.sh drives it on
  `rigjob.sh` with real switch presses; runs and glass shots in `C:\tmp\PAD-658\runs\<run>`), hidden and muted,
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
