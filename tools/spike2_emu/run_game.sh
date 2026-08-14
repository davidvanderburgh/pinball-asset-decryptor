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

# PAD_PIVOT=1 boots a CHECKPOINTABLE guest (item 13, save states). The default
# path chroots, and criu CANNOT dump a chroot'd task - the ladder measured it:
# "The root task has another root than mntns". So under PAD_PIVOT the guest gets
# its own root via pivot_root instead of chroot, and two binaries have to live
# INSIDE the rootfs, because after the pivot detaches the host tree they are the
# only two things that still need to run:
#   * an x86 STATIC busybox, to umount the old root. The rootfs's own busybox is
#     ARM and would need qemu - which we are about to exec INTO, so it cannot
#     also do the umount. busybox-static puts a native one at /bin/busybox.
#   * qemu itself, because via binfmt the interpreter is on the host tree
#     (/usr/libexec/qemu-binfmt/arm-binfmt-P) and criu could not resolve its
#     mapping once that tree is gone. Exec'd explicitly, env still propagates to
#     the guest exactly as binfmt does (qemu is static, so LD_PRELOAD - an ARM
#     path - is ignored by the host process and seen only by the guest loader).
# Fully OPT-IN: with PAD_PIVOT unset, nothing below changes and the boot is
# byte-for-byte the chroot path it has always been.
PIVOT=${PAD_PIVOT:-}
if [ -n "$PIVOT" ]; then
    QEMU=$(command -v qemu-arm-static)
    [ -x "$QEMU" ] || { echo "[run] PAD_PIVOT needs qemu-arm-static" >&2; exit 1; }
    # pad_static_busybox (padpath.sh) is the ONE test for this - watch.sh asks
    # it before it requests a pivot at all, and setupcheck.sh asks it before
    # Start is pressed. A run that gets here anyway was asked for by hand.
    if ! pad_static_busybox; then
        echo "[run] PAD_PIVOT needs a STATIC busybox at /bin/busybox (apt install busybox-static)" >&2
        exit 1
    fi
    # ...AND THE PROGRAM THAT DOES THE PIVOT, which this script used to spell
    # as a bare `pivot_root` and never checked for. A machine without it on
    # PATH answers with `bash: pivot_root: command not found` and the run is
    # over - reported 2026-08-11, one release after the busybox fault above and
    # by the same user. pad_pivot_root_cmd knows the three places it can come
    # from (see padpath.sh); the same rules apply to this test as to that one,
    # so watch.sh asks before it requests a pivot and getting here anyway means
    # the pivot was asked for by hand.
    if ! PIVOTROOT=$(pad_pivot_root_cmd); then
        echo "[run] PAD_PIVOT needs pivot_root and this machine has none:" >&2
        echo "[run]   not on PATH, not at /usr/sbin/pivot_root, and the" >&2
        echo "[run]   busybox here has no pivot_root applet." >&2
        echo "[run]   apt install busybox-static     (then start again)" >&2
        exit 1
    fi
    # ★ comm MUST stay "game". The whole rig identifies the guest by comm=game
    # (alive.sh, watch.sh teardown, savestate.sh, status.sh) - it is the ONE
    # stable name across platforms. Under binfmt the kernel takes comm from the
    # original binary's basename, so it is "game" for free; but exec'ing qemu
    # explicitly would make comm "qemu-arm-static" and the guest would vanish
    # from every count. So qemu is copied to a path whose OWN basename is
    # "game" (comm = basename of the exec'd file), and the real ELF is its
    # argument. Measured: without this the headless boot ran fine but pgrep -x
    # game found nothing.
    mkdir -p "$R/.padqemu"
    cp -f "$QEMU" "$R/.padqemu/game"
    cp -f /bin/busybox "$R/busybox"
    echo "[run] PAD_PIVOT: checkpointable boot (pivot_root, explicit qemu)"
fi

