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
# Where the game dir is bound inside the guest and which binary is run.  The
# 2015-2016 titles live at /games/<TITLE>/game.  An EARLY card (the 2012 home
# models, PAD-101) keeps its game at /usr/local/games/<title>/ and launches
# a symlink's target there (`gamer`; the debug build `game` sits beside it) —
# build_rootfs.py writes both facts as markers, absent on a DMD-generation
# extraction so that path is byte-for-byte what it always was.
GAME_PATH="$(tr -d '[:space:]' < "$G/.game_path" 2>/dev/null)"; : "${GAME_PATH:=/games/$GAME_NAME}"
GAME_EXE="$(tr -d '[:space:]' < "$G/.game_exe" 2>/dev/null)"; : "${GAME_EXE:=game}"
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
# S1_NO_BINFMT=1: leave the kernel's ARM handler alone.  The game is then run
# through the patched qemu EXPLICITLY (the strace/gdb launch lines below do
# that anyway), so a boot for a trace cannot disturb a Spike 2 run on the same
# machine — whose next child exec would otherwise pick up our interpreter.
if [ "${S1_NO_BINFMT:-0}" != "1" ]; then
[ -e "$BF/qemu-arm" ] && echo 0 > "$BF/qemu-arm" 2>/dev/null || true
if [ ! -e "$BF/qemu-arm-pad" ]; then
  echo ':qemu-arm-pad:M::\x7f\x45\x4c\x46\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:'"$S1_QEMU"':POCF' > "$BF/register" 2>/dev/null \
    || echo "warn: could not register binfmt (already set?)"
fi
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
  elif [ "$d" = gpio ] && [ -n "${S1_GPIO_FILE:-}" ]; then
    # the early era reads cabinet switches off GPIO pins (see s1hwshim.c
    # --gpio-file); the file is the injection point for them.
    start_shim --model passive --name "s1$d" --gpio-file "$S1_GPIO_FILE"
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

# ---- 3. namespace + chroot (or pivot) + run ----
# S1_PIVOT=1 boots a CHECKPOINTABLE guest (item 87, save states) — the Spike 2
# PAD_PIVOT recipe verbatim: criu CANNOT dump a chroot'd task ("The root task
# has another root than mntns", criuladder.sh rung), so under S1_PIVOT the
# guest gets its own root via pivot_root inside the same mount+pid namespace,
# and qemu is exec'd EXPLICITLY from a copy INSIDE the rootfs — after the pivot
# detaches the host tree, the binfmt interpreter's host path could not be
# resolved for criu's mapping walk.  The copy's basename is "game" so comm
# stays "game" (status.sh, s1ball.py and alive-checks all identify the guest by
# comm); the real ARM ELF is its argument.  Our qemu is static-pie, so no host
# libraries leak into its mappings (checked: `file` says statically linked).
# Fully OPT-IN: with S1_PIVOT unset the boot is semantically the boot it has
# always been (same mounts, same chroot loop) — a failed pivot prerequisite
# COSTS THE FEATURE, NOT THE RUN, and says so.
: "${S1_PIVOT:=0}"
PIVOTROOT=""
if [ "$S1_PIVOT" = "1" ]; then
    PIVOTROOT=$(command -v pivot_root || true)
    [ -n "$PIVOTROOT" ] || [ ! -x /usr/sbin/pivot_root ] || PIVOTROOT=/usr/sbin/pivot_root
    BB=$(command -v busybox || true)
    BB_STATIC=0
    [ -n "$BB" ] && file -L "$BB" 2>/dev/null | grep -q 'statically linked' && BB_STATIC=1
    if [ -z "$PIVOTROOT" ] || [ "$BB_STATIC" != 1 ]; then
        echo "[emu] S1_PIVOT needs pivot_root + a STATIC busybox (apt install busybox-static);"
        echo "[emu] this machine lacks one, so save states are off for this run."
        echo "[emu] Starting the ordinary way - nothing else about the run changes."
        S1_PIVOT=0
    else
        # the two binaries that must live INSIDE the rootfs (see header above)
        mkdir -p "$R/.padqemu"
        cp -f "$S1_QEMU" "$R/.padqemu/game"
        cp -f "$BB" "$R/busybox"
        echo "[emu] S1_PIVOT: checkpointable boot (pivot_root, explicit qemu)"
    fi
fi

