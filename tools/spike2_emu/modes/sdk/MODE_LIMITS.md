# What a mode can and can't do

The Modes tab lets you add modes to a Stern Spike 2 game and change some of the game's own. This page says where that stops, with the things people ask for most as worked examples. If what you want isn't here, find its nearest neighbour in the table below: the reason it's a yes or a no usually carries over.

## The one idea behind every limit

A Stern game's own modes are not files. They are compiled code inside the game program, and the app does not rewrite that code. Your mode is a small program of its own that the card loads next to the game. It runs inside the game, so it scores through the game's own scoring and plays through the game's own display, speakers and lights, but it reaches the game only through a fixed set of hooks the app knows for that game and version.

So there are three zones, and almost every question lands in one of them:

1. **Your own modes: wide open.** Within the sizes at the end of this page, a mode of yours starts on what you choose, scores what you choose, and brings its own screen, clips, sounds, music and lights.
2. **The game's own modes: numbers yes, structure no.** A timer or an award the game keeps as a single number can be changed. What a mode is, when it starts, how it ends and what it leads to are code, and stay as Stern wrote them.
3. **The rest of the game: hands off.** Its progression, its operator menu, its coils and magnets, its high score table and its link to Insider Connected are not something a mode changes.

## Quick answers

| I want to... | Can I? | What you can do instead |
|---|---|---|
| Add an eighth monster to Godzilla's BATTLE SELECTION screen | **No** | Take over one of the seven slots, so picking that monster starts your mode instead of the game's battle. [Example 1](#example-1-a-new-monster-in-godzillas-battle-selection) |
| Make a brand new mode with its own name, screen, clip, music and callouts | **Yes** | [Example 2](#example-2-a-mode-of-your-own) |
| Start my mode from shots, a timer, or something the game does (a ball starts, the skill shot, a multiball starts...) | **Yes** | The events on offer are the ones this game reports; the tab lists them. |
| Start my mode from a flipper or Action button | **On Godzilla** | Godzilla reports its buttons as shots. Jaws and Uncanny X-Men report one button each; other games report none. |
| Start my mode after another of my modes | **Yes** | "Only after" holds a mode until another one has run this ball or this game. |
| Start my mode when the player beats one of the game's battles | **No** | No game reports "battle won". Start it from your own shots, or after another mode of yours. |
| Change a timer or an award in one of the game's own modes | **Usually** | Where the game keeps it as one number. [Example 3](#example-3-changing-the-games-own-modes) |
| Change which shots one of the game's own modes needs | **Godzilla only, a few modes** | [Example 3](#example-3-changing-the-games-own-modes) |
| Rewrite one of the game's own modes, start to finish | **No** | Build your own mode that plays the way you want, and keep the game's out of the way while it runs. [Example 4](#example-4-rework-a-stock-mode-to-my-hearts-content) |
| Rename one of the game's modes, or a monster | **Yes** | On the Text tab, not the Modes tab. Its Max column says how long the new text can be. |
| Give one of the game's modes different music | **Not for one mode** | Replacing a sound on the Audio tab changes it everywhere the game plays it. Your own modes can have any music you like. |
| Add new sounds to the game | **Only for your modes** | Each sound of yours rides on a sound the game has but never plays. The card has a fixed number of those (21 on Godzilla), shared by every mode on it. |
| Fire a coil, a magnet, a kickback, a ball lock or a diverter | **No** | A mode has no way to drive the machine's hardware. Its own multiball serves balls through the game's own call. |
| Add a switch or a shot the game doesn't already have | **No** | A mode sees the shots the game reports. |
| Keep the game's modes from starting while mine runs | **Yes, except multiballs** | [Example 5](#example-5-sharing-the-game-with-its-own-modes) |
| Run my mode at the same time as one of the game's battles | **Yes** | Your words step aside so the two never print over each other. [Example 5](#example-5-sharing-the-game-with-its-own-modes) |
| Run two of my own modes at the same time | **No** | One of yours runs at a time. A start while another runs waits for it, or does nothing, depending on the mode. |
| Make the game's screens wait until my mode is done | **No** | Removed on purpose. [Why](#why-your-mode-always-gives-way) |
| Change how the game progresses (Godzilla's cities, the second tier of battles, King of the Monsters, what qualifies a wizard mode) | **No** | That's the game's code. A mode in a battle slot counts toward its city (Example 1), and your own modes can build their own progression with shared variables. |
| Change an operator setting, an audit or the high score table from a mode | **No** | Settings are on the Defaults tab. A mode only adds points to the player's score. |
| Take points away from a player | **Form modes only** | A minus number under Points per shot. A Score points block only adds. |
| Send scores from a card with modes to Insider Connected | **No** | Players still log in, but the machine sends no game, score, high score or achievement report. |
| Put modes on a card from a Mac, or write straight to the SD card | **No** | Write an image file on Windows or Linux, then flash it. |
| Make modes for a Spike 1, Spike 3 or non-Stern game | **No** | Stern Spike 2 only. |

## Example 1: a new monster in Godzilla's battle selection

**The ask:** "Add Mothra to the battle selection, next to Ebirah and the rest."

**The answer: the list can't grow, but a place in it can be taken.**

Godzilla's BATTLE SELECTION screen has seven slots: Ebirah, Titanosaurus, Gigan, Megalon, King Ghidorah, Megalon & Gigan, and King Ghidorah & Gigan. Seven is not a setting. It is built into the game program in more than a dozen places: the list of battles is exactly seven entries long, the screen and the battle rule check the slot number against 6 and 7 throughout, and the screen's artwork has exactly seven pictures, tiles and names. An eighth monster would mean rewriting all of that code, so the app doesn't offer it.

What does work is taking over a slot. Say you take Ebirah's:

- Picking Ebirah on the screen starts **your** mode, three seconds after the pick so your start screen is seen once the selection screen has closed. The game's Ebirah battle never starts.
- While your mode runs, the ramps stay dark and no other battle can be lit, just as during one of the game's battles. When your mode ends, the ramps light again.
- It counts toward completing the player's current city, as the game's battle would.
- The slot's picture and name can be replaced with yours, so the screen shows MOTHRA. The new name can't be longer than the one it replaces (EBIRAH has six letters). The old monster's spoken name is silenced, and you can give the slot a callout of your own.

Where it stops:

- **The Modes tab has no control for this yet.** Taking a slot is one line in a mode file (`roster_slot 0`) or one call in a mode written in C, and the picture and name are swapped by a separate tool (`roster_entry.py`). If you want it in the tab, say so in the preview channel.
- The slot keeps Ebirah's progress text (0/4) and never shows "Completed", because the game reads both from the Ebirah battle, which never runs.
- Because Ebirah's battle never completes, anything the game unlocks by completing it may stay locked. Once every other open slot is completed, the screen picks your slot by itself every time.
- King of the Monsters starts the first four battles itself, without the screen, so inside King of the Monsters it is still Ebirah.
- When the ball drains during one of its battles, the game resumes that battle at the next lit scoop. Your mode ends on the drain instead, and the next lit scoop opens the selection screen again.
- The operator menu, the audits and the champion entry still say Ebirah. Those are program text: rename them on the Text tab.
- Godzilla only, run in the emulator on Pro 1.15 and Premium/LE 1.16. No other game has a selection screen the app knows how to take over.

## Example 2: a mode of your own

**The ask:** "A Mothra mode: it starts when I make the left ramp three times, runs for 45 seconds, every orbit pays 2,000,000, it has a title card and its own music, and the orbit inserts blink while it runs."

**The answer: yes, all of it.** This is what the tab is for. Start from an example (New, From an example; KAIJU RUSH is the one that has run on a real machine), from a blank form, or build it from blocks when you need more than the form offers. A mode of your own can:

- **start** on a shot made a number of times, on several shots in one ball (in any order or in order), after another of your modes has run, on one of the game's events, or from a block of your own (a timer, a variable, a condition);
- **score** any shot the game reports, using numbers, variables, conditions and timers, so it can be a hurry-up, a combo chain, a boss with health, or a mode in phases;
- **end** on its clock, on a pick of shots, on a block, on a drain if you tick it, and always when the game ends or the next player comes up;
- **show** a screen of its own (a panel in your colours, or your own picture), its own clips full screen, and a countdown. On Godzilla it can also have a HUD at the screen's edges and play clips behind the score display, like the game's own battles;
- **play** sounds and callouts of its own, and music of its own in place of the game's while it runs;
- **light** the inserts of its scoring shots (solid, blinking, pulsing, chasing, or a blink that speeds up as time runs out) and run light shows;
- **start a multiball** of 2 to 6 balls, with its own ball save.

What it can't do is anything that outlasts its own run: the game's rules are the same after your mode ends as before it started. And beyond lights and sound, it can't touch the machine's hardware.

## Example 3: changing the game's own modes

**The ask:** "Make Ebirah's battle 30 seconds instead of 60, and give it a bigger start award."

**The answer: yes.** The game's own modes are listed in the Modes tab under yours. Each shows the timers, awards and shots the app can change on this game. A timer or award qualifies when the game keeps it as one number: the app changes that number on the card and nothing else. A timer that is really an operator setting is the same number the Defaults tab shows.

Where it stops, and the tab says which applies on each row:

- **Worked out as the game plays.** Many awards are computed during play (a base times a multiplier, a value that grows), not stored as one number. Those rows say the game works it out as it plays, so it can't be changed here.
- **Shared.** Some numbers are one value several modes use. Changing it for one changes it for all of them.
- **Screens.** Several of the game's modes share one start screen, so the app can't give one of them a different screen.
- **Which shots a mode needs.** On Godzilla, a few modes can have their shots changed: the tank attack's path, Ebirah's spinner counts, and "counts as" rows that let another shot count as one of the mode's own. On every other game, the shots of the game's modes are fixed.
- **Operator settings the machine already has.** A machine keeps the settings it has stored. A new default for a timer that is an operator setting shows on a machine still on the old default, or after a factory reset.

## Example 4: "rework a stock mode to my heart's content"

**The ask:** "Make Gigan's battle a three-phase fight with a boss health bar, new shots and a final blow on the scoop."

**The answer: not by editing Gigan's battle.** Beyond its numbers, one of the game's modes is code, and the app doesn't rewrite the game's code. This gets you most of the way:

1. **Build the fight as your own mode.** Blocks can do phases, health, timers, its own screen, a HUD, music and calls. Several of the example modes are exactly this.
2. **Keep the game's battle out of the way** while yours runs: set "While it runs, the game's modes" to "cannot start", and tick the battles.
3. **On Godzilla, take the battle's slot** (Example 1), so picking Gigan starts your fight. Not in the tab yet.
4. **Rename** what's left on the Text tab.

There is one narrower route for programmers: a mode written in C can replace what a shot does inside one of the game's battles, while the battle's start, clock, screens and ending stay the game's. Today only Ebirah has a template for it, on Godzilla Pro 1.15 and Premium/LE 1.16, and the battle's own words on the screen still describe the old shots.

## Example 5: sharing the game with its own modes

Each mode chooses what happens to the game's modes while it runs:

- **may start (this one carries on).** Both run. Your words step aside while one of the game's modes shows its own (Stern never shows two modes' words at once), and your screen hides while one of the game's displays has the screen.
- **may start, and end this one.** Your mode starts only when none of the game's modes runs, and one of theirs starting ends yours.
- **cannot start.** As above, and the game's modes you tick are held off while yours runs. A shot that would have started one does what it does when that mode isn't lit.

Limits:

- **The game's multiballs are never held off.** Balls may be sitting in a lock or on a magnet, and holding the multiball back would leave them there. The game's multiball starts and your mode ends. Your own Multiball block doesn't end your mode.
- On some games the app can't tell which of the game's modes are running, or can't hold them off; there the option is greyed out, or the mode gives way instead.
- On some games, a start that is held off may use up whatever lit it.
- **There is one video screen and one voice.** If your clip starts on the same shot as one of the game's clips, one replaces the other. A full-screen clip of yours starts half a second after it's asked for, so the game's own clip for that shot doesn't take its place.

## Why your mode always gives way

Early versions let a mode hold the screen, so the game's lesser displays waited for it. On a real Godzilla Premium that held back the Magna-Grab's screen, and the game keeps the ball on the magnet until that screen has played: the magnet stayed on until the machine was switched off. Any rule of the game's that waits on a display could stall the same way. So a mode now never makes the game wait for anything. The Display priority setting is kept for modes made before the change, but it no longer holds the game's displays back.

The same thinking is behind the other hard limits: no coils or magnets, the game's multiballs always win, and a mode ends cleanly whenever the game moves on.

## Which games

The app has hooks for 37 Spike 2 game builds, and every one of them has played modes in the app's emulator. Godzilla Premium/LE 1.16 is the one that has run modes on a real machine. The "?" on the Modes tab lists the builds, and a build the app hasn't seen before gets its hooks worked out on the spot: press Check this game (about two minutes in the emulator) before you rely on it.

Everything in Example 2 works on every build except:

| | Builds |
|---|---|
| **Godzilla extras:** buttons as shots, the HUD at the screen's edges, clips behind the score display, the battle slots (Example 1), changing shots of the game's own modes, and the examples written in C | Godzilla only |
| **Lighting just the scoring shots' inserts.** Elsewhere a mode's lights hold every insert in its colour. | Godzilla, The Beatles 1.29, Jaws LE 1.02, King Kong LE 0.97, Metallica Remastered 1.04 |
| **No countdown** (the game's voice never says a number on its own) | Aerosmith LE 1.15, Elvira 1.13, John Wick LE 1.01 |
| **No ball save from the form yet** (found, not yet seen working in the emulator) | Deadpool LE 1.14, Elvira 1.13, Godzilla Premium/LE 1.16, Iron Maiden LE 1.16, TMNT LE 1.59, Venom LE 1.07 |
| **Waits only for the game's multiballs** (one of its songs is always running) | The Beatles 1.29 |
| **Shots, scoring, multiball, ball save and holding off the game's modes only:** no screen, clip, own sound, countdown, light show or events yet. TMNT Pro 1.59 has all of them. | TMNT Pro 1.58 |

## Sizes

| | Limit |
|---|---|
| Modes from the form | 64 per project (blocks and C modes are counted apart) |
| Your modes running at once | 1 |
| A mode's clock | up to 600 seconds (0 = no clock) |
| A blocks mode | 48 scripts, 400 blocks, nested at most 10 deep |
| Variables | 24 per mode, names up to 24 characters |
| Timers | 8 per mode, up to 600 seconds each |
| Numbers | whole numbers only |
| Mode name | 40 characters |
| Words on its screen, a log line | 60 characters |
| HUD (Godzilla) | title, line or award 40 characters; 3 counters, labels 16; badge 12; gauge up to 12 pips |
| Light show | up to 10 steps |
| Multiball | 2 to 6 balls, ball save up to 60 seconds |
| Clips | a form mode: one at its start, one at its end. A blocks or C mode: 12. Each up to 30 seconds, any common video file, converted to 30 fps with no sound |
| Pictures | up to 1360 x 768 (larger is scaled down) |
| Sounds | a form mode: start, scoring shot, end and music. A blocks or C mode: 16. WAV files; music at least half a second |
| A form mode's end sound | one per card: the first mode that has one |
| Music | past 150 seconds it loops |

## Before you put it on a real machine

- The mode maker is a preview. Treat any card with modes on it as a test card, and keep your stock image.
- A card with modes on it never reports scores to Insider Connected.
- Every mode on one card is for that card's game and version. Another build needs its own Write, and so does a Stern code update: until the card is written again for the new version, its modes don't run and the game plays as stock.

## Asking for more

If you hit a wall that isn't on this page, or one that is and you think it shouldn't be, post in the preview channel with the game and version, what you wanted the mode to do, and what the tab did instead. Some of the noes above are "not yet" (the battle slot isn't in the tab, for one). The ones that come from the game's compiled code are much harder to move.
