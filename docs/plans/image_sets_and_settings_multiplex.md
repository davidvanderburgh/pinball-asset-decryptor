# Image sets, and multiplexing the app's own service-menu settings: a handoff

For David's Claude. Written by Simon's Claude on 2026-11-17, from work on the branch
`feature/image-sets-v1495` of `simonpaterson-oss/pinball-asset-decryptor` (rebased on v1.495.0; the older
`feature/image-sets` there is stale). Nothing here is merged; it is offered for review. Every claim below is either
proven in the emulator (said so) or marked unproven.

## 1. What was asked

Simon (Godzilla Premium 1.16, a Heisei retheme) has drawn the Kaiju Battle Select screen (`auto_loaded/cac32730...`)
dark and wants the card to offer the players "a dark or light or perhaps even multiple versions" of a screen, picked in
the service menu or on the start menu, remembered over a power cycle. In PAD: a Scenes tab switch that makes a second
(or nth) variant of a scene, starting as a copy of the scene as the project has it, then given its own pictures and
colour profile. One setting picks the set for every scene that has a variant (agreed: global, not per scene).

## 2. What is built (branch above, 5 commits after v1.495.0)

**Runtime** (`pad_mode_runtime.c`, section "IMAGE SETS", `scnv_*`). Reads `scenes.cfg`
(`/usr/local/padmode/` on a card, `/dump/` in the rig):

    only
    got      eglSwapBuffers <addr>          the game program's import slot (a fopen64 line is read, not needed)
    setting  <live addr> <n sets>           IMAGE SET's value in memory; 0 = none (the last start's set stays)
    scene    <id>/scene.radium <set> <file> a scene whose path ends so is opened as <file> while the set says <set>;
                                            a bare file name is beside the scenes.cfg that was read
    force    <set>                          a rig run's own set (never written by a build)

- The object **exports `fopen64`**, its only exported symbol, the way `hwshim.c` interposes it, and calls on to
  `dlsym(RTLD_NEXT)`. Re-pointing the game program's own `fopen64` import slot was tried first and never saw a scene:
  scenes are opened by libstdc++'s `std::ifstream` through libstdc++'s own import. Unarmed (any process of the preload
  that is not the game, or no `scenes.cfg`) it is a plain call-through.
