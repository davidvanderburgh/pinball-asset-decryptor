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

**Two video paths, and the extension list (PAD-1182).** The game shows video
two ways. Stern's own SpiVideoPlayer (0x945040 in pokemon_le 0.82: the map
background) looks up glEGLImageTargetTexture2DOES and binds each frame's
image itself. Videos placed in Godot scenes go through an ExternalTexture
(0xd02420: the DISCOVER, capture, select and evolve backgrounds), and Godot
only attaches an image when its config found `GL_OES_EGL_image_external_essl3`
in the extension list. The bridge listed none (NUM_EXTENSIONS 0), so those
backgrounds stayed on Godot's black placeholder while s3vid decoded every
frame and the game made an image of each (6,800 images, 0 binds). s3gl.c now
lists exactly what it carries: GL_OES_EGL_image, GL_OES_EGL_image_external,
GL_OES_EGL_image_external_essl3. Tell-tale in padglhost.log: no `video upload`
line for a channel the host is decoding. (The 1940x1100 size of those clips is
not the cause: cropping them to 1920x1080 on the host changed nothing.)

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

**The fault probe** `ff` is a STATUS poll, not a switch read: word A = the
addressed frames the board took since the last probe (this one included,
Spike 2's PAD-249 rule - a mismatch made the game re-initialise node 8/9 for
ever), word B 0. Counting it as a read cleared raised requests with no scan.
Only the scan (`11`) clears a request, and every input state the bridge sees
is QUEUED for its own scan (a 150 ms coin pulse was otherwise lost).
`F0 10`/`F0 20` (enumeration) hold a node's request another 30 s.

**Polarity** - found with the game's own Ball Trough Test (service menu,
live): every node board but the cabinet one (START BUTTON's, node 1) reports
a CLOSED switch as wire bit 0. The game had always seen an empty trough: ball
searches, "Auto Plunger / Left Scoop DEVICE MALFUNCTION". `nodesw` stays
logical (1 = closed); the scan reply inverts active-low boards
(`set_polarity`; `PAD_S3_ACTIVE_LOW/_HIGH` override). Optos rest open.

**The ball model** `s3balls.py` (Spike 2's ballmodel/ballfeed rules, resolved
by name per title): trough full at boot, a TROUGH fire opens the highest made
position and closes SHOOTER LANE, an AUTO PLUNGER fire with a ball in the lane
opens it (in play), `s3press.py drain SLOT` brings one home. Coil frames ask
for no reply, so the model hears them on every addressed frame. First 0x40
to a coil = its configuration. `PAD_S3_NBTRACE=1` traces decoded frames.

**Press by name**: the bridge writes `DIR/switches.json`; `s3press.py sw SLOT
"START BUTTON"`, `coin SLOT N` (1 s apart).

**First presses after boot (PAD-1139).** The cabinet board has nothing
closed at boot, so it never raised a request and the game's FIRST scan of it
was the player's first coin, which the game took as the starting state: the
first two coins after a boot never credited (pokemon_le, 4 coins -> 1/2,
twice). A real board's power-up request does not exist here, so once a board
is past bring-up `attention()` queues its resting inputs for one scan
(`PAD_S3_BASELINE_SCANS`, default 1; 0 = the old behaviour). Proven on fresh
boots: 4 coins 3 s apart -> CREDITS 1 (twice), 8 coins 1 s apart -> 3
credits, then Start -> BALL 1. In a settled attract nothing was ever lost:
16 presses of 20..100 ms and 12 of 150..1000 ms all credited. Note the
pricing (1/$1.00, 3/$2.00) when counting: 8 quarters show CREDITS 3.

**Harness hygiene**: `s3run.sh` kills a killed run's helpers (an orphaned
padglhost wrote stale frames and slowed later boots to 3x), frame dumps sort
numerically, autoguide no longer mistakes service-menu pages for Guided Setup.

**The coin door starts shut** (PAD-1142). A headless run (no `--window`)
left the interlock (SPI bit 15, active low) at rest = OPEN: 48V DISABLED, and
on a slot with saved settings the game went straight to attract and asked for
no node board for ~56 s - first board at 68.7 s instead of ~10 (pokemon_le
and star_wars_2025_le, same saved state, door open vs shut: 68.7 / 10.1 s and
68.7 / 8.1 s). A fresh slot was not affected (Guided Setup starts the bus at
once), nor a window run: the window's keyboard closes the interlock as it
attaches. `s3bridge.py` now shuts it by name (COIN DOOR [POWER] INTERLOCK)
before the game starts; `PAD_S3_DOOR=open` keeps the old start.

