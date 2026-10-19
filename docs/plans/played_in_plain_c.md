# Played in for the plain-C titles and Deadpool (PAD-634)

## What was missing

PAD-624 gave the Video tab's Played in column to every C++ Spike 2 title whose clips its mode
classes name. Two kinds of title still read no mode and showed "Played in: not shown for this
game":

- the plain-C titles (Aerosmith, Batman 66, Beatles, Elvira 3, Guardians, James Bond 1.06 and
  60th, Jurassic Park the Pinball, Metallica, Star Wars ELG, Stranger Things): no class per mode;
- Deadpool: its battle and multiball clips are played by display-effect code in files of their
  own (`def_juggernaut` ...), which no mode class's code is in, so every clip read "Other parts of
  the game".

## How it is read now (`plugins/stern/clip_files.py`)

When the class-by-class reading names no mode, `clip_modes.analyse` reads the program source
file by source file:

1. **Files.** Nearly every source file ends in a static initialiser (`.init_array`: 445 to 661 per
   plain-C program), placed at the end of its code. The code between two initialisers is one file.
   A clip named in a file (a function or its initialiser) or in a table only that file's code
   loads is the file's.
2. **Plain C: whose file it is.** A file is a mode's when the records written in it are that
   mode's alone and outnumber the file's records of no mode. Records: the audits counted
   (`audit_add(id, 1)`, `stock_scan_c`'s audit witness) and the game flags set or cleared. The flag
   writers are the callees handed 20+ different flag ids and nothing else that `orr` / `bic` one
   bit of `[base + (id >> 3)]`: one set and one clear on every plain-C card read (a test writes no
   bit; Stranger Things' 0x4296cc, also handed flag-sized ids, stores into a table and is not one).
   A flag only tested is no record: any code may ask whether a mode runs. The modes are every
   `..._STARTED` audit's and every `FG_<mode>_ACTIVE` flag's (Aerosmith's songs have only the
   flag), named as the Modes tab names them. The "outnumber" rule keeps a feature's file out: the
   pop bumper file of Stranger Things sets Super Pop Bumpers' flag twice but writes four records of
   pop hits and dart levels, and its dart backgrounds showed in normal play on the emulator.
3. **Deadpool: display effects.** The display-effect table is the longest run of
   `{function, priority}` entries whose start the code loads (173 on Deadpool LE 1.16). A mode
   class answers its intro and total effects from fixed virtual slots, read off the framework
   itself: the slots whose answer the code moves into `r1` for one effect function (42, 43 and 44
   on Deadpool; 56 to 58 on Godzilla). An effect a mode's own slot returns is in a file, and that
   file's clips are the mode's (`cbattle_juggernaut` slot 43 returns 68: `def_juggernaut`).
4. **Audit ids.** `stock_scan_c.audit_ids` now takes the descriptor record that maps the most audit
   names, not the first of the count (as PAD-363's `cstart_lib` already did): Batman 66 and
   Metallica have an 8-byte record ahead of theirs, so their audit ids were read by name order and
   each mode's start was read in another mode's function (Metallica's Enter Sandman file counted
   "Battery Mode" audits). This also fixes their Modes tab readings (`stock_reader.READER_REV` 3).

Titles the class reading already reads are read exactly as before.

## Census: every Spike 2 card on D: (90), main against the branch

`clip_modes.read_card` with the rows Extract writes (PAD-624's rows). On every C++ card the class
reading reads, the counts are the same and no pair main lists is lost. The cards that change:

| Card | Clips | Modes | Clips with Played in | Not played |
|---|---:|---|---|---|
| aerosmith-1_16_0 | 163 | 0 -> 12 | 0 -> 45 | 0 -> 23 |
| aerosmith_le-1_15_0 | 163 | 0 -> 12 | 0 -> 44 | 0 -> 23 |
| aerosmith_le-1_16_0 | 163 | 0 -> 13 | 0 -> 46 | 0 -> 23 |
| batman-1_13_0 | 6331 | 0 -> 31 | 0 -> 2073 | 0 -> 6 |
| batman-1_14_0 | 6331 | 0 -> 31 | 0 -> 2073 | 0 -> 7 |
| beatles-1_29_0 (all three) | 354 | 0 -> 4 | 0 -> 131 | 0 -> 17 |
| deadpool_le-1_14_0 | 99 | 0 -> 10 | 0 -> 44 | 8 |
| deadpool_le-1_16_0 / pro-1_16_0 | 99 | 0 -> 10 | 0 -> 44 | 9 |
| elvira3-1_11_0 / 1_13_0 | 5416 | 0 -> 29 | 0 -> 2683 | 0 -> 704 |
| guardians (all three) | 200 | 0 -> 12 | 0 -> 35 | 0 -> 52 |
| james_bond_60th_le (both) | 19 | 0 -> 3 | 0 -> 1 | 0 -> 2 |
| james_bond_le-1_06_0 / pro | 1483 | 0 -> 40 | 0 -> 397 | 0 -> 759 / 760 |
| jurassic_park_the_pin-1_05_0 | 165 | 0 -> 3 | 0 -> 13 | 41 |
| metallica_spike-1_03_0 / 1_04_0 | 287 | 0 -> 17 | 0 -> 96 | 0 -> 49 |
| star_wars_elg-1_10_0_spike2 | 932 | 0 -> 2 | 0 -> 6 | 0 -> 114 |
| stranger_things-1_13_0 | 568 | 0 -> 36 | 0 -> 227 | 0 -> 161 |
| stranger_things_le-1_12_0 | 715 | 0 -> 32 | 0 -> 314 | 0 -> 147 |
| stranger_things_le-1_13_0 | 715 | 0 -> 36 | 0 -> 325 | 0 -> 148 |

"Not played" now shows on the plain-C titles too: a bank clip whose name is nowhere in the program,
in a bank a third of whose clips the program names (PAD-444's rule, unchanged). The names are
genuinely absent (no string, no format string with their stem: Bond's `THNDRBLL_ParaTrooper...`
are not in the program at all).

## Proof on the emulator

Hidden, muted rigs with `sound_census.so` logging every clip handed a surface (V lines, and on
Deadpool its clip player `census_clip_r0`, 0x1455e4), every audit counted (A) and every game flag
set or cleared (F). `correlate.py` checks each showing against the reading: a (clip, mode) pair is
confirmed when the clip showed while that mode's `FG_..._ACTIVE` flag was set or just after its
start audit, contradicted when every showing was outside it.

| Title | Showings of a clip with a mode | Pairs confirmed | Contradicted |
|---|---:|---:|---:|
| Stranger Things LE 1.13 (switch sweeps + drains, two games) | 75 | 26 | 0 |
| Beatles 1.29 (switch sweeps + drains, two games) | 67 | 40 | 0 |
| Deadpool LE 1.16 (modes started by their START virtual, `sc.call`) | 47 | 11 | 0 |

The pairs neither confirmed nor contradicted are clips the program also names outside any mode
(Stranger Things' snow background, its title), shown in normal play: the reading lists them as
"Other parts of the game" too.

Deadpool: Quest Megalodon played `MegQuest_Intro_Long` the moment it started, then its attack and
idle clips on its shots; Mr. Sinister Rex played four `MegakrakolodonusAward*_AVI` clips on shots
and `Megakrakolodonus_TotalScreen_AVI` at its end (its start audit is counted by the game's own
rule, not by START, so the correlator printed those as NO; nothing else that ran names them, and
the code that played them, 0x48764 to 0x48ca8, is the class's); Ninja Multiball played its super
jackpot and total. The battles started and were won on the rig (audits 206, 207 x7, 209) but the
sweep never made their final shot, so the uppercut and total effects (70, 71) did not run; the
battle's own final-shot handler (0xed274, the one that counts
`AUD_JUGGERNAUT_BATTLE_FINAL_SHOT_AWARDS`) sets effect 71, `def_juggernaut`'s total, which is what
the reading names Battle Juggernaut.

The Stranger Things sweep is also where the "outnumber" rule came from: its dart backgrounds
showed during Demogorgon Multiball with Super Pop Bumpers not running.

Files: `work/artifacts/PAD-634/emulator/` (census logs, `correlate.py` and its output, ports, rig
scripts).