# The mounts, ONE definition for both boot paths (export -f carries it into
# the namespace).  Same commands the chroot path has always run.
s1_mounts() {
  mount --make-rprivate / 2>/dev/null || true
  # pivot_root needs the new root to BE a mount, and everything mounted below
  # rides the pivot, so the self-bind of $R comes FIRST (guarded: the chroot
  # path is untouched).
  [ "$S1_PIVOT" = "1" ] && mount --bind "$R" "$R" 2>/dev/null
  mount -t proc proc "$R/proc" 2>/dev/null || true
  # the fake i.MX6 cpuinfo is STAGED INSIDE the rootfs and bound from there:
  # a bind whose source is the repo tree (/mnt/c drvfs) ties a save-state slot
  # to that checkout's path and to a mount the restore namespace strips - the
  # copy makes the slot self-contained (same trick as Spike 2's meminfo).
  mkdir -p "$R/.padqemu"
  cp -f "$S1_CPUINFO" "$R/.padqemu/cpuinfo" 2>/dev/null || true
  mount --bind "$R/.padqemu/cpuinfo" "$R/proc/cpuinfo" 2>/dev/null \
    || mount --bind "$S1_CPUINFO" "$R/proc/cpuinfo" 2>/dev/null || true
  mount -t sysfs sysfs "$R/sys" 2>/dev/null || true
  mkdir -p "$R/data" "$R/dump/log" "$R$GAME_PATH"
  chmod -R 0777 "$R/data" "$R/dump" 2>/dev/null || true
  mount --bind "$G" "$R$GAME_PATH"
  [ "$GAME_PATH" = "/games/$GAME_NAME" ] \
    && ln -sf "/games/$GAME_NAME/game" "$R/games/game" 2>/dev/null || true
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
  # node bus capture: bind /dev/ttyS4 to a host file so the game's node-bus
  # writes (lamp/coil frames) land there for decoding into the viewer state.
  if [ -n "${S1_TTYS4_CAP:-}" ]; then
    t="$R/dev/ttyS4"; [ -e "$t" ] || : > "$t"
    mount --bind "$S1_TTYS4_CAP" "$t" 2>/dev/null || true
  fi
  rm -f "$R/usr/bin/qemu-arm-pad" 2>/dev/null || true
  cp "$S1_QEMU" "$R/usr/bin/qemu-arm-pad" 2>/dev/null || true
}
export -f s1_mounts
export R G GAME_NAME GAME_PATH GAME_EXE S1_CPUINFO S1_QEMU S1_STRACE S1_NO_BINFMT S1_EE_FILE S1_RUNS S1_I2C_LOG S1_GDB S1_TTYS4_CAP S1_PIVOT PIVOTROOT

if [ "$S1_PIVOT" = "1" ]; then
  # Checkpointable boot.  The game_monitor-style restart loop moves OUTSIDE
  # the namespace (first boot provisions the EEPROM then exits; slam tilt
  # soft-restarts the same way): under pivot the inner shell EXECS the game so
  # the guest is the pid-namespace init AND its session leader — both criu
  # requirements ("A session leader of N(1) is outside of its pid namespace").
  # Each restart gets a fresh namespace + fresh mounts, which is idempotent.
  # stdio is reopened INSIDE the rootfs (criu refuses an fd on a mount that
  # left with the pivot: "Can't lookup mount for fd=1"), so under S1_PIVOT the
  # game's own output — including qemu's PAD/spike1 dump lines — is at
  # <rootfs>/dump/game.out, NOT in emu.log.  Stray inherited fds 3..63 (two
  # /dev/ptmx from the wsl.exe ancestry, measured on the Spike 2 ladder and
  # re-measured here on WWE's fd table) are closed for the same reason.
  # S1_HOLDOFF (a flag file): while it exists the loop PARKS — no relaunch,
  # shims and namespace machinery alive — so a save-state restore can kill the
  # guest and take its place without the loop racing it, and without tearing
  # down the CUSE devices the restored guest must reopen (the EXIT trap kills
  # the shims when THIS script dies, which is exactly what a restore must not
  # cause).  Removing the flag resumes the loop: a fresh boot, which is also
  # the recovery path when a restored guest ends.
  _n=0
  while [ "$_n" -lt "$S1_RUNS" ]; do
    if [ -n "${S1_HOLDOFF:-}" ] && [ -e "$S1_HOLDOFF" ]; then
      sleep 1
      continue
    fi
    _n=$((_n + 1))
    echo "======== GAME RUN $_n / $S1_RUNS (pivot) ========"
    unshare -m -p -f setsid bash -c '
      set -u
      s1_mounts
      for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done
      cd "$R"
      mkdir -p oldroot
      if "$PIVOTROOT" . oldroot; then
        cd /
        /busybox umount -l /oldroot
        cd "$GAME_PATH" || exit 1
        exec /.padqemu/game "./$GAME_EXE" </dev/null >/dump/game.out 2>&1
      fi
      # a pivot that fails here still costs only the feature: fall back to the
      # chroot exec for THIS run so the boot is not lost.
      rmdir oldroot 2>/dev/null
      echo "[emu] pivot_root failed - this run is not checkpointable"
      exec chroot "$R" /bin/sh -c "cd $GAME_PATH && exec ./$GAME_EXE"
    '
    echo "======== RUN $_n exited (code $?) ========"
    sleep 0.5
  done
else
  unshare -m -p -f bash -c '
  set -u
  s1_mounts
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
      chroot "$R" /bin/sh -c "cd $GAME_PATH && exec /usr/bin/qemu-arm-pad -g $S1_GDB ./$GAME_EXE"
    elif [ "$S1_STRACE" = "1" ]; then
      chroot "$R" /bin/sh -c "cd $GAME_PATH && exec /usr/bin/qemu-arm-pad -strace ./$GAME_EXE"
    elif [ "${S1_NO_BINFMT:-0}" = "1" ]; then
      # binfmt untouched, so a bare exec would land in the STOCK qemu-arm the
      # kernel has registered (no ioctl passthrough: every device ioctl fails
      # and the game asserts at its first one) - run the patched qemu here.
      # (No apostrophes in here: this whole loop is one single-quoted string.)
      # ... as a copy named game, so comm stays game (status.sh, s1own.sh
      # and the tab all identify the guest by comm, as the pivot path does).
      mkdir -p "$R/.padqemu" && cp -f "$R/usr/bin/qemu-arm-pad" "$R/.padqemu/game"
      chroot "$R" /bin/sh -c "cd $GAME_PATH && exec /.padqemu/game ./$GAME_EXE"
    else
      chroot "$R" /bin/sh -c "cd $GAME_PATH && exec ./$GAME_EXE"
    fi
    echo "======== RUN $_n exited (code $?) ========"
    sleep 0.5
  done
'
fi
