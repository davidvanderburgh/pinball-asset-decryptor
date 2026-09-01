# codeselect - the Spike 2 boot-time code selector (item 90)

One SD card, several complete game images; at power-up a menu on the LCD lets
the player pick the one that boots. This directory holds the selector program
that draws that menu and reads the buttons, the hook script that swaps the
`/games` mount, and the tests. The card layout and the emulator side are in
`DESIGN.md` and in the rig (`run_game.sh`/`watch.sh`).

```
codeselect.c     main loop, CLI, menu state, countdown, choice/last files
gfx.c/.h         software RGBA canvas: rectangles, rounded frames, TrueType
                 text (third_party/stb_truetype.h), 180-degree rotation, P6 PPM
egl_stern.c/.h   Stern's exact EGL/GLES2 bring-up + one textured quad
input.c/.h       the button events, the shared 2-sample debouncer
input_hw.c       node bus (/dev/ttymxc1) + cabinet SPI (/dev/spidev1.0)
input_padsw.c    the emulator's keyboard channel file (PAD_SW_SHM)
conf.c/.h        images.conf, /data/codeselect.last, the choice file
log.c/.h         stderr + --log file; '[select] ' stdout lines
select.sh        the hardware hook for /etc/init.d/game
images.conf.example
fakebus.py       a fake node bus on a pty (for --input hw without a machine)
test/            the checks `make check` / `make check-hw` run
Makefile
```

## Build

Needs Ubuntu's `arm-linux-gnueabihf-gcc` (13.x), `qemu-arm-static`, GNU make
4.x, python3, and the card rootfs copy at `/home/david/spike2root` (`ROOT=`).

```sh
make BUILD=/home/david/tmp/item90/sel            # -> $BUILD/codeselect
make BUILD=/home/david/tmp/item90/sel check      # ELF ceiling + headless + padsw + select.sh
make BUILD=/home/david/tmp/item90/sel check-hw   # fakebus.py node-bus test on a pty
make BUILD=... install DESTDIR=/some/stage       # -> $DESTDIR/usr/local/codeselect/
```

The binary must run on the card's glibc 2.21, so the rootfs is used as the
sysroot BY HAND (`-nostdinc -isystem $ROOT/usr/include`, the rootfs crt
objects, `-nostdlib`, `-l:libc.so.6 libc_nonshared.a`, recipe D of the build
report). `--sysroot` alone silently yields a GLIBC_2.34 binary; the
`-U_TIME_BITS -U_FILE_OFFSET_BITS -U_FORTIFY_SOURCE -fno-stack-protector
-fno-pie` flags are load-bearing. `check_elf.sh` enforces: max version node
`GLIBC_2.17`, NEEDED only `libEGL.so.1 libGLESv2.so.2 libc.so.6 libm.so.6
libgcc_s.so.1`, interpreter `/lib/ld-linux-armhf.so.3`. C only: the rootfs
libstdc++ tops out at GLIBCXX_3.4.20.

`make install` puts `codeselect`, `select.sh`, `images.conf.example` and
`font.ttf` (DejaVuSans-Bold from `/usr/share/fonts/truetype/dejavu/`, when the
build host has it; otherwise the card's own `/usr/local/spike/VeraMono.ttf` is
used at run time) under `$(DESTDIR)/usr/local/codeselect`. The card builder
injects that tree into p2 and writes `images.conf`.

## The program

```
codeselect [--conf PATH] [--out PATH] [--input hw|padsw|none] [--nodebus DEV]
           [--spi DEV|none] [--padsw PATH] [--tables PATH] [--timeout SEC]
           [--last PATH] [--default N] [--log PATH] [--headless FILE.ppm]
           [--invert|--no-invert] [--preamble min|full] [--font PATH]
```

