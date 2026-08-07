#!/bin/bash
# Boot a Stern Spike 2 game binary under qemu-user in an ARM chroot.
#
#   PAD_GAME=turtles_pro run_game.sh
#
# ANY TITLE, not just the one this was written for. The rootfs is shared - it is
# the OS partition and carries no title of its own - and each title is a
# directory under games/ holding its own `game` ELF and assets. Which one boots
# is decided here and nowhere else.
. "$(dirname "$0")/padpath.sh"
R=$ROOT
S=$RIG

# STRAIGHT OFF THE CARD, with no extraction:
#
#   PAD_CARD=.../jaws_le-1_02_0.Release.16G.sdcard.raw run_game.sh
#
# cardmount.sh puts the card's games partition on a read-only FUSE mount (see
# there for how that is done without root), and the title directory is bind
# mounted into place inside the namespace below. Extracting a title copies 3-6
# GB and takes minutes; this takes about a second and cannot modify the image.
#
# PAD_GAME_DIR runs a title from a directory ANYWHERE - an extraction that was
# never put under games/, a working copy, a network share. Same bind mount, one
# fewer step. Both take a title that is not in the rootfs and put it there for
# the length of the run without copying it.
CARD_SRC=""
if [ -n "${PAD_CARD:-}" ]; then
    CARD_SRC=$(bash "$S/cardmount.sh" "$PAD_CARD" | tail -1)
    [ -d "$CARD_SRC" ] || { echo "[run] could not mount $PAD_CARD" >&2; exit 1; }
    GAME=$(basename "$CARD_SRC")
    mkdir -p "$R/games/$GAME"
    echo "[run] title: $GAME (from the card, not extracted)"
elif [ -n "${PAD_GAME_DIR:-}" ]; then
    CARD_SRC=${PAD_GAME_DIR%/}
    [ -x "$CARD_SRC/game" ] || {
        echo "[run] $CARD_SRC holds no game ELF" >&2; exit 1; }
    GAME=$(basename "$CARD_SRC")
    mkdir -p "$R/games/$GAME"
    echo "[run] title: $GAME (from $CARD_SRC)"
fi

# Otherwise the title is PAD_GAME, else whatever games/game already points at
# (the machine's own convention, so reading it is not a rig invention), else the
# only one extracted.
if [ -z "$CARD_SRC" ]; then
    GAME=${PAD_GAME:-}
    if [ -z "$GAME" ]; then
        GAME=$(readlink "$R/games/game" 2>/dev/null); GAME=${GAME%/game}
    fi
    if [ -z "$GAME" ]; then
        GAME=$(cd "$R/games" && ls -d */ 2>/dev/null | tr -d / | head -1)
    fi
    if [ ! -x "$R/games/$GAME/game" ]; then
        echo "[run] no game ELF at "$R/games/$GAME/game"" >&2
        echo "[run] extracted titles: $(cd "$R/games" && ls -d */ 2>/dev/null | tr -d / | tr '\n' ' ')" >&2
        echo "[run] or run it straight off a card: PAD_CARD=<image.raw>" >&2
        exit 1
    fi
    echo "[run] title: $GAME"
fi

mkdir -p "$R"/dev "$R"/proc "$R"/sys "$R"/data "$R"/dump/log/connectivity "$R"/tmp "$R"/run

# PAD_MEMTOTAL_KB=1048576 makes the guest see a machine with 1 GB, which is
# what an i.MX6 Spike 2 board has, instead of this PC's 31.
#
# OPT-IN, because the theory it was built for turned out to be WRONG. Jaws LE
# dies in memcpy with a null destination, and the plausible story was that the
# game sizes its asset budget from MemTotal and a 32-bit process cannot use
# 31 GB. Reporting 1 GB changed nothing: same crash, same address, after the
# same 125 scene loads. The reasoning about the address space is still sound and
# the knob is still worth having, but it does not get to quietly change how
# every title loads on the strength of a theory that failed its one test.
MEM_KB=${PAD_MEMTOTAL_KB:-}
[ -n "$MEM_KB" ] && awk -v t="$MEM_KB" '
    BEGIN { OFS="" }
    { name=$1; val=$2; unit=$3 }
    name=="MemTotal:"     { val=t }
    name=="MemFree:"      { val=int(t/2) }
    name=="MemAvailable:" { val=int(t*3/4) }
    name=="Buffers:"      { val=int(t/64) }
    name=="Cached:"       { val=int(t/8) }
    name=="SwapTotal:"    { val=0 }
    name=="SwapFree:"     { val=0 }
    { printf "%-15s %8s %s\n", name, val, unit }
