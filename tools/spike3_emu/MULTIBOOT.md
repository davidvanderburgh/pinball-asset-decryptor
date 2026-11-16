# Stern Spike 3 multi-boot (PAD-1263)

Several Spike 3 card images on ONE SD card, with a boot menu the machine shows at
power-up: NEXT / PREVIOUS on the coin door move the highlight, SELECT boots it, and
the countdown boots the remembered choice when nobody presses anything. The menu is
the code selector every other multi-boot platform carries
(`tools/spike2_emu/codeselect`), built for the Pi as `s3select`. The builder is
`mks3multi.py`; the menu program is installed by `ensures3select.sh`.

## How a Spike 3 machine starts its game

Read off the cards themselves (all eleven in the store, Buildroot 2024.08.1):

- p1 is the signed boot partition (kernel + initramfs); p2 the rootfs, p3 `/data`,
  p5 `/connectivity`, p6 `/games` - every one of p2..p6 LUKS2 `aes-xts-plain64` over
  ext4, opened with the board's OTP key. Only p1 is signed.
- `/etc/init.d/S95game` starts `reboot_monitor`, `conagent_monitor` (a loop over
  `/games/conagent`) and `game_monitor`, which kills `boot_display` and runs
  `/games/game` in a restart loop, reading its exit code (0 restart, 1 reboot, ...).
- `/games` on a stock card: `game`, `conagent`, `data`, `spike3` links into
  `<title>/`, the `<title>/` tree itself and `spk/`. The boot splash and `dprint`
  are `$GAMES_PATH/spike3/bin/...`.

So the game is chosen entirely by what `/games/game` is, on the one partition PAD's
Write already changes (through the user's own key). A multi-boot card leaves the
signed boot partition and the rootfs byte for byte as image 0's.

## What a multi-boot card is

Image 0's card, copied, with its games partition laid out as:

| path on p6 | what |
|---|---|
| `pad/img0/` | image 0's games tree, moved here whole (a rename) |
| `pad/img1/`, ... | every other image's games tree, copied whole (`cp -a` from its own card through dm-crypt), verified file for file |
| `pad/s3select`, `padselect.sh`, `font.ttf`, `images.conf`, `media/`, `build.json` | the menu, the hook, the menu's words and pictures, the build record |
| `game` | `-> pad/padselect.sh`: what `game_monitor` runs |
| `conagent`, `data`, `spike3`, `spk` | `-> pad/img0/...`: what the boot splash and `conagent_monitor` look for before the menu has run |

The builder writes beside the card the usual `.pad-build.json` with a fresh
`build_id`, so the emulator's store never mistakes it for image 0's card.

A card holds as many images as fit in image 0's games partition (35.4 GB; Fallout
LE is 11.2 GB, Pokemon LE 2.3 GB), up to nine. `plan` measures each card's used
bytes from its ext4 superblock through PAD's own decryptor, needing no root.

## On the machine

`padselect.sh` (codeselect/padselect_s3.sh), run by `game_monitor` as root:

1. `s3select` draws the menu on the backbox LCD and reads the coin door; it writes
   the chosen index to `/tmp/padselect.choice` and remembers it in
   `/data/padselect.last` (the next power-up's highlight);
2. the chosen `pad/imgN` is bind-mounted over `/games`, so the game sees exactly
   the tree it shipped in, at the path it expects;
3. `conagent` is killed; its monitor restarts it within a second from the tree
   now bound;
4. `/games/game` - now the chosen image's own link - is exec'd: the game replaces
   the shell, so `game_monitor` reads the game's own exit code, and every restart
   after that runs the game directly (the bind stays for the whole power-up).

Any failure (no menu, no choice, no such directory, the bind refused) boots img0 the
same way; if even that bind fails, img0's game runs straight from its directory. The
hook's cases are `test/padselect_s3_test.sh` (11, every branch).

Every image runs on **image 0's rootfs**. All eleven stored cards carry the same
Buildroot release; `plan` says so when the images' versions differ. `/data` (the
settings, audits and scores) is one store shared by every image, as on a Spike 2
multi-boot card.

### The menu on the Pi: `make PLATFORM=s3`