# setsid the guest so it leads its own session INSIDE the pid namespace. Without
# it criu refuses the dump: "A session leader of N(1) is outside of its pid
# namespace" - the ns init would otherwise belong to watch.sh's session, which
# is not in the checkpoint. Only under PAD_PIVOT (empty otherwise = byte-for-byte
# the old command, just a stray space); driven through one variable so the big
# INNER heredoc is not duplicated.
SETSID=""
[ -n "$PIVOT" ] && SETSID="setsid"
# THE USER NAMESPACE, and why a checkpointable ROOT run drops it (item 13).
# `-r` maps the caller to root inside a NEW user namespace, which is how an
# UNPRIVILEGED user (david, under watch.sh) gets the mount and chroot caps this
# script needs. But an unprivileged userns is one the kernel FORCES setgroups
# off in, and criu cannot restore the guest's supplementary groups into it -
# the save-state RESTORE dies "Can't setgroups: -22". Real root already holds
# CAP_SYS_ADMIN/CAP_SYS_CHROOT in the initial namespace, so under PAD_PIVOT as
# root the userns is not needed and is dropped: the guest then has NO userns,
# restore is the simple case, and the guest runs as root - which is also how
# the game runs on the real Spike machine. Non-root keeps `-r` (it has no other
# way to get the caps), and such a run is simply not checkpointable, which is
# fine because criu needs root anyway.
#
# ROOT DROPS IT WHETHER OR NOT THERE IS A PIVOT, and the `[ -n "$PIVOT" ]` that
# used to be on this line was an assumption rather than a rule: root runs only
# happened under PAD_PIVOT, so the two were the same condition. They stopped
# being the same when watch.sh learned to withdraw a pivot it cannot do (a WSL
# with no static busybox - see pad_static_busybox), which leaves a run that is
# root AND not pivoted, a combination this script had never taken.
#
# The condition that belongs here is the one the paragraph above argues for:
# `-r` exists to GET the caps, root already has them, so for root it is a
# namespace that buys nothing - and a namespace this rig has already been bitten
# by once (setgroups, above). A root run and a root run without a pivot should
# differ by the pivot and by nothing else.
USERNS="-r"
[ "$(id -u)" = 0 ] && USERNS=""
unshare $USERNS -m -p -f $SETSID bash -s "$R" "$NODEBUS_PTY" "$GAME" "$CARD_SRC" "$PIVOT" \
        "${PIVOTROOT:-}" <<'INNER'
R="$1"
NODEBUS_PTY="$2"
GAME="$3"
CARD_SRC="$4"
PIVOT="$5"
# The pivot_root command this machine actually has, resolved OUTSIDE by
# pad_pivot_root_cmd. Passed in rather than looked up here because the lookup
# belongs to the one function that defines it, and because a namespace is a bad
# place to discover a missing program.
PIVOTROOT="$6"
# pivot_root needs the new root to BE a mount, and everything mounted below then
# rides the pivot, so the self-bind of $R must come FIRST - before proc/sys/tmp.
# Guarded, so the chroot path is untouched.
[ -n "$PIVOT" ] && mount --bind "$R" "$R"
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

