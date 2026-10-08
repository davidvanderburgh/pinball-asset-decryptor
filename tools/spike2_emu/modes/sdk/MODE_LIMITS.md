# What a mode can and can't do

Where the Modes tab's reach ends, with the things people ask for most as examples.

## The short version

Stern's own modes are compiled into the game program, and the app doesn't rewrite that code. Your mode runs next to it and talks to the game through hooks the app knows for each build. That gives three zones:

- **Your modes:** wide open. Your own start, shots, scoring, screen, clips, sounds, music and lights.
- **The game's modes:** you can change their numbers (timers, awards), not how they work.
- **Everything else:** progression, settings, high scores and Insider Connected are off limits, and so are the coils, apart from a few Godzilla mechanisms a mode may hold for a moment.

## Quick answers

### Your modes

| I want to... | Answer |
|---|---|
| Make a new mode with its own name, screen, clip, music and callouts | Yes. [Example 2](#2-a-mothra-mode-of-my-own) |
| Start it on shots, a timer or a game event (ball start, skill shot, multiball...) | Yes. Events vary by game. |
| Start it on a flipper or Action button | Godzilla only |
| Start it after another of my modes | Yes, with "Only after" |
| Start it when the player beats one of the game's battles | No. No game reports a win. |
| Run two of mine at once | No. One at a time. |
| Take points away | Form modes only (a minus number under Points per shot) |
| Give it sounds of its own | Yes, up to 16. Each rides on a game sound that never plays; the card has a fixed number of those (21 on Godzilla), shared by every mode on it. |

### The game's modes

| I want to... | Answer |
|---|---|
| Change a timer or an award | Usually. [Example 3](#3-make-ebirah-30-seconds-and-pay-more) |
| Change which shots it needs | A few modes, Godzilla only |
| Rewrite how it plays | No. Build your own instead. [Example 4](#4-rework-gigans-battle-into-a-three-phase-boss-fight) |
| Rename it | Yes, on the Text tab |
| Give it different music | Not for one mode. A swap on the Audio tab changes it everywhere. |
| Add a monster to Godzilla's battle selection | No, but you can take over a slot. [Example 1](#1-add-mothra-to-godzillas-battle-selection) |
| Keep them from starting while mine runs | Yes, and that's the usual: while yours runs, nothing of the game's starts or counts. [Example 5](#5-running-alongside-the-games-modes) |
| Make their screens wait for mine | No. [Why](#why-your-mode-always-gives-way) |
| Change progression (Godzilla's cities, tier 2 battles, King of the Monsters, wizard modes) | No |

### The machine

| I want to... | Answer |
|---|---|
| Hold the ball on Godzilla's magnet | Godzilla 1.16: up to 5 s when the Godzilla target is hit. [Limits](#why-your-mode-always-gives-way) |
| Hold a ball in the scoop | Godzilla 1.16: up to 10 s, then the game kicks it out as usual |
| Hold the Mechagodzilla magnet or the bridge | Godzilla Premium/LE 1.16: up to 5 s, as it starts or on a shot |
| Turn the shield targets toward the player | Godzilla Premium/LE 1.16: while the mode runs, then back where they were. Only while the game's modes can't start. Tested in the emulator so far |
| Play one of the game's own light shows as it starts or ends | Godzilla Premium/LE 1.16: ten shows by name (flashy, subdued, accent), a few seconds each; none as the ball drains |
| Move the building | Not yet |
| Fire a flipper, slingshot, pop bumper, kickback, lock, the trough or any other coil | No |
| Add a switch or a shot | No. A mode sees the shots the game reports. |
| Change settings, audits or high scores from a mode | No. Settings are on the Defaults tab. |
| Send scores to Insider Connected | No. Players can log in, but a card with modes sends no scores. |
| Write modes from a Mac, or straight to an SD card | No. Write an image file on Windows or Linux. |
| Make modes for Spike 1, Spike 3 or another maker | No. Spike 2 only. |

## Examples

### 1. "Add Mothra to Godzilla's battle selection"

**No.** The screen has seven slots: Ebirah, Titanosaurus, Gigan, Megalon, King Ghidorah, Megalon & Gigan, King Ghidorah & Gigan. Seven is baked into the game's code in more than a dozen places, and the artwork has exactly seven pictures.

**You can take over a slot instead.** Take Ebirah's, and:

- picking Ebirah starts your mode, 3 seconds later so the screen has closed. Ebirah's battle never runs.
- the ramps stay dark until your mode ends, as in a real battle.
- it counts toward the player's city, as the battle would.
- the slot can show your picture and name (no longer than EBIRAH). The old callout is silenced, or replaced with yours.

The catches:

- **Not in the Modes tab yet.** It takes `roster_slot 0` in a mode file or one call in C, and `roster_entry.py` for the picture and name.
- The slot still shows Ebirah's 0/4 and never says Completed. Anything unlocked by finishing Ebirah may stay locked.
- King of the Monsters still runs the real Ebirah.
- A drain ends your mode. The game would have resumed its battle.
- The operator menu, audits and champion still say Ebirah. Rename them on the Text tab.
- Godzilla only.

### 2. "A Mothra mode of my own"

*Three left ramps start it, it runs 45 seconds, orbits pay 2,000,000, it has a title card and its own music, and the orbit inserts blink.*

**Yes, all of it.** That's what the tab is for. Start from an example, the form, or blocks when the form runs out.

| | What a mode of yours can do |
|---|---|
| Start | a shot made N times, several shots in one ball (any order or in order), after another mode, a game event, a block |
| Score | any shot, with variables, conditions and timers for hurry-ups, combos, boss health or phases |
| End | its clock, chosen shots, a block, a drain if ticked; always at game over or the next player |
| Show | its own screen (a panel or your picture), full-screen clips, a countdown. On Godzilla, a HUD and clips behind the score. |
| Sound | its own sounds and callouts, and its own music in place of the game's |
| Light | its scoring shots' inserts (solid, blink, pulse, chase, a blink that speeds up) and light shows |
| Multiball | 2 to 6 balls, with a ball save |

It can't leave anything changed after it ends, or touch the hardware beyond lights and sound.

### 3. "Make Ebirah 30 seconds and pay more"

**Yes.** Pick Ebirah under the game's own modes in the list and type new numbers. That works for any timer or award the game stores as a single number. Rows the app can't change say why:

- **Computed in play**, like a base times a multiplier.
- **Shared** with other modes. Change it for one and it changes for all.
- **An operator setting.** It's also on the Defaults tab, and a machine that already stored a value keeps it until a factory reset.

Shots: on Godzilla you can change the tank attack's path, Ebirah's spinner counts, and let another shot "count as" one of the mode's. On other games the shots are fixed.

Screens: many of the game's modes share one start screen, so one can't get its own.

### 4. "Rework Gigan's battle into a three-phase boss fight"

**Not by editing Gigan.** Its logic is Stern's code. Instead:

1. Build the fight as your own mode. Blocks handle phases, health, timers, a HUD and music.
2. Set the game's modes to "cannot start" and tick the battles.
3. On Godzilla, take Gigan's slot ([Example 1](#1-add-mothra-to-godzillas-battle-selection)) so picking Gigan starts yours.
4. Rename what's left on the Text tab.

For C programmers: a C mode can replace what a shot does inside Ebirah's battle (Godzilla Pro 1.15 and Premium/LE 1.16), but the battle's own screen text still describes the old shots.

### 5. Running alongside the game's modes

Each mode picks one:

| Setting | While yours runs |
|---|---|
| cannot start (the usual) | Yours runs alone. None of the game's modes starts, and none of its features (on Godzilla: the Destruction Jackpot, the building locks, the bridge, the cities, the Powerup...) sees a shot, so nothing of theirs lights, locks, counts or awards, and no multiball of theirs can be lit. Tick a feature to keep it counting. |
| may start (this one carries on) | Both run. Your words step aside while theirs are on screen. |
| may start, and end this one | Yours starts only when none of theirs is running, and one of theirs starting ends yours. |

The catches:

- **A multiball of the game's is never stopped once it starts.** Balls may be sitting in a lock or on a magnet. With "cannot start" none can be lit or locked while yours runs, so it doesn't happen. If one was already on its way (a lock lit before yours began, a ball save), theirs starts and yours ends.
- **One screen, one voice.** A clip of yours and one of the game's on the same shot replace each other. Your full-screen clips start half a second late so the game's doesn't win.
- Some games can't tell which of their modes are running. There the option is greyed out, or your mode just gives way.
- On some games a held-off start uses up whatever lit it.

## Why your mode always gives way

Modes used to be able to hold the screen so the game's lesser displays waited. On a real Godzilla Premium that held up the Magna-Grab screen, and the game keeps the ball on the magnet until that screen plays. The magnet stayed on until the machine was switched off.

So a mode never makes the game wait for anything now. The Display priority setting is still there for older modes, but it doesn't hold anything back. Same thinking behind the other hard limits: multiballs always win, and a mode ends cleanly whenever the game moves on.

The few mechanisms a mode may hold (Godzilla's magnet and scoop, and on a Premium/LE the Mechagodzilla magnet and the bridge) give way the same way, and a mode can't raise their limits:

- One hold at a time per mechanism, up to 5 s (the scoop 10 s), then at least 3 s of rest, and no more than 6 a minute.
- At the game's own power: the same pulse and hold it uses itself.
- Never while the game is using it or the operator has switched it off. If the game wants it in the middle of a hold, yours lets go at once.
- Let go when the mode ends, the ball drains, the player tilts or the game ends.
- The scoop's kick-out is always the game's own.
- The shield platform turns at most once every 1.5 s and 12 times a minute, never while one of the game's own modes or multiballs runs. It stays toward the player only while the game's own Mechagodzilla Shield feature isn't counting, because that feature turns it back. It turns back where it was when the mode ends, the ball drains, the player tilts or the game ends.

All of it was tested on a real Godzilla Premium, except the shield, so far tested only in the emulator.

## Which games

Every build below has played modes in the emulator, and Godzilla Premium/LE 1.16 has run them on a real machine. Shots, scoring, timers, multiball and holding off the game's modes work on all of them; the columns are what differs.

| Game | Screen, clip, sounds | Countdown | Ball save | Lights | Also |
|---|---|---|---|---|---|
| Aerosmith 1.16 | ✓ | no | ✓ | shots | waits for multiballs only |
| Aerosmith LE 1.15 | ✓ | no | ✓ | all |  |
| Aerosmith LE 1.16 | ✓ | no | ✓ | shots | scoop, mechanisms, waits for multiballs only |
| Avengers: Infinity Quest LE 1.09 | ✓ | ✓ | ✓ | all |  |
| Avengers: Infinity Quest LE 1.10 | ✓ | ✓ | ✓ | no | scoop, mechanisms |
| Avengers: Infinity Quest Pro 1.10 | ✓ | ✓ | ✓ | no | mechanisms |
| Batman 66 1.13 | ✓ | ✓ | ✓ | all |  |
| Batman 66 1.14 | no | ✓ | not yet | no | waits for multiballs only |
| Deadpool LE 1.14 | ✓ | ✓ | not yet | all |  |
| Deadpool LE 1.16 | ✓ | ✓ | ✓ | shots | mechanisms |
| Deadpool Pro 1.16 | ✓ | ✓ | ✓ | shots | mechanisms |
| Dungeons & Dragons LE 1.00 | ✓ | ✓ | ✓ | all |  |
| Dungeons & Dragons LE 1.10 | ✓ | ✓ | ✓ | shots | scoop |
| Dungeons & Dragons Pro 1.10 | ✓ | ✓ | ✓ | shots | scoop |
| Elvira 1.13 | ✓ | no | not yet | shots |  |
| Foo Fighters LE 1.04 | ✓ | ✓ | ✓ | shots |  |
| Foo Fighters Pro 1.04 | ✓ | ✓ | ✓ | no |  |
| Godzilla Premium/LE 1.16 | ✓ | ✓ | ✓ | shots | HUD, buttons, magnet, scoop, mechanisms, shield |
| Godzilla Pro 1.15 | ✓ | ✓ | ✓ | shots | HUD, buttons, magnet, scoop |
| Godzilla Pro 1.16 | ✓ | ✓ | ✓ | shots | HUD, buttons, magnet, scoop |
| Guardians of the Galaxy 1.15 | ✓ | ✓ | ✓ | shots | scoop, waits for multiballs only |
| Guardians of the Galaxy LE 1.14 | ✓ | ✓ | ✓ | all |  |
| Guardians of the Galaxy LE 1.15 | ✓ | ✓ | ✓ | shots | scoop, mechanisms, waits for multiballs only |
| Iron Maiden LE 1.16 | ✓ | ✓ | not yet | all |  |
| Iron Maiden LE 1.18 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| Iron Maiden Pro 1.18 | ✓ | ✓ | ✓ | shots | mechanisms |
| James Bond 007 LE 1.06 | ✓ | ✓ | ✓ | shots | magnet, mechanisms |
| James Bond 007 Pro 1.06 | ✓ | ✓ | ✓ | shots | mechanisms, waits for multiballs only |
| James Bond 60th LE 1.11 | ✓ | ✓ | ✓ | shots |  |
| Jaws LE 1.02 | ✓ | ✓ | ✓ | shots | mechanisms |
| John Wick LE 1.01 | ✓ | no | ✓ | all |  |
| John Wick LE 1.02 | ✓ | no | ✓ | no | scoop |
| John Wick Pro 1.02 | ✓ | no | ✓ | no | scoop |
| Jurassic Park LE 1.16 | ✓ | ✓ | ✓ | shots | magnet, mechanisms |
| Jurassic Park Pin 1.05 | ✓ | ✓ | ✓ | shots |  |
| Jurassic Park Pro 1.16 | ✓ | ✓ | ✓ | shots | mechanisms |
| King Kong LE 0.97 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| King Kong Pro 0.97 | ✓ | ✓ | ✓ | no | mechanisms |
| Led Zeppelin LE 1.22 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| Led Zeppelin Pro 1.22 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| Metallica Remastered 1.03 | ✓ | ✓ | ✓ | all |  |
| Metallica Remastered 1.04 | ✓ | ✓ | ✓ | shots |  |
| Rush LE 1.18 | ✓ | ✓ | ✓ | all |  |
| Rush LE 1.19 | no | ✓ | ✓ | no | scoop |
| Rush Pro 1.19 | no | ✓ | ✓ | no | scoop |
| Star Wars ELG 1.10 | ✓ | ✓ | ✓ | shots | mechanisms |
| Star Wars LE 1.30 | ✓ | ✓ | ✓ | all |  |
| Star Wars LE 1.31 | no | ✓ | ✓ | shots | scoop, mechanisms |
| Star Wars Pro 1.31 | no | ✓ | ✓ | shots | scoop, mechanisms |
| Stranger Things 1.13 | no | ✓ | ✓ | shots | scoop, mechanisms, waits for multiballs only |
| Stranger Things LE 1.12 | ✓ | ✓ | ✓ | all |  |
| Stranger Things LE 1.13 | no | ✓ | ✓ | shots | scoop, mechanisms, waits for multiballs only |
| Sword of Rage LE 1.18 | ✓ | ✓ | ✓ | all |  |
| Sword of Rage LE 1.19 | no | ✓ | ✓ | shots | scoop, mechanisms |
| Sword of Rage Pro 1.19 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| TMNT LE 1.59 | ✓ | ✓ | not yet | shots |  |
| TMNT Pro 1.58 | no | no | ✓ | no | never waits, no events |
| TMNT Pro 1.59 | ✓ | ✓ | ✓ | shots |  |
| The Beatles 1.29 | ✓ | ✓ | ✓ | shots | waits for multiballs only |
| The Mandalorian LE 1.44 | ✓ | ✓ | ✓ | all |  |
| The Mandalorian LE 1.45 | ✓ | ✓ | ✓ | no | scoop, mechanisms |
| The Mandalorian Pro 1.45 | ✓ | ✓ | ✓ | no | scoop, mechanisms |
| The Munsters LE 1.28 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| The Munsters Pro 1.28 | ✓ | ✓ | ✓ | no | scoop, mechanisms |
| Uncanny X-Men LE 0.98 | ✓ | ✓ | ✓ | shots |  |
| Uncanny X-Men Pro 0.98 | ✓ | ✓ | ✓ | shots | waits for multiballs only |
| Venom LE 1.07 | ✓ | ✓ | ✓ | shots | scoop, mechanisms |
| Venom Pro 1.07 | no | ✓ | ✓ | shots | scoop |

- **Countdown no:** the game's voice never says a number on its own.
- **Ball save not yet:** found in the game, not yet seen working.
- **Lights:** *shots* lights just the scoring shots' inserts; *all* holds every insert in the mode's colour.
- **HUD:** counters, a timer and a gauge at the screen's edges, like Godzilla's own battles.
- **Buttons:** the flipper and Action buttons count as shots.
- **Magnet, scoop, mechanisms:** what a mode may hold for a moment: the magnet, a ball in the scoop, the Mechagodzilla magnet and the bridge.
- **Shield:** a mode may turn the shield targets toward the player while it runs.
- **Never waits:** a mode can't be set to wait for the game's modes.
- **Not listed?** Pick the card anyway. The app works out its hooks; press Check this game (about two minutes) before trusting them.

## Sizes

| | Limit |
|---|---|
| Form modes | 64 per project (blocks and C modes not counted) |
| Running at once | 1 |
| Clock | up to 600 seconds (0 = no clock) |
| Blocks mode | 48 scripts, 400 blocks, nested at most 10 deep |
| Variables | 24 per mode, names up to 24 characters |
| Timers | 8 per mode, up to 600 seconds each |
| Numbers | whole numbers |
| Mode name | 40 characters |
| Screen words, log lines | 60 characters |
| HUD (Godzilla) | title, line or award 40 characters; 3 counters with 16-character labels; badge 12; gauge up to 12 pips |
| Light show | 10 steps |
| Multiball | 2 to 6 balls, ball save up to 60 seconds |
| Clips | form mode: one at the start, one at the end. Blocks or C: 12. Up to 30 seconds each, any common video format, silent. |
| Pictures | up to 1360 x 768 (bigger is scaled down) |
| Sounds | form mode: start, scoring shot, end and music. Blocks or C: 16. WAV only. |
| Form end sound | one per card, from the first mode that has one |
| Music | loops after 150 seconds |

## Before you flash a real machine

- It's a preview. Treat a card with modes as a test card and keep your stock image.
- A card with modes never sends scores to Insider Connected.
- Modes are built for one game version. After a Stern update, Write the card again: until then the modes don't run and the game plays stock.

## Asking for more

Hit a wall that isn't here, or think one shouldn't be? Post in the preview channel with the game and version, what you wanted, and what happened. Some of these noes are "not yet" (the battle slot in the tab, for one). The ones that come from Stern's compiled code are much harder to move.
