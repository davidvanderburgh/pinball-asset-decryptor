# Example modes

Modes written in C against `pad_mode.h` (read `../MODE_SDK.md` first). Each file is one mode.

| File | Mode | What it shows |
|---|---|---|
| `powerline_blitz.c` | POWERLINE BLITZ | each target pays once, completing ends it, a shield ends it early (item 134) |
| `ghidorah_heads.c` | KING GHIDORAH | a boss battle with health, a lit target that moves, regrowth, a final blow |
| `oxygen_destroyer.c` | OXYGEN DESTROYER | a hurry-up: a value that drains in real time, then a super jackpot worth double |
| `maser_barrage.c` | MASER BARRAGE | a combo chain with a timer between shots and a growing multiplier; started by the game's skill shot EVENT |
| `final_wars.c` | FINAL WARS | a multi-phase wizard mode, lit by playing the other modes, with add-time shots |
| `anguirus_assist.c` | ANGUIRUS | a mode that stacks with the game's own battle on purpose: it starts and ends with it |
| `ebirah_rewrite.c` | EBIRAH, three shots then the Building | the game's OWN Ebirah battle with its shot logic replaced in C (item 161, against `../pad_stock.h`; emulator-proven on Premium 1.16, MODE_SDK.md says what was measured) |

The last five (item 152) were written for Godzilla Premium 1.16 (`godzilla_le-1.16.port`) and use
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

`film_recipes.json` has every film time (clip, picture frame, music loop, each call) and what was
measured to pick it; nothing of a film is in this repo. The Modes tab's Examples add these five as
code modes and cut the assets from the person's own copy of the films.

Build them all, with the mode-file interpreter, into the object a card carries:

```bash
bash ../build_mode.sh -o mode.so ghidorah_heads.c oxygen_destroyer.c maser_barrage.c \
    final_wars.c anguirus_assist.c ../mode_file.c
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
    maser_barrage.c final_wars.c anguirus_assist.c
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
- **How often:** once a ball, twice a game. It waits while the game's own kaiju battle runs: the next
  powerline after it starts it.

### OXYGEN DESTROYER (`oxygen_destroyer.c`): a hurry-up

- **How to start it:** the Godzilla target 3 times in one ball.
- **What to do:** a value starts at 20,000,000 and falls 800,000 a second. The LEFT RAMP collects it.
  The Godzilla target holds it off: 2 s back, three times.
- **Then:** the RIGHT RAMP is lit for 12 s: the super jackpot, DOUBLE what you collected.
- **How it ends:** the super jackpot, or the super jackpot's 12 s run out (you keep what you
  collected), or the value reaches 0 before you collect it (LOST, nothing), or a drain or a tilt.
- **Inserts:** the LEFT RAMP blinks green, yellow, then red as the value falls, faster each time; the
  Godzilla target's insert (MAGNA GRAB) pulses while a hold-off is left; collected, the RIGHT RAMP
  flashes white for the super jackpot. Display priority 180.
- **How often:** three times a game, 15 s apart at least. It runs beside anything the game does.

### MASER BARRAGE (`maser_barrage.c`): a combo chain

- **How to start it:** make the game's own skill shot (the `skill_shot` event), or hit the Maser
  target 3 times in one ball.
- **What to do:** LEFT RAMP, then RIGHT RAMP, then the BUILDING, in that order. Each step pays
  1,000,000 times the multiplier. After a step the next one must come within 7 s.
- **The chain:** the third step is a barrage: a jackpot of 5,000,000 times the multiplier, then the
  multiplier goes up (to x5 at most), the clock gains 5 s, the window shrinks by 1 s (to 4 s at
  least) and the sequence starts again. Miss a window and the CHAIN BREAKS: back to x1 and the Left ramp.
- **How it ends:** the 40 s clock (plus 5 s a barrage), or a drain or a tilt.
- **Inserts:** the NEXT shot is bright Maser blue, the other two a dim blue: the whole chain is on the
  playfield. The next shot is solid until the first step, then blinks while its window runs, faster as
  it closes (500, 250, then 100 ms). Display priority 180.
- **How often:** once a ball. A skill shot made while another pack mode runs waits 15 s for it.

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
- **The screen:** it yields to the battle, whose own screen (timer, shot progress, what to shoot) sits
  where the panel does. Its entrance (clip, music, panel) waits until the battle's start screen is over
  (`pm_display_covered`); after that the panel speaks for 3 s at a spike, the roll lit and each rolling
  attack, holding display priority 180 only for those moments; its total waits for the battle's own.
- **How often:** once per game battle.

Only one pack mode runs at a time, whatever starts it.
