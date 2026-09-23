# Multi-boot tab (web port) - status

Owner files: `pinball_decryptor/webui/tabs/multiboot.py` (service),
`pinball_decryptor/webui/multiboot_panel.py` (the Tk panel run headless),
`pinball_decryptor/webui/static/js/tabs/multiboot.js`,
`pinball_decryptor/webui/static/css/tabs/multiboot.css`,
`tests/test_webui_multiboot.py`.

Visible for: Stern (Spike 2 era only) and JJP - the `multiboot` capability,
exactly as Tk's `_configure_tab("Multi-boot", caps.multiboot)`.

## Approach (read this first)

The Tk tab is `gui/multiboot_tab.py:MultibootPanel` (7 600 lines of
orchestration on top of ~5 900 lines of pure functions). Re-writing the
orchestration would be a second copy of the build / apply / update / load /
recover / plan / preview / sound pipelines, so the web tab RUNS THE TK PANEL
ITSELF, headless:

* `multiboot_panel.py` rebuilds `MultibootPanel`'s methods over a copy of the
  module's globals (`_rebind_class`), in which `tk` is a shim whose
  `StringVar`/`BooleanVar`/`DoubleVar` are `webui.compat`'s, `messagebox` /
  `filedialog` are compat's (the pickers remember their folder per title),
  and the four Tk dialogs (`ImageEditorDialog`, `MenuSettingsDialog`,
  `BuildFlashDialog`, `CardPickDialog`) are web proxies with the same
  constructor shapes. Nothing in `gui/` is patched or edited; the Tk tab and
  its tests are untouched.
* The panel's `after` jobs run on the web UI loop (`_Parent.winfo_toplevel()`
  is a `compat.Root`); its worker threads hand back through its own queue
  exactly as in Tk.
* The methods that PAINT widgets are overridden to mark a part of the page
  state dirty (`_draw_checks`, `_draw_size`, `_update_menu_summary`,
  `_pv_say`, `load_frame`/`_decode_photo`, `_play_start`, `_blackout`,
  `_show_alarm`, `_update_row_label`, `_sync_*`, `_set_busy`, `_say`...);
  `_flush` publishes the dirty parts into the `multiboot` store namespace on
  the next loop turn. The images table is a headless `_WebTable` with
  `ImageTable`'s selection semantics. Every decision (checks, card path
  state, size view, write plan, validation, blockers, confirmations,
  messages) is still the Tk code's.
* The panel's variables are mirrored into the store (`mirror()`), so the
  page's field edits go through `var.set` and the Tk traces fire (preview
  re-render, edit status, summary...). Only the card path, Compact build and
  the preview's Volume / Mute are BOUND; the Edit image… and Menu settings
  fields are published but reach their variable through `on_field`, and
  only while their dialog is open (Tk's grab: an edit that lands after
  Cancel / Escape is dropped, see "Review fixes").
* Preview: the selector's own PPM frame is converted to a PNG in the temp
  dir (`pad-webui-multiboot`, pruned to 96 files) and served by /media;
  each card's rendered `anim<N>.gif` is laid over the rectangle the selector
  reported, so the browser plays the clips (Tk composited them with Pillow
  at 30 fps). The LOADING beat of Select is an overlay. Before a frame
  exists a SKETCH of the menu is drawn from the form in the menu's own
  colours (the design), tagged "sketch · not drawn by the selector yet".
* Sound: the Tk tab's own `PreviewAudio` plays on the host, as before; the
  page tells the panel when the tab is on screen (mount / unmount /
  `visibilitychange`) = Tk's `<Map>` / `<Unmap>`.
* `PAD_UI_NO_RIG=1` (tests, captures) refuses every tool run, the card
  reader read and the menu write-back, and turns the automatic preview and
  size check off.

## Ported (by Tk section)

* Source row: label per platform, path box (Enter reads via `_path_committed`,
  click-in re-probes via `_refresh_facts`), From SD card… (Stern), Browse…
  (`_browse_card`: save-as picker, existing file = discard confirm + read),
  New card (confirm), (i) About badge (Stern / JJP text). The Card-image
  check's sentence is shown under the path (was tooltip-only).
