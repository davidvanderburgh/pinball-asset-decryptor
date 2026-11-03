#!/bin/bash
# binfmt.sh - make the container engine's Linux run 32-bit ARM programs.
#
# Run by padbox.sh before every run, in a throwaway PRIVILEGED box of the
# emulator image:
#
#   docker run --rm --privileged --entrypoint /bin/bash IMAGE /pad/rig/docker/binfmt.sh
#
# WHY (PAD-884). The game is a 32-bit ARM program and runs through the
# kernel's binfmt handler for it (qemu). The handler table belongs to the
# engine's Linux VM, not to any one container, and what is in it is the
# engine's choice: Docker Desktop registers ARM, colima registers only 386 and
# amd64 ("installing: 386 OK / amd64 OK" in its start log). An Apple-silicon
# CPU cannot run 32-bit ARM itself, so on colima the box came up and the guest
# died at its first program: "chroot: failed to run command '/bin/sh': Exec
# format error".
#
# THE IMAGE ALREADY CARRIES THE HANDLER: qemu-user-static, whose
# /usr/lib/binfmt.d/qemu-arm.conf is the very line WSL runs the game with. It
# is registered with the F flag, so the kernel opens the interpreter NOW and
# keeps it - it goes on working after this box is gone, and inside every other
# container and chroot, with no qemu inside them. This is how colima's own
# 386/amd64 handlers got there (a privileged box, tonistiigi/binfmt). It lasts
# until the engine's VM restarts, which is why it is asked on every run.
#
# Never replaces a handler that is there: Docker Desktop's, or anyone's.
# PAD_BINFMT_DIR / PAD_BINFMT_CONF let the tests point it at fakes.
set -u

D=${PAD_BINFMT_DIR:-/proc/sys/fs/binfmt_misc}
CONF=${PAD_BINFMT_CONF:-/usr/lib/binfmt.d/qemu-arm.conf}

# Does a 32-bit ARM program run here? ensurebuild.sh's 96-byte exit(0), read
# out of the rig rather than copied, so there is one of it.
arm_runs() {
    local b t rc=1
    b=$(sed -n 's/^PAD_ARM_EXIT0_B64=//p' "${PAD_RIG:-/pad/rig}/ensurebuild.sh" 2>/dev/null)
    [ -n "$b" ] || return 1
    t=$(mktemp 2>/dev/null) || return 1
    printf '%s' "$b" | base64 -d > "$t" 2>/dev/null && chmod +x "$t" &&
        "$t" >/dev/null 2>&1 && rc=0
    rm -f "$t"
    return $rc
}

# A fresh container's /proc has the table unmounted; privileged ROOT may mount
# it. Root, not just privileged: the image ends USER pad, and v1.316 ran this
# as pad - the mount failed and colima stayed without ARM (PAD-884, third log).
# padbox.sh passes -u 0; this says so plainly if that is ever lost.
if [ ! -e "$D/status" ]; then
    mount -t binfmt_misc binfmt_misc "$D" 2>/dev/null
    if [ ! -e "$D/status" ]; then
        # Nothing to read, but an engine whose handler is there runs ARM all
        # the same (F flag): ask it the way ensurebuild.sh does, by running one.
        if arm_runs; then
            echo "binfmt: present (32-bit ARM runs)"; exit 0
        fi
        if [ "$(id -u)" != 0 ]; then
            echo "binfmt: cannot mount the handler table as uid $(id -u) (needs root)"
        else
            echo "binfmt: cannot see the handler table"
        fi
        exit 2
    fi
fi

# Already there? Matched on the ELF magic (e_machine 0x28 = ARM, 32-bit,
# little-endian), not the name, as ensurebuild.sh's _pad_binfmt_arm does.
for f in "$D"/*; do
    case "${f##*/}" in register|status|*aarch64*|*armeb*) continue ;; esac
    [ -f "$f" ] || continue
    grep -qi '^magic .*02002800$' "$f" 2>/dev/null || continue
    if [ "$(head -1 "$f")" = enabled ]; then
        echo "binfmt: present (${f##*/})"; exit 0
    fi
    echo 1 > "$f" 2>/dev/null && { echo "binfmt: enabled (${f##*/})"; exit 0; }
    echo "binfmt: ${f##*/} is disabled and could not be enabled"; exit 1
done

# THE LINE ITSELF, when the image has no file of it - which is EVERY Mac's
# image (PAD-884, fourth log): qemu-user-static for arm64 leaves qemu-arm.conf
# out, because Debian assumes a 64-bit ARM CPU runs 32-bit ARM natively. Apple
# silicon cannot. The package still ships the interpreter it names (a symlink
# to the static qemu, so with F nothing has to exist inside the guest), and a
# copy of the line under /usr/share/doc - which Ubuntu's container images
# strip. So: the file, the doc copy, then this, byte for byte the amd64
# package's line (the one WSL runs every game with).
LINE=':qemu-arm:M::\x7f\x45\x4c\x46\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/libexec/qemu-binfmt/arm-binfmt-P:OPF'
INTERP=${PAD_BINFMT_INTERP:-/usr/libexec/qemu-binfmt/arm-binfmt-P}
if [ ! -f "$CONF" ] && [ -f /usr/share/doc/qemu-user-static/qemu-arm.conf ] &&
   [ -z "${PAD_BINFMT_CONF:-}" ]; then
    CONF=/usr/share/doc/qemu-user-static/qemu-arm.conf
fi
if [ -f "$CONF" ]; then
    cat "$CONF" > "$D/register" 2>/dev/null && { echo "binfmt: registered"; exit 0; }
elif [ -x "$INTERP" ]; then
    printf '%s\n' "$LINE" > "$D/register" 2>/dev/null &&
        { echo "binfmt: registered (built-in line)"; exit 0; }
else
    echo "binfmt: no qemu-arm in this image ($CONF, $INTERP)"; exit 1
fi
echo "binfmt: registering failed"; exit 1
