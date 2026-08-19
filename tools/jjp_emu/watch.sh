#!/bin/bash
# The whole launch, in the one order that works.  The GUI calls this and
# nothing else, so the sequence lives HERE and not in a Python panel.
#
# Order matters, and each step is a thing that was learned the hard way:
#
#   1. mount    - ISO -> read-only game filesystem (cached; usually a no-op)
#   2. jail     - overlayfs so a run can never write to the image
#   3. dongle   - register the Sentinel key the way udev would, start the
#                 daemons.  WITHOUT THIS THE GAME PRINTS H0007 AND EXITS 1:
#                 the key is not a check, it decrypts the code.
#   4. audio    - point ALSA at WSLg's PulseAudio; WSL has no sound card
#   5. cuse     - REAL /dev/jjp* devices.  An LD_PRELOAD shim cannot work on
#                 this binary (the envelope resolves libc itself), so the
#                 boards have to exist as far as the kernel is concerned.
#   6. display  - a nested X server at the game's native size, so it does not
#                 fullscreen to a 4K desktop and fall back to software GL
#   7. game     - detached; status.sh is how the GUI watches it
#
# Steps 3-6 are all optional in the sense that the game still starts without
# them - it just starts wrong (no sound, no switches, 4K llvmpipe) - so each
# one warns rather than aborting, except the dongle, which is fatal.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "watch.sh: must run as root (wsl -u root)" >&2; exit 2; }

ISO=${1:-${JJP_ISO:-}}
step() { echo "== $* =="; }

if [ -n "$ISO" ]; then
    step "mount image"
    bash "$HERE/mount.sh" "$ISO" || exit 3
else
    mountpoint -q "$JJP_ROOT" || {
        echo "watch.sh: no image mounted and no ISO given" >&2; exit 3; }
fi

step "jail"
bash "$HERE/jail.sh" || exit 4

step "dongle"
if ! bash "$HERE/dongle.sh"; then
    echo "watch.sh: FATAL - no Sentinel key." >&2
    echo "  The game binary is Sentinel LDK Envelope-protected: the purple USB" >&2
    echo "  key supplies the AES key that decrypts its code, so this is not a" >&2
    echo "  check that can be skipped.  Attach it from Windows with:" >&2
    echo "      usbipd attach --wsl --hardware-id $JJP_HASP_VIDPID" >&2
    exit 5
fi

step "audio"
bash "$HERE/audio.sh" || echo "watch.sh: audio setup failed - the game will run silent"

step "boards"
bash "$HERE/jjpcuse.sh" start || echo "watch.sh: CUSE boards unavailable - no switches or LEDs"

step "display"
if bash "$HERE/display.sh"; then
    RUN_DISPLAY=${JJP_NESTED:-:1}
else
    echo "watch.sh: no nested display - falling back to $JJP_DISPLAY (expect 4K software GL)"
    RUN_DISPLAY=$JJP_DISPLAY
fi

# Zero the frame counters so the panel shows THIS run's traffic.  They live in
# shared memory and outlive the game, so without this a stopped rig still reads
# "382,506 frames in" from the last run and looks alive.
python3 - <<'PYEOF' 2>/dev/null || true
import struct
OFF = 12 + 16 + 16 + 8*64          # out_changes, per jjpshm.h
try:
    f = open('/dev/shm/jjp_switches', 'r+b')
    f.seek(OFF); f.write(bytes(8*4 + 8))   # out_changes + read/write counts
    f.close()
except OSError:
    pass
PYEOF

step "game"
JJP_DISPLAY=$RUN_DISPLAY bash "$HERE/run_game.sh" --detach || exit 6

echo
bash "$HERE/status.sh"
