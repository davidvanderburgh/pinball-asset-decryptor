# Five Godzilla modes after Lyman Sheats' rule sets (PAD-379)

David, 2026-10-04: "read through the rules of godzilla (like at tilt forums or other places). also read through the
rules of lyman sheets games (like EHoH, Metallica, etc.). I want to see some new modes in Godzilla that are inspired by
Lyman Sheets games. For example, having a "Gappa Angry" type mode would be amazing in Godzilla with a switch hit counter
on the UI and feedback that it's progressing towards the mode (and not counting swithc hits during multiball) and having
staged locks, etc. Come up with some other inspired modes and put together the code and and assets for me overnight. I'm
looking for sometihng like 5 new modes."

The five are code modes in the example pack (`tools/spike2_emu/modes/sdk/examples/`), written like the six before them
(`intricate_kit.h`, `pad_mode_assets.h`, the HUD at the glass's edges, light shows, own clips, music and calls cut from
the films by `film_recipes.json`), so the Modes tab's Examples offers them and Write carries them. The rules sheets are
in that folder's README.

## What the research found

Tilt Forums closed in 2026; its wiki rulesheets live on at pinballrulesheets.com (the old URLs redirect).

**Godzilla (Stern 2021).** Design Keith Elwin; code Rick Naegele and Keith Elwin (not Lyman Sheats). Rules 1.16:
pinballrulesheets.com/stern/stern-godzilla-rulesheet.html; Stern's LE release notes 0.77 to 1.16
(wp.sternpinball.com/.../godzilla_LE_X.XX-README.txt); the June 2022 rulesheet PDF; Wikizilla; TV Tropes; Pinside.
- Four cities (Tokyo, New York, London, Paris), each with RAID (kaiju battles), POWER (Tesla Strike), BRIDGE (Bridge
  Attack multiball) and TANKS (Tank Attack multiball); Godzilla and Mechagodzilla multiballs; Saucer Attack; wizard modes
  Monster Zero, Terror of Mechagodzilla, Planet X, King of the Monsters, Monster Island Madness.
- It already counts switches here and there: Bridge Attack (50 switch hits, +25 a time, light Attack Bridge), the
  Hedorah Smog Monster Frenzy (a mystery award, +15K a switch), the Ghidorah and Gigan battle (40 switch hits).
- The community's complaints: the same opening every game, only four first-tier battles, almost every mode timed,
  progress hard to read, long animations that break the flow. A Heisei/Millennium reskin (made with this app) wished
  for Biollante, Destoroyah, SpaceGodzilla, Battra, Megaguirus, Orga and Kiryu.
- Toho monsters the game never uses: Biollante, Destoroyah, SpaceGodzilla, Battra, Mecha-King Ghidorah, Baby/Junior,
  Kiryu, Orga, Megaguirus, Baragon, Varan, Manda, Gorosaurus, Kumonga and more. Gappa is Nikkatsu's (1967), not Toho's.

**Lyman F. Sheats Jr.** (died January 2022): Medieval Madness, Attack from Mars, Monster Bash, Revenge from Mars,
Spider-Man, Batman (2008), Iron Man, TRON, AC/DC, Metallica (2013, with Lonnie Ropp and Mike Kyzivat), The Walking Dead
(2014), Batman '66 (2016) and Elvira's House of Horrors (2019, to 1.00). Sources: pinpedia.com/people/148, Wikipedia,
pinballnews.com (2022-01-21), the rulesheets at pinballrulesheets.com (EHoH, Metallica, TWD, Batman '66, Spider-Man),
pinballsupernova's EHoH 0.90 and 1.00 notes, TV Tropes. Not his: Labyrinth and Dune (Eric Priepke), Ghostbusters,
Star Trek, Godzilla.
- **"Gappa Angry!" is EHoH's.** Its Freak Fryer counts every switch hit: levels at 150, 175, 200, 225, 250 (1.0M to
  3.0M; 0.90 cut the step from 50 to 25), a gauge on the playfield and a clip each level. The top level lights the House
  Entrance: a single-ball sequence of lit shots, each stage ending in a lock somewhere else (House, Garage, Crypt, Trunk,
  Garage, Cellar), the Cellar lock a super jackpot and a 6-ball multiball. Shots 500K, +500K a stage, +25K a shot;
  a jackpot built through it; every switch adds to the super. A drain partway gives a smaller multiball of the balls
  locked (Pool Party, Dance Fever, Make-Out Mayhem, Scream Test, Run For Your Life). Only one exclusion is documented:
  1.00 stops the Freak Fryer during They Came From Space, the 6-ball wizard multiball. "Not during multiball" is
  David's rule here, applied to every multiball.