| option | default | meaning |
|---|---|---|
| `--conf` | `/usr/local/codeselect/images.conf` | the menu (below) |
| `--out` | `/var/volatile/codeselect.choice` | written as one line `<index>\n` on success |
| `--input` | `hw` | `hw` = node bus + SPI, `padsw` = the rig's keyboard file, `none` = countdown only |
| `--nodebus` | `/dev/ttymxc1` | 460800 8N2, VMIN 0 / VTIME 3, ASYNC_LOW_LATENCY, RTS pulse - what the game does |
| `--spi` | `/dev/spidev1.0` | 100 kHz mode 3, 8-byte transfers every 10 ms; `none` disables |
| `--padsw` | `$PAD_SW_SHM` or `/dump/padsw` | the 4096-byte padsw file, re-read every 20 ms |
| `--tables` | `/dump/tables/$PAD_GAME/switch_list.txt` | `id num node bit name` rows; maps (8,25)/(8,24)/(1,11)/(0,8..11) to ids |
| `--timeout` | conf `timeout=`, else 10 | seconds; 0 = wait for START; a key press restarts it |
| `--last` | `/data/codeselect.last` | read for the initial highlight, written on confirm |
| `--default` | conf `default=`, else 0 | highlight when the last-choice file is missing/invalid |
| `--log` | none | appended; stderr always carries the same lines |
| `--headless` | off | no EGL; the loop runs (1360x768) and the last menu frame is written as P6 PPM; the LOADING frame goes to `FILE.loading.ppm` |
| `--invert` | auto | auto = `/games/data/boot_display_cmd` contains the token `-invert` (rotate 180, as boot_display does) |
| `--preamble` | `min` | `hw` only: how much of the game's node-bus bring-up to replay first |
| `--font` | conf `font=`, `/usr/local/codeselect/font.ttf`, `/usr/local/spike/VeraMono.ttf` | first that loads wins |

Exit status: `0` = a choice was written to `--out`; `2` = no choice (bad conf,
no font, display failure, interrupted).

Keys: LEFT FLIPPER / Service Minus = highlight left (wraps), RIGHT FLIPPER /
Service Plus = right, START / Service Select = confirm; Service Back is
ignored (autoattract.sh presses it in the rig). Two agreeing samples make a
state, a press edge makes one event, releases make none.

Picture: a dark 1360x768 (or whatever `fbGetDisplayGeometry` says) menu -
`SELECT GAME CODE`, one card per image (2-4, width scaled), the highlighted
card framed amber on a lighter fill, a footer `LEFT / RIGHT FLIPPER: choose
START: boot` and `booting <title> in N s` (or `press START to boot <title>`
with timeout 0). Titles shrink to fit and wrap onto two lines when they must;
subtitles wrap to four. On confirm one `LOADING <title>...` frame is drawn,
swapped, and the program exits. The canvas is redrawn only on a state change
(highlight, countdown second, confirm) and uploaded with one
`glTexSubImage2D`; `eglSwapBuffers` runs every frame regardless (the bridge
paces to 60 Hz).

### images.conf

```
# '#' comments; one image per line; index = order (0-based)
image=/dev/mmcblk0p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code
image=/dev/mmcblk0p7|TMNT 1987|1.59.0 - upscaled cartoon retheme
default=0          # highlight when there is no usable last-choice file
timeout=10         # 0 = wait for ever
#font=/usr/local/codeselect/font.ttf
```

`<device>` is the block device on hardware and an opaque token (`p3`, `p7`)
in the emulator. Up to 8 images; the menu is designed for 2-4.

### stdout lines (the rig forwards `[select]` to its event pane)

```
[select] menu: 2 images, highlight 1 (TMNT 1987) from last choice, timeout 10 s, input hw, invert 0, 1360x768, font ...
[select] key: left|right|start|select|plus|minus|back
[select] chose 1 TMNT 1987
[select] error: <what>
```

## The EGL path (egl_stern.c)

Byte-for-byte boot_display's `glWindow::create_window` (the game shares it):
`setenv FB_MULTI_BUFFER=2`, `fbGetDisplayByIndex(0)`, `eglGetDisplay`,
`eglInitialize`, `eglChooseConfig {RED 5, GREEN 6, BLUE 5, ALPHA DONT_CARE,
SAMPLES 0, DEPTH 24}`, `fbGetDisplayGeometry`, `fbCreateWindow(0,0,w,h)`,
`eglCreateWindowSurface(NULL)`, `eglBindAPI(ES)`, `eglCreateContext
{CLIENT_VERSION 2}`, `eglMakeCurrent`, clear + swap, `glViewport`, blend.
Then `#version 300 es` sprite shaders with `layout(location=0)`, VAO + VBO
only (the bridge refuses client-side arrays), ONE RGBA8 texture created with
`glTexImage2D` and updated with `glTexSubImage2D`, LINEAR/CLAMP set explicitly
(the bridge keeps per-name shadows across guests), never `glPixelStorei` (not
exported by the bridge). The whole bring-up is retried 6 times 500 ms apart
because on hardware boot_display may still be releasing the display. Teardown
leaves default-looking GL state (unbind, `glUseProgram(0)`, blend off, one
black frame), then `eglMakeCurrent(dpy,0,0,0)`, `eglTerminate`,
`eglReleaseThread`. No `eglDestroy*` (the shims do not export them). Every
EGL/GL/fb prototype is hand-written; no Khronos headers exist on the box.

