#!/bin/bash
# spkbox.sh - run the Spooky rig in a container: the macOS route (PAD-953).
#
#   spkbox.sh watch.sh <update file>   start the box and the game in it; returns
#                                      at attract, as watch.sh does on Windows
#   spkbox.sh status.sh | stop.sh | cancel.sh | ctl.sh ... | cache.sh ...
#   spkbox.sh playfield <switches.json in the box>   the virtual playfield,
#                                      a window on the box's screen
#   spkbox.sh --build                  (re)build the image
#   spkbox.sh --shell                  a root shell in the running box
#
# The app runs every rig script through this on a Mac
# (emulate_spooky_core.rig_cmd), with the settings it would give watch.sh in
# the environment; this forwards the ones the rig reads into the box.
#
# THE SHAPE, and why it differs from the Spike 2 box (tools/spike2_emu/docker/
# padbox.sh): a Spooky watch.sh returns once the game is in attract and leaves
# it running detached, so the box cannot be watch.sh's own container - it would
# end when watch.sh did. The box is started idle (docker run -d; entrypoint.sh
# brings up the screen, VNC and the sound), and every script, watch.sh
# included, is a `docker exec` into it. Stop and Cancel remove the box.
#
# Ports differ from the Spike 2 box's (VNC 5901, sound 45998) so both can be
# up at once; the picture is vnc://:pinball@localhost:5901.
#
# THE UPDATE FILE'S FOLDER IS MOUNTED READ ONLY: update files are often the
# only copy someone has.
set -u

SELF=$(cd "$(dirname "$0")" && pwd)
APP=$(cd "$SELF/../../.." && pwd)
NAME=${PAD_SPK_BOX_NAME:-pad-spooky}
PORT=${PAD_SPK_VNC_PORT:-5901}
AUDIO_PORT=${PAD_SPK_AUDIO_PORT:-45998}
VOL=${NAME}-var
PAD_VNC_PASSWD=${PAD_VNC_PASSWD:-pinball}
PLATFORM=linux/amd64
RIG=/pad/app/tools/spooky_emu

# A GUI app started from Finder has launchd's PATH, with no docker on it (the
# Spike 2 box's lesson, padbox.sh); appended, so a user's own PATH wins.
PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:/opt/local/bin
PATH=$PATH:$HOME/.docker/bin:$HOME/.rd/bin:$HOME/.orbstack/bin
PATH=$PATH:/opt/podman/bin
PATH=$PATH:/Applications/Docker.app/Contents/Resources/bin
# Podman stands in for docker through a `docker` link to it, in one shim
# folder per user that every start reuses (a folder per run would pile up
# in TMPDIR, as nothing after the exec below is left to remove it).
if [ -n "${PAD_DOCKER:-}" ] && [ -x "$PAD_DOCKER" ]; then
    if [ "$(basename "$PAD_DOCKER")" != "docker" ]; then
        _SHIM="${TMPDIR:-/tmp}/pad-docker-shim-$(id -u)"
        mkdir -p "$_SHIM"
        ln -sf "$PAD_DOCKER" "$_SHIM/docker"
        PATH="$_SHIM:$PATH"
    else
        PATH=$(dirname "$PAD_DOCKER"):$PATH
    fi
fi
export PATH

if ! command -v docker >/dev/null 2>&1 && command -v podman >/dev/null 2>&1; then
    _SHIM="${TMPDIR:-/tmp}/pad-docker-shim-$(id -u)"
    mkdir -p "$_SHIM"
    ln -sf "$(command -v podman)" "$_SHIM/docker"
    PATH="$_SHIM:$PATH"
fi

command -v docker >/dev/null 2>&1 || {
    echo "[box] docker is not installed. In the app: Emulate tab (Stern) ->" >&2
    echo "[box] \"Set up emulator...\" installs what a Mac needs." >&2
    exit 1
}

box_up() { docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; }

