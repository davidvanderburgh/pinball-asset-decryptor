# PAD-663: a mode's challenge champion on every Spike 2 game

Spun out of PAD-660. A mode's challenge high score (PAD-640) and its attract-mode champion page (PAD-660) were only
on Bond LE/Pro 1.06 and Stranger Things. Goal: every Spike 2 build where a mode can play a challenge keeps the mode's
own champion and shows it in the attract mode, with the game's own champions unchanged.

Scope: the newest build of every title (the library, `D:\Pinball\images\Stern\spike2\*.raw`; the ticket skill,
2026-10-20: "every build" is every title's newest build, the `older versions` folder is not touched). Builds a user
derives get the same lines from their own program (port_derive.py runs portchallenge.find). 46 of the 53 newest
builds have a challenge a mode can take; King Kong 0.97, X-Men 0.98, D&D LE/Pro 1.10 and Bond 60th 1.11 have none.

## What every build keeps (static survey of the 53 game programs, 2026-10-21)

The champion framework is the same code on all 53: one 36-byte category table (category 1 is HIGHEST SCORES on
every build), the (category, n) -> entry lookup, and one end-of-game function. In that function, before it files a
player under a category's entry, it asks the bus:

    strb rP, [sp, #0x48] ; strh rC, [sp, #0x4a] ; str rE, [sp, #0x4c]   ; {player, category, entry}
    ...
    mov r0, #0x5b ; add r1, sp, #0x48 ; mov r2, #0 ; mov r3, #0 ; strd ... ; bl <dispatch> ; cmp r0, #0 ; beq <skip>

the only bus call in it whose answer is tested (0x55..0x5a are announcements). The game's own handlers say no to a
category that does not belong to the kind of game played (Bond's challenge game: only the pick's category).

Champion categories per title: Bond / Stranger Things one per challenge (PAD-640's route, kept); SoR, TMNT,
Munsters, Jaws, John Wick, Avengers (Battle Royale), Beatles (CHALLENGE MODE HIGH SCORES) some of their own; Mando,
Venom, D&D one CHALLENGE CHAMPION; the rest none. None of that matters to the route below.

## The score (done)

`portchallenge.scores_lines` now writes, for every build with the framework and the gate:

    site  challenge_scores        the end-of-game function (PAD-640)
    site  challenge_score_entry   the entry lookup (PAD-640)
    site  challenge_scores_gate   the `bl <dispatch>` of the 0x5b question (PAD-663)
    value challenge_scores_gate_id / _cat_at / _entry_at   91, 2, 4
    value challenge_scores_cat    1 (HIGHEST SCORES)

and Bond / Stranger Things keep `challenge_scores_cat_<n>` (each challenge's own category). The runtime, for a
mode's challenge game: points the host category's first entry at the mode's record (as PAD-640 did), zeroes the
entry's award (+0x20: GRAND CHAMPION wins credits) for the call, and wraps the gate call (`hook_call`, new: a `bl`
and the plain word after it moved into a six-word trampoline) so that only {host category, entry 0} says yes and
every other category says no. The game's own records are not touched by a mode's challenge game.

Found on the way (fixed): a menu entry of a mode's own on a build with no challenge of the game's behind it is
picked as slot ~0u, which `chg_hs.slot` (an int) read as "no pick"; and Avengers LE 1.10 starts the ball (where the
pick is taken) before it counts the game's start, so the pick was stamped with the last game - re-stamped when the
taking mode begins (`chg_scores_began`).

## The attract pages (done)

Probe (rig instrument C:/tmp/PAD-663/rig/probe663.c, rigbatch over the 53): every read of the entry lookup in
attract, with its caller. Four shapes, all wrapped the same way (the game's own call first; after the call that
showed the cycle's first category, the same call again once per mode champion, the category's first entry pointed at
the mode's record and titled "<NAME> CHAMPION", put back after):

- One page PROCESS per category (Bond, Stranger Things, Aerosmith, Guardians): PAD-660's route (`challenge_page`).
- One generic page FUNCTION called per category (`site challenge_pages_0..3`; most builds; Deadpool, Batman 66, Jaws,
  The Beatles have up to four of that shape and all are named). It reads the entry's record and its titles (+0x18).
- HIGHEST SCORES on one LIST page of five rows (TMNT, Venom: `site challenge_list_page`), repeated with the
  category's list cut to the first entry.
- One ROW page per HIGHEST SCORES row (Jurassic Park The Pin): the GRAND CHAMPION's row page named with the pages.

Found on the way (fixed):
- The site must be the function's first word: Sword of Rage opens `movw ip ; movt ip ; ldr ip, [ip] ; push` and,
  wrapped at the push, crashed in attract; TMNT's list page sets r1/r3 up the same way (`_prologue_start`).
- A page's category is the last entry read OF THE TABLE's: after a game Avengers shows the last scores under a
  category of its own (55, table of 38) and Jaws' page reads category 63 entry 0 after the row it shows; the port's
  `data challenge_scores_count` (the category lookup's own bound) is read at each page call.

## Proof (emulator, the newest build of every title)

- Attract (C:/tmp/PAD-663/kit/jobattract.sh: a mode champion record seeded, booted to attract, the page waited for
  and pictured): 44/46 on the first full sweep; Led Zeppelin Pro / Rush Pro rerun.
- A mode's challenge game played to its end, initials entered, the page in attract after, the game's own records
  logged throughout and unchanged (kit/job663.sh on start-menu builds; kit/jobpick.sh on the nine with no start menu,
  the pick made as the game's own selector makes it).

Found by the game sweep (fixed):
- The challenge's "end this ball now" was made from the tick, where there is no current process; The Beatles 1.29
  asks the current process's id while its processes are killed and crashed (null read at 0x6dd2c) as a mode's
  challenge ended. It is now owed to the game's next bus call (a handler of the game's, as the game's own challenge
  endings are), from the tick only when none comes within a second.
- A game started while the game's own champion page was showing left the page marked as running and every later page
  went straight to the game (Batman 66, Godzilla, John Wick: no mode champion after a game). Cleared once a game is in
  play, or after a minute.

Job notes (C:/tmp/PAD-663/kit, job663d.sh / jobpickd.sh): Metallica and Mando file the end-of-game scores at or before
the game's game_over event, so the job waits for either and presses Start only while our record is being entered (an
extra Start began a new game and the attract page never came). The Pin's flipper buttons are "L/R FLIPPER BUTTON"
(FL=58 FR=57). While the game enters initials the host entry reads the mode's record; it is put back when the call
returns (a game-records snapshot inside that call is not a change).

Found by the final sweep (fixed): The Beatles 1.29 and Star Wars ELG 1.10 keep a shorter champion record - a u32
score at +80 and the check (~ the byte sum of what is before it) at +84; every other build a u64 at +72 and the check
at +88. A mode's record in the long layout failed the game's check, the game took HIGHEST SCORES as damaged and reset
it for the call: no initials, no champion. portchallenge reads the layout off HIGHEST SCORES' own compare (category
1's +0x10) and names it where it is not the default (`value challenge_record_check_at / _score_at / _score_size`).

More job notes (kit/job663e.sh, jobpicke.sh, jobgze.sh, proof663b.sh, rig/rec663b.c): the game records' last read
is taken in play (a page's entry points at the mode's record while the page shows - a snapshot inside that call is
not a change; the runtime puts every entry back as a game starts); a game the last initials' Start began is drained
to its end; points are added in the challenge ball (John Wick's switch names are not the job's, its player scored 0
and a 0 never beats a fresh record); Godzilla LE takes the pick at the next ball's start, so its first ball is drained.

Found on the small screens (fixed): Star Wars Home Edition and Jurassic Park The Pin draw on an 800x480 panel (a
reported fact, tools/spike2_emu/display2.py REPORTED_PANELS - in no game program), and "PAD CHALLENGE CHAMPION" ran off
both edges of the HIGHEST SCORES page our page repeats. A build whose program carries one of those titles gets `value
challenge_page_title_max 18`; past it the title is the mode's name alone (as past 27 on the full cabinets).

Diagnostics added: a start-menu pick of a mode's own challenge that is not played says why (the menu's entry under
the cursor is no longer ours; the ball started in no challenge game). TMNT's cursor does not start on the first entry,
so the job stepped past ours and back onto STANDARD; the job now steps until the runtime says ours is picked.

John Wick 1.02 (fixed): the bus is called from more than one thread, and when the challenge's ball end rode a bus call
on another thread John Wick's game logic stopped for good (its log ends at the call, its video runs on). The call is
made from a bus call on the game-logic thread only (the tick's), from the tick only when none comes within a second.

## Result

Final sweep on the finished runtime (C:/tmp/PAD-663/rb_final, kit/jobfinal.sh): all 46 newest builds with a
challenge a mode can take play a mode's challenge game to its end, keep the mode's own champion, show it on the
attract mode, and leave the game's own records unchanged (44 on the first pass; Avengers LE's rig never booted and
Mando LE's last initials press started a new game - both passed on a rerun). Every ball end came from a bus call on
the game-logic thread. After merging main: Avengers Pro, The Beatles, Bond LE, John Wick Pro and Star Wars ELG again,
all pass. Before/after pictures: C:/tmp/PAD-663/shots.