Proven against the rig's bridge libs on a private ring (ringcat.py as the
host): attach, `TEXIMAGE 1360x768 RGBA/UNSIGNED_BYTE`, one `TEXSUBIMAGE` per
state change, 124 acked swaps at ~61 fps, teardown, exit 0. Not yet run on
Vivante hardware.

## The node bus (input_hw.c)

What the game does, from the godzilla_pro 1.15.0 ELF (read_nodebus.md A-F):

* open `O_RDWR|O_NOCTTY`; `TIOCGSERIAL`/`TIOCSSERIAL` with `ASYNC_LOW_LATENCY`;
  `cfmakeraw`; `CS8|CREAD|CLOCAL|CSTOPB`; `cfsetspeed(B460800)`; `~CRTSCTS`;
  `VMIN 0 VTIME 3`; `tcsetattr`; `tcflow(TCOON)`; `tcflush(TCIOFLUSH)`; RTS
  5 ms on / 5 ms off. Every failure is logged and tolerated (pty, /dev/null).
* exchange = `tcflush(TCIFLUSH)`, write the frame, read exactly `reply_len`
  bytes (poll-capped), check the checksum (bytes 0..ck sum to 0) and STATUS
  (`& 0x0c` = error).
* `--preamble min`: `0a 00` (2) . `07 01 01` . `80 02 f1 8d 00` . enumeration
  (`f0 22`, `f0 11`, `00` polls with `f0 10`/`f0 20` per named node, `f0 22`)
  . identity `fe` reads of nodes 8 and 1 (logged: fw, part, board, variant).
* `--preamble full` additionally replays the write-only frames captured
  byte-exactly before the game's first 0x11: node 8 `ff`, `14 40 00 27 00`,
  `14 60 00 40 00`, `46 ff 01`, `72 ff*12`, `48 00 00`; node 1 `ff`,
  `14 08 00 17 00`, `14 60 00 40 00`, `44 01`. The coil-config series
  (`46 <mask>` / `40 <i>` / `72` / `85` / `84`) was never captured verbatim
  and is NOT replayed.
* then `88 02 11 65 0c` (node 8) and `81 02 11 6c 0c` (node 1) every 25 ms:
  RIGHT = byte 3 bit 0, LEFT = byte 3 bit 1, START = byte 1 bit 3, released
  = 1 / pressed = 0. A silent node backs off 500 / 1000 / 2000 ms so the
  menu stays responsive when a board does not answer.
* SPI: `SPI_IOC_WR_MAX_SPEED_HZ 100000`, `SPI_IOC_WR_MODE 3`, an 8-byte
  `SPI_IOC_MESSAGE(1)` with tx zeros every 10 ms; rx[1] bits 0-3 = Service
  Select/Plus/Minus/Back, active low.

The first 40 exchanges are logged in hex (`nb <tag>: tx ... rx ...`), then
only changes and failures; the SPI logs its first 5 words and every change.

## Where things go on the card

```
/usr/local/codeselect/codeselect       the program (comm 'codeselect')
/usr/local/codeselect/select.sh        the hook
/usr/local/codeselect/images.conf      written by the card builder
/usr/local/codeselect/font.ttf         optional (DejaVu Sans Bold)
/etc/init.d/game                       stock + one guarded line after 'pkill boot_display ':
                                       [ -x /usr/local/codeselect/select.sh ] && /usr/local/codeselect/select.sh
```

