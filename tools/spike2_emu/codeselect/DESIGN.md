# codeselect — a boot-time code selector for Spike 2 (item 90)

*Behaviour and file formats. The mechanism facts (wire protocol, GL recipe,
card geometry, validation) are folded in below as they are established; the
authoritative queue entry is item 90 in `plans/TODO.md`.*

## What David asked for

One SD card that carries several complete game images for one machine, and a
menu at power-up that lets the player pick which one boots — flippers move the
highlight, START confirms — so a machine can run the stock Stern code or a
custom build (TMNT 1987 today; the Heisei Godzilla builds, normal and
orchestra, next) without swapping cards. The stock image has to keep passing
Stern's game validation and keep working with Insider Connected.

## Behaviour on the machine

1. Power on. u-boot, kernel and rootfs come up exactly as on a stock card
   (p1 and p2 are byte-for-byte Stern's). `boot_display` shows the Stern
   splash as usual.
2. `/etc/init.d/game` reaches its launch section, does its own
   `pkill boot_display`, and — the one added line — runs
   `/usr/local/codeselect/select.sh` if it exists.
3. `select.sh` runs `codeselect`, which owns the LCD until a choice is made:
   * A dark full-screen menu: title line, one card per image (name, version
     line, a short blurb), the highlighted card framed, and a footer with the
     controls and a countdown.
   * LEFT / RIGHT FLIPPER moves the highlight (wraps). Service **-** / **+**
     on the coin door do the same, as a fallback that needs no node bus.
   * START (or Service Select) confirms. When the countdown reaches zero the
     highlighted image boots by itself, so an unattended power-up still
     boots — the default highlight is the image that booted last time
     (`/data/codeselect.last`), falling back to the config's `default`.
   * `codeselect` exits with the chosen image's index; nothing else.
4. `select.sh` remounts `/games` from that image's partition (the primary
   image is already there from fstab, so index 0 is a no-op), records the
   choice in `/data/codeselect.last`, and returns.
5. Stern's own lines follow, untouched: `conagent_monitor`, `game_monitor`,
   `update`. The game finds its directory through `/games/game` exactly as it
   always has.

If anything in step 3 fails (program missing, exits non-zero, cannot open the
display or the bus), `select.sh` logs to `/dump/log/codeselect.log` and boots
the primary image — the card degrades to a stock card, never to a brick.

## Behaviour in the emulator (the proof of concept)

`PAD_CARD=<multi-image .raw> PAD_SELECT=1 watch.sh` — the same rootfs, the
same chroot, the same GL bridge window: the selector draws in the game window,
the keyboard flipper keys move the highlight, the START key confirms, and the
run continues into the chosen image's game exactly as a plain card run does.
The validation oracle is the same one the rig already uses: the Tech Alerts /
attract screen past 90 s with no `GAME VALIDATION ERROR` line, read by the
screen oracle and by a screenshot.

## Card layout

| part | type | content | from |
|---|---|---|---|
| p1 | FAT (0x0c) | zImage + dtb | primary image, verbatim |
| p2 | ext4 | rootfs + `/usr/local/codeselect/` + patched `/etc/init.d/game` | primary image, then patched |
| p3 | ext4 | games partition of image 0 (the primary) | verbatim |
| p4 | extended | grown to the end of the card | — |
| p5 | ext4 | `/data` | primary image, verbatim |
| p6 | ext4 | `/dump` | primary image, verbatim |
| p7… | ext4 | games partition of image 1, 2, … | each verbatim |

p1/p2 keep u-boot's `root=/dev/mmcblk0p2` and the FAT load valid; p3/p5/p6
keep fstab valid; the extra images are only ever reached by `select.sh`.

Sizes: an 8G image's games partition is 13,402,110 sectors (6.86 GB). Two
images need ≈14.7 GB (a 16 GB card), three ≈21.6 GB (a 32 GB card) - but a
third image lands on p8, and the card's kernel (i.MX6 3.14,
`CONFIG_MMC_BLOCK_MINORS=8`) allocates minors for mmcblk0 and p1..p7 only,
so `/dev/mmcblk0p8` never exists on the machine. TWO IMAGES IS THE LIMIT of
this layout: `mkmulticard.py` refuses more than one `--extra` unless
`--allow-unreachable` (emulator use), and a 3-image card needs two images
inside one partition - a design follow-up.

## Files on the card

```
/usr/local/codeselect/codeselect      the ARM program (EGL/GLES2 menu + input)
/usr/local/codeselect/select.sh       the hook: run the menu, remount /games
/usr/local/codeselect/images.conf     one line per image (below)
/usr/local/codeselect/font.ttf        DejaVu Sans Bold (Bitstream Vera licence)
/etc/init.d/game                      stock script + one guarded hook line
```

`images.conf` — plain text, `#` comments, `image=<device>|<title>|<subtitle>`
one per image (index = order, 0-based), plus `default=`, `timeout=` (0 = wait
for START) and an optional `font=`:

```
image=/dev/mmcblk0p3|STERN 1.59.0|Original Stern code
image=/dev/mmcblk0p7|TMNT 1987|1987 cartoon upscale (1.59.0)
default=0
timeout=15
font=/usr/local/codeselect/font.ttf
```

The builder writes this file; David can edit the names.

## The selector program

Built and tested in `tools/spike2_emu/codeselect/` (README.md there has the
full CLI, the log lines and the test list). What it is:

* C (the rootfs libstdc++ is GLIBCXX_3.4.20, gcc 13's C++ cannot link),
  cross-compiled with the rootfs used as the sysroot by hand (recipe D:
  `-nostdinc -isystem $ROOT/usr/include`, rootfs crt objects, `-nostdlib`,
  `-l:libc.so.6 libc_nonshared.a -l:libm.so.6 -l:libgcc_s.so.1`), so the
  binary demands at most GLIBC_2.17 and NEEDs only `libEGL.so.1
  libGLESv2.so.2 libc.so.6 libm.so.6 libgcc_s.so.1` - the rig's bridge shims
  in the emulator, Vivante's blobs on the machine, same exported names. The
  Makefile's `check` target enforces that ceiling with readelf.
* Files: `codeselect.c` (loop, CLI, menu state, countdown, choice/last
  files), `gfx.c` (software RGBA canvas, rounded frames, stb_truetype text
  with a glyph cache, 180-degree rotation, P6 PPM), `egl_stern.c` (Stern's
  EGL bring-up), `input.c` + `input_hw.c` + `input_padsw.c` (buttons),
  `conf.c` (images.conf), `log.c`; `select.sh`, `images.conf.example`,
  `fakebus.py`, `test/`.
* Draws into a software canvas sized from `fbGetDisplayGeometry` (1360x768
  on the bridge and the TMNT LCD) and presents it as ONE full-screen RGBA8
  textured quad: boot_display's exact EGL order and attribute lists,
  `#version 300 es` sprite shaders, VAO + VBO only, `glTexImage2D` once and
  `glTexSubImage2D` only when the canvas changed, LINEAR/CLAMP set
  explicitly, never `glPixelStorei`, a swap every frame, the bring-up
  retried 6 x 500 ms (boot_display may still hold the LCD), teardown that
  leaves default GL state then `eglMakeCurrent(dpy,0,0,0)` / `eglTerminate` /
  `eglReleaseThread`. Proven against the bridge libs on a private ring
  (attach, TEXIMAGE 1360x768, per-change TEXSUBIMAGE, 124 acked swaps at
  ~61 fps, exit 0); not yet run on Vivante.
* The menu: `SELECT GAME CODE`, one card per image (2-4, width scaled) with
  an `IMAGE n` label, the title (shrunk to fit, wrapped to two lines when it
  must) and the subtitle (wrapped to four), the highlighted card framed
  amber on a lighter fill, a footer `LEFT / RIGHT FLIPPER: choose   START:
  boot` and `booting <title> in N s` (or `press START to boot <title>` with
  timeout 0). Redrawn only on a state change. On confirm one `LOADING
  <title>...` frame, then exit. A key press restarts the countdown.
* Input backends (`--input`), a shared two-sample debouncer, press edges
  only, Service Back ignored (autoattract.sh presses it in the rig):
  * `hw` (default): the game's own tty setup on `/dev/ttymxc1` (460800 8N2,
    ASYNC_LOW_LATENCY, VMIN 0/VTIME 3, RTS pulse), the unaddressed bring-up
    + enumeration + `fe` identity reads (`--preamble min`; `full` also
    replays the byte-exact write-only frames captured before the game's
    first 0x11), then `88 02 11 65 0c` / `81 02 11 6c 0c` every 25 ms with
    per-node back-off when a board is silent; the node-0 cabinet word over
    `/dev/spidev1.0` (100 kHz mode 3, 8 bytes every 10 ms) for Service
    Select/Plus/Minus. Every ioctl failure is tolerated and the first 40
    exchanges are hex-logged. Tested against `fakebus.py` on a pty.
  * `padsw`: the rig's keyboard file (`PAD_SW_SHM`, 4096 bytes, `held[]` at
    8 / `scr_held[]` at 280) re-read every 20 ms, ids from
    `/dump/tables/$PAD_GAME/switch_list.txt` by wire position, platform ids
    (36/25-28) before a title has a table. Tested with a scripted padsw file.
  * `none`: countdown only (tests).
* `images.conf`: `image=<device>|<title>|<subtitle>` lines (index = order),
  `default=`, `timeout=` (0 = wait), `font=`; `--out` gets `<index>\n`,
  `--last` (`/data/codeselect.last`) is read for the initial highlight and
  written on confirm. Exit 0 = a choice was written, 2 = anything else.
