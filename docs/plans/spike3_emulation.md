# Spike 3 emulation (PAD-1090)

Goal (David): run a Stern **Spike 3** raw SD card in the emulator at parity
with Spike 2, without spending a card's 62 GB of disk on it.

## What a Spike 3 card is

Raspberry Pi CM4 (BCM2711, **aarch64**), Buildroot Linux, busybox init. MBR:

| p | type | what | size | used (pokemon_le 0.82.0) |
|---|---|---|---|---|
| p1 | FAT32 `SPIKE3` | signed boot (kernel + initramfs) | 64 MB | - |
| p2 | LUKS2 / ext4 | rootfs | 0.58 GB | 0.27 GB |
| p3 | LUKS2 / ext4 | `/data` (settings) | 24 MB | empty |
| p5 | LUKS2 / ext4 | `/connectivity` (cache, dump, updates) | 25.8 GB | empty (journal only) |
| p6 | LUKS2 / ext4 | `/games` (title + assets) | 35.4 GB | 3.1 GB |

Every LUKS volume is `aes-xts-plain64`, 512-byte sectors, data at 16 MiB, and
opens with the board's customer-OTP keyfile through its keyslot (the same key
spike3_keys.py takes; never in the repo). **Stern writes every card from one
master image**: pokemon_le and fallout_le carry identical LUKS uuids and
partition tables.

`/games` looks like Spike 2's: `<title>/` plus `game`, `conagent`, `data`,
`spike3` symlinks, `spk/`. `/etc/init.d/S95game` -> `game_monitor` runs
`/games/game` in a restart loop and reads its exit code (0 restart, 1 reboot,
2 exit, 3 power loss, 4 fatal, 5 dispatch timeout, >=128 signal) - the same
contract as Spike 2.

## Stage 1 - the card store (done)

`tools/spike3_emu/s3store.py`. A copy of the card would be 62 GB of mostly
encrypted zeros that cannot be compressed or shared, so the store keeps only
the FILES, decrypted, each one once:

- the kernel opens each LUKS partition read-only straight off the original
  (`losetup -r`, `cryptsetup open --readonly`, key on stdin, `mount -o ro,noload`);
  WSL's kernel has dm-crypt and cryptsetup 2.7 - no Python AES in the hot path;
- every regular file goes into `objects/<sha256>-<mode>-<uid>-<gid>` (sparse
  aware), and the card's tree under `cards/<card-id>/<role>/` is hardlinks into
  it; dirs, symlinks and device nodes are recreated;
- the id is the file stem plus a fingerprint of the size, the LUKS uuids AND
  the first 64 KiB of each volume's ciphertext (the uuids alone collide across
  titles);
- it lives on the shared card-store disk (`/mnt/wsl/cards/spike3`, PAD-651)
  when that is mounted, else `~/cardcache/spike3`; builds queue on a lock.

Measured on pokemon_le 0.82.0: **61.9 GB image -> 2.89 GB of files -> 2.35 GB
on disk**, 151 s from the D: drive. Within the one card the dedup already saves
0.5 GB (the seven Mesa `*_dri.so` are one 12 MB file). All six cards on hand,
built in this order from D: (2026-11-09):

| card | files | added to the store | build |
|---|---|---|---|
| pokemon_le 0.82.0 | 2.89 GB | 2.34 GB | 151 s |
| fallout_le 0.81.0 | 10.99 GB | 10.00 GB | 631 s |
| star_wars_2025_le 0.96.0 | 12.34 GB | 10.94 GB | 888 s |
| star_wars_2025_pro 0.84.0 | 10.16 GB | **1.32 GB** | 611 s |
| star_wars_elg 1.10.0 | 4.09 GB | 3.17 GB | 212 s |
| walking_dead_remastered_le 0.92.0 | 2.97 GB | 2.05 GB | 147 s |
| **6 cards** | **43.4 GB** | **29.85 GB on disk** | |