`select.sh` (POSIX sh, busybox `awk sed head tr mount umount` + `pidof`):
waits up to 3 s for boot_display to be gone, runs `codeselect --conf
images.conf --out /var/volatile/codeselect.choice --log
/dump/log/codeselect.log`, reads the index, looks the device up, and when it
differs from what `/proc/mounts` shows at `/games`: `umount /games` then
`mount -t ext4 -o ro,relatime,exec <dev> /games`; if that fails or the new
`/games` has no `game`, the primary `/dev/mmcblk0p3` is remounted. Any other
failure (no binary, no conf, selector exit != 0, no choice, unknown index,
`umount` busy) boots the primary. It never touches `/mnt/boot`, and it never
writes the last-choice file (the selector does, on confirm). `select.sh
--lookup N [conf]` prints image N's device (used by the tests).

## In the emulator

`run_game.sh` runs, inside its namespace and before the pivot/chroot exec,
with no LD_PRELOAD:

```
chroot "$R" /usr/local/codeselect/codeselect --conf /dump/codeselect.conf \
    --out /dump/select.choice --input padsw --timeout "${PAD_SELECT_TIMEOUT:-30}" \
    --log /dump/codeselect.log
```

with `PAD_SW_SHM=/dump/padsw PAD_GAME=<primary title> PAD_GL_BRIDGE=/dump/padgl
PAD_GL_W=1360 PAD_GL_H=768` inherited from watch.sh. The keyboard flippers
(Left/Right arrows), `1` (START) and Enter/`=`/`-` (Service Select/Plus/Minus)
arrive through padsw; ids come from `/dump/tables/$PAD_GAME/switch_list.txt`,
or the platform ids (36/25/26/27/28) before a title has a table (then the
flippers are unknown - use `-`/`=`/`1`).

## Tests

`make check` (all under qemu-arm-static against the rootfs libs, no chroot,
no rig):

1. `test/check_elf.sh` - the readelf ceiling above.
2. `test/headless.sh` - six headless renders (2/3/4 images, `--default 1`,
   last-choice precedence, `--invert`), choice/last file contents, the PPM
   shape (`P6\n1360 768\n255\n` + 1360*768*3 bytes), the invert frame being
   the exact 180-degree rotation of the plain one, an empty conf refused
   with exit 2; PNGs in `$BUILD/t/codeselect_*.png` for eyes.
3. `test/padsw_test.py` - a padsw file, RIGHT (id 64 on turtles_pro) held
   100 ms then START (36): expects `key: right`, `key: start`, `chose 1`,
   choice file `1`, exit 0.
4. `bash -n select.sh` + `test/select_sh_test.sh` - the images.conf lookup
   with the host awk AND the card's busybox awk under qemu.

`make check-hw`: `test/fakebus_test.py` starts `fakebus.py` on a pty and runs
`--input hw --nodebus <pty> --spi none --default 1`; presses LEFT then START
via the control file; expects `chose 0`, the exact frames `88 02 11 65 0c`,
`81 02 11 6c 0c`, `88 02 fe 78 0d`, `81 02 fe 7f 0d`, the `0a 00 -> 03 00`
exchange, the enumeration frames, the pressed-LEFT reply
`00 ff 1f f9 40 00 00 00 00 00 a9 00`, and no `BAD CK`.

## What to look for on hardware

In `/dump/log/codeselect.log` (also the serial console):

```
nb: /dev/ttymxc1 open (460800 8N2, VMIN 0 VTIME 3)
nb 0a: tx 0a 00 rx 03 00                      the bridge answered at all
nb poll: tx 00 rx 08                          enumeration named node 8
nb fe: tx 88 02 fe 78 0d rx ...               node 8 identity (fw/part/board logged)
nb: node 8 switches 00 ff 1f fb 40 00 00 00   the first 0x11 answer (at rest)
spi: rx ff 0f 0f 00 00 00 00 00               the cabinet word at rest
egl: initialised 1.4 / egl: display 1360x768  Vivante came up
egl: up after N attempt(s)                    N > 1 = boot_display was still releasing the LCD
[select] key: left / [select] chose 1 TMNT 1987
select.sh: image 1: mounted /dev/mmcblk0p7 at /games
```

Failure signatures: `nb ...: short reply (timed out)` on every frame = the
bus is not answering (try `--preamble full`, then a hardware capture);
`egl: giving up after 6 attempts` = the display never came free (the hook
boots the primary); `select.sh: umount /games failed` = something held
`/games` (the primary boots, still mounted).
