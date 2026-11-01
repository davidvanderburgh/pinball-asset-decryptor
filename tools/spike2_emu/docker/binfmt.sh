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

# A fresh container's /proc has the table unmounted; privileged, it may mount it.
if [ ! -e "$D/status" ]; then
    mount -t binfmt_misc binfmt_misc "$D" 2>/dev/null
    [ -e "$D/status" ] || { echo "binfmt: cannot see the handler table"; exit 2; }
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

[ -f "$CONF" ] || { echo "binfmt: no $CONF in this image"; exit 1; }
if cat "$CONF" > "$D/register" 2>/dev/null; then
    echo "binfmt: registered"; exit 0
fi
echo "binfmt: registering failed"; exit 1
