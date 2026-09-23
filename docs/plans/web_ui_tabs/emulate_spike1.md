# Emulate Spike 1 tab (web port) - status

Owner files (ns `emulate_spike1`, owned together with the JJP Emulate tab,
see `emulate_jjp.md` for the shared pieces and the core requests):

- `pinball_decryptor/webui/tabs/emulate_spike1.py` - the service
- `pinball_decryptor/webui/emulate_jjp_spike1view.py` - the display feed,
  the switch model and the two native windows (`ViewWindows`, Tk's
  `Spike1Viewers`)
- `pinball_decryptor/webui/emulate_jjp_common.py` - shared with the JJP tab
- `pinball_decryptor/webui/static/js/tabs/emulate_spike1.js` - the tab, and
  `mountView()` for the two windows
- `pinball_decryptor/webui/static/js/tabs/emulate_spike1_view.html` - the
  windows' page (`?view=display` / `?view=switches`)
- `pinball_decryptor/webui/static/css/tabs/emulate_spike1.css`
- `tests/test_webui_emulate_spike1.py`

Tk source: `gui/spike1_emulate_tab.py` (`Spike1EmulatePanel`),
`gui/spike1_windows.py` (`_RunDirIO`, `Spike1DisplayWindow`,
`Spike1SwitchWindow`, `Spike1Viewers`), the seam
`main_window.py:_build_spike1_emulate_tab`.

## Approach

As for JJP: the service ports the panel method by method with its wording;
the rig facts are the Tk modules' own (`rig_dir`, `rig_available`,
`rig_distro`, `rig_cmd`, `rig_cmd_root`, `state_text`, `_EVENT_LOGS` and its
caps, `_load_dmd_decoder`, `_load_alpha`, the panel's `_STATES_TIP`,
`PAYLOAD_KEYS`, `DEFAULT_AUDIO`, `_fmt_size`, `_fmt_when`, `_human_kb`,
`_parse_cache`; `spike1_windows.wsl_unc`, `_RunDirIO`, `KEY_TABLE`,
`SVC_KEYS`, `SVC_ORDER`, `PULSE_S`, `SWITCH_COLS`, `DEFAULT_NODES`), and
`core.payloads` / `core.rigdata` / `core.runtime` / `gui._runtime_ui` do the
installing exactly as the Tk tab called them (`_runtime_ui` asks with
tkinter's messagebox / filedialog, which `compat.install` points at the page;
nothing is patched per call any more).