against **371.5 GB of images**. Every card after the first shares ~0.9 GB of
rootfs; the Star Wars 2025 Pro added 1.3 GB on top of the LE's 12.3. A rebuild
of a card already in the store adds nothing (re-reads, links, done). The cost is
the read: ~15-20 MB/s off a Windows drive through 9p + dm-crypt, so a big title
takes 10-15 minutes once.

## Stage 1 - the boot harness (done: the game runs)

`tools/spike3_emu/s3run.sh CARD [--slot N] [--secs S] [--strace] [--fresh]`
(root). Overlay per slot over the card's tree (lower = store, upper =
`/var/tmp/pad-s3/slot<N>`), so the store is never written and `--fresh` gives
the card's own first boot again; private mount + pid namespace; chroot; the
game exec'd through binfmt's qemu-aarch64 (flags `POF`, so nothing from the
host goes into the chroot).

First boot, no shims at all, **all six cards the same way** (2026-11-09): the
aarch64 `game` loads every one of its 31 libraries, starts its threads, finds
no netbridge (`cpuspi: device open failed`, openocd cannot open its SWD
adapter, `failed to initialize bridge`), carries on, retries `create_window`
27 times at 300 ms, and then aborts on its own check:

    glWindow.cpp:1039: void glWindow::setGlContext():
        Assertion `eglGetError() == EGL_SUCCESS' failed.      (exit 134)

| card | window retries | aborts at |
|---|---|---|
| fallout_le 0.81.0 | 27 | 63 s, glWindow.cpp:1039 |
| pokemon_le 0.82.0 | 27 | 59 s, :1039 |
| star_wars_2025_le 0.96.0 | 0 | 51 s, :970 |
| star_wars_2025_pro 0.84.0 | 0 | 51 s, :963 |
| star_wars_elg 1.10.0 | 27 | 59 s, :1039 |
| walking_dead_remastered_le 0.92.0 | 27 | 59 s, :1039 |

The two Star Wars 2025 builds are an older engine with no retry loop. So the
display is the one wall between every card on hand and its first picture.

Two harness lessons: the game's stdout to a file is block-buffered and its
TERM handler exits without a flush, so s3run.sh runs it on a pty (`script`)
and a 30 s boot no longer leaves game.out empty; and `script` reads stdin,
which under `bash -s` is the harness itself, so it gets `/dev/null`.

## The hardware it reached for (strace, first boot)

| device | what | Spike 2 equivalent / plan |
|---|---|---|
| `/dev/dri/card1` | KMS display, GBM + EGL (Mesa v3d/vc4) | eglshim + GL bridge; Spike 3 needs GBM/DRM entry points too |
| `/dev/spidev4.0` | the **netbridge** link (RP2040 node-bus bridge) | `/dev/ttymxc1` + nodebus.py; a new bridge protocol |
| `/dev/ttyAMA5` | UART (bridge console or bus) | as above - which one carries the bus is open |
| openocd over `/dev/gpiomem` + `/dev/mem` | the game REFLASHES the RP2040 (`netbridge.elf`, SWD) when its CRC differs | stub: answer the CRC check so no flash is attempted |
| `/dev/i2c-10` | cabinet EEPROM (identity record) | hwshim's EEPROM block |
| ALSA | sound | alsastub |
| GStreamer + libav | video | gststub/gstvid |

Game log: `netbridge image CRC mismatch, write new image` / `failed to
verify/update bridge` / `failed to init bridge thread`, then the window.

## Stage 2 - the display (run 2, in progress)

**The game is Godot 4** (its GLES3 "compatibility" renderer: `MethodBind`,
`TextServer`, `res://scenes/...tscn`, `project.godot`) under a display server
of Stern's own (`glWindow.cpp`) that drives KMS directly. No X11/Wayland
display driver is compiled in, so the KMS side is faked.

Built (`s3build.sh` -> `~/.pad-s3/build`, `s3run.sh --bridge` runs it):

- `s3kms.c` (LD_PRELOAD): `/dev/dri/card0|1` is an eventfd; two connected
  HDMI-A outputs at 1920x1080@60 (the game takes connector INDEX
  `display_number` = 1, the second - glWindow at 0x926c9c checks index <
  count_connectors and `connection == 1`); GBM bos with memfd dma-buf fds;
  AddFB/SetCrtc/PageFlip present the bo, flip events through drmHandleEvent.