**Proven** (pokemon_le 0.82.0, names only, emulator_08..11): coins ->
CREDITS, START BUTTON -> BALL 1 (the trough eject is answered, the ball
reaches the shooter lane), ACTION BUTTON -> the auto plunger fires, slings,
pops and orbits score (1,022,310 -> 1,073,640), a drain gives the end-of-ball
bonus and BALL 2; inside the ball save the game re-serves and auto-launches.

## Stage 7 - the other titles (2026-11-10)

Everything is derived per title, and five of the six cards on hand now start
a game and play a ball by switch NAMES only (the same script, `coin`,
`sw "START BUTTON"`, `sw "ACTION BUTTON"`/`"LOCKDOWN BUTTON"`, slings, drain):

| card | result | what it needed |
|---|---|---|
| pokemon_le 0.82.0 | plays, ball 2 | (stage 6) |
| walking_dead_remastered_le 0.92.0 | plays, scores | nothing new |
| star_wars_2025_le 0.96.0 | plays, scores | END-STOP motors (Death Star, Jump Ramp, AT-AT) |
| fallout_le 0.81.0 | character select, ball in play | STEPPER motors (Fat Man pan/tilt), ~110 s settle |
| star_wars_elg 1.10.0 | ball served, opening crawl | node directory flag byte; per-switch polarity; GAME SETUP screen eats the first Start |
| star_wars_2025_pro 0.84.0 | plays, scores 2,030 | legacy power board answered (0.5 -> 20 fps); autoguide on fresh frames |

**Polarity is per switch** (device record +0x28 = LOCATION): playfield
switches answer closed as wire 0, cabinet buttons stay high - the flipper
buttons on playfield node 8, and ELG's Start and tilt on node 8 too
(`s3nodes.active_low_masks`, keyed on the TROUGH switches' location).

**Board-run motors** (`s3motors.py`, Spike 2's PAD-393/656 and PAD-237/249/
955/971 models): steppers `32` configure (end inputs data[5]/[6]), `34`
home, `31` move, status `38+motor` -> pos, target, flags 0x02 moving 0x04
homed; end-stop motors `51` configure (stops data[2]/[3], encoder data[5]/
[6]), `53`/`54` to a stop, `55` to an input, status `52 <motor>` byte 2 =
0x01 moving, 0x20 arrived (55), 0x08 done. Zeros held fallout and star wars
LE in their boot for ever. End switches go into nodesw (logical).

**The netbridge build is per card**: 0.98.4 (most), 0.98.6 (fallout), 0.97.0
(star_wars_2025_pro). The bridge reports the card's `version.txt` and CRCs
from 0x10000100 to the end of the ELF's first flash segment; Pokemon's fixed
range made Pro reflash (openocd fails) and freeze on the logo.

**Star Wars 2025 Pro** (radium engine, not Godot) drew at 0.5 fps: it polls
the power distribution board (`0x12`, `0x19`) every loop and each poll
waited out its timeout. netbridge itself answers those when the power board
is a Spike 1/2 one (HOST_Update, read off the unstripped firmware: `0x10` 3
zeros, `0x12` line frequency u8, `0x15` 0xff, `0x19` line voltage u16; the
rest unanswered) - the bridge does the same now and Pro runs at 20 fps. Its
"second boot hangs" was autoguide judging a frame drawn BEFORE its press
(s3press.frame_after now waits for a newer one).

## Stage 8 - sound and the window (2026-11-10)

**Sound** (`PAD_S3_AUDIO=1`, off by default - rig runs are muted): s3alsa
writes the game's PCM non-blocking into `$SD/audio/audio.fifo` (bound at
/run/padaudio) and "rate channels" into audio.fmt; s3run starts Spike 2's
playaudio.sh outside the game's namespaces on port 46100+slot. SIGPIPE is
blocked around the write. Proven silently: 139 s from the fifo, 138 s
through the player's relay sink (emulator_18 is a 20 s WAV of it).