* Version alarm banner (`version_alarm`), full finding as tooltip + Log.
* Preview: frame + clips + LOADING beat, flippers (wrap, move sound, table
  follows), Select (confirm sound, random re-roll caption), arrow keys on the
  picture, Video:/Audio: readouts, caption (red on failure, full text),
  Volume slider + Mute (preview_audio_ctl.json), placeholder text.
* Status checks: four chips (ok / now / no / bad colours) with the
  `status_checks` sentences as tooltips, platform labels.
* Images table: columns Title | Subtitle | Picture | Music | Confirm | Code
  at the design's widths (the title takes the room: "SURPRISE ME (random, 3
  sets)" is whole at 1280 and 1440 wide), a compact set in a narrow card
  (Title / Subtitle | Picture | Sounds | Code; the Sounds header's tip says
  Music · Confirm sound; header cells clip, never overlap), ▲▼ / ✎ / ✕ per row (greyed at the
  ends and while a run is up), a click opens Edit image…, Enter opens,
  Up/Down walk rows, right-click = `LIST_ACTIONS` menu, the add button's menu
  = `add_row_choices()` with the reasons in the labels, an add row when
  empty, the dim source line under the table (`_cell_image` / ROW_HINT).
* Size strip: need head, bands (image / free (+ hatched saved) / overhead /
  overflow), thinking sweep + meter fraction, sentence in full with the
  why-paragraph as tooltip, band list tooltip, click = re-measure, Compact
  build (Stern; forced + greyed with a random group).
* Action bar: Menu settings… with the summary shown as Menu / Countdown /
  Sounds lines (menu_summary's parts), Build / flash card… (becomes Cancel /
  Cancelling… during a run), Run in emulator, Recover images… (Stern; live
  per `recoverable()`).
