# PAD-1382: more service-menu settings than a game has spare rows

## The limit

Every service-menu setting of ours takes over an adjustment the game no longer reads (a DEPRECATED one,
`menu_settings.spare`). A game's adjustments cannot be added to: each one's value is eight bytes of the board's NVRAM
mirror by id, and the store is keyed by the caption. Godzilla 1.16 (and every latest Spike 2 build measured, PAD-1033)
has three. MUSIC MODE, CO-OP PLAY, HANDICAP, the three picture settings, EDITION and (Simon's branch) IMAGE SET
already want more. Before this, the planner refused what did not fit: on Godzilla LE 1.16 a card with co-op, handicaps
and the picture settings lost co-op altogether and had handicaps forced on (`artifacts/PAD-1382/emulator/build_before.log`).

## What is built

When a card wants more settings of ours than the game has spare rows, they all share two
(`menu_settings.plan_many` -> `plan_shared`):

- **MORE SETTINGS** (values 1..n, its help names them) picks one;
- the row under it (descriptor caption SETTING VALUE) is that one's value. The mode runtime writes the picked
  setting's row caption, help line, range, default and display kind over it, and its value into the row's record
  (with the record's check byte), whenever the pick changes. An accepted change there is that setting's new value.

The **values live on the card**, not in the game's store: `/dump/pad_settings.state` (one `key value` line each,
written to a temp file, fsynced, renamed), so any number of settings keep their values over a power cycle. The game's
store keeps only MORE SETTINGS's pick and the last value the row showed. Up to 8 share (MAX_VALUES). EDITION never
shares: codeselect reads it off the store before the game runs. Settings that fit keep rows of their own exactly as
before; sharing starts only when one would be refused for want of a spare row.

Each setting's reader is unchanged: its cfg line names `0xFADE0000 + 4k` (above a 32-bit process's user space)
instead of a `.nonvol` address, and `setting_addr()` (every reader: coop, handicap, music modes, picture settings)
hands it the runtime's word for setting k. `settings.cfg` (written by `menu_settings.shared_cfg_text`, beside the
runtime: `/usr/local/padmode` on a card, `/dump` in the rig) says where the two rows are and lists the settings.
MUSIC MODE's `sounds.cfg` is written before the menu is planned, so its `setting` line is re-pointed afterwards
(`engine._point_sounds_cfg`).

The rows are watched by a thread of the runtime's own (every 50 ms), not the game's tick: a card of settings only
never hooks the tick, and the menu runs whatever the game does. The thread and its nap are looked up by name
(`pthread_create`, `nanosleep`); MODE_SDK rule 2 is about a mode's code on the game's threads and still holds for
every mode. For 3 s after the pick is first seen the row is held at our value (the game reads its store at boot).
Spike 2 only: a 64-bit program never shares (its category table cannot grow yet; `plan_shared` refuses).

## Proof (emulator, Godzilla LE 1.16, `artifacts/PAD-1382/emulator`)

Override sets built by `engine.write_overrides` from main and from this branch (`C:/tmp/PAD-1382/mkset.py`, job
`job.sh`): co-op (menu), handicaps and the picture settings = five on three spare rows.

- main: Attract Mode has no CO-OP PLAY or HANDICAP row; co-op left off the card, handicaps always on.
- branch: Attract Mode lists **More Settings 1** and **Brightness 5** under it. More Settings -> 4: the row becomes
  **Co-op Play 0** with co-op's help and Current/Default values; set to 1. More Settings -> 5: **Handicap Off** (Off/On
  display); set On. Back to 4: Co-op Play reads 1. `pad_settings.state` holds `coop_play 1`, `handicap 1`.
- power cycle: the runtime reads both back, co-op arms "now Classic" and handicaps "while HANDICAP is On" (the
  features read the shared values), and the page shows More Settings 4 / Co-op Play 1.

Tests: `tests/test_pad1382_more_settings.py`.
