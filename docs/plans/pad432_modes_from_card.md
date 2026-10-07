# PAD-432: modes from one card image into another card's project

David, 2026-10-07: "a simple one-click type operation that allows us to export / import modes
from another image (and from another version or model)". First use: our modes onto a tester's
Godzilla Premium 1.16 Heisei custom image, again for every new version of that image.

## What was already there

- Save / load (PAD-281, PAD-402): a project's modes to a `.zip` (`pad_modes.json` + each
  `modes/<slug>/` folder) and back, with conflicts and a backup. Loading retargets through
  `copy_modes` (shots by name, then by switches within a game; PAD-396 model ports).
- Copy to... and Port to... between two projects.

So project to project was one save and one load. The gap was the IMAGE: nothing read modes off
a card, and a written card held only what the runtime reads (`mode.so`, `mode*.cfg`,
`game.port`, `<slug>.assets`, `stock.cfg`).

## The design call

**Write carries the project's modes on the card**, as `/usr/local/padmode/pad_modes.zip`
(`MP.CARD_BUNDLE`), in the Save to a file format, with a manifest `"from"` naming the card's
title, words and file (`MP.card_about`).

- Size: every settings and source file always (about 30 KB a mode); the pictures, clips and
  sounds smallest first only while they fit `mode_write.CARD_BUNDLE_MEDIA` (8 MB). The rest are
  named in the manifest's `"left_out"`. Why: p2 has about 194 MB free, shared with a multi-boot
  card's selector media, and `cardmodes.sh` pulls the whole folder out of the card on every
  emulator boot; a film-cut set runs 80-170 MB (survey, 2026-10-07).
- `mode_install.py --bundle`: placed when p2 has room beside the rest, else left off with a
  `[mode]` line saying why (an install never fails for it). It is in `ALL_FILES`, so a Write
  without one and a removal take it off.
- Multi-boot: `read_mode_set` skips it (`PADMODE_BUNDLE`); the other images' sets do not need it.
- The runtime never reads it.

**Load modes from a card image...** (`modes.load_card`, `mode_from_card.card_modes_file`),
what is ON THE CARD first:

1. The card's `pad_modes.zip`, read with the pure-Python ext4 reader (no WSL; 0.03 s on an 8 GB
   card, off the UI loop): the modes as they were written. When the card's build record
   (`<card>.pad-build.json`) names a project still on this PC, that project only puts back the
   pictures, clips and sounds the file was too small to carry (`fill_left_out`); whatever is
   still missing is named per mode in the message.
2. A card written before cards carried that file, built on this PC: the build-record project's
   modes as the project is NOW, and the message says so.
3. Otherwise: form modes rebuilt from `mode*.cfg` through the card's own `game.port` (name,
   start shot and count, length, scoring shots, award, stacking, starts, cooldown, lights; the
   Advanced keys it does not carry are named), and code modes whose slug is one of the app's
   examples restored from the app (as shipped; Cut from films makes their media). Any other
   code mode cannot come back (its C is not on the card) and the message says so.

A card with no `/usr/local/padmode` carries no modes, build record or not.

Then the load runs as Load from a file does (conflicts dialog, backup, retarget, report), and
the box names the card the modes were made for. **Save a card image's modes to a file...**
writes the same file without loading it.

Copy to / Load now marks a mode "to fix" when every shot carried but `validate` still refuses
it on the new card (survey gap G1: an event Pro 1.16 does not report, a missing file).

## Proof (2026-10-07)

- Godzilla Pro 1.15 stock + KAIJU RUSH, MECHA HUNT (form) and KING GHIDORAH (code example),
  written by this branch: the card carries `pad_modes.zip` (33 KB); it boots on a hidden muted
  rig and arms its modes with the file beside them.
- With the build record hidden (so the card itself is read), loaded into a stock Godzilla
  Premium/LE 1.16 project and a project of the Heisei Custom V1.96A image: all three carried
  (other model and version) and were written.
- Premium/LE 1.16 card: boots, arms them, and on the rig KAIJU RUSH started (its screen up) and
  ran out its clock, and KING GHIDORAH started with its HUD (heads, lit head moving).
- Heisei V1.96A card (the third-party custom image, 16G): written and armed; on rig 2 it
  reached the retheme's own attract page in 290 s, a game started, KAIJU RUSH started (its
  screen over the Heisei playfield) and ran out its clock, and KING GHIDORAH started with its
  HUD, the lit head moving LEFT -> MIDDLE -> RIGHT (`C:\tmp\PAD-432\heisei_proof\`, driven by
  `playwait432.sh`, which waits for attract by the rig log's video sources). An earlier reading
  of "stays on the Stern logo" was an instrument error: glshot's PNGs are all 3,134,511 bytes
  at 1360x768, so a frame-size test never told attract from the logo, and only the first run
  was genuinely starved (0.9 frames a second while two other rigs ran). Main's own Write of the
  same card behaves the same, so nothing here is this ticket's.
- A real older card (PAD-301's 6-code-mode LE 1.16 build): with no bundle, its build-record
  project is taken (note says so); with that off, path 3 restored all six as the app's examples.

## Left (not in this ticket)

From the survey, still open: code modes are copied without retargeting their C or `block_modes`
(G5; the report's "a build says if X lacks a shot" is not true today), model/version changes do
not clear a ball save or events the new card lacks (G2; G1 now reports them as "to fix"),
callout ids across Metallica/Deadpool versions (G3), mechanisms on another title (G4),
`modes/stock.json` does not travel with Save to a file or the card file, multi-boot image N
cards are read as their primary only.
