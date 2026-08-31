#!/bin/bash
# Spike 1 emulation — full device-model boot (needs root, via `wsl -u root`).
#
# Runs the static ARM game under a PATCHED qemu-user (generic ioctl
# passthrough, so CUSE device models receive the game's device ioctls) with:
#   * /dev/i2c-0  -> CUSE i2c model (board EEPROM at 0x50)
#   * dmd/i2s/amp/adc/gpio/spi* -> CUSE passive models (accept ioctls)
#   * ttyS4 (node bus) -> a pty (a responder attaches separately)
# and a writable /data,/dump + fake i.MX6 /proc/cpuinfo, in a mount+pid
# namespace.  Set S1_STRACE=1 for a guest syscall trace.
#
# Env: S1_ROOT, S1_GAME (from build_rootfs.py); S1_QEMU (patched qemu-arm);
#      S1_HWSHIM (compiled s1hwshim); S1_CPUINFO (default: this dir's cpuinfo).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${S1_CPUINFO:=$HERE/cpuinfo}"
: "${S1_STRACE:=0}"
: "${S1_EEPROM:=}"
[ "$(id -u)" = 0 ] || { echo "run as root (wsl -u root)"; exit 2; }
[ -n "${S1_ROOT:-}${S1_GAME:-}" ] || { echo "set S1_ROOT and S1_GAME"; exit 2; }
: "${S1_QEMU:?set S1_QEMU to the patched qemu-arm}"
: "${S1_HWSHIM:?set S1_HWSHIM to the compiled s1hwshim}"

R="$S1_ROOT"; G="$S1_GAME"
GAME_NAME="$(tr -d '[:space:]' < "$G/.game_name" 2>/dev/null)"; : "${GAME_NAME:=GAME}"
# persistent board EEPROM (path is inside the chroot) + how many times to
# (re)launch the game — first boot provisions the EEPROM then exits expecting
# game_monitor to relaunch it, so we loop like game_monitor.
: "${S1_EE_FILE:=/data/board_eeprom.bin}"
: "${S1_RUNS:=1}"
# DMD refresh the display thread is paced to (see s1hwshim --dmd-fps).  Without
# it the game renders as fast as qemu can spin and attract plays ~80x too fast.
: "${S1_DMD_FPS:=60}"

# ---- 1. binfmt: route ARM ELF through the patched qemu (F flag = works in
#         chroot; disable the stock qemu-arm so ours wins) ----
BF=/proc/sys/fs/binfmt_misc
[ -e "$BF/qemu-arm" ] && echo 0 > "$BF/qemu-arm" 2>/dev/null || true
if [ ! -e "$BF/qemu-arm-pad" ]; then
  echo ':qemu-arm-pad:M::\x7f\x45\x4c\x46\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:'"$S1_QEMU"':POCF' > "$BF/register" 2>/dev/null \
    || echo "warn: could not register binfmt (already set?)"
fi

# ---- 2. CUSE device daemons (host side; killed on exit) ----
PIDS=()
start_shim() { setsid "$S1_HWSHIM" "$@" >/tmp/s1shim_$2.log 2>&1 & PIDS+=($!); }
EEARG=(); [ -n "$S1_EEPROM" ] && EEARG=(--eeprom "$S1_EEPROM")
start_shim --model i2c --name s1i2c0 "${EEARG[@]}"
for d in dmd i2s amp adc gpio spi0 spi1; do
  if [ "$d" = dmd ]; then
    # pace the DMD frame-commit ioctl to a real refresh so the display thread
    # doesn't free-run (attract otherwise plays dozens of x too fast).
    start_shim --model passive --name "s1$d" --dmd-fps "$S1_DMD_FPS"
  elif [ "$d" = spi0 ] && [ -n "${S1_SPI0_CAP:-}" ]; then
    start_shim --model passive --name "s1$d" --capture "$S1_SPI0_CAP"
  elif [ "$d" = i2s ]; then
    # pace the audio stream at its real-time PCM rate (the audio twin of the
    # DMD pacing: unpaced, the audio thread free-runs pumping silence at
    # thousands of writes/s) and tee it into a FIFO for the host speaker
    # chain when start.sh names one (S1_AUDIO_FIFO; no FIFO = discard).
    # 44100 Hz s16 stereo is what the games configure (system_sample_rate in
    # the game ELF, read live: 44100).
    start_shim --model passive --name "s1$d" \
        --pcm-rate "${S1_PCM_RATE:-44100}" --pcm-ch "${S1_PCM_CH:-2}" \
        ${S1_AUDIO_FIFO:+--fifo "$S1_AUDIO_FIFO"}
  elif [ "$d" = adc ] && [ -n "${S1_ADC_WAVEFORM:-}" ]; then
    # /dev/adc feeds the mains line-frequency sense (LineSenseThread).  A synthetic
    # 60 Hz AC waveform (s1hwshim --waveform) is available but OFF by default: it
    # does NOT yet satisfy the boot-time factory line-frequency self-test
    # (sys_factory_config_exec_pdi -> "CHECK POWER DISTRIBUTION BOARD"), which needs
    # faithful analog edge timing — see docs/architecture/spike1_emulation.md.  Set
    # S1_ADC_WAVEFORM=1 to experiment; default is a passive (silent) ADC.
    start_shim --model passive --name "s1$d" --waveform
  else
    start_shim --model passive --name "s1$d"
  fi
