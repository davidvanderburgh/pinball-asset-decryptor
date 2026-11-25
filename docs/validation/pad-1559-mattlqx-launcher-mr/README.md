# PAD-1559: one merge request to mattlqx's spike-pinball-bluetooth (launcher gaps from PAD-1554)

Repo: https://gitlab.com/mattlqx/spike-pinball-bluetooth, branched off `main` at e172fed (v0.3.0 + two doc commits).
No change to PAD itself in this ticket.

## What is in it

One commit, `fix(cabinet): keep add-on preloads and the stock game on launcher fallbacks`
(`0001-fix-cabinet-keep-add-on-preloads-and-the-stock-game-.patch`, made with `git format-patch`):

1. `SPIKEBT_PRELOAD`: colon-separated extra objects that `run-live.sh` and `run-demo.sh` put in front of their own
   list, in the menu path and in `stock_game`. `menu.so` stays rightmost (initializes first).
2. An unsupported `SPIKEBT_BACKEND` runs `stock_game` instead of `exit 2` with no game.
3. With `bluez5` (Spike 3), game exits 1, 3 and 6 no longer touch `/dump/spikebt/disabled`. `bluez` (Spike 2) keeps
   the old rule: Stern only documents those codes as normal ends in Spike 3's `game_monitor`.

Plus a paragraph in `docs/build-menu.md` and four new tests in `tests/test_cabinet_launcher.py`.

Title and description to paste: `merge-request.md`.

## How it was proven

- His tests (WSL Ubuntu, glibc + cc): the new launcher tests fail on `main` (9 subtests) and pass on the branch;
  full suite 89 OK, 8 skipped (game executables not present).
- His CI lint: shellcheck 0.9.0 (bookworm, what CI installs) clean; `sh -n` clean; ruff E9,F63,F7,F82 clean.
  shellcheck 0.11 shows the same three SC2329 info notes on `main` and on the branch (trap-only functions).
- Emulator, his v0.3.0 release files, `main`'s run-live.sh ("before") vs the patched one ("after"), run in the
  card's own userland with a stand-in game (`cases.sh`; helper stand-in = his real helper on its demo backend):
  - Spike 2, Godzilla Pro 1.16 (`s2job.sh` via rigbatch, booted to attract after the cases):
    `spike2_godzilla_pro_1_16_cases.txt`. Before: PAD's pad-buttons.so dropped on every path; `demo` backend
    exit 2, game never started. After: pad-buttons.so in front on every path (menu last); `demo` starts the game;
    exit 1 still disables (Spike 2 rule kept), bluez5 exit 3 does not, exit 2 does.
  - Spike 3, Fallout LE 0.82 (`s3job.sh`): `spike3_fallout_le_0_82_cases.txt`. Before: exits 1, 3, 6 all set the
    disabled mark. After: 1, 3, 6 leave it, 2 sets it; the rig's four preloads kept in front of menu.so.
    Then the REAL game was started by the patched run-live.sh (`SPIKEBT_BACKEND=bluez5`,
    `SPIKEBT_PRELOAD=` the rig's own preloads): `spike3_real_game_maps.txt` shows all four rig objects plus
    menu.so loaded, `LD_PRELOAD=<rig objects>:/usr/local/spikebt/menu.so`; `spike3_bluetooth_menu.png` is his
    Bluetooth menu opened from the service menu.

## To open the merge request (David)

The working clone is `C:\tmp\PAD-1559\spike-pinball-bluetooth`, branch `launcher-extra-preloads-and-fallbacks`.
Fork the repo on GitLab, then from that clone:

    git remote add fork https://gitlab.com/<you>/spike-pinball-bluetooth.git
    git push -u fork launcher-extra-preloads-and-fallbacks

and open the MR against `mattlqx/spike-pinball-bluetooth` `main` with the title and description in
`merge-request.md`. (If the clone is gone: clone his repo, `git checkout -b launcher-extra-preloads-and-fallbacks
origin/main`, `git am <the .patch>`.) His CI runs on the MR pipeline.

## Not in the merge request: a conversation with him

His menu attaches only to an exact game-executable hash (AGENTS.md: "Match exact executable hashes ... do not weaken
these checks"). A game program PAD has changed (Music Mode rows, editions, the Heisei custom card) gets no Bluetooth
entry. That is his design, so it is a question for him (would he take per-build profiles keyed on PAD's output, or
a way for PAD to name the stock hash it patched from?), not a patch.

## Later, in PAD (once he tags a release with this and PAD pins it)

Drop `/usr/local/bin/pad-bt-game` (pass `SPIKEBT_PRELOAD=/usr/local/codeselect/padmenu.so:/usr/local/bin/pad-buttons.so`
instead) and the Spike 3 `disabled`-mark removal in `bluetooth_card.S3_HOOK_LINES`.
