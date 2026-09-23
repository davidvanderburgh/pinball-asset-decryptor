# Web UI: the whole app off Tk

## What and why

David, 2026-09-22: "i want to do the whole app. changing to a 'web based' app gives us better flexibility in the UI and allows us to use CSS". Then: "bundle whatever we need to continue to run it as a native app", "i'd rather do a cut-over release. use this feature branch as the base", "implement them all for each tab and each manufacturer ... we cannot have any regressions ... make this responsive, or give the ability to change the global zoom ... test the macos and linux builds".

The designs are the canvas "Pinball Asset Decryptor web UI" (claude.ai artifact 9Yom3LeiGogqwGmKJPLN5p): a left rail grouped Card / Replace / Make / Build / Inspect / Play, a top bar with the project and the era switcher, a status bar with the phase ladder, a log drawer, IBM Plex type, one amber accent, dark by default.

This branch is based on `feature/emulate-prepare` (the emulator's prepare pipeline), as David asked.

## Design

### No regression by construction

The run logic stays exactly as it is. `pinball_decryptor/app.py` (`App`: extract, write, flash, revert, transfer, port, update, projects, settings) was carried over unchanged; only the Tk parts were swapped (at the cut-over the web constructor was folded into `App` itself, so there is one class and no Tk):

| Tk piece app.py used | Web replacement |
|---|---|
| `tk.Tk()` root: `after`, `after_cancel`, `title` | `webui/compat.py:Root` on `webui/loop.py:UiLoop`, one thread with Tk's semantics, including a modal wait that keeps the loop turning |
| `tkinter.messagebox` | `compat.messagebox`: the page's modal, same return values |
| `tkinter.filedialog` | `compat.filedialog`: pywebview's native panels, or the page's own browser |
| `StringVar` / `BooleanVar` + `trace_add` | `compat.StringVar` & co, mirrored into the store so the page shows and sets them |
| `MainWindow` | `webui/window.py:WebWindow` + one tab service per tab |

`tests/test_webui_core.py::test_every_window_attribute_the_run_logic_reads_exists` reads every `self.window.X` in app.py and fails when any is not provided, for every manufacturer.

### The cut-over (David, 2026-09-23: "go ahead and do the cut-over, delete the tk ui")

The Tk UI is gone: `pinball_decryptor/gui/` is deleted, nothing in the package imports tkinter, and no build bundles it (`--exclude-module tkinter` in the macOS/Linux PyInstaller runs; the Windows embeddable no longer copies Tcl/Tk). `PAD_UI=tk` is gone from both entry points.

- **What the web UI borrowed from `gui/` now lives in `webui/`:** `rig.py`, `theme.py`, `runtime_prompt.py` (asks through compat), `emulate_core.py` (every plain function of the old Emulate tab), `emulate_rig.py` (its panel constants), `emulate_jjp_core.py`, `emulate_spike1_core.py`, `emu_cache.py`, `multiboot_core.py` (the Multi-boot logic, its Tk widget methods removed; the web panel still rebinds it), `multiboot_backend.py`, `multiboot_docker.py`, `preview_audio.py`, `help_content.py`, `disclaimer_text.py`, `preview_text.py`, `picker_data.py`, `update_interval.py`. Text was copied byte for byte.
- **`App(ctx)` is the one app class** (`webui/app.py` and `WebApp` are gone); `messagebox` / `filedialog` come from `webui.compat` at import, and compat patches nothing in tkinter. An exception escaping a UI job lands in the log pane as one line, the traceback in the session log (`App._report_ui_error` on the loop's `error_hook`), as Tk's `report_callback_exception` did.
- **Tests:** every Tk test file was triaged. Widget tests went; logic tests were moved onto the web harness or the new modules (`tests/test_app_run_logic*.py` holds what `test_gui_smoke.py` checked of the run logic, the Modes tab and the Scenes/Fonts windows). conftest's Tk lane, the `tk` / `gui` markers, `-m "not tk"` and CI's xvfb are gone.
- **The dev worktree picker** is a small pywebview window in a child process (no Tk).
- **README screenshots** come from the web UI: `scripts/take_screenshots.py` serves a settings COPY with preview codes stripped and the log collapsed (a developer's log names their own project files), and refuses to write if a preview-gated tab would show.
- **Still Tk, on purpose:** the rig tools that run INSIDE WSL (`tools/jjp_emu/jjpsw.py`, the JJP switch matrix; `tools/spike1_emu/s1view.py`) use the distro's own python3-tk under WSLg. They are not part of the app or its bundles.
- **At the merge:** David's user-level release skill (`~/.claude/skills/release/SKILL.md`) still names `pinball_decryptor/gui` in its screenshot-freshness check; point it at `pinball_decryptor/webui` once this is on main (the branch copy `.claude/commands/release.md` already is).

### Pieces

- `webui/host.py` - `python -m pinball_decryptor` starts the loop, the local server and the native window (pywebview: Edge WebView2 on Windows, WKWebView on macOS, Qt WebEngine on Linux). If the window cannot start, the page opens in the system browser and the log says why. `--browser` and `--serve` for development and captures.
- `webui/server.py` - 127.0.0.1, random port, a session token on every call. `/api` (calls), `/events` (Server-Sent Events, numbered and replayable), `/media` (local files with Range, for audio/video/picture previews), `/static`.
- `webui/state.py` - `Store`: the UI state, one namespace per tab, patches published as events. `EventBus`: numbered events kept for replay.
- `webui/dialogs.py` - modal questions and file pickers.
- `webui/tabs/<ns>.py` - one `TabService` per tab (`tabs/base.py`), listed in `tabs/__init__.py:TABS`.
- `webui/static/` - `index.html`, `css/app.css` (the whole look), `js/core/*` (store, calls, components, dialogs), `js/shell.js` (frame), `js/tabs/<ns>.js` (one per tab), `css/tabs/<ns>.css` (optional), fonts (IBM Plex, OFL) and Preact+htm (vendored, no build step).

### Zoom and small windows

The settings menu and Ctrl + / Ctrl - / Ctrl 0 set a global zoom (67% to 200%), saved in settings.json as `ui_zoom`. Below 1180 px the rail collapses to icons; below 1020 px two-column layouts stack.

### The frame (David, 2026-09-23)

- Top bar reads broad to specific, left to right: manufacturer (and era), then the project. No logo, name or branch chip: the window title already carries the name, version, branch and project.
- No Home button. The manufacturer menu switches manufacturer directly and ends with "Browse manufacturers and their games…", the picker page. The picker is otherwise only the first launch's landing page (no saved `last_manufacturer`); reached from the menu it has a "Back to <manufacturer>" button.
- The log: a dotted border above the status row is dragged to give the log room (up to the window height less 200 px), dragged to the bottom to hide it, or double-clicked. Under the status row, the progress row stays visible with the log hidden: Tk's full-width bar (striped and moving while a run is live, a marquee while the total is unknown), the percent, an ETA for the current step from its pace so far, the elapsed time, and Hide log / Show log.

### The virtual playfield (the rig's window), on the web too

David, 2026-09-23: "let's just go ahead do the virtual playfield with the web-ui now on this feature branch. remember I want a clean cutover". The Spike 2 playfield (`tools/spike2_emu/playfield.py`, launched by watch.sh on every platform) is no longer Tk:

- **Same file, same command line, same process.** watch.sh, killgame.sh, alive.sh and the Emulate tab all find it as `python playfield.py <game> [--savestates]`, so none of that plumbing moved. Everything that was the playfield's knowledge (the padled/padsw/padlcd readers, the fade envelope, the switch driver and pipe, the trough and ball rules, the tables) is kept verbatim; every Tk class became a MODEL (`Field`, `Schematic`, `LedGrid`, `KeyPanel`, `KeyInput`, `TroughDots`, `LcdPanel`) and one controller (`Playfield`) runs the 60 fps loop and answers the page.
- **The page** is `tools/spike2_emu/pfpage/` (plain JavaScript, no build step, the app's tokens and IBM Plex). It draws the artwork view on a canvas with REAL alpha (Tk had to fake it by mixing toward a sampled pixel), keeps Tk's hit test (switches over coils over inserts, rings and squares hit on their outline), the schematic's rows and LED grid, the key panel, the villain vision in its own window, the save slots and a Save dialog.
- **The host** is `tools/spike2_emu/pfweb.py`, stdlib only: a loopback server with a token, numbered events (SSE, long-poll fallback), and the window: pywebview (PAD's bundled Python on Windows: Edge WebView2), else GTK WebKit (the macOS container; Linux desktops), else a Chromium-family `--app` window, else a browser tab. `PAD_PF_WINDOW` forces one.
- **What changed outside it:** padpath.sh's Windows probe asks for `webview, PIL.Image` instead of `tkinter, PIL.ImageTk` (any Python still works, as an Edge app window); watch.sh's Linux branch needs only python3; the container installs `gir1.2-webkit2-4.1 python3-gi fonts-ibm-plex` instead of `python3-tk` (the image tag follows its Dockerfile, so Macs rebuild it by themselves); the Linux prerequisites install the same two GTK packages for Stern instead of python3-tk.
- **Proven:** the ported tests (the villain vision, key panel, actions, balls, ball model, hit, trough, late tables, switch id range, cabinet keys; the artwork hit test runs the page's own `pfHit` under Node) plus `test_spike2_pfweb.py` and `test_spike2_playfield_web.py`; `scripts/playfield_demo.py` (a demo title and a live fake LED show, no emulator, no WSL) run in Edge, in the native WebView2 window with the villain vision beside it (both close together, exit 0), and in CI on Linux (Chromium, and pywebview under Xvfb), macOS (WebKit) and inside the rig's container (GTK WebKit on its Xvfb). All 355 playfield tests also pass under WSL (Linux, with the cabinet-key C harness compiled). The developer scripts (`swholdtest.py`, `swspintest.py`, `ledgridtest.py`, `ledratetest.py`) drive the controller's api calls the way the page does. **Emulator-proven by David 2026-09-23.
- **Not ported yet:** JJP's switch matrix window (`tools/jjp_emu/jjpsw.py`) is still Tk. It runs INSIDE the WSL distro under WSLg (it writes the game's POSIX shared memory), so its web version needs either WebKitGTK in PAD-Runtime or the page shown from the Windows side; that is a decision about the runtime distro, recorded here rather than guessed.

### Hot reload while developing

`webui/devreload.py`, a checkout only (never frozen; `PAD_UI_HOT=0` turns it off). A saved stylesheet is swapped into the page in place; a saved script or HTML file reloads the page, which loses nothing because the UI state lives in Python. A saved Python file shows "Python changed · Restart" in the top bar; clicking it closes the app with its usual saves and starts it again.

The dev `.venv` needs `requirements.txt`, `requirements-ui.txt`, `requirements-windows.txt` and `faster-whisper` (pinned in `requirements-build.txt`): the tree selector relaunches the web UI in it, and anything missing there reads as missing in the app.

## Writing a tab (the contract every port follows)

Files a tab owns (and nothing else): `webui/tabs/<ns>.py`, `webui/static/js/tabs/<ns>.js`, optional `webui/static/css/tabs/<ns>.css`, `tests/test_webui_<ns>.py`, `docs/plans/web_ui_tabs/<ns>.md` (status).

Python (`tabs/<ns>.py`):
- `class XTab(TabService)` with `ns`, `key` (the Tk stable key), `label`, `group`, `icon`, `exports`; module-level `TAB = XTab`.
- Tk variables the run logic reads: `self.foo_var = self.var("foo", "str"|"bool"|"int"|"float", default)`; list the name in `exports`. The page edits `<ns>.foo` and the var's traces fire, as a Tk entry's did.
- Plain page state: `self.set(key=value, ...)`; table rows as a list of dicts; one row changed: `self.patch_item("rows", i, field=v)`.
- Page actions: methods decorated `@rpc` run on the UI loop (like a Tk button handler). `@rpc(loop=False)` only for pure reads that must answer while a modal is open.
- Long work goes on a worker thread; results come back with `self.ctx.loop.post(fn, ...)` (never touch the store's derived state from two threads without the loop).
- Asking the user: `from pinball_decryptor.webui import compat; compat.messagebox.askyesno(...)`, `self.window.ask_open(key, title, filetypes)`, `ask_folder`, `ask_save`.
- Hooks: `on_manufacturer(mfr)` (port the tab's part of Tk `apply_manufacturer` here: gating, labels, resets), `on_show()`, `on_running(running, mode)`, `on_project(folder)`, `on_close()`.
- Cross-tab calls the run logic fans out (define the method on the service if the tab takes part): `invalidate_asset_scans`, `reload_assets_tabs`, `stop_all_preview_playback`, `emulate_shutdown`, `refresh_after_revert`, `clear_replace_assignments`, `begin_revert_view`, `replacement_folder_mismatches`.
- Run the plugins' and `core/` functions the Tk tab called; do not copy their logic.

JavaScript (`js/tabs/<ns>.js`):
- `export default function XTab() { const s = useNs("<ns>"); const shell = useNs("shell"); return html\`<div class="page">...</div>\` }` and `export const css = true` if the tab has a stylesheet.
- Build only from `js/core/ui.js`: `PageHead`, `Card`, `Button`, `Field`, `PathField`, `Select`, `Seg`, `Check`, `Radio`, `Chip`, `Note`, `Table` (virtual, 3000 rows fine), `Empty`, `Modal`, `openMenu`, `InfoBadge`, `tip()`, `Icon`, `Progress`, `mediaUrl(path)`. Classes from `css/app.css`: `cols c75|c57|side`, `grid2`, `kv`, `stack`, `row`, `toolbar`, `pages`, `thumb`, `drop`.
- Calls: `call("<ns>.method", ...args)`; field edits: `<Field ns="<ns>" k="foo" value=${s.foo} />` (sends `ui.set`).
- Look: the designs. Real wording from the Tk tab (labels, tooltips, messages), never invented numbers or claims.

Checking a tab:
- `python -m pytest -o addopts='' -p no:cacheprovider tests/test_webui_<ns>.py tests/test_webui_core.py` (in the branch's `.venv`).
- `python scripts/webui_shot.py --out <dir> --settings "%APPDATA%/pinball_decryptor/settings.json" --mfr <key> --tab <ns>` screenshots the tab in Edge and lists every JavaScript error; `--all` does every manufacturer x tab. It runs against a COPY of the settings and never probes WSL or the rig.

Rules: never run the emulator (the rig is David's); never Extract/Write/Revert/Save into a real project; never name a tester; never mention Pinball Browser.

## Status

- 2026-09-22: framework (loop, server, store, dialogs, shims, window, shell, picker, status bar, log drawer, zoom, theme, capture harness), core tests.
- 2026-09-23: every tab ported for every manufacturer (Extract, Audio, Video, Images, Text, Defaults, Write, Multi-boot, Mod Pack, Partitions, Compare, the three Emulate tabs) plus the gear/help menus and their windows (Fonts, Scenes, disk space, prerequisites, updates, projects). Two independent review rounds walked each Tk tab section by section against its port and fixed what they found; per-tab notes in `docs/plans/web_ui_tabs/`.
- 2026-09-23: the virtual playfield is a web page (emulator-checked by David); the Tk UI is deleted (the cut-over above); PAD-188 from main ported into the web Multi-boot tab. Full suite 6721 passed on Windows (80 s), Linux 6874 passed; the frozen macOS/Linux apps and the rig container pass the manual webui-builds run without tkinter bundled.
- **Done (2026-09-23):** merged to main by `/finish feature/web-ui`, released as v1.0.0. The Owed list below stays as follow-ups.

What is proven, and how:
- Tests: all 586 web UI tests pass (`tests/test_webui_*.py`), including the contract test (every `self.window.X` app.py reads exists for all 11 manufacturers) and the parity test (WebApp sets every attribute Tk's App.__init__ sets). Twelve runs with two suites at once on this PC all passed, and the Tk lane's worker group (Tk and web tests in one process) passes.
- The full suite on this PC, 2026-09-23 01:40: 7,272 passed, 0 failed, 260 skipped (card images, rig scripts and tools this PC does not have). The run before it failed only three stale tests that fail on main too (the lane-grouping stub and the longer-audio wording in the Tk lane, which CI deselects, and the pinned-requirements guard, which needed requirements-ui.txt registered); all three are fixed here.
- The gzho project was checked after every run: its log, anchor and hash cache were not touched after the repairs noted in `web_ui_tabs/multiboot.md` and the handoff report.
- Every manufacturer and tab captured in Edge (59 shots, zero JavaScript errors), in WebKit (Stern, zero errors), at 150% zoom and in a 1024x700 window.
- Native windows: Windows (Edge WebView2) opened from the venv, with the app's icon, and closed cleanly (exit 0). macOS (WKWebView) and Linux (Qt WebEngine under Xvfb) open the frozen app in CI (`webui-builds` runs 35817100248, 35817657859 and 35820347813, the last on the final code): no local-network prompt, no Reconnecting banner, 58 tabs captured per platform with zero JavaScript errors, plus a light-theme (macOS) and a narrow-window (Linux) pass.

Owed (needs David or a decision):
- A real run of the rig from the web Emulate, JJP, Spike 1 and Multi-boot tabs; every rig path was exercised against stubs only (the rig is a mutex and was never started here).
- A real card read or write (Extract from a card, Build / flash, revert); those paths are the unchanged app.py code, reached through tested buttons.
- A real drag of a file from Explorer / Finder onto a drop zone (the host hands the path over; Playwright cannot drop a desktop file).
- Direct SD write on Stern and JJP has no button, exactly as in Tk. Decide whether the web UI should add one.
- CI policy (David, 2026-09-23: "no expensive heavy testing slowing down ci"): `test.yml` stays the only automatic check (about 2 minutes, after a push to main or a tag, gating nothing); the web UI's own tests are in-process and add about 15 seconds. `webui-builds.yml` (frozen apps, every-tab captures, native windows, the rig container) runs by hand only, when the packaging moves.
- Spike 1's DMD and switch windows need the desktop window (they are separate native windows); in `--browser` mode the tab shows its cards without them.
- Keyboard navigation into a menu's submenu (the mouse works).

## How to test it

- `python -m pytest -o addopts='' -p no:cacheprovider tests/test_webui_*.py` and the existing suite (`scripts/testpick.py`).
- `python scripts/webui_shot.py --out shots --all --settings <copy of settings.json>`: every manufacturer and tab, no JavaScript errors.
- The real app: `python -m pinball_decryptor` from this worktree (the tree selector lists it).
- Linux and macOS: the `webui-builds` workflow on this branch builds both apps and captures every tab (`.github/workflows/webui-builds.yml`).