- `s3egl.c` (libEGL.so.1): GBM platform display, surfaceless contexts, TWO
  configs (XR24 and AR24 native visual ids - with only AR24 the game logged
  `failed to find egl config for gbm format` and retried create_window),
  dma-buf / GBM-pixmap EGL images resolved back to the bo, fences signalled.
- `s3gl.c` (libGLESv2.so.2, one unit with glbridge.c): the 55 missing GLES3
  entry points (buffer mapping as a guest shadow, renderbuffer/query names,
  the rest log their first call), the Pi 4 V3D's GLES 3.1 limits for
  glGetIntegerv, no program binaries, `glEGLImageTargetTexture2DOES`, and
  `pad_s3_present_bo` -> `PADGL_PRESENTTEX`.
- `padgl.h` v3: `PADGL_PRESENTTEX` appended (guest texture, w, h);
  `padglhost.c` blits it into the screen fbo (y-flipped, `PAD_S3_FLIPY=0`
  off) and then does what SWAP does. Spike 2 never sends it.

Measured on pokemon_le 0.82.0 (2026-11-09): the window now comes up -
`EGL version 1.5`, `egl resolution: 1920 x 1080`, nine 1920x1080 GBM bos,
three EGL images bound as textures, the bridge attached to padglhost (D3D12,
OpenGL ES 3.1 on the host), the first frame set with SetCrtc, the game
drawing into an FBO. Then, ~2 min in, it aborts:

    TAS57XX: amp initialization failed / TAS57XX thread exiting
    xifo.cpp:72: bool XIFO_PutData(XIFO*, int8_t*): Assertion `pXifo' failed.

The audio amplifier (TI TAS57xx) and the cabinet EEPROM both sit on
`/dev/i2c-10`, which does not exist in the chroot; the amp's thread exits on
the failed init and leaves its queue NULL. **Next: answer `/dev/i2c-10`** (an
I2C bus model in the s3hw preload: the EEPROM and the amp, transactions
logged) - not written in this run. Then the first dumped frame, and the
`[s3gl] first call` lines say which of the stubbed GLES3 calls Godot needs
for real.

## Stage 3 - the audio amp I2C bus (run 3: the crash is cleared)

The abort above is only the *open* of `/dev/i2c-10` failing: the amp thread
exits and leaves its XIFO queue NULL. So the bus has to exist. The clean,
hardware-generic way is Linux's own **i2c-stub** test module (a dummy I2C
adapter), not a hand-written bus model.

It will not side-load into the stock WSL kernel: that kernel is Microsoft's
exact GCC-11.2 / IBT / rethunk build, and its module loader rejects any module
built against a reconstructed tree (`Invalid relocation target, existing value
is nonzero for type 1`) - reproduced with both gcc-13 and gcc-11. So we build a
**self-contained WSL kernel from the matching 6.6.87.2 source**:

    ./scripts/config --set-str LOCALVERSION "-pad" -d LOCALVERSION_AUTO \
                     -e I2C_CHARDEV -m I2C_STUB      # i2c-stub is `depends on m`
    make -j olddefconfig && make -j bzImage          # -> arch/x86/boot/bzImage
    # module built against THIS tree's own vmlinux.symvers (its CRCs, not the
    # stock kernel's), with the SAME gcc as the bzImage, so it loads cleanly:
    make -j -C $K M=~/.pad-s3/i2cstub modules

Boot it via `.wslconfig` `kernel=C:\tmp\PAD-1090\bzImage-i2cstub`
(`wsl --shutdown`), then `insmod i2c-stub.ko chip_addr=0x48,0x4c,0x4d,0x4e,0x50,
0x51,0x52,0x53` -> `/dev/i2c-0` appears (i2c-dev built in). `s3run.sh`'s
`PAD_S3_I2C=<n>` hook surfaces that host adapter as `/dev/i2c-10` in the chroot
(mknod c 89 n).

Measured on pokemon_le 0.82.0 (2026-11-09), kernel 6.6.87.2-pad: `/dev/i2c-10`
now opens and **the game no longer aborts** - it runs the full cap instead of
core-dumping at `xifo.cpp:72`. The amp thread survives. But it still stalls at
the boot splash (uploads the UI atlases at frame 2, then no further presents),
because the amp's register *writes* fail:

    i2c: failed to write data: Inappropriate ioctl for device   (ENOTTY)
    TAS57XX: failed to write oscillator trim: Inappropriate ioctl for device

**Root cause was two-fold, both now fixed:**

1. **qemu-user (8.2.2) had no I2C ioctl translation.** The driver's `I2C_SLAVE`
   (and `I2C_RDWR`/`I2C_SMBUS`) ioctls are not in qemu-user's table, so it
   answered `-ENOTTY` for every one. Fixed by `qemu-i2c-ioctls.patch`
   (`linux-user/syscall.c` + `ioctls.h` + `syscall_defs.h`): `I2C_SLAVE` and the
   other by-value ioctls, `I2C_FUNCS`, and nested-pointer handlers for
   `I2C_RDWR`/`I2C_SMBUS` (guest aarch64 and host x86-64 share the LP64 LE
   layout, so the handlers only translate the embedded buffer pointers). Built
   static, staged at `~/.pad-s3/qemu-aarch64`; `s3run.sh` runs the game through
   it explicitly (PAD_S3_QEMU), leaving the shared binfmt interpreter stock for
   Spike 2.
2. **i2c-stub is SMBus-only**, so once the ioctls reached it, the amp's raw
   `I2C_RDWR` transfers returned `-EOPNOTSUPP`. Fixed by
   `i2c-stub-master-xfer.patch`: a generic register-store `master_xfer` that
   ACKs raw transfers (same `words[]` backing as the SMBus path).

With both in place the whole I2C layer works - the `ENOTTY` errors are gone and
the amp init runs through its I2C sequence (the crash moves from ~123 s to
~196 s in). It does **not** fully complete yet; the amp init now fails further
along, for reasons that are no longer I2C:

    failed to write BQ coefficients: No such file or directory   (ENOENT, a file)
    TAS57XX: oscillator trim failed to lock                      (status readback)

and the amp thread still exits on that failure -> `xifo.cpp:72`. Remaining amp
work: (a) find/provide the DSP biquad-coefficient source the `dsp.cpp`/
`dsp_pdi.cpp` path opens (ENOENT), and (b) have the stub report the TAS57xx
oscillator-lock status bit so the trim "locks". Separately, the **node bus**
(spidev4.0 / ttyAMA5 / netbridge, the constant `cpuspi` failures) is still
entirely absent and is the likely next gate on the render loop once the amp is
non-fatal. The game presents only a black clear-frame (frame 2 uploads the UI
atlases but never composites them) until it gets past init.

## Stage 4 - the node bus side of the CPU board (run 4: the game is on screen)

What the "node bus" devices turned out to be, read off the bridge board's own
firmware (`games/<title>/spike3/netbridge/netbridge.elf` is on the card,
unstripped, with debug info: `uart_host.c`, `uart_node.c`, `uart_powerdist.c`,
`ws2812.c`, `dmd.c`, `lcd.c`/`ch7038b.c`) and the game's own syscalls:

| device | what | stand-in |
|---|---|---|
| `/dev/ttyAMA5` | the RP2040 **netbridge's host UART** (`HOSTUART_*`); the board fans out to the node boards, WS2812 LEDs, DMD, LCD, power distribution | `s3bridge.py`: a pty, every burst logged (`bridge.log`) |
| `/dev/spidev4.0` | a **CPU-board SPI I/O chain**, not the bridge (the RP2040's only `spi_init` is in `DMD_Init1`): SPI mode 3, 100 kHz, 8 bytes out / 8 in, polled ~3000/s - the cabinet inputs and outputs. Its absence is the game's `FATAL error 226 (CPU SPI open failed)` | `s3spid` (CUSE): a real host char device, every transfer logged (`spi.log`), answers zeros |
| ALSA | the sound cards (the game imports 18 `snd_pcm_*` calls, no mixer) | `s3alsa.so` (LD_PRELOAD): paced to the wall clock, muted |

The SPI chain was THE gate. With only `spidev4.0` answering, the game stopped
waiting in hardware init and ran on to sound init in 5 s (previously: never in
120 s); the amp init that stage 3 left half-done now **completes** ("TAS57XX:
amp initialization complete" - its failures were collateral of the missing
SPI chain). With the sound cards answered too, Godot's main loop starts
(`Godot Engine v4.4.1`), shaders compile, HEVC video decodes, and frames
present continuously.

**First picture, pokemon_le 0.82.0 (2026-11-10):** the game's own red **Tech
Alerts** screen - "Check Node Board 4 : Invalid", "Check Node Board 0 : Not
Initialized", ... "Press 'Select' for Node Bus Test" - exactly what a machine
with no node boards answering shows, updating as the game retries them.

Pieces:

- `qemu-spi-ioctls.patch` (applied after `qemu-i2c-ioctls.patch`): the spidev
  setting ioctls and `SPI_IOC_MESSAGE(1..16)` with each transfer's guest
  tx/rx buffers mapped. Same staged `~/.pad-s3/qemu-aarch64`.
- `cuse.ko`, built from the same 6.6.87.2 tree as the kernel and loaded live
  (`make -C $K M=fs/fuse modules && insmod fs/fuse/cuse.ko`; the config already
  has `CONFIG_CUSE=m`) - no WSL restart.
- `s3run.sh --bus` starts `s3spid` (`/dev/pad-s3spi-slot<N>`) and
  `s3bridge.py` per slot and binds them over the chroot's `/dev/spidev4.0` and
  `/dev/ttyAMA5`; `s3alsa.so` is preloaded whenever it is built.

The bridge link's framing, from the game's first messages: `02 <cmd> <id>
[payload] <sum> 03` - STX, command, id, payload, a checksum that makes the
bytes from `cmd` to it sum to 0 (counted unescaped), ETX; a 0x02 or 0x03
inside the frame is sent as `1b 82` / `1b 83` (0x1b, then the byte | 0x80 -
e.g. `02 12 1b 82 ec 03` is cmd 0x12, payload 0x02, 0x12+0x02+0xec = 0x100).
First commands: `0x30` (the game logs
"netbridge image CRC mismatch" when it goes unanswered, then runs openocd to
reflash the RP2040 and fails), `0x20` (repeated every second), `0x27`, `0x41`
(node traffic: `41 <seq> <node> ...`, cycling node addresses), `0x25`,
`0x12`/`0x19`.

## Stage 4b - the bridge board answers, the node boards register (done)

`s3bridge.py` answers the host UART as `netbridge.elf`'s own `HOST_Update`
dispatch does (read off the unstripped firmware): `0x20` version
`[0, 98, 4, board rev]`; `0x30` the CRC32 (zlib's) of flash `0x10000100..
0x10012b40` computed from the card's ELF - the game logs "netbridge image
okay" and never runs openocd; `0x25` NODEBUS_Poll, the LOWEST node raising a
request (0 = none; answering the highest node made the game service node 14
for ever and skip the census); `0x27` LCD status; `0x41` the node relay,
`[node][n][n bytes][reply_len]` -> reply_len-1 node bytes + status (`0x00`
answered, `0x04` timeout with 0x55 fill). `0x10..0x1f` go to the power
distribution board and stay unanswered (the game falls back to "Spike 1/2
power distribution board").

The node protocol behind 0x41 is byte-for-byte Spike 2's (`81 02 fe 7f 0d` is
node 1's identity request on both). `s3nodes.py` reads the title's node
directory and board catalog out of the aarch64 game through its
R_AARCH64_RELATIVE relocations (the 64-bit `nbdir.py`; directory records are
0x20 bytes: handler, name cell, node<<16|code, flags; catalog rows 0x28 from
the part number; row = code - 2, checked by the CPU record landing on
"SPIKE3 CPU") and claims each identity by Spike 2's measured rules against the
`.hex` files the card ships. pokemon_le: nodes 1,2,4,7,8,9,10,12,13,14 all
register. `PAD_S3_NODES_ABSENT=<ids>` leaves boards off the chain.

**No network**: the game runs in its own network namespace (loopback only).
A 200 s strace boot: zero connect/sendto. conagent is never started.

## Stage 4c - cabinet inputs (done)

The SPI chain is the cabinet inputs, 8 bytes, ACTIVE LOW. At 0x00 every
button reads held and the game boots into its service path (Tech Alerts);
0xff (at rest) boots normally. `s3spid --input=$SD/spi.in` answers live from
that file; `s3press.py` presses bits. Measured in Guided Setup: byte 0 bit 0
SELECT, bit 1 NEXT, bit 2 PREVIOUS, bit 3 BACK (BACK jumps the highlight to
Save & Exit). The rest (start, coin, flippers, tilt) are NOT mapped yet: the
attract-mode scan's screen metric was noise (it cropped the Guided Setup rows,
not the CREDITS counter) - next run, score on the credits/start-prompt area.

The game shows Guided Setup at EVERY boot here (the slot's NVRAM persists, so
it is the game's choice - probably the "This machine has an invalid ..."
identity it reports). `s3run.sh --bus --bridge` runs `s3press.py autoguide`,
which spots it in the frame dumps and presses BACK + SELECT, and prunes old
dumps (`PAD_S3_AUTOGUIDE=0` turns it off).

## Stage 5 - video (done)

The game decodes its clips through libavcodec (FFmpeg 5.1.6-rpi) out of its
packed asset store (custom AVIO), expecting the Pi's V4L2 HEVC block and
`h264_v4l2m2m`, with DRM-PRIME frames wrapped as EGL images. `s3vid.so`
(guest, built against the FFmpeg 5.1.6 headers) takes HEVC/H.264 contexts
over at `avcodec_open2/send_packet/receive_frame/flush_buffers/free_context`;
packets go to `s3vidhost.py` (`s3vid.h` feed), one native ffmpeg per stream
(Annex B in, I420 out) writes the padvid ring (2048x1152 slots, 16 a stream -
`-DPADVID_MAX_W/H/SLOTS`); `s3egl`/`s3gl` turn the frame's fd into an image
and its bind into `PADGL_TEXDIRECT`. Traps found: length prefixes 256..511
look like start codes; `-fflags nobuffer` drops the IDR; the real
h264_v4l2m2m open fails (taken over anyway); 4 slots deadlocked; drain must
answer EOF promptly; pts may never be NOPTS.

The GL bridge needed the rest of GLES 3 for the video to SHOW (and for much
of Godot): MAXPROG 128 -> 1024 for Spike 3 (program 144's uniforms were never
set), and new ring ops after PADGL_PRESENTTEX - instancing, uniform blocks,
counted uniform arrays, colour/depth mask, pixel store, 3D textures, mipmaps.
GLES varying limits (0x9122/0x9125) answered; samplerExternalOES shaders get
the game's own `#define samplerExternalOES sampler2D`.

