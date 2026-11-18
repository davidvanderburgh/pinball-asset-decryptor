# Saved progress: a mode remembers between games (PAD-1402)

Row 4 of the PAD-1398 gap analysis (Uncanny X-Men 2.0 built in PAD on Stern's own program): a mode's variables last a
ball, a mode or a game, `pm_read_file` only reads, and PAD-1280's records are high-score entries no mode can read back.
A Story mode, New Game Plus and unlockable characters all need what the player did to outlive the game and a power
cycle. This adds that store and the blocks' way into it.

## What is built

- **The runtime's store** (`pad_mode_runtime.c` "SAVED PROGRESS", `pad_mode.h`): `pm_saved_get(key, player, dflt)`,
  `pm_saved_put(key, player, value)`, `pm_saved_stamp(player)`. Values are `long long` by key, per owner: player 0 the
  machine's (one for everyone), players 1-4 that player's - their Stern Insider Connected login (the 16-byte user id in
  the user manager's table, `coop_play.insider_users`, read the way PAD-1108's co-op reads it, a co-op turn's swap
  undone) while they are logged in, else their player slot. `/dump/pad_saved_progress` on the card's data partition,
  beside `/dump/pad_challenge_scores`: one `<owner> <key> <value>` line each, 16 KB at most, written whole and renamed
  over about two seconds after a change (never on every change), a changed value moved to the end, the lines at the
  front (longest unchanged) dropped to make room.
- **SAVED PROGRESS** in the service menu (`menu_settings.SAVED_PROGRESS`, `engine._SavedProgressMenu`; Custom Code
  page): 1 = Keep, 2 = Clear, **default Clear**. Whenever the runtime reads Clear it clears every value and puts the row
  back to Keep. A factory reset puts every row back to its default, so it clears the progress with the game's own
  settings; so does the row's first boot. On the shared MORE SETTINGS rows (PAD-1382) the value is the runtime's word
  (`sv_setting_put` keeps it and the row shown in step), which a factory reset does not reach.
- **On a card only when a mode uses it** (`saved_progress.wanted`: `pm_saved_` in a mode's C, or a blocks mode with a
  saved variable): `saved.cfg` beside the runtime (`on`, `clear <row>`, `users <manager> <A> <B>`), carried by
  `mode_write.saved_into`, the p2 staging, `mode_install.EXTRA_FILES` (the real card), `tryit.sh` (Try it, the rig) and
  `cardmodes.sh`'s clean-up. The progress file itself is the machine's: no install or clean-up touches it.
- **Spike 3** the same way: `spike3_menu.rows_wanted` asks for the row, `spike3_write` passes its value through
  `spike3_modes.plan`, and the 64-bit runtime reads `/games/pad/padmode/saved.cfg`.
- **Blocks**: a variable's reset **never: saved, each player's** (`saved`) or **never: saved, for everyone**
  (`saved_all`), shared ones too (`shared:<name>`; a mode's own `<slug>:<name>`). The generated C keeps a table of them
  and a `saved_tick` after the new-game check: a player's values are read whenever `pm_saved_stamp` changes (a new
  game, a login, a clear) and a changed one is put; a new game, a ball's end and the mode's start never zero them.
  The blocks simulator keeps them between games too. The Modes tab's reset drop-down offers both, the tip says what
  they do, and the Service menu tab lists SAVED PROGRESS (on the card when a mode keeps a saved variable).

## Decisions

- **Each change kept, no Remember/Recall blocks.** The gap analysis named "Remember" and "Recall"; a saved variable
  is simply never reset and is kept as it changes, so every block that sets or changes a variable already remembers.
  A checkpoint ("only if the chapter is finished") is a game variable copied into the saved one by a Set block.
- **Owner = Insider login, else the player slot.** A logged-in player's progress follows them; a guest's belongs to
  "player N" on that machine. A login made during the first ball takes effect as soon as the game reports it (the
  stamp changes): the values already counted under the slot stay the slot's.
- **Default Clear** so a factory reset clears it (the ticket's ask) with no game-specific factory-reset hook.
- **The runtime's Keep is not the game's until the game saves its settings.** Writing the row's record changes the
  game's memory only; the game stores its settings (`/data/nv/<title>/NVM`) when its menu saves them. The first
  emulator runs showed a power cycle reading Clear again and clearing the progress. Calling the game's own adjustment
  setter would need a site found on every build; instead the store keeps the stamp of the game's newest settings
  generation from when it put the row back, and a Clear read at boot with that generation still newest is not
  cleared again (pad_mode_runtime.c "the row put back to Keep"); a factory reset writes a new generation, so it still
  clears. This rests on the game saving its rows from memory (Guided Setup's Save & Exit stored the runtime's Keep in
  the emulator).
- **16 KB, oldest dropped** rather than refusing a write when full: a machine that sees many Insider players forgets
  the least recently changed values first.

## Proof (emulator)

X-Men LE and Pro 0.98, rig kit `C:/tmp/PAD-1402` (mkset.py builds an Emulate set through `engine.write_overrides` from a
scratch project with one blocks mode, STORY, counting each ended ball in `drains` (saved, each player's), `total`
(saved, for everyone) and `this game` (each game); job.sh / job2.sh on rigjob.sh, go.sh / go2.sh = rigbatch). Balls end
by a sling and pop hit, the tilt four times and `plunge.py drain` (rig drains alone are ball-saved forever). Both
builds, the same numbers:

| step | the store after it |
|---|---|
| 1 boot (the row already Keep on that rig) | empty |
| 2 a 2-player game | p1 3, p2 3, total 6 |
| 3 a 1-player game | p1 6, p2 3, total 9 |
| 4 power cycle | p1 6, p2 3, total 9 - the row reads Keep, nothing cleared |
| 5 a 1-player game | p1 9, p2 3, total 12 |
| 6 factory reset (the title's NVRAM wiped) | cleared: the row read its default, Clear; the runtime put it back to Keep, and Guided Setup's Save & Exit stored that Keep (`the game saved its settings (generation 2) with SAVED PROGRESS at Keep`) |
| 7 a 1-player game | p1 3, total 3 |
| 8 power cycle | p1 3, total 3 - kept |
| 9 a 1-player game | p1 6, total 6 |

The Clear already answered (job2.sh): a factory reset, cleared at boot (the mark names settings generation 1), the
power cut before the game saved its settings, `p1 story:drains 5` put into the store while it was down; the next boot
read the same Clear with generation 1 still newest: `not cleared again; Keep again`, the 5 kept, and the next game
counted it on to 8.

What an earlier build of this ticket did on the same rig, and why the mark exists: the runtime's Keep is only the
game's memory, and two games and a power cycle later the stored row still said Clear - that boot cleared the progress.

Tests: `tests/test_pad1402_saved_progress.py` (the store lifted from the runtime and driven on the host: put, get,
update to the end, the oldest dropped at the cap, owners; the Keep/Clear state machine through a first boot, an old
Clear, a factory reset, a stored Keep and a live Clear; the runtime's hooks and files; the blocks' resets, checks
and C; the simulator; the row; saved.cfg and the install lists; which modes ask for it).
