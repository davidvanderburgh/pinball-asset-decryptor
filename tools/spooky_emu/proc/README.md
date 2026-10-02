# Spooky Pinball P-ROC rig (Rick and Morty, Alice Cooper)

Runs Spooky's **P-ROC-era** games on this PC from their game-code `.pkg`,
on `tools/proc_emu`'s emulated P3-ROC (PAD-262), the way `tools/ap_emu/apiav`
runs Barry-O's BBQ. The Warden games (Beetlejuice on) are `tools/spooky_emu`'s
own, and so is Halloween on its Pinotaur board (PAD-268; Ultraman not yet).

| title | file | status (2026-09-30, PAD-269) |
|---|---|---|
| Rick and Morty | `rm-gamecode-20220902.pkg` | attract, played |
| Alice Cooper's Nightmare Castle | `ac-gamecode.pkg` (1.1.0.5) | attract, played |
| Total Nuclear Annihilation | `tna-gamecode.pkg` | refused: its .pkg key is not known |

"Played" = coins, Start, the ball served by the game's own trough-eject coil
into the shooter lane, launched by its own launch coil, switches hit and
scoring (Rick and Morty: 1,800 from three sling hits; Alice Cooper: 11,130
after the skill shot and slings), all hidden on a private display. Both from
`D:\Pinball\images\Spooky`; the restore images were not needed.

**In the app (PAD-319):** the Emulate Spooky tab runs both from their .pkg.
`tools/spooky_emu`'s own scripts hand them here: `watch.sh` sends a
`rm-gamecode*` / `ac-gamecode*` file to this `watch.sh` (setup.sh when the
Python is missing - exit 7 if that fails - then prepare.py, run_game.sh),
and `status.sh`, `stop.sh`, `cancel.sh`, `cache.sh` and `ctl.sh` answer for
whichever kind runs on the slot. The virtual playfield is the Warden games'
window (`spkpf.py`): `sppswitches.py` writes its table from the machine yaml
(numbered as the board numbers it), and `sppctl.py` answers its requests -
spkwarden's protocol - from proc_emu's board. Volume / Mute follow live
through `../spkvol.py`, which finds the game's streams by `SPK_MARK`.

## Why this is small

Both games are Python 2.7 SkeletonGame (PyProcGameHD) bytecode and ship
**their own copy of procgame** in the .pkg; nothing checks a licence or a
hardware ID. `pinproc` is the one module they take from the OS, and
proc_emu's pure-Python stub stands in for it, talking to `prochw.py`. No
game file is patched.

| the machine | the rig |
|---|---|
| `/game/RickAndMorty` (Arch Linux), `/game/code` (Alice Cooper, Debian) | the rig's hard-linked copy of the build, bind-mounted there in a private mount namespace (the games, and Alice Cooper's Unity player, use those paths) |
| Python 2.7 + pySDL2, SDL2_mixer/ttf/image, PyYAML, numpy, PIL, OpenCV, pyserial | `tools/ap_emu`'s py27 env (`/var/tmp/pad_ap/py27`, shared) |
| pygame, ffpyplayer | `setup.sh` -> `$SPP_ROOT/site` (pip `--target`, not in AP's env) |
| pypinproc + libpinproc, the P3-ROC on USB | proc_emu's `pystub/pinproc.py` + `prochw.py`, seeded from the title's machine yaml (trough full) |
| Alice Cooper's screen: `uptest/main.x86_64`, a Unity 2019 player on TCP 127.0.0.1:9999 | the same player (`-force-glcore`, llvmpipe), started first, in the slot's own network namespace |
| `unlock-root`, `lock-root`, `reboot`, `killall`, `mount`... | logging no-ops first on the game's `PATH` (`$SPP_RIG/shell.log`) |
| the cabinet LCD | a hidden Xvfb per slot (`:200 + slot`, 1280x720 / 1366x768), or WSLg |

## What the rig has to supply

* **pygame 2.0.3, not 1.9.6.** SkeletonGame takes its sound (pygame.mixer)
  and font lookup (`pygame.font.match_font`) from pygame. 1.9.6's wheel
  brings SDL 1.2 and its own libpng into a process that already has SDL2's,
  and dies on a native double free the first time an HD font is drawn. 2.0.3
  (SDL2, the last with a py27 wheel) is fine.
* **ffpyplayer.** Rick and Morty's `procgame/dmd/layers.py` imports it at
  the top (its mp4 movies). 4.0.1 is the last py27 wheel.
* **The paths.** `/game/RickAndMorty/assets/fonts/...` is baked into the
  bytecode; without the bind SkeletonGame's first font load raises IOError,
  which it reports as "Hardware connection failed".
* **Alice Cooper's OS files.** Its launcher reads `/sbin/codeupdate` (wants
  `SYNC_FIX` and `LOG_FIX` in it) and `/etc/X11/xinit/xinitrc` (wants
  `uptest` and `delete`); missing or old, it copies its own over them and
  reboots. Its package carries both, so `spprun.py` answers those two paths
  with copies of them (`SPP_OSFILES`). Its Unity player uses `/game/code/...`
  only when `/game/DO_NOT_DELETE` exists, else its developer's `C:/...`.
