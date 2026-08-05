#!/bin/bash
# Boot a Stern Spike 2 game binary under qemu-user in an ARM chroot.
#
#   PAD_GAME=turtles_pro run_game.sh
#
# ANY TITLE, not just the one this was written for. The rootfs is shared - it is
# the OS partition and carries no title of its own - and each title is a
# directory under games/ holding its own `game` ELF and assets. Which one boots
# is decided here and nowhere else.
R=/home/david/spike2root

# The title: PAD_GAME, else whatever games/game already points at (the machine's
# own convention, so reading it is not a rig invention), else the only one
# extracted.
GAME=${PAD_GAME:-}
if [ -z "$GAME" ]; then
    GAME=$(readlink "$R/games/game" 2>/dev/null); GAME=${GAME%/game}
fi
if [ -z "$GAME" ]; then
    GAME=$(cd "$R/games" && ls -d */ 2>/dev/null | tr -d / | head -1)
fi
if [ ! -x "$R/games/$GAME/game" ]; then
    echo "[run] no game ELF at $R/games/$GAME/game" >&2
    echo "[run] extracted titles: $(cd "$R/games" && ls -d */ 2>/dev/null | tr -d / | tr '\n' ' ')" >&2
    exit 1
fi
echo "[run] title: $GAME"

mkdir -p "$R"/dev "$R"/proc "$R"/sys "$R"/data "$R"/dump/log/connectivity "$R"/tmp "$R"/run

# /games/{game,conagent,data} are symlinks into the title directory on the card
[ -d "$R/games/data" ] && [ ! -L "$R/games/data" ] && rmdir "$R/games/data" 2>/dev/null
ln -sfn "$GAME/game"     "$R/games/game"
ln -sfn "$GAME/conagent" "$R/games/conagent"
ln -sfn "$GAME/data"     "$R/games/data"

# placeholder files that host device nodes get bind-mounted onto
for f in null zero urandom random tty console spidev1.0 i2c-1 ttymxc1 ttymxc0 rtc mxc_vpu; do
  [ -e "$R/dev/$f" ] || : > "$R/dev/$f"
done

# Virtual node bus: hold the master end of a pty outside the container and
# bind its slave onto /dev/ttymxc1, so the game's serial traffic is captured.
rm -f /home/david/nodebus.path
python3 /home/david/nodebus.py >/dev/null 2>&1 &
NODEBUS_PID=$!
for _ in $(seq 1 50); do [ -s /home/david/nodebus.path ] && break; sleep 0.1; done
NODEBUS_PTY=$(cat /home/david/nodebus.path 2>/dev/null)
echo "[run] node bus pty: ${NODEBUS_PTY:-NONE}"
trap 'kill $NODEBUS_PID 2>/dev/null' EXIT

unshare -r -m -p -f bash -s "$R" "$NODEBUS_PTY" "$GAME" <<'INNER'
R="$1"
NODEBUS_PTY="$2"
GAME="$3"
# procfs needs a PID namespace to mount (see the -p -f on unshare below).
# Without it this silently produced an EMPTY /proc: no /proc/meminfo, and the
# game sizes its asset budget from that, so it loaded no scenes at all.
mount -t proc proc "$R/proc"
# A writable fake /sys: the real one has none of the i.MX6 nodes the game reads
# (soc_id, the OTP fuse table, the LVDS backlight), so sysfs is no better here.
mount -t tmpfs tmpfs "$R/sys"
mkdir -p "$R/sys/devices/soc0" "$R/sys/fsl_otp" "$R/sys/class/backlight/backlight_lvds.28" \
         "$R/sys/class/gpio" "$R/sys/class/net" "$R/sys/bus/iio/devices/iio:device0"
# i.MX6Q IS DELIBERATE AND i.MX6DL IS WORSE - DO NOT "CORRECT" THIS.
# libvpu.so.4 reads soc_id and picks vpu_fw_imx6q.bin or vpu_fw_imx6d.bin from
# it. The card ships ONLY vpu_fw_imx6d.bin, so i.MX6Q makes the firmware open
# FAIL - and that failure is what makes vpudec give up quickly and let the boot
# continue. With i.MX6DL the firmware loads, libvpu then tries to bring up VPU
# hardware that does not exist behind the anonymous mmap, and gst_element_
# factory_make("vpudec") NEVER RETURNS: the boot wedges, the audio queue pool is
# never built, and the game produces no PCM at all. Measured both ways.
echo "i.MX6Q"   > "$R/sys/devices/soc0/soc_id"
echo "1.2"      > "$R/sys/devices/soc0/revision"
echo "Freescale i.MX6 Quad/DualLite (Device Tree)" > "$R/sys/devices/soc0/machine"
echo "0x12345678" > "$R/sys/fsl_otp/HW_OCOTP_CFG0"
echo "0x9abcdef0" > "$R/sys/fsl_otp/HW_OCOTP_CFG1"
echo "0x00001122" > "$R/sys/fsl_otp/HW_OCOTP_MAC0"
echo "0x33445566" > "$R/sys/fsl_otp/HW_OCOTP_MAC1"
echo 7   > "$R/sys/class/backlight/backlight_lvds.28/brightness"
echo 7   > "$R/sys/class/backlight/backlight_lvds.28/max_brightness"
echo 7   > "$R/sys/class/backlight/backlight_lvds.28/actual_brightness"
echo 60  > "$R/sys/bus/iio/devices/iio:device0/in_power_frequency"
echo 120 > "$R/sys/bus/iio/devices/iio:device0/in_power_input"
: >      "$R/sys/class/gpio/export"
mount -t tmpfs tmpfs "$R/tmp" 2>/dev/null
mount -t tmpfs tmpfs "$R/run" 2>/dev/null
# the i.MX6 VPU library keeps its instance table in /dev/shm/vpu
mkdir -p "$R/dev/shm"
mount -t tmpfs tmpfs "$R/dev/shm"

# On the machine /games, /data and /dump are separate partitions and the game
# checks /proc/mounts for them. Binding each directory onto itself makes it a
# real mount point without disturbing its contents.
for m in games data dump; do mount --bind "$R/$m" "$R/$m"; done

# real host char devices
for f in null zero urandom random; do mount --bind /dev/$f "$R/dev/$f"; done
# fakes: opening succeeds, ioctls will fail
for f in spidev1.0 i2c-1 ttymxc0 rtc mxc_vpu console tty; do
  mount --bind /dev/null "$R/dev/$f"
done
# The node bus needs a real tty underneath: glibc's tcsetattr reaches the
# kernel through an internal call the shim cannot interpose, and it fails on
# anything that is not a terminal. Traffic itself is still served by the shim,
# which sees the byte count passed to read() and so learns the reply length the
# game expects for each request.
if [ -n "$NODEBUS_PTY" ] && [ -e "$NODEBUS_PTY" ]; then
  mount --bind "$NODEBUS_PTY" "$R/dev/ttymxc1"
else
  mount --bind /dev/null "$R/dev/ttymxc1"
fi

cd "$R"
# LD_PRELOAD is applied to the game alone: the busybox tools in this rootfs do
# not link libdl and fail to start with the shim forced on them.
exec chroot "$R" /bin/sh -c \
  "cd /games/$GAME && LD_PRELOAD=/lib/hwshim.so PAD_AUDIO_OUT=/dump/audio.raw PAD_SEGV_REPORT=1 exec ./game"
INNER
