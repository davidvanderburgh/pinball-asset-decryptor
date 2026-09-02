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
    # ★ ITEM 90 - THE BOOT SELECTOR (PAD_SELECT=1), for a card that carries
    # more than one games partition (mkmulticard.py: the stock p3 plus each
    # extra image's games partition appended as p7, p8...). The machine boots
    # into a menu drawn by /usr/local/codeselect/codeselect before the game;
    # the emulator runs the SAME program, chroot'd into this rootfs, in the
    # INNER namespace below, and binds the partition it chose over
    # games/$GAME before the game execs. Everything it needs is prepared
    # here, outside the namespace, where cardmount.sh and parts.py live:
    #
    #   * every games partition mounted (the primary is the mount above; the
    #     others go to $CARDS/<label>.pN through cardmount.sh --part), and
    #     the token -> directory list handed into INNER as one argument;
    #   * /dump/codeselect.conf in the selector's own images.conf format,
    #     with device tokens p<N> (an opaque string to the selector - on the
    #     machine it is /dev/mmcblk0pN) and the menu text taken from the
    #     card's own /usr/local/codeselect/images.conf when the card was
    #     built with one, so the emulator shows the menu the machine shows;
    #   * the card's media (art, animations, sounds - item 90 v2) copied out
    #     of its rootfs into $R/dump/media, so the menu here looks and sounds
    #     like the machine's.
    #
    # N IMAGES, TWO LAYOUTS (mkmulticard.py --layout): `parts` puts one extra
    # image's games partition on p7 verbatim; `multi` makes p7 ONE ext4 holding
    # img1/, img2/ ... - each a complete games tree - because the card's kernel
    # exposes p1..p7 only. parts.py --list-games prints a fifth field for a
    # tree inside such a partition (`7 <lba> <off> turtles_pro img1`), the
    # device token is then `p7:img1` (the machine's is /dev/mmcblk0p7:img1),
    # and the directory bound over games/$GAME is <p7 mount>/img1/<title>.
    # cardmount.sh mounts p7 once and answers "$MNT/img1" for it (its last
    # line must stay one component under the mount for watch.sh's teardown).
    #
    # PAD_GAME stays the PRIMARY's title: the node identity, the census and
    # the derived tables were all taken from it before this script ran, and
    # a card whose images share one title directory (the TMNT pair) is the
    # only kind this design is for. A refusal, not a silent fallback, when
    # the selector is not built: a run that asked for a menu and got the
    # primary without a word is the fault every gate in this rig exists for.
    #
    # PAD_SELECT=1 IS THE ANSWER HERE, NOT THE QUESTION (2026-09-02). Whether
    # a menu is wanted is decided ONCE, by watch.sh, from the card itself
    # (pad_select_wanted -> parts.py --multiboot, the one definition of a
    # multi-boot card) and handed down as a plain 1 or 0 in this script's
    # environment - so a run that mounted the extra partitions cannot then
    # decide against a menu, and a run that did not cannot decide for one.
    # `= 1` rather than `-n` for exactly that reason: 0 is a real answer now
    # and it means no. Started by hand instead of through watch.sh
    # (runbridge.sh, runlim.sh, savetest*.sh), an unset PAD_SELECT still means
    # no menu - the behaviour those measurement scripts have always had, and
    # they have no selector built to run one with.
    SEL_DIRS=""
    if [ "${PAD_SELECT:-}" = 1 ]; then
        # Every refusal below leaves through `rmdir "$R/games/$GAME"`: the
        # stub the mkdir above made is the bind mountpoint, and the EXIT
        # trap that removes it is not installed until further down - so an
        # early exit used to leave an empty games/<title> behind, which the
        # Emulate tab then offered as an extracted title (see the trap).
        if [ ! -x "$PAD_SELECT_BIN" ]; then
            echo "[run] PAD_SELECT is set but the boot selector is not built:" >&2
            echo "[run]   $PAD_SELECT_BIN is missing" >&2
            echo "[run]   (buildselect.sh builds it; watch.sh does that itself)" >&2
            rmdir "$R/games/$GAME" 2>/dev/null
            exit 1
        fi
        SEL_LIST=$(python3 "$S/parts.py" --list-games "$PAD_CARD" 2>/dev/null)
        [ -n "$SEL_LIST" ] || { echo "[run] PAD_SELECT: no games partition found on $PAD_CARD" >&2; rmdir "$R/games/$GAME" 2>/dev/null; exit 1; }
        SEL_CARDCONF=$(python3 "$S/parts.py" --rootfs-file /usr/local/codeselect/images.conf "$PAD_CARD" 2>/dev/null)
        SEL_N=0; SEL_PRIMARY=""; SEL_IMAGES=""
        while read -r idx _lba _off titles subdir; do
            [ -n "$idx" ] || continue
            tok="p$idx"; [ -n "$subdir" ] && tok="p$idx:$subdir"
            if [ -z "$SEL_PRIMARY" ]; then
                # The first games partition IS the mount above (cardmount's
                # default is exactly `--games`, the first one): reuse it
                # rather than mounting p3 a second time under another name.
                SEL_PRIMARY=$idx; d=$CARD_SRC
            else
                m=$(bash "$S/cardmount.sh" "$PAD_CARD" --part "$idx" | tail -1)
                [ -d "$m" ] || { echo "[run] could not mount partition $idx of $PAD_CARD" >&2; rmdir "$R/games/$GAME" 2>/dev/null; exit 1; }
                if [ -n "$subdir" ]; then
                    # a multi-layout tree: cardmount answered <mount>/imgN for
                    # the FIRST tree; this entry's title dir is one level down
                    # its OWN subdirectory
                    d="$(dirname "$m")/$subdir/${titles%%,*}"
                    [ -d "$d" ] || { echo "[run] partition $idx of $PAD_CARD holds no $subdir/${titles%%,*}" >&2; rmdir "$R/games/$GAME" 2>/dev/null; exit 1; }
                else
                    d=$m
                fi
            fi
            # 'image=/dev/mmcblk0pN[:sub]|<title>|<subtitle>[|art|anim|music]'
            # on the card -> the same fields here (everything after the
            # device is forwarded verbatim, so the media names ride along);
            # else name it after the partition.
            t=$(printf '%s\n' "$SEL_CARDCONF" | sed -n "s#^image=/dev/mmcblk0$tok|##p" | head -1 | tr -d '\r')
            case "$t" in
                "")    t="$tok ${titles%%,*}|games partition $idx${subdir:+ $subdir}" ;;
                *"|"*) ;;
                *)     t="$t|" ;;
            esac
            SEL_IMAGES="${SEL_IMAGES}image=$tok|$t"$'\n'
            SEL_DIRS="${SEL_DIRS}$tok"$'\t'"$d"$'\n'
            echo "[select] menu: $SEL_N = $tok ${t%%|*} ($d)"
            SEL_N=$((SEL_N + 1))
        done <<< "$SEL_LIST"
        # The card's own default highlight, when it has one and it is in
        # range; /data/codeselect.last (the selector's own memory, and
        # $R/data persists across runs here) wins over it inside codeselect.
        SEL_DEFAULT=$(printf '%s\n' "$SEL_CARDCONF" | sed -n 's/^default=\([0-9][0-9]*\).*/\1/p' | head -1)
        [ -n "$SEL_DEFAULT" ] && [ "$SEL_DEFAULT" -lt "$SEL_N" ] || SEL_DEFAULT=0
        {
            echo "# written by run_game.sh for the boot selector (item 90)"
            echo "# device tokens are p<N>[:imgK] = partition N [tree imgK] of $PAD_CARD"
            printf '%s' "$SEL_IMAGES"
            echo "default=$SEL_DEFAULT"
            echo "timeout=${PAD_SELECT_TIMEOUT:-30}"
            # the card's sound and volume keys, verbatim (media= is NOT
            # copied: the media directory is handed over with --media below)
            printf '%s\n' "$SEL_CARDCONF" | tr -d '\r' | grep -E '^(sound_move|sound_confirm|volume|mixer_volume)=' || true
        } > "$R/dump/codeselect.conf"
        echo "[select] menu: $SEL_N images; default $SEL_DEFAULT; auto-boot after ${PAD_SELECT_TIMEOUT:-30} s"
        # THE MEDIA (item 90 v2): the card's /usr/local/codeselect/media,
        # pulled out of its rootfs with debugfs (parts.py --rootfs-dir, no
        # mount, no root) into $R/dump/media - /dump is self-bound below, so
        # the selector sees it as /dump/media. PAD_SELECT_MEDIA=<host dir>
        # takes a directory of David's own instead, so art and sounds can be
        # tried without rebuilding a card. Cleared first: a previous run's
        # (possibly root-owned, PAD_PIVOT) copy must not masquerade as this
        # card's, and a root run hands the fresh copy back to the rig's user.
        rm -rf "$R/dump/media" 2>/dev/null \
            || echo "[select] WARNING: cannot clear a stale $R/dump/media (another user's?)" >&2
        if [ -n "${PAD_SELECT_MEDIA:-}" ]; then
            if [ -d "$PAD_SELECT_MEDIA" ] && cp -r "$PAD_SELECT_MEDIA" "$R/dump/media"; then
                echo "[select] media: $(ls "$R/dump/media" | wc -l) files from PAD_SELECT_MEDIA=$PAD_SELECT_MEDIA"
            else
                echo "[select] media: PAD_SELECT_MEDIA=$PAD_SELECT_MEDIA is not a readable directory - none" >&2
            fi
        else
            python3 "$S/parts.py" --rootfs-dir /usr/local/codeselect/media "$R/dump" "$PAD_CARD" >/dev/null 2>&1
            if [ -d "$R/dump/media" ]; then
                echo "[select] media: $(ls "$R/dump/media" | wc -l) files from the card's /usr/local/codeselect/media"
            else
                echo "[select] media: none on the card"
            fi
        fi
        if [ "$(id -u)" = 0 ] && [ -d "$R/dump/media" ]; then
            _o=$(stat -c %U "$PAD_HOME" 2>/dev/null)
            [ -n "$_o" ] && [ "$_o" != root ] && chown -R "$_o" "$R/dump/media" 2>/dev/null
        fi
    fi
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