# The settings the rig reads, into the box. PAD_AUDIO_CTL is a path on THIS
# machine; its folder is mounted at /pad/ctl when the box starts.
box_env() {
    local v
    for v in PAD_SLOT PAD_LABEL PAD_VISIBLE PAD_HIDDEN PAD_AUDIO PAD_AUDIO_ASKED \
             PAD_TITLE PAD_GAMEKEYS SPK_GL SPK_FRESH; do
        [ -n "${!v:-}" ] && printf '%s\n' "-e" "$v=${!v}"
    done
    [ -n "${PAD_AUDIO_CTL:-}" ] && printf '%s\n' "-e" "PAD_AUDIO_CTL=/pad/ctl/$(basename "$PAD_AUDIO_CTL")"
}
box_exec() {            # <script> [args...]: as root, stdin passed through
    local e=() line
    while IFS= read -r line; do e+=("$line"); done < <(box_env)
    exec docker exec -i -u 0 ${e[@]+"${e[@]}"} "$NAME" bash "$RIG/$1" "${@:2}"
}

# ---- the questions with no box to ask ---------------------------------------
# Asked every two seconds by the tab, so answered before anything is built.
case "${1:-}" in
    status.sh)
        box_up && box_exec "$@"
        # status.sh's own idle answer (wsl=1 is "the rig answered")
        echo "wsl=1"; echo "running=0"; exit 0 ;;
    stop.sh|cancel.sh)
        if box_up; then
            docker exec -u 0 "$NAME" bash "$RIG/$1" "${@:2}"
            docker rm -f "$NAME" >/dev/null 2>&1
            exit 0
        fi
        # a start still building the image or starting the box: end that too
        pkill -f "spkbox.sh watch.sh" 2>/dev/null
        echo "nothing running"; exit 0 ;;
    ctl.sh)
        box_up && box_exec "$@"
        echo '{"ok": false, "error": "the emulator is not running"}'; exit 1 ;;
    playfield)
        box_up || { echo "[box] the emulator is not running" >&2; exit 1; }
        e=(); while IFS= read -r line; do e+=("$line"); done < <(box_env)
        # As pad, detached: a window on the box's screen. Its pipe to the
        # board is ctl.sh inside the box (appf.Rig off Windows).
        exec docker exec -d -u pad -e DISPLAY=:99 -e HOME=/home/pad \
            ${e[@]+"${e[@]}"} "$NAME" python3 "$RIG/spkpf.py" \
            --slot "${PAD_SLOT:-0}" --table "${2:?switches.json}" \
            ${PAD_AUDIO_CTL:+--audio-ctl "/pad/ctl/$(basename "$PAD_AUDIO_CTL")"} ;;
    --shell)
        box_up || { echo "[box] the emulator is not running" >&2; exit 1; }
        exec docker exec -it -u 0 "$NAME" bash ;;
esac

docker info >/dev/null 2>&1 || {
    echo "[box] docker / podman is installed but not running - start it (the Stern" >&2
    echo "[box] Emulate tab's \"Start Docker\" button), then Start again." >&2
    exit 1
}