- `auto_loaded/` scenes are read at boot, before the game has read its settings, so a start shows the set the game
  LAST ran with, kept in `/dump/pad_imageset.state` (the picture settings' PAD-575 pattern). `eglSwapBuffers` is
  re-pointed (chained after the picture settings) to note the setting once a frame and rewrite the state on change.
  A scene opened after boot (demand loaded) takes the setting as it is now.
- A variant file that does not open falls back to the scene's own, logged once. The first three scene paths the game
  opens are logged, for a path that never matches. Spike 2 only (`scnv_arm` returns on `PM_A64`).
- `prebuilt/mode.so` and `mode64.so` rebuilt; the stock v1.495.0 sources reproduce the committed objects byte for
  byte with Ubuntu's arm-linux-gnueabihf-gcc 13.3 / aarch64-linux-gnu-gcc, so the rebuilds are like for like.

**App** (`plugins/stern/scene_variants.py`, new). Sidecar `.staged_changes.json` key `scene_variants`:

    {"names": ["Dark", "Light"], "scenes": {"<scene card path>": {"2": {"file": "<path>"} | {"card": true}}}, "force": 2}

`stage()` finds the import slots (`picture_settings.import_slots` with this module's symbols), writes each variant as
`scn_<first 12 of the id>_<set>.radium` and `scenes.cfg`. The engine gates it like the other runtime features
(`_scenes_for_build`: an image file, a host that can add files) and stages it before the mode plan; `mode_write.plan`
carries it (a plan of its own, `scenes_plan`, when nothing else of the runtime's is on), `p2_payload` puts it in the
extras; `tryit.sh install` copies `scenes.cfg` and `scn_*.radium` into `/dump` and clears old ones; `mode_install.py`
takes `scenes.cfg` and any `scn_<12 hex>_<n>.radium` and removes an earlier install's. `tests/test_image_sets.py` (7
tests) holds the two sides to one table; the touched suites pass (386 + the new ones).

**Proven in the emulator** (Simon's PC, his Heisei 2.3 card, Emulate "apply my replaced assets on top"): with set 2
forced, Battle Select was drawn from a red-tinted copy of `cac32730` (`mode.log`: `image sets: armed - 2 set(s), 1
scene file(s) ... this start shows set 2 (FORCED by the file)`, and the screen red).

**Not built yet:** the IMAGE SET setting (see 3), the Scenes tab variant UI (variants are hand-made files today), a
card Write test. Also open: `/usr/local/padmode` is on p2 and `mode_install` refuses a payload p2 cannot hold; a
re-imaged Battle Select is 26-66 MB on this card, so variants may need to live on the games partition beside the scene
instead (the `.sidx` append path the modes' new files use) - not measured yet.

## 3. The blocker: no spare setting left

IMAGE SET needs a value the operator can change. Every setting of ours takes over a DEPRECATED adjustment
(`menu_settings.spare`). Read off Simon's card's program (`AdjustmentTable` + `spare()`):

    AD_FLASHER_MAX_BRIGHTNESS  35  'CO-OP PLAY'
    AD_LED_MAX_BRIGHTNESS      33  'HANDICAP'
    AD_GI_MAX_BRIGHTNESS       31  'MUSIC MODE'

All three are taken. The limit is game-wide, not per page: a category record can list a setting on any page; the
scarce thing is the adjustment and its NVRAM slot.

## 4. David's question: can the settings be multiplexed, e.g. several custom ones as one JSON value?

Not as JSON inside a setting: an adjustment is one 8-byte `.nonvol` record the menu edits as one number between its
min and max by its step, with a fixed help string. Bit-packing several values into it fits the bytes but the operator
would step through one meaningless number. Three ways that do work:

**A. Combinations in one row (works with today's machinery).** `MAX_VALUES` is 8, so two Off/On features share a row:
CO-OP PLAY + HANDICAP as "Off / Co-op / Handicap / Both". Frees one adjustment. Cost: both features' runtime code reads
the shared value (co-op's and handicap's `live` checks), and it only scales to a few booleans. HANDICAP is not co-op
only (DoomWalrus666 asked for it "on single player or multiplayer"), so the row must keep both independent.

**B. A selector row and a value row, the values kept as JSON in `/dump`. The real multiplex.** Two adjustments become
PAD SETTING (which option: 1 = Image set, 2 = ...) and PAD VALUE. The runtime already reads live values once a frame:

- PAD VALUE changes -> the runtime saves it as the selected option's value in `/dump/pad_settings.json`;
- PAD SETTING changes -> the runtime writes that option's saved value into PAD VALUE's live word, so the menu shows it;
- every feature reads its value from the JSON (the image sets' `/dump/pad_imageset.state` becomes one key of it).

Two adjustments then serve any number of options, and MUSIC MODE, CO-OP PLAY, HANDICAP and the picture settings could
move onto it, freeing the rest. **Unproven, and the thing to test first:** whether the menu shows a value the runtime
writes into the live word under it (or draws a copy it cached when the row was entered), and whether the game's own
NVRAM write-back or range check fights it. The JSON is the truth, so the game's own store does not have to agree.
Also: help strings are fixed, so the help line lists the options ("1 Image set, 2 Music mode, ...") rather than naming
the selected one, and PAD VALUE's min/max is one range for every option (the widest; the runtime clamps per option).
Suggested probe: on Godzilla 1.16, take one spare adjustment, have the runtime write a different value into its live
word while the operator is on its row, and watch the menu (emulator first).

**C. Outside the service menu.** The runtime keeps the value in `/dump` (JSON) and draws its own chooser - an entry on
the start menu, as PAD-686's MODE CHALLENGE does on Godzilla. No adjustment at all; a player picks Dark/Light where they
pick their game, and `/dump` keeps it over a power cycle. This is what Simon's Claude proposed for image sets on a card
with no spare setting; it is the most new runtime code of the three.

## 5. Recommendation and questions for David

- B is a framework change of yours that every future runtime setting benefits from; it reads better as its own ticket
  than inside the image-sets PR. If the probe in B passes, image sets would take an option on it.
- Until then the image-sets PR can ship with IMAGE SET as an ordinary spare-setting row where one is free (cards
  without all three of music modes, co-op and handicaps), C for a card with none - or wait for B. Which do you want?
- Is `/dump` the right home for a runtime's persistent JSON (it already holds `pad_picture.state`), or is there a place
  you prefer?
- Variants on p2 vs beside the scene on the games partition (`.sidx` append): preference?

## 6. Reproducing the emulator proof

1. Branch `feature/image-sets-v1495`; run the app from it (`python -m pinball_decryptor` in a venv with the three
   requirements files).
2. Godzilla Premium/LE 1.16 project; sidecar key as in 2, with `"force": 2` and set 2 a whole `scene.radium` file
   (Simon's was the card's `cac32730` with its two top-level nodes tinted `[1, .25, .25, 1]` via `scene_edit.apply_scene`).
3. Emulate with "Apply my replaced assets on top"; the override log names `scenes.cfg, scn_cac32730af42_2.radium`; the
   game's `/dump/mode.log` says `image sets: armed` and the screen shows the variant.

## 7. PAD-1390: on main, on the shared rows

David took the branch onto main after PAD-1382 built option B of section 4 (MORE SETTINGS + a value row, the values in
`/dump/pad_settings.state`; `docs/plans/pad1382_more_settings.md`). So the blocker of section 3 is gone:

- **IMAGE SET is one of the app's settings** (`menu_settings.IMAGE_SET`, `engine._ImageSetMenu`): 1..n by the sets'
  names, 1 to start with, planned with music mode, edition, the picture settings, co-op and handicap
  (`service_menu.arrange`). A spare row of its own where there is one; else one more option on MORE SETTINGS. No
  IMAGE SET (no room at all): the variants are left off the card, said in the log - nothing could pick one.
- The build stages `scenes.cfg` after the menu is planned and writes the address the menu gave it on the `setting`
  line (a row's `.nonvol` word, or `0xFADE0000 + 4k`); the runtime takes it through `setting_addr()` like every other
  reader. `pad_imageset.state` stays: it is the set the game LAST ran with (auto_loaded scenes are read before the
  settings), the shared value is the operator's pick.
- At most 8 sets (`MAX_SETS = menu_settings.MAX_VALUES`, a menu setting's ceiling); the runtime's table holds 16.
- The Service menu tab lists Image Set (on while the project has image sets); a Spike 3 build says image sets are
  left out. `scene_variants` (and `bank_songs`, missing since PAD-1378) are in the Linux/macOS `--hidden-import`s.
- **Proof** (emulator, Godzilla LE 1.16, `artifacts/PAD-1390/emulator`): co-op, handicaps, the three picture settings
  and image sets Standard/Red (set 2 = Battle Select `cac32730` tinted red) - six settings on three spare rows. The
  Custom Code page: MORE SETTINGS -> 6 makes the row under it **Image Set 1**, help "1 = Standard, 2 = Red"; set 2:
  `pad_settings.state` `image_set 2`, the runtime "IMAGE SET 2 ... kept for the game's next start". Power cycle:
  "this start shows set 2" and `auto_loaded/cac32730.../scene.radium opened as set 2's /dump/scn_cac32730af42_2.radium`.
- Still open from section 2: the Scenes tab's UI for making a variant (today a sidecar entry naming a scene file) and
  where big variants live (p2 vs the games partition).
