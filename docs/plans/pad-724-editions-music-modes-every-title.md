# PAD-724: Editions and music modes on every title

From PAD-722's list: EDITION (PAD-495) and MUSIC MODE (PAD-494) were Godzilla 1.16 only. Both put a setting of the
app's own in the game's operator menu (`menu_settings`); music modes also wrap the game's sound resolver at run time.

## What each title needed

Measured on the newest build of every Spike 2 title (53, the library), 2026-10-25:

| | Titles | What it took |
|---|---|---|
| Category-table menu (Adjustments > Machine Settings > pages) | 32 | nothing new: the same 107-record table and the same DEPRECATED adjustments (ids 31, 33, 35) as Godzilla |
| Older menu: Standard Adjustments + Feature Adjustments | 21 (Aerosmith Pro/LE, Elvira 3, Foo Fighters LE/Pro, Guardians/LE, Led Zeppelin LE/Pro, Mandalorian LE/Pro, Munsters LE/Pro, Rush LE/Pro, Sword of Rage LE/Pro, TMNT LE/Pro, Venom LE/Pro) | `menu_settings.StandardList`: the page's `u16` id list, reached through a `movw r0 / movt r0 / bx lr` getter, copied one row per setting longer into the program's extension segment and the getter pointed at the copy. Our rows are the last of Standard Adjustments (#96 MUSIC MODE, #97 EDITION on Aerosmith). The DMD shows a row's caption and value, not its help, so the modes' names are not on the machine there |
| No room to grow the program | 3 (James Bond 007 LE 1.06, James Bond 60th 1.11, Star Wars LE 1.31) | none possible: no address space is free between their code and data, and program-text growth never maps above .bss (`engine._text_reloc_plan`). Every other longer-text edit of those programs is refused the same way. Their Pro twins (Bond Pro 1.06, Star Wars Pro 1.31) have the room and both settings |
| The sound resolver (`get_asset_descriptor`) | 53 | found on each card by `sfx_names._find_resolver` (the candidate that hands back a magic-5 descriptor: 399 of the first 400 sound ids on every build), added to every newest port as `site sound_resolve`, recipes rebuilt |

Two things only the sweep showed:

- **Avengers Infinity Quest Pro 1.10's sounds could not take a music mode.** Its play tables use key mask
  `0xF80001FF` (measured: 1554 of 1554 records named), but Godzilla's `0xFC0003FF` names 799 of them by the bits the
  two share, and `engine._desc_key_mask` kept a known mask unless the measured one named three times as many. Now a
  measured mask that names nine in ten records wins over a known one that does not. The same rule decides which
  descriptors a longer replacement re-points, so half of Avengers Pro's sounds could not be re-pointed either.
  Munsters LE 1.28 was the same (`0xF80003FF`, 3115 of 3115, where the known mask named 1557). On the other 48 the
  rule picks what it picked before: 13 use a known mask that names every record, 35 one measured as before.
- **Category pages appear only when something lists them.** Batman has no Audio Content page until MUSIC MODE is on
  it; Godzilla has one of its own. The sweep walks Machine Settings from the bottom (the page list wraps), which
  every title shares: Test Menu Settings, Attract Mode, Audio Configuration, then Audio Content.

## The menu, by family

- Category table: Adjustments > Machine Settings > Audio Content, row 1 = Music Mode (its help names the modes);
  Attract Mode, row 6 = Edition (after the five system rows every title has).
- Standard list: Adjustments (the ADJ icon) > Standard Adjustments; Minus from row 1 wraps to EDITION, again to
  MUSIC MODE. Select, Plus, Select sets a row to 2 ("2 (INSTALLED)").

Either way the game wrote the value into a new generation of `/data/nv/<title>/NVM` (keyed SHA1 of the caption, as
the multi-boot selector and the runtime read it).

## Proof: the emulator sweep

Kit `C:/tmp/PAD-724/sweep` (job.py, run724.sh, menu724.sh, nvread.py, verdict.py). For each of the 50 builds:

1. **Build** with Write's own code (`engine.write_overrides`) a one-slot project: a short sound only one request plays
   replaced by a 500 Hz tone; MUSIC MODE with three modes, mode 2 a 1000 Hz tone and mode 3 2000 Hz; EDITION with two
   editions. The build log must say both settings went into the operator menu.
2. **Run** it on a rig (hidden, muted, 1x), the set bound over the cached stock card, with the fire instrument
   (`mode_file.c` + `sound_fire_mode.c`) and the set's own game.port and sounds.cfg. MUSIC MODE and EDITION are put
   back to 1 in the rig's NVM store first (value, check and the generation's crc32).
