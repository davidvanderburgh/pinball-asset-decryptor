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

## The attract pages (in progress)

Probe (rig instrument C:/tmp/PAD-663/rig/probe663.c, rigbatch over the 53): every read of the entry lookup in
attract, with its caller. Two shapes so far:

- One page PROCESS per category (Bond, Stranger Things, Aerosmith, Guardians): PAD-660's route
  (`challenge_page`, its title message wrapped) works for any category with exactly one page.
- One generic page FUNCTION, `page(object, category, n, frames, [stack])`, called per category and blocking for the
  page's time (Avengers 0x214d8 - its first words are `movw/movt ip` - Deadpool 0x2375c, Godzilla 0x23b78,
  Iron Maiden Pro 0x434c8 ...). It reads the entry's record (initials +32, score) and its TITLE from the entry's
  titles list (+0x18) - the field PAD-640 already points at the mode's name. The plan: wrap it; after the game's own
  call for its first category, call it again (same arguments, up to four stack words) once per mode champion, the
  category's first entry pointed at the mode's record and titles, put back after.

Static finder for the generic page: a function calling the entry lookup with the category from a register, keeping
the result (`subs/mov rE, r0`) and loading `[rE, #0x18]` - matches the probe on Avengers, Deadpool, Godzilla, Iron
Maiden Pro; Batman, Beatles, Foo, Mando, Metallica, Rush, SoR, TMNT, Venom need their shapes read.