# ---- the rig has to be somewhere the engine can see --------------------------
# The box mounts the app's folder at /pad/app: the rig, the rigs it borrows
# from (proc_emu, ap_emu, spike2_emu's pfweb) and the one file of the app it
# reads (the Spooky plugin's games.py: the update files' keys, which
# proc/prepare.py and spktitles.py take from there). Every Mac engine shares
# the home folder (colima: only that), and a bind mount of a folder it cannot
# see is an EMPTY folder, not an error (PAD-884). An installed app lives in
# /Applications, so those files are copied under home - a few MB, refreshed
# every start.
under_home() { case "$1" in "$HOME"/*) return 0 ;; esac; return 1; }
if [ "$(uname -s)" = Darwin ] && ! under_home "$APP"; then
    STAGE=${PAD_SPK_BOX_STAGE:-$HOME/Library/Application Support/pinball_decryptor/spooky_box}
    under_home "$STAGE" || {
        echo "[box] $STAGE is not under your home folder; point PAD_SPK_BOX_STAGE there" >&2
        exit 1; }
    T=$APP/tools
    [ -f "$T/spooky_emu/watch.sh" ] || {
        echo "[box] no rig at $T/spooky_emu" >&2; exit 1; }
    mkdir -p "$STAGE/tools/spike2_emu" "$STAGE/pinball_decryptor/plugins/spooky" || exit 1
    # over the top, never rm -rf first: a live box has this folder mounted
    cp -R "$T/spooky_emu" "$T/proc_emu" "$T/ap_emu" "$STAGE/tools"/ \
        && cp -R "$T/spike2_emu/pfweb.py" "$T/spike2_emu/pfpage" "$STAGE/tools/spike2_emu"/ \
        && cp "$APP/pinball_decryptor/plugins/spooky/games.py" \
              "$STAGE/pinball_decryptor/plugins/spooky"/ || {
        echo "[box] could not copy the emulator into $STAGE" >&2; exit 1; }
    [ -f "$T/rigboard.sh" ] && cp "$T/rigboard.sh" "$STAGE/tools"/
    APP=$STAGE
    SELF=$STAGE/tools/spooky_emu/docker
fi

# ---- the image: tagged by its sources, so a shipped fix arrives -------------
DKSUM=$(cat "$SELF/Dockerfile" "$SELF/entrypoint.sh" 2>/dev/null | cksum | cut -d' ' -f1)
IMAGE=${PAD_SPK_BOX_IMAGE:-pad-spooky-emu:c$DKSUM}
build() {
    echo "[box] building $IMAGE (the first time takes a few minutes)"
    BUILDKIT_PROGRESS=plain docker build --platform "$PLATFORM" -t "$IMAGE" "$SELF" 2>&1
    local rc=${PIPESTATUS[0]}
    if [ "$rc" != 0 ]; then
        echo "[box] the emulator container did not build (docker exit $rc); the lines above say why." >&2
        echo "[box] The Spooky games are Intel (x86-64) Linux programs: on Apple silicon the" >&2
        echo "[box] container engine must run those (Docker Desktop: Rosetta; colima does by default)." >&2
    fi
    return "$rc"
}
case "${1:-}" in
    --build) build; exit $? ;;
esac

# The Cache window with no game up: a throwaway box on the same volume.
if [ "${1:-}" = cache.sh ]; then
    box_up && box_exec "$@"
    docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "disk=0 0"; exit 0; }
    exec docker run --rm -i --platform "$PLATFORM" -u 0 -v "$APP:/pad/app:ro" \
        -v "$VOL:/var/tmp" --entrypoint /bin/bash "$IMAGE" "$RIG/cache.sh" "${@:2}"
fi

[ "${1:-}" = watch.sh ] || { echo "[box] unknown command: ${1:-}" >&2; exit 2; }
UPD=${2:-}
[ -f "$UPD" ] || { echo "watch.sh: no such update file: $UPD" >&2; exit 2; }
UPD_DIR=$(cd "$(dirname "$UPD")" && pwd)
UPD_BASE=$(basename "$UPD")

docker image inspect "$IMAGE" >/dev/null 2>&1 || build || exit 1
docker images pad-spooky-emu --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
    | grep -vx "$IMAGE" | while read -r old; do docker rmi "$old" >/dev/null 2>&1 || true; done

# One run at a time: a box left from an earlier run goes first.
docker rm -f "$NAME" >/dev/null 2>&1
docker volume create "$VOL" >/dev/null

# --privileged: run_game.sh makes mount, UTS and network namespaces, binds the
# build where the machine keeps it and brings the namespace's loopback up, and
# the board runs at real-time priority - root's work on Windows too (`wsl -u
# root`). The box is a process of the engine's Linux VM with loopback-only
# ports, so this opens nothing on the Mac.
ARGS=(-d --rm --name "$NAME" --platform "$PLATFORM" --privileged
      -p "127.0.0.1:$PORT:5900" -p "127.0.0.1:$AUDIO_PORT:$AUDIO_PORT"
      -e "PAD_AUDIO_PORT=$AUDIO_PORT" -e "PAD_VNC_PASSWD=$PAD_VNC_PASSWD"
      -v "$APP:/pad/app:ro" -v "$UPD_DIR:/pad/files:ro" -v "$VOL:/var/tmp")
if [ -n "${PAD_AUDIO_CTL:-}" ] && [ -d "$(dirname "$PAD_AUDIO_CTL")" ]; then
    ARGS+=(-v "$(dirname "$PAD_AUDIO_CTL"):/pad/ctl:ro")
fi
echo "[box] starting the emulator container"
docker run "${ARGS[@]}" "$IMAGE" >/dev/null || {
    echo "[box] the emulator container did not start (docker said so above)" >&2; exit 1; }
RATE=""
for _ in $(seq 1 120); do
    RATE=$(docker exec "$NAME" cat /run/pad-box.ready 2>/dev/null) && [ -n "$RATE" ] && break
    box_up || break
    RATE=""; sleep 0.5
done
[ -n "$RATE" ] || {
    echo "[box] the emulator container did not come up:" >&2
    docker logs "$NAME" 2>&1 | tail -n 20 | sed 's/^/[box]   /' >&2
    docker rm -f "$NAME" >/dev/null 2>&1; exit 1; }
# The engine shares only some folders, and one it does not is EMPTY in the box.
docker exec "$NAME" test -f "/pad/files/$UPD_BASE" || {
    echo "[box] the container engine cannot see $UPD_DIR, so the emulator cannot" >&2
    echo "[box] read the update file. Move it under your home folder (Downloads is" >&2
    echo "[box] fine) and Start again." >&2
    docker rm -f "$NAME" >/dev/null 2>&1; exit 4; }

echo "[box] the picture is at vnc://:$PAD_VNC_PASSWD@localhost:$PORT (Screen Sharing)"

# THE SPEAKER, on the Mac: the box's sound server serves its output raw on
# $AUDIO_PORT (entrypoint.sh); ffplay, from the ffmpeg the app already needs on
# macOS, plays it, and exits when the box is removed. Detached with its output
# to a file, because this script returns at attract and the app reads this
# script's output until every holder of it is gone.
if [ "${PAD_AUDIO:-0}" = 1 ] && [ "$(uname -s)" = Darwin ]; then
    if command -v ffplay >/dev/null 2>&1; then
        if ffplay -hide_banner -h demuxer=s16le 2>/dev/null | grep -q -- '-ch_layout'; then
            CH=(-ch_layout stereo)
        else
            CH=(-ac 2)
        fi
        LOG=${TMPDIR:-/tmp}/pad-spooky-audio.log
        nohup ffplay -hide_banner -loglevel error -nodisp -autoexit \
            -fflags nobuffer -flags low_delay -f s16le -ar "$RATE" "${CH[@]}" \
            "tcp://127.0.0.1:$AUDIO_PORT" < /dev/null > "$LOG" 2>&1 &
    else
        echo "[box] no ffplay on this Mac, so this run is silent (brew install ffmpeg)" >&2
    fi
fi

e=(); while IFS= read -r line; do e+=("$line"); done < <(box_env)
docker exec -u 0 ${e[@]+"${e[@]}"} "$NAME" bash "$RIG/watch.sh" "/pad/files/$UPD_BASE"
rc=$?
# A start that did not reach attract leaves nothing worth keeping up.
[ "$rc" = 0 ] || docker rm -f "$NAME" >/dev/null 2>&1
exit "$rc"
