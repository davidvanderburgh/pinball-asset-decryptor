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

## PAD-1546: the tabs off screen read when shown

The restore ran every tab's manufacturer and project hooks, and several read
files only the tab itself shows. Each now reads when it is next shown (or, for
the Colour profiles, when Colour, Images, Video or Scenes is, whose Colors bar
draws from them); `TabService.shown()` is "this is the selected tab" (the
window's `_visible` is "on the rail" and must not be written by a tab):

| What | Was | Now |
|---|---|---|
| Modes `on_manufacturer` / project change | `_refresh_all`, 0.35-0.4 s | `_unread`, read on `on_show` |
| Colour `_load` | 0.23-0.27 s (numpy, the Recommended fit) | `_unread`, read on `on_tab_changed` to a tab that shows it |
| Play options, service menu publish | the same port read (0.3 s) | only while shown (their own `_visible` flag was the rail's, always on) |
| Network: Score feed + online co-op boxes | the same port read | only while shown; the rest of its publish still runs (Build reads its `error`) |
| Attract, Lights project change | reread on the rail flag | only while shown |
| Log lines of the restore | two file opens a line | one `session_log.batched()` for the restore; `set_project`'s banners join it |
| Write scan's colour row | on the loop (numpy import, up to 1.6 s cold) | worked out on the scan thread after the tabs are up |

`window.select_tab` now calls the left tab's `on_hide` (Network's stops its
live view, PAD-1467; the hook was never called before).

The page had a race the faster restore exposed: `useNs` subscribed in a plain
effect, a frame after the render (a second in a hidden window), and the
`shell.opening` change landing in between was lost, so the page stayed on
Starting until some later change. It subscribes in a layout effect now and
re-renders if its namespace changed since the render.

Interleaved, five starts each (`page drew its tabs` is the page's own clock):

| | main | PAD-1546 |
|---|---|---|
| Window on screen | 0.54 | 0.55 |
| Last project opening took | 0.96 | 0.14 |
| Tabs drawn | 1.73 (1.63-1.77) | 0.87 (0.85-0.87) |

## Timing it again

```
python scripts/coldstart_timing.py OUT.json WEBVIEW_SCRATCH_DIR [LINGER_S] [APP_DIR]
python scripts/coldstart_report.py OUT.json
```

Use a Python that has pywebview. The installed copy's Python never writes
bytecode: run `python -m compileall -q pinball_decryptor` in a source tree
first, or its start is a second slower than an installed one.
