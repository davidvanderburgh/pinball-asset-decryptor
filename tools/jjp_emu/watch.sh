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

# Export the ISO BEFORE sourcing padpath, and before spawning any child script,
# so watch.sh and every step (jail, dongle, boards, game) derive the SAME
# JJP_BASE from it.  Otherwise padpath falls back to the last-mounted title and
# a fresh Godfather launch runs against Wonka's directory.
JJP_ISO=${JJP_ISO:-${1:-}}
export JJP_ISO
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "watch.sh: must run as root (wsl -u root)" >&2; exit 2; }

ISO=$JJP_ISO
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

# Rebuild the shim + CUSE daemon when their sources changed (or are missing).
# The GUI only ever calls THIS script, so without this a C change would never
# reach a running rig.  It is safe here and nowhere else: the jail is mounted
# (build.sh links the shim against the image's libc) and the game is not up yet
# (build.sh refuses while a game is live, to avoid SIGBUS'ing a mapped .so).
CUSE_BIN=${JJP_CUSE_BIN:-/var/tmp/jjpcuse}
SHIM_SO=${JJP_SHIM_SO:-/var/tmp/jjphwshim.so}
if [ ! -x "$CUSE_BIN" ] || [ ! -f "$SHIM_SO" ] \
   || [ "$HERE/jjpcuse.c"   -nt "$CUSE_BIN" ] \
   || [ "$HERE/jjphwshim.c" -nt "$SHIM_SO" ] \
   || [ "$HERE/jjpshm.h"    -nt "$CUSE_BIN" ] \
   || [ "$HERE/jjpshm.h"    -nt "$SHIM_SO" ]; then
    step "build (sources changed)"
    bash "$HERE/build.sh" || echo "watch.sh: build failed - boards may be stale"
fi

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
JJPSHM="$HERE/jjpshm.h" SHMDEV="/dev/shm${JJP_SHM_NAME:-/jjp_switches}" \
python3 - <<'PYEOF' 2>/dev/null || true
import os, re
# Derive the out_changes offset from jjpshm.h so this mirror can never drift
# from the struct - the rig's one-definition rule.  Layout: magic+version+pid
# (12) + in_frame(FRAME_LEN) + out(BOARD_COUNT*FRAME_LEN), then everything this
# zeroes: out_changes, the per-bit out_rise counters, read_count, write_count.
# in_frame is deliberately NOT touched - it is the machine's resting state and
# zeroing it jams every cabinet switch (see jjpshm.h).
h = open(os.environ["JJPSHM"]).read()
frame = int(re.search(r'JJP_FRAME_LEN\s+(\d+)', h).group(1))
names = [n.split('=')[0].strip()
         for n in re.search(r'enum\s*\{(.*?)\}', h, re.S).group(1).split(',')
         if n.strip()]
boards = names.index('JJP_BOARD_COUNT')
off = 12 + frame + boards * frame
tail = boards * 4 + boards * frame * 8 + 8
try:
    f = open(os.environ["SHMDEV"], 'r+b')
    f.seek(off); f.write(bytes(tail))
    f.close()
except OSError:
    pass
PYEOF

# Lay the machine down at rest BEFORE the game reads its first frame.  The game
# latches its ball count at power-up and the trough is inverted optos, so a bare
# idle frame reads as an empty/jammed trough and the game never starts.  Uses
# the cached device dump for the inverted set (a first-ever boot has none and is
# a no-op; the dump that run writes makes the next boot correct).  See
# seed_rest.py.
step "seed rest state"
python3 "$HERE/seed_rest.py" "${JJP_DEVICES_JSON:-/var/tmp/jjp_devices.json}" \
    || echo "watch.sh: rest seed skipped"

step "game"
JJP_DISPLAY=$RUN_DISPLAY bash "$HERE/run_game.sh" --detach || exit 6

# The switch matrix comes up WITH the emulator rather than behind a button:
# it is the control surface for the machine, not an optional extra, and a
# button that silently did nothing is how this presented the first time.
if [ "${JJP_NO_MATRIX:-0}" != "1" ]; then
    step "switch matrix"
    bash "$HERE/jjpsw_launch.sh" || echo "watch.sh: switch matrix did not open"
fi

echo
bash "$HERE/status.sh"
