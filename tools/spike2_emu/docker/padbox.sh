#!/bin/bash
# padbox.sh - run a rig script inside the container. The macOS entry point.
#
#   padbox.sh watch.sh 30        # run the emulator, then open vnc://localhost:5900
#   padbox.sh alive.sh           # what is still running
#   padbox.sh killgame.sh        # stop everything
#   padbox.sh --build            # (re)build the image
#   padbox.sh --shell            # a shell inside the box
#
# WHAT THIS IS FOR. The rig is a Linux program - qemu-user translates Linux
# syscalls and the chroot needs Linux namespaces - so on macOS it runs in a
# container and this is the one place that knows how to start it. On Linux and
# on WSL nothing here is needed; watch.sh is run directly.
#
# THE CARD IMAGE IS MOUNTED READ ONLY, which is the same guarantee the rig makes
# everywhere else: card images are often the only copy.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)
RIG=$(cd "$SELF/.." && pwd)
IMAGE=${PAD_BOX_IMAGE:-}     # defaulted below, AFTER the rig's location is final
NAME=${PAD_BOX_NAME:-pad-spike2}
PORT=${PAD_VNC_PORT:-5900}
# A PASSWORD IS NOT OPTIONAL HERE, and not for security (the port is loopback
# only): macOS Screen Sharing refuses a VNC server that offers no
# authentication at all. Against the old -nopw default it put up a password
# prompt anyway, and whatever was typed failed - a tester hit exactly that.
# The Emulate tab opens vnc://:pinball@localhost:5900, so the two defaults
# must match; see _apply() in pinball_decryptor/gui/emulate_tab.py.
PAD_VNC_PASSWD=${PAD_VNC_PASSWD:-pinball}

# WHERE THE MAC KEEPS ITS TOOLS. This script is normally started BY THE APP,
# and a GUI app launched from Finder inherits launchd's PATH - /usr/bin:/bin:
# /usr/sbin:/sbin - which contains no docker, no colima and no ffplay, on a Mac
# where all three are installed and working. Appended, never prepended: a user
# who set PATH themselves has already answered this and their answer wins.
PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:/opt/local/bin
PATH=$PATH:$HOME/.docker/bin:$HOME/.rd/bin:$HOME/.orbstack/bin
PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin
# The app's own override (see docker_cli() in emulate_tab.py), for the Mac that
# keeps it somewhere none of those name. Its DIRECTORY goes first, so `docker`
# means the same binary here as it did in the check that let this run start.
[ -n "${PAD_DOCKER:-}" ] && [ -x "$PAD_DOCKER" ] && \
    PATH=$(dirname "$PAD_DOCKER"):$PATH
export PATH

command -v docker >/dev/null 2>&1 || {
    echo "[box] docker is not installed." >&2
    echo "[box] macOS: install Docker Desktop, or 'brew install colima docker'." >&2
    exit 1
}
docker info >/dev/null 2>&1 || {
    # TWO DIFFERENT FAULTS. On macOS `docker` is only a client and the
    # containers need a Linux machine behind it, so a package manager's docker
    # on its own lands here with nothing to start - and "start Docker Desktop"
    # names an app that Mac does not have. See docker_state() in emulate_tab.py.
    if [ -d /Applications/Docker.app ] || [ -d /Applications/OrbStack.app ] \
       || [ -d "/Applications/Rancher Desktop.app" ] \
       || command -v colima >/dev/null 2>&1; then
        echo "[box] docker is installed but not running - start it and try again." >&2
    else
        echo "[box] the docker command is installed, but nothing on this Mac runs" >&2
        echo "[box] containers. docker is only the client; the containers need a" >&2
        echo "[box] Linux machine behind it." >&2
        echo "[box] In the app: Emulate tab -> \"Set up emulator...\", which installs" >&2
        echo "[box] one and starts it. (From a shell: colima, from Homebrew or" >&2
        echo "[box] MacPorts, is what that button installs.)" >&2
    fi
    exit 1
}

# alive.sh / killgame.sh talk about a RUN, so they belong in the container that
# is running it - not in a second one that shares none of its processes. This is
# the same "one definition of what is running" rule the rig applies everywhere.
#
# ANSWERED FIRST, before anything below is set up, because status.sh is asked
# every two seconds by the Emulate tab and none of it needs an image, a volume,
# a mount or a staged copy. It used to sit at the bottom, so every poll built
# the whole run configuration and could even trigger an image build, to answer
# a question that needs neither.
case "${1:-}" in
    alive.sh|killgame.sh|status.sh)
        if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
            exec docker exec "$NAME" bash "/pad/rig/$1" "${@:2}"
        fi
        # No container: nothing this rig started can be running, so answer
        # rather than starting a box to ask.
        [ "${1:-}" = "alive.sh" ] && { echo "TOTAL STILL RUNNING    : 0  (clean)"; exit 0; }
        [ "${1:-}" = "status.sh" ] && { echo "state=off"; echo "procs=0"; exit 0; }
        echo "[box] nothing running"; exit 0 ;;
