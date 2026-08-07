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
IMAGE=${PAD_BOX_IMAGE:-pad-spike2-emu}
NAME=${PAD_BOX_NAME:-pad-spike2}
PORT=${PAD_VNC_PORT:-5900}

command -v docker >/dev/null 2>&1 || {
    echo "[box] docker is not installed." >&2
    echo "[box] macOS: install Docker Desktop, or 'brew install --cask docker'." >&2
    exit 1
}
docker info >/dev/null 2>&1 || {
    echo "[box] docker is installed but not running - start Docker Desktop." >&2
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

build() {
    echo "[box] building $IMAGE (first time takes a few minutes)"
    docker build -t "$IMAGE" "$SELF"
}

case "${1:-}" in
    --build) build; exit $? ;;
esac

# Build on demand rather than making the user remember a separate step.
docker image inspect "$IMAGE" >/dev/null 2>&1 || build || exit 1

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

echo "[box] starting; the picture appears at vnc://localhost:$PORT"
echo "[box] on macOS: open vnc://localhost:$PORT   (Screen Sharing, nothing to install)"
exec docker run "${RUN_ARGS[@]}" "$IMAGE" "$@"