## Stage 6 - the node bus decoded, Start starts a game (2026-11-10)

**The frame mask.** A node address with bit 0x40 set (`c1`, `c8`...) carries
Spike 2's own frame - `cmd args... ck`, summing to zero with the address -
with each byte XORed by m = (node & 0x0f) << 4 | (n & 0x0f) (n = the byte
count) on even positions and ~m on odd ones (`s3bridge.unmask`, its own
inverse). Read off the bus, not out of any firmware (the pinnode .hex files on
the card are encrypted and were left alone): an all-zero LED frame showed the
alternating mask, and decoded this way every one of 110 frame kinds
checksums. What comes out is Spike 2's command set: `11 key ck` the switch
scan, `40 IDX power t...` coil fire/config, `41` coil rules, `4d` coil off,
`46/48/72/14/70` setup and status, `8x..bx` LEDs. The REPLY goes back plain;
the scan reply is keyed with the DECODED key (rol8 per byte, as Spike 2).
Keying it with the raw byte garbled every switch the game read.

**The cabinet.** Device tables (`s3nodes.devices`, 0x50-byte records found by
name): group g = the board of node-directory record g (1-based; record 5 is
the CPU, whose inputs are the SPI chain). pokemon_le: START BUTTON node 1 bit
11, COIN DOOR POWER INTERLOCK = SPI bit 15 (CPU index 23; service buttons
8..11 = bits 0..3), trough node 8 bits 37 (TROUGH 1) .. 32 (TROUGH 6),
SHOOTER LANE node 8 bit 28, coils TROUGH node 8 #1, AUTO PLUNGER #4. At rest
the SPI interlock bit reads OPEN (door open: service menu live, no coils);
`s3press.py hold SLOT 15` closes it.

