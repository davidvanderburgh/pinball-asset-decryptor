# PAD-980 research: Looney Tunes, Rick and Morty, Alice Cooper - boot chain and update install

Sources (all D:\Pinball\images\Spooky): `2025.10.08.looney` (tar), `LT_AK3V_CLONEZILLA_A.zip`
(mmcblk1p2 ROOT / p3 GAME, saved 2021-11-13, last write 2024-02-08), `LT_clonezilla_kamrui.zip`
(sda3 root / sda4 game, 2024-05-23), `rm-gamecode-20220902.pkg` (AES, decrypted with games.py
RM key), `rick_and_morty_autoflash_usb.iso` (a flasher stick; the machine's root is in its
`/root/goldimage`), `ac-gamecode.pkg` (AES, AC key, 1.1.0.5), `ACNC_image.zip` (mmcblk0p3 root /
p4 game, saved 2018-06-04). Partitions were partclone-restored in WSL and read with debugfs.
Small extracts kept under C:\tmp\PAD-980\looney_proc (`*.out` = raw dumps, `ltgd/` = Looney's
GDScript, `acx/`, `rmx/` = the pkgs' scripts).

---------------------------------------------------------------------------------------------

## 1. Looney Tunes (Godot 4.1.2, project "GDToons", Warden board)

### Boot chain
Two OS generations exist; the newer is the same as Scooby-Doo's.

| | AK3V eMMC image (Debian 11) | Kamrui SSD image (Debian 12, 2024) |
|---|---|---|
| tty1 autologin | `agetty --autologin root` (`/etc/systemd/system/getty@tty1.service.d/override.conf`) | `agetty --autologin norville` |
| login script | `/root/.profile` | `/home/norville/.profile` |
| starts | `cd /game/code/uptest` then `xinit /usr/bin/i3 -- -nocursor vt1`; i3 config `exec --no-startup-id /game/code/uptest/main.x86_64` | `cd /game/code/uptest` then `sway`; `~/.config/sway/config` last line `exec --no-startup-id /game/code/uptest/main.x86_64` |
| sudo | is root | `/etc/sudoers`: `norville ALL=(ALL:ALL) NOPASSWD:ALL` |

* The command line is the bare path, no arguments; cwd is `/game/code/uptest` (inherited
  from the profile's `cd`). The Godot pack is inside `main.x86_64` (PCK at 82 MB offset), so
  `res://` does not depend on cwd.
* `/` is mounted `ro` (fstab: `noatime,nodiratime,ro,...`); `/game` (GAME partition) rw;
  `/tmp`, `/var/log` tmpfs 128M. `unlock-root`/`lock-root` = `/usr/sbin/*`:
  `mount -o remount,rw|ro /`. `/media` is a symlink to `/game/media`. hostname
  `haunted-mansion`.
* Profile = the install step (both images, same text; kamrui adds `sudo`):

```
if [ ! -f /game/code/uptest/.update_file ]; then        # an update is waiting
    unlock-root; mkdir -p /game/backup; rm -rf /game/backup/* ...
    gcp -r /game/code/uptest/* /game/backup/            # backup = the running build
    rm -rf /game/code/uptest/* .backup_file .update_file
    cat /game/update/version.txt
    gcp -r /game/update/* /game/code/uptest/; chmod +x .../main.x86_64
    touch /game/code/uptest/.update_file; rm -rf /game/update/* ...; lock-root
elif [ ! -f /game/code/uptest/.backup_file ]; then      # last update never ran OK
    ... rm -rf /game/code/uptest/*; gcp -r /game/backup/* /game/code/uptest/ ...  # roll back
fi
cd /game/code/uptest; sway        # (AK3V: xinit /usr/bin/i3 ...)
```

  The game writes `.backup_file` on every start: `autoloads/warden.gd` `_ready()` ->
  `create_backup_file()` -> `OS.execute("touch", ["/game/code/uptest/.backup_file"])`
  ("a thing DJ said was needed to let the game know the execution after update was
  successful"). No `.backup_file` at the next boot = restore from `/game/backup`.

### Update install (in-game, not udev)
* USB: udev `11-automount-usb.rules` mounts the stick at `/media` (= `/game/media`)
  (AK3V `mount ... /dev/%k /media`; kamrui `systemd-mount --owner=norville ... $devnode /media`).
  Nothing runs on plug-in.
* Service menu -> `modes/service_menu/util_update_code.gd`: lists `/game/media/` entries that
  `ends_with(".looney")`, takes the FIRST one; `unlock-root`; `cp` to `/game/tmp/`; md5sum
  compare against the stick; `mkdir -p /game/update`; `tar -xf /game/tmp/<f> -C /game/update/`
  (GNU tar, so plain or compressed); requires `/game/update/main.x86_64`; `rm
  /game/code/uptest/.update_file`; if `speaker_kit.hex` present, copies it to uptest and
  flashes the speaker light kit with avrdude; `rm -rf /game/tmp`; `lock-root`. The move into
  place happens at the next power-up (profile above).
* File-name rule: only the `.looney` suffix (the app's own convention `YYYY.MM.DD.looney`).
  `version.txt` is only printed. No signature, no encryption, no checksum beyond the copy md5.
* Update contents (2025.10.08): `main.x86_64` (1.75 GB), `speaker_kit.hex`, `version.txt`
  (`2025_10_08`). Everything in the tar is copied into `/game/code/uptest/` (`gcp -r
  /game/update/*`), subfolders included. The update cannot change OS files directly, but
  `main.x86_64` is simply executed by sway/i3, so a replacement `main.x86_64` (any
  executable, e.g. a shell script; the profile `chmod +x`es it) runs as norville (NOPASSWD
  sudo) / root - that is the hook. No LT code checks or rewrites the profile/sway config
  (unlike Scooby-Doo; grep of all 265 extracted .gd files).

### Where it reads / writes
* `user://` = `~/.local/share/godot/app_userdata/GDToons/`; `~/.local/share/godot` is a symlink
  to `/game/godot` (both images) -> `/game/godot/app_userdata/GDToons/`: `user_settings.cfg`,
  `user_data.cfg`, `user_audits.cfg`, `credit_data.cfg` + `*_backup.cfg`, `logs/`,
  `shader_cache/`, `vulkan/`. Keyed by project name only: EVERY LT build shares it.
* Absolute paths in the game: `/game/code/uptest/.backup_file`, `/game/code/uptest/speaker_kit.hex`,
  `/game/media/` (USB, logs dump, `speaker_kit.hex`), `/game/update`, `/game/tmp`. Nothing
  relative to cwd.

### Buttons (Warden)
* `/dev/WARDEN` = udev `SUBSYSTEM=="tty", ATTRS{product}=="WARDEN", SYMLINK="WARDEN"`, 115200
  baud (`warden.gd`: `baudrate := 115200`, DTR+RTS set on open). The game also accepts a
  `/dev/ttyUSB*` whose description contains WARDEN.
* `autoloads/switches.gd`: `FLIPPER_BUTTON_LL = 86`, `FLIPPER_BUTTON_LR = 80`,
  `FLIPPER_BUTTON_UL = 83`, `FLIPPER_BUTTON_UR = 82`, `START = 87` (also LAUNCH 85, ENTER 91,
  UP 92, DOWN 93, EXIT 94 per tools/spooky_emu/spktitles.py).
* A reader: open /dev/WARDEN 115200, poll `0x3E 0x98 <sw>` (get_switch_state) -> reply
  `0x3C 0x98 <sw> <0|1>`; changes arrive as `0x3C 0x01 <sw>` / `0x3C 0x00 <sw>`. Ping
  `0x3E 0x97` -> `0x3C 0x97 "WARDEN" 0x00` (spkwarden.py docstring). The board reports logical
  states; the cabinet buttons are not inverted. One opener at a time: the reader must close
  the port before the game starts (the game exits its port with `disable_coils()` /
  `close()`).

### Disk
* AK3V eMMC GAME p3 14.9 GB, 12.5 GB free (3,289,486 x 4 KiB). Kamrui SSD sda4 222.7 GB,
  216 GB free. One LT build = one file, 1.1-1.75 GB; installing needs it in `/game/tmp`
  (tar) + `/game/update` + `uptest` + `/game/backup` at once (~4x the update size).

---------------------------------------------------------------------------------------------

## 2. Rick and Morty (P3-ROC, Python 2.7 SkeletonGame, Arch Linux)

Machine root = flasher stick's `/root/goldimage`; `deploy_gold.sh` lays out: p1 FAT32 BOOT
(128 MB), p2 LUKS "GROOT" -> `/` (3 GB, `ro,noatime`), p3 LUKS "C137" -> `/home` (7.4 GB,
rw), p4 ext4 `pkgpart` (12.3 GB, `/game/tmp`, `user,noauto`). `/game` -> `/home/game/`,
`/media` -> `/home/game/media/` (symlinks on root).

### Boot chain
* `getty@tty1.service.d/override.conf`: `agetty --skip-login ... --autologin launch`.
* `/etc/passwd`: `launch:x:1000:986::/home/game/images/launch:/usr/sbin/startgame` - the login
  shell IS the start script (ro root, mode 555, owner launch).
* `/usr/sbin/startgame`: `bash /game/images/tools/bootcheck.sh` (shows `spooky-needupdate.png`
  and halts unless `RMGame.pyc`, `config.yaml`, `config/game_default_data.yaml`,
  `config/game_default_settings.yaml` exist in `/game/RickAndMorty`); trims `/game/log.txt`;
  `cd /game/RickAndMorty`; `export MALLOC_MMAP_THRESHOLD_=1024 MALLOC_MMAP_MAX_=0
  DISPLAY=spookyhhp:0 XAUTHORITY=~/.Xauthority`; `exec startx`.
* `~/.xinitrc` (= `/game/images/launch/.xinitrc`, on the rw /home): `openbox &`, `~/.fehbg &`,
  `exec ~/.local/rmstart.sh`; `~/.xserverrc`: `exec /usr/bin/X -nocursor -nolisten tcp`.
* `~/.local/rmstart.sh`: `python RMGame.pyc 2>> /tmp/runlog` (cwd `/game/RickAndMorty`).
* User `launch` (groups audio, input, video, log). No sudoers entries found
  (`/etc/sudoers` empty in the image, `/etc/sudoers.d` empty): the game itself is not root.

### Update install (udev, on plug-in, as root)
* `/etc/udev/rules.d/13-local.rules`: USB `sd[a-d][0-9]` add -> `systemctl start
  usb-mount@%k` -> `/usr/local/bin/pickup.sh add sdX1`: mount at `/media/<label>` then
  `/usr/bin/run-codeupdate`: `systemctl stop getty@tty1.service; pkill -u launch;
  DISPLAY=:0.0 python2 /usr/bin/codeupdate > /game/updatelog.txt`.
* `/usr/bin/codeupdate` (root): picks a file `startswith('rm-gamecode') and endswith('.pkg')`
  in any `/media/*` (the last one found); copies `game_user_data.yaml`/`game_user_settings.yaml`
  + log to the stick as `*_<epoch>`; `unlock-root`; `rm -rf /game/RickAndMorty/*`; `mount
  /game/tmp` (pkgpart); `/usr/bin/pkgprocess <stick>/<file>`; then if
  `/game/RickAndMorty/run-on-update.sh` exists `bash` it and delete it; copies
  `game_user_*` from the stick back into `config/`; `chmod -R 750`, `chown -R launch:launch
  /game/RickAndMorty`; cleans, `lock-root`; shows "update done" forever (power-cycle).
  No backup of the old build (it is deleted first).
* `/usr/bin/pkgprocess` (the on-machine decrypter, python2 + PyCrypto): `PACKAGE_SIGNING_KEY =
  '4t7w!z%C*F-J@NcRfUjXn2r5u8x/A?D('`; `<Q origsize><16B IV>` + AES-256-CBC, 24 KiB chunks,
  truncate -> `/game/tmp/code_decrypted.zip`; `unzip -qq -o ... -d /game/RickAndMorty`. No
  signature: anyone with the key makes a valid package (the app's crypto.encrypt_aes_pkg).
* The package CAN carry boot/OS changes: `run-on-update.sh` runs as root with `/` unlocked.
  The 20220902 one rewrites `/usr/sbin/startgame` (logging), copies
  `payload/libpinproc.so.2.0` to `/usr/local/lib`, `pinproc.so` to python site-packages,
  flashes P3-ROC firmware v2r14 (`pinprocfw`), installs mesa via pacman, updates
  `/usr/bin/codeupdate` and `pkgprocess`, udev rules, fstab, `grub.cfg`
  (`iommu_gfx_disable`, commented out), then `rm -r payload`.

### Where it reads / writes
* Settings/audits/scores: `/game/RickAndMorty/config/game_user_data.yaml`,
  `game_user_settings.yaml` (RMGame.pyc strings: `/config/game_user_data.yaml` after the game
  dir); `config.yaml` paths are relative (`./assets/...`, `./config/`); machine yaml
  `config/RM_PROTOTYPE1.yaml` (named in RMGame.pyc).
* ABSOLUTE: `procgame/desktop/desktop_pysdl2.pyc` has `/game/RickAndMorty/assets/fonts/...`
  baked in (the rig binds the build there for this reason, tools/spooky_emu/proc/README.md).
  So a build only runs correctly AT `/game/RickAndMorty`.
* Log: `/tmp/runlog` -> filtered into `/game/log.txt` by startgame's `logcheck`.

### Buttons (P3-ROC via libpinproc)
* `RM_PROTOTYPE1.yaml` (and WHITEWOOD1, JANKYV2): `machineType: pdb`, `flipperLwL: SD14`,
  `flipperLwR: SD8`, `startButton: SD15`, `launchBall: SD11`, `flipperUpR: SD10`, service
  `enter SD4, up SD5, down SD6, exit SD7`. The game's own `procgame/game/pdb.pyc` reads
  `SD<n>` as a dedicated switch, P-ROC switch number n (same rule as TBL in dp_emu/MULTIBOOT.md).
* Library on the machine: `/usr/local/lib/libpinproc.so.2.0` (soname `libpinproc.so.2.0`,
  NEEDED `libusb-0.1.so.4`, `libftdi1.so.2`, libstdc++), symlink `libpinproc.so`; the
  package re-installs it from `payload/` every update (127,088 bytes, md5 f5ff7f9c...).
  Python binding `/usr/lib/python2.7/site-packages/pinproc.so` (pinproc 2.0). Header
  `/usr/local/include/p-roc/pinproc.h`. P3-ROC firmware forced to >= 2.14.
* Only one process may own the FTDI P3-ROC: the reader must exit before RMGame starts.

### Disk
* `/home` (C137) 7.4 GB holds the OS user files + the 3.5 GB build (rm zip uncompressed
  3.51 GB) -> roughly 3-3.5 GB free, i.e. NOT room for a second full build. `pkgpart` 12.3 GB
  is mounted only during an update (and must be empty-ish: codeupdate `rm -rf /game/tmp/*`).
  (Sizes from deploy_gold.sh's parted lines; no live machine image of /home was available.)

---------------------------------------------------------------------------------------------

## 3. Alice Cooper's Nightmare Castle (P3-ROC, Python 2.7 SkeletonGame + Unity 2019 screen)

Image 2018-06-04 (Arch, eMMC): p3 root `/` `ro,noatime` (4 GB), p2 swap, p4 `/game` rw
(16 GB, 3.2 GB used = 14 GB free in the image). Note the image predates the Unity screen
(no `uptest/`); the current pkg (1.1.0.5) upgrades the OS files itself (below).

### Boot chain
* `getty@tty1.service.d/override.conf`: `agetty --autologin root`; root's home is `/game`
  (`root:x:0:0:root:/game:/bin/bash`).
* `/game/.profile`: `export XAUTHORITY=/game/Xauthority PINBALL_ENV=production; netup; if
  [ ! -f /game/.nostart ]; then [[ $(fgconsole) == 1 ]] && exec startx -- -nocursor vt1; else
  rm -rf /game/.nostart; fi`.
* startx -> `/etc/X11/xinit/xinitrc` (ro root). In the image: `cd /game/code; python2
  ACGame.py >> /game/log.txt 2>&1`. The package's `xinitrc` (installed by the game, below):
  `chmod +x /game/code/uptest/main.x86_64; cd /game/code/uptest; ./main.x86_64 . &;
  cd /game/code; find /game/log.txt -size +100M -delete; python2 ACGame.py >> /game/log.txt 2>&1`.
  The Unity player is the screen, talking to the Python game on TCP 127.0.0.1:9999.
* `refind_linux.conf` in the pkg: `"Pinix" "root=/dev/mmcblk0p3 rw quiet ..."` (rEFInd boot).
* Runs as root throughout; `sudoers` has `pinball ALL=(ALL) ALL` (password) - irrelevant.

### Self-healing OS files (the "launcher reads /sbin/codeupdate" note)
`mainFunctions.pyc` at start (strings, in order): reads `/sbin/codeupdate`, wants `SYNC_FIX`
and `LOG_FIX` in it, else `unlock-root; rm -rf /sbin/codeupdate; cp -rf /game/code/codeupdate
/sbin/codeupdate; lock-root`; then `rm -rf /game/code/codeupdate`; reads
`/etc/X11/xinit/xinitrc`, wants `uptest` and `delete` in it, else `cp -rf /game/code/xinitrc
/etc/X11/xinit/`; `rm -rf /boot/refind_linux.conf*; cp -rf /game/code/refind_linux.conf
/boot/`; `reboot`. (`/sbin` -> `usr/bin` on Arch, so `/sbin/codeupdate` IS
`/usr/bin/codeupdate`.) So THE PACKAGE CAN CARRY BOOT FILES (xinitrc, codeupdate,
refind_linux.conf), installed by the game. A replacement xinitrc survives this check as long
as it contains the words `uptest` and `delete`. `run-on-update.sh` (userdel pinball, copies
xinitrc) is in the pkg but nothing in AC's codeupdate runs it.

### Update install (udev + updatemon, as root)
* `/etc/udev/rules.d/11-automount-usb.rules`: on add, mount at `/media/<label>` (`/media` ->
  `/game/media`) and run `/usr/bin/run-codeupdate`, which only `touch /game/.nostart
  /game/.doupdate` ("THE CODE UPDATE PROCESS HAS CHANGED TO BE RUN OUTSIDE OF UDEV").
* `updatemon.service` (multi-user, root) -> `/usr/bin/updatemon`: loop; when
  `/game/.doupdate` exists: remove it, `killall -9 startx`, `DISPLAY=:0.0 python2
  /usr/bin/codeupdate > /game/updatelog.txt`.
* `codeupdate` (pkg version with SYNC_FIX/LOG_FIX): needs a file named EXACTLY
  `ac-gamecode.pkg` in a `/media/*` dir (no stick file = it copies audits to the stick and
  stops). Copies `/game/code/config/game_user_data.yaml`, `game_user_settings.yaml`,
  `/game/log.txt` to the stick (`*_<epoch>`); `unlock-root`; `rm -rf /game/code/*
  /game/tmp/*`; copies the pkg to `/game/tmp/`; `/usr/bin/pkgprocess /game/tmp/ac-gamecode.pkg`;
  umounts; `lock-root`; shows "update done" forever.
* `/usr/bin/pkgprocess`: key `'cc180ac8e1239a56fcc5d3dcccccaaac'`, same AES-CBC format;
  `unzip -qq -o` into `/game/tmp/extracted`, then `cp -rf /game/tmp/extracted/* /game/code/`.
  No signature. User data is NOT copied back: `game_user_*.yaml` are lost unless the pkg
  carries them (`game_default_*` are the fallbacks) - the stick copies are the only backup.
  The pkg carries `uptest/` and an identical `uptest_backup/`.

### Where it reads / writes
* Python: `ACGame.py` loads `config/alice.yaml` relative to its own file
  (`curr_file_path`); `config.yaml` paths relative. ABSOLUTE in bytecode: `/game/gamedata.txt`,
  `/game/servodata.txt` (mainFunctions, utility_servos), `/game/code/my_modes/*`
  (Utilities.pyc), `/game/code/codeupdate`, `/game/code/xinitrc`, `/game/code/refind_linux.conf`,
  `main.pyc`: `python2 /game/code/ACGame.py`. Settings/audits/scores:
  `/game/code/config/game_user_data.yaml`, `game_user_settings.yaml` (+ `/game/gamedata.txt`).
* Unity screen (`uptest/main_Data/Managed/Assembly-CSharp.dll`): `/game/code/assets/dmd/`,
  `/game/code/assets/dmd/animations`, `/game/code/config/` when `/game/DO_NOT_DELETE` exists,
  else the developer's `C:/ALICECOOPER/AliceCooper/...`. So the screen ALWAYS reads the
  assets at `/game/code`, whatever folder it runs from.
* Log `/game/log.txt`, `/game/updatelog.txt`.

### Buttons (P3-ROC via libpinproc)
* `config/alice.yaml`: `machineType: pdb`, `numBalls: 4`, `flipperLwL: SD14`, `flipperLwR:
  SD10`, `startButton: SD15`, `launchBallButton: SD11`, `flipperUpR: SD9`, `enter SD4, up
  SD5, down SD6, exit SD7`. (`alice-base.yaml` differs: launch SD120, no flipperUpR.)
* `/usr/lib/libpinproc.so.2.0` (2016, soname `libpinproc.so.2.0`, NEEDED libusb-0.1,
  libftdi1, libstdc++; md5 f61af168... - a different build from R&M's); python
  `/usr/lib/python2.7/site-packages/pinproc.so` (pinproc 2.0). Not updated by the AC pkg.
  The pkg ships its own `procgame/`. One FTDI owner at a time.

### Disk
* `/game` 16 GB (17.2 GB partition), 3.2 GB used in the 2018 image; current code 1.67 GB
  uncompressed (assets dominate). An update needs pkg + decrypted zip + extracted copy in
  `/game/tmp` (~3x 1.4 GB) on the same partition. Room for several builds.

---------------------------------------------------------------------------------------------

## Implications for a boot-menu launcher

General
* All three have a read-only `/` and a rw game partition; root access is available to the
  update path on all three (LT: the profile/user; R&M: codeupdate + run-on-update.sh; AC:
  root everything). None checks a signature; the AES pkgs are just encrypted zips.
* The flipper/START reader must release the board (Warden tty / FTDI P3-ROC) before the game
  starts, as dpprocsw does for TBL.
* Every stock updater DELETES its install dir first (`rm -rf /game/code/uptest/*`,
  `/game/RickAndMorty/*`, `/game/code/*`): extra builds must live OUTSIDE it (e.g.
  `/game/pad/<build>`), and a stock update must leave the menu harmlessly out of the picture.

Looney Tunes - easiest
* Hook: the update's `main.x86_64` IS the launcher (script or static binary); sway/i3 runs it
  with cwd `/game/code/uptest`. It can carry the builds as subfolders (they get copied into
  uptest AND into `/game/backup` on the next install: 2x space per build; 12.5 GB free on
  eMMC fits ~3 builds of 1.75 GB with the install's temporary copies; SSD unlimited).
  Better: on first run move builds out to `/game/pad/` and keep uptest small.
* A build can run from any folder (no cwd/relative reads). But all builds share
  `/game/godot/app_userdata/GDToons/*.cfg` (settings/audits/scores); an old build may misread
  a newer build's cfg. A launcher can swap the `GDToons` dir per build (or keep it shared).
* The game must touch `/game/code/uptest/.backup_file` (it does at `_ready`, absolute path) or
  the next boot restores `/game/backup` - a free fallback if the launcher dies before the
  game starts; the launcher should not remove it.
* Exiting the menu: a stock `.looney` install replaces uptest (menu gone), backup = the menu.
* Display: sway (Wayland, kamrui, user norville) vs i3/Xorg (AK3V, root): the menu must draw
  on both (Wayland client or XWayland; sway runs XWayland by default unless disabled - not
  checked).

Rick and Morty - hard
* Hooks: `run-on-update.sh` runs as root at install (can rewrite `~/.local/rmstart.sh`,
  `.xinitrc` - both on the rw /home - or `/usr/sbin/startgame`). The cleanest wrap is
  `/game/images/launch/.local/rmstart.sh` (rw, run by X with cwd `/game/RickAndMorty`).
* A build only works AT `/game/RickAndMorty` (baked font path; bootcheck.sh checks files
  there; user yaml there): switching builds means renaming/symlinking folders before `python
  RMGame.pyc` (rename on the same fs is instant; `/game/RickAndMorty` could become a symlink -
  but codeupdate's `rm -rf /game/RickAndMorty/*` and `chown -R` would then act on the target).
* Space: /home is 7.4 GB with a 3.5 GB build -> a second full build does not fit; builds would
  have to share assets (hard links) or differ only in code.
* The game runs as `launch` with no sudo; the menu reader must also run as launch (FTDI access
  via the `proc`/udev group? not verified) or be started from startgame/xinitrc before the game.
* Each update also re-installs libpinproc/firmware - a multi-boot pkg must carry or skip that.

Alice Cooper - medium
* Hook: the pkg's `xinitrc` (installed by the game into `/etc/X11/xinit/xinitrc` if the
  current one lacks `uptest`/`delete`, followed by a reboot). The game copies
  `/game/code/xinitrc` only when those words are MISSING, so a launcher xinitrc that contains
  both stays in place. Runs as root. Alternatively replace `/game/.profile` (rw, root's home).
* Two processes per build (Unity screen + Python game) and both hard-code `/game/code`
  (Unity assets/config, `python2 /game/code/ACGame.py`, my_modes, codeupdate copy): a build
  must be AT `/game/code` (rename/swap folders or bind-mount over `/game/code` before starting
  either process). `/game/gamedata.txt`, `/game/servodata.txt` are shared by all builds.
* An AC stock update wipes `/game/code/*` and does not restore user yaml (they are on the
  stick); builds kept elsewhere on `/game` survive; 14 GB free = room for several builds.
* The game's self-heal also rewrites `/sbin/codeupdate` (needs SYNC_FIX/LOG_FIX) and
  `/boot/refind_linux.conf` and REBOOTS when its checks fail - a menu-chosen older build with
  an older check could trigger a reboot loop if the installed files don't satisfy it.
