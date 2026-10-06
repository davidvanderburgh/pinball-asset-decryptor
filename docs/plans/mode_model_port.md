# Modes between a game's Pro and Premium/LE (PAD-396)

## The ask

David, 2026-10-05: *"When making modes, we need to easily be able to port from one model of the
game to another (pro to premium and back). We should have alternate rules or mech adjustments
between the two. No one is going to want to remake all of their modes from one to another. We
should have an automated way of handling this (like one-click port to pro)."*

## What went wrong before

A mode made on a Godzilla Premium/LE 1.16 card and taken to a Pro 1.16 card (Copy to..., Load
from a file, or opened/built in a Pro project) was matched by shot NAME only:

- The Premium's "Shield ramp spinner" is the Pro's "Right spinner" (the same switch, 0x20000), and
  the Premium's "Shield target center" is the switch the Pro calls "Shield target right"
  (0x100000000). Both were "not a shot on Godzilla Pro 1.16": the mode came over "to fix" and a
  build refused it until the shots were picked again by hand.
- The bridge and the Mechagodzilla magnet (Premium/LE only) were carried over silently. Once saved
  on the Pro, `validate_coils` refused it ("Godzilla Pro 1.16 has no mechanism called 'bridge'").
- Going back lost the Premium's choices: whatever had been changed for the Pro was the mode.

## What it does now

`mode_project.retarget` (which Copy to..., Load, opening in the tab and every build go through)
first runs `_port_model` when the target is the same game (`title_family`):

1. **Shots by switch.** A shot name the target lacks goes to the target's one shot on the same
   mask (`shot_twin`), in every field that names a shot (`_map_shots`). Any version or model of the
   same game; masks mean the same switches within a family.
2. **Another model (`other_model`: `_pro` beside `_le`/`_premium`):**
   - the mode's `MODEL_FIELDS` (its shots and the mechanisms it holds) are kept in
     `spec.models[<old model>]`;
   - if `spec.models[<new model>]` exists (the mode was on that model before) it comes back as it
     was left there; else the mechanisms the target cannot hold are left out (held coils it does
     not have, the magnet or scoop where `cannot` says so);
   - `spec.ported` records what the port made, so an edit made since can be told from it.
   - Everything else (name, clock, points, screen, clip, sounds, lights) is the same mode on every
     model.
3. `retarget_words` says it: "Shield ramp spinner is Right spinner on Godzilla Pro 1.16; Godzilla
   Pro 1.16 does not hold the bridge or the Mechagodzilla magnet, so they are left out there; its
   Premium/LE shots and mechanisms are kept in the mode for when it goes back".

**Port to Pro / Port to Premium/LE** (Modes tab, under the list, beside Copy to...): shown on a
title with a model word. Its menu lists the app's known projects (`project_registry`) whose card is
the same game on the other model (`port_targets`), plus "Another project...". `port_modes` is
Copy to... with `replace=True`: a mode ported there before is replaced (asked first), and if its
shots/mechanisms were edited there since the last port (`ported` differs), they are kept as that
model's version (`_keep_their_model`). So: make on the Premium, Port to Pro, tune the Pro's shots
there, keep editing on the Premium, Port to Pro again - the Pro keeps its own shots, gets the rest.

## Not done

- Mechanism substitution (e.g. "on the Pro, hold the scoop instead of the bridge") is not
  automatic: the Pro's version is whatever is set in the Pro project, kept across ports.
- Only Godzilla's Pro and Premium/LE ports exist today with differing shots; other titles
  (Deadpool Pro/LE, TMNT, Led Zeppelin) get the same matching from their port files.
- Machine-proven: not needed for this change (no runtime line changes); the desk tests build
  validated specs for both models from the real port files.
