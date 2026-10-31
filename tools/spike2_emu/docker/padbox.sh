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
#
# AS ROOT IN THE BOX (PAD-835), every one of them. A save-state run's guest is
# root's (see RUN_ARGS below), and the box's own user can neither see its
# environment - which is how status.sh and killgame.sh tell a run's processes
# apart - nor kill it: the same reason the app runs these as `wsl -u root` on
# Windows. Root sees and stops an ordinary run just as well. The three
# save-state scripts are here for the same reason and need root besides
# (criu does); PAD_RESTORE_KILL is the one setting of theirs that has to cross.
box_up() { docker ps --format '{{.Names}}' | grep -qx "$NAME"; }
box_exec() {
    local e=()
    [ -n "${PAD_RESTORE_KILL:-}" ] && e+=(-e "PAD_RESTORE_KILL=$PAD_RESTORE_KILL")
    # ${e[@]+...}: the Mac's bash 3.2 under set -u calls an EMPTY array
    # unbound and stops here, so no script ran in the box (PAD-856)
    exec docker exec -u 0 ${e[@]+"${e[@]}"} "$NAME" bash "/pad/rig/$1" "${@:2}"
}
case "${1:-}" in
    alive.sh|killgame.sh|status.sh|restartgame.sh)
        box_up && box_exec "$@"
        # No container: nothing this rig started can be running, so answer
        # rather than starting a box to ask.
        [ "${1:-}" = "alive.sh" ] && { echo "TOTAL STILL RUNNING    : 0  (clean)"; exit 0; }
        [ "${1:-}" = "status.sh" ] && { echo "state=off"; echo "procs=0"; exit 0; }
        echo "[box] nothing running"; exit 0 ;;
    savegame.sh|loadgame.sh)
        box_up && box_exec "$@"
        echo "[${1%.sh}] the emulator is not running - start it first"; exit 1 ;;
    slots.sh)
        # A running box answers from the guest it holds. Without one the slots
        # are still on the rootfs volume, and the Emulate tab lists and deletes
        # them with no game up, as it does on Windows: further down, once the
        # image is known.
        box_up && box_exec "$@" ;;
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
#
# ...AND THE ONE FOLDER EVERY MAC ENGINE SHARES IS HOME (PAD-884). Docker
# Desktop's list above is Docker Desktop's: colima - what "Set up emulator..."
# installs - shares ~ and nothing else, and a bind mount of a path its Linux VM
# cannot see is not refused, it is an EMPTY directory. So an app opened from
# its disk image (/Volumes/...) or one macOS runs from a translocated copy
# (/private/var/folders/...) passed the old Docker-Desktop list, was mounted
# uncopied, and the box said "no rig at /pad/rig" (a Mac on colima, first run).
# Home is shared by Docker Desktop (/Users), colima, OrbStack and Rancher
# Desktop alike, so "under home" is the test, and anything else is copied.
pad_docker_can_share() {
    case "$1" in
        "$HOME"/*) return 0 ;;
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
    # Never a copy of something that is not a rig: a wrong $RIG would have
    # this copy whatever directory it named, however large.
    [ -f "$RIG/watch.sh" ] || {
        echo "[box] no rig at $RIG (no watch.sh there)" >&2; exit 1; }
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

# THE BUILD IS WATCHED, NOT JUST RUN (PAD-769). A Mac user's first Start sat
# on the "building" line for twenty minutes with the tab saying "Not running",
# and nothing in the log could tell a slow download from a docker that had
# stopped answering. So:
#   - BUILDKIT_PROGRESS=plain: one line per step and per apt message, whatever
#     docker decides about the pipe it is writing to. (An env var, not
#     --progress, which a legacy builder would refuse.)
#   - a "[box] still building" line every minute, which the Emulate tab turns
#     into its state label - the run is not "Not running", it is building;
#   - and a build that prints NOTHING for PAD_BOX_SILENT_S (10 min; the longest
#     quiet step measured is the ~40 s image export) is stopped with a message
#     that says where to look, instead of waiting for ever.
build() {
    echo "[box] building $IMAGE (first time takes a few minutes)"
    local beat pidf rc
    beat=$(mktemp -t padbox-beat.XXXXXX) || beat=/tmp/padbox-beat.$$
    pidf=$beat.pid
    printf '%s' "$SECONDS" > "$beat"
    # Short sleeps, so the watcher is gone within seconds of the build: a
    # 60 s sleep left behind would hold the app's output pipe open that long.
    (
        start=$SECONDS; said=0; tick=${PAD_BOX_TICK_S:-60}
        while sleep 2; do
            last=""; read -r last < "$beat" 2>/dev/null
            [ "$last" = done ] && exit 0
            case "$last" in ''|*[!0-9]*) last=$SECONDS ;; esac
            mins=$(( (SECONDS - start) / tick ))
            [ "$mins" -gt "$said" ] || continue
            said=$mins
            echo "[box] still building the emulator container: $mins min so far"
            if [ $(( SECONDS - last )) -ge "${PAD_BOX_SILENT_S:-600}" ]; then
                echo "[box] docker has printed nothing for $(( (SECONDS - last) / 60 )) min, so the build is stopped." >&2
                echo "[box] Open Docker Desktop: it may be waiting for you (an update, a sign-in, an agreement) or out of disk space. Then press Start again." >&2
                read -r pid < "$pidf" 2>/dev/null && kill "$pid" 2>/dev/null
                exit 0
            fi
        done
    ) &
    local watcher=$!
    (
        BUILDKIT_PROGRESS=plain docker build -t "$IMAGE" "$SELF" 2>&1 &
        echo $! > "$pidf"
        wait $!
    ) | while IFS= read -r line; do
        printf '%s\n' "$line"
        printf '%s' "$SECONDS" > "$beat"
    done
    rc=${PIPESTATUS[0]}
    printf done > "$beat"
    kill "$watcher" 2>/dev/null
    wait "$watcher" 2>/dev/null
    rm -f "$beat" "$pidf"
    [ "$rc" = 0 ] || echo "[box] the emulator container did not build (docker exit $rc); the lines above say why." >&2
    return "$rc"
}

case "${1:-}" in
    --build) build; exit $? ;;
esac

# THE SLOTS WITH NO RUN (PAD-835): a throwaway box with only the rig and the
# rootfs volume, as root because the slots are root's. Never a BUILD for it,
# though: a slot list is a status read, and minutes of image build behind one
# would be a hang. No image yet means no run has ever been, so no slots.
if [ "${1:-}" = slots.sh ]; then
    docker image inspect "$IMAGE" >/dev/null 2>&1 ||
        { echo "slots: the emulator has not been set up yet"; exit 1; }
    exec docker run --rm -u 0 -v "$RIG:/pad/rig:ro" \
        -v "${NAME}-rootfs:/pad/rootfs" --entrypoint /bin/bash \
        "$IMAGE" /pad/rig/slots.sh "${@:2}"
fi

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

# ★ A SAVE-STATE RUN (PAD-835): PAD_PIVOT=1, which the Emulate tab asks for on
# every Start, as it does on Windows. criu can only freeze the game when the
# guest is booted as ROOT in its own namespaces (watch.sh: "ROOT RUNS THE
# GUEST"), so the box starts as root - watch.sh drops every helper back to pad,
# and entrypoint.sh keeps the display pad's - and PRIVILEGED, because criu
# walks and rebuilds a process tree with ptrace, its namespaces and its
# /proc/sys knobs, which no short list of capabilities covers on every
# container engine a Mac might have. The box is a Linux VM's process with
# loopback-only ports, so this widens nothing a Mac exposes. A kernel that
# still cannot do it is caught in entrypoint.sh and costs only the save states.
if [ "${1:-}" = watch.sh ] && [ "${PAD_PIVOT:-}" = 1 ]; then
    RUN_ARGS+=(--privileged -u 0 -e PAD_PIVOT=1 -e PAD_USER=pad)
fi

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
# The same prefix swap for an override set (PAD-103), which is a directory on
# the host the box has no view of either. Its own mount rather than a second
# use of /pad/cards: the set is built into the app's temp dir, which is not
# where anybody keeps card images, and read-only because the box only reads it
# (overrides.sh stages a copy inside the box's own home volume).
if [ -n "${PAD_OVERRIDE_DIR:-}" ]; then
    # THE SET IS BUILT IN THE APP'S TEMP DIR, which on a Mac is
    # /var/folders/..., outside home - the same empty mount the rig got on
    # colima (PAD-884), and an empty override set is a run that quietly shows
    # none of your edits. So it is copied into home first, MIRRORED (--delete)
    # rather than copied over the top: a file left from an older set would
    # still override the card. rsync, so an unchanged set costs a compare and
    # not a copy - sets can be hundreds of MB.
    if [ "$(uname -s)" = Darwin ] && [ -d "$PAD_OVERRIDE_DIR" ]        && ! pad_docker_can_share "$PAD_OVERRIDE_DIR"; then
        OSTAGE=${PAD_BOX_OVERRIDE_STAGE:-$HOME/Library/Caches/pinball_decryptor/spike2_overrides}
        echo "[box] $PAD_OVERRIDE_DIR is outside Docker's file sharing; using a copy in $OSTAGE"
        mkdir -p "$OSTAGE" && rsync -a --delete "${PAD_OVERRIDE_DIR%/}/" "$OSTAGE/" || {
            echo "[box] could not copy your edits into $OSTAGE" >&2; exit 1; }
        PAD_OVERRIDE_DIR=$OSTAGE
    fi
    if [ -d "$PAD_OVERRIDE_DIR" ]; then
        RUN_ARGS+=(-v "${PAD_OVERRIDE_DIR%/}:/pad/overrides:ro"
                   -e "PAD_OVERRIDE_DIR=/pad/overrides")
    else
        echo "[box] no such override folder: $PAD_OVERRIDE_DIR" >&2
        exit 1
    fi
fi
# A MEDIA DIRECTORY IS A HOST PATH TOO (item 90), so it needs the same prefix
# swap the card just had, or the box would be handed a path only the Mac can
# open and the menu would come up bare. Only $CARD_DIR is mounted, so a
# directory outside it cannot cross at all - said out loud, because the
# alternative is quietly showing the card's own art to someone who asked for
# theirs.
if [ -n "${PAD_SELECT_MEDIA:-}" ]; then
    case "$PAD_SELECT_MEDIA" in
        "$CARD_DIR"/*) PAD_SELECT_MEDIA=/pad/cards/${PAD_SELECT_MEDIA#"$CARD_DIR"/} ;;
        *) echo "[box] PAD_SELECT_MEDIA is not under $CARD_DIR, so the box cannot" >&2
           echo "[box] see it; the boot menu will use the card's own media." >&2
           echo "[box] Set PAD_CARD_DIR to a directory that contains both." >&2
           PAD_SELECT_MEDIA="" ;;
    esac
fi

# THE BOX GETS THE SAME KNOBS THE RIG HAS (item 90). PAD_SELECT is a
# three-way switch - unset asks the card, 1 forces the boot menu on, 0 forces
# it off - and without it on this list a Mac could not answer that question at
# all: the container's watch.sh saw an unset variable and asked the card, so
# neither an override nor a refusal ever crossed. `[ -n "${!v:-}" ]` passes a
# literal "0" (it is one character, not empty), which is exactly what the
# "force it off" answer has to look like on the other side.
# PAD-149's machine row rides the same list: the CPU board's country DIP
# switches (PAD_CAB_DIP), the country stored in the machine (PAD_COUNTRY), the
# mains (PAD_MAINS_HZ) and which mains the board was built for
# (PAD_FACTORY_HZ), and the model the board says the machine is (PAD_MODEL,
# PAD-519). Unset is the rig's own machine, exactly as it was.
# PAD_CARD_MODES=0 is the opt-out from a card's own modes (modes/cardmodes.sh). That
# feature needs nothing from out here - run_game.sh reads the card inside the box - but
# a "no" has to be able to cross, for the same reason PAD_SELECT=0 does.
for v in PAD_GAME PAD_PLAYFIELD PAD_AUDIO PAD_AUTO_ATTRACT \
         PAD_SELECT PAD_SELECT_TIMEOUT PAD_SELECT_MEDIA PAD_CARD_MODES \
         PAD_CAB_DIP PAD_COUNTRY PAD_MAINS_HZ PAD_FACTORY_HZ PAD_MODEL LOG; do
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
# HOW THE CHANNEL COUNT IS SAID depends on the ffplay (PAD-832). FFmpeg 7 took
# `-ac` away from ffplay (it was the raw demuxer's `channels` option, now gone;
# only `-ch_layout` is left), and Homebrew ships 7 and newer, so a Mac's ffplay
# said "Failed to set value '2' for option 'ac': Option not found", exited, and
# every run was silent. `-ch_layout` exists from 5.1 on; an older ffplay has
# no such option and still takes `-ac`. Ask the ffplay which one it has.
ffplay_channel_args() {
    if ffplay -hide_banner -h demuxer=s16le 2>/dev/null | grep -q -- '-ch_layout'; then
        case "$1" in
            1) echo "-ch_layout mono" ;;
            2) echo "-ch_layout stereo" ;;
            *) echo "-ch_layout ${1}c" ;;
        esac
    else
        echo "-ac $1"
    fi
}
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
        chargs=$(ffplay_channel_args "$ch")
        echo "[box] audio: ffplay, ${rate} Hz x ${ch} ch ($chargs) from tcp/$AUDIO_PORT"
        # $chargs unquoted on purpose: it is an option and its value
        exec ffplay -hide_banner -loglevel error -nodisp -autoexit \
             -fflags nobuffer -flags low_delay \
             -f s16le -ar "$rate" $chargs "tcp://127.0.0.1:$AUDIO_PORT"
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
