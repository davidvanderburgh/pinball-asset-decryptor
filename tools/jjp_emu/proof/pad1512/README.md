# PAD-1512 proof: a wizard mode, its progress board and a game type on Wonka 03.03

Wonka's Sentinel key attached (`usbipd attach --wsl --hardware-id 0529:0001`), then as root in Ubuntu,
hidden and muted:

    bash run.sh        # rc 0 = every wait in steps.txt met; the log is copied to jjpmodes.log

The runtime is built first against Wonka's glibc (`JJP_MODS_SO`, default `/var/tmp/pad1512/jjpmodes.so`,
`buildmods.sh` with `JJP_MODS_LIBDIR`), and the probe's C++ with `mkjjpmodes.py code --modes modes`.

What it shows (MODES.md "A wizard mode and a game type"):

* **The game type menu.** In attract, both flipper buttons held 1.6 s open it; the right and left buttons
  move through NORMAL GAME, WIZARD GAME and PRACTICE GAME; coins and Start start the game with PRACTICE
  GAME picked, and PRACTICE starts on player 1's first ball.
* **start_all.** The test hook starts three of the game's own: Candy Lane (`cl_mode`, named by its
  global), Mike Teavee (`MikeTeaveeMode`, by its class) and the Gobstopper multiball (`gobstopper_mb`);
  each counts for player 1, the progress board shows when each ends, and the third raises WIZARD's start,
  made as the multiball ends. While WIZARD runs the game's Candy Lane is held off, and player 1's plays
  toward it start again from none.
* **The C++ callback.** `probe.cpp` (API 2) logs every start and end with `jm_player` and `jm_played`
  by global and by class.

## The menu's look (`look/`)

    bash look/run.sh   # rc 0 = the restyled menu opened and moved; shots look_menu*.png in /var/tmp/pad1512

`look/modes/title.cfg` restyles the game type menu with title.cfg keys alone: its box on the right
(`game_type_at = 58 10 38 76`), a frame picture of ours under it (`menu_frame.png`, made by
`look/make_frame.py`) with the panel and bars off, Wonka's own menu fonts (`font_player_menu_title`,
`..._item`, `..._small`), its own colors, heading, normal line and hint. Run 2026-11-23: every wait met,
`game type menu: picture menu_frame.png 520x584` in the log, each line centred in its row.