- **Display (egl_kms.c).** The Spike 3 game has no window system: Stern's own Godot
  display server opens `/dev/dri/card1` (or card0), renders into GBM buffers
  wrapped as EGL images through their dma-buf fds and shows them with
  `drmModeAddFB` + `drmModePageFlip`. The menu takes exactly that path (two
  buffers, a page flip per frame, the first frame by `drmModeSetCrtc`), so the same
  binary runs on the machine's Mesa and under PAD's emulator, whose shims answer
  the game's calls by name. The screen is connector index 1 when connected (the
  game's `display_number` on Pokemon and Fallout), else the first connected one;
  `PADSELECT_DRM_CONNECTOR` overrides. A KMS buffer's row 0 is the top of the
  screen, and the menu draws its top row there; PAD's presenter blits with the
  same rule, so the emulator shows what the LCD shows.
- **Buttons (stubs_s3.c).** `/dev/spidev4.0`, the CPU board's cabinet chain: mode 3,
  100 kHz, 8 bytes each way, active low; the menu sends eight zero bytes, as the
  game's first transfers do. Byte 0: bit 0 SELECT (boots), bit 1 NEXT, bit 2
  PREVIOUS (move), bit 3 BACK. The flippers and START are node-bus switches behind
  the bridge board, which only the game brings up, so the menu promises only the
  coin-door buttons and the footer says so.
- **No sound.** The cabinet amplifier is a TAS57xx the game starts over I2C; the
  menu does not, so it is silent and the build carries no sound sink.
- **Linked against stubs** of `libEGL.so.1`, `libGLESv2.so.2`, `libgbm.so.1` and
  `libdrm.so.2` (s3_stublibs.sh: the names and the symbols the menu imports; none
  of the four versions its symbols), so building it needs no card. `make check
  S3ROOT=<a card's rootfs>` proves every import resolves in a card's real libraries
  and that its glibc needs (2.38) are within the card's (2.39).

## In the emulator

`s3run.sh` (and the Emulate tab through `s3launch.sh`) runs `/games/game` as the
machine does, so the hook and the menu run first, under the same preloaded shims as
the game: the menu's frames are the run's frames, `s3press.py press SLOT 1` is NEXT
and `press SLOT 0` SELECT. The host-side readers (the switch list, the bridge, the
playfield) read `PAD_S3_IMAGE`'s tree, else the menu's `default=` image's. On a
multi-boot card the hook's log goes to the slot's `/data/padselect.log`.

A **checkpointable run** (the Emulate tab's, through `s3launch.sh`: pivot_root and an
explicit static qemu, so save states work) starts the game as a program under that
qemu, which cannot run the hook's shell script. There `s3run.sh` runs the hook first,
under binfmt with the same shims, in its menu-only mode (`PADSELECT_NOEXEC=1`: the
menu, the choice, the bind - then exit 0, or 3 when no bind could be made), and then
starts `/games/game` as for any card: by then it is the chosen image's own program,
checkpointable like any game.

## Back to the menu: hold BACK (PAD-1309)