* Edit image… dialog: title/source line, Title, Subtitle, Shows (kinds per
  platform + "Keep the card's own…"), Picture/Video file + Browse… (picking
  a file picks the option), media note, How it picks (radios + forced tick
  + note) for random cards, Music / Confirm sound (editable, ▾ words + used
  sounds, Browse…, ▶ Play), confirm note, the card preview (picture file,
  rendered art, or a video's first frame via ffmpeg off the loop), OK /
  Cancel (snapshot restore).
* Menu settings dialog: every option (move / confirm sounds + Play, volume
  0-N, machine volume tick (Stern), the sounds paragraph with the own-confirm
  note, Heading, same text size, card counter, Theme, 14 colours with
  swatch picker + hex field (Make your own… only, bad values flagged),
  Countdown (s), Countdown says + live example, Default image), OK / Cancel.
* Build / flash dialog: the `_write_plan()` tick + detail (apply / update /
  build / refused), the flash tick + platform text, "no finished card" line,
  Start (disabled until a tick) / Cancel; refreshed when the dry-run lands.
* Read an SD card dialog: drives listed off the loop, reason line, menu-only
  / whole-card radios, Refresh / Read / Cancel.
* Phase ladder + progress + status line: the panel's `phase_fn` / `status_fn`
  are `window.set_multiboot_phase` / `window.set_status`; tool lines go to the
  shared Log with the panel's tags.
* Dialog keys as Tk's `_Modal`: Return anywhere in Edit image… / Menu
  settings is OK and in Build / flash card is Start (only with a tick on);
  the typed value is sent first and OK waits for it. Escape and ✕ cancel;
  a click on the dim area does nothing (Tk's grab), and Escape is heard only
  by the dialog on top.
* Menu settings' Volume (0 to the cap: 100 Stern, 40 JJP), Countdown (s)
  (0-600) and Default image (0 to images-1) are number boxes with Tk's
  Spinbox bounds.
* Keyboard: Left / Right on the picture AND on the two flipper buttons (not
  Select, as Tk); the menu key / Shift+F10 on the focused table, or a
  right-click on its empty space, pops the list menu over the selected row
  (ImageTable's `_canvas_context`).
* `window._multiboot_panel` is the panel: `state()` / `restore_state()` for
  app.py's multiboot_state / save / restore, `image_titles()`, `on_shown()`.
  The tab is ALWAYS built: when the panel cannot load (no tkinter in a
  build) or cannot be constructed, the export is a `_SavedForm` that keeps
  the document app.py restored and hands the same one back, the page says
  "The Multi-boot tab could not start (…)", and every page call refuses
  with that sentence. (Without an export, App.multiboot_state() was {} and
  the next quit / project switch / Save wrote {} over the project's form.)
* Platform switch (Stern <-> JJP) via `set_platform` in `on_manufacturer`.

## Owed

* Flash and Run in emulator are wired to the Write tab's
  `_open_flash_dialog(initial_image, fresh, image_titles)` and the Emulate
  tabs' `launch_card(path, select=True)` / `launch_iso(path)` (both landed
  2026-09-22; the hand-offs are tested with stubs). If either tab fails to
  load, the tab says so instead ("The SD-card flash dialog is not
  available…", "[multi-boot] the Emulate tab is not built…").
* Not exercised against the real rig (by rule): a real render, build,
  apply, update, load, recover, card-reader read and menu write-back. The
  code paths are the Tk panel's own; the web-specific parts (frame -> PNG,
  clip overlay rectangles, LOADING overlay, dialogs, busy/cancel states) are
  covered by tests and captures with a real rendered frame read-only.
* Browse… (the card path) in the DESKTOP window uses the page's own save
  picker, not the native one: pywebview's native save panels ask
  "replace?" for an existing file and cannot be told not to, which Tk's
  confirmoverwrite=False exists to prevent. Every other picker on the tab is
  native. When the host honours the flag (Core request 4) it sets
  `native_file_dialog.honours_confirmoverwrite = True` and the tab goes
  native again by itself.
* DATA (repaired 2026-09-23 00:03): `gzho/.pinproj` held `"multiboot": {}`,
  written 2026-09-22 22:14:31 by a scratch web run (native_win.py) whose
  build had no Multi-boot panel, so App.multiboot_state() was {} on its
  quit. A project's value wins even when empty (App.restore_multiboot_state),
  so both apps would have opened gzho with an empty tab. The key was
  removed (backup: `C:/tmp/gzho_repair/pinproj.backup-2026-09-23.json`), so
  gzho now restores settings.json's `multiboot_state` (the 4-image form).
  Capture runs set PAD_UI_CAPTURE, which skips every quit-time write.
* Tk's tooltips on the flipper / Select / Volume controls are hover tips
  here too; the table's hover underline is not reproduced (rows highlight on
  hover instead).

## Core requests

1. CUT-OVER: do NOT delete `gui/multiboot_tab.py`, `gui/multiboot_backend.py`,
   `gui/multiboot_docker.py`, `gui/preview_audio.py`, `gui/_rig.py` or what
   `multiboot_tab` imports at module level (`emulate_tab` for
   `rig_dir/wsl_account/wsl_home`, `placement`, `theme`, `widgets`) - the
   web tab runs that module's logic (`gui/image_table.py` is NOT needed). Move them out of `gui/` (or keep them) and
   keep tkinter in the frozen builds while `multiboot_tab` imports it at
   module level (build.ps1 / build_linux.sh / build_macos.sh bundle it today).
2. (done by the Write tab) `_open_flash_dialog(initial_image, fresh,
   image_titles)` exported on the window.
3. (done by the Emulate tabs) `launch_card(path, select=True)` on `emulate`,
   `launch_iso(path)` on `emulate_jjp`.
4. host.native_file_dialog: honour `confirmoverwrite=False` (a WinForms
   SaveFileDialog with OverwritePrompt=False on win32; NSSavePanel / Qt
   cannot, so return NotImplemented there and the page's picker answers),
   then set `native_file_dialog.honours_confirmoverwrite = True`. The tab
   works around it for its own Browse… today (multiboot_panel
   `_save_without_replace_prompt`).
5. compat `_Var`: a public `bind(store, ns, key)` to mirror an existing var
   (multiboot_panel.mirror sets `_store/_ns/_key` directly today).
6. PyInstaller: `webui.tabs.*` are imported dynamically (tabs/__init__.py);
   make sure the builds collect them (multiboot's own helper module is
   imported from tabs/multiboot.py inside a try, so name it as a hidden
   import too).
7. WebApp.multiboot_state(): a backstop for a Multi-boot service that is
   not there at all (its TabService base failing, or the window skipping
   it): with no `_multiboot_panel`, answer what is SAVED (the open
   project's anchor `multiboot` when the key is present, else settings'
   `multiboot_state`), never {}. The tab covers every failure of its own.
8. core Table: a LAST column given in plain px is stretched to
   minmax(0,1fr) and splits the slack with the title; the tab gives its
   action column `minmax(46px,46px)` to keep it at its buttons' width.
9. core Modal: a `grab` prop (no close on the dim area; Escape only when on
   top) and an `onEnter` prop would replace the tab's `grabbed()` /
   `okOnEnter()` (the Tk `_Modal` semantics every dialog tab needs).
10. scripts/webui_shot.py (and any scratch runner): after copying settings,
   point every manufacturer's extract_output / write_assets / write_output,
   projects[].folder and project_dir at scratch copies of their anchors, or
   a capture opens the real project (its Write change scan rewrote
   gzho/.hashcache.json; a graceful close rewrote gzho/.pinproj). A WebApp
   that skips the quit-time anchor and settings writes under PAD_UI_NO_RIG
   would be the backstop.

## How it was checked

* `.venv\Scripts\python -m pytest -o addopts="" -p no:cacheprovider
  tests/test_webui_*.py -q` -> 582 passed, 1 skipped (40 multiboot). The
  tests assert no tool is ever started (the panel's subprocess is replaced
  with one that fails the test).
* `scripts/webui_shot.py --settings <copy> --mfr stern --era spike2 --tab
  multiboot`, `--mfr jjp`, `--width 1024 --height 700`, `--theme light`: 0 JS
  errors. The copy's project folders are scratch copies of their anchors
  (Core request 10), so no capture opens a real project.
* Scratch in-process driver (`scratchpad/webui/scratch/multiboot/flows.py`):
  the restored global form (4 images incl. a random card), a real rendered
  frame read-only, a size plan, version alarm, add menu, Edit image (plain +
  random), Menu settings (+ Make your own…), Build / flash, Read an SD card,
  row right-click menu; at 1440x900 and 1024x700, Stern and JJP; 0 JS errors.
* Found and fixed: the Edit dialog opened before the deferred selection had
  loaded the row, so the focused Title field kept the previous row's title.

## Review fixes (2026-09-22)

* KNOWN REGRESSION ("the web tab is empty where Tk showed 4 images"): the
  restore code is right; the data changed under it (see Owed, DATA). With
  an anchor that has no `multiboot` key the web tab restores the card path
  and all 4 rows (`test_startup_restores_the_global_form_when_the_anchor_
  has_none`; Edge capture on a scratch copy of the anchor); with `{}` it is
  empty, as Tk (`test_a_projects_empty_form_wins`). The code weakness that
  wrote the `{}` is fixed: the tab is always built and keeps the restored
  form when its panel cannot be (`test_quit_without_the_panel_keeps_the_
  saved_form[import|construct]`).
* Cancel / Escape / a click on the dim area no longer let a late edit into
  the row or the menu (`test_a_late_edit_after_cancel_is_dropped`,
  `test_a_late_menu_edit_after_cancel_is_dropped`; Edge: QQ + Escape at
  once, SS + dim-area click, YY + Escape at once -> nothing kept).
* Return = OK / Start, number boxes, flipper-button arrows, the table's
  menu key / Shift+F10, the column widths, the narrow header: Edge drive on
  scratch settings (every project folder a scratch copy of its anchor),
  1440x900 and 1024x700, 0 JS errors; the Build dialog's Start request was
  intercepted in the page and never reached the app.
* Browse… never asks "replace?" in the desktop window
  (`test_browse_never_asks_replace_in_the_desktop_window`).