- His signatures: switch-hit counters with a gauge (the Freak Fryer, TWD's Well Walker and Blood Bath, Metallica's FUEL
  and Fade to Black, Spider-Man's Bonesaw); each repeat costs more (Sparky +2, the Garage locks 1 for all / 1 each /
  2 each, Jam 6/8/10); failing still pays (Gappa Angry's smaller multiballs, TWD's ESCAPE); cash out or keep going
  (Metallica's Crank It Up, Batman '66's cash the super or take +1x); supers worth the sum of the jackpots that add a
  ball the first times; wizard modes that pay back your history; generous clocks (a lit shot puts it back to 15 s,
  the Haunts pause in the bumpers).

## The five, and what each takes from him

| Mode | Lyman mechanic | Starts on | Monster and film |
|---|---|---|---|
| GODZILLA ANGRY | EHoH's Gappa Angry: a meter of every switch, staged locks, a 6-ball multiball, failing still pays, Scream Test | the RAGE meter, then the Building | Baby Godzilla taken by G-Force: Godzilla vs. Mechagodzilla II (1993) |
| SPACEGODZILLA | EHoH's Garage and Batman '66's villain locks (harder each time), three multiballs in turn, supers worth the sum, the first supers add a ball | the shield targets light locks, the Big loop locks | SpaceGodzilla's crystal towers: Godzilla vs. SpaceGodzilla (1994) |
| KIRYU | Metallica's Sparky (a meter, each start costs more) and cash out or carry on | 30 spins of the Mechagodzilla spinner (+10 a time) | Kiryu's Absolute Zero: Godzilla Against Mechagodzilla (2002) |
| BIOLLANTE | TWD's Blood Bath and Metallica's FUEL (every switch scores into a jackpot a bank collects), generous clocks | 6 ramps (+2 a time) | Biollante, rose and beast: Godzilla vs. Biollante (1989) |
| DESTOROYAH | TWD's Horde (enemies advance; closer kills pay more; waves one kill longer; a cleared wave pays it again) | 30 center spins (+10 a time) | the Destoroyah aggregates: Godzilla vs. Destoroyah (1995) |

Every start shot is one no other pack mode qualifies on (KING GHIDORAH the powerlines, OXYGEN DESTROYER the left
spinner, MASER BARRAGE the Maser, MELTDOWN the captive ball, FINAL WARS the Building when lit). GODZILLA ANGRY's Building
is FINAL WARS's too when both are lit; whichever is asked first starts and the other stays lit.

**Isolation (PAD-347).** All five start only while none of the game's own modes runs and one ball is in play (a refused
start stays ready), block the game's modes the port lets them refuse while they run, and end the moment one of the
game's modes begins. A multiball of ours (GODZILLA ANGRY's, SPACEGODZILLA) holds display priority 190; the rest 180.

**The meter on the glass (David: "a switch hit counter on the UI").** `kit_hud_meter` in `intricate_kit.h`: a HUD the
mode is not using shows only its gauge on the right edge (12 pips, RAGE n/5) for as long as the meter counts; it is the
politest thing on the glass (another mode's note or HUD takes its place at once; it comes back by itself), it hides
during a multiball (when nothing counts), after a tilt, and from a drain to the next switch (the bonus has the screen).
The award line says the count every quarter of a level ("40 MORE FOR RAGE 3").

**Locks are virtual.** Godzilla's own locks (the Building's roof on Premium, Mechagodzilla's) belong to its own
multiballs; ours count a shot as a lock and the ball goes on, the way modern Stern virtual locks do.

## What is proven

- Desk: `tests/test_spike2_intricate_modes.py` plays each mode's flows through `desk_harness.c` (all eleven modes in one
  harness): the meter's levels and its multiball, tilt and ball rules; the chase, its locks, BABY FOUND, the 6-ball
  multiball, the smaller multiball on a time-out, the trail kept across a drain or gone cold; the three lock ladders and
  multiballs; the charge, the overheat, the vent, the fire by the captive ball, the button or the clock; the sap, the
  banks, the beast, the final blow, the clock floors; the swarm advancing, the closeness multipliers, the waves, the
  city, the perfect form. Every generic pack test runs on them too (HUD text widths, display priority first, a drain or
  tilt handing everything back, isolation, the assets header, clips by cue).
