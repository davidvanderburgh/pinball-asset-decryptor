# The Big Lebowski multi-boot (PAD-853)

Several builds of The Big Lebowski on one machine, and a boot menu at power-up: the
flippers choose, START boots, the countdown boots the remembered choice. The menu is the
same code selector the Stern card, JJP and Barrels of Fun machines carry
(`tools/spike2_emu/codeselect`), built for this machine as `dpselect`. Asked for on
Pinside (Amused_to_Death, 2026-10-29).

STATUS: design proven in parts (below); the pieces are being built in the order of
*Work list*. Each item says what proves it.

## How a TBL machine starts its game and takes an update

Read off a machine's disk image (`TBL_justin_113_v10.img`, an Arch Linux PC) and out of
the game's own program (1.13's PyInstaller archive: `game/update.py`,
`game/modes/menu/menuitem_usbupdate*.py`, `menuitem_versionselect*.py`), 2026-10-29.

* `/` (sda2, label NXPIN) is mounted READ-ONLY; `/home` (sda3, label DP) is rw.
* tty1 logs `dp` in; `~/.bash_profile` runs `startx`; `~/.xinitrc` runs
  `~/game/run.sh`. So the game is an X client and nothing else draws on the screen.
* `~/game/run.sh` reads `~/game/version` (a folder name), `cd`s into that folder and runs
  `./start fullscreen os_version 2021-10-14-21`. When the program exits and
  `~/game/restart` exists, it removes it and starts again, READING `version` AGAIN.
* `~/game/<version>/` is one complete build: the PyInstaller program (`start` plus ~120
  libraries: its own Python 2.7, pygame, SDL 1.2, libX11, **libpinproc.so.2.0,
  libftdi1, libusb**), `config/machine.yaml`, `assets/` (what that version changed; the
  game looks there first, then `../assets`, the base assets), and `database/database.db`
  (settings, audits, scores: ONE DATABASE PER VERSION FOLDER). 1.13's is 3.6 GB.
  `game.Main.VERSION` is a constant in the program ("1.13"), not the folder name.
* **Version Select** (service menu) lists every sibling folder whose name is only digits
  and dots, newest first by string. Selecting one copies the running database into it,
  writes `../version` and restarts. **Delete** removes one.
* **USB update** lists `TBL-v<digits.dots>.zip` on the stick whose version is NOT already
  a folder. Installing one: copy the zip to `../<v>.zip`, `unzip -o` it into the temp
  folder, and when its `<v>/delta` lists versions (a delta) copy the RUNNING version's
  `assets/` files the zip lacks into it; then rename `<v>/` to `../<v>`. It does not touch
  `version`: the owner picks the new folder with Version Select. A zip with no `delta`
  ("full") is installed as it is. Nothing outside the new folder is changed.

## The design

A multi-boot is ONE update zip, `TBL-v<V>.zip`, installed with the machine's own USB
update and switched to with its own Version Select. No drive comes out, and the stock
service menu takes it away again (Version Select another version, Delete `<V>`).

| in `<V>/` | what |
|---|---|
| `start` | the launcher (a shell script; `run.sh` runs it with the game's arguments) |
| `pad/dpselect` | the menu: codeselect, ONE STATIC x86-64 program, drawing on the X server through the X protocol itself (`x11_raw.c`), no library of the machine's |
| `pad/dpprocsw` | the buttons: a tiny program on the GAME'S OWN `libpinproc.so.2.0` (from the base folder, `LD_LIBRARY_PATH`), reading the flipper and START switches and printing each change |
| `pad/images.conf`, `pad/builds.txt`, pictures, `font.ttf` | the menu and what each card boots |
| `pad/build<k>/` | build k's files: a TBL update zip's `<version>/` content (a PAD mod, or a Dutch Pinball update) |

**Builds live beside the other versions**, as `~/game/<V><k>` (digits and dots, so
Version Select lists and can Delete them). A build cannot run from inside `<V>/`: its
`../` must be `~/game` (`../assets`, `../serial`, `../temp`, `../restart`).

**Every power-up** (`run.sh` -> `<V>/start`):

1. First run after the install (or a build missing): make each build folder the way the
   USB updater would - hard-linked copy of its base (the newest installed stock folder its
   `delta` names; unlinked before a file is laid over it), its files laid over, its
   `database/` a real copy. A build whose base is not on the machine is left out of the
   menu.
2. Run `dpprocsw | dpselect` (menu killed after its own timeout plus a minute).
3. Carry the database: when the chosen build is not the one that ran last, copy the last
   one's `database/database.db` into it first - what Version Select does.
4. `cd ../<chosen>` and `exec ./start "$@"`. `version` keeps naming `<V>`, so the next
   power-up, and the game's own restart, come back to the menu.

Every failure ends on the newest stock folder, exactly as the machine would boot it.

## Facts proven so far

* **A build runs from a renamed folder** (PAD-853 rig, TBL 1.13 off the image): `1.99`,
  `9.13`, `1.13p`, `1.13pa`, `1.13pad`, `1.13-p` boot to attract. The PyInstaller
  loader fails on a LONG path: `/var/tmp/pad_dp/rig2/game/1.13pad1/start` (40
  characters) dies with `Cannot open self .../start<garbage>`, 39 runs. Folder names are
  kept short (`<V><k>`, at most 7 characters).
* The game's P-ROC library is in every version folder (`libpinproc.so.2.0` over
  `libftdi1.so.2`), and `tools/dp_emu/aaiw/aaiwshim.c` already answers libftdi1 the way
  a P-ROC does, so the rig can run `dpprocsw` on the real library.
* Buttons (1.13 `config/machine.yaml`, a P3-ROC, `machineType: pdb`): `flipperLwL` SD67,
  `flipperLwR` SD65, `startButton` SD68.

## Work list

1. `dpprocsw.c` - buttons off libpinproc; proven in the rig under aaiwshim.
2. `x11_raw.c`, `input_pipe.c`, `stubs_dp.c`, `make PLATFORM=dp` - the menu on an X
   server; proven on the rig's Xvfb (shot) with presses from 1.
3. `padselect_dp.sh` (`<V>/start`) - the launcher; a shell test like
   `padselect_bof_test.sh`.
4. `mkdpmulti.py` - the zip builder (and its tests).
5. `machine_sim.sh` - the whole thing in the rig: the USB update's install steps on a
   prepared build, Version Select, the menu, a pick, the chosen build in attract.
6. The Multi-boot tab: a Dutch Pinball backend (`multiboot_backend.py`), the TBL
   capability, before/after shots.
