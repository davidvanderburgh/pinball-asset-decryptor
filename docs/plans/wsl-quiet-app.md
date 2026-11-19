# The app stops waking WSL (PAD-1457)

Found during PAD-1453: with the installed app open, `wsl --shutdown` was undone
within two seconds, every time. WSL never idled, so VmmemWSL kept its memory
(3.2 GB working set when measured on 2026-11-19, with other work inside it as
well) and no disk compaction could run while the app was open.

## Census (measured, 2026-11-19)

Method: the web UI server run through a wrapper that logs every `wsl.exe`
launch with the Python stack that made it (`subprocess.Popen` patched), a
headless Edge on the page, David's real settings (scratch copy, every plugin
loaded via `PYTHONUSERBASE`), prerequisite check, rig and status polls on.

Main (v1.532.0), Home tab, 120 s: **116 launches** (first partial-plugin run:
180 in 180 s). Who, and what for:

| Caller | Interval | What it is for |
|---|---|---|
| `emulate_jjp_common._poll` (JJP, Spike 1, BoF, DP, AP, Spooky, PB tabs) | 10 s idle / 2 s running, each, from app start, every manufacturer | the tab's status panel; app quit stops a run this session started; a JJP key seen in the PC is handed to WSL |
| `tabs/emulate._poll` (Spike 2) | 10 s idle / 2 s running | status panel, rig board, audio/restart/stop request files |
| `runtime.status` (`wsl -l -q` + `cat /etc/pad-runtime.json` in PAD-Runtime) | 60 s cache, asked by every rig command build | which distro every Linux command runs in |
| `prereqs._probe_wsl` + `wsl_release_lines` | app start, every manufacturer switch | the prerequisite strip, and the "which Linux" log line |
| Spike 2 `_setup_check` (`setup_state`, `wsl_account`) | app start | the "Set up emulator…" notice |
| Spike 2 `_spike3_kick` | app start, card pick | Spike 3 cards cannot be emulated: said up front |
| Spike 1 `slots_refresh` | first poll | save-slot list |
| JJP `_attach_dongle` (`wsl.exe -e true` boots the default distro) | when a poll sees the key in the PC | hand the key to WSL |
| shellx disk badge (`wsl -l --running`, then a staging scan) | app start | Explorer disk badge (already only scanned when WSL was up) |

## The rule

Never start WSL to answer a status question. `core/wsl_up.py`:

- VM up? The `vmmemWSL` process (`vmmem` on older Windows, a "maybe") in the
  Windows process list: no wsl.exe at all.
- A distro up? Only asked when the VM is: `wsl -l --running -q`, which never
  starts anything, cached 5 s and shared by every caller. While a tab's last
  reading saw its game running only the VM check is made.
- Registration and the default distro come from the registry WSL keeps
  (`HKCU\...\Lxss`).

Then:

- Every Emulate status call whose distro is down is skipped; the tab shows its
  usual idle word with a hint "WSL is not running…".
- An idle Emulate tab off screen stops polling (Spike 2's backs off to 60 s; its
  reading also carries the rig board). A run this session started keeps its
  pace, so quitting still stops it; showing a tab takes a fresh reading.
- `runtime.status` remembers the manifest against the distro's GUID (new on
  every re-install/upgrade): read live once per install.
- A passing WSL prerequisite probe is remembered per distro GUID and answers
  while the VM is down; failures are never remembered; a pass is re-checked
  monthly or whenever WSL is up. The release log line only when WSL is up.
- Spike 2's startup setup probe and Spike 3 card probe wait until WSL is up or
  the Emulate tab is shown (a card picked there is answered at once; the setup
  notice is worth one boot when the user opens the emulator).
- Spike 1's slot list waits for WSL; the disk badge checks the VM first.

## Proof

- Branch, all plugins, WSL reading as down, memory seeded as after a first
  run: **0 launches in 120 s** on Home (main: 116).
- Hidden Godzilla Pro on rig 1, Spike 2 Emulate tab: polls every 2 s as
  before (Game running, 16 processes, CPU/memory, renderer fps), one
  running-list per minute.
- Real WSL stopped, Home, 10 minutes (2026-11-19 15:22-15:32, every plugin
  loaded): 6 wsl.exe launches, ALL `wsl -l --running -q` (never boots): two
  in the first 2 s while the VM was still winding down from its last distro,
  none for the next 4 minutes, then one a minute (Spike 2's off-screen poll)
  only while another session had a distro up (14 of 119 samples). No call
  that could start WSL. The first real run (before the last fix) caught the
  prerequisite check booting PAD-Runtime in that winding-down minute: the
  memory is now judged by the distro, not the VM.
