# Spooky Pinball multi-boot (PAD-980)

Several builds of one Spooky game on one machine, and a boot menu at power-up: the flippers
choose, START boots, the countdown boots the remembered choice. The menu is the same code
selector the Stern card, JJP, Barrels of Fun and Big Lebowski machines carry
(`tools/spike2_emu/codeselect`), built for these machines as `spkselect` (`make PLATFORM=spk`).
Asked for by daveyvandy: "for all supported Spooky games".

STATUS: design settled from the machines' own files (below); the menu, its button reader and
the launcher are built and tested; the builder, the tab and the emulator proof are the *Work
list*.

## Which games

| family | titles | multi-boot |
|---|---|---|
| Debian PC, Warden/Pinotaur board, the game is `/game/code/uptest/main.x86_64` | Beetlejuice, Scooby-Doo, Texas Chainsaw Massacre, Evil Dead, Looney Tunes, Halloween, Ultraman | this design |
| Arch PC, P-ROC, Python game | Rick and Morty, Alice Cooper's Nightmare Castle | a second design (*P-ROC titles*, below) |
| pinHeck System (PIC32 + Propeller, DMD) | America's Most Haunted, Rob Zombie, Domino's, Jetsons | **not possible** without new firmware (below) |
| Total Nuclear Annihilation | - | the app cannot open its updates at all |

## How the Linux titles start their game and take an update

Read off each title's update and Clonezilla restore image (decompiled Assembly-CSharp.dll,
Looney's GDScript, the boot files), 2026-11-03.

