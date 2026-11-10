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
0.5 GB (the seven Mesa `*_dri.so` are one 12 MB file). Across the six cards on
hand: see the table in the ticket's commit / `s3store.py status`.

## Stage 1 - the boot harness (done: the game runs)

`tools/spike3_emu/s3run.sh CARD [--slot N] [--secs S] [--strace] [--fresh]`
(root). Overlay per slot over the card's tree (lower = store, upper =
`/var/tmp/pad-s3/slot<N>`), so the store is never written and `--fresh` gives
the card's own first boot again; private mount + pid namespace; chroot; the
game exec'd through binfmt's qemu-aarch64 (flags `POF`, so nothing from the
host goes into the chroot).

First boot, pokemon_le 0.82.0, no shims at all: the 52 MB aarch64 `game`
loads every one of its 31 libraries, starts its threads, tries the node-bus
bridge, carries on without it, and then sits in `create_window RETRY n / 27`
(no display). Still running at the 40 s cap.

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
