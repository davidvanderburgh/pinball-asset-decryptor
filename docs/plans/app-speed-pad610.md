# PAD-610: the app starts quicker, and what else took time

David: "App should start quicker. Also, anything in the app that takes time we
should try and improve. Make a before and after table of all the things
improved."

## How it was measured

On David's PC, with copies of his real settings (his Godzilla 1.99D project and
card), never writing into them (`PAD_UI_CAPTURE`). Main (`a8ea7112`) and this
branch were run in turn, several rounds, and the medians kept (the PC is busy:
see "Perf tickets: interleaved A/B"). The window numbers come from the real
WebView2 window started with the installed app's own Python 3.12; the rest from
Python 3.14. Harness: `C:\tmp\PAD-610\bench_all.py` (and the scripts beside it).

## What was slow, and why

1. **The UI loop was busy for 2.2 s at every start**, so clicks went unanswered
   and the window itself waited. The Modes and Write tabs fill at start-up by
   looking up game ports, and every lookup:
   - resolved `tools/spike2_emu/modes/sdk` from disk (`pathlib.resolve`,
     ~16,000 times at start: over a second on its own), and
   - re-listed both port folders and re-checked every derived port's
     references (~1,100 file stats per lookup, 16 lookups at start).

   `mode_runtime.sdk_dir()` now keeps its answer once the folder is found, and
   `port_paths()` keeps its list until a file in the port folders or the
   recipes changes (one directory listing each, plus the text of the derived
   ports' sidecars, so a sidecar rewritten within one clock tick still
   counts). The same fix took the Modes tab switch from 0.84 s to 0.03 s.
2. **The window waited behind the start-up jobs.** The host asked the UI loop
   for the saved window place and title *after* the App had queued its
   start-up work, so the window opened only once all of it had run. The place
   is now read as the App is made, the title straight from it, and a title the
   app sets before the window shows waits in the host until it does
   (pywebview's `set_title` blocks its caller until the window is shown).
3. **The window toolkit loaded after the App was built.** Reading the screens
   loads pywebview's Windows backend (0.4 s); it now runs on the main thread
   while the UI loop builds the App.
4. **The first start after every install or update compiled the whole app**
   (~400 modules, 1.2 - 2 s): the installer ships source only. The installer
   now runs `python -m compileall` on the installed package (1 s, at install).
5. **The Write change scan** stat'ed every file a second time and hashed the
   uncached ones one at a time on one core. It now takes the stats from the
   folder listings and hashes on four threads (MD5 runs outside the GIL), with
   the same files, order, skips and hash cache as before (a test holds it to
   the old walk).

## Before and after

Medians of 3 rounds, main and the branch run in turn (tab switches: 4 each).

| What | Before (v1.207.9) | After | |
|---|---|---|---|
| Start until the window is on screen | 3.7 s | 0.9 s | 4x |
| Start until the page is drawn in the window | 4.2 s | 1.4 s | 3x |
| First start after an install or update: window on screen | 4.9 s | 0.9 s | 5x |
| App not answering clicks during start-up | 2.2 s | 0.2 s | 13x |
| Start until "Ready to extract / write" | 2.9 s | 1.4 s | 2x |
| Card picture on the Card tab after the page loads | 4.5 s | at once | |
| Start-up card read, as the log reports it | 0.6 s | 0.1 s | 6x |
| Switching to the Modes tab | 0.84 s | 0.04 s | 21x |
| Write change scan, 8,400-file project | 0.27 s | 0.10 s | 2.7x |
| Write change scan, nothing cached yet (1.8 GB hashed) | 2.6 s | 1.0 s | 2.5x |
| One game-port lookup (made thousands of times) | 99 ms | 1.2 ms | 80x |

Every other tab switch was already quick (10 - 40 ms) and is unchanged: its
Python side measures the same on both (the Video tab's first visit can look
slower in the page because its video is ready sooner, so the WebGL upload of
its first frame falls inside the measured frames instead of just after them).

Looked at and left alone: the card read itself (0.3 s, already cached by the
program's SHA-1); WebView2 drawing the page once the window shows (0.45 s, the
web view's own start); the static files (29 local files, 0.6 MB, under 0.1 s).
