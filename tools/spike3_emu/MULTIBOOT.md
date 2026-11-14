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
