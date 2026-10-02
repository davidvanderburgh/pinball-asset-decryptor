# PAD-323: lay out a mode's screen in the Scenes editor

David, 2026-10-02 (PAD-314, Ales's Metallica picture): "shouldn't we have the option to layer
the wall image below the HUD? and placement of where the score text shows up? ... a scene
editor link ... instead of just deciding for the user how we present the mode".

## What it does

- The Modes tab's Show page (and a code mode's Assets page) has **Lay out on the screen...**.
  It opens the Scenes tab on the title's HUD scene with the mode's screen in it as virtual
  layers (`webui/scene_mode_layout.py`): a group `PadMode_<slug>_Screen` holding the picture
  (or generated panel, band and all, exactly as the build makes it) and the words, at the
  automatic placement (`mode_assets.screen_place`).
- The editor's own tools work on it: drag or size the picture (that moves or sizes the whole
  group, as the build places the group), move or size the words on their own, re-order the
  group among the HUD scene's root children (Send to back = under the HUD's own pictures).
  Hide, rotate, tint and remove are refused with a sentence: the picture, colours and words
  are the Modes tab's.
- Every edit is turned at once into the mode's `screen_layout` (only what differs from the
  automatic placement) and saved into `mode.json` / a code mode's `assets.json`, keyed by the
  mode's folder, never into `scene_edits.json` (whose node ids a mode's screen does not keep:
  they are handed out at build in slot order). Undo/Redo step over the layout; As shipped on
  the picture or the words, or **Place automatically** in the banner, takes it back out.

## The build

`mode_assets.form_screen` / `code_screen` give the automatic screen; `with_layout` lays the
mode's `screen_layout` over it (`x`, `y`, `scale`, `words_x`/`words_y`, `words_scale`,
`order`). `scene_write.screen` writes `scale` into the group's matrix and `words_scale` into
the words'; `scene_write.add_screens` puts a screen with an `order` just before that stock
root child (`root_children`: the scene walked by `scene_tree.parse`, offsets moved onto a
grown bank scene with `_moved_at`), the rest at the profile's measured place as before.

**Why not an `order` edit after the splice**: a build refuses a project whose other edits
touch the HUD scene the modes go into (`mode_write.conflicts`), and the modes are always
built from the STOCK HUD, so the mode build is the only place the order can be decided.

A scene whose classes the first screen registers (`SceneProfile.new_poly`: Avengers, Bond)
keeps every screen at its measured place: a class must be named before it is used.

A mode with no `screen_layout` builds byte for byte as before (test). A layout change is a
rebuild (`screen_layout` is not in `SETTINGS_ONLY_FIELDS`); an old record with no key and a
new file with `{}` count as the same.

## Proof

- `tests/test_gui_mode_screen_layout.py`: the editor flow end to end on a synthetic scene.
- `tests/test_stern_mode_assets.py`: the layout keys, byte-identical without one, and on the
  real Godzilla Pro 1.15 HUD (skipped without the corpus) `order` 0 makes the screen the
  first root child with its scale and words where they were put, other modes unmoved.
- `scripts/shot_pad323.py`: before/after shots of the Show page and the Scenes editor, and
  with `--rig` a Try it on Godzilla Premium/LE 1.16 on rig slot 3 (hidden, muted).
