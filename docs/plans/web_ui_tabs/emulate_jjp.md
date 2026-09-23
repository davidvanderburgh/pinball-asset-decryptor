# Emulate JJP tab (web port) - status

Owner files (ns `emulate_jjp`, which also owns the Spike 1 Emulate tab, see
`emulate_spike1.md`):

- `pinball_decryptor/webui/tabs/emulate_jjp.py` - the service (`EmulateJJPTab`)
- `pinball_decryptor/webui/emulate_jjp_common.py` - what the JJP and Spike 1
  services share: rig switch-off, logging from workers, the shared Volume /
  Mute control file, the status poller, the streamed launch, the footer ladder
- `pinball_decryptor/webui/static/js/tabs/emulate_jjp.js`
- `pinball_decryptor/webui/static/js/tabs/emulate_jjp_shared.js` - volume
  knob, state chip, intro lines (used by both tabs)
- `pinball_decryptor/webui/static/css/tabs/emulate_jjp.css` (the Spike 1
  sheet `@import`s it)
- `tests/test_webui_emulate_jjp.py`

Tk source: `gui/jjp_emulate_tab.py` (`JJPEmulatePanel`), the seam
`main_window.py:_build_jjp_emulate_tab`, the ladder
`MainWindow.EMULATE_PHASES_JJP`, the app-quit `emulate_shutdown`.

## Approach

The service is its own class (no Tk object is built). The panel's logic is
ported method by method with its wording; every RIG FACT is the Tk module's
own function, called through the module so a test can stub it:
`rig_available`, `rig_cmd`, `rig_cmd_root`, `state_text`, `key_failure`,
`key_on_pc`, `attach_dongle_cmd`, `usbipd_path`, `HASP_VID_PID`,
`rdp_client_running`, `stop_left_nothing`, `hide_rig_ghosts`, and the
panel's `_FOOTER_STEPS` / `_RESTORE_PCT` / `POLL_*` constants. Status
parsing and `CREATE_FLAGS` are `gui/_rig.py`'s; the control file is
`gui/emulate_tab.py`'s `AUDIO_CTL_FILE` / `_load_audio_ctl` /
`_write_audio_ctl`.

