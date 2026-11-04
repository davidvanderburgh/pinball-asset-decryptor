# PAD-980 research: how the Unity Spooky titles boot and update

Titles: Beetlejuice (BJ), Texas Chainsaw Massacre (TCM), Evil Dead (ED), Halloween (H78), Ultraman (UM).
Date: 2026-11-03. Scratch area and evidence: `C:\tmp\PAD-980\warden_unity\` (decompiled C# in `<title>/src`, dumped boot files in `<title>_root/`, `<title>_game/`, restore logs in `logs/`).

Sources:
- updates `v2026.09.15.11.beetlejuice`, `tcm-1_00.pkg`, `2026.07.15.ed`, and the rig caches of `code_H78.pkg` v1.18.1 / `code_UM.pkg` v1.18 (PAD-Runtime `/var/tmp/pad_spooky/cache/{h78_v118,um_v1_18}`)
- Clonezilla images `bj_production_base_image_2026.04.10.zip` (sda3 root, sda4 /game), `clonezilla-live-tcm_prod_base_image_2024_02_10.zip` (mmcblk0p2 root, p3 /game), `ED_clonezilla_base_image_2025_02_27.iso` (sda3 root, sda4 /game), `h78_image_108a.zip` / `um_image_108a.zip` (mmcblk0p3 root, p4 /game)
- I decompiled each `Assembly-CSharp.dll` with ilspycmd 8.2 (`DOTNET_ROLL_FORWARD=Major`)

The titles fall into **three families**:

| family | titles | OS | autologin user | the game runs as | how the game starts | who installs an update |
|---|---|---|---|---|---|---|
| A: sway, norville | BJ, ED (and Scooby) | Debian 12 | norville (NOPASSWD sudo) | norville | `~/.profile` -> `sway` -> `exec /game/code/uptest/main.x86_64` | `~/.profile` at the next boot |
| B: i3, root | TCM | Debian 12 | root | root | `/root/.profile` -> `xinit /usr/bin/i3` -> `exec /game/code/uptest/main.x86_64` | `/root/.profile` at the next boot |
| C: Pinix / startx, root | H78, UM | Arch ("Pinix") | root (home = /game) | root | `/game/.profile` -> `startx` -> `/etc/X11/xinit/xinitrc`: `cd /game/code/uptest; ./main.x86_64` | a C helper (`/game/test`) run by the game itself, right away |

On every title the root filesystem is mounted **read-only** (fstab `ro`). `unlock-root` / `lock-root` run `mount -o remount,rw|ro /`. `/game` is a separate read-write ext4 partition.

---

## Beetlejuice (family A)

**1. Boot chain**
- `getty@tty1` override (`bj_root/getty_override.conf`): `ExecStart=-/usr/sbin/agetty --autologin norville --noclear %I $TERM`.
- `/home/norville/.profile` (byte-identical to the update's `_profile`). On tty1 it runs `sudo chown -R norville:norville /game`, does the update/restore step (below), then the chowns and the speech sidecar (`source /game/vosk-env/bin/activate; python /game/vosk/speech.py &`). After that come `cd /game/code/uptest` and `sway`.
- `/home/norville/.config/sway/config`: `exec --no-startup-id /game/code/uptest/main.x86_64`. The game inherits the profile's working directory, `/game/code/uptest`.
- `/etc/sudoers`: `norville ALL=(ALL:ALL) NOPASSWD:ALL`. Passwordless sudo covers everything. `/etc/sudoers.d` holds only the README.
- hostname `haunted-mansion`. `Machine.cs:188`: the game is "virtual" (skips shell calls) unless the hostname contains `haunted-mansion`.

**2. Update install**
- Trigger: service menu USB update (`Service_menu_mode.cs` ~2980). It lists `/game/media/*.beetlejuice`, skipping names that start with `.`. Any name ending in `.beetlejuice` is accepted. There is no version comparison: the operator picks the file. A WiFi path downloads `release-code` / `beta-code` from Spooky's server.
- `update_software_from_USB_coroutine` (`Service_menu_mode.cs:3277`):
  1. `sudo unlock-root; rm -rf /game/logs/*; rm -rf /game/tmp/*`, then `cp /game/media/<name> /game/tmp/<name>.gpg`
  2. compares the md5 of the copy with the source
  3. runs `gpg -d /game/tmp/<name>.gpg > /game/tmp/<name>; echo $?`. This is a **signature check** against norville's keyring. If gpg does not exit 0, the update stops (`"GPG signature could not be verified"`) unless **developer mode** is on. In developer mode a chain of joke confirmation dialogs lets the update continue anyway. Developer mode is entered by holding MenuBack while pressing MenuEnter, or comes on by itself when no factory defaults are saved (`Service_menu_mode.cs:3874-3884`).
  4. `rm -rf /game/update/*; tar -zxf /game/tmp/<name> -C /game/update/`
  5. if `/game/update/main.x86_64` exists, deletes `/game/code/uptest/.update_file`, then shows "INSTALLATION SUCCESSFUL! RESTART MACHINE".
- At the next boot, `~/.profile` sees no `.update_file`. It runs `unlock-root` and backs up `gcp -rf /game/code/uptest/* /game/backup/`, then `rm -rf /game/code/uptest/*` and `gcp -rf /game/update/* /game/code/uptest/`. After that it runs `chmod +x main.x86_64` and `touch .update_file`. `#rm -rf /game/update/*` is commented out, so the unpacked update **stays on disk**. If `.backup_file` is missing (and no `.reboot_file`), it restores from `/game/backup` instead.
- **The update is flat**: the archive root *is* `uptest/` (`main.x86_64`, `UnityPlayer.so`, `main_Data/`, `lightshows/`, `speaker_kit.hex`, `version.txt`, `splash.png`).
- **The update carries boot files and the game installs them** (`Machine.cs:208`, `ReplaceOldFileNewFile`). At every start it md5-compares and, if they differ, runs `sudo unlock-root && cp new old && sudo lock-root`. The pairs are:
  - `/game/code/uptest/11-automount-usb.rules` -> `/etc/udev/rules.d/11-automount-usb.rules`
  - `/game/code/uptest/_profile` -> `~/.profile`
  - `/game/code/uptest/sway_config` -> `~/.config/sway/config`
  - `/game/code/uptest/speech.py` -> `/game/vosk/speech.py`

  After any replacement it runs `touch .reboot_file; sudo reboot`. A second replacement while `.reboot_file` exists counts as a boot loop: it deletes `.backup_file` and reboots, so the profile restores the backup. A missing new file means no replacement. The 2026.09.15 update ships `_profile`, the udev rule and `speech.py`, but no `sway_config`. The game only does this when not virtual (hostname check).
- After installing, the game touches `/game/code/uptest/.backup_file` (`Machine.cs:460`), which marks the build good.

**3. Where it reads files**
- Code/data: `main_Data` next to the executable (`Application.dataPath`).
- Absolute paths: `/game/code/uptest/lightshows`, `/game/code/uptest/speaker_kit.hex`, `/game/code/uptest/firmware.uf2`, and `/game/code/uptest/{_profile,sway_config,11-automount-usb.rules,speech.py}`.
- Settings, audits, scores, profiles, replay data and the rsa key live in `/game/code/config/` (`Settings.save_directory`, `Settings.cs:1494`). The profile's backup/install never touches that folder. Logs go to `/game/logs`. `/game/tmp` is wiped at every start.

**4. Disk**: `/game` = sda4, 239.1 GB, 19.5 GB used, 219.6 GB free on the factory image (partclone header). Root sda3 is 238 GB, about 9.6 GB used. An update is about 5.3 GB unpacked, held about 3x (code, backup, leftover `/game/update`) plus the tar in `/game/tmp` while it unpacks.

**5. Launcher hazards**: covered in the implications section. The main ones: absolute `/game/code/uptest/...` paths (lightshows, hex, `_profile`, `speech.py`); the boot-file replacement with reboot, keyed to `/game/code/uptest/_profile`; and GPG signing.

---

## Evil Dead (family A)

**1. Boot chain**
- `getty@tty1` autologin `norville` (same override as BJ, `ed_root/getty_override.conf`).
- `/home/norville/.profile` (`ed_root/home_norville_.profile`): same pattern as BJ. Differences: it backs up and installs both `uptest` and `assets` (`gcp -rf /game/update/uptest/* /game/code/uptest/`, `gcp -rf /game/update/assets/* /game/code/assets/`), there is no `.reboot_file` and no speech sidecar, and it does not remove `/game/update/*` after installing (only the marker files). It ends with `sudo chown -R norville:norville /game; cd /game/code/uptest; sway`.
- `~/.config/sway/config`: `exec --no-startup-id /game/code/uptest/main.x86_64`.
- `/etc/sudoers`: `norville ALL=(ALL:ALL) NOPASSWD:ALL`. Hostname `haunted-mansion`. Debian 12.
- The game itself calls `sudo timedatectl|date|hwclock` (`ed.cs:2371`).

**2. Update install**
- `menuUtilities.checkForUpdateMedia`: USB mounted at `/game/media` (udev `systemd-mount ... /media`). The game lists `*.ed`, skipping names that start with `._`, sorted by name, and the operator picks one. There is no signature check and no version comparison.
- `updateprocess.start_update` (`ed/src/updateprocess.cs`) runs `unlock-root`, then `cp /game/media/<f> /game/tmp/`, an md5 compare, `rm -rf /game/update/*` and `tar -zxf ... -C /game/update/`. If `/game/update/uptest/main.x86_64` exists, it runs `rm /game/code/uptest/.update_file`, then `lock-root`. There is no reboot; the operator power-cycles.
- Archive layout: `uptest/` (`main.x86_64`, `UnityPlayer.so`, `main_Data`, `.update_file`, `.backup_file`), `assets/` (1.82 GB), `version.txt`, `version_string.txt`. There is no `config/`.
- The ED code never compares or replaces the profile or sway config, so **an update cannot install boot files on ED**. Only `uptest/` and `assets/` get copied.
- The game touches `/game/code/uptest/.backup_file` once it is ready (`pinball_master.cs:71`).

**3. Files**
- `main_Data` is relative (`Application.dataPath`).
- Absolute paths: `/game/code/assets/{video,sfx,voice,lampshows}/`, `/game/code/assets/graphics_list.json`, `/game/code/uptest/speaker_kit.hex`.
- Settings and scores: `/game/game_settings`, `/game/settings`, `/game/audits/{highscores,modehighscores,lastscores,ed_tokens}.json`. Logs go to `/game/logs`.

**4. Disk**: `/game` = sda4, 239.1 GB, 8.6 GB used, 230.4 GB free. An update is about 2.0 GB unpacked. On the factory `/game` (restored from the image), the files are owned by norville and the folders are `assets audits backup code game_settings media logs update screenshots`. `/game/update` still holds a full `uptest` and `assets` after the install, which confirms that the profile leaves the unpacked update in place. `/game/code` has no `config/`.

---

## Texas Chainsaw Massacre (family B)

**1. Boot chain**
- `getty@tty1` override: `agetty --autologin root`. **The game runs as root.**
- `/root/.profile` (`tcm_root/root_.profile`) does the same update/restore step as ED, plus `config/` (`gcp -rf /game/update/config/* /game/code/config/`) and `rm -rf /game/update/*` after the install. Then: `cd /game/code/uptest; xinit /usr/bin/i3 -- -nocursor vt1`.
- `/root/.config/i3/config`: `exec feh --bg-fill /game/code/uptest/splash.png` ... `exec /game/code/uptest/main.x86_64`.
- There is no `/etc/sudoers` (sudo is not installed or not needed). Hostname `haunted-mansion`. Debian 12.
- `/media` is a symlink to `/game/media`. udev runs `systemd-mount $devnode /media`.

**2. Update install**
- Service menu "LOAD NEW CODE FROM USB" (`menuUtilities.cs:107`) lists `/game/media/tcm-*_*.pkg` with the regex `tcm-(\d+)_(\d{2})\.pkg`. The version number is parsed for display only; the operator picks the file.
- `updateprocess.cs` is identical to ED's, except that it also runs `rm -rf /game/logs/*`. There is no signature check.
- USB marker files trigger extra actions (`pinballController.check_update_process`):
  - `/media/debug`: `mv ~/.profile ~/.profile_` (disables autostart)
  - `/media/backup`: `cp -rf /game/code/* /game/backup/`
  - `/media/restore`: `cp -rf /game/backup/* /game/code/`
- Archive layout: `uptest/` (0.35 GB, Unity 2019 player), `assets/` (1.08 GB), `config/` (`asset_list.json`, `lightconfig.json`), `version.txt` ("TCM V1.00").
- The game never rewrites the profile or i3 config, so **an update cannot install boot files on TCM**.

**3. Files**
- `main_Data` is relative.
- Absolute paths: `/game/code/assets/sound/{sfx,voice,music}/`, `/game/code/assets/{dmd,lampshows}/`, `/game/code/config/lightconfig.json`, `/game/code/uptest/speaker_kit.hex`.
- Settings and audits: `/game/game_settings`, `/game/settings`, `/game/audits/` (`highscores.tcm`, error logs).
- Unity PlayerPrefs and Player.log go under `/root/.config/unity3d/Spooky Pinball LLC/TCM/`, which is on the read-only root.

**4. Disk**: `/game` = mmcblk0p3, **9.3 GB total, 3.5 GB used, 5.8 GB free** (debugfs stats on the restored partition). The factory `/game` holds code, backup and a few stray copies. An update is about 1.43 GB unpacked, and the pkg is 1.17 GB. While the game unpacks, a copy of the pkg sits in `/game/tmp` next to the unpacked tree. At install time the backup copy, the unpacked update and the new code all exist at once.

---

## Halloween and Ultraman (family C, Pinotaur)

The H78 and UM restore images have the same root filesystem (same UUIDs). Every boot file I compared is byte-identical (`cmp` of 15 files).

**1. Boot chain**
- `getty@tty1` override: `agetty --autologin root`. In `/etc/passwd`, root's home is **`/game`** (`root:x:0:0:root:/game:/bin/bash`), so the login shell runs **`/game/.profile`**, which lives on the writable game partition (`h78_game/game_.profile`):
  ```
  export PINBALL_ENV=production
  var=$(ps -ef|grep '[m]ain.x86_64'); if [ "$var" ];then reboot; fi
  rm -rf /game/.nostart
  [[ $(fgconsole) == 1 ]] && exec startx -- -nocursor vt1
  ```
- There is no `~/.xinitrc` in `/game`, so startx uses `/etc/X11/xinit/xinitrc` (on the read-only root). It ends with `cd /game/code/uptest; chmod +x /game/code/uptest/main.x86_64; ./main.x86_64`.
- The OS is Arch Linux "Pinix" (pinHeck's OS), hostname `pinix`. `sudoers`: `pinball ALL=(ALL) ALL`, but the game runs as root and never needs sudo.
- `/media` is a symlink to `/game/media`. udev mounts `sd[a-z][0-9]` on `/media`. `run-codeupdate` and the `updatemon.service` -> `/usr/bin/updatemon` -> `python2 /usr/bin/codeupdate` path are dead: `/usr/bin/codeupdate` is missing, and `/game/updatelog.txt` says so.

**2. Update install** (`h78_v118/src/updateMode.cs`, `updateprocess.cs`; UM differs only in names and passwords)
- `pinballController.check_update_process` polls every 5 s at attract. If `/dev/sdb1` (on SSD machines) or `/dev/sda1` (on eMMC machines) exists, it raises `machine_update_starting`. It runs automatically, with no menu.
- `GetPKGFileRenameIfNecessary("/media/")` takes the newest file matching `^code.+\.pkg$` and **renames it to `code_H78.pkg`** (UM: `code_UM.pkg`). With no pkg, the game exports logs instead.
- `updateprocess.start_update`:
  1. if `/game/code/config/test` exists, it moves that file to `/game/test` and makes it executable. This helper belongs to the **build currently installed**.
  2. it runs `/game/exe '<pkg>' <passphrase>`. `/game/exe` is a tiny ELF on the image that runs `system("/game/test %s %s &")`.
  3. it waits until no process named `test` is left. If `/game/update_error` exists, it retries once with **the other title's passphrase**, so an H78 machine will install a UM pkg and the reverse.
- `/game/test` from v1.18's `config/test` (17112 bytes; strings in `warden_unity`):
  1. `cp -rf /media/<pkg> /game/tmp/extracted/code.tar.gz.gpg`, then `gpg --yes --batch --passphrase=<P>` (symmetric decryption, **no signature**)
  2. `tar -xzvf code.tar.gz -C /game/tmp/extracted/update`
  3. if `update/uptest/main.x86_64` exists (an `access()` check only):
     - if `update/assets` exists: `rm -rf /game/backup/assets; mv /game/code/assets /game/backup; mv update/assets /game/code` (without it: "assets folder missing - running speedy", and assets are kept)
     - then the same backup-and-replace for `uptest`, and then for `config`

     If `update/uptest/main.x86_64` is missing, it does `touch /game/update_error`.
  4. Then `rm -rf ~/.nostart`. Afterwards the game runs `rm -rf /game/tmp/extracted/*`.
- The older helper on the 108a images (`/game/test` and `/game/code/config/test`, 8552 bytes) instead does `rm -rf /game/code/*; mv /game/tmp/extracted/update/* /game/code/`. It takes no backup and moves **every** top-level directory of the archive into `/game/code`.
- Archive layout: `uptest/` (`main.x86_64`, `UnityPlayer.so`, `main_Data`, `version_118.txt`), `assets/` (823 MB H78 / 1.2 GB UM), `config/` (avrdude, firmware .bin, `test`, `clear_cache.sh`, defaults, `asset_list.json`, `lightconfig.json`).
- There is no reboot. The game shows "done" and the operator power-cycles. Nothing in the update path touches `/game/.profile` or the xinitrc.
- **Boot files**: the update cannot write `/game/.profile` directly. However, `config/test` from an update becomes the helper that runs the *next* update, and that helper runs as root. Also, the game runs as root with `/game/.profile` on the writable partition, so any program installed as `uptest/main.x86_64` can rewrite `/game/.profile`.

**3. Files** (`staticVars.cs:126-136`)
- `config_location=/game/code/config/`, `safe_location=/game/`, `log_location=/game/logs/`.
- Media: `/game/code/assets/{dmd,sound/music,sound/sfx,sound/voice,lampshows}/`.
- Highscores in `/game/highscores.config` (defaults from `/game/code/config/default_highscores.config`). Settings via IOFeature live in `/game/<file>`, with defaults in `/game/code/config/<file>`.
- `rgbMode` runs `make -C /game/code/config`, and attract runs `/game/code/config/clear_cache.sh`.
- `main_Data` is relative to the exe.

**4. Disk**: `/game` = mmcblk0p4, **16 GB**. Free space on the factory images: H78 14.8 GB (used about 1.2 GB), UM 14.6 GB. The 64/128 GB variants (`*_64`, `*_128` zips) have other layouts (PARTITION_MAP); I did not check them.

---

## Implications for a boot-menu launcher (`uptest/main.x86_64` = script, builds in subfolders)

1. **The launcher can sit in every title's chain.** All five exec `/game/code/uptest/main.x86_64`. Family A execs it from sway, B from i3 (`exec`), and C runs `./main.x86_64` from the xinitrc after `chmod +x` (which is harmless). Each one starts it with the working directory `/game/code/uptest`. The Unity player finds `<exe>_Data` next to the real binary, so `cd builds/X && exec ./main.x86_64` works. No game checks its own exe, hashes its files or checks the process name.
   - **Caveat (C):** `/game/.profile` reboots if `ps` shows `main.x86_64` already running. That only matters for a second login shell. A launcher script whose argv contains `main.x86_64` still matches, which is harmless at boot.
2. **What each title's install step copies.** The payload must sit where the installer copies it:
   - A/B: only `/game/update/uptest/*`, plus `assets/*` (ED, TCM) and `config/*` (TCM). Builds therefore go inside `uptest/` (e.g. `uptest/builds/<name>/`). `gcp -rf` copies subfolders, and the top-level `*` glob skips only dotfiles.
   - BJ: the whole archive root becomes `uptest/`.
   - C (v1.18 helper): only `uptest`, `assets` and `config` are moved. Anything else is deleted with `/game/tmp/extracted`.
   - The installer's only validity check is that `uptest/main.x86_64` exists (BJ: `main.x86_64` at the root). A shell script passes it. The install scripts run `chmod +x`.
3. **Shared absolute paths conflict between builds.** Each title reads some per-build data from fixed paths, so the launcher must point them at the chosen build before it execs (symlinks or bind mounts; the games run as root on B/C, and as norville with NOPASSWD sudo on A):
   - ED/TCM/H78/UM: `/game/code/assets/...` and `/game/code/config/...`
   - BJ: `/game/code/uptest/{lightshows,speaker_kit.hex,firmware.uf2}`
   - TCM/ED: `/game/code/uptest/speaker_kit.hex`

   Settings, audits and high scores are shared by all builds (BJ `/game/code/config/*.json`; ED/TCM `/game/{game_settings,settings,audits}`; H78/UM `/game/*.config` and `/game/*.json`). Different versions may not agree on their format, so the launcher may need to keep a settings set per build.
4. **BJ boot files.** At every start, every BJ build md5-compares `/game/code/uptest/_profile`, `sway_config`, the udev rule and `speech.py` with the installed copies. On any mismatch it copies them in and **reboots**; a second mismatch while `.reboot_file` exists reverts to the backup. The multi-boot `uptest/` therefore needs one consistent set at the top level (a modified `_profile` / `sway_config` gets installed and then stays). Leaving them out disables the replacement. Scooby works the same way, with `_profile`, `sway_config` and `i3_config`.
5. **Markers and rollback.**
   - The A/B profiles roll back to `/game/backup` at boot if `/game/code/uptest/.backup_file` is missing. TCM, ED and BJ create that marker themselves once the game is up, so a launcher that never starts a game (menu only, power-off) leaves a pending rollback. To avoid it, the launcher should touch `.backup_file` itself once it is running.
   - `.update_file` must stay in `uptest/`. The profiles create it after an install; the ED and TCM archives also carry it.
6. **Signing and naming.**
   - BJ: GPG-**signed** with Spooky's key (`gpg -d` exit status). A third-party file installs only in developer mode, after the confirmation dialogs.
   - H78/UM: GPG-**symmetric** with the known passphrases. The file is any `code*.pkg` and gets renamed. It installs automatically when the USB stick is inserted at attract.
   - TCM: name must match `tcm-N_NN.pkg`, plain tar.gz.
   - ED: `*.ed`, plain tar.gz.
   - None of them compares versions.
7. **Disk space.**
   - **TCM is tight**: 9.3 GB partition, 5.8 GB free, about 1.43 GB per build. During an install the old code (as backup), the unpacked update and the new code coexist, plus the pkg in `/game/tmp` while it unpacks. Realistically **2 TCM builds at most** (3 if assets are shared).
   - H78/UM: 16 GB with about 14.7 GB free, about 1 to 1.4 GB per build. The v1.18 helper *moves* rather than copies, but the pkg, the decrypted tar and the extracted tree all exist at once.
   - BJ and ED: 239 GB partitions, no constraint.
8. **Installing boot files.**
   - Only BJ (and Scooby) install boot files from an update.
   - TCM, ED, H78 and UM never touch their profile or window-manager config from an update. On those titles the launcher itself (a script running as root on TCM/H78/UM, with sudo on ED) is the only way to change the boot chain. Because the chain already execs `uptest/main.x86_64`, it does not need to change.
