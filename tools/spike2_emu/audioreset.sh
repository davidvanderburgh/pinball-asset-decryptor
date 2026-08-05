#!/bin/bash
# audioreset.sh - the remedy for WSLg audio crackle, in the right order.
#
# The fix is `wsl --shutdown`, which rebuilds the WSLg PulseAudio server and
# the RDP audio channel that carries sound to Windows. Doing that with a run
# live is how you leak things: the shutdown kills the VM out from under the
# emulated game, the node bus and the host renderer, and none of their teardown
# runs. So tear the rig down first, prove it is down, and only then pull the
# floor out.
#
# Confirm before it acts, because it terminates EVERY WSL distro and anything
# else the user has running in them - not just this rig. `--yes` skips the
# prompt for scripted use.
#
# See tonetest.sh for whether you actually need this: if a pure sine crackles
# too, the emulator is not at fault and this is the fix. If the sine is clean,
# do NOT reach for this - the problem is somewhere in the rig and restarting
# WSL will only hide it for a while.
set -u
S="$(cd "$(dirname "$0")" && pwd)"

echo "[reset] tearing the rig down first"
bash "$S/killgame.sh" || true
sleep 1
bash "$S/alive.sh" | tail -7

LEFT=$(pgrep -c -x game 2>/dev/null || echo 0)
if [ "${LEFT:-0}" != 0 ]; then
    echo "[reset] the guest is STILL up - not shutting down WSL. Fix that first." >&2
    exit 1
fi

if [ "${1:-}" != "--yes" ]; then
    cat <<'EOF'

[reset] Ready. The next step terminates EVERY WSL distro on this machine,
        not just this rig - anything else you have open in WSL will be
        killed too. Nothing is lost on disk; WSL restarts on next use.

        Run it yourself from Windows:

            wsl --shutdown

        or re-run this script with --yes to do it now.
EOF
    exit 0
fi

echo "[reset] shutting WSL down now - this session ends here"
# wsl.exe is reachable from inside WSL through the interop mount, and yes, it
# happily terminates the distro it was called from. That is the intent.
/mnt/c/Windows/System32/wsl.exe --shutdown