Workers are threads; everything they change comes back through
`ctx.loop.post` (the Tk panel's `after(0, ...)`).

`PAD_UI_NO_RIG=1` (tests, captures): no poll, no launch, no stop, no WSL
restart, no usbipd, no volume-file seed - each action logs "the emulator rig
is switched off in this session (PAD_UI_NO_RIG)" instead.

## Ported (by Tk section)

- Intro label: the PageHead text, both lines.
- Image row: "Game ISO" card, the path field (the window variable
  `jjp_emulate_iso_var`, exported), its tooltip (also shown as the help
  line), "Browse..." (`Select a JJP game ISO`, `JJP game image *.iso`),
  recent paths from the shell's path history.
- Controls: one Start / Stop toggle (Starting... / Stopping... with a
  spinner while a start or stop runs, greyed when the rig is missing), "Fix
  stuck state" NEXT TO Start (Tk's deliberate placement) with its tooltip,
  its Windows-only info box, its confirm text, "Resetting..." (with its own
  spinner; Start is only greyed, as the Tk button was) while
  `wsl --shutdown` runs, then a re-poll. The live Volume slider + Mute on the
  shared control file, with the Tk tooltip; the file is seeded at start and
  re-read when the tab shows (the other Emulate tabs move the same knob).
- Start: the "Pick a JJP game ISO first." box, the key attach
  (`wsl -e true` wake, visible check, `usbipd attach` x2, `bind` on "not
  shared", 12 s wait, every log line), the streamed `watch.sh` launch as
  root with `PAD_AUDIO_CTL`, 1800 s bound, each line logged as printed,
  `watch.sh` step headers and `sdaN: NN%` moving the footer ladder, a key
  verdict (`NO KEY:` / `KEY NOT ACCEPTED:` / legacy `WRONG KEY`) pulled into
  the headline the moment it prints and kept sticky over the next polls,
  exit 7, "start failed (exit N)", and the WSLg `msrdc.exe` warning.
- Stop: `stop.sh` as root, its output logged, the ghost-window sweep after a
  stop that left `matrix=0 xephyr=0`, the "hid N window(s)" line.
- Auto-attach: one shot per drop, re-armed when the key is visible again,
  with its three log lines and an immediate re-poll - whichever manufacturer
  is on screen, as in Tk.
- Headline + hint: the Status card's chip (tone: ok running, warn for the key
  / WSL faults) and the hint under it; the sticky key verdict.
- Status grid: all 11 cells with the Tk formatting (yes/no, "%.1f GB",
  "m:ss", windowed/desktop, "N device(s)" / none, "in / out").
- The orange note: rig missing, running without boards, key in the PC being
  handed over, no key.
- Footer ladder "Restore image / Boot / Game / Ready" when the tab shows;
  the poll drives it (run = Ready, `selector_procs` = Game "Boot menu
  showing...", else idle); only the showing tab's updates land (the window's
  `set_emulate_progress(tab=...)`).
- Polling: as the Tk panel, FROM APP START and for every manufacturer (Tk
  built this panel for every manufacturer and polled from `build()`): 700 ms
  first, 2 s while up, 10 s idle, never stacked, skipped while a start/stop
  is in flight; `key_on_pc` asked only when WSL cannot see the key. Showing
  the tab takes a reading older than 2 s again at once, so Start / Stop
  never acts on a state up to 10 s old (better than Tk, whose worst case was
  the 10 s idle period).
- App quit: `emulate_shutdown` (the window fans it out) stops the rig as
  root, bounded, when a game or the CUSE daemons were seen - including a
  terminal-started run or one left by an earlier session that this session
  never showed.
- Multi-boot "Run in emulator": `launch_iso(path)` on the service (the
  multiboot service calls `window.service("emulate_jjp").launch_iso`), with
  the busy refusal line.

## Owed / differences

- `_open_matrix` (jjpsw_launch.sh) had no control in the Tk tab, so none here.
- Not run against the real rig or a real key (the rig is David's): the
  launch, stop, attach and restart paths are tested with stubbed processes.
- macOS / Linux builds: not captured by this port (the lead's
  `webui-builds` workflow); on those platforms the tab behaves as Tk's did
  (Fix stuck state says Windows only, Start logs that usbipd is missing).

## Core requests

1. **Move the Tk-free helpers out of `gui/` before it is deleted.** Both
   emulate services import, from Tk modules: `gui/_rig.py` (whole module),
   `gui/emulate_tab.py` (`AUDIO_CTL_FILE`, `_load_audio_ctl`,
   `_write_audio_ctl`, `windows_python`), `gui/jjp_emulate_tab.py`
   (`rig_dir`, `rig_available`, `rig_cmd`, `rig_cmd_root`, `usbipd_path`,
   `HASP_VID_PID`, `rdp_client_running`, `rig_ghosts`, `stop_left_nothing`,
   `_desktop_windows`, `hide_rig_ghosts`, `attach_dongle_cmd`, `key_on_pc`,
   `key_failure`, `state_text`, `JJPEmulatePanel._FOOTER_STEPS`,
   `_RESTORE_PCT`, `POLL_*`), `gui/spike1_emulate_tab.py`, `gui/spike1_windows.py`
   and `gui/_runtime_ui.py` (see emulate_spike1.md). A mechanical move to a
   Tk-free home (e.g. `core/emu/`) keeps one definition; until then the web
   build must still bundle `tkinter` (the modules import it at the top).
2. **Per-tab emulate ladder in the window.** Tk's `_on_tab_changed` picked
   the ladder by tab key (Spike 1: Extract/Boot/Node boards/Ready, JJP:
   Restore image/Boot/Game/Ready, Stern: EMULATE_PHASES). The web window
   has one `_phases["emulate"]`; these tabs set theirs in `on_show` and put
   the default back when their manufacturer goes away. A
   `PHASES_BY_TAB_KEY` in `window._show_row_for_tab` would make that
   unnecessary (and protects the Stern tab from a stale ladder).
3. **Done in this round, in a core file** (`static/js/core/dialogs.js`,
   `PromptModal`): the prompt dialog answered Cancel with the field's text
   (the Field's blur-commit replied on Cancel's mousedown). It now answers
   only on Enter (with what is in the box at that moment) or OK; Cancel and
   Escape answer None. Every `compat.simpledialog` caller had it. Checked in Edge with
   `compat.simpledialog.askstring`: Cancel after typing / untouched -> None,
   Enter straight after typing -> the typed text, Escape -> None, OK -> the
   text.

## How it was checked

- `python -m pytest -o addopts="" -p no:cacheprovider tests/test_webui_*.py -q`
  -> 583 passed, 1 skipped (2026-09-22; `test_webui_emulate_jjp.py` +
  `test_webui_emulate_spike1.py` = 65 of them, also green 3 runs in a row
  and under `-n 4`).
- `scripts/webui_shot.py --mfr jjp --tab emulate_jjp` (1440x900,
  `--width 1024 --height 700`, `--theme light`): 0 JavaScript errors.
- Edge, in-process with injected rig states
  (`scratch/fix_emulate_jjp/verify.py`, dark 1440x900 and light 1000x760):
  the core prompt cases above; Start keeps no spinner while Fix stuck state
  runs and Fix stuck state spins; Start spins while starting. 0 JavaScript
  errors.