esac

# ---- THE RIG HAS TO LIVE SOMEWHERE DOCKER IS ALLOWED TO LOOK ---------------
#
# Docker Desktop on macOS bind-mounts only paths on its file-sharing list, and
# the default list is /Users /Volumes /private /tmp /var/folders. AN INSTALLED
# APP LIVES IN /Applications, WHICH IS NOT ON IT, so mounting the rig straight
# out of the bundle fails with
#
#   the path /Applications/Pinball Asset Decryptor.app/Contents/Resources/
#   tools/spike2_emu is not shared from the host and is not known to Docker
#
# and the emulator is unreachable for precisely the people who installed the app
# instead of cloning it - the case the rig was made to ship for. Telling them to
# add /Applications to Docker's settings is a support instruction, not a fix.
#
# So the rig is COPIED into the user's home, which Docker shares out of the box,
# and the container mounts the copy. Copied EVERY START rather than tracked for
# staleness: it is a few megabytes of scripts, so freshness is worth more than
# the milliseconds, and an app update reaches the box with no cache to reason
# about. (The hardware shim is the opposite case - minutes to rebuild - which is
# why that one is digest-tracked instead. See watch.sh.)
pad_docker_can_share() {
    case "$1" in
        /Users/*|/Volumes/*|/private/*|/tmp/*|/var/folders/*) return 0 ;;
        *) return 1 ;;
    esac
}

if [ "$(uname -s)" = Darwin ] && ! pad_docker_can_share "$RIG"; then
    STAGE=${PAD_BOX_STAGE:-$HOME/Library/Application Support/pinball_decryptor/spike2_emu}
    if ! pad_docker_can_share "$STAGE"; then
        echo "[box] Docker cannot share $RIG, and the staging directory" >&2
        echo "[box]   $STAGE" >&2
        echo "[box] is not one it can share either. Point PAD_BOX_STAGE at a" >&2
        echo "[box] directory under your home folder." >&2
        exit 1
    fi
    echo "[box] $RIG is outside Docker's file sharing; using a copy in $STAGE"
    # OVER THE TOP, never rm -rf first: a live container has this directory
    # bind mounted, and deleting it underneath one would break a run that has
    # nothing to do with this command. Nothing in the rig is written to at run
    # time, so an overwrite in place is safe.
    mkdir -p "$STAGE" || exit 1
    cp -R "$RIG"/. "$STAGE"/ || {
        echo "[box] could not copy the rig into $STAGE" >&2; exit 1; }
    RIG=$STAGE
    SELF=$STAGE/docker
fi

# THE IMAGE FOLLOWS ITS SOURCES. "Build if missing" alone stranded every
# installed Mac on whatever image its first run built: a shipped fix to the
# Dockerfile or entrypoint.sh never arrived, because the image was never
# missing again. The tag carries a checksum of the build context, so a changed
# context is a new tag, which IS missing, and so builds. Superseded
# generations are pruned after the build (see below).
if [ -z "$IMAGE" ]; then
    DKSUM=$(cat "$SELF/Dockerfile" "$SELF/entrypoint.sh" 2>/dev/null | cksum | cut -d' ' -f1)
    IMAGE=pad-spike2-emu:c$DKSUM
fi

build() {
    echo "[box] building $IMAGE (first time takes a few minutes)"
    docker build -t "$IMAGE" "$SELF"
}

case "${1:-}" in
    --build) build; exit $? ;;
esac

# Build on demand rather than making the user remember a separate step.
docker image inspect "$IMAGE" >/dev/null 2>&1 || build || exit 1
# Prune the generations this one supersedes. rmi refuses an image a live
# container still uses, which is the correct answer, so failures are ignored.
docker images pad-spike2-emu --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | grep -vx "$IMAGE" | while read -r old; do
        docker rmi "$old" >/dev/null 2>&1 || true
    done

# WHERE THE CARDS ARE. The rig is handed a path inside the container, so the
# directory holding the image has to be mounted. PAD_CARD_DIR overrides; the
# default covers "the image sits somewhere under home", which is where a Mac
# user's downloads and external drives both end up.
CARD_DIR=${PAD_CARD_DIR:-$HOME}

# PERSISTENT, and it matters: PAD_ROOT is the guest filesystem rootfs.sh builds
# out of a card, which takes minutes. A named volume keeps it across runs, so
# that cost is paid once rather than every time the container starts.
docker volume create "${NAME}-home" >/dev/null
docker volume create "${NAME}-rootfs" >/dev/null

# --cap-add SYS_ADMIN + /dev/fuse   cardmount.sh's read-only FUSE mount
# --security-opt seccomp=unconfined run_game.sh's `unshare -r -m -p -f`; the
#                                   default seccomp profile blocks unshare, and
#                                   without it the guest cannot get its own
#                                   mount and PID namespaces at all
# -p 127.0.0.1:PORT                 LOOPBACK ONLY. The VNC display is an
#                                   unauthenticated view of the machine; it has
#                                   no business on the network.
RUN_ARGS=(
    --rm
    --name "$NAME"
    --cap-add SYS_ADMIN
    --device /dev/fuse
    --security-opt seccomp=unconfined
    --security-opt apparmor=unconfined
    -p "127.0.0.1:$PORT:5900"
    -v "$RIG:/pad/rig:ro"
    -v "$CARD_DIR:/pad/cards:ro"
    -v "${NAME}-home:/pad/home"
    -v "${NAME}-rootfs:/pad/rootfs"
    -e "PAD_VNC_PORT=5900"
)
[ -n "${PAD_VNC_PASSWD:-}" ] && RUN_ARGS+=(-e "PAD_VNC_PASSWD=$PAD_VNC_PASSWD")

# SOUND LEAVES OVER TCP. No audio server exists inside the box and VNC carries
# no sound, so the guest's PCM is served raw on a loopback port (playaudio.sh's
# relay sink) and played out here on the Mac by host_player(), below.
AUDIO_PORT=${PAD_AUDIO_PORT:-45997}
RUN_ARGS+=(-p "127.0.0.1:$AUDIO_PORT:$AUDIO_PORT"
           -e "PAD_AUDIO_SINK=relay" -e "PAD_AUDIO_PORT=$AUDIO_PORT")

# A card path on the HOST has to become one inside the box. Only the directory
# is mounted, so this is a prefix swap and not a guess.
if [ -n "${PAD_CARD:-}" ]; then
    case "$PAD_CARD" in
        "$CARD_DIR"/*) RUN_ARGS+=(-e "PAD_CARD=/pad/cards/${PAD_CARD#"$CARD_DIR"/}") ;;
        *) echo "[box] the card is not under $CARD_DIR, so the box cannot see it." >&2
           echo "[box] set PAD_CARD_DIR to a directory that contains it." >&2
           exit 1 ;;
    esac
fi
for v in PAD_GAME PAD_PLAYFIELD PAD_AUDIO PAD_AUTO_ATTRACT LOG; do
    [ -n "${!v:-}" ] && RUN_ARGS+=(-e "$v=${!v}")
done

case "${1:-}" in
    --shell) exec docker run -it "${RUN_ARGS[@]}" "$IMAGE" bash ;;
esac

# THE SPEAKER, on the Mac itself. Waits for the guest to report its PCM format
# (rate + channels land in a file docker exec can read - guessing the rate
# plays every title ~9% sharp, see playaudio.sh), then plays the relay port.
# ffplay is the deliberate first choice: it ships with the ffmpeg this app
# already requires on macOS, whereas probing `python3 -c "import sounddevice"`
# on a Mac without the developer tools pops Apple's install dialog mid-run.
# The poll is long (10 min) because a FIRST run builds the guest rootfs out of
# the card before the game ever configures audio.
host_player() {
    [ "${PAD_AUDIO:-1}" = 0 ] && return 0
    fmt=""
    for _ in $(seq 1 1200); do
        fmt=$(docker exec "$NAME" cat /pad/rootfs/dump/audio.fmt 2>/dev/null) && [ -n "$fmt" ] && break
        fmt=""; sleep 0.5
    done
    [ -n "$fmt" ] || { echo "[box] the guest never reported a PCM format; this run is silent" >&2; return 0; }
    set -- $fmt
    rate=${1:-48000}; ch=${2:-2}
    if command -v ffplay >/dev/null 2>&1; then
        echo "[box] audio: ffplay, ${rate} Hz x ${ch} ch from tcp/$AUDIO_PORT"
        exec ffplay -hide_banner -loglevel error -nodisp -autoexit \
             -fflags nobuffer -flags low_delay \
             -f s16le -ar "$rate" -ac "$ch" "tcp://127.0.0.1:$AUDIO_PORT"
    fi
    echo "[box] no ffplay on this Mac, so this run is silent. Fix:" >&2
    echo "[box]   brew install ffmpeg   (the same package the app's previews use)" >&2
}

echo "[box] starting; the picture appears at vnc://:$PAD_VNC_PASSWD@localhost:$PORT"
echo "[box] on macOS: open 'vnc://:$PAD_VNC_PASSWD@localhost:$PORT'   (Screen Sharing; VNC password: $PAD_VNC_PASSWD)"
# NOT exec'd any more: the run has a Mac-side child now, and something has to
# be here afterwards to take it down when the box exits.
host_player & HOSTAUD=$!
docker run "${RUN_ARGS[@]}" "$IMAGE" "$@"
RC=$?
kill "$HOSTAUD" 2>/dev/null
wait "$HOSTAUD" 2>/dev/null
exit "$RC"
