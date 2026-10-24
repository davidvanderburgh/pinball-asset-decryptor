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

## Not done here

- The plain-C titles (no mode class): their modes are start functions and flags. Next run: the names line up with
  the game's own books (James Bond LE 1.06: block_name "Ahoy Mr Bond Wizard Mode" -> AUD_AHOY_MR_BOND_WIZARD_MODE_STARTED,
  FG_AHOY_MR_BOND_WIZARD_MODE_PLAYED / _COMPLETED; "Bullshit Scoring" -> AUD_BULLSHIT_SCORING_STARTED,
  FG_BULLSHIT_SCORING_PLAYED), so a mode in one's place can count there through the framework's audit add (the same
  function on every build: `push {r4-r9, lr}; subs r5, r0, #0; ...; movw/movt r4 = the audit table`) and the game's flag
  set, the ids read off the FG_ / audit name tables (memory plain-c-fg-flag-names); the route itself (the claim at the
  start function) needs the plain-C start's arguments for a test start.
- A challenge (PAD-615/619) whose challenge is one of the game's modes does not count as that mode yet.
- D&D LE 1.10: no game starts on the rig (attract loop, known); its framework is D&D Pro's (proven).
