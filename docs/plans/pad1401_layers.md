# PAD-1401: several of my modes running at once (layers)

From the PAD-1398 gap analysis, rows 5 and 13: a whole new game (Uncanny X-Men 2.0) needs a game-long mode
with the maker's own modes stacking on it, and multiballs and wizards over those. Before this, `pm_begin` kept
every mode of ours to one at a time, and PAD-1400's whole-game mode left "your own modes inside it" undone.

## The design

- **Runtime** (`pad_mode_runtime.c`, `pad_mode.h`): `running` stays the one BASE mode (`pm_begin`). A mode that
  begins with `pm_begin_layer(priority, flags)` is a LAYER: up to 8, ranked by priority, the later begun over
  at the same one, all over the base. `pm_running()` is true for a layer, so every "only the running mode may"
  check (magnet, coils, shaker, building, shield, spare outputs, game light shows) lets a layer use it.
  - shots: `deliver_shot` calls our running modes top-down first, then every other mode (start counts);
    `pm_shot_claim` / `pm_shot_taken` keep a shot from the running modes under the one that claimed it.
  - pause: `PM_LAYER_PAUSE_BELOW`; the modes under read `pm_paused()`.
  - lights: an insert a higher layer holds stays its; a lower one's paint goes into PAD-601's under-list, kept in
    layer order, and is handed down when the layer lets go.
  - screen: `pm_layer_top()`; display priority asks are kept per mode and handed back to the one under.
  - the base keeps the game's-modes hold (a layer asking never takes it), the whole game and the backdrop; the
    held mechanisms are let go when no mode of ours runs any more (`layers_end_lets_go`).
  - `pm_mode_running_named` (what `inside` waits for), `pm_layers`, `pm_as` (below).
  - with no layer running every order, owner and check is what it was.
- **Mode files** (`mode_file.c`): `layer <priority> [pause] [shots]`, `inside <name>`. Runner 0 is the object
  itself (the base, the files, the triggers); up to 7 layered files run at once, each on a runner of its own: an
  unregistered `pm_mode` the calls are made as (`pm_as`), whose `.shot` the runtime calls in its layer's place.
  `run` is per runner (`runners[R_]`). Layers are not offered for roster/challenge/place/wizard modes or the
  whole game (the base).
- **Blocks** (`block_modes.py`): `layer`, `layer_priority`, `layer_pause`, `layer_takes_shots`, `inside`; the C
  begins with `pm_begin_layer`, stands still while `pm_paused()`, returns from `.shot` on a taken shot, claims
  them with TAKES_SHOTS, ends when its `inside` mode ends, and hands its screen, HUD, info line and the game's
  bar over by `pm_layer_top()` (`layer_glass`). A layer does not count as "another of ours in the way".
- **The app**: Blocks: "With my other modes, it runs" row under the game's modes; the form: a "My other modes"
  section. Both list the project's other modes for "inside".

## Proof

- Desk: tests/test_pad1401_layers.py (13: blocks on the desk harness - shots claimed, lights under and back, a
  child ending with its parent, a wizard pausing the base, one-at-a-time unchanged; mode files on the roster
  harness - the same; the form's lines and checks). The existing suites that lift the runtime's functions were
  pointed at the new ones (`mode_start_in`, `run_shot`, `layers_end_lets_go`).
- Emulator, Uncanny X-Men LE and Pro 0.98 (hidden, muted, 4x; C:/tmp/PAD-1401 layerjob.sh, run2): FUTURE the
  whole game (mode file, the base), STORM (mode file, priority 20, inside FUTURE, keeps the shots, on Left ramp
  tgt), PHOENIX (mode file, priority 50, pauses the ones under it, on Right ramp tgt), WOLVERINE (blocks,
  priority 30, on Xjet tgt), all in one object. Both pass. LE 3 balls / Pro 5: every layer began and ended each
  ball; 0 of the base's 42 / 70 awards came while STORM held the shots; nothing under PHOENIX was paid while it
  ran and STORM's clock stood still for its 6 s; screens and HUDs waited under a layer and came back.
- The pinned objects (prebuilt/mode.so, mode64.so) are rebuilt; the a64 build compiles the layers clean.
