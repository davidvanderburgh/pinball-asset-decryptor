# Example modes

Modes written in C against `pad_mode.h` (read `../MODE_SDK.md` first). Each file is one mode.

| File | Mode | What it shows |
|---|---|---|
| `powerline_blitz.c` | POWERLINE BLITZ | each target pays once, completing ends it, a shield ends it early (item 134) |
| `ghidorah_heads.c` | KING GHIDORAH | a boss battle with health, a lit target that moves, regrowth, a final blow |
| `oxygen_destroyer.c` | OXYGEN DESTROYER | a hurry-up: a value that drains in real time, then a super jackpot worth double |
| `maser_barrage.c` | MASER BARRAGE | a combo chain with a timer between shots and a growing multiplier; started at the Maser target |
| `final_wars.c` | FINAL WARS | a multi-phase wizard mode, lit by playing the other modes, with add-time shots |
| `anguirus_assist.c` | ANGUIRUS | a mode that stacks with the game's own battle on purpose: it starts and ends with it |
| `meltdown.c` | MELTDOWN | a MULTIBALL of our own: a core temperature that climbs, sets the jackpots' multiplier, and melts down at 100% (hud-layers) |
| `godzilla_angry.c` | GODZILLA ANGRY | a RAGE meter every switch fills, all game (one bar to the mode, in the stock POWERUP meter's manner), a chase in staged locks, a 6-ball multiball (PAD-379, after EHoH's Gappa Angry) |
| `spacegodzilla.c` | SPACEGODZILLA | a multiball of crystal locks that are harder to light each time, three multiballs in turn, supers worth the sum (PAD-379) |
| `kiryu.c` | KIRYU | charge the Absolute Zero, then fire it or push your luck into an overheat (PAD-379, after Metallica's Sparky) |
| `biollante.c` | BIOLLANTE | a switch frenzy: every switch feeds a sap jackpot the vine banks collect (PAD-379, after TWD's Blood Bath) |
| `destoroyah.c` | DESTOROYAH | waves of aggregates that advance down the playfield; the closer the kill, the more it pays (PAD-379, after TWD's Horde) |
| `ebirah_rewrite.c` | EBIRAH, three shots then the Building | the game's OWN Ebirah battle with its shot logic replaced in C (item 161, against `../pad_stock.h`; emulator-proven on Premium 1.16, MODE_SDK.md says what was measured) |

**How they look (hud-layers).** Like the game's own battles: an intro clip full screen when a mode starts,
then a clip looping BEHIND the score panel (`pm_backdrop`), and the mode's words at the glass's EDGES in the
game's own font - its title and what to shoot above the score panel, counters across the top, a timer
badge made from the stock BATTLE badge with the mode's own label and icon, and a gauge on the right edge
(MODE_SDK.md, "A mode that looks like the game's own"). Events play their own clip behind the HUD, endings
play full screen, and every start and end has its own light show. No picture panel any more.

The six after POWERLINE BLITZ (item 152, and MELTDOWN) were written for Godzilla Premium 1.16 (`godzilla_le-1.16.port`) and use
only shot names, events and callout roles that port has. They also build and run on Pro 1.15's port,
which has two shield targets where Premium has three (ANGUIRUS then needs two spikes, and FINAL
WARS has two add-time targets). They share `intricate_kit.h`:

- **a debounce**: one shot counts once in 250 ms. A target that bounces, or is hit twelve times in
  a second, pays at most four times (`... again 83 ms after the last: counted once` in the log);
- **the mode's own screen**: a status line that can alternate with a second one, a short flash over
  it, the total at the end, words written only when they change (every `pm_set_text` leaks a small
  string inside the game), and one screen up at a time across the pack;
- **the light sweep** in any colour (the port's example command recoloured), sent only on a change.
  The five do not use it any more: measured in item 157's run, the set it lights includes the RGB
  inserts around the shots, so it made ramps and loops that pay nothing look lit;
- **the playfield's inserts** (item 157, `struct kit_lamps`): every tick a mode says which SHOTS are lit
  and how (a colour, a pattern, a speed), and only a change reaches the game. They are held in one
  layer at priority 200, over every light show the game ran (its highest measured was 145), so a shot
  of ours is never hidden while the game's own inserts around it keep animating; every one is handed
  back the moment the mode ends, a drain, or a tilt. The pack speaks one light language: SOLID = lit,
  no clock; BLINK = lit with a clock, faster as it runs out (700, 400, 200, then 100 ms in the last 3 s);
  PULSE = optional (adds time, or a head growing back); DIM = in the sequence, not next yet;
- **the display priority** (item 157, `kit_display`): taken right after the mode starts, before its
  screen and clip, and given up before `pm_end`. 180 for a mode, 190 for FINAL WARS. BATTLE IS LIT
  waits and plays at the end; the game's full-screen shot awards (LOOPS, POWERLINE ATTACK) are not shown
  over the panel (a waiting one froze the game's drawing, so the runtime drops them); its jackpots,
  battle and multiball starts, the battle select screen and the tilt warning come through, and the panel
  is back when they end. A flash
  on the panel counts its time only while the panel is in view (`pm_display_covered`);
- **the tilt**: every mode ends on the game's tilt event (the tilted ball's own drain comes later);
- **a countdown** with the game's own "ten seconds" and 5..1 voice;
- **a new-game witness** (player 1's score back to 0) for per-game counts;
- **the pack ledger**: which pack modes each player played and won this game (FINAL WARS lights
  from it). The ledger, the running mode and the screen up are WEAK definitions in the header, so
  every file that includes it shares one copy inside `mode.so`, and a file built alone still links.

Every sound is one function per mode, `sound(enum cue)`. It plays the mode's OWN clip, music and
calls through `../pad_mode_assets.h` (MODE_SDK.md, "A code mode's own clip, screen, music and calls"):
START plays its music bed and its start clip, END fades the music and gives the game's music back,
and each event is a cue the card carries (a cue it does not carry falls back to the game's own
time-up call, or silence). The countdown (ten seconds, 5..1) is always the game's own voice.

| Mode | Cues | Films its assets are cut from |
|---|---|---|
| KING GHIDORAH | `sever` (a head severed), `regrow` (a head grows back), `won` (the super jackpot), `lost` (Ghidorah escapes) | Invasion of Astro-Monster (1965): clip, picture, music, won, lost; Ghidorah, the Three-Headed Monster (1964): sever, regrow |
| OXYGEN DESTROYER | `collect` (the hurry-up collected), `won` (the super jackpot), `lost` (the value lost, or the super jackpot missed) | Godzilla (1954): clip, picture, calls; Godzilla vs. Destoroyah (1995): music |
| MASER BARRAGE | `barrage` (a barrage completed), `broken` (the chain broken), `won` / `lost` (the clock, with or without a barrage) | Godzilla vs. Megalon (1973): the Maser cannons, the music, the calls |
| FINAL WARS | `phase1`, `phase2` (a phase won), `won` (the wizard shot), `lost` (a phase's clock runs out) | Godzilla: Final Wars (2004) |
| ANGUIRUS | `spike` (a spike charged), `roll` (a rolling attack), `won` / `lost` (it leaves, with or without a roll) | Godzilla Raids Again (1955) |
| GODZILLA ANGRY | `rage` (a rage level), `angry` (the meter full), `lock`, `baby` (BABY FOUND), `jackpot`, `super`, `won` / `lost` | Godzilla vs. Mechagodzilla II (1993) |
| SPACEGODZILLA | `lit` (a lock lit), `lock` (a crystal planted), `jackpot`, `tower` (a tower falls), `super`, `add`, `won` / `lost` | Godzilla vs. SpaceGodzilla (1994) |
| KIRYU | `charge` (another 100%), `ready`, `fire` (ABSOLUTE ZERO), `overheat` (and a vent), `won` / `lost` | Godzilla Against Mechagodzilla (2002) |
| BIOLLANTE | `cut` (a vine), `collect` (a bank: the sap jackpot), `beast` (her beast form), `won` / `lost` | Godzilla vs. Biollante (1989) |
| DESTOROYAH | `kill`, `escape` (the city is hit), `wave` (a wave cleared), `boss` (the perfect form), `won` / `lost` | Godzilla vs. Destoroyah (1995) |

`film_recipes.json` has every film time (clip, picture frame, music loop, each call) and what was
measured to pick it; nothing of a film is in this repo. The Modes tab's Examples add these five as
code modes and cut the assets from the person's own copy of the films.

Build them all, with the mode-file interpreter, into the object a card carries:

```bash
bash ../build_mode.sh -o mode.so ghidorah_heads.c oxygen_destroyer.c maser_barrage.c \
    final_wars.c anguirus_assist.c meltdown.c godzilla_angry.c spacegodzilla.c kiryu.c \
    biollante.c destoroyah.c ../mode_file.c
```

Each mode finds its screen as `PadMode_<file name>_Screen` (MODE_SDK.md, "Screens"); the card build
adds the five panels to the HUD scene. Without them the modes run the same, with no words.

**On a card**, the app's Write carries them from a project (`modes/<folder>/<folder>.c` with its
`assets.json`): the object compiled from them with `mode_file.c`, and one `<folder>.assets` per mode
beside it naming the carriers of its music and calls. A card of code modes only needs no mode file
(`mode_install.py --asset`; the emulator's card reader `../../cardmodes.sh` names each mode from its
.assets file). The item 152 card, built by hand before this, carries a placeholder `mode.cfg` instead.

## Play them at the desk

`desk_harness.c` stands in for the game: it calls every mode the way the runtime does and prints
every score, word, light command, insert held or handed back, display priority and callout
(`covered 1` makes a display of the game's cover the panel; `lamps` lists what is held). It needs a
Linux (ELF) C compiler.

```bash
gcc -std=gnu17 -I.. -o harness desk_harness.c ghidorah_heads.c oxygen_destroyer.c \
    maser_barrage.c final_wars.c anguirus_assist.c meltdown.c godzilla_angry.c spacegodzilla.c \
    kiryu.c biollante.c destoroyah.c
./harness shot "Powerline left" shot "Powerline center" shot "Powerline right" \
          shot "Left ramp" secs 12 event skill_shot battle 1 secs 1 ball_end
```

`tests/test_spike2_intricate_modes.py` plays every mode's flows this way.

## The rules sheets

Where the shots are, on Godzilla, read from the game's own device map (each switch's place on its
playfield picture), not checked on a machine: the LEFT RAMP and RIGHT RAMP are the two ramps; the
BUILDING is the city building, upper middle-left; the three POWERLINE targets are a row across the
upper playfield (left, center, right); the GODZILLA target is upper left, beside the Building; the
MASER target is on the left side, halfway down; the three SHIELD targets are on the right side,
halfway down, in front of Mechagodzilla; the BIG LOOP is the orbit across the top.

**The shields on a Premium/LE (PAD-379).** There the shield targets sit on a platform a motor turns, and most of
the game it faces AWAY: the shield ramp spinner faces the player and the shields cannot be hit from the flippers
(the game turns them toward the player for parts of its Mechagodzilla multiball). So the modes that play the
shields - MELTDOWN, FINAL WARS, KIRYU, BIOLLANTE, DESTOROYAH and SPACEGODZILLA's M.O.G.U.E.R.A. multiball - turn the
platform toward the player 1.5 s after they start (the ball that started the mode is clear of it by then) and back
away when they end (`pm_shield`, `kit_shields_in` / `kit_shields_out`). A shield hit makes the game turn the platform
away (its own reaction); the mode turns it back 1.5 s later, so the shield recoils and returns. If one of the game's own modes takes over,
the platform is left as that mode wants it. While it turns, or if an operator switched the motor off, the modes put
nothing they need on the shields (`kit_shields_reachable`). A Pro's two shield targets are fixed and face the
player: nothing turns. ANGUIRUS is the exception: it joins the game's own battles, and those play with the shields
away, so on a Premium its spikes are only reachable when the battle itself has the shields toward the player.

### MELTDOWN (`meltdown.c`): a multiball of our own

- **How to light it:** hit the Magna-Grab CAPTIVE BALL (the Godzilla target) 10 times in a game. Each hit
  says how many are left; the tenth says MELTDOWN IS READY and the MAGNA GRAB insert pulses red.
- **How to start it:** hit the captive ball again: 3 balls in play, a 15 s ball save. It waits (still
  ready) while another of our modes, or the game's own battle or multiball, runs.
- **The core:** Burning Godzilla's core temperature starts at 25% and rises 1% a second (2% from 70%);
  each jackpot heats it 4% (8% for the HEART). The heat is the multiplier: STABLE x1, HOT x2 (40%),
  CRITICAL x3 (70%), MELTDOWN IMMINENT x5 (90%).
- **Jackpots:** the LEFT RAMP, RIGHT RAMP, BUILDING and BIG LOOP: 2,000,000 x the heat. One of them is the
  HEART (it moves every 8 s and when hit): double.
- **Cadmium:** each SHIELD target cools the core 12% (the Super X III's cadmium): cool him down, or ride the
  heat for x5.
- **MELTDOWN:** at 100% the BUILDING is the MELTDOWN SUPER JACKPOT for 20 s: twice every jackpot this
  multiball paid. Made: Godzilla Junior absorbs the radiation, the core back to 25%, the jackpots' base
  +500,000. Missed: the core blows, back to 50% and the base back to 2,000,000.
- **Add-a-ball:** after 4 jackpots the MAGNA GRAB insert lights green; the captive ball adds a ball, once.
- **How it ends:** one ball left (after the ball save and 3 s more), a tilt.
- **The glass:** Burning Godzilla steaming in the dark, full screen; his night walk glowing red behind the
  score panel; CORE, JACKPOT and JACKPOTS across the top, the CORE gauge on the right filling yellow to
  white-hot, the MELTDOWN badge counting its 20 s. The spiral ray behind the HUD at a jackpot, the freezing
  mist at cadmium, the glowing veins crossing into CRITICAL; the meltdown and Junior's revival full screen.
- **Inserts:** the four jackpot shots in the heat's colour (yellow, orange, red, flashing white), the HEART
  blinking; the shields ice blue while the core is above 40%; MELTDOWN: only the Building, strobing white.
- **Lights:** the playfield dark and a red fire rising into a white-hot strobe at the start; a white
  implosion into the Building at MELTDOWN; a burst of blue and white at the super jackpot; embers at the end.
- **Sound:** Ifukube's end-title march from Godzilla vs. Destoroyah as its bed; his roar when it is ready,
  the spiral ray, the freezer beams, a strained roar at CRITICAL, the final battle's biggest blast, Junior's
  roar.

### KING GHIDORAH (`ghidorah_heads.c`): a boss battle

- **How to start it:** hit all three powerline targets (any order) in one ball. The third one starts it.
- **What to do:** Ghidorah has three heads with 3 health each. LEFT HEAD is the Left ramp (2 damage)
  or the left powerline (1). MIDDLE HEAD is the Building (2) or the center powerline (1). RIGHT HEAD
  is the Right ramp (2) or the right powerline (1). Only the LIT head is hurt: 1,000,000 a point.
  Another head gives a glancing blow: 250,000, no damage.
- **The twist:** the lit head moves to the next head every 8 s. A wounded head left alone for 10 s
  grows 1 health back. Severing a head pays 5, 10, then 15 million and adds 10 s.
- **The final blow:** with all three severed, the Maser target is lit for 15 s: the super jackpot,
  20,000,000 plus 1,000,000 a second left.
- **How it ends:** the super jackpot (GHIDORAH DEFEATED), or GHIDORAH ESCAPES when the 50 s clock or
  the final blow runs out, or a drain or a tilt. The screen shows the total for 6 s.
- **Inserts:** the lit head's ramp (or the Building) and its powerline are GOLD: solid at full health,
  blinking at 2, blinking fast at 1. A wounded head that is not lit PULSES GREEN (it is growing back).
  The final blow: MASER and MASER READY flash white. Display priority 180.
- **How often:** once a ball, twice a game. It waits while the game's own kaiju battle or a multiball
  runs (the game's, or two balls in play): the next powerline after it starts it.

### OXYGEN DESTROYER (`oxygen_destroyer.c`): a hurry-up

- **How to start it:** spin the LEFT SPINNER 25 times in one ball (hud-layers: it used to be the Godzilla
  target 3 times; that captive ball now leads to MELTDOWN). The Godzilla target is its hold-off.
- **What to do:** a value starts at 20,000,000 and falls 800,000 a second. The LEFT RAMP collects it.
  The Godzilla target holds it off: 2 s back, three times.
- **Then:** the RIGHT RAMP is lit for 12 s: the super jackpot, DOUBLE what you collected.
- **How it ends:** the super jackpot, or the super jackpot's 12 s run out (you keep what you
  collected), or the value reaches 0 before you collect it (LOST, nothing), or a drain or a tilt.
- **Inserts:** the LEFT RAMP blinks green, yellow, then red as the value falls, faster each time; the
  Godzilla target's insert (MAGNA GRAB) pulses while a hold-off is left; collected, the RIGHT RAMP
  flashes white for the super jackpot. Display priority 180.
- **How often:** three times a game, 15 s apart at least. It waits out a multiball (the game's, or two
  balls in play), still ready: the next spin after it starts it. Beside the game's battles and timed
  modes it runs, its words aside.

### MASER BARRAGE (`maser_barrage.c`): a combo chain

- **How to start it:** hit the Maser target 3 times in one ball (PAD-371: no longer on the game's
  skill shot).
- **What to do:** LEFT RAMP, then RIGHT RAMP, then the BUILDING, in that order. Each step pays
  1,000,000 times the multiplier. After a step the next one must come within 7 s.
- **The chain:** the third step is a barrage: a jackpot of 5,000,000 times the multiplier, then the
  multiplier goes up (to x5 at most), the clock gains 5 s, the window shrinks by 1 s (to 4 s at
  least) and the sequence starts again. Miss a window and the CHAIN BREAKS: back to x1 and the Left ramp.
- **How it ends:** the 40 s clock (plus 5 s a barrage), or a drain or a tilt. A step that counts with
  under 10 s on the clock puts it back to 10 s (PAD-371).
- **Inserts:** the NEXT shot is bright Maser blue, the other two a dim blue: the whole chain is on the
  playfield. The next shot is solid until the first step, then blinks while its window runs, faster as
  it closes (500, 250, then 100 ms). Display priority 180.
- **How often:** once a ball. A skill shot made while another pack mode runs waits 15 s for it. It waits
  out a multiball (the game's, or two balls in play): after three Maser hits the next Maser hit after it
  starts it; a skill shot during a multiball is not held.

### FINAL WARS (`final_wars.c`): the wizard mode

- **How to start it:** first light it: play KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE in one
  game, or win any two of them. The screen says FINAL WARS IS LIT. Then shoot the BUILDING.
- **Phase 1, INVASION (25 s):** the Left ramp, the Right ramp and the Big loop are lit; 3,000,000
  each; all three go to phase 2.
- **Phase 2, MONSTER X (25 s):** one of the three powerlines or the Godzilla target is lit, and it
  moves every 3 s (and after each hit). Hit it 3 times: 5, 10, then 15 million.
- **Phase 3, GHIDORAH (20 s):** the BUILDING is the wizard shot: 30,000,000 plus 1,000,000 a second left.
- **Add time:** any shield target adds 3 s to the phase, three times a phase.
- **How it ends:** GODZILLA WINS (the wizard shot), THE XILIENS WIN (a phase's clock runs out), or a
  drain or a tilt.
- **Inserts:** lit and waiting, the BUILDING pulses gold (while no pack mode runs, not between balls).
  Phase 1: the ramps and the Big loop still to save blink orange; phase 2: only MONSTER X's insert
  flashes, and it follows it; phase 3: the BUILDING blinks gold. Blinks speed up with the phase clock.
  The shield inserts pulse green while add-time is left. Display priority 190 (a wizard mode: the
  game's jackpots also wait, and its multiball and battle start screens are not shown).
- **How often:** once per lighting; it has to be earned again. It never runs beside the game's own
  battle or multiball: it waits, still lit.

### ANGUIRUS (`anguirus_assist.c`): an ally in the game's battle

- **How to start it:** it starts by itself when one of the game's own kaiju battles begins.
- **What to do:** each shield target charges a spike: 500,000. Three spikes light the BIG LOOP for a
  rolling attack: 4,000,000, doubling for each loop within 6 s of the last (8, then 16 million).
  Six seconds without a loop ends the roll; charge the spikes again.
- **How it ends:** with the game's battle, or a drain or a tilt. The game's battle itself is never touched.
- **Inserts:** the shield inserts are the charge meter: blinking orange = still to charge, solid orange
  = charged. The roll lit: the BIG LOOP blinks cyan, faster as its 6 s run out.
- **The glass (hud-layers):** the battle keeps its own clip, title, counters and BATTLE badge; ANGUIRUS keeps
  to the right edge: its SPIKES gauge, a spike lighting as it charges, from its entrance to its exit. Its
  entrance (the intro clip full screen, its music) waits until the battle's start screen is over
  (`pm_display_covered`); after that its award line speaks for 3 s at a spike, the roll lit and each rolling
  attack, holding display priority 180 only for those moments; its total waits for the battle's own.
- **How often:** once per game battle.

## The Lyman Sheats modes (PAD-379)

David, 2026-10-04: "I want to see some new modes in Godzilla that are inspired by Lyman Sheets games. For example, having
a 'Gappa Angry' type mode would be amazing in Godzilla with a switch hit counter on the UI and feedback that it's
progressing towards the mode (and not counting switch hits during multiball) and having staged locks". Lyman F. Sheats Jr.
wrote the rules of Elvira's House of Horrors (to 1.00), The Walking Dead, Metallica, Batman '66, AC/DC and Medieval
Madness, among others; Godzilla's own are Rick Naegele's and Keith Elwin's. Each mode below borrows one of his signature
mechanics (`docs/plans/lyman_modes.md` has the research and the sources) and a Toho monster the stock game never uses,
so it plays on shots and in stories the game has not worn out. They follow the pack's rules: one of ours at a time,
isolated from the game's own modes (PAD-347), the HUD at the glass's edges, the light language above, own clips, music
and calls cut from the films.

### GODZILLA ANGRY (`godzilla_angry.c`): EHoH's Gappa Angry

- **How to start it:** fill the RAGE meter. Every playfield switch hit counts (the game's 0x1 dispatch), all game, for
  the player up, through every other mode and multiball, ours and the game's (PAD-416: only the mode itself and a tilt
  stop it; in a multiball it counts quietly). It is ONE meter to the mode (PAD-416, David: "the whole meter should be
  100% towards the mode"): 750 hits, in the stock POWERUP meter's manner at the glass's top-right corner - a metal frame,
  the rage flame in a diamond, a glass tube in five cells that a red-to-orange liquid fills, GODZILLA / RAGE and its
  percent beside it. Each cell (100, 125, 150, 175 and 200 hits: EHoH's 150 to 250, for Godzilla's single pop bumper)
  pays 1,000,000 more 500,000 a cell at its mark, with a roar and a red throb up the playfield ("RAGE 40%"); the award
  line counts to the mode every quarter of a cell ("120 MORE TO GODZILLA ANGRY"). Full, GODZILLA IS ANGRY: the
  BUILDING insert pulses red and the BUILDING starts the chase.
- **The chase (Godzilla vs. Mechagodzilla II: G-Force carried Baby Godzilla away):** five places, each its lit shots in
  any order and then a LOCK (virtual: the ball stays in play). ADONOA ISLAND: lock at the captive ball. YOKKAICHI: both
  ramps, lock at the Maser. OSAKA: the Big loop and the Building, lock at the captive ball. KYOTO: both ramps, the
  Building and the Big loop, lock at the Maser. MAKUHARI: both ramps, the Big loop, the Building and the center
  powerline, lock at the captive ball. Then BABY: the Building is BABY FOUND, the SUPER JACKPOT and a 6-ball multiball.
- **Scoring:** a lit shot pays 500,000, +500,000 a place and +25,000 a shot within it, and an eighth of it goes to the
  JACKPOT; a lock pays twice the shot and adds 250,000 a place to the JACKPOT. Every switch hit during the chase adds
  10,000 to the SUPER JACKPOT (from 5,000,000). A 5 s ball save at the start.
- **Clocks:** 30 s a place; a lit shot with under 15 s left puts it back to 15 (EHoH's Haunts).
- **Failing still pays:** a place's clock running out with locks made turns them into a multiball of the locks + 1
  balls, scoring the JACKPOT built. With no lock yet the trail goes cold (still angry: the Building starts it again). A
  drain with locks made does not end the ball (PAD-416): from the first lock the chase keeps a ball save of its own, and
  the drain (the trough's switch) sends the locked balls straight into ANGRY MULTIBALL, as many as were locked (two at
  least). A drain with no lock ends the chase, and the place waits for the next ball.
- **ANGRY MULTIBALL:** the ramps, the Building and the Big loop are lit; one is BABY (green, it moves every 10 s and when
  hit): BABY pays the JACKPOT times the multiplier; any other lit shot pays 500,000 and raises the multiplier, up to x6
  (EHoH's Scream Test). 15 s ball save; it ends with one ball left.
- **How it ends:** the multiball's last ball, a tilt, one of the game's own modes beginning. Then the meter starts again,
  every level 25 hits more.
- **Inserts:** ready, the BUILDING pulsing red; the chase, the place's shots red and the lock white, blinking faster as
  the clock runs out; the multiball, the jackpot shots orange and BABY green. Display priority 180, 190 in the multiball.

### SPACEGODZILLA (`spacegodzilla.c`): locks that are harder to light each time

- **How to light a lock:** the POWERLINE targets. The first time any powerline lights all three locks; the second time
  each powerline hit lights one lock; from the third, two powerline hits a lock (EHoH's Garage, Batman '66's villain
  locks). The powerlines face the player on every Godzilla; the three in one ball also start KING GHIDORAH.
- **How to lock:** the BIG LOOP while a lock is lit: SpaceGodzilla plants CRYSTAL 1, 2, 3 (250,000 times the crystal's
  number). The locks are virtual and wait across balls. Nothing lights or locks during a multiball or another of our
  modes.
- **How to start it:** the third crystal starts CRYSTAL MULTIBALL, 3 balls with a 15 s ball save. While one of the game's
  own modes runs it waits, still ready: the next Big loop after it starts it.
- **What to do:** three crystal towers stand on the LEFT RAMP, the BUILDING and the RIGHT RAMP. Each JACKPOT (the base,
  +100,000 a jackpot) cracks its tower; a tower falls after 2. All three down lights the SUPER JACKPOT at the BIG LOOP for
  20 s, worth every jackpot since the last super (Metallica's Casket). The first three supers add a ball. Then the towers
  grow back one jackpot stronger.
- **In turn:** the first multiball is CRYSTAL TOWERS (jackpots from 1,000,000); the second M.O.G.U.E.R.A. (from
  1,500,000, stronger towers, and every SHIELD target a spiral grenade: +250,000 on every jackpot, the shields turned
  toward the player for it on a Premium); the third and after
  SPACE BEAST (from 2,000,000, and every 5th jackpot lights the super too, EHoH's Attic Attack).
- **How it ends:** one ball left, a tilt, one of the game's own modes beginning.
- **Inserts:** a lit lock, the BIG LOOP blinking purple; the towers purple, blinking on their last jackpot; the super, the
  BIG LOOP flashing white; M.O.G.U.E.R.A.'s shields pulsing cyan. Display priority 190.
- **How often:** every three crystals.

### KIRYU (`kiryu.c`): charge, then fire or push your luck

- **How to start it:** spin the MECHAGODZILLA spinner (the shield ramp's) 30 times; every spin counts. Then 40, then 50
  (Metallica's Sparky: each start costs more).
- **What to do:** a 40 s clock. The lit shots charge Kiryu's ABSOLUTE ZERO: the ramps, the Building and the Big loop 15%,
  the Maser 10%, each shield target 8% (turned toward the player for the mode on a Premium, which closes the spinner),
  every spin of the Mechagodzilla spinner 1%. Each shot pays 750,000; a lit shot
  with under 15 s left puts the clock back to 15.
- **Fire or push your luck:** from 100% the CAPTIVE BALL (Godzilla) or the ACTION BUTTON fires it: 10,000,000 times the
  multiplier plus a quarter of everything the mode scored, and KIRYU WINS. Or charge on: 200% is x2, 300% x3, 400% x4. From
  200% the reactor OVERHEATS: 12 s to fire, each 100% more gives 12 s again; run out and Kiryu VENTS, the charge back
  to 0 (Metallica's Crank It Up and Batman '66's cash it now or take +1x).
- **How it ends:** fired; the clock (at 100% or more Kiryu fires on its own at x1 with no bonus, under it the charge is
  lost); a drain; a tilt; one of the game's own modes beginning.
- **Inserts:** the charging shots ice blue; ready, the CAPTIVE BALL and the ACTION BUTTON flashing white; overheating,
  flashing red, faster as the seconds run out. Display priority 180.

### BIOLLANTE (`biollante.c`): a switch frenzy

- **How to start it:** 6 ramp shots in a game (either ramp); then 8, then 10.
- **What to do:** a 40 s clock. EVERY playfield switch scores the switch value (100,000, +25,000 for each vine bank cut)
  and adds it to the SAP JACKPOT (TWD's Blood Bath, Metallica's FUEL). The three SHIELD targets and the three POWERLINE
  targets are two banks of vines (the shields turned toward the player for the mode on a Premium; on a Pro its two
  shield targets are the bank): a whole bank cut COLLECTS the sap jackpot times the banks cut so far (x1, x2, x3) and
  grows back. A vine with under 15 s left puts the clock back to 15; each pop bumper hit gives a second back.
- **The beast:** after three collects Biollante comes back as the BEAST: 20 s, and the BUILDING is the FINAL BLOW, worth
  everything the three collects paid.
- **How it ends:** the final blow (BIOLLANTE IS FREE), the clock (she withers), a drain, a tilt, one of the game's own modes.
- **Inserts:** the vines still standing green; the beast, the BUILDING blinking gold. Display priority 180.

### DESTOROYAH (`destoroyah.c`): TWD's Horde

- **How to start it:** spin the CENTER spinner 30 times (then 40, 50).
- **What to do:** aggregates come over the top at the POWERLINES (far, x1) and advance every few seconds to the RAMPS,
  the BUILDING or the BIG LOOP (near, x2), then to the MASER, the SHIELDS or the CAPTIVE BALL (close, x4), then into
  the city. Up to two at a time. A kill pays 1,000,000 (+250,000 a wave) times how close it was: let one come closer
  for more, at your risk. On a Premium the shields turn toward the player for the mode, and no aggregate comes to a
  shield until they face the player.
- **Waves:** 3, 4 and 5 kills; they advance every 7, 6 and 5 s. A cleared wave pays every kill of the wave again.
- **The city:** an aggregate that gets past the close shots hits the city; three hits and Destoroyah wins.
- **The perfect form:** after wave 3, the BUILDING for 25 s: three hits of 5,000,000, the third the SUPER JACKPOT,
  every kill of the mode again.
- **How it ends:** the perfect form defeated (won), three city hits or the perfect form's clock (lost), a drain, a tilt,
  one of the game's own modes beginning.
- **Inserts:** each aggregate's shot, far yellow, near orange and blinking, close red and flickering; the perfect form,
  the BUILDING blinking red. Display priority 180.

Only one pack mode runs at a time, whatever starts it.

**Beside the game's own modes (PAD-347).** Stern never shows two modes' words at once: one mode has the
middle of the screen, the others keep to their badges at the edge. While one of the game's modes runs
(a battle, a multiball, a timed mode such as JET FIGHTER ATTACK), a pack mode that keeps running steps
aside as ANGUIRUS always has: its title and instruction line move into the award line between the
game's counters and its title, its counters along the top are hidden, its gauge stays on the right
edge, and its timer badge drops one slot while a battle's BATTLE badge has the top one. When the
game's mode ends everything goes back (MODE_SDK.md "Stepping aside").