**Raw optos rest CLOSED** (beam received): LEFT EJECT OPTO left open read as a
ball in the scoop - kicked at boot, "Left Scoop DEVICE MALFUNCTION". s3balls
rests every `... OPTO` switch closed (`PAD_S3_OPTO_REST=0` leaves them).

**The fault probe** `ff` carries 32 of the 64 input bits; it marked all 64 as
read, so a trough closed before boot (bits 32..37) never raised a request and
the game ran LOCATING PINBALLS for ever. Fixed: only the bits it carries.

**The ball model** `s3balls.py` (Spike 2's ballmodel/ballfeed rules, resolved
by name per title): trough full at boot, a TROUGH fire opens the highest made
position and closes SHOOTER LANE, an AUTO PLUNGER fire with a ball in the lane
opens it (in play), `s3press.py drain SLOT` brings one home. First 0x40 to a
coil = its configuration, later ones and the short `40 IDX ck` = fires.
`PAD_S3_NBTRACE=1` writes every changed decoded frame to DIR/nbtrace.log.

**Proven**: door closed, Start -> CHOOSE YOUR MODE OF PLAY / STANDARD NORMAL
PLAY (screenshot emulator_07). **Not yet**: the selected game never starts -
the countdown ends back in attract with no coil frame at all (no trough eject),
and the game logs nothing about why. With the trough full from boot, Start
instead runs a ball search (LOCATING PINBALLS, every 28 s: coils 8#2,3,6,7,8,
9#0,2,4..8) - the game counts a ball missing that nothing here holds.

## Where it stands (pokemon_le 0.82.0, 2026-11-10)

A fresh slot boots unattended through the SPIKE 3 logo, the version screen,
node location, Guided Setup (walked), and the whole attract cycle with its
video and how-to-play films; 6 minutes, no crash. Screenshots
emulator_01..07 in the ticket's artifacts. Start reaches the mode select.

## What is left for Spike 2 parity (next runs)

1. **Serve the first ball**: find what the game is missing between mode
   select and the trough eject. Leads: the ball count it expects (Audits /
   the Adjustments "balls installed"), other ball holders (RIGHT EJECT 9/1,
   RIGHT RAMP HOLD 9/15, CAPTIVE BALL, Meowth motor UP/DOWN 9/24-25 with the
   node-9 coil-7 rule `41 07 5a e8 03`), switches that read active at rest
   (TROUGH JAM closed made no difference), and Spike 2's motor models
   (hwshim steppers) for Meowth. Then flippers (node 8 bits 24/25) and a
   drain end a ball.
2. **The other five cards** on hand (fallout, star_wars x3, walking_dead):
   s3nodes.py derives each title's node set and devices; check each boots
   to attract and starts.
3. **Audio**: s3alsa drops the PCM (rig runs are muted); a host player like
   Spike 2's for the Emulate tab.
4. **Rig integration**: the Emulate tab refuses a Spike 3 card at pick; hand
   it to s3run.sh, a playfield window, rig slots/riglock.
5. Power distribution board (`0x10..0x1f`): unanswered, game falls back.