' /proc/meminfo > "$R/dump/meminfo" 2>/dev/null
[ -n "$MEM_KB" ] || rm -f "$R/dump/meminfo"

# /games/{game,conagent,data} are symlinks into the title directory on the card
[ -d "$R/games/data" ] && [ ! -L "$R/games/data" ] && rmdir "$R/games/data" 2>/dev/null
ln -sfn "$GAME/game"     "$R/games/game"
ln -sfn "$GAME/conagent" "$R/games/conagent"
ln -sfn "$GAME/data"     "$R/games/data"

# placeholder files that host device nodes get bind-mounted onto
for f in null zero urandom random tty console spidev1.0 i2c-1 ttymxc1 ttymxc0 rtc mxc_vpu; do
  [ -e "$R/dev/$f" ] || : > "$R/dev/$f"
done

# WHERE THE TITLE'S FILES REALLY ARE, published for anything that needs to read
# them from outside this script. NOT redundant with `games/<title>`: on a card
# or folder run that path is the empty stub created above, and the real
# directory is bind-mounted into it inside the private namespace below, which
# nothing outside the run can see. mktables.py reads this to find the game
# binary and the playfield artwork; gameinfo.py reads it to name the title.
mkdir -p "$R/dump"
{
    echo "name=$GAME"
    echo "dir=${CARD_SRC:-$R/games/$GAME}"
} > "$R/dump/title"

# Virtual node bus: hold the master end of a pty outside the container and
# bind its slave onto /dev/ttymxc1, so the game's serial traffic is captured.
#
# RUN THE RIG'S OWN COPY. This used to exec `$HOME/nodebus.py`, a copy outside
# the checkout that nothing kept in step with the one in git - so the file being
# read here and the file being edited there could differ with no sign.
export PAD_NODEBUS_DIR="$R/dump"
rm -f "$R/dump/nodebus.path"
python3 "$S/nodebus.py" >/dev/null 2>&1 &
NODEBUS_PID=$!
for _ in $(seq 1 50); do [ -s "$R/dump/nodebus.path" ] && break; sleep 0.1; done
NODEBUS_PTY=$(cat "$R/dump/nodebus.path" 2>/dev/null)
echo "[run] node bus pty: ${NODEBUS_PTY:-NONE}"
# The bind mount needs a mountpoint, so a card or folder run creates an empty
# directory under games/ that outlives the run. Left behind it looks exactly
# like an extracted title to anything that lists that directory - the Emulate
# tab offered `elvira3` and `jaws_le` as runnable when both were empty shells.
# rmdir only removes it if it is empty, so an extracted title is never at risk.
STUB=""
[ -n "$CARD_SRC" ] && STUB="$R/games/$GAME"
trap 'kill $NODEBUS_PID 2>/dev/null; [ -n "$STUB" ] && rmdir "$STUB" 2>/dev/null' EXIT

unshare -r -m -p -f bash -s "$R" "$NODEBUS_PTY" "$GAME" "$CARD_SRC" <<'INNER'
R="$1"
NODEBUS_PTY="$2"
GAME="$3"
CARD_SRC="$4"
# procfs needs a PID namespace to mount (see the -p -f on unshare below).
# Without it this silently produced an EMPTY /proc: no /proc/meminfo, and the
# game sizes its asset budget from that, so it loaded no scenes at all.
mount -t proc proc "$R/proc"

# The guest's /proc/meminfo, when PAD_MEMTOTAL_KB asked for one. See where it
# is written, above, for what it is for and why it is not on by default.
if [ -f "$R/dump/meminfo" ]; then
    mount --bind "$R/dump/meminfo" "$R/proc/meminfo"
fi
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

# THE CARD ITSELF, if one was given. The FUSE mount was made outside this
# namespace and so is inherited; binding its title directory into games/ is what
# lets the guest see the assets without a byte being copied. It goes AFTER the
# loop above, because binding it first would put it under a mount that is then
# replaced, and the game would find an empty directory.
if [ -n "$CARD_SRC" ]; then
    mount --bind "$CARD_SRC" "$R/games/$GAME" \
        || { echo "[run] could not bind the card at $CARD_SRC" >&2; exit 1; }
fi

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