# THE SHIM NEEDS THE TITLE BY NAME, not just the directory it is told to run
# from, and until 2026-08-23 a CARD run never gave it one.
#
# nb_fident_load() builds `/dump/tables/$PAD_GAME/node_ident.txt` and RETURNS
# EARLY when PAD_GAME is unset, leaving every board to be answered from the
# built-in nb_idents[] - which is godzilla's node set, measured once. chroot
# inherits this environment, so exporting it here is the whole fix.
#
# What it cost: the built-in table claims part 0x2c40102b / variant 0x05 for
# every board on that part, because on godzilla they are all ws2812node.
# turtles' node 12 is a coil4node whose real variant is 0x04, so it graded
# status 7 = Checksum on every card boot and the game answered with the
# "UPDATING NODE BOARD RUNTIME / UPDATE FAILED" banner (item 55). Nodes 2 and
# 14 ARE ws2812node, which is why they graded clean and only one board looked
# broken. This affects every card run of every title, not just turtles - a card
# run is exactly the case where no title name was ever in the environment.
#
# PAD_GAME is also what the derived-table path uses everywhere else, so setting
# it here makes a card run agree with an extracted one instead of quietly
# taking a different code path.
export PAD_GAME="$GAME"

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
        "${PIVOTROOT:-}" "${SEL_DIRS:-}" <<'INNER'
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
# The boot selector's menu (item 90): one line per image, in menu order,
# `<partition idx><TAB><mounted title directory>`. Empty on every run that
# did not ask for the selector, and then nothing below reads it.
SEL_DIRS="$7"
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
# THIS ATTRIBUTE IS IN CENTI-HERTZ, AND "60" HERE IS WHY stranger_things SAT ON
# "THIS MACHINE WILL NOT OPERATE IN THIS COUNTRY" FOREVER (item 52).
# The game's power-monitor thread (0x4f20b0) computes
#     measured_hz = roundf(strtol(line) / 100.0f)
# and publishes it. The factory frequency check (0x23996c) passes only if that
# lands in 57..63 - or, failing that, if the EEPROM factory config says 50 Hz,
# and that block (52 bytes at EEPROM offset 0) is ALL ZEROS on this rig, so it
# fails both of its checksums and reports nothing. With "60" the game measured
# 60/100 = 1 Hz, missed 57..63, set FG_FACTORY_FREQUENCY_MISMATCH (flag 3) and
# ran screen 8 - whose text is about the COUNTRY, which is what sent four
# passes hunting a country setting that was correct the whole time (the EEPROM
# says U.S.A. at offset 0x140 and its checksum is valid). 6000 = 60.00 Hz.
echo 6000 > "$R/sys/bus/iio/devices/iio:device0/in_power_frequency"
# ...AND in_power_input IS A FAULT FLAG, NOT A VOLTAGE. The same thread does
#     power_fail = (strtol(in_power_input) != 0)          (0x4f28c8/0x4f28d8)
# and power_sample_get (0x4f205c) reports frequency ZERO whenever that flag is
# set - so the old "120" made the game measure a perfect 60.00 Hz and then
# throw it away. Both values were needed; each alone still refuses. MEASURED
# with PAD_PEEK on the guest's own state, not inferred: with 6000/120 the
# platform block at 0x842cc4+0x274 held float 60.0 while +0x270 held 1, and the
# accumulator at 0x7bff8c never took a single sample. 0 = mains present, no
# fault, which is what an emulated cabinet on a bench should report.
echo 0    > "$R/sys/bus/iio/devices/iio:device0/in_power_input"
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

