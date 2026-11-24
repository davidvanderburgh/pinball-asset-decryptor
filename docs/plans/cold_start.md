# Cold start: the window first (PAD-1545)

## What was slow

The window was created only after the whole App had been built, and the App's
constructor opened the last project. Nothing was on screen for all of it.

Measured on the installed v1.586.3 (hidden window, `scripts/coldstart_timing.py`):

| Stage | Warm | Cold file cache |
|---|---|---|
| Shortcut (wscript, runas) to Python running | ~0.15 s | ~0.15 s |
| Python imports | 0.1 s | 0.1 s |
| App() built, no window yet | 1.5 s | 2.0 s |
| webview.start to the page asking for its state | 0.6 s | 0.5 s |
| Page load (33 requests) | 0.26 s | 0.26 s |

The first launch of a day was slower still (about 4 s between the session
banner and the write scan starting in the log, against 1 s in the timed runs).

## What changed

- `webui/host.py`: `begin_build()` starts the server and posts the App's making
  to the UI loop, then returns. `main()` in the native mode creates the window
  and starts the web engine on the main thread meanwhile; a thread
  (`app-build`) waits for the App, registers what needs it (`_wire_app`) and
  ends the start-up watch. `build()` is `begin_build()` + `finish()` and is what
  the browser and serve modes, and the tests, still call.
- `webui/context.py`: `ctx.building` (an Event, None when nobody is building).
  The page's first `/api/state` marks the page as seen (the blank-window watch)
  and then waits on it, so the page needs no change to load before the App.
- `app.py`: with `ctx.defer_session` (set by the native host only) the
  constructor queues `_start_session` as its first job instead of running it,
  with `shell.opening` set meanwhile; the page stays on its Starting line until
  it clears. `saved_window_geometry()` reads the window's place from
  settings.json without an App.
- `static/index.html`: a wordless spinner from the first paint until the first
  render.

## Result (this PC, compiled trees, three runs each, seconds from process start)

| | main | this branch |
|---|---|---|
| Window on screen | 1.65 | 0.59 |
| Page has its state | 1.9-2.0 | 0.9 |
| Tabs on the page | ~2.0 | ~1.9 |

The window is up a second sooner; the tabs arrive when they did, because the
App and the project restore are the same Python work on the same thread, now
beside the web engine's start instead of before it.

## What is left: the project restore itself

About 1 s on the UI loop after the App is made, for the Godzilla project:

| Tab | Time | In |
|---|---|---|
| Modes | 400 ms | `on_manufacturer > _refresh_all > refresh`: every port file parsed once (`mode_project.profiles`), port stamps hashed |
| Colour | 240-270 ms | `_load > colour_profile.asset_profile > recommended` (100 ms of it importing numpy) |
| Project log | ~200 ms | `shell_extras._follow_project_log`: `session_log.set_project` and the first appended lines |

None of the three is on screen at start. Making them load when first shown, or
off the loop, would put the tabs on the page at about 1 s.

## Timing it again

```
python scripts/coldstart_timing.py OUT.json WEBVIEW_SCRATCH_DIR [LINGER_S] [APP_DIR]
python scripts/coldstart_report.py OUT.json
```

Use a Python that has pywebview. The installed copy's Python never writes
bytecode: run `python -m compileall -q pinball_decryptor` in a source tree
first, or its start is a second slower than an installed one.
