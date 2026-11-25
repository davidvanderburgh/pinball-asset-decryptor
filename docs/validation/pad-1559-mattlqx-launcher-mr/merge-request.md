Title:
fix(cabinet): keep add-on preloads and the stock game on launcher fallbacks

Description:
Three small launcher changes that came up while wiring Spike-Pinball-Bluetooth into the cards Pinball Asset Decryptor builds. All of them are in `scripts/cabinet/run-live.sh`; the preload change is in `run-demo.sh` too.

**1. `SPIKEBT_PRELOAD` for other add-ons' objects**
The launcher sets `LD_PRELOAD` to its own `menu.so` (plus `/usr/local/padmode/mode.so` when present), so anything else a cabinet preloads into the game is dropped. `SPIKEBT_PRELOAD` takes a colon-separated list that both launchers put in front of their own list, in the menu path and in `stock_game`. `menu.so` stays rightmost, so it still initializes first and checks the original instructions before anything else changes them. Unset or empty, nothing changes.

**2. An unsupported backend starts the stock game**
`run-live.sh` exited 2 without starting the game when `SPIKEBT_BACKEND` was neither `bluez` nor `bluez5`, and the game supervisor then restarted it in a loop with no game running. Every other failure path runs `stock_game`, and this one does now too (it still prints the error to stderr).

**3. Spike 3 normal exits keep the menu enabled**
After any game exit other than 0, the launcher touches `/dump/spikebt/disabled`. Spike 3's `/etc/init.d/game_monitor` treats 1 (reboot requested after a software update), 3 (power loss) and 6 (deep sleep) as normal ends, so turning the machine off disabled Bluetooth until the mark was removed. With `bluez5` those three codes no longer set the mark. Spike 2 (`bluez`) keeps the current rule, and every other exit still disables the menu.

`docs/build-menu.md` describes all three.

**Testing**
- `tests/test_cabinet_launcher.py` gets four new tests: extra preloads in the menu path (constructor order: menu, then mode, then the extra), extra preloads in `stock_game` with and without `mode.so`, the unsupported backend starting the stock game and passing its exit code on, and the disabled mark after exits 1/3/6/2/139 with `bluez5` and 1/3 with `bluez`. The new tests fail on `main` (9 subtests) and pass with this change. The full suite: 89 tests OK (8 skipped for game executables I don't have locally).
- shellcheck 0.9.0 (the bookworm version CI installs) is clean, and so are `sh -n` and the CI ruff selection. shellcheck 0.11 shows the same three SC2329 info notes on `main` and on this branch (the trap-only `cleanup` and `rollback_attempt` functions).
- Emulated cabinets, with the v0.3.0 release files: on Spike 2 (Godzilla Pro 1.16) and Spike 3 (Fallout LE 0.82) I ran the `main` and patched `run-live.sh` inside the card's own userland with a stand-in game: fall-back, unsupported backend, the menu path with the helper on its demo backend, and the exit codes. On Fallout LE 0.82 the real game was then started by the patched `run-live.sh` with `SPIKEBT_BACKEND=bluez5` and the emulator's own preloads passed through `SPIKEBT_PRELOAD`. It booted with all of them plus `menu.so`, and the Insider Bluetooth entry opened from the service menu.