* Honors `-invert` in `/games/data/boot_display_cmd` (parsed exactly as
  boot_display parses it) by rotating the presented pixels 180 degrees;
  `--invert`/`--no-invert` force it.
* `--headless FILE.ppm` renders without EGL and writes the last menu frame
  (plus `FILE.loading.ppm`): the offline test, and the screenshots.
* `select.sh` is the hardware hook: after `/etc/init.d/game`'s own
  `pkill boot_display ` it waits up to 3 s for boot_display to be gone, runs
  the selector, reads the index, looks up the device in images.conf, and
  when it is not what `/proc/mounts` shows at `/games`: `umount /games` +
  `mount -t ext4 -o ro,relatime,exec <dev> /games`, remounting
  `/dev/mmcblk0p3` if that fails or the new tree has no `game`. Every other
  failure boots the primary; it never touches `/mnt/boot` and logs to
  `/dump/log/codeselect.log`.

## Card builder

`mkmulticard.py` (run under WSL): takes the primary image and N extra images,
writes the layout above onto a sparse output file, injects the selector into
p2 with `debugfs -w`, verifies every copied range by digest and every ext4
by `e2fsck -fn`, and prints the `images.conf` it wrote. `--verify` re-checks
an existing output.

## What is deliberately NOT in the proof of concept

* Per-image NVRAM snapshots (settings/scores kept apart per image). Both
  TMNT images are 1.59.0, so the board NVRAM is shared cleanly; two different
  versions of one title may re-initialise on swap (the Beatles multi-boot
  finding). Designed for, not built.
* USB code updates while a non-primary image is selected write into that
  image's partition (the `update` script uses `/games`), which is the
  behaviour one would want; the primary's p3 is only updated when it is the
  one selected.

## Proven in the emulator (2026-09-01)

Card: `mkmulticard.py build` of `turtles_pro-1_59_0.Release` (primary) +
`TMNT 1987/turtles_pro-1_59_0.1987-upscaled` (extra) — 14,723,055,616 B,
p7 at LBA 15353856, `verify` PASS (every copied range md5-equal to its
source, every ext4 fsck-clean, p2 differs from stock by exactly the five hook
lines and `/usr/local/codeselect/`). Runs: `PAD_CARD=<that .raw>
PAD_CARD_CACHE=0 PAD_SELECT=1 PAD_AUDIO=0 watch.sh`, four times:

| run | keys (swpoke ids 64/65/36 = RIGHT/LEFT/START) | chose | result |
|---|---|---|---|
| 1 | right, left, start | 0 STERN 1.59.0 (p3, primary in place) | attract mode ~200 s after hand-off; NVRAM grades GE/CE/ZK = **P/P/P** in both slots (`nvgrades.py`); no validation banner |
| 2 | right, start | 1 TMNT 1987 (`bound over /games/turtles_pro` from p7) | attract; P/P/P; but the host video player still served the primary's clips (fixed: `dump/vidroot`) |
| 3 | right, start | 0 — the highlight had been remembered at 1, RIGHT wrapped to 0 | attract (the last-choice memory works) |
| 4 | right, start | 1 TMNT 1987 | `[padvid] clip root overridden by dump/vidroot: .../tmnt_multi.p7/turtles_pro`; attract shows the 1987 cartoon art |

The selector attached to the live GL bridge after padglhost was already up,
drew at ~60 fps, mapped the flipper ids from the title's switch table, and
exited 0 within 30 ms of START; watch.sh rode the `dump/selecting` flag
across the hand-off and `alive.sh` read 0 after every run.

## Testing on the machine (David)

1. Flash `D:/Pinball/TMNT 1987/multi/turtles_pro-1_59_0.multi-stock+1987patched.16G.sdcard.raw`
   (stock 1.59.0 + the Insider-clean patched 1987 build) to a 16 GB card with
   the app's *Build / flash SD card…* (any card ≥ 14,723,055,616 B) or
   `dd bs=4M conv=fsync`.
2. Power up. Expect the Stern logo, then within ~2 s of where the game would
   normally start: the SELECT GAME CODE menu. Flippers move, START boots;
   15 s countdown boots the remembered image. Service **−/+/Select** on the
   coin door do the same without the node bus.
3. If the menu never appears the card boots the primary (stock) by itself —
   nothing else changes. Pull `/dump/log/codeselect.log` (the card's p6, or
   through a root shell): look for `egl: up after N attempt(s)`,
   `nb: node 8 switches 00 ff 1f fb 40 00 00 00` (the first 0x11 answer) and
   `spi: rx ff 0f 0f …`. `short reply (timed out)` on every frame means the
   node board wanted more of the game's bring-up: rebuild the card with
   `--preamble full` in `select.sh`'s codeselect line (opt-in replay of the
   byte-exact captured frames) and send the log back.
4. Insider Connected: log in from the stock image first (it grades and
   persists P/P/P), then from the 1987 image.

