#!/bin/bash
# netns.sh - run_game.sh's inside half, run by `unshare --net --mount` as
# root: bring up the namespace's own loopback, bind the rig's /game, start
# the hidden display, Alice Cooper's Unity player, then the game as
# $SPP_USER, and wait.  Writes unity.pid / game.pid (host pids; killgame.sh
# stops them) and ns.pid.
set -u
# lo starts down in a new network namespace (no `ip` in PAD-Runtime).
python3 - <<'PY'
import fcntl, socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
IFF_UP, IFF_LOOPBACK, IFF_RUNNING = 0x1, 0x8, 0x40
fcntl.ioctl(s, 0x8914, struct.pack("16sH14x", b"lo", IFF_UP | IFF_LOOPBACK | IFF_RUNNING))  # SIOCSIFFLAGS
PY
mount --bind "$SPP_RIG/game" /game || exit 3
echo $$ > "$SPP_RIG/ns.pid"
if [ "${SPP_XVFB:-0}" = 1 ]; then
    Xvfb "$DISPLAY" -screen 0 "${SPP_SCREEN}x24" -nolisten tcp -nocursor < /dev/null > "$SPP_RIG/xvfb.log" 2>&1 &
    echo $! > "$SPP_RIG/xvfb.pid"
    for _ in $(seq 1 50); do grep -q "@/tmp/.X11-unix/X${DISPLAY#:}\$" /proc/net/unix && break; sleep 0.1; done
fi

E=$SPP_PY
run_as() {      # <log> <cmd...>: as $SPP_USER, env built from scratch
    local log=$1; shift
    runuser -u "$SPP_USER" -- env -i \
        PATH="$SPP_RIG/bin:$E/bin:/usr/local/bin:/usr/bin:/bin" HOME="$SPP_RIG" USER="$SPP_USER" LANG=C.UTF-8 \
        DISPLAY="$DISPLAY" SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-}" \
        SDL_DISKAUDIOFILE="${SDL_DISKAUDIOFILE:-}" SDL_DISKAUDIODELAY="${SDL_DISKAUDIODELAY:-}" \
        PULSE_SERVER="${PULSE_SERVER:-}" \
        LD_LIBRARY_PATH="$E/lib" PYSDL2_DLL_PATH="$E/lib" \
        PYTHONPATH="$SPP_STUB:$SPP_SITE" PROC_EMU_FPGA="$PROC_EMU_FPGA" SPP_LOG="$SPP_RIG/rig.log" SPP_OSFILES="${SPP_OSFILES:-}" \
        SPP_BALLS="${SPP_BALLS:-}" PROC_EMU_CTL="${PROC_EMU_CTL:-}" SPK_MARK="$SPP_RIG" \
        PYGAME_HIDE_SUPPORT_PROMPT=1 \
        "$@" < /dev/null > "$log" 2>&1 &
    echo $!
}

# What the game shells out to on the machine (unlock-root, lock-root, sync,
# reboot, killall, lsblk...) that must not reach this PC: logging no-ops
# first on its PATH.
mkdir -p "$SPP_RIG/bin"
for c in unlock-root lock-root reboot shutdown killall hwclock timedatectl mount umount; do
    printf '#!/bin/sh\necho "$(date +%%T) %s $*" >> %s/shell.log\n' "$c" "$SPP_RIG" > "$SPP_RIG/bin/$c"
    chmod 755 "$SPP_RIG/bin/$c"
done

cd "/game/$SPP_DIR" || exit 3
if [ -n "$SPP_UNITY" ]; then
    # Alice Cooper: the Unity player draws the screen and listens on :9999;
    # the game dials it once, at start, and dies if nobody answers.
    run_as "$SPP_RIG/unity.out" "./$SPP_UNITY" -force-glcore -screen-fullscreen 1 \
        -screen-width "${SPP_SCREEN%x*}" -screen-height "${SPP_SCREEN#*x}" \
        -logfile "$SPP_RIG/player.log" > "$SPP_RIG/unity.rpid"
    for _ in $(seq 1 600); do
        grep -q ':270F ' /proc/net/tcp && break      # 9999, listening
        sleep 0.1
    done
fi
run_as "$SPP_RIG/game.out" "$E/bin/python2.7" -u "$SPP_TOOLS/spprun.py" "$SPP_LAUNCH" > "$SPP_RIG/game.rpid"
sleep 0.5
# runuser's child is the process that matters.
for n in unity game; do
    [ -f "$SPP_RIG/$n.rpid" ] || continue
    r=$(cat "$SPP_RIG/$n.rpid"); c=$(pgrep -P "$r" | head -1)
    echo "${c:-$r}" > "$SPP_RIG/$n.pid"
done
wait
