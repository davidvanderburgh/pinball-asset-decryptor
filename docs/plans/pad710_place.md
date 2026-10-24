# PAD-710: a mode in the place of one of the game's own modes counts as that mode, every Spike 2 title

David, 2026-10-24 (during PAD-706): "Can we apply anything here generically to other spike 2 games?" ... "Make it a
ticket". PAD-706 made a mode picked in one of Godzilla's battles count as that battle (the battle's START bookkeeping
at the pick, its own STOP with the mode's outcome at the end). This does it for any of the game's own modes, on every
C++ Spike 2 title, through the game's own mode framework.

## What changed

- **A new way into a game mode's place**: the game starting one of its own modes (the ones PAD-363's port lines name a
  start of, with its object) starts a mode of ours instead. The runtime's start hook (`on_block_start`) asks a claim
  first (`pm_place_claim(id, on_start)`); a taken start is refused, and the mode starts on the next tick. Mode files:
  `in_place_of <id>`; the Modes tab's form: Starts on > *the game starting its* <mode>; blocks: *When the game starts
  its* <mode>, End the mode *, completed*.
- **Counted as the game's mode** (`pad_mode_runtime.c` "PAD-710"): at the take, the START's bookkeeping without the
  mode running (the player's stopped and reason bytes cleared, the start count + 1, the manager's STARTED notice where
  the generation has one); at the mode's end `pm_place_over(won)` runs the mode object's own STOP virtual with the
  outcome (`stop(mode, won, 1)`), so the game writes the completion itself: stopped, reason, END, wins, the COMPLETED
  audit, the title's own outcome logic.
- **The game's framework, per build** (`plugins/stern/mode_framework.py`, `sdk/framework_lines.py`): the STOP's slot,
  the stopped / reason bytes, the start and win counts, the player getter and the manager's notice, read off each
  build's own program by the STOP's one shape (MODE_SDK.md "A mode in the place of one of the game's own modes" has the
  shape and the table by generation). Written into the 37 shipped C++ ports whose programs were on hand (the newest
  build of every C++ title and Godzilla Pro 1.15); the card build adds them from the card's own program to any port that
  lacks them (`mode_write.with_framework`: the older builds' shipped ports, whose cards are archival here), and
  `port_derive` writes them into a derived port. portgen counts them as each build's own lines.
- **Profiles**: `places` ((id, name, counts)) and the `place` part, offered on `PLACE_PROVEN` builds; Godzilla's
  battles stay the battle hat's.

## The generations (desk, the newest builds; C:\tmp\PAD-710 fw*.py, armdis.py)

The STOP has the same shape on all 37 C++ builds read; its slot and offsets move. The crule generation keeps its
fields at fixed distances (starts = stopped + 0x11, wins = starts + 0x1c; Venom + 0x2c). Only Godzilla's, Avengers',
Deadpool's, Iron Maiden's, Jaws', King Kong's and Jurassic Park's managers keep per-mode audits (the STARTED notice);
the crule titles and Star Wars log a trace line there instead. John Wick's STOP takes a third word (1 = mark stopped,
always 1 from the game). Jurassic Park's STOP asks the mode's own "stopped already?" virtual first (v[32]); the JP Pro
modes the port names override it.

## Proof (emulator, hidden, muted; C:\tmp\PAD-710\rig)

`place_job2.sh` over `rigbatch.sh`, every C++ newest build: the test object (the runtime + mode_file.c + `p710test.c`,
an instrument that has the game START its mode as its rules do and reads the mode's audits, decoded off the manager's
notices), a mode file `in_place_of <id>` with an 8 s clock (so it completes by its clock), the game's own STOP run,
then the game playing on 5 s. Pass = the game recorded the completion (stopped, wins up, or the COMPLETED audit up).
Godzilla LE 1.16 Jet Fighter Attack: STARTED 0 -> 1 at the take, COMPLETED 0 -> 1 at the end, stopped 1, reason 1.

## Run 2: the plain-C titles

No mode class, so no framework stop: the game keeps a mode's books in its audits and flags, named after it
(`mode_framework.plain_books`; MODE_SDK.md "The plain-C titles"). Reading audit ids out of the start functions' code
was unreliable (they count through wrappers), the ACTIVE flag a start sets is clean: its stem names the mode's books.
167 of 170 game modes of the 16 newest plain-C ports have them. The runtime counts them at the take (STARTED audit,
PLAYED flag) and at a completed end (COMPLETED flag and audit); a test start on a plain-C title only while claimed.
Proof: `place_job3.sh` (the instrument reads the audits through the audit add's table and the flags from the bitmap).
Sweep plain2 (`place_job4.sh`, final runtime): 16/16 - the job reported Star Wars ELG a fail only because the
instrument reads audits through the audit add ELG lacks; the runtime's own bit read-back showed its COMPLETED flag set.
Star Wars ELG's first "audit add" was a lookalike (the same three head words, a function taking stack arguments): the
signature now needs the table load and the 16-byte record index too, and ELG counts through its flags alone.

Challenges: `value challenge_place_<n> <id>` (by the names' words) on Godzilla x3, Bond x2, Jaws x2, Metallica x2 and
Rush x3; the take counts the START (`place_challenge`), the end `pm_place_over`. Proven on Bond LE (the PAD-696 kit,
Default Game Mode 3): STARTED audit 180, PLAYED flag 86, then COMPLETED flag 89.

## Not done here

- (Done in run 2, below.)
- D&D LE 1.10: no game starts on the rig (attract loop, known); its framework is D&D Pro's (proven).
