#!/bin/bash
# s3launch.sh - the Emulate tab's one door into the Spike 3 rig (PAD-1090).
#
#   s3launch.sh --check                     can this PC run a Spike 3 card?
#   s3launch.sh CARD.raw SLOT MINUTES [--audio]
#                                           put the card in the store if it is
#                                           not there yet, then run it in a
#                                           window on rig slot SLOT
#   s3launch.sh --stop SLOT                 end that slot's run
#
# Runs as ROOT (the tab calls it through rig_cmd_root, `wsl -u root`): the
# store's dm-crypt opens and s3run.sh's overlay mounts need it.
#
# Every line the tab acts on starts with a fixed token:
#   s3check: ok | s3check: missing - <what>
#   s3launch: <step>                        progress, for the tab's log
#   s3launch: failed - <why>                the run did not start
# s3run.sh's own [s3run] lines follow once the game starts.
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
B=${PAD_S3_BUILD:-/home/david/.pad-s3/build}
KMOD=${PAD_S3_KMOD:-/home/david/.pad-s3}
QEMU=${PAD_S3_QEMU:-$(dirname "$B")/qemu-aarch64}

check() {
    local miss=()
    [ "$(id -u)" = 0 ] || miss+=("root (run through wsl -u root)")
    for f in libGLESv2.so.2 libEGL.so.1 s3kms.so s3alsa.so s3vid.so s3spid padglhost; do
        [ -e "$B/$f" ] || { miss+=("the rig build ($B/$f: bash s3build.sh)"); break; }
    done
    [ -x "$QEMU" ] || miss+=("the patched qemu-aarch64 ($QEMU)")
    if [ ! -e /dev/cuse ] && [ ! -e "$KMOD/kernel/WSL2-Linux-Kernel-linux-msft-wsl-6.6.87.2/fs/fuse/cuse.ko" ]; then
        miss+=("CUSE (/dev/cuse, or cuse.ko built for this WSL kernel)")
    fi
    if ! grep -qs "SMBus stub driver" /sys/bus/i2c/devices/i2c-*/name /sys/class/i2c-adapter/i2c-*/name && \
       [ ! -e "$KMOD/i2cstub/i2c-stub.ko" ]; then
        miss+=("the amp bus (i2c-stub, or i2c-stub.ko built for this WSL kernel)")
    fi
    for t in python3 ffmpeg cryptsetup losetup; do
        command -v "$t" >/dev/null || miss+=("$t")
    done
    if [ ${#miss[@]} -eq 0 ]; then
        echo "s3check: ok"
        return 0
    fi
    local IFS=';'
    echo "s3check: missing - ${miss[*]}"
    return 1
}

case "${1:-}" in
    --check)
        check
        exit $?
        ;;
    --stop)
        SLOT=${2:?usage: s3launch.sh --stop SLOT}
        # s3run.sh kills its own namespace and helpers on TERM
        if pkill -TERM -f "s3run.sh .* --slot $SLOT( |\$)"; then
            for i in $(seq 1 50); do pgrep -f "s3run.sh .* --slot $SLOT( |\$)" >/dev/null || break; sleep 0.2; done
            echo "s3launch: stopped slot $SLOT"
        else
            echo "s3launch: slot $SLOT was not running"
        fi
        exit 0
        ;;
    ""|-*)
        sed -n 2,19p "$0"
        exit 2
        ;;
esac

CARD=$1; SLOT=${2:?usage: s3launch.sh CARD.raw SLOT MINUTES [--audio]}; MIN=${3:-30}
AUDIO=0; [ "${4:-}" = --audio ] && AUDIO=1
check >/dev/null || { echo "s3launch: failed - $(check | sed 's/^s3check: //')"; exit 1; }
[ -f "$CARD" ] || { echo "s3launch: failed - no such card image: $CARD"; exit 1; }
if ! python3 "$S/s3store.py" path "$CARD" >/dev/null 2>&1; then
    echo "s3launch: decrypting the card into the Spike 3 store (once per card; a few minutes)"
    if ! python3 "$S/s3store.py" build "$CARD" 2>&1 | sed 's/^/s3launch:   /'; then
        echo "s3launch: failed - the card could not be decrypted (is its padkeys.json beside it?)"
        exit 1
    fi
    python3 "$S/s3store.py" path "$CARD" >/dev/null 2>&1 || {
        echo "s3launch: failed - the card could not be decrypted (is its padkeys.json beside it?)"; exit 1; }
fi
echo "s3launch: starting slot $SLOT for $MIN min$( [ $AUDIO = 1 ] && echo ', with sound')"
PAD_S3_AUDIO=$AUDIO exec bash "$S/s3run.sh" "$CARD" --slot "$SLOT" --secs $((MIN * 60)) --window