**The window** (`s3run.sh --window`): padglhost with a window; s3bridge
writes `tables/game/switch_list.txt` (Spike 2's shape) so the window binds
its keys by the title's names, and s3keys.py carries its padsw.h block onto
nodesw / the SPI chain, edges only. Proven on a private Xvfb with xdotool:
5 = coin, 1 = Start (BALL 1), Space = launch, the door/trough latch at open.

## Where it stands (2026-11-10)

All six Spike 3 cards on hand boot, start a game and play a ball, with
video, live sound on request, and a playable window.

## Stage 9 - the Emulate tab (2026-11-10)

Start on a Spike 3 card runs it where the PC has the Spike 3 rig:
`tools/spike3_emu/s3launch.sh` (as root, through `wsl -u root`) checks the
rig (`--check`: root, the build, the patched qemu, CUSE, the amp bus,
tools), puts the card in the store the first time (its padkeys.json beside
it), and runs `s3run.sh --window` on the claimed rig slot; Stop is
`s3launch.sh --stop SLOT`; sound follows the panel's Mute. Without the rig the
PAD-367 refusal stands, saying Spike 3 is not set up on this PC. s3run finds
the amp bus (i2c-stub) by name - unset, the game aborted at xifo.cpp:72.

## Stage 10 - Spike 3 for every user (2026-11-10)

David's decision: the OTP key is never committed, but a user may bring their
own, so the emulator works for everyone who does. What that took:

- **No custom kernel, no patched qemu.** s3dev.so (an LD_PRELOAD in the game)
  answers /dev/spidev4.0 and /dev/i2c-10 inside the game - the SPI chain from
  spi.in, the amp bus as the same generic register store i2c-stub is - and
  the game runs under the distro's own qemu-aarch64-static (binfmt, F flag).
  The `kernel=` line in .wslconfig is no longer needed.
- **No dm-crypt.** s3store.py decrypts in user space with the app's own
  LUKS/ext4 reader (spike3.py, luks_otp.py, `cryptography`) when the kernel
  has no dm-crypt: bit-identical rootfs, pokemon_le in 278 s.
- **The user's own key.** The Extract tab's Spike 3 unlock saves padkeys.json;
  the Emulate tab finds it (spike3_keyfile) and hands its PATH to
  s3launch.sh --keyfile. Used once per card, to build the store. No key: the
  run says to unlock the card in the Extract tab.
- **One door.** s3launch.sh --check / --setup (apt packages, binfmt), then the
  store, then a one-time rig build (s3build.sh: downloads the cross compiler
  and FFmpeg headers into /var/lib/pad-s3), then the run. The installers ship
  tools/spike3_emu and luks_otp.py.
- Proven from nothing: an empty rig home, no custom modules, the system qemu -
  the launcher built the rig, Pokemon booted, Guided Setup was walked and a
  ball was served and plunged.

## Stage 11 - the virtual playfield (2026-11-10)

Spike 2's playfield window, on a Spike 3 run, from the card's own data:

- The device records carry their place exactly as the test menu draws them:
  picture name at +0x18, x/y at +0x2c/+0x2e, w/h at +0x30 (s3nodes.records).
  Every card ships the pictures: pokemon_playfield_le/pro, buck_le/pro_playfield
  (Star Wars 2025), picnic_pf (Walking Dead), the ELG diagnostic drawing.
  Fallout 0.81 places no playfield devices (its window shows the cabinet).
- s3pf.py writes the window's tables at run start; the group map is exact
  (group_node_exact.txt: a group is the board's place in the node directory).
- s3leds.py fills padled.h's block from the node bus in s3bridge: lamp levels
  through leddecode's swelf-generation grammar (Spike 3 speaks it: 3742 frames,
  0 refused), coil fires from `40 IDX power`.
- Proven on pokemon_le: 60 switches, 17 coils, 174 inserts on its drawing,
  lit live by the attract show; a held SHOOTER LANE on the picture closed and
  opened the game's switch.

## Guided Setup at every boot: the factory config (2026-11-11)

The game reopens Guided Setup at every boot with "This machine has an
invalid Factory Config. Contact your distributor." Its settings DO persist
(data.up/nv). The factory config is the 256-byte EEPROM the game reads at
I2C 0x57 at boot (s3dev logs each address's first read; it never writes
0x50-0x53 or 0x57). Spike 2 sidesteps the same screen by seeding a
checksummed identity record (hwshim.c nv_ident_seed); Spike 3's factory
config is not checksummed but protected with a PER-MACHINE factory key
(AES-192-OFB + SHA-1/HMAC, /media/spi_factory_key-1_0_0.key - David's own
research notes), so a valid one cannot be made without a machine's key.
Window runs therefore ask the user for Save & Exit (watchguide); a
"bring your own factory config" (a user's own 0x57 dump, never committed)
is a follow-up ticket, untestable until someone has a real dump.

## The boards fire the flippers: coil rules (PAD-1134, 2026-11-11)

The flipper buttons reached the game (every tap scanned) and no flipper ever
fired: on the machine the game hands each node board a coil's RULE at ball
start (cmd 41, Spike 2's frame, masked like every other) and the board fires
the coil from its own switch; the game sends nothing per flip. `s3rules.py`
plays that board side. The 49-byte frame, read off the wire (the pinnode
.hex firmware is encrypted) and every field named from pokemon_le's device
table:

    [1] coil  [2] pulse power  [3..4] pulse ticks (100/s)  [5] hold power
    [6..7] hold ticks  [24] 0x40|input that fires it  [27] 0x40|second
    input (both flippers: their EOS)  [28] 0x40|input that stops a motor run

pokemon_le arms RIGHT/LEFT FLIPPER (n8 #0/#5, f5 for 40 ms then hold 1e,
inputs 24/25, EOS 31/16), the slingshots (n8 #2/#3, cc 30 ms, inputs 29/30)
and the pop bumpers (n9 #2/#4, 20 ms, inputs 28/30). A closing edge fires
the pulse, a hold follows while the switch is held, opening drops it; the
flipper's EOS input closes while the bat is up. A fire bumps padled's coil
counter (s3leds.fire), so the playfield window flashes the coil, and is
logged `[rule]` in bridge.log. Only a frame whose checksum holds arms a rule.

The same frame with only [28] is a cam motor (MEOWTH BALLOON MOTOR, stop
MEOWTH UP / DOWN, 1000 ticks = its 10 s limit), run by the short `40 coil
ck`: it now reaches its stop switch after PAD_MOTOR_MS (600, Spike 2's).
Unanswered, the game re-tried it every 10 s for ever. PAD_S3_RULES=0 turns
the board model off.

## A launched ball is kept alive (PAD-1137, 2026-11-11)

There is no playfield, so a launched ball moved no switch at all. Measured on
pokemon_le 0.82.0 (main's code, hands off after the ACTION BUTTON launch):
the game re-arms its sling and pop rules every ~27 s (its ball search
rounds) and at **130 s / 137 s** (two runs) gives the ball up and serves the
next one from the trough; ball after ball the game ends. Not a crash and not
NVRAM.

Two ways out were on the table: real ball physics (large, and nothing else on
the rig needs it) or a keep-alive. `s3balls.py` now does the keep-alive:
while a ball is in play and no PLAYFIELD switch has moved for `ALIVE_S`
(6 s, `PAD_S3_ALIVE_MS`, 0 = off), it taps a slingshot for 80 ms, the two in
turn - the switch an unattended real ball hits most. The PAD-1134 rules then
fire the sling coil, so the playfield window flashes it. Fallbacks by name for
other titles: return lanes / inlanes, then pop bumpers; never an outlane.

- "In play" is DERIVED from the switches (balls the trough and shooter lane
  do not hold, against the most ever seen there), not from launches, so a
  ball drained by clicking a trough dot in the playfield window stops the
  taps with no call into the model.
- "Playfield switch" = any node-board switch except buttons, coin, service,
  tilt, trough, shooter, EOS, QR, jumper, headphone, volume, ticket, door and
  motor end stops (`QUIET_EXCLUDE`). A click or key on one restarts the wait,
  so somebody playing is never tapped over; flipper buttons do not count.
- Nothing is tapped with every ball home or a ball waiting in the lane.
- bridge.log: `[ball] keep-alive: ...` at start, then `keep-alive tap N`
  (the first three, then every 25th).

Proven on pokemon_le (hands off after the launch, 420 s): main's code gave
the ball up at 137 s (BALL 2 on screen at 180 s, ball search re-arms every
~27 s); with the keep-alive the game was still on BALL 1 at 420 s, with no
second trough eject and no ball search round at all, ~70 taps of 82-92 ms
and 74 sling coil fires by rule. The taps score like a real ball's sling hits.

Spike 2's rig is left as it is: its ballfeed never leaves a ball sitting
untouched in play - a ball nobody plays drains home after PAD_BALL_HOME_MS,
one somebody played a minute after their last input (PAD-134/186) - so the
game never reaches its lost-ball wait there.

## Save states (PAD-1147, 2026-11-11)

Spike 2's save states, on Spike 3: the playfield window's Save state / Load
state, the tab's slot list, Launch from a slot.

- **A checkpointable run.** criu refuses a chroot'd task, one that is not its
  pid namespace's init, and one whose session leader is outside it - all
  three were the Stage 1 harness (`script` -> `timeout` -> `chroot`). A
  window run (and `PAD_S3_PIVOT=1`) now does Spike 2's PAD_PIVOT: the
  namespace's bash setsid's, pivots into the slot's root, drops the host tree
  with a static busybox and execs a static qemu-aarch64 copied in as
  `/.padqemu/game`, stdio on `/connectivity/dump/pad_game.*`. The cap is
  s3run's own; stdout is block-buffered there (no pty), as on the machine.
- **Save** (`s3save.sh`, via `s3state.sh save`, via Spike 2's savegame.sh
  when the rig slot runs Spike 3): criu dump from INSIDE the game's network
  namespace (`nsenter --net`), so the loopback-only namespace is criu's own
  and needs no iptables lock or dump; externals named from s3run's known
  layout (the overlays, /dev binds, the node-bus pty by device number, the
  /run slot files); the four overlay uppers copied while frozen; the
  renderer's GL journal (padglhost glstate.req in the slot dir). ~0.6-1.3 s
  frozen; 1.2-1.4 GB raw, 83-88 MB packed (zstd), in Spike 2's slot shape at
  /var/lib/pad-s3/saves/<title>/<slot>, so slots.sh lists/renames/deletes it.
- **Load** (`s3restore.sh`): the uppers back, the GL journal replayed into the
  run's renderer, the overlays mounted in a private namespace, criu restore
  in a fresh `unshare -n` NOT detached: the game arms PDEATHSIG (SIGKILL), so
  a detached restore's game died the instant criu exited. A cold load is
  `s3run --restore DIR` (s3launch `--restore game/slot`); a load into a run is
  `$SD/load.req`, served by s3run's wait loop, which ends the game and
  restores into the same renderer, bridge and video host.
- **Video after a load**: s3vid's stream table is in the restored memory but
  the feed/ring are the run's; handed vs a zero write_idx read as frames
  always waiting (5 million a minute). The feed carries a per-run `session`
  (s3vid.h, the old pad word); a stream opened on another session is
  re-opened (from its next key frame), releases of older frames ignored.
  An in-run load gets a new session and every channel closed
  (`s3vidhost.py --new-session`).
- **Proven** on pokemon_le: saved at BALL 1 / 1,560; drained to BALL 2;
  Load state brought back BALL 1 / 1,560 and the slingshots scored on
  (1,950); a save of a loaded game and its load; a cold Launch from a slot
  straight into BALL 1 / 1,560; a default window boot is checkpointable.
- **Not carried**: the node-board model (s3bridge) keeps the run's state
  through an in-run load and starts fresh on a cold one; the game re-arms
  coil rules at its next ball start. No clock credit for the freeze (Spike 3
  showed no watchdog at 1.3 s).

## What is left for Spike 2 parity

1. (PAD-1139, fixed) Coins: the first two after boot were lost.
2. The window's default key bindings fire one QR-scanner switch for a moment
   before the title's switch list loads (harmless, settles).
3. (Done, PAD-1152: every title's lamps watched - see below.)
4. (Answered, PAD-1152: the inserts are one channel each - single-colour
   inserts, drawn in their lens colour as on Spike 2 (PAD-668); Star Wars
   2025 Pro's RGB inserts are named -R/-G/-B and group as RGB.)

## Every title's lamps, watched (PAD-1152, 2026-11-11)

Each card booted headless and muted to its attract show with the padled
block published, polled every 0.5 s for every channel's peak level, and
judged against the card's own device table (the placed inserts on the
layout picture, by group -> node):

| card | inserts lit / placed | addressed | notes |
|---|---|---|---|
| pokemon_le 0.82.0 | 29 / 30 | 30 | universal topper (node 14): 64 channels past 96 lit |
| walking_dead_remastered_le 0.92.0 | 144 / 145 | 145 | topper (node 12): 26 past 96 lit |
| star_wars_2025_le 0.96.0 | 130 / 131 | 131 | SHOOT AGAIN dark in attract |
| star_wars_2025_pro 0.84.0 | 87 / 129 | 129 | the dark ones are R/G halves of RGB inserts the attract shows in one colour |
| star_wars_elg 1.10.0 | 63 / 63 | 63 | after one Start clears the first-boot GAME SETUP (before it: 19) |
| fallout_le 0.81.0 | no layout | - | insert boards 8/9/12 lit 85/89, 91/92, 63/73 |

0 refused lamp frames on any title. **What it found:** a board's channels
past its first 96 (bank form) were dropped by s3leds - the toppers, the
speaker panel and the cabinet strips (node 2: 288/432 channels). s3leds now
fills padled v6's `hi` plane as Spike 2's shim does (led_hi: levels only,
`seen`/`decoded` untouched) and stamps the block version 6; the window lights
them (before/after: Walking Dead's topper bottom row). The strips (node 2)
and speaker panel (node 7) get no lamp frames in attract on any title - only
the `72` 96-bit mask and `f2` reads - so they stay dark there by the game's
choice. A slot whose saved state has the coin door open (48V disabled) sends
no lamp frames at all: judge lamps on a slot in a known state.