# ★ ITEM 90 - THE BOOT SELECTOR RUNS HERE, and exactly here, on a PAD_SELECT
# run: after every mount the game will see (so it draws through the same
# /dump/padgl ring and reads the same /dump/padsw keyboard file the game
# will), and BEFORE `cd "$R"` and the pivot branch - so the PAD_PIVOT path
# (the app's default, root) and the plain chroot path run it identically and
# the two exec lines at the foot of this script stay byte for byte what they
# were. It is an ordinary chroot under binfmt: comm is `codeselect`, which is
# how alive.sh counts it and how watch.sh tells "the menu is up" from "the
# game is up" (both paths give the GAME comm=game).
#
# NO LD_PRELOAD, deliberately. hwshim.so serves the cabinet word out of the
# GAME'S OWN heap switch table, found by a by-shape scan, dereferences
# PAD_NB_OBJS as a game address and hooks the device nodes - none of which is
# a menu program's process shape. The selector reads the keyboard through
# the rig's own channel instead (`--input padsw`: PAD_SW_SHM, mapped to the
# title's switch ids through /dump/tables/$PAD_GAME/switch_list.txt), which
# is what padglhost writes the keys into; the node-bus backend it uses on the
# machine has nothing to talk to in here without the shim.
#
# </dev/null IS LOAD-BEARING: this whole script is bash reading ITS OWN TEXT
# from stdin (`bash -s <<'INNER'`), and a child that reads stdin eats the
# rest of the script. The pivot exec below redirects for the same reason.
#
# THE CHOICE is an index into the menu, written to $PAD_SELECT_CHOICE (one
# line) only on a confirmed or timed-out choice; exit 2 and no file mean no
# choice, and both fall back to the primary OUT LOUD. A non-primary choice
# is a second bind stacked over the card bind at games/$GAME: same
# mountpoint, the chosen image's files win, nothing is unmounted. Then the
# -invert masking below reads the CHOSEN build's boot_display_cmd.
#
# --media /dump/media is the card's media directory (or PAD_SELECT_MEDIA's),
# staged by the outer script; a missing directory or a broken file in it is
# NON-FATAL inside the selector (the menu still draws, the card still boots).
# Audio needs nothing here: PAD_AUDIO_PLAY / PAD_AUDIO_FMT are inherited from
# watch.sh (empty on a PAD_AUDIO=0 run = silent), and the selector writes the
# format file and streams into the FIFO itself, then closes it before exit.
#
# --no-invert, BECAUSE THE MASKING RUNS AFTER THE MENU. The selector's default
# is boot_display's own rule - rotate 180 when /games/data/boot_display_cmd
# says -invert - and on the machine that is right. Here the ITEM 45 block
# below masks that file for the GAME, but only after the selector has run, so
# a title that ships -invert (james_bond_60th_le) drew its menu upside down
# while its game came up the right way round. PAD_DISPLAY_INVERT=1 keeps the
# machine's behaviour for the game, so then the selector is left to auto-detect
# and the two agree either way.
if [ -n "$SEL_DIRS" ]; then
    rm -f "$R/dump/vidroot"
    rm -f "$R$PAD_SELECT_CHOICE"
    SEL_INV="--no-invert"
    [ "${PAD_DISPLAY_INVERT:-0}" = "1" ] && SEL_INV=""
    echo "[select] menu up: LEFT/RIGHT flipper (arrows) move, START (1) confirms; auto-boot in ${PAD_SELECT_TIMEOUT:-30} s"
    chroot "$R" /usr/local/codeselect/codeselect --conf /dump/codeselect.conf --out "$PAD_SELECT_CHOICE" --input padsw --timeout "${PAD_SELECT_TIMEOUT:-30}" --log /dump/codeselect.log --media /dump/media $SEL_INV </dev/null
    SEL_RC=$?
    SEL_CHOICE=$(head -1 "$R$PAD_SELECT_CHOICE" 2>/dev/null | tr -dc '0-9')
    SEL_DIR=""; SEL_IDX=""; SEL_PRIMARY_DIR=""; n=0
    while IFS=$'\t' read -r idx d; do
        [ -n "$idx" ] || continue
        [ "$n" = 0 ] && SEL_PRIMARY_DIR=$d
        [ "$n" = "$SEL_CHOICE" ] && { SEL_IDX=$idx; SEL_DIR=$d; }
        n=$((n + 1))
    done <<< "$SEL_DIRS"
    if [ "$SEL_RC" != 0 ] || [ -z "$SEL_DIR" ]; then
        echo "[select] fallback: primary (selector exit $SEL_RC, choice '${SEL_CHOICE:-none}')"
    elif [ "$SEL_DIR" = "$SEL_PRIMARY_DIR" ]; then
        echo "[select] chose $SEL_CHOICE $SEL_IDX $(basename "$SEL_DIR") - the primary, already in place"
    elif mount --bind "$SEL_DIR" "$R/games/$GAME"; then
        echo "[select] chose $SEL_CHOICE $SEL_IDX $(basename "$SEL_DIR") - bound over /games/$GAME"
        # The video host runs OUTSIDE this namespace and resolves the game's
        # relative clip paths against PAD_VID_ROOT = the primary's directory;
        # it cannot see this bind. dump/vidroot tells it where the chosen
        # image really is (padvidhost.host_root reads it per clip). Removed
        # again by every plain run and by the fallback paths above.
        printf '%s
' "$SEL_DIR" > "$R/dump/vidroot"
        [ "$(basename "$SEL_DIR")" = "$GAME" ] || \
            echo "[select] NOTE: that image's title directory is $(basename "$SEL_DIR"); it runs as /games/$GAME with the primary's tables"
    else
        echo "[select] fallback: primary (could not bind $SEL_DIR over /games/$GAME)" >&2
    fi
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
#
# AFTER THE SELECTOR (item 90), so it masks the file of the image that was
# CHOSEN; it used to sit above the device binds, and only the order moved.
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