Holding BACK on the coin door for 3 s (images.conf `back_hold=`, Menu settings' Hold BACK) during a game restarts the machine into the menu.
`padmenu.so` (codeselect/padmenu.c, `make PLATFORM=s3`) sits beside the menu; padselect.sh
copies it to /tmp before the bind and puts it first in the game's LD_PRELOAD.  It reads byte 0
bit 3 of the game's own transfers on `/dev/spidev4.0` and, after an unbroken hold, runs `sync;
reboot`.  In `s3run.sh` the restart is a stand-in that leaves
`<slot>/connectivity.up/dump/padmenu.restart`; `PAD_S3_MENU_SO=<host .so>` puts the object in
front on any card.  Proven on Fallout LE 0.82 (2026-11-14): a 2 s BACK did nothing, a 6.5 s
hold asked for the restart.  codeselect/DESIGN.md has the whole design.

## Editions: no menu, the game's EDITION picks (PAD-1325)

A card whose images are editions of one game (a Standard and a Dark Side look of Star Wars ELG,
say) shows no menu: the game's own EDITION setting (Adjustments > Machine Settings > Attract Mode)
picks the image at the next power-up, as on a Spike 2 card (PAD-495).

- **Each edition's Write** puts EDITION in the game's operator menu
  (`plugins/stern/spike3_menu.py`): the 64-bit program's spare setting taken over, the menu's
  category table grown so the Attract Mode page lists it (`menu_settings.grow_wide_program`,
  PAD-1321; the page found by its name, `menu_settings.wide_category`), read
  back, and the program put on the card whole. Takers: Star Wars ELG 1.10, Fallout 0.81 / 0.82,
  Transformers 0.96. Pokemon 0.82, both Star Wars 2025 and Walking Dead 0.92 use every setting
  EDITION could take and are refused with a sentence.
- **`mks3multi.py build|inject --editions`** reads every image's program (a card's through PAD's
  own decryptor; an existing card's trees on inject; a modes card through `pad/padmode/game.target`)
  and refuses unless every image is the same game at one version, carries EDITION for exactly as
  many editions as the card has images, names them alike and captions every setting alike (one
  settings store serves them all). images.conf gets
  `edition=/data/nv/<title>/NVM|<SHA1("EDITION")>|<n>`; `--no-editions` takes it off, and an
  inject with neither keeps what the card says. `verify` checks every tree's EDITION.
- **s3select** (codeselect `edition_boot`) reads the setting off the game's settings store before
  the game starts and boots that image; nothing read, or a value out of range, boots image 0. A
  Spike 3 store is Spike 2's export format behind a bigger header: the same `MAP0` counts and
  44-byte records keyed by the SHA1 of the caption, but its section table is u64 at 0xa8 (Spike 2:
  u32 at 0x7c) and its adjustments start 8 bytes past 336 + 40 x audits. `nvm.c` takes the
  adjustments' offset from that table. Each generation's `.crc32` is the CRC-32 of the file.

Proven 2026-11-16 (rig slot 125, hidden, muted; work/artifacts/PAD-1325/rig_proof.txt): the real
Spike 3 Write of Star Wars ELG 1.10 with editions "Standard, Dark Side" (486 s; the grown program
went on whole, its SD-validation record refreshed), a card of two editions built and verified with
`--editions`. A fresh machine booted edition 1 with no menu ("no store"); the game then stored
EDITION as its own setting (id 33, value 1, range 1-2); with EDITION = 2 in the store the next
power-up booted image 1 (DARK SIDE) with no menu. The operator menu reaches Machine Settings >
Attract Mode on the rig, but the Spike 3 emulator opens no setting page at all (the stock card
too), so the row on the page is checked from the program (`menu_settings.check`).

## Proven (2026-11-13, the emulator, real cards)

A card built by `mks3multi.py build` from `fallout_le-0_81_0` + `fallout_le-0_82_0`
(20 min, `verify` OK: both games trees identical file for file to their cards):

- binfmt run (`s3run.sh --bus --bridge`): the menu on HDMI-A-2 at 1920x1080 through
  the KMS/EGL-image path, the coin-door footer; the countdown booted image 0 from
  `/pad/img0`; NEXT then SELECT booted image 1, the game's `/games` bound from
  `/pad/img1` (Fallout's screens running);
- the app's launcher (`s3launch.sh`, hidden, checkpointable): the menu first, then the
  game as the process `game` under the explicit qemu, `/games` from the chosen tree;
  the next power-up's highlight was the image chosen last.

## Running it

```
# as root in WSL (losetup, dm-crypt, mount); plan needs nothing
bash tools/spike3_emu/ensures3select.sh                    # -> /var/tmp/s3select
python3 tools/spike3_emu/mks3multi.py plan  --primary A.raw --extra B.raw
python3 tools/spike3_emu/mks3multi.py build --primary A.raw --extra B.raw \
        --out /var/tmp/multi.raw --selector-dir /var/tmp/s3select \
        --titles "FALLOUT LE 0.81.0;FALLOUT LE 0.82.0" --timeout 20
python3 tools/spike3_emu/mks3multi.py verify --card /var/tmp/multi.raw \
        --primary A.raw --extra B.raw --selector-dir /var/tmp/s3select
```

A Windows `--out` is built in `--workdir` (default `/var/tmp/pad_s3multi`) and copied
there once finished: a loop device over a file on a Windows drive is never made.
