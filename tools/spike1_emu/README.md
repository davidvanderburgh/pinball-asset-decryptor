# Spike 1 emulation rig

Runs the **real** Stern Spike 1 game firmware (2015-2016 DMD generation:
WrestleMania, KISS, Whoa Nellie, Game of Thrones, Spider-Man VE, Ghostbusters)
on a PC under qemu-user — the Spike 1 analog of [`tools/spike2_emu/`](../spike2_emu).

**Read [`docs/architecture/spike1_emulation.md`](../../docs/architecture/spike1_emulation.md)
first** — it has the architecture, the boot trace, the device inventory, and
the privilege wall. This README is the operational quick-start.

## Status

With the device model (patched qemu-user + the `s1hwshim` CUSE daemon), the
firmware boots **through board + EEPROM init** — SoC detect → assets → NVRAM →
the board-identity EEPROM → full i2c EEPROM provisioning (~1500 guest
syscalls/boot). The patched qemu models the board EEPROM (`I2C_SLAVE` +
`I2C_RDWR`), persisted across a `game_monitor`-style restart loop. It currently
stalls on **EEPROM content validation** — the firmware re-formats the EEPROM
every boot, so it wants a valid board config (magic/version/checksum) that must
be reverse-engineered from the firmware or a real EEPROM dump. See
[`docs/architecture/spike1_emulation.md`](../../docs/architecture/spike1_emulation.md)
for the details and next step. The switch/LED **viewer** below works today
(synthetic feed, and live data once the node decoder is built).

There are two run paths:

* **`launch.sh` / `run.sh`** — unprivileged (user namespace), `/dev/null`
  device stand-ins. Boots to the EEPROM wall. No root, nothing to build.
* **`emu_root.sh` / `run_root.sh`** — the device-model path (root, via
  `wsl -u root`): patched qemu + CUSE devices, boots past the EEPROM.

## Prerequisites (WSL2 / Linux)

- `qemu-user-static` (armel — `qemu-arm-static`, handles the soft-float binary)
- `binfmt_misc` with qemu registered **with the `F` flag** (Debian/Ubuntu's
  `qemu-user-static` package does this; check `cat /proc/sys/fs/binfmt_misc/qemu-arm`)
- python3 (uses the repo's pure-Python ext4 reader — no extra deps)

## Boot the game

```bash
# 1. Build the rootfs + game dir from a card image (run in WSL/Linux):
python3 build_rootfs.py /path/to/GOT_LE-1_37.iso ~/s1emu/rootfs ~/s1emu/game

# 2. Boot it (bounded; S1_STRACE=1 for a guest syscall trace):
export S1_ROOT=~/s1emu/rootfs S1_GAME=~/s1emu/game S1_STRACE=1
bash run.sh 10          # -> emu.log

# strace shows the boot reaching /dev/i2c-0 (the EEPROM wall).
```

`launch.sh` is the namespace launcher (`run.sh` wraps it with a bounded
process-group kill). Neither needs root.

### Device-model boot (past the EEPROM)

Needs root (via `wsl -u root`, passwordless on WSL) for CUSE + binfmt.

```bash
# one-time: build the patched qemu-user (generic ioctl passthrough) and the
# CUSE hardware-shim daemon.  Build deps (as root): apt-get install -y meson
# ninja-build libglib2.0-dev pkg-config flex bison gcc libfuse3-dev
bash build_qemu.sh                                   # -> ~/qemubuild/qemu-arm
gcc -O2 -o s1hwshim s1hwshim.c $(pkg-config --cflags --libs fuse3)

# boot with the device model (as root, under `wsl -u root`):
export S1_ROOT=~/s1emu/rootfs S1_GAME=~/s1emu/game \
       S1_QEMU=~/qemubuild/qemu-arm S1_HWSHIM=$PWD/s1hwshim S1_STRACE=1 \
       S1_RUNS=3 S1_EE_FILE=/data/board_eeprom.bin S1_I2C_LOG=1
bash run_root.sh 20          # -> emu.log ; restores the stock binfmt on exit
```

Env: `S1_RUNS` = game_monitor-style restart count; `S1_EE_FILE` = persistent
board-EEPROM path (inside the chroot); `S1_I2C_LOG=1` traces every i2c
transaction (slave / R|W / len / bytes) to identify the board chips.

`emu_root.sh` registers the patched qemu in binfmt, starts the CUSE daemons,
binds them onto the device paths in a namespace, and runs the game as root
(which also makes `SCHED_RR` succeed). `run_root.sh` bounds it and **restores
the stock qemu-arm binfmt** afterward, so the Spike 2 rig is unaffected.

## Switch-matrix / LED viewer

```bash
# Live view over a rig run dir (reads s1hw.state, writes s1sw.input):
python s1view.py --run-dir ~/s1emu/run

# Or a synthetic demo feed (works without a booting game):
python s1view.py --demo

# Or render one frame to a PNG:
python s1view.py --demo --png frame.png
```

The viewer shows the **switch matrix**, the **lamps / RGB LEDs** at their live
colours, and the **coils**; click a switch cell to inject a press. It consumes
the format-agnostic hardware-state model in
`pinball_decryptor/plugins/stern/spike1_emulate.py` (`HardwareState` /
`StateBlock` / `SwitchInput`), which the node-bus decoder will populate once
the device model is in place.