done
# node bus + aux serial: ptys, held open so the fd survives (a responder can
# attach to the master later); socat makes a pty pair whose slave we bind.
sleep 1

cleanup() { kill "${PIDS[@]}" 2>/dev/null; }
trap cleanup EXIT

# ---- 3. namespace + chroot + run ----
export R G GAME_NAME S1_CPUINFO S1_QEMU S1_STRACE S1_EE_FILE S1_RUNS S1_I2C_LOG S1_GDB S1_TTYS4_CAP
unshare -m -p -f bash -c '
  set -u
  mount --make-rprivate / 2>/dev/null || true
  mount -t proc proc "$R/proc" 2>/dev/null || true
  mount --bind "$S1_CPUINFO" "$R/proc/cpuinfo" 2>/dev/null || true
  mount -t sysfs sysfs "$R/sys" 2>/dev/null || true
  mkdir -p "$R/data" "$R/dump/log" "$R/games/$GAME_NAME"
  chmod -R 0777 "$R/data" "$R/dump" 2>/dev/null || true
  mount --bind "$G" "$R/games/$GAME_NAME"
  ln -sf "/games/$GAME_NAME/game" "$R/games/game" 2>/dev/null || true
  for d in null zero full random urandom tty; do
    t="$R/dev/$d"; [ -e "$t" ] || : > "$t"; mount --bind "/dev/$d" "$t" 2>/dev/null || true
  done
  # CUSE-backed Stern devices
  bind_dev() { local host="$1" path="$2"; local t="$R/dev/$path"
    [ -e "$t" ] || : > "$t"; mount --bind "/dev/$host" "$t" 2>/dev/null || true; }
  bind_dev s1i2c0 i2c-0
  bind_dev s1dmd  dmd
  bind_dev s1i2s  i2s
  bind_dev s1amp  amp
  bind_dev s1adc  adc
  bind_dev s1gpio gpio
  bind_dev s1spi0 spi0
  bind_dev s1spi1 spi1
  # devices without a model yet -> /dev/null stand-ins
  _nulldevs="i2c-1 i2c-2 ttyS0 ttyS3 rtc backlight egd watchdog mem"
  [ -n "${S1_TTYS4_CAP:-}" ] || _nulldevs="$_nulldevs ttyS4"
  for d in $_nulldevs; do
    t="$R/dev/$d"; [ -e "$t" ] || : > "$t"; mount --bind /dev/null "$t" 2>/dev/null || true
  done
  # node bus capture: bind /dev/ttyS4 to a host file so the game'"'"'s node-bus
  # writes (lamp/coil frames) land there for decoding into the viewer state.
  if [ -n "${S1_TTYS4_CAP:-}" ]; then
    t="$R/dev/ttyS4"; [ -e "$t" ] || : > "$t"
    mount --bind "$S1_TTYS4_CAP" "$t" 2>/dev/null || true
  fi
  rm -f "$R/usr/bin/qemu-arm-pad" 2>/dev/null || true
  cp "$S1_QEMU" "$R/usr/bin/qemu-arm-pad" 2>/dev/null || true
  # game_monitor-style restart loop: first boot provisions the (now persistent)
  # board EEPROM then exits; relaunch so the next boot sees a valid EEPROM.
  _n=0
  while [ "$_n" -lt "$S1_RUNS" ]; do
    _n=$((_n + 1))
    echo "======== GAME RUN $_n / $S1_RUNS ========"
    if [ -n "${S1_GDB:-}" ]; then
      # run the MAIN game under the qemu gdb stub; children still use binfmt,
      # no stub; qemu waits for gdb on this TCP port host-localhost, the
      # namespace being mount+pid not net
      chroot "$R" /bin/sh -c "cd /games/$GAME_NAME && exec /usr/bin/qemu-arm-pad -g $S1_GDB ./game"
    elif [ "$S1_STRACE" = "1" ]; then
      chroot "$R" /bin/sh -c "cd /games/$GAME_NAME && exec /usr/bin/qemu-arm-pad -strace ./game"
    else
      chroot "$R" /bin/sh -c "cd /games/$GAME_NAME && exec ./game"
    fi
    echo "======== RUN $_n exited (code $?) ========"
    sleep 0.5
  done
'
