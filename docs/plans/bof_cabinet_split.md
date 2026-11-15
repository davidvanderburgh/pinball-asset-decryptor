# A BoF game's window on a cabinet's screens (PAD-1308)

R12 of W8312's suggestions (from PAD-1304): a Barrels of Fun game draws every
display it has into one window; on a cabinet each display has a monitor of
its own. Show each part on its monitor through a DWM thumbnail, keep the real
window out of sight, give the focus back, and show a loading screen there
while the game starts.

## The layouts (read off live runs, 2026-11-14)

| title | window | main display | second display |
|---|---|---|---|
| Dune | 1280x1110 | 0,0 1280x720 | 0,720 1280x390 (the strip over the playfield) |
| Labyrinth | 1280x1110 | 0,0 1280x720 | 0,720 1280x390 |
| Winchester | 3286x768 | 0,0 1366x768 | 1366,0 1920x720 (the reflected one, drawn mirrored; grey below it is the window's background) |

Bon Jovi can't be emulated yet. A title not in the table is cut by its size:
the bottom 390 rows are the strip, the rest the main display. A hidden run's
Xvfb was 2560 wide and cut Winchester off; it is 3840 now (shot.sh too).

## What Windows and WSLg allow (measured, not assumed)

* A DWM thumbnail of the WSLg window works, and PrintWindow with
  PW_RENDERFULLCONTENT sees it in a window off the desktop: that is how the
  proof captures the parts without putting them on a screen. PrintWindow of
  the WSLg window itself returns black.
* **The window cannot be put off the desktop.** SetWindowPos from Windows is
  undone at once (10 817 moves in 4 minutes, all back at the top-left); an X
  window asked to open off-screen is cascaded onto it; a later off-screen
  XMoveWindow is ignored; an override-redirect window off-screen never reaches
  Windows at all (nothing to thumbnail).
* **Nor hidden from Windows.** msrdc runs elevated when the app started WSL
  (integrity 0x3000 against 0x2000): SetLayeredWindowAttributes is refused
  (access denied), DWMWA_CLOAK is refused (only a window's own process may
  cloak it), SetWindowRgn and moves are ignored.
* So it sits **under a part window**: those are topmost and fill their
  monitors, and a topmost window always covers an ordinary one.
  `padsplit.cover_spot` picks the corner of a part's monitor that leaves
  nothing showing on a monitor no part covers (a 1280x1110 window on a
  1920x1080 backbox above Visual Pinball's playfield goes flush with the
  backbox's bottom, overhanging above, off every monitor).
  `tools/bof_emu/bofplace.py` puts it there from the Linux side - under WSLg
  X root coordinates are Windows' physical pixels, a create-time position is
  ignored, a later XMoveWindow lands near the aim and is corrected - and puts
  it back whenever WSLg moves it.
* The split's runs open the game as shipped (borderless, its own size, no
  stretch) and with Godot's `no_focus`. WSLg then gives the window no title
  and no 32 px margin; padsplit finds it by its size either way.
* **The focus**: WSLg still activates the window when it opens. padsplit gives
  the focus back to the window that had it (Visual Pinball's player first in
  the kit): the controller's AttachThreadInput hand-over, then an ALT press
  and SetForegroundWindow. That only works at the same integrity as msrdc -
  proven between two ordinary processes; refused from an unelevated one to
  the elevated msrdc, and padsplit's log says so. The app runs elevated, so
  its split matches an msrdc the app started; a cabinet whose Visual Pinball
  starts WSL itself has both unelevated.

## What was built

* `tools/spike2_emu/vpx/padsplit.py`: the setting (`split.json` beside
  padisplay's display.conf: on, a monitor per part, keep shape / fill), the
  plan, `place_env()` for watch.sh, and the Windows side: one borderless
  topmost no-activate window per part, a DWM thumbnail each, the loading
  screen (title, step, bar) from padloading.py's status protocol until `up`,
  the cover check, the focus minder; `--to` / `--shot` for proofs.
* `tools/bof_emu/run_game.sh`: PAD_BOF_SPLIT=1 writes the split override;
  PAD_BOF_PLACE (`<title>:X,Y;...;*:X,Y`, the title is only known once the
  .fun is unpacked) starts bofplace.py with this title's spot.
* The Emulate tab (Barrels of Fun): a Cabinet screens card; a Start with the
  split on starts padsplit first (loading screens at once), feeds it the
  footer's steps, `up` / `failed <why>`, and `stop` on Stop, Cancel and quit.
* The Visual Pinball kit: a BoF launch (PAD-1305's BofLaunch, through
  SpookyLaunch.env) gets the split's environment, and the controller starts
  padsplit (`--focus vpx`) instead of padloading, keeps it past `up`, and
  stops it when the table closes.

## Proof

Live Dune on rig 1, muted, the split as the tab runs it (main display on
monitor 1, the second at an off-desktop test spot): the loading screen on
both, the game's window found at 0,0 and reported under the part windows,
bofplace placed, both parts showing the live game; a grab of the monitor
shows the picture letterboxed with black where the game's window lies under
it. tests/test_bof_split.py.