- **Emulator (logic), 2026-10-04, a stock Godzilla Premium 1.16 copy, the five built into one object with
  `mode_file.c`, hidden and muted, `C:\tmp\PAD-379\proof` (`run_logic*.sh`, `run_sg*.sh`):**
  - GODZILLA ANGRY (run logic3): 150 real slingshot presses counted as switch hits through the game's 0x1 dispatch
    (about nine in ten land in the rig), RAGE LEVEL 1 at 100. The meter filled by its trigger, then real switches
    played the whole chase: the Building started it, the captive ball and the Maser took the five locks, the Building
    was BABY FOUND, the game served all six balls, five drains took it to one and it ended "one ball left"; the
    meter started again at 125. That run's 19 Baby jackpots paid 500M, so the jackpot now builds half as fast.
  - KIRYU, BIOLLANTE, DESTOROYAH (run logic4): 30 real spins of the Mechagodzilla spinner started KIRYU, real shots
    charged it past 100% and the real ACTION BUTTON fired it (it ended "fired" 4 s later); six real ramps started
    BIOLLANTE, the real shield and powerline targets cut three banks (x1, x2, x3), the beast came and the Building
    was the final blow (WON); 30 real center spins started DESTOROYAH, aggregates came over the top at the real
    powerlines and the kills cleared waves 1 and 2 with their supers; the perfect form took two hits, then its clock
    ran out (the third press was lost in the rig).
  - SPACEGODZILLA (runs sg1, sg2): a real shield lit all three locks, three real Big loops planted the crystals and
    the multiball started; started by its trigger file and by its third crystal the game served the balls and the
    drains ended it "one ball left". **Found:** asked for inside the Big loop shot itself, the game said it was serving
    but never fired the trough (runs logic2-4); the multiball now starts 1.5 s after the third crystal (its
    SPACEGODZILLA ARRIVES moment), and the game serves it.
  - Isolation, seen for real: rage pokes on the inlanes collected the game's own missiles and started its JET FIGHTER
    ATTACK, and GODZILLA ANGRY waited ("a stock mode is running - still ready"), as PAD-347 has it.
  - segv 0, fatal 0, the baseline 6 throws in every run.
- **Emulator (with their assets), 2026-10-05: Try it's set built by Write's own code (`build_set.py`: the five
  modes' HUDs in the slide-outs scene, 38 clips in the video bank, 38 own sounds (33 calls, 5 music beds), the validation bypass) on
  the same stock Premium 1.16 copy; runs fullA, fullB, fullC2, fullD, glass shots in each run folder:**
  - GODZILLA ANGRY (fullB): the RAGE meter on the right edge (RAGE n/5, ten pips) filled by real slingshots, the
    award line's notes, GODZILLA IS ANGRY / SHOOT THE BUILDING; the intro full screen, the chase's HUD over the
    pagoda march (LOCKS 0/5, JACKPOT, SUPER, the ANGRY badge with the place's clock), the five locks, BABY FOUND full
    screen, the six-ball multiball's HUD (MULTIPLIER, JACKPOT AT BABY, JACKPOTS), drains to one ball, the ending clip.
    Total 157M (six Baby jackpots).
  - KIRYU (fullA): the intro, CHARGE / ABSOLUTE ZERO / MULTIPLIER over Kiryu at sunset, the overheat (X2 - 200%, the
    badge counting the overheat), fired by the real Action button, the blast and the ending clip.
  - BIOLLANTE (fullA): BANKS CUT / SAP JACKPOT / PER SWITCH over the rose, collects with the sap clip, the beast, the
    final blow at the Building, WON.
  - DESTOROYAH (fullC2): the aggregate bursting from the bay, WAVE / KILLS / CITY over the SDF line, wave 1 cleared,
    the perfect form, three Building hits, DESTOROYAH DEFEATED.
  - SPACEGODZILLA (fullC2, fullD): LOCKS ARE LIT, three crystals, the descent, TOWERS / JACKPOT / SUPER over the
    crystal field, jackpot clips behind the HUD, the SUPER badge, the super adds a ball, drains to one ball, the
    explosion ending.
  - Every sound the game looked up was the mode's own record (`[pad] sound swap: request N looked up <stock>, took
    <ours>`); segv 0, fatal 0, the baseline 6 throws.
- **Found and fixed on the way:** the edge counters clip long values (C1 on the left, C3 on the right) - short ones
  now ("0/5", "100K"); diamond and spike gauge pips run down onto the score panel - every gauge is segment pips, GODZILLA
  ANGRY's meter ten; BIOLLANTE's final blow at the Building also started a lit GODZILLA ANGRY on the same shot -
  `kit_just_ended()` (a shot that ended another of ours is not a start).
- **Rig behaviour, not the modes'** (recorded so the next run does not chase them): the rig never drains a ball itself
  (`plunge.py drain`); after a multiball's drains its trough model reads "not a stack" and a SECOND multiball in that
  game is not served; and 15-20 s with no switch hit starts Godzilla's ball search, after which a multiball asked for is
  not served either. Keep the rig playing (a slingshot every 2 s) and prove each multiball first in its game.
- The game's own award displays (LOOPS, BUILDING ATTACK, POWERLINE ATTACK AWARD, TANKS ADVANCE, its LOCK IS LIT) come
  through over the HUD while ours run, as PAD-353 decided; the middle words step aside and come back.

## Owed

- A machine. Everything above is the emulator: the feel of the meter's pace (100 to 200 hits a level), the lock
  shots, and each mode's values want a real game.
- Nothing is cut from a film into the repo: the Modes tab's Examples cut each mode's assets from the person's own copy
  (`film_recipes.json`, the same collection as the six before).