# ★ ITEM 45 - THIS TITLE'S PANEL IS BOLTED IN UPSIDE DOWN AND OUR MONITOR IS NOT.
#
# james_bond_60th_le ships an 8-byte /games/data/boot_display_cmd holding exactly
# `-invert`, and its whole picture comes out rotated 180 - measured straight off
# the screen FBO with glshot.sh, so it is the GUEST drawing it that way and not
# the window: win_present() can express only a Y flip, and a Y flip is a mirror,
# not a rotation. The text in a shot reads inverted but never mirrored.
#
# THE FILE IS THE SWITCH, NOT A TITLE LIST, and that is measured both ways:
# godzilla_pro and turtles_pro carry the IDENTICAL `/games/data/boot_display_cmd`
# + `-invert` string block in their own game ELFs, so the code path is generic -
# they simply ship no such file, and their picture is the right way up.
#
# The machine inverts because the LCD is mounted upside down in the cabinet. A
# desktop monitor is not, so the faithful thing on a PC is to let the guest draw
# the right way up. Masking the flag does that AT THE SOURCE, which keeps every
# downstream consumer correct - glshot.sh, the PAD_GL_DUMP frames, video capture,
# save-state thumbnails - where un-rotating in win_present() would fix the window
# alone AND need a rebuild, and a rebuild invalidates every existing save slot
# (item 36a (3)). PAD_DISPLAY_INVERT=1 keeps the machine's own behaviour.
#
# HOW IT IS MASKED, and the shape is deliberate: the guest is shown a data/
# directory with NO boot_display_cmd in it, rather than an empty one. That is
# the exact state the two control titles are in - godzilla_pro and turtles_pro
# ship a data/ holding only READMEs - so the guest lands in a configuration
# that is known to work on this rig rather than in a novel one. An empty file
# is a third state nobody has ever booted, and the first attempt here used one:
# the game read it, its threads returned, and it exited cleanly four frames in.
BDC="$R/games/data/boot_display_cmd"
if [ "${PAD_DISPLAY_INVERT:-0}" != "1" ] && [ -s "$BDC" ] && grep -qa -- '-invert' "$BDC"; then
    NOINV="$R/dump/data_noinvert"
    rm -rf "$NOINV"
    # cp -r, NOT cp -a: -a preserves ownership, the card's files are root's,
    # and a non-root run therefore fails the whole copy on a permission it does
    # not need. The guest only ever reads these.
    if cp -rL "$R/games/$GAME/data" "$NOINV" 2>/dev/null &&
       chmod -R u+rwX "$NOINV" 2>/dev/null &&
       rm -f "$NOINV/boot_display_cmd" &&
       mount --bind "$NOINV" "$R/games/$GAME/data"; then
        echo "[run] display: this title asks the panel for -invert (its LCD is"
        echo "[run]   mounted upside down); masked, so the picture comes up the"
        echo "[run]   right way up here. PAD_DISPLAY_INVERT=1 keeps the machine's."
    else
        echo "[run] display: could not mask $BDC - expect an upside-down picture" >&2
    fi
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
if [ -n "$PIVOT" ]; then
    # THE CHECKPOINTABLE EXEC (item 13). Three steps, each measured on the
    # criuladder.sh rungs:
    #  1. close the stray /dev/ptmx fds (3..63) every wsl.exe descendant
    #     inherits (7 and 10) - criu refuses any process holding them. stdio
    #     (0,1,2) is pointed inside the container in step 3.
    #  2. pivot so the guest's root IS the mount-namespace root (chroot's root is
    #     not, which is why chroot cannot be dumped), then drop the whole host
    #     tree with one lazy umount so it is not a checkpoint liability.
    #  3. exec qemu explicitly. LD_PRELOAD and the PAD_* the shim reads are
    #     inherited from watch.sh and propagated to the guest, same as binfmt.
    for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done
    mkdir -p oldroot
    # A PIVOT THAT FAILS COSTS THE FEATURE, NOT THE RUN. This line used to
    # `exit 1`, and everything above it - the namespace, every mount, the card -
    # was already built and correct: the ordinary chroot boot at the foot of
    # this script would have run perfectly from here. Losing it too is the fault
    # this rig has now been told about twice in two releases, and the second
    # time the missing program was one no gate could have named in advance. So
    # the answer to a pivot that will not happen is the boot we have always
    # done, said out loud. Save states are what it costs, and only for this run.
    if $PIVOTROOT . oldroot; then
        cd /
        /busybox umount -l /oldroot
        cd "/games/$GAME" || exit 1
        export LD_PRELOAD=${PAD_TRACE_SO:+$PAD_TRACE_SO:}/lib/hwshim.so PAD_AUDIO_OUT=/dump/audio.raw PAD_SEGV_REPORT=1
        # stdio has to point INSIDE the container. The caller's stdout is a file
        # on a host mount ($HOME/gzwatch.log for watch.sh), and that mount leaves
        # the namespace with the pivot - criu then refuses fd 1 ("Can't lookup
        # mount for fd=1"). Reopen all three onto the rootfs's own mounts AFTER
        # the pivot, so every fd belongs to a mount that stays. The host reads
        # the same bytes at $ROOT/dump/game.out, so nothing is lost - but a
        # PAD_PIVOT run's log is THERE, not on the caller's stdout, which
        # watch.sh must follow when it learns to launch pivot runs.
        # /.padqemu/game IS qemu (see the copy above) - named so comm stays
        # "game"; /games/$GAME/game is the real ELF it runs.
        exec /.padqemu/game ./game </dev/null >/dump/game.out 2>&1
    fi
    # Nothing was consumed by the attempt: the mounts are still the ones the
    # chroot below wants, the cwd is still the rootfs, and the empty oldroot
    # goes rather than being left inside it looking like part of the guest.
    rmdir oldroot 2>/dev/null
    echo "[run] pivot_root failed, so this run cannot be checkpointed:" >&2
    echo "[run]   save states are off. Starting the ordinary way -" >&2
    echo "[run]   nothing else about the run changes." >&2
fi
# LD_PRELOAD is applied to the game alone: the busybox tools in this rootfs do
# not link libdl and fail to start with the shim forced on them.
exec chroot "$R" /bin/sh -c \
  "cd /games/$GAME && LD_PRELOAD=${PAD_TRACE_SO:+$PAD_TRACE_SO:}/lib/hwshim.so PAD_AUDIO_OUT=/dump/audio.raw PAD_SEGV_REPORT=1 exec ./game"
INNER