* **A ball model.** `prochw.py` gained one (off unless asked): a pulse of the
  eject driver moves a ball from the trough to the shooter switch half a
  second later, a pulse of the launch driver (or `plunge`) empties the lane,
  `drain` puts one back. `spprun.py` turns it on at attract with the driver
  numbers from the game's own coil objects - a PDB coil's number depends on
  the order the game set up its driver groups - named per title in
  `run_game.sh` (`BALLS`).

`spprun.py` also writes `attract` when a mode named *Attract* goes on the
mode queue (Rick and Morty's `CustomAttract`, Alice Cooper's `myAttractMode`)
and logs every mode added / removed to `$SPP_RIG/rig.log` - the games ship
bytecode and log little.

## Use

All in PAD-Runtime, as root; `PAD_SLOT=N` picks a slot (take a riglock slot
first).

```
T=/mnt/c/.../tools/spooky_emu/proc
bash $T/setup.sh                                  # once: pygame + ffpyplayer (and AP's env if missing)
python3 $T/prepare.py /mnt/d/Pinball/images/Spooky/rm-gamecode-20220902.pkg   # -> rm_20220902
python3 $T/prepare.py /mnt/d/Pinball/images/Spooky/ac-gamecode.pkg            # -> ac_1.1.0.5
bash $T/run_game.sh rm_20220902                   # Ready: rm_20220902, slot 0, display :200
bash $T/sw.sh tap coin1 150                       # free play by default on both
bash $T/sw.sh tap startButton 200                 # the trough ejects, the ball lands in the lane
bash $T/sw.sh tap launchBall 200                  # Rick and Morty; Alice Cooper: launchBallButton
bash $T/sw.sh tap slingRight 150                  # Alice Cooper: slingr
bash $T/sw.sh drain | plunge | balls | state | switches | drivers | log 20
bash $T/shot.sh /mnt/c/tmp/rm.png
bash $T/status.sh
bash $T/killgame.sh
bash $T/bootcheck.sh ac_1.1.0.5                   # VERDICT <build> pass|fail ...
```

Switch names are the machine yaml's: Rick and Morty
`config/RM_PROTOTYPE1.yaml`, Alice Cooper `config/alice.yaml`.
`run_game.sh --visible` draws on the WSLg desktop; `--audio` plays sound (a
hidden run stays silent unless asked, tools/rigboard.sh). The game's output is
`$SPP_RIG/game.out`, Unity's `$SPP_RIG/player.log`, the board's
`/var/tmp/pad_proc/rig<slot>/prochw.log`.

## What is open

* **Heavy**: Rick and Morty preloads its assets (~4 GB resident); Alice
  Cooper's Unity player renders on llvmpipe.
* No physics beyond the trough and the shooter lane: scoops, ramps, the
  portal trough (Rick and Morty), locks and the castle are switches you press.
* Alice Cooper's servos (PCA9685 over the P3-ROC's I2C) and its topper
  (`/dev/ttyUSB*`), Rick and Morty's Scorbit (`/dev/scorbit`): none - both
  games carry on without them.
* Sound and the visible window were not tried; every run here was hidden
  and muted.
