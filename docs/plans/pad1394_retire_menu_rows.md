# PAD-1394: retire menu rows a Write no longer wants

A Write reads the game program off the card it writes, and the menu planner (`menu_settings.plan_many`) only ever
ADDED records to the menu's category table. So a card written again from one the app wrote before kept the rows of
settings now switched off (EDITION, HANDICAP, the shared MORE SETTINGS / SETTING VALUE rows, a row left on its old
page) listed on Custom Code with nothing reading them. A Write wanting none of our settings never opened the program.

## What changed

- `stale_rows(table, cat, settings)`: every row the menu lists whose adjustment carries a caption of ours (an earlier
  Write's) and that none of this Write's settings is on, on that page. No game's own menu row carries one of our
  captions: all 60 Spike 2 cards of the library read (`C:/tmp/PAD-1394/stock_captions.py`).
- `plan_many` drops them: out of the table it grows when one grows (`without`), else by same-size writes
  (`shrink_writes`: the shorter table over the old one, tail zeroed, the copy's size constants made the shorter one's).
  Category tables, Standard Adjustments lists and Spike 3 wide tables (`code_records` keeps the copy's old count so
  `wide_copy_sites` still finds its constants).
- `retire(table)` and the engine's `_retire_menu_rows`: a Write with no setting of ours reads the program's header,
  and only when an earlier Write left its text extension segment the whole program, and takes every row of ours off
  (staged program or in place with the `.sidx` overlay, as the score colours).
- `editions.in_program` finds EDITION on whichever page lists it: since PAD-1382 round 5 it sits on Custom Code (15),
  not Attract Mode, and Multi-boot refused every image the app wrote with EDITION (`test_pad495_editions` was red on
  main for it).

## Proof (emulator, Godzilla LE 1.16, rig 1)

Set A by `engine.write_overrides` (EDITION, CO-OP PLAY in the menu, HANDICAP), then CO-OP PLAY alone planned from A's
program with main's planner and this branch's (`C:/tmp/PAD-1394/mkset.py`, `run.sh`, `menushot.sh`):

- main: Custom Code lists Edition, Co-op Play, Handicap.
- branch: Custom Code lists Co-op Play only; the game boots and walks the menu with the shorter table.
- none wanted (`retire`): the table is the game's own 107 records again and Machine Settings has no Custom Code page.

Tests: `tests/test_pad1394_retire_rows.py`.
