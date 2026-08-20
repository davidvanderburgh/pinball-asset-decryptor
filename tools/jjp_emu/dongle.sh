#!/bin/bash
# Make the purple Sentinel HL key usable by a game running in the jail.
#
# WHY THIS SCRIPT EXISTS.  The JJP game binary is wrapped by Sentinel LDK
# Envelope: 7,086 of its 8,566 functions are CIPHERTEXT at rest, each fronted by
# a 5-byte `call` into a decrypt-and-tail-jump trampoline.  The dongle does not
# answer a yes/no question - it supplies the AES key that decrypts the code.
# That is why there is no stub, no patch and no LD_PRELOAD defeat, and why this
# script is a hard prerequisite rather than a convenience.  Without it the game
# prints exactly:  Sentinel LDK Protection System: Sentinel key not found (H0007)
# and exits 1, which is rungame.sh's "dongle missing" case.
#
# THE PART THAT IS NOT OBVIOUS.  On a real machine udev does two things when the
# key is plugged in (/etc/udev/rules.d/80-hasp.rules):
#     SYMLINK+="aks/hasp/%k"      -> /dev/aks/hasp/<kernel>
#     RUN+="aksusbd_x86_64 -c $root/aks/hasp/$kernel"
# WSL runs no udev, so BOTH have to be done by hand.  Starting the daemons alone
# is not enough - the key must be REGISTERED with aksusbd or hasplmd never sees
# it and the game still H0007s.  That was the whole difference between a failed
# and a successful boot on 2026-08-19.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "dongle.sh: must run as root (wsl -u root)" >&2; exit 2; }

VID=${JJP_HASP_VIDPID%%:*}
PID=${JJP_HASP_VIDPID##*:}

# 1. Find the key in sysfs, exactly as udev's ATTRS match would.
#
# POLL for it, do not check once.  `usbipd attach` on the Windows side is
# ASYNCHRONOUS: it returns before WSL has finished enumerating the USB device,
# so a single check right after an attach reliably misses a key that is about
# to appear a second or two later - which is exactly how a Start with the key
# plugged in failed with "NO KEY".  Wait up to JJP_KEY_WAIT seconds.
find_key() {
    KDEV=""; USBNODE=""
    for d in /sys/bus/usb/devices/*; do
        [ -f "$d/idVendor" ] || continue
        [ "$(cat "$d/idVendor")" = "$VID" ] || continue
        [ "$(cat "$d/idProduct")" = "$PID" ] || continue
        KDEV=$(basename "$d")
        USBNODE=$(printf "/dev/bus/usb/%03d/%03d" "$(cat "$d/busnum")" "$(cat "$d/devnum")")
        return 0
    done
    return 1
}

KDEV=""; USBNODE=""
for _ in $(seq 1 "${JJP_KEY_WAIT:-15}"); do
    find_key && break
    sleep 1
done
if [ -z "$KDEV" ]; then
    echo "NO KEY: Sentinel $JJP_HASP_VIDPID did not appear inside WSL." >&2
    echo "  Plug the purple JJP key into this PC, then on Windows:" >&2
    echo "    usbipd attach --wsl --hardware-id $JJP_HASP_VIDPID" >&2
    echo "  (usbipd needs a WSL session already running, or it errors with" >&2
    echo "   'There is no WSL 2 distribution running'.)" >&2
    exit 3
fi
echo "key: kernel=$KDEV node=$USBNODE"
chmod 664 "$USBNODE" 2>/dev/null

# 2. The symlink udev would have made.
mkdir -p /dev/aks/hasp
ln -sf "$USBNODE" "/dev/aks/hasp/$KDEV"

# 3. Daemons, INSIDE the jail - they need the image's own glibc/libs, and the
#    jail already has /dev/bus/usb bind-mounted so they still reach the key.
mountpoint -q "$JJP_JAIL" || { echo "dongle.sh: jail not mounted; run jail.sh first" >&2; exit 4; }
pkill -9 -x aksusbd_x86_64 2>/dev/null; pkill -9 -x hasplmd_x86_64 2>/dev/null; sleep 1

chroot "$JJP_JAIL" "$JJP_AKSUSBD" || { echo "aksusbd failed to start" >&2; exit 5; }
sleep 2
# The udev RUN+= line.  Without this the daemon never learns about the key.
chroot "$JJP_JAIL" "$JJP_AKSUSBD" -c "/dev/aks/hasp/$KDEV" || echo "warning: key registration returned non-zero"
sleep 1
chroot "$JJP_JAIL" "$JJP_HASPLMD" -s || { echo "hasplmd failed to start" >&2; exit 6; }

# 4. hasplmd listens on 1947; the game reaches it over localhost.
READY=0
for i in $(seq 1 "${JJP_DAEMON_TIMEOUT:-15}"); do
    sleep 1
    if bash -c 'echo > /dev/tcp/127.0.0.1/1947' 2>/dev/null; then READY=1; echo "hasplmd ready after ${i}s"; break; fi
done
[ "$READY" = "1" ] || echo "warning: port 1947 never answered - the game will probably H0007"

A=$(pgrep -c -x aksusbd_x86_64 2>/dev/null); H=$(pgrep -c -x hasplmd_x86_64 2>/dev/null)
echo "aksusbd=${A:-0} hasplmd=${H:-0}"
