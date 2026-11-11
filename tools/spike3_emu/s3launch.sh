#!/bin/bash
# s3launch.sh - the Emulate tab's one door into the Spike 3 rig (PAD-1090).
#
#   s3launch.sh --check                     can this PC run a Spike 3 card?
#   s3launch.sh --setup                     install what --check found missing
#   s3launch.sh CARD.raw SLOT MINUTES [--audio] [--keyfile PADKEYS.json]
#                                           put the card in the store if it is
#                                           not there yet, then run it in a
#                                           window on rig slot SLOT
#   s3launch.sh --stop SLOT                 end that slot's run
#
# Runs as ROOT (the tab calls it through rig_cmd_root, `wsl -u root`):
# s3run.sh's overlay mounts and namespaces need it, and the store lives under
# /var/lib/pad-s3. Nothing here needs a special kernel or a patched qemu: a
# stock WSL and the user's OWN OTP key: --keyfile (the padkeys.json the
# Extract tab's Spike 3 unlock saved), else padkeys.json beside the card. The
# key is used once per card, to decrypt it into the store; never stored here.
#
# Every line the tab acts on starts with a fixed token:
#   s3check: ok | s3check: missing - <what>  (+ s3setup: <the fix>)
#   s3launch: <step>                        progress, for the tab's log
#   s3launch: failed - <why>                the run did not start
# s3run.sh's own [s3run] lines follow once the game starts.
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
H=${PAD_S3_HOME:-/var/lib/pad-s3}
B=${PAD_S3_BUILD:-$H/build}
KMOD=${PAD_S3_KMOD:-$H}

# What a stock PC needs, by the package that brings it (Ubuntu/Debian names -
# the WSL distro PAD installs, and the Linux desktops it supports). The rig's
# own binaries are not a requirement here: they are BUILT, once, after the
# first card is in the store (they link against the card's own libc).
PKG_FOR=(
    "python3:python3" "ffmpeg:ffmpeg"
    "unshare:util-linux" "script:bsdutils" "gcc:gcc" "curl:curl" "xz:xz-utils"
    "aarch64-linux-gnu-as:binutils-aarch64-linux-gnu" "apt-get:apt"
)
# cryptography: the card store decrypts in user space when the kernel has no
# dm-crypt (s3store.py UserPartition) - so dm-crypt/cryptsetup are a speed-up
# where present, never a requirement
PYMOD_FOR=("numpy:python3-numpy" "PIL:python3-pil" "cryptography:python3-cryptography")

missing_pkgs() {
    local pk=() kv t m
    for kv in "${PKG_FOR[@]}"; do
        t=${kv%%:*}; command -v "$t" >/dev/null || pk+=("${kv#*:}")
    done
    for kv in "${PYMOD_FOR[@]}"; do
        m=${kv%%:*}; python3 -c "import $m" 2>/dev/null || pk+=("${kv#*:}")
    done
    # the game is aarch64: binfmt runs it through qemu-user, and inside a
    # chroot only a FIXED (F) registration can still find the interpreter
    grep -qs '^flags:.*F' /proc/sys/fs/binfmt_misc/qemu-aarch64 || pk+=(qemu-user-static binfmt-support)
    [ ${#pk[@]} -gt 0 ] && echo "${pk[*]}"
}

check() {
    local miss=() pk
    [ "$(id -u)" = 0 ] || miss+=("root (run through wsl -u root)")
    pk=$(missing_pkgs)
    [ -n "$pk" ] && miss+=("packages: $pk")
    if [ ${#miss[@]} -eq 0 ]; then
        echo "s3check: ok"
        return 0
    fi
    local IFS=';'
    echo "s3check: missing - ${miss[*]}"
    [ -n "$pk" ] && echo "s3setup: apt-get install $pk"
    return 1
}

setup() {
    local pk
    pk=$(missing_pkgs)
    if [ -n "$pk" ]; then
        echo "s3launch: installing $pk"
        DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 update -qq && \
        DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y -qq $pk 2>&1 | tail -3 | sed 's/^/s3launch:   /'
    fi
    # binfmt-support registers qemu-aarch64 without F on some releases
    if ! grep -qs '^flags:.*F' /proc/sys/fs/binfmt_misc/qemu-aarch64 && [ -x /usr/bin/qemu-aarch64-static ]; then
        [ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && echo -1 > /proc/sys/fs/binfmt_misc/qemu-aarch64
        echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:POCF' \
            > /proc/sys/fs/binfmt_misc/register 2>/dev/null && echo "s3launch: registered qemu-aarch64 (binfmt, F)"
    fi
    modprobe dm_crypt 2>/dev/null
    check
}

build_ok() {
    local f
    for f in libGLESv2.so.2 libEGL.so.1 s3kms.so s3alsa.so s3dev.so s3vid.so padglhost; do
        [ -e "$B/$f" ] || return 1
    done
    # built from these sources? (s3build.sh --sum: an app update that changed
    # glbridge.c or a rig source rebuilds once, instead of running the old one)
    [ "$(cat "$B/.srcsum" 2>/dev/null)" = "$(bash "$S/s3build.sh" --sum)" ]
}

case "${1:-}" in
    --check)
        check
        exit $?
        ;;
    --setup)
        setup
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
        sed -n 2,20p "$0"
        exit 2
        ;;
esac

CARD=$1; SLOT=${2:?usage: s3launch.sh CARD.raw SLOT MINUTES [--audio] [--keyfile F]}; MIN=${3:-30}
shift 3 2>/dev/null || shift $#
AUDIO=0
while [ $# -gt 0 ]; do
    case "$1" in
        --audio) AUDIO=1 ;;
        --keyfile) export PAD_SPIKE3_KEYFILE=${2:-}; shift ;;
    esac
    shift
done
NOKEY="the card could not be decrypted: unlock it once with YOUR card's OTP key (Extract tab, Spike 3 unlock), or put padkeys.json beside the card image"
check >/dev/null || { echo "s3launch: failed - $(check | sed 's/^s3check: //')"; exit 1; }
[ -f "$CARD" ] || { echo "s3launch: failed - no such card image: $CARD"; exit 1; }
if ! python3 "$S/s3store.py" path "$CARD" >/dev/null 2>&1; then
    echo "s3launch: decrypting the card into the Spike 3 store (once per card; a few minutes)"
    if ! python3 "$S/s3store.py" build "$CARD" 2>&1 | sed 's/^/s3launch:   /'; then
        echo "s3launch: failed - $NOKEY"
        exit 1
    fi
    python3 "$S/s3store.py" path "$CARD" >/dev/null 2>&1 || {
        echo "s3launch: failed - $NOKEY"; exit 1; }
fi
if ! build_ok; then
    echo "s3launch: building the Spike 3 rig (once per app update; a few minutes)"
    if ! bash "$S/s3build.sh" "$B" 2>&1 | sed 's/^/s3launch:   /'; then
        echo "s3launch: failed - the Spike 3 rig did not build"; exit 1
    fi
    build_ok || { echo "s3launch: failed - the Spike 3 rig did not build"; exit 1; }
fi
echo "s3launch: starting slot $SLOT for $MIN min$( [ $AUDIO = 1 ] && echo ', with sound')"
PAD_S3_AUDIO=$AUDIO exec bash "$S/s3run.sh" "$CARD" --slot "$SLOT" --secs $((MIN * 60)) --window
