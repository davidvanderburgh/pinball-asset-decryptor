# Stern Spike 1 — PC emulation

> Status: **the real Spike 1 firmware BOOTS, RUNS, and DRIVES ITS DMD** under
> the rig — the 128×32 dot-matrix display renders the game's real attract
> sequence, legibly: *GAME OF THRONES LE — V1.37.0*, the *SYS. 2.31.0 / HDW.*
> version banner, *SERVICE MENU — USE -/+ TO VIEW TECH. ALERTS*, *GAME OVER*,
> *CREDITS 0*, *REPLAY AT 300,000,000*. (Rig = patched qemu-user + a CUSE device
> model + a seeded EEPROM; needs root, via WSL's `wsl -u root`.)
>
> **Four unlocks got here, in order:**
> 1. **Persistent-storage region seed** — a valid `{value, ~value}` region
>    header at EEPROM 0x5ff8 / 0x7ff8 (`make_seed.py`), plus a *persistent* i2c
>    EEPROM address pointer in the qemu model (the game does address-write and
>    data-read as separate `I2C_RDWR` calls). Clears `sys_persistent_storage_init`.
> 2. **`/proc/cpuinfo` passthrough** (`patch_qemu.py`, patch 2) — qemu-user fakes
>    `/proc/cpuinfo` and, for its default ARMv8 CPU, emits **no `Hardware:` line**
>    (only `arch < 8` does). The game's platform probe is
>    `cat /proc/cpuinfo | grep Hardware` matched against "Freescale i.MX6"; with
>    no match it fell through to the **wrong (AT91) hardware path** and the node
>    bus never came up. The patch stops qemu intercepting `/proc/cpuinfo` so the
>    bind-mounted fake (real i.MX6 `Hardware:` line) is served → `getPlatform()`
>    returns 2 → correct i.MX6 path.
> 3. **SIGFPE drop** (`patch_qemu.py`, patch 3, env `S1_DROP_SIGFPE=1`) — on the
>    i.MX6 path the game sends `SIGFPE` (via `tgkill`) to a worker thread as an
>    abort path it never installs a handler for, so under emulation it just kills
>    the process. Dropping guest SIGFPE sends (safe — a delivered SIGFPE could
>    only ever crash this game) lets it run past the abort, reach the node-bus
>    thread, and render the DMD.
> 4. **DMD frame format decoded** (`s1dmd.py`) — the 2048-byte `/dev/spi0` frames
>    are **4 bit-planes** of 512 bytes each (128×32, 4bpp, MSB-first). Decoded
>    that way they're legible (see above). Tested: `tests/test_spike1_dmd.py`.
>
> **Node-bus responder — nodes now REGISTER.** The wire format was cracked from
> a live `/dev/ttyS4` capture and the game ELF (not invented):
> `[addr, len, cmd, data…, checksum, resp_len]` — `addr` bit7 set = addressed
> node; `checksum` makes `sum(addr..checksum) ≡ 0 (mod 256)`; `resp_len` =
> expected reply length (0 = none). The game **broadcasts** lamp/coil to node 0
> (`cmd 0xf0`, no reply) and **polls** nodes 1, 8, 9, 10, 11, 12 with the
> `NODEBUS_GetVersion` presence poll (`cmd 0xfe`, resp 12).
>
> `nodebus.py` (`build_response`) answers those polls with the reply the game's
> `NODEBUS_TransferMessage` (@0xbfc28) requires: **`[payload][checksum][status]`**
> — checksum is the SECOND-TO-LAST byte (`sum(payload+checksum) ≡ 0`), the LAST
> byte is a STATUS byte that must have bits `0x04`/`0x08` clear (the trap that
> broke the Spike 2 shim: the last byte is NOT the checksum). No part-id match is
> needed — any well-formed, **deterministic** reply registers the node (the game
> re-polls and `memcmp`s up to 5×). CONFIRMED LIVE: the "short response (got 0,
> expected 12)" errors stop, and the game escalates to **runtime polls (`cmd
> 0xf9`, resp 18)** — a command it only issues to a *registered* node. Reply
> framing pinned by `tests/test_spike1_nodebus.py`.
>
> **Switch path — responder built, one gate remaining.** The switch read is a
> two-step handshake (RE'd from the game ELF): (1) `NODEBUS_Poll` — the game
> broadcasts a bare `0x00` and reads **1 byte** = the id of a node with pending
> switch data (`0` = none); (2) for that node it issues **cmd 0x11**
> (`NODEBUS_GetInputState`), whose reply carries **8 switch bytes, ACTIVE-LOW**
> (idle 0xff; node-local position P → byte `P>>3` bit `P&7`, bit 0 = closed —
> from `sys_node_board_device_switch_update_inputs` @0x62c2c + the matrix
> orr/bic @0x72478). `nodebus.py` implements both: it answers the poll token and
> fills cmd 0x11 from the viewer's `SwitchInput` block (env `S1_SW_INPUT`), all
> unit-tested. (The `cmd 0xf9` runtime poll turned out to be `GetFullBoardID`,
> board-ID pages — NOT switches.)
>
> **The one gate left:** the game only issues cmd 0x11 for a node whose **board
> TYPE** marks it a switch node — a type it derives from the part number in the
> `cmd 0xf9` `GetFullBoardID` reply (`sys_node_board_type_get_from_part_number`).
> The responder currently returns a zero board-ID, so the game treats every
> registered node as a lamp/coil node (it streams `cmd 0xf0` lamp/coil broadcasts
> to them) and never reads their switches. Next RE: the board-type →
> switch-capability mapping + the per-title node topology (which node ids are
> switch boards and their part numbers), then return those in the 0xf9 reply so
> the game latches the switch nodes. Then the node-0 `cmd 0xf0` broadcasts also
> decode into the LED/coil view. (The DMD renders regardless of all of this.)
>
> **WSL rig gremlins (cost real time — see the memory note):** the `/mnt/c` 9p
> mount serves STALE cached file content after a Windows-side edit (`grep`/`md5`
> see the new file, `cp` writes the old bytes) — force `sync; echo 3 >
> /proc/sys/vm/drop_caches` then `cat src > dst` before trusting a synced file.
> And a high-traffic run (the buggy poll loop streamed ~875 KB) can leave the rig
> unable to relaunch until processes are reaped.

This documents emulating the 2015-2016 **Spike 1** DMD generation (WrestleMania,
KISS, Whoa Nellie, Game of Thrones, Spider-Man VE, Ghostbusters) on a PC —
the analog of the Spike 2 rig in [`tools/spike2_emu/`](../../tools/spike2_emu).
Extraction/write for these titles is separate and shipped
([stern.md](stern.md) → Scope; `plugins/stern/spike1.py`).

## Why Spike 1 is a different problem from Spike 2

The Spike 2 emulator hangs everything on **`LD_PRELOAD`**: the Spike 2 game is a
*dynamically linked* armhf ELF, so `hwshim.so` interposes libc
`open`/`read`/`write`/`ioctl` and fakes every peripheral (see
`tools/spike2_emu/hwshim.c:1-10`).

The **Spike 1 game is a fully *static* armel ELF** (no `PT_INTERP`, no dynamic
section; Sourcery CodeBench 2014 glibc, soft-float). `LD_PRELOAD` is ignored
for a static binary, so the entire device-virtualization layer has to move one
level down — to the syscall boundary — where a **device model** answers the
game's `open`/`ioctl`/`read`/`write` directly.

What *does* carry over (verified): same **i.MX6** SoC (same qemu-user ARM
target), and the same **node-bus family** (identical `coil4node` / `pinnode` /
`lcdnode` / `netbridge` / `ws2812node` MCUs on both cards' `.hex`), so the node
protocol knowledge transfers. And because the game is static, **there is no
guest rootfs of libraries to build** — a real simplification over Spike 2.

## The rig (`tools/spike1_emu/`)

Root-free, reproducible from a card alone:

1. **`build_rootfs.py <card> <rootfs> <gamedir>`** — extracts, via the plugin's
   pure-Python ext4 reader + the Spike 1 partition walk (`formats.parse_all_
   partitions`, EBR chain included), the card's **OS rootfs** (the partition
   with `bin/busybox` — needed for the game's `/bin/sh` shell-outs) and the
   **game dir** (`<TITLE>/image.bin` + `game` + node `.hex`). Runs in
   WSL/Linux python3 so symlinks survive.
2. **`launch.sh`** — re-execs itself under `unshare -r -m -p -f` (user + mount +
   pid namespaces, no root), then assembles a chroot: the OS rootfs as the
   base, a writable `/data` + `/dump`, the game dir bound at `/games/<TITLE>`,
   a fake i.MX6 `/proc/cpuinfo` (`cpuinfo`), real `/dev/null,zero,urandom,...`
   bound in, and `/dev/null` stand-ins for the Stern peripherals. Then
   `chroot` + `exec ./game`, which runs under qemu-user via the kernel's
   `binfmt_misc` (registered with the **F** flag, so ARM `execve` works inside
   the chroot). `S1_STRACE=1` traces guest syscalls with `qemu -strace`.
3. **`run.sh [seconds]`** — bounded run; kills the whole namespace **process
   group** after the limit (the `timeout` tool leaks qemu children — the Spike 2
   rig hit this too).

## Boot trace — how far it gets, and the wall

With `/dev/null` stand-ins, the real GOT LE 1.37 firmware runs this far (from a
`-strace` capture):

| Stage | What happens |
|---|---|
| SoC detect | Shells out `cat /proc/cpuinfo \| grep Hardware`; the fake cpuinfo answers `Freescale i.MX6…`. |
| Assets | `open("image.bin")` OK; worker threads spawn. |
| Display probe | `readlink /usr/local/spike/display.hex` (dotmatrix vs rgbdotmatrix), `open("/dev/dmd")`, `ioctl(fd, 0x3d00 /*display reset*/)` → ENOTTY on the stand-in — **non-fatal**, logs "display reset: …" and continues. |
| NVRAM | Creates the full tree under `/data/nv/GOT_LE/` — `SYS_NVRAM`, `PIN_NVRAM`, `NOV_NVRAM`, `FRRAM`, `LKRAM`, `NVRAM`, `PTRAM`. |
| **Board EEPROM** | `open("/dev/i2c-0")`, `ioctl(fd, 0x703 /*I2C_SLAVE*/, 0x50)` — reads the **board-identity EEPROM at address 0x50**. Fails on the stand-in, retries 6×, then **`exit_group(1)`**. |

So the first **must-respond** device is the **i2c board EEPROM at 0x50**. (Also
seen: `sched_setscheduler(SCHED_RR)` → EPERM under the namespace — the Spike 2
shim strips SCHED_RR; a static binary can't, so the device model or a qemu
option must absorb it.)

### Device inventory (from the ELF + traces)

Character devices the game opens: `/dev/dmd` (DMD), `/dev/i2s` + `/dev/amp`
(audio DAC + amplifier), `/dev/ttyS4` (node bus), `/dev/ttyS3`, `/dev/i2c-0`
(board EEPROM), `/dev/gpio`, `/dev/adc` (with DMA), `/dev/spi0`, `/dev/rtc`.
No `/dev/mem`, no framebuffer, no mmap'd MMIO — a clean file-descriptor
surface. Node bus is a serial port (termios + read/write), so it can be a
**pty** (as the Spike 2 rig already does for its node bus, independent of
LD_PRELOAD).

## The device model (implemented)

Stock qemu-user returns `ENOTTY` for any ioctl not in its translation table
**without touching the host fd**, so a CUSE device never sees the game's device
ioctls. Two pieces solve this (both need root — via `wsl -u root`, which is
passwordless because Windows already authenticated the user):

1. **Patched qemu-user** (`patch_qemu.py` + `build_qemu.sh`). One change to
   `do_ioctl`: the unknown-ioctl fallback now does a **generic passthrough** —
   scalar/legacy ioctls pass the arg straight to the host fd, `_IOC`-sized ones
   bounce their buffer. So `I2C_SLAVE` (and the custom device ioctls) reach the
   host device. Verified: `I2C_SLAVE` + read of the CUSE EEPROM works under the
   patched qemu, fails under stock.
2. **`s1hwshim`** — a CUSE daemon (`s1hwshim.c`) that creates the Stern char
   devices: an **i2c** model (the board EEPROM at 0x50; `I2C_SLAVE` + read/write)
   and a **passive** model (accept every ioctl, discard writes, read zeros) for
   the stream devices (`dmd`, `i2s`, `amp`, `adc`, `gpio`, `spi*`).

`emu_root.sh` orchestrates it: register the patched qemu in `binfmt_misc`
(F-flag, so ARM `execve` works in the chroot; the stock qemu-arm is restored on
exit so the Spike 2 rig is unaffected), start the CUSE daemons, bind them onto
the real device paths in a mount+pid namespace, and run the game as root (which
also makes `sched_setscheduler(SCHED_RR)` succeed instead of EPERM). `run_root.sh`
bounds it and restores binfmt.

## What the i2c model does (built)

`I2C_RDWR` (0x0707) is a combined transaction carrying a nested
`struct i2c_rdwr_ioctl_data`. CUSE's unrestricted-ioctl protocol only moves a
single flat buffer, so it **cannot** service a nested-pointer ioctl — the i2c
model therefore lives **in qemu** (`patch_qemu.py`), where the guest pointers
are addressable. It translates the `msgs` array and models a **64 KB board
EEPROM at slave 0x50**: a write msg's first two bytes set a 16-bit big-endian
address, the rest are stored; a read msg returns from the current address. The
EEPROM is **persisted** to a file (env `S1_EE_FILE`) so it survives the
firmware's init-then-exit, and `emu_root.sh` relaunches the game in a
`game_monitor`-style restart loop (`S1_RUNS`). Set `S1_I2C_LOG=1` to trace every
transaction.

## The EEPROM NVRG format (decoded)

The game (which is **not stripped**) let the i2c NVRAM format be read straight
out of `nv_section_eeprom_read` / `nv_block_eeprom_read` / `CRC32`:

```
0x2000  section header:  'NVRG' (u32) + active_block (u32, 0 or 1)
0x2008  block 0 header:  'NVBL' (u32) + len (u32) + crc32 (u32)   data @ 0x2014
0x3004  block 1 header:  'NVBL' (u32) + len (u32) + crc32 (u32)   data @ 0x3010
```

A double-buffered (ping-pong) section: the active block's data is CRC32-checked
(standard init-`~0`/reflected/final-xor = `zlib.crc32`); `len ≤ 4080`.
[`make_seed.py`](../../tools/spike1_emu/make_seed.py) writes a valid image, and
seeding it into the persistent EEPROM (`S1_EE_FILE`) is **confirmed to satisfy
the read** — after a run, `0x2000` still holds `NVRG…NVBL` instead of being
re-formatted to `0xff`.

## The exit cause, found by gdb backtrace

Running the game under qemu-user's gdb stub (`qemu-arm -g <port>`, then
`gdb-multiarch` breaking on `exit`) gave the exact stack — the binary keeps its
symbols, so it reads cleanly:

```
#0 exit(1)
#1 sys_debug_log_fatal_error()
#2 sys_persistent_storage_init_pdi()   <- fatal_error(195) at 0x6dee8
#3 sys_init()
#4 main()
```

`sys_persistent_storage_init_pdi` validates two persistent-storage **regions**
(`validate_region`, 0x6d5ec); when both are invalid it erases and calls
`sys_debug_log_fatal_error(195)` → `exit(1)`. `validate_region` reads an 8-byte
header at **EEPROM offset 0x1ff8** (region base 0x2000 minus 8) via
`EEPROMStorageRegion::read_bytes` → `eep_read_bytes`, and accepts it only when

```
header = { u32 value, u32 checksum }   valid iff checksum == ~sum32(value,4)
```

(for a 4-byte value `sum32 == value`, so `checksum == ~value`; the firmware's
own write at 0x5ff8 was `01 00 00 00 fe ff ff ff` = value 1, ~1). The active
region is the one with the higher `value` (ping-pong). Region *data* at 0x2000
is the NVRG section decoded above.

[`make_seed.py`](../../tools/spike1_emu/make_seed.py) now builds a full valid
image — region headers at 0x1ff8/0x5ff8 plus the NVRG/NVBL section — from these
findings.

## How the boot was unlocked

`validate_region` reads its 8-byte header via `EEPROMStorageRegion::read_bytes`
→ `eep_read_bytes`, which drives the EEPROM with `I2C_SLAVE` + **`I2C_RDWR`**,
and does the address-write and the data-read as **two separate `I2C_RDWR`
calls**. The qemu i2c model reset its address pointer each call, so the read
always came back from offset 0. Making the pointer **persist across
transactions** (a `static` in the handler) fixed it. The two regions' headers
live at EEPROM **0x5ff8** and **0x7ff8** (region base minus 8; `read_bytes` adds
each region's own base offset — confirmed from the i2c transaction log), and
`make_seed.py` seeds both with `{value, ~value}`. With that, both regions
validate, `sys_persistent_storage_init` passes, and the game enters its main
loop.

## The current blocker: a node-bus responder

The game now runs and drives the **DMD** (`/dev/spi0`, 2048-byte 128×32×4-bit
frames — captured via `s1hwshim --capture` / `S1_SPI0_CAP`), but the frames are
**blank**: it waits on the **node bus** (`/dev/ttyS4`) before lighting the
playfield. The pty is in place (`nodebus.py`, bound with `S1_TTYS4_CAP`) and the
game configures the port (`tcsetattr` → `B460800` succeeds), but it sends no
lamp data because the nodes never answer registration. It needs a **responder**:

* answer the node identify/registration handshake (`0xfe` → the identify reply;
  reuse the Spike 2 part-id table + the reply-length-as-oracle trick from
  `tools/spike2_emu/hwshim.c` / `plans/spike2_pc_emulation_handoff.md`), then
* decode the switch-report / lamp / coil frames into the shared
  **hardware-state block** so the switch/LED viewer shows live data, and answer
  switch reads from the viewer's injected state. **⚠ The exact Spike 1 node wire
  byte layout is unverified — derive it from the live `nodebus.py` capture now
  that the game talks to the bus; do not hand-invent field offsets.**

## To finish (recommended order)

1. **Node-bus responder** (above) → the game lights the playfield: real DMD
   frames + live switch/lamp/coil state into the viewer.
2. **DMD render** → the frames are already captured (`/dev/spi0`); render the
   128×32×4-bit (or colour) frames to a window (close to the Spike 2
   `padlcd`/`padled` shared-block model). Content appears once step 1 lets the
   game leave the black screen.
3. **Audio** (`/dev/i2s` + `/dev/amp`, capturable the same `--capture` way) →
   the raw-PCM path can reuse the Spike 2 `padrelay` → PortAudio output half.

`SCHED_RR`, custom ioctls, the i2c EEPROM model (persisted + region-seeded), and
persistent-storage init are all handled and the game **boots + runs its main
loop**. The remaining work is device *content* — the node bus, then DMD/audio —
decoded from the live captures the running game now produces.

## The switch-matrix / LED viewer (built now)

`plugins/stern/spike1_emulate.py` defines a **format-agnostic** hardware-state
model — `HardwareState` (switches, RGB lamps/LEDs, coils, each addressed by
`(node, index)`), a fixed-layout shared **`StateBlock`** the node-bus decoder
writes and the viewer reads, and a **`SwitchInput`** block for injected presses
fed back to the game. It is deliberately *not* a wire-format codec: the decoder
owns the (unverified) node bytes and only ever hands the viewer abstract state.

`tools/spike1_emu/s1view.py` renders it — the switch matrix, the lamps/LEDs at
their live colours, and the coils — and injects switch presses on click (the
parity with the Spike 2 playfield window). It runs standalone over a rig run
dir (`--run-dir`) or a synthetic feed (`--demo`), and can emit a PNG
(`--png`). It consumes live data as soon as the node-bus decoder (step 3)
writes the state block.