| | Beetlejuice, Scooby-Doo, Evil Dead | Texas Chainsaw | Looney Tunes | Halloween, Ultraman |
|---|---|---|---|---|
| OS, user | Debian 12, norville (sudo NOPASSWD) | Debian 12, root | Debian 11 root (eMMC) / 12 norville (SSD) | Arch "Pinix", root (home /game) |
| start | `~/.profile` -> `sway` -> `exec /game/code/uptest/main.x86_64` | `/root/.profile` -> `xinit i3` -> same | i3 or sway -> same | `/game/.profile` -> `startx` -> xinitrc `cd /game/code/uptest; ./main.x86_64` |
| update file | `*.beetlejuice` (GPG-SIGNED: a non-Spooky file installs in developer mode only), `*.scooby`, `*.ed` | `tcm-N_NN.pkg` | `*.looney` | any `code*.pkg` on a stick at attract (GPG symmetric, the app has the passphrases) |
| unpacked into | `/game/update` by the service menu; `.profile` copies it in at the next boot (backup to /game/backup) | same | same | `/game/test` (the INSTALLED build's `config/test`) moves `uptest`, `assets`, `config` into /game/code right away |
| archive layout | flat (root = uptest) for BJ/Scooby; ED: `uptest/` + `assets/` | `uptest/` `assets/` `config/` | flat | `uptest/` `assets/` `config/` |
| per-build absolute paths | BJ/Scooby: `/game/code/uptest/{lightshows,speaker_kit.hex,_profile,...}`; ED: `/game/code/assets` | `/game/code/assets`, `/game/code/config` | none (the pack is inside the program) | `/game/code/assets`, `/game/code/config` |
| shared settings, scores | BJ/Scooby `/game/code/config`; ED `/game/{settings,game_settings,audits}` | `/game/{settings,game_settings,audits}` | `/game/godot/app_userdata/GDToons` | `/game/*.config`, `/game/*.json` |
| /game free | 220-230 GB (BJ, ED) | **5.8 GB** (9.3 GB eMMC) | 12.5 GB eMMC / 216 GB SSD | 14.7 GB |

Every install checks only that `uptest/main.x86_64` (flat: `main.x86_64`) exists, and every
start script `chmod +x`es it. No title checks its own program, hashes its files or compares
versions. The login profiles (BJ, Scooby, ED, TCM, Looney) roll back to `/game/backup` at
boot when `uptest/.backup_file` is missing; the game touches it once it is up. Beetlejuice and
Scooby-Doo md5-compare `uptest/_profile`, `sway_config` (and Scooby's `i3_config`, BJ's udev
rule and `speech.py`) with the installed copies at every start and copy + reboot on a
difference. Unity finds `main_Data` beside the program it runs; Godot's pack is inside the
program. Every stock install deletes its own folder first (`rm -rf /game/code/uptest/*`,
ED `/game/code/assets/*`), and Halloween's helper MOVES the folders.

## The design

ONE update file of the title's own kind, under the primary's own name (the menus list by
extension, Texas Chainsaw by `tcm-N_NN.pkg`), installed with the machine's own update. Its
`uptest/main.x86_64` is the launcher (`codeselect/padselect_spk.sh`); everything else travels
in `uptest/pad/`:

| in `pad/` | what |
|---|---|
| `spkselect`, `spksw`, `font.ttf` | the menu (static, X11 - every cabinet's desktop runs X or Xwayland, since the games are X clients) and its buttons off the board's tty (`spksw.c`: Warden `>152 n` / Pinotaur `<0x58 0x83 n`, three switches every 20 ms, nothing configured) |
| `spk.conf` | `board=`, `L= R= S=` (Warden 86/80/87, Pinotaur 81/80/87), `root=<name> <path>` per per-build folder outside uptest |
| `images.conf`, `media/` | the menu |
| `b0/` | the primary build WHOLE, laid out as the machine has it: `uptest/...` (+ `assets/`, `config/`) |
| `d<k>/`, `d<k>.removed` | build k's files that differ from b0's, and the ones it lacks |
| `builds.txt` | `b<k> d<k>` |

At every power-up the launcher (tested by `codeselect/test/padselect_spk_test.sh`):

0. after an install, moves `uptest/pad` to `/game/pad` (the next stock install backs up and
   wipes all of uptest; builds there would be copied once more);
1. makes each build not made yet: `cp -al b0` + its files (+ deletions), hard links throughout;
2. puts every per-build folder (`/game/code/assets`, `config`) home into its build, renames
   (never symlinks: ED's install `rm -rf`s through one), recorded in `pad/roots` after each
   rename so a power cut is recovered;
3. touches `uptest/.backup_file` (a power-off at the first menu must not roll back);
4. shows the menu; kills the button reader before the game opens the board;
5. points `/game/pad/live` at the choice, makes every entry of uptest a symlink through it
   (lightshows, `_profile` ... - BJ/Scooby then find their own boot files unchanged), moves the
   build's `assets`/`config` folders into place, and runs `/game/pad/b<k>/uptest/main.x86_64`
   with uptest as its working directory.

Every failure ends on b0. A stock update later replaces `main.x86_64` and the menu is gone;
`/game/pad` stays (the owner can delete it from a stock install only by a restore image -
noted for the help).

| title | roots | board |
|---|---|---|
| Beetlejuice, Scooby-Doo, Looney Tunes | - | Warden |
| Evil Dead | `assets /game/code/assets` | Warden |
| Texas Chainsaw | `assets`, `config /game/code/config` | Warden |
| Halloween, Ultraman | `assets`, `config` | Pinotaur |

## P-ROC titles (Rick and Morty, Alice Cooper)

Possible, by a different hook; not built yet.

* **Rick and Morty**: plugging in a stick with `rm-gamecode*.pkg` runs `codeupdate` as root
  (udev), which wipes `/game/RickAndMorty`, decrypts (AES, the app's key) and runs the
  package's `run-on-update.sh` as root: the hook can install a launcher as
  `~/.local/rmstart.sh` (rw /home, run by X in `/game/RickAndMorty`). A build only works AT
  `/game/RickAndMorty` (a font path baked into the bytecode): builds are switched by
  renaming folders. `/home` has ~3.5 GB free for a 3.5 GB build: builds must share files by
  hard links. Buttons: libpinproc (dpprocsw), SD14/SD8/SD15. The game runs as `launch`, no sudo.
* **Alice Cooper**: `ac-gamecode.pkg` (exact name), installed by `codeupdate` (root) into
  `/game/code` after wiping it. The game installs the package's `xinitrc` when the current one
  lacks the words `uptest` and `delete`; the launcher's xinitrc must contain both. Unity screen
  + Python game both hard-code `/game/code`: switched by renaming. 14 GB free. Buttons
  SD14/SD10/SD15 via libpinproc.

## pinHeck System games: not possible as a file

One SD card, read only by the Propeller A/V chip, which takes the first `*.PRG` and the first
`DMD`/`SFX` folders by fixed name and reflashes the PIC32 game CPU from it on UPDATE CODE
(30-60 s, settings reset to defaults, no version check). The PIC32 holds one game, and only
the game program reads the flippers, so there is nowhere a menu could run without a new
Propeller kernel and a patched game program per title and version; America's Most Haunted
cannot even update its game code from the card. Owners can keep one card per build.

## Work list

1. DONE `spksw.c` - proven against the rig's Warden (Beetlejuice) and Pinotaur (Halloween)
   boards: presses and releases of L, R and START.
2. DONE `make PLATFORM=spk` (spkselect + spksw, static, `test/check_elf_spk.sh`).
3. DONE `padselect_spk.sh` + `test/padselect_spk_test.sh` (9 cases).
4. `mkspkmulti.py` - the builder: plan / build / verify / inspect / inject / media, the DP
   builder's command line. Reads every kind (tar.gz, tar, GPG-signed, GPG-symmetric), refuses
   images of different titles, writes b0 whole and d<k> as the differences, packs the output
   the way the primary came (signs a .beetlejuice, encrypts a code_*.pkg). `ensurespkselect.sh`.
5. `machine_sim.sh` - the whole thing in the rig, per family: the title's own install steps
   (profile copy / Halloween's helper), then power-ups through sway's command with the rig's
   board: menu shot, RIGHT + START, the chosen build in attract. Scooby-Doo, Evil Dead, Halloween
   at least (one per family), then every title.
6. The Multi-boot tab: `multiboot_backend.SPK`, `multiboot=True` on the Spooky manufacturer,
   the words, tests, help (docs/guide/multi-boot.md), the before/after shots.
7. P-ROC titles (above).
