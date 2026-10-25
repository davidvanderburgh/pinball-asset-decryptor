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

Results: see the table below (filled from `runs/*/VERDICT.txt`).
