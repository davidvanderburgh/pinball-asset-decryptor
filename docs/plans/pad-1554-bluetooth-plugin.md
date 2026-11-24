# PAD-1554: Bluetooth headphones as a plugin

mattlqx's [spike-pinball-bluetooth](https://gitlab.com/mattlqx/spike-pinball-bluetooth) gives Stern Spike 2
and Spike 3 machines Bluetooth headphones. David asked him whether PAD could integrate it. His answer, which is
the design brief:

> do you think you could have it pull the repo and use it from there rather than pulling all the code into the
> PAD repo? maybe select a version tag or something. installation integration would be great.
>
> if any modifications are needed, create an MR or just let me know

David on the screen: "maybe a new Plugins tab, where the user can choose optional plugins to install. they need
to persist between PAD updates too."

## What the plugin is, upstream

Read from the v0.3.0 tag (commit `c21bfbd0`) and its release archives.

- Release assets per tag: `spike-pinball-bluetooth-armv7.tar.gz` (Spike 2), `spike-pinball-bluetooth-arm64.tar.gz`
  (Spike 3), `SHA256SUMS`. Permanent address:
  `https://gitlab.com/mattlqx/spike-pinball-bluetooth/-/releases/<tag>/downloads/<name>`.
- Each archive is a flat tar: `menu.so` (preloaded into the game, adds the Bluetooth menu; acts only on a game
  executable whose hash it knows, any other runs as stock), `spikebt` (static Go helper), `run-live.sh` (the
  launcher), `rollback.sh`, `LICENSE`, `NOTICE.md`, `menu-elf.txt`, its own `SHA256SUMS`; armv7 adds `btusb.ko`
  and `radio-start.sh` (loads the USB driver only on kernel `3.14.28_1.0.0_ga-wandboard+g08f5291` and only when
  the module's hash is the built one; starts BlueZ 4 with bind mounts, never rewrites the rootfs).
- Install, per its README: the files in `/usr/local/spikebt`, an `enabled` file there, and the game's supervisor
  running `/usr/local/spikebt/run-live.sh <game>` (Spike 3: with `SPIKEBT_BACKEND=bluez5`).
- `run-live.sh` already preloads `/usr/local/padmode/mode.so` ahead of `menu.so` when it is there, runs the plain
  game when anything is missing or fails, and creates `/dump/spikebt/disabled` after a game that exits non-zero.
  It knows no other preload.
- State on the machine: `/dump/spikebt/` (sockets, preferences, link keys). Never touched by a card build.
- GPL-2.0. Nothing of it is in this repository.

## Design

1. **Plugin store** (`core/card_plugins.py`). A plugin is a descriptor (author, project, archives per kind of
   machine, the tag PAD was tested with and its archive hashes). Installing downloads the release at a tag into
   `<settings folder>/plugins/<key>/`, beside `settings.json` and outside the app folder, so an update keeps it.
   A tested tag must match PAD's own hashes; a newer tag is taken on the release's `SHA256SUMS` and is labelled
   untested. Archives must be flat tars of plain files that match their own `SHA256SUMS`. "Install from files"
   covers a computer that cannot reach gitlab.com (tested tags only).
2. **On the card** (`core/bluetooth_card.py`, Spike 2). Every archive file unchanged in `/usr/local/spikebt`,
   plus `enabled` and `pad-release` (the tag). `game_monitor`'s game line becomes `BT_HOOK_LINES`: his launcher
   when it and `enabled` are there, else exactly what the remote-buttons block did.
3. **Other PAD preloads.** His launcher would drop `padmenu.so` (multi-boot) and `pad-buttons.so`. Rather than
   change his file, the block hands the launcher `/usr/local/bin/pad-bt-game` in place of the game when either is
   on the card: six lines of sh that put them in front of `LD_PRELOAD` and exec the game. `mode.so` and `menu.so`
   load into that sh too and do nothing there (`hk_is_game_process`; unknown executable hash).
   **Upstream ask worth sending** (not needed for this to work): let `run-live.sh` take extra preloads, e.g.
   `SPIKEBT_PRELOAD`, so the wrapper can go.
4. **Project choice.** `extras.bluetooth = {enabled}` in `.staged_changes.json`; the build digest carries the
   installed release, so installing another version is a change to build.

## Done (first run)

- `card_plugins.py`, `bluetooth_card.py`, the block in `modehook.py` and `remote_buttons.py` (held equal by a
  test), `card_extras.load_bluetooth/save_bluetooth/digest`.
- `tests/test_pad1554_bluetooth_plugin.py`: 12 tests, 5 on a real ext filesystem (pass under WSL Ubuntu with
  `PAD_E2FSPROGS_DIR=/sbin`). The real v0.3.0 archives were downloaded and match the pinned hashes.

## Left, in order

1. **Build pipeline**: `plugins/stern/pipeline.py` beside remote buttons (validate_request before the build,
   apply_to_build after, summary line, guard_flash where the others are called); `tests/test_extras_pipeline.py`.
2. **Plugins tab** (web UI): a card per plugin: what it is, author, project link, licence; version picker from
   `card_plugins.releases` (tested one marked); Install / Update / Remove / Install from files; "Put on this
   project's cards" tick; what the open card carries (`inspect_image`); `DETAILS` under "Exactly what it changes
   on the card". Before/after screenshots (before = the tab bar without it).
3. **Supported game check**: `profiles/supported-games.json` at the tag lists `executable_sha256` per Spike 2
   build (Spike 3 profiles are one JSON each under `profiles/spike3/`). Fetch at install, keep in the store, and
   tell the user on the tab whether this card's game version gets the Bluetooth entry.
4. **Emulator proof**. The rig execs `./game` and never runs `game_monitor`, so: (a) run the card's real
   `game_monitor` block + `run-live.sh` + `pad-bt-game` under the rig's ARM chroot with busybox sh, showing the
   fall-back to the plain game with every preload kept (the rig has no radio, so `radio-start.sh` refuses there);
   (b) the menu itself with his demo backend (`spikebt --backend=demo`, `scripts/cabinet/run-demo.sh` at the
   tag): Service -> Bluetooth on a built card's game, glshot. Rig step like `modes/cardmodes.sh`.
5. **Spike 3**: rootfs is LUKS; `ssh_spike3.apply_to_build` already rewrites it with the user's key. Same files
   (arm64, no module), launcher with `SPIKEBT_BACKEND=bluez5`; Spike 3 mode hook is `/games/pad/padmode/padmode.sh`
   and appends `mode.so` after `menu.so`, the opposite order to his launcher's: check before choosing the hook.
6. **Direct routes**: `core/network_apply.py` (to an attached SD card, to a running machine) and
   `mode_install.py`/`mkmulticard.py` paths that read `game_monitor` (they go through `modehook`, which knows the
   block now); a "clear the switched-off mark" (`/dump/spikebt/disabled`) for Send to machine.
7. Docs: `docs/guide/using-the-app.md` Plugins section, help text.

## State after the second run (2026-11-24)

Done and committed: items 1 (build pipeline, flash guard, Write tab rows), 2 (Plugins tab, help text, shots) and
4 (emulator proof) of the list above. The proof is written up in
`docs/validation/2026-11-24-pad-1554-bluetooth-plugin.md`; its scripts are in `C:\tmp\PAD-1554\rig\`, the proof
card is `~/pad1554/gz_pro_1554bt.raw` in WSL Ubuntu (delete it when the ticket ships).

Still left, in this order:

1. **Spike 3** (item 5). The author's launcher exits without starting the game when `SPIKEBT_BACKEND` is not one
   it knows: the hook must set `bluez5` exactly. `tabs/plugins.offered` and `bluetooth_card.offered` are
   Spike 2 only today, so the tab is not on a Spike 3 rail yet.
2. **Straight to a card / Send to machine** (item 6): `core/network_apply.py` takes `wifi` and `buttons`; add the
   plugin, and remove `/dump/spikebt/disabled` on Send to machine so a plugin that switched itself off comes back.
3. **Supported game check** (item 3): tell the user on the tab whether the picked card's game version is one the
   installed release knows.
4. `docs/guide/using-the-app.md`: a Plugins section.

Rig notes: `parts.py --rootfs-file` prints text and damages a binary; pull folders with `--rootfs-dir`. The
service menu needs Select twice (a splash page first); Bluetooth is the last row, one Minus from the top.

## State after the third run (2026-11-24): done

- **Spike 3**: the arm64 release on the LUKS system partition (`ssh_spike3.rewrite_rootfs`, shared with remote
  access), `S3_HOOK_LINES` in `game_monitor` with `SPIKEBT_BACKEND=bluez5`, the game's exit code handed on, and
  the launcher's switched-off mark removed after Stern's three normal ends (1, 3, 6). Proven on a real Fallout LE
  0.82 card and in the Spike 3 emulator (docs/validation).
- **Supported games**: installing keeps `profiles/supported-games.json` and `profiles/spike3/*.json` from the
  source tree at the tag; the tab and the build say whether the card's game program is one the release knows.
  Checked on five real cards. A game program this app changed is not known to his menu: no Bluetooth entry there.
- **On the machine**: "Check it on the machine" (remote access) reports the plugin's state and removes
  `/dump/spikebt/disabled`.
- The author asked to be credited as mattlqx; done everywhere.
- Dropped: putting the plugin straight on a card or a running machine without a build. The existing direct routes
  keep a Bluetooth card's block (tested).

Worth telling the author (none of it blocks this): an option for extra preloads in `run-live.sh` would retire
`pad-bt-game`; `run-live.sh` exits 2 without starting the game on an unknown `SPIKEBT_BACKEND`; on Spike 3 exit
codes 1, 3 and 6 are normal ends that his launcher treats as failures; his menu cannot attach to a game program
PAD has changed (Music Mode rows, editions).