The DMD and switch / LED windows are native windows again, as in Tk: while a
game runs, `ViewWindows` opens two more pywebview windows on
`emulate_spike1_view.html` (the display at +80+80, 940x300 / 920x250 for the
16-segment models, titled "Spike 1 — DMD" / "Spike 1 — display"; the switch
panel at +80+360, "Spike 1 — switches / LEDs"). They stay up whichever tab or
manufacturer is on screen, can go to another monitor, reopen on the next poll
if the user closes one (Tk's `Spike1Viewers.open` on every poll), the display
window is replaced when the machine turns out to be the other kind (PAD-101),
Reset windows restores / moves / raises them, and they close with the run and
at quit. Every pywebview call is made on `ViewWindows`' own thread, never the
UI loop: at quit the GUI thread sits in the main window's closing handler
waiting for the loop, so a synchronous window call there would hang the quit.
Without a native window (`--browser` / `--serve`) the tab draws the two as
cards instead (the previous port's behaviour).

Either way the page polls `view_frame` (50 ms) and `view_state` (80 ms) with
`@rpc(loop=False)` calls, so the 20 Hz display never goes through the event
stream. The frame is rendered the Tk way (amber dots for the DMD,
`s1alpha.render_image` + the game's font for the 2012 home models'
16-segment displays) into a PNG the browser scales with hard pixel edges.
Clicks, right-clicks, the play keys, the service cluster, the coin door and
the trough go to the same run-dir files (`s1sw.input`, `s1ball.cmd`).

## Ported (by Tk section)

- Intro label (PageHead).
- Card row: "Card image (extracted once, then kept)", the path field (the
  window variable `spike1_emulate_card_var`, exported) with its tooltip,
  "Browse..." (`Select a Spike 1 card image`, `*.img *.raw *.vhd *.iso`),
  "Cache..." (Windows-only info box elsewhere).
- Button row: Start emulator / Stop (Starting... / Stopping... with a
  spinner), Restart WSL... (Windows only, its confirm, "Restarting..." with
  its own spinner; Start is only greyed, as in Tk), Reset windows (logs
  "nothing running", or restores / moves / raises the two windows and
  reopens a closed one; cards: scrolls them into view), Check setup...
  (read-only report lines, Windows only), Fix setup (runtime -> payloads ->
  prereqcheck.sh; the blocked-download "choose a file" offer for both the
  binaries and the runtime image; greyed only off Windows, so an incomplete
  tools/spike1_emu still gets the Linux and the binaries, as in Tk) and its
  right-click menu (also a caret beside it): Delete the emulator's data...,
  Delete downloaded files..., Remove the app's Linux... with the Tk
  questions and log lines. Volume + Mute (shared control file, live).
- Start: the no-card box, payloads installed before the launch, the "old
  extraction" note, the data disk (and its nearly-full line), the first-run
  build line, `start.sh` as root with `PAD_AUDIO=1`, `PAD_AUDIO_CTL`,
  `PAD_AUDIO_SINK=relay`, `S1_PIVOT=1`, streamed, exit 2 guidance, exit N.
  While a first extract runs the State reads "Extracting the game..." and
  the ladder's first chip lights (the Tk code meant to; its poll was skipped
  while busy so it never showed).
- Stop: `stop.sh` as root, the speaker stopped.
- The app-side Windows speaker (`padplay.py` against the rig's relay, the
  title's `s1audio` rate, 5 s relaunch backoff).
- Save states: the table (Slot / Name / Game / Size / Saved; columns drag
  to resize, kept for the session like the Tk Treeview's), Save now (not
  running box, then Tk's `simpledialog.askstring("Save state", "Slot name
  (letters, digits, _ . - only):", initialvalue="quicksave")` through
  `compat.simpledialog`, the name rule and its error), Load, Refresh,
  Rename... (askstring "Rename slot" / "Name for <ref>:" with the current
  label; Cancel renames nothing), Delete (confirm), the summary line,
  re-list on `saves_mtime` change, the Windows-only line, the (i) tip text.
- Status grid: State / Processes / Game CPU / memory / DMD frames / Boards
  registered with the Tk formatting; the grey hint; the note (rig missing,
  Windows-only, running-and-registered).
- Footer ladder "Extract / Boot / Node boards / Ready" driven by the poll.
- Polling from app start for every manufacturer and era, as the Tk panel
  (see emulate_jjp.md), so a run this session never showed is seen, its
  windows open and the app quit stops it (Tk's `shutdown_sync`: a game or
  the responder); showing the tab re-reads a status older than 2 s at once.
  The poll that first sees a run also reads the display kind and the switch
  names off the run dir (off the loop), so the display window opens as the
  right kind.
- Rig event logs streamed into the log (the Tk filters, 12 lines per file
  per second, 300-char clip, attach at the end of a long file).
- The display: DMD / alphanumeric, "waiting for the game to draw...",
  the PLAYER 1 / PLAYER 2 readouts from the game's font.
- The switch panel: Start / Plunge / Drain / Ball in / Ball out / Coin; the
  named switch LIST by node (click = pulse 350 ms, right-click =
  hold/release, hover names it) or, for a title with no map yet, the raw
  matrix grid with lamp and coil sections once the decoder writes them
  (theme colours: light cells in the light theme); the map re-read every
  poll so late names are adopted; the KEYBOARD panel (rows dim when the
  title does not name the switch, inverse when made), the service cluster
  (dead on the early era with "no service buttons on this machine"), the
  coin-door bar (or "TEST MODE: hold both flippers 3s"), the trough balls and
  shooter; the readout line. The play keys (arrows, 1, 5, T, F, Enter, -, =,
  Backspace/Esc, C, B) work anywhere in either window (Tk bound them on the
  Toplevels; on the cards, while a card has focus); a window losing focus
  releases held keys.
- Cache window: the Tk intro, Game / Card / Size / Last used / active table
  (resizable columns), the summary, Refresh, Delete selected (never the
  active one, with the Tk question), Close.
- App quit: `emulate_shutdown` closes the windows (without waiting) and the
  tail and stops the rig when a game or the responder was seen.

## Owed / differences

- Not run against the real rig (David's); every rig path is tested with
  stubs or refused under `PAD_UI_NO_RIG`. The windows were checked live in
  the native host with every window HIDDEN and a fake run dir
  (`scratch/fix_emulate_jjp/native_probe.py`), and their page in Edge.
- Window sizes are fixed defaults (Tk sized its windows to their canvas and
  did not remember them either); both are resizable.
- macOS / Linux: the tab is Windows-only exactly as in Tk (note shown, Start
  and Fix setup greyed, slots disabled); not captured on those builds here.
  The windows need a native main window; `--browser` / `--serve` get the
  cards.

## Core requests (in addition to emulate_jjp.md's)

1. `gui/spike1_emulate_tab.py`, `gui/spike1_windows.py` (`wsl_unc`,
   `_RunDirIO`, the `Spike1SwitchWindow` / `Spike1DisplayWindow` tables) and
   `gui/_runtime_ui.py` are imported by the web service: move them (Tk-free
   parts) with the rest before `gui/` is deleted.
2. (Optional) a core "open a tab component in its own window" helper: the
   Spike 1 windows are done tab-locally (`ViewWindows` + its own view page);
   if another tab needs one, the pattern (a worker thread for every
   pywebview call, the origin from `host.window.original_url`, a view page
   that calls the tab module's `mountView`) can move into the host.

## How it was checked

- `python -m pytest -o addopts="" -p no:cacheprovider tests/test_webui_*.py -q`
  -> 583 passed, 1 skipped (2026-09-22). The Spike 1 tests now keep the run
  dir's `\\wsl.localhost` paths in a local folder (opening a distro's UNC
  path starts that distro).
- `scripts/webui_shot.py --mfr stern --era spike1 --tab emulate_spike1`
  (1440x900, `--width 1024 --height 700`, `--theme light`): 0 JavaScript
  errors.
- `scratch/fix_emulate_jjp/verify.py` (Edge, in-process, fake run dir; dark
  1440x900 and light 1000x760): Save now with Enter straight after typing
  saves that name; Cancel on Save state / Rename does nothing; a bad name
  shows the rule; OK renames; the Name column drags wider and stays; Start
  has no spinner during Restart WSL and Restart WSL spins; the view page
  (`?view=display`) draws the DMD, ArrowLeft holds the flipper in
  `s1sw.input`, and it keeps drawing with another tab and manufacturer
  showing; `?view=switches` draws the named list, right-click holds a
  switch, Enter sends `svc select`; light theme: open cells and dead service
  buttons are light. 51 checks, 0 failed, 0 JavaScript errors.
- `scratch/fix_emulate_jjp/native_probe.py` (the real native host, every
  window hidden, blank settings, rig off): both windows open after
  `webview.start()`, the display draws the DMD, the switch window the named
  list; they stay up with another manufacturer; an alpha machine replaces
  the display window; a window closed by the user is noticed and the next
  poll reopens it; the app quits at once with both windows open. 9 checks,
  0 failed.