3. In attract, fire the request twice; walk the menu (`menu724.sh`), set MUSIC MODE and EDITION to 2, leave it; fire
   twice again; read the NVM mirror.
4. **Pass** = the half second after each of the first two fires is the 500 Hz tone, after the last two the 1000 Hz
   tone (the game's own PCM, `audio.raw`), and the store holds MUSIC MODE = 2 and EDITION = 2.

The edition's own boot (codeselect reading EDITION and booting that image) is the boot program's, the same on every
title; PAD-495 proved it on Godzilla, and the sweep proves each title's menu takes and stores the setting it reads.

Results: **50 of 50 pass** (each run's `VERDICT.txt` in `runs/<build>/`): on every build mode 1's two fires played the
500 Hz tone, mode 2's two the 1000 Hz tone, and the store held MUSIC MODE = 2 and EDITION = 2. Where a build took more
than one try, the earlier tries were the menu walker's (keys pressed before a page had drawn, or a row count that was
wrong for that title, or a fresh store sitting in Guided Setup), fixed in `menu724*.sh` / `run724f.sh`; the set was the
same.

Afterwards every set was rebuilt from the committed code and compared file by file with the one the sweep ran: the
game program, image.bin, the sound index, sounds.cfg and game.port were byte-identical on all 50 (only
`overrides.delta`'s per-build generation id differs).

| Build | Menu | Tries |
|---|---|---|
| aerosmith-1.16 | Standard list | 1 |
| aerosmith_le-1.16 | Standard list | 1 |
| avengers_infinity_le-1.10 | Category table | 1 |
| avengers_infinity_pro-1.10 | Category table | 1 |
| batman-1.14 | Category table | 1 |
| beatles-1.29 | Category table | 1 |
| deadpool_le-1.16 | Category table | 1 |
| deadpool_pro-1.16 | Category table | 1 |
| dungeons_and_dragons_le-1.10 | Category table | 1 |
| dungeons_and_dragons_pro-1.10 | Category table | 1 |
| elvira3-1.13 | Standard list | 1 |
| foo_fighters_le-1.04 | Standard list | 1 |
| foo_fighters_pro-1.04 | Standard list | 1 |
| godzilla_le-1.16 | Category table | 1 |
| godzilla_pro-1.16 | Category table | 1 |
| guardians-1.15 | Standard list | 1 |
| guardians_le-1.15 | Standard list | 1 |
| iron_maiden_le-1.18 | Category table | 1 |
| iron_maiden_pro-1.18 | Category table | 1 |
| james_bond_pro-1.06 | Category table | 2 |
| jaws_le-1.02 | Category table | 1 |
| jaws_pro-1.02 | Category table | 1 |
| john_wick_le-1.02 | Category table | 1 |
| john_wick_pro-1.02 | Category table | 1 |
| jurassic_park_le-1.16 | Category table | 1 |
| jurassic_park_pro-1.16 | Category table | 1 |
| jurassic_park_the_pin-1.05 | Category table | 2 |
| king_kong_le-0.97 | Category table | 1 |
| king_kong_pro-0.97 | Category table | 1 |
| led_zeppelin_le-1.22 | Standard list | 1 |
| led_zeppelin_pro-1.22 | Standard list | 1 |
| mando_le-1.45 | Standard list | 1 |
| mando_pro-1.45 | Standard list | 1 |
| metallica_spike-1.04 | Category table | 3 |
| munsters_le-1.28 | Standard list | 1 |
| munsters_pro-1.28 | Standard list | 1 |
| rush_le-1.19 | Standard list | 1 |
| rush_pro-1.19 | Standard list | 1 |
| star_wars_elg-1.10 | Category table | 2 |
| star_wars_pro-1.31 | Category table | 1 |
| stranger_things-1.13 | Category table | 1 |
| stranger_things_le-1.13 | Category table | 1 |
| sword_of_rage_le-1.19 | Standard list | 1 |
| sword_of_rage_pro-1.19 | Standard list | 1 |
| turtles_le-1.59 | Standard list | 1 |
| turtles_pro-1.59 | Standard list | 1 |
| uncanny_xmen_le-0.98 | Category table | 3 |
| uncanny_xmen_pro-0.98 | Category table | 2 |
| venom_le-1.07 | Standard list | 1 |
| venom_pro-1.07 | Standard list | 1 |
| james_bond_le-1.06, james_bond_60th_le-1.11, star_wars_le-1.31 | (no room to grow the program) | not run |
