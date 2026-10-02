# Machine screen profile (PAD-324)

## Why

The Scenes preview's "As on the machine" (PAD-312) draws a frame through the whole screen overlay and then through a model of the machine's LCD. That model was the individual files profile run backwards. It defaulted to Recommended, so it was on by default, but it could not be adjusted on its own: the only knob was a correction that also changes what is baked into the files. Setting that correction to No change switched the preview's screen off too, and a black and white correction cannot be undone, so a monochrome screen could not be shown at all.

A tester asked for the smallest proof first: expose that default so it can be changed, and change nothing else.

## What phase 1 does

- `core/colour_profile.py`: a third profile, `screen_profile` in `.staged_changes.json`. `machine_view` applies it forwards after the overlay when one is stored. With none stored it undoes the individual files profile exactly as before, so existing projects look the same.
- `Profile.inverse()`: the forward profile that stands in for `undo_array`, used to show the default on the sliders and for the Recommended screen preset. Exact on greys; colours are close because the saturation mix runs before the shades, not after.
- Color profile tab (Spike 2 only): a third mode, "Machine screen (preview only)", with Recommended screen, No change, Black and white and Same as individual files. Same sliders, preview, Save a copy and Load.
- Preview only. The Write tab lists nothing for it, and Revert all keeps it (`stock_modes.kept_by_revert_all`), since it describes the user's machine rather than a change to the card.

## Phase 2, only if phase 1 proves out

- "Correct for the machine screen" on Adjust individual files (the correction = the screen's inverse), and the reverse bridge.
- The screen's name beside the Scenes tick.
- Whether "Every replaced picture / video" should start ticked.
