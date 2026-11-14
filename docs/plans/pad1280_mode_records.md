# Records of your own on the high-score table (PAD-1280)

Peanutsfr (Discord): "create custom High Score entries in the HSTD section, including for the machine's built-in
modes": a name, a description, the mode it belongs to, and what it measures - points, or a count of shots /
objectives (which ones counted is the owner's pick); edit and delete them; kept with the project.

## What is built

- **Modes tab > High scores…** (under the mode list, `modes_dialogs.js` RecordsDialog; `webui/tabs/modes.py`
  `records_refresh` / `record_save` / `record_delete`): the project's records, each one's editor. Kept in the project
  sidecar (`staged_changes`, key `mode_records`), so they are saved with the project and restored with it.
- **A record** (`plugins/stern/mode_records.py`):
  - `name` - the page's title, capitals, up to 27 (the champion page's longest, as co-op awards);
  - `description` - the owner's note, shown in the app;
  - `mode` - `""` the whole game, `game:<id>` one of the game's own modes (the port's `block_name_<id>` with its
    object `block_obj_<id>`: C++ titles), `own:<NAME>` one of the project's modes (by the name the runtime gives it);
  - `measure` - `points` (the player's score rising while the mode runs) or `count` (the counts ticked);
  - `counts` - `audit:<id>` the game's own audits (every AUD_SHOT_* shot, each mode's STARTED / COMPLETED, ball saves,
    extra balls, ...: the same reading as co-op awards) and `champion:<cat>` the game's own champion counts (Godzilla's
    JET FIGHTER, GODZILLA POWERUP: the category's value getter, risen while the mode runs);
  - `per` - `run` the best single play of the mode, `game` all of it in one game (a whole-game record is always
    `game`).
- **The card** (`records.cfg` beside the runtime, `mode_write.records_into`; a whole install like co-op: the score
  gate holds Insider reports back, because the game's own initials entry runs again under the record's title).
- **The runtime** (`pad_mode_runtime.c`, "records of the owner's own", MODE_SDK.md): counts each player's value per
  record on the game's tick (points, champion counts) and its audit add (audits); at the game's end, after the game's
  own high scores, the game's end-of-game function runs once more for each record a player beat, with the host
  category's (`challenge_scores_cat`) first entry pointed at the record (as PAD-640/663's mode champions), its value
  getter (+4, value(player) -> u64) answering the record's counts, and the gate letting only that entry through. The
  records live in `/dump/pad_challenge_scores` under `"\003" + NAME`, and the attract mode shows each one that has a
  champion after the game's own pages (PAD-660/663's page wrap).

## Choices (decisions for David)

- On the **Modes tab**, not Defaults or Play options: the records need the runtime and hold Insider reports back, as
  modes do (Play options is the tab of things that keep Insider Connected).
- Counting "shots or objectives" with the **game's own audits and champion counts** rather than switches: they are
  what the game itself calls a shot, a mode won, a jet destroyed, on every build that names `audit_add`.
- Records on the **game's own initials entry and champion pages** (the game's look), not a screen of our own.

## Proof (emulator)

Godzilla LE 1.16, rig kit `C:/tmp/PAD-1280/rig` (job.sh on rigjob.sh, run.sh = rigbatch -n 1; stage = the pinned
runtime built with `rec1280_test_mode.c`, an instrument that starts King of the Monsters through the game's own START
and runs a mode of its own for 3 s scoring 123450 + 5; records.cfg from mode_records.cfg_text off the card):

- armed: `records: 5 on the game's high scores (... category 1's place at the game's end, ACTIVE v[14])`;
- one game: the instrument's mode, 4 slings + 3 pops, KOTM started with 3 left + 2 right ramps in it, balls tilted
  away. At the game's end each record went through the game's own initials entry ("PLAYER 1 - ENTER INITIALS / KOTM
  POINTS" on the machine's screen): KOTM POINTS 22,000,000, KOTM RAMPS 5, SLINGS AND POPS 7, TEST MODE POINTS
  123,455, WHOLE GAME POINTS 24,353,775, each `new record ..., AAA`, all five in `/dump/pad_challenge_scores`;
- during each of those calls the gate turned the game's own categories away (`category 29/30 entry 2 is the
  game's`): the game's own high scores untouched;
- attract: `the attract mode shows an award or record (..) under "KOTM POINTS"` and the four others, one page each
  after the game's first champion page (SLINGS AND POPS / AAA / 07 on the screen).

Tests: `tests/test_pad1280_mode_records.py` (the runtime's parser, counting and pages lifted and played through a
model game; the module, Write's plan and staging, the build's gate, the Modes tab's calls).
