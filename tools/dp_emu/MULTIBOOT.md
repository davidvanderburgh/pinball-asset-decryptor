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
  `flipperLwR` SD65, `startButton` SD68. The game's `dp/pdb.py` (PDBSwitch) reads "SD<n>"
  as P-ROC switch n; libpinproc's own `PRDecode` reads it as 0 on a PDB machine, so
  `dpprocsw` uses the game's rule.
* **`dpprocsw` reads the buttons through the game's real libpinproc** (step 1, rig,
  2026-10-29): 1.13's `libpinproc.so.2.0` over `aaiwshim.so` as a P3-ROC
  (`AAIW_PROC_CHIP=p3`): chip id 0xf33db33f, `ready`, then `sw L 1` / `sw L 0` / `sw S 1`
  for `sw 67 c` / `sw 67 o` / `sw 68 c` on the shim's FIFO. Its only glibc version is
  GLIBC_2.2.5 (`-nostartfiles`, its own `_start`). Build and run, as root in Ubuntu:

      gcc -shared -fPIC -o B/libpinproc.so.2.0 -Wl,-soname,libpinproc.so.2.0 stub.c  # link-only stub
      gcc -O2 -fno-stack-protector -fno-pie -no-pie -nostartfiles -o B/dpprocsw dpprocsw.c B/libpinproc.so.2.0
      AAIW_PROC_CHIP=p3 DPEMU_FIFO=B/fifo LD_PRELOAD=B/aaiwshim.so \
          LD_LIBRARY_PATH=/var/tmp/pad_dp/cache/<build>/1.13 B/dpprocsw L=SD67 R=SD65 S=SD68

  (`aaiwshim` now also reads its FIFO from `ftdi_read_data`, for a program with no SDL
  loop.)
* Rig gotcha: a prepared build in the cache is HARD-LINKED into copies; `rm` a copy's
  `version` before writing it, or the cache's own changes too.

## Work list

1. DONE `dpprocsw.c` - buttons off libpinproc; proven in the rig under aaiwshim.
2. DONE `x11_raw.c`, `input_pipe.c`, `stubs_dp.c`, `make PLATFORM=dp` - the menu on an
   X server. `fb_linux.c -DFB_X11` draws into a memory glass the root's size and sends
   the changed rows with PutImage to an override-redirect window with an invisible
   pointer (the X protocol by hand; no X server = the console framebuffer). Proven
   2026-10-29: `dpprocsw` on 1.13's libpinproc over aaiwshim piped into `dpselect
   --input pipe` on an Xvfb: RIGHT moved the highlight (x11grab shot), START booted
   image 1. `make PLATFORM=dp check` = check_elf_dp.sh, headless.sh, fb_bof_test.sh,
   x11_dp_test.py (1:1, scaled 1366x512, pipe ended, no display), padselect_dp_test.sh
   (step 3). BOF `make check` still passes; JJP and Stern still build.
3. DONE `padselect_dp.sh` (`<V>/start`) - the launcher. `pad/images.conf` cards name a
   folder (or `stock` = the newest stock version); `pad/builds.txt` lines are
   `<folder> <bases,...|-> <files dir under pad/>`. Buttons from the stock version's
   machine.yaml PRSwitches (default SD67/SD65/SD68); dpprocsw runs with
   LD_LIBRARY_PATH at the stock version and is killed before the game starts; sound as
   the BOF hook (aplay on a pipe, only when the conf names one). `pad/ran` = the build
   that ran last, for the database carry. `test/padselect_dp_test.sh` (6 cases) passes;
   `make PLATFORM=dp check` passes as a whole.
4. DONE `mkdpmulti.py` - the zip builder: plan / build / verify / inspect / inject / media,
   the BOF builder's command line (the tab's contract). `--primary` = the stock version's
   update zip (only its version is read: its card boots that folder); each `--extra` = a
   TBL update zip whose `<version>/` travels as `pad/b<k>/` and becomes `<V><k>`. `<V>` =
   `9.` + four digits from the build minute (`--version` overrides), the file is always
   `TBL-v<V>.zip` (the update menu reads the version off the name). `ensuredpselect.sh`
   installs dpselect/dpprocsw/padselect.sh into /var/tmp/dpselect. tests/test_mkdpmulti.py.
5. DONE `machine_sim.sh` - the whole thing in the rig: the USB update's install steps (as
   menuitem_usbupdate_download.py: a delta gets only the running version's assets/), Version
   Select (the database copied, `version` written), the machine's run.sh with the rig's
   arguments (`fakepinproc dev`). PASS 2026-10-29, slot 2, TBL_justin_113_v10 (1.13
   installed): TBL-v1.15.zip installed + selected, then TBL-v9.0853.zip (stock 1.15 + a
   1.15 mod with a marker file) installed + selected; at power-up the launcher made 9.08531
   from 1.13 + the mod's files (the mod's delta names 1.01-1.14, as the USB update would
   lay it), the menu came up on X (shot), RIGHT + START through 1.15's libpinproc over the
   fake P3-ROC, the database Version Select put in 9.0853 carried into 9.08531, 9.08531 in
   attract (shot: the Grand Champion screen); the second power-up's countdown booted the
   remembered 9.08531 without making it again. `PADSELECT_PROCSW_PRELOAD` puts the fake
   board under the reader ONLY: preloaded into the game, aaiwshim's Mix_OpenAudio hook
   cannot find TBL's SDL 1.2 mixer and the game dies ("mixer system not initialized").
6. The Multi-boot tab: a Dutch Pinball backend (`multiboot_backend.py`), the TBL
   capability, before/after shots.
