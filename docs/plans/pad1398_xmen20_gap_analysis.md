# Why Uncanny X-Men 2.0 isn't being done in PAD: a gap analysis (PAD-1398)

David asked why 20SidedDies' "Uncanny X-Men 2.0" can't be done in PAD. The source is the whole Pinside thread
(`pinside.com/pinball/forum/topic/uncanny-xmen-20`, 6 pages, 291 posts, read 2026-11-17), especially post #256
(9391576). Post numbers below are the thread's.

## The short answer

There are two reasons, and only one is about code.

1. **We told him so.** On 2026-11-08 he asked in PAD's own thread (post #464 there, ticket PAD-1059): *"Is
   this something I would be able to use if I was intending to build the game from scratch and not just modify
   what already exists?"* Our reply was: *"Not really. PAD works on the software of a game that already exists
   ... It doesn't give you a way to write a new game's code or rules. For a machine built from scratch, the
   Mission Pinball Framework is the usual place to start."* The mode maker was left out on purpose, because it
   is unlocked only with a preview code. His post #256, *"Never used PAD (still haven't) they agree it's not
   able to do what I'm doing here"*, quotes that answer back. stumblor had told him the opposite in #183
   (*"Essentially, yes. There is a pretty sophisticated mode editor built in now, including a mode SDK that you
   can point your agent at"*). He weighed the two answers and kept going with MPF.
2. **The real gap is the one stumblor named in #183**: *"What it doesn't look like is currently possible is
   starting from scratch."* PAD's modes add to Stern's game; they never replace it. X-Men 2.0 is a whole new
   ruleset. Stern's modes, scoring, progression, callouts and wizards are gone, and it adds things a PAD mode
   cannot do at all: saved story progress, several of his modes running at once, the Action button, and his own
   menus. Even with the mode maker unlocked, about two thirds of his design has no route in PAD today
   (table below).

## What X-Men 2.0 is (from the thread)

- **The game.** A new game on a Stern Uncanny X-Men **Pro** (#222): new rules, progression and flow, built
  "from scratch" (#1, #172). It keeps Stern's playfield and Stern's point values as a starting point (#61, #180).
- **How it was built.**
  - The first stack was MPF plus the mpf-spike bridge. MPF is Python/YAML and the bridge is Rust. MPF ran on a
    laptop, with a Raspberry Pi in the backbox planned, talking over USB serial to the bridge on the Stern
    CPU's SD card (#6, #133, #154).
  - The code is AI-written. By his own account he had zero prior coding experience (#88, #126, #272).
- **Where it runs now (#256, #257, #260).**
  - *"I now have the entire game playing off of the SD card....the screen and speakers work as well - NO
    raspberry pi, and no laptop."*
  - He doesn't say how, or whether MPF still runs. The likely reading is that his program replaces Stern's game
    program on the board and drives the node boards, LCD and amp itself. tgarrett09 did the same with his own
    native Spike 2 build (#105, #144).
  - Planned distribution is *"a simple SD card swap"*, maybe with wireless updates (#260). He says he won't sell
    it (#231).
- **Assets.** Mostly his own, many AI-generated. He reuses the Genesis X-Men music as a placeholder (#135), was
  given silentcorp's animated-series work (#90, #165), and asks others for labelled video and sound assets
  (#146).
- **The design.** Every item has an "In PAD today" verdict in the table below.
  - Sentinels are timers on the inserts, colour-coded by strength (#5, #160).
  - Mutants have health bars, and their side objectives in the Future unlock passives (#5, #140).
  - Each X-Man gets an Action-button ability. A Mutant Meter fills from combos, the ability has three levels
    trained in the Danger Room (#40, #88), and Cyclops' Optic Blast clears the playfield (#5, #84).
  - Hold a flipper plus the Action button to open Cyclops' visor (#249, #250).
  - He has 8 modes of 3 phases each (#41). Mini-wizards come from orders of modes (#140), with multiballs and
    3 wizards plus a secret one (#150).
  - Drain doesn't end a mode; it resumes next ball (#222, #252).
  - Story mode saves between games and power cycles, then a New Game Plus with unlocks; Classic mode doesn't
    save (#41, #77, #200, #235).
  - You pick an episode/mission through the portal (#5). There is a starting roster and unlockable mutants, and
    a Bishop rule that resets a lost mutant (#52, #140).
- **The community's top ask (#257).** *"we NEEDED this to play on the machine with no extra gadgets"*. It was
  also the case for PAD in #162 and #177: PAD runs on the original board, so the pinwoofer amp keeps working.

## His design against PAD today

The reference is the mode SDK (`tools/spike2_emu/modes/sdk/MODE_LIMITS.md`, `MODE_SDK.md`, `pad_mode.h`) and the
X-Men ports `ports/uncanny_xmen_{le,pro}-0.98.port`. The mode maker is preview-only, which is gap 0.

| His design needs | In PAD today | Where it stops |
|---|---|---|
| 0. Being able to use the mode maker at all | **Gated** | Unlocked only with a preview code, so the public answer was "PAD can't write rules" (PAD-1059). |
| 1. Stern's rules switched off, his whole game in their place | **Missing** | `MODE_LIMITS.md:9`: the app "doesn't rewrite" Stern's code, and a mode "runs next to it". `pm_block_game_modes` refuses the 14 X-Men stock mode starts. Nothing turns off Stern's scoring per shot, callouts, shows, video, ball save, multiballs or wizards. The X-Men ports have no `block_rule` sites. |
| 2. Replace the game program (what he did) | **Missing** | `mode.so` loads inside Stern's process (`-nostdlib`). There is no "own program on Stern's hardware" target. |
| 3. Scoring of his own | Partial | `pm_score_add/sub` exist, but Stern's shots still score their own values on top. |
| 4. Progress saved between games and power cycles; New Game Plus; unlocks | **Missing** | Variables last a ball, a mode or a game (`block_modes.py:23`). `pm_read_file` is read-only. PAD-1280 records are high-score entries a mode can't read back. `MODE_LIMITS.md:60`: no settings, audits or high scores from a mode. |
| 5. Eight-plus modes of his own running and stacking, with a Future layer under them all game | **Missing** | `MODE_LIMITS.md:26`: "Run two of mine at once: No. One at a time." Each mode ends at drain or game over. |
| 6. Drain doesn't end a mode; it resumes next ball | Partial | Game-scope variables can carry the phase, but the mode must restart itself on the next ball start. |
| 7. Action button abilities; flipper + Action combos | **Done (PAD-1403)** | The Action, flipper and Start buttons are shots on every Spike 2 title: press, release, held 1 s / 3 s, and Left / Right flipper + Action and both flippers (MODE_SDK.md "The cabinet buttons as shots"). Proven on X-Men LE and Pro 0.98 in the emulator. |
| 8. Pick an episode or mutant with the flippers; team or roster pick at game start | **Missing on X-Men** | There is no menu API. X-Men has no challenge route (`pad619_challenges.md:74`), and the team start menu skips X-Men (PAD-1052). |
| 9. Health bars, Mutant Meter, Sentinel strength | Partial | The HUD has three counters, a timer badge and a pip gauge (`block_modes.py:30`). There are no bars or arbitrary meters. Inserts with RGB per Sentinel: yes (85 lamp lines on the Pro port). |
| 10. Fade to black with a red glow (Optic Blast) | Partial | Own clips play (`pm_clip`/`pm_backdrop`, up to 32 a mode), so the fade can be a clip. There is no screen effect primitive. |
| 11. Magnet ability (Magneto), Sentinel bash toy, kickbacks | Partial | Magnet hold and the right return are proven on X-Men LE and Pro. The game's other coils are refused (`MODE_LIMITS.md:56`); spare outputs only. |
| 12. Multiballs and ball saves of his own | Yes | `pm_multiball_start/add`, `pm_ball_save`; the Pro port has `multiball_serve`. |
| 13. Mini-wizards from combinations of modes | Partial | "Only after" and `starts_on completed` chain his own modes. `MAX_COMBOS = 8`. One mode at a time limits it (row 5). |
| 14. His own sounds, music, callouts | Yes, capped | 16 sounds and 6 music beds a mode, riding stock slots that never play (a fixed number per card). |
| 15. His own videos | Yes, capped | 32 clips a mode. The 64-mode cap is far above his count. |
| 16. Light shows | Yes | The X-Men ports have light shows; the PAD-646 editor allows 24 shows a mode. |
| 17. His own attract and title screen ("UNCANNY X-MEN 2.0 - PRESS START", his photo in #256) | Partial | The attract editor (PAD-782) adds pages between Stern's. It doesn't replace Stern's attract or boot screen. |
| 18. Original and his code on one card | Yes | Multi-boot, and Edition in the service menu (PAD-495). stumblor recommended exactly this (#183). |
| 19. Porting what he already wrote (MPF YAML, Python) | **Missing** | The SDK has an agent brief (`MODE_SDK.md`, the PAD-652 tile), but there is no MPF import. His AI could port it into C modes, but rows 1, 4, 5 and 7 have no target. |
| 20. Giving it to other owners as an SD card swap | Partial | Mod Pack and a mode's "Save to a file" (PAD-1050). `docs/guide/legal.md:26`: PAD ships no game content, and distributing modified firmware is the user's own responsibility. |

What PAD has that his route lacks:
- It runs on Stern's own board and program, so the amp, the pinwoofer and Stern's ball handling, node bus and
  stability all stay (#177, #178).
- Dual boot (row 18).
- Emulator-proven builds.
- Every Spike 2 version.

## What closing the gap would take

Rows 1, 4, 5 and 7 are the blockers. Without them he cannot build his design in PAD, however skilled his agent.
In order, each step useful on its own:

1. **An "own game" mode (rows 1, 3, 5, 6).** A mode that starts with the game and lasts every ball. It blocks
   every stock mode start, which is already wired for X-Men. It finds and blocks the rule features that are
   still live: needs `block_rule_<n>` sites for both X-Men ports. It mutes the stock scoring per shot, callouts
   and shows, which is new: a site per build where the game awards a shot. Inside it, the maker's own modes
   become sub-modes that can stack. Running two at once is new; today's single-slot model in `mode_file.c` and
   `block_modes.to_c` would grow into a parent mode with child states. This is the PAD answer to "start from
   scratch on the game's own infrastructure", the hack stumblor guessed at in #183.
2. **Saved progress (row 4).** A small key/value store a mode can write: per profile or per game slot, kept on
   the card's data partition like `/dump/pad_challenge_scores`, size-capped, and wiped by a factory reset.
   Blocks: "Remember" and "Recall" variables with scope "saved". Unlocks a Story mode, New Game Plus and roster
   unlocks.
3. **X-Men inputs (rows 7, 8).** The Action button and flipper buttons as shots on both X-Men ports, the PAD-228
   `switch` lines Godzilla has. Then a generic flipper-picked menu (a list on the HUD, flippers move, Action or
   Start picks), which also gives his episode and mutant pick.
4. **Meters (rows 9, 10).** A bar HUD element (value/max, colour), several per mode, and a screen fade.
5. **Total-conversion attract (row 17)**: replace, not interleave, Stern's attract pages and title. Plus
   **unlock the mode maker** for makers like him (row 0, David's call), and an **MPF-to-PAD porting guide** for
   agents (row 19), which needs steps 1 to 3 first.

Step 1 is the big one: several runs, with per-build sites found and proven on X-Men LE and Pro 0.98 in the
emulator. Steps 2 to 4 are each about one ticket's size and useful to every title, not just X-Men.

## What would not close it

- Replacing Stern's game program, his route (row 2). PAD would become a game framework and lose what makes it
  worth choosing: the stock board, program and stability. MPF plus the bridge already serve that path.
- Bundling his assets or Stern's: PAD ships no manufacturer content.
