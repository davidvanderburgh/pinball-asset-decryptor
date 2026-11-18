# PAD-1407 - a whole new game's own attract and title (Stern Spike 2)

Row 17 of the PAD-1398 gap analysis (docs/plans/pad1398_xmen20_gap_analysis.md): the attract editor (PAD-782) only
put items BETWEEN Stern's attract pages. A whole new game built on Stern's board and program (20SidedDies' Uncanny
X-Men 2.0) needs its own title and attract ("UNCANNY X-MEN 2.0 - PRESS START") in place of Stern's, its own name
on the multi-boot Edition, and its own high score names. X-Men LE/Pro 0.98 is the proof target.

## What was built

| Part | Where |
|---|---|
| `hide <entry>` (and `census on`) in attract.cfg: the game's page at that entry is not shown | pad_mode_runtime.c "the game's own screens taken off" |
| One wrapper per table entry (AIT_WRAP 192, the largest port table is 183): a hidden entry's test says no, the others ask the game's own test (0: always). An entry carrying items shows them and not the game's page. Each screen is said the first time it comes up (`attract items: the game's screen N (entry k) comes up`) | `ait_entry_test`, `attract_hide_arm` |
| A whole round of every test saying no would spin the sequencer with no frame's sleep: after one, a hidden screen is let through. Every screen hidden and no item: nothing is hidden | `ait_noes`, `attract_hide_arm` |
| The record's `hidden` list; `cfg_text(..., hidden)`; a build of hidden screens alone writes attract.cfg; all hidden and no item is refused | attract_items.py |
| Mod packs, Move Your Mods, the Write log carry a record of hidden screens alone | modpack.py, mod_transfer.py, engine.py |
| Attract page: Hide/Show on every screen run; **Replace the game's attract** (all but the high score and champion screens off, a title card of the owner's first when there is none); a pointer to the Text page for the high score words | webui/tabs/attract.py, attract.js, attract.css |
| Screens named by what they show, so Replace keeps the right ones (below) | attract_items.`name_from_scenes`, `_score_runs`, `kept_on_replace` |
| Guide: "Attract screens", and a whole new game as one of the Editions | docs/guide/using-the-app.md |

The title text is the owner's text card (or a clip/photo); the high score WORDS (GRAND CHAMPION, HIGH SCORE #1) are
strings of the game program, which the Text page already renames (PAD-470 era program text). The edition's name is
PAD-495's **Name the editions...**. Neither needed new code; the page and the guide point at them.

## Which screens are the high scores (emulator census, 2026-11-18)

X-Men LE 0.98's port names no champion page, so every screen read "Game screen N". A census run (`census on`, rig
job C:/tmp/PAD-1407/census.sh, a shot every 4 game seconds) showed: entry 3 GAME OVER, 21 REPLAY AT, 22 the X-Men
logo, 23-41 GRAND CHAMPION, HIGH SCORE #1-#4 and the champions (THE FUTURE, SAVE THE CITY, SENTINEL MULTIBALL...).
Their pages are generated one per category: evenly spaced functions (0x74 apart) with evenly spaced tests.

- `_score_runs`: a run of 4+ entries whose pages (and tests) step evenly, and stubs just beside a run of small
  steps (Star Wars LE 1.31 entries 14-18 beside 19-34), is named "High score / champion page" where the program's
  name says nothing (Game screen N, or a name 3+ pages share).
- `name_from_scenes`: a vaguely named page is named by the words of the scene only it loads, read off the card
  (8-byte length + capitals): Aerosmith LE 1.16's six "Layout 4 players" pages become Champion / High Scores,
  Replay At, Presents...; Guardians the same.
- `kept_on_replace`: a name with high score / highscore / champ / HSTD.

Library (newest builds; C:/tmp/PAD-1407/names_all.py): Replace keeps 19 of 49 on X-Men LE/Pro, 43 of 77 on Star
Wars, 3-4 on Aerosmith/Guardians (their HIGH SCORES list and champions), 30-56 on Godzilla, Jaws, KK, Mando, TMNT,
Munsters.... A screen kept that is not a high score (King Kong's and Jaws' credit overlays share the grand champion
scene) is the safe direction. Batman 1.14, Beatles 1.29 and Iron Maiden 1.18 keep none: the page says so through the
Replace says so and the owner uses Show on the rows; see "Census" below.

## Census (12 builds, every entry's test wrapped, `census on`; C:/tmp/PAD-1407/out/census.*/sheet2.png)

All 12 ran with every test wrapped, segv 0 (seven first runs died while a 16 GB card copy loaded the disks:
`unshare: sigprocmask unblock failed`, no runtime fault; re-run clean). What Replace keeps, against the glass:
X-Men LE: exactly GRAND CHAMPION, HIGH SCORE #1-4, the champions. Foo Fighters LE: the HSTD board and every
champion (one machine clip kept too). Aerosmith / Guardians LE: the HIGH SCORES list and the champions. Star Wars LE:
GRAND CHAMPION to the last champion, both times round. Batman 66, Iron Maiden, Metallica, Munsters and Rush are
refused by the page already (their clip bank, PAD-782), so Replace is never offered there. The Beatles runs its whole
attract from one long page (entry 4): no high score screen of its own to keep, so Replace says so and takes all off.

## Proof

- X-Men LE 0.98 card built by the app's own Write (C:/tmp/PAD-1407/card1407.py -> D:/tmp/PAD-1407/xm1407.raw:
  the Attract tab's Replace run on a scratch project, the title card UNCANNY X-MEN 2.0 / PRESS START): attract.cfg
  with 30 hide lines and the item, the clip in the bank, the runtime on p2. Booted on the rig with its own runtime
  (rig job C:/tmp/PAD-1407/cardjob2.sh, PAD_CARD_MODES=1): the title card on the glass, then entries 23-41 (the
  19 kept screens) and nothing else, then the title card again at the next cycle (826 s); Start began a game;
  segv 0. Shots: work/artifacts/PAD-1407 attract_cycle pair.
- tests/test_pad1407_attract_replace.py (13, also under WSL), tests/test_pad782_attract_items.py,
  tests/test_pad1328_spike3_attract.py, tests/test_stern_mode_runtime.py.
