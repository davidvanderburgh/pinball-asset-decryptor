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

## What is left for Spike 2 parity (next runs)

1. **Toolchain**: an aarch64 cross gcc for the shims (only `arm-linux-gnueabihf`
   is installed). Same private-prefix route the README uses for fuse2fs
   (`apt-get download` + `dpkg-deb -x`), no system package needed.
2. **Display**: aarch64 builds of `eglshim.c` + `glbridge.c` (check `padgl.h`
   for 32-bit pointer assumptions), plus `libgbm`/`libdrm` entry points the game
   uses to find `card1`, so `create_window` succeeds and frames reach
   `padglhost`. The game is stripped (dynsym only) and its window is classic
   KMS: it imports `drmModeGetResources/GetConnector/GetEncoder/GetCrtc`,
   `drmModeAddFB/RmFB/SetCrtc/PageFlip`, `drmHandleEvent`, `gbm_create_device`,
   `gbm_bo_create/map/get_handle/get_stride/get_fd/set_user_data...` and EGL
   (`eglGetProcAddress`, so the display is most likely
   `eglGetPlatformDisplayEXT(EGL_PLATFORM_GBM)`). The shim fakes one connected
   connector + CRTC at the panel's mode on a dummy `card1` fd, treats a GBM bo
   as a bridge surface and a page flip as a present (the flip event answered
   through `drmHandleEvent`). Strings name `card0` and `card1` - it probes both.
   **It imports neither `eglCreateWindowSurface` nor `eglSwapBuffers`**: it
   must render into GBM buffers exported as dma-bufs (`gbm_bo_get_fd`) and
   wrapped as EGL images (`eglCreateImageKHR` +
   `glEGLImageTargetRenderbufferStorageOES`/`Texture2DOES` through
   `eglGetProcAddress`), then scan them out itself with `drmModeAddFB` +
   `drmModePageFlip`. So in the shim an EGL image of a bo is a host FBO, and
   the page flip of that bo's fb is the frame's present. Confirm with a
   `--strace` run once the fake card1 answers.
   Extensions it asks `eglGetProcAddress` for (strings): `eglGetPlatformDisplayEXT`,
   `eglCreateImageKHR`/`eglDestroyImageKHR`, `glEGLImageTargetTexture2DOES`,
   `eglCreateSyncKHR`/`ClientWaitSyncKHR`/`WaitSyncKHR`/`DestroySyncKHR`,
   `glFramebufferTexture2DMultisampleEXT`, `glDebugMessageCallbackKHR`.
   **The bridge exports 75 of the 130 GL calls the game imports.** Missing - all
   GLES 3 the Spike 2 titles never used: glBeginTransformFeedback
   glBindBufferBase glBindBufferRange glBindRenderbuffer glBlendColor
   glBlitFramebuffer glClearBufferfv glClearDepthf glColorMask
   glCompressedTexImage3D glCompressedTexSubImage3D glCopyBufferSubData
   glCullFace glDeleteFramebuffers glDeleteQueries glDeleteRenderbuffers
   glDepthFunc glDepthMask glDrawArraysInstanced glDrawElementsInstanced
   glEndTransformFeedback glFinish glFlush glFramebufferRenderbuffer
   glFramebufferTextureLayer glFrontFace glGenQueries glGenRenderbuffers
   glGenerateMipmap glGetFloatv glGetInteger64v glGetProgramBinary glGetStringi
   glGetSynciv glGetUniformBlockIndex glMapBufferRange glPixelStorei
   glProgramBinary glReadBuffer glRenderbufferStorage glTexImage3D
   glTexParameterf glTexStorage2D glTexSubImage3D glTransformFeedbackVaryings
   glUniform1iv glUniform1ui glUniform1uiv glUniform2fv glUniform2iv
   glUniform3fv glUniformBlockBinding glUniformMatrix3fv glUnmapBuffer
   glVertexAttrib4f glVertexAttribDivisor glVertexAttribI4ui
   glVertexAttribIPointer. Most are one-way commands the ring carries as is;
   the round trips (`glGetUniformBlockIndex`, `glGetProgramBinary`,
   `glGetSynciv`, queries) need the bridge's reply path, `glMapBufferRange`
   a guest-side shadow flushed at unmap, and `glProgramBinary` can answer
   "no binary formats" so the engine falls back to source.
   Checked this run: `glbridge.c` and `eglshim.c` compile for aarch64 as they
   are (xgcc.sh, `-nostdlib` against the card's own libc) - the ring protocol
   is pointer-free fixed-width fields.
3. **Netbridge**: what the game expects over `spidev4.0`/`ttyAMA5` (find the
   framing in the game; the RP2040 firmware is on the card as
   `spike3/netbridge/netbridge.elf`), then a bridge emulator that speaks the
   existing nodebus.py node set behind it - switches, coils, LEDs.
4. **hwshim for aarch64**: EEPROM, clocks/pause/speed, the validation reporter;
   per-title addresses for aarch64 ELFs.
5. **Audio / video** stubs rebuilt for aarch64.
6. **Rig integration**: watch.sh / riglock slots / rig board, the Emulate tab
   (today it refuses a Spike 3 card at pick - lift that once stage 2 boots to
   attract), playfield window.
